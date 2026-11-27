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

from . import contextbar, sketchtoolpm

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/ConvertEntities"
TITLE = "Convert Entities"


def _params():
    return App.ParamGet(PARAMS)


def _index(sub):
    try:
        return int("".join(ch for ch in sub if ch.isdigit())) - 1
    except ValueError:
        return -1


def _edge_name(shape, edge):
    for i, e in enumerate(shape.Edges):
        if e.isSame(edge):
            return "Edge%d" % (i + 1)
    return None


def _normal(sketch):
    return sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))


def _square_to(face, normal):
    """A flat face that lies square to the sketch (parallel to its plane)."""
    try:
        if face.Surface.__class__.__name__ != "Plane":
            return False
        n = face.normalAt(0, 0)
        return abs(abs(n.dot(normal)) - 1.0) < 1e-6
    except Exception as _fw_err:
        _fw_log("convertentities.py:82", _fw_err)
        return False


def _loop_with(face, edge):
    for w in face.Wires:
        if any(e.isSame(edge) for e in w.Edges):
            return w
    return None


def expand(sketch, obj, sub, chain=False, all_inner=True):
    """The element names one pick stands for."""
    import Part
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return []
    i = _index(sub)
    if sub.startswith("Face") and 0 <= i < len(shape.Faces):
        face = shape.Faces[i]
        outer = face.OuterWire
        wires = [outer] + ([w for w in face.Wires if not w.isSame(outer)] if all_inner else [])
        names = [_edge_name(shape, e) for w in wires for e in w.Edges]
        return [n for n in dict.fromkeys(names) if n]
    if sub.startswith("Edge") and 0 <= i < len(shape.Edges):
        if not chain:
            return [sub]
        edge = shape.Edges[i]
        normal = _normal(sketch)
        if shape.Faces:
            for face in shape.ancestorsOfType(edge, Part.Face):
                if _square_to(face, normal):
                    loop = _loop_with(face, edge)
                    if loop is not None:
                        return [n for n in (_edge_name(shape, e) for e in loop.Edges) if n]
            return [sub]
        for group in Part.sortEdges(shape.Edges):        # a sketch or wire: the chain holding the edge
            if any(e.isSame(edge) for e in group):
                return [n for n in (_edge_name(shape, e) for e in group) if n]
        return [sub]
    if sub.startswith("Vertex") and 0 <= i < len(shape.Vertexes):
        return [sub]
    return []


def inner_loops(obj, sub):
    """The edges of a picked face's inner loops."""
    shape = getattr(obj, "Shape", None)
    i = _index(sub)
    if shape is None or not sub.startswith("Face") or not 0 <= i < len(shape.Faces):
        return []
    face = shape.Faces[i]
    outer = face.OuterWire
    names = [_edge_name(shape, e) for w in face.Wires if not w.isSame(outer) for e in w.Edges]
    return [n for n in dict.fromkeys(names) if n]


def _referenced(sketch, obj, sub):
    for o, subs in sketch.ExternalGeometry:
        if o == obj and sub in subs:
            return True
    return False


def plan(sketch, picks, chain=False, all_inner=True):
    """[(object, element)] to convert, without touching the sketch."""
    out = []
    for obj, sub in picks:
        if obj is None or obj == sketch:
            continue
        for name in expand(sketch, obj, sub, chain, all_inner):
            if (obj, name) not in out and not _referenced(sketch, obj, name):
                out.append((obj, name))
    return out


