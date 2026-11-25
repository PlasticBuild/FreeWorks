# SPDX-License-Identifier: LGPL-2.1-or-later
""










import math

import FreeCAD as App
import Part
import Sketcher

from .vec import sub, add, mul, length
from . import inference as I
from . import relations as R
from . import geom
from .toolbase import SketchTool, fmt_length, fmt_angle, edited_sketch, toward

STRAIGHT, CENTERPOINT = "straight", "centerpoint"
ALIGNMENTS = ("Horizontal", "Vertical", "Parallel", "Perpendicular")
EPS = 1e-9
PI = math.pi


def V(p):
    return App.Vector(p[0], p[1], 0)


def slot_caps(start, second, radius):
    """The two half-circle caps of a straight slot: (centre, start angle, end angle) each, the
    first at start facing away from second (createShape)."""
    angle = math.atan2(second[1] - start[1], second[0] - start[0])
    return ((start, PI / 2 + angle, 1.5 * PI + angle), (second, 1.5 * PI + angle, 2.5 * PI + angle))


def slot_outline(start, second, radius):
    """A closed polyline around the slot for the preview."""
    (c1, a0, a1), (c2, b0, b1) = slot_caps(start, second, radius)
    pts1 = geom.arc_points(c1, radius, a0, a1 - a0)
    pts2 = geom.arc_points(c2, radius, b0, b1 - b0)
    return pts1 + pts2 + [pts1[0]]


def width_radius(start, second, length_, pos):
    """The cap radius for the pointer at pos while the width is picked: its distance to the
    centerline between the end centres, or to the nearer end centre beyond them (SeekThird)."""
    l1 = length(sub(pos, start))
    l2 = length(sub(pos, second))
    if l1 * l1 + length_ * length_ > l2 * l2 and l2 * l2 + length_ * length_ > l1 * l1:
        return abs((second[1] - start[1]) * pos[0] - (second[0] - start[0]) * pos[1]
                   + second[0] * start[1] - second[1] * start[0]) / length_
    return min(l1, l2)


def add_straight_slot(sketch, start, second, radius, centerpoint=None, construction=False, add_geometry=None):
    """Write the slot's geometry and relations into sketch; returns the first geo index. With
    centerpoint, the construction centerline and the centre point follow (indexes first + 4 and
    first + 5)."""
    add_geometry = add_geometry or (lambda g, c: sketch.addGeometry(g, c))
    (c1, a0, a1), (c2, b0, b1) = slot_caps(start, second, radius)
    arc1 = Part.ArcOfCircle(Part.Circle(V(c1), App.Vector(0, 0, 1), radius), a0, a1)
    arc2 = Part.ArcOfCircle(Part.Circle(V(c2), App.Vector(0, 0, 1), radius), b0, b1)
    first = add_geometry(arc1, construction)
    add_geometry(arc2, construction)
    p11, p12 = arc1.StartPoint, arc1.EndPoint
    p21, p22 = arc2.StartPoint, arc2.EndPoint
    add_geometry(Part.LineSegment(p11, p22), construction)
    add_geometry(Part.LineSegment(p12, p21), construction)
    cs = []         # one add for all: each add solves and redraws the whole sketch (review 1119 perf2)
    if centerpoint is not None:
        add_geometry(Part.LineSegment(V(start), V(second)), True)
        add_geometry(Part.Point(V(centerpoint)), True)
        cs.append(Sketcher.Constraint("Coincident", first + 4, I.START, first, I.MID))
        cs.append(Sketcher.Constraint("Coincident", first + 4, I.END, first + 1, I.MID))
        cs.append(Sketcher.Constraint("Symmetric", first + 4, I.START, first + 4, I.END, first + 5, I.START))
    cs.append(Sketcher.Constraint("Tangent", first, I.START, first + 2, I.START))
    cs.append(Sketcher.Constraint("Tangent", first, I.END, first + 3, I.START))
    cs.append(Sketcher.Constraint("Tangent", first + 1, I.END, first + 2, I.END))
    cs.append(Sketcher.Constraint("Tangent", first + 1, I.START, first + 3, I.END))
    cs.append(Sketcher.Constraint("Equal", first, first + 1))
    sketch.addConstraint(cs)
    return first


