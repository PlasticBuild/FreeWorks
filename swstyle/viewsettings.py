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
from PySide import QtCore

SHADOW = "SWStyle_ShadowsInShadedMode"
REALVIEW = "SWStyle_RealViewGraphics"
AMBIENT = "SWStyle_AmbientOcclusion"
REALVIEW_LIGHTS = ("EnableFillLight", "EnableBacklight")
_ao = {}               # id(view) -> _Occlusion
PERSPECTIVE = "SWStyle_PerspectiveToggle"
SHADOW_COLOUR = (0.22, 0.22, 0.25)
SHADOW_TRANSPARENCY = 0.7
LIGHT = (0.3, -0.25)      # how far a flattened copy leans per unit of height (x, y)
SHADOW_BLUR = 0.09       # the wide, soft shadow's spread, as a part of the model's size
SHADOW_DARKEST = 0.65    # the wide shadow's cover under the middle of the model
SHADOW_CONTACT_BLUR = 0.012   # the contact shadow: tight and dark where the model meets the floor
SHADOW_CONTACT_DARKEST = 0.6
SHADOW_CONTACT_HEIGHT = 0.2   # how high above the floor (part of the model's size) still counts as touching it
SHADOW_PIXELS = 256      # the shadow picture's width and height
SHADED_STYLES = (None, 0, 5, 6)   # Std_DrawStyle: As is, Shaded, Flat lines (Shaded With Edges)
POLL_MS = 500
LARGEST = 1e7
NO_SHADOW = ("SWSectionView", "SWSceneBackground", "SWAmbientOcclusion")   # scene nodes drawn over or behind the model, not part of it
CLIPS = ("SWSectionViewClip",)     # the section's clip plane: it cuts the shadow as it cuts the model

_on = {}            # id(view) -> _Shadow


def _view():
    gdoc = Gui.ActiveDocument
    view = gdoc.ActiveView if gdoc is not None else None
    return view if view is not None and hasattr(view, "getSceneGraph") else None


def draw_style_index():
    try:
        actions = Gui.Command.get("Std_DrawStyle").getAction()
    except Exception:
        return None
    for i, act in enumerate(actions):
        try:
            if act.isChecked():
                if i == 6:
                    try:
                        from . import hlv
                        if hlv.shaded():
                            return 5
                    except Exception as _fw_err:
                        _fw_log("viewsettings.py:shaded", _fw_err)
                return i
        except Exception as _fw_err:
            _fw_log("viewsettings.py:60", _fw_err)
    return None


def floor_matrix(z0, lean=LIGHT):
    """The matrix that flattens a point onto the plane z = z0 along the light (Coin row vectors)."""
    from pivy import coin
    dx, dy = lean
    return coin.SbMatrix(1, 0, 0, 0,
                         0, 1, 0, 0,
                         dx, dy, 0, 0,
                         -dx * z0, -dy * z0, z0, 1)