def _copy(sketch, gid, geo):
    """The converted entity tied to external geometry gid; its index, else None."""
    import Part
    import Sketcher
    C = Sketcher.Constraint
    kind = type(geo).__name__
    z = App.Vector(0, 0, 1)
    if kind == "LineSegment":
        if (geo.EndPoint - geo.StartPoint).Length < 1e-7:
            return None
        g = sketch.addGeometry(Part.LineSegment(geo.StartPoint, geo.EndPoint))
        held = sketch.addConstraint([C("Coincident", g, 1, gid, 1), C("Coincident", g, 2, gid, 2)])
    elif kind == "Circle":
        g = sketch.addGeometry(Part.Circle(geo.Center, z, geo.Radius))
        held = sketch.addConstraint([C("Coincident", g, 3, gid, 3), C("Equal", g, gid)])
    elif kind == "ArcOfCircle":
        # a projected arc may run clockwise; the copy runs anticlockwise between the same ends
        c = geo.Center
        a_s = math.atan2(geo.StartPoint.y - c.y, geo.StartPoint.x - c.x)
        a_e = math.atan2(geo.EndPoint.y - c.y, geo.EndPoint.x - c.x)
        ccw = getattr(geo, "Axis", z).z > 0
        lo, hi, p1, p2 = (a_s, a_e, 1, 2) if ccw else (a_e, a_s, 2, 1)
        while hi <= lo:
            hi += 2 * math.pi
        g = sketch.addGeometry(Part.ArcOfCircle(Part.Circle(c, z, geo.Radius), lo, hi))
        # the ends fix the chord; the centre then only moves along the chord's bisector, so one
        # coordinate of it is enough (an Equal radius would let the arc flip across the chord)
        chord = geo.EndPoint - geo.StartPoint
        along_x = abs(chord.y) >= abs(chord.x)       # the bisector runs mostly along x
        held = sketch.addConstraint([C("Coincident", g, 1, gid, p1), C("Coincident", g, 2, gid, p2),
                              C("DistanceX" if along_x else "DistanceY", gid, 3, g, 3, 0.0)])
    elif kind == "Point":
        g = sketch.addGeometry(Part.Point(App.Vector(geo.X, geo.Y, 0)))
        held = sketch.addConstraint(C("Coincident", g, 1, gid, 1))
    else:
        return None
    _name_on_edge(sketch, held)
    return g


# --------------------------------------------------------------------------- not linkable: plain copies
def _local_edges(sketch, edges):
    """Edges moved into the sketch's own coordinates."""
    inv = sketch.getGlobalPlacement().inverse()
    out = []
    for e in edges:
        c = e.copy()
        c.Placement = inv.multiply(c.Placement)
        out.append(c)
    return out


def _flat_geometry(edge):
    """A sketch geometry for an edge lying in (or seen straight down onto) the sketch plane, else None."""
    import Part
    z = App.Vector(0, 0, 1)
    flat = lambda v: App.Vector(v.x, v.y, 0)
    kind = type(edge.Curve).__name__
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    if kind in ("Line", "LineSegment"):
        if (flat(b) - flat(a)).Length < 1e-7:
            return None
        return Part.LineSegment(flat(a), flat(b))
    if kind == "Circle" and abs(abs(edge.Curve.Axis.z) - 1) < 1e-6:
        circ = Part.Circle(flat(edge.Curve.Center), z, edge.Curve.Radius)
        if edge.isClosed():
            return circ
        f, l = edge.ParameterRange
        if edge.Curve.Axis.z < 0:
            f, l = -l, -f
        return Part.ArcOfCircle(circ, f, l)
    try:
        pts = [flat(p) for p in edge.discretize(24)]
        bs = Part.BSplineCurve()
        bs.interpolate(pts)
        return bs
    except Exception as _fw_err:
        _fw_log("convertentities.py:235", _fw_err)
        return None


def add_plain(sketch, edges, construction=False):
    ""

    new = []
    for e in _local_edges(sketch, edges):
        g = _flat_geometry(e)
        if g is None:
            continue
        try:
            new.append(sketch.addGeometry(g, construction))
        except Exception as _fw_err:
            _fw_log("convertentities.py:247", _fw_err)
    return new


def linkable(sketch, obj):
    try:
        return bool(sketch.isExternalAllowed(sketch.Document, obj)) if hasattr(sketch, "isExternalAllowed") else True
    except Exception:
        return True


