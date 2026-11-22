# SPDX-License-Identifier: LGPL-2.1-or-later
""










import math

import FreeCAD as App
import Part
import Sketcher

from .vec import sub, add, mul, length, unit
from . import inference as I
from . import geom
from . import relations as R
from .toolbase import SketchTool, fmt_length, fmt_angle, edited_sketch

ARC_ENDS, FLAT_ENDS, THREE_POINT = "arc_ends", "flat_ends", "three_point"
FOURTH = 3
EPS = 1e-9
PI = math.pi


def V(p):
    return App.Vector(p[0], p[1], 0)


def arc_through_three_points(a, b, c):
    """The arc from a to b through c (arcThroughThreePoints): (centre, radius, start angle of a,
    signed sweep from a passing c), None when the three are in a line."""
    d = 2.0 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    size = max(length(sub(b, a)), length(sub(c, a)), length(sub(c, b)))
    if abs(d) < 1e-7 * max(1.0, size):
        return None
    centre = geom.circumcenter(a, b, c)
    if centre is None:
        return None
    radius = length(sub(a, centre))
    start_angle = math.atan2(a[1] - centre[1], a[0] - centre[0])

    def ccw(q):
        angle = math.atan2(q[1] - centre[1], q[0] - centre[0]) - start_angle
        while angle < 0:
            angle += 2 * PI
        while angle >= 2 * PI:
            angle -= 2 * PI
        return angle

    sweep = ccw(b)
    arc_angle = sweep if ccw(c) < sweep else sweep - 2 * PI
    return centre, radius, start_angle, arc_angle


def arc_slot_shape(method, centre, start, end, radius, r, start_angle, end_angle, reversed_):
    """The slot's pieces as (kind, params) in geometry order (createShape): ("arc", centre,
    radius, a0, a1) or ("line", p, q)."""
    pieces = []
    if method in (ARC_ENDS, THREE_POINT):
        pieces.append(("arc", centre, radius + r, start_angle, end_angle))
        pieces.append(("arc", start, r, end_angle if reversed_ else start_angle + PI,
                       end_angle + PI if reversed_ else start_angle + 2 * PI))
        pieces.append(("arc", end, r, start_angle + PI if reversed_ else end_angle,
                       start_angle + 2 * PI if reversed_ else end_angle + PI))
        if radius - r > EPS:
            pieces.append(("arc", centre, radius - r, start_angle, end_angle))
        return pieces
    p11 = add(centre, (radius * math.cos(start_angle), radius * math.sin(start_angle)))
    p12 = add(centre, (radius * math.cos(end_angle), radius * math.sin(end_angle)))
    pieces.append(("arc", centre, radius, start_angle, end_angle))
    if r > EPS:
        p21 = add(centre, (r * math.cos(start_angle), r * math.sin(start_angle)))
        p22 = add(centre, (r * math.cos(end_angle), r * math.sin(end_angle)))
        pieces.append(("line", p11, p21))
        pieces.append(("line", p12, p22))
        pieces.append(("arc", centre, r, start_angle, end_angle))   # last, so it may be left out
    else:
        pieces.append(("line", p11, centre))
        pieces.append(("line", p12, centre))
    return pieces


def piece_points(piece):
    if piece[0] == "arc":
        _, c, rad, a0, a1 = piece
        return geom.arc_points(c, rad, a0, a1 - a0)
    return [piece[1], piece[2]]


