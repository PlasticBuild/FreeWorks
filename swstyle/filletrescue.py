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

V = App.Vector
last = []       # (how, picked edge count) of the last rescues, for the checks


def convex(shape, edge):
    """True for an outside edge (the material between its faces less than half round), False for
    an inside one, None when it cannot tell: three points along the edge, each probed a little way
    into the wedge between the faces at two distances, must all agree."""
    import Part
    try:
        faces = shape.ancestorsOfType(edge, Part.Face)
        if len(faces) != 2:
            return None
        votes = set()
        size = max(edge.Length, 1e-6)
        for k in (0.25, 0.5, 0.75):
            t0 = edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * k
            p = edge.valueAt(t0)
            t = edge.tangentAt(t0)
            way = V(0, 0, 0)
            for f in faces:
                n = f.normalAt(*f.Surface.parameter(p))
                d = n.cross(t)
                d.normalize()
                if f.distToShape(Part.Vertex(p + d * 1e-3))[0] > 1e-5:
                    d = d * -1
                way = way + d
            if way.Length < 1e-6:
                return None         # (nearly) flat or folded back: no telling
            way.normalize()
            for reach in (1e-3, min(1e-2, 0.01 * size)):
                votes.add(bool(shape.isInside(p + way * reach, 1e-7, True)))
        return votes.pop() if len(votes) == 1 else None
    except Exception:
        return None


def plausible(base, out, edges):
    """False when a fillet or chamfer on edges that meet three or more at a corner, all outside
    ones, came back adding
    material (or on inside ones, taking it away): OpenCascade has "made" such a one round a
    pyramid's apex, bulging past it. The quick test (volume and box) flags a result; the material
    added (taken) confirms it."""
    # only where three or more of the edges meet at a corner: that is where OpenCascade comes back
    # wrong; elsewhere (an alloy wheel's hub circles) an edge's kind is not worth the risk
    ends = {}
    for e in edges:
        for v in e.Vertexes:
            key = tuple(round(c, 6) for c in v.Point)
            ends[key] = ends.get(key, 0) + 1
    if not ends or max(ends.values()) < 3:
        return True
    kinds = set(convex(base, e) for e in edges)
    if kinds == {True}:
        try:        # tight boxes: a round's BoundBox reaches out to its poles
            bb, ob = base.optimalBoundingBox(False), out.optimalBoundingBox(False)   # not a display mesh
        except Exception:
            bb, ob = base.BoundBox, out.BoundBox
        grown = (ob.XMin < bb.XMin - 1e-4 or ob.YMin < bb.YMin - 1e-4 or ob.ZMin < bb.ZMin - 1e-4 or
                 ob.XMax > bb.XMax + 1e-4 or ob.YMax > bb.YMax + 1e-4 or ob.ZMax > bb.ZMax + 1e-4)
        flagged = grown or out.Volume > base.Volume * (1 + 1e-9) + 1e-9
    elif kinds == {False}:
        flagged = out.Volume < base.Volume * (1 - 1e-9) - 1e-9
    else:
        return True
    if not flagged:
        return True
    try:        # a round on outside edges never adds material, on inside ones never takes any
        tol = 1e-6 * max(base.Volume, 1.0)
        if kinds == {True}:
            return out.cut(base).Volume <= tol
        return base.cut(out).Volume <= tol
    except Exception:
        return True


def _plain_fillet(shape, pairs):
    from . import multiradius
    return multiradius.per_edge(shape, "Fillet", [(i, r, r) for i, r in pairs])


def _overflowing(shape, pairs):
    import Part
    from . import conicfillet
    out = []
    for i, r in pairs:
        e = shape.Edges[i - 1]
        faces = shape.ancestorsOfType(e, Part.Face)
        if len(faces) != 2 or e.Curve.__class__.__name__ not in ("Line", "LineSegment"):
            continue
        if any(f.Surface.__class__.__name__ != "Plane" for f in faces):
            continue
        try:
            if conicfillet.overflows(shape, e, faces, r, r, r):
                out.append((i, r))
        except Exception:
            continue
    return out


def _again(shape, old, pairs):
    """pairs found again on shape by their edges' middles (a round trims an edge, never moves its
    middle), or None when one is lost."""
    from . import multiradius
    out = []
    for i, r in pairs:
        j = multiradius._find(shape, multiradius._mid(old.Edges[i - 1]))
        if j is None:
            return None
        out.append((j, r))
    return out


