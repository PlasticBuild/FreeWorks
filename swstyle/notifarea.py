""





import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import uiextras

KEY = "ShowNotificationArea"
LABEL = "Notification Area"
STATE = {"filter": None, "menu_bar": None}


def shown():
    return uiextras._param().GetBool(KEY, False)


def _status_bar():
    try:
        return Gui.getMainWindow().statusBar()
    except Exception:
        return None


def _button():
    sb = _status_bar()
    if sb is None:
        return None
    return sb.findChild(QtWidgets.QPushButton, "notificationArea")


class _Keep(QtCore.QObject):
    """Hides the button again whenever FreeCAD shows it while the notification area is off."""

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Show and not shown():
            QtCore.QTimer.singleShot(0, lambda b=obj: b.hide() if not shown() else None)
        return False


def apply():
    b = _button()
    if b is None:
        return False
    f = STATE["filter"]
    if f is None:
        f = STATE["filter"] = _Keep(b)
        b.installEventFilter(f)
    b.setVisible(shown())
    return True


def set_shown(on):
    uiextras._param().SetBool(KEY, bool(on))
    apply()


def item():
    """The View > User Interface row (a checkable action)."""
    from . import swmenus
    return swmenus.Item(LABEL, True, lambda: set_shown(not shown()), None, "", shown())


def _context_menu(pos):
    sb = _status_bar()
    if sb is None:
        return
    menu = QtWidgets.QMenu(sb)
    act = menu.addAction(LABEL)
    act.setCheckable(True)
    act.setChecked(shown())
    act.triggered.connect(lambda checked=False: set_shown(not shown()))
    menu.exec_(sb.mapToGlobal(pos))


def install():
    """Hides the button now and again once FreeCAD has built the status bar; adds the right click menu."""
    sb = _status_bar()
    if sb is not None and not sb.property("fw_notif_menu"):
        sb.setProperty("fw_notif_menu", True)
        sb.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        sb.customContextMenuRequested.connect(_context_menu)
    apply()
    for ms in (500, 2000, 6000):
        QtCore.QTimer.singleShot(ms, apply)
