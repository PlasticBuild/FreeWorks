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
import Part

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

TITLE = "DFMXpress"
TAB = ("EV_MANUFACTURABILITY_CHECK", "DFMXpress", "dfmxpress")
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/DFMXpress"
PROCESSES = ["Mill/Drill", "Turn with Mill/Drill", "Sheet Metal", "Injection Molding"]
PULL = ["+Z", "-Z", "+Y", "-Y", "+X", "-X"]
TOL = 1e-6

# rule key -> (name, description, [(parameter key, label, default, min, max, decimals, suffix)])
RULES = {
    "hole_ratio": ("Hole depth to diameter ratio",
                   "Deep, narrow holes are hard to drill: the drill wanders and chips do not clear. Keep the "
                   "depth of each hole within the ratio times its diameter.",
                   [("ratio", "Maximum depth to diameter ratio", 2.5, 0.5, 50, 1, "")]),
    "flat_bottom": ("Holes with flat bottoms",
                    "A blind hole made by a drill ends in a cone. A flat bottom needs another tool (an end "
                    "mill or a flat-bottom drill); end blind holes with a drill point where you can.", []),
    "entry_exit": ("Hole entrance and exit surfaces",
                   "A drill entering or leaving a face that is not square to the hole slips and breaks. The "
                   "faces where each hole starts and ends should be square to its axis.",
                   [("angle", "Largest angle off square", 1.0, 0, 45, 1, " deg")]),
    "partial": ("Partial holes",
                "A hole cut into an edge of the part (less than a full circle in the material) pushes the "
                "drill sideways. Keep at least this much of each hole's circle in the material.",
                [("percent", "Minimum part of the circle in the material", 75.0, 10, 100, 0, " %")]),
    "corner_radius": ("Inner corner radii of milled features",
                      "An end mill is round: the inside corners of pockets and slots need a radius, at least "
                      "the given radius, so a standard tool can reach them.",
                      [("radius", "Minimum corner radius", 1.5, 0, 100, 2, " mm")]),
    "min_wall": ("Minimum wall thickness",
                 "Thin walls move under the cutting forces and chatter. Keep each wall at least this thick.",
                 [("thickness", "Minimum wall thickness", 1.0, 0.01, 100, 2, " mm")]),
    "deep_pocket": ("Deep pockets and slots",
                    "Deep, narrow pockets and slots need long, thin cutters that bend and chatter. Keep each "
                    "pocket's depth within the ratio times its width.",
                    [("ratio", "Maximum depth to width ratio", 4.0, 0.5, 50, 1, "")]),
    "keyway": ("Keyways in bores",
               "A keyway in a bore is broached or slotted right through. A keyway in a blind bore, or one that "
               "stops part way along the bore, cannot be broached; make it run through or leave a relief.",
               []),
    "shoulder": ("Radii at inside shoulders of turned features",
                 "A turning insert has a nose radius: the inside corners where a turned diameter meets a "
                 "shoulder need at least that radius.",
                 [("radius", "Minimum shoulder radius", 0.4, 0, 50, 2, " mm")]),
    "sm_hole": ("Hole diameter",
                "Punched holes smaller than the sheet thickness break punches. Make each hole's diameter at "
                "least the factor times the thickness (T).",
                [("factor", "Minimum diameter (times T)", 1.0, 0.1, 10, 2, " T")]),
    "sm_edge": ("Hole to edge distance",
                "A hole close to the edge of the sheet bulges the edge. Keep holes at least the factor "
                "times the thickness from the edge.",
                [("factor", "Minimum distance (times T)", 2.0, 0.1, 20, 2, " T")]),
    "sm_spacing": ("Hole spacing",
                   "Holes close together tear the web between them. Keep holes at least the factor times "
                   "the thickness apart.",
                   [("factor", "Minimum spacing (times T)", 2.0, 0.1, 20, 2, " T")]),
    "sm_bend": ("Bend radius",
                "An inside bend radius smaller than the thickness cracks the outside of the bend. Make "
                "the inside radius at least the factor times the thickness.",
                [("factor", "Minimum inside radius (times T)", 1.0, 0.1, 20, 2, " T")]),
    "sm_hole_bend": ("Hole to bend distance",
                     "A hole close to a bend is pulled out of shape when the sheet bends. Keep holes at "
                     "least 2.5 T plus the bend radius from the bend (the factor below is the 2.5).",
                     [("factor", "Minimum distance (times T, plus R)", 2.5, 0.1, 20, 2, " T")]),
    "im_wall": ("Wall thickness",
                "Molded walls that are too thin do not fill; walls that are too thick sink and warp. Keep "
                "each wall between the minimum and the maximum.",
                [("minimum", "Minimum wall thickness", 0.75, 0.05, 50, 2, " mm"),
                 ("maximum", "Maximum wall thickness", 4.0, 0.1, 100, 2, " mm")]),
    "im_draft": ("Draft",
                 "Faces along the pull direction need draft so the part comes out of the mold. Give each "
                 "such face at least the minimum draft.",
                 [("angle", "Minimum draft", 1.0, 0, 30, 1, " deg")]),
    "im_corners": ("Sharp inside corners",
                   "Sharp inside corners on molded parts hold stress and stop the plastic flowing. Round "
                   "inside corners to at least the given radius.",
                   [("radius", "Minimum inside radius", 0.5, 0, 50, 2, " mm")]),
}
BY_PROCESS = {
    "Mill/Drill": ["hole_ratio", "flat_bottom", "entry_exit", "partial", "corner_radius", "deep_pocket",
                   "min_wall"],
    "Turn with Mill/Drill": ["hole_ratio", "flat_bottom", "entry_exit", "partial", "corner_radius", "deep_pocket",
                             "min_wall", "shoulder", "keyway"],
    "Sheet Metal": ["sm_hole", "sm_edge", "sm_spacing", "sm_bend", "sm_hole_bend"],
    "Injection Molding": ["im_wall", "im_draft", "im_corners"],
}


