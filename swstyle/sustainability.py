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
import math
import os
import time

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

TITLE = "Sustainability"
TAB = ("EV_SUSTAINABILITY", "Sustainability", "sustainability")
KEY = "FwSustainability"
PHASES = ["Material", "Manufacturing", "Transportation and Use", "End of Life"]
IMPACTS = [("carbon", "Carbon Footprint", "kg CO2e"), ("energy", "Total Energy Consumed", "MJ"),
           ("air", "Air Acidification", "kg SO2e"), ("water", "Water Eutrophication", "kg PO4e")]
COLOURS = ["#3b7dd8", "#e8a33d", "#5aaa50", "#9c5bc9"]
REGIONS = ["North America", "Europe", "Asia", "Japan", "South America"]
MODES = [("truck", "Truck"), ("train", "Train"), ("ship", "Ship"), ("air", "Airplane")]

# class -> {name: (density kg/m3, CO2 kg/kg, MJ/kg, SO2 kg/kg, PO4 kg/kg)} for virgin material
MATERIALS = {
    "Steel": {"Plain Carbon Steel": (7800, 2.0, 25.0, 0.0090, 0.0012), "AISI 1020": (7900, 2.0, 25.0, 0.0090, 0.0012),
              "Alloy Steel": (7700, 2.6, 33.0, 0.0110, 0.0015), "AISI 304": (8000, 6.2, 68.0, 0.0380, 0.0040),
              "Cast Alloy Steel": (7300, 2.4, 30.0, 0.0100, 0.0013)},
    "Iron": {"Gray Cast Iron": (7200, 1.6, 20.0, 0.0070, 0.0009), "Malleable Cast Iron": (7300, 1.8, 22.0, 0.0075, 0.0010),
             "Ductile Iron": (7100, 1.9, 23.0, 0.0080, 0.0010)},
    "Aluminum Alloys": {"1060 Alloy": (2700, 9.0, 170.0, 0.0480, 0.0030), "6061 Alloy": (2700, 9.5, 180.0, 0.0500, 0.0032),
                        "6063-T6": (2700, 9.5, 180.0, 0.0500, 0.0032), "7075-T6": (2810, 10.5, 195.0, 0.0560, 0.0035),
                        "A356.0-T6": (2670, 8.5, 160.0, 0.0450, 0.0029)},
    "Copper Alloys": {"Brass": (8500, 3.9, 60.0, 0.0300, 0.0025), "Copper": (8900, 4.2, 65.0, 0.0500, 0.0030),
                      "Bronze": (8800, 4.5, 68.0, 0.0450, 0.0030)},
    "Titanium Alloys": {"Ti-6Al-4V": (4430, 38.0, 600.0, 0.2100, 0.0120)},
    "Nickel Alloys": {"Nickel": (8900, 12.0, 160.0, 0.1600, 0.0060)},
    "Plastics": {"ABS": (1050, 3.5, 95.0, 0.0120, 0.0011), "ABS PC": (1100, 4.5, 105.0, 0.0140, 0.0013),
                 "Acrylic (Medium-high impact)": (1180, 6.0, 110.0, 0.0200, 0.0016),
                 "Nylon 6/10": (1140, 7.9, 140.0, 0.0250, 0.0050), "PE High Density": (950, 1.9, 77.0, 0.0060, 0.0006),
                 "PP Copolymer": (900, 2.0, 75.0, 0.0060, 0.0006), "PBT General Purpose": (1300, 4.4, 100.0, 0.0150, 0.0014),
                 "PLA": (1240, 2.0, 50.0, 0.0090, 0.0040), "PETG": (1270, 3.3, 85.0, 0.0110, 0.0010),
                 "PC": (1200, 6.0, 110.0, 0.0200, 0.0015)},
    "Rubber": {"Rubber": (1100, 3.0, 100.0, 0.0150, 0.0020)},
    "Woods": {"Balsa": (160, 0.4, 10.0, 0.0020, 0.0005), "Pine": (500, 0.4, 9.0, 0.0020, 0.0005),
              "Oak": (700, 0.5, 11.0, 0.0025, 0.0006)},
}
# share of each impact that recycled content saves (per class)
RECYCLE_SAVING = {"Steel": 0.6, "Iron": 0.6, "Aluminum Alloys": 0.9, "Copper Alloys": 0.7, "Titanium Alloys": 0.5,
                  "Nickel Alloys": 0.6, "Plastics": 0.5, "Rubber": 0.3, "Woods": 0.2}
# process -> (kWh per kg made, scrap as a share of the part's mass, classes it suits)
PROCESSES = {
    "Milled": (6.0, 0.6, ("Steel", "Iron", "Aluminum Alloys", "Copper Alloys", "Titanium Alloys", "Nickel Alloys",
                          "Plastics", "Woods")),
    "Turned": (4.5, 0.5, ("Steel", "Iron", "Aluminum Alloys", "Copper Alloys", "Titanium Alloys", "Nickel Alloys",
                          "Plastics", "Woods")),
    "Casting": (3.5, 0.15, ("Steel", "Iron", "Aluminum Alloys", "Copper Alloys")),
    "Forged": (4.0, 0.2, ("Steel", "Aluminum Alloys", "Copper Alloys", "Titanium Alloys", "Nickel Alloys")),
    "Extrusion": (1.5, 0.08, ("Aluminum Alloys", "Copper Alloys", "Plastics", "Rubber")),
    "Sheet Metal Rolled": (1.2, 0.12, ("Steel", "Aluminum Alloys", "Copper Alloys", "Titanium Alloys")),
    "Stamped": (1.0, 0.25, ("Steel", "Aluminum Alloys", "Copper Alloys")),
    "Injection Molded": (2.0, 0.03, ("Plastics", "Rubber")),
    "Blow Molded": (1.8, 0.05, ("Plastics",)),
    "Thermoformed": (1.6, 0.2, ("Plastics",)),
    "3D Printed": (8.0, 0.05, ("Plastics", "Steel", "Aluminum Alloys", "Titanium Alloys")),
    "Sawn and Planed": (0.6, 0.4, ("Woods",)),
}
# electricity per kWh by region: (CO2 kg, MJ primary, SO2 kg, PO4 kg)
GRID = {"North America": (0.42, 9.5, 0.0012, 0.00008), "Europe": (0.30, 9.0, 0.0007, 0.00005),
        "Asia": (0.65, 10.5, 0.0030, 0.00012), "Japan": (0.47, 9.6, 0.0006, 0.00005),
        "South America": (0.20, 7.5, 0.0009, 0.00006)}
