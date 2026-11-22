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

import hashlib
import json
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import pickguard

V = App.Vector
TITLE = "Decals"
MAPPINGS = ("Label", "Projection", "Spherical", "Cylindrical")
PROJECTIONS = ("Normal to face", "XY", "ZX", "YZ")
MASKS = ("No mask", "Image mask file", "Selective color mask", "Use decal image alpha channel")
PROPS = (
    ("DecalFace", "App::PropertyString", "The face the decal is on"),
    ("DecalImage", "App::PropertyString", "The original picture"),
    ("DecalMask", "App::PropertyString", "Mask kind"),
    ("DecalMaskFile", "App::PropertyString", "Mask picture"),
    ("DecalMaskColors", "App::PropertyString", "Colours left out (#rrggbb, comma separated)"),
    ("DecalMapping", "App::PropertyString", "Mapping type"),
    ("DecalProjection", "App::PropertyString", "Projection direction"),
    ("DecalX", "App::PropertyFloat", "Horizontal location from the face centre (mm)"),
    ("DecalY", "App::PropertyFloat", "Vertical location from the face centre (mm)"),
    ("DecalRotation", "App::PropertyFloat", "Rotation (degrees)"),
    ("DecalFixedAspect", "App::PropertyBool", "Fixed aspect ratio"),
    ("DecalMirrorH", "App::PropertyBool", "Mirror horizontally"),
    ("DecalMirrorV", "App::PropertyBool", "Mirror vertically"),
    ("DecalOwnLight", "App::PropertyBool", "Use the decal's own illumination"),
    ("DecalFaceSig", "App::PropertyString", "Where the face was, to find it again when the part changes"),
)


# --------------------------------------------------------------------------- storage
def ensure(plane):
    for name, kind, tip in PROPS:
        if name not in plane.PropertiesList:
            plane.addProperty(kind, name, "Decal", tip)
    if not plane.DecalImage:
        plane.DecalImage = plane.ImageFile
    if not plane.DecalMask:
        plane.DecalMask = MASKS[3]
    if not plane.DecalMapping:
        plane.DecalMapping = MAPPINGS[0]
    if not plane.DecalProjection:
        plane.DecalProjection = PROJECTIONS[0]
    return plane


def state(plane):
    out = {n: getattr(plane, n) for n, _k, _t in PROPS if n in plane.PropertiesList}
    out.update(XSize=plane.XSize.Value, YSize=plane.YSize.Value, Placement=plane.Placement,
               Transparency=_transparency(plane))
    return out


def restore(plane, saved):
    """Cancel on an edit: the settings as they were, the picture made again, then the size."""
    for k, v in saved.items():
        if k == "Transparency":
            _set_transparency(plane, v)
        elif k in ("ImageFile", "XSize", "YSize"):
            continue
        elif k in plane.PropertiesList:
            setattr(plane, k, v)
    refresh(plane)
    plane.XSize, plane.YSize = saved["XSize"], saved["YSize"]
    plane.Placement = saved["Placement"]


def _transparency(plane):
    try:
        return int(plane.ViewObject.Transparency)
    except Exception:
        return 0


def _set_transparency(plane, value):
    try:
        plane.ViewObject.Transparency = int(value)
    except Exception as _fw_err:
        _fw_log("decalpm.py:120", _fw_err)


def _cache():
    folder = os.path.join(App.getUserCachePath(), "FreeWorks", "Decals")
    os.makedirs(folder, exist_ok=True)
    return folder


def user_folder():
    folder = os.path.join(App.getUserAppDataDir(), "FreeWorks", "Decals")
    os.makedirs(folder, exist_ok=True)
    return folder


# --------------------------------------------------------------------------- the picture
def _colours(text):
    out = []
    for part in (text or "").split(","):
        c = QtGui.QColor(part.strip())
        if c.isValid():
            out.append(c)
    return out


def processed_image(src, mask="Use decal image alpha channel", mask_file="", mask_colours="",
                    mirror_h=False, mirror_v=False, tolerance=40):
    """The picture the decal shows: the original mirrored and masked, as a PNG in the cache."""
    image = QtGui.QImage(src)
    if image.isNull():
        return src
    image = image.convertToFormat(QtGui.QImage.Format_ARGB32)
    if mirror_h or mirror_v:
        try:
            image = image.flipped((QtCore.Qt.Horizontal if mirror_h else QtCore.Qt.Orientation(0)) |
                                  (QtCore.Qt.Vertical if mirror_v else QtCore.Qt.Orientation(0)))
        except Exception:
            image = image.mirrored(bool(mirror_h), bool(mirror_v))
    if mask == "No mask":
        image = image.convertToFormat(QtGui.QImage.Format_RGB32).convertToFormat(QtGui.QImage.Format_ARGB32)
    elif mask == "Image mask file" and mask_file and os.path.exists(mask_file):
        m = QtGui.QImage(mask_file).scaled(image.size()).convertToFormat(QtGui.QImage.Format_Grayscale8)
        for y in range(image.height()):
            for x in range(image.width()):
                c = image.pixelColor(x, y)
                c.setAlpha(min(c.alpha(), QtGui.QColor(m.pixel(x, y)).red()))
                image.setPixelColor(x, y, c)
    elif mask == "Selective color mask":
        keys = _colours(mask_colours)
        if keys:
            for y in range(image.height()):
                for x in range(image.width()):
                    c = image.pixelColor(x, y)
                    for k in keys:
                        if abs(c.red() - k.red()) + abs(c.green() - k.green()) + abs(c.blue() - k.blue()) <= tolerance:
                            c.setAlpha(0)
                            image.setPixelColor(x, y, c)
                            break
    key = hashlib.md5(("%s|%s|%s|%s|%s|%s|%s" % (src, os.path.getmtime(src) if os.path.exists(src) else 0,
                                                 mask, mask_file, mask_colours, mirror_h, mirror_v)).encode()).hexdigest()
    out = os.path.join(_cache(), "decal-%s.png" % key[:16])
    image.save(out, "PNG")
    return out


# --------------------------------------------------------------------------- where it lies
def face_of(plane):
    obj = getattr(plane, "DecalOf", None)
    sub = getattr(plane, "DecalFace", "") or ""
    if obj is None or not sub.startswith("Face"):
        return None
    try:
        return obj.Shape.getElement(sub)
    except Exception as _fw_err:
        _fw_log("decalpm.py:195", _fw_err)
        return None


def _normal(face):
    u0, u1, v0, v1 = face.ParameterRange
    return face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)


def _direction(plane, face):
    n = _normal(face)
    proj = getattr(plane, "DecalProjection", PROJECTIONS[0])
    if plane.DecalMapping == "Projection" and proj in ("XY", "ZX", "YZ"):
        axis = {"XY": V(0, 0, 1), "ZX": V(0, 1, 0), "YZ": V(1, 0, 0)}[proj]
        return axis if axis.dot(n) >= 0 else axis * -1
    return n


