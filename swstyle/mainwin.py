# SPDX-License-Identifier: LGPL-2.1-or-later
""











import FreeCADGui as Gui

try:
    from shiboken6 import isValid as _is_valid
except ImportError:                     # pragma: no cover
    try:
        from shiboken2 import isValid as _is_valid
    except ImportError:
        _is_valid = None

_orig = None
_cached = [None]


def get_main_window():
    w = _cached[0]
    if w is not None:
        try:
            if _is_valid(w):
                return w
        except Exception:
            pass
        _cached[0] = None
    w = _orig()
    if w is not None and _is_valid is not None:
        _cached[0] = w
    return w


def install():
    global _orig
    if _orig is not None or _is_valid is None:
        return False
    try:
        import FreeCAD as App
        if App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").GetBool("MainWindowCacheOff", False):
            return False
    except Exception:
        pass
    _orig = Gui.getMainWindow
    get_main_window.__doc__ = _orig.__doc__
    Gui.getMainWindow = get_main_window
    return True