def by_overflow(shape, pairs):
    from . import conicfillet, multiradius
    over = _overflowing(shape, pairs)
    if not over:
        return None
    rest = [p for p in pairs if p not in over]
    for kind in ("Keep surface", "Keep edge"):
        try:
            cur = shape
            if rest:
                cur = _plain_fillet(shape, rest)
            found = _again(cur, shape, over)
            if found is None:
                continue
            radius = max(r for i, r in found)
            if len(set(r for i, r in found)) > 1:
                for r in sorted(set(r for _j, r in found), reverse=True):      # one radius group at a time
                    k = _again(cur, shape, [p for p in over if p[1] == r])
                    cur = conicfillet.conic_fillet(cur, [cur.Edges[x - 1] for x, _r in k], r, r, "Circular",
                                                   0.5, 1.0, r, False, 0.0, kind)
            else:
                cur = conicfillet.conic_fillet(cur, [cur.Edges[j - 1] for j, _r in found], radius, radius,
                                               "Circular", 0.5, 1.0, radius, False, 0.0, kind)
            rounded = all(multiradius._find(cur, multiradius._mid(shape.Edges[i - 1])) is None for i, _r in over)
            if cur.isValid() and len(cur.Solids) == 1 and rounded:     # the picked edges really rounded
                return cur, "overflow " + kind
        except Exception:
            continue
    return None


def _corners(shape, pairs):
    """Vertices where three or more of the picked edges meet: (vertex, its edges)."""
    from . import setbackfillet
    picked = [shape.Edges[i - 1] for i, r in pairs]
    out = []
    for v in shape.Vertexes:
        at = setbackfillet.vertex_edges(shape, v)
        mine = [e for e in at if any(e.isSame(p) for p in picked)]
        if len(mine) >= 3:
            out.append((v, at))
    return out


def by_corners(shape, pairs):
    from . import setbackfillet
    corners = _corners(shape, pairs)
    if not corners:
        return None
    radius = max(r for i, r in pairs)
    for k in (2.0, 3.0, 1.5):
        try:
            cut = shape
            plan = []
            for v, at in corners:
                s = min(k * radius, 0.4 * min(e.Length for e in at))
                if s <= radius:
                    raise RuntimeError("edges too short")
                dirs = [setbackfillet._away(e, v) for e in at]
                plan.append((v, dirs, [s] * len(at)))
                cut = cut.cut(setbackfillet._corner_region(v, dirs, [s] * len(at)))
                if len(cut.Solids) == 1:
                    cut = cut.Solids[0]
            found = _again(cut, shape, pairs)
            if found is None:
                continue
            cur = _plain_fillet(cut, found)
            for v, dirs, dists in plan:
                cur = setbackfillet.setback_corner(cur, v, dirs, dists)
            if cur.isValid() and len(cur.Solids) == 1:
                return cur, "corners"
        except Exception:
            continue
    return None


def rescue(shape, pairs):
    for way in (by_overflow, by_corners):
        try:
            got = way(shape, pairs)
        except Exception:
            got = None
        if got is not None:
            if not plausible(shape, got[0], [shape.Edges[i - 1] for i, r in pairs]):
                continue
            last.append((got[1], len(pairs)))
            del last[:-20]
            return got
    raise RuntimeError("The fillet could not be made at these sizes: try smaller ones.")


def constant(base, edges, r, keep=True):
    ""


    from . import multiradius, setbackfillet
    try:
        out = base.makeFillet(r, edges)
        if out.isValid() and len(out.Solids) == 1 and plausible(base, out, edges):
            return out.Solids[0]
    except Exception as _fw_err:
        _fw_log("filletrescue.py:246", _fw_err)
    pairs = [(next(i for i, g in enumerate(base.Edges, 1) if g.isSame(e)), r) for e in edges]
    try:
        if keep:
            got = setbackfillet.keep_features(base, pairs, [], False, [], None)
            if got is not None:
                return got
        else:
            clean, new_pairs, _s = setbackfillet._clean(base, pairs, [])
            if clean is not base:
                return multiradius.multi_fillet(clean, new_pairs)
    except Exception as _fw_err:
        _fw_log("filletrescue.py:258", _fw_err)
    try:
        return multiradius.multi_fillet(base, pairs)
    except RuntimeError:
        if len(pairs) < 2:
            raise
    return multiradius.in_passes(base, pairs)[0]
