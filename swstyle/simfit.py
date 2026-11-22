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
    from PySide import QtCore
except ImportError:  # pragma: no cover
    Gui = None

SIM_TAB = "Simulation"
HEAT = ("SIM_Convection", "SIM_HeatFlux", "SIM_BodyHeat", "SIM_Radiation", "SIM_InitialTemp", "SIM_ThermalLoads")
MECH_LOADS = ("SIM_Force", "SIM_Torque", "SIM_Pressure", "SIM_Gravity", "SIM_Centrifugal", "SIM_Bearing", "SIM_RemoteLoad",
              "SIM_DistributedMass")
FIXTURES = ("SIM_Fixed", "SIM_Roller", "SIM_Hinge", "SIM_Elastic", "SIM_Rigid")
ASSEMBLY_ONLY = ("SIM_Interaction", "SIM_SpringConnector", "SIM_Pin", "SIM_Bolt", "SIM_BearingConnector", "SIM_RigidConnector")
NOT_FATIGUE = ("SIM_Contact", "SIM_Bonded", "SIM_Shell", "SIM_Beam", "SIM_BeamRotation", "SIM_Diagnostic", "SIM_Mesh",
               "SIM_MeshInfo", "SIM_MeshNetgen", "SIM_MeshControl", "SIM_MeshQuality", "SIM_MeshBoundary", "SIM_MeshClear",
               "SIM_MaterialNonlinear", "SIM_SolverControl") + ASSEMBLY_ONLY
ADVISOR_OF = {"SIM_FixAdvisor": "SIM_Fixed", "SIM_LoadAdvisor": "SIM_Force", "SIM_ConnAdvisor": "SIM_Contact"}
STATE = {"sig": None, "timer": None, "wrapped": False}


def study():
    try:
        from . import simtree
        return simtree._ctx_study()
    except Exception:
        return None


def _kind(a):
    try:
        from . import simtypes
        return simtypes.study_type(a)
    except Exception:
        return "static"


def _is_flow(a):
    try:
        from . import simtree
        return simtree.is_flow(a)
    except Exception:
        return False


def _asm(a):
    try:
        from . import asmsim
        return bool(asmsim.is_assembly_study(a))
    except Exception:
        return False


def _has_mesh(a):
    try:
        from . import simtree
        return any(getattr(m, "FemMesh", None) is not None and m.FemMesh.NodeCount for m in simtree._meshes(a))
    except Exception:
        return True


def _has_result(a):
    try:
        return any(o.isDerivedFrom("Fem::FemResultObject") or o.isDerivedFrom("Fem::FemPostPipeline") for o in a.Group)
    except Exception:
        return True


def fits(key, a=None):
    """False when the active study's type cannot use the Simulation key (it is then not shown)."""
    if not key or not key.startswith("SIM_"):
        return True
    a = a if a is not None else study()
    if a is None or _is_flow(a):
        return key != "SIM_ThermalLoads"
    k = _kind(a)
    if key == "SIM_MeshQuality" and not _has_mesh(a):
        return False                           # a Mesh Quality Plot needs a mesh (no greyed button before)
    if key == "SIM_LoadAdvisor" and k == "lineardynamic":
        from . import simdynamic
        if simdynamic.analysis(a) in simdynamic.BASE:
            return True                        # its flyout holds Uniform Base Excitation there
    key = ADVISOR_OF.get(key, key)             # an Advisor entry shows with its flyout's tools
    if key == "SIM_ThermalLoads":
        return k == "thermomech"
    if key == "SIM_Temperature":
        return k in ("thermomech", "static", "nonlinear")
    if key in HEAT:
        return k == "thermomech"
    if key == "SIM_BaseExcitation":
        from . import simdynamic
        return k == "lineardynamic" and simdynamic.analysis(a) in simdynamic.BASE
    if key in MECH_LOADS:
        if k == "lineardynamic":               # Random Vibration and Response Spectrum run on the base excitation
            from . import simdynamic
            return simdynamic.analysis(a) not in simdynamic.BASE
        return k in ("static", "nonlinear", "topology", "frequency", "buckling", "check")
    if key in FIXTURES:
        return k in ("static", "nonlinear", "topology", "lineardynamic", "frequency", "buckling", "check")
    if key in ASSEMBLY_ONLY and not _asm(a):
        return False
    if key in NOT_FATIGUE and k in ("fatigue", "pressure"):
        return False
    if key in ("SIM_ApplyMaterial", "SIM_Props", "SIM_MaterialNonlinear") and k == "pressure":
        return False                           # a Pressure Vessel Design study takes its studies' part and material
    if key == "SIM_MeshClear":
        return _has_mesh(a)
    if key == "SIM_Purge":                     # Delete Results: once there are results
        return _has_result(a)
    return True


def signature():
    a = study()
    if a is None:
        return None
    return (a.Document.Name, a.Name, _kind(a), _asm(a), _has_mesh(a), _has_result(a))


# --------------------------------------------------------------------------- the ribbon
def _item_keys(w, keys):
    try:
        return [w.binding.cmd.key]
    except Exception:
        return list(keys)


def _on_sim_page(widget):
    w = widget
    while w is not None:
        if getattr(w, "title", None) == SIM_TAB and hasattr(w, "items"):
            return True
        try:
            w = w.parentWidget()
        except Exception:
            return False
    return False


def _wrap():
    """The Simulation page lays out only the buttons that fit; its flyouts list only the entries that fit."""
    if STATE["wrapped"]:
        return
    from . import ribbon, shell
    page_cls = ribbon.RibbonPage
    relayout = page_cls.relayout

    def fitted_relayout(self, width):
        if getattr(self, "title", "") != SIM_TAB:
            return relayout(self, width)
        self.ensure_built()
        keep = list(self.items)
        shown = []
        for w, keys in keep:
            ks = _item_keys(w, keys)
            if not ks or any(fits(k) for k in ks):
                shown.append((w, keys))
            else:
                w.hide()
        # two separators side by side (a whole group hidden) show as one
        tidy = []
        for item in shown:
            if tidy and isinstance(item[0], ribbon.Separator) and isinstance(tidy[-1][0], ribbon.Separator):
                item[0].hide()
                continue
            tidy.append(item)
        self.items = tidy
        try:
            return relayout(self, width)
        finally:
            self.items = keep

    page_cls.relayout = fitted_relayout
    add = shell.Shell._add_binding_action
    build = shell.Shell.build_flyout

    def fitted_action(self, menu, key, on_chosen=None):
        if STATE.get("filter") and not fits(key):
            return None
        return add(self, menu, key, on_chosen)

    def fitted_flyout(self, button):
        STATE["filter"] = _on_sim_page(button)
        try:
            return build(self, button)
        finally:
            STATE["filter"] = False

    shell.Shell._add_binding_action = fitted_action
    shell.Shell.build_flyout = fitted_flyout
    STATE["wrapped"] = True


def _poll():
    try:
        sig = signature()
        if sig == STATE["sig"]:
            return
        STATE["sig"] = sig
        from . import shell
        sh = shell.shell()
        top = sh.topbar if sh is not None else None
        page = top.current_page() if top is not None else None
        if page is not None and page.title == SIM_TAB:
            top._layout_pages()
    except Exception as _fw_err:
        _fw_log("simfit.py:poll", _fw_err)


def install():
    if Gui is None:
        return
    try:
        _wrap()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: the Simulation tab does not follow the study type (%s)\n" % error)
        return
    if STATE["timer"] is None:
        t = QtCore.QTimer()
        t.setInterval(700)
        t.timeout.connect(_poll)
        t.start()
        STATE["timer"] = t
