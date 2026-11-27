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

import FreeCAD as App
import FreeCADGui as Gui
import Part

from . import naming, smflatten

COMMAND = "SWStyle_SMGusset"
TITLE = "Sheet Metal Gusset"
GROUP = "Gusset"
ICON = "SheetMetal_AddRelief"
V = App.Vector
MESSAGE = "Select the faces on either side of a bend for the gusset."
ROUNDED, FLAT = "Rounded", "Flat"


# ================================================================ geometry
def _plane(face):
    """A flat face's point and normal, out of the material; None if the face is not flat."""
    if face is None or face.Surface.TypeId != "Part::GeomPlane":
        return None
    pts = face.tessellate(0.5)[0]
    p = pts[0] if pts else face.Vertexes[0].Point
    n = face.normalAt(*face.Surface.parameter(p))
    return p, n


def _thickness(shape, p, n):
    """The sheet's thickness at point p of a face with outward normal n."""
    line = Part.makeLine(p + n * 1e-3, p - n * 1000)
    common = shape.common(line)
    for e in common.Edges:
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if min((a - p).Length, (b - p).Length) < 1e-2:
            return e.Length
    return min((e.Length for e in common.Edges), default=0.0)


def _meet(p1, n1, p2, n2):
    """A point on the line where two planes meet."""
    a = n1.cross(n2)
    d1, d2 = n1.dot(p1), n2.dot(p2)
    # point = (d1 (n2 x a) + d2 (a x n1)) / |a|^2
    return (n2.cross(a) * d1 + a.cross(n1) * d2) * (1.0 / a.dot(a))


def _line2(p, d, q, e):
    """Where the lines p + s d and q + t e meet (they lie in one plane)."""
    w = q - p
    c = d.cross(e)
    s = w.cross(e).dot(c) / c.dot(c)
    return p + d * s


def _bend_radius(shape, axis, sharp):
    """The inside radius of the bend at the sharp line (0 when there is no bend face)."""
    best = None
    for f in shape.Faces:
        s = f.Surface
        if s.TypeId != "Part::GeomCylinder" or abs(abs(s.Axis.dot(axis)) - 1) > 1e-6:
            continue
        off = s.Center - sharp
        off = off - axis * off.dot(axis)
        if off.Length < 3 * s.Radius + 1e-6 and (best is None or s.Radius < best):
            best = s.Radius
    return best or 0.0


class Bend:
    """The bend between two supporting faces: its line and the walls either side, at the inside."""

    def __init__(self, shape, f1, f2):
        p1, n1 = _plane(f1)
        p2, n2 = _plane(f2)
        axis = n1.cross(n2)
        if axis.Length < 1e-6:
            raise ValueError("The supporting faces must meet at a bend.")
        axis.normalize()
        sharp = _meet(p1, n1, p2, n2)
        u1 = f1.CenterOfMass - sharp
        u1 = (u1 - axis * u1.dot(axis) - n1 * u1.dot(n1)).normalize()
        u2 = f2.CenterOfMass - sharp
        u2 = (u2 - axis * u2.dot(axis) - n2 * u2.dot(n2)).normalize()
        # the inside faces are those facing the other wall
        t1, t2 = _thickness(shape, p1, n1), _thickness(shape, p2, n2)
        if n1.dot(u2) < 0:
            p1, n1 = p1 - n1 * t1, -n1
        if n2.dot(u1) < 0:
            p2, n2 = p2 - n2 * t2, -n2
        sharp = _meet(p1, n1, p2, n2)
        self.axis, self.sharp, self.u1, self.u2, self.n1, self.n2 = axis, sharp, u1, u2, n1, n2
        self.thickness = max(t1, t2)
        self.radius = _bend_radius(shape, axis, sharp)
        cos = max(-1.0, min(1.0, u1.dot(u2)))
        self.angle = math.acos(cos)         # between the walls, inside
        # the bend's span along its line: where both faces reach
        spans = []
        for f in (f1, f2):
            ts = [(v.Point - sharp).dot(axis) for v in f.Vertexes]
            spans.append((min(ts), max(ts)))
        self.start = max(spans[0][0], spans[1][0])
        self.end = min(spans[0][1], spans[1][1])

    def mid(self):
        return self.sharp + self.axis * ((self.start + self.end) / 2)


