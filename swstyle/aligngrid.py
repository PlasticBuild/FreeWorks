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

import json
import math

import FreeCAD as App
from . import geomkeep

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/AlignGrid"
BASE = "GridOriginBase"
UNDEF = -2000
_TINY = 1e-9


def _v(x, y):
    return App.Vector(x, y, 0)


def frame(origin, angle):
    """The new axes in the sketch's present coordinates: origin (x, y) and the X axis turned by
    angle degrees."""
    return App.Placement(_v(origin[0], origin[1]), App.Rotation(App.Vector(0, 0, 1), angle))


def _offset_name(sketch):
    return "Placement" if getattr(sketch, "MapMode", "Deactivated") == "Deactivated" else "AttachmentOffset"


def base_of(sketch):
    """Where the sketch's axes were before the first Align Grid/Origin."""
    if BASE in sketch.PropertiesList:
        return sketch.getPropertyByName(BASE)
    return getattr(sketch, _offset_name(sketch))


def _keep_base(sketch):
    if BASE not in sketch.PropertiesList:
        here = getattr(sketch, _offset_name(sketch))
        sketch.addProperty("App::PropertyPlacement", BASE, "Sketch",
                           "Where the sketch's axes were before Align Grid/Origin (Reset goes back here)")
        sketch.setEditorMode(BASE, 2)
        setattr(sketch, BASE, here)


def _turn(placement):
    """The turn of placement about the sketch normal, in degrees."""
    r = placement.Rotation
    angle = math.degrees(r.Angle)
    return angle if r.Axis.z >= 0 else -angle


class _Builder:
    """Collects the helper geometry and the extra relations one alignment needs."""

    def __init__(self, sketch, inverse, size):
        self.sketch = sketch
        self.inverse = inverse
        self.size = size
        self.first = sketch.GeometryCount
        self.new = []           # (geometry, construction)
        self.extra = []
        self.axes = None
        self.far = [None, None]
        self.placement = inverse.inverse()
        self.old_box = _box(sketch)

    def add(self, geo):
        self.new.append(geo)
        return self.first + len(self.new) - 1

    def old_axes(self):
        """The old X and Y axes, locked construction lines from the old origin."""
        if self.axes is None:
            o = self.inverse.multVec(_v(0, 0))
            x = self.add(_line(o, self.inverse.multVec(_v(self.size, 0))))
            y = self.add(_line(o, self.inverse.multVec(_v(0, self.size))))
            self.extra += [_C("Block", x), _C("Block", y)]
            self.axes = (x, y)
        return self.axes

    def ref(self, geo, pos):
        """(geo, pos) with the old origin and axes standing in for the sketch's own."""
        if geo == -1:
            return (self.old_axes()[0], 1) if pos == 1 else (self.old_axes()[0], pos)
        if geo == -2:
            return self.old_axes()[1], pos
        return geo, pos

    def point(self, geo, pos):
        """A point of the moved geometry, in the new coordinates."""
        if geo >= self.first:
            g = self.new[geo - self.first]
            return g.StartPoint if pos == 1 else g.EndPoint
        return self.inverse.multVec(self.sketch.getPoint(geo, pos))

    def wall(self, a, axis):
        """A construction line from point a across the old axis (along the old Y axis for axis 0),
        reaching a locked line far outside the sketch so it never shrinks to nothing."""
        if self.far[axis] is None:
            lo, hi = self.old_box
            if axis == 0:
                p, q = _v(lo.x - self.size, lo.y - self.size), _v(hi.x + self.size, lo.y - self.size)
            else:
                p, q = _v(lo.x - self.size, lo.y - self.size), _v(lo.x - self.size, hi.y + self.size)
            line = self.add(_line(self.inverse.multVec(p), self.inverse.multVec(q)))
            self.extra.append(_C("Block", line))
            self.far[axis] = line
        start = self.point(*a)
        old = self.placement.multVec(start)
        lo = self.old_box[0]
        end = _v(old.x, lo.y - self.size) if axis == 0 else _v(lo.x - self.size, old.y)
        line = self.add(_line(start, self.inverse.multVec(end)))
        self.extra += [_C("Coincident", line, 1, a[0], a[1]),
                       _C("Parallel", line, self.old_axes()[1 - axis]),
                       _C("PointOnObject", line, 2, self.far[axis])]
        return line


