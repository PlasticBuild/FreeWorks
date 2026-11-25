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
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import sketch3dsolve as S

Qt = QtCore.Qt
PAGE = "Sketch3D"

TOOL_TITLES = {"Line": "Insert Line", "Centerline": "Insert Line", "Spline": "Spline", "Point": "Point",
               "Smart Dimension": "Dimension", "Circle": "Circle", "Centerpoint Arc": "Arc", "3 Point Arc": "Arc",
               "Corner Rectangle": "Rectangle", "Center Rectangle": "Rectangle"}
TOOL_ICONS = {"Line": "SKETCH_LINE", "Centerline": "SKETCH_CENTERLINE", "Spline": "SKETCH_SPLINE",
              "Point": "SKETCH_POINT", "Smart Dimension": "LAYOUT_SMART_DIM", "Circle": "SKETCH_CIRCLE",
              "Centerpoint Arc": "SKETCH_CPRPT_ARC", "3 Point Arc": "SKETCH_3PT_ARC",
              "Corner Rectangle": "SKETCH_CORNER_RECT", "Center Rectangle": "SKETCH_CTR_RECT"}

TYPE_GROUPS = {
    "Circle": (("Circle", "circle", "SKETCH_CIRCLE"), ("Perimeter Circle", "perimetercircle", "SKETCH_CTRPT_CIRCLE")),
    "Arc": (("Centerpoint Arc", "centerarc", "SKETCH_CPRPT_ARC"), ("Tangent Arc", "tangentarc", "SKETCH_TANGET_ARC"),
            ("3 Point Arc", "arc3", "SKETCH_3PT_ARC")),
    "Rectangle": (("Corner Rectangle", "rectangle", "SKETCH_CORNER_RECT"),
                  ("Center Rectangle", "centerrectangle", "SKETCH_CTR_RECT"),
                  ("3 Point Corner Rectangle", "rect3corner", "SKETCH_3PT_CORNER_RECT"),
                  ("3 Point Center Rectangle", "rect3center", "SKETCH_3PT_CENTER_RECT"),
                  ("Parallelogram", "parallelogram", "SKETCH_PARALLELOGRAM")),
}
GROUP_OF = {t[0]: g for g, types in TYPE_GROUPS.items() for t in types}
# FreeCAD's own pictures where the icon pack has none
FALLBACK = {"Circle": "Sketcher_CreateCircle", "Perimeter Circle": "Sketcher_Create3PointCircle",
            "Centerpoint Arc": "Sketcher_CreateArc", "Tangent Arc": "Sketcher_CreatePolyline",
            "3 Point Arc": "Sketcher_Create3PointArc", "Corner Rectangle": "Sketcher_CreateRectangle",
            "Center Rectangle": "Sketcher_CreateRectangle_Center", "3 Point Corner Rectangle": "Sketcher_CreateRectangle",
            "3 Point Center Rectangle": "Sketcher_CreateRectangle_Center", "Parallelogram": "Sketcher_CreateRectangle"}


def type_icon(name, key):
    """The icon pack's picture, else FreeCAD's, else the name's initials (no blank button)."""
    try:
        from . import icons
        icon = icons.family(key) if key else QtGui.QIcon()
        if not icons.paints(icon) and name in FALLBACK:
            icon = QtGui.QIcon(Gui.getIcon(FALLBACK[name]))
        if not icons.paints(icon):
            icon = icons.initials(name)
        return icon
    except Exception:
        return QtGui.QIcon()
for _g, _types in TYPE_GROUPS.items():
    for _t in _types:
        TOOL_TITLES.setdefault(_t[0], _g)
        TOOL_ICONS.setdefault(_t[0], _t[2])
TOOL_TITLES.update({"Trim Entities": "Trim", "Convert Entities": "Convert Entities", "Mirror": "Mirror",
                    "Intersection Curve": "Intersection Curve", "Face Curves": "Face Curves",
                    "Spline on Surface": "Spline", "Offset on Surface": "Offset on Surface",
                    "Equation Driven Curve": "Equation Driven Curve",
                    "Sketch Fillet": "Sketch Fillet", "Sketch Chamfer": "Sketch Chamfer",
                    "Extend Entities": "Extend Entities", "Split Entities": "Split Entities", "Move": "Move",
                    "Segment": "Segment", "Fit Spline": "Fit Spline", "Jog Line": "Jog Line", "Route Line": "Route Line", "Pen Sketch": "Pen Sketch",
                    "Replace Entity": "Replace Entity", "Style Spline": "Style Spline",
                    "Simplify Spline": "Simplify Spline", "Insert Control Vertex": "Insert Control Vertex", "Copy": "Copy", "Rotate": "3D Rotate",
                    "Plane": "Sketch Plane"})
TOOL_ICONS.update({"Trim Entities": "SKETCH_TRIM", "Convert Entities": "SKETCH_CONVERT_ENTITIES",
                   "Intersection Curve": "SKETCH_INTERSECTION_CURVE", "Face Curves": "SKETCH_FACE_CURVES",
                   "Equation Driven Curve": "SKETCH_EQUATION_CURVE",
                   "Spline on Surface": "SKETCH_SPLINE_ON_SURFACE", "Offset on Surface": "SKETCH_OFFSET_ON_SURFACE",
                   "Mirror": "SKETCH_MIRROR_ENTITIES", "Sketch Fillet": "SKETCH_FILLET",
                   "Sketch Chamfer": "SKETCH_CHAMFER", "Extend Entities": "SKETCH_EXTEND_ENTITIES",
                   "Split Entities": "SKETCH_SPLIT_ENTITIES", "Segment": "SKETCH_SEGMENT",
                   "Fit Spline": "SKETCH_FIT_SPLINE", "Jog Line": "SKETCH_JOG_LINE", "Route Line": "SKETCH_LINE", "Pen Sketch": "SKETCH_INK",
                   "Replace Entity": "SKETCH_REPLACE_ENTITY", "Style Spline": "SKETCH_STYLE_SPLINE",
                   "Move": "SKETCH_MOVE_ENTITIES", "Copy": "SKETCH_COPY_ENTITIES",
                   "Rotate": "SKETCH_ROTATE_ENTITIES", "Plane": "REFGEO_PLANE"})
REFERENCES = ("First Reference", "Second Reference", "Third Reference")
DRAWING = ("Line", "Centerline", "Spline", "Style Spline", "Spline on Surface") + tuple(GROUP_OF)
TRIM_MODES = ("Power trim", "Corner", "Trim away inside", "Trim away outside", "Trim to closest")
TRIM_3D = ("Power trim", "Trim to closest")
MESSAGES = {
    "Line": "Sketch a line in 3D: click its start, then each next point. Double-click or right-click ends "
            "the chain.\n\nThe line is drawn on %(plane)s. Press Tab to "
            "change the plane (XY, YZ, ZX). Hold Ctrl to place a point with no relations.",
    "Spline": "Click the points the spline goes through. Double-click, right-click or Esc ends it; a click on "
              "its first point closes it.\n\nPoints are placed on %(plane)s. Press Tab to change "
              "the plane (XY, YZ, ZX).",
    "Point": "Click to place sketch points on %(plane)s, or on the model and the sketch. "
             "Press Tab to change the plane.",
    "Smart Dimension": "Pick a line, or two points, to dimension the distance between them. Two lines give "
                       "their angle, a circle its diameter, an arc its radius, a point and a plane or flat face "
                       "the distance square to it.",
    "Circle": "Click the center, then a point on the rim. The circle lies on %(plane)s; press Tab to change "
              "the plane (XY, YZ, ZX).",
    "Centerpoint Arc": "Click the arc's center, then its start, then its end; the arc goes the way the pointer "
                       "goes round. It lies on %(plane)s; press Tab to change the plane.",
    "3 Point Arc": "Click the arc's start, then its end, then a point it goes through. It lies on %(plane)s; "
                   "press Tab to change the plane.",
    "Corner Rectangle": "Click one corner, then the opposite corner. The rectangle lies on %(plane)s; press "
                        "Tab to change the plane.",
    "Center Rectangle": "Click the center, then a corner. The rectangle lies on %(plane)s; press Tab to change "
                        "the plane.",
    "Perimeter Circle": "Click three points on the circle. It lies on %(plane)s; press Tab to change the plane.",
    "Tangent Arc": "Click the end of a line, then where the arc ends: the arc leaves the line along it.",
    "3 Point Corner Rectangle": "Click two corners (one side), then the width. The rectangle lies on %(plane)s.",
    "3 Point Center Rectangle": "Click the center, the middle of one side, then the width, on %(plane)s.",
    "Parallelogram": "Click two corners (one side), then the third corner, on %(plane)s.",
    "Trim Entities": "Power trim: drag across the entities to trim them, or click one. Trim to closest: click "
                     "the piece to remove; it goes back to the closest crossings in space.",
    "Convert Entities": "Pick model edges or faces to convert into 3D sketch entities, then OK (Enter). They "
                        "stay on the model.",
    "Spline on Surface": "Click points on a face of the model; the spline goes through them and lies on the face. "
                         "Double-click, right-click or Esc ends it.",
    "Offset on Surface": "Pick edges of a face (or the face for all its edges), set the distance, then OK (Enter). "
                         "Geodesic measures along the face, Euclidean straight.",
    "Intersection Curve": "Pick two or more faces, planes or bodies of the model where they meet, then OK (Enter). "
                          "The curves where they meet become 3D sketch entities.",
    "Equation Driven Curve": "Type the curve as a parametric equation in t (x, y and z; sin, cos, pi, sqrt... "
                             "and ^ for a power), from the start value t1 to the end value t2, then OK (Enter).",
    "Face Curves": "Pick a face of the model. Mesh: how many curves each way; Position: one curve each way where "
                   "you set it. OK (Enter) adds them to the 3D sketch.",
    "Mirror": "Pick the 3D sketch entities to mirror, then a plane or flat face of the model under Mirror "
              "about, then OK (Enter).",
    "Sketch Fillet": "Pick the corners to fillet (a point where two lines meet, or the two lines), set the "
                     "radius, then OK (Enter). The arcs are tangent to the lines.",
    "Sketch Chamfer": "Pick the corners to chamfer (a point where two lines meet, or the two lines), set the "
                      "distances, then OK (Enter). Each corner is cut back and closed by a line.",
    "Extend Entities": "Click a line or arc near the end to extend. It goes on to the next entity it meets in "
                       "space; the preview shows where.",
    "Split Entities": "Click a line, arc or open spline where it splits in two. A circle takes two split points "
                      "and becomes two arcs.",
    "Segment": "Pick a line, arc, circle or spline. Sketch points: points spread evenly on it; Sketch segments: "
               "it is cut into equal pieces. Set the Number of Instances, then OK (Enter).",
    "Fit Spline": "Pick lines, arcs or splines that join end to end, then OK (Enter): one spline follows them "
                  "within the Tolerance.",
    "Pen Sketch": "Draw on the sketch plane with the left mouse button (or a pen). A straight stroke becomes a "
                  "line, any other a spline.",
    "Route Line": "Click the start point and the end point. Alternate Path goes round the routes along X, Y "
                  "and Z; OK keeps it.",
    "Jog Line": "Click the line where the jog goes. Set the width and depth (Flip side for the other way), then "
                "OK (Enter). The jog stands out on %(plane)s.",
    "Simplify Spline": "Pick a spline, set the Tolerance, then OK (Enter): the spline keeps its shape within the "
                       "tolerance with fewer points.",
    "Insert Control Vertex": "Click on a Style Spline where the new control vertex goes. Esc ends.",
    "Style Spline": "Click the control vertices of the Style Spline; the curve starts and ends on the first and "
                    "last. Double-click, right-click or Esc ends it.\n\nPoints are placed on %(plane)s. Press Tab "
                    "to change the plane (XY, YZ, ZX).",
    "Replace Entity": "Pick the entity to replace, then the entity that replaces it, then OK (Enter). Its "
                      "relations and the entities joined to it go to the new one.",
    "Move": "Pick the entities to move. From/To: click the start point, then where it goes on %(plane)s. "
            "X/Y/Z: type how far, then OK (Enter).",
    "Copy": "Pick the entities to copy. From/To: click the start point, then where the copy goes on %(plane)s. "
            "X/Y/Z: type how far, then OK (Enter). Repeat adds one more copy.",
    "Rotate": "Pick the entities to rotate, then click in Rotation Reference and pick a line or a straight model "
              "edge to turn them about. Type the Angle, then OK (Enter).",
    "Plane": "Pick up to three references: sketch points or lines, or a plane or flat face of the model. "
             "Three points: the plane through them; a point and a plane: Parallel to it through the point; "
             "nothing: a plane on %(plane)s. OK (Enter) adds it and you sketch on it.",
}


