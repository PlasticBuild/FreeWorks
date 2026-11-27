# SPDX-License-Identifier: LGPL-2.1-or-later
""













import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

TYPES = (("Static", "static", "Stresses, displacements and the factor of safety under loads."),
         ("Frequency", "frequency", "The natural frequencies and mode shapes."),
         ("Buckling", "buckling", "The load at which a slender part buckles."),
         ("Thermal", "thermomech", "Temperatures from heat loads, steady state or over time."),
         ("Check (no solve)", "check", "Writes the input and checks it without solving."))
GOALS = (("Will the part break or bend under a load?", "static"),
         ("How does the part vibrate? (its natural frequencies)", "frequency"),
         ("Will a slender part buckle?", "buckling"),
         ("How does heat flow through the part?", "thermomech"),
         ("Is the setup complete? (check without solving)", "check"))

# the CalculiX solver properties each type shows: (property, label)
PROPS = {
    "static": (("MatrixSolverType", "Solver"), ("GeometricalNonlinearity", "Large displacement")),
    "frequency": (("EigenmodesCount", "Number of frequencies"), ("EigenmodeLowLimit", "Lower limit (Hz)"),
                  ("EigenmodeHighLimit", "Upper limit (Hz)"), ("MatrixSolverType", "Solver")),
    "buckling": (("BucklingFactors", "Number of buckling modes"), ("MatrixSolverType", "Solver")),
    "thermomech": (("ThermoMechType", "Thermal study type"), ("ThermoMechSteadyState", "Steady state"),
                   ("TimePeriod", "Total time"), ("TimeEnd", "Total time"),
                   ("TimeInitialIncrement", "Time increment"), ("TimeInitialStep", "Time increment"),
                   ("MatrixSolverType", "Solver")),
    "check": (),
}
DEFAULTS = {"frequency": {"EigenmodesCount": 5}, "buckling": {"BucklingFactors": 1},
            "thermomech": {"ThermoMechSteadyState": True, "ThermoMechType": "pure heat transfer"}}

# steps: (label, FreeCAD command, tip, words found in the type name of the study's objects that tick it, optional)
M = ("Material", "FEM_MaterialSolid", "The part's material", ("MaterialSolid", "Material"), False)
FIX = ("Fixtures", "SWStyle_SimFixed", "What holds the part still",
       ("Fixed", "Displacement", "PlaneRotation", "Spring", "RigidBody"), False)
FIX_OPT = ("Fixtures", "SWStyle_SimFixed", "What holds the part still (free-free if none)",
           ("Fixed", "Displacement", "PlaneRotation", "Spring", "RigidBody"), True)
LOAD = ("Loads", "SWStyle_SimForce", "Forces and pressures", ("Force", "Pressure", "SelfWeight", "Centrif", "Bearing"), False)
THERMAL = ("Thermal Loads", "FEM_ConstraintTemperature", "Temperatures, heat flux or heat power",
           ("Temperature", "Heatflux", "BodyHeatSource"), False)
INIT = ("Initial Temperature", "FEM_ConstraintInitialTemperature", "The temperature the part starts from",
        ("InitialTemperature",), False)
CONNECT = ("Connections", "SWStyle_SimContact", "Contact or bonding between faces", ("Contact", "Tie"), True)
MESH = ("Mesh", "SWStyle_SimMesh", "Divides the part into elements", ("MESH",), False)

NATIVE = {"SWStyle_SimFixed": "FEM_ConstraintFixed", "SWStyle_SimForce": "FEM_ConstraintForce",
          "SWStyle_SimContact": "FEM_ConstraintContact", "SWStyle_SimMesh": "FEM_MeshGmshFromShape"}


def _cmd(name):
    return name if name in Gui.listCommands() else NATIVE.get(name, name)
RUN = ("Run", "SWStyle_SimRun", "Meshes if needed and solves", ("RESULT",), False)
STEPS = {
    "static": (M, FIX, LOAD, CONNECT, MESH, RUN),
    "frequency": (M, FIX_OPT, CONNECT, MESH, RUN),
    "buckling": (M, FIX, LOAD, CONNECT, MESH, RUN),
    "thermomech": (M, INIT, THERMAL, MESH, RUN),
    "check": (M, FIX, LOAD, MESH, RUN),
}


