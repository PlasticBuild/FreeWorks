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


import html
import json
import os
import tempfile
import time

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    Gui = None

SECTIONS = ("Description", "Assumptions", "Model Information", "Study Properties", "Units", "Material Properties",
            "Loads and Fixtures", "Connector Definitions", "Contact Information", "Mesh information", "Study Results",
            "Conclusion")
TEXT_SECTIONS = ("Description", "Assumptions", "Conclusion")
HEADER = ("Designer", "Company", "URL", "Address", "Phone", "Fax")
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SimReport"
OPTIONS = "FwReportOptions"
REPORTS = "FwReports"


# --------------------------------------------------------------------------- options
def _param():
    return App.ParamGet(PARAMS)


def options(a):
    ""
    o = {"sections": {s: True for s in SECTIONS}, "texts": {}, "path": "", "name": "", "show": True}
    try:
        o.update(json.loads(getattr(a, OPTIONS, "") or "{}"))
    except Exception as _fw_err:
        _fw_log("simreport.py:options", _fw_err)
    p = _param()
    o["header"] = {h: p.GetString(h, "") for h in HEADER}
    o["header_on"] = {h: p.GetBool(h + "On", bool(o["header"][h])) for h in HEADER}
    o["logo"] = p.GetString("Logo", "")
    if not o["path"]:
        o["path"] = default_folder(a.Document)
    if not o["name"]:
        o["name"] = next_name(a)
    return o


def save_options(a, o):
    keep = {k: o[k] for k in ("sections", "texts", "path", "show") if k in o}
    if OPTIONS not in a.PropertiesList:
        a.addProperty("App::PropertyString", OPTIONS, "Report", "Report Options (JSON)")
        a.setPropertyStatus(OPTIONS, "Hidden")
    setattr(a, OPTIONS, json.dumps(keep, sort_keys=True))
    p = _param()
    for h in HEADER:
        p.SetString(h, o.get("header", {}).get(h, ""))
        p.SetBool(h + "On", bool(o.get("header_on", {}).get(h, False)))
    p.SetString("Logo", o.get("logo", ""))


def default_folder(doc):
    ""
    if doc.FileName:
        return os.path.dirname(doc.FileName)
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return docs if os.path.isdir(docs) else tempfile.gettempdir()


def reports(a):
    return list(getattr(a, REPORTS, []) or [])


def next_name(a):
    ""
    base = "%s-%s-" % (a.Document.Label or a.Document.Name, a.Label)
    used = {os.path.splitext(os.path.basename(r))[0] for r in reports(a)}
    n = 1
    while "%s%d" % (base, n) in used:
        n += 1
    return "%s%d" % (base, n)


def _remember(a, path):
    if REPORTS not in a.PropertiesList:
        a.addProperty("App::PropertyStringList", REPORTS, "Report", "Published reports")
        a.setPropertyStatus(REPORTS, "Hidden")
    rs = [r for r in reports(a) if r != path] + [path]
    setattr(a, REPORTS, rs)


def forget(a, path):
    if REPORTS in a.PropertiesList:
        setattr(a, REPORTS, [r for r in reports(a) if r != path])


# --------------------------------------------------------------------------- the report's data
def _q(text, unit):
    try:
        return App.Units.Quantity(text).getValueAs(unit).Value
    except Exception:
        return None


def _shape_of(a):
    try:
        from . import simtree
        solids = simtree._solids(a)
        return solids
    except Exception:
        return []


def _refs(o):
    out = []
    for obj, subs in (getattr(o, "References", []) or []):
        out.append("%s %s" % (obj.Label, ", ".join(subs)) if subs else obj.Label)
    return "; ".join(out)


def _kept(o):
    try:
        from . import simpms
        return simpms.kept(o)
    except Exception:
        return {}


# the PM's kept kind -> the report's word (PM pkg356 / 359 / 360)
PM_KINDS = {"Torque": "Torque", "Bearing Load": "Bearing Load", "Distributed Mass": "Distributed Mass",
            "Remote Load": "Remote Load/Mass", "Centrifugal": "Centrifugal", "Pressure": "Pressure"}


def _pm_value(k):
    """The value as typed in the PM, for the loads that ride on another FEM object."""
    kind = k.get("kind")
    if kind == "Remote Load":
        f, m = k.get("force") or (), k.get("moment") or ()
        parts = []
        if any(f):
            parts.append("force (%s) %s" % (", ".join("%.6g" % x for x in f), k.get("force_unit", "N")))
        if any(m):
            parts.append("moment (%s) %s" % (", ".join("%.6g" % x for x in m), k.get("moment_unit", "N.m")))
        if k.get("mass"):
            parts.append("mass %.6g %s" % (k["mass"], k.get("mass_unit", "kg")))
        loc = k.get("location")
        if loc:
            parts.append("at (%s) %s" % (", ".join("%.6g" % x for x in loc), k.get("unit", "mm")))
        return ", ".join(parts)
    if kind in PM_KINDS and k.get("value") is not None and kind != "Pressure":
        return "%.6g %s%s" % (float(k["value"]), k.get("unit", ""), " (reversed)" if k.get("reverse") else "")
    return ""


def _name(o):
    """The row's name in its study (Fixed-1 in every study, as the study tree shows it)."""
    try:
        from . import simpms
        return simpms.study_name(o)
    except Exception:
        return o.Label


def _row_kind(o):
    t = o.TypeId
    k = _kept(o)
    if k.get("thermal"):                       # our Temperature, Convection, Heat Flux, Heat Power, Radiation PMs
        return "Initial Temperature" if k.get("initial") else k["thermal"]
    if t == "Fem::ConstraintInitialTemperature":
        return "Initial Temperature"
    if k.get("kind") in PM_KINDS:              # what the PM made (a Torque is a FEM force underneath, ...)
        return PM_KINDS[k["kind"]]
    if k.get("kind") and t in ("Fem::ConstraintFixed", "Fem::ConstraintDisplacement", "Fem::ConstraintPlaneRotation",
                               "Fem::ConstraintTie", "Fem::ConstraintTransform"):
        return k["kind"]                         # the Fixture PM's types (Fixed Geometry, Roller/Slider, Symmetry, ...)
    words = {"Fem::ConstraintFixed": "Fixed Geometry", "Fem::ConstraintDisplacement": "Fixture", "Fem::ConstraintForce": "Force",
             "Fem::ConstraintPressure": "Pressure", "Fem::ConstraintSelfWeight": "Gravity", "Fem::ConstraintBearing": "Bearing Load",
             "Fem::ConstraintCentrif": "Centrifugal", "Fem::ConstraintTemperature": "Temperature",
             "Fem::ConstraintHeatflux": "Heat Flux", "Fem::ConstraintContact": "Contact", "Fem::ConstraintTie": "Bonded",
             "Fem::ConstraintRigidBody": "Rigid Connection", "Fem::ConstraintSpring": "Elastic Support"}
    if t in words:
        return words[t]
    ptype = getattr(getattr(o, "Proxy", None), "Type", "") or ""
    for key, word in (("SelfWeight", "Gravity"), ("Centrif", "Centrifugal"), ("BodyHeatSource", "Heat Power"),
                      ("Tie", "Bonded"), ("Contact", "Contact")):
        if key in ptype or key in t:
            return word
    return t.split("::")[-1].replace("Constraint", "")


