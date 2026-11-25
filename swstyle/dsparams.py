# SPDX-License-Identifier: LGPL-2.1-or-later
""








import json

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import findmodify

TITLE = "Parameters"
META = "FreeWorksDesignStudyParameters"
CATEGORIES = ("Model Dimension",)
COLUMNS = ("Name", "Category", "Parameter Link", "Value", "Units", "Comment", "Linked")
ADD_ROW = "Click here to add"


def _key_out(key):
    return list(key) if isinstance(key, tuple) else key


def _key_in(key):
    return tuple(key) if isinstance(key, list) else key


def load(doc):
    """[{name, category, object, key, comment}] kept with the document."""
    if doc is None:
        return []
    try:
        raw = doc.Meta.get(META, "")
        items = json.loads(raw) if raw else []
        return [dict(p, key=_key_in(p.get("key"))) for p in items if isinstance(p, dict)]
    except Exception:
        return []


def save(doc, params):
    meta = dict(doc.Meta)
    meta[META] = json.dumps([dict(p, key=_key_out(p["key"])) for p in params])
    doc.Meta = meta


def entry_of(doc, param):
    """The findmodify entry (object, key, label, value, locked) the parameter links to, or None."""
    for e in findmodify.entries(doc):
        if e[0].Name == param.get("object") and e[1] == param.get("key"):
            return e
    return None


def units(entry):
    obj, key = entry[0], entry[1]
    try:
        if isinstance(key, tuple):
            return "deg" if obj.Constraints[key[1]].Type == "Angle" else "mm"
        kind = obj.getTypeIdOfProperty(key)
        if "Angle" in kind:
            return "deg"
        if "Integer" in kind:
            return ""
        return "mm"
    except Exception:
        return ""


def link_text(entry):
    return "%s@%s" % (entry[2], entry[0].Label)


def linked_count(param):
    """How many variables of the open Design Study window use this parameter."""
    try:
        from . import designstudy, evaluate
        win = evaluate._OPEN.get(designstudy.DesignStudyWindow.__name__)
        if win is None:
            return 0
        return sum(1 for (e, _vals) in win.variables if e[0].Name == param.get("object") and e[1] == param.get("key"))
    except Exception:
        return 0


