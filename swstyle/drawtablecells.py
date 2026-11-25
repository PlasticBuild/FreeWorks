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


import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D
from . import drawtableedit as DTE
from . import drawtables as DT

BLUE = QtGui.QColor(40, 110, 220)
STATE = {"overlay": None, "editor": None, "popup": None}


# =========================================================================== geometry
def cell_rect(t, r, c):
    """(x0, ytop, x1, ybottom) on the sheet (mm) of logical cell r, c (a merged block whole)."""
    r0, c0, r1, c1 = r, c, r, c
    m = DTE.merged_at(t, r, c)
    if m:
        r0, c0, r1, c1 = [int(v) for v in m.split(",")]
    return range_rect(t, r0, c0, r1, c1)


def range_rect(t, r0, c0, r1, c1):
    left, top, w, h = DTE.box(t)
    k = DTE.K * float(getattr(t, "Scale", 1.0) or 1.0)
    ws, hs = DTE.widths(t), DTE.heights(t)
    p = sorted((DTE._physical(t, r0), DTE._physical(t, r1)))
    x0 = left + sum(ws[:c0]) * k
    x1 = left + sum(ws[:c1 + 1]) * k
    y0 = top - sum(hs[:p[0]]) * k
    y1 = top - sum(hs[:p[1] + 1]) * k
    return x0, y0, x1, y1


def table_rect(gv, t):
    """The whole table in viewport pixels (every row, whichever end its header is at)."""
    nr, nc = DTE.size(t)
    out = None
    for r in range(nr):
        rect = to_viewport(gv, *range_rect(t, r, 0, r, nc - 1))
        out = rect if out is None else out.united(rect)
    return out


def to_viewport(gv, x0, y0, x1, y1):
    a = gv.mapFromScene(D.to_scene(x0, y0))
    b = gv.mapFromScene(D.to_scene(x1, y1))
    return QtCore.QRect(QtCore.QPoint(min(a.x(), b.x()), min(a.y(), b.y())),
                        QtCore.QPoint(max(a.x(), b.x()), max(a.y(), b.y())))


def px_per_mm(gv):
    a = gv.mapFromScene(D.to_scene(0, 0))
    b = gv.mapFromScene(D.to_scene(10, 0))
    return max(0.2, (b.x() - a.x()) / 10.0)


def _alive(t):
    try:
        return t is not None and t.Document is not None and t.Document.getObject(t.Name) is t
    except Exception:
        return False


# =========================================================================== selection
class _Band(QtWidgets.QWidget):
    """The column letters over the table, or the row numbers on its left; a click selects that column / row."""

    def __init__(self, parent, columns):
        super().__init__(parent)
        self.columns = columns
        self.setObjectName("SWTableColumnLetters" if columns else "SWTableRowNumbers")
        self.cuts = []                     # [(start px, end px)] per column / row
        self.on_pick = None
        self.current = (-1, -1)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setPen(QtGui.QColor("#606060"))
        f = p.font()
        f.setPointSizeF(7.5)
        p.setFont(f)
        for i, (a, b) in enumerate(self.cuts):
            rect = QtCore.QRect(a, 0, b - a, self.height()) if self.columns else QtCore.QRect(0, a, self.width(), b - a)
            on = self.current[0] <= i <= self.current[1]
            p.fillRect(rect.adjusted(0, 0, -1, -1), QtGui.QColor(200, 220, 250) if on else QtGui.QColor("#ececec"))
            p.drawRect(rect.adjusted(0, 0, -1, -1))
            p.drawText(rect, QtCore.Qt.AlignCenter, DT.COLS[i] if self.columns else str(i + 1))
        p.end()

    def index_at(self, pos):
        v = pos.x() if self.columns else pos.y()
        for i, (a, b) in enumerate(self.cuts):
            if a <= v < b:
                return i
        return None

    def mousePressEvent(self, e):
        i = self.index_at(e.pos())
        if i is not None and self.on_pick is not None:
            self.on_pick(i)
        e.accept()


