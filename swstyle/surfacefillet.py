# SPDX-License-Identifier: LGPL-2.1-or-later
""










_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming
from . import pmboxes

COMMAND = "SWStyle_SurfaceFillet"
TITLE = "Fillet"
LABEL = "Surface-Fillet"
ICON = "FEATURES_FILLET"
TYPES = ["Constant Size", "Face Fillet"]
KINDS = TYPES + ["Variable Size", "Full Round"]   # made on the Fillet page (surfacefilletpm), not the old one


# --------------------------------------------------------------------------- the geometry
def _shared(shell):
    return [e for e in shell.Edges if len(shell.ancestorsOfType(e, Part.Face)) == 2]


def _shell(faces, tolerance=1e-6):
    from . import sewtol
    return sewtol.sewn(faces, tolerance)


def _result(shape):
    shells = shape.Shells
    return shells[0] if len(shells) == 1 else shape


def constant(shape, edges, radius):
    if not edges:
        raise RuntimeError("Pick the edges to round")
    try:
        out = shape.makeFillet(radius, edges)
    except Exception as error:
        raise RuntimeError("The edges could not be rounded at this radius (%s)" % error)
    if out.isNull() or not out.isValid():
        raise RuntimeError("The edges could not be rounded at this radius")
    return _result(out)


def multi(shape, edges, radii):
    """Multi Radius Fillet on a surface: every edge its own radius, all in one OpenCascade fillet so
    the corners where they meet blend (the solid Multi Radius Fillet's way, multiradius.per_edge)."""
    if not edges:
        raise RuntimeError("Pick the edges to round")
    if min(radii) <= 0:
        raise RuntimeError("Radii must be more than zero.")
    from . import multiradius
    rows = []
    for e, r in zip(edges, radii):
        index = next((i for i, own in enumerate(shape.Edges, 1) if own.isSame(e)), None)
        if index is None:
            raise RuntimeError("An edge is no longer on the surface")
        rows.append((index, r, r))
    try:
        out = multiradius.per_edge(shape, "Fillet", rows)
    except Exception as error:
        raise RuntimeError("The edges could not be rounded at these radii (%s)" % error)
    return _result(out)


def variable(shape, edges, ends):
    """Variable Size Fillet on a surface: ends = [(radius at the edge's start, radius at its end)] for
    each edge (start: the edge's FirstParameter), the radius changing in a straight line between, all
    in one OpenCascade fillet."""
    if not edges:
        raise RuntimeError("Pick the edges to round")
    if min(min(a, b) for a, b in ends) <= 0:
        raise RuntimeError("Radii must be more than zero.")
    from . import multiradius
    rows = []
    for e, (a, b) in zip(edges, ends):
        index = next((i for i, own in enumerate(shape.Edges, 1) if own.isSame(e)), None)
        if index is None:
            raise RuntimeError("An edge is no longer on the surface")
        rows.append((index, a, b))
    try:
        out = multiradius.per_edge(shape, "Fillet", rows)
    except Exception as error:
        raise RuntimeError("The edges could not be rounded at these radii (%s)" % error)
    return _result(out)


def _flat(face):
    if not isinstance(face.Surface, Part.Plane):
        return None
    n = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
    return face.CenterOfMass, n


