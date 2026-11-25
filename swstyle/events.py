# SPDX-License-Identifier: LGPL-2.1-or-later
"""One application-wide Qt event filter for the whole add-on.

Every module that needs to see application events registers a handler for the event types it
cares about; Qt calls one filter, and only the handlers for that type run. Before this, each
module installed its own QApplication filter (15 of them), and every one of them was called for
every event in FreeCAD.

    events.register("facehover", (QEvent.MouseMove, QEvent.Leave), handler)   # handler(obj, event) -> bool
    events.unregister("facehover")

A handler that returns True stops the event, as an eventFilter does. A handler that raises is
reported once in the Report view and keeps running. Handlers run in the order they registered.
Modules that still install their own filter keep working; they move over one at a time."""
import FreeCAD as App
from PySide import QtCore, QtWidgets

_BY_TYPE = {}           # QEvent.Type -> [(name, handler)]
_NAMES = {}             # name -> (types, handler)
_FAILED = set()
_CONSUMED = set()       # (name, QEvent.Type) logged once when a handler eats an event
_filter = None


class _Dispatcher(QtCore.QObject):
    FW_EVENT_TYPES = _BY_TYPE   # extapps/63: the guard (safeguards.py) answers False for types nothing is registered for

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        handlers = _BY_TYPE.get(event.type())
        if not handlers:
            return False
        for name, handler in list(handlers):
            try:
                if handler(obj, event):
                    key = (name, event.type())
                    if key not in _CONSUMED:
                        _CONSUMED.add(key)
                        App.Console.PrintLog("FreeCAD events: %s consumed %s\n" % (name, event.type()))
                    return True
            except Exception as error:
                if name not in _FAILED:
                    _FAILED.add(name)
                    App.Console.PrintWarning("FreeCAD event handler %s: %s\n" % (name, error))
        return False


def install():
    global _filter
    app = QtWidgets.QApplication.instance()
    if _filter is None and app is not None:
        _filter = _Dispatcher(app)
        app.installEventFilter(_filter)
    return _filter


def remove():
    global _filter
    app = QtWidgets.QApplication.instance()
    if _filter is not None and app is not None:
        app.removeEventFilter(_filter)
    _filter = None


def register(name, types, handler):
    """Registers handler(obj, event) -> bool for the event types; a name registers once (the
    later registration replaces the earlier one)."""
    unregister(name)
    types = tuple(types)
    _NAMES[name] = (types, handler)
    for t in types:
        _BY_TYPE.setdefault(t, []).append((name, handler))
    _FAILED.discard(name)
    install()


def unregister(name):
    entry = _NAMES.pop(name, None)
    if entry is None:
        return False
    for t in entry[0]:
        _BY_TYPE[t] = [(n, h) for n, h in _BY_TYPE.get(t, []) if n != name]
        if not _BY_TYPE[t]:
            del _BY_TYPE[t]
    return True


def registered():
    return dict(_NAMES)


def installed():
    return _filter is not None
