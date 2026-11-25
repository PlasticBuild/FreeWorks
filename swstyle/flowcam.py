# -*- coding: utf-8 -*-
""







import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None


def _fw_log(where, err):
    try:
        App.Console.PrintLog("FreeCAD %s: %s\n" % (where, err))
    except Exception:
        pass


FLUIDS = ("Air", "Water")


# ------------------------------------------------------------------ flow project data
def _flow_parts(a):
    """(solver, flow equation, heat equation, fluid material, gmsh mesh) of a flow project; None where missing."""
    from . import addintabs
    solver = addintabs._solver(a)
    flow = heat = fluid = mesh = None
    for e in list(getattr(solver, "Group", None) or []):
        t = getattr(getattr(e, "Proxy", None), "Type", "")
        if t == "Fem::EquationElmerFlow":
            flow = e
        elif t == "Fem::EquationElmerHeat":
            heat = e
    for o in a.Group:
        t = getattr(getattr(o, "Proxy", None), "Type", "")
        if t == "Fem::MaterialCommon" and getattr(o, "Category", "") == "Fluid":
            fluid = o
        elif t == "Fem::FemMeshGmsh":
            mesh = o
    return solver, flow, heat, fluid, mesh


def general(a):
    """The project's General Settings: fluid, time-dependent (with its total time and step), heat transfer."""
    solver, _flow, heat, fluid, _mesh = _flow_parts(a)
    name = (getattr(fluid, "Material", None) or {}).get("Name", "Air") if fluid is not None else "Air"
    out = {"fluid": name if name in FLUIDS else "Air", "transient": False, "total": 1.0, "step": 0.1,
           "heat": heat is not None}
    if solver is not None:
        try:
            out["transient"] = solver.SimulationType == "Transient"
            step = float(list(solver.TimestepSizes)[0])
            out["step"] = step
            out["total"] = step * int(list(solver.TimestepIntervals)[0])
        except Exception as _fw_err:
            _fw_log("flowcam.py:general", _fw_err)
    return out


def set_general(a, values):
    """Writes General Settings onto the project's own objects. Returns the values as set."""
    from . import addintabs
    import ObjectsFem
    doc = a.Document
    solver, _flow, heat, fluid, _mesh = _flow_parts(a)
    v = dict(general(a), **values)
    if v["fluid"] not in FLUIDS:
        raise ValueError("Pick Air or Water.")
    if v["transient"] and (v["step"] <= 0 or v["total"] < v["step"]):
        raise ValueError("The time step must be above zero and no more than the total time.")
    if fluid is None:
        fluid = ObjectsFem.makeMaterialFluid(doc, "Fluid")
        a.addObject(fluid)
    if (fluid.Material or {}).get("Name") != v["fluid"]:
        fluid.Material = dict(addintabs.WATER if v["fluid"] == "Water" else addintabs.AIR)
    if solver is not None:
        solver.SimulationType = "Transient" if v["transient"] else "Steady State"
        if v["transient"]:
            solver.TimestepSizes = [float(v["step"])]
            solver.TimestepIntervals = [max(1, int(round(v["total"] / v["step"])))]
        if v["heat"] and heat is None:
            eq = ObjectsFem.makeEquationHeat(doc, solver)
            if eq is not None and eq not in solver.Group:
                solver.addObject(eq)
        elif not v["heat"] and heat is not None:
            solver.removeObject(heat)
            doc.removeObject(heat.Name)
    doc.recompute()
    return general(a)


def domain_candidates(doc):
    """The solid bodies a project can take as its fluid region (its computational domain): bodies, and top-level
    solids that no other feature uses (a FEM mesh or study that links them does not count)."""
    def fem(o):
        return o.TypeId.startswith("Fem::") or o.isDerivedFrom("Fem::FemAnalysis") or hasattr(o, "FemMesh")
    out = []
    for o in doc.Objects:
        try:
            if not hasattr(o, "Shape") or not o.Shape.Solids or fem(o) or o.TypeId == "Path::FeaturePython":
                continue
            users = [u for u in o.InList if not fem(u)]
            if o.isDerivedFrom("PartDesign::Body") or not users:
                out.append(o)
        except Exception as _fw_err:
            _fw_log("flowcam.py:candidates", _fw_err)
    return out


def domain(a):
    mesh = _flow_parts(a)[4]
    return getattr(mesh, "Shape", None) if mesh is not None else None


