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
import Sketcher

from PySide import QtCore, QtGui, QtWidgets

from . import inference as I
from . import snap as S
from . import model as M
from . import geom
from . import toolbase as TB
from .toolbase import SketchTool, param_bool, continuous_mode
from . import modifybox as MB

V = App.Vector
SKETCHER_GROUP = "User parameter:BaseApp/Preferences/Mod/Sketcher"
DIMENSIONING_GROUP = "User parameter:BaseApp/Preferences/Mod/Sketcher/dimensioning"
SNAP_GROUP = "User parameter:BaseApp/Preferences/Mod/Sketcher/Snap"

POINT, LINE, CIRCLE, ELLIPSE, SPLINE = "point", "line", "circle", "ellipse", "spline"
KINDS = (POINT, LINE, CIRCLE, ELLIPSE, SPLINE)
FIRST, SECOND, THIRD, FOURTH, FIFTH, RESET = range(6)      # AvailableConstraint
NO_SPECIAL, LINE_OR_POINTS_DISTANCE, BLOCK = range(3)      # SpecialConstraint
UNDEF = I.GEO_UNDEF
CONFUSION = 1e-7
DIMENSIONAL = MB.DIMENSIONAL



def _relation_glyph(sketch, sub):
    """True when sub (ConstraintN) is a relation, not a dimension."""
    try:
        c = sketch.Constraints[int(sub[10:]) - 1]
    except Exception:
        return False
    return c.Type not in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle", "Weight")

class Pick:
    """One picked element: a sketch point (pos != NONE) or curve; model = (model geo, pos) when it
    is the part's corner or edge, referenced through external geometry."""
    __slots__ = ("geo", "pos", "name", "model", "shift", "at")

    def __init__(self, geo, pos, name, model=None):
        self.geo, self.pos, self.name, self.model = geo, pos, name, model
        self.shift, self.at = False, None     # Shift held at the pick (arcs: Min/Max), where it was

    def same(self, other):
        return (self.geo, self.pos) == (other.geo, other.pos)

    def __repr__(self):
        return "Pick(%s, %s, %s)" % (self.geo, self.pos, self.name)


# --- geometry -------------------------------------------------------------------------------------
def geometry_of(sketch, geo):
    """SketchObject::getGeometry: sketch geometry, the axes (external 0 and 1) and references."""
    try:
        if geo >= 0:
            return sketch.Geometry[geo]
        if geo == I.H_AXIS:
            return sketch.ExternalGeo[0]
        if geo == I.V_AXIS:
            return sketch.ExternalGeo[1]
        return sketch.ExternalGeo[-geo - 1]
    except Exception:
        return None


def kind_of(sketch, geo, pos):
    if pos != I.NONE:
        return POINT
    g = geometry_of(sketch, geo)
    if isinstance(g, Part.LineSegment):
        return LINE
    if isinstance(g, (Part.Circle, Part.ArcOfCircle)):
        return CIRCLE
    if isinstance(g, (Part.Ellipse, Part.ArcOfEllipse, Part.ArcOfHyperbola, Part.ArcOfParabola)):
        return ELLIPSE
    if isinstance(g, Part.BSplineCurve):
        return SPLINE
    return None


def is_circle(g):
    return isinstance(g, Part.Circle)


def is_arc(g):
    return isinstance(g, Part.ArcOfCircle)


def is_line(g):
    return isinstance(g, Part.LineSegment)


def has_block(sketch, geo):
    return any(c.Type == "Block" and c.First == geo for c in sketch.Constraints)


def is_fixed(sketch, geo):
    """isPointOrSegmentFixed: blocked, or not sketch geometry (axes, origin, references)."""
    return geo != UNDEF and (has_block(sketch, geo) or geo <= I.ROOT)


def both_fixed(sketch, geo1, geo2):
    return geo1 != UNDEF and geo2 != UNDEF and is_fixed(sketch, geo1) and is_fixed(sketch, geo2)


def point_of(sketch, geo, pos):
    p = sketch.getPoint(geo, pos)
    return (p.x, p.y)


def point_line_distance(pnt, line):
    p1, p2 = line.StartPoint, line.EndPoint
    d = p2 - p1
    if d.Length < 1e-12:
        return 0.0
    return abs(-pnt[0] * d.y + pnt[1] * d.x + p1.x * p2.y - p2.x * p1.y) / d.Length


def distance_value(sketch, geo1, pos1, geo2, pos2):
    """The measured value of a Distance between the two picks (createDistanceConstrain), and the
    constraint to add; None when the pair has no distance."""
    if pos1 != I.NONE and pos2 == I.NONE:
        pnt = point_of(sketch, geo1, pos1)
        g = geometry_of(sketch, geo2)
        if is_line(g):
            value = point_line_distance(pnt, g)
        elif is_circle(g) or is_arc(g):
            value = abs((g.Center - V(pnt[0], pnt[1], 0)).Length - g.Radius)
        else:
            return None
        return value, Sketcher.Constraint("Distance", geo1, pos1, geo2, value)
    if pos1 == I.NONE and pos2 == I.NONE:
        g1, g2 = geometry_of(sketch, geo1), geometry_of(sketch, geo2)
        if (is_circle(g1) or is_arc(g1)) and is_line(g2):
            value = abs(point_line_distance((g1.Center.x, g1.Center.y), g2) - g1.Radius)
        elif (is_circle(g1) or is_arc(g1)) and (is_circle(g2) or is_arc(g2)):
            r1, r2 = g1.Radius, g2.Radius
            between = (g1.Center - g2.Center).Length
            if between >= r1 and between >= r2:
                value = between - r1 - r2
            else:
                value = max(r1, r2) - min(r1, r2) - between
        else:
            return None
        return value, Sketcher.Constraint("Distance", geo1, geo2, value)
    p1, p2 = sketch.getPoint(geo1, pos1), sketch.getPoint(geo2, pos2)
    value = (p2 - p1).Length
    return value, Sketcher.Constraint("Distance", geo1, pos1, geo2, pos2, value)


def _cross(a, b):
    return a.x * b.y - a.y * b.x


def angle_for_pointer(sketch, geo1, geo2, p):
    ""


    g1, g2 = geometry_of(sketch, geo1), geometry_of(sketch, geo2)
    if not is_line(g1) or not is_line(g2):
        return None
    d1, d2 = g1.EndPoint - g1.StartPoint, g2.EndPoint - g2.StartPoint
    den = _cross(d1, d2)
    if abs(den) < 1e-12 or d1.Length < 1e-12 or d2.Length < 1e-12:
        return None
    t = _cross(g2.StartPoint - g1.StartPoint, d2) / den
    s = g1.StartPoint + d1 * t
    u = V(p[0], p[1], 0) - s
    if u.Length < 1e-9:
        return None
    for a in (1, -1):
        for b in (1, -1):
            v1, v2 = d1 * a, d2 * b
            first, second = ((geo1, a, v1), (geo2, b, v2)) if _cross(v1, v2) > 0 else ((geo2, b, v2), (geo1, a, v1))
            f, g = first[2], second[2]
            if _cross(f, u) >= 0 and _cross(u, g) >= 0:
                angle = math.atan2(_cross(f, g), f.x * g.x + f.y * g.y)
                return (first[0], I.START if first[1] > 0 else I.END,
                        second[0], I.START if second[1] > 0 else I.END, angle)
    return None


def calculate_angle(sketch, geo1, geo2):
    """calculateAngle: (geo1, pos1, geo2, pos2, angle) between two lines, the ends nearest their
    crossing; angle 0.0 for parallel lines apart; None when not two lines."""
    g1, g2 = geometry_of(sketch, geo1), geometry_of(sketch, geo2)
    if not is_line(g1) or not is_line(g2):
        return None
    p1 = (g1.StartPoint, g1.EndPoint)
    p2 = (g2.StartPoint, g2.EndPoint)
    d1 = p1[1] - p1[0]
    d2 = p2[1] - p2[0]
    den = d1.x * d2.y - d1.y * d2.x
    if abs(den) > 1e-12:
        t = ((p2[0].x - p1[0].x) * d2.y - (p2[0].y - p1[0].y) * d2.x) / den
        s = p1[0] + d1 * t
        pos1 = I.START if (s - p1[0]).Length < (s - p1[1]).Length else I.END
        pos2 = I.START if (s - p2[0]).Length < (s - p2[1]).Length else I.END
    else:
        best = None
        for i in (0, 1):
            for j in (0, 1):
                dd = (p1[i] - p2[j]).Length
                if best is None or dd < best:
                    best = dd
                    pos1 = I.END if i else I.START
                    pos2 = I.END if j else I.START
    dir1 = d1 if pos1 == I.START else -d1
    dir2 = d2 if pos2 == I.START else -d2
    cross = dir1.cross(dir2)
    if cross.Length < 1e-10:
        dist = (p1[0] - p2[0]).cross(dir1)
        if dist.Length ** 2 > 1e-10:
            return geo1, pos1, geo2, pos2, 0.0
    angle = math.atan2(dir1.x * dir2.y - dir1.y * dir2.x, dir1.y * dir2.y + dir1.x * dir2.x)
    if angle < 0:
        angle = -angle
        geo1, geo2 = geo2, geo1
        pos1, pos2 = pos2, pos1
    for c in sketch.Constraints:
        if c.Type == "Perpendicular" and c.FirstPos == I.NONE and c.SecondPos == I.NONE and c.Third == UNDEF \
                and {c.First, c.Second} == {geo1, geo2}:
            angle = math.pi / 2
            break
    return geo1, pos1, geo2, pos2, angle