def _box(sketch):
    """The sketch's extent in its present coordinates: (low corner, high corner)."""
    lo, hi = _v(0, 0), _v(0, 0)
    for g in sketch.Geometry:
        try:
            box = g.toShape().BoundBox
        except Exception as _fw_err:
            _fw_log("aligngrid.py:157", _fw_err)
            continue
        lo = _v(min(lo.x, box.XMin), min(lo.y, box.YMin))
        hi = _v(max(hi.x, box.XMax), max(hi.y, box.YMax))
    return lo, hi


def _line(a, b):
    import Part
    if (b - a).Length < 1e-7:
        b = a + App.Vector(1e-3, 0, 0)
    return Part.LineSegment(a, b)


def _C(*args):
    import Sketcher
    return Sketcher.Constraint(*args)


def _like(old, new):
    new.Name = old.Name
    try:
        new.Driving = old.Driving
    except Exception as _fw_err:
        _fw_log("aligngrid.py:179", _fw_err)
    try:
        new.IsActive = old.IsActive
    except Exception as _fw_err:
        _fw_log("aligngrid.py:183", _fw_err)
    return new


def _uses_axes(c):
    return any(x in (-1, -2) for x in (c.First, c.Second, c.Third))


def _origin_bound(c):
    """A point's distance from the origin along X or Y."""
    return c.Type in ("DistanceX", "DistanceY") and c.Second == UNDEF and c.FirstPos != 0


def _axis_bound(c):
    """Whether a relation means something about the sketch's own X/Y directions."""
    if c.Type in ("Horizontal", "Vertical", "DistanceX", "DistanceY"):
        return True
    return c.Type == "Angle" and c.Second == UNDEF


def align(sketch, placement):
    """Moves the sketch's axes to placement (given in the sketch's present coordinates); the
    entities stay where they are. Returns how many relations were rewritten."""
    if placement.Base.Length < _TINY and abs(placement.Rotation.Angle) < _TINY:
        return 0
    _keep_base(sketch)
    inverse = placement.inverse()
    turned = abs(math.remainder(_turn(placement), 360.0)) > 1e-9
    box = sketch.Shape.BoundBox if not sketch.Shape.isNull() else None
    size = max(10.0, (box.DiagonalLength if box and box.isValid() else 0) + placement.Base.Length)
    b = _Builder(sketch, inverse, size)
    matrix = inverse.toMatrix()
    geos = []
    for g in geomkeep.read(sketch):
        g = g.clone()
        g.transform(matrix)
        geos.append(g)
    old = list(sketch.Constraints)
    out = []
    changed = 0
    for c in old:
        if not (_uses_axes(c) or _origin_bound(c) or (turned and _axis_bound(c))):
            out.append(c)
            continue
        changed += 1
        out.append(_rewrite(c, b, turned))
    expressions = [(path, text) for path, text in sketch.ExpressionEngine if path.startswith(".Constraints.")]
    offset = _offset_name(sketch)
    setattr(sketch, offset, getattr(sketch, offset).multiply(placement))
    sketch.Geometry = geos
    for geo in b.new:
        sketch.addGeometry(geo, True)
    # Block needs the geometry's blocked flag, which only addConstraint sets
    sketch.Constraints = out + [c for c in b.extra if c.Type != "Block"]
    blocks = [c for c in b.extra if c.Type == "Block"]
    if blocks:
        sketch.addConstraint(blocks)
    hidden = list(range(len(out), len(sketch.Constraints)))
    if hidden:
        try:
            sketch.setVirtualSpace(hidden, True)    # the helpers' own relations stay out of sight
        except Exception as _fw_err:
            _fw_log("aligngrid.py:245", _fw_err)
    kept = dict(sketch.ExpressionEngine)
    for path, text in expressions:
        if path not in kept:
            try:
                sketch.setExpression(path[1:], text)
            except Exception as _fw_err:
                _fw_log("aligngrid.py:252", _fw_err)
    sketch.solve()
    return changed


