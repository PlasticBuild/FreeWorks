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

from . import icons, style
from .widgets import alive, scaled, ui_font, ui_scale

Qt = QtCore.Qt

T = style.T                        # the theme's colours, read when painting

BLANK_TITLE = "SWBlankTitle"

# (icon family, tooltip, page id)
TABS = (
    ("PART_TAB", "FeatureManager Design Tree", "Model"),
    ("CMD_PROPERTIES", "PropertyManager (FreeCAD task panel)", "Tasks"),
    ("CONFIGURATION_TAB", "ConfigurationManager", "ConfigurationManager"),
    ("FLYOUT_DIMXPERT", "DimXpertManager", "DimXpertManager"),
    ("DISPLAY_MANAGER_TAB", "DisplayManager", "DisplayManager"),
    ("TOOLS_EQNS", "Python console", "Python console"),
    ("STANDARD_PROPERTIES", "Messages (FreeCAD report view)", "Report view"),
    ("CONFIG_HIDE_SHOW_CUSTOM_PROPS", "Properties of the selected item (FreeCAD property editor)", "PropertyView"),
)

OWN_PAGES = {"DisplayManager": ("displaymanager", "Page"), "ConfigurationManager": ("configmanager", "Page"),
             "DimXpertManager": ("dimxpertpane", "Page")}



DRAWING_SKIP = ("ConfigurationManager", "DimXpertManager", "DisplayManager")


# PropertyManager always stay.
HIDDEN_KEY = "HiddenManagerTabs"
KEEP = ("Model", "Tasks")


def hidden_tabs():
    p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks")
    return [x for x in p.GetString(HIDDEN_KEY, "").split(",") if x and x not in KEEP]


def set_hidden_tabs(ids):
    p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks")
    p.SetString(HIDDEN_KEY, ",".join(x for x in ids if x not in KEEP))


class CustomizeTabsDialog(QtWidgets.QDialog):
    """Right-click a Manager Pane tab > Customize: one box per tab, cleared to hide it."""

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWCustomizeManagerTabs")
        self.setWindowTitle("Customize Manager Pane")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Show these tabs in the Manager Pane:"))
        hidden = hidden_tabs()
        self.boxes = {}
        for fam, tip, pid in TABS:
            b = QtWidgets.QCheckBox(tip, self)
            b.setObjectName("SWManagerTab_%s" % pid.replace(" ", ""))
            b.setChecked(pid not in hidden)
            b.setEnabled(pid not in KEEP)
            try:
                ic = icons.family(fam)
                if not ic.isNull():
                    b.setIcon(ic)
            except Exception as _fw_err:
                _fw_log("leftpane.py:96", _fw_err)
            lay.addWidget(b)
            self.boxes[pid] = b
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def accept(self):
        set_hidden_tabs([pid for pid, b in self.boxes.items() if not b.isChecked()])
        super().accept()


def _drawing_in_front():
    try:
        mw = Gui.getMainWindow()
        mdi = mw.centralWidget() if isinstance(mw.centralWidget(), QtWidgets.QMdiArea) else mw.findChild(QtWidgets.QMdiArea)
        sub = mdi.activeSubWindow() if mdi is not None else None
        w = sub.widget() if sub is not None else None
        return w is not None and "TechDraw" in w.metaObject().className()
    except Exception:
        return False


def dev(v, dpr):
    return int(round(v * dpr))


def _blank_title(dock):
    ""
    blank = QtWidgets.QWidget(dock)
    blank.setObjectName(BLANK_TITLE)
    blank.setFixedHeight(0)
    return blank


PANE_WIDTH = 300    # logical px: FreeCAD's Pad/Pocket/Fillet panels fit without widening the pane