def _module(name):
    import importlib
    return importlib.import_module("." + name, __package__)


def _shell():
    try:
        return _module("shell").shell()
    except Exception as _fw_err:
        _fw_log("sketch3dpm.py:195", _fw_err)
        return None


# ------------------------------------------------------------------ the host
class _Host:
    """One page at a time: in the add-on's left pane (PropertyManager tab), else a tool window."""

    def __init__(self):
        self.page = None
        self.pane = None
        self.window = None

    def show(self, page):
        self.close()
        self.page = page
        sh = _shell()
        pane = getattr(sh, "left_pane", None) if sh is not None else None
        try:
            from .widgets import alive
        except Exception:
            def alive(w):
                return w is not None
        if pane is not None and alive(pane):
            self.pane = pane
            old = pane.pages.get(PAGE)
            if old is not None and alive(old):
                pane.stack.removeWidget(old)
            pane._add_page(PAGE, page)
            pane.select_name(PAGE)
            try:
                from . import relationspm
                pane.header.set_current(relationspm.PM_TAB)
            except Exception as _fw_err:
                _fw_log("sketch3dpm.py:227", _fw_err)
        else:
            w = self.window = QtWidgets.QWidget(Gui.getMainWindow(), Qt.Tool)
            w.setObjectName("FreeWorks3DSketchPM")
            w.setWindowTitle(page.TITLE)
            lay = QtWidgets.QVBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(page)
            w.resize(260, 420)
            w.show()
        _focus_view()

    def close(self):
        page, self.page = self.page, None
        if page is None:
            return
        try:
            page.closing()
        except Exception as _fw_err:
            _fw_log("sketch3dpm.py:246", _fw_err)
        pane, self.pane = self.pane, None
        if pane is not None:
            try:
                pane.pages.pop(PAGE, None)
                pane.stack.removeWidget(page)
                pane.restore_user_page()
            except Exception as _fw_err:
                _fw_log("sketch3dpm.py:254", _fw_err)
        if self.window is not None:
            try:
                self.window.close()
                self.window.deleteLater()
            except Exception as _fw_err:
                _fw_log("sketch3dpm.py:260", _fw_err)
            self.window = None
        try:
            page.setParent(None)
            page.deleteLater()
        except Exception as _fw_err:
            _fw_log("sketch3dpm.py:266", _fw_err)
        _focus_view()


_host = _Host()


def current():
    return _host.page


def _focus_view():
    sh = _shell()
    view = sh.view_widget() if sh is not None else None
    if view is not None:
        try:
            view.setFocus(Qt.OtherFocusReason)
        except Exception as _fw_err:
            _fw_log("sketch3dpm.py:284", _fw_err)


# ------------------------------------------------------------------ pages
def _base():
    return _module("sketchtoolpm").ToolPage


def _relationspm():
    return _module("relationspm")


def _relation_icon(key):
    """The Plane page's relation buttons: the relation pictures of Add Relations, a dimension's for
    Distance and Angle."""
    try:
        if key in ("Distance", "Angle"):
            return QtGui.QIcon(Gui.getIcon({"Distance": "Constraint_Length", "Angle": "Constraint_InternalAngle"}[key]))
        return _relationspm().relation_icon(key)
    except Exception:
        return QtGui.QIcon()


def _draw_along(axis):
    rp = _relationspm()

    def draw(p):
        rp._pen(p, width=1.6)
        rp._line(p, 2.0, 12.0, 14.0, 12.0)
        rp._line(p, 11.5, 9.5, 14.0, 12.0)
        rp._line(p, 11.5, 14.5, 14.0, 12.0)
        rp._letter(p, axis, 4.0, 9.0, 9.0)
    return draw


def _draw_on_plane(curved):
    rp = _relationspm()

    def draw(p):
        rp._pen(p, width=1.2)
        if curved:
            path = QtGui.QPainterPath(QtCore.QPointF(1.5, 12.5))
            path.cubicTo(QtCore.QPointF(5, 7), QtCore.QPointF(10, 15), QtCore.QPointF(14.5, 9.5))
            p.drawPath(path)
        else:
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(1.5, 13.5), QtCore.QPointF(5.5, 8.5),
                                           QtCore.QPointF(14.5, 8.5), QtCore.QPointF(10.5, 13.5)]))
        rp._pen(p, width=2.4)
        p.drawPoint(QtCore.QPointF(8, 5))
        rp._pen(p, width=1.0)
        rp._line(p, 8, 5.5, 8, 10.5)
    return draw


def relation_icon(kind):
    rp = _relationspm()
    try:
        if kind in S.ALONG:
            return rp._icon(_draw_along(kind[-1]))
        if kind in ("OnPlane", "OnSurface", "OnSketchPlane"):
            return rp._icon(_draw_on_plane(kind == "OnSurface"))
        key = {"OnLine": "Coincident", "AtRef": "Coincident", "OnEdge": "Coincident", "OnArc": "Coincident",
               "SymPlane": "Symmetric", "PlaneParallel": "Parallel", "PlaneNormal": "Perpendicular",
               "ParallelYZ": "Parallel", "ParallelZX": "Parallel", "TangentArcs": "Tangent", "ArcMidpoint": "Midpoint",
               "PlaneH": "Horizontal", "PlaneV": "Vertical", "AlongDirH": "Horizontal", "AlongDirV": "Vertical",
               "SplineTangent": "Tangent", "SplineTangentArc": "Tangent", "SplineTangentSpline": "Tangent", "CurveLength": "Equal Curve Length",
               "Distance": None,
               "Angle": None, "Diameter": None, "Radius": None, "PlaneDistance": None, "LineDistance": None,
               "PlaneAngle": None}.get(kind, kind)
        if key is None:
            from . import icons
            icon = icons.family("DIMENSIONS_ANGULAR" if kind in S.ANGLES else "LAYOUT_SMART_DIM")
            return icon
        return rp.relation_icon(key)
    except Exception:
        return QtGui.QIcon()


def entity_name(s, item):
    ""
    kind, i = item
    if kind == "P":
        return "Point%d" % (i + 1)
    if kind == "R":
        n = sum(1 for r in s.rels[:i + 1] if r.kind in S.DIMENSIONS)
        return "D%d" % n
    e = s.ents[i]

    word = {"L": "Line", "S": "Spline", "P": "Point", "C": "Arc", "A": "Arc", "Q": "Plane"}[e.kind]
    same = ("C", "A") if e.kind in ("C", "A") else (e.kind,)
    n = sum(1 for x in s.ents[:i + 1] if x.kind in same)
    return "%s%d" % (word, n)


def relation_text(s, k):
    r = s.rels[k]
    if r.kind == "Distance":
        return "Distance %s" % _fmt(r.values[0])
    if r.kind == "Angle":
        return "Angle %.2f\u00b0" % r.values[0]
    if r.kind == "Diameter":
        return "Diameter %s" % _fmt(r.values[0])
    if r.kind == "Radius":
        return "Radius %s" % _fmt(r.values[0])
    if r.kind == "LineDistance":
        return "Distance %s" % _fmt(r.values[0])
    if r.kind == "PlaneAngle":
        what = r.ref[1] if r.ref and r.ref[1] not in ("", "-") else ""
        return "Angle %.2f\u00b0 (%s)" % (r.values[0], _label(s.doc, r.ref[0]) + (" " + what if what else ""))
    if r.kind == "PlaneDistance":
        what = r.ref[1] if r.ref and r.ref[1] not in ("", "-") else ""
        return "Distance %s (%s)" % (_fmt(r.values[0]), _label(s.doc, r.ref[0]) + (" " + what if what else ""))
    if r.kind in ("OnPlane", "OnSurface", "OnEdge"):
        what = r.ref[1] if r.ref and r.ref[1] not in ("", "-") else ""
        target = _label(s.doc, r.ref[0]) + (" " + what if what else "")
        return "%s (%s)" % (r.name(), target)
    if r.kind == "OnSketchPlane":
        for q in range(len(s.ents)):
            if s.ents[q].kind == "Q" and s.ents[q].points[:3] == r.points[1:4]:
                return "On Plane (%s)" % entity_name(s, ("E", q))
        return "On Plane"
    if r.kind in ("PlaneParallel", "PlaneNormal", "ParallelYZ", "ParallelZX"):
        what = r.ref[1] if r.ref and r.ref[1] not in ("", "-") else ""
        return "%s (%s)" % (r.name(), _label(s.doc, r.ref[0]) + (" " + what if what else ""))
    if r.kind == "SymPlane":
        what = r.ref[1] if r.ref and r.ref[1] not in ("", "-") else ""
        return "Symmetric (%s)" % (_label(s.doc, r.ref[0]) + (" " + what if what else ""))
    if r.kind == "AtRef" and r.ref and r.ref[1].endswith("#Mid"):
        return "Midpoint (%s of %s)" % (r.ref[1][:-4], _label(s.doc, r.ref[0]))
    if r.kind == "AtRef" and r.ref and r.ref[1].startswith("Edge"):
        return "Coincident (center of %s of %s)" % (r.ref[1], _label(s.doc, r.ref[0]))
    if r.kind == "AtRef":
        where = "the origin" if r.ref and r.ref[1] == "Origin" else "%s of %s" % (r.ref[1], _label(s.doc, r.ref[0]))
        return "Coincident (%s)" % where
    return r.name()


def _label(doc, name):
    o = doc.getObject(name) if name else None
    return o.Label if o is not None else name


def _fmt(value):
    try:
        return App.Units.Quantity(value, App.Units.Length).UserString
    except Exception:
        return "%.2f mm" % value


def _command_icon_pm(name):
    try:
        return QtGui.QIcon(Gui.getIcon(name))
    except Exception:
        return QtGui.QIcon()


def _spin(parent, value, lo=-1e7, hi=1e7, angle=False):
    w = QtWidgets.QDoubleSpinBox(parent)
    w.setDecimals(2)
    w.setRange(lo, 180.0 if angle and hi == 1e7 else hi)
    w.setSuffix("\u00b0" if angle else " mm")
    w.setKeyboardTracking(False)
    w.setValue(float(value))
    return w


