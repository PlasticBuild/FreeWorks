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
import Part

V = App.Vector
TOL = 1e-6
PROPS = {
    "SWAngleFaceMode": ("App::PropertyString", "Perpendicular to face"),
    "SWLengthEnd": ("App::PropertyString", "Blind"),
    "SWLengthVertex": ("App::PropertyLinkSub", None),
    "SWVertexMode": ("App::PropertyString", "Perpendicular to flange plane"),
    "SWPosition": ("App::PropertyString", ""),
    "SWTear": ("App::PropertyString", "Rip"),
    "SWProfile": ("App::PropertyLink", None),
    "SWTrimSideBends": ("App::PropertyBool", False),

    "SWMultiLength": ("App::PropertyBool", False),
    "SWEdgeLengths": ("App::PropertyFloatList", None),
}
LIVE = "SWSideBendsLive"     # set on flanges made since Trim side bends works: older ones keep their trimmed shape
TRIMMED = "SWTrimmedShape"   # the flange's shape without the side bends' material kept (by it or before it)
VIRTUAL_SHARP, TANGENT = "Bend from Virtual Sharp", "Tangent to Bend"
PARALLEL_BASE = "Parallel to base flange"


def ensure(obj):
    for name, (kind, default) in PROPS.items():
        if name not in obj.PropertiesList:
            obj.addProperty(kind, name, "FreeCAD", "Edge Flange option")
            if default is not None:
                setattr(obj, name, default)


def _engine():
    import SheetMetalCmd
    return SheetMetalCmd


def _base(fp):
    return fp.baseObject[0], list(fp.baseObject[1])


def thickness(fp):
    base, subs = _base(fp)
    try:
        t, _d = _engine().sheet_thk(base.Shape.copy(), subs[0])
        return float(t)
    except Exception:
        return 1.0


def ref_angle(fp):
    """SheetMetal's angle that puts the wall parallel to the angle face (its RelativeAngleToRef 0)."""
    E = _engine()
    base, subs = _base(fp)
    sm_face, ref_edge, thk_face = E.GetSMComparisonFace(base, subs[0])
    obj, names = fp.AngleFaceReference
    if "Plane" in obj.TypeId:
        face = E.SheetMetalTools.smConvertPlaneToFace(obj.Shape)
    else:
        face = obj.Shape.getElement(names[0])
    a = E.relatAngleCalc(thk_face, ref_edge, face, sm_face)
    try:
        a = a[0]
    except Exception as _fw_err:
        _fw_log("smedgegeom.py:96", _fw_err)
    return float(a)


def before(fp):
    """Settings worked out before the wall's build: the position's offset, the perpendicular face angle."""
    if fp.AngleFaceReference is not None:
        if fp.SWAngleFaceMode == "Parallel to face":
            fp.RelativeAngleToRef = 0.0
        else:
            try:
                fp.RelativeAngleToRef = -90.0 if ref_angle(fp) > 90.0 else 90.0
            except Exception:
                fp.RelativeAngleToRef = 90.0
        fp.SupplAngleRef = False
    if fp.SWPosition in (VIRTUAL_SHARP, TANGENT):
        angle = float(fp.angle)
        if fp.AngleFaceReference is not None:
            try:
                angle = ref_angle(fp) + float(fp.RelativeAngleToRef)
            except Exception as _fw_err:
                _fw_log("smedgegeom.py:117", _fw_err)
        rt = float(fp.radius) + thickness(fp)
        fp.BendType = "Offset"
        if fp.SWPosition == TANGENT:
            fp.offset = -rt
        else:
            fp.offset = -rt * math.tan(math.radians(min(max(angle, 0.0), 178.0) / 2.0))


# ---------------------------------------------------------------- the flange's frame
def flange_only(fp):
    base, _subs = _base(fp)
    return fp.Shape.cut(base.Shape)


