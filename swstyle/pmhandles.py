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
from PySide import QtCore, QtWidgets

from . import instant3d
from . import pmevents

V = App.Vector
GREY = (0.45, 0.45, 0.45)
CONNECTOR = (0.1, 0.65, 0.2)


def _alive(w):
    try:
        w.objectName()
        return True
    except RuntimeError as _fw_err:
        _fw_log("pmhandles.py:56", _fw_err)
        return False


def _edited():
    ""

    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        if edit is not None:
            return edit.Object
        if gdoc is not None and Gui.Control.activeDialog():
            body = gdoc.ActiveView.getActiveObject("pdbody")
            tip = getattr(body, "Tip", None) if body is not None else None
            if tip is not None and tip.TypeId in ("PartDesign::Thickness", "PartDesign::Draft", "PartDesign::Revolution",
                                                   "PartDesign::Groove", "PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft"):
                return tip
        return None
    except Exception:
        return None


def _dialog():
    d = Gui.Control.activeDialog()
    return d if d else None


def _spin(view, name):
    w = view.findChild(QtWidgets.QAbstractSpinBox, name) if _alive(view) else None
    return w if w is not None and _alive(w) and w.isVisible() else None


def _set_spin(spin, value):
    if spin.inherits("Gui::QuantitySpinBox"):
        spin.setProperty("rawValue", float(value))
    else:
        spin.setValue(float(value))


def _spin_value(spin):
    if spin.inherits("Gui::QuantitySpinBox"):
        return float(spin.property("rawValue") or 0.0)
    return float(spin.value())


def _centre(shape):
    try:
        return V(shape.CenterOfMass)
    except Exception:
        return V(shape.BoundBox.Center)


def _profile(feature):
    sketch = feature.Profile[0] if isinstance(feature.Profile, (list, tuple)) else feature.Profile
    if sketch is None:
        return None, None, None
    import Part
    shape = sketch.Shape
    try:
        face = Part.Face(Part.Wire(shape.Wires[0])) if shape.Wires else None
    except Exception:
        face = None
    centre = face.CenterOfMass if face is not None else shape.BoundBox.Center
    normal = sketch.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
    return sketch, V(centre), normal


def _face(obj, sub):
    try:
        return obj.Shape.getElement(sub)
    except Exception as _fw_err:
        _fw_log("pmhandles.py:128", _fw_err)
        return None


def _normal(face):
    u, v = face.Surface.parameter(_centre(face))
    n = face.normalAt(u, v)
    if face.Orientation == "Reversed":
        n = n * -1
    return V(n)


# ------------------------------------------------------------------------------ targets
# Each returns (sink, base, direction, factor, value, unit) or None. factor = value units per mm of drag.

def revolve(view, feature, side):
    if feature.TypeId not in ("PartDesign::Revolution", "PartDesign::Groove"):
        return None
    kind = str(getattr(feature, "Type", "Angle"))
    if kind not in ("Angle", "TwoAngles", "0"):
        return None
    if side == 2 and kind != "TwoAngles":
        return None
    spin = _spin(view, "revolveAngle" if side == 1 else "revolveAngle2")
    if spin is None:
        return None
    sketch, centre, normal = _profile(feature)
    if sketch is None:
        return None
    base, axis = V(feature.Base), V(feature.Axis)
    if axis.Length < 1e-9:
        return None
    axis.normalize()
    r = centre - base
    r = r - axis * r.dot(axis)
    if r.Length < 1e-6:
        return None
    way = axis.cross(r)
    way.normalize()
    if feature.Reversed:
        way = way * -1
    if side == 2:
        way = way * -1
    return spin, centre, way, 180.0 / (math.pi * r.Length), _spin_value(spin), App.Units.Angle


def _dressup(kind):
    ""
    try:
        from . import filletpm
        panel = filletpm.current()
    except Exception as _fw_err:
        _fw_log("pmhandles.py:180", _fw_err)
        return None
    if panel is None or type(panel).__name__ != kind:
        return None
    return panel


def _panel_face(panel):
    """The first face picked on a dress-up page: (centre, outward normal) or None."""
    base = getattr(panel, "base", None)
    for sub in getattr(panel, "items", []) or []:
        if sub.startswith("Face") and base is not None:
            face = _face(base, sub)
            if face is not None:
                return _centre(face), _normal(face)
    return None


