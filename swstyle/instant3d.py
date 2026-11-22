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

import math
import weakref

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import events
from . import checkstate, paths

PARAM = "Instant3D"
ARROW_PX = 70                # arrow length on screen
HIT_PX = 9                   # pointer this close to the arrow grabs it
COLOR = (0.16, 0.42, 0.85)
HOVER = (1.0, 0.55, 0.0)
STEP = 0.01                  # mm the depth is rounded to while dragging
MIN_DEPTH = 0.01
RULER_GAP_PX = 40            # ruler this far beside the arrow
RULER_SNAP_PX = 14           # pointer this close to the ruler snaps to its marks
TICK_MIN_PX = 8              # marks at least this far apart on screen
RULER_COLOR = (0.15, 0.15, 0.15)


def nice_step(raw):
    """The smallest 1, 2 or 5 x 10^n at least raw."""
    if raw <= 0:
        return 1.0
    e = math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        step = m * 10 ** e
        if step >= raw * (1 - 1e-9):
            return float(step)
    return float(10 ** (e + 1))


def enabled():
    return paths.params().GetBool(PARAM, True)


def _plane_of(face):
    """(point, unit normal) of a planar face, or None."""
    try:
        surf = face.Surface
        if not hasattr(surf, "Axis") or surf.__class__.__name__ != "Plane":
            return None
        n = App.Vector(face.normalAt(0, 0))
        n.normalize()
        return App.Vector(face.CenterOfMass), n
    except Exception:
        return None


def _same_plane(face, plane, tol=1e-5):
    p = _plane_of(face)
    if p is None:
        return False
    c, n = p
    pc, pn = plane
    return abs(abs(n.dot(pn)) - 1) < 1e-7 and abs((c - pc).dot(pn)) < tol


def _sketch_plane(feature):
    """(origin, normal) of the feature's sketch, in the body's coordinates."""
    profile = feature.Profile[0] if isinstance(feature.Profile, tuple) else feature.Profile
    if profile is None or not hasattr(profile, "Placement"):
        return None
    pl = profile.Placement
    return pl.Base, pl.Rotation.multVec(App.Vector(0, 0, 1))


def _sides(feature):
    """'one', 'two' or 'symmetric'. FreeCAD 1.1 has SideType (One side / Two sides / Symmetric)
    with Type and Type2 per side; older files have Midplane and a TwoLengths Type."""
    side = getattr(feature, "SideType", "One side")
    if side == "Symmetric" or getattr(feature, "Midplane", False):
        return "symmetric"
    if side == "Two sides" or str(feature.Type).lstrip("?") == "TwoLengths":
        return "two"
    return "one"


def depth_handle(feature, face):
    """For a picked face of a Pad/Pocket, what dragging it changes: (property, unit direction
    the face moves for a bigger value, factor) or None. factor is 2 for Symmetric (both sides
    grow, the picked face moves half the change)."""
    if feature.TypeId not in ("PartDesign::Pad", "PartDesign::Pocket"):
        return None
    plane = _sketch_plane(feature)
    sub = getattr(feature, "AddSubShape", None)
    if plane is None or sub is None or sub.isNull():
        return None
    origin, normal = plane
    fp = _plane_of(face)
    if fp is None or abs(abs(fp[1].dot(normal)) - 1) > 1e-7:
        return None
    sides = _sides(feature)
    # the caps of the added/removed prism parallel to the sketch, and which one the face sits on
    for cap in sub.Faces:
        if not _same_plane(cap, (fp[0], fp[1])):
            continue
        dist = (App.Vector(cap.CenterOfMass) - origin).dot(normal)
        if abs(dist) < 1e-6:
            return None          # the face on the sketch plane does not move
        out = normal * (1 if dist > 0 else -1)
        if sides == "symmetric":
            return ("Length", out, 2.0) if feature.Type == "Length" else None
        if sides == "two":
            # Length goes along the extrude direction; Length2 the other way
            first = out.dot(_extrude_direction(feature, normal)) > 0
            if str(feature.Type).lstrip("?") == "TwoLengths":
                return ("Length" if first else "Length2"), out, 1.0
            kind = feature.Type if first else getattr(feature, "Type2", "Length")
            return (("Length" if first else "Length2"), out, 1.0) if kind == "Length" else None
        return ("Length", out, 1.0) if feature.Type == "Length" else None
    return None


DRESS_TYPES = ("PartDesign::Fillet", "PartDesign::Chamfer", "PartDesign::Revolution", "PartDesign::Groove",
               "PartDesign::Hole", "PartDesign::Thickness")


def _new_face(feature, face):
    """True when the face is one this feature made (not in the shape it started from)."""
    base = getattr(feature, "BaseFeature", None)
    if base is None or base.Shape.isNull():
        return True
    c, a = face.CenterOfMass, face.Area
    return not any(abs(f.Area - a) < 1e-6 and f.CenterOfMass.distanceToPoint(c) < 1e-6 for f in base.Shape.Faces)


def dress_handle(feature, face):
    ""


    kind = feature.TypeId
    if kind in ("PartDesign::Fillet", "PartDesign::Chamfer"):
        if not _new_face(feature, face):
            return None
        surf = type(face.Surface).__name__
        if kind == "PartDesign::Fillet":
            radius = float(feature.Radius)
            r = getattr(face.Surface, "Radius", getattr(face.Surface, "MinorRadius", None))
            if r is None or abs(r - radius) > 1e-4 * max(radius, 1.0):
                return None
            prop = "Radius"
        else:
            if surf != "Plane" or str(getattr(feature, "ChamferType", "Equal distance")) != "Equal distance":
                return None
            prop = "Size"
        u, v = face.Surface.parameter(_centre(face))
        n = face.normalAt(u, v)
        if face.Orientation == "Reversed":
            n = n * -1
        return prop, App.Vector(n) * -1, 1.0
    if kind == "PartDesign::Hole":
        return _hole_handle(feature, face)
    if kind == "PartDesign::Thickness":
        # a shell's inside face: dragging it into the hollow makes the wall thicker
        if not _new_face(feature, face) or str(getattr(feature, "Mode", "Skin")) != "Skin":
            return None
        u, v = face.Surface.parameter(_centre(face))     # inward or outward, the new wall face moves out of the material
        n = App.Vector(face.normalAt(u, v))
        if face.Orientation == "Reversed":
            n = n * -1
        return "Value", n, 1.0
    if kind in ("PartDesign::Revolution", "PartDesign::Groove"):
        if str(getattr(feature, "Type", "Angle")) not in ("Angle", "0") or _sides(feature) != "one":
            return None
        fp = _plane_of(face)
        if fp is None:
            return None
        base, axis = App.Vector(feature.Base), App.Vector(feature.Axis)
        if axis.Length < 1e-9 or abs(fp[1].dot(axis)) > 1e-6:
            return None
        axis.normalize()
        plane = _sketch_plane(feature)
        centre = _centre(face)
        if plane is not None and abs((centre - plane[0]).dot(plane[1])) < 1e-6:
            return None              # the face on the sketch plane stays put
        r = centre - base
        r = r - axis * r.dot(axis)
        if r.Length < 1e-6:
            return None
        way = axis.cross(r)
        way.normalize()
        # the way the end face moves for more angle: away from the sketch plane round the axis
        if plane is not None and (centre + way * 1e-3 - plane[0]).dot(plane[1]) * (centre - plane[0]).dot(plane[1]) < 0:
            way = way * -1
        return "Angle", way, 180.0 / (math.pi * r.Length)
    return None


def _rotary(feat, prop, gpl, base, direction):
    """A revolve's or groove's end face turns round its axis: {"centre" (on the axis, level with
    the face), "axis", "arm" (axis to face centre), "zero" (unit arm at angle 0, the sketch
    plane), "sign" (+1 when more angle turns the right-hand way round axis)}. None otherwise."""
    if prop != "Angle" or feat.TypeId not in ("PartDesign::Revolution", "PartDesign::Groove"):
        return None
    try:
        origin = gpl.multVec(App.Vector(feat.Base))
        axis = gpl.Rotation.multVec(App.Vector(feat.Axis))
    except Exception:
        return None
    if axis.Length < 1e-9:
        return None
    axis.normalize()
    r = base - origin
    centre = origin + axis * r.dot(axis)
    arm = base - centre
    if arm.Length < 1e-6:
        return None
    sign = 1.0 if axis.cross(arm).dot(direction) > 0 else -1.0
    angle = float(feat.Angle.Value)
    zero = App.Rotation(axis, -sign * angle).multVec(arm)
    zero.normalize()
    return {"centre": centre, "axis": axis, "arm": arm, "zero": zero, "sign": sign}


