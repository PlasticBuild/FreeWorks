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
from PySide import QtCore, QtGui, QtWidgets

from . import paths
from .widgets import alive

Qt = QtCore.Qt

VIEW = "User parameter:BaseApp/Preferences/View"
NAVIGATION = "Gui::SolidWorksNavigationStyle"
BULK = "BulkSelection"
HIDDEN_WIREFRAME = "SelectHiddenEdgesWireframe"  # Allow selection in wireframe and HLV modes
HIDDEN_SHADED = "SelectHiddenEdgesShaded"        # Allow selection in HLR and shaded modes
START = 4                                    # pixels the pointer moves before a box starts
WINDOW = QtGui.QColor(0, 120, 215)           # wholly inside: blue, solid
CROSSING = QtGui.QColor(0, 150, 60)          # touching: green, dashed
SKIP = ("Part::Part2DObject", "PartDesign::Plane", "PartDesign::Line", "PartDesign::Point",
        "PartDesign::CoordinateSystem", "App::Origin")
WIREFRAME, HIDDEN_LINE = 2, 3                # Std_DrawStyle actions
NATIVE = ("Std_BoxSelection", "Std_BoxElementSelection")
IDLE, PRESSED, DRAGGING = range(3)


def bulk():
    return "Lasso" if paths.params().GetString(BULK, "Box") == "Lasso" else "Box"


def set_bulk(kind):
    paths.params().SetString(BULK, "Lasso" if kind == "Lasso" else "Box")
    _sync_commands()


# --------------------------------------------------------------------------- regions (view pixels, y up)
class Rect:
    def __init__(self, a, b):
        self.x0, self.x1 = sorted((a[0], b[0]))
        self.y0, self.y1 = sorted((a[1], b[1]))
        self.window = b[0] >= a[0]           # dragged to the right

    def contains(self, p):
        return self.x0 <= p[0] <= self.x1 and self.y0 <= p[1] <= self.y1

    def crosses(self, p, q):
        if self.contains(p) or self.contains(q):
            return True
        corners = ((self.x0, self.y0), (self.x1, self.y0), (self.x1, self.y1), (self.x0, self.y1))
        return any(_segments_cross(p, q, corners[i], corners[(i + 1) % 4]) for i in range(4))

    def centre(self):
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)


class Loop:
    def __init__(self, points, window=None):
        self.points = list(points)
        # Clockwise on the screen picks what is wholly inside. In y-up pixels a clockwise loop has
        # a negative signed area.
        self.window = signed_area(self.points) < 0 if window is None else window

    def contains(self, p):
        inside = False
        pts = self.points
        j = len(pts) - 1
        for i in range(len(pts)):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if (yi > p[1]) != (yj > p[1]):
                x = xi + (p[1] - yi) * (xj - xi) / (yj - yi)
                if p[0] < x:
                    inside = not inside
            j = i
        return inside

    def crosses(self, p, q):
        if self.contains(p) or self.contains(q):
            return True
        pts = self.points
        return any(_segments_cross(p, q, pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))

    def centre(self):
        n = float(len(self.points))
        return (sum(p[0] for p in self.points) / n, sum(p[1] for p in self.points) / n)


