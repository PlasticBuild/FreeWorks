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
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from .vec import sub, add, mul, length, dot
from .toolbase import SketchTool, GENERAL_GROUP, param_bool, edited_sketch, other_buttons
from . import toolbase as TB

EPS = 1e-7
TWO_PI = 2.0 * math.pi
TRIMMABLE = ("Part::GeomLineSegment", "Part::GeomArcOfCircle", "Part::GeomCircle", "Part::GeomEllipse",
             "Part::GeomArcOfEllipse", "Part::GeomBSplineCurve", "Part::GeomArcOfHyperbola", "Part::GeomArcOfParabola")
KEEPABLE = ("Part::GeomLineSegment", "Part::GeomArcOfCircle", "Part::GeomCircle")


def keep_as_construction():
    return param_bool(GENERAL_GROUP, "TrimKeepAsConstruction", False)


def ignore_construction():
    return param_bool(GENERAL_GROUP, "TrimIgnoreConstruction", False)


def V(p):
    return App.Vector(p[0], p[1], 0)


def pt(v):
    return (v.x, v.y)


# --- parameters along a curve -------------------------------------------------------------------
def ccw(a, b):
    """Counter-clockwise sweep from angle a to angle b, in [0, 2 pi)."""
    d = math.fmod(b - a, TWO_PI)
    return d + TWO_PI if d < 0 else d


def param_of(geo, p):
    """Where p lies along geo: a line's 0..1 from start to end, a circle's angle, an arc's sweep from
    its start (0..its angle). None for other curves."""
    t = geo.TypeId
    if t == "Part::GeomLineSegment":
        a, b = pt(geo.StartPoint), pt(geo.EndPoint)
        d = sub(b, a)
        l2 = dot(d, d)
        return dot(sub(p, a), d) / l2 if l2 > EPS else 0.0
    if t == "Part::GeomCircle":
        c = pt(geo.Center)
        return math.atan2(p[1] - c[1], p[0] - c[0]) % TWO_PI
    if t == "Part::GeomArcOfCircle":
        c = pt(geo.Center)
        return ccw(geo.FirstParameter, math.atan2(p[1] - c[1], p[0] - c[0]))
    return None


def param_range(geo):
    t = geo.TypeId
    if t == "Part::GeomLineSegment":
        return 0.0, 1.0
    if t == "Part::GeomCircle":
        return 0.0, TWO_PI
    if t == "Part::GeomArcOfCircle":
        return 0.0, ccw(geo.FirstParameter, geo.LastParameter)
    return None


def point_at(geo, u):
    t = geo.TypeId
    if t == "Part::GeomLineSegment":
        a, b = pt(geo.StartPoint), pt(geo.EndPoint)
        return add(a, mul(sub(b, a), u))
    c, r = pt(geo.Center), geo.Radius
    angle = u if t == "Part::GeomCircle" else geo.FirstParameter + u
    return (c[0] + r * math.cos(angle), c[1] + r * math.sin(angle))


def same_curve(a, b):
    """b lies on a's curve (a collinear segment, or an arc of the same circle)."""
    if a.TypeId == "Part::GeomLineSegment":
        if b.TypeId != "Part::GeomLineSegment":
            return False
        d = sub(pt(a.EndPoint), pt(a.StartPoint))
        l = length(d)
        if l < EPS:
            return False
        n = (-d[1] / l, d[0] / l)
        return all(abs(dot(sub(pt(q), pt(a.StartPoint)), n)) < 1e-6 for q in (b.StartPoint, b.EndPoint))
    if a.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle"):
        return b.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle") and \
            length(sub(pt(a.Center), pt(b.Center))) < 1e-6 and abs(a.Radius - b.Radius) < 1e-6
    return False


def curve_key(g):
    """Identifies a piece by its ends (a circle by its centre and radius)."""
    if g.TypeId == "Part::GeomCircle":
        return ("circle", round(g.Center.x, 5), round(g.Center.y, 5), round(g.Radius, 5))
    return (round(g.StartPoint.x, 5), round(g.StartPoint.y, 5), round(g.EndPoint.x, 5), round(g.EndPoint.y, 5))