def shell(view, feature):
    panel = _dressup("ShellPanel")
    if panel is None:
        return None
    spin = getattr(panel, "thickness", None)
    if spin is None or not _alive(spin) or not spin.isVisible():
        return None
    got = _panel_face(panel)
    if got is None:
        base = getattr(panel, "base", None)
        if base is None or base.Shape.isNull():
            return None
        bb = base.Shape.BoundBox
        centre, normal = V(bb.Center.x, bb.Center.y, bb.ZMax), V(0, 0, 1)
    else:
        centre, normal = got
    outward = getattr(panel, "outward", None)
    direction = normal if (outward is not None and outward.isChecked()) else normal * -1
    return spin, centre, direction, 1.0, _spin_value(spin), App.Units.Length


def draft(view, feature):
    panel = _dressup("DraftPanel")
    if panel is None:
        return None
    spin = getattr(panel, "angle", None)
    if spin is None or not _alive(spin) or not spin.isVisible():
        return None
    got = _panel_face(panel)
    if got is None:
        return None
    centre, normal = got
    return spin, centre, normal, 1.0, _spin_value(spin), App.Units.Angle


def rib(view, feature):
    try:
        from . import rib as ribpm
        dialog = ribpm.current()
    except Exception:
        dialog = None
    if dialog is None:
        return None
    obj = getattr(dialog, "obj", None)
    spin = getattr(dialog, "thickness", None)
    if obj is None or spin is None or not _alive(spin) or not spin.isVisible():
        return None
    sketch = getattr(obj, "Sketch", None)
    if sketch is None or sketch.Shape.isNull() or not sketch.Shape.Edges:
        return None
    edge = sketch.Shape.Edges[0]
    mid = edge.valueAt(edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) / 2.0)
    normal = sketch.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
    return spin, V(mid), normal, 1.0, _spin_value(spin), App.Units.Length


def _pattern_panel():
    try:
        from . import patternpm
        return patternpm.current()
    except Exception:
        return None


def pattern(view, key):
    """Linear Pattern spacing (key dir1 / dir2) or Circular Pattern angle (dir1), at the last instance."""
    panel = _pattern_panel()
    if panel is None or not getattr(panel, "dirs", None):
        return None
    d = panel.dirs.get(key)
    if d is None or d.get("ref") is None or (key == "dir2" and not d.get("use")):
        return None
    try:
        from . import patterns
        seed = panel.seed_centre()
        count = max(int(d["count"]), 1)
        value = float(d["value"])
        if getattr(panel, "CIRCULAR", False):
            if key != "dir1":
                return None
            point, axis = patterns.axis_of(*d["ref"])
            if d.get("reverse"):
                axis = axis * -1
            r = seed - point
            r = r - axis * r.dot(axis)
            if r.Length < 1e-6:
                return None
            equal = bool(d.get("equal", True))
            if equal:
                step = value / count if abs(value - 360.0) < 1e-6 else (value / (count - 1) if count > 1 else 0.0)
            else:
                step = value
            last = step * (count - 1)
            rot = App.Rotation(axis, last)
            base = rot.multVec(r) + point
            way = axis.cross(rot.multVec(r))
            way.normalize()
            per_mm = 180.0 / (math.pi * r.Length)
            factor = per_mm if equal else per_mm / max(count - 1, 1)
            return (panel, key), base, way, factor, value, App.Units.Angle
        direction = patterns.direction_of(*d["ref"]) * (-1 if d.get("reverse") else 1)
        base = seed + direction * (value * (count - 1))
        return (panel, key), base, direction, 1.0 / max(count - 1, 1), value, App.Units.Length
    except Exception:
        return None


