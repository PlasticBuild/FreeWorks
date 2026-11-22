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

import math
import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, smflatten
from .smbaseflange import _box, _spin
from .smedgeflange import error_label
from .smunfold import _DeleteKey, _icon, _list

COMMAND = "SWStyle_SMRip"
TITLE = "Rip"
GROUP = "Rip"
DIRECTIONS = ("both walls", "first wall keeps the corner", "second wall keeps the corner")
V = App.Vector
NOT_CORNER = "Select an edge where two flat walls meet."


# ================================================================ geometry
def _plane(f):
    return f.Surface.TypeId == "Part::GeomPlane"


def _normal(f):
    u0, u1, v0, v1 = f.ParameterRange
    return f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)


def across(shape, face, reach=50.0):
    """The face on the other side of the wall from face: (face, wall thickness)."""
    n, c = _normal(face), face.CenterOfMass
    best = None
    for g in shape.Faces:
        if not _plane(g) or _normal(g).dot(n) > -1 + 1e-6:
            continue
        t = (c - g.CenterOfMass).dot(n)
        if t <= 1e-6 or t > reach:
            continue
        moved = g.copy()
        moved.translate(n * t)
        if face.common(moved).Area < 1e-6:
            continue
        if best is None or t < best[1]:
            best = (g, t)
    return best


def _slab(origin, d1, d2, d3, l1, l2, l3):
    p = [origin, origin + d2 * l2, origin + d2 * l2 + d3 * l3, origin + d3 * l3]
    return Part.Face(Part.makePolygon(p + [p[0]])).extrude(d1 * l1)


def tool(shape, edge, gap, direction=0):
    """What a rip along edge cuts away. direction 0: the slot on the corner's diagonal; 1: the first
    wall keeps the corner; 2: the second wall does."""
    faces = [f for f in shape.ancestorsOfType(edge, Part.Face) if _plane(f)]
    if len(faces) != 2 or edge.Curve.TypeId != "Part::GeomLine":
        raise ValueError(NOT_CORNER)
    f1, f2 = faces
    n1, n2 = _normal(f1), _normal(f2)
    w1, w2 = across(shape, f1), across(shape, f2)
    if w1 is None or w2 is None:
        raise ValueError(NOT_CORNER)
    t1, t2 = w1[1], w2[1]
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    u = (b - a).normalize()
    length = edge.Length
    mid = (a + b) * 0.5
    if shape.isInside(mid + n1 * 1e-3 - n2 * 1e-3, 1e-7, False):
        # an inside corner edge: work from the outside corner, along its whole length
        n1, n2 = n1 * -1, n2 * -1
        a = a + n1 * t1 + n2 * t2
        outer = next((e for e in shape.Edges if e.Curve.TypeId == "Part::GeomLine"
                      and abs(abs(e.tangentAt(e.FirstParameter).dot(u)) - 1) < 1e-9
                      and e.distToShape(Part.Vertex(a))[0] < 1e-6), None)
        if outer is not None:
            ends = sorted((v.Point for v in outer.Vertexes), key=lambda p: p.dot(u))
            a, length = ends[0], outer.Length
    p_out, p_in = a, a - n1 * t1 - n2 * t2
    big = 4 * (t1 + t2) + 4 * gap
    # the slot ends just past the inside corner, so that a floor under the corner is not cut
    e = min(t1, t2) * 0.05
    if direction == 0:
        w = (p_in - p_out).normalize()
        s = u.cross(w).normalize()
        return _slab(p_out - s * (gap / 2) - w * big, u, s, w, length, gap, (p_in - p_out).Length + big + e)
    keep, cut, tk, tc = (n1, n2, t1, t2) if direction == 1 else (n2, n1, t2, t1)
    q = a - keep * tk
    return _slab(q - keep * gap - cut * (tc + e), u, keep, cut, length, gap, tc + e + big)


def rip(shape, edges, gap, directions, rounds=()):
    """rounds: (edge point, rip position or None, angle, offset) for each round-wall rip."""
    out = shape
    for e, d in zip(edges, directions):
        out = out.cut(tool(shape, e, gap, d))
    for edge_point, ref, angle, offset in rounds:
        out = out.cut(round_tool(shape, edge_point, ref, gap, angle, offset))
    return out.removeSplitter()



