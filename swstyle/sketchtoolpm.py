# SPDX-License-Identifier: LGPL-2.1-or-later
"""PropertyManager pages for the look's own sketch commands (Fully Define Sketch,
Scan Equal...).

A page sits in the left pane like the relations panel: the command's icon and
name, the green check and red cross, then its groups. While it is open the
relations panel stays away and Esc in the 3D view is the red cross. Each
page's work is one entry in the sketch's history: the check keeps it, the
cross takes it back. Leaving the sketch with a page open keeps what the page
did so far (FreeCAD closes its edit session there) and closes the page.
"""

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

from . import contextbar, relationspm
from .widgets import alive, ui_font
from . import geomkeep

Qt = QtCore.Qt
PAGE = "SketchTool"

_host = None

# sketchtiles-1121 (desktop recording 2026-10-25): the picture buttons (Rectangle Type, Slot Type...) are framed
# tiles; the pressed one is filled
_TOGGLE_QSS = """
QWidget#SWRelationsPM QToolButton[swToggle="true"] { border: 1px solid %s; }
QWidget#SWRelationsPM QToolButton[swToggle="true"]:checked { background: %s; border: 1px solid %s; }
QWidget#SWRelationsPM QToolButton[swToggle="true"]:disabled { border: 1px solid transparent; }
"""


def _shell():
    try:
        from . import shell as shell_module
        return shell_module.shell()
    except Exception as _fw_err:
        _fw_log("sketchtoolpm.py:49", _fw_err)
        return None


def current():
    """The open page, else None."""
    return _host.page if _host is not None else None


def _draw_cross(p):
    p.setPen(QtGui.QPen(QtGui.QColor("#d03a3a"), 2.2, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QtCore.QPointF(4, 4), QtCore.QPointF(12, 12))
    p.drawLine(QtCore.QPointF(12, 4), QtCore.QPointF(4, 12))




MESSAGE_QSS = ("QWidget#SWToolMessage { background: #fafd88; margin: 0px 3px 2px 3px; }"
               " QWidget#SWToolMessage QLabel { color: #000000; background: transparent; }")


def _message_box(group):
    try:
        group.body.setObjectName("SWToolMessage")
        group.body.setAttribute(Qt.WA_StyledBackground, True)
        group.body.setStyleSheet(MESSAGE_QSS)
        group.content.setContentsMargins(6, 4, 6, 5)
    except Exception as _fw_err:
        _fw_log("sketchtoolpm.py:message", _fw_err)


# toolglyph-1121: a running tool's Parameters read as the picked entity's (and the 2025 video's): the
# measured thing drawn in the field column and a white field, the label kept as the tooltip
_PARAM_GLYPHS = {"Center X": "cx", "Center Y": "cy", "Radius": "radius", "Radius 1": "radius",
                 "Radius 2": "radius", "Diameter": "diameter", "Angle": "angle", "Arc angle": "sweep",
                 "X": "x", "Y": "y", "Start X": "x1", "Start Y": "y1", "End X": "x2", "End Y": "y2",
                 "Length": "length", "Width": "width", "Sides": "sides", "ΔX": "dx", "ΔY": "dy",
                 "Arc Angle": "sweep",
                 "Point 1 X": "x", "Point 1 Y": "y", "Point 2 X": "x", "Point 2 Y": "y",
                 "Point 3 X": "x", "Point 3 Y": "y", "Point 4 X": "x", "Point 4 Y": "y"}


def _param_rows(page):
    """(label, field) pairs of the page's rows: a QLabel right before its field in a row layout."""
    pairs = []
    for layout in page.findChildren(QtWidgets.QHBoxLayout):
        items = [layout.itemAt(i) for i in range(layout.count())]
        for i, item in enumerate(items[:-1]):
            w, nxt = item.widget(), items[i + 1].widget()
            if isinstance(w, QtWidgets.QLabel) and isinstance(nxt, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)):
                pairs.append((w, nxt))
    return pairs


def _form_rows(page):
    """movepm-1121: the same pairs in form layouts (Move's ΔX/ΔY, Rotate's centre and angle)."""
    pairs = []
    for form in page.findChildren(QtWidgets.QFormLayout):
        for i in range(form.rowCount()):
            label = form.itemAt(i, QtWidgets.QFormLayout.LabelRole)
            field = form.itemAt(i, QtWidgets.QFormLayout.FieldRole)
            label = label.widget() if label is not None else None
            field = field.widget() if field is not None else None
            if isinstance(label, QtWidgets.QLabel) and isinstance(field, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)):
                pairs.append((label, field))
    return pairs


