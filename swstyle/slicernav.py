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
from PySide import QtCore, QtGui, QtWidgets

from . import events

Qt = QtCore.Qt
_TYPES = (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove,
          QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.Wheel)

RATE = math.pi          # radians the view turns for a drag across the view's width (Orca: about half a turn)
CLICK = 4.0             # pixels the pointer may move and still be a click
STEP = 0.85             # zoom per wheel notch (Orca: about 15 %)
POLE = math.radians(0.5)  # closest the view comes to straight down or straight up

IDLE, PENDING, TURN, PAN = range(4)


def enabled():
    try:
        from . import slicer
        return slicer.params().GetBool("Navigation", True)
    except Exception:
        return True


def _vec(v):
    return App.Vector(v[0], v[1], v[2])


class Camera:
    """The view's Coin camera as position, look direction, distance to the turning point."""

    def __init__(self, view):
        self.view = view
        self.cam = view.getCameraNode()

    def perspective(self):
        return self.cam.getTypeId().getName().getString() == "PerspectiveCamera"

    def position(self):
        return _vec(self.cam.position.getValue())

    def axes(self):
        """(right, up, forward) world vectors of the camera."""
        from pivy import coin
        rot = self.cam.orientation.getValue()
        out = []
        for v in ((1, 0, 0), (0, 1, 0), (0, 0, -1)):
            w = rot.multVec(coin.SbVec3f(*v))
            out.append(_vec(w))
        return out

    def target(self):
        """The point the view looks at: the focal point."""
        _, _, f = self.axes()
        return self.position() + f * float(self.cam.focalDistance.getValue())

    def look(self, position, target):
        """Camera at position looking at target, the bed's Z up on screen (turntable)."""
        from pivy import coin
        f = target - position
        dist = f.Length
        if dist < 1e-9:
            return
        f = f * (1.0 / dist)
        z = App.Vector(0, 0, 1)
        r = f.cross(z)
        if r.Length < 1e-6:
            r = self.axes()[0]           # straight down or up: keep the screen's right
        r.normalize()
        u = r.cross(f)
        u.normalize()
        m = coin.SbMatrix(r.x, r.y, r.z, 0,
                          u.x, u.y, u.z, 0,
                          -f.x, -f.y, -f.z, 0,
                          0, 0, 0, 1)
        self.cam.orientation.setValue(coin.SbRotation(m))
        self.cam.position.setValue(position.x, position.y, position.z)
        self.cam.focalDistance.setValue(dist)

    def per_pixel(self, height_px):
        """World length of one pixel at the turning point."""
        if self.perspective():
            angle = float(self.cam.heightAngle.getValue())
            return 2.0 * float(self.cam.focalDistance.getValue()) * math.tan(angle / 2.0) / max(1, height_px)
        return float(self.cam.height.getValue()) / max(1, height_px)

    # ------------------------------------------------------------------ the three moves
    def turn(self, dx, dy, width_px, target=None):
        """Turntable: dx about the bed's Z through the turning point, dy up and down, never over the top."""
        t = target if target is not None else self.target()
        v = self.position() - t
        dist = v.Length
        if dist < 1e-9:
            return
        az = math.atan2(v.y, v.x) - dx * RATE / max(1, width_px)
        polar = math.acos(max(-1.0, min(1.0, v.z / dist))) - dy * RATE / max(1, width_px)
        polar = max(POLE, min(math.pi - POLE, polar))
        p = t + App.Vector(math.sin(polar) * math.cos(az), math.sin(polar) * math.sin(az), math.cos(polar)) * dist
        self.look(p, t)

    def pan(self, dx, dy, height_px):
        r, u, _ = self.axes()
        k = self.per_pixel(height_px)
        shift = r * (-dx * k) + u * (dy * k)
        p = self.position() + shift
        self.cam.position.setValue(p.x, p.y, p.z)

    def zoom(self, factor, sx, sy, width_px, height_px):
        """Scale by factor (< 1 is closer) keeping the point under the pointer (sx, sy from the
        middle, pixels, y down) where it is."""
        r, u, f = self.axes()
        k = self.per_pixel(height_px)
        t = self.target()
        w = t + r * (sx * k) + u * (-sy * k)      # under the pointer, on the plane through the turning point
        t2 = w + (t - w) * factor
        if self.perspective():
            dist = float(self.cam.focalDistance.getValue()) * factor
            p = t2 - f * dist
            self.cam.position.setValue(p.x, p.y, p.z)
            self.cam.focalDistance.setValue(dist)
        else:
            self.cam.height.setValue(float(self.cam.height.getValue()) * factor)
            p = self.position() + (t2 - t)
            self.cam.position.setValue(p.x, p.y, p.z)