def _value(o):
    t = o.TypeId
    try:
        said = _pm_value(_kept(o))
        if said:
            return said
        if t == "Fem::ConstraintForce":
            d = getattr(o, "DirectionVector", None)
            n = o.Force.Value / 1000.0
            try:
                from . import addintabs
                lbf = addintabs._inch_units(o.Document.getObject(o.InList[0].Name) if o.InList else None)
            except Exception:
                lbf = False
            return ("%.6g lbf%s" % (n / 4.4482216, "") if lbf else "%.6g N%s" % (n, "")) + (
                (", direction (%.3g, %.3g, %.3g)" % tuple(v + 0.0 for v in (d.x, d.y, d.z))) if d else "")      # no "-0"
        if t == "Fem::ConstraintPressure":
            return "%s%s" % (o.Pressure.UserString if hasattr(o.Pressure, "UserString") else o.Pressure,
                             " (pulls)" if getattr(o, "Reversed", False) else "")
        if hasattr(o, "GravityAcceleration"):
            g = o.GravityDirection
            return "%s, direction (%.3g, %.3g, %.3g)" % ((o.GravityAcceleration.UserString,) + tuple(v + 0.0 for v in (g.x, g.y, g.z)))
        if t == "Fem::ConstraintFixed":
            return "All translations held"
        if t == "Fem::ConstraintDisplacement":
            free = [ax for ax in "xyz" if getattr(o, ax + "Free", True)]
            return "Free: %s" % (", ".join(free) or "none")
        k = _kept(o)
        if t == "Fem::ConstraintInitialTemperature":
            if k.get("static"):                # a static study's Temperature: the load and its zero-strain reference
                return "%.6g K (reference at zero strain %.6g K)" % (o.FinalTemperature.getValueAs("K").Value,
                                                                     o.initialTemperature.getValueAs("K").Value)
            return "%.6g K" % o.initialTemperature.getValueAs("K").Value
        if t == "Fem::ConstraintTemperature":
            return "%.6g K" % o.Temperature.getValueAs("K").Value
        if t == "Fem::ConstraintHeatflux":
            kind = getattr(o, "ConstraintType", "")
            if kind == "Convection":
                return "Convection coefficient %.6g W/(m^2.K), bulk ambient temperature %.6g K" % (
                    o.FilmCoef.getValueAs("W/m^2/K").Value, o.AmbientTemp.getValueAs("K").Value)
            if kind == "Radiation":
                return "Emissivity %.3g, ambient temperature %.6g K" % (float(o.Emissivity), o.AmbientTemp.getValueAs("K").Value)
            return "%.6g W/m^2" % o.DFlux.getValueAs("W/m^2").Value
        if "TotalPower" in o.PropertiesList:
            return "%.6g W" % o.TotalPower.getValueAs("W").Value
    except Exception as _fw_err:
        _fw_log("simreport.py:value", _fw_err)
    return ""


def _material_study(a):
    ""
    try:
        from . import simtypes
        from . import simpressure
        if simpressure.is_pressure(a):        # a Pressure Vessel Design study: its first study's part and mesh
            rows = simpressure.studies(a)
            if rows:
                return rows[0][0]
        if simtypes.is_fatigue(a):
            for o in simtypes.events(a):
                st = simtypes._event_study(a, o)
                if st is not None:
                    return st
    except Exception as _fw_err:
        _fw_log("simreport.py:fatiguemat", _fw_err)
    return a


def _connectors(a):
    ""
    try:
        from . import asmsim
    except ImportError:
        return []
    out = []
    for o in asmsim.connectors(a):
        kind, v = getattr(o, asmsim.CONNECTOR, ""), asmsim.values_of(o)
        n = sum(len(subs or ()) for _obj, subs in (getattr(o, "References", []) or []))
        rows = [("Entities", "%d face(s)" % n), ("Type", kind)]
        if kind == "Bolt":
            e_mpa, nu = asmsim.bolt_material(v)
            rows.append(("Nominal shank diameter", "%.4g mm" % float(v.get("diameter") or 0.0)))
            if float(v.get("preload") or 0.0) > 0:
                if v.get("preload_type") == "Torque":
                    rows.append(("Preload (Torque)", "%.4g N.m" % (float(v["preload"]) / 1000.0)))
                    rows.append(("Friction factor", "%.4g" % float(v.get("friction_factor") or 0.2)))
                else:
                    rows.append(("Preload (Axial)", "%.4g N" % float(v["preload"])))
            rows.append(("Material", "Custom" if v.get("e_mpa") else (v.get("material") or "Alloy Steel")))
            rows.append(("Young's modulus", "%.4g N/m^2" % (e_mpa * 1e6)))
            rows.append(("Poisson's ratio", "%.4g" % nu))
        elif kind == "Pin":
            rows.append(("With retaining ring", "Yes" if v.get("ring") else "No"))
            rows.append(("With key", "Yes" if v.get("key") else "No"))
        elif kind == "Spring":
            rows.append(("Axial stiffness", "%.4g N/mm" % float(v.get("axial") or 0.0)))
            rows.append(("Tangential stiffness", "%.4g N/mm" % float(v.get("tangential") or 0.0)))
        elif kind == "Bearing":
            rows.append(("Stiffness", v.get("stiffness") or "Rigid"))
            if v.get("stiffness") == "Flexible":
                rows.append(("Lateral stiffness", "%.4g N/mm" % float(v.get("lateral") or 0.0)))
                rows.append(("Axial stiffness", "%.4g N/mm" % float(v.get("axial") or 0.0)))
            rows.append(("Self-aligning", "Yes" if v.get("align") else "No"))
        if getattr(o, "Suppressed", False):
            rows.append(("Suppressed", "Yes"))
        out.append({"name": _name(o), "type": kind, "entities": _refs(o), "rows": rows})
    return out


AMP_TYPE = {"AMPRES": "Resultant Amplitude", "AMPX": "X Amplitude", "AMPY": "Y Amplitude", "AMPZ": "Z Amplitude"}


def _amp_type(a, p):
    ""

    if p.get("quantity") != "Amplitude":
        return None
    try:
        from . import simtypes
        n = int(p.get("mode") or 1)
        v = next((v for m, _r, v in simtypes.modes(a) if m == n), None)
        what = AMP_TYPE.get(p.get("comp"), p.get("comp", ""))
        if v is None:
            return "%s: %s Plot for Mode Shape: %d" % (p.get("comp", ""), what, n)
        val = ("Value = %.5g Hz" if simtypes.study_type(a) == "frequency" else "Load Factor = %.5g") % v
        return "%s: %s Plot for Mode Shape: %d(%s)" % (p.get("comp", ""), what, n, val)
    except Exception as _fw_err:
        _fw_log("simreport.py:amptype", _fw_err)
        return None


