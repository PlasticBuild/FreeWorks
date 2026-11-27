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
import Part
from PySide import QtCore, QtGui, QtWidgets

V = App.Vector
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Measure"
ARC_MODES = ("Center to Center", "Minimum Distance", "Maximum Distance")
PROJECTIONS = ("None", "Screen", "Select Face/Plane")
# length units: name -> (symbol, size in mm)
LENGTHS = {"Millimeters": ("mm", 1.0), "Centimeters": ("cm", 10.0), "Meters": ("m", 1000.0),
           "Inches": ("in", 25.4), "Feet": ("ft", 304.8), "Microns": ("um", 0.001)}
SYSTEM_LENGTH = {"MMGS": "Millimeters", "CGS": "Centimeters", "MKS": "Meters", "IPS": "Inches"}
TOL = 1e-7

SHORT = {"Center Distance": "Center Dist", "Distance": "Dist", "Minimum Distance": "Min Dist",
         "Maximum Distance": "Max Dist", "Normal Distance": "Normal Dist"}
PICKED_RGB = (0.25, 0.85, 0.25)


def picked_rgb():
    ""
    try:
        from . import optionspages
        return optionspages.kept_color("Measure Highlight", PICKED_RGB)
    except Exception:
        return PICKED_RGB


# ------------------------------------------------------------------ units
BAR_ICONS = {      # icon pack families for the Measure toolbar (text stays when the pack has none)
    "ArcCircle": "SKETCH_CTRPT_CIRCLE", "Units": "STANDARD_OPTIONS", "XYZ": "VIEW_POINTS",
    "PointToPoint": "QS_POINT", "ProjectedOn": "VIEW_PRIMARY_PLANES", "History": "TREE_HISTORY_FOLDER",
    "Sensor": "TOOLS_SENSOR", "Pin": "PIN_NORMAL"}


def _bar_icon(name):
    try:
        from . import icons
        icon = icons.family(BAR_ICONS.get(name, ""))
        return icon if icons.paints(icon) else None
    except Exception:
        return None