def _hole_handle(feature, face):
    """The bottom of a Hole Wizard hole (its flat end or drill point) drags the hole's Depth."""
    if str(getattr(feature, "DepthType", "Dimension")) != "Dimension" or not _new_face(feature, face):
        return None
    plane = _sketch_plane(feature)
    if plane is None:
        return None
    origin, normal = plane
    down = normal * (1 if getattr(feature, "Reversed", False) else -1)
    surf = face.Surface
    name = type(surf).__name__
    centre = _centre(face)
    if name == "Plane":
        fp = _plane_of(face)
        if fp is None or abs(abs(fp[1].dot(normal)) - 1) > 1e-7:
            return None
    elif name == "Cone":
        if abs(abs(App.Vector(surf.Axis).dot(normal)) - 1) > 1e-6:
            return None
    else:
        return None
    if (centre - origin).dot(down) < 1e-6:
        return None              # a counterbore's floor or the sketch face: not the bottom
    # the deepest such face is the bottom (a counterbore floor sits higher)
    deepest = max((f for f in feature.Shape.Faces if type(f.Surface).__name__ in ("Plane", "Cone")
                   and _new_face(feature, f) and f.distToShape(face)[0] < 10 * feature.Diameter.Value),
                  key=lambda f: (_centre(f) - origin).dot(down), default=face)
    if (_centre(deepest) - origin).dot(down) > (centre - origin).dot(down) + 1e-6:
        return None
    return "Depth", down, 1.0


def _extrude_direction(feature, normal):
    """The side Length goes: the sketch normal for a Pad, against it for a Pocket, flipped
    when Reversed."""
    d = App.Vector(normal)
    if feature.TypeId == "PartDesign::Pocket":
        d = d * -1
    if getattr(feature, "Reversed", False):
        d = d * -1
    return d


def feature_for_face(obj, sub):
    """The Pad/Pocket in obj's history whose end face is obj's sub-element: (feature, face,
    handle) or None. obj is the picked feature (often a later one) or its Body."""
    if obj is None or not sub.startswith("Face"):
        return None
    body = obj if obj.TypeId == "PartDesign::Body" else _body_of(obj)
    shape_obj = obj
    if obj.TypeId == "PartDesign::Body":
        shape_obj = obj.Tip
        if shape_obj is None:
            return None
    try:
        face = shape_obj.Shape.getElement(sub)
    except Exception:
        return None
    feats = body.Group if body is not None else [shape_obj]
    if shape_obj in feats:
        feats = feats[:feats.index(shape_obj) + 1]
    for feat in reversed(feats):
        if feat.TypeId in DRESS_TYPES:
            try:
                handle = dress_handle(feat, face)
            except Exception:
                handle = None
            if handle is not None:
                return feat, face, handle
            continue
        if feat.TypeId not in ("PartDesign::Pad", "PartDesign::Pocket"):
            continue
        handle = depth_handle(feat, face)
        if handle is not None:
            return feat, face, handle
    return None


_TREE_FACE = {}


def _page_open():
    ""


    try:
        return bool(Gui.Control.activeDialog())
    except Exception:
        return False


def tree_face(obj):
    ""


    if obj is None or obj.TypeId not in ("PartDesign::Pad", "PartDesign::Pocket") + tuple(DRESS_TYPES):
        return None
    try:
        shape = obj.Shape
        key = (obj.Document.Name, obj.Name, shape.hashCode(), len(shape.Faces))
    except Exception:
        return None
    if key in _TREE_FACE:
        return _TREE_FACE[key]
    best = None
    for i in range(1, len(shape.Faces) + 1):
        try:
            found = feature_for_face(obj, "Face%d" % i)
        except Exception:
            found = None
        if found is None or found[0] is not obj:
            continue
        prop = found[2][0]
        if prop in ("Length", "Radius", "Size") or best is None:
            best = "Face%d" % i
            if prop in ("Length", "Radius", "Size"):
                break
    if len(_TREE_FACE) > 64:
        _TREE_FACE.clear()
    _TREE_FACE[key] = best
    return best


PROFILE_FEATURES = ("PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution",
                    "PartDesign::Groove", "PartDesign::AdditivePipe", "PartDesign::SubtractivePipe",
                    "PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft", "PartDesign::AdditiveHelix",
                    "PartDesign::SubtractiveHelix", "PartDesign::Hole")


def _centre(shape):
    """The area centre of a face or of several (a sketch with two separate outlines gives a
    Compound of faces, which has no CenterOfMass)."""
    if hasattr(shape, "CenterOfMass"):
        return App.Vector(shape.CenterOfMass)
    faces = shape.Faces
    total = sum(f.Area for f in faces)
    if not faces or total <= 0:
        return App.Vector(shape.BoundBox.Center)
    centre = App.Vector()
    for f in faces:
        centre += App.Vector(f.CenterOfMass) * (f.Area / total)
    return centre


def _profile_face(sketch):
    """The sketch's closed profiles as one face (holes inside outlines), or None."""
    import Part
    shape = sketch.Shape
    wires = [w for w in shape.Wires if w.isClosed()]
    if not wires:
        return None
    try:
        face = Part.makeFace(wires, "Part::FaceMakerBullseye")
        return face if face.Faces else None
    except Exception:
        return None


def _sketch_users(sketch):
    """The features built on the sketch, straight or through its Selected Contours."""
    out = []
    for user in sketch.InList:
        if getattr(getattr(user, "Proxy", None), "Type", "") == "SWStyle::SelectedContours":
            out += [u for u in user.InList if u.TypeId in PROFILE_FEATURES]
            continue
        prof = getattr(user, "Profile", None)
        if user.TypeId in PROFILE_FEATURES and prof is not None and (prof[0] if isinstance(prof, tuple) else prof) is sketch:
            out.append(user)
    return out


def _contour_face(sketch, sub):
    """The closed contour the picked sketch edge is on, as a face in the sketch's place, or None."""
    import Part
    try:
        from . import contours
        wire = contours.contour_of(sketch, sub)
    except Exception:
        wire = None
    if wire is None:
        return None
    try:
        face = Part.Face(wire)
    except Exception:
        return None
    face.Placement = sketch.Placement.multiply(face.Placement)
    return face


def sketch_for(obj, sub):
    ""



    if obj is None or obj.TypeId != "Sketcher::SketchObject" or not (sub == "" or sub.startswith("Edge")):
        return None
    body = _body_of(obj)
    if body is None:
        return None
    if _sketch_users(obj):
        face = _contour_face(obj, sub) if sub else None
        if face is None:
            return None
        _CONTOUR[obj.Name] = "C:" + sub
        return (obj, body, face)
    _CONTOUR.pop(obj.Name, None)
    face = _profile_face(obj)
    return (obj, body, face) if face is not None else None


_CONTOUR = {}           # sketch name -> the contour pick the Instant3D arrow of a used sketch makes


def _solid_sides(body, face, normal):
    """(solid on the + side, solid on the - side) of the profile: what the part had before."""
    tip = body.Tip
    solid = tip.Shape if tip is not None and hasattr(tip, "Shape") else None
    if solid is None or solid.isNull() or not solid.Solids:
        return False, False
    pts = []
    try:
        u0, u1, v0, v1 = face.Faces[0].ParameterRange
        surf = face.Faces[0].Surface
        for i in range(1, 6):
            for j in range(1, 6):
                p = surf.value(u0 + (u1 - u0) * i / 6.0, v0 + (v1 - v0) * j / 6.0)
                if face.isInside(p, 1e-6, True):
                    pts.append(p)
    except Exception as _fw_err:
        _fw_log("instant3d.py:436", _fw_err)
    if not pts:
        pts = [_centre(face)]
    eps = 0.05
    plus = sum(1 for p in pts if solid.isInside(p + normal * eps, 1e-6, False))
    minus = sum(1 for p in pts if solid.isInside(p - normal * eps, 1e-6, False))
    return plus * 2 > len(pts), minus * 2 > len(pts)


def _body_of(obj):
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None


def _ray_param(view, pos, base, direction):
    """Where the view ray under the pointer passes closest to the line base + t*direction: t."""
    q = view.getPoint(int(pos[0]), int(pos[1]))
    r = App.Vector(view.getViewDirection())
    if view.getCameraType() != "Orthographic":
        cam = _camera_position(view)
        if cam is not None:
            r = q - cam
    r.normalize()
    w = base - q
    a, b, c = direction.dot(direction), direction.dot(r), r.dot(r)
    d, e = direction.dot(w), r.dot(w)
    den = a * c - b * b
    if abs(den) < 1e-12:
        return None              # looking straight down the arrow
    return (b * e - c * d) / den


def _camera_position(view):
    try:
        from pivy import coin  # noqa: F401  (loads the SWIG wrapper for getCameraNode)
        return App.Vector(*view.getCameraNode().position.getValue().getValue())
    except Exception:
        return None


def _viewport():
    """The active 3D view's viewport widget (Gui::View3DInventorViewer's)."""
    mw = Gui.getMainWindow()
    mdi = mw.findChild(QtWidgets.QMdiArea) if mw is not None else None
    sub = mdi.activeSubWindow() if mdi is not None else None
    view = sub.widget() if sub is not None else None
    if view is None:
        return None
    for w in view.findChildren(QtWidgets.QWidget):
        if w.metaObject().className() == "Gui::View3DInventorViewer" and hasattr(w, "viewport"):
            return w.viewport()
    return None