def frame(fp, only=None):
    """The flange's frame: origin on the outer virtual sharp at the edge's start, x along the edge, y up
    the flange (away from the bend), z out of the outer face. Also the base's outward normal at the bend."""
    base, subs = _base(fp)
    only = only if only is not None else flange_only(fp)
    edge = base.Shape.getElement(subs[0])
    e = (edge.Vertexes[-1].Point - edge.Vertexes[0].Point)
    e.normalize()
    line = Part.Line(edge.Vertexes[0].Point, edge.Vertexes[0].Point + e)

    def same(c, f):
        return abs(c.Radius - f.Surface.Radius) < 1e-7 and c.Center.distanceToLine(
            f.Surface.Center, f.Surface.Axis) < 1e-7

    old = [f for f in base.Shape.Faces if f.Surface.TypeId == "Part::GeomCylinder"]
    cyls = [f for f in fp.Shape.Faces if f.Surface.TypeId == "Part::GeomCylinder"
            and abs(abs(f.Surface.Axis.dot(e)) - 1) < 1e-7 and not any(same(f.Surface, g) for g in old)]
    if not cyls:
        raise ValueError("The flange has no bend to measure from.")
    near = min(c.Surface.Center.distanceToLine(line.Location, e) for c in cyls)
    cyls = [c for c in cyls if c.Surface.Center.distanceToLine(line.Location, e) < near + 1e-6]
    outer = max(cyls, key=lambda f: f.Surface.Radius)
    p, ro = outer.Surface.Center, outer.Surface.Radius
    axis = outer.Surface.Axis

    def off_axis(q):
        w = q - p
        return w - axis * w.dot(axis)

    def tangent_planes(shape):
        out = []
        for f in shape.Faces:
            if f.Surface.TypeId != "Part::GeomPlane":
                continue
            n = f.normalAt(0, 0)
            if abs(n.dot(e)) > 1e-6:
                continue
            dist = (f.CenterOfMass - p).dot(n)
            if abs(abs(dist) - ro) < 1e-5:
                n = n if dist > 0 else n * -1
                # the cylinder touches the face itself, not only its plane
                touch = Part.Line(p + n * ro, p + n * ro + axis).toShape(-1e4, 1e4)
                if f.distToShape(touch)[0] < 1e-5:
                    out.append((f, n))
        return out
    bases = tangent_planes(base.Shape)
    if not bases:
        raise ValueError("The base's face at the bend wasn't found.")
    walls = [x for x in tangent_planes(fp.Shape) if all(abs(x[1].dot(n)) < 0.9999 for _f, n in bases)]
    if not walls:
        raise ValueError("The flange has no flat face to sketch on.")
    wall, nw = max(walls, key=lambda x: x[0].Area)
    nb = bases[0][1]
    vs = p + (nb + nw) * (ro / (1.0 + nb.dot(nw)))
    origin = vs + e * (edge.Vertexes[0].Point - vs).dot(e)
    d = e.cross(nw)
    if (wall.CenterOfMass - origin).dot(d) < 0:
        d = d * -1
    z = e.cross(d)
    m = App.Matrix(e.x, d.x, z.x, origin.x, e.y, d.y, z.y, origin.y, e.z, d.z, z.z, origin.z, 0, 0, 0, 1)
    pl = App.Placement(m)
    flat = pl.inverse().multVec(p + nw * ro).y      # where the flat of the flange starts
    return pl, nb, edge.Length, flat


# ---------------------------------------------------------------- Up To Vertex
def _tip(only, u):
    return max(v.Point.dot(u) for v in only.Vertexes)


def up_to_vertex(fp, build):
    """Sets the length so the flange ends at the vertex: on the plane through it square to the flange
    (Perpendicular to flange plane) or parallel to the base (Parallel to base flange)."""
    obj, names = fp.SWLengthVertex
    target = obj.Shape.getElement(names[0]).Point
    only = flange_only(fp)
    pl, nb, _len, _flat = frame(fp, only)
    u = nb * -1 if fp.SWVertexMode == PARALLEL_BASE else pl.Rotation.multVec(V(0, 1, 0))
    l0 = float(fp.length)
    t0 = _tip(only, u)
    fp.length = l0 + 1.0
    build()
    t1 = _tip(flange_only(fp), u)
    slope = t1 - t0
    if abs(slope) < 1e-6:
        raise ValueError("Up To Vertex: the flange can't reach the vertex in that direction.")
    length = l0 + (target.dot(u) - t0) / slope
    if length <= 0.01:
        raise ValueError("Up To Vertex: the vertex is behind the bend.")
    fp.length = length
    build()


