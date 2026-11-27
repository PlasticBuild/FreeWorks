# SPDX-License-Identifier: LGPL-2.1-or-later
""























from . import editobj

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeWorks %s: %s\n" % (site, err))
    except Exception:
        return


import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from . import paths

SETTING = "FlatSelection"
COLOUR = (0.0, 168 / 255.0, 1.0)      # when the setting cannot be read
VIEW = "User parameter:BaseApp/Preferences/View"
FACE_SETTING = "SelectedFaceShaded"
FACE_DEFAULT = 0x0080FFFF
SHADE_LIFT = 168 / 128.0
FILL_OFFSET = 0.5       # the model's faces sit at polygon offset 1: the fill sits in between
# (FreeCAD 1.1 draws the faces at factor 0.2, units 1: a fill at 0.5 / 0.5 sat BEHIND a face seen at a
# slant and never showed; the fill now takes half the model's own offset, read from the scene)
EDGE_WIDTH = 2.5        # picked edge width in pixels
EDGE_DEPTH = 0.9999     # depth range of the edge lines: a hair in front of the model's edges
MAX_FACES = 300
COARSE = 1e6            # tessellate() keeps a finer mesh already on the face: FreeCAD's own


def enabled():
    try:
        return paths.params().GetBool(SETTING, True)
    except Exception:
        return True


def _rgb(packed):
    return ((packed >> 24) & 255) / 255.0, ((packed >> 16) & 255) / 255.0, ((packed >> 8) & 255) / 255.0


def selected_colour():
    ""
    try:
        packed = paths.params().GetUnsigned(FACE_SETTING, FACE_DEFAULT)
        return tuple(min(1.0, c * SHADE_LIFT) for c in _rgb(packed))
    except Exception:
        return COLOUR


def edge_colour():
    """A picked edge: Options > Colors > Selected Item 1 (View SelectionColor), as set."""
    try:
        return _rgb(App.ParamGet(VIEW).GetUnsigned("SelectionColor", 0x53A9FFFF))
    except Exception:
        return COLOUR


def _in_sketch():
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        return edit is not None and editobj.type_id(edit).startswith("Sketcher::")
    except Exception:
        return False


def _suppressed_pick(obj, sub):
    """The picked item (the body's feature a tree pick names, "Body" + "Cylinder.") is suppressed."""
    try:
        target = obj.getSubObject(sub, retType=1) if sub else obj
        return bool(getattr(target if target is not None else obj, "Suppressed", False))
    except Exception:
        return False


_MESHES = {}        # (doc, object, sub, face index) -> (object's own shape, face box, (points, triangles))


def _box_of(face):
    b = face.BoundBox
    return (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)


def _mesh(face, key=None, owner=None):
    """face.tessellate(COARSE), kept per picked face: vd108 (11-20) a click on a 200-feature part re-meshed the
    picked faces on every selection poll (1000 tessellate calls, 3 s for five clicks). Part.getShape hands back a
    new copy each call (new hash), so the key is where the face came from; the object's own shape (held, so its
    address stays its own) and the face's box confirm nothing moved or changed."""
    hit = _MESHES.get(key) if key is not None else None
    if hit is not None and owner is not None:
        try:
            if hit[0].isSame(owner) and max(abs(a - b) for a, b in zip(hit[1], _box_of(face))) < 1e-7:
                return hit[2]
        except Exception as _fw_err:
            _fw_log("flatselect.py:meshkey", _fw_err)
    mesh = face.tessellate(COARSE)
    if key is not None and owner is not None:
        if len(_MESHES) > 1200:
            _MESHES.clear()
        _MESHES[key] = (owner, _box_of(face), mesh)
    return mesh


def _own_shape(obj):
    try:
        shape = obj.Shape
        return None if shape.isNull() else shape
    except Exception:
        return None


