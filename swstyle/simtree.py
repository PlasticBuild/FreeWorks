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


import os

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

MESHED = "+meshed"            # icon key suffix: the key's icon with a green check
ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "simicons")
ACTIVE = {}                    # document name -> name of the study whose tree is shown
ASK = {"answer": None}         # checks: True / False answers the delete question
DELETE_TEXT = "Are you sure you want to delete %s?"


FIXTURES = {"Fem::ConstraintFixed": ("Fixed", "SIM_Fixed"), "Fem::ConstraintDisplacement": ("Roller/Slider", "SIM_Roller"),
            "Fem::ConstraintPlaneRotation": ("Fixed Hinge", "SIM_Hinge"), "Fem::ConstraintSpring": ("Elastic Support", "SIM_Elastic"),
            "Fem::ConstraintRigidBody": ("Rigid", "SIM_Rigid"), "Fem::ConstraintTransform": ("Reference Geometry", "SIM_Rigid")}
LOADS = {"Fem::ConstraintForce": ("Force", "SIM_Force"), "Fem::ConstraintPressure": ("Pressure", "SIM_Pressure"),
         "Fem::ConstraintSelfWeight": ("Gravity", "SIM_Gravity"), "Fem::ConstraintCentrif": ("Centrifugal", "SIM_Centrifugal"),
         "Fem::ConstraintBearing": ("Bearing Load", "SIM_Bearing")}
# the PM's kept kind (simpms) -> External Load: these sit on a FEM force or rigid body underneath (PM pkg356)
PM_LOADS = {"Torque": ("Torque", "SIM_Torque"), "Bearing Load": ("Bearing Load", "SIM_Bearing"),
            "Distributed Mass": ("Distributed Mass", "SIM_DistributedMass"), "Remote Load": ("Remote Load", "SIM_RemoteLoad"),
            "Centrifugal": ("Centrifugal", "SIM_Centrifugal"),
            "Pressure": ("Pressure", "SIM_Pressure")}     # Use reference geometry: a FEM force underneath (PM pkg360)
CARRIER = "FwSimLoad"          # simpms.CARRIER
FREE_SET = "FwContactSet"      # simconnect.SET: a contact set's item (a Free set is a plain feature holding faces)
THERMAL = {"Fem::ConstraintTemperature": ("Temperature", "SIM_Temperature"), "Fem::ConstraintHeatflux": ("Heat Flux", "SIM_HeatFlux"),
           "Fem::ConstraintBodyHeatSource": ("Heat Power", "SIM_BodyHeat"),
           "Fem::ConstraintInitialTemperature": ("Initial Temperature", "SIM_InitialTemp")}
CONNECTIONS = {"Fem::ConstraintContact": ("Contact Set", "SIM_Contact"), "Fem::ConstraintTie": ("Bonded", "SIM_Bonded")}
ELEMENTS = {"Fem::ElementGeometry1D": "SIM_Beam", "Fem::ElementGeometry2D": "SIM_Shell", "Fem::ElementRotation1D": "SIM_BeamRotation",
            "Fem::ElementFluid1D": "SIM_Beam"}
FLOW_BC = {"Fem::ConstraintFlowVelocity": "FLOW_Velocity", "Fem::ConstraintPressure": "FLOW_Pressure",
           "Fem::ConstraintTemperature": "SIM_Temperature"}
FLOW_INIT = {"Fem::ConstraintInitialFlowVelocity": "FLOW_InitVel", "Fem::ConstraintInitialPressure": "FLOW_InitPress",
             "Fem::ConstraintInitialTemperature": "SIM_InitialTemp"}
FLOW_HEAT = {"Fem::ConstraintHeatflux": "SIM_HeatFlux", "Fem::ConstraintBodyHeatSource": "SIM_BodyHeat"}
FLOW_PLOTS = (("Cut Plots", ("Fem::FemPostClipFilter", "Fem::FemPostCutFilter"), "SIM_Section"),
              ("Isosurfaces", ("Fem::FemPostContoursFilter", "Fem::FemPostScalarClipFilter"), "SIM_IsoClip"),
              ("XY Plots", ("Fem::FemPostDataAlongLineFilter",), "SIM_ListLine"),
              ("Point Parameters", ("Fem::FemPostDataAtPointFilter",), "SIM_Probe"))
KIND_WORDS = {"static": "Static", "frequency": "Frequency", "buckling": "Buckling", "thermomech": "Thermal", "check": "Static",
              "fatigue": "Fatigue", "drop": "Drop Test"}
COMP_WORDS = {"VON": "vonMises", "URES": "Res disp", "ESTRN": "Equivalent"}
COMPONENTS_TREE = ("Stress", "Displacement", "Strain")      # a drop test's plots read as a static study's


# --------------------------------------------------------------------------- what a study holds
def ftype(o):
    """FreeCAD's type of a FEM object: a Python feature's Proxy.Type, else its TypeId."""
    t = getattr(getattr(o, "Proxy", None), "Type", None)
    return t if isinstance(t, str) and t else o.TypeId


def is_study(o):
    try:
        return o is not None and o.isDerivedFrom("Fem::FemAnalysis")
    except Exception:
        return False


def is_flow(a):
    from . import studytools
    return studytools.is_flow(a)


def studies(doc, flow=False):
    """The document's Simulation studies (flow=False) or Flow Simulation projects (flow=True), in the order made."""
    if doc is None:
        return []
    return [o for o in doc.Objects if is_study(o) and is_flow(o) == bool(flow)]


def kind(a):
    if is_flow(a):
        return "flow"
    from . import simstudy
    return simstudy._kind_of(a)


def _members(a):
    out = []
    for o in a.Group:
        out.append(o)
    return out


def _material_name(m):
    try:
        mat = m.Material or {}
        return mat.get("Name") or m.Label
    except Exception:
        return m.Label


def is_fluid(m):
    return "Fluid" in ftype(m) or getattr(m, "Category", "") == "Fluid"


def _materials(a):
    return [o for o in a.Group if ftype(o).startswith("Fem::Material") or o.TypeId.startswith("App::MaterialObject")]


def _meshes(a):
    return [o for o in a.Group if o.isDerivedFrom("Fem::FemMeshObject")]


def mesh_children(m):
    """A mesh's controls and boundary layers: FreeCAD 1.1 keeps them in the mesh's lists (MeshRegionList ...), not
    only in its Group (an Apply Mesh Control made no row under Mesh)."""
    out = []
    for prop in ("Group", "MeshRegionList", "MeshBoundaryLayerList", "MeshGroupList"):
        for c in list(getattr(m, prop, None) or []):
            if c is not None and c not in out:
                out.append(c)
    return out


def _results(a):
    return [o for o in a.Group if o.isDerivedFrom("Fem::FemResultObject") or o.isDerivedFrom("Fem::FemPostPipeline")
            or ftype(o) in ("Fem::FemResultMechanical",)]


def _solids(a):
    """The part's bodies the study is on: what its meshes are made of (their Shape links)."""
    out = []
    for m in _meshes(a):
        s = getattr(m, "Shape", None)
        if s is not None and s not in out:
            out.append(s)
    if not out:
        from . import simpms
        s = simpms.target(a.Document, a)
        if s is not None:
            out.append(s)
    return out


def config_name(doc):
    try:
        from . import configmanager
        for name in ("active_name", "active_config", "current"):
            fn = getattr(configmanager, name, None)
            if callable(fn):
                n = fn(doc)
                if isinstance(n, str) and n:
                    return n
                if n is not None and getattr(n, "Label", None):
                    return n.Label
    except Exception as _fw_err:
        _fw_log("simtree.py:config", _fw_err)
    return "Default"


class Row:
    """One row of a study tree: text, icon key, the FreeCAD object (or a plot name), its menu kind, its rows."""
    __slots__ = ("text", "icon", "obj", "what", "rows", "plot", "tip")

    def __init__(self, text, icon=None, obj=None, what="item", plot=None, tip=None):
        self.text, self.icon, self.obj, self.what, self.plot, self.tip = text, icon, obj, what, plot, tip
        self.rows = []

    def add(self, row):
        self.rows.append(row)
        return row

    def dump(self, depth=0):
        """Text lines, two spaces a level: what the checks read."""
        out = ["  " * depth + self.text]
        for r in self.rows:
            out += r.dump(depth + 1)
        return out


def carried(o):
    """The kept load data of a Torque / Bearing Load / Distributed Mass (a FEM force left Suppressed for FreeCAD's
    writer, written by simpms.cyclic_inp), else {}."""
    if CARRIER not in getattr(o, "PropertiesList", ()):
        return {}
    try:
        from . import simpms
        return simpms.carrier(o)
    except Exception as _fw_err:
        _fw_log("simtree.py:carried", _fw_err)
        return {}


def is_suppressed(o):
    c = carried(o)
    if c:
        return bool(c.get("suppressed"))
    return bool(getattr(o, "Suppressed", False))


def _pm_kind(o):
    try:
        from . import simpms
        return simpms.kept(o).get("kind")
    except Exception:
        return None


def load_kind(o):
    ""

    k = _pm_kind(o)
    if k in PM_LOADS:
        return PM_LOADS[k]
    t = ftype(o)
    if t in LOADS and t != "Fem::ConstraintRigidBody":
        return LOADS[t]
    return None


