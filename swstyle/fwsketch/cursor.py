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

from PySide import QtCore, QtGui

try:
    from PySide import QtSvg
except ImportError:  # pragma: no cover
    QtSvg = None

HORIZONTAL, VERTICAL, COINCIDENT, ON_EDGE, MIDPOINT, INTERSECTION, TANGENT, PARALLEL, PERPENDICULAR = (
    "Horizontal", "Vertical", "Coincident", "OnEdge", "Midpoint", "Intersection", "Tangent", "Parallel",
    "Perpendicular")

SYMBOLS = {
    HORIZONTAL: '<path d="M3.5 8H12.5"/>',
    VERTICAL: '<path d="M8 3.5V12.5"/>',
    COINCIDENT: '<path d="M3.5 12.5L8 6.5L12.5 12.5"/><circle cx="8" cy="6.5" r="1.9" fill="#141414"/>',
    ON_EDGE: '<path d="M2.5 12.5Q8 1.5 13.5 12.5"/><circle cx="5.25" cy="8.4" r="1.9" fill="#141414"/>',
    MIDPOINT: '<path d="M2.5 10H13.5"/><path d="M2.5 7.8V12.2M13.5 7.8V12.2" stroke-width="1"/>'
              '<circle cx="8" cy="10" r="2" fill="#141414"/>',
    INTERSECTION: '<path d="M3.5 3.5L12.5 12.5M12.5 3.5L3.5 12.5"/><circle cx="8" cy="8" r="1.7" fill="#141414"/>',
    TANGENT: '<path d="M2.5 6.4H13.5"/><circle cx="8" cy="10" r="3.6"/>',
    PARALLEL: '<path d="M4 12.5L8.5 3.5M7.5 12.5L12 3.5"/>',
    PERPENDICULAR: '<path d="M8 3.5V12M3.5 12H12.5"/>',
}

for _axis in "XYZ":
    SYMBOLS["Along" + _axis] = ('<text x="8" y="12.3" font-family="Arial" font-size="10.5" font-weight="bold" '
                                'text-anchor="middle" fill="#141414" stroke="none">%s</text>' % _axis)
SYMBOLS["OnPlane"] = '<path d="M2.5 11.5L6 5H13.5L10 11.5Z" stroke-width="1.2"/>'

# Symmetric and Fix
MERGE, CONCENTRIC, EQUAL, COLLINEAR, SYMMETRIC, FIX = "Merge", "Concentric", "Equal", "Collinear", "Symmetric", "Fix"
SYMBOLS.update({
    MERGE: '<circle cx="8" cy="8" r="4.8"/><circle cx="8" cy="8" r="1.9" fill="#141414"/>',
    CONCENTRIC: '<circle cx="8" cy="8" r="5.2"/><circle cx="8" cy="8" r="2.4"/>',
    EQUAL: '<path d="M3.5 6.2H12.5M3.5 9.8H12.5"/>',
    COLLINEAR: '<path d="M2.5 13.5L6.5 9.5M9.5 6.5L13.5 2.5"/>',
    SYMMETRIC: '<path d="M8 2.5V13.5"/><path d="M2.5 5.5L6 8L2.5 10.5ZM13.5 5.5L10 8L13.5 10.5Z" fill="#141414" stroke-width="1"/>',
    FIX: '<path d="M4.5 7.5H11.5V13H4.5Z"/><path d="M6 7.5V5.5A2 2 0 0 1 10 5.5V7.5" stroke-width="1.3"/>',
})
TILE = 16  # logical pixels


def svg(glyph, alignment_only=False):
    tile = ('<rect x="0.5" y="0.5" width="15" height="15" rx="2.5" fill="#FFFFFF" stroke="#5A5A5A"/>'
            if alignment_only else
            '<rect x="0.5" y="0.5" width="15" height="15" rx="2.5" fill="#FFD447" stroke="#6B5300"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">' + tile +
            '<g fill="none" stroke="#141414" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
            + SYMBOLS[glyph] + '</g></svg>')


