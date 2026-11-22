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

from . import pickguard
from . import pmboxes
from . import naming

COMMAND = "SWStyle_UntrimSurface"
TITLE = "Untrim Surface"
LABEL = "Surface-Untrim"
ICON = "FEATURES_UNTRIM_SURFACE"
TYPES = ["All edges", "Internal edges", "External edges"]
EDGE_TYPES = ["Extend edges", "Connect endpoints"]
INFINITE = 1e99


# --------------------------------------------------------------------------- the geometry
def _on_surface(surface, wire):
    fix = Part.ShapeFix.Face(surface, 1e-6, True)
    fix.add(wire)
    fix.perform()
    return fix.face()


def _grown(surface, own, k, grow):
    """The face's own parameter range in direction k grown by grow on each side, kept inside the
    surface (a closed direction stays one turn)."""
    bounds = surface.bounds()
    lo, hi = own[k] - grow, own[k + 1] + grow
    periodic = surface.isUPeriodic() if k == 0 else surface.isVPeriodic()
    if periodic:
        period = (surface.UPeriod() if k == 0 else surface.VPeriod())
        if hi - lo > period:
            return own[k], own[k] + period
        return lo, hi
    if abs(bounds[k]) < INFINITE:
        lo = max(lo, bounds[k])
    if abs(bounds[k + 1]) < INFINITE:
        hi = min(hi, bounds[k + 1])
    return lo, hi


def _natural(face, distance, exclude=False):
    ""

    surface = face.Surface
    bounds = surface.bounds()
    own = face.ParameterRange
    out = []
    if exclude:
        d = distance if distance > 0 else 10.0
        for k in (0, 2):
            out += list(_grown(surface, own, k, (own[k + 1] - own[k]) * d / 100.0))
        return surface.toShape(*out)
    for k in (0, 2):
        lo, hi = bounds[k], bounds[k + 1]
        if abs(lo) > INFINITE or abs(hi) > INFINITE:
            a, b = own[k], own[k + 1]
            grow = (b - a) * distance / 100.0
            lo, hi = (a - grow if abs(lo) > INFINITE else lo), (b + grow if abs(hi) > INFINITE else hi)
        out += [lo, hi]
    return surface.toShape(*out)


def _infinite(face):
    return any(abs(b) > INFINITE for b in face.Surface.bounds())


def _coplanar(face, other):
    try:
        a, b = face.Surface, other.Surface
        if not (isinstance(a, Part.Plane) and isinstance(b, Part.Plane)):
            return False
        n, m = a.Axis, b.Axis
        return abs(abs(n.dot(m)) - 1.0) < 1e-7 and abs((b.Position - a.Position).dot(n)) < 1e-6
    except Exception:
        return False


def parent_face(source, face, depth=6):
    """The face this trimmed planar face was cut from: the bigger face on the same plane in the
    features the source was built from (a plane has no natural edges of its own; the parent
    surface's edges are where Untrim takes it back to)."""
    seen, todo, best = set(), [(source, 0)], None
    while todo:
        obj, d = todo.pop(0)
        if obj is None or obj.Name in seen or d > depth:
            continue
        seen.add(obj.Name)
        if obj is not source and obj.isDerivedFrom("Part::Feature") and \
                not obj.isDerivedFrom("Sketcher::SketchObject"):
            try:
                for f in Part.getShape(obj).Faces:
                    if _coplanar(face, f) and face.Area + 1e-6 < f.Area < 1e12 and \
                            f.isInside(face.CenterOfMass, 1e-6, True):
                        if best is None or f.Area > best.Area:
                            best = f
            except Exception as _fw_err:
                _fw_log("untrimsurface.parent", _fw_err)
        for x in getattr(obj, "OutList", []) or []:
            todo.append((x, d + 1))
    return best