def binder_for(sketch, obj):
    ""


    body = sketch.getParentGeoFeatureGroup()
    if body is None or not body.isDerivedFrom("PartDesign::Body"):
        return None
    for o in body.Group:
        if o.TypeId == "PartDesign::SubShapeBinder" and getattr(o, "FWExtRefOf", None) is obj:
            return o
    try:
        b = body.newObject("PartDesign::SubShapeBinder", "ExtRef")
        b.Label = "%s ExtRef" % obj.Label
        # FreeCAD's binder reads a feature named on its own in its body's coordinates, so a feature of
        # another body with its own placement (or a moved body in the part) came in off by that placement:
        # it is named through its body. An object beside this body (in a part holding it, or the
        # document) is in the right coordinates as it is.
        owner = obj.getParentGeoFeatureGroup()
        holders = []
        up = body.getParentGeoFeatureGroup()
        while up is not None:
            holders.append(up)
            up = up.getParentGeoFeatureGroup()
        if owner is None or owner in holders:
            b.Support = [(obj, ("",))]
        else:
            b.Support = [(owner, (obj.Name + ".",))]
        try:
            b.BindMode = "Synchronized"
        except Exception as _fw_err:
            _fw_log("convertentities.py:275", _fw_err)
        b.addProperty("App::PropertyLink", "FWExtRefOf", "FreeCAD", "The outside object this binder follows")
        b.FWExtRefOf = obj
        try:
            b.Visibility = False
        except Exception as _fw_err:
            _fw_log("convertentities.py:281", _fw_err)
        b.recompute()
        return b
    except Exception as error:
        App.Console.PrintLog("FreeCAD: external reference binder: %s\n" % error)
        return None


def add_external_linked(sketch, obj, name, *flags):
    """addExternal, through a binder when obj is outside the sketch's Body. The object actually
    linked, else None (then the caller makes plain copies)."""
    try:
        sketch.addExternal(obj.Name, name, *flags)
        return obj
    except ValueError as _fw_err:
        _fw_log("convertentities.py:296", _fw_err)
    b = binder_for(sketch, obj)
    if b is None:
        return None
    try:
        sketch.addExternal(b.Name, name, *flags)
        return b
    except Exception as error:
        App.Console.PrintLog("FreeCAD: external via binder: %s\n" % error)
        return None


ON_EDGE_PREFIX = "FWOnEdge_"


def _name_on_edge(sketch, held):
    ""

    indices = list(held) if isinstance(held, (list, tuple)) else [held]
    names = {c.Name for c in sketch.Constraints}
    k = 0
    while any(n.startswith("%s%d_" % (ON_EDGE_PREFIX, k)) for n in names):
        k += 1
    for j, i in enumerate(indices):
        try:
            sketch.renameConstraint(int(i), "%s%d_%d" % (ON_EDGE_PREFIX, k, j))
        except Exception as _fw_err:
            _fw_log("convertentities.py:323", _fw_err)


def convert(sketch, items, origin=None, construction=False):

    """Converts [(object, element)]; returns the new geometry indexes. `origin`, a dict, gets
    {new geometry index: (object, element)}."""
    new = []
    items = list(items)
    try:        # entities of another component, picked together: one in-context reference for them all
        from . import asmextref
        many = asmextref.in_context_many(sketch, items)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Convert Entities in context: %s\n" % error)
        many = None
    if many is not None:
        items = many
    for obj, name in list(items):
        if obj.getParentGeoFeatureGroup() is sketch.getParentGeoFeatureGroup() or obj.Document is not sketch.Document:
            continue
        try:
            from . import asmextref
            via = asmextref.in_context_items(sketch, obj, name)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Convert Entities in context: %s\n" % error)
            via = None
        if via:
            i = items.index((obj, name))
            items[i:i + 1] = via
    for obj, name in items:
        before = len(sketch.ExternalGeo)
        linked = add_external_linked(sketch, obj, name)
        if linked is None:   # outside the Body, no binder: plain
            try:
                el = obj.Shape.getElement(name)
            except Exception as _fw_err:
                _fw_log("convertentities.py:353", _fw_err)
                continue
            for g in add_plain(sketch, el.Edges or [], False):
                new.append(g)
                if origin is not None:
                    origin[g] = (obj, name)
            continue
        sketch.solve()
        after = len(sketch.ExternalGeo)
        if after <= before:
            continue
        for k in range(before, after):
            gid = -(k + 1)
            geo = sketch.ExternalGeo[k]
            if type(geo).__name__ == "Point" and not name.startswith("Vertex"):
                continue                # an edge seen end on: nothing to draw
            g = _copy(sketch, gid, geo)
            if g is not None:
                new.append(g)
                if origin is not None:
                    origin[g] = (obj, name)
                continue
            if type(geo).__name__ == "LineSegment":
                continue                # an edge seen end on: nothing to draw
            # an ellipse or spline: kept as a defining reference instead
            try:
                sketch.delExternal(k - 2)
                # through the object actually linked: a curve outside the Body (Curve Through XYZ Points,
                # Helix/Spiral) is reached through its binder (convspl-fix01)
                sketch.addExternal(linked.Name, name, True)
            except Exception as _fw_err:
                _fw_log("convertentities.py:378", _fw_err)
    if construction:
        for g in new:
            try:
                if not sketch.getConstruction(g):
                    sketch.setConstruction(g, True)
            except Exception as _fw_err:
                _fw_log("convertentities.py:385", _fw_err)
    sketch.solve()
    return new