def glyphs_for(suggestions):
    """Glyphs for the suggestions, in order, each at most once. Two point-on-object suggestions on
    different edges place the point on both: the intersection glyph."""
    on_object = [s.geo for s in suggestions if s.type == "PointOnObject"]
    intersection = len(on_object) > 1 and any(g != on_object[0] for g in on_object)
    table = {"Horizontal": HORIZONTAL, "Vertical": VERTICAL, "Coincident": COINCIDENT,
             "PointOnObject": INTERSECTION if intersection else ON_EDGE, "Symmetric": MIDPOINT, "MidpointOf": MIDPOINT,
             "Tangent": TANGENT, "Parallel": PARALLEL, "Perpendicular": PERPENDICULAR,
             "Merge": MERGE, "Concentric": CONCENTRIC, "Equal": EQUAL, "Collinear": COLLINEAR,
             "SymmetricTo": SYMMETRIC, "Block": FIX, "Fix": FIX}
    out = []
    for s in suggestions:
        g = table.get(s.type)
        if s.type == "PointOnObject" and getattr(s, "pos", 0) not in (0, None) and not intersection:
            g = COINCIDENT
        if g is not None and g not in out:
            out.append(g)
    return out


def _is_xcb():
    try:
        return QtGui.QGuiApplication.platformName() == "xcb"
    except Exception:
        return False


def crosshair_color():
    """The View parameter CursorCrosshairColor as (r, g, b) 0-255, white when unset."""
    try:
        packed = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("CursorCrosshairColor",
                                                                                       0xFFFFFFFF)
    except Exception:
        packed = 0xFFFFFFFF
    return (packed >> 24) & 0xFF, (packed >> 16) & 0xFF, (packed >> 8) & 0xFF


def pencil_tool(icon_name):
    ""

    name = icon_name or ""
    return "_Create_" in name or name in ("Sketcher_Pointer_Regular_Polygon", "Sketcher_Pointer_Slot")


_drag_cursors = {}

BADGE_BLUE = (20, 90, 220)


def _line_badge(w, h):
    ""
    img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.scale(w / 32.0, h / 32.0)
    blue = QtGui.QColor(*BADGE_BLUE)
    p.setPen(QtGui.QPen(blue, 2.6, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
    p.drawLine(QtCore.QPointF(22, 30), QtCore.QPointF(30, 20))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(blue)
    for x, y in ((22, 30), (30, 20)):
        p.drawEllipse(QtCore.QPointF(x, y), 1.8, 1.8)
    p.end()
    return img


def _arrow(painter):
    """The normal pointer arrow, tip at (1, 1)."""
    arrow = QtGui.QPainterPath()
    arrow.moveTo(1, 1)
    for x, y in ((1, 17), (5, 13), (8, 20), (10.5, 19), (7.5, 12.5), (13, 12.5)):
        arrow.lineTo(x, y)
    arrow.closeSubpath()
    painter.setPen(QtGui.QPen(QtCore.Qt.white, 1.2))
    painter.setBrush(QtCore.Qt.black)
    painter.drawPath(arrow)


def _dimension_badge(p):
    """A small blue horizontal dimension: two extension lines and the dimension line with arrows."""
    blue = QtGui.QColor(*BADGE_BLUE)
    p.setPen(QtGui.QPen(blue, 1.3))
    p.drawLine(QtCore.QPointF(15.5, 18), QtCore.QPointF(15.5, 27))
    p.drawLine(QtCore.QPointF(28.5, 18), QtCore.QPointF(28.5, 27))
    p.drawLine(QtCore.QPointF(16.5, 22.5), QtCore.QPointF(27.5, 22.5))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(blue)
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(16, 22.5), QtCore.QPointF(19.5, 20.6), QtCore.QPointF(19.5, 24.4)]))
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(28, 22.5), QtCore.QPointF(24.5, 20.6), QtCore.QPointF(24.5, 24.4)]))


ARROW_BADGES = {"Constraint_Dimension": _dimension_badge}