DRAG_EVENTS = (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease, QtCore.QEvent.ShortcutOverride, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseMove,)


class _Filter(QtCore.QObject):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        try:
            eaten = bool(self.owner.on_event(event))
        except Exception as error:
            App.Console.PrintLog("Instant3D: %s\n" % error)
            return False
        if event.type() in _QUIET_ON and handle_busy():
            _quiet_tip()
        return eaten



_QUIET_ON = (QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonPress)


def handle_busy():
    """An arrow or handle is hovered or being dragged."""
    for owner in list(_ALL):
        try:
            if getattr(owner, "drag", None) is not None or getattr(owner, "hover", False):
                return True
        except Exception:
            continue
    return False


def _quiet_tip():
    try:
        from . import edgetip
        if edgetip._tip is not None:
            edgetip._tip.hide()
    except Exception as error:
        App.Console.PrintLog("Instant3D tip: %s\n" % error)


def _seg_dist(p, a, b):
    ax, ay = b[0] - a[0], b[1] - a[1]
    px, py = p[0] - a[0], p[1] - a[1]
    ll = ax * ax + ay * ay
    t = 0.0 if ll == 0 else max(0.0, min(1.0, (px * ax + py * ay) / ll))
    dx, dy = px - t * ax, py - t * ay
    return math.hypot(dx, dy)


_ALL = weakref.WeakSet()       # every arrow owner (face arrow, Extrude page arrows, sketch dims)


def on_any_handle(event):
    """The press is on an arrow or handle one of the owners has drawn (not a document object)."""
    for owner in list(_ALL):
        try:
            if owner.widget is not None and owner.over_arrow(owner.coin_pos(event)):
                return True
        except Exception:
            continue
    return False


