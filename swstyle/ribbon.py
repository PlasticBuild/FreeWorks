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

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import catalog, customizedlg, icons, style
from .widgets import (CommandButton, FlatButton, Separator, alive, draw_arrow, glyph_caret_down,
                      glyph_caret_up, glyph_chevron_right, glyph_close, glyph_ellipsis, glyph_maximize, glyph_span,
                      glyph_minimize, glyph_triangle_right, popup_menu, scaled, ui_font, ui_scale)


# Pages and menu-strip buttons taken off the CommandManager are not deleted at once: a click on one of
# their buttons may still be running below a box it opened (the New box, a save box, Insert
# Components), and freeing the button under it took FreeCAD down on Windows (new part window opened
# while an assembly was active, 2026-10-31). They are hidden here and freed once nothing is busy.
_parked = []          # (time parked, widget)
_sweep_timer = None
PARK_SECONDS = 3.0


def park(widget):
    if not alive(widget):
        return
    widget.hide()
    _parked.append((time.monotonic(), widget))
    global _sweep_timer
    if _sweep_timer is None:
        _sweep_timer = QtCore.QTimer()
        _sweep_timer.setInterval(1000)
        _sweep_timer.timeout.connect(_sweep)
    if not _sweep_timer.isActive():
        # not restarted on each park: pages parked less than 1 s apart (every workbench change rebuilds the
        # CommandManager) kept pushing the sweep back, so no parked page was ever freed (pkg250, Reviewer soak)
        _sweep_timer.start()


def _busy():
    app = QtWidgets.QApplication
    if app.activeModalWidget() is not None or app.activePopupWidget() is not None:
        return True
    try:
        held = app.mouseButtons()
        value = getattr(held, "value", None)
        return bool(int(value if value is not None else held))
    except Exception:
        return False


def _sweep():
    if _busy():
        return
    now = time.monotonic()
    keep = []
    for when, widget in _parked:
        if now - when < PARK_SECONDS:
            keep.append((when, widget))
        elif alive(widget):
            widget.deleteLater()
    _parked[:] = keep
    if not _parked and _sweep_timer is not None:
        _sweep_timer.stop()

Qt = QtCore.Qt

T = style.T                        # the theme's colours (T.pane, T.qat, ...), read when painting
LOGO_RED = QtGui.QColor("#d4202a")

QAT_H, LINE_H, RIBBON_H, TABS_H = 33.5, 0.5, 70.5, 21.5

SMALL_H = 26.5


def large_buttons():
    try:
        return bool(customizedlg.option("LargeButtonsWithText"))
    except Exception:
        return True


def band_h():
    ""
    return RIBBON_H if large_buttons() else SMALL_H


def shown_title(page):
    """The tab's name as the row shows it: a tab renamed with Rename Tab... keeps its own title inside."""
    try:
        from . import cmcustom
        return cmcustom.shown_name(page.title)
    except Exception:
        return page.title
LOGO_W = 110.5


def px(value, dpr):
    return int(round(value * dpr))



# takes here (1 when Qt scales the window for the screen).


# --------------------------------------------------------------------------- ribbon page
class GroupBox(QtWidgets.QWidget):
    """Transparent container that lays out a stack column or a small-icon grid."""

    def __init__(self, kind="stack", parent=None):
        super().__init__(parent)
        self.kind = kind         # stack | grid | native
        self.k = ui_scale()
        self.buttons = []
        self.cells = []          # grid: [(row, column, button)]
        self.compact = False     # one row of small buttons (Use Large Buttons with Text off)

    def arrange(self):
        """Place the buttons for their current sizes (they lose their text as the window narrows)."""
        s = lambda v: scaled(v, self.k)
        if self.compact:
            x = 0
            order = [b for _r, _c, b in sorted(self.cells, key=lambda c: (c[0], c[1]))] if self.kind == "grid" \
                else self.buttons
            for b in order:
                w = b.sizeHint().width()
                b.setGeometry(x, s(1), w, s(23))
                x += w
            self.resize(x + s(1), s(SMALL_H) - s(1))
            return
        if self.kind == "grid":
            ncols = 1 + max(col for _, col, _ in self.cells)
            for r, col, b in self.cells:
                b.setGeometry(s(1) + s(33) * col, s(2) + s(23) * r, b.sizeHint().width(), s(23))
            self.resize(s(1) + s(33) * (ncols - 1) + s(24) + s(2), s(70))
            return
        width = max(b.sizeHint().width() for b in self.buttons)
        for row, b in enumerate(self.buttons):
            b.setGeometry(0, s(1) + s(23) * row, width, s(23))
        self.resize(width + (s(2) if self.kind == "native" else s(1)), s(70))


class OverflowStrip(QtWidgets.QFrame):
    ""



    def __init__(self, shell, title, spec, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("SWCommandOverflowStrip")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFrameShape(QtWidgets.QFrame.Box)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QtGui.QPalette.Window, QtGui.QColor(T.pane))
        self.setPalette(pal)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        self.page = RibbonPage(shell, title, spec, self)
        self.page.ensure_built()
        self.page.set_mode(0)
        self.page.relayout(100000)
        self.page.setFixedWidth(self.page.needed_width() + self.page.s(4))
        lay.addWidget(self.page)
        for b in self.page.buttons():
            try:
                b.binding.resolve()
                b.binding.update_state()
            except Exception as _fw_err:
                _fw_log("ribbon.py:strip-state", _fw_err)
            b.installEventFilter(self)

    def eventFilter(self, obj, event):
        if isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.MouseButtonRelease:
            QtCore.QTimer.singleShot(0, lambda: alive(self) and self.close())
        return False

    def show_under(self, anchor):
        self.adjustSize()
        win = anchor.window()
        right = win.mapToGlobal(QtCore.QPoint(win.width(), 0)).x()
        below = anchor.mapToGlobal(QtCore.QPoint(0, anchor.height())).y()
        x = max(win.mapToGlobal(QtCore.QPoint(0, 0)).x(), right - self.width())
        self.move(x, below)
        self.show()
        self.raise_()