ROUND = ("Part::GeomCylinder", "Part::GeomCone")


def _round_face(shape, p):
    """The cylindrical or conical face of shape whose edge passes through p, else None."""
    vp = Part.Vertex(p)
    best = None
    for e in shape.Edges:
        if e.Curve.TypeId == "Part::GeomLine":
            continue
        d = e.distToShape(vp)[0]
        if d > 1e-4:
            continue
        for f in shape.ancestorsOfType(e, Part.Face):
            if f.Surface.TypeId in ROUND and (best is None or d < best[0]):
                best = (d, f)
    return best[1] if best else None


def round_edge(shape, p):
    """True when p lies on an edge of a round (cylindrical / conical) wall of shape."""
    return _round_face(shape, p) is not None


def _axis(face):
    s = face.Surface
    axis = App.Vector(s.Axis).normalize()
    centre = App.Vector(s.Apex) if s.TypeId == "Part::GeomCone" else App.Vector(s.Center)
    return centre, axis


def round_tool(shape, edge_point, ref, gap, angle=0.0, offset=0.0):
    """What a rip on a round wall cuts away: a slot gap wide, in the half plane through the axis on
    ref's side, turned by angle (degrees) and offset (arc length at ref), over the round walls only."""
    face = _round_face(shape, edge_point)
    if face is None:
        raise ValueError("Select an edge of a cylindrical or conical wall.")
    centre, axis = _axis(face)
    walls = [f for f in shape.Faces if f.Surface.TypeId in ROUND
             and abs(abs(App.Vector(f.Surface.Axis).normalize().dot(axis)) - 1) < 1e-7
             and (_axis(f)[0] - centre).cross(axis).Length < 1e-6]
    ref = App.Vector(ref if ref is not None else edge_point)
    rel = ref - centre
    radial = rel - axis * rel.dot(axis)
    if radial.Length < 1e-9:
        raise ValueError("The rip position is on the axis: pick a point off it.")
    r_at = radial.Length
    turn = angle + (math.degrees(offset / r_at) if r_at > 1e-9 else 0.0)
    radial = App.Rotation(axis, turn).multVec(radial).normalize()
    # radial and axial reach of the round walls
    rs, zs = [], []
    for f in walls:
        for v in f.Vertexes:           # (not the centre of mass: on a full round face it is on the axis)
            q = v.Point - centre
            zs.append(q.dot(axis))
            rs.append((q - axis * q.dot(axis)).Length)
        for e in f.Edges:
            if e.Curve.TypeId != "Part::GeomLine" and hasattr(e.Curve, "Radius"):
                rs.append(e.Curve.Radius)
    r0, r1 = max(0.0, min(rs) - 1e-3), max(rs) + 1e-3
    z0, z1 = min(zs) - 1e-3, max(zs) + 1e-3
    side = axis.cross(radial).normalize()
    origin = centre + axis * z0 + radial * r0 - side * (gap / 2)
    return _slab(origin, axis, radial, side, z1 - z0, r1 - r0, gap)


def edge_at(shape, p):
    """The straight edge of shape through point p (as picked), else None."""
    vp = Part.Vertex(p)
    best = None
    for i, e in enumerate(shape.Edges, 1):
        if e.Curve.TypeId != "Part::GeomLine":
            continue
        d = e.distToShape(vp)[0]
        if d < 1e-4 and (best is None or d < best[0]):
            best = (d, "Edge%d" % i)
    return best[1] if best else None


# ================================================================ feature
_LAST = None        # the open Rip PropertyManager


