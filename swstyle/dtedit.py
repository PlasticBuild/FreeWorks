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

from . import cmflows

Qt = QtCore.Qt
HEAD = 1                    # the parameter row (row 2 on screen)
LISTS = (("$STATE@", ("U", "S")), ("$SHOW@", ("Y", "N")), ("$CONFIGURATION@", None))
HINT = ("Type a configuration name in column A and a parameter in row 2, or right-click a row 2 cell "
        "to pick a dimension or a feature. OK updates the part.")
_OPEN = {}                  # document name -> the open window


def _letters(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def rows_of(doc):
    """The table's rows as the window shows them (the title, the parameters, a row per configuration)."""
    from . import configs
    rows = cmflows.table_rows(doc)
    if not rows:
        t = configs.table(doc)
        rows = [[cmflows.TITLE % doc.Label], [""]] + [[n] for n in t.names()]
    rows[0] = [cmflows.TITLE % doc.Label]
    return rows


def offered(doc, heads):
    """[(header, text)] the right-click on a parameter cell offers: dimensions and feature states
    not in the table yet."""
    have = {h.strip().upper() for h in heads if h}
    out = []
    for h, _o, _p, v, _i in cmflows.candidates(doc):
        if h.upper() not in have:
            out.append((h, "%s   %.4g" % (h, v)))
    for o in doc.Objects:
        if o.TypeId.startswith("PartDesign::") and o.TypeId not in ("PartDesign::Body",) and \
                not o.TypeId.startswith("PartDesign::Feature") and "Suppressed" in o.PropertiesList:
            h = "$STATE@" + o.Label
            if h.upper() not in have:
                out.append((h, h))
    try:                            # the part's global variables (Tools > Equations): $VALUE@name@equations
        from . import equations
        for name, _raw, _got in equations.variables(doc):
            h = "$VALUE@%s@equations" % name
            if h.upper() not in have and not equations.linked_values(doc).count(name):
                out.append((h, h))
    except Exception as _fw_err:
        _fw_log("dtedit.py:variables", _fw_err)
    for h in ("$DESCRIPTION", "$PARTNUMBER", "$COMMENT", "$PARENT"):
        if h not in have:
            out.append((h, h))
    return out


class _Lists(QtWidgets.QStyledItemDelegate):
    """Options > Enable cell drop-down lists: a state cell picks from its values."""

    def __init__(self, editor):
        super().__init__(editor.grid)
        self.editor = editor

    def createEditor(self, parent, option, index):
        items = self.editor.choices(index.row(), index.column())
        if not items:
            return super().createEditor(parent, option, index)
        box = QtWidgets.QComboBox(parent)
        box.setObjectName("SWDesignTableCellList")
        box.addItems(list(items))
        return box

    def setEditorData(self, w, index):
        if isinstance(w, QtWidgets.QComboBox):
            i = w.findText(str(index.data() or ""))
            w.setCurrentIndex(max(i, 0))
            QtCore.QTimer.singleShot(0, w.showPopup)
        else:
            super().setEditorData(w, index)

    def setModelData(self, w, model, index):
        if isinstance(w, QtWidgets.QComboBox):
            model.setData(index, w.currentText())
        else:
            super().setModelData(w, model, index)


class Editor(QtWidgets.QDialog):
    def __init__(self, doc, new_window=False):
        super().__init__(Gui.getMainWindow())
        self.doc = doc
        self.made = None
        self.setObjectName("SWDesignTableEditor")
        self.setWindowTitle(cmflows.TITLE % doc.Label)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        lay = QtWidgets.QVBoxLayout(self)
        self.grid = QtWidgets.QTableWidget()
        self.grid.setObjectName("SWDesignTableGrid")
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._menu)
        self.grid.itemChanged.connect(self._grow)
        lay.addWidget(self.grid)
        hint = QtWidgets.QLabel(HINT)
        hint.setWordWrap(True)
        lay.addWidget(hint)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        for b in bb.buttons():
            b.setAutoDefault(False)         # Return moves down a cell, as in a spreadsheet
            b.setDefault(False)
        lay.addWidget(bb)
        self.lists = None
        try:
            from . import dtoptions
            t = __import__("swstyle.configmanager", fromlist=["table"]).table(doc)
            if t is not None and dtoptions._on(dtoptions.options(t.sheet), "dropdowns"):
                self.lists = _Lists(self)
                self.grid.setItemDelegate(self.lists)
        except Exception as _fw_err:
            _fw_log("dtedit.py:lists", _fw_err)
        self.load()
        self._place(new_window)

    # ------------------------------------------------------------------ cells
    def load(self):
        rows = rows_of(self.doc)
        width = max(len(r) for r in rows)
        self.grid.blockSignals(True)
        self.grid.clear()
        self.grid.setRowCount(len(rows) + 1)
        self.grid.setColumnCount(width + 1)
        self.grid.setHorizontalHeaderLabels([_letters(c) for c in range(width + 1)])
        self.grid.setVerticalHeaderLabels([str(r + 1) for r in range(len(rows) + 1)])
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                self.grid.setItem(r, c, QtWidgets.QTableWidgetItem(str(v)))
        bold = self.font()
        bold.setBold(True)
        for c in range(self.grid.columnCount()):
            it = self.grid.item(HEAD, c)
            if it is None:
                it = QtWidgets.QTableWidgetItem("")
                self.grid.setItem(HEAD, c, it)
            it.setFont(bold)
        self.grid.blockSignals(False)
        self.grid.resizeColumnsToContents()

    def text(self, r, c):
        it = self.grid.item(r, c)
        return it.text().strip() if it is not None else ""

    def heads(self):
        return [self.text(HEAD, c) for c in range(self.grid.columnCount())]

    def choices(self, r, c):
        if r <= HEAD or c == 0:
            return None
        h = self.text(HEAD, c).upper()
        for head, items in LISTS:
            if h.startswith(head) and items:
                return items
        return None

    def _grow(self, item):
        """Excel's empty cells: a value typed in the spare row or column brings another."""
        self.grid.blockSignals(True)
        if item.row() == self.grid.rowCount() - 1 and item.text().strip():
            self.grid.setRowCount(self.grid.rowCount() + 1)
            self.grid.setVerticalHeaderLabels([str(r + 1) for r in range(self.grid.rowCount())])
        if item.column() == self.grid.columnCount() - 1 and item.text().strip():
            n = self.grid.columnCount() + 1
            self.grid.setColumnCount(n)
            self.grid.setHorizontalHeaderLabels([_letters(c) for c in range(n)])
        self.grid.blockSignals(False)

    def put_head(self, c, header):
        it = self.grid.item(HEAD, c)
        if it is None:
            it = QtWidgets.QTableWidgetItem("")
            self.grid.setItem(HEAD, c, it)
        it.setText(header)
        f = it.font()
        f.setBold(True)
        it.setFont(f)
        self.grid.resizeColumnToContents(c)

    def _menu(self, pos):
        index = self.grid.indexAt(pos)
        if not index.isValid() or index.row() != HEAD or index.column() == 0:
            return None
        items = offered(self.doc, self.heads())
        if not items:
            return None
        m = QtWidgets.QMenu(self.grid)
        m.setObjectName("SWDesignTableParameters")
        c = index.column()
        for h, label in items:
            m.addAction(label).triggered.connect(lambda _c=False, h=h: self.put_head(c, h))
        m.popup(self.grid.viewport().mapToGlobal(pos))
        self._m = m
        return m

    def rows(self):
        out = []
        for r in range(self.grid.rowCount()):
            row = [self.text(r, c) for c in range(self.grid.columnCount())]
            while row and row[-1] == "":
                row.pop()
            out.append(row)
        while out and not out[-1]:
            out.pop()
        return out

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            i = self.grid.currentIndex()
            if i.isValid() and i.row() + 1 < self.grid.rowCount():
                self.grid.setCurrentCell(i.row() + 1, i.column())
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ OK / Cancel
    def accept(self):
        rows = self.rows()
        heads = rows[HEAD] if len(rows) > HEAD else []
        bad = [h for h in heads[1:] if h and not cmflows.parse_header(self.doc, h)]
        if bad:
            QtWidgets.QMessageBox.warning(self, "Design Table",
                                          "These parameters do not match anything in the part and are left out:\n\n  "
                                          + "\n  ".join(bad))
            rows[HEAD] = [("" if h in bad else h) for h in heads]
        from . import configmanager
        before = set(configmanager.table(self.doc).names()) if configmanager.table(self.doc) else set()
        try:
            out = cmflows.apply_table(self.doc, rows)
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, "Design Table", str(error))
            return
        self.made = [n for n in out["configurations"] if n not in before]
        if out.get("equations"):
            QtWidgets.QMessageBox.information(self, "Design Table",
                                              "An equation drives these dimensions, so the design table's values for them "
                                              "are not used:\n\n  " + "\n  ".join(out["equations"]))
        try:
            configmanager.refresh_all()
        except Exception as _fw_err:
            _fw_log("dtedit.py:refresh", _fw_err)
        _OPEN.pop(self.doc.Name, None)
        super().accept()
        if self.made:
            QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Design Table",
                                              "The design table made these configurations:\n\n  " + "\n  ".join(self.made))

    def reject(self):
        _OPEN.pop(self.doc.Name, None)
        super().reject()

    def _place(self, new_window):
        ""

        mw = Gui.getMainWindow()
        area = mw.findChild(QtWidgets.QMdiArea)
        g = area.geometry() if area is not None else mw.geometry()
        top = (area or mw).mapToGlobal(QtCore.QPoint(0, 0))
        w = min(max(520, self.grid.horizontalHeader().length() + 80), max(520, g.width() - 40))
        h = min(max(260, self.grid.verticalHeader().length() + 140), max(260, g.height() - 40))
        self.resize(w, h)
        if new_window:
            x, y = top.x() + g.width() - w - 20, top.y() + 20
        else:
            x, y = top.x() + 20, top.y() + 20
        # wholly on the screen the main window is on (with two screens it could hang over the edge)
        try:
            scr = QtGui.QGuiApplication.screenAt(mw.frameGeometry().center()) or mw.screen()
            a = scr.availableGeometry()
            w, h = min(w, a.width() - 20), min(h, a.height() - 40)
            self.resize(w, h)
            x = max(a.left() + 10, min(x, a.right() - w - 10))
            y = max(a.top() + 10, min(y, a.bottom() - h - 30))
        except Exception as _fw_err:
            _fw_log("dtedit.py:place", _fw_err)
        self.move(x, y)


def open_editor(doc, new_window=False):
    """Edit Table / Edit Table in New Window: the table's window (one per part)."""
    old = _OPEN.get(doc.Name)
    if old is not None:
        try:
            old.raise_()
            old.activateWindow()
            return old
        except RuntimeError:
            _OPEN.pop(doc.Name, None)
    e = Editor(doc, new_window)
    _OPEN[doc.Name] = e
    e.show()
    e.raise_()
    e.activateWindow()
    e.grid.setFocus()
    e.grid.setCurrentCell(min(HEAD + 1, e.grid.rowCount() - 1), 0)
    QtCore.QTimer.singleShot(0, lambda: _front(e))        # in front once the opening command is done
    return e


def _front(e):
    try:
        if e.isVisible():
            e.raise_()
            e.activateWindow()
            e.grid.setFocus()
    except RuntimeError:
        return