def profile_points(bend, at, mode, d, d1, d2, a1, use_angle, flip):
    """The gusset's triangle at point at on the bend line: inner sharp, and its ends on wall 1 and wall 2."""
    vtx = bend.sharp + bend.axis * (at - bend.sharp).dot(bend.axis)
    u1, u2 = (bend.u2, bend.u1) if flip else (bend.u1, bend.u2)
    b = (u1 + u2).normalize()
    half = bend.angle / 2
    if mode == "depth":
        if d <= 0:
            raise ValueError("The indent depth must be more than 0.")
        reach = bend.radius / math.sin(half) - bend.radius + d     # from the sharp along the bisector
        s = reach / u1.dot(b)
        p1, p2 = vtx + u1 * s, vtx + u2 * s
    else:
        if d1 <= 0:
            raise ValueError("The profile dimensions must be more than 0.")
        p1 = vtx + u1 * d1
        if use_angle:
            if not 0 < a1 < math.degrees(math.pi - bend.angle):
                raise ValueError("The gusset angle does not meet the other flange.")
            n = (u2 - u1 * u2.dot(u1)).normalize()
            r = math.radians(a1)
            w = -u1 * math.cos(r) + n * math.sin(r)
            p2 = _line2(p1, w, vtx, u2)
        else:
            if d2 <= 0:
                raise ValueError("The profile dimensions must be more than 0.")
            p2 = vtx + u2 * d2
    # the face must clear the inside of the bend
    if bend.radius > 0:
        centre = vtx + b * (bend.radius / math.sin(half))
        h = p2 - p1
        off = centre - p1
        dist = (off - h * (off.dot(h) / h.dot(h))).Length
        side = (off - h * (off.dot(h) / h.dot(h))).dot(b)
        if side > 0 or dist < bend.radius + 1e-6:
            raise ValueError("The gusset does not clear the bend: make it bigger.")
    return vtx, p1, p2


def _halfspace(point, normal, size):
    """The solid on the back side of the plane through point with normal (a big box)."""
    box = Part.makeBox(2 * size, 2 * size, size, V(-size, -size, -size))
    box.Placement = App.Placement(point, App.Rotation(V(0, 0, 1), normal))
    return box


def _prism(points, axis, width, centre):
    w = Part.makePolygon(points + points[:1])
    face = Part.Face(w)
    shift = axis * ((centre - points[0]).dot(axis) - width / 2)
    face.translate(shift)
    return face.extrude(axis * width)


def _top_edges(solid, normal, point):
    """The edges of the solid's face on the plane (point, normal) that run across the gusset, along it."""
    out = []
    for e in solid.Edges:
        if e.Curve.TypeId != "Part::GeomLine":
            continue
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if abs((a - point).dot(normal)) < 1e-6 and abs((b - point).dot(normal)) < 1e-6:
            out.append(e)
    return out


def _rib(tri, axis, top_normal, top_point, width, draft, fillet, rounded, size):
    """The solid of the rib (or of its hollow) over the triangle tri, width wide on its top face."""
    centre = top_point
    if rounded or draft <= 0:
        solid = _prism(tri, axis, width, centre)
    else:
        big = _prism(tri, axis, width + 4 * size * math.tan(math.radians(draft)) + 2, centre)
        t = math.tan(math.radians(draft))
        for sgn in (1, -1):
            n = (axis * sgn + top_normal * t).normalize()
            big = big.common(_halfspace(centre + axis * (sgn * width / 2), n, size * 4))
        solid = big
    if rounded:
        r = width / 2 * 0.98
    else:
        r = fillet
    if r > 1e-4:
        edges = [e for e in _top_edges(solid, top_normal, top_point)
                 if abs(abs((e.Vertexes[-1].Point - e.Vertexes[0].Point).normalize().dot(axis)) - 1) > 1e-6]
        if edges:
            solid = solid.makeFillet(r, edges)
    return solid


def gusset(shape, bend, at, mode="depth", d=10.0, d1=10.0, d2=10.0, a1=45.0, use_angle=False, flip=False,
           width=5.08, thickness=None, kind=ROUNDED, draft=5.0, inner=1.016, outer=1.016, full=True):
    """shape with a pressed gusset across bend, centred at point at."""
    t = bend.thickness if thickness is None else thickness
    if width <= 0 or t <= 0:
        raise ValueError("The indent width and thickness must be more than 0.")
    if 2 * t >= width:
        raise ValueError("The indent width must be more than twice the indent thickness.")
    vtx, p1, p2 = profile_points(bend, at, mode, d, d1, d2, a1, use_angle, flip)
    h = p2 - p1
    top = (bend.axis.cross(h)).normalize()
    if (vtx - p1).dot(top) > 0:
        top = -top                                      # the rib's face looks away from the sharp
    size = max((p1 - vtx).Length, (p2 - vtx).Length, width) * 4 + bend.thickness * 4
    rounded = kind == ROUNDED
    draft = 0.0 if (rounded or not full) else draft
    rib = _rib([vtx, p1, p2], bend.axis, top, p1 + bend.axis * (at - p1).dot(bend.axis), width, draft,
               0.0 if not full else outer, rounded, size)
    # the hollow, from the outside of the sheet up to t under the rib's face
    m = bend.thickness + 1.0
    u1, u2 = (bend.u2, bend.u1) if flip else (bend.u1, bend.u2)
    n1, n2 = (bend.n2, bend.n1) if flip else (bend.n1, bend.n2)
    o1p, o2p = vtx - n1 * m, vtx - n2 * m
    q1, q2 = p1 - top * t, p2 - top * t
    corner = _line2(o1p, u1, o2p, u2)
    c1 = _line2(o1p, u1, q1, h)
    c2 = _line2(o2p, u2, q2, h)
    hollow = _rib([corner, c1, c2], bend.axis, top, q1 + bend.axis * (at - q1).dot(bend.axis), width - 2 * t,
                  draft, max(0.0, outer - t) if full else 0.0, rounded, size)
    out = shape.fuse(rib).cut(hollow).removeSplitter()
    if full and not rounded and inner > 1e-4:
        try:
            out = _inner_fillet(out, shape, rib, inner)
        except Exception:
            raise ValueError("The inner corner fillet is too big.")
    solids = out.Solids
    if len(solids) != 1:
        raise ValueError("The gusset does not fit the part here.")
    return solids[0], (vtx, p1, p2)


