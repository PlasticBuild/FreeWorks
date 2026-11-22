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

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import pickguard
from . import pmboxes
from . import naming

V = App.Vector
COMMAND = "SWStyle_BoundarySurface"
TITLE = "Boundary-Surface"
ICON = "FEATURES_BOUNDARY_SURFACE"
MEET = 1e-3            # how close crossing curves must come, mm
GRID = 33              # grid points across the net, each way


# --------------------------------------------------------------------------- curves
class Curve:
    """A chain of edges walked by length: point(f) for f in 0..1. A chain of several edges is
    walked on one spline through closely spaced points on it."""

    def __init__(self, wire, name=""):
        self.name = name
        self.source = wire
        if len(wire.Edges) == 1:
            self.edge = wire.Edges[0]
        else:
            ordered = Part.Wire(Part.__sortEdges__(wire.Edges))
            spline = Part.BSplineCurve()
            spline.interpolate(ordered.discretize(Number=max(80, 40 * len(wire.Edges))))
            self.edge = spline.toShape()
        self.length = self.edge.Length
        self.reversed = False

    def _point(self, f):
        e = self.edge
        return e.valueAt(e.getParameterByLength(max(0.0, min(1.0, f)) * self.length))

    def point(self, f):
        return self._point(1.0 - f if self.reversed else f)

    def fraction(self, point):
        """The fraction along the curve of its point nearest to point; (fraction, distance)."""
        e = self.edge
        dist, pairs, _ = e.distToShape(Part.Vertex(point))
        u = e.Curve.parameter(pairs[0][0])
        u = max(e.FirstParameter, min(e.LastParameter, u))
        along = Part.Edge(e.Curve, e.FirstParameter, u).Length if u > e.FirstParameter + 1e-12 else 0.0
        f = along / self.length
        return (1.0 - f if self.reversed else f), dist

    def start(self):
        return self.point(0.0)

    def end(self):
        return self.point(1.0)

    def wire(self):
        """The curve's own edges, run the curve's way (exact, for the loft)."""
        w = self.source
        first = w.Vertexes[0].Point if len(w.Edges) == 1 else Part.Wire(Part.__sortEdges__(w.Edges)).OrderedVertexes[0].Point
        runs_forward = first.distanceToPoint(self.start()) < first.distanceToPoint(self.end())
        if len(w.Edges) > 1:
            w = Part.Wire(Part.__sortEdges__(w.Edges))
        return w if runs_forward else w.reversed()


def _blend(values, params, t):
    """The value at t of a spline through values (vectors) at params (a line for two, the
    value itself for one)."""
    if len(values) == 1:
        return V(values[0])
    if len(values) == 2:
        a, b = params
        s = (t - a) / (b - a)
        return values[0] * (1 - s) + values[1] * s
    curve = Part.BSplineCurve()
    curve.interpolate(values, Parameters=params)
    return curve.value(t)


INFLUENCE = ("Global", "To Next Curve", "To Next Sharp", "To Next Edge", "Linear")


def _local(values, params, t):
    """A curve's influence reaching only to the next curves: a piecewise cubic through the values
    (Catmull-Rom tangents), so moving one curve changes the surface only up to its neighbours."""
    k = len(params) - 2
    for i in range(len(params) - 1):
        if t <= params[i + 1]:
            k = i
            break
    a, b = params[k], params[k + 1]
    h = (b - a) or 1.0
    s = (t - a) / h
    def slope(i):
        if 0 < i < len(params) - 1:
            return (values[i + 1] - values[i - 1]) * (1.0 / (params[i + 1] - params[i - 1]))
        j = 1 if i == 0 else i
        return (values[j] - values[j - 1]) * (1.0 / (params[j] - params[j - 1]))
    m0, m1 = slope(k) * h, slope(k + 1) * h
    h00, h10, h01, h11 = 2 * s ** 3 - 3 * s ** 2 + 1, s ** 3 - 2 * s ** 2 + s, -2 * s ** 3 + 3 * s ** 2, s ** 3 - s ** 2
    return values[k] * h00 + m0 * h10 + values[k + 1] * h01 + m1 * h11


def _linear(values, params, t):
    k = len(params) - 2
    for i in range(len(params) - 1):
        if t <= params[i + 1]:
            k = i
            break
    a, b = params[k], params[k + 1]
    s = (t - a) / ((b - a) or 1.0)
    return values[k] * (1 - s) + values[k + 1] * s


def _influenced(values, params, t, mode):
    ""

    values = [V(x) for x in values]
    if len(values) <= 2 or mode == "Global":
        return None
    return _linear(values, params, t) if mode == "Linear" else _local(values, params, t)


def _edge_runs(wire, n):
    """The wire's edges in order, each as n points running the way the wire goes."""
    edges = list(Part.Wire(Part.__sortEdges__(wire.Edges)).OrderedEdges) if len(wire.Edges) > 1 else list(wire.Edges)
    runs, last = [], None
    for e in edges:
        pts = e.discretize(Number=n)
        if last is None and len(edges) > 1:
            nxt = edges[1]
            ends = [v.Point for v in nxt.Vertexes]
            if min(pts[0].distanceToPoint(q) for q in ends) < min(pts[-1].distanceToPoint(q) for q in ends):
                pts.reverse()
        elif last is not None and pts[0].distanceToPoint(last) > pts[-1].distanceToPoint(last):
            pts.reverse()
        runs.append(pts)
        last = pts[-1]
    return runs


def _lined_runs(prev, runs):
    """runs started at the edge (and run the way) that best follows prev, so the sections line up."""
    best, count = None, len(runs)
    for flip in (False, True):
        base = [list(reversed(r)) for r in reversed(runs)] if flip else runs
        for k in range(count):
            cand = base[k:] + base[:k]
            cost = sum(a[0].distanceToPoint(b[0]) for a, b in zip(prev, cand))
            if best is None or cost < best[0]:
                best = (cost, cand)
    return best[1]


