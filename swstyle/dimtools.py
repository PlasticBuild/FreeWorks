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

ORIGIN = (-1, 1)
H_AXIS, V_AXIS = -1, -2

RELATIONS = ("Horizontal", "Vertical", "Collinear", "Perpendicular", "Parallel", "Midpoint",
             "Coincident", "Tangent", "Concentric", "Equal")
SCHEMES = ("Baseline", "Chain", "Ordinate")

LENGTH_TOL = 1e-4       # mm: points this close count as one, lengths this close as equal
ANGLE_TOL = 1e-3        # rad (about 0.06 degree): lines this close to an angle count as on it


def _constraint(*args):
    import Sketcher
    return Sketcher.Constraint(*args)


def _kind(geo):
    t = geo.TypeId
    if t == "Part::GeomLineSegment":
        return "line"
    if t == "Part::GeomCircle":
        return "circle"
    if t == "Part::GeomArcOfCircle":
        return "arc"
    if t == "Part::GeomPoint":
        return "point"
    if t in ("Part::GeomEllipse",):
        return "ellipse"
    if t.startswith("Part::GeomArcOf"):
        return "conic_arc"
    if t == "Part::GeomBSplineCurve":
        return "spline"
    return "other"


def _positions(kind):
    """The point positions of a geometry kind, centres first."""
    return {"line": (1, 2), "circle": (3,), "arc": (3, 1, 2), "point": (1,), "ellipse": (3,),
            "conic_arc": (3, 1, 2), "spline": (1, 2)}.get(kind, ())


class Sketch:
    """What the tools need from a sketch, read once per run."""

    def __init__(self, sketch, entities=None):
        self.sketch = sketch
        self.geos = list(sketch.Geometry)
        self.kinds = [_kind(g) for g in self.geos]
        self.only = set(entities) if entities else None

    def wanted(self, g):
        return self.only is None or g in self.only

    def point(self, g, pos):
        return self.sketch.getPoint(g, pos)

    def points(self):
        """[(geo, pos, vector)] of every point the tools may dimension."""
        out = []
        for g, kind in enumerate(self.kinds):
            if not self.wanted(g):
                continue
            for pos in _positions(kind):
                try:
                    out.append((g, pos, self.point(g, pos)))
                except Exception as _fw_err:
                    _fw_log("dimtools.py:102", _fw_err)
        return out

    def lines(self):
        return [g for g, k in enumerate(self.kinds) if k == "line" and self.wanted(g)]

    def rounds(self):
        return [g for g, k in enumerate(self.kinds) if k in ("circle", "arc") and self.wanted(g)]

    def size(self):
        pts = [v for _, _, v in self.points()] or [App.Vector()]
        xs, ys = [v.x for v in pts] + [0.0], [v.y for v in pts] + [0.0]
        return max(max(xs) - min(xs), max(ys) - min(ys), 1.0), (min(xs), max(xs), min(ys), max(ys))


# --------------------------------------------------------------------------- trying
def state(sketch):
    """(degrees of freedom, over-defined) after a solve."""
    sketch.solve()
    bad = bool(list(sketch.RedundantConstraints) or list(sketch.ConflictingConstraints)
               or list(getattr(sketch, "MalformedConstraints", []) or []))
    return sketch.DoF, bad


# fix232: a single addConstraint or delConstraint solves the sketch by itself while it is open
# (0.2 to 0.6 s each in a 500-line sketch), and every try solved it again. These add and take out
# without that solve, so each try solves once.
_QUIET = {"Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Horizontal", "Vertical",
          "PointOnObject", "Coincident", "Parallel", "Equal", "Symmetric"}
BATCH_FROM = 40     # geometries: from here on Fully Define tries its candidates together


def _add(sketch, constraint):
    if constraint.Type in _QUIET:
        return sketch.addConstraint([constraint])[0]
    return sketch.addConstraint(constraint)


def _drop(sketch, indices):
    indices = sorted(set(indices), reverse=True)
    if not indices:
        return
    try:
        sketch.delConstraints(indices)
    except Exception:
        for i in indices:
            sketch.delConstraint(i)


def attempt(sketch, constraint, before=None):
    """Adds the constraint when it takes away freedom without over-defining; its index, else None.
    before: the degrees of freedom when the caller has just solved (saves a solve)."""
    if before is None:
        before, _ = state(sketch)
    if before <= 0:
        return None
    try:
        index = _add(sketch, constraint)
    except Exception as _fw_err:
        _fw_log("dimtools.py:135", _fw_err)
        return None
    after, bad = state(sketch)
    if bad or after >= before:
        _drop(sketch, [index])
        sketch.solve()
        return None
    return index