class _Outline(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SWTableCellOutline")
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(80, 140, 255, 45))
        p.setPen(QtGui.QPen(BLUE, 2))
        p.drawRect(self.rect().adjusted(1, 1, -1, -1))
        p.end()


TABLE_BAR = (
    ("SWTableBarHeaderTop", "\u2191H", "Table Header Top", "cmd:FreeWorks_DrawTableHeaderTop"),
    ("SWTableBarHeaderBottom", "\u2193H", "Table Header Bottom", "cmd:FreeWorks_DrawTableHeaderBottom"),
    ("SWTableBarFormat", "Aa", "Table Format", "cmd:FreeWorks_DrawTableEntireTable"),
    None,
    ("SWTableBarLeft", "L", "Left", "align:left"),
    ("SWTableBarCenter", "C", "Center", "align:center"),
    ("SWTableBarRight", "R", "Right", "align:right"),
    None,
    ("SWTableBarTop", "T", "Top", "valign:top"),
    ("SWTableBarMiddle", "M", "Middle", "valign:vcenter"),
    ("SWTableBarBottom", "B", "Bottom", "valign:bottom"),
    None,
    ("SWTableBarColor", "A", "Color", "color"),
    ("SWTableBarMerge", "\u229e", "Merge Cells", "cmd:FreeWorks_DrawTableMergeCells"),
    ("SWTableBarUnmerge", "\u229f", "Unmerge a Cell", "cmd:FreeWorks_DrawTableUnmergeCell"),
    ("SWTableBarLockWidth", "\u2194", "Lock Column Width", "cmd:FreeWorks_DrawTableLockColumnWidth"),
    ("SWTableBarLockHeight", "\u2195", "Lock Row Height", "cmd:FreeWorks_DrawTableLockRowHeight"),
)


def selected_cells():
    """[(r, c)] of the current selection (the whole block of a range)."""
    cur = DTE.current()
    if cur is None:
        return []
    _t, r0, c0, r1, c1 = cur
    return [(r, c) for r in range(min(r0, r1), max(r0, r1) + 1) for c in range(min(c0, c1), max(c0, c1) + 1)]


def table_bar_action(action):
    """Run one Table toolbar button on the selected cells."""
    cur = DTE.current()
    if cur is None or not _alive(cur[0]):
        return False
    t = cur[0]
    cells = selected_cells()
    if action.startswith("cmd:"):
        name = action[4:]
        if name not in Gui.listCommands():
            return False
        Gui.runCommand(name, 0)
        return True
    doc = t.Document
    doc.openTransaction("Table Format")
    try:
        if action.startswith("align:"):
            DTE.set_format(t, cells, align=action[6:])
        elif action.startswith("valign:"):
            DTE.set_format(t, cells, valign=action[7:])
        elif action == "color":
            col = _pick_color(DTE.cell_extra(t, *cells[0])[2] if cells else None)
            if col is None:
                return False
            DTE.set_format(t, cells, color=col)
    finally:
        doc.commitTransaction()
    return True


class TableBar(QtWidgets.QFrame):
    ""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SWTableToolbar")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(1)
        self.buttons = {}
        for e in TABLE_BAR:
            if e is None:
                lay.addSpacing(5)
                continue
            name, text, tip, action = e
            b = QtWidgets.QToolButton(self)
            b.setObjectName(name)
            b.setText(text)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.setFixedSize(24, 22)
            b.clicked.connect(lambda c=False, a=action: self.run(a))
            lay.addWidget(b)
            self.buttons[name] = b

    def run(self, action):
        table_bar_action(action)
        s = STATE.get("overlay")
        if s is not None and s.shown:
            QtCore.QTimer.singleShot(0, s.place)


