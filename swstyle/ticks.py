# SPDX-License-Identifier: LGPL-2.1-or-later
""















import sys
import time
import weakref

import FreeCAD as App
from PySide import QtCore

PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks"
IDLE_AFTER = 15.0           # IdleRest off: seconds without anything happening before the polling slows
FACTOR = 4                  # IdleRest off: the slowed interval: base * FACTOR, at most CAP_MS (never faster than the base)
CAP_MS = 2000
DEEP_AFTER = 10.0           # seconds without anything happening before the pollers stop
CALM_AFTER = 2.0            # extapps/70: seconds without anything happening before the pollers run at 1/FACTOR rate
DEEP_MAX_MS = 10000         # repeating timers at least this slow are left alone (they cost nothing)
POLLERS = frozenset([
    ("swstyle.activewin", "install"),
    ("swstyle.altface", "install"),
    ("swstyle.asmctrlcopy", "install"),
    ("swstyle.asmmotion", "__init__"),
    ("swstyle.asmstudytabs", "install"),
    ("swstyle.chrome", "__init__"),
    ("swstyle.cosmeticthread", "start"),
    ("swstyle.dimcommands", "start"),
    ("swstyle.dimensionpm", "__init__"),
    ("swstyle.dismissedicon", "__init__"),
    ("swstyle.docstyle", "install"),
    ("swstyle.drawhud", "register"),
    ("swstyle.drawlineformat", "install"),
    ("swstyle.drawpmparts", "register"),
    ("swstyle.drawsheet", "install"),
    ("swstyle.firststart", "install"),
    ("swstyle.flyouttree", "__init__"),
    ("swstyle.fmtree", "__init__"),
    ("swstyle.freezeview", "__init__"),
    ("swstyle.fwsketch.bigsketch", "__init__"),
    ("swstyle.fwsketch.pointshow", "__init__"),
    ("swstyle.fwsketch.splinehandles", "start"),
    ("swstyle.fwsketch.splineshow", "__init__"),
    ("swstyle.fwsketch.virtualsharps", "__init__"),
    ("swstyle.instant3d", "start"),
    ("swstyle.leftpane", "__init__"),
    ("swstyle.linebar", "__init__"),
    ("swstyle.linestyles", "install"),
    ("swstyle.modelorigin", "__init__"),
    ("swstyle.multibody", "__init__"),
    ("swstyle.nativepms", "install"),
    ("swstyle.optionsextras2", "install"),
    ("swstyle.optionsextras3", "install"),
    ("swstyle.pathlength", "__init__"),
    ("swstyle.pmprompts", "install"),
    ("swstyle.quicktips", "__init__"),
    ("swstyle.rapidsketch", "__init__"),
    ("swstyle.relationspm", "__init__"),
    ("swstyle.rollbackbar", "__init__"),
    ("swstyle.saveas", "install_smart_save"),
    ("swstyle.selfilter", "__init__"),
    ("swstyle.shell", "enable"),
    ("swstyle.silhouette", "__init__"),
    ("swstyle.simplifiedui", "install"),
    ("swstyle.sketchcenterlines", "install"),
    ("swstyle.sketchorigin", "__init__"),
    ("swstyle.sketchtriad", "start"),
    ("swstyle.sketchview", "__init__"),
    ("swstyle.sketchxpert", "__init__"),
    ("swstyle.splinetools", "__init__"),
    ("swstyle.swmenus", "install"),
    ("swstyle.tabstrip", "apply"),
    ("swstyle.treelook", "install"),
    ("swstyle.treerefs", "install"),
    ("swstyle.undowording", "install"),
    ("swstyle.viewanim", "install"),
    ("swstyle.viewmenu", "install"),
    ("swstyle.viewspeeds", "install"),
    ("swstyle.windowmenu", "install"),
])
_reg = []                   # [timer, base ms, slowed ms or None]  (slow_when_idle)
_adopted = {}               # id(timer) -> weakref to a poller timer
_stopped = {}               # id(timer) -> weakref: the timers resting stopped (and only those)
# pollers that only keep the window's chrome current: held while a mouse button is down in a 3D view (extapps/61)
DRAG_HOLD = frozenset([("swstyle.rollbackbar", "__init__"), ("swstyle.tabstrip", "apply"), ("swstyle.shell", "enable"),
                       ("swstyle.shell", "__init__")])
