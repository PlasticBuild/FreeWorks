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

import contextlib
import html
import json
import math
import os
import time

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

TITLE = "SimulationXpress"
STUDY_LABEL = "SimulationXpress Study"
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SimulationXpress"
TAB = ("FLYOUT_SIMULATION", "SimulationXpress", "simxpress")
STEPS = ["Welcome", "Fixtures", "Loads", "Material", "Run", "Results", "Optimize"]

FIXED, FORCE, PRESSURE = "Fem::ConstraintFixed", "Fem::ConstraintForce", "Fem::ConstraintPressure"

# E (MPa), Poisson's ratio, yield strength (MPa): generic handbook values for the common names
# (material.COMMON) the FreeCAD material library has no card for
MECH = {
    "Plain Carbon Steel": (210000, 0.28, 220), "AISI 1020": (200000, 0.29, 350), "AISI 304": (190000, 0.29, 207),
    "Alloy Steel": (210000, 0.28, 620), "Cast Alloy Steel": (190000, 0.26, 241),
    "Gray Cast Iron": (66000, 0.27, 150), "Malleable Cast Iron": (190000, 0.27, 275),
    "1060 Alloy": (69000, 0.33, 28), "6061 Alloy": (69000, 0.33, 55), "6063-T6": (69000, 0.33, 215),
    "7075-T6": (72000, 0.33, 505), "Brass": (100000, 0.33, 240), "Copper": (110000, 0.37, 260),
    "Nickel": (200000, 0.31, 150), "Ti-6Al-4V": (114000, 0.34, 830),
    "ABS": (2000, 0.39, 40), "ABS PC": (2400, 0.39, 50), "Acrylic (Medium-high impact)": (3000, 0.35, 45),
    "Nylon 6/10": (2600, 0.3, 140), "PE High Density": (1070, 0.41, 22), "PP Copolymer": (900, 0.41, 28),
    "PLA": (3500, 0.36, 50), "PETG": (2100, 0.38, 50), "PBT General Purpose": (2400, 0.39, 52),
    "Rubber": (6, 0.49, 14), "Balsa": (3000, 0.29, 10), "Pine": (9000, 0.29, 35), "Oak": (11000, 0.3, 45),
}

# units system -> (stress unit, factor from MPa, length unit, factor from mm)
UNITS = {"SI": ("N/m^2", 1e6, "mm", 1.0), "English (IPS)": ("psi", 145.0377, "in", 1 / 25.4),
         "Metric (G)": ("kgf/cm^2", 10.19716, "mm", 1.0)}
FORCE_UNITS = {"N": 1.0, "lbf": 4.448222, "kgf": 9.80665}
PRESSURE_UNITS = {"N/m^2": 1e-6, "MPa": 1.0, "psi": 1 / 145.0377, "kgf/cm^2": 1 / 10.19716}
CONSTRAINTS = ["Factor of safety", "Max von Mises stress", "Max displacement"]


def params():
    return App.ParamGet(PARAMS)


def units():
    u = params().GetString("Units", "SI")
    return u if u in UNITS else "SI"


@contextlib.contextmanager
def fem_safe():
    """asmmotion's colour watch (a Gui observer with slotChangedObject) off while FEM objects are made."""
    w = getattr(Gui, "_fw_lookwatch", None) if Gui is not None else None
    off = False
    if w is not None:
        try:
            Gui.removeDocumentObserver(w)
            off = True
        except Exception as _fw_err:
            _fw_log("simxpress.py:109", _fw_err)
    try:
        yield
    finally:
        if off:
            try:
                Gui.addDocumentObserver(w)
            except Exception as _fw_err:
                _fw_log("simxpress.py:117", _fw_err)


# --------------------------------------------------------------------------- the study
def _hide_row(o):
    try:
        o.ViewObject.ShowInTree = False
    except Exception as _fw_err:
        _fw_log("simxpress.py:125", _fw_err)


def study(doc, create=False):
    for o in getattr(doc, "Objects", []):
        if o.TypeId == "Fem::FemAnalysis" and "FwXpress" in o.PropertiesList:
            return o
    if not create:
        return None
    import ObjectsFem
    with fem_safe():
        a = ObjectsFem.makeAnalysis(doc, "SimulationXpressStudy")
    a.addProperty("App::PropertyBool", "FwXpress", "SimulationXpress", "FreeCAD's SimulationXpress study")
    a.addProperty("App::PropertyString", "FwSummary", "SimulationXpress", "The last run's results (JSON)")
    a.addProperty("App::PropertyLink", "FwTarget", "SimulationXpress", "The body studied")
    a.FwXpress = True
    a.Label = STUDY_LABEL
    _hide_row(a)
    return a


def members(a, type_id):
    return [o for o in (a.Group if a is not None else []) if o.TypeId == type_id]


def fixtures(a):
    return members(a, FIXED)


def loads(a):
    return [o for o in (a.Group if a is not None else []) if o.TypeId in (FORCE, PRESSURE)]


def target(doc):
    a = study(doc)
    t = getattr(a, "FwTarget", None) if a is not None else None
    if t is not None:
        return t
    from . import evaltools
    return evaltools._main(doc)


def _next_label(a, base):
    used = {o.Label for o in a.Group}
    n = 1
    while "%s-%d" % (base, n) in used:
        n += 1
    return "%s-%d" % (base, n)


def _faces(obj, faces):
    return [(obj, list(faces))]


def add_fixture(doc, obj, faces, edit=None):
    import ObjectsFem
    a = study(doc, True)
    a.FwTarget = obj
    with fem_safe():
        fx = edit if edit is not None else ObjectsFem.makeConstraintFixed(doc, "XpressFixed")
        fx.References = _faces(obj, faces)
        if edit is None:
            a.addObject(fx)
            fx.Label = _next_label(a, "Fixed")
    _hide_row(fx)
    doc.recompute()
    return fx


def _keep(o, **values):
    for k, v in values.items():
        prop = "Fw" + k
        if prop not in o.PropertiesList:
            kind = {bool: "App::PropertyBool", float: "App::PropertyFloat", str: "App::PropertyString"}[type(v)]
            o.addProperty(kind, prop, "SimulationXpress", "What the PropertyManager was given")
        setattr(o, prop, v)


def _outward_push(ld, obj, face):
    ""
    try:
        f = obj.Shape.getElement(face)
        u, v = f.Surface.parameter(f.CenterOfMass)
        n = f.normalAt(u, v)
        d = ld.DirectionVector
        if d.Length > 0 and d.dot(n) > 0:
            return True        # pulls: flip
    except Exception as _fw_err:
        _fw_log("simxpress.py:213", _fw_err)
    return False


def add_force(doc, obj, faces, value, unit="N", direction=None, reverse=False, per_item=False, edit=None):
    """A force on faces: normal to them (direction None) or along a picked edge / face / plane."""
    import ObjectsFem
    a = study(doc, True)
    a.FwTarget = obj
    newtons = float(value) * FORCE_UNITS.get(unit, 1.0) * (len(faces) if per_item else 1)
    with fem_safe():
        ld = edit if edit is not None else ObjectsFem.makeConstraintForce(doc, "XpressForce")
        ld.References = _faces(obj, faces)
        ld.Force = "%r N" % newtons
        ld.Direction = (direction[0], [direction[1]]) if direction else None
        ld.Reversed = False                 # an edited force: its normal is read unflipped, then Reverse applies
        if edit is None:
            a.addObject(ld)
            ld.Label = _next_label(a, "Force")
    doc.recompute()
    flip = _outward_push(ld, obj, faces[0]) if direction is None else False
    ld.Reversed = bool(reverse) != flip
    _keep(ld, Value=float(value), Unit=unit, PerItem=bool(per_item), Reverse=bool(reverse))
    _hide_row(ld)
    doc.recompute()
    return ld


def add_pressure(doc, obj, faces, value, unit="N/m^2", reverse=False, edit=None):
    import ObjectsFem
    a = study(doc, True)
    a.FwTarget = obj
    mpa = float(value) * PRESSURE_UNITS.get(unit, 1.0)
    with fem_safe():
        ld = edit if edit is not None else ObjectsFem.makeConstraintPressure(doc, "XpressPressure")
        ld.References = _faces(obj, faces)
        ld.Pressure = "%r MPa" % mpa
        ld.Reversed = bool(reverse)
        if edit is None:
            a.addObject(ld)
            ld.Label = _next_label(a, "Pressure")
    _keep(ld, Value=float(value), Unit=unit, Reverse=bool(reverse))
    _hide_row(ld)
    doc.recompute()
    return ld


def remove(doc, o):
    a = study(doc)
    if a is not None and o in a.Group:
        a.removeObject(o)
    doc.removeObject(o.Name)
    doc.recompute()


def delete_study(doc):
    a = study(doc)
    if a is None:
        return
    reset_plot()
    names = [o.Name for o in a.Group] + [a.Name]
    for o in list(a.Group):
        if o.isDerivedFrom("Fem::FemResultObject") and getattr(o, "Mesh", None) is not None:
            names.append(o.Mesh.Name)
    for n in names:
        if doc.getObject(n) is not None:
            doc.removeObject(n)
    doc.recompute()


# --------------------------------------------------------------------------- the material
def material_values(doc):
    """(name, E MPa, Poisson, yield MPa, density kg/m^3) of the part's material, or None (no material)."""
    from . import material
    dens, name = material.current(doc)
    if not name:
        return None
    vals = {}
    try:
        from . import materialdlg
        vals = dict(materialdlg.part_data(doc).get("values", {}))
        if not vals.get("YoungsModulus"):
            found = materialdlg.find(name)
            if found:
                vals = dict(found[2].get("values", {}), **vals)
    except Exception as _fw_err:
        _fw_log("simxpress.py:298", _fw_err)
    e = (vals.get("YoungsModulus") or 0) / 1e6
    nu = vals.get("PoissonRatio") or 0
    y = (vals.get("YieldStrength") or 0) / 1e6
    mech = MECH.get(name) or MECH.get(name.replace("-Generic", ""))
    if mech is None:
        from . import evaltools
        m = evaltools.MATERIALS.get(name)
        mech = (m[2], m[3], m[1]) if m else None
    if mech is not None:
        e, nu, y = e or mech[0], nu or mech[1], y or mech[2]
    if not e:
        return None
    return name, float(e), float(nu or 0.3), float(y or 0.0), float(dens or vals.get("Density") or 7800)


# --------------------------------------------------------------------------- mesh and run
def high_quality(mesh):
    ""

    for name, value in (("ElementOrder", "2nd"), ("HighOrderOptimize", "Optimization")):
        try:
            if value in mesh.getEnumerationsOfProperty(name):
                setattr(mesh, name, value)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: mesh %s kept (%s)\n" % (name, error))


# CalculiX's exit when it crashed: Windows' access violation (0xC0000005, either sign), or a POSIX segfault
CRASHED = (3221225477, -1073741819, -11, 139)
OUT_OF_MEMORY = (-9, 137, 3221225495, -1073741801)   # killed (Linux OOM) / STATUS_NO_MEMORY (Windows)