class Selection(QtCore.QObject):
    """The selected cell / column / row of a table on a sheet window, kept over the table as it scrolls."""

    def __init__(self, page, gv):
        super().__init__(gv.viewport())
        self.page, self.gv = page, gv
        vp = gv.viewport()
        self.outline = _Outline(vp)
        self.letters = _Band(vp, True)
        self.numbers = _Band(vp, False)
        self.letters.on_pick = self.pick_column
        self.numbers.on_pick = self.pick_row
        self.bar = TableBar(vp)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.place)
        self.shown = False

    def show(self):
        self.shown = True
        self.place()
        for w in (self.outline, self.letters, self.numbers, self.bar):
            w.show()
            w.raise_()
        self.timer.start()

    def hide(self):
        self.shown = False
        self.timer.stop()
        for w in (self.outline, self.letters, self.numbers, self.bar):
            w.hide()

    def place(self):
        cur = DTE.current()
        if cur is None or not _alive(cur[0]):
            self.hide()
            return
        t, r0, c0, r1, c1 = cur
        gv = self.gv
        whole = table_rect(gv, t)
        x0, y0, x1, y1 = range_rect(t, r0, c0, r1, c1)
        if (r0, c0) == (r1, c1):
            x0, y0, x1, y1 = cell_rect(t, r0, c0)
        self.outline.setGeometry(to_viewport(gv, x0, y0, x1, y1).adjusted(-1, -1, 1, 1))
        left, top, _w, _h = DTE.box(t)
        k = DTE.K * float(getattr(t, "Scale", 1.0) or 1.0)
        cuts, acc = [], left
        for w in DTE.widths(t):
            a = gv.mapFromScene(D.to_scene(acc, top)).x()
            acc += w * k
            b = gv.mapFromScene(D.to_scene(acc, top)).x()
            cuts.append((a - whole.left(), b - whole.left()))
        band = 16
        self.letters.cuts = cuts
        self.letters.current = (c0, c1)
        self.letters.setGeometry(whole.left(), whole.top() - band - 2, whole.width() + 1, band)
        rows, acc = [], top
        nr = DTE.size(t)[0]
        hs = DTE.heights(t)
        ys = []
        for pr in range(nr):
            a = gv.mapFromScene(D.to_scene(left, acc)).y()
            acc -= hs[pr] * k
            b = gv.mapFromScene(D.to_scene(left, acc)).y()
            ys.append((a - whole.top(), b - whole.top()))
        rows = [ys[DTE._physical(t, r)] for r in range(nr)]        # numbered in logical order (header 1)
        self.numbers.cuts = rows
        self.numbers.current = (r0, r1)
        self.numbers.setGeometry(whole.left() - band - 2, whole.top(), band, whole.height() + 1)
        for w in (self.letters, self.numbers, self.outline):
            w.update()
        editing = STATE.get("editor") is not None      # the Formatting toolbar takes its place while editing
        self.bar.setVisible(self.shown and not editing)
        if self.shown and not editing:
            self.bar.adjustSize()
            self.bar.move(max(0, whole.left()), max(0, whole.top() - band - 4 - self.bar.height()))
            self.bar.raise_()

    def pick_column(self, c):
        cur = DTE.current()
        if cur is None:
            return
        t = cur[0]
        DTE.set_current(t, 0, c, DTE.size(t)[0] - 1, c)
        self.place()
        if getattr(t, "SWTable", "") == "BOM":
            column_popup(self.page, t, c, self.letters.mapToGlobal(QtCore.QPoint(self.letters.cuts[c][0],
                                                                                  self.letters.height())))

    def pick_row(self, r):
        cur = DTE.current()
        if cur is None:
            return
        t = cur[0]
        DTE.set_current(t, r, 0, r, DTE.size(t)[1] - 1)
        self.place()
        close_popup()