def add_arc_slot(sketch, method, pieces, reversed_, construction=False, add_geometry=None):
    """Write the pieces and the slot's own relations; returns the first geo index."""
    add_geometry = add_geometry or (lambda g, c: sketch.addGeometry(g, c))
    first = None
    for piece in pieces:
        if piece[0] == "arc":
            _, c, rad, a0, a1 = piece
            g = Part.ArcOfCircle(Part.Circle(V(c), App.Vector(0, 0, 1), rad), a0, a1)
        else:
            g = Part.LineSegment(V(piece[1]), V(piece[2]))
        geo = add_geometry(g, construction)
        first = geo if first is None else first
    C = Sketcher.Constraint
    cs = []         # one add for all: each add solves and redraws the whole sketch (review 1119 perf2)
    if method in (ARC_ENDS, THREE_POINT):
        all_arcs = len(pieces) == 4
        pos1 = I.START if reversed_ else I.END
        pos2 = I.END if reversed_ else I.START
        if all_arcs:
            cs.append(C("Coincident", first, I.MID, first + 3, I.MID))
            cs.append(C("Tangent", first + 3, pos1, first + 2, pos1))
            cs.append(C("Tangent", first + 3, pos2, first + 1, pos2))
        else:
            cs.append(C("Coincident", first, I.MID, first + 1, pos2))
            cs.append(C("Coincident", first, I.MID, first + 2, pos1))
        cs.append(C("Tangent", first, pos1, first + 2, pos2))
        cs.append(C("Tangent", first, pos2, first + 1, pos1))
    else:
        all_geos = len(pieces) == 4
        cs.append(C("Perpendicular", first, first + 1))
        cs.append(C("Perpendicular", first, first + 2))
        cs.append(C("Coincident", first, I.START, first + 1, I.START))
        cs.append(C("Coincident", first, I.END, first + 2, I.START))
        if all_geos:
            cs.append(C("Coincident", first, I.MID, first + 3, I.MID))
            cs.append(C("Coincident", first + 3, I.START, first + 1, I.END))
            cs.append(C("Coincident", first + 3, I.END, first + 2, I.END))
        else:
            cs.append(C("Coincident", first, I.MID, first + 1, I.END))
            cs.append(C("Coincident", first, I.MID, first + 2, I.END))
    sketch.addConstraint(cs)
    return first


def drop_redundant(sketch, since):
    """With the centre arc in, a reversed slot's own concentric relation (the first one it adds,
    at index since) is implied: take it out when the solver finds the set redundant. The solver
    does not always name that one, so it is the one taken out, and only when that clears it."""
    sketch.solve()
    if not list(sketch.RedundantConstraints):
        return
    c = sketch.Constraints[since]
    if c.Type != "Coincident":
        return
    sketch.delConstraint(since)
    sketch.solve()
    if list(sketch.RedundantConstraints):
        sketch.addConstraint(c)      # not that: put it back as it was
        sketch.solve()


def add_centre_arc(sketch, pieces, first, add_geometry=None, since=None):
    ""

    add_geometry = add_geometry or (lambda g, c: sketch.addGeometry(g, c))
    _, c, outer, a0, a1 = pieces[0]
    r = pieces[1][2]
    rc = outer - r
    if rc <= EPS:
        return None
    g = add_geometry(Part.ArcOfCircle(Part.Circle(V(c), App.Vector(0, 0, 1), rc), a0, a1), True)
    C = Sketcher.Constraint
    cs = [C("Coincident", g, I.MID, first, I.MID)]     # one add: each add solves and redraws (review 1119 perf2)
    ends = {}
    for cap in (first + 1, first + 2):
        q = sketch.Geometry[cap].Center
        ends[cap] = I.START if (sketch.getPoint(g, I.START) - q).Length <= (sketch.getPoint(g, I.END) - q).Length else I.END
    # one end on a hidden line from the slot centre to its cap centre, not Coincident with it: the
    # cap centres are already as far from the slot centre, so a second Coincident is one equation
    # too many (partially redundant; every solve of the sketch about 0.1 s slower, review 1119)
    from . import helpers
    line, held = helpers.slot_centre_line(sketch, (first, I.MID), first + 1)
    if line is not None:
        cs.append(C("PointOnObject", g, ends[first + 1], line))
    else:
        cs.append(C("Coincident", g, ends[first + 1], first + 1, I.MID))
    cs.append(C("Coincident", g, ends[first + 2], first + 2, I.MID))
    sketch.addConstraint(cs)
    if line is not None:
        helpers.hide_helper_relations(sketch, line)
    if since is not None:
        drop_redundant(sketch, since)    # leaves the sketch solved (review 1119 perf3: one solve less)
    else:
        sketch.solve()
    if list(sketch.RedundantConstraints) or list(sketch.ConflictingConstraints):
        sketch.delGeometries(sorted([g] + ([line] if line is not None else [])))   # rather no centre arc than a slot the solver complains about
        sketch.solve()
        return None
    R.mark_solved(sketch)
    return g