class RibbonPage(QtWidgets.QWidget):
    LEFT = 3
    RESERVED = 26   # chevron / collapse column on the right


    # of the large ones, before it moves tools behind the >> chevron
    MODES = ((CommandButton.FULL, CommandButton.FULL),
             (CommandButton.NO_TEXT, CommandButton.FULL),
             (CommandButton.NO_TEXT, CommandButton.NO_TEXT))

    def __init__(self, shell, title, spec, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.title = title
        self.k = ui_scale()
        self.items = []          # [(widget, [keys])]
        self.hidden_keys = []
        self.mode = 0            # index into MODES
        self.spec = spec
        self.built = False       # the buttons are made on the first show or layout (startup time)
        self._spec_of = {}       # cmstrip-1121: id(widget) -> its spec item (the >> strip rebuilds the hidden ones)
        self.hidden_spec = []
        self.setFixedHeight(self.s(70))

    def ensure_built(self):
        if self.built:
            return False
        self.built = True
        for item in self.spec:
            n = len(self.items)
            self._add(item)
            for w, _ in self.items[n:]:
                self._spec_of[id(w)] = item
        return True

    def showEvent(self, e):
        if self.ensure_built():
            self.relayout(self.width())
        super().showEvent(e)

    def s(self, value):
        return scaled(value, self.k)

    def _add(self, item):
        kind = item[0]
        shell = self.shell
        if kind == "sep":
            try:      # Dark: line_light is nearly the pane colour, so the groups ran together
                dark = QtGui.QColor(T.pane).lightness() < 128
            except Exception:
                dark = False
            w = Separator(color="text_disabled" if dark else "line_light", height=self.s(70), parent=self)
            w.setFixedSize(self.s(2), self.s(70))
            self.items.append((w, []))
        elif kind == "large":
            w = CommandButton(shell, item[1], item[2], "large", self)
            w.resize(w.sizeHint())
            self.items.append((w, [item[1]]))
        elif kind == "stack":
            box = GroupBox("stack", self)
            for key, flyout in item[1]:
                box.buttons.append(CommandButton(shell, key, flyout, "stack", box))
            box.arrange()
            self.items.append((box, [key for key, _ in item[1]]))
        elif kind == "grid":
            box = GroupBox("grid", self)
            keys = []
            for r, row in enumerate(item[1]):
                for col, (key, flyout) in enumerate(row):
                    b = CommandButton(shell, key, flyout, "grid", box)
                    box.buttons.append(b)
                    box.cells.append((r, col, b))
                    keys.append(key)
            box.arrange()
            self.items.append((box, keys))
        elif kind == "native":
            # ("native", [QAction, ...]) -> stacked rows of native FreeCAD actions
            for chunk_start in range(0, len(item[1]), 3):
                box = GroupBox("native", self)
                for action in item[1][chunk_start:chunk_start + 3]:
                    box.buttons.append(NativeActionButton(action, box))
                box.arrange()
                self.items.append((box, []))

    def set_mode(self, index):
        """Show the buttons as MODES[index] says, and resize them and their boxes to match."""
        self.ensure_built()
        self._set_compact(False)
        small, large = self.MODES[index]
        self.mode = index
        for w, _ in self.items:
            if isinstance(w, CommandButton):
                w.set_show_mode(large)
                w.resize(w.sizeHint())
            elif isinstance(w, GroupBox) and w.kind != "grid":
                for b in w.buttons:
                    b.set_show_mode(small)
                w.arrange()

    def _set_compact(self, on):
        """Use Large Buttons with Text off: every button a small icon, the groups side by side in one row
        (the separators between them kept)."""
        h = self.s(SMALL_H if on else 70)
        self.setFixedHeight(h)
        for w, _ in self.items:
            if isinstance(w, Separator):
                w.setFixedSize(self.s(2), h)
            elif isinstance(w, CommandButton):
                if on:
                    w.set_show_mode(CommandButton.COMPACT)
                    w.move(w.x(), self.s(1))
                elif w.show_mode == CommandButton.COMPACT:
                    w.set_show_mode(CommandButton.FULL)
                    w.move(w.x(), 0)
                w.resize(w.sizeHint())
            elif isinstance(w, GroupBox):
                w.compact = on
                for b in w.buttons:
                    if on:
                        b.set_show_mode(CommandButton.COMPACT)
                    elif b.show_mode == CommandButton.COMPACT:
                        b.set_show_mode(CommandButton.FULL)
                w.arrange()

    def needed_width(self):
        widths = [w.width() for w, _ in self.items if not (isinstance(w, CommandButton) and w.idle())]
        if self.items and isinstance(self.items[-1][0], Separator):
            widths.pop()
        return self.s(self.LEFT) + sum(widths)

    def _drop_text(self, limit):
        """Takes the text off one button at a time, from the right: the small (stacked) buttons
        first, then the large ones, so only as many buttons as needed lose their names
        (a few pixels short no longer leaves the whole tab without text)."""
        stacks = [w for w, _ in self.items if isinstance(w, GroupBox) and w.kind != "grid"]
        larges = [w for w, _ in self.items if isinstance(w, CommandButton)]
        for w in reversed(stacks):
            if self.needed_width() <= limit:
                return True
            for b in w.buttons:
                b.set_show_mode(CommandButton.NO_TEXT)
            w.arrange()
        for w in reversed(larges):
            if self.needed_width() <= limit:
                return True
            w.set_show_mode(CommandButton.NO_TEXT)
            w.resize(w.sizeHint())
        return self.needed_width() <= limit

    def relayout(self, width):
        self.ensure_built()
        large = large_buttons()

        # collapse arrow sit side by side at its right end)
        limit = width - self.s(self.RESERVED if large else 2 * self.RESERVED - 6)
        if large:
            self.set_mode(0)
            if self.needed_width() > limit:
                self._drop_text(limit)
                self.mode = len(self.MODES) - 1 if self.needed_width() > limit else 1
        else:
            self._set_compact(True)
            self.mode = len(self.MODES) - 1
        y = 0 if large else self.s(1)
        x = self.s(self.LEFT)
        self.hidden_keys = []
        self.hidden_spec = []
        overflow = False
        for w, keys in self.items:
            if isinstance(w, CommandButton) and w.idle():
                w.hide()                # nothing to act on yet: not shown (CommandButton.IDLE_HIDDEN)
                continue
            ww = w.width()
            if not overflow and x + ww <= limit:
                w.move(x, y if isinstance(w, CommandButton) else 0)   # a box places its own buttons
                w.show()
                x += ww
            else:
                overflow = True
                w.hide()
                self.hidden_keys.extend(keys)
                item = self._spec_of.get(id(w))
                if item is not None and not any(item is h for h in self.hidden_spec):
                    self.hidden_spec.append(item)
        # never leave a trailing separator visible
        visible = [w for w, _ in self.items if not w.isHidden()]
        if visible and isinstance(visible[-1], Separator):
            visible[-1].hide()
        return overflow

    def buttons(self):
        """The page's CommandButtons; a page not yet built has none (its state is read when built)."""
        for w, _ in self.items:
            if isinstance(w, CommandButton):
                yield w
            elif isinstance(w, GroupBox):
                for b in w.buttons:
                    if isinstance(b, CommandButton):
                        yield b


class NativeActionButton(QtWidgets.QWidget):
    """Stack-row button for a native FreeCAD QAction (workbench tab)."""

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action
        self.k = ui_scale()
        self.show_mode = CommandButton.FULL
        self.setFont(ui_font())
        self.setAttribute(Qt.WA_Hover, True)
        self._down = False
        text = action.iconText() or action.text()
        self.text = text.replace("&", "")
        self.setToolTip(action.toolTip())
        try:
            action.changed.connect(self.update)
        except Exception as _fw_err:
            _fw_log("ribbon.py:296", _fw_err)

    def set_show_mode(self, mode):
        self.show_mode = mode
        self.update()

    def sizeHint(self):
        s = lambda v: scaled(v, self.k)
        if self.show_mode != CommandButton.FULL:
            return QtCore.QSize(s(2) + s(20) + s(2), s(23))
        fm = QtGui.QFontMetrics(self.font())
        return QtCore.QSize(s(2) + s(20) + s(4) + fm.horizontalAdvance(self.text) + s(6), s(23))

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._down = True
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._down:
            self._down = False
            self.update()
            if alive(self.action) and self.action.isEnabled() and self.rect().contains(e.position().toPoint()):
                if self.action.menu() is not None:
                    self.action.menu().popup(self.mapToGlobal(QtCore.QPoint(0, self.height())))
                else:
                    self.action.trigger()

    def paintEvent(self, e):
        if not alive(self.action):
            return
        p = QtGui.QPainter(self)
        enabled = self.action.isEnabled()
        from .widgets import T, hairline_pen          # the theme's colours (widgets has no DOWN_FILL... names)
        DOWN_FILL, DOWN_LINE, HOVER_FILL, HOVER_LINE = T.down, T.down_line, T.hover, T.hover_line
        TEXT, TEXT_DISABLED = T.text, T.text_disabled
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._down or (self.action.isCheckable() and self.action.isChecked()):
            p.setPen(hairline_pen(DOWN_LINE)); p.setBrush(DOWN_FILL); p.drawRect(r)
        elif self.underMouse() and enabled:
            p.setPen(hairline_pen(HOVER_LINE)); p.setBrush(HOVER_FILL); p.drawRect(r)
        s = lambda v: scaled(v, self.k)
        style.paint_icon(p, self.action.icon(), QtCore.QRect(s(2), s(1), s(20), s(20)), Qt.AlignCenter,
                                 QtGui.QIcon.Normal if enabled else QtGui.QIcon.Disabled)
        if self.show_mode == CommandButton.FULL:
            p.setPen(TEXT if enabled else TEXT_DISABLED)
            p.setFont(self.font())
            p.drawText(QtCore.QPointF(s(26), s(16)), self.text)
        p.end()


# --------------------------------------------------------------------------- tab row
class TabRow(QtWidgets.QWidget):
    current_changed = QtCore.Signal(int)
    toggle_collapse = QtCore.Signal()

    PAD = 6.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titles = []
        self.current = 0
        self.collapsed = False
        self._hover = -1
        self._spans = []     # [(x0_px, x1_px)] device pixels, tab interiors, in the order shown (self._order)
        self._shown = 0      # how many tabs fit; the rest sit behind the >> at the row's end
        self._order = []     # cmrow-1120: tab indexes in the order drawn (the current tab is always among the shown)
        self._labels = []    # cmtabfit-1120: each tab's text as drawn (shortened with ".." when the row is narrow)
        self.setMouseTracking(True)
        self.setFont(ui_font())
        self.k = ui_scale()
        self.expand_button = FlatButton(glyph=glyph_caret_down, size=(16, 16), parent=self,
                                        hover_fill="tab_hover", down_fill="down")
        self.expand_button.setToolTip("Expand the CommandManager")
        self.expand_button.clicked.connect(self.toggle_collapse.emit)
        self.expand_button.hide()

    def set_titles(self, titles):
        self.titles = list(titles)
        self.current = min(self.current, max(0, len(self.titles) - 1))
        self.update()

    def set_current(self, index):
        if 0 <= index < len(self.titles) and index != self.current:
            self.current = index
            self.update()
            self.current_changed.emit(index)

    def set_collapsed(self, collapsed):
        self.collapsed = collapsed
        self.expand_button.setVisible(collapsed)
        self.update()

    def resizeEvent(self, e):
        self.expand_button.move(self.width() - scaled(20, self.k), scaled(4, self.k))
        super().resizeEvent(e)

    def natural_width(self):
        """Logical px the tabs take side by side (the collapsed row's expand button included)."""
        dpr = self.devicePixelRatioF()
        widths = self._natural_widths(dpr)          # cmtabfit-1120: full names, never the shortened ones
        end = (sum(widths) + len(widths)) / dpr if widths else 0
        return int(end + (scaled(22, self.k) if self.collapsed else 0)) + 1

    def _more_w(self):
        return scaled(18, self.k)

    def hidden_tabs(self):
        """Indexes of the tabs that do not fit the row (behind its >>)."""
        self._compute(self.devicePixelRatioF())
        return list(self._order[self._shown:])

    def more_rect(self):
        """The >> button at the row's end when some tabs do not fit, else None."""
        if not self.hidden_tabs():
            return None
        dpr = self.devicePixelRatioF()
        a = self._spans[self._shown - 1][1] / dpr + 1 if self._shown else 0
        return QtCore.QRect(int(a), 0, self._more_w(), self.height())

    def more_menu(self):
        """The tabs that do not fit, as a menu (the one picked becomes current)."""
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWTabRowMore")
        for i in self.hidden_tabs():
            a = menu.addAction(self.titles[i])
            a.setObjectName("SWTabRowMore_%d" % i)
            a.setCheckable(True)
            a.setChecked(i == self.current)
            a.triggered.connect(lambda _c=False, i=i: (self.toggle_collapse.emit() if self.collapsed else None,
                                                       self.set_current(i)))
        return menu

    def fit_width(self, width):
        """The width the row needs within width (logical px): all its tabs, or the ones that fit
        plus the >>."""
        dpr = self.devicePixelRatioF()
        spans = self._compute(dpr, width)
        try:
            if self._shown >= len(spans):
                return width
            end = spans[self._shown - 1][1] / dpr + 1 if self._shown else 0
            return min(width, int(end) + self._more_w())
        finally:
            self._compute(dpr)

    def _natural_widths(self, dpr):
        bold = ui_font(True)
        normal = ui_font(False)
        widths = []
        for i, title in enumerate(self.titles):
            fm = QtGui.QFontMetricsF(bold if i == self.current else normal)
            widths.append(px(fm.horizontalAdvance(title) + 2 * self.PAD * self.k, dpr))
        return widths

    def _short(self, i, room, dpr):
        ""

        title = self.titles[i]
        fm = QtGui.QFontMetricsF(ui_font(i == self.current))
        pad = 2 * self.PAD * self.k
        full = px(fm.horizontalAdvance(title) + pad, dpr)
        if full <= room:
            return title, full
        for n in range(len(title) - 1, 0, -1):
            text = title[:n].rstrip() + ("..." if n > 1 else "..")
            w = px(fm.horizontalAdvance(text) + pad, dpr)
            if w <= room or n == 1:
                return text, w
        return title, full

    def _compute(self, dpr, width=None):
        widths = self._natural_widths(dpr)
        labels = list(self.titles)
        n = len(widths)
        limit = (self.width() if width is None else width) * dpr - (scaled(22, self.k) * dpr if self.collapsed else 0)
        total = sum(widths) + n
        if n and total > limit:

            # right end first ("SOLIDW...", then "S.."), so every tab stays in the row and can be clicked.
            # The open tab is shortened too, and stays where it is.
            excess = total - limit
            for i in range(n - 1, -1, -1):
                if excess <= 0:
                    break
                floor = self._short(i, 0, dpr)[1]
                text, w = self._short(i, max(floor, widths[i] - excess), dpr)
                excess -= widths[i] - w
                widths[i] = w
                labels[i] = text
        spans, x = [], 0
        for w in widths:
            spans.append((x, x + w))
            x += w + 1           # 1 device pixel separator
        order = list(range(n))
        shown = n
        if spans and spans[-1][1] > limit:
            # narrower than every tab at one letter: the ones past the end still go behind >>
            room = limit - self._more_w() * dpr
            shown = len([1 for a, b in spans if b <= room])
        self._spans = spans
        self._order = order
        self._labels = labels
        self._shown = shown
        return spans

    def _index_at(self, pos):
        dpr = self.devicePixelRatioF()
        xp = pos.x() * dpr
        for pos, (a, b) in enumerate(self._spans[:self._shown]):
            if a <= xp < b + 1:
                return self._order[pos] if pos < len(self._order) else pos     # cmrow-1120: the tab's own index
        return -1

    def mouseMoveEvent(self, e):
        i = self._index_at(e.position())
        r = self.more_rect()
        if i < 0 and r is not None and r.contains(e.position().toPoint()):
            i = -2
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            r = self.more_rect()
            if r is not None and r.contains(e.position().toPoint()):
                from .widgets import popup_menu
                popup_menu(self.more_menu(), self.mapToGlobal(r.bottomLeft()))
                return
            i = self._index_at(e.position())
            if i >= 0:
                if self.collapsed:
                    self.toggle_collapse.emit()
                self.set_current(i)

    def mouseDoubleClickEvent(self, e):
        if self._index_at(e.position()) >= 0:
            self.toggle_collapse.emit()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        dpr = self.devicePixelRatioF()
        W = px(self.width(), dpr)
        H = px(self.height(), dpr)
        top = px(0.5, dpr)          # row(s) that belong to the band above
        line = max(1, px(0.5, dpr))
        body_top = top + line
        body_bottom = H - line
        p.save()
        p.scale(1.0 / dpr, 1.0 / dpr)
        p.fillRect(0, 0, W, top, T.qat if self.collapsed else T.pane)
        p.fillRect(0, top, W, line, T.line)
        p.fillRect(0, body_top, W, body_bottom - body_top, T.tab)
        p.fillRect(0, body_bottom, W, line, T.line)
        spans = self._compute(dpr)[:self._shown]
        for pos, (a, b) in enumerate(spans):
            i = self._order[pos]        # cmrow-1120: tabs drawn in the row's order
            if i == self.current:
                y0 = body_top if self.collapsed else 0
                p.fillRect(a, y0, b - a, body_bottom - y0, T.pane)
            elif i == self._hover:
                p.fillRect(a, body_top, b - a, body_bottom - body_top, T.tab_hover)
            p.fillRect(b, top, 1, body_bottom - top, T.line)
        p.restore()
        r = self.more_rect()
        if r is not None:
            if self._hover == -2:
                p.fillRect(r, T.tab_hover)
            p.setPen(T.text)
            p.setFont(ui_font(False))
            p.drawText(r, Qt.AlignCenter, "\u00bb")
        for pos in range(len(spans)):
            i = self._order[pos]        # cmrow-1120
            title = self._labels[i] if i < len(self._labels) else self.titles[i]    # cmtabfit-1120
            a, b = spans[pos]
            font = ui_font(i == self.current)
            p.setFont(font)
            p.setPen(T.text)
            fm = QtGui.QFontMetricsF(font)
            x = (a / dpr) + self.PAD * self.k
            p.drawText(QtCore.QPointF(x, (1 + 15) * self.k), title)
        p.end()


# --------------------------------------------------------------------------- quick access
class LogoArea(QtWidgets.QWidget):
    ""

    hovered = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.k = ui_scale()
        self.setFixedSize(scaled(int(LOGO_W), self.k), scaled(33, self.k))
        self.setAttribute(Qt.WA_Hover, True)
        self.setMouseTracking(True)
        self.setToolTip("Menus")
        app_icon = QtWidgets.QApplication.windowIcon()
        self.app_icon = app_icon

    def enterEvent(self, e):
        self.hovered.emit()
        self.update()

    def leaveEvent(self, e):
        self.update()

    def mousePressEvent(self, e):
        self.hovered.emit()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        k = self.k
        if not self.app_icon.isNull():
            style.paint_icon(p, self.app_icon, QtCore.QRect(scaled(6, k), scaled(7, k), scaled(19, k), scaled(19, k)))
        bold = ui_font(True, 10.5)
        thin = ui_font(False, 10.5)
        p.setPen(LOGO_RED)
        p.setFont(bold)
        x = 29.0 * k
        p.drawText(QtCore.QPointF(x, 21.5 * k), "Free")
        x += QtGui.QFontMetricsF(bold).horizontalAdvance("Free")
        p.setFont(thin)
        p.drawText(QtCore.QPointF(x, 21.5 * k), "CAD")
        c = T.arrow if self.underMouse() else T.arrow_dim
        path = QtGui.QPainterPath()
        path.moveTo(100.0 * k, 11.5 * k)
        path.lineTo(105.5 * k, 16.75 * k)
        path.lineTo(100.0 * k, 22.0 * k)
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawPath(path)
        p.end()


class MenuStrip(QtWidgets.QWidget):
    ""

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.pinned = False
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self._layout = QtWidgets.QHBoxLayout(self)
        self.k = ui_scale()
        self._layout.setContentsMargins(scaled(4, self.k), scaled(2, self.k), scaled(4, self.k), scaled(2, self.k))
        self._layout.setSpacing(0)
        self.pin = FlatButton(icons.family("PIN_NORMAL"), "Keep the menus visible", (26, 28), 16, self)
        self.pin.setCheckable(True)
        self.pin.toggled.connect(self._pin_toggled)
        self._buttons = []
        self.hide()

    def _pin_toggled(self, on):
        self.pinned = on
        self.pin.set_icon(icons.family("PIN_ACTIVE" if on else "PIN_NORMAL"))
        self.pin.setToolTip("Unpin the menus" if on else "Keep the menus visible")
        try:
            customizedlg._p().SetBool("MenusPinned", bool(on))
        except Exception as _fw_err:
            _fw_log("ribbon.py:pin_save", _fw_err)
        self.shell.qat_relayout()

    def rebuild(self):
        for b in self._buttons:
            self._layout.removeWidget(b)
            park(b)
        self._buttons = []
        self._layout.removeWidget(self.pin)
        bar = self.shell.native_menubar()
        actions = list(bar.actions()) if bar is not None else []
        for action in actions:
            menu = action.menu()
            if menu is None or not action.isVisible():
                continue
            b = QtWidgets.QToolButton(self)
            b.setObjectName("SWMenuStripButton")
            b.setText(action.text())
            b.setMenu(menu)
            b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setAutoRaise(True)
            b.setFont(ui_font())
            b.setFixedHeight(scaled(26, self.k))
            self._layout.addWidget(b)
            self._buttons.append(b)
        self._layout.addWidget(self.pin)
        self.adjustSize()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), T.qat)
        p.end()

    def any_menu_open(self):
        return any(b.menu() is not None and b.menu().isVisible() for b in self._buttons if alive(b))


