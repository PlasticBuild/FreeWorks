# SPDX-License-Identifier: LGPL-2.1-or-later
""


















import json
import math
import re

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

_FW_SEEN = set()


def _fw_log(site, err):
    key = (site, type(err).__name__)
    if key in _FW_SEEN:
        return
    _FW_SEEN.add(key)
    App.Console.PrintLog("FreeCAD simulation (%s): %s\n" % (site, err))


TYPE = "FwSimType"            # "fatigue" or "drop" on an analysis (asmstudytabs and asmmotion use FwStudyType)
EVENT = "FwFatigueEvent"
FATIGUE_RESULTS = "FwFatigueResults"
DROP = "FwDrop"
# New Study PM: (group, label, kind, icon)
TYPES = (

    ("General Simulation", "Static", "static", "SIM_Static"),
    ("General Simulation", "Frequency", "frequency", "SIM_Frequency"),
    ("Design Insight", "Topology Study", "topology", "SIM_Topology"),
    ("Design Insight", "Design Study", "design", "SIM_DesignStudy"),
    ("Advanced Simulation", "Thermal", "thermomech", "SIM_Thermal"),
    ("Advanced Simulation", "Buckling", "buckling", "SIM_Buckling"),
    ("Advanced Simulation", "Fatigue", "fatigue", "SIM_Fatigue"),
    ("Advanced Simulation", "Nonlinear", "nonlinear", "SIM_Nonlinear"),
    ("Advanced Simulation", "Linear Dynamic", "lineardynamic", "SIM_LinearDynamic"),
    ("Specialized Simulation", "Drop Test", "drop", "SIM_DropTest"),
    ("Specialized Simulation", "Pressure Vessel Design", "pressure", "SIM_PressureVessel"),
)
LABELS = {k: label for _g, label, k, _i in TYPES}
GROUPS = ("General Simulation", "Design Insight", "Advanced Simulation", "Specialized Simulation")
# the Study PM's Message: what each type finds (FreeCAD's own words)
MESSAGES = {"static": "Stresses, displacements and the factor of safety under loads that do not change.",
            "frequency": "The natural frequencies of the part and their mode shapes.",
            "topology": "Where material can go: the stiffest shape that keeps the mass you ask for.",
            "design": "Variables and constraints swept over a set of runs.",
            "thermomech": "Temperatures and heat flow, steady state or over time.",
            "buckling": "The load factor at which a slender part buckles, and its shape.",
            "fatigue": "Damage and life after many load cycles, from static studies.",
            "nonlinear": "Large displacements and yielding, in time steps.",
            "lineardynamic": "The response to loads that vary in time or frequency, from the part's modes.",
            "drop": "Stresses in the part just after it hits a floor.",
            "pressure": "Load cases from static studies combined by factors (or as the square root of the sum of "
                        "squares), and stresses split into membrane, bending and peak, as pressure vessel codes ask."}

ULTIMATE = {"Plain Carbon Steel": 399.8, "AISI 304 Stainless": 517.0, "6061-T6 Aluminium": 310.0, "Brass": 478.6,
            "ABS": 30.0, "PLA": 50.0, "Nylon 6/6": 82.7}
ALTERNATING = ("Stress intensity (P1-P3)", "Equivalent stress (von Mises)", "Maximum absolute principal (P1)")
MEAN_CORRECTION = ("None", "Goodman", "Gerber", "Soderberg")
LOADING = ("Fully Reversed (LR=-1)", "Zero Based (LR=0)", "Loading Ratio")

NL = "FwNonlinear"
SOFT_TYPES = ("static", "check", None, "", "frequency", "buckling")
INERTIAL = "FwInertialRelief"  # Static "Use inertial relief": the part, unheld, balanced by its own inertia
SOFT = "FwSoftSpring"        # Static / Frequency "Use soft spring to stabilize the model": weak springs to ground
INPLANE = "FwInplane"          # a Frequency study's "Use inplane effect": its loads stiffen or soften the part
NL_MODELS = ("Linear Elastic Isotropic", "Plasticity - von Mises")
NL_HARDENING = ("Isotropic", "Kinematic")
NL_DEFAULTS = {"large": True, "end": 1.0, "increment": 0.05, "model": NL_MODELS[0], "tangent": 0.0,
               "hardening": NL_HARDENING[0], "curve": False}
CURVE = "Stress-Strain curve"            # the Material dialog's Tables & Curves name


# =========================================================================== study types
def study_type(a):
    t = getattr(a, TYPE, "") if a is not None else ""
    if t:
        return t
    from . import simstudy
    return simstudy._kind_of0(a) if hasattr(simstudy, "_kind_of0") else simstudy._kind_of(a)


def _set(o, name, value, kind="App::PropertyString", tip=""):
    if name not in o.PropertiesList:
        o.addProperty(kind, name, "FreeCAD", tip)
        o.setPropertyStatus(name, "Hidden")
    setattr(o, name, value)


def _next_label(doc, base):
    used = {o.Label for o in doc.Objects}
    n = 1
    while "%s %d" % (base, n) in used:
        n += 1
    return "%s %d" % (base, n)


def new_typed_study(doc, kind, name=None, obj=None, analysis=None):
    ""

    from . import addintabs
    name = name or _next_label(doc, LABELS.get(kind, "Static"))
    asm = _assembly(doc)
    if kind == "design":
        _open_design(doc, asm)
        return None
    if kind == "topology":                     # simtopology: a static study with Goals and Constraints
        from . import simtopology
        a = simtopology.new_study(doc, name, obj)
        doc.recompute()
        return a
    if kind == "lineardynamic":                # simdynamic: a static setup solved over its modes
        from . import simdynamic
        a = simdynamic.new_study(doc, name if name != _next_label(doc, LABELS[kind]) else None, analysis, obj)
        doc.recompute()
        return a
    if kind == "pressure":                     # simpressure: combines static studies, no part setup of its own
        from . import simpressure
        a = simpressure.new_study(doc, name)
        doc.recompute()
        return a
    if kind == "fatigue":
        import ObjectsFem
        a = ObjectsFem.makeAnalysis(doc, "Study")
        a.Label = name
        _set(a, TYPE, "fatigue")
        for p, v in (("FwAlternating", ALTERNATING[1]), ("FwMeanCorrection", "None")):
            _set(a, p, v)
        _set(a, "FwKf", 1.0, "App::PropertyFloat")
        _set(a, "FwInfiniteLife", 1e6, "App::PropertyFloat")
        doc.recompute()
        return a
    solver_kind = "static" if kind == "drop" else kind
    if asm is not None:
        from . import asmsim
        a = asmsim.new_study(asm, solver_kind, name)
    else:
        obj = obj or addintabs._main_solid(doc)
        if obj is None:
            raise ValueError("The document has no solid body to study.")
        a = addintabs.new_study(doc, obj, solver_kind, name)
    if kind == "drop":
        _set(a, TYPE, "drop")
        _set(a, DROP, json.dumps(dict(DROP_DEFAULTS)))
    if kind == "nonlinear":
        _set(a, TYPE, "nonlinear")
        _set(a, NL, json.dumps(dict(NL_DEFAULTS)))
        apply_nonlinear(a)
    doc.recompute()
    return a


def is_nonlinear(a):
    return getattr(a, TYPE, "") == "nonlinear" if a is not None else False


def nonlinear_values(a):
    v = dict(NL_DEFAULTS)
    try:
        v.update(json.loads(getattr(a, NL, "") or "{}"))
    except ValueError:
        pass
    return v


def yield_points(sy, e, et):
    ""

    if et <= 0:
        return ["%.6g, 0.0" % sy]
    h = e * et / (e - et)                      # the plastic hardening modulus of a bilinear curve
    return ["%.6g, 0.0" % sy, "%.6g, 1.0" % (sy + h)]


def stress_strain(a):
    """The study material's Stress-Strain curve from the Material dialog: [(strain, stress N/m^2), ...] (at least two
    points), else []."""
    try:
        from . import simmaterial
        pts = simmaterial.curves_of(a).get(CURVE) or []
        pts = [(float(x), float(y)) for x, y in pts if x is not None and y is not None]
        return pts if len(pts) >= 2 else []
    except Exception as _fw_err:
        _fw_log("simtypes.py:stress_strain", _fw_err)
        return []


def curve_points(points, e):
    ""


    from . import simpms
    pts = sorted((x, y / 1e6) for x, y in points)
    if pts[0][0] <= 0:                        # a curve typed from the origin: its yield is the first bend
        pts = pts[1:]
    if len(pts) < 1 or pts[0][1] <= 0:
        raise simpms.SetupError("The Stress-Strain curve needs points above zero strain and stress.")
    base = pts[0][0] - pts[0][1] / e
    out, last = [], -1.0
    for x, y in pts:
        ep = max(0.0, x - y / e - base)
        if out and (ep <= last or y < float(out[-1].split(",")[0])):
            continue                          # CalculiX takes only rising stress at rising plastic strain
        out.append("%.6g, %.6g" % (y, ep))
        last = ep
    out[0] = "%s, 0.0" % out[0].split(",")[0]
    return out


def apply_nonlinear(a):
    """The study's options onto its CalculiX solver (large displacement, time and increments) and its material
    (Plasticity - von Mises: a nonlinear material on the study's material)."""
    import ObjectsFem
    from . import addintabs, simpms, simtree
    v = nonlinear_values(a)
    s = addintabs._solver(a)
    if s is None:
        raise simpms.SetupError("The study has no solver.")
    end, inc = float(v["end"]), float(v["increment"])
    if end <= 0 or inc <= 0 or inc > end:
        raise simpms.SetupError("The time increment must be above 0 and no more than the end time.")
    s.GeometricalNonlinearity = "nonlinear" if v["large"] else "linear"
    plastic = v["model"] == NL_MODELS[1]
    s.MaterialNonlinearity = "nonlinear" if plastic else "linear"
    for name, val in (("TimePeriod", end), ("TimeInitialIncrement", inc), ("TimeMaximumIncrement", inc),
                      ("TimeMinimumIncrement", inc / 1000.0)):
        if name in s.PropertiesList:
            setattr(s, name, "%r s" % val)
    if "IncrementsMaximum" in s.PropertiesList:
        s.IncrementsMaximum = max(100, int(round(end / inc)) * 20)
    if "OutputFrequency" in s.PropertiesList:
        s.OutputFrequency = 1
    nl_type = "Fem::MaterialMechanicalNonlinear"
    nls = [o for o in a.Group if getattr(getattr(o, "Proxy", None), "Type", "") == nl_type]
    if not plastic:
        for o in nls:
            a.removeObject(o)
            a.Document.removeObject(o.Name)
        a.Document.recompute()
        return
    base = next((m for m in simtree._materials(a) if getattr(getattr(m, "Proxy", None), "Type", "") != nl_type), None)
    if base is None:
        raise simpms.SetupError("Apply a material first: Plasticity - von Mises builds on it.")
    card = getattr(base, "Material", {}) or {}
    sy = _yield_mpa(card)
    e = _q(card, "YoungsModulus", "MPa", 0.0)
    if not sy or not e:
        raise simpms.SetupError("%s has no yield strength or elastic modulus: Plasticity - von Mises needs both."
                                % card.get("Name", "The material"))
    et = float(v.get("tangent") or 0.0)
    if et >= e:
        raise simpms.SetupError("The tangent modulus must be below the elastic modulus (%.6g MPa)." % e)
    nl = nls[0] if nls else ObjectsFem.makeMaterialMechanicalNonlinear(a.Document, base, "Plasticity")
    for extra in nls[1:]:
        a.removeObject(extra)
        a.Document.removeObject(extra.Name)
    if nl not in a.Group:
        a.addObject(nl)
    nl.LinearBaseMaterial = base
    nl.MaterialModelNonlinearity = "isotropic hardening" if v["hardening"] == NL_HARDENING[0] else "kinematic hardening"
    curve = stress_strain(a) if v.get("curve") else []
    if v.get("curve") and not curve:
        raise simpms.SetupError("%s has no Stress-Strain curve: add it in the Material dialog (Tables & Curves)."
                                % card.get("Name", "The material"))
    nl.YieldPoints = curve_points(curve, e) if curve else yield_points(sy, e, et)
    nl.Label = "Plasticity - von Mises"
    if getattr(nl, "ViewObject", None) is not None:
        nl.ViewObject.Visibility = False
    a.Document.recompute()



def _assembly(doc):
    for o in doc.Objects if doc is not None else []:
        if o.TypeId.startswith("Assembly::AssemblyObject") or getattr(o, "SWStyleKind", "") == "Assembly":
            return o
    try:
        from . import asmcore
        return asmcore.assembly_of(doc) if hasattr(asmcore, "assembly_of") else None
    except Exception:
        return None


def _open_design(doc, asm):
    if asm is not None:
        from . import asmstudytabs
        return asmstudytabs.create_design(asm)
    from . import designstudy
    return designstudy.design_study()


# =========================================================================== Frequency and Buckling
def _results(a):
    return [o for o in a.Group if o.isDerivedFrom("Fem::FemResultObject")]


def _dat(a):
    for o in reversed(a.Group):
        text = getattr(o, "Text", None)
        if isinstance(text, str) and ("S T E P" in text or "E I G E N" in text or "B U C K" in text):
            return text
    return ""


def modes(a):
    """[(mode, result, value)]: Frequency -> natural frequency (Hz); Buckling -> load factor."""
    k = study_type(a)
    out = []
    if k == "frequency":
        for r in _results(a):
            n = int(getattr(r, "Eigenmode", 0) or 0)
            if n > 0:
                out.append((n, r, float(getattr(r, "EigenmodeFrequency", 0.0) or 0.0)))
    elif k == "buckling":
        from . import addintabs
        factors = addintabs.buckling_factors(a)
        # CalculiX's first result is the static step under the loads (factor 0), then one per mode, its factor in the
        # label (CCX_BucklingFactor_43_04_Results: 43.04)
        res = [r for r in _results(a) if not re.search(r"BucklingFactor_0_Results", r.Label)]
        for n, r in enumerate(res, 1):
            f = factors[n - 1] if n <= len(factors) else None
            if f is None:
                m = re.search(r"BucklingFactor_(-?\d+)_(\d+)_Results", r.Label)
                f = float("%s.%s" % m.groups()) if m else 0.0
            out.append((n, r, f))
    return sorted(out, key=lambda t: t[0])