# per tonne-km: (CO2 kg, MJ, SO2 kg, PO4 kg)
FREIGHT = {"truck": (0.105, 1.5, 0.00045, 0.00010), "train": (0.028, 0.45, 0.00012, 0.00002),
           "ship": (0.012, 0.15, 0.00025, 0.00002), "air": (0.600, 9.0, 0.00200, 0.00015)}
# end of life per kg: (CO2 kg, MJ, SO2 kg, PO4 kg)
END = {"recycled": (0.05, 1.0, 0.0002, 0.00002), "landfill": (0.04, 0.3, 0.0001, 0.00030),
       "incinerated_plastic": (2.4, -15.0, 0.0010, 0.00005), "incinerated_other": (0.05, 0.5, 0.0003, 0.00002)}

DEFAULTS = {"klass": "", "material": "", "recycled": 0.0, "region": "North America", "process": "",
            "years": 1.0, "use_region": "North America", "auto_distance": True,
            "truck": 0.0, "train": 0.0, "ship": 0.0, "air": 0.0, "kwh_year": 0.0,
            "eol_recycled": 30.0, "eol_incinerated": 10.0, "eol_landfill": 60.0, "baseline": None}


# ------------------------------------------------------------------------------ data
def find(name):
    """(class, name, data) of a material by name, or None."""
    if not name:
        return None
    low = name.replace("-Generic", "").lower()
    for k, mats in MATERIALS.items():
        for n, d in mats.items():
            if n.lower() == low:
                return k, n, d
    for k, mats in MATERIALS.items():      # "Aluminium 6061-T6", "Steel-Generic"...
        for n, d in mats.items():
            if n.lower() in low or low in n.lower():
                return k, n, d
    for word, k in (("alumin", "Aluminum Alloys"), ("steel", "Steel"), ("iron", "Iron"), ("brass", "Copper Alloys"),
                    ("copper", "Copper Alloys"), ("titan", "Titanium Alloys"), ("wood", "Woods")):
        if word in low:
            n = next(iter(MATERIALS[k]))
            return k, n, MATERIALS[k][n]
    return None


def processes_for(klass):
    return [p for p, (_k, _s, cls) in PROCESSES.items() if klass in cls]


def default_process(klass):
    return {"Plastics": "Injection Molded", "Rubber": "Injection Molded", "Iron": "Casting",
            "Woods": "Sawn and Planed"}.get(klass, "Milled")


def distances(region, use_region):
    """Default transport (km per mode) from the making region to the use region."""
    if region == use_region:
        return {"truck": 800.0, "train": 0.0, "ship": 0.0, "air": 0.0}
    return {"truck": 1000.0, "train": 0.0, "ship": 12000.0, "air": 0.0}


def settings(doc):
    out = dict(DEFAULTS)
    try:
        out.update(json.loads(doc.Meta.get(KEY, "") or "{}"))
    except Exception as _fw_err:
        _fw_log("sustainability.py:162", _fw_err)
    from . import material
    part = material.current(doc)[1] or ""
    if part and part != out.get("part_material", "") and find(part) is not None:

        out["klass"], out["material"] = find(part)[:2]
    out["part_material"] = part
    if not out["material"]:
        hit = find(part)
        if hit is None:
            hit = ("Steel", "Plain Carbon Steel", MATERIALS["Steel"]["Plain Carbon Steel"])
        out["klass"], out["material"] = hit[0], hit[1]
    if not out["klass"]:
        hit = find(out["material"])
        out["klass"] = hit[0] if hit else "Steel"
    if out["process"] not in processes_for(out["klass"]):
        out["process"] = default_process(out["klass"])
    if out["auto_distance"]:
        out.update(distances(out["region"], out["use_region"]))
    return out


def save(doc, values):
    meta = dict(doc.Meta)
    meta[KEY] = json.dumps(values, sort_keys=True)
    doc.Meta = meta


def body(doc):
    from . import evaltools
    return evaltools._main(doc)


def mass_kg(doc, s, obj=None):
    obj = obj or body(doc)
    if obj is None:
        return 0.0
    hit = find(s["material"])
    dens = hit[2][0] if hit else 7800
    return obj.Shape.Volume * 1e-9 * dens


def _add(a, b, k=1.0):
    return [x + y * k for x, y in zip(a, b)]


