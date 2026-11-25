# SPDX-License-Identifier: LGPL-2.1-or-later
""








import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import evaluate, featurepaint

TITLE = "Find/Modify"
SIZES = ("App::PropertyLength", "App::PropertyDistance", "App::PropertyAngle", "App::PropertyFloat",
         "App::PropertyFloatConstraint", "App::PropertyQuantity", "App::PropertyQuantityConstraint")
DIMENSIONS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
SKETCH = "Sketch dimensions"
def _helper(obj):
    """The add-on's own tree rows (Solid Bodies, Material): not features."""
    return type(getattr(obj, "Proxy", None)).__name__.endswith(("Row", "Folder"))


def _modelling(doc):
    return [o for o in doc.Objects if not _helper(o)]


def _value(v):
    return float(v.Value) if hasattr(v, "Value") else float(v)


def _expressions(obj):
    return {path for path, _text in obj.ExpressionEngine}


def entries(doc, kind=None, low=None, high=None):
    """[(object, key, label, value, locked)]: key is a property name, or ("Constraints", i) for a
    sketch dimension; locked when an expression holds it."""
    import math
    out = []
    for obj in _modelling(doc):
        is_sketch = obj.isDerivedFrom("Sketcher::SketchObject")
        group = SKETCH if is_sketch else obj.TypeId.split("::")[-1]
        if kind and kind != group:
            continue
        held = _expressions(obj)
        if is_sketch:
            for i, c in enumerate(obj.Constraints):
                if c.Type not in DIMENSIONS or not c.Driving:
                    continue
                value = math.degrees(c.Value) if c.Type == "Angle" else c.Value
                name = c.Name or "%s%d" % (c.Type, i + 1)
                out.append((obj, ("Constraints", i), name, value,
                            ".Constraints.%s" % c.Name in held or ".Constraints[%d]" % i in held))
            continue
        for name in featurepaint.parameters(obj):
            if obj.getTypeIdOfProperty(name) not in SIZES:
                continue
            try:
                value = _value(getattr(obj, name))
            except Exception:
                continue
            out.append((obj, name, featurepaint.words(name), value, name in held))
    return [e for e in out if (low is None or e[3] >= low - 1e-9) and (high is None or e[3] <= high + 1e-9)]


def kinds(doc):
    found = []
    for obj in _modelling(doc):
        group = SKETCH if obj.isDerivedFrom("Sketcher::SketchObject") else obj.TypeId.split("::")[-1]
        if group not in found and (group == SKETCH or any(
                obj.getTypeIdOfProperty(n) in SIZES for n in featurepaint.parameters(obj))):
            found.append(group)
    return sorted(found)


def new_value(old, how, amount):
    if how == "add":
        return old + amount
    if how == "scale":
        return old * amount
    return amount


def modify(items, how, amount):
    """Changes each (object, key, label, value, locked) not locked; how many changed."""
    import math
    count = 0
    for obj, key, _label, value, locked in items:
        if locked:
            continue
        v = new_value(value, how, amount)
        if isinstance(key, tuple):
            c = obj.Constraints[key[1]]
            obj.setDatum(key[1], App.Units.Quantity("%.12g deg" % v) if c.Type == "Angle" else v)
        else:
            unit = getattr(getattr(obj, key), "Unit", None)
            if unit is not None and obj.getTypeIdOfProperty(key) == "App::PropertyAngle":
                setattr(obj, key, App.Units.Quantity("%.12g deg" % v))
            else:
                setattr(obj, key, v)
        count += 1
    return count


