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

import Part

from .vec import add, sub, mul, dot, cross, length, dist, xy

H_AXIS, V_AXIS, ROOT = -1, -2, -1   # GeoEnum: HAxis, VAxis; the origin is RtPnt = -1 at start
GEO_UNDEF = -2000
NONE, START, END, MID = 0, 1, 2, 3  # PointPos

# Candidate kinds
VERTEX, MIDPOINT, QUADRANT, INTERSECTION, CURVE = "vertex", "midpoint", "quadrant", "intersection", "curve"
_RANK = {VERTEX: 0, MIDPOINT: 1, INTERSECTION: 2, QUADRANT: 3}

MAX_NEAR_CURVES = 24
TWO_PI = 2 * math.pi


class Candidate:
    __slots__ = ("kind", "position", "geo", "pos", "geo2", "distance")

    def __init__(self, kind=None, position=(0.0, 0.0), geo=GEO_UNDEF, pos=NONE, geo2=GEO_UNDEF):
        self.kind, self.position, self.geo, self.pos, self.geo2 = kind, position, geo, pos, geo2
        self.distance = 0.0

    def valid(self):
        return self.kind is not None

    def __repr__(self):
        return "Candidate(%s, (%.6g, %.6g), geo=%s, pos=%s, geo2=%s)" % (
            self.kind, self.position[0], self.position[1], self.geo, self.pos, self.geo2)


class Filter:
    __slots__ = ("vertices", "midpoints", "quadrants", "intersections")

    def __init__(self, vertices=True, midpoints=True, quadrants=True, intersections=True):
        self.vertices, self.midpoints, self.quadrants, self.intersections = \
            vertices, midpoints, quadrants, intersections


class Query:
    def __init__(self, cursor, radius, woken=(), include_axes=True, filter=None):
        self.cursor = cursor
        self.radius = radius             # sketch units
        self.woken = list(woken)         # geo ids of the curves hovered recently
        self.include_axes = include_axes
        self.filter = filter or Filter()


def is_axis(geo):
    return geo in (H_AXIS, V_AXIS)


class Shape:
    """Analytic form of the curve types the engine intersects: 'line' or 'circle'."""
    __slots__ = ("type", "p0", "p1", "infinite", "center", "radius", "full", "a0", "a1", "box")

    def __init__(self):
        self.type = None
        self.p0 = self.p1 = self.center = (0.0, 0.0)
        self.infinite = False
        self.radius = 0.0
        self.full = True
        self.a0, self.a1 = 0.0, TWO_PI
        self.box = 0            # other curves' bounding box, worked out on first use


def _is(geo, cls):
    return type(geo) is cls


_SHAPES = {}


def shape_of(geo_id, geometry):
    """The Shape of a geometry, read once per geometry object (callers only read it)."""
    if geometry is None or is_axis(geo_id):
        return _shape_of(geo_id, geometry)
    hit = _SHAPES.get(id(geometry))
    if hit is not None and hit[0] is geometry:
        return hit[1]
    if len(_SHAPES) > 8192:
        _SHAPES.clear()
    s = _shape_of(geo_id, geometry)
    _SHAPES[id(geometry)] = (geometry, s)
    return s


def _shape_of(geo_id, geometry):
    s = Shape()
    if is_axis(geo_id):
        s.type = "line"
        s.p0 = (0.0, 0.0)
        s.p1 = (1.0, 0.0) if geo_id == H_AXIS else (0.0, 1.0)
        s.infinite = True
        return s
    g = geometry
    if g is None:
        return s
    if _is(g, Part.LineSegment):
        s.type = "line"
        s.p0, s.p1 = xy(g.StartPoint), xy(g.EndPoint)
        if length(sub(s.p1, s.p0)) <= 0.0:
            s.type = None
    elif _is(g, Part.Circle):
        s.type = "circle"
        s.center, s.radius = xy(g.Center), g.Radius
    elif _is(g, Part.ArcOfCircle):
        s.type = "circle"
        s.center, s.radius = xy(g.Center), g.Radius
        s.full = False
        a, b = arc_ends_ccw(g)
        start, end = sub(a, s.center), sub(b, s.center)
        s.a0 = math.atan2(start[1], start[0])
        s.a1 = math.atan2(end[1], end[0])
        while s.a1 <= s.a0:
            s.a1 += TWO_PI
    if s.type == "circle" and not s.radius > 0.0:
        s.type = None
    return s


