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

from .vec import sub, add, mul, length, unit
from . import inference as I
from . import relations as R
from . import geom
from . import topology
from .toolbase import SketchTool, continuous_mode, fmt_length, fmt_angle, edited_sketch, param_bool, GENERAL_GROUP, length_unit

TOOL_PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchTools"   # the Insert Line page's


def orientation():
    ""

    try:
        p = App.ParamGet(TOOL_PARAMS)
        name = p.GetString("LineOrientation", "As sketched")
        degrees = p.GetFloat("LineAngle", 0.0)
    except Exception:
        return None
    if name == "Horizontal":
        return name, (1.0, 0.0), 0.0
    if name == "Vertical":
        return name, (0.0, 1.0), math.pi / 2
    if name == "Angle":
        a = math.radians(degrees)
        return name, (math.cos(a), math.sin(a)), a
    return None


def fixed_length():
    ""

    try:
        return max(0.0, App.ParamGet(TOOL_PARAMS).GetFloat("LineLength", 0.0))
    except Exception:
        return 0.0


def infinite():
    ""

    try:
        return App.ParamGet(TOOL_PARAMS).GetBool("LineInfinite", False)
    except Exception:
        return False


INFINITE_REACH = 5000.0     # mm past each click: FreeCAD's sketch has no endless line


LINE, ARC = "line", "arc"
FREE, TANGENT, PERP_L, PERP_R = "free", "tangent", "perpendicular_l", "perpendicular_r"
HOTSPOT_PIXELS, LEAVE_PIXELS = 6.0, 14.0



def _level_too(sk, geo, degrees=1.0):
    ""


    seg = sk.Geometry[geo]
    d = seg.EndPoint - seg.StartPoint
    if d.Length < 1e-9:
        return
    ang = abs(math.degrees(math.atan2(d.y, d.x))) % 180.0
    kind = "Horizontal" if min(ang, 180.0 - ang) <= degrees else "Vertical" if abs(ang - 90.0) <= degrees else None
    if kind is None:
        return
    k = sk.ConstraintCount
    sk.addConstraint([Sketcher.Constraint(kind, geo)])     # a list: no solve and redraw of its own (review 1119 perf3)
    sk.solve()
    if k + 1 in set(sk.ConflictingConstraints) | set(sk.RedundantConstraints) \
            | set(getattr(sk, "PartiallyRedundantConstraints", []) or []):
        sk.delConstraint(k)
        sk.solve()