def hole(view, feature):
    try:
        from . import holespec
        dialog = holespec.active()
    except Exception:
        dialog = None
    hole_ = getattr(dialog, "hole", None) if dialog is not None else None
    depth = getattr(dialog, "depth", None) if dialog is not None else None
    if hole_ is None or depth is None or not _alive(depth) or not depth.isVisible():
        return None
    sketch = hole_.Profile[0] if isinstance(hole_.Profile, (list, tuple)) else hole_.Profile
    if sketch is None:
        return None
    normal = sketch.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
    pt = None
    try:
        shape = hole_.AddSubShape
        if not shape.isNull():
            shape = shape.copy()
            shape.Placement = hole_.Placement.multiply(shape.Placement)
            c = V(shape.BoundBox.Center)
            top = max(v.Point.dot(normal) for v in shape.Vertexes)
            pt = c + normal * (top - c.dot(normal))
    except Exception:
        pt = None
    if pt is None:
        try:
            g = sketch.Geometry[0]
            pt = sketch.getGlobalPlacement().multVec(V(g.X, g.Y, 0))
        except Exception:
            return None
    return depth, pt, normal * -1, 1.0, float(depth.value()), App.Units.Length


# ------------------------------------------------------------------------------ the handle
DRAG_EVENTS = (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick)


class PMHandle(instant3d._Instant3D):
    def _hook_name(self):
        return "pm.handle.%d" % id(self)

    """One drag arrow bound to a page field (or a pattern direction)."""

    def __init__(self, view, name, target):
        super().__init__()
        self.pm_view = view
        self.name = name
        self.target_fn = target
        self.sink = None            # the spin box, or (pattern panel, key)
        self.unit = App.Units.Length

    def _current(self):
        if not _alive(self.pm_view):
            return None
        feat = _edited()
        try:
            return self.target_fn(self.pm_view, feat) if feat is not None or self.name in ("shell", "draft", "rib", "hole") or self.name.startswith("pattern") else None
        except Exception:
            return None

    def poll(self):
        if self.drag is not None:
            return
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None
        got = self._current() if view is not None and hasattr(view, "getPoint") else None
        if got is None:
            self.clear()
            return
        sink, base, direction, factor, value, unit = got
        length = self._arrow_mm(view, base)
        key = (self.name, tuple(round(x, 6) for x in base), tuple(round(x, 6) for x in direction),
               round(length, 4), value, id(view))
        if key == self.key:
            return
        self.clear()
        self.sink = sink
        self.unit = unit
        self.target = (None, "Angle" if self.unit == App.Units.Angle else "Value", base, direction, factor)
        self.length = length
        self.key = key
        self._draw(view)
        if self.parts is not None:
            self.parts[1].diffuseColor.setValue(*GREY)

    def _set_hover(self, on):
        if self.parts is None or on == self.hover:
            return
        self.hover = on
        self.parts[1].diffuseColor.setValue(*(instant3d.HOVER if on else GREY))

    def _show_value(self, v):
        if self.parts is None:
            return
        self.parts[2].string.setValue(App.Units.Quantity(v, self.unit).UserString)

    def _read(self):
        if isinstance(self.sink, tuple):
            panel, key = self.sink
            return float(panel.dirs[key]["value"])
        return _spin_value(self.sink)

    def _write(self, v):
        if isinstance(self.sink, tuple):
            panel, key = self.sink
            panel.set_value(key, "value", float(v))
            box = getattr(panel, "boxes", {}).get(key)
            if box is not None and hasattr(box, "fill"):
                try:
                    box.fill(panel.dirs[key], panel.active)
                except Exception as _fw_err:
                    _fw_log("pmhandles.py:412", _fw_err)
            return
        if _alive(self.sink):
            _set_spin(self.sink, v)

    def press(self, pos):
        feat, prop, base, direction, factor = self.target
        t0 = instant3d._ray_param(self.view, pos, base, direction)
        if t0 is None:
            return False
        v0 = self._read()
        self.drag = {"t0": t0, "v0": v0, "doc": None, "shift": 0.0, "value": None,
                     "snapped": False, "made": None, "mid": False, "pos": pos}
        self._ruler_start()
        pmevents.hook(self._hook_name(), DRAG_EVENTS, self.filter.eventFilter)      # pkg98: the one dispatcher
        self._set_hover(True)
        self._show_value(v0)
        return True

    def value_at(self, pos):
        v = super().value_at(pos)
        if v is None:
            return None
        if self.unit == App.Units.Angle:
            v = min(max(round(v, 1), 0.1), 360.0)
        return v

    def _apply(self):
        if self.drag is None or self.drag["value"] is None:
            return
        self._write(self.drag["value"])

    def release(self):
        if self.drag is None:
            return
        value, v0, pos = self.drag.get("value"), self.drag.get("v0"), self.drag.get("pos")
        clicked = value is None or (v0 is not None and abs(value - v0) < 1e-9)
        if self.recompute_timer is not None:
            self.recompute_timer.stop()
        self._apply()
        self._ruler_clear()
        self.drag = None
        self.key = None
        self._show_value_clear()
        if clicked and pos is not None:
            # a click without a drag is a pick of what lies under the handle (Shell's handle sits on
            # the top face's centre before a face is picked: the click on that face was lost)
            QtCore.QTimer.singleShot(0, lambda p=pos: self._pick_under(p))

    def _pick_under(self, pos):
        try:
            info = self.view.getObjectInfo((int(round(pos[0])), int(round(pos[1]))))
        except Exception as _fw_err:
            _fw_log("pmhandles.py:pick", _fw_err)
            return
        if not info:
            return
        try:
            parent, subname = info.get("ParentObject"), info.get("SubName")
            if parent is not None and subname:
                name, sub = parent.Name, subname
            else:
                name, sub = info.get("Object"), info.get("Component", "")
            Gui.Selection.addSelection(info.get("Document"), name, sub, info.get("x", 0.0), info.get("y", 0.0),
                                       info.get("z", 0.0))
        except Exception as _fw_err:
            _fw_log("pmhandles.py:pick2", _fw_err)

    def cancel(self):
        if self.drag is None:
            return
        if self.recompute_timer is not None:
            self.recompute_timer.stop()
        self._write(self.drag["v0"])
        self._ruler_clear()
        self.drag = None
        self.key = None
        self.swallow = True
        if self.parts is not None:
            self.parts[2].string.setValue("")