def influenced_sections(wires, mode, per=6, n=12):
    """Direction 1 curves only, three or more of them, To Next Curve / Sharp / Edge: each curve
    shapes the surface only up to its neighbours. In-between sections are added along a piecewise
    cubic through the curves (the same one the curve net uses), edge by edge so corners stay corners.
    The wires as they are for any other case (Global; Linear is a ruled loft)."""
    if mode not in ("To Next Curve", "To Next Sharp", "To Next Edge") or len(wires) < 3:
        return list(wires)
    runs = [_edge_runs(w, n) for w in wires]
    if len(set(len(r) for r in runs)) != 1:
        return list(wires)          # the curves differ in edge count: the plain loft
    for i in range(1, len(runs)):
        runs[i] = _lined_runs(runs[i - 1], runs[i])
    centres = [w.CenterOfMass for w in wires]
    dist = [0.0]
    for a, b in zip(centres, centres[1:]):
        dist.append(dist[-1] + max((b - a).Length, 1e-9))
    params = [x / dist[-1] for x in dist]
    out = []
    for k in range(len(wires) - 1):
        out.append(wires[k])
        for j in range(1, per):
            t = params[k] + (params[k + 1] - params[k]) * j / float(per)
            edges = []
            for e in range(len(runs[0])):
                pts = [_local([runs[i][e][q] for i in range(len(wires))], params, t) for q in range(n)]
                curve = Part.BSplineCurve()
                curve.interpolate(pts)
                edges.append(curve.toShape())
            out.append(Part.Wire(edges))
    out.append(wires[-1])
    return out


def _splines(values, params):
    if len(values) <= 2:
        return None
    curve = Part.BSplineCurve()
    curve.interpolate(values, Parameters=params)
    return curve


def _at(spline, values, params, t):
    if len(values) == 1:
        return V(values[0])
    if spline is None:
        a, b = params
        s = (t - a) / (b - a)
        return values[0] * (1 - s) + values[1] * s
    return spline.value(t)


def _map(knots, values, t):
    """Piecewise straight map from knots to values."""
    for k in range(len(knots) - 1):
        if t <= knots[k + 1] or k == len(knots) - 2:
            a, b = knots[k], knots[k + 1]
            s = (t - a) / (b - a) if b > a else 0.0
            return values[k] + (values[k + 1] - values[k]) * s


# --------------------------------------------------------------------------- options
TANGENTS = ("None", "Direction Vector", "Normal To Profile", "Tangency To Face", "Curvature To Face")
OPTIONS = (("StartTangent", "App::PropertyEnumeration", "Tangent type at the first Direction 1 curve"),
           ("EndTangent", "App::PropertyEnumeration", "Tangent type at the last Direction 1 curve"),
           ("StartDraft", "App::PropertyAngle", "Draft angle at the first curve"),
           ("EndDraft", "App::PropertyAngle", "Draft angle at the last curve"),
           ("StartLength", "App::PropertyLength", "Tangent length at the first curve"),
           ("EndLength", "App::PropertyLength", "Tangent length at the last curve"),
           ("StartDirection", "App::PropertyLinkSubGlobal", "Direction vector at the first curve (a line, edge, face or plane)"),
           ("EndDirection", "App::PropertyLinkSubGlobal", "Direction vector at the last curve (a line, edge, face or plane)"),
           ("CloseSurface", "App::PropertyBool", "Close surface: the last curve joins back to the first"),
           ("MergeTangentFaces", "App::PropertyBool", "Merge tangent faces"),
           ("TrimDirection1", "App::PropertyBool", "Trim by direction 1: the surface stops at the outer Direction 2 curves"),
           ("TrimDirection2", "App::PropertyBool", "Trim by direction 2: the surface stops at the outer Direction 1 curves"))


def ensure_options(obj):
    ""
    have = obj.PropertiesList
    for name, kind, tip in OPTIONS:
        if name in have and kind == "App::PropertyEnumeration":
            values = obj.getEnumerationsOfProperty(name) or []
            if list(values) != list(TANGENTS):      # older file: offer the new tangent types
                keep = str(getattr(obj, name))
                setattr(obj, name, list(TANGENTS))
                setattr(obj, name, keep if keep in TANGENTS else "None")
        if name not in have:
            obj.addProperty(kind, name, "Boundary", tip)
            if kind == "App::PropertyEnumeration":
                setattr(obj, name, list(TANGENTS))
                setattr(obj, name, "None")
            elif kind == "App::PropertyLength":
                setattr(obj, name, 5.0)
            elif name in ("MergeTangentFaces", "TrimDirection1", "TrimDirection2"):
                setattr(obj, name, True)        # Trim: older features were always trimmed (new ones start off)
    for name in ("Direction1Influence", "Direction2Influence"):
        if name not in obj.PropertiesList:
            obj.addProperty("App::PropertyEnumeration", name, "Boundary",
                            "Direction curves influence: how far each curve shapes the surface")
            setattr(obj, name, list(INFLUENCE))
            setattr(obj, name, "Global")


def _normal_of(wire, towards):
    """The plane normal of a closed wire, pointing towards a point."""
    try:
        n = Part.Face(wire).normalAt(0, 0)
    except Exception:
        pts = wire.discretize(Number=12)
        n = (pts[1] - pts[0]).cross(pts[2] - pts[0])
    if n.Length < 1e-9:
        n = V(0, 0, 1)
    n.normalize()
    if (towards - wire.CenterOfMass).dot(n) < 0:
        n = n * -1
    return n


def _tangent_section(wire, towards, draft, length):
    """A copy of an end curve moved into the loft along its normal: the loft leaves the curve
    square to it (Normal To Profile), narrowing or widening by the draft angle."""
    import math
    n = _normal_of(wire, towards)
    length = max(float(length), 0.01)
    centre = wire.CenterOfMass
    size = max(wire.BoundBox.DiagonalLength / 2, 0.01)
    scale = max(1.0 - math.tan(math.radians(float(draft))) * length / size, 0.05)
    m = App.Matrix()
    m.move(centre * -1)
    m.scale(scale, scale, scale)
    m.move(centre + n * length)
    w = wire.copy()
    w.transformShape(m)
    return w