class LineTool(SketchTool):
    LINE, ARC = LINE, ARC   # so swstyle.rcmenus can test tool.segment == tool.ARC

    def __init__(self, gdoc, sketch, construction=False):
        self.numeric = None  # the on-screen length box while it is open
        self.menu = None
        super().__init__(gdoc, sketch, construction)
        self.reset()

    def end(self):
        self._close_numeric_input()
        if self.menu is not None:
            try:
                self.menu.close()
            except RuntimeError as _fw_err:
                _fw_log("fwsketch/line.py:126", _fw_err)
            self.menu = None
        super().end()

    def icon_name(self):
        return "Sketcher_Pointer_Create_Lineset"

    def title(self):
        return "Line"

    def reset(self):
        super().reset()
        self.segment = LINE
        self.transition = FREE
        self.snap45 = False
        self.suppress_transition = False
        self.preview_glyphs = []
        self.start = None               # the segment's start (EditCurve[0])
        self.end_point = None                 # its end as last drawn
        self.first_curve = -1
        self.first_pos = I.NONE
        self.previous_curve = -1
        self.previous_pos = I.NONE
        self.dir_vec = (1.0, 0.0)
        self.sug1, self.virtual_sug1, self.sug2 = [], [], []
        self.first_segment = True
        self.ends_chain = False
        self.transition_away = False
        self.transition_armed = False
        self.arc = None                 # (center, radius, start_angle, end_angle, arc_angle)
        self.typed_length = 0.0
        self.typed_entry = False
        self._close_numeric_input()

    # --- moves -----------------------------------------------------------------------------
    def on_move(self, p, px):
        if self.state == self.FIRST:
            self.snapper.set_reference(None)
            self.preview_glyphs = []
            d = self.snap(p, px)
            self.readout(d.position, "")
            self.preview([])
            self.sug1 = self.seek(d.position, (0.0, 0.0))
            return self.sug1
        free_line = self.segment == LINE and self.transition == FREE
        self.snapper.set_reference(self.start)
        self.snapper.mirror_midpoint = free_line
        d = self.snap(p, px, allow_angle=free_line)
        pos = d.position
        if self.previous_curve != -1:
            self._auto_transition(pos, px)
        if self.segment == LINE and getattr(self, "free_after_arc", False) and self.transition in (FREE, TANGENT):
            # the tangent inference off the arc just drawn: near its tangent the line runs along it

            self.transition = TANGENT if self._near_arc_tangent(p, px) else FREE
        point_on_tangent = False
        if self.segment == LINE and getattr(self, "free_after_arc", False) and self.transition == TANGENT \
                and getattr(d, "winner", None) in _POINT_WINNERS:

            # the tangent the line ends on it with both glyphs (Tangent and Coincident: a profile
            # closes); off it the line goes to the point, free
            try:
                t = unit(self.dir_vec)
                rel = sub(pos, self.start)
                point_on_tangent = abs(rel[0] * t[1] - rel[1] * t[0]) <= 0.5 * px and rel[0] * t[0] + rel[1] * t[1] > 0.0
            except Exception:
                point_on_tangent = False
            if not point_on_tangent:
                self.transition = FREE
        self.suppress_transition = False
        self.preview_glyphs = []
        on_curve = False
        if self.segment == LINE:
            if self.transition in (TANGENT, PERP_L, PERP_R) and self.previous_curve != -1:

                from .cursor import TANGENT as _T, PERPENDICULAR as _P
                self.preview_glyphs = [_T if self.transition == TANGENT else _P]
            if self.transition == TANGENT:
                self.end_point, self.suppress_transition = geom.line_end_tangent(self.start, pos, self.dir_vec)
                if self.suppress_transition:
                    self.preview_glyphs = []        # no Tangent will be added: no glyph
                elif point_on_tangent:
                    self.end_point = pos
                elif self._tangent_meets_curve(d, px):
                    self.end_point, on_curve = d.position, True
            elif self.transition in (PERP_L, PERP_R):
                self.end_point = geom.project_along(self.start, pos, (-self.dir_vec[1], self.dir_vec[0]))
            else:
                self.end_point = pos
                fixed = orientation() if not self.typed_entry else None
                if fixed is not None:
                    dv = fixed[1]
                    t = (pos[0] - self.start[0]) * dv[0] + (pos[1] - self.start[1]) * dv[1]
                    if fixed_length() > 0:
                        t = fixed_length() if t >= 0 else -fixed_length()
                    self.end_point = (self.start[0] + dv[0] * t, self.start[1] + dv[1] * t)
            self.preview([[self.start, self.end_point]])
            seg = sub(self.end_point, self.start)
            n = length(seg)
            if n > 0.0 and min(abs(seg[0]), abs(seg[1])) <= 1e-9 * n:

                self.readout(self.end_point, "%s, %s" % (fmt_length(n),
                                                   fmt_angle(round(math.degrees(math.atan2(seg[1], seg[0]))) % 360.0)))
            else:
                self.readout(self.end_point, fmt_length(n))
            if self.transition == FREE and orientation() is not None and not self.typed_entry:
                # held to the page's orientation: only the end's relations, when the pointer is on it
                on_end = length(sub(pos, self.end_point)) < 1e-7
                self.sug2 = [s for s in self.seek(self.end_point, (0.0, 0.0)) if on_end] if on_end else []
            elif self.transition == FREE:
                self.sug2 = self.seek(pos, sub(pos, self.start))
            elif point_on_tangent and not self.suppress_transition:
                self.sug2 = [s for s in self.seek(pos, (0.0, 0.0)) if s.type == "Coincident"]
            elif on_curve:
                self.sug2 = [s for s in self.seek(self.end_point, (0.0, 0.0)) if s.type == "PointOnObject"]
            else:
                self.sug2 = []
            return self.sug2
        # an arc leaving the previous segment
        self.snap45 = S_shift_held()
        tangent = geom.transition_tangent(self.dir_vec, self.transition)
        self.arc = geom.tangent_arc(self.start, tangent, pos, self.snap45)
        self.end_point = pos
        if self.arc is None:
            self.preview([[self.start, pos]])
            self.readout(pos, "")
        else:
            center, radius, a0, a1, arc_angle = self.arc

            # relation to the segment it leaves (Tangent, or Perpendicular sideways) beside the pointer
            pts = geom.arc_points(center, radius, a0, arc_angle)
            self.preview([pts], construction=[[center, pts[0]], [center, pts[-1]]])
            from .cursor import TANGENT as _T, PERPENDICULAR as _P
            self.preview_glyphs = [_T] if self.transition == TANGENT else [_P] if self.transition in (PERP_L, PERP_R) else []
            self.readout(pos, "A = %s R = %s" % (fmt_angle(abs(math.degrees(arc_angle))), fmt_length(abs(radius))))
        self.sug2 = self.seek(pos, (0.0, 0.0))
        return self.sug2

    TANGENT_PIXELS = 8.0

    def _tangent_meets_curve(self, d, px):
        """The pointer is on a line or circle (or an axis) near where the tangent line meets it: the
        decision moves to that crossing (snap review 11-19, bench T1). True when it did."""
        from . import snap as S
        if getattr(d, "winner", None) != S.SKETCH_CURVE or d.geo == I.GEO_UNDEF or not px > 0.0:
            return False
        entry = (d.geo, None if d.geo in (I.H_AXIS, I.V_AXIS) else self.snapper.geometry(d.geo))
        if entry[1] is None and d.geo not in (I.H_AXIS, I.V_AXIS):
            return False
        best, found = self.snapper.p.radius * px, None
        t = unit(self.dir_vec)
        for x in I.intersect_line(self.start, t, entry):
            rel = sub(x, self.start)
            if rel[0] * t[0] + rel[1] * t[1] <= 0.0:
                continue
            dd = length(sub(x, d.position))
            if dd <= best:
                best, found = dd, x
        if found is None:
            return False
        d.position = found
        return True

    def _near_arc_tangent(self, pos, px):
        from .snap import inference_suppressed
        if px <= 0.0 or self.typed_entry or orientation() is not None or inference_suppressed():
            return False
        try:
            t = unit(self.dir_vec)
        except Exception:
            return False
        rel = sub(pos, self.start)
        along = rel[0] * t[0] + rel[1] * t[1]
        across = abs(rel[0] * t[1] - rel[1] * t[0])
        return along > 2.0 * self.TANGENT_PIXELS * px and across <= self.TANGENT_PIXELS * px

    def _auto_transition(self, pos, px):
        if px <= 0.0:
            return
        away = sub(pos, self.start)
        distance = length(away)
        if not self.transition_away:
            self.transition_away = distance > LEAVE_PIXELS * px
            return
        if not self.transition_armed:
            self.transition_armed = distance < HOTSPOT_PIXELS * px
            return
        if distance <= LEAVE_PIXELS * px:
            return
        self.transition_armed = False
        if self.segment == LINE:
            self._switch_to_arc(geom.arc_transition_for(self.dir_vec, away))
        else:
            self._switch_to_line()

    def _switch_to_arc(self, transition):
        self.segment, self.transition, self.snap45 = ARC, transition, False

    def _switch_to_line(self):
        g = self.snapper.geometry(self.previous_curve)
        self.segment = LINE

        # held the next line to the arc's tangent, so a level line after an arc came out slanted and
        # Tangent); leaving along the tangent still gets Tangent from the inference (fix160)
        self.transition = FREE
        self.free_after_arc = isinstance(g, Part.ArcOfCircle)
        self.snap45 = False

    # --- keys ----------------------------------------------------------------------------------
    def numeric_input_wanted(self):
        ""

        return self.state == self.SECOND and self.segment == LINE and self.numeric is None \
            and param_bool(GENERAL_GROUP, "OnScreenNumericInput", False)

    @staticmethod
    def _typed_character(key):
        if QtCore.Qt.Key_0 <= key <= QtCore.Qt.Key_9:
            return chr(ord("0") + key - QtCore.Qt.Key_0)
        if key in (QtCore.Qt.Key_Period, QtCore.Qt.Key_Comma):
            return "."
        return None

    def claims_key(self, key):
        if self.numeric_input_wanted() and self._typed_character(key) is not None:
            return True  # FreeCAD's view shortcuts on the digits wait
        return super().claims_key(key)

    def on_key(self, key):
        typed = self._typed_character(key)
        if typed is not None and self.numeric_input_wanted():
            self._open_numeric_input(typed)
            return True
        if self.state != self.SECOND or self.previous_curve == -1:
            return False
        if key == QtCore.Qt.Key_A:
            if self.segment == LINE:
                self._switch_to_arc(TANGENT)
            else:
                self._switch_to_line()
            self._move()
            return True
        if key == QtCore.Qt.Key_M:
            self._cycle_mode()
            self._move()
            return True
        return False

    def _cycle_mode(self):
        """FreeCAD's M key: line free/tangent, line perpendicular, line tangent/free, arc tangent,
        arc perpendicular left, arc perpendicular right."""
        self.snap45 = False
        self.free_after_arc = False     # a mode picked with M stays
        is_arc = isinstance(self.snapper.geometry(self.previous_curve), Part.ArcOfCircle)
        if self.segment == LINE:
            if self.transition == FREE:
                if is_arc:
                    self.segment, self.transition = ARC, TANGENT
                else:
                    self.transition = PERP_L
            elif self.transition == PERP_L:
                self.transition = FREE if is_arc else TANGENT
            elif self.transition == TANGENT:
                if is_arc:
                    self.transition = PERP_L
                else:
                    self.segment, self.transition = ARC, TANGENT
            else:
                self.transition = FREE
        else:
            if self.transition == TANGENT:
                self.transition = PERP_L
            elif self.transition == PERP_L:
                self.transition = PERP_R
            else:
                self.segment = LINE
                self.transition = TANGENT if is_arc else FREE

    # --- clicks --------------------------------------------------------------------------------
    def starts_click_drag(self):
        return self.state == self.FIRST

    def after_click_drag(self):

        if self.state != self.SECOND or self.sketch.GeometryCount - 1 < self.first_curve:
            return
        self._end_chain()

    def on_double_click(self):

        if self.state == self.SECOND and not self.first_segment:
            self._end_chain()
            return True
        return False

    def _end_chain(self):
        self.preview([])
        self.readout(None, "")
        if continuous_mode():
            self.reset()
        else:
            self.end()

    def cancel_current(self):
        # right click: FreeCAD's polyline keeps the tool in continuous mode and drops the chain
        if self.first_segment or not continuous_mode():
            self.end()
        else:
            self.reset()

    def on_click(self, d):
        if self.state == self.FIRST:
            self._first_click(d)
            fixed = orientation()
            if fixed is not None and infinite() and self.segment == LINE and self.transition == FREE \
                    and not self.typed_entry:
                # an infinite line held Horizontal, Vertical or at an Angle needs no second point: one
                # click puts it through the point clicked (user report 11-27, construction lines)
                dv = fixed[1]
                self.end_point = (self.start[0] + dv[0], self.start[1] + dv[1])
                self.sug2 = []
                self._place_segment(d)
            return
        pos = d.position
        if self.start is not None and length(sub(pos, self.start)) < 1e-9:
            self._end_chain()  # a second click on the same point ends the chain
            return
        self._place_segment(d)

    def _first_click(self, d):
        self.start = d.position
        self.virtual_sug1 = list(self.sug1)
        # a start on an end point of a line or arc: the new segment leaves it (transition data)
        for s in list(self.sug1):
            if s.type != "Coincident" or s.pos not in (I.START, I.END):
                continue
            g = self.snapper.geometry(s.geo) if s.geo >= 0 else None
            if isinstance(g, (Part.LineSegment, Part.ArcOfCircle)):
                self.previous_curve, self.previous_pos = s.geo, s.pos
                self._update_transition_data()
                if isinstance(g, Part.ArcOfCircle):

                    self.transition, self.snap45, self.free_after_arc = FREE, False, True
                self.sug1.remove(s)
                break
        if self.previous_curve == -1:
            # the click took another point where a line or arc also ends (the origin wins the tie):

            hit = self._curve_end_at(self.start)
            if hit is not None:
                self.previous_curve, self.previous_pos = hit
                self._update_transition_data()
                if isinstance(self.snapper.geometry(hit[0]), Part.ArcOfCircle):
                    self.transition, self.snap45, self.free_after_arc = FREE, False, True
                self.sug1 = [s for s in self.sug1 if not (s.type == "Coincident" and s.pos != I.NONE
                             and topology.points_coincident(self.sketch, s.geo, s.pos, hit[0], hit[1]))]
        self.first_curve = self.sketch.GeometryCount
        self.first_pos = I.START
        self.transition_away = self.transition_armed = False
        self.state = self.SECOND
        self.snapper.set_reference(self.start)

    def _curve_end_at(self, point):
        """(geo, START or END) of a line or arc of the sketch that ends at point, or None."""
        if point is None:
            return None
        tol = 1e-7 * (1.0 + length(point))
        for geo, g in self.snapper.entries():
            if geo < 0 or not isinstance(g, (Part.LineSegment, Part.ArcOfCircle)):
                continue
            for pos in (I.START, I.END):
                if length(sub(I.point_of(g, pos), point)) <= tol:
                    return geo, pos
        return None

    def _end_point_of(self, d):
        """(geo, pos) when the click landed on an end point of the sketch or the origin."""
        s = next((s for s in self.sug2 if s.type == "Coincident"), None)
        if s is None:
            return None
        if s.geo == I.ROOT and s.pos == I.START:
            return (I.ROOT, I.START)
        if s.geo >= 0 and s.pos in (I.START, I.END):
            return (s.geo, s.pos)
        return None

    def _place_segment(self, d):
        if self.segment == ARC and (self.arc is None or not math.isfinite(self.arc[1]) or abs(self.arc[1]) < 1e-9):
            return
        close = False
        self.ends_chain = False
        target = None if self.typed_entry else self._end_point_of(d)
        if target is not None and self.first_pos != I.NONE:
            if topology.points_coincident(self.sketch, target[0], target[1], self.first_curve, self.first_pos):
                close = True
            elif self.segment == LINE:

                # through other sketch entities closes a profile too, and the tool ends
                self.ends_chain = topology.closes_profile(self.sketch, self.first_curve, self.first_pos,
                                                          target[0], target[1])
        sk = self.sketch
        segment, transition, arc = self.segment, self.transition, self.arc
        sug1, virtual_sug1, sug2 = list(self.sug1), list(self.virtual_sug1), list(self.sug2)
        typed_length = self.typed_length
        if typed_length <= 0 and segment == LINE and transition == FREE and not self.typed_entry \
                and orientation() is not None and fixed_length() > 0:
            typed_length = fixed_length()          # the page's Length: kept as a dimension too
        adds_dimension = param_bool(GENERAL_GROUP, "NumericInputAddsDimension", True)

        # on-screen numeric input on, every line drawn gets its dimension, typed or clicked
        dimension_clicked = (segment == LINE and adds_dimension and typed_length <= 0
                             and param_bool(GENERAL_GROUP, "OnScreenNumericInput", False)
                             and not param_bool(GENERAL_GROUP, "DimensionOnlyWhenEntered", True))
        reversed_arc = segment == ARC and arc[2] > arc[3]
        fixed = orientation() if segment == LINE and transition == FREE and not self.typed_entry else None
        endless = segment == LINE and infinite()

        def body():
            if endless:
                a = App.Vector(self.start[0], self.start[1], 0)
                b = App.Vector(self.end_point[0], self.end_point[1], 0)
                d = b - a
                if d.Length < 1e-9:
                    return None, I.END
                d.normalize()
                geo = self.add_geometry(Part.LineSegment(a - d * INFINITE_REACH, b + d * INFINITE_REACH))
                if fixed is not None and fixed[0] in ("Horizontal", "Vertical"):
                    sk.addConstraint(Sketcher.Constraint(fixed[0], geo))
                else:
                    # the Horizontal / Vertical the pointer showed, as for a line with ends
                    self.add_relations([s for s in sug1 + sug2 if s.type in ("Horizontal", "Vertical")][:1],
                                       geo, I.END)

                from .toolbase import automatic_relations
                for sug in ((sug1 if sug1 else virtual_sug1) + sug2 if automatic_relations() else ()):
                    if sug.type == "Coincident" and sug.geo is not None and sug.pos in (I.START, I.END, I.MID):
                        try:
                            sk.addConstraint(Sketcher.Constraint("PointOnObject", sug.geo, sug.pos, geo))
                        except Exception as _fw_err:
                            _fw_log("fwsketch/line.py:504", _fw_err)
                return geo, I.END        # transaction() recomputes (solves) the sketch
            if segment == LINE:
                geo = self.add_geometry(Part.LineSegment(App.Vector(self.start[0], self.start[1], 0),
                                                         App.Vector(self.end_point[0], self.end_point[1], 0)))
            else:
                center, radius, a0, a1, arc_angle = arc
                circle = Part.Circle(App.Vector(center[0], center[1], 0), App.Vector(0, 0, 1), abs(radius))
                geo = self.add_geometry(Part.ArcOfCircle(circle, min(a0, a1), max(a0, a1)))
            start_pos = I.END if reversed_arc else I.START
            end_pos = I.START if reversed_arc else I.END
            if segment == LINE and typed_length > 0 and adds_dimension:

                sk.addConstraint([Sketcher.Constraint("Distance", geo, typed_length)])
            # Automatic Relations off: no join to an entity that was there before the chain (the

            from .toolbase import automatic_relations
            outside = 0 <= self.previous_curve < self.first_curve
            if self.previous_pos != I.NONE and not (outside and not automatic_relations()):
                kind = "Coincident"
                if not self.suppress_transition and self.previous_curve != -1:
                    if transition == TANGENT:
                        kind = "Tangent"
                    elif transition in (PERP_L, PERP_R):
                        kind = "Perpendicular"
                # added as lists: a single add solves and redraws the whole sketch by itself; the
                # sketch is solved once by add_relations or transaction() (review 1119 perf3)
                sk.addConstraint([Sketcher.Constraint(kind, self.previous_curve, self.previous_pos, geo, start_pos)])
                if kind == "Tangent" and segment == LINE and automatic_relations():
                    _level_too(sk, geo)
                if segment == ARC and self.snap45 and not close:
                    degrees = abs(round(arc[4] / (math.pi / 4)) * 45)
                    sk.addConstraint([Sketcher.Constraint("Angle", geo, math.radians(degrees))])
                if close:
                    sk.addConstraint([Sketcher.Constraint("Coincident", geo, end_pos, self.first_curve, self.first_pos)])
            if segment == LINE and fixed is not None:
                name, dv, angle = fixed
                if name in ("Horizontal", "Vertical"):
                    sk.addConstraint([Sketcher.Constraint(name, geo)])
                else:
                    seg = sk.Geometry[geo]
                    dd = seg.EndPoint - seg.StartPoint
                    want = angle + (math.pi if math.cos(math.atan2(dd.y, dd.x) - angle) < 0 else 0.0)
                    sk.addConstraint([Sketcher.Constraint("Angle", geo, want)])
                sug1[:] = [s for s in sug1 if s.type not in ("Horizontal", "Vertical")]
            if segment == LINE:
                R.remove_redundant_hv(sk, sug1 if sug1 else virtual_sug1, sug2, self.snapper.geometry)
            if close:
                self.add_relations([s for s in sug2 if s.type != "Coincident"], geo, end_pos)
            else:
                if sug1:
                    self.add_relations(sug1, geo, I.START)
                self.add_relations(sug2, geo, end_pos)
            if dimension_clicked:
                seg = sk.Geometry[geo]
                k = sk.ConstraintCount
                sk.addConstraint([Sketcher.Constraint("Distance", geo, (seg.EndPoint - seg.StartPoint).Length)])
                sk.solve()
                if k + 1 in set(sk.ConflictingConstraints) | set(sk.RedundantConstraints):
                    sk.delConstraint(k)      # it would over-define the sketch: left out
            # no sk.solve() here: transaction() recomputes the sketch right after, which solves it
            # (a solve here solved a 2000-entity sketch twice per click, fix152)
            return geo, end_pos

        geo, end_pos = self.transaction("Add arc to sketch polyline" if segment == ARC else "Add line to sketch polyline",
                                        body)
        if endless:
            # one infinite line per two clicks: the next click starts a new one
            self.first_segment = True
            self.sug1, self.sug2, self.virtual_sug1 = [], [], []
            self._end_chain()
            return
        self.first_segment = False
        if close:
            self.first_segment = True
            self.preview([])
            self.readout(None, "")
            self.end()
            return
        self.sug1 = []
        self.virtual_sug1 = list(sug2)
        self.sug2 = []
        self.previous_curve, self.previous_pos = geo, end_pos
        self._update_transition_data()
        self.transition_away = self.transition_armed = False

        # when it leaves along the arc's tangent (fix160)
        self.transition = FREE
        self.free_after_arc = segment == ARC
        self.segment = LINE
        self.snap45 = False
        self.end_point = self.start
        self.snapper.set_reference(self.start)
        if self.ends_chain:
            self.ends_chain = False
            self.preview([])
            self.readout(None, "")
            self.end()

    def _update_transition_data(self):
        """dir_vec and start from the end (previous_pos) of previous_curve, after the solver."""
        g = self.snapper.geometry(self.previous_curve)
        if isinstance(g, Part.LineSegment):
            a, b = (g.StartPoint.x, g.StartPoint.y), (g.EndPoint.x, g.EndPoint.y)
            d = sub(b, a)
            if self.previous_pos == I.START:
                d = (-d[0], -d[1])
                self.start = a
            else:
                self.start = b
        elif isinstance(g, Part.ArcOfCircle):
            s, e = I.arc_ends_ccw(g)
            c = (g.Center.x, g.Center.y)
            if self.previous_pos == I.START:
                self.start = s
                r = sub(s, c)
                d = (r[1], -r[0])     # (0, 0, -1) x r
            else:
                self.start = e
                r = sub(e, c)
                d = (-r[1], r[0])     # (0, 0, 1) x r
        else:
            return
        n = length(d)
        self.dir_vec = (d[0] / n, d[1] / n) if n > 0 else (1.0, 0.0)



    def _right_click(self):
        if not param_bool(GENERAL_GROUP, "LineContextMenu", False):
            super()._right_click()  # ends the chain, or the tool
            return
        from PySide import QtGui, QtWidgets
        import FreeCADGui as Gui
        if self.menu is not None:
            try:
                self.menu.close()
            except RuntimeError as _fw_err:
                _fw_log("fwsketch/line.py:639", _fw_err)
        self._close_numeric_input()
        menu = QtWidgets.QMenu(Gui.getMainWindow())
        menu.setObjectName("SketcherLineContextMenu")
        menu.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        select = menu.addAction("Select")
        select.setObjectName("Select")
        select.triggered.connect(self.end)
        end_chain = menu.addAction("End Chain (double-click)")
        end_chain.setObjectName("EndChain")
        end_chain.setEnabled(not self.first_segment)
        end_chain.triggered.connect(self._end_chain)
        can_toggle = self.state == self.SECOND and self.previous_curve != -1
        arc = menu.addAction("Switch to Line\tA" if self.segment == ARC else "Switch to Arc\tA")
        arc.setObjectName("SwitchArc")
        arc.setEnabled(can_toggle)
        arc.triggered.connect(lambda: self.on_key(QtCore.Qt.Key_A))
        self.menu = menu
        menu.popup(QtGui.QCursor.pos())

    # --- on-screen numeric input (packages 22, 27) ------------------------------------------
    def _open_numeric_input(self, first):
        from PySide import QtGui, QtWidgets
        box = _LengthBox(self.viewport, first)
        box.accepted.connect(self._accept_typed_length)
        box.cancelled.connect(self._close_numeric_input)
        pos = self.viewport.mapFromGlobal(QtGui.QCursor.pos())
        box.move(pos.x() + 18, pos.y() + 18)  # beside the pointer, never under it
        box.show()
        box.setFocus()
        self.numeric = box

    def _close_numeric_input(self):
        box, self.numeric = getattr(self, "numeric", None), None
        if box is not None:
            try:
                box.hide()
                box.deleteLater()
            except RuntimeError as _fw_err:
                _fw_log("fwsketch/line.py:678", _fw_err)
        try:
            self.quarter.setFocus()
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/line.py:682", _fw_err)

    def _accept_typed_length(self, value):
        self._close_numeric_input()
        if self.state != self.SECOND or self.segment != LINE or not value > 0 or self.start is None:
            return
        d = sub(self.end_point, self.start) if self.end_point is not None else (0.0, 0.0)
        if length(d) < 1e-9:
            return
        end = add(self.start, mul(unit(d), value))
        # the segment's own relations (Horizontal, Vertical) still apply; nothing under the
        # pointer is joined to the typed end, and a typed segment never closes the chain
        self.typed_entry = True
        self.end_point = end
        self.sug2 = [s for s in self.sug2 if s.type in ("Horizontal", "Vertical") and s.geo == I.GEO_UNDEF
                     and s.pos == I.NONE]
        self.typed_length = value
        self._place_segment(self.decision)
        self.typed_length = 0.0
        self.typed_entry = False
        self._move()


