# SPDX-License-Identifier: LGPL-2.1-or-later
"""Check marks for addon commands that toggle something (View Planes, View Sketches...).

FreeCAD makes a command's QAction only when the command goes into one of its own menus or
toolbars, so a CommandManager button bound to such a command has no action to read. A module
registers a function that says whether its command is on; widgets.Binding asks here.
"""
_fns = {}


def register(name, fn):
    _fns[name] = fn


def _wrapped(name):
    """# look-audit skflow-1120: toolfirst.py's SWStyle_TF_<command> wrapper is on when its command is."""
    if name not in _fns and isinstance(name, str) and name.startswith("SWStyle_TF_"):
        return name[len("SWStyle_TF_"):]
    return name


def known(name):
    return _wrapped(name) in _fns


def checked(name):
    fn = _fns.get(_wrapped(name))
    if fn is None:
        return False
    try:
        return bool(fn())
    except Exception:
        return False


# Toggles whose own files register nothing: (module, function, argument). Looked up when first asked,
# so this file imports nothing at load.
_LAZY = {"SWStyle_AutomaticSolve": ("toolsextras", "automatic_solve", None),
         "FreeWorks_PenTouch": ("pentools", "setting", "PenTouch"),
         "FreeWorks_PenAutoShape": ("pentools", "setting", "PenAutoShape"),
         "FreeWorks_PenAutoEntities": ("pentools", "setting", "PenAutoEntities"),
         "FreeWorks_PenAutoSketchEntities": ("pentools", "setting", "PenAutoSketchEntities")}


def _lazy(name):
    row = _LAZY.get(name)
    if row is None or name in _fns:
        return
    mod, fn, arg = row

    def state(mod=mod, fn=fn, arg=arg):
        import importlib
        f = getattr(importlib.import_module("swstyle." + mod), fn)
        return f(arg) if arg is not None else f()
    _fns[name] = state


for _n in _LAZY:
    _lazy(_n)


def run(name):
    """Runs a known toggle the other way round. FreeCAD's runCommand(name, 0) hands Activated
    checked=False, so a menu item or button for a toggle that has no QAction could only turn it off.
    False when name is not a known toggle (the caller runs it as usual)."""
    if name not in _fns:
        return False
    import FreeCADGui as Gui
    Gui.runCommand(name, 0 if checked(name) else 1)
    return True