def _flagged(sketch):
    found, clash = set(), set()
    for name in ("ConflictingConstraints", "RedundantConstraints", "MalformedConstraints"):
        try:
            ids = {i - 1 for i in (getattr(sketch, name, None) or [])}
        except Exception:
            ids = set()
        found |= ids
        if name != "RedundantConstraints":
            clash |= ids
    return found, clash


def attempt_many(sketch, constraints):
    """fix232: attempt() for many at once, for a large sketch. All are added, then the ones the
    solver names redundant or clashing among them are taken out, until the sketch is healthy:
    FreeCAD names the later ones of a redundant set, so the earlier ones are kept, as one by one.
    A clashing one is tried once more on its own at the end. Returns, per constraint, its index or
    None. The sketch must have been solved just before."""
    constraints = list(constraints)
    if not constraints:
        return []
    if sketch.DoF <= 0:
        return [None] * len(constraints)
    start = len(sketch.Constraints)
    try:
        sketch.addConstraint(constraints)
    except Exception as _fw_err:
        _fw_log("dimtools.py:batch", _fw_err)
        return _one_by_one(sketch, constraints)
    owner = list(range(len(constraints)))   # constraint start + k is constraints[owner[k]]
    retry = []
    healthy = False
    for _ in range(12):
        sketch.solve()
        found, clash = _flagged(sketch)
        if not found:
            healthy = True
            break
        new = sorted(i for i in found if start <= i < start + len(owner))
        App.Console.PrintLog("FreeCAD Fully Define: %d tried together, %d named (%d of them new)\n"
                             % (len(owner), len(found), len(new)))
        if not new:
            break
        retry += [owner[i - start] for i in new if i in clash]
        for i in reversed(new):
            owner.pop(i - start)
        _drop(sketch, new)
    if not healthy:
        # The solver named an older one (it names the one in most redundant sets, often a
        # Horizontal the sketch had): take the rest out again and try it in halves.
        rest = [constraints[n] for n in owner]
        _drop(sketch, range(start, start + len(owner)))
        sketch.solve()
        if len(rest) <= 4:
            got = _one_by_one(sketch, rest)
        else:
            half = len(rest) // 2
            got = attempt_many(sketch, rest[:half])
            got += attempt_many(sketch, rest[half:]) if sketch.DoF > 0 else [None] * (len(rest) - half)
        out = [None] * len(constraints)
        for n, index in zip(owner, got):
            out[n] = index
        for n in sorted(retry):
            if sketch.DoF > 0 and out[n] is None:
                out[n] = attempt(sketch, constraints[n], sketch.DoF)
        return out
    out = [None] * len(constraints)
    for k, n in enumerate(owner):
        out[n] = start + k
    for n in sorted(retry):
        if sketch.DoF <= 0:
            break
        out[n] = attempt(sketch, constraints[n], sketch.DoF)
    return out


def _one_by_one(sketch, constraints):
    out = []
    for c in constraints:
        out.append(attempt(sketch, c, sketch.DoF) if sketch.DoF > 0 else None)
    return out


def _many(sketch, sk, constraints):
    """attempt_many for a large sketch, else one by one: the indices kept, per constraint."""
    if len(sk.geos) >= BATCH_FROM:
        return attempt_many(sketch, constraints)
    return _one_by_one(sketch, constraints)


# --------------------------------------------------------------------------- relations
def _direction(sk, g):
    a, b = sk.point(g, 1), sk.point(g, 2)
    d = b - a
    return d, d.Length


def _angle_between(u, v):
    """Angle in [0, pi/2] between two undirected directions."""
    if u.Length == 0 or v.Length == 0:
        return math.pi / 2
    c = abs(u.dot(v)) / (u.Length * v.Length)
    return math.acos(max(-1.0, min(1.0, c)))


def _on_line(p, a, b, tol):
    d = b - a
    if d.Length < tol:
        return False
    t = (p - a).dot(d) / (d.Length ** 2)
    if t <= 1e-6 or t >= 1 - 1e-6:
        return False
    foot = a + d * t
    return (p - foot).Length < tol