def shell_entry(a, out):
    ""

    try:
        from . import simpms, simroutes
        g = simpms.target(a.Document, a)
        shape = getattr(g, "Shape", None)
        if shape is None or shape.isNull():
            return
        free = len(shape.Faces) - sum(len(s.Faces) for s in shape.Solids)
        if free > 0 and hasattr(simroutes, "open_shell"):
            out.append(("-", None))
            out.append(("Define Shell By Selected Faces...", lambda: simroutes.open_shell()))
    except Exception as _fw_err:
        _fw_log("simtree.py:shell_entry", _fw_err)


def draft_entry(a, out):
    ""

    from . import simpms
    m = simpms.gmsh_of(a)
    if m is None or "ElementOrder" not in m.PropertiesList:
        return
    draft = m.ElementOrder == "1st"

    def flip():
        import Fem
        m.ElementOrder = "2nd" if draft else "1st"
        k = simpms.kept(m)
        if k:
            k["draft"] = not draft
            simpms._keep(m, **k)
        if getattr(getattr(m, "FemMesh", None), "NodeCount", 0):
            m.FemMesh = Fem.FemMesh()
        m.Document.recompute()
        refresh()
    out.append(("Apply High Quality Mesh" if draft else "Apply Draft Quality Mesh", flip))


def _item_text(o):
    sup = " (Suppressed)" if is_suppressed(o) else ""
    try:
        from . import simpms
        name = simpms.study_name(o)
    except Exception:
        name = o.Label
    return name + _load_words(o) + sup


def _load_words(o):
    ""
    try:
        if getattr(o, "TypeId", "") != "Fem::ConstraintForce" or getattr(o, "Suppressed", False):
            return ""
        from . import simpms
        k = simpms.kept(o)
        if "value" not in k or k.get("direction") or k.get("kind") not in (None, "Force"):
            return ""
        v = float(k["value"])
        text = "{:,.0f}".format(v) if abs(v - round(v)) < 1e-9 else "{:,g}".format(v)
        sign = "" if k.get("reverse") else "-"
        return " (:%s: %s%s %s:)" % ("Per item" if k.get("per_item") else "Total", sign, text, k.get("unit") or "N")
    except Exception as _fw_err:
        _fw_log("simtree.py:load words", _fw_err)
        return ""


def unrun_mark(a):
    ""
   # look-audit simlook-1120
    try:
        from . import simplots
        if simplots.result(a) is None:
            return "*"
        from . import simpressure
        return "*" if simpressure.out_of_date(a) else ""
    except Exception as _fw_err:
        _fw_log("simtree.py:unrun_mark", _fw_err)
        return ""


def study_rows(a):
    ""
    k = kind(a)
    from . import simtypes
    own = simtypes.study_rows(a, Row)          # a fatigue study's own tree
    if own is not None:
        return own
    root = Row("%s%s (-%s-)" % (a.Label, unrun_mark(a), config_name(a.Document)), "SIM_Analysis", a, "study")   # look-audit simlook-1120
    doc = a.Document
    mats = _materials(a)
    common = [m for m in mats if not list(getattr(m, "References", []) or [])]
    from . import asmsim
    asm_study = asmsim.is_assembly_study(a)
    part = asmsim.part_rows(a, root, Row) if asm_study else root.add(Row(doc.Label or doc.Name, "SIM_ApplyMaterial", None, "part"))
    solids = [] if asm_study else _solids(a)
    for n, s in enumerate(solids, 1):
        own = [m for m in mats if any(r[0] is s for r in (getattr(m, "References", []) or []))]
        m = (own or common or [None])[0]
        text = "SolidBody %d(%s)" % (n, s.Label)
        text += " (-%s-)" % _material_name(m) if m is not None else ""
        part.add(Row(text, "SIM_ApplyMaterial", s, "body", tip=getattr(m, "Name", None)))
    for o in a.Group:
        if ftype(o) in ELEMENTS:
            part.add(Row(_item_text(o), ELEMENTS[ftype(o)], o, "item"))
    thermal = k == "thermomech"
    conn = root.add(Row("Connections", "SIM_Contact", None, "connections"))
    if thermal:
        loads = root.add(Row("Thermal Loads", "SIM_Temperature", None, "thermal"))
        fixtures = None
    else:
        fixtures = root.add(Row("Fixtures", "SIM_Fixed", None, "fixtures"))
        loads = root.add(Row("External Loads", "SIM_Force", None, "loads"))
    mesh = root.add(Row("Mesh", "SIM_Mesh", None, "mesh"))
    results = root.add(Row("Results", "SIM_Results", None, "results"))
    for o in a.Group:
        t = ftype(o)
        if asmsim.AUTO in o.PropertiesList:          # remade from the interactions on each run
            continue
        lk = load_kind(o)
        if t in CONNECTIONS:
            conn.add(Row(_item_text(o), CONNECTIONS[t][1], o, "item"))
        elif FREE_SET in o.PropertiesList and o.TypeId == "App::FeaturePython":
            conn.add(Row(_item_text(o), "SIM_Contact", o, "item"))     # a Free contact set (PM pkg357)
        elif lk is not None and not thermal:
            loads.add(Row(_item_text(o), lk[1], o, "item"))
        elif t in FIXTURES and fixtures is not None:
            fixtures.add(Row(_item_text(o), FIXTURES[t][1], o, "item"))
        elif t in THERMAL:
            if not hidden_initial(a, o):
                loads.add(Row(_item_text(o), THERMAL[t][1], o, "item"))
        elif t in LOADS and not thermal:
            loads.add(Row(_item_text(o), LOADS[t][1], o, "item"))
        elif t in FIXTURES and thermal:
            loads.add(Row(_item_text(o), FIXTURES[t][1], o, "item"))
    asmsim.connection_rows(a, conn, Row)
    for m in _meshes(a):
        mesh.obj = m
        try:
            if m.FemMesh.NodeCount:
                mesh.icon = "SIM_Mesh" + MESHED
        except Exception:
            pass
        for c in mesh_children(m):
            mesh.add(Row(_item_text(c), "SIM_MeshControl" if "Region" in ftype(c) else "SIM_MeshBoundary", c, "item"))
    _result_rows(a, results)
    if not results.rows and not _results(a):
        root.rows.remove(results)
    from . import simreport
    done = simreport.reports(a)
    if done:
        folder = root.add(Row("Report", "SIM_Report", None, "reports"))
        for path in done:
            folder.add(Row(os.path.splitext(os.path.basename(path))[0], "SIM_Report", None, "report", tip=path))
    return simtypes.adjust_rows(a, root, Row)  # a drop test: Setup and Result Options


def _result_rows(a, folder):
    from . import simplots
    res = None
    try:
        res = simplots.result(a)
    except Exception:
        res = None
    if res is not None and kind(a) in ("static", "check"):
        try:
            simplots.defaults(a)
        except Exception as _fw_err:
            _fw_log("simtree.py:defaults", _fw_err)
        for p in simplots.plots(a):
            comp = COMP_WORDS.get(p["comp"], p["comp"])
            text = simplots.title(p) if p["quantity"] == "Factor of Safety" else "%s (-%s-)" % (p["name"], comp)
            folder.add(Row(text, "SIM_Results", res, "plot", plot=p["name"]))
        return
    if res is not None and kind(a) in simplots.KINDS:  # mode shapes, thermal plots, a drop test's plots
        try:
            simplots.defaults(a)
        except Exception as _fw_err:
            _fw_log("simtree.py:defaults2", _fw_err)
        for p in simplots.plots(a):
            text = simplots.title(p)
            if p["quantity"] in COMPONENTS_TREE:
                text = "%s (-%s-)" % (p["name"], COMP_WORDS.get(p["comp"], p["comp"]))
            folder.add(Row(text, "SIM_Results", res, "plot", plot=p["name"]))
        return
    for o in _results(a):
        folder.add(Row(o.Label, "SIM_Results", o, "result"))
        for f in list(getattr(o, "Filter", None) or getattr(o, "Group", None) or []):
            folder.add(Row(f.Label, "SIM_Section", f, "result"))


