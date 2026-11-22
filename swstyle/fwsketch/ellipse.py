# SPDX-License-Identifier: LGPL-2.1-or-later
""








import math

import FreeCAD as App
import Part

from .vec import sub, length
from . import inference as I
from . import relations as R
from .toolbase import SketchTool, fmt_length, edited_sketch, toward

FULL, PARTIAL = "full", "partial"


def ellipse_points(c, a, b, phi, u0=0.0, u1=2 * math.pi, n=64):
    cs, sn = math.cos(phi), math.sin(phi)
    pts = []
    for i in range(n + 1):
        u = u0 + (u1 - u0) * i / n
        x, y = a * math.cos(u), b * math.sin(u)
        pts.append((c[0] + x * cs - y * sn, c[1] + x * sn + y * cs))
    return pts


def param_of(c, phi, a, b, p):
    """The ellipse parameter of the point of the ellipse in the direction of p from the centre."""
    dx, dy = p[0] - c[0], p[1] - c[1]
    cs, sn = math.cos(phi), math.sin(phi)
    x, y = dx * cs + dy * sn, -dx * sn + dy * cs
    return math.atan2(y / b, x / a) if a > 0 and b > 0 else 0.0


def minor_of(c, phi, p):
    ""
    dx, dy = p[0] - c[0], p[1] - c[1]
    return abs(-dx * math.sin(phi) + dy * math.cos(phi))