# ------------------------------------------------------------------------------ settings
def params():
    return App.ParamGet(PARAMS)


def process():
    p = params().GetString("Process", PROCESSES[0])
    return p if p in PROCESSES else PROCESSES[0]


def set_process(name):
    params().SetString("Process", name)


def pull():
    p = params().GetString("Pull", PULL[0])
    return p if p in PULL else PULL[0]


def set_pull(name):
    params().SetString("Pull", name)


def value(rule, key):
    for k, _label, default, *_ in RULES[rule][2]:
        if k == key:
            return params().GetFloat("%s.%s" % (rule, key), default)
    raise KeyError(key)


def set_value(rule, key, v):
    params().SetFloat("%s.%s" % (rule, key), float(v))


def reset_values():
    for rule, (_n, _d, ps) in RULES.items():
        for k, *_ in ps:
            params().RemFloat("%s.%s" % (rule, k))


# ------------------------------------------------------------------------------ the part
def target(doc):
    """The part's main solid object (the Body, or the largest solid at the top of the tree)."""
    if doc is None:
        return None
    try:
        from . import evaltools
        return evaltools._main(doc)
    except Exception as _fw_err:
        _fw_log("dfmxpress.py:183", _fw_err)
    best = None
    for o in doc.Objects:
        s = getattr(o, "Shape", None)
        if isinstance(s, Part.Shape) and not s.isNull() and s.Solids and not o.InList:
            if best is None or s.Volume > best.Shape.Volume:
                best = o
    return best


def _name(shape, sub, kind="Face"):
    seq = shape.Faces if kind == "Face" else shape.Edges
    for i, x in enumerate(seq, 1):
        if x.isSame(sub):
            return "%s%d" % (kind, i)
    return None


def _index(shape, sub, kind="Face"):
    seq = shape.Faces if kind == "Face" else shape.Edges
    for i, x in enumerate(seq):
        if x.isSame(sub):
            return i
    return -1


def _mid(face):
    u0, u1, v0, v1 = face.ParameterRange
    return (u0 + u1) / 2, (v0 + v1) / 2


def _inside_cyl(face):
    """True for a cylinder face whose material is outside it (a hole or a fillet's inside)."""
    s = face.Surface
    if not isinstance(s, Part.Cylinder):
        return False
    u, v = _mid(face)
    p = face.valueAt(u, v)
    n = face.normalAt(u, v)
    axis_pt = s.Center + s.Axis * (p - s.Center).dot(s.Axis)
    return (axis_pt - p).dot(n) > 0


def _span(face):
    u0, u1, _v0, _v1 = face.ParameterRange
    return abs(u1 - u0)


def _plane_normal(face):
    u, v = _mid(face)
    return face.normalAt(u, v)


def _neighbours(shape, face):
    out = []
    for e in face.Edges:
        for g in shape.ancestorsOfType(e, Part.Face):
            if not g.isSame(face):
                out.append((e, g))
    return out


