# SPDX-License-Identifier: LGPL-2.1-or-later
""











import math

import Part

from .vec import add, sub, mul, dot, cross, length, dist, unit, perp, xy
from . import inference as I

# Guide kinds
HORIZONTAL, VERTICAL = "Horizontal", "Vertical"
PARALLEL, PERPENDICULAR = "Parallel", "Perpendicular"
ALIGN_H, ALIGN_V = "AlignHorizontal", "AlignVertical"
EXTENSION = "Extension"
ARC_TANGENT, ARC_RADIAL = "ArcTangent", "ArcRadial"
ANGLE_STEP = "AngleStep"

_DIRECTIONS = (HORIZONTAL, VERTICAL, PARALLEL, PERPENDICULAR, ARC_TANGENT, ARC_RADIAL, ANGLE_STEP)
# The sketch relation a direction guide stands for
RELATION_OF = {HORIZONTAL: "Horizontal", VERTICAL: "Vertical", PARALLEL: "Parallel",
               PERPENDICULAR: "Perpendicular", ARC_TANGENT: "Tangent", ARC_RADIAL: "Perpendicular"}

SQRT2 = math.sqrt(2.0)


class Guide:
    """An infinite guide line through origin along the unit vector direction."""
    __slots__ = ("kind", "origin", "direction", "geo", "pos")

    def __init__(self, kind=None, origin=(0.0, 0.0), direction=(1.0, 0.0), geo=I.GEO_UNDEF, pos=I.NONE):
        self.kind, self.origin, self.direction, self.geo, self.pos = kind, origin, direction, geo, pos

    def valid(self):
        return self.kind is not None

    def is_direction(self):
        return self.kind in _DIRECTIONS

    def adds_relation(self):
        return self.is_direction() and self.kind != ANGLE_STEP

    def __repr__(self):
        return "Guide(%s, origin=(%.6g, %.6g), dir=(%.4f, %.4f), geo=%s, pos=%s)" % (
            self.kind, self.origin[0], self.origin[1], self.direction[0], self.direction[1], self.geo, self.pos)


class GuideFilter:
    __slots__ = ("directions", "parallels", "alignments", "extensions", "angles")

    def __init__(self, directions=True, parallels=True, alignments=True, extensions=True, angles=True):
        self.directions, self.parallels, self.alignments, self.extensions, self.angles = \
            directions, parallels, alignments, extensions, angles


class GuideQuery:
    def __init__(self, cursor, radius, angle_tolerance=0.0, anchor=None, woken=(), include_axes=True,
                 align_all_points=True, recent=(), filter=None, point_filter=None, axis_band=0.0,
                 min_direction_length=0.0, angle_step=0.0):
        self.cursor = cursor
        self.radius = radius                      # sketch units
        self.angle_tolerance = angle_tolerance    # radians
        self.axis_band = axis_band                # sketch units sideways, 0 = angle alone decides
        self.min_direction_length = min_direction_length
        self.angle_step = angle_step              # radians, 0 = no angle snap
        self.anchor = anchor                      # (x, y) or None
        self.woken = list(woken)
        self.include_axes = include_axes
        self.align_all_points = align_all_points
        self.recent = list(recent)
        self.filter = filter or GuideFilter()
        self.point_filter = point_filter or I.Filter()

    @property
    def has_anchor(self):
        return self.anchor is not None


class GuideResult:
    def __init__(self, position):
        self.position = position
        self.guides = []
        self.crossing = False

    def valid(self):
        return bool(self.guides)

    def direction(self):
        for g in self.guides:
            if g.is_direction():
                return g
        return None


class CirclePoint:
    __slots__ = ("kind", "position")
    TANGENT, NORMAL = "Tangent", "Normal"

    def __init__(self, kind, position):
        self.kind, self.position = kind, position


def _tol(scale):
    return 1e-9 * (1.0 + abs(scale))


def same_point(a, b):
    return dist(a, b) <= _tol(max(length(a), length(b)))