class Units:
    ""

    def __init__(self, length="Millimeters", decimals=2, degrees=True, angle_decimals=2,
                 scientific=False, dual=None, denominator=0, round_fraction=False):
        self.length, self.decimals, self.degrees, self.angle_decimals = length, decimals, degrees, angle_decimals
        self.scientific = scientific          # Scientific notation
        self.dual = dual                      # Use dual units: a second length unit in brackets
        self.denominator = denominator        # Fractions (inches, feet): 0 = decimals
        self.round_fraction = round_fraction  # Round to nearest fraction

    @classmethod
    def document(cls):
        length = None
        try:
            # unitsall: the part's own length unit (Document Properties > Units), so a Custom part in feet measures

            from . import unitspage
            length = {"mm": "Millimeters", "cm": "Centimeters", "m": "Meters", "in": "Inches",
                      "ft": "Feet"}.get(unitspage.length_unit(App.ActiveDocument)[0])
        except Exception as _fw_err:
            _fw_log("measure.py:doc length", _fw_err)
        if length is None:
            try:
                from . import massprops
                length = SYSTEM_LENGTH.get(massprops.unit_system(), "Millimeters")
            except Exception:
                length = "Millimeters"
        decimals = App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("Decimals", 2)
        angle_decimals = decimals
        try:

            from . import unitspage
            angle_decimals = unitspage.angle_decimals(App.ActiveDocument)
        except Exception as _fw_err:
            _fw_log("measure.py:angle decimals", _fw_err)
        return cls(length, decimals, True, angle_decimals)

    def value(self, text):
        """The number in front of a result text (the first one), in this unit."""
        import re
        m = re.match(r"\s*(-?\d+(?:\.\d*)?(?:e[-+]?\d+)?)", text or "")
        return float(m.group(1)) if m else None

    def _number(self, value, unit, power):
        if self.scientific:
            return ("%%.%de" % self.decimals) % value
        if self.denominator and power == 1 and unit in ("Inches", "Feet"):
            d = self.denominator
            whole = math.floor(abs(value))
            n = round((abs(value) - whole) * d)
            exact = abs((abs(value) - whole) * d - n) < 1e-6
            if exact or self.round_fraction:
                if n == d:
                    whole, n = whole + 1, 0
                g = math.gcd(int(n), d) if n else d
                frac = ("%d/%d" % (n // g, d // g)) if n else ""
                text = ("%d %s" % (whole, frac) if whole and frac else frac or "%d" % whole).strip()
                return ("-" if value < 0 else "") + text
        return ("%%.%df" % self.decimals) % value

    def len(self, mm, power=1):
        symbol, size = LENGTHS[self.length]
        text = self._number(mm / size ** power, self.length, power) + symbol + ("^%d" % power if power > 1 else "")
        if self.dual and self.dual in LENGTHS and self.dual != self.length:
            s2, z2 = LENGTHS[self.dual]
            text += " (%s%s%s)" % (self._number(mm / z2 ** power, self.dual, power), s2, "^%d" % power if power > 1 else "")
        return text

    def angle(self, radians):
        if self.degrees:
            return ("%%.%df" % self.angle_decimals) % math.degrees(radians) + "°"
        return ("%%.%df" % self.angle_decimals) % radians + "rad"

    def point(self, p):
        return "%s, %s, %s" % (self.len(p.x), self.len(p.y), self.len(p.z))


# ------------------------------------------------------------------ geometry
def _circle(edge):
    curve = getattr(edge, "Curve", None)
    return curve if type(curve).__name__ == "Circle" else None


def _line(edge):
    curve = getattr(edge, "Curve", None)
    return curve if type(curve).__name__ in ("Line", "LineSegment") else None


def _plane(face):
    surface = getattr(face, "Surface", None)
    if type(surface).__name__ != "Plane":
        return None
    n = face.normalAt(0, 0)
    return App.Vector(n).normalize()


def _full(edge):
    return edge.isClosed()


def _direction(shape):
    """Unit direction of a straight edge, else None."""
    if shape.ShapeType == "Edge" and _line(shape) is not None:
        d = shape.Vertexes[-1].Point - shape.Vertexes[0].Point
        return d.normalize() if d.Length > TOL else None
    return None


def _anchor(shape, mode):
    """The point a circle or arc is measured from in Center to Center mode, else None."""
    if mode == ARC_MODES[0] and shape.ShapeType == "Edge" and _circle(shape) is not None:
        return _circle(shape).Center
    if mode == ARC_MODES[0] and shape.ShapeType == "Face" and type(shape.Surface).__name__ == "Cylinder":
        return None     # a cylinder's axis is a line: minimum distance is the honest number
    if shape.ShapeType == "Vertex":
        return shape.Point
    return None


def _cyl_face(shape):
    return shape.ShapeType == "Face" and type(shape.Surface).__name__ == "Cylinder"


def _axis_edge(face):
    ""
    s = face.Surface
    c, n = V(s.Center), V(s.Axis).normalize()
    reach = max(face.BoundBox.DiagonalLength, 1.0) * 1000.0
    return Part.LineSegment(c - n * reach, c + n * reach).toShape()


def _farthest(a, b):
    """Maximum distance between two shapes: across circles through their centres, else vertices."""
    ca, cb = _circle(a) if a.ShapeType == "Edge" else None, _circle(b) if b.ShapeType == "Edge" else None
    if ca is not None and cb is not None and _full(a) and _full(b):
        d = cb.Center - ca.Center
        if abs(d.dot(ca.Axis)) < TOL and abs(d.dot(cb.Axis)) < TOL:     # same plane: along the centre line
            u = d.normalize() if d.Length > TOL else V(1, 0, 0)
            return ca.Center - u * ca.Radius, cb.Center + u * cb.Radius
        def far_on_a(q):        # the point of circle a farthest from q (exact)
            r = q - ca.Center
            r = r - ca.Axis * r.dot(ca.Axis)
            u = r.normalize() if r.Length > TOL else (ca.XAxis if hasattr(ca, "XAxis") else V(1, 0, 0))
            return ca.Center - u * ca.Radius
        qs = [b.valueAt(b.FirstParameter + (b.LastParameter - b.FirstParameter) * i / 360.0) for i in range(360)]
        return max(((far_on_a(q), q) for q in qs), key=lambda pq: (pq[1] - pq[0]).Length)
    pa = [v.Point for v in a.Vertexes] or [a.CenterOfMass]
    pb = [v.Point for v in b.Vertexes] or [b.CenterOfMass]
    if ca is not None and _full(a):
        pa = [a.valueAt(a.FirstParameter + (a.LastParameter - a.FirstParameter) * i / 72.0) for i in range(72)]
    if cb is not None and _full(b):
        pb = [b.valueAt(b.FirstParameter + (b.LastParameter - b.FirstParameter) * i / 72.0) for i in range(72)]
    best = max(((p, q) for p in pa for q in pb), key=lambda pq: (pq[1] - pq[0]).Length)
    return best


def _project(delta, normal):
    if normal is None:
        return delta
    n = V(normal).normalize()
    return delta - n * delta.dot(n)


def _loops(edges):
    """Closed loops of point indices from boundary edges (i, j)."""
    nxt = {}
    for i, j in edges:
        nxt.setdefault(i, []).append(j)
    loops = []
    while nxt:
        start = next(iter(nxt))
        loop, cur = [start], start
        while True:
            outs = nxt.get(cur)
            if not outs:
                break
            j = outs.pop()
            if not outs:
                del nxt[cur]
            if j == start:
                break
            loop.append(j)
            cur = j
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def projected_area(shapes, normal, deflection=None):
    ""



    got = shadow(shapes, normal, deflection)
    return got[0].Area if got is not None else 0.0


def shadow(shapes, normal, deflection=None):
    """The flat shadow of shapes on the plane square to normal, as (shape, u, w): the shape lies in
    the XY plane, in the plane's (u, w) axes (a point p of the model is at (p.u, p.w)). None when
    there is nothing to cast one."""
    n = V(normal).normalize()
    faces = []
    for s in shapes:
        faces += [s] if s.ShapeType == "Face" else list(s.Faces)
    if not faces:
        return None
    size = max(Part.makeCompound(faces).BoundBox.DiagonalLength, 1e-6)
    tol = deflection or size * 0.002
    solid = any(s.Solids for s in shapes)
    axis = V(1, 0, 0) if abs(n.x) < 0.9 else V(0, 1, 0)
    u = n.cross(axis).normalize()
    w = n.cross(u).normalize()
    pieces = []
    for f in faces:
        try:
            pts, tris = f.tessellate(tol)
        except Exception:
            continue
        q = [V(p.dot(u), p.dot(w), 0) for p in pts]
        signs = []
        for a, b, c in tris:
            z = (q[b] - q[a]).cross(q[c] - q[a]).z
            signs.append(0 if abs(z) < 1e-12 else (1 if z > 0 else -1))
        # a body's faces: only the side that looks at the plane casts the shadow (the far side the
        # same again); a surface or a lone face: both sides
        if solid:
            # the side that looks at the plane is the one whose normal points at it
            try:
                uv = f.Surface.parameter(f.CenterOfMass)
                facing = f.normalAt(*uv).dot(n)
            except Exception:
                facing = 1.0
            groups = [[t for t, sg in zip(tris, signs) if sg == 1], [t for t, sg in zip(tris, signs) if sg == -1]]
            front = groups[0] if facing >= 0 else groups[1]
            if not front:
                continue
            groups = [front]
        else:
            groups = [[t for t, sg in zip(tris, signs) if sg == 1], [t for t, sg in zip(tris, signs) if sg == -1]]
        for group in groups:
            if not group:
                continue
            count = {}
            for a, b, c in group:
                for i, j in ((a, b), (b, c), (c, a)):
                    k = (min(i, j), max(i, j))
                    count[k] = count.get(k, 0) + 1
            edges = []
            for a, b, c in group:
                for i, j in ((a, b), (b, c), (c, a)):
                    if count[(min(i, j), max(i, j))] == 1:
                        edges.append((i, j))
            wires = []
            for loop in _loops(edges):
                poly = [q[i] for i in loop]
                try:
                    wires.append(Part.makePolygon(poly + [poly[0]]))
                except Exception as _fw_err:
                    _fw_log("measure.py:304", _fw_err)
            if not wires:
                continue
            try:
                piece = Part.makeFace(wires, "Part::FaceMakerBullseye")
            except Exception:
                try:
                    piece = Part.makeFace(wires, "Part::FaceMakerCheese")
                except Exception:
                    continue
            if piece.Area > 1e-12:
                pieces.append(piece)
    if not pieces:
        return None
    try:
        flat = pieces[0].multiFuse(pieces[1:]) if len(pieces) > 1 else pieces[0]
        try:
            flat = flat.removeSplitter()
        except Exception as _fw_err:
            _fw_log("measure.py:323", _fw_err)
        return flat, u, w
    except Exception:
        return max(pieces, key=lambda p: p.Area), u, w


def measure(shapes, units=None, arc_mode=ARC_MODES[0], xyz=False, projection=None, points=None):
    ""

    lines, draw = measure_shapes(shapes, units, arc_mode, xyz, projection, points)
    if projection is not None and points is None and shapes and \
            all(s.ShapeType in ("Face", "Shell", "Solid", "CompSolid", "Compound") and s.Faces for s in shapes):
        try:
            area = projected_area(shapes, projection)
            lines.append(("Projected area", (units or Units()).len(area, 2)))
        except Exception as error:
            App.Console.PrintLog("FreeCAD Measure: projected area: %s\n" % error)
    return lines, draw


REF_REACH = 1.0e5      # mm: the size a reference plane or axis is measured over (it has no edges of its own)


def _reference(shape):
    """("plane", point, normal) or ("axis", point, direction) for a reference plane or axis (an origin or
    datum plane or axis: an unbounded face or line, no vertices), else None (refmeasure-fix01)."""
    try:
        if shape.ShapeType == "Face" and type(shape.Surface).__name__ == "Plane" and \
                (not shape.Vertexes or shape.Area > 1e12):
            s = shape.Surface
            return "plane", V(s.Position), V(s.Axis).normalize()
        if shape.ShapeType == "Edge" and _line(shape) is not None and (not shape.Vertexes or shape.Length > 1e12):
            c = shape.Curve
            return "axis", V(c.Location), V(c.Direction).normalize()
    except Exception as _fw_err:
        _fw_log("measure.py:reference", _fw_err)
    return None


def _bounded(ref, near):
    ""

    kind, p, n = ref
    w = near - p
    if kind == "plane":
        c = near - n * w.dot(n)
        u = n.cross(V(1, 0, 0) if abs(n.x) < 0.9 else V(0, 1, 0)).normalize()
        v = n.cross(u)
        r = REF_REACH
        corners = [c + u * r + v * r, c - u * r + v * r, c - u * r - v * r, c + u * r - v * r]
        return Part.Face(Part.makePolygon(corners + corners[:1]))
    c = p + n * w.dot(n)
    return Part.LineSegment(c - n * REF_REACH, c + n * REF_REACH).toShape()


def _centre(shape, ref=None):
    if ref is not None:
        return ref[1]
    try:
        return shape.BoundBox.Center
    except Exception:
        return V()


def measure_shapes(shapes, units=None, arc_mode=ARC_MODES[0], xyz=False, projection=None, points=None):
    """Lines of (name, text) and the segments to draw [(p1, p2, label, rgb)] for picked shapes.

    shapes: global shape elements. points: picked points, used instead in Point-to-Point mode.
    projection: None, or the normal of the plane distances are projected onto."""
    units = units or Units()
    lines, draw = [], []
    if points is not None:
        shapes = [Part.Vertex(p) for p in points]
    if not shapes:
        return lines, draw
    refs = [_reference(s) for s in shapes]
    if any(refs):

        # show, and with other items it stands for the whole plane or line (refmeasure-fix01)
        if len(shapes) == 1:
            return lines, draw
        shapes = list(shapes)
        for i, ref in enumerate(refs):
            if ref is not None:
                others = [_centre(s, r) for j, (s, r) in enumerate(zip(shapes, refs)) if j != i]
                shapes[i] = _bounded(ref, others[0] if others else ref[1])
    kinds = {s.ShapeType for s in shapes}
    if len(shapes) == 1:
        s = shapes[0]
        if s.ShapeType == "Vertex":
            p = s.Point
            lines += [("X", units.len(p.x)), ("Y", units.len(p.y)), ("Z", units.len(p.z))]
        elif s.ShapeType == "Edge":
            c = _circle(s)
            if c is not None and _full(s):
                lines += [("Diameter", units.len(2 * c.Radius)), ("Center", units.point(c.Center)),
                          ("Circumference", units.len(s.Length))]
            elif c is not None:
                p0, p1 = s.Vertexes[0].Point, s.Vertexes[-1].Point
                lines += [("Arc length", units.len(s.Length)), ("Chord length", units.len((p1 - p0).Length)),
                          ("Radius", units.len(c.Radius)), ("Center", units.point(c.Center))]
            else:
                lines.append(("Length", units.len(s.Length)))
        elif s.ShapeType == "Face":
            lines.append(("Area", units.len(s.Area, 2)))
            if type(s.Surface).__name__ == "Cylinder":
                lines.append(("Diameter", units.len(2 * s.Surface.Radius)))
            elif _plane(s) is not None:
                lines.append(("Perimeter", units.len(sum(e.Length for e in s.OuterWire.Edges))))
        elif s.ShapeType in ("Solid", "Shell", "Compound", "CompSolid"):
            lines += [("Volume", units.len(s.Volume, 3)), ("Surface area", units.len(s.Area, 2))]
        return lines, draw
    if len(shapes) > 2:
        if any(refs):
            lines.append(("Items", "%d picked: pick two to measure between them" % len(shapes)))
        elif kinds == {"Edge"}:
            lines.append(("Total Length", units.len(sum(s.Length for s in shapes))))
        elif kinds == {"Face"}:
            lines.append(("Total Area", units.len(sum(s.Area for s in shapes), 2)))
        else:
            lines.append(("Items", "%d picked: pick two to measure between them" % len(shapes)))
        return lines, draw
    a, b = shapes
    total = []
    if any(refs):
        pass            # a reference plane or axis has no length or area of its own
    elif kinds == {"Edge"}:
        total.append(("Total Length", units.len(a.Length + b.Length)))
    elif kinds == {"Face"}:
        total.append(("Total Area", units.len(a.Area + b.Area, 2)))
    # angle / normal distance between straight edges and flat faces
    da, db = _direction(a), _direction(b)
    na = _plane(a) if a.ShapeType == "Face" else None
    nb = _plane(b) if b.ShapeType == "Face" else None
    angle = normal_gap = None
    if da is not None and db is not None:
        cosine = abs(da.dot(db))
        if cosine > 1 - 1e-9:
            normal_gap = _line_gap(a, b, da)
        else:
            angle = math.acos(max(-1.0, min(1.0, da.dot(db))))
    elif na is not None and nb is not None:
        cosine = abs(na.dot(nb))
        if cosine > 1 - 1e-9:
            normal_gap = abs((b.Vertexes[0].Point - a.Vertexes[0].Point).dot(na))
        else:
            angle = math.acos(max(-1.0, min(1.0, na.dot(nb))))
    elif (da is not None and nb is not None) or (db is not None and na is not None):
        d, n = (da, nb) if da is not None else (db, na)
        if abs(d.dot(n)) < 1e-9:
            line, face = (a, b) if da is not None else (b, a)
            normal_gap = abs((line.Vertexes[0].Point - face.Vertexes[0].Point).dot(n))
        else:
            angle = math.asin(min(1.0, abs(d.dot(n))))
    # the distance and the two points it runs between
    pa, pb = _anchor(a, arc_mode), _anchor(b, arc_mode)
    circles = any(s.ShapeType == "Edge" and _circle(s) is not None for s in (a, b))
    cyls = [s for s in (a, b) if _cyl_face(s)]
    label = None
    if cyls and arc_mode in (ARC_MODES[0], ARC_MODES[2]):

        # ("Distance between cylinder axes" for two of them, the callout "Center Dist"); Maximum Distance
        # adds the radii; Minimum Distance stays the surfaces' gap
        sa = _axis_edge(a) if _cyl_face(a) else a
        sb = _axis_edge(b) if _cyl_face(b) else b
        dist, pairs, _info = sa.distToShape(sb)
        p, q = pairs[0]
        if arc_mode == ARC_MODES[2]:
            u = (q - p).normalize() if (q - p).Length > TOL else V(1, 0, 0)
            p = p - u * (a.Surface.Radius if _cyl_face(a) else 0.0)
            q = q + u * (b.Surface.Radius if _cyl_face(b) else 0.0)
            name = "Maximum Distance"
        else:
            name, label = "Distance", "Center Distance"
            if len(cyls) == 2:
                lines.append(("Distance between cylinder axes", units.len(dist)))
    elif arc_mode == ARC_MODES[2] and circles:
        p, q = _farthest(a, b)
        name = "Maximum Distance"
    elif pa is not None and pb is not None:
        p, q = pa, pb
        name = "Center Distance" if circles and arc_mode == ARC_MODES[0] and \
            not (a.ShapeType == "Vertex" and b.ShapeType == "Vertex") else "Distance"
    elif pa is not None or pb is not None:
        anchor, other = (pa, b) if pa is not None else (pb, a)
        holder = a if pa is not None else b
        dist, pairs, _info = Part.Vertex(anchor).distToShape(other)
        p, q = (anchor, pairs[0][1]) if pa is not None else (pairs[0][1], anchor)

        name = "Center Distance" if holder.ShapeType == "Edge" and _circle(holder) is not None else "Distance"
    else:
        dist, pairs, _info = a.distToShape(b)
        p, q = pairs[0]
        name = "Minimum Distance" if circles else "Distance"
    delta = _project(q - p, projection)
    shown = delta.Length
    if angle is not None:
        lines.append(("Angle", units.angle(angle)))
    if not (any(refs) and angle is not None and shown < 1e-6):

        lines.append((name if projection is None else name + " (projected)", units.len(shown)))
    if normal_gap is not None and abs(normal_gap - shown) > 1e-6:
        lines.append(("Normal Distance", units.len(normal_gap)))
    end = p + delta
    if shown > TOL:
        draw.append((p, end, "%s: %s" % (SHORT.get(label or name, label or name), units.len(shown)), (0.9, 0.45, 0.0)))
    if xyz:
        lines += [("Delta X", units.len(abs(delta.x))), ("Delta Y", units.len(abs(delta.y))),
                  ("Delta Z", units.len(abs(delta.z)))]
        corner1 = p + V(delta.x, 0, 0)
        corner2 = corner1 + V(0, delta.y, 0)
        for s, e, value, rgb, axis in ((p, corner1, delta.x, (0.85, 0.1, 0.1), "dX"),
                                       (corner1, corner2, delta.y, (0.1, 0.65, 0.1), "dY"),
                                       (corner2, end, delta.z, (0.1, 0.25, 0.9), "dZ")):
            if abs(value) > TOL:
                draw.append((s, e, "%s: %s" % (axis, units.len(abs(value))), rgb))
    return lines + total, draw


def summary_text(lines):
    """The one line shown while the box is collapsed: the first two results, and with XYZ on the
    value with all three deltas (never Delta X alone)."""
    if not lines:
        return ""
    deltas = [(n, v) for n, v in lines if n in ("Delta X", "Delta Y", "Delta Z")]
    if deltas:
        main = [(n, v) for n, v in lines if (n, v) not in deltas][:1]
        return "  ".join(["%s: %s" % (n, v) for n, v in main] +
                         ["d%s: %s" % (n[-1], v) for n, v in deltas])
    return "  ".join("%s: %s" % (n, v) for n, v in lines[:2])


def callout(shape, lines):
    ""
    if shape is None or not lines:
        return None
    t = shape.ShapeType
    try:
        if t == "Vertex":
            at = shape.Point
        elif t == "Edge":
            c = _circle(shape)
            at = shape.valueAt(shape.FirstParameter + 0.5 * (shape.LastParameter - shape.FirstParameter))
        elif t == "Face":
            u0, u1, v0, v1 = shape.ParameterRange
            at = shape.valueAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
            if not shape.isInside(at, 1e-6, True):
                at = shape.CenterOfMass
        else:
            at = shape.BoundBox.Center
    except Exception:
        at = shape.BoundBox.Center
    first = lines[0]
    if t == "Vertex":
        text = "X: %s  Y: %s  Z: %s" % tuple(v for _n, v in lines[:3])
    else:
        text = "%s: %s" % first
    return at, text


def outline(shape):
    """Polylines that draw a picked item over the model: an edge, a face's edges, a vertex mark."""
    out = []
    if shape is None:
        return out
    if shape.ShapeType == "Vertex":
        return [[shape.Point, shape.Point]]
    for e in (shape.Edges if shape.ShapeType != "Edge" else [shape]):
        try:
            pts = e.discretize(Deflection=0.05) if e.Length > TOL else []
        except Exception:
            pts = [v.Point for v in e.Vertexes]
        if len(pts) >= 2:
            out.append(pts)
    return out


def _line_gap(a, b, d):
    """Perpendicular distance between two parallel straight edges."""
    w = b.Vertexes[0].Point - a.Vertexes[0].Point
    return (w - d * w.dot(d)).Length


# ------------------------------------------------------------------ picks
def element(doc_name, obj_name, sub):
    """The picked element as a global shape, or None (sketch axes, unknown names)."""
    doc = App.getDocument(doc_name)
    obj = doc.getObject(obj_name) if doc is not None else None
    if obj is None:
        return None
    last = sub.split(".")[-1] if sub else ""
    if last == "RootPoint":
        held = _held(obj, sub[:-len(last)])
        return Part.Vertex(held[1].multVec(App.Vector())) if held is not None else None
    if last in ("H_Axis", "V_Axis") or last.startswith("ExternalEdge") or last.startswith("Constraint"):
        return None
    # a coordinate system (or an Origin) picked as a whole, in the tree or the graphics area: its origin point,

    # Distance (rcuse-fix01). Found through the pick's own path, so a component's placement counts (fix02)
    if not last:
        held = _held(obj, sub)
        if held is not None and held[0].TypeId in CS_TYPES + ("App::Origin",):
            return Part.Vertex(held[1].multVec(App.Vector()))
    try:
        from . import rcmenus
        mid = rcmenus.midpoint_pick(doc_name, obj_name, sub) if last.startswith("Edge") else None
        if mid is not None:
            return Part.Vertex(mid)
    except Exception as _fw_err:
        _fw_log("measure.py:midpoint", _fw_err)
    try:
        shape = Part.getShape(obj, sub, needSubElement=True) if sub else Part.getShape(obj)
    except Exception as _fw_err:
        _fw_log("measure.py:532", _fw_err)
        return None
    return None if shape is None or shape.isNull() else shape


CS_TYPES = ("PartDesign::CoordinateSystem", "App::LocalCoordinateSystem", "Part::LocalCoordinateSystem")


def _held(obj, sub):
    """(the object a pick path ends on, its global matrix), walked through links and other documents
    (an assembly component's part); None when the path does not resolve."""
    try:
        if not sub:
            return obj, obj.getGlobalPlacement().toMatrix()
        found = obj.getSubObject(sub, retType=2)
        if not found or found[0] is None:
            return None
        # the matrix includes obj's own placement; obj's parents (when it is not top level) come on top
        above = obj.getGlobalPlacement().multiply(obj.Placement.inverse()) if hasattr(obj, "Placement") else App.Placement()
        return found[0], above.toMatrix().multiply(found[1])
    except Exception as _fw_err:
        _fw_log("measure.py:held", _fw_err)
        return None


def coordinate_system(doc_name, obj_name, sub):
    """The global placement of a picked coordinate system (the system itself or one of its axes or
    planes), or None."""
    doc = App.getDocument(doc_name)
    obj = doc.getObject(obj_name) if doc is not None else None
    if obj is None:
        return None
    holder = obj
    for part in (sub or "").split(".")[:-1]:
        holder = doc.getObject(part) or holder
    for o in (holder, obj):
        if o.TypeId in CS_TYPES:
            try:
                return o.getGlobalPlacement()
            except Exception:
                return o.Placement
        try:      # an axis or plane of a coordinate system: its owner
            for parent in o.InList:
                if parent.TypeId in CS_TYPES and o in getattr(parent, "OriginFeatures", []):
                    return parent.getGlobalPlacement()
        except Exception as _fw_err:
            _fw_log("measure.py:559", _fw_err)
    return None


def between_systems(a, b, units=None):
    ""


    units = units or Units()
    import math
    d = b.Base - a.Base
    rel = a.Rotation.inverted().multiply(b.Rotation)
    yaw, pitch, roll = rel.getYawPitchRoll()
    lines = [("Distance", units.len(d.Length)), ("dX", units.len(abs(d.x))), ("dY", units.len(abs(d.y))),
             ("dZ", units.len(abs(d.z))),
             ("Angular rotation about X", units.angle(math.radians(roll))),
             ("Angular rotation about Y", units.angle(math.radians(pitch))),
             ("Angular rotation about Z", units.angle(math.radians(yaw))),
             ("Angle", units.angle(rel.Angle))]
    return lines, [(a.Base, b.Base, units.len(d.Length), (0.85, 0.2, 0.2))] if d.Length > 1e-9 else []


def _label(doc_name, obj_name, sub):
    doc = App.getDocument(doc_name)
    obj = doc.getObject(obj_name) if doc is not None else None
    parts = sub.split(".") if sub else []
    holder = obj
    for part in parts[:-1]:
        holder = doc.getObject(part) or holder
    name = holder.Label if holder is not None else obj_name
    return "%s@%s" % (parts[-1], name) if parts and parts[-1] else name


# ------------------------------------------------------------------ graphics
def coin_vec(x, y, z):
    from pivy import coin
    return coin.SbVec3f(x, y, z)



# default bitmap font (a small serif). Drawn as a screen-aligned image so it stays crisp at any zoom.
CALLOUT_FILL = (255, 255, 225)
CALLOUT_EDGE = (96, 96, 96)
CALLOUT_INK = (0, 0, 0)
_LABEL_IMAGES = {}                  # (text, scale) -> (w, h, bytes): pivy cannot read an SoSFImage back


def _label_scale():
    try:
        mw = Gui.getMainWindow()
        return max(1.0, float(mw.devicePixelRatioF())) if mw is not None else 1.0
    except Exception:
        return 1.0


def label_image(text, scale=None):
    """(width, height, RGBA bytes bottom row first) of a boxed callout holding text."""
    scale = _label_scale() if scale is None else scale
    key = (text, scale)
    if key in _LABEL_IMAGES:
        return _LABEL_IMAGES[key]
    font = QtGui.QFont(QtWidgets.QApplication.font())
    font.setPixelSize(max(9, int(round(12 * scale))))
    font.setStyleHint(QtGui.QFont.SansSerif)
    metrics = QtGui.QFontMetrics(font)
    pad_x, pad_y = int(round(5 * scale)), int(round(2 * scale))
    w = metrics.horizontalAdvance(text) + 2 * pad_x + 2
    h = metrics.height() + 2 * pad_y + 2
    img = QtGui.QImage(w, h, QtGui.QImage.Format_RGBA8888)
    img.fill(QtGui.QColor(*CALLOUT_FILL))
    painter = QtGui.QPainter(img)
    try:
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        pen = QtGui.QPen(QtGui.QColor(*CALLOUT_EDGE))
        pen.setWidth(max(1, int(round(scale))))
        painter.setPen(pen)
        painter.drawRect(0, 0, w - 1, h - 1)
        painter.setPen(QtGui.QColor(*CALLOUT_INK))
        painter.setFont(font)
        painter.drawText(QtCore.QRect(0, 0, w, h), QtCore.Qt.AlignCenter, text)
    finally:
        painter.end()
    img = img.mirrored(False, True)      # Coin images start at the bottom row
    bits = img.constBits()
    try:
        data = bytes(bits[:w * h * 4]) if not hasattr(bits, "setsize") else None
    except Exception:
        data = None
    if data is None or len(data) != w * h * 4:
        rows = []
        for y in range(h):
            for x in range(w):
                c = img.pixelColor(x, y)
                rows.append(bytes((c.red(), c.green(), c.blue(), c.alpha())))
        data = b"".join(rows)
    if len(_LABEL_IMAGES) > 200:
        _LABEL_IMAGES.clear()
    _LABEL_IMAGES[key] = (w, h, data)
    return w, h, data


def label_node(text, centred=False):
    """A screen-aligned callout box for the current translation (left-bottom corner, or centred)."""
    from pivy import coin
    w, h, data = label_image(text)
    node = coin.SoImage()
    node.setName("SWMeasureLabel")
    node.image.setValue(coin.SbVec2s(w, h), 4, data)
    if centred:
        node.horAlignment = coin.SoImage.CENTER
        node.vertAlignment = coin.SoImage.HALF
    return node


class _Drawing:
    def __init__(self):
        self.node = None
        self.view = None
        self.callouts = []

    def show(self, segments, callouts=(), outlines=()):
        """segments: [(p, q, text, rgb)] measure lines; callouts: [(point, text)] leader and label
        on the model; outlines: [[points]] measured items drawn in green."""
        self.clear()
        if (not segments and not callouts and not outlines) or Gui.ActiveDocument is None:
            return
        from pivy import coin
        view = Gui.ActiveDocument.ActiveView
        self.callouts = list(callouts)
        root = coin.SoAnnotation()
        root.setName("SWMeasureDrawing")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
        style = coin.SoDrawStyle()
        style.lineWidth = 2
        root.addChild(style)
        for p, q, text, rgb in segments:
            sep = coin.SoSeparator()
            colour = coin.SoBaseColor()
            colour.rgb.setValue(*rgb)
            sep.addChild(colour)
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, 2, [(p.x, p.y, p.z), (q.x, q.y, q.z)])
            sep.addChild(coords)
            sep.addChild(coin.SoLineSet())
            label = coin.SoSeparator()
            move = coin.SoTranslation()
            mid = (p + q) * 0.5
            move.translation.setValue(mid.x, mid.y, mid.z)
            label.addChild(move)
            label.addChild(label_node(text, centred=True))
            sep.addChild(label)
            root.addChild(sep)
        for pts in outlines:
            sep = coin.SoSeparator()
            sep.setName("SWMeasurePicked")
            colour = coin.SoBaseColor()
            colour.rgb.setValue(*picked_rgb())
            sep.addChild(colour)
            thick = coin.SoDrawStyle()
            thick.lineWidth = 3
            thick.pointSize = 8
            sep.addChild(thick)
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
            sep.addChild(coords)
            sep.addChild(coin.SoPointSet() if len(pts) == 2 and (pts[0] - pts[1]).Length < TOL else coin.SoLineSet())
            root.addChild(sep)
        offset = self._offset(view)
        for at, text in callouts:
            sep = coin.SoSeparator()
            sep.setName("SWMeasureCallout")
            colour = coin.SoBaseColor()
            colour.rgb.setValue(0.9, 0.45, 0.0)
            sep.addChild(colour)
            end = at + offset
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, 2, [(at.x, at.y, at.z), (end.x, end.y, end.z)])
            sep.addChild(coords)
            sep.addChild(coin.SoLineSet())
            move = coin.SoTranslation()
            move.translation.setValue(end.x, end.y, end.z)
            sep.addChild(move)
            sep.addChild(label_node(text))
            root.addChild(sep)
        view.getSceneGraph().addChild(root)
        self.node, self.view = root, view

    @staticmethod
    def _offset(view, pixels=45):
        """A leader up and to the right on the screen, about 45 pixels long at the current zoom."""
        try:
            cam = view.getCameraNode()
            rot = cam.orientation.getValue()
            right = V(*rot.multVec(coin_vec(1, 0, 0)).getValue())
            up = V(*rot.multVec(coin_vec(0, 1, 0)).getValue())
            height = view.getSize()[1] or 600
            if hasattr(cam, "height"):
                world = cam.height.getValue()
            else:
                world = 2 * cam.focalDistance.getValue() * math.tan(cam.heightAngle.getValue() / 2)
            k = world / height * pixels
            return (right + up) * (k / math.sqrt(2))
        except Exception:
            return V(5, 5, 5)

    def clear(self):
        if self.node is not None:
            try:
                self.view.getSceneGraph().removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("measure.py:706", _fw_err)
        self.node = self.view = None