def arc_ends_ccw(arc):
    """Start and end of an arc as if it ran counter-clockwise (emulateCCW)."""
    a, b = xy(arc.StartPoint), xy(arc.EndPoint)
    if arc.Axis.z < 0:
        a, b = b, a
    return a, b


def _tol(scale):
    return 1e-9 * (1.0 + abs(scale))


def angle_in_arc(c, angle, angular_tolerance):
    if c.full:
        return True
    offset = math.fmod(angle - c.a0, TWO_PI)
    if offset < 0.0:
        offset += TWO_PI
    return offset <= (c.a1 - c.a0) + angular_tolerance or offset >= TWO_PI - angular_tolerance


def point_on_arc(c, p, tolerance):
    v = sub(p, c.center)
    return angle_in_arc(c, math.atan2(v[1], v[0]), tolerance / c.radius)


def _on_line(line, t, tolerance):
    return line.infinite or (-tolerance <= t <= 1.0 + tolerance)


def _lines(a, b, out):
    da, db = sub(a.p1, a.p0), sub(b.p1, b.p0)
    den = cross(da, db)
    if abs(den) <= 1e-12 * length(da) * length(db):
        return
    w = sub(b.p0, a.p0)
    t = cross(w, db) / den
    u = cross(w, da) / den
    if _on_line(a, t, 1e-9) and _on_line(b, u, 1e-9):
        out.append(add(a.p0, mul(da, t)))


def _line_circle(line, c, out):
    d = sub(line.p1, line.p0)
    n = length(d)
    u = mul(d, 1.0 / n)
    tol = _tol(max(c.radius, length(c.center), length(line.p0), length(line.p1)))
    foot = add(line.p0, mul(u, dot(sub(c.center, line.p0), u)))
    distance = dist(foot, c.center)
    if distance > c.radius + tol:
        return
    if distance >= c.radius - tol:
        points = [foot]
    else:
        h = math.sqrt(c.radius * c.radius - distance * distance)
        points = [sub(foot, mul(u, h)), add(foot, mul(u, h))]
    for p in points:
        t = dot(sub(p, line.p0), u) / n
        if _on_line(line, t, tol / n) and point_on_arc(c, p, tol):
            out.append(p)


def _circles(a, b, out):
    d = sub(b.center, a.center)
    distance = length(d)
    tol = _tol(max(a.radius, b.radius, length(a.center), length(b.center)))
    if distance <= tol:
        return
    if distance > a.radius + b.radius + tol or distance < abs(a.radius - b.radius) - tol:
        return
    along = (a.radius ** 2 - b.radius ** 2 + distance ** 2) / (2 * distance)
    h2 = a.radius ** 2 - along ** 2
    h = math.sqrt(h2) if h2 > 0.0 else 0.0
    base = add(a.center, mul(d, along / distance))
    normal = (-d[1] / distance, d[0] / distance)
    points = [base] if h <= tol else [add(base, mul(normal, h)), sub(base, mul(normal, h))]
    for p in points:
        if point_on_arc(a, p, tol) and point_on_arc(b, p, tol):
            out.append(p)


def _rank(kind):
    return _RANK.get(kind, 4)


def vertex_positions(g):
    if _is(g, Part.Point):
        return [START]
    if _is(g, Part.LineSegment) or _is(g, Part.BSplineCurve):
        return [START, END]
    if _is(g, Part.Circle) or _is(g, Part.Ellipse):
        return [MID]
    if isinstance(g, (Part.ArcOfCircle, Part.ArcOfEllipse, Part.ArcOfHyperbola, Part.ArcOfParabola)):
        return [START, END, MID]
    return []


def point_of(g, pos):
    """SketchObject::getPoint for one geometry."""
    if _is(g, Part.Point):
        return (g.X, g.Y)
    if pos == MID:
        c = g.Center if hasattr(g, "Center") else g.Location
        return xy(c)
    if isinstance(g, Part.ArcOfCircle) or isinstance(g, (Part.ArcOfEllipse, Part.ArcOfHyperbola, Part.ArcOfParabola)):
        # the Sketcher swaps the ends of a circular or elliptical arc whose axis points down
        a, b = arc_ends_ccw(g) if isinstance(g, (Part.ArcOfCircle, Part.ArcOfEllipse)) \
            else (xy(g.StartPoint), xy(g.EndPoint))
        return a if pos == START else b
    return xy(g.StartPoint) if pos == START else xy(g.EndPoint)


