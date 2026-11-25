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

from PySide import QtCore, QtGui, QtWidgets

from . import namedviews, style, viewselector
from .widgets import CommandButton, alive, ui_font

Qt = QtCore.Qt

STATUS = "Keep the dialog displayed by pinning"


def _status(text):
    """The status bar line while the box is open; on closing, cleared if it is still ours."""
    try:
        import FreeCADGui as Gui
        bar = Gui.getMainWindow().statusBar()
        if text:
            bar.showMessage(text)
        elif bar.currentMessage() == STATUS:
            bar.clearMessage()
    except Exception as _fw_err:
        _fw_log("orientation.py:status", _fw_err)


VIEWS = ("ViewFront", "ViewBack", "ViewLeft", "ViewRight", "ViewTop", "ViewBottom",
         "ViewIsometric", "NormalTo")

ISO_KEYS = ("ViewIsometric", "ViewTrimetric", "ViewDimetric")
UP_KEYS = ("YUpViewOrientation", "ZUpViewOrientation")
STANDARD_OF = {"ViewFront": "Front", "ViewBack": "Back", "ViewLeft": "Left", "ViewRight": "Right",
               "ViewTop": "Top", "ViewBottom": "Bottom", "ViewIsometric": "Isometric",
               "ViewTrimetric": "Trimetric", "ViewDimetric": "Dimetric"}
ARROW_W = 11               # a qat button's flyout arrow
CLOSE_RED = QtGui.QColor("#d24c4c")

LIST = (("*Normal To", "NormalTo"), ("*Front", "ViewFront"), ("*Back", "ViewBack"), ("*Left", "ViewLeft"),
        ("*Right", "ViewRight"), ("*Top", "ViewTop"), ("*Bottom", "ViewBottom"),
        ("*Isometric", "ViewIsometric"), ("*Trimetric", "ViewTrimetric"), ("*Dimetric", "ViewDimetric"))
VIEWPORTS = ("SingleView", "TwoViewHorizontal", "TwoViewVertical", "FourView")
BUTTON = 26
MARGIN = 6
TITLE_H = 20
LIST_ROWS = 5
GLOBE = 18          # the Saved Views row's globe (our own drawing)


def _globe_pixmap(size):
    """A small globe with a view frame on it: the Saved Views row's picture."""
    pix = QtGui.QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2.0)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    r = QtCore.QRectF(1, 1, size - 4, size - 4)
    grad = QtGui.QRadialGradient(r.left() + r.width() * 0.35, r.top() + r.height() * 0.3, r.width() * 0.75)
    grad.setColorAt(0, QtGui.QColor("#e8f3fc"))
    grad.setColorAt(1, QtGui.QColor("#2f6fae"))
    p.setBrush(QtGui.QBrush(grad))
    p.setPen(QtGui.QPen(QtGui.QColor("#1d4f8a"), 1))
    p.drawEllipse(r)
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 170), 0.8))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QtCore.QRectF(r.center().x() - r.width() * 0.22, r.top(), r.width() * 0.44, r.height()))
    p.drawLine(QtCore.QPointF(r.left(), r.center().y()), QtCore.QPointF(r.right(), r.center().y()))
    p.setPen(QtGui.QPen(QtGui.QColor("#4a4a4a"), 1))
    p.setBrush(QtGui.QColor("#f4f4f4"))
    p.drawRect(QtCore.QRectF(size * 0.5, size * 0.5, size * 0.45, size * 0.4))
    p.end()
    return pix
OFFSET = (10, 10)          # from the 3D view's top left
T = style.T                # the theme's colours, read when painting
ON_LINE = QtGui.QColor("#3c7fb1")
LIST_QSS = ("QListWidget#SWOrientationList { background: ${base}; border: 1px solid ${line_light}; color: ${text}; }"
            "QListWidget#SWOrientationList::item { padding: 1px 4px; }"
            "QListWidget#SWOrientationList::item:selected { background: ${menu_hover}; color: ${text}; }")