def apply_defaults(solver, kind):
    ""
    for name, value in DEFAULTS.get(kind, {}).items():
        if name in solver.PropertiesList:
            try:
                setattr(solver, name, value)
            except Exception as error:
                App.Console.PrintLog("FreeCAD study: %s not set (%s)\n" % (name, error))


def after_new(doc, analysis, kind):
    ""

    if kind != "thermomech":
        return
    if any("InitialTemperature" in _kinds(o) for o in analysis.Group):
        return
    import ObjectsFem
    init = ObjectsFem.makeConstraintInitialTemperature(doc, "InitialTemperature")
    for name, value in (("initialTemperature", "300 K"), ("InitialTemperature", "300 K")):
        if name in init.PropertiesList:
            try:
                setattr(init, name, value)
            except Exception as error:
                App.Console.PrintLog("FreeCAD study: initial temperature left at its default (%s)\n" % error)
            break
    analysis.addObject(init)


def _kinds(o):
    return "%s %s" % (getattr(o, "TypeId", ""), getattr(getattr(o, "Proxy", None), "Type", ""))


def _first(analysis, test):
    for o in analysis.Group:
        if test(_kinds(o)):
            return o
    return None


def _analysis():
    from . import addintabs
    return addintabs._active_analysis(App.ActiveDocument) if App.ActiveDocument else None


def _kind_of(analysis):
    from . import addintabs
    solver = addintabs._solver(analysis)
    try:
        return solver.AnalysisType if solver is not None else "static"
    except Exception:
        return "static"


def step_state(analysis, step):
    """(done, text) of one step from what the study holds."""
    words = step[3]
    objs = list(analysis.Group)
    if "MESH" in words:
        for o in objs:
            if "FemMesh" in _kinds(o) and "Result" not in _kinds(o):
                try:
                    count = int(o.FemMesh.NodeCount)
                    return count > 0, ("%d nodes" % count) if count else "not meshed"
                except Exception:
                    return False, "not meshed"
        return False, "no mesh"
    if "RESULT" in words:
        n = len([o for o in objs if "ResultMechanical" in _kinds(o) or "FemResultObject" in _kinds(o)])
        return n > 0, ("%d result set%s" % (n, "" if n == 1 else "s")) if n else "not run"
    hits = [o for o in objs if any(w in _kinds(o) for w in words)]
    if words == M[3]:
        hits = [o for o in objs if "Material" in _kinds(o) and "Fluid" not in _kinds(o)]
    if words == THERMAL[3]:
        hits = [o for o in hits if "InitialTemperature" not in _kinds(o)]
    if hits:
        return True, "%d added" % len(hits) if len(hits) > 1 else hits[0].Label
    return False, "optional" if step[4] else "to do"


