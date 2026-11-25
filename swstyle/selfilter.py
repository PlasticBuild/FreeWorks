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

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import checkstate, paths

Qt = QtCore.Qt


FILTERS = (
    ("Vertices", "Filter Vertices", ("vertex",), "V"),
    ("Edges", "Filter Edges", ("edge",), "E"),
    ("Faces", "Filter Faces", ("face",), "X"),
    ("SurfaceBodies", "Filter Surface Bodies", ("surface_body",), ""),
    ("SolidBodies", "Filter Solid Bodies", ("solid_body",), ""),
    ("Features", "Filter Features", ("feature",), ""),
    ("Components", "Filter Components", ("component",), ""),
    ("Axes", "Filter Axes", ("axis",), ""),
    ("Planes", "Filter Planes", ("plane",), ""),
    ("SketchPoints", "Filter Sketch Points", ("sketch_point",), ""),
    ("Sketches", "Filter Sketches", ("sketch",), ""),
    ("SketchSegments", "Filter Sketch Segments", ("sketch_segment",), ""),
    ("Midpoints", "Filter Midpoints", ("midpoint",), ""),
    ("CenterMarks", "Filter Center Marks", ("center_mark",), ""),
    ("Centerlines", "Filter Centerlines", ("centerline",), ""),
    ("Dimensions", "Filter Dimensions/Hole Callouts", ("dimension",), ""),
    ("SurfaceFinish", "Filter Surface Finish Symbols", ("surface_finish",), ""),
    ("GeometricTolerances", "Filter Geometric Tolerances", ("gtol",), ""),
    ("Notes", "Filter Notes/Balloons", ("note",), ""),
    ("DatumFeatures", "Filter Datum Features", ("datum_feature",), ""),
    ("WeldSymbols", "Filter Weld Symbols", ("weld_symbol",), ""),
    ("WeldBeads", "Filter Weld Beads", ("weld_bead",), ""),
    ("DatumTargets", "Filter Datum Targets", ("datum_target",), ""),
    ("CosmeticThreads", "Filter Cosmetic Threads", ("cosmetic_thread",), ""),
    ("Blocks", "Filter Blocks", ("block",), ""),
    ("DowelPins", "Filter Dowel Pin Symbols", ("dowel_pin",), ""),
    ("ConnectionPoints", "Filter Connection Points", ("connection_point",), ""),
    ("RoutingPoints", "Filter Routing Points", ("routing_point",), ""),
    ("MeshFacets", "Filter Mesh Facets", ("mesh_facet",), ""),
    ("MeshFacetEdges", "Filter Mesh Facet Edges", ("mesh_edge",), ""),
    ("MeshFacetVertices", "Filter Mesh Facet Vertices", ("mesh_vertex",), ""),
    ("Freeshape", "Filter Any Freeshape Entity", ("freeshape",), ""),
)
BY_KEY = {f[0]: f for f in FILTERS}
TIPS = {
    "Vertices": "Allows selection of vertices only.",
    "Edges": "Allows selection of edges only.",
    "Faces": "Allows selection of faces only.",
    "SurfaceBodies": "Allows selection of surface bodies only.",
    "SolidBodies": "Allows selection of solid bodies only.",
    "Features": "Allows selection of whole features (extrudes, cuts, fillets, holes...) in the graphics area only.",
    "Components": "Allows selection of top-level components (parts and subassemblies) only.",
    "Axes": "Allows selection of axes only.",
    "Planes": "Allows selection of planes only.",
    "SketchPoints": "Allows selection of sketch points only.",
    "Sketches": "Allows selection of sketches only.",
    "SketchSegments": "Allows selection of sketch segments only.",
    "Midpoints": "Allows selection of midpoints only.",
    "CenterMarks": "Allows selection of center marks only.",
    "Centerlines": "Allows selection of centerlines only.",
    "Dimensions": "Allows selection of dimensions and hole callouts only.",
    "MeshFacets": "Allows selection of mesh facets only.",
    "MeshFacetEdges": "Allows selection of mesh facet edges only.",
    "MeshFacetVertices": "Allows selection of mesh facet vertices only.",
    "Freeshape": "Allows selection of Freeshape bodies and their faces, edges and vertices only.",
}
# a click anywhere on one of these picks it whole when the finer filters are off
WHOLE = {"solid_body": ("face", "edge", "vertex"), "surface_body": ("face", "edge", "vertex"),
         "sketch": ("sketch_segment", "centerline", "sketch_point"),

         "feature": ("face", "edge", "vertex"), "component": ("face", "edge", "vertex")}
DIMENSIONAL = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")

TOOLBAR_NAME = "SWSelectionFilter"
DEBUG = None     # a list here records every gate call (tests)


