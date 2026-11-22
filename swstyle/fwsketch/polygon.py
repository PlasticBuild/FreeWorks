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
import Part
import Sketcher
from PySide import QtCore

from .vec import sub, length
from . import inference as I
from . import geom
from .toolbase import SketchTool, GENERAL_GROUP, param_bool, fmt_length, edited_sketch, toward

EPS = 1e-9
PI = math.pi


def inscribed_circle():
    return param_bool(GENERAL_GROUP, "PolygonInscribedCircle", False)


def corner_for(centre, pointer, sides, inscribed):
    """The first corner for the pointer: the pointer itself, or with an inscribed circle the
    corner half a side before it (cornerFor)."""
    if not inscribed or sides < 3:
        return pointer
    half = PI / sides
    c, s, k = math.cos(-half), math.sin(-half), 1.0 / math.cos(half)
    d = sub(pointer, centre)
    return (centre[0] + k * (c * d[0] - s * d[1]), centre[1] + k * (s * d[0] + c * d[1]))


def corners_of(centre, corner, sides):
    d = sub(corner, centre)
    out = []
    for i in range(sides):
        a = 2.0 * PI * i / sides
        c, s = math.cos(a), math.sin(a)
        out.append((centre[0] + c * d[0] - s * d[1], centre[1] + c * d[1] + s * d[0]))
    return out


def make_regular_polygon(sketch, sides, centre, corner, construction=False, inscribed=False, add_geometry=None):
    """ProfileLib.RegularPolygon.makeRegularPolygon with package 31's inscribed circle; returns
    the geo indexes (the sides, then the construction circle)."""
    if sides < 3:
        raise ValueError("a polygon needs at least 3 sides")
    add_geometry = add_geometry or (lambda g, c: sketch.addGeometry(g, c))
    pts = corners_of(centre, corner, sides)
    geos = []
    for i in range(sides):
        a, b = pts[i], pts[(i + 1) % sides]
        geos.append(add_geometry(Part.LineSegment(App.Vector(a[0], a[1], 0), App.Vector(b[0], b[1], 0)), construction))
    radius = length(sub(corner, centre))
    circle_radius = radius * math.cos(PI / sides) if inscribed else radius
    circle = add_geometry(Part.Circle(App.Vector(centre[0], centre[1], 0), App.Vector(0, 0, 1), circle_radius), True)
    geos.append(circle)
    C = Sketcher.Constraint
    first = len(sketch.Constraints)
    cs = []             # one add for all: each add solves and redraws the whole sketch (review 1119 perf2)
    for i in range(sides):
        cs.append(C("Coincident", geos[i], I.END, geos[(i + 1) % sides], I.START))
    joints = first + len(cs)
    # with the sides touching the circle, an even polygon's last Equal follows from the others and
    # leaves it free to flatten like a rhombus: an angle between two sides holds it regular

    even_inscribed = inscribed and sides % 2 == 0
    for i in range(sides - 2 if even_inscribed else sides - 1):
        cs.append(C("Equal", geos[0], geos[i + 1]))
    for i in range(sides):
        if inscribed:
            cs.append(C("Tangent", circle, geos[i]))
        else:
            cs.append(C("PointOnObject", geos[i], I.END, circle))
    index = None
    if even_inscribed:
        index = first + len(cs)
        cs.append(C("Angle", geos[0], geos[1], 2.0 * PI / sides))
    sketch.addConstraint(cs)
    if index is not None:
        sketch.setVirtualSpace(index, True)
    try:
        name_pattern(sketch, range(joints, len(sketch.Constraints)))
    except Exception as _fw_err:
        _fw_log("fwsketch/polygon.py:104", _fw_err)
    return geos


PATTERN = "Patterned"


def _pattern_numbers(sketch):
    out = set()
    for c in sketch.Constraints:
        group = pattern_group(c.Name)
        if group is not None:
            out.add(group)
    return out


def pattern_group(name):
    """The polygon a constraint named 'Patterned<k>_<i>' belongs to (k), else None."""
    if not name or not name.startswith(PATTERN):
        return None
    head, _, tail = name[len(PATTERN):].partition("_")
    return int(head) if head.isdigit() and tail.isdigit() else None