def signed_area(points):
    s = 0.0
    for i in range(len(points)):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % len(points)]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def _segments_cross(a, b, c, d):
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    d1, d2 = side(c, d, a), side(c, d, b)
    d3, d4 = side(a, b, c), side(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


# --------------------------------------------------------------------------- what can be picked
def _parents(obj):
    out = []
    parent = obj.getParentGeoFeatureGroup()
    while parent is not None:
        out.insert(0, parent)
        parent = parent.getParentGeoFeatureGroup()
    return out


def _shown(doc):
    """(object, global shape) of what is shown: body tips and plain Part features, not sketches,
    datums or anything inside a hidden Body or App::Part."""
    import Part
    out = []
    for obj in doc.Objects:
        try:
            if obj.TypeId in ("PartDesign::Body", "App::Part") or not obj.isDerivedFrom("Part::Feature"):
                continue
            if any(obj.isDerivedFrom(t) for t in SKIP):
                continue
            if obj.ViewObject is None or not obj.ViewObject.isVisible():
                continue
            parents = _parents(obj)
            if any(not p.Visibility for p in parents):
                continue
            shape = Part.getShape(obj)
            if parents:
                outer = obj.getGlobalPlacement().multiply(obj.Placement.inverse())
                if not outer.isIdentity():
                    shape = shape.copy()
                    shape.Placement = outer.multiply(shape.Placement)
        except Exception:
            continue
        if shape is not None and not shape.isNull() and (shape.Edges or shape.Vertexes):
            out.append((obj, shape))
    return out


def _wanted():
    """The kinds a box picks: edges, or what the Selection Filter lets through."""
    try:
        from . import selfilter
        s = selfilter.state()
        if s.filtering():
            allowed = s.allowed_kinds()
            return {k for k in ("vertex", "edge", "face") if k in allowed} | \
                ({"body"} if allowed & {"solid_body", "surface_body"} else set())
    except Exception as _fw_err:
        _fw_log("boxselect.py:185", _fw_err)
    return {"edge"}


def _draw_style():
    try:
        from . import hlv
        if hlv.mode():
            return hlv.mode()
    except Exception as _fw_err:
        _fw_log("boxselect.py:195", _fw_err)
    try:
        for i, action in enumerate(Gui.Command.get("Std_DrawStyle").getAction()):
            if action.isChecked():
                return {WIREFRAME: "wireframe", HIDDEN_LINE: "hlr"}.get(i, "shaded")
    except Exception as _fw_err:
        _fw_log("boxselect.py:201", _fw_err)
    return "shaded"


def hidden_allowed():
    p = paths.params()
    if _draw_style() in ("wireframe", "hlv"):
        return p.GetBool(HIDDEN_WIREFRAME, True)
    return p.GetBool(HIDDEN_SHADED, False)


class Picker:
    """Works out what a region picks in a view."""

    def __init__(self, view, hidden_ok):
        self.view = view
        self.hidden_ok = hidden_ok
        self.dir = App.Vector(view.getViewDirection())
        try:
            a, b = view.getPoint((0, 0)), view.getPoint((3, 0))
            self.tol = max((b - a).Length, 1e-6)    # three pixels in the model
        except Exception:
            self.tol = 0.05
        self.picks = 0

    def screen(self, p):
        x, y = self.view.getPointOnViewport(p)
        return (float(x), float(y))

    def info(self, xy):
        self.picks += 1
        try:
            return self.view.getObjectInfo((int(round(xy[0])), int(round(xy[1]))))
        except Exception:
            return None

    def seen(self, p, xy=None):
        """Nothing nearer the eye than the point, at its spot on the screen."""
        if self.hidden_ok:
            return True
        info = self.info(xy or self.screen(p))
        if info is None:
            return True
        hit = App.Vector(info["x"], info["y"], info["z"])
        return (hit - p).dot(self.dir) > -self.tol - 1e-3 * max(p.Length, 1.0)

    @staticmethod
    def polyline(edge):
        try:
            straight = type(edge.Curve).__name__ in ("Line", "LineSegment")
            return edge.discretize(Number=2 if straight else 33)
        except Exception:
            return [v.Point for v in edge.Vertexes]

    def edge(self, edge, region):
        pts = self.polyline(edge)
        if len(pts) < 2:
            return False
        xy = [self.screen(p) for p in pts]
        if region.window:
            if not all(region.contains(q) for q in xy):
                return False
            samples = self._along(edge)
        else:
            if not any(region.crosses(xy[i], xy[i + 1]) for i in range(len(xy) - 1)):
                return False
            samples = [p for p in self._along(edge, 9) if region.contains(self.screen(p))] or \
                [pts[i] for i in range(len(pts)) if region.contains(xy[i])] or self._along(edge)
        return any(self.seen(p) for p in samples[:6])

    @staticmethod
    def _along(edge, count=5):
        try:
            a, b = edge.FirstParameter, edge.LastParameter
            return [edge.valueAt(a + (b - a) * (i + 0.5) / count) for i in range(count)]
        except Exception:
            return [v.Point for v in edge.Vertexes]

    def vertex(self, vertex, region):
        p = vertex.Point
        xy = self.screen(p)
        return region.contains(xy) and self.seen(p, xy)

    def face(self, face, name, obj, region):
        edges = face.Edges
        xy_lines = [[self.screen(p) for p in self.polyline(e)] for e in edges]
        if region.window:
            if not all(region.contains(q) for line in xy_lines for q in line):
                return False
        else:
            touched = any(region.crosses(line[i], line[i + 1]) for line in xy_lines for i in range(len(line) - 1))
            if not touched:
                info = self.info(region.centre())        # the region lies inside the face
                return info is not None and self._is(info, obj, name)
        if self.hidden_ok:
            return True
        for p in self._inside(face):
            xy = self.screen(p)
            if not region.window and not region.contains(xy):
                continue
            info = self.info(xy)
            if info is not None and self._is(info, obj, name):
                return True
        return False

    @staticmethod
    def _inside(face, count=5):
        """Points well inside the face (a pick at an edge or a corner names the edge or vertex)."""
        out = []
        try:
            u0, u1, v0, v1 = face.ParameterRange
            for i in range(count):
                for j in range(count):
                    u = u0 + (u1 - u0) * (i + 0.5) / count
                    v = v0 + (v1 - v0) * (j + 0.5) / count
                    if face.isPartOfDomain(u, v):
                        out.append(face.valueAt(u, v))
        except Exception as _fw_err:
            _fw_log("boxselect.py:319", _fw_err)
        return out[:16]

    @staticmethod
    def _is(info, obj, name):
        return info.get("Object") == obj.Name and info.get("Component") == name

    def items(self, doc, region, wanted):
        """[(object, element name)]; an empty name is the whole body."""
        out = []
        for obj, shape in _shown(doc):
            if "body" in wanted:
                if region.window:
                    hit = all(region.contains(self.screen(p)) for e in shape.Edges for p in self.polyline(e)) \
                        and any(self.edge(e, region) for e in shape.Edges)
                else:
                    hit = any(self.edge(e, region) for e in shape.Edges)
                if hit:
                    out.append((obj, ""))
                continue
            if "vertex" in wanted:
                out += [(obj, "Vertex%d" % (i + 1)) for i, v in enumerate(shape.Vertexes) if self.vertex(v, region)]
            if "edge" in wanted:
                out += [(obj, "Edge%d" % (i + 1)) for i, e in enumerate(shape.Edges) if self.edge(e, region)]
            if "face" in wanted:
                out += [(obj, "Face%d" % (i + 1)) for i, f in enumerate(shape.Faces)
                        if self.face(f, "Face%d" % (i + 1), obj, region)]
        return out


def apply(doc, items, mode):
    """mode: 'replace', 'add' (Shift) or 'toggle' (Ctrl)."""
    if mode == "replace":
        Gui.Selection.clearSelection()
    for obj, sub in items:
        parents = _parents(obj)
        top = parents[0] if parents else obj
        path = ".".join([p.Name for p in parents[1:]] + [obj.Name]) + "." if parents else ""
        full = path + sub
        try:
            if mode == "toggle" and Gui.Selection.isSelected(top, full):
                Gui.Selection.removeSelection(doc.Name, top.Name, full)
            else:
                Gui.Selection.addSelection(doc.Name, top.Name, full)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: box selection: %s\n" % error)


def select_region(view, region, mode="replace"):
    """Picks what the region (view pixels, y up) takes; returns the items."""
    gdoc = Gui.ActiveDocument
    if gdoc is None:
        return []
    picker = Picker(view, hidden_allowed())
    items = picker.items(gdoc.Document, region, _wanted())
    apply(gdoc.Document, items, mode)
    return items


# --------------------------------------------------------------------------- the box on the screen
class Band(QtWidgets.QWidget):
    """The box or loop, painted over the 3D view; it never takes the mouse."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SWBoxSelectionBand")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.points = []
        self.lasso = False
        self.window = True

    def update_shape(self, points, lasso, window):
        self.points, self.lasso, self.window = points, lasso, window
        self.setGeometry(self.parentWidget().rect())
        if not self.isVisible():
            self.show()
            self.raise_()
        self.update()

    def paintEvent(self, event):
        if len(self.points) < 2:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, self.lasso)
        colour = WINDOW if self.window else CROSSING
        pen = QtGui.QPen(colour, 1)
        pen.setStyle(Qt.SolidLine if self.window else Qt.DashLine)
        painter.setPen(pen)
        fill = QtGui.QColor(colour)
        fill.setAlpha(28)
        painter.setBrush(fill)
        if self.lasso:
            painter.drawPolygon(QtGui.QPolygonF(self.points))
        else:
            painter.drawRect(QtCore.QRectF(self.points[0], self.points[-1]).normalized())
        painter.end()


# --------------------------------------------------------------------------- the mouse

def _slicer_plate_shown():
    """True while the Orca/Bambu panel shows its build plate in the 3D view."""
    try:
        from . import slicerui
        panel = slicerui.SlicerPanel.current
        return panel is not None and panel.bed.shown()
    except Exception:
        return False


class BoxSelect(QtCore.QObject):
    """Watches the left button on the active 3D view's viewport."""

    def __init__(self, shell):
        super().__init__(shell.window)
        self.over_geometry = False     # T: the next drag may start on the model
        self.shell = shell
        self.mw = shell.window
        self.state = IDLE
        self._press = None           # (widget, local, global, modifiers) of a held-back press
        self._replaying = False
        self._native = False         # FreeCAD's Box Selection runs: leave the next drag to it
        self._shift = None           # a Shift+click on the model: "ctrl" (sent on as Ctrl) or "keep"
        self.band = None
        self.path = []               # QPointF, widget coordinates
        self._watched = []
        # for checks
        self.drags = 0
        self.last_items = []
        self.last_window = None
        self.last_lasso = None
        self.mdi = self.mw.findChild(QtWidgets.QMdiArea)
        if self.mdi is not None:
            self.mdi.subWindowActivated.connect(self.attach)
        QtCore.QTimer.singleShot(0, self.attach)
        QtCore.QTimer.singleShot(0, self._hook_native)

    def attach(self, *args):
        self._watched = [w for w in self._watched if alive(w)]
        view = self.shell.view_widget()
        if view is None or not alive(view) or not hasattr(view, "viewport"):
            return
        widget = view.viewport()
        if widget is None:
            return
        widget.installEventFilter(self)
        if widget not in self._watched:
            self._watched.append(widget)

    def remove(self):
        self._end()
        for widget in self._watched:
            if alive(widget):
                widget.removeEventFilter(self)
        self._watched = []

    def _hook_native(self):
        for name in NATIVE:
            try:
                for action in Gui.Command.get(name).getAction():
                    action.triggered.connect(self._native_started)
            except Exception as _fw_err:
                _fw_log("boxselect.py:471", _fw_err)

    def _native_started(self, *args):
        self._native = True

    # ------------------------------------------------------------------ when
    def usable(self, widget):
        if not getattr(self.shell, "enabled", True) or self._native:
            return False
        if _slicer_plate_shown():
            return False        # the 3D Slicer plate: its objects are not document objects, a press on one is a
                                # pick / drag of the plate (the slicers' own mouse), never the start of a box
        if App.ParamGet(VIEW).GetString("NavigationStyle", "") != NAVIGATION:
            return False
        if widget.cursor().shape() in (Qt.BitmapCursor, Qt.CrossCursor):
            return False             # a FreeCAD tool or its own box is running
        try:
            from . import contextbar
            if contextbar.sketch_in_edit() is not None:

                return bulk() == "Lasso" and Gui.ActiveDocument is not None
        except Exception as _fw_err:
            _fw_log("boxselect.py:490", _fw_err)
        return Gui.ActiveDocument is not None

    @staticmethod
    def _view():
        try:
            view = Gui.ActiveDocument.ActiveView
        except Exception:
            return None
        return view if hasattr(view, "getObjectInfo") else None

    def _xy(self, widget, pos):
        """Widget coordinates to view pixels (y up)."""
        dpr = widget.devicePixelRatioF()
        view = self._view()
        height = view.getSize()[1] if view is not None else widget.height() * dpr
        return (pos.x() * dpr, height - pos.y() * dpr - 1)

    def _empty(self, widget, pos):
        view = self._view()
        if view is None:
            return False
        try:
            x, y = self._xy(widget, pos)
            return view.getObjectInfo((int(round(x)), int(round(y)))) is None
        except Exception:
            return False

    # ------------------------------------------------------------------ events
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if self._replaying:
            return False
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() != Qt.LeftButton:
                if self.state != IDLE:
                    self._end()
                    return True
                return False
            if self.state != IDLE:
                self._end()          # a release went missing
            mods = event.modifiers() & ~Qt.KeypadModifier
            if event.buttons() != Qt.LeftButton or mods & ~(Qt.ShiftModifier | Qt.ControlModifier):
                return False
            if self._filtered_pick(obj, event, mods):
                return True
            if mods == Qt.ShiftModifier and self._shift_pick(obj, event):
                return True
            over = self.over_geometry
            if not self.usable(obj) or _on_handle(event) or _on_dragger(obj, event) or _on_flex_plane(obj, event) \
                    or (not over and not self._empty(obj, event.position())):
                return False
            self.over_geometry = False          # Select over Geometry (T) is for the one drag
            self._press = (obj, QtCore.QPointF(event.position()), QtCore.QPointF(event.globalPosition()), mods)
            self.state = PRESSED
            return True
        if t == QtCore.QEvent.MouseMove:
            if self.state == IDLE:
                if event.buttons() == Qt.NoButton:
                    self._filtered_hover(obj, event)
                return False
            if not event.buttons() & Qt.LeftButton:
                if self.state == PRESSED:
                    self._replay()
                self._end()
                return False
            pos = QtCore.QPointF(event.position())
            if self.state == PRESSED:
                d = pos - self._press[1]
                if math.hypot(d.x(), d.y()) < START:
                    return True
                self._begin()
            self._track(pos)
            return True
        if t == QtCore.QEvent.MouseButtonRelease:
            if event.button() == Qt.LeftButton and self._shift is not None:
                how, self._shift = self._shift, None
                if how == "ctrl":
                    self._send(obj, event, QtCore.QEvent.MouseButtonRelease, Qt.NoButton)
                return True
            if event.button() == Qt.LeftButton:
                self._native = False         # FreeCAD's own box ends with this release
            if self.state == IDLE:
                return False
            if event.button() != Qt.LeftButton:
                return True
            state = self.state
            if state == PRESSED:
                self._replay()               # a click: FreeCAD gets its press, then this release
                self.state = IDLE
                self._press = None
                return False
            self._track(QtCore.QPointF(event.position()))
            self._finish(event.modifiers())
            return True
        if t == QtCore.QEvent.MouseButtonDblClick:
            return self.state == DRAGGING
        return False

    def _shift_pick(self, widget, event):
        ""


        if not self.usable(widget):
            return False
        try:
            from . import contextbar
            if contextbar.sketch_in_edit() is not None or Gui.ActiveDocument.getInEdit() is not None:
                return False
        except Exception as _fw_err:
            _fw_log("boxselect.py:shift", _fw_err)
            return False
        view = self._view()
        if view is None:
            return False
        try:
            x, y = self._xy(widget, event.position())
            info = view.getObjectInfo((int(round(x)), int(round(y))))
        except Exception:
            info = None
        if not info:
            return False                  # empty space: Shift starts an adding box
        self._shift = "keep" if self._picked(info) else "ctrl"
        if self._shift == "ctrl":
            self._send(widget, event, QtCore.QEvent.MouseButtonPress, Qt.LeftButton)
        return True

    def _nearest_allowed(self, widget, pos):
        """(index, info, subname) of the nearest item under pos that the Selection Filter lets
        through, or None (no filter on, nothing allowed, a sketch or feature in edit)."""
        try:
            from . import selfilter
            if not selfilter.state().filtering():
                return None
        except Exception:
            return None
        if not self.usable(widget):
            return None
        try:
            from . import contextbar
            if contextbar.sketch_in_edit() is not None or Gui.ActiveDocument.getInEdit() is not None:
                return None
        except Exception:
            return None
        view = self._view()
        if view is None:
            return None
        try:
            x, y = self._xy(widget, pos)
            infos = view.getObjectsInfo((int(round(x)), int(round(y)))) or []
        except Exception:
            return None
        for i, info in enumerate(infos):
            try:
                # SubName runs from ParentObject (the top object, a Body) down to the element
                top = info.get("ParentObject")
                if top is not None and info.get("SubName"):
                    sub = info["SubName"]
                else:
                    top = App.getDocument(info["Document"]).getObject(info["Object"])
                    sub = info.get("Component", "")
                if selfilter.allows(top, sub):
                    return (i, dict(info, Top=top.Name), sub)
            except Exception:
                continue
        return None

    def _filtered_hover(self, widget, event):
        ""


        found = self._nearest_allowed(widget, event.position())
        if found is None or found[0] == 0:
            return
        _i, info, sub = found
        key = (info["Document"], info["Top"], sub)

        def show(key=key, info=info):
            try:
                hover = getattr(self.shell, "face_hover", None)
                if hover is not None and hover.on():
                    if hover.key != key:
                        hover.preselected(*key)
                    else:
                        hover.seen = True
                    return
                obj = App.getDocument(key[0]).getObject(key[1])
                Gui.Selection.setPreselection(obj, key[2], info.get("x", 0.0), info.get("y", 0.0), info.get("z", 0.0))
            except Exception as _fw_err:
                _fw_log("boxselect.py:hover", _fw_err)
        QtCore.QTimer.singleShot(0, show)

    def _filtered_pick(self, widget, event, mods):
        ""


        found = self._nearest_allowed(widget, event.position())
        if found is None or found[0] == 0:
            return False                 # nothing better behind, or the nearest is fine: FreeCAD picks
        _i, info, sub = found
        doc, name = info["Document"], info["Top"]
        point = (info.get("x", 0.0), info.get("y", 0.0), info.get("z", 0.0))
        try:
            if mods & Qt.ControlModifier and Gui.Selection.isSelected(App.getDocument(doc).getObject(name), sub):
                Gui.Selection.removeSelection(doc, name, sub)
            else:
                if not mods & (Qt.ControlModifier | Qt.ShiftModifier):
                    Gui.Selection.clearSelection()
                Gui.Selection.addSelection(doc, name, sub, *point)
        except Exception as _fw_err:
            _fw_log("boxselect.py:filtered", _fw_err)
            return False
        self._shift = "keep"             # the release that goes with this press is ours too
        return True

    @staticmethod
    def _picked(info):
        comp = info.get("Component", "") or ""
        name = info.get("Object", "")
        for s in Gui.Selection.getSelectionEx("", 0):
            names = [n.split(".")[-1] if n else "" for n in s.SubElementNames] or [""]
            if comp.split(".")[-1] not in names:
                continue
            path = [s.ObjectName] + [n for sub in s.SubElementNames for n in sub.split(".")[:-1]]
            if name in path:
                return True
        return False

    def _send(self, widget, event, kind, buttons):
        mods = (event.modifiers() & ~Qt.ShiftModifier) | Qt.ControlModifier
        e = QtGui.QMouseEvent(kind, QtCore.QPointF(event.position()), QtCore.QPointF(event.globalPosition()),
                              Qt.LeftButton, buttons, mods)
        self._replaying = True
        try:
            QtWidgets.QApplication.sendEvent(widget, e)
        finally:
            self._replaying = False

    def _replay(self):
        press, self._press = self._press, None
        if press is None:
            return
        widget, local, glob, mods = press
        if not alive(widget):
            return
        event = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, local, glob, Qt.LeftButton, Qt.LeftButton, mods)
        self._replaying = True
        try:
            QtWidgets.QApplication.sendEvent(widget, event)
        finally:
            self._replaying = False

    def _begin(self):
        widget = self._press[0]
        self.state = DRAGGING
        self.lasso = bulk() == "Lasso"
        self.path = [self._press[1]]
        if self.band is None or not alive(self.band) or self.band.parentWidget() is not widget:
            if self.band is not None and alive(self.band):
                self.band.deleteLater()
            self.band = Band(widget)
        try:
            Gui.Selection.removePreselection()
        except Exception as _fw_err:
            _fw_log("boxselect.py:606", _fw_err)

    def _region(self, widget):
        pts = [self._xy(widget, p) for p in self.path]
        if self.lasso:
            return Loop(pts) if len(pts) >= 3 else None
        return Rect(pts[0], pts[-1])

    def _track(self, pos):
        if self.state != DRAGGING:
            return
        if self.lasso:
            if (pos - self.path[-1]).manhattanLength() >= 2:
                self.path.append(pos)
        else:
            self.path = [self.path[0], pos]
        widget = self._press[0]
        region = self._region(widget)
        window = True if region is None else region.window
        self.band.update_shape(list(self.path), self.lasso, window)
        _status(T_WINDOW if window else T_CROSSING)

    def _finish(self, mods):
        widget = self._press[0]
        region = self._region(widget)
        mode = "toggle" if mods & Qt.ControlModifier else "add" if mods & Qt.ShiftModifier else "replace"
        self._end()
        view = self._view()
        if region is None or view is None:
            return
        self.drags += 1
        self.last_window, self.last_lasso = region.window, isinstance(region, Loop)
        try:
            from . import contextbar
            sketch = contextbar.sketch_in_edit()
        except Exception:
            sketch = None
        try:
            self.last_items = select_sketch_region(view, sketch, region, mode) if sketch is not None \
                else select_region(view, region, mode)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: box selection: %s\n" % error)

    def _end(self):
        if self.state == DRAGGING:
            _status("")
        self.state = IDLE
        self._press = None
        if self.band is not None and alive(self.band):
            self.band.hide()