def _picked_faces(edges=None):
    """(doc name, world-space face, cache key, object's own shape) for each picked face, at most MAX_FACES + 1. A part or feature
    picked whole (a tree pick) gives all its faces. Picked edges go to the list `edges`, if given."""
    import Part
    out = []
    for doc in App.listDocuments().values():
        try:
            picks = Gui.Selection.getSelectionEx(doc.Name, 0)
        except Exception:
            continue
        for sel in picks:
            obj = sel.Object
            try:
                vo = getattr(obj, "ViewObject", None)
                if vo is not None and not vo.Visibility:
                    continue
            except Exception:
                pass
            for sub in (sel.SubElementNames or ("",)):
                leaf = sub.rsplit(".", 1)[-1]
                if leaf.startswith("Edge") and edges is not None:
                    try:
                        edge = Part.getShape(obj, sub, needSubElement=True)
                        if edge is not None and not edge.isNull() and edge.ShapeType == "Edge":
                            edges.append((doc.Name, edge))
                    except Exception as _fw_err:
                        _fw_log("flatselect.py:edge", _fw_err)
                    continue
                if leaf == "":
                    if _suppressed_pick(obj, sub):
                        continue
                    try:
                        whole = Part.getShape(obj, sub)
                    except Exception as _fw_err:
                        _fw_log("flatselect.py:whole", _fw_err)
                        continue
                    if whole is None or whole.isNull() or not (whole.Solids or whole.Shells):
                        continue                # planes, sketches, axes keep their own looks
                    if len(out) + len(whole.Faces) > MAX_FACES:
                        continue                # too big: FreeCAD's own look
                    own = _own_shape(obj)
                    out.extend((doc.Name, f, (doc.Name, obj.Name, sub, i), own) for i, f in enumerate(whole.Faces))
                    continue
                if not leaf.startswith("Face"):
                    continue
                try:
                    face = Part.getShape(obj, sub, needSubElement=True)
                except Exception as _fw_err:
                    _fw_log("flatselect.py:shape", _fw_err)
                    continue
                if face is not None and not face.isNull() and face.ShapeType == "Face":
                    out.append((doc.Name, face, (doc.Name, obj.Name, sub, 0), _own_shape(obj)))
                if len(out) > MAX_FACES:
                    return out
    return out


class _Observer:
    def __init__(self, owner):
        self.owner = owner

    def addSelection(self, *args):
        self.owner.later()

    def removeSelection(self, *args):
        self.owner.later()

    def setSelection(self, *args):
        self.owner.later()

    def clearSelection(self, *args):
        self.owner.later()


