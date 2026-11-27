
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
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import drawings as D
from . import drawviews as DV
from . import drawsketch as SK
from . import drawsketchedit as SE

EPS = 1e-9


def _d(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def _add(a, b):
    return a[0] + b[0], a[1] + b[1]


def _mul(a, k):
    return a[0] * k, a[1] * k


def _unit(a):
    L = math.hypot(*a)
    return (a[0] / L, a[1] / L) if L > EPS else (0.0, 0.0)


def _perp(a):
    return -a[1], a[0]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


# =========================================================================== entities (pure geometry)
def three_point_corner_rect(a, b, c):
    """A rectangle with side a-b and its far side through c."""
    u = _unit(_sub(b, a))
    if u == (0.0, 0.0):
        return None
    n = _perp(u)
    h = _dot(_sub(c, b), n)
    if abs(h) < EPS:
        return None
    off = _mul(n, h)
    return [a, b, _add(b, off), _add(a, off)]


def three_point_center_rect(c, m, w):
    """A rectangle about centre c: m sets one half side (its direction), w the other."""
    h1 = _sub(m, c)
    if math.hypot(*h1) < EPS:
        return None
    n = _perp(_unit(h1))
    k = _dot(_sub(w, c), n)
    if abs(k) < EPS:
        return None
    h2 = _mul(n, k)
    return [_add(_add(c, h1), h2), _add(_sub(c, h1), h2), _sub(_sub(c, h1), h2), _sub(_add(c, h1), h2)]


def parallelogram(a, b, c):
    if _d(a, b) < EPS or _d(b, c) < EPS:
        return None
    return [a, b, c, _add(a, _sub(c, b))]


def center_slot(c, e, w):
    return SK.slot_points(_sub(_mul(c, 2), e), e, w)


def arc_slot(c, r, a0, a1, w, n=24):
    """A slot along the arc about c of radius r from a0 to a1 (degrees, counterclockwise); w sets its half width."""
    hw = abs(_d(c, w) - r)
    if hw < EPS or hw >= r:
        return None
    pa = (c[0] + r * math.cos(math.radians(a0)), c[1] + r * math.sin(math.radians(a0)))
    pe = (c[0] + r * math.cos(math.radians(a1)), c[1] + r * math.sin(math.radians(a1)))
    outer = SK.arc_points(c, r + hw, a0, a1, n)
    cap_e = SK.arc_points(pe, hw, a1, a1 + 180.0, n // 2)[1:-1]
    inner = list(reversed(SK.arc_points(c, r - hw, a0, a1, n)))
    cap_s = SK.arc_points(pa, hw, a0 + 180.0, a0 + 360.0, n // 2)[1:-1]
    return outer + cap_e + inner + cap_s


def three_point_arc_slot(s, e, m, w):
    hit = SK.three_point_arc(s, e, m)
    if hit is None:
        return None
    c, r, a0, a1 = hit
    return arc_slot(c, r, a0, a1, w)


def centerpoint_arc_slot(c, s, e, w):
    r = _d(c, s)
    if r < EPS:
        return None
    a0 = math.degrees(math.atan2(s[1] - c[1], s[0] - c[0]))
    a1 = math.degrees(math.atan2(e[1] - c[1], e[0] - c[0]))
    return arc_slot(c, r, a0, a1, w)


def partial_ellipse(c, major, start, end, n=48):
    """The ellipse about c (major axis to major, minor through start) from start round to end, counterclockwise."""
    ax = _sub(major, c)
    A = math.hypot(*ax)
    if A < EPS:
        return None
    u = _unit(ax)
    v = _perp(u)
    B = abs(_dot(_sub(start, c), v))
    if B < EPS:
        return None

    def param(q):
        d = _sub(q, c)
        return math.atan2(_dot(d, v) / B, _dot(d, u) / A)
    t0, t1 = param(start), param(end)
    sweep = (t1 - t0) % (2 * math.pi) or 2 * math.pi
    out = []
    for i in range(n + 1):
        t = t0 + sweep * i / n
        out.append((c[0] + A * math.cos(t) * u[0] + B * math.sin(t) * v[0],
                    c[1] + A * math.cos(t) * u[1] + B * math.sin(t) * v[1]))
    return out


def parabola(focus, apex, start, end, n=40):
    ""
    p = _d(focus, apex)
    if p < EPS:
        return None
    u = _unit(_sub(focus, apex))
    w = _perp(u)
    s0, s1 = _dot(_sub(start, apex), w), _dot(_sub(end, apex), w)
    if abs(s1 - s0) < EPS:
        return None
    return [_add(_add(apex, _mul(w, s)), _mul(u, s * s / (4 * p))) for s in
            (s0 + (s1 - s0) * i / n for i in range(n + 1))]


def conic(a, c, b, rho=0.5, n=40):
    ""
    rho = min(max(float(rho), 0.01), 0.99)
    wt = rho / (1.0 - rho)
    out = []
    for i in range(n + 1):
        t = i / n
        k0, k1, k2 = (1 - t) ** 2, 2 * wt * t * (1 - t), t * t
        den = k0 + k1 + k2
        out.append(((k0 * a[0] + k1 * b[0] + k2 * c[0]) / den, (k0 * a[1] + k1 * b[1] + k2 * c[1]) / den))
    return out


def style_spline(ctrl, n=48):
    ""
    if len(ctrl) < 2:
        return None
    m = len(ctrl) - 1
    out = []
    for i in range(n + 1):
        t = i / n
        x = y = 0.0
        for k, q in enumerate(ctrl):
            bern = math.comb(m, k) * (t ** k) * ((1 - t) ** (m - k))
            x += bern * q[0]
            y += bern * q[1]
        out.append((x, y))
    return out


def tangent_arc(s, t, e):
    """The arc that leaves s along direction t and ends at e: an Arc entity's [centre, start, end] (counterclockwise),
    or None when e lies straight ahead."""
    t = _unit(t)
    n = _perp(t)
    d = _sub(e, s)
    den = 2 * _dot(d, n)
    if abs(den) < EPS:
        return None
    k = _dot(d, d) / den
    c = _add(s, _mul(n, k))
    return [c, s, e] if k > 0 else [c, e, s]


def end_direction(kind, pts, g, tol):
    """(end point, direction leaving it) of the entity end nearest g, within tol."""
    ends = []
    if kind in ("Line", "Centerline") and len(pts) >= 2:
        a, b = pts[0], pts[1]
        ends = [(b, _sub(b, a)), (a, _sub(a, b))]
    elif kind == "Polyline" and len(pts) >= 2:
        ends = [(pts[-1], _sub(pts[-1], pts[-2])), (pts[0], _sub(pts[0], pts[1]))]
    elif kind == "Arc" and len(pts) >= 3:
        c, s, e = pts[:3]
        ends = [(e, _perp(_sub(e, c))), (s, _mul(_perp(_sub(s, c)), -1))]
    best = None
    for q, t in ends:
        dd = _d(q, g)
        if dd <= tol and (best is None or dd < best[0]):
            best = (dd, q, t)
    return (best[1], best[2]) if best else (None, None)


# =========================================================================== entity panels
class _MorePoly(SK._PolyPanel):
    CLOSED = True
    KIND = "Ring"


class ThreePointCornerRectPanel(_MorePoly):
    TITLE = "3 Point Corner Rectangle"
    PIXMAP = "Sketcher_CreateRectangle"
    POINTS = 3
    HINT = "Click the first corner, the second corner, then the far side."

    def points(self, pts):
        return three_point_corner_rect(*pts)


class ThreePointCenterRectPanel(_MorePoly):
    TITLE = "3 Point Center Rectangle"
    PIXMAP = "Sketcher_CreateRectangle_Center"
    POINTS = 3
    HINT = "Click the center, the middle of one side, then a corner."

    def points(self, pts):
        return three_point_center_rect(*pts)


class ParallelogramPanel(_MorePoly):
    TITLE = "Parallelogram"
    PIXMAP = "Sketcher_CreateRectangle"
    POINTS = 3
    HINT = "Click the first corner, the second corner, then the third."

    def points(self, pts):
        return parallelogram(*pts)


class CenterSlotPanel(_MorePoly):
    TITLE = "Centerpoint Straight Slot"
    PIXMAP = "Sketcher_CreateSlot"
    POINTS = 3
    HINT = "Click the center, the end of the slot, then its width."

    def points(self, pts):
        return center_slot(*pts)


class ArcSlotPanel(_MorePoly):
    TITLE = "3 Point Arc Slot"
    PIXMAP = "Sketcher_CreateSlot"
    POINTS = 4
    HINT = "Click the start, the end, a point on the arc, then the slot's width."

    def points(self, pts):
        return three_point_arc_slot(*pts)


class CenterArcSlotPanel(_MorePoly):
    TITLE = "Centerpoint Arc Slot"
    PIXMAP = "Sketcher_CreateSlot"
    POINTS = 4
    HINT = "Click the center, the start, the end, then the slot's width."

    def points(self, pts):
        return centerpoint_arc_slot(*pts)


class PartialEllipsePanel(_MorePoly):
    TITLE = "Partial Ellipse"
    PIXMAP = ":/icons/geometry/Sketcher_CreateElliptical_Arc.svg"
    CLOSED = False
    KIND = "Polyline"
    POINTS = 4
    HINT = "Click the center, the end of the major axis, the start of the arc (it sets the minor axis), then its end."

    def points(self, pts):
        return partial_ellipse(*pts)


class ParabolaPanel(_MorePoly):
    TITLE = "Parabola"
    PIXMAP = ":/icons/geometry/Sketcher_CreateParabolic_Arc.svg"
    CLOSED = False
    KIND = "Polyline"
    POINTS = 4
    HINT = "Click the focus, the apex, then the two ends."

    def points(self, pts):
        return parabola(*pts)


class ConicPanel(_MorePoly):
    TITLE = "Conic"
    PIXMAP = ":/icons/geometry/Sketcher_Conics.svg"
    CLOSED = False
    KIND = "Polyline"
    POINTS = 3
    HINT = "Click the start, the end, then the top vertex (the shoulder); Rho sets its shape."

    def build(self):
        super().build()
        box, lay = D._group("Parameters", self.form)
        self.rho = QtWidgets.QDoubleSpinBox(box)
        self.rho.setObjectName("SWSketchConicRho")
        self.rho.setRange(0.01, 0.99)
        self.rho.setDecimals(3)
        self.rho.setSingleStep(0.05)
        self.rho.setValue(0.5)
        self.rho.setPrefix("Rho: ")
        lay.addWidget(self.rho)

    def points(self, pts):
        a, c, b = pts
        return conic(a, c, b, self.rho.value())


class StyleSplinePanel(_MorePoly):
    TITLE = "Style Spline"
    PIXMAP = "Sketcher_CreateBSpline"
    CLOSED = False
    KIND = "Polyline"
    POINTS = 0
    HINT = "Click the control points, then OK."

    def points(self, pts):
        return style_spline(pts)


class TangentArcPanel(SK._SketchPanel):
    TITLE = "Tangent Arc"
    PIXMAP = "Sketcher_CreateArc"
    POINTS = 2
    HINT = "Click the end of a line or arc in a view, then where the arc ends."

    def sheet_click(self, p):
        if not self.pts:
            v, i, g = SE.pick(self.page, p, ("Line", "Centerline", "Polyline", "Arc"))
            if v is None:
                self.say(self.HINT)
                return True
            kind, _t, pts = SK.entities(v)[i]
            q, t = end_direction(kind, pts, g, max(SE.PICK_MM * 2, 3.0) / max(DV.view_scale(v), 1e-9))
            if q is None:
                self.say("Click nearer the end of the line or arc.")
                return True
            self.view, self.start, self.tdir = v, q, t
            self.pts = [p]
            self.say("Click where the arc ends.")
            return True
        e = DV.to_geometry(self.view, p)
        arc = tangent_arc(self.start, self.tdir, e)
        if arc is not None:
            SE.add(self.view, "Arc", arc)
        else:
            SE.add(self.view, "Line", [self.start, e])
        self.pts = []
        self.view = None
        self.doc.recompute()
        self.say(self.HINT + " OK when done.")
        return True

    def make(self, pts):
        pass


# =========================================================================== tools
def split_at(kind, pts, g):
    """[(kind, points)] of the entity split at its point nearest g (lines, polylines and arcs)."""
    if kind in ("Line", "Centerline"):
        a, b = pts[:2]
        ab = _sub(b, a)
        L2 = _dot(ab, ab)
        if L2 < EPS:
            return None
        t = min(max(_dot(_sub(g, a), ab) / L2, 0.0), 1.0)
        if t < 1e-6 or t > 1 - 1e-6:
            return None
        m = _add(a, _mul(ab, t))
        return [(kind, [a, m]), (kind, [m, b])]
    if kind == "Arc":
        c, s, e = pts[:3]
        r = _d(c, s)
        ang = math.atan2(g[1] - c[1], g[0] - c[0])
        m = (c[0] + r * math.cos(ang), c[1] + r * math.sin(ang))
        return [("Arc", [c, s, m]), ("Arc", [c, m, e])]
    if kind == "Polyline" and len(pts) >= 2:
        best = None
        for k in range(len(pts) - 1):
            a, b = pts[k], pts[k + 1]
            ab = _sub(b, a)
            L2 = _dot(ab, ab) or EPS
            t = min(max(_dot(_sub(g, a), ab) / L2, 0.0), 1.0)
            q = _add(a, _mul(ab, t))
            dd = _d(q, g)
            if best is None or dd < best[0]:
                best = (dd, k, q)
        _dd, k, q = best
        first, second = list(pts[:k + 1]) + [q], [q] + list(pts[k + 1:])
        if len(first) < 2 or len(second) < 2:
            return None
        return [("Polyline", first), ("Polyline", second)]
    return None


def extend_end(view, index, g):
    """The line (or polyline) entity index made longer at its end nearest g, to the first entity it meets."""
    kind, _t, pts = SK.entities(view)[index]
    if kind not in ("Line", "Centerline", "Polyline") or len(pts) < 2:
        return None
    at_end = _d(g, pts[-1]) <= _d(g, pts[0])
    q, prev = (pts[-1], pts[-2]) if at_end else (pts[0], pts[1])
    u = _unit(_sub(q, prev))
    far = _add(q, _mul(u, 1e4))
    best = None
    for pr in SE.others_of(view, index):
        for t in SE._line_hits(q, far, pr):
            dist = t * 1e4
            if dist > 1e-6 and (best is None or dist < best):
                best = dist
    if best is None:
        return None
    new = _add(q, _mul(u, best))
    out = list(pts)
    if at_end:
        out[-1] = new
    else:
        out[0] = new
    return SE.replace(view, index, [(kind, out)])


def jog(a, b, p1, p2):
    """A line a-b with a rectangular jog: from its point nearest p1 along to the point nearest p2, out by p2's
    offset from the line."""
    ab = _sub(b, a)
    L2 = _dot(ab, ab)
    if L2 < EPS:
        return None
    u = _unit(ab)
    n = _perp(u)
    t1 = min(max(_dot(_sub(p1, a), ab) / L2, 0.0), 1.0)
    t2 = min(max(_dot(_sub(p2, a), ab) / L2, 0.0), 1.0)
    if t2 < t1:
        t1, t2 = t2, t1
    h = _dot(_sub(p2, a), n)
    if abs(h) < EPS or t2 - t1 < 1e-6:
        return None
    q1, q2 = _add(a, _mul(ab, t1)), _add(a, _mul(ab, t2))
    off = _mul(n, h)
    return [a, q1, _add(q1, off), _add(q2, off), q2, b]


def segment_points(kind, pts, count):
    """Points dividing a line or arc into count equal pieces (ends included)."""
    if kind in ("Line", "Centerline"):
        a, b = pts[:2]
        return [_add(a, _mul(_sub(b, a), i / count)) for i in range(count + 1)]
    if kind == "Arc":
        c, s, e = pts[:3]
        r = _d(c, s)
        a0 = math.degrees(math.atan2(s[1] - c[1], s[0] - c[0]))
        a1 = math.degrees(math.atan2(e[1] - c[1], e[0] - c[0]))
        return SK.arc_points(c, r, a0, a1, count)
    if kind == "Circle":
        c, e = pts[:2]
        r = _d(c, e)
        a0 = math.degrees(math.atan2(e[1] - c[1], e[0] - c[0]))
        return SK.arc_points(c, r, a0, a0 + 360.0, count)[:-1]
    return None


def stretched(pts, box, delta):
    x0, y0, x1, y1 = box
    return [(_add(q, delta) if x0 <= q[0] <= x1 and y0 <= q[1] <= y1 else q) for q in pts]


def polygon_of(pts):
    """(centre, first vertex, sides) of a Polygon entity."""
    n = len(pts)
    c = (sum(q[0] for q in pts) / n, sum(q[1] for q in pts) / n)
    return c, pts[0], n


def insert_point(pts, g):
    """A spline's points with g put in where it adds the least length."""
    best = None
    for k in range(len(pts) - 1):
        extra = _d(pts[k], g) + _d(g, pts[k + 1]) - _d(pts[k], pts[k + 1])
        if best is None or extra < best[0]:
            best = (extra, k)
    if best is None:
        return None
    k = best[1]
    return list(pts[:k + 1]) + [g] + list(pts[k + 1:])


def section_properties(poly):
    """(area, perimeter, centroid) of a closed outline."""
    n = len(poly)
    A = cx = cy = 0.0
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        cr = x0 * y1 - x1 * y0
        A += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
    A /= 2.0
    if abs(A) < EPS:
        return None
    per = sum(_d(poly[i], poly[(i + 1) % n]) for i in range(n))
    return abs(A), per, (cx / (6 * A), cy / (6 * A))


def equal_groups(view, tol=1e-3):
    """Scan Equal: [(what, value, [indices])] of the sketch's lines of one length and circles/arcs of one radius."""
    lengths, radii = {}, {}
    for i, (k, _t, p) in enumerate(SK.entities(view)):
        if k in ("Line", "Centerline") and len(p) >= 2:
            lengths.setdefault(round(_d(p[0], p[1]) / tol) * tol, []).append(i)
        elif k in ("Circle", "Arc") and len(p) >= 2:
            radii.setdefault(round(_d(p[0], p[1]) / tol) * tol, []).append(i)
    out = [("Length", v, ix) for v, ix in sorted(lengths.items()) if len(ix) > 1]
    out += [("Radius", v, ix) for v, ix in sorted(radii.items()) if len(ix) > 1]
    return out


def constrain_all(view, tol=0.5):
    """Constrain All: sketch end points within tol (model mm) of a view vertex or another sketch point are joined
    to it exactly. Returns how many points moved."""
    targets = []
    try:
        k = DV.view_scale(view)
        for vx in view.getVisibleVertexes() if hasattr(view, "getVisibleVertexes") else []:
            targets.append((vx.Point.x / k, vx.Point.y / k))
    except Exception as _fw_err:
        _fw_log("drawsketchmore.py:567", _fw_err)
    ents = SK.entities(view)
    moved = 0
    news = []
    for i, (kind, _t, pts) in enumerate(ents):
        if kind not in ("Line", "Centerline", "Polyline"):
            for q in pts:
                targets.append(q)
            continue
        new = list(pts)
        for j in (0, len(pts) - 1):
            q = pts[j]
            near = [t for t in targets if EPS < _d(t, q) <= tol]
            if near:
                new[j] = min(near, key=lambda t: _d(t, q))
                moved += 1
        for q in new:
            targets.append(q)
        if new != list(pts):
            news.append((i, kind, new))
    for i, kind, new in sorted(news, reverse=True):
        SE.replace(view, i, [(kind, new)])
    return moved


class _PickPanel(SE._EditPanel):
    """Click a sketch entity; the tool does its work on it."""
    KINDS = None

    def sheet_click(self, p):
        v, i, g = SE.pick(self.page, p, self.KINDS)
        if v is None:
            self.say(self.HINT)
            return True
        self.act(v, i, g, p)
        self.doc.recompute()
        return True

    def act(self, v, i, g, p):
        raise NotImplementedError


class SegmentPanel(_PickPanel):
    TITLE = "Segment"
    PIXMAP = "Sketcher_Split"
    HINT = "Set the number of instances, then click a line, arc or circle."
    KINDS = ("Line", "Centerline", "Arc", "Circle")

    def parameters(self):
        box, lay = D._group("Parameters", self.form)
        self.points_on = QtWidgets.QRadioButton("Sketch points", box)
        self.points_on.setObjectName("SWSegmentPoints")
        self.points_on.setChecked(True)
        self.segments_on = QtWidgets.QRadioButton("Sketch segments", box)
        self.segments_on.setObjectName("SWSegmentSegments")
        self.count = QtWidgets.QSpinBox(box)
        self.count.setObjectName("SWSegmentCount")
        self.count.setRange(2, 200)
        self.count.setValue(2)
        for w in (self.points_on, self.segments_on, self.count):
            lay.addWidget(w)
        self.lay.addWidget(box)

    def act(self, v, i, g, p):
        kind, _t, pts = SK.entities(v)[i]
        div = segment_points(kind, pts, self.count.value())
        if not div:
            return
        if self.segments_on.isChecked() and kind in ("Line", "Centerline"):
            SE.replace(v, i, [(kind, [div[k], div[k + 1]]) for k in range(len(div) - 1)])
        elif self.segments_on.isChecked() and kind == "Arc":
            c = pts[0]
            SE.replace(v, i, [("Arc", [c, div[k], div[k + 1]]) for k in range(len(div) - 1)])
        else:
            inner = div if kind == "Circle" else div[1:-1]
            for q in inner:
                SE.add(v, "Point", [q])


class ExtendPanel(_PickPanel):
    TITLE = "Extend Entities"
    PIXMAP = "Sketcher_Extend"
    HINT = "Click a line near the end to extend; it runs on to the next entity."
    KINDS = ("Line", "Centerline", "Polyline")

    def act(self, v, i, g, p):
        if extend_end(v, i, g) is None:
            self.say("Nothing to extend to in that direction.")
        else:
            self.say(self.HINT)


class SplitPanel(_PickPanel):
    TITLE = "Split Entities"
    PIXMAP = "Sketcher_Split"
    HINT = "Click a line, arc or curve where it is to be split."
    KINDS = ("Line", "Centerline", "Arc", "Polyline")

    def act(self, v, i, g, p):
        kind, _t, pts = SK.entities(v)[i]
        parts = split_at(kind, pts, g)
        if parts:
            SE.replace(v, i, parts)
            SE.add(v, "Point", [parts[0][1][-1]])


class JogLinePanel(SE._EditPanel):
    TITLE = "Jog Line"
    PIXMAP = "Sketcher_CreatePolyline"
    HINT = "Click the line where the jog starts, then where it ends and how far it steps out."

    def build(self):
        super().build()
        self.first = None

    def sheet_click(self, p):
        if self.first is None:
            v, i, g = SE.pick(self.page, p, ("Line", "Centerline"))
            if v is None:
                self.say(self.HINT)
                return True
            self.first = (v, SE._ekey(SK.entities(v)[i]), g)
            self.say("Click where the jog ends; the distance off the line is its depth.")
            return True
        v, key, g1 = self.first
        self.first = None
        i = self.index(v, key)
        if i is None:
            return True
        kind, _t, (a, b) = SK.entities(v)[i][0], None, SK.entities(v)[i][2][:2]
        pts = jog(a, b, g1, DV.to_geometry(v, p))
        if pts:
            SE.replace(v, i, [(kind, [pts[k], pts[k + 1]]) for k in range(len(pts) - 1)])
            self.doc.recompute()
        self.say(self.HINT)
        return True


class StretchPanel(SE._EditPanel):
    TITLE = "Stretch Entities"
    PIXMAP = "Sketcher_Move"
    HINT = "Click two corners round the points to stretch, then the base point, then where it goes."

    def build(self):
        super().build()
        self.clicks_ = []

    def sheet_click(self, p):
        self.clicks_.append(p)
        steps = ("Click the opposite corner.", "Click the base point.", "Click where the base point goes.")
        if len(self.clicks_) < 4:
            self.say(steps[len(self.clicks_) - 1])
            return True
        c0, c1, base, dest = self.clicks_
        self.clicks_ = []
        v = DV.focus_view(self.page, c0, margin=0.0) or DV.focus_view(self.page, base, margin=0.0)
        if v is None:
            self.say(self.HINT)
            return True
        g0, g1 = DV.to_geometry(v, c0), DV.to_geometry(v, c1)
        box = (min(g0[0], g1[0]), min(g0[1], g1[1]), max(g0[0], g1[0]), max(g0[1], g1[1]))
        delta = _sub(DV.to_geometry(v, dest), DV.to_geometry(v, base))
        ents = SK.entities(v)
        picked = [i for vv, i in self.picks() if vv is v] or list(range(len(ents)))
        news = []
        for i in picked:
            kind, _t, pts = ents[i]
            new = stretched(pts, box, delta)
            if new != list(pts):
                news.append((i, kind, new))
        for i, kind, new in sorted(news, reverse=True):
            SE.replace(v, i, [(kind, new)])
        self.doc.recompute()
        self.say("%d entities stretched. %s" % (len(news), self.HINT))
        return True


class EditPolygonPanel(_PickPanel):
    TITLE = "Polygon"
    PIXMAP = "Sketcher_CreateHexagon"
    HINT = "Click the polygon to edit, set its sides, then OK."
    KINDS = ("Polygon",)

    def parameters(self):
        box, lay = D._group("Parameters", self.form)
        self.sides = QtWidgets.QSpinBox(box)
        self.sides.setObjectName("SWEditPolygonSides")
        self.sides.setRange(3, 40)
        self.sides.setValue(6)
        lay.addWidget(self.sides)
        self.lay.addWidget(box)
        self.target = None

    def act(self, v, i, g, p):
        self.target = (v, SE._ekey(SK.entities(v)[i]))
        self.sides.setValue(len(SK.entities(v)[i][2]))
        self.say("Set the number of sides, then OK.")

    def finish(self):
        if self.target is None:
            return
        v, key = self.target
        i = self.index(v, key)
        if i is None:
            return
        c, first, _n = polygon_of(SK.entities(v)[i][2])
        SE.replace(v, i, [("Polygon", SK.polygon_points(c, first, self.sides.value()))])
        self.doc.recompute()


class InsertSplinePointPanel(_PickPanel):
    TITLE = "Insert Spline Point"
    PIXMAP = ":/icons/splines/Sketcher_BSplineInsertKnot.svg"
    HINT = "Click on a spline where the new point goes."
    KINDS = ("Spline",)

    def act(self, v, i, g, p):
        kind, _t, pts = SK.entities(v)[i]
        new = insert_point(pts, g)
        if new:
            SE.replace(v, i, [(kind, new)])


# =========================================================================== commands that act at once
DYNAMIC = {}        # view name -> (a, b) mirror line of Dynamic Mirror
_IN_MIRROR = [False]


def _record_with_mirror(view, kind, tags, pts):
    _ORIG_RECORD[0](view, kind, tags, pts)
    axis = DYNAMIC.get(getattr(view, "Name", ""))
    if axis is None or _IN_MIRROR[0]:
        return
    _IN_MIRROR[0] = True
    try:
        SE.add(view, kind, SE.mirrored(kind, list(pts), axis[0], axis[1]))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Dynamic Mirror: %s\n" % error)
    finally:
        _IN_MIRROR[0] = False


_ORIG_RECORD = [None]


def dynamic_mirror():
    """Dynamic Mirror: on with a centerline (or line) picked, everything sketched in its view after is mirrored
    about it; pressed again it goes off."""
    if DYNAMIC:
        DYNAMIC.clear()
        _status("Dynamic Mirror off.")
        return False
    for v, i in SE.selected():
        kind, _t, pts = SK.entities(v)[i]
        if kind in ("Line", "Centerline"):
            DYNAMIC[v.Name] = (pts[0], pts[1])
            _status("Dynamic Mirror: what you sketch in %s is mirrored about the line." % v.Label)
            return True
    _status("Dynamic Mirror: pick a centerline first.")
    return False


def construction_geometry():
    """Construction Geometry: the picked lines become centerlines (and back)."""
    n = 0
    for v, i in sorted(SE.selected(), key=lambda x: -x[1]):
        kind, _t, pts = SK.entities(v)[i]
        if kind in ("Line", "Centerline"):
            SE.replace(v, i, [("Centerline" if kind == "Line" else "Line", pts)])
            n += 1
    return n


def dissolve():
    """Dissolve: a picked rectangle, polygon, slot or other closed outline becomes its lines."""
    n = 0
    for v, i in sorted(SE.selected(), key=lambda x: -x[1]):
        if SK.entities(v)[i][0] in SE.RING_KINDS:
            SE.explode(v, i)
            n += 1
    return n


def make_path():
    """Make Path: the picked entities kept together as one path (listed with the view)."""
    picks = SE.selected()
    if not picks:
        return 0
    by_view = {}
    for v, i in picks:
        by_view.setdefault(v, []).append(SE._ekey(SK.entities(v)[i]))
    for v, keys in by_view.items():
        if "SWSketchPaths" not in v.PropertiesList:
            v.addProperty("App::PropertyStringList", "SWSketchPaths", "FreeCAD", "Make Path: entity keys per path")
        v.SWSketchPaths = list(v.SWSketchPaths) + ["|".join(str(k) for k in keys)]
    return len(picks)


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 8000)
    except Exception as _fw_err:
        _fw_log("drawsketchmore.py:869", _fw_err)


def _focus_or_sketch_view(page):
    picks = SE.selected()
    if picks:
        return picks[0][0], picks
    vs = SE.views_with_sketch(page)
    return (vs[0] if vs else None), []


def scan_equal(page):
    """Scan Equal: a box listing the lines of equal length and the circles and arcs of equal radius; Set Equal
    adds the Equal relation to the group."""
    v, _p = _focus_or_sketch_view(page)
    if v is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Equal Relations", "The drawing sketch has no entities.")
        return None
    groups = equal_groups(v)
    box = QtWidgets.QDialog(Gui.getMainWindow())
    box.setObjectName("SWScanEqual")
    box.setWindowTitle("Equal Relations")
    lay = QtWidgets.QVBoxLayout(box)
    lst = QtWidgets.QListWidget(box)
    lst.setObjectName("SWScanEqualList")
    for what, val, ix in groups:
        lst.addItem("%s %.4g: %s" % (what, val, ", ".join("%s%d" % (SK.entities(v)[i][0], i + 1) for i in ix)))
    if not groups:
        lst.addItem("No equal entities found.")
    lay.addWidget(lst)
    row = QtWidgets.QHBoxLayout()
    seteq = QtWidgets.QPushButton("Set Equal", box)
    seteq.setObjectName("SWScanEqualSet")
    close = QtWidgets.QPushButton("Close", box)
    row.addWidget(seteq)
    row.addStretch(1)
    row.addWidget(close)
    lay.addLayout(row)

    def do_set():
        r = lst.currentRow()
        if 0 <= r < len(groups):
            doc = v.Document
            doc.openTransaction("Set Equal")
            try:
                try:
                    SE.add_relation(v, "Equal", groups[r][2])
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: Scan Equal: %s\n" % error)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            doc.recompute()
    seteq.clicked.connect(do_set)
    close.clicked.connect(box.accept)
    box.groups = groups
    box.show()
    return box


def show_section_properties(page):
    ""

    v, picks = _focus_or_sketch_view(page)
    poly = None
    if picks:
        kind, _t, pts = SK.entities(v)[picks[0][1]]
        poly = SK.profile_points(kind, pts)
    if poly is None and v is not None:
        hit = SK.closed_profile(v)
        poly = hit[1] if hit else None
    if poly is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Section Properties",
                                          "Select a closed sketch outline (a rectangle, circle, polygon ...) in a view.")
        return None
    area, per, (cx, cy) = section_properties(poly)
    text = ("Area = %.3f mm^2\nPerimeter = %.3f mm\nCentroid relative to the view's origin:\n  X = %.3f mm\n  Y = %.3f mm"
            % (area, per, cx, cy))
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, "Section Properties", text,
                                QtWidgets.QMessageBox.Close, Gui.getMainWindow())
    box.setObjectName("SWSectionProperties")
    box.result_values = (area, per, (cx, cy))
    box.show()
    return box