def make_tool_page(session, tool):
    Base = _base()

    class ToolPage3D(Base):
        TITLE = TOOL_TITLES.get(tool.title(), tool.title())
        ICON = TOOL_ICONS.get(tool.title())
        PIXMAP = "Sketcher_CreateLine"

        def __init__(self):
            self.s, self.tool = session, tool
            super().__init__(session.obj)
            self.setObjectName("SWRelationsPM")

        def build(self):
            g = self.group("Message")
            self.message = QtWidgets.QLabel("", g.body)
            self.message.setObjectName("SW3DSketchMessage")
            self.message.setWordWrap(True)
            g.content.addWidget(self.message)
            self.update_message()
            title = self.tool.title()
            if title in GROUP_OF:
                self._types(GROUP_OF[title], title)
            if title == "Trim Entities":
                self._trim_options()
            if title == "Convert Entities":
                self._convert_list()
            if title == "Intersection Curve":
                self._intersection_list()
            if title == "Face Curves":
                self._face_curves_options()
            if title == "Offset on Surface":
                self._offset_surface_options()
            if title == "Equation Driven Curve":
                self._equation_options()
            if title == "Mirror":
                self._mirror_lists()
            if title == "Sketch Fillet":
                self._fillet_options()
            if title == "Sketch Chamfer":
                self._chamfer_options()
            if title == "Segment":
                self._segment_options()
            if title == "Fit Spline":
                self._fit_spline_options()
            if title == "Jog Line":
                self._jog_options()
            if title == "Route Line":
                self._route_options()
            if title == "Replace Entity":
                self._replace_options()
            if title == "Simplify Spline":
                self._simplify_options()
            if title in ("Move", "Copy"):
                self._move_options()
            if title == "Rotate":
                self._rotate_options()
            if title == "Plane":
                self._plane_references()
            line = self.tool.title() in ("Line", "Centerline")
            if line:

                g = self.group("Orientation")
                for text in ("As sketched", "Horizontal", "Vertical", "Angle"):
                    r = QtWidgets.QRadioButton(text, g.body)
                    r.setObjectName("SW3DLineOrientation" + text.replace(" ", ""))
                    r.setChecked(text == "As sketched")
                    r.setEnabled(text == "As sketched")
                    g.content.addWidget(r)
            if self.tool.title() in DRAWING:
                o = self.group("Options")
                self.construction = QtWidgets.QCheckBox("For construction", o.body)
                self.construction.setObjectName("SW3DSketchConstruction")
                self.construction.setChecked(bool(self.tool.construction))
                self.construction.toggled.connect(self._construction)
                o.content.addWidget(self.construction)
                if line:
                    inf = QtWidgets.QCheckBox("Infinite length", o.body)
                    inf.setObjectName("SW3DLineInfinite")
                    inf.setEnabled(False)
                    inf.setToolTip("Infinite lines are 2D sketch geometry")
                    o.content.addWidget(inf)
                    self.midpoint = QtWidgets.QCheckBox("Midpoint line", o.body)
                    self.midpoint.setObjectName("SW3DLineMidpoint")
                    self.midpoint.setChecked(bool(getattr(self.tool, "midpoint", False)))
                    self.midpoint.toggled.connect(self.tool.set_midpoint)
                    o.content.addWidget(self.midpoint)
                if GROUP_OF.get(title) == "Rectangle":
                    self.lines = QtWidgets.QCheckBox("Add construction lines", o.body)
                    self.lines.setObjectName("SW3DRectangleConstructionLines")
                    self.lines.setChecked(bool(self.tool.lines))
                    o.content.addWidget(self.lines)
                    self.lines_from = {}
                    for name in ("From Corners", "From Midpoints"):
                        r = QtWidgets.QRadioButton(name, o.body)
                        r.setObjectName("SW3DRectangle" + name.replace(" ", ""))
                        r.setChecked(name == self.tool.lines_from)
                        r.setEnabled(self.lines.isChecked())
                        r.toggled.connect(lambda on, n=name: on and setattr(self.tool, "lines_from", n))
                        o.content.addWidget(r)
                        self.lines_from[name] = r

                    def lines_on(on):
                        self.tool.lines = bool(on)
                        for r in self.lines_from.values():
                            r.setEnabled(bool(on))
                    self.lines.toggled.connect(lines_on)

        def _types(self, group, title):
            g = self.group("%s Type" % group)
            types = TYPE_GROUPS[group]
            icon_of = {t[0]: t[2] for t in types}
            self.type_buttons = self.toggles(g, [t[0] for t in types], lambda k: type_icon(k, icon_of[k]),
                                             lambda k: k == title)
            for name, b in self.type_buttons.items():
                b.setObjectName("SW3DType" + name.replace(" ", ""))
                b.clicked.connect(lambda checked=False, n=name: self._switch(n, types))

        def _switch(self, name, types):
            for n, b in self.type_buttons.items():
                b.setChecked(n == name)
            if name == self.tool.title():
                return
            key = next(t[1] for t in types if t[0] == name)
            construction = bool(self.tool.construction)
            from . import sketch3d
            QtCore.QTimer.singleShot(0, lambda: _start(sketch3d, key, construction))

        def _trim_options(self):
            g = self.group("Options")
            # the same list as the 2D Trim page; in space only Power trim and Trim to closest apply
            self.trim_buttons = {}
            for name in TRIM_MODES:
                b = QtWidgets.QRadioButton(name, g.body)
                b.setObjectName("SW3DTrim" + name.replace(" ", ""))
                b.setChecked(name == self.tool.mode)
                if name not in TRIM_3D:
                    b.setEnabled(False)
                    b.setToolTip("%s: 2D sketches only" % name)
                b.clicked.connect(lambda checked=False, n=name: self._trim_mode(n))
                g.content.addWidget(b)
                self.trim_buttons[name] = b
            for text, attr, obj in (("Keep trimmed entities as construction geometry", "keep_construction",
                                     "SW3DTrimKeep"),
                                    ("Ignore trimming of construction geometry", "ignore_construction",
                                     "SW3DTrimIgnore")):
                c = QtWidgets.QCheckBox(text, g.body)
                c.setObjectName(obj)
                c.setChecked(bool(getattr(self.tool, attr)))
                c.toggled.connect(lambda on, a=attr: setattr(self.tool, a, bool(on)))
                g.content.addWidget(c)

        def _trim_mode(self, name):
            self.tool.mode = name
            for n, b in self.trim_buttons.items():
                b.setChecked(n == name)
            self.update_message()

        def _convert_list(self):
            g = self.group("Entities to Convert")
            self.picks = QtWidgets.QListWidget(g.body)
            self.picks.setObjectName("SW3DConvertList")
            self.picks.setMaximumHeight(110)
            g.content.addWidget(self.picks)
            self.picks_changed()

        def _intersection_list(self):
            g = self.group("Selections")
            self.picks = QtWidgets.QListWidget(g.body)
            self.picks.setObjectName("SW3DIntersectionList")
            self.picks.setMaximumHeight(110)
            g.content.addWidget(self.picks)
            self.picks_changed()

        def _face_curves_options(self):
            t = self.tool
            g = self.group("Selections")
            self.picks = QtWidgets.QListWidget(g.body)
            self.picks.setObjectName("SW3DFaceCurvesFace")
            self.picks.setMaximumHeight(28)
            g.content.addWidget(self.picks)
            self.fc_modes = {}
            for name in ("Mesh", "Position"):
                r = QtWidgets.QRadioButton(name, g.body)
                r.setObjectName("SW3DFaceCurves" + name)
                r.setChecked(name == t.mode)
                r.clicked.connect(lambda checked=False, n=name: self._fc_set("mode", n))
                g.content.addWidget(r)
                self.fc_modes[name] = r
            self.fc_counts, self.fc_pos = [], []
            for k in range(2):
                row = QtWidgets.QHBoxLayout()
                on = QtWidgets.QCheckBox("Direction %d" % (k + 1), g.body)
                on.setObjectName("SW3DFaceCurvesDir%d" % (k + 1))
                on.setChecked(t.dirs[k])
                on.toggled.connect(lambda v, k=k: self._fc_dir(k, v))
                n = QtWidgets.QSpinBox(g.body)
                n.setObjectName("SW3DFaceCurvesCount%d" % (k + 1))
                n.setRange(1, 200)
                n.setValue(t.counts[k])
                n.setKeyboardTracking(False)
                n.valueChanged.connect(lambda v, k=k: self._fc_count(k, v))
                p = QtWidgets.QDoubleSpinBox(g.body)
                p.setObjectName("SW3DFaceCurvesPos%d" % (k + 1))
                p.setRange(0.0, 100.0)
                p.setSuffix(" %")
                p.setValue(t.pos[k])
                p.setKeyboardTracking(False)
                p.valueChanged.connect(lambda v, k=k: self._fc_posv(k, v))
                for w in (on, n, p):
                    row.addWidget(w)
                g.content.addLayout(row)
                self.fc_counts.append(n)
                self.fc_pos.append(p)
            o = self.group("Options")
            for text, attr, obj in (("Constrain to model", "constrain", "SW3DFaceCurvesConstrain"),
                                    ("Ignore holes", "ignore_holes", "SW3DFaceCurvesIgnoreHoles")):
                c = QtWidgets.QCheckBox(text, o.body)
                c.setObjectName(obj)
                c.setChecked(bool(getattr(t, attr)))
                c.toggled.connect(lambda on, a=attr: self._fc_set(a, bool(on)))
                o.content.addWidget(c)
            self._fc_shown()
            self.picks_changed()

        def _fc_shown(self):
            mesh = self.tool.mode == "Mesh"
            for n, p in zip(self.fc_counts, self.fc_pos):
                n.setVisible(mesh)
                p.setVisible(not mesh)
            for name, r in self.fc_modes.items():
                r.setChecked(name == self.tool.mode)

        def _fc_set(self, attr, value):
            setattr(self.tool, attr, value)
            if attr == "mode":
                self._fc_shown()
            self.tool.move(*self.s.cursor())

        def _fc_dir(self, k, on):
            self.tool.dirs[k] = bool(on)
            self.tool.move(*self.s.cursor())

        def _fc_count(self, k, v):
            self.tool.counts[k] = int(v)
            self.tool.move(*self.s.cursor())

        def _fc_posv(self, k, v):
            self.tool.pos[k] = float(v)
            self.tool.move(*self.s.cursor())

        def _equation_options(self):


            # and Parameters t_1 t_2)
            t = self.tool
            g = self.group("Parameters")
            g.content.addWidget(QtWidgets.QLabel("Equation", g.body))
            self.eq_fields = []
            for k, name in enumerate(("x", "y", "z")):
                row = QtWidgets.QHBoxLayout()
                row.addWidget(QtWidgets.QLabel(name + "\u209c", g.body))
                e = QtWidgets.QLineEdit(t.exprs[k], g.body)
                e.setObjectName("SW3DEquation" + name.upper())
                e.editingFinished.connect(lambda k=k, e=e: self._eq_set(k, e.text()))
                row.addWidget(e)
                g.content.addLayout(row)
                self.eq_fields.append(e)
            g.content.addWidget(QtWidgets.QLabel("Parameters", g.body))
            self.eq_range = []
            for k, name in enumerate(("t\u2081", "t\u2082")):
                row = QtWidgets.QHBoxLayout()
                row.addWidget(QtWidgets.QLabel(name, g.body))
                e = QtWidgets.QLineEdit("%g" % (t.t1 if k == 0 else t.t2), g.body)
                e.setObjectName("SW3DEquationT%d" % (k + 1))
                e.editingFinished.connect(lambda k=k, e=e: self._eq_range(k, e.text()))
                row.addWidget(e)

                # it; unlocked, the end is free to drag
                lock = QtWidgets.QToolButton(g.body)
                lock.setObjectName("SW3DEquationLockT%d" % (k + 1))
                lock.setCheckable(True)
                lock.setChecked(t.locks[k])
                lock.setAutoRaise(True)
                lock.setToolTip("Lock " + ("t₁" if k == 0 else "t₂"))
                self._lock_look(lock)
                lock.toggled.connect(lambda on, k=k, b=lock: (self.tool.locks.__setitem__(k, bool(on)),
                                                              self._lock_look(b)))
                row.addWidget(lock)
                g.content.addLayout(row)
                self.eq_range.append(e)

        def _lock_look(self, button):
            on = button.isChecked()
            icon = _command_icon_pm("Constraint_Lock")
            if not icon.isNull():
                button.setIcon(icon)
            button.setText("\U0001F512" if on else "\U0001F513")
            button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly if not icon.isNull()
                                      else QtCore.Qt.ToolButtonTextOnly)
            button.setToolTip(("Unlock " if on else "Lock ") + button.toolTip().split(" ", 1)[-1])

        def _eq_set(self, k, text):
            self.tool.exprs[k] = text
            self._eq_shown()

        def _eq_range(self, k, text):
            # t1 and t2 take numbers or expressions such as 2*pi
            try:
                from .sketch3d import _equation
                v = _equation(text)(0.0)
            except Exception:
                v = None
            if v is not None:
                if k == 0:
                    self.tool.t1 = v
                else:
                    self.tool.t2 = v
            self._eq_shown()

        def _eq_shown(self):
            self.tool.move(*self.s.cursor())
            if self.tool.error:
                self.message.setText(self.tool.error)
            else:
                self.update_message()

        def _offset_surface_options(self):
            t = self.tool
            g = self.group("Selections")
            self.picks = QtWidgets.QListWidget(g.body)
            self.picks.setObjectName("SW3DOffsetSurfaceList")
            self.picks.setMaximumHeight(90)
            g.content.addWidget(self.picks)
            g = self.group("Offset Parameters")
            self.os_modes = {}
            for name, geo in (("Geodesic Offset", True), ("Euclidean Offset", False)):
                r = QtWidgets.QRadioButton(name, g.body)
                r.setObjectName("SW3DOffsetSurface" + name.split()[0])
                r.setChecked(geo == t.geodesic)
                r.clicked.connect(lambda checked=False, v=geo: self._os_set("geodesic", v))
                g.content.addWidget(r)
                self.os_modes[geo] = r
            dist = _spin(g.body, t.distance, lo=0.001)
            dist.setObjectName("SW3DOffsetSurfaceDistance")
            dist.valueChanged.connect(lambda v: self._os_set("distance", float(v)))
            g.content.addWidget(dist)
            for text, attr, obj in (("Reverse", "reverse", "SW3DOffsetSurfaceReverse"),
                                    ("Make offset construction", "make_construction", "SW3DOffsetSurfaceConstruction")):
                c = QtWidgets.QCheckBox(text, g.body)
                c.setObjectName(obj)
                c.setChecked(bool(getattr(t, attr)))
                c.toggled.connect(lambda on, a=attr: self._os_set(a, bool(on)))
                g.content.addWidget(c)
            self.picks_changed()

        def _os_set(self, attr, value):
            setattr(self.tool, attr, value)
            if attr == "geodesic":
                for v, r in self.os_modes.items():
                    r.setChecked(v == value)
            self.tool.move(*self.s.cursor())

        def _mirror_lists(self):
            g = self.group("Options")
            self.mirror_items = QtWidgets.QListWidget(g.body)
            self.mirror_items.setObjectName("SW3DMirrorEntities")
            self.mirror_items.setMaximumHeight(90)
            g.content.addWidget(QtWidgets.QLabel("Entities to mirror", g.body))
            g.content.addWidget(self.mirror_items)
            self.copy = QtWidgets.QCheckBox("Copy", g.body)
            self.copy.setObjectName("SW3DMirrorCopy")
            self.copy.setChecked(self.tool.copy)
            self.copy.toggled.connect(lambda on: setattr(self.tool, "copy", bool(on)))
            g.content.addWidget(self.copy)
            g.content.addWidget(QtWidgets.QLabel("Mirror about", g.body))
            self.mirror_about = QtWidgets.QListWidget(g.body)
            self.mirror_about.setObjectName("SW3DMirrorAbout")
            self.mirror_about.setMaximumHeight(28)
            g.content.addWidget(self.mirror_about)
            self.picks_changed()

        def _fillet_options(self):
            g = self.group("Entities to Fillet")
            self.fillet_list = QtWidgets.QListWidget(g.body)
            self.fillet_list.setObjectName("SW3DFilletList")
            self.fillet_list.setMaximumHeight(90)
            g.content.addWidget(self.fillet_list)
            g = self.group("Fillet Parameters")
            self.radius = _spin(g.body, self.tool.radius, lo=0.001)
            self.radius.setObjectName("SW3DFilletRadius")
            self.radius.valueChanged.connect(self.tool.set_radius)
            g.content.addWidget(self.radius)
            for text, attr, obj in (("Keep constrained corners", "keep", "SW3DFilletKeep"),
                                    ("Dimension each fillet", "each", "SW3DFilletEach")):
                c = QtWidgets.QCheckBox(text, g.body)
                c.setObjectName(obj)
                c.setChecked(bool(getattr(self.tool, attr)))
                c.toggled.connect(lambda on, a=attr: setattr(self.tool, a, bool(on)))
                g.content.addWidget(c)
            self.picks_changed()

        def _chamfer_options(self):

            # Distance-distance, Equal distance, Distance 1, Direction 1 Angle, Distance 2)
            g = self.group("Entities to Chamfer")
            self.fillet_list = QtWidgets.QListWidget(g.body)
            self.fillet_list.setObjectName("SW3DChamferList")
            self.fillet_list.setMaximumHeight(90)
            g.content.addWidget(self.fillet_list)
            g = self.group("Chamfer Parameters")
            self.chamfer_modes = {}
            for text in ("Angle-distance", "Distance-distance"):
                r = QtWidgets.QRadioButton(text, g.body)
                r.setObjectName("SW3DChamfer" + text.replace("-", "").title().replace(" ", ""))
                r.setChecked(text == self.tool.mode)
                r.toggled.connect(lambda on, m=text: on and self._chamfer_mode(m))
                g.content.addWidget(r)
                self.chamfer_modes[text] = r
            self.chamfer_equal = QtWidgets.QCheckBox("Equal distance", g.body)
            self.chamfer_equal.setObjectName("SW3DChamferEqual")
            self.chamfer_equal.setChecked(self.tool.equal)
            self.chamfer_equal.toggled.connect(lambda on: (self.tool.set_value("equal", bool(on)),
                                                           self._chamfer_mode(self.tool.mode)))
            g.content.addWidget(self.chamfer_equal)
            self.chamfer_boxes = {}
            for attr, tip, angle in (("d1", "Distance 1", False), ("angle", "Direction 1 Angle", True),
                                     ("d2", "Distance 2", False)):
                box = _spin(g.body, getattr(self.tool, attr), lo=0.001, hi=179.0 if angle else 1e7, angle=angle)
                box.setObjectName("SW3DChamfer" + tip.replace(" ", ""))
                box.setToolTip(tip)
                box.valueChanged.connect(lambda v, a=attr: self.tool.set_value(a, float(v)))
                g.content.addWidget(box)
                self.chamfer_boxes[attr] = box
            self._chamfer_mode(self.tool.mode)
            self.picks_changed()

        def _segment_options(self):

            # Instances)
            g = self.group("Segment Parameters")
            self.segment_list = QtWidgets.QListWidget(g.body)
            self.segment_list.setObjectName("SW3DSegmentList")
            self.segment_list.setMaximumHeight(40)
            g.content.addWidget(self.segment_list)
            for text, mode in (("Sketch points", "points"), ("Sketch segments", "segments")):
                r = QtWidgets.QRadioButton(text, g.body)
                r.setObjectName("SW3DSegment" + mode.title())
                r.setChecked(self.tool.mode == mode)
                r.toggled.connect(lambda on, m=mode: on and self.tool.set_value("mode", m))
                g.content.addWidget(r)
            n = QtWidgets.QSpinBox(g.body)
            n.setObjectName("SW3DSegmentCount")
            n.setToolTip("Number of Instances")
            n.setRange(2, 1000)
            n.setValue(int(self.tool.count))
            n.valueChanged.connect(lambda v: self.tool.set_value("count", int(v)))
            g.content.addWidget(n)
            self.picks_changed()

        def _fit_spline_options(self):

            # spline), Tolerance
            g = self.group("Parameters")
            self.fit_delete = QtWidgets.QCheckBox("Delete geometry", g.body)
            self.fit_delete.setObjectName("SW3DFitDelete")
            self.fit_delete.setChecked(self.tool.delete)
            self.fit_delete.toggled.connect(lambda on: self.tool.set_value("delete", bool(on)))
            g.content.addWidget(self.fit_delete)
            for text in ("Constrained", "Unconstrained", "Fixed"):
                r = QtWidgets.QRadioButton(text, g.body)
                r.setObjectName("SW3DFit" + text)
                r.setChecked(self.tool.how == text)
                r.toggled.connect(lambda on, h=text: on and self._fit_how(h))
                g.content.addWidget(r)
            c = QtWidgets.QCheckBox("Closed spline", g.body)
            c.setObjectName("SW3DFitClosed")
            c.setChecked(self.tool.closed)
            c.toggled.connect(lambda on: self.tool.set_value("closed", bool(on)))
            g.content.addWidget(c)
            g = self.group("Tolerance")
            tol = _spin(g.body, self.tool.tolerance, lo=0.0)
            tol.setDecimals(4)
            tol.setObjectName("SW3DFitTolerance")
            tol.setToolTip("Tolerance")
            tol.valueChanged.connect(lambda v: self.tool.set_value("tolerance", float(v)))
            g.content.addWidget(tol)
            self._fit_how(self.tool.how)

        def _fit_how(self, how):
            self.tool.set_value("how", how)
            # Constrained keeps the picked geometry (as construction) for the spline to stay on
            self.fit_delete.setEnabled(how != "Constrained")

        def _simplify_options(self):

            g = self.group("Simplify Spline")
            self.simplify_count = QtWidgets.QLabel("", g.body)
            self.simplify_count.setObjectName("SW3DSimplifyPoints")
            g.content.addWidget(self.simplify_count)
            tol = _spin(g.body, self.tool.tolerance, lo=0.0001)
            tol.setDecimals(4)
            tol.setObjectName("SW3DSimplifyTolerance")
            tol.setToolTip("Tolerance")
            tol.valueChanged.connect(lambda v: (self.tool.set_value("tolerance", float(v)), self.picks_changed()))
            g.content.addWidget(tol)
            self.picks_changed()

        def _replace_options(self):
            # as the 2D Replace Entity page: Entity to replace, Replace with, Make construction
            g = self.group("Replace Entity")
            boxes = {}
            for which, label, name, tip in (("old", "Entity to replace", "SW3DReplaceOld", "The sketch entity to replace"),
                                            ("new", "Replace with", "SW3DReplaceNew",
                                             "The sketch entity that takes its place")):
                g.content.addWidget(QtWidgets.QLabel(label, g.body))
                box = QtWidgets.QListWidget(g.body)
                box.setObjectName(name)
                box.setFixedHeight(26)
                box.setToolTip(tip)
                box.installEventFilter(self)
                g.content.addWidget(box)
                boxes[which] = box
            self.replace_boxes = boxes
            c = QtWidgets.QCheckBox("Make construction", g.body)
            c.setObjectName("SW3DReplaceConstruction")
            c.setToolTip("Keep the replaced entity as construction geometry instead of deleting it")
            c.toggled.connect(lambda on: setattr(self.tool, "make_construction", bool(on)))
            g.content.addWidget(c)
            self.picks_changed()

        def _route_options(self):
            g = self.group("Route Line")
            self.route_ends = QtWidgets.QListWidget(g.body)
            self.route_ends.setObjectName("SW3DRouteEnds")
            self.route_ends.setFixedHeight(44)
            g.content.addWidget(self.route_ends)
            alt = QtWidgets.QPushButton("Alternate Path", g.body)
            alt.setObjectName("SW3DRouteAlternate")
            alt.clicked.connect(lambda: self.tool.alternate())
            g.content.addWidget(alt)
            self.picks_changed()

        def _jog_options(self):
            g = self.group("Jog")
            self.jog_line = QtWidgets.QListWidget(g.body)
            self.jog_line.setObjectName("SW3DJogLine")
            self.jog_line.setFixedHeight(26)
            g.content.addWidget(self.jog_line)
            form = QtWidgets.QFormLayout()
            for attr, name, label in (("width", "SW3DJogWidth", "Width:"), ("depth", "SW3DJogDepth", "Depth:")):
                box = _spin(g.body, getattr(self.tool, attr), lo=0.001)
                box.setObjectName(name)
                box.valueChanged.connect(lambda v, a=attr: self.tool.set_value(a, float(v)))
                form.addRow(label, box)
            g.content.addLayout(form)
            flip = QtWidgets.QCheckBox("Flip side", g.body)
            flip.setObjectName("SW3DJogFlip")
            flip.toggled.connect(lambda on: self.tool.set_value("flip", bool(on)))
            g.content.addWidget(flip)
            self.picks_changed()

        def _chamfer_mode(self, mode):
            self.tool.set_value("mode", mode)
            angled = mode == "Angle-distance"
            self.chamfer_equal.setVisible(not angled)
            self.chamfer_boxes["angle"].setVisible(angled)
            self.chamfer_boxes["d2"].setVisible(not angled and not self.tool.equal)

        def _move_options(self):
            g = self.group("Entities to %s" % self.tool.VERB)
            self.move_list = QtWidgets.QListWidget(g.body)
            self.move_list.setObjectName("SW3DMoveEntities")
            self.move_list.setMaximumHeight(90)
            g.content.addWidget(self.move_list)
            keep = QtWidgets.QCheckBox("Keep relations", g.body)
            keep.setObjectName("SW3DMoveKeep")
            keep.setChecked(bool(self.tool.keep))
            keep.toggled.connect(lambda on: setattr(self.tool, "keep", bool(on)))
            g.content.addWidget(keep)
            g = self.group("Parameters")
            self.move_modes = {}
            for name, obj in (("From/To", "SW3DMoveFromTo"), ("X/Y/Z", "SW3DMoveXYZ")):
                r = QtWidgets.QRadioButton(name, g.body)
                r.setObjectName(obj)
                r.setChecked(name == self.tool.mode)
                r.clicked.connect(lambda checked=False, n=name: self._move_mode(n))
                g.content.addWidget(r)
                self.move_modes[name] = r
            self.move_start = QtWidgets.QLabel("", g.body)
            self.move_start.setObjectName("SW3DMoveStart")
            g.content.addWidget(self.move_start)
            self.move_spins = []
            for axis, v in zip("XYZ", self.tool.delta):
                row = QtWidgets.QHBoxLayout()
                row.addWidget(QtWidgets.QLabel("\u0394" + axis, g.body))
                w = _spin(g.body, v)
                w.setObjectName("SW3DMoveD" + axis)
                w.valueChanged.connect(lambda val, i="XYZ".index(axis): self.tool.delta.__setitem__(i, float(val)))
                row.addWidget(w, 1)
                g.content.addLayout(row)
                self.move_spins.append(w)
            self.move_repeat = QtWidgets.QPushButton("Repeat", g.body)
            self.move_repeat.setObjectName("SW3DMoveRepeat")
            self.move_repeat.clicked.connect(self._move_again)
            g.content.addWidget(self.move_repeat)
            self._move_mode(self.tool.mode)

        def _rotate_options(self):

            t = self.tool
            g = self.group("Entities to Rotate")
            self.move_list = QtWidgets.QListWidget(g.body)
            self.move_list.setObjectName("SW3DMoveEntities")
            self.move_list.setMaximumHeight(90)
            self.move_list.setToolTip("Entities to Rotate")
            self.move_list.installEventFilter(self)
            g.content.addWidget(self.move_list)
            keep = QtWidgets.QCheckBox("Keep relations", g.body)
            keep.setObjectName("SW3DMoveKeep")
            keep.setChecked(bool(t.keep))
            keep.toggled.connect(lambda on: setattr(self.tool, "keep", bool(on)))
            g.content.addWidget(keep)
            g = self.group("Rotate")
            self.rotate_ref = QtWidgets.QListWidget(g.body)
            self.rotate_ref.setObjectName("SW3DRotateReference")
            self.rotate_ref.setToolTip("Rotation Reference (Linear Entity)")
            self.rotate_ref.setMaximumHeight(26)
            self.rotate_ref.installEventFilter(self)
            g.content.addWidget(self.rotate_ref)
            self.rotate_angle = _spin(g.body, t.angle, lo=-360.0, hi=360.0, angle=True)
            self.rotate_angle.setObjectName("SW3DRotateAngle")
            self.rotate_angle.setToolTip("Angle")
            self.rotate_angle.valueChanged.connect(self._rotate_angle)
            g.content.addWidget(self.rotate_angle)
            self.picks_changed()

        def _rotate_angle(self, val):
            self.tool.angle = float(val)
            self.tool.draw(None)

        def _rotate_box(self, which):
            ""
            self.tool.active = which
            self.picks_changed()

        def _move_again(self):
            why = self.tool.repeat()
            if isinstance(why, str):
                self.show_note(why, warning=True)

        def _move_mode(self, name):
            self.tool.mode = name
            self.tool.base = None
            for n, r in self.move_modes.items():
                r.setChecked(n == name)
            for w in self.move_spins:
                w.setEnabled(name == "X/Y/Z")
            self.move_repeat.setEnabled(name == "X/Y/Z")
            self.picks_changed()

        def _plane_references(self):
            ""


            from . import sketch3d as K
            self.plane_refs, self.plane_buttons, self.plane_values, self.plane_flips = [], [], [], []
            for n, title in enumerate(REFERENCES):
                g = self.group(title)
                w = QtWidgets.QListWidget(g.body)
                w.setObjectName("SW3DPlane" + title.replace(" ", ""))
                w.setMaximumHeight(28)
                g.content.addWidget(w)
                self.plane_refs.append(w)
                buttons = self.toggles(g, list(K.PLANE_RELATIONS["M"]), _relation_icon, lambda k: False)
                for key, b in buttons.items():
                    b.setObjectName("SW3DPlane%s%s" % (title.split()[0], key))
                    b.clicked.connect(lambda checked=False, n=n, key=key: self._plane_relation(n, key))
                self.plane_buttons.append(buttons)
                row = QtWidgets.QHBoxLayout()
                value = _spin(g.body, 10.0, lo=0.0)
                value.setObjectName("SW3DPlane%sValue" % title.split()[0])
                value.editingFinished.connect(lambda n=n: self._plane_value(n))
                flip = QtWidgets.QCheckBox("Flip", g.body)
                flip.setObjectName("SW3DPlane%sFlip" % title.split()[0])
                flip.toggled.connect(lambda on, n=n: self._plane_value(n))
                row.addWidget(value, 1)
                row.addWidget(flip)
                g.content.addLayout(row)
                self.plane_values.append(value)
                self.plane_flips.append(flip)
            self.picks_changed()

        def _plane_relation(self, n, key):
            how = self.tool.how[n] if n < len(self.tool.how) else None
            value = None
            if key in ("Distance", "Angle"):
                value = self.plane_values[n].value() if how is not None and how[0] == key else \
                    (10.0 if key == "Distance" else 45.0)
            self.tool.set_relation(n, key, value, self.plane_flips[n].isChecked())
            self.picks_changed()

        def _plane_value(self, n):
            if n >= len(self.tool.how) or self.tool.how[n] is None or self.tool.how[n][0] not in ("Distance", "Angle"):
                return
            self.tool.set_relation(n, self.tool.how[n][0], self.plane_values[n].value(), self.plane_flips[n].isChecked())
            self.picks_changed()

        def picks_changed(self):
            title = self.tool.title()
            if title == "Segment":
                self.segment_list.clear()
                if self.tool.target is not None and self.tool.target < len(self.s.ents):
                    self.segment_list.addItem(entity_name(self.s, ("E", self.tool.target)))
                return
            if title == "Simplify Spline":
                n_now = self.tool.points_now()
                n_new = len(self.tool.preview())
                self.simplify_count.setText("Points: %d, simplified: %d" % (n_now, n_new) if n_now else
                                            "Pick a spline")
                return
            if title == "Replace Entity":
                for which, box in self.replace_boxes.items():
                    box.clear()
                    k = getattr(self.tool, which)
                    if k is not None and k < len(self.s.ents):
                        box.addItem(entity_name(self.s, ("E", k)))
                    box.setStyleSheet("QListWidget { background: rgb(255,205,225); }" if self.tool.active == which
                                      else "")
                return
            if title == "Route Line":
                self.route_ends.clear()
                for n, sn in enumerate(self.tool.ends):
                    self.route_ends.addItem("%s: %s" % ("Start" if n == 0 else "End",
                                                        ", ".join(_fmt3(v) for v in sn.pos)))
                if len(self.tool.ends) < 2:
                    self.route_ends.addItem("Click the %s point" % ("start" if not self.tool.ends else "end"))
                return
            if title == "Jog Line":
                self.jog_line.clear()
                self.jog_line.addItem(entity_name(self.s, ("E", self.tool.line)) if self.tool.line is not None
                                      else "Click the line where the jog goes")
                return
            if title in ("Sketch Fillet", "Sketch Chamfer"):
                self.fillet_list.clear()
                for p in self.tool.corners:
                    self.fillet_list.addItem(entity_name(self.s, ("P", p)))
                return
            if title == "Rotate":
                self.move_list.clear()
                for i in self.tool.items:
                    if i < len(self.s.ents):
                        self.move_list.addItem(entity_name(self.s, ("E", i)))
                self.rotate_ref.clear()
                if self.tool.axis is not None:
                    self.rotate_ref.addItem(self.tool.axis[2])
                pink = "background: rgb(255, 205, 225);"
                self.move_list.setStyleSheet(pink if self.tool.active == "entities" else "")
                self.rotate_ref.setStyleSheet(pink if self.tool.active == "reference" else "")
                return
            if title in ("Move", "Copy"):
                self.move_list.clear()
                for i in self.tool.items:
                    if i < len(self.s.ents):
                        self.move_list.addItem(entity_name(self.s, ("E", i)))
                if self.tool.mode != "From/To":
                    self.move_start.setText("")
                elif self.tool.base is None:
                    self.move_start.setText("Start point: click it")
                else:
                    self.move_start.setText("Start point: %s, %s, %s" % tuple(_fmt(v) for v in self.tool.base))
                return
            if title == "Plane":
                from . import sketch3d as K
                refs, how = list(self.tool.refs), list(self.tool.how)
                for n, w in enumerate(self.plane_refs):
                    ref = refs[n] if n < len(refs) else None
                    rel = how[n] if n < len(how) and how[n] is not None else None
                    w.clear()
                    if ref is not None:
                        if ref[0] == "P":
                            w.addItem(entity_name(self.s, ref))
                        elif ref[0] == "L":
                            w.addItem(entity_name(self.s, ("E", ref[1])))
                        else:
                            name, sub = ref[1]
                            w.addItem(_label(self.s.doc, name) + ("" if sub in ("", "-") else " " + sub))
                    takes = K.PLANE_RELATIONS[ref[0]] if ref is not None else ()
                    for key, b in self.plane_buttons[n].items():
                        b.setVisible(key in takes)
                        b.setChecked(rel is not None and rel[0] == key)
                    valued = rel is not None and rel[0] in ("Distance", "Angle")
                    box, flip = self.plane_values[n], self.plane_flips[n]
                    box.setVisible(valued)
                    flip.setVisible(valued)
                    if valued:
                        box.blockSignals(True)
                        flip.blockSignals(True)
                        angle = rel[0] == "Angle"
                        box.setSuffix("°" if angle else " mm")
                        box.setRange(0.0, 180.0 if angle else 1e7)
                        box.setValue(float(rel[1] if rel[1] is not None else (45.0 if angle else 10.0)))
                        flip.setChecked(bool(rel[2]))
                        box.blockSignals(False)
                        flip.blockSignals(False)
                return
            if self.tool.title() in ("Intersection Curve", "Face Curves", "Offset on Surface"):
                self.picks.clear()
                for name, sub in self.tool.picks:
                    self.picks.addItem(_label(self.s.doc, name) + ("" if sub in ("", "-") else " " + sub))
            elif self.tool.title() == "Convert Entities":
                self.picks.clear()
                for name, sub in self.tool.picks:
                    self.picks.addItem("%s of %s" % (sub, _label(self.s.doc, name)))
            elif self.tool.title() == "Mirror":
                self.mirror_items.clear()
                for i in self.tool.items:
                    if i < len(self.s.ents):
                        self.mirror_items.addItem(entity_name(self.s, ("E", i)))
                self.mirror_about.clear()
                if self.tool.about is not None:
                    name, sub = self.tool.about
                    self.mirror_about.addItem(_label(self.s.doc, name) + ("" if sub in ("", "-") else " " + sub))

        def update_message(self):
            text = MESSAGES.get("Line" if self.tool.title() == "Centerline" else self.tool.title(), "")
            if self.tool.title() == "Trim Entities":
                text = MESSAGES["Trim Entities"] + "\n\nNow: %s." % self.tool.mode
            if self.s.on_custom() or self.s.on_sketch_plane() is not None:
                where = "%s (each point gets On Plane)" % self.s.plane
            else:
                where = "the %s plane through the last point" % self.s.plane
            self.message.setText(text % {"plane": where} if "%(" in text else text)

        def _construction(self, on):
            self.tool.construction = bool(on)

        def eventFilter(self, obj, event):
            if not isinstance(event, QtCore.QEvent):
                return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
            # 3D Rotate: a click in Entities to Rotate or Rotation Reference makes it the box the next pick fills
            try:
                if event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.FocusIn) and \
                        self.tool.title() == "Rotate":
                    if obj is getattr(self, "rotate_ref", None):
                        self._rotate_box("reference")
                    elif obj is getattr(self, "move_list", None):
                        self._rotate_box("entities")
                if event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.FocusIn) and \
                        self.tool.title() == "Replace Entity":
                    for which, box in getattr(self, "replace_boxes", {}).items():
                        if obj is box:
                            self.tool.active = which
                            self.picks_changed()
            except Exception as _fw_err:
                _fw_log("sketch3dpm.py:1305", _fw_err)
            return False

        def accept(self):
            if hasattr(self.tool, "apply"):
                why = self.tool.apply()
                if isinstance(why, str):
                    self.show_note(why, warning=True)
                    return
            self.tool.end()

        def reject(self):
            self.tool.end()

    return ToolPage3D()