class _LengthBox(QtCore.QObject):
    """The small box the typed length goes into; Enter accepts, Esc closes only the box."""
    accepted = QtCore.Signal(float)
    cancelled = QtCore.Signal()

    def __init__(self, parent, first):
        from PySide import QtWidgets
        super().__init__(parent)
        self.edit = QtWidgets.QLineEdit(parent)
        self.edit.setObjectName("FreeWorksLengthBox")
        self.edit.setFixedWidth(90)
        self.edit.setText(first)
        self.edit.installEventFilter(self)
        self.edit.returnPressed.connect(self._accept)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide on Windows can hand a filter a stale wrapper (a QWidgetItem) instead
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            self.cancelled.emit()
            return True
        return False

    def _accept(self):
        text = self.edit.text().strip().replace(",", ".")
        try:
            # a bare number is in the document's unit (3 in an IPS part is 3 in), as the Modify box
            value = float(App.Units.Quantity(text).getValueAs("mm")) if any(ch.isalpha() or ch == '"' for ch in text) \
                else float(text) * length_unit()[0]
        except Exception:
            return
        self.accepted.emit(value)

    def move(self, x, y):
        self.edit.move(x, y)

    def show(self):
        self.edit.show()

    def hide(self):
        self.edit.hide()

    def setFocus(self):
        self.edit.setFocus()
        self.edit.end(False)

    def deleteLater(self):
        self.edit.deleteLater()
        super().deleteLater()


