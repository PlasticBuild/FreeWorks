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

from . import trace

try:
    from PySide import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtWidgets

GENERAL = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"


_GROUP = []     # the parameter group, kept: ParamGet on every mouse move was most of this filter's cost


def wanted():
    if not _GROUP:
        _GROUP.append(App.ParamGet(GENERAL))
    return _GROUP[0].GetBool("PickModelInSketch", True)


def page_takes_model_clicks():
    ""

    try:
        from .. import sketchtoolpm
        page = sketchtoolpm.current()
        return page is not None and sketchtoolpm.alive(page) and bool(getattr(page, "TAKES_MODEL_CLICKS", False))
    except Exception as _fw_err:
        _fw_log("fwsketch/modelpick.py:page_takes_model_clicks", _fw_err)
        return False


def _colour():
    packed = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("HighlightColor", 0xE1E114FF)
    return ((packed >> 24) & 255) / 255.0, ((packed >> 16) & 255) / 255.0, ((packed >> 8) & 255) / 255.0


def sketch_preselected(sketch):
    """FreeCAD has an item of the edited sketch under the pointer (Coin's pick does not report
    the sketch's edit-mode geometry, so its preselection tells)."""
    from .toolbase import preselected_subs
    return bool(preselected_subs(sketch))


def _is_seam(edge, face):
    try:
        return bool(edge.isSeam(face))
    except Exception:
        return False


def seam_vertex(obj, sub):
    ""

    if not sub.startswith("Vertex"):
        return None
    try:
        import Part
        shape = obj.Shape
        v = shape.Vertexes[int(sub[6:]) - 1]
        edges = shape.ancestorsOfType(v, Part.Edge)
        closed = [e for e in edges if e.isClosed()]
        if not closed:
            return None
        for e in edges:
            if e.isClosed():
                continue

            if not any(_is_seam(e, f) for f in shape.ancestorsOfType(e, Part.Face)):
                return None
        for i, e in enumerate(shape.Edges):
            if e.isSame(closed[0]):
                return "Edge%d" % (i + 1)
    except Exception:
        return None
    return None


def element_under(view, sketch, pos=None):
    """(object, "EdgeN" / "VertexN") of the part under the pointer, or None. Anything of the
    edited sketch under the pointer comes first (FreeCAD's own pick), so does a part face."""
    if sketch_preselected(sketch):
        return None
    try:
        trace.note("modelpick getObjectsInfo")
        hits = view.getObjectsInfo(pos or view.getCursorPos()) or []
    except Exception:
        return None
    doc = sketch.Document
    for hit in hits:
        name, sub = hit.get("Object"), hit.get("Component") or ""
        if name == sketch.Name:
            return None
        if not name or not sub.startswith(("Edge", "Vertex")):
            continue
        obj = doc.getObject(name)
        if obj is None or not hasattr(obj, "Shape"):
            continue
        return obj, seam_vertex(obj, sub) or sub   # another sketch's edge counts too (Midpoint, Pierce on it)
    face_hit = None
    for hit in hits:
        if (hit.get("Component") or "").startswith("Face"):
            face_hit = hit
            break         # on a face: its outline may be right there
    else:
        if hits:
            return None
    try:
        from . import silhouette
        found = silhouette.nearest(view, sketch, pos)
    except Exception:
        found = None
    if found is not None:
        src, face, side, _edge = found
        return src, "%s%d:%d" % (SILHOUETTE, face, side)
    if face_hit is not None:

        # Entities take it)
        obj = doc.getObject(face_hit.get("Object") or "")
        if obj is not None and hasattr(obj, "Shape") and getattr(obj, "Visibility", True):
            return obj, face_hit.get("Component")
    return None


SILHOUETTE = "Silhouette:"     # element_under's sub for an outline no edge of the part has


def _silhouette_edge(obj, sub):
    face, side = (int(x) for x in sub[len(SILHOUETTE):].split(":"))
    from . import silhouette
    f = obj.Shape.Faces[face]
    gdoc = Gui.ActiveDocument
    vp = gdoc.getInEdit() if gdoc else None
    sketch = getattr(vp, "Object", None)
    normal = sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
    return silhouette.outline(f, type(f.Surface).__name__, side, normal)


