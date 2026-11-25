# SPDX-License-Identifier: LGPL-2.1-or-later
""













import math

import FreeCAD as App
import Part
import Sketcher

TOL = 1e-6
CLOSED = ("Circle", "Ellipse")
SPLITTABLE = ("LineSegment", "ArcOfCircle", "Circle", "ArcOfEllipse", "Ellipse", "ArcOfParabola",
              "ArcOfHyperbola", "BSplineCurve")


# ---------------------------------------------------------------- curve parameters
def _type(g):
    return type(g).__name__


def closed(g):
    return _type(g) in CLOSED


def bounds(g):
    return g.FirstParameter, g.LastParameter


def period(g):
    return g.LastParameter - g.FirstParameter if closed(g) else None


def param(g, point):
    """The curve parameter of point, inside the entity's own parameter range."""
    u = g.parameter(App.Vector(point.x, point.y, 0))
    first, last = bounds(g)
    if _type(g) in ("ArcOfCircle", "Circle", "ArcOfEllipse", "Ellipse"):
        while u < first - TOL:
            u += 2 * math.pi
        while u > last + TOL and u - 2 * math.pi >= first - TOL:
            u -= 2 * math.pi
    return u


def point(g, u):
    p = g.value(u)
    return App.Vector(p.x, p.y, 0)


# ---------------------------------------------------------------- where entities meet
def meets(sketch, gid, others):
    """Points where entity gid meets the entities others (ids), as [(param, other)]."""
    geos = sketch.Geometry
    g = geos[gid]
    edge = g.toShape()
    out = []
    for j in others:
        if j == gid or j < 0 or j >= len(geos):
            continue
        try:
            sec = edge.section(geos[j].toShape())
        except Exception:
            continue
        for v in sec.Vertexes:
            out.append((param(g, v.Point), j))
    out.sort()
    uniq = []
    for u, j in out:
        if not uniq or abs(u - uniq[-1][0]) > TOL:
            uniq.append((u, j))
    return uniq


def cutters(sketch, gid, skip_construction=False):
    """The entities that cut gid: every other one, without construction geometry if asked."""
    return [j for j in range(len(sketch.Geometry))
            if j != gid and not (skip_construction and sketch.getConstruction(j))]


def cuts(sketch, gid, others):
    """Parameters inside the entity where others cut it (its own ends are not cuts)."""
    g = sketch.Geometry[gid]
    first, last = bounds(g)
    us = [u for u, _j in meets(sketch, gid, others)]
    if closed(g):
        return us
    return [u for u in us if first + TOL < u < last - TOL]


def piece(g, us, u):
    """(lo, hi) of the piece of g around parameter u between the cuts us; None when the
    piece is the whole entity (no cut, or a closed curve cut once at most)."""
    first, last = bounds(g)
    if closed(g):
        if len(us) < 2:
            return None if not us else (us[0], us[0] + period(g))
        below = [c for c in us if c <= u]
        lo = below[-1] if below else us[-1] - period(g)
        above = [c for c in us if c > u]
        hi = above[0] if above else us[0] + period(g)
        return lo, hi
    lo = max([c for c in us if c < u] or [first])
    hi = min([c for c in us if c > u] or [last])
    if lo <= first + TOL and hi >= last - TOL:
        return None
    return lo, hi


# ---------------------------------------------------------------- making a piece its own entity
def isolate(sketch, gid, lo, hi):
    """Splits entity gid so that the piece lo..hi is an entity of its own.
    Returns (piece id, [ids of the other pieces])."""
    g = sketch.Geometry[gid]
    others = []
    lo_at, hi_at = point(g, lo), point(g, hi)     # a split can renumber the parameters
    if closed(g):
        whole = hi - lo >= period(g) - TOL
        sketch.split(gid, lo_at)                   # the circle opens at lo: gid is lo..lo+period
        if not whole:
            sketch.split(gid, hi_at)               # gid is lo..hi, the rest is new
            others.append(len(sketch.Geometry) - 1)
        return gid, others
    first, last = bounds(g)
    if lo > first + TOL:
        sketch.split(gid, lo_at)                   # gid keeps first..lo, lo..last is new
        others.append(gid)
        gid = len(sketch.Geometry) - 1
    g = sketch.Geometry[gid]
    if param(g, hi_at) < g.LastParameter - TOL:
        sketch.split(gid, hi_at)                   # gid keeps lo..hi, hi..last is new
        others.append(len(sketch.Geometry) - 1)
    return gid, others


def _drop(sketch, ids, construction):
    """Deletes the entities ids, or makes them construction. Returns the deleted ids."""
    if construction:
        for i in ids:
            if not sketch.getConstruction(i):
                sketch.setConstruction(i, True)
        return []
    ids = sorted(set(ids))
    if ids:
        sketch.delGeometries(ids)
    return ids


