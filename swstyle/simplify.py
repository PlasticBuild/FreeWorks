# SPDX-License-Identifier: LGPL-2.1-or-later
""










import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

FEATURE_TYPES = {"PartDesign::Fillet": "Radius", "PartDesign::Chamfer": "Size", "PartDesign::Hole": "Diameter",
                 "Part::Fillet": None, "Part::Chamfer": None}
TEXT_PROPS = ("Text", "LabelText", "String")
OPEN = {}


def _assembly(doc):
    try:
        from . import asmcore as ac
        return ac.assembly_of(doc)
    except Exception:
        return None


def _diag(shape):
    try:
        return shape.BoundBox.DiagonalLength
    except Exception:
        return 0.0


def _size(obj):
    prop = FEATURE_TYPES.get(obj.TypeId)
    if prop:
        v = getattr(obj, prop, None)
        return float(getattr(v, "Value", v or 0) or 0)
    edges = getattr(obj, "Edges", None)        # Part::Fillet/Chamfer: [(edge, r1, r2)]
    if edges:
        try:
            return max(float(e[1]) for e in edges)
        except Exception:
            return 0.0
    return 0.0


def model_size(doc):
    asm = _assembly(doc)
    if asm is not None:
        from . import asmcore as ac
        shapes = [c.Shape for c in ac.components(asm) if hasattr(c, "Shape") and not c.Shape.isNull()]
    else:
        shapes = [o.Shape for o in doc.Objects if hasattr(o, "Shape") and o.Visibility and not o.Shape.isNull()
                  and o.Shape.Solids]
    if not shapes:
        return 0.0
    bb = shapes[0].BoundBox
    for s in shapes[1:]:
        bb.add(s.BoundBox)
    return bb.DiagonalLength


def find(doc, factor):
    """[(object, kind, size)] smaller than factor x the model's size."""
    limit = float(factor) * model_size(doc)
    asm = _assembly(doc)
    out = []
    if asm is not None:
        from . import asmcore as ac, asmcomp
        for c in ac.components(asm):
            if c.TypeId != "App::Link" or asmcomp.is_suppressed(c):
                continue
            d = _diag(c.Shape)
            if 0 < d < limit:
                out.append((c, "Component", d))
        return out
    for o in doc.Objects:
        if o.TypeId in FEATURE_TYPES and not getattr(o, "Suppressed", False):
            s = _size(o)
            if 0 < s < limit:
                out.append((o, o.TypeId.split("::")[1], s))
    return out


def suppress(doc, objs):
    asm = _assembly(doc)
    doc.openTransaction("Simplify")
    try:
        n = 0
        for o in objs:
            if asm is not None:
                from . import asmcomp
                n += bool(asmcomp.suppress(o, True))
            elif hasattr(o, "Suppressed"):
                o.Suppressed = True
                n += 1
        doc.recompute()
    finally:
        doc.commitTransaction()
    if asm is not None:
        from . import asmcore as ac
        ac.solve(asm)
    return n


class SimplifyWindow(QtWidgets.QDialog):
    def __init__(self, doc):
        super().__init__(Gui.getMainWindow())
        self.setObjectName("SWSimplify")
        self.setWindowTitle("Simplify")
        self.doc = doc
        self.found = []
        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Simplification factor:", self))
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self.slider.setObjectName("SWSimplifyFactorSlider")
        self.slider.setRange(0, 100)
        self.factor = QtWidgets.QDoubleSpinBox(self)
        self.factor.setObjectName("SWSimplifyFactor")
        self.factor.setRange(0.0, 1.0)
        self.factor.setSingleStep(0.01)
        self.factor.setDecimals(2)
        self.factor.setValue(0.1)
        self.slider.setValue(10)
        self.slider.valueChanged.connect(lambda v: self.factor.setValue(v / 100.0))
        self.factor.valueChanged.connect(lambda v: self.slider.setValue(int(round(v * 100))))
        row.addWidget(self.slider, 1)
        row.addWidget(self.factor)
        lay.addLayout(row)
        self.find_btn = QtWidgets.QPushButton("Find Now", self)
        self.find_btn.setObjectName("SWSimplifyFind")
        self.find_btn.clicked.connect(self.find_now)
        lay.addWidget(self.find_btn, 0, QtCore.Qt.AlignLeft)
        self.list = QtWidgets.QTreeWidget(self)
        self.list.setObjectName("SWSimplifyResults")
        self.list.setHeaderLabels(["Name", "Type", "Size"])
        self.list.setRootIsDecorated(False)
        lay.addWidget(self.list, 1)
        row = QtWidgets.QHBoxLayout()
        self.supp = QtWidgets.QPushButton("Suppress", self)
        self.supp.setObjectName("SWSimplifySuppress")
        self.supp.clicked.connect(self.suppress)
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.close)
        row.addWidget(self.supp)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self.supp.setEnabled(False)

    def find_now(self):
        self.found = find(self.doc, self.factor.value())
        self.list.clear()
        for o, kind, size in self.found:
            it = QtWidgets.QTreeWidgetItem([o.Label, kind, "%.2f mm" % size])
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(0, QtCore.Qt.Checked)
            self.list.addTopLevelItem(it)
        for i in range(3):
            self.list.resizeColumnToContents(i)
        self.supp.setEnabled(bool(self.found))
        return self.found

    def suppress(self):
        picked = [self.found[i][0] for i in range(self.list.topLevelItemCount())
                  if self.list.topLevelItem(i).checkState(0) == QtCore.Qt.Checked]
        n = suppress(self.doc, picked) if picked else 0
        self.find_now()
        return n

    def closeEvent(self, event):
        OPEN.pop("simplify", None)
        super().closeEvent(event)


