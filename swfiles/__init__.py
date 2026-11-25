# SPDX-License-Identifier: LGPL-2.1-or-later
""















import FreeCAD as App

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SolidWorksFiles"
TITLE = "SolidWorks files"


def params():
    return App.ParamGet(PARAMS)


def msg(text):
    App.Console.PrintMessage("FreeCAD files: %s\n" % text)


def warn(text):
    App.Console.PrintWarning("FreeCAD files: %s\n" % text)


def error(text):
    App.Console.PrintError("FreeCAD files: %s\n" % text)


def tell(text, title=TITLE, icon="information"):
    """A message box in the GUI, the console otherwise."""
    (warn if icon == "warning" else msg)(text)
    if App.GuiUp:
        try:
            from PySide import QtGui
            box = QtGui.QMessageBox.warning if icon == "warning" else QtGui.QMessageBox.information
            box(None, title, text)
        except Exception:
            pass


def doc_name(text):
    """A valid, unused document name from a file name."""
    import re
    name = re.sub(r"[^A-Za-z0-9_]", "_", text) or "Part"
    if name[0].isdigit():
        name = "_" + name
    taken = set(App.listDocuments())
    base, n = name, 1
    while name in taken:
        name = "%s%03d" % (base, n)
        n += 1
    return name