def _param_glyphs(page):
    for label, field in _param_rows(page) + _form_rows(page):
        key = _PARAM_GLYPHS.get(label.text().replace("&", "").rstrip(":"))
        if key is None or label.pixmap() is not None and not label.pixmap().isNull():
            continue
        text = label.text().replace("&", "").rstrip(":")
        label.setText("")
        label.setPixmap(relationspm._parameter_icon(key).pixmap(16, 16))
        label.setFixedSize(20, 20)
        label.setAlignment(Qt.AlignCenter)
        label.setToolTip(text)
        label.setProperty("fw_param_glyph", key)
        if not field.toolTip():
            field.setToolTip(text)
        if isinstance(field, QtWidgets.QLineEdit):
            field.setProperty("swParamField", True)
            field.style().unpolish(field)
            field.style().polish(field)


class ToolPage(QtWidgets.QWidget):
    """A PropertyManager page. Subclasses build their groups in build() and do their work in
    calculate(); the history entry is opened by begin() and closed by the check or the cross."""

    TITLE = "Sketch Tool"
    ICON = None             # icon family, else a FreeCAD pixmap name in PIXMAP
    PIXMAP = None
    TRANSACTION = None      # history entry name; TITLE when None

    def __init__(self, sketch, parent=None):
        super().__init__(parent)
        self.sketch = sketch
        self.doc = sketch.Document
        self._open = False
        self.setObjectName("SWRelationsPM")     # the relations panel's style sheet
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFont(ui_font())
        self.setStyleSheet(relationspm._qss() + relationspm._checkbox_qss() + _TOGGLE_QSS % (
            relationspm._tok("line_mid", "#a9a9a9").name(),
            relationspm._tok("down", "#cce4f7").name(), relationspm._tok("accent", "#5a9bd5").name()))
        if not relationspm._dark():
            try:
                from . import propertymanager
                self.setPalette(propertymanager._light_palette(QtWidgets.QApplication.palette()))
            except Exception as _fw_err:
                _fw_log("sketchtoolpm.py:86", _fw_err)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll)
        self.body = QtWidgets.QWidget()
        self.body.setObjectName("SWRelationsBody")
        scroll.setWidget(self.body)
        self.column = QtWidgets.QVBoxLayout(self.body)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(0)
        self._build_header()
        self.note = QtWidgets.QLabel("", self.body)
        self.note.setObjectName("SWToolInfo")
        self.note.setWordWrap(True)
        self.note.setContentsMargins(10, 0, 8, 6)
        self.note.hide()
        self.column.addWidget(self.note)
        self.build()
        try:
            _param_glyphs(self)             # toolglyph-1121
        except Exception as _fw_err:
            _fw_log("sketchtoolpm.py:param_glyphs", _fw_err)
        self.column.addStretch(1)

    # ------------------------------------------------------------------ build
    OK_ONLY = False

    def _build_header(self):
        header = QtWidgets.QWidget(self.body)
        header.setObjectName("SWStyle_PMHeader")
        outer = QtWidgets.QVBoxLayout(header)
        outer.setContentsMargins(8, 8, 8, 6)
        outer.setSpacing(6)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        icon = QtWidgets.QLabel(header)
        icon.setFixedSize(20, 20)
        pix = self.title_icon()
        if pix is not None and not pix.isNull():
            icon.setPixmap(pix.pixmap(16, 16))
        self.title = QtWidgets.QLabel(self.TITLE, header)
        self.title.setObjectName("SWStyle_PMTitle")
        self.title.setWordWrap(True)
        top.addWidget(icon, 0, Qt.AlignTop)
        top.addWidget(self.title, 1)

        self.help = QtWidgets.QToolButton(header)
        self.help.setObjectName("SWToolHelp")
        self.help.setAutoRaise(True)
        self.help.setIconSize(QtCore.QSize(20, 20))
        self.help.setToolTip("Help")
        self.help.setFocusPolicy(Qt.NoFocus)
        try:
            from . import icons, propertymanager
            help_icon = icons.family("PM_HELP")
            if help_icon.isNull():
                help_icon = propertymanager._drawn("PM_HELP")
            if help_icon.isNull():
                self.help.setText("?")
            else:
                self.help.setIcon(help_icon)
        except Exception:
            self.help.setText("?")
        self.help.clicked.connect(self.show_help)
        top.addWidget(self.help, 0, Qt.AlignTop)
        outer.addLayout(top)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(2)
        try:
            from . import propertymanager
            green = propertymanager.OK_GREEN
        except Exception:
            green = "#74a257"
        self.ok = self._header_button(header, "OK", relationspm._pack_or("CHECK_MARK", relationspm._draw_check, green))
        self.cancel = self._header_button(header, "Cancel", relationspm._icon(_draw_cross))
        self.ok.setObjectName("SWToolOK")
        self.cancel.setObjectName("SWToolCancel")
        self.ok.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)
        row.addWidget(self.ok)
        row.addWidget(self.cancel)
        row.addStretch(1)
        outer.addLayout(row)
        self.column.addWidget(header)
        if self.OK_ONLY:
            self.cancel.hide()

    def show_help(self):
        ""
        title = self.title.text() or self.TITLE
        try:
            from . import pmhelp
            if title not in pmhelp.HELP and title in getattr(relationspm, "SKETCH_HELP", {}):
                pmhelp.HELP[title] = relationspm.SKETCH_HELP[title]
            return pmhelp.show(self, title)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: no help for %s (%s)\n" % (title, error))
            return None

    def _header_button(self, parent, tip, icon):
        b = QtWidgets.QToolButton(parent)
        b.setAutoRaise(True)
        b.setIconSize(QtCore.QSize(16, 16))
        b.setFixedSize(24, 22)
        b.setToolTip(tip)
        b.setFocusPolicy(Qt.NoFocus)
        b.setIcon(icon)
        return b

    def title_icon(self):
        try:
            from . import icons
            if self.ICON:
                icon = icons.family(self.ICON)
                if not icon.isNull():
                    return icon
            own = _button_picture(self.TITLE)
            if own is not None:
                return own          # no icon pack: the drawn picture its Sketch tab button shows (fix242)
            if self.PIXMAP:
                return Gui.getIcon(pixmap_of(self.PIXMAP))
        except Exception as _fw_err:
            _fw_log("sketchtoolpm.py:169", _fw_err)
        return None

    def group(self, title):
        g = relationspm.Group(title, self.body)
        if title == "Message":
            _message_box(g)
        self.column.addWidget(g)
        return g

    def build(self):
        pass

    def show_note(self, text, warning=False):
        """A line under the title: what the page did (plain) or why it could not (red)."""
        self.note.setObjectName("SWRelationsNote" if warning else "SWToolInfo")
        self.note.style().unpolish(self.note)
        self.note.style().polish(self.note)
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def toggles(self, group, keys, icon, checked, per_row=5, rows=None, big=False):
        ""


        grid = QtWidgets.QGridLayout()
        grid.setSpacing(6 if big else 2)
        out = {}
        places = []
        if rows:
            for r, n in enumerate(rows):
                places += [(r, c) for c in range(n)]
            per_row = max(rows)
        for i, key in enumerate(keys):
            b = QtWidgets.QToolButton(group.body)
            b.setCheckable(True)
            b.setChecked(checked(key))
            b.setIcon(icon(key))
            if big:
                b.setIconSize(QtCore.QSize(32, 32))
                b.setFixedSize(46, 46)
            else:
                b.setIconSize(QtCore.QSize(16, 16))
                b.setFixedSize(26, 24)
            b.setToolTip(key)
            b.setObjectName("SWToggle" + key)
            b.setProperty("swToggle", True)
            out[key] = b
            r, c = places[i] if i < len(places) else (i // per_row, i % per_row)
            grid.addWidget(b, r, c)
        grid.setColumnStretch(per_row, 1)
        group.content.addLayout(grid)
        return out

    # ------------------------------------------------------------------ history
    def begin(self):
        """Opens the page's history entry (once)."""
        if not self._open:
            self._snapshot = _sketch_state(self.sketch)
            try:
                # kept open past the command's own end: opened inside Activated (picks made first),
                # FreeCAD closes a plain transaction when the command returns, so Cancel could not take it back
                App.setActiveTransaction(self.TRANSACTION or self.TITLE, True)
            except Exception as _fw_err:
                _fw_log("sketchtoolpm.py:begin", _fw_err)
            self.doc.openTransaction(self.TRANSACTION or self.TITLE)
            self._open = True

    def undo_work(self):
        """Takes back what the page did so far and leaves the entry closed. When the aborted
        history entry did not bring the sketch back (an edit committed it on the way: tester
        SK9-09 left a pattern, SK9-12 moved lines after Cancel), the sketch as it was when the
        work began is put back."""
        if self._open:
            self.doc.abortTransaction()
            try:
                App.closeActiveTransaction(True)      # the kept entry opened in begin()
            except Exception as _fw_err:
                _fw_log("sketchtoolpm.py:abort-close", _fw_err)
            self._open = False
            snap = getattr(self, "_snapshot", None)
            if snap is not None and _sketch_key(self.sketch) != snap[2]:
                try:
                    self.sketch.Geometry = [g.clone() for g in snap[0]]
                    self.sketch.Constraints = list(snap[1])
                    for i, v in enumerate(snap[3]):
                        if v:
                            self.sketch.setVirtualSpace(i, True)
                    self.sketch.solve()
                    self.sketch.recompute()
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: %s: putting the sketch back: %s\n" % (self.TITLE, error))
            self._snapshot = None
            _refresh(self.sketch)

    def keyPressEvent(self, event):
        ""

        try:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) \
                    and not (event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier)):
                ok = getattr(self, "ok", None)
                if ok is None or (alive(ok) and ok.isEnabled() and ok.isVisible()):
                    event.accept()
                    QtCore.QTimer.singleShot(0, self.accept)
                    return
        except Exception as _fw_err:
            _fw_log("sketchtoolpm.py:enter", _fw_err)
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ check and cross
    def calculate(self):
        pass

    def finish(self):
        """Called by the check before the work is kept; a page may calculate here."""

    def accept(self):
        try:
            self.finish()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s: %s\n" % (self.TITLE, error))
        if self._open:
            self.doc.commitTransaction()
            try:
                App.closeActiveTransaction()      # the kept entry opened in begin(): the next edit is its own step
            except Exception as _fw_err:
                _fw_log("sketchtoolpm.py:commit-close", _fw_err)
            self._open = False
        close(self)

    def leave(self):
        """The sketch closed under the page: keep its work, as the sketch's own edits are kept."""
        if self._open:
            try:
                self.doc.commitTransaction()
                App.closeActiveTransaction()
            except Exception as _fw_err:
                _fw_log("sketchtoolpm.py:263", _fw_err)
            self._open = False
        close(self)

    def reject(self):
        self.undo_work()
        close(self)

    def closing(self):
        """The page goes away; subclasses drop their observers here."""


