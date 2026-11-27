
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

from . import drawings as D
from . import drawviews as DV
from . import drawannot as DA

V = App.Vector
CURRENT = None
SOLID, CENTER = 1, 4         # TechDraw line styles


def _entities(view):
    if "SWSketchEntities" not in view.PropertiesList:
        view.addProperty("App::PropertyStringList", "SWSketchEntities", "FreeCAD",
                         "drawing sketch entities: kind|tags|points")
    return list(view.SWSketchEntities)


def _record(view, kind, tags, pts):
    ents = _entities(view)
    ents.append("%s|%s|%s" % (kind, ",".join(t for t in tags if t),
                             ";".join("%.6g,%.6g" % (p[0], p[1]) for p in pts)))
    view.SWSketchEntities = ents
    show_points(view)           # extapps84


def _drawing_option(text, default):
    """extapps84: Tools > Options > System Options > Drawings: that row's kept value."""
    try:
        from . import optionspages
        return optionspages.stored("Drawings", text, default)
    except Exception:
        return default


def _sketch_points(view, centres, ends):
    """The points System Options > Drawings shows on a view's drawing sketch (view geometry, each once)."""
    out = []
    for kind, _tags, P in entities(view):
        pts = []
        if kind in ("Circle", "Arc") and P and centres:
            pts.append(P[0])
        if ends:
            if kind == "Arc" and len(P) >= 3:
                r = math.hypot(P[1][0] - P[0][0], P[1][1] - P[0][1])
                a1 = math.atan2(P[2][1] - P[0][1], P[2][0] - P[0][0])
                pts += [P[1], (P[0][0] + r * math.cos(a1), P[0][1] + r * math.sin(a1))]
            elif kind in ("Line", "Centerline", "Rectangle", "CenterRectangle", "Polygon", "Spline"):
                pts += P
        for p in pts:
            if not any(abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6 for q in out):
                out.append(p)
    return out


def show_points(view):
    ""

    try:
        old = list(getattr(view, "SWSketchPoints", []) or [])
        for tag in old:
            try:
                view.removeCosmeticVertex(tag)
            except Exception as _fw_err:
                _fw_log("drawsketch.py:points-off", _fw_err)
        pts = _sketch_points(view, bool(_drawing_option("Display sketch arc centerpoints", False)),
                             bool(_drawing_option("Display sketch entity points", False)))
        if not old and not pts:
            return []
        tags = [view.makeCosmeticVertex(V(p[0], p[1], 0)) for p in pts]
        if "SWSketchPoints" not in view.PropertiesList:
            view.addProperty("App::PropertyStringList", "SWSketchPoints", "FreeCAD", "drawing sketch points shown")
        view.SWSketchPoints = tags
        view.requestPaint()
        return tags
    except Exception as _fw_err:
        _fw_log("drawsketch.py:points", _fw_err)
        return []


def refresh_points(doc=None):
    """Every drawing sketch's points again (after the Options box is saved)."""
    for d in ([doc] if doc is not None else list(App.listDocuments().values())):
        for v in d.Objects:
            if v.isDerivedFrom("TechDraw::DrawViewPart") and (getattr(v, "SWSketchEntities", None)
                                                               or getattr(v, "SWSketchPoints", None)):
                show_points(v)


def entities(view):
    """[(kind, tags, points in view geometry)] of a view's drawing sketch."""
    out = []
    for s in list(getattr(view, "SWSketchEntities", []) or []):
        kind, tags, pts = (s.split("|") + ["", ""])[:3]
        P = [tuple(float(c) for c in q.split(",")) for q in pts.split(";") if q]
        out.append((kind, [t for t in tags.split(",") if t], P))
    return out


def line(view, a, b, style=SOLID):
    """A cosmetic line of view between geometry points a, b."""
    tag = view.makeCosmeticLine(V(a[0], a[1], 0), V(b[0], b[1], 0))
    return DA._styled(view, tag, style) if style != SOLID else tag