T_WINDOW = "Picking what lies wholly inside the box."
T_CROSSING = "Picking what lies inside the box or crosses it."


def _status(text):
    ""

    try:
        bar = Gui.getMainWindow().statusBar()
        if text:
            if bar.currentMessage() != text:
                bar.showMessage(text)
        elif bar.currentMessage() in (T_WINDOW, T_CROSSING):
            bar.clearMessage()
    except Exception as _fw_err:
        _fw_log("boxselect.py:673", _fw_err)


def select_sketch_region(view, sketch, region, mode="replace"):
    ""



    pl = sketch.getGlobalPlacement()

    def screen(p):
        x, y = view.getPointOnViewport(pl.multVec(p))[:2]
        return (float(x), float(y))

    names = []
    for i, geo in enumerate(sketch.Geometry):
        if geo.TypeId == "Part::GeomPoint":
            continue
        try:
            pts = [screen(p) for p in geo.toShape().discretize(24)]
        except Exception:
            continue
        if not pts:
            continue
        if region.window:
            took = all(region.contains(p) for p in pts)
        else:
            took = region.contains(pts[0]) or any(region.crosses(pts[k], pts[k + 1]) for k in range(len(pts) - 1))
        if took:
            names.append("Edge%d" % (i + 1))
    n = 0
    while n < 200000:
        try:
            geo, pos = sketch.getGeoVertexIndex(n)
            if geo == -2000:        # past the last vertex
                break
            point = sketch.getPoint(geo, pos)
        except Exception:
            break
        if region.contains(screen(point)):
            names.append("Vertex%d" % (n + 1))
        n += 1
    try:
        if region.contains(screen(App.Vector(0, 0, 0))):
            names.append("RootPoint")
    except Exception as _fw_err:
        _fw_log("boxselect.py:719", _fw_err)
    doc = sketch.Document.Name
    have = set()
    for ex in Gui.Selection.getSelectionEx(doc):
        if ex.Object == sketch:
            have.update(ex.SubElementNames)
    if mode == "replace":
        Gui.Selection.clearSelection()
        have = set()
    for n in names:
        if mode == "toggle" and n in have:
            Gui.Selection.removeSelection(doc, sketch.Name, n)
        elif n not in have:
            Gui.Selection.addSelection(doc, sketch.Name, n)
    return names