# ------------------------------------------------------------------------------ loft connectors
def _local(sketch, point):
    pl = sketch.getGlobalPlacement() if hasattr(sketch, "getGlobalPlacement") else sketch.Placement
    return pl.inverse().multVec(V(point))


def _near(a, b, tol=1e-5):
    return (V(a) - V(b)).Length <= tol


def _reversed_copy(geo):
    """The same edge the other way round, where the sketcher allows it (lines; an arc is always
    counter-clockwise, so it cannot be turned)."""
    import Part
    if isinstance(geo, Part.LineSegment):
        g = Part.LineSegment(V(geo.EndPoint), V(geo.StartPoint))
        return g
    return None


def rotate_wire_start(sketch, point):
    """Make `point` (global) the start of the sketch's wire, as a loft connector dragged there asks:
    the edge leaving it comes first in the geometry (the wire starts at the first edge's start and
    runs its way), reversed where it ran the other way. The wire keeps its sense where the edge
    can be reversed; a connector on an arc that would need turning falls back to the edge entering
    the point, and the wire flips. Constraints are remapped (start/end swapped on a reversed line).
    Returns True when the sketch changed."""
    shape = sketch.Shape
    if shape.isNull() or not shape.Wires:
        return False
    p = _local(sketch, point)
    geos = list(sketch.Geometry)
    n = len(geos)
    if n < 2:
        return False
    ends = {}
    for i, g in enumerate(geos):
        if sketch.getConstruction(i) or not hasattr(g, "StartPoint"):
            continue
        ends[i] = (V(g.StartPoint), V(g.EndPoint))
    pl = sketch.getGlobalPlacement() if hasattr(sketch, "getGlobalPlacement") else sketch.Placement
    inv = pl.inverse()
    wire = None
    for w in shape.Wires:
        if any(_near(inv.multVec(v.Point), p) for v in w.Vertexes):
            wire = w
            break
    if wire is None:
        return False
    oe = wire.OrderedEdges
    ov = wire.OrderedVertexes
    j = next((k for k, v in enumerate(ov) if _near(inv.multVec(v.Point), p)), None)
    if j is None:
        return False
    if j == 0 and _near(ends.get(0, (V(1e9, 0, 0),))[0], p):
        return False                # already the start

    def geo_of(edge):
        vs = [inv.multVec(v.Point) for v in edge.Vertexes]
        if len(vs) < 2:
            return None
        for i, (a, b) in ends.items():
            if (_near(a, vs[0]) and _near(b, vs[1])) or (_near(a, vs[1]) and _near(b, vs[0])):
                return i
        return None

    leaving = oe[j] if j < len(oe) else None
    entering = oe[j - 1] if j > 0 else (oe[-1] if wire.isClosed() else None)
    plan = None
    for edge, leaves in ((leaving, True), (entering, False)):
        if edge is None:
            continue
        i = geo_of(edge)
        if i is None:
            continue
        a, b = ends[i]
        forward = _near(a, p)       # its own start is the point already
        if forward:
            plan = (i, None)
            break
        rev = _reversed_copy(geos[i])
        if rev is not None:
            plan = (i, rev)
            break
    if plan is None:
        return False
    first, rev = plan
    order = [first] + [k for k in range(n) if k != first]
    perm = {old: new for new, old in enumerate(order)}
    cons = list(sketch.Constraints)
    construction = [sketch.getConstruction(i) for i in range(n)]
    doc = sketch.Document
    doc.openTransaction("Loft connector")
    try:
        sketch.deleteAllGeometry()
        for old in order:
            g = rev if (old == first and rev is not None) else geos[old]
            sketch.addGeometry(g, construction[old])
        swapped = {first} if rev is not None else set()

        def pos(k, v):
            if k in swapped and v in (1, 2):
                return 3 - v
            return v
        driving, virtual = [], []
        for c in cons:
            for key in ("First", "Second", "Third"):
                old = getattr(c, key)
                if old is not None and old >= 0:
                    setattr(c, key + "Pos", pos(old, getattr(c, key + "Pos")))
                    setattr(c, key, perm[old])
            k = sketch.addConstraint(c)
            if not c.Driving:
                driving.append(k)
            if c.InVirtualSpace:
                virtual.append(k)
        for k in driving:
            sketch.setDriving(k, False)
        for k in virtual:
            sketch.setVirtualSpace(k, True)
        doc.recompute()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("Loft connector: %s\n" % error)
        return False
    doc.commitTransaction()
    return True