def glyph_cube(painter, rect):
    ""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    w, h = rect.width(), rect.height()
    x0, y0 = rect.x(), rect.y()
    cx, cy = x0 + w * 0.5, y0 + h * 0.5
    r = min(w, h) * 0.42
    top = QtCore.QPointF(cx, cy - r)
    left = QtCore.QPointF(cx - r * 0.87, cy - r * 0.5)
    right = QtCore.QPointF(cx + r * 0.87, cy - r * 0.5)
    middle = QtCore.QPointF(cx, cy)
    bottom = QtCore.QPointF(cx, cy + r)
    low_left = QtCore.QPointF(cx - r * 0.87, cy + r * 0.5)
    low_right = QtCore.QPointF(cx + r * 0.87, cy + r * 0.5)
    pen = QtGui.QPen(T.arrow, 1.0)
    painter.setPen(pen)
    painter.setBrush(T.base)
    painter.drawPolygon(QtGui.QPolygonF([top, right, middle, left]))
    painter.setBrush(T.tab_hover)
    painter.drawPolygon(QtGui.QPolygonF([left, middle, bottom, low_left]))
    painter.setBrush(T.tab)
    painter.drawPolygon(QtGui.QPolygonF([middle, right, low_right, bottom]))
    painter.restore()


def glyph_pin(painter, rect):
    """A push pin."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    w, h = rect.width(), rect.height()
    x0, y0 = rect.x(), rect.y()
    pen = QtGui.QPen(T.arrow, 1.2)
    painter.setPen(pen)
    painter.setBrush(T.qat)
    head = QtCore.QRectF(x0 + w * 0.3, y0 + h * 0.15, w * 0.4, h * 0.35)
    painter.drawRect(head)
    base = QtCore.QRectF(x0 + w * 0.18, y0 + h * 0.5, w * 0.64, h * 0.14)
    painter.drawRect(base)
    painter.drawLine(QtCore.QPointF(x0 + w * 0.5, y0 + h * 0.64), QtCore.QPointF(x0 + w * 0.5, y0 + h * 0.92))
    painter.restore()


def glyph_close(painter, rect):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(T.arrow, 1.2)
    painter.setPen(pen)
    m = rect.width() * 0.32
    painter.drawLine(QtCore.QPointF(rect.left() + m, rect.top() + m), QtCore.QPointF(rect.right() - m, rect.bottom() - m))
    painter.drawLine(QtCore.QPointF(rect.right() - m, rect.top() + m), QtCore.QPointF(rect.left() + m, rect.bottom() - m))
    painter.restore()


def _small_cube(painter, rect, scale=0.75):
    """The View Selector cube drawn smaller at the top left of rect, room for a mark beside it."""
    s = min(rect.width(), rect.height()) * scale
    glyph_cube(painter, QtCore.QRectF(rect.x(), rect.y(), s, s))


def glyph_new_view(painter, rect):
    """New View: a view with a plus."""
    _small_cube(painter, rect)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtGui.QPen(T.arrow, 1.6))
    cx, cy, r = rect.right() - rect.width() * 0.2, rect.bottom() - rect.height() * 0.2, rect.width() * 0.18
    painter.drawLine(QtCore.QPointF(cx - r, cy), QtCore.QPointF(cx + r, cy))
    painter.drawLine(QtCore.QPointF(cx, cy - r), QtCore.QPointF(cx, cy + r))
    painter.restore()


def glyph_update_views(painter, rect):
    """Update Standard Views: a view with an arrow into it."""
    _small_cube(painter, rect)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtGui.QPen(T.arrow, 1.4))
    a = QtCore.QPointF(rect.right() - rect.width() * 0.05, rect.bottom() - rect.height() * 0.05)
    b = QtCore.QPointF(rect.right() - rect.width() * 0.4, rect.bottom() - rect.height() * 0.4)
    painter.drawLine(a, b)
    painter.drawLine(b, b + QtCore.QPointF(rect.width() * 0.16, 0))
    painter.drawLine(b, b + QtCore.QPointF(0, rect.height() * 0.16))
    painter.restore()


def glyph_reset_views(painter, rect):
    """Reset Standard Views: a view with a turning-back arrow."""
    _small_cube(painter, rect)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtGui.QPen(T.arrow, 1.3))
    painter.setBrush(Qt.NoBrush)
    r = rect.width() * 0.2
    c = QtCore.QPointF(rect.right() - r - 1, rect.bottom() - r - 1)
    painter.drawArc(QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 90 * 16, 270 * 16)
    tip = QtCore.QPointF(c.x(), c.y() - r)
    painter.drawLine(tip, tip + QtCore.QPointF(r * 0.6, -r * 0.4))
    painter.drawLine(tip, tip + QtCore.QPointF(r * 0.6, r * 0.4))
    painter.restore()


def glyph_close_red(painter, rect):
    ""
    painter.save()
    painter.fillRect(rect.adjusted(-1, -1, 1, 1), CLOSE_RED)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1.4))
    m = rect.width() * 0.32
    painter.drawLine(QtCore.QPointF(rect.left() + m, rect.top() + m), QtCore.QPointF(rect.right() - m, rect.bottom() - m))
    painter.drawLine(QtCore.QPointF(rect.right() - m, rect.top() + m), QtCore.QPointF(rect.left() + m, rect.bottom() - m))
    painter.restore()


def current_view_key(tolerance=0.5):
    ""
    try:
        import FreeCADGui as Gui
        view = Gui.ActiveDocument.ActiveView
        now = view.getCameraOrientation()
    except Exception:
        return None
    for key, name in STANDARD_OF.items():
        try:
            other = namedviews.standard_rotation(name)
            if abs(now.multiply(other.inverted()).Angle) * 57.29578 <= tolerance:
                return key
        except Exception as _fw_err:
            _fw_log("orientation.py:current", _fw_err)
    return None


def _camera_now():
    try:
        import FreeCADGui as Gui
        return tuple(round(x, 5) for x in Gui.ActiveDocument.ActiveView.getCameraOrientation().Q)
    except Exception:
        return None


_LAST_ISO = ["ViewIsometric"]      # Isometric, Trimetric or Dimetric: last used, shown on the arrow's button


class OrientationPanel(QtWidgets.QWidget):
    ""




    picked = QtCore.Signal()

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.views = {}
        for key in VIEWS:
            if key == "ViewIsometric":
                b = CommandButton(shell, key, ISO_KEYS, "qat", self)
                b.resize(BUTTON + ARROW_W, BUTTON)
                self._watch_flyout(b)
            else:
                b = CommandButton(shell, key, None, "qat", self)
                b.resize(BUTTON, BUTTON)
            b.setObjectName("SWOrientation" + key)
            b.installEventFilter(self)
            self.views[key] = b
        self.viewports = []
        for key in VIEWPORTS:
            b = CommandButton(shell, key, None, "qat", self)
            b.resize(BUTTON, BUTTON)
            b.setObjectName("SWOrientation" + key)
            b.installEventFilter(self)
            self.viewports.append(b)
        self.link_views = CommandButton(shell, "LinkViews", None, "qat", self)
        self.link_views.resize(BUTTON, BUTTON)
        self.link_views.setObjectName("SWOrientationLinkViews")
        self._also = []             # more CommandButtons whose state refresh() reads (the box's first row)
        self.extra = None           # a widget between the cube and the viewports (the box's Saved Views)
        self.current = None
        self.lay_out()

    def _watch_flyout(self, button):
        """A pick on the button's own flyout counts as a pick (the view turns once the menu closes)."""
        hidden = button._flyout_hidden

        def after():
            hidden()
            before = getattr(button, "_fw_cam", None)

            def check():
                if _camera_now() != before:
                    self.picked.emit()
            QtCore.QTimer.singleShot(120, check)
        button._flyout_hidden = after

    def lay_out(self):
        cols = 6
        inner = cols * BUTTON + 8 + ARROW_W
        y = 0

        def at(key, col, row):
            b = self.views.get(key)
            if b is not None:
                b.move(col * BUTTON + (8 if col >= 4 else 0), y + row * BUTTON)
        at("ViewTop", 1, 0)
        at("ViewLeft", 0, 1)
        at("ViewFront", 1, 1)
        at("ViewRight", 2, 1)
        at("ViewBack", 3, 1)
        at("ViewBottom", 1, 2)
        at("ViewIsometric", 5, 0)
        at("NormalTo", 5, 2)
        y += 3 * BUTTON + 4
        if self.extra is not None and self.extra.isVisibleTo(self):
            self.extra.move(0, y)
            self.extra.resize(inner, self.extra.height())
            y += self.extra.height() + 2
        for i, b in enumerate(self.viewports):
            b.move(i * BUTTON, y)
        self.link_views.move(5 * BUTTON + 8, y)
        y += BUTTON
        self.setFixedSize(inner, y)

    def refresh(self):
        """The pressed look follows the view on screen; the buttons' enabled state is read again (a
        binding not yet resolved draws greyed although its command works)."""
        for b in list(self.views.values()) + self.viewports + [self.link_views] + list(self._also):
            try:
                b.binding.resolve()
                b.binding.update_state()
            except Exception as _fw_err:
                _fw_log("orientation.py:state", _fw_err)
        key = current_view_key()
        iso = self.views["ViewIsometric"]
        if key in ISO_KEYS:
            _LAST_ISO[0] = key           # the arrow's button shows the one on screen, as after a pick there
            key = "ViewIsometric"
        if iso.binding.cmd.key != _LAST_ISO[0]:
            try:
                self.shell.rebind(iso, _LAST_ISO[0])
            except Exception as _fw_err:
                _fw_log("orientation.py:rebind", _fw_err)
        if key != self.current:
            self.current = key
            self.update()

    def paintEvent(self, event):
        b = self.views.get(self.current) if self.current else None
        if b is None:
            return
        painter = QtGui.QPainter(self)
        r = b.geometry() if self.current != "ViewIsometric" else QtCore.QRect(b.pos(), QtCore.QSize(BUTTON, BUTTON))
        painter.fillRect(r, T.tab_hover)
        painter.setPen(T.line_mid)
        painter.drawRect(r.adjusted(0, 0, -1, -1))
        painter.end()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            obj._fw_cam = _camera_now()
        if event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton \
                and obj.rect().contains(event.position().toPoint()) \
                and (obj.arrow_rect().isNull() or not obj.arrow_rect().contains(event.position().toPoint())):
            QtCore.QTimer.singleShot(0, self.picked.emit)
        return False