def _params():
    return paths.params()


def _tip(key):
    return TIPS.get(key) or "Allows selection of %s only." % BY_KEY[key][1][len("Filter "):].lower()


# ---- what a pick is ----------------------------------------------------------------------------

def _element(sub):
    return (sub or "").rsplit(".", 1)[-1]


def _shape_kind(obj):
    shape = getattr(obj, "Shape", None)
    try:
        if shape is not None and not shape.isNull():
            return "solid_body" if shape.Solids else "surface_body"
    except Exception as _fw_err:
        _fw_log("selfilter.py:133", _fw_err)
    return "solid_body"


def _in_assembly(obj):
    """Whether obj sits in a document with an assembly: graphics picks there land on components."""
    try:
        return any(o.TypeId == "Assembly::AssemblyObject" for o in obj.Document.Objects)
    except Exception:
        return False


def _is_feature(obj):
    """A solid-making feature of a part (PartDesign feature, or a Part feature with a solid)."""
    try:
        if obj.isDerivedFrom("PartDesign::Feature") or obj.isDerivedFrom("PartDesign::Body"):
            return True
        return obj.isDerivedFrom("Part::Feature") and bool(obj.Shape.Solids or obj.Shape.Faces)
    except Exception:
        return False


def kinds(obj, sub):
    """The filter kinds a pick of (obj, sub) counts as; obj is the object that owns the element."""
    if obj is None:
        return set()
    out = _kinds(obj, sub)
    # a face, edge or vertex of a model, or the whole feature / component (what the filter picks)
    if "any" not in out and _element(sub)[:4] in ("Face", "Edge", "Vert", "") \
            and not obj.isDerivedFrom("Sketcher::SketchObject"):
        if _in_assembly(obj):
            out.add("component")
        elif _is_feature(obj):
            out.add("feature")
    return out


def _is_freeshape(obj):
    """A Freeshape feature (freeshape.py), or a body whose tip is one."""
    try:
        from . import simplefeature as sf
        for o in (obj, getattr(obj, "Tip", None)):
            spec = sf.SPECS.get(getattr(o, "SWStyleKind", "")) if o is not None else None
            if spec is not None and spec.command.startswith("SWStyle_Freeshape"):
                return True
    except Exception as _fw_err:
        _fw_log("selfilter.py:179", _fw_err)
    return False


def _kinds(obj, sub):
    kinds = _kinds0(obj, sub)
    if _is_freeshape(obj):
        kinds = set(kinds) | {"freeshape"}
    return kinds


def _kinds0(obj, sub):
    name = _element(sub)
    tid = getattr(obj, "TypeId", "")
    if obj.isDerivedFrom("Sketcher::SketchObject"):
        if name.startswith("Edge"):
            try:
                construction = obj.getConstruction(int(name[4:]) - 1)
            except Exception:
                construction = False
            return {"centerline" if construction else "sketch_segment", "sketch"}
        if name.startswith("ExternalEdge"):
            return {"sketch_segment", "sketch"}
        if name.startswith("Vertex") or name == "RootPoint":
            return {"sketch_point", "sketch"}
        if name in ("H_Axis", "V_Axis"):
            return {"axis"}
        if name.startswith("Constraint"):
            try:
                c = obj.Constraints[int(name[10:]) - 1]
            except Exception:
                return {"any"}
            return {"dimension"} if c.Type in DIMENSIONAL else {"any"}
        return {"sketch"}
    if tid in ("App::Plane", "PartDesign::Plane") or (name == "" and tid.endswith("::Plane")):
        return {"plane"}
    if tid in ("App::Line", "PartDesign::Line"):
        return {"axis"}
    if tid in ("App::Point", "PartDesign::Point"):
        return {"vertex"}
    if obj.isDerivedFrom("Mesh::Feature"):
        if name.startswith("Facet"):
            return {"mesh_facet"}
        return {"mesh_facet"} if name == "" else {"mesh_edge"}
    if name.startswith("Vertex"):
        return {"vertex", _shape_kind(obj)}
    if name.startswith("Edge"):
        return {"edge", _shape_kind(obj)}
    if name.startswith("Face"):
        return {"face", _shape_kind(obj)}
    if name == "":
        if tid in ("App::Origin",) or obj.isDerivedFrom("App::OriginFeature"):
            return {"any"}
        return {_shape_kind(obj)} if hasattr(obj, "Shape") else {"any"}
    return {"any"}


def _view_under_cursor():
    """Whether the pointer is over a 3D view: only graphics-area picks are filtered."""
    app = QtWidgets.QApplication.instance()
    w = app.widgetAt(QtGui.QCursor.pos()) if app else None
    while w is not None:
        name = w.metaObject().className()
        if "View3DInventor" in name or w.inherits("QOpenGLWidget") or w.inherits("QGLWidget"):
            return True
        w = w.parentWidget()
    return False


