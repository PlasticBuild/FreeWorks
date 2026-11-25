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


import FreeCAD as App
import Part

from .vec import sub, length
from . import inference as I
from . import relations as R
from . import splineedit as E
from .toolbase import SketchTool, edited_sketch

MAX_VERTICES = 8              # a Bezier style spline: degree 7 at most
DOUBLE_CLICK_PIXELS = 4.0
TOOL_PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchTools"

SPLINE_TYPES = ("Bezier", "B-Spline: Degree 3", "B-Spline: Degree 5", "B-Spline: Degree 7")


def spline_type():
    try:
        name = App.ParamGet(TOOL_PARAMS).GetString("StyleSplineType", "Bezier")
    except Exception:
        name = "Bezier"
    return name if name in SPLINE_TYPES else "Bezier"


def degree_of(kind):
    return None if kind == "Bezier" else int(kind.rsplit(" ", 1)[-1])


def bezier(poles):
    """The single-span Bezier through poles [(x, y)] as a Part.BSplineCurve (degree n - 1)."""
    n = len(poles)
    c = Part.BSplineCurve()
    c.buildFromPolesMultsKnots(poles=[App.Vector(p[0], p[1], 0) for p in poles], mults=[n, n], knots=[0.0, 1.0],
                               periodic=False, degree=n - 1)
    return c


def bspline(poles, degree):
    ""

    n = len(poles)
    d = max(1, min(degree, n - 1))
    spans = n - d
    knots = [k / float(spans) for k in range(spans + 1)]
    mults = [d + 1] + [1] * (spans - 1) + [d + 1]
    c = Part.BSplineCurve()
    c.buildFromPolesMultsKnots(poles=[App.Vector(p[0], p[1], 0) for p in poles], mults=mults, knots=knots,
                               periodic=False, degree=d)
    return c


def style_curve(poles, kind=None):
    """The style spline of the page's Spline Type (or kind) on these control vertices."""
    d = degree_of(kind or spline_type())
    return bezier(poles) if d is None else bspline(poles, d)


def reshaped(curve, poles):
    """curve with its control vertices moved to poles (its degree and spans kept)."""
    c = curve.copy()
    for i, p in enumerate(poles):
        c.setPole(i + 1, App.Vector(p[0], p[1], 0))
    return c


class StyleSplineTool(SketchTool):

    # the spline, Esc does (keeping the points). Without rcmenus the old right-click ends it.
    WANTS_CONTEXT_MENU = True

    def __init__(self, gdoc, sketch, construction=False):
        super().__init__(gdoc, sketch, construction)
        self.last_spline = None
        self.listeners = []
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Create_BSpline"

    def title(self):
        return "Style Spline"

    def reset(self):
        super().reset()
        self.points = []
        self.sugs = []
        self.pending_sug = []

    def hint_state(self):
        return 0 if not self.points else 1

    def starts_click_drag(self):
        return False

    def _near(self, a, b, pixels):
        px = getattr(self, "pixel", 0.0) or 0.0
        return length(sub(a, b)) <= max(pixels * px, 1e-9)

    def on_move(self, p, px):
        self.pixel = px
        self.snapper.set_reference(self.points[-1] if self.points else None)
        d = self.snap(p, px, allow_angle=bool(self.points))
        pos = d.position
        self.pending_sug = self.seek(pos, (0.0, 0.0), R.VERTEX)
        if self.points:
            poles = self.points + [pos]
            self.preview([E.sample(style_curve(poles), 64)], construction=[poles], points=list(self.points))
        else:
            self.preview([])
        self.readout(pos, "")
        return self.pending_sug

    def on_click(self, d):
        pos = d.position
        if self.points and self._near(pos, self.points[-1], DOUBLE_CLICK_PIXELS):
            self.finish()
            return
        self.points.append(pos)
        self.sugs.append(list(self.pending_sug))
        self.state = self.SECOND
        if len(self.points) >= MAX_VERTICES and degree_of(spline_type()) is None:
            self.finish()

    def cancel_current(self):
        self.finish()

    def _key(self, key):
        from PySide import QtCore
        if key == QtCore.Qt.Key_Escape and len(self.points) >= 3:
            self.finish(end_tool=True)
            return True
        return super()._key(key)

    def end(self):
        # another tool, the button again or the sketch closing: a style spline being sketched is kept
        if not getattr(self, "_finishing", False) and len(self.points) >= 3:
            try:
                self._finishing = True
                self.finish(then_end=False)
            except Exception as _fw_err:
                _fw_log("fwsketch/stylespline.py:168", _fw_err)
            finally:
                self._finishing = False
        super().end()

    def finish(self, end_tool=False, then_end=True):
        pts, sugs = list(self.points), list(self.sugs)
        self.points, self.sugs = [], []
        if len(pts) >= 3:
            construction = self.construction

            def body():
                geo = add(self.sketch, pts, construction)
                self.created.append(geo)
                if sugs[0]:
                    self.add_relations(sugs[0], geo, I.START)
                if sugs[-1]:
                    self.add_relations(sugs[-1], geo, I.END)
                self.sketch.solve()
                return geo
            geo = self.transaction("Add sketch style spline", body)
            self.last_spline = geo
            for f in list(self.listeners):
                try:
                    f(self.sketch, geo)
                except Exception as _fw_err:
                    _fw_log("fwsketch/stylespline.py:194", _fw_err)
            try:
                from . import splinehandles
                splinehandles.show(self.gdoc, self.sketch, geo)
            except Exception as _fw_err:
                _fw_log("fwsketch/stylespline.py:199", _fw_err)
        if not then_end:
            return
        if end_tool:
            self.end()
        else:
            self.finish_or_continue()


def add(sketch, poles, construction=False, kind=None):
    """Write a style spline with these control vertices; returns its geo id."""
    geo = sketch.addGeometry(style_curve(poles, kind), bool(construction))
    E._expose(sketch, geo)
    # no spline points: the ends are the curve's own vertices, the shape is the polygon's
    kps = [g for g in E.info(sketch, geo)["knot_points"] if g is not None]
    if kps:
        sketch.delGeometries(sorted(kps))
    return geo


def start_style_spline():
    from .spline import quiet_splines
    quiet_splines()
    gdoc, sketch = edited_sketch()
    tool = StyleSplineTool(gdoc, sketch)
    tool.begin()
    return tool
