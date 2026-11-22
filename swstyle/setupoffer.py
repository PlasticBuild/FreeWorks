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


import FreeCAD as App

try:
    import FreeCADGui as Gui
except ImportError:  # pragma: no cover
    Gui = None

try:
    from PySide import QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtWidgets

ASK = {"answer": None, "asked": []}      # checks: True / False answers the question; asked keeps its text
FLOW_TAB = "Flow Simulation"
CAM_OWN = ("CAM_Setup",)                 # makes the Job itself
RESULT_KEYS = ("FLOW_Results", "SIM_Plot", "SIM_Results", "SIM_Section", "SIM_IsoClip", "SIM_Probe", "SIM_ListLine",
               "SIM_PlotTools", "SIM_Deform", "SIM_Linearized", "SIM_Purge")
MESH_KEYS = ("SIM_MeshControl", "SIM_MeshBoundary", "SIM_MeshInfo", "SIM_Diagnostic")
DRESSUP_KEYS = ("CAM_Dogbone", "CAM_Tag", "CAM_LeadInOut", "CAM_Ramp", "CAM_Boundary")
SIM_TAB = "Simulation"
SIM_RESULT_KEYS = ("SIM_Results", "SIM_Plot", "SIM_Deform", "SIM_IsoClip", "SIM_PlotTools", "SIM_Section", "SIM_Probe",
                   "SIM_ListLine", "SIM_Linearized")
SOLVER_KEYS = ("FLOW_Equation", "FLOW_Heat", "FLOW_Project", "SIM_SolverControl")
SIM_OWN = ("SIM_NewStudy",)              # makes the study itself (the Advisors start one too)
OFFER_KEYS = ("MBD_Stack", "ECAD_Update")    # extapps76: their own offers below


def _doc():
    return App.ActiveDocument


def _busy():
    try:
        return bool(Gui.Control.activeDialog())
    except Exception:
        return False


def _active(name):
    try:
        c = Gui.Command.get(name)
        return c is not None and bool(c.isActive())
    except Exception:
        return False


def _tab():
    try:
        from . import shell
        return shell.shell().topbar.current_page().title
    except Exception:
        return ""


def handles(key):
    if not key:
        return False
    if key.startswith("CAM_"):
        return key not in CAM_OWN
    if key.startswith("FLOW_"):
        return key != "FLOW_New"
    if key == "MBD_CopyScheme" or key in OFFER_KEYS:
        return True
    if key in SIM_RESULT_KEYS and _tab() == SIM_TAB:
        return True
    if key.startswith("SIM_") and key not in SIM_OWN and "Advisor" not in key and _tab() == SIM_TAB:
        return _no_study()          # extapps76: with no study, a Simulation button offers one
    return key.startswith("SIM_") and _tab() == FLOW_TAB


def enabled(key, native):
    """True when the button's command cannot act yet but clicking it can start what it needs."""
    if Gui is None or not native or _doc() is None or _busy():
        return False
    try:
        return handles(key) and not _active(native)
    except Exception as _fw_err:
        _fw_log("setupoffer.py:enabled", _fw_err)
        return False


def takes(key, native):
    """True when a click goes to run(): the command cannot act, or a dress-up whose pick is not an operation
    (FreeCAD would make a broken dress-up on the job, another dress-up or nothing)."""
    if enabled(key, native):
        return True
    if key not in DRESSUP_KEYS or Gui is None or _doc() is None or _busy():
        return False
    try:
        sel = Gui.Selection.getSelection()
        return not (len(sel) == 1 and _is_op(sel[0]))
    except Exception:
        return False


def _ask(title, text):
    ASK["asked"].append(text)
    if ASK["answer"] is not None:
        return bool(ASK["answer"])
    r = QtWidgets.QMessageBox.question(Gui.getMainWindow(), title, text,
                                       QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.Yes)
    return r == QtWidgets.QMessageBox.Yes


def _tell(title, text):
    ASK["asked"].append(text)
    if ASK["answer"] is not None:
        return
    QtWidgets.QMessageBox.information(Gui.getMainWindow(), title, text)


def _label(key):
    try:
        from . import catalog
        return catalog.BY_KEY[key].label
    except Exception:
        return key


def _natives(key, native):
    try:
        from . import catalog
        names = list(catalog.BY_KEY[key].natives)
    except Exception:
        names = []
    if native in names:
        names.remove(native)
    return [native] + names


def _select(objs):
    try:
        Gui.Selection.clearSelection()
        for o in objs:
            if o is not None:
                Gui.Selection.addSelection(o.Document.Name, o.Name)
    except Exception as _fw_err:
        _fw_log("setupoffer.py:select", _fw_err)


