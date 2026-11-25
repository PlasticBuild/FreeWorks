# SPDX-License-Identifier: LGPL-2.1-or-later
"""The sketch tools' application-wide event handlers (fix65), in one application filter
instead of a QApplication filter each.

    appevents.listen(owner, (QEvent.MouseMove, ...))     # owner.eventFilter(obj, event) -> bool
    appevents.stop(owner)

They share one application filter of our own (fix71b), which lets every other event type go at
once; inside it the newest handler runs first, as Qt runs the newest application filter first (a
running tool ahead of the drag watcher that was there before it)."""

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
from PySide import QtCore, QtWidgets

NAME = "fwsketch"
_stack = []          # [(key, types, handler)], oldest first
_failed = set()
_own = [None]        # the fallback application filter


def _key(owner):
    return "%s.%x" % (type(owner).__name__, id(owner))


def dispatch(obj, event):
    if not isinstance(event, QtCore.QEvent):
        return False
    t = event.type()
    for key, types, handler in reversed(list(_stack)):
        if t not in types:
            continue
        try:
            if handler(obj, event):
                return True
        except Exception as error:
            if key not in _failed:
                _failed.add(key)
                App.Console.PrintWarning("FreeCAD sketch event handler %s: %s\n" % (key, error))
    return False


_types = [frozenset()]  # every type some handler wants: other events leave at once


class _LiveTypes:
    """`t in _LiveTypes()` is `t in _types[0]` as it is now (_sync replaces the set)."""
    __slots__ = ()

    def __contains__(self, t):
        return t in _types[0]


class _Own(QtCore.QObject):
    FW_EVENT_TYPES = _LiveTypes()   # extapps/63: the guard (safeguards.py) answers False for the other types

    def eventFilter(self, obj, event):
        try:
            if event.type() not in _types[0]:
                return False
        except Exception:
            return False
        return dispatch(obj, event)


def _sync():
    """One application filter of our own, moved to the front whenever a handler starts.

    fix71b (2026-11-05): through the add-on's shared filter (events.py) the sketch tools ran
    behind every application filter installed after it, and on the PC some of those took the
    keys and drags first: typed-value boxes, drags and Smart Dimension went dead. Qt runs the
    newest application filter first, so (re)installing ours when a tool starts puts the running
    tool ahead of them again, as before fix65."""
    types = set()
    for _k, ts, _h in _stack:
        types.update(ts)
    _types[0] = frozenset(types)
    try:
        from .. import events as shared
        shared.unregister(NAME)        # an older copy of us may have registered there
    except Exception as _fw_err:
        _fw_log("fwsketch/appevents.py:83", _fw_err)
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    if types:
        if _own[0] is None:
            _own[0] = _Own(app)
        app.installEventFilter(_own[0])  # again: Qt moves an installed filter to the front
    elif _own[0] is not None:
        app.removeEventFilter(_own[0])
        _own[0] = None


def listen(owner, types, handler=None):
    """owner's handler (its eventFilter) sees the application's events of these types."""
    key = _key(owner)
    _stack[:] = [e for e in _stack if e[0] != key]
    _stack.append((key, frozenset(types), handler or owner.eventFilter))
    _failed.discard(key)
    _sync()


def stop(owner):
    key = _key(owner)
    before = len(_stack)
    _stack[:] = [e for e in _stack if e[0] != key]
    if len(_stack) != before:
        _sync()


def listening(owner):
    return any(e[0] == _key(owner) for e in _stack)