# ---- state -------------------------------------------------------------------------------------

class _State(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self):
        super().__init__()
        p = _params()

        # across a restart when KeepSelectionFilters is on (a stale filter blocked picks: E15-08)
        saved = p.GetString("SelectionFilters", "") if p.GetBool("KeepSelectionFilters", False) else ""
        self.on = {k for k in saved.split(",") if k in BY_KEY}
        self.active = p.GetBool("SelectionFiltersActive", True)

    def save(self):
        p = _params()
        p.SetString("SelectionFilters", ",".join(k for k, *_ in FILTERS if k in self.on))
        p.SetBool("SelectionFiltersActive", self.active)
        self.changed.emit()

    def filtering(self):
        return self.active and bool(self.on)

    def allowed_kinds(self):
        out = set()
        for k in self.on:
            out.update(BY_KEY[k][2])
        return out

    def is_on(self, key):
        return self.active and key in self.on

    def toggle(self, key):
        if not self.active:
            # a filter pressed while the filters are toggled off turns them back on with it
            self.active = True
            self.on.add(key)
        elif key in self.on:
            self.on.discard(key)
        else:
            self.on.add(key)
        self.save()

    def toggle_all(self):
        self.active = not self.active
        self.save()

    def clear_all(self):
        self.on.clear()
        self.save()

    def select_all(self):
        self.on = {k for k, *_ in FILTERS}
        self.active = True
        self.save()


STATE = None


def state():
    global STATE
    if STATE is None:
        STATE = _State()
    return STATE


def allows(obj, sub):
    """Whether a graphics-area pick of (obj, sub) gets through the filters that are on."""
    s = state()
    if not s.filtering():
        return True
    k = kinds(obj, sub)
    if "any" in k:
        return True
    return bool(k & s.allowed_kinds())


def whole_pick(obj, sub):
    """The object to pick whole instead of (obj, sub) when only a body or sketch filter lets the
    pick through, else None."""
    s = state()
    if not s.filtering() or not sub:
        return None
    k = kinds(obj, sub)
    allowed = s.allowed_kinds()
    if k & allowed - set(WHOLE):
        return None             # a finer filter (Faces, Sketch Segments...) took it: keep the element
    for whole in WHOLE:
        if whole in k and whole in allowed:
            return whole
    return None


# ---- the gate and keeping it in ----------------------------------------------------------------

class _Gate:
    def __init__(self, manager):
        self.manager = manager
        self.last = 0.0

    def allow(self, doc, obj, sub):
        self.last = time.monotonic()
        if DEBUG is not None:
            DEBUG.append((getattr(obj, "Name", obj), sub, self.manager.enabled, _view_under_cursor()))
        try:
            if not self.manager.enabled or not _view_under_cursor():
                return True
            ok = allows(obj, sub)
            if not ok:
                QtCore.QTimer.singleShot(0, self.manager.refused)
            return ok
        except Exception:
            return True


class _Observer:
    def __init__(self, manager):
        self.manager = manager

    def setPreselection(self, doc, obj, sub):
        self.manager.preselected()

    def addSelection(self, doc, obj, sub, pnt):
        self.manager.picked(doc, obj, sub)


def _gl_widget():
    try:
        view = Gui.ActiveDocument.ActiveView
        viewer = view.getViewer() if hasattr(view, "getViewer") else None
        widget = viewer.getGLWidget() if viewer is not None and hasattr(viewer, "getGLWidget") else None
    except Exception:
        widget = None
    if widget is None:
        widget = _scan_gl(Gui.getMainWindow())
    return widget


_GL_CLASS = []


def _scan_gl(mw):
    """The visible OpenGL widget of the main window (the 3D view when FreeCAD gives none). Qt picks the OpenGL widgets by
    type, in C++, instead of a Python wrapper being made for every widget of the window on every call."""
    if not _GL_CLASS:
        cls = None
        try:
            from PySide import QtOpenGLWidgets
            cls = QtOpenGLWidgets.QOpenGLWidget
        except Exception:
            try:
                from PySide6 import QtOpenGLWidgets
                cls = QtOpenGLWidgets.QOpenGLWidget
            except Exception:
                cls = getattr(QtWidgets, "QOpenGLWidget", None)
        _GL_CLASS.append(cls)
    cls = _GL_CLASS[0]
    found = mw.findChildren(cls) if cls is not None else \
        (w for w in mw.findChildren(QtWidgets.QWidget) if w.inherits("QOpenGLWidget"))
    return next((w for w in found if w.isVisible()), None)