def _try(names, candidates, first=True):
    """Picks each candidate in turn (the user's pick first): runs the first command that can act. True when one ran."""
    before = []
    try:
        before = list(Gui.Selection.getSelection())
    except Exception as _fw_err:
        _fw_log("setupoffer.py:before", _fw_err)
    for pick in ([None] if first else []) + [c for c in candidates if c is not None]:
        if pick is not None:
            _select([pick])
        for name in names:
            if _active(name):
                Gui.runCommand(name, 0)
                return True
    _select(before)
    return False


def _run_key(key):
    try:
        from . import catalog
        for name in catalog.BY_KEY[key].natives:
            if _active(name):
                Gui.runCommand(name, 0)
                return True
    except Exception as _fw_err:
        _fw_log("setupoffer.py:runkey", _fw_err)
    return False


# --------------------------------------------------------------------------- CAM
def _jobs(doc):
    return [o for o in doc.Objects if o.Name.startswith("Job") and hasattr(o, "Operations")]


def _ops(job):
    try:
        return list(job.Operations.Group)
    except Exception:
        return []


def _is_op(o):
    """A machining operation (it has a tool controller and depths), not a dress-up, array or copy of one."""
    return hasattr(o, "ToolController") and hasattr(o, "StartDepth") and hasattr(o, "Active")


def _cam(key, names):
    doc, label = _doc(), _label(key)
    jobs = _jobs(doc)
    if not jobs:
        if _ask(label, "%s needs a CAM Job: the part, its stock and the machine origin.\n\nCreate a Job now?" % label):
            Gui.runCommand("CAM_Job", 0)
        return True
    sel = [o for o in Gui.Selection.getSelection()]
    job = jobs[-1]
    for o in sel:
        for j in jobs:
            if o == j or o in _ops(j):
                job = j
    ops = [o for o in _ops(job) if _is_op(o)]       # an operation itself, never a dress-up: a dress-up on a dress-up
    made = [o for o in ops if getattr(getattr(o, "Path", None), "Commands", None)]   # loops (FreeCAD: cyclic)
    tools = list(getattr(job, "Tools", None).Group) if getattr(job, "Tools", None) is not None else []
    if key in DRESSUP_KEYS:
        candidates = list(reversed(made)) + list(reversed(ops))     # the last operation, never the job or a dress-up
        if candidates and _try(names, candidates, first=False):
            return True
    else:
        candidates = list(reversed(made)) + list(reversed(ops)) + [job] + tools
        if _try(names, candidates):
            return True
    if not ops:
        if _ask(label, "%s needs a toolpath operation in %s.\n\nAdd a Contour Mill now?" % (label, job.Label)):
            _select([job])
            _run_key("CAM_Profile")
        return True
    if not made:
        if _ask(label, "%s needs a generated toolpath.\n\nGenerate the toolpaths now?" % label):
            doc.recompute()
            if not _try(names, [o for o in reversed(ops)] + [job]):
                _tell(label, "%s: no operation of %s made a toolpath. Check the operations' faces and tools." % (label, job.Label))
        return True
    _tell(label, "%s cannot act on %s. Pick the operation or the job it is for in the tree, then click it again." % (label, job.Label))
    return True


# --------------------------------------------------------------------------- Flow Simulation
def _flows(doc):
    try:
        from . import simtree
        return simtree.studies(doc, True)
    except Exception:
        return []


def _active_flow(doc, flows):
    try:
        from . import addintabs
        a = addintabs._active_analysis(doc)
        if a in flows:
            return a
        addintabs._set_active(flows[-1])
    except Exception as _fw_err:
        _fw_log("setupoffer.py:activeflow", _fw_err)
    return flows[-1]


def _has_result(a):
    for o in a.Group:
        t = o.TypeId
        if "Result" in t or "FemPost" in t or o.isDerivedFrom("Fem::FemResultObject"):
            return True
    return False


def _flow(key, names):
    doc, label = _doc(), _label(key)
    flows = _flows(doc)
    if not flows:
        if _ask(label, "%s needs a flow project: the fluid region, the fluid and the flow solver.\n\nStart a flow project now?" % label):
            Gui.runCommand("SWStyle_FlowNewProject", 0)
        return True
    a = _active_flow(doc, flows)
    from . import simtree, simpms
    mesh = simpms.gmsh_of(a)
    solver = simtree._solver(a)
    shape = getattr(mesh, "Shape", None) if mesh is not None else None
    if shape is None:
        try:
            from . import addintabs
            shape = addintabs._main_solid(doc)
        except Exception as _fw_err:
            _fw_log("setupoffer.py:shape", _fw_err)
    if key in RESULT_KEYS:
        candidates = [simtree._pipeline(a)] + [o for o in a.Group if "Result" in o.TypeId]
    elif key in MESH_KEYS:
        candidates = [mesh]
    elif key in SOLVER_KEYS:
        candidates = [solver]
    else:
        candidates = [shape, mesh, solver, a]
    if _try(names, candidates):
        return True
    if key in RESULT_KEYS and not _has_result(a):
        if _ask(label, "%s needs results of %s.\n\nRun the project now?" % (label, a.Label)):
            _run_key("SIM_Run")
        return True
    if key in MESH_KEYS and mesh is None:
        if _ask(label, "%s needs a mesh of %s.\n\nMesh the fluid region now?" % (label, a.Label)):
            if shape is not None:
                _select([shape])
            _run_key("SIM_Mesh")
        return True
    if key in SOLVER_KEYS and solver is None:
        if _ask(label, "%s needs the flow solver in %s.\n\nAdd it now?" % (label, a.Label)):
            _run_key("SIM_SolverElmer")
        return True
    _tell(label, "%s cannot act on %s yet. Pick the face, body or result it is for, then click it again." % (label, a.Label))
    return True


