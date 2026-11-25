# SPDX-License-Identifier: LGPL-2.1-or-later
""















import itertools

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import evaluate, findmodify

TITLE = "Design Study"
LIMIT = 200


def parse_values(text):
    """'10, 20, 30' -> [10, 20, 30]; 'from to step' ranges come as 'a:b:s'."""
    text = text.strip()
    if ":" in text:
        a, b, s = (float(x) for x in text.split(":"))
        if s <= 0 or b < a:
            raise ValueError("A range needs from <= to and a step above 0")
        out, v = [], a
        while v <= b + 1e-9 and len(out) <= LIMIT:
            out.append(round(v, 9))
            v += s
        return out
    return [float(x) for x in text.replace(";", ",").split(",") if x.strip()]


def _measure(doc):
    vol = area = 0.0
    for obj in evaluate.visible_bodies(doc):
        vol += obj.Shape.Volume
        area += obj.Shape.Area
    return vol, area


def _ok(doc):
    return all("Invalid" not in o.State and "Error" not in o.State for o in doc.Objects)


def run(doc, variables, sensors=()):
    """variables: [(entry, [values])], entry as findmodify.entries gives it; sensors: [(label, study, fn)] from
    simtypes.design_sensors. Returns [(values, volume, area, rebuilt, {sensor: value})], the part left as it was."""
    combos = list(itertools.product(*[vals for _e, vals in variables]))
    if len(combos) > LIMIT:
        raise ValueError("%d scenarios: at most %d" % (len(combos), LIMIT))
    out = []
    before = [(entry, _current(entry)) for entry, _vals in variables]
    doc.openTransaction(TITLE + " run")
    try:
        for combo in combos:
            for (entry, _vals), v in zip(variables, combo):
                findmodify.modify([entry], "set", v)
            doc.recompute()
            vol, area = _measure(doc)
            vals = {}
            if sensors and _ok(doc):
                from . import simtypes
                try:
                    vals = simtypes.measure_sensors(doc, sensors)
                except Exception as error:
                    vals = {"error": str(error)}
            out.append((combo, vol, area, _ok(doc), vals))
    finally:
        doc.abortTransaction()
        for entry, value in before:          # with Undo off the abort keeps the changes
            if abs(_current(entry) - value) > 1e-9:
                findmodify.modify([entry], "set", value)
        doc.recompute()
        if sensors:
            from . import simtypes
            simtypes.rerun(doc, sensors)
    return out


def _current(entry):
    import math
    obj, key = entry[0], entry[1]
    if isinstance(key, tuple):
        c = obj.Constraints[key[1]]
        return math.degrees(c.Value) if c.Type == "Angle" else c.Value
    return findmodify._value(getattr(obj, key))


def apply(doc, variables, combo):
    doc.openTransaction(TITLE)
    try:
        for (entry, _vals), v in zip(variables, combo):
            findmodify.modify([entry], "set", v)
        doc.recompute()
    finally:
        doc.commitTransaction()


