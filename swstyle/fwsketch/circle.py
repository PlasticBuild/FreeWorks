# SPDX-License-Identifier: LGPL-2.1-or-later
"""Circle and Perimeter Circle on stock FreeCAD (DrawSketchHandlerCircle.h, Center and ThreeRim).

Circle: click (or press) the centre, click (or release) a point on the rim; the radius is read
out. Perimeter circle: three points on the rim. Each pick gets its automatic relations: the
centre as a point, the rim picks as a curve (On edge, Tangent)."""

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

from .vec import sub, length
from . import inference as I
from . import relations as R
from . import geom
from .toolbase import SketchTool, fmt_length, edited_sketch, param_bool, GENERAL_GROUP
from . import snap as S

CENTER, PERIMETER = "center", "perimeter"
ON_CURVE = (S.SKETCH_CURVE, S.AXIS, S.AXIS_GRID, S.MIDPOINT, S.QUADRANT)


def _pick_constraint(snapper, d):
    ""


    if d is None:
        return ("free", d.position if d is not None else None)
    if d.winner in ON_CURVE and d.geo not in (None, I.GEO_UNDEF) and not S.is_model_geo(d.geo):
        g = snapper.geometry(d.geo)
        if isinstance(g, Part.LineSegment):
            a, b = (g.StartPoint.x, g.StartPoint.y), (g.EndPoint.x, g.EndPoint.y)
            return ("line", (d.geo, a, b))
        if isinstance(g, (Part.Circle, Part.ArcOfCircle)):
            return ("circle", (d.geo, (g.Center.x, g.Center.y), g.Radius))
    return ("free", d.position)


def fit_circle(picks, positions):
    """The circle tangent to the picked lines and circles and through the free picks (Newton from
    the circle through the three pick points); None when it does not settle. The side of each
    picked line (and inside or outside each picked circle) is first taken from the circle through
    the picks; when that has no solution (a pick on a line puts that circle across the line), the
    other sides are tried and the solution nearest that circle wins (relations matrix 11-19)."""
    c0 = geom.circumcenter(*positions)
    if c0 is None:
        return None
    r0 = length(sub(positions[0], c0))
    n = sum(1 for k, _ in picks if k in ("line", "circle"))
    best = None
    for flip in range(1 << n):
        found = _fit_sides(picks, positions, flip)
        if found is None:
            continue
        (x, y), r = found
        score = math.hypot(x - c0[0], y - c0[1]) + abs(r - r0)
        if best is None or score < best[0]:
            best = (score, found)
        if flip == 0:
            break           # the sides of the circle through the picks hold: as before
    return best[1] if best is not None else None


def _fit_sides(picks, positions, flip):
    c0 = geom.circumcenter(*positions)
    if c0 is None:
        return None
    x, y = c0
    r = length(sub(positions[0], c0))
    signs = []
    for (kind, data), q in zip(picks, positions):
        if kind == "line":
            _, a, b = data
            t = sub(b, a); n = length(t)
            if n < 1e-12:
                return None
            nx, ny = -t[1] / n, t[0] / n
            signs.append(1.0 if (x - a[0]) * nx + (y - a[1]) * ny >= 0 else -1.0)
        elif kind == "circle":
            _, cc, R0 = data
            signs.append(1.0 if length(sub(c0, cc)) >= R0 else -1.0)   # outside: R + r, inside: R - r
        else:
            signs.append(0.0)

    k = 0
    for i, sg in enumerate(signs):
        if sg != 0.0:
            if flip >> k & 1:
                signs[i] = -sg
            k += 1

    def residuals(x, y, r):
        out = []
        for (kind, data), q, sg in zip(picks, positions, signs):
            if kind == "line":
                _, a, b = data
                t = sub(b, a); n = length(t)
                nx, ny = -t[1] / n, t[0] / n
                out.append(sg * ((x - a[0]) * nx + (y - a[1]) * ny) - r)
            elif kind == "circle":
                _, cc, R0 = data
                dd = math.hypot(x - cc[0], y - cc[1])
                out.append(dd - (R0 + r) if sg > 0 else dd - abs(R0 - r))
            else:
                out.append(math.hypot(x - q[0], y - q[1]) - r)
        return out

    for _ in range(40):
        f = residuals(x, y, r)
        if max(abs(v) for v in f) < 1e-10:
            break
        h = 1e-7
        J = []
        for k in range(3):
            v = [x, y, r]
            v[k] += h
            fk = residuals(*v)
            J.append([(fk[i] - f[i]) / h for i in range(3)])
        # J[k][i] = d f_i / d v_k; solve sum_k J[k][i] dv_k = -f_i
        A = [[J[k][i] for k in range(3)] for i in range(3)]
        try:
            dv = _solve3(A, [-v for v in f])
        except ZeroDivisionError:
            return None
        x, y, r = x + dv[0], y + dv[1], r + dv[2]
    if r <= 1e-9 or max(abs(v) for v in residuals(x, y, r)) > 1e-6:
        return None
    return (x, y), r


