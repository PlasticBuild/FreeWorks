# SPDX-License-Identifier: LGPL-2.1-or-later
""








from PySide import QtCore, QtGui, QtWidgets

SIZE = 28


def _colours():
    try:
        from . import pmlayout
        if pmlayout._dark():
            return pmlayout.BLUE_DARK, pmlayout.GREY_DARK
        return pmlayout.BLUE, pmlayout.GREY
    except Exception:
        return QtGui.QColor(0x2f, 0x6f, 0xc4), QtGui.QColor(0x5a, 0x5a, 0x5a)


RED = QtGui.QColor(0xc2, 0x30, 0x2a)
PINK = QtGui.QColor(0xd0, 0x40, 0x8a)


def _pt(x, y):
    return QtCore.QPointF(x, y)


def _rect(p, x, y, w, h, fill, edge=None):
    p.setPen(QtGui.QPen(edge or fill.darker(140), 1.0))
    p.setBrush(fill)
    p.drawRect(QtCore.QRectF(x, y, w, h))


def _poly(p, pts, fill, edge=None):
    p.setPen(QtGui.QPen(edge or fill.darker(140), 1.0))
    p.setBrush(fill)
    p.drawPolygon(QtGui.QPolygonF([_pt(x, y) for x, y in pts]))


def _line(p, x0, y0, x1, y1, colour, width=1.2, dash=False):
    pen = QtGui.QPen(colour, width)
    if dash:
        pen.setStyle(QtCore.Qt.DashLine)
    p.setPen(pen)
    p.drawLine(_pt(x0, y0), _pt(x1, y1))


def _dim(p, x0, y0, x1, y1):
    """A red dimension line with arrow heads at both ends."""
    import math
    _line(p, x0, y0, x1, y1, RED, 1.0)
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    for (x, y, s) in ((x0, y0, 1), (x1, y1, -1)):
        for t in (1, -1):
            _line(p, x, y, x + s * 3 * ux - t * 2 * uy, y + s * 3 * uy + t * 2 * ux, RED, 1.0)


def _corner(p, kind, blue, grey):
    """Two members meeting at a corner, from above."""
    light = QtGui.QColor(blue).lighter(150)
    if kind == "End Trim":
        _line(p, 18, 3, 18, 25, PINK, 1.4, dash=True)                   # the trimming boundary
        _rect(p, 3, 10, 15, 8, light)
        _rect(p, 18, 10, 6, 8, QtGui.QColor(0, 0, 0, 0), grey)          # the part cut away
    elif kind == "End Miter":
        _poly(p, [(3, 18), (3, 10), (18, 10), (10, 18)], light)
        _poly(p, [(18, 10), (18, 25), (10, 25), (10, 18)], light)
    elif kind == "End Butt1":
        _rect(p, 3, 10, 15, 8, light)                                   # runs through the corner
        _rect(p, 10, 18, 8, 7, QtGui.QColor(grey).lighter(170))         # butts against it
    else:                                                               # End Butt2
        _rect(p, 10, 10, 8, 15, light)
        _rect(p, 3, 10, 7, 8, QtGui.QColor(grey).lighter(170))


def _cap(p, kind, blue, grey):
    """A hollow member's end from the side, the cap in blue."""
    wall = QtGui.QColor(grey).lighter(160)
    _rect(p, 3, 7, 16, 3, wall)
    _rect(p, 3, 18, 16, 3, wall)
    if kind == "Outward":
        _rect(p, 19, 7, 4, 14, blue)
    elif kind == "Inward":
        _rect(p, 15, 7, 4, 14, blue)
        _line(p, 19, 4, 19, 24, grey, 1.0, dash=True)
    else:                                                               # Internal: inside the walls, inset
        _rect(p, 13, 10, 4, 8, blue)
        _line(p, 19, 4, 19, 24, grey, 1.0, dash=True)


def _gusset(p, kind, blue, grey):
    light = QtGui.QColor(grey).lighter(170)
    if kind in ("Polygonal", "Triangular"):
        _rect(p, 3, 3, 5, 22, light)
        _rect(p, 8, 20, 17, 5, light)
        if kind == "Triangular":
            _poly(p, [(8, 6), (8, 20), (22, 20)], blue)
        else:
            _poly(p, [(8, 6), (8, 20), (22, 20), (22, 16), (12, 6)], blue)
        return
    if kind in ("Inner side", "Both sides", "Outer side"):
        # end on: the member's web upright, the gusset plate's thickness to one side or centred on it
        _rect(p, 3, 22, 22, 3, light)
        _line(p, 14, 2, 14, 22, grey, 1.0, dash=True)
        x = {"Inner side": 9, "Both sides": 11.5, "Outer side": 14}[kind]
        _rect(p, x, 6, 5, 16, blue)
        return
    if kind in ("Rounded gusset", "Flat gusset"):      # pkg439: Sheet Metal Gusset profile, across the bend
        _rect(p, 3, 3, 5, 22, light)
        _rect(p, 8, 20, 17, 5, light)
        if kind == "Rounded gusset":
            path = QtGui.QPainterPath(_pt(8, 9))
            path.quadTo(_pt(9, 19), _pt(19, 20))
            path.lineTo(_pt(8, 20))
            path.closeSubpath()
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(blue)
            p.drawPath(path)
        else:
            _poly(p, [(8, 9), (12, 9), (19, 16), (19, 20), (8, 20)], blue)
        return
    # Start / Mid point / End: along the joint edge
    _rect(p, 2, 20, 24, 5, light)
    x = {"Start": 3, "Mid point": 10, "End": 17}.get(kind, 10)
    _poly(p, [(x, 20), (x + 8, 20), (x, 9)], blue)
    _line(p, 2, 27, 2, 18, RED, 1.0)