# ---------------------------------------------------------------------- Find and Replace Annotation
def annotations(doc):
    """[(object, property)] of the document's text annotations."""
    out = []
    for o in doc.Objects:
        for p in TEXT_PROPS:
            if p in o.PropertiesList and o.getTypeIdOfProperty(p) in ("App::PropertyString", "App::PropertyStringList"):
                out.append((o, p))
                break
    return out


def _get(o, p):
    v = getattr(o, p)
    return "\n".join(v) if isinstance(v, (list, tuple)) else str(v)


def _set(o, p, text):
    if o.getTypeIdOfProperty(p) == "App::PropertyStringList":
        setattr(o, p, text.split("\n"))
    else:
        setattr(o, p, text)


def _replace(text, what, with_, case):
    if case:
        return text.replace(what, with_)
    import re
    return re.sub(re.escape(what), lambda m: with_, text, flags=re.IGNORECASE)


def matches(doc, what, case=False):
    if not what:
        return []
    w = what if case else what.lower()
    return [(o, p) for o, p in annotations(doc) if w in (_get(o, p) if case else _get(o, p).lower())]


class FindReplaceWindow(QtWidgets.QDialog):
    def __init__(self, doc):
        super().__init__(Gui.getMainWindow())
        self.setObjectName("SWFindReplaceAnnotation")
        self.setWindowTitle("Find and Replace Annotation")
        self.doc = doc
        self.index = -1
        lay = QtWidgets.QFormLayout(self)
        self.what = QtWidgets.QLineEdit(self)
        self.what.setObjectName("SWFindWhat")
        self.with_ = QtWidgets.QLineEdit(self)
        self.with_.setObjectName("SWReplaceWith")
        self.case = QtWidgets.QCheckBox("Match case", self)
        lay.addRow("Find what:", self.what)
        lay.addRow("Replace with:", self.with_)
        lay.addRow(self.case)
        row = QtWidgets.QHBoxLayout()
        self.next_btn = QtWidgets.QPushButton("Find Next", self)
        self.rep_btn = QtWidgets.QPushButton("Replace", self)
        self.all_btn = QtWidgets.QPushButton("Replace All", self)
        close = QtWidgets.QPushButton("Close", self)
        for b in (self.next_btn, self.rep_btn, self.all_btn, close):
            row.addWidget(b)
        lay.addRow(row)
        self.info = QtWidgets.QLabel("", self)
        lay.addRow(self.info)
        self.next_btn.clicked.connect(self.find_next)
        self.rep_btn.clicked.connect(self.replace)
        self.all_btn.clicked.connect(self.replace_all)
        close.clicked.connect(self.close)
        self.current = None

    def find_next(self):
        hits = matches(self.doc, self.what.text(), self.case.isChecked())
        if not hits:
            self.current = None
            self.info.setText("Not found.")
            return None
        self.index = (self.index + 1) % len(hits)
        self.current = hits[self.index]
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.current[0].Name)
        self.info.setText("%s (%d of %d)" % (self.current[0].Label, self.index + 1, len(hits)))
        return self.current

    def replace(self):
        if self.current is None and self.find_next() is None:
            return 0
        o, p = self.current
        self.doc.openTransaction("Replace Annotation")
        try:
            _set(o, p, _replace(_get(o, p), self.what.text(), self.with_.text(), self.case.isChecked()))
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise
        self.doc.commitTransaction()
        self.doc.recompute()
        self.current, self.index = None, self.index - 1
        self.find_next()
        return 1

    def replace_all(self):
        hits = matches(self.doc, self.what.text(), self.case.isChecked())
        if not hits:
            self.info.setText("Not found.")
            return 0
        self.doc.openTransaction("Replace All Annotations")
        try:
            for o, p in hits:
                _set(o, p, _replace(_get(o, p), self.what.text(), self.with_.text(), self.case.isChecked()))
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise
        self.doc.commitTransaction()
        self.doc.recompute()
        self.info.setText("%d replaced." % len(hits))
        self.current = None
        return len(hits)

    def closeEvent(self, event):
        OPEN.pop("replace", None)
        super().closeEvent(event)


def open_simplify(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    w = SimplifyWindow(doc)
    OPEN["simplify"] = w
    w.show()
    return w


def open_find_replace(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    w = FindReplaceWindow(doc)
    OPEN["replace"] = w
    w.show()
    return w