def _start(sketch3d, key, construction):
    tool = sketch3d.start_tool(key)
    if tool is not None and construction:
        tool.construction = True
        page = _host.page
        box = page.findChild(QtWidgets.QCheckBox, "SW3DSketchConstruction") if page is not None else None
        if box is not None:
            box.setChecked(True)


def make_properties_page(session):
    Base = _base()
    items = list(session.selection)

    class PropertiesPage3D(Base):
        PIXMAP = "Sketcher_CreateLine"

        def __init__(self):
            self.s = session
            self.items = items
            kinds = {k for k, _ in items}
            ents = [session.ents[i].kind for k, i in items if k == "E"]
            if len(items) == 1 and kinds == {"P"}:
                type(self).TITLE = "Point Properties"
                type(self).ICON = "SKETCH_POINT"
            elif len(items) == 1 and ents == ["L"]:
                type(self).TITLE = "Line Properties"
                type(self).ICON = "SKETCH_LINE"
            elif len(items) == 1 and ents == ["S"]:
                type(self).TITLE = "Spline Properties"
                type(self).ICON = "SKETCH_SPLINE"
            elif len(items) == 1 and ents == ["C"]:
                type(self).TITLE = "Circle"
                type(self).ICON = "SKETCH_CIRCLE"
            elif len(items) == 1 and ents == ["A"]:
                type(self).TITLE = "Arc"
                type(self).ICON = "SKETCH_CPRPT_ARC"
            elif len(items) == 1 and ents == ["Q"]:
                type(self).TITLE = "Sketch Plane"
                type(self).ICON = "REFGEO_PLANE"
            elif len(items) == 1 and kinds == {"R"}:
                type(self).TITLE = "Dimension"
                type(self).ICON = "LAYOUT_SMART_DIM"
            else:
                type(self).TITLE = "Properties"
                type(self).ICON = "LAYOUT_ADD_RELATION"
            super().__init__(session.obj)

        # ---- groups
        def build(self):
            s = self.s
            if len(self.items) > 1:
                g = self.group("Selected Entities")
                box = QtWidgets.QListWidget(g.body)
                box.setObjectName("SW3DSelectedEntities")
                for it in self.items:
                    box.addItem(entity_name(s, it))
                box.setMaximumHeight(90)
                g.content.addWidget(box)
            self._existing()
            self._add()
            if len(self.items) == 1 and self.items[0][0] == "E" and s.ents[self.items[0][1]].kind not in ("P", "Q"):
                o = self.group("Options")
                c = QtWidgets.QCheckBox("For construction", o.body)
                c.setObjectName("SW3DSketchConstruction")
                c.setChecked(s.ents[self.items[0][1]].construction)
                c.toggled.connect(lambda on, e=self.items[0][1]: s.set_construction(e, on))
                o.content.addWidget(c)
                if s.ents[self.items[0][1]].kind == "L":
                    inf = QtWidgets.QCheckBox("Infinite length", o.body)
                    inf.setObjectName("SW3DLineInfinite")
                    inf.setEnabled(False)
                    inf.setToolTip("Infinite lines are 2D sketch geometry")
                    o.content.addWidget(inf)
                if s.ents[self.items[0][1]].kind == "S":
                    k = self.items[0][1]
                    comb = QtWidgets.QCheckBox("Show Curvature", o.body)
                    comb.setObjectName("SW3DSplineCurvature")
                    comb.setChecked(k in s.curvature)
                    comb.toggled.connect(lambda on, k=k: s.set_curvature(k, on))
                    o.content.addWidget(comb)
                    keep = QtWidgets.QCheckBox("Maintain Internal Continuity", o.body)
                    keep.setObjectName("SW3DSplineContinuity")
                    from . import sketch3d as K
                    keep.setChecked(K.spline_continuity(s.ents[k], s.rels))
                    keep.setToolTip("On: when a handle is set, the free points' handles follow so the curvature "
                                    "has no break. Off: they stay as they are.")
                    keep.toggled.connect(lambda on, k=k: QtCore.QTimer.singleShot(
                        0, lambda: self.s.set_continuity(k, bool(on))))
                    o.content.addWidget(keep)
            self._parameters()

        def _existing(self):
            s = self.s
            g = self.group("Existing Relations")
            self.relations = QtWidgets.QListWidget(g.body)
            self.relations.setObjectName("SW3DExistingRelations")
            self.relations.setMaximumHeight(110)
            self.relations.setContextMenuPolicy(Qt.CustomContextMenu)
            self.relations.customContextMenuRequested.connect(self._relation_menu)
            self.relations.installEventFilter(self)
            shown = []
            for it in self.items:
                for k in s.relations_of(it):
                    if k not in shown and (s.rels[k].kind not in S.DIMENSIONS or it[0] == "R"):
                        shown.append(k)
            self.shown = shown
            for k in shown:
                item = QtWidgets.QListWidgetItem(relation_icon(s.rels[k].kind), relation_text(s, k))
                item.setData(Qt.UserRole, k)
                self.relations.addItem(item)
            g.content.addWidget(self.relations)
            pts = set()
            for k, i in self.items:
                pts.update([i] if k == "P" else s.ents[i].points if k == "E" else s.rels[i].points)
            self.state = QtWidgets.QLabel("Fully Defined" if pts and pts <= s.fixed else "Under Defined", g.body)
            self.state.setObjectName("SW3DSketchState")
            g.content.addWidget(self.state)

        def eventFilter(self, obj, event):
            if not isinstance(event, QtCore.QEvent):
                return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
            try:
                if obj is self.relations and event.type() == QtCore.QEvent.KeyPress \
                        and event.key() == Qt.Key_Delete:
                    self._delete_relation()
                    return True
            except Exception as _fw_err:
                _fw_log("sketch3dpm.py:1450", _fw_err)
            return False

        def _relation_menu(self, pos):
            menu = QtWidgets.QMenu(self)
            menu.addAction("Delete").triggered.connect(self._delete_relation)
            menu.exec_(self.relations.mapToGlobal(pos)) if hasattr(menu, "exec_") else menu.exec(
                self.relations.mapToGlobal(pos))

        def _delete_relation(self):
            item = self.relations.currentItem()
            if item is None:
                return
            QtCore.QTimer.singleShot(0, lambda k=item.data(Qt.UserRole): self.s.delete_relation(k))

        def _add(self):
            choices = addable(self.s, self.items)
            if not choices:
                return
            g = self.group("Add Relations")
            for kind, label, rel in choices:
                b = QtWidgets.QToolButton(g.body)
                b.setObjectName("SW3DAdd" + kind)
                b.setText(label)
                b.setIcon(relation_icon(kind))
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                b.setAutoRaise(True)
                b.setIconSize(QtCore.QSize(16, 16))
                b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                b.clicked.connect(lambda checked=False, r=rel: self._add_relation(r))
                g.content.addWidget(b)

        def _add_relation(self, rel):
            if rel == "merge":
                why = merge(self.s, self.items)
            elif isinstance(rel, _FixAll):
                free = [p for p in rel.points if p not in self.s.fixed]
                why = self.s.add_relation([S.Relation("Fix", [p], list(self.s.pts[p])) for p in free]) if free \
                    else "It is fixed already."
            else:
                why = self.s.add_relation(rel)
                if not why and isinstance(rel, list):
                    Gui.Selection.clearSelection()       # the model pick was for the relation
            if why:
                self.show_note(why, warning=True)

        def _parameters(self):
            s = self.s
            if len(self.items) != 1:
                return
            kind, i = self.items[0]
            if kind == "P":
                g = self.group("Parameters")
                form = QtWidgets.QFormLayout()
                p = s.pts[i]
                self.coords = []
                for axis, value in zip("XYZ", p):
                    w = _spin(g.body, value)
                    w.setObjectName("SW3DPoint" + axis)
                    w.editingFinished.connect(self._point_typed)
                    form.addRow(axis, w)
                    self.coords.append(w)
                g.content.addLayout(form)
            elif kind == "E" and s.ents[i].kind == "L":

                g = self.group("Parameters")
                ia, ib = s.ents[i].points
                a, b = s.pts[ia], s.pts[ib]
                d = [b[c] - a[c] for c in range(3)]
                form = QtWidgets.QFormLayout()
                from . import sketch3d as K
                self.length = _spin(g.body, K.measured_length(s.pts, s.ents, i), 0.0)
                self.length.setObjectName("SW3DLineLength")
                self.length.editingFinished.connect(self._length_typed)
                form.addRow("Length", self.length)
                g.content.addLayout(form)
                g = self.group("Additional Parameters")
                form = QtWidgets.QFormLayout()
                self.ends = {}
                for word, idx, p in (("Start", ia, a), ("End", ib, b)):
                    for axis, v in zip("XYZ", p):
                        w = _spin(g.body, v)
                        w.setObjectName("SW3DLine%s%s" % (word, axis))
                        w.editingFinished.connect(lambda idx=idx, word=word: self._end_typed(word, idx))
                        form.addRow("%s %s" % (word, axis), w)
                        self.ends[(word, axis)] = w
                self.deltas = []
                for axis, v in zip("XYZ", d):
                    w = _spin(g.body, v)
                    w.setObjectName("SW3DLineDelta" + axis)
                    w.editingFinished.connect(self._delta_typed)
                    form.addRow("Delta " + axis, w)
                    self.deltas.append(w)
                g.content.addLayout(form)

                g.body.setVisible(False)
                g._update_fold()
                self.line_more = g
            elif kind == "E" and s.ents[i].kind in ("C", "A"):

                g = self.group("Parameters")
                ent = s.ents[i]
                form = QtWidgets.QFormLayout()
                self.round_xyz = {}
                words = (("Center", 0), ("Start", 1), ("End", 2)) if ent.kind == "A" else (("Center", 0),)
                for word, k in words:
                    for axis, v in zip("XYZ", s.pts[ent.points[k]]):
                        w = _spin(g.body, v)
                        w.setObjectName("SW3DArc%s%s" % (word, axis))
                        w.editingFinished.connect(lambda word=word: self._round_typed(word))
                        form.addRow("%s %s" % (word, axis), w)
                        self.round_xyz[(word, axis)] = w
                c, a = (s.pts[k] for k in ent.points[:2])
                self.radius = _spin(g.body, sum((a[k] - c[k]) ** 2 for k in range(3)) ** 0.5, 0.0)
                self.radius.setObjectName("SW3DArcRadius")
                self.radius.editingFinished.connect(self._radius_typed)
                form.addRow("Radius", self.radius)
                if ent.kind == "A":
                    from . import sketch3d as K
                    sweep = K.arc_sweep(c, a, s.pts[ent.points[2]], K.arc_normal(ent, s.rels))
                    self.sweep = _spin(g.body, sweep * 57.29577951308232, 0.0, angle=True)
                    self.sweep.setRange(0.01, 359.99)
                    self.sweep.setObjectName("SW3DArcAngle")
                    self.sweep.editingFinished.connect(self._sweep_typed)
                    form.addRow("Angle", self.sweep)
                g.content.addLayout(form)
            elif kind == "E" and s.ents[i].kind == "S":

                g = self.group("Parameters")
                ent = s.ents[i]
                form = QtWidgets.QFormLayout()
                self.spline_no = QtWidgets.QSpinBox(g.body)
                self.spline_no.setObjectName("SW3DSplinePoint")
                closed = len(ent.points) > 3 and ent.points[0] == ent.points[-1]
                self.spline_no.setRange(1, len(ent.points) - (1 if closed else 0))
                self.spline_no.valueChanged.connect(self._spline_point_shown)
                form.addRow("Spline Point Number", self.spline_no)
                self.spline_xyz = []
                for axis in "XYZ":
                    w = _spin(g.body, 0.0)
                    w.setObjectName("SW3DSplinePoint" + axis)
                    w.editingFinished.connect(self._spline_point_typed)
                    form.addRow(axis + " Coordinate", w)
                    self.spline_xyz.append(w)
                g.content.addLayout(form)

                form = QtWidgets.QFormLayout()
                self.handle_weight = QtWidgets.QDoubleSpinBox(g.body)
                self.handle_weight.setObjectName("SW3DSplineTangentWeight")
                self.handle_weight.setRange(0.05, 100.0)
                self.handle_weight.setDecimals(3)
                self.handle_weight.setKeyboardTracking(False)
                self.handle_weight.editingFinished.connect(self._handle_typed)
                form.addRow("Tangent Weighting 1", self.handle_weight)

                self.handle_weight2 = QtWidgets.QDoubleSpinBox(g.body)
                self.handle_weight2.setObjectName("SW3DSplineTangentWeight2")
                self.handle_weight2.setRange(0.05, 100.0)
                self.handle_weight2.setDecimals(3)
                self.handle_weight2.setKeyboardTracking(False)
                self.handle_weight2.editingFinished.connect(self._handle_typed)
                form.addRow("Tangent Weighting 2", self.handle_weight2)
                self.handle_radial = _spin(g.body, 0.0, lo=-360.0, hi=360.0, angle=True)
                self.handle_radial.setObjectName("SW3DSplineTangentRadial")
                self.handle_radial.editingFinished.connect(self._handle_typed)
                form.addRow("Tangent Radial Direction", self.handle_radial)
                self.handle_polar = _spin(g.body, 0.0, lo=0.0, hi=180.0, angle=True)
                self.handle_polar.setObjectName("SW3DSplineTangentPolar")
                self.handle_polar.editingFinished.connect(self._handle_typed)
                form.addRow("Tangent Polar direction", self.handle_polar)
                g.content.addLayout(form)
                self.tangent_driving = QtWidgets.QCheckBox("Tangent Driving", g.body)
                self.tangent_driving.setObjectName("SW3DSplineTangentDriving")
                self.tangent_driving.toggled.connect(self._tangent_driving)
                g.content.addWidget(self.tangent_driving)
                for text, obj, slot in (("Reset This Handle", "SW3DSplineResetHandle", self._reset_handle),
                                        ("Reset All Handles", "SW3DSplineResetAll", self._reset_all),
                                        ("Relax Spline", "SW3DSplineRelax", self._relax)):
                    b = QtWidgets.QPushButton(text, g.body)
                    b.setObjectName(obj)
                    b.clicked.connect(slot)
                    g.content.addWidget(b)
                self._spline_point_shown(1)
            elif kind == "R" and s.rels[i].kind in S.DIMENSIONS:
                g = self.group("Primary Value")
                self.value = _spin(g.body, s.rels[i].values[0], 0.0, angle=s.rels[i].kind in S.ANGLES)
                self.value.setObjectName("SW3DDimensionValue")
                self.value.editingFinished.connect(self._value_typed)
                g.content.addWidget(self.value)

        def _point_typed(self):
            target = [w.value() for w in self.coords]
            i = self.items[0][1]
            if max(abs(a - b) for a, b in zip(target, self.s.pts[i])) < 1e-7:
                return
            why = self.s.move_point(i, target)
            if why:
                self.show_note(why, warning=True)

        def _end_typed(self, word, idx):
            target = [self.ends[(word, a)].value() for a in "XYZ"]
            if max(abs(a - b) for a, b in zip(target, self.s.pts[idx])) < 1e-7:
                return
            why = self.s.move_point(idx, target)
            if why:
                self.show_note(why, warning=True)

        def _delta_typed(self):
            ia, ib = self.s.ents[self.items[0][1]].points
            a = self.s.pts[ia]
            target = [a[k] + self.deltas[k].value() for k in range(3)]
            if max(abs(x - y) for x, y in zip(target, self.s.pts[ib])) < 1e-7:
                return
            why = self.s.move_points({ia: a, ib: target})
            if why:
                self.show_note(why, warning=True)

        def _round_typed(self, word):
            s = self.s
            ent = s.ents[self.items[0][1]]
            k = {"Center": 0, "Start": 1, "End": 2}[word]
            target = [self.round_xyz[(word, a)].value() for a in "XYZ"]
            now = s.pts[ent.points[k]]
            if max(abs(x - y) for x, y in zip(target, now)) < 1e-7:
                return
            if word == "Center":

                d = [t - n for t, n in zip(target, now)]
                why = s.move_points({i: [s.pts[i][c] + d[c] for c in range(3)] for i in dict.fromkeys(ent.points)})
            else:
                why = s.move_point(ent.points[k], target)
            if why:
                self.show_note(why, warning=True)

        def _sweep_typed(self):
            import math
            from . import sketch3d as K
            s = self.s
            ent = s.ents[self.items[0][1]]
            c, a, b = (s.pts[k] for k in ent.points)
            n = K.arc_normal(ent, s.rels)
            ang = math.radians(self.sweep.value())
            if abs(ang - K.arc_sweep(c, a, b, n)) < 1e-9:
                return
            u = K._sub(a, c)
            v = K._cross(n, u)
            end = K._add(c, K._add(K._mul(u, math.cos(ang)), K._mul(v, math.sin(ang))))
            why = s.move_point(ent.points[2], end)
            if why:
                self.show_note(why, warning=True)

        def _spline_point_shown(self, no):
            ent = self.s.ents[self.items[0][1]]
            p = self.s.pts[ent.points[no - 1]]
            for w, v in zip(self.spline_xyz, p):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
            tied = self._tangent_relation(no)
            _, _, own = self._handle_now(no)
            self.tangent_driving.blockSignals(True)
            self.tangent_driving.setChecked(tied is not None or own)
            self.tangent_driving.setEnabled(True)
            self.tangent_driving.setToolTip("The tangent at this point is held (its handle, or a Tangent relation)")
            self.tangent_driving.blockSignals(False)
            self._show_handle(no)

        def _tangent_relation(self, no):
            ent = self.s.ents[self.items[0][1]]
            p = ent.points
            if no not in (1, len(p)):
                return None
            e, n = (p[0], p[1]) if no == 1 else (p[-1], p[-2])
            return next((k for k, r in enumerate(self.s.rels) if r.kind.startswith("SplineTangent")
                         and r.points[:2] == [e, n]), None)

        def _handle_now(self, no):
            """(unit direction, weight, set) of the spline's handle at point no."""
            from . import sketch3d as K
            k = self.items[0][1]
            for e, pos, p, d, w, own, half, back in self.s.handle_lines() or []:
                if e == k and pos == no - 1:
                    return d, w, own
            ent = self.s.ents[k]
            own = K.spline_handles(ent, self.s.rels)
            if no - 1 in own:
                return K._unit(own[no - 1][0]), own[no - 1][1], True
            try:
                c = K.entity_edges(ent, self.s.pts, self.s.rels)[0].Curve
                t = c.tangent(c.parameter(App.Vector(*self.s.pts[ent.points[no - 1]])))[0]
                return K._unit((t.x, t.y, t.z)), 1.0, False
            except Exception:
                return (1.0, 0.0, 0.0), 1.0, False

        def _show_handle(self, no):
            import math
            d, w, own = self._handle_now(no)
            radial = math.degrees(math.atan2(d[1], d[0]))
            polar = math.degrees(math.acos(max(-1.0, min(1.0, d[2]))))
            from . import sketch3d as K
            set_ = K.spline_handles(self.s.ents[self.items[0][1]], self.s.rels).get(no - 1)
            w2 = set_[2] if set_ else w
            for box, v in ((self.handle_weight, w), (self.handle_weight2, w2), (self.handle_radial, radial),
                           (self.handle_polar, polar)):
                box.blockSignals(True)
                box.setValue(v)
                box.setEnabled(bool(own))
                box.blockSignals(False)

        def _handle_typed(self):
            import math
            no = self.spline_no.value()
            d, w, own = self._handle_now(no)
            r, pol = math.radians(self.handle_radial.value()), math.radians(self.handle_polar.value())
            new = (math.sin(pol) * math.cos(r), math.sin(pol) * math.sin(r), math.cos(pol))
            from . import sketch3d as K
            weight, back = self.handle_weight.value(), self.handle_weight2.value()
            was = K.spline_handles(self.s.ents[self.items[0][1]], self.s.rels).get(no - 1)
            if was:
                # a box shows 3 decimals: a weight not typed over keeps its exact value
                if abs(weight - was[1]) < 0.6e-3:
                    weight = was[1]
                if abs(back - was[2]) < 0.6e-3:
                    back = was[2]
            if own and was and abs(weight - was[1]) < 1e-9 and abs(back - was[2]) < 1e-9 \
                    and max(abs(a - b) for a, b in zip(new, d)) < 1e-9:
                return
            QtCore.QTimer.singleShot(0, lambda: self.s.set_handle(self.items[0][1], no - 1, new, weight,
                                                                  back=back))

        def _reset_handle(self):
            no = self.spline_no.value()
            QtCore.QTimer.singleShot(0, lambda: self.s.reset_handles(self.items[0][1], [no - 1]))

        def _reset_all(self):
            QtCore.QTimer.singleShot(0, lambda: self.s.reset_handles(self.items[0][1], name="Reset All Handles"))

        def _relax(self):
            QtCore.QTimer.singleShot(0, lambda: self.s.reset_handles(self.items[0][1], keep_directions=True,
                                                                     name="Relax Spline"))

        def _spline_point_typed(self):
            ent = self.s.ents[self.items[0][1]]
            idx = ent.points[self.spline_no.value() - 1]
            target = [w.value() for w in self.spline_xyz]
            if max(abs(x - y) for x, y in zip(target, self.s.pts[idx])) < 1e-7:
                return
            why = self.s.move_point(idx, target)
            if why:
                self.show_note(why, warning=True)

        def _tangent_driving(self, on):
            no = self.spline_no.value()
            k = self._tangent_relation(no)
            e = self.items[0][1]
            if on:

                d, w, own = self._handle_now(no)
                if not own:
                    QtCore.QTimer.singleShot(0, lambda: self.s.set_handle(e, no - 1, d, w, name="Tangent Driving"))
                return
            if k is not None:
                QtCore.QTimer.singleShot(0, lambda: self.s.delete_relation(k))
            elif self._handle_now(no)[2]:
                QtCore.QTimer.singleShot(0, lambda: self.s.reset_handles(e, [no - 1], name="Tangent Driving"))

        def _length_typed(self):
            e = self.items[0][1]
            why = self.s.set_length(e, self.length.value())
            if why:
                self.show_note(why, warning=True)

        def _radius_typed(self):
            e = self.items[0][1]
            why = self.s.set_radius(e, self.radius.value())
            if why:
                self.show_note(why, warning=True)

        def _value_typed(self):
            why = self.s.set_dimension(self.items[0][1], self.value.value())
            if why:
                self.show_note(why, warning=True)

        def accept(self):
            self.s.select([])

        def reject(self):
            self.s.select([])

    return PropertiesPage3D()