def gather(a):
    """Everything the report shows, as plain data (the checks read it)."""
    from . import simtree, simplots
    doc = a.Document
    out = {"part": doc.Label or doc.Name, "study": a.Label, "config": simtree.config_name(doc), "file": doc.FileName or "(not saved)"}
    try:
        out["type"] = {"static": "Static", "frequency": "Frequency", "buckling": "Buckling", "thermomech": "Thermal",
                       "check": "Static"}.get(simtree.kind(a), simtree.kind(a).title())
    except Exception:
        out["type"] = "Static"
    bodies = []
    src = _material_study(a)
    for s in _shape_of(src if src is not a and simtree.kind(a) == "pressure" else a):
        try:
            sh = s.Shape
            bodies.append({"name": s.Label, "volume": sh.Volume, "area": sh.Area, "box": sh.BoundBox})
        except Exception as _fw_err:
            _fw_log("simreport.py:body", _fw_err)
    out["bodies"] = bodies
    mats = []
    for m in simtree._materials(_material_study(a)):
        if getattr(getattr(m, "Proxy", None), "Type", "") == "Fem::MaterialMechanicalNonlinear":
            continue                           # its plasticity shows as the material's model type
        card = getattr(m, "Material", {}) or {}
        rho = _q(card.get("Density", ""), "kg/m^3")
        mats.append({"name": card.get("Name", m.Label), "refs": _refs(m) or "All bodies",
                     "E": card.get("YoungsModulus", ""), "nu": card.get("PoissonRatio", ""), "density": card.get("Density", ""),
                     "yield": card.get("YieldStrength", ""), "rho": rho,
                     "alpha": card.get("ThermalExpansionCoefficient", ""), "k": card.get("ThermalConductivity", ""),
                     "cp": card.get("SpecificHeat", "")})
    out["materials"] = mats
    vol = sum(b["volume"] for b in bodies)
    rho = next((m["rho"] for m in mats if m["rho"]), None)
    out["mass"] = vol * 1e-9 * rho if rho else None
    out["volume"] = vol
    fixtures, loads, contacts = [], [], []
    for o in a.Group:
        k = simtree.ftype(o)
        if _kept(o).get("kind") in PM_KINDS:       # Torque, Remote Load/Mass, ... ride on other FEM objects
            loads.append({"name": _name(o), "type": _row_kind(o), "entities": _refs(o), "value": _value(o)})
        elif k in simtree.FIXTURES:
            fixtures.append({"name": _name(o), "type": _row_kind(o), "entities": _refs(o), "value": _value(o)})
        elif k in simtree.LOADS or k in simtree.THERMAL:
            if simtree.hidden_initial(a, o):        # not a load the user gave (steady-state thermal)
                continue
            loads.append({"name": _name(o), "type": _row_kind(o), "entities": _refs(o), "value": _value(o)})
        elif k in simtree.CONNECTIONS:
            contacts.append({"name": _name(o), "type": _row_kind(o), "entities": _refs(o)})
    out["fixtures"], out["loads"], out["contacts"] = fixtures, loads, contacts
    out["connectors"] = _connectors(a)
    mesh = None
    for m in simtree._meshes(src if simtree.kind(a) == "pressure" else a):
        try:
            fm = m.FemMesh
            mesh = {"name": m.Label, "mesher": "Gmsh" if "Gmsh" in (getattr(getattr(m, "Proxy", None), "Type", "") or "") else "Netgen",
                    "size": getattr(m, "CharacteristicLengthMax", ""), "min": getattr(m, "CharacteristicLengthMin", ""),
                    "order": getattr(m, "ElementOrder", ""), "nodes": fm.NodeCount, "elements": fm.VolumeCount or fm.FaceCount}
            try:
                from . import simmeshinfo
                mesh["rows"] = [(k, v) for k, v in simmeshinfo.details(m, a) if k != "Study name"]
            except Exception as _fw_err:
                _fw_log("simreport.py:mesh rows", _fw_err)
        except Exception as _fw_err:
            _fw_log("simreport.py:mesh", _fw_err)
    out["mesh"] = mesh
    solver = None
    for o in a.Group:
        if o.isDerivedFrom("Fem::FemSolverObjectPython") or o.TypeId.startswith("Fem::FemSolver"):
            solver = o
    out["solver"] = {"name": "CalculiX" if solver is not None and "Ccx" in (getattr(getattr(solver, "Proxy", None), "Type", "") or "Ccx")
                     else getattr(solver, "Label", ""), "type": getattr(solver, "AnalysisType", ""),
                     "nonlinear": getattr(solver, "GeometricalNonlinearity", "")} if solver is not None else None
    results = []
    try:
        if simplots.result(a) is not None:
            for p in simplots.defaults(a):
                if p["quantity"] == "Material Mass":       # a Topology Study's plot: its own table below
                    continue
                s = simplots.summary(a, p)
                results.append({"name": p["name"], "title": simplots.title(p), "head": simplots.legend_head(p),
                                "type": _amp_type(a, p), "comp": p.get("comp", ""), "min": s["min"], "min_node": s["min_node"], "max": s["max"], "max_node": s["max_node"],
                                "yield": simplots.yield_strength(a, p) if p["quantity"] == "Stress" and p["comp"] == "VON" else None})
    except Exception as _fw_err:
        _fw_log("simreport.py:results", _fw_err)
    out["results"] = results
    out["kind"], out["props"], out["modes"], out["participation"] = "static", {}, [], []
    try:
        from . import simtypes
        out["kind"] = simtypes.study_type(a)
        if out["kind"] == "nonlinear":
            out["type"] = "Nonlinear"
        if out["kind"] == "lineardynamic":
            from . import simdynamic
            dv = simdynamic.values(a)
            out["type"] = "Linear Dynamic (%s)" % dv["analysis"]
            st = simdynamic.steps(a)
            pk = simdynamic.peak_step(a)
            out["dynamic"] = dict(dv, steps=len(st), freqs=simdynamic.mode_frequencies(a),
                                  peak=simdynamic.step_words(a, st[pk - 1][2]) if st else "")
        if out["kind"] == "pressure":
            from . import simpressure
            out["type"] = "Pressure Vessel Design"
            out["pressure"] = {"method": simpressure.method_word(a),
                               "studies": [(st.Label, f) for st, f in simpressure.studies(a)],
                               "linear": simpressure.last_linearization(a)}
        if out["kind"] == "topology":
            from . import simtopology
            out["type"] = "Topology Study"
            h = simtopology.history(a)
            tv = simtopology.values(a)
            out["topology"] = dict(tv, limit=simtopology.run_meta(a).get("limit"), passes=len(h), mass=h[-1][2] if h else None, first=h[0][1] if h else None,
                                   last=h[-1][1] if h else None, shown=simtopology.mass_kept(a) if h else None)
        out["props"] = simtypes.properties(a)
        if out["kind"] == "fatigue":
            ev = []
            for o in simtypes.events(a):
                v = simtypes.event_values(o)
                st = simtypes._event_study(a, o)
                ev.append({"name": o.Label, "cycles": v.get("cycles"), "loading": v.get("loading", ""),
                           "ratio": v.get("ratio"), "study": st.Label if st is not None else "",
                           "scale": v.get("scale", 1.0), "suppressed": bool(getattr(o, "Suppressed", False))})
            out["events"] = ev
            out["sn"] = simtypes.sn_curve(a)
        if out["kind"] == "drop":
            dv = simtypes.drop_values(a)
            shape = simtypes._shape(a)
            dv["impact"] = simtypes.impact_velocity(a, shape)
            dv["solution"] = simtypes.solution_time(a, shape)
            out["drop"] = dv
        if out["kind"] == "frequency" and results:
            out["modes"] = simtypes.frequencies(a)
            out["participation"] = simtypes.mass_participation(a)    # and Mass Participation (Normalized)
        if out["kind"] == "buckling" and results:
            out["factors"] = [(n, v) for n, _r, v in simtypes.modes(a)]
    except Exception as _fw_err:
        _fw_log("simreport.py:types", _fw_err)
    return out


