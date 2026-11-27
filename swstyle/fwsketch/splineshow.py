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
from PySide import QtCore

from . import splineedit as E

PROPERTY = "FreeWorksSplineShow"
COMB, INFLECTION, MINRADIUS = "comb", "inflection", "minradius"
KINDS = (COMB, INFLECTION, MINRADIUS)
COMB_COLOR = (0.75, 0.25, 0.85)
MARK_COLOR = (0.95, 0.45, 0.1)
SAMPLES = 60          # comb teeth per spline
SCAN = 400            # samples for inflections and the minimum radius

_overlay = None


# --- the maths ----------------------------------------------------------------------------------
def _bend(curve, u):
    p, d1, d2 = curve.getD2(u)
    return d1.x * d2.y - d1.y * d2.x, d1.Length, p, d1


def curvature(curve, u):
    """Signed curvature at u (positive = bending left)."""
    cross, speed, _, _ = _bend(curve, u)
    return cross / speed ** 3 if speed > 1e-12 else 0.0


def _params(curve, count):
    a, b = curve.FirstParameter, curve.LastParameter
    return [a + (b - a) * k / float(count) for k in range(count + 1)]


def comb(curve, samples=SAMPLES, scale=None, factor=1.0):
    """[(base, tip)] of the comb's teeth and the scale used."""
    us = _params(curve, samples)
    rows = []
    for u in us:
        cross, speed, p, d1 = _bend(curve, u)
        if speed < 1e-12:
            continue
        k = cross / speed ** 3
        n = (-d1.y / speed, d1.x / speed)
        rows.append(((p.x, p.y), n, k))
    if scale is None:
        biggest = max((abs(k) for _, _, k in rows), default=0.0)
        box = curve.toShape().BoundBox
        size = max(box.DiagonalLength, 1e-6)
        scale = factor * 0.2 * size / biggest if biggest > 1e-12 else 0.0     # combs-1127: factor = Curvature Scale page's Scale

    teeth = [(p, (p[0] - n[0] * k * scale, p[1] - n[1] * k * scale)) for p, n, k in rows]
    return teeth, scale


def inflections(curve):
    us = _params(curve, SCAN)
    out, last = [], None
    for i, u in enumerate(us):
        k = curvature(curve, u)
        s = 0 if abs(k) < 1e-9 else (1 if k > 0 else -1)
        if s == 0:
            continue
        if last is not None and s != last[1]:
            lo, hi = us[last[0]], u
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                if (curvature(curve, mid) > 0) == (last[1] > 0):
                    lo = mid
                else:
                    hi = mid
            p = curve.value(0.5 * (lo + hi))
            out.append((p.x, p.y))
        last = (i, s)
    return out


def minimum_radius(curve):
    """((x, y), radius) where the spline bends tightest, or None when it is straight."""
    us = _params(curve, SCAN)
    ks = [abs(curvature(curve, u)) for u in us]
    i = max(range(len(us)), key=lambda j: ks[j])
    if ks[i] < 1e-9:
        return None
    lo, hi = us[max(0, i - 1)], us[min(len(us) - 1, i + 1)]
    g = (5 ** 0.5 - 1) / 2
    for _ in range(60):
        a, b = hi - g * (hi - lo), lo + g * (hi - lo)
        if abs(curvature(curve, a)) > abs(curvature(curve, b)):
            hi = b
        else:
            lo = a
    u = 0.5 * (lo + hi)
    if abs(curvature(curve, u)) < ks[i]:
        u = us[i]
    p = curve.value(u)
    return (p.x, p.y), 1.0 / abs(curvature(curve, u))


# --- what is switched on ------------------------------------------------------------------------
def _keys(sketch, geo):
    """(key written, keys read) for spline geo. The saved geometry id: it stays while the spline is
    dragged or reshaped and after save and reopen (a Tag is new after reopen, so the displays were
    lost); the Tag still reads rows written before."""
    tag = sketch.Geometry[geo].Tag
    try:
        key = "g%d" % sketch.getGeometryId(geo)
    except Exception:
        return tag, (tag,)
    return key, (key, tag)


def _key(sketch, geo):
    return _keys(sketch, geo)[0]


def _record(sketch):
    try:
        return list(getattr(sketch, PROPERTY))
    except AttributeError:
        return []


def _store(sketch, rows):
    if not hasattr(sketch, PROPERTY):
        if not rows:
            return
        sketch.addProperty("App::PropertyStringList", PROPERTY, "FreeCAD", "Spline displays FreeCAD shows (hidden)")
        try:
            sketch.setEditorMode(PROPERTY, 2)
        except Exception as _fw_err:
            _fw_log("fwsketch/splineshow.py:149", _fw_err)
    if list(getattr(sketch, PROPERTY)) != rows:
        setattr(sketch, PROPERTY, rows)


def shown(sketch, geo):
    """The kinds shown for spline geo."""
    key, read = _keys(sketch, geo)
    for row in _record(sketch):
        k, _, kinds = row.partition(":")
        if k in read:
            return [x for x in kinds.split(",") if x]
    return []


def set_shown(sketch, geo, kind, on):
    key, read = _keys(sketch, geo)
    rows, kinds = [], set()
    for row in _record(sketch):
        k, _, ks = row.partition(":")
        if k in read:
            kinds = {x for x in ks.split(",") if x}
        else:
            rows.append(row)
    (kinds.add if on else kinds.discard)(kind)
    if kinds:
        rows.append("%s:%s" % (key, ",".join(sorted(kinds))))
    _store(sketch, rows)
    refresh()


def splines(sketch):
    return [i for i in range(sketch.GeometryCount) if E.is_spline(sketch, i)]


