# SPDX-License-Identifier: LGPL-2.1-or-later
""




import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import paths

PARAM = "UndoWording"
HOOKED = "swUndoWordingHooked"
TICK = 1000
COMMANDS = (("Std_Undo", "Undo", "UndoNames"), ("Std_Redo", "Redo", "RedoNames"))

_watch = None


def enabled():
    return paths.params().GetBool(PARAM, True)


def wording(which, names):
    """'&Undo Pad' for the step at the top of `names`, or plain '&Undo' when there is none
    (the & keeps the menu's U / R key)."""
    name = (names or [""])[0].strip().replace("&", "&&")
    return "&%s %s" % (which, name) if name else "&" + which


def _actions(command):
    try:
        return list(Gui.Command.get(command).getAction())
    except Exception:
        return []


def refresh():
    doc = App.ActiveDocument
    for command, which, attr in COMMANDS:
        names = list(getattr(doc, attr, []) or []) if doc is not None and enabled() else []
        text = wording(which, names)
        for action in _actions(command):
            if action.text() != text:
                action.setText(text)


def _hook():
    try:
        for command, _which, _attr in COMMANDS:
            for action in _actions(command):
                for owner in action.associatedObjects():
                    if isinstance(owner, QtWidgets.QMenu) and not owner.property(HOOKED):
                        owner.setProperty(HOOKED, True)
                        owner.aboutToShow.connect(refresh)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Undo wording not hooked: %s\n" % error)


def install():
    global _watch
    if _watch is not None:
        return
    _watch = QtCore.QTimer()
    _watch.setInterval(TICK)
    _watch.timeout.connect(_hook)
    _watch.start()
    _hook()


def remove():
    global _watch
    if _watch is not None:
        _watch.stop()
    _watch = None
