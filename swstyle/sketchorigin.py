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

import FreeCADGui as Gui
from PySide import QtCore

from . import contextbar, paths
from .style import ui_scale

PARAM = "SketchOriginArrows"    # addon parameter (default on)
CROSS = "RootCrossMaterials"   # FreeCAD's axis line colours (Sketcher EditModeCoinManager)
ARROW_PX = 31
ARROW_X_PX = 16
HEAD_PX = 8                     # arrow head length on screen: a filled, narrow head
HEAD_HALF_PX = 3.2              # half the head's width
RED = (0.85, 0.1, 0.1)
POLL = 200


def enabled():
    return paths.params().GetBool(PARAM, True)


def _find(root, name):
    from pivy import coin
    search = coin.SoSearchAction()
    search.setName(coin.SbName(name))
    search.setInterest(coin.SoSearchAction.FIRST)
    search.apply(root)
    path = search.getPath()
    return path.getTail() if path is not None else None


def _same_node(a, b):
    """extapps/71: the same Coin node. getSceneGraph() gives a new wrapper on each call, so "is" never held:
    the arrows were taken out and put back on every poll, a 3D redraw each time while sketching."""
    if a is b:
        return True
    try:
        return a is not None and b is not None and int(a.this) == int(b.this)
    except Exception:
        return False


class SketchOrigin(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.cross = None       # FreeCAD's axis draw style, hidden
        self.sketch = None
        self.node = None        # the arrows
        self.root = None
        self.coords = None
        self.size = None        # (pixel size, placement) the arrows were drawn for
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(POLL)
        self.timer.timeout.connect(self.update)
        self.timer.start()

    def update(self):
        sketch = contextbar.sketch_in_edit() if self.shell.enabled and enabled() else None
        if sketch is None:
            self.hide()
            return
        try:
            view = Gui.ActiveDocument.ActiveView
            root = view.getSceneGraph()
        except Exception:
            self.hide()
            return
        if sketch is not self.sketch or not _same_node(root, self.root):
            self.hide()
            self.sketch, self.root = sketch, root
        self._hide_cross(root)
        self._arrows(view, sketch)

    def _hide_cross(self, root):
        cross = _find(root, CROSS)
        if cross is None:
            return
        if cross.transparency.getNum() != 2 or min(cross.transparency.getValues()) < 1.0:
            cross.transparency.setValues(0, 2, [1.0, 1.0])
        self.cross = cross

    def _pixel(self, view, sketch):
        """Sketch units per screen pixel at the origin."""
        origin = sketch.getGlobalPlacement().Base
        x, y = view.getPointOnScreen(origin)
        a = view.getPoint(int(x), int(y))
        b = view.getPoint(int(x) + 10, int(y))
        return max((b - a).Length / 10.0, 1e-9)

    def _arrows(self, view, sketch):
        from pivy import coin
        try:
            px = self._pixel(view, sketch)
            placement = sketch.getGlobalPlacement()
        except Exception:
            return
        key = (round(px, 9), tuple(placement.toMatrix().A))
        if self.node is not None and key == self.size:
            return
        self.size = key
        points = [placement.multVec(_v(x, y)) for x, y in glyph_points(px * ui_scale())]
        points = [(p.x, p.y, p.z) for p in points]
        if self.node is None:
            node = coin.SoSeparator()
            node.setName("SWSketchOriginArrows")
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            light = coin.SoLightModel()
            light.model = coin.SoLightModel.BASE_COLOR
            colour = coin.SoBaseColor()
            colour.rgb.setValue(*RED)
            draw = coin.SoDrawStyle()
            draw.lineWidth = 1.5 * ui_scale() * Gui.getMainWindow().devicePixelRatioF()
            depth = coin.SoDepthBuffer()
            depth.test = False
            self.coords = coin.SoCoordinate3()
            for child in (pick, light, colour, draw, depth, self.coords) + glyph_shapes():
                node.addChild(child)
            self.root.addChild(node)
            self.node = node
        self.coords.point.setValues(0, len(points), points)

    def hide(self):
        if self.node is not None and self.root is not None:
            try:
                self.root.removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("sketchorigin.py:145", _fw_err)
        if self.cross is not None and self.sketch is not None \
                and contextbar.sketch_in_edit() is self.sketch:
            # still editing (the look was switched off): FreeCAD's own lines back; once the
            # edit has ended FreeCAD has dropped the node and it is left alone. The node is
            # looked up again: FreeCAD rebuilds its edit graph and the one kept may be freed
            # (reading a field of a freed node crashed FreeCAD, fix59)
            try:
                cross = _find(Gui.ActiveDocument.ActiveView.getSceneGraph(), CROSS)
                if cross is not None:
                    cross.transparency.setValues(0, 2, [0.0, 0.0])
            except Exception as _fw_err:
                _fw_log("sketchorigin.py:157", _fw_err)
        self.node = self.coords = self.cross = self.sketch = self.root = self.size = None

    def remove(self):
        self.timer.stop()
        self.hide()


def glyph_points(units_per_px):
    ""

    ly, lx = ARROW_PX * units_per_px, ARROW_X_PX * units_per_px
    h, w = HEAD_PX * units_per_px, HEAD_HALF_PX * units_per_px
    return [(0, 0), (lx - h, 0), (0, 0), (0, ly - h),
            (lx, 0), (lx - h, w), (lx - h, -w), (0, ly), (-w, ly - h), (w, ly - h)]


def glyph_shapes():
    """The coin shapes that draw glyph_points from one SoCoordinate3."""
    from pivy import coin
    lines = coin.SoLineSet()
    lines.numVertices.setValues(0, 2, [2, 2])
    heads = coin.SoIndexedFaceSet()
    heads.coordIndex.setValues(0, 8, [4, 5, 6, -1, 7, 8, 9, -1])
    return (lines, heads)


def _v(x, y):
    import FreeCAD as App
    return App.Vector(x, y, 0)