def _rewrite(c, b, turned):
    t = c.Type
    if t in ("Horizontal", "Vertical") and turned:
        axis = 0 if t == "Horizontal" else 1
        if c.Second == UNDEF:
            return _like(c, _C("Parallel", c.First, b.old_axes()[axis]))
        # two points level with each other: no distance across the axis between them
        a, z = b.ref(c.First, c.FirstPos), b.ref(c.Second, c.SecondPos)
        return _like(c, _C("PointOnObject", z[0], z[1], b.wall(a, 1 - axis)))
    if t in ("DistanceX", "DistanceY") and turned:
        axis = 0 if t == "DistanceX" else 1
        if c.Second == UNDEF and c.FirstPos == 0:
            a, z = (c.First, 1), (c.First, 2)
        elif c.Second == UNDEF:
            a, z = b.ref(-1, 1), (c.First, c.FirstPos)
        else:
            a, z = b.ref(c.First, c.FirstPos), b.ref(c.Second, c.SecondPos)
        wall = b.wall(a, axis)
        if abs(c.Value) < 1e-9:
            return _like(c, _C("PointOnObject", z[0], z[1], wall))
        return _like(c, _C("Distance", z[0], z[1], wall, abs(c.Value)))
    if t == "Angle" and c.Second == UNDEF and turned:
        return _like(c, _C("Angle", b.old_axes()[0], c.First, c.Value))
    if t in ("DistanceX", "DistanceY") and c.Second == UNDEF and c.FirstPos != 0:
        # a point's distance from the origin: from the old origin
        o = b.ref(-1, 1)
        return _like(c, _C(t, o[0], o[1], c.First, c.FirstPos, c.Value))
    # any other relation to the origin or the axes: the old ones stand in
    new = c
    f = b.ref(c.First, c.FirstPos)
    new.First, new.FirstPos = f
    if c.Second != UNDEF:
        s = b.ref(c.Second, c.SecondPos)
        new.Second, new.SecondPos = s
    if c.Third != UNDEF:
        th = b.ref(c.Third, c.ThirdPos)
        new.Third, new.ThirdPos = th
    return new


def picked_frame(sketch, origin, axis, reverse=False):
    """The new axes from the picks: origin (geo, pos) or None keeps the origin where it is; axis
    (geo, pos) of a line, an axis or None keeps the X direction."""
    o = sketch.getPoint(*origin) if origin is not None else _v(0, 0)
    angle = 0.0
    if axis is not None:
        geo = axis[0]
        if geo == -1:
            d = _v(1, 0)
        elif geo == -2:
            d = _v(0, 1)
        else:
            d = sketch.getPoint(geo, 2) - sketch.getPoint(geo, 1)
        angle = math.degrees(math.atan2(d.y, d.x))
    if reverse:
        angle += 180.0
    return frame((o.x, o.y), angle)


