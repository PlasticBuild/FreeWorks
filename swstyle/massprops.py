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

import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths
from .widgets import ui_font

DEFAULT_DENSITY = 1000.0
INCLUDE_HIDDEN = False     # Include hidden bodies/components (the dialog's check box)
DECIMALS = 2               # Options...: decimal places of the report
SCIENTIFIC = False         # Options...: scientific notation
NEGATIVE = False           # Options...: Inertia Tensor, Negative Tensor Notation (massprops-1119)
OVERRIDE_META = "SWMassOverride"


SYSTEMS = {
    "MMGS": ("mm", 1.0, "millimeters", "g", 1.0, "grams"),
    "CGS": ("cm", 10.0, "centimeters", "g", 1.0, "grams"),
    "MKS": ("m", 1000.0, "meters", "kg", 1000.0, "kilograms"),
    "IPS": ("in", 25.4, "inches", "lb", 453.59237, "pounds"),
}
SINGULAR = {"millimeters": "millimeter", "centimeters": "centimeter", "meters": "meter", "inches": "inch",
            "feet": "foot", "grams": "gram", "kilograms": "kilogram", "pounds": "pound"}

LENGTHS = {"Millimeters": ("mm", 1.0, "millimeters"), "Centimeters": ("cm", 10.0, "centimeters"),
           "Meters": ("m", 1000.0, "meters"), "Inches": ("in", 25.4, "inches"), "Feet": ("ft", 304.8, "feet")}
MASSES = {"Grams": ("g", 1.0, "grams"), "Kilograms": ("kg", 1000.0, "kilograms"), "Pounds": ("lb", 453.59237, "pounds")}
VOLUMES = {"millimeters^3": ("mm", 1.0, "millimeter"), "centimeters^3": ("cm", 10.0, "centimeter"),
           "meters^3": ("m", 1000.0, "meter"), "inches^3": ("in", 25.4, "inch"), "feet^3": ("ft", 304.8, "foot")}
SYSTEM_PARTS = {"MMGS": ("Millimeters", "Grams", "millimeters^3"), "CGS": ("Centimeters", "Grams", "centimeters^3"),
                "MKS": ("Meters", "Kilograms", "meters^3"), "IPS": ("Inches", "Pounds", "inches^3")}


def custom_system():
    """SYSTEMS["Custom"] from the Options box's Length and Mass (Use custom settings)."""
    p = paths.params()
    base = SYSTEM_PARTS.get(p.GetString("MassUnits", "") or unit_system(), SYSTEM_PARTS["MMGS"])
    length = LENGTHS.get(p.GetString("MassLength", base[0]), LENGTHS[base[0]])
    mass = MASSES.get(p.GetString("MassMass", base[1]), MASSES[base[1]])
    SYSTEMS["Custom"] = (length[0], length[1], length[2], mass[0], mass[1], mass[2])
    return "Custom"


def per_volume():
    """(singular unit name, size in mm) the density is written per: Options > Per unit volume."""
    p = paths.params()
    if p.GetBool("MassCustomUnits", False) and p.GetString("MassVolume", "") in VOLUMES:
        v = VOLUMES[p.GetString("MassVolume")]
        return v[2], v[1]
    return None


def unit_system():
    ""
    try:
        from . import chrome
        names = chrome.schemas()
        index = chrome.current_schema()
        if 0 <= index < len(names):
            label = chrome.schema_label(*names[index])
            if label in SYSTEMS:
                return label
    except Exception as _fw_err:
        _fw_log("massprops.py:89", _fw_err)
    return "MMGS"


def report_system():
    """The report's unit system: the one Options... set (Use custom settings), else Document Properties > Units >
    Mass/Section Properties (Length, Mass), which is the document's own system until it is set apart."""
    p = paths.params()
    if p.GetBool("MassCustomUnits", False):
        if p.GetString("MassLength", "") or p.GetString("MassMass", ""):
            return custom_system()
        if p.GetString("MassUnits", "") in SYSTEMS:
            return p.GetString("MassUnits", "")
    system = unit_system()
    try:
        from . import unitspage
        length, mass, _ld, _md = unitspage.mass_units(App.ActiveDocument)
        length, mass = length.capitalize(), mass.capitalize()
        if (length, mass) != SYSTEM_PARTS.get(system, ("", ""))[:2] and length in LENGTHS and mass in MASSES:
            l, m = LENGTHS[length], MASSES[mass]
            SYSTEMS["Custom"] = (l[0], l[1], l[2], m[0], m[1], m[2])
            return "Custom"
    except Exception as _fw_err:
        _fw_log("massprops.py:units page", _fw_err)
    return system


def units_page_decimals():
    """Document Properties > Units > Mass/Section Properties decimals (the report's, until Options... sets its own)."""
    try:
        from . import unitspage
        return unitspage.mass_units(App.ActiveDocument)[3]
    except Exception:
        return 2


def _solids_of(obj):
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return []
    try:
        return list(shape.Solids)
    except Exception as _fw_err:
        _fw_log("massprops.py:112", _fw_err)
        return []


def _targets():
    """Selected objects, else every visible top-level body or solid in the document."""
    doc = App.ActiveDocument
    if doc is None:
        return [], "No document"
    picked = []
    for sel in Gui.Selection.getSelectionEx():
        obj = sel.Object
        if obj not in picked and _solids_of(obj):
            picked.append(obj)
    if picked:
        return picked, "Selected items"
    objs = []
    for obj in doc.Objects:
        try:
            if obj.InList and any(_solids_of(p) for p in obj.InList if p.TypeId != "App::Part"):
                continue
            vo = getattr(obj, "ViewObject", None)
            if vo is not None and not vo.Visibility and not INCLUDE_HIDDEN:
                continue
        except Exception:
            continue
        if getattr(obj, "FwWeldBead", "") or type(getattr(obj, "Proxy", None)).__name__ == "WeldBead":
            continue
        if _solids_of(obj):
            objs.append(obj)
    return objs, doc.Label