def frame(plane, face):
    """(rotation, centre, u, v): the decal's orientation and in-plane axes on the face."""
    n = _direction(plane, face)
    base = App.Rotation(V(0, 0, 1), n)
    rot = App.Rotation(n, float(plane.DecalRotation or 0.0)).multiply(base)
    u, v = rot.multVec(V(1, 0, 0)), rot.multVec(V(0, 1, 0))
    return rot, face.CenterOfMass, u, v


def place(plane):
    face = face_of(plane)
    if face is None:
        return False
    if curved(face):
        spot = _wrap(plane, face).spot(plane)
        if spot is not None:
            plane.Placement = spot
            return True
    rot, c, u, v = frame(plane, face)
    n = _direction(plane, face)
    plane.Placement = App.Placement(c + u * float(plane.DecalX or 0) + v * float(plane.DecalY or 0) + n * 0.02, rot)
    return True




def _sig_shape(obj):
    """The shape a decal's face is remembered in: a component's (link's) shape without the component's
    own placement, so moving the component does not lose the face (vd112)."""
    shape = obj.Shape
    if getattr(obj, "TypeId", "") == "App::Link":
        shape = shape.copy()
        shape.Placement = obj.Placement.inverse().multiply(shape.Placement)
    return shape


def remember_face(plane):
    """Keeps where the decal's face is, by geometry, to find it after a rebuild renames or moves it."""
    import json
    try:
        from . import picksgeo
        obj, sub = plane.DecalOf, plane.DecalFace
        sig = picksgeo.signature(_sig_shape(obj), sub)
        if sig is None:
            return
        kind, p, n, size = sig
        plane.DecalFaceSig = json.dumps([kind, [p.x, p.y, p.z], [n.x, n.y, n.z], size])
    except Exception as _fw_err:
        _fw_log("decalpm.py:244", _fw_err)


def follow(plane):
    """After a rebuild: the decal's face found again (same name or by geometry) and the decal put on it."""
    import json
    try:
        from . import picksgeo
        obj = getattr(plane, "DecalOf", None)
        text = getattr(plane, "DecalFaceSig", "")
        if obj is None or not text or obj.Shape.isNull():
            return False
        kind, p, n, size = json.loads(text)
        sig = (kind, V(*p), V(*n), size)
        shape = _sig_shape(obj)
        sub = picksgeo.match(shape, sig) or picksgeo.match_near(shape, sig)
        if sub is None:
            return False
        old = App.Placement(plane.Placement)
        if sub != plane.DecalFace:
            plane.DecalFace = sub
        place(plane)
        remember_face(plane)
        if getattr(plane, "DecalShown", ""):
            _show_on_face(plane, plane.DecalShown)      # the face may have new edges or holes
        return not old.isSame(plane.Placement, 1e-9)
    except Exception as error:
        App.Console.PrintLog("FreeCAD decal follow: %s\n" % error)
        return False


def is_decal(obj):
    return "DecalFace" in getattr(obj, "PropertiesList", ()) and getattr(obj, "DecalOf", None) is not None


class _Watch:
    busy = set()

    def slotRecomputedDocument(self, doc):
        if doc.Name in self.busy:
            return
        decals = [o for o in doc.Objects if is_decal(o)]
        if not decals:
            return
        self.busy.add(doc.Name)
        try:
            for o in decals:
                if not getattr(o, "DecalFaceSig", ""):
                    ensure(o)
                    remember_face(o)        # a decal from an older file: remembered as it is now
                else:
                    follow(o)
        finally:
            self.busy.discard(doc.Name)


    def slotFinishRestoreDocument(self, doc):
        # a curved-face decal's drape is drawn, not saved: drape it again once the file is open
        if App.GuiUp and any(is_decal(o) for o in doc.Objects):
            name = doc.Name
            QtCore.QTimer.singleShot(0, lambda: redrape(name))

    def slotCreatedDocument(self, doc):
        # FreeCAD tells Python observers of an opened file this way, before its objects are read
        # (slotFinishRestoreDocument is not passed on to them): drape once the file is open and drawn
        if App.GuiUp:
            name = doc.Name
            QtCore.QTimer.singleShot(0, lambda: redrape(name))

    def slotChangedObject(self, obj, prop):

        if prop != "Visibility" or getattr(obj, "TypeId", "") == "Image::ImagePlane":
            return
        try:
            if getattr(obj.Document, "Restoring", False) or obj.Document.Name in self.busy:
                return
            decals = [o for o in obj.InList if o.TypeId == "Image::ImagePlane" and is_decal(o) and o.DecalOf == obj]
            if not decals:
                return
            shown = bool(obj.Visibility)
            for d in decals:
                if "DecalHiddenWithPart" not in d.PropertiesList:
                    d.addProperty("App::PropertyBool", "DecalHiddenWithPart", "Decal", "Hidden because its part was hidden")
                    d.setEditorMode("DecalHiddenWithPart", 2)
                if not shown and d.Visibility:
                    d.DecalHiddenWithPart = True
                    d.Visibility = False
                elif shown and d.DecalHiddenWithPart:
                    d.DecalHiddenWithPart = False
                    d.Visibility = True
        except Exception as _fw_err:
            _fw_log("decalpm.py:with-part", _fw_err)

    def slotDeletedDocument(self, doc):
        for key in [k for k in _drapes if k[0] == doc.Name]:
            _drapes.pop(key, None)


def redrape(name):
    try:
        doc = App.getDocument(name)
    except Exception:
        return
    for o in doc.Objects:
        if is_decal(o) and getattr(o, "DecalShown", ""):
            face = face_of(o)
            if face is not None and curved(face):
                drape(o, o.DecalShown)


_watch = []


def install():
    if not _watch:
        _watch.append(_Watch())
        App.addDocumentObserver(_watch[0])


def extent(plane, along):
    """The face's width along the decal's horizontal (along='u') or vertical ('v') axis."""
    face = face_of(plane)
    if face is None:
        return None
    if curved(face):
        got = _wrap(plane, face).extent(along)
        if got:
            return got
    _r, c, u, v = frame(plane, face)
    axis = u if along == "u" else v
    vals = [(p.Point - c).dot(axis) for p in face.Vertexes] or [0.0]
    for e in face.Edges:
        vals += [(p - c).dot(axis) for p in e.discretize(12)]
    return max(vals) - min(vals)