def _ccx_live(fea, threads=None):
    """fea.ccx_run() as FreeCAD 1.1 does it (the same command, OMP_NUM_THREADS = every core unless the FEM preference
    asks for 2 or more, *NOANALYSIS's 201 taken as done), with the run window live while CalculiX works."""
    import multiprocessing
    from . import simrun
    fea.ccx_stdout, fea.ccx_stderr = "", ""
    fea.setup_ccx()
    if getattr(fea, "ccx_binary_present", True) is False:
        return None
    pref = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx").GetInt("AnalysisNumCPUs", 1)
    env = dict(os.environ)
    env["OMP_NUM_THREADS"] = str(threads or (pref if pref > 1 else multiprocessing.cpu_count()))
    folder, name = os.path.split(fea.inp_file_name)
    App.Console.PrintMessage("CalculiX solver run...\n")
    code, out, err = simrun.run_process([fea.ccx_binary, "-i", os.path.splitext(name)[0]], folder or None, env, "Solving")
    fea.ccx_stdout, fea.ccx_stderr = out.decode(errors="replace"), err.decode(errors="replace")
    if code == 201 and getattr(getattr(fea, "solver", None), "AnalysisType", "") == "check":
        code = 0                                        # FreeCAD's own workaround for *NOANALYSIS
    if code:
        App.Console.PrintError("CalculiX failed with exit code %s\n" % code)
        App.Console.PrintMessage("%s\n%s\n" % (fea.ccx_stdout[-4000:], fea.ccx_stderr[-2000:]))
    else:
        App.Console.PrintMessage("CalculiX finished without error.\n")
    return code


def run_ccx(fea):
    """CalculiX for fea with the run window live, once more on one thread if it crashed. FreeCAD 1.1 runs it on every
    core (OMP_NUM_THREADS = cpu_count unless the FEM preference asks for 2 or more), and threaded Spooles can crash
    now and then."""
    code = _ccx_live(fea)
    if code in CRASHED:
        App.Console.PrintWarning("CalculiX crashed (exit code %s): running it again on one thread.\n" % code)
        from . import simrun
        simrun.say("CalculiX crashed (exit code %s): running it again on one thread." % code)
        code = _ccx_live(fea, threads=1)
    return code


class _Done:
    def __init__(self, code, out):
        self.returncode, self.stdout = code, out


def run_ccx_command(args, cwd, env, timeout):
    """CalculiX (stdout with stderr) with the run window live, once more on one thread if it crashed. Returns an
    object with returncode and stdout (bytes), as subprocess.run does."""
    from . import simrun
    code, out, _e = simrun.run_process(args, cwd, env, "Solving", timeout=timeout, merge=True)
    if code in CRASHED and env.get("OMP_NUM_THREADS") != "1":
        App.Console.PrintWarning("CalculiX crashed (exit code %s): running it again on one thread.\n" % code)
        code, out, _e = simrun.run_process(args, cwd, dict(env, OMP_NUM_THREADS="1"), "Solving", timeout=timeout,
                                           merge=True)
    return _Done(code, out)


def solver_stopped(fea, code):
    """Raises with the reason, in plain words, when CalculiX ended without solving."""
    if not code:
        if code is None and getattr(fea, "ccx_binary_present", True) is False:
            raise RuntimeError("CalculiX is not installed, so the study cannot run.")
        return
    text = "%s\n%s" % (getattr(fea, "ccx_stdout", "") or "", getattr(fea, "ccx_stderr", "") or "")
    if "nonpositive jacobian" in text:
        raise RuntimeError("The solver stopped because the mesh has distorted elements.\n"
                           "Make the mesh finer and run again.")
    errors = [line.replace("*ERROR", "").strip(" :") for line in text.splitlines() if "*ERROR" in line]
    if code in OUT_OF_MEMORY or "not enough memory" in text.lower() or "out of memory" in text.lower():
        raise RuntimeError("CalculiX ran out of memory, so the study has no results. Make the mesh coarser "
                           "(Mesh > Create Mesh..., move the slider toward Coarse) and run again.")
    if not errors and code in CRASHED:
        raise RuntimeError("CalculiX crashed (exit code %s), so the study has no results. Run it again; if it "
                           "crashes again, make the mesh coarser, or install CalculiX again." % code)
    raise RuntimeError("The solver stopped: %s" % errors[0] if errors else "The solver stopped (exit code %s)." % code)


def mesh_size(shape, density=None):
    ""
    d = params().GetInt("MeshDensity", 5) if density is None else density
    return max(shape.BoundBox.DiagonalLength / (8.0 + 3.0 * max(0, min(10, d))), 0.2)


def _one(a, test, make):
    for o in a.Group:
        if test(o):
            return o
    o = make()
    a.addObject(o)
    return o


def run(doc, density=None, progress=None):
    """Meshes and solves the study. Returns the summary dict (also kept in the study)."""
    import ObjectsFem
    a = study(doc)
    if a is None or not fixtures(a):
        raise RuntimeError("Add a fixture first.")
    if not loads(a):
        raise RuntimeError("Add a load first.")
    mat = material_values(doc)
    if mat is None:
        raise RuntimeError("Choose a material first.")
    obj = target(doc)
    name, e, nu, y, dens = mat
    say = progress or (lambda text: None)
    t0 = time.time()
    with fem_safe():
        m = _one(a, lambda o: o.TypeId == "App::MaterialObjectPython" or "Material" in o.Name and
                 hasattr(o, "Material") and not o.isDerivedFrom("Fem::Constraint"),
                 lambda: ObjectsFem.makeMaterialSolid(doc, "XpressMaterial"))
        card = dict(m.Material)
        card.update({"Name": name, "YoungsModulus": "%r MPa" % e, "PoissonRatio": str(nu),
                     "Density": "%r kg/m^3" % dens})
        m.Material = card
        solver = _one(a, lambda o: "Solver" in o.TypeId or "SolverCcx" in o.Name or o.Name.startswith("XpressSolver"),
                      lambda: (ObjectsFem.makeSolverCalculiXCcxTools(doc, "XpressSolver")
                               if hasattr(ObjectsFem, "makeSolverCalculiXCcxTools")
                               else ObjectsFem.makeSolverCalculiX(doc, "XpressSolver")))
        mesh = _one(a, lambda o: o.TypeId == "Fem::FemMeshGmsh" or (o.isDerivedFrom("Fem::FemMeshObject") and
                                                                    o.Name.startswith("XpressMesh")),
                    lambda: ObjectsFem.makeMeshGmsh(doc, "XpressMesh"))
        mesh.Shape = obj
        high_quality(mesh)
        size = mesh_size(obj.Shape, density)
        mesh.CharacteristicLengthMax = "%r mm" % size
        doc.recompute()
        say("Meshing")
        from femmesh.gmshtools import GmshTools
        err = GmshTools(mesh).create_mesh()
        if err:
            raise RuntimeError("Meshing failed: %s" % err)
        say("Running the solver")
        from femtools import ccxtools
        fea = ccxtools.FemToolsCcx(a, solver)
        fea.update_objects()
        fea.setup_working_dir()
        fea.setup_ccx()
        message = fea.check_prerequisites()
        if message:
            raise RuntimeError(message)
        fea.purge_results()
        fea.write_inp_file()
        solver_stopped(fea, run_ccx(fea))
        fea.load_results()
    res = result(doc)
    if res is None:
        raise RuntimeError("The solver gave no result.")
    for o in a.Group + [getattr(res, "Mesh", None)]:
        if o is not None:
            _hide_row(o)
            try:
                o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("simxpress.py:391", _fw_err)
    vm = list(res.vonMises)
    disp = list(res.DisplacementLengths)
    nodes = list(res.NodeNumbers)
    i_max, i_min = vm.index(max(vm)), vm.index(min(vm))
    j_max = disp.index(max(disp))
    fem = mesh.FemMesh
    summary = {"material": name, "e_mpa": e, "poisson": nu, "yield_mpa": y, "density": dens,
               "max_vm": vm[i_max], "min_vm": vm[i_min], "max_vm_node": nodes[i_max], "min_vm_node": nodes[i_min],
               "max_disp": disp[j_max], "min_disp": min(disp), "max_disp_node": nodes[j_max],
               "min_fos": (y / vm[i_max]) if vm[i_max] > 0 and y else None,
               "nodes": fem.NodeCount, "elements": fem.VolumeCount, "size_mm": size,
               "density_slider": params().GetInt("MeshDensity", 5) if density is None else density,
               "mass_kg": obj.Shape.Volume * 1e-9 * dens, "seconds": round(time.time() - t0, 1),
               "time": time.strftime("%Y-%m-%d %H:%M")}
    a.FwSummary = json.dumps(summary)
    return summary


def result(doc):
    a = study(doc)
    for o in reversed(a.Group if a is not None else []):
        if o.isDerivedFrom("Fem::FemResultObject") and "vonMises" in o.PropertiesList:
            return o
    return None


def summary(doc):
    a = study(doc)
    try:
        return json.loads(a.FwSummary) if a is not None and a.FwSummary else None
    except Exception:
        return None


def fos_values(res, yield_mpa):
    return [(yield_mpa / v) if v > 0 else 1e9 for v in res.vonMises]


# --------------------------------------------------------------------------- optimize
def dims(doc):
    from . import equations
    return [(n, o, p) for n, o, p, _v in equations.dimensions(doc)]


def _constraint_index(obj, path):
    import re
    p = path.lstrip(".")
    m = re.match(r"^Constraints(?:\.(\w+)|\[(\d+)\])$", p)
    if not m:
        return None
    if m.group(2):
        return int(m.group(2))
    for i, c in enumerate(obj.Constraints):
        if c.Name == m.group(1):
            return i
    return None


def dim_get(obj, path):
    i = _constraint_index(obj, path)
    if i is not None:
        c = obj.Constraints[i]
        return math.degrees(c.Value) if c.Type == "Angle" else c.Value
    v = obj.getPropertyByName(path.lstrip("."))
    return float(getattr(v, "Value", v))


def dim_set(obj, path, value):
    i = _constraint_index(obj, path)
    if i is not None:
        unit = "deg" if obj.Constraints[i].Type == "Angle" else "mm"
        obj.setDatum(i, App.Units.Quantity("%r %s" % (float(value), unit)))
    else:
        setattr(obj, path.lstrip("."), float(value))
    obj.Document.recompute()


def constraint_value(summary_, kind):
    if kind == "Factor of safety":
        return summary_.get("min_fos") or 0.0
    if kind == "Max von Mises stress":
        return summary_["max_vm"]
    return summary_["max_disp"]


def passes(kind, value, limit):
    return value >= limit if kind == "Factor of safety" else value <= limit


def optimize(doc, obj, path, lo, hi, kind, limit, steps=5, progress=None, stop=None):
    """Runs the study at the initial value and `steps` values from lo to hi; the part is left at the
    initial value. Returns {"rows": [(value, mass, constraint, ok)], "initial": row, "optimal": row|None}."""
    v0 = dim_get(obj, path)
    values = [v0] + [lo + (hi - lo) * k / max(1, steps - 1) for k in range(steps)]
    rows = []
    try:
        for n, v in enumerate(values):
            if stop is not None and stop():
                break
            if progress:
                progress("Run %d of %d (%g)" % (n + 1, len(values), v))
            dim_set(obj, path, v)
            s = run(doc)
            c = constraint_value(s, kind)
            rows.append((v, s["mass_kg"], c, passes(kind, c, limit)))
    finally:
        dim_set(obj, path, v0)
        try:
            run(doc)
        except Exception as _fw_err:
            _fw_log("simxpress.py:502", _fw_err)
    ok = [r for r in rows if r[3]]
    return {"rows": rows, "initial": rows[0] if rows else None,
            "optimal": min(ok, key=lambda r: r[1]) if ok else None}