CONNECTOR_LINE = (0.12, 0.12, 0.12)
_MARKER = {}


def _connector_marker(n):
    """loftpm-1121: a round Coin marker, a disc n px across in a 16 x 16 bitmap (both sizes share the centre).
    The handle is a dark 13 px disc under a green 10 px one: a green handle with a dark rim; the green takes
    the hover colour under the pointer. Made once per size."""
    if n in _MARKER:
        return _MARKER[n]
    from pivy import coin
    w, c, r = 16, 7.5, n / 2.0
    rows = "".join("".join("x" if ((x - c) ** 2 + (y - c) ** 2) ** 0.5 <= r - 0.15 else " " for x in range(w))
                   for y in range(w))
    index = coin.SoMarkerSet.getNumDefinedMarkers()
    coin.SoMarkerSet.addMarker(index, coin.SbVec2s(w, w), rows, False, True)
    _MARKER[n] = index
    return index


class Connectors:
    def _hook_name(self):
        return "pm.connectors.%d" % id(self)

    """Loft: green lines joining the start points of the profiles, in order.
    An end can be dragged to another vertex of its profile: the profile's wire is rotated to start
    there (rotate_wire_start), so the loft pairs the vertices as placed. Escape puts it back."""

    SNAP_PX = 40

    def __init__(self):
        self.sep = None
        self.view = None
        self.key = None
        self.coords = None
        self.objs = []
        self.points = []
        self.widget = None
        self.filter = None
        self.drag = None
        self.hover = None
        self.swallow = False
        self.mat = None

    def poll(self):
        if self.drag is not None:
            return
        feat = _edited()
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None
        if feat is None or view is None or feat.TypeId not in ("PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft") \
                or not hasattr(view, "getSceneGraph"):
            self.clear()
            return
        points, objs = [], []
        for section in [feat.Profile] + list(feat.Sections or []):
            obj = section[0] if isinstance(section, (list, tuple)) else section
            if obj is None or obj.Shape.isNull() or not obj.Shape.Vertexes:
                continue
            points.append(V(obj.Shape.Vertexes[0].Point))
            objs.append(obj)
        key = (feat.Name, tuple((round(p.x, 4), round(p.y, 4), round(p.z, 4)) for p in points), id(view))
        if key == self.key:
            return
        self.clear()
        if len(points) < 2:
            return
        from pivy import coin
        root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
        light = coin.SoLightModel()
        light.model.setValue(coin.SoLightModel.BASE_COLOR)
        # loftpm-1121: the connector is a thin dark line through round green handles with a dark rim, one
        # on each profile (Loft video); the handles are round marker bitmaps of a fixed size
        line_mat = coin.SoMaterial()
        line_mat.diffuseColor.setValue(*CONNECTOR_LINE)
        line_style = coin.SoDrawStyle()
        line_style.lineWidth.setValue(1.5)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(points), [[float(p.x), float(p.y), float(p.z)] for p in points])
        line = coin.SoLineSet()
        line.numVertices.setValues(0, 1, [len(points)])
        rims = coin.SoMarkerSet()
        rims.numPoints.setValue(len(points))
        rims.markerIndex.setValue(_connector_marker(13))
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*CONNECTOR)
        dots = coin.SoMarkerSet()
        dots.numPoints.setValue(len(points))
        dots.markerIndex.setValue(_connector_marker(10))
        for node in (pick, light, line_mat, line_style, coords, line, rims, mat, dots):
            root.addChild(node)
        view.getSceneGraph().addChild(root)
        self.sep, self.view, self.key, self.coords, self.mat = root, view, key, coords, mat
        self.objs, self.points = objs, points
        self._hook()

    # ---------------------------------------------------------------- the pointer
    def _hook(self):
        widget = instant3d._viewport()
        if widget is None or widget is self.widget:
            return
        self._unhook()
        if self.filter is None:
            self.filter = instant3d._Filter(self)
        widget.installEventFilter(self.filter)
        widget.setMouseTracking(True)
        if widget.parentWidget() is not None:
            widget.parentWidget().installEventFilter(self.filter)
        self.widget = widget

    def _unhook(self):
        if self.widget is not None:
            try:
                self.widget.removeEventFilter(self.filter)
                if self.widget.parentWidget() is not None:
                    self.widget.parentWidget().removeEventFilter(self.filter)
            except Exception as _fw_err:
                _fw_log("pmhandles.py:689", _fw_err)
        self.widget = None

    coin_pos = instant3d._Instant3D.coin_pos

    def _screen(self, p):
        try:
            s = self.view.getPointOnScreen(p)
            return float(s[0]), float(s[1])
        except Exception:
            return None

    def over_end(self, pos):
        """The index of the connector end under the pointer, or None."""
        if self.sep is None:
            return None
        best, best_d = None, instant3d.HIT_PX + 1
        for i, p in enumerate(self.points):
            s = self._screen(p)
            if s is None:
                continue
            d = math.hypot(s[0] - pos[0], s[1] - pos[1])
            if d < best_d:
                best, best_d = i, d
        return best

    over_arrow = lambda self, pos: self.over_end(pos) is not None

    def _set_hover(self, on):
        if self.mat is None or on == self.hover:
            return
        self.hover = on
        self.mat.diffuseColor.setValue(*(instant3d.HOVER if on else CONNECTOR))

    def on_event(self, event):
        t = event.type()
        QE = QtCore.QEvent
        if t == QE.ShortcutOverride and self.drag is not None:
            event.accept()
            return True
        if t == QE.KeyPress:
            if self.drag is None:
                return False
            if event.key() == QtCore.Qt.Key_Escape:
                self.cancel()
            return True
        if not hasattr(event, "button"):
            return False
        if t == QE.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            if self.swallow:
                self.swallow = False
            pos = self.coin_pos(event)
            i = self.over_end(pos) if self.drag is None else None
            if i is not None:
                return self.press(i, pos)
        elif t == QE.MouseMove:
            pos = self.coin_pos(event)
            if self.drag is not None:
                self.move(pos)
                return True
            self._set_hover(self.over_end(pos) is not None)
        elif t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton and self.drag is not None:
            self.release()
            return True
        elif t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton and self.swallow:
            self.swallow = False
            return True
        elif t == QE.MouseButtonDblClick and self.drag is not None:
            return True
        return False

    # ---------------------------------------------------------------- the drag
    def vertices(self, i):
        """The vertices of profile i the connector may snap to (global)."""
        try:
            return [V(v.Point) for v in self.objs[i].Shape.Vertexes]
        except Exception:
            return []

    def nearest(self, i, pos):
        best, best_d = None, self.SNAP_PX
        for v in self.vertices(i):
            s = self._screen(v)
            if s is None:
                continue
            d = math.hypot(s[0] - pos[0], s[1] - pos[1])
            if d < best_d:
                best, best_d = v, d
        return best

    def press(self, i, pos):
        self.drag = {"i": i, "at": self.points[i], "to": None}
        pmevents.hook(self._hook_name(), DRAG_EVENTS, self.filter.eventFilter)
        self._set_hover(True)
        return True

    def _put(self, p):
        if self.coords is not None:
            self.coords.point.set1Value(self.drag["i"], float(p.x), float(p.y), float(p.z))

    def move(self, pos):
        if self.drag is None:
            return
        v = self.nearest(self.drag["i"], pos)
        self.drag["to"] = v
        self._put(v if v is not None else self.drag["at"])

    def release(self):
        if self.drag is None:
            return
        pmevents.unhook(self._hook_name())
        d, self.drag = self.drag, None
        to = d["to"]
        self._set_hover(False)
        if to is None or _near(to, d["at"], 1e-4):
            self._put(d["at"])
            return
        obj = self.objs[d["i"]]
        if not rotate_wire_start(obj, to):
            self._put(d["at"])
            return
        self.key = None             # the next poll redraws from the new start points

    def cancel(self):
        if self.drag is None:
            return
        pmevents.unhook(self._hook_name())
        self._put(self.drag["at"])
        self.drag = None
        self._set_hover(False)
        self.swallow = True

    def clear(self):
        if self.drag is not None:
            self.cancel()
        if self.sep is not None and self.view is not None:
            try:
                self.view.getSceneGraph().removeChild(self.sep)
            except Exception as _fw_err:
                _fw_log("pmhandles.py:828", _fw_err)
        self._unhook()
        self.sep = self.view = self.key = self.coords = self.mat = None
        self.objs, self.points, self.hover = [], [], None

    def stop(self):
        self.clear()


