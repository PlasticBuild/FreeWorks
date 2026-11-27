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


def _subs(area):
    """mdiguard-1126: the area's sub windows that are really sub windows. PySide can hand back a stale wrapper
    (a QSpacerItem) for a window's address while a drawing opens; the poll then raised every 500 ms."""
    out = []
    try:
        for w in area.subWindowList():
            if isinstance(w, QtWidgets.QMdiSubWindow):
                out.append(w)
    except Exception:
        pass
    return out


def guard_sub_window_list():
    """mdiguard-1126b: one guard for every caller of QMdiArea.subWindowList() (about 40 in this package):
    anything in the list that is not a QMdiSubWindow (a stale wrapper PySide can hand back while a drawing
    opens) is dropped, so a caller never meets a QSpacerItem. Set once; the class method is replaced."""
    try:
        cls = QtWidgets.QMdiArea
        original = cls.subWindowList
        if getattr(original, "_fw_guard", False):
            return
        sub = QtWidgets.QMdiSubWindow

        def subWindowList(self, *args):
            found = original(self, *args)
            good = [w for w in found if isinstance(w, sub)]
            return good if len(good) != len(found) else found
        subWindowList._fw_guard = True
        subWindowList._fw_original = original
        cls.subWindowList = subWindowList
    except Exception:
        pass


def tiled(area=None):
    """tilewin-1127: two or more document windows shown side by side (Tile, Cascade, restored windows)."""
    area = area or _state["area"] or _area()
    if area is None:
        return False
    wins = [w for w in _subs(area) if w.isVisible() and not w.isMinimized()]
    return area.viewMode() == QtWidgets.QMdiArea.SubWindowView and len(wins) > 1 \
        and not any(w.isMaximized() for w in wins)


def _overlay_attach():
    """The Task Pane tabs move between the active view and the window area's right edge (chrome.py)."""
    try:
        from . import shell as sh
        overlay = getattr(sh.shell(), "overlay", None)
        if overlay is not None:
            overlay.attach()
    except Exception as _fw_err:
        __import__("FreeCAD").Console.PrintLog("FreeCAD activewin.py:overlay: %s\n" % _fw_err)


def refresh(*_args):
    area = _state["area"] or _area()
    if area is None:
        return
    subs = _subs(area)
    tiled_now = tiled(area)
    if tiled_now != _state.get("tiled", False):
        _state["tiled"] = tiled_now
        QtCore.QTimer.singleShot(0, _overlay_attach)
    active = area.activeSubWindow()
    for w in subs:
        on = bool(tiled_now and w is active)
        if bool(w.property(PROP)) == on:
            continue
        w.setProperty(PROP, on)
        w.setStyleSheet("QMdiSubWindow { border: 2px solid %s; }" % _colour() if on else "")


def install():
    guard_sub_window_list()
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
