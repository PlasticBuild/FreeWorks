# SPDX-License-Identifier: LGPL-2.1-or-later
""



import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from . import smbendtable

GROUP = "Sheet Metal"
PROPS = {"SWCustomType": ("App::PropertyString", "K-Factor"), "SWCustomBA": ("App::PropertyFloat", 0.0),
         "SWCustomBD": ("App::PropertyFloat", 0.0), "SWCustomTable": ("App::PropertyString", "")}


def _spin(name, value, low, high, tip):
    s = QtWidgets.QDoubleSpinBox()
    s.setObjectName(name)
    s.setRange(low, high)
    s.setDecimals(4)
    s.setSuffix(" mm")
    s.setValue(value)
    s.setToolTip(tip)
    return s


def add_props(obj):
    for name, (kind, default) in PROPS.items():
        if name not in obj.PropertiesList:
            obj.addProperty(kind, name, GROUP, "Custom Bend Allowance")
            setattr(obj, name, default)


class CustomAllowance:
    """Adds the Bend Allowance, Bend Deduction and table rows under a PM's allowance list and K-Factor box."""

    def __init__(self, combo, kspin, layout, obj, changed):
        self.combo, self.kspin, self.changed = combo, kspin, changed
        self.doc = obj.Document if obj is not None else App.ActiveDocument
        self.busy = True
        get = (lambda n, d: getattr(obj, n, d)) if obj is not None else (lambda n, d: d)
        self.ba = _spin("SWSMBendAllowance", float(get("SWCustomBA", 0.0)), 0.0, 10000.0, "Bend allowance")
        self.bd = _spin("SWSMBendDeduction", float(get("SWCustomBD", 0.0)), -10000.0, 10000.0, "Bend deduction")
        self.ba_label, self.bd_label = QtWidgets.QLabel("BA"), QtWidgets.QLabel("BD")
        self.k_label = layout.labelForField(kspin)
        self.tables = QtWidgets.QComboBox()
        self.tables.setObjectName("SWSMBendTableList")
        self.browse = QtWidgets.QPushButton("Browse...")
        self.browse.setObjectName("SWSMBendTableBrowse")
        layout.addRow(self.ba_label, self.ba)
        layout.addRow(self.bd_label, self.bd)
        layout.addRow(self.tables)
        layout.addRow(self.browse)
        self.table_name = get("SWCustomTable", "")
        combo.setCurrentText(get("SWCustomType", "K-Factor"))
        self._fill()
        combo.currentIndexChanged.connect(self._kind_changed)
        self.tables.currentIndexChanged.connect(self._table_changed)
        for w in (self.ba, self.bd):
            w.valueChanged.connect(self._value_changed)
        self.browse.clicked.connect(self._browse)
        self.busy = False

    def kind(self):
        return self.combo.currentText()

    def _fill(self):
        calc = self.kind() == "Bend Calculation"
        self.tables.blockSignals(True)
        self.tables.clear()
        for t in smbendtable.tables(self.doc):
            if smbendtable.is_calculation(t) == calc:
                self.tables.addItem(t.Label, t.Name)
        i = self.tables.findData(self.table_name)
        self.tables.setCurrentIndex(i if i >= 0 else 0)
        self.table_name = self.tables.currentData() or ""
        self.tables.blockSignals(False)

    def show(self, on):
        kind = self.kind()
        self.combo.setEnabled(on)
        for w, k in ((self.kspin, "K-Factor"), (self.ba, "Bend Allowance"), (self.bd, "Bend Deduction")):
            w.setVisible(kind == k)
            w.setEnabled(on)
        if self.k_label is not None:
            self.k_label.setVisible(kind == "K-Factor")
        self.ba_label.setVisible(kind == "Bend Allowance")
        self.bd_label.setVisible(kind == "Bend Deduction")
        for w in (self.tables, self.browse):
            w.setVisible(kind in ("Bend Table", "Bend Calculation"))
            w.setEnabled(on)

    def _kind_changed(self, *_a):
        if self.busy:
            return
        self._fill()
        self.changed()

    def _table_changed(self, *_a):
        self.table_name = self.tables.currentData() or ""
        if not self.busy:
            self.changed()

    def _value_changed(self, *_a):
        if not self.busy:
            self.changed()

    def _browse(self):
        calc = self.kind() == "Bend Calculation"
        start = smbendtable.sample_calculation_path() if calc else ""
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            Gui.getMainWindow(), "Open Bend Calculation Table" if calc else "Open Bend Table", start,
            "Bend tables (*.xlsx *.csv *.xls)")
        if path:
            self.add_table(path)

    def add_table(self, path):
        table = smbendtable.from_file(self.doc, path)
        self.table_name = table.Name
        self._fill()
        self.changed()
        return table

    def k(self, thickness, radius, angle):
        """The K-Factor the choice gives for a bend (mm, degrees). Raises ValueError for a missing table or a
        value no K-Factor from 0 to 1 can give."""
        kind = self.kind()
        if kind == "K-Factor":
            return self.kspin.value()
        if kind == "Bend Allowance":
            k = smbendtable.k_from_allowance(self.ba.value(), angle, radius, thickness)
        elif kind == "Bend Deduction":
            k = smbendtable.k_of_value("Bend Deduction", self.bd.value(), angle, radius, thickness)
        else:
            obj = self.doc.getObject(self.table_name) if self.table_name else None
            table = smbendtable.table_of(obj) if obj is not None else None
            if table is None:
                raise ValueError("Select a %s, or Browse... for one." % (
                    "bend calculation table" if kind == "Bend Calculation" else "bend table"))
            k = smbendtable.k_from_table(table, thickness, radius, angle)
        if not -1e-9 <= k <= 1 + 1e-9:
            low = smbendtable.allowance_from_k(0.0, angle, radius, thickness)
            high = smbendtable.allowance_from_k(1.0, angle, radius, thickness)
            raise ValueError("This %s is out of range for a %g mm bend radius: the bend allowance must be "
                             "%.3f to %.3f mm." % (kind.lower(), radius, low, high))
        return min(1.0, max(0.0, k))

    def save(self, obj):
        add_props(obj)
        obj.SWCustomType = self.kind()
        obj.SWCustomBA, obj.SWCustomBD = self.ba.value(), self.bd.value()
        obj.SWCustomTable = self.table_name