class ParametersDialog(QtWidgets.QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.setWindowTitle(TITLE)
        self.setObjectName("SWDesignStudyParameters")
        self.resize(760, 320)
        self.entries = [e for e in findmodify.entries(doc) if not e[4]]
        self.params = [p for p in load(doc) if entry_of(doc, p) is not None]
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(0, len(COLUMNS), self)
        self.table.setObjectName("SWDesignStudyParametersTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.cellClicked.connect(self._clicked)
        self.table.installEventFilter(self)
        lay.addWidget(self.table, 1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
                                             | QtWidgets.QDialogButtonBox.Help, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.helpRequested.connect(self._help)
        lay.addWidget(buttons)
        self.message = QtWidgets.QLabel("", self)
        self.message.setObjectName("SWDesignStudyParametersMessage")
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        self._fill()

    # ---------------------------------------------------------------- rows
    def _fill(self):
        self.table.setRowCount(0)
        for p in self.params:
            self._add_row(p)
        r = self.table.rowCount()
        self.table.insertRow(r)
        add = QtWidgets.QTableWidgetItem(ADD_ROW)
        add.setFlags(QtCore.Qt.ItemIsEnabled)
        role = getattr(QtGui.QPalette, "PlaceholderText", None) or QtGui.QPalette.Mid
        add.setForeground(self.palette().color(role))
        self.table.setItem(r, 0, add)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, max(120, self.table.columnWidth(0)))

    def _add_row(self, p):
        r = self.table.rowCount()
        self.table.insertRow(r)
        name = QtWidgets.QTableWidgetItem(p.get("name", ""))
        self.table.setItem(r, 0, name)
        cat = QtWidgets.QComboBox()
        cat.addItems(CATEGORIES)
        cat.setCurrentText(p.get("category", CATEGORIES[0]))
        self.table.setCellWidget(r, 1, cat)
        link = QtWidgets.QComboBox()
        link.setObjectName("SWDesignStudyParameterLink")
        for e in self.entries:
            link.addItem(link_text(e))
        current = [i for i, e in enumerate(self.entries) if e[0].Name == p.get("object") and e[1] == p.get("key")]
        if current:
            link.setCurrentIndex(current[0])
        link.currentIndexChanged.connect(lambda i, row=r: self._linked(row, i))
        self.table.setCellWidget(r, 2, link)
        e = self.entries[link.currentIndex()] if self.entries and link.currentIndex() >= 0 else None
        value = QtWidgets.QDoubleSpinBox()
        value.setDecimals(3)
        value.setRange(-1e9, 1e9)
        value.setValue(e[3] if e else 0.0)
        value.setProperty("sw_original", e[3] if e else 0.0)
        self.table.setCellWidget(r, 3, value)
        unit = QtWidgets.QTableWidgetItem(units(e) if e else "")
        unit.setFlags(QtCore.Qt.ItemIsEnabled)
        self.table.setItem(r, 4, unit)
        self.table.setItem(r, 5, QtWidgets.QTableWidgetItem(p.get("comment", "")))
        linked = QtWidgets.QTableWidgetItem(str(linked_count(p)))
        linked.setFlags(QtCore.Qt.ItemIsEnabled)
        self.table.setItem(r, 6, linked)

    def _linked(self, row, index):
        if not (0 <= index < len(self.entries)):
            return
        e = self.entries[index]
        value = self.table.cellWidget(row, 3)
        value.setValue(e[3])
        value.setProperty("sw_original", e[3])
        self.table.item(row, 4).setText(units(e))

    def _clicked(self, row, col):
        if row == self.table.rowCount() - 1 and col == 0:
            self.add_parameter()

    def add_parameter(self):
        if not self.entries:
            self.message.setText("This document has no dimensions to link to: add a sketch dimension or a feature first.")
            return
        self._collect()
        used = {p["name"] for p in self.params}
        n = 1
        while "Parameter%d" % n in used:
            n += 1
        e = self.entries[0]
        self.params.append({"name": "Parameter%d" % n, "category": CATEGORIES[0], "object": e[0].Name,
                            "key": e[1], "comment": ""})
        self._fill()
        self.table.setCurrentCell(len(self.params) - 1, 0)
        self.table.editItem(self.table.item(len(self.params) - 1, 0))

    def delete_row(self, row):
        if 0 <= row < len(self.params):
            self._collect()
            del self.params[row]
            self._fill()

    def _menu(self, pos):
        row = self.table.rowAt(pos.y())
        menu = QtWidgets.QMenu(self)
        if 0 <= row < len(self.params):
            menu.addAction("Delete", lambda: self.delete_row(row))
        menu.addAction("Add Parameter", self.add_parameter)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def eventFilter(self, obj, event):
        if obj is self.table and isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.KeyPress \
                and event.key() == QtCore.Qt.Key_Delete and self.table.state() != QtWidgets.QAbstractItemView.EditingState:
            self.delete_row(self.table.currentRow())
            return True
        return False

    def _collect(self):
        """The table's rows back into self.params (names, links, comments), before a rebuild or OK."""
        out = []
        for r, p in enumerate(self.params):
            q = dict(p)
            name = self.table.item(r, 0)
            q["name"] = name.text().strip() if name is not None else p["name"]
            q["category"] = self.table.cellWidget(r, 1).currentText()
            i = self.table.cellWidget(r, 2).currentIndex()
            if 0 <= i < len(self.entries):
                q["object"], q["key"] = self.entries[i][0].Name, self.entries[i][1]
            comment = self.table.item(r, 5)
            q["comment"] = comment.text() if comment is not None else ""
            q["_value"] = self.table.cellWidget(r, 3).value()
            q["_original"] = self.table.cellWidget(r, 3).property("sw_original")
            out.append(q)
        self.params = out

    def accept(self):
        self._collect()
        names = [p["name"] for p in self.params]
        if any(not n for n in names):
            self.message.setText("Every parameter needs a name.")
            return
        if len(set(names)) != len(names):
            self.message.setText("Two parameters have the same name: give each its own.")
            return
        changed = []
        for p in self.params:
            e = entry_of(self.doc, p)
            if e is not None and abs(p["_value"] - e[3]) > 1e-9 and abs(p["_value"] - (p["_original"] or 0)) > 1e-9:
                changed.append((e, p["_value"]))
        self.doc.openTransaction(TITLE)
        try:
            save(self.doc, [{k: v for k, v in p.items() if not k.startswith("_")} for p in self.params])
            for e, v in changed:
                findmodify.modify([e], "set", v)
            if changed:
                self.doc.recompute()
        finally:
            self.doc.commitTransaction()
        try:
            from . import designstudy, evaluate
            win = evaluate._OPEN.get(designstudy.DesignStudyWindow.__name__)
            if win is not None and win.isVisible():
                win.fill_sizes()
        except Exception as _fw_err:
            App.Console.PrintLog("FreeCAD: parameters: %s\n" % _fw_err)
        super().accept()

    def _help(self):
        self.message.setText("Name a model dimension here, then pick it by its name in the Design Study's variables. "
                             "Changing a Value changes the model when you press OK.")


def show():
    doc = App.ActiveDocument
    if doc is None:
        return None
    dlg = ParametersDialog(doc)
    dlg.show()
    dlg.raise_()
    return dlg


class _Cmd:
    def GetResources(self):
        return {"Pixmap": "Std_DlgParameter", "MenuText": TITLE,
                "ToolTip": "Names the model's dimensions so a Design Study's variables can use them"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        show()


COMMAND = "SWStyle_DesignParameters"     # Tools > Design Study > Parameters... (insertextras) opens this too


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, _Cmd())