def impacts(doc=None, s=None, mass=None):
    """{"carbon": {phase: value}, ...} plus "total": {impact: value} and "mass"."""
    doc = doc or App.ActiveDocument
    s = s or settings(doc)
    m = mass_kg(doc, s) if mass is None else mass
    hit = find(s["material"]) or ("Steel", "Plain Carbon Steel", MATERIALS["Steel"]["Plain Carbon Steel"])
    klass, _n, d = hit
    kwh, scrap, _c = PROCESSES.get(s["process"], PROCESSES["Milled"])
    bought = m * (1 + scrap)
    saving = RECYCLE_SAVING.get(klass, 0.5) * max(0.0, min(100.0, s["recycled"])) / 100.0
    mat = [x * bought * (1 - saving) for x in d[1:]]
    grid = GRID.get(s["region"], GRID["North America"])
    man = [x * kwh * bought for x in grid]
    t = [0.0] * 4
    tonnes = m / 1000.0
    for mode, _label in MODES:
        t = _add(t, FREIGHT[mode], tonnes * float(s.get(mode) or 0))
    use_grid = GRID.get(s["use_region"], GRID["North America"])
    t = _add(t, use_grid, float(s["kwh_year"] or 0) * max(float(s["years"] or 0), 0))
    total = max(s["eol_recycled"] + s["eol_incinerated"] + s["eol_landfill"], 1e-9)
    burn = END["incinerated_plastic" if klass in ("Plastics", "Rubber") else "incinerated_other"]
    eol = [0.0] * 4
    for share, f in ((s["eol_recycled"], END["recycled"]), (s["eol_incinerated"], burn),
                     (s["eol_landfill"], END["landfill"])):
        eol = _add(eol, f, m * share / total)
    out = {"mass": m, "total": {}}
    for i, (key, _l, _u) in enumerate(IMPACTS):
        out[key] = dict(zip(PHASES, (mat[i], man[i], t[i], eol[i])))
        out["total"][key] = sum(out[key].values())
    return out


# ------------------------------------------------------------------------------ assemblies
ASSEMBLY_DEFAULTS = {"asm_kwh": 0.0, "excluded": []}


def _assembly(doc):
    from . import costing
    return costing._assembly(doc) if doc is not None else None


def assembly_settings(doc):
    out = dict(DEFAULTS)
    out.update(ASSEMBLY_DEFAULTS)
    try:
        out.update(json.loads(doc.Meta.get(KEY, "") or "{}"))
    except Exception as _fw_err:
        _fw_log("sustainability.py:assembly_settings", _fw_err)
    if out["auto_distance"]:
        out.update(distances(out["region"], out["use_region"]))
    return out


def assembly_impacts(doc, s=None):
    """{"rows": [(part document, count, material, mass kg each, carbon, included)], the four impacts by phase,
    "total" and "mass"} for an assembly: each part's material and manufacturing from its own settings, times
    how many the assembly uses; the assembly's energy to assemble is manufacturing, made in its region;
    transportation, use and end of life follow the assembly's settings for the whole mass."""
    from . import costing
    s = s or assembly_settings(doc)
    out = {"rows": [], "mass": 0.0, "total": {}}
    for key, _l, _u in IMPACTS:
        out[key] = dict((ph, 0.0) for ph in PHASES)
    whole = dict((k, s[k]) for k in ("use_region", "years", "kwh_year", "eol_recycled", "eol_incinerated",
                                     "eol_landfill") + tuple(m for m, _l in MODES))
    first = True
    for d, n in costing.assembly_parts(doc):
        try:
            ps = settings(d)
            ps.update(whole)
            if not first:
                ps["kwh_year"] = 0.0        # the energy in use is the assembly's, counted once
            r = impacts(d, ps)
        except Exception as error:
            _fw_log("sustainability.py:assembly_impacts", error)
            continue
        on = d.Name not in (s.get("excluded") or [])
        out["rows"].append((d, n, ps["material"], r["mass"], r["total"]["carbon"] * n, on))
        if not on:
            continue
        first = False
        out["mass"] += r["mass"] * n
        for key, _l, _u in IMPACTS:
            for ph in PHASES:
                out[key][ph] += r[key][ph] * n
    grid = GRID.get(s["region"], GRID["North America"])
    for i, (key, _l, _u) in enumerate(IMPACTS):
        out[key]["Manufacturing"] += grid[i] * float(s.get("asm_kwh") or 0)
        out["total"][key] = sum(out[key].values())
    return out


def assembly_report(doc, folder=None, s=None):
    s = s or assembly_settings(doc)
    r = assembly_impacts(doc, s)
    folder = folder or (os.path.dirname(doc.FileName) if getattr(doc, "FileName", "") else
                        os.path.join(os.path.expanduser("~"), "FreeCAD", "Sustainability"))
    os.makedirs(folder, exist_ok=True)
    base = doc.Label or doc.Name
    n = 1
    while os.path.exists(os.path.join(folder, "%s-Sustainability-%d.html" % (base, n))):
        n += 1
    path = os.path.join(folder, "%s-Sustainability-%d.html" % (base, n))
    e = html.escape
    comps = "".join("<tr><td>%s</td><td>%d</td><td>%s</td><td>%.4g</td><td>%.4g</td><td>%s</td></tr>"
                    % (e(d.Label or d.Name), c, e(m), kg, co2, "" if on else "left out")
                    for d, c, m, kg, co2, on in r["rows"])
    rows = []
    for key, label, unit in IMPACTS:
        cells = "".join("<td>%.4g</td>" % r[key][p] for p in PHASES)
        b = (s.get("baseline") or {}).get(key)
        rows.append("<tr><th>%s (%s)</th>%s<td><b>%.4g</b></td><td>%s</td></tr>"
                    % (e(label), e(unit), cells, r["total"][key], "%.4g" % b if b is not None else ""))
    text = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>%s</title>" % e(base),
            "<style>body{font-family:sans-serif;margin:24px}table{border-collapse:collapse;margin:12px 0}"
            "td,th{border:1px solid #bbb;padding:4px 8px;text-align:left}</style></head><body>",
            "<h1>Sustainability Report: %s</h1><p>%s</p>" % (e(base), time.strftime("%Y-%m-%d %H:%M")),
            "<p>Assembly mass %.4g kg; assembled in %s with %g kWh; used in %s for %g years.</p>"
            % (r["mass"], e(s["region"]), float(s.get("asm_kwh") or 0), e(s["use_region"]), s["years"]),
            "<h2>Components</h2><table><tr><th>Part</th><th>Count</th><th>Material</th><th>Mass each (kg)</th>"
            "<th>Carbon (kg CO2e)</th><th></th></tr>%s</table>" % comps,
            "<h2>Environmental Impact</h2><table><tr><th></th>%s<th>Total</th><th>Baseline</th></tr>%s</table>"
            % ("".join("<th>%s</th>" % e(p) for p in PHASES), "".join(rows)),
            "<p>Estimates from generic life-cycle factors, for comparing designs.</p></body></html>"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(text))
    with open(path[:-5] + ".json", "w", encoding="utf-8") as f:
        json.dump({"part": base, "totals": r["total"]}, f)
    return path


