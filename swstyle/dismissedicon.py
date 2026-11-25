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

OBJECT_NAME = "SWDismissedMessagesIcon"
KEY = "ShowDismissedMessagesIcon"
PAGE = "Dismissed Messages"


def _fw():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks")


def enabled():
    return _fw().GetBool(KEY, True)


def dismissed():
    """The texts of the messages answered with "Don't show again"."""
    try:
        from . import optionspages
        return [r[0] for r in optionspages.DISMISSABLE if optionspages._dismissed_now(r)]
    except Exception:
        return []


def _icon():
    icon = QtGui.QIcon()
    for size in (16, 32):
        pm = QtGui.QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(size / 16.0, size / 16.0)
        # a message balloon with a small cross: a message that is not shown any more
        p.setPen(QtGui.QPen(QtGui.QColor("#3a78c8"), 1.2))
        p.setBrush(QtGui.QColor("#e8f0fa"))
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(1.5, 2, 12, 8.5), 2, 2)
        path.moveTo(4, 10.5)
        path.lineTo(3.5, 14)
        path.lineTo(7.5, 10.5)
        p.drawPath(path.simplified())
        p.setPen(QtGui.QPen(QtGui.QColor("#c03030"), 1.6))
        p.drawLine(QtCore.QPointF(5.5, 4.5), QtCore.QPointF(9.5, 8))
        p.drawLine(QtCore.QPointF(9.5, 4.5), QtCore.QPointF(5.5, 8))
        p.end()
        icon.addPixmap(pm)
    return icon


def open_page():
    """Opens System Options at Dismissed Messages."""
    try:
        from . import options
        QtCore.QTimer.singleShot(0, lambda: options.show(0, PAGE))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Dismissed Messages not opened: %s\n" % error)


class DismissedIcon(QtWidgets.QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName(OBJECT_NAME)
        self.setAutoRaise(True)
        self.setIcon(_icon())
        self.setIconSize(QtCore.QSize(16, 16))
        self.clicked.connect(open_page)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1500)
        self.refresh()

    def refresh(self):
        rows = dismissed()
        n = len(rows)
        if n:
            self.setToolTip("<b>%d dismissed message%s</b><br>%s<br>Click to choose messages to show again."
                            % (n, "" if n == 1 else "s", "<br>".join(rows[:6])))
            self.setStatusTip("%d dismissed message%s" % (n, "" if n == 1 else "s"))
        self.setVisible(enabled() and n > 0)


_state = {}


def icon():
    w = _state.get("w")
    try:
        if w is not None:
            w.objectName()
            return w
    except RuntimeError as _fw_err:
        _fw_log("dismissedicon.py:117", _fw_err)
    return None


def install(tries=[0]):
    """Puts the icon on the status bar, left of 'Editing Part' (the look's status items)."""
    if icon() is not None:
        return icon()
    mw = Gui.getMainWindow()
    sb = mw.statusBar() if mw is not None else None
    if sb is None:
        return None
    sh = None
    try:
        from . import shell
        sh = shell.shell()
    except Exception as _fw_err:
        _fw_log("dismissedicon.py:134", _fw_err)
    info = getattr(sh, "status_info", None) if sh is not None else None
    if info is None and tries[0] < 40:
        tries[0] += 1
        QtCore.QTimer.singleShot(500, install)
        return None
    w = DismissedIcon()
    k = _perm_index(sb, info) if info is not None else None
    if k is None:
        sb.addPermanentWidget(w)
    else:
        sb.insertPermanentWidget(k, w)
    _state["w"] = w
    return w


def _perm_index(sb, widget):
    """The index insertPermanentWidget takes for a place just before widget: QStatusBar lays out its
    normal items, a stretch, then its permanent items in order."""
    try:
        lay = sb.layout()
        if not isinstance(lay, QtWidgets.QLayout):
            return None         # PySide6 can hand back a reused wrapper (a QSpacerItem): the icon goes at the end
        seen_stretch, perm = False, []
        for i in range(lay.count()):
            it = lay.itemAt(i)
            if it is None:
                continue
            if it.widget() is None and it.spacerItem() is not None:
                seen_stretch = True
                continue
            if seen_stretch and it.widget() is not None:
                perm.append(it.widget())
        return perm.index(widget) if widget in perm else None
    except (AttributeError, RuntimeError) as _fw_err:
        _fw_log("dismissedicon.py:perm_index", _fw_err)
        return None