SEARCH_W = 196
SEARCH_H = 24
SEARCH_QSS = """
QLineEdit#SWSearchBox { background: ${base}; border: 1px solid ${field_line}; border-radius: 2px;
                        padding: 1px 4px 1px 2px; color: ${text}; selection-background-color: ${accent}; }
QLineEdit#SWSearchBox:focus { border: 1px solid ${accent}; }
"""


def search_icon(dpr=1.0):
    """A magnifier, drawn: FreeCAD's icon theme has none that fits a 16 px box."""
    pm = QtGui.QPixmap(int(16 * dpr), int(16 * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(T.text_dim)
    pen.setWidthF(1.6)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QtCore.QPointF(6.5, 6.5), 4.2, 4.2)
    painter.drawLine(QtCore.QPointF(9.6, 9.6), QtCore.QPointF(14, 14))
    painter.end()
    return QtGui.QIcon(pm)


COMMANDS = "SWStyle_SearchCommands"


class SearchBox(QtWidgets.QLineEdit):
    ""


    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.setObjectName("SWSearchBox")
        # Only a click or the search key focuses it (C29-01). With NoFocus, Qt never hands it the
        # focus on its own when an editor closes (a PropertyManager field, the Property view's
        # value editors, a tree rename, a spin box): those leave the keys with their own view.
        # A click raises the policy for the moment of the press; setFocus() ignores the policy, so
        # the Search key still works.
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(ui_font())
        self.setPlaceholderText("Search Commands")
        self.setClearButtonEnabled(True)
        self.setFixedSize(scaled(SEARCH_W), scaled(SEARCH_H))
        icon = icons.family("SEARCH_COMMANDS")
        self._drawn_lens = icon.isNull()
        if self._drawn_lens:
            icon = search_icon(self.devicePixelRatioF())
        self.lens = self.addAction(icon, QtWidgets.QLineEdit.LeadingPosition)
        self.lens.setToolTip("Search Help, Commands, Files and Models or Community")
        self.lens.triggered.connect(self.show_kinds)
        self.setStyleSheet(style.fill(SEARCH_QSS))
        self.textEdited.connect(self._typed)
        self.returnPressed.connect(self._enter)
        self.kind = COMMANDS
        try:
            from . import paths
            kept = paths.params().GetString("SearchKind", COMMANDS)
            if kept in [n for _t, n in self.KINDS] and self._available(kept):
                self.set_kind(kept, remember=False)
        except Exception as _fw_err:
            _fw_log("ribbon.py:search-kind", _fw_err)

    KINDS = (("Help", "SWStyle_HelpSearchHelp"), ("Commands", "SWStyle_SearchCommands"),
             ("Files and Models", "SWStyle_SearchFiles"), ("Community", "SWStyle_SearchCommunity"))

    @staticmethod
    def _available(name):
        try:
            return name == COMMANDS or name in Gui.listCommands()
        except Exception:
            return False

    def set_kind(self, name, remember=True):
        ""

        self.kind = name
        text = dict((n, t) for t, n in self.KINDS).get(name, "Commands")
        self.setPlaceholderText("Search " + text)
        if name != COMMANDS:
            self._search().hide()
        if remember:
            try:
                from . import paths
                paths.params().SetString("SearchKind", name)
            except Exception as _fw_err:
                _fw_log("ribbon.py:search-kind-save", _fw_err)

    def kinds_menu(self):
        ""

        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWSearchKinds")
        words = self.text().strip()
        for text, name in self.KINDS:
            act = menu.addAction(text)
            act.setObjectName("SWSearchKind_" + text.replace(" ", ""))
            act.setCheckable(True)
            act.setChecked(name == getattr(self, "kind", COMMANDS))
            act.setVisible(self._available(name))      # NO DEAD CONTROLS: a search this installation lacks is not listed
            act.triggered.connect(lambda _c=False, n=name, w=words: self._picked_kind(n, w))
        return menu

    def _picked_kind(self, name, words):
        self.set_kind(name)
        if name == COMMANDS:
            if words:
                self._typed(self.text())
        elif words:
            self._search_with(name, words)

    def show_kinds(self):
        self.kinds_menu().popup(self.mapToGlobal(QtCore.QPoint(0, self.height())))

    def _search_with(self, name, words):
        try:
            from . import helpmenu
            if name == "SWStyle_HelpSearchHelp" and words:
                return helpmenu.show("home", search=words)
            if name == "SWStyle_SearchCommunity" and words:
                return helpmenu.search_community(words)
        except Exception as _fw_err:
            _fw_log("ribbon.py:741", _fw_err)
        Gui.runCommand(name, 0)

    def retheme(self):
        """A theme change: the box's colours and the drawn magnifier follow."""
        self.setStyleSheet(style.fill(SEARCH_QSS))
        if self._drawn_lens:
            self.lens.setIcon(search_icon(self.devicePixelRatioF()))

    def _search(self):
        return self.shell.command_search()

    def _typed(self, text):
        if getattr(self, "kind", COMMANDS) == COMMANDS:
            self._search().typed(text, self)

    def _enter(self):
        if getattr(self, "kind", COMMANDS) == COMMANDS:
            self._search().run_current()
            return
        words = self.text().strip()
        self._search_with(self.kind, words)

    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key_Escape:
            self.clear()
            self._search().hide()
            self.clearFocus()
            e.accept()
            return
        if key in (Qt.Key_Down, Qt.Key_Up) and self._search().list_shown():
            self._search().move_current(1 if key == Qt.Key_Down else -1)
            e.accept()
            return
        super().keyPressEvent(e)

    WANTED = (Qt.MouseFocusReason, Qt.ShortcutFocusReason, Qt.PopupFocusReason,
              Qt.ActiveWindowFocusReason, Qt.MenuBarFocusReason)

    def mousePressEvent(self, e):
        self.setFocusPolicy(Qt.ClickFocus)
        super().mousePressEvent(e)
        if not self.hasFocus():
            self.setFocus(Qt.MouseFocusReason)

    def focusInEvent(self, e):
        if e.reason() not in self.WANTED:
            # the focus chain (an editor closed, Tab, "other"): not for us, give it back (C29-01)
            super().focusInEvent(e)
            QtCore.QTimer.singleShot(0, self.give_back)
            return
        super().focusInEvent(e)
        if self.text().strip() and getattr(self, "kind", COMMANDS) == COMMANDS:
            self._search().typed(self.text(), self)

    def give_back(self):
        """The focus went to the box without a click or the search key: hand it to the 3D view."""
        if not self.hasFocus():
            return
        self.clearFocus()
        try:
            mw = Gui.getMainWindow()
            area = mw.findChild(QtWidgets.QMdiArea)
            sub = area.activeSubWindow() if area is not None else None
            target = sub.widget() if sub is not None else None
            if target is not None:
                target.setFocus(Qt.OtherFocusReason)
            else:
                mw.setFocus(Qt.OtherFocusReason)
        except Exception as _fw_err:
            _fw_log("ribbon.py:807", _fw_err)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.setFocusPolicy(Qt.NoFocus)
        QtCore.QTimer.singleShot(150, self._search().hide_if_unfocused)


class QatRow(QtWidgets.QWidget):
    LEFT = 120

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.k = ui_scale()
        self.setMouseTracking(True)
        self.logo = LogoArea(self)
        self.logo.move(0, 0)
        self.logo.hovered.connect(self.show_menus)
        self.menus = MenuStrip(shell, self)
        self.left = []
        for key, flyout in catalog.QUICK_ACCESS:
            b = CommandButton(shell, key, flyout, "qat", self)
            b.resize(self.s(30 if not flyout else 40), self.s(30))
            self.left.append(b)
        self.more = FlatButton(None, "More commands", (14, 30), 12, self, glyph=glyph_ellipsis)
        self.more.clicked.connect(self._show_more)
        self.more.hide()
        self._hidden = []

        self.document = QtWidgets.QLabel(self)
        self.document.setObjectName("SWDocumentName")
        self.document.setFont(ui_font())
        self.document.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.document.hide()
        self._document_text = ""
        self.search = SearchBox(shell, self)
        win = shell.window
        self.help = FlatButton(icons.family("MINMAX_HELP"), "Help", (36, 33), 20, self)
        self.help.clicked.connect(lambda: shell.show_help_menu(self.help))
        self.minimize = FlatButton(icons.family("MINMAX_MINIMIZE"), "Minimize", (36, 33), 20, self,
                                   glyph=glyph_minimize)
        self.minimize.clicked.connect(win.showMinimized)
        self.span = FlatButton(icons.family("MINMAX_SPAN_TB"), "Span the screen height", (36, 33), 20, self,
                               glyph=glyph_span)
        self.span.clicked.connect(shell.span_height)
        self.maximize = FlatButton(icons.family("MINMAX_MAXIMIZE"), "Maximize", (36, 33), 20, self,
                                   glyph=glyph_maximize)
        self.maximize.clicked.connect(shell.toggle_maximized)
        self.close_button = FlatButton(icons.family("MINMAX_CLOSE"), "Close", (33, 33), 20, self,
                                       hover_fill="#e81123", down_fill="#f1707a", glyph=glyph_close)
        hover = icons.family("MINMAX_CLOSE_HOVER")
        if not hover.isNull():
            self.close_button.hover_icon = hover
        self.close_button.clicked.connect(win.close)
        self._hide_timer = QtCore.QTimer(self)
        self._hide_timer.setInterval(350)
        self._hide_timer.timeout.connect(self._maybe_hide_menus)
        self.window_buttons = (self.help, self.minimize, self.span, self.maximize, self.close_button)
        self.set_frameless_controls(True)
        try:        # qatflyout-1119: menus pinned last session stay pinned
            if customizedlg._p().GetBool("MenusPinned", False):
                QtCore.QTimer.singleShot(0, self._restore_pin)
        except Exception as _fw_err:
            _fw_log("ribbon.py:pin_restore", _fw_err)

    def _restore_pin(self):
        if alive(self) and not self.menus.pinned:
            self.show_menus()
            self.menus.pin.setChecked(True)

    def s(self, value):
        return scaled(value, self.k)

    def set_frameless_controls(self, frameless):
        for b in (self.minimize, self.span, self.maximize, self.close_button):
            b.setVisible(frameless)
        self.relayout()

    def update_maximize_icon(self):
        mw = self.shell.window
        maxed = mw.isMaximized() or self.shell._fills(mw.geometry())     # a full-screen "normal" size too
        self.maximize.set_icon(icons.family("MINMAX_RESTORE" if maxed else "MINMAX_MAXIMIZE"))
        self.maximize.setToolTip("Restore Down" if maxed else "Maximize")

    def show_menus(self):
        if not self.menus.isVisible():
            self.menus.rebuild()
            self.menus.move(self.logo.width() + 1, 1)
            self.menus.resize(self.menus.sizeHint().width(), self.s(31))
            self.menus.show()
            self.menus.raise_()
        self._hide_timer.start()

    def _maybe_hide_menus(self):
        if self.menus.pinned:
            self._hide_timer.stop()
            return
        pos = self.mapFromGlobal(QtGui.QCursor.pos())
        over = self.logo.geometry().contains(pos) or self.menus.geometry().contains(pos)
        if over or self.menus.any_menu_open():
            return
        self.menus.hide()
        self._hide_timer.stop()

    def resizeEvent(self, e):
        self.relayout()
        super().resizeEvent(e)

    def relayout(self):
        x = self.s(self.LEFT)
        if self.menus.isVisible() and self.menus.pinned:
            x = self.logo.width() + 1 + self.menus.width() + self.s(6)
        right = self.width()
        for b in reversed(self.window_buttons):
            if b.isHidden() and b is not self.help:
                continue
            right -= b.width()
            b.move(right, 0)
        limit = right - self.s(6)
        try:        # Customize > Toolbars > Quick Access Toolbar > Show in the Menu Bar
            from . import customizedlg
            qat_on = bool(customizedlg.option("QatShowInMenuBar"))
        except Exception:
            qat_on = True
        self._home_buttons(qat_on)
        if not qat_on:     # extapps89: Show in the CommandManager: TopBar puts them at the right end of its tab row
            self.more.hide()
            self._hidden = []
            show_search = x + self.s(8) + self.search.width() <= limit
            self.search.setVisible(show_search)
            if show_search:
                limit -= self.search.width()
                self.search.move(limit, (self.s(33) - self.search.height()) // 2)
                limit -= self.s(8)
            self._place_document(x, limit)
            try:        # extapps94: a button shown or hidden for "nothing open" is placed again at once
                top = getattr(self.shell, "topbar", None)
                if top is not None and top is not self:
                    top._place_qat(top.width())
            except Exception as _fw_err:
                _fw_log("ribbon.py:qat-relayout", _fw_err)
            return
        for b in self.left:
            if getattr(b, "fw_no_document", False):
                b.hide()            # nothing open: only Home, New, Open and Options (nodocstate.py)
        left = [b for b in self.left if not getattr(b, "fw_no_document", False)]
        total = sum(b.width() for b in left)

        show_search = x + total + self.s(8) + self.search.width() <= limit
        self.search.setVisible(show_search)
        if show_search:
            limit -= self.search.width()
            self.search.move(limit, (self.s(33) - self.search.height()) // 2)
            limit -= self.s(8)
        self._hidden = []
        fits = x + total <= limit
        for b in left:
            if not self._hidden and (fits or x + b.width() + self.more.width() <= limit):
                b.move(x, self.s(2))
                b.show()
                x += b.width()
            else:
                b.hide()
                self._hidden.append(b)
        self.more.setVisible(bool(self._hidden))
        if self._hidden:
            self.more.move(x, self.s(2))
            x += self.more.width()
        self._place_document(x, limit)

    def _home_buttons(self, in_row):
        """Show in the Menu Bar: the quick access buttons live in this row; Show in the CommandManager: they are the
        top bar's children, placed at the right end of its tab row (TopBar._place_qat)."""
        bar = self.parent()
        want = self if in_row else (self.shell.window if getattr(bar, "tabs_on_view", False) else bar)
        for b in self.left:
            if want is not None and b.parent() is not want:
                b.setParent(want)
                if not in_row:
                    b.resize(self.s(24 if b.width() < self.s(36) else 34), self.s(20))
                else:
                    b.resize(self.s(30 if b.width() < self.s(36) else 40), self.s(30))

    DOC_GAP = 14
    DOC_MAX = 260

    def set_document(self, text):
        if text != self._document_text:
            self._document_text = text
            self.relayout()

    def _place_document(self, x, limit):
        ""



        text = self._document_text
        room = limit - x - self.s(self.DOC_GAP) - self.s(8)
        if not text or room < self.s(40):
            self.document.hide()
            return
        metrics = QtGui.QFontMetrics(self.document.font())
        width = min(metrics.horizontalAdvance(text) + self.s(4), room, self.s(self.DOC_MAX))
        self.document.setText(metrics.elidedText(text, Qt.ElideRight, width))
        left = x + self.s(self.DOC_GAP)
        self.document.setGeometry(left + (room - width) // 2, 0, width, self.s(33))
        self.document.show()

    def _show_more(self):
        if not self._hidden:
            return
        menu = self.shell.menu_for_keys([b.binding.cmd.key for b in self._hidden])
        popup_menu(menu, self.more.mapToGlobal(QtCore.QPoint(0, self.more.height())))


# --------------------------------------------------------------------------- top bar
class TopBar(QtWidgets.QWidget):
    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.setObjectName("SWTopBar")
        self.shell = shell
        self.k = ui_scale()
        self.collapsed = False
        self.tabs_on_view = False
        self.qat = QatRow(shell, self)
        self.stack = QtWidgets.QStackedWidget(self)
        self.stack.setAutoFillBackground(False)
        self.tabs = TabRow(self)
        self.tabs.current_changed.connect(self._tab_changed)
        self.tabs.toggle_collapse.connect(self.toggle_collapsed)
        self.chevron = FlatButton(glyph=glyph_chevron_right, size=(16, 16), parent=self,
                                  hover_fill="tab_hover", down_fill="down")
        self.chevron.setToolTip("More commands")
        self.chevron.clicked.connect(self._show_overflow)
        self.collapse_button = FlatButton(glyph=glyph_caret_up, size=(16, 16), parent=self,
                                          hover_fill="tab_hover", down_fill="down")
        self.collapse_button.setToolTip("Collapse the CommandManager")
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        self.pages = []
        self._wheel = 0              # wheel turn not yet worth a tab (high-resolution wheels)
        self.wheel_steps = 0         # tabs stepped by the wheel, for checks
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._apply_height()

    # the wheel --------------------------------------------------------------------
    def wheelEvent(self, e):
        ""


        if not self.over_command_manager(e.position().toPoint()):
            e.ignore()
            return
        delta = e.angleDelta().y()
        if abs(delta) >= 120:

            self._wheel = 0
            self.step_tab(1 if delta < 0 else -1)
        else:
            # a fine wheel: its small turns add up to notches
            self._wheel += delta
            notches = int(self._wheel / 120)
            if notches:
                self._wheel -= notches * 120
                self.step_tab(-notches)
        e.accept()

    def over_command_manager(self, pos):
        if self.tabs.geometry().contains(pos):
            return True
        return not self.collapsed and self.stack.geometry().contains(pos)

    def step_tab(self, steps):
        """The tab steps to the right (+) or left (-), stopping at the ends."""
        if not self.pages:
            return False
        index = max(0, min(self.tabs.current + steps, len(self.pages) - 1))
        if index == self.tabs.current:
            return False
        self.tabs.set_current(index)
        self.wheel_steps += 1
        return True

    # pages ------------------------------------------------------------------------
    def set_pages(self, pages, keep_title=None):
        current_title = keep_title or (self.pages[self.tabs.current].title if self.pages else None)
        # Removing the shown page shows the next one, and a page builds its buttons when first shown: an
        # empty page in front first, so the old pages go without each being built (0.5 s when an
        # assembly or a drawing became active).
        blank = QtWidgets.QWidget()
        self.stack.insertWidget(0, blank)
        self.stack.setCurrentWidget(blank)
        for page in self.pages:
            self.stack.removeWidget(page)
            park(page)
        self.stack.removeWidget(blank)
        blank.deleteLater()
        self.pages = list(pages)
        for page in self.pages:
            self.stack.addWidget(page)
        self.tabs.set_titles([shown_title(p) for p in self.pages])
        index = 0
        for i, page in enumerate(self.pages):
            if page.title == current_title:
                index = i
        self.tabs.current = -1
        self.tabs.set_current(index)
        self._layout_pages()

    def add_page(self, page):
        self.pages.append(page)
        self.stack.addWidget(page)
        self.tabs.set_titles([shown_title(p) for p in self.pages])
        self._layout_pages()

    def remove_page(self, page):
        if page in self.pages:
            index = self.pages.index(page)
            current = self.tabs.current
            self.pages.remove(page)
            self.stack.removeWidget(page)
            park(page)
            self.tabs.set_titles([shown_title(p) for p in self.pages])
            if current >= len(self.pages):
                current = len(self.pages) - 1
            self.tabs.current = -1
            self.tabs.set_current(max(0, current if current != index else 0))

    def select(self, title):
        for i, page in enumerate(self.pages):
            if page.title == title:
                self.tabs.set_current(i)
                return True
        return False

    def current_page(self):
        if not self.pages:
            return None
        return self.pages[self.stack.currentIndex()]

    def _tab_changed(self, index):
        if 0 <= index < len(self.pages):
            self.stack.setCurrentIndex(index)
            self._layout_pages()
            self.shell.page_shown(self.pages[index])

    # geometry ----------------------------------------------------------------------
    def total_height(self):
        k = self.k
        if self.property("swNoDocument"):
            return int(round(k * (QAT_H + LINE_H)))   # nothing open: the quick access row alone (nodocstate.py)
        tabs = 0.0 if self.tabs_on_view else TABS_H + LINE_H
        if self.collapsed:
            return int(round(k * (QAT_H + LINE_H + tabs)))
        return int(round(k * (QAT_H + LINE_H + band_h() + LINE_H + tabs)))

    def _apply_height(self):
        self.setFixedHeight(self.total_height())
        self._place()

    def toggle_collapsed(self):
        self.collapsed = not self.collapsed
        self.stack.setVisible(not self.collapsed)
        self.chevron.setVisible(not self.collapsed and self.chevron.isVisible())
        self.collapse_button.setVisible(not self.collapsed)
        self.tabs.set_collapsed(self.collapsed)
        self._apply_height()

    def resizeEvent(self, e):
        self._place()
        super().resizeEvent(e)

    def _place(self):
        if self.height() != self.total_height():
            self.setFixedHeight(self.total_height())   # Use Large Buttons with Text was switched
        w = self.width()
        s = lambda v: scaled(v, self.k)
        band = int(band_h())
        self.qat.setGeometry(0, 0, w, s(33))
        self._place_qat(w)
        if self.collapsed:
            if not self.tabs_on_view:
                self.tabs.setGeometry(0, s(33), w, self.height() - s(33))
        else:
            self.stack.setGeometry(0, s(34), w, s(band))
            if not self.tabs_on_view:
                self.tabs.setGeometry(0, s(34 + band), w, self.height() - s(34 + band))
        if band >= 70:
            self.collapse_button.move(w - s(20), s(34 + 50))
            self.chevron.move(w - s(20), s(34 + 14))
        else:                                           # one small row: >> then the collapse arrow
            self.collapse_button.move(w - s(20), s(34 + 5))
            self.chevron.move(w - s(38), s(34 + 5))
        self._layout_pages()

    def _place_qat(self, w):
        """Customize > Toolbars > Quick Access Tools > Show in the CommandManager (extapps89): the quick access
        buttons sit at the right end of the tab row, left of the collapse arrow."""
        try:
            in_row = bool(customizedlg.option("QatShowInMenuBar"))
            self.qat._home_buttons(in_row)
            if in_row:
                return
            k = self.k
            if self.tabs_on_view:           # the tab row floats over the graphics area: the buttons follow its right end
                g = self.tabs.geometry()
                x = g.right() + int(round(k * 10))
                for b in self.qat.left:
                    if getattr(b, "fw_no_document", False):
                        b.hide()            # extapps94: nothing open: only Home, New, Open and Options (nodocstate.py)
                        continue
                    b.move(x, g.y() + (g.height() - b.height()) // 2)
                    b.show()
                    b.raise_()
                    x += b.width()
                return
            top = int(round(k * (33.5 if self.collapsed else 34 + band_h() + LINE_H)))
            x = w - int(round(k * 44))
            for b in reversed(self.qat.left):
                if getattr(b, "fw_no_document", False):
                    b.hide()
                    continue
                x -= b.width()
                b.move(x, top + (int(round(k * TABS_H)) - b.height()) // 2)
                b.show()
                b.raise_()
        except Exception as _fw_err:
            _fw_log("ribbon.py:qat-cm", _fw_err)

    def _layout_pages(self):
        if self.collapsed:
            return
        w = self.width()
        overflow = False
        page = self.current_page()
        for p in self.pages:
            p.resize(w, scaled(int(band_h()), self.k))
            if p is not page and not p.built:
                continue            # laid out when first shown
            o = p.relayout(w)
            if p is page:
                overflow = o
        self.chevron.setVisible(overflow)
        self.chevron.raise_()
        self.collapse_button.raise_()

    def _show_overflow(self):
        page = self.current_page()
        if page is None:
            return
        spec = list(getattr(page, "hidden_spec", None) or [])
        while spec and spec[0][0] == "sep":
            spec.pop(0)
        while spec and spec[-1][0] == "sep":
            spec.pop()
        if spec:
            try:

                # in the CommandManager (big icons and text), right-aligned to the window's edge; Esc closes it
                strip = OverflowStrip(self.shell, page.title, spec, self)
                strip.show_under(self.chevron)
                return
            except Exception as _fw_err:
                _fw_log("ribbon.py:overflow-strip", _fw_err)
        menu = self.shell.menu_for_keys(page.hidden_keys)
        popup_menu(menu, self.chevron.mapToGlobal(QtCore.QPoint(0, self.chevron.height())))

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        dpr = self.devicePixelRatioF()
        p.scale(1.0 / dpr, 1.0 / dpr)
        W = px(self.width(), dpr)
        qat = px(QAT_H * self.k, dpr)
        line = max(1, px(LINE_H, dpr))
        p.fillRect(0, 0, W, qat, T.qat)
        logo = px(LOGO_W * self.k, dpr)
        p.fillRect(0, 0, logo, qat, T.pane)
        p.fillRect(logo, 0, 1, qat, T.line_light)
        p.fillRect(0, qat, W, line, T.line_light)
        if not self.collapsed:
            p.fillRect(0, qat + line, W, px(band_h() * self.k, dpr), T.pane)
        if self.tabs_on_view:                       # the CommandManager's bottom edge over the graphics area
            p.fillRect(0, px(self.height(), dpr) - line, W, line, T.line)
        p.end()
