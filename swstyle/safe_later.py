"""Deferred calls that must not run after their panel is gone (lifetime3-1126).

A panel queues QtCore.QTimer.singleShot(0, lambda: self.x()) from a selection or click handler; when the
PropertyManager closes first, the callback met a deleted Qt widget and raised RuntimeError (or ReferenceError)
into the console. later() runs the callback unless the owner's guard widget has been deleted by then.
Plain function, no patching of QTimer.
"""
from PySide import QtCore

try:
    import shiboken6 as _shiboken
except Exception:           # pragma: no cover
    _shiboken = None


def alive(widget):
    """True unless widget is a Qt object whose C++ side has been deleted (None counts as alive: not built yet)."""
    if widget is None or _shiboken is None:
        return True
    try:
        return bool(_shiboken.isValid(widget))
    except Exception:
        return True


def later(ms, fn, owner=None, attr=None):
    """QTimer.singleShot(ms, fn), skipped when owner.<attr> is a deleted Qt widget at that time."""
    def run():
        if owner is not None and attr and not alive(getattr(owner, attr, None)):
            return
        fn()
    QtCore.QTimer.singleShot(ms, run)