def similar(doc, s=None, klass=None):
    """[(name, totals)] for the materials of a class (the current settings otherwise)."""
    s = dict(s or settings(doc))
    klass = klass or s["klass"]
    vol = 0.0
    obj = body(doc)
    if obj is not None:
        vol = obj.Shape.Volume * 1e-9
    out = []
    for n, d in MATERIALS[klass].items():
        t = dict(s, material=n, klass=klass)
        if t["process"] not in processes_for(klass):
            t["process"] = default_process(klass)
        out.append((n, impacts(doc, t, vol * d[0])["total"]))
    return out


def report(doc, folder=None, s=None):
    s = s or settings(doc)
    r = impacts(doc, s)
    folder = folder or (os.path.dirname(doc.FileName) if getattr(doc, "FileName", "") else
                        os.path.join(os.path.expanduser("~"), "FreeCAD", "Sustainability"))
    os.makedirs(folder, exist_ok=True)
    base = doc.Label or doc.Name
    n = 1
    while os.path.exists(os.path.join(folder, "%s-Sustainability-%d.html" % (base, n))):
        n += 1
    path = os.path.join(folder, "%s-Sustainability-%d.html" % (base, n))
    e = html.escape
    rows = []
    for key, label, unit in IMPACTS:
        cells = "".join("<td>%.4g</td>" % r[key][p] for p in PHASES)
        b = (s.get("baseline") or {}).get(key)
        rows.append("<tr><th>%s (%s)</th>%s<td><b>%.4g</b></td><td>%s</td></tr>"
                    % (e(label), e(unit), cells, r["total"][key], "%.4g" % b if b is not None else ""))
    settings_rows = [("Material", "%s (%s)" % (s["material"], s["klass"])), ("Recycled content", "%g %%" % s["recycled"]),
                     ("Mass", "%.4g kg" % r["mass"]), ("Manufacturing region", s["region"]),
                     ("Process", s["process"]), ("Built to last", "%g years" % s["years"]),
                     ("Use region", s["use_region"])] + \
        [(label + " distance", "%g km" % s[k]) for k, label in MODES] + \
        [("Energy in use", "%g kWh per year" % s["kwh_year"]),
         ("End of life", "%g %% recycled, %g %% incinerated, %g %% landfill"
          % (s["eol_recycled"], s["eol_incinerated"], s["eol_landfill"]))]
    text = ["<!DOCTYPE html><html><head><meta charset='utf-8'><title>%s</title>" % e(base),
            "<style>body{font-family:sans-serif;margin:24px}table{border-collapse:collapse;margin:12px 0}"
            "td,th{border:1px solid #bbb;padding:4px 8px;text-align:left}</style></head><body>",
            "<h1>Sustainability Report: %s</h1><p>%s</p>" % (e(base), time.strftime("%Y-%m-%d %H:%M")),
            "<h2>Settings</h2><table>%s</table>" % "".join("<tr><th>%s</th><td>%s</td></tr>" % (e(a), e(b))
                                                           for a, b in settings_rows),
            "<h2>Environmental Impact</h2><table><tr><th></th>%s<th>Total</th><th>Baseline</th></tr>%s</table>"
            % ("".join("<th>%s</th>" % e(p) for p in PHASES), "".join(rows)),
            "<p>Estimates from generic life-cycle factors, for comparing designs.</p></body></html>"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(text))
    with open(path[:-5] + ".json", "w", encoding="utf-8") as f:
        json.dump({"part": base, "totals": r["total"]}, f)
    return path