def set_domain(a, obj):
    """The project's computational domain is obj: the mesh takes it and is made again on the next run."""
    from . import addintabs
    mesh = _flow_parts(a)[4]
    if mesh is None:
        mesh = addintabs._gmsh(a.Document, obj, a, second_order=False)
    elif mesh.Shape is not obj:
        mesh.Shape = obj
        try:
            import Fem
            mesh.FemMesh = Fem.FemMesh()          # meshed again from the new region when the project runs
        except Exception as _fw_err:
            _fw_log("flowcam.py:remesh", _fw_err)
    try:
        bb = obj.Shape.BoundBox
        return (bb.XLength, bb.YLength, bb.ZLength)
    except Exception:
        return None


# ------------------------------------------------------------------ CAM data
def _jobs(doc):
    return [o for o in (doc.Objects if doc is not None else []) if type(getattr(o, "Proxy", None)).__name__ == "ObjectJob"]


def operations(job):
    return list(getattr(getattr(job, "Operations", None), "Group", None) or [])


def sort_operations(job, order):
    """Puts the job's operations in this order (the same objects), as Sort Operations does."""
    ops = operations(job)
    if sorted(id(o) for o in order) != sorted(id(o) for o in ops):
        raise ValueError("The order must hold the job's operations, each once.")
    job.Operations.Group = list(order)
    job.Document.recompute()
    return [o.Label for o in operations(job)]


def posts():
    try:
        import Path
        return list(Path.Preferences.allEnabledPostProcessors())
    except Exception as _fw_err:
        _fw_log("flowcam.py:posts", _fw_err)
        return []


META = "FwMachine"


def machine(doc):
    ""

    import Path
    jobs = _jobs(doc)
    m = _kept(doc)
    if jobs:
        j = jobs[0]
        out = {"post": j.PostProcessor or "", "args": j.PostProcessorArgs or "", "output": j.PostProcessorOutputFile or ""}
    elif m:
        out = {"post": m.get("post", ""), "args": m.get("args", ""), "output": m.get("output", "")}
    else:
        out = {"post": Path.Preferences.defaultPostProcessor(), "args": Path.Preferences.defaultPostProcessorArgs(),
               "output": Path.Preferences.defaultOutputFile()}
    out["jobs"] = len(jobs)
    return out


def _kept(doc):
    import json
    try:
        return json.loads(dict(doc.Meta).get(META, "") or "{}") if doc is not None else {}
    except Exception:
        return {}


def set_machine(doc, post, args="", output=""):
    """The part (saved with it) and every job of the part take this machine; FreeCAD's own CAM defaults stay as
    they are. The jobs' change is one Undo step when run inside a transaction."""
    import json
    if post and post not in posts():
        raise ValueError("%s is not an enabled post processor." % post)
    meta = dict(doc.Meta)
    meta[META] = json.dumps({"post": post, "args": args, "output": output})
    doc.Meta = meta
    try:
        if Gui is not None and Gui.getDocument(doc.Name) is not None:
            Gui.getDocument(doc.Name).Modified = True       # doc.Meta alone does not ask to save on close
    except Exception as _fw_err:
        _fw_log("flowcam.py:set_machine", _fw_err)
    for j in _jobs(doc):
        apply_machine(j, m=_kept(doc))
    return machine(doc)


def apply_machine(job, m=None):
    """A job takes its part's machine (a job made after Define Machine, before it is post processed): the other jobs'
    one when there are some (they follow Undo, doc.Meta does not), else the one kept with the part."""
    if m is None:
        other = [j for j in _jobs(job.Document) if j is not job]
        if other:
            j = other[0]
            m = {"post": j.PostProcessor or "", "args": j.PostProcessorArgs or "", "output": j.PostProcessorOutputFile or ""}
        else:
            m = _kept(job.Document)
    if not m:
        return False
    if job.PostProcessor != m.get("post", ""):
        job.PostProcessor = m.get("post", "")
    if job.PostProcessorArgs != m.get("args", ""):
        job.PostProcessorArgs = m.get("args", "")
    if job.PostProcessorOutputFile != m.get("output", ""):
        job.PostProcessorOutputFile = m.get("output", "")
    return True