GENERAL = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"   # the Slot page's options


def slot_add_dimensions():
    try:
        return App.ParamGet(GENERAL).GetBool("SlotAddDimensions", False)
    except Exception:
        return False


def slot_overall():
    try:
        return App.ParamGet(GENERAL).GetString("SlotLength", "Center to Center") == "Overall Length"
    except Exception:
        return False


def add_slot_dimensions(sketch, first, axis, start, second, radius):
    """The Slot page's Add dimensions: the length (Center to Center on the centerline, or Overall
    Length on a construction line through both caps) and the width across the first cap."""
    try:
        if slot_overall():
            d = sub(second, start)
            n = length(d)
            u = (d[0] / n, d[1] / n)
            a = (start[0] - u[0] * radius, start[1] - u[1] * radius)
            b = (second[0] + u[0] * radius, second[1] + u[1] * radius)
            outer = sketch.addGeometry(Part.LineSegment(V(a), V(b)), True)
            cs = [Sketcher.Constraint("PointOnObject", outer, I.START, first)]     # one add for all: each add solves and redraws the whole sketch (review 1119 perf2)
            cs.append(Sketcher.Constraint("PointOnObject", outer, I.END, first + 1))
            cs.append(Sketcher.Constraint("PointOnObject", first, I.MID, outer))
            cs.append(Sketcher.Constraint("PointOnObject", first + 1, I.MID, outer))
            cs.append(Sketcher.Constraint("Distance", outer, n + 2 * radius))
        else:
            cs = [Sketcher.Constraint("Distance", axis, length(sub(second, start)))]
        cs.append(Sketcher.Constraint("Distance", first + 2, I.START, first + 3, I.START, 2 * radius))
        sketch.addConstraint(cs)
    except Exception as e:
        App.Console.PrintLog("FreeCAD slot dimensions: %s\n" % e)


