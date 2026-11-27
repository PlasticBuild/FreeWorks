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
from PySide import QtCore, QtWidgets

TEXT = "Simplified Interface"
TIP = "The Simplified Interface is on: Basic Modeling Tools is the first CommandManager tab. Click to turn it off."
_state = {"widget": None, "timer": None}


def basic_title():
    try:
        from . import addintabs
        return addintabs.BASIC_TITLE
    except Exception:
        return "Basic Modeling Tools"


def on():
    """True while the Basic Modeling Tools tab is shown."""
    try:
        from . import catalog
        return any(t[0] == basic_title() for t in catalog.TABS)
    except Exception:
        return False


def set_on(value):
    from . import cmtabs
    title = basic_title()
    off = [t for t in cmtabs.hidden() if t != title]
    if not value:
        off.append(title)
    cmtabs.set_hidden(off)
    cmtabs.apply()
    refresh()


class Indicator(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__(TEXT, parent)
        self.setObjectName("SWSimplifiedInterface")
        self.setFocusPolicy(QtCore.Qt.ClickFocus)      # statusfocus-1127
        try:
            from .chrome import ui_font
            self.setFont(ui_font())
        except Exception as _fw_err:
            _fw_log("simplifiedui.py:65", _fw_err)
        self.setToolTip(TIP)
        # Ati's frame: 267 px from the start of "Simplified Interface" to the start of the units, text on the left
        self.setMinimumWidth(255)
        self.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            menu = QtWidgets.QMenu(self)
            act = menu.addAction("Turn Off Simplified Interface")
            act.setObjectName("SWSimplifiedOff")
            act.triggered.connect(lambda: set_on(False))
            menu.popup(self.mapToGlobal(QtCore.QPoint(0, 0)) - QtCore.QPoint(0, menu.sizeHint().height()))
            self.menu = menu
        super().mouseReleaseEvent(event)




ORDER = ("FW_AssemblyStatus", "SWStatusInfo", "SWSimplifiedInterface", "SWUnits", "SWStatusTags", "SWRebuildIndicator", "SWQuickTipsButton")


def order():
    ""

    sb = Gui.getMainWindow().statusBar()
    found = [(n, sb.findChild(QtWidgets.QWidget, n)) for n in ORDER]
    found = [(n, w) for n, w in found if w is not None and w.parent() is sb]
    shown = [w for _n, w in found if not w.isHidden()]
    xs = [w.x() for w in shown]
    if xs == sorted(xs) and len(set(xs)) == len(xs):
        return False
    # the leftmost of ORDER that is there (FW_AssemblyStatus only exists in an assembly)
    first = min((w.x() for _n, w in found), default=0)
    right = sorted((w for w in sb.findChildren(QtWidgets.QWidget)
                    if w.parent() is sb and w.x() >= first and not w.isHidden() and w not in [x for _n, x in found]),
                   key=lambda w: w.x())
    keep = [(w, not w.isHidden()) for _n, w in found] + [(w, True) for w in right]
    for w, _v in keep:
        sb.removeWidget(w)
    for w, v in keep:
        sb.addPermanentWidget(w)
        w.setVisible(v)
    return True


def _place(widget):
    sb = Gui.getMainWindow().statusBar()
    sb.addPermanentWidget(widget)
    order()


def refresh():
    w = _state["widget"]
    if w is None:
        return
    w.setVisible(on())
    _state["ticks"] = _state.get("ticks", 0) + 1
    if _state["ticks"] <= 30:              # the Tags button and Quick Tips come later: keep the order for 30 s
        order()


def install():
    if _state["widget"] is not None:
        return
    w = Indicator()
    _state["widget"] = w
    _place(w)
    refresh()
    t = QtCore.QTimer(w)
    t.setObjectName("FW_SimplifiedWatch")
    t.timeout.connect(refresh)            # the tab can come back through right-click > Tabs
    t.start(1000)
    _state["timer"] = t


def widget():
    return _state["widget"]