def untrim(face, kind, distance=0.0, exclude=False, parent=None):
    holes = [w for w in face.Wires if not w.isSame(face.OuterWire)]
    if kind == "Internal edges":
        if not holes:
            raise RuntimeError("The face has no holes to fill")
        result = _on_surface(face.Surface, face.OuterWire)
    elif parent is not None and not exclude:
        result = _on_surface(face.Surface, parent.OuterWire)
        if result.Area < 0:
            wire = parent.OuterWire.copy()
            wire.reverse()
            result = _on_surface(face.Surface, wire)
        if kind == "External edges":
            for hole in holes:
                cut = result.cut(_on_surface(face.Surface, hole))
                if cut.Faces:
                    result = cut.Faces[0]
    else:
        result = _natural(face, distance, exclude)
        if kind == "External edges":
            for hole in holes:
                cut = result.cut(_on_surface(face.Surface, hole))
                if cut.Faces:
                    result = cut.Faces[0]
    if result.isNull() or not result.isValid() or abs(result.Area) < 1e-12:
        raise RuntimeError("The face could not be untrimmed")
    return result


def _rebuild(face, outer, holes):
    result = _on_surface(face.Surface, outer)
    if result.Area < 0:          # the wire ran the other way round: face the same way as before
        outer = outer.copy()
        outer.reverse()
        result = _on_surface(face.Surface, outer)
    for hole in holes:
        cut = result.cut(_on_surface(face.Surface, hole))
        if cut.Faces:
            result = cut.Faces[0]
    return result


def _chord(surface, a, b):
    """A curve on the surface straight across from a to b."""
    pts = []
    for i in range(13):
        p = a + (b - a) * (i / 12.0)
        u, v = surface.parameter(p)
        pts.append(surface.value(u, v))
    if isinstance(surface, Part.Plane):
        return Part.LineSegment(a, b).toShape()
    bs = Part.BSplineCurve()
    bs.interpolate(pts)
    return bs.toShape()


def _same(e, x):
    return e.isSame(x) or (abs(e.Length - x.Length) < 1e-7 and e.CenterOfMass.distanceToPoint(x.CenterOfMass) < 1e-7)


def untrim_edges(face, edges, kind, distance=0.0, exclude=False):
    """Edge Untrim Type for picked edges of the face."""
    outer = face.OuterWire
    holes = [w for w in face.Wires if not w.isSame(outer)]
    on_hole = [h for h in holes if any(_same(e, x) for e in edges for x in h.Edges)]
    on_outer = [e for e in edges if any(_same(e, x) for x in outer.Edges)]
    if not on_hole and not on_outer:
        raise RuntimeError("Pick edges of the face's own boundary")
    keep = [h for h in holes if h not in on_hole]
    if not on_outer:
        return _rebuild(face, outer, keep)
    if kind == "Connect endpoints":
        parts = []
        for x in outer.OrderedEdges:
            if any(_same(e, x) for e in on_outer):
                a, b = x.Vertexes[0].Point, x.Vertexes[-1].Point
                if (a - b).Length < 1e-7:
                    raise RuntimeError("A closed edge has no endpoints to connect")
                parts.append(_chord(face.Surface, a, b))
            else:
                parts.append(x)
        return _rebuild(face, Part.Wire(Part.__sortEdges__(parts)), keep)
    # Extend edges: grow across each picked side to the natural edge (Distance % where there is none)
    from .surfacefeatures import _side
    if len(outer.Edges) != 4:
        raise RuntimeError("Extend edges works on a four-sided face: try Connect endpoints")
    own = list(face.ParameterRange)
    bounds = face.Surface.bounds()
    span = [own[1] - own[0], own[1] - own[0], own[3] - own[2], own[3] - own[2]]
    for e in on_outer:
        k = _side(face, e)
        if k is None:
            raise RuntimeError("Extend edges: the edge does not lie on a side of the surface")
        if abs(bounds[k]) < INFINITE and not exclude:
            own[k] = bounds[k]
        elif exclude:
            j = k - k % 2
            lo, hi = _grown(face.Surface, list(face.ParameterRange), j, span[k] * (distance if distance > 0 else 10.0) / 100.0)
            own[k] = lo if k in (0, 2) else hi
        else:
            grow = span[k] * (distance if distance > 0 else 10.0) / 100.0
            own[k] = own[k] - grow if k in (0, 2) else own[k] + grow
    result = face.Surface.toShape(*own)
    for hole in keep:
        cut = result.cut(_on_surface(face.Surface, hole))
        if cut.Faces:
            result = cut.Faces[0]
    return result


