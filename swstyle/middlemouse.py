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
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import contextbar, paths, style, wheelzoom
from .widgets import alive

Qt = QtCore.Qt

PARAM = "MiddleButton"
RATE = 3.0 * math.pi         # radians the model turns for a drag across the view's width (FreeCAD: 3.85)
SPEED = "RotateSpeed"        # addon parameter: percent of RATE
CLICK = 3.0                  # pixels the pointer may move during a click
END_ON = 0.3                 # an axis this close to pointing at the viewer turns like a knob
RINGS = (0.06, 0.15, 0.3)    # where to look for geometry near the middle, in view heights
SPOKES = 8
ANNOTATION = "SWStyleRotateAbout"
MAGENTA = "1 0 1"
OUTLINE_EDGES = 64           # most edges of a face drawn in magenta
MODS = Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
MOUSE = (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove)

IDLE, PRESSED, TURNING, PASSED, SWALLOW = range(5)


def enabled():
    return paths.params().GetBool(PARAM, True)


def speed():
    """How fast the model turns, as a share of RATE (Mod/<look> RotateSpeed, percent)."""
    percent = paths.params().GetInt(SPEED, 100)
    return min(max(percent, 10), 500) / 100.0


# --------------------------------------------------------------------------- the model
_BOX = {"key": None, "box": None}


def model_box():
    """Bounding box of the solids shown, or of whatever is shown without a solid, or None. Kept while the
    scene stamp stays put: walking every object's shape took 0.15 s at each turn's start on a 150-part
    assembly (vd110, 11-20)."""
    try:
        doc = Gui.ActiveDocument.Document
    except Exception:
        doc = None
    try:
        from . import scenestamp
        gen = scenestamp.generation()
    except Exception:
        gen = None
    key = (doc.Name, gen) if doc is not None and gen is not None else None
    if key is not None and key == _BOX["key"]:
        box = _BOX["box"]
        return App.BoundBox(box) if box is not None else None
    box = _walk_box(doc)
    _BOX["key"], _BOX["box"] = key, (App.BoundBox(box) if box is not None else None)
    return box


def _walk_box(doc):
    solid, shown = None, None
    try:
        objects = doc.Objects
    except Exception:
        objects = []
    has_solid = {}      # linked object -> its shape has a solid: 150 links of one part ask once
    for obj in objects:
        try:
            if not obj.Visibility:
                continue
            if _whole_group(obj):
                continue        # an assembly or part container at the origin: its shown members are walked
            if obj.TypeId == "App::Link":
                # the link's box from the assembly's kept boxes (dynlod), not a transformed copy of its shape
                box, solids = _link_box(obj, has_solid)
                if box is None:
                    continue
            else:
                shape = getattr(obj, "Shape", None)
                if shape is None or shape.isNull():
                    continue
                box = _shown_box(obj) or shape.BoundBox
                solids = bool(shape.Solids)
            if not box.isValid():
                continue
            if shown is None:
                shown = App.BoundBox(box)
            else:
                shown.add(box)
            if solids:
                if solid is None:
                    solid = App.BoundBox(box)
                else:
                    solid.add(box)
        except Exception:
            continue
    return solid or shown


def _shown_box(obj):
    """The box of what the view draws for the object, from its scene node, or None. The shape's exact
    box took 45 ms a solid on a 200-feature part, all of it at the first turn's start (vd117, 11-21)."""
    try:
        vo = obj.ViewObject
        box = vo.getBoundingBox() if vo is not None else None
    except Exception:
        return None
    if box is None or not box.isValid():
        return None
    return box


def _whole_group(obj):
    """True for a container (assembly, App::Part) at the origin, whose Shape is the compound of every member:
    building it took 0.07 s at each turn's start on a 150-part assembly (vd110). A body keeps its own shape."""
    try:
        if obj.isDerivedFrom("PartDesign::Body") or not obj.hasExtension("App::GeoFeatureGroupExtension"):
            return False
        return obj.Placement.isIdentity()
    except Exception:
        return False


def _link_box(obj, has_solid):
    """(world box, has a solid) of a link, or (None, False)."""
    from . import dynlod
    b = dynlod._box(obj)
    if b is None:
        return None, False
    linked = obj.getLinkedObject(True)
    key = (linked.Document.Name, linked.Name) if linked is not None else None
    if key not in has_solid:
        shape = getattr(linked, "Shape", None)
        has_solid[key] = bool(shape is not None and not shape.isNull() and shape.Solids)
    return App.BoundBox(*b), has_solid[key]