class SWRip:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyStringList", "Edges", GROUP, "Edges to rip, as picked")
        add("App::PropertyVectorList", "EdgePoints", GROUP, "A point on each edge")
        add("App::PropertyIntegerList", "Directions", GROUP, "0: both walls, 1: first wall keeps the corner, 2: second")
        add("App::PropertyLength", "Gap", GROUP, "Rip gap")
        obj.Gap = 0.1
        _round_props(obj)
        obj.Proxy = self

    def onDocumentRestored(self, obj):
        _round_props(obj)

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Rip: needs a part to rip")
        _round_props(obj)
        from . import pointrefs        # the picked edges follow an edit before the rip
        pointrefs.follow(obj, base, "EdgePoints", "edge")
        pointrefs.follow(obj, base, "RoundEdgePoints", "anyedge")
        shape = base.Shape.copy()
        rounds = round_rips(obj)
        if not obj.EdgePoints and not rounds:
            obj.Shape = shape
            return
        edges = []
        for p in obj.EdgePoints:
            name = edge_at(shape, p)
            if name is None:
                raise ValueError("Rip: a picked edge is gone; edit the feature and pick it again")
            edges.append(shape.getElement(name))
        dirs = list(obj.Directions) + [0] * (len(edges) - len(obj.Directions))
        obj.Shape = rip(shape, edges, float(obj.Gap), dirs, rounds)

    def dumps(self):
        return None

    def loads(self, state):
        return None


ROUND_PROPS = (("App::PropertyVectorList", "RoundEdgePoints", "A point on the round wall's picked edge"),
               ("App::PropertyVectorList", "RoundPositions", "Rip Position of each round rip"),
               ("App::PropertyIntegerList", "RoundHasPosition", "1 when the round rip has its own Rip Position"),
               ("App::PropertyFloatList", "RoundAngles", "Angle of each round rip about the axis (degrees)"),
               ("App::PropertyFloatList", "RoundOffsets", "Offset of each round rip round the wall (mm)"))


def _round_props(obj):
    for kind, name, tip in ROUND_PROPS:
        if name not in obj.PropertiesList:
            obj.addProperty(kind, name, GROUP, tip)


def round_rips(obj):
    pts = list(getattr(obj, "RoundEdgePoints", []) or [])
    n = len(pts)
    pos = list(getattr(obj, "RoundPositions", []) or []) + [None] * n
    has = list(getattr(obj, "RoundHasPosition", []) or []) + [0] * n
    ang = list(getattr(obj, "RoundAngles", []) or []) + [0.0] * n
    off = list(getattr(obj, "RoundOffsets", []) or []) + [0.0] * n
    return [(pts[i], pos[i] if has[i] else None, float(ang[i]), float(off[i])) for i in range(n)]


def set_round_rips(obj, rows):
    """rows: [(edge point, position or None, angle, offset)]"""
    _round_props(obj)
    obj.RoundEdgePoints = [r[0] for r in rows]
    obj.RoundPositions = [r[1] if r[1] is not None else r[0] for r in rows]
    obj.RoundHasPosition = [1 if r[1] is not None else 0 for r in rows]
    obj.RoundAngles = [float(r[2]) for r in rows]
    obj.RoundOffsets = [float(r[3]) for r in rows]