# --------------------------------------------------------------------------- report
def report(doc, folder=None, images=None):
    """An HTML report of the study (and the plot images given: [(title, path)]). Returns its path."""
    s = summary(doc)
    if s is None:
        raise RuntimeError("Run the simulation first.")
    a = study(doc)
    obj = target(doc)
    folder = folder or result_folder(doc)
    os.makedirs(folder, exist_ok=True)
    base = (doc.Label or doc.Name)
    n = 1
    while os.path.exists(os.path.join(folder, "%s-SimulationXpress-%d.html" % (base, n))):
        n += 1
    path = os.path.join(folder, "%s-SimulationXpress-%d.html" % (base, n))
    su, sf, lu, lf = UNITS[units()]
    esc = html.escape

    def table(head, rows):
        out = ["<table><tr>%s</tr>" % "".join("<th>%s</th>" % esc(h) for h in head)]
        for r in rows:
            out.append("<tr>%s</tr>" % "".join("<td>%s</td>" % esc(str(c)) for c in r))
        return "\n".join(out) + "</table>"

    def faces(o):
        return ", ".join(sub for _ob, subs in o.References for sub in subs)

    fx = [(o.Label, "Fixed geometry", faces(o)) for o in fixtures(a)]
    ld = []
    for o in loads(a):
        if o.TypeId == FORCE:
            ld.append((o.Label, "Force", "%g %s" % (getattr(o, "FwValue", o.Force.Value / 1000.0), getattr(o, "FwUnit", "N")),
                       faces(o)))
        else:
            ld.append((o.Label, "Pressure", "%g %s" % (getattr(o, "FwValue", 0.0), getattr(o, "FwUnit", "MPa")), faces(o)))
    fos = s.get("min_fos")
    parts = ["<!doctype html><html><head><meta charset='utf-8'><title>%s</title>" % esc(base + " - " + STUDY_LABEL),
             "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}"
             "table{border-collapse:collapse;margin:6px 0 18px}td,th{border:1px solid #bbb;padding:4px 10px;"
             "text-align:left}th{background:#e8eef6}h1{color:#1f4e8c}img{max-width:720px;border:1px solid #ccc}"
             "</style></head><body>",
             "<h1>%s</h1><p>%s &middot; %s</p>" % (esc(base), esc(STUDY_LABEL), esc(s["time"])),
             "<h2>Description</h2><p>A linear static study: the part is held at its fixtures and loaded; the "
             "solver finds how far each point moves, the stress there, and the factor of safety (yield "
             "strength divided by the von Mises stress).</p>",
             "<h2>Model information</h2>",
             table(("Item", "Value"), [("Body", obj.Label if obj else ""),
                                       ("Volume", "%.3f cm^3" % (obj.Shape.Volume / 1000.0) if obj else ""),
                                       ("Mass", "%.4f kg" % s["mass_kg"])]),
             "<h2>Material</h2>",
             table(("Property", "Value"), [("Name", s["material"]), ("Elastic modulus", "%g MPa" % s["e_mpa"]),
                                           ("Poisson's ratio", "%g" % s["poisson"]),
                                           ("Yield strength", "%g MPa" % s["yield_mpa"]),
                                           ("Mass density", "%g kg/m^3" % s["density"])]),
             "<h2>Fixtures</h2>", table(("Name", "Type", "Faces"), fx),
             "<h2>Loads</h2>", table(("Name", "Type", "Value", "Faces"), ld),
             "<h2>Mesh</h2>", table(("Item", "Value"), [("Mesher", "Gmsh, solid tetrahedra"),
                                                       ("Element size", "%.3g mm" % s["size_mm"]),
                                                       ("Nodes", s["nodes"]), ("Elements", s["elements"])]),
             "<h2>Results</h2>",
             table(("Name", "Type", "Min", "Max"),
                   [("Stress1", "von Mises stress", "%.4g %s" % (s["min_vm"] * sf, su), "%.4g %s" % (s["max_vm"] * sf, su)),
                    ("Displacement1", "Resultant displacement", "%.4g %s" % (s["min_disp"] * lf, lu),
                     "%.4g %s" % (s["max_disp"] * lf, lu)),
                    ("Factor of Safety1", "Max von Mises stress", "%.3g" % fos if fos else "-", "")])]
    for title, img in images or []:
        parts.append("<h3>%s</h3><img src='%s'>" % (esc(title), esc(os.path.basename(img))))
    parts.append("<h2>Conclusion</h2><p>%s</p></body></html>" % esc(
        ("The lowest factor of safety is %.3g: %s." % (fos, "the part holds this load" if fos >= 1 else
                                                         "the part yields under this load")) if fos else
        "No yield strength is known for the material, so no factor of safety is given."))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return path


def result_folder(doc):
    saved = params().GetString("ResultsFolder", "")
    if saved:
        return saved
    if getattr(doc, "FileName", ""):
        return os.path.dirname(doc.FileName)
    return os.path.join(os.path.expanduser("~"), "FreeCAD", "SimulationXpress")


def results_file(doc, folder=None):
    """The result as a VTK file a 3D viewer opens (ParaView); a picture when VTK export is missing."""
    res = result(doc)
    if res is None:
        raise RuntimeError("Run the simulation first.")
    folder = folder or result_folder(doc)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%s-SimulationXpress.vtu" % (doc.Label or doc.Name))
    try:
        import Fem
        Fem.export([res], path)
        if os.path.exists(path):
            return path
    except Exception as error:
        App.Console.PrintLog("FreeCAD: SimulationXpress VTK export: %s\n" % error)
    path = path[:-4] + ".png"
    Gui.ActiveDocument.ActiveView.saveImage(path, 1200, 800, "Current")
    return path


# --------------------------------------------------------------------------- plots
def rainbow(t):
    """0 blue ... 1 red, through cyan, green and yellow (the result plots' colours)."""
    t = max(0.0, min(1.0, t))
    h = (1.0 - t) * 240.0 / 360.0
    c = QtGui.QColor.fromHsvF(h, 1.0, 1.0) if Gui is not None else None
    return (c.redF(), c.greenF(), c.blueF()) if c is not None else (t, 0.0, 1.0 - t)


PLOT = {"doc": None, "kind": None, "hidden": [], "legend": None, "title": None, "marks": None, "node": None, "timer": None,
        "scale": 1.0, "phase": 0.0}
KINDS = {"stress": "Stress1", "displacement": "Displacement1", "deformation": "Deformation1", "fos": "Factor of Safety1"}


def _host():
    try:
        from .featuredimshow import _viewport
        vp = _viewport()
        return vp.parentWidget() if vp is not None else None
    except Exception:
        return None


def auto_scale(doc, s=None):
    s = s or summary(doc)
    obj = target(doc)
    if not s or not s["max_disp"] or obj is None:
        return 1.0
    raw = 0.06 * obj.Shape.BoundBox.DiagonalLength / s["max_disp"]
    if raw < 1:
        return 1.0
    k = 10 ** math.floor(math.log10(raw))
    return round(raw / k) * k


def show_plot(doc, kind, fos_limit=1.0, deformed=True):
    """Colours the result mesh: stress, displacement, deformation (one colour, deformed) or fos."""
    res = result(doc)
    s = summary(doc)
    if res is None or s is None:
        raise RuntimeError("Run the simulation first.")
    stop_animation()
    _clear_overlays()
    mesh = res.Mesh
    obj = target(doc)
    if not PLOT["hidden"]:
        for o in doc.Objects:
            try:
                if o is mesh or not o.ViewObject.Visibility:
                    continue
                if o.isDerivedFrom("Part::Feature") or o.TypeId == "PartDesign::Body" or \
                        o.TypeId.startswith("Fem::Constraint"):
                    PLOT["hidden"].append(o.Name)
                    o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("simxpress.py:668", _fw_err)
    nodes = list(res.NodeNumbers)
    scale = auto_scale(doc, s) if deformed else 0.0
    PLOT.update(doc=doc, kind=kind, scale=scale, limit=fos_limit)
    su, sf, lu, lf = UNITS[units()]
    if kind == "stress":
        values, lo, hi = list(res.vonMises), s["min_vm"], s["max_vm"]
        legend = ("von Mises (%s)" % su, lo * sf, hi * sf, s["yield_mpa"] * sf if s["yield_mpa"] else None)
        ptype = "Static nodal stress Stress1"
    elif kind == "displacement":
        values, lo, hi = list(res.DisplacementLengths), s["min_disp"], s["max_disp"]
        legend = ("URES (%s)" % lu, lo * lf, hi * lf, None)
        ptype = "Static displacement Displacement1"
    elif kind == "fos":
        y = s["yield_mpa"] or 0.0
        values = fos_values(res, y) if y else [1e9] * len(nodes)
        lo, hi = 0.0, 1.0
        legend = None
        ptype = "Factor of Safety Factor of Safety1"
    else:
        values, lo, hi, legend = None, 0, 1, None
        ptype = "Deformed shape Deformation1"
    if values is None:
        colours = {n: (0.85, 0.65, 0.2) for n in nodes}
    elif kind == "fos":
        colours = {n: ((1.0, 0.0, 0.0) if v < fos_limit else (0.0, 0.0, 1.0)) for n, v in zip(nodes, values)}
    else:
        span = (hi - lo) or 1.0
        colours = {n: rainbow((v - lo) / span) for n, v in zip(nodes, values)}
    _draw(doc, res, colours, scale)
    host = _host()
    if host is not None:
        if legend is not None:
            PLOT["legend"] = Legend(host, *legend)
        elif kind == "fos":
            PLOT["legend"] = FosKey(host, fos_limit)
        lines = ["Model name: %s" % (doc.Label or doc.Name), "Study name: %s" % STUDY_LABEL, "Plot type: %s" % ptype]
        if deformed:
            lines.append("Deformation scale: %g" % scale)
        PLOT["title"] = TitleBlock(host, lines)
    if params().GetBool("ShowMaxMin", True) and kind in ("stress", "displacement"):
        _marks(doc, res, kind, s, scale)
    _place_overlays()
    return {"kind": kind, "scale": scale, "nodes": len(colours),
            "red": sum(1 for c in colours.values() if c == (1.0, 0.0, 0.0))}


def surface(res):
    """The outer triangles of the result mesh (corner nodes of faces no two volumes share)."""
    fm = res.Mesh.FemMesh
    key = (res.Name, fm.NodeCount, fm.VolumeCount)
    if _SURFACE.get("key") == key:
        return _SURFACE["tris"]
    count, oriented = {}, {}
    at = {}

    def pos(n):
        p = at.get(n)
        if p is None:
            p = at[n] = fm.getNodeById(n)
        return p
    for v in fm.Volumes:
        n = fm.getElementNodes(v)
        if len(n) in (4, 10):
            corners = n[:4]
        elif len(n) in (8, 20):
            corners = n[:8]
        else:
            continue
        if len(corners) == 4:
            faces = ((n[0], n[1], n[2]), (n[0], n[1], n[3]), (n[0], n[2], n[3]), (n[1], n[2], n[3]))
        else:
            faces = ((n[0], n[1], n[2]), (n[0], n[2], n[3]), (n[4], n[5], n[6]), (n[4], n[6], n[7]),
                     (n[0], n[1], n[5]), (n[0], n[5], n[4]), (n[1], n[2], n[6]), (n[1], n[6], n[5]),
                     (n[2], n[3], n[7]), (n[2], n[7], n[6]), (n[3], n[0], n[4]), (n[3], n[4], n[7]))
        centre = None
        for f in faces:
            k = tuple(sorted(f))
            c = count[k] = count.get(k, 0) + 1
            if c == 1:
                if centre is None:
                    centre = sum((pos(m) for m in corners), App.Vector()) * (1.0 / len(corners))
                a, b, d = pos(f[0]), pos(f[1]), pos(f[2])
                normal = (b - a).cross(d - a)
                oriented[k] = f if normal.dot(a - centre) >= 0 else (f[0], f[2], f[1])
    tris = [oriented[k] for k, c in count.items() if c == 1]
    _SURFACE.update(key=key, tris=tris)
    return tris