def refresh(plane):
    shown = processed_image(plane.DecalImage, plane.DecalMask, plane.DecalMaskFile, plane.DecalMaskColors,
                            plane.DecalMirrorH, plane.DecalMirrorV)
    if "DecalShown" not in plane.PropertiesList:
        plane.addProperty("App::PropertyString", "DecalShown", "Decal", "The picture made for the decal")
        plane.setEditorMode("DecalShown", 2)
    place(plane)
    _show_on_face(plane, shown)
    if not plane.DecalOwnLight:
        _set_transparency(plane, 0)
    plane.Document.recompute()


def _show_clipped(plane, shown):
    """Puts the decal's picture, cut to its face, on the plane (keeping the decal's own size)."""
    picture = _clipped(plane, shown)
    if "DecalPicture" not in plane.PropertiesList:
        plane.addProperty("App::PropertyString", "DecalPicture", "Decal", "The picture on the plane (cut to the face)")
        plane.setEditorMode("DecalPicture", 2)
        plane.DecalPicture = shown if plane.DecalShown == shown else ""
    if plane.DecalShown != shown or plane.DecalPicture != picture:
        # a new picture resizes the plane to it: keep the decal's own size
        w, h = plane.XSize.Value, plane.YSize.Value
        plane.ImageFile = picture
        plane.DecalShown = shown
        plane.DecalPicture = picture
        plane.XSize, plane.YSize = w, h


def _show_on_face(plane, shown):
    """A flat face: the picture cut to the face, on the plane. A curved face: the picture draped over it."""
    face = face_of(plane)
    if face is not None and curved(face):
        if "DecalPicture" not in plane.PropertiesList:
            plane.addProperty("App::PropertyString", "DecalPicture", "Decal", "The picture on the plane (cut to the face)")
            plane.setEditorMode("DecalPicture", 2)
        if plane.ImageFile != shown or plane.DecalShown != shown:
            w, h = plane.XSize.Value, plane.YSize.Value
            plane.ImageFile = shown
            plane.DecalShown = shown
            plane.XSize, plane.YSize = w, h
        plane.DecalPicture = shown
        drape(plane, shown)
        return
    undrape(plane)
    _show_clipped(plane, shown)




def curved(face):
    try:
        return face.Surface.TypeId != "Part::GeomPlane"
    except Exception:
        return False


def _upright(axis):
    """An axis turned to point up (+Z, else +Y, else +X) so a label on a can stands the right way up."""
    for ref in (V(0, 0, 1), V(0, 1, 0), V(1, 0, 0)):
        d = axis.dot(ref)
        if abs(d) > 1e-6:
            return axis * (1 if d > 0 else -1)
    return axis


class _Wrap:
    """How a decal lies on a curved face: decal(point) gives the point's place on the unrolled
    picture (s along the decal's width, t along its height, mm from the decal's centre before its own
    location and rotation), or None where the picture does not reach (the far side of a projection)."""

    def __init__(self, plane, face):
        import math
        self.face = face
        surf = face.Surface
        kind = surf.TypeId
        mapping = getattr(plane, "DecalMapping", "Label") or "Label"
        u0, u1, v0, v1 = face.ParameterRange
        self.mid = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
        self.n0 = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        self.kind = "plane"
        if mapping in ("Label", "Cylindrical") and kind in ("Part::GeomCylinder", "Part::GeomCone"):
            self.kind = "cylinder"
            self.axis = _upright(V(surf.Axis).normalize())
            self.c = V(surf.Center) if kind == "Part::GeomCylinder" else V(surf.Apex)
            r = self.mid - self.c
            self.ref = (r - self.axis * r.dot(self.axis))
            self.radius = self.ref.Length
            self.ref.normalize()
            self.side = self.axis.cross(self.ref)
            self.h0 = r.dot(self.axis)
        elif mapping in ("Label", "Spherical") and kind == "Part::GeomSphere":
            self.kind = "sphere"
            self.c = V(surf.Center)
            self.radius = float(surf.Radius)
            self.axis = _upright(V(surf.Axis).normalize())
            r = (self.mid - self.c).normalize()
            flat = r - self.axis * r.dot(self.axis)
            if flat.Length < 1e-6:      # the middle is at a pole: any side will do
                flat = self.axis.cross(V(1, 0, 0) if abs(self.axis.x) < 0.9 else V(0, 1, 0))
            self.ref = flat.normalize()
            self.side = self.axis.cross(self.ref)
            self.lat0 = math.asin(max(-1.0, min(1.0, r.dot(self.axis))))
        else:
            self.dir = _direction(plane, face) if mapping == "Projection" else self.n0
            self.dir = V(self.dir).normalize()
            up = _upright(V(0, 0, 1) - self.dir * self.dir.z)
            if up.Length < 1e-6:
                up = V(0, 1, 0) - self.dir * self.dir.y
            self.up = up.normalize()
            self.side = self.up.cross(self.dir)

    def decal(self, p, n=None):
        import math
        if self.kind == "cylinder":
            r = p - self.c
            h = r.dot(self.axis)
            flat = r - self.axis * h
            ang = math.atan2(flat.dot(self.side), flat.dot(self.ref))
            return ang * self.radius, h - self.h0, ang
        if self.kind == "sphere":
            r = (p - self.c).normalize()
            lat = math.asin(max(-1.0, min(1.0, r.dot(self.axis))))
            ang = math.atan2(r.dot(self.side), r.dot(self.ref))
            return ang * self.radius * math.cos(self.lat0), (lat - self.lat0) * self.radius, ang
        if n is not None and n.dot(self.dir) <= 0.02:
            return None
        d = p - self.mid
        return d.dot(self.side), d.dot(self.up), 0.0

    def frame_at(self, plane):
        """(point, normal, right, up) of the decal's centre on the face."""
        import math
        x, y = float(plane.DecalX or 0), float(plane.DecalY or 0)
        if self.kind == "cylinder":
            ang = x / max(self.radius, 1e-9)
            out = self.ref * math.cos(ang) + self.side * math.sin(ang)
            spot = self.c + self.axis * (self.h0 + y) + out * self.radius
            try:
                uv = self.face.Surface.parameter(spot)
                n = self.face.normalAt(*uv)
            except Exception:
                n = out
            right = self.axis.cross(n).normalize()
            return spot, n, right, n.cross(right)
        if self.kind == "sphere":
            ang = x / max(self.radius * math.cos(self.lat0), 1e-9)
            lat = self.lat0 + y / max(self.radius, 1e-9)
            flat = self.ref * math.cos(ang) + self.side * math.sin(ang)
            n = (flat * math.cos(lat) + self.axis * math.sin(lat)).normalize()
            right = self.axis.cross(n)
            if right.Length < 1e-6:
                right = self.side
            right.normalize()
            return self.c + n * self.radius, n, right, n.cross(right)
        return self.mid + self.side * x + self.up * y, self.dir, self.side, self.up

    def spot(self, plane):
        p, n, right, up = self.frame_at(plane)
        base = App.Rotation(right, up, n, "ZXY")
        rot = App.Rotation(n, float(plane.DecalRotation or 0.0)).multiply(base)
        return App.Placement(p + n * 0.02, rot)

    def extent(self, along):
        vals = []
        for e in self.face.Edges:
            for q in e.discretize(48):
                got = self.decal(q)
                if got is not None:
                    vals.append(got[0] if along == "u" else got[1])
        return (max(vals) - min(vals)) if vals else None


