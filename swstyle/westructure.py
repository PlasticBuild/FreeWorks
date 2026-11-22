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

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, wemember
from . import pmboxes

SYSTEM_COMMAND = "SWStyle_WEStructureSystem"
PRIMARY_COMMAND = "SWStyle_WEPrimaryMember"
EDIT_COMMAND = "SWStyle_WEEditStructureSystem"
SYSTEM_LABEL = "Structure System"
PRIMARY_LABEL = "Primary Member"
TITLE = "Primary Structural Member"
GROUP = "Primary Member"
TYPES = ("Path Segment", "Reference Plane", "Points And Length", "Face Plane Intersection")
TYPE_TIPS = ("Path segment members", "Reference plane members", "Point length members",
             "Face/plane intersection members")
AXES = ("HorizontalAxis", "VerticalAxis")
# Pierce Point: where the path runs through the profile, as FrameForge anchors (x: Left/Center/Right,
# y: Bottom/Center/Top)
# Split Member (swStructureSplitMemberType_e, swSplitMemberDimensionType_e)
SPLIT_TYPES = ("Reference", "Dimension")
SPLIT_BY = ("Split Length", "Instances")
# Points And Length: where each member ends (swPrimaryMemberPointLengthEndCondition_e)
END_CONDITIONS = ("Length", "Point", "Up To Point", "Up To Plane")
PIERCE = {"Center": (1, 1), "Top Center": (1, 2), "Bottom Center": (1, 0), "Top Left": (0, 2), "Top Right": (2, 2),
          "Center Left": (0, 1), "Center Right": (2, 1), "Bottom Left": (0, 0), "Bottom Right": (2, 0)}
NOT_YET = wemember.NOT_YET
V = App.Vector
TOL = 1e-6

_active = {}        # document name -> the Structure System being edited (the mode)


def _weicon(name, key=None):
    from . import weprofile
    return weprofile.icon(name, key)


# ================================================================ geometry
def _shape(obj, sub):
    return Part.getShape(obj, sub, needSubElement=True) if sub else Part.getShape(obj)


def plane_of(obj, sub=""):
    """(point, normal) of a plane, datum plane or flat face."""
    if not sub and obj.TypeId in ("App::Plane", "PartDesign::Plane", "Part::DatumPlane"):
        pl = obj.getGlobalPlacement()
        return pl.Base, pl.Rotation.multVec(V(0, 0, 1))
    s = _shape(obj, sub)
    f = s.Faces[0] if s.Faces else None
    if f is None or f.Surface.TypeId != "Part::GeomPlane":
        raise ValueError("Pick planes or flat faces.")
    return f.CenterOfMass, f.normalAt(0, 0)


def direction_of(obj, sub=""):
    """A direction from an edge (along it) or a plane or face (square to it)."""
    if sub.startswith("Edge"):
        e = _shape(obj, sub).Edges[0]
        if e.Curve.TypeId != "Part::GeomLine":
            raise ValueError("The direction must be a straight edge, a plane or a flat face.")
        return (e.Vertexes[-1].Point - e.Vertexes[0].Point).normalize()
    return plane_of(obj, sub)[1].normalize()


def cross_line(a, b):
    """The line where planes a and b = (point, normal) cross: (point, direction)."""
    (p1, n1), (p2, n2) = a, b
    d = n1.cross(n2)
    if d.Length < 1e-9:
        return None
    d.normalize()
    # the point on both planes nearest the first plane's point
    m = App.Matrix(n1.x, n1.y, n1.z, 0, n2.x, n2.y, n2.z, 0, d.x, d.y, d.z, 0, 0, 0, 0, 1)
    rhs = V(n1.dot(p1), n2.dot(p2), d.dot(p1))
    return m.inverse().multVec(rhs), d


def _hit(point, d, plane):
    p, n = plane
    den = d.dot(n)
    if abs(den) < 1e-12:
        return None
    return point + d * ((p - point).dot(n) / den)


def merged(lines):
    """Lines that run on in line from one another joined into one (Merge Tangent Members)."""
    out = [list(l) for l in lines]
    changed = True
    while changed:
        changed = False
        for i in range(len(out)):
            for j in range(len(out)):
                if i == j:
                    continue
                a0, a1 = out[i]
                b0, b1 = out[j]
                da, db = (a1 - a0).normalize(), (b1 - b0).normalize()
                if abs(abs(da.dot(db)) - 1) > 1e-9:
                    continue
                for p, q in ((a1, b0), (a1, b1), (a0, b0), (a0, b1)):
                    if (p - q).Length < TOL:
                        ends = [x for x in (a0, a1, b0, b1) if (x - p).Length > TOL]
                        if len(ends) == 2:
                            out[i] = ends if (ends[0] - a0).Length < TOL or (ends[0] - a1).Length < TOL else ends[::-1]
                            del out[j]
                            changed = True
                        break
                if changed:
                    break
            if changed:
                break
    return [tuple(l) for l in out]


def _line_edges(edges):
    lines = []
    for e in edges:
        if e.Curve.TypeId != "Part::GeomLine":
            raise ValueError("Only straight members can be built yet.")
        lines.append((e.Vertexes[0].Point, e.Vertexes[-1].Point))
    return lines


def _is_arc(obj, sub):
    try:
        return _shape(obj, sub).Edges[0].Curve.TypeId == "Part::GeomCircle"
    except Exception:
        return False


def arc_segments(obj):
    ""

    if is_secondary(obj) or getattr(obj, "MemberType", "") != "Path Segment":
        return []
    return [(o, s) for o, s in _subs(obj.Segments) if s.startswith("Edge") and _is_arc(o, s)]


def _subs(link):
    """[(object, sub)] from a LinkSubList value."""
    out = []
    for obj, subs in link or []:
        for s in (subs if isinstance(subs, (list, tuple)) else [subs]) or [""]:
            out.append((obj, s))
    return out


def paths(obj):
    """The members' straight paths [(start, end)] for the Primary Member's type and selections."""
    kind = obj.MemberType
    if kind == "Path Segment":
        segments = _subs(obj.Segments)
        if any(s.startswith("?") for _o, s in segments):
            raise ValueError("A path segment is gone from its sketch: pick it again.")
        lines = _line_edges([_shape(o, s).Edges[0] for o, s in segments if not _is_arc(o, s)])
        return merged(lines) if obj.MergeTangent else lines
    if kind == "Reference Plane":
        first = [plane_of(o, s) for o, s in _subs(obj.Planes1)]
        second = [plane_of(o, s) for o, s in _subs(obj.Planes2)]
        bounds = [plane_of(o, s) for o, s in _subs(obj.Bounds)]
        if not first or not second:
            return []
        if len(bounds) < 2:
            raise ValueError("Select two bounding planes or faces for the members' ends.")
        out = []
        for a in first:
            for b in second:
                line = cross_line(a, b)
                if line is None:
                    continue
                p0, p1 = _hit(line[0], line[1], bounds[0]), _hit(line[0], line[1], bounds[1])
                if p0 is not None and p1 is not None and (p1 - p0).Length > TOL:
                    out.append((p0, p1))
        if not out:
            raise ValueError("The selected planes do not cross.")
        return out
    if kind == "Points And Length":
        pts = []
        for o, s in _subs(obj.Points):
            shp = _shape(o, s)
            if not shp.Vertexes:
                continue
            pts.append(shp.Vertexes[0].Point)
        if not pts:
            return []
        condition = getattr(obj, "EndCondition", "Length")
        target = _subs(getattr(obj, "EndTarget", None))
        if condition != "Length" and not target:
            raise ValueError("Pick the %s the members end at." % ("plane or face" if condition == "Up To Plane" else "point"))
        if condition == "Point":
            q = _shape(*target[0]).Vertexes[0].Point
            return [(p, q) for p in pts if (q - p).Length > TOL]
        refs = _subs(obj.Direction)
        d = direction_of(*refs[0]) if refs else V(0, 0, 1)
        if obj.ReverseDirection:
            d = d * -1
        if condition == "Length":
            length = float(obj.Length)
            return [(p, p + d * length) for p in pts]
        if condition == "Up To Point":
            q = _shape(*target[0]).Vertexes[0].Point
            plane = (q, d)
        else:
            plane = plane_of(*target[0])
        out = []
        for p in pts:
            end = _hit(p, d, plane)
            if end is None or (end - p).Length < TOL:
                raise ValueError("The direction does not reach the end %s." % ("plane" if condition == "Up To Plane" else "point"))
            out.append((p, end))
        return out
    # Face Plane Intersection
    faces = [_shape(o, s) for o, s in _subs(obj.Faces)]
    planes = [plane_of(o, s) for o, s in _subs(obj.FacePlanes)]
    edges = []
    for f in faces:
        for p, n in planes:
            size = f.BoundBox.DiagonalLength * 4 + 10
            cutter = Part.makePlane(2 * size, 2 * size, V(-size, -size, 0))
            cutter.Placement = App.Placement(p, App.Rotation(V(0, 0, 1), n))
            edges.extend(f.section(cutter).Edges)
    lines = _line_edges(edges)
    return merged(lines) if obj.MergeTangent else lines