# --------------------------------------------------------------- the Study Advisor window
class Advisor(QtWidgets.QDialog):
    def __init__(self, analysis):
        super().__init__(Gui.getMainWindow())
        self.setObjectName("SWStudyAdvisor")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.setWindowTitle("Study Advisor")
        self.analysis = analysis
        lay = QtWidgets.QVBoxLayout(self)
        self.head = QtWidgets.QLabel()
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.rows = []
        for step in STEPS.get(_kind_of(analysis), STEPS["static"]):
            row = QtWidgets.QHBoxLayout()
            tick = QtWidgets.QLabel()
            tick.setFixedWidth(18)
            btn = QtWidgets.QPushButton(step[0])
            btn.setToolTip(step[2])
            btn.setMinimumWidth(130)
            btn.clicked.connect(lambda _c=False, s=step: self._go(s))
            what = QtWidgets.QLabel()
            row.addWidget(tick)
            row.addWidget(btn)
            row.addWidget(what, 1)
            lay.addLayout(row)
            self.rows.append((step, tick, what))
        res = QtWidgets.QPushButton("Show Results")
        res.setToolTip("Opens the study's results: plots and values")
        res.clicked.connect(self._results)
        props = QtWidgets.QPushButton("Study Properties...")
        props.clicked.connect(lambda: Gui.runCommand("SWStyle_SimStudyProps", 0))
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        bottom = QtWidgets.QHBoxLayout()
        for b in (res, props):
            bottom.addWidget(b)
        bottom.addStretch(1)
        bottom.addWidget(close)
        lay.addLayout(bottom)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def refresh(self):
        try:
            self.analysis.Label
        except Exception:
            self.close()                     # the study was deleted
            return
        kind = _kind_of(self.analysis)
        title = dict((k, n) for n, k, _t in TYPES).get(kind, kind)
        todo = None
        for step, tick, what in self.rows:
            done, text = step_state(self.analysis, step)
            tick.setText("✔" if done else ("○" if step[4] else "▶"))
            tick.setStyleSheet("color: #1b7a1b;" if done else "")
            what.setText(text)
            if not done and not step[4] and todo is None:
                todo = step[0]
        self.head.setText("<b>%s</b>: %s" % (self.analysis.Label, ("next: " + todo) if todo else
                                              "all steps done: show the results"))
        self.setWindowTitle("Study Advisor: %s study" % title)

    def _go(self, step):
        try:
            if Gui.Control.activeDialog():
                _say("Study Advisor: finish the open page first (OK or Cancel), then click %s" % step[0])
                return
            _make_active(self.analysis)
            existing = None
            if step is M:
                existing = _first(self.analysis, lambda k: "Material" in k)
            elif step is MESH:
                existing = _first(self.analysis, lambda k: "FemMesh" in k and "Result" not in k)
            elif step is INIT:
                existing = _first(self.analysis, lambda k: "InitialTemperature" in k)
            if step is MESH and _cmd(MESH[1]) == MESH[1]:
                Gui.runCommand(MESH[1], 0)                                         # the Mesh PM, on the study's mesh
            elif existing is not None:
                Gui.getDocument(existing.Document.Name).setEdit(existing.Name)      # its own page, to change it
            elif step is MESH:
                from . import addintabs
                solid = addintabs._main_solid(self.analysis.Document)
                if solid is None:
                    _say("Study Advisor: there is no solid body to mesh")
                    return
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(solid)
                Gui.runCommand(_cmd(step[1]), 0)
            else:
                Gui.runCommand(_cmd(step[1]), 0)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD Study Advisor: %s: %s\n" % (step[0], error))
            _say("Study Advisor: %s: %s" % (step[0], error))
        self.refresh()

    def _results(self):
        try:
            from . import simplots
            if simplots.result(self.analysis) is not None:
                simplots.open_results(self.analysis)                             # Stress1, Displacement1, Strain1
                return
        except Exception as error:
            App.Console.PrintLog("FreeCAD Study Advisor: result plots: %s\n" % error)
        for o in self.analysis.Group:
            if "FemResultObject" in _kinds(o) or "ResultMechanical" in _kinds(o):
                try:
                    Gui.ActiveDocument.setEdit(o.Name)
                    return
                except Exception:
                    pass
        _say("This study has no results yet: Run it first")


_state = {"advisor": None}


def _say(text, ms=8000):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, ms)
    except Exception:
        pass


def _make_active(analysis):
    try:
        from . import addintabs
        addintabs._set_active(analysis)
    except Exception:
        pass


def open_advisor(analysis):
    old = _state.get("advisor")
    try:
        if old is not None:
            old.close()
    except RuntimeError:
        pass
    w = _state["advisor"] = Advisor(analysis)
    w.show()
    w.raise_()
    return w


class AdvisorGoal(QtWidgets.QDialog):
    """Step 0: what do you want to find out?"""

    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle("Study Advisor")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("<b>What do you want to find out?</b>"))
        self.radios = []
        for text, kind in GOALS:
            r = QtWidgets.QRadioButton(text)
            r.setProperty("kind", kind)
            lay.addWidget(r)
            self.radios.append(r)
        self.radios[0].setChecked(True)
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        for r in self.radios:
            r.toggled.connect(self._note)
        self._note()
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Start Study")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def kind(self):
        return next(r.property("kind") for r in self.radios if r.isChecked())

    def _note(self):
        k = self.kind()
        self.note.setText(next(t for _n, kk, t in TYPES if kk == k))


