# SPDX-License-Identifier: LGPL-2.1-or-later
"""The PropertyManager's application-wide event hooks go through the add-on's one dispatcher
(events.py, Interface) when it is there: hook(name, types, handler) registers handler(obj, event)
-> bool for those event types; unhook(name) takes it out. Without events.py (an older tree) the
same handler sits in a filter of its own on the QApplication, as before."""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

from PySide import QtCore, QtWidgets

_own = {}       # name -> filter object, when the dispatcher is not there


class _Own(QtCore.QObject):
    def __init__(self, types, handler):
        super().__init__()
        self.types = set(types)
        self.handler = handler

    def eventFilter(self, obj, event):
        try:
            if not isinstance(event, QtCore.QEvent) or event.type() not in self.types:
                return False
            return bool(self.handler(obj, event))
        except Exception:
            return False


_live = [None]      # None: not probed yet; True: the dispatcher delivers; False: deaf, own filters


def _dispatcher():
    try:
        from . import events
    except Exception:
        return None
    if _live[0] is None:
        if _held():
            # extapps/72: start-up holds the add-on's application filters (extapps/64), the dispatcher's too, so a
            # probe now is never answered and every hook got a filter of its own for good (two more filters that
            # Qt calls for every event). The dispatcher is released with the others; asked again once it is.
            _recheck_later()
            return events
        _live[0] = _probe(events)
    return events if _live[0] else None


def _held():
    try:
        from . import safeguards
        return safeguards.HOLD is not None
    except Exception:
        return False


_LATER = []


def _recheck_later():
    if _LATER:
        return
    _LATER.append(1)
    try:
        QtCore.QTimer.singleShot(20000, _recheck)
    except Exception as _fw_err:
        _fw_log("pmevents.py:recheck", _fw_err)


def _recheck():
    """extapps/72: after start-up: when the dispatcher does not deliver after all, the hooks given to it move to
    filters of their own (as a deaf dispatcher at the first hook did)."""
    _LATER[:] = []
    if _held():
        _recheck_later()
        return
    try:
        from . import events
    except Exception:
        return
    if _live[0] is None:
        _live[0] = _probe(events)
    if _live[0]:
        return
    app = QtWidgets.QApplication.instance()
    for name, (types, handler) in list(_VIA.items()):
        try:
            events.unregister(name)
        except Exception as _fw_err:
            _fw_log("pmevents.py:recheck-unregister", _fw_err)
        if app is not None and name not in _own:
            f = _Own(types, handler)
            app.installEventFilter(f)
            _own[name] = f
    _VIA.clear()


_VIA = {}       # extapps/72: name -> (types, handler) hooked through the dispatcher


def _probe(events):
    """Once: an event of our own sent through the application must reach a handler registered
    with the dispatcher (the coordinator's ask, 09:47Z: on the PC events.py can be there but deaf)."""
    seen = []
    kind = QtCore.QEvent.Type(QtCore.QEvent.registerEventType())
    try:
        events.register("pm.probe", (kind,), lambda obj, event: seen.append(1) or False)
        target = QtCore.QObject()
        QtWidgets.QApplication.sendEvent(target, QtCore.QEvent(kind))
    except Exception:
        seen = []
    finally:
        try:
            events.unregister("pm.probe")
        except Exception as _fw_err:
            _fw_log("pmevents.py:66", _fw_err)
    if not seen:
        try:
            import FreeCAD as App
            App.Console.PrintLog("FreeCAD: the event dispatcher did not deliver a probe; the PropertyManager keeps its own filters\n")
        except Exception as _fw_err:
            _fw_log("pmevents.py:72", _fw_err)
    return bool(seen)


def hook(name, types, handler):
    """handler(obj, event) -> True to stop the event. A name hooks once (a later hook replaces)."""
    unhook(name)
    events = _dispatcher()
    if events is not None:
        try:
            events.register(name, tuple(types), handler)
            _VIA[name] = (tuple(types), handler)
            return "events"
        except Exception as _fw_err:
            _fw_log("pmevents.py:85", _fw_err)
    app = QtWidgets.QApplication.instance()
    if app is None:
        return None
    f = _Own(types, handler)
    app.installEventFilter(f)
    _own[name] = f
    return "own"


def unhook(name):
    _VIA.pop(name, None)
    events = _dispatcher()
    if events is not None:
        try:
            events.unregister(name)
        except Exception as _fw_err:
            _fw_log("pmevents.py:101", _fw_err)
    f = _own.pop(name, None)
    if f is not None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(f)
        f.deleteLater()


def hooked(name):
    events = _dispatcher()
    if events is not None and name in events.registered():
        return True
    return name in _own