class _Instant3D:
    """The arrow on the picked face, and the drag."""

    def __init__(self):
        self.timer = None
        self.sep = None            # Coin root of the arrow
        self.parts = None          # (transform, material, text, shaft scale)
        self.view = None
        self.widget = None         # viewport watched for the mouse
        self.swallow = False       # Escape ended the drag with the button still down
        self.filter = None
        self.target = None         # (feature, prop, world base, world dir, factor, body placement)
        self.key = None
        self.drag = None           # {"t0", "v0", "doc", "pending"}
        self.hover = False
        self.length = 0.0          # arrow length in mm at the current zoom
        self.recompute_timer = None
        self.sketch = None         # {"body", "face", "normal"} when the arrow is on a sketch
        self.rotary = None         # {"centre", "axis", "arm", "sign"} on a revolve's end face
        _ALL.add(self)

    # ---------------------------------------------------------------- watching the selection
    def start(self):
        if self.timer is None:
            self.timer = QtCore.QTimer()
            self.timer.setInterval(150)
            self.timer.timeout.connect(self.poll)
        self.timer.start()

    def stop(self):
        if self.timer is not None:
            self.timer.stop()
        self.cancel()
        self.clear()

    def _picked(self):
        sel = Gui.Selection.getSelectionEx("", 0)
        if len(sel) != 1 or len(sel[0].SubElementNames) > 1:
            return None
        s = sel[0]
        obj, sub = s.Object, (s.SubElementNames[0] if s.SubElementNames else "")
        # a full path from the document (Body.Pad.Face6) resolves to the deepest object
        if "." in sub:
            parts = sub.split(".")
            doc = obj.Document
            for name in parts[:-1]:
                child = doc.getObject(name)
                if child is not None:
                    obj = child
            sub = parts[-1]
        return obj, sub

    def poll(self):
        if self.drag is not None:
            return
        if not enabled() or Gui.ActiveDocument is None:
            self.clear()
            return
        from .sketchextras import sketch_in_edit
        try:
            in_edit = Gui.ActiveDocument.getInEdit() is not None
        except Exception:
            in_edit = sketch_in_edit() is not None
        if not in_edit and _page_open():
            in_edit = True      # a PropertyManager is open (Shell, Fillet...): its picks, not Instant3D's arrow
        picked = None if in_edit else self._picked()
        if picked is not None and not picked[1]:
            face = tree_face(picked[0])
            if face is not None:
                picked = (picked[0], face)
        view = Gui.ActiveDocument.ActiveView
        if picked is None or not hasattr(view, "getPoint"):
            self.clear()
            return
        found = feature_for_face(*picked)
        sketch = sketch_for(*picked) if found is None else None
        if found is None and sketch is None:
            self.clear()
            return
        if sketch is not None:
            feat, body, face = sketch
            prop, factor = None, 1.0
            out = feat.Placement.Rotation.multVec(App.Vector(0, 0, 1))
            gpl = body.getGlobalPlacement()
            base = gpl.multVec(_centre(face))
            value = 0.0
        else:
            feat, face, (prop, out, factor) = found
            body = _body_of(feat)
            gpl = body.getGlobalPlacement() if body is not None else App.Placement()
            base = gpl.multVec(_centre(face))
            value = getattr(feat, prop).Value
        direction = gpl.Rotation.multVec(out)
        length = self._arrow_mm(view, base)
        key = (feat.Name, prop, tuple(round(x, 6) for x in base), tuple(round(x, 6) for x in direction),
               round(length, 4), value, id(view))
        if key == self.key:
            return
        self.clear()
        self.target = (feat, prop, base, direction, factor)
        self.sketch = None if sketch is None else {"body": body, "face": face, "normal": out,
                                                   "pick": _CONTOUR.get(feat.Name)}
        self.rotary = _rotary(feat, prop, gpl, base, direction) if sketch is None else None
        self.length = length
        self.key = key
        self._draw(view)

    def _arrow_mm(self, view, base):
        """mm that make ARROW_PX on screen at the face."""
        try:
            s = view.getPointOnScreen(base)
            a = view.getPoint(int(s[0]), int(s[1]))
            b = view.getPoint(int(s[0]) + 100, int(s[1]))
            return max((b - a).Length / 100.0 * ARROW_PX, 1e-6)
        except Exception:
            return 10.0

    # ---------------------------------------------------------------- the arrow
    def _draw(self, view):
        from pivy import coin
        feat, prop, base, direction, factor = self.target
        root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
        light = coin.SoLightModel()
        light.model.setValue(coin.SoLightModel.BASE_COLOR)
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*COLOR)
        xf = coin.SoTransform()
        root.addChild(pick)
        root.addChild(light)
        root.addChild(mat)
        root.addChild(xf)
        L = self.length
        shaft = coin.SoSeparator()
        st = coin.SoTranslation()
        st.translation.setValue(0, L * 0.36, 0)
        cyl = coin.SoCylinder()
        cyl.radius.setValue(L * 0.035)
        cyl.height.setValue(L * 0.72)
        shaft.addChild(st)
        shaft.addChild(cyl)
        head = coin.SoSeparator()
        ht = coin.SoTranslation()
        ht.translation.setValue(0, L * 0.86, 0)
        cone = coin.SoCone()
        cone.bottomRadius.setValue(L * 0.1)
        cone.height.setValue(L * 0.28)
        head.addChild(ht)
        head.addChild(cone)
        root.addChild(shaft)
        root.addChild(head)
        # the depth, next to the arrow head while dragging
        label = coin.SoSeparator()
        lt = coin.SoTranslation()
        lt.translation.setValue(L * 0.12, L * 1.05, 0)
        font = coin.SoFont()
        font.size.setValue(14)
        tmat = coin.SoMaterial()
        tmat.diffuseColor.setValue(0.05, 0.05, 0.05)
        text = coin.SoText2()
        label.addChild(lt)
        label.addChild(font)
        label.addChild(tmat)
        label.addChild(text)
        root.addChild(label)
        self._place(xf, base, direction)
        view.getSceneGraph().addChild(root)
        self.sep, self.view = root, view
        self.parts = (xf, mat, text)
        self._hook(view)

    def _place(self, xf, base, direction):
        from pivy import coin
        xf.translation.setValue(base.x, base.y, base.z)
        rot = App.Rotation(App.Vector(0, 1, 0), direction)
        q = rot.Q
        xf.rotation.setValue(coin.SbRotation(q[0], q[1], q[2], q[3]))

    def clear(self):
        if self.sep is not None and self.view is not None:
            try:
                self.view.getSceneGraph().removeChild(self.sep)
            except Exception as _fw_err:
                _fw_log("instant3d.py:711", _fw_err)
        self._unhook()
        self.sep, self.parts, self.target, self.key = None, None, None, None
        self.sketch = None
        self.hover = False

    def tip_on_screen(self):
        """(base, tip) of the arrow in screen pixels, from the view's own projection."""
        feat, prop, base, direction, factor = self.target
        offset = self.drag["shift"] if self.drag else 0.0
        b = base + direction * offset
        t = b + direction * self.length
        return self.view.getPointOnScreen(b), self.view.getPointOnScreen(t)

    def over_arrow(self, pos):
        if self.target is None or self.view is None:
            return False
        try:
            a, b = self.tip_on_screen()
        except Exception:
            return False
        return _seg_dist(pos, a, b) <= HIT_PX

    def _set_hover(self, on):
        if self.parts is None or on == self.hover:
            return
        self.hover = on
        self.parts[1].diffuseColor.setValue(*(HOVER if on else COLOR))

    # ---------------------------------------------------------------- the pointer
    # A Qt filter on the view's viewport sees the mouse before FreeCAD: a press on the arrow
    # never reaches the selection or the navigation style, so the picked face stays picked.
    def _hook(self, view):
        widget = _viewport()
        if widget is None or widget is self.widget:
            return
        self._unhook()
        if self.filter is None:
            self.filter = _Filter(self)
        widget.installEventFilter(self.filter)
        widget.setMouseTracking(True)
        # keys (Escape) go to the viewer itself, not its viewport
        if widget.parentWidget() is not None:
            widget.parentWidget().installEventFilter(self.filter)
        self.widget = widget

    def _unhook(self):
        if self.widget is not None:
            try:
                self.widget.removeEventFilter(self.filter)
                if self.widget.parentWidget() is not None:
                    self.widget.parentWidget().removeEventFilter(self.filter)
            except Exception as _fw_err:
                _fw_log("instant3d.py:764", _fw_err)
        self.widget = None

    def coin_pos(self, event):
        """The pointer -> the viewport pixels Coin and getPointOnScreen use. Taken from the
        screen position, as during a drag the event may be for another widget."""
        g = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
        qpos = self.widget.mapFromGlobal(g)
        ratio = self.widget.devicePixelRatioF()
        return qpos.x() * ratio, (self.widget.height() - qpos.y()) * ratio

    def on_event(self, event):
        t = event.type()
        QE = QtCore.QEvent
        if t == QE.ShortcutOverride and self.drag is not None:
            event.accept()           # no shortcut (Escape leaves sketches...) while dragging
            return True
        if t == QE.KeyPress:
            if self.drag is None:
                return False
            if event.key() == QtCore.Qt.Key_Escape:
                self.cancel()
            elif event.key() == QtCore.Qt.Key_M and self.sketch is not None and not event.isAutoRepeat():
                self.toggle_mid()
            return True
        if not hasattr(event, "button"):
            return False
        if t == QE.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            if self.swallow:
                self.swallow = False
                self._show_value_clear()
            pos = self.coin_pos(event)
            if self.drag is None and self.over_arrow(pos):
                return self.press(pos)
        elif t == QE.MouseMove:
            pos = self.coin_pos(event)
            if self.drag is not None:
                self.move(pos)
                return True
            self._set_hover(self.over_arrow(pos))
        elif t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton and self.drag is not None:
            self.release()
            return True
        elif t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton and self.swallow:
            # the button coming up after Escape: FreeCAD never saw the press, so not this either
            self.swallow = False
            self._show_value_clear()
            return True
        elif t == QE.MouseButtonDblClick and self.drag is not None:
            return True
        return False

    # ---------------------------------------------------------------- the drag
    def press(self, pos):
        feat, prop, base, direction, factor = self.target
        t0 = _ray_param(self.view, pos, base, direction)
        if t0 is None:
            return False
        doc = feat.Document
        doc.openTransaction("Instant3D" if self.sketch is None else "Instant3D Extrude")
        try:
            v0 = getattr(feat, prop).Value if self.sketch is None else 0.0
            self.drag = {"t0": t0, "v0": v0, "doc": doc, "shift": 0.0, "value": None,
                         "snapped": False, "made": None, "mid": False}
            if self.sketch is not None:
                sk = self.sketch
                self.drag["sides"] = _solid_sides(sk["body"], sk["face"], sk["normal"])
                self.drag["shown"] = feat.Visibility
            self._ruler_start()
            # ahead of every other filter while dragging, so Escape comes here first
            events.register("instant3d-%d" % id(self), DRAG_EVENTS, self.filter.eventFilter)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        self._set_hover(True)
        self._show_value(self.drag["v0"])
        return True

    def value_at(self, pos):
        if getattr(self, "rotary", None) is not None:
            return self._angle_at(pos)
        feat, prop, base, direction, factor = self.target
        r = self.drag.get("ruler")
        if r is not None and self._on_ruler(pos):
            t = _ray_param(self.view, pos, r["zero"], direction)
            if t is not None:
                self.drag["snapped"] = True
                return max(r["tick"], round(t * factor / r["tick"]) * r["tick"])
        g = self._geometry_snap(pos)
        if g is not None:
            self.drag["snapped"] = "geometry"
            if self.sketch is None:
                g = max(MIN_DEPTH, g)
                if prop == "Angle":
                    g = min(g, 360.0)
            return round(g, 6)
        self.drag["snapped"] = False
        t = _ray_param(self.view, pos, base, direction)
        if t is None:
            return None
        v = self.drag["v0"] + (t - self.drag["t0"]) * factor
        if self.sketch is not None:
            return round(v / STEP) * STEP     # either way off the sketch
        v = max(MIN_DEPTH, round(v / STEP) * STEP)
        if prop == "Angle":
            v = min(round(v, 1), 360.0)       # a revolve turns at most once round
        return v

    def _geometry_snap(self, pos):
        ""

        if self.view is None or not hasattr(self.view, "getObjectInfo"):
            return None
        feat, prop, base, direction, factor = self.target
        if prop == "Angle":
            return None                      # a turn has no straight depth to reach
        try:
            info = self.view.getObjectInfo((int(pos[0]), int(pos[1])))
        except Exception:
            info = None
        if not info or not info.get("Component"):
            return None
        comp = info["Component"]
        point = App.Vector(info["x"], info["y"], info["z"])
        # a PropertyManager handle (Shell thickness, pmhandles) moves a field, not a feature
        doc = feat.Document if feat is not None else App.ActiveDocument
        if doc is None:
            return None
        obj = doc.getObject(info.get("Object", ""))
        if comp.startswith("Vertex") and obj is not None:
            try:
                parent = obj.getGlobalPlacement().multiply(obj.Placement.inverse())
                point = parent.multVec(obj.Shape.getElement(comp).Point)
            except Exception as _fw_err:
                _fw_log("instant3d.py:894", _fw_err)
        elif comp.startswith("Face"):
            try:
                face = obj.Shape.getElement(comp)
                fp = _plane_of(face)
            except Exception:
                fp = None
            if fp is None or abs(abs(fp[1].dot(direction)) - 1) > 1e-6:
                return None
            point = obj.getGlobalPlacement().multiply(obj.Placement.inverse()).multVec(fp[0])
        elif not comp.startswith("Edge"):
            return None
        v = self.drag["v0"] + (point - base).dot(direction) * factor
        now = self.drag.get("value")
        if now is None:
            now = self.drag["v0"]
        if abs(v - now) < 1e-6:
            return None                      # the moving face itself
        own = obj is not None and feat is not None and (obj is feat or obj is _body_of(feat))
        if own and abs(v - self.drag["v0"]) < 1e-6:
            # the moving face where the drag began (the view has not caught up, or the pointer passes back
            # over it): no snap, or the depth jumped back to where it was (features-442: a drag up over the
            # top face of a Pad in an isometric view stayed at its old depth)
            return None
        self.drag["snap_to"] = (info.get("Object"), comp)
        return v

    # ---------------------------------------------------------------- a revolve's turn
    def _turn_point(self, v, radius=None):
        """World point at angle v (degrees from the sketch plane) round the revolve's axis, at the
        end face's distance from the axis (or radius)."""
        ro = self.rotary
        arm = ro["zero"] * (ro["arm"].Length if radius is None else radius)
        return ro["centre"] + App.Rotation(ro["axis"], ro["sign"] * v).multVec(arm)

    def _pointer_angle(self, pos):
        """The pointer's angle round the axis (degrees from the sketch plane, continuous through
        360 from the last one), on the plane through the end face square to the axis."""
        ro = self.rotary
        try:
            ray_from = App.Vector(self.view.getPoint(int(pos[0]), int(pos[1])))
            look = App.Vector(self.view.getViewDirection())
        except Exception:
            return None
        denom = look.dot(ro["axis"])
        if abs(denom) < 0.05:
            return None                      # looking along the plane: no turn to read
        t = (ro["centre"] - ray_from).dot(ro["axis"]) / denom
        hit = ray_from + look * t
        r = hit - ro["centre"]
        r = r - ro["axis"] * r.dot(ro["axis"])
        if r.Length < 1e-9:
            return None
        x = r.dot(ro["zero"])
        y = r.dot(ro["axis"].cross(ro["zero"]) * ro["sign"])
        a = math.degrees(math.atan2(y, x)) % 360.0
        last = self.drag.get("value")
        last = self.drag["v0"] if last is None else last
        # the turn closest to the last value (no jump at 0 / 360)
        a += 360.0 * round((last - a) / 360.0)
        return a

    def _angle_at(self, pos):
        a = self._pointer_angle(pos)
        if a is None:
            return None
        r = self.drag.get("ruler")
        if r is not None and self._on_ruler(pos):
            self.drag["snapped"] = True
            a = round(a / r["tick"]) * r["tick"]
        else:
            self.drag["snapped"] = False
            a = round(a, 1)
        return min(max(a, 0.1), 360.0)        # a revolve turns at most once round

    def _rotary_ruler_start(self):
        mm_px = self.length / ARROW_PX
        radius = self.rotary["arm"].Length + RULER_GAP_PX * mm_px
        # degrees between marks: at least TICK_MIN_PX apart on screen at the ruler's radius
        tick = nice_step(math.degrees(TICK_MIN_PX * mm_px / max(radius, 1e-6)))
        tick = min(max(tick, 1.0), 10.0)
        major = 10.0 if tick < 5 else 30.0
        self.drag["ruler"] = {"zero": None, "side": None, "tick": tick, "major": major, "mm_px": mm_px,
                              "end": 360.0, "node": None, "radius": radius}
        self._rotary_ruler_draw()

    def _rotary_ruler_draw(self):
        ""

        from pivy import coin
        r = self.drag.get("ruler")
        if r is None or self.sep is None or r["node"] is not None:
            return
        node = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*RULER_COLOR)
        node.addChild(mat)
        rad = r["radius"]
        arc = [self._turn_point(k, rad) for k in range(0, 361, 2)]
        pts, counts = list(arc), [len(arc)]
        labels = []
        n = int(round(360.0 / r["tick"]))
        for k in range(n):
            v = k * r["tick"]
            major = abs(v / r["major"] - round(v / r["major"])) < 1e-6
            p = self._turn_point(v, rad)
            q = self._turn_point(v, rad + r["mm_px"] * (10 if major else 5))
            pts += [p, q]
            counts.append(2)
            if major:
                labels.append((v, self._turn_point(v, rad + r["mm_px"] * 22)))
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(pts), [(q.x, q.y, q.z) for q in pts])
        lines = coin.SoLineSet()
        lines.numVertices.setValues(0, len(counts), counts)
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(1.5)
        node.addChild(style)
        node.addChild(coords)
        node.addChild(lines)
        font = coin.SoFont()
        font.size.setValue(11)
        node.addChild(font)
        for v, q in labels:
            lab = coin.SoSeparator()
            tr = coin.SoTranslation()
            tr.translation.setValue(q.x, q.y, q.z)
            txt = coin.SoText2()
            txt.justification.setValue(coin.SoText2.CENTER)
            txt.string.setValue("%g°" % round(v, 6))
            lab.addChild(tr)
            lab.addChild(txt)
            node.addChild(lab)
        self.sep.insertChild(node, 3)
        r["node"] = node

    def _on_rotary_ruler(self, pos):
        r = self.drag.get("ruler")
        try:
            pts = [self.view.getPointOnScreen(self._turn_point(k, r["radius"])) for k in range(0, 361, 5)]
        except Exception:
            return False
        return any(_seg_dist(pos, a, b) <= RULER_SNAP_PX for a, b in zip(pts, pts[1:]))

    # ---------------------------------------------------------------- the ruler
    def _ruler_start(self):
        """Ruler from zero depth along the arrow, set off to the side the screen shows best."""
        if getattr(self, "rotary", None) is not None:
            self._rotary_ruler_start()
            return
        feat, prop, base, direction, factor = self.target
        try:
            look = App.Vector(self.view.getViewDirection())
        except Exception:
            return
        side = direction.cross(look)
        if side.Length < 0.2:
            return                       # looking (nearly) along the arrow: no room for a ruler
        side.normalize()
        # on the screen's left of the arrow, so its numbers stay clear of the depth by the arrow head
        try:
            if self.view.getPointOnScreen(base + side)[0] > self.view.getPointOnScreen(base)[0]:
                side = side * -1
        except Exception as _fw_err:
            _fw_log("instant3d.py:1052", _fw_err)
        mm_px = self.length / ARROW_PX
        v0 = self.drag["v0"]
        zero = base - direction * (v0 / factor) + side * (RULER_GAP_PX * mm_px)
        tick = nice_step(TICK_MIN_PX * mm_px * factor)
        # labelled marks at the next power of ten (1 -> 10, 2 -> 10, 5 -> 10)
        major = 10 ** (math.floor(math.log10(tick) + 1e-9) + 1)
        self.drag["ruler"] = {"zero": zero, "side": side, "tick": tick, "major": float(major),
                              "mm_px": mm_px, "end": 0.0, "node": None}
        self._ruler_draw(max(v0, 0.0))

    def ruler_point(self, v):
        """World point on the ruler at depth value v."""
        r = self.drag["ruler"]
        return r["zero"] + self.target[3] * (v / self.target[4])

    def _on_ruler(self, pos):
        r = self.drag.get("ruler")
        if r is None:
            return False
        if getattr(self, "rotary", None) is not None:
            return self._on_rotary_ruler(pos)
        try:
            a = self.view.getPointOnScreen(self.ruler_point(0.0))
            b = self.view.getPointOnScreen(self.ruler_point(r["end"]))
        except Exception:
            return False
        return _seg_dist(pos, a, b) <= RULER_SNAP_PX

    def _ruler_draw(self, value):
        """(Re)build the ruler so it reaches well past value."""
        from pivy import coin
        r = self.drag.get("ruler")
        if r is None or self.sep is None:
            return
        if getattr(self, "rotary", None) is not None:
            self._rotary_ruler_draw()
            return
        reach = value + 3 * ARROW_PX * r["mm_px"] * self.target[4]
        if r["node"] is not None and r["end"] >= reach - 1e-9:
            return
        end = math.ceil(reach / r["major"]) * r["major"]
        if r["node"] is not None:
            self.sep.removeChild(r["node"])
        node = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*RULER_COLOR)
        node.addChild(mat)
        pts, counts = [self.ruler_point(0.0), self.ruler_point(end)], [2]
        n = int(round(end / r["tick"]))
        labels = []
        for k in range(n + 1):
            v = k * r["tick"]
            major = abs(v / r["major"] - round(v / r["major"])) < 1e-6
            p = self.ruler_point(v)
            pts += [p, p + r["side"] * (r["mm_px"] * (10 if major else 5))]
            counts.append(2)
            if major:
                labels.append((v, p + r["side"] * (r["mm_px"] * 13)))
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(pts), [(q.x, q.y, q.z) for q in pts])
        lines = coin.SoLineSet()
        lines.numVertices.setValues(0, len(counts), counts)
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(1.5)
        node.addChild(style)
        node.addChild(coords)
        node.addChild(lines)
        font = coin.SoFont()
        font.size.setValue(11)
        node.addChild(font)
        for v, q in labels:
            lab = coin.SoSeparator()
            tr = coin.SoTranslation()
            tr.translation.setValue(q.x, q.y, q.z)
            txt = coin.SoText2()
            txt.justification.setValue(coin.SoText2.RIGHT)   # ends at the mark, away from the ruler
            txt.string.setValue("%g" % round(v, 6))
            lab.addChild(tr)
            lab.addChild(txt)
            node.addChild(lab)
        # before the arrow's transform, so the ruler is in world coordinates
        self.sep.insertChild(node, 3)
        r["node"], r["end"] = node, end

    def _ruler_clear(self):
        r = self.drag.get("ruler") if self.drag else None
        if r is not None and r["node"] is not None and self.sep is not None:
            try:
                self.sep.removeChild(r["node"])
            except Exception as _fw_err:
                _fw_log("instant3d.py:1143", _fw_err)

    def move(self, pos):
        if self.drag is None:
            return
        v = self.value_at(pos)
        if v is None:
            return
        feat, prop, base, direction, factor = self.target
        self.drag["value"] = v
        self.drag["shift"] = (v - self.drag["v0"]) / factor
        if getattr(self, "rotary", None) is not None:
            turn = App.Rotation(self.rotary["axis"], self.rotary["sign"] * (v - self.drag["v0"]))
            self._place(self.parts[0], self.rotary["centre"] + turn.multVec(base - self.rotary["centre"]),
                        turn.multVec(direction))
        else:
            self._place(self.parts[0], base + direction * self.drag["shift"], direction)
        self._ruler_draw(v)
        self._show_value(v)
        # the model follows, at most every 80 ms so a heavy part keeps up with the pointer
        if self.recompute_timer is None:
            self.recompute_timer = QtCore.QTimer()
            self.recompute_timer.setSingleShot(True)
            self.recompute_timer.setInterval(80)
            self.recompute_timer.timeout.connect(self._apply)
        if not self.recompute_timer.isActive():
            self.recompute_timer.start()

    def _apply(self):
        if self.drag is None or self.drag["value"] is None:
            return
        if self.sketch is not None:
            self._apply_extrude()
            return
        feat, prop = self.target[0], self.target[1]
        if abs(getattr(feat, prop).Value - self.drag["value"]) > 1e-9:
            setattr(feat, prop, self.drag["value"])
            feat.Document.recompute()

    # ---------------------------------------------------------------- a new extrude from a sketch
    def extrude_kind(self, v):
        """('Pad' or 'Pocket', Reversed) for a drag to signed depth v: into the part cuts, away
        from it adds."""
        plus, minus = self.drag["sides"]
        into = plus if v > 0 else minus
        if into:
            return "Pocket", v > 0          # a Pocket goes against the sketch normal unless reversed
        return "Pad", v < 0

    def _apply_extrude(self):
        v = self.drag["value"]
        sketch = self.target[0]
        body = self.sketch["body"]
        doc = sketch.Document
        made = self.drag["made"]
        if abs(v) < MIN_DEPTH:
            if made is not None:
                body.removeObject(made)
                doc.removeObject(made.Name)
                self.drag["made"] = None
                doc.recompute()
            return
        kind, rev = self.extrude_kind(v)
        if made is not None and made.TypeId != "PartDesign::" + kind:
            body.removeObject(made)
            doc.removeObject(made.Name)
            made = None
        if made is None:
            made = body.newObject("PartDesign::" + kind, kind)
            made.Profile = sketch
            pick = self.sketch.get("pick")
            if pick:
                from . import contours
                contours.set_picks(made, [pick])        # a shared sketch: from the picked contour only
            if App.GuiUp:
                sketch.ViewObject.Visibility = False
            self.drag["made"] = made
        made.Reversed = rev
        made.SideType = "Symmetric" if self.drag["mid"] else "One side"
        made.Length = abs(v) * (2 if self.drag["mid"] else 1)
        doc.recompute()

    def toggle_mid(self):
        ""
        if self.drag is None or self.sketch is None:
            return
        self.drag["mid"] = not self.drag["mid"]
        if self.drag["value"] is not None:
            self._apply_extrude()

    def _show_value(self, v):
        if self.parts is None:
            return
        unit = App.Units.Angle if self.target is not None and self.target[1] == "Angle" else App.Units.Length
        self.parts[2].string.setValue(App.Units.Quantity(v, unit).UserString)

    def release(self):
        if self.drag is None:
            return
        if self.recompute_timer is not None:
            self.recompute_timer.stop()
        self._apply()
        doc = self.drag["doc"]
        self._ruler_clear()
        changed = self.drag["value"] is not None and abs(self.drag["value"] - self.drag["v0"]) > 1e-9
        if self.sketch is not None:
            made = self.drag["made"]
            changed = made is not None and made.isValid()
            if made is not None and not changed:
                App.Console.PrintWarning("Instant3D: %s\n" % made.getStatusString())
        if changed:
            doc.commitTransaction()
        else:
            doc.abortTransaction()
        self.drag = None
        self.key = None
        self._show_value_clear()

    def cancel(self):
        if self.drag is None:
            return
        if self.recompute_timer is not None:
            self.recompute_timer.stop()
        feat, prop = self.target[0], self.target[1]
        if self.sketch is None:
            setattr(feat, prop, self.drag["v0"])
        self._ruler_clear()
        doc = self.drag["doc"]
        doc.abortTransaction()           # takes a new extrude away again too
        if self.sketch is not None and self.drag.get("shown") and App.GuiUp:
            feat.ViewObject.Visibility = True
        doc.recompute()
        self.drag = None
        self.key = None
        # a drag only lives while the button is down: its release still has to come
        self.swallow = True
        if self.parts is not None:
            self.parts[2].string.setValue("")

    def _show_value_clear(self):
        events.unregister("instant3d-%d" % id(self))
        if self.parts is not None:
            self.parts[2].string.setValue("")


