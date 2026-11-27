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

try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtGui, QtWidgets

COINCIDENT, CONCENTRIC, SYMMETRIC = "Coincident", "Concentric", "Symmetric"
EQUAL_CURVATURE = "Equal Curvature"     # fix316: at an Equal Curvature joint (fwsketch/eqcurv.py)
START, END, MID = 1, 2, 3
GREEN = (0.0, 0.6, 0.0)      # used only when the glyph colour is not set
OFFSET = 4


def _colour():
    """FreeCAD's glyph colour (View/ConstrainedIcoColor), as the other squares are filled."""
    try:
        packed = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("ConstrainedIcoColor", 0)
    except Exception:
        packed = 0
    if not packed:
        return QtGui.QColor.fromRgbF(*GREEN)
    return QtGui.QColor((packed >> 24) & 0xFF, (packed >> 16) & 0xFF, (packed >> 8) & 0xFF)


def _round(geo):
    return type(geo).__name__ in ("Circle", "ArcOfCircle", "Ellipse", "ArcOfEllipse")


def _shown(sketch, i, kind=None):
    try:
        from .. import sketchview
        if not sketchview.shown("Relations"):
            return False
    except Exception as _fw_err:
        _fw_log("fwsketch/pointglyphs.py:shown", _fw_err)
    try:        # Hide in the relation list (setVisibility) clears IsVisible; the virtual space is not shown
        c = sketch.Constraints[i]
        if kind == EQUAL_CURVATURE:         # its Tangent sits in hidden space so FreeCAD draws no Tangent glyph
            return 'IsVisible="0"' not in c.Content
        return not c.InVirtualSpace and 'IsVisible="0"' not in c.Content
    except Exception:
        return True


def relations(sketch):
    ""


    out = []
    try:
        geos = sketch.Geometry
        for i, c in enumerate(sketch.Constraints):
            if c.Type != "Coincident" or c.Second is None:
                continue
            a, b = (c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos))
            ga = geos[a[0]] if 0 <= a[0] < len(geos) else None
            gb = geos[b[0]] if 0 <= b[0] < len(geos) else None
            if ga is not None and gb is not None and a[1] == MID and b[1] == MID and _round(ga) and _round(gb):
                out.append((i, CONCENTRIC, a))
                continue
            ends = [g is not None and p in (START, END) and type(g).__name__ != "Point" for g, p in ((ga, a[1]), (gb, b[1]))]
            if all(ends):
                continue                      # a chain joint: merged, no glyph
            # the glyph sits by the point that stays put: the origin, a centre or a sketch point
            at = b if (gb is None or not ends[1]) else a
            out.append((i, COINCIDENT, at))
    except Exception as _fw_err:
        _fw_log("fwsketch/pointglyphs.py:relations", _fw_err)
    try:
        # fix316: Equal Curvature's square by the joint, at its Tangent's point (FreeCAD's Tangent glyph is not drawn)
        for i, c in enumerate(sketch.Constraints):
            if c.Type == "Tangent" and (c.Name or "").startswith("FWEqCurv_") and int(c.FirstPos) in (START, END):
                out.append((i, EQUAL_CURVATURE, (c.First, int(c.FirstPos))))
    except Exception as _fw_err:
        _fw_log("fwsketch/pointglyphs.py:equal curvature", _fw_err)
    try:

        # first one (glyphs.paint_symmetric); this square is the second point's
        from . import glyphs
        for i, second in glyphs.symmetric_points(sketch):
            out.append((i, SYMMETRIC, second))
    except Exception as _fw_err:
        _fw_log("fwsketch/pointglyphs.py:symmetric", _fw_err)
    return out


def symbol(p, kind, u):
    ""
    if kind == SYMMETRIC:
        from . import glyphs
        glyphs._symbol(p, "Constraint_Symmetric", u)
    elif kind == EQUAL_CURVATURE:
        from . import glyphs
        glyphs._symbol(p, "SW_EqualCurvature", u)
    elif kind == CONCENTRIC:
        p.drawEllipse(QtCore.QRectF(2.5 * u, 2.5 * u, 11 * u, 11 * u))
        p.drawEllipse(QtCore.QRectF(5.5 * u, 5.5 * u, 5 * u, 5 * u))
    else:
        p.drawLine(QtCore.QPointF(2.5 * u, 13.5 * u), QtCore.QPointF(7.6 * u, 8.4 * u))
        p.drawEllipse(QtCore.QRectF(7.5 * u, 3.5 * u, 5 * u, 5 * u))