def _picks_before(sketch):
    out = []
    try:
        selection = Gui.Selection.getSelectionEx()
    except Exception as _fw_err:
        _fw_log("convertentities.py:399", _fw_err)
        return out
    for entry in selection:
        obj = entry.Object
        if obj is None or obj == sketch:
            continue
        for sub in entry.SubElementNames:
            sub = sub.rsplit(".", 1)[-1]
            if sub.startswith(("Edge", "Face", "Vertex")):
                out.append((obj, sub))
    return out


def under_pointer(sketch, view, pos=None):
    """The model element under the pointer, ignoring the open sketch: (object, element) or None."""
    try:
        pos = pos if pos is not None else view.getCursorPos()
        found = view.getObjectsInfo(pos) or []
    except Exception:
        return None
    doc = sketch.Document
    hits = []
    for info in found:
        obj = doc.getObject(info.get("Object", ""))
        try:        # a part edited in an assembly: the pick is in another document (the other component's part)
            other = App.getDocument(info.get("Document", "")) if info.get("Document") else None
            if other is not None and other is not doc:
                obj = other.getObject(info.get("Object", ""))
        except Exception as _fw_err:
            _fw_log("convertentities.py:under_pointer", _fw_err)
        sub = info.get("Component", "") or ""
        if obj is None or obj == sketch or not sub.startswith(("Edge", "Face", "Vertex")):
            continue
        if sub.startswith("Vertex"):
            try:
                from .fwsketch import modelpick as _mp
                sub = _mp.seam_vertex(obj, sub) or sub
            except Exception as _fw_err:
                _fw_log("convertentities.py:seam", _fw_err)
        if getattr(obj, "Visibility", True):
            hits.append((obj, sub))

    for prefix in ("Vertex", "Edge", "Face"):
        for hit in hits:
            if hit[1].startswith(prefix):
                return hit
    return None


def _sketch_preselected(sketch):
    """The open sketch's element under the pointer ('Edge3', 'ExternalEdge1'...), else None."""
    try:
        from . import relationspm
        hit = relationspm.preselected_element(sketch)        # Body-edited sketches too
        if hit is not None:
            sub = hit[0]
            if sub.startswith("Edge") and _index(sub) >= len(sketch.Geometry):
                return None         # left over from geometry taken away under the pointer
            return sub or None
    except Exception as _fw_err:
        _fw_log("convertentities.py:442", _fw_err)
    return None


def _clear_preselection():
    """Geometry taken away under the pointer can stay preselected; the next move finds it again."""
    try:
        Gui.Selection.clearPreselection()
    except Exception as _fw_err:
        _fw_log("convertentities.py:451", _fw_err)