def selection(page):
    gv = D.page_view(page)
    if gv is None:
        return None
    s = STATE.get("overlay")
    try:
        if s is not None and s.gv is gv and s.page is page:
            return s
        if s is not None:
            s.hide()
    except Exception as _fw_err:
        _fw_log("drawtablecells.py:347", _fw_err)
    s = Selection(page, gv)
    STATE["overlay"] = s
    return s


def hide_selection():
    s = STATE.get("overlay")
    try:
        if s is not None:
            s.hide()
    except Exception:
        STATE["overlay"] = None


def on_press(page, hit):
    """drawtableedit's sheet press: a table cell selects it (outline, letters, numbers); elsewhere they go."""
    ed = STATE.get("editor")
    if ed is not None:
        try:
            ed.commit()
        except Exception as _fw_err:
            _fw_log("drawtablecells.py:369", _fw_err)
    close_popup()
    if hit is None:
        hide_selection()
        return
    s = selection(page)
    if s is not None:
        QtCore.QTimer.singleShot(0, s.show)


# =========================================================================== Column type (BOM)
def _fit_columns(t, cols):
    n = DTE.size(t)[1]
    cols = list(cols)[:n]
    while len(cols) < n:
        cols.append({"type": "User Defined", "title": ""})
    return cols


def set_column_type(t, c, kind, prop=""):
    """A BOM column's Column type (and Property name for a Custom Property): its header and values follow."""
    doc = t.Document
    cols = _fit_columns(t, DT.columns_of(t))
    old = cols[c]
    col = {"type": kind}
    if kind == "Custom Property":
        col["prop"] = prop or "Description"
        col["title"] = col["prop"].upper()
    elif kind == "Item No.":
        col["title"] = "ITEM NO."
    elif kind == "Part Number":
        col["title"] = "PART NUMBER"
    elif kind == "Quantity":
        col["title"] = DT.qty_title()      # extapps84: System Options > Drawings > Override quantity column name
    else:
        col["title"] = old.get("title", "") if old.get("type") == "User Defined" else ""
    cols[c] = col
    doc.openTransaction("Column type")
    try:
        DT.store_columns(t, cols)
        DT.update_table(t)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return col


def property_names(t):
    names = list(DT.BOM_PROPERTIES)
    try:
        from . import customprops
        for n in customprops.name_list():
            if n not in names:
                names.append(n)
        view = t.Document.getObject(getattr(t, "SWBomView", "") or "")
        for o in DT.DV.source_shapes(view) if view is not None else []:
            for n, _k, _v in customprops.read(getattr(o, "LinkedObject", o).Document):
                if n not in names:
                    names.append(n)
    except Exception as _fw_err:
        _fw_log("drawtablecells.py:429", _fw_err)
    return names