def _sheet_graphic(page, kind, pts_sheet, body_of):
    cx = sum(p[0] for p in pts_sheet) / len(pts_sheet)
    cy = sum(p[1] for p in pts_sheet) / len(pts_sheet)
    rel = [(p[0] - cx, -(p[1] - cy)) for p in pts_sheet]
    reach = max(math.hypot(*q) for q in rel) + 2
    n = 1 + len([o for o in page.Document.Objects if getattr(o, "SWAnnotation", "") == "SheetSketch"])
    s = DA.svg_symbol(page, "SheetSketch", body_of(rel), reach, (cx, cy), "Sketch %s%d" % (kind, n), "SheetSketch")
    s.addProperty("App::PropertyString", "SWSketchKind", "FreeCAD", "drawing sketch entity")
    s.SWSketchKind = kind
    return s


def _svg_poly(rel, closed=False, dash=False):
    return ('<poly%s points="%s" fill="none" stroke="#000" stroke-width="0.35"%s/>'
            % ("gon" if closed else "line", " ".join("%g,%g" % q for q in rel),
               ' stroke-dasharray="8 1.5 1.5 1.5"' if dash else ""))


def spline_points(pts, n=12):
    ""
    if len(pts) < 3:
        return list(pts)
    P = [pts[0]] + list(pts) + [pts[-1]]
    out = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for j in range(n):
            t = j / float(n)
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 +
                                    (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in (0, 1)))
    out.append(pts[-1])
    return out


class _SketchPanel(D._Panel):
    """Clicks on the sheet make the entity; inside a view it belongs to that view."""
    TITLE = "Line"
    PIXMAP = "Sketcher_CreateLine"
    POINTS = 2              # clicks per entity (0: until OK)
    HINT = "Click the start, then the end."

    def build(self):
        self.say(self.HINT)
        self.pts = []
        self.view = None
        self.count = 0
        self.last_snap = None
        global CURRENT
        CURRENT = self             # Quick Snaps is live while a sketch tool is open

    def sheet_click(self, p):
        try:                       # Quick Snaps: the click goes to the snapped point
            from . import drawsketchedit as SE
            p, self.last_snap = SE.snap(self.page, p, self.pts[-1] if self.pts else None)
        except Exception as e:
            App.Console.PrintWarning("FreeCAD: Quick Snaps: %s\n" % e)
        if not self.pts:
            self.view = DV.focus_view(self.page, p, margin=0.0)
        self.pts.append(p)
        if self.POINTS and len(self.pts) >= self.POINTS:
            self.make(self.pts)
            self.after()
        return True

    def after(self):
        self.pts = [self.pts[-1]] if self.CHAIN else []
        if not self.CHAIN:
            self.view = None
        self.count += 1
        self.doc.recompute()
        self.say(self.HINT + " OK when done.")

    CHAIN = False

    def finish(self):
        if not self.POINTS and len(self.pts) >= 2:
            self.make(self.pts)
            self.doc.recompute()

    def geo(self, pts):
        return [DV.to_geometry(self.view, q) for q in pts]

    def make(self, pts):
        raise NotImplementedError


class LinePanel(_SketchPanel):
    TITLE = "Line"
    PIXMAP = "Sketcher_CreateLine"
    CHAIN = True
    STYLE = SOLID
    KIND = "Line"
    HINT = "Click the start, then each next point (lines chain)."

    def make(self, pts):
        a, b = pts[-2], pts[-1]
        if self.view is not None:
            g = self.geo([a, b])
            tag = line(self.view, g[0], g[1], self.STYLE)
            _record(self.view, self.KIND, [tag], g)
        else:
            _sheet_graphic(self.page, self.KIND, [a, b], lambda rel: _svg_poly(rel, dash=self.STYLE == CENTER))
        self.made.append(None)


class CenterlinePanel(LinePanel):
    TITLE = "Centerline"
    PIXMAP = "Sketcher_CreateLine"
    STYLE = CENTER
    KIND = "Centerline"


class RectanglePanel(_SketchPanel):
    TITLE = "Rectangle"
    PIXMAP = "Sketcher_CreateRectangle"
    HINT = "Click one corner, then the opposite corner."

    def make(self, pts):
        a, b = pts
        corners = [a, (b[0], a[1]), b, (a[0], b[1])]
        if self.view is not None:
            g = self.geo(corners)
            tags = [line(self.view, g[i], g[(i + 1) % 4]) for i in range(4)]
            _record(self.view, "Rectangle", tags, g)
        else:
            _sheet_graphic(self.page, "Rectangle", corners, lambda rel: _svg_poly(rel, closed=True))