_SURFACE = {}


def _points(res, ids, scale):
    fm = res.Mesh.FemMesh
    at = {n: i for i, n in enumerate(res.NodeNumbers)}
    dv = res.DisplacementVectors
    out = []
    for n in ids:
        p = fm.getNodeById(n)
        i = at.get(n)
        if i is not None and scale:
            p = p + dv[i] * scale
        out.append((p.x, p.y, p.z))
    return out


def _draw(doc, res, colours, scale):
    """The plot as its own Coin node: the outer faces, coloured per node, moved by the scaled displacement."""
    from pivy import coin
    view = Gui.getDocument(doc.Name).ActiveView
    graph = view.getSceneGraph()
    tris = surface(res)
    ids = sorted({n for t in tris for n in t})
    index = {n: i for i, n in enumerate(ids)}
    root = coin.SoSeparator()
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
    hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
    root.addChild(hints)
    mat = coin.SoMaterial()
    mat.diffuseColor.setValues(0, len(ids), [colours.get(n, (0.6, 0.6, 0.6)) for n in ids])
    mat.specularColor.setValue(0.1, 0.1, 0.1)
    bind = coin.SoMaterialBinding()
    bind.value = coin.SoMaterialBinding.PER_VERTEX_INDEXED
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(ids), _points(res, ids, scale))
    faces = coin.SoIndexedFaceSet()
    flat = []
    for t in tris:
        flat.extend((index[t[0]], index[t[1]], index[t[2]], -1))
    faces.coordIndex.setValues(0, len(flat), flat)
    for n in (mat, bind, coords, faces):
        root.addChild(n)
    graph.addChild(root)
    PLOT["node"] = (view, root, coords, ids)


def _move(scale):
    node = PLOT.get("node")
    res = result(PLOT["doc"]) if PLOT.get("doc") is not None else None
    if node is None or res is None:
        return
    node[2].point.setValues(0, len(node[3]), _points(res, node[3], scale))


def _node_at(res, node, scale):
    p = res.Mesh.FemMesh.getNodeById(node)
    try:
        i = list(res.NodeNumbers).index(node)
        p = p + res.DisplacementVectors[i] * scale
    except Exception as _fw_err:
        _fw_log("simxpress.py:820", _fw_err)
    return p


def _marks(doc, res, kind, s, scale):
    try:
        from pivy import coin
        view = Gui.getDocument(doc.Name).ActiveView
        graph = view.getSceneGraph()
    except Exception:
        return
    su, sf, lu, lf = UNITS[units()]
    if kind == "stress":
        items = (("Max: %.4g" % (s["max_vm"] * sf), s["max_vm_node"]), ("Min: %.4g" % (s["min_vm"] * sf), s["min_vm_node"]))
    else:
        items = (("Max: %.4g" % (s["max_disp"] * lf), s["max_disp_node"]),)
    root = coin.SoAnnotation()
    font = coin.SoFont()
    font.size = 13
    root.addChild(font)
    for text, node in items:
        p = _node_at(res, node, scale)
        sep = coin.SoSeparator()
        col = coin.SoBaseColor()
        col.rgb = (0.0, 0.0, 0.0)
        at = coin.SoTranslation()
        at.translation = (p.x, p.y, p.z)
        dot = coin.SoMarkerSet()
        dot.markerIndex = coin.SoMarkerSet.CIRCLE_FILLED_7_7 if hasattr(coin.SoMarkerSet, "CIRCLE_FILLED_7_7") else 0
        pts = coin.SoCoordinate3()
        pts.point.setValue(0, 0, 0)
        label = coin.SoText2()
        label.string = "  " + text
        for n in (col, at, pts, dot, label):
            sep.addChild(n)
        root.addChild(sep)
    graph.addChild(root)
    PLOT["marks"] = (view, root)


def _clear_overlays():
    for key in ("legend", "title"):
        w = PLOT.get(key)
        if w is not None:
            try:
                w.hide()
                w.deleteLater()
            except Exception as _fw_err:
                _fw_log("simxpress.py:868", _fw_err)
            PLOT[key] = None
    for key in ("marks", "node"):
        m = PLOT.get(key)
        if m is not None:
            try:
                m[0].getSceneGraph().removeChild(m[1])
            except Exception as _fw_err:
                _fw_log("simxpress.py:876", _fw_err)
            PLOT[key] = None