GEO_UNDEF = -2000
LENGTH_TYPES = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter")


def dimension_handles(sketch):
    """The sketch's driving length dimensions as handles: [(constraint index, name, point,
    direction, factor, signed)] in sketch coordinates. Dragging the point along direction makes
    the value grow by factor per mm; signed values (DistanceX/Y) may go below zero."""
    out = []
    geos = sketch.Geometry

    def pt(geo, pos):
        try:
            return App.Vector(sketch.getPoint(geo, pos))
        except Exception:
            return None

    def is_line(g):
        return 0 <= g < len(geos) and geos[g].__class__.__name__ == "LineSegment"

    for i, c in enumerate(sketch.Constraints):
        if c.Type not in LENGTH_TYPES or not c.Driving:
            continue
        handle = None
        if c.Type in ("Radius", "Diameter"):
            g = geos[c.First] if 0 <= c.First < len(geos) else None
            if g is None or not hasattr(g, "Radius"):
                continue
            centre = App.Vector(g.Center)
            if hasattr(g, "FirstParameter") and g.__class__.__name__ in ("ArcOfCircle",):
                ang = 0.5 * (g.FirstParameter + g.LastParameter)
            else:
                ang = math.pi / 4
            d = App.Vector(math.cos(ang), math.sin(ang), 0)
            handle = (centre + d * g.Radius, d, 2.0 if c.Type == "Diameter" else 1.0, False)
        elif c.Second == GEO_UNDEF and is_line(c.First):
            # a line's own length (or its width / height)
            a, b = pt(c.First, 1), pt(c.First, 2)
            if a is None or b is None:
                continue
            if c.Type == "Distance":
                d = b - a
                if d.Length < 1e-9:
                    continue
                d.normalize()
                handle = (b, d, 1.0, False)
            else:
                d = App.Vector(1, 0, 0) if c.Type == "DistanceX" else App.Vector(0, 1, 0)
                handle = (b, d, 1.0, True)
        elif c.Second != GEO_UNDEF:
            a = pt(c.First, c.FirstPos) if c.FirstPos else None
            if c.SecondPos == 0 and is_line(c.Second) and a is not None and c.Type == "Distance":
                # point to line: the point moves square off the line
                l0, l1 = pt(c.Second, 1), pt(c.Second, 2)
                u = l1 - l0
                u.normalize()
                foot = l0 + u * (a - l0).dot(u)
                d = a - foot
                if d.Length < 1e-9:
                    continue
                d.normalize()
                handle = (a, d, 1.0, False)
            else:
                b = pt(c.Second, c.SecondPos) if c.SecondPos else None
                if a is None or b is None:
                    continue
                if c.Type == "Distance":
                    d = b - a
                    if d.Length < 1e-9:
                        continue
                    d.normalize()
                    handle = (b, d, 1.0, False)
                else:
                    d = App.Vector(1, 0, 0) if c.Type == "DistanceX" else App.Vector(0, 1, 0)
                    handle = (b, d, 1.0, True)
        if handle is not None:
            out.append((i, c.Name or "", handle[0], handle[1], handle[2], handle[3]))
    return out