class CirclePanel(_SketchPanel):
    TITLE = "Circle"
    PIXMAP = "Sketcher_CreateCircle"
    HINT = "Click the center, then a point on the circle."

    def make(self, pts):
        c, e = pts
        r = math.hypot(e[0] - c[0], e[1] - c[1])
        if r < 1e-6:
            return
        if self.view is not None:
            g = self.geo([c, e])
            rg = math.hypot(g[1][0] - g[0][0], g[1][1] - g[0][1])
            tag = self.view.makeCosmeticCircle(V(g[0][0], g[0][1], 0), rg)
            _record(self.view, "Circle", [tag], g)
        else:
            _sheet_graphic(self.page, "Circle", [c], lambda rel: '<circle cx="0" cy="0" r="%g" fill="none" '
                           'stroke="#000" stroke-width="0.35"/>' % r)


class ArcPanel(_SketchPanel):
    TITLE = "Arc"
    PIXMAP = "Sketcher_CreateArc"
    POINTS = 3
    HINT = "Click the center, the start, then the end (counterclockwise)."

    def make(self, pts):
        c, s, e = pts
        r = math.hypot(s[0] - c[0], s[1] - c[1])
        a0 = math.degrees(math.atan2(s[1] - c[1], s[0] - c[0]))
        a1 = math.degrees(math.atan2(e[1] - c[1], e[0] - c[0]))
        if self.view is not None:
            g = self.geo([c, s, e])
            rg = math.hypot(g[1][0] - g[0][0], g[1][1] - g[0][1])
            tag = self.view.makeCosmeticCircleArc(V(g[0][0], g[0][1], 0), rg, a0, a1)
            _record(self.view, "Arc", [tag], g)
        else:
            sx, sy = s[0] - c[0], -(s[1] - c[1])
            ex = r * math.cos(math.radians(a1))
            ey = -r * math.sin(math.radians(a1))
            large = 1 if (a1 - a0) % 360 > 180 else 0
            _sheet_graphic(self.page, "Arc", [c], lambda rel: '<path d="M%g %g A%g %g 0 %d 0 %g %g" fill="none" '
                           'stroke="#000" stroke-width="0.35"/>' % (rel[0][0] + sx, rel[0][1] + sy, r, r, large,
                                                                     rel[0][0] + ex, rel[0][1] + ey))


class PointPanel(_SketchPanel):
    TITLE = "Point"
    PIXMAP = "Sketcher_CreatePoint"
    POINTS = 1
    HINT = "Click to place a point."

    def make(self, pts):
        p = pts[0]
        if self.view is not None:
            g = self.geo([p])
            tag = self.view.makeCosmeticVertex(V(g[0][0], g[0][1], 0))
            _record(self.view, "Point", [tag], g)
        else:
            _sheet_graphic(self.page, "Point", [p], lambda rel: '<circle cx="0" cy="0" r="0.5" fill="#000"/>')


class SplinePanel(_SketchPanel):
    TITLE = "Spline"
    PIXMAP = "Sketcher_CreateBSpline"
    POINTS = 0
    HINT = "Click the spline's points; OK ends it."

    def make(self, pts):
        if self.view is not None:
            g = self.geo(pts)
            curve = spline_points(g)
            tags = [line(self.view, curve[i], curve[i + 1]) for i in range(len(curve) - 1)]
            _record(self.view, "Spline", tags, g)
        else:
            _sheet_graphic(self.page, "Spline", pts, lambda rel: _svg_poly(spline_points(rel)))
        self.pts = []



def circle_through(a, b, c):
    """(centre, radius) of the circle through three points, else None (in a line)."""
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def arc_points(c, r, a0, a1, n=24):
    """Points from angle a0 counterclockwise to a1 (degrees)."""
    sweep = (a1 - a0) % 360.0 or 360.0
    return [(c[0] + r * math.cos(math.radians(a0 + sweep * i / n)), c[1] + r * math.sin(math.radians(a0 + sweep * i / n)))
            for i in range(n + 1)]