def _tangent_at(sk, g, pos):
    """Unit tangent direction of a line or arc at an end, else None."""
    kind = sk.kinds[g]
    if kind == "line":
        d, n = _direction(sk, g)
        return d * (1.0 / n) if n > 0 else None
    if kind == "arc":
        c = sk.point(g, 3)
        r = sk.point(g, pos) - c
        if r.Length == 0:
            return None
        t = App.Vector(-r.y, r.x, 0)
        return t * (1.0 / t.Length)
    return None


def relation_candidates(sk, kinds):
    """(name, constraint) in the order Fully Define tries them."""
    out = []
    lines = sk.lines()
    rounds = sk.rounds()
    pts = sk.points()
    tol = LENGTH_TOL
    # fix232: relations the sketch already holds are not tried again (each try is a solve)
    ties = _Ties(sk.sketch)
    held_hv, joined = ties.hv, ties.joined
    if "Horizontal" in kinds or "Vertical" in kinds:
        for g in lines:
            d, n = _direction(sk, g)
            if n < tol or g in held_hv:
                continue
            if "Horizontal" in kinds and abs(d.y) / n < ANGLE_TOL:
                out.append(("Horizontal", _constraint("Horizontal", g)))
                ties.add(out[-1][1])
            elif "Vertical" in kinds and abs(d.x) / n < ANGLE_TOL:
                out.append(("Vertical", _constraint("Vertical", g)))
                ties.add(out[-1][1])
    if "Concentric" in kinds:
        for i, a in enumerate(rounds):
            for b in rounds[i + 1:]:
                if (sk.point(a, 3) - sk.point(b, 3)).Length < tol:
                    out.append(("Concentric", _constraint("Coincident", a, 3, b, 3)))
    if "Tangent" in kinds:
        ends = [(g, p, v) for g, p, v in pts if p in (1, 2) and sk.kinds[g] in ("line", "arc")]
        for i, (ga, pa, va) in enumerate(ends):
            for gb, pb, vb in ends[i + 1:]:
                if ga == gb or (va - vb).Length >= tol or "arc" not in (sk.kinds[ga], sk.kinds[gb]):
                    continue
                ta, tb = _tangent_at(sk, ga, pa), _tangent_at(sk, gb, pb)
                if ta is not None and tb is not None and _angle_between(ta, tb) < ANGLE_TOL:
                    out.append(("Tangent", _constraint("Tangent", ga, pa, gb, pb)))
    if "Coincident" in kinds:
        for i, (ga, pa, va) in enumerate(pts):
            for gb, pb, vb in pts[i + 1:]:
                if ga != gb and (va - vb).Length < tol and not joined.same((ga, pa), (gb, pb)):
                    out.append(("Coincident", _constraint("Coincident", ga, pa, gb, pb)))
                    ties.add(out[-1][1])
            # fix259: one point of a joined corner on the origin is enough (the others were named
            # redundant one per solve, seconds each on a large sketch)
            if (va - App.Vector()).Length < tol and not joined.same((ga, pa), ORIGIN):
                out.append(("Coincident", _constraint("Coincident", ga, pa, *ORIGIN)))
                ties.add(out[-1][1])
    if "Midpoint" in kinds:
        for g in lines:
            a, b = sk.point(g, 1), sk.point(g, 2)
            mid = (a + b) * 0.5
            for gp, pp, vp in pts:
                if gp != g and (vp - mid).Length < tol:
                    out.append(("Midpoint", _constraint("Symmetric", g, 1, g, 2, gp, pp)))
    if "Coincident" in kinds:
        for gp, pp, vp in pts:
            for g in lines:
                if g != gp and _on_line(vp, sk.point(g, 1), sk.point(g, 2), tol):
                    out.append(("Coincident", _constraint("PointOnObject", gp, pp, g)))
            for g in rounds:
                if g == gp:
                    continue
                r = sk.geos[g].Radius
                if abs((vp - sk.point(g, 3)).Length - r) < tol and not any(
                        (vp - sk.point(g, q)).Length < tol for q in _positions(sk.kinds[g])):
                    out.append(("Coincident", _constraint("PointOnObject", gp, pp, g)))
            # fix232: not when the point is already level with the origin (a Horizontal line to one on the axis)
            if abs(vp.y) < tol and abs(vp.x) >= tol and not ties.ys.same((gp, pp), ORIGIN):
                out.append(("Coincident", _constraint("PointOnObject", gp, pp, H_AXIS)))
                ties.add(out[-1][1])
            if abs(vp.x) < tol and abs(vp.y) >= tol and not ties.xs.same((gp, pp), ORIGIN):
                out.append(("Coincident", _constraint("PointOnObject", gp, pp, V_AXIS)))
                ties.add(out[-1][1])
    if len(sk.geos) >= BATCH_FROM:
        out += _line_sets(sk, lines, kinds, ties)
        lines = []      # every pair below would be tried: tens of thousands in a 500-line sketch
    for i, a in enumerate(lines):
        da, na = _direction(sk, a)
        if na < tol:
            continue
        for b in lines[i + 1:]:
            db, nb = _direction(sk, b)
            if nb < tol:
                continue
            ang = _angle_between(da, db)
            if ang < ANGLE_TOL:
                pa = sk.point(a, 1)
                off = (sk.point(b, 1) - pa)
                cross = abs(off.x * da.y - off.y * da.x) / na
                if "Collinear" in kinds and cross < tol:
                    out.append(("Collinear", _constraint("Tangent", a, b)))
                elif "Parallel" in kinds:
                    out.append(("Parallel", _constraint("Parallel", a, b)))
            elif "Perpendicular" in kinds and abs(ang - math.pi / 2) < ANGLE_TOL:
                out.append(("Perpendicular", _constraint("Perpendicular", a, b)))
    if "Equal" in kinds:
        for group in equal_groups(sk):
            a = group[0]
            taken = [a]
            for b in group[1:]:
                if b in ties.hv and sk.kinds[b] == "line" and len(sk.geos) >= BATCH_FROM:
                    db = _direction(sk, b)[0]
                    flat = abs(db.y) < abs(db.x)
                    if any(m in ties.hv and sk.kinds[m] == "line"
                           and (abs(_direction(sk, m)[0].y) < abs(_direction(sk, m)[0].x)) == flat
                           and ties.same_length(m, b, flat) for m in taken):
                        continue    # fix232: equal already to one made equal (the far side of a rectangle)
                taken.append(b)
                out.append(("Equal", _constraint("Equal", a, b)))
    return out


