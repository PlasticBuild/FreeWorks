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

PAGE = "Virtual Sharps"
STYLE = ("Virtual sharp style", "Plus")
EXTENSION = ("Extension lines", False)
STYLES = ("Plus", "Plus with lines", "Star", "Dot", "Hollow dot", "Witness lines")
NODE_NAME = "FwVirtualSharps"
_watcher = None


def style(doc=None):
    """(style, extension lines) of the document (its Document Properties)."""
    doc = doc or App.ActiveDocument
    try:
        from .. import optionspages
        s = optionspages.doc_value(doc, PAGE, *STYLE)
        e = optionspages.doc_value(doc, PAGE, *EXTENSION)
    except Exception:
        s, e = STYLE[1], EXTENSION[1]
    if s not in STYLES:
        s = STYLE[1]
    return s, bool(e)


def _end_points(g):
    try:
        return [(g.StartPoint.x, g.StartPoint.y), (g.EndPoint.x, g.EndPoint.y)]
    except Exception:
        return []


def sharps(sketch):
    """[(point geo id, (x, y), [(x, y) of the nearer end of each entity])] of the sketch's virtual
    sharps: points held on two or more curves by On Entity (PointOnObject) relations."""
    on = {}
    geos = sketch.Geometry
    for c in sketch.Constraints:
        if c.Type != "PointOnObject" or c.First < 0 or c.Second < 0 or c.First >= len(geos):
            continue
        if geos[c.First].TypeId != "Part::GeomPoint" or c.Second >= len(geos):
            continue
        curves = on.setdefault(c.First, [])
        if c.Second not in curves:
            curves.append(c.Second)
    out = []
    for i, curves in on.items():
        if len(curves) < 2:
            continue
        p = geos[i]
        at = (p.X, p.Y)
        ends = []
        for g in curves[:2]:
            pts = _end_points(geos[g])
            if pts:
                ends.append(min(pts, key=lambda q: (q[0] - at[0]) ** 2 + (q[1] - at[1]) ** 2))
        out.append((i, at, ends))
    return out


GLYPH_PX = 7.0


def glyph(kind, at, h):
    """(line strips, filled polygon or None) of the style's glyph at at, h model units a half width."""
    import math
    x, y = at
    if kind in ("Plus", "Plus with lines"):
        return [[(x - h, y), (x + h, y)], [(x, y - h), (x, y + h)]], None
    if kind == "Star":
        d = h * 0.7071
        return [[(x - h, y), (x + h, y)], [(x, y - h), (x, y + h)], [(x - d, y - d), (x + d, y + d)],
                [(x - d, y + d), (x + d, y - d)]], None
    if kind in ("Dot", "Hollow dot"):
        r = h * 0.6
        ring = [(x + r * math.cos(k * math.pi / 8), y + r * math.sin(k * math.pi / 8)) for k in range(17)]
        return [ring], (ring[:-1] if kind == "Dot" else None)
    return [], None


def _colour():
    ""

    try:
        v = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("EditedEdgeColor", 0)
        if v:
            return ((v >> 24) & 0xFF) / 255.0, ((v >> 16) & 0xFF) / 255.0, ((v >> 8) & 0xFF) / 255.0
    except Exception as _fw_err:
        _fw_log("fwsketch/virtualsharps.py:112", _fw_err)
    return 0.0, 0.0, 1.0