def three_point_arc(s, e, m, n=24):
    """The arc from s to e through m: (centre, r, a0, a1) counterclockwise, else None."""
    hit = circle_through(s, e, m)
    if hit is None:
        return None
    c, r = hit
    ang = lambda q: math.degrees(math.atan2(q[1] - c[1], q[0] - c[0])) % 360.0
    a0, a1, am = ang(s), ang(e), ang(m)
    if (am - a0) % 360.0 > (a1 - a0) % 360.0:      # m is not on the way from s to e counterclockwise
        a0, a1 = a1, a0
    return c, r, a0, a1


def polygon_points(c, v, sides=6):
    r = math.hypot(v[0] - c[0], v[1] - c[1])
    a = math.atan2(v[1] - c[1], v[0] - c[0])
    return [(c[0] + r * math.cos(a + 2 * math.pi * i / sides), c[1] + r * math.sin(a + 2 * math.pi * i / sides))
            for i in range(sides)]


def slot_points(a, b, w, n=12):
    """A straight slot from centre a to centre b, its half width the distance of w from the line ab."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return None
    r = abs((w[0] - a[0]) * dy - (w[1] - a[1]) * dx) / L
    if r < 1e-9:
        return None
    ang = math.degrees(math.atan2(dy, dx))
    return arc_points(b, r, ang - 90, ang + 90, n) + arc_points(a, r, ang + 90, ang + 270, n)


def ellipse_points(c, major, minor, n=64):
    ax, ay = major[0] - c[0], major[1] - c[1]
    A = math.hypot(ax, ay)
    if A < 1e-9:
        return None
    ux, uy = ax / A, ay / A
    B = abs((minor[0] - c[0]) * -uy + (minor[1] - c[1]) * ux)
    if B < 1e-9:
        return None
    return [(c[0] + A * math.cos(t) * ux - B * math.sin(t) * uy, c[1] + A * math.cos(t) * uy + B * math.sin(t) * ux)
            for t in (2 * math.pi * i / n for i in range(n))]


CLOSED_POLY = ("CenterRectangle", "Polygon", "Slot", "Ellipse", "Ring")   # Ring: any closed outline (drawsketchmore)


class _PolyPanel(_SketchPanel):
    """An entity made of straight segments through points (closed: back to the first)."""
    CLOSED = True
    KIND = "Polygon"

    def points(self, pts):
        raise NotImplementedError

    def make(self, pts):
        poly = self.points(pts)
        if not poly:
            return
        if self.view is not None:
            g = self.geo(poly)
            ring = g + [g[0]] if self.CLOSED else g
            tags = [line(self.view, ring[i], ring[i + 1]) for i in range(len(ring) - 1)]
            _record(self.view, self.KIND, tags, g)
        else:
            _sheet_graphic(self.page, self.KIND, poly, lambda rel: _svg_poly(rel, closed=self.CLOSED))


class CenterRectanglePanel(_PolyPanel):
    TITLE = "Center Rectangle"
    PIXMAP = "Sketcher_CreateRectangle_Center"
    KIND = "CenterRectangle"
    HINT = "Click the center, then a corner."

    def points(self, pts):
        c, b = pts
        dx, dy = b[0] - c[0], b[1] - c[1]
        return [(c[0] - dx, c[1] - dy), (c[0] + dx, c[1] - dy), (c[0] + dx, c[1] + dy), (c[0] - dx, c[1] + dy)]


class PolygonPanel(_PolyPanel):
    TITLE = "Polygon"
    PIXMAP = "Sketcher_CreateHexagon"
    KIND = "Polygon"
    HINT = "Click the center, then a vertex (6 sides)."
    SIDES = 6

    def build(self):
        super().build()
        box, lay = D._group("Parameters", self.form)
        self.sides = QtWidgets.QSpinBox(box)
        self.sides.setObjectName("SWSketchPolygonSides")
        self.sides.setRange(3, 40)
        self.sides.setValue(self.SIDES)
        self.sides.setToolTip("Number of sides")
        lay.addWidget(self.sides)

    def points(self, pts):
        return polygon_points(pts[0], pts[1], self.sides.value())


class SlotPanel(_PolyPanel):
    TITLE = "Straight Slot"
    PIXMAP = "Sketcher_CreateSlot"
    KIND = "Slot"
    POINTS = 3
    HINT = "Click the start, the end, then the slot's width."

    def points(self, pts):
        return slot_points(*pts)


class EllipsePanel(_PolyPanel):
    TITLE = "Ellipse"
    PIXMAP = "Sketcher_CreateEllipseByCenter"
    KIND = "Ellipse"
    POINTS = 3
    HINT = "Click the center, the end of the major axis, then a point for the minor axis."

    def points(self, pts):
        return ellipse_points(*pts)


class PerimeterCirclePanel(_SketchPanel):
    TITLE = "Perimeter Circle"
    PIXMAP = "Sketcher_Create3PointCircle"
    POINTS = 3
    HINT = "Click three points on the circle."

    def make(self, pts):
        hit = circle_through(*pts)
        if hit is None:
            return
        c, r = hit
        e = (c[0] + r, c[1])
        CirclePanel.make(self, [c, e])


class ThreePointArcPanel(_SketchPanel):
    TITLE = "3 Point Arc"
    PIXMAP = "Sketcher_Create3PointArc"
    POINTS = 3
    HINT = "Click the start, the end, then a point on the arc."

    def make(self, pts):
        hit = three_point_arc(*pts)
        if hit is None:
            return
        c, r, a0, a1 = hit
        s = (c[0] + r * math.cos(math.radians(a0)), c[1] + r * math.sin(math.radians(a0)))
        e = (c[0] + r * math.cos(math.radians(a1)), c[1] + r * math.sin(math.radians(a1)))
        ArcPanel.make(self, [c, s, e])


# --------------------------------------------------------------------------- closed profiles (Crop, Broken-out)
def profile_points(kind, pts, n=64):
    """A closed entity as a polygon in view geometry, else None."""
    if kind == "Rectangle" and len(pts) == 4:
        return list(pts)
    if kind in CLOSED_POLY and len(pts) >= 3:
        return list(pts)
    if kind == "Circle" and len(pts) == 2:
        (cx, cy), (ex, ey) = pts
        r = math.hypot(ex - cx, ey - cy)
        return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    if kind == "Spline" and len(pts) >= 3 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1.0:
        return spline_points(pts)[:-1]
    return None


def closed_profile(view):
    """(index, polygon in view geometry) of the view's last closed sketch entity, else None."""
    ents = entities(view)
    for i in range(len(ents) - 1, -1, -1):
        poly = profile_points(ents[i][0], ents[i][2])
        if poly:
            return i, poly
    return None