class _Joined:
    """Points tied by Coincident (union-find), to leave out a Coincident the sketch already has."""

    def __init__(self):
        self.up = {}

    def root(self, p):
        while self.up.get(p, p) != p:
            p = self.up[p]
        return p

    def same(self, a, b):
        return self.root(a) == self.root(b)

    def join(self, a, b):
        ra, rb = self.root(a), self.root(b)
        if ra != rb:
            self.up[ra] = rb


class _Ties:
    """What the sketch already ties (fix232): lines held Horizontal or Vertical, points made
    coincident, and points that already share their x (xs) or their y (ys) through Coincident,
    a Vertical or Horizontal line or point pair, or a point on an axis."""

    def __init__(self, sketch):
        self.hv = set()
        self.joined, self.xs, self.ys = _Joined(), _Joined(), _Joined()
        self.equal = _Joined()      # lines made Equal
        self.sized = set()          # lines with a length dimension
        self.turns = []             # fix234: (a, b) pairs whose directions are tied (Parallel, Perpendicular, ...)
        try:
            for c in sketch.Constraints:
                if getattr(c, "IsActive", True):
                    self.add(c)
        except Exception as _fw_err:
            _fw_log("dimtools.py:held", _fw_err)

    def add(self, c):
        t = c.Type
        single = c.Second in (None, -2000)
        if t in ("Horizontal", "Vertical"):
            group = self.ys if t == "Horizontal" else self.xs
            if single and c.First >= 0:
                self.hv.add(c.First)
                group.join((c.First, 1), (c.First, 2))
                self.turns.append((c.First, "axis"))
            elif not single:
                group.join((c.First, c.FirstPos), (c.Second, c.SecondPos))
        elif t == "Coincident":
            a, b = (c.First, c.FirstPos), (c.Second, c.SecondPos)
            for group in (self.joined, self.xs, self.ys):
                group.join(a, b)
        elif t in ("Parallel", "Perpendicular", "Angle", "Tangent") and c.First >= 0 and c.Second not in (None, -2000) \
                and c.Second >= 0 and c.FirstPos == 0 and c.SecondPos == 0:
            self.turns.append((c.First, c.Second))     # kept for lines only (_position_batch)
        elif t == "Angle" and single and c.First >= 0:
            self.turns.append((c.First, "axis"))       # a line's angle to the horizontal
        elif t == "Equal" and c.First >= 0 and c.Second >= 0:
            self.equal.join(c.First, c.Second)
        elif t == "Distance" and single and c.First >= 0:
            self.sized.add(c.First)
        elif t == "PointOnObject" and c.Second in (H_AXIS, V_AXIS):
            (self.ys if c.Second == H_AXIS else self.xs).join((c.First, c.FirstPos), ORIGIN)

    def same_length(self, a, b, horizontal):
        """Two horizontal (or vertical) lines whose ends already share their x (or y)."""
        g = self.xs if horizontal else self.ys
        a1, a2, b1, b2 = (g.root((a, 1)), g.root((a, 2)), g.root((b, 1)), g.root((b, 2)))
        return {a1, a2} == {b1, b2} and a1 != a2


