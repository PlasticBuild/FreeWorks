# SPDX-License-Identifier: LGPL-2.1-or-later
"""Centerpoint Arc and 3 Point Arc on stock FreeCAD (DrawSketchHandlerArc.h, Center and
ThreeRim), and Tangent Arc (the Line tool's arc from a picked end point).

Centerpoint: centre, start point, end point; the angle is read out and keeps the turning sense
the arc already has. 3 point: two end points, then a point the arc passes through. Tangent:
pick an end point of a line or arc, the arc leaves it tangentially (sideways: at 90 degrees)."""

import math

import FreeCAD as App
import Part
import Sketcher

from .vec import sub, length
from . import inference as I
from . import relations as R
from . import geom
from .toolbase import SketchTool, fmt_length, fmt_angle, edited_sketch, toward
from .line import LineTool, ARC, TANGENT

CENTER, THREE_POINT = "center", "three_point"


class ArcTool(SketchTool):
    def __init__(self, gdoc, sketch, method=CENTER):
        super().__init__(gdoc, sketch)
        self.method = method
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Create_3PointArc" if self.method == THREE_POINT else "Sketcher_Pointer_Create_Arc"

    def title(self):
        return "3 Point Arc" if self.method == THREE_POINT else "Centerpoint Arc"

    def reset(self):
        super().reset()
        self.center = None
        self.first = None
        self.second = None
        self.radius = 0.0
        self.start_angle = 0.0
        self.arc_angle = 0.0
        self.arc = None            # (start, end) angles of the arc to add, counter-clockwise
        self.pos1 = self.pos2 = I.START
        self.sug = [[], [], []]

    def on_move(self, p, px):
        if self.state == self.FIRST:
            self.snapper.set_reference(None)
            d = self.snap(p, px)
            self.preview([])
            self.readout(d.position, "")
            self.sug[0] = self.seek(d.position, (0.0, 0.0))
            return self.sug[0]
        if self.method == CENTER:
            return self._move_center(p, px)
        return self._move_three_point(p, px)

    def _move_center(self, p, px):
        self.snapper.set_reference(self.center)
        d = self.snap(p, px, allow_angle=True)
        pos = d.position
        if self.state == self.SECOND:
            self.first = pos
            self.start_angle = math.atan2(pos[1] - self.center[1], pos[0] - self.center[0])
            self.radius = length(sub(pos, self.center))
            if self.radius > 1e-9:
                self.preview([geom.circle_points(self.center, self.radius)], construction=[[self.center, pos]],
                             points=[self.center])
            seg = sub(pos, self.center)
            self.readout(pos, "%s, %s" % (fmt_length(self.radius),
                                          fmt_angle(math.degrees(math.atan2(seg[1], seg[0])) % 360.0)))
            self.sug[1] = _level_glyph(self.seek(pos, (0.0, 0.0)), self.center, pos, self.radius)
            return self.sug[1]
        self.second = pos
        cursor_angle = math.atan2(pos[1] - self.center[1], pos[0] - self.center[0])
        self.arc_angle = geom.center_arc_angle(self.start_angle, cursor_angle, self.arc_angle)
        self.arc = geom.center_arc_range(self.start_angle, self.arc_angle)
        if self.radius > 1e-9 and abs(self.arc_angle) > 1e-9:
            a0 = self.arc[0]
            scale = 0.8
            legs = [[self.center, (self.center[0] + math.cos(self.start_angle) * scale * self.radius,
                                   self.center[1] + math.sin(self.start_angle) * scale * self.radius)],
                    [self.center, (self.center[0] + math.cos(cursor_angle) * scale * self.radius,
                                   self.center[1] + math.sin(cursor_angle) * scale * self.radius)]]
            self.preview([geom.arc_points(self.center, self.radius, a0, self.arc[1] - a0)], construction=legs,
                         points=[self.center])
        self.readout(pos, fmt_angle(math.degrees(self.arc_angle)))
        # the end lies on the circle from the second click, along the pointer's direction: what the
        # pointer snapped to holds the end only when the end is there (within the snap distance), or
        # the click would pull the radius and drag what is already drawn (monkey "no jump" 11-19)
        end = (self.center[0] + math.cos(cursor_angle) * self.radius, self.center[1] + math.sin(cursor_angle) * self.radius)
        near = max(2.0 * self.snapper.pixel_size, 1e-6 * max(1.0, self.radius))
        found = self.seek(pos, (0.0, 0.0)) if length(sub(end, pos)) <= near else []
        self.sug[2] = _level_glyph(found, self.center, pos, self.radius)
        return self.sug[2]

    def _move_three_point(self, p, px):
        self.snapper.set_reference(self.first)
        d = self.snap(p, px, allow_angle=False)
        pos = d.position
        if self.state == self.SECOND:
            self.second = pos
            self.center = ((pos[0] + self.first[0]) / 2, (pos[1] + self.first[1]) / 2)
            self.radius = length(sub(pos, self.center))
            if self.radius > 1e-9:
                self.preview([[self.first, pos]])      # the chord, not a circle

            self.readout(pos, "L = %s" % fmt_length(length(sub(pos, self.first))))
            self.sug[1] = self.seek(pos, (0.0, 0.0))
            return self.sug[1]
        found = geom.three_point_arc(self.first, self.second, pos)
        if found is not None:
            self.center, self.radius, a0, a1, self.pos1, self.pos2 = found
            self.arc = (a0, a1)
            self.preview([geom.arc_points(self.center, self.radius, a0, a1 - a0)])

            self.readout(pos, "A = %s R = %s" % (fmt_angle(abs(math.degrees(a1 - a0))), fmt_length(self.radius)))
        else:
            self.readout(pos, "")
        self.sug[2] = self.seek(pos, (0.0, 0.0), R.CURVE)
        return self.sug[2]

    # --- on-screen numeric input (fix65) ---------------------------------------------------------
    def numeric_spec(self):
        cur = self.decision.position
        if self.method == CENTER and self.state == self.SECOND:
            return ("Radius",), lambda v: toward(self.center, cur, v[0]) if v[0] else None, ("radius",)
        if self.method == CENTER and self.state == self.THIRD:
            c, f = self.center, self.first
            sense = -1.0 if self.arc_angle < 0 else 1.0

            def place(v):
                if not v[0]:
                    return None
                t = sense * math.radians(v[0])
                dx, dy = f[0] - c[0], f[1] - c[1]
                self._typed_sweep = t
                return (c[0] + dx * math.cos(t) - dy * math.sin(t), c[1] + dx * math.sin(t) + dy * math.cos(t))
            return ("Angle",), place, ("angle",)
        if self.method == THREE_POINT and self.state == self.SECOND:
            return ("Length",), lambda v: toward(self.first, cur, v[0]) if v[0] else None, ("chord",)
        return None

    def after_typed_move(self, values):
        t = getattr(self, "_typed_sweep", None)
        self._typed_sweep = None
        if t is not None and self.method == CENTER and self.state == self.THIRD:
            self.arc_angle = t        # an angle typed past 180 degrees: the point alone cannot say
            self.arc = geom.center_arc_range(self.start_angle, t)

    def typed_dimensions(self, geos, typed):
        g = geos[0]
        out = []
        if "radius" in typed:
            out.append(Sketcher.Constraint("Radius", g, typed["radius"]))
        if "angle" in typed:
            out.append(Sketcher.Constraint("Angle", g, math.radians(abs(typed["angle"]))))
        if "chord" in typed:
            out.append(Sketcher.Constraint("Distance", g, I.START, g, I.END, typed["chord"]))
        return out

    def on_click(self, d):
        if self.state == self.FIRST:
            if self.method == CENTER:
                self.center = d.position
            else:
                self.first = d.position
            self.state = self.SECOND
            return
        if self.state == self.SECOND:
            if self.method == CENTER:
                if self.radius < 1e-9:
                    return
                self.first = d.position
            else:
                self.second = d.position
            self.state = self.THIRD
            self.arc_angle = 0.0
            return
        if self.arc is None or self.radius < 1e-9 or abs(self.arc[1] - self.arc[0]) < 1e-9:
            return
        sugs = [list(s) for s in self.sug]
        center, radius, (a0, a1) = self.center, self.radius, self.arc
        if self.method == CENTER:
            positions = [I.MID, I.START if self.arc_angle > 0 else I.END, I.END if self.arc_angle > 0 else I.START]
        else:
            positions = [self.pos1, self.pos2, I.NONE]
        sk = self.sketch

        def body():
            circle = Part.Circle(App.Vector(center[0], center[1], 0), App.Vector(0, 0, 1), radius)
            geo = self.add_geometry(Part.ArcOfCircle(circle, a0, a1))     # For construction on the page
            level = []
            if self.method == CENTER:
                sugs[1], sugs[2], level = _level_ends(sugs, center, (self.first, self.second), radius)
            for s, pos in zip(sugs, positions):
                self.add_relations(s, geo, pos)
            for k, kind in level:
                _add_unless_redundant(sk, Sketcher.Constraint(kind, geo, positions[k], geo, I.MID))
            # solved by transaction() right after (review 1119 perf3: one solve a tool action)
            return geo

        self.transaction("Add sketch arc", body)
        self.finish_or_continue()