def is_vertical_quadrant(q, center):
    return abs(q[0] - center[0]) < abs(q[1] - center[1])


def closest_point(geo_id, geometry, p):
    """Point of a supported curve closest to p, or None."""
    s = shape_of(geo_id, geometry)
    if s.type == "line":
        d = sub(s.p1, s.p0)
        dd = dot(d, d)
        if not dd > 0.0:
            return s.p0
        t = dot(sub(p, s.p0), d) / dd
        if not s.infinite:
            t = min(max(t, 0.0), 1.0)
        return add(s.p0, mul(d, t))
    if s.type == "circle":
        v = sub(p, s.center)
        if point_on_arc(s, p, 0.0):
            n = length(v)
            return add(s.center, mul(v, s.radius / n) if n > 0.0 else (s.radius, 0.0))
        start = add(s.center, (math.cos(s.a0) * s.radius, math.sin(s.a0) * s.radius))
        end = add(s.center, (math.cos(s.a1) * s.radius, math.sin(s.a1) * s.radius))
        return start if dist(p, start) <= dist(p, end) else end
    if s.type is None and geometry is not None and not is_axis(geo_id):
        return _projected(geometry, p)
    return None


def _projected(g, p):
    ""

    if _is(g, Part.Point):
        return None
    try:
        import FreeCAD as App
        q = g.value(g.parameter(App.Vector(p[0], p[1], 0)))
        return (q.x, q.y)
    except Exception:
        return None


def beyond(geo_id, geometry, p, r):
    """True when the curve is surely farther than r from p (a box test before the exact one)."""
    s = shape_of(geo_id, geometry)
    if s.type == "line" and not s.infinite:
        (x0, y0), (x1, y1) = s.p0, s.p1
        return p[0] < min(x0, x1) - r or p[0] > max(x0, x1) + r or p[1] < min(y0, y1) - r or p[1] > max(y0, y1) + r
    if s.type == "circle":
        dx, dy = p[0] - s.center[0], p[1] - s.center[1]
        reach = s.radius + r
        return dx * dx + dy * dy > reach * reach
    if s.type is None and geometry is not None and not is_axis(geo_id):
        b = getattr(s, "box", 0)
        if b == 0:
            b = s.box = _box(geo_id, geometry)
        return b is not None and (p[0] < b[0] - r or p[0] > b[2] + r or p[1] < b[1] - r or p[1] > b[3] + r)
    return False


def distance_to_curve(geo_id, geometry, p):
    c = closest_point(geo_id, geometry, p)
    return -1.0 if c is None else dist(c, p)


def intersections(a, b):
    """Crossings of two (geo_id, geometry) entries."""
    out = []
    sa, sb = shape_of(*a), shape_of(*b)
    if sa.type == "line" and sb.type == "line":
        _lines(sa, sb, out)
    elif sa.type == "line" and sb.type == "circle":
        _line_circle(sa, sb, out)
    elif sa.type == "circle" and sb.type == "line":
        _line_circle(sb, sa, out)
    elif sa.type == "circle" and sb.type == "circle":
        _circles(sa, sb, out)
    elif (sa.type is None or sb.type is None) and all(
            is_axis(e[0]) or (e[1] is not None and not _is(e[1], Part.Point)) for e in (a, b)):
        _general(a, b, out)
    return out


def _general(a, b, out):
    """Crossings where one curve is an ellipse, spline or conic (OpenCascade finds them)."""
    try:
        import FreeCAD as App
        ga, gb = a[1], b[1]
        if is_axis(a[0]) or is_axis(b[0]):
            ax, other = (a, gb) if is_axis(a[0]) else (b, ga)
            d = (1, 0, 0) if ax[0] == H_AXIS else (0, 1, 0)
            line = Part.Line(App.Vector(0, 0, 0), App.Vector(*d))
            pts = other.intersectCC(line)
        else:
            pts = ga.intersectCC(gb)
        for q in pts:
            out.append((q.X, q.Y) if hasattr(q, "X") else (q.x, q.y))
    except Exception as _fw_err:
        _fw_log("fwsketch/inference.py:352", _fw_err)


