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
from PySide import QtCore, QtWidgets

Qt = QtCore.Qt
PARAM = "User parameter:BaseApp/Preferences/Mod/SolidWorksStyle"
_state = {"shell": None, "filter": None, "timer": None, "band": None, "geometry": None}


def wanted():
    return App.ParamGet(PARAM).GetBool("TabsOnGraphicsArea", True)


def _alive(w):
    try:
        from .widgets import alive
        return alive(w)
    except Exception:
        return w is not None


def _topbar():
    sh = _state["shell"]
    tb = getattr(sh, "topbar", None) if sh is not None and getattr(sh, "enabled", False) else None
    return tb if tb is not None and _alive(tb) else None


def on():
    """True while the tab row floats on the graphics area."""
    tb = _topbar()
    return bool(tb is not None and getattr(tb, "tabs_on_view", False) and _alive(tb.tabs) and tb.tabs.isVisible())


def top():
    """How far the tab row reaches down over the graphics area (logical px), 0 when it is not there."""
    if not on():
        return 0
    return _topbar().tabs.height()


def row_geometry():
    """The tab row's rectangle in main window coordinates, else None."""
    return _topbar().tabs.geometry() if on() else None


def covers(host, rect):
    """True when rect (host widget coordinates) runs under the floating tab row."""
    g = row_geometry()
    if g is None or host is None:
        return False
    try:
        mw = _state["shell"].window
        tl = host.mapTo(mw, rect.topLeft())
        return QtCore.QRect(tl, rect.size()).intersects(g)
    except Exception:
        return False


class _Filter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        tb = _topbar()
        if tb is not None and obj is tb.tabs and t == QtCore.QEvent.Wheel:

            delta = event.angleDelta().y()
            tb._wheel = getattr(tb, "_wheel", 0) + delta
            notches = int(tb._wheel / 120)
            if notches:
                tb._wheel -= notches * 120
                tb.step_tab(-notches)
            event.accept()
            return True
        if t in (QtCore.QEvent.Resize, QtCore.QEvent.Move, QtCore.QEvent.Show, QtCore.QEvent.Hide,
                 QtCore.QEvent.LayoutRequest):
            QtCore.QTimer.singleShot(0, place)
        return False


def _work_top(sh):
    """The main window y where the docks and the central area begin (under the CommandManager row)."""
    mw = sh.window
    top = 0
    try:
        mb = mw.menuBar()
        if mb is not None and mb.isVisible():
            top = mb.geometry().bottom() + 1
    except Exception as _fw_err:
        _fw_log("tabstrip.py:115", _fw_err)
    # extapps/71: only the window's own toolbars count, so only its direct children are looked at (the whole
    # widget tree took 1.4 ms, on every place: 400 ms apart and on each resize or layout)
    for tb in mw.findChildren(QtWidgets.QToolBar, "", Qt.FindDirectChildrenOnly):
        if tb.parentWidget() is mw and tb.isVisible() and mw.toolBarArea(tb) == Qt.TopToolBarArea:
            top = max(top, tb.geometry().bottom() + 1)
    central = mw.centralWidget()
    if central is not None and central.isVisible():
        top = min(top, central.geometry().top()) if top else central.geometry().top()
    return top


def _left_band(sh, height):
    """A blank band as tall as the tab row at the left pane's top, so the pane starts under the tabs."""
    pane = getattr(sh, "left_pane", None)
    lay = pane.layout() if pane is not None and _alive(pane) else None
    if lay is None:
        return
    m = lay.contentsMargins()
    if m.top() != height:
        lay.setContentsMargins(m.left(), height, m.right(), m.bottom())


_banded = []      # [widget] MDI views given a top band


def _is_3d(w):
    try:
        return "View3D" in w.metaObject().className() or "View3D" in type(w).__name__
    except Exception:
        return False


def _sheet_band(sh, g):
    """Views other than the 3D view (a drawing sheet, a spreadsheet, a web page) get a band at their
    top as tall as the tab row where the row covers them, so nothing on the sheet sits under the tabs:
    a click there reaches the sheet, not a tab, and Zoom to Fit fits the sheet below the tabs. The 3D
    view keeps the model under the strip, the heads-up toolbar's way."""
    mw = sh.window
    want = {}
    if g is not None:
        central = mw.centralWidget()
        # extapps/71: FreeCAD's views live in the central MDI area: the whole widget tree only when it is not one
        areas = [central] if isinstance(central, QtWidgets.QMdiArea) else mw.findChildren(QtWidgets.QMdiArea)
        for area in areas:
            if not _alive(area) or not area.isVisible():
                continue
            for sub in area.subWindowList():
                w = sub.widget()
                if w is None or not _alive(w) or not w.isVisible() or _is_3d(w):
                    continue
                top = w.mapTo(mw, QtCore.QPoint(0, 0)).y()
                band = max(0, g.bottom() + 1 - top)
                left = w.mapTo(mw, QtCore.QPoint(0, 0)).x()
                if band and left < g.right():
                    want[id(w)] = (w, band)
    for w in list(_banded):
        if not _alive(w) or id(w) not in want:
            try:
                if _alive(w):
                    m = w.contentsMargins()
                    w.setContentsMargins(m.left(), 0, m.right(), m.bottom())
            except Exception as _fw_err:
                _fw_log("tabstrip.py:194", _fw_err)
            _banded.remove(w)
    for w, band in want.values():
        m = w.contentsMargins()
        if m.top() != band:
            w.setContentsMargins(m.left(), band, m.right(), m.bottom())
        if w not in _banded:
            _banded.append(w)