class EllipseTool(SketchTool):
    def __init__(self, gdoc, sketch, method=FULL):
        super().__init__(gdoc, sketch)
        self.method = method
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Create_ArcOfEllipse" if self.method == PARTIAL else "Sketcher_Pointer_Create_EllipseByCenter"

    def title(self):
        return "Partial Ellipse" if self.method == PARTIAL else "Ellipse"

    def reset(self):
        super().reset()
        self.center = None
        self.a = self.b = 0.0
        self.phi = 0.0
        self.u0 = None
        self.u1 = None
        self.sweep = 0.0
        self.sug = [[], [], [], []]

    def on_move(self, p, px):
        if self.state == self.FIRST:
            self.snapper.set_reference(None)
            d = self.snap(p, px)
            self.preview([])
            self.readout(d.position, "")
            self.sug[0] = self.seek(d.position, (0.0, 0.0), R.VERTEX)
            return self.sug[0]
        c = self.center
        self.snapper.set_reference(c)
        if self.state == self.SECOND:
            d = self.snap(p, px, allow_angle=True)
            pos = d.position
            self.a = length(sub(pos, c))
            self.phi = math.atan2(pos[1] - c[1], pos[0] - c[0])
            end = (2 * c[0] - pos[0], 2 * c[1] - pos[1])
            self.preview([], construction=[[end, pos]], points=[c])
            self.readout(pos, "R = %s" % fmt_length(self.a))
            self.sug[1] = self.seek(pos, sub(pos, c), R.CURVE)
            return self.sug[1]
        d = self.snap(p, px, allow_angle=False)
        pos = d.position
        if self.state == self.THIRD:
            self.b = max(minor_of(c, self.phi, pos), 1e-9)
            if self.method == PARTIAL:
                self.u0 = param_of(c, self.phi, self.a, self.b, pos)
                self.preview([ellipse_points(c, self.a, self.b, self.phi)], points=[c])
            else:
                self.preview([ellipse_points(c, self.a, self.b, self.phi)], points=[c])
            self.readout(pos, "R = %s  r = %s" % (fmt_length(self.a), fmt_length(self.b)))
            self.sug[2] = self.seek(pos, (0.0, 0.0), R.CURVE)
            return self.sug[2]
        # partial: the end of the arc, the sweep follows the pointer the way it went round
        u = param_of(c, self.phi, self.a, self.b, pos)
        prev = self.u1 if self.u1 is not None else self.u0
        step = math.atan2(math.sin(u - prev), math.cos(u - prev))
        self.sweep = max(-2 * math.pi, min(2 * math.pi, self.sweep + step))
        self.u1 = u
        lo, hi = (self.u0, self.u0 + self.sweep) if self.sweep >= 0 else (self.u0 + self.sweep, self.u0)
        self.preview([ellipse_points(c, self.a, self.b, self.phi, lo, hi)], points=[c])
        self.readout(pos, "%.1f°" % abs(math.degrees(self.sweep)))
        self.sug[3] = self.seek(pos, (0.0, 0.0), R.CURVE)
        return self.sug[3]

    # --- on-screen numeric input (fix65): the two half axes -----------------------------------
    def numeric_spec(self):
        cur = self.decision.position
        c = self.center
        if self.state == self.SECOND:
            return ("Radius 1",), lambda v: toward(c, cur, v[0]) if v[0] else None, ("a",)
        if self.state == self.THIRD:
            n = (-math.sin(self.phi), math.cos(self.phi))
            side = -1.0 if (cur[0] - c[0]) * n[0] + (cur[1] - c[1]) * n[1] < 0 else 1.0
            return ("Radius 2",), lambda v: (c[0] + n[0] * side * v[0], c[1] + n[1] * side * v[0]) if v[0] else None, ("b",)
        return None

    def on_click(self, d):
        if self.state == self.FIRST:
            self.center = d.position
            self.state = self.SECOND
            return
        if self.state == self.SECOND:
            if self.a < 1e-9:
                return
            self.state = self.THIRD
            return
        if self.state == self.THIRD and self.method == PARTIAL:
            if self.b < 1e-9:
                return
            self.sweep, self.u1 = 0.0, None
            self.state = 3
            return
        if self.method == PARTIAL and abs(self.sweep) < 1e-6:
            return
        self._write()

    def _write(self):
        c, a, b, phi = self.center, self.a, self.b, self.phi
        sugs = [list(s) for s in self.sug]
        method = self.method
        if b > a:
            # FreeCAD wants the major axis first: swap the axes, turn by 90 degrees
            a, b, phi = b, a, phi + math.pi / 2
            shift = -math.pi / 2
        else:
            shift = 0.0
        cs, sn = math.cos(phi), math.sin(phi)
        center = App.Vector(c[0], c[1], 0)
        major = App.Vector(c[0] + a * cs, c[1] + a * sn, 0)
        minor = App.Vector(c[0] - b * sn, c[1] + b * cs, 0)
        if method == PARTIAL:
            lo, hi = (self.u0, self.u0 + self.sweep) if self.sweep >= 0 else (self.u0 + self.sweep, self.u0)
            lo, hi = lo + shift, hi + shift

        def body():
            e = Part.Ellipse(major, minor, center)
            geo = self.add_geometry(Part.ArcOfEllipse(e, lo, hi) if method == PARTIAL else e)
            self.add_relations(sugs[0], geo, I.MID)

            def on_point(k):
                return [s for s in sugs[k] if s.type in ("Coincident", "PointOnObject") and s.pos != I.NONE]
            ons = [R.Suggestion("PointOnObject", s.geo, s.pos) for k in (1, 2) for s in on_point(k)]
            if method == PARTIAL:
                start = ons[len(on_point(1)):]
                ons = ons[:len(ons) - len(start)]
                if start:
                    self.add_relations([R.Suggestion("Coincident", s.geo, s.pos) for s in start], geo,
                                       I.START if self.sweep >= 0 else I.END)
            if ons:
                self.add_relations(ons, geo, I.NONE)
            self.sketch.solve()
            return geo

        self.transaction("Add sketch ellipse", body)
        self.finish_or_continue()

    def is_first_state(self):
        return self.state == self.FIRST


def start_ellipse(method=FULL):
    gdoc, sketch = edited_sketch()
    tool = EllipseTool(gdoc, sketch, method)
    tool.begin()
    return tool


def start_partial_ellipse():
    return start_ellipse(PARTIAL)