def arrow_with_badge(ratio, draw_badge):
    pm = QtGui.QPixmap(QtCore.QSize(32, 32) * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    _arrow(p)
    draw_badge(p)
    p.end()
    return pm


def drag_cursor(ratio):
    ""

    key = round(ratio, 3)
    if key in _drag_cursors:
        return _drag_cursors[key]
    pm = QtGui.QPixmap(QtCore.QSize(32, 32) * ratio)
    pm.setDevicePixelRatio(ratio)
    pm.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    arrow = QtGui.QPainterPath()
    arrow.moveTo(1, 1)
    for x, y in ((1, 17), (5, 13), (8, 20), (10.5, 19), (7.5, 12.5), (13, 12.5)):
        arrow.lineTo(x, y)
    arrow.closeSubpath()
    painter.setPen(QtGui.QPen(QtCore.Qt.white, 1.2))
    painter.setBrush(QtCore.Qt.black)
    painter.drawPath(arrow)
    painter.setPen(QtGui.QPen(QtGui.QColor(90, 90, 90), 1.0))
    painter.setBrush(QtGui.QColor(175, 175, 175))
    painter.drawEllipse(QtCore.QPointF(20.5, 22.5), 5.5, 5.5)
    painter.setPen(QtGui.QPen(QtGui.QColor(70, 70, 70), 1.2))
    painter.drawLine(QtCore.QPointF(17.5, 22.5), QtCore.QPointF(23.5, 22.5))
    painter.drawLine(QtCore.QPointF(20.5, 19.5), QtCore.QPointF(20.5, 25.5))
    painter.end()
    hot = QtCore.QPoint(1, 1)
    if _is_xcb():
        hot = QtCore.QPoint(int(round(ratio)), int(round(ratio)))
    _drag_cursors[key] = QtGui.QCursor(pm, hot.x(), hot.y())
    return _drag_cursors[key]


class ToolCursor:
    """Builds and caches the pointer pixmaps of one tool at the view's pixel ratio."""

    def __init__(self, icon_name, ratio, badge=None):
        self.icon_name = icon_name
        self.ratio = ratio
        if badge in ARROW_BADGES:

            # badge, not a crosshair (fix233, look audit U1)
            self.base = arrow_with_badge(ratio, ARROW_BADGES[badge])
            self.hot = QtCore.QPoint(1, 1)
            if _is_xcb():
                self.hot = QtCore.QPoint(int(round(ratio)), int(round(ratio)))
            self._tiles = {}
            self._cursors = {}
            return
        self.base = self._base_pixmap()
        if badge:
            self.base = self._with_badge(self.base, badge)
        self.hot = QtCore.QPoint(8, 8)
        if _is_xcb():
            self.hot = QtCore.QPoint(int(round(8 * ratio)), int(round(8 * ratio)))
        self._tiles = {}
        self._cursors = {}

    # --- pixmaps -----------------------------------------------------------------------------
    def _base_pixmap(self):
        pm = QtGui.QPixmap()
        try:
            icon = Gui.getIcon(self.icon_name)
            if icon is not None and not icon.isNull():
                if self.ratio == 1.0:
                    pm = icon.pixmap(QtCore.QSize(64, 64)).scaled(32, 32, QtCore.Qt.KeepAspectRatio,
                                                                  QtCore.Qt.SmoothTransformation)
                else:
                    pm = icon.pixmap(QtCore.QSize(32, 32), self.ratio)
        except Exception:
            pm = QtGui.QPixmap()
        if pm.isNull():
            pm = self._drawn_crosshair()
        pm = self._recolour(pm)
        if pencil_tool(self.icon_name):
            pm = self._pencil(pm)
        return pm

    def _pencil(self, pm):
        ""

        ratio = self.ratio
        src = pm.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
        w, h = src.width(), src.height()
        k = w / 32.0 if w else ratio
        for y in range(min(h, int(19 * k))):
            for x in range(min(w, int(19 * k))):
                c = src.pixelColor(x, y)
                if c.alpha() and not (c.red() > 120 and c.red() > c.green() + 50 and c.red() > c.blue() + 50):
                    src.setPixelColor(x, y, QtGui.QColor(0, 0, 0, 0))

        for y in range(h):
            for x in range(w):
                c = src.pixelColor(x, y)
                if c.alpha() and c.red() > 120 and c.red() > c.green() + 50 and c.red() > c.blue() + 50:
                    src.setPixelColor(x, y, QtGui.QColor(BADGE_BLUE[0], BADGE_BLUE[1], BADGE_BLUE[2], c.alpha()))
        if self.icon_name == "Sketcher_Pointer_Create_Line":
            src = _line_badge(w, h)
        size = int(round(32 * ratio))
        out = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
        out.fill(0)
        p = QtGui.QPainter(out)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        p.scale(ratio, ratio)
        p.drawImage(QtCore.QRectF(17, 17, 15, 15), src, QtCore.QRectF(src.rect()))
        # the pencil, tip on the hot spot (8, 8), body down to the right
        p.translate(8, 8)
        p.rotate(45)
        outline = QtGui.QPen(QtGui.QColor(40, 30, 20), 1.0)
        p.setPen(outline)
        tip = QtGui.QPolygonF([QtCore.QPointF(0, 0), QtCore.QPointF(5, -2.4), QtCore.QPointF(5, 2.4)])
        p.setBrush(QtGui.QColor(232, 196, 160))
        p.drawPolygon(tip)
        p.setBrush(QtGui.QColor(60, 60, 60))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(0, 0), QtCore.QPointF(1.8, -0.9), QtCore.QPointF(1.8, 0.9)]))
        p.setBrush(QtGui.QColor(250, 160, 30))
        p.drawRect(QtCore.QRectF(5, -2.4, 9, 4.8))
        p.setBrush(QtGui.QColor(190, 190, 190))
        p.drawRect(QtCore.QRectF(14, -2.4, 1.6, 4.8))
        p.setBrush(QtGui.QColor(235, 120, 130))
        p.drawRoundedRect(QtCore.QRectF(15.6, -2.4, 2.6, 4.8), 1.2, 1.2)
        p.end()
        res = QtGui.QPixmap.fromImage(out)
        res.setDevicePixelRatio(ratio)
        return res

    def _with_badge(self, pm, badge):
        """A 16 px tool icon at (16, 16) of the crosshair, as the C++ tools draw theirs."""
        try:
            icon = Gui.getIcon(badge)
            if icon is None or icon.isNull():
                return pm
            size = int(round(16 * self.ratio))
            bp = icon.pixmap(QtCore.QSize(size, size))
            bp.setDevicePixelRatio(self.ratio)
            out = pm.copy()
            p = QtGui.QPainter(out)
            p.drawPixmap(QtCore.QPointF(16, 16), bp)
            p.end()
            return out
        except Exception:
            return pm

    def _drawn_crosshair(self):
        """A plain crosshair when the icon is missing: 32 x 32, hot spot (8, 8)."""
        size = int(32 * self.ratio)
        pm = QtGui.QPixmap(size, size)
        pm.setDevicePixelRatio(self.ratio)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255))
        pen.setWidth(1)
        p.setPen(pen)
        p.drawLine(8, 0, 8, 16)
        p.drawLine(0, 8, 16, 8)
        p.end()
        return pm

    def _recolour(self, pm):
        """White pixels of the crosshair take the CursorCrosshairColor (BitmapFactory colour map)."""
        r, g, b = crosshair_color()
        if (r, g, b) == (255, 255, 255):
            return pm
        img = pm.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.red() == 255 and c.green() == 255 and c.blue() == 255 and c.alpha() > 0:
                    img.setPixelColor(x, y, QtGui.QColor(r, g, b, c.alpha()))
        out = QtGui.QPixmap.fromImage(img)
        out.setDevicePixelRatio(pm.devicePixelRatio())
        return out

    def tile(self, glyph, alignment_only):
        key = (glyph, alignment_only)
        if key not in self._tiles:
            size = int(round(TILE * self.ratio))
            img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
            img.fill(0)
            if QtSvg is not None:
                renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg(glyph, alignment_only).encode("utf-8")))
                p = QtGui.QPainter(img)
                renderer.render(p)
                p.end()
            pm = QtGui.QPixmap.fromImage(img)
            pm.setDevicePixelRatio(self.ratio)
            self._tiles[key] = pm
        return self._tiles[key]

    # --- cursors -----------------------------------------------------------------------------
    def cursor(self, glyphs=(), white=()):
        """QCursor with the tool's crosshair and one tile per glyph (yellow), then the white ones."""
        key = (tuple(glyphs), tuple(white))
        if key in self._cursors:
            return self._cursors[key]
        tiles = [self.tile(g, False) for g in glyphs] + [self.tile(g, True) for g in white]
        if not tiles:
            cur = QtGui.QCursor(self.base, self.hot.x(), self.hot.y())
        else:
            ratio = self.ratio
            bw = self.base.width() / self.base.devicePixelRatio()
            bh = self.base.height() / self.base.devicePixelRatio()
            tail = sum(t.width() / t.devicePixelRatio() for t in tiles)
            pm = QtGui.QPixmap(int(round((bw + tail) * ratio)), int(round(bh * ratio)))
            pm.setDevicePixelRatio(ratio)
            pm.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(pm)
            p.drawPixmap(QtCore.QPointF(0, 0), self.base)
            x = bw
            for t in tiles:
                th = t.height() / t.devicePixelRatio()
                p.drawPixmap(QtCore.QPointF(x, bh - th), t)
                x += t.width() / t.devicePixelRatio()
            p.end()
            cur = QtGui.QCursor(pm, self.hot.x(), self.hot.y())
        self._cursors[key] = cur
        return cur