def name_pattern(sketch, indices):
    ""


    used = _pattern_numbers(sketch)
    k = 0
    while k in used:
        k += 1
    n = 0
    for i in indices:
        c = sketch.Constraints[i]
        if c.Type not in ("Equal", "Tangent", "PointOnObject"):
            continue
        sketch.renameConstraint(i, "%s%d_%d" % (PATTERN, k, n))
        n += 1
        if c.Type != "Equal":
            try:
                sketch.setVirtualSpace(i, True)
            except Exception as _fw_err:
                _fw_log("fwsketch/polygon.py:147", _fw_err)
    return k


class PolygonTool(SketchTool):
    TOOL_KEYS = SketchTool.TOOL_KEYS + (QtCore.Qt.Key_U, QtCore.Qt.Key_J)

    def __init__(self, gdoc, sketch, sides=6):
        super().__init__(gdoc, sketch)
        self.sides = max(3, int(sides))
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Regular_Polygon"

    def title(self):
        return "Polygon"

    def reset(self):
        super().reset()
        self.centre = None
        self.corner = None
        self.radius = 0.0
        self.sug = [[], []]

    def on_move(self, p, px):
        if self.state == self.FIRST:
            self.snapper.set_reference(None)
            d = self.snap(p, px)
            self.preview([])
            self.readout(d.position, "")
            self.sug[0] = self.seek(d.position, (0.0, 0.0))
            return self.sug[0]
        self.snapper.set_reference(self.centre)
        d = self.snap(p, px, allow_angle=True)
        pos = d.position
        inscribed = inscribed_circle()
        self.corner = corner_for(self.centre, pos, self.sides, inscribed)
        self.radius = length(sub(self.corner, self.centre))
        circle_radius = self.radius * math.cos(PI / self.sides) if inscribed else self.radius
        if self.radius > EPS:
            pts = corners_of(self.centre, self.corner, self.sides)
            self.preview([pts + [pts[0]]], construction=[geom.circle_points(self.centre, circle_radius)],
                         points=[self.centre])
        else:
            self.preview([])
        self.readout(pos, "%d sides, R = %s" % (self.sides, fmt_length(circle_radius)))
        self.sug[1] = [] if inscribed else self.seek(pos, (0.0, 0.0))
        return self.sug[1]

    def on_key(self, key):
        if key == QtCore.Qt.Key_U:
            self.sides += 1
        elif key == QtCore.Qt.Key_J:
            self.sides = max(3, self.sides - 1)
        else:
            return False
        self._move()
        return True

    # --- on-screen numeric input (fix65): the radius of the construction circle ----------------
    def numeric_spec(self):
        if self.state != self.SECOND:
            return None
        cur = self.decision.position
        return ("Radius",), lambda v: toward(self.centre, cur, v[0]) if v[0] else None, ("radius",)

    def typed_dimensions(self, geos, typed):
        circle = next((g for g in reversed(geos) if type(self.sketch.Geometry[g]).__name__ == "Circle"), None)
        if circle is None or "radius" not in typed:
            return []
        return [Sketcher.Constraint("Radius", circle, typed["radius"])]

    def on_click(self, d):
        if self.state == self.FIRST:
            self.centre = d.position
            self.state = self.SECOND
            return
        if self.radius < EPS:
            return
        sug0, sug1 = list(self.sug[0]), list(self.sug[1])
        centre, corner, sides, inscribed = self.centre, self.corner, self.sides, inscribed_circle()
        sk = self.sketch

        def body():
            geos = make_regular_polygon(sk, sides, centre, corner, self.construction, inscribed, self.add_geometry)
            self.add_relations(sug0, geos[-1], I.MID)
            if not inscribed:
                self.add_relations(sug1, geos[-2], I.END)
            # solved by transaction() right after (review 1119 perf3: one solve a tool action)
            return geos

        geos = self.transaction("Add polygon", body)
        self.select_new(geos[:-1])
        self.finish_or_continue()


def start_polygon(sides=6):
    gdoc, sketch = edited_sketch()
    tool = PolygonTool(gdoc, sketch, sides)
    tool.begin()
    return tool