_sites = {}                 # id(timer) -> (module, function) that started it, for the POLLERS ones
_held = {}                  # id(timer) -> weakref: the timers a drag stopped (and only those)
_s = {"last": time.monotonic(), "slow": False, "deep": False, "timer": None, "ready": False, "hooked": False,
      "rests": 0, "wakes": 0}
_orig = {"start": None, "stop": None}


def _valid(timer):
    try:
        from .safeguards import valid
        return valid(timer)
    except Exception:
        return True


def _param(name):
    try:
        return App.ParamGet(PARAM).GetBool(name, True)
    except Exception:
        return True


def enabled():
    return _param("IdleThrottle")


def rest_enabled():
    return _param("IdleRest")


# ------------------------------------------------------------------ which timers
def _adopt(timer):
    try:
        if timer.isSingleShot() or timer.interval() >= DEEP_MAX_MS:
            return False
        _adopted[id(timer)] = weakref.ref(timer)
        return True
    except Exception:
        return False


def _start_hook(self, *args):
    _orig["start"](self, *args)
    try:
        key = id(self)
        if key in _stopped:
            del _stopped[key]           # its own code started it again: it runs, as it asked
        _held.pop(key, None)
        if key not in _sites:
            f = sys._getframe(1)
            site = (f.f_globals.get("__name__"), f.f_code.co_name)
            if site in POLLERS or site in DRAG_HOLD:
                _sites[key] = site
                if key not in _adopted:
                    _adopt(self)
    except Exception:
        pass


def _stop_hook(self, *args):
    _orig["stop"](self, *args)
    try:
        _stopped.pop(id(self), None)    # its own code stopped it: do not start it again on waking
        _held.pop(id(self), None)
    except Exception:
        pass


def install_hook():
    """Called first thing at start-up, before any poller starts. Idempotent."""
    if _s["hooked"]:
        return
    _s["hooked"] = True
    _orig["start"], _orig["stop"] = QtCore.QTimer.start, QtCore.QTimer.stop
    QtCore.QTimer.start = _start_hook
    QtCore.QTimer.stop = _stop_hook
    _ensure()


def slow_when_idle(timer):
    """Registers a repeating QTimer (call it after the interval is set); returns the timer."""
    _reg.append([timer, timer.interval(), None])
    _adopt(timer)
    _ensure()
    return timer


# ------------------------------------------------------------------ resting and waking
def _live(ref):
    timer = ref()
    if timer is None or not _valid(timer):
        return None
    return timer


_calmed = {}                # extapps/70: id(timer) -> (weakref, its own interval, the slowed interval)


def calm_enabled():
    return _param("IdleCalm")


def calm():
    """extapps/70: every running poller at a quarter of its rate, at most every CAP_MS (never faster than its own):
    2 s after the last thing that happened (an opened file kept ~70 pollers at full rate until the 10 s rest:
    about 2 s of CPU after each open)."""
    _s["calm"] = True
    for key, ref in list(_adopted.items()):
        if key in _calmed:
            continue
        timer = _live(ref)
        if timer is None:
            continue
        try:
            base = timer.interval()
            target = min(base * FACTOR, max(base, CAP_MS))
            if target > base and timer.isActive():
                timer.setInterval(target)
                _calmed[key] = (ref, base, target)
        except RuntimeError:
            _adopted.pop(key, None)


def uncalm():
    """Back to full rate (something happened). A timer whose code changed its interval meanwhile keeps that."""
    _s["calm"] = False
    for key, (ref, base, slowed) in list(_calmed.items()):
        timer = _live(ref)
        try:
            if timer is not None and timer.interval() == slowed:
                active = timer.isActive()
                timer.setInterval(base)
                if not active:
                    (_orig["stop"] or QtCore.QTimer.stop)(timer)    # setInterval leaves a stopped timer stopped
        except RuntimeError:
            pass
    _calmed.clear()