class FlatSelection(QtCore.QObject):
    """The shell owns one; it follows FreeCAD's selection."""

    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        try:
            own = paths.params()
            if own.GetUnsigned(FACE_SETTING, 0) == 0:
                own.SetUnsigned(FACE_SETTING, FACE_DEFAULT)     # shown in Options > Colors
        except Exception as _fw_err:
            _fw_log("flatselect.py:default", _fw_err)
        self.nodes = []             # (root, node)
        self.drawn = 0              # faces drawn by the last update (checks)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.update)
        self.observer = _Observer(self)
        try:
            Gui.Selection.addObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("flatselect.py:observer", _fw_err)
        # a recompute rebuilds the face's mesh: draw again when the document changes
        self._poll = QtCore.QTimer(self)
        self._poll.setInterval(400)
        self._poll.timeout.connect(self._check)
        self._poll.start()
        self._stamp = None

    def later(self):
        self._timer.start()

    def _check(self):
        if not self.nodes and not self._stamp:
            return
        stamp = self._state()
        if stamp != self._stamp:
            self.update()

    @staticmethod
    def _state():
        """What was picked, and the scene stamp for a recompute. The picked object's shape hash was
        here: an assembly builds a new compound of every part each time it is asked, so the hash
        moved at each poll and the highlight was redrawn (the whole view with it) every 0.4 s; 3 to 4
        draws a click on a 300-part assembly against stock's 1 (vd120, 11-21)."""
        try:
            from . import scenestamp
            gen = scenestamp.generation()
        except Exception:
            gen = None
        out = []
        for doc in App.listDocuments().values():
            try:
                for sel in Gui.Selection.getSelectionEx(doc.Name, 0):
                    if gen is None:
                        out.append((doc.Name, sel.Object.Name, tuple(sel.SubElementNames),
                                    str(getattr(sel.Object, "Shape", None) and sel.Object.Shape.hashCode())))
                    else:
                        out.append((doc.Name, sel.Object.Name, tuple(sel.SubElementNames)))
            except Exception:
                continue
        return tuple(out) + (_in_sketch(), gen)

    def clear(self):
        for root, node in self.nodes:
            try:
                root.removeChild(node)
            except Exception as _fw_err:
                _fw_log("flatselect.py:remove", _fw_err)
        self.nodes = []

    _OFFSET = {}

    def _kept_offset(self, view, doc_name):
        """_fill_offset, kept while the scene stamp stays put: searching every node of a 300-part
        assembly took 60 ms at each pick (vd122, 11-21)."""
        root = view.getSceneGraph()
        try:
            from . import scenestamp
            gen = scenestamp.generation()
        except Exception:
            gen = None
        key = (doc_name, gen)
        if gen is None:
            return self._fill_offset(root)
        got = self._OFFSET.get("v")
        if got is not None and got[0] == key:
            return got[1]
        value = self._fill_offset(root)
        self._OFFSET["v"] = (key, value)
        return value

    @staticmethod
    def _fill_offset(root):
        """(factor, units) half way between the model's faces (their polygon offset, the smallest
        found in the view's scene) and its edges (no offset), so the fill shows at any slant while the
        edges stay drawn over it."""
        from pivy import coin
        factor, units = 2 * FILL_OFFSET, 2 * FILL_OFFSET
        try:
            sa = coin.SoSearchAction()
            sa.setType(coin.SoPolygonOffset.getClassTypeId())
            sa.setInterest(coin.SoSearchAction.ALL)
            sa.apply(root)
            paths = sa.getPaths()
            for i in range(paths.getLength()):
                node = paths[i].getTail()
                f, u = node.factor.getValue(), node.units.getValue()
                if node.on.getValue() and f > 0 and u > 0 and node.getName().getString() != "SWFlatSelectionOffset":
                    factor, units = min(factor, f), min(units, u)
        except Exception as _fw_err:
            _fw_log("flatselect.py:offset", _fw_err)
        return 0.5 * factor, 0.5 * units

    def update(self):
        self.clear()
        self.drawn = 0
        self._stamp = self._state()
        if not enabled() or _in_sketch():
            return
        edges = []
        faces = _picked_faces(edges)
        if len(faces) > MAX_FACES:
            faces = []
        if not faces and not edges:
            return
        from pivy import coin
        by_doc = {}
        for name, face, key, own in faces:
            try:
                points, triangles = _mesh(face, key, own)
            except Exception as _fw_err:
                _fw_log("flatselect.py:mesh", _fw_err)
                continue
            if triangles:
                by_doc.setdefault(name, []).append((points, triangles))
        lines_by_doc = {}
        for name, edge in edges:
            try:
                box = edge.BoundBox
                pts = edge.discretize(Deflection=max(1e-4, (box.XLength + box.YLength + box.ZLength) / 3000.0))
            except Exception as _fw_err:
                _fw_log("flatselect.py:line", _fw_err)
                continue
            if len(pts) > 1:
                lines_by_doc.setdefault(name, []).append(pts)
        for name in lines_by_doc:
            by_doc.setdefault(name, [])
        for name, meshes in by_doc.items():
            try:
                gdoc = Gui.getDocument(name)
                views = [v for v in gdoc.mdiViewsOfType("Gui::View3DInventor")] if gdoc is not None else []
            except Exception:
                views = []
            if not views:
                continue
            node = coin.SoSeparator()
            node.setName("SWFlatSelection")
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            light = coin.SoLightModel()
            light.model = coin.SoLightModel.BASE_COLOR
            colour = coin.SoBaseColor()
            colour.rgb.setValue(*selected_colour())
            hints = coin.SoShapeHints()
            hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
            coords = coin.SoCoordinate3()
            faceset = coin.SoIndexedFaceSet()
            points, index = [], []
            for pts, tris in meshes:
                base = len(points)
                points.extend((p.x, p.y, p.z) for p in pts)
                for a, b, c in tris:
                    index.extend((base + a, base + b, base + c, -1))
            for child in (pick, light, colour):
                node.addChild(child)
            if index:
                fill = coin.SoSeparator()
                offset = coin.SoPolygonOffset()
                offset.setName("SWFlatSelectionOffset")
                try:
                    factor, units = self._kept_offset(views[0], name)
                except Exception:
                    factor, units = FILL_OFFSET, FILL_OFFSET
                offset.factor = factor
                offset.units = units
                coords.point.setValues(0, len(points), points)
                faceset.coordIndex.setValues(0, len(index), index)
                for child in (offset, hints, coords, faceset):
                    fill.addChild(child)
                node.addChild(fill)
            strips = lines_by_doc.get(name, [])
            if strips:
                lines = coin.SoSeparator()
                ecol = coin.SoBaseColor()
                ecol.rgb.setValue(*edge_colour())
                lines.addChild(ecol)
                draw = coin.SoDrawStyle()
                try:
                    draw.lineWidth = EDGE_WIDTH * self.shell.window.devicePixelRatioF()
                except Exception:
                    draw.lineWidth = EDGE_WIDTH
                depth = coin.SoDepthBuffer()
                depth.range.setValue(0.0, EDGE_DEPTH)
                lcoords = coin.SoCoordinate3()
                flat = [(p.x, p.y, p.z) for pts in strips for p in pts]
                lcoords.point.setValues(0, len(flat), flat)
                lineset = coin.SoLineSet()
                lineset.numVertices.setValues(0, len(strips), [len(pts) for pts in strips])
                for child in (draw, depth, lcoords, lineset):
                    lines.addChild(child)
                node.addChild(lines)
            for view in views:
                try:
                    root = view.getSceneGraph()
                    root.addChild(node)
                    self.nodes.append((root, node))
                except Exception as _fw_err:
                    _fw_log("flatselect.py:add", _fw_err)
            self.drawn += len(meshes) + len(strips)

    def remove(self):
        self.clear()
        self._timer.stop()
        self._poll.stop()
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("flatselect.py:observer-off", _fw_err)
