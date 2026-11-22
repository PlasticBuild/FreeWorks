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
from PySide import QtCore, QtWidgets

from .vec import sub, length
from . import splineedit as E
from .toolbase import ViewMath

HANDLE_PIXELS = 36.0     # a weight of 1 (100 %) draws this long on each side of the point
PICK_PIXELS = 8.0
HANDLE_COLOR = (0.25, 0.45, 0.95)     # a driven (held) handle
FREE_COLOR = (0.55, 0.55, 0.6)        # a handle nobody set yet
DRAG_COLOR = (1.0, 0.65, 0.0)

_current = None
_watcher = None


def current():
    return _current


def show(gdoc, sketch, geo):
    global _current
    if _current is not None and _current.sketch is sketch and _current.geo == geo:
        _current.refresh()
        return _current
    hide()
    if not E.is_spline(sketch, geo):
        return None
    from . import sysopts
    if not sysopts.on(sysopts.SPLINE_HANDLES):     # Options > Sketch: no tangency handles
        return None
    _current = Handles(gdoc, sketch, geo)
    return _current


def hide():
    global _current
    if _current is not None:
        _current.remove()
    _current = None


class Handles(QtCore.QObject, ViewMath):
    def __init__(self, gdoc, sketch, geo):
        super().__init__()
        self.setup_view(gdoc, sketch)
        self.geo = geo
        self.drag = None              # (index, side +1/-1) while a diamond is dragged
        self.style = False            # a style spline: the control polygon instead of handles
        self.drag_sides = None        # (angle, weight 1, weight 2) while a diamond is dragged
        self.drag_alt = False         # Alt held at the press: both sides' weights change alike
        self.vertices = []
        self.drag_tangent = None      # (angle, weight) the drag would write
        self.data = None
        from pivy import coin
        self.coin = coin
        self.root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        self.root.addChild(pick)
        self.root.addChild(light)
        self.free_lines = self._lineset(FREE_COLOR, 1)
        self.lines = self._lineset(HANDLE_COLOR, 2)
        self.preview = self._lineset(DRAG_COLOR, 2)
        sep = coin.SoSeparator()
        c = coin.SoBaseColor()
        c.rgb = HANDLE_COLOR
        self.tip_co = coin.SoCoordinate3()
        self.tip_ms = coin.SoMarkerSet()
        self.tip_ms.markerIndex = coin.SoMarkerSet.DIAMOND_FILLED_9_9
        for n in (c, self.tip_co, self.tip_ms):
            sep.addChild(n)
        self.root.addChild(sep)
        self.view.getSceneGraph().addChild(self.root)
        # on the application, as the sketch tools filter (an application filter sees the view's
        # events before any filter on the view): installed later, ours is asked first
        self._app = QtWidgets.QApplication.instance()
        from . import appevents
        appevents.listen(self, (QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove))   # one application filter (fix65)
        self.refresh()

    def _lineset(self, rgb, width):
        coin = self.coin
        sep = coin.SoSeparator()
        c = coin.SoBaseColor()
        c.rgb = rgb
        style = coin.SoDrawStyle()
        style.lineWidth = width * self.ratio
        co = coin.SoCoordinate3()
        ls = coin.SoLineSet()
        ls.numVertices.setNum(0)
        for n in (c, style, co, ls):
            sep.addChild(n)
        self.root.addChild(sep)
        return co, ls

    def _g(self, p):
        v = self.matrix.multVec(App.Vector(p[0], p[1], 0))
        return (v.x, v.y, v.z)

    def _set_lines(self, which, polylines):
        co, ls = which
        pts, counts = [], []
        for poly in polylines:
            if len(poly) >= 2:
                pts.extend(self._g(p) for p in poly)
                counts.append(len(poly))
        co.point.setValues(0, len(pts), pts)
        co.point.setNum(len(pts))
        ls.numVertices.setValues(0, len(counts), counts)
        ls.numVertices.setNum(len(counts))

    # --- what is drawn ----------------------------------------------------------------------------
    def _unit_length(self):
        p, px = self.pointer()
        if not px:
            w, h = self.view.getSize()
            px = self.pixel_size(w / 2, h / 2)
        return HANDLE_PIXELS * (px or 0.0)

    def ends(self):
        """[(index, point, tail, tip)] of the handles as they stand."""
        out = []
        if self.data is None:
            return out
        unit = self._unit_length()
        sides = self.data.get("sides") or [(a, w, w) for a, w in self.data["tangents"]]
        for i, (p, (a, w1, w2)) in enumerate(zip(self.data["points"], sides)):
            if self.drag is not None and self.drag[0] == i and self.drag_sides is not None:
                a, w1, w2 = self.drag_sides
            u = (math.cos(math.radians(a)) * unit, math.sin(math.radians(a)) * unit)
            # Tangent Weighting 1 draws behind the point, 2 ahead of it (uneven after a drag without Alt)
            out.append((i, p, (p[0] - u[0] * w1, p[1] - u[1] * w1), (p[0] + u[0] * w2, p[1] + u[1] * w2)))
        return out

    def refresh(self):
        try:
            if not E.is_spline(self.sketch, self.geo):
                self._set_lines(self.lines, [])
                self._set_lines(self.free_lines, [])
                self.tip_co.point.setNum(0)
                self.tip_ms.numPoints = 0
                return
            self.data = E.info(self.sketch, self.geo)
            self.style = E.is_style(self.sketch, self.geo)
        except Exception:
            self.data = None
            return
        if self.style:
            cv = [q for _, q in E.control_vertices(self.sketch, self.geo)]
            if self.drag is not None and self.drag_tangent is not None:
                cv[self.drag[0]] = self.drag_tangent
            self.vertices = cv
            self._set_lines(self.lines, [cv])
            self._set_lines(self.free_lines, [])
            tips = [self._g(q) for q in cv]
            self.tip_co.point.setValues(0, len(tips), tips)
            self.tip_co.point.setNum(len(tips))
            self.tip_ms.numPoints = len(tips)
            return
        ends = self.ends()
        driven = set(self.data.get("driven", ()))
        if self.drag is not None:
            driven.add(self.drag[0])
        self._set_lines(self.lines, [[tail, tip] for i, _, tail, tip in ends if i in driven])
        self._set_lines(self.free_lines, [[tail, tip] for i, _, tail, tip in ends if i not in driven])
        tips = [self._g(q) for _, _, tail, tip in ends for q in (tail, tip)]
        self.tip_co.point.setValues(0, len(tips), tips)
        self.tip_co.point.setNum(len(tips))
        self.tip_ms.numPoints = len(tips)

    def remove(self):
        try:
            from . import appevents
            appevents.stop(self)
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/splinehandles.py:213", _fw_err)
        try:
            self.view.getSceneGraph().removeChild(self.root)
        except Exception as _fw_err:
            _fw_log("fwsketch/splinehandles.py:217", _fw_err)

    # --- dragging a diamond --------------------------------------------------------------------------
    def hit(self, p, px):
        """(index, side) of the diamond under sketch point p, or None."""
        best, out = PICK_PIXELS * px, None
        if self.style:
            for i, q in enumerate(self.vertices):
                dist = length(sub(p, q))
                if dist <= best:
                    best, out = dist, (i, 0)
            return out
        for i, _, tail, tip in self.ends():
            for side, q in ((1, tip), (-1, tail)):
                dist = length(sub(p, q))
                if dist <= best:
                    best, out = dist, (i, side)
        return out

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide on Windows can hand a filter a stale wrapper (a QWidgetItem) instead
        if obj is not self.viewport:
            return False
        try:
            return self._filter(event)
        except Exception:
            import traceback
            App.Console.PrintError("FreeCAD spline handles: %s" % traceback.format_exc())
            return False

    def _filter(self, event):
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            p, px = self.pointer()
            if p is None or self.data is None:
                return False
            h = self.hit(p, px)
            if h is None:
                return False
            self.drag = h
            self.drag_tangent = tuple(self.vertices[h[0]]) if self.style else tuple(self.data["tangents"][h[0]])
            self.drag_sides = None if self.style else tuple(self._sides()[h[0]])
            self.drag_alt = bool(event.modifiers() & QtCore.Qt.AltModifier)
            return True
        if self.drag is None:
            return False
        if t == QtCore.QEvent.MouseMove:
            self._drag_to_pointer()
            return True
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            self._drag_to_pointer()
            index, (a, w) = self.drag[0], self.drag_tangent
            sides = self.drag_sides
            self.drag, self.drag_tangent, self.drag_sides = None, None, None
            self._set_lines(self.preview, [])
            if self.style:
                self.apply_vertex(index, a, w)
            elif sides is not None:
                self.apply_sides(index, *sides)
            else:
                self.apply(index, a, w)
            return True
        if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick):
            return True
        return False

    def _drag_to_pointer(self):
        p, px = self.pointer()
        if p is None:
            return
        i, side = self.drag
        if self.style:
            self.drag_tangent = (p[0], p[1])
            cv = list(self.vertices)
            cv[i] = (p[0], p[1])
            try:
                from .stylespline import reshaped
                self._set_lines(self.preview, [E.sample(reshaped(self.sketch.Geometry[self.geo], cv), 64)])
            except Exception as _fw_err:
                _fw_log("fwsketch/splinehandles.py:297", _fw_err)
            self.refresh()
            return
        q = self.data["points"][i]
        v = ((p[0] - q[0]) * side, (p[1] - q[1]) * side)
        unit = self._unit_length() or 1.0
        w = max(length(v) / unit, 0.05)
        a = math.degrees(math.atan2(v[1], v[0]))
        self.drag_tangent = (a, w)
        sides = [list(x) for x in self._sides()]
        _, w1, w2 = sides[i]
        end = not self.data["closed"] and i in (0, len(sides) - 1)
        if self.drag_alt or end:

            # has one side only, whichever diamond is dragged)
            w1 = w2 = w
        else:

            w1, w2 = (w1, w) if side > 0 else (w, w2)
        self.drag_sides = (a, w1, w2)
        sides[i] = [a, w1, w2]
        t_in = [E._vec(x[0], x[1]) for x in sides]
        t_out = [E._vec(x[0], x[2]) for x in sides]
        try:
            closed = self.data["closed"]
            knots = self.data["all_knots"] if closed else self.data["knots"]
            if E.maintains_continuity(self.sketch, self.geo):
                free = [k for k in range(len(sides)) if k != i and k not in set(self.data.get("driven", ()))]
                for k, t in E.c2_tangents(self.data["points"], knots, t_in, t_out, free, closed).items():
                    t_in[k] = t_out[k] = t
            curve = E.hermite(self.data["points"], knots, t_out, closed, t_in)
            self._set_lines(self.preview, [E.sample(curve, 32 * len(self.data["points"]))])
        except Exception as _fw_err:
            _fw_log("fwsketch/splinehandles.py:330", _fw_err)
        self.refresh()

    def _sides(self):
        return self.data.get("sides") or [(a, w, w) for a, w in self.data["tangents"]]

    def apply(self, index, angle, weight):
        """Write a tangent, both sides the same weight, as one undo step (also for the PropertyManager)."""
        self.apply_sides(index, angle, weight, weight)

    def apply_sides(self, index, angle, weight1, weight2):
        """Write a tangent with Tangent Weighting 1 (behind the point) and 2 (ahead) as one undo step."""
        doc = self.sketch.Document
        doc.openTransaction("Spline handle")
        try:
            E.set_tangent(self.sketch, self.geo, index, angle, weight1=weight1, weight2=weight2)
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        finally:
            try:
                App.closeActiveTransaction(False)
            except Exception as _fw_err:
                _fw_log("fwsketch/splinehandles.py:354", _fw_err)
        doc.recompute()
        self.refresh()


