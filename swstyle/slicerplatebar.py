"""The icon column beside each build plate, as the slicers draw it in the 3D view: delete the plate, auto orient
and arrange the plate's objects, lock the plate (arrange and orient leave a locked plate alone) and name the plate.
The icons are flat tiles on the bed plane beside the plate's back right corner, so they zoom and turn with the
plates; a click on one runs it. Drawn icons only (resources/slicer/toolbar/plate_*.svg)."""
import os

import FreeCAD as App

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "slicer", "toolbar")

# key, icon, tooltip (the slicers' words)
ICONS = (
    ("delete", "plate_delete", "Remove plate"),
    ("orient", "toolbar_orient", "Auto orient objects on current plate"),
    ("arrange", "toolbar_arrange", "Arrange objects on current plate"),
    ("lock", "plate_unlock", "Lock current plate"),
    ("name", "plate_name", "Edit plate name"),
)
TILE = (0.97, 0.97, 0.97)
_IMAGES = {}


def tile_size(bed):
    x0, y0, x1, y1 = bed.bed_box()
    return max(10.0, min(26.0, 0.075 * max(x1 - x0, y1 - y0)))


def icons(bed, i):
    """[(key, icon, tip)] shown beside plate i: Remove plate only while there is more than one plate; the lock
    shows its state."""
    out = []
    for key, icon, tip in ICONS:
        if key == "delete" and len(bed.plates) <= 1:
            continue
        if key in ("orient", "arrange") and i in bed.locked:
            continue            # a locked plate is left as it is (the slicers grey these; here they go)
        if key == "lock" and i in bed.locked:
            icon, tip = "plate_lock", "Unlock current plate"
        out.append((key, icon, tip))
    return out


def rects(bed, i):
    """[(key, (x0, y0, x1, y1))] of plate i's icons, in plate coordinates (a column right of the plate, from the
    back down)."""
    x0, y0, x1, y1 = bed.bed_box()
    s = tile_size(bed)
    gap = s * 0.18
    left = x1 + s * 0.35
    out = []
    for k, (key, _icon, _tip) in enumerate(icons(bed, i)):
        top = y1 - k * (s + gap)
        out.append((key, (left, top - s, left + s, top)))
    return out


def hit(bed, point):
    """(plate, key) of the icon under a world point on the bed plane, or None."""
    if point is None:
        return None
    for i in range(len(bed.plates)):
        o = bed.plate_origin(i)
        for key, (a, b, c, d) in rects(bed, i):
            if a + o.x <= point.x <= c + o.x and b + o.y <= point.y <= d + o.y:
                return i, key
    return None


def image(name, px=64):
    """The icon drawn on its tile, as (size, bytes) for an SoTexture2 (RGBA, bottom row first)."""
    if name in _IMAGES:
        return _IMAGES[name]
    from PySide import QtCore, QtGui
    img = QtGui.QImage(px, px, QtGui.QImage.Format_RGBA8888)
    img.fill(QtGui.QColor(int(TILE[0] * 255), int(TILE[1] * 255), int(TILE[2] * 255), 235))
    p = QtGui.QPainter(img)
    try:
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtGui.QPen(QtGui.QColor("#9aa4a8"), 2))
        p.drawRect(1, 1, px - 2, px - 2)
        path = os.path.join(HERE, name + ".svg")
        try:
            from PySide6.QtSvg import QSvgRenderer
        except Exception:
            QSvgRenderer = None
        if QSvgRenderer is not None and os.path.isfile(path):
            QSvgRenderer(path).render(p, QtCore.QRectF(px * 0.08, px * 0.08, px * 0.84, px * 0.84))
    finally:
        p.end()
    img = img.mirrored(False, True)
    data = bytes(img.constBits())[:px * px * 4]
    _IMAGES[name] = (px, data)
    return _IMAGES[name]


def node(bed, i):
    """The icon column of plate i (plate coordinates; the plate's node moves it onto its plate)."""
    from pivy import coin
    sep = coin.SoSeparator()
    sep.setName("SWStyle_SlicerPlateIcons")
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    sep.addChild(light)
    mat = coin.SoMaterial()
    mat.diffuseColor = (1, 1, 1)
    sep.addChild(mat)
    lookup = dict((k, ic) for k, ic, _t in icons(bed, i))
    for key, (a, b, c, d) in rects(bed, i):
        t = coin.SoSeparator()
        t.setName("SWStyle_SlicerPlateIcon_" + key)
        tex = coin.SoTexture2()
        try:
            px, data = image(lookup[key])
            tex.image.setValue(coin.SbVec2s(px, px), 4, data)
        except Exception as error:
            App.Console.PrintLog("slicer plate: icon %s not drawn (%s)\n" % (key, error))
        tex.model = coin.SoTexture2.REPLACE
        t.addChild(tex)
        tc = coin.SoTextureCoordinate2()
        tc.point.setValues(0, 4, [(0, 0), (1, 0), (1, 1), (0, 1)])
        t.addChild(tc)
        co = coin.SoCoordinate3()
        co.point.setValues(0, 4, [(a, b, 0.02), (c, b, 0.02), (c, d, 0.02), (a, d, 0.02)])
        t.addChild(co)
        f = coin.SoFaceSet()
        f.numVertices.setValue(4)
        t.addChild(f)
        sep.addChild(t)
    return sep


def run(bed, i, key):
    """What a plate icon does. The panel takes Remove plate and Edit plate name (they ask first); the plate does the
    rest itself."""
    if bed.on_plate_icon is not None and bed.on_plate_icon(i, key):
        return True
    if key == "lock":
        bed.locked ^= {i}
        bed._redraw()
        bed._changed()
        return True
    if key == "arrange":
        bed.arrange_plate(i)
        return True
    if key == "orient":
        bed.orient_plate(i)
        return True
    if key == "delete":
        return bed.delete_plate(i)
    return False