# Per-geometry results, kept while the snapper hands the same geometry objects (snap.entries
# caches them between moves): a dense sketch is read once, not on every pointer move.
_SEG, _CIRC = {}, {}
_CACHE_MAX = 8192


def _cached(cache, g, make):
    hit = cache.get(id(g))
    if hit is not None and hit[0] is g:
        return hit[1]
    if len(cache) > _CACHE_MAX:
        cache.clear()
    value = make(g)
    cache[id(g)] = (g, value)     # the reference keeps id(g) from being reused
    return value


def _make_segment(g):
    p0, p1 = xy(g.StartPoint), xy(g.EndPoint)
    if dist(p0, p1) <= _tol(max(length(p0), length(p1))):
        return None
    return p0, p1


def _segment(entry):
    g = entry[1]
    if g is None or type(g) is not Part.LineSegment:
        return None
    return _cached(_SEG, g, _make_segment)


def _ends_at(seg, point):
    """seg (p0, p1) has an end at point (same_point, with a cheap reject first)."""
    for p in seg:
        if abs(p[0] - point[0]) <= 1e-6 * (1.0 + abs(point[0])) and abs(p[1] - point[1]) <= 1e-6 * (1.0 + abs(point[1])) \
                and same_point(p, point):
            return True
    return False


def _circle(entry):
    """(center, radius, is_arc, start, end) or None."""
    g = entry[1]
    if g is None or type(g) not in (Part.Circle, Part.ArcOfCircle):
        return None
    return _cached(_CIRC, g, lambda gg: _make_circle(entry))


def _make_circle(entry):
    g = entry[1]
    if g is None:
        return None
    if type(g) is Part.Circle:
        c, r, arc, s, e = xy(g.Center), g.Radius, False, None, None
    elif type(g) is Part.ArcOfCircle:
        c, r, arc = xy(g.Center), g.Radius, True
        s, e = I.arc_ends_ccw(g)
    else:
        return None
    if not r > 0.0:
        return None
    return c, r, arc, s, e


def _find(entries, geo_id):
    for e in entries:
        if e[0] == geo_id:
            return e
    return None


def _folded_angle(a, b):
    cosine = abs(dot(a, b)) / (length(a) * length(b))
    return math.acos(min(max(cosine, 0.0), 1.0))


def _along_or_against(direction, reference):
    return mul(direction, -1.0) if dot(reference, direction) < 0.0 else direction


def project_onto(guide, point):
    t = dot(sub(point, guide.origin), guide.direction)
    return add(guide.origin, mul(guide.direction, t))


def _angle_step_guide(entries, q, drawn):
    guide = Guide()
    if not q.filter.angles or not q.angle_step > 0.0:
        return guide
    drawn_angle = math.atan2(drawn[1], drawn[0])
    best = [q.angle_tolerance]
    hv = getattr(q, "hv_tolerance", None)
    hv = q.angle_tolerance if hv is None else hv

    def offer(reference_angle, geo_id):
        relative = drawn_angle - reference_angle
        snapped = reference_angle + round(relative / q.angle_step) * q.angle_step
        deviation = abs(drawn_angle - snapped)
        if deviation > best[0]:
            return
        if deviation > hv and min(abs(math.cos(snapped)), abs(math.sin(snapped))) < 1e-9:
            return
        best[0] = deviation
        guide.kind, guide.origin = ANGLE_STEP, q.anchor
        guide.direction = (math.cos(snapped), math.sin(snapped))
        guide.geo, guide.pos = geo_id, I.NONE

    offer(0.0, I.GEO_UNDEF)
    for e, seg in _anchored(entries, q.anchor)[0]:
        along = sub(seg[1], seg[0])
        offer(math.atan2(along[1], along[0]), e[0])
    return guide


def cross_guides(a, b):
    """Crossing point of two guides, or None when parallel."""
    den = cross(a.direction, b.direction)
    if abs(den) <= 1e-12:
        return None
    s = cross(sub(b.origin, a.origin), b.direction) / den
    return add(a.origin, mul(a.direction, s))