def _vector_of(link):
    """The way a Direction Vector pick points: a line or edge along it, a face or plane square to it."""
    if not link:
        return None
    src, subs = link[0], link[1] if len(link) > 1 else []
    sub = (subs[0] if isinstance(subs, (list, tuple)) and subs else subs) or ""
    try:
        if not sub and src.TypeId in ("App::Plane", "PartDesign::Plane"):
            return src.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
        if not sub and src.TypeId in ("App::Line", "PartDesign::Line"):
            return src.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
        shape = Part.getShape(src)
        el = shape.getElement(sub) if sub else (shape.Edges[0] if shape.Edges else None)
        if el is None:
            return None
        if el.ShapeType == "Face":
            return V(el.normalAt(*el.Surface.parameter(el.CenterOfMass)))
        if el.ShapeType == "Edge":
            d = el.Vertexes[-1].Point - el.Vertexes[0].Point
            return d if d.Length > 1e-9 else el.tangentAt(el.FirstParameter)
    except Exception:
        return None
    return None


def _moved_section(wire, n, towards, draft, length):
    """A copy of an end curve moved along n (turned to the next curve), flared by the draft angle."""
    import math
    n = V(n)
    n.normalize()
    if (towards - wire.CenterOfMass).dot(n) < 0:
        n = n * -1
    length = max(float(length), 0.01)
    centre = wire.CenterOfMass
    size = max(wire.BoundBox.DiagonalLength / 2, 0.01)
    scale = max(1.0 - math.tan(math.radians(float(draft))) * length / size, 0.05)
    m = App.Matrix()
    m.move(centre * -1)
    m.scale(scale, scale, scale)
    m.move(centre + n * length)
    w = wire.copy()
    w.transformShape(m)
    return w


def _face_section(wire, pick, towards, length, kind):
    """Tangency / Curvature To Face: the end curve is an edge of a face. Each point of it is set off
    the way the face carries on past the edge, so the surface leaves the face tangent to it.
    Curvature adds a second row half way, so the surface holds on to the face's way longer."""
    src, sub = pick
    if not sub or not sub.startswith("Edge"):
        raise RuntimeError("%s needs the end curve to be an edge of a face" % kind)
    shape = Part.getShape(src)
    edge = shape.getElement(sub)
    faces = [f for f in shape.Faces if any(e.isSame(edge) for e in f.Edges)]
    if not faces:
        raise RuntimeError("%s: the end curve is not an edge of a face" % kind)
    from .surfacefeatures import _out_at
    mid_t = (edge.FirstParameter + edge.LastParameter) / 2.0
    face = max(faces, key=lambda f: _out_at(f, edge, mid_t).dot(towards - edge.valueAt(mid_t)))
    reach = max(float(length), 0.01)
    base = wire.discretize(Number=24)
    ways = [_out_at(face, edge, edge.Curve.parameter(p)) for p in base]
    rows = []
    for k in ((0.5, 1.0) if kind == "Curvature To Face" else (1.0,)):
        pts = [p + w * (reach * k) for p, w in zip(base, ways)]
        bs = Part.BSplineCurve()
        if wire.isClosed() and (pts[0] - pts[-1]).Length < 1e-6:
            bs.interpolate(pts[:-1], PeriodicFlag=True)
        else:
            bs.interpolate(pts)
        rows.append(Part.Wire([bs.toShape()]))
    return rows


def _end_section(obj, end, wire, nxt, pick):
    kind = str(getattr(obj, end + "Tangent"))
    draft, length = getattr(obj, end + "Draft"), getattr(obj, end + "Length")
    if kind == "Normal To Profile":
        return _tangent_section(wire, nxt.CenterOfMass, draft, length)
    if kind == "Direction Vector":
        n = _vector_of(getattr(obj, end + "Direction", None))
        if n is None:
            raise RuntimeError("Pick the direction vector for the %s curve" % ("first" if end == "Start" else "last"))
        return _moved_section(wire, n, nxt.CenterOfMass, draft, length)
    if kind in ("Tangency To Face", "Curvature To Face"):
        return _face_section(wire, pick, nxt.CenterOfMass, length, kind)
    return None


def sections(wires, obj=None):
    ""
    wires = list(wires)
    if obj is None or len(wires) < 2 or "StartTangent" not in obj.PropertiesList:
        return wires
    picks = _items(getattr(obj, "Direction1", None))
    first = picks[0] if picks else (None, "")
    last = picks[-1] if picks else (None, "")
    out = list(wires)
    tail = _end_section(obj, "End", wires[-1], wires[-2], last)
    if tail is not None:
        tail = tail if isinstance(tail, list) else [tail]
        out[len(out) - 1:len(out) - 1] = list(reversed(tail))   # the far row first, the near row by the curve
    head = _end_section(obj, "Start", wires[0], wires[1], first)
    if head is not None:
        out[1:1] = head if isinstance(head, list) else [head]
    return out


def closed(obj):
    return bool(obj is not None and getattr(obj, "CloseSurface", False))


# --------------------------------------------------------------------------- surfaces
def loft(first, obj=None, merge=False):
    """Direction 1 only: a loft through the curves, ends lined up. merge (Merge tangent faces): the
    tangent runs of each curve loft as one face."""
    if len(first) < 2:
        raise RuntimeError("Pick at least two curves for Direction 1")
    if merge:
        from .surfacepms import merge_tangent_chains
        for c in first:
            c.source = merge_tangent_chains(c.source)
    _line_up(first)
    mode = str(getattr(obj, "Direction1Influence", "Global")) if obj is not None else "Global"
    ruled = mode == "Linear"
    wires = [c.wire() for c in first]
    held = None if ruled else _held(wires, obj)
    if held is not None:
        return held
    if not closed(obj):
        wires = influenced_sections(wires, mode)
    return Part.makeLoft(sections(wires, obj), False, ruled, closed(obj))


HANDLE = {"Curvature To Face": 1.5}      # Curvature To Face holds the face's way further in


