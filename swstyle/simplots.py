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

import csv
import json
import math

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

from . import simxpress as sx

PROP = "FwPlots"
# quantity -> [(component, label)]
COMPONENTS = {

    "Stress": [("SX", "SX: X Normal Stress"), ("SY", "SY: Y Normal Stress"), ("SZ", "SZ: Z Normal Stress"),
               ("TXY", "TXY: Shear in Y Dir. on YZ Plane"), ("TXZ", "TXZ: Shear in Z Dir. on YZ Plane"),
               ("TYZ", "TYZ: Shear in Z Dir. on XZ Plane"), ("P1", "P1: 1st Principal Stress"),
               ("P2", "P2: 2nd Principal Stress"), ("P3", "P3: 3rd Principal Stress"), ("VON", "VON: von Mises Stress"),
               ("INT", "INT: Stress Intensity(P1-P3)"), ("TRI", "TRI: Triaxial Stress(P1+P2+P3)")],
    "Displacement": [("UX", "UX: X Displacement"), ("UY", "UY: Y Displacement"), ("UZ", "UZ: Z Displacement"),
                     ("URES", "URES: Resultant Displacement")],
    "Strain": [("ESTRN", "ESTRN: Equivalent Strain"), ("EPSX", "EPSX: X Normal Strain"), ("EPSY", "EPSY: Y Normal Strain"),
               ("EPSZ", "EPSZ: Z Normal Strain"), ("GMXY", "GMXY: Shear Strain in Y Dir. on YZ Plane"),
               ("GMXZ", "GMXZ: Shear Strain in Z Dir. on YZ Plane"), ("GMYZ", "GMYZ: Shear Strain in Z Dir. on XZ Plane")],

    "Amplitude": [("AMPRES", "AMPRES: Resultant Amplitude"), ("AMPX", "AMPX: X Amplitude"), ("AMPY", "AMPY: Y Amplitude"),
                  ("AMPZ", "AMPZ: Z Amplitude")],
    "Thermal": [("TEMP", "TEMP: Temperature"), ("GRADN", "GRADN: Resultant Temperature Gradient"),
                ("GRADX", "GRADX: Temperature Gradient in X-Direction"), ("GRADY", "GRADY: Temperature Gradient in Y-Direction"),
                ("GRADZ", "GRADZ: Temperature Gradient in Z-Direction"), ("HFLUXN", "HFLUXN: Resultant Heat Flux"),
                ("HFLUXX", "HFLUXX: Heat Flux in X-Direction"), ("HFLUXY", "HFLUXY: Heat Flux in Y-Direction"),
                ("HFLUXZ", "HFLUXZ: Heat Flux in Z-Direction")],
    "Fatigue": [("Damage", "Damage"), ("Life", "Life"), ("LoadFactor", "Load factor")],
    # Define Factor of Safety Plot (its own three-step PM); the component is the criterion
    "Factor of Safety": [("FOS", "FOS: Factor of Safety")],
}
DEFAULT_COMP = {"Stress": "VON", "Displacement": "URES"}
# the kinds of plot a study type has (New Plot lists these)
KINDS = {"static": ("Stress", "Displacement", "Strain"), "check": ("Stress", "Displacement", "Strain"),
         "frequency": ("Amplitude",), "buckling": ("Amplitude",), "thermomech": ("Thermal",), "fatigue": ("Fatigue",),
         "drop": ("Stress", "Displacement", "Strain")}

BASE_NAME = {"Fatigue": "Results"}
UNITS = {"Stress": {"N/m^2": 1e6, "psi": 145.0377, "kgf/cm^2": 10.19716, "N/mm^2 (MPa)": 1.0, "ksi": 0.1450377},
         "Displacement": {"am": 1e15, "nm": 1e6, "micron": 1e3, "mm": 1.0, "cm": 0.1, "m": 0.001, "microIn": 1e6 / 25.4,
                          "mil": 1e3 / 25.4, "in": 1 / 25.4, "ft": 1 / 304.8},
         "Strain": {"": 1.0}, "Amplitude": {"": 1.0},
         "Thermal": {"Kelvin": 1.0, "Celsius": 1.0, "Fahrenheit": 1.8}, "Fatigue": {"": 1.0}, "Factor of Safety": {"": 1.0}}
DEFAULT_UNIT = {"Stress": "N/m^2", "Displacement": "mm", "Strain": "", "Amplitude": "", "Thermal": "Kelvin", "Fatigue": "",
                "Factor of Safety": ""}
IPS_UNIT = {"Stress": "psi", "Displacement": "in", "Thermal": "Fahrenheit"}


def default_unit(a, quantity):
    """A new plot's unit: SI (N/m^2, mm, Kelvin), or English (IPS: psi, in, Fahrenheit) in an inch part, the same
    units as the run's report and the PMs there."""
    try:
        from . import addintabs
        if addintabs._inch_units(a) and quantity in IPS_UNIT:
            return IPS_UNIT[quantity]
    except Exception as _fw_err:
        _fw_log("simplots.py:units", _fw_err)
    return DEFAULT_UNIT[quantity]


TYPE_WORDS = {"Stress": "Static nodal stress", "Displacement": "Static displacement", "Strain": "Static strain",
              "Amplitude": "Amplitude", "Thermal": "Thermal", "Fatigue": "Fatigue", "Factor of Safety": "Factor of Safety"}
STUDY_WORDS = {"frequency": "Frequency", "buckling": "Buckling", "drop": "Dynamic"}


def units_of(quantity, comp):
    """The units a plot can show: a temperature in Kelvin, Celsius or Fahrenheit, a gradient in K/m, a flux in W/m^2."""
    if quantity == "Thermal":
        if comp.startswith("GRAD"):
            return ["K/m"]
        if comp.startswith("HFLUX"):
            return ["W/m^2"]
        return ["Kelvin", "Celsius", "Fahrenheit"]
    return list(UNITS[quantity])


def convert(quantity, comp, unit):
    """value as CalculiX gave it (MPa, mm, K, K/mm, mW/mm^2) -> the plot's unit."""
    if quantity == "Thermal":
        if comp.startswith("GRAD") or comp.startswith("HFLUX"):
            return lambda v: v * 1000.0               # K/mm -> K/m; mW/mm^2 -> W/m^2
        if unit == "Celsius":
            return lambda v: v - 273.15
        if unit == "Fahrenheit":
            return lambda v: (v - 273.15) * 1.8 + 32.0
        return lambda v: v
    k = to_unit(quantity, unit)
    return lambda v: v * k
SCALES = ("Automatic", "True scale", "User defined")
FORMATS = ("Scientific", "Floating", "General")
COLOURS = ("Default", "Rainbow", "Gray Scale", "Optimized for Colorblindness")
CHART = {"show_min": False, "show_max": False, "details": True, "format": "Scientific", "decimals": 3, "colours": "Default",

         # separator, the yield strength mark (von Mises) and one colour for every value above the yield strength
         "auto_max": True, "max_value": 0.0, "auto_min": True, "min_value": 0.0, "thousands": False, "show_yield": True,
         "above": False, "above_colour": [0.55, 0.55, 0.55],
         # Show legend; its place (Predefined positions, or % from the left and the top) and size; the number of
         # colours and Flip
         "legend": True, "pos": [80, 20], "size": "Normal", "ncolours": 10, "flip": False}
POSITIONS = {"Left": [3, 20], "Middle": [45, 20], "Right": [80, 20]}
SIZES = {"Thick": 30, "Normal": 22, "Thin": 14}

FRINGES = ("Point", "Line", "Discrete", "Continuous")
BOUNDARIES = ("None", "Model", "Mesh")
SUPERIMPOSE = ("Translucent (Part colors)", "Translucent (Single color)")
SETTINGS = {"fringe": "Continuous", "boundary": "Model", "boundary_colour": [0.0, 0.0, 0.5], "superimpose": False,
            "super_style": SUPERIMPOSE[0], "translucency": 0.9}
# Property: a plot can keep a view orientation and a title line of its own
VIEWS = ("Front", "Back", "Left", "Right", "Top", "Bottom", "Isometric")
# Define Factor of Safety Plot: step 1 the criterion, step 2 the stress limit, step 3 what the plot shows
CRITERIA = ("Max von Mises Stress", "Max Shear Stress (Tresca)", "Mohr-Coulomb Stress", "Max Normal Stress", "Automatic")
LIMITS = ("Yield strength", "Ultimate strength", "User defined")
FOS_WORDS = {"Automatic": "Max von Mises Stress"}


def chart_of(p):
    """The plot's Chart Options, with the defaults of keys an older plot does not have."""
    c = dict(CHART)
    c.update(p.get("chart") or {})
    return c


def settings_of(p):
    c = dict(SETTINGS)
    c.update(p.get("settings") or {})
    return c


def strengths(a):
    """The study's material strengths in MPa: yield, ultimate (tensile) and compressive, None where not known."""
    out = {"yield": None, "ultimate": None, "compressive": None}
    for o in a.Group:
        mat = getattr(o, "Material", None)
        if not isinstance(mat, dict) or not mat:
            continue
        for key, name in (("yield", "YieldStrength"), ("ultimate", "UltimateTensileStrength"),
                          ("compressive", "CompressiveStrength")):
            if out[key] is None and mat.get(name):
                try:
                    out[key] = App.Units.Quantity(mat[name]).getValueAs("MPa").Value or None
                except Exception:
                    out[key] = None
        if out["yield"] is None:
            try:
                from . import evaltools
                out["yield"] = float(evaltools.MATERIALS[mat.get("Name")][1])
            except Exception:
                pass
        if out["yield"] or out["ultimate"]:
            break
    return out


def criteria(a):
    """The criteria the study's material allows: Mohr-Coulomb needs a compressive strength."""
    st = strengths(a)
    return [c for c in CRITERIA if c != "Mohr-Coulomb Stress" or st["compressive"]]


def limits(a):
    st = strengths(a)
    return [l for l in LIMITS if (l != "Yield strength" or st["yield"]) and (l != "Ultimate strength" or st["ultimate"])]


def fos_limit(a, p):
    """The stress limit in MPa (times the multiplication factor). Automatic: the material's yield strength."""
    st = strengths(a)
    kind = "Yield strength" if p.get("criterion", "Automatic") == "Automatic" else p.get("limit", "Yield strength")
    base = {"Yield strength": st["yield"], "Ultimate strength": st["ultimate"]}.get(kind, p.get("limit_value"))
    if not base:
        raise RuntimeError("The material has no %s: pick another stress limit." % kind.lower())
    return float(base) * float(p.get("multiplier", 1.0) or 1.0)


def fos_values(a, res, p):
    """[(node, factor of safety)]: the limit over the criterion's stress (Mohr-Coulomb: 1 / (P1/St - P3/Sc))."""
    crit = FOS_WORDS.get(p.get("criterion", "Automatic"), p.get("criterion", "Automatic"))
    lim = fos_limit(a, p)
    nodes = list(res.NodeNumbers)
    p1, p3 = _list(res, "PrincipalMax"), _list(res, "PrincipalMin")
    if crit == "Max von Mises Stress":
        stress = _list(res, "vonMises")
    elif crit == "Max Shear Stress (Tresca)":
        stress = [x - y for x, y in zip(p1, p3)]
    elif crit == "Max Normal Stress":
        stress = [max(abs(x), abs(y)) for x, y in zip(p1, p3)]
    else:
        st = strengths(a)
        sc = float(st["compressive"] or lim) * float(p.get("multiplier", 1.0) or 1.0)
        out = []
        for n, x, y in zip(nodes, p1, p3):
            d = max(x, 0.0) / lim + max(-y, 0.0) / sc
            out.append((n, 1.0 / d if d > 0 else 1e9))
        return _capped(out, p)
    if len(stress) != len(nodes):
        raise RuntimeError("This result has no stresses for a factor of safety.")
    out = [(n, lim / v if v > 0 else 1e9) for n, v in zip(nodes, stress)]
    return _capped(out, p)


def _capped(vals, p):
    """Advanced Options > Set upper limit for Factor of Safety."""
    top = p.get("upper")
    return [(n, min(v, float(top))) for n, v in vals] if top else vals

# --------------------------------------------------------------------------- values
def result(a):
    res = [o for o in (a.Group if a is not None else []) if o.isDerivedFrom("Fem::FemResultObject")]
    if not res and a is not None and getattr(a, "FwSimType", "") == "fatigue":
        try:
            from . import simtypes
            return simtypes.fatigue_base(a)            # a fatigue study's results sit on its static study's mesh
        except Exception as _fw_err:
            _fw_log("simplots.py:fatigue", _fw_err)
    return res[-1] if res else None


def study_kind(a):
    try:
        from . import simstudy
        return simstudy._kind_of(a)
    except Exception:
        return "static"


def result_for(a, p):
    """The result object a plot shows: its mode shape (Frequency, Buckling), its time step (a transient thermal study),
    else the study's result."""
    if p.get("quantity") in ("Amplitude", "Thermal") or p.get("step"):
        try:
            from . import simtypes
            r = simtypes.result_of(a, p)
            if r is not None:
                return r
        except Exception as _fw_err:
            _fw_log("simplots.py:result_for", _fw_err)
    return result(a)


def _list(res, name):
    return list(getattr(res, name, []) or [])


def values(res, quantity, comp):
    """[(node, value)] in MPa, mm or strain, as CalculiX gave them."""
    nodes = list(res.NodeNumbers)
    if quantity == "Amplitude":
        quantity, comp = "Displacement", {"AMPRES": "URES", "AMPX": "UX", "AMPY": "UY", "AMPZ": "UZ"}[comp]
    if quantity == "Thermal":
        if comp == "TEMP":
            vals = _list(res, "Temperature")
        else:
            flux = _list(res, "HeatFlux")
            if comp.startswith("GRAD"):
                k = _conductivity(res)
                flux = [v * (-1.0 / k) for v in flux]          # Fourier: q = -k grad T
            if comp.endswith("N"):
                vals = [v.Length for v in flux]
            else:
                i = "XYZ".index(comp[-1])
                vals = [(v.x, v.y, v.z)[i] for v in flux]
    elif quantity == "Displacement":
        if comp == "URES":
            vals = _list(res, "DisplacementLengths")
        else:
            i = "XYZ".index(comp[1])
            vals = [(v.x, v.y, v.z)[i] for v in res.DisplacementVectors]
    elif quantity == "Stress":
        sxx, syy, szz = _list(res, "NodeStressXX"), _list(res, "NodeStressYY"), _list(res, "NodeStressZZ")
        sxy, sxz, syz = _list(res, "NodeStressXY"), _list(res, "NodeStressXZ"), _list(res, "NodeStressYZ")
        pick = {"VON": _list(res, "vonMises"), "P1": _list(res, "PrincipalMax"), "P2": _list(res, "PrincipalMed"),
                "P3": _list(res, "PrincipalMin"), "SX": sxx, "SY": syy, "SZ": szz, "TXY": sxy, "TXZ": sxz, "TYZ": syz}
        if comp == "INT":
            vals = [a - b for a, b in zip(_list(res, "PrincipalMax"), _list(res, "PrincipalMin"))]
        elif comp == "TRI":
            vals = [a + b + c for a, b, c in zip(_list(res, "PrincipalMax"), _list(res, "PrincipalMed"), _list(res, "PrincipalMin"))]
        else:
            vals = pick[comp]
    else:
        exx, eyy, ezz = _list(res, "NodeStrainXX"), _list(res, "NodeStrainYY"), _list(res, "NodeStrainZZ")
        exy, exz, eyz = _list(res, "NodeStrainXY"), _list(res, "NodeStrainXZ"), _list(res, "NodeStrainYZ")
        if comp == "ESTRN":

            vals = []
            for x, y, z, a, b, c in zip(exx, eyy, ezz, exy, exz, eyz):
                m = (x + y + z) / 3.0
                e1 = 0.5 * ((x - m) ** 2 + (y - m) ** 2 + (z - m) ** 2)
                e2 = ((2 * a) ** 2 + (2 * b) ** 2 + (2 * c) ** 2) / 4.0
                vals.append(2.0 * math.sqrt(max(0.0, (e1 + e2) / 3.0)))
        else:
            vals = {"EPSX": exx, "EPSY": eyy, "EPSZ": ezz, "GMXY": [2 * v for v in exy], "GMXZ": [2 * v for v in exz],
                    "GMYZ": [2 * v for v in eyz]}[comp]
    if len(vals) != len(nodes):
        raise RuntimeError("This result has no %s values." % comp)
    return list(zip(nodes, vals))