def line_across_box(point, direction, box):
    """The part of the line through point along direction inside box = (xmin, ymin, xmax, ymax):
    (a, b) or None."""
    if box is None or length(direction) <= 0.0:
        return None
    xmin, ymin, xmax, ymax = box
    t = [-math.inf, math.inf]

    def clip(p, qv):
        if p == 0.0:
            return qv >= 0.0
        tt = qv / p
        if p < 0.0:
            t[0] = max(t[0], tt)
        else:
            t[1] = min(t[1], tt)
        return True

    if not clip(-direction[0], point[0] - xmin) or not clip(direction[0], xmax - point[0]) \
            or not clip(-direction[1], point[1] - ymin) or not clip(direction[1], ymax - point[1]) \
            or t[0] > t[1]:
        return None
    return add(point, mul(direction, t[0])), add(point, mul(direction, t[1]))


def _anchor_on_circle(entry, circ, anchor):
    """pos id of the arc vertex at the anchor, NONE when elsewhere on the curve, or False."""
    c, r, is_arc, s, e = circ
    if is_arc and same_point(s, anchor):
        return I.START
    if is_arc and same_point(e, anchor):
        return I.END
    away = I.distance_to_curve(entry[0], entry[1], anchor)
    if away < 0.0 or away > 1e-7 * (1.0 + r):
        return False
    return I.NONE


def _anchored(entries, anchor):
    """What the anchor touches, found once per entries list and anchor (neither depends on the pointer): the
    segments with an end at the anchor, as (entry, segment), and the circles/arcs the anchor lies on, as
    (entry, pos, radial, tangent). The snapper hands the same entries list on every move until the sketch changes."""
    hit = _ANCHORED[0]
    if hit is not None and hit[0] is entries and hit[1] == anchor:
        return hit[2], hit[3]
    ends, rounds = [], []
    for e in entries:
        seg = _segment(e)
        if seg and _ends_at(seg, anchor):
            ends.append((e, seg))
    for e in entries:
        circ = _circle(e)
        if not circ:
            continue
        c, r = circ[0], circ[1]
        outward = sub(anchor, c)
        distance = length(outward)
        if not distance > _tol(r):
            continue
        pos = _anchor_on_circle(e, circ, anchor)
        if pos is False:
            continue
        radial = mul(outward, 1.0 / distance)
        rounds.append((e, pos, radial, perp(radial)))
    _ANCHORED[0] = (entries, anchor, ends, rounds)
    return ends, rounds


_ANCHORED = [None]


def find_direction_guide(entries, q):
    guide = Guide()
    if not q.has_anchor or not q.filter.directions or not q.angle_tolerance > 0.0:
        return guide
    drawn = sub(q.cursor, q.anchor)
    n = length(drawn)
    if not n > _tol(length(q.anchor)) or n < q.min_direction_length:
        return guide
    guide.origin = q.anchor

    angle = math.atan2(abs(drawn[1]), abs(drawn[0]))
    nearer_h = abs(drawn[1]) <= abs(drawn[0])
    hv = getattr(q, "hv_tolerance", None)
    hv = q.angle_tolerance if hv is None else hv
    if angle <= hv or (nearer_h and abs(drawn[1]) <= q.axis_band):
        guide.kind = HORIZONTAL
        guide.direction = (-1.0 if drawn[0] < 0.0 else 1.0, 0.0)
        return guide
    if math.pi / 2 - angle <= hv or (not nearer_h and abs(drawn[0]) <= q.axis_band):
        guide.kind = VERTICAL
        guide.direction = (0.0, -1.0 if drawn[1] < 0.0 else 1.0)
        return guide

    if not q.filter.parallels:
        return _angle_step_guide(entries, q, drawn)
    best = [q.angle_tolerance]
    tie_slack = 1e-9

    def offer(kind, deviation, along, geo_id, pos, own_curve=False):
        if deviation > best[0] + (tie_slack if own_curve else 0.0):
            return
        best[0] = min(best[0], deviation)
        guide.kind = kind
        guide.direction = _along_or_against(along, drawn)
        guide.geo, guide.pos = geo_id, pos

    def consider(e):
        seg = _segment(e)
        if not seg:
            return
        along = unit(sub(seg[1], seg[0]))
        dev = _folded_angle(drawn, along)
        offer(PARALLEL, dev, along, e[0], I.NONE)
        offer(PERPENDICULAR, math.pi / 2 - dev, perp(along), e[0], I.NONE)

    considered = []
    for geo_id in q.woken:
        e = _find(entries, geo_id)
        if e:
            consider(e)
            considered.append(geo_id)
    ends, rounds = _anchored(entries, q.anchor)
    for e, _seg in ends:
        if e[0] in considered:
            continue
        consider(e)

    for e, pos, radial, tangent in rounds:
        dev = _folded_angle(drawn, tangent)
        offer(ARC_TANGENT, dev, tangent, e[0], pos, True)
        offer(ARC_RADIAL, math.pi / 2 - dev, radial, e[0], pos, True)

    if guide.valid() and guide.kind in (PARALLEL, PERPENDICULAR):

        # Vertical, not Parallel/Perpendicular, and only in its tighter band (else no snap)
        d = guide.direction
        if abs(d[1]) <= 1e-9 or abs(d[0]) <= 1e-9:
            return Guide()
    return guide if guide.valid() else _angle_step_guide(entries, q, drawn)