def _on(shape_faces, p):
    v = Part.Vertex(p)
    return any(f.distToShape(v)[0] < 1e-6 for f in shape_faces)


def _inner_fillet(out, shape, rib, r):
    """Rounds the valley edges where the rib's sides meet the sheet."""
    edges = []
    for e in out.Edges:
        mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
        if _on(rib.Faces, mid) and _on(shape.Faces, mid) and _concave(out, e, mid):
            edges.append(e)
    if not edges:
        return out
    return out.makeFillet(r, edges)


def _concave(solid, edge, mid):
    """True when the solid's two faces at the edge meet in a valley."""
    faces = [f for f in solid.Faces if f.distToShape(Part.Vertex(mid))[0] < 1e-6]
    if len(faces) != 2:
        return False
    n0, n1 = [f.normalAt(*f.Surface.parameter(mid)) for f in faces]
    if (n0 - n1).Length < 1e-6:
        return False
    return solid.isInside(mid + (n0 - n1).normalize() * 1e-3, 1e-7, False)


def zone(bend, at, tri, width, kind, draft, inner):
    """A solid holding everything the gusset changes (to take it out again for the flat pattern)."""
    vtx, p1, p2 = tri
    h = p2 - p1
    top = bend.axis.cross(h).normalize()
    if (vtx - p1).dot(top) > 0:
        top = -top
    m = bend.thickness + 1.0
    u1, u2 = (p1 - vtx).normalize(), (p2 - vtx).normalize()
    n1 = next(n for n in (bend.n1, bend.n2) if abs(n.dot(u1)) < 1e-6)
    n2 = next(n for n in (bend.n1, bend.n2) if abs(n.dot(u2)) < 1e-6 and n is not n1)
    o1, o2 = vtx - n1 * m, vtx - n2 * m
    q1, q2 = p1 + top * 0.5, p2 + top * 0.5
    corner = _line2(o1, u1, o2, u2)
    c1, c2 = _line2(o1, u1, q1, h), _line2(o2, u2, q2, h)
    depth = max((p1 - vtx).Length, (p2 - vtx).Length) + m
    grow = 0.0 if kind == ROUNDED else depth * math.tan(math.radians(draft))
    return _prism([corner, c1, c2], bend.axis, width + 2 * grow + 2 * inner + 2.0, at)


# ================================================================ feature
_LAST = None        # the open Gusset PropertyManager


def face_at(shape, p, normal=None):
    """The face of shape through point p (facing along normal when given), else None."""
    vp = Part.Vertex(p)
    best = None
    for i, f in enumerate(shape.Faces):
        if normal is not None and f.Surface.TypeId == "Part::GeomPlane" and \
                abs(abs(f.normalAt(0, 0).dot(normal)) - 1) > 1e-7:
            continue
        dist = f.distToShape(vp)[0]
        if dist < 1e-4 and (best is None or dist < best[0]):
            best = (dist, i)
    return best[1] if best else None


TOGGLES = (("UseDraft", "Use the side face draft"), ("UseInnerFillet", "Use the inner corner fillet"),
           ("UseOuterFillet", "Use the outer corner fillet"))


def _toggles(obj):
    """The on/off toggles of the flat gusset's draft and fillets (on for a gusset made before them)."""
    for name, tip in TOGGLES:
        if not hasattr(obj, name):
            obj.addProperty("App::PropertyBool", name, GROUP, tip)
            setattr(obj, name, True)


def _used(obj):
    """The draft and fillets the gusset is built with: 0 for each one toggled off."""
    on = [bool(getattr(obj, n, True)) for n, _t in TOGGLES]
    return (float(obj.DraftAngle) if on[0] else 0.0, float(obj.InnerFillet) if on[1] else 0.0,
            float(obj.OuterFillet) if on[2] else 0.0)