def _jacobi(m):
    """Eigenvalues and eigenvectors (columns) of a symmetric 3 x 3 matrix."""
    a = [row[:] for row in m]
    v = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]
    for _ in range(50):
        p, q, big = 0, 1, abs(a[0][1])
        for i, j in ((0, 2), (1, 2)):
            if abs(a[i][j]) > big:
                p, q, big = i, j, abs(a[i][j])
        if big < 1e-12 * max(1.0, abs(a[0][0]) + abs(a[1][1]) + abs(a[2][2])):
            break
        theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
        t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
        c = 1.0 / math.sqrt(t * t + 1.0)
        s = t * c
        for k in range(3):
            akp, akq = a[k][p], a[k][q]
            a[k][p], a[k][q] = c * akp - s * akq, s * akp + c * akq
        for k in range(3):
            apk, aqk = a[p][k], a[q][k]
            a[p][k], a[q][k] = c * apk - s * aqk, s * apk + c * aqk
        for k in range(3):
            vkp, vkq = v[k][p], v[k][q]
            v[k][p], v[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    pairs = sorted(((a[i][i], [v[0][i], v[1][i], v[2][i]]) for i in range(3)), key=lambda x: x[0])
    return pairs



BODY_MATERIAL, BODY_DENSITY = "FwBodyMaterial", "FwBodyDensity"


def body_material(obj):
    """(material name, kg/m^3) given to this body itself, or (None, None): the part's material applies."""
    name = getattr(obj, BODY_MATERIAL, "") or ""
    value = float(getattr(obj, BODY_DENSITY, 0.0) or 0.0)
    return (name, value) if name and value > 0 else (None, None)


def set_body_material(obj, name, value=None):
    """Gives one body its own material ("" goes back to the part's material), in one Undo step."""
    if name and value is None:
        from . import material
        value = material.known_density(name)
        if not value:
            raise ValueError("No density known for %s" % name)
    doc = obj.Document
    doc.openTransaction("Edit Material")
    try:
        for prop, kind in ((BODY_MATERIAL, "App::PropertyString"), (BODY_DENSITY, "App::PropertyFloat")):
            if prop not in obj.PropertiesList:
                obj.addProperty(kind, prop, "Material", "The body's own material (Mass Properties)")
        setattr(obj, BODY_MATERIAL, name or "")
        setattr(obj, BODY_DENSITY, float(value or 0.0))
    finally:
        doc.commitTransaction()
    return body_material(obj)


def assigned(objs, density, part_name=None):
    """[(body label, material name, kg/m^3, volume mm^3)] for each measured body."""
    out = []
    for obj in objs:
        name, value = body_material(obj)
        vol = sum(s.Volume for s in _solids_of(obj))
        out.append((obj.Label, name or part_name or "(part density)", value or density, vol))
    return out


def edit_body_material(obj):
    ""

    try:
        from . import materialdlg
        dlg = materialdlg.edit(body=obj)
        if dlg is not None:
            return dlg
    except Exception as error:
        App.Console.PrintLog("FreeCAD: body material dialog: %s\n" % error)
    from . import material
    names = ["(use the part's material)"] + [n for _f, n, _v in material.COMMON]
    now = body_material(obj)[0]
    pick, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Material", "Material of %s:" % obj.Label,
                                              names, names.index(now) if now in names else 0, False)
    if not ok:
        return None
    return set_body_material(obj, "" if pick == names[0] else pick)


# Options > Accuracy level: Lower (faster) ... Higher (slower). The highest level measures the exact
# shapes; the lower ones measure a faceted copy (deflection = this fraction of the solid's size),

ACCURACY_LEVELS = 5
DEFLECTION = {1: 0.03, 2: 0.01, 3: 0.003, 4: 0.0008}
ANGLE = {1: 0.6, 2: 0.3, 3: 0.12, 4: 0.05}     # radians between facets


def accuracy():
    return max(1, min(ACCURACY_LEVELS, paths.params().GetInt("MassAccuracy", ACCURACY_LEVELS)))


def faceted(solid, level=None):
    """The solid itself at the highest accuracy, else a copy made of flat triangles."""
    level = accuracy() if level is None else level
    if level >= ACCURACY_LEVELS:
        return solid
    if all(f.Surface.__class__.__name__ == "Plane" for f in solid.Faces):
        return solid            # flat faces only: the facets are the faces
    try:
        import Part
        import MeshPart
        mesh = MeshPart.meshFromShape(Shape=solid, LinearDeflection=max(1e-4, solid.BoundBox.DiagonalLength * DEFLECTION[level]),
                                      AngularDeflection=ANGLE[level], Relative=False)
        points, triangles = mesh.Topology
        faces = []
        for a, b, c in triangles:
            try:
                faces.append(Part.Face(Part.makePolygon([points[a], points[b], points[c], points[a]])))
            except Exception:
                continue
        shell = Part.makeShell(faces)
        out = Part.makeSolid(shell)
        if out.Volume < 0:
            out.reverse()
        return out if abs(out.Volume) > 0 else solid
    except Exception:
        return solid


def compute(objs, density):
    """Totals in g, mm, mm^2, mm^3 and g*mm^2 for the solids of objs. A body with its own material
    (body_material) weighs with its own density; the rest use density (kg/m^3)."""
    pairs = []
    for obj in objs:
        own = body_material(obj)[1] if obj is not None else None
        pairs += [(faceted(s), (own or density) * 1e-6) for s in _solids_of(obj)]
    if not pairs:
        return None
    solids = [s for s, _ in pairs]
    volume = sum(s.Volume for s in solids)
    area = sum(s.Area for s in solids)
    if volume <= 0:
        return None
    mass = sum(s.Volume * g for s, g in pairs)
    cx = cy = cz = 0.0
    for s, g in pairs:
        c = s.CenterOfMass
        w = s.Volume * g
        cx += c.x * w
        cy += c.y * w
        cz += c.z * w
    cx, cy, cz = cx / mass, cy / mass, cz / mass
    inertia = [[0.0] * 3 for _ in range(3)]
    for s, g in pairs:
        m = s.MatrixOfInertia
        local = [[m.A11, m.A12, m.A13], [m.A21, m.A22, m.A23], [m.A31, m.A32, m.A33]]
        c = s.CenterOfMass
        d = (c.x - cx, c.y - cy, c.z - cz)
        d2 = d[0] ** 2 + d[1] ** 2 + d[2] ** 2
        for i in range(3):
            for j in range(3):
                inertia[i][j] += (local[i][j] + s.Volume * ((d2 if i == j else 0.0) - d[i] * d[j])) * g
    origin = [[0.0] * 3 for _ in range(3)]
    c = (cx, cy, cz)
    c2 = cx * cx + cy * cy + cz * cz
    for i in range(3):
        for j in range(3):
            origin[i][j] = inertia[i][j] + mass * ((c2 if i == j else 0.0) - c[i] * c[j])
    return {"solids": len(solids), "volume": volume, "area": area, "mass": mass, "center": c,
            "inertia": inertia, "origin": origin, "principal": _jacobi(inertia)}


def _matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _transpose(a):
    return [[a[j][i] for j in range(3)] for i in range(3)]


def _at_point(inertia, mass, c):
    """Inertia about a point at -c from the centre of mass (parallel axis theorem, OCC signs)."""
    c2 = c[0] ** 2 + c[1] ** 2 + c[2] ** 2
    return [[inertia[i][j] + mass * ((c2 if i == j else 0.0) - c[i] * c[j]) for j in range(3)] for i in range(3)]