def _sketch_key(sketch):
    """What the sketch holds, to tell whether an undo brought it back."""
    try:
        return ([repr(g) for g in sketch.Geometry],
                [(c.Type, c.First, c.FirstPos, c.Second, c.SecondPos, c.Third, c.ThirdPos, round(c.Value, 9), c.Name)
                 for c in sketch.Constraints])
    except Exception:
        return None


def _sketch_state(sketch):
    """(geometry copies, constraints, key, virtual space flags) of the sketch now."""
    try:
        n = len(sketch.Constraints)
        return ([g.clone() for g in geomkeep.read(sketch)], list(sketch.Constraints), _sketch_key(sketch),
                [bool(sketch.getVirtualSpace(i)) for i in range(n)])
    except Exception:
        return None


def _refresh(sketch):
    try:
        sketch.solve()
        sketch.recompute()
    except Exception as _fw_err:
        _fw_log("sketchtoolpm.py:300", _fw_err)
    try:
        vp = sketch.ViewObject
        if vp is not None and hasattr(vp, "Proxy") is False:
            Gui.updateGui()
    except Exception as _fw_err:
        _fw_log("sketchtoolpm.py:306", _fw_err)


class _Host(QtCore.QObject):
    """Shows one page at a time in the left pane and closes it when the sketch closes."""

    def __init__(self):
        super().__init__()
        self.page = None
        self.pane = None
        self.view = []
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._check)

    def open(self, page):
        if self.page is not None:
            self.page.reject()
        shell = _shell()
        pane = getattr(shell, "left_pane", None) if shell is not None else None
        if pane is None or not alive(pane):
            return False
        self.page, self.pane = page, pane
        shell.sketch_tool_page = page
        old = pane.pages.get(PAGE)
        if old is not None and alive(old):
            pane.stack.removeWidget(old)
        pane._add_page(PAGE, page)
        pane.select_name(PAGE)
        try:
            pane.header.set_current(relationspm.PM_TAB)
        except Exception as _fw_err:
            _fw_log("sketchtoolpm.py:338", _fw_err)
        self._watch_view(shell, True)
        self.timer.start()
        return True

    def close(self, page):
        if page is not self.page:
            return
        self.timer.stop()
        shell = _shell()
        self._watch_view(shell, False)
        try:
            page.closing()
        except Exception as _fw_err:
            _fw_log("sketchtoolpm.py:352", _fw_err)
        pane = self.pane
        self.page = None
        if shell is not None:
            shell.sketch_tool_page = None
        if pane is not None and alive(pane):
            pane.pages.pop(PAGE, None)
            if alive(page):
                pane.stack.removeWidget(page)
            pane.restore_user_page()
        if alive(page):
            page.setParent(None)
            page.deleteLater()
        if shell is not None and getattr(shell, "relations_pm", None) is not None:
            shell.relations_pm.soon()
        view = shell.view_widget() if shell is not None else None
        if view is not None and alive(view):
            view.setFocus(Qt.OtherFocusReason)

    def _check(self):
        page = self.page
        if page is None:
            self.timer.stop()
            return
        if not alive(page):
            self.close(page)
        elif contextbar.sketch_in_edit() is not page.sketch:
            page.leave()

    def _watch_view(self, shell, on):
        for w in self.view:
            if alive(w):
                w.removeEventFilter(self)
        self.view = []
        view = shell.view_widget() if (on and shell is not None) else None
        if view is not None and alive(view):
            self.view = [view] + ([view.viewport()] if hasattr(view, "viewport") and view.viewport() else [])
            for w in self.view:
                w.installEventFilter(self)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter379(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter sketchtoolpm.py: %s\n" % exc)
            return False

    def _fw_filter379(self, obj, event):
        t = event.type()
        if t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress) and event.key() == Qt.Key_Escape \
                and self.page is not None:
            shell = _shell()
            if shell is not None and contextbar.tool_running(shell):
                return False
            if t == QtCore.QEvent.KeyPress:
                QtCore.QTimer.singleShot(0, self.page.reject)
            event.accept()
            return True
        if t == QtCore.QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.page is not None \
                and not (event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier)):

            # Positions, Mirror / Offset Entities); a running sketch tool keeps its own Enter
            shell = _shell()
            if shell is not None and contextbar.tool_running(shell) and not getattr(self.page, "TOOL_IS_PAGE", False):
                return False
            ok = getattr(self.page, "ok", None)
            if ok is not None and alive(ok) and not ok.isEnabled():
                return False
            QtCore.QTimer.singleShot(0, self.page.accept)
            event.accept()
            return True
        return False


