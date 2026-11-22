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

from . import contextbar, paths

PARAM = "FeatureTip"           # addon parameter (default on)
AXIS_PARAM = "TempAxisHover"
DWELL_MS = 400                 # outside a sketch the tip waits for the pointer to rest
AXIS_COLOUR = (0.1, 0.2, 0.85)
TOL = 1e-6
OFFSET = QtCore.QPoint(14, 18)  # below right of the pointer, clear of the cursor

_tip = None


def enabled():
    return paths.params().GetBool(PARAM, True)


def _same_edge(a, b):
    return abs(a.Length - b.Length) < TOL and (a.CenterOfMass - b.CenterOfMass).Length < TOL


def _same_vertex(a, b):
    return (a.Point - b.Point).Length < TOL


def _same_face(a, b):
    return abs(a.Area - b.Area) < TOL * max(1.0, a.Area) and (a.CenterOfMass - b.CenterOfMass).Length < TOL


def _body_of(obj):
    for parent in obj.InList:
        if parent.isDerivedFrom("PartDesign::Body"):
            return parent
    return None


# vd108 (11-20): the tip used to compare the hovered face with every face of every earlier feature (mass
# properties, and a distance check for faces later cuts had trimmed): on a 200-feature part one hover froze
# FreeCAD for minutes. Now: a bound-box key per element, cached per feature shape, so only boxes that agree are
# compared; the costly "what is left of" check only where a cached box holds the element; and a time
# budget, past which the tip names that feature (or the hovered one) while the cache fills for the next hover.
BUDGET_S = 0.25
_KEYS = {}          # (doc, feature, kind) -> (shape, [(box tuple, item)]); the shape held, compared by isSame
_TAG = __import__("re").compile(r";:H(-?[0-9a-fA-F]+)")


def _box(shape):
    b = shape.BoundBox
    return (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)


def _items(feature, kind):
    """The feature shape's faces (edges, corners) with their bound boxes, cached until the shape changes."""
    shape = feature.Shape
    key = (feature.Document.Name, feature.Name, kind)
    hit = _KEYS.get(key)
    try:
        if hit is not None and hit[0].isSame(shape):
            return hit[1]
    except Exception as _fw_err:
        _fw_log("edgetip.py:same-shape", _fw_err)
    items = getattr(shape, kind + "s" if kind != "Vertex" else "Vertexes")
    out = [[_box(item), item, None, None] for item in items]
    if len(_KEYS) > 600:
        _KEYS.clear()
    _KEYS[key] = (shape, out)
    return out


def _props(shape, kind):
    """What _same_face / _same_edge / _same_vertex compare, worked out once per shape."""
    if kind == "Vertex":
        return (0.0, shape.Point)
    return (shape.Area if kind == "Face" else shape.Length, shape.CenterOfMass)


def _has(feature, shape, kind, box, mine):
    tol = 1e-5
    mine_edges = None
    for entry in _items(feature, kind):
        b = entry[0]
        if not all(abs(x - y) <= tol * max(1.0, abs(x)) for x, y in zip(b, box)):
            continue
        if kind == "Face":
            # a trimmed face (holes cut into it) keeps its box but not its edge count: cheaper than its area
            if entry[3] is None:
                entry[3] = len(entry[1].Edges)
            if mine_edges is None:
                mine_edges = len(shape.Edges)
            if entry[3] != mine_edges:
                continue
        if entry[2] is None:
            entry[2] = _props(entry[1], kind)
        if not mine:
            mine.append(_props(shape, kind))
        my_size, my_centre = mine[0]
        size, centre = entry[2]
        if kind == "Face":
            ok = abs(my_size - size) < TOL * max(1.0, my_size) and (my_centre - centre).Length < TOL
        elif kind == "Edge":
            ok = abs(my_size - size) < TOL and (my_centre - centre).Length < TOL
        else:
            ok = (my_centre - centre).Length < TOL
        if ok:
            return True
    return False


def _named_feature(owner, element, chain):
    """The feature FreeCAD's element name points to (the first tag that is one of the body's features)."""
    try:
        name = owner.Shape.getElementMappedName(element)
        name = name[0] if isinstance(name, (tuple, list)) else name
    except Exception:
        return None
    ids = {}
    for f in chain:
        try:
            ids[f.ID] = f
        except Exception:
            continue
    for m in _TAG.finditer(str(name or "")):
        f = ids.get(abs(int(m.group(1), 16)))
        if f is not None:
            return f
    return None


