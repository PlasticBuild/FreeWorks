# SPDX-License-Identifier: LGPL-2.1-or-later
""











import os

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            App.Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


# ------------------------------------------------------------------ the studies of a document
def studies(doc, flow=None):
    """The document's studies (FEM analyses); flow True / False: only flow projects / only the others."""
    out = [o for o in (doc.Objects if doc is not None else []) if o.isDerivedFrom("Fem::FemAnalysis")]
    if flow is not None:
        out = [a for a in out if is_flow(a) == flow]
    return out


def is_flow(analysis):
    for o in analysis.Group:
        for e in [o] + list(getattr(o, "Group", None) or []):
            if getattr(getattr(e, "Proxy", None), "Type", "") == "Fem::EquationElmerFlow":
                return True
    return False


def _solver(analysis):
    from . import addintabs
    return addintabs._solver(analysis)


def study_type(analysis):
    if is_flow(analysis):
        return "Flow"
    s = _solver(analysis)
    if s is None:
        return "No solver"
    kind = str(getattr(s, "AnalysisType", "") or "")
    return {"static": "Static", "frequency": "Frequency", "buckling": "Buckling", "thermomech": "Thermal",
            "check": "Check"}.get(kind, kind.capitalize() or s.Label)


def _results(analysis):
    return [o for o in analysis.Group if o.isDerivedFrom("Fem::FemResultObject")]


def compare_row(analysis):
    """(study, type, status, [(what, value text)]) for Compare Results."""
    from . import addintabs
    res = _results(analysis)
    kind = study_type(analysis)
    if not res:
        piped = [o for o in analysis.Group if o.isDerivedFrom("Fem::FemPostPipeline")]
        return analysis.Label, kind, "solved (see its plot)" if piped else "not run", []
    values = []
    if kind == "Frequency":
        modes = sorted((int(addintabs._number(getattr(r, "Eigenmode", 0))), addintabs._number(getattr(r, "EigenmodeFrequency", 0.0)))
                       for r in res)
        modes = [m for m in modes if m[0] > 0]
        if modes:
            values.append(("Lowest frequency", "%.5g Hz" % modes[0][1]))
            values.append(("Modes", str(len(modes))))
        return analysis.Label, kind, "solved", values
    if kind == "Buckling":
        factors = [f for f in addintabs.buckling_factors(analysis) if f > 0]
        if factors:
            values.append(("Buckling load factor", "%.4g" % min(factors)))
    r = res[-1]
    temps = list(getattr(r, "Temperature", None) or [])
    if temps and kind == "Thermal":
        values.append(("Temperature", "%.4g K to %.4g K" % (min(temps), max(temps))))
    vm = list(getattr(r, "vonMises", None) or [])
    disp = list(getattr(r, "DisplacementLengths", None) or [])
    if vm and max(vm) > 0:
        values.append(("Max von Mises stress", "%.4g MPa" % max(vm)))
    if disp and max(disp) > 0:
        values.append(("Max displacement", "%.4g mm" % max(disp)))
    return analysis.Label, kind, "solved", values


def compare_table(doc):
    """(column titles, rows) of Compare Results: a column for each kind of value any study has."""
    rows = [compare_row(a) for a in studies(doc)]
    cols = []
    for _l, _k, _s, values in rows:
        for what, _v in values:
            if what not in cols:
                cols.append(what)
    table = [[label, kind, status] + [dict(values).get(c, "") for c in cols] for label, kind, status, values in rows]
    return ["Study", "Type", "Status"] + cols, table


