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

from . import paths

PARAM = "ModelOriginArrows"
ARROW_PX = 24
HEAD_PX = 6
GREY = (0.55, 0.55, 0.55)
POLL = 200
NODE = "SWModelOriginArrows"


def enabled():
    return paths.params().GetBool(PARAM, True)


def set_enabled(on):
    paths.params().SetBool(PARAM, bool(on))


def _selection_blue():
    try:
        value = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("SelectionColor", 0x0058C0FF)
        return ((value >> 24) & 255) / 255.0, ((value >> 16) & 255) / 255.0, ((value >> 8) & 255) / 255.0
    except Exception:
        return 0.0, 0.35, 0.75


def _origin_points(doc):
    """[(origin, point feature or None)] of the origins shown in doc."""
    out = []
    for obj in doc.Objects:
        if not obj.isDerivedFrom("App::Origin"):
            continue
        try:
            vo = obj.ViewObject
            if vo is None or not vo.Visibility:
                continue
            point = next((f for f in obj.OriginFeatures if f.isDerivedFrom("App::Point")), None)
            if point is not None and point.ViewObject is not None and not point.ViewObject.Visibility:
                continue
            out.append((obj, point))
        except Exception as _fw_err:
            _fw_log("modelorigin.py:66", _fw_err)
    return out


def _placement(origin):
    try:
        return origin.getGlobalPlacement()
    except Exception:
        try:
            return origin.Placement
        except Exception:
            return App.Placement()


def _picked(origin, point):
    try:
        names = {s.ObjectName for s in Gui.Selection.getSelectionEx(origin.Document.Name)}
    except Exception:
        return False
    return origin.Name in names or (point is not None and point.Name in names)


class ModelOrigin(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.node = None
        self.view = None
        self.key = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(POLL)
        self.timer.timeout.connect(self.update)
        self.timer.start()
        self.count = 0

    def _view(self):
        gdoc = Gui.ActiveDocument
        view = gdoc.ActiveView if gdoc is not None else None
        return view if view is not None and hasattr(view, "getSceneGraph") else None

    def _pixel(self, view, base):
        x, y = view.getPointOnScreen(base)
        a = view.getPoint(int(x), int(y))
        b = view.getPoint(int(x) + 10, int(y))
        return max((b - a).Length / 10.0, 1e-9)

    def update(self):
        view = self._view()
        if view is None or not enabled():
            self.clear()
            return
        try:
            from . import contextbar
            if contextbar.sketch_in_edit() is not None:
                self.clear()        # the sketch origin's red arrows are shown instead
                return
        except Exception as _fw_err:
            _fw_log("modelorigin.py:122", _fw_err)
        doc = Gui.ActiveDocument.Document
        items = []
        try:
            for origin, point in _origin_points(doc):
                pl = _placement(origin)
                px = self._pixel(view, pl.Base)
                items.append((pl, px, _picked(origin, point)))
        except Exception:
            self.clear()
            return
        key = (id(view), tuple((tuple(pl.toMatrix().A), round(px, 9), picked) for pl, px, picked in items))
        if key == self.key and self.node is not None and self.view is view:
            return
        self.draw(view, items, key)

    def draw(self, view, items, key):
        from pivy import coin
        from .widgets import ui_scale
        self.clear()
        self.key = key
        self.count = len(items)
        if not items:
            return
        k = ui_scale()
        root = coin.SoSeparator()
        root.setName(NODE)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        root.addChild(light)
        draw = coin.SoDrawStyle()
        draw.lineWidth = 1.5 * k * Gui.getMainWindow().devicePixelRatioF()
        root.addChild(draw)
        depth = coin.SoDepthBuffer()
        depth.test = False
        root.addChild(depth)
        from .sketchorigin import glyph_points, glyph_shapes
        for pl, px, picked in items:

            points = [pl.multVec(App.Vector(x, y, 0)) for x, y in glyph_points(k * px)]
            sep = coin.SoSeparator()
            colour = coin.SoBaseColor()
            colour.rgb.setValue(*(_selection_blue() if picked else GREY))
            sep.addChild(colour)
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
            sep.addChild(coords)
            for shape in glyph_shapes():
                sep.addChild(shape)
            root.addChild(sep)
        view.getSceneGraph().addChild(root)
        self.node, self.view = root, view

    def clear(self):
        if self.node is not None and self.view is not None:
            try:
                self.view.getSceneGraph().removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("modelorigin.py:186", _fw_err)
        self.node = self.view = self.key = None
        self.count = 0

    def remove(self):
        self.timer.stop()
        self.clear()


ORIGIN = ModelOrigin()


def install():
    if not ORIGIN.timer.isActive():
        ORIGIN.timer.start()


def remove():
    ORIGIN.remove()
