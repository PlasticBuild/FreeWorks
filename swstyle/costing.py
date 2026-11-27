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

TITLE = "Costing"
TAB = ("EV_COSTING", "Costing", "costing")
METHODS = ["Machining", "Sheet Metal", "Casting", "Plastic", "3D Printing"]
STOCKS = ["Block", "Cylinder", "Plate"]
KEY = "FwCosting"
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Costing"

# cost per kg by material family (generic market figures, editable per material in the pane)
PRICE = (("steel", 1.2), ("aisi 304", 4.0), ("stainless", 4.0), ("iron", 0.9), ("alumin", 4.5), ("alloy", 4.0),
         ("6061", 4.5), ("6063", 4.2), ("7075", 7.0), ("1060", 3.8), ("brass", 7.0), ("copper", 9.0),
         ("nickel", 18.0), ("titan", 30.0), ("abs", 2.5), ("pla", 2.2), ("petg", 2.8), ("nylon", 4.0),
         ("pe ", 1.6), ("pp ", 1.5), ("pbt", 3.0), ("acrylic", 3.0), ("rubber", 3.0), ("wood", 1.0),
         ("balsa", 6.0), ("pine", 0.8), ("oak", 2.5))
# removal rate cm^3/min by family (machining)
REMOVAL = (("alumin", 30.0), ("6061", 30.0), ("6063", 30.0), ("7075", 25.0), ("1060", 30.0), ("brass", 20.0),
           ("copper", 15.0), ("titan", 3.0), ("stainless", 5.0), ("aisi 304", 5.0), ("nickel", 4.0),
           ("iron", 10.0), ("steel", 8.0), ("abs", 40.0), ("pla", 40.0), ("nylon", 35.0), ("wood", 60.0))
DEFAULTS = {"method": "Machining", "material": "", "price": 0.0, "stock": "Block", "extra": 2.0, "quantity": 100,
            "lot": 50, "rate": 60.0, "setup": 80.0, "markup": 0.0, "excluded": [], "overrides": {}, "baseline": None,
            "prices": {}, "template": "", "custom": []}
# the operations a template can speed up or slow down (a factor on their time)
OPERATION_NAMES = (("load", "Load and unload"), ("remove", "Stock removal"), ("drill", "Drilling"),
                   ("finish", "Finish faces"), ("edges", "Fillets and chamfers"), ("cut", "Laser cutting"),
                   ("pierce", "Pierce"), ("bend", "Bend"), ("tool", "Tooling"), ("pour", "Molding and pouring"),
                   ("fettle", "Fettling and cleaning"), ("cycle", "Molding cycle"), ("print", "Printing"),
                   ("supports", "Support removal"))
DEFAULT_TEMPLATE = {"name": "Default", "rate": 60.0, "setup": 80.0,
                    "factors": dict((k, 1.0) for k, _n in OPERATION_NAMES), "prices": {}, "custom": []}
TEMPLATE_EXT = ".fwcost"


# --------------------------------------------------------------------------- templates
def templates_folder():
    path = os.path.join(App.getUserAppDataDir(), "Costing Templates")
    os.makedirs(path, exist_ok=True)
    return path


def template_names():
    """"Default" and the saved templates, A to Z."""
    names = []
    try:
        names = sorted(os.path.splitext(f)[0] for f in os.listdir(templates_folder()) if f.endswith(TEMPLATE_EXT))
    except OSError as _fw_err:
        _fw_log("costing.py:templates", _fw_err)
    return ["Default"] + [n for n in names if n != "Default"]


def load_template(name):
    out = json.loads(json.dumps(DEFAULT_TEMPLATE))
    if name and name != "Default":
        try:
            with open(os.path.join(templates_folder(), name + TEMPLATE_EXT), encoding="utf-8") as f:
                got = json.load(f)
            for k in ("rate", "setup", "prices", "custom"):
                if k in got:
                    out[k] = got[k]
            out["factors"].update(got.get("factors") or {})
        except (OSError, ValueError) as _fw_err:
            _fw_log("costing.py:load_template", _fw_err)
    out["name"] = name or "Default"
    return out


def save_template(t):
    name = (t.get("name") or "").strip()
    if not name or name == "Default" or any(c in name for c in '\\/:*?"<>|'):
        raise ValueError("Give the template a name of its own (not Default, no \\ / : * ? \" < > |).")
    path = os.path.join(templates_folder(), name + TEMPLATE_EXT)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(t, name=name), f, indent=1, sort_keys=True)
    return path


def use_template(s, name):
    """The part's settings with a template picked: its rate, setup and material prices."""
    t = load_template(name)
    s = dict(s)
    s["template"] = "" if t["name"] == "Default" else t["name"]
    s["rate"], s["setup"] = float(t["rate"]), float(t["setup"])
    prices = dict(s.get("prices") or {})
    prices.update(t.get("prices") or {})
    s["prices"] = prices
    if s.get("material") in (t.get("prices") or {}):
        s["price"] = float(t["prices"][s["material"]])
    return s


def _family(name, table, default):
    n = (name or "").lower() + " "
    for key, v in table:
        if key in n:
            return v
    return default


def default_price(name):
    try:
        from . import evaltools
        if name in evaltools.MATERIALS:
            return evaltools.MATERIALS[name][7]
    except Exception as _fw_err:
        _fw_log("costing.py:85", _fw_err)
    return _family(name, PRICE, 2.0)


# --------------------------------------------------------------------------- settings in the part
TEMPLATE_MATERIAL = "Plain Carbon Steel"