def _apply_vertex(self, index, x, y):
    """Move a style spline's control vertex as one undo step "Move control vertex"."""
    doc = self.sketch.Document
    doc.openTransaction("Move control vertex")
    try:
        E.move_vertex(self.sketch, self.geo, index, x, y)
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    finally:
        try:
            App.closeActiveTransaction(False)
        except Exception as _fw_err:
            _fw_log("fwsketch/splinehandles.py:373", _fw_err)
    doc.recompute()
    self.refresh()


Handles.apply_vertex = _apply_vertex


# --- following the selection ---------------------------------------------------------------------
def _edited():
    gdoc = Gui.ActiveDocument
    vp = gdoc.getInEdit() if gdoc else None
    if getattr(vp, "Object", None) is None or not vp.Object.isDerivedFrom("Sketcher::SketchObject"):
        return None, None
    return gdoc, vp.Object


def picked_spline(sketch):
    """The spline whose curve or spline point is picked, else None."""
    try:
        sel = Gui.Selection.getSelectionEx(sketch.Document.Name)
    except Exception:
        return None
    for s in sel:
        if s.Object is not sketch and getattr(s.Object, "Name", None) != sketch.Name:
            continue
        for name in s.SubElementNames:
            geo = None
            if name.startswith("Edge"):
                geo = int(name[4:]) - 1
            elif name.startswith("Vertex"):
                try:
                    geo = sketch.getGeoVertexIndex(int(name[6:]) - 1)[0]
                except Exception:
                    geo = None
            if geo is not None and geo >= 0:
                spline = E.spline_of(sketch, geo)
                if spline is not None:
                    return spline
    return None


def tick():
    gdoc, sketch = _edited()
    if sketch is None:
        hide()
        return
    cur = _current
    if cur is not None and cur.drag is not None:
        return
    geo = picked_spline(sketch)
    if geo is None:
        from . import toolbase
        tool = toolbase.active()
        last = getattr(tool, "last_spline", None)
        if tool is not None and tool.title() in ("Spline", "Style Spline") and not tool.points and last is not None:
            geo = last
    if geo is None:
        hide()
        return
    show(gdoc, sketch, geo)


def start():
    """Show the handles of the picked spline from now on (idempotent)."""
    global _watcher
    if _watcher is not None:
        return _watcher
    _watcher = QtCore.QTimer()
    _watcher.setInterval(250)

    def safe():
        try:
            tick()
        except Exception as _fw_err:
            _fw_log("fwsketch/splinehandles.py:448", _fw_err)
    _watcher.timeout.connect(safe)
    _watcher.start()
    return _watcher
