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

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

PROP = "DesignTableOptions"
DEFAULTS = {"link": "", "mtime": "0", "control": "allow", "new_parameters": "1", "new_configurations": "1",
            "warn": "0", "dropdowns": "0"}
DROPDOWNS = "Enable cell drop-down lists (may slow down performance)"
SUPPRESSION = (("Suppressed", "1"), ("Unsuppressed", "0"))
BLOCKED = "The design table blocks model edits that would update it (Edit Control)."


def _sheet(doc):
    ""

    from . import configmanager, cmflows
    t = configmanager.table(doc)
    if t is None or cmflows.table_deleted(doc):
        return None
    return t.sheet


def options(sheet):
    out = dict(DEFAULTS)
    if sheet is not None and PROP in sheet.PropertiesList:
        out.update(dict(getattr(sheet, PROP) or {}))
    return out


def set_options(sheet, **values):
    if sheet is None:
        return None
    if PROP not in sheet.PropertiesList:
        sheet.addProperty("App::PropertyMap", PROP, "Design Table", "Link to file, Edit Control, Options")
        sheet.setEditorMode(PROP, 2)
    now = options(sheet)
    for k, v in values.items():
        if isinstance(v, bool):
            v = "1" if v else "0"
        now[k] = str(v)
    if values.get("link"):
        try:
            now["mtime"] = str(os.path.getmtime(values["link"]))
        except OSError as _fw_err:
            _fw_log("dtoptions.py:73", _fw_err)
    setattr(sheet, PROP, now)
    return now


def _on(opts, key):
    return opts.get(key, "1") in ("1", "True", "true")


def allow_edit(doc, new_column, quiet=False):
    """A model edit is about to write into the design table: 'table', 'model' (change the model
    only) or None (refused)."""
    sheet = _sheet(doc)
    if sheet is None:
        return "table"
    opts = options(sheet)
    if not new_column and opts.get("control") == "block":
        if not quiet and App.GuiUp:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Design Table", BLOCKED)
        return None
    if new_column and not _on(opts, "new_parameters"):
        return "model"
    if _on(opts, "warn") and not quiet and App.GuiUp:
        answer = QtWidgets.QMessageBox.question(
            Gui.getMainWindow(), "Design Table",
            "This change will update the design table. Continue?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if answer != QtWidgets.QMessageBox.Yes:
            return None
    return "table"


def allow_new_configuration(doc, quiet=False):
    sheet = _sheet(doc)
    if sheet is None or _on(options(sheet), "new_configurations"):
        return True
    if not quiet and App.GuiUp:
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Design Table",
                                      "The design table does not take new configurations (Options).")
    return False


def reload_link(sheet, force=False):
    """Link to file: read the linked file again when it changed. True when it was read."""
    if sheet is None:
        return False
    opts = options(sheet)
    path = opts.get("link")
    if not path or not os.path.exists(path):
        return False
    mtime = os.path.getmtime(path)
    if not force and abs(mtime - float(opts.get("mtime") or 0)) < 1e-6:
        return False
    rows = _read(path)
    if rows is None:
        return False
    try:
        from . import cmflows
        h = cmflows.header_row(rows)
        sw_form = bool(rows) and any(cmflows.parse_header(sheet.Document, c) for c in rows[h][1:])
    except Exception:
        sw_form = False
    if sw_form:

        # Save Table writes it: read the way Insert > Design Table > From file reads it
        set_options(sheet, mtime=str(mtime))
        cmflows.apply_table(sheet.Document, rows)
        sheet.Document.recompute()
        return True
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = "%s%d" % (_col(c), r + 1)
            if str(sheet.getContents(cell)) != str(value):
                sheet.set(cell, str(value))
    set_options(sheet, mtime=str(mtime))
    sheet.Document.recompute()
    return True