def settings(doc):
    out = dict(DEFAULTS)
    try:
        out.update(json.loads(doc.Meta.get(KEY, "") or "{}"))
    except Exception as _fw_err:
        _fw_log("costing.py:95", _fw_err)
    from . import material
    part = material.current(doc)[1] or ""
    if part and part != out.get("part_material", ""):

        out["material"] = part
        out["price"] = 0.0
    out["part_material"] = part
    if not out["material"]:

        out["material"] = TEMPLATE_MATERIAL
    if not out["price"]:
        out["price"] = out["prices"].get(out["material"]) or default_price(out["material"])
    return out


def save(doc, values):
    meta = dict(doc.Meta)
    meta[KEY] = json.dumps(values, sort_keys=True)
    doc.Meta = meta


# --------------------------------------------------------------------------- the part
def body(doc):
    from . import evaltools
    return evaltools._main(doc)


def density(doc, name):
    from . import material
    d, cur = material.current(doc)
    if name and name != cur:
        d = material.known_density(name) or d
    return float(d or material.DEFAULT_DENSITY)


def stock(shape, kind="Block", extra=2.0):
    """(volume mm^3, size text) of the stock the part is cut from."""
    bb = shape.BoundBox
    e = 2 * extra
    if kind == "Cylinder":
        dims = sorted([(bb.XLength, "x"), (bb.YLength, "y"), (bb.ZLength, "z")])
        length = dims[2][0] + e
        d = math.hypot(dims[0][0], dims[1][0]) + e
        return math.pi * d * d / 4 * length, "⌀%.1f x %.1f mm" % (d, length)
    if kind == "Plate":
        dims = sorted([bb.XLength, bb.YLength, bb.ZLength])
        t = _plate_thickness(dims[0])
        return (dims[1] + e) * (dims[2] + e) * t, "%.1f x %.1f x %.1f mm" % (dims[2] + e, dims[1] + e, t)
    x, y, z = bb.XLength + e, bb.YLength + e, bb.ZLength + e
    return x * y * z, "%.1f x %.1f x %.1f mm" % (x, y, z)


def _plate_thickness(t):
    for s in (0.5, 0.8, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 15, 16, 20, 25, 30, 35, 40, 50, 60, 80, 100):
        if s >= t - 1e-6:
            return float(s)
    return math.ceil(t)


def _holes(shape):
    from . import evaltools
    out = {}
    seen = set()
    for f in shape.Faces:
        if not evaltools._is_hole(f):
            continue
        s = f.Surface
        key = (round(s.Center.x, 2), round(s.Center.y, 2), round(s.Center.z, 2), round(s.Radius, 3))
        if key in seen:
            continue
        seen.add(key)
        d = round(2 * s.Radius, 2)
        depth = abs(f.ParameterRange[3] - f.ParameterRange[2])
        n, total = out.get(d, (0, 0.0))
        out[d] = (n + 1, total + depth)
    return out


def _edges_broken(doc):
    """Edges filleted or chamfered (each one a pass of the edge tool)."""
    n = 0
    for o in doc.Objects:
        if o.TypeId not in ("PartDesign::Fillet", "PartDesign::Chamfer"):
            continue
        base = getattr(o, "Base", None)
        subs = base[1] if isinstance(base, tuple) and len(base) > 1 else []
        n += max(1, len(subs) if isinstance(subs, (list, tuple)) else 1)
    return n


def _thickness(shape):
    bb = shape.BoundBox
    return min(bb.XLength, bb.YLength, bb.ZLength)


def operations(doc, obj, s):
    """[(key, operation, quantity, minutes, fixed cost)] for the method, with the template's time factors and the
    template's and the part's custom operations."""
    t = load_template(s.get("template") or "")
    out = []
    for key, name, qty, minutes, fixed in _operations(doc, obj, s):
        f = float(t["factors"].get(key.split("-")[0], 1.0))
        out.append((key, name, qty, minutes * f, fixed * f if key == "tool" else fixed))
    for n, c in enumerate(list(t.get("custom") or [])):
        out.append(("custom-t%d" % n, "%s (template)" % c.get("name", "Custom"), 1, 0.0, _custom_cost(c, s)))
    for n, c in enumerate(list(s.get("custom") or [])):
        out.append(("custom-%d" % n, c.get("name", "Custom"), 1, 0.0, _custom_cost(c, s)))
    return out


def _custom_cost(c, s):
    cost = float(c.get("cost", 0.0))
    return cost / max(1, int(s.get("lot", 1))) if c.get("per") == "lot" else cost


def add_custom(s, name, cost, per="part"):
    s = dict(s)
    s["custom"] = list(s.get("custom") or []) + [{"name": name, "cost": float(cost), "per": "lot" if per == "lot" else "part"}]
    return s


def delete_custom(s, key):
    s = dict(s)
    n = int(key.split("-")[1]) if key.startswith("custom-") and key[7:].isdigit() else None
    custom = list(s.get("custom") or [])
    if n is not None and 0 <= n < len(custom):
        custom.pop(n)
    s["custom"] = custom
    return s