def open_page(page):
    global _host
    if _host is None:
        _host = _Host()
    return _host.open(page)


def close(page):
    if _host is not None:
        _host.close(page)


# --------------------------------------------------------------------------- pick boxes
class PickObserver:
    """Hands each sketch pick to the page while it is open."""

    def __init__(self, page):
        self.page = page

    def addSelection(self, doc, obj, sub, pnt):
        page = self.page
        if page is None or not alive(page) or obj != page.sketch.Name or doc != page.doc.Name or not sub:
            return
        QtCore.QTimer.singleShot(0, lambda s=sub.rsplit(".", 1)[-1]: page.picked(s))

    def removeSelection(self, doc, obj, sub):
        page = self.page
        if page is not None and alive(page):
            QtCore.QTimer.singleShot(0, page.selection_changed)

    def clearSelection(self, doc):
        page = self.page
        if page is not None and alive(page):
            QtCore.QTimer.singleShot(0, page.selection_changed)


def item_of(sketch, sub):
    items = relationspm.items_of(sketch, [sub])
    return items[0] if items else None


def point_name(sketch, geo, pos):
    ""
    if (geo, pos) == (-1, 1):
        return "Point1@Origin"
    names = relationspm._entity_names(sketch.Geometry)
    if 0 <= geo < len(names):
        return "%s (%s)" % (names[geo], {1: "start", 2: "end", 3: "centre"}.get(pos, "point"))
    return "Point"


def _button_picture(title):
    ""
    try:
        from . import catalog, icons
        for cmd in catalog.BY_KEY.values():
            if title and title in (cmd.label, cmd.caption.replace("\n", " ")):
                for icon in (icons.family("FW_" + cmd.key), icons.drawn(cmd.key)):
                    if icons.paints(icon):
                        return icon
                break
    except Exception as _fw_err:
        _fw_log("sketchtoolpm:button_picture", _fw_err)
    return None


def pixmap_of(name):
    """A page's PIXMAP may name a command (Std_ViewLoadImage, Sketcher_Dimension): FreeCAD has no icon by
    that name ("Cannot find icon" in the Report view), so take the command's own pixmap."""
    try:
        if name in Gui.listCommands():
            pm = Gui.Command.get(name).getInfo().get("pixmap") or ""
            if pm:
                return pm
    except Exception as _fw_err:
        _fw_log("sketchtoolpm.py:489", _fw_err)
    return name