def place():
    tb = _topbar()
    if tb is None or not getattr(tb, "tabs_on_view", False):
        return
    sh = _state["shell"]
    mw = sh.window
    row = tb.tabs
    if row.parentWidget() is not mw:
        row.setParent(mw)
        row.show()
    from .widgets import scaled
    h = scaled(21.5 + 0.5, tb.k)
    x = 0
    y = _work_top(sh)
    reserve = scaled(60, tb.k)                       # the task pane tabs on the right stay clear
    room = mw.width() - x - reserve
    try:            # hudbelow-1122: the row stops short of the document's own buttons on the same strip
        db = mw.findChild(QtWidgets.QWidget, "SWDocumentButtons", Qt.FindDirectChildrenOnly)
        at = db.target() if db is not None and _alive(db) else None
        if at is not None:
            room = min(room, at.x() - x - scaled(8, tb.k))
    except Exception as _fw_err:
        _fw_log("tabstrip.py:docbuttons", _fw_err)
    w = max(scaled(40, tb.k), min(row.natural_width(), room))
    try:
        w = row.fit_width(w)             # some tabs behind >>: the row ends at the >>
    except Exception as _fw_err:
        _fw_log("tabstrip.py:223", _fw_err)
    g = QtCore.QRect(x, y, w, h)
    if row.geometry() != g:
        row.setGeometry(g)
    if row.isVisible() and (not tb.isVisible() or tb.property("swCommandManagerOff")):
        row.hide()                                     # the CommandManager is off: no tabs either
    row.raise_()
    _left_band(sh, h if row.isVisible() else 0)
    _sheet_band(sh, g if row.isVisible() else None)
    try:                # extapps89: Quick Access Tools > Show in the CommandManager: the buttons sit beside the tabs
        tb._place_qat(tb.width())
    except Exception as _fw_err:
        _fw_log("tabstrip.py:qat", _fw_err)
    if g != _state["geometry"]:
        _state["geometry"] = g
        _replace_overlays(sh)


def _replace_overlays(sh):
    """The view's overlays take their places again (they read top())."""
    ov = getattr(sh, "overlay", None)
    try:
        if ov is not None:
            ov._place()
    except Exception as _fw_err:
        _fw_log("tabstrip.py:244", _fw_err)


def apply(shell, value=None):
    """Puts the tab row on the graphics area (value True) or back under the CommandManager."""
    value = wanted() if value is None else bool(value)
    _state["shell"] = shell
    tb = getattr(shell, "topbar", None)
    if tb is None or not _alive(tb):
        return False
    row = tb.tabs
    if value == bool(getattr(tb, "tabs_on_view", False)):
        place()
        return value
    tb.tabs_on_view = value
    if value:
        row.setParent(shell.window)
        row.show()
        if _state["filter"] is None:
            _state["filter"] = _Filter()
        for w in (shell.window, row, getattr(shell, "top_tb", None), getattr(shell, "left_dock", None)):
            if w is not None:
                w.installEventFilter(_state["filter"])
    else:
        if _state["filter"] is not None:
            for w in (shell.window, row, getattr(shell, "top_tb", None), getattr(shell, "left_dock", None)):
                if w is not None and _alive(w):
                    w.removeEventFilter(_state["filter"])
        row.setParent(tb)
        row.show()
        _left_band(shell, 0)
        _sheet_band(shell, None)
    tb._apply_height()
    tb.updateGeometry()
    try:
        shell.top_tb.updateGeometry()
    except Exception as _fw_err:
        _fw_log("tabstrip.py:281", _fw_err)
    _state["geometry"] = None
    QtCore.QTimer.singleShot(0, place)
    QtCore.QTimer.singleShot(200, place)
    if value and _state["timer"] is None:
        t = QtCore.QTimer(shell.window)
        t.setObjectName("FW_TabStripWatch")
        t.timeout.connect(place)                 # titles change (add-ins, a drawing) without a resize
        t.start(400)
        _state["timer"] = t
        try:
            from . import ticks as _ticks
            _ticks.slow_when_idle(t)
        except Exception as _fw_err:
            __import__("FreeCAD").Console.PrintLog("FreeCAD ticks: %s\n" % _fw_err)
    return value


def set_wanted(value):
    App.ParamGet(PARAM).SetBool("TabsOnGraphicsArea", bool(value))
    sh = _state["shell"]
    if sh is not None:
        apply(sh, value)


def release(shell):
    """Back under the CommandManager for good (the look is being turned off)."""
    tb = getattr(shell, "topbar", None)
    if _state["timer"] is not None:
        _state["timer"].stop()
        _state["timer"].deleteLater()
        _state["timer"] = None
    if _state["filter"] is not None:
        for w in (shell.window, getattr(tb, "tabs", None), getattr(shell, "top_tb", None), getattr(shell, "left_dock", None)):
            if w is not None and _alive(w):
                w.removeEventFilter(_state["filter"])
    if tb is not None and _alive(tb) and getattr(tb, "tabs_on_view", False):
        tb.tabs_on_view = False
        if _alive(tb.tabs):
            tb.tabs.setParent(tb)
            tb.tabs.show()
        tb._apply_height()
    _left_band(shell, 0)
    _sheet_band(shell, None)
    _state["geometry"] = None


def install(shell):
    try:
        apply(shell)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: tab row on the graphics area: %s\n" % error)
