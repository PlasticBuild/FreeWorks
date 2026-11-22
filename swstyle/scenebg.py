# SPDX-License-Identifier: LGPL-2.1-or-later
""



















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
from PySide import QtCore, QtGui, QtWidgets

from . import paths, style

SETTING = "SolidWorksBackground"
NAME = "SWSceneBackground"
# Rows top to bottom, columns left to right, over the whole 3D view (grey levels sampled as RGB from

GRID = (
    ((251, 251, 251), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (253, 253, 253), (247, 248, 249), (238, 239, 243), (228, 231, 240), (223, 227, 236), (226, 230, 239), (232, 235, 240), (235, 239, 242)),
    ((254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (249, 251, 250), (243, 244, 246), (232, 235, 240), (225, 229, 238), (222, 226, 235), (225, 229, 238), (231, 234, 239), (234, 237, 242)),
    ((254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (253, 253, 253), (249, 251, 250), (244, 245, 247), (234, 238, 241), (228, 231, 240), (222, 226, 235), (220, 224, 233), (223, 227, 236), (228, 231, 240), (231, 234, 239)),
    ((254, 254, 254), (254, 254, 254), (253, 253, 253), (251, 253, 252), (249, 251, 250), (246, 247, 249), (241, 242, 246), (234, 237, 242), (228, 231, 240), (223, 227, 236), (221, 225, 234), (219, 223, 234), (220, 224, 235), (225, 229, 238), (228, 231, 240)),
    ((248, 250, 249), (247, 248, 250), (245, 246, 248), (243, 244, 246), (240, 240, 244), (234, 238, 241), (229, 232, 237), (225, 229, 238), (223, 227, 236), (221, 225, 234), (219, 223, 234), (216, 220, 231), (218, 222, 233), (221, 225, 234), (225, 229, 238)),
    ((237, 239, 242), (235, 239, 242), (234, 237, 241), (230, 233, 238), (227, 229, 238), (225, 229, 238), (223, 227, 236), (222, 226, 235), (219, 223, 233), (218, 222, 233), (217, 221, 232), (215, 219, 230), (216, 220, 231), (219, 223, 234), (221, 225, 234)),
    ((229, 232, 237), (228, 231, 240), (227, 230, 239), (225, 229, 238), (224, 227, 236), (224, 228, 237), (223, 227, 236), (222, 226, 235), (221, 225, 234), (220, 224, 235), (219, 223, 234), (219, 223, 234), (219, 223, 234), (221, 225, 234), (222, 226, 235)),
    ((235, 239, 242), (235, 239, 242), (236, 240, 243), (236, 240, 243), (239, 240, 244), (239, 240, 244), (239, 240, 244), (239, 240, 244), (239, 240, 244), (238, 240, 244), (239, 240, 244), (236, 240, 243), (236, 238, 242), (234, 238, 241), (234, 237, 242)),
    ((250, 252, 251), (251, 253, 252), (251, 253, 252), (252, 252, 252), (253, 253, 253), (253, 253, 253), (253, 253, 253), (249, 248, 248), (253, 253, 253), (252, 253, 252), (252, 253, 253), (251, 253, 252), (250, 252, 251), (249, 251, 250), (246, 247, 249)),
    ((254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (253, 253, 253), (250, 252, 251), (246, 247, 249)),
    ((254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (254, 254, 254), (252, 252, 252), (254, 254, 254), (254, 254, 254), (253, 253, 253), (250, 252, 251), (246, 247, 249), (243, 244, 248)),
    ((248, 250, 250), (251, 253, 252), (253, 253, 253), (253, 253, 253), (251, 253, 252), (250, 252, 251), (250, 252, 251), (250, 252, 251), (250, 252, 251), (250, 252, 251), (249, 251, 250), (248, 250, 249), (245, 246, 248), (244, 245, 247), (243, 244, 248)),
    ((246, 247, 249), (247, 249, 250), (248, 250, 249), (249, 251, 250), (248, 250, 249), (247, 248, 250), (246, 247, 249), (247, 248, 250), (247, 248, 250), (247, 248, 250), (247, 248, 250), (246, 247, 249), (245, 246, 248), (245, 246, 248), (245, 246, 248)),
)
# Dark (Ati 21:55Z: the 3D view is dark in Dark): the same scene, its light levels laid onto the Dark
# theme's greys, so the bright top left, the darker band over the horizon and the floor stay where

DARK_LOW = (0x24, 0x26, 0x2A)
DARK_HIGH = (0x45, 0x48, 0x4F)
OWN_SCENES = (-1, 0)        # the theme's own scene, or 3 Point Faded picked by hand (the same scene)


def wanted():
    """The Light or Dark theme with its own scene (AMOLED stays pure black)."""
    try:
        if not paths.params().GetBool(SETTING, True):
            return False
        if style.current_theme() not in ("Light", "Medium Light", "Medium", "Dark"):      # themes-medium-1120
            return False
        return paths.params().GetInt(style.SCENE_SETTING, -1) in OWN_SCENES
    except Exception:
        return False


def _ray_again(userdata, action):
    try:
        from pivy import coin
        if action.isOfType(coin.SoRayPickAction.getClassTypeId()):
            coin.cast(action, "SoRayPickAction").computeWorldSpaceRay()
    except Exception as _fw_err:
        _fw_log("scenebg.py:ray", _fw_err)


def grid(theme=None):
    ""
    theme = theme or style.current_theme()
    out = []
    for row in GRID:
        line = []
        for c in row:
            if theme in ("Light", "Medium Light", "Medium"):
                line.append(tuple(v / 255.0 for v in c))
            else:
                t = max(0.0, min(1.0, (sum(c) / 3.0 - 220.0) / 34.0))
                line.append(tuple((lo + t * (hi - lo)) / 255.0 for lo, hi in zip(DARK_LOW, DARK_HIGH)))
        out.append(line)
    return out


def _make_node():
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
    group.setName(NAME)
    sep = coin.SoSeparator()
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    cam = coin.SoOrthographicCamera()
    cam.viewportMapping = coin.SoCamera.LEAVE_ALONE      # the patch fills the view whatever its shape
    cam.position.setValue(0.0, 0.0, 1.0)
    cam.height = 2.0
    cam.nearDistance = 0.5
    cam.farDistance = 1.5
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    depth = coin.SoDepthBuffer()
    depth.test = False
    depth.write = False
    rows, cols = len(GRID), len(GRID[0])
    points, colours, index = [], [], []
    for j in range(rows):
        for i in range(cols):
            points.append((-1.0 + 2.0 * i / (cols - 1), 1.0 - 2.0 * j / (rows - 1), 0.0))
            colours.append((1.0, 1.0, 1.0))
    for j in range(rows - 1):
        for i in range(cols - 1):
            a = j * cols + i
            index.extend((a, a + cols, a + cols + 1, -1, a, a + cols + 1, a + 1, -1))
    material = coin.SoMaterial()
    material.diffuseColor.setValues(0, len(colours), colours)
    binding = coin.SoMaterialBinding()
    binding.value = coin.SoMaterialBinding.PER_VERTEX_INDEXED
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(points), points)
    faces = coin.SoIndexedFaceSet()
    faces.coordIndex.setValues(0, len(index), index)
    faces.materialIndex.setValues(0, len(index), index)
    for node in (pick, cam, light, depth, material, binding, coords, faces):
        sep.addChild(node)
    group.addChild(sep)
    # the patch's own camera leaves its ray in a pick action (a ray is kept by the action, not by
    # the state the separator restores): every pick after it would aim through the middle of the
    # view. The ray is worked out again from the 3D view's camera right after the patch.
    again = coin.SoCallback()
    again.setCallback(_ray_again)
    group.addChild(again)
    group.ref()          # held for the module's life: Coin frees a node its last parent lets go of
    return group, material


PHOTO_NAME = "SWScenePhoto"


def photo_file():
    """The picked scene's background photo, or None (a studio scene, the theme's own, or a missing file)."""
    try:
        from . import realview
        env = realview.environment_file()
    except Exception as _fw_err:
        _fw_log("scenebg.py:photo", _fw_err)
        return None
    if not env:
        return None
    path = env[:-4] + "_bg.jpg"
    import os
    return path if os.path.isfile(path) else None


def _make_photo_node():
    """(group, texture, texture coordinates): a picture filling the view behind the model."""
    from pivy import coin
    group, _material = _make_node()
    group.setName(PHOTO_NAME)
    sep = group.getChild(0)
    # the grid's colour patch becomes one white quad with the picture on it
    for k in range(sep.getNumChildren() - 1, 3, -1):
        sep.removeChild(k)
    material = coin.SoMaterial()
    material.diffuseColor.setValue(1.0, 1.0, 1.0)
    tex = coin.SoTexture2()
    tex.model = coin.SoTexture2.REPLACE
    tex.wrapS = coin.SoTexture2.CLAMP
    tex.wrapT = coin.SoTexture2.CLAMP
    tc = coin.SoTextureCoordinate2()
    tc.point.setValues(0, 4, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, 4, [(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0)])
    faces = coin.SoFaceSet()
    faces.numVertices.setValue(4)
    for node in (material, tex, tc, coords, faces):
        sep.addChild(node)
    return group, tex, tc


def _load_photo(tex, path):
    """(width, height) of the picture put in the texture (read with Qt), or None."""
    from pivy import coin
    image = QtGui.QImage(path)
    if image.isNull():
        return None
    image = image.convertToFormat(QtGui.QImage.Format_RGB888).mirrored(False, True)     # Coin: bottom row first
    w, h = image.width(), image.height()
    stride = image.bytesPerLine()
    raw = bytes(image.constBits())[:stride * h]
    tex.image.setValue(coin.SbVec2s(w, h), 3, b"".join(raw[y * stride:y * stride + 3 * w] for y in range(h)))
    return w, h


def cover(view_aspect, image_aspect):
    """Texture coordinates (s0, t0, s1, t1) that fill a view of that aspect with the picture, cut
    to fit and never stretched (the middle of the picture kept)."""
    if view_aspect >= image_aspect:
        span = image_aspect / view_aspect
        return 0.0, 0.5 - span / 2, 1.0, 0.5 + span / 2
    span = view_aspect / image_aspect
    return 0.5 - span / 2, 0.0, 0.5 + span / 2, 1.0


class SceneBackground(QtCore.QObject):
    """Keeps the patch first in every 3D view's scene while wanted(), takes it out otherwise."""

    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.node = None
        self.material = None
        self.theme = None           # the theme whose colours the patch has
        self.photo = None           # (group, texture, texture coordinates) of a photo scene's picture
        self.photo_file = None      # the picture in it
        self.photo_size = None
        self.photo_aspect = None
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self.sync)
        self._timer.start()
        try:
            style.signals.theme_changed.connect(self.sync)
        except Exception as _fw_err:
            _fw_log("scenebg.py:signal", _fw_err)
        QtCore.QTimer.singleShot(0, self.sync)

    @staticmethod
    def _views():
        out = []
        for name in list(App.listDocuments().keys()):
            try:
                gdoc = Gui.getDocument(name)
                out.extend(gdoc.mdiViewsOfType("Gui::View3DInventor"))
            except Exception:
                continue
        return out

    def _mdi_background(self):
        """The area behind the documents (seen with none open, behind the Welcome): the theme's window
        colour, not Qt's mid-grey, which was the one light patch on a dark screen (look audit AC7)."""
        try:
            mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
            if mdi is None:
                return
            colour = QtWidgets.QApplication.palette().color(QtGui.QPalette.Window)
            if style.dark():
                colour = colour.darker(115)
            # FreeCAD puts its own grey back when the style sheet changes: checked on every pass
            if mdi.background().color() != colour or mdi.background().style() != QtCore.Qt.SolidPattern:
                mdi.setBackground(QtGui.QBrush(colour))
        except Exception as _fw_err:
            _fw_log("scenebg.py:mdi", _fw_err)

    def _sync_photo(self, views):
        path = photo_file()
        if path and self.photo is None:
            try:
                self.photo = _make_photo_node()
            except Exception as _fw_err:
                _fw_log("scenebg.py:photo-node", _fw_err)
                return
        if self.photo is None:
            return
        group, tex, tc = self.photo
        if path and path != self.photo_file:
            self.photo_size = _load_photo(tex, path)
            self.photo_file = path
            self.photo_aspect = None
        want = bool(path) and self.photo_size is not None
        if want:
            try:
                w = Gui.ActiveDocument.ActiveView.graphicsView().viewport()
                aspect = w.width() / float(max(1, w.height()))
            except Exception:
                aspect = 1.6
            if self.photo_aspect is None or abs(aspect - self.photo_aspect) > 0.01:
                s0, t0, s1, t1 = cover(aspect, self.photo_size[0] / float(self.photo_size[1]))
                tc.point.setValues(0, 4, [(s0, t0), (s1, t0), (s1, t1), (s0, t1)])
                self.photo_aspect = aspect
        for view in views:
            try:
                root = view.getSceneGraph()
            except Exception:
                continue
            if root is None:
                continue
            at = root.findChild(group)
            if want and at != 0:
                if at > 0:
                    root.removeChild(at)
                root.insertChild(group, 0)
            elif not want and at >= 0:
                root.removeChild(at)

    def sync(self, *args):
        self._mdi_background()
        try:
            self._sync_photo(self._views())
        except Exception as _fw_err:
            _fw_log("scenebg.py:photo-sync", _fw_err)
        want = wanted()
        if want and self.node is None:
            try:
                self.node, self.material = _make_node()
            except Exception as error:
                App.Console.PrintLog("FreeCAD: scene background: %s\n" % error)
                self._timer.stop()
                return
        if self.node is None:
            return
        theme = style.current_theme()
        if want and theme != self.theme:
            colours = [c for row in grid(theme) for c in row]
            self.material.diffuseColor.setValues(0, len(colours), colours)
            self.theme = theme
        for view in self._views():
            try:
                root = view.getSceneGraph()
            except Exception:
                continue
            if root is None:
                continue
            at = root.findChild(self.node)
            if want and at != 0:
                if at > 0:
                    root.removeChild(at)
                root.insertChild(self.node, 0)
            elif not want and at >= 0:
                root.removeChild(at)

    def remove(self):
        self._timer.stop()
        if self.photo is not None:
            for view in self._views():
                try:
                    root = view.getSceneGraph()
                    at = root.findChild(self.photo[0])
                    if at >= 0:
                        root.removeChild(at)
                except Exception as _fw_err:
                    _fw_log("scenebg.py:photo-remove", _fw_err)
        if self.node is not None:
            for view in self._views():
                try:
                    root = view.getSceneGraph()
                    at = root.findChild(self.node)
                    if at >= 0:
                        root.removeChild(at)
                except Exception as _fw_err:
                    _fw_log("scenebg.py:remove", _fw_err)
        if self.node is not None:
            try:
                self.node.unref()
            except Exception as _fw_err:
                _fw_log("scenebg.py:unref", _fw_err)
            self.node = None
