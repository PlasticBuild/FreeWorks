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
import Sketcher

from . import helpers as H

PREFIX = "FWEqCurv_"
KIND = "eqcurv"
OWN = "t"           # the member name's tag of a Tangent the user had before: FWEqCurv_<k>_t
START, END, MID = 1, 2, 3
UNDEF = -2000
TOL = 1e-6


def _geo(sketch, g):
    try:
        return sketch.Geometry[g] if g >= 0 else sketch.ExternalGeo[-g - 1]
    except Exception:
        return None


def _kind(sketch, g):
    geo = _geo(sketch, g)
    name = type(geo).__name__ if geo is not None else ""
    if name == "BSplineCurve":
        try:
            if geo.isPeriodic() or geo.Degree < 2 or geo.NbPoles < 3:
                return None
        except Exception:
            return None
        return "spline"
    if name == "ArcOfCircle":
        return "arc"
    if name == "LineSegment" or g in (-1, -2):
        return "line"
    return None


def shared_end(sketch, a, b):
    """(end of a, end of b) where a and b meet (held together, or at the same place), else None."""
    for c in sketch.Constraints:
        if c.Type in ("Coincident", "Tangent") and {c.First, c.Second} == {a, b} and c.First != c.Second:
            fp, sp = int(c.FirstPos), int(c.SecondPos)
            if fp in (START, END) and sp in (START, END):
                return (fp, sp) if c.First == a else (sp, fp)
    if a < 0 or b < 0:
        return None
    try:
        best = None
        for pa in (START, END):
            for pb in (START, END):
                d = (sketch.getPoint(a, pa) - sketch.getPoint(b, pb)).Length
                if d <= TOL * (1.0 + sketch.getPoint(a, pa).Length) and (best is None or d < best[0]):
                    best = (d, pa, pb)
        return None if best is None else (best[1], best[2])
    except Exception:
        return None


def groups(sketch):
    """{group prefix: [constraint indices]} of the sketch's Equal Curvature relations."""
    out = {}
    for i, c in enumerate(sketch.Constraints):
        if c.Name.startswith(PREFIX):
            out.setdefault(c.Name.rsplit("_", 1)[0] + "_", []).append(i)
    return out


def _has(sketch, a, b):
    for indices in groups(sketch).values():
        for i in indices:
            c = sketch.Constraints[i]
            if c.Type == "Tangent" and {c.First, c.Second} == {a, b}:
                return True
    return False


def offer(sketch, a, b):
    ""

    try:
        ka, kb = _kind(sketch, a), _kind(sketch, b)
        if a == b or None in (ka, kb) or "spline" not in (ka, kb):
            return False
        if (ka != "spline" and a < 0) or (kb != "spline" and b < 0):
            return False        # FreeCAD's tangency at an end needs the other end's own geometry
        return shared_end(sketch, a, b) is not None and not _has(sketch, a, b)
    except Exception as err:
        _fw_log("fwsketch/eqcurv.py:offer", err)
        return False


# --- the spline's end ---------------------------------------------------------------------------
def _poles(sketch, b):
    """Geometry ids of spline b's pole circles, in pole order (shown first when hidden)."""
    def find():
        geo = sketch.Geometry[b]
        poles = geo.getPoles()
        out = [None] * len(poles)
        for c in sketch.Constraints:
            if c.Type == "InternalAlignment" and c.Second == b and type(sketch.Geometry[c.First]).__name__ == "Circle":
                centre = sketch.Geometry[c.First].Center
                j = min(range(len(poles)), key=lambda k: (poles[k] - centre).Length)
                out[j] = c.First
        return out
    out = find()
    if None in out:
        sketch.exposeInternalGeometry(b)
        out = find()
    return out


def _end(sketch, b, pos):
    """(P0, P1 pole id, P2 pole id, c) at end pos of spline b."""
    geo = sketch.Geometry[b]
    n = geo.Degree
    knots = list(geo.KnotSequence)
    weights = list(geo.getWeights())
    ids = _poles(sketch, b)
    if pos == END:
        top = knots[-1]
        knots = [top - k for k in reversed(knots)]
        weights = list(reversed(weights))
        ids = list(reversed(ids))
    k1 = knots[n + 1] - knots[1]
    k2 = knots[n + 2] - knots[2]
    c = n / (n - 1.0) * (k2 / k1) * (weights[1] ** 2 / (weights[0] * weights[2]))
    return ids[1], ids[2], c


def _turn(u, v):
    """1 when v is counterclockwise of u, else -1: the side the fixed angle opens to (exactly the
    construction's angle, whatever the start geometry)."""
    return 1.0 if u.x * v.y - u.y * v.x >= 0 else -1.0


def _line(sketch, p, q, made):
    """The id the hidden line from p to q will get (added with the others once their relations are known)."""
    if (q - p).Length < 1e-9:
        q = p + App.Vector(1e-3, 0, 0)
    made.append(Part.LineSegment(p, q))
    return sketch.GeometryCount + len(made) - 1