def _listed(widget):
    """True while the main window still owns the widget: a view being closed is gone from the list
    before its Python wrapper is, and touching it then crashes FreeCAD."""
    try:
        return widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget, "", QtCore.Qt.FindChildrenRecursively)
    except Exception:
        return False


_CURSOR = []


def filter_cursor():
    ""
    if not _CURSOR:
        from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
        pm = _hidpi.canvas(32, 32)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        P = QtCore.QPointF
        arrow = [P(1, 1), P(1, 17), P(5, 13), P(8, 19), P(10.5, 18), P(7.5, 12), P(12.5, 12)]
        p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 1))
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawPolygon(arrow)
        p.scale(1.4, 1.4)
        _funnel(p, 9, 11, QtGui.QColor("#d020c8"))
        p.end()
        _CURSOR.append(QtGui.QCursor(pm, *_hidpi.hotspot(1, 1, pm)))
    return _CURSOR[0]


def _ours(cursor):
    try:
        return bool(_CURSOR) and cursor.shape() == Qt.BitmapCursor and \
            cursor.pixmap().cacheKey() == _CURSOR[0].pixmap().cacheKey()
    except Exception:
        return False


def _tool_busy():
    """A task panel or a tool with its own cursor (Sketcher tools) may have its own gate in."""
    try:
        if Gui.Control.activeDialog():
            return True
    except Exception as _fw_err:
        _fw_log("selfilter.py:434", _fw_err)
    widget = _gl_widget()
    if widget is not None and _ours(widget.cursor()):
        return False
    return widget is not None and widget.cursor().shape() == Qt.BitmapCursor     # (the same lookup, not made twice)


class _Manager:
    def __init__(self):
        self.gate = None          # our gate while FreeCAD holds it (as far as we know)
        self.enabled = False      # the gate filters (off at once; taken out when safe)
        self.busy = False
        self.converting = False
        self.observer = _Observer(self)
        Gui.Selection.addObserver(self.observer)
        self.timer = QtCore.QTimer()
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        try:
            from . import ticks as _ticks
            _ticks.slow_when_idle(self.timer)
        except Exception as _fw_err:
            __import__("FreeCAD").Console.PrintLog("FreeCAD ticks: %s\n" % _fw_err)
        state().changed.connect(self.sync)
        self.sync()

    def _install(self):
        self.gate = _Gate(self)
        Gui.Selection.addSelectionGate(self.gate)

    def sync(self):
        want = state().filtering()
        self.enabled = want
        busy = _tool_busy()
        if want and self.gate is None and not busy:
            self._install()
        elif want and self.gate is not None and not busy:
            self._install()       # ours or not, nothing else needs a gate now
        elif not want and self.gate is not None and not busy:
            Gui.Selection.removeSelectionGate()
            self.gate = None
        try:
            self.show_cursor(busy)
        except Exception as _fw_err:
            _fw_log("selfilter.py:484", _fw_err)

    def show_cursor(self, busy):
        """The funnel pointer over the graphics area while the filters are on and nothing else
        owns the pointer; the plain arrow back when they go off."""
        widget = _gl_widget()
        if widget is None or not _listed(widget):
            return
        cursor = widget.cursor()
        if self.enabled and not busy:
            if cursor.shape() == Qt.ArrowCursor:
                widget.setCursor(filter_cursor())
        elif _ours(cursor):
            widget.setCursor(Qt.ArrowCursor)

    def refused(self):
        ""
        now = time.monotonic()
        if now - getattr(self, "_told", 0.0) < 2.0:
            return
        self._told = now
        names = [name.replace("Filter ", "") for key, name, *_ in FILTERS if key in state().on]
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "Selection Filter on (%s): only those can be picked. F6 turns the filters off." % ", ".join(names), 6000)
        except Exception as _fw_err:
            _fw_log("selfilter.py:510", _fw_err)

    def poll(self):
        busy = _tool_busy()
        try:
            self.show_cursor(busy)
        except Exception as _fw_err:
            _fw_log("selfilter.py:517", _fw_err)
        if self.busy and not busy:
            # a task panel or tool just ended and may have taken its gate (and ours) out with it
            self.gate = None
            self.sync()
        elif not busy and (self.gate is None) == self.enabled:
            self.sync()
        self.busy = busy

    def preselected(self):
        # a hover the gate never saw: our gate is not in any more
        if self.enabled and self.gate is not None and time.monotonic() - self.gate.last > 0.25:
            self.gate = None
            if not _tool_busy():
                self.sync()

    def picked(self, doc, obj, sub):
        if self.converting or not sub or not _view_under_cursor():
            return
        try:
            top = App.getDocument(doc).getObject(obj)
            leaf, element = top.resolve(sub)[0], _element(sub)
        except Exception:
            return
        try:
            from .sketchextras import sketch_in_edit
            if leaf is not None and leaf == sketch_in_edit():
                return          # picks inside the sketch being edited stay elements
        except Exception as _fw_err:
            _fw_log("selfilter.py:546", _fw_err)
        whole = whole_pick(leaf, element)
        if whole is None:
            return
        target = leaf
        if whole == "feature":
            try:
                from .contextbar import owner_feature
                target = owner_feature(leaf, element) or leaf
            except Exception:
                target = leaf
            if target.isDerivedFrom("PartDesign::Body"):
                target = getattr(target, "Tip", None) or target
        elif whole == "component":
            # the top-level component: the first object of the pick's path under the assembly
            head = sub.split(".")[0] if "." in sub else ""
            comp = top.Document.getObject(head) if head else None
            if top.TypeId == "Assembly::AssemblyObject" and comp is not None:
                target = comp
            else:
                target = top
        if whole in ("solid_body", "surface_body"):
            body = leaf.getParentGeoFeatureGroup() if hasattr(leaf, "getParentGeoFeatureGroup") else None
            if body is not None and body.isDerivedFrom("PartDesign::Body"):
                target = body

        def swap():
            self.converting = True
            try:
                Gui.Selection.removeSelection(doc, obj, sub)
                if target is top:
                    Gui.Selection.addSelection(doc, top.Name)
                else:
                    path = sub[:sub.find(target.Name + ".")] + target.Name + "." if (target.Name + ".") in sub else ""
                    if path:
                        Gui.Selection.addSelection(doc, top.Name, path)
                    else:
                        Gui.Selection.addSelection(doc, target.Name)
            finally:
                self.converting = False
        QtCore.QTimer.singleShot(0, swap)


