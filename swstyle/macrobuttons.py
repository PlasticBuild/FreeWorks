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

import json
import os
import traceback

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import catalog

Qt = QtCore.Qt
PARAM = "User parameter:BaseApp/Preferences/Mod/SolidWorksStyle/Customize"
LIST = "MacroButtons"
NEW_KEY = "MacroNewButton"
KEY_PREFIX = "MacroBtn_"
CMD_PREFIX = "SWStyle_MacroButton_"
DEFAULT_ICON = "TOOLS_EQNS"
ICONS = (("Macro", "TOOLS_EQNS"), ("Run", "STANDARD_REBUILD"), ("Options", "STANDARD_OPTIONS"),
         ("Document", "STANDARD_FILE_PROP"), ("Open", "STANDARD_OPEN"), ("Print", "STANDARD_PRINT"))
FIELDS = ("id", "path", "label", "tip", "prompt", "icon")
_LOADED = {}            # id -> record (a dict)


def _p():
    return App.ParamGet(PARAM)


def _clean(text):
    return (text or "").replace("\n", " ").strip()


def _read():
    try:
        rows = json.loads(_p().GetString(LIST, "") or "[]")
    except Exception as _fw_err:
        _fw_log("macrobuttons.py:68", _fw_err)
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("id") and r.get("path")]


def _write(rows):
    if rows:
        _p().SetString(LIST, json.dumps(rows))
    else:
        _p().RemString(LIST)


def key_of(rid):
    return KEY_PREFIX + rid


def is_button(key):
    return isinstance(key, str) and key.startswith(KEY_PREFIX)


def records():
    """[record] of every macro button, in the order they were made."""
    return list(_LOADED.values())


def keys():
    return [key_of(rid) for rid in _LOADED]


# ---------------------------------------------------------------------------- running a macro
def run(path, prompt=""):
    """Runs a macro file as FreeCAD's own Macro > Execute does: in a fresh __main__ namespace."""
    if not os.path.isfile(path):
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Macro", "The macro file is not there:\n%s" % path)
        return False
    if prompt:
        try:
            Gui.getMainWindow().statusBar().showMessage(prompt, 4000)
        except Exception:
            pass
    try:
        with open(path, encoding="utf-8") as handle:
            code = compile(handle.read(), path, "exec")
        exec(code, {"__name__": "__main__", "__file__": path})
        return True
    except Exception:
        App.Console.PrintError("FreeCAD macro button %s:\n%s\n" % (path, traceback.format_exc()))
        return False


class _ButtonCommand:
    def __init__(self, rid):
        self.rid = rid

    def _rec(self):
        return _LOADED.get(self.rid)

    def GetResources(self):
        rec = self._rec() or {}
        return {"MenuText": rec.get("label", "Macro"), "ToolTip": rec.get("tip", "") or rec.get("label", "")}

    def IsActive(self):
        return self._rec() is not None

    def Activated(self):
        rec = self._rec()
        if rec is not None:
            run(rec["path"], rec.get("prompt", ""))


class _NewButtonCommand:
    def GetResources(self):
        return {"MenuText": "New Macro Button...",
                "ToolTip": "Makes a toolbar button that runs a macro file you pick."}

    def IsActive(self):
        return True

    def Activated(self):
        key = new_button()
        if key:
            try:
                from . import customizedlg
                box = customizedlg._open[0] if customizedlg.is_open() else None
                if box is not None:
                    box.add_to_toolbar(box.cmd_toolbar.currentText(), key)
                    box.refresh_macro_category()
            except Exception as error:
                App.Console.PrintLog("FreeCAD: macro button not added to the toolbar: %s\n" % error)


# ---------------------------------------------------------------------------- catalog entries
def _tip(rec):
    return rec.get("tip") or ("Runs the macro %s." % os.path.basename(rec["path"]))


def _publish(rec):
    """Puts the button in the catalog (so toolbars, search and Customize see it) and registers its command."""
    rid = rec["id"]
    _LOADED[rid] = rec
    name = CMD_PREFIX + rid
    try:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _ButtonCommand(rid))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: macro button %s not added: %s\n" % (rec.get("label"), error))
    key = key_of(rid)
    cmd = catalog.BY_KEY.get(key)
    if cmd is None:
        cmd = catalog.c(key, rec["label"], (name,), rec.get("icon") or DEFAULT_ICON, _tip(rec))
        catalog.BY_KEY[key] = cmd
    else:
        cmd.label = cmd.caption = rec["label"]
        cmd.icon = rec.get("icon") or DEFAULT_ICON
        cmd.tip = _tip(rec)
    return cmd