def _place(sketch, pole, where):
    """Start the solve near its answer: the third pole where the new relation wants it (it only reshapes
    the spline's end; where its own relations hold it, it stays)."""
    C = Sketcher.Constraint
    n = len(sketch.Constraints)
    try:
        # a pole circle cannot be dragged (moveGeometry refuses it): two passing dimensions take it there
        sketch.addConstraint([C("DistanceX", -1, START, pole, MID, where.x), C("DistanceY", -1, START, pole, MID, where.y)])
        sketch.solve()
    except Exception as err:
        _fw_log("fwsketch/eqcurv.py:place", err)
    while len(sketch.Constraints) > n:
        sketch.delConstraint(len(sketch.Constraints) - 1)
    sketch.solve()


def _osculate(sketch, b, pos, p1, p2, c, centre, normal, radius, made, cons):
    """Hold spline b's curvature at end pos to the circle of radius radius about centre ((geo, pos) of
    an existing point, or None: a new hidden centre, returned) on normal at the end."""
    C = Sketcher.Constraint
    P0 = sketch.getPoint(b, pos)
    P1 = sketch.Geometry[p1].Center
    t = P1 - P0
    al = max(t.Length, 1e-6)
    t.normalize()
    O = P0 + normal * radius
    hgt = c * al * al / radius
    _place(sketch, p2, P0 + t * (sketch.Geometry[p2].Center - P0).dot(t) + normal * hgt)
    P2 = sketch.Geometry[p2].Center
    tg = 1.0 / math.sqrt(c)
    X2, E, Y = P0 + normal * hgt, P0 + t * (hgt * tg), P0 - normal * (hgt * tg * tg)
    h0 = _line(sketch, O, Y, made)          # the normal, from the centre past the end
    h6 = _line(sketch, P0, P1, made)        # the tangent line
    h1 = _line(sketch, P1, O, made)
    h2 = _line(sketch, P1, Y, made)
    h3 = _line(sketch, P2, X2, made)
    h4 = _line(sketch, X2, E, made)
    h5 = _line(sketch, E, Y, made)
    cons += [C("Coincident", h0, START, *centre) if centre else None,
             C("PointOnObject", b, pos, h0),
             C("Coincident", h6, START, b, pos), C("Coincident", h6, END, p1, MID),
             C("Coincident", h1, START, p1, MID), C("Coincident", h1, END, h0, START),
             C("Coincident", h2, START, p1, MID), C("Coincident", h2, END, h0, END), C("Perpendicular", h1, h2),
             C("Coincident", h3, START, p2, MID), C("PointOnObject", h3, END, h0), C("Perpendicular", h3, h0),
             C("Coincident", h4, START, h3, END), C("PointOnObject", h4, END, h6),
             C("Angle", h0, h4, _turn(normal * -1, t) * math.atan(tg)),
             C("Coincident", h5, START, h4, END), C("Coincident", h5, END, h0, END), C("Perpendicular", h4, h5)]
    return h0, h6


def _flat(sketch, b, pos, p1, p2, made, cons):
    """Zero curvature at spline b's end pos: its third pole on the tangent line."""
    C = Sketcher.Constraint
    P0, P1 = sketch.getPoint(b, pos), sketch.Geometry[p1].Center
    t = P1 - P0
    if t.Length > 1e-9:
        t.normalize()
        _place(sketch, p2, P0 + t * (sketch.Geometry[p2].Center - P0).dot(t))
    h6 = _line(sketch, P0, P1, made)
    cons += [C("Coincident", h6, START, b, pos), C("Coincident", h6, END, p1, MID), C("PointOnObject", p2, MID, h6)]


def _side(sketch, b, pos, p1, p2):
    """(unit normal at the end towards the third pole, the end's radius of curvature or None)."""
    P0, P1, P2 = sketch.getPoint(b, pos), sketch.Geometry[p1].Center, sketch.Geometry[p2].Center
    t = P1 - P0
    if t.Length < 1e-9:
        return None, None
    t.normalize()
    n = App.Vector(-t.y, t.x, 0)
    h = (P2 - P0).dot(n)
    if h < 0:
        n, h = n * -1, -h
    return n, h


def own_tangents(sketch, indices):
    """Of the constraint indices about to be deleted: the Tangents the user had at the joint before
    Equal Curvature joined them to it. Deleting Equal Curvature leaves them (restore)."""
    out = []
    for i in indices:
        try:
            c = sketch.Constraints[i]
        except IndexError:
            continue
        if c.Type == "Tangent" and c.Name.startswith(PREFIX) and c.Name.rsplit("_", 1)[1] == OWN:
            out.append(i)
    return out