# ------------------------------------------------------------------ window
_MODEL_STAMP = [0]
_MODEL_OBSERVER = []


class _ModelObserver(object):
    """Counts the model changes Measure follows (one observer for the session, it only bumps a number)."""
    def _bump(self, *args):
        _MODEL_STAMP[0] += 1
    slotRecomputedDocument = slotDeletedObject = slotUndoDocument = slotRedoDocument = slotDeletedDocument = _bump


def _watch_model():
    if not _MODEL_OBSERVER:
        _MODEL_OBSERVER.append(_ModelObserver())
        App.addDocumentObserver(_MODEL_OBSERVER[0])


def ui_font():
    from .widgets import ui_font as font
    return font()


class _UnitsBox(QtWidgets.QDialog):
    """Measure Units/Precision."""

    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("Measure Units/Precision")
        self.setFont(ui_font())
        form = QtWidgets.QFormLayout(self)
        self.doc = QtWidgets.QRadioButton("Use document settings")
        self.custom = QtWidgets.QRadioButton("Use custom settings")
        form.addRow(self.doc)
        form.addRow(self.custom)
        self.length = QtWidgets.QComboBox()
        self.length.addItems(list(LENGTHS))
        self.decimals = QtWidgets.QSpinBox()
        self.decimals.setRange(0, 8)
        self.angle = QtWidgets.QComboBox()
        self.angle.addItems(["Degrees", "Radians"])
        self.angle_decimals = QtWidgets.QSpinBox()
        self.angle_decimals.setRange(0, 8)
        self.dual_on = QtWidgets.QCheckBox("Use dual units")
        self.dual = QtWidgets.QComboBox()
        self.dual.addItems(list(LENGTHS))
        self.scientific = QtWidgets.QCheckBox("Scientific notation")
        self.fractions = QtWidgets.QCheckBox("Fractions")
        self.denominator = QtWidgets.QSpinBox()
        self.denominator.setRange(2, 128)
        self.round_fraction = QtWidgets.QCheckBox("Round to nearest fraction")
        form.addRow("Length unit:", self.length)
        form.addRow(self.dual_on, self.dual)
        form.addRow(self.scientific)
        form.addRow("Decimal places:", self.decimals)
        form.addRow(self.fractions, self.denominator)
        form.addRow(self.round_fraction)
        form.addRow("Angular unit:", self.angle)
        form.addRow("Decimal places:", self.angle_decimals)
        u = window.units()
        p0 = window.params()
        self.dual_on.setChecked(bool(p0.GetString("Dual", "")))
        self.dual.setCurrentText(p0.GetString("Dual", "") or "Inches")
        self.scientific.setChecked(p0.GetBool("Scientific", False))
        self.fractions.setChecked(p0.GetInt("Denominator", 0) > 0)
        self.denominator.setValue(p0.GetInt("Denominator", 0) or 16)
        self.round_fraction.setChecked(p0.GetBool("RoundFraction", False))
        custom = window.params().GetBool("CustomUnits", False)
        (self.custom if custom else self.doc).setChecked(True)
        self.length.setCurrentText(u.length)
        self.decimals.setValue(u.decimals)
        self.angle.setCurrentIndex(0 if u.degrees else 1)
        self.angle_decimals.setValue(u.angle_decimals)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.length.currentTextChanged.connect(self._enable)
        self._enable()
        # no greyed controls (Ati's rule): the custom settings stay live, and changing one picks
        # Use custom settings
        for sig in (self.length.currentTextChanged, self.decimals.valueChanged, self.angle.currentIndexChanged,
                    self.angle_decimals.valueChanged, self.dual_on.toggled, self.dual.currentTextChanged,
                    self.scientific.toggled, self.fractions.toggled, self.denominator.valueChanged,
                    self.round_fraction.toggled):
            sig.connect(self._to_custom)
        self.dual.currentTextChanged.connect(lambda *_: self.dual_on.setChecked(True))
        self.denominator.valueChanged.connect(lambda *_: self.fractions.setChecked(True))

    def _to_custom(self, *args):
        self.custom.setChecked(True)

    def _enable(self, *args):
        # fractions are for inches and feet: shown only with those
        imperial = self.length.currentText() in ("Inches", "Feet")
        for w in (self.fractions, self.denominator, self.round_fraction):
            w.setVisible(imperial)

    def store(self, p):
        p.SetBool("CustomUnits", self.custom.isChecked())
        p.SetString("Length", self.length.currentText())
        p.SetInt("Decimals", self.decimals.value())
        p.SetBool("Degrees", self.angle.currentIndex() == 0)
        p.SetInt("AngleDecimals", self.angle_decimals.value())
        p.SetString("Dual", self.dual.currentText() if self.dual_on.isChecked() else "")
        p.SetBool("Scientific", self.scientific.isChecked())
        p.SetInt("Denominator", self.denominator.value() if self.fractions.isChecked() else 0)
        p.SetBool("RoundFraction", self.round_fraction.isChecked())


