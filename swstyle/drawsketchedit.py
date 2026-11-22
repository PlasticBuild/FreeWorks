
"""Midpoint Line, Sketch Fillet / Sketch Chamfer, Trim Entities, Convert Entities, Offset Entities, Mirror Entities,
Linear / Circular Sketch Pattern, Move / Copy / Rotate / Scale Entities, Display/Delete Relations, Add Relation and
Quick Snaps, working on the drawing sketch entities drawsketch records in a view (SWSketchEntities: kind|tags|points
in view geometry; each entity is TechDraw cosmetic geometry of that view)."""

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

from . import drawings as D
from . import drawviews as DV
from . import drawsketch as SK

V = App.Vector
EPS = 1e-6
PICK_MM = 2.0              # how near (sheet mm) a click must be to pick an entity
RING_KINDS = ("Rectangle",) + SK.CLOSED_POLY
LINE_KINDS = ("Line", "Centerline", "Polyline")


# --------------------------------------------------------------------------- geometry of entities
def _d(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _arc_of(pts):
    """(centre, r, a0, a1) of an Arc entity [c, s, e] (counterclockwise s -> e, degrees)."""
    c, s, e = pts[:3]
    return (c, _d(c, s), math.degrees(math.atan2(s[1] - c[1], s[0] - c[0])),
            math.degrees(math.atan2(e[1] - c[1], e[0] - c[0])))


def _on_arc(a, a0, a1):
    span = (a1 - a0) % 360.0 or 360.0
    return (a - a0) % 360.0 <= span + 1e-7


def chain(kind, pts):
    """The points an entity runs through when it is straight pieces (closed rings end on their first point)."""
    if kind in LINE_KINDS:
        return list(pts)
    if kind in RING_KINDS:
        return list(pts) + [pts[0]]
    if kind == "Spline":
        return SK.spline_points(pts)
    return None


def prims(kind, pts):
    """('L', a, b) pieces, ('C', c, r) circles and ('A', c, r, a0, a1) arcs of an entity."""
    ch = chain(kind, pts)
    if ch is not None:
        return [("L", ch[i], ch[i + 1]) for i in range(len(ch) - 1)]
    if kind == "Circle" and len(pts) >= 2:
        return [("C", pts[0], _d(pts[0], pts[1]))]
    if kind == "Arc" and len(pts) >= 3:
        c, r, a0, a1 = _arc_of(pts)
        return [("A", c, r, a0, a1)]
    return []


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < EPS else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    q = (a[0] + dx * t, a[1] + dy * t)
    return _d(p, q), t


def prim_dist(p, pr):
    if pr[0] == "L":
        return _seg_dist(p, pr[1], pr[2])[0]
    c, r = pr[1], pr[2]
    if pr[0] == "C":
        return abs(_d(p, c) - r)
    a = math.degrees(math.atan2(p[1] - c[1], p[0] - c[0]))
    if _on_arc(a, pr[3], pr[4]):
        return abs(_d(p, c) - r)
    ends = [(c[0] + r * math.cos(math.radians(x)), c[1] + r * math.sin(math.radians(x))) for x in (pr[3], pr[4])]
    return min(_d(p, e) for e in ends)


def _line_hits(a, b, pr):
    """Parameters t (0..1 along a-b) where the segment a-b meets the primitive."""
    out = []
    if pr[0] == "L":
        c, d = pr[1], pr[2]
        r = (b[0] - a[0], b[1] - a[1])
        s = (d[0] - c[0], d[1] - c[1])
        den = r[0] * s[1] - r[1] * s[0]
        if abs(den) < 1e-12:
            return out
        t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
        u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
        if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
            out.append(t)
        return out
    c, R = pr[1], pr[2]
    dx, dy = b[0] - a[0], b[1] - a[1]
    fx, fy = a[0] - c[0], a[1] - c[1]
    A = dx * dx + dy * dy
    B = 2 * (fx * dx + fy * dy)
    C = fx * fx + fy * fy - R * R
    disc = B * B - 4 * A * C
    if A < EPS or disc < 0:
        return out
    for sgn in (-1, 1):
        t = (-B + sgn * math.sqrt(disc)) / (2 * A)
        if -1e-9 <= t <= 1 + 1e-9:
            q = (a[0] + dx * t, a[1] + dy * t)
            if pr[0] == "C" or _on_arc(math.degrees(math.atan2(q[1] - c[1], q[0] - c[0])), pr[3], pr[4]):
                out.append(t)
    return out


def _circle_hits(c, R, pr):
    """Angles (degrees) on the circle c, R where it meets the primitive."""
    out = []
    if pr[0] == "L":
        a, b = pr[1], pr[2]
        for t in _line_hits(a, b, ("C", c, R)):
            q = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            out.append(math.degrees(math.atan2(q[1] - c[1], q[0] - c[0])))
        return out
    c2, R2 = pr[1], pr[2]
    d = _d(c, c2)
    if d < EPS or d > R + R2 + 1e-9 or d < abs(R - R2) - 1e-9:
        return out
    a = (R * R - R2 * R2 + d * d) / (2 * d)
    h = math.sqrt(max(0.0, R * R - a * a))
    mx, my = c[0] + a * (c2[0] - c[0]) / d, c[1] + a * (c2[1] - c[1]) / d
    for sgn in (-1, 1):
        q = (mx + sgn * h * (c2[1] - c[1]) / d, my - sgn * h * (c2[0] - c[0]) / d)
        if pr[0] == "C" or _on_arc(math.degrees(math.atan2(q[1] - c2[1], q[0] - c2[0])), pr[3], pr[4]):
            out.append(math.degrees(math.atan2(q[1] - c[1], q[0] - c[0])))
    return out


def _box(pr):
    if pr[0] == "L":
        (ax, ay), (bx, by) = pr[1], pr[2]
        return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)
    (cx, cy), r = pr[1], pr[2]
    return cx - r, cy - r, cx + r, cy + r


def intersections(view, skip=None):
    """Every point where two entities of the view's sketch cross (Quick Snaps: Intersection)."""
    ents = SK.entities(view)
    items = []
    for i, (k, _t, p) in enumerate(ents):
        for pr in prims(k, p):
            items.append((i, pr, _box(pr)))
    items.sort(key=lambda x: x[2][0])
    out = []
    for n, (i, a, ba) in enumerate(items):
        for j, b, bb in items[n + 1:]:
            if bb[0] > ba[2] + 1e-9:
                break
            if i == j or bb[1] > ba[3] + 1e-9 or bb[3] < ba[1] - 1e-9:
                continue
            if a[0] == "L":
                for t in _line_hits(a[1], a[2], b):
                    out.append((a[1][0] + (a[2][0] - a[1][0]) * t, a[1][1] + (a[2][1] - a[1][1]) * t))
            elif b[0] == "L":
                for t in _line_hits(b[1], b[2], a):
                    out.append((b[1][0] + (b[2][0] - b[1][0]) * t, b[1][1] + (b[2][1] - b[1][1]) * t))
            else:
                for ang in _circle_hits(a[1], a[2], b):
                    r = math.radians(ang)
                    out.append((a[1][0] + a[2] * math.cos(r), a[1][1] + a[2] * math.sin(r)))
    return out


# --------------------------------------------------------------------------- entities: draw, add, remove
def draw(view, kind, pts):
    """The cosmetic geometry of an entity: its tags."""
    if kind in ("Line", "Centerline"):
        return [SK.line(view, pts[0], pts[1], SK.CENTER if kind == "Centerline" else SK.SOLID)]
    ch = chain(kind, pts)
    if ch is not None:
        return [SK.line(view, ch[i], ch[i + 1]) for i in range(len(ch) - 1)]
    if kind == "Circle":
        return [view.makeCosmeticCircle(V(pts[0][0], pts[0][1], 0), _d(pts[0], pts[1]))]
    if kind == "Arc":
        c, r, a0, a1 = _arc_of(pts)
        return [view.makeCosmeticCircleArc(V(c[0], c[1], 0), r, a0, a1)]
    if kind == "Point":
        return [view.makeCosmeticVertex(V(pts[0][0], pts[0][1], 0))]
    return []


def add(view, kind, pts):
    pts = [tuple(float(c) for c in q[:2]) for q in pts]
    SK._record(view, kind, draw(view, kind, pts), pts)
    return len(view.SWSketchEntities) - 1


def remove(view, indices):
    for i in sorted(set(indices), reverse=True):
        SK.consume(view, i)


def replace(view, index, new):
    """Takes entity index out and adds the [(kind, points)] in its place (at the end)."""
    remove(view, [index])
    return [add(view, k, p) for k, p in new if p]


def views_with_sketch(page):
    return [v for v in D.views_of(page) if v.isDerivedFrom("TechDraw::DrawViewPart")
            and getattr(v, "SWSketchEntities", None)]


def to_sheet(view, g):
    x0, y0 = D.view_position(view)
    k = DV.view_scale(view)
    return x0 + g[0] * k, y0 + g[1] * k


def pick(page, p, kinds=None):
    """(view, entity index, point in view geometry) of the drawing sketch entity nearest sheet point p."""
    best = None
    for v in views_with_sketch(page):
        g = DV.to_geometry(v, p)
        tol = PICK_MM / max(DV.view_scale(v), 1e-9)
        for i, (kind, _tags, pts) in enumerate(SK.entities(v)):
            if kinds and kind not in kinds:
                continue
            ds = [prim_dist(g, pr) for pr in prims(kind, pts)]
            if kind == "Point" and pts:
                ds.append(_d(g, pts[0]))
            if ds and min(ds) <= tol and (best is None or min(ds) < best[0]):
                best = (min(ds), v, i, g)
    return best[1:] if best else (None, None, None)


def selected():
    """[(view, entity index)] of drawing sketch entities picked in the views (their cosmetic edges)."""
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        v = sel.Object
        if not v.isDerivedFrom("TechDraw::DrawViewPart") or not getattr(v, "SWSketchEntities", None):
            continue
        tags = []
        for sub in sel.SubElementNames:
            name = sub.split(".")[-1]
            try:
                ce = v.getCosmeticEdgeBySelection(name) if name.startswith("Edge") else \
                    v.getCosmeticVertexBySelection(name)
                tags.append(ce.Tag)
            except Exception as _fw_err:
                _fw_log("drawsketchedit.py:267", _fw_err)
        for i, (_k, t, _p) in enumerate(SK.entities(v)):
            if set(t) & set(tags) and (v, i) not in out:
                out.append((v, i))
    return out