def _advisor():
    from . import addintabs
    addintabs.load("FEM")
    doc = App.ActiveDocument
    obj = addintabs._main_solid(doc) if doc else None
    if obj is None:
        _say("Study Advisor: the document has no solid body to study")
        addintabs._warn("Study Advisor", "The document has no solid body to study.")
        return
    dlg = AdvisorGoal()
    if not dlg.exec_():
        return
    doc.openTransaction("Study Advisor")
    try:
        a = addintabs.new_study(doc, obj, dlg.kind())
    except Exception as error:
        doc.abortTransaction()
        addintabs._warn("Study Advisor", str(error))
        return
    doc.commitTransaction()
    _make_active(a)
    open_advisor(a)
    addintabs._refresh_buttons()


# --------------------------------------------------------------- Study Properties (a task page)
class PropsPanel:
    def __init__(self, analysis):
        from . import addintabs
        self.analysis = analysis
        self.solver = addintabs._solver(analysis)
        self.kind = _kind_of(analysis)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Study Properties")
        lay = QtWidgets.QFormLayout(self.form)
        self.edits = {}
        solver = self.solver
        for name, label in PROPS.get(self.kind, ()):
            if solver is None or name not in solver.PropertiesList:
                continue
            kind = solver.getTypeIdOfProperty(name)
            cur = getattr(solver, name)
            if kind == "App::PropertyEnumeration":
                w = QtWidgets.QComboBox()
                w.addItems(list(solver.getEnumerationsOfProperty(name)))
                w.setCurrentText(str(cur))
            elif kind == "App::PropertyBool":
                w = QtWidgets.QCheckBox()
                w.setChecked(bool(cur))
            elif "Integer" in kind:
                w = QtWidgets.QSpinBox()
                w.setRange(0, 100000)
                w.setValue(int(cur))
            else:
                w = QtWidgets.QLineEdit(str(getattr(cur, "UserString", cur)))
            self.edits[name] = w
            lay.addRow(label, w)
        if not self.edits:
            lay.addRow(QtWidgets.QLabel("This type of study has no options to set."))
        self.form.setProperty("swPrompt", "Set the study's options, then click OK")

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        doc = self.analysis.Document
        doc.openTransaction("Study Properties")
        try:
            for name, w in self.edits.items():
                if isinstance(w, QtWidgets.QComboBox):
                    value = w.currentText()
                elif isinstance(w, QtWidgets.QCheckBox):
                    value = w.isChecked()
                elif isinstance(w, QtWidgets.QSpinBox):
                    value = w.value()
                else:
                    value = w.text().strip()
                try:
                    setattr(self.solver, name, value)
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD study: %s not set (%s)\n" % (name, error))
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True



SOLVER_NAMES = {"spooles": "Direct sparse (SPOOLES)", "iterativescaling": "Iterative (scaling)",
                "iterativecholesky": "Iterative (Cholesky)"}
REMARK, REMARK_REPORT = "FwRemark", "FwRemarkInReport"


def remark(a):
    """The study's Remark tab: (text, include in report)."""
    return str(getattr(a, REMARK, "") or ""), bool(getattr(a, REMARK_REPORT, False))


def set_remark(a, text, in_report):
    for name, kind in ((REMARK, "App::PropertyString"), (REMARK_REPORT, "App::PropertyBool")):
        if name not in a.PropertiesList:
            a.addProperty(kind, name, "FreeCAD", "Study Properties > Remark")
            a.setPropertyStatus(name, "Hidden")
    setattr(a, REMARK, text)
    setattr(a, REMARK_REPORT, bool(in_report))