def _line_pts(sketch, g):
    """(start, end) of a sketch line, or of the H / V axis (-1 / -2), in sketch coordinates."""
    if g == -1:
        return App.Vector(0, 0, 0), App.Vector(1, 0, 0)
    if g == -2:
        return App.Vector(0, 0, 0), App.Vector(0, 1, 0)
    geos = sketch.Geometry
    if 0 <= g < len(geos) and geos[g].__class__.__name__ == "LineSegment":
        return App.Vector(geos[g].StartPoint), App.Vector(geos[g].EndPoint)
    return None


def _angle_geom(sketch, c):
    """A driving angle between two lines (or a line and the horizontal): {"pivot" (the corner),
    "point" (the handle, on the line that turns), "tangent", "rel" (degrees from the other line
    to the turning one)} in sketch coordinates, or None."""
    if c.Type != "Angle" or not c.Driving or getattr(c, "Third", GEO_UNDEF) != GEO_UNDEF:
        return None
    if c.Second == GEO_UNDEF:
        mine, other = _line_pts(sketch, c.First), _line_pts(sketch, -1)
        if mine is None:
            return None              # an arc's own span: no corner to turn round
        pivot = mine[0]
    else:
        l1, l2 = _line_pts(sketch, c.First), _line_pts(sketch, c.Second)
        if l1 is None or l2 is None:
            return None
        mine, other = (l1, l2) if c.Second < 0 else (l2, l1)     # the axis never turns
        d1, d2 = other[1] - other[0], mine[1] - mine[0]
        den = d1.x * d2.y - d1.y * d2.x
        if abs(den) < 1e-9 * max(d1.Length * d2.Length, 1e-12):
            return None              # parallel lines: no corner
        w = mine[0] - other[0]
        pivot = other[0] + d1 * ((w.x * d2.y - w.y * d2.x) / den)
    dm, do = mine[1] - mine[0], other[1] - other[0]
    if dm.Length < 1e-9 or do.Length < 1e-9:
        return None
    mid = (mine[0] + mine[1]) * 0.5
    if (mid - pivot).Length >= 0.25 * dm.Length:
        point = mid
    else:
        point = max(mine, key=lambda q: (q - pivot).Length)
    arm = point - pivot
    if arm.Length < 1e-9:
        return None
    tangent = App.Vector(-arm.y, arm.x, 0)
    tangent.normalize()
    rel = math.degrees(math.atan2(do.x * dm.y - do.y * dm.x, do.x * dm.x + do.y * dm.y))
    return {"pivot": App.Vector(pivot.x, pivot.y, 0), "point": App.Vector(point.x, point.y, 0),
            "tangent": tangent, "rel": rel}