def _conductivity(res):
    """The study's thermal conductivity in mW/mm/K (= W/m/K), from its material."""
    for a in getattr(res, "InList", []) or []:
        for o in getattr(a, "Group", []) or []:
            mat = getattr(o, "Material", None)
            if isinstance(mat, dict) and mat.get("ThermalConductivity"):
                try:
                    return App.Units.Quantity(mat["ThermalConductivity"]).getValueAs("W/m/K").Value or 1.0
                except Exception:
                    return 1.0
    return 1.0


def to_unit(quantity, unit):
    return UNITS[quantity].get(unit, 1.0)


def fmt(v, chart):
    d = max(0, int(chart.get("decimals", 3)))
    f = chart.get("format", "Scientific")
    if f == "Scientific":
        return "%.*e" % (d, v)
    sep = "," if chart.get("thousands") else ""
    if f == "Floating":
        return ("{:%s.%df}" % (sep, d)).format(v)
    return ("{:%s.%dg}" % (sep, max(1, d + 1))).format(v)


CIVIDIS = ((0.0, 0.135, 0.305), (0.24, 0.30, 0.43), (0.45, 0.45, 0.47), (0.66, 0.62, 0.47), (0.88, 0.80, 0.33),
           (1.0, 0.92, 0.27))


def colour(t, scheme):
    t = max(0.0, min(1.0, t))
    if scheme in ("Grayscale", "Gray Scale"):
        return (t, t, t)
    if scheme == "Optimized for Colorblindness":       # dark blue ... grey ... yellow: no red against green
        x = t * (len(CIVIDIS) - 1)
        i = min(int(x), len(CIVIDIS) - 2)
        k = x - i
        return tuple(CIVIDIS[i][j] + (CIVIDIS[i + 1][j] - CIVIDIS[i][j]) * k for j in range(3))
    if scheme == "Rainbow":
        c = QtGui.QColor.fromHsvF((1.0 - t) * 300.0 / 360.0, 1.0, 1.0)      # violet ... red
        return (c.redF(), c.greenF(), c.blueF())
    return sx.rainbow(t)


# --------------------------------------------------------------------------- the plots kept in the study
def plots(a):
    try:
        return json.loads(getattr(a, PROP, "") or "[]")
    except ValueError:
        return []


def save_plots(a, items):
    if PROP not in a.PropertiesList:
        a.addProperty("App::PropertyString", PROP, "FreeCAD", "The study's result plots")
        a.setPropertyStatus(PROP, "Hidden")
    setattr(a, PROP, json.dumps(items))


def new_plot(a, quantity="Stress", comp=None, unit=None, deformed=True, scale="Automatic", factor=1.0, name=None, mode=None,
             step=None, **extra):
    items = plots(a)
    comp = comp or DEFAULT_COMP.get(quantity) or COMPONENTS[quantity][0][0]
    if name is None:
        base = BASE_NAME.get(quantity, quantity)
        n = 1
        while any(p["name"] == "%s%d" % (base, n) for p in items):
            n += 1
        name = "%s%d" % (base, n)
    p = {"name": name, "quantity": quantity, "comp": comp, "unit": unit or default_unit(a, quantity), "deformed": bool(deformed),
         "scale": scale, "factor": float(factor), "chart": dict(CHART), "settings": dict(SETTINGS)}
    chart, settings = extra.pop("chart", None), extra.pop("settings", None)
    p["chart"].update(chart or {})
    p["settings"].update(settings or {})
    p.update(extra)
    if quantity == "Amplitude":
        p["mode"] = int(mode or 1)
    if step:
        p["step"] = int(step)
    items.append(p)
    save_plots(a, items)
    return p


def get_plot(a, name):
    return next((p for p in plots(a) if p["name"] == name), None)


def update_plot(a, name, **values_):
    items = plots(a)
    for p in items:
        if p["name"] == name:
            chart = values_.pop("chart", None)
            settings = values_.pop("settings", None)
            p.update(values_)
            if chart:
                p.setdefault("chart", {}).update(chart)
            if settings:
                p.setdefault("settings", {}).update(settings)
    save_plots(a, items)
    return get_plot(a, name)


def delete_plot(a, name):
    save_plots(a, [p for p in plots(a) if p["name"] != name])


def defaults(a):
    ""


    if not plots(a) and result(a) is not None:
        k = study_kind(a)
        if k in ("frequency", "buckling"):
            new_plot(a, "Amplitude", deformed=True, mode=1)
        elif k == "thermomech":
            new_plot(a, "Thermal", deformed=False)
        elif k == "fatigue":
            new_plot(a, "Fatigue", "Damage", deformed=False)
            new_plot(a, "Fatigue", "Life", deformed=False)
        else:
            for q in ("Stress", "Displacement", "Strain"):
                new_plot(a, q, deformed=True)
    return plots(a)


def title(p):
    """The tree / list text: Stress1 (-vonMises-), Amplitude1 (-Res amp- Mode Shape 1-), Thermal1 (-Temperature-)."""
    if p["quantity"] == "Amplitude":
        return "%s (-%s- Mode Shape %d-)" % (p["name"], AMP_WORDS.get(p["comp"], p["comp"]), p.get("mode", 1))
    if p["quantity"] == "Factor of Safety":
        return "%s (-%s-)" % (p["name"], FOS_WORDS.get(p.get("criterion", "Automatic"), p.get("criterion", "Automatic")))
    comp = dict(COMPONENTS[p["quantity"]]).get(p["comp"], p["comp"]).split(": ", 1)[-1]
    if p["quantity"] == "Thermal" and p.get("step"):
        return "%s (-%s- Step %d-)" % (p["name"], comp, p["step"])
    return "%s (-%s-)" % (p["name"], comp)


AMP_WORDS = {"AMPRES": "Res amp", "AMPX": "X amp", "AMPY": "Y amp", "AMPZ": "Z amp"}


def _config(a):
    try:
        from . import simtree
        return simtree.config_name(a.Document)
    except Exception:
        return "Default"


def legend_head(p):
    ""
    name = "von Mises" if p["comp"] == "VON" else p["comp"]
    if p["quantity"] == "Thermal" and p["comp"] == "TEMP":
        name = "Temp"
    if p["quantity"] == "Fatigue":
        return {"Damage": "Damage", "Life": "Life (cycle)", "LoadFactor": "Load factor"}[p["comp"]]
    if p["quantity"] == "Factor of Safety":
        return "FOS"
    return "%s (%s)" % (name, p["unit"]) if p.get("unit") else name


def yield_strength(a, p):
    """The study's material yield strength in the plot's unit, or None when the material does not say."""
    for o in a.Group:
        mat = getattr(o, "Material", None)
        if not isinstance(mat, dict) or not mat:
            continue
        mpa = None
        if mat.get("YieldStrength"):
            try:
                mpa = App.Units.Quantity(mat["YieldStrength"]).getValueAs("MPa").Value
            except Exception:
                mpa = None
        if mpa is None:
            try:
                from . import evaltools
                mpa = float(evaltools.MATERIALS[mat.get("Name")][1])
            except Exception:
                mpa = None
        if mpa:
            return mpa * to_unit("Stress", p["unit"])
    return None


def auto_factor(a, res, below=False):
    ""

    obj = None
    for o in a.Group:
        if o.isDerivedFrom("Fem::FemMeshObject") and getattr(o, "Shape", None) is not None:
            obj = o.Shape
    size = obj.Shape.BoundBox.DiagonalLength if obj is not None else res.Mesh.FemMesh.BoundBox.DiagonalLength
    peak = max(_list(res, "DisplacementLengths") or [0.0])
    if peak <= 0:
        return 1.0
    raw = 0.06 * size / peak
    if raw < 1 and not below:
        return 1.0
    k = 10 ** math.floor(math.log10(raw))
    return round(raw / k) * k


def factor_of(a, res, p):
    if not p.get("deformed"):
        return 0.0
    if p.get("scale") == "True scale":
        return 1.0
    if p.get("scale") == "User defined":
        return float(p.get("factor") or 1.0)
    return auto_factor(a, res, below=p.get("quantity") == "Amplitude")


def _on_part(a, vals):
    """Only the part's nodes: a drop test adds a node for its rigid target, which is not on the part (its 0 was the
    plot's min)."""
    try:
        from . import simtree
        meshes = simtree._meshes(a)
        if not meshes:
            return vals
        n = sum(m.FemMesh.NodeCount for m in meshes)
        if len(vals) <= n:
            return vals
        ids = set()
        for m in meshes:
            ids.update(m.FemMesh.Nodes.keys())
        kept = [nv for nv in vals if nv[0] in ids]
        return kept or vals
    except Exception as _fw_err:
        _fw_log("simplots.py:onpart", _fw_err)
        return vals


def summary(a, p):
    """min / max (in the plot's unit) with their nodes."""
    res = result_for(a, p)
    if p["quantity"] == "Fatigue":
        from . import simtypes
        vals = simtypes.fatigue_values(a, p["comp"])
    elif p["quantity"] == "Factor of Safety":
        vals = fos_values(a, res, p)
    else:
        vals = values(res, p["quantity"], p["comp"])
    conv = convert(p["quantity"], p["comp"], p["unit"])
    vals = [(n, conv(v)) for n, v in vals]
    vals = _on_part(a, vals)
    peak = max((abs(v) for n, v in vals), default=0.0)
    if peak > 0:
        vals = [(n, 0.0 if abs(v) < peak * 1e-12 else v) for n, v in vals]
    lo = min(vals, key=lambda nv: nv[1])
    hi = max(vals, key=lambda nv: nv[1])
    return {"min": lo[1], "min_node": lo[0], "max": hi[1], "max_node": hi[0], "k": 1.0, "values": vals, "res": res}


def chart_colour(t, c):
    """Colour Options: the scheme, flipped when asked."""
    t = max(0.0, min(1.0, t))
    return colour(1.0 - t if c.get("flip") else t, c.get("colours", "Default"))


def chart_range(p, s):
    """The legend's range: the plot's min and max, or the values typed in Chart Options."""
    c = chart_of(p)
    lo = s["min"] if c.get("auto_min", True) else float(c.get("min_value", 0.0))
    hi = s["max"] if c.get("auto_max", True) else float(c.get("max_value", 0.0))
    if hi <= lo:
        hi = lo + (abs(lo) * 1e-6 or 1e-12)
    return lo, hi


def node_colours(a, p, s):
    """{node: (r, g, b)}: the chart's colours over its range; Areas below factor of safety: red below, blue above;
    the colour for values above the yield strength when Chart Options asks for it."""
    c = chart_of(p)
    if p["quantity"] == "Factor of Safety" and p.get("below"):
        n = float(p.get("below_value", 1.0))
        return {k: ((0.9, 0.0, 0.0) if v < n else (0.0, 0.2, 0.9)) for k, v in s["values"]}
    lo, hi = chart_range(p, s)
    span = hi - lo
    out = {k: chart_colour((v - lo) / span, c) for k, v in s["values"]}
    y = yield_strength(a, p) if c.get("above") and p["quantity"] == "Stress" and p["comp"] == "VON" else None
    if y is not None:
        above = tuple(c.get("above_colour") or CHART["above_colour"])
        for k, v in s["values"]:
            if v > y:
                out[k] = above
    return out