def add_arc_slot_dimensions(sketch, first, centre_arc):
    """The Slot page's Add dimensions on an arc slot: the centre arc's radius and the slot width."""
    try:
        if centre_arc is not None:
            sketch.addConstraint(Sketcher.Constraint("Radius", centre_arc, sketch.Geometry[centre_arc].Radius))
        cap = sketch.Geometry[first + 1]
        sketch.addConstraint(Sketcher.Constraint("Distance", first + 1, I.START, first + 1, I.END, 2 * cap.Radius))
    except Exception as e:
        App.Console.PrintLog("FreeCAD arc slot dimensions: %s\n" % e)


class ArcSlotTool(SketchTool):
    def __init__(self, gdoc, sketch, method=ARC_ENDS):
        super().__init__(gdoc, sketch)
        self.method = method
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Create_RectangleSlot" if self.method == FLAT_ENDS else "Sketcher_Pointer_Create_ArcSlot"

    def title(self):
        return {ARC_ENDS: "Centerpoint Arc Slot", FLAT_ENDS: "Flat Ends Arc Slot",
                THREE_POINT: "3 Point Arc Slot"}[self.method]

    def reset(self):
        super().reset()
        self.centre = None
        self.start = None        # on the arc: the first cap's centre
        self.end_point = None          # the second cap's centre
        self.radius = 0.0        # of the arc through the caps' centres
        self.r = 0.0             # the caps' radius (half the width)
        self.start_angle = 0.0
        self.start_angle_backup = 0.0
        self.end_angle = 0.0
        self.arc_angle = 0.0
        self.reversed = False
        self.pieces = []
        self.sug = [[], [], []]

    # --- the pointer ---------------------------------------------------------------------------
    def on_move(self, p, px):
        if self.state == self.FIRST:
            self.snapper.set_reference(None)
            d = self.snap(p, px)
            self.preview([])
            self.readout(d.position, "")
            self.sug[0] = self.seek(d.position, (0.0, 0.0))
            return self.sug[0]
        if self.method == THREE_POINT:
            return self._move_three_point(p, px)
        return self._move_centre(p, px)

    def _move_centre(self, p, px):
        if self.state in (self.SECOND, self.THIRD):
            self.snapper.set_reference(self.centre)
            d = self.snap(p, px, allow_angle=True)
        else:
            self.snapper.set_reference(None)
            d = self.snap(p, px, allow_angle=False)
        pos = d.position
        if self.state == self.SECOND:
            self.start = pos
            self.start_angle = math.atan2(pos[1] - self.centre[1], pos[0] - self.centre[0])
            self.start_angle_backup = self.start_angle
            self.radius = length(sub(pos, self.centre))
            if self.radius > EPS:
                self.preview([geom.circle_points(self.centre, self.radius)], construction=[[self.centre, pos]],
                             points=[self.centre])
            else:
                self.preview([])
            self.readout(pos, fmt_length(self.radius))
            self.sug[1] = self.seek(pos, (0.0, 0.0))
            return self.sug[1]
        if self.state == self.THIRD:
            if self.radius > EPS:
                self.end_point = add(self.centre, mul(unit(sub(pos, self.centre)), self.radius))
            self.r = self.radius / 10.0 if self.method == ARC_ENDS else self.radius * 1.2
            self.start_angle = self.start_angle_backup
            cursor_angle = math.atan2(pos[1] - self.centre[1], pos[0] - self.centre[0])
            self.arc_angle = geom.center_arc_angle(self.start_angle, cursor_angle, self.arc_angle)
            self._reverse_if_necessary()
            self._preview()
            self.readout(pos, fmt_angle(math.degrees(self.arc_angle)))
            # the end sits on the circle from the second click: the snap holds it only when it is
            # there, or the click pulls the radius and drags what is drawn (as the Centerpoint Arc, fix220)
            near = max(2.0 * self.snapper.pixel_size, 1e-6 * max(1.0, self.radius))
            end = getattr(self, "end_point", None)
            self.sug[2] = self.seek(pos, (0.0, 0.0)) if end is not None and length(sub(end, pos)) <= near else []
            return self.sug[2]
        if self.method == ARC_ENDS:
            self.r = min(self.radius, abs(self.radius - length(sub(pos, self.centre))))
        else:
            self.r = length(sub(pos, self.centre))
        self._preview()
        self.readout(pos, "R = %s" % fmt_length(self.r))
        return []

    def _move_three_point(self, p, px):
        if self.state == self.SECOND:
            self.snapper.set_reference(self.start)
            d = self.snap(p, px, allow_angle=True)
        else:
            self.snapper.set_reference(None)
            d = self.snap(p, px, allow_angle=False)
        pos = d.position
        if self.state == self.SECOND:
            self.end_point = pos
            self.radius = length(sub(pos, self.start)) / 2.0   # only to tell a real arc
            self.preview([], construction=[[self.start, pos]] if self.radius > EPS else [])
            self.readout(pos, fmt_length(2.0 * self.radius))
            self.sug[1] = self.seek(pos, (0.0, 0.0))
            return self.sug[1]
        if self.state == self.THIRD:
            found = arc_through_three_points(self.start, self.end_point, pos)
            if found is None:
                self.arc_angle = 0.0
                self.preview([], construction=[[self.start, self.end_point]])
                self.readout(pos, "")
                return []
            self.centre, self.radius, self.start_angle, self.arc_angle = found
            self.start_angle_backup = self.start_angle
            self.r = self.radius / 10.0
            self._reverse_if_necessary()
            self._preview()
            self.readout(pos, "R = %s" % fmt_length(self.radius))
            return []
        self.r = min(self.radius, abs(self.radius - length(sub(pos, self.centre))))
        self._preview()
        self.readout(pos, "R = %s" % fmt_length(self.r))
        return []

    def _reverse_if_necessary(self):
        if self.arc_angle > 0:
            self.end_angle = self.start_angle + self.arc_angle
            self.reversed = False
        else:
            self.end_angle = self.start_angle
            self.start_angle = self.start_angle + self.arc_angle
            self.reversed = True

    def _shape(self):
        if self.radius < EPS or abs(self.arc_angle) < EPS:
            return []
        if self.state == FOURTH and self.method != FLAT_ENDS and self.r < EPS:
            return []
        return arc_slot_shape(self.method, self.centre, self.start, self.end_point, self.radius, self.r,
                              self.start_angle, self.end_angle, self.reversed)

    def _preview(self):
        self.pieces = self._shape()
        points = [self.centre] if self.centre is not None else []
        self.preview([piece_points(piece) for piece in self.pieces], points=points)

    # --- the clicks ----------------------------------------------------------------------------
    def on_click(self, d):
        if self.state == self.FIRST:
            if self.method == THREE_POINT:
                self.start = d.position
            else:
                self.centre = d.position
            self.state = self.SECOND
            return
        if self.state == self.SECOND:
            if self.radius < EPS:
                return
            self.state = self.THIRD
            self.arc_angle = 0.0
            return
        if self.state == self.THIRD:
            if abs(self.arc_angle) < EPS:
                return
            self.state = FOURTH
            return
        if self.method == FLAT_ENDS:
            if abs(self.radius - self.r) < EPS:
                return
        elif self.r < EPS:
            return
        pieces = self._shape()
        if not pieces:
            return
        sugs = [list(s) for s in self.sug]
        method, reversed_, positive = self.method, self.reversed, self.arc_angle > 0
        sk = self.sketch

        def body():
            since = len(sk.Constraints)
            first = add_arc_slot(sk, method, pieces, reversed_, self.construction, self.add_geometry)
            if method in (THREE_POINT, ARC_ENDS):
                centre_arc = add_centre_arc(sk, pieces, first, self.add_geometry, since)
                from .slot import slot_add_dimensions
                if slot_add_dimensions():
                    add_arc_slot_dimensions(sk, first, centre_arc)
            if method == THREE_POINT:
                self.add_relations(sugs[0], first + 1, I.MID)
                self.add_relations(sugs[1], first + 2, I.MID)
            elif method == ARC_ENDS:
                self.add_relations(sugs[0], first, I.MID)
                self.add_relations(sugs[1], first + 1, I.MID)
                self.add_relations(sugs[2], first + 2, I.MID)
            else:
                self.add_relations(sugs[0], first, I.MID)
                self.add_relations(sugs[1], first, I.START if positive else I.END)
                self.add_relations(sugs[2], first, I.END if positive else I.START)
            # solved by transaction() right after (review 1119 perf3: one solve a tool action)
            return first

        first = self.transaction("Add sketch arc slot", body)
        self.select_new(range(first, first + len(pieces)))
        self.finish_or_continue()


def start_arc_slot(method=ARC_ENDS):
    gdoc, sketch = edited_sketch()
    tool = ArcSlotTool(gdoc, sketch, method)
    tool.begin()
    return tool


def start_three_point_arc_slot():
    return start_arc_slot(THREE_POINT)