class SWGusset:
    def __init__(self, obj):
        self.editing = False
        add = obj.addProperty
        add("App::PropertyStringList", "Faces", GROUP, "The supporting faces, as picked")
        add("App::PropertyVectorList", "FacePoints", GROUP, "A point on each supporting face")
        add("App::PropertyVectorList", "FaceNormals", GROUP, "Each supporting face's normal")
        add("App::PropertyString", "Line", GROUP, "Reference line (the bend when empty)")
        add("App::PropertyVector", "LineStart", GROUP, "Reference line start")
        add("App::PropertyVector", "LineEnd", GROUP, "Reference line end")
        add("App::PropertyString", "Point", GROUP, "Reference point (the middle of the line when empty)")
        add("App::PropertyVector", "PointAt", GROUP, "Reference point position")
        add("App::PropertyBool", "UseOffset", GROUP, "Offset the gusset from the reference point")
        add("App::PropertyLength", "Offset", GROUP, "Offset along the reference line")
        add("App::PropertyBool", "OffsetReverse", GROUP, "Offset the other way along the line")
        add("App::PropertyEnumeration", "ProfileType", GROUP, "Indent depth or Profile dimensions")
        obj.ProfileType = ["Indent depth", "Profile dimensions"]
        add("App::PropertyLength", "IndentDepth", GROUP, "How far the gusset's face stands off the bend")
        add("App::PropertyLength", "D1", GROUP, "Length along the first flange")
        add("App::PropertyLength", "D2", GROUP, "Length along the second flange")
        add("App::PropertyAngle", "A1", GROUP, "Angle from the first flange")
        add("App::PropertyBool", "UseAngle", GROUP, "d1 and the angle instead of d1 and d2")
        add("App::PropertyBool", "FlipSides", GROUP, "Flip dimension sides")
        add("App::PropertyEnumeration", "GussetType", GROUP, "Rounded or flat gusset")
        obj.GussetType = [ROUNDED, FLAT]
        add("App::PropertyLength", "IndentWidth", GROUP, "Indent width")
        add("App::PropertyLength", "IndentThickness", GROUP, "Indent thickness")
        add("App::PropertyAngle", "DraftAngle", GROUP, "Side face draft (flat gusset)")
        add("App::PropertyLength", "InnerFillet", GROUP, "Inner corner fillet (flat gusset)")
        add("App::PropertyLength", "OuterFillet", GROUP, "Outer corner fillet (flat gusset)")
        _toggles(obj)
        add("App::PropertyEnumeration", "Preview", GROUP, "Preview while editing")
        obj.Preview = ["Partial", "Full"]
        add("App::PropertyBool", "OverrideFlat", GROUP, "Override document settings in the flat pattern")
        add("App::PropertyBool", "ShowProfile", GROUP, "Show the gusset's profile in the flat pattern")
        add("App::PropertyBool", "ShowCenter", GROUP, "Show the gusset's center in the flat pattern")
        obj.UseOffset = True
        obj.Offset = 10.0
        obj.IndentDepth = 10.0
        obj.D1 = obj.D2 = 10.0
        obj.A1 = 45.0
        from .smbaseflange import inch_part
        inch = inch_part(obj.Document)                  # round inch sizes in an inch part, round mm otherwise
        obj.IndentWidth = 5.08 if inch else 5.0
        obj.IndentThickness = 1.016 if inch else 1.0
        obj.DraftAngle = 5.0
        obj.InnerFillet = obj.OuterFillet = 1.016 if inch else 1.0
        obj.Proxy = self

    # ---------------------------------------------------------------- geometry
    def bend(self, obj, shape):
        faces = []
        for p, n in zip(obj.FacePoints, obj.FaceNormals):
            i = face_at(shape, p, n)
            if i is None:
                raise ValueError("A supporting face of the gusset is no longer there.")
            faces.append(shape.Faces[i])
        if len(faces) != 2:
            raise ValueError(MESSAGE)
        return Bend(shape, faces[0], faces[1])

    def at(self, obj, bend):
        if obj.Line:
            start, end = V(obj.LineStart), V(obj.LineEnd)
        else:
            start, end = bend.sharp + bend.axis * bend.start, bend.sharp + bend.axis * bend.end
        direction = end - start
        if direction.Length < 1e-9:
            direction = V(bend.axis)
        direction.normalize()
        middle = (start + end) * 0.5
        point = V(obj.PointAt) if obj.Point else middle
        if (middle - point).dot(direction) < -1e-6:
            direction = -direction          # from a reference point the offset runs into the part
        if obj.UseOffset:
            point = point + direction * (float(obj.Offset) * (-1 if obj.OffsetReverse else 1))
        t = (point - bend.sharp).dot(bend.axis)
        if not bend.start - 1e-6 <= t <= bend.end + 1e-6:
            raise ValueError("The gusset is off the end of the bend: change the reference point or offset.")
        return point

    def build(self, obj, shape, full=True):
        bend = self.bend(obj, shape)
        at = self.at(obj, bend)
        out, tri = gusset(shape, bend, at, "depth" if obj.ProfileType == "Indent depth" else "dims",
                          float(obj.IndentDepth), float(obj.D1), float(obj.D2), float(obj.A1), bool(obj.UseAngle),
                          bool(obj.FlipSides), float(obj.IndentWidth), float(obj.IndentThickness), obj.GussetType,
                          *_used(obj), full)
        return out, bend, at, tri

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Sheet Metal Gusset: needs a sheet metal part")
        from .smnormalcut import baked
        shape = baked(base.Shape)
        if len(obj.Faces) < 2:
            obj.Shape = shape
            return
        full = not getattr(self, "editing", False) or obj.Preview == "Full"
        obj.Shape = self.build(obj, shape, full)[0]

    def onDocumentRestored(self, obj):
        self.editing = False
        _toggles(obj)

    def dumps(self):
        return None

    def loads(self, state):
        self.editing = False
        return None