class TangentArcTool(LineTool):
    ""



    def icon_name(self):
        return "Sketcher_Pointer_Create_Arc"

    def title(self):
        return "Tangent Arc"

    def on_click(self, d):
        if self.state == self.FIRST:
            self._first_click(d)
            if self.previous_curve == -1:
                self.reset()  # not an end point: nothing to leave from
                return
            cands = self._corner_candidates()
            # a corner (a rectangle's): every line or arc ending there is a candidate; the pointer
            # picks the one it continues (tester SK7-03: the arc took the side it could not leave)
            self._cands = cands if len(cands) > 1 else []
            if self._cands:
                keys = set(self._cands)
                self.sug1 = [s for s in self.sug1 if not (s.type == "Coincident" and (s.geo, s.pos) in keys)]
            self.segment, self.transition = ARC, TANGENT
            self._intent_pending = True
            return
        if self.state == self.SECOND and getattr(self, "_cands", None) and not self._arc_ok():
            self._try_other_candidates()
            d = self.decision or d
        super().on_click(d)
        if self.state == self.SECOND and self.previous_curve != -1 and self.sketch.GeometryCount - 1 >= self.first_curve:
            self._end_chain()

    def _corner_candidates(self):
        """Every (geo, end) of a line or arc at the start point, the one the click took first."""
        out = [(self.previous_curve, self.previous_pos)]
        here = App.Vector(self.start[0], self.start[1], 0)
        tol = max(1e-6, 1e-7 * max(1.0, here.Length))
        for g, geo in enumerate(self.sketch.Geometry):
            if not isinstance(geo, (Part.LineSegment, Part.ArcOfCircle)) or self.sketch.getConstruction(g):
                continue
            for pos in (I.START, I.END):
                if (g, pos) not in out and (self.sketch.getPoint(g, pos) - here).Length < tol:
                    out.append((g, pos))
        return out

    def _use(self, cand):
        self.previous_curve, self.previous_pos = cand
        self._update_transition_data()

    def _arc_ok(self):
        a = self.arc
        return a is not None and math.isfinite(a[1]) and abs(a[1]) > 1e-9

    def _try_other_candidates(self):
        """The arc came out straight (its end on the tangent): leave from another curve at the corner."""
        keep = (self.previous_curve, self.previous_pos, self.transition)
        p, px = self.pointer()
        if p is None:
            return
        # first the other curves with the pointer's intent zone, then any curve plain tangent
        # (from a rectangle corner straight up to the next corner: the semicircle off the side

        tries = [(c, None) for c in self._cands if c != keep[:2]]
        tries += [(c, TANGENT) for c in self._cands]
        for cand, mode in tries:
            self._use(cand)
            self.transition = mode or geom.arc_transition_for(self.dir_vec, sub(p, self.start))
            self.on_move(p, px)
            if self._arc_ok():
                return
        self.previous_curve, self.previous_pos = keep[:2]
        self._update_transition_data()
        self.transition = keep[2]
        self.on_move(p, px)

    def on_move(self, p, px):
        if self.state == self.SECOND and getattr(self, "_intent_pending", False) and self.start is not None:
            away = sub(p, self.start)
            if length(away) > 14.0 * px:
                if getattr(self, "_cands", None):
                    n = length(away)
                    best = None
                    for cand in self._cands:
                        self._use(cand)
                        along = (self.dir_vec[0] * away[0] + self.dir_vec[1] * away[1]) / n
                        if best is None or along > best[0]:
                            best = (along, cand)
                    self._use(best[1])
                self.transition = geom.arc_transition_for(self.dir_vec, away)
                self._intent_pending = False
        return super().on_move(p, px)

    def _auto_transition(self, pos, px):
        pass  # the arc stays an arc

    def on_key(self, key):
        return False