# --------------------------------------------------------------------------- picking in the 3D view
class _Picker(QtCore.QObject):
    """Model picks while the page is open: a click on a model edge, face or vertex (not on the
    sketch's own geometry) goes to the page instead of the sketch."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.pressed = None
        self.widgets = []

    def install(self):
        shell = sketchtoolpm._shell()
        view = shell.view_widget() if shell is not None else None
        if view is None:
            return
        self.widgets = [view] + ([view.viewport()] if hasattr(view, "viewport") and view.viewport() else [])
        for w in self.widgets:
            w.installEventFilter(self)

    def remove(self):
        for w in self.widgets:
            try:
                if sketchtoolpm.alive(w):
                    w.removeEventFilter(self)
            except Exception as _fw_err:
                _fw_log("convertentities.py:480", _fw_err)
        self.widgets = []
        self.page = None

    def _view(self):
        try:
            return Gui.ActiveDocument.ActiveView
        except Exception:
            return None

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter317(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter convertentities.py: %s\n" % exc)
            return False

    def _fw_filter317(self, obj, event):
        page = self.page
        if page is None or not sketchtoolpm.alive(page):
            return False
        t = event.type()
        if t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) \
                or event.button() != QtCore.Qt.LeftButton:
            return False
        if t == QtCore.QEvent.MouseButtonPress:
            self.pressed = None
            pre = _sketch_preselected(page.sketch)
            if pre is not None:
                source = page.source_of(pre)
                if source is None:
                    return False        # the sketch's own geometry: the sketch takes the click
                self.pressed = source   # a converted entity: the click takes its pick out
                return True
            hit = under_pointer(page.sketch, self._view())
            if hit is None:
                return False
            self.pressed = hit
            return True
        if self.pressed is None:
            return False
        hit, self.pressed = self.pressed, None
        QtCore.QTimer.singleShot(0, lambda: page.picked_model(*hit) if sketchtoolpm.alive(page) else None)
        return True


class _ViewOnly(QtCore.QObject):
    """fix300: hands the picker only the events of one view's viewport (an application-level filter)."""

    def __init__(self, picker, viewport):
        super().__init__()
        self.picker, self.viewport = picker, viewport

    def eventFilter(self, obj, event):
        if self.viewport is None or obj is not self.viewport or self.picker.page is None:
            return False
        return self.picker.eventFilter(obj, event)