# ------------------------------------------------------------------------------ the pane
if Gui is not None:

    def _alive(w):
        try:
            w.objectName()
            return True
        except RuntimeError:
            return False

    class Dial(QtWidgets.QWidget):
        """One impact: a pie by phase, the total, and the baseline beside it."""

        def __init__(self, key, label, unit):
            super().__init__()
            self.setObjectName("SWSustDial_" + key)
            self.key, self.label, self.unit = key, label, unit
            self.parts, self.total, self.baseline = {}, 0.0, None
            self.setMinimumSize(110, 170)

        def set_values(self, parts, total, baseline):
            self.parts, self.total, self.baseline = parts, total, baseline
            self.setToolTip("\n".join("%s: %.4g %s" % (p, parts.get(p, 0), self.unit) for p in PHASES))
            self.update()

        def paintEvent(self, _e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            w, h = self.width(), self.height()
            pal = self.palette()
            p.setPen(pal.color(QtGui.QPalette.WindowText))
            f = p.font()
            f.setBold(True)
            p.setFont(f)
            fm = QtGui.QFontMetrics(f)
            top = 34 if fm.horizontalAdvance(self.label) > w - 4 else 18
            p.drawText(QtCore.QRectF(0, 0, w, top), QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap, self.label)
            f.setBold(False)
            p.setFont(f)
            size = min(w - 20, h - 46 - top)
            rect = QtCore.QRectF((w - size) / 2, top + 4, size, size)
            values = [max(self.parts.get(ph, 0.0), 0.0) for ph in PHASES]
            s = sum(values)
            start = 90 * 16
            if s > 0:
                for v, c in zip(values, COLOURS):
                    span = -int(round(v / s * 360 * 16))
                    p.setBrush(QtGui.QColor(c))
                    p.setPen(QtCore.Qt.NoPen)
                    p.drawPie(rect, start, span)
                    start += span
            else:
                p.setPen(pal.color(QtGui.QPalette.Mid))
                p.drawEllipse(rect)
            p.setPen(pal.color(QtGui.QPalette.WindowText))
            p.drawText(QtCore.QRectF(0, top + 6 + size, w, 18), QtCore.Qt.AlignCenter, "%.3g %s" % (self.total, self.unit))
            if self.baseline:
                diff = (self.total - self.baseline) / self.baseline * 100
                p.setPen(QtGui.QColor("#2e8b3a" if diff <= 0 else "#c0392b"))
                p.drawText(QtCore.QRectF(0, top + 24 + size, w, 18), QtCore.Qt.AlignCenter,
                           "Baseline %.3g (%+.0f %%)" % (self.baseline, diff))
            p.end()

    class SimilarDialog(QtWidgets.QDialog):
        """Find Similar Material: the class's materials and their impacts; Accept takes the picked one."""

        def __init__(self, doc, s, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.setObjectName("SWSustSimilar")
            self.setWindowTitle("Find Similar Material")
            self.doc, self.s, self.picked = doc, s, None
            lay = QtWidgets.QVBoxLayout(self)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Class:"))
            self.klass = QtWidgets.QComboBox()
            self.klass.setObjectName("SWSustSimilarClass")
            self.klass.addItems(list(MATERIALS))
            self.klass.setCurrentText(s["klass"])
            row.addWidget(self.klass, 1)
            lay.addLayout(row)
            self.table = QtWidgets.QTableWidget(0, 1 + len(IMPACTS))
            self.table.setObjectName("SWSustSimilarTable")
            self.table.setHorizontalHeaderLabels(["Material"] + ["%s (%s)" % (l, u) for _k, l, u in IMPACTS])
            self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.table)
            bb = QtWidgets.QDialogButtonBox()
            self.accept_btn = bb.addButton("Accept", QtWidgets.QDialogButtonBox.AcceptRole)
            self.accept_btn.setObjectName("SWSustSimilarAccept")
            bb.addButton(QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            self.klass.currentTextChanged.connect(self.fill)
            self.resize(760, 360)
            self.fill()

        def fill(self, *_a):
            rows = similar(self.doc, self.s, self.klass.currentText())
            rows.sort(key=lambda r: r[1]["carbon"])
            self.table.setRowCount(0)
            for name, tot in rows:
                r = self.table.rowCount()
                self.table.insertRow(r)
                it = QtWidgets.QTableWidgetItem(name)
                if name == self.s["material"]:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.table.setItem(r, 0, it)
                for c, (k, _l, _u) in enumerate(IMPACTS, 1):
                    self.table.setItem(r, c, QtWidgets.QTableWidgetItem("%.4g" % tot[k]))

        def accept(self):
            r = self.table.currentRow()
            if r >= 0:
                self.picked = (self.klass.currentText(), self.table.item(r, 0).text())
            super().accept()

    class SustainabilityPage(QtWidgets.QWidget):
        def __init__(self, pane=None):
            super().__init__()
            self.setObjectName("SWSustainability")
            self.doc = App.ActiveDocument
            self.s = settings(self.doc) if self.doc is not None else dict(DEFAULTS)
            self._busy = True
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(4, 4, 4, 4)
            area = QtWidgets.QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QtWidgets.QFrame.NoFrame)
            area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            inner = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(inner)
            area.setWidget(inner)
            outer.addWidget(area)
            lay.addWidget(QtWidgets.QLabel("<b>Sustainability</b>"))

            g = self._group(lay, "Material", "SWSustMaterialBox")
            f = QtWidgets.QFormLayout(g)
            self.klass = self._combo("SWSustClass", list(MATERIALS))
            self.material = self._combo("SWSustMaterial", [])
            self.similar_btn = QtWidgets.QPushButton("Find Similar...")
            self.similar_btn.setObjectName("SWSustFindSimilar")
            self.recycled = self._spin("SWSustRecycled", 0, 100, 0, " %")
            f.addRow("Class:", self.klass)
            f.addRow("Name:", self.material)
            f.addRow("", self.similar_btn)
            f.addRow("Recycled content:", self.recycled)

            g = self._group(lay, "Manufacturing", "SWSustManufacturingBox")
            f = QtWidgets.QFormLayout(g)
            self.region = self._combo("SWSustRegion", REGIONS)
            self.process = self._combo("SWSustProcess", [])
            self.years = self._spin("SWSustYears", 0, 200, 1, " years")
            self.mass = QtWidgets.QLabel("")
            self.mass.setObjectName("SWSustMass")
            f.addRow("Region:", self.region)
            f.addRow("Process:", self.process)
            f.addRow("Built to last:", self.years)
            f.addRow("Part mass:", self.mass)

            g = self._group(lay, "Transportation and Use", "SWSustTransportBox")
            f = QtWidgets.QFormLayout(g)
            self.use_region = self._combo("SWSustUseRegion", REGIONS)
            self.auto = QtWidgets.QCheckBox("From the regions")
            self.auto.setObjectName("SWSustAutoDistance")
            f.addRow("Use region:", self.use_region)
            f.addRow("", self.auto)
            self.dist = {}
            for k, label in MODES:
                sp = self._spin("SWSustDist_" + k, 0, 100000, 0, " km")
                self.dist[k] = sp
                f.addRow(label + ":", sp)
            self.kwh = self._spin("SWSustKwh", 0, 1e6, 1, " kWh/year")
            f.addRow("Energy in use:", self.kwh)

            g = self._group(lay, "End of Life", "SWSustEndBox")
            f = QtWidgets.QFormLayout(g)
            self.eol = {}
            for k, label in (("eol_recycled", "Recycled"), ("eol_incinerated", "Incinerated"),
                             ("eol_landfill", "Landfill")):
                sp = self._spin("SWSust_" + k, 0, 100, 0, " %")
                self.eol[k] = sp
                f.addRow(label + ":", sp)

            g = self._group(lay, "Environmental Impact", "SWSustImpactBox")
            v = QtWidgets.QVBoxLayout(g)
            grid = QtWidgets.QGridLayout()
            self.dials = {}
            for i, (k, label, unit) in enumerate(IMPACTS):
                d = Dial(k, label, unit)
                self.dials[k] = d
                grid.addWidget(d, i // 2, i % 2)
            v.addLayout(grid)
            legend = QtWidgets.QGridLayout()
            for i, (ph, c) in enumerate(zip(PHASES, COLOURS)):
                lab = QtWidgets.QLabel("<span style='color:%s'>&#9632;</span> %s" % (c, ph))
                legend.addWidget(lab, i // 2, i % 2)
            v.addLayout(legend)
            self.versus = QtWidgets.QLabel("")
            self.versus.setObjectName("SWSustVersus")
            self.versus.setWordWrap(True)
            v.addWidget(self.versus)

            row = QtWidgets.QGridLayout()
            for i, (attr, text, name, fn) in enumerate( (("base_btn", "Set Baseline", "SWSustBaseline", self.set_baseline),
                                         ("import_btn", "Import Baseline...", "SWSustImport", self.import_baseline),
                                         ("report_btn", "Generate Report", "SWSustReport", self.make_report),
                                         ("close_btn", "Close", "SWSustClose", close))):
                b = QtWidgets.QPushButton(text)
                b.setObjectName(name)
                b.clicked.connect(fn)
                setattr(self, attr, b)
                row.addWidget(b, i // 2, i % 2)
            outer.addLayout(row)
            self.status = QtWidgets.QLabel("")
            self.status.setObjectName("SWSustStatus")
            self.status.setWordWrap(True)
            outer.addWidget(self.status)

            self.load()
            self.klass.currentTextChanged.connect(self._class_changed)
            self.material.currentTextChanged.connect(lambda *_: self.changed())
            self.similar_btn.clicked.connect(self.find_similar)
            for w in (self.region, self.process, self.use_region):
                w.currentTextChanged.connect(lambda *_: self.changed())
            for w in [self.recycled, self.years, self.kwh] + list(self.dist.values()):
                w.valueChanged.connect(lambda *_: self.changed())
            for k, w in self.eol.items():
                w.valueChanged.connect(lambda v, k=k: self._eol_changed(k))
            self.auto.toggled.connect(lambda *_: self.changed())
            self._busy = False
            self.refresh()

        # -- building
        def _group(self, lay, title, name):
            g = QtWidgets.QGroupBox(title)
            g.setObjectName(name)
            lay.addWidget(g)
            return g

        def _combo(self, name, items):
            c = QtWidgets.QComboBox()
            c.setObjectName(name)
            c.addItems(items)
            c.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(8)
            return c

        def _spin(self, name, lo, hi, dec, suffix=""):
            s = QtWidgets.QDoubleSpinBox()
            s.setObjectName(name)
            s.setRange(lo, hi)
            s.setDecimals(dec)
            s.setSuffix(suffix)
            s.setMinimumWidth(60)
            s.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            return s

        def _set_items(self, combo, items, current):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(items)
            if current in items:
                combo.setCurrentText(current)
            combo.blockSignals(False)

        # -- values
        def load(self):
            s = self.s
            self._busy = True
            self.klass.setCurrentText(s["klass"])
            self._set_items(self.material, list(MATERIALS[s["klass"]]), s["material"])
            self._set_items(self.process, processes_for(s["klass"]), s["process"])
            self.recycled.setValue(s["recycled"])
            self.region.setCurrentText(s["region"])
            self.years.setValue(s["years"])
            self.use_region.setCurrentText(s["use_region"])
            self.auto.setChecked(bool(s["auto_distance"]))
            for k, w in self.dist.items():
                w.setValue(float(s[k]))
                w.setEnabled(not s["auto_distance"])
            self.kwh.setValue(s["kwh_year"])
            for k, w in self.eol.items():
                w.setValue(s[k])
            self._busy = False

        def read(self):
            s = dict(self.s)
            s.update(klass=self.klass.currentText(), material=self.material.currentText(),
                     recycled=self.recycled.value(), region=self.region.currentText(),
                     process=self.process.currentText(), years=self.years.value(),
                     use_region=self.use_region.currentText(), auto_distance=self.auto.isChecked(),
                     kwh_year=self.kwh.value())
            for k, w in self.dist.items():
                s[k] = w.value()
            for k, w in self.eol.items():
                s[k] = w.value()
            if s["auto_distance"]:
                s.update(distances(s["region"], s["use_region"]))
            return s

        def _class_changed(self, klass):
            if self._busy:
                return
            self._set_items(self.material, list(MATERIALS[klass]), "")
            self._set_items(self.process, processes_for(klass), default_process(klass))
            self.changed()

        def _eol_changed(self, key):
            """End of life always adds up to 100 %: the next field takes up the difference."""
            if self._busy:
                return
            order = ["eol_recycled", "eol_incinerated", "eol_landfill"]
            rest = 100.0 - sum(self.eol[k].value() for k in order)
            if abs(rest) > 1e-9:
                i = order.index(key)
                for j in range(1, 3):
                    w = self.eol[order[(i + j) % 3]]
                    nv = max(0.0, min(100.0, w.value() + rest))
                    rest -= nv - w.value()
                    self._busy = True
                    w.setValue(nv)
                    self._busy = False
                    if abs(rest) < 1e-9:
                        break
            self.changed()

        def changed(self):
            if self._busy:
                return
            self.s = self.read()
            self.load()
            if self.doc is not None:
                save(self.doc, self.s)
            self.refresh()

        def refresh(self):
            if self.doc is None or body(self.doc) is None:
                self.status.setText("Open a part with a solid body.")
                return
            r = impacts(self.doc, self.s)
            self.mass.setText("%.4g kg" % r["mass"])
            b = self.s.get("baseline") or {}
            for k, d in self.dials.items():
                d.set_values(r[k], r["total"][k], b.get(k))
            self.result = r
            if b:
                parts = []
                for k, label, unit in IMPACTS:
                    if b.get(k):
                        parts.append("%s %+.0f %%" % (label, (r["total"][k] - b[k]) / b[k] * 100))
                self.versus.setText("Against the baseline: " + ", ".join(parts))
            else:
                self.versus.setText("Set Baseline to compare a change of material or design.")

        # -- actions
        def find_similar(self):
            d = SimilarDialog(self.doc, self.s, self)
            if d.exec_() and d.picked:
                self.klass.blockSignals(True)
                self.klass.setCurrentText(d.picked[0])
                self.klass.blockSignals(False)
                self._set_items(self.material, list(MATERIALS[d.picked[0]]), d.picked[1])
                if self.process.currentText() not in processes_for(d.picked[0]):
                    self._set_items(self.process, processes_for(d.picked[0]), default_process(d.picked[0]))
                self.changed()

        def set_baseline(self):
            self.s["baseline"] = dict(impacts(self.doc, self.s)["total"])
            save(self.doc, self.s)
            self.refresh()
            self.status.setText("Baseline set.")

        def import_baseline(self, path=None):
            if not path:
                path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Import Baseline", os.path.expanduser("~"),
                                                                 "Sustainability report data (*.json)")
            if not path:
                return
            try:
                data = json.load(open(path, encoding="utf-8"))
                self.s["baseline"] = {k: float(data["totals"][k]) for k, _l, _u in IMPACTS}
            except Exception as e:
                self.status.setText("Not a Sustainability report data file: %s" % e)
                return
            save(self.doc, self.s)
            self.refresh()
            self.status.setText("Baseline imported from %s." % data.get("part", os.path.basename(path)))

        def make_report(self, folder=None, open_it=True):
            try:
                path = report(self.doc, folder or None, self.s)
            except Exception as e:
                self.status.setText(str(e))
                return None
            self.status.setText("Report saved: %s" % path)
            if open_it:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
            return path

    class AssemblySustainabilityPage(QtWidgets.QWidget):
        """The assembly's page: Components, Assembly Process, Transportation and Use, End of Life, the impacts."""

        def __init__(self, pane=None):
            super().__init__()
            self.setObjectName("SWSustainabilityAssembly")
            self.doc = App.ActiveDocument
            self._busy = True
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(4, 4, 4, 4)
            area = QtWidgets.QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QtWidgets.QFrame.NoFrame)
            area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            inner = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(inner)
            area.setWidget(inner)
            outer.addWidget(area)
            lay.addWidget(QtWidgets.QLabel("<b>Sustainability</b> (assembly)"))
            g = SustainabilityPage._group(self, lay, "Components", "SWSustComponentsBox")
            v = QtWidgets.QVBoxLayout(g)
            self.table = QtWidgets.QTableWidget(0, 4)
            self.table.setObjectName("SWSustComponents")
            self.table.setHorizontalHeaderLabels(["Part", "Count", "Material", "Carbon"])
            self.table.verticalHeader().hide()
            self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.table.itemChanged.connect(self._ticked)
            self.table.cellDoubleClicked.connect(lambda *_a: self.open_part())
            v.addWidget(self.table)
            b = QtWidgets.QPushButton("Open Part")
            b.setObjectName("SWSustOpenPart")
            b.clicked.connect(lambda *_a: self.open_part())
            v.addWidget(b)
            g = SustainabilityPage._group(self, lay, "Assembly Process", "SWSustAssemblyBox")
            f = QtWidgets.QFormLayout(g)
            self.region = SustainabilityPage._combo(self, "SWSustRegion", REGIONS)
            self.asm_kwh = SustainabilityPage._spin(self, "SWSustAssemblyEnergy", 0, 1e6, 2, " kWh")
            self.years = SustainabilityPage._spin(self, "SWSustYears", 0, 200, 1, " years")
            f.addRow("Region:", self.region)
            f.addRow("Energy to assemble:", self.asm_kwh)
            f.addRow("Built to last:", self.years)
            g = SustainabilityPage._group(self, lay, "Transportation and Use", "SWSustTransportBox")
            f = QtWidgets.QFormLayout(g)
            self.use_region = SustainabilityPage._combo(self, "SWSustUseRegion", REGIONS)
            f.addRow("Use region:", self.use_region)
            self.auto = QtWidgets.QCheckBox("Distances from the regions")
            self.auto.setObjectName("SWSustAutoDistance")
            f.addRow("", self.auto)
            self.modes = {}
            for k, label in MODES:
                self.modes[k] = SustainabilityPage._spin(self, "SWSust_" + k, 0, 1e6, 0, " km")
                f.addRow(label + ":", self.modes[k])
            self.kwh_year = SustainabilityPage._spin(self, "SWSustKwh", 0, 1e7, 1, " kWh/year")
            f.addRow("Energy in use:", self.kwh_year)
            g = SustainabilityPage._group(self, lay, "End of Life", "SWSustEndBox")
            f = QtWidgets.QFormLayout(g)
            self.eol = {}
            for k, label in (("eol_recycled", "Recycled"), ("eol_incinerated", "Incinerated"), ("eol_landfill", "Landfill")):
                self.eol[k] = SustainabilityPage._spin(self, "SWSust_" + k, 0, 100, 0, " %")
                f.addRow(label + ":", self.eol[k])
            g = SustainabilityPage._group(self, lay, "Environmental Impact", "SWSustImpactBox")
            grid = QtWidgets.QGridLayout(g)
            self.dials = []
            for i, (key, label, unit) in enumerate(IMPACTS):
                d = Dial(key, label, unit)
                self.dials.append(d)
                grid.addWidget(d, i // 2, i % 2)
            self.mass = QtWidgets.QLabel()
            self.mass.setObjectName("SWSustAssemblyMass")
            lay.addWidget(self.mass)
            row = QtWidgets.QHBoxLayout()
            for text, name, fn in (("Set Baseline", "SWSustBaseline", self.set_baseline),
                                   ("Generate Report", "SWSustReport", lambda: self.make_report()),
                                   ("Close", "SWSustClose", lambda: close())):
                b = QtWidgets.QPushButton(text)
                b.setObjectName(name)
                b.clicked.connect(lambda *_a, fn=fn: fn())
                row.addWidget(b)
            lay.addLayout(row)
            lay.addStretch(1)
            for w in [self.region, self.use_region]:
                w.currentIndexChanged.connect(lambda *_a: self.changed())
            for w in [self.asm_kwh, self.years, self.kwh_year] + list(self.modes.values()) + list(self.eol.values()):
                w.valueChanged.connect(lambda *_a: self.changed())
            self.auto.toggled.connect(lambda *_a: self.changed())
            self.load()

        def load(self):
            self._busy = True
            try:
                s = assembly_settings(self.doc)
                self.region.setCurrentText(s["region"])
                self.use_region.setCurrentText(s["use_region"])
                self.asm_kwh.setValue(float(s["asm_kwh"]))
                self.years.setValue(float(s["years"]))
                self.kwh_year.setValue(float(s["kwh_year"]))
                self.auto.setChecked(bool(s["auto_distance"]))
                for k, w in self.modes.items():
                    w.setValue(float(s[k]))
                    w.setEnabled(not s["auto_distance"])
                for k, w in self.eol.items():
                    w.setValue(float(s[k]))
            finally:
                self._busy = False
            self.refresh()

        def read(self):
            s = assembly_settings(self.doc)
            s.update(region=self.region.currentText(), use_region=self.use_region.currentText(),
                     asm_kwh=self.asm_kwh.value(), years=self.years.value(), kwh_year=self.kwh_year.value(),
                     auto_distance=self.auto.isChecked())
            for k, w in self.modes.items():
                s[k] = w.value()
            for k, w in self.eol.items():
                s[k] = w.value()
            return s

        def changed(self):
            if self._busy or self.doc is None:
                return
            save(self.doc, self.read())
            self.load()

        def _ticked(self, item):
            if self._busy or item.column() != 0:
                return
            s = assembly_settings(self.doc)
            name = item.data(QtCore.Qt.UserRole)
            ex = set(s.get("excluded") or [])
            if item.checkState() == QtCore.Qt.Checked:
                ex.discard(name)
            else:
                ex.add(name)
            s["excluded"] = sorted(ex)
            save(self.doc, s)
            self.refresh()

        def refresh(self):
            if self.doc is None:
                return None
            s = assembly_settings(self.doc)
            r = assembly_impacts(self.doc, s)
            self._busy = True
            try:
                self.table.setRowCount(0)
                for d, n, m, _kg, co2, on in r["rows"]:
                    i = self.table.rowCount()
                    self.table.insertRow(i)
                    for col, text in enumerate((d.Label or d.Name, str(n), m, "%.3g kg CO2e" % co2)):
                        it = QtWidgets.QTableWidgetItem(text)
                        it.setData(QtCore.Qt.UserRole, d.Name)
                        if col == 0:
                            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                            it.setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
                        self.table.setItem(i, col, it)
            finally:
                self._busy = False
            for d in self.dials:
                d.set_values(r[d.key], r["total"][d.key], (s.get("baseline") or {}).get(d.key))
            self.mass.setText("Assembly mass: %.4g kg" % r["mass"])
            self.last = r
            return r

        def set_baseline(self):
            s = assembly_settings(self.doc)
            s["baseline"] = dict(assembly_impacts(self.doc, s)["total"])
            save(self.doc, s)
            self.refresh()

        def open_part(self):
            row = self.table.currentRow()
            if row < 0:
                return None
            d = App.getDocument(self.table.item(row, 0).data(QtCore.Qt.UserRole))
            App.setActiveDocument(d.Name)
            gd = Gui.getDocument(d.Name)
            Gui.ActiveDocument = gd
            views = gd.mdiViewsOfType("Gui::View3DInventor")
            if views:
                Gui.getMainWindow().setActiveWindow(views[0])
            QtCore.QTimer.singleShot(0, open_sustainability)
            return d

        def make_report(self, folder=None, open_it=True):
            try:
                path = assembly_report(self.doc, folder)
            except Exception as error:
                QtWidgets.QMessageBox.warning(self, TITLE, str(error))
                return None
            if open_it:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
            return path

    _state = {"page": None, "dock": None}

    def _page(pane):
        p = AssemblySustainabilityPage(pane) if _assembly(App.ActiveDocument) is not None else SustainabilityPage(pane)
        _state["page"] = p
        return p

    def open_sustainability():
        from . import simxpress, taskpane
        page = _state.get("page")
        if page is not None and _alive(page) and page.doc is not App.ActiveDocument:
            close()                     # another part's (or the assembly's) page: a new one
        index = simxpress.add_tab(TAB, _page)
        page = taskpane.open_tab(index)
        if page is None:
            dock = _state.get("dock")
            if dock is None or not _alive(dock):
                dock = QtWidgets.QDockWidget(TITLE, Gui.getMainWindow())
                dock.setObjectName("SWSustainabilityDock")
                dock.setWidget(_page(None))
                Gui.getMainWindow().addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
                _state["dock"] = dock
            dock.show()
            page = dock.widget()
        else:
            try:
                page.parentWidget().parentWidget().pin.setChecked(True)
            except Exception as _fw_err:
                _fw_log("sustainability.py:723", _fw_err)
        _state["page"] = page
        return page

    def close():
        from . import simxpress
        simxpress.remove_tab(TAB)
        dock = _state.get("dock")
        if dock is not None and _alive(dock):
            dock.close()
            dock.deleteLater()
        _state.update(page=None, dock=None)

    def page():
        p = _state.get("page")
        return p if p is not None and _alive(p) else None