def _wrap(plane, face):
    return _Wrap(plane, face)


_drapes = {}        # (document, plane) -> (what the drape was made from, its nodes, the plane's own face sets)


def _padded(src):
    """The picture with a see-through border, so the drape clamps to nothing past the decal's edge."""
    image = QtGui.QImage(src)
    if image.isNull():
        return None, 0, 0, 0
    pad = 2
    out = QtGui.QImage(image.width() + 2 * pad, image.height() + 2 * pad, QtGui.QImage.Format_ARGB32)
    out.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(out)
    p.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
    p.drawImage(pad, pad, image)
    p.end()
    path = os.path.join(_cache(), "decal-drape-%s.png" % hashlib.md5(
        ("%s|%s" % (src, os.path.getmtime(src) if os.path.exists(src) else 0)).encode()).hexdigest()[:12])
    if not os.path.exists(path):
        out.save(path, "PNG")
    return path, pad, image.width(), image.height()


def drape_mesh(plane, face):
    """(points, normals, uvs, triangles) of the decal draped over its face, in the plane's own
    coordinates (so the drape moves with it), or None. Triangles the picture does not touch are left out."""
    import math
    w, h = float(plane.XSize.Value), float(plane.YSize.Value)
    if w <= 1e-9 or h <= 1e-9:
        return None
    wrap = _wrap(plane, face)
    size = max(face.BoundBox.DiagonalLength, 1e-3)
    deviation = min(0.05, size / 400.0)
    pts, tris = face.tessellate(deviation)
    # the drape's flat triangles cut inside the surface by up to the deviation: stand them off by more,
    # or the part's own (finer) shading pokes through the middle of each
    lift = 0.02 + 1.5 * deviation
    if not tris:
        return None
    surf = face.Surface
    rev = face.Orientation == "Reversed"
    x0, y0 = float(plane.DecalX or 0), float(plane.DecalY or 0)
    a = math.radians(float(plane.DecalRotation or 0.0))
    ca, sa = math.cos(a), math.sin(a)
    inv = plane.Placement.inverse()
    rinv = inv.Rotation
    out_p, out_n, out_uv, keep = [], [], [], []
    for q in pts:
        try:
            n = face.normalAt(*surf.parameter(q))
        except Exception:
            n = wrap.n0
        got = wrap.decal(q, n)
        if got is None:
            out_uv.append(None)
        else:
            ds, dt = got[0] - x0, got[1] - y0
            s2, t2 = ds * ca + dt * sa, -ds * sa + dt * ca
            out_uv.append((s2 / w + 0.5, t2 / h + 0.5, got[2]))
        out_p.append(inv.multVec(q + n * lift))
        out_n.append(rinv.multVec(n))
    for t in tris:
        uv = [out_uv[i] for i in t]
        if any(x is None for x in uv):
            continue
        if max(x[0] for x in uv) < 0 or min(x[0] for x in uv) > 1 or max(x[1] for x in uv) < 0 or min(x[1] for x in uv) > 1:
            continue
        angs = [x[2] for x in uv]
        if max(angs) - min(angs) > math.pi:
            continue        # across the back seam of a wrap
        keep.append(t)
    if not keep:
        return [], [], [], []
    return out_p, out_n, [(x[0], x[1]) if x else (0.0, 0.0) for x in out_uv], keep


def _plane_sets(plane):
    """[(mode group, its FaceSet, index)] of the picture plane's own flat picture."""
    from pivy import coin
    root = plane.ViewObject.RootNode
    out = []
    for i in range(root.getNumChildren()):
        sw = root.getChild(i)
        if sw.isOfType(coin.SoSwitch.getClassTypeId()) and str(sw.getName()) == "ModeSwitch":
            for j in range(sw.getNumChildren()):
                g = sw.getChild(j)
                if not g.isOfType(coin.SoGroup.getClassTypeId()):
                    continue
                for k in range(g.getNumChildren()):
                    c = g.getChild(k)
                    if c.isOfType(coin.SoFaceSet.getClassTypeId()) or str(c.getName()) == "FwDecalDrape":
                        out.append((g, c, k))
    return out


def drape(plane, shown):
    """Draws the decal's picture over its curved face in place of the flat picture plane."""
    if not App.GuiUp or getattr(plane, "ViewObject", None) is None:
        return False
    face = face_of(plane)
    if face is None:
        return False
    try:
        from pivy import coin
        key = (shown, plane.XSize.Value, plane.YSize.Value, str(plane.Placement), plane.DecalX, plane.DecalY,
               plane.DecalRotation, plane.DecalMapping, plane.DecalProjection, plane.DecalFace,
               getattr(plane, "DecalFaceSig", ""), face.Area, str(face.BoundBox))
        name = (plane.Document.Name, plane.Name)
        kept = _drapes.get(name)
        sets = _plane_sets(plane)
        if kept is not None and kept[0] == key and all(str(c.getName()) == "FwDecalDrape" for _g, c, _k in sets):
            return True
        texture, pad, iw, ih = _padded(shown)
        mesh = drape_mesh(plane, face)
        if texture is None or mesh is None:
            return False
        pts, nrm, uvs, tris = mesh
        tw, th = iw + 2.0 * pad, ih + 2.0 * pad
        sep = kept[1] if kept is not None else None
        if sep is None:
            sep = coin.SoSeparator()
            sep.setName("FwDecalDrape")
            sep.ref()
            sep.addChild(coin.SoPolygonOffset())
            hints = coin.SoShapeHints()
            hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
            sep.addChild(hints)
            for cls in (coin.SoTexture2, coin.SoTextureCoordinate2, coin.SoCoordinate3, coin.SoNormal):
                sep.addChild(cls())
            bind = coin.SoNormalBinding()
            bind.value = coin.SoNormalBinding.PER_VERTEX_INDEXED
            sep.addChild(bind)
            sep.addChild(coin.SoIndexedFaceSet())
        off, _hints, tex, tc, co, nn, _b, ifs = [sep.getChild(i) for i in range(8)]
        off.factor = -1.0
        off.units = -1.0
        tex.filename = texture
        tex.wrapS = coin.SoTexture2.CLAMP
        tex.wrapT = coin.SoTexture2.CLAMP
        tex.model = coin.SoTexture2.MODULATE
        tc.point.setValues(0, len(uvs), [((pad + u * iw) / tw, (pad + v * ih) / th) for u, v in uvs])
        tc.point.setNum(len(uvs))
        co.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
        co.point.setNum(len(pts))
        nn.vector.setValues(0, len(nrm), [(n.x, n.y, n.z) for n in nrm])
        nn.vector.setNum(len(nrm))
        idx = []
        for t in tris:
            idx += [t[0], t[1], t[2], -1]
        ifs.coordIndex.setValues(0, len(idx), idx)
        ifs.coordIndex.setNum(len(idx))
        ifs.textureCoordIndex.setValues(0, len(idx), idx)
        ifs.textureCoordIndex.setNum(len(idx))
        ifs.normalIndex.setValues(0, len(idx), idx)
        ifs.normalIndex.setNum(len(idx))
        flats = kept[2] if kept is not None else []
        for g, c, k in sets:
            if str(c.getName()) == "FwDecalDrape":
                continue
            c.ref()
            flats.append((g, c))
            g.replaceChild(k, sep)
        _drapes[name] = (key, sep, flats)
        return True
    except Exception as _fw_err:
        _fw_log("decalpm.py:drape", _fw_err)
        return False


