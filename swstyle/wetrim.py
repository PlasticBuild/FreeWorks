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
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, paths
from . import pmboxes

COMMAND = "SWStyle_WETrimExtend"
PREVIEW_PARAM = paths.PARAM_PATH + "/Weldments"
TITLE = "Trim/Extend"
LABEL = "Trim/Extend"
GROUP = "Trim/Extend"
CORNERS = ("End Trim", "End Miter", "End Butt1", "End Butt2")
BOUNDARY = ("Face / Plane", "Bodies")
CUTS = ("Simple cut", "Coped cut")
NOT_YET = "Not available: FrameForge has no equivalent yet"
TOL = 1e-6


def _weicon(name):
    from . import weprofile
    return weprofile.icon(name)



# ---------------------------------------------------------------- bodies
def is_trim_extend(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "TrimExtend"


def trim_extends(doc):
    return [o for o in doc.Objects if is_trim_extend(o)]


def chain(doc):
    """The weldment features that work on member bodies, in tree order: Trim/Extend, End Cap, Gusset,
    Weld Bead, Corner Management, Connection Element and its pattern."""
    return [o for o in doc.Objects
            if type(getattr(o, "Proxy", None)).__name__ in ("TrimExtend", "EndCap", "Gusset", "WeldBead",
                                                            "CornerManagement", "ConnectionElement",
                                                            "ConnectionPattern", "WeldmentCut", "WeldmentChamfer")]


def _outputs(te):
    try:
        return json.loads(te.Outputs or "{}")
    except Exception:
        return {}


def member_tip(doc, ref):
    name, _sep, k = ref.rpartition(":")
    sm = doc.getObject(name)
    try:
        return sm.Bodies[int(k)]
    except Exception:
        return None


def current_tip(doc, ref, before=None):
    """The body's newest shape: the Structural Member's, or the last Trim/Extend's (or End Cap's)
    before `before`."""
    tip = member_tip(doc, ref)
    for te in chain(doc):
        if te is before:
            break
        name = _outputs(te).get(ref)
        if name and doc.getObject(name) is not None:
            tip = doc.getObject(name)
    return tip


def ref_of(obj):
    """The body reference of a member body (any shape in its chain), else None."""
    if obj is None:
        return None
    doc = obj.Document
    from . import wemember
    for sm in doc.Objects:
        if not wemember.is_structural_member(sm):
            continue
        for k, b in enumerate(sm.Bodies):
            ref = "%s:%d" % (sm.Name, k)
            if b is obj or current_tip(doc, ref) is obj:
                return ref
    for te in chain(doc):
        for ref, name in _outputs(te).items():
            if name == obj.Name:
                return ref
    # a body picked in the view can be another link of the member's chain (the corner trim FrameForge
    # made, or the bare profile under it): the member whose body grows from the same profile
    base = base_of(obj)
    if base is not None:
        for sm in doc.Objects:
            if not wemember.is_structural_member(sm):
                continue
            for k, b in enumerate(sm.Bodies):
                if base_of(b) is base:
                    return "%s:%d" % (sm.Name, k)
    return None


def base_of(obj):
    """The FrameForge Profile under a trimmed body."""
    while obj is not None and not hasattr(obj, "Target"):
        obj = getattr(obj, "TrimmedBody", None)
    return obj


def line_of(base):
    edge = base.Target[0].getSubObject(base.Target[1][0])
    return edge.Vertexes[0].Point, edge.Vertexes[-1].Point


def _margin(base):
    return 2 * max(getattr(base, "ProfileWidth", 0.0), getattr(base, "ProfileHeight", 0.0), 1.0)


def _extend(base, end, length):
    """Lengthens a member at an end (0 start, 1 end) to at least length past its path."""
    prop = "OffsetA" if end == 1 else "OffsetB"     # FrameForge: OffsetA = path end, OffsetB = start
    if getattr(base, prop) < length - TOL:
        setattr(base, prop, length)


def closest(a0, a1, b0, b1):
    """The point midway between the closest points of two lines (None when parallel)."""
    d1, d2 = a1 - a0, b1 - b0
    w = a0 - b0
    a, b, c, d, e = d1.dot(d1), d1.dot(d2), d2.dot(d2), d1.dot(w), d2.dot(w)
    den = a * c - b * b
    if abs(den) < 1e-12 * a * c:
        return None
    s = (b * e - c * d) / den
    t = (a * e - b * d) / den
    return (a0 + d1 * s + b0 + d2 * t) * 0.5


def _crosses(body, plane):
    """True when the trim plane cuts through the body (else FrameForge has nothing to cut)."""
    try:
        f = plane.Shape.Faces[0]
        n, p = f.normalAt(0, 0), f.Vertexes[0].Point
        d = [(v.Point - p).dot(n) for v in body.Shape.Vertexes]
        return min(d) < -TOL and max(d) > TOL
    except Exception:
        return False


def _meets(a, b):
    """True when the two bodies share volume (FrameForge's Perfect fit needs a cut)."""
    try:
        return a.Shape.common(b.Shape).Volume > 1e-6
    except Exception:
        return False


def _meets_on_path(body, other, end):
    """True when body's path, going to its end (0 start, 1 end), runs into one of other's faces itself (not
    only into a face's infinite plane)."""
    base = base_of(body)
    if base is None or other is None:
        return False
    p0, p1 = line_of(base)
    start, u = (p0, (p1 - p0).normalize()) if end == 1 else (p1, (p0 - p1).normalize())
    try:
        return bool(_hits(other.Shape, start, u, True))
    except Exception:
        return False


def _near_end(p0, p1, point):
    return 1 if (p1 - point).Length < (p0 - point).Length else 0


# ---------------------------------------------------------------- the trim plane
class TrimPlane:
    """A planar face the trims cut at. Kind plane: a face or plane (Source); miter: the bisector of
    members A and B at their corner; near/far: the face of Body the member Trimmed meets first/last
    going to its End; first: square to Trimmed where its profile first touches that near face (Corner
    Management's First contact)."""

    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "Kind", GROUP, "plane, miter, near or far")
        add("App::PropertyLinkSubGlobal", "Source", GROUP, "Face or plane")
        add("App::PropertyLink", "A", GROUP, "First member (miter)")
        add("App::PropertyLink", "B", GROUP, "Second member (miter)")
        add("App::PropertyLink", "Body", GROUP, "Boundary body (near, far)")
        add("App::PropertyLink", "Trimmed", GROUP, "Trimmed member (near, far)")
        add("App::PropertyInteger", "End", GROUP, "Trimmed member's end: 0 start, 1 end")
        add("App::PropertyBool", "Unbounded", GROUP, "The face counts as infinite (allow extension)")
        add("App::PropertyDistance", "Offset", GROUP, "endface: distance in from the end face")
        add("App::PropertyDistance", "Gap", GROUP, "Weld gap: the plane moves this far back into Keep")
        add("App::PropertyLink", "Keep", GROUP, "The member the gap leaves room on (it is trimmed shorter)")
        add("App::PropertyBool", "UseThrough", GROUP, "miter: the plane passes through Through, not the corner")
        add("App::PropertyVector", "Through", GROUP, "miter: a point the miter plane passes through (Complex corner)")
        obj.Proxy = self

    def execute(self, obj):
        plane = plane_of(obj)
        if plane is None:
            raise RuntimeError("Trim/Extend: no trimming plane")
        point, normal = plane
        gap = float(getattr(obj, "Gap", 0) or 0)
        keep = base_of(getattr(obj, "Keep", None))
        if gap > TOL and keep is not None:
            k0, k1 = line_of(keep)
            far = k0 if (k0 - point).Length > (k1 - point).Length else k1     # the kept end of the member
            point = point + normal * (gap if normal.dot(far - point) > 0 else -gap)
        size = 1000.0
        x = normal.cross(App.Vector(0, 0, 1))
        if x.Length < 1e-6:
            x = normal.cross(App.Vector(1, 0, 0))
        x.normalize()
        y = normal.cross(x)
        corner = point - x * (size / 2) - y * (size / 2)
        obj.Shape = Part.Face(Part.makePolygon([corner, corner + x * size, corner + x * size + y * size,
                                                corner + y * size, corner]))

    def dumps(self):
        return None

    def loads(self, state):
        return None