def angle_handles(sketch):
    """The sketch's driving angle dimensions as handles: [(constraint index, name, point, tangent,
    pivot)] in sketch coordinates."""
    out = []
    for i, c in enumerate(sketch.Constraints):
        if c.Type != "Angle":
            continue
        try:
            g = _angle_geom(sketch, c)
        except Exception:
            g = None
        if g is not None:
            out.append((i, c.Name or "", g["point"], g["tangent"], g["pivot"]))
    return out


def sketch_of(obj):
    """The sketch whose dimensions to show for a picked sketch or sketch-based feature."""
    if obj is None:
        return None
    if obj.TypeId == "Sketcher::SketchObject":
        return obj
    prof = getattr(obj, "Profile", None)
    prof = prof[0] if isinstance(prof, tuple) else prof
    if prof is not None and getattr(prof, "TypeId", "") == "Sketcher::SketchObject":
        return prof
    return None


class _ValueEdit(QtWidgets.QLineEdit):
    """The box a clicked dimension is typed into; Escape closes it unchanged."""
    cancelled = QtCore.Signal()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class _SketchDims(_Instant3D):
    """Blue handles on a picked sketch's dimensions; drag one or click it to type."""

    def __init__(self):
        super().__init__()
        self.sketch_obj = None
        self.handles = []          # [(index, name, world point, world dir, factor, signed)]
        self.nodes = []            # per handle: (transform, material, text)
        self.active = None         # index into handles under the pointer / being dragged
        self.editor = None
        self.press_pos = None

    def poll(self):
        if self.drag is not None or self.editor is not None:
            return
        if not enabled() or Gui.ActiveDocument is None:
            self.clear()
            return
        try:
            in_edit = Gui.ActiveDocument.getInEdit() is not None
        except Exception:
            in_edit = False
        if not in_edit and _page_open():
            in_edit = True      # a PropertyManager is open: no sketch handles over its picks
        picked = None if in_edit else self._picked()
        sketch = sketch_of(picked[0]) if picked is not None and picked[1] == "" else None
        view = Gui.ActiveDocument.ActiveView
        if sketch is None or not hasattr(view, "getPoint"):
            self.clear()
            return
        handles = self._world_handles(sketch, view)
        cons = sketch.Constraints if handles else []      # once: each .Constraints builds the whole list (fix152)
        key = (sketch.Name, id(view), tuple((h[0], tuple(round(x, 6) for x in h[2])) for h in handles),
               tuple(round(cons[h[0]].Value, 9) for h in handles))
        if key == self.key:
            return
        self.clear()
        if not handles:
            return
        self.sketch_obj, self.handles, self.key, self.view = sketch, handles, key, view
        self.length = self._arrow_mm(view, handles[0][2])
        self._draw(view)

    def _world_handles(self, sketch, view=None):
        gpl = sketch.getGlobalPlacement()
        view = view or self.view
        out = []
        cells = {}      # 1e-5 grid of the handle points: "same point" without a scan of all (fix152)
        for i, name, p, d, factor, signed in dimension_handles(sketch):
            w = gpl.Rotation.multVec(d)
            w.normalize()
            q = gpl.multVec(p)
            # two dimensions on one point (a centre placed by X and Y): set the later ones a
            # little way along their own direction so each can be seen and grabbed
            cx, cy, cz = int(math.floor(q.x * 1e5)), int(math.floor(q.y * 1e5)), int(math.floor(q.z * 1e5))
            same = sum(1 for ax in (cx - 1, cx, cx + 1) for ay in (cy - 1, cy, cy + 1) for az in (cz - 1, cz, cz + 1)
                       for p0 in cells.get((ax, ay, az), ()) if (p0 - q).Length < 1e-6)
            cells.setdefault((cx, cy, cz), []).append(q)
            if same and view is not None:
                q_shown = q + w * (same * 30 * self._arrow_mm(view, q) / ARROW_PX)
            else:
                q_shown = q
            out.append((i, name, q_shown, w, factor, signed, q))
        # angle dimensions: factor holds the corner the handle turns round
        for i, name, p, d, pivot in angle_handles(sketch):
            w = gpl.Rotation.multVec(d)
            w.normalize()
            q = gpl.multVec(p)
            out.append((i, name, q, w, gpl.multVec(pivot), "angle", q))
        return out

    def _is_angle(self, index):
        return self.sketch_obj.Constraints[index].Type == "Angle"

    def _value(self, index):
        """The dimension's value as dragged and typed: mm, or degrees for an angle."""
        v = self.sketch_obj.Constraints[index].Value
        return math.degrees(v) if self._is_angle(index) else v

    def _quantity(self, index, v):
        return App.Units.Quantity(v, App.Units.Angle if self._is_angle(index) else App.Units.Length)

    def _draw(self, view):
        from pivy import coin
        root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
        light = coin.SoLightModel()
        light.model.setValue(coin.SoLightModel.BASE_COLOR)
        spacer = coin.SoSeparator()      # keeps the ruler's insert position (3) ahead of the handles
        root.addChild(pick)
        root.addChild(light)
        root.addChild(spacer)
        self.nodes = []
        for h in self.handles:
            sep = coin.SoSeparator()
            mat = coin.SoMaterial()
            mat.diffuseColor.setValue(*COLOR)
            xf = coin.SoTranslation()
            xf.translation.setValue(h[2].x, h[2].y, h[2].z)
            ball = coin.SoSphere()
            ball.radius.setValue(self.length * 0.07)
            label = coin.SoSeparator()
            lt = coin.SoTranslation()
            lt.translation.setValue(self.length * 0.12, self.length * 0.12, 0)
            font = coin.SoFont()
            font.size.setValue(13)
            text = coin.SoText2()
            text.string.setValue(self._label(h))
            label.addChild(lt)
            label.addChild(font)
            label.addChild(text)
            sep.addChild(mat)
            sep.addChild(xf)
            sep.addChild(ball)
            sep.addChild(label)
            root.addChild(sep)
            self.nodes.append((xf, mat, text))
        view.getSceneGraph().addChild(root)
        self.sep = root
        self._hook(view)

    def _label(self, h):
        c = self.sketch_obj.Constraints[h[0]]
        v = c.Value
        if c.Type == "Angle":
            return App.Units.Quantity(math.degrees(v), App.Units.Angle).UserString
        prefix = "R" if c.Type == "Radius" else ("\u00d8" if c.Type == "Diameter" else "")
        return prefix + App.Units.Quantity(v, App.Units.Length).UserString

    def clear(self):
        super().clear()
        self.rotary = None         # an angle handle's turn, set again on each press
        self.sketch_obj, self.handles, self.nodes, self.active = None, [], [], None

    def _hit(self, pos):
        best, best_d = None, HIT_PX + 1
        for k, h in enumerate(self.handles):
            try:
                s = self.view.getPointOnScreen(h[2])
            except Exception:
                continue
            d = math.hypot(s[0] - pos[0], s[1] - pos[1])
            if d < best_d:
                best, best_d = k, d
        return best

    def over_arrow(self, pos):
        if not self.handles or self.view is None:
            return False
        k = self._hit(pos)
        if self.drag is None:
            self._hover_handle(k)
        return k is not None

    def _hover_handle(self, k):
        if k == self.active:
            return
        for j, n in enumerate(self.nodes):
            n[1].diffuseColor.setValue(*(HOVER if j == k else COLOR))
        self.active = k

    def _set_hover(self, on):
        self.hover = on

    def press(self, pos):
        k = self._hit(pos)
        if k is None:
            return False
        h = self.handles[k]
        self.active = k
        self.rotary = None
        if h[5] == "angle":
            return self._press_angle(h, pos)
        self.target = (self.sketch_obj, h[0], h[2], h[3], h[4])
        t0 = _ray_param(self.view, pos, h[2], h[3])
        if t0 is None:
            return False
        doc = self.sketch_obj.Document
        doc.openTransaction("Instant3D")
        try:
            v0 = self.sketch_obj.Constraints[h[0]].Value
            self.drag = {"t0": t0, "v0": v0, "doc": doc, "shift": 0.0, "value": None, "snapped": False,
                         "good": v0, "moved": False, "pos": pos}
            events.register("instant3d-%d" % id(self), DRAG_EVENTS, self.filter.eventFilter)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        if v0 > 0:
            self._ruler_start()
        return True

    def _press_angle(self, h, pos):
        ""
        sk, index = self.sketch_obj, h[0]
        gpl = sk.getGlobalPlacement()
        axis = gpl.Rotation.multVec(App.Vector(0, 0, 1))
        axis.normalize()
        centre, arm = h[4], h[6] - h[4]
        if arm.Length < 1e-9:
            return False
        doc = sk.Document
        doc.openTransaction("Instant3D")
        try:
            v0 = self._value(index)
            # which way the line turns for more angle: try one degree more and put it back
            sign = 1.0
            try:
                r0 = _angle_geom(sk, sk.Constraints[index])["rel"]
                sk.setDatum(index, App.Units.Quantity(v0 + 1.0, App.Units.Angle))
                doc.recompute()
                g1 = _angle_geom(sk, sk.Constraints[index])
                if g1 is not None:
                    d = (g1["rel"] - r0 + 180.0) % 360.0 - 180.0
                    sign = 1.0 if d >= 0 else -1.0
            except Exception as _fw_err:
                _fw_log("instant3d.py:angle-probe", _fw_err)
            sk.setDatum(index, App.Units.Quantity(v0, App.Units.Angle))
            doc.recompute()
            zero = App.Rotation(axis, -sign * v0).multVec(arm)
            zero.normalize()
            self.rotary = {"centre": centre, "axis": axis, "arm": arm, "zero": zero, "sign": sign}
            self.target = (sk, index, h[2], h[3], 1.0)
            self.drag = {"t0": 0.0, "v0": v0, "doc": doc, "shift": 0.0, "value": None, "snapped": False,
                         "good": v0, "moved": False, "pos": pos, "angle": True}
            events.register("instant3d-%d" % id(self), DRAG_EVENTS, self.filter.eventFilter)
        except BaseException:
            self.rotary = None
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        self._ruler_start()
        return True

    def value_at(self, pos):
        if self.drag.get("angle"):
            a = self._pointer_angle(pos)
            if a is None:
                return None
            r = self.drag.get("ruler")
            if r is not None and self._on_ruler(pos):
                self.drag["snapped"] = True
                a = round(a / r["tick"]) * r["tick"]
            else:
                self.drag["snapped"] = False
                a = round(a, 1)
            return min(max(a, 0.1), 359.9)      # never through zero: the lines would fold over
        if self.drag.get("ruler") is not None and self._on_ruler(pos):
            return super().value_at(pos)
        self.drag["snapped"] = False
        sketch, index, base, direction, factor = self.target
        t = _ray_param(self.view, pos, base, direction)
        if t is None:
            return None
        v0 = self.drag["v0"]
        v = round((v0 + (t - self.drag["t0"]) * factor) / STEP) * STEP
        # never through zero: the solver would flip the geometry over
        return max(v, MIN_DEPTH) if v0 > 0 else min(v, -MIN_DEPTH)

    def move(self, pos):
        if self.drag is None:
            return
        p0 = self.drag["pos"]
        if not self.drag["moved"] and math.hypot(pos[0] - p0[0], pos[1] - p0[1]) < 3:
            return
        self.drag["moved"] = True
        v = self.value_at(pos)
        if v is None:
            return
        self.drag["value"] = v
        self._ruler_draw(abs(v))
        self.nodes[self.active][2].string.setValue(self._quantity(self.target[1], v).UserString)
        if self.recompute_timer is None:
            self.recompute_timer = QtCore.QTimer()
            self.recompute_timer.setSingleShot(True)
            self.recompute_timer.setInterval(80)
            self.recompute_timer.timeout.connect(self._apply)
        if not self.recompute_timer.isActive():
            self.recompute_timer.start()

    def set_value(self, index, v):
        """Set the dimension and solve; a value the sketch can't take is put back. True if kept."""
        sk = self.sketch_obj
        old = self._value(index)
        try:
            sk.setDatum(index, self._quantity(index, v))
            sk.Document.recompute()
            ok = sk.isValid() and (not hasattr(sk, "solve") or sk.solve() == 0)
        except Exception:
            ok = False
        if not ok:
            try:
                sk.setDatum(index, self._quantity(index, old))
                sk.Document.recompute()
            except Exception as _fw_err:
                _fw_log("instant3d.py:1604", _fw_err)
        return ok

    def _apply(self):
        if self.drag is None or self.drag["value"] is None:
            return
        index = self.target[1]
        if abs(self._value(index) - self.drag["value"]) < 1e-9:
            return
        if self.set_value(index, self.drag["value"]):
            self.drag["good"] = self.drag["value"]
        self._follow()

    def _follow(self):
        """Handles to where the solved geometry is now."""
        handles = self._world_handles(self.sketch_obj)
        if len(handles) != len(self.handles):
            return
        self.handles = handles
        for h, n in zip(handles, self.nodes):
            n[0].translation.setValue(h[2].x, h[2].y, h[2].z)
            if self.drag is None or h[0] != self.target[1]:
                n[2].string.setValue(self._label(h))

    def release(self):
        if self.drag is None:
            return
        if not self.drag["moved"]:
            # a click: type the value instead
            doc = self.drag["doc"]
            doc.abortTransaction()
            pos = self.drag["pos"]
            self.drag = None
            self._show_value_clear()
            self.open_editor(self.active, pos)
            return
        if self.recompute_timer is not None:
            self.recompute_timer.stop()
        self._apply()
        self._ruler_clear()
        doc = self.drag["doc"]
        changed = abs(self._value(self.target[1]) - self.drag["v0"]) > 1e-9
        if changed:
            doc.commitTransaction()
        else:
            doc.abortTransaction()
        self.drag = None
        self.key = None
        self._show_value_clear()

    def cancel(self):
        if self.drag is None:
            return
        if self.recompute_timer is not None:
            self.recompute_timer.stop()
        self._ruler_clear()
        doc = self.drag["doc"]
        doc.abortTransaction()
        doc.recompute()
        self.drag = None
        self.key = None
        self.swallow = True

    def _show_value_clear(self):
        events.unregister("instant3d-%d" % id(self))

    # ---------------------------------------------------------------- click to type
    def open_editor(self, k, pos):
        if k is None or self.widget is None:
            return
        h = self.handles[k]
        index = h[0]
        edit = _ValueEdit(self.widget)
        edit.setText(self._quantity(index, self._value(index)).UserString)
        edit.selectAll()
        ratio = self.widget.devicePixelRatioF()
        edit.move(int(pos[0] / ratio) + 8, int(self.widget.height() - pos[1] / ratio) - 10)
        edit.setFixedWidth(110)
        edit.show()
        edit.setFocus()
        self.editor = edit

        def done():
            if self.editor is not edit:
                return
            self.editor = None
            text = edit.text()
            edit.deleteLater()
            self.type_value(index, text)

        edit.cancelled.connect(lambda: self.close_editor(edit))
        edit.returnPressed.connect(done)
        edit.editingFinished.connect(lambda: self.close_editor(edit))

    def close_editor(self, edit=None):
        edit = edit or self.editor
        if edit is not None and self.editor is edit:
            self.editor = None
            edit.deleteLater()
            self.key = None

    def type_value(self, index, text):
        """A typed value (with or without units) for the dimension: one undo step."""
        try:
            q = App.Units.Quantity(text)
            unit = "deg" if self._is_angle(index) else "mm"
            if q.Unit == App.Units.Unit():
                v = float(q.Value)           # a bare number: the dimension's own unit
            else:
                v = q.getValueAs(unit).Value
        except Exception:
            return False
        doc = self.sketch_obj.Document
        doc.openTransaction("Instant3D")
        ok = self.set_value(index, v)
        if ok:
            doc.commitTransaction()
        else:
            doc.abortTransaction()
        self.key = None
        return ok