def undrape(plane):
    """Back to the flat picture plane (the decal was moved to a flat face)."""
    name = (plane.Document.Name, plane.Name)
    kept = _drapes.pop(name, None)
    if kept is None:
        return
    try:
        for g, c in kept[2]:
            k = g.findChild(kept[1])
            if k >= 0:
                g.replaceChild(k, c)
            c.unref()
        kept[1].unref()
    except Exception as _fw_err:
        _fw_log("decalpm.py:undrape", _fw_err)


_clips = {}         # (document, plane) -> (what the cut picture was made from, its file)


def _clipped(plane, src):
    ""

    face = face_of(plane)
    image = QtGui.QImage(src)
    if face is None or image.isNull():
        return src
    try:
        w, h = float(plane.XSize.Value), float(plane.YSize.Value)
        if w <= 1e-9 or h <= 1e-9:
            return src
        width, height = image.width(), image.height()
        inv = plane.Placement.inverse()
        outline = QtGui.QPainterPath()
        outline.setFillRule(QtCore.Qt.OddEvenFill)
        for wire in face.Wires:
            pts = [inv.multVec(p) for p in wire.discretize(Number=max(64, 16 * len(wire.Edges)))]
            if len(pts) < 3:
                continue
            outline.addPolygon(QtGui.QPolygonF([QtCore.QPointF((q.x / w + 0.5) * width, (0.5 - q.y / h) * height)
                                                for q in pts]))
            outline.closeSubpath()
        if outline.contains(QtCore.QRectF(0, 0, width, height)):
            return src
        key = (src, os.path.getmtime(src) if os.path.exists(src) else 0, w, h, str(plane.Placement), plane.DecalFace,
               getattr(plane, "DecalFaceSig", ""))
        name = (plane.Document.Name, plane.Name)
        kept = _clips.get(name)
        if kept is not None and kept[0] == key and os.path.exists(kept[1]):
            return kept[1]
        mask = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32_Premultiplied)
        mask.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(mask)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillPath(outline, QtGui.QColor(255, 255, 255))
        p.end()
        out = image.convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied)
        p = QtGui.QPainter(out)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
        p.drawImage(0, 0, mask)
        p.end()
        # two files a decal takes turns with, so the picture plane always sees a new name and reloads it
        turn = 1 - int(kept[1].endswith("-1.png")) if kept is not None else 0
        path = os.path.join(_cache(), "decal-cut-%s-%s-%d.png" % (
            hashlib.md5(plane.Document.Name.encode()).hexdigest()[:8], plane.Name, turn))
        out.save(path, "PNG")
        _clips[name] = (key, path)
        return path
    except Exception as _fw_err:
        _fw_log("decalpm.py:clip", _fw_err)
        return src


def aspect(path):
    image = QtGui.QImageReader(path)
    s = image.size()
    return (s.height() / float(s.width())) if s.isValid() and s.width() > 0 else 1.0


# --------------------------------------------------------------------------- saved and own decals
def save_decal(plane, path):
    data = {"image": plane.DecalImage, "mask": plane.DecalMask, "mask_file": plane.DecalMaskFile,
            "mask_colors": plane.DecalMaskColors, "mapping": plane.DecalMapping,
            "projection": plane.DecalProjection, "width": plane.XSize.Value, "height": plane.YSize.Value,
            "rotation": plane.DecalRotation, "fixed_aspect": plane.DecalFixedAspect,
            "mirror_h": plane.DecalMirrorH, "mirror_v": plane.DecalMirrorV, "label": plane.Label}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return path


def load_decal(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _draw_own(name, size=128):
    img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    if name == "Label":
        p.setBrush(QtGui.QColor("#ffffff"))
        p.setPen(QtGui.QPen(QtGui.QColor("#1f3b73"), 6))
        p.drawRoundedRect(QtCore.QRectF(8, 30, size - 16, size - 60), 12, 12)
        p.setPen(QtGui.QColor("#1f3b73"))
        f = p.font()
        f.setPixelSize(28)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QtCore.QRectF(8, 30, size - 16, size - 60), QtCore.Qt.AlignCenter, "LABEL")
    elif name == "Caution":
        p.setBrush(QtGui.QColor("#ffcc00"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 6))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(size / 2, 10), QtCore.QPointF(size - 8, size - 14),
                                       QtCore.QPointF(8, size - 14)]))
        f = p.font()
        f.setPixelSize(64)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QtCore.QRectF(0, 30, size, size - 40), QtCore.Qt.AlignCenter, "!")
    elif name == "Arrow":
        p.setBrush(QtGui.QColor("#d22"))
        p.setPen(QtCore.Qt.NoPen)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(10, 48), QtCore.QPointF(70, 48), QtCore.QPointF(70, 20),
                                       QtCore.QPointF(118, 64), QtCore.QPointF(70, 108), QtCore.QPointF(70, 80),
                                       QtCore.QPointF(10, 80)]))
    else:   # Checker
        for i in range(8):
            for j in range(8):
                p.fillRect(i * size // 8, j * size // 8, size // 8, size // 8,
                           QtGui.QColor("#202020" if (i + j) % 2 else "#f0f0f0"))
    p.end()
    path = os.path.join(_cache(), "own-%s.png" % name.lower())
    img.save(path, "PNG")
    return path


OWN = ("Label", "Caution", "Arrow", "Checker")