class GlyphButton(QtWidgets.QAbstractButton):
    ""

    def __init__(self, glyph, tooltip, parent, checkable=False, size=BUTTON):
        super().__init__(parent)
        self._glyph = glyph
        self.setToolTip(tooltip)
        self.setCheckable(checkable)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        r = self.rect().adjusted(0, 0, -1, -1)
        if self.isChecked():
            painter.fillRect(self.rect(), T.menu_hover)
            painter.setPen(ON_LINE)
            painter.drawRect(r)
        elif self.underMouse() and self.isEnabled():
            painter.fillRect(self.rect(), T.hover)
        s = 16
        inner = QtCore.QRectF((self.width() - s) / 2.0, (self.height() - s) / 2.0, s, s)
        if not self.isEnabled():
            painter.setOpacity(0.4)         # greyed, as Reset Standard Views with nothing to reset
        self._glyph(painter, inner)
        painter.end()


class OrientationBox(QtWidgets.QWidget):
    """One box for the main window; the shell owns it and places it over the active 3D view."""

    selector_toggled = QtCore.Signal(bool)
    closed = QtCore.Signal(str)

    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.setObjectName("SWOrientationBox")
        self.setFont(ui_font())
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.pinned = False
        self.shows = 0                 # for checks

        # Views, the up axis (Y-Up / Z-Up on its arrow), the View Selector, and the pin at the right
        self.previous = CommandButton(shell, "PreviousView", None, "qat", self)
        self.previous.resize(BUTTON, BUTTON)
        self.previous.setObjectName("SWOrientationPreviousView")
        self.new_view = GlyphButton(glyph_new_view, "New View: saves the current view under a name", self)
        self.new_view.setObjectName("SWOrientationNewView")
        self.new_view.clicked.connect(self._new_view)
        self.update_views = GlyphButton(glyph_update_views, "Update Standard Views: then pick the standard view "
                                        "that the current view becomes", self)
        self.update_views.setObjectName("SWOrientationUpdateViews")
        self.update_views.clicked.connect(namedviews.arm_update)
        self.reset_views = GlyphButton(glyph_reset_views, "Reset Standard Views", self)
        self.reset_views.setObjectName("SWOrientationResetViews")
        self.reset_views.clicked.connect(self._reset_views)
        self.up_axis = CommandButton(shell, UP_KEYS[0], UP_KEYS, "qat", self)
        self.up_axis.resize(BUTTON + ARROW_W, BUTTON)
        self.up_axis.setObjectName("SWOrientationUpAxis")
        self.selector = GlyphButton(glyph_cube, "View Selector: a box around the model in the 3D view",
                                    self, checkable=True)
        self.selector.setObjectName("SWViewSelectorButton")
        self.selector.setChecked(viewselector.enabled())
        self.selector.toggled.connect(self._selector_toggled)
        self.pin = GlyphButton(glyph_pin, "Pin: keeps the box open", self, checkable=True, size=BUTTON - 6)
        self.pin.setObjectName("SWOrientationPin")
        self.pin.toggled.connect(self._pin_toggled)
        self.close_button = GlyphButton(glyph_close_red, "Close", self, size=TITLE_H - 4)
        self.close_button.setObjectName("SWOrientationClose")
        self.close_button.clicked.connect(lambda: self.shell.hide_orientation("close"))
        self.panel = OrientationPanel(shell, self)
        self.panel.setObjectName("SWOrientationPanel")
        self.panel.picked.connect(self.after_pick)
        self.panel._also = [self.previous, self.up_axis]
        self.views = list(self.panel.views.values())
        self.viewports = self.panel.viewports
        self.link_views = self.panel.link_views
        self.saved = QtWidgets.QWidget(self.panel)
        self.saved.setObjectName("SWOrientationSaved")
        self.saved_title = QtWidgets.QLabel("Saved Views", self.saved)
        self.saved_title.setObjectName("SWOrientationSavedTitle")
        self.saved_title.setFont(ui_font())
        self.saved_title.move(4, 2)
        self.saved_globe = QtWidgets.QLabel(self.saved)
        self.saved_globe.setPixmap(_globe_pixmap(GLOBE))
        self.saved_globe.resize(GLOBE, GLOBE)
        self.saved_rule = QtWidgets.QFrame(self.saved)
        self.saved_rule.setFrameShape(QtWidgets.QFrame.HLine)
        self.saved_rule.setFrameShadow(QtWidgets.QFrame.Plain)
        self.saved_rule.setStyleSheet("color: #c8c8c8;")
        self.panel.extra = self.saved
        self.list = QtWidgets.QListWidget(self.saved)
        self.list.setObjectName("SWOrientationList")
        self.list.setFont(ui_font())
        self.list.setStyleSheet(style.fill(LIST_QSS))
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        self.fill_list()
        self.list.itemDoubleClicked.connect(self._list_picked)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.place)
        self._timer.timeout.connect(self.panel.refresh)
        self._layout()
        self.hide()

    # -- layout ----------------------------------------------------------------------
    def _layout(self):
        ""





        # the list under it only while there are saved views
        saved = self.list.count() > 0
        self.saved.setVisible(True)
        self.list.setVisible(saved)
        row = self.list.fontMetrics().height() + 4
        top = max(self.saved_title.sizeHint().height(), GLOBE) + 6
        rows = min(LIST_ROWS, self.list.count()) * row + 4 if saved else 0
        width = self.panel.width()
        self.list.setGeometry(0, top, width, rows)
        self.saved_rule.setGeometry(GLOBE + 8, 1, max(0, width - GLOBE - 8), 1)
        self.saved_globe.move(2, 4)
        self.saved_title.move(GLOBE + 8, 4 + (GLOBE - self.saved_title.sizeHint().height()) // 2)
        self.saved_title.resize(width - GLOBE - 10, self.saved_title.sizeHint().height())
        self.saved.resize(width, top + rows)
        self.panel.lay_out()
        width = self.panel.width() + 2 * MARGIN
        y = TITLE_H + 3
        x = MARGIN
        for b in (self.previous, self.new_view, self.update_views, self.reset_views, self.up_axis, self.selector):
            b.move(x, y + (BUTTON - b.height()) // 2)
            x += b.width()
        width = max(width, x + 4 + self.pin.width() + MARGIN)
        self.pin.move(width - MARGIN - self.pin.width(), y + (BUTTON - self.pin.height()) // 2)
        y += BUTTON + 4
        self._row_line = y - 2
        self.panel.move(MARGIN, y)
        y += self.panel.height() + MARGIN
        self.close_button.move(width - MARGIN - self.close_button.width(), (TITLE_H - self.close_button.height()) // 2)
        self.setFixedSize(width, y)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), T.pane)
        painter.fillRect(QtCore.QRect(0, 0, self.width(), TITLE_H), T.pane)
        painter.setPen(T.line_mid)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.setPen(T.line_light)
        painter.drawLine(1, getattr(self, "_row_line", TITLE_H + BUTTON + 5), self.width() - 2,
                         getattr(self, "_row_line", TITLE_H + BUTTON + 5))
        painter.setPen(T.text)
        painter.setFont(self.font())
        painter.drawText(QtCore.QRect(MARGIN, 0, self.width() - 60, TITLE_H), Qt.AlignVCenter | Qt.AlignLeft, "Orientation")
        painter.end()

    # -- showing ---------------------------------------------------------------------
    def retheme(self):
        """A theme change: the list's style sheet follows, the rest repaints from the tokens."""
        self.list.setStyleSheet(style.fill(LIST_QSS))
        self.saved_title.setStyleSheet(style.fill("QLabel#SWOrientationSavedTitle { color: ${text}; }"))
        self.update()
        self.panel.update()

    def fill_list(self):
        ""
        self.list.clear()
        try:
            saved = [name for name, _camera in namedviews.views()]
        except Exception:
            saved = []
        for name in saved:
            item = QtWidgets.QListWidgetItem(name)
            item.setData(Qt.UserRole + 1, name)
            self.list.addItem(item)
        try:
            # no greyed button: Reset Standard Views shows (in its place) only once a standard view was changed
            turned = bool(namedviews.turned())
            policy = self.reset_views.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            self.reset_views.setSizePolicy(policy)
            self.reset_views.setEnabled(True)
            self.reset_views.setVisible(turned)
        except Exception as _fw_err:
            _fw_log("orientation.py:347", _fw_err)
        if self.isVisible():
            self._layout()

    def show_box(self):
        self.fill_list()
        self.selector.blockSignals(True)
        self.selector.setChecked(viewselector.enabled())
        self.selector.blockSignals(False)
        self._layout()
        self.panel.refresh()
        if not self.place():
            return False
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self._timer.start()
        self.shows += 1
        _status(STATUS)
        return True

    def hide_box(self, reason="close"):
        if not self.isVisible():
            return
        self._timer.stop()
        self.hide()
        _status(None)
        self.closed.emit(reason)

    def place(self):
        host = self.shell.view_widget()
        if host is None or not alive(host):
            self.hide_box("view")
            return False
        try:
            from . import tabstrip
            down = tabstrip.top()
        except Exception:
            down = 0
        at = host.mapTo(self.shell.window, QtCore.QPoint(OFFSET[0], OFFSET[1] + down))
        if at != self.pos():
            self.move(at)
        self.raise_()
        return True

    def remove(self):
        self._timer.stop()
        self.hide()
        self.setParent(None)
        self.deleteLater()

    # -- behaviour -------------------------------------------------------------------
    def selector_hidden(self, reason):
        """The View Selector in the 3D view went away: unpinned, the box follows."""
        if reason in ("pick", "click", "escape") and not self.pinned:
            self.hide_box(reason)

    def after_pick(self):
        ""
        if self.pinned:
            return
        self.hide_box("pick")
        selector = getattr(self.shell, "view_selector", None)
        if selector is not None:
            selector.hide("pick")

    def _selector_toggled(self, on):
        viewselector.set_enabled(on)
        self.selector_toggled.emit(bool(on))

    def _pin_toggled(self, on):
        self.pinned = bool(on)

    def _list_picked(self, item):
        key = item.data(Qt.UserRole)
        saved = item.data(Qt.UserRole + 1)
        if key:
            self.shell.binding(key).run()
            QtCore.QTimer.singleShot(0, self.after_pick)
        elif saved:
            try:
                self.shell.push_view()
            except Exception as _fw_err:
                _fw_log("orientation.py:427", _fw_err)
            namedviews.go(saved)
            QtCore.QTimer.singleShot(0, self.after_pick)

    def _list_menu(self, pos):
        ""
        item = self.list.itemAt(pos)
        saved = item.data(Qt.UserRole + 1) if item is not None else None
        if not saved:
            return
        menu = QtWidgets.QMenu(self)
        rename = menu.addAction("Rename")
        delete = menu.addAction("Delete")
        chosen = menu.exec(self.list.viewport().mapToGlobal(pos))
        if chosen is rename:
            name, ok = QtWidgets.QInputDialog.getText(self, "Rename View", "View name:", text=saved)
            if ok:
                namedviews.rename_view(saved, name)
        elif chosen is delete:
            namedviews.delete_view(saved)
        self.fill_list()

    def _new_view(self):
        if namedviews.ask_new_view(self.shell.window):
            self.fill_list()

    def _reset_views(self):
        namedviews.reset_standard()
        self.fill_list()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        return False        # view buttons: OrientationPanel.picked

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.shell.hide_orientation("escape")
            return
        super().keyPressEvent(event)


MORE_KEYS = ("UpdateStandardViews", "ResetStandardViews", "YUpViewOrientation", "ZUpViewOrientation")


def glyph_more(painter, rect):
    from .widgets import draw_arrow_right
    draw_arrow_right(painter, rect.center().x(), rect.center().y(), T.arrow, 6)


class FlyoutPanel(QtWidgets.QWidget):
    ""



    done = QtCore.Signal()

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.setObjectName("SWViewOrientationFlyout")
        self.setFont(ui_font())
        self.panel = OrientationPanel(shell, self)
        self.panel.picked.connect(self.done.emit)
        self.top = []
        self.panel._also = self.top
        for key in ("NewView", "ViewSelector"):
            b = CommandButton(shell, key, None, "qat", self)
            b.resize(BUTTON, BUTTON)
            b.setObjectName("SWFlyout" + key)
            b.installEventFilter(self.panel)
            self.top.append(b)
        self.more = GlyphButton(glyph_more, "More view orientation commands", self, size=BUTTON)
        self.more.setObjectName("SWFlyoutMore")
        self.more.clicked.connect(self._more)
        w = self.panel.width()
        x = w - 3 * BUTTON + ARROW_W
        for b in self.top + [self.more]:
            b.move(x, 0)
            x += BUTTON
        self.more.resize(BUTTON - ARROW_W, BUTTON)
        self.panel.move(0, BUTTON + 2)
        self.setFixedSize(w, BUTTON + 2 + self.panel.height())
        self.panel.refresh()

    def _more(self):
        from .widgets import popup_menu
        menu = self.shell.menu_for_keys(MORE_KEYS)
        menu.triggered.connect(lambda _act: self.done.emit())
        popup_menu(menu, self.more.mapToGlobal(QtCore.QPoint(self.more.width(), 0)))


def fill_flyout(shell, menu):
    """Puts the View Orientation panel in the heads-up flyout's menu; a pick closes the menu."""
    panel = FlyoutPanel(shell, menu)
    holder = QtWidgets.QWidget(menu)
    holder.setObjectName("SWViewOrientationHolder")
    lay = QtWidgets.QVBoxLayout(holder)
    lay.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
    lay.addWidget(panel)
    act = QtWidgets.QWidgetAction(menu)
    act.setDefaultWidget(holder)
    menu.addAction(act)
    panel.done.connect(menu.close)
    menu.setProperty("swOrientationPanel", True)
    return menu