def _fmt3(v):
    return ("%.2f" % v).rstrip("0").rstrip(".") or "0"


# ------------------------------------------------------------------ relations that fit the picks
def addable(s, items):
    ""

    if any(k == "R" for k, _ in items):
        return []
    model = model_picks(s)
    if model:
        return model_addable(s, items, model)
    pts = [i for k, i in items if k == "P"]
    ents = [i for k, i in items if k == "E"]
    lines = [s.ents[i].points[:2] for i in ents if s.ents[i].kind == "L"]
    rounds = [s.ents[i] for i in ents if s.ents[i].kind in ("C", "A")]
    planes = [s.ents[i] for i in ents if s.ents[i].kind == "Q"]
    others = [i for i in ents if s.ents[i].kind not in ("L", "C", "A", "Q")]
    out = []
    from . import sketch3d as K
    if planes:
        # points and lines On Plane to a plane of the sketch
        if len(planes) == 1 and (pts or lines) and not rounds and not others:
            qa, qb, qc = planes[0].points[:3]
            on = [p for p in dict.fromkeys(pts + [q for ab in lines for q in ab]) if p not in (qa, qb, qc)]
            if on:
                out.append(("OnSketchPlane", "On Plane", [S.Relation("OnSketchPlane", [p, qa, qb, qc]) for p in on]))
        elif len(planes) == 1 and not (pts or lines or rounds or others):
            out.append(("Fix", "Fix", _FixAll(planes[0].points)))
        return out
    curves = [s.ents[i] for i in ents if s.ents[i].kind in ("L", "C", "A", "S")]
    if others:
        sp = s.ents[others[0]]
        if len(others) == 1 and not (pts or lines or rounds):
            out.append(("Fix", "Fix", _FixAll(sp.points)))      # a spline: all its points
        elif len(curves) == 2 and not pts:
            other = curves[1] if curves[0] is sp else curves[0]
            tan = spline_tangent(s, sp, other)
            if tan is not None:
                out.append(("Tangent", "Tangent", tan))
            out.append(("CurveLength", "Equal Curve Length", curve_length_relation(s, curves[0], curves[1])))
        return out
    if rounds:
        r1 = rounds[0]
        n1 = K.arc_normal(r1, s.rels)
        c1, a1 = r1.points[0], r1.points[1]
        if len(rounds) == 1 and not pts and not lines:
            out.append(("Fix", "Fix", _FixAll(r1.points)))
        elif len(rounds) >= 2 and not pts and not lines:
            r2 = rounds[1]
            c2, a2 = r2.points[0], r2.points[1]
            d = K._len(K._sub(s.pts[c2], s.pts[c1]))
            ra, rb = (K._len(K._sub(s.pts[a], s.pts[c])) for c, a in ((c1, a1), (c2, a2)))
            side = 1.0 if abs(d - (ra + rb)) <= abs(d - abs(ra - rb)) else -1.0
            out += [("Tangent", "Tangent", S.Relation("TangentArcs", [c1, a1, c2, a2], [side])),
                    ("Concentric", "Concentric", S.Relation("Concentric", [c1, c2])),
                    ("Coradial", "Coradial", S.Relation("Coradial", [c1, a1, c2, a2])),
                    ("Equal", "Equal", S.Relation("Equal", [c1, a1, c2, a2])),
                    ("CurveLength", "Equal Curve Length", curve_length_relation(s, r1, r2))]
        elif len(rounds) == 1 and len(pts) == 1 and not lines:
            p = pts[0]
            if p not in r1.points:
                out.append(("Coincident", "Coincident", S.Relation("OnArc", [c1, a1, p], list(n1))))
            if p != c1:
                out.append(("Concentric", "Concentric", S.Relation("Concentric", [p, c1])))
            if r1.kind == "A" and p not in r1.points:
                out.append(("Midpoint", "Midpoint", S.Relation("ArcMidpoint", [p, c1, a1, r1.points[2]], list(n1))))
        elif len(rounds) == 1 and len(lines) == 1 and not pts:
            a, b = lines[0]
            shared = [q for q in (a, b) if q in r1.points[1:]]
            out.append(("Tangent", "Tangent", S.Relation("Tangent", [c1, shared[0] if shared else a1, a, b], list(n1))))
            line = next(s.ents[i] for i in ents if s.ents[i].kind == "L")
            out.append(("CurveLength", "Equal Curve Length", curve_length_relation(s, line, r1)))
        return out
    if not pts and len(lines) == 1:
        a, b = lines[0]
        for kind in S.ALONG:
            out.append((kind, S.NAMES[kind], S.Relation(kind, [a, b])))
        if s.on_sketch_plane() is not None or s.on_custom():

            for kind in (("PlaneH", "PlaneV") if s.on_sketch_plane() is not None else ("AlongDirH", "AlongDirV")):
                out.append((kind, S.NAMES[kind], s.axis_relation(kind, a, b)))
        out.append(("Fix", "Fix", _FixAll([a, b])))
    elif not pts and len(lines) >= 2:
        (a, b), (c, d) = lines[0], lines[1]
        for kind in ("Parallel", "Perpendicular", "Equal", "Collinear"):
            out.append((kind, kind, S.Relation(kind, [a, b, c, d])))
    elif len(pts) == 1 and not lines:
        out.append(("Fix", "Fix", S.Relation("Fix", [pts[0]], list(s.pts[pts[0]]))))
    elif len(pts) == 2 and not lines:
        a, b = pts
        out.append(("Merge", "Merge", "merge"))
        for kind in S.ALONG:
            out.append((kind, S.NAMES[kind], S.Relation(kind, [a, b])))
    elif len(pts) == 1 and len(lines) == 1:
        p, (a, b) = pts[0], lines[0]
        if p not in (a, b):
            out.append(("Coincident", "Coincident", S.Relation("OnLine", [p, a, b])))
            out.append(("Midpoint", "Midpoint", S.Relation("Midpoint", [p, a, b])))
    elif len(pts) == 1 and len(lines) == 2:
        p, (a, b), (c, d) = pts[0], lines[0], lines[1]
        out.append(("Intersection", "Intersection", [S.Relation("OnLine", [p, a, b]), S.Relation("OnLine", [p, c, d])]))
    return out


