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

from .vec import sub, length
from . import inference as I
from . import relations as R
from . import splineedit as E
from .toolbase import SketchTool, edited_sketch, param_bool, GENERAL_GROUP

DOUBLE_CLICK_PIXELS = 4.0   # a second click this close to the last point ends the spline
CLOSE_PIXELS = 8.0          # a click this close to the first point closes it
CONTINUE, END, NOTHING = "continue", "end", "nothing"


class SplineTool(SketchTool):

    # the spline, Esc does (keeping the points). Without rcmenus the old right-click ends it.
    WANTS_CONTEXT_MENU = True

    def __init__(self, gdoc, sketch, construction=None):
        if construction is None:
            construction = param_bool(GENERAL_GROUP, "SplineForConstruction", False)
        super().__init__(gdoc, sketch, construction)
        self.last_spline = None     # geo id of the spline made last
        self.listeners = []         # callables (sketch, geo) after each spline
        self._finishing = False
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Create_BSpline"

    def title(self):
        return "Spline"

    def reset(self):
        super().reset()
        self.points = []            # the placed spline points
        self.sugs = []              # their automatic relations
        self.closed = False
        self.pending = None         # the pointer's snapped point
        self.pending_sug = []

    def hint_state(self):
        return 0 if not self.points else 1

    def starts_click_drag(self):
        return False

    # --- moves ------------------------------------------------------------------------------------
    def _near(self, a, b, pixels):
        px = getattr(self, "pixel", 0.0) or 0.0
        return a is not None and b is not None and length(sub(a, b)) <= max(pixels * px, 1e-9)

    def on_move(self, p, px):
        self.pixel = px
        self.snapper.set_reference(self.points[-1] if self.points else None)
        d = self.snap(p, px, allow_angle=bool(self.points))
        pos = d.position
        self.pending = pos
        if self.points and len(self.points) >= 2 and self._near(pos, self.points[0], CLOSE_PIXELS):
            # back on the first point: the preview closes
            self.pending_sug = []
            self.preview([E.sample(E.natural(self.points, True), 24 * len(self.points))], points=list(self.points))
            self.readout(pos, "")
            return []
        self.pending_sug = self.seek(pos, (0.0, 0.0), R.VERTEX)
        if self.points:
            pts = self.points + [pos]
            curve = E.natural(pts)
            self.preview([E.sample(curve, 24 * len(pts))] if curve is not None else [], points=list(self.points))
        else:
            self.preview([])
        self.readout(pos, "")
        return self.pending_sug

    # --- clicks -------------------------------------------------------------------------------------
    def on_click(self, d):
        pos = d.position
        if self.points and self._near(pos, self.points[-1], DOUBLE_CLICK_PIXELS):
            self.finish()               # the double-click's second click: the spline ends here
            return
        if len(self.points) >= 2 and self._near(pos, self.points[0], CLOSE_PIXELS):
            self.finish(closed=True)
            return
        self.points.append(pos)
        self.sugs.append(list(self.pending_sug))
        self.state = self.SECOND

    def on_key(self, key):
        return False

    def cancel_current(self):
        # right click while sketching: the spline ends with the points placed, the tool stays
        self.finish()

    def _key(self, key):
        from PySide import QtCore
        if key == QtCore.Qt.Key_Escape and len(self.points) >= 2:
            self.finish(then=END)      # Esc keeps the spline and ends the tool
            return True
        return super()._key(key)

    def end(self):
        # another tool, the button again or the sketch closing: a spline being sketched is kept
        if not self._finishing and len(self.points) >= 2:
            try:
                self.finish(then=NOTHING)
            except Exception as _fw_err:
                _fw_log("fwsketch/spline.py:138", _fw_err)
        super().end()

    # --- writing ------------------------------------------------------------------------------------
    def finish(self, closed=False, then=None):
        """Write the spline through the placed points (when there are two). then: CONTINUE (the
        next spline, or the tool ends outside ContinuousCreationMode), END or NOTHING."""
        then = then or CONTINUE
        pts, sugs = list(self.points), [list(s) for s in self.sugs]
        self.points, self.sugs = [], []
        geo = None
        if len(pts) >= 2 and not self._finishing:
            geo = self._write(pts, sugs, closed and len(pts) >= 3)
        if then == END:
            self.end()
        elif then == CONTINUE:
            self.finish_or_continue()
        return geo

    def _write(self, pts, sugs, closed):
        self._finishing = True
        try:
            construction = self.construction

            def body():
                geo, knots = E.add(self.sketch, pts, closed, construction)
                self.created.append(geo)
                for i, s in enumerate(sugs):
                    if not s:
                        continue
                    if not closed and i == 0:
                        self.add_relations(s, geo, I.START)
                    elif not closed and i == len(pts) - 1:
                        self.add_relations(s, geo, I.END)
                    elif i < len(knots) and knots[i] is not None:
                        self.add_relations(s, knots[i], I.START)
                self.sketch.solve()
                return geo

            geo = self.transaction("Add sketch spline", body)
            self.last_spline = geo
            self.closed = closed
            self.select_new([geo])
            for f in list(self.listeners):
                try:
                    f(self.sketch, geo)
                except Exception as _fw_err:
                    _fw_log("fwsketch/spline.py:185", _fw_err)
            try:
                from . import splinehandles
                splinehandles.show(self.gdoc, self.sketch, geo)
            except Exception as _fw_err:
                _fw_log("fwsketch/spline.py:190", _fw_err)
            return geo
        finally:
            self._finishing = False


SPLINE_INFO = ("BSplineCombVisible", "BSplineDegreeVisible", "BSplinePoleWeightVisible",
               "BSplineKnotMultiplicityVisible", "BSplineControlPolygonVisible")


def quiet_splines():
    ""

    import FreeCAD as App
    g = App.ParamGet(GENERAL_GROUP)
    have = set(g.GetBools())
    for key in SPLINE_INFO:
        if key not in have:
            g.SetBool(key, False)


def start_spline():
    quiet_splines()
    gdoc, sketch = edited_sketch()
    tool = SplineTool(gdoc, sketch)
    tool.begin()
    return tool
