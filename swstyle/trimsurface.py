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

V = App.Vector
COMMAND = "SWStyle_TrimSurface"
TITLE = "Trim Surface"
ICON = "FEATURES_TRIM_SURFACE"
TOL = 1e-6
PICK_TOL = 1e-3


# --------------------------------------------------------------------------- shapes
def _faces(obj):
    shape = Part.getShape(obj)
    return shape.Faces


def _size(shapes):
    box = None
    for shape in shapes:
        b = shape.BoundBox
        if not b.isValid():
            continue
        if box is None:
            box = App.BoundBox(b)
        else:
            box.add(b)
    return (box.DiagonalLength if box is not None else 100.0) * 2.0 + 10.0, box


def _grown(face, size, how):
    """Split all: the tool face carried on past its edges, Natural (on its own surface) or
    Linear (straight on from each edge), so it splits the targets right across."""
    if how == "Natural":
        try:
            u0, u1, v0, v1 = face.ParameterRange
            s = face.Surface
            if s.isUPeriodic():
                du = 0
            else:
                du = (u1 - u0)
            if s.isVPeriodic():
                dv = 0
            else:
                dv = (v1 - v0)
            grow = []
            if type(s).__name__ in ("Plane", "Cylinder", "Cone", "SurfaceOfExtrusion"):
                grow.append((size if du else 0, size if dv else 0))   # these run on for ever: reach past the targets
            grow += [(du * k, dv * k) for k in (4.0, 2.0, 1.0, 0.5)]
            # a closed surface (cylinder, cone, sphere, torus) runs on round its whole period:

            full_u = s.isUPeriodic() and (u1 - u0) < s.UPeriod() - 1e-9
            full_v = s.isVPeriodic() and (v1 - v0) < s.VPeriod() - 1e-9
            for gu, gv in grow:
                if type(s).__name__ in ("Cylinder", "Cone"):
                    gu = 0 if s.isUPeriodic() else gu
                lo_u, hi_u = (u0, u0 + s.UPeriod()) if full_u else (u0 - gu, u1 + gu)
                lo_v, hi_v = (v0, v0 + s.VPeriod()) if full_v else (v0 - gv, v1 + gv)
                try:
                    big = s.toShape(lo_u, hi_u, lo_v, hi_v)
                    if big.isValid():
                        return big
                except Exception:
                    continue
        except Exception as _fw_err:
            _fw_log("trimsurface.py:99", _fw_err)
    faces = [face]
    for edge in face.Edges:
        mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        u, v = face.Surface.parameter(mid)
        side = face.normalAt(u, v).cross(edge.tangentAt((edge.FirstParameter + edge.LastParameter) / 2.0))
        side.normalize()
        if face.isInside(mid + side * (edge.Length * 1e-3 + 1e-4), 1e-6, True):
            side = side * -1
        faces += edge.extrude(side * size).Faces
    return Part.makeShell(faces)


def tool_shape(tool, targets, split_all=True, how="Natural"):
    """The trimming tool as a shape big enough to cut the targets: a surface as it is (with Split
    all, carried on past its edges), a plane as a square face, a sketch's curves pushed both ways
    along its normal."""
    size, box = _size([Part.getShape(t) for t in targets])
    centre = box.Center if box is not None else V()
    kind = tool.TypeId
    if kind in ("App::Plane", "PartDesign::Plane", "Part::DatumPlane") or tool.isDerivedFrom("App::Plane"):
        placement = tool.getGlobalPlacement() if hasattr(tool, "getGlobalPlacement") else tool.Placement
        normal = placement.Rotation.multVec(V(0, 0, 1))
        origin = placement.Base
        # the square's centre: the targets' centre dropped onto the plane
        foot = centre - normal * (centre - origin).dot(normal)
        plane = Part.Plane(foot, normal)
        return plane.toShape(-size, size, -size, size)
    shape = Part.getShape(tool)
    if kind == "Sketcher::SketchObject" or (shape.Faces == [] and shape.Edges):
        placement = tool.getGlobalPlacement() if hasattr(tool, "getGlobalPlacement") else tool.Placement
        normal = placement.Rotation.multVec(V(0, 0, 1))
        edges = [e for e in shape.Edges if not getattr(e, "isConstruction", False)]
        wire = Part.Compound(edges)
        wire.translate(normal * -size)
        return wire.extrude(normal * (2 * size))
    if split_all and shape.Faces:
        try:
            return Part.makeCompound([_grown(f, size, how) for f in shape.Faces])
        except Exception:
            return shape
    return shape