def drag_tool_cursor(ratio):
    """A ToolCursor for the tail beside the drag pointer (the drag arrow, its hot spot near the top left)."""
    tc = ToolCursor.__new__(ToolCursor)
    tc.icon_name, tc.ratio = "", ratio
    tc.base = drag_cursor(ratio).pixmap()
    tc.hot = QtCore.QPoint(1, 1)
    tc._tiles, tc._cursors = {}, {}
    return tc


class Tail:
    ""




    GAP = 4     # logical pixels between the crosshair's hot spot area and the first tile

    def __init__(self, viewport, tool_cursor):
        self.viewport = viewport
        self.tc = tool_cursor
        self.label = None
        self.key = None

    def _make(self):
        from PySide import QtWidgets
        lab = QtWidgets.QLabel(self.viewport)
        lab.setObjectName("FwRelationGlyphTail")
        lab.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        lab.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        lab.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        lab.setStyleSheet("background: transparent; border: none;")
        lab.setFocusPolicy(QtCore.Qt.NoFocus)
        self.label = lab

    def show(self, glyphs=(), white=()):
        key = (tuple(glyphs), tuple(white))
        if not key[0] and not key[1]:
            self.hide()
            return
        try:
            if self.label is None:
                self._make()
            if key != self.key:
                tiles = [self.tc.tile(g, False) for g in glyphs] + [self.tc.tile(g, True) for g in white]
                ratio = self.tc.ratio
                w = sum(t.width() / t.devicePixelRatio() for t in tiles)
                h = max(t.height() / t.devicePixelRatio() for t in tiles)
                pm = QtGui.QPixmap(int(round(w * ratio)), int(round(h * ratio)))
                pm.setDevicePixelRatio(ratio)
                pm.fill(QtCore.Qt.transparent)
                p = QtGui.QPainter(pm)
                x = 0.0
                for t in tiles:
                    p.drawPixmap(QtCore.QPointF(x, 0), t)
                    x += t.width() / t.devicePixelRatio()
                p.end()
                self.label.setPixmap(pm)
                self.label.resize(int(round(w)), int(round(h)))
                self.key = key
            at = self.viewport.mapFromGlobal(QtGui.QCursor.pos())
            bw = self.tc.base.width() / self.tc.base.devicePixelRatio()
            bh = self.tc.base.height() / self.tc.base.devicePixelRatio()
            # the tiles sit where the old pointer tail had them: right of the crosshair, along its bottom
            self.label.move(int(round(at.x() - 8 + bw)), int(round(at.y() - 8 + bh - self.label.height())))
            self.label.show()
            self.label.raise_()
        except RuntimeError:
            self.label = None

    def hide(self):
        try:
            if self.label is not None:
                self.label.hide()
        except RuntimeError:
            self.label = None

    def close(self):
        try:
            if self.label is not None:
                self.label.hide()
                self.label.deleteLater()
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/cursor.py:381", _fw_err)
        self.label = None
        self.key = None