def _operations(doc, obj, s):
    """[(key, operation, quantity, minutes, fixed cost)] for the method."""
    from . import evaltools
    shape = obj.Shape
    vol = shape.Volume / 1000.0                     # cm^3
    area = shape.Area / 100.0                       # cm^2
    method = s["method"]
    ops = [("setup", "Setup (per lot)", 1, 0.0, s["setup"] / max(1, s["lot"]))]
    if method == "Machining":
        stock_mm3, _size = stock(shape, s["stock"], s["extra"])
        removed = max(0.0, stock_mm3 / 1000.0 - vol)
        rate = _family(s["material"], REMOVAL, 8.0)
        ops.append(("load", "Load and unload", 1, 0.5, 0.0))
        ops.append(("remove", "Stock removal (%.1f cm^3)" % removed, 1, removed / rate, 0.0))
        for d, (n, depth) in sorted(_holes(shape).items()):
            ops.append(("drill-%g" % d, "Drill ⌀%g mm" % d, n, n * (0.15 + (depth / n) / 80.0), 0.0))
        planar = sum(f.Area for f in shape.Faces if f.Surface.TypeId == "Part::GeomPlane") / 100.0
        ops.append(("finish", "Finish faces (%.0f cm^2)" % planar, 1, planar * 0.02, 0.0))
        e = _edges_broken(doc)
        if e:
            ops.append(("edges", "Fillets and chamfers", e, e * 0.4, 0.0))
    elif method == "Sheet Metal":
        t = _thickness(shape)
        big = max((f for f in shape.Faces if f.Surface.TypeId == "Part::GeomPlane"), key=lambda f: f.Area, default=None)
        cut = sum(e.Length for e in big.Edges) if big is not None else 0.0
        holes = sum(n for n, _d in _holes(shape).values())
        bends = sum(1 for f in shape.Faces if f.Surface.TypeId == "Part::GeomCylinder" and
                    getattr(f.Surface, "Radius", 99) <= 4 * max(t, 0.5) and not evaltools._is_hole(f)) // 2
        ops.append(("cut", "Laser cutting (%.0f mm)" % cut, 1, cut / 3000.0 * max(1.0, t / 2.0), 0.0))
        if holes:
            ops.append(("pierce", "Pierce", holes, holes * 0.02, 0.0))
        if bends:
            ops.append(("bend", "Bend", bends, bends * 0.3, 0.0))
    elif method == "Casting":
        bb = shape.BoundBox
        tool = 800.0 + bb.XLength * bb.YLength * bb.ZLength / 1000.0 * 1.5
        ops.append(("tool", "Pattern and core box (tooling)", 1, 0.0, tool / max(1, s["quantity"])))
        mass = shape.Volume * 1e-9 * density(doc, s["material"])
        ops.append(("pour", "Molding and pouring", 1, 1.0 + mass * 0.6, 0.0))
        ops.append(("fettle", "Fettling and cleaning", 1, 1.5 + area * 0.01, 0.0))
    elif method == "Plastic":
        bb = shape.BoundBox
        tool = 4000.0 + bb.XLength * bb.YLength * bb.ZLength / 1000.0 * 6.0
        ops.append(("tool", "Injection mold (tooling)", 1, 0.0, tool / max(1, s["quantity"])))
        wall = max(0.5, min(_thickness(shape), 8.0))
        ops.append(("cycle", "Molding cycle", 1, (8.0 + 2.5 * wall * wall) / 60.0, 0.0))
    else:
        ops.append(("print", "Printing (%.1f cm^3)" % vol, 1, vol / 12.0 * 60.0 / 1.0 if vol else 0.0, 0.0))
        ops.append(("supports", "Support removal", 1, 2.0 + area * 0.005, 0.0))
    return ops


def material_kg(doc, obj, s):
    shape = obj.Shape
    dens = density(doc, s["material"])
    if s["method"] == "Machining":
        v = stock(shape, s["stock"], s["extra"])[0]
    elif s["method"] == "Sheet Metal":
        v = shape.Volume * 1.15                    # nesting scrap
    elif s["method"] == "Casting":
        v = shape.Volume * 1.3                     # gates and risers
    elif s["method"] == "Plastic":
        v = shape.Volume * 1.05                    # runners
    else:
        v = shape.Volume * 1.1                     # supports
    return v * 1e-9 * dens


def estimate(doc, obj=None, s=None):
    """{"each", "total", "breakdown": {...}, "rows": [(key, name, qty, minutes, cost, excluded, override)]}."""
    obj = obj or body(doc)
    s = s or settings(doc)
    if obj is None:
        raise RuntimeError("The part has no solid body to cost.")
    rows = []
    manuf = setup = tooling = 0.0
    for key, name, qty, minutes, fixed in operations(doc, obj, s):
        cost = minutes / 60.0 * s["rate"] + fixed
        over = s["overrides"].get(key)
        if over is not None:
            cost = float(over)
        off = key in s["excluded"]
        rows.append((key, name, qty, minutes, cost, off, over is not None))
        if off:
            continue
        if key == "setup":
            setup += cost
        elif key == "tool":
            tooling += cost
        else:
            manuf += cost
    kg = material_kg(doc, obj, s)
    mat = kg * s["price"]
    sub = mat + manuf + setup + tooling
    markup = sub * s["markup"] / 100.0
    each = sub + markup
    out = {"each": each, "total": each * s["quantity"], "kg": kg, "rows": rows,
           "breakdown": {"Material": mat, "Manufacturing": manuf, "Setup": setup, "Tooling": tooling,
                         "Markup": markup},
           "stock": stock(obj.Shape, s["stock"], s["extra"])[1] if s["method"] == "Machining" else ""}
    b = s.get("baseline")
    out["baseline"] = b
    out["change"] = ((each - b) / b * 100.0) if b else None
    return out


# --------------------------------------------------------------------------- assemblies
def _assembly(doc):
    try:
        from . import asmcore
        return asmcore.assembly_of(doc)
    except Exception:
        return None


def assembly_parts(doc, times=1, out=None):
    ""

    from . import asmcore
    out = {} if out is None else out
    asm = _assembly(doc)
    if asm is None:
        return []
    for comp in asmcore.components(asm):
        linked = getattr(comp, "LinkedObject", None)
        d = getattr(linked, "Document", None)
        if d is None or d is doc:
            continue
        n = int(getattr(comp, "ElementCount", 0) or 0) or 1
        if _assembly(d) is not None:
            assembly_parts(d, times * n, out)
        else:
            key = d.Name
            out[key] = (d, out.get(key, (d, 0))[1] + times * n)
    return list(out.values())


def assembly_estimate(doc):
    """{"rows": [(part document, quantity, cost each or None, cost or None, note)], "each": cost per
    assembly, "total": cost of the assemblies asked for}. Each part is costed with its own Costing
    settings (method, material, rates)."""
    rows = []
    each = 0.0
    for d, n in assembly_parts(doc):
        try:
            r = estimate(d)
            rows.append((d, n, r["each"], r["each"] * n, ""))
            each += r["each"] * n
        except Exception as error:
            rows.append((d, n, None, None, str(error)))
    s = settings(doc)
    return {"rows": rows, "each": each, "total": each * s["quantity"], "quantity": s["quantity"]}


def assembly_report(doc, folder=None):
    r = assembly_estimate(doc)
    folder = folder or (os.path.dirname(doc.FileName) if getattr(doc, "FileName", "") else
                        os.path.join(os.path.expanduser("~"), "FreeCAD", "Costing"))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%s-Costing.html" % (doc.Label or doc.Name))
    esc = html.escape
    rows = "".join("<tr><td>%s</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
        esc(d.Label or d.Name), n, "-" if e is None else "%.2f" % e, "-" if c is None else "%.2f" % c, esc(note))
        for d, n, e, c, note in r["rows"])
    text = ["<!doctype html><html><head><meta charset='utf-8'><title>%s</title>" % esc((doc.Label or doc.Name) + " - Costing"),
            "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px}table{border-collapse:collapse;margin:6px 0 18px}"
            "td,th{border:1px solid #bbb;padding:4px 10px;text-align:left}th{background:#e8eef6}</style></head><body>",
            "<h1>%s</h1><p>Costing &middot; %s</p>" % (esc(doc.Label or doc.Name), time.strftime("%Y-%m-%d %H:%M")),
            "<h2>Estimated cost per assembly: %.2f</h2>" % r["each"],
            "<p>%d assemblies: %.2f in all.</p>" % (r["quantity"], r["total"]),
            "<table><tr><th>Part</th><th>Quantity</th><th>Cost per part</th><th>Cost</th><th></th></tr>%s</table>" % rows,
            "<p>Each part is costed with its own Costing settings.</p></body></html>"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(text))
    return path


def report(doc, folder=None):
    s = settings(doc)
    r = estimate(doc, None, s)
    folder = folder or (os.path.dirname(doc.FileName) if getattr(doc, "FileName", "") else
                        os.path.join(os.path.expanduser("~"), "FreeCAD", "Costing"))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%s-Costing.html" % (doc.Label or doc.Name))
    esc = html.escape
    rows = "".join("<tr><td>%s</td><td>%s</td><td>%.2f</td><td>%.2f</td><td>%s</td></tr>" %
                   (esc(n), q, m, c, "excluded" if off else ("override" if ov else "")) for _k, n, q, m, c, off, ov in r["rows"])
    br = "".join("<tr><td>%s</td><td>%.2f</td></tr>" % (esc(k), v) for k, v in r["breakdown"].items())
    text = ["<!doctype html><html><head><meta charset='utf-8'><title>%s</title>" % esc((doc.Label or doc.Name) + " - Costing"),
            "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px}table{border-collapse:collapse;margin:6px 0 18px}"
            "td,th{border:1px solid #bbb;padding:4px 10px;text-align:left}th{background:#e8eef6}</style></head><body>",
            "<h1>%s</h1><p>Costing &middot; %s</p>" % (esc(doc.Label or doc.Name), time.strftime("%Y-%m-%d %H:%M")),
            "<h2>Estimated cost per part: %.2f</h2>" % r["each"],
            "<p>Quantity %d (lots of %d): %.2f in all.%s</p>" % (s["quantity"], s["lot"], r["total"],
                                                              (" Baseline %.2f (%+.1f%%)." % (r["baseline"], r["change"])) if r["baseline"] else ""),
            "<h2>Settings</h2><table><tr><th>Item</th><th>Value</th></tr>",
            "".join("<tr><td>%s</td><td>%s</td></tr>" % (esc(a), esc(str(b))) for a, b in (
                ("Method", s["method"]), ("Material", s["material"]), ("Cost per kg", "%.2f" % s["price"]),
                ("Material used", "%.3f kg" % r["kg"]), ("Stock", r["stock"] or "-"), ("Shop rate per hour", s["rate"]),
                ("Setup cost per lot", s["setup"]), ("Markup / Discount", "%g %%" % s["markup"]))),
            "</table><h2>Cost breakdown</h2><table><tr><th>Item</th><th>Per part</th></tr>%s</table>" % br,
            "<h2>Operations</h2><table><tr><th>Operation</th><th>Quantity</th><th>Minutes</th><th>Cost</th><th></th></tr>%s</table>" % rows,
            "<p>Estimates from plain rules; override any operation with the shop's own figure.</p></body></html>"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(text))
    return path


# =========================================================================== GUI
if Gui is not None:
    class CostingPage(QtWidgets.QWidget):
        def __init__(self, pane=None):
            super().__init__()
            self.setObjectName("SWCostingPage")
            self.doc = App.ActiveDocument
            self.busy = False
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(4, 4, 4, 4)
            form = QtWidgets.QFormLayout()
            self.method = QtWidgets.QComboBox()
            self.method.setObjectName("SWCostingMethod")
            self.method.addItems(METHODS)
            self.material = QtWidgets.QComboBox()
            self.material.setObjectName("SWCostingMaterial")
            self.material.setEditable(True)
            from . import material
            for _f, n, _d in material.COMMON:
                self.material.addItem(n)
            self.price = self._spin("SWCostingPrice", 0, 1e6, 2)
            self.stock = QtWidgets.QComboBox()
            self.stock.setObjectName("SWCostingStock")
            self.stock.addItems(STOCKS)
            self.extra = self._spin("SWCostingExtra", 0, 1000, 2, " mm")
            self.stock_size = QtWidgets.QLabel("")
            self.quantity = QtWidgets.QSpinBox()
            self.quantity.setObjectName("SWCostingQuantity")
            self.quantity.setRange(1, 10 ** 8)
            self.lot = QtWidgets.QSpinBox()
            self.lot.setObjectName("SWCostingLot")
            self.lot.setRange(1, 10 ** 8)
            self.rate = self._spin("SWCostingRate", 0, 1e5, 2)
            self.setup = self._spin("SWCostingSetup", 0, 1e7, 2)
            self.markup = self._spin("SWCostingMarkup", -100, 1000, 1, " %")
            self.template = QtWidgets.QComboBox()
            self.template.setObjectName("SWCostingTemplate")
            self.template.addItems(template_names())
            self.edit_template = QtWidgets.QPushButton("Launch Template Editor")
            self.edit_template.setObjectName("SWCostingTemplateEditor")
            self.edit_template.clicked.connect(self.template_editor)
            form.addRow("Costing template:", self.template)
            form.addRow("", self.edit_template)
            form.addRow("Method:", self.method)
            form.addRow("Material:", self.material)
            form.addRow("Cost per kg:", self.price)
            self.stock_rows = []
            for label, w in (("Stock body:", self.stock), ("Extra each side:", self.extra), ("Stock size:", self.stock_size)):
                form.addRow(label, w)
                self.stock_rows.append((form.labelForField(w), w))
            form.addRow("Total number of parts:", self.quantity)
            form.addRow("Lot size:", self.lot)
            form.addRow("Shop rate per hour:", self.rate)
            form.addRow("Setup cost per lot:", self.setup)
            form.addRow("Markup / Discount:", self.markup)
            lay.addLayout(form)
            self.each = QtWidgets.QLabel("")
            self.each.setObjectName("SWCostingEach")
            self.each.setStyleSheet("QLabel { font-size: 15pt; font-weight: bold; }")
            self.versus = QtWidgets.QLabel("")
            self.versus.setObjectName("SWCostingVersus")
            lay.addWidget(QtWidgets.QLabel("Estimated cost per part:"))
            lay.addWidget(self.each)
            lay.addWidget(self.versus)
            row = QtWidgets.QHBoxLayout()
            self.base = QtWidgets.QPushButton("Set Baseline")
            self.base.setObjectName("SWCostingBaseline")
            self.base.clicked.connect(self.set_baseline)
            self.rep = QtWidgets.QPushButton("Generate Report")
            self.rep.setObjectName("SWCostingReport")
            self.rep.clicked.connect(lambda: self.make_report(True))
            row.addWidget(self.base)
            row.addWidget(self.rep)
            lay.addLayout(row)
            self.breakdown = QtWidgets.QTableWidget(0, 2)
            self.breakdown.setObjectName("SWCostingBreakdown")
            self.breakdown.setHorizontalHeaderLabels(["Cost Breakdown", "Per part"])
            self.breakdown.verticalHeader().hide()
            self.breakdown.horizontalHeader().setStretchLastSection(True)
            self.breakdown.setFixedHeight(140)
            lay.addWidget(self.breakdown)
            self.ops = QtWidgets.QTableWidget(0, 4)
            self.ops.setObjectName("SWCostingOperations")
            self.ops.setHorizontalHeaderLabels(["Operation", "Qty", "Min", "Cost"])
            self.ops.verticalHeader().hide()
            self.ops.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            self.ops.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            self.ops.customContextMenuRequested.connect(self._ops_menu)
            lay.addWidget(self.ops, 1)
            close_row = QtWidgets.QHBoxLayout()
            close_row.addStretch(1)
            c = QtWidgets.QPushButton("Close")
            c.setObjectName("SWCostingClose")
            c.clicked.connect(lambda: close())
            close_row.addWidget(c)
            lay.addLayout(close_row)
            for w in (self.method, self.stock):
                w.currentIndexChanged.connect(lambda *_: self._changed())
            self.template.currentIndexChanged.connect(lambda *_: self._template_changed())
            self.material.currentTextChanged.connect(lambda *_: self._material_changed())
            for w in (self.price, self.extra, self.rate, self.setup, self.markup, self.quantity, self.lot):
                w.valueChanged.connect(lambda *_: self._changed())
            self.refresh()

        def _spin(self, name, lo, hi, dec, suffix=""):
            sb = QtWidgets.QDoubleSpinBox()
            sb.setObjectName(name)
            sb.setRange(lo, hi)
            sb.setDecimals(dec)
            sb.setSuffix(suffix)
            return sb

        def refresh(self):
            if App.ActiveDocument is not None:
                self.doc = App.ActiveDocument
            if self.doc is None:
                return
            s = settings(self.doc)
            self.busy = True
            try:
                self.template.clear()
                self.template.addItems(template_names())
                self.template.setCurrentText(s.get("template") or "Default")
                self.method.setCurrentText(s["method"])
                self.material.setCurrentText(s["material"])
                self.price.setValue(s["price"])
                self.stock.setCurrentText(s["stock"])
                self.extra.setValue(s["extra"])
                self.quantity.setValue(int(s["quantity"]))
                self.lot.setValue(int(s["lot"]))
                self.rate.setValue(s["rate"])
                self.setup.setValue(s["setup"])
                self.markup.setValue(s["markup"])
            finally:
                self.busy = False
            self.show_estimate()

        def values(self):
            s = settings(self.doc)
            prices = dict(s["prices"])
            prices[self.material.currentText()] = self.price.value()
            s.update(method=self.method.currentText(), material=self.material.currentText(), price=self.price.value(),
                     stock=self.stock.currentText(), extra=self.extra.value(), quantity=self.quantity.value(),
                     lot=self.lot.value(), rate=self.rate.value(), setup=self.setup.value(),
                     markup=self.markup.value(), prices=prices)
            return s

        def _template_changed(self):
            if self.busy or self.doc is None:
                return
            save(self.doc, use_template(self.values(), self.template.currentText()))
            self.refresh()

        def template_editor(self):
            dlg = TemplateEditor(self, self.template.currentText())
            _state["editor"] = dlg
            dlg.finished.connect(lambda *_: self.refresh())
            dlg.show()
            return dlg

        def add_custom(self, name=None, cost=None, per=None):
            if name is None:
                name, ok = QtWidgets.QInputDialog.getText(self, "Add Custom Operation", "Operation name:")
                if not ok or not name.strip():
                    return None
                cost, ok = QtWidgets.QInputDialog.getDouble(self, "Add Custom Operation", "Cost:", 0.0, 0, 1e9, 2)
                if not ok:
                    return None
                per, ok = QtWidgets.QInputDialog.getItem(self, "Add Custom Operation", "Cost is:", ["per part", "per lot"], 0, False)
                if not ok:
                    return None
            save(self.doc, add_custom(self.values(), name.strip(), cost, "lot" if "lot" in str(per) else "part"))
            self.show_estimate()
            return True

        def delete_custom(self, key):
            save(self.doc, delete_custom(self.values(), key))
            self.show_estimate()

        def _material_changed(self):
            if self.busy:
                return
            s = settings(self.doc)
            name = self.material.currentText()
            self.busy = True
            self.price.setValue(s["prices"].get(name) or default_price(name))
            self.busy = False
            self._changed()

        def _changed(self):
            if self.busy or self.doc is None:
                return
            save(self.doc, self.values())
            self.show_estimate()

        def show_estimate(self):
            machining = self.method.currentText() == "Machining"
            for label, w in self.stock_rows:
                label.setVisible(machining)
                w.setVisible(machining)
            try:
                r = estimate(self.doc)
            except Exception as error:
                self.each.setText("-")
                self.versus.setText(str(error))
                return None
            self.last = r
            self.each.setText("%.2f" % r["each"])
            self.stock_size.setText(r["stock"])
            if r["baseline"]:
                ch = r["change"]
                self.versus.setText("Baseline %.2f: %+.1f %%" % (r["baseline"], ch))
                self.versus.setStyleSheet("QLabel { color: %s; }" % ("#1e8a2e" if ch <= 0 else "#c0392b"))
            else:
                self.versus.setText("No baseline set")
                self.versus.setStyleSheet("")
            self.breakdown.setRowCount(0)
            for k, v in r["breakdown"].items():
                i = self.breakdown.rowCount()
                self.breakdown.insertRow(i)
                self.breakdown.setItem(i, 0, QtWidgets.QTableWidgetItem(k))
                self.breakdown.setItem(i, 1, QtWidgets.QTableWidgetItem("%.2f" % v))
            self.ops.setRowCount(0)
            for key, name, qty, minutes, cost, off, over in r["rows"]:
                i = self.ops.rowCount()
                self.ops.insertRow(i)
                cells = (name + (" (excluded)" if off else ""), str(qty), "%.2f" % minutes, "%.2f" % cost + (" *" if over else ""))
                for c, text in enumerate(cells):
                    it = QtWidgets.QTableWidgetItem(text)
                    it.setData(QtCore.Qt.UserRole, key)
                    it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                    if off:
                        it.setForeground(QtGui.QColor(150, 150, 150))
                    self.ops.setItem(i, c, it)
            return r

        def set_baseline(self):
            r = estimate(self.doc)
            s = self.values()
            s["baseline"] = r["each"]
            save(self.doc, s)
            self.show_estimate()
            return r["each"]

        def toggle(self, key):
            s = self.values()
            ex = list(s["excluded"])
            if key in ex:
                ex.remove(key)
            else:
                ex.append(key)
            s["excluded"] = ex
            save(self.doc, s)
            self.show_estimate()

        def override(self, key, cost=None):
            s = self.values()
            if cost is None:
                now = next((c for k, _n, _q, _m, c, _o, _v in self.last["rows"] if k == key), 0.0)
                cost, ok = QtWidgets.QInputDialog.getDouble(self, TITLE, "Cost of this operation per part:", now, 0, 1e9, 2)
                if not ok:
                    return
            ov = dict(s["overrides"])
            if cost == "remove":
                ov.pop(key, None)
            else:
                ov[key] = float(cost)
            s["overrides"] = ov
            save(self.doc, s)
            self.show_estimate()

        def _ops_menu(self, pos):
            it = self.ops.itemAt(pos)
            if it is None:
                return
            key = it.data(QtCore.Qt.UserRole)
            s = settings(self.doc)
            menu = QtWidgets.QMenu(self.ops)
            menu.addAction("Include in Costing" if key in s["excluded"] else "Exclude from Costing",
                           lambda: self.toggle(key))
            menu.addAction("Override Cost...", lambda: self.override(key))
            if key in s["overrides"]:
                menu.addAction("Remove Override", lambda: self.override(key, "remove"))
            menu.addSeparator()
            menu.addAction("Add Custom Operation...", lambda: self.add_custom())
            if key.startswith("custom-") and key[7:].isdigit():
                menu.addAction("Delete Custom Operation", lambda: self.delete_custom(key))
            self.ops._fw_menu = menu
            menu.exec_(self.ops.viewport().mapToGlobal(pos))

        def make_report(self, open_it=True):
            try:
                path = report(self.doc)
            except Exception as error:
                QtWidgets.QMessageBox.warning(self, TITLE, str(error))
                return None
            if open_it:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
            App.Console.PrintMessage("Costing report: %s\n" % path)
            return path

    class TemplateEditor(QtWidgets.QDialog):
        ""


        def __init__(self, parent=None, name="Default"):
            super().__init__(parent or Gui.getMainWindow())
            self.setObjectName("SWCostingTemplateEditor")
            self.setWindowTitle("Costing Template Editor")
            self.resize(560, 620)
            t = load_template(name)
            lay = QtWidgets.QVBoxLayout(self)
            form = QtWidgets.QFormLayout()
            self.name = QtWidgets.QLineEdit("" if t["name"] == "Default" else t["name"])
            self.name.setObjectName("SWCTName")
            self.name.setPlaceholderText("Template name")
            self.rate = QtWidgets.QDoubleSpinBox()
            self.rate.setObjectName("SWCTRate")
            self.rate.setRange(0, 1e5)
            self.rate.setValue(float(t["rate"]))
            self.setup = QtWidgets.QDoubleSpinBox()
            self.setup.setObjectName("SWCTSetup")
            self.setup.setRange(0, 1e7)
            self.setup.setValue(float(t["setup"]))
            form.addRow("Template name:", self.name)
            form.addRow("Shop rate per hour:", self.rate)
            form.addRow("Setup cost per lot:", self.setup)
            lay.addLayout(form)
            self.factors = self._table("SWCTFactors", ["Operation", "Time factor"],
                                       [(n, "%g" % float(t["factors"].get(k, 1.0))) for k, n in OPERATION_NAMES], [0])
            self.prices = self._table("SWCTPrices", ["Material", "Cost per kg"],
                                      [(m, "%g" % v) for m, v in sorted((t.get("prices") or {}).items())])
            self.custom = self._table("SWCTCustom", ["Custom operation", "Cost", "Per (part or lot)"],
                                      [(c.get("name", ""), "%g" % float(c.get("cost", 0)), c.get("per", "part"))
                                       for c in t.get("custom") or []])
            for label, table in (("Operations", self.factors), ("Materials", self.prices), ("Custom Operations", self.custom)):
                box = QtWidgets.QGroupBox(label)
                bl = QtWidgets.QVBoxLayout(box)
                bl.addWidget(table)
                if table is not self.factors:
                    row = QtWidgets.QHBoxLayout()
                    add = QtWidgets.QPushButton("Add")
                    add.setObjectName(table.objectName() + "Add")
                    add.clicked.connect(lambda *_a, tb=table: tb.insertRow(tb.rowCount()))
                    rem = QtWidgets.QPushButton("Remove")
                    rem.setObjectName(table.objectName() + "Remove")
                    rem.clicked.connect(lambda *_a, tb=table: tb.removeRow(max(tb.currentRow(), tb.rowCount() - 1))
                                        if tb.rowCount() else None)
                    row.addWidget(add)
                    row.addWidget(rem)
                    row.addStretch(1)
                    bl.addLayout(row)
                lay.addWidget(box, 1)
            self.note = QtWidgets.QLabel()
            self.note.setObjectName("SWCTNote")
            self.note.setWordWrap(True)
            lay.addWidget(self.note)
            row = QtWidgets.QHBoxLayout()
            save_b = QtWidgets.QPushButton("Save")
            save_b.setObjectName("SWCTSave")
            save_b.clicked.connect(self.save)
            close_b = QtWidgets.QPushButton("Close")
            close_b.clicked.connect(self.accept)
            row.addStretch(1)
            row.addWidget(save_b)
            row.addWidget(close_b)
            lay.addLayout(row)

        def _table(self, name, heads, rows, locked=()):
            tb = QtWidgets.QTableWidget(len(rows), len(heads))
            tb.setObjectName(name)
            tb.setHorizontalHeaderLabels(heads)
            tb.verticalHeader().hide()
            tb.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            for r, row in enumerate(rows):
                for c, v in enumerate(row):
                    it = QtWidgets.QTableWidgetItem(str(v))
                    if c in locked:
                        it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                    tb.setItem(r, c, it)
            return tb

        def _cell(self, tb, r, c):
            it = tb.item(r, c)
            return it.text().strip() if it is not None else ""

        def template(self):
            factors = {}
            for r, (k, _n) in enumerate(OPERATION_NAMES):
                try:
                    factors[k] = float(self._cell(self.factors, r, 1).replace(",", "."))
                except ValueError:
                    raise ValueError("The time factor of %s must be a number." % OPERATION_NAMES[r][1])
            prices = {}
            for r in range(self.prices.rowCount()):
                m = self._cell(self.prices, r, 0)
                if m:
                    try:
                        prices[m] = float(self._cell(self.prices, r, 1).replace(",", "."))
                    except ValueError:
                        raise ValueError("The cost per kg of %s must be a number." % m)
            custom = []
            for r in range(self.custom.rowCount()):
                n = self._cell(self.custom, r, 0)
                if n:
                    try:
                        cost = float(self._cell(self.custom, r, 1).replace(",", ".") or 0)
                    except ValueError:
                        raise ValueError("The cost of %s must be a number." % n)
                    custom.append({"name": n, "cost": cost, "per": "lot" if "lot" in self._cell(self.custom, r, 2).lower() else "part"})
            return {"name": self.name.text().strip(), "rate": self.rate.value(), "setup": self.setup.value(),
                    "factors": factors, "prices": prices, "custom": custom}

        def save(self):
            try:
                path = save_template(self.template())
            except ValueError as error:
                self.note.setText(str(error))
                return None
            self.note.setText("Saved: %s" % path)
            return path

    class AssemblyCostingPage(QtWidgets.QWidget):
        """Costing on an assembly: each part it uses with its quantity and cost (from the part's own
        Costing settings), the cost per assembly, the number of assemblies, Open Part, Recalculate,
        Generate Report and Close."""

        def __init__(self, pane=None):
            super().__init__()
            self.setObjectName("SWCostingAssemblyPage")
            self.doc = App.ActiveDocument
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(4, 4, 4, 4)
            lay.addWidget(QtWidgets.QLabel("Parts in this assembly:"))
            self.table = QtWidgets.QTableWidget(0, 4)
            self.table.setObjectName("SWCostingParts")
            self.table.setHorizontalHeaderLabels(["Part", "Qty", "Cost per part", "Cost"])
            self.table.verticalHeader().hide()
            self.table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.table.itemDoubleClicked.connect(lambda *a: self.open_part())
            lay.addWidget(self.table, 1)
            form = QtWidgets.QFormLayout()
            self.quantity = QtWidgets.QSpinBox()
            self.quantity.setObjectName("SWCostingQuantity")
            self.quantity.setRange(1, 10 ** 8)
            form.addRow("Total number of assemblies:", self.quantity)
            lay.addLayout(form)
            lay.addWidget(QtWidgets.QLabel("Estimated cost per assembly:"))
            self.each = QtWidgets.QLabel("")
            self.each.setObjectName("SWCostingEach")
            self.each.setStyleSheet("QLabel { font-size: 15pt; font-weight: bold; }")
            lay.addWidget(self.each)
            self.total = QtWidgets.QLabel("")
            self.total.setObjectName("SWCostingTotal")
            lay.addWidget(self.total)
            row = QtWidgets.QHBoxLayout()
            for text, name, fn in (("Open Part", "SWCostingOpenPart", self.open_part),
                                   ("Recalculate", "SWCostingRecalculate", self.refresh),
                                   ("Generate Report", "SWCostingReport", lambda: self.make_report(True)),
                                   ("Close", "SWCostingClose", lambda: close())):
                b = QtWidgets.QPushButton(text)
                b.setObjectName(name)
                b.clicked.connect(lambda *a, fn=fn: fn())
                row.addWidget(b)
            lay.addLayout(row)
            self.quantity.valueChanged.connect(lambda *a: self._quantity())
            self.last = None
            self.refresh()

        def refresh(self):
            if App.ActiveDocument is not None and _assembly(App.ActiveDocument) is not None:
                self.doc = App.ActiveDocument
            if self.doc is None:
                return None
            self.quantity.blockSignals(True)
            self.quantity.setValue(int(settings(self.doc)["quantity"]))
            self.quantity.blockSignals(False)
            r = assembly_estimate(self.doc)
            self.last = r
            self.table.setRowCount(0)
            for d, n, e, c, note in r["rows"]:
                i = self.table.rowCount()
                self.table.insertRow(i)
                cells = (d.Label or d.Name, str(n), "-" if e is None else "%.2f" % e, note if c is None else "%.2f" % c)
                for col, text in enumerate(cells):
                    it = QtWidgets.QTableWidgetItem(text)
                    it.setData(QtCore.Qt.UserRole, d.Name)
                    self.table.setItem(i, col, it)
            self.each.setText("%.2f" % r["each"])
            self.total.setText("%d assemblies: %.2f" % (r["quantity"], r["total"]))
            return r

        def _quantity(self):
            s = settings(self.doc)
            s["quantity"] = self.quantity.value()
            save(self.doc, s)
            self.refresh()

        def open_part(self):
            """Open Part: the picked part comes to the front with its own Costing."""
            row = self.table.currentRow()
            if row < 0:
                return None
            name = self.table.item(row, 0).data(QtCore.Qt.UserRole)
            try:
                d = App.getDocument(name)
                App.setActiveDocument(d.Name)
                gd = Gui.getDocument(d.Name)
                Gui.ActiveDocument = gd
                views = gd.mdiViewsOfType("Gui::View3DInventor")
                if views:
                    Gui.getMainWindow().setActiveWindow(views[0])
                else:
                    gd.ActiveView        # opens a view
            except Exception as error:
                App.Console.PrintWarning("Costing: %s\n" % error)
                return None
            QtCore.QTimer.singleShot(0, open_costing)
            return d

        def make_report(self, open_it=True):
            try:
                path = assembly_report(self.doc)
            except Exception as error:
                QtWidgets.QMessageBox.warning(self, TITLE, str(error))
                return None
            if open_it:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
            return path

    _state = {"page": None, "dock": None}

    def _page(pane):
        p = AssemblyCostingPage(pane) if _assembly(App.ActiveDocument) is not None else CostingPage(pane)
        _state["page"] = p
        return p

    def open_costing():
        from . import simxpress, taskpane
        page = _state.get("page")
        want = _assembly(App.ActiveDocument) is not None
        if page is not None and simxpress.alive_(page) and isinstance(page, AssemblyCostingPage) != want:
            close()             # a part's page in front of an assembly (or the other way): a new page
        index = simxpress.add_tab(TAB, _page)
        page = taskpane.open_tab(index)
        if page is None:
            dock = _state.get("dock")
            if dock is None or not simxpress.alive_(dock):
                dock = QtWidgets.QDockWidget(TITLE, Gui.getMainWindow())
                dock.setObjectName("SWCostingDock")
                dock.setWidget(_page(None))
                Gui.getMainWindow().addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
                _state["dock"] = dock
            dock.show()
            page = dock.widget()
        else:
            try:
                page.parentWidget().parentWidget().pin.setChecked(True)
            except Exception as _fw_err:
                _fw_log("costing.py:783", _fw_err)
        _state["page"] = page
        return page

    def close():
        from . import simxpress
        simxpress.remove_tab(TAB)
        dock = _state.get("dock")
        if dock is not None and simxpress.alive_(dock):
            dock.close()
            dock.deleteLater()
        _state.update(page=None, dock=None)

    def page():
        from . import simxpress
        p = _state.get("page")
        return p if p is not None and simxpress.alive_(p) else None