# --------------------------------------------------------------------------- Simulation results
def _result_candidates(a):
    from . import simtree
    return [simtree._pipeline(a)] + [o for o in a.Group if o.isDerivedFrom("Fem::FemResultObject")]


def _sim_result(key, names):
    """A result tool on the Simulation tab: the study's plot or result picked for it, or a run first."""
    from . import simtree
    label = _label(key)
    a = simtree._ctx_study()
    if a is None:
        if _ask(label, "%s needs a study with results.\n\nStart a new study now?" % label):
            _run_key("SIM_NewStudy")
        return True
    if _try(names, _result_candidates(a)):
        return True
    if not _has_result(a):
        if not _ask(label, "%s needs results of %s.\n\nRun the study now?" % (label, a.Label)):
            return True
        _run_key("SIM_Run")
        if _has_result(a) and _try(names, _result_candidates(a), first=False):
            return True
        if _has_result(a):
            return True                     # Run shows the first plot; the tool can act on it from here
        _tell(label, "%s has no results yet: the run did not finish. Its messages are in the Report view." % a.Label)
        return True
    _tell(label, "%s cannot act on %s yet. Pick the plot or result it is for, then click it again." % (label, a.Label))
    return True


def _no_study():
    try:
        from . import simtree
        return simtree._ctx_study() is None
    except Exception:
        return False


def _sim_study(key, names):
    ""
    label = _label(key)
    if _ask(label, "%s needs a study.\n\nStart a new study now?" % label):
        _run_key("SIM_NewStudy")
    return True


# --------------------------------------------------------------------------- MBD
def _stack_up(key, names):
    """extapps76: Tolerance Stack-Up Study with no annotations offers Auto Dimension Scheme."""
    label = _label(key)
    if _ask(label, "%s works on the part's annotations, and the part has none yet.\n\n"
                   "Add annotations now (Auto Dimension Scheme)?" % label):
        _run_key("MBD_Auto")
    return True


def _ecad_update(key, names):
    """extapps76: Update Model on a model not built from an ECAD file offers Open ECAD File."""
    label = _label(key)
    if _ask(label, "%s reads the ECAD file of a board built here, and this model has none.\n\n"
                   "Open an ECAD file now?" % label):
        _run_key("ECAD_Open")
    return True


def _copy_scheme(key, names):
    label = _label(key)
    try:
        from . import mbd, configmanager
        doc = _doc()
        if not any(mbd.is_pmi(o) for o in doc.Objects):
            if _ask(label, "%s copies a configuration's annotations, and the part has none yet.\n\n"
                           "Add annotations now (Auto Dimension Scheme)?" % label):
                _run_key("MBD_Auto")
            return True
        t = configmanager.table(doc)
        if t is None or len(t.names()) < 2:
            if _ask(label, "%s needs a second configuration to copy the annotations to.\n\nAdd a configuration now?" % label):
                configmanager.add_configuration(doc)
            return True
    except Exception as _fw_err:
        _fw_log("setupoffer.py:copyscheme", _fw_err)
    _tell(label, "%s cannot act yet: it needs annotations and two configurations." % label)
    return True


def run(key, native):
    """Handles a click on a button whose command cannot act: True when handled here (nothing else to do)."""
    if Gui is None or not native or _doc() is None or not takes(key, native):
        return False
    names = _natives(key, native)
    try:
        if key.startswith("CAM_"):
            return _cam(key, names)
        if key == "MBD_CopyScheme":
            return _copy_scheme(key, names)
        if key == "MBD_Stack":
            return _stack_up(key, names)
        if key == "ECAD_Update":
            return _ecad_update(key, names)
        if key in SIM_RESULT_KEYS and _tab() == SIM_TAB:
            return _sim_result(key, names)
        if key.startswith("SIM_") and "Advisor" not in key and _tab() == SIM_TAB:
            return _sim_study(key, names)
        return _flow(key, names)
    except Exception as error:
        App.Console.PrintError("FreeCAD: %s: %s\n" % (_label(key), error))
        return True
