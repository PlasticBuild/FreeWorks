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

import json
import math
import os
import shutil
import struct
import zipfile

import FreeCAD as App

INDEX = "FreeWorks/tessellation.json"
DATA = "FreeWorks/tessellation.bin"
ROW = ("Image Quality", "Save tessellation with part document")
ISO_YAW, ISO_PITCH = math.radians(-45), math.radians(35.2644)     # the isometric view, from front-right above
MAX_TRIANGLES = 60000            # a preview needs no more; bigger meshes are thinned evenly
LIGHT = (-0.3714, -0.7428, 0.5571)      # from the viewer, a little left and above


def enabled(doc):
    try:
        from . import optionspages
        return bool(optionspages.doc_value(doc, ROW[0], ROW[1], False))
    except Exception:
        return False


def _is_assembly(doc):
    try:
        from . import asmcore
        return asmcore.assembly_of(doc) is not None
    except Exception:
        return False


def _shown(obj):
    try:
        vo = obj.ViewObject
        if vo is not None:
            return bool(vo.Visibility)
    except Exception as _fw_err:
        _fw_log("tessave.py:65", _fw_err)
    return bool(getattr(obj, "Visibility", True))


def _color(obj):
    try:
        vo = obj.ViewObject
        app = getattr(vo, "ShapeAppearance", None)
        if app:
            c = app[0].DiffuseColor
            return [round(float(c[0]), 4), round(float(c[1]), 4), round(float(c[2]), 4)]
        c = vo.ShapeColor
        return [round(float(c[0]), 4), round(float(c[1]), 4), round(float(c[2]), 4)]
    except Exception:
        return [0.8, 0.8, 0.8]


def _deviation(doc):
    try:
        from . import optionspages
        return max(0.01, float(optionspages._deviation_read()))
    except Exception:
        return 0.5


def shown_shapes(doc):
    """[(object, global shape)] of the part's shown solids and surfaces (a Body draws through its features)."""
    import Part
    out = []
    for o in doc.Objects:
        if o.TypeId in ("PartDesign::Body", "App::Part", "App::Origin") or not hasattr(o, "Shape"):
            continue
        if not _shown(o):
            continue
        try:
            body = o.getParentGeoFeatureGroup()
            if body is not None and not _shown(body):
                continue
            shape = Part.getShape(o, "", needSubElement=False, transform=False).copy()
            shape.Placement = o.getGlobalPlacement()           # a Body's features sit in the Body's place
        except Exception:
            continue
        if shape is None or shape.isNull() or not shape.Faces:
            continue
        out.append((o, shape))
    return out


def meshes(doc):
    """[{name, label, color, points, triangles}] for doc's shown shapes, at the document's deviation."""
    dev = _deviation(doc)
    out = []
    for o, shape in shown_shapes(doc):
        try:
            tol = max(shape.BoundBox.DiagonalLength * dev / 100.0, 0.01)
            pts, tris = shape.tessellate(tol)
        except Exception:
            continue
        if not tris:
            continue
        out.append({"name": o.Name, "label": o.Label, "color": _color(o),
                    "points": [(p.x, p.y, p.z) for p in pts], "triangles": [tuple(t) for t in tris]})
    return out


def _pack(items):
    index, blob = [], bytearray()
    for m in items:
        pts, tris = m["points"], m["triangles"]
        entry = {"name": m["name"], "label": m["label"], "color": m["color"], "offset": len(blob),
                 "points": len(pts), "triangles": len(tris)}
        blob += struct.pack("<%df" % (3 * len(pts)), *[c for p in pts for c in p])
        blob += struct.pack("<%dI" % (3 * len(tris)), *[i for t in tris for i in t])
        index.append(entry)
    return {"version": 1, "objects": index}, bytes(blob)


def write(doc, path=None):
    """Adds the saved tessellation to doc's file. True when it was written."""
    path = path or doc.FileName
    if not path or not os.path.isfile(path):
        return False
    items = meshes(doc)
    if not items:
        return False
    index, blob = _pack(items)
    tmp = path + ".fwtess"
    try:
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                if info.filename in (INDEX, DATA):
                    continue
                dst.writestr(info, src.read(info.filename))
            dst.writestr(INDEX, json.dumps(index))
            dst.writestr(DATA, blob)
        with zipfile.ZipFile(tmp) as check:
            if check.testzip() is not None or "Document.xml" not in check.namelist():
                raise RuntimeError("the copy did not read back")
        shutil.copystat(path, tmp)
        os.replace(tmp, path)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: save tessellation: %s\n" % error)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception as _fw_err:
            _fw_log("tessave.py:172", _fw_err)
        return False


def after_save(doc, path):
    """slotFinishSaveDocument: the row on, a part (not an assembly or drawing), a .FCStd."""
    path = path or doc.FileName
    if not path or not path.lower().endswith(".fcstd") or not enabled(doc) or _is_assembly(doc):
        return False
    return write(doc, path)


def has(path):
    try:
        with zipfile.ZipFile(path) as z:
            return INDEX in z.namelist()
    except Exception:
        return False


