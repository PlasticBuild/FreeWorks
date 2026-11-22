# SPDX-License-Identifier: LGPL-2.1-or-later
""


















import math

import FreeCAD as App
import Part
import Sketcher

from .vec import add, sub, mul, dot, unit, perp, length
from . import inference as I
from . import geom
from .snap import shift_held
from .toolbase import SketchTool, fmt_length, fmt_angle, edited_sketch, GENERAL_GROUP, param_bool, toward, side_of, lines_of

CORNER, CENTER = "corner", "center"
THREE_CORNER, THREE_CENTER, PARALLELOGRAM = "three_corner", "three_center", "parallelogram"
TITLES = {CORNER: "Corner Rectangle", CENTER: "Center Rectangle", THREE_CORNER: "3 Point Corner Rectangle",
          THREE_CENTER: "3 Point Center Rectangle", PARALLELOGRAM: "Parallelogram"}
FROM_CORNERS, FROM_MIDPOINTS = "From Corners", "From Midpoints"
CENTERED = (CENTER, THREE_CENTER)
THREE_CLICKS = (THREE_CORNER, THREE_CENTER, PARALLELOGRAM)


def diagonals():
    ""
    return param_bool(GENERAL_GROUP, "CenterRectangleDiagonals", True)


def start_lines(method):
    """(add construction lines, From Corners / From Midpoints) a new tool starts with."""
    if method in CENTERED:
        on = param_bool(GENERAL_GROUP, "RectangleConstructionLinesCenter", True) and diagonals()
    else:
        on = param_bool(GENERAL_GROUP, "RectangleConstructionLines", False)
    try:
        frm = App.ParamGet(GENERAL_GROUP).GetString("RectangleConstructionLinesFrom", FROM_CORNERS)
    except Exception:
        frm = FROM_CORNERS
    return on, (frm if frm in (FROM_CORNERS, FROM_MIDPOINTS) else FROM_CORNERS)


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