def rest():
    """Stops every poller that is running (nothing is happening)."""
    _s["deep"] = True
    _s["rests"] += 1
    _watch_changes(True)
    stop = _orig["stop"] or QtCore.QTimer.stop
    for key, ref in list(_adopted.items()):
        timer = _live(ref)
        if timer is None:
            _adopted.pop(key, None)
            continue
        try:
            if timer.isActive():
                stop(timer)
                _stopped[key] = ref
        except RuntimeError:
            _adopted.pop(key, None)


def wake():
    """Starts again every poller rest() stopped, at its own interval."""
    _s["deep"] = False
    _s["wakes"] += 1
    _watch_changes(False)
    start = _orig["start"] or QtCore.QTimer.start
    for key, ref in list(_stopped.items()):
        timer = _live(ref)
        try:
            if timer is not None and not timer.isActive():
                start(timer)
        except RuntimeError:
            pass
    _stopped.clear()


def _in_3d_view(obj):
    """A widget inside a 3D view (its viewport or a child of it)."""
    try:
        w = obj
        for _i in range(6):
            if w is None:
                return False
            if "View3DInventor" in w.metaObject().className():
                return True
            w = w.parent()
    except Exception:
        return False
    return False


def drag_start():
    """A mouse button went down in a 3D view: the chrome pollers wait until it comes up."""
    _s["drag"] = True
    stop = _orig["stop"] or QtCore.QTimer.stop
    for key, site in list(_sites.items()):
        if site not in DRAG_HOLD:
            continue
        ref = _adopted.get(key)
        timer = _live(ref) if ref is not None else None
        if timer is None:
            _sites.pop(key, None)
            continue
        try:
            if timer.isActive():
                stop(timer)
                _held[key] = ref
        except RuntimeError:
            _sites.pop(key, None)


def drag_end():
    _s["drag"] = False
    start = _orig["start"] or QtCore.QTimer.start
    for key, ref in list(_held.items()):
        timer = _live(ref)
        try:
            if timer is not None and not timer.isActive() and not _s["deep"]:
                start(timer)
            elif timer is not None and _s["deep"]:
                _stopped[key] = ref     # resting meanwhile: waking starts it
        except RuntimeError:
            pass
    _held.clear()


def dragging():
    return bool(_s.get("drag"))


_PRESS = QtCore.QEvent.MouseButtonPress
_RELEASE = QtCore.QEvent.MouseButtonRelease


def _activity(_obj=None, _event=None):
    _s["last"] = time.monotonic()
    if _event is not None:
        try:
            t = _event.type()
            if t == _PRESS:
                if not _s.get("drag") and _in_3d_view(_obj):
                    drag_start()
            elif t == _RELEASE and _s.get("drag"):
                drag_end()
        except Exception:
            pass
    if _s["deep"]:
        wake()
    if _s.get("calm"):
        uncalm()            # extapps/70
    if _s["slow"]:
        speed_up()
    return False


def _window_activity(obj, event):
    """Shown, resized, maximized, activated: only for windows (a tiled or maximized main window, a dialog opening)."""
    try:
        if obj.isWidgetType() and obj.isWindow():
            _activity()
    except Exception:
        pass
    return False


def slow_down():
    _s["slow"] = True
    for entry in list(_reg):
        timer, base, slowed = entry
        if not _valid(timer):
            _reg.remove(entry)
            continue
        try:
            current = timer.interval()
            if slowed is not None and current != slowed:
                entry[1] = base = current           # its code changed the interval: that is the base now
            elif slowed is None and current != base:
                entry[1] = base = current
            target = min(base * FACTOR, max(base, CAP_MS))
            if target > base and slowed is None:
                timer.setInterval(target)
                entry[2] = target
        except RuntimeError:
            _reg.remove(entry)


def speed_up():
    _s["slow"] = False
    for entry in list(_reg):
        timer, base, slowed = entry
        if slowed is None:
            continue
        entry[2] = None
        try:
            if _valid(timer):
                if timer.interval() == slowed:
                    timer.setInterval(base)
                else:
                    entry[1] = timer.interval()      # changed meanwhile: keep that
            else:
                _reg.remove(entry)
        except RuntimeError:
            _reg.remove(entry)