def _on_dragger(widget, event):
    """The press is on a Coin dragger (the assembly's drag handle in Exploded View and FreeCAD's
    own Transform handles): FreeCAD drags it, no box."""
    try:
        from pivy import coin
        view = Gui.ActiveDocument.ActiveView
        if not hasattr(view, "getViewer"):
            return False
        manager = view.getViewer().getSoRenderManager()
        dpr = widget.devicePixelRatioF()
        pos = event.position()
        pick = coin.SoRayPickAction(manager.getViewportRegion())
        pick.setPoint(coin.SbVec2s(int(pos.x() * dpr), int((widget.height() - pos.y()) * dpr)))
        pick.setRadius(4)
        pick.apply(manager.getSceneGraph())
        point = pick.getPickedPoint()
        if point is None:
            return False
        path = point.getPath()
        kind = coin.SoDragger.getClassTypeId()
        return any(path.getNode(i).isOfType(kind) for i in range(path.getLength()))
    except Exception:
        return False


def _on_flex_plane(widget, event):
    """The press is on a Flex trim plane (red or green), which is dragged: no box."""
    try:
        from . import flex
        return flex.on_trim_plane(widget, event)
    except Exception:
        return False


def _on_handle(event):
    """The press is on a handle drawn in the view that is not a document object (Instant3D's
    arrow): that drag is not a box."""
    try:
        from . import instant3d
        if hasattr(instant3d, "on_any_handle"):
            # the face arrow and the Extrude page's Direction 1/2 arrows alike
            return instant3d.on_any_handle(event)
        i3d = instant3d.INSTANT
        return i3d.sep is not None and i3d.widget is not None and i3d.over_arrow(i3d.coin_pos(event))
    except Exception:
        return False


