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
from PySide import QtCore, QtGui, QtWidgets

VIEW = "User parameter:BaseApp/Preferences/View"
MS = {"Off": 0, "Slow": 1000, "Medium": 500, "Fast": 250}
MOUSE = {"Slow": 0.5, "Medium": 0.75, "Fast": 1.0}
_done = []


def _stored(text, default):
    try:
        from . import optionspages
        return str(optionspages.stored("View", text, default))
    except Exception:
        return default


def transition_ms(text):
    """Milliseconds of a Transitions setting: 'Hide/show component', 'Isolate' or 'View selector'."""
    return MS.get(_stored(text, "Fast"), 250)


def mouse_factor():
    return MOUSE.get(_stored("Mouse speed", "Fast"), 1.0)


# ------------------------------------------------------------------ fades
_running = {}


def fade(comps, start, end, ms, done=None):
    """Turns the components' see-through level from start to end over ms (a material override, as
    asmtools does); done() runs at the end. ms 0: done at once."""
    from . import asmtools
    comps = [c for c in comps if getattr(c, "ViewObject", None) is not None]
    if ms <= 0 or not comps:
        if done:
            done()
        return None
    olds = {c.Name: (c.ViewObject.OverrideMaterial, c.ViewObject.ShapeMaterial) for c in comps}
    steps = max(2, int(ms / 40))
    state = {"i": 0}
    timer = QtCore.QTimer()

    def tick():
        state["i"] += 1
        t = min(1.0, state["i"] / float(steps))
        for c in comps:
            try:
                asmtools._fade(c, start + (end - start) * t)
            except Exception as _fw_err:
                _fw_log("viewspeeds.py:74", _fw_err)
        if t >= 1.0:
            timer.stop()
            _running.pop(id(timer), None)
            _ends.pop(id(timer), None)
            for c in comps:
                old = olds.get(c.Name)
                if old is not None:
                    asmtools._restore(c, old)
            if done:
                done()
    def end_now():
        if timer.isActive():
            state["i"] = steps - 1
            tick()

    timer.timeout.connect(tick)
    timer.start(40)
    _running[id(timer)] = timer
    _ends[id(timer)] = end_now
    tick()
    return timer


_ends = {}          # running fades: id(timer) -> end it now


def settle():
    """Ends every running see-through fade at once on its end look (Exit Isolate right after Isolate
    would otherwise have the fade's end put Isolate's look back)."""
    for key, end in list(_ends.items()):
        try:
            end()
        except Exception as _fw_err:
            _fw_log("viewspeeds.py:108", _fw_err)
    _ends.clear()


def fading():
    return any(t.isActive() for t in list(_running.values()))


def _hook_hide_show():
    from . import asmmenu
    if getattr(asmmenu, "_fw_speeds", False):
        return
    plain = asmmenu.hide_show

    def hide_show(comp):
        ms = transition_ms("Hide/show component")
        if ms <= 0 or not hasattr(comp.ViewObject, "OverrideMaterial"):
            return plain(comp)
        if asmmenu.shown(comp):
            fade([comp], 0.0, 1.0, ms, lambda: setattr(comp.ViewObject, "Visibility", False))
        else:
            comp.ViewObject.Visibility = True
            fade([comp], 1.0, 0.0, ms)
    asmmenu.hide_show = hide_show
    asmmenu._fw_speeds = True


def _hook_isolate():
    from . import asmisolate, asmtools
    cls = asmisolate.Isolate
    if getattr(cls, "_fw_speeds", False):
        return
    plain = cls.apply

    def apply(self, mode=None):
        plain(self, mode)
        ms = transition_ms("Isolate")
        if ms > 0 and self.mode not in ("Hidden", "Wireframe"):
            others = [c for c in self.others() if hasattr(c.ViewObject, "OverrideMaterial")]
            # the fade ends on Isolate's own see-through look, which stays
            def keep():
                for c in others:
                    asmtools._fade(c)
            fade(others, 0.0, asmtools.FADE, ms, keep)
    cls.apply = apply
    cls._fw_speeds = True


def _hook_view_selector():
    from . import viewselector
    cls = getattr(viewselector, "ViewSelector", None)
    if cls is None:
        for v in vars(viewselector).values():
            if isinstance(v, type) and hasattr(v, "turn_to"):
                cls = v
                break
    if cls is None or getattr(cls, "_fw_speeds", False):
        return
    plain = cls.turn_to

    def turn_to(self, signs):
        grp = App.ParamGet(VIEW)
        ms = transition_ms("View selector")
        was = (grp.GetBool("UseNavigationAnimations", True), grp.GetInt("AnimationDuration", 250))
        grp.SetBool("UseNavigationAnimations", ms > 0)
        if ms > 0:
            grp.SetInt("AnimationDuration", ms)
        try:
            return plain(self, signs)
        finally:
            def back():
                grp.SetBool("UseNavigationAnimations", was[0])
                grp.SetInt("AnimationDuration", was[1])
            QtCore.QTimer.singleShot(0, back)   # FreeCAD reads them when the turn starts
    cls.turn_to = turn_to
    cls._fw_speeds = True


# ------------------------------------------------------------------ mouse speed
class MouseSpeed(QtCore.QObject):
    """A plain middle-button drag in a 3D view (the turn) moves the pointer the view sees by the
    Mouse speed factor from where the drag started; pan (Ctrl) and zoom (Shift) keep their speed."""

    def __init__(self):
        super().__init__()
        self.start = None

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QWidgetItem) instead of the event
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.MiddleButton:
            self.start = event.position() if event.modifiers() == QtCore.Qt.NoModifier else None
            return False
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.MiddleButton:
            self.start = None
            return False
        if t != QtCore.QEvent.MouseMove or self.start is None or getattr(self, "_inside", False):
            return False
        if not (event.buttons() & QtCore.Qt.MiddleButton) or event.modifiers() != QtCore.Qt.NoModifier:
            return False
        k = mouse_factor()
        if k >= 0.999 or not isinstance(obj, QtWidgets.QWidget) or not _is_3d(obj):
            return False
        p = event.position()
        q = QtCore.QPointF(self.start.x() + (p.x() - self.start.x()) * k, self.start.y() + (p.y() - self.start.y()) * k)
        ev = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, q, obj.mapToGlobal(q.toPoint()), event.button(),
                               event.buttons(), event.modifiers())
        self._inside = True
        try:
            QtWidgets.QApplication.sendEvent(obj, ev)
        finally:
            self._inside = False
        return True


def _is_3d(w):
    while w is not None:
        if type(w).__name__ in ("View3DInventorViewer", "QuarterWidget") or "View3DInventor" in w.metaObject().className():
            return True
        w = w.parentWidget()
    return False


def install():
    if _done:
        return
    _done.append(True)
    for hook in (_hook_hide_show, _hook_isolate, _hook_view_selector):
        try:
            hook()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: view speeds: %s\n" % error)
    try:
        f = MouseSpeed()
        _done.append(f)
        # the filter sees every event of the application: it is only in while Mouse speed is below Fast
        f.on = False
        t = QtCore.QTimer(f)
        t.timeout.connect(lambda: _follow_speed(f))
        t.start(1500)
        _follow_speed(f)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: mouse speed: %s\n" % error)


def _follow_speed(f):
    try:
        want = mouse_factor() < 0.999
    except Exception:
        want = False
    if want != f.on:
        app = QtWidgets.QApplication.instance()
        (app.installEventFilter if want else app.removeEventFilter)(f)
        f.on = want