# ------------------------------------------------------------------ keys (key, label, natives, tip, caption)
KEYS = (
    ("FLOW_Wizard", "Wizard", ("SWStyle_FlowNewProject",),
     "Walks through a new flow project: the fluid region body and its fluid.", None),
    ("FLOW_NewDefault", "New", ("SWStyle_FlowNew",), "A new flow project on the active body with the default settings (air).", None),
    ("FLOW_General", "General Settings", ("SWStyle_FlowGeneral",),
     "The project's fluid, time-dependent analysis and heat transfer.", "General\nSettings"),
    ("FLOW_Domain", "Computational Domain", ("SWStyle_FlowDomain",), "The fluid region the project meshes and solves.", None),
    ("FLOW_Conditions", "Conditions", ("FEM_ConstraintFlowVelocity",), "Boundary and initial conditions.", None),
    ("FLOW_Tools", "Tools", ("SWStyle_AllTools_FEM",), "Every FEM command, by toolbar.", None),
    ("CAM_Machine", "Define Machine", ("SWStyle_CAMMachine",),
     "The machine the part is cut on: its post processor, arguments and output file.", "Define\nMachine"),
    ("CAM_Sort", "Sort Operations", ("SWStyle_CAMSort",), "Puts the job's operations in the order they are cut.",
     "Sort\nOperations"),
)