def read(path):
    """The saved meshes of a file, without opening it: [{name, label, color, points, triangles}], or []."""
    try:
        with zipfile.ZipFile(path) as z:
            if INDEX not in z.namelist():
                return []
            index = json.loads(z.read(INDEX).decode("utf-8"))
            blob = z.read(DATA)
    except Exception:
        return []
    out = []
    for e in index.get("objects", []):
        try:
            o, n, t = e["offset"], e["points"], e["triangles"]
            flat = struct.unpack_from("<%df" % (3 * n), blob, o)
            idx = struct.unpack_from("<%dI" % (3 * t), blob, o + 12 * n)
            out.append({"name": e["name"], "label": e.get("label", e["name"]), "color": e.get("color", [0.8] * 3),
                        "points": [flat[i:i + 3] for i in range(0, len(flat), 3)],
                        "triangles": [idx[i:i + 3] for i in range(0, len(idx), 3)]})
        except Exception:
            continue
    return out


def as_mesh(path):
    """The saved tessellation as one Mesh.Mesh (or None)."""
    items = read(path)
    if not items:
        return None
    import Mesh
    facets = []
    for m in items:
        p = m["points"]
        facets += [(p[a], p[b], p[c]) for a, b, c in m["triangles"]]
    return Mesh.Mesh(facets)


# ---------------------------------------------------------------- drawing it
def _rot(yaw, pitch):
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)

    def f(p):
        x, y, z = p
        x, y = cy * x - sy * y, sy * x + cy * y          # turn about Z
        y, z = cp * y - sp * z, sp * y + cp * z          # tilt towards the viewer
        return x, y, z
    return f


def render(source, width=240, height=180, yaw=ISO_YAW, pitch=ISO_PITCH, background=None):
    """A QImage of a file's saved tessellation (source: a path or read()'s list), lit from the viewer, at the
    isometric view by default. None when there is none."""
    from PySide import QtCore, QtGui
    items = read(source) if isinstance(source, str) else source
    if not items:
        return None
    rot = _rot(yaw, pitch)
    tris = []
    total = sum(len(m["triangles"]) for m in items)
    step = max(1, int(math.ceil(total / float(MAX_TRIANGLES))))
    for m in items:
        pts = [rot(p) for p in m["points"]]
        col = m["color"]
        for k, (a, b, c) in enumerate(m["triangles"]):
            if k % step:
                continue
            tris.append((pts[a], pts[b], pts[c], col))
    xs = [p[0] for t in tris for p in t[:3]]
    zs = [p[2] for t in tris for p in t[:3]]
    if not xs:
        return None
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    scale = 0.9 * min(width / max(x1 - x0, 1e-9), height / max(z1 - z0, 1e-9))
    cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
    img = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)
    img.fill(background if background is not None else QtGui.QColor(0, 0, 0, 0))
    painter = QtGui.QPainter(img)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    tris.sort(key=lambda t: -(t[0][1] + t[1][1] + t[2][1]))     # far (large y) first
    for a, b, c, col in tris:
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        light = 0.3 + 0.7 * abs(nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]) / nl
        color = QtGui.QColor.fromRgbF(min(1.0, col[0] * light), min(1.0, col[1] * light), min(1.0, col[2] * light))
        poly = QtGui.QPolygonF([QtCore.QPointF(width / 2 + (p[0] - cx) * scale, height / 2 - (p[2] - cz) * scale)
                                for p in (a, b, c)])
        painter.setPen(QtGui.QPen(color, 0.6))
        painter.setBrush(color)
        painter.drawPolygon(poly)
    painter.end()
    return img


try:
    from PySide import QtCore as _QtCore, QtGui as _QtGui, QtWidgets as _QtWidgets

    class PreviewWidget(_QtWidgets.QLabel):
        """A file's saved model: drag to turn it, double-click for the isometric view again."""

        def __init__(self, path="", parent=None, size=(240, 180)):
            super().__init__(parent)
            self.setObjectName("FW_TessellationPreview")
            self.setAlignment(_QtCore.Qt.AlignCenter)
            self.setMinimumSize(*size)
            self.size_wh = size
            self.items = []
            self.yaw, self.pitch = ISO_YAW, ISO_PITCH
            self._drag = None
            self.set_path(path)

        def set_path(self, path):
            self.items = read(path) if path else []
            self.yaw, self.pitch = ISO_YAW, ISO_PITCH
            self.redraw()
            return bool(self.items)

        def redraw(self):
            img = render(self.items, self.size_wh[0], self.size_wh[1], self.yaw, self.pitch) if self.items else None
            if img is None:
                self.setPixmap(_QtGui.QPixmap())
                self.setText("No saved tessellation")
            else:
                self.setText("")
                self.setPixmap(_QtGui.QPixmap.fromImage(img))

        def mousePressEvent(self, event):
            self._drag = event.pos()

        def mouseMoveEvent(self, event):
            if self._drag is None or not self.items:
                return
            d = event.pos() - self._drag
            self._drag = event.pos()
            self.yaw += d.x() * 0.01
            self.pitch += d.y() * 0.01
            self.redraw()

        def mouseReleaseEvent(self, event):
            self._drag = None

        def mouseDoubleClickEvent(self, event):
            self.yaw, self.pitch = ISO_YAW, ISO_PITCH
            self.redraw()
except Exception:      # pragma: no cover - no GUI
    PreviewWidget = None