def feature_of(obj, sub):
    """The feature that made the face, edge or vertex `sub` of `obj` (a body or a feature), or None."""
    import time
    start = time.perf_counter()
    try:
        chain = obj.getSubObjectList(sub)
    except Exception:
        chain = [obj]
    element = sub.rsplit(".", 1)[-1]
    if not element.startswith(("Edge", "Vertex", "Face")):
        return None
    owner = chain[-1] if chain else obj
    if owner.isDerivedFrom("PartDesign::Body"):
        owner = owner.Tip
    if owner is None or not hasattr(owner, "Shape"):
        return None
    try:
        shape = owner.Shape.getElement(element)
    except Exception:
        return None
    body = _body_of(owner)
    if body is None:
        return owner
    kind = element.rstrip("0123456789")
    features = []
    for feature in body.Group:
        if feature is owner:
            break
        if feature.isDerivedFrom("PartDesign::Feature") and not feature.isDerivedFrom("PartDesign::Body"):
            features.append(feature)
    named = _named_feature(owner, element, features)
    box = _box(shape)
    mine = []           # the hovered element's size and centre, worked out at most once
    # the first feature whose shape still has this very element (bound boxes first, cached per shape)
    try:
        for feature in features:
            if time.perf_counter() - start > BUDGET_S:
                return named or owner
            if _has(feature, shape, kind, box, mine):
                return feature
    except Exception as _fw_err:
        _fw_log("edgetip.py:search", _fw_err)
        return named or owner

    # it is what is left of; only items whose cached box holds it get the costly check
    if kind != "Vertex":
        try:
            for feature in features:
                if time.perf_counter() - start > BUDGET_S * 2:
                    return named or owner
                for b, item, _p, _n in _items(feature, kind):
                    if _box_holds(b, box) and _part_of(shape, item):
                        return feature
        except Exception as _fw_err:
            _fw_log("edgetip.py:part", _fw_err)
    return owner


def _box_holds(outer, inner, tol=1e-4):
    return all(outer[i] - tol <= inner[i] for i in range(3)) and all(inner[i] <= outer[i] + tol for i in range(3, 6))


def _samples(shape):
    """Points on the boundary of a face or along an edge: its corners and edge middles."""
    points = [v.Point for v in shape.Vertexes]
    for edge in (shape.Edges if shape.ShapeType == "Face" else [shape]):
        try:
            a, b = edge.ParameterRange
            points.append(edge.valueAt(0.5 * (a + b)))
        except Exception:
            continue
    return points


def _part_of(shape, item):
    ""


    try:
        kind = "Surface" if shape.ShapeType == "Face" else "Curve"
        if type(getattr(shape, kind)).__name__ != type(getattr(item, kind)).__name__:
            return False
        size = "Area" if kind == "Surface" else "Length"
        if getattr(shape, size) > getattr(item, size) * (1 + 1e-6) + TOL:
            return False
        box = item.BoundBox
        box.enlarge(1e-4)
        if not box.isInside(shape.BoundBox):
            return False
        import Part
        return all(item.distToShape(Part.Vertex(p))[0] < 1e-5 for p in _samples(shape))
    except Exception:
        return False


class _Observer:
    def __init__(self, owner):
        self.owner = owner

    def setPreselection(self, doc, obj, sub):
        self.owner.preselected(doc, obj, sub)

    def removePreselection(self, doc, obj, sub):
        self.owner.removed()


def cylinder_axis(obj, sub):
    """(start, end) of the axis of the round face `sub`, a little past both ends of the face,
    or None when it is not a cylinder or cone."""
    try:
        face = obj.getSubObject(sub)
        surface = face.Surface
        if type(surface).__name__ not in ("Cylinder", "Cone"):
            return None
        centre, direction = surface.Center if hasattr(surface, "Center") else surface.Apex, surface.Axis
        heights = [(v.Point - centre).dot(direction) for v in face.Vertexes] or [0.0]
        for edge in face.Edges:
            heights.append((edge.CenterOfMass - centre).dot(direction))
        low, high = min(heights), max(heights)
        extra = max((high - low) * 0.15, 1.0)
        return centre + direction * (low - extra), centre + direction * (high + extra)
    except Exception:
        return None


class _Axis:
    """A blue dash-dot line drawn over the model in the active 3D view."""

    def __init__(self):
        self.root = None
        self.view = None

    def show(self, start, end):
        self.hide()
        try:
            from pivy import coin
            view = Gui.ActiveDocument.ActiveView
            root = coin.SoSeparator()
            root.addChild(coin.SoAnnotation())
            colour = coin.SoBaseColor()
            colour.rgb = AXIS_COLOUR
            style = coin.SoDrawStyle()
            style.lineWidth = 1.5
            style.linePattern = 0xFF18     # long dash, gap, dot
            points = coin.SoCoordinate3()
            points.point.setValues(0, 2, [tuple(start), tuple(end)])
            line = coin.SoLineSet()
            line.numVertices.setValue(2)
            for node in (colour, style, points, line):
                root.addChild(node)
            view.getSceneGraph().addChild(root)
            self.root, self.view = root, view
        except Exception as error:
            App.Console.PrintLog("FreeCAD: temporary axis not drawn: %s\n" % error)

    def hide(self):
        if self.root is not None:
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("edgetip.py:169", _fw_err)
        self.root = self.view = None


