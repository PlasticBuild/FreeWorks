# SPDX-License-Identifier: LGPL-2.1-or-later
""











_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


import math

import FreeCAD as App

PROPERTY = "FreeWorksCombScale"
STEPS = 100                     # slider positions; the middle (50) is the comb's own size and density
SCALE_RANGE = 10.0              # Scale: a tenth to ten times the automatic tooth length
DENSITY_RANGE = 4.0             # Density: a quarter to four times the teeth (60 at the middle)
CURVES = ("ArcOfCircle", "Circle")


def combable(sketch, geo):
    """A spline, an arc or a circle (what Show Curvature works on)."""
    try:
        g = sketch.Geometry[geo]
    except Exception:
        return False
    name = type(g).__name__
    return name in CURVES or "BSpline" in name


def _show():
    from .fwsketch import splineshow
    return splineshow


# --- the values kept with the sketch ------------------------------------------------------------
def _rows(sketch):
    try:
        return list(getattr(sketch, PROPERTY))
    except AttributeError:
        return []


def settings(sketch, geo):
    """(scale, density) factors of geo's comb; (1, 1) when never set."""
    try:
        _key, read = _show()._keys(sketch, geo)
    except Exception:
        return 1.0, 1.0
    read = [str(k) for k in read]
    for row in _rows(sketch):
        k, _, v = row.partition(":")
        if k in read:
            try:
                s, d = (float(x) for x in v.split(","))
                return s, d
            except Exception:
                break
    return 1.0, 1.0


def set_settings(sketch, geo, scale, density):
    key, read = _show()._keys(sketch, geo)
    read = [str(k) for k in read]
    rows = [r for r in _rows(sketch) if r.partition(":")[0] not in read]
    if abs(scale - 1.0) > 1e-9 or abs(density - 1.0) > 1e-9:
        rows.append("%s:%.6g,%.6g" % (key, scale, density))
    if not hasattr(sketch, PROPERTY):
        if not rows:
            return
        sketch.addProperty("App::PropertyStringList", PROPERTY, "FreeCAD", "Curvature comb scale and density (hidden)")
        try:
            sketch.setEditorMode(PROPERTY, 2)
        except Exception as _fw_err:
            _fw_log("combpm.py:editor mode", _fw_err)
    if list(getattr(sketch, PROPERTY)) != rows:
        setattr(sketch, PROPERTY, rows)


def comb_args(sketch, geo, samples):
    """splineshow's comb() arguments for geo: (teeth count, factor on the automatic tooth length)."""
    s, d = settings(sketch, geo)
    return max(4, int(round(samples * d))), s


def to_slider(factor, span):
    return int(round(STEPS / 2.0 * (1.0 + math.log(max(factor, 1e-6)) / math.log(span))))


def from_slider(value, span):
    return span ** ((value - STEPS / 2.0) / (STEPS / 2.0))


# --- the page ---------------------------------------------------------------------------------------
_page_class = None
_opening = ()


def _make_class():
    from PySide import QtCore, QtWidgets
    from . import sketchtoolpm

    class CurvatureScalePage(sketchtoolpm.ToolPage):
        TITLE = "Curvature Scale"
        PIXMAP = "Sketcher_BSplineComb"

        def build(self):
            # the entities come in through _opening (a PySide widget takes no attributes before its __init__)
            self.geos = list(_opening)
            self.before = {g: settings(self.sketch, g) for g in self.geos}
            first = self.before[self.geos[0]] if self.geos else (1.0, 1.0)
            self.scale = self._slider("Scale", "SWCombScale", to_slider(first[0], SCALE_RANGE))
            self.density = self._slider("Density", "SWCombDensity", to_slider(first[1], DENSITY_RANGE))

        def _slider(self, title, name, value):
            group = self.group(title)
            s = QtWidgets.QSlider(QtCore.Qt.Horizontal, group.body)
            s.setObjectName(name)
            s.setRange(0, STEPS)
            s.setPageStep(10)
            s.setValue(max(0, min(STEPS, value)))
            s.valueChanged.connect(self.changed)
            group.content.addWidget(s)
            return s

        def values(self):
            return (from_slider(self.scale.value(), SCALE_RANGE), from_slider(self.density.value(), DENSITY_RANGE))

        def changed(self, *_):
            s, d = self.values()
            for g in self.geos:
                set_settings(self.sketch, g, s, d)
            _show().refresh()

        def reject(self):
            for g, (s, d) in self.before.items():
                try:
                    set_settings(self.sketch, g, s, d)
                except Exception as _fw_err:
                    _fw_log("combpm.py:cancel", _fw_err)
            _show().refresh()
            sketchtoolpm.close(self)

    return CurvatureScalePage


def open_for(sketch, geos):
    """Opens the Curvature Scale page for those entities (their comb was just switched on).
    Returns the page, or None when it could not open."""
    global _page_class, _opening
    geos = [g for g in (geos or ()) if combable(sketch, g)]
    if not geos:
        return None
    try:
        if _page_class is None:
            _page_class = _make_class()
        from . import sketchtoolpm
        _opening = geos
        try:
            page = _page_class(sketch)
        finally:
            _opening = ()
        return page if sketchtoolpm.open_page(page) else None
    except Exception as _fw_err:
        _fw_log("combpm.py:open", _fw_err)
        return None


def toggled(sketch, geos, on):
    """The comb of geos was switched on (the page opens) or off (an open page for them closes).
    splineshow.toggle calls this too, so the spline commands open the page as the shortcut menu does."""
    page = current()
    if on:
        if page is None or set(page.geos) != set(geos):
            open_for(sketch, geos)
    elif page is not None and set(page.geos) & set(geos):
        page.accept()


def current():
    try:
        from . import sketchtoolpm
        host = sketchtoolpm._host
        page = getattr(host, "page", None) if host is not None else None
        return page if _page_class is not None and isinstance(page, _page_class) else None
    except Exception:
        return None


def toggle(sketch, geos):
    """Show Curvature on these entities: on for all when none shows it, else off for all. With the comb
    on, the Curvature Scale page opens. Returns the new state."""
    show = _show()
    geos = [g for g in geos if combable(sketch, g)]
    if not geos:
        return False
    on = not any(show.COMB in show.shown(sketch, g) for g in geos)
    for g in geos:
        show.set_shown(sketch, g, show.COMB, on)
    toggled(sketch, geos, on)
    return on


def shown(sketch, geo):
    try:
        show = _show()
        return show.COMB in show.shown(sketch, geo)
    except Exception:
        return False