def covered_range(original, piece):
    """The parameter interval of original that piece covers, in original's parameters."""
    if original.TypeId == "Part::GeomLineSegment":
        u = sorted((param_of(original, pt(piece.StartPoint)), param_of(original, pt(piece.EndPoint))))
        return (max(0.0, u[0]), min(1.0, u[1]))
    if piece.TypeId == "Part::GeomCircle":
        return param_range(original)
    # an arc of the same circle: its counter-clockwise sweep in the original's parameter
    if original.TypeId == "Part::GeomCircle":
        a0 = piece.FirstParameter % TWO_PI
        return (a0, a0 + ccw(piece.FirstParameter, piece.LastParameter))
    a0 = ccw(original.FirstParameter, piece.FirstParameter)
    return (a0, a0 + ccw(piece.FirstParameter, piece.LastParameter))


def complement(total, intervals, periodic):
    """What is left of total once intervals are taken out; on a periodic range intervals may wrap."""
    lo, hi = total
    cuts = []
    for a, b in intervals:
        if periodic:
            a %= hi
            b = a + (b - a)
            if b > hi:
                cuts.append((a, hi))
                cuts.append((0.0, b - hi))
                continue
        cuts.append((max(lo, a), min(hi, b)))
    cuts.sort()
    out = []
    at = lo
    for a, b in cuts:
        if a - at > 1e-6:
            out.append((at, a))
        at = max(at, b)
    if hi - at > 1e-6:
        out.append((at, hi))
    return out


def removed_pieces(original, remaining):
    """The parts of original (a line, circle or arc) that the curves in remaining do not cover, as
    new construction-ready geometry (makeTrimmedPiece of package 31, worked out from the result)."""
    if original.TypeId not in KEEPABLE:
        return []
    total = param_range(original)
    on_curve = [g for g in remaining if same_curve(original, g)]
    if any(g.TypeId == "Part::GeomCircle" for g in on_curve):
        return []
    periodic = original.TypeId == "Part::GeomCircle"
    gaps = complement(total, [covered_range(original, g) for g in on_curve], periodic)
    if periodic and not on_curve:
        return [Part.Circle(original.Center, App.Vector(0, 0, 1), original.Radius)]
    out = []
    for a, b in gaps:
        if original.TypeId == "Part::GeomLineSegment":
            p, q = point_at(original, a), point_at(original, b)
            if length(sub(q, p)) > 1e-6:
                out.append(Part.LineSegment(V(p), V(q)))
        else:
            if b - a < 1e-6:
                continue
            start = a if periodic else original.FirstParameter + a
            circle = Part.Circle(original.Center, App.Vector(0, 0, 1), original.Radius)
            out.append(Part.ArcOfCircle(circle, start, start + (b - a)))
    return out


# --- the pick and the cut points --------------------------------------------------------------
def hovered_edge(sketch):
    """The sketch's own edge under the pointer (FreeCAD's preselection) as a geo index, or None."""
    subs = TB.preselected_subs(sketch)
    sub = subs[0] if subs else ""
    if not sub.startswith("Edge"):
        return None
    try:
        return int(sub[4:]) - 1
    except ValueError:
        return None


def near_curve(geo, p, tolerance):
    """Whether p lies within tolerance of the curve geo."""
    try:
        return geo.toShape().distToShape(Part.Vertex(V(p)))[0] <= tolerance
    except Exception:
        return True


def is_construction(sketch, geo):
    try:
        return bool(sketch.getConstruction(geo))
    except Exception:
        return bool(sketch.Geometry[geo].Construction)


def trimmable(sketch, geo):
    if geo is None or geo < 0 or geo >= sketch.GeometryCount:
        return False
    g = sketch.Geometry[geo]
    if g.TypeId not in TRIMMABLE:
        return False
    try:
        if sketch.getGeometryFacade(geo).InternalType != "None":
            return False   # internal geometry of ellipses and splines is not trimmed
    except Exception as _fw_err:
        _fw_log("fwsketch/trim.py:239", _fw_err)
    if ignore_construction() and is_construction(sketch, geo):
        return False
    return True


def cut_params(sketch, geo):
    """Parameters along geo of every crossing with another curve of the sketch (external too)."""
    g = sketch.Geometry[geo]
    others = [h for i, h in enumerate(sketch.Geometry) if i != geo]
    try:
        others += list(sketch.ExternalGeo)
    except Exception as _fw_err:
        _fw_log("fwsketch/trim.py:252", _fw_err)
    out = []
    for h in others:
        try:
            points = g.intersect(h)
        except Exception:
            continue
        for p in points:
            u = param_of(g, (p.X, p.Y) if hasattr(p, "X") else (p.x, p.y))
            if u is not None:
                out.append(u)
    return sorted(out)