# ---------------------------------------------------------------- Edit Flange Profile
def _local_face(sketch):
    """The profile as a face in the sketch's own plane coordinates."""
    shape = sketch.Shape.copy()
    shape.transformShape(sketch.Placement.inverse().toMatrix(), True)
    wires = [w for w in shape.Wires if w.isClosed()]
    if not wires:
        raise ValueError("The flange profile must be one closed outline.")
    return Part.makeFace(wires, "Part::FaceMakerBullseye")


def profile_rectangle(fp):
    """The flange's outline in its frame (x along the edge from its start, y up from the virtual sharp)."""
    only = flange_only(fp)
    pl, _nb, _len, _flat = frame(fp, only)
    inv = pl.inverse()
    pts = [inv.multVec(v.Point) for v in only.Vertexes]
    walls = [p for p in pts if abs(p.z) < 1e-5]
    x0, x1 = min(p.x for p in walls), max(p.x for p in walls)
    y1 = max(p.y for p in walls)
    return pl, (x0, 0.0, x1, y1)


def apply_profile(fp, build):
    """Builds the flange so it covers the profile, then cuts it to the profile."""
    face = _local_face(fp.SWProfile)
    bb = face.BoundBox
    if not face.common(Part.makeLine(V(bb.XMin - 1, 0, 0), V(bb.XMax + 1, 0, 0))).Edges:
        raise ValueError("The flange profile's bottom must lie on the edge (the line y = 0 of its sketch).")
    pl, _nb, length, flat = frame(fp)
    # the bend keeps the profile's width where the flat starts; the sides run on from there
    at = min(max(flat, 0.0), bb.YMax - 1e-6)
    bottom = face.common(Part.makeLine(V(bb.XMin - 1, at, 0), V(bb.XMax + 1, at, 0)))
    if not bottom.Edges:
        raise ValueError("The flange profile is too low to clear the bend.")
    b0 = min(v.X for v in bottom.Vertexes)
    b1 = max(v.X for v in bottom.Vertexes)
    p0, p1 = bb.XMin, bb.XMax
    if b1 < TOL or b0 > length - TOL:
        raise ValueError("The flange profile's bottom must lie on the edge.")
    b0, b1 = max(b0, 0.0), min(b1, length)
    fp.LengthSpec = "Outer Sharp"
    fp.length = bb.YMax + 1.0

    def set_sides(swap):
        g1, g2 = max(b0, 0.0), max(length - b1, 0.0)
        x1, x2 = g1 - p0, p1 - b1
        if swap:
            g1, g2, x1, x2 = g2, g1, x2, x1
        fp.gap1, fp.gap2, fp.extend1, fp.extend2 = g1, g2, x1, x2
    set_sides(False)
    build()
    only = flange_only(fp)
    inv = pl.inverse()
    xs = [inv.multVec(v.Point).x for v in only.Vertexes]
    if abs(min(xs) - p0) > 1e-4 or abs(max(xs) - p1) > 1e-4:
        set_sides(True)
        build()
        only = flange_only(fp)
    big = 10.0 * (bb.XLength + bb.YLength + length + 10.0)
    upper = face.common(Part.makeFace(Part.makePolygon(
        [V(-big, at, 0), V(big, at, 0), V(big, big, 0), V(-big, big, 0), V(-big, at, 0)])))
    keep = upper.fuse(Part.makeFace(Part.makePolygon(
        [V(b0, at, 0), V(b1, at, 0), V(b1, -big, 0), V(b0, -big, 0), V(b0, at, 0)]))).removeSplitter()
    keep = keep.extrude(V(0, 0, 2 * big))
    keep.translate(V(0, 0, -big))
    keep.transformShape(pl.toMatrix(), True)
    waste = only.cut(keep)
    if waste.Volume > 1e-9:
        fp.Shape = fp.Shape.cut(waste).removeSplitter()


def after(fp, build):
    """The options worked out from the wall's build."""
    if fp.SWProfile is not None:
        apply_profile(fp, build)
    elif fp.SWLengthEnd == "Up To Vertex" and fp.SWLengthVertex is not None:
        up_to_vertex(fp, build)