class UntrimSurface:
    def __init__(self, obj):
        obj.addProperty("App::PropertyLinkSubGlobal", "Face", "Untrim Surface", "The trimmed surface face")
        obj.addProperty("App::PropertyEnumeration", "UntrimType", "Untrim Surface",
                        "All edges, only the holes (Internal) or only the outline (External)")
        obj.UntrimType = TYPES
        obj.addProperty("App::PropertyFloat", "Distance", "Untrim Surface",
                        "How far a surface with no natural edge reaches past the face, in % of the face's size")
        obj.addProperty("App::PropertyBool", "Merge", "Untrim Surface",
                        "Merge with original: the untrimmed face takes the picked face's place")
        obj.Merge = True
        _edge_props(obj)
        obj.Proxy = self

    def execute(self, obj):
        _edge_props(obj)
        edges = []
        if obj.Edges:
            source, subs = obj.Edges
            whole = Part.getShape(source)
            edges = [whole.getElement(x) for x in subs if x.startswith("Edge")]
        if edges:
            owners = [f for f in whole.Faces if any(_same(e, x) for e in edges for x in f.Edges)]
            if not owners:
                raise RuntimeError("Pick edges of a surface face")
            face = owners[0]
            new = untrim_edges(face, edges, obj.EdgeUntrimType, obj.Distance, obj.ExcludeParent)
        elif obj.Face is None or not obj.Face[1]:
            obj.Shape = Part.Shape()
            return
        else:
            source, subs = obj.Face
            sub = subs[0] if isinstance(subs, (list, tuple)) else subs
            whole = Part.getShape(source)
            face = whole.getElement(sub)
            parent = None
            if not obj.ExcludeParent and _infinite(face):
                parent = parent_face(source, face)
            new = untrim(face, obj.UntrimType, obj.Distance, obj.ExcludeParent, parent)
        if obj.Merge and len(whole.Faces) > 1:
            others = [f for f in whole.Faces if not f.isSame(face)]
            from . import sewtol
            shell = sewtol.sewn(others + [new], 1e-4)
            obj.Shape = shell
        else:
            obj.Shape = new

    def onDocumentRestored(self, obj):
        _edge_props(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _edge_props(obj):
    if "Edges" not in obj.PropertiesList:
        obj.addProperty("App::PropertyLinkSubGlobal", "Edges", "Untrim Surface",
                        "Picked edges of the face (Edge Untrim Type)")
    if "EdgeUntrimType" not in obj.PropertiesList:
        obj.addProperty("App::PropertyEnumeration", "EdgeUntrimType", "Untrim Surface",
                        "Extend edges, or Connect endpoints across the picked edges")
        obj.EdgeUntrimType = EDGE_TYPES
    if "ExcludeParent" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "ExcludeParent", "Untrim Surface",
                        "Exclude parent surfaces: grow the face only Distance % past its edges, not back "
                        "to the parent surface's natural edges")