BOX = None


def _start(tries=[0]):
    global BOX
    from . import shell as shell_module
    sh = shell_module.shell()
    if sh is None or not hasattr(sh, "view_widget"):
        tries[0] += 1
        if tries[0] < 60:
            QtCore.QTimer.singleShot(500, _start)
        return
    if BOX is None:
        BOX = BoxSelect(sh)


# --------------------------------------------------------------------------- Tools > Box / Lasso Selection
class _Command:
    def __init__(self, kind):
        self.kind = kind

    def GetResources(self):
        if self.kind == "Box":
            tip = ("Drag in the graphics area to pick with a box: to the right picks what is wholly "
                   "inside, to the left what the box touches.")
        else:
            tip = ("Drag in the graphics area to pick with a free loop: clockwise picks what is wholly "
                   "inside, counterclockwise what the loop touches.")
        return {"MenuText": "%s Selection" % self.kind, "ToolTip": tip, "Checkable": bulk() == self.kind,
                "CmdType": "ForEdit"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self, checked=True):
        # a checkable command also runs when _sync_commands unticks it: only a tick picks the mode
        # (unticking Box after Lasso was chosen used to set Box straight back)
        if checked is False or _SYNCING:
            return
        set_bulk(self.kind)


_SYNCING = []


def _sync_commands():
    current = bulk()
    _SYNCING.append(True)
    try:
        for kind in ("Box", "Lasso"):
            try:
                for action in Gui.Command.get("SWStyle_%sSelection" % kind).getAction():
                    action.setChecked(kind == current)
            except Exception as _fw_err:
                _fw_log("boxselect.py:838", _fw_err)
    finally:
        _SYNCING.pop()