# ================================================================ features
class StructureSystem:
    """Structure System1: holds the system's members."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLinkList", "Primaries", GROUP, "Primary members").Primaries = []
        obj.setEditorMode("Primaries", 2)
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _icon(name, key=None):
    try:
        return _weicon(name, key)
    except Exception:
        return ""


class ViewProviderStructureSystem:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        wemember._empty_mode(vobj)

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return _icon("metalwb.svg", "WE_StructureSystem")

    def claimChildren(self):
        if not hasattr(self, "Object"):     # asked before attach() on a reopened file (pkg123)
            return []
        return list(self.Object.Primaries)

    def doubleClicked(self, vobj):
        enter(vobj.Object.Document, vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


class PrimaryMember(wemember.StructuralMember):
    """A Primary Member: a Structural Member whose paths come from its type's selections."""

    def __init__(self, obj):
        super().__init__(obj)
        add = obj.addProperty
        add("App::PropertyEnumeration", "MemberType", GROUP, "Primary member type")
        obj.MemberType = list(TYPES)
        add("App::PropertyLinkSubListGlobal", "Segments", GROUP, "Path segments")
        add("App::PropertyBool", "MergeTangent", GROUP, "Merge Tangent Members")
        add("App::PropertyLinkSubListGlobal", "Planes1", GROUP, "Reference planes (first set)")
        add("App::PropertyLinkSubListGlobal", "Planes2", GROUP, "Reference planes (second set)")
        add("App::PropertyLinkSubListGlobal", "Bounds", GROUP, "Bounding planes or faces")
        add("App::PropertyLinkSubListGlobal", "Points", GROUP, "Points")
        add("App::PropertyLinkSubListGlobal", "Direction", GROUP, "Direction reference")
        add("App::PropertyEnumeration", "EndCondition", GROUP, "Points And Length: End Condition")
        obj.EndCondition = list(END_CONDITIONS)
        add("App::PropertyLinkSubListGlobal", "EndTarget", GROUP, "The point or plane members end at")
        add("App::PropertyBool", "ReverseDirection", GROUP, "Reverse Direction")
        add("App::PropertyLength", "Length", GROUP, "Member length")
        add("App::PropertyLinkSubListGlobal", "Faces", GROUP, "Faces")
        add("App::PropertyLinkSubListGlobal", "FacePlanes", GROUP, "Planes crossing the faces")
        add("App::PropertyLength", "StartExtend", GROUP, "Start extend (D1)")
        add("App::PropertyLength", "EndExtend", GROUP, "End extend (D2)")
        add("App::PropertyBool", "MirrorProfile", GROUP, "Mirror Profile")
        add("App::PropertyEnumeration", "MirrorAxis", GROUP, "Mirror axis")
        obj.MirrorAxis = list(AXES)
        add("App::PropertyString", "Problem", GROUP, "Why no members could be built")
        obj.setEditorMode("Problem", 2)
        obj.Length = 100.0
        _add_rotation(obj)


def _add_rotation(obj):
    """The Profile tab's later properties: Profile Alignment's angle and the Pierce Point (members made
    before they were added have none)."""
    if "Rotation" not in obj.PropertiesList:
        obj.addProperty("App::PropertyAngle", "Rotation", GROUP, "Profile Alignment: the profile's angle")
    if "EndCondition" not in obj.PropertiesList and "Points" in obj.PropertiesList:
        obj.addProperty("App::PropertyEnumeration", "EndCondition", GROUP, "Points And Length: End Condition")
        obj.EndCondition = list(END_CONDITIONS)
        obj.addProperty("App::PropertyLinkSubListGlobal", "EndTarget", GROUP, "The point or plane members end at")
    if "Split" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "Split", GROUP, "Split Member")
        obj.addProperty("App::PropertyEnumeration", "SplitType", GROUP, "Split by references or by dimension")
        obj.SplitType = list(SPLIT_TYPES)
        obj.addProperty("App::PropertyLinkSubListGlobal", "SplitRefs", GROUP, "Points, planes or faces the members split at")
        obj.addProperty("App::PropertyEnumeration", "SplitBy", GROUP, "Dimension: by length or into equal instances")
        obj.SplitBy = list(SPLIT_BY)
        obj.addProperty("App::PropertyLength", "SplitLength", GROUP, "Split Length")
        obj.SplitLength = 100.0
        obj.addProperty("App::PropertyInteger", "SplitCount", GROUP, "Number of instances")
        obj.SplitCount = 2
    if "AlignTo" not in obj.PropertiesList:
        obj.addProperty("App::PropertyLinkSubListGlobal", "AlignTo", GROUP, "Profile Alignment: what the profile lines up with")
        obj.addProperty("App::PropertyEnumeration", "AlignAxis", GROUP, "Profile Alignment: the profile axis lined up")
        obj.AlignAxis = list(AXES)
    if "PiercePoint" not in obj.PropertiesList:
        obj.addProperty("App::PropertyEnumeration", "PiercePoint", GROUP, "Pierce Point: where the path runs through the profile")
        obj.PiercePoint = list(PIERCE)
        obj.PiercePoint = "Center"
        obj.addProperty("App::PropertyBool", "PierceOffset", GROUP, "Offset Pierce Point")
        obj.addProperty("App::PropertyDistance", "Horizon", GROUP, "Pierce Point offset across the profile")
        obj.addProperty("App::PropertyDistance", "Vertical", GROUP, "Pierce Point offset up the profile")
    if "PointMode" in obj.PropertiesList and "AlignMember" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "AlignMember", GROUP, "Align Member: the profile lines up with the members it joins")