class DesignStudyWindow(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle(TITLE)
        self.setObjectName("SWEvaluate_DesignStudy")
        self.resize(720, 560)
        lay = QtWidgets.QVBoxLayout(self)
        box = QtWidgets.QGroupBox("Variables")
        blay = QtWidgets.QVBoxLayout(box)
        row = QtWidgets.QHBoxLayout()
        self.size = QtWidgets.QComboBox()
        self.size.setObjectName("SWStudySize")
        self.values = QtWidgets.QLineEdit()
        self.values.setObjectName("SWStudyValues")
        self.values.setPlaceholderText("10, 20, 30   or   from:to:step")
        self.add = QtWidgets.QPushButton("Add Variable")
        self.add.setObjectName("SWStudyAdd")
        self.add.clicked.connect(self.add_variable)
        self.params = QtWidgets.QPushButton("Parameters...")
        self.params.setObjectName("SWStudyParameters")
        self.params.setToolTip("Names the model's dimensions so the variables can use them")
        self.params.clicked.connect(self.open_parameters)
        row.addWidget(self.size, 2)
        row.addWidget(self.values, 2)
        row.addWidget(self.add)
        row.addWidget(self.params)
        blay.addLayout(row)
        self.vars = QtWidgets.QTreeWidget()
        self.vars.setObjectName("SWStudyVariables")
        self.vars.setHeaderLabels(["Variable", "Values"])
        self.vars.setRootIsDecorated(False)
        self.vars.setFixedHeight(110)
        blay.addWidget(self.vars)
        remove = QtWidgets.QPushButton("Remove Variable")
        remove.clicked.connect(self.remove_variable)
        blay.addWidget(remove, 0, QtCore.Qt.AlignLeft)
        lay.addWidget(box)
        # Constraints and Goals: sensors (mass, volume, the simulation studies' results)
        cg = QtWidgets.QHBoxLayout()
        cbox = QtWidgets.QGroupBox("Constraints")
        cl = QtWidgets.QVBoxLayout(cbox)
        crow = QtWidgets.QHBoxLayout()
        self.c_sensor = QtWidgets.QComboBox()
        self.c_sensor.setObjectName("SWStudyConstraintSensor")
        self.c_cond = QtWidgets.QComboBox()
        self.c_cond.setObjectName("SWStudyConstraintCondition")
        self.c_cond.addItems(["is less than", "is greater than", "is between"])
        self.c_vals = QtWidgets.QLineEdit()
        self.c_vals.setObjectName("SWStudyConstraintValues")
        self.c_vals.setPlaceholderText("value   or   min, max")
        c_add = QtWidgets.QPushButton("Add")
        c_add.setObjectName("SWStudyConstraintAdd")
        c_add.clicked.connect(self.add_constraint)
        for w_ in (self.c_sensor, self.c_cond, self.c_vals, c_add):
            crow.addWidget(w_)
        cl.addLayout(crow)
        self.c_list = QtWidgets.QListWidget()
        self.c_list.setObjectName("SWStudyConstraints")
        self.c_list.setFixedHeight(60)
        cl.addWidget(self.c_list)
        gbox = QtWidgets.QGroupBox("Goals")
        gl = QtWidgets.QVBoxLayout(gbox)
        grow = QtWidgets.QHBoxLayout()
        self.g_how = QtWidgets.QComboBox()
        self.g_how.setObjectName("SWStudyGoalHow")
        self.g_how.addItems(["Minimize", "Maximize"])
        self.g_sensor = QtWidgets.QComboBox()
        self.g_sensor.setObjectName("SWStudyGoalSensor")
        g_add = QtWidgets.QPushButton("Add")
        g_add.setObjectName("SWStudyGoalAdd")
        g_add.clicked.connect(self.add_goal)
        for w_ in (self.g_how, self.g_sensor, g_add):
            grow.addWidget(w_)
        gl.addLayout(grow)
        self.g_list = QtWidgets.QListWidget()
        self.g_list.setObjectName("SWStudyGoals")
        self.g_list.setFixedHeight(60)
        gl.addWidget(self.g_list)
        cg.addWidget(cbox, 3)
        cg.addWidget(gbox, 2)
        lay.addLayout(cg)
        self.constraints, self.goals, self.sensors, self.optimal = [], [], [], None
        self.run_button = QtWidgets.QPushButton("Run")
        self.run_button.setObjectName("SWStudyRun")
        self.run_button.clicked.connect(self.refresh)
        lay.addWidget(self.run_button, 0, QtCore.Qt.AlignLeft)
        self.results = QtWidgets.QTreeWidget()
        self.results.setObjectName("SWStudyResults")
        self.results.setRootIsDecorated(False)
        self.results.setAlternatingRowColors(True)
        lay.addWidget(self.results, 1)
        bottom = QtWidgets.QHBoxLayout()
        self.apply_button = QtWidgets.QPushButton("Apply Scenario")
        self.apply_button.setObjectName("SWStudyApply")
        self.apply_button.clicked.connect(self.apply_scenario)
        bottom.addWidget(self.apply_button)
        bottom.addStretch(1)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        lay.addLayout(bottom)
        self.entries = []
        self.variables = []
        self.found = []
        self.fill_sizes()

    def fill_sizes(self):
        doc = App.ActiveDocument
        self.entries = findmodify.entries(doc) if doc else []
        self.size.clear()
        named = []
        try:
            from . import dsparams
            for p in dsparams.load(doc):
                e = dsparams.entry_of(doc, p)
                if e is not None and not e[4]:
                    named.append(e)
                    self.size.addItem("Parameter: %s (%.3f)" % (p["name"], e[3]))
        except Exception as _fw_err:
            App.Console.PrintLog("FreeCAD: design study parameters: %s\n" % _fw_err)
        for obj, _key, label, value, locked in self.entries:
            if not locked:
                self.size.addItem("%s: %s (%.3f)" % (obj.Label, label, value))
        self.entries = named + [e for e in self.entries if not e[4]]
        try:
            from . import simtypes
            self.sensors = simtypes.design_sensors(doc) if doc else []
        except Exception:
            self.sensors = []
        for combo in (self.c_sensor, self.g_sensor):
            combo.clear()
            combo.addItems([s_[0] for s_ in self.sensors])

    def open_parameters(self):
        from . import dsparams
        dlg = dsparams.show()
        if dlg is None:
            self.summary.setText("Open a part first.")
        return dlg

    def add_constraint(self):
        i = self.c_sensor.currentIndex()
        if i < 0:
            return
        try:
            vals = [float(x) for x in self.c_vals.text().replace(";", ",").split(",") if x.strip()]
        except ValueError:
            self.summary.setText("Constraint: give a number (or min, max).")
            return
        cond = self.c_cond.currentText()
        if not vals or (cond == "is between" and len(vals) != 2):
            self.summary.setText("Constraint: give a value (two for is between).")
            return
        self.constraints.append((self.sensors[i][0], cond) + tuple(vals[:2]))
        self.c_list.addItem("%s %s %s" % (self.sensors[i][0], cond, " and ".join("%g" % v for v in vals[:2])))

    def add_goal(self):
        i = self.g_sensor.currentIndex()
        if i < 0:
            return
        self.goals.append((self.sensors[i][0], self.g_how.currentText()))
        self.g_list.addItem("%s %s" % (self.g_how.currentText(), self.sensors[i][0]))

    def _picked_sensors(self):
        names = {c[0] for c in self.constraints} | {g[0] for g in self.goals}
        return [s_ for s_ in self.sensors if s_[0] in names]

    def add_variable(self):
        i = self.size.currentIndex()
        if i < 0:
            return
        try:
            vals = parse_values(self.values.text())
        except Exception as error:
            self.summary.setText("Values: %s" % error)
            return
        if not vals:
            self.summary.setText("Give the variable some values.")
            return
        entry = self.entries[i]
        self.variables = [v for v in self.variables if v[0][:2] != entry[:2]] + [(entry, vals)]
        self._show_variables()

    def remove_variable(self):
        item = self.vars.currentItem()
        if item is None:
            return
        del self.variables[self.vars.indexOfTopLevelItem(item)]
        self._show_variables()

    def _show_variables(self):
        self.vars.clear()
        for (obj, _key, label, _value, _locked), vals in self.variables:
            self.vars.addTopLevelItem(QtWidgets.QTreeWidgetItem(["%s: %s" % (obj.Label, label),
                                                                 ", ".join("%g" % v for v in vals)]))
        self.vars.resizeColumnToContents(0)

    def refresh(self):
        doc = App.ActiveDocument
        if doc is None or not self.variables:
            self.summary.setText("Add at least one variable.")
            return
        picked = self._picked_sensors()
        try:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                self.found = run(doc, self.variables, picked)
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
        except Exception as error:
            self.summary.setText(str(error))
            return
        labels = [s_[0] for s_ in picked]
        heads = ["Scenario"] + ["%s: %s" % (v[0][0].Label, v[0][2]) for v in self.variables] + \
            ["Volume (mm³)", "Surface area (mm²)", "Rebuilt"] + labels
        best = None
        if picked:
            from . import simtypes
            rows = [r[4] if all(k in r[4] for k in labels) else {k: float("nan") for k in labels} for r in self.found]
            good = [i for i, r in enumerate(self.found) if all(k in r[4] for k in labels)]
            best = simtypes.optimal([rows[i] for i in good], self.constraints, self.goals)
            best = good[best] if best is not None else None
            heads.append("Constraints")
            self.optimal = best
        self.results.clear()
        self.results.setHeaderLabels(heads)
        for n, row in enumerate(self.found, 1):
            combo, vol, area, ok, vals = row
            cells = [str(n) + (" (Optimal)" if best == n - 1 else "")] + ["%g" % v for v in combo] + \
                ["%.3f" % vol, "%.3f" % area, "yes" if ok else "no"]
            cells += ["%.5g" % vals[k] if k in vals else vals.get("error", "-") for k in labels]
            if picked:
                from . import simtypes
                met = all(k[0] in vals and simtypes.meets(vals[k[0]], k[1], k[2], k[3] if len(k) > 3 else None)
                          for k in self.constraints)
                cells.append("met" if met else "not met")
            item = QtWidgets.QTreeWidgetItem(cells)
            if best == n - 1:
                for c in range(len(cells)):
                    item.setBackground(c, QtGui.QColor(200, 240, 200))
            self.results.addTopLevelItem(item)
        for i in range(len(heads)):
            self.results.resizeColumnToContents(i)
        text = "%d scenarios run; the part is as it was. Pick a row and Apply Scenario to keep its values." % len(self.found)
        if picked:
            text += " Optimal: %s." % ("scenario %d" % (best + 1) if best is not None else "none meets the constraints"
                                         if self.goals else "add a goal")
        self.summary.setText(text)

    def apply_scenario(self):
        doc = App.ActiveDocument
        item = self.results.currentItem()
        if doc is None or item is None:
            self.summary.setText("Pick a scenario row first.")
            return
        combo = self.found[self.results.indexOfTopLevelItem(item)][0]
        apply(doc, self.variables, combo)
        self.fill_sizes()
        self.summary.setText("Scenario %s applied." % item.text(0))

    def closeEvent(self, event):
        evaluate._OPEN.pop(type(self).__name__, None)
        super().closeEvent(event)


@evaluate.command("SWStyle_DesignStudy", TITLE,
                  "Tries the part over sets of values for some of its sizes and compares the results.")
def design_study():
    win = evaluate._OPEN.get(DesignStudyWindow.__name__)
    if win is None or not win.isVisible():
        win = DesignStudyWindow()
        evaluate._OPEN[DesignStudyWindow.__name__] = win
    else:
        win.fill_sizes()
    win.show()
    win.raise_()
    win.activateWindow()
    return win


def register():
    if Gui.Command.get("SWStyle_DesignStudy") is None:
        Gui.addCommand("SWStyle_DesignStudy", evaluate._Cmd("SWStyle_DesignStudy"))
    from . import dsparams          # dsparams-1121: Design Study > Parameters
    dsparams.register()