class MeasureWindow(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(Gui.getMainWindow(), QtCore.Qt.Tool)
        self.setObjectName("SWMeasure")
        doc = App.ActiveDocument
        self._doc_name = doc.Name if doc is not None else None
        self.setWindowTitle("Measure - %s" % (doc.Label if doc is not None else ""))
        self.setFont(ui_font())
        self.items = []         # (doc, obj, sub, point)
        self.history = []
        self.plane = None       # (label, normal) for Projected On: Select Face/Plane
        self.busy = False
        self.pending_clear = False
        self.added = False
        self.drawing = _Drawing()
        p = self.params()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(2)
        layout.addLayout(bar)

        def button(name, text, tip, checkable=False):
            b = QtWidgets.QToolButton(self)
            b.setObjectName("SWMeasure" + name)
            b.setText(text)
            b.setToolTip(tip)
            icon = _bar_icon(name)
            if icon is not None:

                b.setIcon(icon)
                b.setIconSize(QtCore.QSize(20, 20))
                b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
            b.setCheckable(checkable)
            b.setAutoRaise(True)
            bar.addWidget(b)
            return b

        self.arc = button("ArcCircle", "Arc/Circle", "Arc/Circle Measurements")
        self.arc.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(self.arc)
        self.arc_actions = QtGui.QActionGroup(self)
        for mode in ARC_MODES:
            a = menu.addAction(mode)
            a.setCheckable(True)
            a.setChecked(mode == p.GetString("ArcMode", ARC_MODES[0]))
            self.arc_actions.addAction(a)
        if self.arc_actions.checkedAction() is None:
            self.arc_actions.actions()[0].setChecked(True)
        self.arc_actions.triggered.connect(self._arc_mode)
        self.arc.setMenu(menu)
        self.units_button = button("Units", "Units", "Units/Precision")
        self.units_button.clicked.connect(self._units)
        self.xyz = button("XYZ", "XYZ", "Show XYZ Measurements", True)
        self.xyz.setChecked(p.GetBool("ShowXYZ", False))
        self.xyz.toggled.connect(self._options)
        self.p2p = button("PointToPoint", "Point-to-Point", "Point-to-Point: measures between the points you click", True)
        self.p2p.toggled.connect(self._point_mode)
        self.proj = button("ProjectedOn", "Projected On", "Projected On")
        self.proj.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        pmenu = QtWidgets.QMenu(self.proj)
        self.proj_actions = QtGui.QActionGroup(self)
        for mode in PROJECTIONS:
            a = pmenu.addAction(mode)
            a.setCheckable(True)
            a.setChecked(mode == PROJECTIONS[0])
            self.proj_actions.addAction(a)
        self.proj_actions.triggered.connect(self._projection)
        self.proj.setMenu(pmenu)
        self.hist = button("History", "History", "Measurement History")
        self.hist.clicked.connect(self._show_history)
        self.sensor = button("Sensor", "Create Sensor", "Create Sensor: a sensor that watches this measurement")
        self.sensor.clicked.connect(self.create_sensor)
        bar.addStretch(1)

        self.pin = button("Pin", "Pin", "Keep Measure open when another command starts", True)
        try:
            from . import icons
            pin_icon = QtGui.QIcon()
            pin_icon.addPixmap(icons.family("PIN_NORMAL").pixmap(20, 20), QtGui.QIcon.Normal, QtGui.QIcon.Off)
            pin_icon.addPixmap(icons.family("PIN_ACTIVE").pixmap(20, 20), QtGui.QIcon.Normal, QtGui.QIcon.On)
            if not pin_icon.isNull():
                self.pin.setIcon(pin_icon)
                self.pin.setIconSize(QtCore.QSize(20, 20))
                self.pin.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        except Exception as _fw_err:
            _fw_log("measure.py:pin", _fw_err)
        self.pin.setChecked(p.GetBool("Pinned", False))
        self.pin.toggled.connect(lambda on: self.params().SetBool("Pinned", bool(on)))
        self.expand = button("Expand", "", "Expand/Collapse the results", True)
        self.expand.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.expand.setArrowType(QtCore.Qt.DownArrow)
        self.expand.toggled.connect(self._expanded)
        self.picks = QtWidgets.QListWidget(self)
        self.picks.setObjectName("SWMeasurePicks")
        self.picks.setMaximumHeight(70)
        layout.addWidget(self.picks)
        self.note = QtWidgets.QLabel("", self)
        self.note.setObjectName("SWMeasureNote")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.result = QtWidgets.QTextEdit(self)
        self.result.setObjectName("SWMeasureResult")
        self.result.setReadOnly(True)
        self.result.setMinimumHeight(110)
        layout.addWidget(self.result, 1)
        self.summary = QtWidgets.QLabel("", self)
        self.summary.setObjectName("SWMeasureSummary")
        layout.addWidget(self.summary)
        self.resize(380, 260)
        self.lines = []
        self.expand.setChecked(p.GetBool("Expanded", False))
        self._expanded(self.expand.isChecked())
        self._place()
        self.refresh()
        Gui.Selection.addObserver(self)

        self._sensor_until = 0.0
        self._pm_before = self._pm_open()
        self._pin_timer = QtCore.QTimer(self)
        self._pin_timer.setInterval(400)
        self._pin_timer.timeout.connect(self._watch_commands)
        self._pin_timer.start()
        # what was picked before the command counts
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub, pnt in zip(sel.SubElementNames or [""], sel.PickedPoints or [None] * max(1, len(sel.SubElementNames))):
                self.items.append((sel.DocumentName, sel.ObjectName, sub, pnt))
        self.refresh()

    def _pm_open(self):
        try:
            from . import cmdhelp
            return bool(cmdhelp.open_pm_title())
        except Exception:
            return False

    def _follow_document(self):
        """Another part made active: the window measures in that one (its title, its picks and units)."""
        doc = App.ActiveDocument
        if doc is None:
            return      # only for a moment (a window closing, the Start page): the picks stay
        name = doc.Name
        if name == getattr(self, "_doc_name", name):
            return
        self._doc_name = name
        self.setWindowTitle("Measure - %s" % (doc.Label if doc is not None else ""))
        self.items = [i for i in self.items if i[0] == name]
        self.plane = None
        self.refresh()

    def _follow_model(self):
        ""


        _watch_model()
        stamp = _MODEL_STAMP[0]
        if stamp == getattr(self, "_model_stamp", stamp):
            self._model_stamp = stamp
            return
        self._model_stamp = stamp
        keep = []
        for item in self.items:
            doc_name, obj_name, sub, _p = item
            doc = App.getDocument(doc_name) if doc_name in App.listDocuments() else None
            obj = doc.getObject(obj_name) if doc is not None else None
            if obj is None or getattr(obj, "Removing", False):
                continue
            last = sub.split(".")[-1] if sub else ""
            if (last[:4] in ("Face", "Edge") or last.startswith("Vertex")) and element(doc_name, obj_name, sub) is None:
                continue
            keep.append(item)
        if len(keep) != len(self.items):
            self.items = keep
            self._sync()
        else:
            self.refresh()

    def _watch_commands(self):
        import time
        try:
            self._follow_document()
        except Exception as _fw_err:
            _fw_log("measure.py:follow document", _fw_err)
        try:
            if self.items and not self.busy:
                self._follow_model()
        except Exception as _fw_err:
            _fw_log("measure.py:follow model", _fw_err)
        now = self._pm_open()
        started = now and not self._pm_before
        self._pm_before = now
        if started and not self.pin.isChecked() and time.time() > self._sensor_until:
            self.close()

    # settings
    def params(self):
        return App.ParamGet(PARAMS)

    def units(self):
        p = self.params()
        if not p.GetBool("CustomUnits", False):
            return Units.document()
        return Units(p.GetString("Length", "Millimeters"), p.GetInt("Decimals", 2),
                     p.GetBool("Degrees", True), p.GetInt("AngleDecimals", 2), p.GetBool("Scientific", False),
                     p.GetString("Dual", "") or None, p.GetInt("Denominator", 0), p.GetBool("RoundFraction", False))

    def arc_mode(self):
        a = self.arc_actions.checkedAction()
        return a.text() if a is not None else ARC_MODES[0]

    def projection_mode(self):
        a = self.proj_actions.checkedAction()
        return a.text() if a is not None else PROJECTIONS[0]

    def _expanded(self, on):
        ""
        self.params().SetBool("Expanded", bool(on))
        self.expand.setArrowType(QtCore.Qt.UpArrow if on else QtCore.Qt.DownArrow)
        for w in (self.picks, self.result):
            w.setVisible(bool(on))
        self.summary.setVisible(not on)
        self.adjustSize()
        if not on:
            self.resize(max(self.minimumSizeHint().width(), 380), self.minimumSizeHint().height())
        else:
            self.resize(max(self.width(), 380), max(self.height(), 260))

    def _arc_mode(self, *args):
        self.params().SetString("ArcMode", self.arc_mode())
        self.refresh()

    def _options(self, *args):
        self.params().SetBool("ShowXYZ", self.xyz.isChecked())
        self.refresh()

    def _point_mode(self, *args):
        self._clear_items()

    def _projection(self, *args):
        self.plane = None
        self.refresh()

    def _units(self):
        box = _UnitsBox(self)
        if box.exec():
            box.store(self.params())
            self.refresh()

    def _show_history(self):
        box = QtWidgets.QDialog(self)
        box.setWindowTitle("Measurement History")
        lay = QtWidgets.QVBoxLayout(box)
        text = QtWidgets.QPlainTextEdit(box)
        text.setObjectName("SWMeasureHistoryText")
        text.setReadOnly(True)
        text.setPlainText("\n\n".join(self.history) or "No measurements yet.")
        lay.addWidget(text)
        box.resize(360, 300)
        box.show()
        self._history_box = box

    def _place(self):
        mw = Gui.getMainWindow()
        try:
            # stock FreeCAD 1.1: findChildren(QOpenGLWidget) finds nothing from Python
            views = [w for w in mw.findChildren(QtWidgets.QWidget)
                     if w.inherits("QOpenGLWidget") and w.isVisible() and w.width() > 300]
        except Exception:
            views = []
        if views:
            corner = views[0].mapToGlobal(QtCore.QPoint(20, 40))
            self.move(corner)

    # selection: every click adds; a click on empty space starts again
    def addSelection(self, doc, obj, sub, pnt):
        if self.busy:
            return
        point = V(*pnt) if pnt else None
        if self.projection_mode() == PROJECTIONS[2] and self.plane is None:
            shape = element(doc, obj, sub)
            if shape is not None and shape.ShapeType == "Face" and _plane(shape) is not None:
                self.plane = (_label(doc, obj, sub), _plane(shape))
                self.pending_clear = False
                QtCore.QTimer.singleShot(0, self._sync)
                return
        key = (doc, obj, sub)
        found = [i for i in self.items if i[:3] == key]
        if found and not self.p2p.isChecked():
            self.items.remove(found[0])
        else:
            self.items.append((doc, obj, sub, point))
        self.added = True
        QtCore.QTimer.singleShot(0, self._settle)

    def removeSelection(self, doc, obj, sub):
        if self.busy:
            return
        self.items = [i for i in self.items if i[:3] != (doc, obj, sub)]
        from . import safe_later as _sl; _sl.later(0, self.refresh, self, "picks")

    def clearSelection(self, doc):
        if self.busy:
            return
        self.pending_clear = True
        self.added = False
        QtCore.QTimer.singleShot(0, self._settle)

    def setSelection(self, doc):
        pass

    def _settle(self):
        if self.pending_clear and not self.added:
            self.items = []
        self.pending_clear = False
        self.added = False
        self._sync()

    def _sync(self):
        """FreeCAD's selection shows every item the window measures."""
        self.busy = True
        try:
            Gui.Selection.clearSelection()
            for doc, obj, sub, point in self.items:
                try:
                    if point is not None:
                        Gui.Selection.addSelection(doc, obj, sub, point.x, point.y, point.z)
                    else:
                        Gui.Selection.addSelection(doc, obj, sub)
                except Exception as _fw_err:
                    _fw_log("measure.py:1035", _fw_err)
        finally:
            self.busy = False
        self.refresh()

    def _clear_items(self):
        self.items = []
        self._sync()

    # results
    def refresh(self):
        units = self.units()
        self.picks.clear()
        shapes, points = [], []
        for doc, obj, sub, point in self.items:
            self.picks.addItem(_label(doc, obj, sub))
            shape = element(doc, obj, sub)
            if shape is not None:
                shapes.append(shape)
            if point is not None:
                points.append(point)
        mode = self.projection_mode()
        normal = None
        if mode == PROJECTIONS[1] and Gui.ActiveDocument is not None:
            normal = V(*Gui.ActiveDocument.ActiveView.getViewDirection())
        elif mode == PROJECTIONS[2]:
            normal = self.plane[1] if self.plane is not None else None
        note = ""
        if mode == PROJECTIONS[2]:
            note = "Projected on %s" % self.plane[0] if self.plane else "Select a flat face or plane to project on."
        elif mode == PROJECTIONS[1]:
            note = "Projected on the screen"
        try:
            from . import pmprompts
            if self.items and pmprompts.graphics_section():

                note = (note + "\n" if note else "") + pmprompts.MEASURE_IN_SECTION
        except Exception as _fw_err:
            _fw_log("measure.py:1073", _fw_err)
        self.note.setText(note)
        self.note.setVisible(bool(note))
        callouts = []
        systems = [coordinate_system(doc, obj, sub) for doc, obj, sub, _p in self.items]
        try:
            if len(self.items) == 2 and None not in systems and not self.p2p.isChecked():
                lines, draw = between_systems(systems[0], systems[1], units)
            else:
                lines, draw = measure(shapes, units, self.arc_mode(), self.xyz.isChecked(), normal,
                                      points if self.p2p.isChecked() else None)
            if len(shapes) == 1 and not self.p2p.isChecked():
                c = callout(shapes[0], lines)
                if c is not None:
                    callouts.append(c)
        except Exception as error:
            lines, draw = [("Could not measure", str(error))], []
        outlines = [pts for sh in shapes for pts in outline(sh)]
        self.lines = lines
        if lines:
            html = "<br>".join("<b>%s:</b> %s" % (name, value) for name, value in lines)
            text = "\n".join("%s: %s" % (name, value) for name, value in lines)
            if not self.history or self.history[-1] != text:
                self.history.append(text)
        else:
            html = "Select items in the graphics area to measure them." if not self.p2p.isChecked() else \
                "Click two points on the model."
        self.result.setHtml(html)
        self.summary.setText(summary_text(lines))
        self.drawing.show(draw, callouts, outlines)

    def create_sensor(self, name=None, operator="Is greater than", limit1=None, limit2=0.0, ask=True):
        ""

        import time
        self._sensor_until = time.time() + 6.0       # the sensor's own box is no "other command"
        numeric = [(n, v) for n, v in self.lines if Units().value(v) is not None]
        if not self.items or not numeric:
            self.note.setText("Measure something first, then Create Sensor.")
            self.note.setVisible(True)
            return None
        if ask:
            box = QtWidgets.QDialog(self)
            box.setWindowTitle("Sensor - Measurement")
            form = QtWidgets.QFormLayout(box)
            what = QtWidgets.QComboBox()
            what.addItems([n for n, _v in numeric])
            op = QtWidgets.QComboBox()
            from . import sensorpm
            op.addItems(list(sensorpm.RULES))
            l1, l2 = QtWidgets.QDoubleSpinBox(), QtWidgets.QDoubleSpinBox()
            for sb in (l1, l2):
                sb.setRange(-1e12, 1e12)
                sb.setDecimals(4)
            l1.setValue(Units().value(numeric[0][1]) or 0.0)
            what.currentIndexChanged.connect(lambda i: l1.setValue(Units().value(numeric[i][1]) or 0.0))
            form.addRow("Measurement:", what)
            form.addRow("Alert:", op)
            form.addRow("Limit:", l1)
            form.addRow("Second limit:", l2)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(box.accept)
            bb.rejected.connect(box.reject)
            form.addRow(bb)
            if not box.exec():
                return None
            name, operator, limit1, limit2 = what.currentText(), op.currentText(), l1.value(), l2.value()
        name = name or numeric[0][0]
        if limit1 is None:
            limit1 = Units().value(dict(numeric).get(name, "0")) or 0.0
        from . import evaluate2
        refs = [(App.getDocument(d).getObject(o), s) for d, o, s, _p in self.items if App.getDocument(d).getObject(o)]
        s = evaluate2.make_measure_sensor(refs, name, self.units(), self.arc_mode(), operator, limit1, limit2)
        self.note.setText("Sensor added: %s" % s.Label)
        self.note.setVisible(True)
        return s

    def value(self, name):
        """The text shown for a result line (tests, the context bar)."""
        return next((v for n, v in self.lines if n == name), None)

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def reject(self):
        self.cleanup()
        super().reject()

    def cleanup(self):
        global _window
        try:
            self._pin_timer.stop()
        except Exception:
            pass
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("measure.py:1164", _fw_err)
        self.drawing.clear()
        if _window is self:
            _window = None


_window = None


def current():
    return _window


def toggle():
    ""
    global _window
    if _window is not None:
        w = _window
        w.close()
        return None
    _window = MeasureWindow()
    _window.show()
    return _window


class _Command:
    def GetResources(self):
        return {"MenuText": "Measure", "ToolTip": "Takes distances, angles, lengths and areas between picked items.",
                "Pixmap": "umf-measurement"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        toggle()


class _UnitsWatch:
    ""


    def slotChangedDocument(self, doc, prop):
        if prop == "UnitSystem":
            QtCore.QTimer.singleShot(0, follow_units)


def follow_units():
    w = current()
    try:
        if w is not None and w.isVisible():
            w.refresh()
    except Exception as _fw_err:
        _fw_log("measure.py:units", _fw_err)
    try:
        from . import massprops
        d = massprops._dialog
        if d is not None and d.isVisible():
            d.refresh()
    except Exception as _fw_err:
        _fw_log("measure.py:mass units", _fw_err)


_UNITS_WATCH = []


def register():
    if not _UNITS_WATCH:
        _UNITS_WATCH.append(_UnitsWatch())
        App.addDocumentObserver(_UNITS_WATCH[0])
    if "SWStyle_Measure" not in Gui.listCommands():
        Gui.addCommand("SWStyle_Measure", _Command())
