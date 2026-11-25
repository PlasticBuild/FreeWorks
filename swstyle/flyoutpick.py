# SPDX-License-Identifier: LGPL-2.1-or-later
"""Commands that need a pick, never greyed (Ati: a greyed entry counts as a dead one).

In a flyout or menu, a command of PICK_FIRST that cannot run because nothing is picked stays
enabled: clicking it puts a prompt on the status bar, and the first pick in the graphics area or the
tree runs it. A command of HIDE_WHEN_OFF that has nothing to work with (Paste Appearance with
nothing copied) is left out of the flyout instead.
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


import FreeCADGui as Gui
from PySide import QtCore

PICK_FIRST = {
    "SWStyle_CopyAppearance": "Copy Appearance: select the face, feature, body or part to copy from",
    "SWStyle_ChangeTransparency": "Change Transparency: select the bodies or parts",
    "Std_ToggleTransparency": "Change Transparency: select the bodies or parts",
    "Std_ToggleVisibility": "Hide/Show: select the items to hide or show",
    "Std_HideSelection": "Hide: select the items to hide",
    "Std_ShowSelection": "Show: select the items to show",
}
HIDE_WHEN_OFF = ("SWStyle_PasteAppearance",)

_WAITING = []


class _Pick:
    def __init__(self, command):
        self.command = command

    def addSelection(self, doc, obj, sub, pnt):
        stop()
        QtCore.QTimer.singleShot(0, lambda c=self.command: Gui.runCommand(c, 0))


def stop():
    for o in _WAITING:
        try:
            Gui.Selection.removeObserver(o)
        except Exception as _fw_err:
            _fw_log("flyoutpick.py:stop", _fw_err)
    del _WAITING[:]


def waiting():
    return _WAITING[0].command if _WAITING else None


def start(command):
    """Asks for the pick on the status bar; the first pick runs command."""
    stop()
    o = _Pick(command)
    Gui.Selection.addObserver(o)
    _WAITING.append(o)
    try:
        Gui.getMainWindow().statusBar().showMessage(PICK_FIRST.get(command, "Select the items first"))
    except Exception as _fw_err:
        _fw_log("flyoutpick.py:prompt", _fw_err)


def fix_action(act, command, enabled):
    """A flyout row for command: (keep, run) where keep False leaves the row out and run, when not
    None, is what a click does instead (ask for the pick)."""
    if enabled or not command:
        return True, None
    if command in HIDE_WHEN_OFF:
        return False, None
    if command in PICK_FIRST:
        return True, lambda c=command: start(c)
    return True, None