def intersect_line(origin, direction, entry):
    """Crossings of the infinite line through origin along direction with a curve entry."""
    out = []
    if not length(direction) > 0.0:
        return out
    line = Shape()
    line.type, line.p0, line.p1, line.infinite = "line", origin, add(origin, direction), True
    other = shape_of(*entry)
    if other.type == "line":
        _lines(line, other, out)
    elif other.type == "circle":
        _line_circle(line, other, out)
    return out


def virtual_points(entry, filt=None):
    filt = filt or Filter()
    geo_id = entry[0]
    points = []
    if is_axis(geo_id):
        return points
    s = shape_of(*entry)
    if s.type == "line":
        if filt.midpoints:
            points.append(Candidate(MIDPOINT, mul(add(s.p0, s.p1), 0.5), geo_id))
    elif s.type == "circle":
        on = lambda a: add(s.center, (math.cos(a) * s.radius, math.sin(a) * s.radius))
        tol = 1e-9 * (1.0 + s.radius + length(s.center))
        is_end = lambda p: (not s.full) and (dist(p, on(s.a0)) <= tol or dist(p, on(s.a1)) <= tol)
        quadrants = []
        if filt.quadrants:
            r = s.radius
            for quarter, off in enumerate(((r, 0.0), (0.0, r), (-r, 0.0), (0.0, -r))):
                if not angle_in_arc(s, quarter * math.pi / 2, 1e-12):
                    continue
                q = add(s.center, off)
                if not is_end(q):
                    quadrants.append(q)
                    points.append(Candidate(QUADRANT, q, geo_id))
        if filt.midpoints and not s.full:
            m = on((s.a0 + s.a1) / 2)
            if not any(dist(q, m) <= tol for q in quadrants):
                points.append(Candidate(MIDPOINT, m, geo_id))
    elif filt.quadrants and _is(entry[1], Part.Ellipse):

        g = entry[1]
        c, u = xy(g.Center), xy(g.XAxis)
        n = length(u)
        if n > 0.0:
            u = mul(u, 1.0 / n)
            v = (-u[1], u[0])
            for vec, r in ((u, g.MajorRadius), (v, g.MinorRadius)):
                for sign in (1.0, -1.0):
                    points.append(Candidate(QUADRANT, add(c, mul(vec, sign * r)), geo_id))
    return points


NEARBY_MIN = 64          # fewer entries than this: no index, the plain loops are as fast
_GRID = [None]           # (entries list, cell, {cell: [index]}, [index always looked at])


def _box(geo_id, g):
    """(x0, y0, x1, y1) holding the curve and all its points (an arc's centre too), or None."""
    s = shape_of(geo_id, g)
    if s.type == "line" and not s.infinite:
        (x0, y0), (x1, y1) = s.p0, s.p1
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    if s.type == "circle":
        (cx, cy), r = s.center, s.radius
        return cx - r, cy - r, cx + r, cy + r
    if _is(g, Part.Point):
        return g.X, g.Y, g.X, g.Y
    try:
        if hasattr(g, "MajorRadius") and not isinstance(g, Part.ArcOfHyperbola):   # a hyperbola runs outside it
            c, r = g.Center, g.MajorRadius
            return c.x - r, c.y - r, c.x + r, c.y + r
        b = g.toShape().BoundBox
        return b.XMin, b.YMin, b.XMax, b.YMax
    except Exception:
        return None


def _grid(entries):
    hit = _GRID[0]
    if hit is not None and hit[0] is entries:
        return hit
    boxes, always = [], []
    for i, (geo_id, g) in enumerate(entries):
        b = None if g is None or is_axis(geo_id) else _box(geo_id, g)
        if b is None:
            always.append(i)
        boxes.append(b)
    known = [b for b in boxes if b is not None]
    if not known:
        hit = (entries, 1.0, {}, always)
        _GRID[0] = hit
        return hit
    w = max(max(b[2] for b in known) - min(b[0] for b in known), max(b[3] for b in known) - min(b[1] for b in known))
    cell = max(w / 128.0, 1e-9)
    cells = {}
    for i, b in enumerate(boxes):
        if b is None:
            continue
        i0, j0, i1, j1 = (int(math.floor(b[0] / cell)), int(math.floor(b[1] / cell)),
                          int(math.floor(b[2] / cell)), int(math.floor(b[3] / cell)))
        if (i1 - i0 + 1) * (j1 - j0 + 1) > 256:
            always.append(i)
            continue
        for ci in range(i0, i1 + 1):
            for cj in range(j0, j1 + 1):
                cells.setdefault((ci, cj), []).append(i)
    hit = (entries, cell, cells, always)
    _GRID[0] = hit
    return hit