def flow_rows(a):
    """The Flow Simulation analysis tree of project a."""
    root = Row(a.Label, "FLOW_Project", a, "flowproject")
    data = root.add(Row("Input Data", "FLOW_Equation", None, "folder"))
    fluids = data.add(Row("Fluid Subdomains", "FLOW_Fluid", None, "fluids"))
    solids = data.add(Row("Solid Materials", "SIM_ApplyMaterial", None, "solidmats"))
    bcs = data.add(Row("Boundary Conditions", "FLOW_Velocity", None, "bcs"))
    inits = data.add(Row("Initial Conditions", "FLOW_InitVel", None, "inits"))
    heat = data.add(Row("Heat Sources", "FLOW_Sources", None, "heat"))
    mesh = data.add(Row("Mesh", "FLOW_Mesh", None, "flowmesh"))
    for m in _materials(a):
        (fluids if is_fluid(m) else solids).add(Row("%s (%s)" % (m.Label, _material_name(m)) if m.Label != _material_name(m)
                                                            else m.Label, "FLOW_Fluid" if is_fluid(m) else "SIM_ApplyMaterial",
                                                            m, "item"))
    for o in a.Group:
        t = ftype(o)
        if t in FLOW_INIT:
            inits.add(Row(_item_text(o), FLOW_INIT[t], o, "item"))
        elif t in FLOW_HEAT:
            heat.add(Row(_item_text(o), FLOW_HEAT[t], o, "item"))
        elif t in FLOW_BC:
            bcs.add(Row(_item_text(o), FLOW_BC[t], o, "item"))
    for m in _meshes(a):
        mesh.obj = m
        mesh.add(Row("Global Mesh (%s)" % m.Label, "SIM_Mesh", m, "meshobj"))
        for c in list(getattr(m, "Group", []) or []):
            mesh.add(Row(_item_text(c), "SIM_MeshControl", c, "item"))
    results = root.add(Row("Results", "FLOW_Results", None, "flowresults"))
    pipes = [o for o in _results(a) if o.isDerivedFrom("Fem::FemPostPipeline")]
    surf = results.add(Row("Surface Plots", "FLOW_Results", None, "flowplots"))
    for p in pipes:
        surf.add(Row(p.Label, "FLOW_Results", p, "result"))
    for name, types, icon in FLOW_PLOTS:
        f = results.add(Row(name, icon, None, "flowplots:" + icon))
        for p in pipes:
            for c in list(getattr(p, "Filter", None) or []):
                if c.TypeId in types:
                    f.add(Row(c.Label, icon, c, "result"))
    for o in _results(a):
        if not o.isDerivedFrom("Fem::FemPostPipeline"):
            results.add(Row(o.Label, "FLOW_Results", o, "result"))
    return root


def signature(a):
    """What the tree shows of a: it is rebuilt only when this changes."""
    out = [a.Label, config_name(a.Document)]
    def walk(o):
        card = getattr(o, "Material", None)
        if isinstance(card, dict):
            out.append(card.get("Name"))          # Apply Material: the part row's (-name-) follows
        out.append((o.Name, o.Label, getattr(o, "FwSimPM", None), getattr(o, "Suppressed", None), len(getattr(o, "Group", None) or []),
                    len(getattr(o, "Filter", None) or []), getattr(getattr(o, "ViewObject", None), "Visibility", None)))
        for c in list(getattr(o, "Group", None) or []) + list(getattr(o, "Filter", None) or []):
            walk(c)
    for o in a.Group:
        walk(o)
    out.append(getattr(a, "FwPlots", ""))
    for o in a.Group:                          # look-audit SM-2: the Mesh row's green check as soon as it is meshed
        if o.isDerivedFrom("Fem::FemMeshObject"):
            try:
                out.append(bool(o.FemMesh.NodeCount))
            except Exception:
                out.append(None)
    out.append(getattr(a, "FwGlobalInteraction", None))       # an assembly study's Global Interaction (-Contact-) row
    out.append(tuple(getattr(a, "FwReports", []) or ()))      # a published report: the Report folder
    try:
        from . import simstudy
        out.append(simstudy._kind_of(a))
        from . import simtypes
        out.append(simtypes.properties(a).get("steady"))  # steady state or transient: the initial temperature row
    except Exception as _fw_err:
        _fw_log("simtree.py:sig", _fw_err)
    return tuple(out)


# --------------------------------------------------------------------------- actions
def _ask(text):
    if ASK["answer"] is not None:
        return bool(ASK["answer"])
    r = QtWidgets.QMessageBox.question(Gui.getMainWindow(), "FreeCAD", text,
                                       QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.Yes)
    return r == QtWidgets.QMessageBox.Yes


def _make_active(a):
    from . import addintabs
    addintabs._set_active(a)


def _select(obj):
    try:
        Gui.Selection.clearSelection()
        if obj is not None:
            Gui.Selection.addSelection(obj.Document.Name, obj.Name)
    except Exception as _fw_err:
        _fw_log("simtree.py:select", _fw_err)


# FreeCAD commands that act on a picked object: the Simulation tab and the study tree pick it for them, as

def _pipeline(a):
    found = [o for o in (a.Group if a is not None else []) if o.isDerivedFrom("Fem::FemPostPipeline")]
    return found[-1] if found else None


def _material(a):
    found = [o for o in (a.Group if a is not None else []) if o.TypeId.startswith("Fem::MaterialCommon")
             or getattr(getattr(o, "Proxy", None), "Type", "") in ("Fem::MaterialCommon", "Fem::MaterialMechanicalNonlinear")
             or (hasattr(o, "Material") and isinstance(getattr(o, "Material", None), dict) and o.TypeId.startswith("App::Material"))]
    return found[0] if found else None


def _solver(a):
    found = [o for o in (a.Group if a is not None else []) if o.isDerivedFrom("Fem::FemSolverObjectPython")
             or o.TypeId.startswith("Fem::FemSolver")]
    return found[0] if found else None


def _geometry(a):
    try:
        from . import simpms
        mesh = simpms.gmsh_of(a)
        if mesh is not None and getattr(mesh, "Shape", None) is not None:
            return mesh.Shape
    except Exception as _fw_err:
        _fw_log("simtree.py:geometry", _fw_err)
    return None


def _mesh(a):
    from . import simpms
    return simpms.gmsh_of(a)


CONTEXT = {"SIM_PlotTools": _pipeline, "SIM_Diagnostic": _mesh, "SIM_MeshInfo": _mesh, "SIM_MeshControl": _mesh, "SIM_MeshBoundary": _mesh, "SIM_MeshNetgen": _geometry,
           "SIM_SolverControl": _solver, "SIM_MaterialNonlinear": _material, "SIM_Deform": _pipeline,
           "SIM_IsoClip": _pipeline, "SIM_Section": _pipeline, "SIM_ListLine": _pipeline, "SIM_Linearized": _pipeline}


def hidden_initial(a, o):
    ""

    try:
        from . import simpms, simtypes
        if o.TypeId != "Fem::ConstraintInitialTemperature" or simtypes.study_type(a) != "thermomech":
            return False
        if simpms.kept(o).get("initial"):
            return False
        return bool(simtypes.properties(a).get("steady", True))
    except Exception:
        return False


def _ctx_study():
    """The study the Simulation tab acts on: the active one, else FreeCAD's active analysis."""
    doc = App.ActiveDocument
    if doc is None:
        return None
    try:
        a = active_study(doc)
        if a is not None:
            return a
        from . import addintabs
        return addintabs._active_analysis(doc)
    except Exception:
        return None


def context_object(key, a=None):
    pick = CONTEXT.get(key)
    if pick is None:
        return None
    try:
        return pick(a if a is not None else _ctx_study())
    except Exception as _fw_err:
        _fw_log("simtree.py:context", _fw_err)
        return None


class _ContextCmd:
    """A Simulation tab button for a FreeCAD command that needs its object picked: on when the active study has
    that object (the mesh, the solver, the material, the result), and it picks it, then runs the command."""

    def __init__(self, key, natives, res):
        self.key, self.natives, self.res = key, tuple(natives), res

    def GetResources(self):
        return dict(self.res)

    def IsActive(self):
        return context_object(self.key) is not None

    def Activated(self, *_a):
        obj = context_object(self.key)
        if obj is None:
            return
        _select(obj)
        for name in self.natives:
            if Gui.Command.get(name) is not None:
                Gui.runCommand(name, 0)
                return


def install_context_commands():
    """Puts a picking command first on each CONTEXT key (once FEM's commands exist)."""
    from . import catalog
    done = 0
    for key in CONTEXT:
        cmd = catalog.BY_KEY.get(key)
        if cmd is None:
            continue
        name = "SWStyle_SimCtx_" + key[4:]
        natives = [n for n in cmd.natives if n != name]
        if name not in Gui.listCommands():
            res = {"MenuText": cmd.label, "ToolTip": getattr(cmd, "tip", "") or cmd.label}
            for n in natives:
                c = Gui.Command.get(n)
                if c is not None:
                    try:
                        info = c.getInfo()
                        res["Pixmap"] = info.get("pixmap") or info.get("Pixmap") or ""
                        res["ToolTip"] = info.get("toolTip") or res["ToolTip"]
                    except Exception as _fw_err:
                        _fw_log("simtree.py:ctxinfo", _fw_err)
                    break
            Gui.addCommand(name, _ContextCmd(key, natives, res))
        if not cmd.natives or cmd.natives[0] != name:
            cmd.natives = (name,) + tuple(natives)
            done += 1
    return done


def run_key(key, a=None, obj=None):
    """Runs the first command of catalog key `key` that FreeCAD has (study a made active, obj picked first)."""
    from . import catalog
    if a is not None:
        _make_active(a)
    if obj is None:
        obj = context_object(key, a)
    if obj is not None:
        _select(obj)
    cmd = catalog.BY_KEY.get(key)
    for name in (cmd.natives if cmd is not None else ()):
        c = Gui.Command.get(name)
        if c is not None:
            Gui.runCommand(name, 0)
            return name
    return None


def key_on(key, a=None):
    """True when the key's command is on with study a active (a load the study type has)."""
    from . import catalog
    cmd = catalog.BY_KEY.get(key)
    if cmd is None:
        return False
    if a is not None:
        _make_active(a)
    for n in cmd.natives:           # the command run_key runs: the first one FreeCAD has
        c = Gui.Command.get(n)
        if c is not None:
            try:
                return bool(c.isActive())
            except Exception as _fw_err:
                _fw_log("simtree.py:key_on", _fw_err)
                return True
    return False