def library():
    """The Task Pane's Decals: [(name, picture, .fwdecal path or None)]."""
    out = [(n, _draw_own(n), None) for n in OWN]
    try:
        for f in sorted(os.listdir(user_folder())):
            if f.lower().endswith(".fwdecal"):
                path = os.path.join(user_folder(), f)
                try:
                    data = load_decal(path)
                    out.append((os.path.splitext(f)[0], data.get("image", ""), path))
                except Exception:
                    continue
    except Exception as _fw_err:
        _fw_log("decalpm.py:418", _fw_err)
    return out


# --------------------------------------------------------------------------- making one
def new_decal(obj, sub, image, saved=None, show=True):
    """A decal of the picture on obj's face sub; with show, the Decals PropertyManager opens on it."""
    from . import insertextras
    face = obj.Shape.getElement(sub)
    doc = obj.Document
    doc.openTransaction("Decal")
    plane = insertextras.apply_decal(obj, face, image)
    ensure(plane)
    plane.DecalFace = sub
    plane.DecalImage = image
    plane.DecalFixedAspect = True
    if saved:
        for key, prop in (("mask", "DecalMask"), ("mask_file", "DecalMaskFile"), ("mask_colors", "DecalMaskColors"),
                          ("mapping", "DecalMapping"), ("projection", "DecalProjection"), ("rotation", "DecalRotation"),
                          ("fixed_aspect", "DecalFixedAspect"), ("mirror_h", "DecalMirrorH"), ("mirror_v", "DecalMirrorV")):
            if key in saved:
                setattr(plane, prop, saved[key])
        if saved.get("width"):
            plane.XSize = saved["width"]
            plane.YSize = saved.get("height") or saved["width"]
    else:
        plane.YSize = plane.XSize.Value * aspect(image)
    refresh(plane)
    remember_face(plane)
    install()
    if show and App.GuiUp:
        panel = DecalPanel(plane, True)
        Gui.Control.showDialog(panel)
        return panel
    doc.commitTransaction()
    return plane


def edit(plane):
    """Edit Decal on a decal (DisplayManager double-click, its right-click)."""
    if plane is None:
        return None
    ensure(plane)
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    plane.Document.openTransaction("Edit Decal")
    try:
        panel = DecalPanel(plane, False)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            plane.Document.abortTransaction()
        except Exception:
            pass
        raise
    return panel


def _component_face(top, sub):
    """(component, 'FaceN') for a face picked on an assembly component (a link along the pick's path),
    the face named in the component's own shape, which already stands where the component does; or None.
    Without it a decal picked on the second copy of a part landed on the part's own file position,
    on the first copy (vd112, 11-20)."""
    names = sub.split(".")[:-1]
    if not names or not sub.rsplit(".", 1)[-1].startswith("Face"):
        return None
    cur, comp = top, None
    for name in names:
        child = cur.Document.getObject(name) if cur is not None else None
        if child is None:
            break
        if child.TypeId == "App::Link":
            comp = child
            break
        cur = child
    if comp is None:
        return None
    import Part
    picked = Part.getShape(top, sub, needSubElement=True)
    if picked is None or picked.isNull() or picked.ShapeType != "Face":
        return None
    area, centre = picked.Area, picked.CenterOfMass
    tol = 1e-6 * max(1.0, picked.BoundBox.DiagonalLength)
    for i, f in enumerate(comp.Shape.Faces, 1):
        if abs(f.Area - area) <= 1e-6 * max(1.0, area) and (f.CenterOfMass - centre).Length <= tol:
            return comp, "Face%d" % i
    return None


def _flat_pick():
    try:
        for s in Gui.Selection.getSelectionEx("", 0):
            for sub in s.SubElementNames:
                hit = _component_face(s.Object, sub)
                if hit is not None and hit[0].Shape.getElement(hit[1]).ShapeType == "Face":
                    return hit
    except Exception as _fw_err:
        _fw_log("decalpm.py:component", _fw_err)
    for s in Gui.Selection.getSelectionEx():
        for sub in s.SubElementNames:
            if sub.startswith("Face"):
                obj, name = s.Object, sub
                try:
                    from . import refplane
                    obj, name = refplane.resolve(s.Object, sub)
                except Exception as _fw_err:
                    _fw_log("decalpm.py:478", _fw_err)
                try:
                    if obj.Shape.getElement(name).ShapeType == "Face":
                        return obj, name
                except Exception as _fw_err:
                    _fw_log("decalpm.py:492", _fw_err)
                    continue
    return None


def command():
    """Edit Decal: a picked decal opens; a picked face (flat or curved) gets a new decal (a picture to choose)."""
    for o in Gui.Selection.getSelection():
        if o.TypeId == "Image::ImagePlane" and hasattr(o, "DecalOf"):
            return edit(o)
    hit = _flat_pick()
    if hit is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Edit Decal", "Pick a face for the decal first.")
        return None
    path, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Decal image", "",
                                                     "Pictures (*.png *.jpg *.jpeg *.bmp *.svg);;Decals (*.fwdecal)")
    if not path:
        return None
    return apply_from_library(path, hit)


def apply_from_library(path, hit=None):
    """A Task Pane decal (a picture or a .fwdecal) on the picked face (or the face given)."""
    hit = hit or _flat_pick()
    if hit is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Decals", "Pick a face for the decal first.")
        return None
    saved = None
    if path.lower().endswith(".fwdecal"):
        saved = load_decal(path)
        path = saved.get("image", "")
    Gui.Selection.clearSelection()
    return new_decal(hit[0], hit[1], path, saved)


# --------------------------------------------------------------------------- the PropertyManager
def _spin(lo, hi, value, suffix, decimals=2):
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSuffix(suffix)
    s.setValue(value)
    s.setKeyboardTracking(False)
    return s


