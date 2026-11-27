# SPDX-License-Identifier: LGPL-2.1-or-later
""









import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui

Qt = QtCore.Qt


def _fw_log(site, err):
    try:
        App.Console.PrintLog("FreeCAD: %s: %s\n" % (site, err))
    except Exception:
        pass



COMMANDS = (
    ("SWStyle_RepeatLastCommand", "Edit", "Repeat Last Command", "Return"),
    ("SWStyle_HideHovered", "Others", "Hide the Hovered-over Component/Bodies", "Tab"),
    ("SWStyle_ShowHovered", "Others", "Show the Hovered-over Component/Bodies", "Shift+Tab"),
    ("SWStyle_ShowAllHidden", "Others", "Show all the hidden Components/Bodies", "Ctrl+Shift+Tab"),
    ("SWStyle_MoveToPointer", "Others", "Move Selection Breadcrumbs, Confirmation Corner and Toolbar to Pointer", "D"),
    ("SWStyle_CommandOptionToggle", "Others", "Command option toggle", "A"),
)
DEFAULTS = {name: key for name, _c, _l, key in COMMANDS}


def _store():
    from . import customizedlg
    return App.ParamGet(customizedlg.PARAM)


def key(name):
    ""
    try:
        g = _store()
        if ("Key." + name) in g.GetStrings():
            return g.GetString("Key." + name, "")
    except Exception as _fw_err:
        _fw_log("filterkeys.py:key", _fw_err)
    return DEFAULTS.get(name, "")


def _seq(key_code, mods):
    if key_code == Qt.Key_Backtab:
        key_code, mods = Qt.Key_Tab, mods | Qt.ShiftModifier
    if key_code == Qt.Key_Enter:
        key_code = Qt.Key_Return        # the keypad's Enter is Enter too
    try:
        return QtGui.QKeySequence(QtCore.QKeyCombination(Qt.KeyboardModifier(mods), Qt.Key(key_code))).toString()
    except Exception:
        try:
            return QtGui.QKeySequence(int(mods) | int(key_code)).toString()
        except Exception:
            return ""


def _parts(text):
    seq = QtGui.QKeySequence(text)
    if seq.isEmpty():
        return 0, Qt.NoModifier
    c = seq[0]
    try:
        return c.key(), c.keyboardModifiers()
    except AttributeError:
        k = int(c)
        return k & ~int(Qt.KeyboardModifierMask), Qt.KeyboardModifiers(k & int(Qt.KeyboardModifierMask))


def logical(key_code, mods):
    """(key, modifiers) as the key filters know them: a key the user gave one of these commands becomes the
    command's default key; a default key given away to nothing or to another key becomes 0 (no key)."""
    changed = [(n, key(n)) for n in DEFAULTS if key(n) != DEFAULTS[n]]
    if not changed:
        return key_code, mods
    pressed = _seq(key_code, mods)
    if not pressed:
        return key_code, mods
    for name, now in changed:
        if now and QtGui.QKeySequence(now).toString() == pressed:
            return _parts(DEFAULTS[name])
    for name, now in changed:
        if QtGui.QKeySequence(DEFAULTS[name]).toString() == pressed:
            return 0, mods
    return key_code, mods


def shown(name):
    ""
    text = QtGui.QKeySequence(key(name)).toString(QtGui.QKeySequence.NativeText)
    return "Enter" if text == "Return" else text


# --------------------------------------------------------------------------- the commands
def _shell():
    try:
        from . import shell
        s = shell.shell()
    except Exception:
        return None
    return s if s is not None and s.enabled else None


class _Base:
    NAME = ""

    def GetResources(self):
        label = next(l for n, _c, l, _k in COMMANDS if n == self.NAME)
        return {"MenuText": label, "ToolTip": label, "CmdType": "ForEdit"}

    def IsActive(self):
        return _shell() is not None


class _HideHovered(_Base):
    NAME = "SWStyle_HideHovered"

    def Activated(self):
        from . import swkeys
        swkeys.install().hide_under()


class _ShowHovered(_Base):
    NAME = "SWStyle_ShowHovered"

    def Activated(self):
        from . import swkeys
        h = swkeys.install()
        target = h._over_view()
        if target is not None:
            h.show_under(target)


class _ShowAllHidden(_Base):
    NAME = "SWStyle_ShowAllHidden"

    def Activated(self):
        from . import swkeys
        swkeys.install().show_all()


class _MoveToPointer(_Base):
    NAME = "SWStyle_MoveToPointer"

    def Activated(self):
        s = _shell()
        if s is None:
            return
        corner = getattr(getattr(s, "overlay", None), "confirm", None)
        if corner is not None:
            corner.to_pointer()
        crumbs = getattr(s, "breadcrumbs", None)
        if crumbs is not None:
            crumbs.to_pointer()


class _CommandOptionToggle(_Base):
    NAME = "SWStyle_CommandOptionToggle"

    def Activated(self):
        try:
            from .fwsketch import toolbase
            tool = toolbase._active
        except Exception:
            tool = None
        if tool is not None:
            tool.on_key(Qt.Key_A)


def register():
    have = Gui.listCommands()
    for cls in (_HideHovered, _ShowHovered, _ShowAllHidden, _MoveToPointer, _CommandOptionToggle):
        if cls.NAME not in have:
            Gui.addCommand(cls.NAME, cls())