COMMANDS = {
    "FreeWorks_DrawSketch3PointCornerRect": ("3 Point Corner Rectangle", "Sketcher_CreateRectangle",
                                             "Sketches a rectangle at an angle from three points."),
    "FreeWorks_DrawSketch3PointCenterRect": ("3 Point Center Rectangle", "Sketcher_CreateRectangle_Center",
                                             "Sketches a rectangle at an angle about its center."),
    "FreeWorks_DrawSketchParallelogram": ("Parallelogram", "Sketcher_CreateRectangle", "Sketches a parallelogram."),
    "FreeWorks_DrawSketchCenterSlot": ("Centerpoint Straight Slot", "Sketcher_CreateSlot",
                                       "Sketches a straight slot from its center."),
    "FreeWorks_DrawSketchArcSlot": ("3 Point Arc Slot", "Sketcher_CreateSlot", "Sketches a slot along a 3 point arc."),
    "FreeWorks_DrawSketchCenterArcSlot": ("Centerpoint Arc Slot", "Sketcher_CreateSlot",
                                          "Sketches a slot along an arc about its center."),
    "FreeWorks_DrawSketchTangentArc": ("Tangent Arc", "Sketcher_CreateArc", "Sketches an arc on from the end of a line or arc."),
    "FreeWorks_DrawSketchPartialEllipse": ("Partial Ellipse", ":/icons/geometry/Sketcher_CreateElliptical_Arc.svg", "Sketches part of an ellipse."),
    "FreeWorks_DrawSketchParabola": ("Parabola", ":/icons/geometry/Sketcher_CreateParabolic_Arc.svg", "Sketches a parabola."),
    "FreeWorks_DrawSketchConic": ("Conic", ":/icons/geometry/Sketcher_Conics.svg", "Sketches a conic with its Rho."),
    "FreeWorks_DrawSketchStyleSpline": ("Style Spline", "Sketcher_CreateBSpline", "Sketches a spline on control points."),
    "FreeWorks_DrawSegment": ("Segment", "Sketcher_Split", "Divides an entity into equal pieces or points."),
    "FreeWorks_DrawExtend": ("Extend Entities", "Sketcher_Extend", "Extends a line to the next entity."),
    "FreeWorks_DrawSplitEntities": ("Split Entities", "Sketcher_Split", "Splits an entity in two where you click."),
    "FreeWorks_DrawJogLine": ("Jog Line", "Sketcher_CreatePolyline", "Puts a rectangular jog into a line."),
    "FreeWorks_DrawConstructionGeometry": ("Construction Geometry", "Sketcher_ToggleConstruction",
                                           "Turns the picked lines into construction lines (centerlines), and back."),
    "FreeWorks_DrawMakePath": ("Make Path", "Sketcher_CreatePolyline", "Keeps the picked entities together as a path."),
    "FreeWorks_DrawDissolve": ("Dissolve", "Sketcher_Split", "Breaks a picked closed outline into its lines."),
    "FreeWorks_DrawDynamicMirror": ("Dynamic Mirror", "Sketcher_Symmetry",
                                    "Mirrors what you sketch about the picked centerline, as you sketch it."),
    "FreeWorks_DrawStretchEntities": ("Stretch Entities", "Sketcher_Move", "Stretches the entities' points in a box."),
    "FreeWorks_DrawEditPolygon": ("Edit Polygon", "Sketcher_CreateHexagon", "Changes a polygon's number of sides."),
    "FreeWorks_DrawInsertSplinePoint": ("Insert Spline Point", ":/icons/splines/Sketcher_BSplineInsertKnot.svg",
                                        "Adds a point to a spline where you click."),
    "FreeWorks_DrawScanEqual": ("Scan Equal", "Constraint_EqualLength",
                                "Finds the lines of equal length and the arcs of equal radius."),
    "FreeWorks_DrawConstrainAll": ("Constrain All", "Constraint_PointOnPoint",
                                   "Joins the sketch's end points to the view's vertices and to each other."),
    "FreeWorks_DrawSectionProperties": ("Section Properties", ":/icons/Measurement-Area.svg",
                                        "Area, perimeter and centroid of a closed sketch outline."),
}
PANELS = {"FreeWorks_DrawSketch3PointCornerRect": ThreePointCornerRectPanel,
          "FreeWorks_DrawSketch3PointCenterRect": ThreePointCenterRectPanel,
          "FreeWorks_DrawSketchParallelogram": ParallelogramPanel, "FreeWorks_DrawSketchCenterSlot": CenterSlotPanel,
          "FreeWorks_DrawSketchArcSlot": ArcSlotPanel, "FreeWorks_DrawSketchCenterArcSlot": CenterArcSlotPanel,
          "FreeWorks_DrawSketchTangentArc": TangentArcPanel, "FreeWorks_DrawSketchPartialEllipse": PartialEllipsePanel,
          "FreeWorks_DrawSketchParabola": ParabolaPanel, "FreeWorks_DrawSketchConic": ConicPanel,
          "FreeWorks_DrawSketchStyleSpline": StyleSplinePanel, "FreeWorks_DrawSegment": SegmentPanel,
          "FreeWorks_DrawExtend": ExtendPanel, "FreeWorks_DrawSplitEntities": SplitPanel,
          "FreeWorks_DrawJogLine": JogLinePanel, "FreeWorks_DrawStretchEntities": StretchPanel,
          "FreeWorks_DrawEditPolygon": EditPolygonPanel, "FreeWorks_DrawInsertSplinePoint": InsertSplinePointPanel}