def mark_live(obj, trim="SWTrimSideBends"):
    ""

    if LIVE not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", LIVE, "FreeCAD", "Trim side bends takes effect")
        obj.setEditorMode(LIVE, 2)
    setattr(obj, LIVE, True)
    if trim in obj.PropertiesList:
        setattr(obj, trim, False)


def trimmed_shape(obj):
    """obj's shape without any side bend material kept, for the builds made on it."""
    if obj is not None and TRIMMED in obj.PropertiesList:
        t = getattr(obj, TRIMMED)
        if not t.isNull():
            return t
    return obj.Shape


def kept_material(obj):
    """The side bends' material obj's shape kept (Trim side bends off, on it or on a flange before it)."""
    t = trimmed_shape(obj)
    if t is obj.Shape or obj.Shape.isNull():
        return []
    try:
        extra = obj.Shape.cut(t)
    except Exception:
        return []
    return [x for x in extra.Solids if x.Volume > 1e-9]


def remember_trimmed(obj, shape):
    if TRIMMED not in obj.PropertiesList:
        obj.addProperty("Part::PropertyPartShape", TRIMMED, "FreeCAD", "The shape without side bend material kept")
        obj.setEditorMode(TRIMMED, 2)
    setattr(obj, TRIMMED, shape)


def _same(a, b):
    if a.ShapeType != b.ShapeType or abs(a.Length - b.Length if a.ShapeType == "Edge" else a.Area - b.Area) > 1e-6:
        return False
    if a.ShapeType == "Edge":
        p, q = [v.Point for v in a.Vertexes], [v.Point for v in b.Vertexes]
        return len(p) == len(q) and (all((x - y).Length < 1e-6 for x, y in zip(p, q))
                                     or all((x - y).Length < 1e-6 for x, y in zip(p, reversed(q))))
    return (a.CenterOfMass - b.CenterOfMass).Length < 1e-6


def remap(src, dst, subs):
    """The names in dst of src's elements subs (the same edge or face), or None when one is not there."""
    out = []
    for sub in subs:
        if not sub.startswith(("Edge", "Face")):
            out.append(sub)
            continue
        el = src.getElement(sub)
        kind = "Edge" if sub.startswith("Edge") else "Face"
        items = dst.Edges if kind == "Edge" else dst.Faces
        hit = next((i for i, x in enumerate(items, 1) if _same(el, x)), None)
        if hit is None:
            return None
        out.append("%s%d" % (kind, hit))
    return out


def with_kept(shape, kept):
    """shape with the side bend material kept before it put back, when the part stays one valid solid."""
    if not kept:
        return shape
    try:
        out = shape.fuse(kept).removeSplitter()
    except Exception:
        return shape
    if len(out.Solids) != 1 or not out.isValid():
        return shape
    return out.Solids[0]


def corner_base(base):
    """For a corner feature (Corner Relief, Closed Corner, Welded Corner): the base's trimmed shape to work
    on, and the side bend material it kept."""
    return trimmed_shape(base).copy(), kept_material(base)


def corner_result(obj, trimmed, result, kept, reach=0.5):
    """A corner feature's shape: its result on the trimmed shape, with the kept side bend material put back
    except at the corners it worked on (its own treatment takes the place of that material there)."""
    remember_trimmed(obj, result)
    if not kept:
        return result
    try:
        changed = [x for x in trimmed.cut(result).Solids + result.cut(trimmed).Solids if x.Volume > 1e-9]
    except Exception:
        changed = []
    stay = [k for k in kept if not any(k.distToShape(c)[0] < reach for c in changed)]
    return with_kept(result, stay)


def bend_pieces(shape):
    """The material of each bend of shape, between the bend's two ends."""
    from .smunfold import Bend, _coaxial, bends_of
    out = []
    for inner, outer in bends_of(shape):
        b = Bend(inner, outer, 0.5)
        try:
            res, _m = shape.generalFuse([b.seam_face(b.u0), b.seam_face(b.u1)])
        except Exception:
            continue
        for piece in res.Solids:
            if any(f.Surface.TypeId == "Part::GeomCylinder" and _coaxial(f, b.ref)
                   and min(abs(f.Surface.Radius - b.Ro), abs(f.Surface.Radius - b.Ri)) < TOL for f in piece.Faces):
                out.append(piece)
    return out


