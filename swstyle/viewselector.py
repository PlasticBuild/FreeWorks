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

import itertools
import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import chrome, paths
from .widgets import alive

Qt = QtCore.Qt

SETTING = "ViewSelector"          # the Orientation box's View Selector button, on by default
A, B = 1.75, 2.25
                                  # 2024: thin edge bands, small corner facets (corner ~0.22 of the box wide)
EXPLODE = 0.80                    # far faces pushed out (behind the box) by this much of the half-size
EYE = 12.0
                                  # draws the box all but parallel: its sides stay parallel in Isometric)
SIZE = 0.40
                                  # the box, chamfers included, about 0.6 of the view's height in Isometric;
                                  # measured again on shot 21 once the box is drawn near-parallel)
MODEL_MARGIN = 2.0                # the box's half-size, in radii of the model's bounding sphere
FILL = (0.14, 0.15, 0.18)
FILL_ON_DARK = (0.78, 0.81, 0.86)  # on a dark viewport the box is light instead
FILL_TRANSPARENCY = 0.89
PANEL_TRANSPARENCY = 0.74         # the slid-out panels: ~#bbbcc0 over white
HOVER = (0.18, 0.50, 0.93)        # the facet under the pointer: selection blue
HOVER_TRANSPARENCY = 0.55
LINE = (0.22, 0.22, 0.24)
LINE_ON_DARK = (0.88, 0.90, 0.94)
NEAR = 0.05                       # a face is a panel when its normal leans this much away from the viewer
GROW = (-0.1, 0.5)                # a face slides out to a panel as its lean away goes from the first to the second
TICK = 10                         # ms between looks at the camera while the box is up
FACE_KEYS = {(0, -1, 0): "ViewFront", (0, 1, 0): "ViewBack", (-1, 0, 0): "ViewLeft",
             (1, 0, 0): "ViewRight", (0, 0, 1): "ViewTop", (0, 0, -1): "ViewBottom"}
WORDS = (("left", "right"), ("front", "back"), ("bottom", "top"))   # by axis (X, Y, Z): negative, positive
MODS = Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier


# --------------------------------------------------------------------------- the shape
def _planes():
    """(normal, offset, kind) of the 26 cuts of the unit box."""
    out = []
    for axis in range(3):
        for sign in (1, -1):
            n = [0, 0, 0]
            n[axis] = sign
            out.append((tuple(n), 1.0, "face"))
    for i, j in itertools.combinations(range(3), 2):
        for si in (1, -1):
            for sj in (1, -1):
                n = [0, 0, 0]
                n[i], n[j] = si, sj
                out.append((tuple(n), A, "edge"))
    for sx in (1, -1):
        for sy in (1, -1):
            for sz in (1, -1):
                out.append(((sx, sy, sz), B, "corner"))
    return out