class FeatureTip(QtCore.QObject):
    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.text = ""             # the tip showing now, for checks
        self.axis = _Axis()
        self.axis_shown = False    # for checks
        self.pending = None        # (doc, obj, sub) waiting for the pointer to rest
        self.shown = None          # (doc, obj, sub) the tip names now
        self.generation = 0        # counts preselections, so a removal undone at once is ignored
        self.dwell = QtCore.QTimer(self)
        self.dwell.setSingleShot(True)
        self.dwell.setInterval(DWELL_MS)
        self.dwell.timeout.connect(self._rested)
        self.observer = _Observer(self)
        try:
            Gui.Selection.addObserver(self.observer)
        except Exception:
            self.observer = None

    def on(self):
        store = paths.params()
        return bool(store.GetBool("Enabled", True) and enabled() and self.mode() is not None)

    @staticmethod
    def mode():
        """'sketch' while a sketch is open, 'part' while nothing is being edited, else None
        (a feature's PropertyManager is open)."""
        if contextbar.sketch_in_edit() is not None:
            return "sketch"
        try:
            gdoc = Gui.ActiveDocument
            if gdoc is not None and gdoc.getInEdit() is None:
                return "part"
        except Exception as _fw_err:
            _fw_log("edgetip.py:207", _fw_err)
        return None

    def preselected(self, doc, obj, sub):
        self.generation += 1
        key = (doc, obj, sub)
        if self.text and key == self.shown:
            return                 # face hover sets the same face again on every pointer move
        self.dwell.stop()
        self.pending = None
        if not self.on():
            self.hide()
            return
        if self.mode() == "part":
            self.hide()
            self.pending = (doc, obj, sub)
            self.dwell.start()
            return
        self.show(doc, obj, sub)

    def removed(self):
        """FreeCAD dropped the preselection. Face hover drops a face's on purpose and FreeCAD
        sets it again on the next move, so hide only when nothing came back meanwhile."""
        generation = self.generation
        QtCore.QTimer.singleShot(0, lambda: self.generation == generation and _outlined() is None and self.hide())

    def _rested(self):
        if self.pending is not None and self.on():
            # face hover outlines what the pointer is on (an edge by the pointer wins over its
            # face): the tip names that one
            self.show(*(_outlined() or self.pending))
        self.pending = None

    def outline_gone(self):
        """Face hover took its outline away (the pointer left the face or edge): so does the tip."""
        try:
            if Gui.Selection.getPreselection().ObjectName:
                return              # FreeCAD's own preselection (a corner) goes on: its tip stays
        except Exception as _fw_err:
            _fw_log("edgetip.py:gone", _fw_err)
        if self.pending is not None or self.text:
            self.hide()

    def show(self, doc, obj, sub):
        if _handle_busy():
            self.hide()
            return
        sketch = contextbar.sketch_in_edit()
        try:
            o = App.getDocument(doc).getObject(obj)
        except Exception:
            o = None
        if o is None or o is sketch:
            self.hide()
            return
        feature = feature_of(o, sub)
        if feature is None or feature is sketch:
            self.hide()
            return
        self.text = feature.Label
        self.shown = (doc, obj, sub)
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos() + OFFSET, self.text)
        if paths.params().GetBool(AXIS_PARAM, False):
            ends = cylinder_axis(o, sub)
            if ends is not None:
                self.axis.show(*ends)
                self.axis_shown = True

    def hide(self):
        self.dwell.stop()
        self.pending = None
        if self.axis_shown:
            self.axis.hide()
            self.axis_shown = False
        self.shown = None
        if self.text:
            self.text = ""
            QtWidgets.QToolTip.hideText()

    def remove(self):
        self.hide()
        if self.observer is not None:
            try:
                Gui.Selection.removeObserver(self.observer)
            except Exception as _fw_err:
                _fw_log("edgetip.py:277", _fw_err)
            self.observer = None


def _handle_busy():
    try:
        from . import instant3d
        return instant3d.handle_busy()
    except Exception:
        return False


def _outlined():
    """(doc, obj, sub) face hover outlines now, or None. Face hover clears FreeCAD's preselection
    of a face or edge as soon as it is set, which used to take the tip away with it: outside a
    sketch the tip never showed for faces and edges, only for corners."""
    try:
        from . import shell
        hover = getattr(shell.shell(), "face_hover", None)
        return hover.key if hover is not None else None
    except Exception:
        return None


def register():
    global _tip
    if _tip is None:
        _tip = FeatureTip()
    return _tip