def _flange_length(p, kind, blue, grey):
    """A bend from the side: the base (grey), the flange (blue), the length measured from the named point."""
    light = QtGui.QColor(grey).lighter(170)
    _rect(p, 2, 21, 12, 4, light)
    path = QtGui.QPainterPath(_pt(14, 21))
    path.arcTo(QtCore.QRectF(8, 13, 12, 12), 270, 90)                   # outer arc 14,25 -> 20,19
    path.lineTo(_pt(20, 8))
    path.lineTo(_pt(16, 8))
    path.lineTo(_pt(16, 19))
    path.arcTo(QtCore.QRectF(12, 17, 4, 4), 0, -90)
    path.closeSubpath()
    p.setPen(QtGui.QPen(blue.darker(140), 1.0))
    p.setBrush(QtGui.QColor(blue).lighter(150))
    p.drawPath(path)
    if kind == "Outer Virtual Sharp":
        _line(p, 14, 25, 20, 25, grey, 0.8, dash=True)
        _line(p, 20, 25, 20, 19, grey, 0.8, dash=True)
        _dim(p, 24, 25, 24, 8)
    elif kind == "Inner Virtual Sharp":
        _line(p, 14, 21, 16, 21, grey, 0.8, dash=True)
        _dim(p, 24, 21, 24, 8)
    else:                                                               # Tangent Bend
        _line(p, 16, 19, 26, 19, grey, 0.8, dash=True)
        _dim(p, 24, 19, 24, 8)


def _flange_position(p, kind, blue, grey):
    """The flange at the base's edge (dashed): inside it, outside it, or the bend outside it."""
    light = QtGui.QColor(grey).lighter(170)
    flange = QtGui.QColor(blue).lighter(150)
    edge = 16
    _rect(p, 2, 20, edge - 2, 4, light)
    if kind == "Material Inside":
        x = edge - 4
    elif kind == "Material Outside":
        x = edge
    elif kind == "Bend Outside":
        x = edge + 4
    elif kind == "Bend from Virtual Sharp":
        x = edge + 2
    else:                                                               # Tangent to Bend
        x = edge + 1
    if x > edge:
        _rect(p, edge, 20, x - edge, 4, flange)                         # the part of the sheet past the edge
    _rect(p, x, 4, 4, 20, flange)
    _line(p, edge, 2, edge, 27, PINK, 1.0, dash=True)
    if kind == "Bend from Virtual Sharp":
        _line(p, edge, 24, x + 4, 24, RED, 1.0)
    elif kind == "Tangent to Bend":
        p.setPen(QtGui.QPen(RED, 1.0))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawArc(QtCore.QRectF(edge - 6, 18, 12, 12), 0, 90 * 16)


def _pick(p, kind, blue, grey):
    """A pick box's own small picture: what the box takes (an edge, a point, a face)."""
    light = QtGui.QColor(grey).lighter(170)
    if kind in ("Edge",):
        _poly(p, [(4, 18), (16, 18), (24, 10), (12, 10)], light)
        _line(p, 4, 18, 16, 18, blue, 2.6)
    elif kind in ("Start", "End"):
        _line(p, 4, 18, 24, 18, grey, 1.4)
        x = 5 if kind == "Start" else 23
        p.setPen(QtGui.QPen(blue.darker(140), 1.0))
        p.setBrush(blue)
        p.drawEllipse(_pt(x, 18), 3.2, 3.2)
    else:                                                               # a face (slot face / tab face)
        _poly(p, [(4, 20), (17, 20), (24, 9), (11, 9)], QtGui.QColor(blue).lighter(150))
        if kind == "TabFace":
            _rect(p, 11, 5, 5, 6, light)


GROUPS = {"pick": _pick, 
    "corner": _corner, "cap": _cap, "gusset": _gusset, "flange_length": _flange_length,
    "flange_position": _flange_position,
}


def pixmap(group, kind, size=SIZE):
    try:
        from . import hidpi
        pix = hidpi.canvas(size, size)
    except Exception:
        pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    try:
        if size != SIZE:
            p.scale(size / float(SIZE), size / float(SIZE))
        blue, grey = _colours()
        GROUPS[group](p, kind, QtGui.QColor(blue), QtGui.QColor(grey))
    finally:
        p.end()
    return pix


def icon(group, kind, size=SIZE):
    return QtGui.QIcon(pixmap(group, kind, size))


def picture(button, group, kind, size=SIZE):
    ""
    button.setText(kind)
    button.setToolTip(kind)
    button.setIcon(icon(group, kind, size))
    button.setIconSize(QtCore.QSize(size, size))
    button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
    return button


def button(name, group, kind, checked=False, size=SIZE):
    b = QtWidgets.QToolButton()
    b.setObjectName(name)
    b.setCheckable(True)
    b.setAutoRaise(True)
    picture(b, group, kind, size)
    b.setChecked(checked)
    return b