def full_round(shell, side1, center, side2):
    """A surface's center face replaced by a half round touching it and the two side faces; the sides are
    trimmed at the round. Flat faces running the same way (a rib, a slot wall)."""
    import numpy
    p1, s1 = _flat(side1) or (None, None); p2, s2 = _flat(side2) or (None, None); pc, nc = _flat(center) or (None, None)
    if s1 is None or s2 is None or nc is None:
        raise RuntimeError("Full round fillet here needs flat side and center faces")
    d = nc.cross(s1)
    if d.Length < 1e-6: raise RuntimeError("The center face must run across the side faces")
    d.normalize()
    if abs(s2.dot(d)) > 1e-6: raise RuntimeError("Full round fillet here needs the side faces to run the same way")
    # the round's side of each face: the sides face each other, the center faces the way the sides run off it
    def toward(n, p, target):
        return n if n.dot(target - p) > 0 else n * -1
    n1 = toward(s1, p1, p2); n2 = toward(s2, p2, p1)
    away = (p1 + p2) * 0.5
    ncc = toward(nc, pc, away)
    u = ncc.cross(d); u.normalize(); w = d.cross(u)
    two = lambda v: (v.dot(u), v.dot(w))
    rows = []
    for n, pt in ((n1, p1), (n2, p2), (ncc, pc)):
        a, b = two(n); rows.append((a, b, -1.0, a * two(pt)[0] + b * two(pt)[1]))
    m = numpy.array([[a, b, c] for a, b, c, _k in rows]); k = numpy.array([kk for *_x, kk in rows])
    cu, cw, r = numpy.linalg.solve(m, k)
    if r <= 1e-6: raise RuntimeError("Full round fillet: no round touches the three faces")
    centre = u * cu + w * cw
    ts = [v.Point.dot(d) for v in center.Vertexes]; tmin, tmax = min(ts), max(ts)
    c0 = centre + d * tmin
    t1, t2 = c0 - n1 * r, c0 - n2 * r
    def corner(na, pa):
        a1, b1 = two(na); a2, b2 = two(ncc)
        x, y = numpy.linalg.solve(numpy.array([[a1, b1], [a2, b2]]), numpy.array([a1 * two(pa)[0] + b1 * two(pa)[1], a2 * two(pc)[0] + b2 * two(pc)[1]]))
        return u * x + w * y + d * tmin
    k1, k2 = corner(n1, p1), corner(n2, p2)
    block = Part.Face(Part.makePolygon([t1, k1, k2, t2, t1])).extrude(d * (tmax - tmin))
    rod = Part.makeCylinder(r, tmax - tmin, c0, d)
    arc = rod.Faces[0].common(block).Faces
    keep = []
    for f in shell.Faces:
        if f.isSame(center): continue
        if f.isSame(side1) or f.isSame(side2):
            keep += f.cut(block).Faces
        else:
            keep.append(f)
    from . import sewtol
    out = sewtol.sewn(keep + arc, 1e-4)
    try:
        out = out.removeSplitter()
    except Exception as _fw_err:
        _fw_log("surfacefillet.py:full-round-refine", _fw_err)
    if out.isNull() or not out.isValid():
        raise RuntimeError("The full round could not be made on these faces")
    return _result(out)
def face_fillet(face1, face2, radius, reverse1=False, reverse2=False):
    """face1 and face2 joined by a round of radius."""
    shell = _shell([face1, face2], 1e-4)
    edges = _shared(shell)
    if not edges:
        _, pieces = face1.generalFuse([face2], 1e-6)
        one, two = [f for f in pieces[0] if f.ShapeType == "Face"], [f for f in pieces[1] if f.ShapeType == "Face"]
        if len(one) < 2 or len(two) < 2:
            raise RuntimeError("The two surfaces neither meet nor cross")
        one.sort(key=lambda f: -f.Area)
        two.sort(key=lambda f: -f.Area)
        shell = _shell([one[1] if reverse1 else one[0], two[1] if reverse2 else two[0]])
        edges = _shared(shell)
        if not edges:
            raise RuntimeError("The kept pieces do not meet")
    return constant(shell, edges, radius)