# --------------------------------------------------------------------------- the page
class ConvertPage(sketchtoolpm.ToolPage):
    TITLE = TITLE
    ICON = "SKETCH_CONVERT_ENTITIES"
    PIXMAP = "Sketcher_Projection"
    TRANSACTION = TITLE

    def build(self):
        p = _params()
        self.picks = []         # (object, element) as picked
        self.extra = []         # inner loop edges added one by one or all at once
        self.made = []
        self.origin = {}        # converted entity: (object, element) it came from
        g = self.group("Entities to Convert")
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWConvertList")
        self.list.setFixedHeight(90)
        self.list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        g.content.addWidget(self.list)
        self.chain = QtWidgets.QCheckBox("Select chain", g.body)
        self.chain.setObjectName("SWConvertSelectChain")
        self.chain.setChecked(p.GetBool("SelectChain", False))
        self.one_by_one = QtWidgets.QCheckBox("Inner loops one by one", g.body)
        self.one_by_one.setObjectName("SWConvertInnerOneByOne")
        self.one_by_one.setChecked(p.GetBool("InnerLoopsOneByOne", False))
        self.all_inner = QtWidgets.QPushButton("Select all inner loops", g.body)
        self.all_inner.setObjectName("SWConvertAllInnerLoops")
        self.all_inner.setFlat(True)

        self.construction = QtWidgets.QCheckBox("Construction geometry", g.body)
        self.construction.setObjectName("SWConvertConstruction")
        self.construction.setChecked(p.GetBool("Construction", False))
        for w in (self.chain, self.one_by_one, self.all_inner, self.construction):
            g.content.addWidget(w)
        self.construction.toggled.connect(self.changed)
        self.chain.toggled.connect(self.changed)
        self.one_by_one.toggled.connect(self.changed)
        self.all_inner.clicked.connect(self._all_inner)
        self.show_note("Select edges, loops, faces or sketch entities to convert.")
        self.picker = _Picker(self)
        self.picker.install()
        # fix300: on the application too, as Mirror's: the sketch's own application-level filters took the
        # press on a model edge first, so FreeCAD selected it and the list stayed empty (Interface run 5)
        self._app_picker = None
        try:
            vp = Gui.ActiveDocument.ActiveView.graphicsView().viewport()
            self._app_picker = _ViewOnly(self.picker, vp)
            QtWidgets.QApplication.instance().installEventFilter(self._app_picker)
        except Exception as _fw_err:
            _fw_log("convertentities.py: app picker", _fw_err)
        self._enable()

    def _faces_with_inner(self):
        return [(o, s) for o, s in self.picks if inner_loops(o, s)]

    def _enable(self):
        # no greyed button: Select all inner loops shows while it has loops to take
        self.all_inner.setEnabled(True)
        self.all_inner.setVisible(self.one_by_one.isChecked() and bool(self._faces_with_inner()))

    def _label(self, obj, sub):
        return "%s@%s" % (sub, obj.Label)

    def _list_menu(self, pos):
        item = self.list.itemAt(pos)
        menu = QtWidgets.QMenu(self.list)
        drop = menu.addAction("Delete")
        drop.setEnabled(item is not None)
        clear = menu.addAction("Clear Selections")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is drop and item is not None:
            del self.picks[self.list.row(item)]
            self._fill()
        elif chosen is clear:
            self.picks = []
            self.extra = []
            self._fill()

    def _fill(self):
        self.list.clear()
        for obj, sub in self.picks:
            self.list.addItem(self._label(obj, sub))
        self.changed()

    def picked_model(self, obj, sub):
        if (obj, sub) in self.picks:
            self.picks.remove((obj, sub))
        else:
            self.picks.append((obj, sub))
        self._fill()

    def picked(self, sub):
        pass

    def selection_changed(self):
        pass

    def _all_inner(self):
        for obj, sub in self._faces_with_inner():
            for name in inner_loops(obj, sub):
                if (obj, name) not in self.picks:
                    self.picks.append((obj, name))
        self._fill()

    def source_of(self, sub):
        """The pick that made the converted entity `sub` ('Edge3'), else None."""
        if not sub.startswith("Edge"):
            return None
        made = self.origin.get(_index(sub))
        if made is None:
            return None
        chain, all_inner = self.chain.isChecked(), not self.one_by_one.isChecked()
        for pick in self.picks:
            if pick == made or (pick[0] == made[0] and made[1] in expand(self.sketch, pick[0], pick[1], chain, all_inner)):
                return pick
        return None

    def changed(self, *args):
        self._enable()
        self.undo_work()
        self.made = []
        self.origin = {}
        items = plan(self.sketch, self.picks, self.chain.isChecked(), not self.one_by_one.isChecked())
        if not items:
            _clear_preselection()
            self.show_note("Select edges, loops, faces or sketch entities to convert." if not self.picks else "")
            return
        self.begin()
        try:
            self.made = convert(self.sketch, items, self.origin, self.construction.isChecked())
        except Exception as error:
            self.undo_work()
            _clear_preselection()
            self.show_note("Could not convert: %s" % error, True)
            return
        sketchtoolpm._refresh(self.sketch)
        _clear_preselection()
        self.show_note("")

    def finish(self):
        p = _params()
        p.SetBool("SelectChain", self.chain.isChecked())
        p.SetBool("InnerLoopsOneByOne", self.one_by_one.isChecked())
        p.SetBool("Construction", self.construction.isChecked())

    def closing(self):
        if getattr(self, "_app_picker", None) is not None:
            try:
                QtWidgets.QApplication.instance().removeEventFilter(self._app_picker)
            except Exception as _fw_err:
                _fw_log("convertentities.py: app picker off", _fw_err)
            self._app_picker = None
        self.picker.remove()


def convert_now(sketch, picks):
    """Picks made before the command: converted at once, one Undo step."""
    p = _params()
    items = plan(sketch, picks, p.GetBool("SelectChain", False), not p.GetBool("InnerLoopsOneByOne", False))
    if not items:
        return []
    doc = sketch.Document
    doc.openTransaction(TITLE)
    try:
        new = convert(sketch, items, None, p.GetBool("Construction", False))
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: Convert Entities: %s\n" % error)
        return []
    doc.commitTransaction()
    Gui.Selection.clearSelection()
    sketchtoolpm._refresh(sketch)
    return new


class ConvertCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_Projection", "MenuText": TITLE,
                "ToolTip": "Converts model edges, faces or other sketches' entities into sketch entities",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return
        picks = _picks_before(sketch)
        if picks and convert_now(sketch, picks):
            return
        sketchtoolpm.open_page(ConvertPage(sketch))


COMMAND = "SWStyle_ConvertEntities"


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, ConvertCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
