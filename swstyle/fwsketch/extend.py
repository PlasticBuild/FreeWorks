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
from PySide import QtCore

from .vec import sub, length, dot
from .toolbase import SketchTool, edited_sketch, other_buttons
from . import trim as T
from . import helpers as H

EPS = 1e-7
TWO_PI = 2.0 * math.pi


def drop_middle(sketch, geo):
    """Delete the hidden Midpoint Line helper that holds geo's middle on a curve (fix223): the
    extension moves the middle, and the solver would drag the curve it sits on (reviewer 11-19).
    Returns the deleted ids, highest first."""
    gone = set()
    for c in sketch.Constraints:
        if c.Type == "Symmetric" and c.First == geo and c.Second == geo and c.Third is not None and c.Third >= 0:
            t = H.tag_of(sketch.Geometry[c.Third])
            if t is not None and t[0] == "midline":
                gone.add(c.Third)
    for h in sorted(gone, reverse=True):
        sketch.delGeometry(h)       # its relations go with it
    return sorted(gone, reverse=True)


def _shift(i, gone):
    return i - sum(1 for h in gone if h < i) if i is not None and i >= 0 else i


def _others(sketch, geo):
    out = [(i, h) for i, h in enumerate(sketch.Geometry) if i != geo]
    try:
        out += [(-(k + 1), h) for k, h in enumerate(sketch.ExternalGeo) if k >= 2]
    except Exception as _fw_err:
        _fw_log("fwsketch/extend.py:40", _fw_err)
    return out


def _hits(curve, sketch, geo):
    for i, h in _others(sketch, geo):
        try:
            points = curve.intersect(h)
        except Exception:
            continue
        for p in points:
            yield i, ((p.X, p.Y) if hasattr(p, "X") else (p.x, p.y))


def extension(sketch, geo, pointer):
    """(end pos 1/2, increment, reached point, target geo, end point before) for extending geo at
    its end nearest pointer, or None when nothing is met. A line's increment is a length, an arc's
    an angle (SketchObject.extend)."""
    g = sketch.Geometry[geo]
    s, e = T.pt(g.StartPoint), T.pt(g.EndPoint)
    pos = 1 if length(sub(pointer, s)) < length(sub(pointer, e)) else 2
    end = s if pos == 1 else e
    best = None
    if g.TypeId == "Part::GeomLineSegment":
        other = e if pos == 1 else s
        d = sub(end, other)
        n = length(d)
        if n < EPS:
            return None
        u = (d[0] / n, d[1] / n)
        ray = Part.Line(T.V(end), T.V((end[0] + u[0], end[1] + u[1])))
        for i, q in _hits(ray, sketch, geo):
            t = dot(sub(q, end), u)
            if t > 1e-6 and (best is None or t < best[1]):
                best = (pos, t, q, i, end)
        return best
    if g.TypeId == "Part::GeomArcOfCircle":
        c, r = T.pt(g.Center), g.Radius
        circle = Part.Circle(g.Center, App.Vector(0, 0, 1), r)
        a_end = g.FirstParameter if pos == 1 else g.LastParameter
        for i, q in _hits(circle, sketch, geo):
            a = math.atan2(q[1] - c[1], q[0] - c[0])
            # away from the arc: clockwise from its start, counter-clockwise from its end
            sweep = T.ccw(a, a_end) if pos == 1 else T.ccw(a_end, a)
            free = TWO_PI - T.ccw(g.FirstParameter, g.LastParameter)
            if 1e-6 < sweep < free - 1e-6 and (best is None or sweep < best[1]):
                best = (pos, sweep, q, i, end)
        return best
    return None


def _preview_points(sketch, geo, ext):
    g = sketch.Geometry[geo]
    pos, inc, q, _, end = ext
    if g.TypeId == "Part::GeomLineSegment":
        return [end, q]
    c, r = T.pt(g.Center), g.Radius
    a0 = g.FirstParameter if pos == 1 else g.LastParameter
    sign = -1.0 if pos == 1 else 1.0
    return [(c[0] + r * math.cos(a0 + sign * inc * k / 24.0), c[1] + r * math.sin(a0 + sign * inc * k / 24.0))
            for k in range(25)]


class ExtendTool(SketchTool):
    def __init__(self, gdoc, sketch):
        super().__init__(gdoc, sketch)
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Extension"

    def title(self):
        return "Extend Entities"

    def starts_click_drag(self):
        return False

    def reset(self):
        super().reset()
        self.hover = None
        self.ext = None
        self.last = None        # (geo, target, point) of the last extension, for tests

    def _filter(self, obj, event):
        # mouse moves pass through, so FreeCAD preselects the curve under the pointer (as Trim)
        if (obj is self.viewport or obj is self.quarter) and event.type() == QtCore.QEvent.MouseMove \
                and self._press is None:
            if self._other_down or other_buttons(event):
                return False
            QtCore.QTimer.singleShot(0, self._move)
            return False
        return super()._filter(obj, event)

    def on_move(self, p, px):
        d = self.snap(p, px, allow_point=False, allow_edge=False, allow_angle=False, allow_grid=False)
        sk = self.sketch
        geo = T.hovered_edge(sk)
        ok = geo is not None and 0 <= geo < sk.GeometryCount and \
            sk.Geometry[geo].TypeId in ("Part::GeomLineSegment", "Part::GeomArcOfCircle")
        if ok and not T.near_curve(sk.Geometry[geo], d.position, 8.0 * px):
            ok = False
        self.hover = geo if ok else None
        self.ext = extension(sk, geo, d.position) if ok else None
        self.preview([_preview_points(sk, geo, self.ext)] if self.ext else [])
        return []

    def on_click(self, d):
        if self.hover is None or self.ext is None:
            return
        geo, (pos, inc, q, target, _) = self.hover, self.ext
        sk = self.sketch

        def body():
            gone = drop_middle(sk, geo)
            g, tgt = _shift(geo, gone), _shift(target, gone)
            sk.extend(g, inc, pos)
            tg = sk.Geometry[tgt] if tgt >= 0 else None
            at_end = None
            if tg is not None and hasattr(tg, "StartPoint"):
                for tp, v in ((1, tg.StartPoint), (2, tg.EndPoint)):
                    if math.hypot(v.x - q[0], v.y - q[1]) < 1e-6:
                        at_end = tp
            if at_end is not None:
                sk.addConstraint(Sketcher.Constraint("Coincident", g, pos, tgt, at_end))
            else:
                sk.addConstraint(Sketcher.Constraint("PointOnObject", g, pos, tgt))
            sk.solve()

        try:
            Gui.Selection.rmPreselect()
        except Exception as _fw_err:
            _fw_log("fwsketch/extend.py:169", _fw_err)
        try:
            self.transaction("Extend edge", body)
            self.last = (geo, target, q)
        except Exception as e:
            App.Console.PrintError("FreeCAD Extend: %s\n" % e)
        self.hover = self.ext = None
        self.preview([])


def start_extend():
    gdoc, sketch = edited_sketch()
    t = ExtendTool(gdoc, sketch)
    t.begin()
    return t