def model_picks(s):
    """(object, element) the person picked in the model next to the sketch items (Ctrl+click):
    datum planes, faces, edges, corners."""
    out = []
    try:
        for sel in Gui.Selection.getSelectionEx(s.doc.Name):
            o = sel.Object
            if o is s.obj:
                continue
            subs = [n for n in sel.SubElementNames if n] or [""]
            for n in subs:
                out.append((o, n.rsplit(".", 1)[-1]))
    except Exception as _fw_err:
        _fw_log("sketch3dpm.py:1961", _fw_err)
    return out


def model_addable(s, items, model):
    """Relations to the model: On Plane (a plane or flat face), On Surface (a curved face), Coincident
    (an edge, or a corner for one point). Each applies to every point of the picked items."""
    from . import sketch3d as K
    if len(model) != 1 or any(k == "R" for k, _ in items):
        return []
    obj, sub = model[0]
    pts = []
    for k, i in items:
        for p in ([i] if k == "P" else s.ents[i].points):
            if p not in pts:
                pts.append(p)
    if not pts:
        return []
    if K.is_plane_pick(obj, sub):
        out = [("OnPlane", "On Plane", [K.model_relation(s.doc, "OnPlane", p, obj.Name, sub or "-") for p in pts])]
        pl = K.plane_of(s.doc, obj.Name, sub or "-")
        ref = (obj.Name, sub or "-")
        ents = [s.ents[i] for k, i in items if k == "E"]
        if pl is not None and len(items) == 1 and ents and ents[0].kind == "L":
            a, b = ents[0].points[:2]
            base, n = pl
            x, y = plane_axes(s.doc, obj.Name, sub or "-", n)
            out += [("Parallel", "Parallel", S.Relation("PlaneParallel", [a, b], list(base) + list(n), ref)),
                    ("PlaneNormal", "Normal", S.Relation("PlaneNormal", [a, b], list(base) + list(n), ref)),
                    ("ParallelYZ", "Parallel YZ", S.Relation("ParallelYZ", [a, b], list(base) + list(n) + list(x), ref)),
                    ("ParallelZX", "Parallel ZX", S.Relation("ParallelZX", [a, b], list(base) + list(n) + list(y), ref))]
        if pl is not None and len(pts) == 2 and all(k == "P" for k, _ in items):
            out.append(("Symmetric", "Symmetric", S.Relation("SymPlane", pts, list(pl[0]) + list(pl[1]), ref)))
        return out
    if sub.startswith("Face"):
        return [("OnSurface", "On Surface", [K.model_relation(s.doc, "OnSurface", p, obj.Name, sub) for p in pts])]
    if sub.startswith("Edge"):
        return [("Coincident", "Coincident", [K.model_relation(s.doc, "OnEdge", p, obj.Name, sub) for p in pts])]
    if sub.startswith("Vertex") and len(pts) == 1:
        try:
            v = obj.Shape.getElement(sub).Point
        except Exception:
            return []
        return [("Coincident", "Coincident", [S.Relation("AtRef", [pts[0]], [v.x, v.y, v.z], (obj.Name, sub))])]
    return []