def candidate_directions(entries, q):
    """The faint candidate lines through the anchor: axes, along/across lines ending at the
    anchor, tangent/radius of a curve the anchor is on. Each direction once."""
    candidates = []
    if not q.has_anchor or not q.filter.directions:
        return candidates
    drawn = sub(q.cursor, q.anchor)
    drawing = length(drawn) > _tol(length(q.anchor))

    def offer(kind, along, geo_id, pos):
        for c in candidates:
            if abs(cross(c.direction, along)) <= 1e-9:
                return
        candidates.append(Guide(kind, q.anchor, _along_or_against(along, drawn) if drawing else along, geo_id, pos))

    offer(HORIZONTAL, (1.0, 0.0), I.GEO_UNDEF, I.NONE)
    offer(VERTICAL, (0.0, 1.0), I.GEO_UNDEF, I.NONE)
    if not q.filter.parallels:
        return candidates
    ends, rounds = _anchored(entries, q.anchor)
    for e, seg in ends:
        along = unit(sub(seg[1], seg[0]))
        offer(PARALLEL, along, e[0], I.NONE)
        offer(PERPENDICULAR, perp(along), e[0], I.NONE)
    for e, pos, radial, tangent in rounds:
        offer(ARC_TANGENT, tangent, e[0], pos)
        offer(ARC_RADIAL, radial, e[0], pos)
    return candidates