def box_in_view(view, box):
    """True when every corner of the box shows in the view."""
    try:
        width, height = view.getSize()
    except Exception:
        return False
    for x in (box.XMin, box.XMax):
        for y in (box.YMin, box.YMax):
            for z in (box.ZMin, box.ZMax):
                px, py = view.getPointOnViewport(App.Vector(x, y, z))
                if px < 0 or py < 0 or px > width - 1 or py > height - 1:
                    return False
    return True


# --------------------------------------------------------------------------- what a turn is about
class Pivot:
    """What a turn is about: a point, or a line through it (axis), with the outline shown in
    magenta (polylines) and the point marked."""

    def __init__(self, point, axis=None, outline=(), mark=True, what=""):
        self.point = App.Vector(point)
        self.axis = None
        if axis is not None and axis.Length > 1e-12:
            self.axis = App.Vector(axis).normalize()
        self.outline = [list(line) for line in outline]
        self.mark = mark
        self.what = what             # "vertex", "line", "circle", "plane", "cylinder"..., for checks

    def __repr__(self):
        return "Pivot(%s, %s, %s)" % (self.what, self.point, self.axis)


def _polyline(edge):
    try:
        straight = type(edge.Curve).__name__ in ("Line", "LineSegment")
        points = edge.discretize(Number=2 if straight else 96)
    except Exception:
        points = [v.Point for v in edge.Vertexes]
    return points


def _foot(shape, point):
    """The point of the shape nearest the given one."""
    try:
        import Part
        return shape.distToShape(Part.Vertex(point))[1][0][0]
    except Exception:
        return point


def _shape_of(info):
    """The picked element's shape, in the document's coordinates, and the object it is of."""
    import Part
    doc = App.getDocument(info["Document"])
    parent, sub = info.get("ParentObject"), info.get("SubName") or ""
    if parent is None:
        parent, sub = doc.getObject(info["Object"]), info.get("Component") or ""
    if parent is None:
        return None, None
    obj = parent
    try:
        resolved = parent.getSubObject(sub, retType=1) if sub else parent
        if resolved is not None:
            obj = resolved
    except Exception as _fw_err:
        _fw_log("middlemouse.py:171", _fw_err)
    try:
        shape = Part.getShape(parent, sub, needSubElement=True)
    except Exception:
        shape = None
    return shape, obj


def pivot_for_shape(shape, point, obj=None):
    ""


    if shape is None or shape.isNull():
        return _pivot_for_datum(obj, point)
    kind = shape.ShapeType
    if kind == "Vertex":
        return Pivot(shape.Point, None, [], True, "vertex")
    if kind == "Edge":
        outline = [_polyline(shape)]
        curve = shape.Curve
        name = type(curve).__name__
        if name in ("Line", "LineSegment"):
            direction = getattr(curve, "Direction", None)
            if direction is None:
                direction = shape.Vertexes[-1].Point - shape.Vertexes[0].Point
            return Pivot(_foot(shape, point), direction, outline, False, "line")
        if name in ("Circle", "ArcOfCircle", "Ellipse", "ArcOfEllipse"):
            centre = getattr(curve, "Center", None)
            axis = getattr(curve, "Axis", None)
            if centre is not None and axis is not None:
                return Pivot(centre, axis, outline, False, "circle")
        return Pivot(_foot(shape, point), None, outline, True, "edge")
    if kind == "Face":
        edges = shape.Edges[:OUTLINE_EDGES]
        outline = [_polyline(e) for e in edges]
        surface = shape.Surface
        name = type(surface).__name__
        if name == "Plane":
            normal = getattr(surface, "Axis", None)
            return Pivot(_foot(shape, point), normal, outline, True, "plane")
        if name in ("Cylinder", "Cone", "Toroid"):
            centre = getattr(surface, "Center", None)
            axis = getattr(surface, "Axis", None)
            if centre is not None and axis is not None:
                return Pivot(centre, axis, outline, False, name.lower())
        if name == "Sphere":
            return Pivot(surface.Center, None, outline, True, "sphere")
        try:
            u, v = surface.parameter(point)
            normal = shape.normalAt(u, v)
        except Exception:
            normal = None
        return Pivot(_foot(shape, point), normal, outline, True, "face")
    return Pivot(point, None, [], True, kind.lower())