def nearby(entries, p, r):
    """The entries whose box comes within r of p, in their own order: a grid index over the
    sketch, built once per entries list, so a pointer move in a sketch of thousands of entities
    looks at the few near it."""
    if len(entries) < NEARBY_MIN or not r > 0.0:
        return entries
    _e, cell, cells, always = _grid(entries)
    if (2.0 * r / cell + 1) ** 2 > 4096:
        return entries
    i0, j0 = int(math.floor((p[0] - r) / cell)), int(math.floor((p[1] - r) / cell))
    i1, j1 = int(math.floor((p[0] + r) / cell)), int(math.floor((p[1] + r) / cell))
    found = set(always)
    for ci in range(i0, i1 + 1):
        for cj in range(j0, j1 + 1):
            found.update(cells.get((ci, cj), ()))
    return [entries[i] for i in sorted(found)]


def find_point_candidate(entries, query):
    """entries: list of (geo_id, geometry). Best point within query.radius, or an invalid candidate.
    Nearest first; at equal distance Vertex > Midpoint > Intersection > Quadrant. An end point
    within query.radius of the nearest midpoint, quadrant or intersection wins over it."""
    best = [Candidate()]
    vertex = [Candidate()]      # the nearest end point in reach (fix65)
    if not query.radius > 0.0:
        return best[0]
    tie = 1e-6 * query.radius

    def consider(c):
        c.distance = dist(c.position, query.cursor)
        if c.distance > query.radius:
            return
        if c.kind == VERTEX and (not vertex[0].valid() or c.distance < vertex[0].distance - tie):
            vertex[0] = c
        b = best[0]
        if (not b.valid() or c.distance < b.distance - tie
                or (abs(c.distance - b.distance) <= tie and _rank(c.kind) < _rank(b.kind))):
            best[0] = c

    f = query.filter
    every = entries
    entries = nearby(entries, query.cursor, query.radius)
    if f.vertices:
        if query.include_axes:
            consider(Candidate(VERTEX, (0.0, 0.0), ROOT, START))
        for geo_id, g in entries:
            if g is None or is_axis(geo_id):
                continue
            for pos in vertex_positions(g):
                consider(Candidate(VERTEX, point_of(g, pos), geo_id, pos))
    if f.midpoints or f.quadrants:
        by_id = dict(every)
        for geo_id in query.woken:
            if geo_id in by_id:
                for c in virtual_points((geo_id, by_id[geo_id]), f):
                    consider(c)
    if f.intersections:
        near = []
        if query.include_axes:
            for axis in (H_AXIS, V_AXIS):
                if distance_to_curve(axis, None, query.cursor) <= query.radius:
                    near.append((axis, None))
        for e in entries:
            if len(near) >= MAX_NEAR_CURVES:
                break
            if is_axis(e[0]) or beyond(e[0], e[1], query.cursor, query.radius):
                continue
            d = distance_to_curve(e[0], e[1], query.cursor)
            if 0.0 <= d <= query.radius:
                near.append(e)
        for i in range(len(near)):
            for j in range(i + 1, len(near)):
                for p in intersections(near[i], near[j]):
                    consider(Candidate(INTERSECTION, p, near[i][0], NONE, near[j][0]))
    b, v = best[0], vertex[0]
    if b.valid() and b.kind != VERTEX and v.valid() and dist(v.position, b.position) <= query.radius:

        # (a short entity, or the view zoomed out on small geometry) the end point is taken
        return v
    return b


def find_curve_candidate(entries, query):
    best = Candidate()
    if not query.radius > 0.0:
        return best
    for geo_id, g in nearby(entries, query.cursor, query.radius):
        if g is None or is_axis(geo_id) or beyond(geo_id, g, query.cursor, query.radius):
            continue
        c = closest_point(geo_id, g, query.cursor)
        if c is None:
            continue
        d = dist(c, query.cursor)
        if d <= query.radius and (not best.valid() or d < best.distance):
            best = Candidate(CURVE, c, geo_id)
            best.distance = d
    return best