def trim_points(sketch, geo, pointer):
    """The two markers: the nearest cuts on either side of the pointer along geo, else its ends
    (seekTrimPoints as the C++ handler shows it); None when geo is not a line, circle or arc."""
    g = sketch.Geometry[geo]
    rng = param_range(g)
    if rng is None:
        return None
    u = param_of(g, pointer)
    cuts = cut_params(sketch, geo)
    periodic = g.TypeId == "Part::GeomCircle"
    before = [c for c in cuts if c <= u]
    after = [c for c in cuts if c > u]
    if periodic:
        if len(cuts) < 2:
            return None
        a = before[-1] if before else cuts[-1]
        b = after[0] if after else cuts[0]
    else:
        a = before[-1] if before else rng[0]
        b = after[0] if after else rng[1]
    return [point_at(g, a), point_at(g, b)]


RELATION_LOSS_TEXT = ("The sketch segment being trimmed has a midpoint or equal length or equidistant or "
                      "polyline intersection relation. Trimming the segment will delete the relation. "
                      "Do you want to continue?")


def loses_relation(sketch, geo):
    ""


    try:
        if sketch.Geometry[geo].TypeId != "Part::GeomLineSegment":
            return False
    except Exception:
        return False
    for c in sketch.Constraints:
        if c.Type == "Symmetric" and c.First == geo and c.Second == geo:
            return True
        if c.Type == "Equal" and geo in (c.First, c.Second):
            return True
    return False


def confirm_relation_loss(parent=None):
    ""
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, "Trim Entities", RELATION_LOSS_TEXT,
                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, parent or Gui.getMainWindow())
    box.setObjectName("TrimDeletesRelation")
    box.setDefaultButton(QtWidgets.QMessageBox.Yes)
    box.show()
    box.raise_()
    box.activateWindow()
    answer = box.exec()
    App.Console.PrintLog("FreeCAD Trim: Trim Entities question answered %s\n" % answer)
    return answer == QtWidgets.QMessageBox.Yes


# --- the tool ----------------------------------------------------------------------------------
# The Trim PropertyManager while it is in one of its own modes (Corner, Trim away inside/outside):
# a click on an entity goes to it (page.own_pick(geo, (x, y)) -> True when it took the click), and
# a drag does no Power trim
PAGE = None


def _page_mode():
    page = PAGE
    try:
        return page if page is not None and page.own_mode() else None
    except Exception:
        return None