def _ways(obj, end, wire, other, pts):
    """The unit way the surface leaves an end curve with, at each of its points."""
    kind = str(getattr(obj, end + "Tangent"))
    towards = other.CenterOfMass
    if kind == "Normal To Profile":
        return [_normal_of(wire, towards)] * len(pts)
    if kind == "Direction Vector":
        n = _vector_of(getattr(obj, end + "Direction", None))
        if n is None:
            raise RuntimeError("Pick the direction vector for the %s curve" % ("first" if end == "Start" else "last"))
        n = V(n)
        n.normalize()
        return [n if (towards - wire.CenterOfMass).dot(n) >= 0 else n * -1] * len(pts)
    picks = _items(getattr(obj, "Direction1", None))
    src, sub = picks[0] if end == "Start" else picks[-1]
    if not sub or not sub.startswith("Edge"):
        raise RuntimeError("%s needs the end curve to be an edge of a face" % kind)
    shape = Part.getShape(src)
    edge = shape.getElement(sub)
    faces = [f for f in shape.Faces if any(e.isSame(edge) for e in f.Edges)]
    if not faces:
        raise RuntimeError("%s: the end curve is not an edge of a face" % kind)
    from .surfacefeatures import _out_at
    mid_t = (edge.FirstParameter + edge.LastParameter) / 2.0
    face = max(faces, key=lambda f: _out_at(f, edge, mid_t).dot(towards - edge.valueAt(mid_t)))
    out = []
    for p in pts:
        t = min(max(edge.Curve.parameter(p), edge.FirstParameter), edge.LastParameter)
        w = V(_out_at(face, edge, t))
        w.normalize()
        out.append(w)
    return out


def _held(wires, obj, m=40):
    ""



    if obj is None or len(wires) != 2 or closed(obj) or "StartTangent" not in obj.PropertiesList:
        return None
    kinds = [str(getattr(obj, e + "Tangent")) for e in ("Start", "End")]
    if all(k == "None" for k in kinds):
        return None
    a, b = wires
    if a.isClosed() != b.isClosed():
        return None
    if any(float(getattr(obj, e + "Draft")) for e, k in zip(("Start", "End"), kinds) if k != "None"):
        return None
    from .surfacepms import held_points, held_surface, held_closed_ok
    if a.isClosed() and not held_closed_ok(a, b, kinds):
        return None
    pa, pb = held_points(a, b, m)
    gap = (b.CenterOfMass - a.CenterOfMass).Length
    inner = []
    for end, wire, other, pts, opp, kind in (("Start", a, b, pa, pb, kinds[0]), ("End", b, a, pb, pa, kinds[1])):
        if kind == "None":
            inner.append([p + (q - p) * (1.0 / 3.0) for p, q in zip(pts, opp)])
            continue
        reach = min(max(float(getattr(obj, end + "Length")), 0.01) * HANDLE.get(kind, 1.0), gap)
        ways = _ways(obj, end, wire, other, pts)
        inner.append([p + w * reach for p, w in zip(pts, ways)])
    return held_surface(pa, inner[0], inner[1], pb, a.isClosed())


def _line_up(chain):
    """Runs each curve the way the one before it runs (by its ends)."""
    for prev, cur in zip(chain, chain[1:]):
        if cur.start().distanceToPoint(prev.start()) + cur.end().distanceToPoint(prev.end()) > \
                cur.start().distanceToPoint(prev.end()) + cur.end().distanceToPoint(prev.start()):
            cur.reversed = not cur.reversed


def _knots(rows, count):
    """Grid parameters of the crossings along one direction: evenly spaced for two or more
    curves the other way; for a single curve, where it crosses on average (with the ends added,
    so the single curve is reached at the same grid line on every curve)."""
    if count > 1:
        return [k / (count - 1.0) for k in range(count)], rows
    mean = sum(r[0] for r in rows) / len(rows)
    return [0.0, mean, 1.0], [[0.0, r[0], 1.0] for r in rows]


def _overhang(rows):
    """How far the curves run past their outer crossings, in units of the span between them
    (before, after); rows = each curve's crossing fractions, in order."""
    span = sum(r[-1] - r[0] for r in rows) / len(rows)
    if span <= 1e-9:
        return 0.0, 0.0
    return (max(0.0, sum(r[0] for r in rows) / len(rows) / span),
            max(0.0, sum(1.0 - r[-1] for r in rows) / len(rows) / span))


def _untrimmed(knots, rows, ext):
    """The grid knots and crossing rows reaching the curves' ends (Trim off)."""
    a, b = ext
    if a < 1e-3 and b < 1e-3:
        return knots, rows, [k / (GRID - 1.0) for k in range(GRID)]
    lo, hi = knots[0] - a, knots[-1] + b
    k2 = ([lo] if a >= 1e-3 else []) + list(knots) + ([hi] if b >= 1e-3 else [])
    r2 = [([0.0] if a >= 1e-3 else []) + list(r) + ([1.0] if b >= 1e-3 else []) for r in rows]
    lo, hi = k2[0], k2[-1]
    return k2, r2, [lo + (hi - lo) * k / (GRID - 1.0) for k in range(GRID)]


