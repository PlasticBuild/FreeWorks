# SPDX-License-Identifier: LGPL-2.1-or-later
""





import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

PROP = "fwActiveWindow"
_state = {"area": None}


def _area():
    try:
        return Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    except Exception:
        return None


def _colour():
    try:
        return QtWidgets.QApplication.palette().color(QtWidgets.QApplication.palette().Highlight).name()
    except Exception:
        return "#3d8ee6"


def outlined(win):
    """True when win is drawn with the active outline."""
    return bool(win is not None and win.property(PROP))


def refresh(*_args):
    area = _state["area"] or _area()
    if area is None:
        return
    wins = [w for w in area.subWindowList() if w.isVisible()]
    tiled = area.viewMode() == QtWidgets.QMdiArea.SubWindowView and len(wins) > 1 \
        and not any(w.isMaximized() for w in wins)
    active = area.activeSubWindow()
    for w in area.subWindowList():
        on = bool(tiled and w is active)
        if bool(w.property(PROP)) == on:
            continue
        w.setProperty(PROP, on)
        w.setStyleSheet("QMdiSubWindow { border: 2px solid %s; }" % _colour() if on else "")


def install():
    area = _area()
    if area is None or _state["area"] is area:
        return
    _state["area"] = area
    area.subWindowActivated.connect(lambda _w: QtCore.QTimer.singleShot(0, refresh))
    t = QtCore.QTimer(area)
    t.setObjectName("FW_ActiveWindowOutline")
    t.timeout.connect(refresh)       # tiling, maximizing and closing change the layout without an activation
    t.start(500)
    refresh()
    try:
        from . import ticks as _ticks
        _ticks.slow_when_idle(t)
    except Exception as _fw_err:
        __import__("FreeCAD").Console.PrintLog("FreeCAD ticks: %s\n" % _fw_err)