def _held(sketch):
    ties = _Ties(sketch)
    return ties.hv, ties.joined


def _line_sets(sk, lines, kinds, ties):
    """fix232, a large sketch: lines in sets of one direction, and those in sets on one line. Each
    is related to the first of its set (Collinear, else Parallel to the first of the direction),
    and one Perpendicular per pair of directions, instead of every pair of lines. Parallel and
    Perpendicular between lines that are all horizontal or vertical already are left out."""
    tol = LENGTH_TOL
    held_hv = ties.hv
    dirs = []       # [direction, [lines]]
    for g in lines:
        d, n = _direction(sk, g)
        if n < tol:
            continue
        for entry in dirs:
            if _angle_between(entry[0], d) < ANGLE_TOL:
                entry[1].append(g)
                break
        else:
            dirs.append([d, [g]])
    out = []
    for d, members in dirs:
        n = d.Length
        rows = []   # [offset, [lines]]: lines on one infinite line
        for g in members:
            p = sk.point(g, 1)
            off = (p.x * d.y - p.y * d.x) / n
            for row in rows:
                if abs(row[0] - off) < tol and "Collinear" in kinds:
                    row[1].append(g)
                    break
            else:
                rows.append([off, [g]])
        for row in rows:
            for b in row[1][1:]:
                a = row[1][0]
                if a in held_hv and b in held_hv:
                    # both horizontal (vertical) already: FreeCAD's Collinear would repeat that and
                    # over-define, as one at a time finds; the position dimensions place them
                    continue
                out.append(("Collinear", _constraint("Tangent", a, b)))
        if "Parallel" in kinds:
            first = rows[0][1][0]
            for row in rows[1:]:
                b = row[1][0]
                if not (first in held_hv and b in held_hv):
                    out.append(("Parallel", _constraint("Parallel", first, b)))
    if "Perpendicular" in kinds:
        for i, (da, ma) in enumerate(dirs):
            for db, mb in dirs[i + 1:]:
                if abs(_angle_between(da, db) - math.pi / 2) < ANGLE_TOL and not (
                        ma[0] in held_hv and mb[0] in held_hv):
                    out.append(("Perpendicular", _constraint("Perpendicular", ma[0], mb[0])))
    return out


def equal_groups(sk, lengths=True, radii=True):
    """Lists of lines of one length, then of circles and arcs of one radius (two or more each)."""
    groups = []
    if lengths:
        groups += _group(sk.lines(), lambda g: _direction(sk, g)[1])
    if radii:
        groups += _group(sk.rounds(), lambda g: sk.geos[g].Radius)
    return groups


def _group(geos, measure):
    out = []
    for g in geos:
        value = measure(g)
        for group in out:
            if abs(group[0] - value) < LENGTH_TOL:
                group[1].append(g)
                break
        else:
            out.append((value, [g]))
    return [members for _, members in out if len(members) > 1]


def add_relations(sketch, sk, kinds):
    """Tries every fitting relation; {name: count} of those kept."""
    kept = {}
    found = relation_candidates(sk, kinds)
    for (name, _), index in zip(found, _many(sketch, sk, [c for _, c in found])):
        if index is not None:
            kept[name] = kept.get(name, 0) + 1
    return kept


# --------------------------------------------------------------------------- dimensions
def _along(v, axis):
    return v.x if axis == "x" else v.y


def _datum_point(sketch, datum):
    g, pos = datum
    return sketch.getPoint(g, pos)


def _distance(axis, a, b, value):
    """A horizontal (x) or vertical (y) distance from point a to point b, kept positive."""
    name = "DistanceX" if axis == "x" else "DistanceY"
    if value < 0:
        a, b, value = b, a, -value
    return _constraint(name, a[0], a[1], b[0], b[1], value)