# --------------------------------------------------------------------------- pictures
def _shot(path, overlays=False):
    """The view as a picture; overlays: the view widget itself, with the plot's legend and title block on it."""
    try:
        if overlays:
            from . import simxpress
            host = simxpress._host()
            if host is not None:
                QtWidgets.QApplication.processEvents()
                if host.grab().save(path):
                    return os.path.basename(path)
        Gui.ActiveDocument.ActiveView.saveImage(path, 1000, 640, "Current")
        return os.path.basename(path)
    except Exception as _fw_err:
        _fw_log("simreport.py:shot", _fw_err)
        return None


def _fem_display(doc):
    ""
    out = []
    for o in doc.Objects:
        try:
            if (o.isDerivedFrom("Fem::FemMeshObject") or o.isDerivedFrom("Fem::FemResultObject")
                    or o.isDerivedFrom("Fem::FemPostObject")) and o.ViewObject is not None:
                out.append(o)
        except Exception as _fw_err:
            _fw_log("simreport.py:femdisplay", _fw_err)
    return out


def hide_fem_display(doc):
    ""

    hidden = []
    for o in _fem_display(doc):
        if o.ViewObject.Visibility:
            o.ViewObject.Visibility = False
            hidden.append(o)
    return hidden


def pictures(a, folder, stem, with_results=True):
    """{"model": file, "loads": file, plot name: file}: the model, the fixtures and loads, then each plot shown."""
    from . import simplots
    out = {}
    if Gui.ActiveDocument is None:
        return out
    was = simplots.SHOWN.get("name") if simplots.SHOWN.get("a") is a else None
    try:
        simplots.clear()
    except Exception as _fw_err:
        _fw_log("simreport.py:clear", _fw_err)
    hidden = hide_fem_display(a.Document)
    out["model"] = _shot(os.path.join(folder, stem + "-model.png"))
    for o in hidden:
        o.ViewObject.Visibility = True
    if with_results:
        try:
            if simplots.result(a) is not None:
                for p in simplots.defaults(a):
                    simplots.show(a, p["name"])
                    QtWidgets.QApplication.processEvents()
                    out[p["name"]] = _shot(os.path.join(folder, "%s-%s.png" % (stem, p["name"])), overlays=True)
                simplots.clear()
        except Exception as _fw_err:
            _fw_log("simreport.py:plots", _fw_err)
    if was:
        try:
            simplots.show(a, was)
        except Exception as _fw_err:
            _fw_log("simreport.py:back", _fw_err)
    return out


# --------------------------------------------------------------------------- the HTML
CSS = ("body{font-family:Segoe UI,Arial,sans-serif;margin:32px;color:#222}h1{font-size:26px;margin:0}"
       "h2{font-size:18px;border-bottom:2px solid #c00;padding-bottom:3px;margin-top:28px}"
       "table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #bbb;padding:4px 8px;text-align:left;"
       "vertical-align:top}th{background:#eee}.cover td{border:none;padding:2px 12px 2px 0}img{max-width:100%}"
       ".toc li{margin:2px 0}")


def _t(rows, head=None, raw=False):
    """A table; raw: the cells are HTML already (escaped by the caller)."""
    e = (lambda x: x) if raw else html.escape
    out = ["<table>"]
    if head:
        out.append("<tr>%s</tr>" % "".join("<th>%s</th>" % e(str(h)) for h in head))
    for r in rows:
        out.append("<tr>%s</tr>" % "".join("<td>%s</td>" % e("" if c is None else str(c)) for c in r))
    out.append("</table>")
    return "".join(out)


def _n(v, unit=""):
    if v is None:
        return ""
    return ("%.4g %s" % (v, unit)).strip()


def _len(q, ips):
    ""
    try:
        v = q.getValueAs("mm").Value if hasattr(q, "getValueAs") else App.Units.Quantity(str(q)).getValueAs("mm").Value
        return "%.4g in" % (v / 25.4) if ips else "%.4g mm" % v
    except Exception:
        return str(q)


IPS_CARD = {"E": "psi", "yield": "psi", "density": "lb/in^3", "k": "Btu/(in.s.F)" , "cp": "Btu/(lb.F)", "alpha": "1/F"}


def _ips(text, key):
    ""
    unit = IPS_CARD.get(key)
    if not unit or not text:
        return text
    try:
        if key == "alpha":
            return "%.4g %s" % (App.Units.Quantity(text).getValueAs("1/K").Value / 1.8, unit)
        if key in ("E", "yield"):
            return "%.4g %s" % (App.Units.Quantity(text).getValueAs("MPa").Value * 145.0377, unit)
        if key == "density":
            return "%.4g %s" % (App.Units.Quantity(text).getValueAs("kg/m^3").Value / 27679.9, unit)
    except Exception as _fw_err:
        _fw_log("simreport.py:ips", _fw_err)
    return text