def _slab(p, out, gap, size=1000.0):
    """The slab from the plane through p normal to out, gap thick on out's side."""
    box = Part.makeBox(2 * size, 2 * size, gap, V(-size, -size, 0))
    box.Placement = App.Placement(p, App.Rotation(V(0, 0, 1), out))
    return box


def side_bend_material(base_shape, result, edges, gap, reach):
    """The material of base_shape's bends the build cut away beside the ends of edges, less a gap-wide
    relief next to each end: the solids to put back when Trim side bends is off."""
    removed = base_shape.cut(result)
    if removed.isNull() or removed.Volume < 1e-9:
        return []
    keep = []
    for piece in bend_pieces(base_shape):
        for s in removed.common(piece).Solids:
            if s.Volume < 1e-9:
                continue
            near = False
            for e in edges:
                a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
                if (b - a).Length < TOL:
                    continue
                d = (b - a).normalize()
                for p, out in ((a, d * -1), (b, d)):
                    if s.distToShape(Part.Vertex(p))[0] <= reach:
                        near = True
                        s = s.cut(_slab(p, out, gap))
            if near:
                keep += [x for x in s.Solids if x.Volume > 1e-9]
    return keep


def put_back_side_bends(shape, base_shape, edges, gap, reach):
    """shape with the side bends' material put back (Trim side bends off)."""
    keep = side_bend_material(base_shape, shape, edges, gap, reach)
    if not keep:
        return shape
    try:
        out = shape.fuse(keep).removeSplitter()
    except Exception:
        return shape
    if len(out.Solids) != 1 or not out.isValid():
        return shape            # the material cannot go back cleanly here: the trimmed build stands
    return out.Solids[0]


def relief_gap(thk, use_ratio, ratio, width):
    return max(float(ratio) * thk if use_ratio else float(width), 0.01)


def keep_side_bends(fp):
    """Trim side bends off on an Edge Flange made since it works: the side bends' material goes back."""
    if not getattr(fp, LIVE, False) or getattr(fp, "SWTrimSideBends", True):
        return
    base, subs = _base(fp)
    edges = [base.Shape.getElement(s) for s in subs if s.startswith("Edge")]
    edges = [e for e in edges if e.Curve.TypeId == "Part::GeomLine"]
    if not edges:
        return
    thk = thickness(fp)
    gap = relief_gap(thk, fp.UseReliefFactor, fp.ReliefFactor, fp.reliefw)
    fp.Shape = put_back_side_bends(fp.Shape, base.Shape, edges, gap, 3 * (float(fp.radius) + thk) + gap)


class on_trimmed:
    """While the wall builds: its base shows its trimmed shape (the side bend material it kept taken off)
    and the wall's edges are named in it; afterwards both are as they were. .kept is that material."""

    def __init__(self, fp):
        self.fp = fp
        self.base, self.subs = _base(fp)
        self.kept = kept_material(self.base) if self.base is not None else []
        self.swapped = False

    def __enter__(self):
        if not self.kept:
            return self
        full, trimmed = self.base.Shape, trimmed_shape(self.base)
        subs = remap(full, trimmed, self.subs)
        if subs is None:            # an edge of the kept material: the wall is built on the whole shape
            self.kept = []
            return self
        self.full = full.copy()
        self.base.Shape = trimmed
        self.fp.baseObject = (self.base, subs)
        self.swapped = True
        return self

    def __exit__(self, *exc):
        if self.swapped:
            self.base.Shape = self.full
            self.fp.baseObject = (self.base, self.subs)
            for o in (self.base, self.fp):
                try:
                    o.purgeTouched()
                except Exception as _fw_err:
                    _fw_log("smedgegeom.py:518", _fw_err)
        return False


def edge_lengths(fp):
    """Multi-length flange: [(edge name, length)] when it is on and the lengths differ, else None."""
    if not getattr(fp, "SWMultiLength", False):
        return None
    _b, subs = _base(fp)
    subs = [x for x in subs if x.startswith("Edge")]
    vals = list(getattr(fp, "SWEdgeLengths", []) or [])
    out = [(sub, vals[i] if i < len(vals) and vals[i] > 0 else float(fp.length)) for i, sub in enumerate(subs)]
    if len(out) < 2 or len({round(v, 9) for _s, v in out}) < 2:
        return None
    return out