class MidpointLineTool(SketchTool):
    ""



    def __init__(self, gdoc, sketch, construction=False):
        super().__init__(gdoc, sketch, construction)
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Create_Line"

    def title(self):
        return "Midpoint Line"

    def reset(self):
        super().reset()
        self.mid = None
        self.ends = None
        self.sug1, self.sug2 = [], []

    def on_move(self, p, px):
        if self.state == self.FIRST:
            self.snapper.set_reference(None)
            d = self.snap(p, px)
            self.preview([])
            self.readout(d.position, "")
            self.sug1 = self.seek(d.position, (0.0, 0.0))
            return self.sug1
        self.snapper.set_reference(self.mid)
        d = self.snap(p, px)
        end = d.position
        start = (2 * self.mid[0] - end[0], 2 * self.mid[1] - end[1])
        self.ends = (start, end)
        self.preview([[start, end]], points=[self.mid])
        self.readout(end, "(%s)" % fmt_length(length(sub(end, start))))
        self.sug2 = self.seek(end, sub(end, start))
        return self.sug2

    def on_click(self, d):
        if self.state == self.FIRST:
            self.mid = d.position
            self.state = self.SECOND
            self.snapper.set_reference(self.mid)
            return
        if self.ends is None or length(sub(self.ends[1], self.ends[0])) < 1e-9:
            return
        start, end = self.ends
        sug1, sug2 = list(self.sug1), list(self.sug2)
        sk = self.sketch

        def body():
            geo = self.add_geometry(Part.LineSegment(App.Vector(start[0], start[1], 0), App.Vector(end[0], end[1], 0)))
            R.remove_redundant_hv(sk, sug1, sug2, self.snapper.geometry)
            from .toolbase import automatic_relations
            held = False
            mids = R.resolve_model(self.snapper, sug1) if automatic_relations() else []
            for s in mids:
                if s.type == "Coincident" and s.pos != I.NONE:
                    sk.addConstraint(Sketcher.Constraint("Symmetric", geo, I.START, geo, I.END, s.geo, s.pos))
                    held = True
                    break
            if not held and mids:

                # line's midpoint there; FreeCAD has no such point, so a hidden helper point holds it
                from . import helpers
                helpers.lock_line_middle(sk, geo, self.mid, mids, lambda sugs, h: self.add_relations(sugs, h, I.MID))
            self.add_relations(sug2, geo, I.END)
            # solved by transaction() right after (review 1119 perf3: one solve a tool action)
            return geo

        self.transaction("Add sketch midpoint line", body)
        self.finish_or_continue()