def explode(view, index):
    ""

    kind, _t, pts = SK.entities(view)[index]
    if kind not in RING_KINDS:
        return [index]
    ring = list(pts) + [pts[0]]
    return replace(view, index, [("Line", [ring[i], ring[i + 1]]) for i in range(len(ring) - 1)])


# --------------------------------------------------------------------------- transforms
def _xf(pts, fn):
    return [fn(q) for q in pts]


def moved(pts, dx, dy):
    return _xf(pts, lambda q: (q[0] + dx, q[1] + dy))


def rotated(pts, c, deg):
    r = math.radians(deg)
    co, si = math.cos(r), math.sin(r)
    return _xf(pts, lambda q: (c[0] + (q[0] - c[0]) * co - (q[1] - c[1]) * si,
                               c[1] + (q[0] - c[0]) * si + (q[1] - c[1]) * co))


def scaled(pts, c, f):
    return _xf(pts, lambda q: (c[0] + (q[0] - c[0]) * f, c[1] + (q[1] - c[1]) * f))


def mirrored(kind, pts, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy or 1.0

    def m(q):
        t = ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L2
        fx, fy = a[0] + dx * t, a[1] + dy * t
        return 2 * fx - q[0], 2 * fy - q[1]
    out = _xf(pts, m)
    if kind == "Arc":          # a mirror turns the arc round: start and end swap to stay counterclockwise
        out = [out[0], out[2], out[1]]
    return out


# --------------------------------------------------------------------------- Trim
def _chain_hits(ch, others):
    """Global parameters u (segment index + t) where the chain meets the other primitives."""
    us = []
    for i in range(len(ch) - 1):
        for pr in others:
            us += [i + t for t in _line_hits(ch[i], ch[i + 1], pr)]
    return sorted(set(round(u, 9) for u in us))


def _chain_at(ch, u):
    i = min(int(u), len(ch) - 2)
    t = u - i
    a, b = ch[i], ch[i + 1]
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _sub_chain(ch, u0, u1):
    pts = [_chain_at(ch, u0)]
    pts += [ch[i] for i in range(int(math.floor(u0)) + 1, int(math.ceil(u1))) if u0 < i < u1]
    pts.append(_chain_at(ch, u1))
    return pts


def _click_u(ch, g):
    best = None
    for i in range(len(ch) - 1):
        d, t = _seg_dist(g, ch[i], ch[i + 1])
        if best is None or d < best[0]:
            best = (d, i + t)
    return best[1]


def _chain_kind(kind, pts):
    if len(pts) == 2:
        return "Centerline" if kind == "Centerline" else "Line"
    return "Polyline"


def others_of(view, index):
    out = []
    for j, (k, _t, p) in enumerate(SK.entities(view)):
        if j != index:
            out += prims(k, p)
    return out


def trim_pieces(kind, pts, g, others, keep=False):
    """What is left of an entity once the piece clicked at g (between its nearest crossings) is trimmed away
    (keep: only that piece is left). [] when the entity crosses nothing (Power trim deletes it)."""
    ch = chain(kind, pts)
    if ch is not None and kind not in RING_KINDS:
        cuts = [u for u in _chain_hits(ch, others) if EPS < u < len(ch) - 1 - EPS]
        if not cuts:
            return [] if not keep else [(kind, pts)]
        u = _click_u(ch, g)
        edges = [0.0] + cuts + [float(len(ch) - 1)]
        out = []
        for a, b in zip(edges, edges[1:]):
            inside = a - EPS <= u <= b + EPS
            if inside == keep and b - a > EPS:
                sub = _sub_chain(ch, a, b)
                out.append((_chain_kind(kind, sub), sub))
        return out
    if kind in ("Circle", "Arc"):
        if kind == "Circle":
            c, r = pts[0], _d(pts[0], pts[1])
            a0, span = 0.0, 360.0
        else:
            c, r, a0, a1 = _arc_of(pts)
            span = (a1 - a0) % 360.0 or 360.0
        rel = sorted(set(round((x - a0) % 360.0, 7) for pr in others for x in _circle_hits(c, r, pr)))
        rel = [x for x in rel if EPS < x < span - EPS] if kind == "Arc" else rel
        if kind == "Circle" and len(rel) < 2 or kind == "Arc" and not rel:
            return [] if not keep else [(kind, pts)]
        ac = (math.degrees(math.atan2(g[1] - c[1], g[0] - c[0])) - a0) % 360.0
        if kind == "Circle":
            edges = rel + [rel[0] + 360.0]
            if ac < rel[0]:
                ac += 360.0
        else:
            edges = [0.0] + rel + [span]

        def arc(x0, x1):
            s, e = math.radians(a0 + x0), math.radians(a0 + x1)
            return ("Arc", [c, (c[0] + r * math.cos(s), c[1] + r * math.sin(s)),
                            (c[0] + r * math.cos(e), c[1] + r * math.sin(e))])
        pieces = list(zip(edges, edges[1:]))
        hit = [n for n, (x0, x1) in enumerate(pieces) if x0 - EPS <= ac <= x1 + EPS]
        hit = hit[0] if hit else 0
        if keep:
            return [arc(*pieces[hit])]
        if kind == "Circle":
            x0, x1 = pieces[hit]
            return [arc(x1, x0 + 360.0)]
        return [arc(x0, x1) for n, (x0, x1) in enumerate(pieces) if n != hit and x1 - x0 > EPS]
    return [] if not keep else [(kind, pts)]


def trim(view, index, g, keep=False):
    """Trim Entities (Power trim / Trim to closest) on entity index at the click g: the new indices."""
    kind = SK.entities(view)[index][0]
    if kind in RING_KINDS:
        news = explode(view, index)
        ents = SK.entities(view)
        index = min(news, key=lambda j: min(prim_dist(g, pr) for pr in prims(ents[j][0], ents[j][2])))
    kind, _t, pts = SK.entities(view)[index]
    return replace(view, index, trim_pieces(kind, pts, g, others_of(view, index), keep))


def _line_ends(view, i):
    k, _t, p = SK.entities(view)[i]
    return (k, p) if k in ("Line", "Centerline") and len(p) == 2 else (None, None)


def _cross(a1, b1, a2, b2):
    r = (b1[0] - a1[0], b1[1] - a1[1])
    s = (b2[0] - a2[0], b2[1] - a2[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    t = ((a2[0] - a1[0]) * s[1] - (a2[1] - a1[1]) * s[0]) / den
    return a1[0] + r[0] * t, a1[1] + r[1] * t


def corner(view, i, gi, j, gj):
    """Trim: Corner: two lines run (extended or cut back) to where they meet, keeping the sides clicked."""
    ki, pi = _line_ends(view, i)
    kj, pj = _line_ends(view, j)
    if ki is None or kj is None:
        return False
    x = _cross(pi[0], pi[1], pj[0], pj[1])
    if x is None:
        return False

    def keep(p, g):
        # the end kept is the one on the clicked side of the corner
        far = p[0] if _d(p[0], x) > _d(p[1], x) else p[1]
        side = (g[0] - x[0]) * (far[0] - x[0]) + (g[1] - x[1]) * (far[1] - x[1])
        if side < 0:
            far = p[1] if far is p[0] else p[0]
        return [far, x]
    ni, nj = keep(pi, gi), keep(pj, gj)
    remove(view, [i, j])
    add(view, ki, ni)
    add(view, kj, nj)
    return True


def trim_between(view, index, g, bounds, inside=True):
    """Trim away inside / outside: the part of the clicked entity between (inside) or beyond (outside) the two
    bounding entities."""
    kind = SK.entities(view)[index][0]
    if kind in RING_KINDS:
        news = explode(view, index)
        ents = SK.entities(view)
        index = min(news, key=lambda j: min(prim_dist(g, pr) for pr in prims(ents[j][0], ents[j][2])))
    kind, _t, pts = SK.entities(view)[index]
    ch = chain(kind, pts)
    if ch is None or kind in RING_KINDS:
        return []
    ents = SK.entities(view)
    others = []
    for bv, bi in bounds:
        if bv is view and bi != index and bi < len(ents):
            others += prims(ents[bi][0], ents[bi][2])
    cuts = [u for u in _chain_hits(ch, others) if EPS < u < len(ch) - 1 - EPS]
    if len(cuts) < 2:
        return []
    lo, hi = cuts[0], cuts[-1]
    if inside:
        parts = [(0.0, lo), (hi, float(len(ch) - 1))]
    else:
        parts = [(lo, hi)]
    new = [(_chain_kind(kind, s), s) for s in (_sub_chain(ch, a, b) for a, b in parts if b - a > EPS)]
    return replace(view, index, new)


# --------------------------------------------------------------------------- Fillet / Chamfer
def lines_at_corner(view, g, tol):
    """The two straight entities whose ends meet nearest g: [(index, end at the corner 0/1)], exploding a
    rectangle or polygon first."""
    for _round in range(2):
        ends = []
        for i, (k, _t, p) in enumerate(SK.entities(view)):
            if k in ("Line", "Centerline") and len(p) == 2:
                for n in (0, 1):
                    ends.append((_d(g, p[n]), i, n, p[n]))
            elif k in RING_KINDS and _round == 0:
                if min(_d(g, q) for q in p) <= tol:
                    explode(view, i)
                    break
        else:
            ends.sort()
            if not ends or ends[0][0] > tol:
                return None
            c = ends[0][3]
            pair = [(i, n) for d, i, n, q in ends if _d(q, c) <= 1e-6 * max(1.0, abs(c[0]) + abs(c[1])) + 1e-6]
            seen, out = set(), []
            for i, n in pair:
                if i not in seen:
                    seen.add(i)
                    out.append((i, n))
            return out[:2] if len(out) >= 2 else None
    return None


def fillet(view, g, radius, tol, keep_corner=False, chamfer=None):
    """Sketch Fillet (radius) or Sketch Chamfer (chamfer = (d1, d2)) at the corner nearest g: the two lines are
    cut back and joined by an arc or a line. True when made."""
    hit = lines_at_corner(view, g, tol)
    if not hit:
        return False
    (i, ni), (j, nj) = hit
    ents = SK.entities(view)
    ki, pi = ents[i][0], ents[i][2]
    kj, pj = ents[j][0], ents[j][2]
    c = pi[ni]
    fi, fj = pi[1 - ni], pj[1 - nj]
    ui = ((fi[0] - c[0]) / (_d(c, fi) or 1), (fi[1] - c[1]) / (_d(c, fi) or 1))
    uj = ((fj[0] - c[0]) / (_d(c, fj) or 1), (fj[1] - c[1]) / (_d(c, fj) or 1))
    cosang = max(-1.0, min(1.0, ui[0] * uj[0] + ui[1] * uj[1]))
    ang = math.acos(cosang)
    if ang < 1e-6 or abs(ang - math.pi) < 1e-6:
        return False
    if chamfer is None:
        t = radius / math.tan(ang / 2.0)
        di = dj = t
    else:
        di, dj = chamfer
    if di >= _d(c, fi) or dj >= _d(c, fj):
        return False
    ti = (c[0] + ui[0] * di, c[1] + ui[1] * di)
    tj = (c[0] + uj[0] * dj, c[1] + uj[1] * dj)
    remove(view, [i, j])
    add(view, ki, [fi, ti])
    add(view, kj, [fj, tj])
    if chamfer is None:
        bis = (ui[0] + uj[0], ui[1] + uj[1])
        bl = math.hypot(*bis) or 1.0
        h = radius / math.sin(ang / 2.0)
        ctr = (c[0] + bis[0] / bl * h, c[1] + bis[1] / bl * h)
        # counterclockwise from one tangent point to the other the short way
        a_i = math.atan2(ti[1] - ctr[1], ti[0] - ctr[0])
        a_j = math.atan2(tj[1] - ctr[1], tj[0] - ctr[0])
        s, e = (ti, tj) if (a_j - a_i) % (2 * math.pi) < math.pi else (tj, ti)
        add(view, "Arc", [ctr, s, e])
    else:
        add(view, "Line", [ti, tj])
    if keep_corner:
        add(view, "Point", [c])
    return True


# --------------------------------------------------------------------------- Offset
def _offset_chain(ch, d, closed):
    """The chain moved d to its left (mitred corners)."""
    n = len(ch)
    segs = []
    for i in range(n - 1):
        a, b = ch[i], ch[i + 1]
        L = _d(a, b) or 1.0
        nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
        segs.append(((a[0] + nx * d, a[1] + ny * d), (b[0] + nx * d, b[1] + ny * d)))
    if not segs:
        return list(ch)
    out = []
    if closed:
        for i in range(len(segs)):
            p = _cross(segs[i - 1][0], segs[i - 1][1], segs[i][0], segs[i][1])
            out.append(p or segs[i][0])
        return out
    out.append(segs[0][0])
    for i in range(1, len(segs)):
        p = _cross(segs[i - 1][0], segs[i - 1][1], segs[i][0], segs[i][1])
        out.append(p or segs[i][0])
    out.append(segs[-1][1])
    return out


def _area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def offset_entity(kind, pts, d):
    """(kind, points) of the entity offset by d (positive: outward for closed shapes, left for open ones)."""
    if kind in RING_KINDS:
        sgn = -1.0 if _area(pts) > 0 else 1.0       # left of a counterclockwise ring is inside
        return "Polygon" if kind != "Rectangle" else "Rectangle", _offset_chain(list(pts) + [pts[0]], d * sgn, True)
    if kind in LINE_KINDS:
        return kind, _offset_chain(list(pts), d, False)
    if kind == "Spline":
        return "Polyline", _offset_chain(SK.spline_points(pts), d, False)
    if kind == "Circle":
        r = _d(pts[0], pts[1]) + d
        return (kind, [pts[0], (pts[0][0] + r, pts[0][1])]) if r > EPS else (None, None)
    if kind == "Arc":
        c, r, a0, a1 = _arc_of(pts)
        r2 = r + d
        if r2 <= EPS:
            return None, None
        return kind, [c, (c[0] + r2 * math.cos(math.radians(a0)), c[1] + r2 * math.sin(math.radians(a0))),
                      (c[0] + r2 * math.cos(math.radians(a1)), c[1] + r2 * math.sin(math.radians(a1)))]
    return None, None


# --------------------------------------------------------------------------- relations
def relations(view):
    ""


    ents = SK.entities(view)
    off = set(getattr(view, "SWSketchRelationsOff", []) or [])
    out = []

    def push(name, idx, key):
        if key not in off:
            out.append((name, idx, key))
    for i, (k, _t, p) in enumerate(ents):
        if k in ("Line", "Centerline") and len(p) == 2:
            if abs(p[0][1] - p[1][1]) < 1e-6:
                push("Horizontal", [i], "Horizontal|%s" % _ekey(ents[i]))
            elif abs(p[0][0] - p[1][0]) < 1e-6:
                push("Vertical", [i], "Vertical|%s" % _ekey(ents[i]))
    ends = []
    for i, (k, _t, p) in enumerate(ents):
        if k in LINE_KINDS and len(p) >= 2:
            ends += [(i, p[0]), (i, p[-1])]
        elif k == "Arc":
            ends += [(i, p[1]), (i, p[2])]
        elif k == "Point":
            ends.append((i, p[0]))
    for a in range(len(ends)):
        for b in range(a + 1, len(ends)):
            (i, p), (j, q) = ends[a], ends[b]
            if i != j and _d(p, q) < 1e-6:
                push("Coincident", [i, j], "Coincident|%.5g,%.5g|%s|%s" % (p[0], p[1], _ekey(ents[i]), _ekey(ents[j])))
    cs = [(i, p[0]) for i, (k, _t, p) in enumerate(ents) if k in ("Circle", "Arc")]
    for a in range(len(cs)):
        for b in range(a + 1, len(cs)):
            if _d(cs[a][1], cs[b][1]) < 1e-6:
                push("Concentric", [cs[a][0], cs[b][0]],
                     "Concentric|%s|%s" % (_ekey(ents[cs[a][0]]), _ekey(ents[cs[b][0]])))
    added = []
    for r in list(getattr(view, "SWSketchRelationsAdded", []) or []):
        name, keys = (r.split("#") + [""])[:2]
        idx = [n for n, e in enumerate(ents) if _ekey(e) in keys.split("~")]
        if len(idx) == len(keys.split("~")) and r not in off:
            added.append((name, idx, r))
    # a relation added with Add Relation that the geometry also shows (Horizontal on the line it made

    out = [o for o in out if not any(o[0] == a[0] and sorted(o[1]) == sorted(a[1]) for a in added)]
    return out + added


def _ekey(e):
    return ",".join(e[1])


def delete_relation(view, key):
    if "SWSketchRelationsOff" not in view.PropertiesList:
        view.addProperty("App::PropertyStringList", "SWSketchRelationsOff", "FreeCAD",
                         "drawing sketch relations deleted in Display/Delete Relations")
    twins = []
    if key in list(getattr(view, "SWSketchRelationsAdded", []) or []):
        # the same relation the geometry shows goes too, else it comes back in the list
        got = next((r for r in relations(view) if r[2] == key), None)
        if got is not None:
            view.SWSketchRelationsOff = list(view.SWSketchRelationsOff) + [key]
            twins = [r[2] for r in relations(view) if r[0] == got[0] and sorted(r[1]) == sorted(got[1]) and r[2] != key]
    view.SWSketchRelationsOff = list(view.SWSketchRelationsOff) + [k for k in [key] + twins if k not in view.SWSketchRelationsOff]
    if key in list(getattr(view, "SWSketchRelationsAdded", []) or []):
        view.SWSketchRelationsAdded = [r for r in view.SWSketchRelationsAdded if r != key]


ADD_RELATIONS = ("Horizontal", "Vertical", "Collinear", "Perpendicular", "Parallel", "Equal", "Coincident",
                 "Concentric", "Fix")


def fixed(view, i):
    """The entity carries a Fix relation (Move, Rotate and Scale leave it where it is)."""
    return any(name == "Fix" and i in idx for name, idx, _k in relations(view))


def possible_relations(view, idx):
    ents = SK.entities(view)
    ks = [ents[i][0] for i in idx]
    lines = all(k in ("Line", "Centerline") for k in ks)
    rounds = all(k in ("Circle", "Arc") for k in ks)
    out = []
    if lines and len(idx) >= 1:
        out += ["Horizontal", "Vertical"]
    if lines and len(idx) == 2:
        out += ["Collinear", "Perpendicular", "Parallel", "Equal"]
    if rounds and len(idx) == 2:
        out += ["Concentric", "Equal"]
    if len(idx) == 2:
        out.append("Coincident")
    if idx:
        out.append("Fix")
    return out


def add_relation(view, name, idx):
    """Add Relation: the geometry is made to satisfy the relation (the last entity picked moves), and the
    relation is listed in Display/Delete Relations."""
    ents = SK.entities(view)
    keys = [_ekey(ents[i]) for i in idx]
    new = {}
    if name in ("Horizontal", "Vertical"):
        for i in idx:
            k, _t, (a, b) = ents[i]
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            L = _d(a, b) / 2
            new[i] = (k, [(m[0] - L, m[1]), (m[0] + L, m[1])] if name == "Horizontal" else
                      [(m[0], m[1] - L), (m[0], m[1] + L)])
    elif name in ("Parallel", "Perpendicular", "Collinear", "Equal") and all(
            ents[i][0] in ("Line", "Centerline") for i in idx):
        (a, b), (c, d) = ents[idx[0]][2], ents[idx[1]][2]
        ang = math.atan2(b[1] - a[1], b[0] - a[0]) + (math.pi / 2 if name == "Perpendicular" else 0)
        m = ((c[0] + d[0]) / 2, (c[1] + d[1]) / 2)
        L = _d(c, d) / 2 if name != "Equal" else _d(a, b) / 2
        if name == "Equal":
            ang = math.atan2(d[1] - c[1], d[0] - c[0])
        if name == "Collinear":
            u = (math.cos(ang), math.sin(ang))
            t = (m[0] - a[0]) * u[0] + (m[1] - a[1]) * u[1]
            m = (a[0] + u[0] * t, a[1] + u[1] * t)
        if name in ("Parallel", "Collinear") and (math.cos(ang) * (d[0] - c[0]) + math.sin(ang) * (d[1] - c[1])) < 0:
            ang += math.pi
        u = (math.cos(ang) * L, math.sin(ang) * L)
        new[idx[1]] = (ents[idx[1]][0], [(m[0] - u[0], m[1] - u[1]), (m[0] + u[0], m[1] + u[1])])
    elif name == "Equal":
        p0, (k1, p1) = ents[idx[0]][2], (ents[idx[1]][0], ents[idx[1]][2])
        r = _d(p0[0], p0[1])
        if k1 == "Circle":
            new[idx[1]] = (k1, [p1[0], (p1[0][0] + r, p1[0][1])])
        else:
            c, _r, a0, a1 = _arc_of(p1)
            new[idx[1]] = (k1, [c, (c[0] + r * math.cos(math.radians(a0)), c[1] + r * math.sin(math.radians(a0))),
                                (c[0] + r * math.cos(math.radians(a1)), c[1] + r * math.sin(math.radians(a1)))])
    elif name == "Concentric":
        c0 = ents[idx[0]][2][0]
        k1, _t, p1 = ents[idx[1]]
        new[idx[1]] = (k1, moved(p1, c0[0] - p1[0][0], c0[1] - p1[0][1]))
    elif name == "Coincident":
        p0, p1 = ents[idx[0]][2], ents[idx[1]][2]
        best = min(((_d(a, b), n, a) for a in p0 for n, b in enumerate(p1)), key=lambda x: x[0])
        q = list(p1)
        q[best[1]] = best[2]
        new[idx[1]] = (ents[idx[1]][0], q)
    order = sorted(new, reverse=True)
    for i in order:
        SK.consume(view, i)
    for i in sorted(new):
        add(view, *new[i])
    ents = SK.entities(view)
    keys2 = [_ekey(e) for e in ents]
    # entities that were redrawn have new tags: the relation names the redrawn ones
    redrawn = dict(zip(sorted(new), [_ekey(e) for e in ents[len(ents) - len(new):]])) if new else {}
    final = [redrawn.get(i, keys[n]) for n, i in enumerate(idx)]
    final = [k for k in final if k in keys2]
    if "SWSketchRelationsAdded" not in view.PropertiesList:
        view.addProperty("App::PropertyStringList", "SWSketchRelationsAdded", "FreeCAD",
                         "drawing sketch relations added with Add Relation")
    view.SWSketchRelationsAdded = list(view.SWSketchRelationsAdded) + ["%s#%s" % (name, "~".join(final))]
    return True


# --------------------------------------------------------------------------- Quick Snaps
SNAPS = ["Point", "Center Point", "Midpoint", "Quadrant", "Intersection", "Nearest", "Tangent", "Perpendicular",
         "Parallel", "Horizontal/Vertical Lines", "Horizontal/Vertical to Points", "Length", "Grid", "Angle"]
SNAP_ON = {s: s not in ("Grid", "Length", "Angle") for s in SNAPS}
SNAP_MM = 2.0
ANGLE_STEP = 15.0
LENGTH_STEP = 1.0


def _sheet_prims(page):
    out = []
    for v in views_with_sketch(page):
        k = DV.view_scale(v)
        x0, y0 = D.view_position(v)
        for kind, _t, pts in SK.entities(v):
            for pr in prims(kind, pts):
                if pr[0] == "L":
                    out.append(("L", to_sheet(v, pr[1]), to_sheet(v, pr[2])))
                else:
                    out.append((pr[0], to_sheet(v, pr[1]), pr[2] * k) + tuple(pr[3:]))
    return out


def _sheet_snap_points(page):
    out = []
    for v in views_with_sketch(page):
        for kind, _t, pts in SK.entities(v):
            for pr in prims(kind, pts):
                if pr[0] == "L":
                    out += [("Point", to_sheet(v, pr[1])), ("Point", to_sheet(v, pr[2])),
                            ("Midpoint", to_sheet(v, ((pr[1][0] + pr[2][0]) / 2, (pr[1][1] + pr[2][1]) / 2)))]
                else:
                    c, r = pr[1], pr[2]
                    out.append(("Center Point", to_sheet(v, c)))
                    for q in range(4):
                        if pr[0] == "C" or _on_arc(90 * q, pr[3], pr[4]):
                            a = math.radians(90 * q)
                            out.append(("Quadrant", to_sheet(v, (c[0] + r * math.cos(a), c[1] + r * math.sin(a)))))
                    if pr[0] == "A":
                        for a in (pr[3], pr[4]):
                            out.append(("Point", to_sheet(v, (c[0] + r * math.cos(math.radians(a)),
                                                              c[1] + r * math.sin(math.radians(a))))))
            if kind == "Point" and pts:
                out.append(("Point", to_sheet(v, pts[0])))
        out += [("Intersection", to_sheet(v, q)) for q in intersections(v)]
    return out


def snap(page, p, last=None, on=None):
    """Quick Snaps: the sheet point p moves to the nearest sketch point of a snap type that is on (Point, Center
    Point, Midpoint, Quadrant, Intersection), else onto a line or circle (Nearest, Tangent, Perpendicular,
    Parallel from the last point), else Horizontal/Vertical from the last point or to sketch points, Length and
    Angle steps, Grid. Returns (point, snap name or None)."""
    on = SNAP_ON if on is None else on
    best = None
    spts = _sheet_snap_points(page)
    for kind, q in spts:
        if on.get(kind) and _d(p, q) <= SNAP_MM and (best is None or _d(p, q) < best[0]):
            best = (_d(p, q), q, kind)
    if best:
        return best[1], best[2]
    pr_s = _sheet_prims(page)
    if last is not None:
        for pr in pr_s:
            if pr[0] == "L" and on.get("Perpendicular"):
                a, b = pr[1], pr[2]
                d, t = _seg_dist(last, a, b)
                f = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                if 0 < t < 1 and _d(p, f) <= SNAP_MM and _d(last, f) > EPS:
                    return f, "Perpendicular"
            if pr[0] in ("C", "A") and on.get("Tangent"):
                c, r = pr[1], pr[2]
                dl = _d(last, c)
                if dl > r + EPS:
                    base = math.atan2(last[1] - c[1], last[0] - c[0])
                    off = math.acos(r / dl)
                    for s in (-1, 1):
                        a = base + s * off
                        q = (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
                        if _d(p, q) <= SNAP_MM:
                            return q, "Tangent"
    for pr in pr_s:
        if on.get("Nearest") and prim_dist(p, pr) <= SNAP_MM / 2:
            if pr[0] == "L":
                _d0, t = _seg_dist(p, pr[1], pr[2])
                return (pr[1][0] + (pr[2][0] - pr[1][0]) * t, pr[1][1] + (pr[2][1] - pr[1][1]) * t), "Nearest"
            c, r = pr[1], pr[2]
            a = math.atan2(p[1] - c[1], p[0] - c[0])
            return (c[0] + r * math.cos(a), c[1] + r * math.sin(a)), "Nearest"
    if last is not None:
        dx, dy = p[0] - last[0], p[1] - last[1]
        L = math.hypot(dx, dy)
        if on.get("Parallel") and L > EPS:
            for pr in pr_s:
                if pr[0] == "L":
                    u = (pr[2][0] - pr[1][0], pr[2][1] - pr[1][1])
                    ul = math.hypot(*u) or 1
                    u = (u[0] / ul, u[1] / ul)
                    t = dx * u[0] + dy * u[1]
                    q = (last[0] + u[0] * t, last[1] + u[1] * t)
                    if _d(p, q) <= SNAP_MM / 2 and abs(u[0]) > 1e-6 and abs(u[1]) > 1e-6:
                        return q, "Parallel"
        if on.get("Horizontal/Vertical Lines"):
            if abs(dy) <= SNAP_MM / 2:
                p = (p[0], last[1])
                return _len_step(p, last, on), "Horizontal"
            if abs(dx) <= SNAP_MM / 2:
                p = (last[0], p[1])
                return _len_step(p, last, on), "Vertical"
        if on.get("Angle") and L > EPS:
            a = round(math.degrees(math.atan2(dy, dx)) / ANGLE_STEP) * ANGLE_STEP
            q = (last[0] + L * math.cos(math.radians(a)), last[1] + L * math.sin(math.radians(a)))
            return _len_step(q, last, on), "Angle"
        if on.get("Length") and L > EPS:
            return _len_step(p, last, on), "Length"
    if on.get("Horizontal/Vertical to Points"):
        for _k, q in spts:
            if abs(p[0] - q[0]) <= SNAP_MM / 2:
                return (q[0], p[1]), "Vertical to point"
            if abs(p[1] - q[1]) <= SNAP_MM / 2:
                return (p[0], q[1]), "Horizontal to point"
    if on.get("Grid"):
        step = 10.0
        try:
            from . import drawdocprops as DP
            step = float(DP.prop(page.Document, "grid_major") or 10.0)
        except Exception as _fw_err:
            _fw_log("drawsketchedit.py:904", _fw_err)
        q = (round(p[0] / step) * step, round(p[1] / step) * step)
        if _d(p, q) <= SNAP_MM:
            return q, "Grid"
    return p, None


def _len_step(q, last, on):
    if not on.get("Length"):
        return q
    dx, dy = q[0] - last[0], q[1] - last[1]
    L = math.hypot(dx, dy)
    if L < EPS:
        return q
    n = max(1, round(L / LENGTH_STEP)) * LENGTH_STEP
    return last[0] + dx / L * n, last[1] + dy / L * n


def sketch_panel_open():
    ""
    p = getattr(SK, "CURRENT", None)
    if p is None or not Gui.Control.activeDialog():
        return None
    try:
        return p if p.form.isVisible() else None
    except RuntimeError:
        return None


def quick_snaps_menu(parent=None):
    """The Quick Snaps flyout: every snap type checkable."""
    m = QtWidgets.QMenu(parent or Gui.getMainWindow())
    m.setObjectName("SWQuickSnapsMenu")
    groups = (("Point Snaps", SNAPS[:9]), ("Line Snaps", SNAPS[9:12]), ("", SNAPS[12:]))
    for title, names in groups:
        if title:
            m.addSection(title)
        else:
            m.addSeparator()
        for n in names:
            a = m.addAction(n)
            a.setCheckable(True)
            a.setChecked(bool(SNAP_ON.get(n)))
            a.setObjectName("SWQuickSnap_" + n.replace(" ", "").replace("/", ""))
            a.toggled.connect(lambda on, n=n: SNAP_ON.__setitem__(n, bool(on)))
    return m


# --------------------------------------------------------------------------- PropertyManagers
class MidpointLinePanel(SK.LinePanel):
    TITLE = "Midpoint Line"
    KIND = "Line"
    CHAIN = False
    HINT = "Click the line's midpoint, then one end."

    def make(self, pts):
        m, b = pts[-2], pts[-1]
        a = (2 * m[0] - b[0], 2 * m[1] - b[1])
        SK.LinePanel.make(self, [a, b])


class _EditPanel(D._Panel):
    """A drawing sketch tool that works on the entities already sketched in a view."""
    HINT = "Click a sketch entity."

    def build(self):
        self.say(self.HINT)
        self.picked = []          # [(view, entity key)] (tags change when an entity is redrawn)
        self.parameters()
        for v, i in selected():
            self.add_pick(v, i)

    def parameters(self):
        pass

    def key(self, v, i):
        return v.Name, _ekey(SK.entities(v)[i])

    def index(self, v, key):
        for i, e in enumerate(SK.entities(v)):
            if _ekey(e) == key:
                return i
        return None

    def add_pick(self, v, i):
        k = self.key(v, i)
        if k not in self.picked:
            self.picked.append(k)
            if hasattr(self, "entity_list"):
                kind = SK.entities(v)[i][0]
                it = QtWidgets.QListWidgetItem("%s%d@%s" % (kind, i + 1, v.Label))
                self.entity_list.addItem(it)

    def picks(self):
        out = []
        for name, key in self.picked:
            v = self.doc.getObject(name)
            i = self.index(v, key) if v is not None else None
            if i is not None:
                out.append((v, i))
        return out

    def entity_box(self, title="Entities to Move"):
        box, lay = D._group(title, self.form)
        self.entity_list = QtWidgets.QListWidget(box)
        self.entity_list.setObjectName("SWSketchEditEntities")
        self.entity_list.setMaximumHeight(90)
        lay.addWidget(self.entity_list)
        self.lay.addWidget(box)
        return box, lay

    def tol(self, v):
        return PICK_MM / max(DV.view_scale(v), 1e-9)

    def done(self):
        self.doc.recompute()


class TrimPanel(_EditPanel):
    TITLE = "Trim"
    PIXMAP = "Sketcher_Trimming"
    HINT = "Click the piece of an entity to trim away."
    MODES = ("Power trim", "Corner", "Trim away inside", "Trim away outside", "Trim to closest")

    def parameters(self):
        box, lay = D._group("Options", self.form)
        self.modes = QtWidgets.QButtonGroup(box)
        for n, m in enumerate(self.MODES):
            b = QtWidgets.QRadioButton(m, box)
            b.setObjectName("SWTrim_" + m.replace(" ", ""))
            self.modes.addButton(b, n)
            lay.addWidget(b)
        self.modes.button(0).setChecked(True)
        self.keep = QtWidgets.QCheckBox("Keep trimmed entities as\nconstruction geometry", box)    # fits 300 px
        self.keep.setObjectName("SWTrimKeepConstruction")
        lay.addWidget(self.keep)
        self.lay.addWidget(box)
        self.modes.buttonClicked.connect(lambda *_: self.mode_changed())
        self.state = []

    def mode(self):
        return self.MODES[self.modes.checkedId()]

    def mode_changed(self):
        self.state = []
        self.say({"Corner": "Click the two entities to meet at a corner (on the sides to keep).",
                  "Trim away inside": "Click the two bounding entities, then the entities to trim.",
                  "Trim away outside": "Click the two bounding entities, then the entities to trim."}.get(
            self.mode(), self.HINT))

    def sheet_click(self, p):
        v, i, g = pick(self.page, p)
        if v is None:
            return True
        m = self.mode()
        if m == "Corner":
            self.state.append((v, i, g))
            if len(self.state) == 2:
                (v1, i1, g1), (v2, i2, g2) = self.state
                if v1 is v2:
                    corner(v1, i1, g1, i2, g2)
                self.state = []
                self.done()
            return True
        if m in ("Trim away inside", "Trim away outside"):
            if len(self.state) < 2:
                self.state.append((v, i))
                return True
            bounds = [(bv, bi) for bv, bi in self.state]
            keys = [(bv, _ekey(SK.entities(bv)[bi])) for bv, bi in bounds]
            self._construction(v, i, g)
            trim_between(v, i, g, bounds, inside=m == "Trim away inside")
            self.state = [(bv, self.index(bv, k)) for bv, k in keys if self.index(bv, k) is not None]
            self.done()
            return True
        self._construction(v, i, g)
        trim(v, i, g)
        self.done()
        return True

    def _construction(self, v, i, g):
        """Keep trimmed entities as construction geometry: the piece trimmed away stays as a centerline."""
        if not self.keep.isChecked():
            return
        kind, _t, pts = SK.entities(v)[i]
        if kind in RING_KINDS:
            return
        for k, p in trim_pieces(kind, pts, g, others_of(v, i), keep=True):
            if k in ("Line", "Centerline", "Polyline") and len(p) == 2:
                add(v, "Centerline", p)


class FilletPanel(_EditPanel):
    TITLE = "Sketch Fillet"
    PIXMAP = "Sketcher_CreateFillet"
    HINT = "Click the corner (where two sketch lines meet) to fillet."
    CHAMFER = False

    def parameters(self):
        box, lay = D._group("Fillet Parameters" if not self.CHAMFER else "Chamfer Parameters", self.form)
        if not self.CHAMFER:
            self.radius = QtWidgets.QDoubleSpinBox(box)
            self.radius.setObjectName("SWSketchFilletRadius")
            self.radius.setRange(0.01, 10000)
            self.radius.setSuffix("mm")
            self.radius.setValue(10.0)
            lay.addWidget(self.radius)
            self.keep = QtWidgets.QCheckBox("Keep constrained corners", box)
            self.keep.setObjectName("SWSketchFilletKeepCorners")
            self.keep.setChecked(True)
            lay.addWidget(self.keep)
            self.dim = QtWidgets.QCheckBox("Dimension each fillet", box)
            self.dim.setObjectName("SWSketchFilletDimension")
            lay.addWidget(self.dim)
        else:
            self.kind = QtWidgets.QButtonGroup(box)
            for n, t in enumerate(("Angle-distance", "Distance-distance")):
                b = QtWidgets.QRadioButton(t, box)
                b.setObjectName("SWSketchChamfer_" + t.replace("-", ""))
                self.kind.addButton(b, n)
                lay.addWidget(b)
            self.kind.button(1).setChecked(True)
            self.equal = QtWidgets.QCheckBox("Equal distance", box)
            self.equal.setObjectName("SWSketchChamferEqual")
            self.equal.setChecked(True)
            lay.addWidget(self.equal)
            self.d1 = QtWidgets.QDoubleSpinBox(box)
            self.d1.setObjectName("SWSketchChamferD1")
            self.d2 = QtWidgets.QDoubleSpinBox(box)
            self.d2.setObjectName("SWSketchChamferD2")
            for w in (self.d1, self.d2):
                w.setRange(0.01, 10000)
                w.setSuffix("mm")
                w.setValue(10.0)
                lay.addWidget(w)
            self.angle = QtWidgets.QDoubleSpinBox(box)
            self.angle.setObjectName("SWSketchChamferAngle")
            self.angle.setRange(1, 89)
            self.angle.setSuffix("°")
            self.angle.setValue(45)
            lay.addWidget(self.angle)

            def sync(*_):
                aa = self.kind.checkedId() == 0
                self.angle.setEnabled(aa)
                self.equal.setEnabled(not aa)
                self.d2.setEnabled(not aa and not self.equal.isChecked())
            self.kind.buttonClicked.connect(sync)
            self.equal.toggled.connect(sync)
            sync()
        self.lay.addWidget(box)

    def sheet_click(self, p):
        v = DV.focus_view(self.page, p, margin=0.0)
        if v is None or not getattr(v, "SWSketchEntities", None):
            near = [w for w in views_with_sketch(self.page) if lines_or_rings(w)]
            v = near[0] if near else None
        if v is None:
            return True
        g = DV.to_geometry(v, p)
        if self.CHAMFER:
            d1 = self.d1.value()
            if self.kind.checkedId() == 0:
                d2 = d1 * math.tan(math.radians(self.angle.value()))
            else:
                d2 = d1 if self.equal.isChecked() else self.d2.value()
            ok = fillet(v, g, 0, self.tol(v) * 2, chamfer=(d1, d2))
        else:
            ok = fillet(v, g, self.radius.value(), self.tol(v) * 2, keep_corner=self.keep.isChecked())
            if ok and self.dim.isChecked():
                self.dimension(v)
        if not ok:
            self.say("No corner of two sketch lines there (or the %s is too big)."
                     % ("chamfer" if self.CHAMFER else "radius"))
        else:
            self.say(self.HINT)
        self.done()
        return True

    def dimension(self, v):
        """Dimension each fillet: a radius dimension on the new arc."""
        try:
            self.doc.recompute()
            arc_tag = [e for e in SK.entities(v) if e[0] == "Arc"][-1][1][0]
            n = len(v.getVisibleEdges())
            for idx in range(n + 64):
                try:
                    if v.getCosmeticEdgeBySelection("Edge%d" % idx).Tag == arc_tag:
                        dim = self.doc.addObject("TechDraw::DrawViewDimension", "Dimension")
                        dim.Type = "Radius"
                        dim.References2D = [(v, "Edge%d" % idx)]
                        self.page.addView(dim)
                        break
                except Exception:
                    continue
        except Exception as e:
            App.Console.PrintWarning("FreeCAD: Dimension each fillet: %s\n" % e)


def lines_or_rings(v):
    return any(k in ("Line", "Centerline") + RING_KINDS for k, _t, _p in SK.entities(v))


class ChamferPanel(FilletPanel):
    TITLE = "Sketch Chamfer"
    PIXMAP = "Sketcher_CreateChamfer"
    HINT = "Click the corner (where two sketch lines meet) to chamfer."
    CHAMFER = True


class OffsetPanel(_EditPanel):
    TITLE = "Offset Entities"
    PIXMAP = "Sketcher_Offset"
    HINT = "Click the sketch entities to offset; OK makes them."

    def parameters(self):
        self.entity_box("Entities to Offset")
        box, lay = D._group("Parameters", self.form)
        self.dist = QtWidgets.QDoubleSpinBox(box)
        self.dist.setObjectName("SWOffsetDistance")
        self.dist.setRange(0.0, 10000)
        self.dist.setSuffix("mm")
        self.dist.setValue(10.0)
        lay.addWidget(self.dist)
        self.checks = {}
        for name in ("Add dimensions", "Reverse", "Select chain", "Bi-directional", "Cap ends"):
            c = QtWidgets.QCheckBox(name, box)
            c.setObjectName("SWOffset_" + name.replace(" ", "").replace("-", ""))
            lay.addWidget(c)
            self.checks[name] = c
        self.checks["Select chain"].setChecked(True)
        self.caps = QtWidgets.QButtonGroup(box)
        crow = QtWidgets.QHBoxLayout()
        for n, t in enumerate(("Arcs", "Lines")):
            b = QtWidgets.QRadioButton(t, box)
            b.setObjectName("SWOffsetCap" + t)
            self.caps.addButton(b, n)
            crow.addWidget(b)
        self.caps.button(0).setChecked(True)
        lay.addLayout(crow)
        lay.addWidget(QtWidgets.QLabel("Construction geometry:", box))
        self.base_cons = QtWidgets.QCheckBox("Base geometry", box)
        self.base_cons.setObjectName("SWOffsetBaseConstruction")
        self.off_cons = QtWidgets.QCheckBox("Offset geometry", box)
        self.off_cons.setObjectName("SWOffsetOffsetConstruction")
        lay.addWidget(self.base_cons)
        lay.addWidget(self.off_cons)
        self.lay.addWidget(box)

        def sync(*_):
            bi = self.checks["Bi-directional"].isChecked()
            self.checks["Cap ends"].setEnabled(bi)
            for b in self.caps.buttons():
                b.setEnabled(bi and self.checks["Cap ends"].isChecked())
        self.checks["Bi-directional"].toggled.connect(sync)
        self.checks["Cap ends"].toggled.connect(sync)
        sync()

    def sheet_click(self, p):
        v, i, _g = pick(self.page, p)
        if v is not None:
            self.add_pick(v, i)
        return True

    def finish(self):
        d = self.dist.value() * (-1 if self.checks["Reverse"].isChecked() else 1)
        bi = self.checks["Bi-directional"].isChecked()
        for v, i in sorted(self.picks(), key=lambda x: -x[1]):
            kind, _t, pts = SK.entities(v)[i]
            made = []
            for s in ((d, -d) if bi else (d,)):
                k2, p2 = offset_entity(kind, pts, s)
                if k2:
                    if self.off_cons.isChecked() and k2 in ("Line", "Polyline") and len(p2) == 2:
                        k2 = "Centerline"
                    add(v, k2, p2)
                    made.append((k2, p2))
            if bi and self.checks["Cap ends"].isChecked() and len(made) == 2 and kind in LINE_KINDS:
                (_k, a), (_k2, b) = made
                for e1, e2, mid in ((a[0], b[0], pts[0]), (a[-1], b[-1], pts[-1])):
                    if self.caps.checkedId() == 1:
                        add(v, "Line", [e1, e2])
                    else:
                        s, e = (e1, e2) if (math.atan2(e2[1] - mid[1], e2[0] - mid[0]) -
                                            math.atan2(e1[1] - mid[1], e1[0] - mid[0])) % (2 * math.pi) < math.pi \
                            else (e2, e1)
                        add(v, "Arc", [mid, s, e])
            if self.base_cons.isChecked() and kind in ("Line",):
                replace(v, self.index(v, _ekey(SK.entities(v)[i])) or i, [("Centerline", pts)])
        self.done()


class MirrorPanel(_EditPanel):
    TITLE = "Mirror"
    PIXMAP = "Sketcher_Symmetry"
    HINT = "Click the entities to mirror, then click in Mirror about and click the line to mirror about."

    def parameters(self):
        self.entity_box("Entities to mirror")
        box, lay = D._group("Mirror about", self.form)
        self.about = QtWidgets.QListWidget(box)
        self.about.setObjectName("SWMirrorAbout")
        self.about.setMaximumHeight(40)
        lay.addWidget(self.about)
        self.copy = QtWidgets.QCheckBox("Copy", box)
        self.copy.setObjectName("SWMirrorCopy")
        self.copy.setChecked(True)
        lay.addWidget(self.copy)
        self.lay.addWidget(box)
        self.axis = None
        self.about_active = False
        self.about.itemSelectionChanged.connect(lambda: None)
        self.about.installEventFilter(_FocusWatch(self.about, lambda: setattr(self, "about_active", True)))
        self.entity_list.installEventFilter(_FocusWatch(self.entity_list, lambda: setattr(self, "about_active", False)))

    def sheet_click(self, p):
        v, i, _g = pick(self.page, p)
        if v is None:
            return True
        kind = SK.entities(v)[i][0]
        if kind in ("Line", "Centerline") and (self.about_active or (kind == "Centerline" and self.picked
                                                                     and self.axis is None)):
            self.axis = self.key(v, i)
            self.about.clear()
            self.about.addItem("%s%d@%s" % (kind, i + 1, v.Label))
            self.about_active = False
            return True
        self.add_pick(v, i)
        return True

    def finish(self):
        if self.axis is None:
            return
        av = self.doc.getObject(self.axis[0])
        ai = self.index(av, self.axis[1])
        if ai is None:
            return
        a, b = SK.entities(av)[ai][2]
        picks = [(v, i) for v, i in self.picks() if v is av]
        news = []
        for v, i in picks:
            kind, _t, pts = SK.entities(v)[i]
            news.append((kind, mirrored(kind, pts, a, b)))
        if not self.copy.isChecked():
            remove(av, [i for _v, i in picks])
        for k, p in news:
            add(av, k, p)
        if self.copy.isChecked() and news:
            if "SWSketchRelationsAdded" not in av.PropertiesList:
                av.addProperty("App::PropertyStringList", "SWSketchRelationsAdded", "FreeCAD", "")
        self.done()


class _FocusWatch(QtCore.QObject):
    def __init__(self, w, fn):
        super().__init__(w)
        self.fn = fn

    def eventFilter(self, obj, ev):
        if not isinstance(ev, QtCore.QEvent):
            return False          # a stale PySide wrapper can arrive here
        if ev.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            self.fn()
        return False


class PatternPanel(_EditPanel):
    TITLE = "Linear Pattern"
    PIXMAP = "Sketcher_RectangularArray"
    HINT = "Click the entities to pattern; OK makes the copies."
    CIRCULAR = False

    def parameters(self):
        self.spins = {}
        if not self.CIRCULAR:
            for n, (title, ang) in enumerate((("Direction 1", 0.0), ("Direction 2", 90.0))):
                box, lay = D._group(title, self.form)
                g = QtWidgets.QFormLayout()
                for key, label, lo, hi, val, suf in (("spacing", "Spacing", 0.0, 1e5, 20.0, "mm"),
                                                      ("count", "Number of instances", 1, 1000, 2 if n == 0 else 1, ""),
                                                      ("angle", "Angle", -360, 360, ang, "°")):
                    w = QtWidgets.QDoubleSpinBox(box) if key != "count" else QtWidgets.QSpinBox(box)
                    w.setObjectName("SWPattern%d_%s" % (n + 1, key))
                    w.setRange(lo, hi)
                    w.setValue(val)
                    if suf:
                        w.setSuffix(suf)
                    g.addRow(label + ":", w)
                    self.spins[(n, key)] = w
                rev = QtWidgets.QCheckBox("Reverse direction", box)
                rev.setObjectName("SWPattern%d_reverse" % (n + 1))
                self.spins[(n, "reverse")] = rev
                g.addRow(rev)
                lay.addLayout(g)
                self.lay.addWidget(box)
        else:
            box, lay = D._group("Parameters", self.form)
            g = QtWidgets.QFormLayout()
            self.centre_label = QtWidgets.QLabel("Click the pattern centre (else the view's origin).", box)
            self.centre_label.setObjectName("SWCircPatternCentreLabel")
            self.centre_label.setWordWrap(True)          # one line made the pane 344 px wide
            g.addRow(self.centre_label)
            for key, label, lo, hi, val, suf in (("count", "Number of instances", 2, 1000, 4, ""),
                                                  ("total", "Total angle", -360, 360, 360.0, "°")):
                w = QtWidgets.QDoubleSpinBox(box) if key != "count" else QtWidgets.QSpinBox(box)
                w.setObjectName("SWCircPattern_%s" % key)
                w.setRange(lo, hi)
                w.setValue(val)
                if suf:
                    w.setSuffix(suf)
                g.addRow(label + ":", w)
                self.spins[key] = w
            eq = QtWidgets.QCheckBox("Equal spacing", box)
            eq.setObjectName("SWCircPattern_equal")
            eq.setChecked(True)
            self.spins["equal"] = eq
            g.addRow(eq)
            lay.addLayout(g)
            self.lay.addWidget(box)
            self.centre = None
        self.entity_box("Entities to Pattern")

    def sheet_click(self, p):
        v, i, _g = pick(self.page, p)
        if v is not None:
            self.add_pick(v, i)
        elif self.CIRCULAR:
            self.centre = p
            self.centre_label.setText("Centre: %.2f, %.2f" % p)
        return True

    def finish(self):
        picks = self.picks()
        news = []
        for v, i in picks:
            kind, _t, pts = SK.entities(v)[i]
            k = DV.view_scale(v)
            if not self.CIRCULAR:
                for a in range(self.spins[(0, "count")].value()):
                    for b in range(self.spins[(1, "count")].value()):
                        if a == 0 and b == 0:
                            continue
                        dx = dy = 0.0
                        for n, m in ((0, a), (1, b)):
                            ang = math.radians(self.spins[(n, "angle")].value() +
                                               (180 if self.spins[(n, "reverse")].isChecked() else 0))
                            s = self.spins[(n, "spacing")].value() / k * m
                            dx += s * math.cos(ang)
                            dy += s * math.sin(ang)
                        news.append((v, kind, moved(pts, dx, dy)))
            else:
                c = DV.to_geometry(v, self.centre) if self.centre else (0.0, 0.0)
                n = self.spins["count"].value()
                total = self.spins["total"].value()
                step = total / (n if abs(abs(total) - 360) < 1e-6 else max(1, n - 1))
                for m in range(1, n):
                    news.append((v, kind, rotated(pts, c, step * m)))
        for v, kind, pts in news:
            add(v, kind, pts)
        self.done()


class CircularPatternPanel(PatternPanel):
    TITLE = "Circular Pattern"
    PIXMAP = "Sketcher_RectangularArray"
    CIRCULAR = True


class MovePanel(_EditPanel):
    """Move / Copy / Rotate / Scale Entities."""
    TITLE = "Move"
    PIXMAP = "Sketcher_Move"
    MODE = "Move"
    HINT = "Click the entities, then set the move (or click the start and end point with From/To)."

    def parameters(self):
        self.entity_box("Entities to %s" % self.MODE)
        if self.MODE in ("Move", "Copy"):
            self.keep_rel = QtWidgets.QCheckBox("Keep relations", self.form)
            self.keep_rel.setObjectName("SWMoveKeepRelations")
            self.lay.addWidget(self.keep_rel)
        box, lay = D._group("Parameters", self.form)
        g = QtWidgets.QFormLayout()
        self.base = None
        self.base2 = None
        if self.MODE in ("Move", "Copy"):
            self.fromto = QtWidgets.QRadioButton("From/To", box)
            self.fromto.setObjectName("SWMoveFromTo")
            self.xy = QtWidgets.QRadioButton("X/Y", box)
            self.xy.setObjectName("SWMoveXY")
            self.xy.setChecked(True)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.fromto)
            row.addWidget(self.xy)
            g.addRow(row)
            self.dx = QtWidgets.QDoubleSpinBox(box)
            self.dx.setObjectName("SWMoveDX")
            self.dy = QtWidgets.QDoubleSpinBox(box)
            self.dy.setObjectName("SWMoveDY")
            for w in (self.dx, self.dy):
                w.setRange(-1e5, 1e5)
                w.setSuffix("mm")
                w.setMinimumWidth(80)       # the range's widest text made the pane 313 px wide
            g.addRow("ΔX:", self.dx)
            g.addRow("ΔY:", self.dy)
            self.repeat = QtWidgets.QPushButton("Repeat", box)
            self.repeat.setObjectName("SWMoveRepeat")
            self.repeat.clicked.connect(self.do_repeat)
            g.addRow(self.repeat)
            if self.MODE == "Copy":
                self.copies = QtWidgets.QSpinBox(box)
                self.copies.setObjectName("SWCopyNumber")
                self.copies.setRange(1, 1000)
                self.copies.setValue(1)
                g.addRow("Number of copies:", self.copies)
        else:
            self.base_label = QtWidgets.QLabel("Click the %s point." % ("center of rotation" if self.MODE == "Rotate"
                                                                         else "base"), box)
            self.base_label.setObjectName("SWMoveBaseLabel")
            g.addRow(self.base_label)
            if self.MODE == "Rotate":
                self.angle = QtWidgets.QDoubleSpinBox(box)
                self.angle.setObjectName("SWRotateAngle")
                self.angle.setRange(-360, 360)
                self.angle.setSuffix("°")
                self.angle.setValue(90)
                g.addRow("Angle:", self.angle)
            else:
                self.factor = QtWidgets.QDoubleSpinBox(box)
                self.factor.setObjectName("SWScaleFactor")
                self.factor.setRange(0.001, 1000)
                self.factor.setDecimals(3)
                self.factor.setValue(2)
                g.addRow("Scale factor:", self.factor)
                self.copy = QtWidgets.QCheckBox("Copy", box)
                self.copy.setObjectName("SWScaleCopy")
                g.addRow(self.copy)
                self.copies = QtWidgets.QSpinBox(box)
                self.copies.setObjectName("SWScaleCopies")
                self.copies.setRange(1, 1000)
                g.addRow("Number of copies:", self.copies)
        lay.addLayout(g)
        self.lay.addWidget(box)

    def sheet_click(self, p):
        v, i, _g = pick(self.page, p)
        if self.MODE in ("Move", "Copy"):
            if self.fromto.isChecked() and self.picked and (self.base is not None or v is None
                                                            or self.key(v, i) in self.picked):
                if self.base is None:
                    self.base = p
                    self.say("Click where the start point goes.")
                    return True
                self.dx.setValue(p[0] - self.base[0])
                self.dy.setValue(p[1] - self.base[1])
                self.base = None
                self.apply()
                self.say(self.HINT)
            elif v is not None:
                self.add_pick(v, i)
            return True
        if v is not None and self.base is None and self.key(v, i) not in self.picked:
            self.add_pick(v, i)
            return True
        self.base = p
        self.base_label.setText("Base: %.2f, %.2f" % p)
        return True

    def do_repeat(self):
        self.apply()

    def apply(self):
        picks = self.picks()
        if not picks:
            return
        n = self.copies.value() if self.MODE == "Copy" else 1
        jobs = []
        for v, i in picks:
            if self.MODE == "Move" and fixed(v, i):
                continue
            kind, _t, pts = SK.entities(v)[i]
            k = DV.view_scale(v)
            dx, dy = self.dx.value() / k, self.dy.value() / k
            if self.MODE == "Copy":
                for m in range(1, n + 1):
                    add(v, kind, moved(pts, dx * m, dy * m))
                continue
            touching = self._touching(v, i) if self.keep_rel.isChecked() else []
            jobs.append((v, _ekey(SK.entities(v)[i]), kind, moved(pts, dx, dy), touching, dx, dy))
        if self.MODE == "Move":
            picked = []
            for v, key, kind, pts, touching, dx, dy in jobs:
                i = self.index(v, key)
                if i is None:
                    continue
                SK.consume(v, i)
                # Keep relations: the ends of other entities coincident with the moved ends follow
                for tkey, n_end in touching:
                    j = self.index(v, tkey)
                    if j is None:
                        continue
                    k2, _t2, p2 = SK.entities(v)[j]
                    p2 = list(p2)
                    p2[n_end] = (p2[n_end][0] + dx, p2[n_end][1] + dy)
                    SK.consume(v, j)
                    add(v, k2, p2)
                ni = add(v, kind, pts)
                picked.append((v.Name, _ekey(SK.entities(v)[ni])))
            self.picked = picked
        self.done()

    def _touching(self, v, i):
        rels = relations(v)
        ents = SK.entities(v)
        pts = ents[i][2]
        out = []
        for name, idx, _key in rels:
            if name == "Coincident" and i in idx:
                j = idx[0] if idx[1] == i else idx[1]
                if any(self.key(v, j) == pk for pk in self.picked):
                    continue
                pj = ents[j][2]
                for n, q in enumerate(pj):
                    if any(_d(q, r) < 1e-6 for r in pts):
                        out.append((_ekey(ents[j]), n))
        return out

    def finish(self):
        picks = self.picks()
        if self.MODE in ("Move", "Copy"):
            if self.xy.isChecked() and (self.dx.value() or self.dy.value()):
                self.apply()
            return
        if not picks or self.base is None:
            return
        for v, i in sorted(picks, key=lambda x: -x[1]):
            if fixed(v, i) and not (self.MODE == "Scale" and self.copy.isChecked()):
                continue
            kind, _t, pts = SK.entities(v)[i]
            c = DV.to_geometry(v, self.base)
            if self.MODE == "Rotate":
                SK.consume(v, i)
                add(v, kind, rotated(pts, c, self.angle.value()))
            else:
                f = self.factor.value()
                if self.copy.isChecked():
                    for m in range(1, self.copies.value() + 1):
                        add(v, kind, scaled(pts, c, f ** m))
                else:
                    SK.consume(v, i)
                    add(v, kind, scaled(pts, c, f))
        self.done()


class CopyPanel(MovePanel):
    TITLE = "Copy"
    MODE = "Copy"


class RotatePanel(MovePanel):
    TITLE = "Rotate"
    MODE = "Rotate"
    PIXMAP = "Draft_Rotate"
    HINT = "Click the entities, then the center of rotation; set the angle and OK."


class ScalePanel(MovePanel):
    TITLE = "Scale"
    MODE = "Scale"
    PIXMAP = "Draft_Scale"
    HINT = "Click the entities, then the base point; set the scale factor and OK."


class RelationsPanel(_EditPanel):
    TITLE = "Display/Delete Relations"
    PIXMAP = "Constraint_PointOnPoint"
    HINT = "The sketch's relations: pick one to see its entities; Delete removes it."

    def parameters(self):
        box, lay = D._group("Relations", self.form)
        self.filter = QtWidgets.QComboBox(box)
        self.filter.setObjectName("SWRelationsFilter")
        self.filter.addItems(["All in this sketch", "Dangling", "Over Defined/Not Solved", "External",
                              "Defined In Context", "Locked", "Broken", "Selected Entities"])
        lay.addWidget(self.filter)
        self.list = QtWidgets.QListWidget(box)
        self.list.setObjectName("SWRelationsList")
        lay.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        self.delete = QtWidgets.QPushButton("Delete", box)
        self.delete.setObjectName("SWRelationsDelete")
        self.delete_all = QtWidgets.QPushButton("Delete All", box)
        self.delete_all.setObjectName("SWRelationsDeleteAll")
        row.addWidget(self.delete)
        row.addWidget(self.delete_all)
        lay.addLayout(row)

        self.lay.addWidget(box)
        box, lay = D._group("Entities", self.form)
        self.ents = QtWidgets.QListWidget(box)
        self.ents.setObjectName("SWRelationsEntities")
        self.ents.setMaximumHeight(80)
        lay.addWidget(self.ents)
        self.lay.addWidget(box)
        self.filter.currentIndexChanged.connect(self.fill)
        self.list.currentRowChanged.connect(self.show_entities)
        self.delete.clicked.connect(self.delete_current)
        self.delete_all.clicked.connect(self.delete_every)
        self.rows = []
        self.sel_view = None
        self.fill()

    def fill(self, *_):
        self.list.clear()
        self.rows = []
        f = self.filter.currentText()
        picked = self.picks() if f == "Selected Entities" else None
        for v in views_with_sketch(self.page):
            for name, idx, key in relations(v):
                if f not in ("All in this sketch", "Selected Entities"):
                    continue
                if picked is not None and not any(pv is v and pi in idx for pv, pi in picked):
                    continue
                self.rows.append((v, name, idx, key))
                self.list.addItem("%s%d" % (name, len(self.rows)))

    def sheet_click(self, p):
        v, i, _g = pick(self.page, p)
        if v is not None:
            self.add_pick(v, i)
            if self.filter.currentText() != "Selected Entities":
                self.filter.setCurrentText("Selected Entities")
            else:
                self.fill()
        return True

    def show_entities(self, row):
        self.ents.clear()
        if 0 <= row < len(self.rows):
            v, _n, idx, _k = self.rows[row]
            ents = SK.entities(v)
            for i in idx:
                self.ents.addItem("%s%d" % (ents[i][0], i + 1))

    def delete_current(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.rows):
            v, _n, _i, key = self.rows[row]
            delete_relation(v, key)
            self.fill()

    def delete_every(self):
        for v, _n, _i, key in list(self.rows):
            delete_relation(v, key)
        self.fill()


class AddRelationPanel(_EditPanel):
    TITLE = "Add Relations"
    PIXMAP = "Constraint_PointOnPoint"
    HINT = "Click the sketch entities, then a relation."

    def parameters(self):
        self.entity_box("Selected Entities")
        box, lay = D._group("Add Relations", self.form)
        self.buttons = {}
        for name in ADD_RELATIONS:
            b = QtWidgets.QPushButton(name, box)
            b.setObjectName("SWAddRelation_" + name)
            b.clicked.connect(lambda *_a, n=name: self.relate(n))
            lay.addWidget(b)
            self.buttons[name] = b
        self.lay.addWidget(box)
        self.sync()

    def add_pick(self, v, i):
        super().add_pick(v, i)
        self.sync()

    def sync(self):
        picks = self.picks() if hasattr(self, "picked") else []
        views = {v.Name for v, _i in picks}
        ok = possible_relations(picks[0][0], [i for _v, i in picks]) if picks and len(views) == 1 else []
        for n, b in getattr(self, "buttons", {}).items():
            b.setEnabled(n in ok)

    def sheet_click(self, p):
        v, i, _g = pick(self.page, p)
        if v is not None:
            self.add_pick(v, i)
        return True

    def relate(self, name):
        picks = self.picks()
        if not picks:
            return
        v = picks[0][0]
        add_relation(v, name, [i for _v, i in picks])
        self.picked = []
        self.entity_list.clear()
        self.sync()
        self.done()


# --------------------------------------------------------------------------- Convert Entities
def picked_model_edges():
    """(view, [edge index]) of model edges (not drawing sketch ones) picked in one view, else (None, [])."""
    for sel in Gui.Selection.getSelectionEx("", 0):
        v = sel.Object
        if not v.isDerivedFrom("TechDraw::DrawViewPart"):
            continue
        idx = []
        for sub in sel.SubElementNames:
            name = sub.split(".")[-1]
            if not name.startswith("Edge"):
                continue
            try:
                v.getCosmeticEdgeBySelection(name)
                continue          # a sketch line or other cosmetic edge
            except Exception as _fw_err:
                _fw_log("drawsketchedit.py:1824", _fw_err)
            try:
                idx.append(int(name[4:]))
            except ValueError as _fw_err:
                _fw_log("drawsketchedit.py:1828", _fw_err)
        if idx:
            return v, idx
    return None, []


def convert(view, indices):
    """Convert Entities: the picked model edges become drawing sketch entities on top of them."""
    made = 0
    for n in indices:
        try:
            e = view.getEdgeByIndex(n)
        except Exception:
            continue
        cname = type(e.Curve).__name__
        vs = [(x.Point.x, x.Point.y) for x in e.Vertexes]
        if cname in ("Line", "LineSegment") and len(vs) >= 2:
            add(view, "Line", [vs[0], vs[-1]])
        elif cname == "Circle" and (len(vs) < 2 or _d(vs[0], vs[-1]) < 1e-7):
            c = e.Curve.Center
            add(view, "Circle", [(c.x, c.y), (c.x + e.Curve.Radius, c.y)])
        elif cname == "Circle":
            c = e.Curve.Center
            m = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
            s, t = vs[0], vs[-1]
            # counterclockwise through the middle point
            a_s = math.atan2(s[1] - c.y, s[0] - c.x)
            a_t = math.atan2(t[1] - c.y, t[0] - c.x)
            a_m = math.atan2(m.y - c.y, m.x - c.x)
            if (a_m - a_s) % (2 * math.pi) > (a_t - a_s) % (2 * math.pi):
                s, t = t, s
            add(view, "Arc", [(c.x, c.y), s, t])
        else:
            pts = [(q.x, q.y) for q in e.discretize(24)]
            add(view, "Polyline", pts)
        made += 1
    return made


# --------------------------------------------------------------------------- commands
COMMANDS = {
    "FreeWorks_DrawSketchMidpointLine": ("Midpoint Line", "Sketcher_CreateLine",
                                         "Sketches a line from its midpoint."),
    "FreeWorks_DrawSketchFillet": ("Sketch Fillet", "Sketcher_CreateFillet",
                                   "Rounds the corner where two sketch lines meet."),
    "FreeWorks_DrawSketchChamfer": ("Sketch Chamfer", "Sketcher_CreateFillet",
                                    "Bevels the corner where two sketch lines meet."),
    "FreeWorks_DrawTrimEntities": ("Trim Entities", "Sketcher_Trimming",
                                   "Trims sketch entities back to where they meet others."),
    "FreeWorks_DrawConvertEntities": ("Convert Entities", "Sketcher_Projection",
                                      "Makes sketch entities on top of the picked model edges."),
    "FreeWorks_DrawOffsetEntities": ("Offset Entities", "Sketcher_Offset",
                                     "Copies sketch entities a set distance away."),
    "FreeWorks_DrawMirrorEntities": ("Mirror Entities", "Sketcher_Symmetry",
                                     "Mirrors sketch entities about a line."),
    "FreeWorks_DrawLinearSketchPattern": ("Linear Sketch Pattern", "Sketcher_RectangularArray",
                                          "Copies sketch entities in rows and columns."),
    "FreeWorks_DrawCircularSketchPattern": ("Circular Sketch Pattern", "Sketcher_RectangularArray",
                                            "Copies sketch entities round a centre."),
    "FreeWorks_DrawMoveEntities": ("Move Entities", "Sketcher_Move", "Moves sketch entities."),
    "FreeWorks_DrawCopyEntities": ("Copy Entities", "Sketcher_Copy", "Copies sketch entities."),
    "FreeWorks_DrawRotateEntities": ("Rotate Entities", "Sketcher_Rotate", "Rotates sketch entities."),
    "FreeWorks_DrawScaleEntities": ("Scale Entities", "Sketcher_Scale", "Scales sketch entities."),
    "FreeWorks_DrawDisplayDeleteRelations": ("Display/Delete Relations", "Constraint_PointOnPoint",
                                             "Shows and deletes the drawing sketch's relations."),
    "FreeWorks_DrawAddRelation": ("Add Relation", "Constraint_PointOnPoint",
                                  "Adds a relation (Horizontal, Parallel, Coincident...) to sketch entities."),
    "FreeWorks_DrawQuickSnaps": ("Quick Snaps", "Sketcher_CreatePoint",
                                 "Turns the sketch snaps on and off while sketching."),
}
PANELS = {"FreeWorks_DrawSketchMidpointLine": MidpointLinePanel, "FreeWorks_DrawSketchFillet": FilletPanel,
          "FreeWorks_DrawSketchChamfer": ChamferPanel, "FreeWorks_DrawTrimEntities": TrimPanel,
          "FreeWorks_DrawOffsetEntities": OffsetPanel, "FreeWorks_DrawMirrorEntities": MirrorPanel,
          "FreeWorks_DrawLinearSketchPattern": PatternPanel, "FreeWorks_DrawCircularSketchPattern": CircularPatternPanel,
          "FreeWorks_DrawMoveEntities": MovePanel, "FreeWorks_DrawCopyEntities": CopyPanel,
          "FreeWorks_DrawRotateEntities": RotatePanel, "FreeWorks_DrawScaleEntities": ScalePanel,
          "FreeWorks_DrawDisplayDeleteRelations": RelationsPanel, "FreeWorks_DrawAddRelation": AddRelationPanel}
NEEDS_SELECTION = ("FreeWorks_DrawMoveEntities", "FreeWorks_DrawCopyEntities", "FreeWorks_DrawRotateEntities",
                   "FreeWorks_DrawScaleEntities")


class _Command(SK._Command):
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def IsActive(self):
        if self.name == "FreeWorks_DrawQuickSnaps":
            return sketch_panel_open() is not None
        page = D.active_page()
        if page is None or not D.sheet_shown(page):
            return SK._Command.IsActive(self)
        if D.busy():
            return False
        if self.name == "FreeWorks_DrawConvertEntities":
            return picked_model_edges()[0] is not None
        if self.name in NEEDS_SELECTION:
            return bool(selected())
        return True

    def Activated(self):
        if self.name == "FreeWorks_DrawQuickSnaps":
            m = quick_snaps_menu()
            quick_snaps_menu.last = m
            m.popup(QtGui.QCursor.pos())
            return
        page = D.active_page()
        if page is None or not D.sheet_shown(page):
            twin = self.part_twin()
            if twin is not None:
                Gui.runCommand(twin, 0)
            return
        if self.name == "FreeWorks_DrawConvertEntities":
            v, idx = picked_model_edges()
            if v is None:
                return
            doc = v.Document
            doc.openTransaction("Convert Entities")
            try:
                convert(v, idx)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            doc.recompute()
            Gui.Selection.clearSelection()
            return
        D._show(PANELS[self.name](page))


def register():
    try:
        import Draft_rc  # noqa: F401  (stock Draft's icons: Rotate and Scale use them)
    except Exception as _fw_err:
        _fw_log("drawsketchedit.py:1958", _fw_err)
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