def distance_type_for(pnt1, pnt2, pos):
    """updateDistanceType: which of DistanceX, DistanceY, Distance the pointer position asks for
    between the two points (None when it stays)."""
    min_x, max_x = min(pnt1[0], pnt2[0]), max(pnt1[0], pnt2[0])
    min_y, max_y = min(pnt1[1], pnt2[1]), max(pnt1[1], pnt2[1])
    x, y = pos
    inside_x = min_x < x < max_x
    inside_y = min_y < y < max_y
    if inside_x != inside_y:
        kind = "DistanceX" if inside_x else "DistanceY"

        # while the pointer is out square to it, and the horizontal / vertical one while it is out straight up
        # or down / to the side: whichever way is nearer the pointer's way out from the middle.
        # FreeCAD's box rule alone made a DistanceX square below a 22 deg line.
        dx, dy = pnt2[0] - pnt1[0], pnt2[1] - pnt1[1]
        angle = math.degrees(math.atan2(dy, dx)) % 180.0
        if dx * dx + dy * dy > 1e-12 and 1.0 < angle % 90.0 < 89.0:
            mx, my = (pnt1[0] + pnt2[0]) / 2.0, (pnt1[1] + pnt2[1]) / 2.0
            way = math.degrees(math.atan2(y - my, x - mx)) % 180.0

            def apart(a, b):
                d = abs(a - b) % 180.0
                return min(d, 180.0 - d)
            square = apart(way, angle + 90.0)
            if square < apart(way, 90.0 if inside_x else 0.0):
                return "Distance"
        return kind
    if not inside_x and not inside_y:

        # dimension whose way out is nearest the pointer's way out from the middle: to the side the vertical
        # one, straight up or down the horizontal one, square to the pair the aligned one.
        dx, dy = pnt2[0] - pnt1[0], pnt2[1] - pnt1[1]
        angle = math.degrees(math.atan2(dy, dx)) % 180.0
        if dx * dx + dy * dy > 1e-12 and 1.0 < angle % 90.0 < 89.0:
            mx, my = (pnt1[0] + pnt2[0]) / 2.0, (pnt1[1] + pnt2[1]) / 2.0
            way = math.degrees(math.atan2(y - my, x - mx)) % 180.0

            def apart(a, b):
                d = abs(a - b) % 180.0
                return min(d, 180.0 - d)
            ways = ((apart(way, angle + 90.0), "Distance"), (apart(way, 0.0), "DistanceY"), (apart(way, 90.0), "DistanceX"))
            return min(ways)[1]
        return "Distance"
    if inside_x and inside_y:
        return "Distance"
    return None


def label_for(sketch, c, to_pos, offset=0.0):
    """(LabelDistance, LabelPosition or None) that puts dimension c at to_pos (moveConstraint)."""
    t = c.Type
    to = V(to_pos[0], to_pos[1], 0)
    if t in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter"):
        p1 = p2 = V(0, 0, 0)
        if c.SecondPos != I.NONE:
            p1 = sketch.getPoint(c.First, c.FirstPos)
            p2 = sketch.getPoint(c.Second, c.SecondPos)
        elif c.Second != UNDEF:
            p1 = sketch.getPoint(c.First, c.FirstPos) if c.FirstPos != I.NONE else V(0, 0, 0)
            g1, g2 = geometry_of(sketch, c.First), geometry_of(sketch, c.Second)
            if is_line(g2):
                if (is_circle(g1) or is_arc(g1)) and c.FirstPos == I.NONE:
                    g1, g2 = g2, g1
                else:
                    a, b = g2.StartPoint, g2.EndPoint
                    d = b - a
                    tt = (p1 - a).dot(d) / d.dot(d) if d.dot(d) > 0 else 0.0
                    p2 = a + d * tt
            if is_circle(g2) or is_arc(g2):
                ct, rad = g2.Center, g2.Radius
                if c.FirstPos != I.NONE:
                    v = p1 - ct
                    if v.Length > 0:
                        v.normalize()
                    p2 = ct + v * rad
                elif is_circle(g1) or is_arc(g1):
                    ct1, r1 = g1.Center, g1.Radius
                    v = ct - ct1
                    between = v.Length
                    if between > 0:
                        v.normalize()
                    if between >= r1 and between >= rad:
                        p1, p2 = ct1 + v * r1, ct - v * rad
                    elif r1 > rad:
                        p1, p2 = ct1 + v * r1, ct + v * rad
                    else:
                        p1, p2 = ct1 - v * r1, ct - v * rad
                elif is_line(g1):
                    a, b = g1.StartPoint, g1.EndPoint
                    d = b - a
                    tt = (ct - a).dot(d) / d.dot(d) if d.dot(d) > 0 else 0.0
                    p1 = a + d * tt
                    v = p1 - ct
                    if v.Length > 0:
                        v.normalize()
                    p2 = ct + v * rad
        elif c.FirstPos != I.NONE:
            p2 = sketch.getPoint(c.First, c.FirstPos)
        elif c.First != UNDEF:
            g = geometry_of(sketch, c.First)
            if is_line(g):
                p1, p2 = g.StartPoint, g.EndPoint
            elif is_arc(g):
                center = g.Center
                a0, a1 = g.FirstParameter, g.LastParameter
                if t == "Distance":  # arc length
                    mid = (a0 + a1) / 2
                    v = to - center
                    return v.x * math.cos(mid) + v.y * math.sin(mid), None
                p1 = center
                angle = math.atan2(to.y - p1.y, to.x - p1.x)
                r = g.Radius
                if t == "Diameter":
                    p1 = center - V(math.cos(angle), math.sin(angle), 0) * r
                p2 = center + V(math.cos(angle), math.sin(angle), 0) * r
            elif is_circle(g):
                center, r = g.Center, g.Radius
                p1 = center
                v = to - p1
                if v.Length > 0:
                    v.normalize()
                d = v * r
                if t == "Diameter":
                    p1 = center - d
                p2 = center + d
            else:
                return None
        else:
            return None
        vec = to - p2
        if t in ("Distance", "Radius", "Diameter"):
            d = p2 - p1
            if d.Length > 0:
                d.normalize()
        elif t == "DistanceX":
            d = V(1 if p2.x - p1.x >= 1e-7 else -1, 0, 0)
        else:
            d = V(0, 1 if p2.y - p1.y >= 1e-7 else -1, 0)
        if t in ("Radius", "Diameter"):
            distance = vec.x * d.x + vec.y * d.y
            if distance > offset:
                distance -= offset
            return distance, math.atan2(d.y, d.x)
        normal = V(-d.y, d.x, 0)
        distance = vec.x * normal.x + vec.y * normal.y - offset
        vec = to - (p2 + p1) * 0.5
        return distance, vec.x * d.x + vec.y * d.y
    if t == "Angle":
        if c.Second != UNDEF:
            g1, g2 = geometry_of(sketch, c.First), geometry_of(sketch, c.Second)
            if not is_line(g1) or not is_line(g2):
                return None
            a, b = (g1.StartPoint, g1.EndPoint), (g2.StartPoint, g2.EndPoint)
            d1, d2 = a[1] - a[0], b[1] - b[0]
            den = d1.x * d2.y - d1.y * d2.x
            if abs(den) < 1e-12:
                return None
            tt = ((b[0].x - a[0].x) * d2.y - (b[0].y - a[0].y) * d2.x) / den
            p0 = a[0] + d1 * tt
            return 0.5 * (to - p0).Length, None
        g = geometry_of(sketch, c.First)
        if is_line(g):
            p0 = (g.StartPoint + g.EndPoint) * 0.5
            return 0.5 * (to - p0).Length, None
        if is_arc(g):
            mid = (g.FirstParameter + g.LastParameter) / 2
            v = to - g.Center
            return 0.5 * (v.x * math.cos(mid) + v.y * math.sin(mid)), None
    return None


def model_element_at(snapper, pos, radius):
    """(model geo id, pos) of the part's corner within radius of pos, else its nearest edge
    (modelElementAt, package 11); None when nothing is near."""
    p = V(pos[0], pos[1], 0)
    best_corner = best_edge = radius
    corner = edge = None
    for i, (_obj, el) in enumerate(snapper.model_targets()):
        gid = S.MODEL_BASE - i
        g = el.geometry
        ends = []
        if isinstance(g, Part.Point):
            ends = [((g.X, g.Y), I.START)]
        elif is_line(g):
            ends = [(I.point_of(g, I.START), I.START), (I.point_of(g, I.END), I.END)]
        elif is_arc(g):
            ends = [(I.point_of(g, I.START), I.START), (I.point_of(g, I.END), I.END)]
        for at, at_pos in ends:
            d = math.hypot(at[0] - pos[0], at[1] - pos[1])
            if d < best_corner:
                best_corner, corner = d, (gid, at_pos)
        if isinstance(g, Part.Point):
            continue
        d = M._distance_to(g, p)
        if d < best_edge:
            best_edge, edge = d, (gid, I.NONE)
    return corner or edge