def drawn_geos(sketch):
    """combs-1127: the splines, and the arcs and circles (their curvature comb only, constant along them)."""
    return [i for i in range(sketch.GeometryCount) if E.is_spline(sketch, i)
            or type(sketch.Geometry[i]).__name__ in ("ArcOfCircle", "Circle")]


def toggle(sketch, kind, geos=None):
    ""

    geos = list(geos) if geos else splines(sketch)
    if not geos:
        return False
    on = not any(kind in shown(sketch, g) for g in geos)
    for g in geos:
        set_shown(sketch, g, kind, on)
    if kind == COMB:
        try:
            from .. import combpm
            combpm.toggled(sketch, geos, on)
        except Exception as _fw_err:
            _fw_log("fwsketch/splineshow.py:comb page", _fw_err)
    return on


# --- drawing -------------------------------------------------------------------------------------
class Overlay(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.root = None
        self.view = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.safe_draw)
        self.timer.start()
        self.drawn = {}      # what was drawn last, for checks: {geo: {"teeth": n, "inflections": [...], "minradius": ...}}

    def _edited(self):
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc else None
        if getattr(vp, "Object", None) is None or not vp.Object.isDerivedFrom("Sketcher::SketchObject"):
            return None, None
        return gdoc, vp.Object

    def _clear(self):
        if self.root is not None and self.view is not None:
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("fwsketch/splineshow.py:220", _fw_err)
        self.root, self.view = None, None

    def safe_draw(self):
        try:
            self.draw()
        except Exception:
            import traceback
            text = traceback.format_exc()
            if text != getattr(self, "_last_error", None):     # once per error, not every 300 ms
                self._last_error = text
                App.Console.PrintWarning("FreeCAD spline displays: %s" % text)

    def draw(self):
        gdoc, sketch = self._edited()
        if sketch is None or not _record(sketch):
            self._clear()
            self.drawn = {}
            return
        from pivy import coin
        view = gdoc.ActiveView
        matrix = gdoc.EditingTransform
        self._clear()

        def g(p):
            v = matrix.multVec(App.Vector(p[0], p[1], 0))
            return (v.x, v.y, v.z)
        root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        root.addChild(pick)
        root.addChild(light)
        drawn = {}
        for geo in drawn_geos(sketch):     # combs-1127: arcs and circles show their comb too
            kinds = shown(sketch, geo)
            if kinds and not E.is_spline(sketch, geo):
                kinds = [k for k in kinds if k == COMB]
            if not kinds:
                continue
            curve = sketch.Geometry[geo]
            row = {}
            if COMB in kinds:
                try:        # combs-1127: the Curvature Scale page's Scale and Density
                    from .. import combpm
                    count, factor = combpm.comb_args(sketch, geo, SAMPLES)
                except Exception:
                    count, factor = SAMPLES, 1.0
                teeth, _ = comb(curve, samples=count, factor=factor)
                lines = [list(t) for t in teeth]
                from . import sysopts
                if sysopts.on(sysopts.COMB_BOUNDING):     # Options > Sketch: the comb's outline
                    lines.append([t[1] for t in teeth])
                row["bounding"] = len(lines) > len(teeth)
                root.addChild(self._lines(coin, g, lines, COMB_COLOR))
                row["teeth"] = len(teeth)
            if INFLECTION in kinds:
                pts = inflections(curve)
                root.addChild(self._marks(coin, g, pts, MARK_COLOR, coin.SoMarkerSet.CROSS_9_9))
                row["inflections"] = pts
            if MINRADIUS in kinds:
                m = minimum_radius(curve)
                if m is not None:
                    root.addChild(self._marks(coin, g, [m[0]], MARK_COLOR, coin.SoMarkerSet.CIRCLE_LINE_9_9))
                    root.addChild(self._text(coin, g, m[0], "R %s" % _fmt(m[1])))
                row["minradius"] = m
            drawn[geo] = row
        view.getSceneGraph().addChild(root)
        self.root, self.view, self.drawn = root, view, drawn

    @staticmethod
    def _lines(coin, g, polylines, rgb):
        sep = coin.SoSeparator()
        c = coin.SoBaseColor()
        c.rgb = rgb
        co = coin.SoCoordinate3()
        pts, counts = [], []
        for poly in polylines:
            if len(poly) >= 2:
                pts.extend(g(p) for p in poly)
                counts.append(len(poly))
        co.point.setValues(0, len(pts), pts)
        ls = coin.SoLineSet()
        ls.numVertices.setValues(0, len(counts), counts)
        for n in (c, co, ls):
            sep.addChild(n)
        return sep

    @staticmethod
    def _marks(coin, g, pts, rgb, marker):
        sep = coin.SoSeparator()
        c = coin.SoBaseColor()
        c.rgb = rgb
        co = coin.SoCoordinate3()
        co.point.setValues(0, len(pts), [g(p) for p in pts])
        ms = coin.SoMarkerSet()
        ms.markerIndex = marker
        for n in (c, co, ms):
            sep.addChild(n)
        return sep

    @staticmethod
    def _text(coin, g, p, text):
        sep = coin.SoSeparator()
        c = coin.SoBaseColor()
        c.rgb = MARK_COLOR
        tr = coin.SoTranslation()
        tr.translation.setValue(*g(p))
        t = coin.SoText2()
        t.string = "  " + text
        for n in (c, tr, t):
            sep.addChild(n)
        return sep


def _fmt(value):
    try:
        return App.Units.Quantity(value, App.Units.Length).UserString
    except Exception:
        return "%.2f mm" % value


def start():
    global _overlay
    if _overlay is None:
        _overlay = Overlay()
    return _overlay


def refresh():
    if _overlay is not None:
        _overlay.safe_draw()


def overlay():
    return _overlay