def source_plane(obj, sub):
    """(point, normal) of a planar face or a plane."""
    if obj is None:
        return None
    if obj.TypeId == "App::Plane" or (not sub and not hasattr(obj, "Shape")):
        pl = obj.getGlobalPlacement()
        return pl.Base, pl.Rotation.multVec(App.Vector(0, 0, 1))
    shape = obj.getSubObject(sub) if sub else obj.Shape
    faces = shape.Faces if shape is not None else []
    if not faces or faces[0].Surface.TypeId != "Part::GeomPlane":
        return None
    f = faces[0]
    return f.CenterOfMass, f.normalAt(0, 0)


def _hits(shape, start, u, bounded):
    """(t, face) for the planar faces of shape across the line start + t u, t > 0."""
    out = []
    for f in shape.Faces:
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        n = f.normalAt(0, 0)
        if abs(n.dot(u)) < 0.1:         # 0.3 missed a brace at 17 degrees meeting a rail's top face (wf gate frame)
            continue
        t = (f.CenterOfMass - start).dot(n) / u.dot(n)
        if t <= TOL:
            continue
        if bounded:
            p = start + u * t
            bb = f.BoundBox
            bb.enlarge(1e-3)
            if not bb.isInside(p) or f.distToShape(Part.Vertex(p))[0] > 1e-3:
                continue
        out.append((t, f))
    return sorted(out, key=lambda x: x[0])