if Gui is not None:
    class StaticProperties(QtWidgets.QDialog):
        ""



        def __init__(self, a, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            from . import addintabs
            self.a = a
            self.solver = addintabs._solver(a)
            self.setObjectName("SWSimStudyProperties")
            self.setWindowTitle("Static")
            self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
            lay = QtWidgets.QVBoxLayout(self)
            self.tabs = QtWidgets.QTabWidget()
            self.tabs.setObjectName("SWSimStudyPropertiesTabs")
            lay.addWidget(self.tabs)
            # Options
            opt = QtWidgets.QWidget()
            ol = QtWidgets.QVBoxLayout(opt)
            sf = QtWidgets.QGroupBox("Solver")
            sl = QtWidgets.QVBoxLayout(sf)
            sel = QtWidgets.QGroupBox("Selection")
            gl = QtWidgets.QGridLayout(sel)
            self.auto = QtWidgets.QRadioButton("Automatic")
            self.auto.setObjectName("SWSimPropSolverAuto")
            self.manual = QtWidgets.QRadioButton("Manual")
            self.manual.setObjectName("SWSimPropSolverManual")
            self.choice = QtWidgets.QComboBox()
            self.choice.setObjectName("SWSimPropSolverChoice")
            kinds = []
            cur = "default"
            if self.solver is not None and "MatrixSolverType" in self.solver.PropertiesList:
                have = list(self.solver.getEnumerationsOfProperty("MatrixSolverType"))
                kinds = [k for k in SOLVER_NAMES if k in have]       # the ones every CalculiX build has
                cur = str(self.solver.MatrixSolverType)
            self.choice.addItems([SOLVER_NAMES[k] for k in kinds])
            self.kinds = kinds
            gl.addWidget(self.auto, 0, 0)
            gl.addWidget(self.manual, 1, 0)
            gl.addWidget(self.choice, 1, 1)
            sl.addWidget(sel)
            ol.addWidget(sf)
            (self.manual if cur in kinds else self.auto).setChecked(True)
            if cur in kinds:
                self.choice.setCurrentIndex(kinds.index(cur))
            self.manual.setVisible(bool(kinds))
            self.manual.toggled.connect(self._solver_rows)
            self.large = QtWidgets.QCheckBox("Large displacement")
            self.large.setObjectName("SWSimPropLarge")
            self.large.setVisible(self.solver is not None and "GeometricalNonlinearity" in self.solver.PropertiesList)
            if self.large.isVisible() or self.solver is not None:
                self.large.setChecked(str(getattr(self.solver, "GeometricalNonlinearity", "linear")) == "nonlinear")
            ol.addWidget(self.large)

            # fixtures leave free (loads in balance) still solves
            from . import simtypes as _st
            self.soft = QtWidgets.QCheckBox("Use soft spring to stabilize the model")
            self.soft.setObjectName("SWSimPropSoft")
            self.soft.setToolTip("Adds very weak springs to ground at every node, so a part that is not fully held "
                                 "by its fixtures still solves. Use it when the loads are in balance.")
            self.soft.setChecked(bool(getattr(a, _st.SOFT, False)))
            ol.addWidget(self.soft)

            # own inertia (the loads' resultant taken by an even acceleration of the whole part)
            self.inertial = QtWidgets.QCheckBox("Use inertial relief")
            self.inertial.setObjectName("SWSimPropInertial")
            self.inertial.setToolTip("For a part with no fixtures: its own inertia balances the loads, as for a "
                                     "part in flight or in free fall.")
            self.inertial.setChecked(bool(getattr(a, _st.INERTIAL, False)))
            ol.addWidget(self.inertial)
            ol.addStretch(1)
            self.tabs.addTab(opt, "Options")
            # Remark
            rem = QtWidgets.QWidget()
            rl = QtWidgets.QVBoxLayout(rem)
            text, in_report = remark(a)
            self.in_report = QtWidgets.QCheckBox("Include in report")
            self.in_report.setObjectName("SWSimPropRemarkReport")
            self.in_report.setChecked(in_report)
            cf = QtWidgets.QGroupBox("Comment")
            cl = QtWidgets.QVBoxLayout(cf)
            self.comment = QtWidgets.QPlainTextEdit(text)
            self.comment.setObjectName("SWSimPropRemark")
            cl.addWidget(self.comment)
            rl.addWidget(self.in_report)
            rl.addWidget(cf)
            self.tabs.addTab(rem, "Remark")
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel |
                                            QtWidgets.QDialogButtonBox.Apply)
            bb.setObjectName("SWSimStudyPropertiesButtons")
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            self.apply_btn = bb.button(QtWidgets.QDialogButtonBox.Apply)
            self.apply_btn.clicked.connect(self.apply)
            self.apply_btn.setEnabled(False)
            for sig in (self.auto.toggled, self.manual.toggled, self.choice.currentIndexChanged, self.large.toggled,
                        self.soft.toggled, self.inertial.toggled, self.in_report.toggled, self.comment.textChanged):
                sig.connect(lambda *_x: self.apply_btn.setEnabled(True))
            lay.addWidget(bb)
            self._solver_rows()

        def _solver_rows(self, *_x):
            self.choice.setVisible(self.manual.isChecked())   # shown only for Manual (greyed is a dead control)

        def values(self):
            solver = self.kinds[self.choice.currentIndex()] if self.manual.isChecked() and self.kinds else "default"
            return {"solver": solver, "large": self.large.isChecked(), "remark": self.comment.toPlainText(),
                    "in_report": self.in_report.isChecked(), "soft": self.soft.isChecked(),
                    "inertial": self.inertial.isChecked()}

        def apply(self):
            v = self.values()
            doc = self.a.Document
            doc.openTransaction("Study Properties")
            try:
                s = self.solver
                if s is not None and "MatrixSolverType" in s.PropertiesList:
                    s.MatrixSolverType = v["solver"]
                if s is not None and "GeometricalNonlinearity" in s.PropertiesList:
                    s.GeometricalNonlinearity = "nonlinear" if v["large"] else "linear"
                from . import simtypes
                if s is not None:
                    simtypes.set_properties(self.a, soft=v["soft"], inertial=v["inertial"])
                set_remark(self.a, v["remark"], v["in_report"])
                doc.commitTransaction()
            except Exception:
                doc.abortTransaction()
                raise
            doc.recompute()
            self.apply_btn.setEnabled(False)
            return True

        def accept(self):
            try:
                self.apply()
            except Exception as error:
                QtWidgets.QMessageBox.warning(self, self.windowTitle(), str(error))
                return
            super().accept()

    class ModalProperties(StaticProperties):
        ""



        def __init__(self, a, parent=None):
            super().__init__(a, parent)
            from . import simtypes
            self.kind = simtypes.study_type(a)
            v = simtypes.properties(a)
            self.setWindowTitle("Frequency" if self.kind == "frequency" else "Buckling")
            self.large.setVisible(False)
            self.inertial.setVisible(False)                 # a static option
            opt = self.tabs.widget(0)
            ol = opt.layout()
            box = QtWidgets.QGroupBox("Options")
            box.setObjectName("SWSimPropOptions")
            gl = QtWidgets.QGridLayout(box)
            self.count = QtWidgets.QSpinBox()
            self.count.setObjectName("SWSimPropCount")
            self.count.setRange(1, 200)
            self.count.setValue(int(v.get("count") or (5 if self.kind == "frequency" else 1)))
            gl.addWidget(QtWidgets.QLabel("Number of frequencies" if self.kind == "frequency" else "Number of buckling modes"), 0, 0)
            gl.addWidget(self.count, 0, 1)
            self.upper_on = self.upper = None
            if self.kind == "frequency":
                self.upper_on = QtWidgets.QCheckBox("Upper bound frequency")
                self.upper_on.setObjectName("SWSimPropUpperOn")
                self.upper = QtWidgets.QDoubleSpinBox()
                self.upper.setObjectName("SWSimPropUpper")
                self.upper.setRange(0.001, 1e9)
                self.upper.setDecimals(3)
                self.upper.setSuffix(" Hz")
                self.upper.setValue(v.get("upper") or 1000.0)
                self.upper_on.setChecked(v.get("upper") is not None)
                self.upper.setVisible(self.upper_on.isChecked())   # shown only while ticked (greyed is a dead control)
                self.upper_on.toggled.connect(self.upper.setVisible)
                gl.addWidget(self.upper_on, 1, 0)
                gl.addWidget(self.upper, 1, 1)

                # part, solved as a static step then the frequencies about it
                self.inplane = QtWidgets.QCheckBox("Use inplane effect")
                self.inplane.setObjectName("SWSimPropInplane")
                self.inplane.setToolTip("The study's loads change the frequencies: tension raises them, compression "
                                        "lowers them. Without it the loads are not used.")
                self.inplane.setChecked(bool(v.get("inplane")))
                gl.addWidget(self.inplane, 2, 0, 1, 2)
                gl.addWidget(self.soft, 3, 0, 1, 2)
            else:
                self.soft.setVisible(False)
            ol.insertWidget(0, box)
            sigs = [self.count.valueChanged]
            if self.upper_on is not None:
                sigs += [self.upper_on.toggled, self.upper.valueChanged, self.inplane.toggled]
            for sig in sigs:
                sig.connect(lambda *_x: self.apply_btn.setEnabled(True))

        def values(self):
            v = super().values()
            v["count"] = self.count.value()
            if self.kind == "frequency":
                v["upper"] = self.upper.value() if self.upper_on.isChecked() else None
                v["inplane"] = self.inplane.isChecked()
            else:
                v.pop("soft", None)
            v.pop("inertial", None)
            return v

        def apply(self):
            from . import simtypes
            v = self.values()
            doc = self.a.Document
            doc.openTransaction("Study Properties")
            try:
                s = self.solver
                if s is not None and "MatrixSolverType" in s.PropertiesList:
                    s.MatrixSolverType = v["solver"]
                kw = {"count": v["count"]}
                if self.kind == "frequency":
                    kw["upper"] = v["upper"]
                    kw["inplane"] = v["inplane"]
                    kw["soft"] = v["soft"]
                simtypes.set_properties(self.a, **kw)
                set_remark(self.a, v["remark"], v["in_report"])
                doc.commitTransaction()
            except Exception:
                doc.abortTransaction()
                raise
            doc.recompute()
            self.apply_btn.setEnabled(False)
            return True

    def open_modal_properties(a):
        dlg = ModalProperties(a)
        dlg.show()
        dlg.raise_()
        OPEN_DIALOGS[:] = [dlg]
        return dlg

    def open_static_properties(a):
        dlg = StaticProperties(a)
        dlg.show()
        dlg.raise_()
        OPEN_DIALOGS[:] = [dlg]
        return dlg

