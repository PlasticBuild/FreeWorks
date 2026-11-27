# SPDX-License-Identifier: LGPL-2.1-or-later
""









_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
PREFIX = "Spreadsheet_"
SHEET_VIEW = "SpreadsheetGui::SheetView"
SHEET_TABLE = "SpreadsheetGui::SheetTableView"      # FreeCAD 1.1 shows it through a ZoomableView (a graphics proxy)
TEXT = (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit, QtWidgets.QAbstractSpinBox)
_done = []


def in_sheet(widget):
    """The widget is (inside) a spreadsheet view, and not a text box."""
    if widget is None or isinstance(widget, TEXT):
        return False
    w, hops = widget, 0
    while w is not None and hops < 40:
        hops += 1
        try:
            if w.metaObject().className() in (SHEET_VIEW, SHEET_TABLE):
                return True
            up = w.parentWidget()
            if up is None:          # a widget shown through a graphics proxy: on to the view showing it
                proxy = w.graphicsProxyWidget()
                views = proxy.scene().views() if proxy is not None and proxy.scene() is not None else []
                up = views[0] if views else None
        except Exception:
            return False
        w = up
    return False


def _key(event):
    mods = event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
    k = event.key()
    if k in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, 0, Qt.Key_unknown):
        return ""
    try:
        return QtGui.QKeySequence(int(mods.value if hasattr(mods, "value") else mods) | int(k)).toString()
    except Exception:
        return ""


def sheet_command(text):
    """The active Spreadsheet command whose key is text, or None."""
    if not text:
        return None
    for name in Gui.listCommands():
        if not name.startswith(PREFIX):
            continue
        c = Gui.Command.get(name)
        try:
            if c is not None and QtGui.QKeySequence(c.getShortcut()).toString() == text and c.isActive():
                return name
        except Exception as _fw_err:
            _fw_log("sheetkeys.py:command", _fw_err)
    return None


def handler(obj, event):
    try:
        t = event.type()
        if t not in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
            return False
        if not isinstance(obj, QtWidgets.QWidget) or not in_sheet(obj):
            return False            # Qt sends the key to the widget it is for: the sheet's own, or nothing
        if not (event.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            return False            # plain letters type into the cell
        name = sheet_command(_key(event))
        if name is None:
            return False
        if t == QtCore.QEvent.ShortcutOverride:
            event.accept()          # the key comes to the sheet, not to the shortcut both commands hold
            return True
        QtCore.QTimer.singleShot(0, lambda n=name: Gui.runCommand(n, 0))
        return True
    except Exception as _fw_err:
        _fw_log("sheetkeys.py:handler", _fw_err)
        return False


def install():
    if _done:
        return
    try:
        from . import events
        events.register("sheetkeys", (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress), handler)
    except ImportError:
        class _F(QtCore.QObject):
            def eventFilter(self, obj, event):
                return handler(obj, event)
        f = _F(QtWidgets.QApplication.instance())
        QtWidgets.QApplication.instance().installEventFilter(f)
        _done.append(f)
    _done.append(True)