class PaneHeader(QtWidgets.QWidget):
    tab_clicked = QtCore.Signal(int)

    grip_pressed = QtCore.Signal(int)          # global y
    grip_dragged = QtCore.Signal(int)          # global y
    grip_released = QtCore.Signal(int)         # global y
    grip_double_clicked = QtCore.Signal()


    # the grip row 2..17, the filter row (FeatureManager only) 47..72
    TAB_W = 39.5
    TAB_TOP = 22.0
    TAB_H = 25.0
    FULL_H = 72
    SHORT_H = 50
    SHOWN = 5
    MAIN = 4              # FeatureManager, PropertyManager, ConfigurationManager, DimXpertManager; the rest

    LEFT = 2.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.k = ui_scale()
        self.setFixedHeight(scaled(self.FULL_H, self.k))
        self.setMouseTracking(True)
        self.current = 0
        self.first = 0         # first visible tab when scrolled
        self.hover = -1
        self.icons = [icons.family(t[0]) for t in TABS]
        self.filter_icon = icons.family("TREE_FEATURE_FILTER")
        self._drawing = None
        self._mode_timer = QtCore.QTimer(self)          # a drawing in front shows 2 tabs: repaint when that changes
        self._mode_timer.timeout.connect(self._check_mode)
        self._mode_timer.start(500)
        try:
            from . import ticks as _ticks
            _ticks.slow_when_idle(self._mode_timer)
        except Exception as _fw_err:
            __import__("FreeCAD").Console.PrintLog("FreeCAD ticks: %s\n" % _fw_err)
        self.filter = QtWidgets.QLineEdit(self)
        self.filter.setObjectName("SWTreeFilter")
        self.filter.setFrame(False)
        self.filter.setFont(ui_font())
        self.filter.setPlaceholderText("")
        self.filter.setToolTip("Filter the FeatureManager design tree")
        self.filter.setClearButtonEnabled(True)
        self.setFont(ui_font())
        self._grip_down = False

    def _check_mode(self):
        self._fit()                        # current can be set from outside (asmvistab)
        d = _drawing_in_front()
        if d != self._drawing:
            self._drawing = d
            self.update()

    # geometry ----------------------------------------------------------------------
    def _tab_rect(self, slot):
        k = self.k
        x = (self.LEFT + slot * (self.TAB_W + 0.5)) * k
        return QtCore.QRectF(x, (self.TAB_TOP + 0.5) * k, self.TAB_W * k, (self.TAB_H - 0.5) * k)

    def _arrows_rect(self):
        """Where the scroll arrows were: now past the right end (the "..." tab took their place)."""
        return QtCore.QRectF(self.width() + 1.0, 0.0, 0.0, 0.0)

    def _shown_tabs(self):
        skip = DRAWING_SKIP if _drawing_in_front() else ()
        hidden = hidden_tabs()
        return [i for i in range(len(TABS)) if TABS[i][2] not in skip and TABS[i][2] not in hidden]

    def main_tabs(self):
        # the first four shown managers (a drawing: FM and PM); a hidden tab leaves its place to the next
        shown = self._shown_tabs()
        return [i for i in shown if i < self.MAIN] if _drawing_in_front() else shown[:self.MAIN]

    def more_tabs(self):
        """The managers and panes in the "..." tab's menu."""
        main = self.main_tabs()
        return [i for i in self._shown_tabs() if i not in main]

    def visible_slots(self):
        return [(i, self._tab_rect(slot)) for slot, i in enumerate(self.main_tabs())]

    def more_rect(self):
        """The "..." tab after the managers, else None when nothing is behind it."""
        if not self.more_tabs():
            return None
        return self._tab_rect(len(self.main_tabs()))

    def more_menu(self):
        """The "..." tab's menu: one checkable entry for each manager or pane behind it."""
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWPaneMoreMenu")
        for i in self.more_tabs():
            act = menu.addAction(self.icons[i], TABS[i][1]) if not self.icons[i].isNull() else menu.addAction(TABS[i][1])
            act.setObjectName("SWPaneMore_%s" % TABS[i][2].replace(" ", ""))
            act.setCheckable(True)
            act.setChecked(i == self.current)
            act.triggered.connect(lambda checked=False, i=i: self.tab_clicked.emit(i))
        return menu

    def resizeEvent(self, e):
        s = lambda v: scaled(v, self.k)
        self.filter.setGeometry(s(27), s(self.TAB_TOP + self.TAB_H + 1), max(10, self.width() - s(32)), s(22))
        super().resizeEvent(e)

    # input -------------------------------------------------------------------------
    def grip_rect(self):
        return QtCore.QRectF(0, 0, self.width(), (self.TAB_TOP - 1.5) * self.k)

    def _hit(self, pos):
        if self.grip_rect().contains(pos):
            return "grip"
        more = self.more_rect()
        if more is not None and more.contains(pos):
            return "more"
        for i, r in self.visible_slots():
            if r.contains(pos):
                return i
        return None

    def mouseMoveEvent(self, e):
        if self._grip_down:
            self.grip_dragged.emit(int(e.globalPosition().y()))
            return
        hit = self._hit(e.position())
        self.setCursor(Qt.SplitVCursor if hit == "grip" else Qt.ArrowCursor)
        hover = hit if isinstance(hit, int) or hit == "more" else -1
        if hover != self.hover:
            self.hover = hover
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def customize_menu(self):
        ""
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWManagerTabsMenu")
        act = menu.addAction("Customize...")
        act.setObjectName("SWManagerTabsCustomize")
        act.triggered.connect(self.customize)
        return menu

    def customize(self):
        box = CustomizeTabsDialog(self.window())
        self._customize_box = box
        if box.exec():
            self._fit()
            self.update()
            if TABS[self.current][2] in hidden_tabs():
                self.tab_clicked.emit(0)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton and self._hit(e.position()) not in (None, "grip"):
            self._menu = self.customize_menu()
            self._menu.popup(e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        hit = self._hit(e.position())
        if hit == "grip":
            self._grip_down = True
            self.grip_pressed.emit(int(e.globalPosition().y()))
        elif hit == "more":
            r = self.more_rect()
            self._menu = self.more_menu()
            self._menu.popup(self.mapToGlobal(QtCore.QPoint(int(r.left()), int(r.bottom()) + 1)))
        elif isinstance(hit, int):
            self.tab_clicked.emit(hit)

    def mouseReleaseEvent(self, e):
        if self._grip_down and e.button() == Qt.LeftButton:
            self._grip_down = False
            self.grip_released.emit(int(e.globalPosition().y()))

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton and self._hit(e.position()) == "grip":
            self._grip_down = False
            self.grip_double_clicked.emit()
            return
        self.mousePressEvent(e)

    def event(self, e):
        if e.type() == QtCore.QEvent.ToolTip:
            hit = self._hit(QtCore.QPointF(e.pos()))
            if hit == "more":
                extra = TABS[self.current][1] if self.current in self.more_tabs() else ""
                QtWidgets.QToolTip.showText(e.globalPos(), "More managers" + (" (showing: %s)" % extra if extra else ""), self)
            elif isinstance(hit, int):
                QtWidgets.QToolTip.showText(e.globalPos(), TABS[hit][1], self)
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return super().event(e)

    def filter_shown(self):
        ""
        if not (0 <= self.current < len(TABS) and TABS[self.current][2] == "Model"):
            return False
        try:        # Options > FeatureManager > Enable FeatureManager tree filter (Features thread, pkg273)
            from . import optionspages
            return bool(optionspages._tree_filter_on())
        except Exception:
            return True

    def _fit(self):
        on = self.filter_shown()
        h = scaled(self.FULL_H if on else self.SHORT_H, self.k)
        if self.height() != h:
            self.setFixedHeight(h)
        if self.filter.isHidden() == on:
            self.filter.setVisible(on)

    def set_current(self, index):
        self.current = index
        self._fit()
        self.update()

    # paint -------------------------------------------------------------------------
    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        dpr = self.devicePixelRatioF()
        W = dev(self.width(), dpr)
        sw = dpr * self.k
        p.save()
        p.scale(1.0 / dpr, 1.0 / dpr)
        p.fillRect(0, 0, W, dev(self.FULL_H, sw), T.pane)
        one = 1
        p.fillRect(0, dev(2, sw), W, one, T.line_light)            # grip row top
        p.fillRect(0, dev(17, sw), W, one, T.line_light)           # grip row bottom
        cx, cy = W / 2.0, dev(9.5, sw)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setPen(QtGui.QPen(T.grip_line, 1))
        p.setBrush(T.grip_fill)
        p.drawEllipse(QtCore.QPointF(cx, cy), 3.5 * self.k, 3.5 * self.k)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        top = dev(self.TAB_TOP, sw)                              # tab top line row
        bottom = dev(self.TAB_TOP + self.TAB_H, sw)              # tab bottom line row
        slots = self.visible_slots()
        more = self.more_rect()
        on_more = self.current in self.more_tabs()
        # (key, rect, current, hovered): the managers, then "..."
        cells = [(i, r, i == self.current, i == self.hover) for i, r in slots]
        if more is not None:
            cells.append(("more", more, on_more, self.hover == "more"))
        for _key, r, cur, hov in cells:
            x0, x1 = dev(r.left(), dpr), dev(r.right(), dpr)
            if cur:
                p.fillRect(x0, top + 1, x1 - x0, bottom - top, T.pane)
            else:
                p.fillRect(x0, top + 1, x1 - x0, bottom - top - 1, T.tab_hover if hov else T.tab)
        for n_, (_key, r, cur, _hov) in enumerate(cells):   # the lines after all the fills: a fill can cover the line before it
            x0, x1 = dev(r.left(), dpr), dev(r.right(), dpr)
            if not cur:
                p.fillRect(x0, bottom, x1 - x0 + 1, 1, T.line)
            p.fillRect(x0, top, x1 - x0 + 1, 1, T.line)
            if n_ == 0:
                p.fillRect(x0, top, 1, bottom - top + 1, T.line)
            p.fillRect(x1, top, 1, bottom - top + 1, T.line)
        # filter box (FeatureManager only)
        if self.filter_shown():
            fx0, fy0 = dev(2.5, sw), dev(self.TAB_TOP + self.TAB_H, sw)
            fx1, fy1 = W - dev(3, sw), dev(self.FULL_H - 0.5, sw)
            p.fillRect(fx0, fy0, fx1 - fx0, 1, T.line_light)
            p.fillRect(fx0, fy1, fx1 - fx0, 1, T.line_light)
            p.fillRect(fx0, fy0, 1, fy1 - fy0, T.line_light)
            p.fillRect(fx1, fy0, 1, fy1 - fy0 + 1, T.line_light)
        p.restore()
        # icons (logical coordinates)
        k = self.k
        n = scaled(20, k)
        for i, r in slots:
            icon = self.icons[i]
            rect = QtCore.QRect(int(r.center().x() - n / 2.0), int(r.center().y() - n / 2.0), n, n)
            p.save()
            p.setClipRect(r.toRect())
            if not icon.isNull():
                style.paint_icon(p, icon, rect)
            p.restore()
        if more is not None:
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            p.setPen(Qt.NoPen)
            p.setBrush(T.text)
            c = more.center()
            for j in (-1, 0, 1):
                p.drawEllipse(QtCore.QPointF(c.x() + j * 6.0 * k, c.y()), 1.6 * k, 1.6 * k)
        if not self.filter_icon.isNull() and self.filter_shown():
            style.paint_icon(p, self.filter_icon, QtCore.QRect(scaled(4, k), scaled(self.TAB_TOP + self.TAB_H + 2, k), n, n))
        p.end()


def _dialog_open():
    try:
        return bool(Gui.Control.activeDialog())
    except Exception as _fw_err:
        _fw_log("leftpane.py:434", _fw_err)
        return False


class PageStack(QtWidgets.QStackedWidget):
    """The pane's pages, sized by the page on show only.

    A plain QStackedWidget asks for the room of its largest page, hidden ones
    too. FreeCAD sets the Tasks panel's minimum width for each dialog and the
    hidden panel kept the width of the last one, so every feature edit left the
    pane wider than before, for good."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    @staticmethod
    def autosize():
        """Options > General > Auto-size PropertyManager when panels are split: the pane follows each
        PropertyManager's own size; off, the pane keeps the room it has (the minimum is asked for)."""
        try:
            from . import optionspages
            return bool(optionspages.stored("General", "Auto-size PropertyManager when panels are split", True))
        except Exception:
            return True

    def _hint(self, minimum):
        page = self.currentWidget()
        if page is None:
            return QtCore.QSize(0, 0)
        if not minimum and not self.autosize():
            minimum = True
        hint = page.minimumSizeHint() if minimum else page.sizeHint()
        floor = page.minimumSize()     # an explicit minimum wins, as in Qt's layouts
        w = floor.width() if floor.width() > 0 else hint.width()
        h = floor.height() if floor.height() > 0 else hint.height()
        if not minimum:
            w, h = max(w, floor.width()), max(h, floor.height())
        m = self.contentsMargins()
        return QtCore.QSize(max(0, w) + m.left() + m.right(), max(0, h) + m.top() + m.bottom())

    def minimumSizeHint(self):
        return self._hint(True)

    def sizeHint(self):
        return self._hint(False)


class _DragWatch(QtCore.QObject):
    """Notes a resize of the pane made with a mouse button down (the user dragging its edge)."""

    def __init__(self, pane, dock):
        super().__init__(dock)
        self.pane = pane
        dock.installEventFilter(self)

    def eventFilter(self, obj, event):
        try:
            if event.type() == QtCore.QEvent.Resize and QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton:
                if getattr(self.pane, "_base_width", None):
                    self.pane._user_dragged = True
        except Exception:
            pass
        return False


class LeftPane(QtWidgets.QWidget):
    """Owns the moved FreeCAD panels while the style is on."""

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.setObjectName("SWLeftPane")
        self.shell = shell
        self.window = shell.window
        self.header = PaneHeader(self)
        self.stack = PageStack(self)
        self.stack.setObjectName("SWLeftStack")

        # row down adds a lower half with its own manager tabs, double-clicking its grip row removes it
        self.splitter = QtWidgets.QSplitter(Qt.Vertical, self)
        self.splitter.setObjectName("SWPaneSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)
        self.upper = QtWidgets.QWidget(self.splitter)
        self.upper.setObjectName("SWPaneUpper")
        upper = QtWidgets.QVBoxLayout(self.upper)
        upper.setContentsMargins(0, 0, 0, 0)
        upper.setSpacing(0)
        upper.addWidget(self.header)
        upper.addWidget(self.stack, 1)
        self.splitter.addWidget(self.upper)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter, 1)
        self.header.tab_clicked.connect(self.select)
        self.header.filter.textChanged.connect(self._filter_tree)
        self.header.grip_pressed.connect(lambda y: self._grip_press("upper", y))
        self.header.grip_dragged.connect(self._grip_drag)
        self.header.grip_released.connect(self._grip_release)
        self.header.grip_double_clicked.connect(self._grip_double)
        self.lower = self.lower_header = self.lower_stack = None
        self.lower_name = None
        self._drag = None
        self.pages = {}            # page id -> widget in stack
        self.moved = []            # restore records
        self._user_page = "Model"
        self._switching = False
        self._filtered = []
        self._base_width = None    # pane width before a dialog widened it
        self._forced = 0           # widest minimum the dialog asked for

    # ------------------------------------------------------------------ adopt/release
    def adopt(self):
        """Move FreeCAD's panels into the pane. Returns the list of adopted names."""
        mw = self.window
        adopted = []
        for icon, tip, name in TABS:
            if name in OWN_PAGES:

                try:
                    import importlib
                    module, cls = OWN_PAGES[name]
                    page = getattr(importlib.import_module("." + module, __package__), cls)()
                    self._add_page(name, page)
                    self.moved.append({"kind": "own", "name": name, "widget": page})
                    adopted.append(name)
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: %s page: %s\n" % (name, error))
                continue
            if name == "PropertyView":
                widget = self._take_property_view()
                if widget is not None:
                    self._add_page(name, widget)
                    adopted.append(name)
                continue
            dock = mw.findChild(QtWidgets.QDockWidget, name)
            # Panels in FreeCAD's overlay mode belong to the overlay tabs; leave them there.
            if dock is None or dock.parentWidget() is not mw:
                continue
            record = {
                "kind": "dock", "name": name, "dock": dock,
                "visible": dock.isVisible(), "floating": dock.isFloating(),
                "area": mw.dockWidgetArea(dock), "title_bar": dock.titleBarWidget(),
                "features": dock.features(), "min_width": dock.minimumWidth(),
            }
            mw.removeDockWidget(dock)
            dock.setFloating(False)
            dock.setTitleBarWidget(_blank_title(dock))
            dock.setParent(None)
            self._add_page(name, dock)
            dock.installEventFilter(self)
            dock.featuresChanged.connect(self._refresh_title_bars)
            self.moved.append(record)
            adopted.append(name)
        self.select_name("Model")
        return adopted

    def _take_property_view(self):
        combo_dock = self.pages.get("Model") or self.window.findChild(QtWidgets.QDockWidget, "Model")
        if combo_dock is None or combo_dock.widget() is None:
            return None
        splitter = None
        for s in combo_dock.widget().findChildren(QtWidgets.QSplitter):
            if s.count() >= 2:
                splitter = s
                break
        if splitter is None:
            return None
        widget = None
        for i in range(splitter.count()):
            w = splitter.widget(i)
            if w.metaObject().className() in ("Gui::PropertyView",) or "PropertyView" in w.metaObject().className():
                widget = w
                index = i
                break
        if widget is None:
            return None
        self.moved.append({"kind": "property", "widget": widget, "splitter": splitter,
                           "index": index, "sizes": splitter.sizes(), "visible": widget.isVisible()})
        widget.setParent(None)
        widget.show()
        return widget

    def _add_page(self, name, widget):
        self.pages[name] = widget
        self.stack.addWidget(widget)

    def release(self):
        """Give every panel back to the main window exactly where it was."""
        mw = self.window
        self.unsplit()
        self.header.filter.clear()
        self._base_width, self._forced = None, 0
        for record in reversed(self.moved):
            try:
                if record["kind"] == "own":
                    w = record["widget"]
                    if alive(w):
                        self.stack.removeWidget(w)
                        w.deleteLater()
                    continue
                if record["kind"] == "property":
                    w = record["widget"]
                    if not alive(w) or not alive(record["splitter"]):
                        continue
                    self.stack.removeWidget(w)
                    record["splitter"].insertWidget(record["index"], w)
                    record["splitter"].setSizes(record["sizes"])
                    w.setVisible(True)
                    continue
                dock = record["dock"]
                if not alive(dock):
                    continue
                dock.removeEventFilter(self)
                try:
                    dock.featuresChanged.disconnect(self._refresh_title_bars)
                except Exception as _fw_err:
                    _fw_log("leftpane.py:627", _fw_err)
                self.stack.removeWidget(dock)
                dock.setParent(mw)
                current = dock.titleBarWidget()
                original = record["title_bar"]
                dock.setTitleBarWidget(original if alive(original) else None)
                if alive(current) and current.objectName() == BLANK_TITLE:
                    current.deleteLater()
                if not alive(original):
                    # A features change makes FreeCAD build its own title bar again.
                    features = dock.features()
                    dock.setFeatures(features ^ QtWidgets.QDockWidget.DockWidgetFloatable)
                    dock.setFeatures(features)
                area = record["area"]
                if area == Qt.NoDockWidgetArea:
                    area = Qt.LeftDockWidgetArea
                mw.addDockWidget(area, dock)
                dock.setFloating(record["floating"])
                dock.setVisible(record["visible"])
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: could not return %s: %s\n"
                                         % (record.get("name", "property view"), error))
        self.moved = []
        self.pages = {}

    # ------------------------------------------------------------------ paging
    def select(self, index):
        name = TABS[index][2]
        self._user_page = name
        self.select_name(name, swap=True)

    def select_name(self, name, swap=False):
        widget = self.pages.get(name)
        if widget is None:
            return
        if self.lower is not None and name == self.lower_name:
            if not swap:
                return              # already on show in the lower half (a PropertyManager put there stays there)
            # a click on the upper tab of the lower half's manager: the two halves trade pages
            self._lower_show(self.current_name() or self._spare(name))
            widget = self.pages.get(name)
            if widget is None or self.current_name() == name:
                return
        before = self.current_name()
        if name == "Tasks" and before != "Tasks" and self._base_width is None:
            dock = self._dock()
            if dock is not None:
                self._base_width = dock.width()
                self._forced = 0
                self._user_dragged = False
        elif before == "Tasks" and name != "Tasks":
            self._sample_width()
        focus = QtWidgets.QApplication.focusWidget()
        self._switching = True
        try:
            self.stack.setCurrentWidget(widget)
            if not widget.isVisible():
                widget.show()
            lower = self.pages.get(self.lower_name) if self.lower is not None else None
            for page in self.pages.values():
                if page is not widget and page is not lower and alive(page) and page.isVisible():
                    page.hide()
        finally:
            self._switching = False
        for i, tab in enumerate(TABS):
            if tab[2] == name:
                self.header.set_current(i)
        self._refresh_title_bars()
        # Hiding the page that had the keyboard focus lets Qt hand it to some
        # widget in the new page, and then Escape no longer reaches a running
        # sketch tool. Give it back to the 3D view instead.
        if focus is not None and alive(focus) and not focus.isVisible():
            view = self.shell.view_widget()
            if view is not None:
                view.setFocus(Qt.OtherFocusReason)

    def current_name(self):
        w = self.stack.currentWidget()
        for name, page in self.pages.items():
            if page is w:
                return name
        return None

    def restore_user_page(self):
        if self.shell.tasks_wanted():
            self.select_name("Tasks")
        else:
            self.select_name(self._user_page if self._user_page != "Tasks" else "Model")

    def dialog_closed(self):
        if self.current_name() == "Tasks":
            self.select_name("Model" if self._user_page == "Tasks" else self._user_page)

    # ------------------------------------------------------------------ split pane
    def is_split(self):
        return self.lower is not None

    def _spare(self, *taken):
        """A page for a half that has to give its page up."""
        for name in ("Model", "ConfigurationManager", "PropertyView", "DisplayManager", "Report view"):
            if name in self.pages and name not in taken:
                return name
        for name in self.pages:
            if name not in taken:
                return name
        return None

    def split(self, at=None):
        """Split the pane: a lower half with its own manager tabs, its top edge at `at` (pane y)."""
        if self.lower is not None:
            return
        self.lower = QtWidgets.QWidget(self.splitter)
        self.lower.setObjectName("SWPaneLower")
        box = QtWidgets.QVBoxLayout(self.lower)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.lower_header = PaneHeader(self.lower)
        self.lower_header.setObjectName("SWPaneSplitBar")
        self.lower_header.filter.setObjectName("SWTreeFilterLower")
        self.lower_stack = PageStack(self.lower)
        self.lower_stack.setObjectName("SWLeftStackLower")
        box.addWidget(self.lower_header)
        box.addWidget(self.lower_stack, 1)
        self.splitter.addWidget(self.lower)
        self.lower_header.tab_clicked.connect(lambda i: self._lower_show(TABS[i][2]))
        self.lower_header.filter.textChanged.connect(self._filter_tree)
        self.lower_header.grip_pressed.connect(lambda y: self._grip_press("lower", y))
        self.lower_header.grip_dragged.connect(self._grip_drag)
        self.lower_header.grip_released.connect(self._grip_release)
        self.lower_header.grip_double_clicked.connect(self.unsplit)
        top = self.current_name()
        first = next((n for n in ("ConfigurationManager", "PropertyView", "DisplayManager", "Model")
                      if n in self.pages and n != top), None) or self._spare(top)
        self.lower.show()
        if first is not None:
            self._lower_show(first)
        total = max(1, self.splitter.height())
        at = total // 2 if at is None else int(at)
        floor = self.header.height() + scaled(20, self.header.k)
        at = max(floor, min(total - self.lower_header.height(), at))
        self.splitter.setSizes([at, max(1, total - at)])

    def unsplit(self):
        """Back to one pane; the lower half's page goes back behind its tab in the upper half."""
        if self.lower is None:
            return
        self._drag = None
        name = self.lower_name
        self._return_lower()
        lower, self.lower = self.lower, None
        self.lower_header = self.lower_stack = None
        lower.hide()
        lower.setParent(None)
        lower.deleteLater()
        if name == "Tasks" and _dialog_open():
            self.select_name("Tasks")

    def _return_lower(self):
        name, self.lower_name = self.lower_name, None
        w = self.pages.get(name) if name else None
        if w is None or not alive(w):
            return
        self._switching = True
        try:
            self.lower_stack.removeWidget(w)
            self.stack.addWidget(w)
            if w is not self.stack.currentWidget():
                w.hide()
        finally:
            self._switching = False

    def _lower_show(self, name):
        if self.lower is None or name not in self.pages or name == self.lower_name:
            return
        old = self.lower_name
        self._return_lower()
        if self.current_name() == name:
            self.select_name(old if old and old != name else self._spare(name))
        w = self.pages[name]
        self._switching = True
        try:
            self.stack.removeWidget(w)
            self.lower_stack.addWidget(w)
            self.lower_stack.setCurrentWidget(w)
            w.show()
        finally:
            self._switching = False
        self.lower_name = name
        for i, tab in enumerate(TABS):
            if tab[2] == name:
                self.lower_header.set_current(i)
        self._refresh_title_bars()

    def _grip_press(self, which, gy):
        self._drag = (which, gy, self.lower.mapToGlobal(QtCore.QPoint(0, 0)).y() - gy
                      if which == "lower" and self.lower is not None else 0)

    def _grip_drag(self, gy):
        if self._drag is None:
            return
        which, start, offset = self._drag
        if which == "upper" and self.lower is None:
            if gy - start < scaled(12, self.header.k):
                return
            self.split(self.splitter.mapFromGlobal(QtCore.QPoint(0, gy)).y())
            self._drag = ("lower", start, 0)
            return
        if which == "lower" and self.lower is not None:
            y = self.splitter.mapFromGlobal(QtCore.QPoint(0, gy + offset)).y()
            total = self.splitter.height()
            floor = self.header.height() + scaled(20, self.header.k)
            y = max(floor, min(total - self.lower_header.height(), y))
            self.splitter.setSizes([y, max(1, total - y)])

    def _grip_release(self, gy):
        self._drag = None

    def _grip_double(self):
        # the upper grip row: unsplits a split pane, splits a whole one in half
        if self.lower is not None:
            self.unsplit()
        else:
            self.split()

    # ------------------------------------------------------------------ width

    # tree and the PropertyManager alike. It starts at PANE_WIDTH, which fits
    # FreeCAD's feature dialogs. A dialog that needs more room still widens it
    # (its fields would be cut off otherwise); once it closes the pane goes back
    # to the user's width (Qt had widened it, not the user), unless the user
    # dragged the pane meanwhile: then the dragged width stays (land258; before,
    # every PropertyManager open left the pane ~10 px wider).
    def _dock(self):
        dock = getattr(self.shell, "left_dock", None)
        return dock if dock is not None and alive(dock) else None

    def _sample_width(self):
        dock = self._dock()
        if dock is not None and self._base_width is not None:
            self._forced = max(self._forced, dock.minimumSizeHint().width())

    def settle_width(self):
        """Runs on the shell's watch timer."""
        if self._base_width is None:
            return
        if self.current_name() == "Tasks":
            self._fit_tasks()
            self._sample_width()
            return
        if _dialog_open():
            return
        self._fitted = False
        if not self._restore_width() and getattr(self, "_retries", 0) < 10:
            self._retries = getattr(self, "_retries", 0) + 1
            return                  # Qt kept the pane wide (a closing page still held it): try again next tick
        self._base_width, self._forced, self._retries = None, 0, 0
        self._user_dragged = False

    def _fit_tasks(self):
        ""




        dock = self._dock()
        page = self.pages.get("Tasks")
        if dock is None or page is None or not alive(page):
            return
        view = getattr(self, "_task_view", None)
        if view is None or not alive(view) or not (view is page or page.isAncestorOf(view)):
            views = [page] + page.findChildren(QtWidgets.QWidget, "Tasks")
            views = [w for w in views if w.metaObject().className().endswith("TaskView")]
            view = views[0] if views else None
            self._task_view = view
        if view is None or not alive(view):
            return
        need = view.minimumSizeHint().width()
        if view.minimumWidth() != need:
            if view.minimumWidth() > need:
                self._fitted = True
            view.setMinimumWidth(need)
        if getattr(self, "_fitted", False) and self._base_width and dock.width() > self._base_width:
            self._shrink_to_need()
        elif self._base_width and dock.width() > self._base_width and not self._dragged(dock) \
                and dock.minimumSizeHint().width() < dock.width() - 4:
            # Qt widened the pane for the page's first layout (FloXpress 371 px) and the page has since got
            # narrower (long notes wrapped): back to what it needs; a pane the user dragged wider stays
            self._shrink_to_need()

    def _shrink_to_need(self):
        dock = self._dock()
        if dock is None or not self._base_width:
            return
        target = max(self._base_width, dock.minimumSizeHint().width())
        if dock.width() > target:
            try:
                self.window.resizeDocks([dock], [target], QtCore.Qt.Horizontal)
            except Exception:
                return
        # the width Qt left the pane at: a shrink Qt has not carried out yet must not look like the user's drag
        # later (the pane then stayed wide for every page after; look audit AO1)
        self._forced = max(dock.minimumSizeHint().width(), dock.width())

    def _dragged(self, dock):
        """True once the user has dragged the pane's edge since a page widened it: a resize of the pane while
        a mouse button is down. Qt's own widening and shrinking (a page's first layout, notes wrapping) is
        not a drag; before, a width that differed from the last sampled minimum counted as one, and the pane
        stayed wide for every later page (Tooling Split 328 px after Advanced Hole; look audit AO1)."""
        if not getattr(self, "_drag_watch", None) or getattr(self, "_drag_dock", None) is not dock:
            self._drag_dock = dock
            self._drag_watch = _DragWatch(self, dock)
        return bool(getattr(self, "_user_dragged", False))

    def _free_task_view(self):
        """Look audit AO1: FreeCAD's TaskView kept the minimum width of a wide page (Geometry Analysis, 472 px)
        after it closed, and the page stack is as wide as its widest page, so the pane could not go back and
        every later page opened at 472. Once the Tasks page is not on show its minimum is let go."""
        if self.current_name() == "Tasks":
            return
        view = getattr(self, "_task_view", None)
        if view is None or not alive(view):
            page = self.pages.get("Tasks")
            if page is None or not alive(page):
                return
            views = [w for w in [page] + page.findChildren(QtWidgets.QWidget) if w.metaObject().className().endswith("TaskView")]
            view = views[0] if views else None
        if view is not None and view.minimumWidth() > 0:
            view.setMinimumWidth(0)

    def _restore_width(self):
        dock = self._dock()
        if dock is None or not self._base_width:
            return True
        width = dock.width()
        if width <= self._base_width:
            return True
        dragged = self._dragged(dock)
        if dragged:
            return True
        self._free_task_view()
        try:
            self.window.resizeDocks([dock], [self._base_width], QtCore.Qt.Horizontal)
            self.restored = getattr(self, "restored", 0) + 1
        except Exception:
            return True
        return dock.width() <= self._base_width

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if self.lower is not None and obj is self.pages.get(self.lower_name):
            return False        # the lower half's page: its showing and hiding are its own
        if t == QtCore.QEvent.Show and not self._switching:
            if obj is not self.stack.currentWidget():
                QtCore.QTimer.singleShot(0, lambda o=obj: self._shown(o))
        elif t == QtCore.QEvent.Hide and not self._switching:
            if obj is self.stack.currentWidget():
                QtCore.QTimer.singleShot(0, self._current_hidden)
        return False

    def _shown(self, obj):
        if not alive(obj):
            return
        for name, page in self.pages.items():
            if page is obj and obj.isVisible():
                if name == "Tasks" and (not self.shell.tasks_wanted() or not self.shell._auto_show_pm()):
                    # FreeCAD shows the Tasks panel for every dialog; while a

                    self._switching = True
                    try:
                        obj.hide()
                    finally:
                        self._switching = False
                    return
                self.select_name(name)
                return

    def _current_hidden(self):
        w = self.stack.currentWidget()
        if w is not None and not w.isVisible():
            self.select_name("Model")

    def _refresh_title_bars(self, *args):
        """Keep the panels' title bars hidden. FreeCAD builds a new title bar each
        time a panel's features change, which every task dialog does when it
        opens and closes, and deletes the bar it replaces, ours included."""
        for record in self.moved:
            if record["kind"] != "dock":
                continue
            dock = record["dock"]
            if not alive(dock):
                continue
            current = dock.titleBarWidget()
            if alive(current) and current.objectName() == BLANK_TITLE:
                continue
            dock.setTitleBarWidget(_blank_title(dock))
            if alive(current) and current is not record["title_bar"]:
                current.hide()
                current.deleteLater()

    # ------------------------------------------------------------------ tree filter
    def tree_widget(self):
        page = self.pages.get("Model")
        if page is None:
            return None
        for tree in page.findChildren(QtWidgets.QTreeWidget):
            return tree
        return None

    def _filter_tree(self, text):

        from . import fmtree
        page = self.pages.get("Model")
        overlays = [t for t in (page.findChildren(fmtree.FeatureTree) if page is not None else [])
                    if t.isVisible()] or [t for t in Gui.getMainWindow().findChildren(fmtree.FeatureTree)
                                          if t.isVisible()]
        for overlay in overlays:
            overlay.fm_filter(text)
        if overlays:
            text = ""       # FreeCAD's own tree under it stays whole (the overlay's rows come from it)
        tree = self.tree_widget()
        if tree is None:
            return
        for item in self._filtered:
            try:
                item.setHidden(False)
            except RuntimeError as _fw_err:
                _fw_log("leftpane.py:1019", _fw_err)
        self._filtered = []
        text = text.strip().lower()
        if not text:
            return

        def visit(item):
            match = text in item.text(0).lower()
            child_match = False
            for i in range(item.childCount()):
                if visit(item.child(i)):
                    child_match = True
            keep = match or child_match
            if not keep and not item.isHidden():
                item.setHidden(True)
                self._filtered.append(item)
            elif child_match:
                item.setExpanded(True)
            return keep

        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            for j in range(top.childCount()):
                visit(top.child(j))