def _pivot_for_datum(obj, point):
    """Origin planes, axes and points have no shape: their placement says it."""
    if obj is None:
        return Pivot(point, None, [], True, "point")
    try:
        placement = obj.getGlobalPlacement()
    except Exception:
        placement = getattr(obj, "Placement", App.Placement())
    type_id = getattr(obj, "TypeId", "")
    if type_id.endswith("Plane"):
        return Pivot(point, placement.Rotation.multVec(App.Vector(0, 0, 1)), [], True, "plane")
    if type_id.endswith("Line"):
        return Pivot(placement.Base, placement.Rotation.multVec(App.Vector(1, 0, 0)), [], False, "line")
    if type_id.endswith("Point"):
        return Pivot(placement.Base, None, [], True, "vertex")
    return Pivot(point, None, [], True, "point")


def pivot_from_pick(info):
    point = App.Vector(info["x"], info["y"], info["z"])
    try:
        shape, obj = _shape_of(info)
    except Exception:
        shape, obj = None, None
    try:
        return pivot_for_shape(shape, point, obj)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: middle button: %s\n" % error)
        return Pivot(point, None, [], True, "point")


# --------------------------------------------------------------------------- magenta
def _inventor(pivot):
    lines = ["#Inventor V2.1 ascii", "Annotation {", "PickStyle { style UNPICKABLE }",
             "LightModel { model BASE_COLOR }", "BaseColor { rgb %s }" % MAGENTA,
             "DrawStyle { lineWidth 3 pointSize 9 }"]
    polylines = [p for p in pivot.outline if len(p) >= 2]
    if polylines:
        points = [p for line in polylines for p in line]
        lines.append("Coordinate3 { point [ %s ] }" % ", ".join("%.9g %.9g %.9g" % (p.x, p.y, p.z) for p in points))
        lines.append("LineSet { numVertices [ %s ] }" % ", ".join(str(len(line)) for line in polylines))
    if pivot.mark or not polylines:
        p = pivot.point
        lines.append("Coordinate3 { point [ %.9g %.9g %.9g ] }" % (p.x, p.y, p.z))
        lines.append("PointSet { numPoints 1 }")
    lines.append("}")
    return "\n".join(lines) + "\n"


SHOWN = [False]              # True while the magenta highlight is up, for checks


def show(view, pivot):
    hide(view)
    if view is None or pivot is None:
        return False
    try:
        view.setAnnotation(ANNOTATION, _inventor(pivot))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: middle button highlight: %s\n" % error)
        return False
    SHOWN[0] = True
    return True


def hide(view):
    if view is None:
        return
    try:
        view.removeAnnotation(ANNOTATION)
    except Exception as _fw_err:
        _fw_log("middlemouse.py:298", _fw_err)
    SHOWN[0] = False


# --------------------------------------------------------------------------- cursors
_CURSORS = {}