def net(first, second, grid=GRID, trim1=True, trim2=True, influence1="Global", influence2="Global"):
    """Both directions: a Gordon surface through the curve net. One direction may hold a single
    curve: the surface then passes through it as well."""
    n, m = len(first), len(second)
    if n < 1 or m < 1 or n + m < 3:
        raise RuntimeError("Pick at least two curves for Direction 1")
    # where each Direction 2 curve crosses each Direction 1 curve
    def crossing(a, b):
        dist, pairs, _ = a.wire().distToShape(b.wire())
        if dist > MEET:
            raise RuntimeError("%s and %s do not meet (%.3f mm apart)" % (a.name, b.name, dist))
        return pairs[0][0]
    X = [[crossing(first[i], second[j]) for j in range(m)] for i in range(n)]
    # order the Direction 2 curves along the first Direction 1 curve, and the Direction 1
    # curves along the first Direction 2 curve, then run every curve the same way
    order2 = sorted(range(m), key=lambda j: first[0].fraction(X[0][j])[0])
    second = [second[j] for j in order2]
    X = [[row[j] for j in order2] for row in X]
    order1 = sorted(range(n), key=lambda i: second[0].fraction(X[i][0])[0])
    first = [first[i] for i in order1]
    X = [X[i] for i in order1]
    if m > 1:
        for i, c in enumerate(first):
            if c.fraction(X[i][0])[0] > c.fraction(X[i][-1])[0]:
                c.reversed = not c.reversed
    else:
        _line_up(first)
    if n > 1:
        for j, c in enumerate(second):
            if c.fraction(X[0][j])[0] > c.fraction(X[-1][j])[0]:
                c.reversed = not c.reversed
    else:
        _line_up(second)
    # crossing parameters: u along Direction 1 curves, v along Direction 2 curves
    U, t1 = _knots([[first[i].fraction(X[i][j])[0] for j in range(m)] for i in range(n)], m)
    Vv, t2 = _knots([[second[j].fraction(X[i][j])[0] for i in range(n)] for j in range(m)], n)
    for row in t1 + t2:
        if any(b < a - 1e-9 for a, b in zip(row, row[1:])):
            raise RuntimeError("The curves cross out of order: pick a net where each curve crosses the "
                               "others once")
    Uc = U if m > 1 else [U[1]]
    Vc = Vv if n > 1 else [Vv[1]]
    us = [k / (grid - 1.0) for k in range(grid)]
    vs = us

    # runs on to the ends of the curves that reach past them (the crossings carried on)
    if not trim1 and m > 1:
        U, t1, us = _untrimmed(U, t1, _overhang(t1))
    if not trim2 and n > 1:
        Vv, t2, vs = _untrimmed(Vv, t2, _overhang(t2))
    # points on the curves at the grid's u (Direction 1) and v (Direction 2)
    P1 = [[first[i].point(_map(U, t1[i], u)) for u in us] for i in range(n)]
    P2 = [[second[j].point(_map(Vv, t2[j], v)) for v in vs] for j in range(m)]
    # the crossings as a tensor spline: across i at each j first
    across = [_splines([X[i][j] for i in range(n)], Vc) for j in range(m)]
    rows = []
    for a, u in enumerate(us):
        s1 = _splines([P1[i][a] for i in range(n)], Vc)
        row = []
        for b, v in enumerate(vs):
            c1 = [P1[i][a] for i in range(n)]
            l1 = _at(s1, c1, Vc, v) if influence1 == "Global" or n <= 2 else _influenced(c1, Vc, v, influence1)
            s2 = [P2[j][b] for j in range(m)]
            l2 = _blend(s2, Uc, u) if influence2 == "Global" or m <= 2 else _influenced(s2, Uc, u, influence2)
            tv = []
            for j in range(m):
                cj = [X[i][j] for i in range(n)]
                tv.append(_at(across[j], cj, Vc, v) if influence1 == "Global" or n <= 2 else _influenced(cj, Vc, v, influence1))
            t = _blend(tv, Uc, u) if influence2 == "Global" or m <= 2 else _influenced(tv, Uc, u, influence2)
            row.append(l1 + l2 - t)
        rows.append(row)
    surface = Part.BSplineSurface()
    surface.interpolate(rows)
    return surface.toShape()


# --------------------------------------------------------------------------- picks
def curves(links):
    """One Curve per pick: an edge, or a whole sketch or wire object as one chain."""
    out = []
    for obj, subs in links or []:
        subs = subs if isinstance(subs, (list, tuple)) else [subs]
        shape = Part.getShape(obj)
        for sub in subs or [""]:
            if sub:
                edge = shape.getElement(sub)
                out.append(Curve(Part.Wire([edge]), "%s.%s" % (obj.Label, sub)))
            else:
                edges = [e for e in shape.Edges]
                if not edges:
                    continue
                out.append(Curve(Part.Wire(Part.__sortEdges__(edges)), obj.Label))
    return out