class DecalPanel:
    def __init__(self, plane, new):
        self.plane, self.new = ensure(plane), new
        self.saved = state(plane)
        self._busy = False
        w = QtWidgets.QWidget()
        w.setObjectName("SWDecalsPM")
        w.setWindowTitle(TITLE)
        w.setProperty("swstyle_pm_title", TITLE)
        lay = QtWidgets.QVBoxLayout(w)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("SWDecalTabs")
        lay.addWidget(self.tabs)
        self._image_tab()
        self._mapping_tab()
        self._light_tab()
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.form = w
        self._load()
        Gui.Selection.addObserver(self)

    # ---- Image
    def _image_tab(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        box = QtWidgets.QGroupBox("Decal Preview")
        bl = QtWidgets.QVBoxLayout(box)
        self.preview = QtWidgets.QLabel()
        self.preview.setObjectName("SWDecalPreview")
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setMinimumHeight(110)
        bl.addWidget(self.preview)
        bl.addWidget(QtWidgets.QLabel("Image file path:"))
        row = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit()
        self.path.setObjectName("SWDecalPath")
        self.path.editingFinished.connect(lambda: self._set_image(self.path.text()))
        row.addWidget(self.path, 1)
        browse = QtWidgets.QPushButton("Browse...")
        browse.setObjectName("SWDecalBrowse")
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        bl.addLayout(row)
        save = QtWidgets.QPushButton("Save Decal...")
        save.setObjectName("SWDecalSave")
        save.clicked.connect(self.save)
        bl.addWidget(save)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Mask Image")
        bl = QtWidgets.QVBoxLayout(box)
        self.masks = {}
        for m in MASKS:
            r = QtWidgets.QRadioButton(m)
            r.setObjectName("SWDecalMask_" + m.split()[0])
            r.toggled.connect(self._changed)
            self.masks[m] = r
            bl.addWidget(r)
            if m == "Image mask file":
                self.mask_path_row = QtWidgets.QWidget()
                row = QtWidgets.QHBoxLayout(self.mask_path_row)
                row.setContentsMargins(0, 0, 0, 0)
                self.mask_path = QtWidgets.QLineEdit()
                self.mask_path.setObjectName("SWDecalMaskPath")
                self.mask_path.editingFinished.connect(self._changed)
                row.addWidget(self.mask_path, 1)
                b = QtWidgets.QPushButton("Browse...")
                b.clicked.connect(self.browse_mask)
                row.addWidget(b)
                bl.addWidget(self.mask_path_row)
            if m == "Selective color mask":
                self.mask_colours_row = QtWidgets.QWidget()
                row = QtWidgets.QHBoxLayout(self.mask_colours_row)
                row.setContentsMargins(0, 0, 0, 0)
                self.mask_colours = QtWidgets.QLineEdit()
                self.mask_colours.setObjectName("SWDecalMaskColors")
                self.mask_colours.setPlaceholderText("#ffffff")
                self.mask_colours.editingFinished.connect(self._changed)
                row.addWidget(self.mask_colours, 1)
                b = QtWidgets.QPushButton("Add Color...")
                b.clicked.connect(self.add_mask_colour)
                row.addWidget(b)
                bl.addWidget(self.mask_colours_row)
        lay.addWidget(box)
        lay.addStretch(1)
        self.tabs.addTab(page, "Image")

    # ---- Mapping
    def _mapping_tab(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        box = QtWidgets.QGroupBox("Selected Geometry")
        bl = QtWidgets.QVBoxLayout(box)
        self.geometry = QtWidgets.QListWidget()
        self.geometry.setObjectName("SWDecalGeometry")
        self.geometry.setMaximumHeight(40)
        bl.addWidget(self.geometry)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Mapping")
        form = QtWidgets.QFormLayout(box)
        self.mapping = QtWidgets.QComboBox()
        self.mapping.setObjectName("SWDecalMapping")
        self.mapping.addItems(list(MAPPINGS))
        self.mapping.currentIndexChanged.connect(self._changed)
        form.addRow("Mapping type:", self.mapping)
        self.projection = QtWidgets.QComboBox()
        self.projection.setObjectName("SWDecalProjection")
        self.projection.addItems(list(PROJECTIONS))
        self.projection.currentIndexChanged.connect(self._changed)
        form.addRow("Projection direction:", self.projection)
        self.mapping_form = form
        self.x = _spin(-1e5, 1e5, 0.0, " mm")
        self.x.setObjectName("SWDecalX")
        self.y = _spin(-1e5, 1e5, 0.0, " mm")
        self.y.setObjectName("SWDecalY")
        form.addRow("Horizontal location:", self.x)
        form.addRow("Vertical location:", self.y)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Size/Orientation")
        form = QtWidgets.QFormLayout(box)
        self.fixed = QtWidgets.QCheckBox("Fixed aspect ratio")
        self.fixed.setObjectName("SWDecalFixedAspect")
        form.addRow(self.fixed)
        row = QtWidgets.QHBoxLayout()
        fw = QtWidgets.QPushButton("Fit width to selection")
        fw.setObjectName("SWDecalFitWidth")
        fw.clicked.connect(lambda: self.fit("u"))
        fh = QtWidgets.QPushButton("Fit height to selection")
        fh.setObjectName("SWDecalFitHeight")
        fh.clicked.connect(lambda: self.fit("v"))
        row.addWidget(fw)
        row.addWidget(fh)
        form.addRow(row)
        self.width = _spin(0.01, 1e5, 10.0, " mm")
        self.width.setObjectName("SWDecalWidth")
        self.height = _spin(0.01, 1e5, 10.0, " mm")
        self.height.setObjectName("SWDecalHeight")
        form.addRow("Width:", self.width)
        form.addRow("Height:", self.height)
        self.ratio = QtWidgets.QLabel("")
        self.ratio.setObjectName("SWDecalRatio")
        form.addRow("Aspect ratio:", self.ratio)
        self.rotation = _spin(-360.0, 360.0, 0.0, " °")
        self.rotation.setObjectName("SWDecalRotation")
        form.addRow("Rotation:", self.rotation)
        self.mirror_h = QtWidgets.QCheckBox("Mirror horizontally")
        self.mirror_h.setObjectName("SWDecalMirrorH")
        self.mirror_v = QtWidgets.QCheckBox("Mirror vertically")
        self.mirror_v.setObjectName("SWDecalMirrorV")
        form.addRow(self.mirror_h)
        form.addRow(self.mirror_v)
        lay.addWidget(box)
        lay.addStretch(1)
        for s in (self.x, self.y, self.rotation):
            s.valueChanged.connect(self._changed)
        self.width.valueChanged.connect(lambda v: self._size("w"))
        self.height.valueChanged.connect(lambda v: self._size("h"))
        for c in (self.fixed, self.mirror_h, self.mirror_v):
            c.toggled.connect(self._changed)
        self.tabs.addTab(page, "Mapping")

    # ---- Illumination
    def _light_tab(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        self.underlying = QtWidgets.QCheckBox("Use underlying appearance's illumination properties")
        self.underlying.setObjectName("SWDecalUnderlying")
        self.underlying.toggled.connect(self._changed)
        lay.addWidget(self.underlying)
        self.own_light = QtWidgets.QWidget()
        self.own_light.setObjectName("SWDecalOwnIllumination")
        row = QtWidgets.QHBoxLayout(self.own_light)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QtWidgets.QLabel("Transparent amount:"))
        self.transparent = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.transparent.setObjectName("SWDecalTransparent")
        self.transparent.setRange(0, 100)
        self.transparent.valueChanged.connect(self._changed)
        row.addWidget(self.transparent, 1)
        lay.addWidget(self.own_light)
        lay.addStretch(1)
        self.tabs.addTab(page, "Illumination")

    # ---- values in and out
    def _load(self):
        p = self.plane
        self._busy = True
        try:
            self.path.setText(p.DecalImage)
            self.masks.get(p.DecalMask, self.masks[MASKS[3]]).setChecked(True)
            self.mask_path.setText(p.DecalMaskFile)
            self.mask_colours.setText(p.DecalMaskColors)
            self.mapping.setCurrentText(p.DecalMapping)
            self.projection.setCurrentText(p.DecalProjection)
            self.x.setValue(p.DecalX)
            self.y.setValue(p.DecalY)
            self.fixed.setChecked(p.DecalFixedAspect)
            self.width.setValue(p.XSize.Value)
            self.height.setValue(p.YSize.Value)
            self.rotation.setValue(p.DecalRotation)
            self.mirror_h.setChecked(p.DecalMirrorH)
            self.mirror_v.setChecked(p.DecalMirrorV)
            self.underlying.setChecked(not p.DecalOwnLight)
            self.transparent.setValue(_transparency(p))
        finally:
            self._busy = False
        self._show()

    def _show(self):
        p = self.plane
        pix = QtGui.QPixmap(p.ImageFile)
        if not pix.isNull():
            self.preview.setPixmap(pix.scaled(160, 110, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        self.geometry.clear()
        if p.DecalOf is not None and p.DecalFace:
            self.geometry.addItem("%s@%s" % (p.DecalFace, p.DecalOf.Label))

        projection = self.mapping.currentText() == "Projection"
        if hasattr(self.mapping_form, "setRowVisible"):
            self.mapping_form.setRowVisible(self.projection, projection)
        else:
            self.projection.setVisible(projection)
            label = self.mapping_form.labelForField(self.projection)
            if label is not None:
                label.setVisible(projection)
        self.mask_path_row.setVisible(self.masks["Image mask file"].isChecked())
        self.mask_colours_row.setVisible(self.masks["Selective color mask"].isChecked())
        self.own_light.setVisible(not self.underlying.isChecked())
        self.ratio.setText("%.3f" % (p.YSize.Value / max(p.XSize.Value, 1e-9)))

    def _size(self, which):
        if self._busy:
            return
        if self.fixed.isChecked():
            r = self.plane.YSize.Value / max(self.plane.XSize.Value, 1e-9)
            self._busy = True
            try:
                if which == "w":
                    self.height.setValue(self.width.value() * r)
                else:
                    self.width.setValue(self.height.value() / max(r, 1e-9))
            finally:
                self._busy = False
        self._changed()

    def _changed(self, *args):
        if self._busy:
            return
        p = self.plane
        p.DecalMask = next((m for m, r in self.masks.items() if r.isChecked()), MASKS[3])
        p.DecalMaskFile = self.mask_path.text()
        p.DecalMaskColors = self.mask_colours.text()
        p.DecalMapping = self.mapping.currentText()
        p.DecalProjection = self.projection.currentText()
        p.DecalX = self.x.value()
        p.DecalY = self.y.value()
        p.DecalRotation = self.rotation.value()
        p.DecalFixedAspect = self.fixed.isChecked()
        p.DecalMirrorH = self.mirror_h.isChecked()
        p.DecalMirrorV = self.mirror_v.isChecked()
        p.DecalOwnLight = not self.underlying.isChecked()
        p.XSize = self.width.value()
        p.YSize = self.height.value()
        refresh(p)
        if p.DecalOwnLight:
            _set_transparency(p, self.transparent.value())
        self._show()

    def _set_image(self, path):
        if not path or path == self.plane.DecalImage:
            return
        if not os.path.exists(path):
            self.note.setText("There is no picture at %s." % path)
            return
        self.plane.DecalImage = path
        if self.fixed.isChecked():
            self._busy = True
            self.height.setValue(self.width.value() * aspect(path))
            self._busy = False
        self.note.setText("")
        self._changed()

    def browse(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(self.form, "Decal image", os.path.dirname(self.plane.DecalImage),
                                                         "Pictures (*.png *.jpg *.jpeg *.bmp *.svg)")
        if path:
            self.path.setText(path)
            self._set_image(path)

    def browse_mask(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(self.form, "Mask image", "", "Pictures (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.mask_path.setText(path)
            self.masks["Image mask file"].setChecked(True)
            self._changed()

    def add_mask_colour(self):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor("#ffffff"), self.form, "Selective color mask")
        if c.isValid():
            have = [t for t in self.mask_colours.text().split(",") if t.strip()]
            self.mask_colours.setText(",".join(have + [c.name()]))
            self.masks["Selective color mask"].setChecked(True)
            self._changed()

    def save(self, path=None):
        if not path:
            path, _f = QtWidgets.QFileDialog.getSaveFileName(
                self.form, "Save Decal", os.path.join(user_folder(), self.plane.Label.replace("Decal ", "") + ".fwdecal"),
                "Decals (*.fwdecal)")
        if not path:
            return None
        if not path.lower().endswith(".fwdecal"):
            path += ".fwdecal"
        return save_decal(self.plane, path)

    def fit(self, along):
        size = extent(self.plane, along)
        if not size:
            return None
        if along == "u":
            self.width.setValue(size)
        else:
            self.height.setValue(size)
        return size

    # ---- picks: another face moves the decal there
    def addSelection(self, doc, name, sub, point):
        if pickguard.stale(self, self.plane):
            return
        if not sub.startswith("Face") and "." not in sub:
            return
        try:
            d = App.getDocument(doc)
        except Exception:
            return
        obj = d.getObject(name)
        if obj is None or obj == self.plane:
            return
        try:
            from . import refplane
            obj, sub = refplane.resolve(obj, sub)
        except Exception as _fw_err:
            _fw_log("decalpm.py:855", _fw_err)
        QtCore.QTimer.singleShot(0, lambda: self.pick(obj, sub))

    def pick(self, obj, sub):
        try:
            face = obj.Shape.getElement(sub)
        except Exception:
            return False
        if face.ShapeType != "Face":
            self.note.setText("Pick a face.")
            return False
        self.plane.DecalOf = obj
        self.plane.DecalFace = sub
        self.note.setText("")
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("decalpm.py:872", _fw_err)
        self._changed()
        return True

    # ---- OK / Cancel
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _drop(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("decalpm.py:884", _fw_err)

    def accept(self):
        self._drop()
        self._changed()
        self.plane.Document.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._drop()
        doc, name = self.plane.Document, self.plane.Name
        Gui.Control.closeDialog()
        if self.new:
            doc.abortTransaction()
            if doc.getObject(name) is not None:
                doc.removeObject(name)
        else:
            restore(self.plane, self.saved)
            doc.commitTransaction()
        doc.recompute()
        return True