class SlicerNavigation(QtCore.QObject):
    ""


    def __init__(self, plate):
        super().__init__(QtWidgets.QApplication.instance())
        self.plate = plate
        self.state = IDLE
        self._press = None         # (widget, button, local pos, global pos, modifiers)
        self._last = None
        self._replaying = False
        self.on = False
        self.moves = []            # ("turn"|"pan"|"zoom", ...) for checks

    # ------------------------------------------------------------------ on and off
    def start(self):
        if self.on or not enabled():
            return
        events.register("slicernav", _TYPES, self.eventFilter)
        self.on = True

    def stop(self):
        if self.on:
            events.unregister("slicernav")
        self.on = False
        self.state = IDLE
        self._press = None

    def aim(self):
        """Look at the middle of the plate on show, as the slicers open their Prepare view; again
        once FreeCAD's fit (which may be animated) has settled."""
        self._aim_now()
        QtCore.QTimer.singleShot(900, self._aim_now)

    def _aim_now(self):
        view = self.plate.view
        if view is None:
            return
        try:
            cam = Camera(view)
            x, y = self.plate.bed_centre()
            o = self.plate.plate_origin(self.plate.current)
            t = App.Vector(x + o.x, y + o.y, 0.0)
            _, _, f = cam.axes()
            cam.look(t - f * float(cam.cam.focalDistance.getValue()), t)
        except Exception as error:
            App.Console.PrintWarning("Slicer view: could not aim at the plate: %s\n" % error)

    # ------------------------------------------------------------------ helpers
    def _viewport(self):
        view = self.plate.view
        if view is None:
            return None
        try:
            from . import shell
            w = shell.shell().view_widget()
            if w is not None and hasattr(w, "viewport"):
                return w.viewport()
        except Exception as _fw_err:
            _fw_log("slicernav.py:213", _fw_err)
        try:
            gl = view.graphicsView() if hasattr(view, "graphicsView") else None
            return gl.viewport() if gl is not None else None
        except Exception:
            return None

    def _ours(self, obj):
        vp = self._viewport()
        return vp is not None and obj is vp

    def _inventor(self, widget, pos):
        dpr = widget.devicePixelRatioF() if hasattr(widget, "devicePixelRatioF") else 1.0
        return (int(pos.x() * dpr), int((widget.height() - pos.y()) * dpr))

    def _on_plate(self, widget, pos):
        """A press here is the plate's: an object, a gizmo handle, or picking a face."""
        p = self.plate
        if getattr(p, "picking", None) is not None:
            return True
        xy = self._inventor(widget, pos)
        try:
            if p.gizmo._hit(xy) is not None:
                return True
        except Exception as _fw_err:
            _fw_log("slicernav.py:238", _fw_err)
        try:
            return p._pick(xy) is not None
        except Exception:
            return False

    def _camera(self):
        return Camera(self.plate.view)

    def _replay(self, release=None):
        press, self._press = self._press, None
        if press is None:
            return
        widget, button, local, glob, mods = press
        events = [QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, local, glob, button, button, mods)]
        if release is not None:
            events.append(QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease, release[0], release[1], button,
                                            Qt.NoButton, mods))
        self._replaying = True
        try:
            for e in events:
                QtWidgets.QApplication.sendEvent(widget, e)
        finally:
            self._replaying = False

    # ------------------------------------------------------------------ events
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if self._replaying or self.plate.view is None:
            return False
        t = event.type()
        if t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove,
                     QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.Wheel):
            return False
        if not self._ours(obj):
            return False
        try:
            return self._event(obj, event, t)
        except Exception as error:
            App.Console.PrintError("Slicer view: %s\n" % error)
            self.state = IDLE
            self._press = None
            return False

    def _event(self, obj, event, t):
        if t == QtCore.QEvent.Wheel:
            if event.modifiers() != Qt.NoModifier:
                return False
            notches = event.angleDelta().y() / 120.0
            if not notches:
                return True
            pos = event.position()
            factor = STEP ** notches                 # wheel up: closer, as in the slicers
            self._camera().zoom(factor, pos.x() - obj.width() / 2.0, pos.y() - obj.height() / 2.0,
                                obj.width(), obj.height())
            self.moves.append(("zoom", factor))
            return True
        if t == QtCore.QEvent.MouseButtonPress:
            if self.state != IDLE:
                return True                          # another button during a move
            button = event.button()
            if event.modifiers() != Qt.NoModifier or event.buttons() != button:
                return False
            if button == Qt.LeftButton and self._on_plate(obj, event.position()):
                return False                         # select, move, handles: the plate's
            if button not in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
                return False
            self._press = (obj, button, QtCore.QPointF(event.position()), QtCore.QPointF(event.globalPosition()),
                           event.modifiers())
            self._last = QtCore.QPointF(event.position())
            self.state = PENDING
            return True
        if t == QtCore.QEvent.MouseMove:
            if self.state == IDLE:
                return False
            if self._press is None or not event.buttons() & self._press[1]:
                self.state = IDLE                    # the release went elsewhere
                self._press = None
                return False
            pos = event.position()
            if self.state == PENDING:
                d = pos - self._press[2]
                if math.hypot(d.x(), d.y()) < CLICK:
                    return True
                self.state = TURN if self._press[1] == Qt.LeftButton else PAN
            dx, dy = pos.x() - self._last.x(), pos.y() - self._last.y()
            self._last = QtCore.QPointF(pos)
            cam = self._camera()
            if self.state == TURN:
                cam.turn(dx, dy, obj.width())
                self.moves.append(("turn", dx, dy))
            else:
                cam.pan(dx, dy, obj.height())
                self.moves.append(("pan", dx, dy))
            return True
        if t == QtCore.QEvent.MouseButtonRelease:
            if self.state == IDLE or self._press is None or event.button() != self._press[1]:
                return self.state != IDLE
            state, self.state = self.state, IDLE
            if state == PENDING:
                if self._press[1] == Qt.MiddleButton:
                    self._press = None               # a middle click does nothing, as in the slicers
                    return True
                tool = getattr(self.plate, "picking", None)
                if self._press[1] == Qt.RightButton and hasattr(tool, "right_click"):
                    # a tool that takes right clicks (Brim ears: remove an ear); elsewhere, the menu as usual
                    try:
                        if tool.right_click(self._inventor(obj, event.position())):
                            self._press = None
                            return True
                    except Exception as _fw_err:
                        _fw_log("slicernav.py:right_click", _fw_err)
                # a click: FreeCAD and the plate get it as it was (select, empty to clear, the menu)
                self._replay((QtCore.QPointF(event.position()), QtCore.QPointF(event.globalPosition())))
                return True
            self._press = None
            return True                              # the end of a turn or pan: no click, no menu
        if t == QtCore.QEvent.MouseButtonDblClick:
            return self.state != IDLE
        return False