class ColumnPopup(QtWidgets.QFrame):
    ""

    def __init__(self, t, c):
        super().__init__(Gui.getMainWindow(), QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.setObjectName("SWBomColumnPopup")
        self.setFrameShape(QtWidgets.QFrame.Box)
        self.t, self.c = t, c
        lay = QtWidgets.QFormLayout(self)
        self.kind = QtWidgets.QComboBox(self)
        self.kind.setObjectName("SWBomColumnType")
        self.kind.addItems(DT.BOM_COLUMN_TYPES)
        self.prop = QtWidgets.QComboBox(self)
        self.prop.setObjectName("SWBomColumnProperty")
        self.prop.setEditable(True)
        self.prop.addItems(property_names(t))
        cols = _fit_columns(t, DT.columns_of(t))
        col = cols[c]
        self.kind.setCurrentText(col.get("type", "User Defined"))
        self.prop.setCurrentText(col.get("prop", "Description"))
        self.prop.setEnabled(self.kind.currentText() == "Custom Property")
        lay.addRow("Column type:", self.kind)
        lay.addRow("Property name:", self.prop)
        self.kind.activated.connect(self.apply)
        self.prop.activated.connect(self.apply)
        self.prop.lineEdit().editingFinished.connect(self.apply)

    def apply(self, *_):
        kind = self.kind.currentText()
        self.prop.setEnabled(kind == "Custom Property")
        cols = _fit_columns(self.t, DT.columns_of(self.t))
        now = cols[self.c]
        if now.get("type") == kind and (kind != "Custom Property" or now.get("prop") == self.prop.currentText()):
            return
        set_column_type(self.t, self.c, kind, self.prop.currentText())
        s = STATE.get("overlay")
        if s is not None and s.shown:
            s.place()

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            close_popup()
            return
        super().keyPressEvent(e)


def column_popup(page, t, c, at):
    close_popup()
    pop = ColumnPopup(t, c)
    STATE["popup"] = pop
    pop.adjustSize()
    pop.move(at + QtCore.QPoint(0, 4))
    pop.show()
    pop.raise_()
    return pop


def close_popup():
    pop = STATE.get("popup")
    STATE["popup"] = None
    if pop is not None:
        try:
            pop.hide()
            pop.deleteLater()
        except Exception as _fw_err:
            _fw_log("drawtablecells.py:498", _fw_err)


# =========================================================================== in-place editing
class _Line(QtWidgets.QLineEdit):
    def __init__(self, editor, parent):
        super().__init__(parent)
        self.editor = editor

    def keyPressEvent(self, e):
        k = e.key()
        if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.editor.commit()
            return
        if k == QtCore.Qt.Key_Escape:
            self.editor.cancel()
            return
        if k == QtCore.Qt.Key_Tab:
            self.editor.go(0, 1)
            return
        if k == QtCore.Qt.Key_Backtab:
            self.editor.go(0, -1)
            return
        if k == QtCore.Qt.Key_Up:
            self.editor.go(-1, 0)
            return
        if k == QtCore.Qt.Key_Down:
            self.editor.go(1, 0)
            return
        super().keyPressEvent(e)

    def event(self, e):
        if e.type() == QtCore.QEvent.KeyPress and e.key() in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab):
            self.keyPressEvent(e)
            return True
        return super().event(e)


FORMAT_BUTTONS = (("SWCellBold", "B", "Bold", "bold"), ("SWCellItalic", "I", "Italic", "italic"),
                  ("SWCellUnderline", "U", "Underline", "underline"))
ALIGN_BUTTONS = (("SWCellLeft", "Left", "left"), ("SWCellCenter", "Center", "center"),
                 ("SWCellRight", "Right", "right"))
VALIGN_BUTTONS = (("SWCellTop", "Top", "top"), ("SWCellMiddle", "Middle", "vcenter"),
                  ("SWCellBottom", "Bottom", "bottom"))
ASK = {}                                   # tests: ASK["color"] = (r, g, b) answers the colour dialog
SIZES = ("2", "2.5", "3", "3.5", "4", "5", "6", "7", "8", "10", "12", "14")


def _pick_color(start=None):
    """The colour dialog (Formatting / Table toolbar Color), else None when cancelled."""
    if "color" in ASK:
        return tuple(ASK.pop("color"))
    c = QtWidgets.QColorDialog.getColor(QtGui.QColor(*(start or (0, 0, 0))), Gui.getMainWindow(), "Color")
    return (c.red(), c.green(), c.blue()) if c.isValid() else None


def _font_box(parent, t):
    ""

    font = QtWidgets.QFontComboBox(parent)
    font.setObjectName("SWCellFont")
    font.setToolTip("Font")
    font.setMaximumWidth(150)
    name = str(getattr(t, "Font", "") or "")
    if name:
        font.setCurrentFont(QtGui.QFont(name))
    size = QtWidgets.QComboBox(parent)
    size.setObjectName("SWCellSize")
    size.setToolTip("Font size (mm)")
    size.setEditable(True)
    size.addItems(SIZES)
    size.setMaximumWidth(60)
    try:
        # look-audit tablefont-1121: the box shows mm (TextSize is in 1/96 in, times the table's Scale)
        v = float(getattr(t, "TextSize", 12.0) or 12.0) * 25.4 / 96.0 * float(getattr(t, "Scale", 1.0) or 1.0)
    except Exception:
        v = 3.5
    size.setEditText(("%g" % v))
    return font, size