def _tick():
    if _s.get("drag"):
        try:
            up = __import__("PySide.QtWidgets", fromlist=["x"]).QApplication.mouseButtons() == QtCore.Qt.NoButton
        except Exception:
            up = True
        if up:
            drag_end()                  # the release went elsewhere
    if not enabled():
        if _s["deep"]:
            wake()
        if _s.get("calm"):
            uncalm()
        if _s["slow"]:
            speed_up()
        return
    quiet = time.monotonic() - _s["last"]
    if rest_enabled():
        if _s["slow"]:
            speed_up()
        if quiet > CALM_AFTER and not _s["deep"] and not _s.get("drag") and calm_enabled():
            calm()          # extapps/70: also takes in pollers started since the last calm
        elif _s.get("calm") and not calm_enabled():
            uncalm()
        if not _s["deep"] and quiet > DEEP_AFTER:
            try:
                held = QtCore.QCoreApplication.instance() is not None and \
                    __import__("PySide.QtWidgets", fromlist=["x"]).QApplication.mouseButtons() != QtCore.Qt.NoButton
            except Exception:
                held = False
            if not held:
                rest()
        return
    if _s["deep"]:
        wake()
    if not _s["slow"] and quiet > IDLE_AFTER:
        slow_down()


class _Docs:
    """A document made, opened, activated, changed, recomputed or closed is activity (macros and scripts)."""
    def slotCreatedDocument(self, doc):
        _activity()

    def slotActivateDocument(self, doc):
        _activity()

    def slotRecomputedDocument(self, doc):
        _activity()

    def slotDeletedDocument(self, doc):
        _activity()

    def slotCreatedObject(self, obj):
        _activity()

    def slotDeletedObject(self, obj):
        _activity()

    def slotUndoDocument(self, doc):
        _activity()

    def slotRedoDocument(self, doc):
        _activity()


class _Changes:
    """Only while resting: the first property change (a macro, the Python console, a script) wakes the pollers. Not kept
    the rest of the time, so a model opening or recomputing does not pay a call per change for it."""
    def slotChangedObject(self, obj, prop):
        _activity()


def _watch_changes(on):
    try:
        if on and _s.get("changes") is None:
            _s["changes"] = _Changes()
            App.addDocumentObserver(_s["changes"])
        elif not on and _s.get("changes") is not None:
            obs, _s["changes"] = _s["changes"], None
            # not from inside the notification that woke us: FreeCAD is still calling the observer
            QtCore.QTimer.singleShot(0, lambda: App.removeDocumentObserver(obs))
    except Exception as error:
        App.Console.PrintLog("FreeCAD ticks: %s\n" % error)


class _Selection:
    def addSelection(self, *args):
        _activity()

    def removeSelection(self, *args):
        _activity()

    def setSelection(self, *args):
        _activity()

    def clearSelection(self, *args):
        _activity()


def _ensure():
    if _s["ready"]:
        return
    _s["ready"] = True
    try:
        from . import events
        E = QtCore.QEvent
        types = [E.MouseMove, E.MouseButtonPress, E.MouseButtonRelease, E.MouseButtonDblClick, E.Wheel, E.KeyPress, E.KeyRelease,
                 E.TouchBegin, E.ShortcutOverride]
        for name in ("TabletMove", "TabletPress", "NativeGesture", "Gesture"):
            if hasattr(E, name):
                types.append(getattr(E, name))
        events.register("ticks", types, _activity)
        win = [E.Show, E.Resize, E.WindowStateChange, E.WindowActivate, E.ActivationChange]
        if hasattr(E, "ApplicationStateChange"):
            win.append(E.ApplicationStateChange)
        events.register("ticks.windows", win, _window_activity)
    except Exception as error:
        App.Console.PrintLog("FreeCAD ticks: %s\n" % error)
    try:
        _s["docs"] = _Docs()
        App.addDocumentObserver(_s["docs"])
    except Exception as error:
        App.Console.PrintLog("FreeCAD ticks: %s\n" % error)
    try:
        if App.GuiUp:
            import FreeCADGui as Gui
            _s["sel"] = _Selection()
            Gui.Selection.addObserver(_s["sel"])
    except Exception as error:
        App.Console.PrintLog("FreeCAD ticks: %s\n" % error)
    t = QtCore.QTimer()
    t.setInterval(1000)
    t.timeout.connect(_tick)
    (_orig["start"] or QtCore.QTimer.start)(t)
    _s["timer"] = t