class _Shadow:
    ""





    def __init__(self, view):
        from pivy import coin
        self.view = view
        self.doc = Gui.ActiveDocument.Document
        self.doc_name = self.doc.Name
        self.root = view.getViewer().getSoRenderManager().getSceneGraph()
        self.switch = coin.SoSwitch()
        self.switch.setName("SWFloorShadow")
        sep = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        material = coin.SoMaterial()
        material.diffuseColor = SHADOW_COLOUR
        # a trace of transparency makes Coin blend the square (the picture's cover sets how much);
        # fully opaque, it would only cut the picture at half cover
        material.transparency = 0.002
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING     # seen from either side
        self.texture = coin.SoTexture2()
        self.texture.model = coin.SoTexture2.MODULATE
        self.texture.wrapS = coin.SoTexture2.CLAMP
        self.texture.wrapT = coin.SoTexture2.CLAMP
        self.coords = coin.SoCoordinate3()
        uv = coin.SoTextureCoordinate2()
        uv.point.setValues(0, 4, [(0, 0), (1, 0), (1, 1), (0, 1)])
        binding = coin.SoTextureCoordinateBinding()
        binding.value = coin.SoTextureCoordinateBinding.PER_VERTEX
        face = coin.SoFaceSet()
        face.numVertices.setValue(4)
        for node in (pick, light, material, hints, self.texture, self.coords, uv, binding, face):
            sep.addChild(node)
        holder = _unbounded()       # View Fit frames the model, not its shadow
        holder.addChild(sep)
        # an unseen mark at the floor's height, under the model's own outline: the camera's clipping
        # planes then reach down to the floor (left out, the floor would be cut off seen from above)
        # while View Fit's frame stays the model's
        reach = coin.SoSeparator()
        unseen = coin.SoDrawStyle()
        unseen.style = coin.SoDrawStyle.INVISIBLE
        self.reach = coin.SoCoordinate3()
        reach.addChild(unseen)
        reach.addChild(self.reach)
        reach.addChild(coin.SoPointSet())
        group = coin.SoGroup()
        group.addChild(reach)
        group.addChild(holder)
        self.switch.addChild(group)
        self.root.addChild(self.switch)
        self.signature = None
        self.box = None
        from . import scenestamp
        self.gate = scenestamp.Gate()     # read every shape only when the model or the view moved
        self.timer = QtCore.QTimer()
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def shapes(self):
        """The shown shapes of the document, placed where they show (a body stands for its features,
        a Part container moves what is in it)."""
        out = []
        for obj in self.doc.Objects:
            try:
                if obj.isDerivedFrom("Part::Datum") or not obj.Visibility or not obj.ViewObject.Visibility \
                        or not hasattr(obj, "Shape"):
                    continue
                if obj.isDerivedFrom("App::Part"):
                    continue    # rv29: a Part container (an assembly too): its own Shape is a new compound of what is
                                # in it at every read, and what is in it already casts the shadow
                parent = obj.getParentGeoFeatureGroup()
                if parent is not None and not parent.isDerivedFrom("App::Part"):
                    continue
                if obj.isDerivedFrom("Part::Part2DObject") or obj.Shape.isNull() or not obj.Shape.Faces:
                    continue
                shape = obj.Shape
                place = None
                box = shape.BoundBox
                if parent is not None:
                    if not parent.Visibility:
                        continue
                    # rv29: the Part container's placement is kept beside the shape, not copied into it: a copy
                    # has a new hash at every poll, which repainted the shadow twice a second in any assembly
                    place = parent.getGlobalPlacement()
                    box = box.transformed(place.toMatrix())
                if box.isValid() and box.DiagonalLength < LARGEST:    # leaves out endless planes
                    out.append((obj, shape, place))
            except Exception:
                continue
        return out

    def paint(self, shapes):
        """Paint the outline seen from above, blur it, and lay it on the floor. Returns the floor's
        corners, or None when nothing casts a shadow."""
        import FreeCAD
        shapes = [x if isinstance(x, tuple) else (x, None) for x in shapes]
        box = FreeCAD.BoundBox()
        for shape, place in shapes:
            box.add(shape.BoundBox if place is None else shape.BoundBox.transformed(place.toMatrix()))
        size = max(box.XLength, box.YLength, 1e-6)
        blur = SHADOW_BLUR * max(size, 0.5 * box.ZLength)
        contact_blur = SHADOW_CONTACT_BLUR * max(size, 0.5 * box.ZLength)
        x0, y0 = box.XMin - 3 * blur, box.YMin - 3 * blur
        span = size + 6 * blur
        z0 = box.ZMin - 0.01 * (box.DiagonalLength or 1.0)
        touch = box.ZMin + SHADOW_CONTACT_HEIGHT * max(size, box.ZLength)
        n = SHADOW_PIXELS
        scale = (n - 1) / span
        from PySide import QtGui
        images = []
        for _ in range(2):      # the whole outline, and only what is near the floor
            image = QtGui.QImage(n, n, QtGui.QImage.Format_ARGB32)
            image.fill(QtGui.QColor(0, 0, 0, 0))
            painter = QtGui.QPainter(image)
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(255, 255, 255, 255))
            images.append((image, painter))
        tolerance = max(size / 150.0, 1e-4)
        meshes = _Meshes(lambda local: local.tessellate(tolerance))
        for shape, place in shapes:
            try:
                xyz, triangles = meshes.placed(shape, place)
            except Exception as _fw_err:
                _fw_log("viewsettings.py:tessellate", _fw_err)
                continue
            flat = [QtCore.QPointF((x - x0) * scale, (y - y0) * scale) for x, y, _z in xyz]
            for a, b, c in triangles:
                poly = QtGui.QPolygonF([flat[a], flat[b], flat[c]])
                images[0][1].drawPolygon(poly)
                if min(xyz[a][2], xyz[b][2], xyz[c][2]) <= touch:
                    images[1][1].drawPolygon(poly)
        for _image, painter in images:
            painter.end()

        # wide soft shade around it (the two covers laid one over the other)
        wide = _blurred_alpha(images[0][0], max(1.0, blur * scale), SHADOW_DARKEST)
        near = _blurred_alpha(images[1][0], max(1.0, contact_blur * scale), SHADOW_CONTACT_DARKEST)
        alpha = [255 - (255 - w) * (255 - c) // 255 for w, c in zip(wide, near)]
        rect = _floor_rect(self.doc)
        if rect is not None:        # Edit Scene > Advanced: a floor of its own size ends the shadow at its edges
            centre, u, w, hu, hw = rect
            step = span / (n - 1)
            for j in range(n):
                qy = y0 + j * step - centre.y
                for i in range(n):
                    k = j * n + i
                    if alpha[k]:
                        qx = x0 + i * step - centre.x
                        if abs(qx * u.x + qy * u.y) > hu or abs(qx * w.x + qy * w.y) > hw:
                            alpha[k] = 0
        self.alpha = alpha      # kept for the checks (pivy cannot read a texture back)
        # one byte of grey (white: the material colours it) and one of cover per pixel
        data = bytes(v for a in alpha for v in (255, a))
        from pivy import coin
        self.texture.image.setValue(coin.SbVec2s(n, n), 2, data)
        self.coords.point.setValues(0, 4, [(x0, y0, z0), (x0 + span, y0, z0),
                                           (x0 + span, y0 + span, z0), (x0, y0 + span, z0)])
        self.reach.point.setValues(0, 2, [(box.XMin, box.YMin, z0), (box.XMax, box.YMax, z0)])
        return (x0, y0, span, z0)

    def _alive(self):
        """The document and its view still there: after a close the scene's root is freed, and
        touching it (removeChild) crashes FreeCAD."""
        try:
            if self.doc_name not in App.listDocuments():
                return False
            gdoc = Gui.getDocument(self.doc_name)
            return gdoc is not None and any(v is self.view or v == self.view for v in gdoc.mdiViewsOfType("Gui::View3DInventor"))
        except Exception:
            return False

    def refresh(self):
        if not self._alive():
            self.stop(remove=False)
            return
        try:
            shown = draw_style_index() in SHADED_STYLES
            if shown and not self.gate.due(_floor_key()):
                shown = self.box is not None
            elif shown:
                shapes = self.shapes()
                signature = tuple((obj.Name, shape.hashCode(), str(shape.Placement), str(place))
                                  for obj, shape, place in shapes) + (str(_floor_rect(self.doc)),)
                if signature != self.signature:
                    self.signature = signature
                    self.paints = getattr(self, "paints", 0) + 1
                    self.box = self.paint([(shape, place) for _obj, shape, place in shapes]) if shapes else None
                shown = self.box is not None
            want = 0 if shown else -1
            if self.switch.whichChild.getValue() != want:
                self.switch.whichChild = want
        except Exception as error:
            App.Console.PrintLog("FreeCAD: floor shadow stopped: %s\n" % error)
            self.stop()     # the view or document closed

    def stop(self, remove=True):
        self.timer.stop()
        if remove and self._alive():
            try:
                self.root.removeChild(self.switch)
            except Exception as _fw_err:
                _fw_log("viewsettings.py:160", _fw_err)
        _on.pop(id(self.view), None)


def _floor_key():
    """Edit Scene's floor size settings, so a change repaints the shadow at once."""
    try:
        from . import scenepm
        v = scenepm.settings()
        return tuple(v.get(k) for k in ("autosize", "width", "depth", "floor_turn", "align", "flip", "offset"))
    except Exception as _fw_err:
        _fw_log("viewsettings.py:floorkey", _fw_err)
        return ()


def _floor_rect(doc):
    """Edit Scene > Advanced's floor rectangle, or None for a floor sized from the model."""
    try:
        from . import scenepm
        return scenepm.floor_rect(doc)
    except Exception as _fw_err:
        _fw_log("viewsettings.py:floorrect", _fw_err)
        return None


class _Meshes:
    """Meshes each part once: an assembly's copies of one part (the same geometry placed elsewhere,
    isPartner) share the mesh made in the part's own axes, moved to each copy. Meshing 300 copies one
    by one made Shadows take 4 s and Ambient Occlusion 20 s on a 300-part assembly."""

    def __init__(self, mesher):
        self.mesher = mesher        # local shape (Placement cleared) -> (points, triangles) or a list of them
        self.held = []              # [(shape, local mesh)]

    def local(self, shape):
        for held, mesh in self.held:
            if held.isPartner(shape):
                return mesh
        local = _fresh(shape)
        local.Placement = App.Placement()
        mesh = self.mesher(local)
        self.held.append((shape, mesh))
        return mesh

    def placed(self, shape, place=None, mesh=None):
        """([(x, y, z)], triangles) where the shape shows (place: its container's placement)."""
        points, triangles = mesh if mesh is not None else self.local(shape)
        at = shape.Placement if place is None else place.multiply(shape.Placement)
        return _move([(v.x, v.y, v.z) for v in points] if points and hasattr(points[0], "x") else points, at), triangles


def _move(xyz, place):
    """Points moved by a placement (numpy when there, for the many copies of an assembly)."""
    if not xyz or place.isIdentity():
        return list(xyz)
    m = place.toMatrix()
    try:
        import numpy as np
        a = np.asarray(xyz, dtype=float)
        r = np.array([[m.A11, m.A12, m.A13], [m.A21, m.A22, m.A23], [m.A31, m.A32, m.A33]])
        t = np.array([m.A14, m.A24, m.A34])
        return (a @ r.T + t).tolist()
    except ImportError:
        out = []
        for x, y, z in xyz:
            v = m.multVec(App.Vector(x, y, z))
            out.append((v.x, v.y, v.z))
        return out


def _parts(shape):
    """The solids (else shells / faces) of a shape, compounds opened: an assembly's one compound
    becomes its components' shapes, each with its own placement."""
    if shape.ShapeType == "Compound":
        out = []
        for sub in shape.childShapes():
            out.extend(_parts(sub))
        return out
    return [shape]


def _placed(shape, place):
    """The shape where it shows: moved by its Part container's placement (a copy, the object's own shape is fixed)."""
    if place is None:
        return shape
    shape = shape.copy()
    shape.Placement = place.multiply(shape.Placement)
    return shape


def _blurred_alpha(image, radius, darkest=None):
    """The image's cover (alpha), blurred about radius pixels and scaled to the shadow's darkness,
    row 0 at the floor's low y (where the picture was painted from and the texture starts)."""
    n = image.width()
    darkest = SHADOW_DARKEST if darkest is None else darkest
    try:
        import numpy
        bits = image.constBits()
        raw = numpy.frombuffer(bytes(bits) if not hasattr(bits, "tobytes") else bits.tobytes(), dtype=numpy.uint8)
        a = raw.reshape(n, image.bytesPerLine() // 4, 4)[:, :n, 3].astype(numpy.float32) / 255.0
        r = max(1, int(round(radius / 1.7)))     # three box passes come close to a Gaussian
        for _ in range(3):
            for axis in (0, 1):
                pad = numpy.pad(a, [(r, r) if i == axis else (0, 0) for i in (0, 1)], mode="constant")
                c = numpy.cumsum(pad, axis=axis, dtype=numpy.float32)
                c = numpy.insert(c, 0, 0.0, axis=axis)
                hi = numpy.take(c, numpy.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
                lo = numpy.take(c, numpy.arange(0, n), axis=axis)
                a = (hi - lo) / (2 * r + 1)
        a = numpy.clip(a * darkest * 255.0, 0, 255).astype(numpy.uint8)
        return a.reshape(-1).tolist()
    except Exception as _fw_err:
        _fw_log("viewsettings.py:blur", _fw_err)
    # no numpy: shrink and grow the picture smoothly, which blurs it nearly as well
    small = max(4, int(n / max(2.0, radius)))
    soft = image.scaled(small, small, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation) \
        .scaled(n, n, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
    out = []
    for y in range(n):
        for x in range(n):
            out.append(int(((soft.pixel(x, y) >> 24) & 0xFF) * darkest))
    return out


def _unbounded():
    """A group View Fit leaves out (the shadow is not the model)."""
    from pivy import coin
    try:
        group = coin.SoType.fromName("SoSkipBoundingGroup").createInstance()
        group.getField("mode").setValue(1)          # EXCLUDE_BBOX
        return group
    except Exception as _fw_err:
        _fw_log("viewsettings.py:unbounded", _fw_err)
        return coin.SoGroup()


def shadows_on(view=None):
    view = view or _view()
    return view is not None and id(view) in _on


def set_shadows(on, view=None):
    view = view or _view()
    if view is None:
        return
    if on and id(view) not in _on:
        _on[id(view)] = _Shadow(view)
    elif not on and id(view) in _on:
        _on[id(view)].stop()


def perspective_on(view=None):
    view = view or _view()
    try:
        return view is not None and view.getCameraType() == "Perspective"
    except Exception:
        return False


def perspective_angle():
    ""

    import math
    distance = 2.0
    try:
        from .viewextras import PARAMS
        distance = App.ParamGet(PARAMS).GetFloat("ObserverDistance", 2.0)
    except Exception as _fw_err:
        _fw_log("viewsettings.py:observer", _fw_err)
    return 2 * math.atan(0.5 / max(distance, 0.1))


def set_perspective(on, view=None):
    ""

    view = view or _view()
    if view is None:
        return
    import math
    try:
        before = view.getCameraNode()
        ortho = before.getTypeId().getName() == "OrthographicCamera"
        height = before.height.getValue() if ortho else None
        aim = _aim_point(view, before)
    except Exception as _fw_err:
        _fw_log("viewsettings.py:perspective", _fw_err)
        height, aim = None, None
    view.setCameraType("Perspective" if on else "Orthographic")
    if not on or height is None or aim is None:
        return
    try:
        from pivy import coin
        cam = view.getCameraNode()
        angle = perspective_angle()
        # the plane through the model's middle shows as much as the flat view did
        distance = 0.5 * height / math.tan(0.5 * angle)
        direction = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
        cam.heightAngle = angle
        cam.position = aim - direction * distance
        cam.focalDistance = distance
    except Exception as _fw_err:
        _fw_log("viewsettings.py:perspective2", _fw_err)


def _aim_point(view, cam):
    """The point the camera looks at, at the depth of the model's middle (so the lens does not
    sit inside the model or far behind it)."""
    from pivy import coin
    direction = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
    position = cam.position.getValue()
    focal = position + direction * cam.focalDistance.getValue()
    try:
        action = coin.SoGetBoundingBoxAction(view.getViewer().getSoRenderManager().getViewportRegion())
        action.apply(view.getSceneGraph())
        box = action.getBoundingBox()
        if box.isEmpty():
            return focal
        middle = box.getCenter()
    except Exception:
        return focal
    # slide the focal point along the line of sight to the model's depth
    return focal + direction * (direction.dot(middle - focal))


def realview_on(view=None):
    """RealView Graphics: the faces shaded per pixel with a studio reflection (realview.py)."""
    from . import realview
    return realview.enabled()


def set_realview(on, view=None):
    """The lights stay as the user set them (Lights in the DisplayManager): RealView is the shading."""
    from . import realview
    realview.set_enabled(on)


def ambient_on(view=None):
    view = view or _view()
    return view is not None and id(view) in _ao


AO_RAYS = 12           # rays from each point of the model's surface, over the half sphere it faces
AO_REACH = 0.12        # how far a ray looks for something in the way, as a part of the model's size
AO_DARK = 0.55         # darkest a fully closed-in spot goes (0 none, 1 black)
AO_PART_SPAN = 4.0     # an assembly's rays reach as for a part this many times its middle part's size
AO_POINTS = 8000       # most points baked: a bigger model is meshed more coarsely
AO_SLICE = 0.04        # seconds of baking between pauses, so FreeCAD stays responsive on a big model


class _Occlusion:
    ""




    def __init__(self, view):
        from pivy import coin
        self.view = view
        self.doc_name = Gui.ActiveDocument.Document.Name
        self.root = view.getViewer().getSoRenderManager().getSceneGraph()
        self.switch = coin.SoSwitch()
        self.switch.setName("SWAmbientOcclusion")
        self.root.addChild(self.switch)
        self.key = None
        self.job = None
        from . import scenestamp
        self.gate = scenestamp.Gate()
        self.timer = QtCore.QTimer()
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def _alive(self):
        return _Shadow._alive(self)

    def _solids(self):
        doc = App.getDocument(self.doc_name)
        out = []
        for obj in doc.Objects:
            try:
                if obj.isDerivedFrom("Part::Datum") or obj.getParentGeoFeatureGroup() is not None \
                        or not obj.Visibility or not obj.ViewObject.Visibility or obj.Shape.isNull() \
                        or not obj.Shape.Faces:
                    continue
                if obj.Shape.BoundBox.DiagonalLength < LARGEST:
                    out.append(obj)
            except Exception:
                continue
        return out

    def refresh(self):
        if not self._alive():
            self.stop(remove=False)
            return
        try:
            if self.key is not None and not self.gate.due():
                solids = None          # nothing moved since the last look: keep the skin (or the bake going)
            else:
                solids = self._solids()
            key = self.key if solids is None else tuple(_shape_key(o) for o in solids)
            if key != self.key:
                self.key = key
                self.start(solids)
            shown = draw_style_index() in SHADED_STYLES
            want = 0 if shown and self.switch.getNumChildren() else -1
            if self.switch.whichChild.getValue() != want:
                self.switch.whichChild = want
        except Exception as error:
            App.Console.PrintLog("FreeCAD: ambient occlusion stopped: %s\n" % error)
            self.stop()

    def start(self, solids):
        """Mesh the model and bake it a chunk at a time (the old skin stays until the new one is done)."""
        import math
        self.job = None
        if not solids:
            self.switch.removeAllChildren()
            return
        box = App.BoundBox()
        for o in solids:
            box.add(o.Shape.BoundBox)
        diag = box.DiagonalLength or 1.0
        deviation = max(diag * 0.004, 0.05)
        before = None
        parts = [part for o in solids for part in _parts(o.Shape)]
        while True:
            pts, tris, nrm, spans = [], [], [], []
            meshes = _Meshes(lambda local, d=deviation: _face_meshes(local, d))
            if True:
                for part in parts:
                    rot = part.Placement.Rotation
                    for p, t, n0 in meshes.local(part):
                        moved, _t = meshes.placed(part, None, (p, t))
                        base = len(pts)
                        spans.append((base, base + len(moved)))
                        pts.extend(tuple(v) for v in moved)
                        for v in n0:
                            w = rot.multVec(App.Vector(*v))
                            nrm.append([w.x, w.y, w.z])
                        tris.extend((base + i, base + j, base + k) for i, j, k in t)
            if len(pts) <= AO_POINTS or deviation > diag * 0.05 or (before and len(pts) > 0.8 * before):
                break           # small enough, as coarse as it may get, or coarser no longer helps (many small faces)
            before = len(pts)
            deviation *= min(4.0, max(2.0, (len(pts) / float(AO_POINTS)) ** 0.5))     # fewer meshing rounds
        for m in nrm:
            size = math.sqrt(m[0] * m[0] + m[1] * m[1] + m[2] * m[2]) or 1.0
            m[0] /= size
            m[1] /= size
            m[2] /= size
        turn = math.pi * (3 - math.sqrt(5))
        rays = []
        for i in range(AO_RAYS):      # a spiral over the half sphere, lifted a little off the face
            z = 0.15 + 0.85 * (i + 0.5) / AO_RAYS
            r = math.sqrt(max(0.0, 1 - z * z))
            rays.append((r * math.cos(turn * i), r * math.sin(turn * i), z))
        # an assembly or a pattern of many parts: the rays look about as far as for its parts, not the whole
        # layout (a ray across a 200-part grid met thousands of triangles); one part: the model's size as before
        sizes = sorted(o.Shape.BoundBox.DiagonalLength for o in solids)
        reach = AO_REACH * min(diag, AO_PART_SPAN * sizes[len(sizes) // 2])
        # more points than AO_POINTS: bake every few points of each face, the others take their neighbour's
        sample, fill = list(range(len(pts))), None
        if len(pts) > AO_POINTS:
            stride = int(math.ceil(len(pts) / float(AO_POINTS)))
            sample, fill = _sample_faces(pts, spans, stride)
        self.job = {"pts": pts, "tris": tris, "nrm": nrm, "occ": [], "rays": rays, "sample": sample, "fill": fill,
                    "reach": reach, "lift": 1e-3 * diag}
        self._next_slice(0)

    def _next_slice(self, ms):
        """The bake's next slice, from a timer of its own: a free singleShot lambda now and then never came
        (the bench saw a 120-part bake stall at a tenth for minutes while nothing else happened)."""
        t = getattr(self, "_slice_timer", None)
        if t is None:
            t = self._slice_timer = QtCore.QTimer()
            t.setSingleShot(True)
            t.setTimerType(QtCore.Qt.PreciseTimer)
            t.timeout.connect(lambda: self.job is not None and self.bake(self.job))
        t.start(ms)

    def bake(self, job):
        import time
        if job is not self.job or not self._alive():
            return
        if job.get("mesh") is None:
            job["mesh"] = _RayMesh.make(job) or False
        until = time.time() + AO_SLICE
        if job["mesh"]:
            job["mesh"].bake(job, until)
        else:
            self._bake_scene(job, until)
        if len(job["occ"]) < len(job["sample"]):
            self._next_slice(10)
            return
        if job.get("fill") is not None:
            occ = job["occ"]
            job["occ"] = [occ[k] for k in job["fill"]]
        self.job = None
        self.switch.removeAllChildren()
        self.switch.addChild(self.skin(job))
        self.refresh()

    def _bake_scene(self, job, until):
        """Without numpy: each ray picked in FreeCAD's own scene (slow on a big model)."""
        import math
        import time
        from pivy import coin
        act = coin.SoRayPickAction(self.view.getViewer().getSoRenderManager().getViewportRegion())
        act.setPickAll(True)
        model = self.view.getSceneGraph()
        face = coin.SoFaceDetail.getClassTypeId()
        pts, nrm, occ, reach, lift = job["pts"], job["nrm"], job["occ"], job["reach"], job["lift"]
        sample = job["sample"]
        while len(occ) < len(sample) and time.time() < until:
            index = sample[len(occ)]
            p, (nx, ny, nz) = pts[index], nrm[index]
            t = (0.0, -nz, ny) if abs(nx) < 0.9 else (-nz, 0.0, nx)
            size = math.sqrt(t[0] * t[0] + t[1] * t[1] + t[2] * t[2]) or 1.0
            t = (t[0] / size, t[1] / size, t[2] / size)
            b = (ny * t[2] - nz * t[1], nz * t[0] - nx * t[2], nx * t[1] - ny * t[0])
            origin = coin.SbVec3f(p[0] + nx * lift, p[1] + ny * lift, p[2] + nz * lift)
            hits = 0
            for dx, dy, dz in job["rays"]:
                act.setRay(origin, coin.SbVec3f(t[0] * dx + b[0] * dy + nx * dz, t[1] * dx + b[1] * dy + ny * dz,
                                                t[2] * dx + b[2] * dy + nz * dz), 0.0, reach)
                act.apply(model)
                for picked in act.getPickedPointList():
                    detail = picked.getDetail()
                    if detail is not None and detail.isOfType(face):
                        hits += 1
                        break
            occ.append(hits / float(len(job["rays"])))

    def skin(self, job):
        from pivy import coin
        pts, occ = job["pts"], job["occ"]
        sep = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        offset = coin.SoPolygonOffset()
        offset.factor = 0.0         # no push by slope: at a hole's rim it lets the far side show through
        offset.units = -2.0
        bind = coin.SoMaterialBinding()
        bind.value = coin.SoMaterialBinding.PER_VERTEX_INDEXED
        material = coin.SoMaterial()
        material.diffuseColor.setValues(0, len(pts), [(0.0, 0.0, 0.0)] * len(pts))
        material.transparency.setValues(0, len(pts), [1.0 - AO_DARK * min(1.0, o * 1.6) for o in occ])
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(pts), pts)
        faces = coin.SoIndexedFaceSet()
        index = []
        for a, b, c in job["tris"]:
            index += [a, b, c, -1]
        faces.coordIndex.setValues(0, len(index), index)
        faces.materialIndex.setValues(0, len(index), index)
        clips = self.view.getSceneGraph()
        for i in range(clips.getNumChildren()):         # Section View's cut cuts the skin too
            if str(clips.getChild(i).getName()) in CLIPS:
                sep.addChild(clips.getChild(i))
        for node in (pick, light, offset, bind, material, coords, faces):
            sep.addChild(node)
        return sep

    def stop(self, remove=True):
        self.timer.stop()
        self.job = None
        if remove and self._alive():
            try:
                self.root.removeChild(self.switch)
            except Exception as _fw_err:
                _fw_log("viewsettings.py:ao", _fw_err)
        _ao.pop(id(self.view), None)


def _shape_key(obj):
    """What Ambient Occlusion is baked for, from one read of the shape (an assembly's Shape is a new compound
    at every read: five reads on each poll took 0.35 s a poll on 300 parts, also while baking)."""
    shape = obj.Shape
    counts = tuple(shape.countElement(k) for k in ("Face", "Edge", "Vertex"))
    # an assembly's compound: its area took 0.6 s on 300 parts; the counts and the box tell a change
    area = None if shape.ShapeType == "Compound" and len(shape.childShapes()) > 8 else round(shape.Area, 6)
    return (obj.Name, counts, area, str(shape.BoundBox), str(shape.Placement))


def _face_meshes(shape, deviation):
    """[(points, triangles, vertex normals)] for each face of a shape in its own axes (Ambient Occlusion)."""
    out = []
    for face in shape.Faces:
        try:
            p, t = face.tessellate(deviation)
        except Exception:
            continue
        nrm = [[0.0, 0.0, 0.0] for _v in p]
        for i, j, k in t:
            n = (p[j] - p[i]).cross(p[k] - p[i])
            for q in (i, j, k):
                m = nrm[q]
                m[0] += n.x
                m[1] += n.y
                m[2] += n.z
        out.append(([(v.x, v.y, v.z) for v in p], t, nrm))
    return out


def _fresh(shape):
    """A copy without the shape's mesh: tessellate() keeps a mesh it already has when that one is finer, so
    the shown shape (meshed finely for the view) never got coarser for a big model."""
    try:
        return shape.copy(True, False)
    except Exception:
        try:
            return shape.copy()
        except Exception:
            return shape


def _sample_faces(pts, spans, stride):
    """Every stride-th point of each face to bake, and for every point the baked one nearest to it on
    the same face (its value is copied)."""
    sample, fill = [], [0] * len(pts)
    try:
        import numpy as np
    except Exception:
        np = None
    for a, b in spans:
        first = len(sample)
        picked = list(range(a, b, stride))
        sample.extend(picked)
        if np is None or len(picked) == 1:
            for i in range(a, b):
                fill[i] = first + min((i - a) // stride, len(picked) - 1)
            continue
        here = np.asarray(pts[a:b], dtype=float)
        chosen = here[::stride]
        for lo in range(0, b - a, 512):
            part = here[lo:lo + 512]
            d = ((part[:, None, :] - chosen[None, :, :]) ** 2).sum(axis=2)
            for k, j in enumerate(d.argmin(axis=1).tolist()):
                fill[a + lo + k] = first + j
    return sample, fill


class _RayMesh:
    """The AO rays tested against the baked mesh itself with numpy: only the triangles within a ray's
    reach of the point, all of its rays at once. Picking each ray in FreeCAD's scene took minutes on a
    200-part model (and over 3 minutes on 5 filleted parts on the bench) and held the view up meanwhile."""

    @classmethod
    def make(cls, job):
        try:
            import numpy
        except Exception as _fw_err:
            _fw_log("viewsettings.py:numpy", _fw_err)
            return None
        return cls(numpy, job)

    def __init__(self, np, job):
        self.np = np
        pts = np.asarray(job["pts"], dtype=float).reshape(-1, 3)
        tri = np.asarray(job["tris"], dtype=np.int64).reshape(-1, 3)
        self.p0 = pts[tri[:, 0]]
        self.e1 = pts[tri[:, 1]] - self.p0
        self.e2 = pts[tri[:, 2]] - self.p0
        self.reach = float(job["reach"])
        self.cell = max(self.reach, 1e-9)
        lo = np.minimum(np.minimum(self.p0, self.p0 + self.e1), self.p0 + self.e2)
        hi = np.maximum(np.maximum(self.p0, self.p0 + self.e1), self.p0 + self.e2)
        self.lo, self.hi = lo, hi
        self.origin = pts.min(axis=0) if len(pts) else np.zeros(3)
        a = np.floor((lo - self.origin) / self.cell).astype(np.int64)
        b = np.floor((hi - self.origin) / self.cell).astype(np.int64)
        grid = {}
        for i in range(len(tri)):          # each triangle in every cell its box touches
            for x in range(a[i, 0], b[i, 0] + 1):
                for y in range(a[i, 1], b[i, 1] + 1):
                    for z in range(a[i, 2], b[i, 2] + 1):
                        grid.setdefault((x, y, z), []).append(i)
        self.grid = grid
        self.near = {}
        self.pts = pts
        self.nrm = np.asarray(job["nrm"], dtype=float).reshape(-1, 3)
        self.rays = np.asarray(job["rays"], dtype=float).reshape(-1, 3)
        self.lift = float(job["lift"])

    def _candidates(self, key):
        """The triangles in the cell and the 26 around it: all a ray of the reach can meet."""
        got = self.near.get(key)
        if got is None:
            x, y, z = key
            ids = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        ids.extend(self.grid.get((x + dx, y + dy, z + dz), ()))
            got = self.near[key] = self.np.unique(self.np.asarray(ids, dtype=self.np.int64))
            if len(self.near) > 20000:
                self.near.clear()
        return got

    def bake(self, job, until):
        import time
        np = self.np
        occ = job["occ"]
        n_rays = float(len(self.rays))
        reach2 = self.reach * self.reach
        sample = job["sample"]
        while len(occ) < len(sample) and time.time() < until:
            index = sample[len(occ)]
            p, n = self.pts[index], self.nrm[index]
            t = np.array((0.0, -n[2], n[1])) if abs(n[0]) < 0.9 else np.array((-n[2], 0.0, n[0]))
            t = t / (np.linalg.norm(t) or 1.0)
            b = _cross(np, n, t)
            dirs = self.rays[:, :1] * t + self.rays[:, 1:2] * b + self.rays[:, 2:3] * n      # (R, 3)
            o = p + n * self.lift
            ids = self._candidates(tuple(np.floor((o - self.origin) / self.cell).astype(np.int64)))
            if len(ids):
                gap = np.maximum(np.maximum(self.lo[ids] - o, o - self.hi[ids]), 0.0)
                ids = ids[np.einsum("tk,tk->t", gap, gap) <= reach2]      # boxes within the reach
            if not len(ids):
                occ.append(0.0)
                continue
            p0, e1, e2 = self.p0[ids], self.e1[ids], self.e2[ids]
            # Moller-Trumbore, every ray against every nearby triangle (both sides of a face count)
            pv = _cross(np, dirs[:, None, :], e2[None, :, :])               # (R, T, 3)
            det = np.einsum("tk,rtk->rt", e1, pv)
            ok = np.abs(det) > 1e-12
            inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
            tv = o - p0                                                       # (T, 3)
            u = np.einsum("tk,rtk->rt", tv, pv) * inv
            qv = _cross(np, tv, e1)                                           # (T, 3)
            v = (dirs @ qv.T) * inv
            dist = np.einsum("tk,tk->t", e2, qv)[None, :] * inv
            hit = ok & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0) & (dist > 0.0) & (dist <= self.reach)
            occ.append(float(hit.any(axis=1).sum()) / n_rays)


def _cross(np, a, b):
    """np.cross without its axis shuffling (a third of the bake's time in a profile)."""
    a, b = np.broadcast_arrays(a, b)
    out = np.empty(a.shape)
    out[..., 0] = a[..., 1] * b[..., 2] - a[..., 2] * b[..., 1]
    out[..., 1] = a[..., 2] * b[..., 0] - a[..., 0] * b[..., 2]
    out[..., 2] = a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]
    return out


def set_ambient(on, view=None):
    """Ambient Occlusion: the corners, hollows and holes of the model go darker (_Occlusion)."""
    view = view or _view()
    if view is None:
        return
    if on and id(view) not in _ao:
        _ao[id(view)] = _Occlusion(view)
    elif not on and id(view) in _ao:
        _ao[id(view)].stop()


def _sync(command, state):
    try:
        actions = Gui.Command.get(command).getAction()
    except Exception:
        actions = []
    for action in actions:
        if action.isCheckable() and action.isChecked() != state:
            blocked = action.blockSignals(True)
            action.setChecked(state)
            action.blockSignals(blocked)


class _Toggle:
    def __init__(self, command, text, tip, pixmap, get, put):
        self.command, self.text, self.tip, self.pixmap, self.get, self.put = command, text, tip, pixmap, get, put

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": self.pixmap, "Checkable": False}

    def Activated(self, checked=None):
        if _view() is None:
            return
        # a menu or button says which way; a macro or key (FreeCAD passes 0) toggles
        self.put(checked if type(checked) is bool else not self.get())

    def IsActive(self):
        if _view() is None:
            return False
        _sync(self.command, self.get())
        return True


def entries():
    ""
    from . import cartoon
    return (("RealView Graphics", realview_on, set_realview),
            ("Shadows In Shaded Mode", shadows_on, set_shadows),
            ("Ambient Occlusion", ambient_on, set_ambient),
            ("Perspective", perspective_on, set_perspective),
            ("Cartoon", cartoon.active, cartoon.set_cartoon))


def register():
    if REALVIEW not in Gui.listCommands():
        Gui.addCommand(REALVIEW, _Toggle(REALVIEW, "RealView Graphics",
                                         "Shades the model per pixel, glossy, with a studio reflected in it",
                                         "DrawStyleShaded", realview_on, set_realview))
    try:
        from . import realview
        realview.install()
    except Exception as _fw_err:
        _fw_log("viewsettings.py:realview", _fw_err)
    if AMBIENT not in Gui.listCommands():
        Gui.addCommand(AMBIENT, _Toggle(AMBIENT, "Ambient Occlusion",
                                        "Darkens the corners, hollows and holes of the model, as light from all around reaches them less",
                                        "DrawStyleShaded", ambient_on, set_ambient))
    if SHADOW not in Gui.listCommands():
        Gui.addCommand(SHADOW, _Toggle(SHADOW, "Shadows In Shaded Mode",
                                       "Drops a shadow of the model on the floor while it is shaded",
                                       "DrawStyleShaded", shadows_on, set_shadows))
    if PERSPECTIVE not in Gui.listCommands():
        Gui.addCommand(PERSPECTIVE, _Toggle(PERSPECTIVE, "Perspective",
                                            "Shows the model in perspective; off shows it orthographic",
                                            "view-perspective", perspective_on, set_perspective))