NEEDS_PICK = ("FreeWorks_DrawConstructionGeometry", "FreeWorks_DrawMakePath", "FreeWorks_DrawDissolve")
NEEDS_SKETCH = ("FreeWorks_DrawSegment", "FreeWorks_DrawExtend", "FreeWorks_DrawSplitEntities",
                "FreeWorks_DrawJogLine", "FreeWorks_DrawStretchEntities", "FreeWorks_DrawEditPolygon",
                "FreeWorks_DrawInsertSplinePoint", "FreeWorks_DrawScanEqual", "FreeWorks_DrawConstrainAll",
                "FreeWorks_DrawSketchTangentArc")
# Section Properties is never greyed on a sheet (NO DEAD CONTROLS, View/display 11-27: Tools > Evaluate >
# Section Properties... sat greyed): with no closed outline to measure it says what to pick


class _Command(SK._Command):
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        r = SK._Command.GetResources(self)
        if self.name == "FreeWorks_DrawDynamicMirror":
            r["Checkable"] = True
        return r

    def IsActive(self):
        page = D.active_page()
        if page is None or not D.sheet_shown(page):
            return SK._Command.IsActive(self)
        if D.busy():
            return False
        if self.name in NEEDS_PICK:
            return bool(SE.selected())
        if self.name == "FreeWorks_DrawDynamicMirror":
            return bool(DYNAMIC) or bool(SE.selected())
        if self.name in NEEDS_SKETCH:
            return bool(SE.views_with_sketch(page))
        return True

    def Activated(self, *args):
        page = D.active_page()
        if page is None or not D.sheet_shown(page):
            twin = self.part_twin()
            if twin is not None:
                Gui.runCommand(twin, 0)
            return
        doc = page.Document
        n = self.name
        if n in PANELS:
            D._show(PANELS[n](page))
            return
        if n == "FreeWorks_DrawDynamicMirror":
            dynamic_mirror()
            return
        if n == "FreeWorks_DrawScanEqual":
            scan_equal(page)
            return
        if n == "FreeWorks_DrawSectionProperties":
            show_section_properties(page)
            return
        doc.openTransaction(self.text)
        try:
            if n == "FreeWorks_DrawConstructionGeometry":
                construction_geometry()
            elif n == "FreeWorks_DrawMakePath":
                k = make_path()
                _status("Make Path: %d entities in the path." % k)
            elif n == "FreeWorks_DrawDissolve":
                dissolve()
            elif n == "FreeWorks_DrawConstrainAll":
                views = [v for v, _i in SE.selected()] or SE.views_with_sketch(page)
                k = sum(constrain_all(v) for v in dict.fromkeys(views))
                _status("Constrain All: %d points joined." % k)
        finally:
            doc.commitTransaction()
        doc.recompute()
        Gui.Selection.clearSelection()


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    if _ORIG_RECORD[0] is None:
        _ORIG_RECORD[0] = SK._record
        SK._record = _record_with_mirror