class TrimTool(SketchTool):
    def __init__(self, gdoc, sketch):
        super().__init__(gdoc, sketch)
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Trimming"

    def title(self):
        return "Trim Entities"

    def starts_click_drag(self):
        return False

    def reset(self):
        super().reset()
        self.hover = None
        self.last_trim = None
        self.trail = []
        self.power_trims = []    # (geo, point) trimmed along the path, for tests

    def _filter(self, obj, event):
        # the mouse moves pass through, so FreeCAD preselects the curve under the pointer (the
        # pick comes from it, as the C++ handler's getPreselectCurve); the markers follow right after
        if (obj is self.viewport or obj is self.quarter) and event.type() == QtCore.QEvent.MouseMove \
                and self._press is None:
            if self._other_down or other_buttons(event):
                return False
            QtCore.QTimer.singleShot(0, self._move)
            return False
        return super()._filter(obj, event)

    def on_move(self, p, px):
        d = self.snap(p, px, allow_point=False, allow_edge=False, allow_angle=False, allow_grid=False)
        if self._press is not None and self._dragged and _page_mode() is None:

            self._power_trim(d.position)
            self.hover = None
            self.preview([], construction=[list(self.trail)] if len(self.trail) > 1 else [])
            return []
        if self.trail and self._press is None:
            self.trail = []
        geo = hovered_edge(self.sketch)
        self.hover = geo if trimmable(self.sketch, geo) else None
        if self.hover is not None and not near_curve(self.sketch.Geometry[geo], d.position, 8.0 * px):
            self.hover = None   # a stale preselection (the pointer is not on that curve)
        marks = trim_points(self.sketch, self.hover, d.position) if self.hover is not None else None
        self.preview([], points=marks or [])
        return []

    def _power_trim(self, pos):
        ""

        if not self.trail:
            self.trail = [pos]
            return
        start = self.trail[-1]
        if len(self.trail) == 1 and length(sub(pos, start)) > EPS:
            # the first stroke piece starts a few pixels behind the press, so a curve the press was
            # on (or just short of) is crossed too
            back = unit_from(pos, start)
            reach = 4.0 * (self.pixel or 0.1)
            start = (start[0] + back[0] * reach, start[1] + back[1] * reach)
        self.trail.append(pos)
        sk = self.sketch
        for _ in range(16):
            if length(sub(pos, start)) < EPS:
                return
            path = Part.LineSegment(V(start), V(pos))
            best = None
            for geo, g in enumerate(sk.Geometry):
                if not trimmable(sk, geo):
                    continue
                try:
                    hits = path.intersect(g)
                except Exception:
                    continue
                for h in hits:
                    q = (h.X, h.Y) if hasattr(h, "X") else (h.x, h.y)
                    t = length(sub(q, start))
                    if t > EPS * 10 and (best is None or t < best[0]):
                        best = (t, geo, q)
            if best is None:
                return
            _, geo, q = best
            self.hover = geo
            self._trim(geo, q, ask=False)
            self.power_trims.append((geo, q))
            # go on from just past the crossing
            step = unit_from(start, pos)
            start = (q[0] + step[0] * 1e-4, q[1] + step[1] * 1e-4)

    def _left_press(self, event):

        # that was under the pointer; a drag is Power trim from the press point on, so a stroke
        # that starts on (or right before) a curve trims it too (tester, Beginners 1: two strokes
        # across a fillet arc did nothing, the press had trimmed or asked first)
        self._press = (self._global(event), False)
        self._dragged = False
        self._move()
        d = self.decision
        self._press_pick = (self.hover, d.position if d is not None else None)
        self.trail = [d.position] if d is not None else []

    def _left_release(self):
        press, self._press = self._press, None
        pick, self._press_pick = getattr(self, "_press_pick", (None, None)), (None, None)
        dragged, self._dragged = self._dragged, False
        if press is None or TB._active is not self:
            return
        page = _page_mode()
        if page is not None:
            if not dragged and pick[0] is not None and pick[1] is not None and pick[0] < len(self.sketch.Geometry):
                try:
                    page.own_pick(pick[0], pick[1])
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: trim: %s\n" % error)
        elif not dragged and pick[0] is not None and pick[1] is not None and pick[0] < len(self.sketch.Geometry):
            self._trim(pick[0], pick[1])
        self.trail = []
        self.preview([])
        if TB._active is self:
            self._move()

    def on_click(self, d):
        if self.hover is None or _page_mode() is not None:
            return
        self._trim(self.hover, d.position)

    def _trim(self, geo, pointer, ask=True):
        sk = self.sketch
        keep = keep_as_construction() and not is_construction(sk, geo)
        if ask and loses_relation(sk, geo):
            App.Console.PrintLog("FreeCAD Trim: Edge%d carries a midpoint or Equal relation, asking\n" % (geo + 1))
            if not confirm_relation_loss():
                self.last_trim = (geo, pointer, "declined")
                return

        def body():
            before = sk.Geometry[geo].copy()
            # other geometry already on the same curve stays out of the reckoning
            others = {curve_key(g) for i, g in enumerate(sk.Geometry) if i != geo and same_curve(before, g)}
            touching = _tangent_ends(sk, geo)
            sk.trim(geo, V(pointer))
            # a midpoint or other relation the trim could not carry over can be left malformed

            # relation with the trim, as its question says
            try:
                sk.solve()
                bad = sorted(set(sk.MalformedConstraints), reverse=True)
            except Exception:
                bad = []
            for i in bad:
                try:
                    sk.delConstraint(i - 1)
                except Exception as _fw_err:
                    _fw_log("fwsketch/trim.py:495", _fw_err)
            _keep_tangent(sk, touching, before)
            coradial(sk, before, geo, others)
            drop_redundant(sk)
            added = []
            if keep and before.TypeId in KEEPABLE:
                remaining = [g for g in sk.Geometry if same_curve(before, g) and curve_key(g) not in others]
                for piece in removed_pieces(before, remaining):
                    added.append(sk.addGeometry(piece, True))
            return added

        try:
            Gui.Selection.rmPreselect()
        except Exception as _fw_err:
            _fw_log("fwsketch/trim.py:506", _fw_err)
        try:
            added = self.transaction("Trim edge", body)
        except Exception as e:
            App.Console.PrintError("FreeCAD Trim: %s\n" % e)
            added = []
        self.last_trim = (geo, pointer, added)
        self.hover = None
        self.preview([])


