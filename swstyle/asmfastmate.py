# SPDX-License-Identifier: LGPL-2.1-or-later
""














import math

import FreeCAD as App

from . import asmcore as ac
from . import paths

PARAM = "AsmAutoFastenerMates"
FIT = (0.65, 1.02)        # shank radius / hole radius that fits (a tapped hole is a little smaller)


def enabled():
    return paths.params().GetBool(PARAM, True)


def _axis(face):
    s = face.Surface
    return App.Vector(s.Center), App.Vector(s.Axis).normalize(), s.Radius


def _outer(face):
    """True for an outside round face (its normal points away from its axis)."""
    c, a, r = _axis(face)
    u0, u1, v0, v1 = face.ParameterRange
    p = face.valueAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
    n = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
    out = p - (c + a * (p - c).dot(a))
    return out.Length > 1e-9 and n.dot(out) > 0


def _full(face):
    u0, u1, _v0, _v1 = face.ParameterRange
    return u1 - u0 > math.pi


def _span(face, a):
    zs = [v.Point.dot(a) for v in face.Vertexes] or [face.CenterOfMass.dot(a)]
    return min(zs), max(zs)


def _rings(shape, a, r):
    """[(face name, normal)] of the flat faces square to a with a round edge of radius r."""
    out = []
    for i, f in enumerate(shape.Faces, 1):
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        n = f.normalAt(0, 0)
        if abs(abs(n.dot(a)) - 1.0) > 1e-6:
            continue
        for e in f.Edges:
            if e.Curve.TypeId == "Part::GeomCircle" and abs(e.Curve.Radius - r) < 1e-4 * max(1.0, r):
                out.append(("Face%d" % i, n, f))
                break
    return out


def recognise(shape, name=""):
    """{"kind": "bolt"/"nut"/"washer", "axis": face name, "seat": face name, "radius", "seat_normal"}
    from the part's own shape, or None for a part that is not a fastener."""
    if shape is None or shape.isNull() or len(shape.Solids) != 1:
        return None
    low = (name or "").lower()
    cyl = [(i, f) for i, f in enumerate(shape.Faces, 1) if f.Surface.TypeId == "Part::GeomCylinder" and _full(f)]
    if not cyl:
        return None
    bb = shape.BoundBox
    outer = [(i, f) for i, f in cyl if _outer(f)]
    inner = [(i, f) for i, f in cyl if not _outer(f)]
    # bolt / screw: the longest outside round face is the shank, and a flat ring where it meets the head
    if outer and "nut" not in low and "washer" not in low:
        def run(t):
            ax = _axis(t[1])[1]
            lo_, hi_ = _span(t[1], ax)
            return hi_ - lo_
        i, shank = max(outer, key=run)
        c, a, r = _axis(shank)
        lo, hi = _span(shank, a)
        wider = max(((v.Point - c) - a * (v.Point - c).dot(a)).Length for v in shape.Vertexes)
        if hi - lo >= 1.5 * r and wider > r * 1.2 and not inner_through(inner, a, c, r):
            for fname, n, f in _rings(shape, a, r):
                # the underside: at one end of the shank, facing along it
                level = f.CenterOfMass.dot(a)
                if abs(level - lo) < 1e-4:
                    toward = a
                elif abs(level - hi) < 1e-4:
                    toward = -a
                else:
                    continue
                if n.dot(toward) > 0.5:
                    return {"kind": "bolt", "axis": "Face%d" % i, "seat": fname, "radius": r, "seat_normal": n}
    # nut / washer: a ring round a hole, short along its axis
    if inner:
        i, hole = max(inner, key=lambda t: t[1].Area)
        c, a, r = _axis(hole)
        z0, z1 = min(v.Point.dot(a) for v in shape.Vertexes), max(v.Point.dot(a) for v in shape.Vertexes)
        height = z1 - z0
        if height > 2.5 * r * 2 and "nut" not in low and "washer" not in low:
            return None
        reach = max(((v.Point - c) - a * (v.Point - c).dot(a)).Length for v in shape.Vertexes)
        if reach > 3.2 * r:
            return None         # a plate or a block with a hole, not a ring round it
        rings = _rings(shape, a, r)
        if not rings:
            return None
        kind = "washer" if ("washer" in low or (height < 0.45 * r * 2 and "nut" not in low)) else "nut"
        fname, n, _f = rings[0]
        return {"kind": kind, "axis": "Face%d" % i, "seat": fname, "radius": r, "seat_normal": n}
    return None


def inner_through(inner, a, c, r):
    """A bolt-like part with a hole down its own axis as wide as the shank is a tube, not a bolt."""
    for _i, f in inner:
        c2, a2, r2 = _axis(f)
        if abs(abs(a.dot(a2)) - 1) < 1e-6 and r2 > 0.6 * r:
            return True
    return False


def _target(link):
    return link.getLinkedObject(True)


def _holes(asm, link):
    from . import toolbox
    out = []
    for comp in ac.components(asm):
        if comp is link or toolbox.is_fastener(comp) or recognised(comp):
            continue
        for name, r, c, a in toolbox.hole_faces(comp):
            out.append((comp, name, r, c, a))
    return out


def recognised(comp):
    try:
        t = _target(comp)
        return recognise(t.Shape, getattr(t, "Label", "") + " " + comp.Label) is not None
    except Exception:
        return False


def pick_hole(asm, link, info, pick=None, point=None):
    """(component, hole face) the fastener goes in: the face dropped on, else the nearest that fits."""
    holes = _holes(asm, link)
    if pick is not None:
        comp, sub = pick[0], str(pick[1]).split(".")[-1]
        for h in holes:
            if h[0] is comp and h[1] == sub:
                return h
    r = info["radius"]
    fits = [h for h in holes if FIT[0] * h[2] <= r <= FIT[1] * h[2]] if info["kind"] == "bolt" else \
        [h for h in holes if 0.85 * h[2] <= r <= 1.35 * h[2]]       # a ring's hole is the bolt's size
    if not fits:
        return None
    at = point if point is not None else link.Placement.Base

    def dist(h):
        d = at - h[3]
        return (d - h[4] * d.dot(h[4])).Length + abs(d.dot(h[4])) * 0.1
    return min(fits, key=dist)


def auto_mate(asm, link, pick=None, point=None):
    """Mates a dropped fastener into its hole. Returns the mates made ([] when it is not a
    fastener, has mates already, or no hole fits)."""
    from . import toolbox
    if asm is None or link is None or not enabled() or toolbox.is_fastener(link):
        return []
    for j in ac.mates(asm):
        for prop in ("Reference1", "Reference2"):
            ref = getattr(j, prop, None)
            if ref and ref[0] is link:
                return []           # mated already (a Mate Reference, SmartMates)
    t = _target(link)
    info = recognise(t.Shape, getattr(t, "Label", "") + " " + link.Label)
    if info is None:
        return []
    hole = pick_hole(asm, link, info, pick, point)
    if hole is None:
        return []
    st = toolbox.stack(asm, hole[0], hole[1])
    if st is None:
        return []
    seat = st["seat"]
    if info["kind"] == "nut" and st.get("exit"):
        seat = st["exit"]
    # put it in place first (seat on the seat, along the hole), then the mates hold it there
    try:
        on_far = seat is not st["seat"]
        want = -st["into"] if on_far else st["into"]
        n = App.Vector(info["seat_normal"])
        rot = App.Rotation(n, want)
        seat_face = toolbox.global_shape(seat[0]).getElement(seat[1])
        level = (seat_face.CenterOfMass - st["centre"]).dot(st["into"])
        centre = st["centre"] + st["into"] * level
        sc = t.Shape.getElement(info["seat"]).CenterOfMass
        c, a, _r = _axis(t.Shape.getElement(info["axis"]))
        on_axis = c + a * (sc - c).dot(a)
        link.Placement = App.Placement(centre - rot.multVec(on_axis), rot)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: fastener place: %s\n" % error)
    made = []
    j1 = toolbox._mate(asm, "Concentric", st["axis"], (link, info["axis"]))
    j2 = toolbox._mate(asm, "Coincident", seat, (link, info["seat"]))
    made = [j for j in (j1, j2) if j is not None]
    asm.Document.recompute()
    return made


def install():
    """Designs dropped from the Design Library or File Explorer go through designlib.insert."""
    try:
        from . import designlib
    except Exception:
        return
    if getattr(designlib, "_fw_fastmate", False):
        return
    insert0 = designlib.insert

    def insert(path, doc=None, pick=None, point=None, pm=True):
        out = insert0(path, doc, pick, point, pm)
        try:
            if out is not None and getattr(out, "TypeId", "") == "App::Link":
                asm = ac.assembly_of(out.Document)
                if asm is not None:
                    made = auto_mate(asm, out, pick, point)
                    if made:
                        App.Console.PrintMessage("FreeCAD: %s mated as a fastener (%s)\n" %
                                                 (out.Label, ", ".join(j.Label for j in made)))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: fastener mating: %s\n" % error)
        return out
    insert.__wrapped__ = insert0
    designlib.insert = insert
    designlib._fw_fastmate = True