def square(kind, side, colour):
    img = QtGui.QImage(side, side, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(colour)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    u = side / 16.0
    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), max(1.0, 1.4 * u)))
    p.setBrush(QtCore.Qt.NoBrush)
    symbol(p, kind, u)
    p.end()
    return img


class Overlay(QtWidgets.QWidget):
    """The squares over one view's viewport; repositioned on each repaint of the view."""

    def __init__(self, viewport, view):
        super().__init__(viewport)
        self.setObjectName("FwPointGlyphs")
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.viewport = viewport
        self.view = view
        self.items = []            # [(kind, App.Vector global)] to draw
        self.placed = []           # [(constraint index, kind, QPointF)] the last paint, for tests
        self._ids = []
        self._pending = False
        self.resize(viewport.size())
        viewport.installEventFilter(self)

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QtCore.QEvent.Resize:
            self.resize(self.viewport.size())
        if t in (QtCore.QEvent.Paint, QtCore.QEvent.UpdateRequest, QtCore.QEvent.Resize) and self.items and not self._pending:
            self._pending = True
            QtCore.QTimer.singleShot(0, self._again)
        return False

    def _again(self):
        self._pending = False
        try:
            self.update()
        except RuntimeError:
            pass

    def set_items(self, ids, items):
        self._ids, self.items = ids, items
        self.setVisible(bool(items))
        if items:
            self.raise_()
        self.update()

    def _screen(self, v):
        """The view's pixel of a global point, in this widget's (top-left) coordinates."""
        x, y = self.view.getPointOnViewport(v)[:2]
        ratio = self.viewport.devicePixelRatioF() if hasattr(self.viewport, "devicePixelRatioF") else 1.0
        h = self.viewport.height() * ratio
        return QtCore.QPointF(x / ratio, (h - y) / ratio)

    def paintEvent(self, _event):
        self.placed = []
        if not self.items:
            return
        try:
            gdoc = Gui.ActiveDocument
            if gdoc is None or gdoc.getInEdit() is None:
                self.items, self._ids = [], []          # the sketch left edit: nothing until the next one
                self.hide()
                return
        except Exception as _fw_err:
            _fw_log("fwsketch/pointglyphs.py:edit", _fw_err)
        try:
            from . import glyphs
            size = glyphs.icon_size()
        except Exception:
            size = 15
        ratio = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        side = max(4, int(round(size * ratio)))
        colour = _colour()
        cache = {}
        p = QtGui.QPainter(self)
        try:
            for i, (kind, v) in zip(self._ids, self.items):
                try:
                    at = self._screen(v)
                except Exception:
                    continue
                if kind not in cache:
                    img = square(kind, side, colour)
                    img.setDevicePixelRatio(ratio)
                    cache[kind] = img
                p.drawImage(QtCore.QPointF(at.x() + OFFSET, at.y() + OFFSET), cache[kind])
                self.placed.append((i, kind, at))
        finally:
            p.end()


_state = {"overlay": None}


def _overlay(view):
    o = _state.get("overlay")
    try:
        if o is not None and o.view is view and o.isVisible() is not None:
            return o
    except RuntimeError:
        o = None
    try:
        viewport = view.graphicsView().viewport()
    except Exception:
        return None
    if o is not None:
        try:
            o.viewport.removeEventFilter(o)
            o.deleteLater()
        except RuntimeError:
            pass
    o = Overlay(viewport, view)
    _state["overlay"] = o
    return o


def update(view, sketch):
    """Puts the Coincident and Concentric squares of the sketch in edit over the view (glyphs.paint)."""
    from . import glyphs
    items, ids = [], []
    if glyphs.wanted():
        try:
            placement = sketch.getGlobalPlacement()
            for i, kind, (geo, pos) in relations(sketch):
                if not _shown(sketch, i, kind):
                    continue
                v = sketch.getPoint(geo, pos) if geo >= 0 or geo == -1 else None
                if v is None:
                    continue
                ids.append(i)
                items.append((kind, placement.multVec(v)))
        except Exception as _fw_err:
            _fw_log("fwsketch/pointglyphs.py:update", _fw_err)
    o = _overlay(view) if items or _state.get("overlay") is not None else None
    if o is not None:
        o.set_items(ids, items)
    return items


def clear():
    o = _state.get("overlay")
    if o is not None:
        try:
            o.set_items([], [])
        except RuntimeError:
            _state["overlay"] = None