def picked_closed_profile():
    """(view, index, polygon) of a closed sketch entity in the picked view (or the only view with one)."""
    v, _ = D.picked_view_and_edge()
    page = D.active_page()
    views = [v] if v is not None else [w for w in (D.views_of(page) if page else []) if closed_profile(w)]
    for view in views[:1] if v is not None else views[:1]:
        hit = closed_profile(view)
        if hit:
            return view, hit[0], hit[1]
    return None


def consume(view, index):
    ""
    ents = list(view.SWSketchEntities)
    if not 0 <= index < len(ents):
        return
    kind, tags, _ = (ents[index].split("|") + ["", ""])[:3]
    for tag in [t for t in tags.split(",") if t]:
        try:
            view.removeCosmeticEdge(tag)
        except Exception:
            try:
                view.removeCosmeticVertex(tag)
            except Exception as _fw_err:
                _fw_log("drawsketch.py:498", _fw_err)
    del ents[index]
    view.SWSketchEntities = ents
    show_points(view)           # extapps84


# --------------------------------------------------------------------------- Make Section Line
def picked_sketch_line():
    """(view, sheet points a, b) of the drawing sketch line picked last in the picked view, else None."""
    v, edge = D.picked_view_and_edge()
    views = [v] if v is not None else []
    if not views:
        page = D.active_page()
        views = [w for w in (D.views_of(page) if page else []) if getattr(w, "SWSketchEntities", None)]
    for view in views:
        lines = [e for e in entities(view) if e[0] in ("Line", "Centerline") and len(e[2]) == 2]
        if lines:
            g = lines[-1][2]
            x0, y0 = D.view_position(view)
            k = DV.view_scale(view)
            return view, [(x0 + q[0] * k, y0 + q[1] * k) for q in g]
    return None