def overrides(doc, config=None):
    """The part's Override Mass Properties: {"mass": g, "center": [x, y, z] mm,
    "inertia": [[Lxx, Lxy, Lxz], ...] g*mm^2 positive notation}; missing keys are not overridden."""
    import json
    if doc is None:
        return {}
    meta = doc.Meta or {}
    key = _override_key(doc, config)
    try:
        out = json.loads(meta.get(key, meta.get(OVERRIDE_META, "")) or "{}")
    except Exception:
        return {}

    # follows when that coordinate system moves (mpcs-fix01); the global point is the fallback when it is gone
    # the coordinate system by its object name (a rename keeps it, mpcs-fix02), by label for files saved before
    local, label = out.get("center_local"), out.get("center_frame")
    if local and (label or out.get("center_frame_name")):
        place = _frame_placement(doc, out.get("center_frame_name"), label)
        if place is not None:
            p = place.multVec(App.Vector(*[float(x) for x in local]))
            out["center"] = [p.x, p.y, p.z]
    return out


def _override_key(doc, config=None):
    ""
    from . import fileprops
    return OVERRIDE_META + "@" + (config or fileprops.active_configuration(doc))


def set_overrides(doc, values, configs=None):
    """configs: the configurations it applies to (Apply changes to); None: the one shown."""
    import json
    meta = dict(doc.Meta or {})
    keys = [_override_key(doc, c) for c in configs] if configs else [_override_key(doc)]
    legacy = meta.pop(OVERRIDE_META, None)
    if legacy is not None:                   # an older file's one set: kept by every configuration
        try:
            from . import configmanager
            t = configmanager.table(doc)
            for name in (t.names() if t is not None else []):
                meta.setdefault(OVERRIDE_META + "@" + name, legacy)
        except Exception as _fw_err:
            App.Console.PrintLog("FreeCAD: Override Mass Properties: %s\n" % _fw_err)
    for key in keys:
        if values:
            meta[key] = json.dumps(values)
        else:
            meta.pop(key, None)
    doc.Meta = meta
    # rgdeep: the part's Center of Mass point takes the overridden centre of mass (and goes back when cleared)
    for o in doc.Objects:
        if type(getattr(o, "Proxy", None)).__name__ == "CenterOfMass":
            try:
                o.touch()
            except Exception as _fw_err:
                _fw_log("massprops.py:com-touch", _fw_err)