def has_key(key):
    from . import catalog
    cmd = catalog.BY_KEY.get(key)
    return cmd is not None and any(Gui.Command.get(n) is not None for n in cmd.natives)


def edit(obj):
    """Edit Definition: the object's PropertyManager (ours where there is one: simconnect's hook redirects)."""
    from . import asmsim
    if asmsim.is_ours(obj):                   # an interaction or connector: its PropertyManager
        return asmsim.edit(obj)
    from . import simtypes
    if simtypes.is_ours(obj):                 # a thermal load or a fatigue event made here
        return simtypes.edit(obj)
    if FREE_SET in obj.PropertiesList:          # a contact set (Free has no FreeCAD panel at all)
        from . import simconnect
        if hasattr(simconnect, "edit_definition") and simconnect.edit_definition(obj) is not None:
            return None
    if "FwMeshControl" in obj.PropertiesList:  # a mesh control made by the Mesh Control PM (PM pkg358)
        from . import simpms
        if hasattr(simpms, "edit_definition") and simpms.edit_definition(obj) is not None:
            return None
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    Gui.getDocument(obj.Document.Name).setEdit(obj.Name)


def mesh_and_run(a, m):
    """Mesh and Run: the mesh made again with its settings, then the study solved (the run window shows both)."""
    import Fem
    m.FemMesh = Fem.FemMesh()                 # an empty mesh: Run meshes first
    m.Document.recompute()
    run_key("SIM_Run", a)


def set_suppressed(obj, on):
    if carried(obj):                          # Torque / Bearing Load / Distributed Mass: the FEM force stays Suppressed
        from . import simpms
        simpms.suppress_carrier(obj, on)
    else:
        obj.Suppressed = bool(on)
    obj.Document.recompute()


def set_shown(objs, on):
    for o in objs:
        try:
            o.ViewObject.Visibility = bool(on)
        except Exception as _fw_err:
            _fw_log("simtree.py:shown", _fw_err)


def _tree_of(o):
    out = []
    for c in list(getattr(o, "Group", None) or []) + list(getattr(o, "Filter", None) or []):
        out += _tree_of(c)
    return out + [o]


def delete_objects(objs, ask=True):
    if not objs:
        return False
    if ask and not _ask(DELETE_TEXT % (objs[0].Label if len(objs) == 1 else "the %d items" % len(objs))):
        return False
    doc = objs[0].Document
    doc.openTransaction("Delete")
    try:
        names = []
        for o in objs:
            for x in _tree_of(o):
                if x.Name not in names:
                    names.append(x.Name)
        for n in names:
            if doc.getObject(n) is not None:
                doc.removeObject(n)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return True


def delete_study(a, ask=True):
    doc = a.Document
    if ask and not _ask(DELETE_TEXT % a.Label):
        return False
    if ACTIVE.get(doc.Name) == a.Name:
        deactivate(doc)
    members = list(a.Group)
    doc.openTransaction("Delete study")
    try:
        names = []
        for o in members:
            for x in _tree_of(o):
                names.append(x.Name)
        names.append(a.Name)
        for n in names:
            if doc.getObject(n) is not None:
                doc.removeObject(n)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return True


def copy_study(a):
    from . import studytools
    b = studytools.duplicate(a)
    return b


# ------------------------------------------------------------------ Copy / Paste between studies

# or Copy (Ctrl+C) and Paste (Ctrl+V) there. The copy keeps its definition and takes the next name in that study.
CLIP = {"doc": None, "items": []}       # items: [(object name, folder kind)]
COPY_FOLDERS = ("connections", "fixtures", "loads")
MIME = "application/x-freecad-sim-items"


def _folder_rows(a):
    root = study_rows(a)
    return {r.what: r for r in root.rows if r.what in COPY_FOLDERS}


def _copyable(a):
    """[(object, folder kind)] of the rows Copy can take in study a."""
    out = []
    for what, r in _folder_rows(a).items():
        for c in r.rows:
            o = c.obj
            if c.what == "item" and o is not None and getattr(o, "Document", None) is not None:
                from . import asmsim
                if asmsim.AUTO not in o.PropertiesList:
                    out.append((o, what))
    return out


def copy_items(a, objs):
    """Copy (Ctrl+C) in the study tree: the fixtures, loads or connectors objs of study a."""
    fold = {o.Name: w for o, w in _copyable(a)}
    items = [(o.Name, fold[o.Name]) for o in objs if o is not None and o.Name in fold]
    if items:
        CLIP["doc"], CLIP["items"] = a.Document.Name, items
    return items


def clipboard(doc, b=None, folder=None):
    """[(object, folder kind)] Paste would put in study b (in folder, else in the folders b has)."""
    if doc is None or CLIP["doc"] != doc.Name:
        return []
    have = set(_folder_rows(b)) if b is not None else set(COPY_FOLDERS)
    out = []
    for name, what in CLIP["items"]:
        o = doc.getObject(name)
        if o is not None and what in have and (folder is None or what == folder):
            out.append((o, what))
    return out


def _base_name(o):
    from . import simpms
    import re
    return re.sub(r"-\d+$", "", simpms.study_name(o)) or o.Label


def paste_items(b, objs):
    """The copies of objs (fixtures, loads, connectors) in study b, each with b's next name (Fixed-1, Fixed-2...)."""
    from . import simpms
    doc = b.Document
    made = []
    doc.openTransaction("Paste")
    try:
        for o in objs:
            k = simpms.kept(o)
            helpers = [doc.getObject(n) for n in (k.get("helpers") or [])]
            helpers = [h for h in helpers if h is not None]
            copies = {}
            c = doc.copyObject(o, False)
            copies[o.Name] = c
            for h in helpers:
                copies[h.Name] = doc.copyObject(h, False)
            for x in copies.values():            # the copies point at each other, not back at the originals
                for prop in x.PropertiesList:
                    if prop in ("Group", "ExpressionEngine", "Label", "Label2"):
                        continue
                    try:
                        v = x.getPropertyByName(prop)
                    except Exception:
                        continue
                    if isinstance(v, App.DocumentObject) and v.Name in copies:
                        setattr(x, prop, copies[v.Name])
                    elif isinstance(v, list) and v and all(isinstance(y, App.DocumentObject) for y in v) and \
                            any(y.Name in copies for y in v):
                        setattr(x, prop, [copies.get(y.Name, y) for y in v])
            if helpers:
                k["helpers"] = [copies[h.Name].Name for h in helpers]
                simpms._keep(c, **k)
            for h in helpers:
                b.addObject(copies[h.Name])
            b.addObject(c)
            simpms._set_label(c, simpms._label(b, _base_name(o)))
            try:
                if c.TypeId in simpms.SYMBOL_COLOUR:
                    simpms.symbol(c, simpms.SYMBOL_COLOUR[c.TypeId])
                if getattr(o, "ViewObject", None) is not None and getattr(c, "ViewObject", None) is not None:
                    c.ViewObject.Visibility = o.ViewObject.Visibility
            except Exception as _fw_err:
                _fw_log("simtree.py:pastelook", _fw_err)
            made.append(c)
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    doc.recompute()
    if Gui is not None:
        refresh()
    return made


def paste(b, folder=None):
    """Paste (Ctrl+V) in study b: what Copy took, into the folders b has."""
    return paste_items(b, [o for o, _w in clipboard(b.Document, b, folder)])


def clip_entries(row, a, out):
    """Copy on a fixture, load or connector row and on its folder; Paste on the study and the folder once there is
    something Copy took that the study can have (never a dead Paste)."""
    w, o = row.what, row.obj
    if a is None:
        return out
    mine = {x.Name for x, _f in _copyable(a)}
    if w == "item" and o is not None and o.Name in mine:
        out.append(("Copy", lambda: copy_items(a, [o])))
    elif w in COPY_FOLDERS:
        kids = [c.obj for c in row.rows if c.obj is not None and c.obj.Name in mine]
        if kids:
            out.append(("Copy", lambda: copy_items(a, kids)))
        if clipboard(a.Document, a, w):
            out.append(("Paste", lambda: paste(a, w)))
    elif w == "study" and clipboard(a.Document, a):
        out.append(("Paste", lambda: paste(a)))
    return out


def rename(o, text):
    text = (text or "").strip()
    if text:
        o.Label = text
    return o.Label


def new_study():
    return run_key("SIM_NewStudy")


def activate(doc, a):
    """The study's tab: it becomes the active study and its tree shows below the FeatureManager."""
    ACTIVE[doc.Name] = a.Name
    try:
        _make_active(a)
    except Exception as _fw_err:
        _fw_log("simtree.py:activate", _fw_err)
    if Gui is not None:
        refresh()
    return a


def deactivate(doc):
    """Model (or a Motion Study tab): the study tree folds away and the plot leaves the model."""
    if doc is None:
        return
    had = ACTIVE.pop(doc.Name, None)
    if had is not None and Gui is not None:
        try:
            from . import simplots
            if simplots.SHOWN.get("a") is not None and simplots.SHOWN["a"].Document is doc:
                simplots.clear()
        except Exception as _fw_err:
            _fw_log("simtree.py:deactivate", _fw_err)
        refresh()