MANAGER = None


# ---- icons -------------------------------------------------------------------------------------

def _dark():
    return QtWidgets.QApplication.palette().color(QtGui.QPalette.Window).lightness() < 128


def _icon(key):
    icon = QtGui.QIcon()
    for size in (20, 40):
        pm = QtGui.QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(size / 20.0, size / 20.0)
        _draw(p, key)
        p.end()
        icon.addPixmap(pm)
    return icon


def _funnel(p, x, y, color, mark=None):
    path = QtGui.QPainterPath()
    path.moveTo(x, y)
    path.lineTo(x + 8, y)
    path.lineTo(x + 5, y + 3.5)
    path.lineTo(x + 5, y + 7)
    path.lineTo(x + 3, y + 6)
    path.lineTo(x + 3, y + 3.5)
    path.closeSubpath()
    p.setPen(QtGui.QPen(color.darker(130), 0.8))
    p.setBrush(color)
    p.drawPath(path)
    if mark == "x":
        p.setPen(QtGui.QPen(QtGui.QColor("#d02020"), 1.6))
        p.drawLine(QtCore.QPointF(x + 7, y + 4), QtCore.QPointF(x + 11, y + 8))
        p.drawLine(QtCore.QPointF(x + 11, y + 4), QtCore.QPointF(x + 7, y + 8))
    elif mark == "check":
        p.setPen(QtGui.QPen(QtGui.QColor("#20a040"), 1.6))
        p.drawPolyline([QtCore.QPointF(x + 6.5, y + 6), QtCore.QPointF(x + 8, y + 8), QtCore.QPointF(x + 11.5, y + 3.5)])