def set_table_font(t, family=None, size=None):
    if family is not None and "Font" in t.PropertiesList:
        t.Font = str(family)
    if size is not None and "TextSize" in t.PropertiesList:
        try:
            v = float(str(size).replace(",", "."))
        except ValueError:
            return
        if v > 0:
            t.TextSize = v / (25.4 / 96.0 * float(getattr(t, "Scale", 1.0) or 1.0))    # mm in (tablefont-1121)
    t.Document.recompute()


class _KeysFirst(QtCore.QObject):
    """While a cell is edited its Enter / Esc are the editor's: an open PropertyManager (a picked BOM opens
    its PM) must not take them as OK / Cancel. An application filter installed last runs first."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor

    def eventFilter(self, obj, event):
        try:
            t = event.type()
            if t not in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease, QtCore.QEvent.ShortcutOverride):
                return False
            if event.key() not in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Escape):
                return False
            ed = self.editor
            if ed.done or QtWidgets.QApplication.focusWidget() is not ed.line:
                return False
            if t == QtCore.QEvent.ShortcutOverride:
                event.accept()
                return True
            if t == QtCore.QEvent.KeyPress and not event.isAutoRepeat():
                QtCore.QTimer.singleShot(0, ed.cancel if event.key() == QtCore.Qt.Key_Escape else ed.commit)
            return True
        except Exception:
            return False


class CellEditor(QtCore.QObject):
    """The cell's text edited where it is, the Formatting toolbar over it."""

    def __init__(self, page, t, r, c):
        gv = D.page_view(page)
        super().__init__(gv.viewport())
        self.page, self.gv, self.t, self.r, self.c = page, gv, t, r, c
        self.done = False
        vp = gv.viewport()
        self.line = _Line(self, vp)
        self.line.setObjectName("SWTableCellEditor")
        self.line.setFrame(False)
        self.line.setStyleSheet("QLineEdit { background: #ffffff; color: #000000; border: 2px solid #286edc; }")
        self.bar = QtWidgets.QFrame(vp)
        self.bar.setObjectName("SWTableFormatting")
        self.bar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.bar.setAutoFillBackground(True)
        lay = QtWidgets.QHBoxLayout(self.bar)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(1)
        self.buttons = {}
        self.font, self.size = _font_box(self.bar, t)
        self.font.currentFontChanged.connect(lambda f: self.refont(family=f.family()))
        self.size.activated.connect(lambda i: self.refont(size=self.size.itemText(i)))
        self.size.lineEdit().returnPressed.connect(lambda: self.refont(size=self.size.currentText()))
        lay.addWidget(self.font)
        lay.addWidget(self.size)
        lay.addSpacing(4)
        for name, text, tip, _style in FORMAT_BUTTONS:
            b = self._button(name, text, tip)
            f = b.font()
            f.setBold(text == "B")
            f.setItalic(text == "I")
            f.setUnderline(text == "U")
            b.setFont(f)
            b.toggled.connect(self.restyle)
            lay.addWidget(b)
        b = self._button("SWCellStrike", "S", "Strikeout")
        f = b.font()
        f.setStrikeOut(True)
        b.setFont(f)
        b.toggled.connect(self.restrike)
        lay.addWidget(b)
        c = self._button("SWCellColor", "A", "Color")
        c.setCheckable(False)
        c.clicked.connect(self.recolor)
        lay.addWidget(c)
        lay.addSpacing(6)
        self.aligns = QtWidgets.QButtonGroup(self.bar)
        self.aligns.setExclusive(True)
        for name, tip, _a in ALIGN_BUTTONS:
            b = self._button(name, tip[0], tip)
            self.aligns.addButton(b)
            lay.addWidget(b)
        self.aligns.buttonClicked.connect(self.realign)
        lay.addSpacing(6)
        self.valigns = QtWidgets.QButtonGroup(self.bar)
        self.valigns.setExclusive(True)
        for name, tip, _a in VALIGN_BUTTONS:
            b = self._button(name, tip[0], tip)
            self.valigns.addButton(b)
            lay.addWidget(b)
        self.valigns.buttonClicked.connect(self.revalign)
        self.keys = _KeysFirst(self)
        QtWidgets.QApplication.instance().installEventFilter(self.keys)
        self.load()

    def _button(self, name, text, tip):
        b = QtWidgets.QToolButton(self.bar)
        b.setObjectName(name)
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(True)
        b.setAutoRaise(True)
        b.setFixedSize(22, 22)
        self.buttons[name] = b
        return b

    def load(self):
        rs = DTE.rows(self.t)
        self.original = rs[self.r][self.c] if self.r < len(rs) and self.c < len(rs[self.r]) else ""
        self.line.setText(DT.unstrike(self.original))
        self.line.selectAll()
        style, align = DTE.cell_format(self.t, self.r, self.c)
        for name, _text, _tip, st in FORMAT_BUTTONS:
            b = self.buttons[name]
            b.blockSignals(True)
            b.setChecked(st in style.split("|"))
            b.blockSignals(False)
        for name, _tip, a in ALIGN_BUTTONS:
            self.buttons[name].setChecked(a == align)
        valign, struck, _col = DTE.cell_extra(self.t, self.r, self.c)
        for name, _tip, a in VALIGN_BUTTONS:
            self.buttons[name].setChecked(a == valign)
        b = self.buttons["SWCellStrike"]
        b.blockSignals(True)
        b.setChecked(struck)
        b.blockSignals(False)
        self.place()
        self.line.show()
        self.bar.show()
        self.line.raise_()
        self.bar.raise_()
        self.line.setFocus(QtCore.Qt.OtherFocusReason)

    def place(self):
        rect = to_viewport(self.gv, *cell_rect(self.t, self.r, self.c))
        self.line.setGeometry(rect.adjusted(-1, -1, 1, 1))
        size = float(getattr(self.t, "TextSize", 12.0) or 12.0) * 25.4 / 96.0 * float(getattr(self.t, "Scale", 1.0) or 1.0)
        f = self.line.font()
        f.setPixelSize(max(8, int(size * px_per_mm(self.gv))))
        style, align = DTE.cell_format(self.t, self.r, self.c)
        f.setBold("bold" in style)
        f.setItalic("italic" in style)
        f.setUnderline("underline" in style)
        self.line.setFont(f)
        self.line.setAlignment({"left": QtCore.Qt.AlignLeft, "center": QtCore.Qt.AlignHCenter,
                                "right": QtCore.Qt.AlignRight}.get(align, QtCore.Qt.AlignLeft) |
                               QtCore.Qt.AlignVCenter)
        self.bar.adjustSize()
        self.bar.move(rect.left(), max(0, rect.top() - self.bar.height() - 20))

    def restyle(self, *_):
        style = "|".join(st for name, _t, _tip, st in FORMAT_BUTTONS if self.buttons[name].isChecked())
        DTE.set_format(self.t, [(self.r, self.c)], style=style)
        self.place()
        self.line.setFocus()

    def refont(self, family=None, size=None):
        set_table_font(self.t, family, size)
        self.place()
        self.line.setFocus()

    def restrike(self, on):
        DTE.set_format(self.t, [(self.r, self.c)], strike=bool(on))
        self.line.setFocus()

    def recolor(self, *_):
        col = _pick_color(DTE.cell_extra(self.t, self.r, self.c)[2])
        if col is not None:
            DTE.set_format(self.t, [(self.r, self.c)], color=col)
        self.line.setFocus()

    def revalign(self, b):
        a = next(a for name, _tip, a in VALIGN_BUTTONS if self.buttons[name] is b)
        DTE.set_format(self.t, [(self.r, self.c)], valign=a)
        self.line.setFocus()

    def realign(self, b):
        a = next(a for name, _tip, a in ALIGN_BUTTONS if self.buttons[name] is b)
        DTE.set_format(self.t, [(self.r, self.c)], align=a)
        self.place()
        self.line.setFocus()

    def keep(self):
        text = self.line.text()
        if text != DT.unstrike(self.original) and _alive(self.t):
            doc = self.t.Document
            doc.openTransaction("Edit Text")
            try:
                DTE.edit_cell(self.t, self.r, self.c, text)
                if DTE.cell_extra(self.t, self.r, self.c)[1]:
                    DTE.apply_formats(self.t)       # Strikeout stays on the new text
            finally:
                doc.commitTransaction()

    def go(self, dr, dc):
        """Keep the text and edit the next cell (Tab: along the row, wrapping; Up / Down: the column)."""
        self.keep()
        nr, nc = DTE.size(self.t)

        def block(r, c):
            m = DTE.merged_at(self.t, r, c)
            return [int(v) for v in m.split(",")] if m else [r, c, r, c]

        r0, c0, r1, c1 = block(self.r, self.c)       # a merged block moves as one cell
        r = r1 + 1 if dr > 0 else (r0 - 1 if dr < 0 else self.r)
        c = c1 + 1 if dc > 0 else (c0 - 1 if dc < 0 else self.c)
        for _i in range(nr * nc + 1):
            if dc:
                if c >= nc:
                    r, c = r + 1, 0
                elif c < 0:
                    r, c = r - 1, nc - 1
            if not (0 <= r < nr and 0 <= c < nc):
                break
            a0, b0, a1, b1 = block(r, c)
            if (r, c) == (a0, b0):
                break
            if dc > 0:
                c = b1 + 1                          # Tab steps over a block's hidden cells
                continue
            r, c = a0, b0                           # into a block: the block's own cell
            break
        if not (0 <= r < nr and 0 <= c < nc):
            self.close()
            return
        self.r, self.c = r, c
        DTE.set_current(self.t, r, c)
        s = STATE.get("overlay")
        if s is not None and s.shown:
            s.place()
        self.load()

    def commit(self):
        if self.done:
            return
        self.keep()
        self.close()

    def cancel(self):
        self.close()

    def close(self):
        self.done = True
        try:
            QtWidgets.QApplication.instance().removeEventFilter(self.keys)
        except Exception as _fw_err:
            _fw_log("drawtablecells.py:819", _fw_err)
        if STATE.get("editor") is self:
            STATE["editor"] = None
        for w in (self.line, self.bar):
            try:
                w.hide()
                w.deleteLater()
            except Exception as _fw_err:
                _fw_log("drawtablecells.py:827", _fw_err)
        try:
            self.gv.viewport().setFocus()
        except Exception as _fw_err:
            _fw_log("drawtablecells.py:831", _fw_err)


def edit_in_place(page, t, r, c):
    """Double-click on a cell: its text edited where it is."""
    old = STATE.get("editor")
    if old is not None:
        try:
            old.commit()
        except Exception as _fw_err:
            _fw_log("drawtablecells.py:841", _fw_err)
    close_popup()
    if D.page_view(page) is None:
        return None
    if DTE.is_locked(t, r, c):
        DTE.set_current(t, r, c)
        DTE._locked_message()                   # a locked cell isn't opened for editing
        return None
    DTE.set_current(t, r, c)
    s = selection(page)
    if s is not None:
        s.show()
    ed = CellEditor(page, t, r, c)
    STATE["editor"] = ed
    return ed