def _place_overlays():
    host = _host()
    if host is None:
        return
    pane_w = 0
    try:
        from . import shell as sh
        tabs = sh.shell().overlay.tasks
        pane = getattr(tabs, "_pane", None)
        pane_w = tabs.width() + (pane.width() if pane is not None and pane.isVisible() else 0)
    except Exception as _fw_err:
        _fw_log("simxpress.py:891", _fw_err)
    lg, tb = PLOT.get("legend"), PLOT.get("title")
    if tb is not None:
        tb.adjustSize()
        tb.move(12, 64)
        tb.show()
        tb.raise_()
    if lg is not None:
        lg.move(max(10, host.width() - pane_w - lg.width() - 16), max(70, (host.height() - lg.height()) // 2))
        lg.show()
        lg.raise_()


def stop_animation():
    t = PLOT.get("timer")
    if t is not None:
        t.stop()
        PLOT["timer"] = None
        try:
            _move(PLOT["scale"])
        except Exception as _fw_err:
            _fw_log("simxpress.py:912", _fw_err)


def animate(on=True):
    stop_animation()
    if not on or PLOT.get("doc") is None:
        return False
    if PLOT.get("node") is None:
        return False
    timer = QtCore.QTimer()
    PLOT["phase"] = 0.0

    def tick():
        PLOT["phase"] = (PLOT["phase"] + 0.08) % (2 * math.pi)
        try:
            _move(PLOT["scale"] * 0.5 * (1 - math.cos(PLOT["phase"])))
        except Exception:
            stop_animation()
    timer.timeout.connect(tick)
    timer.start(60)
    PLOT["timer"] = timer
    return True


def reset_plot():
    """The model back as it was: result mesh hidden, the part and the symbols shown."""
    stop_animation()
    _clear_overlays()
    doc = PLOT.get("doc")
    if doc is not None:
        for n in PLOT["hidden"]:
            o = doc.getObject(n)
            if o is not None:
                try:
                    o.ViewObject.Visibility = True
                except Exception as _fw_err:
                    _fw_log("simxpress.py:948", _fw_err)
    PLOT.update(doc=None, kind=None, hidden=[])


# =========================================================================== GUI
if Gui is not None:
    class Legend(QtWidgets.QWidget):
        """The colour bar: title, 11 values from max (top) to min, yield strength marked."""

        def __init__(self, host, title, lo, hi, yield_value=None):
            super().__init__(host)
            self.setObjectName("SWXpressLegend")
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            self.title, self.lo, self.hi, self.yv = title, lo, hi, yield_value
            self.resize(200, 320)

        def paintEvent(self, e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            f = p.font()
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.setPen(ink())
            p.drawText(QtCore.QRect(0, 0, self.width(), 18), QtCore.Qt.AlignLeft, self.title)
            top, bottom, x, w = 24, self.height() - 30, 4, 22
            grad = QtGui.QLinearGradient(0, top, 0, bottom)
            for k in range(11):
                r, g, b = rainbow(1 - k / 10.0)
                grad.setColorAt(k / 10.0, QtGui.QColor.fromRgbF(r, g, b))
            p.fillRect(QtCore.QRect(x, top, w, bottom - top), grad)
            p.setPen(ink("line"))
            p.drawRect(QtCore.QRect(x, top, w, bottom - top))
            for k in range(11):
                y = top + (bottom - top) * k / 10.0
                v = self.hi - (self.hi - self.lo) * k / 10.0
                p.drawLine(int(x + w), int(y), int(x + w + 4), int(y))
                p.drawText(QtCore.QPointF(x + w + 7, y + 4), "%.3e" % v)
            if self.yv is not None and self.hi > self.lo:
                t = (self.yv - self.lo) / (self.hi - self.lo)
                y = top + (bottom - top) * (1 - max(0.0, min(1.0, t)))
                p.setPen(QtGui.QPen(QtGui.QColor(200, 0, 0), 1.5))
                p.drawLine(int(x - 3), int(y), int(x + w + 3), int(y))
                p.drawText(QtCore.QPointF(x, self.height() - 10), "Yield strength: %.3e" % self.yv)
            p.end()

    class FosKey(QtWidgets.QWidget):
        def __init__(self, host, limit):
            super().__init__(host)
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            self.limit = limit
            self.resize(170, 64)

        def paintEvent(self, e):
            p = QtGui.QPainter(self)
            p.setPen(ink())
            for i, (c, text) in enumerate(((QtGui.QColor(255, 0, 0), "FOS below %g" % self.limit),
                                           (QtGui.QColor(0, 0, 255), "FOS %g and above" % self.limit))):
                p.fillRect(QtCore.QRect(4, 8 + i * 26, 22, 18), c)
                p.drawText(QtCore.QPointF(34, 22 + i * 26), text)
            p.end()

    def view_is_dark():
        """True when the 3D view's background is dark (the Dark look's grey gradient, AMOLED black, or a dark scene
        picked by hand): plot text is then drawn light, or the legend and title would be unreadable."""
        try:
            v = App.ParamGet("User parameter:BaseApp/Preferences/View")
            keys = ("BackgroundColor2", "BackgroundColor3", "BackgroundColor4") if v.GetBool("Gradient", True) else ("BackgroundColor",)
            lum = []
            for k in keys:
                c = v.GetUnsigned(k, 0xFFFFFFFF)
                r, g, b = (c >> 24) & 255, (c >> 16) & 255, (c >> 8) & 255
                lum.append(0.299 * r + 0.587 * g + 0.114 * b)
            return sum(lum) / len(lum) < 128
        except Exception:
            return False

    def ink(kind="text"):
        """Plot overlay colours for the view's background: text, and the thin frame / tick lines."""
        if view_is_dark():
            return QtGui.QColor(232, 232, 232) if kind == "text" else QtGui.QColor(200, 200, 200)
        return QtGui.QColor(20, 20, 20) if kind == "text" else QtGui.QColor(60, 60, 60)

    class TitleBlock(QtWidgets.QLabel):
        def __init__(self, host, lines):
            super().__init__("\n".join(lines), host)
            self.setObjectName("SWXpressTitle")
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            self.setStyleSheet("QLabel { color: %s; background: transparent; font-size: 8.5pt; }" % ink().name())

    # ----------------------------------------------------------------------- picks
    def _picked_faces(doc, obj):
        out = []
        for sel in Gui.Selection.getSelectionEx(doc.Name, 0):
            for sub in sel.SubElementNames:
                last = sub.split(".")[-1]
                if last.startswith("Face"):
                    out.append(last)
        return out


    # fixture arrows (Fixture PM) or purple load arrows (Force/Torque, Pressure PMs) at once, before OK.
    PREVIEW_KIND = {"SWSimFixFaces": "fixture", "SWXpressFixtureFaces": "fixture", "SWSimForceFaces": "load",
                    "SWSimPressureFaces": "load", "SWXpressForceFaces": "load", "SWXpressPressureFaces": "load",
                    "SWSimBearingFaces": "load", "SWSimRemoteFaces": "load", "SWSimMassFaces": "load"}
    PREVIEW_COLOUR = {"fixture": (0.0, 0.62, 0.0), "load": (0.58, 0.0, 0.62)}
    _PREVIEWS = {}                      # id(pick list) -> [pick list, view, coin node]
    _PREVIEW_TIMER = []

    def _preview_points(face, n=4):
        """Up to n x n points spread over the face (inside its bounds), with the outward normal at each."""
        out = []
        try:
            u0, u1, v0, v1 = face.ParameterRange
            for i in range(n):
                for j in range(n):
                    u = u0 + (u1 - u0) * (i + 0.5) / n
                    v = v0 + (v1 - v0) * (j + 0.5) / n
                    p = face.valueAt(u, v)
                    if face.isInside(p, 1e-6, True):
                        nv = face.normalAt(u, v)
                        if face.Orientation == "Reversed":
                            nv = nv * -1
                        out.append((p, nv))
        except Exception as _fw_err:
            _fw_log("simxpress.py:preview points", _fw_err)
        if not out:
            try:
                c = face.CenterOfMass
                u, v = face.Surface.parameter(c)
                out.append((c, face.normalAt(u, v)))
            except Exception:
                pass
        return out

    def _preview_node(obj, faces, kind):
        from pivy import coin
        bb = obj.Shape.BoundBox
        size = max(bb.DiagonalLength * 0.08, 1e-3)
        root = coin.SoSeparator()
        root.setName("SWSimPickPreview")
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*PREVIEW_COLOUR[kind])
        root.addChild(mat)
        head, shaft, rad = size * 0.35, size * 0.65, size * 0.14
        for name in faces:
            try:
                face = obj.Shape.getElement(name)
            except Exception:
                continue
            if face.ShapeType != "Face":
                continue
            for p, nv in _preview_points(face):
                d = nv * -1                       # the arrow points at the face
                sep = coin.SoSeparator()
                tr = coin.SoTransform()
                tip = p - d * (head * 0.5)
                tr.translation.setValue(tip.x, tip.y, tip.z)
                tr.rotation.setValue(coin.SbRotation(coin.SbVec3f(0, 1, 0), coin.SbVec3f(d.x, d.y, d.z)))
                sep.addChild(tr)
                cone = coin.SoCone()
                cone.height.setValue(head)
                cone.bottomRadius.setValue(rad)
                sep.addChild(cone)
                t2 = coin.SoTranslation()
                t2.translation.setValue(0, -(head + shaft) * 0.5, 0)
                sep.addChild(t2)
                cyl = coin.SoCylinder()
                cyl.height.setValue(shaft)
                cyl.radius.setValue(rad * 0.3)
                sep.addChild(cyl)
                if kind == "fixture":              # the fixture arrow's disc at its tail
                    t3 = coin.SoTranslation()
                    t3.translation.setValue(0, -shaft * 0.5, 0)
                    sep.addChild(t3)
                    disc = coin.SoCylinder()
                    disc.height.setValue(rad * 0.25)
                    disc.radius.setValue(rad * 1.1)
                    sep.addChild(disc)
                root.addChild(sep)
        return root

    def _preview_drop(key):
        entry = _PREVIEWS.pop(key, None)
        if entry is None:
            return
        _w, view, node = entry
        try:
            if node is not None:
                view.getSceneGraph().removeChild(node)
        except Exception:
            pass

    def _preview_sweep():
        """Takes a preview off when its PM has closed (or the list is gone)."""
        open_ = bool(Gui.Control.activeDialog()) if hasattr(Gui, "Control") else False
        for key, (w, _view, _node) in list(_PREVIEWS.items()):
            try:
                alive = open_ and w.parent() is not None
            except RuntimeError:                   # the C++ list was deleted with its PM
                alive = False
            if not alive:
                _preview_drop(key)
        if not _PREVIEWS and _PREVIEW_TIMER:
            _PREVIEW_TIMER[0].stop()

    def preview(pick):
        """Redraws pick's arrows on the model (nothing for a box that takes no faces of the part)."""
        kind = PREVIEW_KIND.get(pick.objectName())
        if kind is None:
            return
        key = id(pick)
        _preview_drop(key)
        try:
            doc = App.ActiveDocument
            view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None
            obj = getattr(pick, "preview_obj", None) or (target(doc) if doc is not None else None)
            names = [t.split(".")[-1] for t in pick.values()]
            if view is None or obj is None or not names or not hasattr(view, "getSceneGraph"):
                return
            node = _preview_node(obj, names, kind)
            view.getSceneGraph().addChild(node)
            _PREVIEWS[key] = [pick, view, node]
            if not _PREVIEW_TIMER:
                t = QtCore.QTimer()
                t.setInterval(400)
                t.timeout.connect(_preview_sweep)
                _PREVIEW_TIMER.append(t)
            _PREVIEW_TIMER[0].start()
        except Exception as _fw_err:
            _fw_log("simxpress.py:preview", _fw_err)

    def previews():
        """[(pick list name, kind, arrow count)] of the previews on the model now (for checks)."""
        out = []
        for _k, (w, _v, node) in _PREVIEWS.items():
            try:
                out.append((w.objectName(), PREVIEW_KIND.get(w.objectName()), node.getNumChildren() - 1))
            except RuntimeError:
                pass
        return out

    class _PickList(QtWidgets.QListWidget):
        """A PropertyManager pick box (light blue while it takes the picks)."""
        activated_box = QtCore.Signal(object)

        def __init__(self, name):
            super().__init__()
            self.setObjectName(name)
            self.setFixedHeight(64)
            self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            self.customContextMenuRequested.connect(self._menu)
            self.active(False)
            if name in PREVIEW_KIND:
                m = self.model()
                for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset):
                    sig.connect(lambda *_a: QtCore.QTimer.singleShot(0, lambda: self._preview()))

        def _preview(self):
            try:
                preview(self)
            except RuntimeError:
                pass

        def active(self, on):
            self.setStyleSheet("QListWidget { background: %s; }" % ("#cce4f7" if on else "#ffffff"))

        def focusInEvent(self, e):
            self.activated_box.emit(self)
            super().focusInEvent(e)

        def mousePressEvent(self, e):
            self.activated_box.emit(self)
            super().mousePressEvent(e)

        def _menu(self, pos):
            menu = QtWidgets.QMenu(self)
            menu.addAction("Delete", lambda: [self.takeItem(self.row(i)) for i in self.selectedItems()])
            menu.addAction("Clear Selections", self.clear)
            menu.exec_(self.viewport().mapToGlobal(pos))

        def values(self):
            return [self.item(i).text() for i in range(self.count())]

        def toggle(self, text):
            found = self.findItems(text, QtCore.Qt.MatchExactly)
            if found:
                self.takeItem(self.row(found[0]))
            else:
                self.addItem(text)

    def _box(title, icon=None, pm_title=None):
        w = QtWidgets.QWidget()
        w.setWindowTitle(title)
        if pm_title:
            w.setProperty("swstyle_pm_title", pm_title)
        if icon:
            w.setProperty("swstyle_pm_icon", icon)
        return w

    class _XpressPM:
        """Shared parts of the Fixture / Force / Pressure PropertyManagers."""
        PM = "Fixture"

        def __init__(self, page, doc, edit=None):
            self.page, self.doc, self.edit = page, doc, edit
            self.obj = target(doc)
            self.boxes = []
            self.current = None

        def _activate(self, box):
            self.current = box
            for b in self.boxes:
                b.active(b is box)

        def addSelection(self, doc, name, sub, pnt):
            if doc != self.doc.Name or self.current is None:
                return
            QtCore.QTimer.singleShot(0, lambda: self._picked(name, sub))

        def _picked(self, name, sub):
            last = (sub or "").split(".")[-1]
            box = self.current
            if box is None:
                return
            if box is self.boxes[0]:
                if last.startswith("Face"):
                    o = self.doc.getObject(name)
                    if self.obj is None and o is not None:
                        self.obj = o
                    box.toggle(last)
            elif last:
                box.clear()
                box.addItem("%s:%s" % (name, last))
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("simxpress.py:1111", _fw_err)

        def _start(self):
            first = self.boxes[0]
            for f in _picked_faces(self.doc, self.obj):
                if not first.findItems(f, QtCore.Qt.MatchExactly):
                    first.addItem(f)
            for b in self.boxes:
                b.activated_box.connect(self._activate)
            self._activate(first)
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def reject(self):
            self._close()
            return True

        def _close(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("simxpress.py:1135", _fw_err)
            Gui.Control.closeDialog()
            QtCore.QTimer.singleShot(0, lambda: self.page.refresh() if self.page is not None else None)

        def _faces_or_warn(self):
            faces = self.boxes[0].values()
            if not faces or self.obj is None:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, "Pick the faces in the graphics area first.")
                return None
            return faces

    class FixturePM(_XpressPM):
        PM = "Fixture"

        def __init__(self, page, doc, edit=None):
            super().__init__(page, doc, edit)
            msg = _box("Message", "TOOLS_SENSOR", self.PM)
            QtWidgets.QVBoxLayout(msg).addWidget(QtWidgets.QLabel(
                "Pick the faces that are held. They do not move or turn in the study."))
            kind = _box("Standard (Fixed Geometry)")
            lay = QtWidgets.QVBoxLayout(kind)
            self.faces = _PickList("SWXpressFixtureFaces")
            self.faces.setToolTip("Faces held: click them in the graphics area; a second click takes one out")
            lay.addWidget(self.faces)
            self.boxes = [self.faces]
            self.form = [msg, kind]
            if edit is not None:
                for _o, subs in edit.References:
                    self.faces.addItems(list(subs))
            self._start()

        def accept(self):
            faces = self._faces_or_warn()
            if faces is None:
                return False
            self.doc.openTransaction("Fixture")
            try:
                add_fixture(self.doc, self.obj, faces, self.edit)
            finally:
                self.doc.commitTransaction()
            self._close()
            return True

    class ForcePM(_XpressPM):
        PM = "Force"

        def __init__(self, page, doc, edit=None):
            super().__init__(page, doc, edit)
            msg = _box("Message", None, self.PM)
            QtWidgets.QVBoxLayout(msg).addWidget(QtWidgets.QLabel("Pick the faces the force acts on."))
            box = _box("Force")
            form = QtWidgets.QFormLayout(box)
            self.faces = _PickList("SWXpressForceFaces")
            self.normal = QtWidgets.QRadioButton("Normal")
            self.selected = QtWidgets.QRadioButton("Selected direction")
            self.normal.setChecked(True)
            self.direction = _PickList("SWXpressForceDirection")
            self.direction.setFixedHeight(26)
            self.direction.setToolTip("An edge, face or plane: the force runs along it (normal to a face or plane)")
            self.unit = QtWidgets.QComboBox()
            self.unit.addItems(list(FORCE_UNITS))
            self.unit.setObjectName("SWXpressForceUnit")
            self.value = QtWidgets.QDoubleSpinBox()
            self.value.setObjectName("SWXpressForceValue")
            self.value.setRange(0.0, 1e12)
            self.value.setDecimals(3)
            self.value.setValue(100.0)
            self.reverse = QtWidgets.QCheckBox("Reverse direction")
            self.per_item = QtWidgets.QRadioButton("Per item")
            self.total = QtWidgets.QRadioButton("Total")
            self.total.setChecked(True)
            form.addRow(self.faces)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.normal)
            row.addWidget(self.selected)
            form.addRow(row)
            form.addRow("Direction:", self.direction)
            form.addRow("Units:", self.unit)
            form.addRow("Force:", self.value)
            form.addRow(self.reverse)
            row2 = QtWidgets.QHBoxLayout()
            row2.addWidget(self.per_item)
            row2.addWidget(self.total)
            form.addRow(row2)
            self.normal.toggled.connect(lambda on: self.direction.setEnabled(not on))
            self.direction.setEnabled(False)
            self.boxes = [self.faces, self.direction]
            self.form = [msg, box]
            if edit is not None:
                for _o, subs in edit.References:
                    self.faces.addItems(list(subs))
                self.value.setValue(getattr(edit, "FwValue", edit.Force.Value / 1000.0))
                self.unit.setCurrentText(getattr(edit, "FwUnit", "N"))
                self.reverse.setChecked(getattr(edit, "FwReverse", False))
                (self.per_item if getattr(edit, "FwPerItem", False) else self.total).setChecked(True)
                if edit.Direction:
                    self.selected.setChecked(True)
                    self.direction.addItem("%s:%s" % (edit.Direction[0].Name, edit.Direction[1][0]))
            self._start()

        def accept(self):
            faces = self._faces_or_warn()
            if faces is None:
                return False
            direction = None
            if self.selected.isChecked():
                vals = self.direction.values()
                if not vals:
                    QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, "Pick the direction (an edge, face or plane).")
                    return False
                name, sub = vals[0].split(":", 1)
                direction = (self.doc.getObject(name), sub)
            self.doc.openTransaction("Force")
            try:
                add_force(self.doc, self.obj, faces, self.value.value(), self.unit.currentText(), direction,
                          self.reverse.isChecked(), self.per_item.isChecked(), self.edit)
            finally:
                self.doc.commitTransaction()
            self._close()
            return True

    class PressurePM(_XpressPM):
        PM = "Pressure"

        def __init__(self, page, doc, edit=None):
            super().__init__(page, doc, edit)
            msg = _box("Message", None, self.PM)
            QtWidgets.QVBoxLayout(msg).addWidget(QtWidgets.QLabel("Pick the faces the pressure acts on."))
            box = _box("Pressure")
            form = QtWidgets.QFormLayout(box)
            self.faces = _PickList("SWXpressPressureFaces")
            self.unit = QtWidgets.QComboBox()
            self.unit.addItems(list(PRESSURE_UNITS))
            self.value = QtWidgets.QDoubleSpinBox()
            self.value.setObjectName("SWXpressPressureValue")
            self.value.setRange(0.0, 1e15)
            self.value.setDecimals(3)
            self.value.setValue(1e6)
            self.unit.currentTextChanged.connect(lambda u: self.value.setValue(
                {"N/m^2": 1e6, "MPa": 1.0, "psi": 145.0, "kgf/cm^2": 10.0}.get(u, 1.0)) if self.edit is None else None)
            self.reverse = QtWidgets.QCheckBox("Reverse direction")
            form.addRow(self.faces)
            form.addRow("Units:", self.unit)
            form.addRow("Pressure:", self.value)
            form.addRow(self.reverse)
            self.boxes = [self.faces]
            self.form = [msg, box]
            if edit is not None:
                for _o, subs in edit.References:
                    self.faces.addItems(list(subs))
                self.unit.setCurrentText(getattr(edit, "FwUnit", "MPa"))
                self.value.setValue(getattr(edit, "FwValue", edit.Pressure.Value))
                self.reverse.setChecked(getattr(edit, "FwReverse", False))
            self._start()

        def accept(self):
            faces = self._faces_or_warn()
            if faces is None:
                return False
            self.doc.openTransaction("Pressure")
            try:
                add_pressure(self.doc, self.obj, faces, self.value.value(), self.unit.currentText(),
                             self.reverse.isChecked(), self.edit)
            finally:
                self.doc.commitTransaction()
            self._close()
            return True

    def open_pm(cls, page, doc, edit=None):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        panel = cls(page, doc, edit)
        Gui.Control.showDialog(panel)
        LAST_PM[0] = panel
        return panel

    LAST_PM = [None]

    # ----------------------------------------------------------------------- options
    class OptionsDialog(QtWidgets.QDialog):
        def __init__(self, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.setWindowTitle("SimulationXpress Options")
            form = QtWidgets.QFormLayout(self)
            self.units = QtWidgets.QComboBox()
            self.units.setObjectName("SWXpressUnits")
            self.units.addItems(list(UNITS))
            self.units.setCurrentText(units())
            row = QtWidgets.QHBoxLayout()
            self.folder = QtWidgets.QLineEdit(params().GetString("ResultsFolder", ""))
            self.folder.setPlaceholderText("The part's folder")
            browse = QtWidgets.QPushButton("...")
            browse.setFixedWidth(28)
            browse.clicked.connect(self._browse)
            row.addWidget(self.folder)
            row.addWidget(browse)
            self.maxmin = QtWidgets.QCheckBox("Show annotation for maximum and minimum in the result plots")
            self.maxmin.setChecked(params().GetBool("ShowMaxMin", True))
            form.addRow("System of units:", self.units)
            form.addRow("Results location:", row)
            form.addRow(self.maxmin)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            form.addRow(bb)

        def _browse(self):
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "Results location", self.folder.text() or os.path.expanduser("~"))
            if d:
                self.folder.setText(d)

        def accept(self):
            p = params()
            p.SetString("Units", self.units.currentText())
            p.SetString("ResultsFolder", self.folder.text().strip())
            p.SetBool("ShowMaxMin", self.maxmin.isChecked())
            super().accept()

    # ----------------------------------------------------------------------- the Task Pane page
    def _label(text):
        l = QtWidgets.QLabel(text)
        l.setWordWrap(True)
        return l

    def _link(text, run, name=None):
        b = QtWidgets.QPushButton(text)
        b.setFlat(True)
        b.setCursor(QtCore.Qt.PointingHandCursor)
        b.setStyleSheet("QPushButton { text-align: left; color: #1f5fbf; padding: 3px 2px; }"
                        "QPushButton:disabled { color: #9a9a9a; }")
        if name:
            b.setObjectName(name)
        b.clicked.connect(lambda checked=False: run())
        return b

    class XpressPage(QtWidgets.QWidget):
        def __init__(self, pane=None):
            super().__init__()
            self.setObjectName("SWSimulationXpress")
            self.doc = App.ActiveDocument
            self.accepted_shape = False
            self.opt = None
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(4, 4, 4, 4)
            self.bar = QtWidgets.QTabBar()
            self.bar.setObjectName("SWXpressSteps")
            self.bar.setExpanding(False)
            self.bar.setUsesScrollButtons(True)
            for s in STEPS:
                self.bar.addTab(s)
            self.bar.currentChanged.connect(self._go)
            lay.addWidget(self.bar)
            self.stack = QtWidgets.QStackedWidget()
            lay.addWidget(self.stack, 1)
            self.pages = {}
            for s in STEPS:
                w = QtWidgets.QWidget()
                v = QtWidgets.QVBoxLayout(w)
                v.setContentsMargins(4, 6, 4, 4)
                self.pages[s] = v
                self.stack.addWidget(w)
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setObjectName("SWXpressTree")
            self.tree.setHeaderHidden(True)
            self.tree.setFixedHeight(150)
            self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self._tree_menu)
            self.tree.itemDoubleClicked.connect(self._tree_double)
            lay.addWidget(self.tree)
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            self.close_button = QtWidgets.QPushButton("Close")
            self.close_button.setObjectName("SWXpressClose")
            self.close_button.clicked.connect(lambda: close())
            row.addWidget(self.close_button)
            lay.addLayout(row)
            self.refresh()
            self.bar.setCurrentIndex(self._first_open_step())

        # --- state
        def _first_open_step(self):
            a = study(self.doc) if self.doc else None
            if a is None:
                return 0
            if not fixtures(a):
                return 1
            if not loads(a):
                return 2
            if material_values(self.doc) is None:
                return 3
            return 5 if result(self.doc) is not None else 4

        def done(self):
            a = study(self.doc) if self.doc else None
            return {"Welcome": a is not None, "Fixtures": bool(fixtures(a)), "Loads": bool(loads(a)),
                    "Material": self.doc is not None and material_values(self.doc) is not None,
                    "Run": self.doc is not None and result(self.doc) is not None,
                    "Results": self.accepted_shape, "Optimize": self.opt is not None}

        def refresh(self):
            if App.ActiveDocument is not None and App.ActiveDocument is not self.doc:
                reset_plot()
                self.doc = App.ActiveDocument
            d = self.done()
            for i, s in enumerate(STEPS):
                self.bar.setTabText(i, ("✔ " if d[s] else "") + s)
            self._fill_tree()
            self._go(self.bar.currentIndex())

        def _clear(self, v):
            while v.count():
                item = v.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.hide()
                    w.deleteLater()
                elif item.layout() is not None:
                    self._clear(item.layout())

        def _go(self, i):
            if i < 0:
                return
            self.stack.setCurrentIndex(i)
            s = STEPS[i]
            v = self.pages[s]
            self._clear(v)
            getattr(self, "_page_" + s.lower())(v)
            v.addStretch(1)

        def step(self, name):
            self.bar.setCurrentIndex(STEPS.index(name))
            self._go(STEPS.index(name))

        def _next(self, v, to, enabled=True):
            b = QtWidgets.QPushButton("Next")
            b.setObjectName("SWXpressNext")
            b.setEnabled(enabled)
            b.clicked.connect(lambda: self.step(to))
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            row.addWidget(b)
            v.addLayout(row)

        # --- pages
        def _page_welcome(self, v):
            v.addWidget(_label("<b>Welcome to SimulationXpress</b>"))
            v.addWidget(_label("SimulationXpress shows how the part bends under a load and where it could fail. "
                               "Hold it with fixtures, load it with forces or pressures, give it a material and run "
                               "the study. The results show the stress, how far the part moves and its factor of "
                               "safety; Optimize then finds the lightest value of a dimension that still holds."))
            v.addWidget(_label("The study is linear and static: small movements, the material stays elastic, and the "
                               "loads are applied slowly and do not change."))
            v.addWidget(_link("Options", lambda: OptionsDialog(self).exec_() and self.refresh(), "SWXpressOptions"))
            if self.doc is None or target(self.doc) is None:
                v.addWidget(_label("<i>Open a part with a solid body to start.</i>"))
            self._next(v, "Fixtures", self.doc is not None and target(self.doc) is not None)

        def _page_fixtures(self, v):
            a = study(self.doc) if self.doc else None
            fx = fixtures(a)
            v.addWidget(_label("<b>Fixtures</b>"))
            v.addWidget(_label("Fixtures hold the part: pick the faces that stay where they are. Every study needs "
                               "at least one."))
            if fx:
                v.addWidget(_label("Fixtures in the study: %s." % ", ".join(o.Label for o in fx)))
            v.addWidget(_link("Add a fixture", lambda: open_pm(FixturePM, self, self.doc), "SWXpressAddFixture"))
            if fx:
                v.addWidget(_link("Edit a fixture", lambda: open_pm(FixturePM, self, self.doc, fx[-1])))
            self._next(v, "Loads", bool(fx))

        def _page_loads(self, v):
            a = study(self.doc) if self.doc else None
            ld = loads(a)
            v.addWidget(_label("<b>Loads</b>"))
            v.addWidget(_label("Loads push or pull on the part: a force on faces (normal to them or along a direction "
                               "you pick) or a pressure."))
            if ld:
                v.addWidget(_label("Loads in the study: %s." % ", ".join(o.Label for o in ld)))
            v.addWidget(_link("Add a force", lambda: open_pm(ForcePM, self, self.doc), "SWXpressAddForce"))
            v.addWidget(_link("Add a pressure", lambda: open_pm(PressurePM, self, self.doc), "SWXpressAddPressure"))
            self._next(v, "Material", bool(ld))

        def _page_material(self, v):
            m = material_values(self.doc) if self.doc else None
            v.addWidget(_label("<b>Material</b>"))
            if m is None:
                v.addWidget(_label("The part has no material yet. Choose one: the study needs its stiffness and its "
                                   "yield strength."))
                text = "Choose material"
            else:
                name, e, nu, y, dens = m
                su, sf, _lu, _lf = UNITS[units()]
                v.addWidget(_label("Material: <b>%s</b><br>Elastic modulus: %.4g %s<br>Poisson's ratio: %g<br>"
                                   "Yield strength: %s" % (html.escape(name), e * sf, su, nu,
                                                           ("%.4g %s" % (y * sf, su)) if y else "not known")))
                text = "Change material"

            def change():
                from . import materialdlg
                dlg = materialdlg.edit(self.doc)
                if dlg is not None:
                    dlg.finished.connect(lambda *_: self.refresh())
                    dlg.destroyed.connect(lambda *_: QtCore.QTimer.singleShot(0, self.refresh))
            v.addWidget(_link(text, change, "SWXpressMaterial"))
            self._next(v, "Run", m is not None)

        def _page_run(self, v):
            v.addWidget(_label("<b>Run</b>"))
            v.addWidget(_label("Run Simulation meshes the part and solves the study. Change settings sets how fine "
                               "the mesh is: finer is more exact and takes longer."))
            self.slider_row = QtWidgets.QWidget()
            sl = QtWidgets.QVBoxLayout(self.slider_row)
            sl.setContentsMargins(0, 0, 0, 0)
            self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.slider.setObjectName("SWXpressMeshDensity")
            self.slider.setRange(0, 10)
            self.slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
            self.slider.setValue(params().GetInt("MeshDensity", 5))
            self.slider.valueChanged.connect(lambda n: params().SetInt("MeshDensity", n))
            ends = QtWidgets.QHBoxLayout()
            ends.addWidget(QtWidgets.QLabel("Coarse"))
            ends.addStretch(1)
            ends.addWidget(QtWidgets.QLabel("Fine"))
            sl.addWidget(_label("Mesh density"))
            sl.addWidget(self.slider)
            sl.addLayout(ends)
            self.slider_row.setVisible(False)
            ready = all(self.done()[k] for k in ("Fixtures", "Loads", "Material"))
            b = _link("Run Simulation", self.run_study, "SWXpressRun")
            b.setEnabled(ready)
            v.addWidget(b)
            v.addWidget(_link("Change settings", lambda: self.slider_row.setVisible(not self.slider_row.isVisible()),
                              "SWXpressSettings"))
            v.addWidget(self.slider_row)
            if not ready:
                v.addWidget(_label("<i>Fixtures, loads and a material come first.</i>"))
            s = summary(self.doc) if self.doc else None
            if s:
                v.addWidget(_label("Last run %s: %d nodes, %d elements, %.1f s." % (s["time"], s["nodes"], s["elements"],
                                                                                   s["seconds"])))

        def run_study(self):
            reset_plot()
            box = QtWidgets.QProgressDialog("Meshing", None, 0, 0, self)
            box.setWindowTitle(TITLE)
            box.setMinimumDuration(0)
            box.setWindowModality(QtCore.Qt.WindowModal)
            box.show()

            def say(text):
                box.setLabelText(text)
                QtWidgets.QApplication.processEvents()
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                say("Meshing")
                run(self.doc, progress=say)
            except Exception as error:
                QtWidgets.QApplication.restoreOverrideCursor()
                box.close()
                QtWidgets.QMessageBox.warning(self, TITLE, str(error))
                return False
            QtWidgets.QApplication.restoreOverrideCursor()
            box.close()
            self.accepted_shape = False
            self.refresh()
            self.step("Results")
            return True

        def _page_results(self, v):
            s = summary(self.doc) if self.doc else None
            v.addWidget(_label("<b>Results</b>"))
            if s is None or result(self.doc) is None:
                v.addWidget(_label("Run the study first."))
                return
            if not self.accepted_shape:
                if PLOT.get("kind") != "stress":
                    show_plot(self.doc, "stress")
                    animate(True)
                v.addWidget(_label("The stress plot shows the part bent (the bending is scaled up so it shows)."))
                v.addWidget(_label("<b>Does the part deform as expected?</b>"))
                yes = _link("Yes, continue", self._yes, "SWXpressYes")
                no = _link("No, return to fixtures", self._no, "SWXpressNo")
                v.addWidget(yes)
                v.addWidget(no)
                return
            su, sf, lu, lf = UNITS[units()]
            fos = s.get("min_fos")
            v.addWidget(_label("Max von Mises stress: %.4g %s<br>Max displacement: %.4g %s<br>Lowest factor of "
                               "safety: %s" % (s["max_vm"] * sf, su, s["max_disp"] * lf, lu,
                                               ("%.3g" % fos) if fos else "not known (no yield strength)")))
            if fos:
                v.addWidget(_label("The part %s." % ("holds this load" if fos >= 1 else
                                                     "yields under this load: the stress passes the yield strength")))
            v.addWidget(_link("Show von Mises stress", lambda: show_plot(self.doc, "stress"), "SWXpressShowStress"))
            v.addWidget(_link("Show displacement", lambda: show_plot(self.doc, "displacement"), "SWXpressShowDisp"))
            v.addWidget(_link("Show deformation", lambda: show_plot(self.doc, "deformation"), "SWXpressShowDeform"))
            row = QtWidgets.QHBoxLayout()
            row.addWidget(_label("Show where factor of safety (FOS) is below:"))
            self.fos = QtWidgets.QDoubleSpinBox()
            self.fos.setObjectName("SWXpressFosLimit")
            self.fos.setRange(0.01, 1000)
            self.fos.setValue(1.0)
            row.addWidget(self.fos)
            v.addLayout(row)
            v.addWidget(_link("Show me", lambda: show_plot(self.doc, "fos", self.fos.value()), "SWXpressShowMe"))
            v.addWidget(_link("Play animation", lambda: animate(True), "SWXpressPlay"))
            v.addWidget(_link("Stop animation", stop_animation, "SWXpressStop"))
            v.addWidget(_link("Generate report", self.make_report, "SWXpressReport"))
            v.addWidget(_link("Generate 3D results file", self.make_file, "SWXpressFile"))
            v.addWidget(_link("Done viewing results", self._done_viewing, "SWXpressDoneViewing"))

        def _yes(self):
            stop_animation()
            self.accepted_shape = True
            self.refresh()

        def _no(self):
            reset_plot()
            self.step("Fixtures")

        def _done_viewing(self):
            reset_plot()
            self.refresh()
            self.step("Optimize")

        def make_report(self, open_it=True):
            folder = result_folder(self.doc)
            os.makedirs(folder, exist_ok=True)
            images = []
            kind_before = PLOT.get("kind")
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                view = Gui.getDocument(self.doc.Name).ActiveView
                for kind, title in (("stress", "von Mises stress"), ("displacement", "Displacement"),
                                    ("deformation", "Deformed shape"), ("fos", "Factor of safety")):
                    show_plot(self.doc, kind, getattr(self, "fos", None).value() if hasattr(self, "fos") else 1.0)
                    QtWidgets.QApplication.processEvents()
                    img = os.path.join(folder, "%s-%s.png" % (self.doc.Label or self.doc.Name, KINDS[kind].replace(" ", "")))
                    view.saveImage(img, 1000, 700, "White")
                    images.append((title, img))
                path = report(self.doc, folder, images)
            except Exception as error:
                QtWidgets.QApplication.restoreOverrideCursor()
                QtWidgets.QMessageBox.warning(self, TITLE, str(error))
                return None
            QtWidgets.QApplication.restoreOverrideCursor()
            if kind_before:
                show_plot(self.doc, kind_before)
            else:
                reset_plot()
            self.last_report = path
            if open_it:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
            App.Console.PrintMessage("SimulationXpress report: %s\n" % path)
            return path

        def make_file(self):
            try:
                path = results_file(self.doc)
            except Exception as error:
                QtWidgets.QMessageBox.warning(self, TITLE, str(error))
                return None
            self.last_file = path
            QtWidgets.QMessageBox.information(self, TITLE, "Results saved to\n%s" % path)
            return path

        def _page_optimize(self, v):
            v.addWidget(_label("<b>Optimize</b>"))
            if self.doc is None or summary(self.doc) is None:
                v.addWidget(_label("Run the study first."))
                return
            if getattr(self, "opt_mode", None) is None:
                v.addWidget(_label("Would you like to optimize your model? SimulationXpress changes one dimension "
                                   "to make the part as light as it can be while it still meets a limit you set."))
                v.addWidget(_link("Yes", lambda: (setattr(self, "opt_mode", "yes"), self._go(6)), "SWXpressOptYes"))
                v.addWidget(_link("No", lambda: (setattr(self, "opt_mode", "no"), self._go(6)), "SWXpressOptNo"))
                return
            if self.opt_mode == "no":
                v.addWidget(_label("SimulationXpress is done. Close keeps the study in the part for next time."))
                v.addWidget(_link("Optimize after all", lambda: (setattr(self, "opt_mode", "yes"), self._go(6))))
                return
            form = QtWidgets.QFormLayout()
            self.var = QtWidgets.QComboBox()
            self.var.setObjectName("SWXpressVariable")
            for name, o, p in dims(self.doc):
                try:
                    self.var.addItem("%s (%g)" % (name, dim_get(o, p)), (o.Name, p))
                except Exception:
                    continue
            self.lo, self.hi, self.limit = (QtWidgets.QDoubleSpinBox() for _ in range(3))
            for sb in (self.lo, self.hi, self.limit):
                sb.setRange(-1e9, 1e9)
                sb.setDecimals(4)
            self.lo.setObjectName("SWXpressMin")
            self.hi.setObjectName("SWXpressMax")
            self.limit.setObjectName("SWXpressLimit")

            def picked_var(*_):
                data = self.var.currentData()
                if data:
                    v0 = dim_get(self.doc.getObject(data[0]), data[1])
                    self.lo.setValue(v0 * 0.5)
                    self.hi.setValue(v0 * 1.5)
            self.var.currentIndexChanged.connect(picked_var)
            picked_var()
            self.kind = QtWidgets.QComboBox()
            self.kind.setObjectName("SWXpressConstraint")
            self.kind.addItems(CONSTRAINTS)
            self.rule = QtWidgets.QLabel("Is greater than")

            def picked_kind(*_):
                k = self.kind.currentText()
                self.rule.setText("Is greater than" if k == "Factor of safety" else "Is less than")
                s = summary(self.doc)
                self.limit.setValue({"Factor of safety": 2.0, "Max von Mises stress": s["yield_mpa"] / 2 or s["max_vm"],
                                     "Max displacement": s["max_disp"] * 2}[k])
            self.kind.currentIndexChanged.connect(picked_kind)
            picked_kind()
            self.steps = QtWidgets.QSpinBox()
            self.steps.setRange(2, 20)
            self.steps.setValue(5)
            goal = QtWidgets.QLabel("Minimize mass")      # SimulationXpress has the one goal: shown, not a list
            form.addRow("Variable:", self.var)
            form.addRow("Min:", self.lo)
            form.addRow("Max:", self.hi)
            form.addRow("Constraint:", self.kind)
            form.addRow(self.rule, self.limit)
            form.addRow("Goal:", goal)
            form.addRow("Values tried:", self.steps)
            v.addLayout(form)
            v.addWidget(_link("Run", self.run_optimize, "SWXpressOptRun"))
            if self.opt is not None:
                self._opt_table(v)

        def run_optimize(self):
            data = self.var.currentData()
            if not data:
                QtWidgets.QMessageBox.warning(self, TITLE, "The part has no dimension to vary.")
                return None
            o = self.doc.getObject(data[0])
            box = QtWidgets.QProgressDialog("Optimizing", "Stop", 0, 0, self)
            box.setWindowTitle(TITLE)
            box.setMinimumDuration(0)
            box.show()

            def say(text):
                box.setLabelText(text)
                QtWidgets.QApplication.processEvents()
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                out = optimize(self.doc, o, data[1], self.lo.value(), self.hi.value(), self.kind.currentText(),
                               self.limit.value(), self.steps.value(), say, box.wasCanceled)
            except Exception as error:
                QtWidgets.QApplication.restoreOverrideCursor()
                box.close()
                QtWidgets.QMessageBox.warning(self, TITLE, str(error))
                return None
            QtWidgets.QApplication.restoreOverrideCursor()
            box.close()
            out.update(name=self.var.currentText().split(" (")[0], obj=o.Name, path=data[1], kind=self.kind.currentText(),
                       limit=self.limit.value())
            self.opt = out
            self.refresh()
            return out

        def _opt_table(self, v):
            out = self.opt
            t = QtWidgets.QTableWidget(3, 2)
            t.setObjectName("SWXpressOptTable")
            t.setHorizontalHeaderLabels(["Initial", "Optimal"])
            t.setVerticalHeaderLabels([out["name"], out["kind"], "Mass (kg)"])
            for c, r in enumerate((out["initial"], out["optimal"])):
                for k, val in enumerate(("%g" % r[0], "%.4g" % r[2], "%.4g" % r[1]) if r else ("-", "-", "-")):
                    t.setItem(k, c, QtWidgets.QTableWidgetItem(val))
            t.setFixedHeight(110)
            v.addWidget(t)
            if out["optimal"] is None:
                v.addWidget(_label("No value tried meets the constraint. Widen Min / Max or ease the limit."))
                return
            v.addWidget(_link("Use optimal value", self.use_optimal, "SWXpressUseOptimal"))

        def use_optimal(self):
            out = self.opt
            o = self.doc.getObject(out["obj"])
            self.doc.openTransaction("Optimize")
            try:
                dim_set(o, out["path"], out["optimal"][0])
            finally:
                self.doc.commitTransaction()
            try:
                run(self.doc)
            except Exception as _fw_err:
                _fw_log("simxpress.py:1828", _fw_err)
            self.refresh()

        # --- the study tree
        def _fill_tree(self):
            self.tree.clear()
            a = study(self.doc) if self.doc else None
            root = QtWidgets.QTreeWidgetItem([STUDY_LABEL])
            self.tree.addTopLevelItem(root)
            groups = (("Fixtures", fixtures(a)), ("External Loads", loads(a)))
            for title, items in groups:
                g = QtWidgets.QTreeWidgetItem([title])
                root.addChild(g)
                for o in items:
                    it = QtWidgets.QTreeWidgetItem([o.Label])
                    it.setData(0, QtCore.Qt.UserRole, o.Name)
                    g.addChild(it)
            m = material_values(self.doc) if self.doc else None
            root.addChild(QtWidgets.QTreeWidgetItem(["Material: %s" % (m[0] if m else "none")]))
            if self.doc is not None and result(self.doc) is not None:
                g = QtWidgets.QTreeWidgetItem(["Results"])
                root.addChild(g)
                for kind, label in KINDS.items():
                    it = QtWidgets.QTreeWidgetItem([label])
                    it.setData(0, QtCore.Qt.UserRole + 1, kind)
                    g.addChild(it)
            self.tree.expandAll()

        def _tree_double(self, item, _col=0):
            name = item.data(0, QtCore.Qt.UserRole)
            kind = item.data(0, QtCore.Qt.UserRole + 1)
            if name:
                self.edit(self.doc.getObject(name))
            elif kind:
                show_plot(self.doc, kind, getattr(self, "fos", None).value() if hasattr(self, "fos") and alive_(self.fos) else 1.0)

        def edit(self, o):
            if o is None:
                return
            cls = {FIXED: FixturePM, FORCE: ForcePM, PRESSURE: PressurePM}.get(o.TypeId)
            if cls is not None:
                open_pm(cls, self, self.doc, o)

        def _tree_menu(self, pos):
            item = self.tree.itemAt(pos)
            if item is None:
                return
            name = item.data(0, QtCore.Qt.UserRole)
            kind = item.data(0, QtCore.Qt.UserRole + 1)
            menu = QtWidgets.QMenu(self.tree)
            if name:
                o = self.doc.getObject(name)
                menu.addAction("Edit Definition...", lambda: self.edit(o))
                menu.addAction("Delete", lambda: (remove(self.doc, o), self.refresh()))
            elif kind:
                menu.addAction("Show", lambda: show_plot(self.doc, kind))
            elif item.text(0) == "Fixtures":
                menu.addAction("Add a fixture", lambda: open_pm(FixturePM, self, self.doc))
            elif item.text(0) == "External Loads":
                menu.addAction("Add a force", lambda: open_pm(ForcePM, self, self.doc))
                menu.addAction("Add a pressure", lambda: open_pm(PressurePM, self, self.doc))
            elif item.text(0).startswith("Material"):
                menu.addAction("Change material", lambda: self.step("Material"))
            elif item.text(0) == STUDY_LABEL:
                menu.addAction("Run", self.run_study)
            if not menu.isEmpty():
                menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def alive_(w):
        try:
            w.objectName()
            return True
        except RuntimeError:
            return False

    # ----------------------------------------------------------------------- the tab
    _state = {"index": None, "page": None, "dock": None}

    def _tabs():
        try:
            from . import shell as sh
            s = sh.shell()
            if s is not None and getattr(s, "enabled", False) and s.overlay is not None:
                return s.overlay.tasks
        except Exception as _fw_err:
            _fw_log("simxpress.py:1913", _fw_err)
        return None

    def _page(pane):
        p = XpressPage(pane)
        _state["page"] = p
        return p

    def add_tab(item, make):
        """A Task Pane tab added at the bottom while a tool is open (SimulationXpress, Costing)."""
        from . import taskpane
        from .chrome import TaskPaneTabs
        items = list(TaskPaneTabs.ITEMS)
        if item not in items:
            items.append(item)
            TaskPaneTabs.ITEMS = tuple(items)
        index = items.index(item)
        taskpane.register_page(index, make)
        tabs = _tabs()
        if tabs is not None:
            from . import icons
            while len(tabs.icons) < len(TaskPaneTabs.ITEMS):
                tabs.icons.append(icons.family(TaskPaneTabs.ITEMS[len(tabs.icons)][0]))
            tabs.resize(tabs.width(), int(len(TaskPaneTabs.ITEMS) * tabs.box_h + 1))
            tabs.update()
        return index

    def remove_tab(item):
        """The tab taken away again; the tabs below it move up (their pages with them)."""
        from . import taskpane
        from .chrome import TaskPaneTabs
        items = list(TaskPaneTabs.ITEMS)
        if item not in items:
            return
        index = items.index(item)
        tabs = _tabs()
        pane = getattr(tabs, "_pane", None) if tabs is not None else None
        if pane is not None and alive_(pane):
            w = pane.pages.pop(index, None)
            if w is not None:
                pane.stack.removeWidget(w)
                w.deleteLater()
            pane.pages = {(k - 1 if k > index else k): v for k, v in pane.pages.items()}
            pane.history = [h - 1 if h > index else h for h in pane.history if h != index]
            pane.at = len(pane.history) - 1
            if pane.index == index:
                pane.index = -1
                pane.close_pane()
            elif pane.index > index:
                pane.index -= 1
        del items[index]
        TaskPaneTabs.ITEMS = tuple(items)
        taskpane.PAGES.pop(index, None)
        for k in sorted(k for k in list(taskpane.PAGES) if k > index):
            taskpane.PAGES[k - 1] = taskpane.PAGES.pop(k)
        if tabs is not None:
            del tabs.icons[index]
            if tabs.active == index:
                tabs.active = 0
            elif tabs.active > index:
                tabs.active -= 1
            tabs.resize(tabs.width(), int(len(TaskPaneTabs.ITEMS) * tabs.box_h + 1))
            tabs.update()

    def _add_tab():
        _state["index"] = add_tab(TAB, _page)
        return _state["index"]

    def _remove_tab():
        remove_tab(TAB)
        _state["index"] = None

    def _in_assembly():
        try:
            from . import asmcore
            return asmcore.assembly_of(App.ActiveDocument) is not None
        except Exception:
            return False

    def open_xpress():
        """Tools > Xpress Products > SimulationXpress / Evaluate > SimulationXpress Analysis Wizard."""
        if _in_assembly():

            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), TITLE,
                "SimulationXpress analyzes single-body parts. Open the part you want to analyze "
                "(right-click a component > Open Part), then run SimulationXpress there.")
            return None
        from . import taskpane
        index = _add_tab()
        page = taskpane.open_tab(index)
        if page is None:
            dock = _state.get("dock")
            if dock is None or not alive_(dock):
                dock = QtWidgets.QDockWidget(TITLE, Gui.getMainWindow())
                dock.setObjectName("SWSimulationXpressDock")
                dock.setWidget(_page(None))
                Gui.getMainWindow().addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
                _state["dock"] = dock
            dock.show()
            page = dock.widget()
        else:
            try:
                taskpane.open_tab(index).parentWidget().parentWidget().pin.setChecked(True)
            except Exception as _fw_err:
                _fw_log("simxpress.py:2018", _fw_err)
        _state["page"] = page
        return page

    def close():
        """Close: the plots go, the tab goes; the study stays in the part for next time."""
        reset_plot()
        try:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
        except Exception as _fw_err:
            _fw_log("simxpress.py:2029", _fw_err)
        _remove_tab()
        dock = _state.get("dock")
        if dock is not None and alive_(dock):
            dock.close()
            dock.deleteLater()
        _state.update(page=None, dock=None)

    def page():
        p = _state.get("page")
        return p if p is not None and alive_(p) else None