class _OverGeometry:
    ""

    def GetResources(self):
        return {"MenuText": "Select over Geometry",
                "ToolTip": "The next box or lasso can start on the model instead of on empty space (T)",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        if BOX is not None:
            BOX.over_geometry = True


def register():
    for kind in ("Box", "Lasso"):
        name = "SWStyle_%sSelection" % kind
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(kind))
    if "SWStyle_SelectOverGeometry" not in Gui.listCommands():
        Gui.addCommand("SWStyle_SelectOverGeometry", _OverGeometry())
    try:
        # the tick on Tools > Selection > Box Selection / Lasso Selection (no QAction to read)
        from . import checkstate
        for kind in ("Box", "Lasso"):
            checkstate.register("SWStyle_%sSelection" % kind, lambda k=kind: bulk() == k)
    except Exception as _fw_err:
        _fw_log("boxselect.py:872", _fw_err)
    QtCore.QTimer.singleShot(0, _start)


def menu(parent=None):
    ""
    sub = QtWidgets.QMenu("Selection Tools", parent)
    group = QtGui.QActionGroup(sub)
    for kind in ("Box", "Lasso"):
        action = sub.addAction("%s Selection" % kind)
        action.setCheckable(True)
        action.setChecked(bulk() == kind)
        action.triggered.connect(lambda *a, k=kind: set_bulk(k))
        group.addAction(action)
    return sub
