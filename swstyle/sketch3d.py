# SPDX-License-Identifier: LGPL-2.1-or-later
""















from . import editobj

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

from . import sketch3dsolve as S

GUI = App.GuiUp
if GUI:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets

TYPE = "FreeWorksSketch3D"        # the proxy's Type, how the add-on knows a 3D sketch
PLANES = ("XY", "YZ", "ZX")
# normal and the two in-plane axes of each sketch plane
PLANE_AXES = {"XY": ((0, 0, 1), ((1, 0, 0), (0, 1, 0))),
              "YZ": ((1, 0, 0), ((0, 1, 0), (0, 0, 1))),
              "ZX": ((0, 1, 0), ((0, 0, 1), (1, 0, 0)))}
AXIS_RELATION = {(1, 0, 0): "AlongX", (0, 1, 0): "AlongY", (0, 0, 1): "AlongZ"}
SNAP_PX = 8.0                     # pick and snap distance in logical pixels
VIEW_GROUP = "User parameter:BaseApp/Preferences/View"


# =================================================================== the object
def is_sketch3d(obj):
    return obj is not None and getattr(getattr(obj, "Proxy", None), "Type", None) == TYPE


def load(obj):
    pts = [(v.x, v.y, v.z) for v in obj.Points]
    ents = [e for e in (S.Entity.parse(t) for t in obj.Entities) if e is not None]
    rels = [r for r in (S.Relation.parse(t) for t in obj.Relations) if r is not None]
    return pts, ents, rels


def store(obj, pts, ents, rels):
    obj.Points = [App.Vector(*p) for p in pts]
    obj.Entities = [e.text() for e in ents]
    obj.Relations = [r.text() for r in rels]
    refs = []
    for r in rels:
        if r.kind in S.MODEL and r.ref and r.ref[0]:
            o = obj.Document.getObject(r.ref[0])
            if o is not None and o not in refs and o is not obj:
                refs.append(o)
    if list(obj.References) != refs:
        obj.References = refs


_ELEMENT = ("Vertex", "Edge", "Face")


def follow_refs(obj):
    """The model elements the relations name as text (AtRef Pad Vertex6, OnEdge Pad Edge7, ...)
    follow the part: an edit before the referenced feature renumbers its elements, and the text
    would then name another corner or edge (elementrefs: a hidden link FreeCAD renames). True
    when a relation's text changed."""
    from . import elementrefs
    doc = obj.Document

    def split(el):
        base, sep, tail = str(el).partition("#")
        return base, sep + tail

    def named():
        out = []
        for t in obj.Relations:
            r = S.Relation.parse(t)
            if r is None or r.ref is None or not r.ref[0]:
                continue
            base, _tail = split(r.ref[1])
            if base.startswith(_ELEMENT) and base.lstrip("VertxEdgFac").isdigit():
                out.append((doc.getObject(r.ref[0]), base))
        return out

    def apply(moved):
        rows = []
        for t in obj.Relations:
            r = S.Relation.parse(t)
            if r is not None and r.ref is not None and r.ref[0]:
                base, tail = split(r.ref[1])
                new = moved.get((r.ref[0], base))
                if new:
                    r.ref = (r.ref[0], new + tail)
                    t = r.text()
            rows.append(t)
        obj.Relations = rows

    return elementrefs.follow(obj, named, apply)


def ref_point(doc, rel):
    """Where an AtRef relation's model corner is now, else None (the corner is gone)."""
    name, element = rel.ref or ("", "")
    if element == "Origin":
        return (0.0, 0.0, 0.0)
    o = doc.getObject(name) if name else None
    if o is None or not hasattr(o, "Shape"):
        return None
    try:
        if element.endswith("#Mid"):

            e = o.Shape.getElement(element[:-4])
            p = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
            return (p.x, p.y, p.z)
        v = o.Shape.getElement(element)
        # a vertex, or a circular edge's centre (a converted circle or arc)
        p = v.Curve.Center if element.startswith("Edge") else v.Point
        return (p.x, p.y, p.z)
    except Exception:
        return None


def plane_of(doc, name, element):
    """(base, normal) of a datum plane (element "-" or "") or a flat face, in model coordinates, else None."""
    o = doc.getObject(name) if name else None
    if o is None:
        return None
    try:
        if element and element != "-":
            face = o.Shape.getElement(element)
            surf = face.Surface
            if type(surf).__name__ != "Plane":
                return None
            b, n = surf.Position, surf.Axis
            if face.Orientation == "Reversed":
                n = n * -1
            return (b.x, b.y, b.z), (n.x, n.y, n.z)
        pl = o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else o.Placement
        n = pl.Rotation.multVec(App.Vector(0, 0, 1))
        b = pl.Base
        return (b.x, b.y, b.z), (n.x, n.y, n.z)
    except Exception as _fw_err:
        _fw_log("sketch3d.py:122", _fw_err)
        return None


def is_plane_pick(obj, sub):
    """A datum plane (Front/Top/Right, a reference plane) or a flat face."""
    if obj is None:
        return False
    if not sub:
        return obj.isDerivedFrom("App::Plane") or obj.isDerivedFrom("PartDesign::Plane") \
            or obj.isDerivedFrom("Part::Datum") and "Plane" in obj.TypeId
    return sub.startswith("Face") and plane_of(obj.Document, obj.Name, sub) is not None


def ref_residual(doc, rel):
    """What the solver needs of the model for a relation to it: a point (AtRef), or a function from a
    sketch point to the relation's equations (On Plane, On Surface, On Edge); None when it is gone."""
    name, element = rel.ref or ("", "")
    if rel.kind == "AtRef":
        return ref_point(doc, rel)
    if rel.kind in ("SymPlane", "PlaneParallel", "PlaneNormal", "ParallelYZ", "ParallelZX", "PlaneAngle"):
        return plane_of(doc, name, element)
    if rel.kind in ("OnPlane", "PlaneDistance"):
        pl = plane_of(doc, name, element)
        if pl is None:
            return None
        b, n = pl

        def on_plane(q, b=b, n=n):
            return [(q[0] - b[0]) * n[0] + (q[1] - b[1]) * n[1] + (q[2] - b[2]) * n[2]]
        return on_plane
    o = doc.getObject(name) if name else None
    if o is None or not hasattr(o, "Shape"):
        return None
    try:
        shape = o.Shape.getElement(element)
    except Exception:
        return None
    if rel.kind == "OnSurface":
        surf = shape.Surface

        def on_surface(q, surf=surf):
            v = App.Vector(float(q[0]), float(q[1]), float(q[2]))
            u, w = surf.parameter(v)
            f = surf.value(u, w)
            n = surf.normal(u, w)
            return [(v - f).dot(n)]
        return on_surface
    if rel.kind == "OnEdge":
        curve, first, last = shape.Curve, shape.FirstParameter, shape.LastParameter

        def on_edge(q, curve=curve, first=first, last=last):
            v = App.Vector(float(q[0]), float(q[1]), float(q[2]))
            t = min(max(curve.parameter(v), first), last)
            f = curve.value(t)
            return [v.x - f.x, v.y - f.y, v.z - f.z]
        return on_edge
    return None


def model_relation(doc, kind, point, obj_name, element):
    """An On Plane / On Surface / On Edge relation of a sketch point to the model (On Plane keeps the
    plane's base point and normal for when the plane is gone)."""
    values = []
    if kind == "OnPlane":
        pl = plane_of(doc, obj_name, element)
        if pl is not None:
            values = list(pl[0]) + list(pl[1])
    return S.Relation(kind, [point], values, (obj_name, element or "-"))


def _refs(doc, rels):
    out = {}
    for i, r in enumerate(rels):
        if r.kind == "CurveLength":
            def length(idx, X, rels=rels):
                # a spline's length as FreeCAD builds it, its Tangent ends included
                pts = S.unflat(X)
                ent = S.Entity("S", list(idx))
                try:
                    return spline_edge([pts[k] for k in idx], False, spline_tangents(ent, pts, rels),
                                       spline_handles(ent, rels), spline_continuity(ent, rels)).Length
                except Exception:
                    return spline_length([pts[k] for k in idx])
            out[i] = (length, length)
            continue
        if r.kind in S.MODEL:
            got = ref_residual(doc, r)
            if got is None and r.kind == "AtRef":
                got = tuple(r.values)
            if got is not None:
                out[i] = got
    return out


def solve(doc, pts, rels, extra=()):
    """(points, every relation holds) with the extra relations held too (a drag's target)."""
    allrels = list(rels) + list(extra)
    X, ok = S.Solver(len(pts), allrels, _refs(doc, allrels)).solve(S.flat(pts))
    return S.unflat(X), ok


def freedom(doc, pts, rels):
    return S.Solver(len(pts), rels, _refs(doc, rels)).freedom(S.flat(pts))


def spline_edge(points, closed=False, tangents=(None, None), handles=None, continuity=True):
    ""




    import Part
    vecs = [App.Vector(*p) for p in points]
    if closed and len(vecs) > 2 and vecs[0].distanceToPoint(vecs[-1]) < 1e-9:
        vecs = vecs[:-1]
    c = Part.BSplineCurve()
    t0, t1 = tangents
    if not closed and (t0 is not None or t1 is not None) and len(vecs) >= 2:
        # FreeCAD needs both ends' tangents: a free end takes the natural one of the plain spline
        plain = Part.BSplineCurve()
        plain.interpolate(vecs)
        t0 = App.Vector(*t0) if t0 is not None else plain.tangent(plain.FirstParameter)[0]
        t1 = App.Vector(*t1) if t1 is not None else plain.tangent(plain.LastParameter)[0]
        c.interpolate(Points=vecs, InitialTangent=t0, FinalTangent=t1)
    else:
        c.interpolate(vecs, PeriodicFlag=bool(closed))
    handles = {k: h for k, h in (handles or {}).items() if 0 <= k < len(vecs)}
    if handles and len(vecs) >= 2:
        try:
            return hermite_spline(vecs, closed, c, handles, continuity).toShape()
        except Exception as _fw_err:
            _fw_log("sketch3d.py:252", _fw_err)
    return c.toShape()


def _c2_tangents():
    """fwsketch.splineedit.c2_tangents when it takes 3D points (spline-land05), else None."""
    try:
        from .fwsketch import splineedit
        f = splineedit.c2_tangents
        got = f([(0, 0, 0), (1, 0, 0), (2, 1, 0)], [0.0, 1.0, 2.4], [(1, 0, 0)] * 3, [(1, 0, 0)] * 3, [1])
        return f if got and len(got[1]) == 3 else None
    except Exception:
        return None


def hermite_spline(vecs, closed, natural, handles, continuity=True):
    ""




    import Part
    n = len(vecs)
    spans = n if closed else n - 1
    knots = [0.0]
    for i in range(spans):
        knots.append(knots[-1] + max(vecs[i].distanceToPoint(vecs[(i + 1) % n]), 1e-9))
    t_out, t_in = [], []
    for i, v in enumerate(vecs):
        if i in handles:
            d, w = handles[i][:2]
            w2 = handles[i][2] if len(handles[i]) > 2 else w
            d = App.Vector(*d)
        else:
            d, w = natural.tangent(natural.parameter(v))[0], 1.0
            w2 = w
        if d.Length < 1e-12:
            d = App.Vector(1, 0, 0)
        d = App.Vector(d).normalize()
        t_out.append(d * float(w))
        t_in.append(d * float(w2))
    free = [i for i in range(n) if i not in handles]
    solve = _c2_tangents() if continuity and free else None
    if solve is not None:
        got = solve([(v.x, v.y, v.z) for v in vecs], knots, [(v.x, v.y, v.z) for v in t_in],
                    [(v.x, v.y, v.z) for v in t_out], free, bool(closed))
        for i, m in (got or {}).items():
            m = App.Vector(*m)
            if m.Length > 1e-12:
                t_out[i] = t_in[i] = m
    inner = []                # each span's two inner poles
    for i in range(spans):
        j = (i + 1) % n
        h = knots[i + 1] - knots[i]
        inner.append((vecs[i] + t_out[i] * (h / 3.0), vecs[j] - t_in[j] * (h / 3.0)))
    # a point whose two weights differ: knot multiplicity 3 and the point itself a pole between its two inner
    # poles, so the curve still goes through it (G1 there), as the 2D spline's (splineedit.hermite)
    triple = [(t_in[i] - t_out[i]).Length > 1e-9 * max(1.0, t_out[i].Length) for i in range(n)]
    c = Part.BSplineCurve()
    if closed:
        poles, mults = [], []
        for i in range(n):
            poles.append(inner[i - 1][1])
            if triple[i]:
                poles.append(vecs[i])
            poles.append(inner[i][0])
            mults.append(3 if triple[i] else 2)
        mults.append(mults[0])
        rot = 1 if triple[0] else 0    # OCC's periodic poles start at the first knot's own pole when it has one
        poles = poles[rot:] + poles[:rot]
        c.buildFromPolesMultsKnots(poles=poles, mults=mults, knots=knots, periodic=True, degree=3)
        return c
    poles, mults = [vecs[0]], [4]
    for i in range(spans):
        poles.extend(inner[i])
        j = i + 1
        if j < n - 1:
            if triple[j]:
                poles.append(vecs[j])
            mults.append(3 if triple[j] else 2)
    poles.append(vecs[-1])
    mults.append(4)
    c.buildFromPolesMultsKnots(poles=poles, mults=mults, knots=knots, periodic=False, degree=3)
    return c


def spline_style(ent, rels):
    ""
    a, b = ent.points[0], ent.points[-1]
    return any(r.kind in ("SplineStyle", "SplineGeneric") and r.points == [a, b] for r in rels)


def spline_generic(ent, rels):
    """Convert to Generic Spline's spline: ent's points are the poles of a clamped uniform cubic B-spline."""
    a, b = ent.points[0], ent.points[-1]
    return any(r.kind == "SplineGeneric" and r.points == [a, b] for r in rels)


def generic_knots(n, degree=3):
    """(knots, multiplicities) of a clamped uniform B-spline with n poles."""
    d = min(degree, n - 1)
    spans = n - d
    knots = [i / float(spans) for i in range(spans + 1)]
    mults = [d + 1] + [1] * (spans - 1) + [d + 1]
    return knots, mults, d


def style_edge(points, generic=False):
    """The Style Spline over the control vertices: one Bezier span (degree points - 1, at most 25 points);
    generic: a clamped uniform cubic B-spline over them."""
    import Part
    if generic:
        knots, mults, d = generic_knots(len(points))
        c = Part.BSplineCurve()
        c.buildFromPolesMultsKnots([App.Vector(*p) for p in points], mults, knots, False, d)
        return c.toShape()
    c = Part.BezierCurve()
    c.setPoles([App.Vector(*p) for p in points[:25]])
    return c.toShape()


def _basis(knots, mults, d, u):
    """The B-spline basis values at u (clamped knots), one per pole (Cox-de Boor)."""
    full = []
    for k, m in zip(knots, mults):
        full += [k] * m
    n = len(full) - d - 1
    if u >= full[-1]:
        out = [0.0] * n
        out[-1] = 1.0
        return out
    N = [1.0 if full[i] <= u < full[i + 1] else 0.0 for i in range(len(full) - 1)]
    for p in range(1, d + 1):
        nxt = []
        for i in range(len(full) - p - 1):
            a = full[i + p] - full[i]
            b = full[i + p + 1] - full[i + 1]
            v = 0.0
            if a > 0:
                v += (u - full[i]) / a * N[i]
            if b > 0:
                v += (full[i + p + 1] - u) / b * N[i + 1]
            nxt.append(v)
        N = nxt
    return N[:n]


def spline_continuity(ent, rels):
    ""
    a, b = ent.points[0], ent.points[-1]
    return not any(r.kind == "SplineLoose" and r.points == [a, b] for r in rels)


def spline_handles(ent, rels):
    """{position in ent.points: (direction, weight, back weight)} of spline ent's tangent handles (SplineHandle)."""
    out = {}
    p = list(ent.points)
    closed = len(p) > 3 and p[0] == p[-1]
    if closed:
        p = p[:-1]
    for r in rels:
        if r.kind != "SplineHandle" or len(r.values) < 4:
            continue
        a, b = r.points[:2]
        for k, i in enumerate(p):
            if i != a:
                continue
            near = [p[(k + 1) % len(p)], p[k - 1]] if closed else p[k + 1:k + 2] + p[max(0, k - 1):k]
            if b in near:
                out[k] = (tuple(r.values[:3]), r.values[3], r.values[4] if len(r.values) > 4 else r.values[3])
    return out


def spline_tangents(ent, pts, rels):
    """(first, last) tangent directions of spline ent from its Tangent relations, else None each."""
    out = [None, None]
    p = ent.points
    if len(p) < 2 or (len(p) > 3 and p[0] == p[-1]):
        return tuple(out)
    for r in rels:
        if r.kind not in ("SplineTangent", "SplineTangentArc", "SplineTangentSpline"):
            continue
        e, n = r.points[0], r.points[1]
        end = 0 if (e, n) == (p[0], p[1]) else (1 if (e, n) == (p[-1], p[-2]) else None)
        if end is None:
            continue
        if r.kind == "SplineTangent":
            d = _sub(pts[r.points[3]], pts[r.points[2]])
        elif r.kind == "SplineTangentSpline":
            # the other spline as it is built without spline-to-spline ties (no loop between the two)
            other = r.points[2:]
            if len(other) < 2 or e not in (other[0], other[-1]):
                continue
            own = [x for x in rels if x.kind != "SplineTangentSpline"]
            try:
                edge = spline_edge([pts[i] for i in other], False,
                                   spline_tangents(S.Entity("S", other), pts, own),
                                   spline_handles(S.Entity("S", other), own),
                                   spline_continuity(S.Entity("S", other), own))
                c = edge.Curve
                t = c.tangent(c.FirstParameter if e == other[0] else c.LastParameter)[0]
                d = (t.x, t.y, t.z)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:457", _fw_err)
                continue
        else:
            d = _cross(tuple(r.values[:3]), _sub(pts[e], pts[r.points[2]]))
        if _len(d) < 1e-12:
            continue
        way = _sub(pts[n], pts[e]) if end == 0 else _sub(pts[e], pts[n])
        if _dot(d, way) < 0:
            d = _mul(d, -1.0)
        out[end] = d
    return tuple(out)


def spline_length(points):
    """Length of the spline through the points (Equal Curve Length)."""
    try:
        return spline_edge(points).Length
    except Exception:
        return sum(_len(_sub(points[i + 1], points[i])) for i in range(len(points) - 1))


def arc_normal(ent, rels):
    """The plane normal a circle or arc was drawn on (its ArcPlane relation)."""
    want = ent.points[:2] + ([ent.points[2]] if ent.kind == "A" else [ent.points[1]])
    for r in rels:
        if r.kind == "ArcPlane" and r.points == want:
            return tuple(r.values[:3])
    return (0.0, 0.0, 1.0)


def arc_frame(c, a, n):
    """(radius, u, v): u from the centre to a, v = n x u, both unit."""
    d = _sub(a, c)
    d = _sub(d, _mul(n, _dot(d, n)))
    r = _len(d)
    if r < 1e-12:
        return 0.0, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    u = _mul(d, 1.0 / r)
    v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
    return r, u, v


def arc_sweep(c, a, b, n):
    """The counterclockwise angle about n from a to b (0 < sweep <= 2 pi)."""
    r, u, v = arc_frame(c, a, n)
    d = _sub(b, c)
    t = math.atan2(_dot(d, v), _dot(d, u)) % (2 * math.pi)
    return t if t > 1e-9 else 2 * math.pi


def arc_points(c, a, b, n, full=False, count=64):
    r, u, v = arc_frame(c, a, n)
    sweep = 2 * math.pi if full else arc_sweep(c, a, b, n)
    k = max(8, int(count * sweep / (2 * math.pi)))
    return [_add(c, _add(_mul(u, r * math.cos(sweep * i / k)), _mul(v, r * math.sin(sweep * i / k))))
            for i in range(k + 1)]


def circumcentre(a, b, m, n):
    """(centre, normal) of the arc from a to b through m on the plane of normal n (m and b are put on
    the plane through a), the normal turned so the arc goes counterclockwise about it; else None."""
    m = _sub(m, _mul(n, _dot(_sub(m, a), n)))
    b = _sub(b, _mul(n, _dot(_sub(b, a), n)))
    p, q = _sub(a, m), _sub(b, m)
    cr = (p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0])
    l2 = _dot(cr, cr)
    if l2 < 1e-12 * max(1.0, _dot(p, p) * _dot(q, q)):
        return None
    w = _sub(_mul(q, _dot(p, p)), _mul(p, _dot(q, q)))
    num = (w[1] * cr[2] - w[2] * cr[1], w[2] * cr[0] - w[0] * cr[2], w[0] * cr[1] - w[1] * cr[0])
    c = _add(m, _mul(num, 1.0 / (2.0 * l2)))
    if arc_sweep(c, a, m, n) > arc_sweep(c, a, b, n):
        n = _mul(n, -1.0)
    return c, n


def _model_face(name, element):
    """The face element of object name, in whichever open document has it."""
    docs = ([App.ActiveDocument] if App.ActiveDocument is not None else []) + list(App.listDocuments().values())
    for d in docs:
        o = d.getObject(name) if d is not None else None
        if o is not None and hasattr(o, "Shape"):
            try:
                return o.Shape.getElement(element)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:542", _fw_err)
                return None
    return None


def surface_spline_edge(points, ref, closed=False):
    ""

    import Part
    face = _model_face(*ref)
    if face is None or len(points) < 2:
        return None
    surf = face.Surface
    uv = []
    for p in points:
        u, v = surf.parameter(App.Vector(*p))
        uv.append(App.Base.Vector2d(u, v))
    if closed and len(uv) > 2 and (uv[0] - uv[-1]).Length < 1e-9:
        uv = uv[:-1]
    c = Part.Geom2d.BSplineCurve2d()
    c.interpolate(uv, PeriodicFlag=bool(closed))
    return c.toShape(surf)


def spline_surface(ent, rels):
    """(object, face) a spline lies on (its SplineOnSurface), else None."""
    p = ent.points
    for r in rels:
        if r.kind == "SplineOnSurface" and r.points[:2] == list(p[:2]) and r.ref:
            return tuple(r.ref)
    return None


def offset_on_surface(face, edge, distance, geodesic=True, side=1.0, samples=16, steps=12):
    ""


    surf = face.Surface
    out = []
    a, b = edge.FirstParameter, edge.LastParameter
    for k in range(samples + 1):
        t = a + (b - a) * k / samples
        p = edge.valueAt(t)
        tan = edge.tangentAt(t)
        start = App.Vector(p)
        q = App.Vector(p)
        walked = 0.0
        step = distance / steps
        for _ in range(steps * 4):
            u, v = surf.parameter(q)
            n = face.normalAt(u, v)
            d = n.cross(tan)
            if d.Length < 1e-12:
                break
            d.normalize()
            nxt = q + d * (step * side)
            u, v = surf.parameter(nxt)
            nxt = surf.value(u, v)
            if geodesic:
                walked += (nxt - q).Length
                q = nxt
                if walked >= distance - 1e-9:
                    break
            else:
                q = nxt
                if (q - start).Length >= distance - 1e-9:
                    break
        out.append((q.x, q.y, q.z))
    return out


def entity_edges(ent, pts, rels=()):
    import Part
    if ent.kind in ("C", "A"):
        n = arc_normal(ent, rels)
        c, a = pts[ent.points[0]], pts[ent.points[1]]
        r, u, v = arc_frame(c, a, n)
        if r < 1e-9:
            return []
        circle = Part.Circle(App.Vector(*c), App.Vector(*n), r)
        if ent.kind == "C":
            return [circle.toShape()]
        u1 = circle.parameter(App.Vector(*a))
        u2 = u1 + arc_sweep(c, a, pts[ent.points[2]], n)
        return [Part.ArcOfCircle(circle, u1, u2).toShape()]
    if ent.kind == "L":
        a, b = App.Vector(*pts[ent.points[0]]), App.Vector(*pts[ent.points[1]])
        if a.distanceToPoint(b) < 1e-9:
            return []
        return [Part.LineSegment(a, b).toShape()]
    if ent.kind == "S" and len(ent.points) >= 2:
        closed = len(ent.points) > 3 and ent.points[0] == ent.points[-1]
        on = spline_surface(ent, rels)
        if len(ent.points) == 2 and on is None:
            return entity_edges(S.Entity("L", ent.points), pts)
        if spline_style(ent, rels):
            try:
                return [style_edge([pts[i] for i in ent.points], spline_generic(ent, rels))]
            except Exception as _fw_err:
                _fw_log("sketch3d.py:641", _fw_err)
                return []
        if on is not None:
            try:
                e = surface_spline_edge([pts[i] for i in ent.points], on, closed)
                if e is not None:
                    return [e]
            except Exception as _fw_err:
                _fw_log("sketch3d.py:644", _fw_err)
        try:
            return [spline_edge([pts[i] for i in ent.points], closed, spline_tangents(ent, pts, rels),
                                spline_handles(ent, rels), spline_continuity(ent, rels))]
        except Exception as _fw_err:
            _fw_log("sketch3d.py:654", _fw_err)
            return []
    return []


class Sketch3D:
    """Proxy of a 3D sketch (Part::Part2DObjectPython)."""

    Type = TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self.add_properties(obj)

    def add_properties(self, obj):
        have = obj.PropertiesList
        if "Points" not in have:
            obj.addProperty("App::PropertyVectorList", "Points", "3D Sketch", "The sketch's points")
        if "Entities" not in have:
            obj.addProperty("App::PropertyStringList", "Entities", "3D Sketch", "Lines, splines and points")
        if "Relations" not in have:
            obj.addProperty("App::PropertyStringList", "Relations", "3D Sketch", "Relations and dimensions")
        if "References" not in have:
            obj.addProperty("App::PropertyLinkList", "References", "3D Sketch", "Model objects the sketch touches")
        if "SketchState" not in have:
            obj.addProperty("App::PropertyString", "SketchState", "3D Sketch", "Under Defined, Fully Defined...")
        for name in ("Points", "Entities", "Relations", "References", "SketchState"):
            obj.setEditorMode(name, 1 if name == "SketchState" else 2)
        for name in ("MapMode", "AttachmentSupport", "MapReversed", "MapPathParameter", "AttachmentOffset",
                     "AttacherEngine", "AttacherType"):
            if name in obj.PropertiesList:
                try:
                    obj.setEditorMode(name, 2)
                except Exception as _fw_err:
                    _fw_log("sketch3d.py:682", _fw_err)

    def onDocumentRestored(self, obj):
        self.add_properties(obj)

    def execute(self, obj):
        import Part
        follow_refs(obj)
        pts, ents, rels = load(obj)
        if any(r.kind in S.MODEL for r in rels):
            # the model moved under a corner the sketch is on: follow it
            new, ok = solve(obj.Document, pts, rels)
            if ok and any(abs(a - b) > 1e-9 for p, q in zip(pts, new) for a, b in zip(p, q)):
                obj.Points = [App.Vector(*p) for p in new]
                pts = new
        edges, verts = [], []
        for e in ents:
            if e.construction:
                continue
            if e.kind == "P":
                verts.append(Part.Vertex(App.Vector(*pts[e.points[0]])))
            else:
                edges += entity_edges(e, pts, rels)
        shape = Part.Shape()
        if edges or verts:
            # connected lines and splines as wires (a Sweep path, a Structural Member's segments)
            try:
                parts = [Part.Wire(group) for group in Part.sortEdges(edges)] if edges else []
            except Exception:
                parts = list(edges)
            parts += verts
            shape = parts[0] if len(parts) == 1 else Part.Compound(parts)
        obj.Shape = shape
        try:
            dof, _ = freedom(obj.Document, pts, rels)
            obj.SketchState = "Fully Defined" if dof == 0 and pts else "Under Defined"
        except Exception as _fw_err:
            _fw_log("sketch3d.py:718", _fw_err)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(doc, body=None):
    from . import naming
    obj = doc.addObject("Part::Part2DObjectPython", "Sketch3D")
    Sketch3D(obj)
    if GUI:
        ViewProvider3D(obj.ViewObject)
    obj.Label = naming.next_label(doc, "3DSketch")
    if body is not None:
        try:
            body.addObject(obj)
        except Exception as _fw_err:
            _fw_log("sketch3d.py:738", _fw_err)
            from . import fwtell
            fwtell.tell("The 3D sketch was made, but it could not be added to the body.", _fw_err)
    return obj


# =================================================================== colours
def _packed(name, default):
    try:
        packed = App.ParamGet(VIEW_GROUP).GetUnsigned(name, 0)
    except Exception:
        packed = 0
    if not packed:
        return default
    return ((packed >> 24) & 0xFF) / 255.0, ((packed >> 16) & 0xFF) / 255.0, ((packed >> 8) & 0xFF) / 255.0


def colours():
    ""

    return {"under": _packed("EditedEdgeColor", (0.0, 0.0, 1.0)),
            "full": _packed("FullyConstrainedColor", (0.0, 0.0, 0.0)),
            "construction": _packed("ConstructionColor", (0.6, 0.6, 0.6)),
            "selected": (0.1, 0.72, 1.0),
            "hover": (1.0, 0.5, 0.0),
            "conflict": _packed("OverDefinedColor", (0.84, 0.89, 0.05)),
            "relation": (0.12, 0.55, 0.15),
            "dimension": _packed("ConstrainedDimColor", (0.0, 0.0, 0.0)),
            "guide": _packed("SnapGuideRelationColor", (0.41, 0.37, 0.89)),
            "preview": _packed("CreateLineColor", (0.9, 0.9, 0.9)),
            "text": _packed("CursorTextColor", (0.0, 0.0, 1.0))}


# =================================================================== view provider
if GUI:
    def _icon():
        try:
            from . import icons
            icon = icons.family("SKETCH_3D_SKETCH")
            if icon is not None and not icon.isNull():
                return icon
        except Exception as _fw_err:
            _fw_log("sketch3d.py:778", _fw_err)
        return ":/icons/Sketcher_Sketch.svg"

    class ViewProvider3D:
        def __init__(self, vobj):
            vobj.Proxy = self

        def attach(self, vobj):
            self.Object = vobj.Object
            try:
                vobj.LineWidth = 2.0
                vobj.PointSize = 5.0
                c = colours()["full"]
                vobj.LineColor = c
                vobj.PointColor = c
            except Exception as _fw_err:
                _fw_log("sketch3d.py:794", _fw_err)

        def getIcon(self):
            return _icon()        # a QIcon or a path, never a QPixmap (Windows crash)

        def setEdit(self, vobj, mode=0):
            if mode != 0:
                return None
            start_session(vobj.Object)
            return True

        def unsetEdit(self, vobj, mode=0):
            if mode != 0:
                return None
            end_session(vobj.Object)
            return True

        def doubleClicked(self, vobj):
            Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
            return True

        def setupContextMenu(self, vobj, menu):
            action = menu.addAction(_icon() if not isinstance(_icon(), str) else QtGui.QIcon(_icon()),
                                    "Edit 3D Sketch")
            action.triggered.connect(lambda: Gui.ActiveDocument.setEdit(vobj.Object.Name, 0))

        def updateData(self, obj, prop):
            s = _session
            if s is not None and s.obj is obj and prop in ("Points", "Entities", "Relations"):
                s.data_changed()

        def onChanged(self, vobj, prop):
            pass

        def dumps(self):
            return None

        def loads(self, state):
            return None


# =================================================================== editing session
_session = None


def editing():
    """The 3D sketch being edited, or None."""
    return _session.obj if _session is not None else None


def session():
    return _session


def start_session(obj):
    global _session
    if _session is not None:
        if _session.obj is obj:
            return _session
        _session.stop()
    _session = Session(obj)
    _session.start()
    return _session


def end_session(obj=None):
    global _session
    s = _session
    if s is None or (obj is not None and s.obj is not obj):
        return
    _session = None
    s.stop()


def _axis_along(d, axes):
    """AlongX/Y/Z when direction d follows one of the world axes among axes, else None."""
    n = math.sqrt(sum(c * c for c in d))
    if n < 1e-9:
        return None
    for u in axes:
        key = tuple(int(round(c)) for c in u)
        rel = AXIS_RELATION.get(key) or AXIS_RELATION.get(tuple(-c for c in key))
        if rel is None or any(abs(c - k) > 1e-9 for c, k in zip(u, key)):
            continue
        cross = (d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2], d[0] * u[1] - d[1] * u[0])
        if math.sqrt(sum(c * c for c in cross)) <= 1e-6 * n:
            return rel
    return None


def _vec(t):
    return App.Vector(float(t[0]), float(t[1]), float(t[2]))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _len(a):
    return math.sqrt(_dot(a, a))


class Snap:
    """Where a click lands and what it touches: an existing point (index), a relation to add for
    the new point, an axis it follows from the previous point."""
    __slots__ = ("pos", "point", "relation", "label", "axis", "guide", "free", "align")

    def __init__(self, pos, point=None, relation=None, label="", axis=None, guide=None, free=False):
        self.free = free              # placed on the sketch plane, touching nothing
        self.pos = tuple(pos)
        self.point = point            # index of a sketch point it lands on
        self.relation = relation      # ("OnLine", a, b) / ("Midpoint", a, b) / ("AtRef", obj, element)
        self.label = label            # what the pointer glyph says
        self.axis = axis              # "AlongX"... from the previous point
        self.guide = guide            # (from, to) dotted inference line
        self.align = None             # (from, to) dotted line from a sketch point it lines up with


class _ModelPicks:
    """Model picks (Ctrl+click a plane or face next to sketch items) change what Add Relations offers."""

    def __init__(self, session):
        self.s = session
        self._queued = False

    def _soon(self, *args):
        if self._queued or not self.s.selection:
            return
        self._queued = True

        def run():
            self._queued = False
            if _session is self.s:
                self.s._selection_changed()
        QtCore.QTimer.singleShot(0, run)

    addSelection = removeSelection = setSelection = clearSelection = _soon


if GUI:
    class Session(QtCore.QObject):
        """One 3D sketch in edit: its drawing, picks, drags, keys and the running tool."""

        def __init__(self, obj):
            super().__init__()
            self.obj = obj
            self.doc = obj.Document
            self.plane = "XY"
            self.custom = None        # 3D Sketch On Plane: {"name", "base", "n", "u", "v", "ref"}
            self.tool = None
            self.selection = []       # ("P", i) / ("E", i) / ("R", i), in pick order
            self.hover = None
            self.cursor_pos = None    # 3D point of the pointer on the sketch plane (for the handle)
            self._writing = False
            self._drag = None
            self._press = None
            self._held = set()        # keys taken on press, so their release is not FreeCAD's
            self.view = None
            self.root = None
            self.pts, self.ents, self.rels = load(obj)
            self.fixed = set()
            self.state = ""
            self.pm = None
            self.recent = []          # tools used in this edit, newest first (Recent Commands)
            self.show_triad = False   # Show Sketcher Triad (right-click): the triad at the picked entities
            self.show_glyphs = True   # the relation glyphs (View Sketch Relations)
            self.glyph_rows = []      # (where, glyph keys) drawn last, for tests
            self.curvature = set()    # splines showing their curvature comb (Spline > Show curvature)
            self.inflections = set()  # splines showing their inflection points (Spline Tools)
            self.min_radius = set()   # splines showing their minimum radius of curvature (Spline Tools)
            self.handles_off = set()  # splines whose handles Show Spline Handles has switched off
            self.polygon = set()      # splines showing their control polygon (Show Spline Control Polygon)
            self.quick_snap = None    # Quick Snaps: the one snap kind on for the next entity, else None
            self.ink = _load_ink(obj)  # Pen Sketch ink not yet converted: [[(x, y, z), ...], ...]
            self.ink_picked = set()   # ink strokes picked with the Pen's Select
            self.ruler = None         # the Pen's Ruler: (a, b)
            self.fresh_spline = None

        # ------------------------------------------------------------- life
        def start(self):
            gdoc = Gui.getDocument(self.doc.Name)
            self.gdoc = gdoc
            self.view = gdoc.ActiveView
            self.quarter = self.view.graphicsView()
            self.viewport = self.quarter.viewport()
            self.ratio = self.viewport.devicePixelRatioF()
            self._app = QtWidgets.QApplication.instance()
            from pivy import coin
            self.coin = coin
            self.root = coin.SoSeparator()
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            self.root.addChild(pick)
            self.annotation = coin.SoAnnotation()
            self.root.addChild(self.annotation)
            self.layer_geo = coin.SoSeparator()
            self.layer_tool = coin.SoSeparator()
            self.annotation.addChild(self.layer_geo)
            self.annotation.addChild(self.layer_tool)
            self.view.getSceneGraph().addChild(self.root)
            for w in (self.viewport, self.quarter):
                w.installEventFilter(self)
            self._app.installEventFilter(self)
            self._observer = _ModelPicks(self)
            Gui.Selection.addObserver(self._observer)
            self.recount()
            self.redraw()
            _ribbon(True)
            try:
                from . import sketch3dpm
                sketch3dpm.session_started(self)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD 3D Sketch: PropertyManager: %s\n" % error)
            self.status("3D sketch: pick a tool on the Sketch tab. Tab changes the sketch plane (now %s)." % self.plane)

        def stop(self):
            if self.tool is not None:
                self.tool.end()
            try:
                Gui.Selection.removeObserver(self._observer)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:1027", _fw_err)
            for w in (self.viewport, self.quarter, self._app):
                try:
                    w.removeEventFilter(self)
                except Exception as _fw_err:
                    _fw_log("sketch3d.py:1032", _fw_err)
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:1036", _fw_err)
            try:
                from . import sketch3dpm
                sketch3dpm.session_ended(self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:1041", _fw_err)
            _ribbon(False)
            self.status("")
            try:
                self.doc.recompute()
            except Exception as _fw_err:
                _fw_log("sketch3d.py:1047", _fw_err)

        def status(self, text):
            try:
                Gui.getMainWindow().statusBar().showMessage(text)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:1053", _fw_err)

        # ------------------------------------------------------------- data
        def data_changed(self, _again=False):
            if self._writing:
                return
            pts, ents, rels = load(self.obj)
            n = len(pts)
            broken = [e for e in ents if not all(0 <= k < n for k in getattr(e, "points", ()))]
            if broken and _again:
                ents = [e for e in ents if e not in broken]      # still broken a moment later: draw the rest
            elif broken:
                # Undo/Redo restore Points, Entities and Relations one by one: an entity list that names
                # points not there yet is the middle of that; redraw once all three are back (no traceback)
                if not getattr(self, "_data_later", False):
                    self._data_later = True

                    def later():
                        self._data_later = False
                        if _session is self:
                            self.data_changed(True)
                    QtCore.QTimer.singleShot(0, later)
                return
            self.pts, self.ents, self.rels = pts, ents, rels
            self.selection = [s for s in self.selection if
                              (s[0] == "P" and s[1] < n) or (s[0] == "E" and s[1] < len(self.ents))
                              or (s[0] == "R" and s[1] < len(self.rels))]
            self.recount()
            self.redraw()
            self._selection_changed()

        def recount(self):
            if self.plane not in self.planes():
                self.plane = "XY"          # its sketch plane went (deleted, undone)
            try:
                dof, self.fixed = freedom(self.doc, self.pts, self.rels)
                self.state = "Fully Defined" if dof == 0 and self.pts else "Under Defined"
            except Exception:
                self.fixed, self.state = set(), "Under Defined"

        def write(self, name, pts, ents, rels, solve_first=True):
            """One undo step: the new data, solved, written to the object."""
            if solve_first:
                pts, ok = solve(self.doc, pts, rels)
            if self.quick_snap is not None and self.tool is not None:
                self.quick_snap = None
            self.doc.openTransaction(name)
            self._writing = True
            try:
                store(self.obj, pts, ents, rels)
                self.doc.commitTransaction()
            except Exception:
                self.doc.abortTransaction()
                raise
            finally:
                self._writing = False
            try:
                App.closeActiveTransaction()
            except Exception as _fw_err:
                _fw_log("sketch3d.py:1096", _fw_err)
            self.doc.recompute()
            self.pts, self.ents, self.rels = load(self.obj)
            self.recount()
            self.redraw()
            self._selection_changed()

        def entities_of_point(self, i):
            return [k for k, e in enumerate(self.ents) if i in e.points]

        def relations_of(self, item):
            """Indexes of the relations shown for a picked item (the PropertyManager's Existing Relations)."""
            kind, i = item
            if kind == "R":
                return [i]
            out = []
            for k, r in enumerate(self.rels):
                if r.kind in S.INTERNAL + S.SPLINE_OWN:
                    continue
                if kind == "E":
                    if self._relation_on_entity(r, self.ents[i]) or (
                            r.kind in ("Fix",) + S.MODEL[1:] and self.ents[i].kind == "L"
                            and r.points[0] in self.ents[i].points):
                        out.append(k)
                elif i in r.points:
                    if r.kind == "SymPlane" or (r.kind == "OnArc" and r.points[2] == i):
                        out.append(k)
                    elif r.kind in ("Fix", "OnLine", "Midpoint", "OnSketchPlane") + S.MODEL and r.points[0] == i:
                        out.append(k)
                    elif r.kind in S.ALONG + ("Coincident", "Distance") and not any(
                            e.kind == "L" and set(e.points) == set(r.points) for e in self.ents):
                        out.append(k)
            return out

        @staticmethod
        def _relation_on_entity(r, e):
            if r.kind == "CurveLength":
                return set(e.points) <= set(r.points)
            if e.kind == "S" and r.kind in ("SplineTangent", "SplineTangentArc", "SplineTangentSpline"):
                return (r.points[0] in e.points and r.points[1] in e.points) or (
                    r.kind == "SplineTangentSpline" and r.points[2:] == e.points)
            if e.kind in ("C", "A"):
                # a circle's or arc's: its radius, Tangent, Concentric, Coradial, Equal, Midpoint, On Arc
                return e.points[0] in r.points and (e.points[1] in r.points or r.kind in (
                    "Concentric", "ArcMidpoint", "Coincident")) and len(r.points) > 1
            if e.kind != "L":
                return set(r.points) <= set(e.points) and len(r.points) > 1
            a, b = e.points
            if r.kind in S.ALONG or r.kind == "Distance":
                return set(r.points) == {a, b}
            if r.kind in LINE_OWN:
                return set(r.points[:2]) == {a, b}
            if r.kind in ("Tangent", "SplineTangent"):
                return {r.points[2], r.points[3]} == {a, b}
            if r.kind in S.TWO_LINE + ("Angle", "Collinear"):
                return {r.points[0], r.points[1]} == {a, b} or {r.points[2], r.points[3]} == {a, b}
            if r.kind in ("OnLine", "Midpoint"):
                return {r.points[1], r.points[2]} == {a, b}
            return False

        # ------------------------------------------------------------- view maths
        def px(self):
            return SNAP_PX * self.ratio

        def to_screen(self, p):
            try:
                x, y = self.view.getPointOnViewport(_vec(p))
                return float(x), float(y)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:1173", _fw_err)
                return None

        def cursor(self):
            x, y = self.view.getCursorPos()
            return float(x), float(y)

        def ray(self, x, y):
            p = self.view.getPoint(int(x), int(y))
            d = self.view.getViewDirection()
            return (p.x, p.y, p.z), (d.x, d.y, d.z)

        def axes(self, plane=None):
            """(normal, (u, v)) of a sketch plane: XY, YZ, ZX or the plane of 3D Sketch On Plane."""
            name = plane or self.plane
            if self.custom is not None and name == self.custom["name"]:
                c = self.custom
                return c["n"], (c["u"], c["v"])
            k = self.sketch_planes().get(name)
            if k is not None:
                _, n, u, v = sketch_plane_frame(self.pts, self.ents[k])
                return n, (u, v)
            return PLANE_AXES.get(name, PLANE_AXES["XY"])

        def sketch_planes(self):
            ""
            out = {}
            for k, e in enumerate(self.ents):
                if e.kind == "Q":
                    out["Plane%d" % (len(out) + 1)] = k
            return out

        def planes(self):
            return ((self.custom["name"],) if self.custom is not None else ()) + tuple(self.sketch_planes()) + PLANES

        def on_custom(self):
            return self.custom is not None and self.plane == self.custom["name"]

        def on_sketch_plane(self):
            """The entity index of the sketch plane drawn on, else None."""
            return self.sketch_planes().get(self.plane)

        def plane_anchor(self):
            """Where the sketch plane in use goes through when nothing is placed yet."""
            if self.on_custom():
                return self.custom["base"]
            k = self.on_sketch_plane()
            if k is not None:
                return self.pts[self.ents[k].points[0]]
            return (0.0, 0.0, 0.0)

        def leave_plane(self):
            ""

            self.plane = "XY"
            self.status("Sketch plane: XY (Tab changes it)")
            if self.tool is not None:
                self.tool.plane_changed()
            self.redraw()
            try:
                from . import sketch3dpm
                sketch3dpm.plane_changed(self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:1227", _fw_err)

        def activate_plane(self, k):
            """Draw on sketch plane entity k (a double-click on it, or a new plane)."""
            for name, j in self.sketch_planes().items():
                if j == k:
                    self.plane = name
                    self.status("Sketch plane: %s (Tab changes it)" % name)
                    if self.tool is not None:
                        self.tool.plane_changed()
                    self.redraw()
                    try:
                        from . import sketch3dpm
                        sketch3dpm.plane_changed(self)
                    except Exception as _fw_err:
                        _fw_log("sketch3d.py:1242", _fw_err)
                    return True
            return False

        def set_custom_plane(self, obj, sub):
            """Draw on a model plane or flat face (3D Sketch On Plane): it becomes the first sketch plane
            (Tab goes on to XY, YZ, ZX) and points placed on it get On Plane."""
            pl = plane_of(self.doc, obj.Name, sub or "-")
            if pl is None:
                return False
            base, n = pl
            n = _mul(n, 1.0 / max(_len(n), 1e-12))
            # in-plane axes: the model axes the plane holds, else any two at right angles
            cand = [a for a in ((1, 0, 0), (0, 1, 0), (0, 0, 1)) if abs(_dot(a, n)) < 1e-9]
            if len(cand) >= 2:
                u, v = cand[0], cand[1]
            else:
                seed = (1, 0, 0) if abs(n[0]) < 0.9 else (0, 1, 0)
                u = _sub(seed, _mul(n, _dot(seed, n)))
                u = _mul(u, 1.0 / _len(u))
                v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
            label = obj.Label + (" " + sub if sub else "")
            self.custom = {"name": label, "base": base, "n": n, "u": u, "v": v, "ref": (obj.Name, sub or "-")}
            self.plane = label
            return True

        def on_plane(self, x, y, anchor, plane=None):
            n = self.axes(plane)[0]
            if self.custom is not None and (plane or self.plane) == self.custom["name"]:
                anchor = self.custom["base"]      # a model plane stays where it is
            else:
                k = self.sketch_planes().get(plane or self.plane)
                if k is not None:
                    anchor = self.pts[self.ents[k].points[0]]   # so does a sketch plane
            o, d = self.ray(x, y)
            den = _dot(d, n)
            if abs(den) < 1e-9:
                # the plane is seen edge on: the point under the pointer nearest the anchor
                t = _dot(_sub(anchor, o), d) / max(_dot(d, d), 1e-12)
                return _add(o, _mul(d, t))
            t = _dot(_sub(anchor, o), n) / den
            return _add(o, _mul(d, t))

        def world_per_px(self, x, y, anchor):
            a = self.on_plane(x, y, anchor)
            b = self.on_plane(x + 10, y, anchor)
            v = _len(_sub(a, b)) / 10.0
            if v < 1e-12:
                o1, _ = self.ray(x, y)
                o2, _ = self.ray(x + 10, y)
                v = _len(_sub(o1, o2)) / 10.0
            return v

        def _screen_dist(self, p, x, y):
            s = self.to_screen(p)
            if s is None:
                return 1e9
            return math.hypot(s[0] - x, s[1] - y)

        def _seg_dist(self, a, b, x, y):
            """(pixel distance, parameter 0..1) from (x, y) to the screen image of segment a b."""
            sa, sb = self.to_screen(a), self.to_screen(b)
            if sa is None or sb is None:
                return 1e9, 0.0
            dx, dy = sb[0] - sa[0], sb[1] - sa[1]
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 < 1e-9 else max(0.0, min(1.0, ((x - sa[0]) * dx + (y - sa[1]) * dy) / l2))
            return math.hypot(sa[0] + t * dx - x, sa[1] + t * dy - y), t

        def polyline(self, ent):
            """3D points that draw the entity."""
            if ent.kind == "L":
                return [self.pts[ent.points[0]], self.pts[ent.points[1]]]
            if ent.kind in ("C", "A"):
                return arc_points(self.pts[ent.points[0]], self.pts[ent.points[1]],
                                  self.pts[ent.points[-1]], arc_normal(ent, self.rels), full=ent.kind == "C")
            if ent.kind == "S":
                edges = entity_edges(ent, self.pts, self.rels)
                if edges:
                    try:
                        return [(v.x, v.y, v.z) for v in edges[0].discretize(Number=max(24, 12 * len(ent.points)))]
                    except Exception as _fw_err:
                        _fw_log("sketch3d.py:1324", _fw_err)
                return [self.pts[i] for i in ent.points]
            if ent.kind == "Q":
                a, b, c = (self.pts[i] for i in ent.points[:3])
                return [a, b, _sub(_add(b, c), a), c, a]
            return []

        # ------------------------------------------------------------- picking
        def pick(self, x, y, points=True, entities=True, dims=True, exclude_points=()):
            tol = self.px()
            best, best_d = None, tol
            if points:
                for i, p in enumerate(self.pts):
                    if i in exclude_points:
                        continue
                    d = self._screen_dist(p, x, y)
                    if d < best_d:
                        best, best_d = ("P", i), d
                if best is not None:
                    return best
            if dims:
                for k, r in enumerate(self.rels):
                    if r.kind not in S.DIMENSIONS:
                        continue
                    d = self._screen_dist(self.dim_anchor(r), x, y)
                    if d < max(best_d, 1.6 * tol):
                        best, best_d = ("R", k), d
                if best is not None:
                    return best
            if entities:
                for k, e in enumerate(self.ents):
                    line = self.polyline(e)
                    for a, b in zip(line[:-1], line[1:]):
                        d, _ = self._seg_dist(a, b, x, y)
                        if d < best_d:
                            best, best_d = ("E", k), d
            return best

        def plane_foot(self, r):
            """Where a point-to-plane dimension's point meets the plane, square to it."""
            q = self.pts[r.points[0]]
            pl = plane_of(self.doc, r.ref[0], r.ref[1]) if r.ref else None
            b, n = pl if pl is not None else (tuple(r.values[2:5]), tuple(r.values[5:8]))
            n = _mul(n, 1.0 / max(_len(n), 1e-12))
            return _sub(q, _mul(n, _dot(_sub(q, b), n)))

        def dim_anchor(self, r):
            if r.kind == "PlaneDistance":
                return _mul(_add(self.pts[r.points[0]], self.plane_foot(r)), 0.5)
            if r.kind in ("Diameter", "Radius"):
                c, a = self.pts[r.points[0]], self.pts[r.points[1]]
                return _add(a, _mul(_sub(a, c), 0.25)) if r.kind == "Diameter" else _mul(_add(a, c), 0.5)
            if r.kind == "LineDistance":
                q, a, b = (self.pts[i] for i in r.points)
                u = _unit(_sub(b, a))
                foot = _add(a, _mul(u, _dot(_sub(q, a), u)))
                return _mul(_add(q, foot), 0.5)
            if r.kind == "PlaneAngle":
                a, b = self.pts[r.points[0]], self.pts[r.points[1]]
                return _add(a, _mul(_sub(b, a), 0.25))
            if r.kind == "Angle":
                # between the two lines, nearer their shared end when they have one
                a, b, c, d = (self.pts[i] for i in r.points)
                shared = set(r.points[:2]) & set(r.points[2:])
                m1, m2 = _mul(_add(a, b), 0.5), _mul(_add(c, d), 0.5)
                mid = _mul(_add(m1, m2), 0.5)
                if shared:
                    corner = self.pts[shared.pop()]
                    return _add(corner, _mul(_sub(mid, corner), 0.6))
                return mid
            a, b = self.pts[r.points[0]], self.pts[r.points[1]]
            return _mul(_add(a, b), 0.5)

        def snap(self, x, y, anchor, prev=None, exclude_points=(), plain=False):
            """Snap the pointer: sketch points, midpoints and lines, the origin, the model's corners,
            edges and faces, then Along X/Y/Z from prev on the sketch plane. plain (Ctrl): only the plane."""
            tol = self.px()
            model = None
            qs = self.quick_snap
            if not plain:
                hit = self.pick(x, y, points=True, entities=False, dims=False, exclude_points=exclude_points) \
                    if qs in (None, "Point", "CenterPoint") else None
                if hit is not None and qs == "CenterPoint" and not any(
                        e.kind in ("C", "A") and e.points[0] == hit[1] for e in self.ents):
                    hit = None
                if hit is not None:
                    return Snap(self.pts[hit[1]], point=hit[1], label="Coincident")
                if qs in (None, "Point") and self._screen_dist((0, 0, 0), x, y) < tol:
                    return Snap((0, 0, 0), relation=("AtRef", "", "Origin"), label="Coincident")
                for k, e in enumerate(self.ents):
                    if e.kind != "L" or qs not in (None, "Midpoint"):
                        continue
                    a, b = self.pts[e.points[0]], self.pts[e.points[1]]
                    mid = _mul(_add(a, b), 0.5)
                    if self._screen_dist(mid, x, y) < tol:
                        return Snap(mid, relation=("Midpoint", e.points[0], e.points[1]), label="Midpoint")
                model = self.model_snap(x, y) if qs is None else None
                if model is not None and model.relation is not None and model.relation[0] == "AtRef":
                    return model          # a corner of the model
                for k, e in enumerate(self.ents):
                    if e.kind != "L" or qs not in (None, "Nearest"):
                        continue
                    a, b = self.pts[e.points[0]], self.pts[e.points[1]]
                    if e.points[0] in exclude_points and e.points[1] in exclude_points:
                        continue
                    d, t = self._seg_dist(a, b, x, y)
                    if d < tol:
                        return Snap(self._closest_on_line(a, b, x, y), relation=("OnLine", e.points[0], e.points[1]),
                                    label="Coincident")
                for k, e in enumerate(self.ents):
                    if e.kind not in ("C", "A") or e.points[0] in exclude_points or qs not in (None, "Nearest"):
                        continue
                    on = self._on_round(e, x, y, tol)
                    if on is not None:
                        return Snap(on, relation=("OnArc", e.points[0], e.points[1], arc_normal(e, self.rels)),
                                    label="Coincident")
            q = self.on_plane(x, y, anchor)
            if prev is not None and not plain and qs in (None, "HV"):
                best = None
                for j, u in enumerate(self.axes()[1]):
                    rel = AXIS_RELATION.get(tuple(int(round(c)) if abs(abs(c) - round(abs(c))) < 1e-9 else 9
                                                  for c in u))
                    if rel is None:

                        if self.on_sketch_plane() is not None:
                            rel = ("PlaneH", "PlaneV")[j]
                        elif self.on_custom():
                            rel = ("AlongDirH", "AlongDirV")[j]
                        else:
                            continue
                    c = _add(prev, _mul(u, _dot(_sub(q, prev), u)))
                    d = self._screen_dist(c, x, y)
                    if d < tol and _len(_sub(c, prev)) > 1e-9 and (best is None or d < best[0]):
                        best = (d, c, rel)
                if best is not None:
                    _, c, rel = best
                    c, line = self._aligned(c, prev, exclude_points, x, y, tol)
                    sn = Snap(c, label=S.NAMES[rel], axis=rel, guide=(prev, c), free=True)
                    sn.align = line
                    return sn
            if not plain and model is not None:
                return model              # on an edge or a face of the model
            return Snap(q, free=True, label="On Plane" if (self.on_custom() or self.on_sketch_plane() is not None)
                        and not plain else "")

        def _aligned(self, c, prev, exclude_points, x, y, tol):
            ""


            u = _sub(c, prev)
            n = _len(u)
            if n < 1e-9:
                return c, None
            u = _mul(u, 1.0 / n)
            best = None
            for k, p in enumerate(self.pts):
                if k in exclude_points or _len(_sub(p, prev)) < 1e-9:
                    continue
                t = _dot(_sub(p, prev), u)
                if t <= 1e-9:
                    continue
                q = _add(prev, _mul(u, t))
                if _len(_sub(q, p)) < 1e-9:
                    continue          # on the line itself: the point snap has it
                d = self._screen_dist(q, x, y)
                if d < tol and (best is None or d < best[0]):
                    best = (d, q, p)
            if best is None:
                return c, None
            return best[1], (best[2], best[1])

        def _on_round(self, e, x, y, tol):
            """The point of circle or arc e under the pointer (exactly on it), else None."""
            line = self.polyline(e)
            best = None
            for a, b in zip(line[:-1], line[1:]):
                d, _ = self._seg_dist(a, b, x, y)
                if d < tol and (best is None or d < best[0]):
                    best = (d, a, b)
            if best is None:
                return None
            q = self._closest_on_line(best[1], best[2], x, y)
            c, r = self.pts[e.points[0]], _len(_sub(self.pts[e.points[1]], self.pts[e.points[0]]))
            n = arc_normal(e, self.rels)
            w = _sub(q, c)
            w = _sub(w, _mul(n, _dot(w, n)))
            if _len(w) < 1e-12:
                return None
            return _add(c, _mul(w, r / _len(w)))

        def axis_relation(self, kind, a, b):
            """The relation a snap's axis gives the line a b: Along X/Y/Z, or Horizontal/Vertical on a
            sketch plane (following it) or on a slanted model plane."""
            if kind in ("PlaneH", "PlaneV") and self.on_sketch_plane() is not None:
                return S.Relation(kind, [a, b] + self.ents[self.on_sketch_plane()].points[:3])
            if kind in ("AlongDirH", "AlongDirV"):
                return S.Relation(kind, [a, b], list(self.axes()[1][0 if kind == "AlongDirH" else 1]))
            return S.Relation(kind, [a, b])

        def _closest_on_line(self, a, b, x, y):
            """The point of segment a b under the pointer (closest to the view ray)."""
            o, d = self.ray(x, y)
            u = _sub(b, a)
            # closest points between the ray o + s d and the line a + t u
            uu, dd, ud = _dot(u, u), _dot(d, d), _dot(u, d)
            w = _sub(a, o)
            den = uu * dd - ud * ud
            if abs(den) < 1e-12 or uu < 1e-12:
                return a
            t = (ud * _dot(w, d) - dd * _dot(w, u)) / den
            t = max(0.0, min(1.0, t))
            return _add(a, _mul(u, t))

        def _woken_snap(self, x, y):
            ""

            for (name, ename), c in reversed(list(getattr(self, "_woken", {}).items())):
                if self._screen_dist(c, x, y) < self.px():
                    return Snap(c, relation=("AtRef", name, ename), label="Coincident")
            return None

        def _model_edge_snap(self, o, comp, x, y):
            ""

            try:
                sh = o.Shape
                if comp.startswith("Face"):
                    own = sh.getElement(comp).Edges
                elif comp.startswith("Edge"):
                    own = [sh.getElement(comp)]
                else:
                    return None
                if len(sh.Edges) > 2000 or len(own) > 200:
                    return None
                names = []
                for e in own:
                    k = next((i for i, f in enumerate(sh.Edges) if f.isSame(e)), None)
                    if k is not None:
                        names.append(("Edge%d" % (k + 1), sh.Edges[k]))
            except Exception:
                return None
            tol = self.px()
            woken = self.__dict__.setdefault("_woken", {})
            for name, e in names:
                if type(e.Curve).__name__ == "Circle" and (comp.startswith("Edge") or len(own) <= 4):
                    c = e.Curve.Center
                    woken.pop((o.Name, name), None)
                    woken[(o.Name, name)] = (c.x, c.y, c.z)
                    while len(woken) > 6:
                        woken.pop(next(iter(woken)))
            if comp.startswith("Face"):
                for name, e in names:
                    for v in e.Vertexes:
                        q = (v.Point.x, v.Point.y, v.Point.z)
                        if self._screen_dist(q, x, y) < tol:
                            vn = self._vertex_name(sh, v)
                            if vn:
                                return Snap(q, relation=("AtRef", o.Name, vn), label="Coincident")
            got = self._woken_snap(x, y)
            if got is not None:
                return got
            for name, e in names:
                if e.isClosed() or e.Length < 1e-9:
                    continue
                m = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
                q = (m.x, m.y, m.z)
                if self._screen_dist(q, x, y) < tol:
                    return Snap(q, relation=("AtRef", o.Name, name + "#Mid"), label="Midpoint")
            return None

        def model_snap(self, x, y):
            try:
                info = self.view.getObjectInfo((int(x), int(y)))
            except Exception:
                info = None
            if not info or info.get("Object") in (None, self.obj.Name):
                return self._woken_snap(x, y)
            o = self.doc.getObject(info["Object"])
            comp = info.get("Component", "") or ""
            if o is None or not hasattr(o, "Shape"):
                return None
            near = self._model_edge_snap(o, comp, x, y)
            if near is not None:
                return near
            try:
                if comp.startswith("Vertex"):
                    p = o.Shape.getElement(comp).Point
                    return Snap((p.x, p.y, p.z), relation=("AtRef", o.Name, comp), label="Coincident")
                if comp.startswith("Edge"):
                    edge = o.Shape.getElement(comp)
                    for v in edge.Vertexes:
                        if self._screen_dist((v.Point.x, v.Point.y, v.Point.z), x, y) < self.px():
                            name = self._vertex_name(o.Shape, v)
                            if name:
                                return Snap((v.Point.x, v.Point.y, v.Point.z), relation=("AtRef", o.Name, name),
                                            label="Coincident")
                    return Snap((info["x"], info["y"], info["z"]), relation=("OnEdge", o.Name, comp),
                                label="Coincident")
                if comp.startswith("Face"):
                    flat = plane_of(self.doc, o.Name, comp) is not None
                    return Snap((info["x"], info["y"], info["z"]), relation=("OnPlane" if flat else "OnSurface",
                                                                          o.Name, comp),
                                label="On Plane" if flat else "On Surface")
            except Exception:
                return None
            return None

        @staticmethod
        def _vertex_name(shape, v):
            for i, w in enumerate(shape.Vertexes):
                if w.Point.distanceToPoint(v.Point) < 1e-9:
                    return "Vertex%d" % (i + 1)
            return None

        # ------------------------------------------------------------- drawing
        def redraw(self):
            if self.root is None:
                return
            col = colours()
            g = self.layer_geo
            g.removeAllChildren()
            self.glyph_rows = []
            selected = set(self.selection)
            groups = {}
            for k, e in enumerate(self.ents):
                if e.kind in ("P", "Q"):
                    continue
                if ("E", k) in selected:
                    c = col["selected"]
                elif self.hover == ("E", k):
                    c = col["hover"]
                elif e.construction:
                    c = col["construction"]
                elif all(p in self.fixed for p in e.points):
                    c = col["full"]
                else:
                    c = col["under"]
                key = (c, e.construction, ("E", k) in selected or self.hover == ("E", k))
                groups.setdefault(key, []).append(self.polyline(e))
            for (c, construction, lit), lines in groups.items():
                self._lines(g, lines, c, 3.0 if lit else 2.0, 0xF0F0 if construction else 0xFFFF)
            # sketch planes: their outline (dashed, heavier when drawn on) and name at the corner
            for name, k in self.sketch_planes().items():
                e = self.ents[k]
                lit = ("E", k) in selected or self.hover == ("E", k)
                c = col["selected"] if ("E", k) in selected else (col["hover"] if self.hover == ("E", k)
                                                                  else col["relation"])
                self._lines(g, [self.polyline(e)], c, 3.0 if lit or name == self.plane else 1.5, 0xFF00)
                self._text(g, self.pts[e.points[0]], "  " + name, c)
            # points: ends and sketch points
            pgroups = {}
            for i, p in enumerate(self.pts):
                if ("P", i) in selected:
                    c = col["selected"]
                elif self.hover == ("P", i):
                    c = col["hover"]
                elif i in self.fixed:
                    c = col["full"]
                else:
                    c = col["under"]
                pgroups.setdefault(c, []).append(p)
            for c, ps in pgroups.items():
                self._points(g, ps, c, 6.0)
            self._origin_triad(g)
            self._combs(g)
            self._spline_marks(g)
            self._ink_marks(g)
            self._spline_handles(g)
            self._sketcher_triad(g)
            # relation glyphs (a row of squares where relations meet) and dimensions
            rows = {}
            for k, r in enumerate(self.rels):
                if r.kind in S.DIMENSIONS:
                    c = col["selected"] if ("R", k) in selected else (col["hover"] if self.hover == ("R", k)
                                                                      else col["dimension"])
                    text = _fmt_angle(r.values[0]) if r.kind in S.ANGLES else _fmt(r.values[0])
                    text = {"Diameter": "Ø", "Radius": "R"}.get(r.kind, "") + text
                    if r.kind == "PlaneDistance":
                        self._lines(g, [[self.pts[r.points[0]], self.plane_foot(r)]], col["dimension"], 1.0, 0xAAAA)
                    self._text(g, self.dim_anchor(r), text, c, size=13)
                elif r.kind in GLYPHS and self.show_glyphs:
                    for q in glyph_anchors(r, self.pts):
                        key = tuple(round(v, 6) for v in q)
                        rows.setdefault(key, (q, []))[1].append((GLYPHS[r.kind][0], r))
            for q, got in rows.values():
                self._glyphs(g, q, got, col["relation"])
            self._handle()

        def _glyphs(self, parent, q, got, c):
            """The glyphs at q in one row (an SoImage beside the point); their names as text when no
            image can be made."""
            keys = list(dict.fromkeys(key for key, _ in got))
            self.glyph_rows.append((q, keys))
            image = None
            try:
                image = glyph_image(keys, c)
            except Exception:
                image = None
            if image is None:
                self._text(parent, q, "  " + ", ".join(dict.fromkeys(r.name() for _, r in got)), c)
                return
            coin = self.coin
            img = image.convertToFormat(QtGui.QImage.Format_RGBA8888).mirrored(False, True)
            w, h = img.width(), img.height()
            data = bytes(img.constBits())[:w * h * 4]
            sep = coin.SoSeparator()
            tr = coin.SoTranslation()
            tr.translation.setValue(*q)
            node = coin.SoImage()
            node.image.setValue(coin.SbVec2s(w, h), 4, data)
            node.horAlignment = coin.SoImage.LEFT
            node.vertAlignment = coin.SoImage.BOTTOM
            for n in (tr, node):
                sep.addChild(n)
            parent.addChild(sep)

        def _lines(self, parent, lines, c, width, pattern=0xFFFF):
            coin = self.coin
            sep = coin.SoSeparator()
            colour = coin.SoBaseColor()
            colour.rgb.setValue(*c)
            style = coin.SoDrawStyle()
            style.lineWidth = width
            style.linePattern = pattern
            coords = coin.SoCoordinate3()
            flat_pts, counts = [], []
            for line in lines:
                if len(line) < 2:
                    continue
                flat_pts += [list(p) for p in line]
                counts.append(len(line))
            if not counts:
                return
            coords.point.setValues(0, len(flat_pts), flat_pts)
            ls = coin.SoLineSet()
            ls.numVertices.setValues(0, len(counts), counts)
            for n in (colour, style, coords, ls):
                sep.addChild(n)
            parent.addChild(sep)

        def _points(self, parent, pts, c, size):
            coin = self.coin
            if not pts:
                return
            sep = coin.SoSeparator()
            colour = coin.SoBaseColor()
            colour.rgb.setValue(*c)
            style = coin.SoDrawStyle()
            style.pointSize = size
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(pts), [list(p) for p in pts])
            for n in (colour, style, coords, coin.SoPointSet()):
                sep.addChild(n)
            parent.addChild(sep)

        def _text(self, parent, p, text, c, size=11):
            coin = self.coin
            sep = coin.SoSeparator()
            tr = coin.SoTranslation()
            tr.translation.setValue(*p)
            colour = coin.SoBaseColor()
            colour.rgb.setValue(*c)
            font = coin.SoFont()
            font.size = size
            font.name = "Arial"
            t = coin.SoText2()
            t.string = text
            for n in (tr, colour, font, t):
                sep.addChild(n)
            parent.addChild(sep)

        def set_curvature(self, k, on):
            (self.curvature.add if on else self.curvature.discard)(k)
            self.redraw()

        def _combs(self, g):
            ""

            for k in sorted(self.curvature):
                if k >= len(self.ents) or self.ents[k].kind != "S":
                    continue
                try:
                    edge = entity_edges(self.ents[k], self.pts, self.rels)[0]
                    c = edge.Curve
                    t0, t1 = edge.ParameterRange
                    samples = [t0 + (t1 - t0) * j / 48.0 for j in range(49)]
                    data = []
                    for t in samples:
                        p = c.value(t)
                        kap = c.curvature(t)
                        nv = c.normal(t) if kap > 1e-12 else App.Vector(0, 0, 0)
                        data.append(((p.x, p.y, p.z), kap, (nv.x, nv.y, nv.z)))
                except Exception:
                    continue
                top = max(d[1] for d in data) or 1.0
                scale = 0.25 * edge.Length / top
                tips = [_sub(p, _mul(nv, kap * scale)) for p, kap, nv in data]
                teeth = [[p, tip] for (p, _, _), tip in zip(data, tips)]
                self._lines(g, teeth, (0.75, 0.2, 0.75), 1.0)
                self._lines(g, [tips], (0.75, 0.2, 0.75), 1.0)

        def toggle_mark(self, which, items=None):
            """Show Inflection Points / Show Minimum Radius of Curvature / Show Curvature / Show Spline Control
            Polygon on the picked splines (on for all of them, or off when all show it). Show Spline Handles is
            on by default: its set holds the splines switched off."""
            store = {"inflections": self.inflections, "min_radius": self.min_radius,
                     "curvature": self.curvature, "handles": self.handles_off, "polygon": self.polygon}[which]
            ks = items if items is not None else [i for kind, i in self.selection
                                                  if kind == "E" and self.ents[i].kind == "S"]
            if not ks:
                return False
            on = not all(k in store for k in ks)
            for k in ks:
                (store.add if on else store.discard)(k)
            self.redraw()
            return on

        def set_ink(self, strokes, name="Pen Sketch ink"):
            """The sketch's ink now strokes (one undo step; kept in the sketch until converted)."""
            self.ink = [list(map(tuple, s)) for s in strokes]
            self.ink_picked = {n for n in self.ink_picked if n < len(self.ink)}
            doc = self.obj.Document
            doc.openTransaction(name)
            try:
                _save_ink(self.obj, self.ink)
            finally:
                doc.commitTransaction()
            self.redraw()

        def convert_ink(self, as_shapes):
            """Convert to Shape (lines, and splines for curves; a stroke with corners: joined lines) or Convert to
            Entities (splines) on the picked ink, else all of it; the new entities' indices."""
            chosen = sorted(self.ink_picked) if self.ink_picked else list(range(len(self.ink)))
            if not chosen:
                self.status("There is no ink to convert.")
                return []
            pts, ents, rels = list(self.pts), list(self.ents), list(self.rels)
            made = []
            for n in chosen:
                made += _stroke_entities(self.ink[n], as_shapes, pts, ents)
            self.write("Convert to Shape" if as_shapes else "Convert to Entities", pts, ents, rels)
            self.ink_picked = set()
            self.set_ink([s for n, s in enumerate(self.ink) if n not in chosen], "Convert ink")
            return made

        def _ink_marks(self, g):
            if self.ink:
                plain = [s for n, s in enumerate(self.ink) if n not in self.ink_picked and len(s) > 1]
                if plain:
                    self._lines(g, plain, (0.1, 0.3, 0.9), 2.0)
                picked = [self.ink[n] for n in sorted(self.ink_picked) if n < len(self.ink) and len(self.ink[n]) > 1]
                if picked:
                    self._lines(g, picked, (1.0, 0.55, 0.0), 3.0)
            if self.ruler is not None and math.dist(self.ruler[0], self.ruler[1]) > 1e-9:
                self._lines(g, [list(self.ruler)], (0.45, 0.45, 0.45), 4.0)

        def control_polygon(self, k):
            """Spline k's control polygon: its B-spline's poles (a Style Spline's: its own points)."""
            e = self.ents[k]
            if spline_style(e, self.rels):
                return [self.pts[i] for i in e.points]
            try:
                c = entity_edges(e, self.pts, self.rels)[0].Curve
                return [(p.x, p.y, p.z) for p in c.getPoles()]
            except Exception:
                return []

        def _spline_marks(self, g):
            picked = {i for kind, i in self.selection if kind == "E"}
            styled = {k for k in picked if k < len(self.ents) and self.ents[k].kind == "S"
                      and spline_style(self.ents[k], self.rels)}
            for k in sorted(self.inflections | self.min_radius | styled | self.polygon):
                if k >= len(self.ents) or self.ents[k].kind != "S":
                    continue
                e = self.ents[k]
                if k in styled:

                    self._lines(g, [[self.pts[i] for i in e.points]], (0.45, 0.45, 0.45), 1.0, 0x0F0F)
                elif k in self.polygon:
                    poly = self.control_polygon(k)
                    if poly:
                        self._lines(g, [poly], (0.45, 0.45, 0.45), 1.0, 0x0F0F)
                        self._points(g, poly, (0.45, 0.45, 0.45), 5.0)
                if not (k in self.inflections or k in self.min_radius):
                    continue
                try:
                    infl, mr = spline_marks(entity_edges(e, self.pts, self.rels)[0])
                except Exception:
                    continue
                if k in self.inflections and infl:
                    self._points(g, infl, (0.9, 0.45, 0.0), 9.0)
                if k in self.min_radius and mr is not None:
                    self._points(g, [mr[0]], (0.1, 0.55, 0.9), 9.0)
                    self._text(g, mr[0], "R%s" % _fmt(mr[1]), (0.1, 0.55, 0.9))

        def simplify_spline(self, k, tolerance):
            """Simplify Spline: spline k with the fewest through points within the tolerance (its ends stay)."""
            e = self.ents[k]
            try:
                new = simplify_points(self, k, tolerance)
            except Exception as error:
                return "Simplify Spline: %s" % error
            closed = len(e.points) > 3 and e.points[0] == e.points[-1]
            pts, ents, rels = list(self.pts), list(self.ents), list(self.rels)
            first, last = e.points[0], e.points[-1]
            mid = []
            for q in new[1:(None if closed else -1)]:
                pts.append(q)
                mid.append(len(pts) - 1)
            idx = [first] + mid + ([first] if closed else [last])
            ents[k] = S.Entity("S", idx, e.construction)
            # handles on points that go, go with them (compact); the spline's own settings stay on its ends
            self.write("Simplify Spline", pts, ents, rels, solve_first=False)
            return None

        def add_spline_control(self, k, q, curvature=False):
            """Add Tangency Control / Add Curvature Control: a new point on spline k where q is closest, with
            its handle set along the spline there (the shape kept), to drag at once."""
            e = self.ents[k]
            if e.kind != "S" or spline_style(e, self.rels):
                return "Pick a spline (not a Style Spline)."
            got = self.spline_inserted(k, q)
            if isinstance(got, str):
                return got
            pts, ents, rels, new = got
            try:
                c = entity_edges(e, self.pts, self.rels)[0].Curve
                tv = c.tangent(c.parameter(App.Vector(*pts[new])))[0]
            except Exception:
                return "The spline cannot be read."
            p = ents[k].points
            pos = p.index(new)
            vals = list(_unit((tv.x, tv.y, tv.z))) + [1.0]
            rels.append(S.Relation("SplineHandle", [new, p[pos + 1]], vals))
            self.write("Add Curvature Control" if curvature else "Add Tangency Control", pts, ents, rels,
                       solve_first=False)
            self.select([("P", new)])
            return None

        def convert_to_style(self, k):
            """Convert to Style Spline: spline k as a Style Spline (one Bezier span) that keeps its shape and
            ends; a vertex for each through point, at least 4."""
            import numpy as np
            e = self.ents[k]
            if e.kind != "S" or (spline_style(e, self.rels) and not spline_generic(e, self.rels)):
                return "Pick a spline (not a Style Spline)."
            if len(e.points) > 3 and e.points[0] == e.points[-1]:
                return "Convert to Style Spline takes an open spline."
            try:
                edge = entity_edges(e, self.pts, self.rels)[0]
            except Exception as _fw_err:
                _fw_log("sketch3d.py:1984", _fw_err)
                return "The spline cannot be read."
            n = min(25, max(4, len(e.points)))
            m = 80
            L = edge.Length
            samples = [edge.valueAt(edge.getParameterByLength(min(L, L * i / (m - 1.0)) * (1 - 1e-12))) for i in range(m)]
            u = np.linspace(0.0, 1.0, m)
            from math import comb
            B = np.array([[comb(n - 1, j) * x ** j * (1 - x) ** (n - 1 - j) for j in range(n)] for x in u])
            Q = np.array([[v.x, v.y, v.z] for v in samples])
            P0, P1 = Q[0], Q[-1]
            rhs = Q - np.outer(B[:, 0], P0) - np.outer(B[:, -1], P1)
            mid = np.linalg.lstsq(B[:, 1:-1], rhs, rcond=None)[0]
            # a few rounds of parameter correction: each sample to its nearest spot on the Bezier
            import Part
            for _ in range(4):
                bz = Part.BezierCurve()
                bz.setPoles([App.Vector(*P0)] + [App.Vector(*r) for r in mid] + [App.Vector(*P1)])
                u = np.array([min(1.0, max(0.0, bz.parameter(v))) for v in samples])
                u[0], u[-1] = 0.0, 1.0
                B = np.array([[comb(n - 1, j) * x ** j * (1 - x) ** (n - 1 - j) for j in range(n)] for x in u])
                rhs = Q - np.outer(B[:, 0], P0) - np.outer(B[:, -1], P1)
                mid = np.linalg.lstsq(B[:, 1:-1], rhs, rcond=None)[0]
            pts, ents = list(self.pts), list(self.ents)
            a, b = e.points[0], e.points[-1]
            idx = [a]
            for r in mid:
                pts.append(tuple(float(x) for x in r))
                idx.append(len(pts) - 1)
            idx.append(b)
            ents[k] = S.Entity("S", idx, e.construction)
            own = set(e.points)
            rels = [r for r in self.rels if not (r.kind in ("SplineHandle", "SplineProportional", "SplineLoose",
                                                            "SplineGeneric") and set(r.points[:2]) <= own)]
            rels.append(S.Relation("SplineStyle", [a, b]))
            self.write("Convert to Style Spline", pts, ents, rels, solve_first=False)
            return None

        def convert_to_spline(self, k):
            """Convert to Spline: Style Spline k as a spline through points that keeps its shape and ends (a
            point for each control vertex, at least 4, each with its handle along the curve)."""
            e = self.ents[k]
            if e.kind != "S" or not spline_style(e, self.rels):
                return "Pick a Style Spline."
            try:
                edge = entity_edges(e, self.pts, self.rels)[0]
            except Exception as _fw_err:
                _fw_log("sketch3d.py:2031", _fw_err)
                return "The Style Spline cannot be read."
            n = max(4, len(e.points))
            c = edge.Curve
            L = edge.Length
            a, b = e.points[0], e.points[-1]
            pts, ents = list(self.pts), list(self.ents)
            idx, dirs = [], []
            for i in range(n):
                par = edge.getParameterByLength(min(L, L * i / (n - 1.0)) * (1 - 1e-12))
                v = c.value(par)
                tv = c.tangent(par)[0]
                dirs.append(_unit((tv.x, tv.y, tv.z)))
                if i == 0:
                    idx.append(a)
                elif i == n - 1:
                    idx.append(b)
                else:
                    pts.append((v.x, v.y, v.z))
                    idx.append(len(pts) - 1)
            ents[k] = S.Entity("S", idx, e.construction)
            rels = [r for r in self.rels if not (r.kind in ("SplineStyle", "SplineGeneric") and r.points == [a, b])]
            for j, i in enumerate(idx):
                near = idx[j + 1] if j + 1 < len(idx) else idx[j - 1]
                rels.append(S.Relation("SplineHandle", [i, near], list(dirs[j]) + [1.0]))
            self.write("Convert to Spline", pts, ents, rels, solve_first=False)
            return None

        def convert_to_generic(self, k):
            """Convert to Generic Spline: spline k (through points, or Style) as a generic spline, a clamped
            cubic B-spline over poles that keeps its shape and ends; no handles."""
            import numpy as np
            e = self.ents[k]
            if e.kind != "S" or spline_generic(e, self.rels):
                return "Pick a spline (not a generic one)."
            if len(e.points) > 3 and e.points[0] == e.points[-1]:
                return "Convert to Generic Spline takes an open spline."
            try:
                edge = entity_edges(e, self.pts, self.rels)[0]
            except Exception as _fw_err:
                _fw_log("sketch3d.py:2071", _fw_err)
                return "The spline cannot be read."
            n = min(30, max(4, len(e.points) + 2))
            knots, mults, d = generic_knots(n)
            m = 100
            L = edge.Length
            samples = [edge.valueAt(edge.getParameterByLength(min(L, L * i / (m - 1.0)) * (1 - 1e-12))) for i in range(m)]
            Q = np.array([[v.x, v.y, v.z] for v in samples])
            u = np.linspace(0.0, 1.0, m)
            import Part
            for _ in range(5):
                B = np.array([_basis(knots, mults, d, x) for x in u])
                rhs = Q - np.outer(B[:, 0], Q[0]) - np.outer(B[:, -1], Q[-1])
                mid = np.linalg.lstsq(B[:, 1:-1], rhs, rcond=None)[0]
                c = style_edge([tuple(Q[0])] + [tuple(r) for r in mid] + [tuple(Q[-1])], True).Curve
                u = np.array([min(1.0, max(0.0, c.parameter(v))) for v in samples])
                u[0], u[-1] = 0.0, 1.0
            pts, ents = list(self.pts), list(self.ents)
            a, b = e.points[0], e.points[-1]
            idx = [a]
            for r in mid:
                pts.append(tuple(float(x) for x in r))
                idx.append(len(pts) - 1)
            idx.append(b)
            ents[k] = S.Entity("S", idx, e.construction)
            own = set(e.points)
            rels = [r for r in self.rels if not (r.kind in ("SplineHandle", "SplineProportional", "SplineLoose",
                                                            "SplineStyle") and set(r.points[:2]) <= own)]
            rels.append(S.Relation("SplineGeneric", [a, b]))
            self.write("Convert to Generic Spline", pts, ents, rels, solve_first=False)
            return None

        def picked_spline(self, style=None):
            """The first picked spline (style True: a Style Spline only, False: not one), else None."""
            for kind, i in self.selection:
                if kind == "E" and self.ents[i].kind == "S":
                    if style is None or bool(spline_style(self.ents[i], self.rels)) == style:
                        return i
            return None

        def insert_control_vertex(self, k, q):
            """Insert Control Vertex on Style Spline k: a new control vertex on the control polygon where q is
            nearest."""
            e = self.ents[k]
            if not spline_style(e, self.rels) or len(e.points) >= 25:
                return "Insert Control Vertex works on a Style Spline (up to 25 vertices)."
            best = None
            for j, (a, b) in enumerate(zip(e.points[:-1], e.points[1:])):
                d, f, _ = _seg_closest(self.pts[a], self.pts[b], q, q)
                if best is None or d < best[0]:
                    best = (d, j, _add(self.pts[a], _mul(_sub(self.pts[b], self.pts[a]), f)))
            _, j, p = best
            pts, ents = list(self.pts) + [p], list(self.ents)
            ents[k] = S.Entity("S", e.points[:j + 1] + [len(pts) - 1] + e.points[j + 1:], e.construction)
            self.write("Insert Control Vertex", pts, ents, list(self.rels), solve_first=False)
            return None

        def _origin_triad(self, g):
            ""

            try:
                sp = self.to_screen((0.0, 0.0, 0.0))
                if sp is None:
                    return
                size = 36.0 * self.ratio * self.world_per_px(sp[0], sp[1], (0.0, 0.0, 0.0))
            except Exception:
                return
            if not size > 0:
                return
            self.triad_size = size
            for axis, colour, name in (((1, 0, 0), (0.85, 0.1, 0.1), "X"), ((0, 1, 0), (0.1, 0.65, 0.1), "Y"),
                                       ((0, 0, 1), (0.15, 0.3, 0.95), "Z")):
                tip = _mul(axis, size)
                self._lines(g, [[(0.0, 0.0, 0.0), tip]], colour, 2.0)
                self._text(g, _mul(axis, size * 1.15), name, colour)

        def _handle(self):
            ""

            p = self.cursor_pos
            if p is None or self.tool is None:
                return
            x, y = self.cursor()
            size = 30.0 * self.ratio * self.world_per_px(x, y, p)
            if size <= 0:
                return
            n, (u, v) = self.axes()
            corners = [_add(p, _add(_mul(u, su * size), _mul(v, sv * size))) for su, sv in
                       ((0, 0), (1, 0), (1, 1), (0, 1), (0, 0))]
            g = self.layer_geo
            coin = self.coin
            sep = coin.SoSeparator()
            mat = coin.SoMaterial()
            mat.diffuseColor.setValue(0.55, 0.7, 0.9)
            mat.transparency = 0.7
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, 4, [list(c) for c in corners[:4]])
            face = coin.SoFaceSet()
            face.numVertices.setValue(4)
            for node in (mat, coords, face):
                sep.addChild(node)
            g.addChild(sep)
            self._lines(g, [corners], (0.35, 0.5, 0.75), 1.0)
            axis_colour = {(1, 0, 0): (0.85, 0.1, 0.1), (0, 1, 0): (0.1, 0.65, 0.1), (0, 0, 1): (0.15, 0.3, 0.95)}
            for w in (u, v):
                self._lines(g, [[p, _add(p, _mul(w, size * 1.4))]], axis_colour.get(tuple(w), (0.4, 0.4, 0.4)), 2.0)

        def tool_drawing(self, lines=(), guides=(), label=None, label_at=None, points=()):
            """The running tool's preview: rubber band lines, dotted inference lines, the pointer text."""
            col = colours()
            t = self.layer_tool
            t.removeAllChildren()
            if lines:
                self._lines(t, list(lines), col["preview"], 2.0)
            if guides:
                self._lines(t, list(guides), col["guide"], 1.0, 0xAAAA)
            if points:
                self._points(t, list(points), col["hover"], 8.0)
            label = self._badges(label)
            if label and label_at is not None:
                self._text(t, label_at, "    " + label, col["text"])
            self._plane_tag(t, col)
            self.redraw()

        BADGES = (("Coincident", "Coincident"), ("Midpoint", "Midpoint"), ("Along X", "AlongX"),
                  ("Along Y", "AlongY"), ("Along Z", "AlongZ"), ("On Plane", "OnPlane"), ("On Line", "OnEdge"),
                  ("OnLine", "OnEdge"), ("Tangent", "Tangent"), ("Perpendicular", "Perpendicular"),
                  ("Parallel", "Parallel"), ("Horizontal", "Horizontal"), ("Vertical", "Vertical"))

        def _badges(self, label):
            ""

            glyphs = []
            rest = (label or "").strip()
            changed = True
            while rest and changed:
                changed = False
                for word, glyph in self.BADGES:
                    if rest.startswith(word):
                        glyphs.append(glyph)
                        rest = rest[len(word):].strip()
                        changed = True
                        break
            tool = self.tool
            try:
                if tool is not None and getattr(self, "_badge_key", None) != (id(tool), tuple(glyphs)):
                    from .fwsketch.cursor import ToolCursor
                    tc = getattr(tool, "_tool_cursor", None)
                    if tc is None:
                        tc = tool._tool_cursor = ToolCursor(getattr(tool, "CURSOR", "Sketcher_Pointer_Create_Lineset"),
                                                            self.ratio)
                    self.viewport.setCursor(tc.cursor(glyphs))
                    self._badge_key = (id(tool), tuple(glyphs))
            except Exception:
                return label
            return rest

        def _plane_tag(self, parent, col):
            ""
            if self.tool is None or self.cursor_pos is None or not getattr(self.tool, "PLANE_TAG", True):
                return
            try:
                x, y = self.cursor()
                p = self.view.getPoint(int(x + 14 * self.ratio), int(y - 30 * self.ratio))
            except Exception:
                return
            self._text(parent, (p.x, p.y, p.z), self.plane, col["text"], size=15)

        # ------------------------------------------------------------- plane
        def next_plane(self):
            names = self.planes()
            self.plane = names[(names.index(self.plane) + 1) % len(names)] if self.plane in names else names[0]
            self.status("Sketch plane: %s (Tab changes it)" % self.plane)
            if self.tool is not None:
                self.tool.plane_changed()
            self.redraw()
            try:
                from . import sketch3dpm
                sketch3dpm.plane_changed(self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:2239", _fw_err)

        # ------------------------------------------------------------- tools
        def run_tool(self, tool):
            if self.tool is not None:
                self.tool.end()
            self.select([])
            self.tool = tool
            tool.begin()
            try:
                from . import sketch3dpm
                sketch3dpm.tool_started(self, tool)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD 3D Sketch: %s\n" % error)

        def tool_ended(self, tool):
            if self.tool is tool:
                self.tool = None
                self.layer_tool.removeAllChildren()
                self.cursor_pos = None
                self.redraw()
                try:
                    from . import sketch3dpm
                    sketch3dpm.tool_ended(self, tool)
                except Exception as _fw_err:
                    _fw_log("sketch3d.py:2264", _fw_err)

        # ------------------------------------------------------------- selection
        def select(self, items, add=False):
            if add:
                for it in items:
                    if it in self.selection:
                        self.selection.remove(it)
                    else:
                        self.selection.append(it)
            else:
                self.selection = list(items)
            self.fresh_spline = None
            self.redraw()
            self._selection_changed()

        def _selection_changed(self):
            try:
                from . import sketch3dpm
                sketch3dpm.selection_changed(self)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD 3D Sketch: %s\n" % error)

        def delete_selection(self):
            if not self.selection:
                return
            ents_drop = {i for k, i in self.selection if k == "E"}
            rels_drop = {i for k, i in self.selection if k == "R"}
            pts_drop = {i for k, i in self.selection if k == "P"}
            for i in pts_drop:
                ents_drop.update(self.entities_of_point(i))
            ents = [e for k, e in enumerate(self.ents) if k not in ents_drop]
            rels = [r for k, r in enumerate(self.rels) if k not in rels_drop]
            # a circle's or arc's own geometry goes with it
            owned = {tuple(e.points[:2] + ([e.points[2]] if e.kind == "A" else [e.points[1]]))
                     for e in ents if e.kind in ("C", "A")}
            rels = [r for r in rels if r.kind not in S.INTERNAL or tuple(r.points) in owned]
            # a spline that loses a through point keeps the others
            pts, ents, rels = S.compact(self.pts, ents, rels)
            self.selection = []
            self.write("Delete", pts, ents, rels, solve_first=False)

        def add_relation(self, rel):
            ""

            new = list(rel) if isinstance(rel, (list, tuple)) else [rel]
            rels, X = list(self.rels), S.flat(self.pts)
            for r in new:
                if r.kind in ("SplineTangent", "SplineTangentArc", "SplineTangentSpline"):
                    # held by how the spline is built: no equation to check
                    if any(x.kind == r.kind and x.points[:2] == r.points[:2] for x in rels):
                        return "The relation would over define the sketch: it holds already."
                    rels.append(r)
                    continue
                refs = _refs(self.doc, rels + [r])
                verdict, X = S.relation_adds_freedom_loss(len(self.pts), rels, r, X, refs)
                if verdict == "conflict":
                    return "The relation cannot be solved with the sketch's other relations."
                if verdict == "redundant":
                    return "The relation would over define the sketch: it holds already."
                rels.append(r)
            self.write("Add Relation", S.unflat(X), list(self.ents), rels, solve_first=False)
            return None

        def delete_relation(self, k):
            rels = [r for i, r in enumerate(self.rels) if i != k]
            self.write("Delete Relation", self.pts, self.ents, rels, solve_first=False)

        def set_dimension(self, k, value):
            r = self.rels[k]
            new = S.Relation(r.kind, r.points, [float(value)] + list(r.values[1:]), r.ref)
            rels = list(self.rels)
            rels[k] = new
            pts, ok = solve(self.doc, self.pts, rels)
            if not ok:
                return "The dimension cannot be solved with the sketch's other relations."
            self.write("Dimension", pts, self.ents, rels, solve_first=False)
            return None

        def move_points(self, targets):
            """Moves several points at once ({index: target}), the relations kept (a circle's centre and
            rim together, a line's end from its Delta X/Y/Z)."""
            fixed = [S.Relation("Fix", [i], list(t)) for i, t in targets.items()]
            pts, ok = solve(self.doc, self.pts, list(self.rels), extra=fixed)
            if not ok:
                return "The entity cannot go there: its relations hold it."
            self.write("Move", pts, self.ents, self.rels, solve_first=False)
            return None

        def move_point(self, i, target):
            """Moves point i to target (PropertyManager Parameters), the relations kept (a Proportional
            spline's shape too)."""
            fixed = [S.Relation("Fix", [i], list(target))] + [
                S.Relation("Fix", [m], list(v)) for m, v in self.proportional_targets({i}, {i: tuple(target)}).items()]
            pts, ok = solve(self.doc, self.pts, [r for r in self.rels], extra=fixed)
            if not ok:
                return "The point cannot go there: its relations hold it."
            self.write("Move Point", pts, self.ents, self.rels, solve_first=False)
            return None

        def set_length(self, e, value):
            a, b = self.ents[e].points[:2]
            # between virtual sharps: the line itself is shorter by what the fillets cut back
            cut = measured_length(self.pts, self.ents, e) - _len(_sub(self.pts[b], self.pts[a]))
            extra = [S.Relation("Distance", [a, b], [max(1e-6, float(value) - cut)])]
            pts, ok = solve(self.doc, self.pts, self.rels, extra=extra)
            if not ok:
                return "The line cannot take that length with its relations."
            self.write("Line Length", pts, self.ents, self.rels, solve_first=False)
            return None

        def set_radius(self, e, value):
            c, a = self.ents[e].points[:2]
            extra = [S.Relation("Radius", [c, a], [float(value)])]
            pts, ok = solve(self.doc, self.pts, self.rels, extra=extra)
            if not ok:
                return "The arc cannot take that radius with its relations."
            self.write("Radius", pts, self.ents, self.rels, solve_first=False)
            return None

        def set_construction(self, e, on):
            ents = [S.Entity(x.kind, x.points, on if k == e else x.construction) for k, x in enumerate(self.ents)]
            self.write("For Construction", self.pts, ents, self.rels, solve_first=False)

        # ------------------------------------------------------------- sketcher triad
        TRIAD_PX = 60.0       # arrow length on screen
        AXES = (((1.0, 0.0, 0.0), (0.85, 0.1, 0.1)), ((0.0, 1.0, 0.0), (0.1, 0.65, 0.1)),
                ((0.0, 0.0, 1.0), (0.15, 0.3, 0.95)))

        def triad_points(self):
            """The points the Sketcher Triad moves: those of the picked entities and points."""
            out = []
            for k, i in self.selection:
                if k == "P":
                    out.append(i)
                elif k == "E" and i < len(self.ents):
                    out += list(self.ents[i].points)
            return list(dict.fromkeys(out))

        def triad_frame(self):
            """(centre, arrow length) of the Sketcher Triad, else None (not shown)."""
            if not self.show_triad or self.tool is not None:
                return None
            drag = (self._drag or {}).get("triad")
            moving = drag["moving"] if drag else self.triad_points()
            if not moving:
                return None
            c = drag["centre"] if drag else _mul(tuple(sum(self.pts[i][j] for i in moving) for j in range(3)),
                                                  1.0 / len(moving))
            sp = self.to_screen(c)
            if sp is None:
                return None
            size = self.TRIAD_PX * self.ratio * self.world_per_px(sp[0], sp[1], c)
            return (c, size) if size > 0 else None

        def _ring(self, c, k, r, n=48):
            axis = self.AXES[k][0]
            u = self.AXES[(k + 1) % 3][0]
            v = self.AXES[(k + 2) % 3][0]
            return [_add(c, _add(_mul(u, r * math.cos(2 * math.pi * j / n)), _mul(v, r * math.sin(2 * math.pi * j / n))))
                    for j in range(n + 1)]

        def _sketcher_triad(self, g):
            ""

            got = self.triad_frame()
            if got is None:
                return
            c, size = got
            for k, (axis, colour) in enumerate(self.AXES):
                self._lines(g, [[c, _add(c, _mul(axis, size))]], colour, 3.0)
                self._points(g, [_add(c, _mul(axis, size))], colour, 9.0)
                self._lines(g, [self._ring(c, k, 0.6 * size)], colour, 1.5, 0xF0F0)
            self._points(g, [c], (0.9, 0.75, 0.1), 10.0)

        def triad_at(self, x, y):
            """("free",), ("axis", k) or ("ring", k): the part of the Sketcher Triad under the pointer."""
            got = self.triad_frame()
            if got is None:
                return None
            c, size = got
            reach = 7.0 * self.ratio
            d = self._screen_dist(c, x, y)
            if d is not None and d < reach:
                return ("free",)
            best, best_d = None, reach
            for k, (axis, _) in enumerate(self.AXES):
                dd, _ = self._seg_dist(_add(c, _mul(axis, 0.15 * size)), _add(c, _mul(axis, size)), x, y)
                if dd < best_d:
                    best, best_d = ("axis", k), dd
                ring = self._ring(c, k, 0.6 * size)
                dd = min(self._seg_dist(a, b, x, y)[0] for a, b in zip(ring[:-1], ring[1:]))
                if dd < best_d:
                    best, best_d = ("ring", k), dd
            return best

        def _triad_targets(self, d, x, y):
            """Where the triad drag puts the moving points."""
            part, c = d["triad"]["part"], d["triad"]["centre"]
            start = d["start"]
            if part[0] == "axis":
                axis = self.AXES[part[1]][0]
                o, w = self.ray(x, y)
                # the point of the axis line nearest the pointer's ray
                a, b, e = _dot(axis, axis), _dot(axis, w), _dot(w, w)
                r = _sub(c, o)
                den = a * e - b * b
                if abs(den) < 1e-12:
                    return None
                t = (b * _dot(w, r) - e * _dot(axis, r)) / den
                t0 = d["triad"].setdefault("t0", t)
                delta = _mul(axis, t - t0)
                return [_add(p, delta) for p in start]
            if part[0] == "ring":
                axis = self.AXES[part[1]][0]
                o, w = self.ray(x, y)
                den = _dot(w, axis)
                if abs(den) < 1e-12:
                    return None
                q = _add(o, _mul(w, _dot(_sub(c, o), axis) / den))
                v = _sub(q, c)
                if _len(v) < 1e-12:
                    return None
                v0 = d["triad"].setdefault("v0", v)
                ang = math.degrees(math.atan2(_dot(_cross(v0, v), axis), _dot(v0, v)))
                rot = App.Rotation(App.Vector(*axis), ang)
                d["triad"]["angle"] = ang
                out = []
                for p in start:
                    m = rot.multVec(App.Vector(*_sub(p, c)))
                    out.append(_add(c, (m.x, m.y, m.z)))
                return out
            q = self._view_point(x, y, c)
            q0 = d["triad"].setdefault("q0", q)
            delta = _sub(q, q0)
            return [_add(p, delta) for p in start]

        # ------------------------------------------------------------- spline handles
        HANDLE_PX = 36.0      # a handle's half length on screen at weight 1, as the 2D spline's
        HANDLE_GRAB_PX = 8.0

        def handle_lines(self):
            ""


            picked = {i for k, i in self.selection if k == "E"}
            points = {i for k, i in self.selection if k == "P"}
            drag = (self._drag or {}).get("handle")
            out = []
            for k, e in enumerate(self.ents):
                if e.kind != "S" or len(e.points) < 3:
                    continue
                if k in self.handles_off or spline_style(e, self.rels):
                    continue        # Show Spline Handles off; a Style Spline has its control polygon instead
                if k not in picked and not (points & set(e.points)) and not (drag and drag[0] == k) \
                        and k != self.fresh_spline:
                    continue
                try:
                    curve = entity_edges(e, self.pts, self.rels)[0].Curve
                except Exception:
                    continue
                own = spline_handles(e, self.rels)
                closed = len(e.points) > 3 and e.points[0] == e.points[-1]
                for pos, i in enumerate(e.points[:-1] if closed else e.points):
                    p = self.pts[i]
                    try:
                        t = curve.tangent(curve.parameter(App.Vector(*p)))[0]
                        d = _unit((t.x, t.y, t.z))
                    except Exception:
                        continue
                    w = own[pos][1] if pos in own else 1.0
                    w2 = own[pos][2] if pos in own else 1.0
                    if pos in own:
                        d = _unit(own[pos][0])
                    sp = self.to_screen(p)
                    if sp is None:
                        continue
                    unit = self.HANDLE_PX * self.ratio * self.world_per_px(sp[0], sp[1], p)
                    out.append((k, pos, p, d, w, pos in own, w * unit, w2 * unit))
            return out

        def _spline_handles(self, g):
            drag = (self._drag or {}).get("handle")
            for k, pos, p, d, w, own, half, back in self.handle_lines():
                ends = [_sub(p, _mul(d, back)), _add(p, _mul(d, half))]
                if drag and drag[:2] == (k, pos):
                    c, width = (1.0, 0.65, 0.0), 2.0
                elif own:
                    c, width = (0.25, 0.45, 0.95), 2.0
                else:
                    c, width = (0.55, 0.55, 0.6), 1.0
                self._lines(g, [ends], c, width)
                coin = self.coin
                sep = coin.SoSeparator()
                colour = coin.SoBaseColor()
                colour.rgb.setValue(*c)
                coords = coin.SoCoordinate3()
                coords.point.setValues(0, 2, [list(q) for q in ends])
                marks = coin.SoMarkerSet()
                marks.markerIndex = coin.SoMarkerSet.DIAMOND_FILLED_9_9
                for n in (colour, coords, marks):
                    sep.addChild(n)
                g.addChild(sep)

        def handle_at(self, x, y):
            """(entity, position, side) of the handle diamond within reach of the pointer: side +1 the
            front one (the way of the spline's points), -1 the back one; else None."""
            best, reach = None, self.HANDLE_GRAB_PX * self.ratio
            for k, pos, p, d, w, own, half, back in self.handle_lines():
                for side in (1.0, -1.0):
                    dist = self._screen_dist(_add(p, _mul(d, half if side > 0 else -back)), x, y)
                    if dist is not None and dist <= reach:
                        best, reach = (k, pos, side), dist
            return best

        def _view_point(self, x, y, p):
            """The point under the pointer on the screen-facing plane through p."""
            o, d = self.ray(x, y)
            den = _dot(d, d)
            if den < 1e-12:
                return tuple(p)
            return _add(o, _mul(d, _dot(_sub(p, o), d) / den))

        def handle_relation(self, k, pos, direction, weight, back=None):
            """The SplineHandle relation for spline k's point pos (direction the way of its points; weight the
            leaving side's, back the arriving side's, the same when None)."""
            e = self.ents[k]
            closed = len(e.points) > 3 and e.points[0] == e.points[-1]
            p = e.points[:-1] if closed else list(e.points)
            near = p[(pos + 1) % len(p)] if closed or pos + 1 < len(p) else p[pos - 1]
            w = max(0.05, float(weight))
            w2 = w if back is None else max(0.05, float(back))
            vals = list(_unit(direction)) + [w]
            if abs(w2 - w) > 1e-12:
                vals.append(w2)
            return S.Relation("SplineHandle", [p[pos], near], vals)

        def _without_handle(self, rels, k, pos):
            e = self.ents[k]
            closed = len(e.points) > 3 and e.points[0] == e.points[-1]
            p = e.points[:-1] if closed else list(e.points)
            a = p[pos]
            near = {p[(pos + 1) % len(p)], p[pos - 1]} if closed else set(p[pos + 1:pos + 2] + p[max(0, pos - 1):pos])
            return [r for r in rels if not (r.kind == "SplineHandle" and r.points[0] == a and r.points[1] in near)]

        def set_handle(self, k, pos, direction, weight, name="Spline handle", back=None):
            rels = self._without_handle(self.rels, k, pos) + [self.handle_relation(k, pos, direction, weight, back)]
            self.write(name, self.pts, self.ents, rels, solve_first=False)

        def reset_handles(self, k, positions=None, keep_directions=False, name="Reset Handle"):
            """Reset This Handle / Reset All Handles (positions None); keep_directions: Relax Spline (each
            set handle keeps its direction, its weight back to 1)."""
            rels = list(self.rels)
            own = spline_handles(self.ents[k], rels)
            for pos in (own if positions is None else positions):
                if pos in own:
                    rels = self._without_handle(rels, k, pos)
                    if keep_directions:
                        rels.append(self.handle_relation(k, pos, own[pos][0], 1.0))
            self.write(name, self.pts, self.ents, rels, solve_first=False)

        def picked_spline_end(self):
            """(spline, 0 or last position) of the picked spline end point, else None."""
            for kind, i in self.selection:
                if kind != "P":
                    continue
                for k, e in enumerate(self.ents):
                    if e.kind != "S" or len(e.points) < 2 or (len(e.points) > 3 and e.points[0] == e.points[-1]):
                        continue
                    if i == e.points[0]:
                        return k, 0
                    if i == e.points[-1]:
                        return k, len(e.points) - 1
            return None

        def reverse_end_tangent(self, k=None, pos=None):
            ""


            if k is None:
                end = self.picked_spline_end()
                if end is None:
                    self.status("Flip Endpoint Tangent: pick a spline end point first.")
                    return False
                k, pos = end
            e = self.ents[k]
            last = pos != 0
            if spline_tangents(e, self.pts, self.rels)[1 if last else 0] is not None:
                self.status("Flip Endpoint Tangent: a relation holds this spline end's tangent; delete it "
                            "to reverse the tangent.")
                return False
            own = spline_handles(e, self.rels)
            if pos in own:
                d, w, w2 = own[pos]
            else:
                c = entity_edges(e, self.pts, self.rels)[0].Curve
                t = c.tangent(c.LastParameter if last else c.FirstParameter)[0]
                d, w, w2 = (t.x, t.y, t.z), 1.0, 1.0
            self.set_handle(k, pos, _mul(_unit(d), -1.0), w, name="Flip Endpoint Tangent", back=w2)
            return True

        def set_continuity(self, k, on):
            ""
            e = self.ents[k]
            a, b = e.points[0], e.points[-1]
            rels = [r for r in self.rels if not (r.kind == "SplineLoose" and r.points == [a, b])]
            if not on:
                rels.append(S.Relation("SplineLoose", [a, b]))
            self.write("Maintain internal continuity", self.pts, self.ents, rels, solve_first=False)

        def set_proportional(self, k, on):
            e = self.ents[k]
            a, b = e.points[0], e.points[-1]
            rels = [r for r in self.rels if not (r.kind == "SplineProportional" and r.points == [a, b])]
            if on:
                rels.append(S.Relation("SplineProportional", [a, b]))
            self.write("Proportional", self.pts, self.ents, rels, solve_first=False)

        def proportional(self, k):
            e = self.ents[k]
            return any(r.kind == "SplineProportional" and r.points == [e.points[0], e.points[-1]] for r in self.rels)

        def proportional_targets(self, moving, targets):
            ""

            out = {}
            for r in self.rels:
                if r.kind != "SplineProportional":
                    continue
                a, b = r.points
                if (a in moving) == (b in moving):
                    continue
                e = next((x for x in self.ents if x.kind == "S" and x.points[0] == a and x.points[-1] == b), None)
                if e is None:
                    continue
                pa, pb = self.pts[a], self.pts[b]
                na, nb = targets.get(a, pa), targets.get(b, pb)
                u, w = _sub(pb, pa), _sub(nb, na)
                lu, lw = _len(u), _len(w)
                if lu < 1e-12 or lw < 1e-12:
                    continue
                rot = App.Rotation(App.Vector(*u), App.Vector(*w))
                k = lw / lu
                for i in e.points[1:-1]:
                    v = rot.multVec(App.Vector(*_sub(self.pts[i], pa))) * k
                    out[i] = _add(na, (v.x, v.y, v.z))
            return out

        # ------------------------------------------------------------- dragging
        def _drag_start(self, item, x, y):
            kind, i = item
            if kind == "H":
                return {"handle": i, "moved": False, "rels": list(self.rels)}
            if kind == "T":
                moving = self.triad_points()
                c, _ = self.triad_frame()
                return {"triad": {"part": i, "centre": c, "moving": moving}, "moving": moving, "grab": c,
                        "start": [self.pts[m] for m in moving], "moved": False, "pts": list(self.pts)}
            if kind == "P":
                moving = [i]
                grab = self.pts[i]
            elif kind == "E":
                ent = self.ents[i]
                moving = list(dict.fromkeys(ent.points))
                if ent.kind == "L":
                    grab = self._closest_on_line(self.pts[ent.points[0]], self.pts[ent.points[1]], x, y)
                else:
                    grab = self.pts[moving[0]]
            else:
                return None
            return {"moving": moving, "grab": grab, "start": [self.pts[m] for m in moving], "moved": False,
                    "pts": list(self.pts)}

        def _drag_move(self, x, y):
            d = self._drag
            if "handle" in d:
                # a handle diamond: direction from the point to the pointer, weight its distance / 36 px; with

                k, pos, side = d["handle"]
                e = self.ents[k]
                p = self.pts[e.points[pos]]
                q = self._view_point(x, y, p)
                v = _mul(_sub(q, p), side)
                sp = self.to_screen(p)
                unit_len = self.HANDLE_PX * self.ratio * self.world_per_px(sp[0], sp[1], p) if sp else 0.0
                if _len(v) < 1e-12 or not unit_len > 0:
                    return
                w = max(0.05, _len(v) / unit_len)
                w1 = w2 = w
                if QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.AltModifier:
                    was = spline_handles(e, d["rels"]).get(pos)
                    other = (was[2] if side > 0 else was[1]) if was else 1.0
                    w1, w2 = (w, other) if side > 0 else (other, w)
                self.rels = self._without_handle(d["rels"], k, pos) + [self.handle_relation(k, pos, v, w1, w2)]
                d["moved"] = True
                self.redraw()
                return
            if "triad" in d:
                targets = self._triad_targets(d, x, y)
                if targets is None:
                    return
            else:
                q = self.on_plane(x, y, d["grab"])
                delta = _sub(q, d["grab"])
                targets = [_add(s, delta) for s in d["start"]]
            extra = [S.Relation("Fix", [m], list(v)) for m, v in zip(d["moving"], targets)]
            extra += [S.Relation("Fix", [m], list(v)) for m, v in self.proportional_targets(
                set(d["moving"]), dict(zip(d["moving"], targets))).items()]
            pts, ok = solve(self.doc, d["pts"], self.rels, extra=extra)
            if not ok:
                # the relations do not let it go there: put it there and let the relations pull it back

                start = list(d["pts"])
                for m, v in zip(d["moving"], targets):
                    start[m] = v
                pts, ok = solve(self.doc, start, self.rels)
            if ok:
                self.pts = pts
                d["moved"] = True
                self.redraw()

        def _drag_end(self):
            d, self._drag = self._drag, None
            if d is not None and "handle" in d:
                rels, self.rels = self.rels, d["rels"]
                if d["moved"]:
                    self.write("Spline handle", self.pts, self.ents, rels, solve_first=False)
                else:
                    self.redraw()
                return
            if d is None or not d["moved"]:
                return
            pts = self.pts
            self.pts = d["pts"]
            self.write("Drag" if "triad" not in d or d["triad"]["part"][0] != "ring" else "Rotate", pts, self.ents,
                       self.rels, solve_first=False)

        # ------------------------------------------------------------- events
        def eventFilter(self, obj, event):
            if not isinstance(event, QtCore.QEvent):
                return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
            # an exception out of a Qt override takes FreeCAD down: keep them in here
            try:
                return self._filter(obj, event)
            except Exception:
                import traceback
                App.Console.PrintError("FreeCAD 3D Sketch: %s" % traceback.format_exc())
                return False

        def _over_view(self):
            try:
                return self.viewport.underMouse()
            except RuntimeError:
                return False

        @staticmethod
        def _text_has_focus():
            w = QtWidgets.QApplication.focusWidget()
            return isinstance(w, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
                                  QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox))

        KEYS = None

        def _claims(self, key):

            # leaves a sketch on Esc
            if key in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Escape):
                return True
            if key == QtCore.Qt.Key_Delete:
                return bool(self.selection) and self.tool is None
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                return self.tool is not None and hasattr(self.tool, "apply")
            return False

        def _filter(self, obj, event):
            t = event.type()
            if t == QtCore.QEvent.KeyRelease and isinstance(event, QtGui.QKeyEvent) and event.key() in self._held:
                if not event.isAutoRepeat():
                    self._held.discard(event.key())
                return True       # the release of a key the sketch took is the sketch's too
            if obj is not self.viewport and obj is not self.quarter:
                if t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress) and isinstance(event, QtGui.QKeyEvent) \
                        and not self._text_has_focus() and self._over_view() and self._claims(event.key()):
                    if t == QtCore.QEvent.ShortcutOverride:
                        event.accept()
                        return True
                    return self._key(event.key())
                return False
            if t == QtCore.QEvent.ShortcutOverride and isinstance(event, QtGui.QKeyEvent) and self._claims(event.key()):
                event.accept()
                return True
            if t == QtCore.QEvent.KeyPress:
                if event.key() == QtCore.Qt.Key_Control and self.tool is not None:
                    self.tool.move(*self.cursor())
                    return False
                if self._claims(event.key()):
                    return self._key(event.key())
                return False
            if t == QtCore.QEvent.KeyRelease and event.key() == QtCore.Qt.Key_Control and self.tool is not None:
                self.tool.move(*self.cursor())
                return False
            if t == QtCore.QEvent.MouseMove:
                if self._other_buttons(event):
                    return False
                x, y = self.cursor()
                if self.tool is not None and not (self._press and (self._press.get("item") or ("",))[0] == "H"):
                    if self._press is not None:
                        self._press["dragged"] = self._press["dragged"] or self._moved_far(event)
                    self.tool.move(x, y)
                    return True
                if self._press is not None and self._press.get("item") is not None:
                    if not self._press["dragged"] and self._moved_far(event):
                        self._press["dragged"] = True
                        self._drag = self._drag_start(self._press["item"], x, y)
                    if self._drag is not None:
                        self._drag_move(x, y)
                        return True
                hit = self.pick(x, y)
                if hit != self.hover:
                    self.hover = hit
                    self.redraw()
                return hit is not None
            if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick):
                b = event.button()
                if b == QtCore.Qt.LeftButton:
                    x, y = self.cursor()
                    gp = self._global(event)
                    grab = self.handle_at(x, y) if self.tool is not None and self.fresh_spline is not None \
                        and t == QtCore.QEvent.MouseButtonPress and getattr(self.tool, "through", None) == [] else None
                    if grab is not None:

                        self._press = {"at": gp, "dragged": False, "item": ("H", grab)}
                        return True
                    if self.tool is not None:
                        self._press = {"at": gp, "dragged": False, "item": None}
                        if t == QtCore.QEvent.MouseButtonDblClick:
                            self.tool.double_click(x, y)
                        else:
                            self.tool.press(x, y)
                        return True
                    part = self.triad_at(x, y) if t == QtCore.QEvent.MouseButtonPress else None
                    if part is not None:
                        # the Sketcher Triad: an arrow moves along its axis, a ring turns, the centre moves freely
                        self._press = {"at": gp, "dragged": False, "item": ("T", part)}
                        return True
                    grab = self.handle_at(x, y) if t == QtCore.QEvent.MouseButtonPress else None
                    if grab is not None:
                        # a spline handle's diamond: dragging it sets the tangent there
                        self._press = {"at": gp, "dragged": False, "item": ("H", grab)}
                        return True
                    hit = self.pick(x, y)
                    if t == QtCore.QEvent.MouseButtonDblClick and hit is not None and hit[0] == "R":
                        from . import sketch3dpm
                        sketch3dpm.modify_dimension(self, hit[1])
                        return True
                    if t == QtCore.QEvent.MouseButtonDblClick and hit is not None and hit[0] == "E" \
                            and self.ents[hit[1]].kind == "Q":
                        self.activate_plane(hit[1])
                        return True
                    if t == QtCore.QEvent.MouseButtonDblClick and hit is None and self.on_sketch_plane() is not None:
                        self.leave_plane()
                        return True
                    if hit is None:
                        if not (event.modifiers() & QtCore.Qt.ControlModifier):
                            if self.selection:
                                self.select([])
                        return False
                    add = bool(event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier))
                    if not add and hit in self.selection:
                        pass
                    else:
                        self.select([hit], add=add)
                    self._press = {"at": gp, "dragged": False, "item": hit}
                    return True
                if b == QtCore.Qt.RightButton:
                    return True
                return False
            if t == QtCore.QEvent.MouseButtonRelease:
                b = event.button()
                if b == QtCore.Qt.LeftButton:
                    press, self._press = self._press, None
                    if press and (press.get("item") or ("",))[0] == "H" and self.tool is not None:
                        if self._drag is not None:
                            k = self._drag["handle"][0]
                            self._drag_end()
                            self.fresh_spline = k
                            self.redraw()
                        return True
                    if self.tool is not None:
                        x, y = self.cursor()
                        self.tool.release(x, y, bool(press and press["dragged"]))
                        return True
                    if self._drag is not None:
                        self._drag_end()
                        return True
                    return press is not None
                if b == QtCore.Qt.RightButton:
                    if self.tool is not None and getattr(self.tool, "RUNNING_MENU", False):
                        self._tool_menu(event)
                    elif self.tool is not None:
                        self.tool.right_click()
                    else:
                        self._context_menu(event)
                    return True
            return False

        def _moved_far(self, event):
            if self._press is None:
                return False
            return (self._global(event) - self._press["at"]).manhattanLength() >= \
                QtWidgets.QApplication.startDragDistance()

        @staticmethod
        def _global(event):
            try:
                return event.globalPosition().toPoint()
            except AttributeError:
                return event.globalPos()

        @staticmethod
        def _other_buttons(event):
            try:
                held = event.buttons()
                value = getattr(held, "value", None)
                if value is None:
                    value = int(held)
                return bool(int(value) & ~1)
            except Exception:
                return False

        def _key(self, key):
            self._held.add(key)
            if key == QtCore.Qt.Key_Tab:
                if isinstance(self.tool, DimensionTool) and self.tool.takes_tab():
                    self.tool.next_type()
                    return True
                self.next_plane()
                return True
            if key == QtCore.Qt.Key_Escape:
                if self.tool is not None:
                    self.tool.end()
                else:
                    self.select([])
                return True
            if key == QtCore.Qt.Key_Delete:
                self.delete_selection()
                return True
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and self.tool is not None:
                # Enter is the PropertyManager's OK (Convert Entities, Mirror)
                from . import sketch3dpm
                page = sketch3dpm.current()
                if page is not None and getattr(page, "tool", None) is self.tool:
                    page.accept()
                return True
            return False

        def hits_at(self, x, y):
            """Everything within reach of the pointer, nearest first: points, dimensions, entities (Select
            Other's list)."""
            tol = self.px() * 1.5
            out = []
            for i, p in enumerate(self.pts):
                d = self._screen_dist(p, x, y)
                if d is not None and d < tol and self.entities_of_point(i):
                    out.append((d, ("P", i)))
            for k, r in enumerate(self.rels):
                if r.kind in S.DIMENSIONS:
                    d = self._screen_dist(self.dim_anchor(r), x, y)
                    if d is not None and d < 1.6 * tol:
                        out.append((d, ("R", k)))
            for k, e in enumerate(self.ents):
                line = self.polyline(e)
                best = min([self._seg_dist(a, b, x, y)[0] for a, b in zip(line[:-1], line[1:])] or [1e9])
                if best < tol:
                    out.append((best, ("E", k)))
            out.sort(key=lambda t: t[0])
            return [h for _, h in out]

        def select_other(self, x, y):
            ""

            from . import sketch3dpm
            menu = QtWidgets.QMenu(Gui.getMainWindow())
            menu.setObjectName("SW3DSelectOther")
            for hit in self.hits_at(x, y):
                name = sketch3dpm.entity_name(self, hit) if hit[0] != "R" else S.NAMES.get(self.rels[hit[1]].kind,
                                                                                             "Dimension")
                menu.addAction(name).triggered.connect(lambda checked=False, h=hit: self.select([h]))
            self._other_menu = menu
            if not menu.isEmpty():
                menu.popup(QtGui.QCursor.pos())
            return menu

        def chain_of(self, k):
            """The entities joined end to end with entity k (shared points or Coincident): Select Chain."""
            links = {}
            for r in self.rels:
                if r.kind == "Coincident":
                    a, b = r.points[:2]
                    links.setdefault(a, set()).add(b)
                    links.setdefault(b, set()).add(a)
            seen, todo = {k}, [k]
            while todo:
                e = self.ents[todo.pop()]
                ends = {e.points[0], e.points[-1]} if e.kind in ("L", "S") else set(e.points[1:3])
                for p in list(ends):
                    ends |= links.get(p, set())
                for j, other in enumerate(self.ents):
                    if j in seen or other.kind in ("P", "Q"):
                        continue
                    if ends & set(other.points):
                        seen.add(j)
                        todo.append(j)
            return sorted(seen)

        def select_chain(self, k):
            self.select([("E", j) for j in self.chain_of(k)])

        def insert_spline_point(self, k, q):
            """Insert Spline Point: a new through point on spline k where q is closest, the shape kept as near
            as can be; the spline's own ties (Tangent, handles, Spline on Surface) follow."""
            got = self.spline_inserted(k, q)
            if isinstance(got, str):
                return got
            pts, ents, rels, new = got
            self.write("Insert Spline Point", pts, ents, rels, solve_first=False)
            return None

        def spline_inserted(self, k, q):
            """(points, entities, relations, new point) with a through point on spline k where q is closest,
            else a reason (str)."""
            e = self.ents[k]
            if e.kind != "S":
                return "Pick a spline."
            try:
                curve = entity_edges(e, self.pts, self.rels)[0].Curve
            except Exception:
                return "The spline cannot be read."
            tq = curve.parameter(App.Vector(*q))
            params = [curve.parameter(App.Vector(*self.pts[i])) for i in e.points]
            closed = len(e.points) > 3 and e.points[0] == e.points[-1]
            if closed:
                params[-1] = curve.LastParameter
            j = next((n for n in range(len(params) - 1) if params[n] < tq < params[n + 1]), None)
            if j is None:
                return "Click on the spline between two of its points."
            v = curve.value(tq)
            pts = list(self.pts) + [(v.x, v.y, v.z)]
            new = len(pts) - 1
            a, b = e.points[j], e.points[j + 1]
            ents = list(self.ents)
            ents[k] = S.Entity("S", e.points[:j + 1] + [new] + e.points[j + 1:], e.construction)
            rels = []
            for r in self.rels:
                if r.kind in S.SPLINE_OWN + ("SplineTangent", "SplineTangentArc", "SplineTangentSpline") and \
                        r.points[:2] in ([a, b], [b, a]):
                    r = S.Relation(r.kind, [r.points[0], new] + list(r.points[2:]), r.values, r.ref)
                rels.append(r)
            on = spline_surface(e, self.rels)
            if on is not None:
                rels.append(model_relation(self.doc, "OnSurface", new, on[0], on[1]))
            return pts, ents, rels, new

        def segment_spline(self, k, count, mode="points"):
            """Segment on spline k: count - 1 through points at equal lengths along it (Sketch points), and
            for Sketch segments the spline split there into count splines. One undo step."""
            e = self.ents[k]
            if len(e.points) > 3 and e.points[0] == e.points[-1]:
                return "Segment takes an open spline."
            try:
                edge = entity_edges(e, self.pts, self.rels)[0]
            except Exception:
                return "The spline cannot be read."
            L = edge.Length
            targets = [edge.valueAt(edge.getParameterByLength(L * i / float(count))) for i in range(1, int(count))]
            saved = self.pts, self.ents, self.rels
            new = []
            try:
                tol = 1e-6 * max([1.0] + [abs(c) for p in self.pts for c in p])
                for v in targets:
                    on = [i for i in self.ents[k].points if _len(_sub(self.pts[i], (v.x, v.y, v.z))) < tol]
                    if on:
                        new.append(on[0])      # already a through point there
                        continue
                    got = self.spline_inserted(k, (v.x, v.y, v.z))
                    if isinstance(got, str):
                        return got
                    self.pts, self.ents, self.rels, i = got
                    new.append(i)
                pts, ents, rels = self.pts, self.ents, self.rels
            finally:
                self.pts, self.ents, self.rels = saved
            if mode != "points":
                sp = ents[k].points
                cuts = [0] + sorted(sp.index(i) for i in new) + [len(sp) - 1]
                construction = ents[k].construction
                del ents[k]
                ents += [S.Entity("S", sp[x:y + 1], construction) for x, y in zip(cuts[:-1], cuts[1:])]
            self.write("Segment", pts, ents, rels, solve_first=False)
            return None

        def split_spline(self, k, q):
            """Split Entities on an open spline: a through point where q is closest (an existing through point
            when q is on one), and two splines that meet there."""
            e = self.ents[k]
            if len(e.points) > 3 and e.points[0] == e.points[-1]:
                return "Split Entities splits an open spline; trim a closed one instead."
            tol = 1e-6 * max([1.0] + [abs(c) for p in self.pts for c in p])
            at = next((n for n, i in enumerate(e.points) if _len(_sub(self.pts[i], q)) < tol), None)
            if at is not None:
                pts, ents, rels, new = list(self.pts), list(self.ents), list(self.rels), e.points[at]
            else:
                got = self.spline_inserted(k, q)
                if isinstance(got, str):
                    return got
                pts, ents, rels, new = got
            sp = ents[k].points
            j = sp.index(new)
            if j == 0 or j == len(sp) - 1:
                return "Click inside the spline, not at its end."
            del ents[k]
            ents += [S.Entity("S", sp[:j + 1], e.construction), S.Entity("S", sp[j:], e.construction)]
            # the whole spline's settings (continuity, Proportional, on a surface) go to both pieces; a handle
            # and an end's Tangent go with the piece they are on
            out = []
            for r in rels:
                if r.kind in ("SplineLoose", "SplineProportional") and r.points == [sp[0], sp[-1]]:
                    out += [S.Relation(r.kind, [sp[0], new], r.values, r.ref),
                            S.Relation(r.kind, [new, sp[-1]], r.values, r.ref)]
                    continue
                if r.kind == "SplineOnSurface" and r.points[:2] == sp[:2]:
                    out.append(S.Relation(r.kind, [new, sp[j + 1]] + list(r.points[2:]), r.values, r.ref))
                out.append(r)
            rels = out
            self.write("Split Entities", pts, ents, rels, solve_first=False)
            return None

        def _context_menu(self, event, full=False, at=None):
            ""








            menu = QtWidgets.QMenu(Gui.getMainWindow())
            menu.setObjectName("SW3DSketchContextMenu")
            menu.setProperty("swFull", bool(full))
            gpos = at[0] if at is not None else self._global(event)
            hidden = _menu_hidden()
            entries = []        # (key, label) for Customize Menu

            def item(key, label, fn=None, parent=None, enabled=True):
                entries.append((key, label))
                if key in hidden:
                    return None
                act = (parent or menu).addAction(label)
                act.setProperty("swKey", key)
                act.setEnabled(bool(enabled))
                if fn is not None:
                    act.triggered.connect(lambda checked=False, fn=fn: fn())
                return act
            keep = [menu]

            def submenu(title, parent=None):
                # made with a parent and kept: PySide drops a menu addMenu(title) made once Python lets go
                sub = QtWidgets.QMenu(title, menu)
                (parent or menu).addMenu(sub)
                keep.append(sub)
                return sub
            x, y = (at[1], at[2]) if at is not None else self.cursor()
            hit = self.pick(x, y)
            if hit is not None and hit not in self.selection:
                self.select([hit])
            on_entity = hit is not None and hit[0] in ("E", "P")
            # the icon rows
            rows = QtWidgets.QWidget(menu)
            rows.setObjectName("SW3DSketchContextBar")
            lay = QtWidgets.QVBoxLayout(rows)
            lay.setContentsMargins(4, 2, 4, 2)
            lay.setSpacing(0)

            def row(name):
                bar = QtWidgets.QToolBar(rows)
                bar.setObjectName(name)
                bar.setIconSize(QtCore.QSize(16, 16))
                lay.addWidget(bar)
                return bar

            def icon_action(bar, icon, tip, fn):
                act = bar.addAction(icon if isinstance(icon, QtGui.QIcon) else _command_icon(icon), tip)
                act.setToolTip(tip)
                act.triggered.connect(lambda checked=False, fn=fn, m=menu: (m.close(), fn()))
                return act
            top = row("SW3DSketchContextRelations")
            if on_entity and self.selection:
                try:
                    from . import sketch3dpm
                    offer = {kind: rel for kind, label, rel in sketch3dpm.addable(self, list(self.selection))}
                except Exception:
                    offer = {}
                for kind, tip in (("AlongX", "Make Along X"), ("AlongY", "Make Along Y"), ("AlongZ", "Make Along Z"),
                                  ("Fix", "Make Fixed")):
                    if kind in offer:
                        icon_action(top, sketch3dpm.relation_icon(kind), tip, lambda r=offer[kind]: self._add_offered(r))

            try:
                from . import rcextras
                prev = icon_action(top, rcextras._icon(rcextras.T_PREVIEW, "SKETCH_PREVIEW_DIMENSION"),
                                   rcextras.T_PREVIEW, lambda h=hit: self._preview_dimension(h))
                prev.setCheckable(True)
                prev.setChecked(rcextras.preview_on())
                prev.setObjectName("SW3DPreviewSketchDimension")
                prev.setStatusTip("Toggles preview of sketch dimension when selected")
            except Exception:
                rcextras = None
            bar = row("SW3DSketchContextTools")
            icon_action(bar, "edit-select-all", "Select Other",
                        lambda x=x, y=y: self.select_other(x, y))
            lines = [i for k, i in self.selection if k == "E" and self.ents[i].kind not in ("P", "Q")]
            cg = icon_action(bar, "Sketcher_ToggleConstruction", "Construction Geometry",
                             lambda ls=lines: self.toggle_construction(ls))
            cg.setEnabled(bool(lines))
            block = icon_action(bar, _row_icon("MakeBlock", "Make Block"), "Make Block", lambda: None)
            block.setEnabled(False)
            block.setToolTip("Make Block: blocks are made in 2D sketches")
            block.setStatusTip("Makes a new block")
            icon_action(bar, "zoom-selection", "Zoom to Selection", lambda: Gui.runCommand("Std_ViewFitSelection"))
            icon_action(bar, "Sketcher_SwitchVirtualSpace", "Replace Entity", lambda: start_tool("replace"))
            if rcextras is not None:
                num = icon_action(bar, rcextras._icon(rcextras.T_NUMERIC, "SKETCH_NUMERIC_INPUT"), rcextras.T_NUMERIC,
                                  rcextras.toggle_numeric_input)
                num.setCheckable(True)
                num.setChecked(rcextras.numeric_input_on())
                num.setStatusTip("Toggles the dynamic numeric input for sketch dimensions")
            icon_action(bar, "Constraint_Dimension", "Smart Dimension", lambda: start_tool("dimension"))
            icon_action(bar, "Sketcher_LeaveSketch", "Exit Sketch", exit_sketch)
            icon_action(bar, "PartDesign_Pad", "Extruded Boss/Base", lambda: _extrude_sketch(self.obj))
            wa = QtWidgets.QWidgetAction(menu)
            wa.setDefaultWidget(rows)
            menu.addAction(wa)
            curve = hit is not None and hit[0] == "E" and self.ents[hit[1]].kind not in ("P", "Q")
            if curve:
                item("SelectChain", "Select Chain", lambda k=hit[1]: self.select_chain(k))
                mid = self.ents[hit[1]].kind in ("L", "A")
                item("SelectMidpoint", "Select Midpoint", lambda k=hit[1]: self.select_midpoint(k), enabled=mid)
            if full:
                item("ContourSelect", "Contour Select Tool", lambda: start_tool("contourselect"))

            def sub_item(key, title):
                entries.append((key, title))
                return None if key in hidden else submenu(title)
            sel = sub_item("SelectionTools", "Selection Tools")
            if sel is not None:
                sel.addAction("Select").triggered.connect(self.select_tool)
                sel.addAction("Select Other").triggered.connect(lambda checked=False, x=x, y=y: self.select_other(x, y))
                sel.addAction("Select All").triggered.connect(self.select_all)
            zoom = sub_item("ZoomPanRotate", "Zoom/Pan/Rotate")
            if zoom is not None:
                for text, cmd in (("Zoom to Fit", "Std_ViewFitAll"), ("Zoom to Area", "Std_ViewBoxZoom"),
                                  ("Zoom In", "Std_ViewZoomIn"), ("Zoom Out", "Std_ViewZoomOut"),
                                  ("Zoom to Selection", "Std_ViewFitSelection")):
                    zoom.addAction(text).triggered.connect(lambda checked=False, c=cmd: Gui.runCommand(c))
            if full:
                views = sub_item("SetCurrentViewAs", "Set Current View As...")
                if views is not None:
                    for name in ("Front", "Back", "Top", "Bottom", "Left", "Right"):
                        cmd = "SWStyle_SetCurrentViewAs" + name
                        act = views.addAction(name)
                        act.setEnabled(cmd in Gui.listCommands())
                        act.triggered.connect(lambda checked=False, c=cmd: Gui.runCommand(c))
            recent = sub_item("RecentCommands", "Recent Commands")
            if recent is not None:
                for name in self.recent[:6]:
                    recent.addAction(TOOL_NAMES.get(name, name)).triggered.connect(
                        lambda checked=False, n=name: start_tool(n))
                recent.setEnabled(bool(self.recent))
            if full and on_entity:
                item("Sketch3DOnPlane", "3D Sketch On Plane", lambda: start_tool("sketchplane"))
            ents = sub_item("SketchEntities", "Sketch Entities")
            if ents is not None:
                for name in ENTITY_TOOLS:
                    ents.addAction(TOOL_NAMES[name]).triggered.connect(lambda checked=False, n=name: start_tool(n))
            menu.addSection("Relations")
            item("DisplayDeleteRelations", "Display/Delete Relations...", self.show_relations)
            if full:
                item("RelationsSnapsOptions", "Relations/Snaps Options...", _relations_snaps_options)

            def sketch_tools():
                tools = sub_item("SketchTools", "Sketch Tools")
                if tools is None:
                    return
                cg = tools.addAction("Construction Geometry")
                cg.setEnabled(bool(lines))
                cg.triggered.connect(lambda checked=False, ls=lines: self.toggle_construction(ls))
                tools.addAction("Smart Dimension").triggered.connect(lambda: start_tool("dimension"))
                for name in ("fillet", "chamfer", "offsetonsurface", "convert", "intersection", "facecurves",
                             "segment", "trim", "extend", "split", "jogline", "mirror", "move", "rotate", "copy",
                             "replace", "fitspline"):
                    tools.addAction(TOOL_NAMES[name]).triggered.connect(lambda checked=False, n=name: start_tool(n))
                tools.addAction("Repair Sketch").triggered.connect(lambda: repair_now())

            def triad():
                entries.append(("ShowTriad", "Show Sketcher Triad"))
                if "ShowTriad" in hidden:
                    return
                act = menu.addAction("Show Sketcher Triad")
                act.setProperty("swKey", "ShowTriad")
                act.setCheckable(True)
                act.setChecked(self.show_triad)
                act.setEnabled(bool(self.selection) or self.show_triad)
                act.toggled.connect(self.set_triad)
            if on_entity:
                try:
                    from . import sketch3dpm
                    name = sketch3dpm.entity_name(self, hit)
                except Exception:
                    name = ""
                menu.addSection("Selected Entity (%s)" % name if name else "Selected Entity")
                item("Delete", "Delete", self.delete_selection)
                if hit[0] == "E" and self.ents[hit[1]].kind == "S":
                    # the spline's own items
                    item("InsertSplinePoint", "Insert Spline Point", lambda: start_tool("insertsplinepoint"))
                    if spline_style(self.ents[hit[1]], self.rels):
                        item("ConvertToSpline", "Convert to Spline", lambda k=hit[1]: self.convert_to_spline(k))
                    else:
                        item("AddTangencyControl", "Add Tangency Control", lambda: start_tool("addtangency"))
                        item("AddCurvatureControl", "Add Curvature Control", lambda: start_tool("addcurvature"))
                        item("ConvertToStyleSpline", "Convert to Style Spline",
                             lambda k=hit[1]: self.convert_to_style(k))
                    item("RelaxSpline", "Relax Spline",
                         lambda k=hit[1]: self.reset_handles(k, keep_directions=True, name="Relax Spline"))
                if hit[0] == "P" and self.picked_spline_end() is not None:
                    item("ReverseEndpointTangent", "Flip Endpoint Tangent", lambda: self.reverse_end_tangent())
                triad()
                sketch_tools()
            else:
                sketch_tools()
                triad()
            kind = "entity" if on_entity else "space"
            if full:
                choices = list(entries)
                a = menu.addAction("Customize Menu")
                a.setProperty("swKey", "Customize")
                a.triggered.connect(lambda checked=False, c=choices: QtCore.QTimer.singleShot(
                    0, lambda: _customize_menu(c)))
            else:
                try:
                    from . import fmmenu
                    chevron = fmmenu._Chevron(menu, lambda: self._reopen_full(menu, (gpos, x, y)))
                    chevron.button.setObjectName("SW3DSketchMenuChevron")
                    menu.addAction(chevron)
                except Exception:
                    a = menu.addAction("\u2304")
                    a.setObjectName("SW3DSketchMenuChevron")
                    a.setToolTip("Show the full menu")
                    a.triggered.connect(lambda checked=False: self._reopen_full(menu, (gpos, x, y)))
            menu.setProperty("swKind", kind)
            menu.popup(gpos)
            self._menu, self._menu_keep = menu, keep

        QUICK_SNAPS_3D = (("Point", "Point Snap"), ("CenterPoint", "Center Point Snap"),
                          ("Midpoint", "Midpoint Snap"), ("Nearest", "Nearest Snap"),
                          ("HV", "Along X/Y/Z Snap"))

        def _tool_menu(self, event, full=False, at=None):
            ""





            tool = self.tool
            menu = QtWidgets.QMenu(Gui.getMainWindow())
            menu.setObjectName("SW3DSketchToolMenu")
            menu.setProperty("swFull", bool(full))
            gpos = at[0] if at is not None else self._global(event)
            x, y = (at[1], at[2]) if at is not None else self.cursor()
            hidden = _menu_hidden()
            entries = []
            keep = [menu]

            def item(key, label, fn=None, parent=None, enabled=True):
                entries.append((key, label))
                if key in hidden:
                    return None
                act = (parent or menu).addAction(label)
                act.setProperty("swKey", key)
                act.setEnabled(bool(enabled))
                if fn is not None:
                    act.triggered.connect(lambda checked=False, fn=fn: fn())
                return act

            def sub_item(key, title):
                entries.append((key, title))
                if key in hidden:
                    return None
                sub = QtWidgets.QMenu(title, menu)
                menu.addMenu(sub)
                keep.append(sub)
                return sub
            rows = QtWidgets.QWidget(menu)
            rows.setObjectName("SW3DSketchContextBar")
            lay = QtWidgets.QVBoxLayout(rows)
            lay.setContentsMargins(4, 2, 4, 2)
            lay.setSpacing(0)

            def row(name):
                bar = QtWidgets.QToolBar(rows)
                bar.setObjectName(name)
                bar.setIconSize(QtCore.QSize(16, 16))
                lay.addWidget(bar)
                return bar

            def icon_action(bar, icon, tip, fn, status=None):
                act = bar.addAction(icon if isinstance(icon, QtGui.QIcon) else _command_icon(icon), tip)
                act.setToolTip(tip)
                if status:
                    act.setStatusTip(status)
                act.triggered.connect(lambda checked=False, fn=fn, m=menu: (m.close(), fn()))
                return act
            from . import sketch3dpm
            top = row("SW3DSketchContextRelations")
            if isinstance(tool, LineTool):
                for kind, tip in (("AlongX", "Make Along X"), ("AlongY", "Make Along Y"), ("AlongZ", "Make Along Z")):
                    icon_action(top, sketch3dpm.relation_icon(kind), tip,
                                lambda k=kind: (setattr(tool, "force", k), tool.move(*self.cursor())))
            icon_action(top, sketch3dpm.relation_icon("Fix"), "Make Fixed", lambda: setattr(tool, "fix_first", True))
            try:
                from . import rcextras
                prev = icon_action(top, rcextras._icon(rcextras.T_PREVIEW, "SKETCH_PREVIEW_DIMENSION"),
                                   rcextras.T_PREVIEW, lambda: rcextras.toggle_preview(),
                                   "Toggles preview of sketch dimension when selected")
                prev.setCheckable(True)
                prev.setChecked(rcextras.preview_on())
            except Exception as _fw_err:
                _fw_log("sketch3d.py:3502", _fw_err)
            bar = row("SW3DSketchContextTools")
            icon_action(bar, "edit-select-all", "Select Other", lambda: self.select_other(x, y))
            cg = icon_action(bar, "Sketcher_ToggleConstruction", "Construction Geometry",
                             lambda: setattr(tool, "construction", not tool.construction))
            cg.setCheckable(True)
            cg.setChecked(bool(tool.construction))
            block = icon_action(bar, _row_icon("MakeBlock", "Make Block"), "Make Block", lambda: None,
                                "Makes a new block")
            block.setEnabled(False)
            icon_action(bar, "zoom-selection", "Zoom to Selection", lambda: Gui.runCommand("Std_ViewFitSelection"))
            icon_action(bar, "Sketcher_SwitchVirtualSpace", "Replace Entity", lambda: start_tool("replace"))
            icon_action(bar, "Constraint_Dimension", "Smart Dimension", lambda: start_tool("dimension"))
            icon_action(bar, "Sketcher_LeaveSketch", "Exit Sketch", exit_sketch)
            if isinstance(tool, SplineTool):
                icon_action(bar, "PartDesign_Pad", "Extruded Boss/Base",
                            lambda: (tool.end(), _extrude_sketch(self.obj)))
            if isinstance(tool, LineTool) and tool.chain and tool.prev() is not None and self.cursor_pos is not None:

                readout = QtWidgets.QLabel(_fmt(_len(_sub(self.cursor_pos, tool.prev()))), rows)
                readout.setObjectName("SW3DToolMenuLength")
                readout.setContentsMargins(4, 2, 4, 2)
                lay.addWidget(readout)
            wa = QtWidgets.QWidgetAction(menu)
            wa.setDefaultWidget(rows)
            menu.addAction(wa)
            item("Select", "Select", lambda: tool.end())
            ents = sub_item("SketchEntities", "Sketch Entities")
            if ents is not None:
                for name in ENTITY_TOOLS:
                    ents.addAction(TOOL_NAMES[name]).triggered.connect(lambda checked=False, n=name: start_tool(n))
            recent = sub_item("RecentCommands", "Recent Commands")
            if recent is not None:
                for name in self.recent[:6]:
                    recent.addAction(TOOL_NAMES.get(name, name)).triggered.connect(
                        lambda checked=False, n=name: start_tool(n))
                recent.setEnabled(bool(self.recent))
            menu.addSection("Selected Entity")
            if full:
                item("RelationsSnapsOptions", "Relations/Snaps Options...", _relations_snaps_options)
            snaps = sub_item("QuickSnaps", "Quick Snaps")
            if snaps is not None:
                snaps.setObjectName("SW3DQuickSnaps")
                for key, label in self.QUICK_SNAPS_3D:
                    act = snaps.addAction(label)
                    act.setCheckable(True)
                    act.setChecked(self.quick_snap == key)
                    act.setProperty("swKey", key)
                    act.triggered.connect(lambda checked=False, k=key: self.set_quick_snap(k))
            if full:
                choices = list(entries)
                a = menu.addAction("Customize Menu")
                a.setProperty("swKey", "Customize")
                a.triggered.connect(lambda checked=False, c=choices: QtCore.QTimer.singleShot(
                    0, lambda: _customize_menu(c)))
            else:
                try:
                    from . import fmmenu
                    chevron = fmmenu._Chevron(menu, lambda: self._reopen_tool_menu(menu, (gpos, x, y)))
                    chevron.button.setObjectName("SW3DSketchMenuChevron")
                    menu.addAction(chevron)
                except Exception:
                    a = menu.addAction("\u2304")
                    a.setObjectName("SW3DSketchMenuChevron")
                    a.triggered.connect(lambda checked=False: self._reopen_tool_menu(menu, (gpos, x, y)))
            menu.setProperty("swKind", "tool")
            menu.popup(gpos)
            self._menu, self._menu_keep = menu, keep

        def _reopen_tool_menu(self, menu, at):
            menu.close()
            QtCore.QTimer.singleShot(0, lambda: self._tool_menu(None, full=True, at=at))

        def set_quick_snap(self, key):
            """Quick Snaps: only that kind of snap for the next entity (again: all snaps back)."""
            self.quick_snap = None if self.quick_snap == key else key
            if self.tool is not None:
                self.tool.move(*self.cursor())

        def _preview_dimension(self, hit):
            """Preview Sketch Dimension: on or off (System Options > Sketch), and the picked line's length
            shown at once."""
            from . import rcextras
            on = rcextras.toggle_preview()
            if not on or hit is None or hit[0] != "E" or self.ents[hit[1]].kind != "L":
                return None
            ia, ib = self.ents[hit[1]].points
            a, b = self.pts[ia], self.pts[ib]
            text = rcextras.length_text(sum((b[c] - a[c]) ** 2 for c in range(3)) ** 0.5)
            QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), text)
            return text

        def _reopen_full(self, menu, at):
            """The chevron: the same menu again, full."""
            menu.close()
            QtCore.QTimer.singleShot(0, lambda: self._context_menu(None, full=True, at=at))

        def select_midpoint(self, k):
            """Select Midpoint: the midpoint of line or arc k, picked (a construction point held there by a
            Midpoint relation, which relations and dimensions can then use)."""
            e = self.ents[k]
            if e.kind not in ("L", "A"):
                return
            pts, ents, rels = list(self.pts), list(self.ents), list(self.rels)
            if e.kind == "L":
                a, b = e.points
                q = _mul(_add(pts[a], pts[b]), 0.5)
                have = [r.points[0] for r in rels if r.kind == "Midpoint" and set(r.points[1:]) == {a, b}]
            else:
                rd = _round_of(e, pts, rels)
                q = _at_angle(rd, rd[5] / 2.0)
                have = [r.points[0] for r in rels if r.kind == "ArcMidpoint" and r.points[1:] == e.points]
            if have:
                self.select([("P", have[0])])
                return
            pts.append(q)
            i = len(pts) - 1
            ents.append(S.Entity("P", [i], True))
            if e.kind == "L":
                rels.append(S.Relation("Midpoint", [i, a, b]))
            else:
                rels.append(S.Relation("ArcMidpoint", [i] + list(e.points), list(rd[4])))
            self.write("Select Midpoint", pts, ents, rels, solve_first=False)
            self.select([("P", i)])

        def _add_offered(self, rel):
            """A relation from the right-click icon row (as Add Relations offers it)."""
            if type(rel).__name__ == "_FixAll":
                free = [p for p in rel.points if p not in self.fixed]
                rel = [S.Relation("Fix", [p], list(self.pts[p])) for p in free]
                if not rel:
                    return
            why = self.add_relation(rel)
            if why:
                self.status(why)

        def select_tool(self):
            if self.tool is not None:
                self.tool.end()

        def select_all(self):
            self.select_tool()
            self.select([("E", k) for k in range(len(self.ents))])

        def show_relations(self):
            """Display/Delete Relations: the picked items' relations (all of the sketch's when nothing is
            picked) in the PropertyManager, where Delete takes one out."""
            self.select_tool()
            if not self.selection:
                self.select_all()
            else:
                self._selection_changed()

        def toggle_construction(self, items):
            if not items:
                return
            on = not all(self.ents[i].construction for i in items)
            ents = [S.Entity(x.kind, x.points, on if k in items else x.construction) for k, x in enumerate(self.ents)]
            self.write("Construction Geometry", self.pts, ents, self.rels, solve_first=False)

        def set_triad(self, on):
            self.show_triad = bool(on)
            self.redraw()


MENU_PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Sketch3D"


def _menu_hidden():
    """The right-click entries Customize Menu has hidden."""
    try:
        return {k for k in App.ParamGet(MENU_PARAMS).GetString("MenuHidden", "").split(",") if k}
    except Exception:
        return set()


def _customize_menu(entries, run=True):
    ""
    try:
        from . import fmmenu
        box = fmmenu.CustomizeDialog("sketch3d", entries)
    except Exception:
        return None
    # the boxes the menu shows: hidden ones from our own parameter
    hidden = _menu_hidden()
    for i in range(box.list.count()):
        it = box.list.item(i)
        it.setCheckState(QtCore.Qt.Unchecked if it.data(QtCore.Qt.UserRole) in hidden else QtCore.Qt.Checked)

    def apply(b):
        off = [b.list.item(i).data(QtCore.Qt.UserRole) for i in range(b.list.count())
               if b.list.item(i).checkState() != QtCore.Qt.Checked]
        App.ParamGet(MENU_PARAMS).SetString("MenuHidden", ",".join(off))
    if not run:
        return box, apply
    return fmmenu._run_dialog(box, apply)


def _extrude_sketch(obj):
    """Extruded Boss/Base from the right-click icon row: the 3D sketch is closed (kept) and extruded, as the
    Features tab's button does with a sketch picked (a closed, flat 3D sketch extrudes; FreeCAD says why not
    otherwise)."""
    exit_sketch()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj)
    try:
        from . import catalog
        natives = catalog.BY_KEY["BossExtrude"].natives
    except Exception:
        natives = ("PartDesign_Pad",)
    name = next((n for n in natives if n in Gui.listCommands()), None)
    if name:
        Gui.runCommand(name)


INK_PROP = "FreeWorksInk3D"


def _load_ink(obj):
    import json
    try:
        return [[tuple(float(v) for v in p) for p in s] for s in json.loads(getattr(obj, INK_PROP, "") or "[]")]
    except Exception:
        return []


def _save_ink(obj, strokes):
    import json
    if not hasattr(obj, INK_PROP):
        obj.addProperty("App::PropertyString", INK_PROP, "FreeCAD", "Pen Sketch ink, not yet converted")
        try:
            obj.setEditorMode(INK_PROP, 2)
        except Exception as _fw_err:
            _fw_log("sketch3d.py:3735", _fw_err)
    setattr(obj, INK_PROP, json.dumps([[[round(v, 6) for v in p] for p in s] for s in strokes]))


def _rdp3(points, eps):
    if len(points) < 3:
        return list(points)
    a, b = points[0], points[-1]
    u = _sub(b, a)
    L = _len(u)
    worst, k = -1.0, 0
    for i in range(1, len(points) - 1):
        d = _len(_cross(_sub(points[i], a), _unit(u))) if L > 1e-12 else math.dist(points[i], a)
        if d > worst:
            worst, k = d, i
    if worst <= eps:
        return [a, b]
    return _rdp3(points[:k + 1], eps)[:-1] + _rdp3(points[k:], eps)


def _stroke_entities(stroke, as_shapes, pts, ents):
    """A Pen stroke as 3D sketch entities appended to pts/ents: a nearly straight one a line; with as_shapes a
    stroke with corners lines joined end to end; else a spline through it (closed when its ends meet)."""
    L = sum(math.dist(a, b) for a, b in zip(stroke[:-1], stroke[1:]))
    if len(stroke) < 2 or L < 1e-6:
        return []
    a, b = stroke[0], stroke[-1]
    chord = math.dist(a, b)
    closed = chord <= 0.12 * L and len(stroke) > 3
    if chord > 1e-9 and max(_len(_cross(_sub(p, a), _unit(_sub(b, a)))) for p in stroke) <= 0.02 * L:
        pts += [tuple(a), tuple(b)]
        ents.append(S.Entity("L", [len(pts) - 2, len(pts) - 1]))
        return [len(ents) - 1]
    if as_shapes:
        corners = _rdp3(stroke, 0.04 * L)
        if 3 <= len(corners) <= 13:
            # straight between the corners (within the stroke's wobble)? then lines
            straight = True
            for c0, c1 in zip(corners[:-1], corners[1:]):
                if math.dist(c0, c1) < 0.03 * L:
                    straight = False
            if straight:
                if closed:
                    corners[-1] = corners[0]
                idx = []
                for c in (corners[:-1] if closed else corners):
                    pts.append(tuple(c))
                    idx.append(len(pts) - 1)
                if closed:
                    idx.append(idx[0])
                out = []
                for i, j in zip(idx[:-1], idx[1:]):
                    ents.append(S.Entity("L", [i, j]))
                    out.append(len(ents) - 1)
                return out
    n = 12
    keep, walked, step = [stroke[0]], 0.0, L / (n - 1.0)
    target = step
    for p, q in zip(stroke[:-1], stroke[1:]):
        d = math.dist(p, q)
        while d > 1e-12 and walked + d >= target - 1e-12 and len(keep) < n - 1:
            f = (target - walked) / d
            keep.append(tuple(p[i] + (q[i] - p[i]) * f for i in range(3)))
            target += step
        walked += d
    if not closed:
        keep.append(tuple(stroke[-1]))
    idx = []
    for p in keep:
        pts.append(tuple(p))
        idx.append(len(pts) - 1)
    if closed:
        idx.append(idx[0])
    ents.append(S.Entity("S", idx))
    return [len(ents) - 1]


def extrude_3d(cut=False):
    """2D to 3D > Extrude... / Cut... in a 3D sketch: the sketch closed (kept) and Extruded Boss/Base or
    Extruded Cut started on it (a closed, flat 3D sketch extrudes; FreeCAD says why not otherwise)."""
    obj = editing()
    if obj is None:
        return
    if not cut:
        _extrude_sketch(obj)
        return
    exit_sketch()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj)
    try:
        from . import catalog
        natives = tuple(catalog.BY_KEY["CutExtrude"].natives)
    except Exception:
        natives = ()
    name = next((n for n in natives + ("PartDesign_Pocket",) if n in Gui.listCommands()), None)
    if name:
        Gui.runCommand(name)


def align_view_to_line(s):
    """Align > Sketch in a 3D sketch: the view turned so the picked line runs straight across the screen, seen
    square to the sketch plane it lies on (else square to the line); False with no line picked."""
    k = next((i for kind, i in s.selection if kind == "E" and s.ents[i].kind == "L"), None)
    if k is None:
        s.status("Align Sketch: pick a line to line the view up with.")
        return False
    a, b = (s.pts[i] for i in s.ents[k].points[:2])
    x = _unit(_sub(b, a))
    try:
        view = Gui.ActiveDocument.ActiveView
        d = view.getViewDirection()
        d = (d.x, d.y, d.z)
    except Exception as _fw_err:
        _fw_log("sketch3d.py:3860", _fw_err)
        return False
    n = _sub(d, _mul(x, _dot(d, x)))          # the view direction made square to the line
    if _len(n) < 1e-9:
        n = (0.0, 0.0, -1.0) if abs(x[2]) < 0.9 else (0.0, -1.0, 0.0)
    back = _unit(_mul(n, -1.0))               # the camera's z: towards the viewer
    y = _cross(back, x)
    rot = App.Rotation(App.Vector(*x), App.Vector(*y), App.Vector(*back), "ZXY")
    view.setCameraOrientation(rot)
    view.fitAll()
    s.status("Align Sketch: the view runs along the picked line.")
    return True


def _relations_snaps_options():
    """Relations/Snaps Options...: the Options box on System Options > Relations/Snaps."""
    try:
        from . import options
        box = options.OptionsDialog(tab=0)
        box.select("Relations/Snaps")
        options._open.append(box)
        try:
            box.exec()
        finally:
            options._open.remove(box)
            box.deleteLater()
    except Exception:
        Gui.runCommand("Std_DlgPreferences", 0)


def _row_icon(key, label):
    ""
    try:
        from . import shell as shell_module
        icon = shell_module.shell().binding(key).icon()
        if icon is not None and not icon.isNull():
            return icon
    except Exception as _fw_err:
        _fw_log("sketch3d.py:3885", _fw_err)
    try:
        from . import icons
        return icons.initials(label)
    except Exception:
        return QtGui.QIcon()


def _command_icon(name):
    try:
        return QtGui.QIcon(Gui.getIcon(name)) if hasattr(Gui, "getIcon") else QtGui.QIcon(":/icons/%s.svg" % name)
    except Exception:
        return QtGui.QIcon(":/icons/%s.svg" % name)



# kind: (glyph, where), where a point index in the relation, the middle of two, or a list of those
# (a glyph on each entity); "ends" a Curve Length's two entities
GLYPHS = {"AlongX": ("SW_AlongX", (0, 1)), "AlongY": ("SW_AlongY", (0, 1)), "AlongZ": ("SW_AlongZ", (0, 1)),
          "Fix": ("Constraint_Block", 0), "Coincident": ("Constraint_PointOnObject", 0),
          "OnLine": ("Constraint_PointOnObject", 0), "OnArc": ("Constraint_PointOnObject", 2),
          "OnEdge": ("Constraint_PointOnObject", 0), "AtRef": ("Constraint_PointOnObject", 0),
          "OnPlane": ("SW_OnPlane", 0), "OnSketchPlane": ("SW_OnPlane", 0), "OnSurface": ("SW_OnSurface", 0),
          "Midpoint": ("SW_Midpoint", 0), "ArcMidpoint": ("SW_Midpoint", 0),
          "Parallel": ("Constraint_Parallel", [(0, 1), (2, 3)]),
          "Perpendicular": ("Constraint_Perpendicular", [(0, 1), (2, 3)]),
          "Equal": ("Constraint_EqualLength", [(0, 1), (2, 3)]),
          "Collinear": ("SW_Collinear", [(0, 1), (2, 3)]), "PlaneParallel": ("Constraint_Parallel", (0, 1)),
          "PlaneNormal": ("SW_Normal", (0, 1)), "ParallelYZ": ("SW_ParallelYZ", (0, 1)),
          "ParallelZX": ("SW_ParallelZX", (0, 1)), "PlaneH": ("Constraint_Horizontal", (0, 1)),
          "PlaneV": ("Constraint_Vertical", (0, 1)), "AlongDirH": ("Constraint_Horizontal", (0, 1)),
          "AlongDirV": ("Constraint_Vertical", (0, 1)), "SymPlane": ("Constraint_Symmetric", (0, 1)),
          "Tangent": ("Constraint_Tangent", 1), "TangentArcs": ("Constraint_Tangent", 1),
          "SplineTangent": ("Constraint_Tangent", 0), "SplineTangentArc": ("Constraint_Tangent", 0),
          "SplineTangentSpline": ("Constraint_Tangent", 0), "Concentric": ("SW_Concentric", 0),
          "Coradial": ("SW_Coradial", 0), "CurveLength": ("SW_EqualCurve", "ends")}
GLYPH_SIDE = 15          # pixels, as FreeCAD's default glyph size


def glyph_anchors(r, pts):
    """Where relation r's glyphs go: a list of points (one per entity it ties)."""
    got = GLYPHS.get(r.kind)
    if got is None:
        return []
    where = got[1]
    if where == "ends":
        n = int(r.values[0]) if r.values else 0
        a, b = r.points[:n], r.points[n:]
        where = [(0, n - 1)] + ([(n, len(r.points) - 1)] if b else []) if a else []
    out = []
    for w in where if isinstance(where, list) else [where]:
        try:
            out.append(tuple(pts[r.points[w]]) if isinstance(w, int) else
                       _mul(_add(pts[r.points[w[0]]], pts[r.points[w[1]]]), 0.5))
        except (IndexError, TypeError) as _fw_err:
            _fw_log("sketch3d.py:3940", _fw_err)
    return out


def _symbol3d(p, key, u):
    """The 3D sketch's own glyph symbols (fwsketch.glyphs draws the 2D ones) on a 16-unit square."""
    def line(x1, y1, x2, y2):
        p.drawLine(QtCore.QPointF(x1 * u, y1 * u), QtCore.QPointF(x2 * u, y2 * u))

    def ring(cx, cy, r):
        p.drawEllipse(QtCore.QPointF(cx * u, cy * u), r * u, r * u)
    if key in ("SW_AlongX", "SW_AlongY", "SW_AlongZ", "SW_ParallelYZ", "SW_ParallelZX"):
        font = QtGui.QFont()
        font.setPixelSize(max(6, int(8 * u)))
        font.setBold(True)
        p.setFont(font)
        text = {"SW_AlongX": "X", "SW_AlongY": "Y", "SW_AlongZ": "Z", "SW_ParallelYZ": "YZ",
                "SW_ParallelZX": "ZX"}[key]
        if key.startswith("SW_Along"):
            line(2, 13, 14, 13)
        else:
            line(2, 12, 7, 15)
            line(9, 12, 14, 15)
        p.drawText(QtCore.QRectF(0, 0, 16 * u, 11.5 * u), QtCore.Qt.AlignCenter, text)
    elif key == "SW_OnPlane":
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x * u, y * u) for x, y in ((5, 4), (14, 4), (11, 12), (2, 12))]))
        ring(8, 8, 1.2)
    elif key == "SW_OnSurface":
        p.drawArc(QtCore.QRectF(2 * u, 5 * u, 12 * u, 12 * u), 20 * 16, 140 * 16)
        ring(8, 5.5, 1.5)
    elif key == "SW_Normal":
        line(3, 12, 13, 12)
        line(8, 12, 8, 2.5)
        line(6, 5, 8, 2.5)
        line(10, 5, 8, 2.5)
    elif key == "SW_Concentric":
        ring(8, 8, 5.5)
        ring(8, 8, 2.5)
    elif key == "SW_Coradial":
        ring(8, 8, 5.5)
        line(8, 8, 12, 4)
    elif key == "SW_Collinear":
        line(1.5, 14.5, 6.5, 9.5)
        line(9.5, 6.5, 14.5, 1.5)
    elif key == "SW_EqualCurve":
        p.drawArc(QtCore.QRectF(2 * u, 3 * u, 12 * u, 8 * u), 20 * 16, 140 * 16)
        line(4, 10, 12, 10)
        line(4, 13, 12, 13)
    else:
        return False
    return True


def glyph_image(keys, colour, side=GLYPH_SIDE):
    """A row of glyph squares (one per key) in colour, each symbol cut out, as FreeCAD fills the 2D
    sketch's: a QImage, or None."""
    keys = list(keys)
    if not keys or not GUI:
        return None
    try:
        from .fwsketch import glyphs as G2
    except Exception:
        G2 = None
    gap = 2
    image = QtGui.QImage(len(keys) * (side + gap) - gap, side, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(image)
    p.setRenderHint(QtGui.QPainter.Antialiasing, False)     # crisp, as FreeCAD's glyphs
    fill = QtGui.QColor.fromRgbF(*colour)
    u = side / 16.0
    for k, key in enumerate(keys):
        p.save()
        p.translate(k * (side + gap), 0)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        p.fillRect(QtCore.QRectF(0, 0, side, side), fill)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), max(1.0, 1.4 * u), QtCore.Qt.SolidLine, QtCore.Qt.FlatCap,
                            QtCore.Qt.MiterJoin))
        p.setBrush(QtCore.Qt.NoBrush)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
        if not (G2 is not None and G2._symbol(p, key, u)):
            _symbol3d(p, key, u)
        p.restore()
    p.end()
    return image


ENTITY_TOOLS = ("line", "centerline", "midpointline", "spline", "stylespline", "splineonsurface", "equation", "point",
                "circle",
                "perimetercircle", "centerarc",
                "tangentarc", "arc3", "rectangle", "centerrectangle", "rect3corner", "rect3center", "parallelogram",
                "sketchplane")
TOOL_NAMES = {"line": "Line", "centerline": "Centerline", "midpointline": "Midpoint Line", "spline": "Spline",
              "point": "Point", "circle": "Circle", "centerarc": "Centerpoint Arc", "arc3": "3 Point Arc",
              "rectangle": "Corner Rectangle", "centerrectangle": "Center Rectangle", "dimension": "Smart Dimension",
              "perimetercircle": "Perimeter Circle", "tangentarc": "Tangent Arc",
              "rect3corner": "3 Point Corner Rectangle", "rect3center": "3 Point Center Rectangle",
              "parallelogram": "Parallelogram", "trim": "Trim Entities",
              "convert": "Convert Entities", "mirror": "Mirror Entities", "fillet": "Sketch Fillet",
              "intersection": "Intersection Curve", "facecurves": "Face Curves",
              "splineonsurface": "Spline on Surface", "offsetonsurface": "Offset on Surface",
              "insertsplinepoint": "Insert Spline Point", "equation": "Equation Driven Curve",
              "move": "Move Entities", "copy": "Copy Entities",
              "rotate": "Rotate Entities", "sketchplane": "Plane", "chamfer": "Sketch Chamfer",
              "extend": "Extend Entities", "split": "Split Entities", "segment": "Segment",
              "routeline": "Route Line", "pen": "Pen Sketch", "fitspline": "Fit Spline", "jogline": "Jog Line", "replace": "Replace Entity",
              "contourselect": "Contour Select Tool", "stylespline": "Style Spline",
              "simplifyspline": "Simplify Spline", "insertcontrolvertex": "Insert Control Vertex",
              "addtangency": "Add Tangency Control", "addcurvature": "Add Curvature Control"}


# =================================================================== trim, convert, mirror
def _seg_closest(p1, q1, p2, q2):
    """(distance, s, t) of the closest points p1 + s (q1 - p1) and p2 + t (q2 - p2), s and t in 0..1."""
    d1, d2, r = _sub(q1, p1), _sub(q2, p2), _sub(p1, p2)
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    if a < 1e-18 and e < 1e-18:
        return _len(r), 0.0, 0.0
    if a < 1e-18:
        sp, t = 0.0, max(0.0, min(1.0, f / e))
    else:
        c = _dot(d1, r)
        if e < 1e-18:
            t, sp = 0.0, max(0.0, min(1.0, -c / a))
        else:
            b = _dot(d1, d2)
            den = a * e - b * b
            sp = max(0.0, min(1.0, (b * f - c * e) / den)) if den > 1e-18 else 0.0
            t = (b * sp + f) / e
            if t < 0.0:
                t, sp = 0.0, max(0.0, min(1.0, -c / a))
            elif t > 1.0:
                t, sp = 1.0, max(0.0, min(1.0, (b - c) / a))
    w = _sub(_add(p1, _mul(d1, sp)), _add(p2, _mul(d2, t)))
    return _len(w), sp, t


def _round_of(e, pts, rels):
    """(centre, radius, u, v, normal, sweep) of a circle or arc entity; angles count from its first rim point."""
    n = arc_normal(e, rels)
    c, a = pts[e.points[0]], pts[e.points[1]]
    r, u, v = arc_frame(c, a, n)
    sweep = 2 * math.pi if e.kind == "C" else arc_sweep(c, a, pts[e.points[2]], n)
    return c, r, u, v, n, sweep


def _angle_on(rd, p):
    c, r, u, v, n, sweep = rd
    d = _sub(p, c)
    return math.atan2(_dot(d, v), _dot(d, u)) % (2 * math.pi)


def _at_angle(rd, t):
    c, r, u, v, n, sweep = rd
    return _add(c, _add(_mul(u, r * math.cos(t)), _mul(v, r * math.sin(t))))


def _line_round(a, b, rd, tol):
    """Where segment a b meets a circle (its plane, its rim): [(s on the segment, point)]."""
    c, r, u, v, n, sweep = rd
    d = _sub(b, a)
    out = []
    dn, an = _dot(d, n), _dot(_sub(a, c), n)
    if abs(dn) > 1e-12 * max(1.0, _len(d)):
        s = -an / dn
        p = _add(a, _mul(d, s))
        if -1e-9 <= s <= 1 + 1e-9 and abs(_len(_sub(p, c)) - r) < tol:
            out.append((s, p))
        return out
    if abs(an) > tol:
        return out
    w = _sub(a, c)
    qa, qb, qc = _dot(d, d), 2 * _dot(w, d), _dot(w, w) - r * r
    disc = qb * qb - 4 * qa * qc
    if qa < 1e-18 or disc < -tol:
        return out
    root = math.sqrt(max(disc, 0.0))
    for s in ((-qb - root) / (2 * qa), (-qb + root) / (2 * qa)):
        if -1e-9 <= s <= 1 + 1e-9:
            out.append((s, _add(a, _mul(d, s))))
    return out


def _round_round(r1, r2, tol):
    """Where two circles on one plane meet."""
    c1, ra, u, v, n1, _ = r1
    c2, rb, _, _, n2, _ = r2
    cr = (n1[1] * n2[2] - n1[2] * n2[1], n1[2] * n2[0] - n1[0] * n2[2], n1[0] * n2[1] - n1[1] * n2[0])
    if _len(cr) > 1e-9 or abs(_dot(_sub(c2, c1), n1)) > tol:
        return []
    d = _len(_sub(c2, c1))
    if d < 1e-12 or d > ra + rb + tol or d < abs(ra - rb) - tol:
        return []
    x = (d * d + ra * ra - rb * rb) / (2 * d)
    h = math.sqrt(max(ra * ra - x * x, 0.0))
    e = _mul(_sub(c2, c1), 1.0 / d)
    w = (n1[1] * e[2] - n1[2] * e[1], n1[2] * e[0] - n1[0] * e[2], n1[0] * e[1] - n1[1] * e[0])
    base = _add(c1, _mul(e, x))
    return [_add(base, _mul(w, h)), _sub(base, _mul(w, h))] if h > tol else [base]


def _crossings(s, k, tol):
    """[(parameter on entity k, point, relation maker)]: where the other entities cross it in space. The
    parameter is 0..1 along a line, the angle from the first rim point on a circle or arc."""
    e, pts, rels = s.ents[k], s.pts, s.rels
    out = []
    mine = _round_of(e, pts, rels) if e.kind in ("C", "A") else None

    def keep(param, p, make):
        if e.kind == "L" and not (1e-7 < param < 1 - 1e-7):
            return
        if e.kind == "A" and not (1e-7 < param < mine[5] - 1e-7):
            return
        out.append((param, p, make))
    for j, f in enumerate(s.ents):
        if j == k or f.kind == "P":
            continue
        if f.kind == "L":
            fa, fb = f.points
            make = (lambda i, fa=fa, fb=fb: S.Relation("OnLine", [i, fa, fb]))
        elif f.kind in ("C", "A"):
            rd_f = _round_of(f, pts, rels)
            make = (lambda i, f=f, n=rd_f[4]: S.Relation("OnArc", [f.points[0], f.points[1], i], list(n)))
        else:
            make = (lambda i: None)
        if f.kind in ("C", "A"):
            if e.kind == "L":
                a, b = pts[e.points[0]], pts[e.points[1]]
                for sp, p in _line_round(a, b, rd_f, tol):
                    if f.kind == "A" and _angle_on(rd_f, p) > rd_f[5] + 1e-9:
                        continue
                    keep(sp, p, make)
            elif mine is not None:
                for p in _round_round(mine, rd_f, tol):
                    if f.kind == "A" and _angle_on(rd_f, p) > rd_f[5] + 1e-9:
                        continue
                    keep(_angle_on(mine, p), p, make)
            continue
        line = s.polyline(f) if f.kind != "L" else [pts[f.points[0]], pts[f.points[1]]]
        for p2, q2 in zip(line[:-1], line[1:]):
            if e.kind == "L":
                a, b = pts[e.points[0]], pts[e.points[1]]
                d, sp, t = _seg_closest(a, b, p2, q2)
                if d < tol:
                    keep(sp, _add(a, _mul(_sub(b, a), sp)), make)
            elif mine is not None:
                for sp, p in _line_round(p2, q2, mine, tol):
                    keep(_angle_on(mine, p), p, make)
    # one crossing seen twice (a polyline joint): keep one
    out.sort(key=lambda c: c[0])
    clean = []
    for c in out:
        if not clean or abs(c[0] - clean[-1][0]) > 1e-7:
            clean.append(c)
    return clean


# a line's own direction relations (the line is points[:2]): they go with each piece of it
LINE_OWN = ("PlaneH", "PlaneV", "AlongDirH", "AlongDirV", "PlaneNormal", "PlaneParallel", "ParallelYZ", "ParallelZX")


def _line_pair_relations(rels, a, b, pieces):
    """The relations of line (a b) carried onto the pieces left after a trim (Along X/Y/Z on each,
    Parallel, Perpendicular, Equal, Angle and Coincident on the first); its length dimension goes."""
    out = []
    first = pieces[0] if pieces else None
    for r in rels:
        p = r.points
        if r.kind in S.ALONG + LINE_OWN and set(p[:2]) == {a, b}:
            out += [S.Relation(r.kind, list(x) + p[2:], r.values, r.ref) for x in pieces]
            continue
        if r.kind in ("Tangent", "SplineTangent") and {p[2], p[3]} == {a, b}:
            if first is None:
                continue
            r = S.Relation(r.kind, p[:2] + list(first), r.values)
        elif r.kind in S.TWO_LINE + ("Angle", "Collinear"):
            if {p[0], p[1]} == {a, b}:
                if first is None:
                    continue
                r = S.Relation(r.kind, list(first) + p[2:], r.values, r.ref)
            elif {p[2], p[3]} == {a, b}:
                if first is None:
                    continue
                r = S.Relation(r.kind, p[:2] + list(first), r.values, r.ref)
        elif r.kind == "OnLine" and {p[1], p[2]} == {a, b}:
            if first is None:
                continue
            r = S.Relation("OnLine", [p[0]] + list(first))
        elif (r.kind == "Distance" and set(p) == {a, b}) or (r.kind == "Midpoint" and {p[1], p[2]} == {a, b}):
            continue
        out.append(r)
    return out


def trim_entity(s, k, x, y, keep=False):
    ""


    e = s.ents[k]
    if e.kind not in ("L", "C", "A", "S"):
        return None
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    size = max([1.0] + [abs(c) for p in pts for c in p])
    tol = 1e-6 * size
    cuts = _crossings(s, k, tol) if e.kind != "S" else []
    del ents[k]
    if not cuts or (e.kind == "C" and len(cuts) < 2):
        if keep:
            ents.insert(k, S.Entity(e.kind, e.points, True))
        if e.kind in ("C", "A") and not keep:
            owned = e.points[:2] + ([e.points[2]] if e.kind == "A" else [e.points[1]])
            rels = [r for r in rels if not (r.kind == "ArcPlane" and r.points == owned)]
        return S.compact(pts, ents, rels)

    def point(p, make):
        pts.append(p)
        i = len(pts) - 1
        r = make(i)
        if r is not None:
            rels.append(r)
        return i
    if e.kind == "L":
        a, b = e.points
        _, tc = s._seg_dist(pts[a], pts[b], x, y)
        lo = [c for c in cuts if c[0] < tc]
        hi = [c for c in cuts if c[0] > tc]
        pieces = []
        ia = point(lo[-1][1], lo[-1][2]) if lo else None
        ib = point(hi[0][1], hi[0][2]) if hi else None
        if ia is not None:
            pieces.append((a, ia))
        if ib is not None:
            pieces.append((ib, b))
        for p, q in pieces:
            ents.append(S.Entity("L", [p, q], e.construction))
        if keep:
            ents.append(S.Entity("L", [ia if ia is not None else a, ib if ib is not None else b], True))
        rels = _line_pair_relations(rels, a, b, pieces)
        return S.compact(pts, ents, rels)
    rd = _round_of(e, pts, rels)
    n = rd[4]
    line = s.polyline(e)
    best = min(range(len(line)), key=lambda i: s._screen_dist(line[i], x, y))
    tc = _angle_on(rd, line[best])
    owned = e.points[:2] + ([e.points[2]] if e.kind == "A" else [e.points[1]])
    rels = [r for r in rels if not (r.kind == "ArcPlane" and r.points == owned)]
    c = e.points[0]
    old_radius = [r for r in rels if r.kind in ("Diameter", "Radius") and r.points == e.points[:2]]
    rels = [r for r in rels if r not in old_radius]
    arcs = []
    if e.kind == "C":
        angles = [cu[0] for cu in cuts]
        # the gap between two crossings the click is in goes; the rest is one arc
        i_hi = next((i for i, t in enumerate(angles) if t > tc), 0)
        hi, lo = cuts[i_hi], cuts[i_hi - 1]
        ps = point(hi[1], hi[2])
        pe = point(lo[1], lo[2])
        arcs.append((ps, pe))
        gone = (pe, ps)
    else:
        a, b = e.points[1], e.points[2]
        lo = [cu for cu in cuts if cu[0] < tc]
        hi = [cu for cu in cuts if cu[0] > tc]
        ia = point(lo[-1][1], lo[-1][2]) if lo else None
        ib = point(hi[0][1], hi[0][2]) if hi else None
        if ia is not None:
            arcs.append((a, ia))
        if ib is not None:
            arcs.append((ib, b))
        gone = (ia if ia is not None else a, ib if ib is not None else b)
    for p, q in arcs:
        ents.append(S.Entity("A", [c, p, q], e.construction))
        rels.append(S.Relation("ArcPlane", [c, p, q], list(n)))
    if keep:
        ents.append(S.Entity("A", [c, gone[0], gone[1]], True))
        rels.append(S.Relation("ArcPlane", [c, gone[0], gone[1]], list(n)))
    if old_radius and arcs:
        r0 = old_radius[0]
        value = r0.values[0] / 2.0 if r0.kind == "Diameter" else r0.values[0]
        rels.append(S.Relation("Radius", [c, arcs[0][0]], [value]))
    return S.compact(pts, ents, rels)


def convert_edges(s, picks, construction=False):
    """(points, entities, relations) with the model edges picked (a face: its edges) as 3D sketch
    entities: lines, circles, arcs (ends Coincident with the model's corners, the centre with the
    edge's centre) and splines through points On Edge."""
    doc = s.doc
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    corners = {}
    for i, r in enumerate(rels):
        if r.kind == "AtRef" and r.ref:
            corners[tuple(r.ref)] = r.points[0]

    def corner(o, v):
        name = s._vertex_name(o.Shape, v)
        key = (o.Name, name)
        if name and key in corners:
            return corners[key]
        pts.append((v.Point.x, v.Point.y, v.Point.z))
        i = len(pts) - 1
        if name:
            rels.append(S.Relation("AtRef", [i], list(pts[i]), key))
            corners[key] = i
        return i
    edges = []
    for name, sub in picks:
        o = doc.getObject(name)
        if o is None or not hasattr(o, "Shape"):
            continue
        try:
            el = o.Shape.getElement(sub)
        except Exception:
            continue
        if sub.startswith("Face"):
            for fe in el.Edges:
                idx = next((i for i, x in enumerate(o.Shape.Edges) if x.isSame(fe)), None)
                if idx is not None:
                    edges.append((o, "Edge%d" % (idx + 1)))
        else:
            edges.append((o, sub))
    seen = set()
    for o, ename in edges:
        if (o.Name, ename) in seen:
            continue
        seen.add((o.Name, ename))
        edge = o.Shape.getElement(ename)
        curve = edge.Curve
        kind = type(curve).__name__
        if kind in ("Line", "LineSegment"):
            ents.append(S.Entity("L", [corner(o, edge.Vertexes[0]), corner(o, edge.Vertexes[-1])], construction))
        elif kind == "Circle":
            cc, ax = curve.Center, curve.Axis
            pts.append((cc.x, cc.y, cc.z))
            ci = len(pts) - 1
            rels.append(S.Relation("AtRef", [ci], list(pts[ci]), (o.Name, ename)))
            n = (ax.x, ax.y, ax.z)
            if edge.isClosed() or len(edge.Vertexes) == 1:
                a = corner(o, edge.Vertexes[0])
                ents.append(S.Entity("C", [ci, a], construction))
                rels.append(S.Relation("ArcPlane", [ci, a, a], list(n)))
            else:
                a, b = corner(o, edge.Vertexes[0]), corner(o, edge.Vertexes[-1])
                m = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
                if arc_sweep(pts[ci], pts[a], (m.x, m.y, m.z), n) > arc_sweep(pts[ci], pts[a], pts[b], n):
                    n = _mul(n, -1.0)
                ents.append(S.Entity("A", [ci, a, b], construction))
                rels.append(S.Relation("ArcPlane", [ci, a, b], list(n)))
        else:
            through = edge.discretize(Number=8)
            idx = [corner(o, edge.Vertexes[0])]
            for p in through[1:-1]:
                pts.append((p.x, p.y, p.z))
                idx.append(len(pts) - 1)
                rels.append(model_relation(doc, "OnEdge", idx[-1], o.Name, ename))
            idx.append(idx[0] if edge.isClosed() else corner(o, edge.Vertexes[-1]))
            ents.append(S.Entity("S", idx, construction))
    if not seen:
        return None
    return pts, ents, rels



def _join_corners(lines):
    ""



    def meet(a0, a1, b0, b1):
        u, v, w = a1 - a0, b1 - b0, a0 - b0
        uu, uv, vv, uw, vw = u.dot(u), u.dot(v), v.dot(v), u.dot(w), v.dot(w)
        den = uu * vv - uv * uv
        if abs(den) < 1e-12 * uu * vv:
            return None                       # parallel
        s_ = (uv * vw - vv * uw) / den
        t_ = (uu * vw - uv * uw) / den
        p, q = a0 + u * s_, b0 + v * t_
        return p if (p - q).Length < 1e-6 else None
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            fi, ei, ai, bi = lines[i]
            fj, ej, aj, bj = lines[j]
            if not fi.isSame(fj):
                continue
            shared = [v.Point for v in ei.Vertexes if any((v.Point - w.Point).Length < 1e-7 for w in ej.Vertexes)]
            if not shared:
                continue
            x = meet(ai, bi, aj, bj)
            if x is None:
                continue
            corner = shared[0]
            for k in (i, j):
                a, b = lines[k][2], lines[k][3]
                if (a - corner).Length <= (b - corner).Length:
                    lines[k][2] = x
                else:
                    lines[k][3] = x



def free_edges(s, edges, construction=False, on=None):
    """(points, entities, relations) with Part edges added as 3D sketch entities of their own (Intersection
    Curve, Face Curves): lines, circles, arcs, splines through points along the rest; ends on one spot are
    shared. on: (object name, face) puts each point On Surface (Face Curves' Constrain to model)."""
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    spots = {}

    def point(v, linked=True):
        key = tuple(round(c, 6) for c in (v.x, v.y, v.z))
        if key in spots:
            return spots[key]
        pts.append((v.x, v.y, v.z))
        i = len(pts) - 1
        spots[key] = i
        if on is not None and linked:
            rels.append(model_relation(s.doc, "OnSurface", i, on[0], on[1]))
        return i
    added = 0
    for edge in edges:
        if edge.Length < 1e-7:
            continue
        curve = edge.Curve
        kind = type(curve).__name__
        if kind in ("Line", "LineSegment"):
            ents.append(S.Entity("L", [point(edge.Vertexes[0].Point), point(edge.Vertexes[-1].Point)], construction))
        elif kind == "Circle":
            cc, ax = curve.Center, curve.Axis
            pts.append((cc.x, cc.y, cc.z))
            ci = len(pts) - 1
            n = (ax.x, ax.y, ax.z)
            if edge.isClosed():
                a = point(edge.Vertexes[0].Point)
                ents.append(S.Entity("C", [ci, a], construction))
                rels.append(S.Relation("ArcPlane", [ci, a, a], list(n)))
            else:
                a, b = point(edge.Vertexes[0].Point), point(edge.Vertexes[-1].Point)
                m = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
                if arc_sweep(pts[ci], pts[a], (m.x, m.y, m.z), n) > arc_sweep(pts[ci], pts[a], pts[b], n):
                    n = _mul(n, -1.0)
                ents.append(S.Entity("A", [ci, a, b], construction))
                rels.append(S.Relation("ArcPlane", [ci, a, b], list(n)))
        else:
            through = edge.discretize(Number=9)
            idx = [point(through[0])]
            for p in through[1:-1]:
                pts.append((p.x, p.y, p.z))
                idx.append(len(pts) - 1)
                if on is not None:
                    rels.append(model_relation(s.doc, "OnSurface", idx[-1], on[0], on[1]))
            idx.append(idx[0] if edge.isClosed() else point(through[-1]))
            ents.append(S.Entity("S", idx, construction))
        added += 1
    if not added:
        return None
    return pts, ents, rels


_EQ_MATH = None


def _equation(text, var="t"):
    """x(t) as a function: math names (sin, cos, pi, exp, sqrt...) and t only, ^ is a power."""
    global _EQ_MATH
    if _EQ_MATH is None:
        _EQ_MATH = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
        _EQ_MATH.update(abs=abs, min=min, max=max, pow=pow)
    text = (text or "").strip()
    if not text:
        raise ValueError("an equation is empty")
    code = compile(text.replace("^", "**"), "<equation>", "eval")
    for name in code.co_names:
        if name not in _EQ_MATH and name != var:
            raise ValueError("unknown name '%s' in %s" % (name, text))
    return lambda v: float(eval(code, {"__builtins__": {}}, dict(_EQ_MATH, **{var: v})))


def equation_points_3d(exprs, t1, t2, samples=49):
    ""
    if not t2 > t1:
        raise ValueError("t2 must be larger than t1")
    fx, fy, fz = (_equation(e) for e in exprs)
    out = []
    for k in range(samples):
        t = t1 + (t2 - t1) * k / (samples - 1)
        out.append((fx(t), fy(t), fz(t)))
    return out


def equation_curve(s, exprs, t1, t2, construction=False, locks=(True, True)):
    ""

    got = equation_points_3d(exprs, t1, t2)
    closed = _len(_sub(got[0], got[-1])) < 1e-7
    if closed:
        got = got[:-1]
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    idx = []
    for n, p in enumerate(got):
        pts.append(tuple(p))
        idx.append(len(pts) - 1)
        if (n == 0 and not locks[0] and not closed) or (n == len(got) - 1 and not locks[1] and not closed):
            continue
        rels.append(S.Relation("Fix", [idx[-1]], list(p)))
    if closed:
        idx.append(idx[0])
    ents.append(S.Entity("S", idx, construction))
    return pts, ents, rels


def pick_shape(doc, name, sub, size=1000.0):
    """The model shape a pick stands for in Intersection Curve: a face, a datum plane (a big square on
    it), else the whole body."""
    import Part
    o = doc.getObject(name)
    if o is None:
        return None
    if sub and sub.startswith("Face"):
        try:
            return o.Shape.getElement(sub)
        except Exception:
            return None
    pl = plane_of(doc, name, sub if sub and sub != "-" else "")
    if pl is not None and (not hasattr(o, "Shape") or o.Shape.isNull() or not o.Shape.Solids):
        base, n = pl
        n = _unit(n)
        seed = (1, 0, 0) if abs(n[0]) < 0.9 else (0, 1, 0)
        u = _unit(_sub(seed, _mul(n, _dot(seed, n))))
        v = _cross(n, u)
        corner = _sub(base, _add(_mul(u, size / 2), _mul(v, size / 2)))
        return Part.makePlane(size, size, App.Vector(*corner), App.Vector(*n), App.Vector(*u))
    if hasattr(o, "Shape") and not o.Shape.isNull():
        return o.Shape
    return None


def intersection_edges(doc, picks):
    ""
    shapes = [x for x in (pick_shape(doc, n, sub) for n, sub in picks) if x is not None]
    out = []
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            try:
                out += shapes[i].section(shapes[j]).Edges
            except Exception as _fw_err:
                _fw_log("sketch3d.py:4583", _fw_err)
    return out


def face_curve_edges(face, mode="Mesh", n1=5, n2=5, pos=(50.0, 50.0), dir1=True, dir2=True, ignore_holes=False):
    ""


    import Part
    u0, u1, v0, v1 = face.ParameterRange
    surf = face.Surface
    if mode == "Position":
        us = [u0 + (u1 - u0) * pos[0] / 100.0] if dir1 else []
        vs = [v0 + (v1 - v0) * pos[1] / 100.0] if dir2 else []
    else:
        us = [u0 + (u1 - u0) * k / (n1 + 1) for k in range(1, n1 + 1)] if dir1 else []
        vs = [v0 + (v1 - v0) * k / (n2 + 1) for k in range(1, n2 + 1)] if dir2 else []
    bound = face
    if ignore_holes:
        try:
            bound = Part.Face(face.Surface, face.OuterWire)
        except Exception:
            bound = face
    out = []
    for e in [Part.Edge(surf.uIso(u), v0, v1) for u in us] + [Part.Edge(surf.vIso(v), u0, u1) for v in vs]:
        try:
            out += bound.common(e).Edges
        except Exception:
            out.append(e)
    return out


def mirror_entities(s, items, about, copy=True):
    """(points, entities, relations) with the entities mirrored about a model plane: each new point
    Symmetric to its original (a point on the plane is its own mirror). copy False: the originals go."""
    name, element = about
    pl = plane_of(s.doc, name, element)
    if pl is None:
        return None
    base, n = pl
    n = _mul(n, 1.0 / max(_len(n), 1e-12))
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    size = max([1.0] + [abs(c) for p in pts for c in p])
    image = {}

    def mirrored(i):
        if i in image:
            return image[i]
        q = pts[i]
        d = _dot(_sub(q, base), n)
        if abs(d) < 1e-9 * size and copy:
            image[i] = i
            return i
        pts.append(_sub(q, _mul(n, 2 * d)))
        j = len(pts) - 1
        image[i] = j
        if copy:
            rels.append(S.Relation("SymPlane", [i, j], list(base) + list(n), (name, element)))
        return j

    def reflect(v):
        return _sub(v, _mul(n, 2 * _dot(v, n)))
    for k in items:
        e = s.ents[k]
        new = [mirrored(i) for i in e.points]
        ents.append(S.Entity(e.kind, new, e.construction))
        if e.kind in ("C", "A"):
            # a mirror turns an arc's way round: counterclockwise about the reflected normal reversed
            nn = reflect(arc_normal(e, s.rels))
            if e.kind == "A":
                nn = _mul(nn, -1.0)
            rels.append(S.Relation("ArcPlane", new[:2] + ([new[2]] if e.kind == "A" else [new[1]]), list(nn)))
    if not copy:
        drop = set(items)
        keep_e = [x for i, x in enumerate(ents) if i not in drop]
        owned = {tuple(x.points[:2] + ([x.points[2]] if x.kind == "A" else [x.points[1]]))
                 for x in keep_e if x.kind in ("C", "A")}
        rels = [r for r in rels if r.kind not in S.INTERNAL or tuple(r.points) in owned]
        return S.compact(pts, keep_e, rels)
    return pts, ents, rels

# =================================================================== sketch fillet, move, sketch plane
def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(v):
    n = _len(v)
    return _mul(v, 1.0 / n) if n > 1e-12 else v


def corner_lines(ents, p):
    """The two lines that meet at point p (a corner Sketch Fillet can round), else None."""
    users = [k for k, e in enumerate(ents) if p in e.points]
    if len(users) != 2 or any(ents[k].kind != "L" for k in users):
        return None
    return users


def corner_of(ents, k1, k2):
    """The point two lines share (their corner), else None."""
    if ents[k1].kind != "L" or ents[k2].kind != "L":
        return None
    common = set(ents[k1].points) & set(ents[k2].points)
    return next(iter(common)) if len(common) == 1 else None


def fillet_geometry(pts, ents, p, radius):
    """(centre, start, end, normal, (line1, line2), (far1, far2)) of the fillet of radius at corner p,
    else None (no two lines meet there, they are in line, or the radius does not fit)."""
    lines = corner_lines(ents, p)
    if lines is None or radius <= 0:
        return None
    far = [ents[k].points[1] if ents[k].points[0] == p else ents[k].points[0] for k in lines]
    P = pts[p]
    d1, d2 = _sub(pts[far[0]], P), _sub(pts[far[1]], P)
    l1, l2 = _len(d1), _len(d2)
    if l1 < 1e-9 or l2 < 1e-9:
        return None
    u, w = _mul(d1, 1.0 / l1), _mul(d2, 1.0 / l2)
    th = math.acos(max(-1.0, min(1.0, _dot(u, w))))
    if th < 1e-6 or th > math.pi - 1e-6:
        return None
    t = radius / math.tan(th / 2.0)
    if t >= l1 - 1e-9 or t >= l2 - 1e-9:
        return None
    centre = _add(P, _mul(_unit(_add(u, w)), radius / math.sin(th / 2.0)))
    t1, t2 = _add(P, _mul(u, t)), _add(P, _mul(w, t))
    n = _unit(_cross(_sub(t1, centre), _sub(t2, centre)))
    return centre, t1, t2, n, tuple(lines), tuple(far)


def virtual_sharps_on():
    ""
    try:
        from .fwsketch import sysopts
        v = sysopts.VIRTUAL_SHARPS_3D
        v = v() if callable(v) else v
        if isinstance(v, bool):
            return v
    except Exception as _fw_err:
        _fw_log("sketch3d.py:4724", _fw_err)
    try:
        from . import optionspages
        return bool(optionspages.stored("Sketch", "Line length measured between virtual sharps in 3d", True))
    except Exception:
        return True


def _closest_on_lines(p1, d1, p2, d2):
    """The point midway between the closest points of two 3D lines, else None (parallel)."""
    a, b, c = _dot(d1, d1), _dot(d1, d2), _dot(d2, d2)
    w = _sub(p1, p2)
    d, e = _dot(d1, w), _dot(d2, w)
    den = a * c - b * b
    if abs(den) < 1e-12:
        return None
    t = (b * e - c * d) / den
    u = (a * e - b * d) / den
    q1, q2 = _add(p1, _mul(d1, t)), _add(p2, _mul(d2, u))
    return _mul(_add(q1, q2), 0.5)


def sharp_end(pts, ents, e, q):
    """Where line e's end q would be without the sketch fillet that cut it back (the virtual sharp with the
    other line of the fillet), else the end itself."""
    for arc in ents:
        if arc.kind != "A" or q not in arc.points[1:3]:
            continue
        other_t = arc.points[2] if arc.points[1] == q else arc.points[1]
        for k, o in enumerate(ents):
            if o.kind == "L" and other_t in o.points and o is not ents[e]:
                a, b = ents[e].points[:2]
                oa, ob = o.points[:2]
                hit = _closest_on_lines(pts[a], _sub(pts[b], pts[a]), pts[oa], _sub(pts[ob], pts[oa]))
                if hit is not None:
                    return hit
    return pts[q]


def measured_length(pts, ents, e):
    ""
    a, b = ents[e].points[:2]
    if not virtual_sharps_on():
        return _len(_sub(pts[b], pts[a]))
    return _len(_sub(sharp_end(pts, ents, e, b), sharp_end(pts, ents, e, a)))


def fillet_corners(s, corners, radius, keep=True, each=False):
    ""



    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    failed, first = [], None
    carried = S.ALONG + S.TWO_LINE + ("Angle",)
    for p in corners:
        got = fillet_geometry(pts, ents, p, radius)
        if got is None:
            failed.append(p)
            continue
        centre, t1, t2, n, lines, far = got
        pts += [centre, t1, t2]
        c, i1, i2 = len(pts) - 3, len(pts) - 2, len(pts) - 1
        for k, t in zip(lines, (i1, i2)):
            e = ents[k]
            ents[k] = S.Entity("L", [t if q == p else q for q in e.points], e.construction)
        # a corner held by a relation or a dimension (a line's own Along/Parallel/Angle, or another
        # point On Line of it, go with the cut-back line)
        constrained = any(p in r.points and r.kind not in carried + ("Tangent",)
                          and not (r.kind == "OnLine" and r.points[0] != p)
                          for r in rels)
        if keep and constrained:
            ents.append(S.Entity("P", [p], True))
            rels += [S.Relation("OnLine", [p, far[0], i1]), S.Relation("OnLine", [p, far[1], i2])]
        else:
            for f, t in zip(far, (i1, i2)):
                rels = _line_pair_relations(rels, f, p, [(f, t)])
        ents.append(S.Entity("A", [c, i1, i2]))
        rels += [S.Relation("ArcPlane", [c, i1, i2], list(n)),
                 S.Relation("Tangent", [c, i1, far[0], i1], list(n)),
                 S.Relation("Tangent", [c, i2, far[1], i2], list(n))]
        if first is None or each:
            rels.append(S.Relation("Radius", [c, i1], [float(radius)]))
            first = first or (c, i1)
        else:
            rels.append(S.Relation("Equal", [first[0], first[1], c, i1]))
    return S.compact(pts, ents, rels), failed


def chamfer_geometry(pts, ents, p, d1, d2=None, angle=None):
    """(start, end, (line1, line2), (far1, far2)) of the chamfer at corner p, else None. Distance-distance:
    d1 back along the first line, d2 along the second. Angle-distance (angle in degrees): d1 along the first
    line, the chamfer leaving it at the angle."""
    lines = corner_lines(ents, p)
    if lines is None or d1 <= 0:
        return None
    far = [ents[k].points[1] if ents[k].points[0] == p else ents[k].points[0] for k in lines]
    P = pts[p]
    e1, e2 = _sub(pts[far[0]], P), _sub(pts[far[1]], P)
    l1, l2 = _len(e1), _len(e2)
    if l1 < 1e-9 or l2 < 1e-9:
        return None
    u, w = _mul(e1, 1.0 / l1), _mul(e2, 1.0 / l2)
    th = math.acos(max(-1.0, min(1.0, _dot(u, w))))
    if th < 1e-6 or th > math.pi - 1e-6:
        return None
    if angle is not None:
        a = math.radians(angle)
        rest = math.pi - th - a
        if a <= 1e-9 or rest <= 1e-9:
            return None
        d2 = d1 * math.sin(a) / math.sin(rest)
    if d2 is None:
        d2 = d1
    if d2 <= 0 or d1 >= l1 - 1e-9 or d2 >= l2 - 1e-9:
        return None
    return _add(P, _mul(u, d1)), _add(P, _mul(w, d2)), tuple(lines), tuple(far)


def chamfer_corners(s, corners, d1, d2=None, angle=None):
    ""


    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    failed = []
    carried = S.ALONG + S.TWO_LINE + ("Angle",)
    for p in corners:
        got = chamfer_geometry(pts, ents, p, d1, d2, angle)
        if got is None:
            failed.append(p)
            continue
        t1, t2, lines, far = got
        pts += [t1, t2]
        i1, i2 = len(pts) - 2, len(pts) - 1
        for k, i in zip(lines, (i1, i2)):
            e = ents[k]
            ents[k] = S.Entity("L", [i if q == p else q for q in e.points], e.construction)
        constrained = any(p in r.points and r.kind not in carried
                          and not (r.kind == "OnLine" and r.points[0] != p) for r in rels)
        if constrained:
            ents.append(S.Entity("P", [p], True))
            rels += [S.Relation("OnLine", [p, far[0], i1]), S.Relation("OnLine", [p, far[1], i2])]
        else:
            for f, i in zip(far, (i1, i2)):
                rels = _line_pair_relations(rels, f, p, [(f, i)])
        ents.append(S.Entity("L", [i1, i2], ents[lines[0]].construction))
    return S.compact(pts, ents, rels), failed


def _ray_hits(s, k, start, d, tol):
    """[(distance along d, point, relation maker)]: where the ray from start along the unit vector d meets
    the entities other than k in space."""
    pts, rels = s.pts, s.rels
    size = max([1.0] + [abs(c) for p in pts for c in p])
    far = _add(start, _mul(d, 1e3 * size))
    out = []
    for j, f in enumerate(s.ents):
        if j == k or f.kind in ("P", "Q"):
            continue
        if f.kind == "L":
            fa, fb = f.points
            make = (lambda i, fa=fa, fb=fb: S.Relation("OnLine", [i, fa, fb]))
        elif f.kind in ("C", "A"):
            rd = _round_of(f, pts, rels)
            make = (lambda i, f=f, n=rd[4]: S.Relation("OnArc", [f.points[0], f.points[1], i], list(n)))
            for sp, q in _line_round(start, far, rd, tol):
                if f.kind == "A" and _angle_on(rd, q) > rd[5] + 1e-9:
                    continue
                out.append((_len(_sub(q, start)), q, make))
            continue
        else:
            make = (lambda i: None)
        line = s.polyline(f)
        for a, b in zip(line[:-1], line[1:]):
            dist, sp, tt = _seg_closest(start, far, a, b)
            if dist < tol:
                q = _add(start, _mul(_sub(far, start), sp))
                out.append((_len(_sub(q, start)), q, make))
    return sorted([h for h in out if h[0] > tol], key=lambda h: h[0])


def _round_hits(s, k, rd, tol):
    """[(angle on round rd, point, relation maker)]: where the other entities cross the full circle of rd."""
    pts, rels = s.pts, s.rels
    full = rd[:5] + (2 * math.pi,)
    out = []
    for j, f in enumerate(s.ents):
        if j == k or f.kind in ("P", "Q"):
            continue
        if f.kind == "L":
            fa, fb = f.points
            make = (lambda i, fa=fa, fb=fb: S.Relation("OnLine", [i, fa, fb]))
            for sp, q in _line_round(pts[fa], pts[fb], full, tol):
                out.append((_angle_on(full, q), q, make))
        elif f.kind in ("C", "A"):
            rf = _round_of(f, pts, rels)
            make = (lambda i, f=f, n=rf[4]: S.Relation("OnArc", [f.points[0], f.points[1], i], list(n)))
            for q in _round_round(full, rf, tol):
                if f.kind == "A" and _angle_on(rf, q) > rf[5] + 1e-9:
                    continue
                out.append((_angle_on(full, q), q, make))
        else:
            line = s.polyline(f)
            for a, b in zip(line[:-1], line[1:]):
                for sp, q in _line_round(a, b, full, tol):
                    out.append((_angle_on(full, q), q, lambda i: None))
    return out


def extend_target(s, k, end):
    """(the end's point index, where it goes, relation maker) for Extend Entities on entity k at its end 0
    (start) or 1 (end), else None: a line goes on along itself, an arc round its circle, to the next entity
    it meets in space."""
    e = s.ents[k]
    pts = s.pts
    size = max([1.0] + [abs(c) for p in pts for c in p])
    tol = 1e-6 * size
    if e.kind == "L":
        a, b = (e.points[0], e.points[1]) if end == 1 else (e.points[1], e.points[0])
        d = _sub(pts[b], pts[a])
        if _len(d) < 1e-12:
            return None
        hits = _ray_hits(s, k, pts[b], _unit(d), tol)
        return (b, hits[0][1], hits[0][2]) if hits else None
    if e.kind == "A":
        rd = _round_of(e, pts, s.rels)
        sweep = rd[5]
        hits = [h for h in _round_hits(s, k, rd, tol) if sweep + 1e-7 < h[0] < 2 * math.pi - 1e-7]
        if not hits:
            return None
        h = min(hits, key=lambda h: h[0]) if end == 1 else max(hits, key=lambda h: h[0])
        return (e.points[2] if end == 1 else e.points[1], h[1], h[2])
    return None


def extend_entity(s, k, end):
    """(points, entities, relations) after Extend Entities, else None (nothing to extend to). The end
    comes loose from what held it there (its Fix, the length dimension); an end joined to other entities
    stays with them and the extended entity gets a new end."""
    got = extend_target(s, k, end)
    if got is None:
        return None
    p, q, make = got
    e = s.ents[k]
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    shared = any(p in f.points for j, f in enumerate(ents) if j != k)
    if shared:
        pts.append(q)
        i = len(pts) - 1
        if e.kind == "A":
            owned = list(e.points)
            new = [i if x == p else x for x in e.points]
            rels = [S.Relation("ArcPlane", new, r.values) if r.kind == "ArcPlane" and r.points == owned else r
                    for r in rels]
        ents[k] = S.Entity(e.kind, [i if x == p else x for x in e.points], e.construction)
    else:
        i = p
        pts[p] = q
        rels = [r for r in rels if not (r.kind in ("Fix", "Coincident", "AtRef", "OnLine", "OnArc") and
                                        r.points and r.points[0] == p)]
    if e.kind == "L":
        rels = [r for r in rels if not (r.kind == "Distance" and set(r.points) == set(e.points))]
    r = make(i)
    if r is not None:
        rels.append(r)
    return S.compact(pts, ents, rels)


def split_entity(s, k, q, second=None):
    """(points, entities, relations) after Split Entities at the point of entity k nearest q, else a reason
    (str). A line or arc becomes two; a circle needs two split points (second) and becomes two arcs; an open
    spline becomes two splines that meet at the split point."""
    e = s.ents[k]
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    if e.kind == "L":
        a, b = e.points
        A, B = pts[a], pts[b]
        d = _sub(B, A)
        f = _dot(_sub(q, A), d) / max(_dot(d, d), 1e-18)
        if not (1e-6 < f < 1 - 1e-6):
            return "Click inside the line, not at its end."
        pts.append(_add(A, _mul(d, f)))
        m = len(pts) - 1
        del ents[k]
        pieces = [(a, m), (m, b)]
        ents += [S.Entity("L", list(x), e.construction) for x in pieces]
        rels = _line_pair_relations(rels, a, b, pieces)
        rels.append(S.Relation("Collinear", [a, m, m, b]))
        return S.compact(pts, ents, rels)
    if e.kind in ("A", "C"):
        rd = _round_of(e, pts, rels)
        c = e.points[0]
        n = list(rd[4])
        t1 = _angle_on(rd, q)
        if e.kind == "A":
            if not (1e-6 < t1 < rd[5] - 1e-6):
                return "Click inside the arc, not at its end."
            pts.append(_at_angle(rd, t1))
            m = len(pts) - 1
            a, b = e.points[1], e.points[2]
            owned = list(e.points)
            rels = [r for r in rels if not (r.kind == "ArcPlane" and r.points == owned)]
            del ents[k]
            ents += [S.Entity("A", [c, a, m], e.construction), S.Entity("A", [c, m, b], e.construction)]
            rels += [S.Relation("ArcPlane", [c, a, m], n), S.Relation("ArcPlane", [c, m, b], n)]
            return S.compact(pts, ents, rels)
        if second is None:
            return "Click a second point on the circle: a circle splits at two points."
        t2 = _angle_on(rd, second)
        if abs(t1 - t2) < 1e-6:
            return "Click a second point away from the first."
        pts += [_at_angle(rd, t1), _at_angle(rd, t2)]
        m1, m2 = len(pts) - 2, len(pts) - 1
        owned = e.points[:2]
        old_radius = [r for r in rels if r.kind in ("Diameter", "Radius") and r.points == e.points[:2]]
        rels = [r for r in rels if not (r.kind == "ArcPlane" and r.points[:2] == owned) and r not in old_radius]
        del ents[k]
        ents += [S.Entity("A", [c, m1, m2], e.construction), S.Entity("A", [c, m2, m1], e.construction)]
        rels += [S.Relation("ArcPlane", [c, m1, m2], n), S.Relation("ArcPlane", [c, m2, m1], n)]
        if old_radius:
            r0 = old_radius[0]
            value = r0.values[0] / 2.0 if r0.kind == "Diameter" else r0.values[0]
            rels.append(S.Relation("Radius", [c, m1], [value]))
        return S.compact(pts, ents, rels)
    if e.kind == "S":
        if len(e.points) > 3 and e.points[0] == e.points[-1]:
            return "Split Entities splits an open spline; trim a closed one instead."
        return "spline"
    return "Pick a line, arc, circle or spline."


def segment_entity(s, k, count, mode="points"):
    ""


    e = s.ents[k]
    count = int(count)
    if count < 2:
        return "Segment needs 2 or more instances."
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    if e.kind == "L":
        a, b = e.points
        A, B = pts[a], pts[b]
        new = []
        for i in range(1, count):
            pts.append(_add(A, _mul(_sub(B, A), i / float(count))))
            new.append(len(pts) - 1)
        if mode == "points":
            ents += [S.Entity("P", [i]) for i in new]
            rels += [S.Relation("OnLine", [i, a, b]) for i in new]
            return S.compact(pts, ents, rels)
        chain = [a] + new + [b]
        pieces = list(zip(chain[:-1], chain[1:]))
        del ents[k]
        ents += [S.Entity("L", list(x), e.construction) for x in pieces]
        rels = _line_pair_relations(rels, a, b, pieces)
        for x, y in zip(pieces[:-1], pieces[1:]):
            rels.append(S.Relation("Collinear", list(x) + list(y)))
        for y in pieces[1:]:
            rels.append(S.Relation("Equal", list(pieces[0]) + list(y)))
        return S.compact(pts, ents, rels)
    if e.kind in ("A", "C"):
        rd = _round_of(e, pts, rels)
        c, n = e.points[0], list(rd[4])
        sweep = rd[5]
        steps = range(1, count) if e.kind == "A" or mode != "points" else range(0, count)
        new = []
        for i in steps:
            if i == 0:
                new.append(e.points[1])
                continue
            pts.append(_at_angle(rd, sweep * i / float(count)))
            new.append(len(pts) - 1)
        if mode == "points":
            ents += [S.Entity("P", [i]) for i in new]
            rels += [S.Relation("OnArc", [c, e.points[1], i], n) for i in new if i != e.points[1]]
            return S.compact(pts, ents, rels)
        owned = list(e.points)
        rels = [r for r in rels if not (r.kind == "ArcPlane" and r.points[:2] == owned[:2])]
        rim = e.points[1]
        chain = [rim] + new + ([rim] if e.kind == "C" else [e.points[2]])
        del ents[k]
        for x, y in zip(chain[:-1], chain[1:]):
            ents.append(S.Entity("A", [c, x, y], e.construction))
            rels.append(S.Relation("ArcPlane", [c, x, y], n))
        return S.compact(pts, ents, rels)
    return "Segment takes a line, arc, circle or spline."


def _chain_order(ents, items):
    """The entities in chain order, each with its direction ((k, reversed)), else None (not one chain)."""
    left = list(items)
    if not left:
        return None

    def ends(k):
        p = ents[k].points
        return (p[1], p[2]) if ents[k].kind == "A" else (p[0], p[-1])
    chain = [(left.pop(0), False)]
    while left:
        head = ends(chain[0][0])[1 if chain[0][1] else 0]
        tail = ends(chain[-1][0])[0 if chain[-1][1] else 1]
        for k in left:
            a, b = ends(k)
            if a == tail or b == tail:
                chain.append((k, b == tail))
                break
            if a == head or b == head:
                chain.insert(0, (k, a == head))
                break
        else:
            return None
        left.remove(k)
    return chain


def fit_points(s, items, tolerance=0.01, closed=False):
    ""

    chain = _chain_order(s.ents, items)
    if chain is None:
        return None
    samples, corners, source = [], [], []
    for k, back in chain:
        e = s.ents[k]
        line = s.polyline(e)
        if e.kind == "L":
            line = [_add(line[0], _mul(_sub(line[1], line[0]), i / 16.0)) for i in range(17)]
        if back:
            line = line[::-1]
        if samples:
            line = line[1:]
        corners.append(len(samples))
        samples += line
        source += [k] * len(line)
    corners.append(len(samples) - 1)
    if closed and _len(_sub(samples[0], samples[-1])) < 1e-9:
        samples = samples[:-1]
        corners = corners[:-1]
    fit_points.sources = source
    chosen = sorted(set(corners))
    for _ in range(60):
        edge = spline_edge([samples[i] for i in chosen] + ([samples[chosen[0]]] if closed else []), closed)
        worst, at = 0.0, None
        for i, q in enumerate(samples):
            if i in chosen:
                continue
            d = edge.distToShape(Part_vertex(q))[0]
            if d > worst:
                worst, at = d, i
        if at is None or worst <= tolerance:
            break
        chosen = sorted(chosen + [at])
    fit_points.sources = [source[i] for i in chosen]
    return [samples[i] for i in chosen]


def Part_vertex(q):
    import Part
    return Part.Vertex(App.Vector(*q))


def fit_spline(s, items, tolerance=0.01, closed=False, delete=True, construction=False, how="Unconstrained"):
    """(points, entities, relations) with a spline fitted over the chain (Fit Spline), the chain deleted
    (Delete geometry) or kept as construction geometry, else a reason. how: Constrained (the chain stays as
    construction geometry and the spline's points stay on it), Unconstrained, or Fixed (every point Fix)."""
    got = fit_points(s, items, tolerance, closed)
    if got is None:
        return "Pick lines, arcs or splines that join end to end."
    sources = list(fit_points.sources)
    if how == "Constrained":
        delete = False
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    base = len(pts)
    pts += got
    idx = list(range(base, base + len(got)))
    if closed:
        idx.append(base)
    for k in items:
        if delete:
            ents[k] = None
        else:
            ents[k] = S.Entity(ents[k].kind, ents[k].points, True)
    for i, k in zip(range(base, base + len(got)), sources):
        if how == "Fixed":
            rels.append(S.Relation("Fix", [i], list(pts[i])))
        elif how == "Constrained":
            e = s.ents[k]
            if e.kind == "L":
                rels.append(S.Relation("OnLine", [i] + list(e.points)))
            elif e.kind in ("A", "C"):
                rels.append(S.Relation("OnArc", [e.points[0], e.points[1], i], list(arc_normal(e, s.rels))))
    ents = [e for e in ents if e is not None]
    ents.append(S.Entity("S", idx, construction))
    return S.compact(pts, ents, rels)


def jog_line(s, k, at, width, depth, flip=False, normal=(0.0, 0.0, 1.0)):
    ""


    e = s.ents[k]
    if e.kind != "L":
        return "Pick a line."
    a, b = e.points
    A, B = s.pts[a], s.pts[b]
    d = _sub(B, A)
    L = _len(d)
    if L < 1e-9:
        return "Pick a line."
    u = _mul(d, 1.0 / L)
    f = max(0.0, min(L, _dot(_sub(at, A), u)))
    lo, hi = f - width / 2.0, f + width / 2.0
    if width <= 0 or depth <= 0 or lo <= 1e-9 or hi >= L - 1e-9:
        return "The jog does not fit on the line there."
    side = _cross(normal, u)
    if _len(side) < 1e-6:
        side = _cross((0.0, 0.0, 1.0) if abs(u[2]) < 0.9 else (1.0, 0.0, 0.0), u)
    side = _mul(_unit(side), -depth if flip else depth)
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    p1, p2 = _add(A, _mul(u, lo)), _add(A, _mul(u, hi))
    pts += [p1, _add(p1, side), _add(p2, side), p2]
    i1, i2, i3, i4 = range(len(pts) - 4, len(pts))
    del ents[k]
    sides = [(a, i1), (i1, i2), (i2, i3), (i3, i4), (i4, b)]
    ents += [S.Entity("L", list(x), e.construction) for x in sides]
    rels = _line_pair_relations(rels, a, b, [(a, i1), (i4, b)])
    rels += [S.Relation("Collinear", [a, i1, i4, b]), S.Relation("Perpendicular", [a, i1, i1, i2]),
             S.Relation("Perpendicular", [a, i1, i3, i4]), S.Relation("Parallel", [a, i1, i2, i3])]
    return S.compact(pts, ents, rels)


def repair_sketch(s, gap=None):
    ""

    size = max([1.0] + [abs(c) for p in s.pts for c in p])
    gap = 1e-4 * size if gap is None else gap
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    fixed = []
    same = {}
    for i in range(len(pts)):
        if i in same:
            continue
        for j in range(i + 1, len(pts)):
            if j not in same and _len(_sub(pts[i], pts[j])) < gap and i != j:
                same[j] = i
    if same:
        fixed.append("%d gap%s closed" % (len(same), "" if len(same) == 1 else "s"))
        m = lambda p: same.get(p, p)
        ents = [S.Entity(e.kind, [m(p) for p in e.points], e.construction) for e in ents]
        rels = [S.Relation(r.kind, [m(p) for p in r.points], r.values, r.ref) for r in rels]
        rels = [r for r in rels if not (r.kind in ("Coincident", "Distance") and len(set(r.points)) < 2)]
    keep, seen, short, twice = [], set(), 0, 0
    for e in ents:
        if e.kind == "L" and (e.points[0] == e.points[1] or _len(_sub(pts[e.points[0]], pts[e.points[1]])) < gap):
            short += 1
            continue
        key = (e.kind, tuple(sorted(e.points)) if e.kind in ("L", "P") else tuple(e.points))
        if key in seen:
            twice += 1
            continue
        seen.add(key)
        keep.append(e)
    if short:
        fixed.append("%d entit%s of no length deleted" % (short, "y" if short == 1 else "ies"))
    if twice:
        fixed.append("%d overlapping entit%s deleted" % (twice, "y" if twice == 1 else "ies"))
    return S.compact(pts, keep, rels), fixed


def _key_points(e):
    """The points of entity e that relations hold: a line's ends, an arc's centre and ends, a circle's centre
    and rim point, a spline's through points, a point."""
    return list(e.points) if e.kind != "Q" else []


LINE_ONLY = S.ALONG + LINE_OWN + S.TWO_LINE + ("Angle", "Collinear", "Distance", "Midpoint")


def replace_entity(s, old, new, construction=False):
    ""


    if old == new:
        return "Pick a different entity to replace it with."
    eo, en = s.ents[old], s.ents[new]
    if eo.kind in ("Q",) or en.kind in ("Q",):
        return "A sketch plane cannot be replaced."
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    mine = _key_points(eo)
    targets = _key_points(en)
    if eo.kind in ("A", "C") and en.kind in ("A", "C"):
        m = {eo.points[0]: en.points[0]}      # centre to centre
        rest = [p for p in mine if p != eo.points[0]]
        tgt = [p for p in targets if p != en.points[0]]
    else:
        m, rest, tgt = {}, mine, targets
    for p in rest:
        if tgt:
            m[p] = min(tgt, key=lambda q: _len(_sub(pts[p], pts[q])))
    whole = set(eo.points)
    out = []
    for r in rels:
        if not set(r.points) & set(m):
            out.append(r)
            continue
        if r.kind in ("ArcPlane",) and set(r.points) <= whole:
            if construction:
                out.append(r)
            continue
        line_rel = r.kind in LINE_ONLY and len(set(r.points) & whole) >= 2
        if line_rel and en.kind != "L":
            continue
        if r.kind in ("Diameter", "Radius") and en.kind not in ("A", "C"):
            continue
        q = [m.get(p, p) for p in r.points]
        if len(set(q)) < len(q) and r.kind in ("Coincident", "Distance", "OnLine", "Midpoint") + S.TWO_LINE:
            continue
        out.append(S.Relation(r.kind, q, r.values, r.ref))
    if construction:
        # the old entity stays, with its own points, as construction geometry; the rest moves over
        ents = [S.Entity(e.kind, [m.get(p, p) for p in e.points] if k not in (old, new) else e.points,
                         True if k == old else e.construction) for k, e in enumerate(ents)]
    else:
        ents = [S.Entity(e.kind, [m.get(p, p) for p in e.points] if k != new else e.points, e.construction)
                for k, e in enumerate(ents) if k != old]
    return S.compact(pts, ents, out)


def dissolve_points(s, points):
    """((points, entities, relations), how many dissolved) after Dissolve on split points: where exactly two
    lines meet in line, two arcs of one circle, or two splines end to end, they become one entity again (the
    reverse of Split Entities and Segment)."""
    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    done = 0
    for p in points:
        users = [k for k, e in enumerate(ents) if e is not None and p in e.points and e.kind != "P"]
        if len(users) != 2:
            continue
        e1, e2 = ents[users[0]], ents[users[1]]
        if e1.kind != e2.kind or e1.construction != e2.construction:
            continue
        joined = None
        if e1.kind == "L":
            f1 = e1.points[0] if e1.points[1] == p else e1.points[1]
            f2 = e2.points[0] if e2.points[1] == p else e2.points[1]
            u, w = _sub(pts[p], pts[f1]), _sub(pts[f2], pts[p])
            if _len(_cross(_unit(u), _unit(w))) < 1e-6 and _dot(u, w) > 0:
                joined = S.Entity("L", [f1, f2], e1.construction)
                rels = _line_pair_relations(rels, f1, p, [(f1, f2)])
                rels = _line_pair_relations(rels, p, f2, [(f1, f2)])
        elif e1.kind == "A" and e1.points[0] == e2.points[0]:
            c = e1.points[0]
            if e1.points[2] == p and e2.points[1] == p:
                joined = S.Entity("A", [c, e1.points[1], e2.points[2]], e1.construction)
            elif e2.points[2] == p and e1.points[1] == p:
                joined = S.Entity("A", [c, e2.points[1], e1.points[2]], e1.construction)
            if joined is not None:
                n = [r.values for r in rels if r.kind == "ArcPlane" and r.points == e1.points][:1]
                rels = [r for r in rels if not (r.kind == "ArcPlane" and r.points in (e1.points, e2.points))]
                if n:
                    rels.append(S.Relation("ArcPlane", list(joined.points), n[0]))
        elif e1.kind == "S":
            a, b = e1.points, e2.points
            if a[-1] == p and b[0] == p:
                joined = S.Entity("S", a + b[1:], e1.construction)
            elif b[-1] == p and a[0] == p:
                joined = S.Entity("S", b + a[1:], e1.construction)
        if joined is None:
            continue
        ents[users[0]], ents[users[1]] = joined, None     # p goes, and its relations with it (compact)
        done += 1
    return S.compact(pts, [e for e in ents if e is not None], rels), done


def entities_subset(s, items):
    """(points, entities, relations) of the picked entities alone, with the relations among them (Create Sketch
    from Selections)."""
    keep = sorted(set(items))
    ents = [s.ents[k] for k in keep]
    used = set(p for e in ents for p in e.points)
    rels = [r for r in s.rels if r.points and set(r.points) <= used]
    return S.compact(list(s.pts), ents, rels)


def sketch_from_selections():
    ""


    doc = App.ActiveDocument
    s = session()
    if s is not None:
        items = [i for kind, i in s.selection if kind == "E" and s.ents[i].kind != "Q"]
        if not items:
            s.status("Create Sketch from Selections: pick the sketch entities first.")
            return None
        pts, ents, rels = entities_subset(s, items)
        doc.openTransaction("Create Sketch from Selections")
        try:
            body = None
            try:
                body = s.obj.getParentGeoFeatureGroup()
            except Exception:
                body = None
            obj = make(doc, body)
            store(obj, pts, ents, rels)
            obj.ViewObject.Visibility = True
        finally:
            doc.commitTransaction()
        s.status("Create Sketch from Selections: %s with %d entit%s." % (obj.Label, len(ents),
                                                                          "y" if len(ents) == 1 else "ies"))
        return obj
    gdoc = Gui.ActiveDocument
    vp = gdoc.getInEdit() if gdoc else None
    sk = getattr(vp, "Object", None) if vp is not None else None
    if sk is None or not sk.isDerivedFrom("Sketcher::SketchObject"):
        return None
    ids = sorted({int(n[4:]) - 1 for o in Gui.Selection.getSelectionEx()
                  for n in o.SubElementNames if n.startswith("Edge") and o.Object == sk})
    if not ids:
        return None
    doc.openTransaction("Create Sketch from Selections")
    try:
        new = doc.addObject("Sketcher::SketchObject", "Sketch")
        body = sk.getParentGeoFeatureGroup()
        if body is not None:
            body.addObject(new)
        for prop in ("AttachmentSupport", "Support"):
            if hasattr(sk, prop):
                try:
                    setattr(new, prop, getattr(sk, prop))
                except Exception as _fw_err:
                    _fw_log("sketch3d.py:5456", _fw_err)
        new.MapMode = sk.MapMode
        new.AttachmentOffset = sk.AttachmentOffset
        new.Placement = sk.Placement
        index = {}
        for g in ids:
            index[g] = new.addGeometry(sk.Geometry[g].copy(), bool(sk.getConstruction(g)))
        for c in sk.Constraints:
            geos = [getattr(c, k) for k in ("First", "Second", "Third")]
            used = [x for x in geos if x is not None and x >= 0]
            # external geometry (-3 and below; -2000 is "none") does not come along
            if not used or any(x not in index for x in used) or \
                    any(x is not None and -2000 < x <= -3 for x in geos):
                continue
            try:
                d = c        # the Constraints list hands out copies
                for k in ("First", "Second", "Third"):
                    v = getattr(d, k)
                    if v is not None and v >= 0:
                        setattr(d, k, index[v])
                new.addConstraint(d)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:5478", _fw_err)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return new


def spline_marks(edge, samples=400):
    """(inflection points, (point, radius) of the minimum radius of curvature) of a spline edge in space. An
    inflection is where the curvature falls to nothing between two bends (for a flat curve: the bend changes
    side); the minimum radius is at the curvature's peak."""
    c = edge.Curve
    t0, t1 = edge.ParameterRange
    ts = [t0 + (t1 - t0) * j / float(samples) for j in range(samples + 1)]
    data = []
    for u in ts:
        try:
            kap = c.curvature(u)
        except Exception:
            kap = 0.0
        p = c.value(u)
        try:
            v1, v2 = c.getDN(u, 1), c.getDN(u, 2)
            b = v1.cross(v2)
        except Exception:
            b = App.Vector(0, 0, 0)
        data.append((u, (p.x, p.y, p.z), kap, (b.x, b.y, b.z)))
    infl = []
    size = max([1e-12] + [_len(d[3]) for d in data])
    last, flat = None, None      # the last sample with a bend, the first straight one since
    for u, p, k, b in data:
        # the binormal (bend side) turns over: an inflection there (on a straight sample, or between two)
        if _len(b) <= 1e-9 * size:
            flat = flat or p
            continue
        if last is not None and _dot(last, b) < 0:
            infl.append(flat or p)
        last, flat = b, None
    peak = max(data, key=lambda d: d[2]) if data else None
    min_radius = (peak[1], 1.0 / peak[2]) if peak is not None and peak[2] > 1e-12 else None
    return infl, min_radius


def simplify_points(s, k, tolerance):
    ""

    e = s.ents[k]
    edge = entity_edges(e, s.pts, s.rels)[0]
    samples = [tuple(v) for v in edge.discretize(Number=120)]
    closed = len(e.points) > 3 and e.points[0] == e.points[-1]
    chosen = [0, len(samples) - 1] if not closed else [0, 40, 80]
    for _ in range(len(e.points) + 40):
        pts = [samples[i] for i in chosen]
        if len(pts) >= 2:
            fit = spline_edge(pts + ([pts[0]] if closed else []), closed)
        worst, at = 0.0, None
        for i, q in enumerate(samples):
            if i in chosen:
                continue
            d = fit.distToShape(Part_vertex(q))[0]
            if d > worst:
                worst, at = d, i
        if at is None or worst <= tolerance:
            break
        chosen = sorted(chosen + [at])
    return [samples[i] for i in chosen]


def move_entities(doc, pts, ents, rels, items, delta, keep=False):
    """(points, entities, relations) with the entities moved by delta, else None (Keep relations is on
    and the relations hold them where they are). Keep relations off: the moved entities come loose from
    the rest (shared ends are split) and their relations to it, Fix and the model go."""
    return transform_entities(doc, pts, ents, rels, items, lambda q: _add(q, delta), keep)


# directions kept in a relation's values (a circle's plane normal...): (start, ...) of each x y z; Rotate turns them
DIRECTION_VALUES = {"ArcPlane": (0,), "OnArc": (0,), "Tangent": (0,), "ArcMidpoint": (0,),
                    "SplineTangentArc": (0,), "CurveLength": (3, 6), "SplineHandle": (0,)}
# relations to a fixed direction: they no longer hold once turned
FIXED_DIRECTION = S.ALONG + ("AlongDirH", "AlongDirV")


def _turned(r, turn, pmap=None):
    values = list(r.values)
    if turn is not None:
        for at in DIRECTION_VALUES.get(r.kind, ()):
            values[at:at + 3] = list(turn(tuple(values[at:at + 3])))
    points = [pmap.get(i, i) for i in r.points] if pmap is not None else list(r.points)
    return S.Relation(r.kind, points, values, r.ref)


def transform_entities(doc, pts, ents, rels, items, where, keep=False, copy=False, turn=None):
    """(points, entities, relations) with the entities moved (Move, Rotate) or copies of them added (Copy):
    where(point) is a point's new place, turn(direction) turns a direction (Rotate); else None (Keep
    relations holds them). The relations among the entities go with them (turned); Keep relations off,
    the ones to the rest of the sketch, Fix and the model go (a copy's always do), and a moved entity's
    ends shared with the rest are split."""
    items = set(items)
    moving = sorted({i for k in items for i in ents[k].points})
    if not moving:
        return None
    mset = set(moving)
    if copy:
        pts = list(pts)
        dup = {}
        for i in moving:
            pts.append(tuple(where(pts[i])))
            dup[i] = len(pts) - 1
        ents = list(ents) + [S.Entity(ents[k].kind, [dup[i] for i in ents[k].points], ents[k].construction)
                             for k in sorted(items)]
        out = list(rels)
        for r in rels:
            if r.points and all(i in mset for i in r.points) and r.kind != "Fix" and r.kind not in S.MODEL \
                    and not (turn is not None and r.kind in FIXED_DIRECTION):
                out.append(_turned(r, turn, dup))
        return pts, ents, out
    if keep:
        new = [tuple(where(q)) if i in mset else q for i, q in enumerate(pts)]
        out = [_turned(r, turn) if r.points and all(i in mset for i in r.points) else r for r in rels]
        extra = [S.Relation("Fix", [i], list(new[i])) for i in moving]
        got, ok = solve(doc, new, out, extra)
        if not ok:
            return None
        return got, list(ents), out
    pts = list(pts)
    staying = {i for k, e in enumerate(ents) if k not in items for i in e.points}
    dup = {}
    for i in sorted(mset & staying):
        pts.append(pts[i])
        dup[i] = len(pts) - 1
    ents = [S.Entity(e.kind, [dup.get(i, i) for i in e.points], e.construction) if k in items else e
            for k, e in enumerate(ents)]
    out = []
    for r in rels:
        if all(i in staying or i not in mset for i in r.points):
            out.append(r)                 # the entities that stay (a shared point is theirs)
        elif all(i in mset for i in r.points) and r.kind != "Fix" and r.kind not in S.MODEL \
                and not (turn is not None and r.kind in FIXED_DIRECTION):
            out.append(_turned(r, turn, dup))
    for i in mset:
        j = dup.get(i, i)
        pts[j] = tuple(where(pts[j]))
    return pts, ents, out


def rotation(centre, angles):
    """(where, turn) of a 3D sketch Rotate: about the model's X, then Y, then Z axis through centre, by
    angles (degrees)."""
    rot = App.Rotation(App.Vector(0, 0, 1), angles[2]).multiply(App.Rotation(App.Vector(0, 1, 0), angles[1])) \
        .multiply(App.Rotation(App.Vector(1, 0, 0), angles[0]))

    def turn(d):
        v = rot.multVec(App.Vector(*d))
        return (v.x, v.y, v.z)

    def where(q):
        return _add(centre, turn(_sub(q, centre)))
    return where, turn


def sketch_plane_frame(pts, ent):
    """(corner, normal, u, v) of a sketch plane entity."""
    a, b, c = (pts[i] for i in ent.points[:3])
    u = _unit(_sub(b, a))
    n = _unit(_cross(_sub(b, a), _sub(c, a)))
    return a, n, u, _cross(n, u)



PLANE_RELATIONS = {"P": ("Coincident",), "L": ("Coincident", "Parallel", "Perpendicular"),
                   "M": ("Coincident", "Parallel", "Perpendicular", "Distance", "Angle")}


def default_plane_relations(refs):
    """The relation each reference gets until one is picked: Coincident; a model plane with a sketch point
    or line beside it: Parallel."""
    others = any(k in ("P", "L") for k, _ in refs)
    return [("Parallel" if k == "M" and others else "Coincident", None, False) for k, _ in refs]


def make_sketch_plane(s, refs, size=None, how=None):
    ""








    pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
    base_how = default_plane_relations(refs)
    how = [h if h is not None else d for h, d in zip(list(how or []) + [None] * len(refs), base_how)]
    pids, lines, model = [], [], None
    for (k, i), (rel, value, flip) in zip(refs, how):
        if k == "P":
            pids.append(i)
        elif k == "L":
            p, q = ents[i].points[:2]
            if rel == "Coincident":
                pids += [p, q]
            else:
                lines.append((rel, p, q))
        elif k == "M":
            model = (i, rel, value, flip)
    pids = list(dict.fromkeys(pids))[:3]
    if size is None:
        span = max([0.0] + [abs(c) for p in pts for c in p])
        size = max(20.0, 0.5 * span)
    n0, (u0, v0) = s.axes()

    def new(q):
        pts.append(q)
        return len(pts) - 1

    def anchor():
        return pids[0] if pids else new(s.plane_anchor())
    if len(pids) >= 3:
        a, b, c = pids
        if _len(_cross(_sub(pts[b], pts[a]), _sub(pts[c], pts[a]))) < 1e-9 * max(1.0, size) ** 2:
            return "The three points are in line: pick points that make a plane."
        ents.append(S.Entity("Q", [a, b, c]))
        return pts, ents, rels
    if model is not None:
        (name, element), rel, value, flip = model
        pl = plane_of(s.doc, name, element)
        if pl is None:
            return "Pick a plane or a flat face of the model."
        base, n = pl
        n = _unit(n)
        seed = (1, 0, 0) if abs(n[0]) < 0.9 else (0, 1, 0)
        u = _unit(_sub(seed, _mul(n, _dot(seed, n))))
        v = _cross(n, u)
        ref = (name, element or "-")
        if rel == "Distance":
            d = abs(float(value if value is not None else 10.0))
            side = -1.0 if flip else 1.0
            a = new(_add(base, _mul(n, d * side)))
            b, c = new(_add(pts[a], _mul(u, size))), new(_add(pts[a], _mul(v, size)))
            rels += [S.Relation("PlaneParallel", [a, b], list(base) + list(n), ref),
                     S.Relation("PlaneParallel", [a, c], list(base) + list(n), ref),
                     S.Relation("PlaneDistance", [a], [d, side] + list(base) + list(n), ref)]
        elif rel == "Angle":
            if len(pids) < 2:
                return "Angle: pick a sketch line (or two points) too, the line the plane turns about."
            a, b = pids[:2]
            hinge = _unit(_sub(pts[b], pts[a]))
            w = _cross(n, hinge)
            if _len(w) < 1e-9:
                return "Angle: the line is square to the plane; pick a line along it."
            w = _unit(w)
            deg = float(value if value is not None else 45.0)
            t = math.radians(deg) * (-1.0 if flip else 1.0)
            c = new(_add(pts[a], _mul(_add(_mul(w, math.cos(t)), _mul(n, math.sin(t))), size)))
            rels += [S.Relation("Perpendicular", [a, b, a, c]),
                     S.Relation("PlaneAngle", [a, c], [abs(deg)] + list(base) + list(n), ref)]
            ents.append(S.Entity("Q", [a, b, c]))
            return pts, ents, rels
        elif rel == "Perpendicular":
            a = anchor()
            c = new(_add(pts[a], _mul(n, size)))
            b = pids[1] if len(pids) >= 2 else new(_add(pts[a], _mul(u, size)))
            rels.append(S.Relation("PlaneNormal", [a, c], list(base) + list(n), ref))
            ents.append(S.Entity("Q", [a, b, c]))
            return pts, ents, rels
        elif rel == "Parallel":
            a = anchor()
            b, c = new(_add(pts[a], _mul(u, size))), new(_add(pts[a], _mul(v, size)))
            rels += [S.Relation("PlaneParallel", [a, b], list(base) + list(n), ref),
                     S.Relation("PlaneParallel", [a, c], list(base) + list(n), ref)]
        else:
            # Coincident: on the plane (a picked point is pulled onto it too)
            a = pids[0] if pids else new(base)
            b, c = new(_add(pts[a], _mul(u, size))), new(_add(pts[a], _mul(v, size)))
            for i in (a, b, c):
                rels.append(model_relation(s.doc, "OnPlane", i, name, element))
        ents.append(S.Entity("Q", [a, b, c]))
        return pts, ents, rels
    if lines:
        rel, p, q = lines[0]
        d = _sub(pts[q], pts[p])
        if _len(d) < 1e-12:
            return "The line has no length."
        d = _unit(d)
        a = anchor()
        if rel == "Perpendicular":
            seed = (1, 0, 0) if abs(d[0]) < 0.9 else (0, 1, 0)
            w1 = _unit(_sub(seed, _mul(d, _dot(seed, d))))
            w2 = _cross(d, w1)
            b, c = new(_add(pts[a], _mul(w1, size))), new(_add(pts[a], _mul(w2, size)))
            rels += [S.Relation("Perpendicular", [a, b, p, q]), S.Relation("Perpendicular", [a, c, p, q])]
        else:
            # Parallel: the plane runs along the line, through the picked points
            c = new(_add(pts[a], _mul(d, size)))
            if len(pids) >= 2:
                b = pids[1]
            else:
                side = _cross(n0, d)
                b = new(_add(pts[a], _mul(_unit(side) if _len(side) > 1e-6 else u0, size)))
            rels.append(S.Relation("Parallel", [a, c, p, q]))
        ents.append(S.Entity("Q", [a, b, c]))
        return pts, ents, rels
    if len(pids) == 2:
        a, b = pids
        d = _unit(_sub(pts[b], pts[a]))
        side = _cross(n0, d)
        if _len(side) < 1e-6:
            side = u0
        c = new(_add(pts[a], _mul(_unit(side), size)))
        ents.append(S.Entity("Q", [a, b, c]))
        return pts, ents, rels
    a = anchor()
    b, c = new(_add(pts[a], _mul(u0, size))), new(_add(pts[a], _mul(v0, size)))
    ents.append(S.Entity("Q", [a, b, c]))
    return pts, ents, rels


# =================================================================== tools
def _fmt(value):
    try:
        return App.Units.Quantity(value, App.Units.Length).UserString
    except Exception:
        return "%.2f mm" % value


def _fmt_angle(degrees):
    return "%.2f\u00b0" % degrees


def _line_angle(pts, a, b, c, d):
    u, w = _sub(pts[b], pts[a]), _sub(pts[d], pts[c])
    lu, lw = _len(u), _len(w)
    if lu < 1e-12 or lw < 1e-12:
        return 0.0
    cr = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    return math.degrees(math.atan2(_len(cr), _dot(u, w)))


if GUI:
    class Tool:
        TITLE = "3D Sketch tool"
        CURSOR = "Sketcher_Pointer_Create_Lineset"
        HINT = ""

        def __init__(self, session, construction=False):
            self.s = session
            self.construction = construction
            self.last = None          # the last Snap under the pointer

        def title(self):
            return self.TITLE

        def begin(self):
            try:
                from .fwsketch.cursor import ToolCursor
                self.s.viewport.setCursor(ToolCursor(self.CURSOR, self.s.ratio).cursor())
            except Exception:
                try:
                    self.s.viewport.setCursor(QtCore.Qt.CrossCursor)
                except Exception as _fw_err:
                    _fw_log("sketch3d.py:5838", _fw_err)
            self.s.status(self.HINT % {"plane": self.s.plane} if "%(" in self.HINT else self.HINT)
            self.move(*self.s.cursor())

        def end(self):
            try:
                self.s.viewport.unsetCursor()
            except Exception as _fw_err:
                _fw_log("sketch3d.py:5846", _fw_err)
            self.s.status("")
            self.s.tool_ended(self)

        def plane_changed(self):
            self.move(*self.s.cursor())

        def anchor(self):
            return (0.0, 0.0, 0.0)

        def prev(self):
            return None

        def exclude(self):
            return ()

        def plain(self):
            return bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ControlModifier)

        def move(self, x, y):
            sn = self.s.snap(x, y, self.anchor(), self.prev(), self.exclude(), self.plain())
            self.last = sn
            self.s.cursor_pos = sn.pos
            self.draw(sn)

        def draw(self, sn):
            self.s.tool_drawing(guides=[sn.guide] if sn.guide else (), label=sn.label, label_at=sn.pos)

        def press(self, x, y):
            self.move(x, y)
            self.click(self.last)

        def release(self, x, y, dragged):
            pass

        def double_click(self, x, y):
            self.press(x, y)

        def right_click(self):
            self.end()

        def click(self, sn):
            pass

        # ---- writing a new point
        def place(self, sn, pts, rels, prev_index=None, plane=None):
            """The index of the point sn lands on (an existing point, or a new one with its
            relation); pts and rels grow in place. plane: the sketch plane sn was clicked on, when
            that was before a Tab (dimension review 11-19), else the one in use."""
            if sn.point is not None:
                return sn.point
            plane = plane or self.s.plane
            on_custom = self.s.custom is not None and plane == self.s.custom["name"]
            on_sketch_plane = self.s.sketch_planes().get(plane)
            pts.append(sn.pos)
            i = len(pts) - 1
            if sn.relation is not None and not self.plain():
                kind = sn.relation[0]
                if kind == "AtRef":
                    rels.append(S.Relation("AtRef", [i], list(sn.pos), (sn.relation[1], sn.relation[2])))
                elif kind == "OnArc":
                    rels.append(S.Relation("OnArc", [sn.relation[1], sn.relation[2], i], list(sn.relation[3])))
                elif kind in S.MODEL:
                    rels.append(model_relation(self.s.doc, kind, i, sn.relation[1], sn.relation[2]))
                else:
                    rels.append(S.Relation(kind, [i, sn.relation[1], sn.relation[2]]))
            elif sn.free and on_custom and not self.plain():
                obj_name, sub = self.s.custom["ref"]
                rels.append(model_relation(self.s.doc, "OnPlane", i, obj_name, sub))
            elif sn.free and on_sketch_plane is not None and not self.plain():
                a, b, c = self.s.ents[on_sketch_plane].points[:3]
                rels.append(S.Relation("OnSketchPlane", [i, a, b, c]))
            return i

    class LineTool(Tool):
        RUNNING_MENU = True
        TITLE = "Line"
        CURSOR = "Sketcher_Pointer_Create_Lineset"
        HINT = "3D Line: click the start, then each next point; double-click or Esc ends (right-click: the menu, " \
               "Select ends). " \
               "Tab changes the sketch plane."

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.chain = []           # point indexes placed in this chain (None: the first, not written yet)
            self.pending = None       # the Snap of that first point
            self._pending_pos = None
            self.midpoint = False     # Midpoint Line: the first click is the line's middle

        def title(self):
            return "Centerline" if self.construction else "Line"

        def set_midpoint(self, on):
            self.midpoint = bool(on)
            self.chain, self.pending = [], None
            self.move(*self.s.cursor())

        def draw(self, sn):
            lines = [[self.prev(), sn.pos]] if self.chain else []
            if self.midpoint and self.chain:
                lines = [[_sub(_mul(self.prev(), 2.0), sn.pos), sn.pos]]
            text = sn.label
            if self.chain:
                length = _len(_sub(sn.pos, self.prev())) * (2.0 if self.midpoint else 1.0)
                text = (sn.label + "  " if sn.label else "") + _fmt(length)
            guides = [g for g in (sn.guide, getattr(sn, "align", None)) if g]
            self.s.tool_drawing(lines=lines, guides=guides, label=text, label_at=sn.pos,
                                points=[sn.pos] if sn.point is not None or sn.relation else ())

        def click(self, sn):
            s = self.s
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            if self.midpoint:
                self._midpoint_click(sn, pts, ents, rels)
                return
            if not self.chain:
                if sn.point is not None:
                    self.chain = [sn.point]
                    return
                # the first point is written with the first line (no lone point in the sketch)
                self.pending = sn
                self.chain = [None]
                self._pending_pos = sn.pos
                self._pending_plane = s.plane      # its plane, should Tab change it before the next click
                return
            start = self.chain[-1]
            if start is None:
                a = self.place(self.pending, pts, rels, plane=getattr(self, "_pending_plane", None))
            else:
                a = start
            b = self.place(sn, pts, rels)
            if a == b:
                return
            ents.append(S.Entity("L", [a, b], self.construction))
            force, self.force = getattr(self, "force", None), None
            if force in ("AlongX", "AlongY", "AlongZ"):
                rels = [r for r in rels if not (r.kind in ("AlongX", "AlongY", "AlongZ") and r.points == [a, b])]
                rels.append(S.Relation(force, [a, b]))
            elif sn.axis is not None and not self.plain():
                rels.append(self.s.axis_relation(sn.axis, a, b))
            elif not self.plain() and (sn.point is not None or (sn.relation or ("",))[0] == "AtRef"):

                # Along X/Y/Z with the Coincident
                along = _axis_along(_sub(pts[b], pts[a]), self.s.axes()[1])
                if along is not None:
                    rels.append(S.Relation(along, [a, b]))
            if getattr(self, "fix_first", False) and not any(r.kind == "Fix" and r.points == [a] for r in rels):
                rels.append(S.Relation("Fix", [a], list(pts[a])))
            self.fix_first = False
            closes = len(self.chain) > 1 and b == self.chain[0]
            s.write("Line", pts, ents, rels)
            self.chain[-1] = a
            self.chain.append(b)
            if closes or (sn.point is not None and len(s.entities_of_point(b)) > 1):

                self.chain = []

        def _midpoint_click(self, sn, pts, ents, rels):
            if not self.chain:
                self.pending, self.chain, self._pending_pos = sn, [None], sn.pos
                self._pending_plane = self.s.plane
                return
            m = self.pending
            if _len(_sub(sn.pos, m.pos)) < 1e-9:
                return
            mi = self.place(m, pts, rels, plane=getattr(self, "_pending_plane", None))
            bi = self.place(sn, pts, rels)
            ai = self.place(Snap(_sub(_mul(m.pos, 2.0), sn.pos), free=True), pts, rels)
            ents.append(S.Entity("L", [ai, bi], self.construction))
            if m.point is None:
                ents.append(S.Entity("P", [mi], True))      # the middle stays as a sketch point
            rels.append(S.Relation("Midpoint", [mi, ai, bi]))
            if sn.axis is not None and not self.plain():
                rels.append(self.s.axis_relation(sn.axis, ai, bi))
            self.chain, self.pending = [], None
            self.s.write("Midpoint Line", pts, ents, rels)

        def prev(self):
            if not self.chain:
                return None
            if self.chain[-1] is None:
                return self._pending_pos
            return self.s.pts[self.chain[-1]]

        def anchor(self):
            p = self.prev()
            return p if p is not None else (0.0, 0.0, 0.0)

        def exclude(self):
            return (self.chain[-1],) if self.chain and self.chain[-1] is not None else ()

        def release(self, x, y, dragged):

            if dragged and len(self.chain) == 1:
                self.move(x, y)
                self.click(self.last)

        def double_click(self, x, y):
            if self.chain:
                self.chain = []
                self.move(x, y)
            else:
                self.press(x, y)

        def right_click(self):
            if self.chain:
                self.chain = []
                self.move(*self.s.cursor())
            else:
                self.end()

    class SplineTool(Tool):
        RUNNING_MENU = True
        TITLE = "Spline"
        CURSOR = "Sketcher_Pointer_Create_BSpline"
        HINT = "3D Spline: click the points it goes through; double-click, right-click or Esc ends it, a click " \
               "on its first point closes it. Tab changes the sketch plane."

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.through = []          # Snaps

        def anchor(self):
            return self.through[-1].pos if self.through else (0.0, 0.0, 0.0)

        def prev(self):
            return None                # no Along X/Y/Z on a spline

        def draw(self, sn):
            lines = []
            pos = [t.pos for t in self.through] + [sn.pos]
            if len(pos) >= 3:
                try:
                    e = spline_edge(pos)
                    lines = [[(v.x, v.y, v.z) for v in e.discretize(Number=60)]]
                except Exception:
                    lines = [pos]
            elif len(pos) == 2:
                lines = [pos]
            self.s.tool_drawing(lines=lines, label=sn.label, label_at=sn.pos,
                                points=[t.pos for t in self.through])

        def click(self, sn):
            if not self.through and self.s.fresh_spline is not None:
                self.s.fresh_spline = None            # a new spline: the last one's handles go
            if len(self.through) > 2 and _len(_sub(sn.pos, self.through[0].pos)) < 1e-9:
                self.through.append(self.through[0])
                self.finish(closed=True)
                return
            self.through.append(sn)
            self.draw(sn)

        def finish(self, closed=False):
            through, self.through = self.through, []
            if len(through) < 2:
                return
            s = self.s
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            idx = []
            for k, sn in enumerate(through):
                if closed and k == len(through) - 1:
                    idx.append(idx[0])
                    continue
                idx.append(self.place(sn, pts, rels))
            ents.append(S.Entity("S", idx, self.construction))
            if getattr(self, "fix_first", False):
                rels.append(S.Relation("Fix", [idx[0]], list(pts[idx[0]])))
                self.fix_first = False
            s.write("Spline", pts, ents, rels)
            s.fresh_spline = len(s.ents) - 1
            s.redraw()

        def double_click(self, x, y):
            # the double-click's first press already added the point
            self.finish()
            self.move(x, y)

        def right_click(self):
            if self.through:
                self.finish()
                self.move(*self.s.cursor())
            else:
                self.end()

        def end(self):
            if self.through:
                self.finish()
            super().end()

    class StyleSplineTool(SplineTool):
        ""

        TITLE = "Style Spline"
        HINT = "Style Spline: click the control vertices; double-click, right-click or Esc ends it. Tab changes " \
               "the sketch plane."

        def draw(self, sn):
            pos = [t.pos for t in self.through] + [sn.pos]
            lines = []
            if len(pos) >= 2:
                lines.append(pos)                 # the control polygon
            if len(pos) >= 3:
                try:
                    lines.append([(v.x, v.y, v.z) for v in style_edge(pos).discretize(Number=60)])
                except Exception as _fw_err:
                    _fw_log("sketch3d.py:6145", _fw_err)
            self.s.tool_drawing(lines=lines, label=sn.label, label_at=sn.pos, points=[t.pos for t in self.through])

        def click(self, sn):
            if len(self.through) >= 25:
                self.finish()
                return
            self.through.append(sn)
            self.draw(sn)

        def finish(self, closed=False):
            through, self.through = self.through, []
            if len(through) < 2:
                return
            s = self.s
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            idx = [self.place(sn, pts, rels) for sn in through]
            if len(set(idx)) < len(idx):
                return
            ents.append(S.Entity("S", idx, self.construction))
            if len(idx) > 2:
                rels.append(S.Relation("SplineStyle", [idx[0], idx[-1]]))
            s.write("Style Spline", pts, ents, rels)
            s.redraw()

    class RouteLineTool(Tool):
        """Route Line: pick a start and an end point; a route of lines along X, Y and Z joins them (Along
        relations on each); Alternate Path (the page's button) goes round the axis orders; OK keeps it."""
        TITLE = "Route Line"
        CURSOR = "Sketcher_Pointer_Create_Lineset"
        HINT = "Route Line: click the start point, then the end point; Alternate Path changes the route; OK " \
               "(Enter) keeps it."
        ORDERS = ("XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX")

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.ends = []            # the Snaps of the start and the end
            self.order = 0

        def route(self, a=None, b=None):
            """The route's corners from a to b in the current axis order (no zero-length legs), and the axis of
            each leg."""
            a = a if a is not None else self.ends[0].pos
            b = b if b is not None else self.ends[1].pos
            corners, axes = [tuple(a)], []
            p = list(a)
            for ax in self.ORDERS[self.order]:
                i = "XYZ".index(ax)
                if abs(b[i] - p[i]) < 1e-9:
                    continue
                p[i] = b[i]
                corners.append(tuple(p))
                axes.append(ax)
            return corners, axes

        def alternate(self):
            """Alternate Path: the next axis order (one giving another route)."""
            if len(self.ends) < 2:
                self.order = (self.order + 1) % len(self.ORDERS)
                return
            now = self.route()[0]
            for _ in range(len(self.ORDERS)):
                self.order = (self.order + 1) % len(self.ORDERS)
                if self.route()[0] != now:
                    break
            self.move(*self.s.cursor())

        def draw(self, sn):
            if not self.ends:
                return super().draw(sn)
            b = self.ends[1].pos if len(self.ends) > 1 else sn.pos
            corners = self.route(self.ends[0].pos, b)[0]
            self.s.tool_drawing(lines=[corners] if len(corners) > 1 else (), label=sn.label, label_at=sn.pos)

        def click(self, sn):
            if len(self.ends) < 2:
                self.ends.append(sn)
                if len(self.ends) == 2 and math.dist(self.ends[0].pos, self.ends[1].pos) < 1e-9:
                    self.ends.pop()
            self.picks_changed()

        def picks_changed(self):
            try:
                from . import sketch3dpm
                page = sketch3dpm.current()
                if page is not None and hasattr(page, "picks_changed"):
                    page.picks_changed()
            except Exception as _fw_err:
                _fw_log("sketch3d.py:6233", _fw_err)

        def apply(self):
            """OK: the route written (one undo step)."""
            if len(self.ends) < 2:
                return "Route Line: pick the start point and the end point."
            s = self.s
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            corners, axes = self.route()
            first = self.place(self.ends[0], pts, rels)
            idx = [first]
            for c in corners[1:-1]:
                pts.append(tuple(c))
                idx.append(len(pts) - 1)
            idx.append(self.place(self.ends[1], pts, rels))
            for (a, b), ax in zip(zip(idx[:-1], idx[1:]), axes):
                ents.append(S.Entity("L", [a, b], self.construction))
                rels.append(S.Relation("Along" + ax, [a, b]))
            s.write("Route Line", pts, ents, rels)
            self.ends = []
            return None

    class PenTool(Tool):
        ""




        TITLE = "Pen Sketch"
        CURSOR = "Sketcher_Pointer_Create_BSpline"
        HINT = "Pen Sketch: draw ink with the left mouse button (or a pen) on the %(plane)s plane; Convert to " \
               "Shape or Convert to Entities turns it into sketch entities. Tab changes the plane; Esc ends."
        MODES = ("Draw", "Eraser", "Select", "Ruler")

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.stroke = None
            self.mode = "Draw"

        def set_mode(self, mode):
            if mode == "Ruler" and self.mode == "Ruler":
                self.s.ruler = None          # the Ruler again takes it away
                mode = "Draw"
            self.mode = mode if mode in self.MODES else "Draw"
            self.s.redraw()

        def _at(self, x, y):
            return tuple(self.s.snap(x, y, (0.0, 0.0, 0.0), None, (), True).pos)

        def _near(self, x, y):
            """Ink strokes within reach of the pointer (screen pixels)."""
            tol = self.s.px() * 1.5
            out = []
            for n, stroke in enumerate(self.s.ink):
                if any(self.s._screen_dist(p, x, y) <= tol for p in stroke):
                    out.append(n)
                    continue
                sp = [self.s.to_screen(p) for p in stroke]
                for a, b in zip(sp[:-1], sp[1:]):
                    if a is None or b is None:
                        continue
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    L2 = dx * dx + dy * dy
                    f = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
                    if math.hypot(x - a[0] - f * dx, y - a[1] - f * dy) <= tol:
                        out.append(n)
                        break
            return out

        def move(self, x, y):
            if self.stroke is not None and self.s._press is not None:
                p = self._at(x, y)
                if self.mode == "Draw":
                    if math.dist(p, self.stroke[-1]) > 1e-9:
                        self.stroke.append(p)
                    self.s.tool_drawing(lines=[self.stroke] if len(self.stroke) > 1 else ())
                elif self.mode == "Eraser":
                    self.erase(x, y)
                elif self.mode == "Ruler":
                    self.s.ruler = (self.stroke[0], p)
                    self.s.redraw()
                return
            self.s.cursor_pos = self._at(x, y)
            self.s.tool_drawing()

        def press(self, x, y):
            p = self._at(x, y)
            if self.mode == "Select":
                hit = self._near(x, y)
                if not hit:
                    self.s.ink_picked = set()
                else:
                    (self.s.ink_picked.discard if hit[0] in self.s.ink_picked else self.s.ink_picked.add)(hit[0])
                self.s.redraw()
                return
            self.stroke = [p]
            if self.mode == "Eraser":
                self.erase(x, y)

        def double_click(self, x, y):
            pass

        def erase(self, x, y):
            hit = set(self._near(x, y))
            if hit:
                self.s.set_ink([st for n, st in enumerate(self.s.ink) if n not in hit])

        def release(self, x, y, dragged):
            stroke, self.stroke = self.stroke, None
            if stroke and self.mode == "Draw":
                self.add(stroke)
            elif stroke and self.mode == "Ruler":
                r = getattr(self.s, "ruler", None)
                if r is None or math.dist(r[0], r[1]) < 1e-9:
                    self.s.ruler = None
                self.mode = "Draw"
            self.s.tool_drawing()

        def add(self, stroke):
            """A stroke drawn: kept as ink (straight along the ruler when it follows it)."""
            if len(stroke) < 2:
                return None
            r = getattr(self.s, "ruler", None)
            if r is not None and math.dist(r[0], r[1]) > 1e-9:
                u = _unit(_sub(r[1], r[0]))
                tol = 14 * self.s.world_per_px(*(self.s.to_screen(stroke[0]) or (0, 0)), stroke[0]) * self.s.ratio
                if all(_len(_cross(_sub(p, r[0]), u)) <= tol for p in stroke):
                    t0, t1 = _dot(_sub(stroke[0], r[0]), u), _dot(_sub(stroke[-1], r[0]), u)
                    stroke = [_add(r[0], _mul(u, t0)), _add(r[0], _mul(u, t1))]
            self.s.set_ink(self.s.ink + [[tuple(p) for p in stroke]])
            return len(self.s.ink) - 1

    class PointTool(Tool):
        TITLE = "Point"
        CURSOR = "Sketcher_Pointer_Create_Point"
        HINT = "3D Point: click to place sketch points. Tab changes the sketch plane."

        def click(self, sn):
            if sn.point is not None:
                return
            s = self.s
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            i = self.place(sn, pts, rels)
            ents.append(S.Entity("P", [i]))
            s.write("Point", pts, ents, rels)

    class DimensionTool(Tool):
        TITLE = "Smart Dimension"
        CURSOR = "Sketcher_Crosshair"
        HINT = "Smart Dimension: pick a line (its length), two points (the distance), two lines (the angle; " \
               "parallel: the distance between them), a point and a line (the distance square to it), a circle or " \
               "an arc (diameter, radius), a point and a plane or flat face of the model (the distance square to " \
               "it) or a line and one (the angle to it)."


        DIM_TYPES = ("Absolute", "Along X", "Along Y", "Along Z")

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.first = None         # ("P", i) or ("E", i) picked first
            self.dim_type = "Absolute"

        def next_type(self):
            self.dim_type = self.DIM_TYPES[(self.DIM_TYPES.index(self.dim_type) + 1) % len(self.DIM_TYPES)]
            self.s.status("Smart Dimension: %s (Tab changes it)" % self.dim_type)
            self.move(*self.s.cursor())

        def takes_tab(self):
            """Tab goes round the distance types once a point or a line is picked (else it changes the plane)."""
            return self.first is not None and (self.first[0] == "P" or self._is_line(self.s, self.first))

        def move(self, x, y):
            self.s.cursor_pos = None
            hit = self.s.pick(x, y, dims=False)
            self.s.hover = hit
            label = self._preview()
            if self.takes_tab() and self.dim_type != "Absolute":
                label = (label + "  " if label else "") + self.dim_type
            self.s.tool_drawing(label=label, label_at=self.s.on_plane(x, y, self._anchor()))

        def _anchor(self):
            if self.first is None:
                return (0.0, 0.0, 0.0)
            k, i = self.first
            return self.s.pts[i] if k == "P" else self.s.pts[self.s.ents[i].points[0]]

        def _preview(self):
            if self.first is not None and self.first[0] == "E" and self._is_line(self.s, self.first):
                a, b = self.s.ents[self.first[1]].points[:2]
                d = _sub(self.s.pts[b], self.s.pts[a])
                if self.dim_type != "Absolute":
                    return _fmt(abs(d["XYZ".index(self.dim_type[-1])]))
                return _fmt(_len(d))
            return ""

        def _typed(self, rel):
            """A distance between two points as the type picked with Tab: Along X, Y or Z."""
            if rel is None or rel.kind != "Distance" or self.dim_type == "Absolute":
                return rel
            k = "XYZ".index(self.dim_type[-1])
            a, b = rel.points
            d = self.s.pts[b][k] - self.s.pts[a][k]
            return S.Relation("AxisDistance", [a, b], [abs(d), 1.0 if d >= 0 else -1.0, float(k)])

        @staticmethod
        def _is_line(s, hit):
            return hit is not None and hit[0] == "E" and s.ents[hit[1]].kind == "L"

        def _front_line_hit(self, x, y, hit):
            """Prefer the native frontmost 3D line when screen projections overlap.

            Match the native hit point geometrically rather than interpreting EdgeN
            as an entity index: the shape can reorder edges into wires. Leave point
            and construction picks, ambiguous matches and missing hit data alone.
            """
            s = self.s
            if not self._is_line(s, hit) or s.ents[hit[1]].construction:
                return hit
            try:
                info = s.view.getObjectInfo((int(x), int(y))) or {}
                component = str(info.get("Component", ""))
                if info.get("Object") != s.obj.Name or not component.startswith("Edge"):
                    return hit
                # A native curved edge can cross a line at the hit point. Only
                # redirect a line pick if the frontmost native edge is itself a line.
                native_edge = s.obj.Shape.getElement(component)
                if type(native_edge.Curve).__name__ not in ("Line", "LineSegment"):
                    return hit
                doc_name = info.get("Document")
                if doc_name and doc_name != s.doc.Name:
                    return hit
                point = tuple(float(info[k]) for k in ("x", "y", "z"))
                if not all(math.isfinite(v) for v in point):
                    return hit
                tolerance = 4e-7 * max([1.0] + [abs(v) for v in point])
                candidates = []
                for k, e in enumerate(s.ents):
                    if e.kind != "L" or e.construction:
                        continue
                    a, b = (s.pts[i] for i in e.points[:2])
                    if s._seg_dist(a, b, x, y)[0] >= s.px():
                        continue
                    distance = _seg_closest(a, b, point, point)[0]
                    if distance <= tolerance:
                        candidates.append(k)
                if len(candidates) == 1:
                    return ("E", candidates[0])
            except Exception as _fw_err:
                # A stale shape, unavailable native hit or unusual entity must
                # never prevent the existing screen-space picker from working.
                _fw_log("sketch3d.py:6481", _fw_err)
            return hit

        @staticmethod
        def _is_round(s, hit):
            return hit is not None and hit[0] == "E" and s.ents[hit[1]].kind in ("C", "A")

        def _model_plane(self, x, y):
            """(object name, element) of a datum plane or flat face of the model under the pointer."""
            s = self.s
            try:
                info = s.view.getObjectInfo((int(x), int(y)))
            except Exception:
                info = None
            # The active sketch can be in front of the intended model face.
            # In that case inspect the other objects on this ray, just as Spline
            # on Surface does; do not look through a different foreground model.
            if not info or info.get("Object") in (None, s.obj.Name):
                try:
                    candidates = s.view.getObjectsInfo((int(x), int(y))) or []
                except Exception:
                    candidates = []
            else:
                candidates = [info]
            for info in candidates:
                name = info.get("Object")
                if name in (None, s.obj.Name):
                    continue
                o = s.doc.getObject(name)
                if o is None or is_sketch3d(o):
                    continue
                comp = info.get("Component", "") or ""
                sub = comp if comp.startswith("Face") else ""
                if sub and is_plane_pick(o, sub):
                    return o.Name, sub
                if not sub and is_plane_pick(o, ""):
                    return o.Name, "-"
                # A non-planar foreground object occludes geometry behind it.
                return None
            return None

        def _plane_distance(self, p, name, element):
            pl = plane_of(self.s.doc, name, element)
            if pl is None:
                return None
            b, n = pl
            n = _mul(n, 1.0 / max(_len(n), 1e-12))
            signed = _dot(_sub(self.s.pts[p], b), n)
            return S.Relation("PlaneDistance", [p], [abs(signed), 1.0 if signed >= 0 else -1.0] + list(b) + list(n),
                              (name, element))

        def press(self, x, y):
            s = self.s
            hit = s.pick(x, y, dims=False)
            first = self.first
            if first is None:
                hit = self._front_line_hit(x, y, hit)
                if hit is not None and (hit[0] == "P" or self._is_line(s, hit) or self._is_round(s, hit)):
                    self.first = hit
                    s.select([hit])
                return
            rel = None
            if self._is_round(s, first):
                # a circle's diameter, an arc's radius, placed where the click is
                e = s.ents[first[1]]
                c, a = e.points[:2]
                r = _len(_sub(s.pts[a], s.pts[c]))
                rel = S.Relation("Diameter", [c, a], [2 * r]) if e.kind == "C" else S.Relation("Radius", [c, a], [r])
            elif first[0] == "P" and hit is None:
                plane = self._model_plane(x, y)
                if plane is None:
                    return
                rel = self._plane_distance(first[1], *plane)
            elif first[0] == "P" and hit is not None and hit[0] == "P" and hit[1] != first[1]:
                a, b = first[1], hit[1]
                rel = S.Relation("Distance", [a, b], [_len(_sub(s.pts[a], s.pts[b]))])
            elif first[0] == "E" and self._is_line(s, hit) and hit[1] != first[1]:
                a, b = s.ents[first[1]].points[:2]
                c, d = s.ents[hit[1]].points[:2]
                ang = _line_angle(s.pts, a, b, c, d)
                if ang < 1e-3 or ang > 180 - 1e-3:

                    rel = S.Relation("LineDistance", [c, a, b], [self._line_gap(c, a, b)])
                else:
                    rel = S.Relation("Angle", [a, b, c, d], [ang])
            elif (first[0] == "E" and hit is not None and hit[0] == "P" and hit[1] not in s.ents[first[1]].points) \
                    or (first[0] == "P" and self._is_line(s, hit) and first[1] not in s.ents[hit[1]].points):
                # a point and a line: the distance square to the line
                p, k = (hit[1], first[1]) if first[0] == "E" else (first[1], hit[1])
                a, b = s.ents[k].points[:2]
                rel = S.Relation("LineDistance", [p, a, b], [self._line_gap(p, a, b)])
            elif first[0] == "E" and self._is_line(s, first) and hit is None and self._model_plane(x, y) is not None:
                # a line and a plane or flat face of the model: the angle between them
                a, b = s.ents[first[1]].points[:2]
                name, element = self._model_plane(x, y)
                pl = plane_of(s.doc, name, element)
                if pl is None:
                    return
                n = _unit(pl[1])
                u = _unit(_sub(s.pts[b], s.pts[a]))
                deg = math.degrees(math.asin(min(1.0, abs(_dot(u, n)))))
                rel = S.Relation("PlaneAngle", [a, b], [deg] + list(pl[0]) + list(n), (name, element))
            elif first[0] == "E" and (hit == first or not self._is_line(s, hit)):
                # a click away from the line (or on it again, or on a point) places its length
                a, b = s.ents[first[1]].points[:2]
                rel = S.Relation("Distance", [a, b], [_len(_sub(s.pts[a], s.pts[b]))])
            if rel is None:
                return
            rel = self._typed(rel)
            self.first = None
            self.dim_type = "Absolute"
            s.select([])
            why = s.add_relation(rel)
            if why:
                s.status(why)
                return
            from . import sketch3dpm
            sketch3dpm.modify_dimension(s, len(s.rels) - 1)

        def _line_gap(self, p, a, b):
            s = self.s
            u = _unit(_sub(s.pts[b], s.pts[a]))
            w = _sub(s.pts[p], s.pts[a])
            return _len(_sub(w, _mul(u, _dot(w, u))))

        def right_click(self):
            if self.first is not None:
                self.first = None
                self.s.select([])
            else:
                self.end()

    class CircleTool(Tool):
        """Circle (and the arcs below): on the sketch plane through the centre, which keeps the plane
        it was drawn on (its ArcPlane)."""
        TITLE = "Circle"
        CURSOR = "Sketcher_Pointer_Create_Circle"
        HINT = "3D Circle: click the center, then a point on the rim. The circle lies on the sketch plane " \
               "(Tab changes it)."

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.picks = []           # Snaps clicked so far

        def anchor(self):
            return self.picks[0].pos if self.picks else (0.0, 0.0, 0.0)

        def normal(self):
            return self.s.axes()[0]

        def move(self, x, y):
            if not self.picks:
                super().move(x, y)
                return
            sn = self.on_circle_plane(x, y)
            self.last = sn
            self.s.cursor_pos = sn.pos
            self.draw(sn)

        def on_circle_plane(self, x, y):
            """The pointer on the plane through the centre: a sketch point there, else the plane."""
            c, n = self.picks[0].pos, self.normal()
            if not self.plain():
                hit = self.s.pick(x, y, points=True, entities=False, dims=False)
                if hit is not None:
                    p = self.s.pts[hit[1]]
                    if abs(_dot(_sub(p, c), n)) < 1e-6 * max(1.0, _len(_sub(p, c))):
                        return Snap(p, point=hit[1], label="Coincident")
            return Snap(self.s.on_plane(x, y, c), free=True)

        def place_arc_end(self, sn, pts, rels):
            ""


            return self.place(sn, pts, rels)

        def draw(self, sn):
            if not self.picks:
                super().draw(sn)
                return
            c = self.picks[0].pos
            r = _len(_sub(sn.pos, c))
            lines = [arc_points(c, sn.pos, sn.pos, self.normal(), full=True)] if r > 1e-9 else []
            self.s.tool_drawing(lines=lines, label="R " + _fmt(r), label_at=sn.pos, points=[c])

        def click(self, sn):
            if not self.picks:
                self.picks = [sn]
                return
            c = self.picks[0]
            if _len(_sub(sn.pos, c.pos)) < 1e-9:
                return
            s = self.s
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            ci = self.place(c, pts, rels)
            ai = self.place(sn, pts, rels)
            ents.append(S.Entity("C", [ci, ai], self.construction))
            rels.append(S.Relation("ArcPlane", [ci, ai, ai], list(self.normal())))
            self.picks = []
            s.write("Circle", pts, ents, rels)

        def right_click(self):
            if self.picks:
                self.picks = []
                self.move(*self.s.cursor())
            else:
                self.end()

        def double_click(self, x, y):
            self.press(x, y)

    class CenterArcTool(CircleTool):
        TITLE = "Centerpoint Arc"
        CURSOR = "Sketcher_Pointer_Create_Arc"
        HINT = "3D Centerpoint Arc: click the center, then the start, then the end. The arc lies on the sketch " \
               "plane (Tab changes it)."

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.sweep = 0.0          # how far the pointer went round the centre (its sign: the arc's way)
            self._angle = None

        def _end_point(self, q):
            c, a = self.picks[0].pos, self.picks[1].pos
            n = self.normal()
            r, u, v = arc_frame(c, a, n)
            d = _sub(q, c)
            t = math.atan2(_dot(d, v), _dot(d, u))
            if self._angle is not None:
                step = (t - self._angle + math.pi) % (2 * math.pi) - math.pi
                self.sweep += step
            self._angle = t
            return _add(c, _add(_mul(u, r * math.cos(t)), _mul(v, r * math.sin(t))))

        def arc_normal(self):
            n = self.normal()
            return n if self.sweep >= 0 else _mul(n, -1.0)

        def move(self, x, y):
            if len(self.picks) < 2:
                super().move(x, y)
                return
            raw = self.on_circle_plane(x, y)     # a sketch point on the arc's plane, else the plane
            q = self._end_point(raw.pos)
            radius = _len(_sub(self.picks[1].pos, self.picks[0].pos))
            if _len(_sub(q, raw.pos)) > 1e-6 * max(1.0, radius):
                sn = Snap(q, free=True)
            else:
                sn = Snap(q, point=raw.point, relation=raw.relation, label=raw.label,
                          axis=raw.axis, guide=raw.guide, free=raw.free)
            self.last = sn
            self.s.cursor_pos = sn.pos
            self.draw(sn)

        def draw(self, sn):
            if len(self.picks) < 2:
                if self.picks:
                    c = self.picks[0].pos
                    self.s.tool_drawing(lines=[[c, sn.pos]], label="R " + _fmt(_len(_sub(sn.pos, c))),
                                        label_at=sn.pos, points=[c])
                else:
                    Tool.draw(self, sn)
                return
            c, a = self.picks[0].pos, self.picks[1].pos
            lines = [arc_points(c, a, sn.pos, self.arc_normal())] if abs(self.sweep) > 1e-6 else []
            self.s.tool_drawing(lines=lines, guides=[[c, a], [c, sn.pos]],
                                label=_fmt_angle(math.degrees(abs(self.sweep))), label_at=sn.pos, points=[c, a])

        def click(self, sn):
            if len(self.picks) < 2:
                if self.picks and _len(_sub(sn.pos, self.picks[0].pos)) < 1e-9:
                    return
                self.picks.append(sn)
                self.sweep, self._angle = 0.0, None
                return
            if abs(self.sweep) < 1e-6:
                return
            s = self.s
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            ci = self.place(self.picks[0], pts, rels)
            ai = self.place_arc_end(self.picks[1], pts, rels)
            bi = self.place_arc_end(sn, pts, rels)
            ents.append(S.Entity("A", [ci, ai, bi], self.construction))
            rels.append(S.Relation("ArcPlane", [ci, ai, bi], list(self.arc_normal())))
            self.picks = []
            s.write("Arc", pts, ents, rels)

    class ThreePointArcTool(CircleTool):
        TITLE = "3 Point Arc"
        CURSOR = "Sketcher_Pointer_Create_3PointArc"
        HINT = "3D 3 Point Arc: click the start, then the end, then a point the arc goes through. The arc " \
               "lies on the sketch plane (Tab changes it)."

        def _circle(self, m):
            """(centre, normal) of the arc from the start to the end through m, else None."""
            a, b = self.picks[0].pos, self.picks[1].pos
            n = self.normal()
            m = _sub(m, _mul(n, _dot(_sub(m, a), n)))
            b = _sub(b, _mul(n, _dot(_sub(b, a), n)))
            p, q = _sub(a, m), _sub(b, m)
            cr = (p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0])
            l2 = _dot(cr, cr)
            if l2 < 1e-12 * max(1.0, _dot(p, p) * _dot(q, q)):
                return None
            w = _sub(_mul(q, _dot(p, p)), _mul(p, _dot(q, q)))
            num = (w[1] * cr[2] - w[2] * cr[1], w[2] * cr[0] - w[0] * cr[2], w[0] * cr[1] - w[1] * cr[0])
            c = _add(m, _mul(num, 1.0 / (2.0 * l2)))
            # counterclockwise about n from a to b passes m? else the other way round
            if arc_sweep(c, a, m, n) > arc_sweep(c, a, b, n):
                n = _mul(n, -1.0)
            return c, n, b

        def move(self, x, y):
            if len(self.picks) < 1:
                Tool.move(self, x, y)
                return
            sn = self.on_circle_plane(x, y) if len(self.picks) == 1 else \
                Snap(self.s.on_plane(x, y, self.picks[0].pos), free=True)
            self.last = sn
            self.s.cursor_pos = sn.pos
            self.draw(sn)

        def draw(self, sn):
            if not self.picks:
                Tool.draw(self, sn)
                return
            if len(self.picks) == 1:
                a = self.picks[0].pos
                self.s.tool_drawing(lines=[[a, sn.pos]], label=_fmt(_len(_sub(sn.pos, a))), label_at=sn.pos,
                                    points=[a])
                return
            got = self._circle(sn.pos)
            a = self.picks[0].pos
            if got is None:
                self.s.tool_drawing(lines=[[a, self.picks[1].pos]], label_at=sn.pos, points=[a, self.picks[1].pos])
                return
            c, n, b = got
            self.s.tool_drawing(lines=[arc_points(c, a, b, n)], label="R " + _fmt(_len(_sub(a, c))),
                                label_at=sn.pos, points=[a, b])

        def click(self, sn):
            if len(self.picks) < 2:
                if self.picks and _len(_sub(sn.pos, self.picks[0].pos)) < 1e-9:
                    return
                self.picks.append(sn)
                return
            got = self._circle(sn.pos)
            if got is None:
                return
            c, n, _ = got
            s = self.s
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            ai = self.place_arc_end(self.picks[0], pts, rels)
            bi = self.place_arc_end(self.picks[1], pts, rels)
            ci = self.place(Snap(c, free=True), pts, rels)
            ents.append(S.Entity("A", [ci, ai, bi], self.construction))
            rels.append(S.Relation("ArcPlane", [ci, ai, bi], list(n)))
            self.picks = []
            s.write("Arc", pts, ents, rels)

    class PerimeterCircleTool(CircleTool):
        TITLE = "Perimeter Circle"
        CURSOR = "Sketcher_Pointer_Create_3PointCircle"
        HINT = "3D Perimeter Circle: click three points on the rim. The circle lies on the sketch plane " \
               "(Tab changes it)."

        def move(self, x, y):
            if not self.picks:
                Tool.move(self, x, y)
                return
            sn = Snap(self.s.on_plane(x, y, self.picks[0].pos), free=True)
            self.last = sn
            self.s.cursor_pos = sn.pos
            self.draw(sn)

        def draw(self, sn):
            pts = [p.pos for p in self.picks]
            if len(pts) < 2:
                Tool.draw(self, sn) if not pts else self.s.tool_drawing(lines=[[pts[0], sn.pos]], label_at=sn.pos,
                                                                        points=pts)
                return
            got = circumcentre(pts[0], pts[1], sn.pos, self.normal())
            if got is None:
                self.s.tool_drawing(lines=[pts + [sn.pos]], label_at=sn.pos, points=pts)
                return
            c, n = got
            self.s.tool_drawing(lines=[arc_points(c, pts[0], pts[0], n, full=True)],
                                label="R " + _fmt(_len(_sub(pts[0], c))), label_at=sn.pos, points=pts)

        def click(self, sn):
            if len(self.picks) < 2:
                if self.picks and _len(_sub(sn.pos, self.picks[-1].pos)) < 1e-9:
                    return
                self.picks.append(sn)
                return
            got = circumcentre(self.picks[0].pos, self.picks[1].pos, sn.pos, self.normal())
            if got is None:
                return
            c, n = got
            s = self.s
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            ai = self.place(self.picks[0], pts, rels)
            ci = self.place(Snap(c, free=True), pts, rels)
            ents.append(S.Entity("C", [ci, ai], self.construction))
            rels.append(S.Relation("ArcPlane", [ci, ai, ai], list(n)))
            self.picks = []
            s.write("Circle", pts, ents, rels)

    class TangentArcTool(CircleTool):
        """Tangent Arc: from the end of a line, leaving it along the line (radius square to the line)."""
        TITLE = "Tangent Arc"
        CURSOR = "Sketcher_Pointer_Create_Arc"
        HINT = "3D Tangent Arc: click the end of a line, then where the arc ends. The arc leaves the line along it."

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.start = None          # (end point index, the line's other end index)

        def _line_end(self, i):
            for e in self.s.ents:
                if e.kind == "L" and i in e.points:
                    return e.points[1] if e.points[0] == i else e.points[0]
            return None

        def _arc(self, q):
            a, o = self.s.pts[self.start[0]], self.s.pts[self.start[1]]
            t = _sub(a, o)
            t = _mul(t, 1.0 / max(_len(t), 1e-12))
            d = _sub(q, a)
            m = _sub(d, _mul(t, _dot(d, t)))
            lm = _len(m)
            if lm < 1e-9:
                return None
            m = _mul(m, 1.0 / lm)
            r = _dot(d, d) / (2.0 * _dot(d, m))
            c = _add(a, _mul(m, r))
            n = (t[1] * d[2] - t[2] * d[1], t[2] * d[0] - t[0] * d[2], t[0] * d[1] - t[1] * d[0])
            n = _mul(n, 1.0 / max(_len(n), 1e-12))
            return c, n

        def move(self, x, y):
            if self.start is None:
                Tool.move(self, x, y)
                return
            sn = self.s.snap(x, y, self.s.pts[self.start[0]], None, (self.start[0],), self.plain())
            self.last = sn
            self.s.cursor_pos = sn.pos
            self.draw(sn)

        def draw(self, sn):
            if self.start is None:
                Tool.draw(self, sn)
                return
            got = self._arc(sn.pos)
            a = self.s.pts[self.start[0]]
            lines = [arc_points(got[0], a, sn.pos, got[1])] if got else [[a, sn.pos]]
            self.s.tool_drawing(lines=lines, label=sn.label, label_at=sn.pos, points=[a])

        def click(self, sn):
            s = self.s
            if self.start is None:
                other = self._line_end(sn.point) if sn.point is not None else None
                if other is None:
                    s.status("Tangent Arc: click the end of a line to start from.")
                    return
                self.start = (sn.point, other)
                return
            got = self._arc(sn.pos)
            if got is None:
                return
            c, n = got
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            o = self.start[1]
            a = self.place_arc_end(Snap(self.s.pts[self.start[0]], point=self.start[0]), pts, rels)
            ci = self.place(Snap(c, free=True), pts, rels)
            bi = self.place_arc_end(sn, pts, rels)
            ents.append(S.Entity("A", [ci, a, bi], self.construction))
            rels.append(S.Relation("ArcPlane", [ci, a, bi], list(n)))
            rels.append(S.Relation("Tangent", [ci, a, o, self.start[0]], list(n)))   # radius square to the line at a
            self.start = None
            s.write("Tangent Arc", pts, ents, rels)

        def right_click(self):
            if self.start is not None:
                self.start = None
                self.move(*self.s.cursor())
            else:
                self.end()

    class RectangleTool(CircleTool):
        ""



        TITLE = "Corner Rectangle"
        CURSOR = "Sketcher_Pointer_Create_Box"
        HINT = "3D Corner Rectangle: click one corner, then the opposite one, on the sketch plane " \
               "(Tab changes it)."
        MODE = "corner"
        NEEDS = 1                 # clicks before the last one

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            centred = self.MODE in ("center", "3center")
            self.lines = centred
            self.lines_from = "From Corners"

        def move(self, x, y):
            if len(self.picks) < self.NEEDS:
                Tool.move(self, x, y) if not self.picks else CircleTool.move(self, x, y)
                return
            CircleTool.move(self, x, y)

        def corners(self, q):
            n, (u, v) = self.s.axes()
            p = self.picks[0].pos
            if self.MODE in ("corner", "center"):
                d = _sub(q, p)
                du, dv = _dot(d, u), _dot(d, v)
                if self.MODE == "center":
                    return [_add(p, _add(_mul(u, su * du), _mul(v, sv * dv)))
                            for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                return [p, _add(p, _mul(u, du)), _add(p, _add(_mul(u, du), _mul(v, dv))), _add(p, _mul(v, dv))]
            p2 = self.picks[1].pos
            if self.MODE == "parallelogram":
                return [p, p2, q, _add(p, _sub(q, p2))]
            if self.MODE == "3corner":
                e = _sub(p2, p)
                w = _sub(q, p2)
            else:                              # 3center: the centre, a side's middle, then the width
                e = _sub(p2, p)
                w = _sub(q, p2)
            w = _sub(w, _mul(n, _dot(w, n)))
            ee = max(_dot(e, e), 1e-12)
            w = _sub(w, _mul(e, _dot(w, e) / ee))
            if self.MODE == "3corner":
                return [p, p2, _add(p2, w), _add(p, w)]
            far = _sub(_mul(p, 2.0), p2)
            return [_add(p2, w), _sub(p2, w), _sub(far, w), _add(far, w)]

        @staticmethod
        def _area(cs):
            a, b, d = cs[0], cs[1], cs[3]
            u, v = _sub(b, a), _sub(d, a)
            cr = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            return _len(cr)

        def draw(self, sn):
            if len(self.picks) < self.NEEDS:
                if not self.picks:
                    Tool.draw(self, sn)
                else:
                    self.s.tool_drawing(lines=[[self.picks[0].pos, sn.pos]], label=_fmt(_len(_sub(sn.pos,
                                        self.picks[0].pos))), label_at=sn.pos, points=[self.picks[0].pos])
                return
            cs = self.corners(sn.pos)
            lines = [cs + [cs[0]]]
            if self.lines:
                lines += self._guide_lines(cs)
            self.s.tool_drawing(lines=lines, label="%s x %s" % (_fmt(_len(_sub(cs[1], cs[0]))),
                                                                 _fmt(_len(_sub(cs[3], cs[0])))),
                                label_at=sn.pos, points=[p.pos for p in self.picks])

        def _guide_lines(self, cs):
            if self.lines_from == "From Midpoints":
                m = [_mul(_add(cs[k], cs[(k + 1) % 4]), 0.5) for k in range(4)]
                return [[m[0], m[2]], [m[1], m[3]]]
            return [[cs[0], cs[2]], [cs[1], cs[3]]]

        def click(self, sn):
            if len(self.picks) < self.NEEDS:
                if self.picks and _len(_sub(sn.pos, self.picks[-1].pos)) < 1e-9:
                    return
                self.picks.append(sn)
                return
            cs = self.corners(sn.pos)
            if self._area(cs) < 1e-9:
                return
            s = self.s
            n, (u, v) = s.axes()
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            idx = []
            for k, c in enumerate(cs):
                if k == 0 and self.MODE in ("corner", "3corner", "parallelogram"):
                    idx.append(self.place(self.picks[0], pts, rels))
                elif k == 1 and self.MODE in ("3corner", "parallelogram"):
                    idx.append(self.place(self.picks[1], pts, rels))
                elif k == 2 and self.MODE in ("corner", "center", "parallelogram") and \
                        (sn.point is not None or sn.relation is not None):
                    idx.append(self.place(sn, pts, rels))
                else:
                    idx.append(self.place(Snap(c, free=True), pts, rels))
            sides = [(idx[k], idx[(k + 1) % 4]) for k in range(4)]
            for a, b in sides:
                ents.append(S.Entity("L", [a, b], self.construction))
            axis_of = [AXIS_RELATION.get(tuple(int(round(c)) for c in w)) if all(abs(c - round(c)) < 1e-9 for c in w)
                       else None for w in (u, v)]
            (a, b), (c, d), (e, f), (g, h) = sides
            if self.MODE in ("corner", "center") and all(axis_of):
                for k, (p, q) in enumerate(sides):
                    rels.append(S.Relation(axis_of[k % 2], [p, q]))
            else:
                rels += [S.Relation("Parallel", [a, b, e, f]), S.Relation("Parallel", [c, d, g, h])]
                if self.MODE != "parallelogram":
                    rels.append(S.Relation("Perpendicular", [a, b, c, d]))
            centre = None
            if self.MODE in ("center", "3center"):
                centre = self.place(self.picks[0], pts, rels)
            if self.MODE == "3center":
                # the side's middle clicked second stays the middle of that side
                mi = self.place(self.picks[1], pts, rels)
                rels.append(S.Relation("Midpoint", [mi, idx[0], idx[1]]))
                ents.append(S.Entity("P", [mi], True))
            if self.lines or centre is not None:
                if self.lines_from == "From Midpoints" and self.lines:
                    mids = []
                    for p, q in sides:
                        pts.append(_mul(_add(pts[p], pts[q]), 0.5))
                        mids.append(len(pts) - 1)
                        rels.append(S.Relation("Midpoint", [mids[-1], p, q]))
                    ents.append(S.Entity("L", [mids[0], mids[2]], True))
                    ents.append(S.Entity("L", [mids[1], mids[3]], True))
                else:
                    ents.append(S.Entity("L", [idx[0], idx[2]], True))
                    ents.append(S.Entity("L", [idx[1], idx[3]], True))
                if centre is not None:
                    rels.append(S.Relation("Midpoint", [centre, idx[0], idx[2]]))
                    if not any(centre in x.points for x in ents):
                        ents.append(S.Entity("P", [centre], True))
            self.picks = []
            s.write("Rectangle", pts, ents, rels)

    class CenterRectangleTool(RectangleTool):
        TITLE = "Center Rectangle"
        CURSOR = "Sketcher_Pointer_Create_Box_Center"
        HINT = "3D Center Rectangle: click the center, then a corner, on the sketch plane (Tab changes it)."
        MODE = "center"

    class ThreePointCornerRectangleTool(RectangleTool):
        TITLE = "3 Point Corner Rectangle"
        HINT = "3D 3 Point Corner Rectangle: click two corners (one side), then the width, on the sketch plane."
        MODE = "3corner"
        NEEDS = 2

    class ThreePointCenterRectangleTool(RectangleTool):
        TITLE = "3 Point Center Rectangle"
        CURSOR = "Sketcher_Pointer_Create_Box_Center"
        HINT = "3D 3 Point Center Rectangle: click the center, the middle of one side, then the width."
        MODE = "3center"
        NEEDS = 2

    class ParallelogramTool(RectangleTool):
        TITLE = "Parallelogram"
        HINT = "3D Parallelogram: click two corners (one side), then the third corner."
        MODE = "parallelogram"
        NEEDS = 2

    class TrimTool(Tool):
        """Trim Entities in a 3D sketch: Power trim (drag across the entities, or click one) and Trim to
        closest (click the piece to remove, back to the closest crossings in space)."""
        TITLE = "Trim Entities"
        CURSOR = "Sketcher_Pointer_Trimming"
        HINT = "Trim: click the piece of a line, arc or circle to remove it back to the closest crossings, or " \
               "drag across several (Power trim). An entity with no crossing goes as a whole."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.mode = "Power trim"
            self.keep_construction = False
            self.ignore_construction = False
            self._crossed = None

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            hit = s.pick(x, y, points=False, dims=False)
            s.hover = hit
            held = bool(QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton)
            if held and self.mode == "Power trim" and hit is not None and hit != self._crossed:
                self._crossed = hit
                self.trim(hit[1], x, y)
                return
            if hit is None:
                self._crossed = None
            s.tool_drawing()

        def press(self, x, y):
            hit = self.s.pick(x, y, points=False, dims=False)
            if hit is not None:
                self._crossed = hit
                self.trim(hit[1], x, y)

        def release(self, x, y, dragged):
            self._crossed = None

        def double_click(self, x, y):
            pass

        def trim(self, k, x, y):
            s = self.s
            e = s.ents[k]
            if e.kind in ("P", "Q") or (e.construction and self.ignore_construction):
                return
            got = trim_entity(s, k, x, y, self.keep_construction)
            if got is None:
                return
            pts, ents, rels = got
            s.hover = None
            s.selection = []
            s.write("Trim", pts, ents, rels)

    class ConvertTool(Tool):
        """Convert Entities: the picked model edges (a face: its edges) become 3D sketch entities that stay
        on them (their ends Coincident with the corners, a circle's centre with the edge's centre)."""
        TITLE = "Convert Entities"
        CURSOR = "Sketcher_Pointer_External"
        HINT = "Convert Entities: click edges or faces of the model to convert, then OK (Enter)."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.picks = []           # (object name, element)

        def begin(self):
            for sel in Gui.Selection.getSelectionEx(self.s.doc.Name):
                if sel.Object is self.s.obj:
                    continue
                for n in sel.SubElementNames:
                    sub = n.rsplit(".", 1)[-1]
                    if sub.startswith(("Edge", "Face")) and (sel.Object.Name, sub) not in self.picks:
                        self.picks.append((sel.Object.Name, sub))
            super().begin()

        def move(self, x, y):
            self.s.cursor_pos = None
            self.s.tool_drawing()

        def press(self, x, y):
            try:
                info = self.s.view.getObjectInfo((int(x), int(y)))
            except Exception:
                info = None
            if not info or info.get("Object") in (None, self.s.obj.Name):
                return
            comp = info.get("Component", "") or ""
            if not comp.startswith(("Edge", "Face")):
                return
            key = (info["Object"], comp)
            if key in self.picks:
                self.picks.remove(key)
            else:
                self.picks.append(key)
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(self.s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:7243", _fw_err)

        def double_click(self, x, y):
            pass

        def apply(self):
            if not self.picks:
                return None
            got = convert_edges(self.s, self.picks, self.construction)
            self.picks = []
            if got:
                self.s.write("Convert Entities", *got)
            Gui.Selection.clearSelection()
            return got

    class IntersectionTool(Tool):
        ""

        TITLE = "Intersection Curve"
        CURSOR = "Sketcher_Pointer_External"
        HINT = "Intersection Curve: click two or more faces or planes of the model (a plane and a body, two faces...), " \
               "then OK (Enter)."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.picks = []           # (object name, element)

        def begin(self):
            for sel in Gui.Selection.getSelectionEx(self.s.doc.Name):
                if sel.Object is self.s.obj:
                    continue
                subs = [n.rsplit(".", 1)[-1] for n in sel.SubElementNames] or [""]
                for sub in subs:
                    if (not sub or sub.startswith("Face")) and (sel.Object.Name, sub or "-") not in self.picks:
                        self.picks.append((sel.Object.Name, sub or "-"))
            super().begin()

        def move(self, x, y):
            self.s.cursor_pos = None
            self.s.tool_drawing(lines=self._preview())

        def _preview(self):
            out = []
            for e in intersection_edges(self.s.doc, self.picks) if len(self.picks) > 1 else []:
                try:
                    out.append([(p.x, p.y, p.z) for p in e.discretize(Number=24)])
                except Exception as _fw_err:
                    _fw_log("sketch3d.py:7291", _fw_err)
            return out

        def take(self, key):
            if key in self.picks:
                self.picks.remove(key)
            else:
                self.picks.append(key)
            self.move(*self.s.cursor())
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(self.s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:7304", _fw_err)

        def press(self, x, y):
            try:
                info = self.s.view.getObjectInfo((int(x), int(y)))
            except Exception:
                info = None
            if info and info.get("Object") not in (None, self.s.obj.Name) and \
                    str(info.get("Component", "") or "").startswith("Face"):
                self.take((info["Object"], info["Component"]))
                return
            plane = DimensionTool._model_plane(self, x, y)
            if plane is not None:
                self.take((plane[0], plane[1] or "-"))

        def double_click(self, x, y):
            pass

        def apply(self):
            if len(self.picks) < 2:
                return "Pick at least two faces, planes or bodies that meet."
            edges = intersection_edges(self.s.doc, self.picks)
            got = free_edges(self.s, edges, self.construction)
            if got is None:
                return "The picked faces and planes do not meet."
            self.picks = []
            self.s.write("Intersection Curve", *got)
            Gui.Selection.clearSelection()
            return None

    class FaceCurvesTool(IntersectionTool):
        ""

        TITLE = "Face Curves"
        HINT = "Face Curves: click a face of the model; Mesh (how many each way) or Position, then OK (Enter)."

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.mode = "Mesh"
            self.counts = [5, 5]
            self.dirs = [True, True]
            self.pos = [50.0, 50.0]
            self.constrain = True
            self.ignore_holes = False

        def begin(self):
            super().begin()
            self.picks = [p for p in self.picks if p[1].startswith("Face")][-1:]

        def _edges(self):
            if not self.picks:
                return []
            o = self.s.doc.getObject(self.picks[0][0])
            try:
                face = o.Shape.getElement(self.picks[0][1])
            except Exception:
                return []
            return face_curve_edges(face, self.mode, self.counts[0], self.counts[1], self.pos, self.dirs[0],
                                    self.dirs[1], self.ignore_holes)

        def _preview(self):
            out = []
            for e in self._edges():
                try:
                    out.append([(p.x, p.y, p.z) for p in e.discretize(Number=24)])
                except Exception as _fw_err:
                    _fw_log("sketch3d.py:7370", _fw_err)
            return out

        def take(self, key):
            if not key[1].startswith("Face"):
                return
            self.picks = [] if key in self.picks else [key]
            self.move(*self.s.cursor())
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(self.s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:7382", _fw_err)

        def apply(self):
            if not self.picks:
                return "Pick a face of the model."
            got = free_edges(self.s, self._edges(), self.construction, on=self.picks[0] if self.constrain else None)
            if got is None:
                return "No curves on that face with these settings."
            self.picks = []
            self.s.write("Face Curves", *got)
            Gui.Selection.clearSelection()
            return None

    class SplineOnSurfaceTool(SplineTool):
        ""

        TITLE = "Spline on Surface"
        HINT = "Spline on Surface: click points on a face of the model; double-click or Esc ends it (right-click: " \
               "the menu)."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.face = None          # (object name, FaceN) of the first click

        def _face_of(self, sn):
            r = sn.relation if sn is not None else None
            if r is not None and r[0] in ("OnSurface", "OnPlane") and str(r[2]).startswith("Face"):
                return (r[1], r[2])
            # fwsketch fix65: a click that snaps to an edge or vertex of the face (a cylinder's seam, the

            if r is not None and r[0] in ("OnEdge", "AtRef") and (str(r[2]).startswith("Edge") or str(r[2]).startswith("Vertex")):
                return self._face_with(r[1], str(r[2]))
            return None

        def move(self, x, y):

            super().move(x, y)
            if self._face_of(self.last) is None:
                m = self._face_under(x, y)
                if m is not None:
                    self.last = m
                    self.s.cursor_pos = m.pos
                    self.draw(m)

        def _face_under(self, x, y):
            """The model face under the pointer, behind whatever sketch is drawn in front of it."""
            try:
                infos = self.s.view.getObjectsInfo((int(x), int(y))) or []
            except Exception:
                infos = []
            for info in infos:
                name, comp = info.get("Object"), str(info.get("Component", "") or "")
                if name in (None, self.s.obj.Name) or not comp.startswith("Face"):
                    continue
                o = self.s.doc.getObject(name)
                if o is None or not hasattr(o, "Shape") or is_sketch3d(o):
                    continue
                flat = plane_of(self.s.doc, name, comp) is not None
                sn = Snap((info["x"], info["y"], info["z"]), relation=("OnPlane" if flat else "OnSurface", name, comp),
                          label="On Plane" if flat else "On Surface")
                if self._face_of(sn) is not None and (self.face is None or self._face_of(sn) == self.face):
                    return sn
            return None

        def _face_with(self, name, sub):
            try:
                obj = App.ActiveDocument.getObject(name)
                el = obj.Shape.getElement(sub)
            except Exception:
                return None
            faces = [(i, f) for i, f in enumerate(obj.Shape.Faces)
                     if any(el.isSame(x) for x in (f.Edges if sub.startswith("Edge") else f.Vertexes))]
            if self.face is not None and self.face[0] == name:
                if any("Face%d" % (i + 1) == self.face[1] for i, _f in faces):
                    return self.face
                return None
            # the first click: a curved face before a flat one (the seam of a cylinder is on it only)
            faces.sort(key=lambda t: type(t[1].Surface).__name__ == "Plane")
            return (name, "Face%d" % (faces[0][0] + 1)) if faces else None

        def draw(self, sn):
            pos = [t.pos for t in self.through] + ([sn.pos] if self._face_of(sn) == (self.face or self._face_of(sn))
                                                    and self._face_of(sn) else [])
            lines = []
            if len(pos) >= 2 and (self.face or self._face_of(sn)):
                try:
                    e = surface_spline_edge(pos, self.face or self._face_of(sn))
                    lines = [[(v.x, v.y, v.z) for v in e.discretize(Number=60)]]
                except Exception:
                    lines = [pos]
            self.s.tool_drawing(lines=lines, label=sn.label if sn is not None else None,
                                label_at=sn.pos if sn is not None else None, points=[t.pos for t in self.through])

        def click(self, sn):
            face = self._face_of(sn)
            if face is None or (self.face is not None and face != self.face):
                self.s.status("Spline on Surface: click on the face%s." % (
                    "" if self.face is None else " (%s)" % self.face[1]))
                return
            self.face = face
            self.through.append(sn)
            self.draw(sn)

        def finish(self, closed=False):
            through, face = self.through, self.face
            self.through, self.face = [], None
            if len(through) < 2:
                return
            s = self.s
            pts, ents, rels = list(s.pts), list(s.ents), list(s.rels)
            idx = [self.place(sn, pts, rels) for sn in through]
            ents.append(S.Entity("S", idx, self.construction))
            rels.append(S.Relation("SplineOnSurface", idx[:2], [], face))
            s.write("Spline on Surface", pts, ents, rels)

    class EquationCurveTool(IntersectionTool):
        ""
        TITLE = "Equation Driven Curve"
        CURSOR = "Sketcher_Pointer_Create_BSpline"
        HINT = "Equation Driven Curve: type x(t), y(t), z(t) and t1, t2, then OK (Enter)."

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.exprs = ["10*cos(t)", "10*sin(t)", "t"]
            self.t1, self.t2 = 0.0, 4 * math.pi
            self.locks = [True, True]
            self.error = None

        def begin(self):
            Tool.begin(self)

        def _preview(self):
            try:
                got = equation_points_3d(self.exprs, self.t1, self.t2)
                self.error = None
                return [got]
            except Exception as e:
                self.error = str(e)
                return []

        def take(self, key):
            pass

        def press(self, x, y):
            pass

        def apply(self):
            try:
                got = equation_curve(self.s, self.exprs, self.t1, self.t2, self.construction, self.locks)
            except Exception as e:
                return "Equation Driven Curve: %s." % e
            self.s.write("Equation Driven Curve", *got)
            return None

    class OffsetOnSurfaceTool(IntersectionTool):
        ""

        TITLE = "Offset on Surface"
        HINT = "Offset on Surface: click edges of a face (or the face), set the distance, then OK (Enter)."

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.distance = 10.0
            self.geodesic = True
            self.reverse = False
            self.make_construction = False

        def begin(self):
            super().begin()
            self.picks = [p for p in self.picks if p[1].startswith(("Edge", "Face"))]
            for sel in Gui.Selection.getSelectionEx(self.s.doc.Name):
                for n in sel.SubElementNames:
                    sub = n.rsplit(".", 1)[-1]
                    if sub.startswith("Edge") and (sel.Object.Name, sub) not in self.picks:
                        self.picks.append((sel.Object.Name, sub))

        def press(self, x, y):
            try:
                info = self.s.view.getObjectInfo((int(x), int(y)))
            except Exception:
                info = None
            if info and info.get("Object") not in (None, self.s.obj.Name) and \
                    str(info.get("Component", "") or "").startswith(("Edge", "Face")):
                self.take((info["Object"], info["Component"]))

        def _pairs(self):
            """(face, edge, side) for each edge to offset. A face picked with some of its edges: those edges
            across it; a face alone: all its edges, inward; an edge alone: across its first face."""
            out = []
            got = []
            for name, sub in self.picks:
                o = self.s.doc.getObject(name)
                try:
                    got.append((sub, o.Shape.getElement(sub), o))
                except Exception:
                    continue
            faces = [(el, o) for sub, el, o in got if sub.startswith("Face")]
            edges = [(el, o) for sub, el, o in got if sub.startswith("Edge")]
            for face, o in faces:
                own = [e for e, eo in edges if eo is o and any(x.isSame(e) for x in face.Edges)]
                for e in own or face.Edges:
                    out.append((face, e, None))
            for e, o in edges:
                if any(f is not None and any(x.isSame(e) for x in f.Edges) for f, fo in faces if fo is o):
                    continue
                around = [f for f in o.Shape.Faces if any(x.isSame(e) for x in f.Edges)]
                if around:
                    out.append((around[0], e, None))
            return out

        def _offsets(self):
            got = []
            for face, edge, _ in self._pairs():
                mid = 0.5 * (edge.FirstParameter + edge.LastParameter)
                p, tan = edge.valueAt(mid), edge.tangentAt(mid)
                u, v = face.Surface.parameter(p)
                d = face.normalAt(u, v).cross(tan)
                side = 1.0
                if d.Length > 1e-12:
                    d.normalize()
                    probe = p + d * min(self.distance, 0.5) * 0.1
                    try:
                        inside = face.isInside(probe, 1e-6, True)
                    except Exception:
                        inside = True
                    side = 1.0 if inside else -1.0
                if self.reverse:
                    side = -side
                got.append(offset_on_surface(face, edge, self.distance, self.geodesic, side))
            return got

        def _edges(self):
            import Part
            out = []
            lines = []
            for (face, edge, _), q in zip(self._pairs(), self._offsets()):
                vs = [App.Vector(*p) for p in q]
                if len(vs) < 2:
                    continue
                d = vs[-1] - vs[0]
                straight = d.Length > 1e-9 and all(((v - vs[0]).cross(d)).Length / d.Length < 1e-7 for v in vs)
                if straight:
                    lines.append([face, edge, vs[0], vs[-1]])
                    continue
                c = Part.BSplineCurve()
                closed = (vs[0] - vs[-1]).Length < 1e-7
                c.interpolate(vs[:-1] if closed else vs, PeriodicFlag=closed)
                out.append(c.toShape())
            _join_corners(lines)
            return [Part.LineSegment(a, b).toShape() for _f, _e, a, b in lines if (b - a).Length > 1e-9] + out

        def _preview(self):
            lines = []
            other = []
            for (face, edge, _), q in zip(self._pairs(), self._offsets()):
                vs = [App.Vector(*p) for p in q]
                d = vs[-1] - vs[0] if len(vs) > 1 else App.Vector()
                if d.Length > 1e-9 and all(((v - vs[0]).cross(d)).Length / d.Length < 1e-7 for v in vs):
                    lines.append([face, edge, vs[0], vs[-1]])
                else:
                    other.append(list(q))
            _join_corners(lines)
            return [[tuple(a), tuple(b)] for _f, _e, a, b in lines] + other

        def apply(self):
            if not self.picks:
                return "Pick edges of a face of the model (or the face)."
            got = free_edges(self.s, self._edges(), self.make_construction)
            if got is None:
                return "Nothing to offset."
            self.picks = []
            self.s.write("Offset on Surface", *got)
            Gui.Selection.clearSelection()
            return None

    class InsertSplinePointTool(Tool):
        """Insert Spline Point: click on a spline where a new through point goes."""
        TITLE = "Insert Spline Point"
        CURSOR = "Sketcher_Pointer_Create_Point"
        HINT = "Insert Spline Point: click on a spline where the new point goes; Esc ends."
        PLANE_TAG = False

        def move(self, x, y):
            self.s.cursor_pos = None
            hit = self.s.pick(x, y, points=False, dims=False)
            self.s.hover = hit if hit is not None and self.s.ents[hit[1]].kind == "S" else None
            self.s.tool_drawing()

        def press(self, x, y):
            s = self.s
            hit = s.pick(x, y, points=False, dims=False)
            if hit is None or s.ents[hit[1]].kind != "S":
                return
            line = s.polyline(s.ents[hit[1]])
            best = min(((s._seg_dist(a, b, x, y), a, b) for a, b in zip(line[:-1], line[1:])), key=lambda t: t[0][0])
            (_, f), a, b = best
            why = s.insert_spline_point(hit[1], _add(a, _mul(_sub(b, a), f)))
            if why:
                s.status(why)

        def double_click(self, x, y):
            pass

    class MirrorTool(Tool):
        """Mirror Entities in a 3D sketch: the picked sketch entities mirrored about a plane or flat face of
        the model, each copy Symmetric to its original about it (Copy off: the originals go)."""
        TITLE = "Mirror"
        CURSOR = "Sketcher_Pointer_Create_Lineset"
        HINT = "Mirror: click the sketch entities to mirror, then a plane or flat face of the model to mirror " \
               "about (Mirror about), then OK (Enter)."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.items = [i for k, i in session.selection if k == "E"]
            self.about = None
            self.copy = True

        def move(self, x, y):
            self.s.cursor_pos = None
            self.s.hover = self.s.pick(x, y, points=False, dims=False)
            self.s.tool_drawing()

        def press(self, x, y):
            s = self.s
            hit = s.pick(x, y, points=False, dims=False)
            if hit is not None and hit[0] == "E":
                if hit[1] in self.items:
                    self.items.remove(hit[1])
                else:
                    self.items.append(hit[1])
                s.selection = [("E", i) for i in self.items]
                s.redraw()
            else:
                plane = DimensionTool._model_plane(self, x, y)
                if plane is not None:
                    self.about = plane
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:7724", _fw_err)

        def double_click(self, x, y):
            pass

        def apply(self):
            if not self.items or self.about is None:
                return "Pick the entities to mirror and a plane or flat face to mirror about."
            got = mirror_entities(self.s, self.items, self.about, self.copy)
            if got is None:
                return "The plane is gone."
            self.items = []
            self.s.selection = []
            self.s.write("Mirror", *got)
            return None

    class FilletTool(Tool):
        """Sketch Fillet in a 3D sketch: click corners (a point where two lines meet) or two lines, then
        OK (Enter): each corner gets a tangent arc of the radius."""
        TITLE = "Sketch Fillet"
        CURSOR = "Sketcher_Pointer_Create_Fillet"
        HINT = "Sketch Fillet: click the corners to round (or two lines that meet), set the radius, then OK."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.radius = 10.0
            self.keep = True          # Keep constrained corners
            self.each = False         # Dimension each fillet
            self.corners = []
            self._line = None         # the first of two lines picked
            for k, i in session.selection:
                self._take((k, i))
            self._line = None

        def _take(self, hit):
            s = self.s
            if hit[0] == "P":
                p = hit[1]
            elif hit[0] == "E" and s.ents[hit[1]].kind == "L":
                if self._line is None or self._line == hit[1]:
                    self._line = hit[1]
                    return
                p = corner_of(s.ents, self._line, hit[1])
                self._line = None
            else:
                return
            if p is None or corner_lines(s.ents, p) is None:
                return
            if p in self.corners:
                self.corners.remove(p)
            else:
                self.corners.append(p)

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            s.hover = s.pick(x, y, dims=False)
            self.draw(None)

        def draw(self, sn):
            arcs = []
            for p in self.corners:
                got = fillet_geometry(self.s.pts, self.s.ents, p, self.radius)
                if got is not None:
                    c, t1, t2, n = got[:4]
                    arcs.append(arc_points(c, t1, t2, n))
            self.s.tool_drawing(lines=arcs, points=[self.s.pts[p] for p in self.corners])

        def press(self, x, y):
            hit = self.s.pick(x, y, dims=False)
            if hit is None:
                return
            self._take(hit)
            self.s.selection = [("P", p) for p in self.corners]
            self.draw(None)
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(self.s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:7804", _fw_err)

        def double_click(self, x, y):
            pass

        def set_radius(self, value):
            self.radius = float(value)
            self.draw(None)

        def apply(self):
            if not self.corners:
                return "Pick the corners to fillet: a point where two lines meet, or two lines."
            (pts, ents, rels), failed = fillet_corners(self.s, self.corners, self.radius, self.keep, self.each)
            if len(failed) == len(self.corners):
                return "The radius does not fit these corners."
            self.corners = []
            self.s.selection = []
            self.s.write("Sketch Fillet", pts, ents, rels)
            if failed:
                self.s.status("Sketch Fillet: %d corner%s could not take that radius."
                              % (len(failed), "" if len(failed) == 1 else "s"))
            return None

    class ChamferTool(FilletTool):
        """Sketch Chamfer in a 3D sketch: click corners (a point where two lines meet) or two lines, then
        OK (Enter): each corner is cut back and closed by a line. Distance-distance (Equal distance) or
        Angle-distance."""
        TITLE = "Sketch Chamfer"
        CURSOR = "Sketcher_Pointer_Create_Chamfer"
        HINT = "Sketch Chamfer: click the corners to chamfer (or two lines that meet), set the distances, then OK."

        def __init__(self, session, construction=False):
            self.mode = "Distance-distance"
            self.equal = True
            self.d1, self.d2, self.angle = 10.0, 10.0, 45.0
            super().__init__(session, construction)

        def _args(self):
            if self.mode == "Angle-distance":
                return self.d1, None, self.angle
            return self.d1, (self.d1 if self.equal else self.d2), None

        def set_value(self, name, value):
            setattr(self, name, value)
            self.draw(None)

        def draw(self, sn):
            lines = []
            for p in self.corners:
                got = chamfer_geometry(self.s.pts, self.s.ents, p, *self._args())
                if got is not None:
                    lines.append([got[0], got[1]])
            self.s.tool_drawing(lines=lines, points=[self.s.pts[p] for p in self.corners])

        def apply(self):
            if not self.corners:
                return "Pick the corners to chamfer: a point where two lines meet, or two lines."
            (pts, ents, rels), failed = chamfer_corners(self.s, self.corners, *self._args())
            if len(failed) == len(self.corners):
                return "The distances do not fit these corners."
            self.corners = []
            self.s.selection = []
            self.s.write("Sketch Chamfer", pts, ents, rels)
            if failed:
                self.s.status("Sketch Chamfer: %d corner%s could not take those distances."
                              % (len(failed), "" if len(failed) == 1 else "s"))
            return None

    class ExtendTool(Tool):
        """Extend Entities in a 3D sketch: click a line or arc near the end to extend; it goes on to the next
        entity it meets in space. The preview shows where it goes."""
        TITLE = "Extend Entities"
        CURSOR = "Sketcher_Pointer_Extension"
        HINT = "Extend Entities: click a line or arc near the end to extend it to the next entity it meets."
        PLANE_TAG = False

        def _target(self, x, y):
            s = self.s
            hit = s.pick(x, y, points=False, dims=False)
            if hit is None or hit[0] != "E" or s.ents[hit[1]].kind not in ("L", "A"):
                return None
            k = hit[1]
            e = s.ents[k]
            if e.kind == "L":
                _, f = s._seg_dist(s.pts[e.points[0]], s.pts[e.points[1]], x, y)
                end = 0 if f < 0.5 else 1
            else:
                line = s.polyline(e)
                best = min(range(len(line)), key=lambda i: s._screen_dist(line[i], x, y))
                end = 0 if best < len(line) / 2.0 else 1
            got = extend_target(s, k, end)
            return (k, end, got) if got is not None else None

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            s.hover = s.pick(x, y, points=False, dims=False)
            got = self._target(x, y)
            lines = []
            if got is not None:
                k, end, (p, q, make) = got
                e = s.ents[k]
                if e.kind == "L":
                    lines.append([s.pts[p], q])
                else:
                    rd = _round_of(e, s.pts, s.rels)
                    a, b = (s.pts[e.points[2]], q) if end == 1 else (q, s.pts[e.points[1]])
                    lines.append(arc_points(rd[0], a, b, rd[4]))
            s.tool_drawing(lines=lines)

        def press(self, x, y):
            got = self._target(x, y)
            if got is None:
                if self.s.pick(x, y, points=False, dims=False) is not None:
                    self.s.status("Extend Entities: nothing to extend to that way.")
                return
            k, end, _ = got
            out = extend_entity(self.s, k, end)
            if out is None:
                return
            self.s.hover = None
            self.s.selection = []
            self.s.write("Extend Entities", *out)

        def double_click(self, x, y):
            pass

    class SplitTool(Tool):
        """Split Entities in a 3D sketch: click a line, arc or open spline where it splits in two; a circle
        takes two clicks (two split points) and becomes two arcs."""
        TITLE = "Split Entities"
        CURSOR = "Sketcher_Pointer_Splitting"
        HINT = "Split Entities: click where a line, arc or spline splits; a circle takes two split points."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.first = None     # (circle, point) waiting for the second split point

        def _on(self, x, y):
            s = self.s
            hit = s.pick(x, y, points=False, dims=False)
            if hit is None or hit[0] != "E" or s.ents[hit[1]].kind not in ("L", "A", "C", "S"):
                return None
            e = s.ents[hit[1]]
            if e.kind == "S":
                # on a through point: split there (no new point)
                near = [i for i in e.points[1:-1] if s._screen_dist(s.pts[i], x, y) < s.px()]
                if near:
                    return hit[1], s.pts[min(near, key=lambda i: s._screen_dist(s.pts[i], x, y))]
            line = s.polyline(e)
            (_, f), a, b = min(((s._seg_dist(a, b, x, y), a, b) for a, b in zip(line[:-1], line[1:])),
                               key=lambda t: t[0][0])
            return hit[1], _add(a, _mul(_sub(b, a), f))

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            on = self._on(x, y)
            s.hover = ("E", on[0]) if on else None
            marks = [on[1]] if on else []
            if self.first is not None:
                marks.append(self.first[1])
            s.tool_drawing(points=marks)

        def press(self, x, y):
            s = self.s
            on = self._on(x, y)
            if on is None:
                return
            k, q = on
            e = s.ents[k]
            if e.kind == "S":
                why = s.split_spline(k, q)
            elif e.kind == "C":
                if self.first is None or self.first[0] != k:
                    self.first = (k, q)
                    s.status("Split Entities: click a second point on the circle.")
                    self.move(x, y)
                    return
                why = split_entity(s, k, self.first[1], q)
                self.first = None
            else:
                why = split_entity(s, k, q)
            if isinstance(why, tuple):
                s.hover = None
                s.selection = []
                s.write("Split Entities", *why)
                why = None
            if why:
                s.status(why)

        def double_click(self, x, y):
            pass

    class SegmentTool(Tool):
        ""

        TITLE = "Segment"
        CURSOR = "Sketcher_Pointer_Create_Point"
        HINT = "Segment: pick a line, arc, circle or spline, set the number of instances, then OK."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.mode = "points"
            self.count = 2
            self.target = None
            for kind, i in session.selection:
                if kind == "E" and session.ents[i].kind in ("L", "A", "C", "S"):
                    self.target = i
                    break

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            s.hover = s.pick(x, y, points=False, dims=False)
            self.draw(None)

        def preview(self):
            s = self.s
            if self.target is None or self.target >= len(s.ents):
                return []
            e = s.ents[self.target]
            n = int(self.count)
            if e.kind == "L":
                A, B = (s.pts[i] for i in e.points)
                return [_add(A, _mul(_sub(B, A), i / float(n))) for i in range(1, n)]
            if e.kind in ("A", "C"):
                rd = _round_of(e, s.pts, s.rels)
                return [_at_angle(rd, rd[5] * i / float(n)) for i in range(0 if e.kind == "C" else 1, n)]
            try:
                edge = entity_edges(e, s.pts, s.rels)[0]
                return [tuple(edge.valueAt(edge.getParameterByLength(edge.Length * i / float(n))))
                        for i in range(1, n)]
            except Exception:
                return []

        def draw(self, sn):
            self.s.tool_drawing(points=self.preview())

        def press(self, x, y):
            hit = self.s.pick(x, y, points=False, dims=False)
            if hit is None or hit[0] != "E" or self.s.ents[hit[1]].kind not in ("L", "A", "C", "S"):
                return
            self.target = hit[1]
            self.s.selection = [hit]
            self.draw(None)
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(self.s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:8056", _fw_err)

        def double_click(self, x, y):
            pass

        def set_value(self, name, value):
            setattr(self, name, value)
            self.draw(None)

        def apply(self):
            s = self.s
            if self.target is None or self.target >= len(s.ents):
                return "Pick a line, arc, circle or spline to segment."
            if s.ents[self.target].kind == "S":
                why = s.segment_spline(self.target, self.count, self.mode)
                if why:
                    return why
            else:
                got = segment_entity(s, self.target, self.count, self.mode)
                if isinstance(got, str):
                    return got
                s.write("Segment", *got)
            self.target = None
            s.selection = []
            return None

    class FitSplineTool(Tool):
        ""

        TITLE = "Fit Spline"
        CURSOR = "Sketcher_Pointer_Create_BSpline"
        HINT = "Fit Spline: pick lines, arcs or splines that join end to end, then OK."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.items = [i for kind, i in session.selection if kind == "E" and session.ents[i].kind in ("L", "A", "S")]
            self.delete, self.closed, self.how, self.tolerance = True, False, "Constrained", 0.01

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            s.hover = s.pick(x, y, points=False, dims=False)
            self.draw(None)

        def draw(self, sn):
            lines = []
            got = fit_points(self.s, self.items, self.tolerance, self.closed) if self.items else None
            if got and len(got) >= 2:
                try:
                    edge = spline_edge(got + ([got[0]] if self.closed else []), self.closed)
                    lines.append([(v.x, v.y, v.z) for v in edge.discretize(Number=64)])
                except Exception as _fw_err:
                    _fw_log("sketch3d.py:8109", _fw_err)
            self.s.tool_drawing(lines=lines)

        def press(self, x, y):
            hit = self.s.pick(x, y, points=False, dims=False)
            if hit is None or hit[0] != "E" or self.s.ents[hit[1]].kind not in ("L", "A", "S"):
                return
            k = hit[1]
            if k in self.items:
                self.items.remove(k)
            else:
                self.items.append(k)
            self.s.selection = [("E", i) for i in self.items]
            self.draw(None)
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(self.s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:8127", _fw_err)

        def double_click(self, x, y):
            pass

        def set_value(self, name, value):
            setattr(self, name, value)
            self.draw(None)

        def apply(self):
            if not self.items:
                return "Pick the lines, arcs or splines to fit a spline over."
            got = fit_spline(self.s, self.items, self.tolerance, self.closed, self.delete, False, self.how)
            if isinstance(got, str):
                return got
            self.items = []
            self.s.selection = []
            self.s.write("Fit Spline", *got)
            return None

    class JogLineTool(Tool):
        ""

        TITLE = "Jog Line"
        CURSOR = "Sketcher_Pointer_Create_Lineset"
        HINT = "Jog Line: click the line where the jog goes, set the width and depth, then OK."
        PLANE_TAG = True

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.width, self.depth, self.flip = 10.0, 5.0, False
            self.line, self.at = None, None

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            s.hover = s.pick(x, y, points=False, dims=False)
            self.draw(None)

        def result(self):
            if self.line is None or self.line >= len(self.s.ents):
                return None
            return jog_line(self.s, self.line, self.at, self.width, self.depth, self.flip, self.s.axes()[0])

        def draw(self, sn):
            got = self.result()
            lines = []
            if got is not None and not isinstance(got, str):
                pts, ents, _ = got
                lines = [[pts[i] for i in e.points] for e in ents[-5:]]
            self.s.tool_drawing(lines=lines)

        def press(self, x, y):
            s = self.s
            hit = s.pick(x, y, points=False, dims=False)
            if hit is None or hit[0] != "E" or s.ents[hit[1]].kind != "L":
                return
            e = s.ents[hit[1]]
            A, B = (s.pts[i] for i in e.points)
            _, f = s._seg_dist(A, B, x, y)
            self.line, self.at = hit[1], _add(A, _mul(_sub(B, A), f))
            self.draw(None)
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:8193", _fw_err)

        def double_click(self, x, y):
            pass

        def set_value(self, name, value):
            setattr(self, name, value)
            self.draw(None)

        def apply(self):
            got = self.result()
            if got is None:
                return "Click the line where the jog goes."
            if isinstance(got, str):
                return got
            self.line = None
            self.s.selection = []
            self.s.write("Jog Line", *got)
            return None

    class ReplaceTool(Tool):
        ""

        TITLE = "Replace Entity"
        CURSOR = "Sketcher_Pointer_Create_Lineset"
        HINT = "Replace Entity: pick the entity to replace, then the entity that replaces it, then OK."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            picked = [i for kind, i in session.selection if kind == "E"]
            self.old = picked[0] if picked else None
            self.new = picked[1] if len(picked) > 1 else None
            self.active = "new" if self.old is not None else "old"
            self.make_construction = False

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            s.hover = s.pick(x, y, points=False, dims=False)
            self.draw(None)

        def draw(self, sn):
            s = self.s
            lines = [s.polyline(s.ents[k]) for k in (self.old, self.new) if k is not None and k < len(s.ents)]
            s.tool_drawing(lines=lines)

        def press(self, x, y):
            hit = self.s.pick(x, y, points=False, dims=False)
            if hit is None or hit[0] != "E" or self.s.ents[hit[1]].kind == "Q":
                return
            if self.active == "old":
                self.old, self.active = hit[1], "new"
            else:
                self.new = hit[1]
            self.s.selection = [("E", k) for k in (self.old, self.new) if k is not None]
            self.draw(None)
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(self.s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:8254", _fw_err)

        def double_click(self, x, y):
            pass

        def apply(self):
            if self.old is None or self.new is None:
                return "Pick the entity to replace, then the entity that replaces it."
            got = replace_entity(self.s, self.old, self.new, self.make_construction)
            if isinstance(got, str):
                return got
            self.old = self.new = None
            self.active = "old"
            self.s.selection = []
            self.s.write("Replace Entity", *got)
            return None

    class ContourSelectTool(Tool):
        """Contour Select Tool: each click picks the whole chain (contour) the entity is in; Esc ends."""
        TITLE = "Contour Select Tool"
        CURSOR = "Sketcher_Pointer_Create_Lineset"
        HINT = "Contour Select Tool: click an entity to pick its whole contour; Ctrl adds to the selection; Esc ends."
        PLANE_TAG = False

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            hit = s.pick(x, y, points=False, dims=False)
            s.hover = hit
            lines = [s.polyline(s.ents[j]) for j in s.chain_of(hit[1])] if hit is not None and hit[0] == "E" else []
            s.tool_drawing(lines=lines)

        def press(self, x, y):
            s = self.s
            hit = s.pick(x, y, points=False, dims=False)
            if hit is None or hit[0] != "E":
                if not self.plain():
                    s.selection = []
                    s.redraw()
                return
            chain = [("E", j) for j in s.chain_of(hit[1])]
            s.selection = (list(s.selection) + [c for c in chain if c not in s.selection]) if self.plain() else chain
            s.redraw()

        def double_click(self, x, y):
            pass

    class SimplifySplineTool(Tool):
        ""

        TITLE = "Simplify Spline"
        CURSOR = "Sketcher_Pointer_Create_BSpline"
        HINT = "Simplify Spline: pick a spline, set the tolerance, then OK."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.tolerance = 0.1
            self.target = next((i for kind, i in session.selection if kind == "E" and session.ents[i].kind == "S"
                                and not spline_style(session.ents[i], session.rels)), None)

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            s.hover = s.pick(x, y, points=False, dims=False)
            self.draw(None)

        def preview(self):
            if self.target is None or self.target >= len(self.s.ents):
                return []
            try:
                return simplify_points(self.s, self.target, self.tolerance)
            except Exception:
                return []

        def draw(self, sn):
            got = self.preview()
            lines = []
            if len(got) >= 2:
                try:
                    lines = [[tuple(v) for v in spline_edge(got).discretize(Number=80)]]
                except Exception as _fw_err:
                    _fw_log("sketch3d.py:8336", _fw_err)
            self.s.tool_drawing(lines=lines, points=got)

        def press(self, x, y):
            hit = self.s.pick(x, y, points=False, dims=False)
            if hit is None or hit[0] != "E" or self.s.ents[hit[1]].kind != "S":
                return
            self.target = hit[1]
            self.s.selection = [hit]
            self.draw(None)
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(self.s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:8350", _fw_err)

        def double_click(self, x, y):
            pass

        def set_value(self, name, value):
            setattr(self, name, value)
            self.draw(None)

        def points_now(self):
            return len(self.s.ents[self.target].points) if self.target is not None else 0

        def apply(self):
            if self.target is None:
                return "Pick a spline to simplify."
            why = self.s.simplify_spline(self.target, self.tolerance)
            if why:
                return why
            self.target = None
            self.s.selection = []
            return None

    class AddTangencyControlTool(Tool):
        """Add Tangency Control: click on a spline where a new tangent handle goes; Esc ends."""
        TITLE = "Add Tangency Control"
        CURVATURE = False
        CURSOR = "Sketcher_Pointer_Create_Point"
        HINT = "Add Tangency Control: click on a spline where the new handle goes, then drag the handle; Esc ends."
        PLANE_TAG = False

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            hit = s.pick(x, y, points=False, dims=False)
            s.hover = hit if hit is not None and hit[0] == "E" and s.ents[hit[1]].kind == "S" and \
                not spline_style(s.ents[hit[1]], s.rels) else None
            s.tool_drawing()

        def press(self, x, y):
            s = self.s
            hit = s.pick(x, y, points=False, dims=False)
            if hit is None or hit[0] != "E" or s.ents[hit[1]].kind != "S":
                return
            line = s.polyline(s.ents[hit[1]])
            (_, f), a, b = min(((s._seg_dist(a, b, x, y), a, b) for a, b in zip(line[:-1], line[1:])),
                               key=lambda t: t[0][0])
            why = s.add_spline_control(hit[1], _add(a, _mul(_sub(b, a), f)), self.CURVATURE)
            if why:
                s.status(why)

        def double_click(self, x, y):
            pass

    class AddCurvatureControlTool(AddTangencyControlTool):
        """Add Curvature Control: click on a spline where a new curvature handle goes; Esc ends."""
        TITLE = "Add Curvature Control"
        CURVATURE = True
        HINT = "Add Curvature Control: click on a spline where the new handle goes, then drag it (its length " \
               "sets the curvature there); Esc ends."

    class InsertControlVertexTool(Tool):
        """Insert Control Vertex: click on a Style Spline's control polygon (or the curve) where the new
        vertex goes; Esc ends."""
        TITLE = "Insert Control Vertex"
        CURSOR = "Sketcher_Pointer_Create_Point"
        HINT = "Insert Control Vertex: click on a Style Spline where the new control vertex goes; Esc ends."
        PLANE_TAG = False

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            hit = s.pick(x, y, points=False, dims=False)
            s.hover = hit if hit is not None and hit[0] == "E" and spline_style(s.ents[hit[1]], s.rels) else None
            s.tool_drawing()

        def press(self, x, y):
            s = self.s
            hit = s.pick(x, y, points=False, dims=False)
            if hit is None or hit[0] != "E" or not spline_style(s.ents[hit[1]], s.rels):
                return
            line = s.polyline(s.ents[hit[1]])
            (_, f), a, b = min(((s._seg_dist(a, b, x, y), a, b) for a, b in zip(line[:-1], line[1:])),
                               key=lambda t: t[0][0])
            why = s.insert_control_vertex(hit[1], _add(a, _mul(_sub(b, a), f)))
            if why:
                s.status(why)

        def double_click(self, x, y):
            pass

    class MoveTool(Tool):
        """Move Entities in a 3D sketch: the picked entities moved From/To (a start point, then where it
        goes, on the sketch plane) or by X, Y and Z. Keep relations off: they come loose from the rest."""
        TITLE = "Move"
        VERB = "Move"
        CURSOR = "Sketcher_Pointer_Create_Point"
        HINT = "Move: click the entities to move, then the start point and where it goes (From/To), or type " \
               "X, Y and Z and OK."

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.items = [i for k, i in session.selection if k == "E"]
            self.keep = False
            self.mode = "From/To"
            self.delta = [0.0, 0.0, 0.0]
            self.base = None

        def anchor(self):
            return self.base if self.base is not None else self.s.plane_anchor()

        def exclude(self):
            return tuple(i for k in self.items for i in self.s.ents[k].points) if self.base is not None else ()

        def draw(self, sn):
            s = self.s
            lines = []
            if self.base is not None and sn is not None:
                d = _sub(sn.pos, self.base)
                lines.append([self.base, sn.pos])
                for k in self.items:
                    lines.append([_add(q, d) for q in s.polyline(s.ents[k])])
            s.tool_drawing(lines=lines, guides=[sn.guide] if sn is not None and sn.guide else (),
                           label=sn.label if sn is not None else None, label_at=sn.pos if sn is not None else None)

        def press(self, x, y):
            s = self.s
            if self.base is None:
                # an entity toggles in Entities to Move; a point (a line's end too) or nothing is the start
                hit = s.pick(x, y, dims=False)
                if hit is not None and hit[0] == "E":
                    if hit[1] in self.items:
                        self.items.remove(hit[1])
                    else:
                        self.items.append(hit[1])
                    s.selection = [("E", i) for i in self.items]
                    s.redraw()
                    self._picks_changed()
                    return
                if not self.items or self.mode != "From/To":
                    return
                self.move(x, y)
                self.base = self.last.pos
                self._picks_changed()
                return
            self.move(x, y)
            by = _sub(self.last.pos, self.base)
            self.base = None
            self.apply(by=by)

        def _picks_changed(self):
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(self.s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:8504", _fw_err)

        def double_click(self, x, y):
            pass

        def right_click(self):
            if self.base is not None:
                self.base = None
                self.move(*self.s.cursor())
                return
            self.end()

        def repeat(self):
            ""
            if self.mode == "X/Y/Z":
                return self.apply()
            return "Repeat %ss by the X/Y/Z distances." % self.VERB.lower()

        def apply(self, by=None):
            if not self.items:
                return "Pick the entities to move."
            d = tuple(float(v) for v in (by if by is not None else self.delta))
            if by is None and self.mode == "From/To":
                return "Click the start point, then where it goes; or pick X/Y/Z and type the distances."
            s = self.s
            copy = self.VERB == "Copy"
            got = transform_entities(s.doc, s.pts, s.ents, s.rels, self.items, lambda q: _add(q, d), self.keep,
                                     copy=copy)
            if got is None:
                s.status("%s: the relations hold these entities where they are (turn Keep relations off)."
                         % self.VERB)
                return "The relations hold these entities where they are."
            items = list(self.items)
            n0 = len(s.ents)
            s.write("%s Entities" % self.VERB, *got)
            if copy:
                items = list(range(n0, len(s.ents)))       # Repeat copies the copies on
            self.items = [k for k in items if k < len(s.ents)]
            s.selection = [("E", i) for i in self.items]
            s.redraw()
            self._picks_changed()
            return None

    class CopyTool(MoveTool):
        """Copy Entities in a 3D sketch: as Move, the copies placed From/To or by X, Y and Z; Repeat copies
        the copies again."""
        TITLE = "Copy"
        VERB = "Copy"
        HINT = "Copy: click the entities to copy, then the start point and where it goes (From/To), or type " \
               "X, Y and Z and OK."

    class RotateTool(MoveTool):
        ""


        TITLE = "Rotate"
        VERB = "Rotate"
        HINT = "3D Rotate: click the entities to rotate, then click in Rotation Reference and pick a line or a " \
               "straight model edge to turn about; type the Angle and OK."

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.mode = "Rotate"
            self.axis = None              # (point, unit direction, name) of the Rotation Reference
            self.angle = 0.0

            self.active = "reference" if self.items else "entities"

        def anchor(self):
            return self.s.plane_anchor()

        def exclude(self):
            return ()

        def turning(self):
            """(where, turn) of the rotation now, else None."""
            if self.axis is None:
                return None
            a, u, _ = self.axis
            rot = App.Rotation(App.Vector(*u), self.angle)

            def turn(d):
                v = rot.multVec(App.Vector(*d))
                return (v.x, v.y, v.z)

            def where(q):
                return _add(a, turn(_sub(q, a)))
            return where, turn

        def draw(self, sn):
            s = self.s
            lines = []
            got = self.turning()
            if self.items and got is not None and self.angle:
                for k in self.items:
                    lines.append([got[0](q) for q in s.polyline(s.ents[k])])
            if self.axis is not None:
                a, u, _ = self.axis
                lines.append([_sub(a, _mul(u, 1000.0)), _add(a, _mul(u, 1000.0))])
            s.tool_drawing(lines=lines)

        def _model_line(self, x, y):
            """A straight model edge under the pointer: (point, direction, name), else None."""
            try:
                info = self.s.view.getObjectInfo((int(x), int(y)))
            except Exception:
                info = None
            if not info or info.get("Object") in (None, self.s.obj.Name):
                return None
            comp = str(info.get("Component", "") or "")
            o = self.s.doc.getObject(info["Object"])
            if o is None or not comp.startswith("Edge"):
                return None
            try:
                e = o.Shape.getElement(comp)
                if type(e.Curve).__name__ not in ("Line", "LineSegment"):
                    return None
                p, q = e.Vertexes[0].Point, e.Vertexes[-1].Point
                return (p.x, p.y, p.z), _unit((q.x - p.x, q.y - p.y, q.z - p.z)), "%s.%s" % (o.Label, comp)
            except Exception:
                return None

        def set_reference(self, item):
            """The Rotation Reference from a pick: ("E", k) a sketch line, or (point, direction, name)."""
            s = self.s
            if isinstance(item, tuple) and len(item) == 2 and item[0] == "E":
                e = s.ents[item[1]]
                a, b = s.pts[e.points[0]], s.pts[e.points[1]]
                if _len(_sub(b, a)) < 1e-12:
                    return False
                self.axis = (tuple(a), _unit(_sub(b, a)), "Line%d" % (item[1] + 1))
            else:
                self.axis = item
            self.draw(None)
            self._picks_changed()
            return True

        def press(self, x, y):
            s = self.s
            hit = s.pick(x, y, dims=False)
            if self.active == "reference":
                if hit is not None and hit[0] == "E" and s.ents[hit[1]].kind == "L":
                    self.set_reference(hit)
                    return
                got = self._model_line(x, y)
                if got is not None:
                    self.set_reference(got)
                return
            if hit is not None and hit[0] == "E" and s.ents[hit[1]].kind not in ("P", "Q"):
                if hit[1] in self.items:
                    self.items.remove(hit[1])
                else:
                    self.items.append(hit[1])
                s.selection = [("E", i) for i in self.items]
                s.redraw()
                self._picks_changed()

        def right_click(self):
            self.end()

        def apply(self, by=None):
            if not self.items:
                return "Pick the entities to rotate."
            if self.axis is None:
                return "Pick the Rotation Reference: a line or a straight model edge to turn about."
            s = self.s
            where, turn = self.turning()
            got = transform_entities(s.doc, s.pts, s.ents, s.rels, self.items, where, self.keep, turn=turn)
            if got is None:
                s.status("Rotate: the relations hold these entities where they are (turn Keep relations off).")
                return "The relations hold these entities where they are."
            s.write("Rotate Entities", *got)
            self.items = [k for k in self.items if k < len(s.ents)]
            s.selection = [("E", i) for i in self.items]
            s.redraw()
            self._picks_changed()
            return None

    class SketchPlaneTool(Tool):
        ""

        TITLE = "Plane"
        CURSOR = "Sketcher_Pointer_Create_Point"
        HINT = "Plane: pick up to three references (sketch points or lines, a plane or flat face of the model), " \
               "then OK. Nothing picked: a plane on the sketch plane in use."
        PLANE_TAG = False

        def __init__(self, session, construction=False):
            super().__init__(session, construction)
            self.refs = []
            self.how = []         # each reference's (relation, value, flip): the PropertyManager's buttons
            self._set = set()     # the references whose relation was picked (the rest follow the default)
            for k, i in session.selection:
                self._take((k, i))

        def _take(self, ref):
            s = self.s
            if ref[0] == "E":
                e = s.ents[ref[1]]
                if e.kind == "P":
                    ref = ("P", e.points[0])
                elif e.kind == "L":
                    ref = ("L", ref[1])
                else:
                    return
            if ref in self.refs:
                k = self.refs.index(ref)
                del self.refs[k], self.how[k]
                self._set.discard(ref)
            else:
                if ref[0] == "M":
                    for k in [k for k, r in enumerate(self.refs) if r[0] == "M"][::-1]:
                        self._set.discard(self.refs[k])
                        del self.refs[k], self.how[k]
                if len(self.refs) >= 3:
                    return
                self.refs.append(ref)
                self.how.append(None)
            base = default_plane_relations(self.refs)
            self.how = [h if r in self._set else base[k] for k, (r, h) in enumerate(zip(self.refs, self.how))]

        def set_relation(self, k, relation, value=None, flip=None):
            """The PropertyManager's relation button (with its value and Flip) for reference k."""
            if k >= len(self.refs) or relation not in PLANE_RELATIONS[self.refs[k][0]]:
                return
            old = self.how[k]
            if value is None and old is not None and old[0] == relation:
                value = old[1]
            if flip is None:
                flip = bool(old[2]) if old is not None else False
            self.how[k] = (relation, value, bool(flip))
            self._set.add(self.refs[k])
            self.draw(None)

        def _points(self):
            out = []
            for k, i in self.refs:
                if k == "P":
                    out.append(self.s.pts[i])
                elif k == "L":
                    out += [self.s.pts[j] for j in self.s.ents[i].points[:2]]
            return out

        def move(self, x, y):
            s = self.s
            s.cursor_pos = None
            s.hover = s.pick(x, y, dims=False)
            self.draw(None)

        def draw(self, sn):
            got = make_sketch_plane(self.s, self.refs, how=self.how)
            lines = []
            if not isinstance(got, str):
                pts, ents, _ = got
                a, b, c = (pts[i] for i in ents[-1].points)
                lines = [[a, b, _sub(_add(b, c), a), c, a]]
            self.s.tool_drawing(lines=lines, points=self._points())

        def press(self, x, y):
            s = self.s
            hit = s.pick(x, y, dims=False)
            if hit is not None and hit[0] in ("P", "E"):
                self._take(hit)
            else:
                plane = DimensionTool._model_plane(self, x, y)
                if plane is None:
                    return
                self._take(("M", plane))
            s.selection = [r if r[0] == "P" else ("E", r[1]) for r in self.refs if r[0] in ("P", "L")]
            self.draw(None)
            try:
                from . import sketch3dpm
                sketch3dpm.tool_picks_changed(s, self)
            except Exception as _fw_err:
                _fw_log("sketch3d.py:8778", _fw_err)

        def double_click(self, x, y):
            pass

        def apply(self):
            got = make_sketch_plane(self.s, self.refs, how=self.how)
            if isinstance(got, str):
                return got
            self.refs, self.how, self._set = [], [], set()
            self.s.selection = []
            self.s.write("Plane", *got)
            self.s.activate_plane(len(self.s.ents) - 1)
            return None

    TOOLS = {"line": (LineTool, False), "centerline": (LineTool, True), "spline": (SplineTool, False),
             "point": (PointTool, False), "dimension": (DimensionTool, False), "circle": (CircleTool, False),
             "centerarc": (CenterArcTool, False), "arc3": (ThreePointArcTool, False),
             "rectangle": (RectangleTool, False), "centerrectangle": (CenterRectangleTool, False),
             "midpointline": (LineTool, False), "perimetercircle": (PerimeterCircleTool, False),
             "tangentarc": (TangentArcTool, False), "rect3corner": (ThreePointCornerRectangleTool, False),
             "rect3center": (ThreePointCenterRectangleTool, False), "parallelogram": (ParallelogramTool, False),
             "trim": (TrimTool, False), "convert": (ConvertTool, False), "mirror": (MirrorTool, False),
             "intersection": (IntersectionTool, False), "facecurves": (FaceCurvesTool, False),
             "splineonsurface": (SplineOnSurfaceTool, False), "offsetonsurface": (OffsetOnSurfaceTool, False),
             "insertsplinepoint": (InsertSplinePointTool, False), "equation": (EquationCurveTool, False),
             "fillet": (FilletTool, False), "move": (MoveTool, False), "copy": (CopyTool, False),
             "rotate": (RotateTool, False), "sketchplane": (SketchPlaneTool, False),
             "chamfer": (ChamferTool, False), "extend": (ExtendTool, False), "split": (SplitTool, False),
             "routeline": (RouteLineTool, False), "pen": (PenTool, False), "segment": (SegmentTool, False), "fitspline": (FitSplineTool, False), "jogline": (JogLineTool, False),
             "replace": (ReplaceTool, False), "contourselect": (ContourSelectTool, False),
             "stylespline": (StyleSplineTool, False), "simplifyspline": (SimplifySplineTool, False),
             "insertcontrolvertex": (InsertControlVertexTool, False),
             "addtangency": (AddTangencyControlTool, False), "addcurvature": (AddCurvatureControlTool, False)}

    def start_tool(name):
        s = _session
        if s is None:
            return None
        cls, construction = TOOLS[name]
        midpoint = name == "midpointline"
        if s.tool is not None and type(s.tool) is cls and s.tool.construction == construction \
                and getattr(s.tool, "midpoint", False) == midpoint:
            s.tool.end()       # the running tool's button toggles it off
            return None
        tool = cls(s, construction)
        if midpoint:
            tool.midpoint = True
        if name in s.recent:
            s.recent.remove(name)
        s.recent.insert(0, name)
        s.run_tool(tool)
        return tool


# =================================================================== ribbon, commands
def _shell():
    try:
        from . import shell as shell_module
        return shell_module.shell()
    except Exception:
        return None


def _ribbon(on):
    """The Sketch tab while the 3D sketch is edited, with Exit Sketch in the Sketch button's place
    (the shell does the same for a 2D sketch)."""
    sh = _shell()
    if sh is None or getattr(sh, "topbar", None) is None:
        return
    try:
        target = "Exit3DSketch" if on else "Sketch"
        for page in sh.topbar.pages:
            if page.title != "Sketch":
                continue
            # The Sketch tab is built lazily. On the first 3D sketch it may
            # not have any buttons until selected, so build it before rebinding.
            page.ensure_built()
            for b in page.buttons():
                if b.binding.cmd.key in ("Sketch", "Exit3DSketch", "ExitSketch"):
                    if b.binding.cmd.key != target:
                        sh.rebind(b, target)
                        b._lines = sh.binding(target).cmd.caption.split("\n")
                        b.flyout_keys = () if on else ("Sketch", "Sketch3D", "EditSketch")
                        b.resize(b.sizeHint())
                        b.update()
                        sh.topbar._layout_pages()
        sh.topbar.select("Sketch" if on else "Features")
    except Exception as error:
        App.Console.PrintWarning("FreeCAD 3D Sketch: ribbon: %s\n" % error)


def _active_body():
    try:
        return Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception as _fw_err:
        _fw_log("sketch3d.py:8887", _fw_err)
        return None


def sketch2d_in_edit():
    try:
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc else None
        return vp is not None and editobj.derived(vp, "Sketcher::SketchObject")
    except Exception as _fw_err:
        _fw_log("sketch3d.py:8897", _fw_err)
        return False


def picked_plane():
    """(object, element) of the one plane or flat face picked, else None."""
    try:
        sel = Gui.Selection.getSelectionEx()
    except Exception as _fw_err:
        _fw_log("sketch3d.py:8906", _fw_err)
        return None
    picks = [(x.Object, n.rsplit(".", 1)[-1]) for x in sel for n in (x.SubElementNames or ("",))]
    if len(picks) == 1 and is_plane_pick(*picks[0]):
        return picks[0]
    return None


def new_sketch_on_plane(obj=None, sub=""):
    """Insert > 3D Sketch On Plane (and the plane's right-click menu): a 3D sketch that draws on the
    plane or flat face first, every point placed there On Plane; Tab goes on to XY, YZ, ZX."""
    if obj is None:
        pick = picked_plane()
        if pick is None:
            return None
        obj, sub = pick
    if editing() is None:
        Gui.Selection.clearSelection()
        new_sketch()
    s = _session
    if s is None or not s.set_custom_plane(obj, sub):
        return None
    s.redraw()
    s.status("3D sketch on %s: points go on it (On Plane). Tab changes the sketch plane." % s.plane)
    try:
        from . import sketch3dpm
        sketch3dpm.plane_changed(s)
    except Exception as _fw_err:
        _fw_log("sketch3d.py:8918", _fw_err)
    return s.obj


def _model_view():
    try:    # the active window is a 3D model view (not a drawing sheet or a text page)
        return hasattr(Gui.ActiveDocument.ActiveView, "graphicsView")
    except Exception:
        return False


def new_sketch():
    ""

    if editing() is not None:
        exit_sketch()
        return None
    doc = App.ActiveDocument
    if doc is None or not _model_view():
        return None    # a drawing sheet has no 3D sketch (rcmenus sweep p280)
    picked = [s.Object for s in Gui.Selection.getSelectionEx() if is_sketch3d(s.Object)]
    if picked:
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(picked[0].Name, 0)
        return picked[0]
    doc.openTransaction("3D Sketch")
    try:
        obj = make(doc, _active_body())
        doc.recompute()
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    Gui.Selection.clearSelection()
    Gui.ActiveDocument.setEdit(obj.Name, 0)
    return obj


def exit_sketch():
    obj = editing()
    if obj is None:
        return
    try:
        Gui.getDocument(obj.Document.Name).resetEdit()
    except Exception:
        end_session(obj)
    if editing() is not None:
        end_session(obj)





DELEGATED = {"FreeWorks_Line": "line", "FreeWorks_Centerline": "centerline", "FreeWorks_Spline": "spline",
             "FreeWorks_SmartDimension": "dimension", "FreeWorks_Point": "point", "FreeWorks_Circle": "circle",
             "FreeWorks_CenterArc": "centerarc", "FreeWorks_ThreePointArc": "arc3",
             "FreeWorks_CornerRectangle": "rectangle", "FreeWorks_CenterRectangle": "centerrectangle",
             "FreeWorks_MidpointLine": "midpointline", "FreeWorks_PerimeterCircle": "perimetercircle",
             "FreeWorks_TangentArc": "tangentarc", "FreeWorks_Trim": "trim",
             "FreeWorks_StyleSpline": "stylespline",
             # the Rectangle flyout's own fwsketch tools went first on these buttons: their 3D tools as before
             "FreeWorks_3PointCornerRectangle": "rect3corner", "FreeWorks_3PointCenterRectangle": "rect3center",
             "FreeWorks_Parallelogram": "parallelogram"}

# the sketch patterns; they stay greyed
# the add-on's own (not fwsketch) commands that act in a 3D sketch: their command class is wrapped
OTHER_3D = {("convertentities", "ConvertCommand"): lambda cmd: "convert",
            ("sketchextras", "_Cmd"): lambda cmd: {"SWStyle_FaceCurves": "facecurves",
                                                     "SWStyle_EquationDrivenCurve": "equation",
                                                     "SWStyle_Segment": "segment",
                                                     "SWStyle_FitSpline": "fitspline"}.get(getattr(cmd, "name", "")),
            ("jogline", "_Command"): lambda cmd: "jogline",
            ("replaceentity", "_Command"): lambda cmd: "replace",
            ("nativepms", "MirrorCommand"): lambda cmd: "mirror",
            ("sketchfillet", "SketchFilletCommand"): lambda cmd: "fillet",
            ("sketchmove", "_PageCommand"): lambda cmd: {"Move Entities": "move", "Copy Entities": "copy",
                                                         "Rotate Entities": "rotate"}.get(getattr(cmd, "menu", "")),
            ("shapetypes", "_Command"): lambda cmd: {"3 Point Corner Rectangle": "rect3corner",
                                                      "3 Point Center Rectangle": "rect3center",
                                                      "Parallelogram": "parallelogram"}.get(getattr(cmd, "name", ""))}


def _wrap_other_commands():
    """In a 3D sketch, Convert Entities, Mirror Entities, Sketch Fillet, Move, Copy and Rotate Entities and
    the shape types (3 Point rectangles, Parallelogram) start the 3D tools, the slot types are greyed;
    elsewhere they are what they were."""
    import importlib
    for (module, cls_name), tool_of in OTHER_3D.items():
        try:
            cls = getattr(importlib.import_module("." + module, __package__), cls_name)
        except Exception:
            continue
        if getattr(cls, "_sketch3d_wrapped", False):
            continue
        is_active, activated = cls.IsActive, cls.Activated

        def IsActive(self, is_active=is_active, tool_of=tool_of):
            if editing() is not None:
                return tool_of(self) is not None
            return is_active(self)

        def Activated(self, *args, activated=activated, tool_of=tool_of):
            if editing() is not None:
                name = tool_of(self)
                if name:
                    start_tool(name)
                return
            return activated(self, *args)
        cls.IsActive, cls.Activated, cls._sketch3d_wrapped = IsActive, Activated, True


class _Hook:
    ""


    def claims(self, name):
        if editing() is None:
            return None
        return name in DELEGATED

    def run(self, name):
        if name in DELEGATED:
            start_tool(DELEGATED[name])


COMMAND_INFO = {
    "FreeWorks_Sketch3D": ("3D Sketch", "Adds a new 3D sketch, or edits the picked one: lines, splines and points in "
                           "space. Tab changes the sketch plane."),
    "FreeWorks_Sketch3DExit": ("Exit Sketch", "Exits the 3D sketch and keeps all changes."),
    "FreeWorks_Point": ("Point", "Sketches a point."),
    "FreeWorks_Sketch3DOnPlane": ("3D Sketch On Plane", "Adds a 3D sketch that draws on the picked plane or flat "
                                  "face first (On Plane); Tab goes on to the XY, YZ and ZX planes."),
    "FreeWorks_Sketch3DPlane": ("Plane", "Adds a sketch plane to the 3D sketch through the picked points, lines or "
                                "model plane; you sketch on it (double-click it, or Tab)."),
    "FreeWorks_Sketch3DInsertSplinePoint": ("Insert Spline Point", "Adds a point to a spline where you click on it "
                                            "(in a 2D sketch: the 2D spline's Insert Spline Point)."),
    "FreeWorks_Sketch3DSplineOnSurface": ("Spline on Surface", "Sketches a spline on a face of the model: it goes "
                                          "through the points you click and lies on the face all along."),
    "FreeWorks_Sketch3DOffsetOnSurface": ("Offset on Surface", "Offsets edges of a face across the face, along it "
                                          "(Geodesic) or straight (Euclidean)."),
    "FreeWorks_Sketch3DIntersectionCurve": ("Intersection Curve", "Sketches the curves where the picked faces, planes "
                                            "and bodies meet (in a 2D sketch: FreeCAD's intersection with the sketch "
                                            "plane)."),
}


class _Command:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        text, tip = COMMAND_INFO[self.name]
        pixmap = {"FreeWorks_Sketch3D": "Sketcher_NewSketch", "FreeWorks_Sketch3DExit": "Sketcher_LeaveSketch",
                  "FreeWorks_Point": "Sketcher_CreatePoint", "FreeWorks_Sketch3DOnPlane": "Sketcher_NewSketch",
                  "FreeWorks_Sketch3DPlane": "PartDesign_Plane",
                  "FreeWorks_Sketch3DIntersectionCurve": "Sketcher_Intersection",
                  "FreeWorks_Sketch3DSplineOnSurface": "Sketcher_CreateBSpline",
                  "FreeWorks_Sketch3DInsertSplinePoint": "Sketcher_BSplineInsertKnot",
                  "FreeWorks_Sketch3DOffsetOnSurface": "Sketcher_Offset"}[self.name]
        return {"Pixmap": pixmap, "MenuText": text, "ToolTip": tip, "CmdType": "ForEdit NoTransaction"}

    def IsActive(self):
        if self.name == "FreeWorks_Sketch3D":
            return _model_view() and not sketch2d_in_edit()
        if self.name in ("FreeWorks_Sketch3DExit", "FreeWorks_Sketch3DPlane"):
            return editing() is not None
        if self.name == "FreeWorks_Sketch3DOnPlane":
            return _model_view() and not sketch2d_in_edit() and picked_plane() is not None
        if self.name in ("FreeWorks_Sketch3DSplineOnSurface", "FreeWorks_Sketch3DOffsetOnSurface"):
            return _model_view() and not sketch2d_in_edit()
        if self.name == "FreeWorks_Sketch3DInsertSplinePoint":
            if editing() is not None:
                return any(e.kind == "S" for e in session().ents) if session() is not None else False
            try:
                return bool(Gui.Command.get(_insert_spline_point_2d()).isActive())
            except Exception:
                return False
        if self.name == "FreeWorks_Sketch3DIntersectionCurve":
            if sketch2d_in_edit():
                if "SWStyle_IntersectionCurve2D" in Gui.listCommands():
                    return True
                try:
                    return bool(Gui.Command.get("Sketcher_Intersection").isActive())
                except Exception:
                    return False
            return _model_view()
        if editing() is not None:
            return True
        try:
            return bool(Gui.Command.get("Sketcher_CreatePoint").isActive())
        except Exception:
            return False

    def Activated(self):
        if self.name == "FreeWorks_Sketch3D":
            new_sketch()
        elif self.name == "FreeWorks_Sketch3DExit":
            exit_sketch()
        elif self.name == "FreeWorks_Sketch3DPlane":
            start_tool("sketchplane")
        elif self.name == "FreeWorks_Sketch3DOnPlane":
            new_sketch_on_plane()
        elif self.name == "FreeWorks_Sketch3DInsertSplinePoint":
            if editing() is not None:
                start_tool("insertsplinepoint")
            else:
                Gui.runCommand(_insert_spline_point_2d())
        elif self.name in ("FreeWorks_Sketch3DSplineOnSurface", "FreeWorks_Sketch3DOffsetOnSurface"):
            if editing() is None:
                new_sketch()
            if editing() is not None:
                start_tool("splineonsurface" if "Spline" in self.name else "offsetonsurface")
        elif self.name == "FreeWorks_Sketch3DIntersectionCurve":
            if sketch2d_in_edit():
                Gui.runCommand("SWStyle_IntersectionCurve2D" if "SWStyle_IntersectionCurve2D" in Gui.listCommands()
                               else "Sketcher_Intersection")
                return
            if editing() is None:
                new_sketch()
            if editing() is not None:
                start_tool("intersection")
        elif editing() is not None:
            start_tool("point")
        else:
            Gui.runCommand("Sketcher_CreatePoint")



# command goes first on the button; it starts the 3D tool in a 3D sketch and FreeCAD's command elsewhere
SKETCH_TOOLS_3D = {"FreeWorks_Sketch3DChamfer": ("SketchChamfer", "chamfer", "Sketcher_CreateChamfer", "Sketch Chamfer",
                                                 "Chamfers the corner where two sketch lines meet."),
                   "FreeWorks_Sketch3DExtend": ("Extend", "extend", "Sketcher_Extend", "Extend Entities",
                                                "Extends a sketch line or arc to the next entity it meets."),
                   "FreeWorks_Sketch3DSplit": ("Split", "split", "Sketcher_Split", "Split Entities",
                                               "Splits a sketch entity in two where you click."),
                   "FreeWorks_Sketch3DRepair": ("RepairSketch", None, "Sketcher_ValidateSketch", "Repair Sketch",
                                                "Finds and fixes small gaps and overlapping entities in the sketch."),
                   "FreeWorks_Sketch3DStyleSpline": ("StyleSpline", "stylespline",
                                                     ("FreeWorks_StyleSpline", "Sketcher_CreateBSpline"), "Style Spline",
                                                     "Sketches a spline from its control vertices (one Bezier span)."),
                   "FreeWorks_Sketch3DSimplifySpline": ("SimplifySpline", "simplifyspline",
                                                        ("FreeWorks_SimplifySpline", "Sketcher_BSplineDecreaseDegree"),
                                                        "Simplify Spline", "Makes a spline simpler, within a tolerance."),
                   "FreeWorks_Sketch3DInsertControlVertex": ("InsertControlVertex", "insertcontrolvertex",
                                                             ("Sketcher_BSplineInsertKnot",), "Insert Control Vertex",
                                                             "Adds a control vertex to a Style Spline."),
                   "FreeWorks_Sketch3DReverseTangent": ("ReverseEndpointTangent", "!reverse",
                                                        ("SWStyle_ReverseEndpointTangent", "Sketcher_BSplinePolygon"),
                                                        "Flip Endpoint Tangent",
                                                        "The picked spline end leaves the other way."),
                   "FreeWorks_Sketch3DAddTangencyControl": ("AddTangencyControl", "addtangency",
                                                            ("Sketcher_BSplineInsertKnot",), "Add Tangency Control",
                                                            "Adds a tangent handle where you click on the spline."),
                   "FreeWorks_Sketch3DAddCurvatureControl": ("AddCurvatureControl", "addcurvature",
                                                             ("Sketcher_BSplineInsertKnot",), "Add Curvature Control",
                                                             "Adds a curvature handle where you click on the spline."),
                   "FreeWorks_Sketch3DConvertStyleSpline": ("ConvertToStyleSpline", "!tostyle",
                                                            ("Sketcher_BSplineConvertToNURBS",), "Convert to Style Spline",
                                                            "Changes the picked spline into a Style Spline (its control "
                                                            "vertices)."),
                   "FreeWorks_Sketch3DConvertSpline": ("ConvertToSpline", "!tospline",
                                                       ("Sketcher_BSplineConvertToNURBS",), "Convert to Spline",
                                                       "Changes the picked Style Spline into a spline through points."),
                   "FreeWorks_Sketch3DShowControlPolygon": ("ShowSplineControlPolygon", ":polygon",
                                                            ("Sketcher_BSplinePolygon",), "Show Spline Control Polygon",
                                                            "Shows the picked spline's control polygon."),
                   "FreeWorks_Sketch3DConvertGenericSpline": ("ConvertToGenericSpline", "!togeneric",
                                                              ("Sketcher_BSplineConvertToNURBS",),
                                                              "Convert to Generic Spline",
                                                              "Changes the picked spline into a generic spline: its "
                                                              "shape kept, no handles."),
                   "FreeWorks_Sketch3DRouteLine": ("RouteLine", "routeline", ("Sketcher_CreatePolyline",),
                                                   "Route Line", "Sketches a route of lines along X, Y and Z between "
                                                   "two picked points."),
                   "FreeWorks_Sketch3DAlignSketch": ("AlignSketch", "!align", ("Sketcher_ReorientSketch",),
                                                     "Align Sketch", "Turns the view to run along the picked line."),
                   "FreeWorks_Sketch3DShowInflection": ("ShowInflectionPoints", ":inflections",
                                                        ("FreeWorks_ShowInflectionPoints", "SWStyle_ShowInflectionPoints"),
                                                        "Show Inflection Points",
                                                        "Shows where the picked spline's bend changes side."),
                   "FreeWorks_Sketch3DShowMinimumRadius": ("ShowMinimumRadius", ":min_radius",
                                                           ("FreeWorks_ShowMinimumRadius", "SWStyle_ShowMinimumRadius"),
                                                           "Show Minimum Radius of Curvature",
                                                           "Shows where the picked spline bends tightest, and the radius."),
                   "FreeWorks_Sketch3DShowCurvature": ("ShowCurvatureCombs", ":curvature",
                                                       ("FreeWorks_ShowCurvatureCombs", "Sketcher_BSplineComb"),
                                                       "Show Curvature", "Shows the picked spline's curvature comb."),
                   "FreeWorks_Sketch3DShowHandles": ("ShowSplineHandles", ":handles",
                                                     ("Sketcher_BSplinePolygon",
                                                      "Sketcher_CompBSplineShowHideGeometryInformation"),
                                                     "Show Spline Handles",
                                                     "Shows or hides the picked spline's tangent handles."),
                   "FreeWorks_Sketch3DConstruction": (("ConstructionPlane", "RelConstruction"), None,
                                                      "Sketcher_ToggleConstruction", "Construction Geometry",
                                                      "Turns the picked sketch entities into construction geometry, "
                                                      "or back.")}


class _ToolCommand:
    """A Sketch tab tool that works in 2D (FreeCAD's own command) and in a 3D sketch (ours)."""

    def __init__(self, name):
        self.name = name
        self.key, self.tool, self.native, self.text, self.tip = SKETCH_TOOLS_3D[name]

    def _native(self):
        """FreeCAD's (or the add-on's 2D) command this one stands in for outside a 3D sketch."""
        names = self.native if isinstance(self.native, tuple) else (self.native,)
        have = Gui.listCommands()

        # with FreeCAD's fixed here the 2D button ran stock Extend / Chamfer / Validate (fwsketch-fix47)
        try:
            from . import catalog
            for key in (self.key if isinstance(self.key, tuple) else (self.key,)):
                cmd = catalog.BY_KEY.get(key)
                for n in (cmd.natives if cmd is not None else ()):
                    # fix270: not the button's tool-first wrapper either (SWStyle_TF_...): it runs this
                    # command again, so in a 2D sketch Repair Sketch said "Open a 3D sketch first."
                    if n != self.name and not n.startswith(("FreeWorks_Sketch3D", "SWStyle_TF_")) and n in have:
                        return n
        except Exception as _fw_err:
            _fw_log("sketch3d.py:9230", _fw_err)
        return next((n for n in names if n in have), names[-1])

    PIXMAPS = {"FreeWorks_Sketch3DShowInflection": "Sketcher_BSplineComb",
               "FreeWorks_Sketch3DShowMinimumRadius": "Sketcher_BSplineComb",
               "FreeWorks_Sketch3DShowHandles": "Sketcher_BSplinePolygon"}

    def GetResources(self):
        names = self.native if isinstance(self.native, tuple) else (self.native,)
        return {"Pixmap": self.PIXMAPS.get(self.name, names[-1]), "MenuText": self.text, "ToolTip": self.tip,
                "CmdType": "ForEdit"}

    def IsActive(self):
        if editing() is not None:
            s = session()
            if self.tool == "!reverse":
                return s is not None and s.picked_spline_end() is not None
            if self.tool in ("!tostyle", "!tospline"):
                return s is not None and s.picked_spline(self.tool == "!tospline") is not None
            if self.tool == "!align":
                return True
            if self.tool == "!togeneric":
                return s is not None and any(kind == "E" and s.ents[i].kind == "S" and
                                             not spline_generic(s.ents[i], s.rels) for kind, i in s.selection)
            if self.tool in ("simplifyspline", ) or (self.tool or "").startswith(":"):

                return s is not None and any(kind == "E" and s.ents[i].kind == "S" for kind, i in s.selection)
            return True
        try:
            return bool(Gui.Command.get(self._native()).isActive())
        except Exception:
            return False

    def Activated(self):
        if editing() is None:
            Gui.runCommand(self._native())
        elif self.tool == "!reverse":
            s = session()
            if s is not None:
                s.reverse_end_tangent()
        elif self.tool == "!align":
            s = session()
            if s is not None:
                align_view_to_line(s)
        elif self.tool == "!togeneric":
            s = session()
            k = next((i for kind, i in s.selection if kind == "E" and s.ents[i].kind == "S" and
                      not spline_generic(s.ents[i], s.rels)), None) if s is not None else None
            if k is not None:
                why = s.convert_to_generic(k)
                if why:
                    s.status(why)
        elif self.tool in ("!tostyle", "!tospline"):
            s = session()
            k = s.picked_spline(self.tool == "!tospline") if s is not None else None
            if k is not None:
                why = s.convert_to_spline(k) if self.tool == "!tospline" else s.convert_to_style(k)
                if why:
                    s.status(why)
        elif self.tool is not None and self.tool.startswith(":"):
            s = session()
            if s is not None:
                s.toggle_mark(self.tool[1:])
        elif self.tool is not None:
            start_tool(self.tool)
        elif self.name == "FreeWorks_Sketch3DConstruction":
            s = session()
            if s is not None:
                items = [i for kind, i in s.selection if kind == "E"]
                if items:
                    s.toggle_construction(items)
                else:
                    s.status("Construction Geometry: pick the sketch entities first.")
        else:
            repair_now()


def repair_now():
    """Repair Sketch in the 3D sketch being edited: one undo step, and a message with what was fixed."""
    s = session()
    if s is None:
        return None
    if s.tool is not None:
        s.tool.end()
    (pts, ents, rels), fixed = repair_sketch(s)
    if fixed:
        s.write("Repair Sketch", pts, ents, rels)
    text = "Repair Sketch: " + ("; ".join(fixed) + "." if fixed else "no problems found.")
    s.status(text)
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 8000)
    except Exception as _fw_err:
        _fw_log("sketch3d.py:9322", _fw_err)
    return fixed


def _put_on_buttons():
    """Our 2D/3D commands first on the catalog's Sketch Chamfer, Extend and Split Entities buttons."""
    try:
        from . import catalog
    except Exception:
        return
    for name, info in SKETCH_TOOLS_3D.items():
        for key in (info[0] if isinstance(info[0], tuple) else (info[0],)):
            cmd = catalog.BY_KEY.get(key)
            if cmd is not None and name not in cmd.natives:
                cmd.natives = (name,) + tuple(cmd.natives)
            # a button already made binds FreeCAD's command: bind it again
            shell = _shell()
            b = getattr(shell, "bindings", {}).get(key) if shell is not None else None
            if b is not None and getattr(b, "native", None) != name:
                try:
                    b.action = None
                    b.resolve()
                    b.update_state()
                except Exception as _fw_err:
                    _fw_log("sketch3d.py:9346", _fw_err)


class _SelectionCommand:
    """Dissolve (3D: split points back to one entity; 2D: Dissolve Sketch Text) and Create Sketch from
    Selections (2D and 3D)."""

    def __init__(self, name):
        self.name = name

    def GetResources(self):
        if self.name == "FreeWorks_Sketch3DDissolve":
            return {"Pixmap": "Sketcher_JoinCurves", "MenuText": "Dissolve",
                    "ToolTip": "Joins sketch entities back into one where they were split (pick the split points, "
                               "or the entities); in a 2D sketch, dissolves sketch text.", "CmdType": "ForEdit"}
        return {"Pixmap": "Sketcher_NewSketch", "MenuText": "Create Sketch from Selections",
                "ToolTip": "Copies the picked sketch entities into a new sketch.", "CmdType": "ForEdit"}

    def _picked2d(self):
        try:
            return any(n.startswith("Edge") for o in Gui.Selection.getSelectionEx() for n in o.SubElementNames)
        except Exception:
            return False

    def IsActive(self):
        s = session() if editing() is not None else None
        if self.name == "FreeWorks_Sketch3DDissolve":
            if s is not None:
                return bool(s.selection)
            try:
                return bool(Gui.Command.get("SWStyle_DissolveSketchText").isActive())
            except Exception:
                return False
        if s is not None:
            return any(kind == "E" for kind, i in s.selection)
        return sketch2d_in_edit() and self._picked2d()

    def Activated(self):
        s = session() if editing() is not None else None
        if self.name == "FreeWorks_Sketch3DDissolve":
            if s is None:
                Gui.runCommand("SWStyle_DissolveSketchText")
                return
            points = [i for kind, i in s.selection if kind == "P"]
            for kind, k in s.selection:
                if kind == "E":
                    points += s.ents[k].points
            (pts, ents, rels), n = dissolve_points(s, list(dict.fromkeys(points)))
            if n:
                s.select([])
                s.write("Dissolve", pts, ents, rels)
            s.status("Dissolve: %s." % ("%d joined" % n if n else "nothing to join there (pick a split point)"))
            return
        sketch_from_selections()


def _insert_spline_point_2d():
    ""
    return "FreeWorks_InsertSplinePoint" if "FreeWorks_InsertSplinePoint" in Gui.listCommands() \
        else "Sketcher_BSplineInsertKnot"


_registered = False


def register():
    ""
    global _registered
    if _registered or not GUI:
        return
    for name in COMMAND_INFO:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    for name in SKETCH_TOOLS_3D:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _ToolCommand(name))
    for name in ("FreeWorks_Sketch3DDissolve", "FreeWorks_SketchFromSelections"):
        if name not in Gui.listCommands():
            Gui.addCommand(name, _SelectionCommand(name))
    _put_on_buttons()
    for module in ("twodto3d", "pentools"):

        try:
            import importlib
            importlib.import_module("." + module, __package__).register()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s: %s\n" % (module, error))
    try:
        from .fwsketch import commands as fwcommands
        hooks = getattr(fwcommands, "HOOKS", None)
        if hooks is not None and not any(isinstance(h, _Hook) for h in hooks):
            hooks.append(_Hook())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD 3D Sketch: sketch tools hook: %s\n" % error)
    try:
        _wrap_other_commands()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD 3D Sketch: Convert/Mirror in 3D: %s\n" % error)
    _registered = True