def _col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _read_xlsx(path):
    """The first worksheet of an .xlsx as rows of text. Stock FreeCAD's importXLSX stops on an empty
    inline string and on "str"/"b" cells, so a design table saved by Save Table (or by Excel with
    blank cells) did not read back; this reader takes shared strings, inline strings, numbers,
    booleans and formula results."""
    import re
    import zipfile
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rid = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        book = ET.fromstring(z.read("xl/workbook.xml"))
        first = book.find("m:sheets/m:sheet", ns)
        target = "worksheets/sheet1.xml"
        if first is not None and "xl/_rels/workbook.xml.rels" in names:
            rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            for r in rels:
                if r.get("Id") == first.get(rid):
                    target = r.get("Target", target)
        target = target.lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        sheet = ET.fromstring(z.read(target))
    out = {}
    for row in sheet.iter("{%s}row" % ns["m"]):
        for c in row.findall("m:c", ns):
            m = re.match(r"([A-Z]+)(\d+)$", c.get("r", ""))
            if not m:
                continue
            col = 0
            for ch in m.group(1):
                col = col * 26 + ord(ch) - 64
            kind = c.get("t", "n")
            v = c.find("m:v", ns)
            if kind == "inlineStr":
                text = "".join(t.text or "" for t in c.iter("{%s}t" % ns["m"]))
            elif v is None or v.text is None:
                text = ""
            elif kind == "s":
                i = int(v.text)
                text = shared[i] if 0 <= i < len(shared) else ""
            elif kind == "b":
                text = "TRUE" if v.text.strip() == "1" else "FALSE"
            else:
                text = v.text
                if kind == "n" and re.fullmatch(r"-?\d+\.0+", text):
                    text = text.split(".")[0]
            out.setdefault(int(m.group(2)) - 1, {})[col - 1] = text
    n_rows = max(out) + 1 if out else 0
    n_cols = max((max(r) for r in out.values()), default=-1) + 1
    return [[out.get(r, {}).get(c, "") for c in range(n_cols)] for r in range(n_rows)]


def _read(path):
    if path.lower().endswith(".csv"):
        import csv
        with open(path, newline="", encoding="utf-8-sig") as f:
            return [row for row in csv.reader(f)]
    if path.lower().endswith((".xlsx", ".xlsm")):
        try:
            return _read_xlsx(path)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: design table .xlsx: %s\n" % error)
    try:
        import importXLSX
        doc = App.newDocument("FWDesignTableLink", hidden=True)
        try:
            importXLSX.insert(path, doc.Name)
            sheets = [o for o in doc.Objects if o.TypeId == "Spreadsheet::Sheet"]
            if not sheets:
                return None
            s = sheets[0]
            out = {}
            for cell in s.getUsedCells():
                import re
                m = re.match(r"([A-Z]+)(\d+)$", cell)
                if not m:
                    continue
                col = 0
                for ch in m.group(1):
                    col = col * 26 + ord(ch) - 64
                out.setdefault(int(m.group(2)) - 1, {})[col - 1] = str(s.getContents(cell)).lstrip("'")
            n_rows = max(out) + 1 if out else 0
            n_cols = max((max(r) for r in out.values()), default=-1) + 1
            return [[out.get(r, {}).get(c, "") for c in range(n_cols)] for r in range(n_rows)]
        finally:
            App.closeDocument(doc.Name)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: design table link: %s\n" % error)
        return None


# --------------------------------------------------------------------------- the boxes
class _WrapLabel(QtWidgets.QLabel):
    """The text of a check box or option button, word-wrapped beside it (a long one widened the PropertyManager pane
    and moved the graphics area); a click on it works the button, as a click on its own text does."""

    def __init__(self, button, text):
        super().__init__(text)
        self.button = button
        self.setWordWrap(True)
        self.setBuddy(button)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)

    def mouseReleaseEvent(self, event):
        if self.button.isEnabled() and event.button() == QtCore.Qt.LeftButton:
            if isinstance(self.button, QtWidgets.QRadioButton):
                self.button.setChecked(True)
            else:
                self.button.toggle()
        super().mouseReleaseEvent(event)


def _wrapped(button, text):
    """A row: the button with no text of its own, then its text wrapped to the pane's width."""
    button.setAccessibleName(text)
    row = QtWidgets.QWidget()
    h = QtWidgets.QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    h.addWidget(button, 0, QtCore.Qt.AlignTop)
    label = _WrapLabel(button, text)
    label.setObjectName(button.objectName() + "Text")
    h.addWidget(label, 1)
    button.setProperty("fwWrappedText", text)
    return row