def preselected(sketch):
    """The sketch element under the pointer as a Pick, or None (FreeCAD's preselection)."""
    subs = TB.preselected_subs(sketch)
    sub = subs[0] if subs else ""
    try:
        if sub.startswith("Vertex"):
            geo, pos = sketch.getGeoVertexIndex(int(sub[6:]) - 1)
            return Pick(geo, pos, sub)
        if sub == "RootPoint":
            return Pick(I.ROOT, I.START, sub)
        if sub == "H_Axis":
            return Pick(I.H_AXIS, I.NONE, sub)
        if sub == "V_Axis":
            return Pick(I.V_AXIS, I.NONE, sub)
        if sub.startswith("ExternalEdge"):
            return Pick(-int(sub[12:]) - 2, I.NONE, sub)
        if sub.startswith("Edge"):
            return Pick(int(sub[4:]) - 1, I.NONE, sub)
    except Exception:
        return None
    return None


def same_place(sketch, geo1, pos1, geo2, pos2):
    ""

    if pos1 == I.NONE or pos2 == I.NONE:
        return False
    try:
        return (sketch.getPoint(geo1, pos1) - sketch.getPoint(geo2, pos2)).Length < 1e-7
    except Exception:
        return False


def element_under(sketch, p, radius, skip=()):
    ""


    at = V(p[0], p[1], 0)
    best = None
    try:
        for v in range(10000):
            geo, pos = sketch.getGeoVertexIndex(v)
            if geo == UNDEF or (geo == -2000):
                break
            if geo < 0 or geo in skip:
                continue
            d = (sketch.getPoint(geo, pos) - at).Length
            if d <= radius and (best is None or d < best[0]):
                best = (d, Pick(geo, pos, "Vertex%d" % (v + 1)))
    except Exception as _fw_err:
        _fw_log("fwsketch/dimension.py:480", _fw_err)
    if best is not None:
        return best[1]
    for i, g in enumerate(sketch.Geometry):
        if i in skip or isinstance(g, Part.Point):
            continue
        try:
            d = g.toShape().distToShape(Part.Vertex(at))[0]
        except Exception:
            continue
        if d <= radius and (best is None or d < best[0]):
            best = (d, Pick(i, I.NONE, "Edge%d" % (i + 1)))
    return best[1] if best is not None else None


def outline(g):
    if is_line(g):
        return [(g.StartPoint.x, g.StartPoint.y), (g.EndPoint.x, g.EndPoint.y)]
    if is_arc(g):
        return geom.arc_points((g.Center.x, g.Center.y), g.Radius, g.FirstParameter, g.LastParameter - g.FirstParameter)
    if is_circle(g):
        return geom.circle_points((g.Center.x, g.Center.y), g.Radius)
    return []


# --- the tool -------------------------------------------------------------------------------------
def _close_tool_page():
    ""

    try:
        from .. import nativepms, sketchtoolpm
        page = sketchtoolpm.current()
        if isinstance(page, nativepms._ToolOptionsPage):
            page.taken_over()
    except Exception as error:
        App.Console.PrintLog("FreeCAD Smart Dimension: old tool page: %s\n" % error)


def _close_dimension_page():
    ""

    try:
        from .. import sketchtoolpm, dimensionpm
        page = sketchtoolpm.current()
        if isinstance(page, dimensionpm.DimensionPage):
            page.accept()
    except Exception as _fw_err:
        _fw_log("fwsketch/dimension.py:527", _fw_err)


