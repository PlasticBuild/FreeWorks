# SPDX-License-Identifier: LGPL-2.1-or-later
""


_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import re

import FreeCAD as App
import FreeCADGui as Gui

PREFIX = "SWStyle_ToolbarToggle_"


def native(name):
    return PREFIX + re.sub(r"\W", "", name)


class ToolbarToggle:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        return {"MenuText": self.name, "ToolTip": "Shows or hides the %s toolbar" % self.name}

    def IsActive(self):
        return True

    def Activated(self):
        from . import swtoolbars
        try:
            from . import shell as sh
            s = sh.shell()
        except Exception:
            s = None
        swtoolbars.show(s, self.name, not swtoolbars.is_shown(self.name))


def names():
    """[(command name, toolbar name)] in View > Toolbars order."""
    try:
        from . import swtoolbars
        return [(native(n), n) for n, _k in swtoolbars.TOOLBARS]
    except Exception:
        return []


def register():
    have = set(Gui.listCommands())
    for cmd, name in names():
        if cmd not in have:
            Gui.addCommand(cmd, ToolbarToggle(name))


_ACTIONS = {}


def action(cmd):
    """The main window's action for a toolbar command (FreeCAD makes a command's own action only once
    the command sits in a menu or toolbar, and these sit in neither)."""
    a = _ACTIONS.get(cmd)
    try:
        if a is not None:
            a.objectName()
            return a
    except RuntimeError as _fw_err:
        _fw_log("tbkeys.py:76", _fw_err)
    return None


def attach():
    """The commands' actions on the main window, where their keys work wherever the focus is."""
    mw = Gui.getMainWindow()
    if mw is None:
        return
    from PySide import QtGui
    for cmd, name in names():
        if action(cmd) is not None:
            continue
        a = QtGui.QAction(name, mw)
        a.setObjectName(cmd)
        a.triggered.connect(lambda _c=False, n=name: ToolbarToggle(n).Activated())
        try:
            key = App.ParamGet("User parameter:BaseApp/Preferences/Shortcut").GetString(cmd, "")
            if key:
                a.setShortcut(QtGui.QKeySequence(key))
        except Exception as _fw_err:
            _fw_log("tbkeys.py:97", _fw_err)
        mw.addAction(a)
        _ACTIONS[cmd] = a