class SurfaceFillet:
    def __init__(self, obj):
        obj.addProperty("App::PropertyEnumeration", "FilletType", "Fillet", "Constant Size or Face Fillet")
        obj.FilletType = KINDS
        obj.addProperty("App::PropertyLength", "Radius", "Fillet", "The fillet's radius")
        obj.Radius = 5.0
        obj.addProperty("App::PropertyLinkSubListGlobal", "Edges", "Fillet", "Constant Size: the edges to round")
        obj.addProperty("App::PropertyLinkSubGlobal", "Face1", "Fillet", "Face Fillet: the first surface")
        obj.addProperty("App::PropertyLinkSubGlobal", "Face2", "Fillet", "Face Fillet: the second surface")
        obj.addProperty("App::PropertyBool", "Reverse1", "Fillet", "Face Fillet: keep the other side of the first surface")
        obj.addProperty("App::PropertyBool", "Reverse2", "Fillet", "Face Fillet: keep the other side of the second surface")
        _radii_prop(obj)
        obj.Proxy = self

    def execute(self, obj):
        r = obj.Radius.Value
        if obj.FilletType == "Full Round":
            links = [obj.Face1, getattr(obj, "CenterFace", None), obj.Face2]
            if any(l is None for l in links):
                obj.Shape = Part.Shape()
                return
            shape = Part.getShape(links[0][0])
            faces = []
            for l in links:
                sub = l[1][0] if isinstance(l[1], (list, tuple)) else l[1]
                faces.append(shape.getElement(sub))       # from the one shape: isSame finds them in it
            obj.Shape = full_round(shape, faces[0], faces[1], faces[2])
            return
        if obj.FilletType == "Variable Size":
            groups = {}
            for source, subs in obj.Edges or []:
                for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
                    groups.setdefault(source.Name, (source, []))[1].append(sub)
            ends = [float(x) for x in (getattr(obj, "EdgeEnds", None) or [])]
            count = sum(len(subs) for source, subs in groups.values())
            if not groups:
                obj.Shape = Part.Shape()
                return
            if len(ends) != 2 * count:
                ends = [r] * (2 * count)
            out = []
            at = 0
            for source, subs in groups.values():
                shape = Part.getShape(source)
                edges = [shape.getElement(sb) for sb in subs]
                pairs = [(ends[2 * k], ends[2 * k + 1]) for k in range(at, at + len(subs))]
                out.append(variable(shape, edges, pairs))
                at += len(subs)
            obj.Shape = out[0] if len(out) == 1 else Part.makeCompound(out)
            return
        if obj.FilletType == "Constant Size":
            groups = {}
            for source, subs in obj.Edges or []:
                for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
                    groups.setdefault(source.Name, (source, []))[1].append(sub)
            if not groups:
                obj.Shape = Part.Shape()
                return
            # Multi Radius Fillet: EdgeRadii holds a radius for each edge, in the order of Edges
            radii = [float(x) for x in (getattr(obj, "EdgeRadii", None) or [])]
            count = sum(len(subs) for source, subs in groups.values())
            per = radii if len(radii) == count and any(abs(x - r) > 1e-9 for x in radii) else None
            out = []
            at = 0
            for source, subs in groups.values():
                shape = Part.getShape(source)
                edges = [shape.getElement(s) for s in subs]
                if per is None:
                    out.append(constant(shape, edges, r))
                else:
                    out.append(multi(shape, edges, per[at:at + len(subs)]))
                at += len(subs)
            obj.Shape = out[0] if len(out) == 1 else Part.makeCompound(out)
            return
        if obj.Face1 is None or obj.Face2 is None:
            obj.Shape = Part.Shape()
            return
        faces = []
        for link in (obj.Face1, obj.Face2):
            subs = link[1]
            faces.append(Part.getShape(link[0]).getElement(subs[0] if isinstance(subs, (list, tuple)) else subs))
        obj.Shape = face_fillet(faces[0], faces[1], r, obj.Reverse1, obj.Reverse2)

    def onDocumentRestored(self, obj):
        _radii_prop(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _radii_prop(obj):
    """EdgeRadii: Multi Radius Fillet's radius for each edge (empty: every edge takes Radius).
    EdgeEnds: Variable Size's radius at the start and at the end of each edge, in the order of Edges."""
    if "EdgeRadii" not in obj.PropertiesList:
        obj.addProperty("App::PropertyFloatList", "EdgeRadii", "Fillet",
                        "Multi Radius Fillet: the radius of each edge, in the order of Edges (empty: Radius)")
    if "CenterFace" not in obj.PropertiesList:
        obj.addProperty("App::PropertyLinkSubGlobal", "CenterFace", "Fillet",
                        "Full Round: the center face (Face1 and Face2 are the side faces)")
    if "EdgeEnds" not in obj.PropertiesList:
        obj.addProperty("App::PropertyFloatList", "EdgeEnds", "Fillet",
                        "Variable Size: the radius at the start and at the end of each edge, in the order of Edges")
    try:
        if "FilletType" in obj.PropertiesList and "Full Round" not in obj.getEnumerationsOfProperty("FilletType"):
            kind = obj.FilletType
            obj.FilletType = KINDS
            obj.FilletType = kind
    except Exception as _fw_err:
        _fw_log("surfacefillet.py:kinds", _fw_err)


def sources(obj):
    out = []
    links = list(obj.Edges or []) if obj.FilletType == "Constant Size" else \
        [link for link in (obj.Face1, obj.Face2) if link is not None]
    for link in links:
        if link[0] not in out:
            out.append(link[0])
    return out


class View:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            icon = icons.family(ICON)
            if not icon.isNull():
                return icon         # a QIcon, never a QPixmap
        except Exception as _fw_err:
            _fw_log("surfacefillet.py:157", _fw_err)
        return "Part_Fillet"

    def claimChildren(self):
        return sources(self.Object)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        try:
            from . import surfacefilletpm
            if surfacefilletpm.enabled() and vobj.Object.FilletType == "Full Round":
                return surfacefilletpm.open_full_round(vobj.Object.Document, feature=vobj.Object)
            if surfacefilletpm.enabled() and vobj.Object.FilletType in ("Constant Size", "Variable Size") and vobj.Object.Edges \
                    and not getattr(surfacefilletpm, "_old_page", False):
                return surfacefilletpm.open_edit(vobj.Object)
        except Exception as _fw_err:
            _fw_log("surfacefillet.py:edit-full-pm", _fw_err)
        Gui.Control.showDialog(Panel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


# --------------------------------------------------------------------------- PropertyManager
class Panel:
    """Fillet Type, Items To Fillet (edges, or Face set 1 / Face set 2 with Reverse) and Fillet Parameters (Radius)."""

    def __init__(self, obj):
        self.obj = obj
        self.busy = False
        self.shown = {}
        page = QtWidgets.QWidget()
        page.setWindowTitle("Fillet Type")
        page.setProperty("swstyle_pm_title", TITLE)
        page.setProperty("swstyle_pm_icon", ICON)
        lay = QtWidgets.QVBoxLayout(page)
        self.types = {}
        for name in TYPES:
            button = QtWidgets.QRadioButton(name)
            button.toggled.connect(self._changed)
            lay.addWidget(button)
            self.types[name] = button
        items = QtWidgets.QWidget()
        items.setWindowTitle("Items To Fillet")
        ilay = QtWidgets.QVBoxLayout(items)
        self.boxes, self.reverse = {}, {}
        for key, label in (("Edges", "Edges"), ("Face1", "Face set 1"), ("Face2", "Face set 2")):
            caption = QtWidgets.QLabel(label)
            box = QtWidgets.QListWidget()
            box.setObjectName("SWStyle_SurfaceFillet%s" % key)
            box.setMaximumHeight(64 if key == "Edges" else 40)
            box.installEventFilter(self._focus(key))
            pmboxes.bind(box, remove=lambda row, k=key: self._drop(k, row))
            ilay.addWidget(caption)
            ilay.addWidget(box)
            self.boxes[key] = (caption, box)
            if key != "Edges":
                flip = QtWidgets.QCheckBox("Reverse")
                flip.setObjectName("SWStyle_SurfaceFilletReverse%s" % key[-1])
                flip.toggled.connect(self._changed)
                ilay.addWidget(flip)
                self.reverse[key] = flip

        params = QtWidgets.QWidget()
        params.setWindowTitle("Fillet Parameters")
        play = QtWidgets.QVBoxLayout(params)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Radius"))
        self.radius = QtWidgets.QDoubleSpinBox()
        self.radius.setObjectName("SWStyle_SurfaceFilletRadius")
        self.radius.setRange(0.001, 100000.0)
        self.radius.setDecimals(2)
        self.radius.setSuffix(" mm")
        self.radius.setKeyboardTracking(False)        # a typed value is taken once it is finished
        self.radius.valueChanged.connect(self._changed)
        row.addWidget(self.radius)
        play.addLayout(row)
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        ilay.addWidget(self.note)
        self.form = [page, items, params]
        self.active = "Edges" if obj.FilletType == "Constant Size" else ("Face1" if obj.Face1 is None else "Face2")
        self._show()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _focus(self, key):
        panel = self

        class Filter(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if event.type() == QtCore.QEvent.FocusIn:
                    panel.active = key
                    panel._show()
                return False
        self._filters = getattr(self, "_filters", []) + [Filter()]
        return self._filters[-1]

    def _begin(self):
        doc = self.obj.Document
        if not doc.HasPendingTransaction:
            doc.openTransaction(TITLE)

    def _hide_sources(self):
        """The surfaces being filleted are hidden while the fillet shows them; others show."""
        now = sources(self.obj) if not self.obj.Shape.isNull() else []
        for o in set(list(self.shown) + now):
            if o.ViewObject is None:
                continue
            if o in now and o not in self.shown:
                self.shown[o] = o.ViewObject.Visibility
                o.ViewObject.Visibility = False
            elif o not in now and o in self.shown:
                o.ViewObject.Visibility = self.shown.pop(o)

    def _restore(self):
        for o, was in self.shown.items():
            if o.ViewObject is not None:
                o.ViewObject.Visibility = was
        self.shown = {}

    def _show(self):
        obj = self.obj
        self.busy = True
        constant_size = obj.FilletType == "Constant Size"
        for name, button in self.types.items():
            button.setChecked(name == obj.FilletType)
        for key, (caption, box) in self.boxes.items():
            on = (key == "Edges") == constant_size
            caption.setVisible(on)
            box.setVisible(on)
            box.clear()
            value = getattr(obj, key)
            links = value if key == "Edges" else ([value] if value is not None else [])
            for source, subs in links or []:
                for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
                    box.addItem("%s.%s" % (source.Label, sub))
            pmboxes.mark(box, key == self.active)
        for key, flip in self.reverse.items():
            flip.setVisible(not constant_size)
            flip.setChecked(getattr(obj, "Reverse" + key[-1]))
        self.radius.setValue(obj.Radius.Value)
        self.busy = False
        if "Invalid" in obj.State:
            self.note.setText(obj.getStatusString())
        elif obj.Shape.isNull():
            self.note.setText("Pick the edges of a surface body to round." if constant_size else
                              "Pick a face of each of the two surfaces.")
        else:
            self.note.setText("")
        self._hide_sources()

    def _changed(self, *args):
        if self.busy:
            return
        obj = self.obj
        kind = next((n for n, b in self.types.items() if b.isChecked()), obj.FilletType)
        values = (kind, self.radius.value(), self.reverse["Face1"].isChecked(), self.reverse["Face2"].isChecked())
        if values == (obj.FilletType, obj.Radius.Value, obj.Reverse1, obj.Reverse2):
            return
        self._begin()
        if kind != obj.FilletType:
            self.active = "Edges" if kind == "Constant Size" else ("Face1" if obj.Face1 is None else "Face2")
        obj.FilletType, obj.Radius, obj.Reverse1, obj.Reverse2 = values
        obj.Document.recompute()
        self._show()

    def addSelection(self, doc, name, sub, point):
        if doc != self.obj.Document.Name:
            return
        QtCore.QTimer.singleShot(0, lambda: self._picked(name, sub))

    def _picked(self, name, sub):
        if self.busy:
            return
        doc = self.obj.Document
        holder = doc.getObject(name)
        for part in sub.split(".")[:-1]:
            found = doc.getObject(part)
            if found is not None:
                holder = found
        element = sub.split(".")[-1]
        Gui.Selection.clearSelection()
        if holder is None or holder is self.obj:
            return
        key = self.active
        if not element.startswith("Edge" if key == "Edges" else "Face"):
            return
        self._begin()
        if key == "Edges":
            pairs = [(s, e) for s, subs in (self.obj.Edges or []) for e in
                     (subs if isinstance(subs, (list, tuple)) else [subs])]
            pairs.remove((holder, element)) if (holder, element) in pairs else pairs.append((holder, element))
            self.obj.Edges = [(s, [e]) for s, e in pairs]
        else:
            setattr(self.obj, key, (holder, [element]))
            if key == "Face1" and self.obj.Face2 is None:
                self.active = "Face2"
        doc.recompute()
        self._show()

    def _drop(self, key, row):
        ""
        if self.busy or row < 0:
            return
        self._begin()
        if key == "Edges":
            pairs = [(s, e) for s, subs in (self.obj.Edges or []) for e in
                     (subs if isinstance(subs, (list, tuple)) else [subs])]
            if row >= len(pairs):
                return
            del pairs[row]
            self.obj.Edges = [(s, [e]) for s, e in pairs]
        else:
            setattr(self.obj, key, None)
            self.active = key
        self.obj.Document.recompute()
        self._show()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("surfacefillet.py:385", _fw_err)
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()

    def accept(self):
        obj = self.obj
        obj.Document.recompute()
        if obj.Shape.isNull() or "Invalid" in obj.State:
            self.note.setText(obj.getStatusString() if "Invalid" in obj.State else
                              "Pick what to round first.")
            return False
        self._hide_sources()
        self.shown = {}
        if obj.Document.HasPendingTransaction:
            obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        self._restore()
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("surfacefillet.py:409", _fw_err)
        if doc.HasPendingTransaction:
            doc.abortTransaction()
        doc.recompute()
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()
        return True


# --------------------------------------------------------------------------- making
def make(doc=None, edges=(), faces=(), edit=True):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    doc.openTransaction(TITLE)
    obj = doc.addObject("Part::FeaturePython", "SurfaceFillet")
    SurfaceFillet(obj)
    if App.GuiUp and obj.ViewObject is not None:
        View(obj.ViewObject)
    obj.Label = naming.next_label(doc, LABEL)
    if faces and not edges:
        obj.FilletType = "Face Fillet"
        obj.Face1 = (faces[0][0], [faces[0][1]])
        if len(faces) > 1:
            obj.Face2 = (faces[1][0], [faces[1][1]])
    elif edges:
        obj.Edges = [(o, [e]) for o, e in edges]
    doc.recompute()
    if edit and App.GuiUp:
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
    else:
        for o in sources(obj):
            if o.ViewObject is not None:
                o.ViewObject.Visibility = False
        doc.commitTransaction()
    return obj


def _is_surface(obj):
    try:
        shape = Part.getShape(obj)
    except Exception as _fw_err:
        _fw_log("surfacefillet.py:453", _fw_err)
        return False
    return not shape.isNull() and bool(shape.Faces) and not shape.Solids


def _preselected():
    edges, faces = [], []
    for sel in Gui.Selection.getSelectionEx("", 0):
        obj = sel.Object
        doc = obj.Document
        for sub in sel.SubElementNames:
            holder = obj
            for part in sub.split(".")[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    holder = found
            element = sub.split(".")[-1]
            if not _is_surface(holder):
                continue
            if element.startswith("Edge"):
                edges.append((holder, element))
            elif element.startswith("Face"):
                faces.append((holder, element))
    return edges, faces


def surfaces_picked():
    edges, faces = _preselected()
    return bool(edges or faces)


class Command:
    def GetResources(self):
        return {"MenuText": "Fillet (surfaces)", "Pixmap": "Part_Fillet",
                "ToolTip": "Rounds edges of a surface body, or between two surfaces."}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        edges, faces = _preselected()
        try:
            from . import surfacefilletpm
            if surfacefilletpm.enabled() and not faces and (edges or not _solid_model()):
                # surface edges picked, or a part of surfaces only: the Fillet PropertyManager itself,

                surfacefilletpm.open_new(edges=edges)
                return
        except Exception as _fw_err:
            _fw_log("surfacefillet.py:full-pm", _fw_err)
        if not edges and not faces and _solid_model():

            # FilletXpert, the four Fillet Types, Items To Fillet...; look audit AA3): with no surface
            # picked in a part that has a solid, that page opens. Surface edges or faces picked (or a
            # part of surfaces only) open the surface fillet, which rounds surface bodies.
            try:
                Gui.runCommand("PartDesign_Fillet", 0)
                return
            except Exception as _fw_err:
                _fw_log("surfacefillet.py:to-fillet", _fw_err)
        make(edges=edges, faces=faces)


def _solid_model():
    """True when the active part has a solid body with a tip the Fillet page can work on."""
    doc = App.ActiveDocument
    if doc is None:
        return False
    for obj in doc.Objects:
        if obj.TypeId == "PartDesign::Body" and obj.Tip is not None:
            try:
                if obj.Shape.Solids:
                    return True
            except Exception as _fw_err:
                _fw_log("surfacefillet.py:solid-model", _fw_err)
    return False


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Surface Fillet command not added (%s)\n" % error)