class MakeSectionLinePanel(DV.SectionViewPanel):
    """Section View from a sketched line: the cutting line is the line; click to place the view."""

    def __init__(self, page, view, pts):
        self._pre = (view, pts)
        super().__init__(page)

    def build(self):
        super().build()
        view, pts = self._pre
        self.base = view
        self.line = (tuple(pts[0]), tuple(pts[1]))
        for b in self.kind.buttons():
            if b.text() == "Auxiliary":
                b.setChecked(True)
        self.say("Click to place the section view.")


COMMANDS = {
    "FreeWorks_DrawSketchLine": ("Line", "Sketcher_CreateLine", "Sketches lines on the drawing."),
    "FreeWorks_DrawSketchCenterline": ("Centerline", "Sketcher_CreateLine", "Sketches centerlines on the drawing."),
    "FreeWorks_DrawSketchRectangle": ("Corner Rectangle", "Sketcher_CreateRectangle", "Sketches a rectangle."),
    "FreeWorks_DrawSketchCircle": ("Circle", "Sketcher_CreateCircle", "Sketches a circle."),
    "FreeWorks_DrawSketchArc": ("Centerpoint Arc", "Sketcher_CreateArc", "Sketches an arc."),
    "FreeWorks_DrawSketchPoint": ("Point", "Sketcher_CreatePoint", "Sketches a point."),
    "FreeWorks_DrawSketchSpline": ("Spline", "Sketcher_CreateBSpline", "Sketches a spline through points."),
    "FreeWorks_DrawSketchCenterRectangle": ("Center Rectangle", "Sketcher_CreateRectangle_Center",
                                            "Sketches a rectangle from its center."),
    "FreeWorks_DrawSketchSlot": ("Straight Slot", "Sketcher_CreateSlot", "Sketches a straight slot."),
    "FreeWorks_DrawSketchPerimeterCircle": ("Perimeter Circle", "Sketcher_Create3PointCircle",
                                            "Sketches a circle through three points."),
    "FreeWorks_DrawSketchThreePointArc": ("3 Point Arc", "Sketcher_Create3PointArc", "Sketches an arc through three points."),
    "FreeWorks_DrawSketchPolygon": ("Polygon", "Sketcher_CreateHexagon", "Sketches a regular polygon."),
    "FreeWorks_DrawSketchEllipse": ("Ellipse", "Sketcher_CreateEllipseByCenter", "Sketches an ellipse."),
    "FreeWorks_DrawSketchText": ("Text", "TechDraw_Annotation", "Adds text on the drawing (a note)."),
    "FreeWorks_DrawMakeSectionLine": ("Make Section Line", "TechDraw_SectionView",
                                      "Makes a section view from a line sketched in a view."),
}
PANELS = {"FreeWorks_DrawSketchLine": LinePanel, "FreeWorks_DrawSketchCenterline": CenterlinePanel,
          "FreeWorks_DrawSketchRectangle": RectanglePanel, "FreeWorks_DrawSketchCircle": CirclePanel,
          "FreeWorks_DrawSketchArc": ArcPanel, "FreeWorks_DrawSketchPoint": PointPanel,
          "FreeWorks_DrawSketchSpline": SplinePanel, "FreeWorks_DrawSketchCenterRectangle": CenterRectanglePanel,
          "FreeWorks_DrawSketchSlot": SlotPanel, "FreeWorks_DrawSketchPerimeterCircle": PerimeterCirclePanel,
          "FreeWorks_DrawSketchThreePointArc": ThreePointArcPanel, "FreeWorks_DrawSketchPolygon": PolygonPanel,
          "FreeWorks_DrawSketchEllipse": EllipsePanel}


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}

    def part_twin(self):
        """With a part (not a sheet) in front, the part's own sketch tool of the same name: a menu or button
        that still holds the sheet tool after the window changes keeps working (ChatGPT dsketch216)."""
        try:
            from . import drawselect
            if drawselect.sheet_in_front():
                return None
            for part_cmd, sheet_cmd in drawselect.SKETCH_ON_SHEET.items():
                if sheet_cmd == self.name and part_cmd in Gui.listCommands():
                    return part_cmd
        except Exception as _fw_err:
            _fw_log("drawsketch.py:587", _fw_err)
        return None

    def IsActive(self):
        page = D.active_page()
        if page is None or D.busy() or not D.sheet_shown(page):
            twin = self.part_twin()
            if twin is not None:
                try:
                    return bool(Gui.Command.get(twin).isActive())
                except Exception:
                    return False
            return False
        if self.name == "FreeWorks_DrawMakeSectionLine":
            return picked_sketch_line() is not None
        return True

    def Activated(self):
        page = D.active_page()
        if page is None or not D.sheet_shown(page):
            twin = self.part_twin()
            if twin is not None:
                Gui.runCommand(twin, 0)
            return
        if self.name == "FreeWorks_DrawMakeSectionLine":
            hit = picked_sketch_line()
            if hit is not None:
                D._show(MakeSectionLinePanel(page, hit[0], hit[1]))
            return
        if self.name == "FreeWorks_DrawSketchPoint" and picked_sharp():
            return
        if self.name == "FreeWorks_DrawSketchText":
            Gui.runCommand("FreeWorks_DrawNote", 0)
            return
        D._show(PANELS[self.name](page))


