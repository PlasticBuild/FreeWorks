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
        ("left", "Show/Hide FeatureManager Tree Area (F9)", glyph_left_panel, toggle_left_panel),
        ("right", "Show/Hide Task Pane (Ctrl+F1)", glyph_right_panel, toggle_right_panel),
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
            at = self.target()
            if at is None:
                if self.isVisible():
                    self.hide()
                return
            if self.pos() != at:
                self.move(at)
            if not self.isVisible():
                self.show()
            self.raise_()
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
            self.raise_()
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