class RectangleTool(SketchTool):
    def __init__(self, gdoc, sketch, method=CORNER):
        super().__init__(gdoc, sketch)
        self.method = method
        self.add_lines, self.lines_from = start_lines(method)
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Create_Box_Center" if self.method in CENTERED else "Sketcher_Pointer_Create_Box"

    def title(self):
        return TITLES.get(self.method, "Corner Rectangle")

    def reset(self):
        super().reset()
        self.anchor = None      # corner1 or the centre
        self.second = None      # the second click of the three-click types
        self.corners = None     # the four corners while the rectangle is placed (the page's Parameters)
        self.center = None
        self.last_pos = None
        self.sug = [[], [], []]

    # --- the four corners for the pointer -------------------------------------------------------
    def _corners(self, pos):
        a, b = self.anchor, self.second
        if self.method == CENTER:
            return geom.rectangle_corners(sub(a, sub(pos, a)), pos)[0]
        if self.method == CORNER:
            return geom.rectangle_corners(a, pos)[0]
        if self.method == THREE_CORNER:
            n = perp(unit(sub(b, a)))
            h = mul(n, dot(sub(pos, b), n))
            return (a, b, add(b, h), add(a, h))
        if self.method == THREE_CENTER:
            u = sub(b, a)                       # centre to the middle of a side
            v = perp(unit(u))
            t = mul(v, dot(sub(pos, b), v))
            return (sub(add(a, u), t), add(add(a, u), t), add(sub(a, u), t), sub(sub(a, u), t))
        return (a, b, pos, add(a, sub(pos, b)))      # parallelogram

    def _square_pos(self, pos):
        """The pointer moved so that the rectangle is a square."""
        a, b = self.anchor, self.second
        if self.method in (CORNER, CENTER):
            dx, dy = pos[0] - a[0], pos[1] - a[1]
            side = max(abs(dx), abs(dy))
            return (a[0] + (side if dx >= 0 else -side), a[1] + (side if dy >= 0 else -side))
        if self.method == THREE_CORNER:
            n = perp(unit(sub(b, a)))
            k = dot(sub(pos, b), n)
            return add(b, mul(n, length(sub(b, a)) * (1.0 if k >= 0 else -1.0)))
        if self.method == THREE_CENTER:
            u = sub(b, a)                       # half the side through the middle picked
            v = perp(unit(u))
            k = dot(sub(pos, b), v)
            return add(b, mul(v, length(u) * (1.0 if k >= 0 else -1.0)))
        if self.method == PARALLELOGRAM:

            d = sub(pos, b)
            if length(d) < 1e-12:
                return pos
            return add(b, mul(unit(d), length(sub(b, a))))
        return pos

    def _lines(self, c):
        """The construction lines for corners c (pairs of points)."""
        if not self.add_lines:
            return []
        if self.lines_from == FROM_MIDPOINTS:
            m = [mul(add(c[i], c[(i + 1) % 4]), 0.5) for i in range(4)]
            return [[m[0], m[2]], [m[1], m[3]]]
        return [[c[0], c[2]], [c[1], c[3]]]

    def on_move(self, p, px):
        if self.state == self.FIRST:
            self.snapper.set_reference(None)
            d = self.snap(p, px)
            self.preview([])
            self.readout(d.position, "")
            self.sug[0] = self.seek(d.position, (0.0, 0.0))
            self.corners = self.center = None
            return self.sug[0]
        three = self.method in THREE_CLICKS
        if three and self.state == self.SECOND:
            # the first side (3 Point Center: the centre to the middle of a side), at any angle
            self.snapper.set_reference(self.anchor)
            d = self.snap(p, px)
            pos = d.position
            if self.method == THREE_CENTER:
                end = sub(self.anchor, sub(pos, self.anchor))
                self.preview([], construction=[[end, pos]], points=[self.anchor])
                self.readout(pos, "L = %s" % fmt_length(2.0 * length(sub(pos, self.anchor))))
            elif self.method == THREE_CORNER:

                self.preview([[self.anchor, pos]])
                rel = sub(pos, self.anchor)
                angle = math.degrees(math.atan2(rel[1], rel[0])) % 360.0
                self.readout(pos, "d = %s, a = %s" % (fmt_length(length(rel)), fmt_angle(angle)))
            else:
                self.preview([[self.anchor, pos]])
                self.readout(pos, "L = %s" % fmt_length(length(sub(pos, self.anchor))))
            self.sug[1] = self.seek(pos, sub(pos, self.anchor))
            self.corners = self.center = None
            return self.sug[1]
        self.snapper.set_reference(self.second if three else self.anchor)
        d = self.snap(p, px, allow_angle=self.method == PARALLELOGRAM)
        pos = d.position

        # Equal relation on two sides); the Parallelogram gets equal sides at its own angle
        self.square = shift_held()
        if self.square:
            pos = self._square_pos(pos)
        self.last_pos = pos
        c = self._corners(pos)
        self.corners = c
        self.center = mul(add(c[0], c[2]), 0.5)
        self.preview([[c[0], c[1], c[2], c[3], c[0]]], construction=self._lines(c),
                     points=[self.center] if self.method in CENTERED else [])
        w, h = length(sub(c[1], c[0])), length(sub(c[2], c[1]))
        if self.method in (CORNER, CENTER):

            self.readout(pos, "x = %s, y = %s" % (fmt_length(w), fmt_length(h)))
        else:
            self.readout(pos, "%s x %s" % (fmt_length(w), fmt_length(h)))
        slot = 2 if three else 1
        self.sug[slot] = self.seek(pos, (0.0, 0.0))
        return self.sug[slot]

    # --- on-screen numeric input (fix65) ---------------------------------------------------------
    def numeric_spec(self):
        cur = self.decision.position
        a, b = self.anchor, self.second
        if self.state == self.SECOND and self.method in (CORNER, CENTER):
            k = 0.5 if self.method == CENTER else 1.0
            sx, sy = side_of(cur[0] - a[0]), side_of(cur[1] - a[1])

            def place(v):
                w = v[0] * k if v[0] is not None else abs(cur[0] - a[0])
                h = v[1] * k if v[1] is not None else abs(cur[1] - a[1])
                return (a[0] + sx * w, a[1] + sy * h)
            return ("Width", "Height"), place, ("width", "height")
        if self.state == self.SECOND and self.method in THREE_CLICKS:
            k = 0.5 if self.method == THREE_CENTER else 1.0
            return ("Length",), lambda v: toward(a, cur, v[0] * k) if v[0] else None, ("length",)
        if self.state == self.THIRD and self.method in THREE_CLICKS:
            if self.method == PARALLELOGRAM:
                return ("Width",), lambda v: toward(b, cur, v[0]) if v[0] else None, ("width",)
            ref = b
            n = perp(unit(sub(b, a)))
            side = side_of(dot(sub(cur, ref), n))
            k = 0.5 if self.method == THREE_CENTER else 1.0
            return ("Width",), lambda v: add(ref, mul(n, side * v[0] * k)) if v[0] else None, ("width",)
        return None

    def typed_dimensions(self, geos, typed):
        lines = lines_of(self.sketch, geos)[:4]
        if len(lines) < 4:
            return []
        out = []
        if self.method in (CORNER, CENTER):
            for key, flat in (("width", True), ("height", False)):
                g = next((g for g, h in lines if h == flat), None)
                if key in typed and g is not None:
                    out.append(Sketcher.Constraint("Distance", g, typed[key]))
            return out
        first, second = lines[0][0], lines[1][0]
        if self.method == THREE_CENTER:
            first, second = second, first      # the first line is the side through the middle picked
        if "length" in typed:
            out.append(Sketcher.Constraint("Distance", first, typed["length"]))
        if "width" in typed:
            out.append(Sketcher.Constraint("Distance", second, typed["width"]))
        return out

    def on_click(self, d):
        if self.state == self.FIRST:
            self.anchor = d.position
            self.state = self.SECOND
            self.snapper.set_reference(self.anchor)
            return
        if self.method in THREE_CLICKS and self.state == self.SECOND:
            if length(sub(d.position, self.anchor)) < 1e-9:
                return
            self.second = d.position
            self.state = self.THIRD
            self.snapper.set_reference(self.second)
            return
        if self.corners is None:
            return
        c = self.corners
        if length(sub(c[1], c[0])) < 1e-9 or length(sub(c[2], c[1])) < 1e-9:
            return  # no width or no height yet
        if abs(_cross(sub(c[1], c[0]), sub(c[2], c[1]))) < 1e-9:
            return  # the corners are in line
        self._write(c)

    def _write(self, c):
        sug0, sug1, sug2 = list(self.sug[0]), list(self.sug[1]), list(self.sug[2])
        sk = self.sketch
        method = self.method
        lines = self._lines(c)
        frm = self.lines_from
        center = self.center if method in CENTERED and lines else None
        last = self.last_pos
        square = getattr(self, "square", False)

        def line(a, b, construction=None):
            return self.add_geometry(Part.LineSegment(App.Vector(a[0], a[1], 0), App.Vector(b[0], b[1], 0)),
                                     construction)

        def body():
            first = line(c[0], c[1])
            line(c[1], c[2])
            line(c[2], c[3])
            line(c[3], c[0])
            cs = []         # one add for all: each add solves and redraws the whole sketch (review 1119 perf2)
            for i in range(4):
                cs.append(Sketcher.Constraint("Coincident", first + i, I.END, first + (i + 1) % 4, I.START))
            if method in (CORNER, CENTER):
                type_a, type_b = geom.rectangle_relation_types(c[0], c[2])
                cs.append(Sketcher.Constraint(type_a, first))
                cs.append(Sketcher.Constraint(type_a, first + 2))
                cs.append(Sketcher.Constraint(type_b, first + 1))
                cs.append(Sketcher.Constraint(type_b, first + 3))
            else:
                cs.append(Sketcher.Constraint("Parallel", first, first + 2))
                cs.append(Sketcher.Constraint("Parallel", first + 1, first + 3))
                if method != PARALLELOGRAM:
                    cs.append(Sketcher.Constraint("Perpendicular", first, first + 1))
            if square:
                cs.append(Sketcher.Constraint("Equal", first, first + 1))
            point = None
            if lines:
                l1 = line(lines[0][0], lines[0][1], True)
                l2 = line(lines[1][0], lines[1][1], True)
                if frm == FROM_MIDPOINTS:
                    # each end at the Midpoint of a side
                    for geo, sides in ((l1, (0, 2)), (l2, (1, 3))):
                        for end, side in zip((I.START, I.END), sides):
                            cs.append(Sketcher.Constraint("Symmetric", first + side, I.START,
                                                                 first + side, I.END, geo, end))
                else:
                    cs.append(Sketcher.Constraint("Coincident", l1, I.START, first, I.START))
                    cs.append(Sketcher.Constraint("Coincident", l1, I.END, first + 2, I.START))
                    cs.append(Sketcher.Constraint("Coincident", l2, I.START, first + 1, I.START))
                    cs.append(Sketcher.Constraint("Coincident", l2, I.END, first + 3, I.START))
                if center is not None:
                    # the centre is the Midpoint of a construction line (package 29; the other one
                    # passes through it by the rectangle's own relations)
                    point = self.add_geometry(Part.Point(App.Vector(center[0], center[1], 0)), True)
                    cs.append(Sketcher.Constraint("Symmetric", l1, I.START, l1, I.END, point, I.START))
            sk.addConstraint(cs)
            if method in CENTERED:
                if point is not None:
                    self.add_relations(sug0, point, I.START)
            else:
                self.add_relations(sug0, first, I.START)
            if method in THREE_CLICKS:
                if method != THREE_CENTER:      # 3 Point Center's second click is no point of the sketch
                    self.add_relations(sug1, first, I.END)
                # the last click's relations go on the corner it placed (3 Point Corner and
                # Center take only the width from it: none unless the pointer is on a corner)
                hit = [i for i in range(4) if length(sub(c[i], last)) < 1e-7]
                if hit:
                    self.add_relations(sug2, first + hit[0], I.START)
            else:
                self.add_relations(sug1, first + 1, I.END)
            # solved by transaction() right after (review 1119 perf3: one solve a tool action)
            return first

        first = self.transaction("Add sketch box", body)
        self.select_new(range(first, first + 4))
        self.finish_or_continue()


def start_rectangle(method=CORNER):
    gdoc, sketch = edited_sketch()
    tool = RectangleTool(gdoc, sketch, method)
    tool.begin()
    return tool


def start_center_rectangle():
    return start_rectangle(CENTER)


def start_three_point_corner_rectangle():
    return start_rectangle(THREE_CORNER)


def start_three_point_center_rectangle():
    return start_rectangle(THREE_CENTER)


def start_parallelogram():
    return start_rectangle(PARALLELOGRAM)