def adjust(r, over=None, frame=None):
    ""


    if r is None:
        return None
    r = dict(r)
    over = over or {}
    marks = set()
    if over.get("mass"):
        k = float(over["mass"]) / r["mass"]
        r["mass"] = float(over["mass"])
        r["inertia"] = [[x * k for x in row] for row in r["inertia"]]
        marks.add("mass")
    if over.get("center"):
        r["center"] = tuple(float(x) for x in over["center"])
        marks.add("center")
    if over.get("inertia"):
        m = over["inertia"]
        r["inertia"] = [[float(m[i][j]) if i == j else -float(m[i][j]) for j in range(3)] for i in range(3)]
        marks.add("inertia")
    c = r["center"]
    inertia = r["inertia"]
    if frame is not None:
        inv = frame.inverse()
        p = inv.multVec(App.Vector(*c))
        c = (p.x, p.y, p.z)
        rot = frame.Rotation
        axes = [rot.multVec(App.Vector(*v)) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
        R = [[axes[j][i] for j in range(3)] for i in range(3)]     # columns: the frame's axes
        inertia = _matmul(_transpose(R), _matmul(inertia, R))
    r["center"] = c
    r["inertia"] = inertia
    r["origin"] = _at_point(inertia, r["mass"], c)
    r["principal"] = _jacobi(inertia)
    r["marks"] = marks
    return r


def _is_frame(o):
    return o.TypeId in ("PartDesign::CoordinateSystem", "App::LocalCoordinateSystem") or \
        getattr(getattr(o, "Proxy", None), "Type", None) == "SWStyle::CoordinateSystem"


def _frame_object(doc, name=None, label=None):
    """The coordinate system an override was typed in: by its Name, else (older files) by its Label."""
    if doc is None:
        return None
    o = doc.getObject(name) if name else None
    if o is not None and _is_frame(o):
        return o
    if name:
        return None         # that system was deleted: another one taking its label is not it
    for o in doc.Objects:
        if o.Label == label and _is_frame(o):
            return o
    return None


def _frame_placement(doc, name=None, label=None):
    o = _frame_object(doc, name, label)
    if o is None:
        return None
    try:
        return o.getGlobalPlacement()
    except Exception:
        return o.Placement


def frames(doc):
    """[(label, global Placement)] of the coordinate systems 'Report coordinate values relative to'
    offers after -- default --."""
    out = []
    for o in (doc.Objects if doc is not None else []):
        if o.TypeId in ("PartDesign::CoordinateSystem", "App::LocalCoordinateSystem") or \
                getattr(getattr(o, "Proxy", None), "Type", None) == "SWStyle::CoordinateSystem":
            try:
                out.append((o.Label, o.getGlobalPlacement()))
            except Exception:
                out.append((o.Label, o.Placement))
    return out


def _notation():
    return "negative" if NEGATIVE else "positive"


def _positive(tensor):
    ""

    if NEGATIVE:
        return [[tensor[i][j] for j in range(3)] for i in range(3)]
    return [[tensor[i][j] if i == j else -tensor[i][j] for j in range(3)] for i in range(3)]


def _fmt(value):
    ""
    out = _fmt_raw(value)
    if out.startswith("-") and not any(c in "123456789" for c in out.split("e")[0]):
        out = out[1:]
    return out


def _fmt_raw(value):
    if SCIENTIFIC:
        return "%.*e" % (DECIMALS, value)
    try:
        # Document Properties > Units: with "Only apply rounding method to dimensions" off, the
        # Decimal rounding method rounds the mass properties too
        from . import optionspages, docstyle
        doc = App.ActiveDocument
        if not optionspages.doc_value(doc, "Units", "Only apply rounding method to dimensions", True):
            return docstyle.rounded(value, DECIMALS, docstyle.rounding(doc))
    except Exception as _fw_err:
        _fw_log("massprops.py:418", _fw_err)
    return "%.*f" % (DECIMALS, value)


def _dens(value):
    ""

    return _fmt(value)


def weld_beads(doc):
    """The weld bead solids of a part (Weld Bead features) or an assembly (assembly Weld Beads)."""
    out = []
    for o in (doc.Objects if doc is not None else []):
        shape = None
        try:
            from . import weweld
            if weweld.is_weld_bead(o):
                shape = o.Shape
        except Exception as _fw_err:
            _fw_log("massprops.py:437", _fw_err)
        if shape is None and hasattr(o, "FwWeldBead") and getattr(o, "FwWeldBead", ""):
            shape = o.Shape
        if shape is not None and not shape.isNull():
            out += list(shape.Solids)
    return out


def bead_weight(doc):
    """Document Properties > Weldments > Weld bead: None for mass from the bead volume, or the mass per unit
    length in kg/m."""
    try:
        from . import optionspages
        how = str(optionspages.doc_value(doc, "Weldments", "Bead weight", "Mass from bead volume"))
        if how not in ("Mass per unit length", "Length"):
            return None
        return max(0.0, float(optionspages.doc_value(doc, "Weldments", "Mass per unit length (kg/m)", 0.25)))
    except Exception:
        return None


def weld_mass(doc, density):
    """Weld bead mass in grams: bead volume x density (kg/m^3), or bead length x the document's mass per
    unit length (Bead weight)."""
    beads = weld_beads(doc)
    per = bead_weight(doc)
    if per is not None:
        from . import weweld
        return sum(weweld._bead_length(s) for s in beads) * per          # mm x kg/m = g
    return sum(s.Volume for s in beads) * density * 1e-6


def _configuration(objs):
    ""
    try:
        from . import fileprops
        return fileprops.active_configuration(objs[0].Document) or "Default"
    except Exception:
        return "Default"


def report(objs, label, density, system=None, over=None, frame=None, frame_label=None, weld=None, part_name=None):
    result = adjust(compute(objs, density), over, frame)
    if result is None:
        return "There are no solid bodies to measure.\n\nSelect a body or make one visible, then press Recalculate."
    system = system or report_system()
    _, mm, length, _, g, mass = SYSTEMS[system]
    one_length, one_mass = SINGULAR[length], SINGULAR[mass]
    vol_name, vol_mm = per_volume() or (one_length, mm)
    r = result
    lines = []
    lines.append("Mass properties of %s" % label)
    lines.append("     Configuration: %s" % _configuration(objs))
    lines.append("     Coordinate system: %s" % (frame_label or "-- default --"))
    lines.append("")
    mats = assigned(objs, density, part_name)
    if len(set((m[1], m[2]) for m in mats)) > 1:

        lines.append("Assigned materials:")
        for body, name, value, vol in mats:
            lines.append("\t%s: %s, density = %s %s per cubic %s, mass = %s %s"
                         % (body, name, _dens(value * 1e-6 * vol_mm ** 3 / g), mass, vol_name,
                            _fmt(vol * value * 1e-6 / g), mass))
    else:
        lines.append("Density = %s %s per cubic %s" % (_dens((mats[0][2] if mats else density) * 1e-6 * vol_mm ** 3 / g),
                                                       mass, vol_name))
    lines.append("")
    marks = r.get("marks", set())
    tag = lambda key: " (user overridden)" if key in marks else ""
    lines.append("Mass = %s %s%s" % (_fmt(r["mass"] / g), mass, tag("mass")))
    lines.append("")
    if weld is not None:
        lines.append("Weld bead mass = %s %s" % (_fmt(weld / g), mass))
        lines.append("")
    lines.append("Volume = %s cubic %s" % (_fmt(r["volume"] / mm ** 3), length))
    lines.append("")
    lines.append("Surface area = %s square %s" % (_fmt(r["area"] / mm ** 2), length))
    lines.append("")
    lines.append("Center of mass: ( %s )%s" % (length, tag("center")))
    for axis, value in zip("XYZ", r["center"]):
        lines.append("\t%s = %s" % (axis, _fmt(value / mm)))
    lines.append("")
    inertia_unit = "%s *  square %s" % (mass, length)
    scale = 1.0 / (g * mm * mm)
    lines.append("Principal axes of inertia and principal moments of inertia: ( %s )" % inertia_unit)
    lines.append("Taken at the center of mass.")
    for name, (moment, axis) in zip(("Ix", "Iy", "Iz"), r["principal"]):
        lines.append("\t %s = (%s, %s, %s)   \tP%s = %s" % (name, "%.*f" % (DECIMALS, axis[0]), "%.*f" % (DECIMALS, axis[1]),
                                                         "%.*f" % (DECIMALS, axis[2]), name[1], _fmt(moment * scale)))
    lines.append("")
    lines.append("Moments of inertia: ( %s )%s" % (inertia_unit, tag("inertia")))
    lines.append("Taken at the center of mass and aligned with the output coordinate system. (Using %s tensor notation.)" % _notation())
    names = "xyz"
    m = _positive(r["inertia"])
    for i in range(3):
        lines.append("\t" + "\t".join("L%s%s = %s" % (names[i], names[j], _fmt(m[i][j] * scale)) for j in range(3)))
    lines.append("")
    lines.append("Moments of inertia: ( %s )" % inertia_unit)
    lines.append("Taken at the output coordinate system. (Using %s tensor notation.)" % _notation())
    m = _positive(r["origin"])
    for i in range(3):
        lines.append("\t" + "\t".join("I%s%s = %s" % (names[i], names[j], _fmt(m[i][j] * scale)) for j in range(3)))
    if r["solids"] > 1:
        lines.append("")
        lines.append("%d solid bodies." % r["solids"])
    return "\n".join(lines)


class OptionsBox(QtWidgets.QDialog):
    ""


    def __init__(self, parent=None, axis=True):
        super().__init__(parent)
        self.setObjectName("SWMassOptions")
        self.setWindowTitle("Mass/Section Property Options")
        p = paths.params()
        layout = QtWidgets.QVBoxLayout(self)
        box = QtWidgets.QGroupBox("Units", self)
        form = QtWidgets.QFormLayout(box)
        self.scientific = QtWidgets.QCheckBox("Scientific Notation", box)
        self.scientific.setObjectName("SWMassScientific")
        self.scientific.setChecked(p.GetBool("MassScientific", False))
        form.addRow(self.scientific)
        self.document = QtWidgets.QRadioButton("Use document settings", box)
        self.custom = QtWidgets.QRadioButton("Use custom settings", box)
        (self.custom if p.GetBool("MassCustomUnits", False) else self.document).setChecked(True)
        form.addRow(self.document)
        form.addRow(self.custom)
        base = SYSTEM_PARTS.get(p.GetString("MassUnits", "") or unit_system(), SYSTEM_PARTS["MMGS"])
        self._system = p.GetString("MassUnits", "") or unit_system()
        self.length = QtWidgets.QComboBox(box)
        self.length.setObjectName("SWMassLength")
        self.length.addItems(list(LENGTHS))
        self.length.setCurrentText(p.GetString("MassLength", "") or base[0])
        form.addRow("Length:", self.length)
        self.decimals = QtWidgets.QSpinBox(box)
        self.decimals.setRange(0, 8)
        self.decimals.setValue(p.GetInt("MassDecimals", 2))
        form.addRow("Decimal places:", self.decimals)
        self.mass = QtWidgets.QComboBox(box)
        self.mass.setObjectName("SWMassMass")
        self.mass.addItems(list(MASSES))
        self.mass.setCurrentText(p.GetString("MassMass", "") or base[1])
        form.addRow("Mass:", self.mass)
        self.volume = QtWidgets.QComboBox(box)
        self.volume.setObjectName("SWMassVolume")
        self.volume.addItems(list(VOLUMES))
        self.volume.setCurrentText(p.GetString("MassVolume", "") or base[2])
        form.addRow("Per unit volume:", self.volume)
        layout.addWidget(box)
        # Material Properties: the part's material gives the density (shown, nothing to edit); with no material the

        try:
            from . import material
            value, name = material.current(App.ActiveDocument)
        except Exception:
            value, name = None, None
        mat = QtWidgets.QGroupBox("Material Properties", self)
        ml = QtWidgets.QFormLayout(mat)
        system = report_system()
        _, mm, _length, unit, g, _mass = SYSTEMS[system]
        self._factor = 1e-6 * mm ** 3 / g
        self.density = None
        if value:
            ml.addRow("Density:", QtWidgets.QLabel("%s %s/%s\u00b3 (%s)" % (_dens(value * self._factor), unit, SYSTEMS[system][0], name)))
        else:
            self.density = QtWidgets.QDoubleSpinBox(mat)
            self.density.setObjectName("SWMassDensity")
            self.density.setDecimals(6 if self._factor < 1e-3 else 3)
            self.density.setRange(1e-6, 100000.0)
            self.density.setSuffix(" %s/%s\u00b3" % (unit, SYSTEMS[system][0]))
            self.density.setValue(p.GetFloat("Density", DEFAULT_DENSITY) * self._factor)
            self.density.setToolTip("No material: right-click Material in the tree > Edit Material")
            ml.addRow("Density:", self.density)
        layout.addWidget(mat)
        acc = QtWidgets.QGroupBox("Accuracy level", self)
        al = QtWidgets.QGridLayout(acc)
        self.accuracy = QtWidgets.QSlider(QtCore.Qt.Horizontal, acc)
        self.accuracy.setObjectName("SWMassAccuracy")
        self.accuracy.setRange(1, ACCURACY_LEVELS)
        self.accuracy.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.accuracy.setValue(accuracy())
        al.addWidget(self.accuracy, 0, 0, 1, 2)
        al.addWidget(QtWidgets.QLabel("Lower (faster)", acc), 1, 0)
        higher = QtWidgets.QLabel("Higher (slower)", acc)
        higher.setAlignment(QtCore.Qt.AlignRight)
        al.addWidget(higher, 1, 1)
        layout.addWidget(acc)
        tens = QtWidgets.QGroupBox("Inertia Tensor (Crossproduct Convention)", self)
        tl = QtWidgets.QVBoxLayout(tens)
        self.positive = QtWidgets.QRadioButton("Positive Tensor Notation", tens)
        self.positive.setObjectName("SWMassPositive")
        self.negative = QtWidgets.QRadioButton("Negative Tensor Notation", tens)
        self.negative.setObjectName("SWMassNegative")
        (self.negative if p.GetBool("MassNegativeTensor", False) else self.positive).setChecked(True)
        tl.addWidget(self.positive)
        tl.addWidget(self.negative)
        layout.addWidget(tens)
        self.axis = None
        if axis:
            self.axis = QtWidgets.QCheckBox("Show output coordinate system in corner of window", self)
            self.axis.setObjectName("SWMassShowAxis")
            self.axis.setChecked(p.GetBool("MassShowAxis", True))
            layout.addWidget(self.axis)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
                                             | QtWidgets.QDialogButtonBox.Help)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.helpRequested.connect(self._help)
        layout.addWidget(buttons)
        # no greyed controls (Ati's rule): the custom settings stay live, and changing one of them
        # picks Use custom settings, as the user means
        for sig in (self.length.currentTextChanged, self.mass.currentTextChanged,
                    self.volume.currentTextChanged, self.decimals.valueChanged, self.scientific.toggled):
            sig.connect(self._to_custom)

    def _to_custom(self, *args):
        self.custom.setChecked(True)

    def _help(self):
        try:
            from . import helpguide
            if helpguide.show_topic("mass properties") is None:
                helpguide.show("04-features.html")
        except Exception as error:
            App.Console.PrintWarning("Help: %s\n" % error)

    def accept(self):
        p = paths.params()
        p.SetBool("MassCustomUnits", self.custom.isChecked())
        p.SetString("MassUnits", self._system)
        p.SetInt("MassDecimals", self.decimals.value())
        p.SetBool("MassScientific", self.scientific.isChecked())
        p.SetString("MassLength", self.length.currentText())
        p.SetString("MassMass", self.mass.currentText())
        p.SetString("MassVolume", self.volume.currentText())
        p.SetInt("MassAccuracy", self.accuracy.value())
        p.SetBool("MassNegativeTensor", self.negative.isChecked())
        if self.axis is not None:
            p.SetBool("MassShowAxis", self.axis.isChecked())
        if self.density is not None:
            p.SetFloat("Density", float(self.density.value() / self._factor))
        super().accept()