def element_points(obj, sub):
    if sub.startswith(SILHOUETTE):
        try:
            shape = _silhouette_edge(obj, sub)
            pts = shape.discretize(Deflection=0.05)
            return [(p.x, p.y, p.z) for p in pts], False
        except Exception:
            return [], False
    try:
        shape = obj.getSubObject(sub)
    except Exception:
        shape = None
    if shape is None:
        try:
            shape = obj.Shape.getElement(sub)
        except Exception:
            return [], False
    if sub.startswith("Vertex"):
        p = shape.Point
        return [(p.x, p.y, p.z)], True
    if sub.startswith("Face"):
        try:
            pts = shape.OuterWire.discretize(Deflection=0.05)       # fix308: the face lit by its outline
            return [(p.x, p.y, p.z) for p in pts], False
        except Exception:
            return [], False
    try:
        pts = shape.discretize(Deflection=0.05) if shape.Length > 0 else []
    except Exception:
        pts = [v.Point for v in shape.Vertexes]
    return [(p.x, p.y, p.z) for p in pts], False


class Highlight:
    """The lit element: a thick line or a marker drawn over everything, never picked."""

    def __init__(self, view):
        from pivy import coin
        self.coin = coin
        self.view = view
        self.root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        self.colour = coin.SoBaseColor()
        self.colour.rgb = _colour()
        style = coin.SoDrawStyle()
        style.lineWidth = 3
        style.pointSize = 7
        self.coords = coin.SoCoordinate3()
        self.lines = coin.SoLineSet()
        self.markers = coin.SoMarkerSet()
        self.markers.markerIndex = coin.SoMarkerSet.CIRCLE_FILLED_7_7
        for node in (pick, self.colour, style, self.coords, self.lines, self.markers):
            self.root.addChild(node)
        self.lines.numVertices.setValue(0)
        self.markers.numPoints = 0
        view.getSceneGraph().addChild(self.root)

    def show(self, points, vertex):
        self.coords.point.setValues(0, len(points), points)
        self.coords.point.setNum(len(points))
        if vertex:
            self.lines.numVertices.setValue(0)
            self.markers.numPoints = len(points)
        else:
            self.lines.numVertices.setValue(len(points))
            self.markers.numPoints = 0

    def clear(self):
        self.show([], False)

    def remove(self):
        try:
            self.view.getSceneGraph().removeChild(self.root)
        except Exception as _fw_err:
            _fw_log("fwsketch/modelpick.py:180", _fw_err)