def _draw(p, key):
    ink = QtGui.QColor("#9cc4f0" if _dark() else "#2f62a8")
    grey = QtGui.QColor("#a0a0a0" if _dark() else "#707070")
    magenta = QtGui.QColor("#d020c8")
    pen = QtGui.QPen(ink, 1.4)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    P = QtCore.QPointF
    if key == "Toggle":
        _funnel(p, 3, 3, grey.lighter(110))
        _funnel(p, 9, 9, magenta)
        return
    if key in ("Select", "InvertSelection"):
        arrow = [P(4, 2), P(4, 15), P(7, 12), P(9.5, 17), P(11.5, 16), P(9, 11), P(13, 11)]
        p.setPen(QtGui.QPen(QtGui.QColor("#202020"), 1))
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawPolygon(arrow)
        if key == "InvertSelection":
            p.setPen(QtGui.QPen(QtGui.QColor("#20a040"), 1.5))
            p.drawArc(QtCore.QRectF(11, 2, 7, 7), 30 * 16, 260 * 16)
            p.drawLine(P(17.3, 3.5), P(17.6, 6.2))
        return
    if key == "ClearAll":
        _funnel(p, 2, 4, magenta, "x")
        return
    if key == "SelectAll":
        _funnel(p, 2, 4, magenta, "check")
        return
    if key == "Vertices":
        p.setBrush(ink)
        p.drawEllipse(P(7, 7), 2.6, 2.6)
    elif key == "Edges":
        p.drawLine(P(2, 13), P(12, 3))
    elif key == "Faces":
        p.setBrush(QtGui.QColor(ink.red(), ink.green(), ink.blue(), 110))
        p.drawPolygon([P(2, 6), P(9, 2), P(13, 6), P(6, 11)])
    elif key == "SurfaceBodies":
        path = QtGui.QPainterPath(P(2, 10))
        path.cubicTo(P(5, 3), P(9, 13), P(13, 5))
        path.lineTo(P(13, 2))
        path.cubicTo(P(9, 9), P(5, 0), P(2, 7))
        path.closeSubpath()
        p.setBrush(QtGui.QColor(ink.red(), ink.green(), ink.blue(), 110))
        p.drawPath(path)
    elif key == "SolidBodies":
        p.setBrush(QtGui.QColor(ink.red(), ink.green(), ink.blue(), 150))
        p.drawPolygon([P(2, 5), P(7, 2), P(13, 4), P(13, 10), P(8, 13), P(2, 11)])
        p.drawLine(P(2, 5), P(8, 7))
        p.drawLine(P(8, 7), P(13, 4))
        p.drawLine(P(8, 7), P(8, 13))
    elif key == "Features":
        # a block with a boss on it, the boss filled: one feature
        p.drawRect(QtCore.QRectF(2, 8, 11, 5))
        p.setBrush(QtGui.QColor(ink.red(), ink.green(), ink.blue(), 150))
        p.drawRect(QtCore.QRectF(5, 3, 5, 5))
    elif key == "Components":
        # two blocks, one of them filled: a component of an assembly
        p.drawRect(QtCore.QRectF(2, 6, 6, 6))
        p.setBrush(QtGui.QColor(ink.red(), ink.green(), ink.blue(), 150))
        p.drawRect(QtCore.QRectF(7, 2, 6, 6))
    elif key == "Axes":
        pen.setDashPattern([3, 1.5, 1, 1.5])
        p.setPen(pen)
        p.drawLine(P(2, 13), P(13, 2))
    elif key == "Planes":
        p.drawPolygon([P(1, 9), P(6, 3), P(14, 3), P(9, 9)])
    elif key in ("SketchPoints", "ConnectionPoints", "RoutingPoints"):
        if key != "SketchPoints":
            p.drawLine(P(2, 12), P(12, 2) if key == "RoutingPoints" else P(7, 7))
        p.setBrush(ink)
        p.drawRect(QtCore.QRectF(5, 5, 4, 4))
    elif key == "Sketches":
        p.drawPolyline([P(2, 3), P(2, 12), P(12, 12)])
        p.drawArc(QtCore.QRectF(5, 2, 8, 8), 0, 180 * 16)
    elif key == "SketchSegments":
        p.drawLine(P(3, 11), P(11, 3))
        p.setBrush(ink)
        p.drawRect(QtCore.QRectF(1.5, 9.5, 3, 3))
        p.drawRect(QtCore.QRectF(9.5, 1.5, 3, 3))
    elif key == "Midpoints":
        p.drawLine(P(2, 12), P(12, 2))
        p.setBrush(QtGui.QColor("#f08020"))
        p.drawEllipse(P(7, 7), 2.2, 2.2)
    elif key == "CenterMarks":
        p.drawLine(P(7, 1), P(7, 13))
        p.drawLine(P(1, 7), P(13, 7))
        p.drawEllipse(P(7, 7), 3.5, 3.5)
    elif key == "Centerlines":
        pen.setDashPattern([3, 1.5, 1, 1.5])
        p.setPen(pen)
        p.drawLine(P(7, 1), P(7, 13))
    elif key == "Dimensions":
        p.drawLine(P(2, 9), P(12, 9))
        p.drawLine(P(2, 6), P(2, 12))
        p.drawLine(P(12, 6), P(12, 12))
        p.setFont(QtGui.QFont("Sans", 5))
        p.drawText(QtCore.QRectF(2, 1, 10, 7), Qt.AlignCenter, "0.3")
    elif key == "SurfaceFinish":
        p.drawPolyline([P(2, 7), P(5, 12), P(12, 2)])
    elif key == "GeometricTolerances":
        p.drawRect(QtCore.QRectF(1, 4, 12, 7))
        p.drawLine(P(5, 4), P(5, 11))
    elif key == "Notes":
        p.setFont(QtGui.QFont("Sans", 9, QtGui.QFont.Bold))
        p.drawText(QtCore.QRectF(0, 0, 14, 14), Qt.AlignCenter, "A")
    elif key == "DatumFeatures":
        p.drawRect(QtCore.QRectF(3, 1, 8, 7))
        p.setBrush(ink)
        p.drawPolygon([P(4, 13), P(10, 13), P(7, 9)])
    elif key == "WeldSymbols":
        p.drawLine(P(1, 10), P(13, 10))
        p.drawPolyline([P(4, 10), P(7, 5), P(10, 10)])
    elif key == "WeldBeads":
        path = QtGui.QPainterPath(P(1, 8))
        for i in range(4):
            path.quadTo(P(2.5 + 3 * i, 3), P(4 + 3 * i, 8))
        p.drawPath(path)
    elif key == "DatumTargets":
        p.drawEllipse(P(7, 7), 5, 5)
        p.drawLine(P(2, 7), P(12, 7))
    elif key == "CosmeticThreads":
        for i in range(4):
            p.drawLine(P(2 + 3 * i, 12), P(5 + 3 * i, 2))
    elif key == "Blocks":
        p.drawRect(QtCore.QRectF(2, 2, 10, 10))
        p.setFont(QtGui.QFont("Sans", 6, QtGui.QFont.Bold))
        p.drawText(QtCore.QRectF(2, 2, 10, 10), Qt.AlignCenter, "B")
    elif key == "DowelPins":
        p.drawEllipse(P(7, 7), 5, 5)
        p.drawLine(P(3.5, 3.5), P(10.5, 10.5))
        p.drawLine(P(10.5, 3.5), P(3.5, 10.5))
    elif key == "Freeshape":
        p.setBrush(QtGui.QColor(ink.red(), ink.green(), ink.blue(), 60))
        p.drawRoundedRect(QtCore.QRectF(2, 3, 10, 9), 4, 4)
        p.setPen(QtGui.QPen(ink, 1, Qt.DotLine))
        p.drawRect(QtCore.QRectF(1.5, 2.5, 11, 10))
    elif key.startswith("Mesh"):
        p.setBrush(QtGui.QColor(ink.red(), ink.green(), ink.blue(), 90 if key == "MeshFacets" else 0))
        p.drawPolygon([P(2, 12), P(7, 2), P(12, 12)])
        if key == "MeshFacetEdges":
            p.setPen(QtGui.QPen(QtGui.QColor("#f08020"), 2))
            p.drawLine(P(2, 12), P(12, 12))
        elif key == "MeshFacetVertices":
            p.setBrush(QtGui.QColor("#f08020"))
            for pt in (P(2, 12), P(7, 2), P(12, 12)):
                p.drawEllipse(pt, 1.8, 1.8)
    _funnel(p, 11, 11, magenta)