class Boxes:
    """The three boxes, added to a PropertyManager's form layout."""

    def __init__(self, lay, sheet=None, path_edit=None):
        opts = options(sheet)
        self.path_edit = path_edit
        self.link = QtWidgets.QCheckBox("Link to file")
        self.link.setObjectName("SWDesignTableLink")
        self.link.setChecked(bool(opts.get("link")))
        lay.addRow(self.link)
        control = QtWidgets.QGroupBox("Edit Control")
        g = QtWidgets.QVBoxLayout(control)
        self.allow = QtWidgets.QRadioButton()
        self.block = QtWidgets.QRadioButton()
        self.allow.setObjectName("SWDesignTableAllow")
        self.block.setObjectName("SWDesignTableBlock")
        (self.block if opts.get("control") == "block" else self.allow).setChecked(True)
        g.addWidget(_wrapped(self.allow, "Allow model edits to update the design table"))
        g.addWidget(_wrapped(self.block, "Block model edits that would update the design table"))
        lay.addRow(control)
        box = QtWidgets.QGroupBox("Options")
        g = QtWidgets.QVBoxLayout(box)
        intro = QtWidgets.QLabel("Allow new parameters / configurations to be added to the table:")
        intro.setWordWrap(True)
        intro.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        g.addWidget(intro)
        self.new_parameters = QtWidgets.QCheckBox("New parameters")
        self.new_configurations = QtWidgets.QCheckBox("New configurations")
        self.warn = QtWidgets.QCheckBox("Warn when updating design table")
        for w, key in ((self.new_parameters, "new_parameters"), (self.new_configurations, "new_configurations"),
                       (self.warn, "warn")):
            w.setObjectName("SWDesignTable_" + key)
            w.setChecked(_on(opts, key))
            g.addWidget(w)
        self.dropdowns = QtWidgets.QCheckBox()
        self.dropdowns.setObjectName("SWDesignTable_dropdowns")
        self.dropdowns.setToolTip("Edit Table: cells that take a few values (suppression state, material) get a list to pick from")
        self.dropdowns.setChecked(_on(opts, "dropdowns"))
        g.addWidget(_wrapped(self.dropdowns, DROPDOWNS))
        lay.addRow(box)

    def values(self):
        path = self.path_edit.text().strip() if self.path_edit is not None else ""
        return {"link": path if self.link.isChecked() else "", "control": "block" if self.block.isChecked() else "allow",
                "new_parameters": self.new_parameters.isChecked(),
                "new_configurations": self.new_configurations.isChecked(), "warn": self.warn.isChecked(),
                "dropdowns": self.dropdowns.isChecked()}


class EditPanel:
    """Edit Feature on the design table: Source (the linked file, Reload), Edit Control, Options."""

    def __init__(self, doc):
        self.doc = doc
        self.sheet = _sheet(doc)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Design Table")
        self.form.setObjectName("SWDesignTableEditPM")
        self.form.setProperty("swstyle_pm_title", "Design Table")
        self.form.setProperty("swstyle_pm_icon", "TABLES_DESIGN_TABLE")
        lay = QtWidgets.QFormLayout(self.form)
        source = QtWidgets.QGroupBox("Source")
        g = QtWidgets.QHBoxLayout(source)
        self.path = QtWidgets.QLineEdit(options(self.sheet).get("link", ""))
        self.path.setObjectName("SWDesignTablePath")
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        reload_ = QtWidgets.QPushButton("Reload")
        reload_.setObjectName("SWDesignTableReload")
        reload_.clicked.connect(lambda: reload_link(self.sheet, force=True))
        g.addWidget(self.path)
        g.addWidget(browse)
        g.addWidget(reload_)
        lay.addRow(source)
        self.boxes = Boxes(lay, self.sheet, self.path)

    def _browse(self):
        p = QtWidgets.QFileDialog.getOpenFileName(self.form, "Design table", "", "Tables (*.xlsx *.csv)")[0]
        if p:
            self.path.setText(p)
            self.boxes.link.setChecked(True)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        set_options(self.sheet, **self.boxes.values())
        reload_link(self.sheet)
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


# --------------------------------------------------------------------------- cell drop-down lists
def choices(sheet, row, column):
    """[(shown text, stored value)] for a table cell that takes a few values, else None. Row 1 holds
    the column names (aliases), the configurations' rows are below it."""
    if row < 2 or column < 1:
        return None
    from . import configs
    try:
        alias = sheet.getAlias("%s1" % _col(column)) or ""
    except Exception as _fw_err:
        _fw_log("dtoptions.py:362", _fw_err)
        return None
    if alias.startswith((configs.SUPPRESS, configs.COMP)) or alias == configs.SUPPRESS_NEW:
        return list(SUPPRESSION)
    if alias == configs.BOM_MODE:
        return [(m, m) for m in configs.BOM_MODES]
    if alias == "Material":
        try:
            from . import configtable
            return [(n, n) for n in configtable.material_names()]
        except Exception as _fw_err:
            _fw_log("dtoptions.py:373", _fw_err)
            return None
    return None