if Gui is not None:
    def _main():
        return Gui.getMainWindow()

    def _warn(title, text):
        QtWidgets.QMessageBox.warning(_main(), title, text)

    def _flow_study():
        from . import studytools
        doc = App.ActiveDocument
        return studytools._active(doc, True) if doc is not None else None

    def _no_dialog():
        return not Gui.Control.activeDialog()

    class GeneralSettingsDialog(QtWidgets.QDialog):
        def __init__(self, a, parent=None):
            super().__init__(parent or _main())
            self.a = a
            self.setObjectName("SWFlowGeneralSettings")
            self.setWindowTitle("General Settings")
            v = general(a)
            lay = QtWidgets.QVBoxLayout(self)
            box = QtWidgets.QGroupBox("Analysis Type", self)
            form = QtWidgets.QFormLayout(box)
            form.addRow("Analysis type:", QtWidgets.QLabel("Internal (the body is the fluid region)", box))
            self.transient = QtWidgets.QCheckBox("Time-dependent", box)
            self.transient.setChecked(v["transient"])
            form.addRow(self.transient)
            self.total = QtWidgets.QDoubleSpinBox(box)
            self.total.setRange(1e-6, 1e6); self.total.setDecimals(4); self.total.setSuffix(" s"); self.total.setValue(v["total"])
            self.step = QtWidgets.QDoubleSpinBox(box)
            self.step.setRange(1e-6, 1e6); self.step.setDecimals(4); self.step.setSuffix(" s"); self.step.setValue(v["step"])
            self.total_label = QtWidgets.QLabel("Total analysis time:", box)
            self.step_label = QtWidgets.QLabel("Time step:", box)
            form.addRow(self.total_label, self.total)
            form.addRow(self.step_label, self.step)
            self.heat = QtWidgets.QCheckBox("Heat transfer", box)
            self.heat.setChecked(v["heat"])
            form.addRow(self.heat)
            lay.addWidget(box)
            fbox = QtWidgets.QGroupBox("Fluids", self)
            ff = QtWidgets.QFormLayout(fbox)
            self.fluid = QtWidgets.QComboBox(fbox)
            self.fluid.addItems(list(FLUIDS))
            self.fluid.setCurrentIndex(FLUIDS.index(v["fluid"]))
            ff.addRow("Project fluid:", self.fluid)
            lay.addWidget(fbox)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            lay.addWidget(buttons)
            self.transient.toggled.connect(self._show)
            self._show()

        def _show(self):
            on = self.transient.isChecked()
            for w in (self.total, self.step, self.total_label, self.step_label):
                w.setVisible(on)               # shown only with Time-dependent: no greyed fields

        def values(self):
            return {"fluid": self.fluid.currentText(), "transient": self.transient.isChecked(),
                    "total": self.total.value(), "step": self.step.value(), "heat": self.heat.isChecked()}

        def accept(self):
            doc = self.a.Document
            doc.openTransaction("General Settings")
            try:
                set_general(self.a, self.values())
            except Exception as error:
                doc.abortTransaction()
                _warn("General Settings", str(error))
                return
            doc.commitTransaction()
            super().accept()

    class DomainDialog(QtWidgets.QDialog):
        def __init__(self, a, parent=None):
            super().__init__(parent or _main())
            self.a = a
            self.setObjectName("SWFlowDomain")
            self.setWindowTitle("Computational Domain")
            lay = QtWidgets.QVBoxLayout(self)
            self.bodies = domain_candidates(a.Document)
            now = domain(a)
            form = QtWidgets.QFormLayout()
            if len(self.bodies) > 1:
                self.body = QtWidgets.QComboBox(self)
                self.body.addItems([o.Label for o in self.bodies])
                if now in self.bodies:
                    self.body.setCurrentIndex(self.bodies.index(now))
                self.body.currentIndexChanged.connect(self._size)
                form.addRow("Fluid region:", self.body)
            else:
                self.body = None                # one body: shown as text, not a one-entry list
                form.addRow("Fluid region:", QtWidgets.QLabel(now.Label if now is not None else
                                                              (self.bodies[0].Label if self.bodies else "(none)"), self))
            self.size = QtWidgets.QLabel(self)
            form.addRow("Size:", self.size)
            lay.addLayout(form)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            lay.addWidget(buttons)
            self._size()

        def picked(self):
            if self.body is not None:
                return self.bodies[self.body.currentIndex()]
            return domain(self.a) or (self.bodies[0] if self.bodies else None)

        def _size(self, *_):
            o = self.picked()
            try:
                bb = o.Shape.BoundBox
                self.size.setText("%.4g x %.4g x %.4g mm" % (bb.XLength, bb.YLength, bb.ZLength))
            except Exception:
                self.size.setText("-")

        def accept(self):
            o = self.picked()
            if o is None:
                _warn("Computational Domain", "Model the fluid region as a solid body first.")
                return
            doc = self.a.Document
            doc.openTransaction("Computational Domain")
            set_domain(self.a, o)
            doc.commitTransaction()
            doc.recompute()
            super().accept()

    class MachineDialog(QtWidgets.QDialog):
        def __init__(self, doc, parent=None):
            super().__init__(parent or _main())
            self.doc = doc
            self.setObjectName("SWCAMDefineMachine")
            self.setWindowTitle("Machine")
            m = machine(doc)
            lay = QtWidgets.QVBoxLayout(self)
            tabs = QtWidgets.QTabWidget(self)
            page = QtWidgets.QWidget(tabs)
            form = QtWidgets.QFormLayout(page)
            self.post = QtWidgets.QComboBox(page)
            self.post.setObjectName("SWCAMMachinePost")
            names = posts()
            self.post.addItems(names)
            if m["post"] in names:
                self.post.setCurrentIndex(names.index(m["post"]))
            form.addRow("Post processor:", self.post)
            self.args = QtWidgets.QLineEdit(m["args"], page)
            form.addRow("Arguments:", self.args)
            self.output = QtWidgets.QLineEdit(m["output"], page)
            self.output.setPlaceholderText("FreeCAD's default output file")
            form.addRow("Output file:", self.output)
            note = ("Kept with the part: its %d job(s) and the jobs made later." % m["jobs"] if m["jobs"]
                    else "Kept with the part: the jobs made later take it.")
            form.addRow(QtWidgets.QLabel(note, page))
            tabs.addTab(page, "Post Processor")
            lay.addWidget(tabs)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            lay.addWidget(buttons)

        def accept(self):
            self.doc.openTransaction("Define Machine")
            try:
                set_machine(self.doc, self.post.currentText(), self.args.text(), self.output.text())
            except Exception as error:
                self.doc.abortTransaction()
                _warn("Define Machine", str(error))
                return
            self.doc.commitTransaction()
            super().accept()

    class SortDialog(QtWidgets.QDialog):
        def __init__(self, job, parent=None):
            super().__init__(parent or _main())
            self.job = job
            self.setObjectName("SWCAMSortOperations")
            self.setWindowTitle("Sort Operations")
            self.ops = operations(job)
            lay = QtWidgets.QHBoxLayout(self)
            self.list = QtWidgets.QListWidget(self)
            for o in self.ops:
                it = QtWidgets.QListWidgetItem(o.Label)
                it.setData(QtCore.Qt.UserRole, o.Name)
                self.list.addItem(it)
            self.list.setCurrentRow(0)
            lay.addWidget(self.list)
            side = QtWidgets.QVBoxLayout()
            self.moves = {}
            for text, fn in (("Move to Top", lambda: self.move(-10 ** 6)), ("Move Up", lambda: self.move(-1)),
                             ("Move Down", lambda: self.move(1)), ("Move to Bottom", lambda: self.move(10 ** 6))):
                b = QtWidgets.QPushButton(text, self)
                b.clicked.connect(fn)
                side.addWidget(b)
                self.moves[text] = b
            side.addStretch(1)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
                                                 QtCore.Qt.Vertical, self)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            side.addWidget(buttons)
            lay.addLayout(side)

        def move(self, by):
            row = self.list.currentRow()
            if row < 0:
                return
            new = max(0, min(self.list.count() - 1, row + by))
            if new != row:
                it = self.list.takeItem(row)
                self.list.insertItem(new, it)
                self.list.setCurrentRow(new)

        def order(self):
            by_name = {o.Name: o for o in self.ops}
            return [by_name[self.list.item(i).data(QtCore.Qt.UserRole)] for i in range(self.list.count())]

        def accept(self):
            doc = self.job.Document
            doc.openTransaction("Sort Operations")
            try:
                sort_operations(self.job, self.order())
            except Exception as error:
                doc.abortTransaction()
                _warn("Sort Operations", str(error))
                return
            doc.commitTransaction()
            super().accept()

    def flow_new():
        from . import addintabs
        addintabs.load("FEM")
        doc = App.ActiveDocument
        obj = addintabs._main_solid(doc)
        if obj is None:
            _warn("New", "Model the fluid region as a solid body first.")
            return None
        doc.openTransaction("New Flow Project")
        try:
            a = addintabs.new_flow(doc, obj, "Air")
        except Exception as error:
            doc.abortTransaction()
            _warn("New", str(error))
            return None
        doc.commitTransaction()
        addintabs._set_active(a)
        addintabs._refresh_buttons()
        return a

    def flow_general():
        a = _flow_study()
        if a is None:
            return None
        dlg = GeneralSettingsDialog(a)
        dlg.exec_()
        return dlg

    def flow_domain():
        a = _flow_study()
        if a is None:
            return None
        dlg = DomainDialog(a)
        dlg.exec_()
        return dlg

    def cam_machine():
        doc = App.ActiveDocument
        try:
            import Path  # noqa: F401  (FreeCAD's CAM preferences and post processors)
        except Exception as error:
            _warn("Define Machine", "FreeCAD's CAM workbench is not available (%s)." % error)
            return None
        dlg = MachineDialog(doc)
        dlg.exec_()
        return dlg

    def _picked_job():
        doc = App.ActiveDocument
        jobs = _jobs(doc)
        for s in Gui.Selection.getSelection():
            for j in jobs:
                if s is j or s in operations(j):
                    return j
        return jobs[0] if jobs else None

    def cam_sort():
        job = _picked_job()
        if job is None:
            _warn("Sort Operations", "There is no job yet: start one with Setup.")
            return None
        if len(operations(job)) < 2:
            _warn("Sort Operations", "The job has %d operation(s): there is nothing to sort." % len(operations(job)))
            return None
        dlg = SortDialog(job)
        dlg.exec_()
        return dlg

    class _Cmd:
        def __init__(self, label, tip, run, active, pixmap=""):
            self.label, self.tip, self.run, self.active, self.pixmap = label, tip, run, active, pixmap

        def GetResources(self):
            return {"MenuText": self.label, "ToolTip": self.tip, "Pixmap": self.pixmap}

        def IsActive(self):
            try:
                return bool(self.active())
            except Exception:
                return False

        def Activated(self):
            self.run()

    def _has_flow():
        from . import studytools
        return App.ActiveDocument is not None and bool(studytools.studies(App.ActiveDocument, True)) and _no_dialog()

    COMMANDS = {
        "SWStyle_FlowNew": _Cmd("New", KEYS[1][3], flow_new, lambda: App.ActiveDocument is not None and _no_dialog(),
                                "FEM_Analysis"),
        "SWStyle_FlowGeneral": _Cmd("General Settings", KEYS[2][3], flow_general, _has_flow, "FEM_EquationFlow"),
        "SWStyle_FlowDomain": _Cmd("Computational Domain", KEYS[3][3], flow_domain, _has_flow, "Part_Box"),
        "SWStyle_CAMMachine": _Cmd("Define Machine", KEYS[6][3], cam_machine,
                                   lambda: App.ActiveDocument is not None and _no_dialog(), "CAM_Job"),
        "SWStyle_CAMSort": _Cmd("Sort Operations", KEYS[7][3], cam_sort,
                                lambda: bool(_jobs(App.ActiveDocument)) and _no_dialog(), "CAM_OpActiveToggle"),
    }


def install():
    """The commands and their catalog keys (before the add-in tabs are built from them)."""
    if Gui is None:
        return
    from . import catalog
    have = set(Gui.listCommands())
    for name, cmd in COMMANDS.items():
        if name not in have:
            Gui.addCommand(name, cmd)
    for key, label, natives, tip, caption in KEYS:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, natives, None, tip, caption=caption)