def _aligned(axis, a, b):
    """The relation that puts two points at the same x (Vertical) or y (Horizontal)."""
    if a == ORIGIN:
        return _constraint("PointOnObject", b[0], b[1], V_AXIS if axis == "x" else H_AXIS)
    if b == ORIGIN:
        return _constraint("PointOnObject", a[0], a[1], V_AXIS if axis == "x" else H_AXIS)
    return _constraint("Vertical" if axis == "x" else "Horizontal", a[0], a[1], b[0], b[1])


def _position_dimensions(sketch, sk, axis, scheme, datum, step, placed):
    """Dimensions every point's position along one axis; the indices added."""
    added = []
    origin = _along(_datum_point(sketch, datum), axis)
    pts = sorted(sk.points(), key=lambda e: (abs(_along(e[2], axis) - origin), e[0], e[1]))
    if scheme != "Chain" and len(sk.geos) >= BATCH_FROM:
        return _position_batch(sketch, sk, axis, datum, origin, pts, placed)
    sketch.solve()
    previous = {1: datum, -1: datum}    # chain: the last point dimensioned on each side of the datum
    behind = {1: datum, -1: datum}      # and where its dimension starts
    for g, pos, v in pts:
        if sketch.DoF <= 0:      # fix232: attempt() leaves the sketch solved
            break
        here = (g, pos)
        if here == datum:
            continue
        offset = _along(sketch.getPoint(g, pos), axis) - origin
        side = 1 if offset >= 0 else -1
        start = previous[side] if scheme == "Chain" else datum
        value = _along(sketch.getPoint(g, pos), axis) - _along(_datum_point(sketch, start), axis)
        if abs(value) < LENGTH_TOL and scheme == "Chain" and start != datum:
            # level with the last link of the chain: measure from where that link starts
            start = behind[side]
            value = _along(sketch.getPoint(g, pos), axis) - _along(_datum_point(sketch, start), axis)
        if abs(value) < LENGTH_TOL:
            index = attempt(sketch, _aligned(axis, start, here), sketch.DoF)
        else:
            index = attempt(sketch, _distance(axis, start, here, value), sketch.DoF)
        if index is None:
            continue
        added.append(index)
        if abs(value) >= LENGTH_TOL:
            if here != previous[side] and _along(_datum_point(sketch, previous[side]), axis) != \
                    _along(sketch.getPoint(g, pos), axis):
                behind[side], previous[side] = start, here
            placed.append((index, axis, start, here))
    return added + _tie_datum(sketch, axis, datum, placed)


def _tie_datum(sketch, axis, datum, placed):
    added = []
    if datum != ORIGIN and state(sketch)[0] > 0:
        # A sketch point as datum: the whole scheme still slides until the datum is tied to the origin
        value = _along(_datum_point(sketch, datum), axis)
        c = _aligned(axis, ORIGIN, datum) if abs(value) < LENGTH_TOL else _distance(axis, ORIGIN, datum, value)
        index = attempt(sketch, c)
        if index is not None:
            added.append(index)
            if abs(value) >= LENGTH_TOL:
                placed.append((index, axis, ORIGIN, datum))
    return added


def _parallelograms(sk, ties, turn, is_line):
    """fix234: four lines closed by Coincident ends whose opposite sides are held parallel (one
    direction set, and parallel now) form a parallelogram: opposite sides are of one length, so
    they go in one Equal set (ties.equal) for _position_batch."""
    ends = {}
    at = {}
    for g in is_line:
        p, q = ties.joined.root((g, 1)), ties.joined.root((g, 2))
        if p == q:
            continue
        ends[g] = (p, q)
        at.setdefault(p, []).append(g)
        at.setdefault(q, []).append(g)

    def parallel(a, b):
        if turn.root(a) != turn.root(b):
            return False
        u, v = _direction(sk, a)[0], _direction(sk, b)[0]
        return abs(u.x * v.y - u.y * v.x) <= 1e-6 * max(u.Length * v.Length, 1e-12)

    def other(g, p):
        a, b = ends[g]
        return b if a == p else a

    for m, (p, q) in ends.items():
        for e in at.get(p, ()):
            if e == m:
                continue
            r = other(e, p)
            for n in at.get(r, ()):
                if n in (m, e) or not parallel(m, n):
                    continue
                s_ = other(n, r)
                if s_ in (p, q, r):
                    continue
                for f in at.get(s_, ()):
                    if f not in (m, e, n) and other(f, s_) == q and parallel(e, f):
                        ties.equal.join(m, n)
                        ties.equal.join(e, f)