# ---- the toolbar -------------------------------------------------------------------------------

class FilterToolbar(QtWidgets.QToolBar):
    def __init__(self, mw):
        super().__init__("Selection Filter", mw)
        self.setObjectName(TOOLBAR_NAME)
        self.setIconSize(QtCore.QSize(20, 20))
        self.actions_by_key = {}
        s = state()
        self.toggle = self._add("Toggle", "Toggle Selection Filters", "Turns selected filters on and off.",
                                s.toggle_all, True)
        self._add("ClearAll", "Clear All Filters", "Turns off all selection filters.", s.clear_all)
        self._add("SelectAll", "Select All Filters", "Turns on all selection filters.", s.select_all)
        self.addSeparator()
        self.select = self._binding_action("Select", "Select",
                                           "Selects entities in the graphics area or the FeatureManager design tree.")
        self.invert = self._binding_action("InvertSelection", "Invert Selection",
                                           "Clears the currently selected entity and selects all the other entities.")
        self.addSeparator()
        for key, label, _kinds, letter in FILTERS:
            a = self._add(key, label, _tip(key), lambda key=key: s.toggle(key), True, letter)
            self.actions_by_key[key] = a
            if key in ("Components", "Centerlines", "RoutingPoints"):
                self.addSeparator()
        s.changed.connect(self.refresh)
        self.refresh()

    def _add(self, key, label, tip, fn, checkable=False, letter=""):
        a = self.addAction(_icon(key), label)
        a.setToolTip("<b>%s%s</b><br>%s" % (label, "  (%s)" % letter if letter else "", tip))
        a.setStatusTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(lambda checked=False, fn=fn: fn())
        return a

    def _binding_action(self, key, label, tip):
        sh = _shell()
        icon = QtGui.QIcon()
        try:
            from . import icons, catalog
            cmd = catalog.BY_KEY.get(key)
            if cmd is not None:
                icon = icons.command_icon(cmd)
        except Exception as _fw_err:
            _fw_log("selfilter.py:826", _fw_err)
        if icon.isNull():
            icon = _icon(key)
        a = self.addAction(icon, label)
        a.setToolTip("<b>%s</b><br>%s" % (label, tip))
        a.setStatusTip(tip)

        def run():
            shell = _shell()
            if shell is not None:
                try:
                    shell.binding(key).run()
                    return
                except Exception as _fw_err:
                    _fw_log("selfilter.py:840", _fw_err)
            if key == "Select":
                Gui.Selection.clearSelection()
            else:
                Gui.runCommand("SWStyle_InvertSelection")
        a.triggered.connect(lambda checked=False: run())
        return a

    def refresh(self):
        s = state()
        self.toggle.setChecked(s.filtering())
        for key, a in self.actions_by_key.items():
            a.setChecked(s.is_on(key))