def find_guides(entries, q):
    result = GuideResult(q.cursor)
    if not q.radius > 0.0:
        return result
    direction = find_direction_guide(entries, q)
    crossing_radius = q.radius * SQRT2
    tie = 1e-6 * q.radius

    align_h = [None]
    align_v = [None]
    best = {"level": q.radius, "level_other": math.inf, "plumb": q.radius, "plumb_other": math.inf}

    def consider_point(point, geo_id, pos):
        offset = sub(point, q.cursor)
        if length(offset) <= q.radius:
            return
        if q.has_anchor and same_point(point, q.anchor):
            return
        dx, dy = abs(offset[0]), abs(offset[1])
        if dy <= q.radius and (dy < best["level"] - tie
                               or (abs(dy - best["level"]) <= tie and dx < best["level_other"])):
            best["level"], best["level_other"] = dy, dx
            align_h[0] = Guide(ALIGN_H, point, (1.0, 0.0), geo_id, pos)
        if dx <= q.radius and (dx < best["plumb"] - tie
                               or (abs(dx - best["plumb"]) <= tie and dy < best["plumb_other"])):
            best["plumb"], best["plumb_other"] = dx, dy
            align_v[0] = Guide(ALIGN_V, point, (0.0, 1.0), geo_id, pos)

    if q.filter.alignments:
        if q.include_axes:
            consider_point((0.0, 0.0), I.ROOT, I.START)

        def consider_vertices(e):
            if e[1] is None:
                return
            for pos in I.vertex_positions(e[1]):
                consider_point(I.point_of(e[1], pos), e[0], pos)

        if q.align_all_points:
            for e in entries:
                consider_vertices(e)
        else:
            for geo_id in q.recent:
                e = _find(entries, geo_id)
                if e:
                    consider_vertices(e)
        for geo_id in q.woken:
            e = _find(entries, geo_id)
            if e:
                if not q.align_all_points and geo_id not in q.recent:
                    consider_vertices(e)
                for p in I.virtual_points(e, q.point_filter):
                    consider_point(p.position, geo_id, I.NONE)

    extension = None
    if q.filter.extensions:
        best_d = q.radius
        for geo_id in q.woken:
            e = _find(entries, geo_id)
            seg = _segment(e) if e else None
            if not seg:
                continue
            along = unit(sub(seg[1], seg[0]))
            n = dist(seg[0], seg[1])
            t = dot(sub(q.cursor, seg[0]), along)
            if 0.0 <= t <= n:
                continue
            d = abs(cross(along, sub(q.cursor, seg[0])))
            if d <= best_d:
                best_d = d
                before = t < 0.0
                extension = Guide(EXTENSION, seg[0] if before else seg[1],
                                  mul(along, -1.0) if before else along, geo_id, I.NONE)

    if extension:
        for slot in (align_h, align_v):
            a = slot[0]
            if not a or abs(cross(a.direction, extension.direction)) > 1e-9:
                continue
            offset = abs(cross(extension.direction, sub(a.origin, extension.origin)))
            if offset <= _tol(length(a.origin)):
                slot[0] = None

    ah, av = align_h[0], align_v[0]
    if direction.valid():
        result.guides.append(direction)
        result.position = project_onto(direction, q.cursor)
        best_d = crossing_radius
        for cand in (ah, av, extension):
            if not cand:
                continue
            x = cross_guides(direction, cand)
            if x is None:
                continue
            d = dist(x, q.cursor)
            if d <= best_d:
                best_d = d
                result.position = x
                result.guides = [direction, cand]
                result.crossing = True
        return result

    if ah and av:
        result.position = (av.origin[0], ah.origin[1])
        result.guides = [ah, av]
        result.crossing = True
        return result
    alignment = ah or av
    if alignment and extension:
        x = cross_guides(alignment, extension)
        if x is not None and dist(x, q.cursor) <= crossing_radius:
            result.position = x
            result.guides = [alignment, extension]
            result.crossing = True
            return result
    if alignment:
        result.position = project_onto(alignment, q.cursor)
        result.guides = [alignment]
        return result
    if extension:
        result.position = project_onto(extension, q.cursor)
        result.guides = [extension]
        return result
    return result


def circle_points(anchor, entry):
    """Tangent and normal points of a circle or arc for lines from anchor, inside the arc's range."""
    points = []
    g = entry[1]
    if g is None or type(g) not in (Part.Circle, Part.ArcOfCircle):
        return points
    center, radius = xy(g.Center), g.Radius
    if not radius > 0.0:
        return points
    offset = sub(anchor, center)
    distance = length(offset)
    tol = _tol(radius + distance)

    def on_curve(p):
        away = I.distance_to_curve(entry[0], g, p)
        return 0.0 <= away <= 1e-7 * (1.0 + radius)

    if distance > radius + tol:
        alpha = math.acos(min(max(radius / distance, 0.0), 1.0))
        beta = math.atan2(offset[1], offset[0])
        for a in (beta + alpha, beta - alpha):
            p = add(center, (math.cos(a) * radius, math.sin(a) * radius))
            if on_curve(p):
                points.append(CirclePoint(CirclePoint.TANGENT, p))
    if distance > tol:
        towards = mul(offset, 1.0 / distance)
        for p in (add(center, mul(towards, radius)), sub(center, mul(towards, radius))):
            if on_curve(p):
                points.append(CirclePoint(CirclePoint.NORMAL, p))
    return points