class DimensionTool(SketchTool):
    """Smart Dimension. Picks with left clicks, M for the other kinds, a click on empty space or
    after two picks places the dimension, Esc drops an unplaced one (then ends the tool)."""

    def __init__(self, gdoc, sketch, initial=()):
        super().__init__(gdoc, sketch)
        self.doc = sketch.Document
        self.picks = {k: [] for k in KINDS}
        self.mode = FIRST
        self.special = NO_SPECIAL
        self.indexes = []            # constraints being placed
        self.over_defining = []      # of those, the ones made driven because they would over-define
        self.last_pos = (0.0, 0.0)
        self.pixel = 0.0
        self.hover = None            # (model geo, pos) highlighted under the pointer
        self.open = False            # a transaction of ours is open
        self.initial = list(initial)
        self.placed = []             # (type, value, driving) per placed dimension, for tests
        self.events = []             # for tests
        self.forced = None           # fix285: "DistanceX" / "DistanceY": Horizontal / Vertical Dimension

    def icon_name(self):
        return "Sketcher_Crosshair"

    def icon_badge(self):
        return "Constraint_Dimension"

    def title(self):
        return {"DistanceX": "Horizontal Dimension", "DistanceY": "Vertical Dimension"}.get(self.forced, "Smart Dimension")

    def is_first_state(self):
        return self.empty()

    # --- life ----------------------------------------------------------------------------------
    def begin(self):
        super().begin()
        _close_tool_page()
        self.open_command("Dimension")
        if self.initial:
            # fix294: a line picked before Smart Dimension: the dimension is made once the command has
            # returned. Made inside it, FreeCAD committed it as "Add length constraint" with the command,

            QtCore.QTimer.singleShot(0, self._initial_later)
        else:
            self.handle_initial_selection()

    def _initial_later(self):
        if TB.active() is not self:
            return
        self.ensure_open()
        self.handle_initial_selection()
        try:
            if self.indexes and self.last_pos is not None:
                self.move_constraints(self.last_pos)
        except Exception as _fw_err:
            _fw_log("fwsketch/dimension.py:initial-later", _fw_err)

    def end(self):
        self.clear_hover()
        if self.open:
            self.abort()
        super().end()
        try:
            self.sketch.solve()
        except Exception as _fw_err:
            _fw_log("fwsketch/dimension.py:577", _fw_err)

    def reset(self):
        # SketchTool.reset is called from begin(); the dimension tool keeps its own state in reset_tool
        self.suggestions = []
        if self.scene is not None:
            self.scene.clear()

    def cancel_current(self):
        self.reset_tool()

    # --- transactions ----------------------------------------------------------------------------
    def open_command(self, name):
        if self.open:
            self.abort()
        self.doc.openTransaction(name)
        try:
            self.open = True
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise

    def ensure_open(self, name="Dimension"):
        """Our transaction, open for sure. begin() opens it inside the command's Activated, and when
        the tool was started from a button (Command::invoke, also Gui.runCommand) FreeCAD closes
        the active transaction as Activated returns; the tool then believed it was still open and a
        later Escape could not take a picked part edge's reference back (found 2026-10-30 with real
        toolbar clicks)."""
        if self.open:
            try:
                active = App.getActiveTransaction()
            except Exception:
                active = None
            if active is None:
                self.open = False
        if not self.open:
            self.open_command(name)

    def abort(self):
        # abortCommand: close FreeCAD's active transaction too, even when nothing was changed yet,
        # otherwise the next change anywhere (a recompute) opens a "Dimension" undo step on its own
        if self.open:
            self.doc.abortTransaction()
            self.open = False
        try:
            App.closeActiveTransaction(True)
        except Exception as _fw_err:
            _fw_log("fwsketch/dimension.py:620", _fw_err)
        try:
            self.sketch.solve()
        except Exception as _fw_err:
            _fw_log("fwsketch/dimension.py:624", _fw_err)

    def commit(self):
        if self.open:
            self.doc.commitTransaction()
            self.open = False
        try:
            App.closeActiveTransaction(False)
        except Exception as _fw_err:
            _fw_log("fwsketch/dimension.py:633", _fw_err)

    def restart(self, name):
        """restartCommand: drop what was made for the picks so far, keep the picks."""
        self.special = NO_SPECIAL
        self.angle_lines = None
        self.unselect_model_picks()
        self.open_command(name)
        self.restore_model_picks()
        self.indexes = []
        self.over_defining = []

    def reset_tool(self):
        self.diam_watch = None
        self.clear_hover()
        self.abort()
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("fwsketch/dimension.py:652", _fw_err)
        self.open_command("Dimension")
        self.indexes = []
        self.over_defining = []
        self.special = NO_SPECIAL
        self.mode = FIRST
        for k in KINDS:
            self.picks[k] = []
        if self.scene is not None:
            self.scene.clear()

    def aborted(self):
        """hasBeenAborted: the user undid under the tool (Ctrl+Z)."""
        return bool(self.indexes) and self.indexes[-1] != self.sketch.ConstraintCount - 1

    # --- events ----------------------------------------------------------------------------------
    def _filter(self, obj, event):
        from . import dimdrag
        answer = dimdrag.filter(self, obj, event)   # package 36: dimension drags, drag to nothing
        if answer is not None:
            return answer
        t = event.type()
        if (obj is self.viewport or obj is self.quarter) and t == QtCore.QEvent.MouseMove:
            if self._other_down or TB.other_buttons(event):
                return False
            self._move()
            return False  # FreeCAD still preselects what is under the pointer: the picks use it
        return super()._filter(obj, event)

    def _left_press(self, event):
        self._press = (self._global(event), False)

    def _left_release(self):
        if self._press is None:
            return
        self._press = None
        p, px = self.pointer()
        if p is None:
            return
        self.pixel = px
        self.release(p)

    def _key(self, key):
        if key == QtCore.Qt.Key_Escape:
            self.events.append(("escape", list(self.indexes), len(self.sketch.ExternalGeo)))
            self.quit()
            self.events.append(("after-escape", len(self.sketch.ExternalGeo), list(self.doc.UndoNames[:2])))
            return True
        if key == QtCore.Qt.Key_M:
            self.cycle_mode()
            return True
        return False

    def quit(self):
        if self.indexes:
            self.reset_tool()   # the dimension being made goes, the tool stays
        else:
            self.end()
            _close_dimension_page()

    def cycle_mode(self):
        self.mode = {FIRST: SECOND, SECOND: THIRD, THIRD: FOURTH, FOURTH: FIFTH}.get(self.mode, FIRST)
        self.make_constraint(self.last_pos)

    def _move(self):
        if TB.active() is not self or self.scene is None:
            return
        p, px = self.pointer()
        if p is None:
            return
        self.last_pos, self.pixel = p, px
        if self.aborted():
            self.reset_tool()
            return
        self.show_model_hover(p, px)
        if self.special == LINE_OR_POINTS_DISTANCE:
            self.update_distance_type(p)
        if getattr(self, "angle_lines", None) and self.indexes:
            self.update_angle_quadrant(p)
        if getattr(self, "diam_watch", None) and self.indexes and self.mode == FIRST:

            now = any(self.across_centerline(c_, g_, q_, p) for c_, g_, q_ in self.diam_watch)
            if now != getattr(self, "diam_now", False):
                self.make_constraint(p)
        self.move_constraints(p)

    # --- picking -----------------------------------------------------------------------------------
    def pick_count(self):
        return sum(len(v) for v in self.picks.values())

    def hint_state(self):
        return min(self.pick_count(), 2) if not self.indexes else 2

    def empty(self):
        return all(not self.picks[k] for k in (POINT, LINE, CIRCLE, ELLIPSE))

    def selected_yet(self, pick):
        return any(pick.same(q) for k in (POINT, LINE, CIRCLE, ELLIPSE) for q in self.picks[k])

    def snap_radius(self):
        return max(1, App.ParamGet(SNAP_GROUP).GetInt("SnapRadius", 5)) * self.pixel

    def pick_model(self, p):
        """The part's corner or edge under the pointer as a pick through a reference; (pick, the
        reference is new)."""
        if not self.pixel > 0.0:
            return None, False
        found = model_element_at(self.snapper, p, self.snap_radius())
        if found is None:
            return None, False
        before = len(self.sketch.ExternalGeo)
        resolved = self.snapper.resolve_model_reference(found[0], found[1])
        if resolved is None:
            return None, False
        geo, pos = resolved
        return Pick(geo, pos, self.reference_name(geo, pos), found), len(self.sketch.ExternalGeo) > before

    def reference_name(self, geo, pos):
        if pos == I.NONE:
            return "ExternalEdge%d" % (-geo - 2)
        for i in range(3 * self.sketch.GeometryCount + 4 * len(self.sketch.ExternalGeo)):
            try:
                g, p = self.sketch.getGeoVertexIndex(i)
            except Exception:
                break
            if g == UNDEF:
                break
            if (g, p) == (geo, pos):
                return "Vertex%d" % (i + 1)
        return ""

    def unselect_model_picks(self):
        for k in KINDS:
            for pick in self.picks[k]:
                if pick.model is not None and pick.name:
                    try:
                        Gui.Selection.removeSelection(self.sketch, pick.name)
                    except Exception as _fw_err:
                        _fw_log("fwsketch/dimension.py:790", _fw_err)

    def restore_model_picks(self):
        """After an abort the references are gone: make them again, the picks follow their new ids."""
        self.snapper.sketch_changed()
        for k in KINDS:
            kept = []
            for pick in self.picks[k]:
                if pick.model is not None:
                    resolved = self.snapper.resolve_model_reference(pick.model[0], pick.model[1])
                    if resolved is None:
                        continue
                    pick.geo, pick.pos = resolved
                    pick.name = self.reference_name(pick.geo, pick.pos)
                    if pick.name:
                        try:
                            Gui.Selection.addSelection(self.doc.Name, self.sketch.Name, pick.name)
                        except Exception as _fw_err:
                            _fw_log("fwsketch/dimension.py:808", _fw_err)
                kept.append(pick)
            self.picks[k] = kept

    def release(self, p, forced_pick=None):
        """releaseButton: a pick, an unpick, the placing click, or a click on nothing.
        forced_pick (dragdim-1127): the element pressed at the start of a click-drag, picked as if clicked."""
        self.ensure_open()
        if forced_pick is None and self.pick_count() >= 2 and self.indexes and \
                not self.arc_other_end(preselected(self.sketch)) and not self.arc_three_points(preselected(self.sketch)):
            self.clear_hover()
            self.finalize()
            return
        self.mode = FIRST
        pick = forced_pick if forced_pick is not None else preselected(self.sketch)
        new_reference = False
        if pick is None:
            subs = TB.preselected_subs(self.sketch)
            if subs and subs[0].startswith("Constraint"):
                px = self.pixel or 0.0
                if self.indexes:
                    # the label of the dimension being made is under the pointer: pick through it
                    pick = element_under(self.sketch, p, max(px * 8.0, 1e-6))
                else:

                    # point it starts from stays pickable (FreeCAD preselects the dimension there)
                    under = element_under(self.sketch, p, max(px * 6.0, 1e-6))
                    if under is not None and under.name.startswith("Vertex"):
                        pick = under
                    elif under is not None and under.name.startswith("Edge") and _relation_glyph(self.sketch, subs[0]):

                        # keeps the entity pickable there (PC diag150b V8)
                        pick = under
        if pick is None:
            pick, new_reference = self.pick_model(p)
        self.clear_hover()
        if pick is None:
            try:
                self.events.append(("miss", list(Gui.Selection.getPreselection().SubElementNames)))
            except Exception:
                self.events.append(("miss", None))
            self.finalize()
            return
        kind = kind_of(self.sketch, pick.geo, pick.pos)
        if kind is None:
            self.events.append(("nokind", pick.name))
            return
        self.events.append(("pick", pick.name, kind, list(self.doc.UndoNames[:3])))
        try:
            pick.shift = bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier)
        except Exception:
            pick.shift = False
        pick.at = (p[0], p[1])
        if not self.selected_yet(pick):
            self.picks[kind].append(pick)
            if self.make_constraint(p):
                if self.forced and self.indexes:
                    self.update_distance_type(p)        # fix285: only the horizontal / vertical distance
                if pick.name:
                    try:
                        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name, pick.name)
                    except Exception as _fw_err:
                        _fw_log("fwsketch/dimension.py:866", _fw_err)
            else:
                self.picks[kind].pop()
                if pick.model is not None and new_reference:
                    self.restart("Dimension")  # takes the unused reference out again
                    if not self.empty():
                        self.make_constraint(p)
        else:
            for k in KINDS:
                self.picks[k] = [q for q in self.picks[k] if not q.same(pick)]
            if not self.empty():
                self.make_constraint(p)
            else:
                self.restart("Dimension")
            try:
                Gui.Selection.removeSelection(self.sketch, pick.name)
            except Exception as _fw_err:
                _fw_log("fwsketch/dimension.py:883", _fw_err)

    def arc_other_end(self, pick):
        ""

        pts, cir = self.picks[POINT], self.picks[CIRCLE]
        if pick is None or len(pts) != 1 or len(cir) != 1 or self.pick_count() != 2:
            return False
        c, q = cir[0], pts[0]
        if q.geo != c.geo or not is_arc(geometry_of(self.sketch, c.geo)):
            return False
        return (pick.geo, {I.START: I.END, I.END: I.START}.get(q.pos)) == (c.geo, pick.pos)

    def _arc_of_points(self, picks):
        """The arc whose centre, start and end are exactly these three point picks, or None."""
        if len(picks) != 3 or len({q.geo for q in picks}) != 1:
            return None
        geo = picks[0].geo
        if geo < 0 or {q.pos for q in picks} != {I.START, I.END, I.MID} or not is_arc(geometry_of(self.sketch, geo)):
            return None
        return geo

    def arc_three_points(self, pick):
        ""

        pts = self.picks[POINT]
        if pick is None or len(pts) != 2 or self.pick_count() != 2:
            return False
        return self._arc_of_points(pts + [pick]) is not None

    def handle_initial_selection(self):
        if not self.initial:
            return
        self.events.append(("initial", list(self.initial)))
        if len(self.initial) > 2:

            # picked) starts it empty, never FreeCAD's Equal chain over the picked lines
            self.initial = []
            Gui.Selection.clearSelection()
            return
        self.mode = FIRST
        for name in self.initial:
            pick = None
            try:
                if name.startswith("Vertex"):
                    geo, pos = self.sketch.getGeoVertexIndex(int(name[6:]) - 1)
                    pick = Pick(geo, pos, name)
                elif name.startswith("ExternalEdge"):
                    pick = Pick(-int(name[12:]) - 2, I.NONE, name)
                elif name.startswith("Edge"):
                    pick = Pick(int(name[4:]) - 1, I.NONE, name)
                elif name == "RootPoint":
                    pick = Pick(I.ROOT, I.START, name)
                elif name == "H_Axis":
                    pick = Pick(I.H_AXIS, I.NONE, name)
                elif name == "V_Axis":
                    pick = Pick(I.V_AXIS, I.NONE, name)
            except Exception:
                pick = None
            if pick is None:
                continue
            kind = kind_of(self.sketch, pick.geo, pick.pos)
            if kind is not None:
                self.picks[kind].append(pick)
        if not self.make_constraint((0.0, 0.0)):
            for k in KINDS:
                self.picks[k] = []

    # --- the part under the pointer (11) ---------------------------------------------------------------
    def show_model_hover(self, p, px):
        on_sketch = preselected(self.sketch) is not None
        found = None
        if not on_sketch and px > 0.0 and self.snapper.p.model:
            found = model_element_at(self.snapper, p, max(1, App.ParamGet(SNAP_GROUP).GetInt("SnapRadius", 5)) * px)
        if found == self.hover:
            return
        self.hover = found
        if found is None or self.scene is None:
            self.clear_hover()
            return
        g = self.snapper.geometry(found[0])
        if found[1] != I.NONE:
            at = (g.X, g.Y) if isinstance(g, Part.Point) else I.point_of(g, found[1])
            self.scene.points("hover", [at])
            self.scene.lines("hover", [])
        else:
            self.scene.points("hover", [])
            self.scene.lines("hover", [outline(g)])

    def clear_hover(self):
        self.hover = None
        if self.scene is not None:
            self.scene.points("hover", [])
            self.scene.lines("hover", [])

    # --- what the picks make -------------------------------------------------------------------------
    def make_constraint(self, p):
        """makeAppropriateConstraint: the dimension or relation for the picks in the current mode;
        False when the last pick is not allowed with the others."""
        pts, lns, cir, ell = (self.picks[POINT], self.picks[LINE], self.picks[CIRCLE], self.picks[ELLIPSE])
        n_p, n_l, n_c, n_e, n_s = len(pts), len(lns), len(cir), len(ell), len(self.picks[SPLINE])
        allowed = False
        if n_p:
            if (n_l, n_c, n_e, n_s) == (0, 0, 0, 0):
                if n_p == 1:
                    allowed = self.cts_1point(p)
                elif n_p == 2:
                    allowed = self.cts_2point(p)
                elif n_p == 3:
                    allowed = self.cts_3point()
                else:
                    allowed = self.cts_4point()
            elif (n_l, n_c, n_e, n_s) == (1, 0, 0, 0):
                if n_p == 1:
                    allowed = self.cts_1point_1line(p)
                elif n_p == 2:
                    allowed = self.cts_2point_1line(p)
                else:
                    allowed = self.cts_3point_1line(p)
            elif (n_p, n_l, n_c, n_e, n_s) == (1, 0, 1, 0, 0):
                allowed = self.cts_1point_1circle(p)
            elif (n_p, n_l, n_c, n_e, n_s) == (2, 0, 1, 0, 0):
                allowed = self.cts_2point_1circle(p)
        elif n_l:
            if (n_c, n_e, n_s) == (0, 0, 0):
                if n_l == 1:
                    allowed = self.cts_1line(p)
                elif n_l == 2:
                    allowed = self.cts_2line(p)
                else:
                    allowed = self.cts_3line()
            elif (n_l, n_c, n_e, n_s) == (1, 1, 0, 0):
                allowed = self.cts_1line_1circle(p)
            elif (n_l, n_c, n_e, n_s) == (1, 2, 0, 0):
                allowed = self.cts_1line_2circle()
        elif n_c:
            if (n_e, n_s) == (0, 0):
                if n_c == 1:
                    allowed = self.cts_1circle(p)
                elif n_c == 2:
                    allowed = self.cts_2circle(p)
                else:
                    allowed = self.cts_3circle()
        elif n_e:
            if n_e == 1 and n_s == 0:
                allowed = True
            elif n_s == 0:
                allowed = self.cts_2ellipse()
        return allowed

    def cts_1point(self, p):
        a = self.picks[POINT][0]
        allowed = False
        if self.mode == FIRST:
            allowed = True
            if a.geo == I.ROOT:
                return True
            self.restart("Add 'Distance to origin' constraint")
            self.create_distance(a.geo, a.pos, I.ROOT, I.START, p)
        if self.mode == SECOND:
            self.restart("Add lock constraint")
            self.special = BLOCK
            self.create_distance_xy("DistanceX", a.geo, a.pos, I.ROOT, I.START, p)
            self.create_distance_xy("DistanceY", a.geo, a.pos, I.ROOT, I.START, p)
            self.mode = RESET
        return allowed

    def cts_2point(self, p):
        a, b = self.picks[POINT][:2]
        allowed = False
        if self.mode == FIRST:
            self.restart("Add Distance constraint")
            self.create_distance(a.geo, a.pos, b.geo, b.pos, p)
            allowed = True
        if self.mode == SECOND:
            self.restart("Add 'Horizontal' constraints")
            self.create_horizontal(a.geo, a.pos, b.geo, b.pos)
        if self.mode == THIRD:
            self.restart("Add 'Vertical' constraints")
            self.create_vertical(a.geo, a.pos, b.geo, b.pos)
            self.mode = RESET
        return allowed

    def cts_1point_1line(self, p):
        a, ln = self.picks[POINT][0], self.picks[LINE][0]
        allowed = False
        if self.mode == FIRST:
            self.diam_watch = [(ln.geo, a.geo, a.pos)]
            self.diam_now = self.across_centerline(ln.geo, a.geo, a.pos, p)
            if self.diam_now:
                self.restart("Add diameter dimension")
                self.create_diameter(ln.geo, a.geo, a.pos, p)
            else:
                self.restart("Add point to line Distance constraint")
                self.create_distance(a.geo, a.pos, ln.geo, ln.pos, p)
            allowed = True
        if self.mode == SECOND:
            self.restart("Add Symmetry constraint")
            self.create_symmetry(ln.geo, I.START, ln.geo, I.END, a.geo, a.pos)
            self.mode = RESET
        return allowed

    def cts_3point(self):
        pts = self.picks[POINT]
        allowed = False
        arc = self._arc_of_points(pts)
        if arc is not None and self.mode == FIRST:

            self.restart("Add angle constraint")
            self.create_arc_angle(arc, pts[-1].at)
            return True
        if self.mode == FIRST:
            self.restart("Add 'Horizontal' constraints")
            for a, b in zip(pts, pts[1:]):
                self.create_horizontal(a.geo, a.pos, b.geo, b.pos)
            allowed = True
        if self.mode == SECOND:
            self.restart("Add 'Vertical' constraints")
            for a, b in zip(pts, pts[1:]):
                self.create_vertical(a.geo, a.pos, b.geo, b.pos)
        if self.mode == THIRD:
            self.restart("Add Symmetry constraints")
            self.create_symmetry(pts[0].geo, pts[0].pos, pts[1].geo, pts[1].pos, pts[2].geo, pts[2].pos)
            self.mode = RESET
        return allowed

    def cts_4point(self):
        pts = self.picks[POINT]
        allowed = False
        if self.mode == FIRST:
            self.restart("Add 'Horizontal' constraints")
            for a, b in zip(pts, pts[1:]):
                self.create_horizontal(a.geo, a.pos, b.geo, b.pos)
            allowed = True
        if self.mode == SECOND:
            self.restart("Add 'Vertical' constraints")
            for a, b in zip(pts, pts[1:]):
                self.create_vertical(a.geo, a.pos, b.geo, b.pos)
            self.mode = RESET
        return allowed

    def cts_2point_1line(self, p):
        pts, ln = self.picks[POINT], self.picks[LINE][0]
        allowed = False
        if self.mode == FIRST:
            self.restart("Add Symmetry constraint")
            self.create_symmetry(pts[0].geo, pts[0].pos, pts[1].geo, pts[1].pos, ln.geo, ln.pos)
            allowed = True
        if self.mode == SECOND:
            self.restart("Add Distance constraints")
            for a in pts:
                self.create_distance(a.geo, a.pos, ln.geo, ln.pos, p)
            self.mode = RESET
        return allowed

    def cts_3point_1line(self, p):
        pts, ln = self.picks[POINT], self.picks[LINE][0]
        if self.mode == FIRST:
            self.restart("Add Distance constraints")
            for a in pts:
                self.create_distance(a.geo, a.pos, ln.geo, ln.pos, p)
            self.mode = RESET
            return True
        return False

    def cts_1point_1circle(self, p):
        a, c = self.picks[POINT][0], self.picks[CIRCLE][0]
        if self.mode == FIRST:
            self.restart("Add length constraint")
            self.create_arc_distance(a, c, p)
            self.mode = RESET
            return True
        return False

    def cts_2point_1circle(self, p):
        ""
        pts, c = self.picks[POINT], self.picks[CIRCLE][0]
        ends = {(q.geo, q.pos) for q in pts}
        if self.mode == FIRST and ends == {(c.geo, I.START), (c.geo, I.END)} \
                and is_arc(geometry_of(self.sketch, c.geo)):
            self.restart("Add arc length constraint")
            self.create_arc_length(c.geo, p)
            self.mode = RESET
            return True
        return False

    def cts_1line(self, p):
        ln = self.picks[LINE][0]
        if ln.geo in (I.H_AXIS, I.V_AXIS):
            return True  # an axis can be picked, but has no length
        allowed = False
        if self.mode == FIRST:
            self.restart("Add length constraint")
            self.create_distance(ln.geo, I.START, ln.geo, I.END, p)
            allowed = True
        if self.mode == SECOND:
            if self.has_hv_block(ln.geo):
                self.mode = RESET
            else:
                self.restart("Add Horizontal constraint")
                self.create_horizontal(ln.geo, I.NONE, UNDEF, I.NONE)
        if self.mode == THIRD:
            self.restart("Add Vertical constraint")
            self.create_vertical(ln.geo, I.NONE, UNDEF, I.NONE)
        if self.mode == FOURTH:
            self.restart("Add Block constraint")
            self.add_relation(Sketcher.Constraint("Block", ln.geo))
            self.mode = RESET
        return allowed

    def cts_2line(self, p):
        a, b = self.picks[LINE][:2]
        allowed = False
        if self.mode == FIRST:
            self.restart("Add Angle constraint")
            self.create_angle(a.geo, b.geo, p)
            allowed = True
        if self.mode == SECOND:
            if not any(x.geo in (I.H_AXIS, I.V_AXIS) for x in (a, b)):
                self.restart("Add Equality constraint")
                self.create_equality(a.geo, b.geo)
            self.mode = RESET
        return allowed

    def cts_3line(self):
        lns = self.picks[LINE]
        if self.mode == FIRST:
            self.restart("Add Equality constraints")
            for a, b in zip(lns, lns[1:]):
                self.create_equality(a.geo, b.geo)
            self.mode = RESET
            return True
        return False

    def cts_1line_1circle(self, p):
        ln, c = self.picks[LINE][0], self.picks[CIRCLE][0]
        if self.mode == FIRST:
            self.restart("Add length constraint")
            self.create_arc_distance(ln, c, p)
            self.mode = RESET
            return True
        return False

    def cts_1line_2circle(self):
        ln, cs = self.picks[LINE][0], self.picks[CIRCLE]
        if self.mode == FIRST:
            self.restart("Add Symmetry constraints")
            self.create_symmetry(cs[0].geo, I.MID, cs[1].geo, I.MID, ln.geo, ln.pos)
            self.mode = RESET
            return True
        return False

    def cts_1circle(self, p):
        geo = self.picks[CIRCLE][0].geo
        g = geometry_of(self.sketch, geo)
        allowed = False
        # (the C++ asks the solver whether the arc's radius is still free; here the radius comes first)
        if self.mode == FIRST:
            self.restart("Add radius constraint")
            self.create_radius_diameter(geo, p, True)
            allowed = True
        if self.mode == SECOND:
            self.restart("Add radius constraint")
            self.create_radius_diameter(geo, p, False)
            if not is_arc(g):
                self.mode = RESET
        if self.mode == THIRD:
            self.restart("Add arc angle constraint")
            self.create_arc_angle(geo, p)
        if self.mode == FOURTH:
            self.restart("Add arc length constraint")
            self.create_arc_length(geo, p)
            self.mode = RESET
        return allowed

    def cts_2circle(self, p):
        a, b = self.picks[CIRCLE][:2]
        allowed = False
        if self.mode == FIRST:
            self.restart("Add length constraint")
            if a.shift != b.shift:
                # Shift at one of them: from the other's centre to its near (Min) or far (Max) edge
                other, edge = (b, a) if a.shift else (a, b)
                self.create_arc_distance(Pick(other.geo, I.MID, other.name), edge, p)
            elif a.shift:
                # Shift at both: edge to edge, each side its near (Min) or far (Max) edge
                self.create_distance(a.geo, a.pos, b.geo, b.pos, p)
                self.circle_sides(a, b)
            else:
                self.create_centre_distance(a.geo, I.MID, b.geo, I.MID, p)
            allowed = True
        if self.mode == SECOND:
            self.restart("Add concentric and length constraint")
            if not self.create_coincidence(a.geo, I.MID, b.geo, I.MID):
                self.mode = THIRD
            else:
                self.create_distance(a.geo, a.pos, b.geo, b.pos, p)
        if self.mode == THIRD:
            self.restart("Add Equality constraint")
            self.create_equality(a.geo, b.geo)
            self.mode = RESET
        return allowed

    def cts_3circle(self):
        cs = self.picks[CIRCLE]
        if self.mode == FIRST:
            self.restart("Add Equality constraint")
            for a, b in zip(cs, cs[1:]):
                self.create_equality(a.geo, b.geo)
            self.mode = RESET
            return True
        return False

    def cts_2ellipse(self):
        es = self.picks[ELLIPSE]
        types = {type(geometry_of(self.sketch, e.geo)) for e in es}
        if len(types) == 1:
            self.restart("Add Equality constraint")
            for e in es[1:]:
                self.create_equality(es[0].geo, e.geo)
            return True
        return False

    # --- making the constraints -----------------------------------------------------------------------
    def add_relation(self, constraint):
        self.sketch.addConstraint(constraint)
        self.indexes.append(self.sketch.ConstraintCount - 1)
        self.sketch.solve()

    def create_distance(self, geo1, pos1, geo2, pos2, p):
        if geo1 == geo2 or (pos1 != I.NONE and pos2 != I.NONE):
            self.special = LINE_OR_POINTS_DISTANCE
        if same_place(self.sketch, geo1, pos1, geo2, pos2):
            return
        made = distance_value(self.sketch, geo1, pos1, geo2, pos2)
        if made is None or abs(made[0]) < 1e-7:
            return      # a point on the curve, or touching curves: no 0 dimension (as same_place)
        self.sketch.addConstraint(made[1])
        self.finish_dimension(geo1, geo2, p)

    def create_centre_distance(self, geo1, pos1, geo2, pos2, p):
        """A distance between two points (circle centres among them), without the horizontal and
        vertical switching a plain two-point distance has."""
        p1, p2 = self.sketch.getPoint(geo1, pos1), self.sketch.getPoint(geo2, pos2)
        if (p2 - p1).Length < 1e-7:
            return
        self.special = LINE_OR_POINTS_DISTANCE
        self.sketch.addConstraint(Sketcher.Constraint("Distance", geo1, pos1, geo2, pos2, (p2 - p1).Length))
        self.finish_dimension(geo1, geo2, p)

    def circle_sides(self, a, b):
        ""

        sk = self.sketch
        if not self.indexes:
            return
        index = self.indexes[-1]
        c = sk.Constraints[index]
        ga, gb = geometry_of(sk, a.geo), geometry_of(sk, b.geo)

        def far(pick, g, other):
            at = V(pick.at[0], pick.at[1], 0) if pick.at else g.Center
            return (at - g.Center).dot(g.Center - other.Center) > 0
        fa, fb = far(a, ga, gb), far(b, gb, ga)
        first, second = (fa, fb) if c.First == a.geo else (fb, fa)
        values = {"arc": "Max" if first else "Min", "arc2": "Max" if second else "Min"}
        if True:
            try:
                from .. import dimensionpm
                dimensionpm.set_style(sk, index, **values)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: arc Max: %s\n" % error)

    def create_arc_distance(self, other, c, p):
        ""


        sk = self.sketch
        g = geometry_of(sk, c.geo)
        if not c.shift:
            if other.pos != I.NONE:
                self.create_centre_distance(other.geo, other.pos, c.geo, I.MID, p)
            else:
                ln = geometry_of(sk, other.geo)
                value = point_line_distance((g.Center.x, g.Center.y), ln)
                sk.addConstraint(Sketcher.Constraint("Distance", c.geo, I.MID, other.geo, value))
                self.finish_dimension(c.geo, other.geo, p)
            return
        if other.pos != I.NONE:
            q = sk.getPoint(other.geo, other.pos)
        else:
            ln = geometry_of(sk, other.geo)
            d = ln.EndPoint - ln.StartPoint
            d.normalize()
            q = ln.StartPoint + d * (g.Center - ln.StartPoint).dot(d)
        at = V(c.at[0], c.at[1], 0) if c.at else g.Center
        far = (at - g.Center).dot(g.Center - q) > 0
        if other.pos != I.NONE:
            self.create_distance(other.geo, other.pos, c.geo, c.pos, p)
        else:
            self.create_distance(c.geo, c.pos, other.geo, other.pos, p)
        if far and self.indexes:
            try:
                from .. import dimensionpm
                dimensionpm.set_style(sk, self.indexes[-1], arc="Max")
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: arc Max: %s\n" % error)

    def update_angle_quadrant(self, p):
        ""
        sk = self.sketch
        index = self.indexes[-1]
        try:
            c = sk.Constraints[index]
        except Exception:
            return
        if c.Type != "Angle":
            return
        found = angle_for_pointer(sk, self.angle_lines[0], self.angle_lines[1], p)
        if found is None:
            return
        g1, p1, g2, p2, angle = found
        if (c.First, c.FirstPos, c.Second, c.SecondPos) == (g1, p1, g2, p2):
            return
        lines = self.angle_lines
        self.restart("Add Angle constraint")
        self.angle_lines = lines
        sk.addConstraint(Sketcher.Constraint("Angle", g1, p1, g2, p2, angle))
        self.finish_dimension(g1, g2, p)

    def create_distance_xy(self, type, geo1, pos1, geo2, pos2, p):
        p1, p2 = self.sketch.getPoint(geo1, pos1), self.sketch.getPoint(geo2, pos2)
        value = (p2.y - p1.y) if type == "DistanceY" else (p2.x - p1.x)
        if value < -CONFUSION:
            geo1, geo2 = geo2, geo1
            pos1, pos2 = pos2, pos1
            value = -value
        self.sketch.addConstraint(Sketcher.Constraint(type, geo1, pos1, geo2, pos2, value))
        self.finish_dimension(geo1, geo2, p)

    def create_radius_diameter(self, geo, p, first):
        g = geometry_of(self.sketch, geo)
        if g is None or not (is_circle(g) or is_arc(g)):
            return
        grp = App.ParamGet(DIMENSIONING_GROUP)
        diameter_on, radius_on = grp.GetBool("DimensioningDiameter", True), grp.GetBool("DimensioningRadius", True)
        circle = is_circle(g)
        if (first and radius_on and not diameter_on) or (not first and not radius_on and diameter_on) \
                or (first and radius_on and diameter_on and not circle) \
                or (not first and radius_on and diameter_on and circle):
            self.sketch.addConstraint(Sketcher.Constraint("Radius", geo, g.Radius))
        else:
            self.sketch.addConstraint(Sketcher.Constraint("Diameter", geo, 2 * g.Radius))
        self.finish_dimension(geo, UNDEF, p)

    def create_coincidence(self, geo1, pos1, geo2, pos2):
        if both_fixed(self.sketch, geo1, geo2):
            return False
        from . import topology
        if geo1 != geo2 and not topology.points_coincident(self.sketch, geo1, pos1, geo2, pos2):
            self.add_relation(Sketcher.Constraint("Coincident", geo1, pos1, geo2, pos2))
            return True
        return False

    def create_equality(self, geo1, geo2):
        if both_fixed(self.sketch, geo1, geo2):
            return
        g1, g2 = geometry_of(self.sketch, geo1), geometry_of(self.sketch, geo2)
        circles = (Part.Circle, Part.ArcOfCircle)
        ellipses = (Part.Ellipse, Part.ArcOfEllipse)
        if (is_line(g1) and not is_line(g2)) or (isinstance(g1, circles) and not isinstance(g2, circles)) \
                or (isinstance(g1, ellipses) and not isinstance(g2, ellipses)) \
                or (isinstance(g1, Part.ArcOfHyperbola) and not isinstance(g2, Part.ArcOfHyperbola)) \
                or (isinstance(g1, Part.ArcOfParabola) and not isinstance(g2, Part.ArcOfParabola)):
            MB.status("Wrong selection: select two or more edges of similar type")
            return
        self.add_relation(Sketcher.Constraint("Equal", geo1, geo2))

    def create_angle(self, geo1, geo2, p):
        found = calculate_angle(self.sketch, geo1, geo2)
        if found is None:
            return
        g1, p1, g2, p2, angle = found
        if angle == 0.0:
            # parallel lines: a distance instead
            lns = self.picks[LINE]
            self.diam_watch = [(lns[0].geo, lns[1].geo, I.START), (lns[1].geo, lns[0].geo, I.START)]
            self.diam_now = any(self.across_centerline(c_, g_, q_, p) for c_, g_, q_ in self.diam_watch)
            for cl, other in ((lns[0], lns[1]), (lns[1], lns[0])):
                if self.across_centerline(cl.geo, other.geo, I.START, p):
                    self.restart("Add diameter dimension")
                    self.create_diameter(cl.geo, other.geo, I.START, p)
                    return
            self.restart("Add Distance constraint")
            self.create_distance(lns[1].geo, I.START, lns[0].geo, lns[0].pos, p)
            return
        at = angle_for_pointer(self.sketch, geo1, geo2, p)
        if at is not None:
            g1, p1, g2, p2, angle = at
        self.sketch.addConstraint(Sketcher.Constraint("Angle", g1, p1, g2, p2, angle))
        self.finish_dimension(g1, g2, p)
        self.angle_lines = (geo1, geo2)

    def across_centerline(self, cl, geo, pos, p):
        ""


        if cl < 0 or geo == cl:
            return False
        try:
            g = self.sketch.Geometry[cl]
            if not is_line(g) or not self.sketch.getConstruction(cl):
                return False
            q = self.sketch.getPoint(geo, pos)
        except Exception:
            return False
        a, b = g.StartPoint, g.EndPoint
        d = b - a
        if d.Length < CONFUSION:
            return False
        side = lambda v: d.x * (v.y - a.y) - d.y * (v.x - a.x)
        sq, sp = side(q), side(V(p[0], p[1], 0))
        return abs(sq) > CONFUSION * d.Length and sq * sp < 0

    def create_diameter(self, cl, geo, pos, p):
        """The diameter across centerline cl of point (geo, pos): FreeCAD measures it to a
        construction point mirrored over the centerline (held Symmetric about it)."""
        import Part
        g = self.sketch.Geometry[cl]
        a, b = g.StartPoint, g.EndPoint
        q = self.sketch.getPoint(geo, pos)
        d = b - a
        foot = a + d * ((q - a).dot(d) / d.dot(d))
        m = foot * 2 - q
        width = (m - q).Length
        mirror = self.sketch.addGeometry(Part.Point(m), True)
        self.sketch.addConstraint(Sketcher.Constraint("Symmetric", geo, pos, mirror, 1, cl))
        self.sketch.addConstraint(Sketcher.Constraint("Distance", geo, pos, mirror, 1, width))
        self.diameter_across = (cl, mirror)
        self.finish_dimension(geo, mirror, p)

    def create_arc_length(self, geo, p):
        g = geometry_of(self.sketch, geo)
        if not is_arc(g):
            return
        self.sketch.addConstraint(Sketcher.Constraint("Distance", geo, (g.LastParameter - g.FirstParameter) * g.Radius))
        self.finish_dimension(geo, UNDEF, p)

    def create_arc_angle(self, geo, p):
        g = geometry_of(self.sketch, geo)
        if not is_arc(g):
            return
        self.sketch.addConstraint(Sketcher.Constraint("Angle", geo, g.LastParameter - g.FirstParameter))
        self.finish_dimension(geo, UNDEF, p)

    def create_horizontal(self, geo1, pos1, geo2, pos2):
        if len(self.picks[LINE]) == 1 and pos1 == I.NONE:
            g = geometry_of(self.sketch, geo1)
            if not is_line(g):
                return
            a, b = g.StartPoint, g.EndPoint
            if abs(a.x - b.x) < CONFUSION:  # an upright line would collapse: lay it down first
                b = a + V((b - a).Length, 0, 0)
                self.sketch.moveGeometry(geo1, I.END, b, False)
            self.add_relation(Sketcher.Constraint("Horizontal", geo1))
            return
        if both_fixed(self.sketch, geo1, geo2):
            return
        self.add_relation(Sketcher.Constraint("Horizontal", geo1, pos1, geo2, pos2))

    def create_vertical(self, geo1, pos1, geo2, pos2):
        if len(self.picks[LINE]) == 1 and pos1 == I.NONE:
            g = geometry_of(self.sketch, geo1)
            if not is_line(g):
                return
            a, b = g.StartPoint, g.EndPoint
            if abs(a.y - b.y) < CONFUSION:
                b = a + V(0, (b - a).Length, 0)
                self.sketch.moveGeometry(geo1, I.END, b, False)
            self.add_relation(Sketcher.Constraint("Vertical", geo1))
            return
        if both_fixed(self.sketch, geo1, geo2):
            return
        self.add_relation(Sketcher.Constraint("Vertical", geo1, pos1, geo2, pos2))

    def create_symmetry(self, geo1, pos1, geo2, pos2, geo3, pos3):
        if geo3 == UNDEF or both_fixed(self.sketch, geo1, geo2) and is_fixed(self.sketch, geo3):
            return
        if pos3 == I.NONE:
            self.add_relation(Sketcher.Constraint("Symmetric", geo1, pos1, geo2, pos2, geo3))
        else:
            self.add_relation(Sketcher.Constraint("Symmetric", geo1, pos1, geo2, pos2, geo3, pos3))

    def has_hv_block(self, geo):
        return any(c.Type in ("Horizontal", "Vertical", "Block") and c.First == geo and c.Second == UNDEF
                   for c in self.sketch.Constraints)

    # --- after a dimension was added -----------------------------------------------------------------
    def finish_dimension(self, geo1, geo2, p):
        sk = self.sketch
        index = sk.ConstraintCount - 1
        fixed = is_fixed(sk, geo1) if geo2 == UNDEF else both_fixed(sk, geo1, geo2)
        if fixed:
            sk.setDriving(index, False)
        elif self.make_driven_if_over_defining(index):
            self.over_defining.append(index)
        self.indexes.append(index)
        sk.solve()
        self.place(index, p, offset=False)

    def make_driven_if_over_defining(self, index):
        """makeDrivenIfOverDefining (06/12b): a dimension the solver reports redundant or
        conflicting becomes driven while it is placed; with the prompt off and DrivenWhenOverDefining
        off it stays driving."""
        prompt = MB.prompt_driven_state()
        if not prompt and not MB.driven_when_over_defining():
            return False
        sk = self.sketch
        c = sk.Constraints[index]
        if c.Type not in DIMENSIONAL or not c.Driving:
            return False
        sk.solve()
        listed = index + 1
        if listed not in sk.RedundantConstraints and listed not in sk.ConflictingConstraints \
                and listed not in getattr(sk, "PartiallyRedundantConstraints", []):
            return False
        sk.setDriving(index, False)
        if not prompt:
            MB.status("Dimension added as driven: a driving dimension would over-define the sketch")
        return True

    def view_offset(self):
        """moveConstraint's OffsetConstraint: 1 % of the view's width plus height."""
        box = self._view_box()
        if box is None:
            return 0.0
        w, h = (box[2] - box[0]) / 1.2, (box[3] - box[1]) / 1.2
        return (w + h) * 0.01

    def place(self, index, p, offset=True):
        sk = self.sketch
        try:
            c = sk.Constraints[index]
        except Exception:
            return
        found = label_for(sk, c, p, self.view_offset() if offset else 0.0)
        if found is None:
            return
        distance, position = found
        try:
            sk.setLabelDistance(index, distance)
            if position is not None:
                sk.setLabelPosition(index, position)
        except Exception as _fw_err:
            _fw_log("fwsketch/dimension.py:1613", _fw_err)

    def move_constraints(self, p):
        if not self.indexes:
            return
        sk = self.sketch
        last = sk.ConstraintCount - 1
        for index in self.indexes:
            try:
                c = sk.Constraints[index]
            except Exception:
                continue
            if c.Type not in DIMENSIONAL:
                continue
            at = p
            if self.special == BLOCK and self.picks[POINT]:
                a = self.picks[POINT][0]
                q = sk.getPoint(a.geo, a.pos)
                at = (p[0], q.y) if index == last else (q.x, p[1])
            self.place(index, at, offset=True)
        try:
            sk.solve()   # FreeCAD redraws the dimensions on the solver's signal (moveConstraint's draw)
        except Exception as _fw_err:
            _fw_log("fwsketch/dimension.py:1636", _fw_err)

    def update_distance_type(self, p):
        sk = self.sketch
        if not self.indexes:
            return
        current = sk.Constraints[sk.ConstraintCount - 1].Type
        pts, lns, cir = self.picks[POINT], self.picks[LINE], self.picks[CIRCLE]
        if cir:
            # a circle's centre with another centre or a point (dimension review 11-19): the two points
            if lns or any(q.shift for q in cir) or len(pts) + len(cir) != 2:
                return
            ends = [(q.geo, q.pos) for q in pts] + [(q.geo, I.MID) for q in cir]
            wanted = self.forced or distance_type_for(point_of(sk, *ends[0]), point_of(sk, *ends[1]), p)
            if wanted is None or wanted == current:
                return
            self.restart("Add Distance constraint" if wanted == "Distance" else "Add %s constraint" % wanted)
            if wanted == "Distance":
                self.create_centre_distance(ends[0][0], ends[0][1], ends[1][0], ends[1][1], p)
            else:
                self.special = LINE_OR_POINTS_DISTANCE
                self.create_distance_xy(wanted, ends[0][0], ends[0][1], ends[1][0], ends[1][1], p)
            return
        if self.forced and len(lns) == 1 and len(pts) == 1:
            # fix286: Horizontal / Vertical Dimension on a line and a point measures the horizontal /

            q = point_of(sk, pts[0].geo, pts[0].pos)
            a, b = point_of(sk, lns[0].geo, I.START), point_of(sk, lns[0].geo, I.END)
            end = I.START if math.hypot(q[0] - a[0], q[1] - a[1]) <= math.hypot(q[0] - b[0], q[1] - b[1]) else I.END
            last = sk.Constraints[sk.ConstraintCount - 1]
            if current == self.forced and pts[0].geo in (last.First, last.Second, getattr(last, "Third", None)):
                return
            self.restart("Add %s constraint" % self.forced)
            self.special = LINE_OR_POINTS_DISTANCE
            self.create_distance_xy(self.forced, pts[0].geo, pts[0].pos, lns[0].geo, end, p)
            return
        if len(lns) == 1:
            pnt1, pnt2 = point_of(sk, lns[0].geo, I.START), point_of(sk, lns[0].geo, I.END)
        elif len(pts) == 1:
            pnt1, pnt2 = point_of(sk, pts[0].geo, pts[0].pos), (0.0, 0.0)
        elif len(pts) >= 2:
            pnt1, pnt2 = point_of(sk, pts[0].geo, pts[0].pos), point_of(sk, pts[1].geo, pts[1].pos)
        else:
            return
        wanted = self.forced or distance_type_for(pnt1, pnt2, p)
        if wanted is None or wanted == current:
            return
        if wanted == "Distance":
            self.restart("Add Distance constraint")
            if len(lns) == 1:
                self.create_distance(lns[0].geo, I.START, lns[0].geo, I.END, p)
            elif len(pts) == 1:
                self.create_distance(pts[0].geo, pts[0].pos, I.ROOT, I.START, p)
            else:
                self.create_distance(pts[0].geo, pts[0].pos, pts[1].geo, pts[1].pos, p)
        else:
            self.restart("Add %s constraint" % wanted)
            self.special = LINE_OR_POINTS_DISTANCE
            if len(lns) == 1:
                self.create_distance_xy(wanted, lns[0].geo, I.START, lns[0].geo, I.END, p)
            elif len(pts) == 1:
                self.create_distance_xy(wanted, pts[0].geo, pts[0].pos, I.ROOT, I.START, p)
            else:
                self.create_distance_xy(wanted, pts[0].geo, pts[0].pos, pts[1].geo, pts[1].pos, p)

    # --- the placing click ------------------------------------------------------------------------------
    def finalize(self):
        """finalizeCommand: settle an over-defining dimension (12b), keep the dimension (06),
        the Modify box (12), then the next one or the end."""
        sk = self.sketch
        if self.aborted():
            self.reset_tool()
            return
        left_driving = []
        for index in self.over_defining:
            choice = MB.settle_over_defining(sk, index)
            if choice == MB.CANCEL:
                self.reset_tool()
                return
            if choice == MB.DRIVING:
                left_driving.append(index)
        show = param_bool(SKETCHER_GROUP, "ShowDialogOnDistanceConstraint", True)
        keep = param_bool(SKETCHER_GROUP, "KeepDimensionOnCancel", True)
        for index in self.indexes:
            try:
                c = sk.Constraints[index]
                self.placed.append((c.Type, c.Value, c.Driving))
            except Exception as _fw_err:
                _fw_log("fwsketch/dimension.py:1696", _fw_err)
        if keep:
            self.commit()
        handled = False
        for index in reversed(self.indexes):
            try:
                c = sk.Constraints[index]
            except Exception:
                continue
            if show and c.Type in DIMENSIONAL and c.Driving and index not in left_driving:
                handled = True
                if keep:
                    self.doc.openTransaction("Modify sketch constraints")
                    self.open = True
                box = MB.ModifyBox(sk, index)
                box.scale_first = True
                box.own_transaction = keep      # its "Modify sketch constraints" step: dropped when untouched
                ok = box.run()
                if box.scaled_by:
                    self.events.append(("scaled", round(box.scaled_by, 6)))
                self.open = False  # the box committed or aborted
                self.events.append(("box", index, ok))
                if not ok:
                    break
        if not handled and not keep:
            self.commit()
        if TB.active() is not self:
            return
        if continuous_mode():
            self.reset_tool()
        else:
            self.end()


def start_dimension(forced=None):
    ""


    gdoc, sketch = TB.edited_sketch()
    names = []
    try:
        for sel in Gui.Selection.getSelectionEx():
            if sel.Object == sketch:
                names.extend(sel.SubElementNames)
    except Exception as _fw_err:
        _fw_log("fwsketch/dimension.py:1738", _fw_err)
    tool = DimensionTool(gdoc, sketch, names)
    tool.forced = forced
    tool.begin()
    return tool