def build(sketch, found, kind, extension, half=1.0):
    """The Coin group that draws the sharps, in the sketch's placement."""
    from pivy import coin
    root = coin.SoAnnotation()
    root.setName(NODE_NAME)
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    col = coin.SoBaseColor()
    col.rgb = _colour()
    tr = coin.SoTransform()
    pl = sketch.getGlobalPlacement()
    tr.translation.setValue(*pl.Base)
    tr.rotation.setValue(*pl.Rotation.Q)
    for n in (pick, light, col, tr):
        root.addChild(n)
    z = 0.006           # over FreeCAD's sketch lines and points
    strips, fills = [], []
    for _i, at, _e in found:
        st, fill = glyph(kind, at, half)
        strips += st
        if fill:
            fills.append(fill)
    if strips:
        pts = [(p[0], p[1], z) for st in strips for p in st]
        co = coin.SoCoordinate3()
        co.point.setValues(0, len(pts), pts)
        ls = coin.SoLineSet()
        ls.numVertices.setValues(0, len(strips), [len(st) for st in strips])
        style = coin.SoDrawStyle()
        style.lineWidth = 1.5
        sep = coin.SoSeparator()
        sep.setName("FwVirtualSharpGlyphs")
        for n in (style, co, ls):
            sep.addChild(n)
        root.addChild(sep)
    if fills:
        pts = [(p[0], p[1], z) for f in fills for p in f]
        co = coin.SoCoordinate3()
        co.point.setValues(0, len(pts), pts)
        fs = coin.SoFaceSet()
        fs.numVertices.setValues(0, len(fills), [len(f) for f in fills])
        sep = coin.SoSeparator()
        sep.setName("FwVirtualSharpDots")
        for n in (co, fs):
            sep.addChild(n)
        root.addChild(sep)
    if kind in ("Plus with lines", "Witness lines") or extension:
        pts, counts = [], []
        for _i, at, ends in found:
            for q in ends:
                pts += [(at[0], at[1], z), (q[0], q[1], z)]
                counts.append(2)
        if pts:
            style = coin.SoDrawStyle()
            style.lineWidth = 1
            style.linePattern = 0xFFFF if kind == "Witness lines" else 0xF0F0
            co = coin.SoCoordinate3()
            co.point.setValues(0, len(pts), pts)
            ls = coin.SoLineSet()
            ls.numVertices.setValues(0, len(counts), counts)
            sep = coin.SoSeparator()
            sep.setName("FwVirtualSharpLines")
            for n in (style, co, ls):
                sep.addChild(n)
            root.addChild(sep)
    return root


def _half_width(view):
    """GLYPH_PX in model units at the view's present zoom (the glyph keeps its size on screen)."""
    try:
        cam = view.getCameraNode()
        w, h = view.getSize()
        height = cam.height.getValue() if hasattr(cam, "height") else 100.0
        try:
            ratio = view.graphicsView().viewport().devicePixelRatioF()
        except Exception:
            ratio = 1.0
        return GLYPH_PX * ratio * height / max(h, 1)
    except Exception:
        return 1.0


def _edited():
    try:
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc is not None else None
        obj = getattr(vp, "Object", None)
        if obj is not None and obj.TypeId == "Sketcher::SketchObject":
            return gdoc, obj
    except Exception as _fw_err:
        _fw_log("fwsketch/virtualsharps.py:209", _fw_err)
    return None, None


class Watcher(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.graph = self.node = self.signature = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def clear(self):
        if self.graph is not None and self.node is not None:
            try:
                self.graph.removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("fwsketch/virtualsharps.py:227", _fw_err)
        self.graph = self.node = self.signature = None

    def refresh(self):
        try:
            self._refresh()
        except Exception as error:
            App.Console.PrintLog("FreeCAD virtual sharps: %s\n" % error)
            self.clear()

    def _refresh(self):
        gdoc, sketch = _edited()
        if sketch is None:
            self.clear()
            return
        graph = gdoc.ActiveView.getSceneGraph()
        found = sharps(sketch)
        kind, extension = style(sketch.Document)
        pl = sketch.getGlobalPlacement()
        half = _half_width(gdoc.ActiveView)
        signature = (sketch.Document.Name, sketch.Name, tuple((i, at, tuple(e)) for i, at, e in found),
                     kind, extension, tuple(pl.Base), tuple(pl.Rotation.Q), round(half, 9))
        if signature == self.signature and self.graph is graph and self.node is not None \
                and graph.findChild(self.node) >= 0:
            return
        self.clear()
        self.signature = signature
        if not found:
            return
        self.graph = graph
        self.node = build(sketch, found, kind, extension, half)
        graph.addChild(self.node)

    def stop(self):
        self.timer.stop()
        self.clear()


def start():
    global _watcher
    if _watcher is None:
        _watcher = Watcher()
    return _watcher


def stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
        _watcher = None