def frequencies(a):
    """List Resonant Frequencies: [(mode, rad/s, Hz, period s)], from CalculiX's eigenvalue output (else the results)."""
    text = _dat(a)
    rows = []
    if "E I G E N V A L U E   O U T P U T" in text:
        block = text.split("E I G E N V A L U E   O U T P U T", 1)[1].split("P A R T I C I P", 1)[0]
        for m in re.finditer(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$", block, re.M):
            rad, hz = float(m.group(3)), float(m.group(4))
            rows.append((int(m.group(1)), rad, hz, 1.0 / hz if hz else 0.0))
    if not rows:
        for n, _r, hz in modes(a):
            rows.append((n, 2 * math.pi * hz, hz, 1.0 / hz if hz else 0.0))
    have = {r[0] for r in rows}
    for n in rigid_modes(a, text):
        if n not in have:
            rows.append((n, 0.0, 0.0, 0.0))
    return sorted(rows)


def rigid_modes(a, text=None):
    """Mode numbers CalculiX solved but left out of its eigenvalue output and results (a free or partly free part's
    rigid-body modes, eigenvalue at or below zero): those in its participation factors with no eigenvalue line."""
    text = _dat(a) if text is None else text
    if "E I G E N V A L U E   O U T P U T" not in text or "P A R T I C I P" not in text:
        return []
    head, tail = text.split("E I G E N V A L U E   O U T P U T", 1)[1].split("P A R T I C I P", 1)
    listed = {int(m.group(1)) for m in re.finditer(r"^\s*(\d+)\s+\S+\s+\S+\s+\S+\s+\S+\s*$", head, re.M)}
    tail = tail.split("E F F E C T I V E", 1)[0]
    parts = [int(m.group(1)) for m in re.finditer(r"^\s*(\d+)(?:\s+[-+]?\d\S*){6}\s*$", tail, re.M)]
    # rigid-body modes come first (eigenvalue 0): a mode missing above the listed ones is above the Upper bound
    # frequency, not a rigid-body mode (those read as fake 0 Hz rows)
    low = min(listed) if listed else None
    return [n for n in parts if n not in listed and (low is None or n < low)]


def mass_participation(a):
    ""

    text = _dat(a)
    if "E F F E C T I V E   M O D A L   M A S S" not in text or "T O T A L   E F F E C T I V E   M A S S" not in text:
        return []
    eff = text.split("E F F E C T I V E   M O D A L   M A S S", 1)[1].split("T O T A L   E F F E C T I V E", 1)[0]
    tot = text.split("T O T A L   E F F E C T I V E   M A S S", 1)[1].split("F R A C T I O N", 1)[0]
    total = [float(v) for v in re.findall(r"[-+]?\d\.\d+E[-+]\d+", tot)[:3]]
    if len(total) < 3:
        return []
    hz = {n: f for n, _rad, f, _p in frequencies(a)}
    rows = []
    for m in re.finditer(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)", eff, re.M):
        n = int(m.group(1))
        vals = [float(m.group(i)) for i in (2, 3, 4)]
        rows.append((n, hz.get(n, 0.0)) + tuple(v / t if t else 0.0 for v, t in zip(vals, total)))
    return rows


def thermal_steps(a):
    """[(step, result, time s)] of a thermal study's results, in time order."""
    out = []
    for r in _results(a):
        t = getattr(r, "Time", None)
        try:
            t = float(getattr(t, "Value", t) or 0.0)
        except Exception:
            t = 0.0
        if not t:            # a mechanical step's time is only in its name: CCX_Time_0_05_Results (0.05, to 0.01)
            m = re.search(r"Time_(\d+)(?:_(\d+))?_Results", r.Label or r.Name or "")
            if m:
                t = float("%s.%s" % (m.group(1), m.group(2) or "0"))
        out.append((t, r))
    if is_drop(a):
        try:
            times = json.loads(getattr(a, "FwDropTimes", "") or "[]")
        except ValueError:
            times = []
        if len(times) == len(out):
            out = [(t, r) for t, (_t0, r) in zip(times, out)]
    out.sort(key=lambda tr: tr[0])
    return [(i, r, t) for i, (t, r) in enumerate(out, 1)]


def drop_steps(a):
    return thermal_steps(a)


def steps(a, quantity):
    """[(number, words)] the plot PM offers: mode shapes, or the saved time steps (more than one)."""
    k = study_type(a)
    if quantity == "Amplitude":
        if k == "frequency":
            return [(n, "Value = %.5g Hz" % v) for n, _r, v in modes(a)]
        return [(n, "Load Factor = %.5g" % v) for n, _r, v in modes(a)]
    if k == "lineardynamic":
        from . import simdynamic
        return [(n, simdynamic.step_words(a, v)) for n, _r, v in simdynamic.steps(a)]
    if k in ("thermomech", "drop", "nonlinear"):
        st = thermal_steps(a)
        if len(st) > 1:
            return [(n, "Time = %.4g s" % t) for n, _r, t in st]
    return []


def result_of(a, p):
    """The result object of plot p: its mode shape, or its time step (the last when none is set)."""
    k = study_type(a)
    if p.get("quantity") == "Amplitude":
        want = int(p.get("mode") or 1)
        for n, r, _v in modes(a):
            if n == want:
                return r
        ms = modes(a)
        return ms[0][1] if ms else None
    if k == "lineardynamic":
        from . import simdynamic
        st = simdynamic.steps(a)
        if st:
            want = int(p.get("step") or simdynamic.peak_step(a))
            return st[min(max(want, 1), len(st)) - 1][1]
    if k in ("thermomech", "drop", "nonlinear"):
        st = thermal_steps(a)
        if st:
            want = int(p.get("step") or len(st))
            return st[min(max(want, 1), len(st)) - 1][1]
    return None


def title_lines(a, p):
    k = study_type(a)
    if p.get("quantity") == "Amplitude":
        want = int(p.get("mode") or 1)
        for n, _r, v in modes(a):
            if n == want:
                if k == "frequency":
                    return ["Mode Shape : %d  Value = %.5g Hz" % (n, v)]
                return ["Mode Shape : %d  Load Factor = %.5g" % (n, v)]
    if k == "lineardynamic":
        from . import simdynamic
        st = simdynamic.steps(a)
        if st:
            want = min(max(int(p.get("step") or simdynamic.peak_step(a)), 1), len(st))
            v = st[want - 1][2]
            if simdynamic.analysis(a) in simdynamic.BASE:
                return ["%s, base excitation along %s" % (simdynamic.step_words(a, v), simdynamic.values(a)["direction"])]
            if simdynamic.analysis(a) == "Harmonic":
                return ["Plot step: %d  frequency: %.5g Hz" % (want, v)]
            return ["Plot step: %d  time: %.4g Sec" % (want, v)]
    if k in ("thermomech", "drop", "nonlinear"):
        st = thermal_steps(a)
        if len(st) > 1:
            want = int(p.get("step") or len(st))
            want = min(max(want, 1), len(st))
            return ["Plot step: %d  time: %.4g Sec" % (want, st[want - 1][2])]
    return []


# =========================================================================== Fatigue
def is_fatigue(a):
    return getattr(a, TYPE, "") == "fatigue"


def events(a):
    return [o for o in a.Group if EVENT in o.PropertiesList]


def event_values(o):
    try:
        return json.loads(getattr(o, EVENT, "") or "{}")
    except ValueError:
        return {}


def add_event(a, cycles=1000, loading=LOADING[0], ratio=-1.0, study=None, scale=1.0, edit=None):
    """Add Event: the cycles, the loading type and the static study whose stresses it repeats (times the scale)."""
    from . import simpms
    if study is None or getattr(study, "TypeId", "") != "Fem::FemAnalysis" or study_type(study) != "static":
        raise simpms.SetupError("Pick a static study for the event.")
    if int(cycles) < 1:
        raise simpms.SetupError("An event needs at least one cycle.")
    if loading not in LOADING:
        raise simpms.SetupError("Unknown loading type %r." % loading)
    doc = a.Document
    o = edit
    if o is None:
        o = doc.addObject("App::FeaturePython", "Event")
        o.addProperty("App::PropertyString", EVENT, "FreeCAD", "Fatigue event")
        o.addProperty("App::PropertyBool", "Suppressed", "FreeCAD", "Left out of the run")
        a.addObject(o)
        used = {e.Label for e in events(a)}
        n = 1
        while "Event-%d" % n in used:
            n += 1
        o.Label = "Event-%d" % n
        try:
            o.ViewObject.ShowInTree = False
        except Exception as _fw_err:
            _fw_log("simtypes.py:event", _fw_err)
    if loading == LOADING[0]:
        ratio = -1.0
    elif loading == LOADING[1]:
        ratio = 0.0
    setattr(o, EVENT, json.dumps({"cycles": int(cycles), "loading": loading, "ratio": float(ratio), "study": study.Name,
                                  "scale": float(scale)}))
    _clear_fatigue(a)
    doc.recompute()
    return o


def event_text(o):
    v = event_values(o)
    return "%s (-%s-)" % (o.Label, "LR: %g, %d cycles" % (v.get("ratio", -1.0), v.get("cycles", 0)))


def _clear_fatigue(a):
    if FATIGUE_RESULTS in a.PropertiesList:
        setattr(a, FATIGUE_RESULTS, "")


def _event_study(a, o):
    return a.Document.getObject(event_values(o).get("study", "")) if o is not None else None


def fatigue_base(a):
    """The result a fatigue study draws on: the first event's static study's (same mesh)."""
    from . import simplots
    if not getattr(a, FATIGUE_RESULTS, ""):
        return None
    for o in events(a):
        st = _event_study(a, o)
        if st is not None:
            res = [r for r in st.Group if r.isDerivedFrom("Fem::FemResultObject")]
            if res:
                return res[-1]
    return None


def ultimate_mpa(mat):
    ""
    if isinstance(mat, dict):
        for key in ("UltimateTensileStrength", "TensileStrength"):
            if mat.get(key):
                try:
                    return App.Units.Quantity(mat[key]).getValueAs("MPa").Value
                except Exception as _fw_err:
                    _fw_log("simtypes.py:su", _fw_err)
        if mat.get("Name") in ULTIMATE:
            return ULTIMATE[mat["Name"]]
    return None


def _yield_mpa(mat):
    if isinstance(mat, dict):
        if mat.get("YieldStrength"):
            try:
                return App.Units.Quantity(mat["YieldStrength"]).getValueAs("MPa").Value
            except Exception as _fw_err:
                _fw_log("simtypes.py:sy", _fw_err)
        try:
            from . import evaltools
            return float(evaltools.MATERIALS[mat.get("Name")][1])
        except Exception:
            return None
    return None


def estimated_curve(su, ferrous=True):
    """An S-N curve from the ultimate strength (MPa): 0.9 Su at 1e3 cycles; a steel's endurance limit 0.5 Su (at most
    700 MPa) at 1e6 cycles; other materials 0.35 Su at 1e7 cycles (no endurance limit)."""
    if ferrous:
        return [[1e3, 0.9 * su], [1e6, min(0.5 * su, 700.0)]]
    return [[1e3, 0.9 * su], [1e7, 0.35 * su]]


def sn_curve(a, study=None):
    """The fatigue study's S-N curve: {"source", "points" [[N, S MPa], ...], "su", "sy", "material"}."""
    try:
        data = json.loads(getattr(a, "FwSNCurve", "") or "{}")
    except ValueError:
        data = {}
    mat = None
    for st in ([study] if study is not None else []) + [_event_study(a, o) for o in events(a)]:
        if st is None:
            continue
        for o in st.Group:
            if isinstance(getattr(o, "Material", None), dict) and o.Material:
                mat = o.Material
                break
        if mat:
            break
    su = ultimate_mpa(mat) if mat else None
    if data.get("points") and data.get("source") == "Tabulated":
        data.setdefault("su", su)
        data.setdefault("sy", _yield_mpa(mat) if mat else None)
        return data
    name = (mat or {}).get("Name", "")
    ferrous = "Steel" in name or "AISI" in name or "Iron" in name or "steel" in name
    return {"source": "Estimated", "points": estimated_curve(su, ferrous) if su else [], "su": su,
            "sy": _yield_mpa(mat) if mat else None, "material": name}


def set_sn_curve(a, source="Estimated", points=None):
    from . import simpms
    if source == "Tabulated":
        pts = sorted([float(n), float(s)] for n, s in (points or []))
        if len(pts) < 2 or any(n <= 0 or s <= 0 for n, s in pts):
            raise simpms.SetupError("An S-N curve needs at least two points with cycles and stress above 0.")
        _set(a, "FwSNCurve", json.dumps({"source": "Tabulated", "points": pts}))
    else:
        _set(a, "FwSNCurve", json.dumps({"source": "Estimated"}))
    _clear_fatigue(a)


def cycles_at(points, s, infinite):
    """Cycles to failure at alternating stress s (MPa) on a log-log S-N curve; below the last point: infinite life."""
    pts = sorted(points)
    if s <= 0:
        return infinite
    if s >= pts[0][1]:
        (n1, s1), (n2, s2) = pts[0], pts[1]
    elif s <= pts[-1][1]:
        return infinite
    else:
        for (n1, s1), (n2, s2) in zip(pts, pts[1:]):
            if s2 <= s <= s1:
                break
    if s1 == s2:
        return n2
    b = (math.log10(n2) - math.log10(n1)) / (math.log10(s2) - math.log10(s1))
    return min(infinite, max(1.0, 10 ** (math.log10(n1) + b * (math.log10(s) - math.log10(s1)))))


def _alternating(res, how):
    from . import simplots
    if how == ALTERNATING[0]:
        p1, p3 = simplots._list(res, "PrincipalMax"), simplots._list(res, "PrincipalMin")
        vals = [x - y for x, y in zip(p1, p3)]
    elif how == ALTERNATING[2]:
        p1, p3 = simplots._list(res, "PrincipalMax"), simplots._list(res, "PrincipalMin")
        vals = [x if abs(x) >= abs(y) else y for x, y in zip(p1, p3)]
    else:
        vals = simplots._list(res, "vonMises")
    return dict(zip(list(res.NodeNumbers), vals))


def _equivalent(sa, sm, how, su, sy):
    """The fully reversed stress amplitude equal to (sa, sm) with the mean stress correction."""
    if how == "Goodman" and su:
        return sa / max(1e-9, 1.0 - sm / su) if sm < su else float("inf")
    if how == "Gerber" and su:
        return sa / max(1e-9, 1.0 - (sm / su) ** 2) if abs(sm) < su else float("inf")
    if how == "Soderberg" and sy:
        return sa / max(1e-9, 1.0 - sm / sy) if sm < sy else float("inf")
    return sa


def run_fatigue(a):
    """Runs the events' static studies when they have no result, then Miner's rule at every node: Damage (% of life
    used), Life (cycles: total event cycles over the damage) and Load factor (what the loads may be multiplied by
    before the damage reaches 100 %)."""
    from . import addintabs, simpms, simplots
    evs = [o for o in events(a) if not getattr(o, "Suppressed", False)]
    if not evs:
        raise simpms.SetupError("Add an event first (right-click Loading, Add Event).")
    stress = []
    for o in evs:
        st = _event_study(a, o)
        if st is None:
            raise simpms.SetupError("%s: its study is gone." % o.Label)
        if simplots.result(st) is None:
            addintabs.run_study(st)
        res = simplots.result(st)
        if res is None:
            raise simpms.SetupError("%s: %s has no result." % (o.Label, st.Label))
        stress.append((event_values(o), _alternating(res, getattr(a, "FwAlternating", ALTERNATING[1]))))
    curve = sn_curve(a, _event_study(a, evs[0]))
    if len(curve.get("points", [])) < 2:
        raise simpms.SetupError("The material has no ultimate strength for its S-N curve: give the curve in "
                                "Apply/Edit Fatigue Data.")
    nodes = sorted(set.intersection(*[set(s) for _v, s in stress]))
    how = getattr(a, "FwMeanCorrection", "None")
    kf = float(getattr(a, "FwKf", 1.0) or 1.0)
    inf = float(getattr(a, "FwInfiniteLife", 1e6) or 1e6)
    su, sy = curve.get("su"), curve.get("sy")
    total = float(sum(v["cycles"] for v, _s in stress))
    endurance = min(s for _n, s in curve["points"])

    def damage(n, factor):
        d = 0.0
        for v, s in stress:
            peak = abs(s[n]) * v["scale"] * factor
            r = v["ratio"]
            sa, sm = peak * (1.0 - r) / 2.0, peak * (1.0 + r) / 2.0
            seq = _equivalent(sa * kf, sm, how, su, sy)
            if seq <= endurance:            # below the curve's last point: infinite life, no damage (it was
                continue                    # cycles / infinite life: 100 % at 1e6 cycles on unloaded nodes)
            life = 0.0 if seq == float("inf") else cycles_at(curve["points"], seq, inf)
            d += v["cycles"] / life if life > 0 else float("inf")
        return d

    out = {"nodes": nodes, "Damage": [], "Life": [], "LoadFactor": []}
    for n in nodes:
        d = damage(n, 1.0)
        out["Damage"].append(min(1e12, 100.0 * d))
        out["Life"].append(min(inf, total / d) if d > 0 else inf)
        lo, hi = 1e-4, 1e4                  # load factor: damage(f) = 1, by bisection in log space
        if damage(n, hi) < 1.0:
            out["LoadFactor"].append(hi)
            continue
        for _i in range(40):
            mid = math.sqrt(lo * hi)
            if damage(n, mid) < 1.0:
                lo = mid
            else:
                hi = mid
        out["LoadFactor"].append(lo)
    _set(a, FATIGUE_RESULTS, json.dumps(out))
    simplots.defaults(a)
    return out


def fatigue_values(a, comp):
    data = json.loads(getattr(a, FATIGUE_RESULTS, "") or "{}")
    if not data:
        raise RuntimeError("Run the fatigue study first.")
    return list(zip(data["nodes"], data[comp]))


def fatigue_summary(a):
    data = json.loads(getattr(a, FATIGUE_RESULTS, "") or "{}")
    if not data:
        return ""
    return "Damage: max %.4g %%\nLife: min %.4g cycles\nLoad factor: min %.4g" % (
        max(data["Damage"]), min(data["Life"]), min(data["LoadFactor"]))


# =========================================================================== Drop Test
DROP_DEFAULTS = {"type": "Drop height", "from": "From centroid", "height": 1000.0, "height_unit": "mm",
                 "velocity": 4429.0, "gravity": 9.81, "direction": [0.0, 0.0, -1.0], "time": 0.0, "plots": 25,
                 "start": 0.0, "gravity_ref": "", "reverse": False, "orientation": "Normal to gravity",
                 "plane": "", "target": "Rigid target", "stiffness": 1e12}
TARGET_ORIENTATIONS = ("Normal to gravity", "Parallel to plane")
TARGET_KINDS = ("Rigid target", "Flexible target")


def direction_of(doc, ref):
    ""

    name, _c, sub = (ref or "").partition(":")
    o = doc.getObject(name) if name else None
    if o is None:
        return None
    if not sub:
        try:
            return o.Placement.Rotation.multVec(App.Vector(0, 0, 1))    # a datum plane's normal, a datum line's axis
        except Exception:
            return None
    try:
        el = o.Shape.getElement(sub)
    except Exception:
        return None
    if sub.startswith("Face"):
        try:
            if el.Surface.__class__.__name__ != "Plane":
                return None
            n = el.normalAt(*el.ParameterRange[::2])
            return App.Vector(n)
        except Exception:
            return None
    if sub.startswith("Edge"):
        try:
            if el.Curve.__class__.__name__ not in ("Line", "LineSegment"):
                return None
            d = el.Vertexes[-1].Point - el.Vertexes[0].Point
            return d if d.Length > 1e-12 else None
        except Exception:
            return None
    return None


def is_drop(a):
    return getattr(a, TYPE, "") == "drop"


def drop_values(a):
    v = dict(DROP_DEFAULTS)
    try:
        v.update(json.loads(getattr(a, DROP, "") or "{}"))
    except ValueError:
        pass
    return v


def set_drop(a, **values):
    from . import simpms
    v = drop_values(a)
    v.update(values)
    if v["type"] == "Drop height" and float(v["height"]) <= 0:
        raise simpms.SetupError("Give the drop height.")
    if v["type"] == "Velocity at impact" and float(v["velocity"]) <= 0:
        raise simpms.SetupError("Give the velocity at impact.")
    if float(v["gravity"]) <= 0:
        raise simpms.SetupError("Give the gravity.")
    if int(v["plots"]) < 1:
        raise simpms.SetupError("Save at least one plot.")
    if v.get("gravity_ref"):
        ref = direction_of(a.Document, v["gravity_ref"])
        if ref is None:
            raise simpms.SetupError("Pick a flat face, a plane or a straight edge for the gravity direction.")
        v["direction"] = list(ref * (-1.0 if v.get("reverse") else 1.0))
    d = App.Vector(*v["direction"])
    if d.Length < 1e-12:
        raise simpms.SetupError("Pick the gravity direction.")
    if v.get("orientation") == TARGET_ORIENTATIONS[1]:
        n = direction_of(a.Document, v.get("plane", ""))
        if n is None:
            raise simpms.SetupError("Pick the plane the target is parallel to (a flat face or a plane).")
        if abs(n.normalize().dot(App.Vector(d).normalize())) < 0.05:
            raise simpms.SetupError("The target plane cannot be parallel to gravity: the part would never reach it.")
    if v.get("target") == TARGET_KINDS[1] and float(v.get("stiffness", 0)) <= 0:
        raise simpms.SetupError("Give the target's normal stiffness per unit area.")
    d.normalize()
    v["direction"] = [d.x, d.y, d.z]
    _set(a, DROP, json.dumps(v))
    return v


def _mesh(a):
    return next((m for m in a.Group if m.isDerivedFrom("Fem::FemMeshObject")), None)


def _shape(a):
    from . import simpms
    m = _mesh(a)
    s = getattr(m, "Shape", None) if m is not None else None
    s = s or simpms.target(a.Document, a)
    return s.Shape if s is not None else None


def _material(a):
    for o in a.Group:
        if isinstance(getattr(o, "Material", None), dict) and o.Material:
            return o.Material
    return {}


def _q(mat, key, unit, default):
    try:
        return App.Units.Quantity(mat[key]).getValueAs(unit).Value
    except Exception:
        return default


def centroid(shape):
    """The centre of mass of a shape's solids: a Body's shape is a Compound, which has no CenterOfMass."""
    solids = list(getattr(shape, "Solids", []) or [])
    vol = sum(x.Volume for x in solids)
    if vol > 0:
        c = App.Vector()
        for x in solids:
            c += x.CenterOfMass * x.Volume
        return c * (1.0 / vol)
    try:
        return shape.CenterOfMass
    except Exception:
        return shape.BoundBox.Center


def impact_velocity(a, shape=None):
    """mm/s: from the drop height (from the centroid or the lowest point) or as given."""
    v = drop_values(a)
    if v["type"] == "Velocity at impact":
        return float(v["velocity"])
    h = float(v["height"])
    if v["from"] == "From centroid" and shape is not None:
        g = App.Vector(*v["direction"])        # pointing down: the lowest point has the largest p . g
        try:
            pts = shape.tessellate(max(0.1, shape.BoundBox.DiagonalLength / 200.0))[0]
        except Exception:
            pts = [x.Point for x in shape.Vertexes]
        low = max(p.dot(g) for p in pts) if pts else 0.0
        h -= low - centroid(shape).dot(g)        # the centroid is that far above the lowest point
    return math.sqrt(2.0 * float(v["gravity"]) * 1000.0 * max(h, 0.0))


def solution_time(a, shape):
    ""
    v = drop_values(a)
    if float(v.get("time") or 0.0) > 0:
        return float(v["time"]) * 1e-6
    mat = _material(a)
    e = _q(mat, "YoungsModulus", "MPa", 210000.0)
    rho = _q(mat, "Density", "t/mm^3", 7.8e-9)
    c = math.sqrt(e / rho) if rho > 0 else 5e6            # mm/s
    g = App.Vector(*v["direction"])
    span = shape.BoundBox.DiagonalLength if shape is not None else 100.0
    try:
        ext = [p.dot(g) for p in (shape.BoundBox.getPoint(i) for i in range(8))]
        span = max(ext) - min(ext) or span
    except Exception as _fw_err:
        _fw_log("simtypes.py:span", _fw_err)
    return 4.0 * span / c


def _num(x):
    """A real CalculiX reads whole: it takes 20 characters of a field ("5.139328595516968e-07" would lose its
    exponent's last digit)."""
    return "%.9g" % float(x) if "e" in "%.9g" % float(x) or "." in "%.9g" % float(x) else "%.9g." % float(x)


def target_stiffness(v, points, normal, band):
    ""

    if v.get("target") != TARGET_KINDS[1]:
        return 1e6
    u = normal.cross(App.Vector(1, 0, 0))
    if u.Length < 1e-6:
        u = normal.cross(App.Vector(0, 1, 0))
    u.normalize()
    w = normal.cross(u)
    us = [p.dot(u) for p in points]
    ws = [p.dot(w) for p in points]
    area = max(max(us) - min(us), band) * max(max(ws) - min(ws), band)      # mm^2
    per_node = area / max(1, len(points))
    return float(v.get("stiffness", 1e12)) * 1e-9 * per_node                # N/m^3 -> N/mm^3, times mm^2


def drop_input(a, text, femmesh):
    """The CalculiX input of a drop test from the static one FreeCAD wrote: density, the floor (a fixed node under
    each node near the lowest point, joined by a GAPUNI gap element with its clearance), the initial velocity, and
    *DYNAMIC in place of *STATIC; fixtures are dropped (a drop test has none)."""
    v = drop_values(a)
    shape = _shape(a)
    g = App.Vector(*v["direction"])
    g.normalize()
    fall = App.Vector(g)                       # the gaps close along the target's normal (into the target)
    if v.get("orientation") == TARGET_ORIENTATIONS[1]:
        n = direction_of(a.Document, v.get("plane", ""))
        if n is not None and n.Length > 1e-12:
            n.normalize()
            fall = n if n.dot(g) > 0 else n * -1.0
    nodes = {n: femmesh.getNodeById(n) for n in femmesh.Nodes}
    depth = {n: p.dot(fall) for n, p in nodes.items()}
    lowest = max(depth.values())
    size = shape.BoundBox.DiagonalLength if shape is not None else 100.0
    band = 0.03 * size
    near = sorted(n for n, d in depth.items() if lowest - d <= band)
    node0 = max(nodes) + 1000
    elem0 = max(list(femmesh.Volumes) + list(femmesh.Faces) + list(femmesh.Edges)) + 1000
    for line in text.splitlines():
        s = line.split(",")[0].strip()
        if s.isdigit():
            node0 = max(node0, int(s) + 1000)
            elem0 = max(elem0, int(s) + 1000)
    lines = ["** FreeCAD drop test: the floor"]
    lines.append("*NODE, NSET=FWFLOOR")
    for i, n in enumerate(near):
        p = nodes[n] + fall * (lowest - depth[n])
        lines.append("%d, %.12g, %.12g, %.12g" % (node0 + i, p.x, p.y, p.z))
    k = target_stiffness(v, [nodes[n] for n in near], fall, band)
    for i, n in enumerate(near):
        es = "FWGAP%d" % i
        lines += ["*ELEMENT, TYPE=GAPUNI, ELSET=%s" % es, "%d, %d, %d" % (elem0 + i, n, node0 + i),
                  "*GAP, ELSET=%s" % es, "%s, %s, %s, %s, , %s" % tuple(_num(x) for x in (lowest - depth[n], fall.x, fall.y,
                                                                                        fall.z, k))]
    speed = impact_velocity(a, shape)
    lines.append("*INITIAL CONDITIONS, TYPE=VELOCITY")
    for n in sorted(nodes):
        for dof, c in ((1, g.x), (2, g.y), (3, g.z)):
            if abs(c) > 1e-12:
                lines.append("%d, %d, %s" % (n, dof, _num(speed * c)))
    total = solution_time(a, shape)
    plots = max(1, int(v["plots"]))
    incs = max(60, 6 * plots)
    dt = total / incs
    every = max(1, incs // plots)
    mat = _material(a)
    rho = _q(mat, "Density", "t/mm^3", 7.8e-9)
    if "*DENSITY" not in text.upper():
        text = re.sub(r"(\*ELASTIC\n[^\n]*\n)", lambda m: m.group(1) + "*DENSITY\n%s\n" % _num(rho), text, count=1)
    text = re.sub(r"\*\* Fixed Constraints\n.*?(?=\*{5,})", "", text, flags=re.S)
    i = text.upper().find("\n*STEP")
    text = text[:i + 1] + "\n".join(lines) + "\n" + text[i + 1:]
    gval = float(v["gravity"]) * 1000.0
    step = ("*STEP, NLGEOM, INC=%d\n*DYNAMIC, DIRECT\n%s, %s\n*BOUNDARY\nFWFLOOR,1,3\n*DLOAD\nEall,GRAV,%s,%s,%s,%s\n"
            % ((incs * 4,) + tuple(_num(x) for x in (dt, total, gval, g.x, g.y, g.z))))
    text = re.sub(r"\*STEP[^\n]*\n\*STATIC\n[^\n]*\n", step, text, count=1, flags=re.I)
    text = re.sub(r"\*NODE FILE\n", "*NODE FILE, FREQUENCY=%d\n" % every, text, count=1)
    text = re.sub(r"\*EL FILE\n", "*EL FILE, FREQUENCY=%d\n" % every, text, count=1)
    text = re.sub(r"\*NODE PRINT[^\n]*\n[^\n]*\n", "", text)
    text = re.sub(r"\*OUTPUT, FREQUENCY=\d+", "*OUTPUT, FREQUENCY=%d" % every, text)
    saved = [dt * every * k for k in range(1, incs // every + 1)]
    if saved and saved[-1] < total - dt / 2:
        saved.append(total)
    _set(a, "FwDropTimes", json.dumps(saved))       # CalculiX's result labels round the times away
    return text


def _patch_ccx():
    try:
        from femtools import ccxtools
    except ImportError:
        return False
    cls = ccxtools.FemToolsCcx
    if getattr(cls, "_fw_drop", False):
        return True
    write0 = cls.write_inp_file
    check0 = cls.check_prerequisites

    def check_prerequisites(self, *args, **kw):
        message = check0(self, *args, **kw)
        if message and is_drop(getattr(self, "analysis", None)):     # a drop test has no fixtures: the floor holds it
            message = message.replace("Static analysis: No mechanical boundary conditions defined.\n", "")
        return message
    cls.check_prerequisites = check_prerequisites

    def write_inp_file(self, *args, **kw):
        r = write0(self, *args, **kw)
        try:
            a = self.analysis
            if is_drop(a):
                mesh = _mesh(a)
                path = self.inp_file_name
                text = open(path).read()
                with open(path, "w") as f:
                    f.write(drop_input(a, text, mesh.FemMesh))
        except Exception as _fw_err:
            _fw_log("simtypes.py:drop inp", _fw_err)
            raise
        return r
    cls.write_inp_file = write_inp_file
    cls._fw_drop = True
    return True


def _patch_kind():
    """simstudy's kind of a study: a fatigue or drop study's own type first."""
    from . import simstudy
    if getattr(simstudy, "_fw_types", False):
        return
    simstudy._kind_of0 = simstudy._kind_of

    def _kind_of(analysis):
        t = getattr(analysis, TYPE, "") if analysis is not None else ""
        if t in ("nonlinear", "topology", "lineardynamic"):     # a static setup to simstudy (tree, Advisor, checks)
            return "static"
        return t or simstudy._kind_of0(analysis)
    simstudy._kind_of = _kind_of
    simstudy.STEPS.setdefault("fatigue", ())
    simstudy._fw_types = True


def _topology_progress(it, comp, mass, change):
    """A Topology Study's run, pass by pass, in the status bar (the window stays live)."""
    if Gui is None:
        return
    from . import simrun
    try:
        text = "Topology Study: pass %d, mass %.0f %%, change %.3f" % (it, mass * 100.0, change)
        if simrun.window() is not None:
            simrun.stage(text)
            return
        Gui.getMainWindow().statusBar().showMessage(text, 5000)
        QtWidgets.QApplication.processEvents()
    except simrun.Cancelled:
        raise
    except Exception as _fw_err:
        _fw_log("simtypes.py:topology progress", _fw_err)


def _progress(text):
    if Gui is None:
        return
    from . import simrun
    try:
        if simrun.window() is not None:      # the run window's stage line (Cancel is honoured here too)
            simrun.stage(text)
            return
        Gui.getMainWindow().statusBar().showMessage(text, 5000)
        QtWidgets.QApplication.processEvents()
    except simrun.Cancelled:
        raise
    except Exception as _fw_err:
        _fw_log("simtypes.py:progress", _fw_err)


def _patch_run():
    """Run This Study: a fatigue study runs its events; a drop test needs no fixtures."""
    from . import addintabs
    if getattr(addintabs, "_fw_types", False):
        return
    run0 = addintabs.run_study

    def run_study(analysis):
        if is_fatigue(analysis):
            run_fatigue(analysis)
            return fatigue_summary(analysis)
        if is_nonlinear(analysis):
            apply_nonlinear(analysis)          # the options and plasticity as the study and its material are now
        from . import simdynamic, simpressure, simtopology
        if simpressure.is_pressure(analysis):  # the static studies' results, combined
            return simpressure.run(analysis, _progress)
        if simdynamic.is_dynamic(analysis):    # modes, then the response over frequency or time
            return simdynamic.run(analysis, _progress)
        if simtopology.is_topology(analysis):  # repeated static solves, a density per element
            return simtopology.run(analysis, _topology_progress)
        return run0(analysis)
    addintabs.run_study = run_study
    summary0 = addintabs.study_summary

    def study_summary(solver, res, analysis=None):
        if analysis is not None and is_drop(analysis) and res:
            r = res[-1]
            peak = max(res, key=lambda r: max(r.vonMises or [0.0]))
            return "Drop test, %d time steps\nMax von Mises stress: %.4g MPa (step %d)\nMax displacement: %.4g mm" % (
                len(res), max(peak.vonMises or [0.0]), res.index(peak) + 1, max(max(r.DisplacementLengths or [0.0]) for r in res))
        if analysis is not None and is_nonlinear(analysis) and res:
            st = thermal_steps(analysis)
            r = st[-1][1] if st else res[-1]
            return "Nonlinear, %d time steps (end time %.4g s)\nMax von Mises stress: %.4g MPa\nMax displacement: %.4g mm" % (
                len(res), st[-1][2] if st else 0.0, max(r.vonMises or [0.0]), max(r.DisplacementLengths or [0.0]))
        return summary0(solver, res, analysis)
    addintabs.study_summary = study_summary
    addintabs._fw_types = True


def _patch_pipeline():
    """FreeCAD 1.1's result pipeline refuses two steps with the same value ("Values need to be unique"): a frequency
    study of a square bar has two modes at the same frequency, and a drop test can save one time twice. The run's
    results are read already; the pipeline then gets the values made distinct by a hair (or is left out)."""
    try:
        from feminout import importCcxFrdResults as imp
    except ImportError:
        return False
    if getattr(imp, "_fw_unique", False):
        return True
    setup0 = imp.setupPipeline

    def setupPipeline(doc, analysis, results_name, result_data):
        try:
            return setup0(doc, analysis, results_name, result_data)
        except ValueError as err:
            if "unique" not in str(err) or len(result_data) < 2:
                raise
            vals, seen = [], set()
            for v in list(result_data[1]):
                v = float(v)
                while v in seen:
                    v = v + max(abs(v), 1.0) * 1e-9
                seen.add(v)
                vals.append(v)
            data = list(result_data)
            data[1] = vals
            try:
                return setup0(doc, analysis, results_name, data)
            except Exception as err2:
                _fw_log("simtypes.py:pipeline", err2)
                return None
    imp.setupPipeline = setupPipeline
    imp._fw_unique = True
    return True


def install_core():
    _patch_pipeline()
    _patch_kind()
    _patch_run()
    _patch_ccx()
    try:
        from . import simtopology
        simtopology.install()                  # Material Mass, a Topology Study's plot
    except Exception as _fw_err:
        _fw_log("simtypes.py:topology", _fw_err)
    try:
        from . import simpressure
        simpressure.install()                  # a Pressure Vessel Design study's plots and Linearize
    except Exception as _fw_err:
        _fw_log("simtypes.py:pressure", _fw_err)
    try:
        from . import simdynamic
        simdynamic.install()                   # a Linear Dynamic study's plots at its peak step
    except Exception as _fw_err:
        _fw_log("simtypes.py:dynamic", _fw_err)


# =========================================================================== Thermal Loads (the objects)
TEMP_UNITS = ("Kelvin", "Celsius", "Fahrenheit")


def to_kelvin(value, unit):
    value = float(value)
    if unit == "Celsius":
        return value + 273.15
    if unit == "Fahrenheit":
        return (value - 32.0) / 1.8 + 273.15
    return value


def from_kelvin(value, unit):
    if unit == "Celsius":
        return value - 273.15
    if unit == "Fahrenheit":
        return (value - 273.15) * 1.8 + 32.0
    return value


def _thermal(a):
    from . import simpms
    if a is None:
        raise simpms.SetupError("Make a thermal study first (Simulation > New Study > Thermal).")
    if study_type(a) != "thermomech":
        raise simpms.SetupError("Thermal loads belong to a thermal study: make one with New Study > Thermal.")


def add_temperature(doc, a, obj, faces, value, unit="Kelvin", initial=False, edit=None):
    """Temperature on faces; with initial=True the study's Initial temperature (CalculiX takes it for the whole part)."""
    import ObjectsFem
    from . import simpms, simxpress as sx
    _thermal(a)
    k = to_kelvin(value, unit)
    if k <= 0:
        raise simpms.SetupError("The temperature must be above absolute zero.")
    if initial:
        o = edit if edit is not None else next((x for x in a.Group if x.TypeId == "Fem::ConstraintInitialTemperature"), None)
        with sx.fem_safe():
            if o is None:
                o = ObjectsFem.makeConstraintInitialTemperature(doc, "InitialTemperature")
                a.addObject(o)
            for name in ("initialTemperature", "InitialTemperature"):
                if name in o.PropertiesList:
                    setattr(o, name, "%r K" % k)
                    break
        o.Label = "Initial Temperature-1"
    else:
        if not faces:
            raise simpms.SetupError("Pick the faces that have the temperature.")
        with sx.fem_safe():
            o = edit if edit is not None else ObjectsFem.makeConstraintTemperature(doc, "Temperature")
            o.References = [(obj, list(faces))]
            if "ConstraintType" in o.PropertiesList:
                o.ConstraintType = "Temperature"
            o.Temperature = "%r K" % k
            simpms._add(a, o, "Temperature", edit)
    simpms._keep(o, thermal="Temperature", value=float(value), unit=unit, initial=bool(initial))
    doc.recompute()
    return o


STATIC_TEMPERATURE = ("static", "nonlinear")       # the study types whose External Loads take a Temperature (CalculiX writes it)


def add_static_temperature(doc, a, obj, faces, value, unit="Kelvin", reference=298.0, ref_unit="Kelvin", edit=None):
    ""


    import ObjectsFem
    from . import simpms, simtree, simxpress as sx
    if a is None or study_type(a) not in STATIC_TEMPERATURE:
        raise simpms.SetupError("A temperature load belongs to a static or thermal study.")
    k, r = to_kelvin(value, unit), to_kelvin(reference, ref_unit)
    if k <= 0 or r <= 0:
        raise simpms.SetupError("The temperature must be above absolute zero.")
    mats = simtree._materials(a)
    if mats and not any("ThermalExpansionCoefficient" in (getattr(m, "Material", {}) or {}) for m in mats):
        raise simpms.SetupError("The study's material has no thermal expansion coefficient: apply a material that has one.")
    with sx.fem_safe():
        o = edit if edit is not None else ObjectsFem.makeConstraintInitialTemperature(doc, "Temperature")
        o.References = [(obj, list(faces))] if faces else []
        o.initialTemperature = "%r K" % r
        o.EnableFinalTemperature = True
        o.FinalTemperature = "%r K" % k
        simpms._add(a, o, "Temperature", edit)
    simpms._keep(o, thermal="Temperature", value=float(value), unit=unit, static=True, reference=float(reference),
                 ref_unit=ref_unit)
    doc.recompute()
    return o


def add_heatflux(doc, a, obj, faces, kind, edit=None, **v):
    """Convection (coefficient W/(m^2.K), bulk ambient temperature), Heat Flux (W/m^2) or Radiation (emissivity,
    ambient temperature) on faces: FreeCAD's heat flux object of that type."""
    import ObjectsFem
    from . import simpms, simxpress as sx
    _thermal(a)
    if not faces:
        raise simpms.SetupError("Pick the faces for the %s." % kind.lower())
    with sx.fem_safe():
        o = edit if edit is not None else ObjectsFem.makeConstraintHeatflux(doc, kind.replace(" ", ""))
        o.References = [(obj, list(faces))]
        if kind == "Convection":
            if float(v.get("coefficient", 0)) <= 0:
                raise simpms.SetupError("Give the convection coefficient.")
            o.ConstraintType = "Convection"
            o.FilmCoef = "%r W/m^2/K" % float(v["coefficient"])
            o.AmbientTemp = "%r K" % to_kelvin(v.get("ambient", 300.0), v.get("unit", "Kelvin"))
        elif kind == "Radiation":
            e = float(v.get("emissivity", 0))
            if not 0 < e <= 1:
                raise simpms.SetupError("Emissivity is between 0 and 1.")
            o.ConstraintType = "Radiation"
            o.Emissivity = e
            o.AmbientTemp = "%r K" % to_kelvin(v.get("ambient", 300.0), v.get("unit", "Kelvin"))
        else:
            o.ConstraintType = "DFlux"
            o.DFlux = "%r W/m^2" % (float(v.get("flux", 0.0)) * (-1.0 if v.get("reverse") else 1.0))
        simpms._add(a, o, kind, edit)
    simpms._keep(o, thermal=kind, **v)
    doc.recompute()
    return o


def add_heat_power(doc, a, obj, power, edit=None):
    """Heat Power (W) made inside the part (FreeCAD's body heat source, Total Power)."""
    import ObjectsFem
    from . import simpms, simxpress as sx
    _thermal(a)
    if float(power) == 0:
        raise simpms.SetupError("Give the heat power.")
    with sx.fem_safe():
        o = edit if edit is not None else ObjectsFem.makeConstraintBodyHeatSource(doc, "HeatPower")
        o.References = [(obj, ["Solid%d" % (i + 1) for i in range(len(obj.Shape.Solids))])]
        o.Mode = "Total Power"
        o.TotalPower = "%r W" % float(power)
        simpms._add(a, o, "Heat Power", edit)
    simpms._keep(o, thermal="Heat Power", power=float(power))
    doc.recompute()
    return o


def is_ours(o):
    from . import simpms
    return EVENT in getattr(o, "PropertiesList", []) or "thermal" in simpms.kept(o)


# =========================================================================== Study Properties (values)
def set_properties(a, **v):
    """The type's Study Properties onto the solver (or the fatigue study)."""
    from . import addintabs, simpms
    k = study_type(a)
    if k == "nonlinear":
        old = getattr(a, NL, "")
        nv = nonlinear_values(a)
        nv.update({key: v[key] for key in NL_DEFAULTS if key in v})
        _set(a, NL, json.dumps(nv))
        try:
            apply_nonlinear(a)
        except Exception:
            _set(a, NL, old)                   # refused: the study keeps its options
            raise
        return
    if k == "fatigue":
        if "alternating" in v:
            _set(a, "FwAlternating", v["alternating"])
        if "mean" in v:
            _set(a, "FwMeanCorrection", v["mean"])
        if "kf" in v:
            if float(v["kf"]) <= 0:
                raise simpms.SetupError("Kf must be above 0.")
            _set(a, "FwKf", float(v["kf"]), "App::PropertyFloat")
        if "infinite" in v:
            _set(a, "FwInfiniteLife", float(v["infinite"]), "App::PropertyFloat")
        _clear_fatigue(a)
        return
    s = addintabs._solver(a)
    if s is None:
        raise simpms.SetupError("The study has no solver.")
    if "soft" in v and k in SOFT_TYPES:
        _set(a, SOFT, bool(v["soft"]), "App::PropertyBool", "Options: Use soft spring to stabilize the model")
    if "inertial" in v and k in SOFT_TYPES and k not in ("frequency", "buckling"):
        _set(a, INERTIAL, bool(v["inertial"]), "App::PropertyBool", "Options: Use inertial relief")
    if k == "frequency":
        if int(v.get("count", 1)) < 1:
            raise simpms.SetupError("Ask for at least one frequency.")
        s.EigenmodesCount = int(v.get("count", 5))
        upper = v.get("upper")
        s.EigenmodeHighLimit = float(upper) if upper else 1e6
        if "inplane" in v:
            _set(a, INPLANE, bool(v["inplane"]), "App::PropertyBool", "Frequency Options: Use inplane effect")
    elif k == "buckling":
        if int(v.get("count", 1)) < 1:
            raise simpms.SetupError("Ask for at least one buckling mode.")
        s.BucklingFactors = int(v.get("count", 1))
    elif k == "thermomech":
        steady = bool(v.get("steady", True))
        s.ThermoMechSteadyState = steady
        if not steady:
            total, inc = float(v.get("total", 100.0)), float(v.get("increment", 10.0))
            if total <= 0 or inc <= 0 or inc > total:
                raise simpms.SetupError("The time increment must be above 0 and no more than the total time.")
            for name, val in (("TimePeriod", total), ("TimeEnd", total), ("TimeInitialIncrement", inc),
                              ("TimeInitialStep", inc), ("TimeMaximumIncrement", inc), ("TimeMaximumStep", inc),
                              ("TimeMinimumIncrement", inc / 1000.0), ("TimeMinimumStep", inc / 1000.0)):
                if name in s.PropertiesList:
                    try:
                        setattr(s, name, "%r s" % val if "Quantity" in s.getTypeIdOfProperty(name) else val)
                    except Exception as _fw_err:
                        _fw_log("simtypes.py:time", _fw_err)
            if "IterationsUserDefinedIncrementations" in s.PropertiesList:
                s.IterationsUserDefinedIncrementations = True
    a.Document.recompute()


def properties(a):
    from . import addintabs
    k = study_type(a)
    if k == "nonlinear":
        return nonlinear_values(a)
    if k == "fatigue":
        return {"alternating": getattr(a, "FwAlternating", ALTERNATING[1]), "mean": getattr(a, "FwMeanCorrection", "None"),
                "kf": float(getattr(a, "FwKf", 1.0)), "infinite": float(getattr(a, "FwInfiniteLife", 1e6))}
    s = addintabs._solver(a)

    def num(name, default):
        try:
            v = getattr(s, name)
            return float(getattr(v, "Value", v))
        except Exception:
            return default
    if k == "frequency":
        hi = num("EigenmodeHighLimit", 1e6)
        return {"count": int(num("EigenmodesCount", 5)), "upper": hi if hi < 1e6 else None,
                "inplane": bool(getattr(a, INPLANE, False)), "soft": bool(getattr(a, SOFT, False))}
    if k == "buckling":
        return {"count": int(num("BucklingFactors", 1)), "soft": bool(getattr(a, SOFT, False))}
    if k == "thermomech":
        return {"steady": bool(getattr(s, "ThermoMechSteadyState", True)),
                "total": num("TimePeriod", num("TimeEnd", 100.0)),
                "increment": num("TimeInitialIncrement", num("TimeInitialStep", 10.0))}
    if k in SOFT_TYPES:
        return {"soft": bool(getattr(a, SOFT, False)), "inertial": bool(getattr(a, INERTIAL, False))}
    return {}


# =========================================================================== tree hooks (simtree calls these)
def study_rows(a, Row):
    ""

    from . import simpressure
    if simpressure.is_pressure(a):
        return simpressure.study_rows(a, Row)
    if not is_fatigue(a):
        return None
    from . import simtree
    root = Row("%s (-%s-)" % (a.Label, simtree.config_name(a.Document)), "SIM_Fatigue", a, "study")
    part = root.add(Row(a.Document.Label or a.Document.Name, "SIM_ApplyMaterial", None, "fatigueparts"))
    curve = sn_curve(a)
    if curve.get("material"):
        part.add(Row("SolidBody 1 (-%s-)" % curve["material"], "SIM_ApplyMaterial", None, "fatiguebody"))
    loading = root.add(Row("Loading (-Constant Amplitude-)", "SIM_FatigueEvent", None, "loading"))
    for o in events(a):
        loading.add(Row(event_text(o) + (" (Suppressed)" if getattr(o, "Suppressed", False) else ""), "SIM_FatigueEvent",
                        o, "event"))
    results = root.add(Row("Results", "SIM_Results", None, "results"))
    if getattr(a, FATIGUE_RESULTS, ""):
        from . import simplots
        simplots.defaults(a)
        for p in simplots.plots(a):
            results.add(Row(simplots.title(p), "SIM_Results", None, "plot", plot=p["name"]))
    return root


def adjust_rows(a, root, Row):
    """A drop test's tree: Setup and Result Options in place of Fixtures and External Loads. A Topology Study's: Goals
    and Constraints and Manufacturing Controls after External Loads."""
    from . import simtopology
    if simtopology.is_topology(a):
        at = next((i for i, r in enumerate(root.rows) if r.what == "mesh"), len(root.rows))
        mc = Row("Manufacturing Controls", "SIM_Topology", None, "topocontrols")
        for text in simtopology.control_rows(a):
            mc.add(Row(text, "SIM_Topology", None, "topocontrols"))
        root.rows.insert(at, mc)
        root.rows.insert(at, Row("Goals and Constraints", "SIM_Topology", None, "topogoals"))
        return root
    if not is_drop(a):
        return root
    keep = [r for r in root.rows if r.what not in ("fixtures", "loads")]
    v = drop_values(a)
    words = "Drop height" if v["type"] == "Drop height" else "Velocity at impact"
    at = next((i for i, r in enumerate(keep) if r.what == "mesh"), len(keep))
    keep.insert(at, Row("Result Options", "SIM_Props", None, "dropresults"))
    keep.insert(at, Row("Setup (-%s-)" % words, "SIM_DropTest", None, "dropsetup"))
    root.rows = keep
    return root


def menu_entries(row, a, key):
    """Right-click entries of the rows this module owns, or of a Results folder of these types; None otherwise."""
    from . import simplots, simtree
    w, o = row.what, row.obj
    k = study_type(a)
    out = []
    if k == "pressure":
        from . import simpressure
        ext = simpressure.menu_entries(row, a, key)
        if ext is not None:
            return [x for x in ext if x is not None]
    if w == "study" and k == "fatigue":
        out += [("Run", lambda: _run(a)), ("Properties...", lambda: open_properties(a)), ("-", None)]
        from . import simtree
        out += [("Copy Study", lambda: simtree.copy_study(a)), ("Rename", None), ("Delete", lambda: simtree.delete_study(a))]
        return out
    if w == "loading":
        return [("Add Event...", lambda: open_event(a))]
    if k == "topology":
        from . import simtopology
        if w in ("topogoals", "topocontrols"):
            return [("Edit Definition...", lambda: simtopology.open_goals(a))]
        if w == "plot":
            name = row.plot
            return [("Show", lambda: simplots.show(a, name)), ("Edit Definition...", lambda: simtopology.open_mass(a, name)),
                    ("Export Smoothed Mesh", lambda: simtopology.export_smoothed(a)), ("-", None),
                    ("Hide", lambda: simplots.clear())]
        if w == "results" and simtopology.densities(a):
            if simtree.has_key("SIM_Purge"):
                return [("Delete All Results", lambda: simtree.run_key("SIM_Purge", a, None))]
            return []
    if w == "event" and o is not None:
        sup = bool(getattr(o, "Suppressed", False))
        return [("Edit Definition...", lambda: open_event(a, o)),
                ("Unsuppress" if sup else "Suppress", lambda: _suppress(a, o, not sup)), ("-", None),
                ("Delete", lambda: _delete(a, o))]
    if w in ("fatigueparts", "fatiguebody"):
        return [("Apply/Edit Fatigue Data...", lambda: open_fatigue_data(a))]
    if w == "dropsetup":
        return [("Edit Definition...", lambda: open_drop_setup(a))]
    if w == "dropresults":
        return [("Edit Definition...", lambda: open_result_options(a))]
    if w == "thermal":
        for text, kk in (("Temperature...", "SIM_Temperature"), ("Convection...", "SIM_Convection"),
                         ("Heat Flux...", "SIM_HeatFlux"), ("Heat Power...", "SIM_BodyHeat"),
                         ("Radiation...", "SIM_Radiation")):
            key(text, kk)
        return out
    if w == "results" and simplots.result(a) is not None and k in ("frequency", "buckling", "thermomech", "fatigue", "drop"):
        if k in ("frequency", "buckling"):
            out.append(("Define Mode Shape/Displacement Plot...", lambda: simtree._define(a, "Amplitude")))
            if k == "frequency":
                out.append(("List Resonant Frequencies...", lambda: list_dialog(a, "frequencies")))
                out.append(("List Mass Participation...", lambda: list_dialog(a, "mass")))
            else:
                out.append(("List Buckling Factors...", lambda: list_dialog(a, "buckling")))
        elif k == "thermomech":
            out.append(("Define Thermal Plot...", lambda: simtree._define(a, "Thermal")))
        elif k == "fatigue":
            out.append(("Define Fatigue Plot...", lambda: simtree._define(a, "Fatigue")))
        else:
            for q in ("Stress", "Displacement", "Strain"):
                out.append(("Define %s Plot..." % q, lambda q=q: simtree._define(a, q)))
        out.append(("-", None))
        if k != "fatigue":        # this menu's own list (key() adds to the tree's, ahead of these)
            if simtree.has_key("SIM_Purge"):
                out.append(("Delete All Results", lambda: simtree.run_key("SIM_Purge", a, None)))
        else:
            out.append(("Delete All Results", lambda: (_clear_fatigue(a), simplots.save_plots(a, []))))
        return out
    return None


def _run(a):
    from . import addintabs
    try:
        text = addintabs.run_study(a)
    except Exception as e:
        if Gui is not None:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Run", str(e))
        return None
    _refresh()
    return text


def _suppress(a, o, on):
    o.Suppressed = bool(on)
    _clear_fatigue(a)
    a.Document.recompute()
    _refresh()


def _delete(a, o):
    from . import simtree
    if not simtree._ask(simtree.DELETE_TEXT % o.Label):
        return False
    a.removeObject(o)
    a.Document.removeObject(o.Name)
    _clear_fatigue(a)
    _refresh()
    return True


def _refresh():
    try:
        from . import simtree
        simtree.refresh()
    except Exception as _fw_err:
        _fw_log("simtypes.py:refresh", _fw_err)


def edit(o):
    """Edit Definition of a thermal load or an event made here."""
    from . import simpms
    k = simpms.kept(o)
    a = next((x for x in o.InList if x.TypeId == "Fem::FemAnalysis"), None)
    if EVENT in o.PropertiesList:
        return open_event(a, o)
    kind = k.get("thermal")
    if kind and Gui is not None:
        return simpms.show(ThermalPM(o.Document, kind, edit=o))
    return None


# =========================================================================== GUI
if Gui is not None:
    from . import simpms, simxpress as sx

    OPEN = []

    def _show(pm):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        del OPEN[:]
        OPEN.append(pm)
        Gui.Control.showDialog(pm)
        return pm

    ICON_STAND_IN = {"SIM_Nonlinear": "SIM_MaterialNonlinear"}    # no drawn study-type icon of its own yet

    def _icon(key):
        try:
            from . import simicons
            path = simicons.svg(key) or (simicons.svg(ICON_STAND_IN[key]) if key in ICON_STAND_IN else None)
            return QtGui.QIcon(path) if path else QtGui.QIcon()
        except Exception:
            return QtGui.QIcon()

    class _Panel:
        """A PropertyManager of boxes, OK / Cancel, one Undo step."""
        PM = "Study"

        def __init__(self, doc):
            self.doc = doc

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def reject(self):
            Gui.Control.closeDialog()
            return True

        def accept(self):
            self.doc.openTransaction(self.PM)
            try:
                self.made = self.apply()
            except simpms.SetupError as e:
                self.doc.abortTransaction()
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, str(e))
                return False
            except Exception:
                self.doc.abortTransaction()
                raise
            self.doc.commitTransaction()
            Gui.Control.closeDialog()
            _refresh()
            return True

    # ------------------------------------------------------------------- New Study
    STUDY_ICON = 24
    STUDY_GRID = QtCore.QSize(78, 58)

    def _fit_types(lw, count=None):
        ""

        count = lw.count() if count is None else count
        cols = max(1, (lw.width() - 6) // STUDY_GRID.width()) if lw.width() > 50 else 3
        h = 6 + STUDY_GRID.height() * ((count + cols - 1) // cols)
        if lw.height() != h:
            lw.setFixedHeight(h)

    class _TypesFit(QtCore.QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QtCore.QEvent.Resize and isinstance(obj, QtWidgets.QListWidget):
                try:
                    _fit_types(obj)
                except RuntimeError:
                    pass
            return False
    _TYPES_FIT = _TypesFit()

    class NewStudyPM(_Panel):
        ""

        PM = "Study"

        def __init__(self, doc, kind="static"):
            super().__init__(doc)
            msg = sx._box("Message", None, "Study")
            ml = QtWidgets.QVBoxLayout(msg)
            self.message = QtWidgets.QLabel()
            self.message.setObjectName("SWSimStudyMessage")
            self.message.setWordWrap(True)
            ml.addWidget(self.message)
            name = sx._box("Name")
            nl = QtWidgets.QVBoxLayout(name)
            self.name = QtWidgets.QLineEdit()
            self.name.setObjectName("SWSimStudyName")
            nl.addWidget(self.name)
            self.kind = None
            self.lists = {}
            self.group_boxes = {}
            boxes = [msg, name]
            for group in GROUPS:
                box = sx._box(group)
                bl = QtWidgets.QVBoxLayout(box)
                lw = QtWidgets.QListWidget()
                lw.setObjectName("SWSimStudyTypes" + group.split()[0])
                lw.setViewMode(QtWidgets.QListView.IconMode)
                lw.setIconSize(QtCore.QSize(STUDY_ICON, STUDY_ICON))
                lw.setGridSize(STUDY_GRID)
                lw.setWordWrap(True)
                lw.setTextElideMode(QtCore.Qt.ElideNone)     # "Pressure Vessel Design" on two lines, not "Pressu..."
                lw.setMovement(QtWidgets.QListView.Static)
                lw.setResizeMode(QtWidgets.QListView.Adjust)
                lw.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                lw.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                count = sum(1 for g, _l, _k, _i in TYPES if g == group)
                _fit_types(lw, count)
                lw.installEventFilter(_TYPES_FIT)
                for g, label, k, icon in TYPES:
                    if g == group:
                        it = QtWidgets.QListWidgetItem(_icon(icon), label)
                        it.setToolTip(label)
                        it.setData(QtCore.Qt.UserRole, k)
                        lw.addItem(it)
                lw.currentItemChanged.connect(lambda cur, _prev, lw=lw: self._picked(lw, cur))
                bl.addWidget(lw)
                self.lists[group] = lw
                self.group_boxes[group] = box
                boxes.append(box)
                if group == "Advanced Simulation":       # Linear Dynamic: the analysis, under its group
                    self.dyn = QtWidgets.QWidget()
                    dl = QtWidgets.QVBoxLayout(self.dyn)
                    dl.setContentsMargins(4, 0, 0, 0)
                    self.dyn_buttons = {}
                    from . import simdynamic
                    for n in simdynamic.ANALYSES:
                        r = QtWidgets.QRadioButton(n)
                        r.setObjectName("SWSimDynamic" + n.replace(" ", ""))
                        r.toggled.connect(lambda on, n=n: on and self._analysis(n))
                        dl.addWidget(r)
                        self.dyn_buttons[n] = r
                    self.dyn_buttons[simdynamic.DEFAULTS["analysis"]].setChecked(True)
                    bl.addWidget(self.dyn)
            self.analysis = None
            self.form = boxes
            self.kind = None
            self.pick(kind)

        def _picked(self, lw, item):
            if item is None:
                return
            for other in self.lists.values():
                if other is not lw:
                    other.blockSignals(True)
                    other.clearSelection()
                    other.setCurrentItem(None)
                    other.blockSignals(False)
            self.kind = item.data(QtCore.Qt.UserRole)
            self.dyn.setVisible(self.kind == "lineardynamic")
            self.message.setText(MESSAGES.get(self.kind, ""))
            if self.kind == "lineardynamic":
                self.analysis = next(n for n, r in self.dyn_buttons.items() if r.isChecked())
                self.name.setText(_next_label(self.doc, self.analysis))
            elif self.kind != "design":
                self.name.setText(_next_label(self.doc, LABELS[self.kind]))
            else:
                self.name.setText(_next_label(self.doc, "Design Study"))

        def _analysis(self, n):
            self.analysis = n
            if self.kind == "lineardynamic":
                self.name.setText(_next_label(self.doc, n))

        def pick(self, kind):
            for lw in self.lists.values():
                for i in range(lw.count()):
                    if lw.item(i).data(QtCore.Qt.UserRole) == kind:
                        lw.setCurrentRow(i)
                        return

        def apply(self):
            if self.kind is None:
                raise simpms.SetupError("Pick the type of study.")
            name = self.name.text().strip() or None
            if self.kind == "design":
                Gui.Control.closeDialog()
                QtCore.QTimer.singleShot(0, lambda: _open_design(self.doc, _assembly(self.doc)))
                return None
            try:
                a = new_typed_study(self.doc, self.kind, name, analysis=self.analysis if self.kind == "lineardynamic"
                                    else None)
            except ValueError as e:
                raise simpms.SetupError(str(e))
            from . import addintabs
            addintabs._set_active(a)
            try:
                from . import simtree
                simtree.activate(a.Document, a)
            except Exception as _fw_err:
                _fw_log("simtypes.py:activate", _fw_err)
            addintabs._refresh_buttons()
            return a

        def accept(self):
            if self.kind == "design":
                return super().accept() or True
            return super().accept()

    def _row_visible(w, on):
        """Shows or hides a field with its form label (a field that cannot be used is hidden, not greyed)."""
        w.setVisible(bool(on))
        try:
            lay = w.parentWidget().layout() if w.parentWidget() is not None else None
            label = lay.labelForField(w) if isinstance(lay, QtWidgets.QFormLayout) else None
            if label is not None:
                label.setVisible(bool(on))
        except Exception as _fw_err:
            _fw_log("simtypes.py:row", _fw_err)

    # ------------------------------------------------------------------- Study Properties
    class PropertiesPM(_Panel):
        ""
        PM = "Study Properties"

        def __init__(self, a):
            super().__init__(a.Document)
            self.a = a
            self.k = study_type(a)
            v = properties(a)
            box = sx._box("Options", None, "%s" % LABELS.get(self.k, "Study") if self.k != "thermomech" else "Thermal")
            form = QtWidgets.QFormLayout(box)
            self.w = {}
            if self.k in ("frequency", "buckling"):
                n = QtWidgets.QSpinBox()
                n.setObjectName("SWSimPropCount")
                n.setRange(1, 200)
                n.setValue(v["count"])
                form.addRow("Number of frequencies:" if self.k == "frequency" else "Number of buckling modes:", n)
                self.w["count"] = n
                if self.k == "frequency":
                    self.upper_on = QtWidgets.QCheckBox("Upper bound frequency:")
                    self.upper_on.setObjectName("SWSimPropUpperOn")
                    up = QtWidgets.QDoubleSpinBox()
                    up.setObjectName("SWSimPropUpper")
                    up.setRange(0.0, 1e9)
                    up.setDecimals(3)
                    up.setSuffix(" Hz")
                    up.setValue(v["upper"] or 1000.0)
                    self.upper_on.setChecked(v["upper"] is not None)
                    up.setVisible(v["upper"] is not None)          # shown only while ticked (greyed is dead)
                    self.upper_on.toggled.connect(up.setVisible)
                    form.addRow(self.upper_on, up)
                    self.w["upper"] = up
            elif self.k == "thermomech":
                self.steady = QtWidgets.QRadioButton("Steady state")
                self.steady.setObjectName("SWSimPropSteady")
                self.transient = QtWidgets.QRadioButton("Transient")
                self.transient.setObjectName("SWSimPropTransient")
                (self.steady if v["steady"] else self.transient).setChecked(True)
                form.addRow("Solution type:", self.steady)
                form.addRow("", self.transient)
                for name, label in (("total", "Total time:"), ("increment", "Time increment:")):
                    sp = QtWidgets.QDoubleSpinBox()
                    sp.setObjectName("SWSimProp" + name.title())
                    sp.setRange(0.0, 1e9)
                    sp.setDecimals(3)
                    sp.setSuffix(" sec")
                    sp.setValue(v[name])
                    form.addRow(label, sp)
                    self.w[name] = sp
                self.transient.toggled.connect(self._enable)
                self._enable()
            elif self.k == "nonlinear":

                # material model (Plasticity - von Mises, its tangent modulus and hardening) sits here too
                for name, label, suffix in (("end", "End time:", " sec"), ("increment", "Time increment:", " sec")):
                    sp = QtWidgets.QDoubleSpinBox()
                    sp.setObjectName("SWSimProp" + name.title())
                    sp.setRange(0.0001, 1e6)
                    sp.setDecimals(4)
                    sp.setSuffix(suffix)
                    sp.setValue(float(v[name]))
                    form.addRow(label, sp)
                    self.w[name] = sp
                self.large = QtWidgets.QCheckBox("Use large displacement formulation")
                self.large.setObjectName("SWSimPropLarge")
                self.large.setChecked(bool(v["large"]))
                form.addRow(QtWidgets.QLabel("Geometry nonlinearity options:"))
                form.addRow(self.large)
                mb = sx._box("Material Model")
                mf = QtWidgets.QFormLayout(mb)
                model = QtWidgets.QComboBox()
                model.setObjectName("SWSimPropModel")
                model.addItems(list(NL_MODELS))
                model.setCurrentText(v["model"])
                tangent = QtWidgets.QDoubleSpinBox()
                tangent.setObjectName("SWSimPropTangent")
                tangent.setRange(0.0, 1e7)
                tangent.setDecimals(1)
                tangent.setSuffix(" MPa")
                tangent.setValue(float(v["tangent"]))
                hard = QtWidgets.QComboBox()
                hard.setObjectName("SWSimPropHardening")
                hard.addItems(list(NL_HARDENING))
                hard.setCurrentText(v["hardening"])
                mf.addRow("Model type:", model)

                # when the material has one (no dead control)
                self.use_curve = QtWidgets.QCheckBox("Use stress-strain curve")
                self.use_curve.setObjectName("SWSimPropCurve")
                self.use_curve.setChecked(bool(v.get("curve")))
                self.has_curve = bool(stress_strain(a))
                mf.addRow(self.use_curve)
                self.use_curve.toggled.connect(self._models)
                mf.addRow("Tangent modulus:", tangent)
                mf.addRow("Hardening:", hard)
                self.w.update(model=model, tangent=tangent, hardening=hard)
                self.nl_rows = [(tangent, mf.labelForField(tangent)), (hard, mf.labelForField(hard))]
                model.currentTextChanged.connect(self._models)
                self.extra_boxes = [mb]
                self._models()
            elif self.k == "fatigue":
                alt = QtWidgets.QComboBox()
                alt.setObjectName("SWSimPropAlternating")
                alt.addItems(list(ALTERNATING))
                alt.setCurrentText(v["alternating"])
                mean = QtWidgets.QComboBox()
                mean.setObjectName("SWSimPropMean")
                mean.addItems(list(MEAN_CORRECTION))
                mean.setCurrentText(v["mean"])
                kf = QtWidgets.QDoubleSpinBox()
                kf.setObjectName("SWSimPropKf")
                kf.setRange(0.01, 100.0)
                kf.setDecimals(3)
                kf.setValue(v["kf"])
                inf = QtWidgets.QDoubleSpinBox()
                inf.setObjectName("SWSimPropInfinite")
                inf.setRange(1.0, 1e12)
                inf.setDecimals(0)
                inf.setValue(v["infinite"])
                inf.setSuffix(" cycles")
                form.addRow("Computing alternating stress using:", alt)
                form.addRow("Mean stress correction:", mean)
                form.addRow("Fatigue strength reduction factor (Kf):", kf)
                form.addRow("Infinite life:", inf)
                self.w.update(alternating=alt, mean=mean, kf=kf, infinite=inf)
            self.form = [box] + list(getattr(self, "extra_boxes", []))

        def _models(self, *_a):
            on = self.w["model"].currentText() == NL_MODELS[1]      # plasticity fields only for that model
            curve = getattr(self, "use_curve", None)
            if curve is not None:
                curve.setVisible(on and self.has_curve)
            by_curve = curve is not None and on and self.has_curve and curve.isChecked()
            for w, label in self.nl_rows:
                show = on and not (by_curve and w is self.w.get("tangent"))
                w.setVisible(show)
                if label is not None:
                    label.setVisible(show)

        def _enable(self, *_a):
            for name in ("total", "increment"):              # Transient only (shown, not greyed)
                _row_visible(self.w[name], self.transient.isChecked())

        def values(self):
            out = {}
            for name, w in self.w.items():
                out[name] = w.currentText() if isinstance(w, QtWidgets.QComboBox) else w.value()
            if self.k == "frequency":
                out["upper"] = self.w["upper"].value() if self.upper_on.isChecked() else None
            if self.k == "thermomech":
                out["steady"] = self.steady.isChecked()
            if self.k == "nonlinear":
                out["large"] = self.large.isChecked()
                out["curve"] = bool(self.has_curve and self.use_curve.isChecked())
            return out

        def apply(self):
            set_properties(self.a, **self.values())
            return self.a

    def open_properties(a):
        k = study_type(a)
        from . import simstudy
        if k in ("frequency", "buckling") and hasattr(simstudy, "open_modal_properties"):
            return simstudy.open_modal_properties(a)
        if k in ("frequency", "buckling", "thermomech", "fatigue", "nonlinear"):
            return _show(PropertiesPM(a))
        if k == "drop":
            return open_result_options(a)
        if k == "lineardynamic":
            from . import simdynamic
            return simdynamic.open_properties(a)
        if k == "pressure":
            from . import simpressure
            return simpressure.open_setup(a)
        from . import simstudy
        if k in ("static", "check", None, "") and hasattr(simstudy, "open_static_properties"):
            return simstudy.open_static_properties(a)
        return _show(simstudy.PropsPanel(a))

    # ------------------------------------------------------------------- Thermal Loads
    class ThermalPM(simpms._PM):
        """Temperature (or Initial temperature), Convection, Heat Flux, Heat Power, Radiation."""

        def __init__(self, doc, kind="Temperature", edit=None):
            super().__init__(doc, edit)
            self.PM = kind
            k = simpms.kept(edit) if edit is not None else {}
            self.kind = kind
            msg = sx._box("Message", None, kind)
            words = {"Temperature": "Pick the faces that have the temperature.",
                     "Convection": "Pick the faces that lose (or take) heat to the surrounding fluid.",
                     "Heat Flux": "Pick the faces the heat flux goes through.",
                     "Heat Power": "The power made inside the part (CalculiX spreads it over the whole part).",
                     "Radiation": "Pick the faces that radiate to the surroundings."}[kind]
            QtWidgets.QVBoxLayout(msg).addWidget(QtWidgets.QLabel(words))
            box = sx._box({"Temperature": "Temperature", "Convection": "Convection Parameters", "Heat Flux": "Heat Flux",
                           "Heat Power": "Heat Power", "Radiation": "Radiation Parameters"}[kind])
            form = QtWidgets.QFormLayout(box)
            self.faces = sx._PickList("SWSimThermalFaces")
            self.boxes = [self.faces]
            self.w = {}

            def num(name, label, lo, hi, val, suffix="", dec=3):
                sp = QtWidgets.QDoubleSpinBox()
                sp.setObjectName("SWSimThermal" + name.title())
                sp.setRange(lo, hi)
                sp.setDecimals(dec)
                sp.setValue(val)
                if suffix:
                    sp.setSuffix(" " + suffix)
                form.addRow(label, sp)
                self.w[name] = sp
                return sp

            def units(name="unit", label="Units:"):
                c = QtWidgets.QComboBox()
                c.setObjectName("SWSimThermalUnit")
                c.addItems(list(TEMP_UNITS))
                c.setCurrentText(k.get(name, "Kelvin"))
                form.addRow(label, c)
                self.w[name] = c
                return c
            if kind != "Heat Power":
                form.addRow(self.faces)
            self.static = kind == "Temperature" and (k.get("static") or study_type(simpms.active_study(doc)) in STATIC_TEMPERATURE)
            if self.static:          # a static study's External Loads > Temperature (no faces: the whole part)
                self.initial = QtWidgets.QCheckBox()
                units()
                num("value", "Temperature:", -1e6, 1e6, k.get("value", 350.0))
                units("ref_unit", "Reference units:")
                self.w["ref_unit"].setCurrentText(k.get("ref_unit", "Kelvin"))
                num("reference", "Reference temperature at zero strain:", -1e6, 1e6, k.get("reference", 298.0))
            elif kind == "Temperature":
                self.initial = QtWidgets.QCheckBox("Initial temperature")
                self.initial.setToolTip("The temperature of the whole part when the study starts")
                self.initial.setObjectName("SWSimThermalInitial")
                self.initial.setChecked(bool(k.get("initial")))
                self.initial.toggled.connect(lambda on: self.faces.setVisible(not on))
                form.addRow(self.initial)
                units()
                num("value", "Temperature:", -1e6, 1e6, k.get("value", 300.0))
            elif kind == "Convection":
                num("coefficient", "Convection coefficient:", 0.0, 1e9, k.get("coefficient", 25.0), "W/(m^2.K)")
                units()
                num("ambient", "Bulk ambient temperature:", -1e6, 1e6, k.get("ambient", 300.0))
            elif kind == "Heat Flux":
                num("flux", "Heat flux:", 0.0, 1e12, k.get("flux", 1000.0), "W/m^2")
                self.reverse = QtWidgets.QCheckBox("Reverse direction")
                self.reverse.setToolTip("The heat flows out of the faces")
                self.reverse.setChecked(bool(k.get("reverse")))
                form.addRow(self.reverse)
            elif kind == "Heat Power":
                num("power", "Heat power:", -1e9, 1e9, k.get("power", 10.0), "W")
            else:
                num("emissivity", "Emissivity:", 0.0, 1.0, k.get("emissivity", 0.8))
                units()
                num("ambient", "Ambient temperature:", -1e6, 1e6, k.get("ambient", 300.0))
            self.form = [msg, box]
            if edit is not None:
                for _o, subs in getattr(edit, "References", []) or []:
                    if kind != "Heat Power":
                        self.faces.addItems([s for s in subs if s.startswith("Face")])
            if kind == "Temperature" and not self.static:
                self.faces.setVisible(not self.initial.isChecked())
            self._start()

        def apply(self):
            v = {n: (w.currentText() if isinstance(w, QtWidgets.QComboBox) else w.value()) for n, w in self.w.items()}
            if self.kind == "Temperature" and self.static:
                return add_static_temperature(self.doc, self.a, self.obj, self.faces.values(), v["value"], v["unit"],
                                              v["reference"], v["ref_unit"], self.edit)
            if self.kind == "Temperature":
                return add_temperature(self.doc, self.a, self.obj, self.faces.values(), v["value"], v["unit"],
                                       self.initial.isChecked(), self.edit)
            if self.kind == "Heat Power":
                return add_heat_power(self.doc, self.a, self.obj, v["power"], self.edit)
            if self.kind == "Heat Flux":
                v["reverse"] = self.reverse.isChecked()
            return add_heatflux(self.doc, self.a, self.obj, self.faces.values(), self.kind, self.edit, **v)

    # ------------------------------------------------------------------- Fatigue
    class EventPM(_Panel):
        """Add Event: Cycles, Loading type, Study Association (study, scale factor)."""
        PM = "Add Event"

        def __init__(self, a, edit=None):
            super().__init__(a.Document)
            self.a, self.edit = a, edit
            v = event_values(edit) if edit is not None else {}
            box = sx._box("Information", None, "Add Event")
            form = QtWidgets.QFormLayout(box)
            self.cycles = QtWidgets.QSpinBox()
            self.cycles.setObjectName("SWSimEventCycles")
            self.cycles.setRange(1, 2000000000)
            self.cycles.setValue(int(v.get("cycles", 1000)))
            self.loading = QtWidgets.QComboBox()
            self.loading.setObjectName("SWSimEventLoading")
            self.loading.addItems(list(LOADING))
            self.loading.setCurrentText(v.get("loading", LOADING[0]))
            self.ratio = QtWidgets.QDoubleSpinBox()
            self.ratio.setObjectName("SWSimEventRatio")
            self.ratio.setRange(-1e6, 1.0)
            self.ratio.setDecimals(3)
            self.ratio.setValue(float(v.get("ratio", -1.0)))
            form.addRow("Cycles:", self.cycles)
            form.addRow("Loading type:", self.loading)
            form.addRow("Loading ratio:", self.ratio)
            self.ratio_label = form.labelForField(self.ratio)
            assoc = sx._box("Study Association")
            al = QtWidgets.QFormLayout(assoc)
            self.study = QtWidgets.QComboBox()
            self.study.setObjectName("SWSimEventStudy")
            self.studies = [o for o in a.Document.Objects if o.TypeId == "Fem::FemAnalysis" and o is not a
                            and study_type(o) == "static"]
            self.study.addItems([o.Label for o in self.studies])
            if v.get("study"):
                names = [o.Name for o in self.studies]
                if v["study"] in names:
                    self.study.setCurrentIndex(names.index(v["study"]))
            self.scale = QtWidgets.QDoubleSpinBox()
            self.scale.setObjectName("SWSimEventScale")
            self.scale.setRange(-1e6, 1e6)
            self.scale.setDecimals(3)
            self.scale.setValue(float(v.get("scale", 1.0)))
            al.addRow("Study:", self.study)
            al.addRow("Scale factor:", self.scale)
            self.form = [box, assoc]
            self.loading.currentTextChanged.connect(self._enable)
            self._enable()

        def _enable(self, *_a):
            on = self.loading.currentText() == LOADING[2]
            self.ratio.setVisible(on)
            if self.ratio_label is not None:
                self.ratio_label.setVisible(on)

        def apply(self):
            st = self.studies[self.study.currentIndex()] if self.studies and self.study.currentIndex() >= 0 else None
            return add_event(self.a, self.cycles.value(), self.loading.currentText(), self.ratio.value(), st,
                             self.scale.value(), self.edit)

    def open_event(a, o=None):
        return _show(EventPM(a, o))

    class FatigueDataPM(_Panel):
        """Apply/Edit Fatigue Data: the S-N curve, estimated from the ultimate strength or typed in (cycles, stress)."""
        PM = "Fatigue Data"

        def __init__(self, a):
            super().__init__(a.Document)
            self.a = a
            c = sn_curve(a)
            box = sx._box("S-N Curve", None, "Material")
            lay = QtWidgets.QVBoxLayout(box)
            self.est = QtWidgets.QRadioButton("Estimate from the ultimate strength")
            self.est.setObjectName("SWSimSNEstimate")
            self.tab = QtWidgets.QRadioButton("Use the tabulated points")
            self.tab.setObjectName("SWSimSNTable")
            lay.addWidget(QtWidgets.QLabel("Material: %s   Ultimate strength: %s" % (
                c.get("material") or "?", ("%.4g MPa" % c["su"]) if c.get("su") else "unknown")))
            lay.addWidget(self.est)
            lay.addWidget(self.tab)
            self.table = QtWidgets.QTableWidget(8, 2)
            self.table.setObjectName("SWSimSNPoints")
            self.table.setHorizontalHeaderLabels(["Cycles (N)", "Alternating stress (MPa)"])
            for r, (n, s) in enumerate(c.get("points", [])[:8]):
                self.table.setItem(r, 0, QtWidgets.QTableWidgetItem("%g" % n))
                self.table.setItem(r, 1, QtWidgets.QTableWidgetItem("%g" % s))
            lay.addWidget(self.table)
            lay.addWidget(QtWidgets.QLabel("Interpolate: Log-log"))
            (self.tab if c.get("source") == "Tabulated" else self.est).setChecked(True)
            self.est.toggled.connect(lambda on: self.table.setVisible(not on))     # the points only for Tabulated
            self.table.setVisible(self.tab.isChecked())
            self.form = [box]

        def points(self):
            pts = []
            for r in range(self.table.rowCount()):
                a_, b_ = self.table.item(r, 0), self.table.item(r, 1)
                if a_ and b_ and a_.text().strip() and b_.text().strip():
                    try:
                        pts.append((float(a_.text()), float(b_.text())))
                    except ValueError:
                        raise simpms.SetupError("Row %d: cycles and stress are numbers." % (r + 1))
            return pts

        def apply(self):
            set_sn_curve(self.a, "Tabulated" if self.tab.isChecked() else "Estimated", self.points())
            return self.a

    def open_fatigue_data(a):
        return _show(FatigueDataPM(a))

    # ------------------------------------------------------------------- Drop Test
    class DropSetupPM(_Panel):
        """Drop Test Setup: Drop height (From centroid / From lowest point) or Velocity at impact; Gravity."""
        PM = "Drop Test Setup"

        def __init__(self, a):
            super().__init__(a.Document)
            self.a = a
            v = drop_values(a)
            box = sx._box("Specify", None, "Drop Test Setup")
            form = QtWidgets.QFormLayout(box)
            self.height_on = QtWidgets.QRadioButton("Drop height")
            self.height_on.setObjectName("SWSimDropHeightOn")
            self.vel_on = QtWidgets.QRadioButton("Velocity at impact")
            self.vel_on.setObjectName("SWSimDropVelocityOn")
            (self.height_on if v["type"] == "Drop height" else self.vel_on).setChecked(True)
            form.addRow(self.height_on)
            form.addRow(self.vel_on)
            hb = sx._box("Height")
            hl = QtWidgets.QFormLayout(hb)
            self.frm = QtWidgets.QComboBox()
            self.frm.setObjectName("SWSimDropFrom")
            self.frm.addItems(["From centroid", "From lowest point"])
            self.frm.setCurrentText(v["from"])
            self.height = QtWidgets.QDoubleSpinBox()
            self.height.setObjectName("SWSimDropHeight")
            self.height.setRange(0.0, 1e9)
            self.height.setDecimals(3)
            self.height.setValue(float(v["height"]))
            self.height.setSuffix(" mm")
            hl.addRow(self.frm)
            hl.addRow("Height:", self.height)
            self.velocity = QtWidgets.QDoubleSpinBox()
            self.velocity.setObjectName("SWSimDropVelocity")
            self.velocity.setRange(0.0, 1e9)
            self.velocity.setDecimals(3)
            self.velocity.setValue(float(v["velocity"]) / 1000.0)
            self.velocity.setSuffix(" m/s")
            hl.addRow("Velocity:", self.velocity)
            gb = sx._box("Gravity")
            gl = QtWidgets.QFormLayout(gb)
            self.gravity = QtWidgets.QDoubleSpinBox()
            self.gravity.setObjectName("SWSimDropGravity")
            self.gravity.setRange(0.0, 1e6)
            self.gravity.setDecimals(3)
            self.gravity.setValue(float(v["gravity"]))
            self.gravity.setSuffix(" m/s^2")
            gl.addRow("Gravity:", self.gravity)

            self.gref = sx._PickList("SWSimDropGravityRef")
            self.gref.setFixedHeight(26)
            self.gref.setToolTip("Pick a plane, a flat face or a straight edge: gravity acts along it")
            if v.get("gravity_ref"):
                self.gref.addItem(v["gravity_ref"])
            self.reverse = QtWidgets.QCheckBox("Reverse direction")
            self.reverse.setObjectName("SWSimDropReverse")
            self.reverse.setChecked(bool(v.get("reverse")))
            self.dir_note = QtWidgets.QLabel()
            self.dir_note.setObjectName("SWSimDropDirectionNote")
            self.direction = list(v["direction"])
            gl.addRow("Reference:", self.gref)
            gl.addRow(self.reverse)
            gl.addRow(self.dir_note)
            tb = sx._box("Target")
            tl = QtWidgets.QFormLayout(tb)
            self.normal_on = QtWidgets.QRadioButton("Normal to gravity")
            self.normal_on.setObjectName("SWSimDropTargetNormal")
            self.plane_on = QtWidgets.QRadioButton("Parallel to plane")
            self.plane_on.setObjectName("SWSimDropTargetParallel")
            (self.plane_on if v.get("orientation") == TARGET_ORIENTATIONS[1] else self.normal_on).setChecked(True)
            self.plane = sx._PickList("SWSimDropTargetPlane")
            self.plane.setFixedHeight(26)
            self.plane.setToolTip("Pick the plane or flat face the target is parallel to")
            if v.get("plane"):
                self.plane.addItem(v["plane"])
            self.rigid_on = QtWidgets.QRadioButton("Rigid target")
            self.rigid_on.setObjectName("SWSimDropRigid")
            self.flex_on = QtWidgets.QRadioButton("Flexible target")
            self.flex_on.setObjectName("SWSimDropFlexible")
            (self.flex_on if v.get("target") == TARGET_KINDS[1] else self.rigid_on).setChecked(True)
            self.stiff = QtWidgets.QDoubleSpinBox()
            self.stiff.setObjectName("SWSimDropStiffness")
            self.stiff.setRange(1.0, 1e18)
            self.stiff.setDecimals(0)
            self.stiff.setValue(float(v.get("stiffness", 1e12)))
            self.stiff.setSuffix(" N/m^3")
            orient = QtWidgets.QButtonGroup(tb)
            orient.addButton(self.normal_on)
            orient.addButton(self.plane_on)
            kind = QtWidgets.QButtonGroup(tb)
            kind.addButton(self.rigid_on)
            kind.addButton(self.flex_on)
            self._groups = (orient, kind)
            tl.addRow("Target orientation:", self.normal_on)
            tl.addRow("", self.plane_on)
            tl.addRow("Plane:", self.plane)
            tl.addRow("Target stiffness:", self.rigid_on)
            tl.addRow("", self.flex_on)
            tl.addRow("Normal stiffness per unit area:", self.stiff)
            self.form = [box, hb, gb, tb]
            self.height_on.toggled.connect(self._enable)
            self.plane_on.toggled.connect(self._enable)
            self.flex_on.toggled.connect(self._enable)
            self.reverse.toggled.connect(self._direction)
            self.boxes = [self.gref, self.plane]
            for b in self.boxes:
                b.activated_box.connect(self._activate)
            self.current = None
            self._activate(self.gref)
            self._enable()
            self._direction()
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def _activate(self, box):
            self.current = box
            for b in self.boxes:
                b.active(b is box)

        def addSelection(self, doc, name, sub, pnt):
            if doc != self.doc.Name or self.current is None:
                return
            last = (sub or "").split(".")[-1]
            ref = "%s:%s" % (name, last) if last else name
            QtCore.QTimer.singleShot(0, lambda: self._picked(ref))

        def _picked(self, ref):
            try:
                box = self.current
                box.clear()
                box.addItem(ref)
                Gui.Selection.clearSelection()
                if box is self.gref:
                    self._direction()
            except RuntimeError:
                Gui.Selection.removeObserver(self)

        def _direction(self, *_a):
            refs = self.gref.values()
            d = direction_of(self.doc, refs[0]) if refs else None
            if refs and d is None:
                self.dir_note.setText("Pick a plane, a flat face or a straight edge")
                return
            if d is not None:
                d = d * (-1.0 if self.reverse.isChecked() else 1.0)
                self.direction = [d.x, d.y, d.z]
            x, y, z = self.direction
            self.dir_note.setText("Direction: (%.3g, %.3g, %.3g)" % (x, y, z))

        def _enable(self, *_a):
            on = self.height_on.isChecked()
            _row_visible(self.frm, on)
            _row_visible(self.height, on)
            _row_visible(self.velocity, not on)
            _row_visible(self.plane, self.plane_on.isChecked())
            _row_visible(self.stiff, self.flex_on.isChecked())

        def _close(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("simtypes.py:drop observer", _fw_err)

        def reject(self):
            self._close()
            return super().reject()

        def accept(self):
            ok = super().accept()
            if ok:
                self._close()
            return ok

        def apply(self):
            refs, planes = self.gref.values(), self.plane.values()
            return set_drop(self.a, type="Drop height" if self.height_on.isChecked() else "Velocity at impact",
                            **{"from": self.frm.currentText(), "height": self.height.value(),
                               "velocity": self.velocity.value() * 1000.0, "gravity": self.gravity.value(),
                               "direction": list(self.direction), "gravity_ref": refs[0] if refs else "",
                               "reverse": self.reverse.isChecked(),
                               "orientation": TARGET_ORIENTATIONS[1 if self.plane_on.isChecked() else 0],
                               "plane": planes[0] if planes else "",
                               "target": TARGET_KINDS[1 if self.flex_on.isChecked() else 0],
                               "stiffness": self.stiff.value()})

    def open_drop_setup(a):
        return _show(DropSetupPM(a))

    class ResultOptionsPM(_Panel):
        """Drop Test Result Options: Solution time after impact, number of plots."""
        PM = "Result Options"

        def __init__(self, a):
            super().__init__(a.Document)
            self.a = a
            v = drop_values(a)
            box = sx._box("Solution Time", None, "Result Options")
            form = QtWidgets.QFormLayout(box)
            self.auto = QtWidgets.QCheckBox("Automatic")
            self.auto.setToolTip("Four times the time a stress wave takes to cross the part")
            self.auto.setObjectName("SWSimDropAuto")
            self.auto.setChecked(not float(v.get("time") or 0.0))
            self.time = QtWidgets.QDoubleSpinBox()
            self.time.setObjectName("SWSimDropTime")
            self.time.setRange(0.0, 1e9)
            self.time.setDecimals(3)
            self.time.setSuffix(" microsec")
            self.time.setValue(float(v.get("time") or solution_time(a, _shape(a)) * 1e6))
            form.addRow(self.auto)
            form.addRow("Solution time after impact:", self.time)
            sb = sx._box("Save Results")
            sl = QtWidgets.QFormLayout(sb)
            self.plots = QtWidgets.QSpinBox()
            self.plots.setObjectName("SWSimDropPlots")
            self.plots.setRange(1, 200)
            self.plots.setValue(int(v["plots"]))
            sl.addRow("No. of plots:", self.plots)
            self.form = [box, sb]
            self.auto.toggled.connect(lambda on: _row_visible(self.time, not on))
            _row_visible(self.time, not self.auto.isChecked())

        def apply(self):
            return set_drop(self.a, time=0.0 if self.auto.isChecked() else self.time.value(), plots=self.plots.value())

    def open_result_options(a):
        return _show(ResultOptionsPM(a))

    # ------------------------------------------------------------------- lists
    class ListDialog(QtWidgets.QDialog):
        """List Resonant Frequencies / List Mass Participation / List Buckling Factors, with Save (CSV)."""

        def __init__(self, a, what):
            super().__init__(Gui.getMainWindow())
            self.setObjectName("SWSimList")
            self.what = what
            if what == "frequencies":
                self.setWindowTitle("List Modes")
                head = ["Mode No.", "Frequency(Rad/sec)", "Frequency(Hertz)", "Period(Seconds)"]
                rows = [["%d" % n, "%.5g" % r, "%.5g" % h, "%.5g" % p] for n, r, h, p in frequencies(a)]
            elif what == "mass":
                self.setWindowTitle("Mass Participation (Normalized)")
                head = ["Mode Number", "Freq(Hertz)", "X direction", "Y direction", "Z direction"]
                data = mass_participation(a)
                rows = [["%d" % n, "%.5g" % h, "%.4g" % x, "%.4g" % y, "%.4g" % z] for n, h, x, y, z in data]
                if data:
                    rows.append(["", "", "Sum X = %.4g" % sum(r[2] for r in data), "Sum Y = %.4g" % sum(r[3] for r in data),
                                 "Sum Z = %.4g" % sum(r[4] for r in data)])
            else:
                self.setWindowTitle("List Buckling Factors")
                head = ["Mode No.", "Load Factor"]
                rows = [["%d" % n, "%.5g" % v] for n, _r, v in modes(a)]
            self.head, self.rows = head, rows
            lay = QtWidgets.QVBoxLayout(self)
            lay.addWidget(QtWidgets.QLabel("Study name: %s" % a.Label))
            self.table = QtWidgets.QTableWidget(len(rows), len(head))
            self.table.setObjectName("SWSimListTable")
            self.table.setHorizontalHeaderLabels(head)
            self.table.verticalHeader().hide()
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            for r, row in enumerate(rows):
                for c, text in enumerate(row):
                    self.table.setItem(r, c, QtWidgets.QTableWidgetItem(text))
            self.table.resizeColumnsToContents()
            lay.addWidget(self.table)
            bb = QtWidgets.QHBoxLayout()
            self.save_btn = QtWidgets.QPushButton("Save")
            self.save_btn.setObjectName("SWSimListSave")
            self.save_btn.clicked.connect(lambda: self.save())
            close = QtWidgets.QPushButton("Close")
            close.clicked.connect(self.accept)
            bb.addStretch(1)
            bb.addWidget(self.save_btn)
            bb.addWidget(close)
            lay.addLayout(bb)
            self.resize(520, 300)

        def save(self, path=None):
            import csv
            if not path:
                path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save", "%s.csv" % self.windowTitle(), "CSV (*.csv)")
            if not path:
                return None
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(self.head)
                w.writerows(self.rows)
            return path

    LISTS = []

    def list_dialog(a, what):
        d = ListDialog(a, what)
        del LISTS[:]
        LISTS.append(d)
        d.show()
        return d

    # ------------------------------------------------------------------- commands
    def _study():
        doc = App.ActiveDocument
        return simpms.active_study(doc) if doc is not None else None

    class _Cmd:
        def __init__(self, text, tip, run, pixmap, need=None):
            self.text, self.tip, self.run, self.pixmap, self.need = text, tip, run, pixmap, need

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": _pixmap(self.pixmap)}

        def IsActive(self):
            if App.ActiveDocument is None or Gui.Control.activeDialog():
                return False
            if self.need is None:
                return True
            a = _study()
            return a is not None and study_type(a) in self.need

        def Activated(self):
            try:
                self.run()
            except simpms.SetupError as e:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.text, str(e))

    def _pixmap(key):
        try:
            from . import simicons
            return simicons.svg(key) or key
        except Exception:
            return key

    def _new_study():
        from . import addintabs
        addintabs.load("FEM")
        _show(NewStudyPM(App.ActiveDocument))

    def _thermal_cmd(kind):
        def run():
            _show(ThermalPM(App.ActiveDocument, kind))
        return run

    def _with_study(fn):
        def run():
            a = _study()
            if a is None:
                raise simpms.SetupError("Make a study first (Simulation > New Study).")
            return fn(a)
        return run

    THERMAL = ("thermomech",)
    COMMANDS = {
        "SWStyle_SimNewStudyPM": _Cmd("New Study", "Starts a study: Static, Thermal, Frequency, Buckling, Fatigue, Drop Test "
                                      "or Design Study.", _new_study, "SIM_NewStudy"),
        "SWStyle_SimTemperature": _Cmd("Temperature", "A temperature on faces, or the part's initial temperature.",
                                       _thermal_cmd("Temperature"), "SIM_Temperature", THERMAL + STATIC_TEMPERATURE),
        "SWStyle_SimConvection": _Cmd("Convection", "Heat lost to (or taken from) a surrounding fluid.",
                                      _thermal_cmd("Convection"), "SIM_Convection", THERMAL),
        "SWStyle_SimHeatFlux": _Cmd("Heat Flux", "Heat flowing through faces (W/m^2).", _thermal_cmd("Heat Flux"),
                                    "SIM_HeatFlux", THERMAL),
        "SWStyle_SimHeatPower": _Cmd("Heat Power", "Heat made inside the part (W).", _thermal_cmd("Heat Power"),
                                     "SIM_BodyHeat", THERMAL),
        "SWStyle_SimRadiation": _Cmd("Radiation", "Heat radiated from faces to the surroundings.", _thermal_cmd("Radiation"),
                                     "SIM_Radiation", THERMAL),
        "SWStyle_SimAddEvent": _Cmd("Add Event", "A fatigue event: cycles, loading type and the static study it repeats.",
                                    _with_study(open_event), "SIM_FatigueEvent", ("fatigue",)),
        "SWStyle_SimStudyPropsPM": _Cmd("Study Properties", "The options of the active study's type: frequencies, buckling "
                                        "modes, steady state or transient, fatigue options, drop test result options.",
                                        lambda: _props_cmd(), "SIM_Props"),
        "SWStyle_SimDropSetup": _Cmd("Drop Test Setup", "Drop height or velocity at impact, and gravity.",
                                     _with_study(open_drop_setup), "SIM_DropTest", ("drop",)),
        "SWStyle_SimBaseExcitation": _Cmd("Uniform Base Excitation", "The fixtures shaken together along X, Y or Z: the "
                                          "acceleration PSD (Random Vibration) or spectrum (Response Spectrum).",
                                          _with_study(open_properties), "SIM_BaseExcitation", ("lineardynamic",)),
    }

# key, label, natives, tip, caption (they replace addintabs' keys of the same name)
KEYS = (
    ("SIM_NewStudy", "New Study", ("SWStyle_SimNewStudyPM", "SWStyle_SimNewStudy", "FEM_Analysis"),
     "Starts a study: Static, Thermal, Frequency, Buckling, Fatigue, Drop Test or Design Study.", "New\nStudy"),
    ("SIM_Props", "Study Properties", ("SWStyle_SimStudyPropsPM", "SWStyle_SimStudyProps"),
     "The options of the active study's type.", None),
    ("SIM_Temperature", "Temperature", ("SWStyle_SimTemperature", "FEM_ConstraintTemperature"),
     "A temperature on faces, or the part's initial temperature.", None),
    ("SIM_Convection", "Convection", ("SWStyle_SimConvection", "FEM_ConstraintHeatflux"),
     "Heat lost to (or taken from) a surrounding fluid.", None),
    ("SIM_HeatFlux", "Heat Flux", ("SWStyle_SimHeatFlux", "FEM_ConstraintHeatflux"), "Heat flowing through faces.", None),
    ("SIM_BodyHeat", "Heat Power", ("SWStyle_SimHeatPower", "FEM_ConstraintBodyHeatSource"), "Heat made inside the part.", None),
    ("SIM_Radiation", "Radiation", ("SWStyle_SimRadiation", "FEM_ConstraintHeatflux"),
     "Heat radiated from faces to the surroundings.", None),
    ("SIM_InitialTemp", "Initial Temperature", ("SWStyle_SimTemperature", "FEM_ConstraintInitialTemperature"),
     "The temperature the part starts from (Temperature PM, Initial temperature).", None),

    ("SIM_BaseExcitation", "Uniform Base Excitation", ("SWStyle_SimBaseExcitation",),
     "The fixtures shaken together: Random Vibration's acceleration PSD, Response Spectrum's acceleration spectrum.", None),
    ("SIM_ThermalLoads", "Thermal Loads", ("SWStyle_SimTemperature", "FEM_ConstraintTemperature"),
     "Temperature, convection, heat flux, heat power and radiation for the thermal study.", "Thermal\nLoads"),
)


def _props_cmd():
    from . import simstudy
    a = simstudy._analysis()
    if a is None:
        return simstudy._props()
    return open_properties(a)


def _patch_props():
    """Study Properties opens the type's PM."""
    from . import simstudy
    if getattr(simstudy, "_fw_types_props", False):
        return
    props0 = simstudy._props

    def _props():
        a = simstudy._analysis()
        if a is not None and study_type(a) not in ("static", "check"):
            return open_properties(a)
        return props0()
    simstudy._props = _props
    simstudy._fw_types_props = True


def install():
    install_core()
    if Gui is None:
        return
    from . import catalog
    have = set(Gui.listCommands())
    for name, cmd in COMMANDS.items():
        if name not in have:
            Gui.addCommand(name, cmd)
    for key, label, natives, tip, caption in KEYS:
        icon = None
        try:
            from . import simicons
            icon = simicons.svg(key) or (simicons.svg("SIM_Temperature") if key == "SIM_ThermalLoads" else None)
        except Exception as _fw_err:
            _fw_log("simtypes.py:icon", _fw_err)
        old = catalog.BY_KEY.get(key)
        if old is None:
            catalog.BY_KEY[key] = catalog.c(key, label, natives, icon, tip, caption=caption)
        else:                                  # ours first, FreeCAD's own after; the key keeps its picture
            old.label, old.natives, old.tip = label, tuple(natives), tip
            if caption:
                old.caption = caption
    _patch_props()
    from . import addintabs
    cls = getattr(addintabs, "SimNewStudy", None)       # the New Study command opens the PM too
    if cls is not None and not getattr(cls, "_fw_pm", False):
        cls.Activated = lambda self: _new_study()
        cls._fw_pm = True


# =========================================================================== Design Study sensors
def _first_material(doc):
    for o in doc.Objects:
        if isinstance(getattr(o, "Material", None), dict) and o.Material.get("Density"):
            return o.Material
    return {}


def _fresh_run(a):
    """Runs study a on the part as it is now: the mesh is made again first."""
    import Fem
    from . import addintabs
    m = _mesh(a)
    if m is not None and getattr(getattr(m, "Proxy", None), "Type", "") == "Fem::FemMeshGmsh":
        m.FemMesh = Fem.FemMesh()
    addintabs.run_study(a)


def design_sensors(doc):
    ""


    from . import evaluate, simplots
    out = []

    def volume(_doc):
        from . import addintabs
        main = addintabs._main_solid(doc)      # the part, shown or hidden under a result plot
        return main.Shape.Volume if main is not None else sum(o.Shape.Volume for o in evaluate.visible_bodies(doc))

    def mass(_doc):
        rho = _q(_first_material(doc), "Density", "kg/mm^3", 7.8e-6)
        return volume(_doc) * rho
    out.append(("Mass (kg)", None, mass))
    out.append(("Volume (mm^3)", None, volume))
    for a in [o for o in doc.Objects if o.TypeId == "Fem::FemAnalysis"]:
        k = study_type(a)

        def last(a=a):
            return simplots.result(a)
        if k == "static":
            out.append(("%s: Max von Mises stress (MPa)" % a.Label, a, lambda d, a=a: max(last(a).vonMises)))
            out.append(("%s: Max displacement (mm)" % a.Label, a, lambda d, a=a: max(last(a).DisplacementLengths)))
        elif k == "frequency":
            out.append(("%s: Frequency 1 (Hz)" % a.Label, a, lambda d, a=a: modes(a)[0][2]))
        elif k == "buckling":
            out.append(("%s: Buckling load factor 1" % a.Label, a, lambda d, a=a: modes(a)[0][2]))
        elif k == "thermomech":
            out.append(("%s: Max temperature (K)" % a.Label, a, lambda d, a=a: max(last(a).Temperature)))
    return out


def measure_sensors(doc, picked):
    """The values of the picked sensors on the part as it is now; each study is run once."""
    done, vals = set(), {}
    for label, study, fn in picked:
        if study is not None and study.Name not in done:
            _fresh_run(study)
            done.add(study.Name)
        vals[label] = fn(doc)
    return vals


def rerun(doc, picked):
    """After the scenarios: the studies run again on the part as it was, so their results match it."""
    done = set()
    for _label, study, _fn in picked:
        if study is not None and study.Name not in done:
            try:
                _fresh_run(study)
            except Exception as _fw_err:
                _fw_log("simtypes.py:rerun", _fw_err)
            done.add(study.Name)


def meets(value, condition, lo, hi=None):
    if condition == "is less than":
        return value < lo
    if condition == "is greater than":
        return value > lo
    return lo <= value <= (hi if hi is not None else lo)


def optimal(rows, constraints, goals):
    ""

    ok = [i for i, r in enumerate(rows) if all(meets(r[c[0]], c[1], c[2], c[3] if len(c) > 3 else None) for c in constraints)]
    if not ok or not goals:
        return None
    score = {i: 0.0 for i in ok}
    for label, how in goals:
        vals = [rows[i][label] for i in ok]
        lo, hi = min(vals), max(vals)
        for i in ok:
            t = (rows[i][label] - lo) / (hi - lo) if hi > lo else 0.0
            score[i] += t if how == "Minimize" else 1.0 - t
    return min(ok, key=lambda i: score[i])