class _Dropdowns(QtCore.QObject):
    """The design table's list cells: a double-click (or F2 / Enter) on one opens a drop-down list over
    it; every other cell edits as FreeCAD's sheet edits it (its own cell editor stays in place)."""

    def __init__(self, sheet, table):
        super().__init__(table)
        self.sheet, self.table = sheet, table
        self.box = None
        table.viewport().installEventFilter(self)
        table.installEventFilter(self)

    def remove(self):
        try:
            self.table.viewport().removeEventFilter(self)
            self.table.removeEventFilter(self)
        except RuntimeError as _fw_err:
            _fw_log("dtoptions.py:378", _fw_err)
        self._close()

    def eventFilter(self, obj, event):
        t = event.type()
        index = None
        if t == QtCore.QEvent.MouseButtonDblClick and obj is self.table.viewport():
            index = self.table.indexAt(event.position().toPoint())
        elif t == QtCore.QEvent.KeyPress and obj is self.table and event.key() in (
                QtCore.Qt.Key_F2, QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            index = self.table.currentIndex()
        if index is None or not index.isValid():
            return False
        items = choices(self.sheet, index.row() + 1, index.column())
        if not items:
            return False
        self.open(index, items)
        return True

    def open(self, index, items=None):
        items = items or choices(self.sheet, index.row() + 1, index.column())
        if not items:
            return None
        self._close()
        cell = "%s%d" % (_col(index.column()), index.row() + 1)
        box = QtWidgets.QComboBox(self.table.viewport())
        box.setObjectName("SWDesignTableCellList")
        for text, value in items:
            box.addItem(text, value)
        try:
            now = str(self.sheet.getContents(cell)).lstrip("'=")
        except Exception:
            now = ""
        i = box.findData(now)
        box.setCurrentIndex(i if i >= 0 else 0)
        box.setGeometry(self.table.visualRect(index))
        box.activated.connect(lambda _i, b=box, c=cell: self._commit(b, c))
        box.show()
        box.setFocus()
        self.box = box
        if App.GuiUp and not getattr(self, "quiet", False):
            box.showPopup()
        return box

    def _commit(self, box, cell):
        value = box.currentData()
        try:
            if value is not None and str(self.sheet.getContents(cell)).lstrip("'=") != str(value):
                self.sheet.set(cell, str(value))
                self.sheet.Document.recompute()
        finally:
            QtCore.QTimer.singleShot(0, self._close)

    def _close(self):
        if self.box is not None:
            try:
                self.box.hide()
                self.box.deleteLater()
            except RuntimeError as _fw_err:
                _fw_log("dtoptions.py:437", _fw_err)
        self.box = None


def sheet_table(sheet):
    """The QTableView of sheet's own window, when it is open."""
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    if mdi is None:
        return None
    for sub in mdi.subWindowList():
        w = sub.widget()
        if w is None or w.metaObject().className() != "SpreadsheetGui::SheetView":
            continue
        title = w.windowTitle()
        if sheet.Label not in title and sheet.Name not in title:
            continue
        table = w.findChild(QtWidgets.QTableView)
        if table is not None:
            return table
        # FreeCAD 1.1 draws the sheet's table inside a zoomable QGraphicsView (a proxy widget), so it
        # is not a child of the window: find it among the application's widgets by what it shows
        for t in QtWidgets.QApplication.allWidgets():
            try:
                if t.metaObject().className() != "SpreadsheetGui::SheetTableView":
                    continue
                if not isinstance(t, QtWidgets.QTableView):
                    continue
                if _shows(t, sheet):
                    return t
            except RuntimeError:
                continue
    return None


def _shows(table, sheet):
    """True when table's cells are sheet's (the column A names of its first rows match)."""
    model = table.model()
    if model is None:
        return False
    for r in range(1, 6):
        want = str(sheet.getContents("A%d" % (r + 1)) or "").lstrip("'=")
        got = model.data(model.index(r, 0))
        if want and str(got or "") != want:
            return False
        if want:
            return True
    return False


def install_dropdowns(sheet, tries=8):
    """Edit Table with the option on: the list cells of the table's window get their drop-down lists.
    Off: FreeCAD's own cell editing."""
    if sheet is None or not App.GuiUp:
        return False
    table = sheet_table(sheet)
    if table is None:
        if tries > 0:
            QtCore.QTimer.singleShot(250, lambda: install_dropdowns(sheet, tries - 1))
        return False
    key = (sheet.Document.Name, sheet.Name)
    ours = _LISTS.get(key)
    if ours is not None:
        try:
            ours.table.objectName()
        except RuntimeError:
            ours = _LISTS.pop(key, None) and None      # its window was closed
    if not _on(options(sheet), "dropdowns"):
        if ours is not None:
            ours.remove()
            _LISTS.pop(key, None)
        return False
    if ours is None:
        _LISTS[key] = _Dropdowns(sheet, table)
    return True


_LISTS = {}         # (document, sheet) -> the open table window's drop-down lists


def edit(doc):
    if _sheet(doc) is None:
        return None
    panel = EditPanel(doc)
    Gui.Control.showDialog(panel)
    return panel
