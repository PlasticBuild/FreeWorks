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
from .. import geomkeep

V = App.Vector
DEGREE = 3


# --- building curves -------------------------------------------------------------------------
def chord_knots(points):
    """Chord-length parameters of points (as OCC's default interpolation)."""
    u = [0.0]
    for a, b in zip(points, points[1:]):
        u.append(u[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    return u


def natural(points, closed=False):
    ""

    pts = _dedupe(points)
    if len(pts) < 2:
        return None
    if closed and len(pts) < 3:
        closed = False
    if not closed and len(pts) == 3:
        return through_three(pts)
    try:
        c = Part.BSplineCurve()
        c.interpolate(Points=[V(p[0], p[1], 0) for p in pts], PeriodicFlag=bool(closed))
        return c
    except Exception:
        return None


def through_three(pts, knots=None):
    ""


    try:
        (x0, y0), (x1, y1), (x2, y2) = [(p[0], p[1]) for p in pts]
        u = list(knots) if knots else chord_knots(pts)
        h0, h1 = u[1] - u[0], u[2] - u[1]
        if not (h0 > 0.0 and h1 > 0.0):
            return None
        d0 = ((x1 - x0) / h0, (y1 - y0) / h0)
        d1 = ((x2 - x1) / h1, (y2 - y1) / h1)
        m = (3.0 * (d1[0] - d0[0]) / (h0 + h1), 3.0 * (d1[1] - d0[1]) / (h0 + h1))   # S'' at the middle
        t0 = V(d0[0] - h0 * m[0] / 6.0, d0[1] - h0 * m[1] / 6.0, 0)
        t2 = V(d1[0] + h1 * m[0] / 6.0, d1[1] + h1 * m[1] / 6.0, 0)
        c = Part.BSplineCurve()
        c.interpolate(Points=[V(x, y, 0) for x, y in ((x0, y0), (x1, y1), (x2, y2))], Parameters=u,
                      InitialTangent=t0, FinalTangent=t2, Scale=False)
        return c
    except Exception:
        return None


def _uneven(t_in, t_out):
    return math.hypot(t_in[0] - t_out[0], t_in[1] - t_out[1]) > 1e-9 * max(1.0, math.hypot(*t_out))


def hermite(points, knots, tangents, closed=False, tangents_in=None):
    ""







    n = len(points)
    t_out = list(tangents)
    t_in = list(tangents_in) if tangents_in is not None else t_out
    spans = n if closed else n - 1
    inner = []
    for i in range(spans):
        j = (i + 1) % n
        h = knots[i + 1] - knots[i]
        a, b = points[i], points[j]
        ta, tb = t_out[i], t_in[j]
        inner.append((V(a[0] + ta[0] * h / 3.0, a[1] + ta[1] * h / 3.0, 0), V(b[0] - tb[0] * h / 3.0, b[1] - tb[1] * h / 3.0, 0)))
    triple = [_uneven(t_in[i], t_out[i]) for i in range(n)]
    c = Part.BSplineCurve()
    if closed:
        poles, mults = [], []
        for i in range(n):
            before = inner[i - 1][1]          # the last pole of the span arriving at point i
            poles.append(before)
            if triple[i]:
                poles.append(V(points[i][0], points[i][1], 0))
            poles.append(inner[i][0])
            mults.append(3 if triple[i] else 2)
        mults.append(mults[0])
        # OCC's periodic poles start at the first knot's own pole when it has one (found by test)
        rot = 1 if triple[0] else 0
        poles = poles[rot:] + poles[:rot]
        c.buildFromPolesMultsKnots(poles=poles, mults=mults, knots=list(knots), periodic=True, degree=DEGREE)
        return c
    poles = [V(points[0][0], points[0][1], 0)]
    mults = [DEGREE + 1]
    for i in range(spans):
        poles.extend(inner[i])
        j = i + 1
        if j < n - 1:
            if triple[j]:
                poles.append(V(points[j][0], points[j][1], 0))
            mults.append(3 if triple[j] else 2)
    poles.append(V(points[-1][0], points[-1][1], 0))
    mults.append(DEGREE + 1)
    c.buildFromPolesMultsKnots(poles=poles, mults=mults, knots=list(knots), periodic=False, degree=DEGREE)
    return c


def pole_layout(curve):
    """[(pole before, pole at or None, pole after)] per spline point of a hermite() spline; None
    where a point has no pole on that side (the ends of an open spline)."""
    mults = list(curve.getMultiplicities())
    n = len(_knot_values(curve))
    out = []
    if curve.isPeriodic():
        k = 0
        for j in range(n):
            if mults[j] >= 3:
                out.append((k, k + 1, k + 2))
                k += 3
            else:
                out.append((k, None, k + 1))
                k += 2
        rot = 1 if mults[0] >= 3 else 0         # as hermite() writes them
        return [tuple(None if x is None else (x - rot) % k for x in row) for row in out]
    out.append((None, 0, 1))
    k = 1
    for j in range(1, n):
        if j == n - 1:
            out.append((k + 1, k + 2, None))
        elif mults[j] >= 3:
            out.append((k + 1, k + 2, k + 3))
            k += 3
        else:
            out.append((k + 1, None, k + 2))
            k += 2
    return out


def sides(curve):
    ""

    knots = _knot_values(curve)
    n = len(knots)
    out = []
    if not is_hermite(curve):
        for k in knots:
            d = curve.getDN(k, 1)
            w = math.hypot(d.x, d.y)
            out.append((math.degrees(math.atan2(d.y, d.x)), w, w))
        return out
    all_knots = list(curve.getKnots())
    poles = curve.getPoles()
    for i, (before, at, after) in enumerate(pole_layout(curve)):
        p = curve.value(knots[i])
        w_in = w_out = None
        d = None
        if before is not None:
            h = all_knots[i] - all_knots[i - 1] if i > 0 else all_knots[-1] - all_knots[-2]
            v = (p.x - poles[before].x, p.y - poles[before].y)
            w_in = math.hypot(*v) * 3.0 / h
            d = v
        if after is not None:
            h = all_knots[i + 1] - all_knots[i]
            v = (poles[after].x - p.x, poles[after].y - p.y)
            w_out = math.hypot(*v) * 3.0 / h
            if math.hypot(*v) > 1e-12 or d is None:
                d = v
        w_in = w_out if w_in is None else w_in
        w_out = w_in if w_out is None else w_out
        out.append((math.degrees(math.atan2(d[1], d[0])), w_in, w_out))
    return out


def hold_pole(curve, index):
    """The pole index that holds the tangent at spline point index of a hermite() spline: the one
    after the point, before it for an open spline's last point. (pole index, sign)."""
    before, _, after = pole_layout(curve)[index]
    if after is None:
        return before, -1
    return after, 1


def hold_poles(curve, index):
    """Every pole that holds point index's tangent: also the one before when the point has a
    pole of its own (uneven weights, multiplicity 3)."""
    before, at, after = pole_layout(curve)[index]
    out = [hold_pole(curve, index)[0]]
    if at is not None and before is not None and after is not None:
        out.append(before)
    return out


def is_hermite(curve):
    """True when every interior knot has multiplicity 2, or 3 at a point of uneven weights
    (tangents can be held per point)."""
    if curve.Degree != DEGREE:
        return False
    m = list(curve.getMultiplicities())
    inner = m if curve.isPeriodic() else m[1:-1]
    return all(k in (2, 3) for k in inner) and (curve.isPeriodic() or (m[0] == 4 and m[-1] == 4))


def sample(curve, count=64):
    """A polyline along curve, for previews."""
    if curve is None:
        return []
    a, b = curve.FirstParameter, curve.LastParameter
    out = []
    for k in range(count + 1):
        p = curve.value(a + (b - a) * k / count)
        out.append((p.x, p.y))
    return out


def _dedupe(points, tol=1e-7):
    out = []
    for p in points:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > tol:
            out.append((float(p[0]), float(p[1])))
    return out


# --- reading a sketch ---------------------------------------------------------------------------
def is_spline(sketch, geo):
    try:
        return geo >= 0 and isinstance(sketch.Geometry[geo], Part.BSplineCurve)
    except Exception:
        return False


def _aligned_points(sketch, geo):
    """Point geometries InternalAlignment'ed to spline geo (its knot points)."""
    out = []
    geos = sketch.Geometry
    for c in sketch.Constraints:
        if c.Type == "InternalAlignment" and c.Second == geo and 0 <= c.First < len(geos) \
                and isinstance(geos[c.First], Part.Point):
            out.append(c.First)
    return out


def spline_of(sketch, geo):
    """The spline geo id a spline point (knot point) belongs to; geo itself when it is a spline."""
    if is_spline(sketch, geo):
        return geo
    for c in sketch.Constraints:
        if c.Type == "InternalAlignment" and c.First == geo and is_spline(sketch, c.Second):
            return c.Second
    return None


def _knot_values(curve):
    knots = list(curve.getKnots())
    if curve.isPeriodic():
        knots = knots[:-1]          # the last knot closes the curve onto the first
    return knots


def info(sketch, geo):
    """The spline's points in order, the knot point geo ids (None where a point has none), the
    tangents as (angle in degrees, weight) and whether it is closed."""
    curve = sketch.Geometry[geo]
    knots = _knot_values(curve)
    pts, tans = [], []
    for k in knots:
        p = curve.value(k)
        d = curve.getDN(k, 1)
        pts.append((p.x, p.y))
        tans.append((math.degrees(math.atan2(d.y, d.x)), math.hypot(d.x, d.y)))
    knot_points = [None] * len(knots)
    geos = sketch.Geometry
    for g in _aligned_points(sketch, geo):
        q = geos[g]
        best = min(range(len(pts)), key=lambda i: math.hypot(pts[i][0] - q.X, pts[i][1] - q.Y))
        if knot_points[best] is None:
            knot_points[best] = g
    sd = sides(curve)
    # the tangent leaving each point (arriving at an open spline's end)
    tans = [(a, w2 if not (not curve.isPeriodic() and i == len(sd) - 1) else w1) for i, (a, w1, w2) in enumerate(sd)]
    return {"closed": bool(curve.isPeriodic()), "points": pts, "knot_points": knot_points,
            "tangents": tans, "sides": sd, "knots": knots, "all_knots": list(curve.getKnots()),
            "driven": sorted(holds(sketch, geo))}


# --- changing it ------------------------------------------------------------------------------------
HIDDEN_LAYER = 2   # ViewProviderSketch's default layers: 0 normal, 2 hidden (the Elements list's eye)


def pole_circles(sketch, geo):
    """The control-point circles of spline geo."""
    geos = sketch.Geometry
    return [c.First for c in sketch.Constraints
            if c.Type == "InternalAlignment" and c.Second == geo and 0 <= c.First < len(geos)
            and isinstance(geos[c.First], Part.Circle)]


def hide_poles(sketch, geo):
    """Put the spline's control-point circles on the hidden layer (GUI only)."""
    try:
        import SketcherGui
    except ImportError:
        return False
    ids = pole_circles(sketch, geo)
    if not ids:
        return False
    geos = geomkeep.read(sketch)
    for i in ids:
        e = SketcherGui.ViewProviderSketchGeometryExtension()
        e.VisualLayerId = HIDDEN_LAYER
        geos[i].setExtension(e)
    sketch.Geometry = geos
    return True


def _expose(sketch, geo):
    """Expose the spline's internal geometry, drop knot points it already had (a closed spline's
    seam knot comes twice) and hide the control circles."""
    before = sketch.GeometryCount
    sketch.exposeInternalGeometry(geo)
    geos = sketch.Geometry
    seen = [(geos[g].X, geos[g].Y) for g in _aligned_points(sketch, geo) if g < before]
    extra = []
    for g in range(before, len(geos)):
        if isinstance(geos[g], Part.Point):
            q = (geos[g].X, geos[g].Y)
            if any(math.hypot(q[0] - s[0], q[1] - s[1]) < 1e-7 for s in seen):
                extra.append(g)
            else:
                seen.append(q)
    if extra:
        sketch.delGeometries(sorted(extra))
    hide_poles(sketch, geo)
    hide_pole_constraints(sketch, geo)


def hide_pole_constraints(sketch, geo):
    """The circles' Weight and Equal relations go to the virtual space: no glyphs or weight
    dimension on show (they only hold the weights)."""
    poles = set(pole_circles(sketch, geo))
    ids = [i for i, c in enumerate(sketch.Constraints)
           if c.Type in ("Weight", "Equal") and c.First in poles and (c.Type == "Weight" or c.Second in poles)]
    if ids:
        try:
            sketch.setVirtualSpace(ids, True)
        except Exception as _fw_err:
            _fw_log("fwsketch/splineedit.py:401", _fw_err)


def _in_place(sketch, geo, curve):
    """The sketch's own geometry object for geo, given curve's shape: it keeps its Tag (the spline
    displays are keyed by it) and its extensions (construction, layer)."""
    own = sketch.Geometry[geo]
    try:
        own.buildFromPolesMultsKnots(poles=curve.getPoles(), mults=list(curve.getMultiplicities()),
                                     knots=list(curve.getKnots()), periodic=bool(curve.isPeriodic()),
                                     degree=curve.Degree, weights=list(curve.getWeights()))
        return own
    except Exception:
        return curve


def _knots_onto(sketch, geo, old, geos, curve):
    """The spline's knot points go onto the new curve's knots: left where they were, the next
    solve pulls the new curve half way back to the old one. A point's knot is the old curve's
    knot it sits on (stock Python does not give the alignment index)."""
    try:
        new_k = list(curve.getKnots())
        old_k = list(old.getKnots())
        if len(new_k) != len(old_k):
            return
        old_p = [old.value(k) for k in old_k]
    except Exception:
        return
    for c in sketch.Constraints:
        if c.Type != "InternalAlignment" or c.Second != geo or not (0 <= c.First < len(geos)) \
                or not isinstance(geos[c.First], Part.Point):
            continue
        q = geos[c.First]
        k = min(range(len(old_p)), key=lambda i: math.hypot(old_p[i].x - q.X, old_p[i].y - q.Y))
        p = curve.value(new_k[k])
        geos[c.First] = Part.Point(V(p.x, p.y, 0))


def _replace(sketch, geo, curve):
    """Put curve in place of spline geo: the spline points and their relations stay, the control
    circles are made again for the new poles."""
    construction = False
    try:
        construction = bool(sketch.getConstruction(geo))
    except Exception as _fw_err:
        _fw_log("fwsketch/splineedit.py:446", _fw_err)
    circles = pole_circles(sketch, geo)
    if circles:
        sketch.delGeometries(sorted(circles))      # geo comes first: its id does not move
    geos = geomkeep.read(sketch)
    old = geos[geo].copy()
    geos[geo] = _in_place(sketch, geo, curve)
    _knots_onto(sketch, geo, old, geos, curve)
    sketch.Geometry = geos
    if construction:
        try:
            sketch.setConstruction(geo, True)
        except Exception as _fw_err:
            _fw_log("fwsketch/splineedit.py:459", _fw_err)
    _expose(sketch, geo)
    sketch.solve()


def set_point(sketch, geo, index, x, y):
    """Move spline point index to (x, y); its relations and the solver reshape the curve."""
    data = info(sketch, geo)
    kp = data["knot_points"][index]
    if kp is not None:
        sketch.moveGeometry(kp, 1, V(x, y, 0), False)
    elif not data["closed"] and index in (0, len(data["points"]) - 1):
        sketch.moveGeometry(geo, 1 if index == 0 else 2, V(x, y, 0), False)
    else:
        raise ValueError("spline point %d has no point to move" % index)
    sketch.solve()


def _circle_of_pole(sketch, geo, pole):
    """The control circle at pole index of spline geo (by position), or None."""
    curve = sketch.Geometry[geo]
    p = curve.getPoles()[pole]
    geos = sketch.Geometry
    best, out = 1e-6, None
    for g in pole_circles(sketch, geo):
        c = geos[g].Center
        dist = math.hypot(c.x - p.x, c.y - p.y)
        if dist <= best:
            best, out = dist, g
    return out


def holds(sketch, geo):
    ""

    data_kp = info_points(sketch, geo)
    poles = set(pole_circles(sketch, geo))
    out = {}
    for ci, c in enumerate(sketch.Constraints):
        if c.Type in ("DistanceX", "DistanceY") and c.First in data_kp and c.Second in poles:
            out.setdefault(data_kp[c.First], []).append(ci)
    return out


def info_points(sketch, geo):
    """{knot point geo: spline point index}."""
    curve = sketch.Geometry[geo]
    knots = _knot_values(curve)
    pts = [curve.value(k) for k in knots]
    geos = sketch.Geometry
    out = {}
    for g in _aligned_points(sketch, geo):
        q = geos[g]
        out[g] = min(range(len(pts)), key=lambda i: math.hypot(pts[i].x - q.X, pts[i].y - q.Y))
    return out


def _add_hold(sketch, geo, index):
    """Hold the tangent at spline point index: the holding circle stays at its offset from the
    point (direction and weight), whatever else the solver moves. In the virtual space."""
    import Sketcher
    curve = sketch.Geometry[geo]
    kp = None
    for g, i in info_points(sketch, geo).items():
        if i == index:
            kp = g
    if kp is None:
        return []
    q = sketch.Geometry[kp]
    ids = []
    for pole in hold_poles(curve, index):
        cg = _circle_of_pole(sketch, geo, pole)
        if cg is None:
            continue
        c = sketch.Geometry[cg].Center
        ids += [sketch.addConstraint(Sketcher.Constraint("DistanceX", kp, 1, cg, 3, c.x - q.X)),
                sketch.addConstraint(Sketcher.Constraint("DistanceY", kp, 1, cg, 3, c.y - q.Y))]
    try:
        sketch.setVirtualSpace(ids, True)
    except Exception as _fw_err:
        _fw_log("fwsketch/splineedit.py:539", _fw_err)
    return ids


def undrive(sketch, geo, index):
    ""
    ids = holds(sketch, geo).get(index, [])
    for ci in sorted(ids, reverse=True):
        sketch.delConstraint(ci)
    sketch.solve()


def _vec(angle, weight):
    return (weight * math.cos(math.radians(angle)), weight * math.sin(math.radians(angle)))


def set_tangent(sketch, geo, index, angle=None, weight=None, weight1=None, weight2=None, continuity=None):
    ""






    data = info(sketch, geo)
    sd = [list(x) for x in data["sides"]]
    a0, w10, w20 = sd[index]
    a = a0 if angle is None else float(angle)
    w1, w2 = w10, w20
    if weight is not None:
        w1 = w2 = max(1e-6, float(weight))
    if weight1 is not None:
        w1 = max(1e-6, float(weight1))
    if weight2 is not None:
        w2 = max(1e-6, float(weight2))
    sd[index] = [a, w1, w2]
    t_in = [_vec(x[0], x[1]) for x in sd]
    t_out = [_vec(x[0], x[2]) for x in sd]
    driven = set(data["driven"]) | {index}
    if continuity is None:
        continuity = maintains_continuity(sketch, geo)
    knots = data["all_knots"] if data["closed"] else data["knots"]
    if continuity:
        free = [i for i in range(len(sd)) if i not in driven]
        smooth = c2_tangents(data["points"], knots, t_in, t_out, free, data["closed"])
        for i, t in smooth.items():
            t_in[i] = t_out[i] = t
    _replace(sketch, geo, hermite(data["points"], knots, t_out, data["closed"], t_in))
    for i in sorted(driven):
        _add_hold(sketch, geo, i)
    sketch.solve()


def c2_tangents(points, knots, t_in, t_out, free, closed=False):
    """Tangents at the free points so that the cubic spline through points (with the other points'
    tangents as given) has no break in curvature there; an open spline's free ends get zero
    curvature (the natural spline's ends). Returns {index: (dx, dy)}. Any dimension: 3D points with
    3D tangents give (dx, dy, dz) (the 3D Sketch's splines use it too)."""
    n = len(points)
    dim = len(t_in[0]) if t_in else 2
    free = sorted(set(free))
    if not free:
        return {}
    col = {i: k for k, i in enumerate(free)}
    h = [knots[i + 1] - knots[i] for i in range(n if closed else n - 1)]
    out = {}
    for axis in range(dim):
        A = [[0.0] * len(free) for _ in free]
        rhs = [0.0] * len(free)

        def term(row, i, coef, side):
            # coef * (tangent at i, arriving when side < 0 / leaving when side > 0)
            if i in col:
                A[row][col[i]] += coef
            else:
                rhs[row] -= coef * (t_in[i] if side < 0 else t_out[i])[axis]
        for row, i in enumerate(free):
            prev_span = (i - 1) % n if closed else (i - 1 if i > 0 else None)
            next_span = i if (closed or i < n - 1) else None
            # the curvature arriving at i equals the one leaving it: S''(arriving) - S''(leaving) = 0,
            # S''(arriving) = (-6 d/h + 2 m_prev_out + 4 m_i_in) / h, S''(leaving) = (6 d/h - 4 m_i_out - 2 m_next_in) / h
            if prev_span is not None:       # + S''(arriving)
                hp = h[prev_span]
                ip = prev_span
                d = points[i][axis] - points[ip][axis]
                rhs[row] -= -6.0 * d / hp / hp
                term(row, ip, 2.0 / hp, +1)
                term(row, i, 4.0 / hp, -1)
            if next_span is not None:       # - S''(leaving)
                hn = h[next_span]
                inx = (i + 1) % n
                d = points[inx][axis] - points[i][axis]
                rhs[row] -= -6.0 * d / hn / hn
                term(row, i, 4.0 / hn, +1)
                term(row, inx, 2.0 / hn, -1)
        x = _solve(A, rhs)
        if x is None:
            return {}
        for i in free:
            out.setdefault(i, [0.0] * dim)[axis] = x[col[i]]
    return {i: tuple(v) for i, v in out.items()}


def _solve(A, b):
    """Gaussian elimination with pivoting; None when singular."""
    n = len(b)
    M = [row[:] + [b[k]] for k, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-14:
            return None
        M[c], M[p] = M[p], M[c]
        for r in range(n):
            if r != c and M[r][c] != 0.0:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[k][n] / M[k][k] for k in range(n)]


# --- per-spline settings (kept with the sketch, keyed by the spline's Tag; splineshow uses the same list)
SETTINGS = "FreeWorksSplineShow"
NO_CONTINUITY = "nocontinuity"


def _rows(sketch):
    try:
        return list(getattr(sketch, SETTINGS))
    except AttributeError:
        return []


def _keys(sketch, geo):
    """(key written, keys read): the saved geometry id, kept after save and reopen (a Tag is not);
    the Tag still reads rows written before."""
    tag = sketch.Geometry[geo].Tag
    try:
        key = "g%d" % sketch.getGeometryId(geo)
    except Exception:
        return tag, (tag,)
    return key, (key, tag)


def flags(sketch, geo):
    key, read = _keys(sketch, geo)
    for row in _rows(sketch):
        k, _, kinds = row.partition(":")
        if k in read:
            return [x for x in kinds.split(",") if x]
    return []


def set_flag(sketch, geo, flag, on):
    key, read = _keys(sketch, geo)
    rows, kinds = [], set()
    for row in _rows(sketch):
        k, _, ks = row.partition(":")
        if k in read:
            kinds = {x for x in ks.split(",") if x}
        else:
            rows.append(row)
    (kinds.add if on else kinds.discard)(flag)
    if kinds:
        rows.append("%s:%s" % (key, ",".join(sorted(kinds))))
    if not hasattr(sketch, SETTINGS):
        if not rows:
            return
        sketch.addProperty("App::PropertyStringList", SETTINGS, "FreeCAD", "Spline displays and options FreeCAD keeps (hidden)")
        try:
            sketch.setEditorMode(SETTINGS, 2)
        except Exception as _fw_err:
            _fw_log("fwsketch/splineedit.py:699", _fw_err)
    if list(getattr(sketch, SETTINGS)) != rows:
        setattr(sketch, SETTINGS, rows)


def maintains_continuity(sketch, geo):
    ""
    return NO_CONTINUITY not in flags(sketch, geo)


def set_continuity(sketch, geo, on):
    set_flag(sketch, geo, NO_CONTINUITY, not on)


def relax(sketch, geo):
    ""

    data = info(sketch, geo)
    pts = data["points"]
    c = Part.BSplineCurve()
    if data["closed"]:
        c.interpolate(Points=[V(p[0], p[1], 0) for p in pts], PeriodicFlag=True)
    elif len(pts) == 3 and through_three(pts, data["knots"]) is not None:
        c = through_three(pts, data["knots"])
    else:
        c.interpolate(Points=[V(p[0], p[1], 0) for p in pts], Parameters=list(data["knots"]))
    _replace(sketch, geo, c)


def add(sketch, points, closed=False, construction=False):
    ""
    curve = natural(points, closed)
    if curve is None:
        raise ValueError("a spline needs two different points")
    geo = sketch.addGeometry(curve, bool(construction))
    _expose(sketch, geo)
    return geo, info(sketch, geo)["knot_points"]


# --- rebuilding with other spline points (Insert Spline Point, Simplify Spline) ------------------
def _ia_of_points(sketch, geo):
    """Constraint ids of the InternalAlignments that hold spline points on spline geo."""
    geos = sketch.Geometry
    return [i for i, c in enumerate(sketch.Constraints)
            if c.Type == "InternalAlignment" and c.Second == geo and 0 <= c.First < len(geos)
            and isinstance(geos[c.First], Part.Point)]


def _geo_by_tag(sketch, tag):
    for i, g in enumerate(sketch.Geometry):
        if g.Tag == tag:
            return i
    return None


def rebuild(sketch, geo, curve, keep, driven=()):
    """Put curve (another knot vector) in place of spline geo. keep[new knot index] = the old
    spline point index whose sketch point (and its relations) moves to that knot, or None for a
    new point; old points not kept are deleted with their relations. driven = new indexes whose
    tangents are held again."""
    import Sketcher
    old = info(sketch, geo)
    was_proportional = is_proportional(sketch, geo)
    if was_proportional:
        set_proportional(sketch, geo, False)
        old = info(sketch, geo)
    construction = False
    try:
        construction = bool(sketch.getConstruction(geo))
    except Exception as _fw_err:
        _fw_log("fwsketch/splineedit.py:769", _fw_err)
    # the spline points' alignments and the control circles (holds go with them) come off first
    for ci in sorted(_ia_of_points(sketch, geo), reverse=True):
        sketch.delConstraint(ci)
    kept = {k for k in keep if k is not None}
    gone = [g for i, g in enumerate(old["knot_points"]) if g is not None and i not in kept]
    circles = pole_circles(sketch, geo)
    removed = sorted(set(circles) | set(gone))
    # where each kept point will be once the others are gone (point geometries get a new Tag on
    # every read, so they are followed by index)
    ids = [None if g is None or g in removed else g - sum(1 for r in removed if r < g) for g in old["knot_points"]]
    if removed:
        sketch.delGeometries(removed)   # all after geo: its id stays
    geos = geomkeep.read(sketch)
    old = geos[geo].copy()
    geos[geo] = _in_place(sketch, geo, curve)
    _knots_onto(sketch, geo, old, geos, curve)
    sketch.Geometry = geos
    if construction:
        try:
            sketch.setConstruction(geo, True)
        except Exception as _fw_err:
            _fw_log("fwsketch/splineedit.py:791", _fw_err)
    nknots = len(_knot_values(curve))
    for new_index, old_index in enumerate(keep[:nknots]):
        if old_index is None or ids[old_index] is None:
            continue
        g = ids[old_index]
        p = curve.value(_knot_values(curve)[new_index])
        geos = geomkeep.read(sketch)
        geos[g] = Part.Point(V(p.x, p.y, 0))
        sketch.Geometry = geos
        sketch.addConstraint(Sketcher.Constraint("InternalAlignment:Sketcher::BSplineKnotPoint", g, 1, geo, new_index))
    _expose(sketch, geo)          # new spline points and the control circles, hidden
    for i in sorted(set(driven)):
        _add_hold(sketch, geo, i)
    if was_proportional:
        set_proportional(sketch, geo, True)
    sketch.solve()


def nearest_param(sketch, geo, point):
    """The curve parameter of spline geo nearest to point (x, y)."""
    curve = sketch.Geometry[geo]
    try:
        return curve.parameter(V(point[0], point[1], 0))
    except Exception:
        a, b = curve.FirstParameter, curve.LastParameter
        return min((a + (b - a) * k / 400.0 for k in range(401)),
                   key=lambda u: curve.value(u).distanceToPoint(V(point[0], point[1], 0)))


def insert_point(sketch, geo, point):
    ""

    curve = sketch.Geometry[geo].copy()
    u = nearest_param(sketch, geo, point)
    knots = _knot_values(curve)
    if any(abs(u - k) < 1e-7 for k in knots):
        return None
    data = info(sketch, geo)
    curve.insertKnot(u, 2 if is_hermite(curve) else 1, 1e-9)
    new = sorted(knots + [u])
    at = new.index(u)
    keep = [i if i < at else (None if i == at else i - 1) for i in range(len(new))]
    driven = [i if i < at else i + 1 for i in data["driven"]]
    rebuild(sketch, geo, curve, keep, driven)
    return at


def deviation(curve, reference, samples=400):
    """Largest distance from reference (a curve) to curve."""
    a, b = reference.FirstParameter, reference.LastParameter
    worst = 0.0
    for k in range(samples + 1):
        p = reference.value(a + (b - a) * k / samples)
        try:
            u = curve.parameter(p)
            worst = max(worst, curve.value(u).distanceToPoint(p))
        except Exception:
            worst = max(worst, min(curve.value(curve.FirstParameter + (curve.LastParameter - curve.FirstParameter) * j / 200.0).distanceToPoint(p) for j in range(201)))
    return worst


def simplify_choice(points, reference, closed, tolerance=None, count=None):
    """Indexes of the spline points to keep: drop one point at a time, the one whose loss bends
    the spline least, while the spline stays within tolerance of reference (or until count are
    left). Ends of an open spline stay. Returns (indexes, deviation)."""
    keep = list(range(len(points)))
    least = 3 if closed else 2
    dev = 0.0
    while len(keep) > least and (count is None or len(keep) > count):
        best = None
        for j in keep:
            if not closed and j in (0, len(points) - 1):
                continue
            trial = [k for k in keep if k != j]
            c = natural([points[k] for k in trial], closed)
            if c is None:
                continue
            d = deviation(c, reference, 160)
            if best is None or d < best[0]:
                best = (d, trial)
        if best is None or (tolerance is not None and count is None and best[0] > tolerance):
            break
        dev, keep = best
    return keep, dev


def simplify(sketch, geo, tolerance=None, count=None):
    ""


    data = info(sketch, geo)
    reference = sketch.Geometry[geo].copy()
    keep, dev = simplify_choice(data["points"], reference, data["closed"], tolerance, count)
    if len(keep) == len(data["points"]):
        return len(keep), 0.0
    curve = natural([data["points"][k] for k in keep], data["closed"])
    rebuild(sketch, geo, curve, keep, ())
    return len(keep), dev



PROPORTIONAL_LAYER = HIDDEN_LAYER


def proportional_lines(sketch, geo):
    """The hidden construction lines that hold spline geo proportional: {line geo: role}."""
    out = {}
    geos = sketch.Geometry
    pts = set(info_points(sketch, geo)) | {geo}
    for i, c in enumerate(sketch.Constraints):
        if c.Type == "Coincident" and 0 <= c.First < len(geos) and isinstance(geos[c.First], Part.LineSegment) \
                and c.Second in pts and _virtual(sketch, i):
            out.setdefault(c.First, []).append((c.FirstPos, c.Second, c.SecondPos))
    return out


def _virtual(sketch, ci):
    try:
        return bool(sketch.getVirtualSpace(ci))
    except Exception:
        return False


def _is_hidden(g):
    for e in g.getExtensions():
        if type(e).__name__ == "ViewProviderSketchGeometryExtension" and getattr(e, "VisualLayerId", 0) == HIDDEN_LAYER:
            return True
    return False


def is_proportional(sketch, geo):
    return bool(proportional_lines(sketch, geo))


def _hide(sketch, ids):
    try:
        import SketcherGui
    except ImportError:
        return
    geos = geomkeep.read(sketch)
    for i in ids:
        e = SketcherGui.ViewProviderSketchGeometryExtension()
        e.VisualLayerId = HIDDEN_LAYER
        geos[i].setExtension(e)
    sketch.Geometry = geos


def set_proportional(sketch, geo, on=True):
    """Hold the spline's shape against its two ends (open splines): for every point between
    them, the angles at both ends of the triangle end-end-point stay, so dragging an end scales
    and turns the spline as a whole. Hidden construction lines, relations in virtual space."""
    import Sketcher
    lines = proportional_lines(sketch, geo)
    if lines:
        sketch.delGeometries(sorted(lines))
    if not on:
        sketch.solve()
        return False
    data = info(sketch, geo)
    if data["closed"] or len(data["points"]) < 3:
        return False
    pts, kps = data["points"], data["knot_points"]
    a, b = pts[0], pts[-1]
    made, cons = [], []

    def line(p, q, construction=True):
        g = sketch.addGeometry(Part.LineSegment(V(p[0], p[1], 0), V(q[0], q[1], 0)), True)
        made.append(g)
        return g
    chord = line(a, b)
    cons.append(sketch.addConstraint(Sketcher.Constraint("Coincident", chord, 1, geo, 1)))
    cons.append(sketch.addConstraint(Sketcher.Constraint("Coincident", chord, 2, geo, 2)))
    d1 = (b[0] - a[0], b[1] - a[1])
    # a third frame point c, square to the chord at a and as long: a point in line with the ends
    # takes its rays from a and c (or b and c), so no triangle is ever flat
    c = (a[0] - d1[1], a[1] + d1[0])
    perp = None
    frame = {"a": (a, (geo, 1)), "b": (b, (geo, 2)), "c": (c, None)}

    def sine(u, v, q):
        e, f = (v[0] - u[0], v[1] - u[1]), (q[0] - u[0], q[1] - u[1])
        le, lf = math.hypot(*e), math.hypot(*f)
        return abs(e[0] * f[1] - e[1] * f[0]) / (le * lf) if le > 1e-12 and lf > 1e-12 else 0.0
    for i in range(1, len(pts) - 1):
        p, kp = pts[i], kps[i]
        if kp is None:
            continue
        pair = max((("a", "b"), ("a", "c"), ("b", "c")),
                   key=lambda uv: min(sine(frame[uv[0]][0], frame[uv[1]][0], p), sine(frame[uv[1]][0], frame[uv[0]][0], p)))
        if "c" in pair and perp is None:
            perp = line(a, c)
            frame["c"] = (c, (perp, 2))
            cons.append(sketch.addConstraint(Sketcher.Constraint("Coincident", perp, 1, geo, 1)))
            cons.append(sketch.addConstraint(Sketcher.Constraint("Perpendicular", chord, perp)))
            cons.append(sketch.addConstraint(Sketcher.Constraint("Equal", chord, perp)))
        for name in pair:
            end, (g, pos) = frame[name]
            ln = line(end, p)
            cons.append(sketch.addConstraint(Sketcher.Constraint("Coincident", ln, 1, g, pos)))
            cons.append(sketch.addConstraint(Sketcher.Constraint("Coincident", ln, 2, kp, 1)))
            d2 = (p[0] - end[0], p[1] - end[1])
            ang = math.atan2(d1[0] * d2[1] - d1[1] * d2[0], d1[0] * d2[0] + d1[1] * d2[1])
            cons.append(sketch.addConstraint(Sketcher.Constraint("Angle", chord, ln, ang)))
    try:
        sketch.setVirtualSpace(cons, True)
    except Exception as _fw_err:
        _fw_log("fwsketch/splineedit.py:998", _fw_err)
    _hide(sketch, made)
    sketch.solve()
    return True


# --- style splines (single-span Bezier, shaped by the control polygon) ---------------------------
def is_style(sketch, geo):
    ""
    return is_spline(sketch, geo) and not _aligned_points(sketch, geo) and bool(pole_circles(sketch, geo))


def control_vertices(sketch, geo):
    """[(circle geo or None, (x, y))] of the spline's poles, in order."""
    curve = sketch.Geometry[geo]
    out = []
    for i, p in enumerate(curve.getPoles()):
        out.append((_circle_of_pole(sketch, geo, i), (p.x, p.y)))
    return out


def move_vertex(sketch, geo, index, x, y):
    """Move control vertex index of a style spline to (x, y)."""
    cv = control_vertices(sketch, geo)
    circle = cv[index][0]
    if circle is None:
        raise ValueError("control vertex %d has no circle" % index)
    sketch.moveGeometry(circle, 3, V(x, y, 0), False)
    sketch.solve()