def _position_batch(sketch, sk, axis, datum, origin, pts, placed):
    """fix232: Baseline and Ordinate positions of a large sketch, tried together (attempt_many).
    A point already tied by Coincident to one in the list is left out."""
    ties = _Ties(sketch)
    joined = ties.xs if axis == "x" else ties.ys
    # fix234: a line whose length and direction are known places its other end once one end is
    # placed. Its length is known by a length dimension, by Equal to such a line, or once both
    # ends are placed and its direction is known; its direction is known when it is held
    # Horizontal or Vertical, by Parallel, Perpendicular, Angle or Collinear to such a line, or
    # once both ends are placed and its length is known. A point placed that way is left out: its
    # dimension would over-define the sketch, and the solver names such repeats one per solve
    # (minutes in a grid of rectangles, more with tilted ones: Reviewer round 4, 205 s).
    # What one axis learns (lengths, directions) holds for the other axis too.
    lines = []
    for g in range(len(sk.geos)):
        if sk.kinds[g] != "line":
            continue
        d, n = _direction(sk, g)
        if n < LENGTH_TOL:
            continue
        if abs(d.x if axis == "x" else d.y) / n > 0.05:     # not across the axis: says something along it
            lines.append(g)
    is_line = set(g for g in range(len(sk.geos)) if sk.kinds[g] == "line")
    turn = _Joined()
    for a_, b_ in ties.turns:
        if a_ in is_line and (b_ == "axis" or b_ in is_line):
            turn.join(a_, b_)
    _parallelograms(sk, ties, turn, is_line)
    learned = getattr(sk, "_fd_learned", None)
    if learned is None:
        learned = sk._fd_learned = {"turn": set(), "length": set()}
    known_turn = {turn.root("axis")} | {turn.root(g) for g in learned["turn"]}
    known_len = {ties.equal.root(g) for g in ties.sized} | {ties.equal.root(g) for g in learned["length"]}
    seen = {joined.root(datum)}
    # fix259: what the other axis placed. A line whose two ends are placed on the other axis
    # (and that crosses it) has its direction and length known as soon as both its ends are
    # placed on this axis too; with its direction known, one end placed here places the other.
    # Without this the solver named those repeats a few per solve (a 400-line sketch: 13 solves of
    # 3 s each on the vertical positions); the dimensions kept are the same.
    other = learned.get("placed_" + ("y" if axis == "x" else "x"), set())
    cross = set()
    for g in lines:
        d, n = _direction(sk, g)
        if (g, 1) in other and (g, 2) in other and abs(d.y if axis == "x" else d.x) / n > 0.05:
            cross.add(g)

    def spread():
        grew = True
        while grew:
            grew = False
            for g in lines:
                a, b = joined.root((g, 1)), joined.root((g, 2))
                cls, way = ties.equal.root(g), turn.root(g)
                if a in seen and b in seen:
                    if g in cross:
                        if way not in known_turn:
                            known_turn.add(way)
                            grew = True
                        if cls not in known_len:
                            known_len.add(cls)
                            grew = True
                    elif way in known_turn and cls not in known_len:
                        known_len.add(cls)
                        grew = True
                    elif cls in known_len and way not in known_turn:
                        known_turn.add(way)
                        grew = True
                elif (a in seen or b in seen) and way in known_turn and (cls in known_len or g in cross):
                    seen.add(b if a in seen else a)
                    grew = True
    spread()
    tries = []
    for g, pos, v in pts:
        here = (g, pos)
        if here == datum:
            continue
        root = joined.root(here)
        if root in seen:
            continue
        seen.add(root)
        spread()
        value = _along(sketch.getPoint(g, pos), axis) - _along(_datum_point(sketch, datum), axis)
        c = _aligned(axis, datum, here) if abs(value) < LENGTH_TOL else _distance(axis, datum, here, value)
        tries.append((here, value, c))
    sketch.solve()
    added = []
    for (here, value, c), index in zip(tries, attempt_many(sketch, [c for _, _, c in tries])):
        if index is None:
            continue
        added.append(index)
        if abs(value) >= LENGTH_TOL:
            placed.append((index, axis, datum, here))
    learned["placed_" + axis] = {(g, pos) for g in is_line for pos in (1, 2) if joined.root((g, pos)) in seen}
    for g in is_line:
        if turn.root(g) in known_turn:
            learned["turn"].add(g)
        if ties.equal.root(g) in known_len:
            learned["length"].add(g)
    # attempt_many may keep a retried one after the block: placed in the order of the indices
    placed.sort(key=lambda e: e[0])
    return sorted(added) + _tie_datum(sketch, axis, datum, placed)