def plane_of(tp):
    kind = tp.Kind
    if kind == "plane":
        src = tp.Source
        if not src:
            return None
        return source_plane(src[0], src[1][0] if src[1] else "")
    if kind == "miter":
        a, b = base_of(tp.A), base_of(tp.B)
        if a is None or b is None:
            return None
        a0, a1 = line_of(a)
        b0, b1 = line_of(b)
        p = closest(a0, a1, b0, b1)
        if p is None:
            return None
        ua = ((a0 if (a0 - p).Length > (a1 - p).Length else a1) - p).normalize()
        ub = ((b0 if (b0 - p).Length > (b1 - p).Length else b1) - p).normalize()
        n = ua - ub
        if n.Length < 1e-9:
            return None
        if getattr(tp, "UseThrough", False):
            p = App.Vector(tp.Through)
        return p, n.normalize()
    if kind == "endface":
        f, u = end_face(tp.Body, tp.End)
        if f is None:
            return None
        n = f.normalAt(0, 0)
        if n.dot(u) < 0:
            n = -n
        return f.CenterOfMass - n * float(getattr(tp, "Offset", 0)), n
    if kind in ("near", "first", "far"):
        base = base_of(tp.Trimmed)
        if base is None or tp.Body is None:
            return None
        p0, p1 = line_of(base)
        start, end = (p0, p1) if tp.End == 1 else (p1, p0)
        u = (end - start).normalize()
        if kind == "far":                   # the outer face across the path (End Butt's through member)
            faces = [(f.CenterOfMass - start).dot(u) for f in tp.Body.Shape.Faces
                     if f.Surface.TypeId == "Part::GeomPlane" and abs(abs(f.normalAt(0, 0).dot(u)) - 1) < 1e-6]
            if not faces:
                return None
            return start + u * max(faces), u
        # a face the path really goes through comes first; the faces' infinite planes only when it meets
        # none (Allow extension). Taken unbounded first, the mitred top face of a leg (at 45 degrees) cut a
        # crossbar halfway along (pkg123 weld session: 230..500 instead of 20..380)
        hits = _hits(tp.Body.Shape, start, u, True)
        if not hits and tp.Unbounded:
            hits = _hits(tp.Body.Shape, start, u, False)
        if not hits:
            return None
        t, f = hits[0]
        n = f.normalAt(0, 0)
        # a tube's outer wall before its inner one: the path can slip past the outer face (beside a mitred
        # end) and first meet the inner wall, which left the brace inside the post (wf gate frame diagonal)
        for t2, f2 in _hits(tp.Body.Shape, start, u, False):
            if t2 < t - TOL and abs(abs(f2.normalAt(0, 0).dot(n)) - 1) < 1e-6:
                t, f = t2, f2
                break
        n = f.normalAt(0, 0)
        if kind == "first":
            # each point r of the profile (across the path) meets the face at t - r.n / u.n
            pts = [q for e in base.Shape.Edges for q in e.discretize(8)]       # round profiles have few vertexes
            rs = [(q - start) - u * (q - start).dot(u) for q in pts]
            t = min([t - r.dot(n) / u.dot(n) for r in rs] or [t])
            return start + u * t, u
        return start + u * t, n
    return None


def end_face(body, end):
    """(the planar face at a member body's end, the path's outward direction there)."""
    base = base_of(body)
    if base is None or body is None:
        return None, None
    p0, p1 = line_of(base)
    e, u = (p1, (p1 - p0).normalize()) if end == 1 else (p0, (p0 - p1).normalize())
    best, best_d = None, None
    for f in body.Shape.Faces:
        if f.Surface.TypeId != "Part::GeomPlane" or abs(f.normalAt(0, 0).dot(u)) < 0.3:
            continue
        d = (f.CenterOfMass - e).dot(u)
        if best_d is None or d > best_d + TOL or (abs(d - best_d) <= TOL and f.Area > best.Area):
            best, best_d = f, d
    return best, u


def _trim_plane(doc, kind, **links):
    obj = doc.addObject("Part::FeaturePython", "TrimPlane")
    TrimPlane(obj)
    obj.Kind = kind
    for k, v in links.items():
        setattr(obj, k, v)
    if App.GuiUp:
        obj.ViewObject.Proxy = 0
        obj.ViewObject.Visibility = False
    return obj


def _trim(doc, body, boundary, kind="End Trim", cut="Simple fit"):
    from . import wemember
    return wemember._trim(doc, body, boundary, kind, cut)


# ---------------------------------------------------------------- the feature
class TrimExtend:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "CornerType", GROUP, "End Trim, End Miter, End Butt1 or End Butt2")
        add("App::PropertyString", "Trimmed", GROUP, "Bodies to be trimmed (JSON)")
        add("App::PropertyString", "BoundaryType", GROUP, "Face / Plane or Bodies")
        add("App::PropertyString", "Boundary", GROUP, "Trimming boundary (JSON)")
        add("App::PropertyBool", "ExtendTrimmed", GROUP, "Allow extension of the trimmed bodies")
        add("App::PropertyBool", "ExtendBoundary", GROUP, "Allow extension of the trimming boundary")
        add("App::PropertyString", "Cut", GROUP, "Simple cut or Coped cut")
        add("App::PropertyLinkList", "Created", GROUP, "Objects made by this feature")
        add("App::PropertyString", "Outputs", GROUP, "Newest shape of each trimmed body (JSON)")
        _gap_props(obj)
        for name in ("Trimmed", "Boundary", "Created", "Outputs"):
            obj.setEditorMode(name, 2)
        obj.CornerType = "End Trim"
        obj.BoundaryType = "Face / Plane"
        obj.ExtendTrimmed = True
        obj.ExtendBoundary = True
        obj.Cut = "Simple cut"
        obj.Trimmed = obj.Boundary = "[]"
        obj.Outputs = "{}"
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _load(text, default):
    try:
        return json.loads(text or "")
    except Exception:
        return default