def build_html(a, data, o, pics):
    e = html.escape
    on = o["sections"]
    texts = o.get("texts", {})
    head = o.get("header", {})
    head_on = o.get("header_on", {})
    parts = ["<html><head><meta charset='utf-8'><title>%s</title><style>%s</style></head><body>" % (e(o["name"]), CSS)]
    cover = [("Model", data["part"]), ("Study", "%s (-%s-)" % (data["study"], data["config"])), ("Analysis type", data["type"]),
             ("Date", time.strftime("%Y-%m-%d %H:%M"))]
    cover += [(h, head.get(h, "")) for h in HEADER if head_on.get(h) and head.get(h)]
    logo = ""
    if o.get("logo") and os.path.isfile(o["logo"]):
        logo = "<img src='%s' style='max-height:80px;float:right'>" % e(o["logo"].replace("\\", "/"))
    parts.append("%s<h1>Simulation of %s</h1><table class='cover'>%s</table>" % (
        logo, e(data["part"]), "".join("<tr><td><b>%s</b></td><td>%s</td></tr>" % (e(k), e(v)) for k, v in cover)))
    try:
        from . import addintabs
        ips = bool(addintabs._inch_units(a))
    except Exception:
        ips = False
    shown = [s for s in SECTIONS if on.get(s, True) and _has(s, data, texts)]
    parts.append("<h2>Table of Contents</h2><ol class='toc'>%s</ol>" % "".join(
        "<li><a href='#%s'>%s</a></li>" % (s.replace(" ", ""), e(s)) for s in shown))
    for s in shown:
        parts.append("<h2 id='%s'>%s</h2>" % (s.replace(" ", ""), e(s)))
        if s in TEXT_SECTIONS:
            parts.append("<p>%s</p>" % e(texts.get(s, "")).replace("\n", "<br>"))
        elif s == "Model Information":
            if pics.get("model"):
                parts.append("<p><img src='%s'></p>" % e(pics["model"]))
            L, Ln = (25.4, "in") if ips else (1.0, "mm")
            parts.append(_t([(b["name"], "Solid Body", _n(b["volume"] / L ** 3, Ln + "^3"), _n(b["area"] / L ** 2, Ln + "^2"),
                              "%.4g x %.4g x %.4g %s" % (b["box"].XLength / L, b["box"].YLength / L, b["box"].ZLength / L, Ln))
                             for b in data["bodies"]], ("Body", "Treated As", "Volume", "Surface area", "Size")))
            mass = data["mass"] / 0.45359237 if ips and data["mass"] is not None else data["mass"]
            vol = data["volume"] / L ** 3 if data["volume"] is not None else None
            parts.append(_t([("Mass", _n(mass, "lb" if ips else "kg")), ("Volume", _n(vol, Ln + "^3")),
                             ("Document path", data["file"])]))
        elif s == "Study Properties":
            sv = data["solver"] or {}
            props = data.get("props") or {}
            rows = [("Study name", data["study"]), ("Analysis type", data["type"]), ("Mesh type", "Solid Mesh")]
            if data.get("kind") == "frequency":
                rows.append(("Number of frequencies", props.get("count", "")))
                if props.get("upper"):
                    rows.append(("Upper bound frequency", "%.6g Hz" % props["upper"]))
                rows.append(("Use inplane effect", "On" if props.get("inplane") else "Off"))
                rows.append(("Soft Spring", "On" if props.get("soft") else "Off"))
            elif data.get("kind") == "thermomech":
                steady = props.get("steady", True)
                rows.append(("Solution type", "Steady state" if steady else "Transient"))
                if not steady:
                    rows.append(("Total time", "%.6g s" % props.get("total", 0)))
                    rows.append(("Time increment", "%.6g s" % props.get("increment", 0)))
            elif data.get("kind") == "buckling":
                rows.append(("Number of buckling modes", props.get("count", "")))
            elif data.get("kind") == "nonlinear":
                rows.append(("Solution type", "Static, end time %.4g s, time increment %.4g s" % (
                    float(props.get("end", 1.0)), float(props.get("increment", 0.05)))))
                rows.append(("Large displacement", "On" if props.get("large", True) else "Off"))
                rows.append(("Material model", props.get("model", "")))
                if props.get("model") == "Plasticity - von Mises":
                    rows.append(("Tangent modulus", "%.6g MPa" % float(props.get("tangent", 0.0))))
                    rows.append(("Hardening", props.get("hardening", "")))
            elif data.get("kind") == "topology":
                tv = data.get("topology") or {}
                rows.append(("Goal", tv.get("goal", "")))
                if tv.get("goal") == "Minimize Mass with Displacement constraint":
                    rows.append(("Displacement constraint", "%.4g mm" % float(tv["limit"]) if tv.get("limit") else
                                 ("%g mm" % float(tv.get("disp_limit", 0)) if tv.get("disp_mode") == "Specify value" else
                                  "%g x the initial maximum displacement" % float(tv.get("disp_factor", 2)))))
                else:
                    rows.append(("Mass constraint", "Reduce mass by %g %%" % float(tv.get("reduce", 0))))
                pres = ["Faces where loads and fixtures are applied"] if tv.get("preserve_loads", True) else []
                pres += list(tv.get("faces", []))
                rows.append(("Preserved regions", ", ".join(pres) or "None"))
                if tv.get("thickness_on"):
                    rows.append(("Thickness Control", "Minimum thickness %g mm" % float(tv.get("min_thickness", 0))))
                if tv.get("demold_on"):
                    rows.append(("Demold Direction", "%s %s%s" % ("Both directions from" if tv.get("demold_both") else "Pull along",
                                                             tv.get("demold_ref", ""), ", reversed" if tv.get("demold_reverse") else "")))
                if tv.get("sym_on"):
                    rows.append(("Symmetry", ", ".join(tv.get("sym_planes", []))))
            elif data.get("kind") == "lineardynamic":     # Linear Dynamic Properties
                dv = data.get("dynamic") or {}
                rows.append(("Number of frequencies", dv.get("modes", "")))
                rows.append(("Modal damping ratio", "%g %%" % float(dv.get("damping", 0))))
                if dv.get("analysis") in ("Random Vibration", "Response Spectrum Analysis"):
                    rows.append(("Base excitation", "Uniform, along %s" % dv.get("direction", "Y")))
                    if dv.get("analysis") == "Random Vibration":
                        rows.append(("Acceleration PSD", ", ".join("(%g Hz, %g g^2/Hz)" % (f, y) for f, y in dv.get("psd", []))))
                    else:
                        rows.append(("Acceleration spectrum", ", ".join("(%g Hz, %g g)" % (f, y) for f, y in dv.get("spectrum", []))))
                        rows.append(("Mode combination", dv.get("combination", "SRSS")))
                elif dv.get("analysis") == "Harmonic":
                    rows.append(("Frequency range", "%g to %g Hz" % (float(dv.get("f_lo", 0)), float(dv.get("f_hi", 0)))))
                    rows.append(("Number of points", dv.get("points", "")))
                    rows.append(("Bias parameter", "%g" % float(dv.get("bias", 3))))
                else:
                    rows.append(("End time", "%g s" % float(dv.get("end", 0))))
                    rows.append(("Time increment", "%g s" % float(dv.get("increment", 0))))
                    rows.append(("Variation with time", ", ".join("(%g s, %g)" % (t, f) for t, f in dv.get("curve", []))))
                if dv.get("steps"):
                    rows.append(("Largest response", dv.get("peak", "")))
            elif data.get("kind") == "pressure":
                pv = data.get("pressure") or {}
                rows.append(("Combination", pv.get("method", "")))
                for name, f in pv.get("studies", []):
                    rows.append(("Study %s" % name, "Factor %g" % f))
            elif data.get("kind") == "fatigue":
                rows.append(("Loading", "Constant amplitude"))
                rows.append(("Compute alternating stress using", props.get("alternating", "")))
                rows.append(("Mean stress correction", props.get("mean", "None")))
                rows.append(("Fatigue strength reduction factor (Kf)", "%.4g" % props.get("kf", 1.0)))
                rows.append(("Infinite life", "%.6g cycles" % props.get("infinite", 1e6)))
            elif data.get("kind") == "drop":
                dv = data.get("drop") or {}
                if dv.get("type") == "Velocity at impact":
                    rows.append(("Velocity at impact", "%.6g m/s" % (float(dv.get("velocity", 0)) / 1000.0)))
                else:
                    rows.append(("Drop height", "%.6g mm (%s)" % (float(dv.get("height", 0)), dv.get("from", "").lower())))
                    if dv.get("impact"):
                        rows.append(("Velocity at impact", "%.4g m/s" % (dv["impact"] / 1000.0)))
                rows.append(("Gravity", "%.6g m/s^2, direction (%g, %g, %g)" % ((float(dv.get("gravity", 9.81)),) +
                                                                             tuple(dv.get("direction", (0, 0, -1))))))
                if dv.get("orientation") == "Parallel to plane":
                    rows.append(("Target orientation", "Parallel to plane %s" % dv.get("plane", "")))
                else:
                    rows.append(("Target orientation", "Normal to gravity"))
                if dv.get("target") == "Flexible target":
                    rows.append(("Target stiffness", "Flexible, normal stiffness per unit area %.4g N/m^3" % float(dv.get("stiffness", 0))))
                else:
                    rows.append(("Target stiffness", "Rigid target"))
                if dv.get("solution"):
                    rows.append(("Solution time after impact", "%.4g microseconds" % (dv["solution"] * 1e6)))
                rows.append(("Number of plots", dv.get("plots", "")))
            if sv.get("name"):
                rows.append(("Solver type", sv.get("name", "")))
            if data.get("kind") not in ("thermomech", "frequency", "buckling", "drop", "fatigue", "nonlinear", "topology",
                                         "pressure", "lineardynamic"):
                rows.append(("Large displacement", "On" if sv.get("nonlinear") == "nonlinear" else "Off"))
            if data.get("kind") in ("static", "check", None, ""):
                rows.append(("Soft Spring", "On" if props.get("soft") else "Off"))
                rows.append(("Inertial Relief", "On" if props.get("inertial") else "Off"))
            rows.append(("Result folder", os.path.dirname(a.Document.FileName) if a.Document.FileName else "(the part is not saved)"))
            try:                                     # Study Properties > Remark, when "Include in report" is ticked
                from . import simstudy
                text, in_report = simstudy.remark(a)
                if in_report and text.strip():
                    rows.append(("Remark", text.strip()))
            except Exception as _fw_err:
                _fw_log("simreport.py:remark", _fw_err)
            parts.append(_t(rows))
        elif s == "Units":
            if ips:
                parts.append(_t([("Unit system", "English (IPS)"), ("Length/Displacement", "in"), ("Temperature", "Fahrenheit"),
                                 ("Angular velocity", "Rad/sec"), ("Pressure/Stress", "psi")]))
            else:
                parts.append(_t([("Unit system", "SI (MKS)"), ("Length/Displacement", "mm"), ("Temperature", "Kelvin"),
                                 ("Angular velocity", "Rad/sec"), ("Pressure/Stress", "N/m^2")]))
        elif s == "Material Properties":
            cols = [("Elastic modulus", "E"), ("Poisson's ratio", "nu"), ("Mass density", "density"), ("Yield strength", "yield")]
            if data.get("kind") == "thermomech":     # a thermal study: what it solves with
                cols += [("Thermal conductivity", "k"), ("Specific heat", "cp")]
            if any(m.get("alpha") for m in data["materials"]) and (data.get("kind") == "thermomech" or any(
                    f["type"] == "Temperature" for f in data["loads"])):
                cols.append(("Thermal expansion coefficient", "alpha"))
            model = (data.get("props") or {}).get("model") if data.get("kind") == "nonlinear" else None
            parts.append(_t([(m["refs"], m["name"], model or "Linear Elastic Isotropic") + tuple(_ips(m.get(k, ""), k) if ips else m.get(k, "") for _h, k in cols)
                             for m in data["materials"]],
                            ("Model reference", "Name", "Model type") + tuple(h for h, _k in cols)))
        elif s == "Loads and Fixtures":
            if data.get("events"):            # a fatigue study: its Loading (events) and S-N curve
                parts.append("<h3>Loading (-Constant Amplitude-)</h3>" + _t(
                    [(v["name"] + (" (Suppressed)" if v["suppressed"] else ""), v["cycles"], v["loading"],
                      "%.4g" % v["ratio"] if v["ratio"] is not None else "", v["study"], "%.4g" % v["scale"])
                     for v in data["events"]], ("Event", "Cycles", "Loading type", "Loading ratio", "Study", "Scale factor")))
                sn = data.get("sn") or {}
                if sn.get("points"):
                    parts.append("<h3>S-N Curve (%s)</h3>" % e(sn.get("source", "")) + _t(
                        [("%.6g" % n, "%.6g MPa" % st) for n, st in sn["points"]], ("Cycles", "Alternating stress")))
            if data["fixtures"]:
                parts.append("<h3>Fixtures</h3>" + _t([(f["name"], f["type"], f["entities"], f["value"]) for f in data["fixtures"]],
                                                       ("Fixture name", "Type", "Entities", "Details")))
            if data["loads"]:
                parts.append("<h3>%s</h3>" % ("Thermal Loads" if data.get("kind") == "thermomech" else "Loads") +
                             _t([(f["name"], f["type"], f["entities"], f["value"]) for f in data["loads"]],
                                ("Load name", "Type", "Entities", "Value")))
        elif s == "Connector Definitions":
            for c in data.get("connectors") or []:
                parts.append("<h3>%s</h3>" % e(c["name"]) + _t(c["rows"], ("Connector Details", "")))
        elif s == "Contact Information":
            parts.append(_t([(c["name"], c["type"], c["entities"]) for c in data["contacts"]], ("Contact", "Type", "Entities")))
        elif s == "Mesh information":
            m = data["mesh"] or {}
            if m.get("rows"):
                parts.append(_t(m["rows"]))
            else:
                parts.append(_t([("Mesh type", "Solid Mesh"), ("Mesher used", m.get("mesher", "")), ("Element size", _len(m.get("size", ""), ips)),
                                 ("Minimum element size", _len(m.get("min", ""), ips)), ("Element order", m.get("order", "")),
                                 ("Total nodes", m.get("nodes", "")), ("Total elements", m.get("elements", ""))]))
        elif s == "Study Results":
            tv = data.get("topology") or {}
            if tv.get("passes"):
                parts.append("<h3>Material Mass1 (-Material Mass-)</h3>")
                parts.append(_t([("Passes", tv["passes"]), ("Mass kept by the optimization", "%.1f %%" % (100.0 * tv["mass"])),
                                 ("Shown at relative mass density %.2f and above" % float(tv.get("threshold", 0.5)),
                                  "%.1f %% of the part" % (100.0 * (tv.get("shown") or 0.0))),
                                 (("Compliance (first pass, last pass)", "%.4g N.mm, %.4g N.mm" % (tv["first"], tv["last"]))
                                  if tv.get("goal", "Best Stiffness to Weight ratio") == "Best Stiffness to Weight ratio" else
                                  ("Max displacement (first pass, last pass)", "%.4g mm, %.4g mm" % (tv["first"], tv["last"])))]))

            for r in data["results"]:
                unit = r["head"][r["head"].rfind("(") + 1:-1] if r["head"].endswith(")") and "(" in r["head"] else ""
                words = r["title"][r["title"].find("(-") + 2:r["title"].rfind("-)")] if "(-" in r["title"] else r["head"]
                kind = "%s: %s" % (r["comp"], words) if r.get("comp") else words
                kind = r.get("type") or kind
                parts.append(_t([(e(r["name"]), e(kind), "%.3e%s<br>Node: %s" % (r["min"], e(unit), r["min_node"]),
                                  "%.3e%s<br>Node: %s" % (r["max"], e(unit), r["max_node"]))], ("Name", "Type", "Min", "Max"), raw=True))
                if pics.get(r["name"]):
                    parts.append("<p><img src='%s'><br>%s-%s</p>" % (e(pics[r["name"]]), e(a.Document.Label or a.Document.Name),
                                                                       e("%s-%s" % (a.Label, r["name"]))))
            lin = (data.get("pressure") or {}).get("linear") or {}
            if lin.get("rows"):                      # the last Stress Linearization, in MPa
                parts.append("<h3>Stress Linearization</h3><p>From (%.4g, %.4g, %.4g) mm to (%.4g, %.4g, %.4g) mm, "
                             "length %.4g mm</p>" % (tuple(lin["start"]) + tuple(lin["end"]) + (lin["length"],)))
                from . import simpressure
                parts.append(_t([(r,) + tuple("%.4g" % lin["rows"][r][c] for c in simpressure.LIN_COLUMNS)
                                 for r in simpressure.LIN_ROWS], ("N/mm^2 (MPa)",) + simpressure.LIN_COLUMNS))
            if data.get("modes"):
                parts.append("<h3>Mode List</h3>" + _t([(n, "%.6g" % rad, "%.6g" % hz, "%.6g" % per) for n, rad, hz, per in data["modes"]],
                                                       ("Frequency Number", "Rad/sec", "Hertz", "Seconds")))
            if data.get("factors"):
                parts.append("<h3>Mode List</h3>" + _t([(n, "%.6g" % v) for n, v in data["factors"]],
                                                       ("Mode Number", "Load Factor")))
            mp = data.get("participation")
            if mp:
                rows = [(n, "%.6g" % hz, "%.4g" % x, "%.4g" % y, "%.4g" % z) for n, hz, x, y, z in mp]
                rows.append(("", "", "Sum X = %.4g" % sum(m[2] for m in mp), "Sum Y = %.4g" % sum(m[3] for m in mp),
                             "Sum Z = %.4g" % sum(m[4] for m in mp)))
                parts.append("<h3>Mass Participation (Normalized)</h3>" + _t(rows, ("Mode Number", "Frequency (Hertz)",
                                                                                    "X direction", "Y direction", "Z direction")))
    parts.append("</body></html>")
    return "".join(parts)