class HandleSet(QtCore.QObject):
    """Every handle of one task view; polled together."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.handles = [
            PMHandle(view, "revolve1", lambda v, f: revolve(v, f, 1)),
            PMHandle(view, "revolve2", lambda v, f: revolve(v, f, 2)),
            PMHandle(view, "shell", shell),
            PMHandle(view, "draft", draft),
            PMHandle(view, "rib", rib),
            PMHandle(view, "pattern-dir1", lambda v, f: pattern(v, "dir1")),
            PMHandle(view, "pattern-dir2", lambda v, f: pattern(v, "dir2")),
            PMHandle(view, "hole", hole),
        ]
        self.connectors = Connectors()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(150)
        view.destroyed.connect(self.stop)

    def poll(self):
        if not _alive(self.view) or not self.view.isVisible():
            for h in self.handles:
                h.clear()
            self.connectors.clear()
            return
        for h in self.handles:
            try:
                h.poll()
            except Exception as _fw_err:
                _fw_log("pmhandles.py:869", _fw_err)
        try:
            self.connectors.poll()
        except Exception as _fw_err:
            _fw_log("pmhandles.py:873", _fw_err)

    def stop(self, *args):
        try:
            self.timer.stop()
        except Exception as _fw_err:
            _fw_log("pmhandles.py:879", _fw_err)
        for h in self.handles:
            try:
                h.stop()
            except Exception as _fw_err:
                _fw_log("pmhandles.py:884", _fw_err)
        self.connectors.stop()


_sets = {}


def install(view):
    if id(view) in _sets and _alive(_sets[id(view)].view):
        return
    _sets[id(view)] = HandleSet(view)


def dragging():
    """The page handle being dragged now, else None: Esc then cancels the drag, not the page."""
    for s in list(_sets.values()):
        for h in s.handles:
            if getattr(h, "drag", None) is not None:
                return h
    return None


def esc_cancels_drag(event):
    """For a page's Esc filter: True (and the drag is put back on the key press) when a handle is being dragged."""
    try:
        h = dragging()
        if h is None:
            return False
        if event.type() == QtCore.QEvent.KeyPress:
            h.cancel()
        else:
            event.accept()      # the shortcut override: no Esc shortcut runs (it closed the page)
        return True
    except Exception as _fw_err:
        _fw_log("pmhandles.py:esc", _fw_err)
        return False


def active():
    """The handles drawn right now (for checks)."""
    out = []
    for s in _sets.values():
        for h in s.handles:
            if h.sep is not None:
                out.append(h)
    return out