# ------------------------------------------------------------------ run them all
def run_one(analysis):
    """Runs a study to the end (blocking). Returns its summary text ("" when the solver gives none)."""
    from . import addintabs
    solver = _solver(analysis)
    if solver is None:
        raise RuntimeError("no solver: add one from the Run This Study arrow")
    if getattr(getattr(solver, "Proxy", None), "Type", "") == "Fem::SolverCcxTools":
        return addintabs.run_study(analysis) or ""
    addintabs._ensure_mesh(analysis)
    if getattr(getattr(solver, "Proxy", None), "Type", "") == "Fem::SolverElmer":
        addintabs._need_program("ElmerSolver", "Elmer")
        try:
            from femsolver import settings
            found = settings.get_binary("ElmerSolver", silent=True)
        except Exception:
            found = True
        if not found:
            raise RuntimeError("Elmer is not installed. Install Elmer, or set its path in Edit > Preferences > FEM > Elmer.")
    from femsolver import run
    run.run_fem_solver(solver, blocking=True)
    analysis.Document.recompute()
    return ""


def run_all(doc, flow=None, progress=None):
    """Runs every study in turn. Returns [(study, ok, text)]."""
    out = []
    for a in studies(doc, flow):
        if progress is not None:
            progress(a)
        try:
            out.append((a.Label, True, run_one(a)))
        except Exception as error:
            out.append((a.Label, False, str(error)))
    return out


# ------------------------------------------------------------------ duplicate
SKIP = ("Fem::FemResultObject", "Fem::FemPostPipeline", "Fem::FemPostObject", "App::TextDocument")


def duplicate(analysis, label=None):
    ""

    doc = analysis.Document
    import ObjectsFem
    new = ObjectsFem.makeAnalysis(doc, analysis.Name)
    new.Label = label or next_label(doc, analysis.Label)
    copies = {}
    for o in analysis.Group:
        if any(o.isDerivedFrom(t) for t in SKIP):
            continue
        c = doc.copyObject(o, False)
        copies[o.Name] = c
        kids = list(getattr(o, "Group", None) or [])
        if kids and hasattr(c, "Group"):
            mine = []
            for k in kids:
                kc = doc.copyObject(k, False)
                copies[k.Name] = kc
                mine.append(kc)
            c.Group = mine
        new.addObject(c)
    # the copies point at each other, not back at the original study's objects
    for c in copies.values():
        for prop in c.PropertiesList:
            if prop in ("Group", "ExpressionEngine", "Label", "Label2"):
                continue
            try:
                v = c.getPropertyByName(prop)
            except Exception:
                continue
            if isinstance(v, App.DocumentObject) and v.Name in copies:
                setattr(c, prop, copies[v.Name])
            elif isinstance(v, list) and v and all(isinstance(x, App.DocumentObject) for x in v) and \
                    any(x.Name in copies for x in v):
                setattr(c, prop, [copies.get(x.Name, x) for x in v])
    for m in new.Group:          # an empty mesh: Run makes it again
        if getattr(getattr(m, "Proxy", None), "Type", "") == "Fem::FemMeshGmsh":
            try:
                import Fem
                m.FemMesh = Fem.FemMesh()
            except Exception as _fw_err:
                _fw_log("studytools.py:mesh", _fw_err)
    doc.recompute()
    return new


def next_label(doc, label):
    ""
    have = {o.Label for o in doc.Objects}
    n = 1
    while "Copy[%d]-%s" % (n, label) in have:
        n += 1
    return "Copy[%d]-%s" % (n, label)