class FindModifyWindow(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle(TITLE)
        self.setObjectName("SWEvaluate_FindModify")
        self.resize(620, 520)
        lay = QtWidgets.QVBoxLayout(self)
        find = QtWidgets.QGroupBox("Find")
        form = QtWidgets.QFormLayout(find)
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("SWFindKind")
        form.addRow("Feature type:", self.kind)
        self.low = self._number("SWFindFrom", 0.0)
        self.high = self._number("SWFindTo", 1000.0)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.low)
        row.addWidget(QtWidgets.QLabel("to"))
        row.addWidget(self.high)
        form.addRow("Value from:", row)
        self.find = QtWidgets.QPushButton("Find")
        self.find.setObjectName("SWFindRun")
        self.find.clicked.connect(self.refresh)
        form.addRow(self.find)
        lay.addWidget(find)
        self.table = QtWidgets.QTreeWidget()
        self.table.setObjectName("SWFindResults")
        self.table.setHeaderLabels(["Feature", "Size", "Value"])
        self.table.setRootIsDecorated(False)
        lay.addWidget(self.table, 1)
        mod = QtWidgets.QGroupBox("Modify")
        mrow = QtWidgets.QHBoxLayout(mod)
        self.how = QtWidgets.QComboBox()
        self.how.setObjectName("SWModifyHow")
        self.how.addItem("Set to", "set")
        self.how.addItem("Add", "add")
        self.how.addItem("Multiply by", "scale")
        self.amount = self._number("SWModifyAmount", 1.0)
        self.apply = QtWidgets.QPushButton("Modify")
        self.apply.setObjectName("SWModifyRun")
        self.apply.clicked.connect(self.modify)
        mrow.addWidget(self.how)
        mrow.addWidget(self.amount)
        mrow.addWidget(self.apply)
        mrow.addStretch(1)
        lay.addWidget(mod)
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        lay.addWidget(close, 0, QtCore.Qt.AlignRight)
        self.found = []
        self.fill_kinds()

    def _number(self, name, value):
        box = QtWidgets.QDoubleSpinBox()
        box.setObjectName(name)
        box.setRange(-1e9, 1e9)
        box.setDecimals(3)
        box.setValue(value)
        return box

    def fill_kinds(self):
        doc = App.ActiveDocument
        self.kind.clear()
        self.kind.addItem("All", "")
        for k in kinds(doc) if doc else []:
            self.kind.addItem(k, k)

    def refresh(self):
        doc = App.ActiveDocument
        self.table.clear()
        if doc is None:
            self.found = []
            return
        self.found = entries(doc, self.kind.currentData() or None, self.low.value(), self.high.value())
        for obj, key, label, value, locked in self.found:
            item = QtWidgets.QTreeWidgetItem([obj.Label, label, "%.3f%s" % (value, "  (expression)" if locked else "")])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(0, QtCore.Qt.Unchecked if locked else QtCore.Qt.Checked)
            if locked:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEnabled)
            self.table.addTopLevelItem(item)
        for i in range(3):
            self.table.resizeColumnToContents(i)
        self.summary.setText("%d sizes found." % len(self.found))

    def chosen(self):
        return [e for i, e in enumerate(self.found)
                if self.table.topLevelItem(i).checkState(0) == QtCore.Qt.Checked]

    def modify(self):
        doc = App.ActiveDocument
        items = self.chosen()
        if doc is None or not items:
            self.summary.setText("Find the sizes to change first, and tick them.")
            return
        doc.openTransaction(TITLE)
        try:
            count = modify(items, self.how.currentData(), self.amount.value())
            doc.recompute()
        finally:
            doc.commitTransaction()
        self.refresh()
        self.summary.setText("%d sizes changed." % count)

    def closeEvent(self, event):
        evaluate._OPEN.pop(type(self).__name__, None)
        super().closeEvent(event)


@evaluate.command("SWStyle_FindModify", TITLE,
                  "Finds the part's sizes by feature type and value, and changes them all at once.")
def find_modify():
    win = evaluate._OPEN.get(FindModifyWindow.__name__)
    if win is None or not win.isVisible():
        win = FindModifyWindow()
        evaluate._OPEN[FindModifyWindow.__name__] = win
    else:
        win.fill_kinds()
    win.show()
    win.raise_()
    win.activateWindow()
    return win


def register():
    if Gui.Command.get("SWStyle_FindModify") is None:
        Gui.addCommand("SWStyle_FindModify", evaluate._Cmd("SWStyle_FindModify"))