# --------------------------------------------------------------------------- the feature
class BoundarySurface:
    def __init__(self, obj):
        obj.addProperty("App::PropertyLinkSubListGlobal", "Direction1", "Boundary Surface",
                        "Direction 1 curves, in order")
        obj.addProperty("App::PropertyLinkSubListGlobal", "Direction2", "Boundary Surface",
                        "Direction 2 curves (optional), crossing the Direction 1 curves")
        obj.Proxy = self

    def execute(self, obj):
        ensure_options(obj)
        first = curves(obj.Direction1)
        second = curves(obj.Direction2)
        if len(first) < 2 and len(second) < 2:
            obj.Shape = Part.Shape()
            return
        merge = bool(getattr(obj, "MergeTangentFaces", True))
        if len(second) == 0 or len(first) == 0:
            shape = loft(first or second, obj if first else None, merge)
        elif len(first) < 2 and len(second) < 2:
            raise RuntimeError("Pick at least two curves for Direction 1")
        else:
            shape = net(first, second, trim1=bool(getattr(obj, "TrimDirection1", True)),
                        trim2=bool(getattr(obj, "TrimDirection2", True)),
                        influence1=str(getattr(obj, "Direction1Influence", "Global")),
                        influence2=str(getattr(obj, "Direction2Influence", "Global")))
        if merge:
            try:
                shape = shape.removeSplitter()
            except Exception as _fw_err:
                _fw_log("boundarysurface.py:626", _fw_err)
        obj.Shape = shape

    def onDocumentRestored(self, obj):
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class View:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            icon = icons.family(ICON)
            if not icon.isNull():
                return icon         # a QIcon: FreeCAD reads a returned QPixmap as a QIcon
        except Exception as _fw_err:
            _fw_log("boundarysurface.py:653", _fw_err)
        return ":/icons/Surface_GeomFillSurface.svg"

    def claimChildren(self):
        obj = self.Object
        out = []
        for link in list(obj.Direction1 or []) + list(obj.Direction2 or []):
            o = link[0]
            if o.TypeId == "Sketcher::SketchObject" and o not in out:
                out.append(o)
        return out

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(Panel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


# --------------------------------------------------------------------------- PropertyManager
_open = {"panel": None}


def current():
    return _open["panel"]


def _items(links):
    out = []
    for obj, subs in links or []:
        subs = subs if isinstance(subs, (list, tuple)) else [subs]
        for sub in subs or [""]:
            out.append((obj, sub))
    return out


_DATUMS = ("App::Plane", "App::Line", "App::Point", "App::Origin", "PartDesign::Plane", "PartDesign::Line",
           "PartDesign::Point", "PartDesign::CoordinateSystem", "Part::DatumPlane", "Part::DatumLine",
           "Part::DatumPoint")


def _sketch_edge_at(doc, point, own=None):
    """(sketch, "EdgeN") of the shown sketch edge nearest the picked point, or (None, "")."""
    if point is None:
        return None, ""
    try:
        p = App.Vector(*point) if not isinstance(point, App.Vector) else point
    except Exception:
        return None, ""
    best, found = None, (None, "")
    for o in doc.Objects:
        if o is own or not o.isDerivedFrom("Sketcher::SketchObject"):
            continue
        try:
            if o.ViewObject is None or not o.ViewObject.isVisible():
                continue
            shape = o.Shape
            size = max(shape.BoundBox.DiagonalLength, 1.0)
            for i, e in enumerate(shape.Edges, 1):
                d = e.distToShape(Part.Vertex(p))[0]
                if d <= max(0.02 * size, 0.5) and (best is None or d < best):
                    best, found = d, (o, "Edge%d" % i)
        except Exception as _fw_err:
            _fw_log("boundarysurface._sketch_edge_at", _fw_err)
    return found


class Panel:
    ""

    def __init__(self, obj):
        _open["panel"] = self
        self.obj = obj
        self.busy = False
        self.boxes = {}
        pages = []
        for key, title in (("Direction1", "Direction 1"), ("Direction2", "Direction 2")):
            page = QtWidgets.QWidget()
            page.setWindowTitle(title)
            lay = QtWidgets.QVBoxLayout(page)
            box = QtWidgets.QListWidget()
            box.setObjectName("SWStyle_Boundary%s" % key)
            box.setMaximumHeight(90)
            box.setToolTip("Curves in order: edges, or a whole sketch as one curve")
            box.installEventFilter(self._focus(key))

            row = QtWidgets.QHBoxLayout()
            arrows = QtWidgets.QVBoxLayout()
            style = QtWidgets.QApplication.style()
            for text, pix, step in (("Move Up", QtWidgets.QStyle.SP_ArrowUp, -1),
                                    ("Move Down", QtWidgets.QStyle.SP_ArrowDown, 1)):
                b = QtWidgets.QToolButton()
                b.setObjectName("SWStyle_Boundary%s%s" % (key, text.replace(" ", "")))
                b.setIcon(style.standardIcon(pix))
                b.setToolTip(text)
                b.setAccessibleName(text)
                b.setAutoRaise(True)
                b.clicked.connect(lambda checked=False, k=key, st=step: self.move(k, st))
                arrows.addWidget(b)
            arrows.addStretch(1)
            row.addLayout(arrows)
            row.addWidget(box, 1)
            lay.addLayout(row)
            ensure_options(obj)
            inf_row = QtWidgets.QVBoxLayout()
            inf_row.setSpacing(2)
            inf_row.addWidget(QtWidgets.QLabel("Direction curves influence:"))
            combo = QtWidgets.QComboBox()
            combo.setObjectName("SWStyle_Boundary%sInfluence" % key)
            combo.addItems(list(INFLUENCE))
            combo.setCurrentText(str(getattr(obj, key + "Influence")))
            combo.currentTextChanged.connect(lambda text, k=key: self._influence_changed(k, text))
            inf_row.addWidget(combo)
            lay.addLayout(inf_row)
            setattr(self, "influence_" + key, combo)
            self.boxes[key] = box
            pages.append(page)
            if key == "Direction1":
                self._tangent_rows(page, lay)
        ensure_options(obj)
        options = QtWidgets.QWidget()
        options.setWindowTitle("Options and Preview")
        olay = QtWidgets.QVBoxLayout(options)
        self.merge_faces = QtWidgets.QCheckBox("Merge tangent faces")
        self.merge_faces.setObjectName("SWStyle_BoundaryMergeTangent")
        self.merge_faces.setChecked(bool(obj.MergeTangentFaces))
        self.close_surface = QtWidgets.QCheckBox("Close surface")
        self.close_surface.setObjectName("SWStyle_BoundaryClose")
        self.close_surface.setChecked(bool(obj.CloseSurface))
        self.trim1 = QtWidgets.QCheckBox("Trim by direction 1")
        self.trim1.setObjectName("SWStyle_BoundaryTrim1")
        self.trim1.setChecked(bool(obj.TrimDirection1))
        self.trim2 = QtWidgets.QCheckBox("Trim by direction 2")
        self.trim2.setObjectName("SWStyle_BoundaryTrim2")
        self.trim2.setChecked(bool(obj.TrimDirection2))
        for w in (self.merge_faces, self.close_surface, self.trim1, self.trim2):
            olay.addWidget(w)
            w.toggled.connect(self._options_changed)
        self.preview = QtWidgets.QCheckBox("Show preview")
        self.preview.setObjectName("SWStyle_BoundaryPreview")
        self.preview.setChecked(True)
        self.preview.toggled.connect(lambda on: setattr(obj.ViewObject, "Visibility", on))
        olay.addWidget(self.preview)

        # with the preview following (dragsketch.SketchDrag on each picked sketch)
        self.drags = []
        drag_row = QtWidgets.QHBoxLayout()
        self.drag_button = QtWidgets.QPushButton("Drag Sketch")
        self.drag_button.setObjectName("SWStyle_BoundaryDragSketch")
        self.drag_button.setCheckable(True)
        self.drag_button.setToolTip("Drag a picked sketch in the graphics area; the surface follows")
        self.drag_button.toggled.connect(self._drag_toggled)
        self.undo_drag = QtWidgets.QPushButton("Undo Sketch Drag")
        self.undo_drag.setObjectName("SWStyle_BoundaryUndoDrag")
        self.undo_drag.setVisible(False)          # shown once there is a drag to undo (no greyed button)
        self.undo_drag.clicked.connect(self._undo_drag)
        drag_row.addWidget(self.drag_button)
        drag_row.addWidget(self.undo_drag)
        olay.addLayout(drag_row)
        olay.addStretch(1)
        pages.append(options)
        from . import curvdisplay
        display = QtWidgets.QWidget()
        display.setWindowTitle("Curvature Display")
        QtWidgets.QVBoxLayout(display)
        self.curv = curvdisplay.CurvatureDisplay(lambda: obj.Shape)
        self.curv.setTitle("")           # the group's title already says Curvature Display (look audit AA4)
        self.curv.setFlat(True)
        display.layout().addWidget(self.curv)
        pages.append(display)
        pages[0].setProperty("swstyle_pm_title", "Boundary-Surface")
        pages[0].setProperty("swstyle_pm_icon", ICON)
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        pages[1].layout().addWidget(self.note)
        self.form = pages
        self.boxes["Direction1"].currentRowChanged.connect(lambda row: self._show_tangent())
        self.active = "Direction1" if not obj.Direction1 else "Direction2"
        self._show()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _tangent_rows(self, page, lay):
        ""

        self.tangent_widget = QtWidgets.QWidget(page)
        form = QtWidgets.QFormLayout(self.tangent_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.tangent = QtWidgets.QComboBox()
        self.tangent.setObjectName("SWStyle_BoundaryTangentType")
        self.tangent.addItems(list(TANGENTS))
        self.draft = QtWidgets.QDoubleSpinBox()
        self.draft.setObjectName("SWStyle_BoundaryDraft")
        self.draft.setRange(-89.0, 89.0)
        self.draft.setSuffix(" °")
        self.draft.setKeyboardTracking(False)
        self.length = QtWidgets.QDoubleSpinBox()
        self.length.setObjectName("SWStyle_BoundaryTangentLength")
        self.length.setRange(0.01, 100000.0)
        self.length.setSuffix(" mm")
        self.length.setKeyboardTracking(False)
        self.direction = QtWidgets.QListWidget()
        self.direction.setObjectName("SWStyle_BoundaryDirectionVector")
        self.direction.setMaximumHeight(26)
        self.direction.setToolTip("Direction vector: a line, edge, face or plane")
        self.direction.installEventFilter(self._focus("Direction"))
        form.addRow("Tangent Type:", self.tangent)
        form.addRow("Direction vector:", self.direction)
        form.addRow("Draft angle:", self.draft)
        form.addRow("Tangent length:", self.length)
        lay.addWidget(self.tangent_widget)
        self.tangent_widget.hide()
        self.tangent.currentIndexChanged.connect(self._tangent_changed)
        self.draft.valueChanged.connect(self._tangent_changed)
        self.length.valueChanged.connect(self._tangent_changed)

    def _tangent_end(self):
        """'Start', 'End' or None for the Direction 1 row picked."""
        box = self.boxes.get("Direction1")
        if box is None:
            return None
        row, count = box.currentRow(), box.count()
        if count < 2 or row < 0:
            return None
        return "Start" if row == 0 else ("End" if row == count - 1 else None)

    def _show_tangent(self):
        end = self._tangent_end()
        if not hasattr(self, "tangent_widget"):
            return
        self.tangent_widget.setVisible(end is not None)
        if end is None:
            return
        obj = self.obj
        self.busy = True
        try:
            self.tangent.setCurrentText(str(getattr(obj, end + "Tangent")))
            self.draft.setValue(float(getattr(obj, end + "Draft")))
            self.length.setValue(float(getattr(obj, end + "Length")))
            kind = self.tangent.currentText()
            on = kind != "None"
            flare = kind in ("Direction Vector", "Normal To Profile")
            vector = kind == "Direction Vector"
            self.direction.clear()
            link = getattr(obj, end + "Direction", None)
            if link:
                subs = link[1] if len(link) > 1 else []
                sub = (subs[0] if isinstance(subs, (list, tuple)) and subs else subs) or ""
                self.direction.addItem("%s%s" % (link[0].Label, ("." + sub) if sub else ""))
            pmboxes.mark(self.direction, self.active == "Direction")
            form = self.tangent_widget.layout()
            for w, show in ((self.direction, vector), (self.draft, flare), (self.length, on)):
                w.setVisible(show)
                label = form.labelForField(w)
                if label is not None:
                    label.setVisible(show)
        finally:
            self.busy = False

    def _tangent_changed(self, *args):
        end = self._tangent_end()
        if self.busy or end is None:
            return
        self._begin()
        obj = self.obj
        setattr(obj, end + "Tangent", self.tangent.currentText())
        if self.tangent.currentText() == "Direction Vector" and not getattr(obj, end + "Direction", None):
            self.active = "Direction"
        setattr(obj, end + "Draft", self.draft.value())
        setattr(obj, end + "Length", self.length.value())
        obj.Document.recompute()
        self._show()
        self._show_tangent()

    def _influence_changed(self, key, text):
        if self.busy:
            return
        self._begin()
        setattr(self.obj, key + "Influence", text)
        self.obj.Document.recompute()
        self._show()

    def _options_changed(self, *args):
        if self.busy:
            return
        self._begin()
        self.obj.MergeTangentFaces = self.merge_faces.isChecked()
        self.obj.CloseSurface = self.close_surface.isChecked()
        self.obj.TrimDirection1 = self.trim1.isChecked()
        self.obj.TrimDirection2 = self.trim2.isChecked()
        self.obj.Document.recompute()
        self._show()

    def _focus(self, key):
        panel = self

        class Filter(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if event.type() == QtCore.QEvent.FocusIn:
                    panel.active = key
                    panel._show()
                return False
        self._filters = getattr(self, "_filters", []) + [Filter()]
        return self._filters[-1]

    def _begin(self):
        doc = self.obj.Document
        if not doc.HasPendingTransaction:
            doc.openTransaction("Boundary Surface")

    def _set(self, key, items):
        # one entry per curve; "" = the whole object (an empty sub list would be dropped)
        setattr(self.obj, key, [(o, sub or "") for o, sub in items])

    def _show(self):
        obj = self.obj
        for key, box in self.boxes.items():
            row = box.currentRow()
            box.clear()
            for o, sub in _items(getattr(obj, key)):
                box.addItem("%s%s" % (o.Label, ("." + sub) if sub else ""))
            if 0 <= row < box.count():
                box.setCurrentRow(row)
            pmboxes.mark(box, key == self.active)
        if hasattr(self, "direction"):
            pmboxes.mark(self.direction, self.active == "Direction")
        if "Invalid" in obj.State:
            self.note.setText(obj.getStatusString())
        elif len(_items(obj.Direction1)) < 2 and len(_items(obj.Direction2)) < 2:
            self.note.setText("Pick curves for Direction 1 (edges or sketches), in order.")
        else:
            self.note.setText("")

    def move(self, key, step):
        box = self.boxes[key]
        row = box.currentRow()
        items = _items(getattr(self.obj, key))
        if not (0 <= row < len(items)) or not (0 <= row + step < len(items)):
            return
        self._begin()
        items[row], items[row + step] = items[row + step], items[row]
        self._set(key, items)
        self.obj.Document.recompute()
        self._show()
        self.boxes[key].setCurrentRow(row + step)

    # picks
    def addSelection(self, doc, name, sub, point):
        if pickguard.stale(self, self.obj):
            return
        if doc != self.obj.Document.Name:
            return
        self._point = point        # where the pick was (a plane's click finds the sketch edge there)
        QtCore.QTimer.singleShot(0, lambda: self._picked(name, sub))

    def _picked(self, name, sub):
        if self.busy:
            return
        self.busy = True
        try:
            Gui.Selection.clearSelection()
            doc = self.obj.Document
            holder = doc.getObject(name)
            for part in sub.split(".")[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    holder = found
            element = sub.split(".")[-1]
            if holder is None or holder is self.obj:
                return
            if self.active == "Direction":
                end = self._tangent_end()
                if end is None or (element and not element.startswith(("Edge", "Face"))):
                    return
                self._begin()
                setattr(self.obj, end + "Direction", (holder, [element] if element else []))
                doc.recompute()
                self._show()
                self.busy = False
                self._show_tangent()
                return
            if element and not element.startswith("Edge"):
                return
            if not element and holder.TypeId in _DATUMS:

                # shown plane is the sketch's edge under the pointer, never the plane
                holder, element = _sketch_edge_at(doc, getattr(self, "_point", None), self.obj)
                if holder is None:
                    return
            self._begin()
            items = _items(getattr(self.obj, self.active))
            key = (holder, element)
            if key in items:
                items.remove(key)
            else:
                items.append(key)
            self._set(self.active, items)
            doc.recompute()
            self._show()
        finally:
            self.busy = False

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _sketches(self):
        out = []
        for o, _sub in _items(self.obj.Direction1) + _items(self.obj.Direction2):
            if o.TypeId == "Sketcher::SketchObject" and o not in out:
                out.append(o)
        return out

    def _drag_toggled(self, on):
        kept = list(getattr(self, "drag_log", []))
        self._drop_drags()
        self.drag_log = kept            # Undo Sketch Drag keeps the drags made before Drag Sketch went off
        self.undo_drag.setVisible(bool(kept))
        if not on:
            return
        from . import dragsketch
        self._begin()
        for sk in self._sketches():
            try:
                self.drags.append(dragsketch.SketchDrag(sk, self._dragged))
            except Exception as error:
                App.Console.PrintLog("FreeCAD: drag sketch %s\n" % error)
        if not self.drags:
            self.note.setText("Pick a sketch as a curve to drag it.")
            self.drag_button.setChecked(False)

    def _dragged(self, sketch):
        """A drag (or an undo) moved sketch: note new drags in order, for Undo Sketch Drag."""
        for d in self.drags:
            if d.sketch is sketch and len(d._undo) > getattr(d, "seen", 0):
                self.drag_log.append(d)
            if d.sketch is sketch:
                d.seen = len(d._undo)
        self.undo_drag.setVisible(bool(self.drag_log))
        self._show()

    def _undo_drag(self):
        ""
        if self.drag_log:
            d = self.drag_log.pop()
            d.undo()
            d.seen = len(d._undo)
        self.undo_drag.setVisible(bool(self.drag_log))

    def _drop_drags(self):
        for d in getattr(self, "drags", []):
            try:
                d.remove()
            except Exception as _fw_err:
                _fw_log("boundarysurface.py:1079", _fw_err)
        self.drags = []
        self.drag_log = []

    def _close(self):
        self._drop_drags()
        _open["panel"] = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("boundarysurface.py:1089", _fw_err)
        try:
            self.curv.close()
        except Exception as _fw_err:
            _fw_log("boundarysurface.py:1093", _fw_err)
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()

    def accept(self):
        obj = self.obj
        obj.Document.recompute()
        if obj.Shape.isNull() or "Invalid" in obj.State:
            self.note.setText(obj.getStatusString() if "Invalid" in obj.State else
                              "Pick at least two curves for Direction 1.")
            return False
        for o, _ in _items(obj.Direction1) + _items(obj.Direction2):
            if o.TypeId == "Sketcher::SketchObject" and o.ViewObject is not None:
                o.ViewObject.Visibility = False
        if obj.Document.HasPendingTransaction:
            obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        self._drop_drags()
        _open["panel"] = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("boundarysurface.py:1119", _fw_err)
        if doc.HasPendingTransaction:
            doc.abortTransaction()
        doc.recompute()
        Gui.ActiveDocument.resetEdit()
        Gui.Control.closeDialog()
        return True


# --------------------------------------------------------------------------- making
def make(doc=None, first=(), second=(), edit=True):
    """first/second: [(object, "Edge1") or (object, "")]."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    doc.openTransaction("Boundary Surface")
    obj = doc.addObject("Part::FeaturePython", "BoundarySurface")
    BoundarySurface(obj)
    ensure_options(obj)
    obj.TrimDirection1 = obj.TrimDirection2 = False
    if App.GuiUp and obj.ViewObject is not None:
        View(obj.ViewObject)
    obj.Label = naming.next_label(doc, TITLE)
    if first:
        obj.Direction1 = [(o, s or "") for o, s in first]
    if second:
        obj.Direction2 = [(o, s or "") for o, s in second]
    doc.recompute()
    if edit and App.GuiUp:
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
    else:
        doc.commitTransaction()
    return obj


def _preselected():
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        obj = sel.Object
        doc = obj.Document
        for sub in sel.SubElementNames or [""]:
            holder = obj
            for part in sub.split(".")[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    holder = found
            element = sub.split(".")[-1]
            if element.startswith("Edge") or (not element and holder.TypeId == "Sketcher::SketchObject"):
                out.append((holder, element))
    return out


class Command:
    def GetResources(self):
        return {"MenuText": "Boundary Surface", "ToolTip": "A surface through curves in one or two directions.",
                "Pixmap": "Surface_GeomFillSurface"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        make(first=_preselected())


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Boundary Surface command not added (%s)\n" % error)