def _det(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


def _meet(p1, p2, p3):
    """The point on three planes, or None."""
    m = [list(p1[0]), list(p2[0]), list(p3[0])]
    d = [p1[1], p2[1], p3[1]]
    det = _det(m)
    if abs(det) < 1e-9:
        return None
    out = []
    for col in range(3):
        mc = [row[:] for row in m]
        for row in range(3):
            mc[row][col] = d[row]
        out.append(_det(mc) / det)
    return tuple(out)


def _unit(v):
    length = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / length for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def facet_name(normal):
    """'face:front', 'edge:front-top', 'corner:front-right-top' from the outward direction."""
    kind = ("", "face", "edge", "corner")[sum(1 for c in normal if abs(c) > 1e-6)]
    words = []
    for axis in (1, 0, 2):            # front/back, left/right, bottom/top
        c = normal[axis]
        if abs(c) > 1e-6:
            words.append(WORDS[axis][1 if c > 0 else 0])
    return "%s:%s" % (kind, "-".join(words))


def _shape():
    """The 26 facets: (kind, unit outward normal, direction signs, vertices in order)."""
    planes = _planes()
    verts = []
    for a, b, c in itertools.combinations(planes, 3):
        v = _meet(a, b, c)
        if v is None:
            continue
        if all(_dot(n, v) <= d + 1e-9 for n, d, _ in planes):
            key = tuple(round(x, 6) for x in v)
            if key not in verts:
                verts.append(key)
    facets = []
    for n, d, kind in planes:
        on = [v for v in verts if abs(_dot(n, v) - d) < 1e-6]
        if len(on) < 3:
            continue
        un = _unit(n)
        ref = (0.0, 0.0, 1.0) if abs(un[2]) < 0.9 else (1.0, 0.0, 0.0)
        u = _unit(_cross(un, ref))
        w = _cross(un, u)
        centre = tuple(sum(v[k] for v in on) / len(on) for k in range(3))

        def angle(v, centre=centre, u=u, w=w):
            r = tuple(v[k] - centre[k] for k in range(3))
            return math.atan2(_dot(r, w), _dot(r, u))

        on.sort(key=angle)
        facets.append((kind, un, n, tuple(on)))
    return tuple(facets)


FACETS = _shape()
NAMES = tuple(facet_name(f[2]) for f in FACETS)


def looking_from(direction):
    """Camera orientation quaternion (x, y, z, w) looking at the model from the given world
    direction with Z up: FreeCAD's own standard views come out of the same rule."""
    z = _unit(direction)
    # FreeCAD's Top has +Y up, its Bottom -Y up
    up = (0.0, 0.0, 1.0) if abs(z[2]) < 0.999 else (0.0, 1.0 if z[2] > 0 else -1.0, 0.0)
    x = _unit(_cross(up, z))
    y = _cross(z, x)
    m = ((x[0], y[0], z[0]), (x[1], y[1], z[1]), (x[2], y[2], z[2]))
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        return ((m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s)
    if m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        return (0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s)
    if m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        return ((m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s)
    s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
    return ((m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s)


def from_camera(q, v):
    """Camera-frame vector v in world coordinates: the camera orientation q applied to v."""
    x, y, z, w = chrome._unit(q)
    vx, vy, vz = v
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx))


def _inside(point, polygon):
    x, y = point
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            cross = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < cross:
                inside = not inside
        j = i
    return inside


def enabled():
    return paths.params().GetBool(SETTING, True)


def set_enabled(on):
    paths.params().SetBool(SETTING, bool(on))


def model_extent(doc):
    """(centre, radius) of what is shown in the document: the middle of the shapes' bounding box
    and the radius of the sphere around it; None without shapes."""
    box = None
    for obj in doc.Objects:
        try:
            vo = obj.ViewObject
            if vo is None or not vo.Visibility:
                continue
            shape = getattr(obj, "Shape", None)
            if shape is None or shape.isNull():
                continue
            b = shape.BoundBox
            # datum planes and lines come with boundless shapes: not part of the model's extent
            if not b.isValid() or not (b.DiagonalLength < 1e12):
                continue
        except Exception:
            continue
        if box is None:
            box = App.BoundBox(b)
        else:
            box.add(b)
    if box is None:
        return None
    c = box.Center
    return (c.x, c.y, c.z), box.DiagonalLength / 2.0


def model_centre(doc):
    extent = model_extent(doc)
    return extent[0] if extent else None


# --------------------------------------------------------------------------- the selector
class _DocGone:
    """menusweep-1119: tells the box when a document is deleted."""

    def __init__(self, selector):
        self.selector = selector

    def slotDeletedDocument(self, doc):
        try:
            if alive(self.selector):
                self.selector.doc_gone(doc.Name)
        except Exception as _fw_err:
            _fw_log("viewselector.py:doc_gone", _fw_err)


class ViewSelector(QtCore.QObject):
    """One box for the active 3D view; the shell owns one of these."""

    picked = QtCore.Signal(str)      # facet name
    hidden = QtCore.Signal(str)      # reason: pick, escape, click, space, view, off

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.visible = False
        self.view = None
        self.view_widget = None
        self.hover = None             # index into self._drawn
        self._press = None
        self._drawn = []              # (facet index, screen polygon, depth, pickable)
        self._panel = []              # per drawn polygon: a pushed-out near face
        self._dpr = 1.0
        self._watched = []
        self._key = None
        self._nodes = None
        self._half = None          # the box's half-size in world units, from the model
        self._centre = None        # the model's middle, found once per show (the model holds still)
        self._saved = None         # the view's zoom and pan from before the box, put back on hide
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(TICK)
        self._timer.timeout.connect(self._tick)
        # menusweep-1119: the document the box is drawn in; closing it takes the box away before its 3D view
        # goes (a tick on the deleted view crashed FreeCAD)
        self._doc = None
        self._observer = _DocGone(self)
        try:
            App.addDocumentObserver(self._observer)
        except Exception as _fw_err:
            _fw_log("viewselector.py:observer", _fw_err)
        # for checks
        self.shows = 0
        self.picks = 0
        self.last_pick = None
        self.rebuilds = 0
        self.error = None

    # -- scene -----------------------------------------------------------------------
    def _make_nodes(self):
        from pivy import coin
        group = None
        try:
            kind = coin.SoType.fromName("SoSkipBoundingGroup")
            if not kind.isBad():
                group = coin.cast(kind.createInstance(), "SoGroup")
        except Exception:
            group = None
        if group is None:
            group = coin.SoSeparator()
        sep = coin.SoSeparator()
        sep.setName("SWViewSelector")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
        hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
        coords = coin.SoCoordinate3()
        fills = coin.SoSeparator()
        offset = coin.SoPolygonOffset()
        offset.factor = 1.0
        offset.units = 1.0
        material = coin.SoMaterial()
        material.diffuseColor.setValues(0, 3, [FILL, FILL, HOVER])
        material.transparency.setValues(0, 3, [FILL_TRANSPARENCY, PANEL_TRANSPARENCY, HOVER_TRANSPARENCY])
        binding = coin.SoMaterialBinding()
        binding.value = coin.SoMaterialBinding.PER_FACE_INDEXED
        faces = coin.SoIndexedFaceSet()
        for node in (offset, material, binding, faces):
            fills.addChild(node)

        # them: the faces, drawn after them, washed them grey
        lines = coin.SoAnnotation()
        colour = coin.SoBaseColor()
        colour.rgb = LINE
        style = coin.SoDrawStyle()
        style.lineWidth = 1.0
        edges = coin.SoIndexedLineSet()
        for node in (colour, style, edges):
            lines.addChild(node)
        for node in (pick, light, hints, coords, fills, lines):
            sep.addChild(node)
        group.addChild(sep)
        # Coin frees a node whose last parent lets go of it; this one is taken out of the scene and
        # put back on every Space, so it is held here for the selector's life
        group.ref()
        self._nodes = {"group": group, "coords": coords, "faces": faces, "lines": edges, "style": style,
                       "material": material, "colour": colour}
        self.retheme()

    def retheme(self):
        """Fill and line colours for the viewport's brightness: a light box over a dark scene."""
        if self._nodes is None:
            return
        from . import style as look
        dark = look.viewport_dark()
        fill = FILL_ON_DARK if dark else FILL
        self._nodes["material"].diffuseColor.setValues(0, 3, [fill, fill, HOVER])
        if self._drawn:
            self._paint_materials()
        self._nodes["colour"].rgb = LINE_ON_DARK if dark else LINE

    def _scene(self, view):
        try:
            return view.getSceneGraph()
        except Exception:
            return None

    # -- showing ---------------------------------------------------------------------
    def show(self):
        view = self.shell._view()
        widget = self.shell.view_widget()
        if view is None or widget is None or not hasattr(view, "getSceneGraph"):
            return False
        if self.visible:
            if view is self.view:
                return True
            self.hide("view")
        try:
            if self._nodes is None:
                self._make_nodes()
            else:
                self.retheme()
            scene = self._scene(view)
            if scene is None:
                return False
            scene.addChild(self._nodes["group"])
        except Exception as error:
            self.error = "scene: %s" % error
            App.Console.PrintWarning("FreeCAD: view selector not drawn: %s\n" % error)
            return False
        self.view = view
        self.view_widget = widget
        try:
            self._doc = Gui.ActiveDocument.Document.Name if Gui.ActiveDocument is not None else None
        except Exception:
            self._doc = None
        self.visible = True
        self.hover = None
        self._press = None
        self._key = None
        self.shows += 1
        self._frame()
        self._attach()
        self._tick()
        self._timer.start()
        return True

    # -- the view while the box is up ----------------------------------------------------
    def _frame(self):
        ""


        self._half = None
        self._saved = None
        self._centre = None
        try:
            doc = Gui.ActiveDocument.Document if Gui.ActiveDocument is not None else None
            extent = model_extent(doc) if doc is not None else None
            self._centre = extent[0] if extent else None
            q, pos, perspective, angle, height, w, h = self._camera()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: view selector: %s\n" % error)
            return
        if extent is None or extent[1] <= 1e-9 or w < 2 or h < 2:
            return
        centre, radius = extent
        half = radius * MODEL_MARGIN
        cq = chrome._unit(q)
        cc = chrome.to_camera(cq, (centre[0] - pos[0], centre[1] - pos[1], centre[2] - pos[2]))
        distance = max(-cc[2], 1e-6)
        self._saved = {"centre": centre, "offset": (cc[0], cc[1]), "distance": distance,
                       "height": height, "perspective": perspective}
        self._half = half
        try:
            cam = self.view.getCameraNode()
            units_per_px = 2.0 * half / (SIZE * min(w, h))
            if perspective:
                tan_half = math.tan(angle / 2.0) or 1e-6
                distance = units_per_px * h / (2.0 * tan_half)
            else:
                cam.height.setValue(units_per_px * h)
            self._place_camera(cq, centre, (0.0, 0.0), distance)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: view selector: zoom: %s\n" % error)

    def _place_camera(self, q, centre, offset, distance):
        """Puts the camera so that centre sits at offset (camera x, y) at this distance."""
        cam = self.view.getCameraNode()
        back = from_camera(q, (offset[0], offset[1], -distance))
        cam.position.setValue(centre[0] - back[0], centre[1] - back[1], centre[2] - back[2])
        cam.focalDistance.setValue(distance)

    def _restore(self, centred):
        ""

        saved, self._saved = self._saved, None
        self._half = None
        if saved is None or self.view is None:
            return
        try:
            q, pos, perspective, angle, height, w, h = self._camera()
            cam = self.view.getCameraNode()
            if not perspective and saved["height"]:
                cam.height.setValue(saved["height"])
            offset = (0.0, 0.0) if centred else saved["offset"]
            self._place_camera(chrome._unit(q), saved["centre"], offset, saved["distance"])
        except Exception as error:
            App.Console.PrintLog("FreeCAD: view selector: view not put back: %s\n" % error)

    def hide(self, reason="off"):
        if not self.visible:
            return
        self._timer.stop()
        self.visible = False
        self._detach()
        self._restore(centred=(reason == "pick"))
        scene = self._scene(self.view) if self.view is not None else None
        if scene is not None and self._nodes is not None:
            try:
                scene.removeChild(self._nodes["group"])
            except Exception as _fw_err:
                _fw_log("viewselector.py:485", _fw_err)
        if self.hover is not None and self.view_widget is not None and alive(self.view_widget):
            self.view_widget.unsetCursor()
        self.hover = None
        self._press = None
        self._drawn = []
        self.view = None
        self.view_widget = None
        self.hidden.emit(reason)

    def toggle(self):
        if self.visible:
            self.hide("space")
            return False
        return self.show()

    def remove(self):
        self.hide("off")
        nodes, self._nodes = self._nodes, None
        if nodes is not None:
            try:
                nodes["group"].unref()
            except Exception as _fw_err:
                _fw_log("viewselector.py:508", _fw_err)

    # -- the filter ------------------------------------------------------------------
    def _attach(self):
        self._detach()
        widget = self.view_widget
        if widget is None or not alive(widget):
            return
        widgets = [widget]
        self._vp = None
        if hasattr(widget, "viewport") and widget.viewport() is not None:
            self._vp = widget.viewport()
            widgets.append(self._vp)
        for w in widgets:
            w.installEventFilter(self)
            self._watched.append(w)

        # FeatureManager, or after the Orientation box closed and focus went to another widget)
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._watched.append(app)

    def _detach(self):
        for w in self._watched:
            if alive(w):
                w.removeEventFilter(self)
        self._watched = []
        self._vp = None

    def _viewport(self):
        """The viewport taken when the filter was installed: no call into the view widget here, it
        may be half destroyed while Qt still delivers events (the sweep's segfault)."""
        vp = getattr(self, "_vp", None)
        if vp is not None:
            return vp
        return self.view_widget

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if not self.visible:
            return False
        t = event.type()
        if t == QtCore.QEvent.KeyPress:
            if event.key() == Qt.Key_Escape and not (event.modifiers() & MODS) and self._own_escape(obj):
                self.hide("escape")
                return True
            return False
        if obj is not self._viewport():
            return False
        if t == QtCore.QEvent.MouseMove:
            if event.buttons() == Qt.NoButton:
                self._set_hover(self._hit(event.position()))
            return False
        if t == QtCore.QEvent.Leave:
            self._set_hover(None)
            return False
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() != Qt.LeftButton or (event.modifiers() & MODS):
                return False
            hit = self._hit(event.position())
            if hit is None:
                # a click elsewhere in the view takes the box away; the click goes on to FreeCAD
                self.hide("click")
                return False
            self._press = hit
            return True
        if t == QtCore.QEvent.MouseButtonDblClick:
            return event.button() == Qt.LeftButton and self._hit(event.position()) is not None
        if t == QtCore.QEvent.MouseButtonRelease:
            if event.button() != Qt.LeftButton or self._press is None:
                return False
            pressed, self._press = self._press, None
            if self._hit(event.position()) == pressed:
                self.pick(pressed)
            return True
        return False

    def _own_escape(self, obj):
        """An Escape meant for the box: in the view's own window, with no menu, dialog or
        PropertyManager edit field waiting for it."""
        if obj is self.view_widget or obj is getattr(self, "_vp", None):
            return True
        app = QtWidgets.QApplication
        if app.activePopupWidget() is not None or app.activeModalWidget() is not None:
            return False
        widget = self.view_widget
        if not isinstance(obj, QtWidgets.QWidget) or widget is None or not alive(widget):
            return False
        if isinstance(obj, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox,
                            QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
            return False
        return obj.window() is widget.window()

    def _set_hover(self, index):
        if index == self.hover:
            return
        self.hover = index
        self._paint_materials()
        widget = self.view_widget
        if widget is not None and alive(widget):
            if index is None:
                widget.unsetCursor()
            else:
                widget.setCursor(Qt.ArrowCursor)

    def _paint_materials(self):
        if self._nodes is None:
            return
        from . import style as look
        fill = FILL_ON_DARK if look.viewport_dark() else FILL
        colours, alphas, values = [], [], []
        for i, (facet, polygon, depth, pickable) in enumerate(self._drawn):
            if i == self.hover:
                colours.append(HOVER)
                alphas.append(HOVER_TRANSPARENCY)
            else:
                # a panel's tint comes in as it slides out
                out = self._panel[i] if FACETS[facet][0] == "face" and pickable else 0.0
                colours.append(fill)
                alphas.append(FILL_TRANSPARENCY + out * (PANEL_TRANSPARENCY - FILL_TRANSPARENCY))
            values.append(i)
        material = self._nodes["material"]
        material.diffuseColor.setValues(0, len(colours), colours)
        material.diffuseColor.setNum(len(colours))
        material.transparency.setValues(0, len(alphas), alphas)
        material.transparency.setNum(len(alphas))
        faces = self._nodes["faces"]
        faces.materialIndex.setValues(0, len(values), values)
        faces.materialIndex.setNum(len(values))

    # -- geometry --------------------------------------------------------------------
    def _camera(self):
        view = self.view
        cam = view.getCameraNode()
        q = tuple(cam.orientation.getValue().getValue())
        pos = tuple(cam.position.getValue().getValue())
        perspective = "Perspective" in cam.getTypeId().getName().getString()
        angle = cam.heightAngle.getValue() if perspective else 0.0
        height = cam.height.getValue() if not perspective else 0.0
        region = view.getViewer().getSoRenderManager().getViewportRegion()
        w, h = region.getViewportSizePixels().getValue()
        return q, pos, perspective, angle, height, int(w), int(h)

    def doc_gone(self, name=None):
        """menusweep-1119: the box's document is closing or closed: take the box away without touching its view."""
        if not self.visible or (name is not None and name != self._doc):
            return
        self.view = None
        self._saved = None
        self.hide("view")

    def _tick(self):
        if not self.visible:
            return
        if self._doc is not None and self._doc not in App.listDocuments():
            self.doc_gone()
            return
        view = self.view
        if view is None or self.view_widget is None or not alive(self.view_widget) \
                or self.shell.view_widget() is not self.view_widget:
            self.hide("view")
            return
        try:
            cam = self._camera()
        except Exception as error:
            self.error = "camera: %s" % error
            self.hide("view")
            return
        dpr = self.view_widget.devicePixelRatioF() if hasattr(self.view_widget, "devicePixelRatioF") else 1.0
        key = (tuple(round(c, 5) for c in cam[0]), tuple(round(c, 4) for c in cam[1]), cam[2],
               round(cam[3], 5), round(cam[4], 4), cam[5], cam[6], dpr)
        if key == self._key:
            return
        self._key = key
        try:
            self._rebuild(cam, dpr)
        except Exception as error:
            import traceback
            self.error = "rebuild: %s" % error
            App.Console.PrintLog("FreeCAD: view selector: %s\n" % traceback.format_exc())

    def _rebuild(self, cam, dpr):
        q, pos, perspective, angle, height, w, h = cam
        if w < 2 or h < 2:
            return
        # found once in _frame: going through every shape on every frame made the turning choppy
        centre = self._centre
        cq = chrome._unit(q)
        if centre is None:
            # the focal point
            focal = self.view.getCameraNode().focalDistance.getValue()
            back = from_camera(cq, (0.0, 0.0, -focal))
            centre = (pos[0] + back[0], pos[1] + back[1], pos[2] + back[2])
        cc = chrome.to_camera(cq, (centre[0] - pos[0], centre[1] - pos[1], centre[2] - pos[2]))
        distance = max(-cc[2], 1e-6)
        if perspective:
            tan_half = math.tan(angle / 2.0) or 1e-6
            units_per_px = 2.0 * distance * tan_half / h
        else:
            tan_half = 0.0
            units_per_px = height / h
        if self._half:
            # around the whole model, in world units (the view was zoomed out to fit it)
            half = self._half
        else:
            # no shapes: a box of the view's size about the focal point; when that is off to the
            # side, about the middle of the view instead, at the same depth
            sx = w / 2.0 + cc[0] / units_per_px
            sy = h / 2.0 - cc[1] / units_per_px
            if not (0.2 * w <= sx <= 0.8 * w and 0.2 * h <= sy <= 0.8 * h):
                cc = (0.0, 0.0, cc[2])
                moved = from_camera(cq, cc)
                centre = (pos[0] + moved[0], pos[1] + moved[1], pos[2] + moved[2])
            half = SIZE * min(w, h) * units_per_px / 2.0
        toward = from_camera(cq, (0.0, 0.0, 1.0))
        points, face_index, line_index, drawn, panel = [], [], [], [], []
        for fi, (kind, normal, signs, verts) in enumerate(FACETS):
            far = -_dot(normal, toward)
            is_panel = False
            out = 0.0
            if kind == "face":

                # viewer, and back in as it turns toward it: never all at once
                out = _smooth((far - GROW[0]) / (GROW[1] - GROW[0]))
                is_panel = far > NEAR
                if out > 0.0:
                    verts = tuple(tuple(v[k] + out * EXPLODE * normal[k] for k in range(3)) for v in verts)
            screen, start = [], len(points)
            depth = 0.0
            for u in verts:
                world = (centre[0] + half * u[0], centre[1] + half * u[1], centre[2] + half * u[2])
                c = chrome.to_camera(cq, (world[0] - pos[0], world[1] - pos[1], world[2] - pos[2]))
                if perspective:
                    d = max(-c[2], 1e-6)
                    upp = 2.0 * d * tan_half / h
                    screen.append((w / 2.0 + c[0] / upp, h / 2.0 - c[1] / upp))
                    points.append(world)
                else:
                    dz = (c[2] - cc[2]) / half
                    k = EYE / max(EYE - dz, 0.5)
                    c2 = (cc[0] + k * (c[0] - cc[0]), cc[1] + k * (c[1] - cc[1]), c[2])
                    screen.append((w / 2.0 + c2[0] / units_per_px, h / 2.0 - c2[1] / units_per_px))
                    back = from_camera(cq, c2)
                    points.append((pos[0] + back[0], pos[1] + back[1], pos[2] + back[2]))
                depth += c[2]
            depth /= len(verts)
            n = len(verts)
            face_index.extend(range(start, start + n))
            face_index.append(-1)
            line_index.extend(range(start, start + n))
            line_index.extend((start, -1))
            drawn.append((fi, screen, depth, True))
            panel.append(out if is_panel or out > 0.0 else 0.0)
        nodes = self._nodes
        nodes["coords"].point.setValues(0, len(points), points)
        nodes["coords"].point.setNum(len(points))
        nodes["faces"].coordIndex.setValues(0, len(face_index), face_index)
        nodes["faces"].coordIndex.setNum(len(face_index))
        nodes["lines"].coordIndex.setValues(0, len(line_index), line_index)
        nodes["lines"].coordIndex.setNum(len(line_index))
        nodes["style"].lineWidth = float(max(1.0, round(dpr)))
        self._drawn = drawn
        self._panel = panel
        self._dpr = dpr
        self._size = (w, h)
        if self.hover is not None and self.hover >= len(drawn):
            self.hover = None
        self._paint_materials()
        self.rebuilds += 1

    def _hit(self, position):
        """Index into the drawn polygons under a viewport position (logical pixels), or None."""
        if not self._drawn:
            return None
        dpr = getattr(self, "_dpr", 1.0) or 1.0
        point = (position.x() * dpr, position.y() * dpr)
        best, best_depth = None, None
        for i, (facet, polygon, depth, pickable) in enumerate(self._drawn):
            if not pickable or not _inside(point, polygon):
                continue
            if best is None or depth > best_depth:
                best, best_depth = i, depth
        return best

    def facet_at(self, x, y):
        """Facet name at viewport (logical) coordinates, for checks."""
        i = self._hit(QtCore.QPointF(x, y))
        return NAMES[self._drawn[i][0]] if i is not None else None

    def facet_centre(self, name):
        """Viewport (logical) centre of a drawn facet, for checks; None when not drawn."""
        dpr = getattr(self, "_dpr", 1.0) or 1.0
        for facet, polygon, depth, pickable in self._drawn:
            if NAMES[facet] == name:
                xs = [p[0] for p in polygon]
                ys = [p[1] for p in polygon]
                return (sum(xs) / len(xs) / dpr, sum(ys) / len(ys) / dpr)
        return None

    def drawn_names(self):
        return [NAMES[d[0]] for d in self._drawn]

    # -- picking ---------------------------------------------------------------------
    def pick(self, index):
        if index is None or index >= len(self._drawn):
            return
        facet = self._drawn[index][0]
        name = NAMES[facet]
        self.picks += 1
        self.last_pick = name
        self.hide("pick")
        self.picked.emit(name)
        self.turn_to(FACETS[facet][2])

    def turn_to(self, signs):
        """Turns the active view to look from the direction of a facet."""
        key = FACE_KEYS.get(tuple(signs))
        if key is not None:
            try:
                self.shell.binding(key).run()
                return
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: view selector: %s\n" % error)
        view = self.shell._view()
        if view is None:
            return
        try:
            self.shell.push_view()
        except Exception as _fw_err:
            _fw_log("viewselector.py:808", _fw_err)
        q = looking_from(signs)
        try:
            from . import namedviews
            if namedviews.turned():
                # standard views updated (Update Standard Views): the in-between views turn with them
                q = tuple(namedviews.turn().multiply(App.Rotation(*q)).Q)
        except Exception as _fw_err:
            _fw_log("viewselector.py:816", _fw_err)
        try:
            view.setCameraOrientation(q)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: view selector: %s\n" % error)
