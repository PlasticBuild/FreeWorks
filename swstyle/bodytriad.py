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
from PySide import QtCore

ARM_PX = 70             # arm length on screen
RING_PX = 42            # ring radius on screen
HIT_PX = 8
STEP = 0.01             # mm
STEP_DEG = 1.0
AXES = (App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1))
COLOURS = ((0.85, 0.1, 0.1), (0.1, 0.7, 0.1), (0.1, 0.25, 0.95))
HOVER = (1.0, 0.55, 0.0)
RING_SEGMENTS = 48
NAME = "SWBodyTriad"

_current = []           # the triad shown now (tests)


def current():
    return _current[0] if _current else None


def _busy():
    """A triad drag is on (pmconfirm leaves Esc to it)."""
    t = current()
    return t is not None and t.drag is not None


def _view():
    try:
        return Gui.ActiveDocument.ActiveView
    except Exception:
        return None


class BodyTriad(QtCore.QObject):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.sep = None
        self.root = None
        self.drag = None            # {"kind": "arm"/"ring", "axis": i, "v0": value, ...}
        self.hover = None           # ("arm"|"ring", i)
        self.swallow = False        # Escape ended a drag with the button still down
        self.esc_up = False         # the release of that Escape is ours too
        self.cache = None           # (base, arm mm) last drawn
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.redraw)
        self.timer.start()
        from . import events
        events.register("bodytriad", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                                      QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.KeyPress,
                                      QtCore.QEvent.KeyRelease, QtCore.QEvent.ShortcutOverride), self.filter)
        _current[:] = [self]
        try:
            from . import pmconfirm
            if _busy not in pmconfirm.BUSY:
                pmconfirm.BUSY.append(_busy)
        except Exception as _fw_err:
            _fw_log("bodytriad.py:busy", _fw_err)
        self.redraw()

    # ------------------------------------------------------------------ geometry
    def obj(self):
        try:
            return self.panel.obj()
        except Exception:
            return None

    def base(self):
        """The bodies' centre where they are now (their picked centres + Delta)."""
        obj = self.obj()
        if obj is None:
            return None
        pts = []
        for text in getattr(obj, "Bodies", []) or []:
            try:
                parts = str(text).split(":")
                pts.append(App.Vector(float(parts[-3]), float(parts[-2]), float(parts[-1])))
            except Exception:
                continue
        if not pts:
            return None
        c = App.Vector()
        for p in pts:
            c += p
        c = c * (1.0 / len(pts))
        try:
            c += App.Vector(obj.Translate)
        except Exception:
            pass
        return c

    def _mm_per_px(self, view, base):
        try:
            s = view.getPointOnScreen(base)
            a = view.getPoint(int(s[0]), int(s[1]))
            b = view.getPoint(int(s[0]) + 100, int(s[1]))
            return max((b - a).Length / 100.0, 1e-9)
        except Exception:
            return 0.1

    def _ring_points(self, base, axis, radius):
        u = AXES[(axis + 1) % 3]
        v = AXES[(axis + 2) % 3]
        return [base + u * (radius * math.cos(2 * math.pi * k / RING_SEGMENTS))
                + v * (radius * math.sin(2 * math.pi * k / RING_SEGMENTS)) for k in range(RING_SEGMENTS + 1)]

    # ------------------------------------------------------------------ drawing
    def redraw(self):
        view = _view()
        base = self.base()
        if view is None or base is None or not hasattr(view, "getSceneGraph"):
            self.clear()
            return
        mm = self._mm_per_px(view, base)
        key = (round(base.x, 6), round(base.y, 6), round(base.z, 6), round(mm, 9), self.hover)
        if self.sep is not None and key == self.cache:
            return
        self.clear()
        from pivy import coin
        sep = coin.SoSeparator()
        sep.setName(NAME)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        depth = coin.SoDepthBuffer()
        depth.test = False
        draw = coin.SoDrawStyle()
        draw.lineWidth = 3
        for child in (pick, light, depth, draw):
            sep.addChild(child)
        arm, ring = ARM_PX * mm, RING_PX * mm
        for i, axis in enumerate(AXES):
            for kind, pts in (("arm", [base, base + axis * arm]), ("ring", self._ring_points(base, i, ring))):
                part = coin.SoSeparator()
                colour = coin.SoBaseColor()
                colour.rgb.setValue(*(HOVER if self.hover == (kind, i) else COLOURS[i]))
                coords = coin.SoCoordinate3()
                coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
                line = coin.SoLineSet()
                line.numVertices.setValue(len(pts))
                for child in (colour, coords, line):
                    part.addChild(child)
                if kind == "arm":
                    head = coin.SoSeparator()
                    move = coin.SoTransform()
                    tip = base + axis * arm
                    move.translation.setValue(tip.x, tip.y, tip.z)
                    move.rotation.setValue(coin.SbRotation(coin.SbVec3f(0, 1, 0), coin.SbVec3f(axis.x, axis.y, axis.z)))
                    cone = coin.SoCone()
                    cone.bottomRadius = 4 * mm
                    cone.height = 12 * mm
                    head.addChild(move)
                    head.addChild(cone)
                    part.addChild(head)
                sep.addChild(part)
        root = view.getSceneGraph()
        root.addChild(sep)
        self.sep, self.root, self.cache = sep, root, key

    def clear(self):
        if self.sep is not None and self.root is not None:
            try:
                self.root.removeChild(self.sep)
            except Exception as _fw_err:
                _fw_log("bodytriad.py:clear", _fw_err)
        self.sep = self.root = None
        self.cache = None

    # ------------------------------------------------------------------ the mouse
    def _coin_pos(self, widget, event):
        try:
            p = event.position()
        except AttributeError:
            p = QtCore.QPointF(event.pos())
        r = widget.devicePixelRatioF()
        return p.x() * r, (widget.height() - p.y()) * r

    def under(self, pos):
        """("arm"|"ring", axis) under the screen position (coin pixels), else None."""
        view = _view()
        base = self.base()
        if view is None or base is None:
            return None
        mm = self._mm_per_px(view, base)
        best = None
        for i, axis in enumerate(AXES):
            for kind, pts in (("arm", [base + axis * (ARM_PX * mm * k / 8.0) for k in range(2, 9)]),
                              ("ring", self._ring_points(base, i, RING_PX * mm))):
                scr = [view.getPointOnScreen(p) for p in pts]
                for a, b in zip(scr, scr[1:]):
                    d = _seg_dist(pos, a, b)
                    if d <= HIT_PX and (best is None or d < best[0]):
                        best = (d, kind, i)
        return best[1:] if best else None

    def _ray_param(self, view, pos, base, direction):
        from .instant3d import _ray_param
        return _ray_param(view, pos, base, direction)

    def _screen_angle(self, view, pos, base, axis):
        c = view.getPointOnScreen(base)
        ang = math.degrees(math.atan2(pos[1] - c[1], pos[0] - c[0]))
        # the ring turns the other way on screen when its axis points away from the viewer
        towards = App.Vector(*view.getViewDirection()).dot(axis) < 0
        return ang if towards else -ang

    def filter(self, obj, event):
        kind = event.type()
        QE = QtCore.QEvent
        if kind == QE.ShortcutOverride:
            if self.drag is not None:
                event.accept()          # no shortcut while dragging: Escape would close the page
                return True
            return False
        if kind == QE.KeyPress:
            if self.drag is not None:
                if event.key() == QtCore.Qt.Key_Escape:
                    self.cancel()
                    self.swallow = True
                    self.esc_up = True
                return True
            return False
        if kind == QE.KeyRelease:
            if self.esc_up and event.key() == QtCore.Qt.Key_Escape:
                self.esc_up = False     # FreeCAD's view closes the page on the release of Esc
                return True
            return False
        if not obj.inherits("QOpenGLWidget"):
            return False
        pos = self._coin_pos(obj, event)
        if kind == QE.MouseMove:
            if self.drag is not None:
                self.move(pos)
                return True
            if self.swallow:
                return True             # the button is still down after Escape
            h = self.under(pos)
            if h != self.hover:
                self.hover = h
                self.redraw()
            return False
        if event.button() != QtCore.Qt.LeftButton:
            return False
        if kind == QE.MouseButtonPress:
            self.swallow = False
            h = self.under(pos)
            if h is None:
                return False
            self.press(h, pos)
            return True
        if kind == QE.MouseButtonRelease:
            if self.drag is not None:
                self.drag = None
                return True
            if self.swallow:
                self.swallow = False    # FreeCAD never saw the press, so not this either
                return True
        return False

    def _boxes(self, kind):
        return getattr(self.panel, "delta" if kind == "arm" else "angles", None)

    def press(self, handle, pos):
        kind, i = handle
        view = _view()
        base = self.base()
        boxes = self._boxes(kind)
        if view is None or base is None or not boxes:
            return
        d = {"kind": kind, "axis": i, "v0": boxes[i].value(), "base": base}
        if kind == "arm":
            d["t0"] = self._ray_param(view, pos, base, AXES[i])
        else:
            obj = self.obj()
            try:
                if obj is not None and App.Vector(obj.RotateAngles).Length < 1e-9:
                    for k, box in enumerate(self.panel.center):
                        box.setValue((base.x, base.y, base.z)[k])
            except Exception as _fw_err:
                _fw_log("bodytriad.py:centre", _fw_err)
            d["a0"] = self._screen_angle(view, pos, base, AXES[i])
        self.drag = d

    def move(self, pos):
        d = self.drag
        view = _view()
        if d is None or view is None:
            return
        box = self._boxes(d["kind"])[d["axis"]]
        if d["kind"] == "arm":
            t = self._ray_param(view, pos, d["base"], AXES[d["axis"]])
            if t is None or d["t0"] is None:
                return
            value = d["v0"] + round((t - d["t0"]) / STEP) * STEP
        else:
            a = self._screen_angle(view, pos, d["base"], AXES[d["axis"]])
            turn = (a - d["a0"] + 180.0) % 360.0 - 180.0
            value = d["v0"] + round(turn / STEP_DEG) * STEP_DEG
        if abs(box.value() - value) > 1e-9:
            box.setValue(value)

    def cancel(self):
        d, self.drag = self.drag, None
        if d is not None:
            self._boxes(d["kind"])[d["axis"]].setValue(d["v0"])

    def remove(self):
        self.timer.stop()
        self.cancel()
        self.clear()
        from . import events
        events.unregister("bodytriad")
        if _current and _current[0] is self:
            _current[:] = []


def _seg_dist(p, a, b):
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L < 1e-12 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def show(panel):
    try:
        return BodyTriad(panel)
    except Exception as _fw_err:
        _fw_log("bodytriad.py:show", _fw_err)
        return None