def _solve3(A, b):
    m = [row[:] + [bb] for row, bb in zip(A, b)]
    for i in range(3):
        piv = max(range(i, 3), key=lambda k: abs(m[k][i]))
        if abs(m[piv][i]) < 1e-14:
            raise ZeroDivisionError
        m[i], m[piv] = m[piv], m[i]
        for k in range(i + 1, 3):
            f = m[k][i] / m[i][i]
            for j in range(i, 4):
                m[k][j] -= f * m[i][j]
    out = [0.0] * 3
    for i in (2, 1, 0):
        out[i] = (m[i][3] - sum(m[i][j] * out[j] for j in range(i + 1, 3))) / m[i][i]
    return out


class CircleTool(SketchTool):
    def __init__(self, gdoc, sketch, method=CENTER):
        super().__init__(gdoc, sketch)
        self.method = method
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Create_3PointCircle" if self.method == PERIMETER else "Sketcher_Pointer_Create_Circle"

    def title(self):
        return "Perimeter Circle" if self.method == PERIMETER else "Circle"

    def reset(self):
        super().reset()
        self.points = []
        self.picks = []          # Perimeter Circle: what each pick holds the circle to
        self.center = None
        self.radius = 0.0
        self.sug = [[], [], []]
        self.fit_failed = False
        self._close_numeric_input()


    def numeric_input_wanted(self):
        return self.method == CENTER and self.state == self.SECOND and getattr(self, "numeric", None) is None \
            and param_bool(GENERAL_GROUP, "OnScreenNumericInput", False)

    def claims_key(self, key):
        from .line import LineTool
        if self.numeric_input_wanted() and LineTool._typed_character(key) is not None:
            return True
        return super().claims_key(key)

    def on_key(self, key):
        from .line import LineTool
        typed = LineTool._typed_character(key)
        if typed is not None and self.numeric_input_wanted():
            from PySide import QtGui
            from .line import _LengthBox
            box = _LengthBox(self.viewport, typed)
            box.accepted.connect(self._typed_radius)
            box.cancelled.connect(self._close_numeric_input)
            pos = self.viewport.mapFromGlobal(QtGui.QCursor.pos())
            box.move(pos.x() + 18, pos.y() + 18)
            box.show()
            box.edit.setFocus()
            self.numeric = box
            return True
        return False

    def _close_numeric_input(self):
        box, self.numeric = getattr(self, "numeric", None), None
        if box is not None:
            try:
                box.hide()
                box.deleteLater()
            except RuntimeError as _fw_err:
                _fw_log("fwsketch/circle.py:187", _fw_err)
            try:
                self.quarter.setFocus()
            except (RuntimeError, AttributeError) as _fw_err:
                _fw_log("fwsketch/circle.py:191", _fw_err)

    def _typed_radius(self, value):
        self._close_numeric_input()
        if self.state != self.SECOND or self.center is None or not value > 0:
            return
        self.radius = value
        self.sug[1] = []                 # nothing under the pointer is tied to a typed circle
        self._place(dimension=value if param_bool(GENERAL_GROUP, "NumericInputAddsDimension", True) else None)

    def on_move(self, p, px):
        if self.state == self.FIRST:
            self.snapper.set_reference(None)
            d = self.snap(p, px)
            self.preview([])
            self.readout(d.position, "")
            if self.method == PERIMETER:
                self.sug[0] = self._perimeter_sug(d.position, d)
            else:
                self.sug[0] = self.seek(d.position, (0.0, 0.0), R.VERTEX)
            return self.sug[0]
        if self.method == CENTER:
            self.snapper.set_reference(self.center)
            d = self.snap(p, px, allow_angle=True)
            pos = d.position
            self.radius = length(sub(pos, self.center))
            self._draw_circle(pos)

            self.readout(pos, "R = %s" % fmt_length(self.radius))
            self.sug[1] = self.seek(pos, sub(pos, self.center), R.CURVE)
            return self.sug[1]
        self.snapper.set_reference(self.points[0])
        d = self.snap(p, px, allow_angle=False)
        pos = d.position
        if self.state == self.SECOND:
            self.center = ((pos[0] + self.points[0][0]) / 2, (pos[1] + self.points[0][1]) / 2)
            self.radius = length(sub(pos, self.center))
            self._draw_circle()
            self.readout(pos, "")
            self.sug[1] = self._perimeter_sug(pos, d)
            return self.sug[1]
        picks = self.picks + [_pick_constraint(self.snapper, d)]
        curved = any(k in ("line", "circle") for k, _ in picks)
        fitted = fit_circle(picks, self.points + [pos]) if curved else None
        # no circle is tangent to those picks: the preview is the circle through the three points, so
        # the click adds no Tangent either (else the solver pulls the sketch to a circle not shown)
        self.fit_failed = curved and fitted is None
        if fitted is not None:
            self.center, self.radius = fitted
            self._draw_circle()
        else:
            c = geom.circumcenter(self.points[0], self.points[1], pos)
            if c is not None:
                self.center, self.radius = c, length(sub(pos, c))
                self._draw_circle()
        self.readout(pos, "")
        self.sug[2] = self._perimeter_sug(pos, d)
        if self.fit_failed:
            self.sug[2] = [x for x in self.sug[2] if x.type != "Tangent"]
        return self.sug[2]

    def _perimeter_sug(self, pos, d):
        ""
        sug = self.seek(pos, (0.0, 0.0), R.CURVE)
        kind, data = _pick_constraint(self.snapper, d)
        if kind in ("line", "circle"):
            geo = data[0]
            sug = [x for x in sug if x.geo != geo] + [R.Suggestion("Tangent", geo)]
        return sug

    def _draw_circle(self, pointer=None):
        if self.radius > 1e-9:
            self.preview([geom.circle_points(self.center, self.radius)],
                         construction=[[self.center, pointer]] if pointer is not None else (),
                         points=[self.center])
        else:
            self.preview([])

    def on_click(self, d):
        if self.state == self.FIRST:
            if self.method == CENTER:
                self.center = d.position
            self.points = [d.position]
            self.picks = [_pick_constraint(self.snapper, d)]
            self.state = self.SECOND
            return
        if self.method == PERIMETER and self.state == self.SECOND:
            self.points.append(d.position)
            self.picks.append(_pick_constraint(self.snapper, d))
            self.state = self.THIRD
            return
        self._place()

    def _place(self, dimension=None):
        if self.radius < 1e-9 or self.center is None:
            return
        sugs = [list(s) for s in self.sug]
        if self.method == PERIMETER and getattr(self, "fit_failed", False):
            sugs = [[x for x in s if x.type != "Tangent"] for s in sugs]
        center, radius = self.center, self.radius
        sk = self.sketch

        def body():
            geo = self.add_geometry(Part.Circle(App.Vector(center[0], center[1], 0), App.Vector(0, 0, 1), radius))
            if self.method == CENTER:
                self.add_relations(sugs[0], geo, I.MID)
                self.add_relations(sugs[1], geo, I.NONE)
            else:
                for s in sugs:
                    self.add_relations(s, geo, I.NONE)
            if dimension is not None:
                import Sketcher

                if param_bool(GENERAL_GROUP, "CircleDiameterDimension", True):
                    sk.addConstraint(Sketcher.Constraint("Diameter", geo, 2.0 * dimension))
                else:
                    sk.addConstraint(Sketcher.Constraint("Radius", geo, dimension))
            # solved by transaction() right after (review 1119 perf3: one solve a tool action)
            return geo

        self.transaction("Add sketch circle", body)
        self.finish_or_continue()


def start_circle(method=CENTER):
    gdoc, sketch = edited_sketch()
    tool = CircleTool(gdoc, sketch, method)
    tool.begin()
    return tool


def start_perimeter_circle():
    return start_circle(PERIMETER)