def is_gusset(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWGusset"


def without_gussets(body, shape):
    ""

    from .smnormalcut import baked
    out = shape
    for o in body.Group:
        if not is_gusset(o) or o.BaseFeature is None or "Invalid" in o.State or len(o.Faces) < 2:
            continue
        try:
            base = baked(o.BaseFeature.Shape)
            bend = o.Proxy.bend(o, base)
            at = o.Proxy.at(o, bend)
            tri = profile_points(bend, at, "depth" if o.ProfileType == "Indent depth" else "dims",
                                 float(o.IndentDepth), float(o.D1), float(o.D2), float(o.A1), bool(o.UseAngle),
                                 bool(o.FlipSides))
            z = zone(bend, at, tri, float(o.IndentWidth), o.GussetType, *_used(o)[:2])
            out = out.cut(z).fuse(base.common(z)).removeSplitter()
        except Exception as _fw_err:
            _fw_log("smgusset.py:466", _fw_err)
    if len(out.Solids) == 1:
        out = out.Solids[0]
    return out


def shows(obj, what):
    """Whether the flat pattern shows the gusset's profile or centre (document setting: no)."""
    if not obj.OverrideFlat:
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/SWStyle")
        return p.GetBool("FlatGusset" + what, False)
    return bool(getattr(obj, "Show" + what))


def flat_lines(body, shape, fixed_point, kfactor):
    """The gussets' profiles and centres on the flat pattern, unfolded with the part's bends."""
    from . import smunfold
    from .smnormalcut import baked
    wanted = [o for o in body.Group if is_gusset(o) and o.BaseFeature is not None and "Invalid" not in o.State
              and len(o.Faces) >= 2 and (shows(o, "Profile") or shows(o, "Center"))]
    if not wanted:
        return []
    probes = [smunfold.probe(i, o) for i, o in smunfold.bends_of(shape)]
    _flat, steps = smunfold.unfold(shape, probes, fixed_point, kfactor)
    edges = []
    for o in wanted:
        base = baked(o.BaseFeature.Shape)
        bend = o.Proxy.bend(o, base)
        at = o.Proxy.at(o, bend)
        _vtx, p1, p2 = profile_points(bend, at, "depth" if o.ProfileType == "Indent depth" else "dims",
                                      float(o.IndentDepth), float(o.D1), float(o.D2), float(o.A1),
                                      bool(o.UseAngle), bool(o.FlipSides))
        half = bend.axis * (float(o.IndentWidth) / 2)
        f = [point_flat(steps, p) for p in (p1 - half, p2 - half, p2 + half, p1 + half, p1, p2)]
        if shows(o, "Profile"):
            edges += [Part.makeLine(f[k], f[(k + 1) % 4]) for k in range(4)]
        if shows(o, "Center"):
            edges.append(Part.makeLine(f[4], f[5]))
    return edges


def point_flat(steps, p):
    """A point of the folded part -> the flat pattern, through the unfold steps."""
    for step in steps:
        bend = step["bend"]
        if step["A"].isInside(p, 1e-4, True):
            continue
        if bend.in_sector(p):
            p = bend.to_flat(p)
            continue
        p = step["M"].multVec(p)
    return p


class ViewProviderGusset:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from .smunfold import _icon
        return _icon(ICON)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + obj.Label)
        try:
            Gui.Control.showDialog(Panel(obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(body):
    doc = body.Document
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", "Gusset")
    SWGusset(obj)
    if App.GuiUp:
        ViewProviderGusset(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, "Gusset")
    smflatten.gusset_lines(body)
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smgusset.py:567", _fw_err)
    return obj


# ================================================================ PropertyManager
def _supporting(shape, face):
    """The flat faces either side of a picked bend face (its inside or outside)."""
    out = []
    seams = [e for e in face.Edges if e.Curve.TypeId == "Part::GeomLine"]     # along the bend
    for f in shape.Faces:
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        if any(e.isSame(x) for e in f.Edges for x in seams):
            out.append(f)
    return out if len(out) == 2 else []


class Panel:
    """The Sheet Metal Gusset PropertyManager."""

    def __init__(self, obj, new):
        from PySide import QtWidgets
        from .smbaseflange import _box, _spin
        from .smedgeflange import error_label
        from .smunfold import _DeleteKey, _list
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        self.pick_error = ""
        self.busy = True
        obj.Proxy.editing = True

        position = _box("Position")
        f = position.layout()
        self.error = error_label()
        f.addRow(self.error)
        self.faces = _list("SWSMGussetFaces", "#d6ecff", "Supporting faces: the faces either side of the bend",
                           rows=2)
        f.addRow(self.faces)
        self.line = _list("SWSMGussetLine", "#ffd6ec", "Reference line (the bend when empty)")
        f.addRow(self.line)
        self.point = _list("SWSMGussetPoint", "#e6d6ff", "Reference point (the middle of the line when empty)")
        f.addRow(self.point)
        row = QtWidgets.QHBoxLayout()
        self.use_offset = QtWidgets.QCheckBox("Offset")
        self.use_offset.setObjectName("SWSMGussetUseOffset")
        self.use_offset.setChecked(bool(obj.UseOffset))
        row.addWidget(self.use_offset)
        self.offset_reverse = QtWidgets.QToolButton()
        self.offset_reverse.setObjectName("SWSMGussetOffsetReverse")
        self.offset_reverse.setCheckable(True)
        self.offset_reverse.setChecked(bool(obj.OffsetReverse))
        try:
            from . import pmvalues
            self.offset_reverse.setIcon(pmvalues.reverse_icon())
        except Exception:
            self.offset_reverse.setText("⇄")
        self.offset_reverse.setToolTip("Reverse direction")
        row.addWidget(self.offset_reverse)
        f.addRow(row)
        self.offset = _spin("SWSMGussetOffset", float(obj.Offset), 0.0, 10000.0, step=1.0)
        self.offset.setToolTip("Offset from the reference point along the reference line")
        f.addRow("Offset:", self.offset)

        prof = _box("Profile")
        f = prof.layout()
        self.depth_mode = QtWidgets.QRadioButton("Indent depth")
        self.depth_mode.setObjectName("SWSMGussetDepthMode")
        f.addRow(self.depth_mode)
        self.depth = _spin("SWSMGussetDepth", float(obj.IndentDepth), 0.0, 10000.0, step=1.0)
        self.depth.setToolTip("Indent depth: how far the gusset's face stands off the inside of the bend")
        f.addRow("d:", self.depth)
        self.dims_mode = QtWidgets.QRadioButton("Profile dimensions")
        self.dims_mode.setObjectName("SWSMGussetDimsMode")
        f.addRow(self.dims_mode)
        group = QtWidgets.QButtonGroup(prof)
        group.addButton(self.depth_mode)
        group.addButton(self.dims_mode)
        self.d1 = _spin("SWSMGussetD1", float(obj.D1), 0.0, 10000.0, step=1.0)
        self.d1.setToolTip("d1: length along the first flange")
        f.addRow("d1:", self.d1)
        self.d2_mode = QtWidgets.QRadioButton("d2:")
        self.d2_mode.setObjectName("SWSMGussetD2Mode")
        self.d2 = _spin("SWSMGussetD2", float(obj.D2), 0.0, 10000.0, step=1.0)
        self.d2.setToolTip("d2: length along the second flange")
        f.addRow(self.d2_mode, self.d2)
        self.a1_mode = QtWidgets.QRadioButton("a1:")
        self.a1_mode.setObjectName("SWSMGussetA1Mode")
        self.a1 = _spin("SWSMGussetA1", float(obj.A1), 0.0, 180.0, suffix=" deg", step=1.0)
        self.a1.setToolTip("a1: angle from the first flange")
        f.addRow(self.a1_mode, self.a1)
        group2 = QtWidgets.QButtonGroup(prof)
        group2.addButton(self.d2_mode)
        group2.addButton(self.a1_mode)
        self.flip = QtWidgets.QCheckBox("Flip dimension sides")
        self.flip.setObjectName("SWSMGussetFlip")
        self.flip.setChecked(bool(obj.FlipSides))
        f.addRow(self.flip)
        row = QtWidgets.QHBoxLayout()
        self.rounded = QtWidgets.QToolButton()
        self.rounded.setObjectName("SWSMGussetRounded")
        self.rounded.setCheckable(True)
        from . import pmpics
        pmpics.picture(self.rounded, "gusset", "Rounded gusset")
        self.rounded.setAutoRaise(True)
        self.flat = QtWidgets.QToolButton()
        self.flat.setObjectName("SWSMGussetFlat")
        self.flat.setCheckable(True)
        pmpics.picture(self.flat, "gusset", "Flat gusset")
        self.flat.setAutoRaise(True)
        group3 = QtWidgets.QButtonGroup(prof)
        for b in (self.rounded, self.flat):
            b.setCheckable(True)
            group3.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        f.addRow(row)

        dims = _box("Dimensions")
        f = dims.layout()
        self.width = _spin("SWSMGussetWidth", float(obj.IndentWidth), 0.0, 10000.0, step=0.1)
        self.width.setToolTip("Indent width")
        f.addRow("Indent width:", self.width)
        self.thick = _spin("SWSMGussetThickness", float(obj.IndentThickness), 0.0, 1000.0, step=0.1)
        self.thick.setToolTip("Indent thickness")
        f.addRow("Indent thickness:", self.thick)
        _toggles(obj)
        self.draft = _spin("SWSMGussetDraft", float(obj.DraftAngle), 0.0, 45.0, suffix=" deg", step=1.0)
        self.inner = _spin("SWSMGussetInner", float(obj.InnerFillet), 0.0, 1000.0, step=0.1)
        self.outer = _spin("SWSMGussetOuter", float(obj.OuterFillet), 0.0, 1000.0, step=0.1)
        self.toggles = []
        for spin, (prop, _tip), text in zip((self.draft, self.inner, self.outer), TOGGLES,
                                            ("Side face draft", "Inner corner fillet", "Outer corner fillet")):

            box = QtWidgets.QCheckBox(text)
            box.setObjectName("SWSMGusset" + prop)
            box.setChecked(bool(getattr(obj, prop)))
            box.setToolTip(text)
            spin.setToolTip(text)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(box)
            row.addWidget(spin, 1)
            f.addRow(row)
            self.toggles.append(box)
        self.use_draft, self.use_inner, self.use_outer = self.toggles

        prev = _box("Preview")
        f = prev.layout()
        self.partial = QtWidgets.QRadioButton("Partial preview")
        self.partial.setObjectName("SWSMGussetPartial")
        self.full = QtWidgets.QRadioButton("Full preview")
        self.full.setObjectName("SWSMGussetFull")
        f.addRow(self.partial)
        f.addRow(self.full)

        fpv = _box("Flat Pattern Visibility")
        f = fpv.layout()
        self.override = QtWidgets.QCheckBox("Override document settings")
        self.override.setObjectName("SWSMGussetOverride")
        self.show_profile = QtWidgets.QCheckBox("Show profile")
        self.show_profile.setObjectName("SWSMGussetShowProfile")
        self.show_center = QtWidgets.QCheckBox("Show center")
        self.show_center.setObjectName("SWSMGussetShowCenter")
        for w in (self.override, self.show_profile, self.show_center):
            f.addRow(w)

        position.setProperty("swstyle_pm_title", TITLE)
        position.setProperty("swstyle_pm_icon", ICON)
        self.form = [position, prof, dims, prev, fpv]
        self.lists = [self.faces, self.line, self.point]
        self.active = self.faces
        self.keys = _DeleteKey(self)
        for w in self.lists:
            w.installEventFilter(self.keys)
        self._load()
        for s in (self.offset, self.depth, self.d1, self.d2, self.a1, self.width, self.thick, self.draft,
                  self.inner, self.outer):
            s.valueChanged.connect(self._changed)
        for b in (self.use_offset, self.offset_reverse, self.depth_mode, self.dims_mode, self.d2_mode,
                  self.a1_mode, self.flip, self.rounded, self.flat, self.partial, self.full, self.override,
                  self.show_profile, self.show_center, self.use_draft, self.use_inner, self.use_outer):
            b.toggled.connect(self._changed)
        self.busy = False
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _load(self):
        o = self.obj
        (self.depth_mode if o.ProfileType == "Indent depth" else self.dims_mode).setChecked(True)
        (self.a1_mode if o.UseAngle else self.d2_mode).setChecked(True)
        (self.rounded if o.GussetType == ROUNDED else self.flat).setChecked(True)
        (self.full if o.Preview == "Full" else self.partial).setChecked(True)
        self.override.setChecked(bool(o.OverrideFlat))
        self.show_profile.setChecked(bool(o.ShowProfile))
        self.show_center.setChecked(bool(o.ShowCenter))

    # ---------------------------------------------------------------- lists
    def set_active(self, w):
        if w in self.lists:
            self.active = w

    def _fill(self):
        o = self.obj
        self.faces.clear()
        for name in o.Faces:
            self.faces.addItem(name)
        self.line.clear()
        if o.Line:
            self.line.addItem(o.Line)
        self.point.clear()
        if o.Point:
            self.point.addItem(o.Point)
        dims = o.ProfileType != "Indent depth"
        self.depth.setEnabled(not dims)
        for w in (self.d1, self.d2_mode, self.a1_mode, self.flip):
            w.setEnabled(dims)
        self.d2.setEnabled(dims and not o.UseAngle)
        self.a1.setEnabled(dims and bool(o.UseAngle))
        flat = o.GussetType == FLAT
        for box, spin in zip(self.toggles, (self.draft, self.inner, self.outer)):
            box.setEnabled(flat)
            spin.setEnabled(flat)
            spin.setVisible(box.isChecked())    # a value switched off is not shown
        self.offset.setEnabled(bool(o.UseOffset))
        self.offset_reverse.setEnabled(bool(o.UseOffset))
        self.show_center.setEnabled(self.show_profile.isChecked())

    def remove_current(self, w):
        o = self.obj
        if w is self.faces:
            row = w.currentRow()
            if row < 0:
                return
            for prop in ("Faces", "FacePoints", "FaceNormals"):
                values = list(getattr(o, prop))
                del values[row]
                setattr(o, prop, values)
        elif w is self.line:
            o.Line = ""
        elif w is self.point:
            o.Point = ""
        self._apply()

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        from PySide import QtCore
        at = App.Vector(*point) if point else None
        QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smgusset.py:804", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or not sub:
            return
        from .smnormalcut import baked
        base = baked(self.obj.BaseFeature.Shape)
        element = picked.Shape.getElement(sub)
        o = self.obj
        self.pick_error = ""
        if sub.startswith("Face"):
            if at is None or element.distToShape(Part.Vertex(at))[0] > 1e-4:
                at = element.distToShape(Part.Vertex(element.CenterOfMass))[1][0][0]
            i = face_at(base, at)
            if i is None:
                return
            face = base.Faces[i]
            if face.Surface.TypeId == "Part::GeomCylinder":
                faces = _supporting(base, face)
            elif face.Surface.TypeId == "Part::GeomPlane":
                faces = [face]
            else:
                faces = []
            if not faces:
                self.pick_error = MESSAGE
                self._report()
                return
            names, points, normals = list(o.Faces), list(o.FacePoints), list(o.FaceNormals)
            if len(faces) == 2:
                names, points, normals = [], [], []
            for fc in faces:
                from .smnormalcut import inside_point
                p = inside_point(fc)
                k = face_at(base, p, fc.normalAt(0, 0))
                label = "Face%d" % (k + 1)
                if label in names:
                    continue
                if len(names) >= 2:
                    names, points, normals = names[1:], points[1:], normals[1:]
                names.append(label)
                points.append(p)
                normals.append(fc.normalAt(0, 0))
            o.Faces, o.FacePoints, o.FaceNormals = names, points, normals
        elif sub.startswith("Edge"):
            if element.Curve.TypeId != "Part::GeomLine":
                self.pick_error = "The reference line must be a straight edge."
                self._report()
                return
            o.Line = "%s@%s" % (sub, picked.Label)
            o.LineStart, o.LineEnd = element.Vertexes[0].Point, element.Vertexes[-1].Point
        elif sub.startswith("Vertex"):
            o.Point = "%s@%s" % (sub, picked.Label)
            o.PointAt = element.Point
        self._apply()

    # ---------------------------------------------------------------- result
    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        o.UseOffset = self.use_offset.isChecked()
        o.OffsetReverse = self.offset_reverse.isChecked()
        o.Offset = self.offset.value()
        o.ProfileType = "Indent depth" if self.depth_mode.isChecked() else "Profile dimensions"
        o.IndentDepth = self.depth.value()
        o.D1, o.D2, o.A1 = self.d1.value(), self.d2.value(), self.a1.value()
        o.UseAngle = self.a1_mode.isChecked()
        o.FlipSides = self.flip.isChecked()
        o.GussetType = ROUNDED if self.rounded.isChecked() else FLAT
        o.IndentWidth, o.IndentThickness = self.width.value(), self.thick.value()
        o.DraftAngle, o.InnerFillet, o.OuterFillet = self.draft.value(), self.inner.value(), self.outer.value()
        o.UseDraft, o.UseInnerFillet, o.UseOuterFillet = [b.isChecked() for b in self.toggles]
        o.Preview = "Full" if self.full.isChecked() else "Partial"
        if (self.show_profile.isChecked() or self.show_center.isChecked()) and not self.override.isChecked() \
                and (self.show_profile.isChecked() != bool(o.ShowProfile)
                     or self.show_center.isChecked() != bool(o.ShowCenter)):
            self.busy = True
            self.override.setChecked(True)      # picking what to show overrides the document settings
            self.busy = False
        if not self.show_profile.isChecked():
            self.busy = True
            self.show_center.setChecked(False)
            self.busy = False
        o.OverrideFlat = self.override.isChecked()
        o.ShowProfile = self.show_profile.isChecked()
        o.ShowCenter = self.show_center.isChecked()
        self._apply()

    def _apply(self):
        from PySide import QtCore
        doc = self.obj.Document
        if doc.Recomputing:
            QtCore.QTimer.singleShot(50, self._apply)
            return
        self.obj.touch()
        doc.recompute()
        self._fill()
        self._report()

    def _report(self):
        if "Invalid" in self.obj.State:
            text = self.obj.getStatusString()
        elif self.pick_error:
            text = self.pick_error
        elif len(self.obj.Faces) < 2:
            text = MESSAGE
        else:
            text = ""
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text

    def getStandardButtons(self):
        from PySide import QtWidgets
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smgusset.py:922", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smgusset.py:928", _fw_err)

    def accept(self):
        self.pick_error = ""
        if not self._report():
            return False
        self.obj.Proxy.editing = False
        self.obj.touch()
        self.obj.Document.recompute()
        if "Invalid" in self.obj.State:
            self.obj.Proxy.editing = True
            self._report()
            return False
        try:
            self.obj.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("smgusset.py:944", _fw_err)
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        base = self.obj.BaseFeature if self.new else None
        self.obj.Proxy.editing = False
        doc.abortTransaction()
        doc.recompute()
        if base is not None:
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smgusset.py:959", _fw_err)
        self._close()
        return True


# ================================================================ command
def _sheet_body():
    """The active body when it is sheet metal, folded and not in a dialog."""
    if App.ActiveDocument is None or smflatten.blocked():
        return None
    try:
        if Gui.Control.activeDialog():
            return None
        body = smflatten._body()
    except Exception as _fw_err:
        _fw_log("smgusset.py:982", _fw_err)
        return None
    if body is None or smflatten.root(body) is None or body.Tip is None or body.Tip.Shape.isNull():
        return None
    return body


def start():
    body = _sheet_body()
    if body is None:
        return
    picked = [(o.Document.Name, o.Object.Name, sub, App.Vector(p)) for o in Gui.Selection.getSelectionEx()
              for sub, p in zip(o.SubElementNames, o.PickedPoints) if sub.startswith("Face")]
    doc = body.Document
    doc.openTransaction(TITLE)
    try:
        obj = make(body)
        doc.recompute()
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    for doc_name, name, sub, at in picked[:2]:
        panel._picked(doc_name, name, sub, at)


class Command:
    def GetResources(self):
        from .smunfold import _icon
        return {"Pixmap": _icon(ICON), "MenuText": "Sheet Metal Gusset",
                "ToolTip": "Presses a stiffening rib across a bend."}

    def IsActive(self):
        return _sheet_body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