def holes(shape):
    """[{"faces": [Face], "radius", "axis", "depth", "angle", "ends": [(edge, face)]}]: coaxial inside
    cylinder faces of one radius grouped into one hole (fillet-sized arcs left out)."""
    groups = []
    for f in shape.Faces:
        if not _inside_cyl(f):
            continue
        s = f.Surface
        for g in groups:
            if abs(g["radius"] - s.Radius) < 1e-6 and abs(abs(g["axis"].dot(s.Axis)) - 1) < 1e-6:
                d = s.Center - g["center"]
                if (d - g["axis"] * d.dot(g["axis"])).Length < 1e-5:
                    g["faces"].append(f)
                    break
        else:
            groups.append({"faces": [f], "radius": s.Radius, "axis": App.Vector(s.Axis).normalize(),
                           "center": App.Vector(s.Center)})
    out = []
    for g in groups:
        angle = sum(_span(f) for f in g["faces"])
        if angle < math.pi * 0.95:          # a fillet or a round edge, not a hole
            continue
        ax, c = g["axis"], g["center"]
        ts = [(v.Point - c).dot(ax) for f in g["faces"] for v in f.Vertexes]
        if not ts:
            continue
        g["depth"] = max(ts) - min(ts)
        g["angle"] = min(angle, 2 * math.pi)
        ends = []
        for f in g["faces"]:
            for e, n in _neighbours(shape, f):
                if any(n.isSame(h) for h in g["faces"]):
                    continue
                if isinstance(e.Curve, (Part.Circle, Part.ArcOfCircle)) or e.Curve.TypeId == "Part::GeomCircle" \
                        or not isinstance(e.Curve, Part.Line):
                    ends.append((e, n))
        g["ends"] = ends
        out.append(g)
    return out


def _bottom(g):
    """The face closing a blind hole, or None (a through hole)."""
    for e, n in g["ends"]:
        if isinstance(n.Surface, Part.Cone):
            return n
        if isinstance(n.Surface, Part.Plane):
            nn = _plane_normal(n)
            if abs(abs(nn.dot(g["axis"])) - 1) < 1e-6 and n.Area <= math.pi * g["radius"] ** 2 * 1.02 \
                    and len(n.Wires) == 1:
                return n
    return None


def _concave(shape, e, fa, fb):
    """True when the edge between fa and fb is an inside (concave) corner."""
    try:
        t = (e.FirstParameter + e.LastParameter) / 2
        m = e.valueAt(t)
        pa = fa.Surface.parameter(m)
        pb = fb.Surface.parameter(m)
        na, nb = fa.normalAt(*pa), fb.normalAt(*pb)
    except Exception:
        return False
    if abs(na.dot(nb)) > 0.999:
        return False
    # along one face's normal and against the other's: in the material only at an inside corner
    probe = m + (na - nb) * 0.02
    return shape.isInside(probe, 1e-6, False)


def sharp_inside_edges(shape):
    """Line or circle edges where two faces meet at an inside corner with no radius."""
    out = []
    for e in shape.Edges:
        fs = shape.ancestorsOfType(e, Part.Face)
        if len(fs) != 2:
            continue
        if _concave(shape, e, fs[0], fs[1]):
            out.append((e, fs[0], fs[1]))
    return out


def inside_radii(shape):
    """[(face, radius)]: inside fillet faces (concave cylinder faces less than a half turn)."""
    return [(f, f.Surface.Radius) for f in shape.Faces
            if _inside_cyl(f) and _span(f) < math.pi * 0.95]


def walls(shape):
    """[(face a, face b, thickness)]: opposite parallel planar faces with material between them."""
    planes = [f for f in shape.Faces if isinstance(f.Surface, Part.Plane)]
    out = []
    for i, f in enumerate(planes):
        n = _plane_normal(f)
        p = _point_on(f)
        if p is None:
            continue
        best = None
        for j, g in enumerate(planes):
            if j == i:
                continue
            m = _plane_normal(g)
            if abs(n.dot(m) + 1) > 1e-6:
                continue
            d = (p - _point_on(g, any_point=True)).dot(n)
            if d <= 1e-6:
                continue
            q = p - n * d
            try:
                if not g.isInside(q, 1e-5, True):
                    continue
            except Exception:
                continue
            if not shape.isInside(p - n * (d / 2), 1e-6, False):
                continue
            if best is None or d < best[2]:
                best = (f, g, d)
        if best is not None and not any(b is best[0] and a is best[1] for a, b, _d in out):
            out.append(best)
    return out


def _point_on(face, any_point=False):
    u, v = _mid(face)
    p = face.valueAt(u, v)
    if any_point:
        return p
    try:
        if face.isInside(p, 1e-6, True):
            return p
    except Exception as _fw_err:
        _fw_log("dfmxpress.py:377", _fw_err)
    try:
        t = face.tessellate(1.0)
        for tri in t[1]:
            c = (t[0][tri[0]] + t[0][tri[1]] + t[0][tri[2]]) / 3
            if face.isInside(c, 1e-6, True):
                return c
    except Exception as _fw_err:
        _fw_log("dfmxpress.py:385", _fw_err)
    return None