class ModelPickWatcher(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.hover = None              # (object name, sub) lit now
        self.highlight = None
        self.view = None
        self.pressed = None            # the element a swallowed press was on
        self.picked = []               # (object name, sub, added) per click, for tests
        self._hover_pending = False
        self._closing = False          # the main window is closing: hands off FreeCAD's objects
        self._app = QtWidgets.QApplication.instance()
        from . import appevents
        appevents.listen(self, (QtCore.QEvent.Close, QtCore.QEvent.Leave, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove))   # one application filter (fix65)
        try:
            self._app.aboutToQuit.connect(self.stop)
        except Exception as _fw_err:
            _fw_log("fwsketch/modelpick.py:199", _fw_err)

    def stop(self):
        try:
            from . import appevents
            appevents.stop(self)
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/modelpick.py:206", _fw_err)
        self._clear()

    def _clear(self):
        self.hover = None
        if self.highlight is not None:
            self.highlight.remove()
            self.highlight = None
            self.view = None

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide on Windows can hand a filter a stale wrapper (a QWidgetItem) instead
        try:
            return self._filter(obj, event)
        except Exception:
            import traceback
            App.Console.PrintError("FreeCAD part picking: %s" % traceback.format_exc())
            return False

    def _context(self):
        ""
        if not wanted():
            return None
        from . import tool
        if tool.active() is not None:
            return None
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc else None
        obj = getattr(vp, "Object", None) if vp is not None else None   # an assembly's has none
        if obj is None or not obj.isDerivedFrom("Sketcher::SketchObject"):
            return None
        return gdoc.ActiveView, obj

    @staticmethod
    def _on_view(view, obj):
        try:
            return obj is view.graphicsView().viewport()
        except (AttributeError, RuntimeError):
            return False

    def _filter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # a stale wrapper (a QWidgetItem) when a page re-lays its rows
        t = event.type()
        if t == QtCore.QEvent.Close and obj is Gui.getMainWindow():
            # while FreeCAD closes its documents and views, asking them for the edited sketch is a
            # suspect for the Windows access violation at quit (relations stock-08); back on if
            # the close is cancelled
            self._closing = True
            self._clear()
            QtCore.QTimer.singleShot(1000, self._still_open)
            return False
        if self._closing:
            return False
        if t not in (QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonPress,
                     QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.Leave):
            return False
        if t == QtCore.QEvent.Leave and self.hover is None:
            return False                   # nothing lit to put out
        if t == QtCore.QEvent.MouseButtonRelease and self.pressed is not None \
                and event.button() == QtCore.Qt.LeftButton:
            target, self.pressed = self.pressed, None
            QtCore.QTimer.singleShot(0, lambda: self._toggle(*target))
            return True
        ctx = self._context()
        if ctx is None:
            if self.hover is not None and t == QtCore.QEvent.MouseMove:
                self._clear()
            return False
        view, sketch = ctx
        if not self._on_view(view, obj):
            return False   # the same move reaches the view's parents too
        if t == QtCore.QEvent.Leave:
            self._show(view, None)
            return False
        if t == QtCore.QEvent.MouseMove:
            if event.buttons() != QtCore.Qt.NoButton:
                return False
            # Coin's pick runs a moment later, outside the view's own event handling (picking
            # inside it is a suspect for the Windows access violation), once per burst of moves
            if not self._hover_pending:
                self._hover_pending = True
                QtCore.QTimer.singleShot(0, self._hover_now)
            return False
        if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            # the element lit under the pointer, unless the sketch has the pointer now
            if self.hover is None or sketch_preselected(sketch) or page_takes_model_clicks():
                return False
            self.pressed = (sketch.Document.Name,) + tuple(self.hover)
            return True
        return False

    def _still_open(self):
        try:
            self._closing = not Gui.getMainWindow().isVisible()
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/modelpick.py:303", _fw_err)

    def _hover_now(self):
        self._hover_pending = False
        if self._closing:
            return
        ctx = self._context()
        if ctx is None:
            return
        view, sketch = ctx
        found = element_under(view, sketch)
        self._show(view, (found[0].Name, found[1]) if found else None)

    def _show(self, view, element):
        trace.note("modelpick show %s" % (element,))
        if element == self.hover and (element is None or self.highlight is not None):
            return
        self.hover = element
        if self.highlight is None or self.view is not view:
            if self.highlight is not None:
                self.highlight.remove()
            self.highlight = Highlight(view)
            self.view = view
        if element is None:
            self.highlight.clear()
            return
        obj = App.ActiveDocument.getObject(element[0]) if App.ActiveDocument else None
        points, vertex = element_points(obj, element[1]) if obj is not None else ([], False)
        self.highlight.show(points, vertex)

    def _toggle(self, doc, name, sub):
        if sub.startswith(SILHOUETTE):

            from . import silhouette
            gdoc = Gui.ActiveDocument
            vp = gdoc.getInEdit() if gdoc else None
            sketch = getattr(vp, "Object", None)
            src = App.getDocument(doc).getObject(name)
            if sketch is None or src is None:
                return
            face, side = (int(x) for x in sub[len(SILHOUETTE):].split(":"))
            name, sub = silhouette.make(sketch, src, face, side).Name, "Edge1"
        selected = any(s.ObjectName == name and sub in s.SubElementNames
                       for s in Gui.Selection.getSelectionEx(doc))
        if selected:
            Gui.Selection.removeSelection(doc, name, sub)
        else:
            Gui.Selection.addSelection(doc, name, sub)
        self.picked.append((name, sub, not selected))


_watcher = None


def start():
    global _watcher
    if _watcher is None:
        _watcher = ModelPickWatcher()
    return _watcher


def stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
        _watcher = None


def watcher():
    return _watcher
