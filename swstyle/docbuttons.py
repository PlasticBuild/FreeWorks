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

from . import style
from .widgets import FlatButton, alive, scaled, ui_scale

Qt = QtCore.Qt
T = style.T
PARAM = "User parameter:BaseApp/Preferences/Mod/SolidWorksStyle"
CELL = (26, 22)
RIGHT = 6               # from the view's right edge to the close button's right side
_state = {"bar": None}


def wanted():
    return App.ParamGet(PARAM).GetBool("DocumentWindowButtons", True)


def _raise_once(widget):
    """perf-1126 / perf2-1126 / perf3-1126: raise only when something other than its partner covers part of the widget.
    DocButtons and PaneHandle are siblings that can overlap; raising one covered the other, which raised itself in turn,
    on every tick. One fixed order now: the PaneHandle is above the DocButtons, so the handle covering the buttons is
    fine for the buttons, and a real raise puts the buttons back first and the handle on top of them."""
    try:
        bar, handle = _state.get("bar"), _state.get("handle")
        partner = handle if widget is bar else bar if widget is handle else None
        full = QtGui.QRegion(widget.rect())
        seen = widget.visibleRegion()
        if seen == full:
            return
        above = partner is not None and widget is bar and alive(partner) and partner.isVisible()
        if above:                   # the handle sits over the buttons by design
            over = partner.geometry().intersected(widget.geometry()).translated(-widget.pos())
            if seen.united(QtGui.QRegion(over)) == full:
                return
    except Exception as _fw_err:
        _fw_log("docbuttons.raise", _fw_err)
        above = False
    widget.raise_()
    if above:
        partner.raise_()


def _pen(widget, width=1.0):
    pen = QtGui.QPen(T.arrow if widget.underMouse() else T.arrow_dim)
    pen.setWidthF(width)
    return pen