def is_primary(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "PrimaryMember"


class ViewProviderPrimaryMember(wemember.ViewProviderStructuralMember):
    def getIcon(self):
        return _icon("profile.svg")

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + PRIMARY_LABEL)
        try:
            Gui.Control.showDialog(Panel(obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True


def rebuild(obj):
    """Recreates a Primary Member's members (called from wemember's rebuild, in tree order)."""
    doc = obj.Document
    for m in reversed(list(obj.Members)):
        try:
            doc.removeObject(m.Name)
        except Exception as _fw_err:
            _fw_log("westructure.py:426", _fw_err)
    obj.Members = obj.Bodies = []
    obj.Problem = ""
    row = wemember.find_size(obj.Standard, obj.Type, obj.Size)
    if row is None:
        obj.Problem = "Pick the profile on the Profile tab."
        return
    try:
        lines = secondary_paths(obj) if is_secondary(obj) else paths(obj)
    except Exception as e:
        obj.Problem = str(e)
        return
    arcs = arc_segments(obj)
    if not lines and not arcs:
        return
    try:
        pieces = split_lines(obj, lines) if lines else []
    except Exception as e:
        obj.Problem = str(e)
        return
    lines = [(a, b) for a, b, _f, _l in pieces]
    # Start/End Extend: at the ends of each whole member, not where it is split
    extends = [(float(obj.StartExtend) if f else 0.0, float(obj.EndExtend) if last else 0.0)
               for _a, _b, f, last in pieces]
    path = doc.addObject("Part::Feature", "MemberPath")
    path.Shape = Part.Compound([Part.makeLine(a, b) for a, b in lines] +
                               [_shape(o, s).Edges[0].copy() for o, s in arcs])
    if App.GuiUp:
        path.ViewObject.Visibility = False
        if "ShowInTree" in path.ViewObject.PropertiesList:
            path.ViewObject.ShowInTree = False
    group = {"anchor": list(PIERCE.get(getattr(obj, "PiercePoint", "Center"), (1, 1))),
             "rotation": float(getattr(obj, "Rotation", 0.0)),
             "mirror": ("Horizontal" if obj.MirrorAxis == "HorizontalAxis" else "Vertical") if obj.MirrorProfile else ""}
    profiles = [wemember._profile(doc, path, "Edge%d" % (k + 1), row, group, d1, d2)
                for k, (d1, d2) in enumerate(extends)]
    stands, curved = [], []
    if arcs:
        stands = [wemember._profile(doc, path, "Edge%d" % (len(lines) + k + 1), row, group, 0.0, 0.0)
                  for k in range(len(arcs))]
        doc.recompute([path] + stands)
        curved = [wemember._arc_member(doc, p, path, "Edge%d" % (len(lines) + k + 1)) for k, p in enumerate(stands)]
        doc.recompute(curved)
    align = _subs(getattr(obj, "AlignTo", None))
    if align:
        _align(profiles, direction_of(*align[0]), obj.AlignAxis, float(getattr(obj, "Rotation", 0.0)))
    elif is_secondary(obj) and getattr(obj, "AlignMember", False):
        _align_to_members(obj, profiles)
    if getattr(obj, "PierceOffset", False):
        for p in profiles:
            pl = p.AttachmentOffset
            pl.Base = V(float(obj.Horizon), float(obj.Vertical), 0)
            p.AttachmentOffset = pl
    obj.Members = [path] + profiles + stands + curved
    obj.Bodies = profiles + curved


def _point_of(obj, sub):
    s = _shape(obj, sub)
    return s.Vertexes[0].Point if s.Vertexes and not s.Faces and (sub.startswith("Vertex") or len(s.Vertexes) == 1) \
        else None


def split_lines(obj, lines):
    """Split Member: each path line cut where the split points or planes cross it (Reference), or every
    Split Length / into equal Instances (Dimension). [(start, end, first piece, last piece)]."""
    if not getattr(obj, "Split", False):
        return [(a, b, True, True) for a, b in lines]
    refs = _subs(obj.SplitRefs)
    if obj.SplitType == "Reference" and not refs:
        raise ValueError("Pick the points, planes or faces to split the members at.")
    out = []
    for a, b in lines:
        length = (b - a).Length
        u = (b - a) / length
        ts = []
        if obj.SplitType == "Reference":
            for o, sub in refs:
                p = _point_of(o, sub)
                if p is not None:
                    ts.append((p - a).dot(u))
                else:
                    hit = _hit(a, u, plane_of(o, sub))
                    if hit is not None:
                        ts.append((hit - a).dot(u))
        elif obj.SplitBy == "Instances":
            n = max(1, int(obj.SplitCount))
            ts = [length * k / n for k in range(1, n)]
        else:
            step = float(obj.SplitLength)
            if step <= TOL:
                raise ValueError("The split length must be more than 0.")
            ts = [step * k for k in range(1, int(length / step) + 1)]
        ts = sorted(set(round(t, 9) for t in ts if TOL < t < length - TOL))
        pts = [a] + [a + u * t for t in ts] + [b]
        for i in range(len(pts) - 1):
            out.append((pts[i], pts[i + 1], i == 0, i == len(pts) - 2))
    return out


def _align(profiles, d, axis, extra):
    """Profile Alignment: turns each profile about its path so its horizontal (or vertical) axis lines up
    with d seen along the path, then by the Rotation Angle on top."""
    for p in profiles:
        p.recompute()
        base = p.Placement.Rotation.multiply(p.AttachmentOffset.Rotation.inverted())
        z = base.multVec(V(0, 0, 1))
        ref = base.multVec(V(1, 0, 0) if axis == "HorizontalAxis" else V(0, 1, 0))
        t = d - z * d.dot(z)
        if t.Length < 1e-9:
            continue            # lined up with the path itself: no turn says which way
        angle = math.degrees(math.atan2(z.dot(ref.cross(t)), ref.dot(t)))
        p.RotationAngle = angle + extra


def _joined(obj):
    """The member refs a Secondary Member's members run between or to."""
    if obj.SecondaryType == "Point Member":
        return [r for item in json.loads(obj.PointPairs or "[]") for r in item[1:]]
    return [r for pair in json.loads(obj.Pairs or "[]") for r in pair]


def _align_to_members(obj, profiles):
    """Align Member: each member turns so its profile's axes line up with those of the member it starts
    from (vertical with vertical; horizontal with horizontal when the vertical axis runs along the path)."""
    doc = obj.Document
    axes = []
    for ref in dict.fromkeys(_joined(obj)):
        name, k = ref.split(":")
        sm = doc.getObject(name)
        if sm is None or int(k) >= len(sm.Bodies):
            continue
        prof = _chain(sm.Bodies[int(k)])[-1]
        prof.recompute()
        a, b = member_axis(doc, ref)
        axes.append((a, b, prof.Placement.Rotation))
    if not axes:
        return
    extra = float(getattr(obj, "Rotation", 0.0))
    for p in profiles:
        p.recompute()
        start = p.Placement.Base
        def gap(item):
            a, b, _r = item
            d = b - a
            t = max(0.0, min(1.0, (start - a).dot(d) / max(d.Length ** 2, 1e-12)))
            return (a + d * t - start).Length
        rot = min(axes, key=gap)[2]
        z = p.Placement.Rotation.multVec(V(0, 0, 1))
        up = rot.multVec(V(0, 1, 0))
        if (up - z * up.dot(z)).Length > 1e-6:
            _align([p], up, "VerticalAxis", extra)
        else:
            _align([p], rot.multVec(V(1, 0, 0)), "HorizontalAxis", extra)


def system(doc, create=True):
    """The document's Structure System being edited (made on demand)."""
    found = _active.get(doc.Name)
    if found is not None and doc.getObject(found) is not None:
        return doc.getObject(found)
    if not create:
        return None
    wemember.weldment(doc)
    obj = doc.addObject("App::FeaturePython", "StructureSystem")
    StructureSystem(obj)
    if App.GuiUp:
        ViewProviderStructureSystem(obj.ViewObject)
    obj.Label = naming.next_label(doc, SYSTEM_LABEL)
    _active[doc.Name] = obj.Name
    return obj


def in_mode(doc=None):
    doc = doc or App.ActiveDocument
    return doc is not None and doc.getObject(_active.get(doc.Name, "")) is not None


def enter(doc, existing=None):
    if existing is not None:
        _active[doc.Name] = existing.Name
        return existing
    doc.openTransaction(SYSTEM_LABEL)
    try:
        obj = system(doc)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return obj


def leave(doc):
    ""

    from . import wecorner
    obj = system(doc, create=False)
    _active.pop(doc.Name, None)
    if obj is not None and not obj.Primaries:
        doc.openTransaction("Exit " + SYSTEM_LABEL)
        try:
            doc.removeObject(obj.Name)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
    elif obj is not None:
        doc.openTransaction("Exit " + SYSTEM_LABEL)
        try:
            wecorner.ensure(obj)
            wemember.refresh(doc)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
    doc.recompute()


def make_primary(doc):
    sysobj = system(doc)
    obj = doc.addObject("App::FeaturePython", "PrimaryMember")
    PrimaryMember(obj)
    if App.GuiUp:
        ViewProviderPrimaryMember(obj.ViewObject)
    p = App.ParamGet(wemember.PARAMS)
    obj.Standard = p.GetString("Standard", wemember.DEFAULT[0])
    obj.Type = p.GetString("Type", wemember.DEFAULT[1])
    obj.Size = p.GetString("Size", wemember.DEFAULT[2])
    if wemember.find_size(obj.Standard, obj.Type, obj.Size) is None:
        obj.Standard, obj.Type, obj.Size = wemember.DEFAULT
    obj.Groups = json.dumps([])
    obj.Label = naming.next_label(doc, PRIMARY_LABEL)
    sysobj.Primaries = list(sysobj.Primaries) + [obj]
    return obj


# ================================================================ PropertyManager
_LAST = None
LISTS = {
    # type -> [(property, object name, colour, tooltip, what it takes)]
    "Path Segment": [("Segments", "SWWEPMSegments", "#d6ecff", "Path segments: sketch segments", "edge")],
    "Reference Plane": [("Planes1", "SWWEPMPlanes1", "#d6ecff", "Planes or flat faces", "plane"),
                        ("Planes2", "SWWEPMPlanes2", "#ffd6ec", "Planes or flat faces crossing the first",
                         "plane"),
                        ("Bounds", "SWWEPMBounds", "#e6d6ff", "Two bounding planes or faces: the members' ends",
                         "plane")],
    "Points And Length": [("Points", "SWWEPMPoints", "#d6ecff", "Points: where members start", "point"),
                          ("Direction", "SWWEPMDirection", "#ffd6ec",
                           "Direction: an edge, a plane or a flat face", "direction"),
                          ("EndTarget", "SWWEPMEndTarget", "#e6d6ff",
                           "End: the point, or the plane or flat face, the members go up to", "target")],
    "Face Plane Intersection": [("Faces", "SWWEPMFaces", "#d6ecff", "Faces", "face"),
                                ("FacePlanes", "SWWEPMFacePlanes", "#ffd6ec", "Planes crossing the faces",
                                 "plane")],
}


def _bold(text):
    lab = QtWidgets.QLabel(text)
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    return lab


def _spin(name, value, tip, low=-100000.0, high=100000.0):
    s = QtWidgets.QDoubleSpinBox()
    s.setObjectName(name)
    s.setRange(low, high)
    s.setDecimals(2)
    s.setSuffix(" mm")
    s.setValue(value)
    s.setToolTip(tip)
    return s


class Panel:
    """The Primary Structural Member PropertyManager: Member and Profile tabs."""

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj, self.new, self.busy = obj, new, True
        _add_rotation(obj)
        wemember._ensure(obj)
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWWEPrimaryPanel")
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", TITLE)
        self.form.setProperty("swstyle_pm_icon", "SWStyle_WEStructuralMember")
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("SWWEError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        from . import pickprompt
        pickprompt.style(self.error)     # look audit AI1: the start prompt in the yellow box
        self.error.hide()
        lay.addWidget(self.error)
        self.tabs = QtWidgets.QTabBar()
        self.tabs.setObjectName("SWWEPMTabs")
        self.tabs.addTab("Member")
        self.tabs.addTab("Profile")
        self.tabs.setExpanding(True)
        lay.addWidget(self.tabs)
        self.pages = QtWidgets.QStackedWidget()
        lay.addWidget(self.pages)
        self.pages.addWidget(self._member_page())
        self.pages.addWidget(self._profile_page())
        self.tabs.currentChanged.connect(self.pages.setCurrentIndex)
        self.lists = {}
        self._show_type()
        self.busy = False
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ------------------------------------------------------------- pages
    def _member_page(self):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_bold("Primary Member Type"))
        row = QtWidgets.QHBoxLayout()
        self.type_buttons = []
        for k, (kind, tip) in enumerate(zip(TYPES, TYPE_TIPS)):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWWEPMType%d" % k)
            b.setText(("Path", "Planes", "Point", "Face")[k])
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setChecked(self.obj.MemberType == kind)
            b.clicked.connect(lambda _c=False, kind=kind: self._set_type(kind))
            self.type_buttons.append(b)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.type_pages = QtWidgets.QStackedWidget()
        self.lists_by_type = {}
        for kind in TYPES:
            self.type_pages.addWidget(self._type_page(kind))
        lay.addWidget(self.type_pages)
        lay.addWidget(_bold("Start/End Extend"))
        self.d1 = _spin("SWWEPMExtend1", float(self.obj.StartExtend), "Start extend (D1)", 0.0)
        self.d2 = _spin("SWWEPMExtend2", float(self.obj.EndExtend), "End extend (D2)", 0.0)
        lay.addWidget(self.d1)
        lay.addWidget(self.d2)
        self._split_controls(lay)
        lay.addStretch(1)
        for s in (self.d1, self.d2):
            s.valueChanged.connect(self._changed)
        return page

    def _type_page(self, kind):
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        heading = {"Path Segment": "Path Segments", "Reference Plane": "Reference Parameters",
                   "Points And Length": "Points And Length", "Face Plane Intersection": "Face Parameters"}[kind]
        lay.addWidget(_bold(heading))
        widgets = []
        for prop, name, colour, tip, _what in LISTS[kind]:
            if kind == "Points And Length" and prop == "Direction":
                lay.addWidget(_bold("End Condition"))
                row = QtWidgets.QHBoxLayout()
                self.reverse = QtWidgets.QPushButton("Reverse Direction")
                from . import pmvalues
                self.reverse.setIcon(pmvalues.reverse_icon())
                self.reverse.setObjectName("SWWEPMReverse")
                self.reverse.setCheckable(True)
                self.reverse.setChecked(bool(self.obj.ReverseDirection))
                self.reverse.toggled.connect(self._changed)
                self.end = QtWidgets.QComboBox()
                self.end.setObjectName("SWWEPMEndCondition")
                self.end.addItems(list(END_CONDITIONS))
                self.end.setCurrentText(getattr(self.obj, "EndCondition", "Length"))
                self.end.currentIndexChanged.connect(self._changed)
                row.addWidget(self.reverse)
                row.addWidget(self.end, 1)
                lay.addLayout(row)
            w = QtWidgets.QListWidget()
            w.setObjectName(name)
            w.setToolTip(tip)
            w.setMaximumHeight(80 if kind != "Points And Length" or prop == "Points" else 40)
            if colour == "#d6ecff":
                pmboxes.mark(w, True)
            else:
                w.setStyleSheet("QListWidget { background: %s; }" % colour)
            w.installEventFilter(self._keys())
            widgets.append((prop, w))
            lay.addWidget(w)
        if kind == "Points And Length":
            self.length = _spin("SWWEPMLength", float(self.obj.Length), "Length", 0.01)
            self.length.valueChanged.connect(self._changed)
            lay.addWidget(self.length)
        if kind in ("Path Segment", "Face Plane Intersection"):
            m = QtWidgets.QCheckBox("Merge Tangent Members")
            m.setObjectName("SWWEPMMerge%d" % TYPES.index(kind))
            m.setChecked(bool(self.obj.MergeTangent))
            m.toggled.connect(self._merge)
            lay.addWidget(m)
        lay.addStretch(1)
        self.lists_by_type[kind] = widgets
        return page

    def _profile_page(self):
        page = QtWidgets.QWidget()
        f = QtWidgets.QFormLayout(page)
        f.addRow(_bold("Profile"))
        self.standard = QtWidgets.QComboBox()
        self.standard.setObjectName("SWWEStandard")
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("SWWEType")
        self.size = QtWidgets.QComboBox()
        self.size.setObjectName("SWWESize")
        self.standard.addItems(list(wemember.catalog()))
        self.standard.setCurrentText(self.obj.Standard)
        self._fill_types(self.obj.Type, self.obj.Size)
        f.addRow(QtWidgets.QLabel("Standard:"))
        f.addRow(self.standard)
        f.addRow(QtWidgets.QLabel("Type:"))
        f.addRow(self.kind)
        f.addRow(QtWidgets.QLabel("Size:"))
        f.addRow(self.size)
        wemember.favorites_row(self, f, label=False)
        self.transfer = QtWidgets.QCheckBox("Transfer Material from Profile")
        self.transfer.setObjectName("SWWETransfer")
        self.transfer.setChecked(bool(getattr(self.obj, "TransferMaterial", True)))
        self.transfer.setToolTip("The members take the profile's material")
        f.addRow(self.transfer)
        self.mirror = QtWidgets.QCheckBox("Mirror Profile")
        self.mirror.setObjectName("SWWEPMMirror")
        self.mirror.setChecked(bool(self.obj.MirrorProfile))
        f.addRow(self.mirror)
        self.axis = QtWidgets.QComboBox()
        self.axis.setObjectName("SWWEPMMirrorAxis")
        self.axis.addItems(list(AXES))
        self.axis.setCurrentText(self.obj.MirrorAxis)
        f.addRow(self.axis)
        # Pierce Point: where the path runs through the profile, and an offset from there
        f.addRow(_bold("Pierce Point"))
        self.pierce = QtWidgets.QComboBox()
        self.pierce.setObjectName("SWWEPMPierce")
        self.pierce.addItems(list(PIERCE))
        self.pierce.setCurrentText(getattr(self.obj, "PiercePoint", "Center"))
        self.pierce.setToolTip("Where the path runs through the profile")
        self.pierce_offset = QtWidgets.QCheckBox("Offset Pierce Point")
        self.pierce_offset.setObjectName("SWWEPMPierceOffset")
        self.pierce_offset.setChecked(bool(getattr(self.obj, "PierceOffset", False)))
        self.horizon = _spin("SWWEPMHorizon", float(getattr(self.obj, "Horizon", 0.0)), "Horizon: across the profile")
        self.vertical = _spin("SWWEPMVertical", float(getattr(self.obj, "Vertical", 0.0)), "Vertical: up the profile")
        self.horizon_label, self.vertical_label = QtWidgets.QLabel("Horizon"), QtWidgets.QLabel("Vertical")
        f.addRow(self.pierce)
        f.addRow(self.pierce_offset)
        f.addRow(self.horizon_label)
        f.addRow(self.horizon)
        f.addRow(self.vertical_label)
        f.addRow(self.vertical)
        self._show_offset()
        f.addRow(_bold("Profile Alignment:"))
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setObjectName("SWWEPMAngle")
        self.angle.setRange(-360.0, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix("deg")
        self.angle.setValue(float(getattr(self.obj, "Rotation", 0.0)))
        self.angle.setToolTip("Rotates the profile about the path")
        self.align_list = QtWidgets.QListWidget()
        self.align_list.setObjectName("SWWEPMAlignList")
        self.align_list.setMaximumHeight(40)
        pmboxes.mark(self.align_list, True)
        self.align_list.setToolTip("Align: an edge, axis, plane or flat face the profile's axis lines up with")
        self.align_list.installEventFilter(self._keys())
        radios = QtWidgets.QWidget()       # its own parent: exclusive only with each other
        rl = QtWidgets.QVBoxLayout(radios)
        rl.setContentsMargins(0, 0, 0, 0)
        self.align_h = QtWidgets.QRadioButton("Align Horizontal Axis")
        self.align_h.setObjectName("SWWEPMAlignH")
        self.align_v = QtWidgets.QRadioButton("Align Vertical Axis")
        self.align_v.setObjectName("SWWEPMAlignV")
        (self.align_v if getattr(self.obj, "AlignAxis", AXES[0]) == "VerticalAxis" else self.align_h).setChecked(True)
        rl.addWidget(self.align_h)
        rl.addWidget(self.align_v)
        f.addRow(self.align_list)
        f.addRow(radios)
        f.addRow(QtWidgets.QLabel("Rotation Angle"))
        f.addRow(self.angle)
        self.align_v.toggled.connect(self._changed)
        self._fill_align()
        self.angle.valueChanged.connect(self._changed)
        self.standard.currentIndexChanged.connect(self._standard_changed)
        self.kind.currentIndexChanged.connect(self._type_changed)
        self.size.currentIndexChanged.connect(self._changed)
        self.mirror.toggled.connect(self._changed)
        self.transfer.toggled.connect(self._changed)
        self.axis.currentIndexChanged.connect(self._changed)
        self.pierce.currentIndexChanged.connect(self._changed)
        self.pierce_offset.toggled.connect(self._changed)
        self.horizon.valueChanged.connect(self._changed)
        self.vertical.valueChanged.connect(self._changed)
        return page

    def _split_controls(self, lay):
        """Split Member: Reference (the split points, planes or faces) or Dimension (Split Length or
        Instances)."""
        o = self.obj
        self.split = QtWidgets.QCheckBox("Split Member")
        self.split.setObjectName("SWWEPMSplit")
        self.split.setChecked(bool(getattr(o, "Split", False)))
        lay.addWidget(self.split)
        self.split_box = QtWidgets.QWidget()
        sl = QtWidgets.QVBoxLayout(self.split_box)
        sl.setContentsMargins(12, 0, 0, 0)
        kinds = QtWidgets.QWidget()          # its own parent: exclusive only with each other
        kl = QtWidgets.QHBoxLayout(kinds)
        kl.setContentsMargins(0, 0, 0, 0)
        self.split_ref = QtWidgets.QRadioButton("Reference")
        self.split_ref.setObjectName("SWWEPMSplitRef")
        self.split_dim = QtWidgets.QRadioButton("Dimension")
        self.split_dim.setObjectName("SWWEPMSplitDim")
        (self.split_dim if getattr(o, "SplitType", "Reference") == "Dimension" else self.split_ref).setChecked(True)
        kl.addWidget(self.split_ref)
        kl.addWidget(self.split_dim)
        sl.addWidget(kinds)
        self.split_list = QtWidgets.QListWidget()
        self.split_list.setObjectName("SWWEPMSplitRefs")
        self.split_list.setToolTip("Split at: points, planes or faces crossing the members")
        self.split_list.setMaximumHeight(60)
        pmboxes.mark(self.split_list, True)
        self.split_list.installEventFilter(self._keys())
        sl.addWidget(self.split_list)
        self.split_by = QtWidgets.QComboBox()
        self.split_by.setObjectName("SWWEPMSplitBy")
        self.split_by.addItems(list(SPLIT_BY))
        self.split_by.setCurrentText(getattr(o, "SplitBy", SPLIT_BY[0]))
        sl.addWidget(self.split_by)
        self.split_length = _spin("SWWEPMSplitLength", float(getattr(o, "SplitLength", 100.0)), "Split Length", 0.01)
        sl.addWidget(self.split_length)
        self.split_count = QtWidgets.QSpinBox()
        self.split_count.setObjectName("SWWEPMSplitCount")
        self.split_count.setRange(1, 1000)
        self.split_count.setValue(int(getattr(o, "SplitCount", 2)))
        self.split_count.setToolTip("Instances: equal members each is split into")
        sl.addWidget(self.split_count)
        lay.addWidget(self.split_box)
        self.split.toggled.connect(self._split_on)
        self.split.toggled.connect(self._changed)
        self.split_dim.toggled.connect(self._changed)
        self.split_by.currentIndexChanged.connect(self._changed)
        self.split_length.valueChanged.connect(self._changed)
        self.split_count.valueChanged.connect(self._changed)
        self._fill_split()
        self._show_split()

    def _fill_split(self):
        self.split_list.clear()
        for o, s in _subs(getattr(self.obj, "SplitRefs", None)):
            self.split_list.addItem("%s%s" % (o.Label, (", " + s) if s else ""))

    def _show_split(self):
        on = self.split.isChecked()
        self.split_box.setVisible(on)
        ref = self.split_ref.isChecked()
        self.split_list.setVisible(ref)
        self.split_by.setVisible(not ref)
        self.split_length.setVisible(not ref and self.split_by.currentText() == "Split Length")
        self.split_count.setVisible(not ref and self.split_by.currentText() == "Instances")
        if self.split.isHidden():
            self.split_box.setVisible(False)

    def _split_on(self, on):
        if on and self.split_ref.isChecked():
            self.active = self.split_list

    def _fill_align(self):
        self.align_list.clear()
        for o, s in _subs(getattr(self.obj, "AlignTo", None)):
            self.align_list.addItem("%s%s" % (o.Label, (", " + s) if s else ""))

    def _pick_align(self, obj, sub):
        """A pick while the Align box is active: the one edge, axis, plane or face the profile lines up with.
        While the Split Member box is active: the points, planes or faces the members split at."""
        if getattr(self, "split_list", None) is not None and self.active is self.split_list:
            if sub.startswith("Edge"):
                return True
            now = _subs(self.obj.SplitRefs)
            if (obj, sub) in now:
                now.remove((obj, sub))
            else:
                now.append((obj, sub))
            self.obj.SplitRefs = now
            self._fill_split()
            self._apply()
            return True
        if self.active is not self.align_list:
            return False
        if not (sub.startswith(("Edge", "Face")) or not sub):
            return True
        now = _subs(self.obj.AlignTo)
        self.obj.AlignTo = [] if (obj, sub) in now else [(obj, sub)]
        self._fill_align()
        self._apply()
        return True

    def _show_offset(self):
        on = self.pierce_offset.isChecked()
        for w in (self.horizon_label, self.horizon, self.vertical_label, self.vertical):
            w.setVisible(on)

    def _fill_types(self, kind=None, size=None):
        self.kind.blockSignals(True)
        self.kind.clear()
        self.kind.addItems(list(wemember.catalog().get(self.standard.currentText(), {})))
        if kind:
            self.kind.setCurrentText(kind)
        self.kind.blockSignals(False)
        self._fill_sizes(size)

    def _fill_sizes(self, size=None):
        self.size.blockSignals(True)
        self.size.clear()
        rows = wemember.catalog().get(self.standard.currentText(), {}).get(self.kind.currentText(), [])
        self.size.addItems([r[0] for r in rows])
        if size:
            self.size.setCurrentText(size)
        self.size.blockSignals(False)

    def _standard_changed(self, *_a):
        self._fill_types()
        self._changed()

    def _type_changed(self, *_a):
        self._fill_sizes()
        self._changed()

    def _keys(self):
        panel = self

        class Keys(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if event.type() == QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Delete,
                                                                               QtCore.Qt.Key_Backspace):
                    panel.remove_current(watched)
                    return True
                if event.type() == QtCore.QEvent.FocusIn:
                    panel.active = watched
                return False
        self._filters = getattr(self, "_filters", [])
        self._filters.append(Keys())
        return self._filters[-1]

    # ------------------------------------------------------------- state
    def _show_type(self):
        kind = self.obj.MemberType
        self.type_pages.setCurrentIndex(TYPES.index(kind))
        self.lists = dict(self.lists_by_type[kind])
        self.active = self.lists_by_type[kind][0][1]

        self.split.setVisible(kind != "Reference Plane")
        self._show_split()
        self._show_end()

    def _set_type(self, kind):
        if self.busy or self.obj.MemberType == kind:
            return
        self.obj.MemberType = kind
        self._show_type()
        self._apply()

    def _merge(self, on):
        if not self.busy:
            self.obj.MergeTangent = on
            self._apply()

    def _fill(self):
        self.busy = True
        for kind in TYPES:
            for prop, w in self.lists_by_type[kind]:
                w.clear()
                for o, s in _subs(getattr(self.obj, prop)):
                    w.addItem("%s%s" % (o.Label, (", " + s) if s else ""))
        self.busy = False

    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        o.ReverseDirection = self.reverse.isChecked()
        o.Length = self.length.value()
        o.EndCondition = self.end.currentText()
        self._show_end()
        self._set_common(o)
        self._apply()

    def _show_end(self):
        """Points And Length: Length shows the length box; the others the box for their end point or plane;
        Point needs no direction."""
        cond = self.end.currentText()
        lists = dict(self.lists_by_type.get("Points And Length", []))
        self.length.setVisible(cond == "Length")
        if "EndTarget" in lists:
            lists["EndTarget"].setVisible(cond != "Length")
            lists["EndTarget"].setToolTip("End: the plane or flat face the members go up to" if cond == "Up To Plane"
                                          else "End: the point the members go to")
        if "Direction" in lists:
            lists["Direction"].setVisible(cond != "Point")
        self.reverse.setVisible(cond != "Point")

    def _set_common(self, o):
        """Start/End Extend and the Profile tab, shared by primary and secondary members."""
        o.StartExtend, o.EndExtend = self.d1.value(), self.d2.value()
        o.Standard, o.Type, o.Size = self.standard.currentText(), self.kind.currentText(), self.size.currentText()
        o.MirrorProfile = self.mirror.isChecked()
        o.TransferMaterial = self.transfer.isChecked()
        o.MirrorAxis = self.axis.currentText()
        o.Rotation = self.angle.value()
        o.AlignAxis = "VerticalAxis" if self.align_v.isChecked() else "HorizontalAxis"
        o.Split = self.split.isChecked()
        o.SplitType = "Dimension" if self.split_dim.isChecked() else "Reference"
        o.SplitBy = self.split_by.currentText()
        o.SplitLength = max(self.split_length.value(), 0.01)
        o.SplitCount = self.split_count.value()
        self._show_split()
        o.PiercePoint = self.pierce.currentText()
        o.PierceOffset = self.pierce_offset.isChecked()
        o.Horizon, o.Vertical = self.horizon.value(), self.vertical.value()
        self._show_offset()
        from . import smlive            # Mirror Profile's axis shown while it is on, never greyed (drawings-land281)
        smlive.row(self.axis, self.mirror.isChecked())

    def remove_current(self, w):
        if w is getattr(self, "split_list", None):
            now = _subs(self.obj.SplitRefs)
            row = w.currentRow()
            if 0 <= row < len(now):
                del now[row]
                self.obj.SplitRefs = now
                self._fill_split()
                self._apply()
            return
        if w is self.align_list:
            self.obj.AlignTo = []
            self._fill_align()
            self._apply()
            return
        prop = next((p for p, x in self.lists_by_type[self.obj.MemberType] if x is w), None)
        row = w.currentRow()
        if prop is None or row < 0:
            return
        items = _subs(getattr(self.obj, prop))
        del items[row]
        setattr(self.obj, prop, [(o, s) for o, s in items])
        self._fill()
        self._apply()

    def _editing(self):
        """This page's member is still the one in edit: a page closed from outside (another
        PropertyManager opening, Esc, a closed document) lets go of the selection, so picks meant for
        the next page do not land here."""
        try:
            gdoc = Gui.getDocument(self.obj.Document.Name)
            vp = gdoc.getInEdit() if gdoc is not None else None
            if vp is not None:
                return vp.Object == self.obj
            # a new member's page is shown without an edit: it is this page while its form is up
            return self.obj.Document.getObject(self.obj.Name) is not None and self.form.isVisible()
        except Exception:
            return False

    def addSelection(self, doc, name, sub, point):
        if not self._editing():
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("westructure.py:1190", _fw_err)
            return
        QtCore.QTimer.singleShot(0, lambda: self._editing() and self.picked(doc, name, sub))

    def picked(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("westructure.py:1198", _fw_err)
        obj = App.getDocument(doc_name).getObject(name)
        if obj is None or self._pick_align(obj, sub):
            return
        kind = self.obj.MemberType
        lists = self.lists_by_type[kind]
        prop = next((p for p, w in lists if w is self.active), lists[0][0])
        what = next(x[4] for x in LISTS[kind] if x[0] == prop)
        # a pick that does not fit the active box goes to the box that takes it
        up_to_plane = getattr(self.obj, "EndCondition", "Length") == "Up To Plane"
        fits = {"edge": sub.startswith("Edge"), "plane": sub.startswith("Face") or not sub,
                "point": sub.startswith("Vertex"), "face": sub.startswith("Face"),
                "direction": sub.startswith(("Edge", "Face")) or not sub,
                "target": (sub.startswith("Face") or not sub) if up_to_plane else sub.startswith("Vertex")}
        if not fits[what]:
            for p, _n, _c, _t, w in LISTS[kind]:
                if fits[w] and not dict(lists)[p].isHidden():
                    prop, what = p, w
                    break
            else:
                return
        items = _subs(getattr(self.obj, prop))
        if (obj, sub) in items:
            items.remove((obj, sub))
        elif what in ("direction", "target"):
            items = [(obj, sub)]
        else:
            items.append((obj, sub))
        setattr(self.obj, prop, items)
        self._fill()
        self._apply()

    def _apply(self):
        doc = self.obj.Document
        if doc.Recomputing:
            QtCore.QTimer.singleShot(50, self._apply)
            return
        wemember.refresh(doc)
        self._report()

    def _report(self):
        text = self.obj.Problem
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("westructure.py:1251", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("westructure.py:1257", _fw_err)

    def accept(self):
        if not self.obj.Bodies:
            if not self.obj.Problem:
                self.obj.Problem = "Select the members' paths."
            self._report()
            return False
        p = App.ParamGet(wemember.PARAMS)
        p.SetString("Standard", self.obj.Standard)
        p.SetString("Type", self.obj.Type)
        p.SetString("Size", self.obj.Size)
        self.obj.Document.commitTransaction()
        _close_transaction(False)
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        _close_transaction(True)
        wemember.refresh(doc)
        self._close()
        return True


def _close_transaction(abort):
    try:
        App.closeActiveTransaction(abort)
    except Exception as _fw_err:
        _fw_log("westructure.py:1287", _fw_err)


# ================================================================ secondary members
SECONDARY_COMMAND = "SWStyle_WESecondaryMember"
SECONDARY_LABEL = "Secondary Member"
SECONDARY_TITLE = "Secondary Structural Member"
SECONDARY_TYPES = ("Support Plane", "Up To Members", "Point Member")
SECONDARY_TIPS = ("Support plane members: between member pairs, on a plane",
                  "Up to members: between member pairs, offset along them",
                  "Point member: from a point to a member")
OFFSETS = ("Distance", "Length Ratio")
POINT_MODES = ("Point-Member pair", "From Point")


def _chain(obj):
    """obj and the bodies it was trimmed from."""
    out = []
    while obj is not None and obj not in out:
        out.append(obj)
        obj = getattr(obj, "TrimmedBody", None)
    return out


def member_ref(doc, obj, skip=None):
    """'<member feature name>:<k>' of the structural member body obj (or a trim of it), else None."""
    chain = _chain(obj)
    for sm in wemember.structural_members(doc):
        if sm is skip:
            continue
        for k, body in enumerate(sm.Bodies):
            if body in chain or any(c in _chain(body) for c in chain):
                return "%s:%d" % (sm.Name, k)
    return None


def ref_label(doc, ref):
    name, k = ref.split(":")
    sm = doc.getObject(name)
    return "%s[%d]" % (sm.Label if sm is not None else name, int(k) + 1)


def member_axis(doc, ref):
    """(start, end) of a member's path line."""
    name, k = ref.split(":")
    sm = doc.getObject(name)
    if sm is None or int(k) >= len(sm.Bodies):
        raise ValueError("A member of the pair is gone.")
    profile = _chain(sm.Bodies[int(k)])[-1]
    support = getattr(profile, "AttachmentSupport", None)
    if not support:
        raise ValueError("A member of the pair has no path.")
    owner, subs = support[0]
    sub = subs[0] if isinstance(subs, (list, tuple)) else subs
    e = Part.getShape(owner, sub, needSubElement=True).Edges[0]
    return e.Vertexes[0].Point, e.Vertexes[-1].Point


def _along(a, b, value, ratio):
    d = b - a
    if ratio:
        return a + d * max(0.0, min(1.0, float(value)))
    return a + d.normalize() * float(value)


def secondary_paths(obj):
    doc = obj.Document
    kind = obj.SecondaryType
    out = []
    if kind in ("Support Plane", "Up To Members"):
        pairs = [p for p in json.loads(obj.Pairs or "[]") if len(p) == 2]
        if not pairs:
            return []
        planes = [plane_of(o, s) for o, s in _subs(obj.SupportPlanes)]
        if kind == "Support Plane" and not planes:
            raise ValueError("Select a plane for the members (Member Parameter).")
        ratio = obj.OffsetMode == "Length Ratio"
        for r1, r2 in pairs:
            a0, a1 = member_axis(doc, r1)
            b0, b1 = member_axis(doc, r2)
            if kind == "Support Plane":
                for pl in planes:
                    p = _hit(a0, (a1 - a0).normalize(), pl)
                    q = _hit(b0, (b1 - b0).normalize(), pl)
                    if p is None or q is None:
                        raise ValueError("A member of the pair runs along the plane.")
                    out.append((p, q))
            else:
                off2 = obj.Offset1 if obj.EqualOffset else obj.Offset2
                out.append((_along(a0, a1, obj.Offset1, ratio), _along(b0, b1, off2, ratio)))
    else:
        ratio = obj.OffsetMode == "Length Ratio"
        for item in json.loads(obj.PointPairs or "[]"):
            if len(item) != 2:
                continue
            p = V(*item[0])
            a, b = member_axis(doc, item[1])
            if ratio:
                q = _along(a, b, obj.PointOffset, True)
            else:
                d = (b - a).normalize()
                q = a + d * ((p - a).dot(d) + float(obj.PointOffset))      # the foot, moved along the member
            out.append((p, q))
    out = [(p, q) for p, q in out if (q - p).Length > TOL]
    if not out and kind != "Point Member":
        raise ValueError("The members of the pair meet: there is no room for a member.")
    return out


class SecondaryMember(wemember.StructuralMember):
    """A Secondary Member: members between pairs of members (or from points to members)."""

    def __init__(self, obj):
        super().__init__(obj)
        add = obj.addProperty
        add("App::PropertyEnumeration", "SecondaryType", GROUP, "Secondary member type")
        obj.SecondaryType = list(SECONDARY_TYPES)
        add("App::PropertyString", "Pairs", GROUP, "Member pairs (JSON of member refs)")
        add("App::PropertyLinkSubListGlobal", "SupportPlanes", GROUP, "Member Parameter: the plane")
        add("App::PropertyEnumeration", "OffsetMode", GROUP, "Offset: Distance or Length Ratio")
        obj.OffsetMode = list(OFFSETS)
        add("App::PropertyFloat", "Offset1", GROUP, "Offset from First Member (P1)")
        add("App::PropertyFloat", "Offset2", GROUP, "Offset from Second Member (P2)")
        add("App::PropertyBool", "EqualOffset", GROUP, "Equal offset")
        add("App::PropertyEnumeration", "PointMode", GROUP, "Member Point Parameters")
        obj.PointMode = list(POINT_MODES)
        add("App::PropertyString", "PointPairs", GROUP, "Point-member pairs (JSON)")
        add("App::PropertyFloat", "PointOffset", GROUP, "Member offset")
        add("App::PropertyLength", "StartExtend", GROUP, "Start extend (D1)")
        add("App::PropertyLength", "EndExtend", GROUP, "End extend (D2)")
        add("App::PropertyBool", "MirrorProfile", GROUP, "Mirror Profile")
        add("App::PropertyEnumeration", "MirrorAxis", GROUP, "Mirror axis")
        obj.MirrorAxis = list(AXES)
        add("App::PropertyString", "Problem", GROUP, "Why no members could be built")
        for name in ("Problem", "Pairs", "PointPairs"):
            obj.setEditorMode(name, 2)
        _add_rotation(obj)
        obj.Pairs, obj.PointPairs = "[]", "[]"


def is_secondary(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SecondaryMember"


class ViewProviderSecondaryMember(wemember.ViewProviderStructuralMember):
    def getIcon(self):
        return _icon("profile.svg")

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + SECONDARY_LABEL)
        try:
            Gui.Control.showDialog(SecondaryPanel(obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True


def make_secondary(doc):
    sysobj = system(doc)
    obj = doc.addObject("App::FeaturePython", "SecondaryMember")
    SecondaryMember(obj)
    if App.GuiUp:
        ViewProviderSecondaryMember(obj.ViewObject)
    p = App.ParamGet(wemember.PARAMS)
    obj.Standard = p.GetString("Standard", wemember.DEFAULT[0])
    obj.Type = p.GetString("Type", wemember.DEFAULT[1])
    obj.Size = p.GetString("Size", wemember.DEFAULT[2])
    if wemember.find_size(obj.Standard, obj.Type, obj.Size) is None:
        obj.Standard, obj.Type, obj.Size = wemember.DEFAULT
    obj.Groups = json.dumps([])
    obj.Label = naming.next_label(doc, SECONDARY_LABEL)
    sysobj.Primaries = list(sysobj.Primaries) + [obj]
    return obj


class SecondaryPanel(Panel):
    """The Secondary Structural Member PropertyManager: Member and Profile tabs."""

    def __init__(self, obj, new):
        super().__init__(obj, new)
        self.form.setObjectName("SWWESecondaryPanel")
        self.form.setWindowTitle(SECONDARY_TITLE)
        self.form.setProperty("swstyle_pm_title", SECONDARY_TITLE)

    def _member_page(self):
        o = self.obj
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(_bold("Secondary Member Type"))
        row = QtWidgets.QHBoxLayout()
        self.type_buttons = []
        for k, (kind, tip) in enumerate(zip(SECONDARY_TYPES, SECONDARY_TIPS)):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWWESMType%d" % k)
            b.setText(("Plane", "Members", "Point")[k])
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setChecked(o.SecondaryType == kind)
            b.clicked.connect(lambda _c=False, kind=kind: self._set_type(kind))
            self.type_buttons.append(b)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        self.pair_box = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(self.pair_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(_bold("Member Pair"))
        self.pairs = QtWidgets.QListWidget()
        self.pairs.setObjectName("SWWESMPairs")
        self.pairs.setToolTip("Member pairs: pick two members for each")
        self.pairs.setMaximumHeight(80)
        pmboxes.mark(self.pairs, True)
        self.pairs.installEventFilter(self._keys())
        pl.addWidget(self.pairs)
        pl.addWidget(_bold("Member Parameter"))
        self.planes = QtWidgets.QListWidget()
        self.planes.setObjectName("SWWESMPlanes")
        self.planes.setToolTip("The plane the members lie on")
        self.planes.setMaximumHeight(60)
        self.planes.setStyleSheet("QListWidget { background: #ffd6ec; }")
        self.planes.installEventFilter(self._keys())
        pl.addWidget(self.planes)
        lay.addWidget(self.pair_box)

        self.point_box = QtWidgets.QWidget()
        ql = QtWidgets.QVBoxLayout(self.point_box)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.addWidget(_bold("Member Point Parameters"))
        self.point_mode = QtWidgets.QComboBox()
        self.point_mode.setObjectName("SWWESMPointMode")
        self.point_mode.addItems(list(POINT_MODES))
        self.point_mode.setCurrentText(o.PointMode)
        self.point_mode.setItemData(0, "Select a point and a member", QtCore.Qt.ToolTipRole)
        self.point_mode.setItemData(1, "Select a point, then several members: a member runs from the point to each",
                                    QtCore.Qt.ToolTipRole)
        ql.addWidget(self.point_mode)
        self.points = QtWidgets.QListWidget()
        self.points.setObjectName("SWWESMPoints")
        self.points.setToolTip("A point, then the member it runs to")
        self.points.setMaximumHeight(80)
        pmboxes.mark(self.points, True)
        self.points.installEventFilter(self._keys())
        ql.addWidget(self.points)
        lay.addWidget(self.point_box)

        self.offset_box = QtWidgets.QWidget()
        fl = QtWidgets.QVBoxLayout(self.offset_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(QtWidgets.QLabel("Offset"))
        self.by_distance = QtWidgets.QRadioButton("Distance")
        self.by_distance.setObjectName("SWWESMDistance")
        self.by_ratio = QtWidgets.QRadioButton("Length Ratio")
        self.by_ratio.setObjectName("SWWESMRatio")
        (self.by_ratio if o.OffsetMode == "Length Ratio" else self.by_distance).setChecked(True)
        fl.addWidget(self.by_distance)
        fl.addWidget(self.by_ratio)
        self.p1_label = QtWidgets.QLabel("Offset from First Member (P1)")
        self.p1 = _spin("SWWESMOffset1", float(o.Offset1), "Offset from First Member (P1)")
        self.p2_label = QtWidgets.QLabel("Offset from Second Member (P2)")
        self.p2 = _spin("SWWESMOffset2", float(o.Offset2), "Offset from Second Member (P2)")
        self.equal = QtWidgets.QCheckBox("Equal offset")
        self.equal.setObjectName("SWWESMEqual")
        self.equal.setChecked(bool(o.EqualOffset))
        self.m_label = QtWidgets.QLabel("Member")
        self.m_offset = _spin("SWWESMMemberOffset", float(o.PointOffset), "Member offset")
        for w in (self.p1_label, self.p1, self.p2_label, self.p2, self.equal, self.m_label, self.m_offset):
            fl.addWidget(w)
        lay.addWidget(self.offset_box)
        self.align = QtWidgets.QPushButton("Align Member")
        self.align.setObjectName("SWWESMAlign")
        self.align.setCheckable(True)
        self.align.setChecked(bool(getattr(o, "AlignMember", False)))
        self.align.setToolTip("Lines the members' profile up with the members they join")
        lay.addWidget(self.align)

        lay.addWidget(_bold("Start/End Extend"))
        self.d1 = _spin("SWWEPMExtend1", float(o.StartExtend), "Start extend (D1)", 0.0)
        self.d2 = _spin("SWWEPMExtend2", float(o.EndExtend), "End extend (D2)", 0.0)
        lay.addWidget(self.d1)
        lay.addWidget(self.d2)
        self._split_controls(lay)
        lay.addStretch(1)
        for w in (self.d1, self.d2, self.p1, self.p2, self.m_offset):
            w.valueChanged.connect(self._changed)
        for w in (self.by_distance, self.equal, self.align):
            w.toggled.connect(self._changed)
        self.point_mode.currentIndexChanged.connect(self._changed)
        self.active = self.pairs
        self.pending = None         # the first member of a pair being picked, or a point waiting for its member
        self.lists_by_type = {}
        return page

    def _show_type(self):
        kind = self.obj.SecondaryType
        self.pair_box.setVisible(kind != "Point Member")
        self.planes.setVisible(kind == "Support Plane")
        self.point_box.setVisible(kind == "Point Member")
        self.offset_box.setVisible(kind != "Support Plane")
        for w in (self.p1_label, self.p1, self.p2_label, self.p2, self.equal):
            w.setVisible(kind == "Up To Members")
        for w in (self.m_label, self.m_offset):
            w.setVisible(kind == "Point Member")
        for w in (self.p2_label, self.p2):          # Equal: the second distance is the first one's (hidden)
            w.setVisible(kind == "Up To Members" and not self.equal.isChecked())
        self.active = self.points if kind == "Point Member" else self.pairs
        unit = "" if self.by_ratio.isChecked() else " mm"
        for w in (self.p1, self.p2, self.m_offset):
            w.setSuffix(unit)

    def _set_type(self, kind):
        if self.busy or self.obj.SecondaryType == kind:
            return
        self.obj.SecondaryType = kind
        self.pending = None
        self._show_type()
        self._apply()

    def _fill(self):
        self.busy = True
        doc = self.obj.Document
        self.pairs.clear()
        for k, pair in enumerate(json.loads(self.obj.Pairs or "[]"), 1):
            self.pairs.addItem("Pair%d: %s" % (k, ", ".join(ref_label(doc, r) for r in pair)))
        self.planes.clear()
        for o, s in _subs(self.obj.SupportPlanes):
            self.planes.addItem("%s%s" % (o.Label, (", " + s) if s else ""))
        self.points.clear()
        for item in json.loads(self.obj.PointPairs or "[]"):
            p = V(*item[0])
            self.points.addItem("(%.2f, %.2f, %.2f)%s" % (p.x, p.y, p.z,
                                                          (" - " + ref_label(doc, item[1])) if len(item) > 1 else ""))
        self.busy = False

    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        o.OffsetMode = "Length Ratio" if self.by_ratio.isChecked() else "Distance"
        o.Offset1, o.Offset2, o.EqualOffset = self.p1.value(), self.p2.value(), self.equal.isChecked()
        o.PointOffset = self.m_offset.value()
        o.PointMode = self.point_mode.currentText()
        if "AlignMember" in o.PropertiesList:
            o.AlignMember = self.align.isChecked()
        self._set_common(o)
        self._show_type()
        self._apply()

    def remove_current(self, w):
        if w is getattr(self, "split_list", None):
            now = _subs(self.obj.SplitRefs)
            row = w.currentRow()
            if 0 <= row < len(now):
                del now[row]
                self.obj.SplitRefs = now
                self._fill_split()
                self._apply()
            return
        if w is self.align_list:
            self.obj.AlignTo = []
            self._fill_align()
            self._apply()
            return
        row = w.currentRow()
        if row < 0:
            return
        if w is self.planes:
            items = _subs(self.obj.SupportPlanes)
            del items[row]
            self.obj.SupportPlanes = items
        else:
            prop = "Pairs" if w is self.pairs else "PointPairs"
            items = json.loads(getattr(self.obj, prop) or "[]")
            del items[row]
            setattr(self.obj, prop, json.dumps(items))
        self._fill()
        self._apply()

    def picked(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("westructure.py:1670", _fw_err)
        doc = App.getDocument(doc_name)
        obj = doc.getObject(name)
        if obj is None or self._pick_align(obj, sub):
            return
        o = self.obj
        ref = member_ref(doc, obj, skip=o)
        if o.SecondaryType == "Point Member":
            items = json.loads(o.PointPairs or "[]")
            waiting = bool(items) and len(items[-1]) == 1
            if ref is not None and waiting:
                items[-1].append(ref)
            elif ref is not None and items and o.PointMode == "From Point":
                # From Point: each further member gets a member from the same point
                point = items[-1][0]
                if any(it[0] == point and ref in it[1:] for it in items):
                    return
                items.append([point, ref])
            elif sub.startswith("Vertex") and not waiting:
                p = _shape(obj, sub).Vertexes[0].Point
                items.append([[p.x, p.y, p.z]])
            else:
                return
            o.PointPairs = json.dumps(items)
        elif ref is not None and self.active is not self.planes:
            items = json.loads(o.Pairs or "[]")
            if items and len(items[-1]) == 1:
                if items[-1][0] == ref:
                    return
                items[-1].append(ref)
            else:
                items.append([ref])
            o.Pairs = json.dumps(items)
        elif o.SecondaryType == "Support Plane" and ref is None and (sub.startswith("Face") or not sub):
            items = _subs(o.SupportPlanes)
            if (obj, sub) in items:
                items.remove((obj, sub))
            else:
                items.append((obj, sub))
            o.SupportPlanes = items
        else:
            return
        self._fill()
        self._apply()

    def accept(self):
        if not self.obj.Bodies:
            if not self.obj.Problem:
                self.obj.Problem = ("Select a point and a member." if self.obj.SecondaryType == "Point Member"
                                    else "Select member pairs.")
            self._report()
            return False
        return super().accept()


# ================================================================ commands
class SystemCommand:
    def GetResources(self):
        return {"Pixmap": _icon("metalwb.svg", "WE_StructureSystem"), "MenuText": "Structure System",
                "ToolTip": "Enters or leaves the Structure System, where primary members are placed."}

    def IsActive(self):
        if App.ActiveDocument is None or not wemember._engine_ready():
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        doc = App.ActiveDocument
        if in_mode(doc):
            obj = system(doc, create=False)
            leave(doc)
            _corner_page(obj)
        else:
            enter(doc)


def _corner_page(obj):
    ""
    try:
        from . import wecorner
        if obj is None or obj.Document.getObject(obj.Name) is None or Gui.Control.activeDialog():
            return
        cm = wecorner.of_system(obj)
        if cm is not None and wecorner.corners(obj):
            Gui.Control.showDialog(wecorner.Panel(cm))
    except Exception as _fw_err:
        _fw_log("westructure.py:1759", _fw_err)
        from . import fwtell
        fwtell.tell("Corner Management could not be opened.", _fw_err)


def systems(doc):
    return [o for o in (doc.Objects if doc is not None else []) if type(getattr(o, "Proxy", None)).__name__ == "StructureSystem"]


def system_of(obj):
    """The Structure System an object belongs to (itself, or the one holding the member)."""
    if obj is None:
        return None
    for s in systems(obj.Document):
        if s is obj or obj in s.Primaries:
            return s
    return None


class EditSystemCommand:
    ""

    def GetResources(self):
        return {"Pixmap": _icon("metalwb.svg", "WE_EditStructureSystem"), "MenuText": "Edit Structure System",
                "ToolTip": "Enters an existing Structure System to add or change its members."}

    def IsActive(self):
        doc = App.ActiveDocument
        if doc is None or in_mode(doc) or not systems(doc):
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        doc = App.ActiveDocument
        picked = [system_of(s.Object) for s in Gui.Selection.getSelectionEx()]
        picked = [p for p in picked if p is not None]
        enter(doc, picked[0] if picked else systems(doc)[-1])


class PrimaryCommand:
    def GetResources(self):
        return {"Pixmap": _icon("profile.svg", "WE_PrimaryMember"), "MenuText": "Primary Member",
                "ToolTip": "Places primary structural members in the Structure System."}

    def IsActive(self):
        if not in_mode():
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        doc = App.ActiveDocument
        picked = [(s.Object, n) for s in Gui.Selection.getSelectionEx() for n in (s.SubElementNames or [""])]
        doc.openTransaction(PRIMARY_LABEL)
        try:
            obj = make_primary(doc)
            panel = Panel(obj, True)
            Gui.Control.showDialog(panel)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        for o, n in picked:
            panel.picked(o.Document.Name, o.Name, n)


class SecondaryCommand:
    def GetResources(self):
        return {"Pixmap": _icon("profile.svg", "WE_SecondaryMember"), "MenuText": "Secondary Member",
                "ToolTip": "Creates a secondary member between existing members."}

    def IsActive(self):
        doc = App.ActiveDocument
        if not in_mode(doc) or not wemember.structural_members(doc):
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        doc = App.ActiveDocument
        picked = [(s.Object, n) for s in Gui.Selection.getSelectionEx() for n in (s.SubElementNames or [""])]
        doc.openTransaction(SECONDARY_LABEL)
        try:
            obj = make_secondary(doc)
            panel = SecondaryPanel(obj, True)
            Gui.Control.showDialog(panel)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        for o, n in picked:
            panel.picked(o.Document.Name, o.Name, n)



def primary_of_body(body):
    """The Primary Member whose members include body, else None."""
    if body is None:
        return None
    for o in body.Document.Objects:
        if is_primary(o) and body in list(getattr(o, "Bodies", []) or []) + list(getattr(o, "Members", []) or []):
            return o
    return None


def editable_length(sm):
    return sm is not None and sm.MemberType == "Points And Length" and getattr(sm, "EndCondition", "Length") == "Length"


class LengthEdit(QtWidgets.QDoubleSpinBox):
    """The member length, over the graphics area where the member was double-clicked: Enter (or a click
    away) takes it, Esc leaves it as it was."""

    def __init__(self, sm, at=None):
        mw = Gui.getMainWindow()
        view = None
        try:
            view = Gui.ActiveDocument.ActiveView.graphicsView()
        except Exception:
            view = None
        super().__init__(view or mw)
        self.sm = sm
        self.setObjectName("SWSSLengthEdit")
        self.setRange(0.001, 1.0e7)
        self.setDecimals(2)
        self.setSuffix(" mm")
        self.setValue(float(sm.Length))
        self.setToolTip("%s: member length" % sm.Label)
        self.setKeyboardTracking(False)
        self.done = False
        try:
            if at is not None and view is not None:
                x, y = Gui.ActiveDocument.ActiveView.getPointOnViewport(at)
                self.move(int(x) + 8, int(view.height() - y) - self.sizeHint().height() // 2)
        except Exception as _fw_err:
            _fw_log("westructure.py:1889", _fw_err)
        self.show()
        self.raise_()
        self.setFocus()
        self.selectAll()

    def keyPressEvent(self, e):
        if e.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.take()
            return
        if e.key() == QtCore.Qt.Key_Escape:
            self.finish()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        QtCore.QTimer.singleShot(0, self.take)

    def take(self):
        if self.done:
            return
        self.interpretText()
        value = self.value()
        sm = self.sm
        if abs(float(sm.Length) - value) > 1e-9:
            doc = sm.Document
            doc.openTransaction("Member length")
            try:
                sm.Length = value
                wemember.refresh(doc)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
        self.finish()

    def finish(self):
        self.done = True
        global _length_edit
        _length_edit = None
        self.hide()
        self.deleteLater()


_length_edit = None


def edit_length(sm, at=None):
    """Shows the length box for a Points And Length member (Length end condition)."""
    global _length_edit
    if not editable_length(sm) or in_mode(sm.Document):
        return None
    if _length_edit is not None:
        try:
            _length_edit.finish()
        except RuntimeError as _fw_err:
            _fw_log("westructure.py:1942", _fw_err)
    _length_edit = LengthEdit(sm, at)
    return _length_edit


class _DoubleClickWatch:
    """A second pick of the same member within the double-click time: its length to change."""

    def __init__(self):
        self.last = (None, 0.0)

    def addSelection(self, doc, name, sub, point):
        import time
        try:
            body = App.getDocument(doc).getObject(name)
        except Exception:
            return
        now = time.time()
        was, t = self.last
        self.last = (name, now)
        gap = QtWidgets.QApplication.doubleClickInterval() / 1000.0
        if was != name or now - t > gap:
            return
        sm = primary_of_body(body)
        if editable_length(sm):
            at = App.Vector(*point) if point else None
            QtCore.QTimer.singleShot(0, lambda: edit_length(sm, at))


_watch = None


def watch_double_clicks():
    global _watch
    if _watch is None:
        _watch = _DoubleClickWatch()
        Gui.Selection.addObserver(_watch)
    return _watch


def register():
    watch_double_clicks()
    if SYSTEM_COMMAND not in Gui.listCommands():
        Gui.addCommand(SYSTEM_COMMAND, SystemCommand())
        Gui.addCommand(PRIMARY_COMMAND, PrimaryCommand())
        Gui.addCommand(SECONDARY_COMMAND, SecondaryCommand())
    if EDIT_COMMAND not in Gui.listCommands():
        Gui.addCommand(EDIT_COMMAND, EditSystemCommand())