def _middle(edge):
    return edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))


def _pieces(faces, cutters):
    """Faces grouped into pieces: two faces are in one piece when they share an edge that is
    not a cut line (does not lie on one of the cutters). Edges are matched by where they are,
    since faces split one at a time do not share edge objects."""
    def on_cut(point):
        vertex = Part.Vertex(point)
        return any(c.distToShape(vertex)[0] < 1e-5 for c in cutters)
    parent = list(range(len(faces)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = []          # (middle, length, face index)
    for i, face in enumerate(faces):
        for edge in face.Edges:
            middle, length = _middle(edge), edge.Length
            for point, other_length, j in seen:
                if j != i and abs(length - other_length) < 1e-6 and point.distanceToPoint(middle) < 1e-6 \
                        and not on_cut(middle):
                    parent[find(i)] = find(j)
            seen.append((middle, length, i))
    groups = {}
    for i in range(len(faces)):
        groups.setdefault(find(i), []).append(faces[i])
    return list(groups.values())


def split(targets, cutters):
    """[[faces of one piece], ...] of each target shape split by the cutters."""
    out = []
    for target in targets:
        others = [c for c in cutters if not c.isSame(target)]
        faces = []
        for face in target.Faces:
            if not others:
                faces.append(face)
                continue
            result, mapping = face.generalFuse(others, TOL)
            parts = [f for f in (mapping[0] if mapping else []) if f.ShapeType == "Face"]
            faces.extend(parts or [face])
        out.extend(_pieces(faces, others))
    return out


def _pickable(obj, on):
    """See-through pieces stay clickable while the page is open: selection through transparency
    (Options > Selection) would otherwise let the clicks pass through them."""
    try:
        from . import optionsextras2 as ox
    except Exception:
        ox = None
    key = (obj.Document.Name, obj.Name)
    if ox is not None:
        if on:
            ox.PICKABLE.add(key)
        else:
            ox.PICKABLE.discard(key)
        try:
            ox.apply_through(obj.Document)
        except Exception as _fw_err:
            _fw_log("trimsurface.py:209", _fw_err)
    if on and obj.ViewObject is not None and "Selectable" in obj.ViewObject.PropertiesList:
        obj.ViewObject.Selectable = True


def _empty():
    """Nothing kept: an empty compound, not a null shape (a null shape breaks anything that asks its type)."""
    return Part.makeCompound([])


def _holds(piece, point):
    vertex = Part.Vertex(point)
    return min(f.distToShape(vertex)[0] for f in piece) < PICK_TOL


def trim(targets, cutters, points, keep=True):
    """The kept pieces as one shape; (shape, all pieces)."""
    pieces = split(targets, cutters)
    chosen = [p for p in pieces if any(_holds(p, pt) for pt in points)]
    # a change earlier in the tree moved the surfaces (the crown raised): a picked point is on no

    lost = [pt for pt in points if not any(_holds(p, pt) for p in pieces)]
    if lost and pieces:
        try:
            box = Part.makeCompound([f for p in pieces for f in p]).BoundBox
            reach = 0.25 * box.DiagonalLength
            for pt in lost:
                vertex = Part.Vertex(pt)
                near = min(pieces, key=lambda p: min(f.distToShape(vertex)[0] for f in p))
                if near not in chosen and min(f.distToShape(vertex)[0] for f in near) < reach:
                    chosen.append(near)
        except Exception as _fw_err:
            _fw_log("trimsurface.py:241", _fw_err)
    kept = chosen if keep else [p for p in pieces if p not in chosen]
    faces = [f for p in kept for f in p]
    if not faces:
        return _empty(), pieces
    if len(faces) == 1:
        return faces[0], pieces
    shape = Part.makeCompound(faces)
    if len(faces) > 1:
        try:
            sewn = shape.copy()
            sewn.sewShape()
            if sewn.Shells:
                shells = sewn.Shells
                shape = shells[0] if len(shells) == 1 and not sewn.Faces[len(shells[0].Faces):] \
                    else Part.makeCompound(shells + [f for f in sewn.Faces if not any(f.isSame(g) for s in shells for g in s.Faces)])
        except Exception as _fw_err:
            _fw_log("trimsurface.py:258", _fw_err)
    return shape, pieces


# --------------------------------------------------------------------------- the feature
def _split_props(obj):
    """Surface Split Options (added to trims made before they existed)."""
    if "SplitAll" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "SplitAll", "Surface Split Options",
                        "Split all: the tool carries on past its edges to split the surfaces right across")
    if "SplitHow" not in obj.PropertiesList:
        obj.addProperty("App::PropertyEnumeration", "SplitHow", "Surface Split Options",
                        "Natural: on along the tool's own surface. Linear: straight on from its edges")
        obj.SplitHow = ["Natural", "Linear"]


class TrimSurface:
    def __init__(self, obj):
        obj.addProperty("App::PropertyEnumeration", "TrimType", "Trim Surface", "Standard: a tool trims the "
                        "surfaces. Mutual: the surfaces trim each other.")
        obj.TrimType = ["Standard", "Mutual"]
        obj.addProperty("App::PropertyLinkGlobal", "TrimmingTool", "Trim Surface",
                        "Standard: the surface, plane or sketch that trims")
        obj.addProperty("App::PropertyLinkListGlobal", "Surfaces", "Trim Surface",
                        "The surfaces trimmed (Mutual: the surfaces that trim each other)")
        obj.addProperty("App::PropertyEnumeration", "Selections", "Trim Surface", "Keep or remove the picked pieces")
        obj.Selections = ["Keep selections", "Remove selections"]
        obj.addProperty("App::PropertyVectorList", "Pieces", "Trim Surface", "A point on each picked piece")
        obj.addProperty("App::PropertyInteger", "PieceCount", "Trim Surface", "How many pieces the cut makes")
        obj.setEditorMode("PieceCount", 1)
        _split_props(obj)
        obj.Proxy = self

    def execute(self, obj):
        targets = list(obj.Surfaces or [])
        if not targets:
            obj.Shape = _empty()
            return
        shapes = [Part.getShape(t) for t in targets]
        if obj.TrimType == "Standard":
            if obj.TrimmingTool is None:
                obj.Shape = _empty()
                obj.PieceCount = 0
                return
            cutters = [tool_shape(obj.TrimmingTool, targets, getattr(obj, "SplitAll", False),
                                  getattr(obj, "SplitHow", "Natural"))]
        else:
            cutters = shapes
        shape, pieces = trim(shapes, cutters, list(obj.Pieces), obj.Selections == "Keep selections")
        obj.PieceCount = len(pieces)
        obj.Shape = shape

    def onDocumentRestored(self, obj):
        _split_props(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


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
                return icon         # a QIcon: FreeCAD reads a returned QPixmap as a QIcon
        except Exception as _fw_err:
            _fw_log("trimsurface.py:335", _fw_err)
        return ":/icons/booleans/Part_BooleanFragments.svg"

    def claimChildren(self):
        obj = self.Object
        out = list(obj.Surfaces or [])
        if obj.TrimType == "Standard" and obj.TrimmingTool is not None and \
                obj.TrimmingTool.TypeId not in ("App::Plane",):
            out.append(obj.TrimmingTool)
        return out

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
_open = {"panel": None}


def current():
    return _open["panel"]


class Panel:
    ""

    def __init__(self, obj, new=False):
        _open["panel"] = self
        self.obj = obj
        self.new = new
        self.busy = False
        self.shown = {}
        first = QtWidgets.QWidget()
        first.setWindowTitle("Trim Type")
        first.setProperty("swstyle_pm_title", TITLE)
        first.setProperty("swstyle_pm_icon", ICON)
        lay = QtWidgets.QVBoxLayout(first)
        self.standard = QtWidgets.QRadioButton("Standard")
        self.mutual = QtWidgets.QRadioButton("Mutual")
        self.standard.setChecked(obj.TrimType == "Standard")
        self.mutual.setChecked(obj.TrimType == "Mutual")
        self.standard.toggled.connect(self._type)
        lay.addWidget(self.standard)
        lay.addWidget(self.mutual)

        second = QtWidgets.QWidget()
        second.setWindowTitle("Selections")
        lay = QtWidgets.QVBoxLayout(second)
        self.tool_label = QtWidgets.QLabel("Trimming Tool")
        self.tool = QtWidgets.QListWidget()
        self.tool.setObjectName("SWStyle_TrimTool")
        self.tool.setMaximumHeight(36)
        self.tool.setToolTip("A surface, a plane or a sketch")
        self.surfaces_label = QtWidgets.QLabel("Trimming Surfaces")
        self.surfaces = QtWidgets.QListWidget()
        self.surfaces.setObjectName("SWStyle_TrimSurfaces")
        self.surfaces.setMaximumHeight(64)
        self.keep = QtWidgets.QRadioButton("Keep selections")
        self.remove = QtWidgets.QRadioButton("Remove selections")
        self.keep.setChecked(obj.Selections == "Keep selections")
        self.remove.setChecked(obj.Selections != "Keep selections")
        self.keep.toggled.connect(self._keep)
        self.pieces_label = QtWidgets.QLabel("Pieces to Keep")
        self.pieces = QtWidgets.QListWidget()
        self.pieces.setObjectName("SWStyle_TrimPieces")
        self.pieces.setMaximumHeight(64)
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        for w in (self.tool_label, self.tool, self.surfaces_label, self.surfaces, self.keep, self.remove,
                  self.pieces_label, self.pieces, self.note):
            lay.addWidget(w)
        for box in (self.tool, self.surfaces, self.pieces):
            box.installEventFilter(self._focus(box))
        third = QtWidgets.QWidget()
        third.setWindowTitle("Surface Split Options")
        lay3 = QtWidgets.QVBoxLayout(third)
        _split_props(obj)
        self.split_all = QtWidgets.QCheckBox("Split all")
        self.split_all.setObjectName("SWStyle_TrimSplitAll")
        self.split_all.setChecked(bool(obj.SplitAll))
        self.natural = QtWidgets.QRadioButton("Natural")
        self.natural.setObjectName("SWStyle_TrimNatural")
        self.linear = QtWidgets.QRadioButton("Linear")
        self.linear.setObjectName("SWStyle_TrimLinear")
        self._how = QtWidgets.QButtonGroup(third)
        self._how.addButton(self.natural)
        self._how.addButton(self.linear)
        (self.linear if obj.SplitHow == "Linear" else self.natural).setChecked(True)
        for w in (self.split_all, self.natural, self.linear):
            lay3.addWidget(w)
        self.split_all.toggled.connect(self._split)
        self.natural.toggled.connect(self._split)
        self.form = [first, second, third]
        self.active = self.tool if obj.TrimType == "Standard" and obj.TrimmingTool is None else (
            self.surfaces if obj.TrimType == "Mutual" and len(obj.Surfaces) < 2 else self.pieces)
        self._see_through()
        self._show()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _focus(self, box):
        panel = self

        class Filter(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if event.type() == QtCore.QEvent.FocusIn:
                    panel.active = box
                    panel._show()
                return False
        self._filters = getattr(self, "_filters", []) + [Filter()]
        return self._filters[-1]

    # what the page shows
    def _see_through(self):
        """While the page is open the surfaces show see-through, so removed pieces can be clicked."""
        for obj in list(self.obj.Surfaces or []) + ([self.obj.TrimmingTool] if self.obj.TrimmingTool else []):
            if obj.Name in self.shown or obj.ViewObject is None:
                continue
            vobj = obj.ViewObject
            self.shown[obj.Name] = (vobj.Visibility, getattr(vobj, "Transparency", 0))
            vobj.Visibility = True
            if hasattr(vobj, "Transparency"):
                vobj.Transparency = 75
            _pickable(obj, True)

    def _restore(self, hide):
        doc = self.obj.Document
        for name, (visible, transparency) in self.shown.items():
            obj = doc.getObject(name)
            if obj is None or obj.ViewObject is None:
                continue
            if hasattr(obj.ViewObject, "Transparency"):
                obj.ViewObject.Transparency = transparency
            obj.ViewObject.Visibility = False if hide else visible
            _pickable(obj, False)
        self.shown = {}

    def _show(self):
        obj = self.obj
        standard = obj.TrimType == "Standard"
        self.tool_label.setVisible(standard)
        self.tool.setVisible(standard)
        self.surfaces_label.setVisible(not standard)
        self.surfaces.setVisible(not standard)
        self.pieces_label.setText("Pieces to Keep" if obj.Selections == "Keep selections" else "Pieces to Remove")
        self.tool.clear()
        if obj.TrimmingTool is not None:
            self.tool.addItem(obj.TrimmingTool.Label)
        self.surfaces.clear()
        for s in obj.Surfaces or []:
            self.surfaces.addItem(s.Label)
        self.pieces.clear()
        for i, p in enumerate(obj.Pieces):
            self.pieces.addItem("Piece %d  (%.1f, %.1f, %.1f)" % (i + 1, p.x, p.y, p.z))
        for box in (self.tool, self.surfaces, self.pieces):
            pmboxes.mark(box, box is self.active)
        if standard and obj.TrimmingTool is None:
            text = "Pick the trimming tool: a surface, a plane or a sketch."
        elif standard and not obj.Surfaces:
            text = "Click the pieces of the surfaces to %s." % (
                "keep" if obj.Selections == "Keep selections" else "remove")
        elif not standard and len(obj.Surfaces) < 2:
            text = "Pick the surfaces that trim each other; then click the pieces."
        elif not obj.Pieces:
            text = "Click the pieces to %s (%d pieces)." % (
                "keep" if obj.Selections == "Keep selections" else "remove", obj.PieceCount)
        else:
            text = "%d pieces." % obj.PieceCount
        if "Invalid" in obj.State:
            text = obj.getStatusString()
        self.note.setText(text)

    def _recompute(self):
        self.obj.Document.recompute()
        self._see_through()
        self._show()

    def _begin(self):
        """An edit opened from the tree gets its Undo step at its first change (FreeCAD 1.1 keeps
        an empty step for a transaction opened and aborted with no change)."""
        doc = self.obj.Document
        if not doc.HasPendingTransaction:
            doc.openTransaction(TITLE)

    def _type(self, *args):
        self._begin()
        self.obj.TrimType = "Standard" if self.standard.isChecked() else "Mutual"
        if self.obj.TrimType == "Mutual" and self.obj.TrimmingTool is not None:

            tool = self.obj.TrimmingTool
            self.obj.TrimmingTool = None
            if tool.TypeId not in ("App::Plane", "Sketcher::SketchObject") and tool not in self.obj.Surfaces:
                self.obj.Surfaces = list(self.obj.Surfaces) + [tool]
        self.active = (self.surfaces if len(self.obj.Surfaces) < 2 else self.pieces) if \
            self.obj.TrimType == "Mutual" else (self.tool if self.obj.TrimmingTool is None else self.pieces)
        self._recompute()

    def _split(self, *args):
        self._begin()
        self.obj.SplitAll = self.split_all.isChecked()
        self.obj.SplitHow = "Linear" if self.linear.isChecked() else "Natural"
        self._recompute()

    def _keep(self, *args):
        self._begin()
        self.obj.Selections = "Keep selections" if self.keep.isChecked() else "Remove selections"
        self._recompute()

    # picks
    def addSelection(self, doc, name, sub, point):
        if doc != self.obj.Document.Name:
            return
        QtCore.QTimer.singleShot(0, lambda: self._picked(name, sub, point))

    def _holder(self, name, sub):
        doc = self.obj.Document
        holder = doc.getObject(name)
        for part in sub.split(".")[:-1]:
            found = doc.getObject(part)
            if found is not None:
                holder = found
        return holder

    def _picked(self, name, sub, point):
        if self.busy:
            return
        self.busy = True
        try:
            Gui.Selection.clearSelection()
            obj = self.obj
            holder = self._holder(name, sub)
            if holder is None:
                return
            element = sub.split(".")[-1]
            point = V(*point)
            standard = obj.TrimType == "Standard"
            surfaces = list(obj.Surfaces or [])
            self._begin()
            if standard and (self.active is self.tool or obj.TrimmingTool is None):
                # Standard: the first pick is the trimming tool
                if holder is obj or holder in surfaces or not _is_tool(holder):
                    return
                obj.TrimmingTool = holder
                self.active = self.pieces
            elif standard and holder is obj.TrimmingTool:
                return
            elif not element.startswith("Face"):
                return
            elif holder is not obj and holder not in surfaces:
                if not _is_surface(holder):
                    return
                obj.Surfaces = surfaces + [holder]
                if standard:

                    obj.Pieces = list(obj.Pieces) + [point]
                    self.active = self.pieces
            else:
                self._toggle(point)
            self._recompute()
        finally:
            self.busy = False

    def _cutters(self):
        obj = self.obj
        if obj.TrimType == "Standard":
            return [tool_shape(obj.TrimmingTool, obj.Surfaces, getattr(obj, "SplitAll", False),
                               getattr(obj, "SplitHow", "Natural"))] if obj.TrimmingTool is not None else []
        return [Part.getShape(s) for s in obj.Surfaces]

    def _toggle(self, point):
        """Adds the piece under point, or takes it off when it is picked already. In Standard, a
        surface with no piece left picked is dropped."""
        obj = self.obj
        points = list(obj.Pieces)
        pieces = split([Part.getShape(s) for s in obj.Surfaces], self._cutters())
        mine = [p for p in pieces if _holds(p, point)]
        same = [q for q in points if mine and _holds(mine[0], q)]
        if same:
            points = [q for q in points if q not in same]
        else:
            points.append(point)
        obj.Pieces = points
        if obj.TrimType == "Standard":
            keep = [s for s in obj.Surfaces
                    if any(Part.getShape(s).distToShape(Part.Vertex(q))[0] < PICK_TOL for q in points)]
            if len(keep) != len(obj.Surfaces):
                obj.Surfaces = keep

    # buttons
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        _open["panel"] = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("trimsurface.py:651", _fw_err)
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()

    def accept(self):
        obj = self.obj
        obj.Document.recompute()
        if obj.Shape.isNull() or not obj.Shape.Faces or not obj.Pieces or "Invalid" in obj.State:
            self.note.setText(obj.getStatusString() if "Invalid" in obj.State else
                              "Pick the tool, the surfaces and the pieces to keep or remove.")
            return False
        self._restore(hide=True)
        if obj.Document.HasPendingTransaction:
            obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        self._restore(hide=False)
        _open["panel"] = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("trimsurface.py:675", _fw_err)
        if doc.HasPendingTransaction:
            doc.abortTransaction()
        doc.recompute()
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()
        return True


# --------------------------------------------------------------------------- making
def _is_surface(obj):
    try:
        shape = Part.getShape(obj)
    except Exception as _fw_err:
        _fw_log("trimsurface.py:690", _fw_err)
        return False
    return not shape.isNull() and shape.Faces and not shape.Solids


def _is_tool(obj):
    return obj.TypeId in ("App::Plane", "PartDesign::Plane", "Sketcher::SketchObject") or _is_surface(obj)


def make(doc=None, tool=None, surfaces=(), pieces=(), mutual=False, keep=True, edit=True):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    doc.openTransaction(TITLE)
    obj = doc.addObject("Part::FeaturePython", "TrimSurface")
    TrimSurface(obj)
    if App.GuiUp and obj.ViewObject is not None:
        View(obj.ViewObject)
    obj.Label = naming.next_label(doc, "Surface-Trim") if hasattr(naming, "next_label") else "Surface-Trim1"
    obj.TrimType = "Mutual" if mutual else "Standard"
    obj.Selections = "Keep selections" if keep else "Remove selections"
    if tool is not None:
        obj.TrimmingTool = tool
    if surfaces:
        obj.Surfaces = list(surfaces)
    if pieces:
        obj.Pieces = list(pieces)
    doc.recompute()
    if edit and App.GuiUp:
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
    else:
        for o in list(obj.Surfaces) + ([obj.TrimmingTool] if obj.TrimmingTool else []):
            if o.ViewObject is not None and o.TypeId != "App::Plane":
                o.ViewObject.Visibility = False
        doc.commitTransaction()
    return obj


def _preselected():
    tool, surfaces = None, []
    for sel in Gui.Selection.getSelectionEx("", 0):
        obj = sel.Object
        doc = obj.Document
        for sub in sel.SubElementNames or [""]:
            holder = obj
            for part in sub.split(".")[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    holder = found
            if tool is None and _is_tool(holder):
                tool = holder
            elif _is_surface(holder) and holder not in surfaces and holder is not tool:
                surfaces.append(holder)
    return tool, surfaces


class Command:
    def GetResources(self):
        return {"MenuText": TITLE, "ToolTip": "Trims surfaces with a surface, plane or sketch, or with each other; "
                "keeps or removes the pieces you click.", "Pixmap": "Part_BooleanFragments"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        tool, surfaces = _preselected()
        make(tool=tool, surfaces=surfaces)


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Trim Surface command not added (%s)\n" % error)