def clear(te):
    doc = te.Document
    for o in reversed(list(te.Created)):
        try:
            doc.removeObject(o.Name)
        except Exception as _fw_err:
            _fw_log("wetrim.py:426", _fw_err)
    te.Created = []
    te.Outputs = "{}"


def clear_all(doc):
    for te in reversed(chain(doc)):
        clear(te)


def _gap_props(obj):
    if "WeldGap" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "WeldGap", GROUP, "Weld gap: leave a gap at the trim")
        obj.addProperty("App::PropertyDistance", "TrimGap", GROUP, "Weld gap size")
        obj.TrimGap = 1.0


def build(te):
    """Makes te's trims on the bodies' current shapes."""
    doc = te.Document
    _gap_props(te)
    trimmed = _load(te.Trimmed, [])
    boundary = _load(te.Boundary, [])
    created, outputs = [], {}

    def tip(ref):
        return doc.getObject(outputs[ref]) if ref in outputs else current_tip(doc, ref, te)

    def add(ref, obj):
        created.append(obj)
        outputs[ref] = obj.Name

    apply(doc, tip, add, created, te.CornerType, trimmed, boundary, te.ExtendTrimmed, te.ExtendBoundary, te.Cut,
          gap=float(te.TrimGap) if te.WeldGap else 0.0)
    te.Created = created
    te.Outputs = json.dumps(outputs)
    if App.GuiUp:
        for o in created:
            try:
                o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("wetrim.py:467", _fw_err)