def is_rip(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWRip"


class ViewProviderRip:
    ICON = "SheetMetal_AddJunction"

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return _icon(self.ICON)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + obj.Label)
        try:
            Gui.Control.showDialog(Panel(obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(body):
    doc = body.Document
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", "Rip")
    SWRip(obj)
    if App.GuiUp:
        ViewProviderRip(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, "Rip")
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smrip.py:338", _fw_err)
    return obj


# ================================================================ PropertyManager
class Panel:
    """The Rip PropertyManager."""
    HINT = "Select the edges to rip, or an edge of a cylindrical or conical wall."

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        box = _box("Rip Parameters")
        f = box.layout()
        self.edges = _list("SWSMRipEdges", "#ffd6ec", "Edges to rip", rows=4)
        f.addRow(self.edges)
        self.change = QtWidgets.QPushButton("Change Direction")
        self.change.setObjectName("SWSMRipChangeDirection")
        self.change.setToolTip("Change the direction of the selected rip: both walls, then one wall, then the other")
        self.change.clicked.connect(self.change_direction)
        f.addRow(self.change)
        self.gap = _spin("SWSMRipGap", float(obj.Gap), 0.001, 100.0, step=0.1)
        self.gap.setToolTip("Rip gap")
        f.addRow("Rip gap:", self.gap)

        self.round_box = QtWidgets.QGroupBox("Rip Position")
        self.round_box.setObjectName("SWSMRipPositionBox")
        rf = QtWidgets.QFormLayout(self.round_box)
        self.position = _list("SWSMRipPosition", "#d6ecff", "The point the rip goes through: a vertex or sketch point", rows=1)
        rf.addRow(self.position)
        self.angle = _spin("SWSMRipAngle", 0.0, -360.0, 360.0, suffix=" deg", step=5.0)
        self.angle.setToolTip("Turns the rip about the axis from the Rip Position")
        rf.addRow("Angle:", self.angle)
        self.offset = _spin("SWSMRipOffset", 0.0, -10000.0, 10000.0, step=1.0)
        self.offset.setToolTip("Moves the rip round the wall from the Rip Position (arc length)")
        rf.addRow("Offset:", self.offset)
        f.addRow(self.round_box)
        self.round_box.hide()
        self.error = error_label()
        f.addRow(self.error)
        box.setProperty("swstyle_pm_title", TITLE)
        box.setProperty("swstyle_pm_icon", "SheetMetal_AddJunction")
        self.form = [box]
        self.gap.valueChanged.connect(self._changed)
        self.angle.valueChanged.connect(self._round_changed)
        self.offset.valueChanged.connect(self._round_changed)
        self.edges.currentRowChanged.connect(self._show_round)
        self.keys = _DeleteKey(self)
        self.edges.installEventFilter(self.keys)
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def set_active(self, w):
        pass

    def _dirs(self):
        return list(self.obj.Directions) + [0] * (len(self.obj.Edges) - len(self.obj.Directions))

    def _fill(self):
        row = self.edges.currentRow()
        self.edges.blockSignals(True)
        self.edges.clear()
        for n, d in zip(self.obj.Edges, self._dirs()):
            self.edges.addItem(n if d == 0 else "%s (%s)" % (n, DIRECTIONS[d]))
        for i, r in enumerate(round_rips(self.obj), 1):
            self.edges.addItem("Round wall rip %d" % i)
        self.edges.blockSignals(False)
        if 0 <= row < self.edges.count():
            self.edges.setCurrentRow(row)
        self._show_round()

    def _round_row(self):
        """The index of the current row among the round rips, else -1."""
        k = self.edges.currentRow() - len(self.obj.Edges)
        return k if 0 <= k < len(round_rips(self.obj)) else -1

    def _show_round(self, *_a):
        k = self._round_row()
        self.round_box.setVisible(k >= 0)
        if k < 0:
            return
        pt, ref, ang, off = round_rips(self.obj)[k]
        self.position.clear()
        self.position.addItem("Point (%.2f, %.2f, %.2f)" % tuple(ref) if ref is not None else "Where the edge was picked")
        for spin, value in ((self.angle, ang), (self.offset, off)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def _round_changed(self, *_a):
        k = self._round_row()
        if k < 0:
            return
        rows = round_rips(self.obj)
        pt, ref, _ang, _off = rows[k]
        rows[k] = (pt, ref, self.angle.value(), self.offset.value())
        set_round_rips(self.obj, rows)
        self._apply()

    def set_position(self, point):
        k = self._round_row()
        if k < 0:
            rows = round_rips(self.obj)
            if not rows:
                return False
            k = len(rows) - 1
        rows = round_rips(self.obj)
        pt, _ref, ang, off = rows[k]
        rows[k] = (pt, App.Vector(point), ang, off)
        set_round_rips(self.obj, rows)
        self._apply()
        self.edges.setCurrentRow(len(self.obj.Edges) + k)
        return True

    def remove_current(self, w):
        row = self.edges.currentRow()
        if row < 0:
            return
        k = self._round_row()
        if k >= 0:
            rows = round_rips(self.obj)
            del rows[k]
            set_round_rips(self.obj, rows)
            self._apply()
            return
        names, points, dirs = list(self.obj.Edges), list(self.obj.EdgePoints), self._dirs()
        del names[row], points[row], dirs[row]
        self.obj.Edges, self.obj.EdgePoints, self.obj.Directions = names, points, dirs
        self._apply()

    def change_direction(self):
        if self._round_row() >= 0:
            self.angle.setValue((self.angle.value() + 180.0) % 360.0)      # the other side of the wall
            return
        row = self.edges.currentRow()
        if row < 0:
            row = self.edges.count() - 1
        if row < 0:
            return
        dirs = self._dirs()
        dirs[row] = (dirs[row] + 1) % 3
        self.obj.Directions = dirs
        self._apply()
        self.edges.setCurrentRow(row)

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        if sub.startswith("Edge"):
            at = App.Vector(*point) if point else None
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))
        elif sub.startswith("Vertex") and round_rips(self.obj):
            QtCore.QTimer.singleShot(0, lambda: self._picked_point(doc, name, sub))

    def _picked_point(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smrip.py:499", _fw_err)
        obj = App.getDocument(doc_name).getObject(name)
        if obj is None:
            return
        try:
            v = obj.Shape.getElement(sub)
            p = v.Point
            if obj.TypeId.startswith("Sketcher::"):
                p = obj.getGlobalPlacement().multVec(obj.Placement.inverse().multVec(p))
        except Exception:
            return
        self.set_position(p)

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smrip.py:516", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or picked.Shape.isNull():
            return
        edge = picked.Shape.getElement(sub)
        if at is None or edge.distToShape(Part.Vertex(at))[0] > 1e-4:
            at = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
        base = self.obj.BaseFeature.Shape
        if edge.Curve.TypeId != "Part::GeomLine" and round_edge(base, at):
            rows = round_rips(self.obj)
            rows.append((at, None, 0.0, 0.0))
            set_round_rips(self.obj, rows)
            self._apply()
            self.edges.setCurrentRow(self.edges.count() - 1)
            return
        ename = edge_at(base, at)
        if ename is None:
            self.error.setText(NOT_CORNER)
            self.error.show()
            return
        names, points, dirs = list(self.obj.Edges), list(self.obj.EdgePoints), self._dirs()
        if ename in names:
            i = names.index(ename)
            del names[i], points[i], dirs[i]
        else:
            names.append(ename)
            points.append(at)
            dirs.append(0)
        self.obj.Edges, self.obj.EdgePoints, self.obj.Directions = names, points, dirs
        self._apply()
        self.edges.setCurrentRow(self.edges.count() - 1)

    # ---------------------------------------------------------------- result
    def _changed(self, *_a):
        self.obj.Gap = self.gap.value()
        self._apply()

    def _apply(self):
        self.obj.touch()
        self.obj.Document.recompute()
        self._fill()
        self._report()

    def _report(self):
        if "Invalid" in self.obj.State:
            self.error.setText(self.obj.getStatusString())
        elif not self.obj.EdgePoints and not round_rips(self.obj):
            self.error.setText(self.HINT)
        else:
            self.error.setText("")
        self.error.setVisible(bool(self.error.text()))
        return not self.error.text()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smrip.py:576", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smrip.py:582", _fw_err)

    def accept(self):
        if not self._report():
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        base = self.obj.BaseFeature if self.new else None
        doc.abortTransaction()
        doc.recompute()
        if base is not None:
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smrip.py:600", _fw_err)
        self._close()
        return True


# ================================================================ command
def _part_body():
    """The active body when its last feature is a solid (sheet metal or a part still to convert)."""
    if App.ActiveDocument is None or smflatten.blocked():
        return None
    try:
        if Gui.Control.activeDialog():
            return None
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception as _fw_err:
        _fw_log("smrip.py:623", _fw_err)
        return None
    if body is None or body.Tip is None or body.Tip.Shape.isNull() or not body.Tip.Shape.Solids:
        return None
    return body


def start():
    body = _part_body()
    if body is None:
        return
    picked = [(o.Document.Name, o.Object.Name, sub, App.Vector(p)) for o in Gui.Selection.getSelectionEx()
              for sub, p in zip(o.SubElementNames, o.PickedPoints) if sub.startswith("Edge")]
    doc = body.Document
    doc.openTransaction(TITLE)
    try:
        obj = make(body)
        doc.recompute()
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    for doc_name, name, sub, at in picked:
        panel._picked(doc_name, name, sub, at)


class Command:
    def GetResources(self):
        return {"Pixmap": _icon("SheetMetal_AddJunction"), "MenuText": TITLE,
                "ToolTip": "Cuts a gap along an edge so the part can unfold."}

    def IsActive(self):
        return _part_body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