def _in_plane_axes(n, face):
    """Two unit vectors in the plane of n, the first along the face's longest straight edge."""
    best = None
    for e in face.Edges:
        if isinstance(e.Curve, Part.Line) and (best is None or e.Length > best.Length):
            best = e
    if best is not None:
        a = best.Vertexes[-1].Point - best.Vertexes[0].Point
    else:
        a = App.Vector(1, 0, 0) if abs(n.x) < 0.9 else App.Vector(0, 1, 0)
    a = a - n * a.dot(n)
    a.normalize()
    return a, n.cross(a)


def pockets(shape):
    """[(floor, [walls], depth, width)]: planar floors with inside-corner walls on two or more sides."""
    out = []
    for f in shape.Faces:
        if not isinstance(f.Surface, Part.Plane):
            continue
        n = _plane_normal(f)
        walls_ = []
        for e, g in _neighbours(shape, f):
            if any(g.isSame(w) for w in walls_):
                continue
            if _concave(shape, e, f, g):
                walls_.append(g)
        if len(walls_) < 2:
            continue
        base = f.Vertexes[0].Point.dot(n)
        depth = max(v.Point.dot(n) - base for w in walls_ for v in w.Vertexes)
        if depth <= 1e-6:
            continue
        p = _point_on(f)
        if p is None or shape.isInside(p + n * (depth + 0.05), 1e-6, False):
            continue                        # closed above: a wall of something else, not a floor
        a, b = _in_plane_axes(n, f)
        pa = [v.Point.dot(a) for v in f.Vertexes]
        pb = [v.Point.dot(b) for v in f.Vertexes]
        width = min(max(pa) - min(pa), max(pb) - min(pb))
        if width > 1e-6:
            out.append((f, walls_, depth, width))
    return out


def _blind(shape, g):
    ax, c = g["axis"], g["center"]
    ts = [(v.Point - c).dot(ax) for f in g["faces"] for v in f.Vertexes]
    return any(shape.isInside(c + ax * t, 1e-6, False) for t in (min(ts) - 0.05, max(ts) + 0.05))


def keyways(shape):
    """[(hole, [key faces], blind bore, blind key)]: bores broken by a slot whose sides run along the axis."""
    out = []
    for g in holes(shape):
        sides = []
        for _e, n in [x for f in g["faces"] for x in _neighbours(shape, f)]:
            if isinstance(n.Surface, Part.Plane) and abs(_plane_normal(n).dot(g["axis"])) < 1e-6 \
                    and not any(n.isSame(x) for x in sides):
                sides.append(n)
        if len(sides) < 2:
            continue
        ax = g["axis"]
        ts = [v.Point.dot(ax) for f in g["faces"] for v in f.Vertexes]
        ks = [v.Point.dot(ax) for f in sides for v in f.Vertexes]
        short = (max(ks) - min(ks)) < (max(ts) - min(ts)) - 1e-4
        out.append((g, sides, _blind(shape, g), short))
    return out


def sheet_thickness(shape):
    """The most common wall thickness: the sheet's thickness T."""
    counts = {}
    for _a, _b, d in walls(shape):
        k = round(d, 3)
        counts[k] = counts.get(k, 0) + 1
    return max(counts, key=lambda k: (counts[k], -k)) if counts else None


# ------------------------------------------------------------------------------ rules
def _inst(shape, subs, text):
    names = []
    for s in subs:
        kind = "Edge" if isinstance(s, Part.Edge) else "Face"
        n = _name(shape, s, kind)
        if n and n not in names:
            names.append(n)
    return {"subs": names, "text": text}


def _hole_text(g):
    return "diameter %.2f mm, depth %.2f mm" % (2 * g["radius"], g["depth"])