class OverrideBox(QtWidgets.QDialog):
    ""


    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setObjectName("SWMassOverride")
        self.setWindowTitle("Override Mass Properties")
        old = overrides(doc)
        _, self._mm, length, unit, self._g, _mass = SYSTEMS[report_system()]
        self._places = dict([("Part coordinate system (default)", None)] + frames(doc))
        fine = 4 if self._mm == 1.0 and self._g == 1.0 else 8
        layout = QtWidgets.QVBoxLayout(self)

        def spin(value=0.0, decimals=fine):
            b = QtWidgets.QDoubleSpinBox(self)
            b.setRange(-1e12, 1e12)
            b.setDecimals(decimals)
            b.setValue(float(value))
            return b

        self.mass_on = QtWidgets.QCheckBox("Override mass:", self)
        self.mass_on.setChecked(bool(old.get("mass")))
        self.mass = spin(old.get("mass", 0.0) / self._g)
        self.mass.setSuffix(" " + unit)
        self.mass.setRange(0.0, 1e12)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.mass_on)
        row.addWidget(self.mass)
        layout.addLayout(row)
        self.center_on = QtWidgets.QCheckBox("Override center of mass (%s):" % length, self)
        self.center_on.setChecked(bool(old.get("center")))
        layout.addWidget(self.center_on)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("As defined in:"))
        self.center_frame = QtWidgets.QComboBox(self)
        self.center_frame.setObjectName("SWMassOverrideFrame")
        self.center_frame.addItems(list(self._places))
        self._frame_names = dict((o.Label, o.Name) for o in (doc.Objects if doc is not None else []) if _is_frame(o))
        held = _frame_object(doc, old.get("center_frame_name"), old.get("center_frame")) if old.get("center_local") \
            or old.get("center_frame_name") else None
        if held is not None and held.Label in self._places:
            self.center_frame.setCurrentText(held.Label)       # its label now, after a rename
        elif not old.get("center_frame_name") and old.get("center_frame") in self._places:
            self.center_frame.setCurrentText(old["center_frame"])
        row.addWidget(self.center_frame, 1)
        layout.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        c = old.get("center") or [0.0, 0.0, 0.0]
        place = self._places.get(self.center_frame.currentText())
        if place is not None and old.get("center"):
            p = place.inverse().multVec(App.Vector(*c))
            c = [p.x, p.y, p.z]
        self.center = []
        for axis, v in zip("XYZ", c):
            row.addWidget(QtWidgets.QLabel(axis + ":"))
            b = spin(v / self._mm)
            self.center.append(b)
            row.addWidget(b)
        layout.addLayout(row)
        self.inertia_on = QtWidgets.QCheckBox("Override moments of inertia (%s*%s^2, at the center of mass):"
                                              % (unit, SYSTEMS[report_system()][0]), self)
        self.inertia_on.setChecked(bool(old.get("inertia")))
        layout.addWidget(self.inertia_on)
        grid = QtWidgets.QGridLayout()
        m = old.get("inertia") or [[0.0] * 3 for _ in range(3)]
        k = self._g * self._mm * self._mm
        self.inertia = [[None] * 3 for _ in range(3)]
        for i, a in enumerate("xyz"):
            for j, b in enumerate("xyz"):
                if j < i:
                    continue
                grid.addWidget(QtWidgets.QLabel("L%s%s:" % (a, b)), i, 2 * j)
                box = spin(m[i][j] / k)
                self.inertia[i][j] = box
                grid.addWidget(box, i, 2 * j + 1)
        layout.addLayout(grid)
        self._scope_group(layout)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        # no greyed boxes (Ati's rule): typing a value ticks its Override switch
        for box, boxes in ((self.mass_on, [self.mass]), (self.center_on, self.center),
                           (self.inertia_on, [b for r in self.inertia for b in r if b is not None])):
            for b in boxes:
                b.valueChanged.connect(lambda _v, on=box: on.setChecked(True))
        self.center_frame.activated.connect(lambda *a: self.center_on.setChecked(True))

    def _scope_group(self, layout):
        ""


        self.scope = None
        names, active = [], None
        try:
            from . import configmanager
            t = configmanager.table(self.doc) if self.doc is not None else None
            if t is not None:
                names, active = list(t.names()), t.active()
        except Exception as _fw_err:
            App.Console.PrintLog("FreeCAD: Override Mass Properties configurations: %s\n" % _fw_err)
        if len(names) < 2:
            return
        box = QtWidgets.QGroupBox("Apply changes to:", self)
        box.setObjectName("SWMassOverrideScope")
        lay = QtWidgets.QVBoxLayout(box)
        self.scope = {}
        for key, text in (("this", "This configuration"), ("all", "All configurations"), ("specify", "Specify configurations")):
            r = QtWidgets.QRadioButton(text, box)
            r.setObjectName("SWMassOverrideScope_" + key)
            self.scope[key] = r
            lay.addWidget(r)
        self.scope["this"].setChecked(True)
        self.configs = QtWidgets.QListWidget(box)
        self.configs.setObjectName("SWMassOverrideConfigs")
        self.configs.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.configs.addItems(names)
        self._active = active
        self.configs.setMaximumHeight(90)
        lay.addWidget(self.configs)
        row = QtWidgets.QHBoxLayout()
        self.all_button = QtWidgets.QPushButton("All", box)
        self.reset_button = QtWidgets.QPushButton("Reset", box)
        self.all_button.clicked.connect(self.configs.selectAll)
        self.reset_button.clicked.connect(self._reset_configs)
        row.addWidget(self.all_button)
        row.addWidget(self.reset_button)
        row.addStretch(1)
        lay.addLayout(row)
        layout.addWidget(box)
        for r in self.scope.values():
            r.toggled.connect(lambda _on: self._scope_shown())
        self.configs.itemSelectionChanged.connect(self._picked_configs)
        self._reset_configs()
        self._scope_shown()

    def _reset_configs(self):
        self.configs.blockSignals(True)
        self.configs.clearSelection()
        for i in range(self.configs.count()):
            if self.configs.item(i).text() == self._active:
                self.configs.item(i).setSelected(True)
        self.configs.blockSignals(False)

    def _picked_configs(self):
        if not self.scope["specify"].isChecked():       # picking in the list chooses Specify configurations
            self.scope["specify"].setChecked(True)

    def _scope_shown(self):
        specify = self.scope["specify"].isChecked()
        self.all_button.setVisible(specify)
        self.reset_button.setVisible(specify)
        if self.scope["all"].isChecked():
            self.configs.blockSignals(True)
            self.configs.selectAll()
            self.configs.blockSignals(False)
        elif self.scope["this"].isChecked():
            self._reset_configs()

    def targets(self):
        """The configurations OK applies the overrides to (None: the one shown)."""
        if not self.scope or self.scope["this"].isChecked():
            return None
        if self.scope["all"].isChecked():
            return [self.configs.item(i).text() for i in range(self.configs.count())]
        return [i.text() for i in self.configs.selectedItems()] or None

    def values(self):
        out = {}
        if self.mass_on.isChecked() and self.mass.value() > 0:
            out["mass"] = self.mass.value() * self._g
        if self.center_on.isChecked():
            c = App.Vector(*[b.value() * self._mm for b in self.center])
            place = self._places.get(self.center_frame.currentText())
            if place is not None:
                out["center_local"] = [c.x, c.y, c.z]
                c = place.multVec(c)
                out["center_frame"] = self.center_frame.currentText()
                if self.center_frame.currentText() in self._frame_names:
                    out["center_frame_name"] = self._frame_names[self.center_frame.currentText()]
            out["center"] = [c.x, c.y, c.z]
        if self.inertia_on.isChecked():
            k = self._g * self._mm * self._mm
            m = [[0.0] * 3 for _ in range(3)]
            for i in range(3):
                for j in range(i, 3):
                    m[i][j] = m[j][i] = self.inertia[i][j].value() * k
            out["inertia"] = m
        return out

    def accept(self):
        doc = self.doc
        if doc is not None and (self.values() != overrides(doc) or self.targets()):
            doc.openTransaction("Override Mass Properties")
            try:
                # its own Undo step: the values live in the file's Meta, which follows the Undo list
                # (displaystates) once the step records a change; adding and removing a mark leaves nothing behind
                doc.removeObject(doc.addObject("App::DocumentObject", "FwMassOverrideMark").Name)
                set_overrides(doc, self.values(), self.targets())
            finally:
                doc.commitTransaction()
        super().accept()