def _tangent_ends(sk, geo):
    """Tags of (entity, end) held tangent on geo (end to edge) before a trim of geo."""
    out = []
    try:
        tags = [g.Tag for g in sk.Geometry]
        for c in sk.Constraints:
            if c.Type != "Tangent":
                continue
            for a, ap, b, bp in ((c.First, c.FirstPos, c.Second, c.SecondPos),
                                 (c.Second, c.SecondPos, c.First, c.FirstPos)):
                if b == geo and int(bp) == 0 and int(ap) in (1, 2) and 0 <= a < len(tags):
                    out.append((tags[a], int(ap)))
    except Exception as _fw_err:
        _fw_log("fwsketch/trim.py: tangent ends", _fw_err)
    return out


def _keep_tangent(sk, touching, before):
    ""



    if not touching:
        return
    try:
        import Sketcher
        for tag, pos in touching:
            tags = [g.Tag for g in sk.Geometry]
            if tag not in tags:
                continue
            a = tags.index(tag)
            pieces = [i for i, g in enumerate(sk.Geometry) if g.TypeId in ROUND and same_curve(before, g)]
            done = False
            for k, c in enumerate(sk.Constraints):
                if (c.First, int(c.FirstPos)) == (a, pos):
                    b, bp = c.Second, int(c.SecondPos)
                elif (c.Second, int(c.SecondPos)) == (a, pos):
                    b, bp = c.First, int(c.FirstPos)
                else:
                    continue
                if b not in pieces:
                    continue
                if c.Type == "Coincident" and bp in (1, 2):
                    sk.delConstraint(k)
                    sk.addConstraint(Sketcher.Constraint("Tangent", a, pos, b, bp))
                done = True             # held on the curve still (tangent or not, as FreeCAD carried it)
                break
            if done:
                continue
            end = sk.getPoint(a, pos)
            for b in pieces:
                if sk.Geometry[b].toShape().distToShape(Part.Vertex(end))[0] < 1e-6:
                    sk.addConstraint(Sketcher.Constraint("Tangent", a, pos, b))
                    break
    except Exception as _fw_err:
        _fw_log("fwsketch/trim.py: keep tangent", _fw_err)


ROUND = ("Part::GeomCircle", "Part::GeomArcOfCircle")
SIZED = ("Radius", "Diameter", "Equal")


def coradial(sk, before, geo, others):
    ""


    if before.TypeId not in ROUND:
        return []
    try:
        geos = sk.Geometry
        pieces = [i for i, g in enumerate(geos) if same_curve(before, g) and curve_key(g) not in others
                  and not sk.getConstruction(i)]
        if len(pieces) < 2:
            return []
        base = geo if geo in pieces else pieces[0]

        def sized(i):
            return any(c.Type in SIZED and (c.First == i or (c.Type == "Equal" and c.Second == i))
                       for c in sk.Constraints)
        out = []
        import Sketcher
        for i in pieces:
            if i == base or sized(i):
                continue
            k = sk.addConstraint(Sketcher.Constraint("Equal", base, i))
            sk.solve()
            if k + 1 in set(sk.RedundantConstraints) | set(sk.ConflictingConstraints) \
                    | set(getattr(sk, "PartiallyRedundantConstraints", []) or []):
                sk.delConstraint(k)         # already held the same size: nothing to add
                continue
            out.append(k)
        return out
    except Exception as _fw_err:
        _fw_log("fwsketch/trim.py: coradial", _fw_err)
        return []


def drop_redundant(sk, limit=8):
    ""


    try:
        for _ in range(limit):
            sk.solve()
            red = sorted(set(sk.RedundantConstraints), reverse=True)
            if not red:
                return
            sk.delConstraint(red[0] - 1)
    except Exception as _fw_err:
        _fw_log("fwsketch/trim.py: drop redundant", _fw_err)


def unit_from(a, b):
    d = sub(b, a)
    n = length(d)
    return (d[0] / n, d[1] / n) if n > 0 else (0.0, 0.0)


def start_trim():
    gdoc, sketch = edited_sketch()
    t = TrimTool(gdoc, sketch)
    t.begin()
    return t