def active_study(doc):
    name = ACTIVE.get(doc.Name) if doc is not None else None
    o = doc.getObject(name) if name else None
    if name and o is None:
        ACTIVE.pop(doc.Name, None)
    return o


# --------------------------------------------------------------------------- right-click menus
def menu_entries(row, a):
    ""
    out = []
    w, o = row.what, row.obj

    def key(text, k, obj=None, study_type=False):
        if has_key(k) and (not study_type or key_on(k, a)):
            out.append((text, lambda: run_key(k, a, obj)))

    def compare(name=None):
        """Compare Results...: the view thread's synced views (simplotview.compare), else the Compare tool."""
        try:
            from . import simplotview
            if hasattr(simplotview, "compare"):
                out.append(("Compare Results...", lambda: simplotview.compare(a, name)))
                return
        except ImportError:
            pass
        key("Compare Results...", "SIM_Compare")

    def show_hide(objs):
        objs = [x for x in objs if x is not None and getattr(x, "ViewObject", None) is not None]
        if not objs:
            return
        if w in ("item", "body"):           # one row: Hide or Show, as it stands
            vis = bool(objs[0].ViewObject.Visibility)
            out.append(("Hide" if vis else "Show", lambda: set_shown(objs, not vis)))
        else:                               # a folder: both
            out.append(("Hide All", lambda: set_shown(objs, False)))
            out.append(("Show All", lambda: set_shown(objs, True)))

    kids = [r.obj for r in row.rows if r.obj is not None and getattr(r.obj, "ViewObject", None) is not None
            and r.what != "ours"]
    from . import asmsim
    ext = asmsim.menu_entries(row, a, key)
    if ext is not None:                       # an assembly study's rows (interactions, connectors, parts)
        return out + ext
    from . import simtypes
    ext = simtypes.menu_entries(row, a, key)
    if ext is not None:                       # the other study types' rows (events, setup, lists of modes)
        return out + ext
    if w in ("study", "flowproject"):
        key("Run", "SIM_Run")
        if w == "study":
            key("Properties...", "SIM_Props")
            key("Study Advisor...", "SIM_Advisor")
            key("Report...", "SIM_Report")
        out.append(("-", None))
        if w == "study":
            out.append(("Copy Study", lambda: copy_study(a)))
        elif has_key("FLOW_Clone"):
            out.append(("Clone Project", lambda: run_key("FLOW_Clone", a)))
        out.append(("Rename", None))
        out.append(("Delete", lambda: delete_study(a)))
    elif w in ("part", "body"):
        mats = _materials(a)
        if mats and asmsim.is_assembly_study(a) is False and has_key("SIM_ApplyMaterial"):
            out.append(("Apply/Edit Material...", lambda: run_key("SIM_ApplyMaterial", a)))   # the Material dialog
        elif mats:
            out.append(("Apply/Edit Material...", lambda: edit(mats[0])))
        else:
            key("Apply/Edit Material...", "SIM_ApplyMaterial")
        if w == "part" and asmsim.is_assembly_study(a) is False:
            draft_entry(a, out)
        if w == "part" and asmsim.is_assembly_study(a) is False:
            shell_entry(a, out)
        if w == "body":
            show_hide([o])
    elif w == "connections":
        key("Connections Advisor...", "SIM_ConnAdvisor")
        key("Contact Set...", "SIM_Contact")
        asmsim.connections_extra(a, key)
        key("Rigid Connection...", "SIM_Rigid")
        show_hide(kids)
    elif w == "fixtures":
        key("Fixtures Advisor...", "SIM_FixAdvisor")
        key("Fixed Geometry...", "SIM_Fixed")
        key("Roller/Slider...", "SIM_Roller")
        key("Fixed Hinge...", "SIM_Hinge")
        key("Elastic Support...", "SIM_Elastic")
        show_hide(kids)
    elif w == "loads":
        key("External Loads Advisor...", "SIM_LoadAdvisor")
        key("Force...", "SIM_Force")
        key("Torque...", "SIM_Torque")
        key("Pressure...", "SIM_Pressure")
        key("Gravity...", "SIM_Gravity")
        key("Centrifugal...", "SIM_Centrifugal")
        key("Bearing Load...", "SIM_Bearing")
        key("Temperature...", "SIM_Temperature", study_type=True)      # only where the study takes it
        out.append(("-", None))
        key("Remote Load/Mass...", "SIM_RemoteLoad")
        key("Distributed Mass...", "SIM_DistributedMass")
        out.append(("-", None))
        show_hide(kids)
    elif w == "thermal":
        key("Temperature...", "SIM_Temperature")
        key("Convection...", "SIM_HeatFlux")
        key("Heat Flux...", "SIM_HeatFlux")
        key("Heat Power...", "SIM_BodyHeat")
        key("Initial Temperature...", "SIM_InitialTemp")
        show_hide(kids)
    elif w in ("mesh", "flowmesh"):
        key("Create Mesh...", "SIM_Mesh")
        if o is not None and w == "mesh" and has_key("SIM_Run") and hasattr(o, "FemMesh"):
            out.append(("Mesh and Run", lambda: mesh_and_run(a, o)))
        key("Apply Mesh Control..." if w == "mesh" else "Insert Local Mesh...", "SIM_MeshControl")
        if o is not None and w == "mesh" and getattr(getattr(o, "FemMesh", None), "NodeCount", 0):
            key("Create Mesh Quality Plot...", "SIM_MeshQuality")     # PM pkg358 (only once the key exists)
        if o is not None:
            vis = getattr(o.ViewObject, "Visibility", False)
            out.append(("Hide Mesh" if vis else "Show Mesh", lambda: set_shown([o], not vis)))
            try:
                from . import simmeshinfo
                out.append(("Details...", lambda: simmeshinfo.show(o, a)))
            except ImportError:
                key("Details...", "SIM_MeshInfo", o)
            key("Delete Mesh", "SIM_MeshClear", o)
    elif w == "meshobj":
        out.append(("Edit Definition...", lambda: edit(o)))
    elif w == "results":
        from . import simplots
        if simplots.result(a) is not None and kind(a) in ("static", "check"):

            # lists, Compare Results, Save All Plots; Delete All Results is FreeCAD's, kept last
            from . import simresults
            key("Results Advisor...", "SIM_ResAdvisor")
            out.append(("Solver Messages...", lambda: simresults.solver_messages(a)))
            out.append(("-", None))
            out.append(("Define Factor Of Safety Plot...", lambda: _define(a, "Factor of Safety")))
            for q in ("Stress", "Displacement", "Strain"):
                out.append(("Define %s Plot..." % q, lambda q=q: _define(a, q)))
            out.append(("-", None))
            out.append(("List Stress, Displacement, Strain...", lambda: simresults.list_results(a)))
            try:                               # List Result Force... (view thread's simforce, when it is there)
                from . import simforce
                out.extend(simforce.results_menu(a) or [])
            except ImportError:
                pass
            except Exception as _fw_err:
                _fw_log("simtree.py:simforce", _fw_err)
            try:
                from . import asmsim
                if hasattr(asmsim, "list_forces") and any(asmsim.forces_of(c) for c in asmsim.connectors(a)):
                    out.append(("List Pin/Bolt/Bearing Force...", lambda: asmsim.list_forces(a)))
            except Exception as _fw_err:
                _fw_log("simtree.py:connforces", _fw_err)
            out.append(("-", None))
            compare(row.plot if w == "plot" else None)
            out.append(("-", None))
            out.append(("Save All Plots as JPEG Files", lambda: simresults.save_all(a)))
            out.append(("-", None))
            key("Delete All Results", "SIM_Purge", None)
        elif kids:
            key("Delete All Results", "SIM_Purge", None)
    elif w == "reports":
        key("Report...", "SIM_Report")
    elif w == "report":
        from . import simreport
        out.append(("Open", lambda: simreport.open_report(row.tip)))
        out.append(("Publish", lambda: simreport.publish(a)))
        out.append(("-", None))
        out.append(("Delete", lambda: (simreport.forget(a, row.tip), QtCore.QTimer.singleShot(0, refresh))))
    elif w == "plot":

        from . import simplots
        on = simplots.SHOWN.get("a") is a and simplots.SHOWN.get("name") == row.plot
        if on:
            out.append(("Hide", lambda: _hide_plot()))
        else:
            out.append(("Show", lambda: show_plot(a, row.plot)))
        out.append(("-", None))
        out.append(("Edit Definition...", lambda: _plot_pm(a, row.plot, "EditDefinitionPM")))
        out.append(("Chart Options...", lambda: _plot_pm(a, row.plot, "ChartOptionsPM")))
        out.append(("Settings...", lambda: _plot_pm(a, row.plot, "SettingsPM")))
        if on:                                  # Animate..., Section Clipping..., Iso Clipping... (view thread's
            try:                                # simplotview, when it is there): [(text, function)]
                from . import simplotview
                out.extend(simplotview.plot_menu(a, row.plot) or [])
            except ImportError:
                pass
            except Exception as _fw_err:
                _fw_log("simtree.py:plotview", _fw_err)
        out.append(("-", None))
        if on:
            out.append(("Probe", lambda: _plot_pm(a, row.plot, "ProbePM")))
            out.append(("List Selected", lambda: _plot_pm(a, row.plot, "ListSelectedPM")))
            p = simplots.get_plot(a, row.plot)
            if p is not None and p["quantity"] not in ("Thermal", "Fatigue", "Factor of Safety"):
                out.append(("Deformed Result", lambda: _toggle_deformed(a, row.plot)))
            compare(row.plot if w == "plot" else None)
            out.append(("-", None))
            from . import simresults
            if simresults.print_support() is not None:
                out.append(("Print...", lambda: simresults.print_view(a)))
            out.append(("Save As...", lambda: simresults.save_as(a, row.plot)))
            out.append(("-", None))
        out.append(("Delete...", lambda: _delete_plot(a, row.plot)))
        if on:
            from . import simresults
            out.append(("Copy", lambda: simresults.copy_view(a)))
    elif w == "fluids":
        fl = [m for m in _materials(a) if is_fluid(m)]
        if fl:
            out.append(("Edit Definition...", lambda: edit(fl[0])))
        else:
            key("Insert Fluid...", "FLOW_Fluid")
    elif w == "solidmats":
        key("Insert Solid Material...", "SIM_ApplyMaterial")
    elif w == "bcs":
        key("Insert Inlet Velocity...", "FLOW_Velocity")
        key("Insert Environment Pressure...", "FLOW_Pressure")
        key("Insert Wall Temperature...", "SIM_Temperature")
        show_hide(kids)
    elif w == "inits":
        key("Insert Initial Velocity...", "FLOW_InitVel")
        key("Insert Initial Pressure...", "FLOW_InitPress")
        key("Insert Initial Temperature...", "SIM_InitialTemp")
    elif w == "heat":
        key("Insert Surface Source...", "SIM_HeatFlux")
        key("Insert Volume Source...", "SIM_BodyHeat")
        show_hide(kids)
    elif w in ("flowresults", "flowplots") or w.startswith("flowplots:"):
        pipes = [x for x in _results(a) if x.isDerivedFrom("Fem::FemPostPipeline")]
        res = [x for x in _results(a) if not x.isDerivedFrom("Fem::FemPostPipeline")]
        if w.startswith("flowplots:") and pipes:
            k = w.split(":", 1)[1]
            key("Insert...", k, pipes[0])
        elif w == "flowplots" and res:
            key("Insert...", "SIM_Plot", res[0])
        elif w == "flowresults" and (res or pipes):
            key("Delete All Results", "SIM_Purge", None)
    elif w == "item" and o is not None:
        if o.isDerivedFrom("Fem::Constraint") or ftype(o).startswith("Fem::Constraint") or "Mesh" in ftype(o) \
                or ftype(o).startswith("Fem::Element") or ftype(o).startswith("Fem::Material") or FREE_SET in o.PropertiesList:
            out.append(("Edit Definition...", lambda: edit(o)))
        if "Suppressed" in o.PropertiesList:
            sup = is_suppressed(o)
            out.append(("Unsuppress" if sup else "Suppress", lambda: set_suppressed(o, not sup)))
        show_hide([o])
        out.append(("-", None))
        out.append(("Delete...", lambda: delete_objects([o])))
    elif w == "result" and o is not None:
        out.append(("Show", lambda: set_shown([o], True)))
        out.append(("Hide", lambda: set_shown([o], False)))
        out.append(("-", None))
        out.append(("Delete", lambda: delete_objects([o])))
    try:                                        # Copy / Paste of fixtures, loads and connectors between studies
        clip_entries(row, a, out)
    except Exception as _fw_err:
        _fw_log("simtree.py:clip", _fw_err)
    try:
        from . import simrcmenus
        out = list(simrcmenus.arrange(w, out, o, a) or out)
    except ImportError:
        pass
    except Exception as _fw_err:
        _fw_log("simtree.py:rcmenus", _fw_err)
    tidy = []
    for t, f in out:                            # no line first, last or twice in a row
        if t == "-" and (not tidy or tidy[-1][0] == "-"):
            continue
        tidy.append((t, f))
    while tidy and tidy[-1][0] == "-":
        tidy.pop()
    return tidy


def _define(a, quantity):
    from . import simplots
    simplots.defaults(a)
    return simplots._open(simplots.EditDefinitionPM(a, None, quantity))


def _plot_pm(a, name, cls):
    from . import simplots
    return simplots._open(getattr(simplots, cls)(a, name))


def _toggle_deformed(a, name):
    """Deformed Result: the plot on its deformed shape, or back on the model as it is."""
    from . import simplots
    p = simplots.get_plot(a, name)
    simplots.update_plot(a, name, deformed=not p.get("deformed"))
    return simplots.show(a, name)


def show_plot(a, name):
    from . import simplots
    return simplots.show(a, name)


def _hide_plot():
    from . import simplots
    simplots.clear()


def _delete_plot(a, name):
    from . import simplots
    if not _ask(DELETE_TEXT % name):
        return False
    if simplots.SHOWN.get("name") == name:
        simplots.clear()
    simplots.delete_plot(a, name)
    return True


def double_click(row, a):
    ""
    if row.what == "plot":
        return show_plot(a, row.plot)
    if row.what == "report":
        from . import simreport
        return simreport.open_report(row.tip)
    if row.what in ("item", "meshobj", "ours", "event") and row.obj is not None:
        return edit(row.obj)
    return None


# =========================================================================== GUI
if Gui is not None:
    Qt = QtCore.Qt

    def icon(key):
        if key.endswith(MESHED):
            return _checked(icon(key[:-len(MESHED)]))
        path = os.path.join(ICONS, key + ".svg")
        return _v2(path) if os.path.isfile(path) else QtGui.QIcon()

    def _checked(base):
        ""
        pm = base.pixmap(32, 32) if not base.isNull() else QtGui.QPixmap(32, 32)
        if base.isNull():
            pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255), 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        path = QtGui.QPainterPath(QtCore.QPointF(15, 23)); path.lineTo(20, 28); path.lineTo(30, 15)
        p.setPen(pen); p.drawPath(path)
        p.setPen(QtGui.QPen(QtGui.QColor(30, 160, 50), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); p.drawPath(path)
        p.end()
        return QtGui.QIcon(pm)

    class StudyTree(QtWidgets.QTreeWidget):
        ""

        def __init__(self, flow=False, parent=None):
            super().__init__(parent)
            self.flow = flow
            self.setObjectName("SWFlowTree" if flow else "SWStudyTree")
            self.setHeaderHidden(True)
            self.setColumnCount(1)
            self.setRootIsDecorated(True)
            self.setContextMenuPolicy(Qt.CustomContextMenu)
            self.setEditTriggers(QtWidgets.QAbstractItemView.EditKeyPressed)
            self.customContextMenuRequested.connect(self._menu)
            self.itemDoubleClicked.connect(self._double)
            self.itemClicked.connect(self._clicked)
            self.itemChanged.connect(self._renamed)
            self.study = None
            self._sig = None
            self._filling = False
            self.rows = {}
            self.last_menu = None
            if not flow:                    # drag a fixture, load or connector onto another study's tab: a copy there
                self.setDragEnabled(True)
                self.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)

        def _current_objs(self):
            row = self.row_of(self.currentItem())
            if row is None or self.study is None:
                return []
            if row.what in COPY_FOLDERS:
                return [c.obj for c in row.rows if c.obj is not None]
            return [row.obj] if row.what == "item" and row.obj is not None else []

        def _clip_key(self, e):
            """"copy" / "paste" when Ctrl+C / Ctrl+V has something to do in this tree, else None."""
            if self.flow or self.study is None or not hasattr(e, "matches"):
                return None
            if e.matches(QtGui.QKeySequence.Copy) and self._current_objs() and \
                    {o.Name for o in self._current_objs()} & {x.Name for x, _f in _copyable(self.study)}:
                return "copy"
            if e.matches(QtGui.QKeySequence.Paste):
                row = self.row_of(self.currentItem())
                folder = row.what if row is not None and row.what in COPY_FOLDERS else None
                if clipboard(self.study.Document, self.study, folder):
                    return "paste"
            return None

        def event(self, e):
            # FreeCAD's Edit > Copy / Paste (Std_Copy: copies to the system clipboard with the export dialog) would

            try:
                if e.type() == QtCore.QEvent.ShortcutOverride and self._clip_key(e):
                    e.accept()
                    return True
            except Exception as _fw_err:
                _fw_log("simtree.py:override", _fw_err)
            return super().event(e)

        def keyPressEvent(self, e):
            """Ctrl+C copies the fixture, load or connector row (or its folder's rows); Ctrl+V pastes in this study."""
            if not self.flow and self.study is not None:
                try:
                    if e.matches(QtGui.QKeySequence.Copy):
                        if copy_items(self.study, self._current_objs()):
                            e.accept()
                            return
                    elif e.matches(QtGui.QKeySequence.Paste):
                        row = self.row_of(self.currentItem())
                        folder = row.what if row is not None and row.what in COPY_FOLDERS else None
                        if clipboard(self.study.Document, self.study, folder):
                            paste(self.study, folder)
                            e.accept()
                            return
                except Exception as _fw_err:
                    _fw_log("simtree.py:keys", _fw_err)
            super().keyPressEvent(e)

        def startDrag(self, actions):
            a = self.study
            items = copy_items(a, self._current_objs()) if a is not None else []
            if not items:
                return
            mime = QtCore.QMimeData()
            mime.setData(MIME, QtCore.QByteArray(("%s\n%s" % (a.Document.Name, " ".join(n for n, _w in items))).encode()))
            drag = QtGui.QDrag(self)
            drag.setMimeData(mime)
            it = self.currentItem()
            if it is not None:
                drag.setPixmap(it.icon(0).pixmap(16, 16))
            drag.exec(QtCore.Qt.CopyAction)

        def fill(self, a, force=False):
            sig = (a.Name, signature(a)) if a is not None else None
            if sig == self._sig and not force:
                return False
            self._sig = sig
            self.study = a
            opened = {self._path(it) for it in self._items() if it.isExpanded()}
            known = {self._path(it) for it in self._items()}
            first = not opened
            self._filling = True
            try:
                self.clear()
                self.rows = {}
                if a is None:
                    return True
                root = flow_rows(a) if self.flow else study_rows(a)
                top = self._add(None, root)
                top.setFlags(top.flags() | Qt.ItemIsEditable)
                for it in self._items():

                    if first or self._path(it) in opened or (known and self._path(it) not in known):
                        it.setExpanded(True)
                f = top.font(0)
                f.setBold(True)
                top.setFont(0, f)
            finally:
                self._filling = False
            return True

        def _add(self, parent, row):
            it = QtWidgets.QTreeWidgetItem([row.text])
            if row.icon:
                it.setIcon(0, icon(row.icon))
            if row.tip:
                it.setToolTip(0, row.tip)
            if parent is None:
                self.addTopLevelItem(it)
            else:
                parent.addChild(it)
            self.rows[id(it)] = (it, row)
            for r in row.rows:
                self._add(it, r)
            return it

        def _items(self):
            out = []
            def walk(it):
                out.append(it)
                for i in range(it.childCount()):
                    walk(it.child(i))
            for i in range(self.topLevelItemCount()):
                walk(self.topLevelItem(i))
            return out

        def _path(self, it):
            parts = []
            while it is not None:
                parts.append(it.text(0) if it.parent() is not None else "")
                it = it.parent()
            return tuple(reversed(parts))

        def row_of(self, it):
            v = self.rows.get(id(it)) if it is not None else None
            return v[1] if v else None

        def find(self, text):
            return next((it for it in self._items() if it.text(0) == text or it.text(0).startswith(text)), None)

        def entries(self, it):
            row = self.row_of(it)
            return menu_entries(row, self.study) if row is not None and self.study is not None else []

        def _menu(self, pos):
            it = self.itemAt(pos)
            items = self.entries(it)
            if not items:
                return
            m = QtWidgets.QMenu(self)
            m.setObjectName("SWStudyTreeMenu")
            for text, fn in items:
                if text == "-":
                    m.addSeparator()
                elif text == "Rename":
                    m.addAction(text).triggered.connect(lambda _=False, i=it: self.editItem(i, 0))
                else:
                    m.addAction(text).triggered.connect(lambda _=False, f=fn: self._run(f))
                if text != "-":
                    try:
                        from . import simrcmenus
                        ic = simrcmenus.icon_for(text)
                        if ic is not None:
                            m.actions()[-1].setIcon(ic)
                    except Exception as _fw_err:
                        _fw_log("simtree.py:menu icon", _fw_err)
            self.last_menu = m
            m.popup(self.viewport().mapToGlobal(pos))

        def _run(self, fn):
            try:
                fn()
            except Exception as error:
                App.Console.PrintError("FreeCAD study tree: %s\n" % error)
            QtCore.QTimer.singleShot(50, refresh)

        def _clicked(self, it, _col):
            row = self.row_of(it)
            if row is not None and row.obj is not None and row.what in ("item", "body", "meshobj", "result", "mesh"):
                _select(row.obj)

        def _double(self, it, _col):
            row = self.row_of(it)
            if row is not None and self.study is not None:
                self._run(lambda: double_click(row, self.study))

        def _renamed(self, it, _col):
            if self._filling:
                return
            row = self.row_of(it)
            if row is not None and row.what in ("study", "flowproject") and self.study is not None:
                text = it.text(0).split(" (-")[0]
                if text.endswith("*") and not self.study.Label.endswith("*"):
                    text = text[:-1]       # look-audit simlook-1120: the not-run mark is not part of the name
                rename(self.study, text)
                QtCore.QTimer.singleShot(0, refresh)

    class StudyPane(QtWidgets.QWidget):
        ""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("SWStudyPane")
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            self.tree = StudyTree(False, self)
            lay.addWidget(self.tree)

    class FlowPage(QtWidgets.QWidget):
        """The Flow Simulation analysis tree manager page: the document's flow projects, the active one open."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setObjectName("SWFlowPage")
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(2)
            self.pick = QtWidgets.QComboBox(self)
            self.pick.setObjectName("SWFlowProject")
            self.pick.activated.connect(self._picked)
            lay.addWidget(self.pick)
            self.tree = StudyTree(True, self)
            lay.addWidget(self.tree, 1)
            self.projects = []

        def fill(self, doc):
            ps = studies(doc, flow=True)
            names = [p.Label for p in ps]
            if names != [self.pick.itemText(i) for i in range(self.pick.count())]:
                self.pick.clear()
                self.pick.addItems(names)
            self.pick.setVisible(len(ps) > 1)
            self.projects = ps
            from . import addintabs
            act = addintabs._active_analysis(doc)
            cur = act if act in ps else (ps[0] if ps else None)
            if cur is not None:
                self.pick.setCurrentIndex(ps.index(cur))
            self.tree.fill(cur)

        def _picked(self, i):
            if 0 <= i < len(self.projects):
                _make_active(self.projects[i])
                self.tree.fill(self.projects[i], force=True)

    PANE = {"study": None}
    FLOW_TAB = (os.path.join(ICONS, "FLOW_Project.svg"), "Flow Simulation analysis tree", "FlowSimulation")

    def left_pane():
        try:
            return Gui.getMainWindow().findChild(QtWidgets.QWidget, "SWLeftPane")
        except Exception:
            return None

    def study_pane():
        """The study tree under the FeatureManager (made on first use), or None without the left pane."""
        lp = left_pane()
        if lp is None or not hasattr(lp, "splitter"):
            return None
        sp = PANE.get("study")
        try:
            if sp is not None and sp.parentWidget() is lp.splitter:
                return sp
        except RuntimeError:
            sp = None
        sp = StudyPane()
        lp.splitter.addWidget(sp)
        sp.hide()
        PANE["study"] = sp
        return sp

    def _show_study(doc):
        a = active_study(doc)
        sp = study_pane() if (a is not None or PANE.get("study") is not None) else None
        if sp is None:
            return None
        if a is None or is_flow(a):
            sp.tree.fill(None)
            if sp.isVisible():
                sp.hide()
            return sp
        sp.tree.fill(a)
        if not sp.isVisible():
            sp.show()
            lp = left_pane()
            total = max(2, lp.splitter.height())
            sizes = lp.splitter.sizes()
            n = len(sizes)
            new = [0] * n
            idx = lp.splitter.indexOf(sp)
            rest = total - total * 45 // 100
            others = [i for i in range(n) if i != idx and lp.splitter.widget(i).isVisible()]
            for i in others:
                new[i] = max(1, rest // max(1, len(others)))
            new[idx] = total - sum(new)
            lp.splitter.setSizes(new)
        return sp

    def _flow_tab(doc):
        lp = left_pane()
        if lp is None or not hasattr(lp, "pages"):
            return None
        from . import leftpane, icons as _icons
        have = bool(studies(doc, flow=True))
        page = lp.pages.get(FLOW_TAB[2])
        if have:
            if page is None:
                page = FlowPage()
                lp._add_page(FLOW_TAB[2], page)
            if FLOW_TAB not in leftpane.TABS:
                leftpane.TABS = tuple(leftpane.TABS) + (FLOW_TAB,)
                lp.header.icons.append(_icons.family(FLOW_TAB[0]))
                lp.header.update()
            page.fill(doc)
            return page
        if FLOW_TAB in leftpane.TABS:
            i = leftpane.TABS.index(FLOW_TAB)
            if lp.current_name() == FLOW_TAB[2]:
                lp.select_name("Model")
            leftpane.TABS = tuple(t for t in leftpane.TABS if t != FLOW_TAB)
            try:
                lp.header.icons.pop(i)
            except Exception as _fw_err:
                _fw_log("simtree.py:flowtab", _fw_err)
            if lp.header.current >= len(leftpane.TABS):
                lp.header.current = 0
            lp.header.update()
        if page is not None:
            lp.pages.pop(FLOW_TAB[2], None)
            try:
                lp.stack.removeWidget(page)
                page.deleteLater()
            except RuntimeError as _fw_err:
                _fw_log("simtree.py:flowpage", _fw_err)
        return None

    def open_flow_tree():
        """The Flow Simulation analysis tree tab, in front."""
        doc = App.ActiveDocument
        page = _flow_tab(doc)
        lp = left_pane()
        if page is not None and lp is not None:
            lp._user_page = FLOW_TAB[2]
            lp.select_name(FLOW_TAB[2])
        return page

    def refresh():
        doc = App.ActiveDocument
        for name in list(ACTIVE):
            if name not in App.listDocuments():
                ACTIVE.pop(name, None)
        try:
            _show_study(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD study tree: %s\n" % error)
        try:
            _flow_tab(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD flow tree: %s\n" % error)

    # ----------------------------------------------------------------- the bottom tabs of a part
    def _part_doc():
        doc = App.ActiveDocument
        if doc is None:
            return None
        try:
            from . import asmcore
            if asmcore.assembly_of(doc) is not None:
                return None
        except Exception as _fw_err:
            _fw_log("simtree.py:asm", _fw_err)
        return doc

    def tab_entries(doc, a):
        ""
        out = []
        if a is not None:
            def ask_rename():
                text, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Rename", "Study name:", text=a.Label)
                if ok and text:
                    rename(a, text)
            out += [("Copy Study", lambda: copy_study(a)), ("Rename", ask_rename), ("Delete", lambda: delete_study(a))]
            out.append(("-", None))
        if has_key("SIM_NewStudy"):
            out.append(("Create New Simulation Study", new_study))
        return out

    def _patch_tabs():
        from . import chrome
        cls = chrome.ModelTabs
        if getattr(cls, "_fw_simtabs", False):
            return
        extras0, open0, activate0, press0 = cls.extras, cls._open_extra, cls._activate, cls.mousePressEvent

        def extras(self):
            out = extras0(self)
            try:
                doc = _part_doc()
                if doc is None or chrome._drawing_in_front():
                    return out
                shown = active_study(doc)
                return out + [(a.Label, "simstudy", a.Name, shown is a) for a in studies(doc)]
            except Exception as _fw_err:
                _fw_log("simtree.py:extras", _fw_err)
                return out

        def _open_extra(self, title, kind_, payload):
            doc = App.ActiveDocument
            if kind_ == "simstudy":
                a = doc.getObject(payload) if doc is not None else None
                if a is not None:
                    activate(doc, a)
                self.refresh()
                return None
            deactivate(doc)
            return open0(self, title, kind_, payload)

        def _activate(self, index):
            subs = self.subwindows()
            model_row = index < (len(subs) or (1 if App.ActiveDocument is not None else 0))
            r = activate0(self, index)
            if model_row and _part_doc() is not None:
                deactivate(App.ActiveDocument)
            return r

        def mousePressEvent(self, e):
            doc = _part_doc()
            if doc is not None and e.button() == Qt.RightButton:
                hit = self._hit(e.position().x())
                if hit and hit[0] == "tab":
                    subs = self.subwindows()
                    n = len(subs) or 1
                    j = hit[1] - n
                    ex = self.extras()
                    a = None
                    if 0 <= j < len(ex) and ex[j][1] == "simstudy":
                        a = doc.getObject(ex[j][2])
                    if a is not None or (hit[1] < n and studies(doc)):
                        items = tab_entries(doc, a)
                        m = QtWidgets.QMenu(self)
                        m.setObjectName("FW_StudyTabMenu")
                        if hit[1] < len(subs):
                            m.addAction("Close").triggered.connect(lambda _=False, sub=subs[hit[1]]: (sub.close(), self.refresh()))
                            m.addSeparator()
                        for text, fn in items:
                            if text == "-":
                                m.addSeparator()
                            else:
                                m.addAction(text).triggered.connect(lambda _=False, f=fn: (f(), self.refresh()))
                        self._fw_menu = m
                        m.popup(e.globalPosition().toPoint())
                        return None
            return press0(self, e)

        def _study_at(self, e):
            doc = _part_doc()
            if doc is None:
                return None
            pos = e.position() if hasattr(e, "position") else e.pos()
            hit = self._hit(pos.x())
            if not hit or hit[0] != "tab":
                return None
            j = hit[1] - (len(self.subwindows()) or 1)
            ex = self.extras()
            if 0 <= j < len(ex) and ex[j][1] == "simstudy":
                return doc.getObject(ex[j][2])
            return None

        def _ours(e):
            return e.mimeData() is not None and e.mimeData().hasFormat(MIME)

        def dragEnterEvent(self, e):
            if _ours(e):
                e.acceptProposedAction()
            else:
                e.ignore()

        def dragMoveEvent(self, e):
            if _ours(e) and self._study_at(e) is not None:
                e.acceptProposedAction()
            else:
                e.ignore()

        def dropEvent(self, e):
            ""
            b = self._study_at(e) if _ours(e) else None
            if b is None:
                e.ignore()
                return
            try:
                text = bytes(e.mimeData().data(MIME)).decode()
                docname, _sep, names = text.partition("\n")
                if docname != b.Document.Name:
                    e.ignore()
                    return
                objs = [b.Document.getObject(n) for n in names.split()]
                have = set(_folder_rows(b))
                fold = dict(CLIP["items"])
                objs = [o for o in objs if o is not None and fold.get(o.Name, "fixtures") in have]
                if objs:
                    paste_items(b, objs)
                    e.acceptProposedAction()
                    self.refresh()
                    return
            except Exception as _fw_err:
                _fw_log("simtree.py:drop", _fw_err)
            e.ignore()

        init0 = cls.__init__

        def __init__(self, *args, **kw):
            init0(self, *args, **kw)
            self.setAcceptDrops(True)

        cls.extras, cls._open_extra, cls._activate, cls.mousePressEvent = extras, _open_extra, _activate, mousePressEvent
        cls._study_at, cls.dragEnterEvent, cls.dragMoveEvent, cls.dropEvent = _study_at, dragEnterEvent, dragMoveEvent, dropEvent
        cls.__init__ = __init__
        try:
            for w in Gui.getMainWindow().findChildren(cls):
                w.setAcceptDrops(True)
        except Exception as _fw_err:
            _fw_log("simtree.py:tabsdrop", _fw_err)
        cls._fw_simtabs = True

    def _patch_asm():
        """An assembly's simulation study tab (asmstudytabs) shows the same study tree."""
        from . import asmstudytabs as st
        if getattr(st, "_fw_simtree", False):
            return
        open0, model0 = st.open_any, st.to_model

        def open_any(asm, study):
            r = open0(asm, study)
            try:
                if is_study(study) and not is_flow(study):
                    activate(asm.Document, study)
                else:
                    deactivate(asm.Document)
            except Exception as _fw_err:
                _fw_log("simtree.py:asmopen", _fw_err)
            return r

        def to_model(asm, keep=False):
            r = model0(asm, keep)
            try:
                deactivate(asm.Document)
            except Exception as _fw_err:
                _fw_log("simtree.py:asmmodel", _fw_err)
            return r

        st.open_any, st.to_model = open_any, to_model
        st._fw_simtree = True

    def _patch_featuretree():
        ""
        from . import fmtree
        cls = fmtree.Model
        if getattr(cls, "_fw_nostudies", False):
            return
        children0 = cls._children

        def _children(self, index):
            out = children0(self, index)
            try:
                if index.isValid() and not index.parent().isValid():          # the part's own rows
                    doc = self.doc or App.ActiveDocument
                    keep = []
                    for c in out:
                        o = fmtree._object(doc, c.data(Qt.DisplayRole))
                        if not is_study(o):
                            keep.append(c)
                    return keep
            except Exception as _fw_err:
                _fw_log("simtree.py:fm", _fw_err)
            return out

        cls._children = _children
        cls._fw_nostudies = True

    _TIMER = []

    def hide_result_pipelines(doc):
        ""


        hidden = []
        for a in [o for o in doc.Objects if is_study(o)]:
            for o in list(getattr(a, "Group", []) or []):
                try:
                    if o.isDerivedFrom("Fem::FemPostObject") and o.ViewObject is not None and o.ViewObject.Visibility:
                        o.ViewObject.Visibility = False
                        hidden.append(o.Name)
                except Exception as _fw_err:
                    _fw_log("simtree.py:hide pipeline", _fw_err)
        return hidden

    SEEN_DOCS = {}

    def _new_docs():
        """Each document once, as it opens (a closed and reopened part counts as new)."""
        names = App.listDocuments()
        for name in list(SEEN_DOCS):
            if name not in names:
                SEEN_DOCS.pop(name, None)
        for name, doc in names.items():
            if SEEN_DOCS.get(name) is doc:
                continue
            SEEN_DOCS[name] = doc
            try:
                hide_result_pipelines(doc)
            except Exception as _fw_err:
                _fw_log("simtree.py:new docs", _fw_err)

    def _tick():
        try:
            _new_docs()
        except Exception as error:
            App.Console.PrintLog("FreeCAD study pipelines: %s\n" % error)
        try:
            refresh()
        except Exception as error:
            App.Console.PrintLog("FreeCAD study tree: %s\n" % error)

    def install():
        for fn in (_patch_tabs, _patch_asm, _patch_featuretree):
            try:
                fn()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: study tree (%s): %s\n" % (fn.__name__, error))
        if _TIMER:
            return
        t = QtCore.QTimer()
        t.setInterval(700)
        t.timeout.connect(_tick)
        t.start()
        try:
            from . import ticks
            ticks.slow_when_idle(t)
        except Exception as _fw_err:
            _fw_log("simtree.py:ticks", _fw_err)
        _TIMER.append(t)
else:
    def install():
        return None


def _v2(path):
    """v2last-1127: the V2 pack's themed picture for one of the add-on's own drawings, else the file itself."""
    from . import icons
    return icons.family(str(path))