# ---- the principal axes triad and centre of mass in the graphics area while the box is open
AXIS_COLOURS = ((0.85, 0.1, 0.1), (0.1, 0.65, 0.1), (0.15, 0.3, 0.9))
COM_COLOUR = (0.75, 0.2, 0.75)


class Triad:
    ""


    def __init__(self):
        self.view = None
        self.root = None
        self.node = None
        self.shown = None          # (centre, [axis vectors], size) for checks

    def show(self, result, view=None):
        self.hide()
        if result is None:
            return
        try:
            from pivy import coin
            view = view or Gui.ActiveDocument.ActiveView
            root = view.getViewer().getSoRenderManager().getSceneGraph()
        except Exception:
            return
        c = App.Vector(*result["center"])
        size = 0.0
        try:
            size = max(s.BoundBox.DiagonalLength for s in result.get("shapes", [])) if result.get("shapes") else 0.0
        except Exception:
            size = 0.0
        size = 0.35 * (size or (result["volume"] ** (1.0 / 3.0) * 1.7))
        sep = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        sep.addChild(pick)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        sep.addChild(light)
        depth = coin.SoDepthBuffer()
        depth.test = False
        sep.addChild(depth)
        axes = []
        for (moment, axis), colour, name in zip(result["principal"], AXIS_COLOURS, ("Ix", "Iy", "Iz")):
            a = App.Vector(*axis)
            if a.Length < 1e-12:
                continue
            a.normalize()
            axes.append(a)
            tip = c + a * size
            part = coin.SoSeparator()
            mat = coin.SoBaseColor()
            mat.rgb = colour
            part.addChild(mat)
            style = coin.SoDrawStyle()
            style.lineWidth = 2
            part.addChild(style)
            pts = coin.SoCoordinate3()
            pts.point.setValues(0, 2, [(c.x, c.y, c.z), (tip.x, tip.y, tip.z)])
            part.addChild(pts)
            part.addChild(coin.SoLineSet())
            where = coin.SoTranslation()
            where.translation = (tip.x, tip.y, tip.z)
            part.addChild(where)
            text = coin.SoText2()
            text.string = name
            part.addChild(text)
            sep.addChild(part)
        ball = coin.SoSeparator()
        mat = coin.SoBaseColor()
        mat.rgb = COM_COLOUR
        ball.addChild(mat)
        where = coin.SoTranslation()
        where.translation = (c.x, c.y, c.z)
        ball.addChild(where)
        sphere = coin.SoSphere()
        sphere.radius = size * 0.04
        ball.addChild(sphere)
        sep.addChild(ball)
        root.addChild(sep)
        self.view, self.root, self.node = view, root, sep
        self.shown = (c, axes, size)

    def hide(self):
        if self.root is not None and self.node is not None:
            try:
                self.root.removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("massprops.py:814", _fw_err)
        self.view = self.root = self.node = None
        self.shown = None


class MassPropertiesDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWMassProperties")
        self.setWindowTitle("Mass Properties")
        self.setFont(ui_font())
        self.resize(600, 640)
        self._axis_before = None
        self.triad = Triad()
        layout = QtWidgets.QVBoxLayout(self)

        # and Recalculate side by side, the check boxes, the frame, the report, and Help / Print... / Copy to Clipboard
        head = QtWidgets.QHBoxLayout()
        self.items = QtWidgets.QListWidget()
        self.items.setObjectName("SWMassSelected")
        self.items.setMaximumHeight(64)
        self.items.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.items.customContextMenuRequested.connect(self._items_menu)
        head.addWidget(self.items, 1)
        self.options = QtWidgets.QPushButton("Options...")
        self.options.setObjectName("SWMassOptionsButton")
        head.addWidget(self.options, 0, QtCore.Qt.AlignTop)
        layout.addLayout(head)
        top = QtWidgets.QHBoxLayout()
        self.override = QtWidgets.QPushButton("Override Mass Properties...")
        self.override.setObjectName("SWMassOverrideButton")
        top.addWidget(self.override)
        self.recalc = QtWidgets.QPushButton("Recalculate")
        top.addWidget(self.recalc)
        top.addStretch(1)
        layout.addLayout(top)
        self._sel_timer = QtCore.QTimer(self)
        self._sel_timer.setSingleShot(True)
        self._sel_timer.setInterval(150)
        self._sel_timer.timeout.connect(lambda: self.isVisible() and self.refresh())
        self._observer = _SelWatch(self._sel_timer)
        Gui.Selection.addObserver(self._observer)
        self.hidden = QtWidgets.QCheckBox("Include hidden bodies/components")
        self.hidden.setObjectName("SWMassIncludeHidden")
        self.hidden.setChecked(paths.params().GetBool("MassIncludeHidden", False))
        layout.addWidget(self.hidden)
        self.com = QtWidgets.QCheckBox("Create Center of Mass feature")
        self.com.setObjectName("SWMassCreateCOM")
        layout.addWidget(self.com)
        self.weld = QtWidgets.QCheckBox("Show weld bead mass")
        self.weld.setObjectName("SWMassWeldBead")
        self.weld.setChecked(paths.params().GetBool("MassShowWeld", False))
        layout.addWidget(self.weld)
        layout.addWidget(QtWidgets.QLabel("Report coordinate values relative to:"))
        self.frame = QtWidgets.QComboBox()
        self.frame.setObjectName("SWMassFrame")
        layout.addWidget(self.frame)
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(ui_font())
        self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.text.setTabStopDistance(36)
        layout.addWidget(self.text, 1)
        bottom = QtWidgets.QHBoxLayout()
        self.help_button = QtWidgets.QPushButton("Help")
        self.help_button.setObjectName("SWMassHelp")
        bottom.addWidget(self.help_button)
        self.print_button = QtWidgets.QPushButton("Print...")
        self.print_button.setObjectName("SWMassPrint")
        bottom.addWidget(self.print_button)
        self.copy = QtWidgets.QPushButton("Copy to Clipboard")
        self.copy.setObjectName("SWMassCopy")
        bottom.addWidget(self.copy)
        layout.addLayout(bottom)
        self.recalc.clicked.connect(self.refresh)
        self.help_button.clicked.connect(self._help)
        self.copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(self.text.toPlainText()))
        self.print_button.clicked.connect(self._print)
        self.options.clicked.connect(self._options)
        self.override.clicked.connect(self._override)
        self.hidden.toggled.connect(self._hidden)
        self.weld.toggled.connect(self._weld)
        self.com.toggled.connect(self._com)
        self.frame.activated.connect(lambda *a: self.refresh())

    def _help(self):
        try:
            from . import helpguide
            if helpguide.show_topic("mass properties") is None:
                helpguide.show("04-features.html")
        except Exception as error:
            App.Console.PrintWarning("Help: %s\n" % error)

    def _axis_on(self):
        return paths.params().GetBool("MassShowAxis", True)

    # the switches
    def _hidden(self, on):
        paths.params().SetBool("MassIncludeHidden", bool(on))
        self.refresh()

    def _weld(self, on):
        paths.params().SetBool("MassShowWeld", bool(on))
        self.refresh()

    def _com(self, on):
        doc = App.ActiveDocument
        if doc is None:
            return
        try:
            if on:
                from . import curves
                curves.center_of_mass()
            else:
                # unticked: the Center of Mass feature goes again (one Undo step), so the box is never
                # a switch that springs back
                old = [o for o in doc.Objects if getattr(o, "Proxy", None).__class__.__name__ == "CenterOfMass"]
                if old:
                    doc.openTransaction("Delete Center of Mass")
                    try:
                        for o in old:
                            doc.removeObject(o.Name)
                    finally:
                        doc.commitTransaction()
                    doc.recompute()
        except Exception as error:
            App.Console.PrintWarning("Center of Mass: %s\n" % error)
        self.refresh()

    def _has_com(self):
        doc = App.ActiveDocument
        return doc is not None and any(getattr(o, "Proxy", None).__class__.__name__ == "CenterOfMass" for o in doc.Objects)

    def _view(self):
        try:
            return Gui.ActiveDocument.ActiveView
        except Exception:
            return None

    def _axis(self, on):
        paths.params().SetBool("MassShowAxis", bool(on))
        view = self._view()
        if view is None or not hasattr(view, "setAxisCross"):
            return
        if self._axis_before is None:
            try:
                self._axis_before = (view, bool(view.hasAxisCross()))
            except Exception:
                self._axis_before = (view, False)
        try:
            view.setAxisCross(bool(on))
        except Exception as _fw_err:
            _fw_log("massprops.py:958", _fw_err)

    def _restore_axis(self):
        if self._axis_before is not None:
            view, was = self._axis_before
            try:
                view.setAxisCross(was)
            except Exception as _fw_err:
                _fw_log("massprops.py:966", _fw_err)
        self._axis_before = None

    def _options(self):
        if OptionsBox(self).exec_():
            self.refresh()

    def _override(self):
        if OverrideBox(App.ActiveDocument, self).exec_():
            self.refresh()

    def _print(self):
        try:
            try:
                from PySide import QtPrintSupport
            except ImportError:
                from PySide6 import QtPrintSupport      # FreeCAD's PySide shim leaves it out
            printer = QtPrintSupport.QPrinter()
            dialog = QtPrintSupport.QPrintDialog(printer, self)
            if dialog.exec_():
                doc = self.text.document()
                (doc.print_ if hasattr(doc, "print_") else doc.print)(printer)
        except Exception as error:
            # without Qt's print support, a PDF of the report opens instead (as Section Properties does)
            App.Console.PrintWarning("Print: %s\n" % error)
            try:
                import os
                import tempfile
                path = os.path.join(tempfile.gettempdir(), "Mass-Properties.pdf")
                try:
                    open(path, "ab").close()    # pkg321: still open (locked) in a PDF viewer: a new name
                except OSError:
                    import time
                    path = os.path.join(tempfile.gettempdir(), "Mass-Properties-%d.pdf" % int(time.time() * 1000))
                writer = QtGui.QPdfWriter(path)
                doc = self.text.document()
                (doc.print_ if hasattr(doc, "print_") else doc.print)(writer)
                del writer
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
                self.pdf = path
            except Exception as _fw_err:
                _fw_log("massprops.py:print", _fw_err)

    def _frames(self):
        doc = App.ActiveDocument
        items = [("-- default --", None)] + frames(doc)
        now = self.frame.currentText()
        self.frame.blockSignals(True)
        self.frame.clear()
        for label, placement in items:
            self.frame.addItem(label)
        index = self.frame.findText(now)
        self.frame.setCurrentIndex(index if index >= 0 else 0)
        self.frame.blockSignals(False)
        return dict(items)

    def _units(self):
        """The report's unit system; the density factor (kg/m^3 -> mass unit per cubic length unit) follows it."""
        system = report_system()
        _, mm, length, unit, g, _ = SYSTEMS[system]
        self._factor = 1e-6 * mm ** 3 / g
        return system

    def _stored(self):
        """kg/m^3: the part's material, else the density set in Options..."""
        part = None
        try:
            from . import material
            part = material.part_density(App.ActiveDocument)     # Document Properties > Material Properties
        except Exception as _fw_err:
            _fw_log("massprops.py:part density", _fw_err)
        return getattr(self, "_mat", None) or part or paths.params().GetFloat("Density", DEFAULT_DENSITY)

    def _material(self):
        ""
        try:
            from . import material
            value, name = material.current(App.ActiveDocument)
        except Exception:
            value, name = None, None
        self._mat = value or None
        self._units()
        return value

    def refresh(self):
        global INCLUDE_HIDDEN, DECIMALS, SCIENTIFIC, NEGATIVE
        INCLUDE_HIDDEN = self.hidden.isChecked()
        p = paths.params()
        DECIMALS = p.GetInt("MassDecimals", 2) if p.GetBool("MassCustomUnits", False) else units_page_decimals()
        SCIENTIFIC = p.GetBool("MassScientific", False) and p.GetBool("MassCustomUnits", False)
        NEGATIVE = p.GetBool("MassNegativeTensor", False)
        self._material()
        self.com.blockSignals(True)
        self.com.setChecked(self._has_com())
        self.com.blockSignals(False)
        found = self._frames()
        label = self.frame.currentText()
        frame = found.get(label)
        try:
            objs, title = _targets()
            self.items.clear()
            if title == "Selected items":
                for o in objs:
                    row = QtWidgets.QListWidgetItem(o.Label)
                    row.setData(QtCore.Qt.UserRole, True)         # a picked item: right-click > Delete drops it
                    self.items.addItem(row)
            else:
                self.items.addItem(title)
            doc = App.ActiveDocument
            beads = bool(weld_beads(doc))
            self.weld.setVisible(beads)
            weld = weld_mass(doc, self._stored()) if beads and self.weld.isChecked() else None
            try:
                from . import material
                part_name = material.current(doc)[1]
            except Exception:
                part_name = None
            self.text.setPlainText(report(objs, title, self._stored(), over=overrides(doc), part_name=part_name,
                                          frame=frame, frame_label=label if frame is not None else None, weld=weld))
            if self.isVisible():
                shown = adjust(compute(objs, self._stored()), overrides(doc), None)   # the triad stays in model space
                if shown is not None:
                    shown["shapes"] = [o.Shape for o in objs]
                self.triad.show(shown)
        except Exception as error:
            self.text.setPlainText("Mass properties could not be computed:\n%s" % error)
        finally:
            INCLUDE_HIDDEN = False
        if self.isVisible():
            self._axis(self._axis_on())

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self.refresh)
        self._axis(self._axis_on())

    def _items_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.addAction("Clear Selections").triggered.connect(lambda: (Gui.Selection.clearSelection(), self.refresh()))
        item = self.items.itemAt(pos)
        if item is not None and item.data(QtCore.Qt.UserRole):
            menu.addAction("Delete").triggered.connect(lambda: self._drop(item.text()))
        menu.exec_(self.items.viewport().mapToGlobal(pos))

    def _drop(self, label):
        for s in Gui.Selection.getSelectionEx():
            if s.Object.Label == label:
                Gui.Selection.removeSelection(s.Object)
        self.refresh()

    def closeEvent(self, event):
        self.triad.hide()
        self._restore_axis()            # the selection watch stays: the box is reopened, not made again
        super().closeEvent(event)

    def hideEvent(self, event):
        self.triad.hide()
        self._restore_axis()
        super().hideEvent(event)


class _SelWatch:
    def __init__(self, timer):
        self.timer = timer

    def _poke(self, *args):
        try:
            self.timer.start()
        except Exception as _fw_err:
            _fw_log("massprops.py:1123", _fw_err)
    addSelection = removeSelection = setSelection = clearSelection = _poke


_dialog = None


def show(parent=None):
    global _dialog
    if _dialog is None:
        _dialog = MassPropertiesDialog(parent)
    _dialog.refresh()
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog
