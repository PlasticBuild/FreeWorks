# SPDX-License-Identifier: LGPL-2.1-or-later
""






import FreeCAD as App

from . import asmcore as ac

V = App.Vector
KIND = "Cam"


def refs_of(joint):
    """(cam face (comp, element), follower (comp, element))."""
    return (joint.Reference1[0], joint.Reference1[1][0]), (joint.Reference2[0], joint.Reference2[1][0])


def is_cam(ref):
    s = ac.element(*ref)
    return s is not None and s.ShapeType == "Face" and s.Surface.TypeId != "Part::GeomPlane"


def follower_kind(ref):
    ""

    s = ac.element(*ref)
    if s is None:
        return None
    if s.ShapeType == "Vertex":
        return "point"
    if _flat(s):
        return "plane"
    g = ac.geometry(s)
    if g is not None and g[0] == "axis" and len(g) > 3 and g[3] > 0:
        return "roller"
    return None


def _flat(s):
    """A flat face: a plane follower (asmpkg355)."""
    return s.ShapeType == "Face" and s.Surface.TypeId == "Part::GeomPlane"


def _plane_of(s):
    """A flat follower face: (a point on it, its outward normal: the side the cam is on)."""
    u0, u1, v0, v1 = s.ParameterRange
    u, v = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    return V(s.valueAt(u, v)), V(s.normalAt(u, v)).normalize()


def _plane_gap(solid, p, n):
    """How far the cam is in front of the flat follower (< 0: into it): the least x . n over the
    cam, less p . n, measured exactly against a wide face set well behind the cam."""
    import Part
    bb = solid.BoundBox
    far = bb.DiagonalLength + abs((bb.Center - p).dot(n)) + 1.0
    at = bb.Center - n * ((bb.Center - p).dot(n) + far)
    wall = Part.Face(Part.Wire(Part.makeCircle(bb.DiagonalLength * 4 + 10.0, at, n)))
    return solid.distToShape(wall)[0] - far


def make(asm, cam, follower, joint=None):
    """Returns (mate, message)."""
    if not is_cam(cam) or follower_kind(follower) is None:
        return None, "Pick a curved face of the cam, then the follower's vertex, flat face or round face."
    if cam[0] is follower[0]:
        return None, "The cam and the follower are two components."
    if joint is None:
        joint = ac.joint_group(asm).newObject("App::FeaturePython", "CamMate")
        for prop, t, doc in ((ac.MATE_PROP, "App::PropertyString", "Mate type"),
                             (ac.ERROR_PROP, "App::PropertyBool", "The mate over defines the assembly"),
                             ("Suppressed", "App::PropertyBool", "Suppressed"),
                             ("Reference1", "App::PropertyXLinkSubHidden", "Cam path"),
                             ("Reference2", "App::PropertyXLinkSubHidden", "Cam follower")):
            joint.addProperty(t, prop, "FreeCAD", doc)
        setattr(joint, ac.MATE_PROP, KIND)
        stem = "CamMateCoincident" if follower_kind(follower) == "point" else "CamMateTangent"
        taken = {o.Label.split(" (")[0] for o in asm.Document.Objects}
        n = 1
        while "%s%d" % (stem, n) in taken:
            n += 1
        joint.Label = "%s%d" % (stem, n)
        if App.GuiUp and joint.ViewObject is not None:
            joint.ViewObject.Proxy = 0
    joint.Reference1 = (cam[0], [cam[1]])
    joint.Reference2 = (follower[0], [follower[1]])
    ok = ac.solve(asm)
    return joint, (None if ac._mark(joint, ok) else ac.OVER_MESSAGE)


def cams(asm):
    return [j for j in ac.mates(asm) if ac.mate_type(j) == KIND and not getattr(j, "Suppressed", False)]


_SLABS = {}     # (component, face, placement) -> the cam's own solid


def _whole(comp):
    s = comp.Shape
    return s.Solids[0] if s.Solids else s


def _profile_axis(face):
    """The direction a cam's side face runs across the cam's thickness (it is a profile swept
    straight): the normals at points spread over the face all lie square to it. None otherwise."""
    try:
        u0, u1, v0, v1 = face.ParameterRange
        ns = [face.normalAt(u0 + (u1 - u0) * a, v0 + (v1 - v0) * b) for a in (0.1, 0.37, 0.63, 0.9) for b in (0.25, 0.75)]
    except Exception:
        return None
    axis = None
    for n in ns[1:]:
        c = ns[0].cross(n)
        if c.Length > 1e-3:
            axis = c.normalize()
            break
    if axis is None or any(abs(n.dot(axis)) > 1e-3 for n in ns):
        return None
    return axis


def _cam_solid(cam):
    ""


    import Part
    comp, sub = cam
    key = (comp.Document.Name, comp.Name, sub)
    pl = App.Placement(comp.Placement)
    hit = _SLABS.get(key)
    try:
        src = comp.getLinkedObject(True).Shape.hashCode()      # the part rebuilt: worked out again
    except Exception:
        src = None
    if hit is not None and hit[2] == src:
        if hit[0].isSame(pl, 1e-12) if hasattr(hit[0], "isSame") else hit[0] == pl:
            return hit[1]
        moved = hit[1].copy()       # worked out once: moved with the cam as it turns
        moved.Placement = pl.multiply(hit[0].inverse()).multiply(moved.Placement)
        return moved
    solid = _whole(comp)
    out = solid
    try:
        face = ac.element(comp, sub)
        axis = _profile_axis(face) if face is not None else None
        if axis is not None and solid.ShapeType == "Solid":
            ts = [v.Point.dot(axis) for v in face.Vertexes] or [face.BoundBox.Center.dot(axis)]
            lo, hi = min(ts), max(ts)
            if hi - lo > 1e-6:
                c = solid.BoundBox.Center
                base = c + axis * (lo - c.dot(axis))
                disc = Part.Face(Part.Wire(Part.makeCircle(solid.BoundBox.DiagonalLength * 2, base, axis)))
                slab = solid.common(disc.extrude(axis * (hi - lo)))
                mid = face.CenterOfMass
                own = [x for x in slab.Solids if x.distToShape(Part.Vertex(mid))[0] < 1e-6]
                if own and own[0].Volume < solid.Volume - 1e-6:
                    out = own[0]
    except Exception as error:
        App.Console.PrintLog("FreeCAD: cam profile: %s\n" % error)
    if len(_SLABS) > 64:
        _SLABS.clear()
    _SLABS[key] = (pl, out, src)
    return out


def _gap(joint, shift=V()):
    """How far the follower (moved by shift) is from touching the cam: < 0 inside it."""
    import Part
    cam, fol = refs_of(joint)
    solid = _cam_solid(cam)
    s = ac.element(*fol)
    if follower_kind(fol) == "point":
        p = V(s.Point) + shift
        d = Part.Compound(solid.Faces).distToShape(Part.Vertex(p))[0]     # to the skin (a solid is 0 inside)
        return -d if solid.isInside(p, 1e-7, False) else d
    if follower_kind(fol) == "plane":
        p, n = _plane_of(s)
        return _plane_gap(solid, p + shift, n)
    g = ac.geometry(s)
    c, axis, r = V(g[1]) + shift, V(g[2]).normalize(), g[3]
    # the roller's axis across the cam's thickness: a segment through the cam's bounding box
    bb = solid.BoundBox
    half = bb.DiagonalLength
    seg = Part.LineSegment(c - axis * half, c + axis * half).toShape()
    d = solid.distToShape(seg)[0]
    if d < 1e-9:
        # the axis runs through the cam: how deep, from the nearest point of the cam's side faces
        side = [f for f in solid.Faces if f.Surface.TypeId != "Part::GeomPlane"] or solid.Faces
        return -Part.Compound(side).distToShape(seg)[0] - r
    return d - r


def slide_axis(asm, comp):
    """The direction the component's own mates let it slide (a Concentric/Slider to another
    component), or None."""
    for j in ac.joint_group(asm).Group:
        if getattr(j, "JointType", None) not in ("Slider", "Cylindrical") or getattr(j, "Suppressed", False):
            continue
        for r in (getattr(j, "Reference1", None), getattr(j, "Reference2", None)):
            if r and r[0] is comp:
                for sub in r[1]:
                    g = ac.geometry(ac.element(comp, sub))
                    if g is not None and g[0] in ("axis", "line"):
                        return V(g[2]).normalize()
    return None


def _root(f, lo, hi, n=40):
    flo = f(lo)
    for _i in range(n):
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if (fm < 0) == (flo < 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2.0


def touch(asm, joint, fixed):
    cam, fol = refs_of(joint)
    comp = fol[0]
    if comp in fixed:
        return False
    gap0 = _gap(joint)
    if abs(gap0) < 1e-6:
        return False
    d = slide_axis(asm, comp)
    if d is not None:
        bb = _cam_solid(cam).BoundBox
        at = ac.element(*fol)
        kind = follower_kind(fol)
        at = V(at.Point) if kind == "point" else _plane_of(at)[0] if kind == "plane" else V(ac.geometry(at)[1])
        reach = bb.DiagonalLength + (at - bb.Center).Length + 1.0     # as far as the cam is
        f = lambda t: _gap(joint, d * t)
        best = None
        steps = 64
        prev_t, prev = 0.0, gap0
        for sign in (1, -1):
            prev_t, prev = 0.0, gap0
            for i in range(1, steps + 1):
                t = sign * reach * i / steps
                ft = f(t)
                if (ft < 0) != (prev < 0) or abs(ft) < 1e-9:
                    root = _root(f, prev_t, t)
                    if best is None or abs(root) < abs(best):
                        best = root
                    break
                prev_t, prev = t, ft
        if best is None:
            return False
        shift = d * best
    elif follower_kind(fol) == "plane":
        shift = _plane_of(ac.element(*fol))[1] * gap0     # straight on along its normal: the face meets the cam
    else:
        import Part
        s = ac.element(*fol)
        solid = _cam_solid(cam)
        p = V(s.Point) if follower_kind(fol) == "point" else V(ac.geometry(s)[1])
        q = V(solid.distToShape(Part.Vertex(p))[1][0][0])
        n = q - p
        if n.Length < 1e-12:
            return False
        n.normalize()
        f = lambda t: _gap(joint, n * t)
        shift = n * _root(f, -abs(gap0) * 2 - 1, abs(gap0) * 2 + 1)
    comp.Placement = App.Placement(comp.Placement.Base + shift, comp.Placement.Rotation)
    return True


def follow(asm):
    """After a solve or a drag step: each follower back on its cam. True when one moved."""
    fixed = set(ac.grounded(asm))
    moved = False
    for joint in cams(asm):
        try:
            moved |= touch(asm, joint, fixed)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: cam: %s\n" % error)
    return moved


def follow_frames(asm, frames, n):
    """A motion study's frames with each cam follower back on its cam (FreeCAD's simulation moves
    only its own joints). frames: the study's held frames ({component: placement} per frame) or
    None (FreeCAD's own frames, read with updateForFrame). None when there is no cam."""
    if not cams(asm):
        return None
    comps = ac.components(asm)
    start = {c.Name: App.Placement(c.Placement) for c in comps}
    if not frames:
        frames = []
        for k in range(n):
            try:
                asm.updateForFrame(k)
            except Exception:
                break
            frames.append({c.Name: App.Placement(c.Placement) for c in comps})
    out = []
    try:
        for frame in frames:
            for c in comps:
                if c.Name in frame:
                    c.Placement = frame[c.Name]
            for _ in range(3):
                if not follow(asm):
                    break
            out.append({c.Name: App.Placement(c.Placement) for c in comps})
    finally:
        for c in comps:
            c.Placement = start[c.Name]
    return out


def holds(joint, tol=1e-3):
    try:
        return abs(_gap(joint)) < tol * 10
    except Exception:
        return True


def is_cam_shape(s):
    return s.ShapeType == "Face" and s.Surface.TypeId != "Part::GeomPlane"


def follower_shape(s):
    if s.ShapeType == "Vertex" or _flat(s):
        return True
    g = ac.geometry(s)
    return g is not None and g[0] == "axis" and len(g) > 3 and g[3] > 0