def _shell():
    try:
        from . import shell
        return shell.shell()
    except Exception:
        return None


TOOLBAR = None


def toolbar(create=True):
    global TOOLBAR
    mw = Gui.getMainWindow()
    if TOOLBAR is not None:
        try:
            TOOLBAR.objectName()
            return TOOLBAR
        except RuntimeError:
            TOOLBAR = None
    if not create or mw is None:
        return None
    TOOLBAR = FilterToolbar(mw)

    # stacks a bottom area's rows from the window edge up, so it goes in before the tabs' row.
    tabs = mw.findChild(QtWidgets.QToolBar, "SWBottomToolBar")
    if tabs is not None and mw.toolBarArea(tabs) == Qt.BottomToolBarArea:
        mw.insertToolBar(tabs, TOOLBAR)
        mw.insertToolBarBreak(tabs)
    else:
        mw.addToolBarBreak(Qt.BottomToolBarArea)
        mw.addToolBar(Qt.BottomToolBarArea, TOOLBAR)
    TOOLBAR.visibilityChanged.connect(lambda shown: _params().SetBool("SelectionFilterToolbar", shown))
    return TOOLBAR


def toolbar_shown():
    tb = toolbar(create=False)
    return tb is not None and tb.isVisible()


def toggle_toolbar():
    tb = toolbar()
    if tb is None:
        return
    tb.setVisible(not tb.isVisible())


# ---- commands ----------------------------------------------------------------------------------

class _Cmd:
    def __init__(self, label, tip, fn, checked=None):
        self.label, self.tip, self.fn, self.checked = label, tip, fn, checked

    def GetResources(self):

        # sketch or feature is edited unless it says ForEdit
        return {"MenuText": self.label, "ToolTip": self.tip, "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        self.fn()

    def IsActive(self):
        if self.label in ("Selection Filter",):
            return True
        return App.ActiveDocument is not None


def _commands():
    s = state()
    out = [
        ("SWStyle_SelectionFilterToolbar", "Selection Filter",
         "Shows or hides the Selection Filter toolbar.", toggle_toolbar, toolbar_shown),
        ("SWStyle_ToggleSelectionFilters", "Toggle Selection Filters", "Turns selected filters on and off.",
         lambda: state().toggle_all(), lambda: state().filtering()),
        ("SWStyle_ClearAllFilters", "Clear All Filters", "Turns off all selection filters.",
         lambda: state().clear_all(), None),
        ("SWStyle_SelectAllFilters", "Select All Filters", "Turns on all selection filters.",
         lambda: state().select_all(), None),
    ]
    for key, label, _kinds, _letter in FILTERS:
        out.append(("SWStyle_Filter" + key, label, _tip(key), lambda key=key: state().toggle(key),
                    lambda key=key: state().is_on(key)))
    return out


COMMANDS = []
_installed = False


def install():
    global _installed, MANAGER
    if _installed:
        return
    for name, label, tip, fn, checked in _commands():
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _Cmd(label, tip, fn, checked))
        if checked is not None:
            checkstate.register(name, checked)
        COMMANDS.append(name)
    MANAGER = _Manager()
    if not _params().GetBool("SelectionFilterToolbarReset1", False):

        _params().SetBool("SelectionFilterToolbar", False)
        _params().SetBool("SelectionFilterToolbarReset1", True)
    if _params().GetBool("SelectionFilterToolbar", False):
        _show_when_ready()
    _installed = True


def _show_when_ready(tries=[0]):
    """Bring the toolbar back at start once the look's own bottom row is up (it goes under it)."""
    mw = Gui.getMainWindow()
    ready = mw is not None and mw.isVisible() and (
        mw.findChild(QtWidgets.QToolBar, "SWBottomToolBar") is not None or tries[0] > 50)
    if ready:
        toolbar().setVisible(True)
        return
    tries[0] += 1
    QtCore.QTimer.singleShot(200, _show_when_ready)
