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

import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from . import contextbar, sketchtoolpm

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/EquationCurve"
EXPLICIT, PARAMETRIC = "Explicit", "Parametric"
DEFAULTS = {EXPLICIT: ("10*sin(x/5)", "", "0", "50"), PARAMETRIC: ("20*cos(t)", "20*sin(t)", "0", "pi")}


def _params():
    return App.ParamGet(PARAMS)


class EquationCurvePage(sketchtoolpm.ToolPage):
    TITLE = "Equation Driven Curve"
    ICON = "SKETCH_EQUATION_CURVE"
    PIXMAP = "Sketcher_CreateBSpline"

    def build(self):
        p = _params()
        self._original = (len(self.sketch.Geometry), len(self.sketch.Constraints))
        self.curve = None
        self._filling = True
        g = self.group("Message")
        label = QtWidgets.QLabel("Enter an equation, the start and end values, and click OK.", g.body)
        label.setWordWrap(True)
        g.content.addWidget(label)
        g = self.group("Equation Type")
        self.explicit = QtWidgets.QRadioButton(EXPLICIT, g.body)
        self.explicit.setObjectName("SWEquationExplicit")
        self.parametric = QtWidgets.QRadioButton(PARAMETRIC, g.body)
        self.parametric.setObjectName("SWEquationParametric")
        kind = p.GetString("Type", EXPLICIT)
        (self.parametric if kind == PARAMETRIC else self.explicit).setChecked(True)
        g.content.addWidget(self.explicit)
        g.content.addWidget(self.parametric)
        g = self.group("Parameters")
        form = QtWidgets.QFormLayout()
        self.e1 = QtWidgets.QLineEdit(g.body)
        self.e1.setObjectName("SWEquation1")
        self.e2 = QtWidgets.QLineEdit(g.body)
        self.e2.setObjectName("SWEquation2")
        self.a = QtWidgets.QLineEdit(g.body)
        self.a.setObjectName("SWEquationStart")
        self.b = QtWidgets.QLineEdit(g.body)
        self.b.setObjectName("SWEquationEnd")
        self.l1 = QtWidgets.QLabel("", g.body)
        self.l2 = QtWidgets.QLabel("", g.body)
        self.la = QtWidgets.QLabel("", g.body)
        self.lb = QtWidgets.QLabel("", g.body)
        form.addRow(self.l1, self.e1)
        form.addRow(self.l2, self.e2)
        form.addRow(self.la, self.a)
        form.addRow(self.lb, self.b)
        g.content.addLayout(form)
        self._remembered = {}
        for k in (EXPLICIT, PARAMETRIC):
            d = DEFAULTS[k]
            self._remembered[k] = tuple(p.GetString("%s%d" % (k, i), d[i]) for i in range(4))
        self._load(kind)
        for w in (self.e1, self.e2, self.a, self.b):
            w.editingFinished.connect(self.changed)
        self.explicit.toggled.connect(self._type_changed)
        self._filling = False
        self.changed()

    def kind(self):
        return PARAMETRIC if self.parametric.isChecked() else EXPLICIT

    def _load(self, kind):
        e1, e2, a, b = self._remembered[kind]
        self.e1.setText(e1)
        self.e2.setText(e2)
        self.a.setText(a)
        self.b.setText(b)
        par = kind == PARAMETRIC
        self.l1.setText("x(t) =" if par else "y(x) =")
        self.l2.setText("y(t) =")
        self.e2.setVisible(par)
        self.l2.setVisible(par)
        self.la.setText("t1:" if par else "x1:")
        self.lb.setText("t2:" if par else "x2:")

    def _type_changed(self, *args):
        if self._filling:
            return
        other = EXPLICIT if self.kind() == PARAMETRIC else PARAMETRIC
        self._remembered[other] = (self.e1.text(), self.e2.text(), self.a.text(), self.b.text())
        self._filling = True
        self._load(self.kind())
        self._filling = False
        self.changed()

    def undo_work(self):
        self.curve = None
        super().undo_work()
        orig = getattr(self, "_original", None)
        if orig is None:
            return
        sk = self.sketch
        try:
            extra = list(range(orig[0], len(sk.Geometry)))
            if extra:
                sk.delGeometries(extra)
        except Exception as _fw_err:
            _fw_log("equationpm.py:127", _fw_err)

    def values(self):
        from .sketchextras import _evaluator
        lo = _evaluator(self.a.text(), "x")(0)
        hi = _evaluator(self.b.text(), "x")(0)
        exprs = (self.e1.text(),) if self.kind() == EXPLICIT else (self.e1.text(), self.e2.text())
        return lo, hi, exprs

    def changed(self, *args):
        if self._filling:
            return
        from .sketchextras import add_equation_curve
        self.undo_work()
        try:
            lo, hi, exprs = self.values()
        except Exception as error:
            self.show_note("Check the equation: %s" % error, True)
            return
        self.begin()
        try:
            self.curve = add_equation_curve(self.sketch, self.kind().lower(), exprs, lo, hi)
        except Exception as error:
            self.show_note("Could not make the curve: %s" % error, True)
            return
        self.show_note("")
        sketchtoolpm._refresh(self.sketch)

    def finish(self):
        p = _params()
        p.SetString("Type", self.kind())
        self._remembered[self.kind()] = (self.e1.text(), self.e2.text(), self.a.text(), self.b.text())
        for k, vals in self._remembered.items():
            for i, v in enumerate(vals):
                p.SetString("%s%d" % (k, i), v)
        if self.curve is None:
            self.changed()


def open_page():
    sketch = contextbar.sketch_in_edit()
    if sketch is not None:
        return sketchtoolpm.open_page(EquationCurvePage(sketch))