INSTANT = _Instant3D()
DIMS = _SketchDims()


def toggle():
    on = not enabled()
    paths.params().SetBool(PARAM, on)
    for part in (INSTANT, DIMS):
        if on:
            part.start()
        else:
            part.stop()


class _Cmd:
    def GetResources(self):
        return {"MenuText": "Instant3D",
                "ToolTip": "Drag the arrow on a picked extrude face to change its depth on screen.",
                "Checkable": enabled()}

    def Activated(self, checked=None):
        # Gui.runCommand passes checked=0 whatever the state, so the setting decides
        toggle()

    def IsActive(self):
        return App.ActiveDocument is not None


_installed = False


def install():
    global _installed
    if _installed:
        return
    if Gui.Command.get("SWStyle_Instant3D") is None:
        Gui.addCommand("SWStyle_Instant3D", _Cmd())
    checkstate.register("SWStyle_Instant3D", enabled)
    if enabled():
        INSTANT.start()
        DIMS.start()
    try:
        from . import featuredrag
        featuredrag.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: feature drag not installed: %s\n" % error)
    for name in ("drawholecallpm", "drawballoonpm", "pmnogrey", "toolfirst", "pmlength", "pickprio"):
        try:

            # pmnogrey: a greyed control on any open page is hidden until it can be used (no dead controls);
            # toolfirst: a CommandManager button that cannot run yet opens its page and asks for its pick

            # pickprio: a click picks the highlighted sketch entity or edge before the plane it lies on
            import importlib
            importlib.import_module("." + name, __package__).install()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: %s not installed: %s\n" % (name, error))
    _installed = True