OPEN_DIALOGS = []


def _props():
    a = _analysis()
    if a is None:
        _say("Study Properties: there is no study yet. Start one with New Study or Study Advisor")
        return
    try:
        if Gui.Control.activeDialog():
            return
        Gui.Control.showDialog(PropsPanel(a))
        _say("Set the study's options, then click OK", 10000)
    except Exception as error:
        _say("Study Properties: %s" % error)


# --------------------------------------------------------------- commands
class _Cmd:
    def __init__(self, text, tip, run, pixmap="FEM_Analysis"):
        self.text, self.tip, self.run, self.pixmap = text, tip, run, pixmap

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": self.pixmap}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        try:
            self.run()
        except Exception as error:
            App.Console.PrintError("FreeCAD study: %s\n" % error)
            _say("%s: %s" % (self.text, error))


def register():
    if Gui is None:
        return
    for name, cmd in (("SWStyle_SimStudyAdvisor", _Cmd("Study Advisor", "Asks what you want to find out, starts that type of "
                                                        "study and walks through its steps.", _advisor)),
                      ("SWStyle_SimStudyProps", _Cmd("Study Properties", "The options of the active study's type: solver, "
                                                      "frequencies, buckling modes, steady state or time.", _props,
                                                      "FEM_SolverControl"))):
        if name not in Gui.listCommands():
            Gui.addCommand(name, cmd)