_POINT_WINNERS = ("SketchPoint", "Midpoint", "Quadrant", "Intersection")   # snap.SKETCH_POINT ... (a point under the pointer)


def S_shift_held():
    from . import snap
    return snap.shift_held()


def start_line(construction=False):
    gdoc, sketch = edited_sketch()
    from .toolbase import active
    t = active()
    if type(t) is LineTool and t.state == t.SECOND and t.sketch is sketch:

        # the chain going from its last point; only For construction changes (sketch RMB hand check 11-12)
        t.construction = construction
        _tick_construction_box(construction)
        return t
    tool = LineTool(gdoc, sketch, construction)
    tool.begin()
    return tool


def _tick_construction_box(on):
    try:
        from PySide import QtWidgets
        import FreeCADGui as Gui
        mw = Gui.getMainWindow()
        for box in mw.findChildren(QtWidgets.QCheckBox):
            if box.objectName() in ("SWLineForConstruction", "SWCenterlineForConstruction") and box.isChecked() != bool(on):
                was = box.blockSignals(True)
                box.setChecked(bool(on))
                box.blockSignals(was)
    except Exception as _fw_err:
        _fw_log("fwsketch/line.py:857", _fw_err)


def start_centerline():
    ""
    return start_line(construction=True)


def start_midpoint_line():
    gdoc, sketch = edited_sketch()
    tool = MidpointLineTool(gdoc, sketch)
    tool.begin()
    return tool