class SlotTool(SketchTool):
    def __init__(self, gdoc, sketch, method=STRAIGHT):
        super().__init__(gdoc, sketch)
        self.method = method
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Slot"

    def title(self):
        return "Centerpoint Straight Slot" if self.method == CENTERPOINT else "Straight Slot"

    def reset(self):
        super().reset()
        self.anchor = None       # the first click: an end centre, or the centre
        self.start = None        # the first cap's centre
        self.second = None       # the second cap's centre
        self.length = 0.0
        self.radius = 1.0
        self.sug = [[], []]

    def on_move(self, p, px):
        if self.state == self.FIRST:
            self.snapper.set_reference(None)
            d = self.snap(p, px)
            self.preview([])
            self.readout(d.position, "")
            self.sug[0] = self.seek(d.position, (0.0, 0.0))
            return self.sug[0]
        if self.state == self.SECOND:
            self.snapper.set_reference(self.anchor)
            d = self.snap(p, px, allow_angle=True)
            pos = d.position
            self.second = pos
            self.start = sub(mul(self.anchor, 2.0), pos) if self.method == CENTERPOINT else self.anchor
            self.length = length(sub(self.second, self.start))
            self.radius = self.length * 0.2   # a fifth of the length until the width is picked
            self._preview()
            seg = sub(pos, self.anchor)
            self.readout(pos, "%s, %s" % (fmt_length(length(seg)),
                                          fmt_angle(math.degrees(math.atan2(seg[1], seg[0])) % 360.0)))
            self.sug[1] = self.seek(pos, seg, R.VERTEX_NO_TANGENCY)
            return self.sug[1]
        self.snapper.set_reference(None)
        d = self.snap(p, px, allow_angle=False)
        if self.length > EPS:
            self.radius = width_radius(self.start, self.second, self.length, d.position)
        self._preview()
        self.readout(d.position, "R = %s" % fmt_length(self.radius))
        return []

    def _preview(self):
        if self.length < EPS or self.radius < EPS:
            self.preview([])
            return
        construction = [[self.start, self.second]] if self.method == CENTERPOINT else []
        points = [self.anchor] if self.method == CENTERPOINT else []
        self.preview([slot_outline(self.start, self.second, self.radius)], construction=construction, points=points)

    # --- on-screen numeric input (fix65) ---------------------------------------------------------
    def numeric_spec(self):
        cur = self.decision.position
        if self.state == self.SECOND:
            k = 0.5 if self.method == CENTERPOINT else 1.0
            return ("Length",), lambda v: toward(self.anchor, cur, v[0] * k) if v[0] else None, ("length",)
        if self.state == self.THIRD and self.length > EPS:
            s0, s1 = self.start, self.second
            mid = mul(add(s0, s1), 0.5)
            ux, uy = (s1[0] - s0[0]) / self.length, (s1[1] - s0[1]) / self.length
            n = (-uy, ux)
            side = -1.0 if (cur[0] - mid[0]) * n[0] + (cur[1] - mid[1]) * n[1] < 0 else 1.0
            return ("Width",), lambda v: add(mid, mul(n, side * v[0] / 2.0)) if v[0] else None, ("width",)
        return None

    def typed_dimensions(self, geos, typed):
        if slot_add_dimensions() or len(geos) < 2:
            return []          # the page's Add dimensions already keeps both
        first = geos[0]
        out = []
        if "length" in typed:
            out.append(Sketcher.Constraint("Distance", first, I.MID, first + 1, I.MID, typed["length"]))
        if "width" in typed:
            out.append(Sketcher.Constraint("Diameter", first, typed["width"]))
        return out

    def on_click(self, d):
        if self.state == self.FIRST:
            self.anchor = d.position
            self.state = self.SECOND
            self.snapper.set_reference(self.anchor)
            return
        if self.state == self.SECOND:
            if self.length < EPS:
                return
            self.state = self.THIRD
            return
        if self.length < EPS or self.radius < EPS:
            return
        sug0, sug1 = list(self.sug[0]), list(self.sug[1])
        # as a line: Horizontal from the origin keeps the H, not the end's relation to the X axis
        R.remove_redundant_hv(self.sketch, sug0, sug1, self.snapper.geometry)
        align = [s for s in sug1 if s.type in ALIGNMENTS]
        rest = [s for s in sug1 if s.type not in ALIGNMENTS]
        start, second, radius = self.start, self.second, self.radius
        centre = self.anchor if self.method == CENTERPOINT else None
        sk = self.sketch

        def body():
            first = add_straight_slot(sk, start, second, radius, centre, self.construction, self.add_geometry)
            if centre is None:

                axis = self.add_geometry(Part.LineSegment(V(start), V(second)), True)
                sk.addConstraint([Sketcher.Constraint("Coincident", axis, I.START, first, I.MID),
                                  Sketcher.Constraint("Coincident", axis, I.END, first + 1, I.MID)])
            else:
                axis = first + 4
            if slot_add_dimensions():
                add_slot_dimensions(sk, first, axis, start, second, radius)
            if centre is not None:
                self.add_relations(sug0, first + 5, I.START)
            else:
                self.add_relations(sug0, first, I.MID)
            self.add_relations(rest, first + 1, I.MID)
            self.add_relations(align, first + 2, I.NONE)   # alignments go to the side, not the cap
            # solved by transaction() right after (review 1119 perf3: one solve a tool action)
            return first

        first = self.transaction("Add slot", body)
        self.select_new(range(first, first + 4))
        self.finish_or_continue()


def start_slot(method=STRAIGHT):
    gdoc, sketch = edited_sketch()
    tool = SlotTool(gdoc, sketch, method)
    tool.begin()
    return tool


def start_centerpoint_slot():
    return start_slot(CENTERPOINT)