def apply(doc, tip, add, created, corner, trimmed, boundary, extend_trimmed=True, extend_boundary=True,
          cut="Simple cut", ends=None, butt_cut="Simple cut", gap=0.0, contact="Full contact", through=None):
    """Trims the bodies trimmed (refs) at a corner: End Trim to faces, planes or bodies (boundary), or
    End Miter / End Butt1 / End Butt2 with the first boundary body. tip(ref) gives a body's newest shape,
    add(ref, obj) records a trim; helper objects go in created. ends ({ref: 0 or 1}) says which end of a body
    an End Trim cuts (else the end nearer the boundary body); butt_cut "Coped cut" fits End Butt's butting
    member to the other's shape; gap (Weld gap) leaves that much room before the boundary (split between the
    two at a miter); contact "First contact" cuts a planar trim square to the member where it first touches
    the other (else flush with its face). Shared by Trim/Extend and Corner Management."""
    near = "first" if contact == "First contact" else "near"
    if corner == "End Trim":
        def end_for(ref, body, p0, p1, other):
            end = (ends or {}).get(ref)
            return _near_end(p0, p1, other.Shape.BoundBox.Center) if end is None else end
        for ref in trimmed:

            # through a face's extended plane counts only when nothing at that end is really met (else a
            # crossmember between two posts was cut by the mitred ends of the top and bottom rails:
            # 230..570 instead of 20..780, and a diagonal brace cut at mid-length)
            met = set()
            body0 = tip(ref)
            base0 = base_of(body0)
            if body0 is not None and base0 is not None:
                q0, q1 = line_of(base0)
                for b in boundary:
                    if b.get("kind") == "body" and b["ref"] != ref:
                        other = tip(b["ref"])
                        if other is not None:
                            e = end_for(ref, body0, q0, q1, other)
                            if _meets_on_path(body0, other, e):
                                met.add(e)
            for b in boundary:
                body = tip(ref)
                base = base_of(body)
                if body is None or base is None:
                    continue
                p0, p1 = line_of(base)
                if b.get("kind") == "body":
                    other = tip(b["ref"])
                    if other is None or b["ref"] == ref:
                        continue
                    end = end_for(ref, body, p0, p1, other)
                    if end in met and not _meets_on_path(body, other, end):
                        continue
                    if extend_trimmed:
                        u = ((p1 - p0) if end == 1 else (p0 - p1)).normalize()
                        e = p1 if end == 1 else p0
                        reach = max((v.Point - e).dot(u) for v in other.Shape.Vertexes)
                        if reach > 0:
                            _extend(base, end, reach + _margin(base))
                            doc.recompute([base])
                    if cut == "Coped cut":
                        if _meets(base, other):
                            add(ref, _trim(doc, body, [(other, ["Face1"])], "End Trim", "Perfect fit"))
                        continue
                    tp = _trim_plane(doc, near, Body=other, Trimmed=body, End=end, Unbounded=extend_boundary,
                                     Gap=gap, Keep=body)
                    if plane_of(tp) is None:        # the member never meets that body: nothing to trim at
                        doc.removeObject(tp.Name)
                        continue
                else:
                    obj = doc.getObject(b.get("obj", ""))
                    plane = source_plane(obj, b.get("sub", ""))
                    if plane is None:
                        continue
                    point, n = plane
                    d = (p1 - p0)
                    length = d.Length
                    u = d.normalize()
                    if abs(n.dot(u)) < 1e-9:
                        continue
                    t = (point - p0).dot(n) / u.dot(n)
                    end = 1 if t > length / 2 else 0
                    beyond = t - length if end == 1 else -t
                    if beyond > -TOL:
                        if not extend_trimmed:
                            continue
                        _extend(base, end, beyond + _margin(base))
                        doc.recompute([base])
                    tp = _trim_plane(doc, "plane", Source=(obj, [b.get("sub", "")]), Gap=gap, Keep=body)
                created.append(tp)
                doc.recompute()
                if _crosses(body, tp):
                    add(ref, _trim(doc, body, [(tp, ["Face1"])], "End Trim", "Simple fit"))
    elif trimmed and boundary and boundary[0].get("kind") == "body":
        ra, rb = trimmed[0], boundary[0]["ref"]
        a, b = tip(ra), tip(rb)
        ba, bb = base_of(a), base_of(b)
        if None not in (a, b, ba, bb) and ra != rb:
            a0, a1 = line_of(ba)
            b0, b1 = line_of(bb)
            p = closest(a0, a1, b0, b1)
            if p is not None:
                ea, eb = _near_end(a0, a1, p), _near_end(b0, b1, p)
                if corner == "End Miter":
                    reach = [p] + ([App.Vector(through)] if through is not None else [])
                    for base, (q0, q1), end in ((ba, (a0, a1), ea), (bb, (b0, b1), eb)):
                        e, u = (q1, q1 - q0) if end == 1 else (q0, q0 - q1)
                        _extend(base, end, max(0.0, max((x - e).dot(u.normalize()) for x in reach)) + _margin(base))
                    doc.recompute([ba, bb])
                    pt = {"UseThrough": True, "Through": App.Vector(through)} if through is not None else {}
                    ta = _trim_plane(doc, "miter", A=a, B=b, Gap=gap / 2, Keep=a, **pt)
                    tb = _trim_plane(doc, "miter", A=a, B=b, Gap=gap / 2, Keep=b, **pt) if gap > TOL else ta
                    created.extend([ta] if tb is ta else [ta, tb])
                    doc.recompute([ta, tb])
                    add(ra, _trim(doc, a, [(ta, ["Face1"])], "End Trim", "Simple fit"))
                    add(rb, _trim(doc, b, [(tb, ["Face1"])], "End Trim", "Simple fit"))
                else:
                    through, butt = ((ra, a, ba, (a0, a1), ea), (rb, b, bb, (b0, b1), eb)) \
                        if corner == "End Butt1" else ((rb, b, bb, (b0, b1), eb), (ra, a, ba, (a0, a1), ea))
                    rt, t_obj, t_base, (q0, q1), end = through
                    e, u = (q1, q1 - q0) if end == 1 else (q0, q0 - q1)
                    _extend(t_base, end, max(0.0, (p - e).dot(u.normalize())) + _margin(t_base))
                    _r, _o, b_base, (q0, q1), b_end = butt       # the butting member reaches into the other
                    e, u = (q1, q1 - q0) if b_end == 1 else (q0, q0 - q1)
                    _extend(b_base, b_end, max(0.0, (p - e).dot(u.normalize())))
                    doc.recompute([t_base, b_base])
                    tp = _trim_plane(doc, "far", Body=butt[1], Trimmed=t_obj, End=end)
                    created.append(tp)
                    doc.recompute([tp])
                    add(rt, _trim(doc, t_obj, [(tp, ["Face1"])], "End Trim", "Simple fit"))
                    doc.recompute()
                    if butt_cut == "Coped cut":
                        through_tip = tip(rt)
                        if _meets(butt[1], through_tip):
                            add(butt[0], _trim(doc, butt[1], [(through_tip, ["Face1"])], "End Trim", "Perfect fit"))
                        return
                    tb = _trim_plane(doc, near, Body=t_base, Trimmed=butt[1], End=b_end, Unbounded=True,
                                     Gap=gap, Keep=butt[1])
                    created.append(tb)
                    doc.recompute([tb])
                    if _crosses(butt[1], tb):
                        add(butt[0], _trim(doc, butt[1], [(tb, ["Face1"])], "End Trim", "Simple fit"))


def build_all(doc):
    from . import wechamfer, wecut, weconnection, wecorner, weendcap, wegusset, weweld
    builders = {"WeldmentCut": wecut.build, "WeldmentChamfer": wechamfer.build, "TrimExtend": build, "EndCap": weendcap.build, "Gusset": wegusset.build, "WeldBead": weweld.build,
                "CornerManagement": wecorner.build, "ConnectionElement": weconnection.build,
                "ConnectionPattern": weconnection.build_pattern}
    for te in chain(doc):
        builders[type(te.Proxy).__name__](te)
        doc.recompute()


class ViewProviderTrimExtend:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        from . import wemember
        wemember._empty_mode(vobj)

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        try:
            return _weicon("trim_extend.svg")
        except Exception:
            return ""

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + TITLE)
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

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        doc = obj.Document
        clear(obj)
        QtCore.QTimer.singleShot(0, lambda: _refresh_later(doc))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _refresh_later(doc):
    from . import wemember
    try:
        wemember.refresh(doc)
    except Exception as error:
        App.Console.PrintError("Trim/Extend: %s\n" % error)