def cursor(about=False):
    ""

    key = (bool(about), style.viewport_dark())      # the drawn ring follows the viewport's brightness
    if key in _CURSORS:
        return _CURSORS[key]
    size = 16
    icon = QtGui.QIcon(":/icons/cursor-rotate.svg")
    pixmap = icon.pixmap(QtCore.QSize(size, size)) if not icon.isNull() else QtGui.QPixmap()
    if pixmap.isNull():
        from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
        pixmap = _hidpi.canvas(size, size)
        pixmap.fill(Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtGui.QPen(style.viewport_ink(), 1.6))
        painter.drawArc(QtCore.QRectF(2.5, 2.5, 11, 11), 30 * 16, 300 * 16)
        painter.end()
    if about:
        pixmap = QtGui.QPixmap(pixmap)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtGui.QPen(QtGui.QColor("#00b000"), 2.0))
        painter.drawLine(QtCore.QPointF(1, size - 1), QtCore.QPointF(size - 1, 1))
        painter.end()
    from . import hidpi as _hidpi   # hidpi-1119
    _CURSORS[key] = QtGui.QCursor(pixmap, *_hidpi.hotspot(size // 2, size // 2, pixmap))
    return _CURSORS[key]


# --------------------------------------------------------------------------- turning
class Turn:
    """One middle drag: the camera turned about a pivot as the pointer moves."""

    def __init__(self, view, pivot, kind, width, origin):
        from .viewkeys import Camera
        self.view = view
        self.camera = Camera(view.getCamera())
        self.position = self.camera.position
        self.rotation = self.camera.rotation
        self.pivot = pivot
        self.kind = kind             # "free", "axis" or "roll"
        self.rate = RATE * speed() / max(float(width), 50.0)
        self.origin = origin         # the pivot on the screen, (x, y) in Qt pixels, for a knob turn
        self.turned = 0.0            # degrees, for checks

    def _axes(self):
        q = self.rotation
        return q.multVec(App.Vector(1, 0, 0)), q.multVec(App.Vector(0, 1, 0)), q.multVec(App.Vector(0, 0, 1))

    def step(self, last, pos):
        """Turns for the pointer's move from last to pos (Qt pixels, y down)."""
        dx, dy = pos.x() - last.x(), pos.y() - last.y()
        if dx == 0 and dy == 0:
            return
        right, up, out = self._axes()
        move = right * dx - up * dy          # the pointer's move, in the screen's plane
        if self.kind == "roll":
            # dragged right, the model rolls clockwise
            axis, angle = out, -self.rate * dx
        elif self.pivot.axis is None:
            # the near side of the model goes the way the pointer goes
            length = move.Length
            axis, angle = out.cross(move).normalize(), self.rate * length
        else:
            axis = self.pivot.axis
            across = axis.cross(out)        # where the near side goes for a positive turn
            if across.Length > END_ON:
                angle = self.rate * move.dot(across.normalize())
            else:
                angle = self._knob(last, pos) * (1.0 if axis.dot(out) > 0 else -1.0)
        if abs(angle) < 1e-12:
            return
        model = App.Rotation(axis, math.degrees(angle))
        q = model.inverted()                 # the camera goes the other way
        centre = self.pivot.point
        self.position = centre + q.multVec(self.position - centre)
        self.rotation = q.multiply(self.rotation)
        self.view.setCamera(self.camera.with_pose(self.position, self.rotation))
        self.turned += math.degrees(abs(angle))

    def _knob(self, last, pos):
        """The angle the pointer went round the pivot's spot, anticlockwise on the screen."""
        if self.origin is None:
            return 0.0
        ox, oy = self.origin
        ax, ay = last.x() - ox, oy - last.y()
        bx, by = pos.x() - ox, oy - pos.y()
        if math.hypot(ax, ay) < 2.0 or math.hypot(bx, by) < 2.0:
            return 0.0
        return math.atan2(ax * by - ay * bx, ax * bx + ay * by)


class MiddleMouse:
    ""


    def __init__(self, owner):
        self.owner = owner           # ViewKeys
        self.state = IDLE
        self.kind = "free"
        self.press = None            # (QPointF, time) of the middle press
        self.last = None             # QPointF the last turn step ended at
        self.moved = False
        self.pending = None          # (viewport, view, Pivot) a middle click picked, for the next drag
        self.turn = None
        self.swallowed = set()       # other buttons pressed during a turn
        self._sending = False
        self._cursor_widget = None   # (widget, its cursor) while a picked item waits
        self._override = False
        # for checks
        self.clicks = 0
        self.turns = 0
        self.last_pivot = None
        self.last_kind = None
        self.nudges = 0

    # ------------------------------------------------------------------ events
    def filter(self, obj, event, view):
        if self._sending:
            return False
        t = event.type()
        if isinstance(obj, QtWidgets.QAbstractScrollArea):
            return False             # the viewport gets the mouse first
        if t == QtCore.QEvent.MouseButtonPress:
            return self._pressed(obj, event, view)
        if t == QtCore.QEvent.MouseMove:
            return self._moved(obj, event)
        if t == QtCore.QEvent.MouseButtonRelease:
            return self._released(obj, event, view)
        return False

    def _usable(self, view):
        return view is not None and enabled() and wheelzoom._navigation_ok(view)

    def _pressed(self, obj, event, view):
        button = event.button()
        if button != Qt.MiddleButton:
            if self.state in (PRESSED, TURNING):
                self.swallowed.add(button)
                return True
            self.forget()            # a click with another button drops a picked item
            return False
        if self.state != IDLE:
            self.reset()             # a release went missing
        if event.buttons() != Qt.MiddleButton or not self._usable(view):
            return False
        mods = event.modifiers() & MODS
        self.press = (QtCore.QPointF(event.position()), time.monotonic())
        self.last = QtCore.QPointF(event.position())
        self.moved = False
        if mods & (Qt.ControlModifier | Qt.ShiftModifier):
            self.forget()
            self.state = PASSED      # FreeCAD pans or zooms
            return False
        self.kind = "roll" if mods == Qt.AltModifier else "turn"
        self.state = PRESSED
        return True

    def _moved(self, obj, event):
        if self.state == IDLE:
            return False
        pos = QtCore.QPointF(event.position())
        if self.state == PASSED:
            if self.press is not None and pos != self.press[0]:
                self.moved = True
            if not event.buttons() & Qt.MiddleButton:
                self.state = IDLE
            return False
        if self.state == SWALLOW:
            return bool(event.buttons() & Qt.MiddleButton)
        if not event.buttons() & Qt.MiddleButton:
            if self.state == PRESSED and self.press is not None:
                start = self.press[0]
                if math.hypot(pos.x() - start.x(), pos.y() - start.y()) < CLICK:
                    return False     # a late move from before the press, on the same spot
            self.finish()            # the release went elsewhere
            return False
        if self.state == PRESSED:
            start = self.press[0]
            if math.hypot(pos.x() - start.x(), pos.y() - start.y()) < CLICK:
                return True
            if not self.begin(obj):
                self.state = SWALLOW
                return True
        if self.state == TURNING and self.turn is not None:
            try:
                self.turn.step(self.last, pos)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: middle button turn: %s\n" % error)
                self.finish()
                return True
            self.last = pos
        return True

    def _released(self, obj, event, view):
        button = event.button()
        if button != Qt.MiddleButton:
            if button in self.swallowed:
                self.swallowed.discard(button)
                return True
            return False
        state, self.state = self.state, IDLE
        if state == PASSED:
            if not self.moved:
                self._nudge(obj, event)
            return False
        if state == PRESSED:
            if self.kind == "roll":
                self.forget()        # only a plain click picks
            else:
                self.click(obj, event, view)
            return True
        if state == TURNING:
            self.finish()
            QtCore.QTimer.singleShot(0, lambda: self._hover(obj))
            return True
        return state == SWALLOW

    def double_clicked(self):
        """A middle double-click zooms to fit (ViewKeys): the first click's pick is dropped and the
        second release goes nowhere."""
        self.forget()
        self.state = SWALLOW

    def double_with_keys(self, obj, event, view):
        """A middle double-click with a key held: FreeCAD takes it for a press, and centres the view
        on the release. With Ctrl or Shift FreeCAD gets it and the release is nudged; with Alt it goes
        nowhere. True when the double-click is taken here."""
        if isinstance(obj, QtWidgets.QAbstractScrollArea) or not self._usable(view):
            return False
        self.forget()
        if event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
            self.press = (QtCore.QPointF(event.position()), time.monotonic())
            self.moved = False
            self.state = PASSED
            return False
        self.state = SWALLOW
        return True

    # ------------------------------------------------------------------ click
    def click(self, widget, event, view):
        ""

        self.forget()
        if view is None or contextbar.sketch_in_edit() is not None:
            return
        info = self._pick(view, widget, event.position())
        if not info:
            return
        pivot = pivot_from_pick(info)
        self.pending = (widget, view, pivot)
        self.clicks += 1
        self.last_pivot = pivot
        show(view, pivot)
        target = self.owner.shell.view_widget() if self.owner is not None else None
        if target is not None and alive(target):
            self._cursor_widget = (target, target.cursor())
            target.setCursor(cursor(True))

    def forget(self):
        """Drops a pick that waits for a drag."""
        if self.pending is not None:
            hide(self.pending[1])
            self.pending = None
        if self._cursor_widget is not None:
            widget, saved = self._cursor_widget
            self._cursor_widget = None
            if alive(widget):
                widget.setCursor(saved)

    # ------------------------------------------------------------------ drag
    def begin(self, widget):
        view = self.owner_view()
        if view is None:
            return False
        try:
            view.stopAnimating()
        except Exception as _fw_err:
            _fw_log("middlemouse.py:583", _fw_err)
        width = widget.width()
        mark = False
        if self.kind == "roll":
            box = model_box()
            pivot = Pivot(box.Center if box is not None else self._focal(view), None, [], False, "middle")
            kind = "roll"
            self.forget()
        elif self.pending is not None and self.pending[0] is widget:
            pivot = self.pending[2]
            self.pending = None
            if self._cursor_widget is not None:
                widget_, saved = self._cursor_widget
                self._cursor_widget = None
                if alive(widget_):
                    widget_.setCursor(saved)
            kind = "free" if pivot.axis is None else "axis"
            mark = True              # the pick stays magenta while the model turns about it
        else:
            self.forget()
            pivot, mark = self.centre(view, widget)
            kind = "free"
        try:
            x, y = view.getPointOnViewport(pivot.point)
            dpr = widget.devicePixelRatioF()
            _, height = view.getSize()
            origin = (x / dpr, (height - 1 - y) / dpr)
        except Exception:
            origin = None
        try:
            self.turn = Turn(view, pivot, kind, width, origin)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: middle button: %s\n" % error)
            hide(view)
            return False
        if mark:
            show(view, pivot)
        try:
            Gui.Selection.clearPreselection()   # nothing lights up under the pointer while it turns
        except Exception as _fw_err:
            _fw_log("middlemouse.py:623", _fw_err)
        self.state = TURNING
        self.turns += 1
        self.last_pivot = pivot
        self.last_kind = kind
        QtWidgets.QApplication.setOverrideCursor(cursor(kind == "axis"))
        self._override = True
        return True

    def centre(self, view, widget):
        ""

        box = model_box()
        if box is None:
            return Pivot(self._focal(view), None, [], False, "screen"), False
        if box_in_view(view, box):
            return Pivot(box.Center, None, [], False, "middle"), False
        try:
            width, height = view.getSize()
        except Exception:
            return Pivot(box.Center, None, [], False, "middle"), False
        cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
        spots = [(cx, cy)]
        for ring in RINGS:
            r = ring * height
            for i in range(SPOKES):
                a = 2.0 * math.pi * i / SPOKES
                spots.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        for x, y in spots:
            try:
                info = view.getObjectInfo((int(round(x)), int(round(y))))
            except Exception:
                info = None
            if info:
                picked = pivot_from_pick(info)
                return Pivot(App.Vector(info["x"], info["y"], info["z"]), None, picked.outline, True,
                             "seen " + picked.what), True
        return Pivot(box.Center, None, [], False, "middle"), False

    def finish(self):
        turn, self.turn = self.turn, None
        self.state = IDLE
        if turn is not None:
            hide(turn.view)
        if self._override:
            self._override = False
            QtWidgets.QApplication.restoreOverrideCursor()

    def reset(self):
        self.finish()
        self.press = None
        self.swallowed.clear()

    def remove(self):
        self.reset()
        self.forget()

    # ------------------------------------------------------------------ helpers
    def owner_view(self):
        try:
            doc = Gui.ActiveDocument
            view = doc.ActiveView if doc is not None else None
        except Exception:
            return None
        return view if view is not None and hasattr(view, "setCamera") else None

    @staticmethod
    def _focal(view):
        from .viewkeys import Camera
        try:
            return Camera(view.getCamera()).focal_point()
        except Exception:
            return App.Vector()

    @staticmethod
    def _pick(view, widget, pos):
        try:
            dpr = widget.devicePixelRatioF()
            _, height = view.getSize()
            x = int(round(pos.x() * dpr))
            y = int(height - round(pos.y() * dpr) - 1)
            return view.getObjectInfo((x, y))
        except Exception:
            return None

    def _nudge(self, widget, event):
        """FreeCAD centres the view on a middle click that did not move, even with Ctrl or Shift;
        a move on the spot before the release tells it the pointer moved."""
        if not alive(widget):
            return
        move = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, event.position(), event.globalPosition(),
                                 Qt.NoButton, Qt.MiddleButton, event.modifiers())
        self._sending = True
        try:
            QtWidgets.QApplication.sendEvent(widget, move)
        finally:
            self._sending = False
        self.nudges += 1

    def _hover(self, widget):
        """After a turn FreeCAD has not seen the pointer move: a move on the spot updates what it
        highlights under the pointer."""
        if not alive(widget):
            return
        pos = QtCore.QPointF(widget.mapFromGlobal(QtGui.QCursor.pos()))
        move = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, pos, QtCore.QPointF(widget.mapToGlobal(pos.toPoint())),
                                 Qt.NoButton, QtWidgets.QApplication.mouseButtons(),
                                 QtWidgets.QApplication.keyboardModifiers())
        self._sending = True
        try:
            QtWidgets.QApplication.sendEvent(widget, move)
        finally:
            self._sending = False