# ------------------------------------------------------------------ the commands
KEYS = (
    ("SIM_Compare", "Compare Results", ("SWStyle_SimCompare",),
     "Every study of the part side by side: its type, whether it has run, its main results.", "Compare\nResults"),
    ("SIM_RunAll", "Run All Studies", ("SWStyle_SimRunAll",), "Runs every study of the document in turn.", None),
    ("SIM_Duplicate", "Duplicate Study", ("SWStyle_SimDuplicate",),
     "A copy of the active study with its setup, without its results.", None),
    ("FLOW_Clone", "Clone Project", ("SWStyle_FlowClone",), "A copy of the active flow project with its setup.", None),
    ("FLOW_BatchRun", "Batch Run", ("SWStyle_FlowBatchRun",), "Runs every flow project of the document in turn.",
     "Batch\nRun"),
    ("FLOW_Capture", "Screen Capture", ("Std_ViewScreenShot",), "Saves a picture of the view.", "Screen\nCapture"),
    ("FLOW_EngDB", "Engineering Database", ("FEM_MaterialEditor",), "The material and fluid database.", None),
    ("CAM_Probe", "Probe Operation", ("CAM_Probe",), "Probes the stock or the part with a touch probe.", "Probe\nOperation"),
    ("CAM_Options", "CAM Options", ("SWStyle_CAMOptions",), "The CAM settings: job, assets and dressups.", "CAM\nOptions"),
    # these three replace addintabs' own keys (installed first): FreeCAD's commands are greyed until a job or an operation

    ("CAM_Post", "Post Process", ("SWStyle_CAMPost", "CAM_Post"), "Writes G-code for your machine.", "Post\nProcess"),
    ("CAM_Sanity", "Check Job", ("SWStyle_CAMCheck", "CAM_Sanity"), "Checks the job for problems and writes a report.", "Check\nJob"),
    ("CAM_Inspect", "Step Thru Toolpath", ("SWStyle_CAMStep", "CAM_Inspect"), "Lists the G-code of the picked (or first) toolpath.",
     "Step Thru\nToolpath"),
)