CURVE_CODE = {"L": 0, "A": 1, "S": 2, "C": 3}


def curve_length_relation(s, e1, e2):
    """Equal Curve Length between two of lines, arcs, circles and splines."""
    from . import sketch3d as K
    vals = [float(len(e1.points)), float(CURVE_CODE[e1.kind]), float(CURVE_CODE[e2.kind])]
    for e in (e1, e2):
        vals += list(K.arc_normal(e, s.rels)) if e.kind in ("C", "A") else [0.0, 0.0, 0.0]
    return S.Relation("CurveLength", list(e1.points) + list(e2.points), vals)


def spline_tangent(s, sp, other):
    """Tangent of a spline's end to the line or arc that shares it, else None."""
    from . import sketch3d as K
    p = sp.points
    if len(p) < 2 or (len(p) > 3 and p[0] == p[-1]):
        return None
    for e, n in ((p[0], p[1]), (p[-1], p[-2])):
        if other.kind == "L" and e in other.points:
            return S.Relation("SplineTangent", [e, n] + list(other.points[:2]))
        if other.kind == "A" and e in other.points[1:]:
            return S.Relation("SplineTangentArc", [e, n, other.points[0], e], list(K.arc_normal(other, s.rels)))
        if other.kind == "S" and e in (other.points[0], other.points[-1]) and other.points[0] != other.points[-1]:

            return S.Relation("SplineTangentSpline", [e, n] + list(other.points))
    return None