def _page_class():
    import FreeCADGui as Gui
    from PySide import QtWidgets
    from . import sketchtoolpm

    class AlignPage(sketchtoolpm.ToolPage):
        TITLE = "Modify Sketch Grid/Origin"
        ICON = "SKETCH_ALIGN_GRID"
        PIXMAP = "Sketcher_ViewSketch"
        TRANSACTION = "Align Grid/Origin"

        def build(self):
            self.count = self.sketch.GeometryCount     # the preview's helper lines come after
            self.origin = None
            self.axis = None
            g = self.group("Selections")
            self.origin_box = self._box(g, "SWAlignOrigin", "Point for the origin",
                                        "The sketch's origin moves here")
            self.axis_box = self._box(g, "SWAlignXAxis", "Line or edge for the X axis",
                                      "The sketch's X axis turns along this line")
            self.reverse = QtWidgets.QCheckBox("Reverse X axis direction", g.body)
            self.reverse.setObjectName("SWAlignReverse")
            self.reverse.toggled.connect(self.changed)
            g.content.addWidget(self.reverse)
            g = self.group("Options")
            self.reset = QtWidgets.QPushButton("Reset to the original origin", g.body)
            self.reset.setObjectName("SWAlignReset")
            self.reset.setToolTip("Puts the grid and the origin back where the sketch first had them")
            self.reset.clicked.connect(self.reset_origin)
            g.content.addWidget(self.reset)
            self.reset.setEnabled(BASE in self.sketch.PropertiesList)
            self.active = self.origin_box
            self._mark()
            self.observer = sketchtoolpm.PickObserver(self)
            Gui.Selection.addObserver(self.observer)
            from . import relationspm
            for sub in relationspm.picked_subs(self.sketch):
                self.picked(sub)

        def _box(self, g, name, placeholder, tip):
            box = QtWidgets.QListWidget(g.body)
            box.setObjectName(name)
            box.setFixedHeight(26)
            box.setToolTip(tip)
            box.addItem(placeholder)
            box.setProperty("placeholder", placeholder)
            box.installEventFilter(self)
            g.content.addWidget(box)
            return box

        def eventFilter(self, obj, event):
            from PySide import QtCore
            if not isinstance(event, QtCore.QEvent):
                return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
            if event.type() == QtCore.QEvent.FocusIn and obj in (self.origin_box, self.axis_box):
                self.active = obj
                self._mark()
            return False

        def _mark(self):
            for box in (self.origin_box, self.axis_box):
                box.setStyleSheet("QListWidget { background: #dcecff; }" if box is self.active else "")

        def _fill(self, box, text):
            box.clear()
            box.addItem(text)

        def picked(self, sub):
            from . import relationspm
            item = sketchtoolpm.item_of(self.sketch, sub)
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("aligngrid.py:389", _fw_err)
            if item is None or item.geo >= self.count:
                return
            if item.kind == "point":
                pos = item.pos if item.pos else 1
                self.origin = (item.geo, pos)
                self._fill(self.origin_box, sketchtoolpm.point_name(self.sketch, item.geo, pos)
                           if item.geo >= -1 else item.name)
                if self.axis is None:
                    self.active = self.axis_box
            elif item.kind == "line":
                self.axis = (item.geo, 0)
                self._fill(self.axis_box, item.name)
                if self.origin is None:
                    self.active = self.origin_box
            else:
                self.show_note("Pick a point for the origin, or a line for the X axis.", True)
                return
            self._mark()
            self.changed()

        def selection_changed(self):
            pass

        def changed(self, *args):
            self.undo_work()
            if self.origin is None and self.axis is None and not self.reverse.isChecked():
                self.show_note("")
                return
            self.begin()
            try:
                n = align(self.sketch, picked_frame(self.sketch, self.origin, self.axis,
                                                    self.reverse.isChecked()))
            except Exception as error:
                self.show_note("Could not move the origin: %s" % error, True)
                return
            sketchtoolpm._refresh(self.sketch)
            self.show_note("%d relations now refer to the old axes." % n if n else "")

        def reset_origin(self):
            self.undo_work()
            self.origin = self.axis = None
            self._fill(self.origin_box, self.origin_box.property("placeholder"))
            self._fill(self.axis_box, self.axis_box.property("placeholder"))
            self.reverse.blockSignals(True)
            self.reverse.setChecked(False)
            self.reverse.blockSignals(False)
            here = getattr(self.sketch, _offset_name(self.sketch))
            back = here.inverse().multiply(base_of(self.sketch))
            self.begin()
            align(self.sketch, back)
            sketchtoolpm._refresh(self.sketch)
            self.show_note("The grid and the origin are back where the sketch first had them.")

        def closing(self):
            try:
                Gui.Selection.removeObserver(self.observer)
            except Exception as _fw_err:
                _fw_log("aligngrid.py:447", _fw_err)
            self.observer.page = None

    return AlignPage


class _Command:
    def GetResources(self):
        return {"Pixmap": "Sketcher_ViewSketch", "MenuText": "Align Grid/Origin",
                "ToolTip": "Moves the sketch's origin to a point and turns its grid and X axis along a line; "
                           "the sketch stays where it is",
                "CmdType": "ForEdit"}

    def IsActive(self):
        from . import contextbar
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        from . import contextbar, sketchtoolpm
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(_page_class()(sketch))


def register():
    import FreeCADGui as Gui
    try:
        if "SWStyle_AlignGridOrigin" not in Gui.listCommands():
            Gui.addCommand("SWStyle_AlignGridOrigin", _Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Align Grid/Origin command not added (%s)\n" % error)