if Gui is not None:
    def _main():
        return Gui.getMainWindow()

    def _active(doc, flow=None):
        from . import addintabs
        a = addintabs._active_analysis(doc) if doc is not None else None
        if a is not None and (flow is None or is_flow(a) == flow):
            return a
        found = studies(doc, flow)
        return found[-1] if found else None

    class CompareDialog(QtWidgets.QDialog):
        def __init__(self, doc, parent=None):
            super().__init__(parent or _main())
            self.doc = doc
            self.setObjectName("SWCompareResults")
            self.setWindowTitle("Compare Results")
            lay = QtWidgets.QVBoxLayout(self)
            self.table = QtWidgets.QTableWidget(self)
            self.table.setObjectName("SWCompareResultsTable")
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            lay.addWidget(self.table)
            row = QtWidgets.QHBoxLayout()
            self.show_btn = QtWidgets.QPushButton("Show")
            self.show_btn.setObjectName("SWCompareResultsShow")
            self.show_btn.setToolTip("Makes the picked study the active one and shows its result.")
            self.refresh_btn = QtWidgets.QPushButton("Refresh")
            self.refresh_btn.setObjectName("SWCompareResultsRefresh")
            close = QtWidgets.QPushButton("Close")
            row.addWidget(self.show_btn)
            row.addWidget(self.refresh_btn)
            row.addStretch(1)
            row.addWidget(close)
            lay.addLayout(row)
            self.show_btn.clicked.connect(self.show_picked)
            self.refresh_btn.clicked.connect(self.fill)
            close.clicked.connect(self.close)
            self.table.itemSelectionChanged.connect(self._gate)
            self.table.itemDoubleClicked.connect(lambda *a: self.show_picked())
            self.resize(720, 260)
            self.fill()

        def fill(self):
            cols, rows = compare_table(self.doc)
            self.labels = [r[0] for r in rows]
            self.table.clear()
            self.table.setColumnCount(len(cols))
            self.table.setRowCount(len(rows))
            self.table.setHorizontalHeaderLabels(cols)
            for i, r in enumerate(rows):
                for j, v in enumerate(r):
                    self.table.setItem(i, j, QtWidgets.QTableWidgetItem(v))
            self.table.resizeColumnsToContents()
            if rows:
                self.table.selectRow(0)
            self._gate()

        def _picked(self):
            i = self.table.currentRow()
            if i < 0 or i >= len(self.labels):
                return None
            found = [a for a in studies(self.doc) if a.Label == self.labels[i]]
            return found[0] if found else None

        def _gate(self):
            a = self._picked()
            self.show_btn.setEnabled(a is not None)

        def show_picked(self):
            from . import addintabs
            a = self._picked()
            if a is None:
                return None
            addintabs._set_active(a)
            shown = None
            for o in self.doc.Objects:          # one study's result on screen at a time
                if o.isDerivedFrom("Fem::FemPostPipeline") or o.isDerivedFrom("Fem::FemResultObject"):
                    try:
                        o.ViewObject.Visibility = o in a.Group and o.isDerivedFrom("Fem::FemPostPipeline")
                        if o.ViewObject.Visibility:
                            shown = o
                    except Exception as _fw_err:
                        _fw_log("studytools.py:show", _fw_err)
            if shown is None:
                res = _results(a)
                if res:
                    Gui.Selection.clearSelection()
                    Gui.Selection.addSelection(res[-1])
                    shown = res[-1]
            return shown

    OPEN = []

    def compare(doc=None):
        doc = doc or App.ActiveDocument
        dlg = CompareDialog(doc)
        OPEN.append(dlg)
        dlg.finished.connect(lambda *a: OPEN.remove(dlg) if dlg in OPEN else None)
        dlg.show()
        return dlg

    def _run_all_ask(title, flow):
        doc = App.ActiveDocument
        from . import addintabs
        addintabs.load("FEM")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            done = run_all(doc, flow, lambda a: Gui.getMainWindow().statusBar().showMessage("%s: running %s..." % (title, a.Label)))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            Gui.getMainWindow().statusBar().clearMessage()
        doc.recompute()
        lines = []
        for label, ok, text in done:
            lines.append("%s: %s" % (label, "finished" if ok else "stopped: " + text))
            if ok and text:
                lines += ["    " + t for t in text.splitlines()]
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information if all(d[1] for d in done) else QtWidgets.QMessageBox.Warning,
                                    title, "\n".join(lines) or "There is no study to run.", QtWidgets.QMessageBox.Ok, _main())
        box.setObjectName("SWRunAllResult")
        box.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        box.open()
        return done

    def _duplicate_active(flow):
        doc = App.ActiveDocument
        a = _active(doc, flow)
        if a is None:
            return None
        from . import addintabs
        doc.openTransaction("Duplicate Study")
        try:
            new = duplicate(a)
        except Exception as error:
            doc.abortTransaction()
            addintabs._warn("Duplicate Study", str(error))
            return None
        doc.commitTransaction()
        addintabs._set_active(new)
        return new

    def _jobs(doc):
        return [o for o in (doc.Objects if doc is not None else []) if type(getattr(o, "Proxy", None)).__name__ == "ObjectJob"]

    def _picked_job():
        for s in Gui.Selection.getSelectionEx():
            o = s.Object
            if type(getattr(o, "Proxy", None)).__name__ == "ObjectJob":
                return o
            for p in o.InListRecursive:
                if type(getattr(p, "Proxy", None)).__name__ == "ObjectJob":
                    return p
        return None

    def _job_run(title, native, want_op=False):
        """Runs FreeCAD's command on the picked job (or operation), else on the part's only job, picking it first."""
        from . import addintabs
        doc = App.ActiveDocument
        job = _picked_job()
        if job is None:
            jobs = _jobs(doc)
            if len(jobs) > 1:
                addintabs._warn(title, "The part has %d jobs: pick the job (or one of its operations) first." % len(jobs))
                return None
            job = jobs[0] if jobs else None
        if job is None:
            addintabs._warn(title, "There is no job yet: start one with Setup.")
            return None
        picked = [s.Object for s in Gui.Selection.getSelectionEx()]
        target = job
        if want_op:
            ops = list(getattr(getattr(job, "Operations", None), "Group", None) or [])
            target = next((o for o in picked if o in ops), ops[0] if ops else None)
            if target is None:
                addintabs._warn(title, "The job has no operation yet.")
                return None
        if native == "CAM_Post" and not _post_of(job):
            return None                    # the post processor pick was cancelled: nothing written, no error
        if not any(o is target for o in picked) or len(picked) != 1:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, target.Name)
        before = set(id(w) for w in QtWidgets.QApplication.topLevelWidgets())
        Gui.runCommand(native, 0)
        # FreeCAD's Check Job draws its report pictures in new 3D views and then takes them out of the main window
        # without closing them: they were left floating on the screen (one per picture). Close the ones it left.
        prefix = doc.Label + " : "
        for w in QtWidgets.QApplication.topLevelWidgets():
            try:
                if id(w) not in before and w.isVisible() and w.windowTitle().startswith(prefix):
                    w.close()
            except RuntimeError as _fw_err:
                _fw_log("studytools.py:views", _fw_err)
        return target

    def _post_of(job):
        """The job's post processor; asked once (FreeCAD's list) when neither the job nor CAM Options name one,
        and kept on the job as FreeCAD does. FreeCAD's own Post Process stops with an error on Cancel there."""
        try:
            import Path
            try:
                from . import flowcam
                flowcam.apply_machine(job)         # the part's Define Machine, for a job made after it
            except Exception as _fw_err:
                _fw_log("studytools.py:machine", _fw_err)
            if getattr(job, "PostProcessor", "") or Path.Preferences.defaultPostProcessor():
                return True
            from Path.Post.Command import DlgSelectPostProcessor
            name = DlgSelectPostProcessor().exec_()
            if not name:
                return False
            job.PostProcessor = name
            return True
        except Exception as _fw_err:
            _fw_log("studytools.py:post", _fw_err)
            return True

    def _has_job():
        return bool(_jobs(App.ActiveDocument)) and _no_dialog()

    def cam_options():
        for group in ("CAM", "Path"):
            try:
                Gui.showPreferences(group)
                return group
            except Exception as _fw_err:
                _fw_log("studytools.py:cam", _fw_err)
        Gui.runCommand("Std_DlgPreferences", 0)
        return None

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

    def _doc_has(flow=None):
        return App.ActiveDocument is not None and bool(studies(App.ActiveDocument, flow))

    def _no_dialog():
        return not Gui.Control.activeDialog()

    COMMANDS = {
        "SWStyle_SimCompare": _Cmd("Compare Results", KEYS[0][3], lambda: compare(), lambda: _doc_has(), "FEM_PostVisualizationTable"),
        "SWStyle_SimRunAll": _Cmd("Run All Studies", KEYS[1][3], lambda: _run_all_ask("Run All Studies", None),
                                  lambda: _doc_has() and _no_dialog(), "FEM_SolverRun"),
        "SWStyle_SimDuplicate": _Cmd("Duplicate Study", KEYS[2][3], lambda: _duplicate_active(None),
                                     lambda: _doc_has() and _no_dialog(), "FEM_Analysis"),
        "SWStyle_FlowClone": _Cmd("Clone Project", KEYS[3][3], lambda: _duplicate_active(True),
                                  lambda: _doc_has(True) and _no_dialog(), "FEM_Analysis"),
        "SWStyle_FlowBatchRun": _Cmd("Batch Run", KEYS[4][3], lambda: _run_all_ask("Batch Run", True),
                                     lambda: _doc_has(True) and _no_dialog(), "FEM_SolverRun"),
        "SWStyle_CAMOptions": _Cmd("CAM Options", KEYS[8][3], cam_options, lambda: True, "preferences-system"),
        "SWStyle_CAMPost": _Cmd("Post Process", KEYS[9][3], lambda: _job_run("Post Process", "CAM_Post"), _has_job, "CAM_Post"),
        "SWStyle_CAMCheck": _Cmd("Check Job", KEYS[10][3], lambda: _job_run("Check Job", "CAM_Sanity"), _has_job, "CAM_Sanity"),
        "SWStyle_CAMStep": _Cmd("Step Thru Toolpath", KEYS[11][3], lambda: _job_run("Step Thru Toolpath", "CAM_Inspect", True),
                                _has_job, "CAM_Inspect"),
    }


def install():
    """The commands and their catalog keys (before the add-in tabs are built from them)."""
    if Gui is None:
        return
    from . import catalog, simpms, simplots, simconnect
    simpms.install()
    simplots.install()
    simconnect.install()
    have = set(Gui.listCommands())
    for name, cmd in COMMANDS.items():
        if name not in have:
            Gui.addCommand(name, cmd)
    for key, label, natives, tip, caption in KEYS:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, natives, None, tip, caption=caption)