def joints(sketch, indices):
    ""


    out = []
    for i in indices:
        try:
            c = sketch.Constraints[i]
        except IndexError:
            continue
        if c.Type == "Tangent" and c.Name.startswith(PREFIX) and c.Name.rsplit("_", 1)[1] == "0" \
                and int(c.FirstPos) in (START, END) and int(c.SecondPos) in (START, END):
            out.append(Sketcher.Constraint("Coincident", c.First, int(c.FirstPos), c.Second, int(c.SecondPos)))
    return out


def restore(sketch, indices):
    """The user's own Tangents again: unnamed and shown, as before Equal Curvature."""
    for i in sorted(indices, reverse=True):
        try:
            sketch.renameConstraint(i, "")
        except Exception as err:
            _fw_log("fwsketch/eqcurv.py:restore name", err)
    if indices:
        try:
            sketch.setVirtualSpace(sorted(indices), False)
        except Exception as err:
            _fw_log("fwsketch/eqcurv.py:restore shown", err)


def add(sketch, a, b, removed=None):
    """Add Equal Curvature between edges a and b (offer() said yes). Leaves the solve to the caller.
    removed (a list) gets the indices of the constraints deleted first (the joint's Coincident)."""
    C = Sketcher.Constraint
    pa, pb = shared_end(sketch, a, b)
    if _kind(sketch, a) != "spline":
        a, b, pa, pb = b, a, pb, pa         # the spline first: stock refuses the tangency otherwise
    first = len(sketch.Constraints)
    # the shared end's tangency: an existing one is kept and joins the relation
    tangent = None
    for i, c in enumerate(sketch.Constraints):
        if c.Type == "Tangent" and {c.First, c.Second} == {a, b}:
            tangent = i
    own = tangent is not None
    if tangent is None:
        for i, c in reversed(list(enumerate(sketch.Constraints))):
            if c.Type == "Coincident" and {(c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos))} == {(a, pa), (b, pb)}:
                sketch.delConstraint(i)
                if removed is not None:
                    removed.append(i)
                first -= 1
        sketch.addConstraint(C("Tangent", a, pa, b, pb))
        tangent = len(sketch.Constraints) - 1
        sketch.solve()
    made, cons = [], []
    kb = _kind(sketch, b)
    p1a, p2a, ca = _end(sketch, a, pa)
    if kb == "line":
        _flat(sketch, a, pa, p1a, p2a, made, cons)
    elif kb == "arc":
        arc = sketch.Geometry[b]
        centre = arc.Center
        normal = centre - sketch.getPoint(a, pa)
        radius = normal.Length
        normal.normalize()
        _osculate(sketch, a, pa, p1a, p2a, ca, (b, MID), normal, radius, made, cons)
    else:
        p1b, p2b, cb = _end(sketch, b, pb)
        na, ha = _side(sketch, a, pa, p1a, p2a)
        nb, hb = _side(sketch, b, pb, p1b, p2b)
        la = (sketch.Geometry[p1a].Center - sketch.getPoint(a, pa)).Length
        lb = (sketch.Geometry[p1b].Center - sketch.getPoint(b, pb)).Length
        normal = na if na is not None else nb
        if normal is None:
            raise ValueError("a spline's end has no direction")
        r = [ca * la * la / ha] if ha and ha > 1e-9 else []
        if hb and hb > 1e-9:
            r.append(cb * lb * lb / hb)
        radius = min(r) if r else 10.0 * max(la, lb, 1.0)
        h0, h6 = _osculate(sketch, a, pa, p1a, p2a, ca, None, normal, radius, made, cons)
        cons.append(C("Perpendicular", h0, h6))     # the shared centre on the normal
        _osculate(sketch, b, pb, p1b, p2b, cb, (h0, START), normal, radius, made, cons)
    cons = [c for c in cons if c is not None]
    # each helper is held by every relation it is in: one gone (the arc deleted), the helper goes
    base = sketch.GeometryCount
    for j, g in enumerate(made):
        held = sum(1 for c in cons if base + j in (c.First, c.Second, c.Third))
        H.add_helper(sketch, g, KIND, held)
    n0 = len(sketch.Constraints)
    sketch.addConstraint(cons)
    names = {c.Name for c in sketch.Constraints}
    k = 0
    while any(nm.startswith("%s%d_" % (PREFIX, k)) for nm in names):
        k += 1
    members = [tangent] + list(range(n0, len(sketch.Constraints)))
    for j, i in enumerate(members):
        try:
            sketch.renameConstraint(i, "%s%d_%s" % (PREFIX, k, OWN if own and j == 0 else j))
        except Exception as err:
            _fw_log("fwsketch/eqcurv.py:name", err)
    # the Tangent too: FreeCAD would draw its Tangent glyph (stacked with the pole glyphs there); the joint
    # shows Equal Curvature's own square instead (fwsketch/pointglyphs.py, fix316)
    H._hide_relations(sketch, [tangent] + list(range(n0, len(sketch.Constraints))))
    return "%s%d_" % (PREFIX, k)