def load():
    """Reads the saved macro buttons and publishes them. Safe to call more than once."""
    try:
        if "SWStyle_MacroNewButton" not in Gui.listCommands():
            Gui.addCommand("SWStyle_MacroNewButton", _NewButtonCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: New Macro Button command not added: %s\n" % error)
    _LOADED.clear()
    for rec in _read():
        _publish(rec)


def new_id():
    used = {int(r["id"]) for r in _read() if str(r["id"]).isdigit()}
    return str(max(used) + 1 if used else 1)


def add(path, label, tip="", prompt="", icon=DEFAULT_ICON):
    """Makes a macro button; returns its catalog key."""
    rec = {"id": new_id(), "path": path, "label": _clean(label) or os.path.splitext(os.path.basename(path))[0],
           "tip": _clean(tip), "prompt": _clean(prompt), "icon": icon or DEFAULT_ICON}
    _write(_read() + [rec])
    _publish(rec)
    return key_of(rec["id"])


def update(rid, **fields):
    rows = _read()
    for row in rows:
        if row["id"] == rid:
            for name, value in fields.items():
                if name in FIELDS and name != "id":
                    row[name] = _clean(value) if name != "path" else value
            _write(rows)
            _publish(row)
            return True
    return False


def remove(rid):
    """Deletes a macro button (the command stays registered but inactive until FreeCAD restarts)."""
    _write([r for r in _read() if r["id"] != rid])
    _LOADED.pop(rid, None)
    key = key_of(rid)
    cmd = catalog.BY_KEY.pop(key, None)
    if cmd is not None:
        try:
            catalog._ALL.remove(cmd)
        except ValueError:
            pass


# ---------------------------------------------------------------------------- the box
class MacroButtonDialog(QtWidgets.QDialog):
    ""

    def __init__(self, record=None, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWMacroButtonDialog")
        self.setWindowTitle("Customize Macro Button")
        rec = record or {}
        form = QtWidgets.QFormLayout(self)
        self.path = QtWidgets.QLineEdit(rec.get("path", ""))
        self.path.setObjectName("SWMacroButtonFile")
        browse = QtWidgets.QPushButton("Browse...")
        browse.setObjectName("SWMacroButtonBrowse")
        browse.clicked.connect(self._browse)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        form.addRow("Macro file:", row)
        self.label = QtWidgets.QLineEdit(rec.get("label", ""))
        self.label.setObjectName("SWMacroButtonName")
        form.addRow("Custom button name:", self.label)
        self.tip = QtWidgets.QLineEdit(rec.get("tip", ""))
        self.tip.setObjectName("SWMacroButtonTip")
        form.addRow("Tooltip:", self.tip)
        self.prompt = QtWidgets.QLineEdit(rec.get("prompt", ""))
        self.prompt.setObjectName("SWMacroButtonPrompt")
        form.addRow("Prompt (status bar):", self.prompt)
        self.icon = QtWidgets.QComboBox()
        self.icon.setObjectName("SWMacroButtonIcon")
        for text, family in ICONS:
            self.icon.addItem(text, family)
        at = self.icon.findData(rec.get("icon", DEFAULT_ICON))
        self.icon.setCurrentIndex(max(at, 0))
        form.addRow("Icon:", self.icon)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self):
        start = self.path.text() or App.ParamGet("User parameter:BaseApp/Preferences/Macro").GetString(
            "MacroPath", "") or App.getUserMacroDir(True)
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Macro file", start, "Macros (*.FCMacro *.py)")
        if path:
            self.path.setText(path)
            if not self.label.text():
                self.label.setText(os.path.splitext(os.path.basename(path))[0])

    def _accept(self):
        if not os.path.isfile(self.path.text().strip()):
            QtWidgets.QMessageBox.warning(self, "Macro Button", "Pick a macro file that exists.")
            return
        self.accept()

    def values(self):
        return dict(path=self.path.text().strip(), label=self.label.text(), tip=self.tip.text(),
                    prompt=self.prompt.text(), icon=self.icon.currentData())


def new_button(parent=None):
    """The New Macro Button box; returns the new catalog key, or None when cancelled."""
    box = MacroButtonDialog(None, parent)
    if box.exec() != QtWidgets.QDialog.Accepted:
        return None
    v = box.values()
    return add(v["path"], v["label"], v["tip"], v["prompt"], v["icon"])


def edit_button(key, parent=None):
    rid = key[len(KEY_PREFIX):] if is_button(key) else ""
    rec = _LOADED.get(rid)
    if rec is None:
        return False
    box = MacroButtonDialog(rec, parent)
    if box.exec() != QtWidgets.QDialog.Accepted:
        return False
    return update(rid, **box.values())
