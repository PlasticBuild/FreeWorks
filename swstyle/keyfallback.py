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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
SHORTCUT = "User parameter:BaseApp/Preferences/Shortcut"
TEXT = (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit, QtWidgets.QAbstractSpinBox,
        QtWidgets.QComboBox, QtWidgets.QAbstractItemView)
_FILTER = []
ANYWHERE = ("FreeWorks_ContextHelp",)


def table():
    ""
    try:
        from . import keys
        pairs = [(c, k) for c, k in keys.KEYS]
    except Exception:
        return {}
    out = {}
    group = App.ParamGet(SHORTCUT)
    for cmd, key in pairs:
        try:
            key = group.GetString(cmd, key)
        except Exception as _fw_err:
            _fw_log("keyfallback.py:47", _fw_err)
        if key:
            out[QtGui.QKeySequence(key).toString()] = cmd
    return out


def key_text(event):
    mods = event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
    key = event.key()
    if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, 0, Qt.Key_unknown):
        return ""
    try:
        return QtGui.QKeySequence(QtCore.QKeyCombination(mods, Qt.Key(key))).toString()
    except Exception:
        return QtGui.QKeySequence(int(mods) | int(key)).toString()


def _view_widget(obj):
    ""
    if isinstance(obj, TEXT):
        return False
    w = obj
    for _ in range(4):
        if w is None:
            return False
        name = w.metaObject().className()
        if isinstance(w, QtWidgets.QGraphicsView) or "View3DInventor" in name or "GLWidget" in name \
                or "QuarterWidget" in name:
            return True
        w = w.parentWidget() if isinstance(w, QtWidgets.QWidget) else None
    return False


def dead(cmd):
    """The command exists but FreeCAD has made no action for it (so its shortcut is nowhere)."""
    try:
        c = Gui.Command.get(cmd)
    except Exception:
        return False
    if c is None:
        return False
    try:
        return not c.getAction()
    except Exception:
        return False


class _Filter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper can arrive here
        try:
            if event.type() != QtCore.QEvent.KeyPress or event.isAutoRepeat():
                return False
            focus = QtWidgets.QApplication.focusWidget()
            text = key_text(event)
            if not text:
                return False
            cmd = table().get(text)
            in_view = obj is focus and _view_widget(obj)
            elsewhere = (isinstance(obj, QtWidgets.QWidget) and not isinstance(obj, TEXT) and
                         (obj is focus or (focus is None and obj.isWindow())))
            # F1 works in every window, text boxes and trees included, but never over a modal box
            anywhere = cmd in ANYWHERE and QtWidgets.QApplication.activeModalWidget() is None
            if not (in_view or elsewhere or anywhere):
                return False
            if cmd is None or not (dead(cmd) or cmd in ANYWHERE):    # F1: also when FreeCAD's own action never fires
                return False
            if not in_view and cmd not in ANYWHERE:
                return False
            if not Gui.Command.get(cmd).isActive():
                return False
            QtCore.QTimer.singleShot(0, lambda c=cmd: Gui.runCommand(c, 0))
            return True
        except Exception as error:
            App.Console.PrintLog("FreeCAD: key fallback: %s\n" % error)
            return False


def install():
    if _FILTER:
        return _FILTER[0]
    f = _Filter(QtWidgets.QApplication.instance())
    try:
        from . import events
        events.register("keyfallback", (QtCore.QEvent.KeyPress,), f.eventFilter)
    except ImportError:          # only without the shared dispatcher: never both
        QtWidgets.QApplication.instance().installEventFilter(f)
    _FILTER.append(f)
    return f