def start_arc(method=CENTER):
    gdoc, sketch = edited_sketch()
    tool = ArcTool(gdoc, sketch, method)
    tool.begin()
    return tool


def start_three_point_arc():
    return start_arc(THREE_POINT)


def start_tangent_arc():
    gdoc, sketch = edited_sketch()
    tool = TangentArcTool(gdoc, sketch)
    tool.begin()
    return tool


def _level_ends(sugs, center, ends, radius):
    ""


    tol = 1e-9 * max(1.0, radius)
    out, level = [sugs[1], sugs[2]], []
    for k, end in ((1, ends[0]), (2, ends[1])):
        if end is None:
            continue
        kind = "Horizontal" if abs(end[1] - center[1]) <= tol else "Vertical" if abs(end[0] - center[0]) <= tol else None
        if kind is None:
            continue
        axis = I.H_AXIS if kind == "Horizontal" else I.V_AXIS
        out[k - 1] = [s for s in sugs[k] if not (s.type == "PointOnObject" and s.geo == axis)
                      and not (s.type in ("Horizontal", "Vertical") and s.geo == I.GEO_UNDEF)]
        if not any(s.type in ("Coincident", "PointOnObject") for s in out[k - 1]):
            level.append((k, kind))
    return out[0], out[1], level


def _add_unless_redundant(sk, constraint):
    i = sk.addConstraint(constraint)
    sk.solve()
    if i + 1 in sk.RedundantConstraints or i + 1 in sk.ConflictingConstraints:
        sk.delConstraint(i)


def _level_glyph(sug, center, pos, radius):
    """While the end is level with the centre, the pointer shows Horizontal (Vertical), the
    relation the click adds, in place of On Entity to the axis."""
    tol = 1e-9 * max(1.0, radius)
    if center is None or pos is None:
        return sug
    kind = "Horizontal" if abs(pos[1] - center[1]) <= tol else "Vertical" if abs(pos[0] - center[0]) <= tol else None
    if kind is None:
        return sug
    axis = I.H_AXIS if kind == "Horizontal" else I.V_AXIS
    out = [s for s in sug if not (s.type == "PointOnObject" and s.geo == axis)]
    if not any(s.type in ("Coincident", "PointOnObject") for s in out):
        out.append(R.Suggestion(kind))
    return out