def check(shape, proc=None, direction=None):
    """[{"rule", "name", "description", "passed", "instances": [{"subs", "text"}]}] for the process."""
    proc = proc or process()
    out = []
    hs = holes(shape)
    full = [g for g in hs if g["angle"] >= 2 * math.pi - 1e-3]
    for rule in BY_PROCESS[proc]:
        inst = []
        if rule == "hole_ratio":
            r = value(rule, "ratio")
            for g in hs:
                ratio = g["depth"] / (2 * g["radius"])
                if ratio > r + 1e-9:
                    inst.append(_inst(shape, g["faces"], "%s: ratio %.2f (max %.2f)" % (_hole_text(g), ratio, r)))
        elif rule == "flat_bottom":
            for g in hs:
                b = _bottom(g)
                if b is not None and isinstance(b.Surface, Part.Plane):
                    inst.append(_inst(shape, g["faces"] + [b], "%s: flat bottom" % _hole_text(g)))
        elif rule == "entry_exit":
            lim = math.radians(value(rule, "angle"))
            for g in hs:
                b = _bottom(g)
                bad = []
                for e, n in g["ends"]:
                    if b is not None and n.isSame(b):
                        continue
                    if isinstance(n.Surface, Part.Plane):
                        off = math.acos(min(1.0, abs(_plane_normal(n).dot(g["axis"]))))
                        if off > lim + 1e-9:
                            bad.append((n, "%.1f deg off square" % math.degrees(off)))
                    elif not isinstance(n.Surface, Part.Cone):
                        bad.append((n, "a curved face"))
                if bad:
                    inst.append(_inst(shape, g["faces"] + [n for n, _t in bad],
                                      "%s: enters or leaves %s" % (_hole_text(g), "; ".join(t for _n, t in bad))))
        elif rule == "partial":
            pc = value(rule, "percent")
            for g in hs:
                share = g["angle"] / (2 * math.pi) * 100
                if share < pc - 1e-6:
                    inst.append(_inst(shape, g["faces"], "%s: %.0f %% of the circle in the material (min %.0f %%)"
                                      % (_hole_text(g), share, pc)))
        elif rule in ("corner_radius", "im_corners"):
            rmin = value(rule, "radius")
            for e, fa, fb in sharp_inside_edges(shape):
                if not (isinstance(fa.Surface, Part.Plane) and isinstance(fb.Surface, Part.Plane)):
                    continue
                inst.append(_inst(shape, [e], "sharp inside corner (radius 0, min %.2f mm)" % rmin))
            for f, r in inside_radii(shape):
                if r < rmin - 1e-9:
                    inst.append(_inst(shape, [f], "inside radius %.2f mm (min %.2f mm)" % (r, rmin)))
        elif rule == "min_wall":
            t = value(rule, "thickness")
            for a, b, d in walls(shape):
                if d < t - 1e-9:
                    inst.append(_inst(shape, [a, b], "wall %.2f mm (min %.2f mm)" % (d, t)))
        elif rule == "deep_pocket":
            r = value(rule, "ratio")
            for floor, ws, depth, width in pockets(shape):
                if depth / width > r + 1e-9:
                    inst.append(_inst(shape, [floor] + ws, "depth %.2f mm, width %.2f mm: ratio %.2f (max %.2f)"
                                      % (depth, width, depth / width, r)))
        elif rule == "keyway":
            for g, sides, blind, short in keyways(shape):
                if blind or short:
                    why = "the bore is blind" if blind else "the keyway stops part way along the bore"
                    inst.append(_inst(shape, g["faces"] + sides, "%s: %s" % (_hole_text(g), why)))
        elif rule == "shoulder":
            rmin = value(rule, "radius")
            for e, fa, fb in sharp_inside_edges(shape):
                kinds = {type(fa.Surface).__name__, type(fb.Surface).__name__}
                if kinds == {"Cylinder", "Plane"} and e.Curve.TypeId == "Part::GeomCircle":
                    inst.append(_inst(shape, [e], "sharp inside shoulder (min radius %.2f mm)" % rmin))
        elif rule.startswith("sm_"):
            T = sheet_thickness(shape)
            if T is None:
                continue
            sm = [g for g in full if abs(g["depth"] - T) < max(1e-3, T * 0.02)]
            bends = [f for f in shape.Faces if isinstance(f.Surface, Part.Cylinder) and _span(f) < math.pi * 0.999
                     and not any(any(f.isSame(h) for h in g["faces"]) for g in hs)]
            inner = [f for f in bends if _inside_cyl(f)]
            if rule == "sm_hole":
                k = value(rule, "factor")
                for g in sm:
                    if 2 * g["radius"] < k * T - 1e-9:
                        inst.append(_inst(shape, g["faces"], "diameter %.2f mm (min %.2f mm, T = %.2f mm)"
                                          % (2 * g["radius"], k * T, T)))
            elif rule == "sm_edge":
                k = value(rule, "factor")
                hole_edges = [e for g in sm for f in g["faces"] for e in f.Edges]
                for g in sm:
                    best = None
                    for e, n in g["ends"]:
                        if not isinstance(n.Surface, Part.Plane):
                            continue
                        rim = [x for x in n.OuterWire.Edges if not any(x.isSame(h) for h in hole_edges)]
                        if not rim:
                            continue
                        d = Part.Compound(rim).distToShape(e)[0]
                        if best is None or d < best[0]:
                            best = (d, n)
                    if best is not None and best[0] < k * T - 1e-9:
                        inst.append(_inst(shape, g["faces"], "%.2f mm from the edge (min %.2f mm)" % (best[0], k * T)))
            elif rule == "sm_spacing":
                k = value(rule, "factor")
                for i, g in enumerate(sm):
                    for h in sm[i + 1:]:
                        d = Part.Compound(g["faces"]).distToShape(Part.Compound(h["faces"]))[0]
                        if d < k * T - 1e-9:
                            inst.append(_inst(shape, g["faces"] + h["faces"], "holes %.2f mm apart (min %.2f mm)"
                                              % (d, k * T)))
            elif rule == "sm_bend":
                k = value(rule, "factor")
                for f in inner:
                    if f.Surface.Radius < k * T - 1e-9:
                        inst.append(_inst(shape, [f], "inside bend radius %.2f mm (min %.2f mm)"
                                          % (f.Surface.Radius, k * T)))
                for e, fa, fb in sharp_inside_edges(shape):
                    if isinstance(fa.Surface, Part.Plane) and isinstance(fb.Surface, Part.Plane):
                        inst.append(_inst(shape, [e], "sharp bend (radius 0, min %.2f mm)" % (k * T)))
            elif rule == "sm_hole_bend":
                k = value(rule, "factor")
                for g in sm:
                    for f in inner:
                        lim = k * T + f.Surface.Radius
                        d = Part.Compound(g["faces"]).distToShape(f)[0]
                        if d < lim - 1e-9:
                            inst.append(_inst(shape, g["faces"] + [f], "%.2f mm from the bend (min %.2f mm)" % (d, lim)))
        elif rule == "im_wall":
            lo, hi = value(rule, "minimum"), value(rule, "maximum")
            for a, b, d in walls(shape):
                if d < lo - 1e-9:
                    inst.append(_inst(shape, [a, b], "wall %.2f mm, thinner than %.2f mm" % (d, lo)))
                elif d > hi + 1e-9:
                    inst.append(_inst(shape, [a, b], "wall %.2f mm, thicker than %.2f mm" % (d, hi)))
        elif rule == "im_draft":
            amin = math.radians(value(rule, "angle"))
            d = direction or pull()
            axis = {"X": App.Vector(1, 0, 0), "Y": App.Vector(0, 1, 0), "Z": App.Vector(0, 0, 1)}[d[1]]
            for f in shape.Faces:
                try:
                    if isinstance(f.Surface, Part.Plane):
                        n = _plane_normal(f)
                    elif isinstance(f.Surface, Part.Cylinder):
                        n = None
                        if abs(abs(App.Vector(f.Surface.Axis).dot(axis)) - 1) < 1e-6:
                            inst.append(_inst(shape, [f], "no draft (0.0 deg, min %.1f deg)" % math.degrees(amin)))
                        continue
                    else:
                        continue
                except Exception:
                    continue
                c = abs(n.dot(axis))
                if c > 0.999999:
                    continue                    # a face square to the pull: a parting or top face
                draft = math.asin(min(1.0, c))
                if draft < amin - 1e-9:
                    inst.append(_inst(shape, [f], "draft %.1f deg (min %.1f deg)" % (math.degrees(draft),
                                                                                     math.degrees(amin))))
        name, desc, _ps = RULES[rule]
        out.append({"rule": rule, "name": name, "description": desc, "passed": not inst, "instances": inst})
    return out


