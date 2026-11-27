"""Variable layer height, as the slicers' plate toolbar tool: Adaptive (thin layers where the surface slopes, thick
where the walls are straight), Smooth, Reset, and a curve of layer height over the object's height to drag by hand.
The profile goes to the slicer in the plate's 3MF (Metadata/layer_heights_profile.txt), as the slicers keep it."""
import math

import FreeCAD as App
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt


def _num(value, default):
    try:
        if isinstance(value, (list, tuple)):
            value = value[0]
        return float(str(value).rstrip("%"))
    except Exception:
        return default


def limits(panel):
    """(first layer, min layer, max layer, layer height) of the panel's printer and process."""
    from . import slicerobject
    process = slicerobject.effective_process(panel)
    try:
        machine = dict(panel.slicer.resolve("machine", panel.choice["printer"]))
    except Exception:
        machine = {}
    machine.update(panel.choice.get("printer_overrides") or {})
    layer = _num(process.get("layer_height"), 0.2)
    first = _num(process.get("initial_layer_print_height"), layer)
    lo = _num(machine.get("min_layer_height"), 0.07)
    hi = _num(machine.get("max_layer_height"), 0.28)
    nozzle = _num(machine.get("nozzle_diameter"), 0.4)
    hi = min(hi, 0.75 * nozzle) if hi > 0 else 0.75 * nozzle
    lo = max(0.02, min(lo, hi))
    return first, lo, hi, layer


def placed_mesh(bed, item):
    m = item.mesh.copy()
    m.transform(bed.item_matrix(item))
    return m


def signature(item):
    """The placement the profile was made for (a turn or a scale makes it stale, as in the slicers)."""
    r = item.rotation.Q
    return tuple(round(v, 6) for v in tuple(r) + (item.scale.x, item.scale.y, item.scale.z))


def profile_of(item):
    """The item's profile if it still fits its placement, else None."""
    p = getattr(item, "layer_profile", None)
    if not p or getattr(item, "layer_profile_sig", None) != signature(item):
        return None
    return p


def flat(height, first, layer):
    """The process's own layers as a profile (first layer, then the layer height to the top)."""
    prof = [0.0, first]
    z = first
    while z < height - 1e-6:
        prof += [z, layer]
        z += layer
    prof += [height, layer]
    return prof


def adaptive(mesh, first, lo, hi, quality=0.5):
    """Layer heights from the surface slope (the slicers' Adaptive): the cusp a layer leaves on a sloped surface stays
    under a limit set by quality (1 = finest). Returns the profile [z0, h0, z1, h1, ...] starting with the first layer."""
    height = mesh.BoundBox.ZMax - mesh.BoundBox.ZMin
    z0 = mesh.BoundBox.ZMin
    cusp = lo + (hi - lo) * 0.5 * (1.0 - max(0.0, min(1.0, quality)))
    facets = []
    for f in mesh.Facets:
        n = f.Normal
        nz = abs(n.z)
        if nz > 0.999 or nz < 1e-4:
            continue                 # flat tops and bottoms, straight walls: no cusp limit
        zs = [p[2] - z0 for p in f.Points]
        # the cusp of a layer of height h on a surface with normal n: h * |n.z| (n unit)
        facets.append((min(zs), max(zs), cusp / nz))
    facets.sort()
    prof = [0.0, first]
    z = first
    while z < height - 1e-6:
        h = hi
        for fmin, fmax, limit in facets:
            if fmin > z + hi:
                break
            if fmax >= z and limit < h:
                h = limit
        h = max(lo, min(hi, h))
        if z + h > height:
            h = max(lo, height - z)
        prof += [z, h]
        z += h
    prof += [height, prof[-1]]
    return prof


def smooth(prof, radius=1.0, lo=0.0, hi=10.0):
    """Even out the profile (the slicers' Smooth): each height becomes the mean of those within radius mm."""
    pts = [(prof[i], prof[i + 1]) for i in range(0, len(prof), 2)]
    if len(pts) < 4:
        return list(prof)
    out = [pts[0][0], pts[0][1]]
    for i, (z, h) in enumerate(pts[1:], 1):
        near = [hh for zz, hh in pts[1:] if abs(zz - z) <= radius]
        out += [z, max(lo, min(hi, sum(near) / len(near)))]
    return out