def _undo(sketch, label, change):
    doc = sketch.Document
    doc.openTransaction(label)
    try:
        result = change()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    sketch.solve()
    return result


def shift(ids, deleted):
    """Ids after the entities deleted are gone (None for a deleted one)."""
    out = []
    for i in ids:
        if i is None or i in deleted:
            out.append(None)
        else:
            out.append(i - sum(1 for d in deleted if d < i))
    return out


# ---------------------------------------------------------------- the trims
def trim(sketch, gid, picked, construction=False, skip_construction=False):
    """Trims the piece of gid around the point picked (sketch coordinates) back to the closest
    intersections, as FreeCAD's Trim does; with construction the piece stays as construction.
    An entity nothing cuts goes whole (or turns construction whole). Returns the deleted ids."""
    def change():
        g = sketch.Geometry[gid]
        if not construction:
            sketch.trim(gid, App.Vector(picked.x, picked.y, 0))
            return None
        span = piece(g, cuts(sketch, gid, cutters(sketch, gid, skip_construction)), param(g, picked))
        if span is None:
            return _drop(sketch, [gid], True)
        if _type(g) not in SPLITTABLE:
            raise ValueError("this kind of entity cannot be kept as construction")
        p, _rest = isolate(sketch, gid, *span)
        return _drop(sketch, [p], True)
    return _undo(sketch, "Trim", change)


def _bounded(sketch, gid, bounds_ids, picked):
    """(lo, hi) on gid between its crossings with the two bounding entities, nearest the pick."""
    g = sketch.Geometry[gid]
    u = param(g, picked)
    sides = []
    for b in bounds_ids:
        us = [c for c, _j in meets(sketch, gid, [b])]
        if not us:
            return None
        sides.append(min(us, key=lambda c: abs(c - u)))
    lo, hi = sorted(sides)
    return (lo, hi) if hi - lo > TOL else None


def trim_inside(sketch, gid, bounds_ids, picked, construction=False):
    """Trim away inside: the part of gid between the two bounding entities goes."""
    g = sketch.Geometry[gid]
    if closed(g):
        raise ValueError("Trim away inside works on open entities")
    span = _bounded(sketch, gid, bounds_ids, picked)
    if span is None:
        raise ValueError("The entity must cross both bounding entities")

    def change():
        p, _rest = isolate(sketch, gid, *span)
        return _drop(sketch, [p], construction)
    return _undo(sketch, "Trim", change)


def trim_outside(sketch, gid, bounds_ids, picked, construction=False):
    """Trim away outside: the part of gid between the two bounding entities stays."""
    g = sketch.Geometry[gid]
    if closed(g):
        raise ValueError("Trim away outside works on open entities")
    span = _bounded(sketch, gid, bounds_ids, picked)
    if span is None:
        raise ValueError("The entity must cross both bounding entities")

    def change():
        _p, rest = isolate(sketch, gid, *span)
        return _drop(sketch, rest, construction)
    return _undo(sketch, "Trim", change)


def _line(g):
    return Part.Line(App.Vector(g.StartPoint.x, g.StartPoint.y, 0), App.Vector(g.EndPoint.x, g.EndPoint.y, 0))


def corner(sketch, first, first_pick, second, second_pick):
    """Corner: extends or trims two lines until they meet. Each keeps the end on the side
    where it was picked. The corner gets a Coincident relation."""
    geos = sketch.Geometry
    g1, g2 = geos[first], geos[second]
    if first == second or _type(g1) != "LineSegment" or _type(g2) != "LineSegment":
        raise ValueError("Corner works on two lines")
    hits = _line(g1).intersect(_line(g2))
    if not hits:
        raise ValueError("The lines are parallel and have no corner")
    corner_point = App.Vector(hits[0].X, hits[0].Y, 0)

    def moved_end(g, picked):
        """The end (1 start, 2 end) that moves to the corner."""
        d = g.EndPoint - g.StartPoint
        at = (corner_point - g.StartPoint).dot(d)
        pick = (App.Vector(picked.x, picked.y, 0) - g.StartPoint).dot(d)
        return 2 if pick < at else 1

    ends = (moved_end(g1, first_pick), moved_end(g2, second_pick))

    def change():
        for gid, end in zip((first, second), ends):
            g = sketch.Geometry[gid]
            if (g.StartPoint if end == 1 else g.EndPoint).distanceToPoint(corner_point) > TOL:
                sketch.moveGeometry(gid, end, corner_point)
        already = any(c.Type == "Coincident" and {(c.First, c.FirstPos), (c.Second, c.SecondPos)}
                      == {(first, ends[0]), (second, ends[1])} for c in sketch.Constraints)
        if not already:
            sketch.addConstraint(Sketcher.Constraint("Coincident", first, ends[0], second, ends[1]))
        return []
    return _undo(sketch, "Trim", change)