def run(doc=None, proc=None):
    doc = doc or App.ActiveDocument
    obj = target(doc)
    if obj is None:
        raise RuntimeError("DFMXpress needs a part with a solid body.")
    return obj, check(obj.Shape, proc)


# ------------------------------------------------------------------------------ the pane
if Gui is not None:

    def _alive(w):
        try:
            w.objectName()
            return True
        except RuntimeError:
            return False

    class RulesDialog(QtWidgets.QDialog):
        """Configure Rules...: each rule's limits, a tab per process; Reset to defaults."""

        def __init__(self, parent=None, start=None):
            super().__init__(parent or Gui.getMainWindow())
            self.setObjectName("SWDFMXpressRules")
            self.setWindowTitle("Configure Rules")
            lay = QtWidgets.QVBoxLayout(self)
            self.tabs = QtWidgets.QTabWidget()
            self.spins = {}
            for proc in PROCESSES:
                page = QtWidgets.QWidget()
                form = QtWidgets.QFormLayout(page)
                for rule in BY_PROCESS[proc]:
                    name, _d, ps = RULES[rule]
                    head = QtWidgets.QLabel("<b>%s</b>" % name)
                    form.addRow(head)
                    if not ps:
                        form.addRow(QtWidgets.QLabel("(no limits: every instance is reported)"))
                    for k, label, default, lo, hi, dec, suffix in ps:
                        sp = QtWidgets.QDoubleSpinBox()
                        sp.setObjectName("SWDFMRule_%s_%s" % (rule, k))
                        sp.setRange(lo, hi)
                        sp.setDecimals(dec)
                        sp.setSuffix(suffix)
                        sp.setValue(value(rule, k))
                        self.spins.setdefault((rule, k), []).append(sp)
                        sp.valueChanged.connect(lambda v, key=(rule, k), w=sp: self._sync(key, w, v))
                        form.addRow(label + ":", sp)
                self.tabs.addTab(page, proc)
            if start in PROCESSES:
                self.tabs.setCurrentIndex(PROCESSES.index(start))
            lay.addWidget(self.tabs)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            reset = bb.addButton("Reset to Defaults", QtWidgets.QDialogButtonBox.ResetRole)
            reset.setObjectName("SWDFMRulesReset")
            reset.clicked.connect(self.defaults)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)

        def _sync(self, key, w, v):
            for other in self.spins[key]:      # a rule shared by two processes shows one value
                if other is not w and abs(other.value() - v) > 1e-12:
                    other.blockSignals(True)
                    other.setValue(v)
                    other.blockSignals(False)

        def defaults(self):
            for (rule, k), ws in self.spins.items():
                for kk, _l, default, *_ in RULES[rule][2]:
                    if kk == k:
                        for w in ws:
                            w.setValue(default)

        def accept(self):
            for (rule, k), ws in self.spins.items():
                set_value(rule, k, ws[0].value())
            super().accept()

    class DFMXpressPage(QtWidgets.QWidget):
        def __init__(self, pane=None):
            super().__init__()
            self.setObjectName("SWDFMXpress")
            self.results, self.obj = None, None
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(6, 6, 6, 6)
            head = QtWidgets.QLabel("<b>DFMXpress</b>")
            lay.addWidget(head)
            row = QtWidgets.QHBoxLayout()
            self.settings_btn = QtWidgets.QPushButton("Settings")
            self.settings_btn.setObjectName("SWDFMSettings")
            self.settings_btn.setCheckable(True)
            self.run_btn = QtWidgets.QPushButton("Run")
            self.run_btn.setObjectName("SWDFMRun")
            self.close_btn = QtWidgets.QPushButton("Close")
            self.close_btn.setObjectName("SWDFMClose")
            for b in (self.settings_btn, self.run_btn, self.close_btn):
                row.addWidget(b)
            lay.addLayout(row)

            self.settings = QtWidgets.QGroupBox("Settings")
            self.settings.setObjectName("SWDFMSettingsBox")
            sl = QtWidgets.QVBoxLayout(self.settings)
            sl.addWidget(QtWidgets.QLabel("Manufacturing process:"))
            self.proc_group = QtWidgets.QButtonGroup(self)
            self.proc_buttons = {}
            for i, p in enumerate(PROCESSES):
                rb = QtWidgets.QRadioButton(p)
                rb.setObjectName("SWDFMProcess_" + p.replace("/", "").replace(" ", ""))
                self.proc_group.addButton(rb, i)
                self.proc_buttons[p] = rb
                sl.addWidget(rb)
            self.proc_buttons[process()].setChecked(True)
            self.pull_row = QtWidgets.QWidget()
            pr = QtWidgets.QHBoxLayout(self.pull_row)
            pr.setContentsMargins(0, 0, 0, 0)
            pr.addWidget(QtWidgets.QLabel("Pull direction:"))
            self.pull = QtWidgets.QComboBox()
            self.pull.setObjectName("SWDFMPull")
            self.pull.addItems(PULL)
            self.pull.setCurrentText(pull())
            pr.addWidget(self.pull)
            sl.addWidget(self.pull_row)
            self.rules_btn = QtWidgets.QPushButton("Configure Rules...")
            self.rules_btn.setObjectName("SWDFMConfigure")
            sl.addWidget(self.rules_btn)
            lay.addWidget(self.settings)
            self.settings.setVisible(False)

            self.status = QtWidgets.QLabel("Pick the manufacturing process in Settings, then click Run.")
            self.status.setObjectName("SWDFMStatus")
            self.status.setWordWrap(True)
            lay.addWidget(self.status)
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setObjectName("SWDFMResults")
            self.tree.setHeaderHidden(True)
            lay.addWidget(self.tree, 1)
            self.info = QtWidgets.QTextBrowser()
            self.info.setObjectName("SWDFMDescription")
            self.info.setMaximumHeight(140)
            lay.addWidget(self.info)

            self.settings_btn.toggled.connect(self.settings.setVisible)
            self.run_btn.clicked.connect(self.run_check)
            self.close_btn.clicked.connect(close)
            self.rules_btn.clicked.connect(self.configure)
            self.proc_group.buttonClicked.connect(self._process_picked)
            self.pull.currentTextChanged.connect(lambda t: (set_pull(t), self._stale()))
            self.tree.currentItemChanged.connect(self._picked)
            self._show_pull()

        def _show_pull(self):
            self.pull_row.setVisible(process() == "Injection Molding")

        def _process_picked(self, b):
            set_process(b.text())
            self._show_pull()
            self._stale()

        def _stale(self):
            if self.results is not None:
                self.status.setText("The settings changed: click Rerun.")

        def configure(self):
            if RulesDialog(self, process()).exec_():
                self._stale()

        def run_check(self):
            self.tree.clear()
            self.info.clear()
            try:
                self.obj, self.results = run(App.ActiveDocument)
            except Exception as e:
                self.results = None
                self.status.setText(str(e))
                return
            self.run_btn.setText("Rerun")
            self.settings_btn.setChecked(False)
            failed = [r for r in self.results if not r["passed"]]
            passed = [r for r in self.results if r["passed"]]
            red, green = QtGui.QBrush(QtGui.QColor(200, 40, 40)), QtGui.QBrush(QtGui.QColor(30, 140, 50))
            for title, rules, brush in (("Failed Rules", failed, red), ("Passed Rules", passed, green)):
                top = QtWidgets.QTreeWidgetItem(self.tree, ["%s (%d)" % (title, len(rules))])
                top.setForeground(0, brush)
                f = top.font(0)
                f.setBold(True)
                top.setFont(0, f)
                for r in rules:
                    it = QtWidgets.QTreeWidgetItem(top, [r["name"] + (" (%d)" % len(r["instances"]) if r["instances"] else "")])
                    it.setForeground(0, brush)
                    it.setData(0, QtCore.Qt.UserRole, ("rule", r["rule"]))
                    for k, inst in enumerate(r["instances"], 1):
                        c = QtWidgets.QTreeWidgetItem(it, ["Instance %d" % k])
                        c.setData(0, QtCore.Qt.UserRole, ("inst", r["rule"], k - 1))
                top.setExpanded(True)
            self.status.setText("%s on %s: %d rules failed, %d passed." % (process(), self.obj.Label, len(failed),
                                                                           len(passed)))

        def _rule(self, key):
            for r in self.results or []:
                if r["rule"] == key:
                    return r
            return None

        def _picked(self, item, _prev=None):
            if item is None or self.obj is None:
                return
            data = item.data(0, QtCore.Qt.UserRole)
            if not data:
                self.info.clear()
                return
            r = self._rule(data[1])
            if r is None:
                return
            insts = r["instances"] if data[0] == "rule" else [r["instances"][data[2]]]
            text = "<b>%s</b><br>%s" % (r["name"], r["description"])
            if data[0] == "inst":
                text += "<br><br><b>Instance %d:</b> %s" % (data[2] + 1, insts[0]["text"])
            elif r["passed"]:
                text += "<br><br>No instances: the part meets this rule."
            self.info.setHtml(text)
            self.highlight(insts)

        def highlight(self, insts):
            try:
                Gui.Selection.clearSelection()
                doc = self.obj.Document
                for inst in insts:
                    for sub in inst["subs"]:
                        Gui.Selection.addSelection(doc.Name, self.obj.Name, sub)
            except Exception as _fw_err:
                _fw_log("dfmxpress.py:879", _fw_err)

    _state = {"page": None, "dock": None}

    def _page(pane):
        p = DFMXpressPage(pane)
        _state["page"] = p
        return p

    def open_dfm():
        """Tools > Xpress Products > DFMXpress / Evaluate > Manufacturability Check."""
        from . import simxpress, taskpane
        index = simxpress.add_tab(TAB, _page)
        page = taskpane.open_tab(index)
        if page is None:
            dock = _state.get("dock")
            if dock is None or not _alive(dock):
                dock = QtWidgets.QDockWidget(TITLE, Gui.getMainWindow())
                dock.setObjectName("SWDFMXpressDock")
                dock.setWidget(_page(None))
                Gui.getMainWindow().addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
                _state["dock"] = dock
            dock.show()
            page = dock.widget()
        else:
            try:
                page.parentWidget().parentWidget().pin.setChecked(True)
            except Exception as _fw_err:
                _fw_log("dfmxpress.py:907", _fw_err)
        _state["page"] = page
        return page

    def close():
        from . import simxpress
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("dfmxpress.py:916", _fw_err)
        simxpress.remove_tab(TAB)
        dock = _state.get("dock")
        if dock is not None and _alive(dock):
            dock.close()
            dock.deleteLater()
        _state.update(page=None, dock=None)

    def page():
        p = _state.get("page")
        return p if p is not None and _alive(p) else None