def make(doc):
    obj = doc.addObject("App::FeaturePython", "TrimExtend")
    TrimExtend(obj)
    if App.GuiUp:
        ViewProviderTrimExtend(obj.ViewObject)
    obj.Label = naming.next_label(doc, LABEL)
    return obj


# ---------------------------------------------------------------- PropertyManager
def _box(title):
    box = QtWidgets.QWidget()
    box.setWindowTitle(title)
    QtWidgets.QFormLayout(box)
    return box


class _Keys(QtCore.QObject):
    def __init__(self, panel, which):
        super().__init__()
        self.panel, self.which = panel, which

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.FocusIn:
            self.panel.set_active(self.which)
        elif event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Delete:
            self.panel.remove_current(self.which)
            return True
        return False


class Panel:
    def __init__(self, obj, new):
        self.obj = obj
        self.new = new
        self.busy = True
        self.trimmed = _load(obj.Trimmed, [])
        self.boundary = _load(obj.Boundary, [])
        self.active = "trimmed"
        self._filters = []

        corner_box = _box("Corner Type")
        row = QtWidgets.QHBoxLayout()
        self.corners = QtWidgets.QButtonGroup(corner_box)
        for i, text in enumerate(CORNERS):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWWETrim" + text.replace(" ", ""))
            b.setText(text)
            b.setToolTip(text)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setChecked(text == obj.CornerType)
            from . import pmpics
            pmpics.picture(b, "corner", text)
            self.corners.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        corner_box.layout().addRow(row)

        trimmed_box = _box("Bodies to Be Trimmed")
        f = trimmed_box.layout()
        self.trimmed_list = QtWidgets.QListWidget()
        self.trimmed_list.setObjectName("SWWETrimBodies")
        self.trimmed_list.setMaximumHeight(70)
        f.addRow(self.trimmed_list)
        self.extend_trimmed = QtWidgets.QCheckBox("Allow extension")
        self.extend_trimmed.setObjectName("SWWETrimExtendBodies")
        self.extend_trimmed.setChecked(obj.ExtendTrimmed)
        f.addRow(self.extend_trimmed)

        boundary_box = _box("Trimming Boundary")
        f = boundary_box.layout()
        self.kinds = QtWidgets.QButtonGroup(boundary_box)
        row = QtWidgets.QHBoxLayout()
        for i, text in enumerate(BOUNDARY):
            b = QtWidgets.QRadioButton(text)
            b.setObjectName("SWWETrimBoundary" + ("Face" if i == 0 else "Bodies"))
            b.setChecked(text == obj.BoundaryType)
            self.kinds.addButton(b, i)
            row.addWidget(b)
        self.kind_row = QtWidgets.QWidget()
        self.kind_row.setLayout(row)
        f.addRow(self.kind_row)
        self.boundary_list = QtWidgets.QListWidget()
        self.boundary_list.setObjectName("SWWETrimBoundaryList")
        self.boundary_list.setMaximumHeight(70)
        f.addRow(self.boundary_list)
        self.extend_boundary = QtWidgets.QCheckBox("Allow extension")
        self.extend_boundary.setObjectName("SWWETrimExtendBoundary")
        self.extend_boundary.setChecked(obj.ExtendBoundary)
        f.addRow(self.extend_boundary)
        self.cuts = QtWidgets.QButtonGroup(boundary_box)
        row = QtWidgets.QHBoxLayout()
        for i, text in enumerate(CUTS):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWWETrim" + text.replace(" ", ""))
            b.setText(text)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setChecked(text == obj.Cut)
            self.cuts.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        self.cut_row = QtWidgets.QWidget()
        self.cut_row.setLayout(row)
        f.addRow(self.cut_row)
        _gap_props(obj)
        self.gap = QtWidgets.QCheckBox("Weld gap")
        self.gap.setObjectName("SWWETrimGap")
        self.gap.setChecked(bool(obj.WeldGap))
        f.addRow(self.gap)
        self.gap_size = QtWidgets.QDoubleSpinBox()
        self.gap_size.setObjectName("SWWETrimGapSize")
        self.gap_size.setRange(0.0, 1000.0)
        self.gap_size.setDecimals(2)
        self.gap_size.setSuffix(" mm")
        self.gap_size.setToolTip("Trim gap")
        self.gap_size.setValue(float(obj.TrimGap))
        self.gap_size.setVisible(bool(obj.WeldGap))
        f.addRow(self.gap_size)

        self.preview = QtWidgets.QCheckBox("Preview")
        self.preview.setObjectName("SWWETrimPreview")
        self.preview.setChecked(App.ParamGet(PREVIEW_PARAM).GetBool("TrimExtendPreview", True))
        f.addRow(self.preview)
        self.pending = False
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("SWWETrimError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        from . import pickprompt
        pickprompt.style(self.error)     # look audit AI1: the start prompt in the yellow box
        self.error.hide()
        f.addRow(self.error)

        for w in (corner_box, trimmed_box, boundary_box):
            w.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        corner_box.setProperty("swstyle_pm_title", TITLE)
        corner_box.setProperty("swstyle_pm_icon", "FrameForge_TrimProfiles")
        self.form = [corner_box, trimmed_box, boundary_box]
        for which, w in (("trimmed", self.trimmed_list), ("boundary", self.boundary_list)):
            k = _Keys(self, which)
            self._filters.append(k)
            w.installEventFilter(k)
        self._show()

        self.corners.buttonClicked.connect(self._changed)
        self.kinds.buttonClicked.connect(self._kind_changed)
        self.cuts.buttonClicked.connect(self._changed)
        self.extend_trimmed.toggled.connect(self._changed)
        self.extend_boundary.toggled.connect(self._changed)
        self.gap.toggled.connect(self._changed)
        self.gap_size.valueChanged.connect(self._changed)
        self.preview.toggled.connect(self._preview_toggled)
        self.busy = False
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ---------------------------------------------------------------- state
    def corner(self):
        return CORNERS[max(0, self.corners.checkedId())]

    def kind(self):
        if self.corner() != "End Trim":
            return "Bodies"
        return BOUNDARY[max(0, self.kinds.checkedId())]

    def set_active(self, which):
        self.active = which
        for name, w in (("trimmed", self.trimmed_list), ("boundary", self.boundary_list)):
            pmboxes.mark(w, name == which)

    def _label(self, item):
        doc = self.obj.Document
        if isinstance(item, str) or item.get("kind") == "body":
            ref = item if isinstance(item, str) else item["ref"]
            tip = current_tip(doc, ref)
            return tip.Label if tip is not None else ref
        obj = doc.getObject(item.get("obj", ""))
        label = obj.Label if obj is not None else item.get("obj", "")
        return "%s@%s" % (item["sub"], label) if item.get("sub") else label

    def _show(self):
        busy, self.busy = self.busy, True
        single = self.corner() != "End Trim"
        self.kind_row.setVisible(not single)
        self.cut_row.setVisible(not single and self.kind() == "Bodies")
        self.extend_boundary.setVisible(not single)
        self.trimmed_list.clear()
        for ref in self.trimmed:
            self.trimmed_list.addItem(self._label(ref))
        self.boundary_list.clear()
        for item in self.boundary:
            self.boundary_list.addItem(self._label(item))
        self.set_active(self.active)
        self.busy = busy

    def _kind_changed(self, *args):
        if self.busy:
            return
        self.boundary = []
        self._changed()

    def _changed(self, *args):
        if self.busy:
            return
        obj = self.obj
        single = self.corner() != "End Trim"
        if single:
            self.trimmed = self.trimmed[-1:]
            self.boundary = [b for b in self.boundary if b.get("kind") == "body"][-1:]
        obj.CornerType = self.corner()
        obj.BoundaryType = self.kind()
        obj.Cut = CUTS[max(0, self.cuts.checkedId())]
        obj.ExtendTrimmed = self.extend_trimmed.isChecked()
        obj.ExtendBoundary = self.extend_boundary.isChecked()
        obj.WeldGap = self.gap.isChecked()
        obj.TrimGap = self.gap_size.value()
        self.gap_size.setVisible(obj.WeldGap)
        obj.Trimmed = json.dumps(self.trimmed)
        obj.Boundary = json.dumps(self.boundary)
        self._show()
        if not self.preview.isChecked():
            self.pending = True              # Preview off: the members are trimmed at OK
            return
        self._rebuild()

    def _rebuild(self):
        from . import wemember
        self.pending = False
        try:
            wemember.refresh(self.obj.Document)
            self.error.hide()
            return True
        except Exception as error:
            self.error.setText(str(error))
            self.error.show()
            return False

    def _preview_toggled(self, on):
        App.ParamGet(PREVIEW_PARAM).SetBool("TrimExtendPreview", bool(on))
        if on and self.pending:
            self._rebuild()

    # ---------------------------------------------------------------- selection
    def addSelection(self, doc, name, sub, point):
        # a PropertyManager closed without its own close (Esc through the PM keys) must not keep
        # clearing every pick in the view
        try:
            from .widgets import alive
            forms = self.form if isinstance(self.form, (list, tuple)) else [self.form]
            if not (Gui.Control.activeDialog() and any(alive(f) and _in_tasks(f) for f in forms)):
                Gui.Selection.removeObserver(self)
                return
        except Exception:
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("wetrim.py:889", _fw_err)
            return
        from . import safe_later as _sl; _sl.later(0, lambda: self._picked(doc, name, sub), self, "error")

    def _picked(self, doc_name, name, sub):
        # The panel can close between addSelection and this queued callback. Recheck before touching
        # selection or the model, and fail closed if the Qt wrapper is already gone.
        try:
            from .widgets import alive
            forms = self.form if isinstance(self.form, (list, tuple)) else [self.form]
            if not (Gui.Control.activeDialog() and any(alive(f) and _in_tasks(f) for f in forms)):
                Gui.Selection.removeObserver(self)
                return
        except Exception:
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("wetrim.py:906", _fw_err)
            return
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("wetrim.py:911", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        ref = ref_of(picked)
        if ref is None:
            App.Console.PrintLog("FreeCAD Trim/Extend: %s (%s) is not a member body\n" % (picked.Label, picked.TypeId))
        if self.active == "trimmed":
            if ref is None or ref in self.trimmed:
                return
            if self.corner() != "End Trim":
                self.trimmed = []
            self.trimmed.append(ref)

            # box is clicked; End Miter / End Butt take one body, then go on to the boundary
            if self.corner() != "End Trim":
                self.set_active("boundary")
        else:
            if ref is not None:
                item = {"kind": "body", "ref": ref}
                if self.kind() == "Face / Plane" and self.corner() == "End Trim":
                    self.kinds.button(1).setChecked(True)      # a member's face trims as a body
                    self.boundary = [b for b in self.boundary if b.get("kind") == "body"]
            else:
                if self.corner() != "End Trim" or self.kind() == "Bodies":
                    return
                if source_plane(picked, sub) is None:
                    self.error.setText("The trim boundary must be a planar face or a plane.")      # an error: red (reviewer 418)
                    self.error.show()
                    return
                item = {"kind": "face", "obj": picked.Name, "sub": sub}
            if item in self.boundary:
                return
            if self.corner() != "End Trim":
                self.boundary = []
            self.boundary.append(item)
        self._changed()

    def remove_current(self, which):
        lst, items = (self.trimmed_list, self.trimmed) if which == "trimmed" else (self.boundary_list, self.boundary)
        row = lst.currentRow()
        if row < 0:
            return
        del items[row]
        self._changed()

    # ---------------------------------------------------------------- closing
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("wetrim.py:963", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("wetrim.py:969", _fw_err)

    def accept(self):
        if not self.trimmed or not self.boundary:
            self.error.setText("Select the bodies to be trimmed and the trimming boundary.")
            self.error.show()
            return False
        if self.pending and not self._rebuild():
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        doc.recompute()
        self._close()
        return True


def start():
    doc = App.ActiveDocument
    if doc is None:
        return
    picked = [ref_of(s.Object) for s in Gui.Selection.getSelectionEx()]
    doc.openTransaction(TITLE)
    try:
        obj = make(doc)
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    refs = [r for r in picked if r]
    if refs:
        panel.trimmed = refs
        panel.set_active("boundary")
        panel._changed()


def _has_members():
    doc = App.ActiveDocument
    if doc is None:
        return False
    from . import wemember
    return any(wemember.is_structural_member(o) for o in doc.Objects)


def weldment_ready():
    ""

    if _has_members():
        return True
    doc = App.ActiveDocument
    try:
        from . import wemember
        return doc is not None and wemember.weldment(doc, create=False) is not None
    except Exception:
        return False


def need_members(title):
    """a42: True when there are members to work on; else the status bar and a note say to add one first."""
    if _has_members():
        return True
    text = "%s: there are no structural members yet. Add one with Structural Member first." % title
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 8000)
        # features-420 (look audit AO7): the page opens with the yellow Message saying what is needed,

        if not Gui.Control.activeDialog():
            Gui.Control.showDialog(_NeedMembersPage(title))
    except Exception:
        App.Console.PrintMessage(text + "\n")
    return False


class _NeedMembersPage:
    """Message page: this weldment tool works on structural members; start one here."""

    def __init__(self, title):
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Message")
        self.form.setProperty("swstyle_pm_title", title)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        text = QtWidgets.QLabel("%s works on structural members, and the part has none yet. Add one with "
                                "Structural Member, then use %s on it." % (title, title))
        text.setObjectName("SWNeedMembersMessage")
        text.setWordWrap(True)
        text.setProperty("swMessage", "info")       # the yellow message box (pickprompt), not red error text
        text.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        lay.addWidget(text)
        b = QtWidgets.QPushButton("Structural Member")
        b.setObjectName("SWNeedMembersStart")
        b.clicked.connect(self._start)
        lay.addWidget(b)
        lay.addStretch(1)

    def _start(self):
        Gui.Control.closeDialog()
        listed = set(Gui.listCommands())
        name = next((n for n in ("SWStyle_WEStructuralMember", "FrameForge_CreateProfiles") if n in listed), None)
        if name:
            QtCore.QTimer.singleShot(200, lambda: Gui.runCommand(name, 0))

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Cancel    # sketchfirst-1126

    def reject(self):
        Gui.Control.closeDialog()
        return True


class Command:
    def GetResources(self):
        try:
            pixmap = _weicon("trim_extend.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Trim/Extend",
                "ToolTip": "Trims or extends members against other members or faces."}

    def IsActive(self):
        if not weldment_ready():
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        if not need_members("Trim/Extend"):
            return
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())


def _in_tasks(w):
    """The form still sits in FreeCAD's task view: shown, or hidden behind the FeatureManager tab."""
    try:
        p = w
        while p is not None:
            if p.metaObject().className() in ("Gui::TaskView::TaskView", "Gui::TaskView::TaskBox"):
                return True
            p = p.parentWidget()
    except (RuntimeError, AttributeError):
        return False
    return False