# =========================================================================== GUI
if Gui is not None:
    SHOWN = {"a": None, "name": None, "node": None, "marks": None, "legend": None, "title": None, "hidden": [], "factor": 1.0,
             "values": None, "drawn": None}

    class Legend(QtWidgets.QWidget):
        ""


        def __init__(self, host, head, lo, hi, chart, yield_=None, below=None):
            super().__init__(host)
            self.setObjectName("SWSimLegend")
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            self.head, self.lo, self.hi, self.chart = head, lo, hi, chart
            self.below = below
            self.discrete = False
            if below is not None:
                self.labels = ["FOS below %s" % fmt(below, dict(chart, format="General")),
                               "FOS above %s" % fmt(below, dict(chart, format="General"))]
                self.yield_, self.yield_text = None, ""
                self.resize(210, 90)
                return
            self.n = n = max(2, int(chart.get("ncolours", 10)))
            self.bar = SIZES.get(chart.get("size", "Normal"), 22)
            self.labels = [fmt(hi - (hi - lo) * k / float(n), chart) for k in range(n + 1)]

            # it on the bar with a red arrow when it falls inside the range
            self.yield_ = yield_
            self.yield_text = ("Yield strength: %s" % fmt(yield_, chart)) if yield_ is not None else ""
            self.resize(190 + self.bar, 340 if yield_ is not None else 320)

        def paintEvent(self, e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            f = p.font()
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.setPen(sx.ink())
            p.drawText(QtCore.QRect(0, 0, self.width(), 18), QtCore.Qt.AlignLeft, self.head)
            if self.below is not None:
                for k, (rgb, text) in enumerate((((230, 0, 0), self.labels[0]), ((0, 51, 230), self.labels[1]))):
                    y = 26 + 26 * k
                    p.fillRect(QtCore.QRect(12, y, 22, 18), QtGui.QColor(*rgb))
                    p.drawRect(QtCore.QRect(12, y, 22, 18))
                    p.drawText(QtCore.QPointF(42, y + 13), text)
                p.end()
                return
            top, bottom, x, w = 24, self.height() - (36 if self.yield_text else 16), 12, self.bar
            n = self.n
            if self.discrete:                       # Discrete fringe: one band a colour, as the model shows them
                for k in range(n):
                    r, g, b = chart_colour(1 - (k + 0.5) / n, self.chart)
                    y0 = top + (bottom - top) * k / float(n)
                    p.fillRect(QtCore.QRectF(x, y0, w, (bottom - top) / float(n) + 0.5), QtGui.QColor.fromRgbF(r, g, b))
            else:
                grad = QtGui.QLinearGradient(0, top, 0, bottom)
                for k in range(n + 1):
                    r, g, b = chart_colour(1 - k / float(n), self.chart)
                    grad.setColorAt(k / float(n), QtGui.QColor.fromRgbF(r, g, b))
                p.fillRect(QtCore.QRect(x, top, w, bottom - top), grad)
            p.setPen(sx.ink("line"))
            p.drawRect(QtCore.QRect(x, top, w, bottom - top))
            for k, text in enumerate(self.labels):
                y = top + (bottom - top) * k / float(n)
                p.drawLine(int(x + w), int(y), int(x + w + 4), int(y))
                p.drawText(QtCore.QPointF(x + w + 7, y + 4), text)
            if self.yield_text:

                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(QtGui.QColor(220, 0, 0))
                ty = bottom + 22
                p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x + 10, ty), QtCore.QPointF(x, ty - 5),
                                               QtCore.QPointF(x, ty + 5)]))
                p.setPen(sx.ink())
                p.drawText(QtCore.QPointF(x + 15, bottom + 26), self.yield_text)
                span = (self.hi - self.lo) or 1.0
                t = (self.hi - self.yield_) / span
                if 0.0 <= t <= 1.0:
                    y = top + (bottom - top) * t
                    p.setPen(QtCore.Qt.NoPen)
                    p.setBrush(QtGui.QColor(220, 0, 0))
                    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x - 1, y), QtCore.QPointF(x - 9, y - 5),
                                                   QtCore.QPointF(x - 9, y + 5)]))
            p.end()

    def _view(doc):
        return Gui.getDocument(doc.Name).ActiveView

    def clear():
        """The model back as it was: the plot, its marks and overlays gone, the part shown again."""
        for key in ("legend", "title"):
            w = SHOWN.get(key)
            if w is not None:
                try:
                    w.hide()
                    w.deleteLater()
                except Exception as _fw_err:
                    _fw_log("simplots.py:clear", _fw_err)
                SHOWN[key] = None
        for key in ("node", "marks"):
            m = SHOWN.get(key)
            if m is not None:
                try:
                    m[0].getSceneGraph().removeChild(m[1])
                except Exception as _fw_err:
                    _fw_log("simplots.py:clear2", _fw_err)
                if key == "marks" and len(m) > 3 and m[3] is not None:      # the Min/Max callouts' layer
                    try:
                        m[3].timer.stop()
                        m[3].hide()
                        m[3].deleteLater()
                    except RuntimeError:
                        pass
                SHOWN[key] = None
        a = SHOWN.get("a")
        if a is not None:
            try:
                for n in SHOWN["hidden"]:
                    o = a.Document.getObject(n)
                    if o is not None:
                        o.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("simplots.py:clear3", _fw_err)
        SHOWN.update(a=None, name=None, hidden=[], values=None, drawn=None)

    def _hide_model(a):
        doc = a.Document
        for o in doc.Objects:
            try:
                if not o.ViewObject.Visibility:
                    continue
                if o.isDerivedFrom("Part::Feature") or o.TypeId == "PartDesign::Body" or o.TypeId.startswith("Fem::Constraint") \
                        or o.isDerivedFrom("Fem::FemPostObject") or o.isDerivedFrom("Fem::FemMeshObject") \
                        or o.TypeId.startswith("Assembly::"):           # an assembly's components (its study's plot)
                    SHOWN["hidden"].append(o.Name)
                    o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("simplots.py:hide", _fw_err)

    def _orient(a, view_name):
        """Property > Associate plot with named view orientation."""
        try:
            v = _view(a.Document)
            getattr(v, "view" + {"Isometric": "Isometric"}.get(view_name, view_name))()
            v.fitAll()
        except Exception as _fw_err:
            _fw_log("simplots.py:orient", _fw_err)

    def show(a, name):
        """Shows the plot on the model. Returns its summary."""
        p = get_plot(a, name)
        res = result_for(a, p) if p is not None else None
        if res is None or p is None:
            raise RuntimeError("Run the study first.")
        s = summary(a, p)
        clear()                 # puts back what the last plot hid ...
        _hide_model(a)          # ... so hide it again: a second plot used to leave the part, mesh and loads showing
        factor = factor_of(a, res, p)
        chart = chart_of(p)
        lo, hi = chart_range(p, s)
        cols = node_colours(a, p, s)
        _draw(a, res, cols, factor, p, s)
        host = sx._host()
        yield_ = yield_strength(a, p) if p["quantity"] == "Stress" and p["comp"] == "VON" else None
        if host is not None:
            below = float(p.get("below_value", 1.0)) if p["quantity"] == "Factor of Safety" and p.get("below") else None
            SHOWN["legend"] = Legend(host, legend_head(p), lo, hi, chart, yield_ if chart.get("show_yield", True) else None,
                                     below)
            SHOWN["legend"].discrete = settings_of(p)["fringe"] == "Discrete"
            if chart.get("details", True):
                lines = ["Model name: %s" % (a.Document.Label or a.Document.Name), "Study name: %s(-%s-)" % (a.Label, _config(a)),
                         "Plot type: %s %s" % (_type_words(a, p), p["name"])]
                lines += _mode_lines(a, p)
                if p["quantity"] == "Factor of Safety":
                    lines.append("Criterion : %s" % FOS_WORDS.get(p.get("criterion", "Automatic"), p.get("criterion")))
                    lines.append("Factor of safety distribution: Min FOS = %.2g" % s["min"])
                    if p.get("below"):
                        lines.append("Red < FOS = %s < Blue" % fmt(float(p.get("below_value", 1.0)), dict(chart, format="General")))
                if p.get("deformed"):
                    lines.append("Deformation scale: %g" % factor)
                if p.get("title_text"):
                    lines.append(p["title_text"])
                SHOWN["title"] = sx.TitleBlock(host, lines)
            sx.PLOT["legend"], sx.PLOT["title"] = SHOWN["legend"], SHOWN["title"]
            sx._place_overlays()
            sx.PLOT["legend"] = sx.PLOT["title"] = None
            lg = SHOWN["legend"]
            if not chart.get("legend", True):
                lg.hide()
            elif chart.get("pos") and list(chart["pos"]) != CHART["pos"]:      # Position/Format: % from left and top
                px, py = chart["pos"]
                lg.move(int(max(0, min(host.width() - lg.width(), host.width() * px / 100.0))),
                        int(max(0, min(host.height() - lg.height(), host.height() * py / 100.0))))
        _marks(a, res, p, s, factor)
        if p.get("view"):
            _orient(a, p["view"])
        SHOWN.update(a=a, name=name, factor=factor, values=dict(s["values"]))
        s["factor"] = factor
        s["range"] = (lo, hi)
        s["labels"] = SHOWN["legend"].labels if SHOWN.get("legend") is not None else []
        return s

    def _type_words(a, p):
        if p["quantity"] == "Amplitude":
            return STUDY_WORDS.get(study_kind(a), "Frequency") + " Amplitude"
        if p["quantity"] == "Fatigue":
            return {"Damage": "Damage", "Life": "Life", "LoadFactor": "Load factor"}.get(p["comp"], "Fatigue")
        return TYPE_WORDS[p["quantity"]]

    def _mode_lines(a, p):
        ""

        try:
            from . import simtypes
            return simtypes.title_lines(a, p)
        except Exception as _fw_err:
            _fw_log("simplots.py:mode", _fw_err)
            return []

    # ----------------------------------------------------------------------- drawing (Settings tab)
    def bands(tris, pts, vals, cuts):
        ""

        out = []
        for t in tris:
            poly = [(pts[i], vals[i]) for i in t]
            vs = [v for _q, v in poly]
            lo, hi = min(vs), max(vs)
            inner = [c for c in cuts if lo < c < hi]
            if not inner:
                out.append(([q for q, _v in poly], sum(vs) / 3.0))
                continue
            edges = [lo] + inner + [hi]
            for b0, b1 in zip(edges[:-1], edges[1:]):
                piece = _clip(_clip(poly, b0, True), b1, False)
                if len(piece) >= 3:
                    out.append(([q for q, _v in piece], 0.5 * (b0 + b1)))
        return out

    def _clip(poly, level, keep_above):
        """Sutherland-Hodgman on the value: the part of the polygon above (or below) level."""
        out = []
        n = len(poly)
        for i in range(n):
            (p0, v0), (p1, v1) = poly[i], poly[(i + 1) % n]
            in0 = v0 >= level if keep_above else v0 <= level
            in1 = v1 >= level if keep_above else v1 <= level
            if in0:
                out.append((p0, v0))
            if in0 != in1 and v1 != v0:
                k = (level - v0) / (v1 - v0)
                out.append((tuple(p0[j] + (p1[j] - p0[j]) * k for j in range(3)), level))
        return out

    def contours(tris, pts, vals, levels):
        ""
        out = []
        for t in tris:
            for lv in levels:
                cut = []
                for i, j in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                    v0, v1 = vals[i], vals[j]
                    if (v0 - lv) * (v1 - lv) < 0:
                        k = (lv - v0) / (v1 - v0)
                        cut.append(tuple(pts[i][m] + (pts[j][m] - pts[i][m]) * k for m in range(3)))
                if len(cut) == 2:
                    out.append((lv, cut[0], cut[1]))
        return out

    def edges_of(tris, pts, model=False, angle=30.0):
        """The surface's edges (Mesh boundary), or only those where it bends more than angle and open ones
        (Model boundary)."""
        seen = {}
        for t in tris:
            for i, j in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                seen.setdefault((min(i, j), max(i, j)), []).append(t)
        if not model:
            return list(seen)
        cos = math.cos(math.radians(angle))

        def normal(t):
            a, b, c = (App.Vector(*pts[k]) for k in t)
            n = (b - a).cross(c - a)
            return n.normalize() if n.Length > 0 else n
        out = []
        for e, ts in seen.items():
            if len(ts) != 2 or abs(normal(ts[0]).dot(normal(ts[1]))) < cos:     # either winding (a mesh's faces need not agree)
                out.append(e)
        return out

    def _draw(a, res, cols, factor, p=None, s=None):
        from pivy import coin
        view = _view(a.Document)
        tris = sx.surface(res)
        ids = sorted({n for t in tris for n in t})
        index = {n: i for i, n in enumerate(ids)}
        st = settings_of(p) if p is not None else dict(SETTINGS)
        fringe = st["fringe"]
        nc = max(2, int(chart_of(p).get("ncolours", 10))) if p is not None else 10
        if p is not None and not p.get("show_colors", True):        # Deformed shape without Show colors
            cols = {}
            fringe = "Continuous"
        pts = sx._points(res, ids, factor)
        local = [(index[t[0]], index[t[1]], index[t[2]]) for t in tris]
        flat = []
        for t in local:
            flat.extend((t[0], t[1], t[2], -1))
        root = coin.SoSeparator()
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        root.addChild(hints)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(ids), pts)
        root.addChild(coords)
        vals = None
        if s is not None:
            sv = dict(s["values"])
            vals = [sv.get(n, s["min"]) for n in ids]
        grey = (0.82, 0.82, 0.82)
        faces = coin.SoSeparator()
        if fringe == "Discrete" and vals is not None and p is not None:
            lo, hi = chart_range(p, s)
            cuts = [lo + (hi - lo) * k / float(nc) for k in range(1, nc)]
            extra = []
            y = yield_strength(a, p) if chart_of(p).get("above") and p["quantity"] == "Stress" and p["comp"] == "VON" else None
            if y is not None:
                extra.append(y)
            if p["quantity"] == "Factor of Safety" and p.get("below"):
                cuts = [float(p.get("below_value", 1.0))]
            pieces = bands(local, pts, vals, sorted(cuts + extra))
            pc = coin.SoCoordinate3()
            fl, colours_, at = [], [], 0
            allp = []
            probe = {}
            for poly, mid in pieces:
                allp.extend(poly)
                fl.extend(list(range(at, at + len(poly))) + [-1])
                at += len(poly)
                colours_.append(_band_colour(a, p, s, mid, lo, hi, probe, nc))
            pc.point.setValues(0, len(allp), allp)
            mat = coin.SoMaterial()
            mat.diffuseColor.setValues(0, len(colours_), colours_)
            bind = coin.SoMaterialBinding()
            bind.value = coin.SoMaterialBinding.PER_FACE
            fs = coin.SoIndexedFaceSet()
            fs.coordIndex.setValues(0, len(fl), fl)
            for n in (pc, mat, bind, fs):
                faces.addChild(n)
        else:
            mat = coin.SoMaterial()
            if fringe == "Continuous":
                mat.diffuseColor.setValues(0, len(ids), [cols.get(n, (0.7, 0.7, 0.7)) for n in ids])
                bind = coin.SoMaterialBinding()
                bind.value = coin.SoMaterialBinding.PER_VERTEX_INDEXED
                faces.addChild(mat)
                faces.addChild(bind)
            else:                                   # Point and Line draw their colours on a plain model
                mat.diffuseColor.setValue(*grey)
                faces.addChild(mat)
            fs = coin.SoIndexedFaceSet()
            fs.coordIndex.setValues(0, len(flat), flat)
            faces.addChild(fs)
        off = coin.SoPolygonOffset()                # edges and iso-lines drawn over the faces
        root.addChild(off)
        root.addChild(faces)
        if fringe == "Line" and vals is not None and p is not None:
            lo, hi = chart_range(p, s)
            levels = [lo + (hi - lo) * k / float(nc) for k in range(1, nc)]
            segs = contours(local, pts, vals, levels)
            if segs:
                ls = coin.SoSeparator()
                lc = coin.SoCoordinate3()
                lc.point.setValues(0, 2 * len(segs), [q for _l, q0, q1 in segs for q in (q0, q1)])
                lm = coin.SoMaterial()
                cc = chart_of(p)
                lm.diffuseColor.setValues(0, len(segs), [chart_colour((lv - lo) / (hi - lo), cc) for lv, _a, _b in segs])
                lb = coin.SoMaterialBinding()
                lb.value = coin.SoMaterialBinding.PER_PART
                dst = coin.SoDrawStyle()
                dst.lineWidth = 2
                lset = coin.SoLineSet()
                lset.numVertices.setValues(0, len(segs), [2] * len(segs))
                for n in (dst, lc, lm, lb, lset):
                    ls.addChild(n)
                root.addChild(ls)
        if fringe == "Point":
            ps = coin.SoSeparator()
            pm = coin.SoMaterial()
            pm.diffuseColor.setValues(0, len(ids), [cols.get(n, (0.6, 0.6, 0.6)) for n in ids])
            pb = coin.SoMaterialBinding()
            pb.value = coin.SoMaterialBinding.PER_VERTEX
            dst = coin.SoDrawStyle()
            dst.pointSize = 5
            pset = coin.SoPointSet()
            pset.numPoints = len(ids)
            for n in (dst, pm, pb, pset):
                ps.addChild(n)
            root.addChild(ps)
        if st["boundary"] in ("Model", "Mesh"):
            es = edges_of(local, pts, model=st["boundary"] == "Model")
            if es:
                bs = coin.SoSeparator()
                bm = coin.SoMaterial()
                bm.diffuseColor.setValue(*(st.get("boundary_colour") or SETTINGS["boundary_colour"]))
                lm = coin.SoLightModel()
                lm.model = coin.SoLightModel.BASE_COLOR
                il = coin.SoIndexedLineSet()
                ix = []
                for i, j in es:
                    ix.extend((i, j, -1))
                il.coordIndex.setValues(0, len(ix), ix)
                for n in (lm, bm, il):
                    bs.addChild(n)
                root.addChild(bs)
        if p is not None and p.get("vector") and p["quantity"] == "Displacement":
            root.addChild(_arrows(res, ids, pts, cols))
        if st["superimpose"] and factor:            # the model as it was, see-through, under the deformed plot
            ss = coin.SoSeparator()
            sc = coin.SoCoordinate3()
            sc.point.setValues(0, len(ids), sx._points(res, ids, 0.0))
            sm = coin.SoMaterial()
            sm.diffuseColor.setValue(*(_part_colour(a) if st.get("super_style", SUPERIMPOSE[0]) == SUPERIMPOSE[0]
                                       else (0.6, 0.6, 0.65)))
            sm.transparency = max(0.0, min(0.95, float(st.get("translucency", 0.9))))
            sf = coin.SoIndexedFaceSet()
            sf.coordIndex.setValues(0, len(flat), flat)
            for n in (sc, sm, sf):
                ss.addChild(n)
            root.addChild(ss)
        view.getSceneGraph().addChild(root)
        SHOWN["node"] = (view, root, coords, ids)
        SHOWN["drawn"] = (ids, pts)

    def _part_colour(a):
        """Translucent (Part colors): the colour of the part the study solves."""
        for n in SHOWN.get("hidden") or []:
            o = a.Document.getObject(n)
            if o is not None and (o.isDerivedFrom("Part::Feature") or o.TypeId == "PartDesign::Body"):
                try:
                    c = o.ViewObject.ShapeColor
                    return (c[0], c[1], c[2])
                except Exception:
                    break
        return (0.8, 0.8, 0.8)

    def _band_colour(a, p, s, mid, lo, hi, _cache, nc=10):
        c = chart_of(p)
        if p["quantity"] == "Factor of Safety" and p.get("below"):
            return (0.9, 0.0, 0.0) if mid < float(p.get("below_value", 1.0)) else (0.0, 0.2, 0.9)
        if c.get("above") and p["quantity"] == "Stress" and p["comp"] == "VON":
            if "y" not in _cache:
                _cache["y"] = yield_strength(a, p)
            if _cache["y"] is not None and mid > _cache["y"]:
                return tuple(c.get("above_colour") or CHART["above_colour"])
        t = (mid - lo) / ((hi - lo) or 1.0)
        return chart_colour((math.floor(max(0.0, min(0.999999, t)) * nc) + 0.5) / nc, c)

    def _arrows(res, ids, pts, cols, most=400):
        """Show as vector plot: an arrow at each of up to 400 surface nodes, along its displacement, sized by it."""
        from pivy import coin
        at = {n: i for i, n in enumerate(res.NodeNumbers)}
        dv = res.DisplacementVectors
        peak = max([dv[at[n]].Length for n in ids if n in at] or [0.0]) or 1.0
        box = res.Mesh.FemMesh.BoundBox
        size = 0.06 * box.DiagonalLength
        step = max(1, len(ids) // most)
        sep = coin.SoSeparator()
        lc, cl = [], []
        cones = coin.SoSeparator()
        for k in range(0, len(ids), step):
            n = ids[k]
            if n not in at:
                continue
            u = dv[at[n]]
            if u.Length <= 0:
                continue
            d = App.Vector(u).normalize()
            length = size * (0.25 + 0.75 * u.Length / peak)
            q0 = App.Vector(*pts[k])
            q1 = q0 + d * length
            lc.extend([(q0.x, q0.y, q0.z), (q1.x, q1.y, q1.z)])
            cl.append(cols.get(n, (0.2, 0.2, 0.2)))
            c = coin.SoSeparator()
            tr = coin.SoTransform()
            tr.translation = (q1.x, q1.y, q1.z)
            tr.rotation.setValue(coin.SbRotation(coin.SbVec3f(0, 1, 0), coin.SbVec3f(d.x, d.y, d.z)))
            m = coin.SoMaterial()
            m.diffuseColor.setValue(*cols.get(n, (0.2, 0.2, 0.2)))
            cone = coin.SoCone()
            cone.height = length * 0.3
            cone.bottomRadius = length * 0.1
            for x in (tr, m, cone):
                c.addChild(x)
            cones.addChild(c)
        if lc:
            co = coin.SoCoordinate3()
            co.point.setValues(0, len(lc), lc)
            m = coin.SoMaterial()
            m.diffuseColor.setValues(0, len(cl), cl)
            b = coin.SoMaterialBinding()
            b.value = coin.SoMaterialBinding.PER_PART
            ls = coin.SoLineSet()
            ls.numVertices.setValues(0, len(cl), [2] * len(cl))
            for x in (co, m, b, ls):
                sep.addChild(x)
        sep.addChild(cones)
        return sep

    def _marks(a, res, p, s, factor):
        chart = chart_of(p)
        items = []
        if chart.get("show_max", False):
            items.append(("Max: " + fmt(s["max"], chart), s["max_node"]))
        if chart.get("show_min", False):
            items.append(("Min: " + fmt(s["min"], chart), s["min_node"]))
        if not items:
            return
        from pivy import coin
        view = _view(a.Document)
        root = coin.SoAnnotation()            # the node itself: a small dot the callout's leader ends on
        points = []
        for text, node in items:
            q = sx._node_at(res, node, factor)
            points.append((text, App.Vector(q.x, q.y, q.z)))
            sep = coin.SoSeparator()
            col = coin.SoBaseColor()
            col.rgb = (0.0, 0.0, 0.0)
            style = coin.SoDrawStyle()
            style.pointSize = 5
            coords = coin.SoCoordinate3()
            coords.point.setValue(q.x, q.y, q.z)
            for n in (col, style, coords, coin.SoPointSet()):
                sep.addChild(n)
            root.addChild(sep)
        view.getSceneGraph().addChild(root)
        host = sx._host()
        box = Callouts(host, view, points) if host is not None else None
        SHOWN["marks"] = (view, root, [t for t, _n in items], box)

    class Callouts(QtWidgets.QWidget):
        ""


        def __init__(self, host, view, points):
            super().__init__(host)
            self.setObjectName("SWSimCallouts")
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
            self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
            self.view, self.points, self.at = view, points, []
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.place)
            self.timer.start(120)
            self.place()
            self.show()
            self.raise_()

        def place(self):
            host = self.parentWidget()
            if host is None:
                return
            if self.geometry() != host.rect():
                self.setGeometry(host.rect())
            ratio = host.devicePixelRatioF() if hasattr(host, "devicePixelRatioF") else 1.0
            at = []
            try:
                for text, q in self.points:
                    x, y = self.view.getPointOnViewport(q)
                    at.append((text, QtCore.QPointF(x / ratio, host.height() - y / ratio)))
            except Exception:
                at = []
            if at != self.at:
                self.at = at
                self.update()

        def boxes(self):
            """(text, node point, box rectangle) of each callout: up and right of its node, kept inside the view.
            A text of several lines (a Probe flag: Node, X,Y,Z, Value) makes a taller box."""
            fm = QtGui.QFontMetrics(self.font())
            out = []
            for k, (text, q) in enumerate(self.at):
                lines = text.split("\n")
                w, h = max(fm.horizontalAdvance(t) for t in lines) + 12, fm.height() * len(lines) + 6
                x = q.x() + 40
                y = q.y() - 46 - (h + 6) * k
                if x + w > self.width() - 4:
                    x = q.x() - 40 - w
                y = max(4, min(self.height() - h - 4, y))
                out.append((text, q, QtCore.QRectF(x, y, w, h)))
            return out

        def paintEvent(self, e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            for text, q, r in self.boxes():
                end = QtCore.QPointF(r.left() if r.left() > q.x() else r.right(), r.bottom())
                p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1))
                p.drawLine(q, end)
                p.setBrush(QtGui.QColor(255, 255, 225))
                p.drawRect(r)
                p.drawText(r, QtCore.Qt.AlignCenter if "\n" not in text else QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
                           text if "\n" not in text else "\n".join(" " + t for t in text.split("\n")))
            p.end()

    # ----------------------------------------------------------------------- probe
    def probe_at(a, name, point):
        """The probe row at a picked point: (node, value in the plot's unit, x, y, z) of the nearest node."""
        p = get_plot(a, name)
        s = summary(a, p)
        res = s["res"]
        mesh = res.Mesh.FemMesh
        best = None
        for n, v in s["values"]:
            q = mesh.getNodeById(n)
            d = (q - point).Length
            if best is None or d < best[0]:
                best = (d, n, v, q)
        _d, n, v, q = best
        return (n, v, q.x, q.y, q.z)

    def pick_drawn(view, root, position):
        """The point of the shown plot under a viewport position (Coin's, from the bottom left), or None. The ray
        goes through the whole scene (the camera is there, not under the plot's own node); the first hit on the
        plot counts, so the part or its edges drawn in front do not hide it."""
        from pivy import coin
        rm = view.getViewer().getSoRenderManager()
        rp = coin.SoRayPickAction(rm.getViewportRegion())
        rp.setPoint(position)
        rp.setRadius(3)
        rp.setPickAll(True)
        rp.apply(rm.getSceneGraph())
        for pp in rp.getPickedPointList() or []:
            path = pp.getPath()
            if path is None:
                continue
            cut = any(str(path.getNode(i).getName()) == "SWSimPlotCut" for i in range(path.getLength()))
            if cut or path.containsNode(root):    # the plot, or its clipped cut (simplotview)
                q = pp.getPoint()
                return (q[0], q[1], q[2])
        return None

    def node_on_screen(view, position, radius=8):
        """The shown plot's front-most drawn node within radius pixels of a viewport position (Coin's, from the
        bottom left), or None: the click's node when the ray pick hits nothing (a clip plane left on, a view
        that has not redrawn yet)."""
        drawn = SHOWN.get("drawn")
        if not drawn:
            return None
        try:
            import numpy as np
            from pivy import coin
            rm = view.getViewer().getSoRenderManager()
            vpr = rm.getViewportRegion()
            w, h = vpr.getViewportSizePixels().getValue()
            cam = rm.getCamera()
            vv = cam.getViewVolume(float(w) / float(h or 1))
            m = np.array([[vv.getMatrix().getValue()[i][j] for j in range(4)] for i in range(4)])
            ids, pts = drawn
            P = np.c_[np.asarray(pts, dtype=float), np.ones(len(pts))] @ m     # Coin: row vectors
            P = P[:, :3] / P[:, 3:4]
            sx = (P[:, 0] + 1.0) * 0.5 * w
            sy = (P[:, 1] + 1.0) * 0.5 * h
            x, y = position[0], position[1]
            d2 = (sx - x) ** 2 + (sy - y) ** 2
            near = np.nonzero(d2 <= radius * radius)[0]
            if not len(near):
                return None
            best = near[np.argmin(P[near, 2])]                               # nearest the camera
            return ids[int(best)]
        except Exception as _fw_err:
            _fw_log("simplots.py:node_on_screen", _fw_err)
            return None

    def node_at_drawn(point):
        """The shown plot's node nearest a point on the drawn (deformed) surface."""
        drawn = SHOWN.get("drawn")
        if not drawn:
            return None
        ids, pts = drawn
        x, y, z = point
        best = min(range(len(ids)), key=lambda i: (pts[i][0] - x) ** 2 + (pts[i][1] - y) ** 2 + (pts[i][2] - z) ** 2)
        return ids[best]

    def row_of(a, name, node):
        p = get_plot(a, name)
        s = summary(a, p)
        v = dict(s["values"]).get(node)
        q = s["res"].Mesh.FemMesh.getNodeById(node)
        return (node, v, q.x, q.y, q.z)

    def _study_mesh(res):
        """The study's own mesh object (it knows the part it meshes; the result's copy of the mesh does not)."""
        for a in getattr(res, "InList", []) or []:
            for o in getattr(a, "Group", []) or []:
                if o.isDerivedFrom("Fem::FemMeshObject") and getattr(o, "Shape", None) is not None:
                    return o
        m = getattr(res, "Mesh", None)
        return m if getattr(m, "Shape", None) is not None else None

    def _meshed_shape(res):
        m = _study_mesh(res)
        return getattr(m, "Shape", None) if m is not None else None

    def entity_nodes(res, sub):
        """The mesh nodes on a face, edge or vertex of the meshed part."""
        obj = _meshed_shape(res)
        if obj is None:
            return []
        fm = _study_mesh(res).FemMesh
        el = obj.Shape.getElement(sub)
        if sub.startswith("Face"):
            return list(fm.getNodesByFace(el))
        if sub.startswith("Edge"):
            return list(fm.getNodesByEdge(el))
        return list(fm.getNodesByVertex(el))

    def face_at(res, node):
        """The meshed part's face a node lies on (the closest one)."""
        obj = _meshed_shape(res)
        if obj is None:
            return None
        import Part
        q = res.Mesh.FemMesh.getNodeById(node)
        v = Part.Vertex(q)
        best = None
        for i, f in enumerate(obj.Shape.Faces, 1):
            d = f.distToShape(v)[0]
            if best is None or d < best[0]:
                best = (d, "Face%d" % i)
        return best[1] if best else None

    def selected_summary(rows):
        """Probe > On selected entities: Sum, Avg, Max, Min and RMS of the rows' values."""
        vs = [r[1] for r in rows if r[1] is not None]
        if not vs:
            return {}
        return {"Sum": sum(vs), "Avg": sum(vs) / len(vs), "Max": max(vs), "Min": min(vs),
                "RMS": math.sqrt(sum(v * v for v in vs) / len(vs))}

    def write_rows(path, p, rows):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Node", "%s (%s)" % (p["comp"], p["unit"]) if p["unit"] else p["comp"], "X (mm)", "Y (mm)", "Z (mm)"])
            for r in rows:
                w.writerow([r[0], "%.6g" % r[1], "%.4f" % r[2], "%.4f" % r[3], "%.4f" % r[4]])
        return path

    # ----------------------------------------------------------------------- PMs
    def _box(title, pm=None):
        return sx._box(title, None, pm)

    def box_visible(w, on):
        """A PM box with its task box frame and title row: hiding only the box leaves its empty header (the other
        tabs' boxes showed as bare headers)."""
        try:
            w.setVisible(on)
            g = w.parentWidget()
            while g is not None and not g.inherits("QSint::ActionGroup"):
                g = g.parentWidget()
            if g is not None and g.isHidden() == on:
                g.setVisible(on)
        except RuntimeError as _fw_err:
            _fw_log("simplots.py:box", _fw_err)

    def picture(kind, size=24):
        ""

        pm = QtGui.QPixmap(size, size)
        pm.fill(QtCore.Qt.transparent)
        g = QtGui.QPainter(pm)
        g.setRenderHint(QtGui.QPainter.Antialiasing)
        ink, blue = QtGui.QColor("#3c4654"), QtGui.QColor("#2f6fd0")
        g.setPen(QtGui.QPen(ink, 1.4))
        k = size / 24.0
        def R(x, y, w, h):
            return QtCore.QRectF(x * k, y * k, w * k, h * k)
        if kind in ("Left", "Middle", "Right"):
            g.setBrush(QtGui.QColor("#ffffff"))
            g.drawRect(R(2, 4, 20, 16))
            x = {"Left": 4, "Middle": 10.5, "Right": 17}[kind]
            grad = QtGui.QLinearGradient(0, 6 * k, 0, 18 * k)
            for t, c in ((0, "#ff2020"), (0.35, "#ffd020"), (0.65, "#20d040"), (1, "#2040ff")):
                grad.setColorAt(t, QtGui.QColor(c))
            g.setPen(QtCore.Qt.NoPen)
            g.setBrush(QtGui.QBrush(grad))
            g.drawRect(R(x, 6, 3, 12))
        elif kind == "Save":
            g.setBrush(blue)
            g.drawRoundedRect(R(3, 3, 18, 18), 2, 2)
            g.setBrush(QtGui.QColor("#ffffff"))
            g.drawRect(R(7, 3, 10, 6))
            g.drawRect(R(6, 13, 12, 8))
        elif kind == "Plot":
            g.drawLine(QtCore.QPointF(4 * k, 3 * k), QtCore.QPointF(4 * k, 20 * k))
            g.drawLine(QtCore.QPointF(4 * k, 20 * k), QtCore.QPointF(21 * k, 20 * k))
            g.setPen(QtGui.QPen(blue, 2))
            pts = [(5, 17), (9, 12), (13, 14), (17, 7), (21, 5)]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                g.drawLine(QtCore.QPointF(x1 * k, y1 * k), QtCore.QPointF(x2 * k, y2 * k))
        elif kind == "Capture":
            g.setBrush(QtGui.QColor("#5d6b80"))
            g.drawRoundedRect(R(2, 7, 20, 13), 2, 2)
            g.drawRect(R(8, 4, 8, 4))
            g.setBrush(QtGui.QColor("#cfe3ff"))
            g.drawEllipse(R(8, 9, 8, 8))
        elif kind == "Copy":
            g.setBrush(QtGui.QColor("#ffffff"))
            g.drawRect(R(3, 2, 12, 15))
            g.drawRect(R(9, 7, 12, 15))
            g.setPen(QtGui.QPen(blue, 1.2))
            for y in (11, 14, 17):
                g.drawLine(QtCore.QPointF(11 * k, y * k), QtCore.QPointF(19 * k, y * k))
        g.end()
        return QtGui.QIcon(pm)

    def pic_button(kind, name, tip):
        b = QtWidgets.QToolButton()
        b.setObjectName(name)
        b.setIcon(picture(kind))
        b.setIconSize(QtCore.QSize(24, 24))
        b.setToolTip(tip)
        b.setText(tip)
        b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        return b

    def bare_box(w):
        ""

        try:
            box = w
            while box is not None and not box.inherits("QSint::ActionGroup"):
                box = box.parentWidget()
            if box is None:
                return False
            for header in box.findChildren(QtWidgets.QWidget):
                if header.inherits("QSint::TaskHeader"):
                    header.hide()
                    return True
        except RuntimeError as _fw_err:
            _fw_log("simplots.py:bare", _fw_err)
        return False

    def _later(fn):
        """Again once the task pane has framed the boxes (the frames do not exist while the PM is built)."""
        QtCore.QTimer.singleShot(0, fn)

    PLOT_TITLES = {"Stress": "Stress plot", "Displacement": "Displacement plot", "Strain": "Strain plot",
                   "Amplitude": "Mode Shape/Displacement Plot", "Thermal": "Thermal Plot", "Fatigue": "Fatigue Plot",
                   "Factor of Safety": "Factor of Safety"}
    TABS = ("Definition", "Chart Options", "Settings")

    class _Colour(QtWidgets.QPushButton):
        """A colour swatch button (Chart Options > the colour for values above the yield strength)."""

        def __init__(self, rgb, name):
            super().__init__("")
            self.setObjectName(name)
            self.setFixedWidth(48)
            self.set(rgb)
            self.clicked.connect(self._pick)

        def set(self, rgb):
            self.rgb = [float(x) for x in rgb]
            c = QtGui.QColor.fromRgbF(*self.rgb)
            self.setStyleSheet("QPushButton { background: %s; border: 1px solid #555; }" % c.name())

        def _pick(self):
            c = QtWidgets.QColorDialog.getColor(QtGui.QColor.fromRgbF(*self.rgb), self, "Color")
            if c.isValid():
                self.set((c.redF(), c.greenF(), c.blueF()))

    class PlotPM:
        ""



        def __init__(self, a, name=None, quantity=None, tab="Definition"):
            self.a, self.name = a, name
            p = get_plot(a, name) if name else None
            self.p = p
            kinds = KINDS.get(study_kind(a), KINDS["static"])
            q = p["quantity"] if p else (quantity if quantity in kinds else kinds[0])
            self.q = q
            chart = chart_of(p) if p else dict(CHART)
            st = settings_of(p) if p else dict(SETTINGS)
            # the tabs, as the PM's first row
            self.tab_box = _box("Plot", PLOT_TITLES.get(q, "Plot"))
            tl = QtWidgets.QVBoxLayout(self.tab_box)
            tl.setContentsMargins(0, 0, 0, 0)
            self.tabs = QtWidgets.QTabBar()
            self.tabs.setObjectName("SWSimPlotTabs")
            self.tabs.setDrawBase(False)
            self.tabs.setExpanding(True)
            self.tabs.setUsesScrollButtons(False)       # all three fit; its scroll arrows would sit there greyed
            self.tab_names = [t for t in TABS if t != "Definition" or q != "Factor of Safety"]
            for t in self.tab_names:
                self.tabs.addTab(t)
            tl.addWidget(self.tabs)
            self.pages = {t: [] for t in self.tab_names}
            if "Definition" in self.pages:
                self._definition(a, p, q, kinds)
            self._chart(a, p, q, chart)
            self._settings(p, q, st)
            self.form = [self.tab_box] + [w for t in self.tab_names for w in self.pages[t]]
            self.tabs.currentChanged.connect(self._tab)
            self.go(tab if tab in self.tab_names else self.tab_names[0])
            _later(lambda: self._alive() and self._tab(self.tabs.currentIndex()))
            _later(lambda: self._alive() and bare_box(self.tab_box))

        def _alive(self):
            try:
                self.tabs.objectName()
                return True
            except RuntimeError:
                return False

        # -- tabs
        def go(self, tab):
            self.tabs.setCurrentIndex(self.tab_names.index(tab))
            self._tab(self.tab_names.index(tab))

        def _tab(self, i):
            cur = self.tab_names[i]
            for t, boxes in self.pages.items():
                for w in boxes:
                    box_visible(w, t == cur and not w.property("fw_off"))
            if cur == "Definition":
                self._enable()
            self._chart_enable()

        def current_tab(self):
            return self.tab_names[self.tabs.currentIndex()]

        def _off(self, w, off):
            """A box this plot has no use for (a Thermal plot's Deformed shape): kept hidden on every tab."""
            w.setProperty("fw_off", bool(off))
            if off:
                box_visible(w, False)

        # -- Definition
        def _definition(self, a, p, q, kinds):
            disp = _box("Display")
            form = QtWidgets.QFormLayout(disp)
            self.quantity = QtWidgets.QComboBox()
            self.quantity.setObjectName("SWSimPlotQuantity")
            self.quantity.addItems(list(kinds))
            self.mode = QtWidgets.QSpinBox()            # Mode Shape (Frequency, Buckling) or the time step (transient)
            self.mode.setObjectName("SWSimPlotMode")
            self.mode.setRange(1, 1)
            self.comp = QtWidgets.QComboBox()
            self.comp.setObjectName("SWSimPlotComponent")
            self.unit = QtWidgets.QComboBox()
            self.unit.setObjectName("SWSimPlotUnit")
            if len(kinds) > 1 and p is None:
                form.addRow("Plot:", self.quantity)
            else:
                self.quantity.hide()
            form.addRow("Component:", self.comp)
            self.unit_label = QtWidgets.QLabel("Units:")
            form.addRow(self.unit_label, self.unit)
            self.steps = []
            try:
                from . import simtypes
                self.steps = simtypes.steps(a, q)            # [(number, words)] of the mode shapes or time steps
            except Exception as _fw_err:
                _fw_log("simplots.py:steps", _fw_err)
            if self.steps:
                self.mode.setRange(1, len(self.steps))
                self.mode_label = QtWidgets.QLabel("")
                self.mode.valueChanged.connect(self._mode_words)
                form.addRow("Mode Shape:" if q == "Amplitude" else "Plot step:", self.mode)
                form.addRow("", self.mode_label)
            adv = _box("Advanced Options")
            al = QtWidgets.QVBoxLayout(adv)
            self.vector = QtWidgets.QCheckBox("Show as vector plot")
            self.vector.setObjectName("SWSimPlotVector")
            al.addWidget(self.vector)
            self.adv = adv
            dfm = _box("Deformed shape")
            dl = QtWidgets.QVBoxLayout(dfm)
            self.deformed = QtWidgets.QCheckBox("Deformed shape")
            self.deformed.setObjectName("SWSimPlotDeformed")
            self.scales = {}
            for s in SCALES:
                b = QtWidgets.QRadioButton(s)
                b.setObjectName("SWSimPlotScale" + s.replace(" ", ""))
                self.scales[s] = b
                dl.addWidget(b)
            self.factor = QtWidgets.QDoubleSpinBox()
            self.factor.setObjectName("SWSimPlotFactor")
            self.factor.setRange(0.0, 1e9)
            self.factor.setDecimals(3)
            self.factor.setValue(1.0)
            dl.insertWidget(0, self.deformed)
            dl.addWidget(self.factor)
            self.show_colors = QtWidgets.QCheckBox("Show colors")       # a displacement plot's: off, the shape alone
            self.show_colors.setObjectName("SWSimPlotShowColors")
            dl.addWidget(self.show_colors)
            self.dfm = dfm
            prop = _box("Property")
            pl = QtWidgets.QVBoxLayout(prop)
            self.view_on = QtWidgets.QCheckBox("Associate plot with named view orientation")
            self.view_on.setObjectName("SWSimPlotViewOn")
            self.view = QtWidgets.QComboBox()
            self.view.setObjectName("SWSimPlotView")
            self.view.addItems(list(VIEWS))
            self.title_on = QtWidgets.QCheckBox("Include title text:")
            self.title_on.setObjectName("SWSimPlotTitleOn")
            self.title_text = QtWidgets.QLineEdit()
            self.title_text.setObjectName("SWSimPlotTitleText")
            for w in (self.title_on, self.title_text, self.view_on, self.view):
                pl.addWidget(w)
            self.pages["Definition"] = [disp, adv, dfm, prop]
            self.quantity.currentTextChanged.connect(self._quantity)
            self.deformed.toggled.connect(self._enable)
            self.view_on.toggled.connect(self._enable)
            self.title_on.toggled.connect(self._enable)
            for b in self.scales.values():
                b.toggled.connect(self._enable)
            self.quantity.setCurrentText(q)
            self._quantity(q)
            self.comp.currentIndexChanged.connect(self._units)
            if p:
                self.comp.setCurrentIndex([c for c, _l in COMPONENTS[q]].index(p["comp"]))
                self._units()
                self.unit.setCurrentText(p["unit"])
                self.mode.setValue(int(p.get("mode") or p.get("step") or (len(self.steps) if q == "Thermal" else 1)))
                self.deformed.setChecked(p["deformed"])
                self.scales[p["scale"]].setChecked(True)
                self.factor.setValue(p["factor"])
                self.vector.setChecked(bool(p.get("vector")))
                self.view_on.setChecked(bool(p.get("view")))
                self.view.setCurrentText(p.get("view") or "Isometric")
                self.title_on.setChecked(bool(p.get("title_text")))
                self.title_text.setText(p.get("title_text") or "")
                self.show_colors.setChecked(p.get("show_colors", True))
            else:
                self.deformed.setChecked(q not in ("Thermal", "Fatigue"))
                self.scales["Automatic"].setChecked(True)
                self.mode.setValue(len(self.steps) if q == "Thermal" else 1)
                self.view.setCurrentText("Isometric")
                self.show_colors.setChecked(True)
            self._mode_words()

        def _mode_words(self, *_a):
            if self.steps and hasattr(self, "mode_label"):
                self.mode_label.setText(self.steps[self.mode.value() - 1][1])

        def _quantity(self, q):
            self.q = q
            self.comp.clear()
            self.comp.addItems([l for _c, l in COMPONENTS[q]])
            self._units()
            if hasattr(self, "tab_box"):
                self.tab_box.setProperty("swstyle_pm_title", PLOT_TITLES.get(q, "Plot"))

            self._off(self.dfm, q in ("Thermal", "Fatigue"))
            self._off(self.adv, q != "Displacement")
            if hasattr(self, "tabs"):
                self._tab(self.tabs.currentIndex())

        def _units(self, *_a):
            q = self.quantity.currentText()
            i = max(0, self.comp.currentIndex())
            units = units_of(q, COMPONENTS[q][i][0])
            self.unit.clear()
            self.unit.addItems(units)
            want = default_unit(getattr(self, "a", None), q)
            self.unit.setCurrentText(want if want in units else DEFAULT_UNIT[q] if DEFAULT_UNIT[q] in units else units[0])
            one = len(units) < 2                    # no choice: no Units row (a one-entry combo is a dead control)
            self.unit.setVisible(not one)
            self.unit_label.setVisible(not one)

        def _enable(self, *_a):
            if not hasattr(self, "deformed"):
                return
            on = self.deformed.isChecked()
            for b in self.scales.values():
                b.setVisible(on)
            self.factor.setVisible(on and self.scales["User defined"].isChecked())
            self.show_colors.setVisible(on and self.quantity.currentText() == "Displacement")
            self.view.setVisible(self.view_on.isChecked())
            self.title_text.setVisible(self.title_on.isChecked())

        # -- Chart Options
        def _chart(self, a, p, q, c):
            disp = _box("Display Options")
            dl = QtWidgets.QVBoxLayout(disp)
            self.show_min = QtWidgets.QCheckBox("Show min annotation")
            self.show_min.setObjectName("SWSimChartMin")
            self.show_max = QtWidgets.QCheckBox("Show max annotation")
            self.show_max.setObjectName("SWSimChartMax")
            self.details = QtWidgets.QCheckBox("Show plot details")
            self.details.setObjectName("SWSimChartDetails")
            self.legend = QtWidgets.QCheckBox("Show legend")
            self.legend.setObjectName("SWSimChartLegend")
            self.auto_max = QtWidgets.QCheckBox("Automatically defined maximum value")
            self.auto_max.setObjectName("SWSimChartAutoMax")
            self.max_value = QtWidgets.QDoubleSpinBox()
            self.max_value.setObjectName("SWSimChartMaxValue")
            self.auto_min = QtWidgets.QCheckBox("Automatically defined minimum value")
            self.auto_min.setObjectName("SWSimChartAutoMin")
            self.min_value = QtWidgets.QDoubleSpinBox()
            self.min_value.setObjectName("SWSimChartMinValue")
            for sp in (self.max_value, self.min_value):
                sp.setRange(-1e15, 1e15)
                sp.setDecimals(6)
            for w in (self.show_min, self.show_max, self.details, self.legend, self.auto_max, self.max_value,
                      self.auto_min, self.min_value):
                dl.addWidget(w)
            num = _box("Position/Format")
            nl = QtWidgets.QVBoxLayout(num)
            nl.addWidget(QtWidgets.QLabel("Predefined positions:"))
            row = QtWidgets.QHBoxLayout()
            self.positions = {}
            for name in POSITIONS:
                b = pic_button(name, "SWSimChartPos" + name, name)
                b.setToolTip("%s: the legend at the %s of the graphics area" % (name, name.lower()))
                b.clicked.connect(lambda _=False, n=name: self._position(n))
                row.addWidget(b)
                self.positions[name] = b
            nl.addLayout(row)
            form = QtWidgets.QFormLayout()
            self.pos_x = QtWidgets.QSpinBox()
            self.pos_x.setObjectName("SWSimChartPosX")
            self.pos_x.setToolTip("Horizontal from left")
            self.pos_y = QtWidgets.QSpinBox()
            self.pos_y.setObjectName("SWSimChartPosY")
            self.pos_y.setToolTip("Vertical from top")
            for sp in (self.pos_x, self.pos_y):
                sp.setRange(0, 100)
                sp.setSuffix(" %")
            self.size = QtWidgets.QComboBox()
            self.size.setObjectName("SWSimChartSize")
            self.size.addItems(list(SIZES))
            self.format = QtWidgets.QComboBox()
            self.format.setObjectName("SWSimChartFormat")
            self.format.addItems([f.lower() for f in FORMATS])
            self.decimals = QtWidgets.QSpinBox()
            self.decimals.setObjectName("SWSimChartDecimals")
            self.decimals.setRange(0, 10)
            form.addRow("Horizontal:", self.pos_x)
            form.addRow("Vertical:", self.pos_y)
            form.addRow("Size:", self.size)
            form.addRow("Number format:", self.format)
            form.addRow("No. of decimal places:", self.decimals)
            nl.addLayout(form)
            col = _box("Color Options")
            cl = QtWidgets.QFormLayout(col)
            self.colours = QtWidgets.QComboBox()
            self.colours.setObjectName("SWSimChartColours")
            self.colours.addItems(list(COLOURS))
            self.ncolours = QtWidgets.QSpinBox()
            self.ncolours.setObjectName("SWSimChartNColours")
            self.ncolours.setRange(2, 24)
            self.flip = QtWidgets.QCheckBox("Flip")
            self.flip.setObjectName("SWSimChartFlip")
            cl.addRow("Colors:", self.colours)
            cl.addRow("Number of colors:", self.ncolours)
            cl.addRow(self.flip)
            self.above = QtWidgets.QCheckBox("Specify color for values above yield limit")
            self.above.setObjectName("SWSimChartAbove")
            self.above_colour = _Colour(c.get("above_colour") or CHART["above_colour"], "SWSimChartAboveColour")
            self.above_edit = QtWidgets.QPushButton("Edit Color...")
            self.above_edit.setObjectName("SWSimChartAboveEdit")
            self.above_edit.clicked.connect(self.above_colour._pick)
            cl.addRow(self.above)
            cl.addRow(self.above_colour, self.above_edit)
            self.pages["Chart Options"] = [disp, num, col]
            self.von = q == "Stress" and (p is None or p.get("comp") == "VON")
            s = None
            try:
                s = summary(a, p) if p is not None and result_for(a, p) is not None else None
            except Exception as _fw_err:
                _fw_log("simplots.py:chartsum", _fw_err)
            self.show_min.setChecked(c["show_min"])
            self.show_max.setChecked(c["show_max"])
            self.details.setChecked(c["details"])
            self.legend.setChecked(c.get("legend", True))
            self.auto_max.setChecked(c.get("auto_max", True))
            self.auto_min.setChecked(c.get("auto_min", True))
            self.max_value.setValue(c.get("max_value") if not c.get("auto_max", True) else (s["max"] if s else 0.0))
            self.min_value.setValue(c.get("min_value") if not c.get("auto_min", True) else (s["min"] if s else 0.0))
            self.pos_x.setValue(int((c.get("pos") or CHART["pos"])[0]))
            self.pos_y.setValue(int((c.get("pos") or CHART["pos"])[1]))
            self.size.setCurrentText(c.get("size", "Normal"))
            self.format.setCurrentText(c["format"].lower())
            self.decimals.setValue(c["decimals"])
            self.colours.setCurrentText({"Grayscale": "Gray Scale"}.get(c["colours"], c["colours"]))
            self.ncolours.setValue(int(c.get("ncolours", 10)))
            self.flip.setChecked(bool(c.get("flip")))
            self.above.setChecked(c.get("above", False))
            for w in (self.auto_max, self.auto_min, self.above):
                w.toggled.connect(self._chart_enable)

        def _position(self, name):
            x, y = POSITIONS[name]
            self.pos_x.setValue(x)
            self.pos_y.setValue(y)

        def _chart_enable(self, *_a):
            if self.current_tab() != "Chart Options":
                return
            von = self.q == "Stress" and (COMPONENTS["Stress"][max(0, self.comp.currentIndex())][0] == "VON"
                                          if hasattr(self, "comp") else self.von)
            self.above.setVisible(von)
            self.above_colour.setVisible(von and self.above.isChecked())
            self.above_edit.setVisible(von and self.above.isChecked())
            self.max_value.setVisible(not self.auto_max.isChecked())
            self.min_value.setVisible(not self.auto_min.isChecked())

        # -- Settings
        def _settings(self, p, q, st):
            fr = _box("Fringe Options")
            fl = QtWidgets.QVBoxLayout(fr)
            self.fringe = QtWidgets.QComboBox()
            self.fringe.setObjectName("SWSimSetFringe")
            self.fringe.addItems(list(FRINGES))
            fl.addWidget(self.fringe)
            bd = _box("Boundary Options")
            bl = QtWidgets.QVBoxLayout(bd)
            self.boundary = QtWidgets.QComboBox()
            self.boundary.setObjectName("SWSimSetBoundary")
            self.boundary.addItems(list(BOUNDARIES))
            bl.addWidget(self.boundary)
            brow = QtWidgets.QHBoxLayout()
            self.boundary_colour = _Colour(st.get("boundary_colour") or SETTINGS["boundary_colour"], "SWSimSetBoundaryColour")
            self.boundary_edit = QtWidgets.QPushButton("Edit Color...")
            self.boundary_edit.setObjectName("SWSimSetBoundaryEdit")
            self.boundary_edit.clicked.connect(self.boundary_colour._pick)
            brow.addWidget(self.boundary_colour)
            brow.addWidget(self.boundary_edit)
            bl.addLayout(brow)
            df = _box("Deformed Plot Options")
            dfl = QtWidgets.QVBoxLayout(df)
            self.superimpose = QtWidgets.QCheckBox("Superimpose model on the deformed shape")
            self.superimpose.setObjectName("SWSimSetSuperimpose")
            self.super_style = QtWidgets.QComboBox()
            self.super_style.setObjectName("SWSimSetSuperStyle")
            self.super_style.addItems(list(SUPERIMPOSE))
            self.trans_label = QtWidgets.QLabel("Transparency:")
            self.transparency = QtWidgets.QDoubleSpinBox()
            self.transparency.setObjectName("SWSimSetTransparency")
            self.transparency.setRange(0.0, 0.95)
            self.transparency.setDecimals(2)
            self.transparency.setSingleStep(0.05)
            self.translucency = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.translucency.setObjectName("SWSimSetTranslucency")
            self.translucency.setRange(0, 95)
            self.translucency.valueChanged.connect(lambda v: abs(self.transparency.value() * 100 - v) > 0.5
                                                   and self.transparency.setValue(v / 100.0))
            self.transparency.valueChanged.connect(lambda v: self.translucency.value() != int(round(v * 100))
                                                   and self.translucency.setValue(int(round(v * 100))))
            for w in (self.superimpose, self.super_style, self.trans_label, self.transparency, self.translucency):
                dfl.addWidget(w)
            self.pages["Settings"] = [fr, bd, df]
            self.df = df
            self.fringe.setCurrentText(st["fringe"])
            self.boundary.setCurrentText(st["boundary"])
            self.superimpose.setChecked(bool(st["superimpose"]))
            self.super_style.setCurrentText(st.get("super_style", SUPERIMPOSE[0]))
            self.transparency.setValue(float(st.get("translucency", 0.9)))
            self.superimpose.toggled.connect(self._settings_enable)
            self.boundary.currentTextChanged.connect(self._settings_enable)
            self._settings_enable()

        def _settings_enable(self, *_a):
            on = self.superimpose.isChecked()
            for w in (self.super_style, self.trans_label, self.transparency, self.translucency):
                w.setVisible(on)
            edges = self.boundary.currentText() != "None"
            self.boundary_colour.setVisible(edges)
            self.boundary_edit.setVisible(edges)

        # -- OK
        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def chart_values(self):
            return dict(show_min=self.show_min.isChecked(), show_max=self.show_max.isChecked(),
                        details=self.details.isChecked(), legend=self.legend.isChecked(),
                        auto_max=self.auto_max.isChecked(), max_value=self.max_value.value(),
                        auto_min=self.auto_min.isChecked(), min_value=self.min_value.value(),
                        pos=[self.pos_x.value(), self.pos_y.value()], size=self.size.currentText(),
                        format=self.format.currentText().capitalize(), decimals=self.decimals.value(),
                        colours=self.colours.currentText(), ncolours=self.ncolours.value(), flip=self.flip.isChecked(),
                        above=self.above.isChecked(), above_colour=list(self.above_colour.rgb))

        def settings_values(self):
            return dict(fringe=self.fringe.currentText(), boundary=self.boundary.currentText(),
                        boundary_colour=list(self.boundary_colour.rgb), superimpose=self.superimpose.isChecked(),
                        super_style=self.super_style.currentText(), translucency=self.transparency.value())

        def values(self):
            v = {"chart": self.chart_values(), "settings": self.settings_values()}
            if not hasattr(self, "deformed"):           # a Factor of Safety plot: its definition is its own PM
                return v
            q = self.quantity.currentText()
            v.update(quantity=q, comp=COMPONENTS[q][self.comp.currentIndex()][0], unit=self.unit.currentText(),
                     deformed=self.deformed.isChecked() and q not in ("Thermal", "Fatigue"),
                     scale=next(s for s, b in self.scales.items() if b.isChecked()), factor=self.factor.value(),
                     vector=self.vector.isChecked() and q == "Displacement",
                     show_colors=self.show_colors.isChecked() or q != "Displacement" or not self.deformed.isChecked(),
                     view=self.view.currentText() if self.view_on.isChecked() else "",
                     title_text=self.title_text.text().strip() if self.title_on.isChecked() else "")
            if q == "Amplitude":
                v["mode"] = self.mode.value()
            elif self.steps and len(self.steps) > 1:
                v["step"] = self.mode.value()
            return v

        def accept(self):
            v = self.values()
            if self.p is None:
                q = v.pop("quantity")
                self.name = new_plot(self.a, q, v.pop("comp"), v.pop("unit"), v.pop("deformed"), v.pop("scale"),
                                     v.pop("factor"), mode=v.pop("mode", None), step=v.pop("step", None), **v)["name"]
            else:
                update_plot(self.a, self.name, **v)
            Gui.Control.closeDialog()
            try:
                show(self.a, self.name)
            except Exception as e:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Result plot", str(e))
            _refresh_panel()
            return True

        def reject(self):
            Gui.Control.closeDialog()
            return True

    def EditDefinitionPM(a, name=None, quantity=None):
        """Edit Definition / Define ... Plot: the plot PM on its Definition tab; a Factor of Safety plot's own PM."""
        p = get_plot(a, name) if name else None
        if (p and p["quantity"] == "Factor of Safety") or (p is None and quantity == "Factor of Safety"):
            return FactorOfSafetyPM(a, name)
        return PlotPM(a, name, quantity)

    def ChartOptionsPM(a, name):
        return PlotPM(a, name, tab="Chart Options")

    def SettingsPM(a, name):
        return PlotPM(a, name, tab="Settings")

    class FactorOfSafetyPM:
        ""




        WORDS = {"Automatic": "Automatic takes the failure criterion the material gives (the maximum von Mises stress "
                              "for a ductile metal) and its yield strength.",
                 "Max von Mises Stress": "The stress limit over the von Mises stress. For ductile materials.",
                 "Max Shear Stress (Tresca)": "The stress limit over the stress intensity (P1 - P3). A little more "
                                              "careful than von Mises for ductile materials.",
                 "Mohr-Coulomb Stress": "Tension and compression measured against their own strengths. For brittle "
                                        "materials.",
                 "Max Normal Stress": "The stress limit over the largest principal stress. For brittle materials."}

        def __init__(self, a, name=None):
            self.a, self.name = a, name
            self.p = p = get_plot(a, name) if name else None
            self.st = st = strengths(a)
            self.step_box = _box("Steps", "Factor of Safety")
            sl = QtWidgets.QHBoxLayout(self.step_box)
            self.step_label = QtWidgets.QLabel("")
            self.step_label.setObjectName("SWSimFosStep")
            self.back = QtWidgets.QToolButton()
            self.back.setObjectName("SWSimFosBack")
            self.back.setArrowType(QtCore.Qt.LeftArrow)
            self.back.setToolTip("Back")
            self.next = QtWidgets.QToolButton()
            self.next.setObjectName("SWSimFosNext")
            self.next.setArrowType(QtCore.Qt.RightArrow)
            self.next.setToolTip("Next")

            # "Step 1 of 3"
            self.step_label.hide()
            sl.setContentsMargins(0, 0, 0, 0)
            sl.addStretch(1)
            sl.addWidget(self.back)
            sl.addWidget(self.next)
            _later(lambda: bare_box(self.step_box))
            # step 1
            s1 = _box("Step 1 of 3")
            l1 = QtWidgets.QVBoxLayout(s1)
            msg = QtWidgets.QLabel("The factor of safety depends on the failure criterion you pick.")
            msg.setWordWrap(True)
            msg.setStyleSheet("QLabel { background: #fff8c4; border: 1px solid #e0c860; padding: 4px; }")
            l1.addWidget(msg)
            self.criterion = QtWidgets.QComboBox()
            self.criterion.setObjectName("SWSimFosCriterion")
            self.criterion.addItems(criteria(a))
            l1.addWidget(self.criterion)
            self.crit_text = QtWidgets.QLabel("")
            self.crit_text.setWordWrap(True)
            l1.addWidget(self.crit_text)
            adv = _box("Advanced Options")
            al = QtWidgets.QVBoxLayout(adv)
            self.upper_on = QtWidgets.QCheckBox("Set upper limit for Factor of Safety")
            self.upper_on.setObjectName("SWSimFosUpperOn")
            self.upper = QtWidgets.QDoubleSpinBox()
            self.upper.setObjectName("SWSimFosUpper")
            self.upper.setRange(0.01, 1e6)
            self.upper.setValue(3.0)
            al.addWidget(self.upper_on)
            al.addWidget(self.upper)
            prop = _box("Property")
            pl = QtWidgets.QVBoxLayout(prop)
            self.title_on = QtWidgets.QCheckBox("Include title text:")
            self.title_on.setObjectName("SWSimPlotTitleOn")
            self.title_text = QtWidgets.QLineEdit()
            self.title_text.setObjectName("SWSimPlotTitleText")
            self.view_on = QtWidgets.QCheckBox("Associate plot with named view orientation")
            self.view_on.setObjectName("SWSimPlotViewOn")
            self.view = QtWidgets.QComboBox()
            self.view.setObjectName("SWSimPlotView")
            self.view.addItems(list(VIEWS))
            for w in (self.title_on, self.title_text, self.view_on, self.view):
                pl.addWidget(w)
            # step 2
            s2 = _box("Step 2 of 3")
            l2 = QtWidgets.QVBoxLayout(s2)
            self.unit_row = QtWidgets.QWidget()
            ur = QtWidgets.QFormLayout(self.unit_row)
            ur.setContentsMargins(0, 0, 0, 0)
            self.unit = QtWidgets.QComboBox()
            self.unit.setObjectName("SWSimFosUnit")
            self.unit.addItems(list(UNITS["Stress"]))
            ur.addRow("Units:", self.unit)
            l2.addWidget(self.unit_row)
            self.limit_head = QtWidgets.QLabel("Set stress limit to:")
            l2.addWidget(self.limit_head)
            self.limits = {}
            for lim in limits(a):
                b = QtWidgets.QRadioButton(lim)
                b.setObjectName("SWSimFosLimit" + lim.split()[0])
                l2.addWidget(b)
                self.limits[lim] = b
            self.limit_value = QtWidgets.QDoubleSpinBox()
            self.limit_value.setObjectName("SWSimFosLimitValue")
            self.limit_value.setRange(1e-6, 1e15)
            self.limit_value.setDecimals(4)
            l2.addWidget(self.limit_value)
            mf = QtWidgets.QFormLayout()
            self.multiplier = QtWidgets.QDoubleSpinBox()
            self.multiplier.setObjectName("SWSimFosMultiplier")
            self.multiplier.setRange(0.001, 1000.0)
            self.multiplier.setDecimals(3)
            self.multiplier.setValue(1.0)
            mf.addRow("Multiplication factor:", self.multiplier)
            l2.addLayout(mf)
            self.material = QtWidgets.QLabel("")
            self.material.setObjectName("SWSimFosMaterial")
            self.material.setStyleSheet("QLabel { border: 1px solid #b0b0b0; padding: 4px; }")
            l2.addWidget(self.material)
            # step 3
            s3 = _box("Step 3 of 3")
            l3 = QtWidgets.QVBoxLayout(s3)
            self.distribution = QtWidgets.QRadioButton("Factor of safety distribution")
            self.distribution.setObjectName("SWSimFosDistribution")
            self.below = QtWidgets.QRadioButton("Areas below factor of safety")
            self.below.setObjectName("SWSimFosBelow")
            self.below_value = QtWidgets.QDoubleSpinBox()
            self.below_value.setObjectName("SWSimFosBelowValue")
            self.below_value.setRange(0.001, 1e6)
            self.below_value.setDecimals(3)
            self.below_value.setValue(1.0)
            self.result = QtWidgets.QLabel("")
            self.result.setObjectName("SWSimFosResult")
            self.result.setStyleSheet("QLabel { border: 1px solid #b0b0b0; padding: 4px; }")
            for w in (self.distribution, self.below, self.below_value, self.result):
                l3.addWidget(w)
            self.pages = [[s1, adv, prop], [s2], [s3]]
            self.steps = [s1, s2, s3]
            self.form = [self.step_box, s1, adv, prop, s2, s3]
            self.unit.setCurrentText("N/m^2")
            mpa = float(st["yield"] or st["ultimate"] or 250.0)
            if p:
                self.criterion.setCurrentText(p.get("criterion", "Automatic"))
                lim = p.get("limit", "Yield strength")
                (self.limits.get(lim) or next(iter(self.limits.values()))).setChecked(True)
                mpa = float(p.get("limit_value") or mpa)
                self.multiplier.setValue(float(p.get("multiplier", 1.0)))
                (self.below if p.get("below") else self.distribution).setChecked(True)
                self.below_value.setValue(float(p.get("below_value", 1.0)))
                self.upper_on.setChecked(bool(p.get("upper")))
                self.upper.setValue(float(p.get("upper") or 3.0))
                self.title_on.setChecked(bool(p.get("title_text")))
                self.title_text.setText(p.get("title_text") or "")
                self.view_on.setChecked(bool(p.get("view")))
                self.view.setCurrentText(p.get("view") or "Isometric")
            else:
                self.criterion.setCurrentText("Automatic")
                next(iter(self.limits.values())).setChecked(True)
                self.distribution.setChecked(True)
                self.view.setCurrentText("Isometric")
            self._mpa = mpa
            self.limit_value.setValue(mpa * to_unit("Stress", self.unit.currentText()))
            self.unit.currentTextChanged.connect(self._unit)
            self.criterion.currentTextChanged.connect(self._changed)
            for w in (self.upper_on, self.title_on, self.view_on, self.below, self.distribution):
                w.toggled.connect(self._enable)
            for b in self.limits.values():
                b.toggled.connect(self._enable)
            for w in (self.multiplier, self.upper, self.limit_value):
                w.valueChanged.connect(self._lowest)
            self.back.clicked.connect(lambda: self.go(self.step - 1))
            self.next.clicked.connect(lambda: self.go(self.step + 1))
            self.unit_shown = self.unit.currentText()
            self._changed()
            self.go(0)
            _later(lambda: self._alive() and self.go(self.step))

        def _alive(self):
            try:
                self.back.objectName()
                return True
            except RuntimeError:
                return False

        def _unit(self, unit):
            """The typed limit and the material's strengths in the units picked."""
            mpa = self.limit_value.value() / to_unit("Stress", self.unit_shown)
            self.unit_shown = unit
            self.limit_value.setValue(mpa * to_unit("Stress", unit))
            self._material()

        def _material(self):
            k = to_unit("Stress", self.unit.currentText())
            lines = []
            for key, words in (("yield", "Yield strength"), ("ultimate", "Ultimate strength"),
                               ("compressive", "Compressive strength")):
                if self.st[key]:
                    lines.append("%s: %s %s" % (words, "{:.6g}".format(self.st[key] * k), self.unit.currentText()))
            self.material.setText("\n".join(lines) or "The material gives no strengths: type a limit of your own.")

        def _changed(self, *_a):
            self.crit_text.setText(self.WORDS.get(self.criterion.currentText(), ""))
            self._material()
            self._enable()

        def go(self, k):
            self.step = max(0, min(2, k))
            for i, boxes in enumerate(self.pages):
                for b in boxes:
                    box_visible(b, i == self.step)
            self.back.setVisible(self.step > 0)
            self.next.setVisible(self.step < 2)
            self.step_label.setText("Step %d of 3" % (self.step + 1))
            self._enable()

        def _enable(self, *_a):
            auto = self.criterion.currentText() == "Automatic"
            for w in [self.unit_row, self.limit_head, self.material] + list(self.limits.values()):
                w.setVisible(not auto)
            ud = self.limits.get("User defined")
            self.limit_value.setVisible(not auto and ud is not None and ud.isChecked())
            self.below_value.setVisible(self.below.isChecked())
            self.upper.setVisible(self.upper_on.isChecked())
            self.title_text.setVisible(self.title_on.isChecked())
            self.view.setVisible(self.view_on.isChecked())
            self._lowest()

        def _lowest(self, *_a):
            """Step 3's box: the study's lowest factor of safety with what is set now."""
            try:
                res = result(self.a)
                vals = fos_values(self.a, res, self.values())
                self.lowest = min(v for _n, v in _on_part(self.a, vals))
                self.result.setText("Lowest factor of safety: %s" % "{:.6g}".format(self.lowest))
            except Exception as e:
                self.lowest = None
                self.result.setText(str(e))

        def values(self):
            lim = next((l for l, b in self.limits.items() if b.isChecked()), "Yield strength")
            return dict(criterion=self.criterion.currentText(), limit=lim,
                        limit_value=(self.limit_value.value() / to_unit("Stress", self.unit.currentText()))
                        if lim == "User defined" else None,
                        multiplier=self.multiplier.value(), below=self.below.isChecked(),
                        below_value=self.below_value.value(), upper=self.upper.value() if self.upper_on.isChecked() else None,
                        title_text=self.title_text.text().strip() if self.title_on.isChecked() else "",
                        view=self.view.currentText() if self.view_on.isChecked() else "")

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def accept(self):
            v = self.values()
            try:
                fos_limit(self.a, v)
            except RuntimeError as e:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Factor of Safety", str(e))
                return False
            if self.p is None:
                self.name = new_plot(self.a, "Factor of Safety", "FOS", "", False, **v)["name"]
            else:
                update_plot(self.a, self.name, **v)
            Gui.Control.closeDialog()
            try:
                show(self.a, self.name)
            except Exception as e:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Factor of Safety", str(e))
            _refresh_panel()
            return True

        def reject(self):
            Gui.Control.closeDialog()
            return True

    class _ProbeGraph(QtWidgets.QDialog):
        """Probe > Plot: the probed values in order, as a line graph."""

        def __init__(self, title, head, rows, chart):
            super().__init__(Gui.getMainWindow())
            self.setObjectName("SWSimProbeGraph")
            self.setWindowTitle(title)
            self.head, self.vals, self.chart = head, [r[1] for r in rows], chart
            self.resize(520, 340)

        def paintEvent(self, e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.fillRect(self.rect(), QtGui.QColor(255, 255, 255))
            left, top, right, bottom = 90, 30, self.width() - 20, self.height() - 40
            p.setPen(QtGui.QColor(30, 30, 30))
            p.drawText(QtCore.QRect(0, 4, self.width(), 20), QtCore.Qt.AlignCenter, self.head)
            p.drawLine(left, bottom, right, bottom)
            p.drawLine(left, top, left, bottom)
            vs = self.vals
            if vs:
                lo, hi = min(vs), max(vs)
                if hi == lo:
                    hi = lo + 1.0
                for k in range(5):
                    v = lo + (hi - lo) * k / 4.0
                    y = bottom - (bottom - top) * k / 4.0
                    p.drawText(QtCore.QRectF(0, y - 8, left - 6, 16), QtCore.Qt.AlignRight, fmt(v, self.chart))
                n = max(1, len(vs) - 1)
                pts = [QtCore.QPointF(left + (right - left) * i / n, bottom - (bottom - top) * (v - lo) / (hi - lo))
                       for i, v in enumerate(vs)]
                p.setPen(QtGui.QPen(QtGui.QColor(0, 80, 200), 2))
                p.drawPolyline(QtGui.QPolygonF(pts))
                for q in pts:
                    p.drawEllipse(q, 2.5, 2.5)
                p.setPen(QtGui.QColor(30, 30, 30))
                p.drawText(QtCore.QRect(left, bottom + 8, right - left, 20), QtCore.Qt.AlignCenter, "Location (row)")
            p.end()

    class ProbePM:
        """Probe Result. At location: each click on the plot adds the nearest node's row (Node, Value, X, Y, Z), with a
        flag on the model. On selected entities (List Selected): pick faces, edges or vertices, then Update: every node
        on them, and Summary's Sum, Avg, Max, Min and RMS. At Node number: type a node, then add it. Report Options:
        Save (CSV), Plot (a graph), Capture Image, Copy to Clipboard. Annotations: what each flag shows."""

        def __init__(self, a, name, on_selected=False):
            self.a, self.name = a, name
            self.p = get_plot(a, name)
            opts = _box("Options", "Probe Result")
            ol = QtWidgets.QVBoxLayout(opts)
            self.at = QtWidgets.QRadioButton("At location")
            self.at.setObjectName("SWSimProbeAt")
            self.selected = QtWidgets.QRadioButton("On selected entities")
            self.selected.setObjectName("SWSimProbeSelected")
            self.by_node = QtWidgets.QRadioButton("At Node number")
            self.by_node.setObjectName("SWSimProbeNode")
            for w in (self.at, self.selected, self.by_node):
                ol.addWidget(w)
            self.picks = QtWidgets.QListWidget()
            self.picks.setObjectName("SWSimProbePicks")
            self.picks.setFixedHeight(64)
            self.update_btn = QtWidgets.QPushButton("Update")
            self.update_btn.setObjectName("SWSimProbeUpdate")
            self.update_btn.clicked.connect(self.update)
            ol.addWidget(self.picks)
            ol.addWidget(self.update_btn)
            self.node_row = QtWidgets.QWidget()
            nr = QtWidgets.QHBoxLayout(self.node_row)
            nr.setContentsMargins(0, 0, 0, 0)
            self.node_edit = QtWidgets.QLineEdit()
            self.node_edit.setObjectName("SWSimProbeNodeNumber")
            self.node_edit.setPlaceholderText("Node number")
            self.node_add = QtWidgets.QPushButton("Add")
            self.node_add.setObjectName("SWSimProbeNodeAdd")
            self.node_add.clicked.connect(self._add_typed)
            self.node_edit.returnPressed.connect(self._add_typed)
            nr.addWidget(self.node_edit)
            nr.addWidget(self.node_add)
            ol.addWidget(self.node_row)
            res = _box("Results")
            rl = QtWidgets.QVBoxLayout(res)
            unit = self.p["unit"] or legend_head(self.p)
            self.table = QtWidgets.QTableWidget(0, 5)
            self.table.setObjectName("SWSimProbeTable")
            self.table.setHorizontalHeaderLabels(["Node", "Value (%s)" % unit, "X (mm)", "Y (mm)", "Z (mm)"])
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.table.setToolTip("Location")
            rl.addWidget(self.table)
            self.sum_box = _box("Summary")
            sl = QtWidgets.QVBoxLayout(self.sum_box)
            self.sum_table = QtWidgets.QTableWidget(5, 2)
            self.sum_table.setObjectName("SWSimProbeSummary")
            self.sum_table.setHorizontalHeaderLabels(["Value", "Unit"])
            self.sum_table.setVerticalHeaderLabels(["Sum", "Avg", "Max", "Min", "RMS"])
            self.sum_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.sum_table.setFixedHeight(150)
            sl.addWidget(self.sum_table)
            self.sum_unit = self.p["unit"] or ""
            rep = _box("Report Options")
            pl = QtWidgets.QHBoxLayout(rep)

            self.save = pic_button("Save", "SWSimProbeSave", "Save")
            self.save.clicked.connect(self.save_rows)
            self.plot = pic_button("Plot", "SWSimProbePlot", "Plot")
            self.plot.clicked.connect(self.graph)
            self.capture = pic_button("Capture", "SWSimProbeCapture", "Capture Image")
            self.capture.clicked.connect(self.capture_image)
            self.copy = pic_button("Copy", "SWSimProbeCopy", "Copy to Clipboard")
            self.copy.clicked.connect(self.copy_rows)
            for b in (self.save, self.plot, self.capture, self.copy):
                pl.addWidget(b)
            pl.addStretch(1)
            ann = _box("Annotations")
            anl = QtWidgets.QVBoxLayout(ann)
            self.ann_node = QtWidgets.QCheckBox("Show Node/Element Number")
            self.ann_node.setObjectName("SWSimProbeAnnNode")
            self.ann_xyz = QtWidgets.QCheckBox("Show X,Y,Z Location")
            self.ann_xyz.setObjectName("SWSimProbeAnnXYZ")
            self.ann_value = QtWidgets.QCheckBox("Show Value")
            self.ann_value.setObjectName("SWSimProbeAnnValue")
            for w in (self.ann_node, self.ann_xyz, self.ann_value):
                w.setChecked(True)
                w.toggled.connect(self._flags)
                anl.addWidget(w)
            self.ann_box = ann
            self.form = [opts, res, self.sum_box, rep, ann]
            self.rows = []
            self.entities = []
            self.flags = None
            self.summary = {}
            (self.selected if on_selected else self.at).setChecked(True)
            for w in (self.at, self.selected, self.by_node):
                w.toggled.connect(self._mode)
            self._mode()
            if SHOWN.get("name") != name or SHOWN.get("a") is not a:
                show(a, name)
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)
            self._cb = None
            try:
                from pivy import coin
                view = _view(a.Document)
                view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self._click)
                self._cb = (view, self._click)
            except Exception as _fw_err:
                _fw_log("simplots.py:probecb", _fw_err)
            _later(lambda: self._alive() and self._boxes())

        def _boxes(self):
            box_visible(self.sum_box, self.selected.isChecked())
            box_visible(self.ann_box, not self.selected.isChecked())

        def _mode(self, *_a):
            on = self.selected.isChecked()
            self.picks.setVisible(on)
            self.update_btn.setVisible(on)
            self.node_row.setVisible(self.by_node.isChecked())
            self._boxes()
            self.rows, self.entities = [], []
            self.picks.clear()
            self._fill()

        def _alive(self):
            try:
                self.table.objectName()
                return True
            except RuntimeError:                # the panel was closed without Close (another command took the
                self._stop()                    # task pane): stop listening to picks
                return False

        def _click(self, cb):
            """A left click on the shown plot: the point on its drawn (deformed) surface."""
            from pivy import coin
            if not self._alive() or self.by_node.isChecked():
                return
            ev = cb.getEvent()
            if not coin.SoMouseButtonEvent.isButtonPressEvent(ev, coin.SoMouseButtonEvent.BUTTON1):
                return
            node = SHOWN.get("node")
            if node is None:
                return
            q = pick_drawn(node[0], node[1], ev.getPosition())
            n = node_at_drawn(q) if q is not None else node_on_screen(node[0], ev.getPosition().getValue())
            if n is not None:
                cb.setHandled()
                QtCore.QTimer.singleShot(0, lambda: self.add_node(n))

        def addSelection(self, doc, obj, sub, pnt):
            if self.selected.isChecked() and sub:
                QtCore.QTimer.singleShot(0, lambda: self.pick(sub.split(".")[-1]))
            elif not self.by_node.isChecked():
                QtCore.QTimer.singleShot(0, lambda: self.add(App.Vector(*pnt)))

        def add(self, point):
            """At location: the row of the node nearest a point on the model."""
            if not self._alive():
                return None
            return self._take(probe_at(self.a, self.name, point))

        def add_node(self, n):
            if not self._alive():
                return None
            if self.selected.isChecked():
                face = face_at(result_for(self.a, self.p), n)
                return self.pick(face) if face else None
            return self._take(row_of(self.a, self.name, n))

        def _add_typed(self):
            """At Node number: the typed node's row (a node the plot does not have is refused, and said so)."""
            try:
                n = int(self.node_edit.text().strip())
            except ValueError:
                self.node_edit.selectAll()
                return None
            row = row_of(self.a, self.name, n)
            if row[1] is None:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Probe Result", "The plot has no node %d." % n)
                return None
            self.node_edit.clear()
            return self._take(row)

        def pick(self, sub):
            """On selected entities: a face, edge or vertex of the part goes to the pick box (Update lists it)."""
            if not self._alive() or not sub or sub in self.entities:
                return None
            if not entity_nodes(result_for(self.a, self.p), sub):
                return None
            self.entities.append(sub)
            self.picks.addItem(sub)
            self._clear_pick()
            return sub

        def update(self):
            """Update: every node on the picked entities, with the Summary."""
            res = result_for(self.a, self.p)
            vals = dict(summary(self.a, self.p)["values"])
            fm = res.Mesh.FemMesh
            self.rows = []
            seen = set()
            for sub in self.entities:
                for n in entity_nodes(res, sub):
                    if n in vals and n not in seen:
                        seen.add(n)
                        q = fm.getNodeById(n)
                        self.rows.append((n, vals[n], q.x, q.y, q.z))
            self._fill()
            return list(self.rows)

        def add_entity(self, sub):
            """A pick and an Update in one (scripts)."""
            self.pick(sub)
            return self.update()

        def _take(self, row):
            self.rows.append(row)
            self._fill()
            self._clear_pick()
            return row

        def _clear_pick(self):
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("simplots.py:probe", _fw_err)

        def _fill(self):
            c = chart_of(self.p)
            self.table.setRowCount(0)
            for r, row in enumerate(self.rows):
                self.table.insertRow(r)
                for k, text in enumerate([str(row[0]), fmt(row[1], c), "%.3f" % row[2], "%.3f" % row[3], "%.3f" % row[4]]):
                    self.table.setItem(r, k, QtWidgets.QTableWidgetItem(text))
            sm = selected_summary(self.rows)
            for i, k in enumerate(("Sum", "Avg", "Max", "Min", "RMS")):
                self.sum_table.setItem(i, 0, QtWidgets.QTableWidgetItem(fmt(sm[k], c) if k in sm else ""))
                self.sum_table.setItem(i, 1, QtWidgets.QTableWidgetItem(self.sum_unit if k in sm else ""))
            self.summary = sm
            self._flags()

        def _flags(self, *_a):
            """A flag on the model at each probed point: node number, X, Y, Z and the value, as Annotations ask."""
            try:
                from pivy import coin
                if self.flags is not None:
                    self._drop_flags()
                if self.selected.isChecked() or not self.rows or not any(
                        w.isChecked() for w in (self.ann_node, self.ann_xyz, self.ann_value)):
                    return
                res = result_for(self.a, self.p)
                factor = SHOWN.get("factor", 0.0) if SHOWN.get("name") == self.name else 0.0
                c = chart_of(self.p)
                view = _view(self.a.Document)
                root = coin.SoAnnotation()
                points = []
                for row in self.rows:
                    lines = []
                    if self.ann_node.isChecked():
                        lines.append("Node: %d" % row[0])
                    if self.ann_xyz.isChecked():
                        lines.append("X,Y,Z: %.3f, %.3f, %.3f mm" % (row[2], row[3], row[4]))
                    if self.ann_value.isChecked():
                        lines.append("Value: %s %s" % (fmt(row[1], c), self.p["unit"] or ""))
                    q = sx._node_at(res, row[0], factor)

                    sep = coin.SoSeparator()
                    col = coin.SoBaseColor()
                    col.rgb = (0.0, 0.0, 0.0)
                    style = coin.SoDrawStyle()
                    style.pointSize = 5
                    coords = coin.SoCoordinate3()
                    coords.point.setValue(q.x, q.y, q.z)
                    for n in (col, style, coords, coin.SoPointSet()):
                        sep.addChild(n)
                    root.addChild(sep)
                    points.append(("\n".join(lines), App.Vector(q.x, q.y, q.z)))
                view.getSceneGraph().addChild(root)
                host = sx._host()
                box = Callouts(host, view, points) if host is not None else None
                if box is not None:
                    box.setObjectName("SWSimProbeFlags")
                self.flags = (view, root, len(self.rows), box)
            except Exception as _fw_err:
                _fw_log("simplots.py:flags", _fw_err)

        def rows_text(self):
            head = "Node\tValue (%s)\tX (mm)\tY (mm)\tZ (mm)" % (self.p["unit"] or legend_head(self.p))
            return "\n".join([head] + ["%d\t%.6g\t%.4f\t%.4f\t%.4f" % r for r in self.rows])

        def copy_rows(self):
            QtWidgets.QApplication.clipboard().setText(self.rows_text())
            return self.rows_text()

        def capture_image(self, path=None):
            if not path:
                path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Capture Image",
                                                                 "%s-probe.png" % self.name, "PNG (*.png)")
            if not path:
                return None
            _view(self.a.Document).saveImage(path, 1200, 800, "Current")
            return path

        def save_rows(self, path=None):
            if not path:
                path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save", "%s-probe.csv" % self.name,
                                                                 "CSV (*.csv)")
            if not path:
                return None
            return write_rows(path, self.p, self.rows)

        def graph(self):
            g = _ProbeGraph("Probe Result", legend_head(self.p), self.rows, chart_of(self.p))
            g.show()
            self.graph_dialog = g
            return g

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def _stop(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("simplots.py:probe2", _fw_err)
            if self._cb is not None:
                try:
                    from pivy import coin
                    self._cb[0].removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self._cb[1])
                except Exception as _fw_err:
                    _fw_log("simplots.py:probe3", _fw_err)
                self._cb = None
            if self.flags is not None:
                self._drop_flags()

        def _drop_flags(self):
            try:
                self.flags[0].getSceneGraph().removeChild(self.flags[1])
            except Exception as _fw_err:
                _fw_log("simplots.py:probe4", _fw_err)
            try:
                if len(self.flags) > 3 and self.flags[3] is not None:
                    self.flags[3].hide()
                    self.flags[3].deleteLater()
            except RuntimeError:
                pass
            self.flags = None

        def _close(self):
            self._stop()
            Gui.Control.closeDialog()

        def accept(self):
            self._close()
            return True

        def reject(self):
            self._close()
            return True

    def ListSelectedPM(a, name):
        """List Selected: the Probe PM on its On selected entities option."""
        return ProbePM(a, name, on_selected=True)

    class ResultsPanel(QtWidgets.QDockWidget):
        """The study's Results folder: its plots; Show (double-click), Edit Definition, Chart Options, Probe, New Plot,
        Delete."""

        def __init__(self, a):
            super().__init__("Results: %s" % a.Label, Gui.getMainWindow())
            self.setObjectName("SWSimResults")
            self.a = a
            w = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(w)
            self.list = QtWidgets.QListWidget()
            self.list.setObjectName("SWSimResultsList")
            lay.addWidget(self.list)
            grid = QtWidgets.QGridLayout()
            self.buttons = {}
            for i, (text, fn) in enumerate((("Show", self.show_picked), ("Edit Definition...", self.edit),
                                            ("Chart Options...", self.chart), ("Probe", self.probe),
                                            ("New Plot...", self.new), ("Delete", self.delete),
                                            ("Hide Plot", clear))):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("SWSimResults" + text.replace(" ", "").replace(".", ""))
                b.clicked.connect(lambda *_a, f=fn: f())
                grid.addWidget(b, i // 2, i % 2)
                self.buttons[text] = b
            lay.addLayout(grid)
            self.setWidget(w)
            self.list.itemDoubleClicked.connect(lambda *_: self.show_picked())
            self.list.currentRowChanged.connect(lambda *_: self._enable())
            self.refresh()

        def refresh(self):
            defaults(self.a)
            keep = self.picked()
            self.list.clear()
            for p in plots(self.a):
                it = QtWidgets.QListWidgetItem(title(p))
                it.setData(QtCore.Qt.UserRole, p["name"])
                self.list.addItem(it)
            names = [p["name"] for p in plots(self.a)]
            if names:
                self.list.setCurrentRow(names.index(keep) if keep in names else 0)
            self._enable()

        def _enable(self):
            have = self.picked() is not None and result(self.a) is not None
            for text, b in self.buttons.items():          # what cannot act is not shown (no greyed buttons)
                if text not in ("New Plot...", "Hide Plot"):
                    b.setVisible(have)
            self.buttons["New Plot..."].setVisible(result(self.a) is not None)

        def picked(self):
            it = self.list.currentItem() if hasattr(self, "list") else None
            return it.data(QtCore.Qt.UserRole) if it is not None else None

        def show_picked(self):
            return show(self.a, self.picked()) if self.picked() else None

        def edit(self):
            return _open(EditDefinitionPM(self.a, self.picked()))

        def chart(self):
            return _open(ChartOptionsPM(self.a, self.picked()))

        def probe(self):
            return _open(ProbePM(self.a, self.picked()))

        def new(self):
            return _open(EditDefinitionPM(self.a, None))

        def delete(self):
            name = self.picked()
            if name:
                if SHOWN.get("name") == name:
                    clear()
                delete_plot(self.a, name)
                self.refresh()

    OPEN = []
    PANEL = {"dock": None}

    def _open(pm):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        del OPEN[:]
        OPEN.append(pm)
        Gui.Control.showDialog(pm)
        return pm

    def _refresh_panel():
        d = PANEL.get("dock")
        try:
            if d is not None and d.isVisible():
                d.refresh()
        except RuntimeError:
            PANEL["dock"] = None

    def open_results(a):
        d = PANEL.get("dock")
        try:
            if d is not None and d.a is not a:
                d.close()
                d = None
        except RuntimeError:
            d = None
        if d is None:
            d = ResultsPanel(a)
            Gui.getMainWindow().addDockWidget(QtCore.Qt.LeftDockWidgetArea, d)
            PANEL["dock"] = d
        d.refresh()
        d.show()
        d.raise_()
        if d.picked() and result(a) is not None:
            d.show_picked()
        return d

    def _study():
        from . import simpms
        doc = App.ActiveDocument
        return simpms.active_study(doc) if doc is not None else None

    def _native_active(name):
        try:
            c = Gui.Command.get(name)
            return bool(c is not None and c.isActive())
        except Exception as _fw_err:
            _fw_log("simplots.py:native", _fw_err)
            return False

    class _Cmd:
        """Ours on a study with a structural (CalculiX) result; FreeCAD's own command otherwise (a flow study's results)."""

        def __init__(self, text, tip, run, pixmap, native):
            self.text, self.tip, self.run, self.pixmap, self.native = text, tip, run, pixmap, native

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": self.pixmap}

        def _ours(self):
            a = _study()
            return a if a is not None and result(a) is not None else None

        def IsActive(self):
            if Gui.Control.activeDialog():
                return False
            return self._ours() is not None or _native_active(self.native)

        def Activated(self):
            a = self._ours()
            if a is not None:
                self.run(a)
            else:
                Gui.runCommand(self.native, 0)

    def _probe(a):
        defaults(a)
        name = SHOWN.get("name") if SHOWN.get("a") is a else None
        return _open(ProbePM(a, name or plots(a)[0]["name"]))

    COMMANDS = {
        "SWStyle_SimResults": _Cmd("Results", "The study's result plots: show, edit, chart options, probe.", open_results,
                                   "FEM_ResultShow", "FEM_ResultShow"),
        "SWStyle_SimNewPlot": _Cmd("New Plot", "A new stress, displacement or strain plot.",
                                   lambda a: (defaults(a), _open(EditDefinitionPM(a, None))), "FEM_PostPipelineFromResult",
                                   "FEM_PostPipelineFromResult"),
        "SWStyle_SimProbe": _Cmd("Probe", "Values at the points you click on the plot.", _probe, "FEM_PostFilterDataAtPoint",
                                 "FEM_PostFilterDataAtPoint"),
    }

KEYS = (
    ("SIM_Results", "Results", ("SWStyle_SimResults", "FEM_ResultShow", "FEM_PostPipelineFromResult"),
     "The study's result plots: show, Edit Definition, Chart Options, Probe.", None),
    ("SIM_Plot", "New Plot", ("SWStyle_SimNewPlot", "FEM_PostPipelineFromResult"), "A new stress, displacement or strain plot.", None),
    ("SIM_Probe", "Probe", ("SWStyle_SimProbe", "FEM_PostFilterDataAtPoint"), "Values at the points you click on the plot.", None),
)


def install():
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