def _size_dimensions(sketch, sk):
    tries = []
    for g in sk.rounds():
        r = sk.geos[g].Radius
        tries.append(_constraint("Diameter", g, 2 * r) if sk.kinds[g] == "circle" else _constraint("Radius", g, r))
    sketch.solve()
    return [i for i in _many(sketch, sk, tries) if i is not None]


def _leftovers(sketch, sk):
    """Anything still free after the positions: line lengths, then angles to the horizontal."""
    added = []
    sketch.solve()
    for g in sk.lines():
        if sketch.DoF <= 0:      # fix232: attempt() leaves the sketch solved
            break
        d, n = _direction(sk, g)
        index = attempt(sketch, _constraint("Distance", g, n), sketch.DoF)
        if index is None:
            index = attempt(sketch, _constraint("Angle", g, math.atan2(d.y, d.x)), sketch.DoF)
        if index is not None:
            added.append(index)
    return added


def _place_labels(sketch, sk, placed, h_side, v_side):
    ""

    size, (x0, x1, y0, y1) = sk.size()
    gap = max(size * 0.08, 2.0)
    count = {"x": 0, "y": 0}
    for index, axis, a, b in placed:
        count[axis] += 1
        c = sketch.Constraints[index]
        # Values are kept positive, so a horizontal distance always runs left to right and a
        # vertical one bottom to top: a positive label distance is above, or left of, the line.
        pa, pb = sketch.getPoint(c.First, c.FirstPos), sketch.getPoint(c.Second, c.SecondPos)
        if axis == "x":
            edge = y1 if h_side > 0 else y0
            far = max(pa.y, pb.y) if h_side > 0 else min(pa.y, pb.y)
            want = ((edge - far) * h_side + gap * count[axis]) * h_side
        else:
            edge = x1 if v_side > 0 else x0
            far = max(pa.x, pb.x) if v_side > 0 else min(pa.x, pb.x)
            want = -((edge - far) * v_side + gap * count[axis]) * v_side
        try:
            sketch.setLabelDistance(index, want)
        except Exception as _fw_err:
            _fw_log("dimtools.py:426", _fw_err)


def add_dimensions(sketch, sk, h_scheme="Baseline", v_scheme="Baseline", h_datum=ORIGIN, v_datum=ORIGIN,
                   h_side=1, v_side=1):
    """Diameters and radii, then horizontal then vertical positions; the indices added."""
    placed = []
    added = _size_dimensions(sketch, sk)
    added += _position_dimensions(sketch, sk, "x", h_scheme, h_datum, None, placed)
    added += _position_dimensions(sketch, sk, "y", v_scheme, v_datum, None, placed)
    added += _leftovers(sketch, sk)
    _place_labels(sketch, sk, placed, h_side, v_side)
    return added


# --------------------------------------------------------------------------- the whole run
def fully_define(sketch, relations=RELATIONS, dimensions=True, entities=None, h_scheme="Baseline",
                 v_scheme="Baseline", h_datum=ORIGIN, v_datum=ORIGIN, h_side=1, v_side=1):
    ""

    result = {"relations": {}, "dimensions": 0, "dof": None, "over": False}
    dof, bad = state(sketch)
    if bad:
        result["over"], result["dof"] = True, dof
        return result
    sk = Sketch(sketch, entities)
    if relations:
        result["relations"] = add_relations(sketch, sk, set(relations))
        sk = Sketch(sketch, entities)
    if dimensions:
        result["dimensions"] = len(add_dimensions(sketch, sk, h_scheme, v_scheme, h_datum, v_datum,
                                                  h_side, v_side))
    result["dof"] = state(sketch)[0]
    return result


def describe(result):
    """One line for the PropertyManager and the status bar."""
    if result.get("over"):
        return "The sketch is over defined. Resolve that first (Display/Delete Relations)."
    parts = []
    n = sum(result["relations"].values())
    if n:
        parts.append("%d relation%s" % (n, "" if n == 1 else "s"))
    if result["dimensions"]:
        parts.append("%d dimension%s" % (result["dimensions"], "" if result["dimensions"] == 1 else "s"))
    added = "Added " + " and ".join(parts) + "." if parts else "Nothing to add."
    if result["dof"] == 0:
        return added + " The sketch is fully defined."
    return added + " %d degree%s of freedom left." % (result["dof"], "" if result["dof"] == 1 else "s")