def _same_edge(shape, edge):
    """The edge of shape lying on edge's line inside its span (an edge a flange beside it shortened by
    its gap or relief): the longest such, else None."""
    if edge.Curve.TypeId != "Part::GeomLine":
        for i, e in enumerate(shape.Edges, 1):
            if abs(e.Length - edge.Length) < TOL and e.CenterOfMass.distanceToPoint(edge.CenterOfMass) < TOL:
                return "Edge%d" % i
        return None
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    d = b - a
    n = d.Length
    d = d * (1.0 / n)
    best, length = None, 0.0
    for i, e in enumerate(shape.Edges, 1):
        if e.Curve.TypeId != "Part::GeomLine":
            continue
        ok = True
        for v in (e.Vertexes[0].Point, e.Vertexes[-1].Point):
            t = (v - a).dot(d)
            if t < -TOL or t > n + TOL or (a + d * t - v).Length > TOL:
                ok = False
                break
        if ok and e.Length > length + TOL:
            best, length = "Edge%d" % i, e.Length
    return best


class _Base:
    """A stand-in for the wall's base object: only its shape (what the build reads)."""

    def __init__(self, obj, shape):
        self._obj, self.Shape = obj, shape

    def __getattr__(self, name):
        return getattr(self._obj, name)


class _Wall:
    """The wall as one build of a Multi-length flange sees it: its own base (the shape built so far),
    edges and length; the shape it builds is kept here, and nothing is written to the document."""

    _OWN = ("baseObject", "length", "Shape", "LengthList", "bendAList")

    def __init__(self, fp, base, names, length):
        d = self.__dict__
        d["_fp"] = fp
        d["baseObject"] = (base, list(names))
        d["length"] = App.Units.Quantity(float(length), App.Units.Length)
        d["Shape"] = None

    def __getattr__(self, name):
        return getattr(self.__dict__["_fp"], name)

    def __setattr__(self, name, value):
        if name in self._OWN:
            self.__dict__[name] = value
        else:
            setattr(self.__dict__["_fp"], name, value)


def build_multi_length(fp, build, groups):
    """Each group of edges (same length) built in turn, the next on what the last one built. The
    builds run on a stand-in of the wall (_Wall) whose base shows the shape built so far, so the
    document's objects are not changed while it builds; the wall gets the last shape."""
    base, subs = _base(fp)
    shape = base.Shape.copy()
    edges = {sub: shape.getElement(sub) for sub, _l in groups}
    order = []
    for sub, val in groups:
        for g in order:
            if abs(g[0] - val) < 1e-9:
                g[1].append(sub)
                break
        else:
            order.append((val, [sub]))
    for k, (val, names) in enumerate(order):
        if k:
            names = [_same_edge(shape, edges[n]) for n in names]
            if None in names:
                raise RuntimeError("Multi-length flange: an edge could not be found after the flange beside it")
        wall = _Wall(fp, _Base(base, shape), names, val)
        build(wall)
        if wall.Shape is None:
            raise RuntimeError("Multi-length flange: a length could not be built")
        shape = wall.Shape.copy()
    fp.Shape = shape


_patched = {}


def patch():
    """Runs SheetMetal's wall build through before() and after() for walls that carry the options."""
    cls = _engine().SMBendWall
    if "execute" in _patched:
        return
    _patched["execute"] = cls.execute

    def execute(self, fp, original=_patched["execute"]):
        if "SWPosition" not in fp.PropertiesList:
            return original(self, fp)
        with on_trimmed(fp) as built:
            before(fp)
            groups = edge_lengths(fp)
            if groups and fp.SWProfile is None:
                build_multi_length(fp, lambda wall: original(self, wall), groups)
            else:
                original(self, fp)
            if fp.SWProfile is not None or (fp.SWLengthEnd == "Up To Vertex" and fp.SWLengthVertex is not None):
                try:
                    after(fp, lambda: original(self, fp))
                except ValueError as e:
                    raise RuntimeError(str(e))
            wall = fp.Shape
            keep_side_bends(fp)
        if getattr(fp, LIVE, False):
            remember_trimmed(fp, wall)      # the wall as built on the trimmed base
        fp.Shape = with_kept(fp.Shape, built.kept)
        return None
    cls.execute = execute