def plane_axes(doc, name, element, n):
    """(x, y) of a datum plane (its own X and Y) or a flat face (two axes at right angles in it)."""
    o = doc.getObject(name)
    try:
        if element in ("", "-"):
            pl = o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else o.Placement
            x, y = pl.Rotation.multVec(App.Vector(1, 0, 0)), pl.Rotation.multVec(App.Vector(0, 1, 0))
            return (x.x, x.y, x.z), (y.x, y.y, y.z)
    except Exception as _fw_err:
        _fw_log("sketch3dpm.py:2046", _fw_err)
    from . import sketch3d as K
    cand = [a for a in ((1, 0, 0), (0, 1, 0), (0, 0, 1)) if abs(K._dot(a, n)) < 1e-9]
    if len(cand) >= 2:
        return cand[0], cand[1]
    seed = (1, 0, 0) if abs(n[0]) < 0.9 else (0, 1, 0)
    u = K._sub(seed, K._mul(n, K._dot(seed, n)))
    u = K._mul(u, 1.0 / K._len(u))
    v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
    return u, v


class _FixAll:
    ""
    kind = "FixAll"

    def __init__(self, points):
        self.points = list(dict.fromkeys(points))


def merge(s, items):
    pts = [i for k, i in items if k == "P"]
    if len(pts) != 2:
        return None
    keep, drop = pts
    target = s.pts[keep]
    pts_list = list(s.pts)
    pts_list[drop] = target
    new_pts, ents, rels = S.merge_points(pts_list, s.ents, s.rels, keep, drop)
    s.selection = []
    s.write("Merge", new_pts, ents, rels)
    return None


# ------------------------------------------------------------------ Modify box
class ModifyBox(QtWidgets.QFrame):
    ""

    def __init__(self, session, k):
        super().__init__(Gui.getMainWindow(), Qt.Tool | Qt.FramelessWindowHint)
        self.s, self.k = session, k
        self.setObjectName("FreeWorks3DModifyBox")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 6)
        title = QtWidgets.QLabel("Modify", self)
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)
        row = QtWidgets.QHBoxLayout()
        self.ok = QtWidgets.QToolButton(self)
        self.ok.setObjectName("SW3DModifyOK")
        self.ok.setText("✔")
        self.ok.setToolTip("Save the current value and exit the dialog")
        self.cancel = QtWidgets.QToolButton(self)
        self.cancel.setObjectName("SW3DModifyCancel")
        self.cancel.setText("✖")
        self.cancel.setToolTip("Restore the original value and exit the dialog")
        try:
            rp = _relationspm()
            self.ok.setIcon(rp._pack_or("CHECK_MARK", rp._draw_check, "#74a257"))
        except Exception as _fw_err:
            _fw_log("sketch3dpm.py:2109", _fw_err)
        row.addWidget(self.ok)
        row.addWidget(self.cancel)
        row.addStretch(1)
        lay.addLayout(row)
        self.edit = _spin(self, session.rels[k].values[0], 0.0, angle=session.rels[k].kind in S.ANGLES)
        self.edit.setObjectName("SW3DModifyValue")
        lay.addWidget(self.edit)
        self.ok.clicked.connect(self.apply)
        self.cancel.clicked.connect(self.close)
        self.edit.lineEdit().returnPressed.connect(self.apply)

    def keyPressEvent(self, event):
        try:
            if event.key() == Qt.Key_Escape:
                self.close()
                return
        except Exception as _fw_err:
            _fw_log("sketch3dpm.py:2127", _fw_err)
        super().keyPressEvent(event)

    def apply(self):
        try:
            self.edit.interpretText()
            if self.k < len(self.s.rels) and self.s.rels[self.k].kind in S.DIMENSIONS:
                why = self.s.set_dimension(self.k, self.edit.value())
                if why:
                    self.s.status(why)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD 3D Sketch: Modify: %s\n" % error)
        self.close()

    def closeEvent(self, event):
        global _modify
        if _modify is self:
            _modify = None
        _focus_view()
        super().closeEvent(event)


_modify = None


def modify_dimension(session, k):
    global _modify
    if _modify is not None:
        try:
            _modify.close()
        except Exception as _fw_err:
            _fw_log("sketch3dpm.py:2158", _fw_err)
    box = _modify = ModifyBox(session, k)
    box.adjustSize()
    box.move(QtGui.QCursor.pos() + QtCore.QPoint(12, 12))
    box.show()
    box.raise_()
    box.activateWindow()
    box.edit.setFocus()
    box.edit.selectAll()
    return box


# ------------------------------------------------------------------ session callbacks
def session_started(session):
    _host.close()


def session_ended(session):
    _host.close()
    if _modify is not None:
        try:
            _modify.close()
        except Exception as _fw_err:
            _fw_log("sketch3dpm.py:2181", _fw_err)


def tool_started(session, tool):
    _host.show(make_tool_page(session, tool))


def tool_ended(session, tool):
    page = _host.page
    if page is not None and getattr(page, "tool", None) is tool:
        _host.close()
    selection_changed(session)


def tool_picks_changed(session, tool):
    page = _host.page
    if page is not None and getattr(page, "tool", None) is tool and hasattr(page, "picks_changed"):
        page.picks_changed()


def plane_changed(session):
    page = _host.page
    if page is not None and hasattr(page, "update_message"):
        page.update_message()


def selection_changed(session):
    if session.tool is not None:
        return
    page = _host.page
    if not session.selection:
        if page is not None:
            _host.close()
        return
    _host.show(make_properties_page(session))