def _has(s, data, texts):
    if s in TEXT_SECTIONS:
        return bool(texts.get(s, "").strip())
    if s == "Contact Information":
        return bool(data["contacts"])
    if s == "Connector Definitions":
        return bool(data.get("connectors"))
    if s == "Mesh information":
        return data["mesh"] is not None
    if s == "Study Results":
        return bool(data["results"] or (data.get("topology") or {}).get("passes"))
    if s == "Loads and Fixtures":            # a drop test has neither (its Setup is under Study Properties)
        return bool(data["fixtures"] or data["loads"] or data.get("events"))
    return True


def publish(a, o=None):
    """Writes the report (and its pictures) to o["path"]/o["name"].html; adds it under the study's Report folder."""
    o = o or options(a)
    folder = o["path"] or default_folder(a.Document)
    os.makedirs(folder, exist_ok=True)
    stem = o["name"] or next_name(a)
    pics = {}
    if Gui is not None and (o["sections"].get("Model Information", True) or o["sections"].get("Study Results", True)):
        pics = pictures(a, folder, stem, o["sections"].get("Study Results", True))
    data = gather(a)
    path = os.path.join(folder, stem + ".html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_html(a, data, o, pics))
    _remember(a, path)
    App.Console.PrintMessage("FreeCAD: study report %s\n" % path)
    if Gui is not None:
        Gui.getMainWindow().statusBar().showMessage("Report published: %s" % path, 10000)
        if o.get("show", True) and not os.environ.get("SWCHECK_OUT"):      # a check run never opens the browser
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
    return path


def open_report(path):
    if os.path.isfile(path):
        if not os.environ.get("SWCHECK_OUT"):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
        return True
    QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Report", "The report file is gone:\n%s" % path)
    return False


# =========================================================================== GUI
if Gui is not None:
    class OptionsDialog(QtWidgets.QDialog):
        ""

        def __init__(self, a, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.a = a
            self.o = options(a)
            self.published = None
            self.setWindowTitle("Report Options")
            self.setObjectName("SWSimReportOptions")
            lay = QtWidgets.QVBoxLayout(self)
            top = QtWidgets.QHBoxLayout()
            box = QtWidgets.QGroupBox("Report format settings")
            bl = QtWidgets.QVBoxLayout(box)
            bl.addWidget(QtWidgets.QLabel("Report sections:"))
            self.sections = QtWidgets.QListWidget()
            self.sections.setObjectName("SWSimReportSections")
            for s in SECTIONS:
                it = QtWidgets.QListWidgetItem(s)
                it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Checked if self.o["sections"].get(s, True) else QtCore.Qt.Unchecked)
                self.sections.addItem(it)
            bl.addWidget(self.sections)
            self.props = QtWidgets.QGroupBox("Section properties")
            pl = QtWidgets.QVBoxLayout(self.props)
            self.prop_label = QtWidgets.QLabel()
            self.prop_label.setWordWrap(True)
            self.text = QtWidgets.QPlainTextEdit()
            self.text.setObjectName("SWSimReportText")
            self.text.setPlaceholderText("Comments")
            pl.addWidget(self.prop_label)
            pl.addWidget(self.text)
            bl.addWidget(self.props)
            top.addWidget(box, 1)
            right = QtWidgets.QVBoxLayout()
            hbox = QtWidgets.QGroupBox("Header information")
            hl = QtWidgets.QGridLayout(hbox)
            self.head, self.head_on = {}, {}
            for i, h in enumerate(HEADER):
                cb = QtWidgets.QCheckBox(h + ":")
                cb.setChecked(bool(self.o["header_on"].get(h)))
                le = QtWidgets.QLineEdit(self.o["header"].get(h, ""))
                le.setObjectName("SWSimReport" + h)
                le.textEdited.connect(lambda _t, cb=cb: cb.setChecked(True))
                hl.addWidget(cb, i, 0)
                hl.addWidget(le, i, 1)
                self.head[h], self.head_on[h] = le, cb
            self.logo = QtWidgets.QLineEdit(self.o.get("logo", ""))
            logo_b = QtWidgets.QPushButton("Browse...")
            logo_b.clicked.connect(self._logo)
            hl.addWidget(QtWidgets.QLabel("Logo:"), len(HEADER), 0)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.logo)
            row.addWidget(logo_b)
            hl.addLayout(row, len(HEADER), 1)
            right.addWidget(hbox)
            pbox = QtWidgets.QGroupBox("Report publishing options")
            pf = QtWidgets.QGridLayout(pbox)
            self.path = QtWidgets.QLineEdit(self.o["path"])
            self.path.setObjectName("SWSimReportPath")
            path_b = QtWidgets.QPushButton("...")
            path_b.clicked.connect(self._folder)
            pf.addWidget(QtWidgets.QLabel("Report path:"), 0, 0)
            pf.addWidget(self.path, 0, 1)
            pf.addWidget(path_b, 0, 2)
            self.name = QtWidgets.QLineEdit(self.o["name"])
            self.name.setObjectName("SWSimReportName")
            pf.addWidget(QtWidgets.QLabel("Document name:"), 1, 0)
            pf.addWidget(self.name, 1, 1, 1, 2)
            self.show_on = QtWidgets.QCheckBox("Show report on publish")
            self.show_on.setChecked(bool(self.o.get("show", True)))
            pf.addWidget(self.show_on, 2, 0, 1, 3)
            right.addWidget(pbox)
            right.addStretch(1)
            top.addLayout(right, 1)
            lay.addLayout(top, 1)
            buttons = QtWidgets.QDialogButtonBox()
            self.publish_b = buttons.addButton("Publish", QtWidgets.QDialogButtonBox.AcceptRole)
            self.apply_b = buttons.addButton("Apply", QtWidgets.QDialogButtonBox.ApplyRole)
            buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
            self.publish_b.setObjectName("SWSimReportPublish")
            self.publish_b.clicked.connect(self._publish)
            self.apply_b.clicked.connect(self._apply)
            buttons.rejected.connect(self.reject)
            lay.addWidget(buttons)
            self._current = None
            self.sections.currentItemChanged.connect(lambda cur, prev: self._section(cur, prev))
            self.sections.setCurrentRow(0)
            self.resize(820, 520)

        def _section(self, cur, prev):
            if prev is not None and prev.text() in TEXT_SECTIONS:
                self.o["texts"][prev.text()] = self.text.toPlainText()
            s = cur.text() if cur is not None else ""
            self._current = s
            takes = s in TEXT_SECTIONS
            self.text.setVisible(takes)
            self.prop_label.setText("Your text for this section." if takes else
                                    "%s is filled in from the study." % s if s else "")
            if takes:
                self.text.setPlainText(self.o["texts"].get(s, ""))

        def _logo(self):
            f, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Logo", self.logo.text(), "Pictures (*.png *.jpg *.jpeg *.bmp *.svg)")
            if f:
                self.logo.setText(f)

        def _folder(self):
            f = QtWidgets.QFileDialog.getExistingDirectory(self, "Report path", self.path.text())
            if f:
                self.path.setText(f)

        def read(self):
            if self._current in TEXT_SECTIONS:
                self.o["texts"][self._current] = self.text.toPlainText()
            for i in range(self.sections.count()):
                it = self.sections.item(i)
                self.o["sections"][it.text()] = it.checkState() == QtCore.Qt.Checked
            self.o["header"] = {h: self.head[h].text() for h in HEADER}
            self.o["header_on"] = {h: self.head_on[h].isChecked() for h in HEADER}
            self.o["logo"] = self.logo.text().strip()
            self.o["path"] = self.path.text().strip() or default_folder(self.a.Document)
            self.o["name"] = self.name.text().strip() or next_name(self.a)
            self.o["show"] = self.show_on.isChecked()
            return self.o

        def _apply(self):
            save_options(self.a, self.read())

        def _publish(self):
            # Publish closes Report Options first, then the report is written outside the dialog's own event loop
            # (the pictures pump events and swap plots, which must not run nested inside a modal dialog).
            o = self.read()
            save_options(self.a, o)
            self.want = o
            self.accept()

    def open_options(a=None):
        from . import simtree
        a = a or simtree._ctx_study()
        if a is None:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Report", "There is no study yet: start one with New Study.")
            return None
        dlg = OptionsDialog(a)
        dlg.exec_()
        o = getattr(dlg, "want", None)
        if o is not None and not PUBLISHING:
            PUBLISHING.append(1)
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                dlg.published = publish(a, o)
            except Exception as error:
                QtWidgets.QApplication.restoreOverrideCursor()
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Report", "The report was not published: %s" % error)
            else:
                QtWidgets.QApplication.restoreOverrideCursor()
            finally:
                del PUBLISHING[:]
        return dlg

    PUBLISHING = []      # one report at a time: a second Publish while one is being written is ignored

    class _Cmd:
        def GetResources(self):
            return {"MenuText": "Report", "ToolTip": "Report Options, then publishes the active study's report.",
                    "Pixmap": "document-print"}

        def IsActive(self):
            return App.ActiveDocument is not None and not Gui.Control.activeDialog()

        def Activated(self):
            open_options()

    def install():
        name = "SWStyle_SimReportOptions"
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Cmd())
        try:
            from . import catalog
            cmd = catalog.BY_KEY.get("SIM_Report")
            if cmd is not None and (not cmd.natives or cmd.natives[0] != name):
                cmd.natives = (name,) + tuple(n for n in cmd.natives if n != name)
                cmd.tip = "Report Options, then publishes the active study's report."
        except Exception as _fw_err:
            _fw_log("simreport.py:install", _fw_err)
else:
    def install():
        return None