def picked_lines():
    """Two straight model edges picked in one view: (view, (a1, b1), (a2, b2)) in view geometry, else None."""
    sel = Gui.Selection.getSelectionEx()
    if len(sel) != 1:
        return None
    view = sel[0].Object
    names = [n for n in sel[0].SubElementNames if n.startswith("Edge")]
    if len(names) != 2 or len(sel[0].SubElementNames) != 2 or not view.isDerivedFrom("TechDraw::DrawViewPart"):
        return None
    out = []
    for n in names:
        try:
            e = view.getEdgeByIndex(int(n[4:]))
        except Exception as _fw_err:
            _fw_log("drawsketch.py:639", _fw_err)
            return None
        if type(e.Curve).__name__ not in ("Line", "LineSegment") or len(e.Vertexes) < 2:
            return None
        out.append((e.Vertexes[0].Point, e.Vertexes[-1].Point))
    return view, out[0], out[1]


def picked_sharp():
    ""
    hit = picked_lines()
    if hit is None:
        return False
    from . import drawdocprops as DP
    view, (a1, b1), (a2, b2) = hit
    doc = view.Document
    doc.openTransaction("Virtual Sharp")
    try:
        DP.virtual_sharp(view, a1, b1, a2, b2, DP.sharp_style(doc))
    except ValueError:
        doc.abortTransaction()
        return False
    doc.commitTransaction()
    doc.recompute()
    Gui.Selection.clearSelection()
    return True


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    try:
        from . import drawsketchedit
        drawsketchedit.register()
    except Exception as e:
        App.Console.PrintWarning("FreeCAD: drawing sketch tools: %s\n" % e)
    try:
        from . import drawsketchmore    # land88: 3 Point rectangles, arc slots, conic ...; Segment, Extend, Jog ...
        drawsketchmore.register()
    except Exception as e:
        App.Console.PrintWarning("FreeCAD: drawing sketch tools (more): %s\n" % e)
    try:
        from . import drawdimtools      # Dimension Palette, Align, Autodimension, Ordinate, Chamfer Dimension
        drawdimtools.register()
    except Exception as e:
        App.Console.PrintWarning("FreeCAD: drawing dimension tools: %s\n" % e)
    try:
        from . import drawmbd           # MBD: General Profile Tolerance, Import Scheme, Delete All Tolerances
        drawmbd.register()
    except Exception as e:
        App.Console.PrintWarning("FreeCAD: MBD annotations: %s\n" % e)