def _panel(painter, rect, widget, left):
    """A window with a bar at one side and a small solid arrow pointing out of it."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
    painter.setPen(_pen(widget))
    c = rect.center()
    box = QtCore.QRectF(round(c.x()) - 5.5, round(c.y()) - 6.5, 11, 13)
    painter.drawRect(box)
    bar_x = box.left() + 3 if left else box.right() - 3
    painter.drawLine(QtCore.QPointF(bar_x, box.top()), QtCore.QPointF(bar_x, box.bottom()))
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(T.arrow if widget.underMouse() else T.arrow_dim)
    tip = box.left() + 4.2 if left else box.right() - 4.2
    back = tip + 3 if left else tip - 3
    path = QtGui.QPainterPath()
    path.moveTo(tip, c.y())
    path.lineTo(back, c.y() - 3)
    path.lineTo(back, c.y() + 3)
    path.closeSubpath()
    painter.drawPath(path)
    painter.restore()


def glyph_left_panel(painter, rect, widget):
    _panel(painter, rect, widget, True)




# "Tiling Windows in Displays": "Click ... Tile Left, Tile Right, Tile Top, or Tile Bottom in the document window's
# title bar"; "You can tile a document window so it occupies half of one display, or all available space on one of
# two displays"; displays one above the other give Tile Top and Tile Bottom, otherwise Tile Left and Tile Right).

# a click puts that document in the top (bottom) part of the graphics area, the other document goes in the rest,
# and a click in either makes it the active document.

def stacked():
    ""

    try:
        mw = Gui.getMainWindow()
        scr = mw.screen() if mw is not None and hasattr(mw, "screen") else QtGui.QGuiApplication.primaryScreen()
        here = scr.geometry()
        for other in QtGui.QGuiApplication.screens():
            g = other.geometry()
            if g == here:
                continue
            apart = g.bottom() < here.top() + 8 or g.top() > here.bottom() - 8
            overlap = min(g.right(), here.right()) - max(g.left(), here.left())
            if apart and overlap > 0:
                return True
    except Exception as _fw_err:
        _fw_log("docbuttons.stacked", _fw_err)
    return False


def _tile_glyph(painter, rect, widget, first):
    ""

    vertical = stacked()
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
    ink = T.arrow if widget.underMouse() else T.arrow_dim
    painter.setPen(_pen(widget))
    c = rect.center()
    box = QtCore.QRectF(round(c.x()) - 6.5, round(c.y()) - 6.5, 13, 13)
    painter.drawRect(box)
    painter.fillRect(QtCore.QRectF(box.left(), box.top(), box.width() + 1, 2.5), ink)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(ink)
    path = QtGui.QPainterPath()
    cx, cy = box.center().x() + 0.5, box.center().y() + 1.5
    if vertical:
        tip = cy - 3 if first else cy + 3
        back = tip + 3 if first else tip - 3
        path.moveTo(cx, tip)
        path.lineTo(cx - 3.5, back)
        path.lineTo(cx + 3.5, back)
    else:
        tip = cx - 3.5 if first else cx + 3.5
        back = tip + 3 if first else tip - 3
        path.moveTo(tip, cy)
        path.lineTo(back, cy - 3.5)
        path.lineTo(back, cy + 3.5)
    path.closeSubpath()
    painter.drawPath(path)
    painter.restore()


def glyph_tile_first(painter, rect, widget):
    _tile_glyph(painter, rect, widget, True)


def glyph_tile_second(painter, rect, widget):
    _tile_glyph(painter, rect, widget, False)


def tile_names():
    return ("Tile Top", "Tile Bottom") if stacked() else ("Tile Left", "Tile Right")


def _cells(area, vertical):
    """The two parts of the work area: the part on each display when the window spans two displays that way,
    else its two halves (viewport coordinates)."""
    from . import windowmenu
    room = windowmenu._room(area)
    vp = area.viewport()
    try:
        tl = vp.mapToGlobal(room.topLeft())
        groom = QtCore.QRect(tl, room.size())
        parts = []
        for scr in QtGui.QGuiApplication.screens():
            g = scr.geometry().intersected(groom)
            if g.width() > 120 and g.height() > 90:
                parts.append(g)
        if len(parts) == 2:
            parts.sort(key=lambda g: g.y() if vertical else g.x())
            a, b = parts
            if (vertical and a.bottom() < b.top() + 2) or (not vertical and a.right() < b.left() + 2):
                return [QtCore.QRect(vp.mapFromGlobal(g.topLeft()), g.size()) for g in (a, b)]
    except Exception as _fw_err:
        _fw_log("docbuttons.cells", _fw_err)
    if vertical:
        h = room.height() // 2
        return [QtCore.QRect(room.x(), room.y(), room.width(), h),
                QtCore.QRect(room.x(), room.y() + h, room.width(), room.height() - h)]
    w = room.width() // 2
    return [QtCore.QRect(room.x(), room.y(), w, room.height()),
            QtCore.QRect(room.x() + w, room.y(), room.width() - w, room.height())]


def tile_document(first, sub=None):
    """Tile Left / Top (first) or Tile Right / Bottom: the document window fills that part of the work area; a
    maximized document behind it (or one mostly under it) goes to the other part, so two documents end up side by
    side; a click in either makes it the active document."""
    from . import windowmenu
    area = _mdi()
    if area is None or not alive(area):
        return False
    if sub is None:
        sub = area.activeSubWindow() or area.currentSubWindow()
    if sub is None or not alive(sub):
        return False
    vertical = stacked()
    mine, other = _cells(area, vertical)
    if not first:
        mine, other = other, mine
    others = [w for w in windowmenu._shown(area) if w is not sub]
    was_max = set(w for w in others if w.isMaximized()) if area.viewMode() == QtWidgets.QMdiArea.SubWindowView \
        else set(others)            # tabbed: every other document filled the area
    left_out = windowmenu._drawing_model_windows(area, others + [sub])
    windowmenu._as_windows(area)
    sub.showNormal()
    windowmenu._fits(sub)
    sub.setGeometry(mine)
    for w in others:
        if w in left_out:
            continue
        g = w.geometry().intersected(mine)
        mostly_under = g.width() * g.height() * 2 > max(1, w.width() * w.height())
        if w in was_max or w.isMaximized() or mostly_under:
            w.showNormal()
            windowmenu._fits(w)
            w.setGeometry(other)
    windowmenu._behind_sheets(left_out)
    area.setActiveSubWindow(sub)
    windowmenu._overlay_follow()
    return True


def tile_first():
    return tile_document(True)


def tile_second():
    return tile_document(False)


class TitleTiles(QtWidgets.QWidget):
    ""

    def __init__(self, sub):
        super().__init__(sub)
        self.setObjectName("SWTitleTiles")
        self.sub = sub
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.k = ui_scale()
        self.first = FlatButton(None, "", (22, 18), 12, self, glyph=glyph_tile_first)
        self.first.setObjectName("SWTitleTile_first")
        self.second = FlatButton(None, "", (22, 18), 12, self, glyph=glyph_tile_second)
        self.second.setObjectName("SWTitleTile_second")
        self.first.clicked.connect(lambda _=False: QtCore.QTimer.singleShot(0, lambda: tile_document(True, self.sub)))
        self.second.clicked.connect(lambda _=False: QtCore.QTimer.singleShot(0, lambda: tile_document(False, self.sub)))
        self.second.move(self.first.width(), 0)
        self.resize(self.first.width() * 2, self.first.height())

    def place(self):
        sub = self.sub
        S = QtWidgets.QStyle
        opt = QtWidgets.QStyleOptionTitleBar()
        opt.initFrom(sub)
        h = sub.style().pixelMetric(S.PM_TitleBarHeight, opt, sub)
        opt.rect = QtCore.QRect(0, 0, sub.width(), h)
        opt.subControls = S.SC_All
        opt.titleBarFlags = sub.windowFlags()
        opt.titleBarState = int(_iv(sub.windowState()))
        left = sub.width()
        for sc in (S.SC_TitleBarMinButton, S.SC_TitleBarMaxButton, S.SC_TitleBarCloseButton):
            r = sub.style().subControlRect(S.CC_TitleBar, opt, sc, sub)
            if r.isValid() and not r.isEmpty():
                left = min(left, r.left())
        a, b = tile_names()
        if self.first.toolTip() != a:
            self.first.setToolTip(a)
            self.second.setToolTip(b)
        self.move(max(0, left - self.width() - 2), max(0, (h - self.height()) // 2))
        if not self.isVisible():
            self.show()
        self.raise_()


def _title_tiles(area):
    """doctile-1127: every restored document window carries the two Tile buttons in its title bar."""
    sub_view = area.viewMode() == QtWidgets.QMdiArea.SubWindowView
    for sub in area.subWindowList():
        t = sub.findChild(QtWidgets.QWidget, "SWTitleTiles", Qt.FindDirectChildrenOnly)
        show = sub_view and sub.isVisible() and not sub.isMaximized() and not sub.isMinimized()
        if not show:
            if t is not None and t.isVisible():
                t.hide()
            continue
        if t is None:
            t = TitleTiles(sub)
        t.place()


def glyph_right_panel(painter, rect, widget):
    _panel(painter, rect, widget, False)


def glyph_doc_minimize(painter, rect, widget):
    painter.save()
    c = rect.center()
    painter.fillRect(QtCore.QRectF(round(c.x()) - 5, round(c.y()) + 4, 11, 1.5),
                     T.arrow if widget.underMouse() else T.arrow_dim)
    painter.restore()


def glyph_doc_restore(painter, rect, widget):
    """Two overlapping windows."""
    painter.save()
    painter.setPen(_pen(widget))
    c = rect.center()
    x, y = round(c.x()) - 5.5, round(c.y()) - 5.5
    painter.drawRect(QtCore.QRectF(x, y + 4, 8, 7))
    painter.drawLine(QtCore.QPointF(x + 3, y + 4), QtCore.QPointF(x + 3, y))
    painter.drawLine(QtCore.QPointF(x + 3, y), QtCore.QPointF(x + 11, y))
    painter.drawLine(QtCore.QPointF(x + 11, y), QtCore.QPointF(x + 11, y + 7))
    painter.drawLine(QtCore.QPointF(x + 11, y + 7), QtCore.QPointF(x + 8, y + 7))
    painter.restore()


def glyph_doc_close(painter, rect, widget):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(_pen(widget, 1.2))
    c = rect.center()
    painter.drawLine(QtCore.QPointF(c.x() - 5, c.y() - 5), QtCore.QPointF(c.x() + 5, c.y() + 5))
    painter.drawLine(QtCore.QPointF(c.x() + 5, c.y() - 5), QtCore.QPointF(c.x() - 5, c.y() + 5))
    painter.restore()


def _shell():
    try:
        from . import shell
        s = shell.shell()
        return s if s is not None and getattr(s, "enabled", False) else None
    except Exception:
        return None


def _mdi():
    s = _shell()
    mw = getattr(s, "window", None) if s is not None else None
    return mw.findChild(QtWidgets.QMdiArea) if mw is not None and alive(mw) else None


def _active_sub():
    area = _mdi()
    if area is None or not alive(area):
        return None, None
    return area, (area.activeSubWindow() or area.currentSubWindow())


def _run(*names):
    have = set(Gui.listCommands())
    for name in names:
        if name in have:
            Gui.runCommand(name, 0)
            return name
    return None


def toggle_left_panel():
    return _run("SWStyle_FeatureManagerArea")


def toggle_right_panel():
    if _run("SWStyle_TaskPaneKey"):
        return "SWStyle_TaskPaneKey"
    from . import uiextras
    uiextras.set_task_pane(not uiextras.task_pane_shown())
    return "uiextras"


def minimize_document():
    area, sub = _active_sub()
    if sub is None:
        return False
    if area.viewMode() != QtWidgets.QMdiArea.SubWindowView:
        area.setViewMode(QtWidgets.QMdiArea.SubWindowView)
    sub.showMinimized()
    return True


def restore_document():
    """The document window as a window of its own in the work area, two thirds of its size, at the top left
    (Windows' restore of a maximized document window)."""
    area, sub = _active_sub()
    if sub is None:
        return False
    if area.viewMode() != QtWidgets.QMdiArea.SubWindowView:
        area.setViewMode(QtWidgets.QMdiArea.SubWindowView)
    sub.showNormal()
    room = area.viewport().rect()
    g = sub.geometry()
    # its last size of its own, unless it never had one (Qt's small default) or it is the whole area
    top = _under_tabs(area)
    if not (room.width() // 2 <= g.width() < room.width() - 2 and room.height() // 2 <= g.height() < room.height() - 2):
        sub.setGeometry(0, top, max(320, room.width() * 2 // 3), max(240, min(room.height() * 2 // 3, room.height() - top)))
    elif g.y() < top:
        sub.move(g.x(), top)        # restorewin-1121: its title bar clear of the CommandManager tabs on the strip
    area.setActiveSubWindow(sub)
    return True


def _under_tabs(area):
    """How far the CommandManager tab row (tabstrip, on the work area's top strip) reaches down into the work
    area: a restored window starts under it, or the tabs sit over its title bar."""
    try:
        from . import tabstrip
        g = tabstrip.row_geometry()
        if g is None:
            return 0
        mw = area.window()
        top = area.viewport().mapTo(mw, QtCore.QPoint(0, 0)).y()
        return max(0, g.y() + g.height() - top)
    except Exception as error:
        _fw_log("docbuttons.under_tabs", error)
        return 0


def close_document():
    return _run("SWStyle_CloseDocument", "Std_CloseActiveWindow")


class DocButtons(QtWidgets.QWidget):
    ITEMS = (

        ("tile_first", "Tile Left", glyph_tile_first, tile_first),
        ("tile_second", "Tile Right", glyph_tile_second, tile_second),
        ("minimize", "Minimize", glyph_doc_minimize, minimize_document),
        ("restore", "Restore Down", glyph_doc_restore, restore_document),
        ("close", "Close", glyph_doc_close, close_document),
    )

    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.setObjectName("SWDocumentButtons")
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.k = ui_scale()
        self.buttons = {}
        x = 0
        for key, tip, glyph, action in self.ITEMS:
            b = FlatButton(None, tip, CELL, 14, self, glyph=glyph)
            b.setObjectName("SWDocButton_" + key)
            b.clicked.connect(lambda _=False, a=action: QtCore.QTimer.singleShot(0, a))
            b.move(x, 0)
            x += b.width()
            self.buttons[key] = b
        self.resize(x, scaled(CELL[1], self.k))
        self.hide()
        self._timer = QtCore.QTimer(self)
        self._timer.setObjectName("FW_DocButtons")
        self._timer.timeout.connect(self.refresh)
        self._timer.start(400)
        area = _mdi()
        if area is not None:
            area.subWindowActivated.connect(lambda *_: QtCore.QTimer.singleShot(0, self.refresh))
        QtCore.QTimer.singleShot(0, self.refresh)

    def _host(self):
        ov = getattr(self.shell, "overlay", None)
        for name in ("host", "sheet"):
            w = getattr(ov, name, None) if ov is not None else None
            if w is not None and alive(w) and w.isVisible():
                return w
        return None

    def target(self):
        """Where the row goes (main window coordinates), or None when it should not show."""
        if not wanted() or not getattr(self.shell, "enabled", False):
            return None
        area, sub = _active_sub()
        if sub is None or not alive(sub) or not sub.isVisible() or sub.isMinimized():
            return None
        if area.viewMode() != QtWidgets.QMdiArea.TabbedView and not sub.isMaximized():
            return None     # a restored window has its own title bar buttons
        host = self._host()
        mw = self.shell.window
        if host is None or not host.window() is mw:
            return None
        tl = host.mapTo(mw, QtCore.QPoint(0, 0))
        right = tl.x() + host.width() - host.contentsMargins().right() - scaled(RIGHT, self.k)
        top = tl.y()
        try:
            from . import tabstrip
            g = tabstrip.row_geometry()
        except Exception:
            g = None
        if g is not None and g.bottom() >= top:
            top = g.y() + max(0, (g.height() - self.height()) // 2)       # on the tab strip's row
        else:
            top += scaled(3, self.k)
        return QtCore.QPoint(right - self.width(), top)

    def refresh(self):
        try:
            if not alive(self):
                return
            _theme_titles()             # darktitle-1121
            area = _mdi()
            if area is not None and alive(area):
                _title_tiles(area)      # doctile-1127
            a, b = tile_names()
            if self.buttons["tile_first"].toolTip() != a:
                self.buttons["tile_first"].setToolTip(a)
                self.buttons["tile_second"].setToolTip(b)
            at = self.target()
            if at is None:
                if self.isVisible():
                    self.hide()
                return
            if self.pos() != at:
                self.move(at)
            if not self.isVisible():
                self.show()
            _raise_once(self)
        except Exception as error:
            _fw_log("docbuttons.refresh", error)


class _TitleStyle(QtWidgets.QProxyStyle):
    """darktitle-1121: a restored document window's title bar in the look's colours. Fusion fills it with the
    palette's Highlight (the theme's selection blue, #35578a in Dark) and writes white text over it; the document
    window title follows the theme instead. The bar is painted here: the theme's tab colour when active and the
    pane colour when not, the window's icon and name at the left, and minimize / restore / maximize / close drawn
    in the text colour, close turning red under the mouse."""

    def drawComplexControl(self, control, option, painter, widget=None):
        if control != QtWidgets.QStyle.CC_TitleBar or not isinstance(option, QtWidgets.QStyleOptionTitleBar):
            return super().drawComplexControl(control, option, painter, widget)
        try:
            self._title(option, painter, widget)
        except Exception as error:
            _fw_log("docbuttons.title", error)
            super().drawComplexControl(control, option, painter, widget)

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QtWidgets.QStyle.PE_FrameWindow:
            painter.save()
            painter.setPen(QtGui.QPen(T.line_mid, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QtCore.QRectF(option.rect).adjusted(0.5, 0.5, -0.5, -0.5))
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)

    def _title(self, opt, p, widget):
        S = QtWidgets.QStyle
        state = _iv(opt.titleBarState)
        flags = _iv(opt.titleBarFlags)
        subs = _iv(opt.subControls)
        hot_sc = _iv(opt.activeSubControls)
        ostate = _iv(opt.state)
        active = bool(state & _iv(S.State_Active)) or bool(ostate & _iv(S.State_Active))
        p.save()
        p.fillRect(opt.rect, T.tab if active else T.pane)
        p.setPen(QtGui.QPen(T.line_mid, 1))
        p.drawLine(opt.rect.bottomLeft(), opt.rect.bottomRight())
        ink = T.text if active else T.text_dim
        left = opt.rect.left() + 4
        if subs & _iv(S.SC_TitleBarSysMenu) and not opt.icon.isNull():
            r = self.subControlRect(S.CC_TitleBar, opt, S.SC_TitleBarSysMenu, widget)
            opt.icon.paint(p, r.adjusted(2, 2, -2, -2))
            left = r.right() + 4
        buttons = []
        for sc, kind in ((S.SC_TitleBarMinButton, "min"), (S.SC_TitleBarNormalButton, "normal"),
                         (S.SC_TitleBarMaxButton, "max"), (S.SC_TitleBarCloseButton, "close")):
            if not (subs & _iv(sc)):
                continue
            if kind == "min" and (not flags & _iv(Qt.WindowMinimizeButtonHint) or state & _iv(Qt.WindowMinimized)):
                continue
            if kind == "max" and (not flags & _iv(Qt.WindowMaximizeButtonHint) or state & _iv(Qt.WindowMaximized)):
                continue
            if kind == "normal" and not state & (_iv(Qt.WindowMinimized) | _iv(Qt.WindowMaximized)):
                continue
            r = self.subControlRect(S.CC_TitleBar, opt, sc, widget)
            if r.isValid() and not r.isEmpty():
                buttons.append((sc, kind, r))
        right = min([r.left() for _, _, r in buttons] + [opt.rect.right()]) - 4
        text_rect = QtCore.QRect(left, opt.rect.top(), max(0, right - left), opt.rect.height())
        if widget is not None:
            p.setFont(widget.font())
        p.setPen(ink)
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(opt.text, Qt.ElideRight, text_rect.width()))
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        for sc, kind, r in buttons:
            hot = bool(hot_sc & _iv(sc)) and bool(ostate & (_iv(S.State_MouseOver) | _iv(S.State_Sunken)))
            if hot:
                p.fillRect(r, QtGui.QColor("#e81123") if kind == "close" else T.hover)
            p.setPen(QtGui.QPen(QtGui.QColor("#ffffff") if hot and kind == "close" else ink, 1.1))
            p.setBrush(Qt.NoBrush)
            c = QtCore.QRectF(r).center()
            P = QtCore.QPointF
            if kind == "min":
                p.drawLine(P(c.x() - 4.5, c.y() + 3.5), P(c.x() + 4.5, c.y() + 3.5))
            elif kind == "max":
                p.drawRect(QtCore.QRectF(c.x() - 4.5, c.y() - 4.5, 9, 9))
            elif kind == "normal":
                p.drawRect(QtCore.QRectF(c.x() - 4.5, c.y() - 2.5, 7, 7))
                p.drawPolyline(QtGui.QPolygonF([P(c.x() - 2.5, c.y() - 2.5), P(c.x() - 2.5, c.y() - 4.5),
                                                P(c.x() + 4.5, c.y() - 4.5), P(c.x() + 4.5, c.y() + 2.5),
                                                P(c.x() + 2.5, c.y() + 2.5)]))
            else:
                p.drawLine(P(c.x() - 4.5, c.y() - 4.5), P(c.x() + 4.5, c.y() + 4.5))
                p.drawLine(P(c.x() + 4.5, c.y() - 4.5), P(c.x() - 4.5, c.y() + 4.5))
        p.restore()


def _iv(value):
    """darktitle-1121: an enum or flag value as an int (PySide 6 enums do not mix with ints)."""
    try:
        return int(value)
    except TypeError:
        return int(getattr(value, "value", 0))


def _theme_titles():
    """darktitle-1121: every document window in the work area draws its title bar with _TitleStyle, and a restored
    window's title bar is kept below the CommandManager tabs."""
    area = _mdi()
    if area is None or not alive(area):
        return
    st = _state.get("title_style")
    if st is None:
        st = _TitleStyle("Fusion")
        _state["title_style"] = st
    top = None
    for sub in area.subWindowList():
        if not sub.property("fw_title_style"):
            sub.setProperty("fw_title_style", True)
            sub.setStyle(st)
            sub.update()
        if not sub.isVisible() or sub.isMaximized() or sub.isMinimized() or area.viewMode() != QtWidgets.QMdiArea.SubWindowView:
            continue
        if top is None:
            top = _under_tabs(area)
        g = sub.geometry()
        if g.y() < top:
            # Cascade, Tile and a window dragged up: its title bar stays clear of the CommandManager tabs on the
            # strip (they sit over the work area's top). The bottom edge stays put so tiled windows do not overlap.
            h = g.bottom() - top + 1 if g.bottom() - top + 1 >= 120 else g.height()
            sub.setGeometry(g.x(), top, g.width(), h)


class PaneHandle(QtWidgets.QWidget):
    ""


    SIZE = (9, 38)

    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.setObjectName("SWPaneHandle")
        self.k = ui_scale()
        self.setFixedSize(scaled(self.SIZE[0], self.k), scaled(self.SIZE[1], self.k))
        self.setToolTip("Show/Hide FeatureManager Tree Area (F9)")
        self.setCursor(Qt.ArrowCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.hide()
        self._timer = QtCore.QTimer(self)
        self._timer.setObjectName("FW_PaneHandle")
        self._timer.timeout.connect(self.refresh)
        self._timer.start(400)
        QtCore.QTimer.singleShot(0, self.refresh)

    def target(self):
        if not wanted() or not getattr(self.shell, "enabled", False):
            return None
        mw = self.shell.window
        dock = getattr(self.shell, "left_dock", None)
        if dock is None or not alive(dock) or dock.isFloating():
            return None
        host = DocButtons._host(self)
        if host is None or host.window() is not mw:
            return None
        htl = host.mapTo(mw, QtCore.QPoint(0, 0))
        if dock.isVisible():
            tl = dock.mapTo(mw, QtCore.QPoint(0, 0))
            x, top, h = tl.x() + dock.width(), tl.y(), dock.height()
            if abs(x - htl.x()) > scaled(12, self.k):
                return None             # the pane is not beside the graphics area (docked elsewhere)
        else:
            x, top, h = htl.x(), htl.y(), host.height()
        return QtCore.QPoint(x, top + (h - self.height()) // 2)

    def refresh(self):
        try:
            if not alive(self):
                return
            at = self.target()
            if at is None:
                if self.isVisible():
                    self.hide()
                return
            if self.pos() != at:
                self.move(at)
            if not self.isVisible():
                self.show()
            _raise_once(self)
        except Exception as error:
            _fw_log("docbuttons.panehandle", error)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()
                                                                     if hasattr(event, "position") else event.pos()):
            QtCore.QTimer.singleShot(0, toggle_left_panel)
            QtCore.QTimer.singleShot(50, self.refresh)
        event.accept()

    def mousePressEvent(self, event):
        event.accept()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        r = QtCore.QRectF(self.rect())
        p.fillRect(r, T.hover if self.underMouse() else T.pane)
        p.setPen(QtGui.QPen(T.line_mid if T.text.lightness() > 128 else T.line, 1.0))
        x0, x1, y0, y1 = 0.0, r.width() - 0.5, 0.5, r.height() - 0.5
        p.drawLine(QtCore.QPointF(x0, y0), QtCore.QPointF(x1, y0))
        p.drawLine(QtCore.QPointF(x1, y0), QtCore.QPointF(x1, y1))
        p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x0, y1))
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(T.arrow if self.underMouse() else T.arrow_dim)
        d = 2.4 * self.k
        p.drawEllipse(QtCore.QPointF(r.width() / 2 - 0.5, r.height() / 2), d, d)
        p.end()


def install(shell):
    try:
        bar = _state["bar"]
        if bar is not None and alive(bar):
            return bar
        bar = DocButtons(shell)
        _state["bar"] = bar
    except Exception as error:
        _fw_log("docbuttons.install", error)
        return None
    try:
        h = _state.get("handle")
        if h is None or not alive(h):
            _state["handle"] = PaneHandle(shell)      # panehandle-1121
    except Exception as error:
        _fw_log("docbuttons.install-handle", error)
    return bar


def handle():
    h = _state.get("handle")
    return h if h is not None and alive(h) else None


def bar():
    b = _state["bar"]
    return b if b is not None and alive(b) else None
