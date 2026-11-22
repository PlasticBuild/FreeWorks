# SPDX-License-Identifier: LGPL-2.1-or-later
"""Answers kept until the event loop runs again.

The feature tree asks the same questions thousands of times while it paints one frame (every
row's flags, data and expanded state; the rollback bar's layout for each paint and tick). In a
150-feature part these repeats made scrolling, rollback and Ctrl+Q several times slower than the
rebuild itself. A value cached here lives until control returns to the event loop, so nothing can
change underneath it except inside the same Python call chain, and a key should carry what the
answer depends on (a document's object count, for instance).
"""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

_CACHE = {}
_armed = [False]


def _clear():
    _CACHE.clear()
    _armed[0] = False


def _arm():
    if _armed[0]:
        return
    try:
        from PySide import QtCore
        if QtCore.QCoreApplication.instance() is None or not __import__("FreeCAD").GuiUp:
            raise RuntimeError("no event loop")      # a timer would never fire: answers would be kept forever
        QtCore.QTimer.singleShot(0, _clear)
        _armed[0] = True
    except Exception:
        _CACHE.clear()      # no event loop (console): no caching


def get(key, compute):
    """compute() for key, once per pass of the event loop."""
    try:
        return _CACHE[key]
    except KeyError as _fw_err:
        _fw_log("tickcache.py:48", _fw_err)
    except TypeError:
        return compute()
    value = compute()
    _arm()
    if _armed[0]:
        _CACHE[key] = value
    return value


def clear():
    _clear()