def thickness_of(root, doc=None):
    """The sheet thickness: the part's Base Flange's (root), else the document's first Base Flange's."""
    v = getattr(root, "Thickness", None) if root is not None else None
    if v is not None:
        return float(getattr(v, "Value", v))
    from . import smbaseflange
    doc = doc or (root.Document if root is not None else App.ActiveDocument)
    for o in doc.Objects if doc is not None else []:
        if smbaseflange.is_base_flange(o) or ("SWKFactor" in o.PropertiesList and "Thickness" in o.PropertiesList):
            v = o.Thickness
            return float(getattr(v, "Value", v))
    return 1.0


def k_for(panel, obj, angle):
    """The K-Factor of a PM's Custom Bend Allowance for its bend; a missing table is kept for report()."""
    panel.allowance_problem = ""
    try:
        radius = panel.radius.value() if hasattr(panel, "radius") else 1.0
        from .smedgeflange import _root
        try:
            root = _root(obj)
        except Exception:
            root = None
        return panel.custom.k(thickness_of(root, obj.Document), radius, angle)
    except ValueError as e:
        panel.allowance_problem = str(e)
        return panel.kfactor.value()


def report(panel):
    """Shows a Custom Bend Allowance problem in the PM's message (after its own report)."""
    text = getattr(panel, "allowance_problem", "") if panel.custom_k.isChecked() else ""
    if text:
        panel.error.setText(text)
        panel.error.setVisible(True)