def _source(obj):
    """The surface body the picks are on."""
    if obj.Edges:
        return obj.Edges[0]
    return obj.Face[0] if obj.Face is not None else None


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
            _fw_log("untrimsurface.py:286", _fw_err)
        return "Surface_ExtendFace"

    def claimChildren(self):
        obj = self.Object
        src = _source(obj) if "Edges" in obj.PropertiesList else (obj.Face[0] if obj.Face is not None else None)
        return [src] if obj.Merge and src is not None else []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
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
    """Selections (the face, Face Untrim Type, Distance %) and Options (Merge with original)."""

    def __init__(self, obj):
        self.obj = obj
        self.busy = False
        page = QtWidgets.QWidget()
        page.setWindowTitle("Selections")
        page.setProperty("swstyle_pm_title", TITLE)
        page.setProperty("swstyle_pm_icon", ICON)
        lay = QtWidgets.QVBoxLayout(page)
        self.box = QtWidgets.QListWidget()
        self.box.setObjectName("SWStyle_UntrimFace")
        self.box.setMaximumHeight(40)
        self.box.setToolTip("The trimmed surface face")
        pmboxes.mark(self.box, True)
        pmboxes.bind(self.box, lambda row: self._clear_pick(), self._clear_pick)
        lay.addWidget(self.box)
        _edge_props(obj)
        self.face_label = QtWidgets.QLabel("Face Untrim Type")
        lay.addWidget(self.face_label)
        self.types = {}
        group = QtWidgets.QButtonGroup(page)
        for name in TYPES:
            button = QtWidgets.QRadioButton(name)
            button.toggled.connect(self._changed)
            lay.addWidget(button)
            group.addButton(button)
            self.types[name] = button
        self.edge_label = QtWidgets.QLabel("Edge Untrim Type")
        lay.addWidget(self.edge_label)
        self.edge_types = {}
        egroup = QtWidgets.QButtonGroup(page)
        for name in EDGE_TYPES:
            button = QtWidgets.QRadioButton(name)
            button.setObjectName("SWStyle_Untrim_" + name.replace(" ", ""))
            button.toggled.connect(self._changed)
            lay.addWidget(button)
            egroup.addButton(button)
            self.edge_types[name] = button
        self._groups = (group, egroup)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Distance %"))
        self.distance = QtWidgets.QDoubleSpinBox()
        self.distance.setObjectName("SWStyle_UntrimDistance")
        self.distance.setRange(0.0, 1000.0)
        self.distance.setSuffix(" %")
        self.distance.setToolTip("How far a surface with no natural edge (a plane, the length of a cylinder) "
                                 "reaches past the face, in % of the face's size")
        self.distance.valueChanged.connect(self._changed)
        row.addWidget(self.distance)
        lay.addLayout(row)
        lay.addStretch(1)        # rows packed to the top, no blank band under the box (look audit AA2)
        options = QtWidgets.QWidget()
        options.setWindowTitle("Surface Untrim Options")
        olay = QtWidgets.QVBoxLayout(options)
        self.merge = QtWidgets.QCheckBox("Merge with original")
        self.merge.toggled.connect(self._changed)
        olay.addWidget(self.merge)
        self.exclude = QtWidgets.QCheckBox("Exclude parent surfaces")
        self.exclude.setObjectName("SWStyle_UntrimExcludeParent")
        self.exclude.setToolTip("Untrims or extends only Distance % past the face, without restoring the "
                                "parent surface it was trimmed from")
        self.exclude.toggled.connect(self._changed)
        olay.addWidget(self.exclude)
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        olay.addWidget(self.note)
        olay.addStretch(1)
        for w in (page, options):        # each group as tall as its rows (no share of the pane's spare height)
            w.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        self.form = [page, options]
        self._show()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _begin(self):
        doc = self.obj.Document
        if not doc.HasPendingTransaction:
            doc.openTransaction(TITLE)

    def _show(self):
        obj = self.obj
        self.busy = True
        self.box.clear()
        edges = bool(obj.Edges)
        if edges:
            for sub in obj.Edges[1]:
                self.box.addItem("%s.%s" % (obj.Edges[0].Label, sub))
        elif obj.Face is not None:
            subs = obj.Face[1]
            self.box.addItem("%s.%s" % (obj.Face[0].Label, subs[0] if subs else ""))
        for name, button in self.types.items():
            button.setChecked(name == obj.UntrimType)
            button.setVisible(not edges)
        for name, button in self.edge_types.items():
            button.setChecked(name == obj.EdgeUntrimType)
            button.setVisible(edges)
        self.face_label.setVisible(not edges)
        self.edge_label.setVisible(edges)
        self.distance.setValue(obj.Distance)
        self.merge.setChecked(obj.Merge)
        self.exclude.setChecked(obj.ExcludeParent)
        self.busy = False
        if "Invalid" in obj.State:
            self.note.setText(obj.getStatusString())
        elif obj.Face is None and not obj.Edges:
            self.note.setText("Pick the trimmed surface face, or edges of it.")
        else:
            self.note.setText("")
        self._show_source()

    def _show_source(self):
        obj = self.obj
        src = _source(obj)
        if src is not None and src.ViewObject is not None:
            src.ViewObject.Visibility = not obj.Merge

    def _changed(self, *args):
        if self.busy:
            return
        obj = self.obj
        kind = next((n for n, b in self.types.items() if b.isChecked()), obj.UntrimType)
        ekind = next((n for n, b in self.edge_types.items() if b.isChecked()), obj.EdgeUntrimType)
        values = (kind, ekind, self.distance.value(), self.merge.isChecked(), self.exclude.isChecked())
        if values == (obj.UntrimType, obj.EdgeUntrimType, obj.Distance, obj.Merge, obj.ExcludeParent):
            return
        self._begin()
        obj.UntrimType, obj.EdgeUntrimType, obj.Distance, obj.Merge, obj.ExcludeParent = values
        obj.Document.recompute()
        self._show()

    def addSelection(self, doc, name, sub, point):
        if pickguard.stale(self, self.obj):
            return
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
        if holder is None or holder is self.obj or not element.startswith(("Face", "Edge")):
            return
        self._begin()
        old = _source(self.obj)
        if element.startswith("Edge"):
            # edges of the face: Edge Untrim Type (a second pick takes an edge out)
            subs = list(self.obj.Edges[1]) if self.obj.Edges and self.obj.Edges[0] is holder else []
            if element in subs:
                subs.remove(element)
            else:
                subs.append(element)
            self.obj.Edges = (holder, subs) if subs else None
            self.obj.Face = None
        else:
            self.obj.Edges = None
            self.obj.Face = (holder, [element])
        if old is not None and old is not holder and old.ViewObject is not None:
            old.ViewObject.Visibility = True
        doc.recompute()
        self._show()

    def _clear_pick(self):
        if self.obj.Face is None and self.obj.Edges is None:
            return
        self._begin()
        old = _source(self.obj)
        self.obj.Edges = None
        self.obj.Face = None
        if old is not None and old.ViewObject is not None:
            old.ViewObject.Visibility = True
        self.obj.Document.recompute()
        self._show()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("untrimsurface.py:502", _fw_err)
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()

    def accept(self):
        obj = self.obj
        obj.Document.recompute()
        if obj.Shape.isNull() or "Invalid" in obj.State:
            self.note.setText(obj.getStatusString() if "Invalid" in obj.State else "Pick the trimmed surface face, or edges of it.")
            return False
        if obj.Document.HasPendingTransaction:
            obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        name = self.obj.Name
        source = _source(self.obj)
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("untrimsurface.py:524", _fw_err)
        if doc.HasPendingTransaction:
            doc.abortTransaction()
        doc.recompute()
        obj = doc.getObject(name)
        if obj is None:
            # a new one, gone again: its face's body shows as before
            if source is not None and source.ViewObject is not None:
                source.ViewObject.Visibility = True
        elif _source(obj) is not None and _source(obj).ViewObject is not None:
            _source(obj).ViewObject.Visibility = not obj.Merge
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()
        return True


# --------------------------------------------------------------------------- making
def make(doc=None, face=None, edit=True):
    """face: (object, "Face1") or None."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    doc.openTransaction(TITLE)
    obj = doc.addObject("Part::FeaturePython", "UntrimSurface")
    UntrimSurface(obj)
    if App.GuiUp and obj.ViewObject is not None:
        View(obj.ViewObject)
    obj.Label = naming.next_label(doc, LABEL)
    if face is not None:
        obj.Face = (face[0], [face[1]])
    doc.recompute()
    if edit and App.GuiUp:
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
    else:
        if obj.Merge and face is not None and face[0].ViewObject is not None:
            face[0].ViewObject.Visibility = False
        doc.commitTransaction()
    return obj


def _preselected():
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
            if element.startswith("Face"):
                return holder, element
    return None


class Command:
    def GetResources(self):
        return {"MenuText": TITLE, "ToolTip": "Grows a trimmed surface back to its natural edges, "
                "filling its holes, its outline or both.", "Pixmap": "Surface_ExtendFace"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        make(face=_preselected())


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Untrim Surface command not added (%s)\n" % error)