def layer_count(prof):
    return max(0, len(prof) // 2 - 1)


def at(prof, z):
    """The layer height at z (the step of the profile under z)."""
    h = prof[1] if len(prof) > 1 else 0.2
    for i in range(0, len(prof), 2):
        if prof[i] <= z + 1e-9:
            h = prof[i + 1]
        else:
            break
    return h


def resample(prof, height, first, lo, hi, step=0.05):
    """A profile as a curve sampled every step mm (what the curve editor edits)."""
    zs = [i * step for i in range(int(height / step) + 1)]
    return [(z, max(lo, min(hi, at(prof, z)))) for z in zs]


def from_curve(curve, height, first, lo, hi):
    """Layers walked up a curve [(z, h)]: each layer takes the curve's height where it starts."""
    def h_at(z):
        best = curve[0][1]
        for zz, hh in curve:
            if zz <= z + 1e-9:
                best = hh
            else:
                break
        return best
    prof = [0.0, first]
    z = first
    while z < height - 1e-6:
        h = max(lo, min(hi, h_at(z)))
        prof += [z, h]
        z += h
    prof += [height, prof[-1]]
    return prof


class Curve(QtWidgets.QWidget):
    """The profile as a curve, height up, layer height across (the slicers' band beside the object). Drag to set the
    layer height there (it blends out over radius mm)."""
    edited = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWStyle_SlicerLayerCurve")
        self.setMinimumSize(220, 200)
        self.curve, self.span, self.lo, self.hi, self.radius = [], 1.0, 0.05, 0.3, 1.0
        self.setToolTip("Drag left for thinner layers, right for thicker ones, at that height")

    def set_curve(self, curve, height, lo, hi):
        self.curve, self.span, self.lo, self.hi = list(curve), max(height, 1e-3), lo, hi
        self.update()

    def _xy(self, z, h):
        r = self.rect().adjusted(34, 8, -8, -20)
        x = r.left() + (h - self.lo) / max(1e-9, self.hi - self.lo) * r.width()
        y = r.bottom() - z / self.span * r.height()
        return x, y, r

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        pal = self.palette()
        p.fillRect(self.rect(), pal.color(QtGui.QPalette.Base))
        _x, _y, r = self._xy(0, self.lo)
        p.setPen(QtGui.QPen(pal.color(QtGui.QPalette.Mid), 1))
        p.drawRect(r)
        p.setPen(pal.color(QtGui.QPalette.Text))
        p.drawText(2, r.bottom(), "0")
        p.drawText(2, r.top() + 10, "%.0f" % self.span)
        p.drawText(r.left(), self.rect().height() - 4, "%.2f" % self.lo)
        p.drawText(r.right() - 28, self.rect().height() - 4, "%.2f" % self.hi)
        if self.curve:
            path = QtGui.QPainterPath()
            for i, (z, h) in enumerate(self.curve):
                x, y, _r = self._xy(z, h)
                (path.lineTo if i else path.moveTo)(x, y)
            p.setPen(QtGui.QPen(pal.color(QtGui.QPalette.Highlight), 2))
            p.drawPath(path)
        p.end()

    def _edit(self, pos):
        x, y = (pos.x(), pos.y())
        _x, _y, r = self._xy(0, self.lo)
        h = self.lo + (x - r.left()) / max(1, r.width()) * (self.hi - self.lo)
        z = (r.bottom() - y) / max(1, r.height()) * self.span
        h = max(self.lo, min(self.hi, h))
        out = []
        for zz, hh in self.curve:
            d = abs(zz - z)
            if d < self.radius:
                w = 1.0 - d / self.radius
                hh = hh * (1 - w) + h * w
            out.append((zz, hh))
        self.curve = out
        self.update()
        self.edited.emit()

    def mousePressEvent(self, e):
        self._edit(e.position() if hasattr(e, "position") else e.pos())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._edit(e.position() if hasattr(e, "position") else e.pos())


def profile_text(objects_profiles):
    """Metadata/layer_heights_profile.txt: one line per object (1-based), "object_id=N|z;h;z;h...". """
    lines = []
    for i, prof in enumerate(objects_profiles, 1):
        if prof and len(prof) >= 6 and len(prof) % 2 == 0:
            lines.append("object_id=%d|%s" % (i, ";".join("%.6g" % v for v in prof)))
    return "\n".join(lines) + ("\n" if lines else "")


# ------------------------------------------------------------------ the colour band on the object
BAND_STOPS = ((0.0, (0.15, 0.35, 0.95)), (0.33, (0.15, 0.80, 0.85)), (0.66, (0.95, 0.85, 0.20)), (1.0, (0.90, 0.20, 0.15)))


def band_colour(h, lo, hi):
    """The band's colour for a layer height: blue (thin) through cyan and yellow to red (thick), as the slicers'."""
    t = 0.0 if hi <= lo else min(1.0, max(0.0, (h - lo) / (hi - lo)))
    for (t0, c0), (t1, c1) in zip(BAND_STOPS, BAND_STOPS[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return tuple(a + (b - a) * f for a, b in zip(c0, c1))
    return BAND_STOPS[-1][1]


def band_image(prof, height, lo, hi, path, size=512):
    """A picture of the band up the object's height (one row per step), for the 3D view's texture."""
    from PySide import QtGui
    img = QtGui.QImage(2, size, QtGui.QImage.Format_RGB32)
    for row in range(size):
        z = (row + 0.5) / size * height
        r, g, b = band_colour(at(prof, z), lo, hi)
        c = QtGui.QColor.fromRgbF(r, g, b).rgb()
        img.setPixel(0, size - 1 - row, c)
        img.setPixel(1, size - 1 - row, c)
    img.save(path)
    return path


def load_texture(tex, path):
    """slicertex-1127: the picture into the SoTexture2 node, read with Qt. Coin's own reader (tex.filename) needs
    simage, which FreeCAD 1.1.4 on Windows does not ship: the band drew blank (same as vdp200 / appeartex).
    True when the node got the picture."""
    from PySide import QtGui
    from pivy import coin
    image = QtGui.QImage(path) if path else QtGui.QImage()
    if image.isNull():
        tex.image.setValue(coin.SbVec2s(0, 0), 0, b"")
        return False
    image = image.convertToFormat(QtGui.QImage.Format_RGB888).mirrored(False, True)     # Coin: bottom row first
    w, h = image.width(), image.height()
    stride = image.bytesPerLine()
    raw = bytes(image.constBits())[:stride * h]
    data = b"".join(raw[y * stride:y * stride + 3 * w] for y in range(h))
    tex.image.setValue(coin.SbVec2s(w, h), 3, data)
    return True


def show_band(bed, item, prof, lo, hi, old=None):
    """The object coloured by its layer height (the Variable layer height tool's band), over the plate's object.
    Returns the node (old one taken away)."""
    import os
    import tempfile
    from pivy import coin
    root = bed.root
    if old is not None and root is not None:
        try:
            root.removeChild(old)
        except Exception:
            pass
    if root is None:
        return None
    mesh = placed_mesh(bed, item)
    height = max(1e-6, mesh.BoundBox.ZLength)
    path = os.path.join(tempfile.gettempdir(), "swstyle-layer-band-%d.png" % os.getpid())
    band_image(prof, height, lo, hi, path)
    o = bed.plate_origin(item.plate)
    sep = coin.SoSeparator()
    sep.setName("SWStyle_SlicerLayerBand")
    move = coin.SoTranslation()
    move.translation.setValue(o.x, o.y, o.z)
    sep.addChild(move)
    offset = coin.SoPolygonOffset()
    offset.factor = -1.0
    offset.units = -1.0
    sep.addChild(offset)
    mat = coin.SoMaterial()
    mat.diffuseColor.setValue(1.0, 1.0, 1.0)
    sep.addChild(mat)
    tex = coin.SoTexture2()
    load_texture(tex, path)      # slicertex-1127: pixels through Qt (tex.filename drew blank on the PC: no simage)
    tex.model = coin.SoTexture2.MODULATE
    tex.wrapS = coin.SoTexture2.CLAMP
    tex.wrapT = coin.SoTexture2.CLAMP
    sep.addChild(tex)
    plane = coin.SoTextureCoordinatePlane()
    plane.directionS.setValue(0, 0, 0)
    plane.directionT.setValue(0, 0, 1.0 / height)   # up the object: the picture's rows
    sep.addChild(plane)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
    hints.creaseAngle = 0.5
    sep.addChild(hints)
    pts, tris = mesh.Topology
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
    sep.addChild(coords)
    faces = coin.SoIndexedFaceSet()
    idx = []
    for a, b, c in tris:
        idx += [a, b, c, -1]
    faces.coordIndex.setValues(0, len(idx), idx)
    sep.addChild(faces)
    root.addChild(sep)
    return sep
