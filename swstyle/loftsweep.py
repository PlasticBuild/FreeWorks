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

from . import simplefeature as sf
from . import surfacepms as sp
from .simplefeature import Field

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = QtCore = QtWidgets = None

V = App.Vector
CONSTRAINTS = ("None", "Direction Vector", "Normal To Profile", "Tangency To Face", "Curvature To Face")
THIN_TYPES = ("One-Direction", "Mid-Plane", "Two-Direction")
SCOPES = ("All bodies", "Selected bodies")
SWEEP_TWISTS = sp.SWEEP_TWISTS        # with Follow Path and 1st Guide Curve / Follow 1st and 2nd Guide Curves
SWEEP_DIRECTIONS = ("Direction 1", "Bidirectional", "Direction 2")
TANGENCY = ("None", "Path Tangent")
CUT_PROFILES = tuple(sp.SWEEP_PROFILES) + ("Solid Profile",)


# --------------------------------------------------------------------------- picks
GROUP_PROP = "%sGroupEdges"


def kept_edges(obj, name):
    """The sketch edges a pick field keeps as they are ("Sketch.Edge1"): a SelectionManager group, or
    the edges of a FreeCAD path moved over to this feature."""
    return list(getattr(obj, GROUP_PROP % name, None) or [])


def keep_edges(obj, name, source, subs):
    """Marks (source, subs) of a pick field as a chosen group of the sketch's edges, not the whole
    sketch (features-465)."""
    prop = GROUP_PROP % name
    if prop not in obj.PropertiesList:
        obj.addProperty("App::PropertyStringList", prop, "Sweep",
                        "Edges of the sketch picked as a group for %s (SelectionManager): only these are used" % name)
        try:
            obj.setEditorMode(prop, 2)
        except Exception as _fw_err:
            _fw_log("loftsweep.py:keep_edges", _fw_err)
    setattr(obj, prop, ["%s.%s" % (source.Name, s) for s in subs if s])


def _sketch_part(source, subs):
    """True when subs name some, not all, of a sketch's edges."""
    try:
        edges = len(source.Shape.Edges)
    except Exception:
        return False
    names = {s for s in subs if s and s.startswith("Edge")}
    return bool(names) and len(names) < edges and len(names) == len([s for s in subs if s])


def _links(obj, name):
    ""



    out, seen = [], set()
    kept = set(kept_edges(obj, name))
    items = getattr(obj, name, None) or []
    picked = {"%s.%s" % (source.Name, s) for source, subs in items
              for s in (subs if isinstance(subs, (list, tuple)) else [subs])}
    kept = kept if kept and picked == kept else set()      # a new click replaced the group: whole sketch again
    for source, subs in items:
        subs = subs if isinstance(subs, (list, tuple)) else [subs]
        if kept and subs and all(s and "%s.%s" % (source.Name, s) in kept for s in subs):
            for sub in subs:
                out.append((source, [sub]))
            continue
        if source.isDerivedFrom("Sketcher::SketchObject") or source.TypeId.startswith("Part::Part2D"):
            if source.Name not in seen:
                seen.add(source.Name)
                out.append((source, [""]))
            continue
        for sub in subs or [""]:
            out.append((source, [sub]))
    return out


class _Held:
    """A shape standing in for a picked object (a profile turned square to the path)."""
    TypeId = ""

    def __init__(self, shape):
        self.Shape = shape

    def isDerivedFrom(self, _kind):
        return False


SURFACE_DEFAULTS = {"MicroTolerance": False, "MergeSmooth": True, "GuideInfluence": "Global"}


class _Settings:
    """surfacepms' Loft/Sweep maths read their settings off a feature; this hands them ours, under
    the names they use, and catches the Shape they set."""

    def __init__(self, obj, **names):
        self.__dict__["_obj"], self.__dict__["_names"], self.__dict__["Shape"] = obj, names, None

    def __getattr__(self, name):
        if name in self._names:
            value = self._names[name]
            return value(self._obj) if callable(value) else value
        try:
            return getattr(self._obj, name)
        except AttributeError:
            # a setting surfacepms' surface has and this solid feature does not (MicroTolerance,
            # added to the Lofted Surface later): its default, off
            if name.startswith("_") or name in ("Proxy", "ViewObject"):
                raise
            return SURFACE_DEFAULTS.get(name)

    def __setattr__(self, name, value):
        self.__dict__[name] = value


# --------------------------------------------------------------------------- solid and thin
def _cap(wire):
    if isinstance(wire, Part.Vertex) or not wire.isClosed():
        return []
    try:
        return [Part.Face(wire)]
    except Exception:
        try:
            return Part.makeFilledFace(wire.Edges).Faces
        except Exception:
            return []


def _open_edges(skin):
    """The skin's open boundary (a seam of a round face is not open)."""
    shells = skin.Shells or [Part.makeShell(skin.Faces)]
    return [e for sh in shells for e in sh.getFreeEdges().Edges]


def _skin_ends(skin, ends):
    """The end profiles to cap the skin on. Where the skin's own open boundary runs round an end
    profile (a held loft's skin is built through points on it, within a micron or so), that boundary
    is used, so the caps share the skin's edges and the shell closes without sewing."""
    try:
        loops = [Part.Wire(es) for es in Part.sortEdges(_open_edges(skin))]
    except Exception:
        loops = []
    out = []
    for w in ends:
        pick = w
        if not isinstance(w, Part.Vertex) and w.isClosed():
            size = max(w.BoundBox.DiagonalLength, 1e-6)
            for lp in loops:
                if (lp.isClosed() and abs(lp.Length - w.Length) < 1e-3 * size
                        and lp.CenterOfMass.distanceToPoint(w.CenterOfMass) < 1e-3 * size):
                    far = max(e.distToShape(w)[0] for e in lp.Edges)
                    if far < 1e-3 * size:
                        pick = lp
                        break
        out.append(pick)
    return out


def _solid(skin, ends):
    """The loft or sweep skin closed by flat faces on its end profiles."""
    if skin.Solids:
        return skin
    faces = list(skin.Faces)
    for w in _skin_ends(skin, ends):
        faces.extend(_cap(w))
    shell = Part.makeShell(faces)
    if shell.isClosed():
        solid = Part.Solid(shell)
        if solid.Volume < 0:
            solid.reverse()
        if not solid.isValid():
            solid.fix(1e-6, 1e-6, 1e-6)
        return solid
    try:
        shell.sewShape()
    except Exception as _fw_err:
        _fw_log("loftsweep.py:170", _fw_err)
    shell = shell.Shells[0] if shell.Shells else shell
    if not shell.isClosed():
        try:                    # a loft through connectors: its strips meet within a micron or so
            from . import sewtol
            shell = sewtol.sewn(faces, 1e-3)
            shell = shell.Shells[0] if shell.Shells else shell
        except Exception as _fw_err:
            _fw_log("loftsweep.py:178", _fw_err)
    solid = Part.Solid(shell)
    if solid.Volume < 0:
        solid.reverse()
    if not solid.isValid():
        solid.fix(1e-6, 1e-6, 1e-6)
    return solid


def _sides(obj):
    """Thin Feature: how far the wall goes out from the profile, and how far in."""
    t1, t2 = float(obj.Thickness), float(getattr(obj, "Thickness2", 0.0))
    kind = obj.ThinType
    if kind == "Mid-Plane":
        out, back = t1 / 2.0, t1 / 2.0
    elif kind == "Two-Direction":
        out, back = t1, t2
    else:
        out, back = (0.0, t1) if obj.ThinReverse else (t1, 0.0)
    if out + back <= 0:
        raise RuntimeError("The thin feature thickness must be more than 0")
    return out, back


def _offset(wire, d):
    """A profile grown (d > 0) or shrunk in its own plane, corners kept sharp."""
    if abs(d) < 1e-12 or isinstance(wire, Part.Vertex):
        return wire
    grown = wire.makeOffset2D(d, 2, False, False, False)
    return grown.Wires[0] if grown.Wires else grown


def _thin(obj, build, skin):
    """Thin Feature: a wall of the set thickness, its ends left open. Closed profiles: the loft or
    sweep of the profiles grown, less the one of the profiles shrunk; open ones: the skin thickened."""
    out, back = _sides(obj)
    try:
        outer = _solid(*build(out))
        inner = _solid(*build(-back))
        wall = outer.cut(inner)
        if wall.Solids and wall.isValid():
            return wall
    except Exception as error:
        App.Console.PrintLog("FreeCAD: thin from offset profiles: %s\n" % error)
    skin = Part.makeShell(skin.Faces) if not isinstance(skin, Part.Shell) else skin
    start = skin.makeOffsetShape(-back, 1e-6, fill=False) if back > 0 else skin
    start = start.Shells[0] if start.Shells else start
    return start.makeOffsetShape(out + back, 1e-6, fill=True)


def _finish(obj, base, build):
    """Close or thicken the skin and add it to, or cut it from, the part. build(d) gives the skin
    and its end profiles for the profiles grown by d."""
    skin, ends = build(0.0)
    if skin is None or skin.isNull() or not skin.Faces:
        raise RuntimeError("The profiles give no shape")
    tool = _thin(obj, build, skin) if getattr(obj, "Thin", False) else _solid(skin, ends)
    if not tool.Solids:
        raise RuntimeError("The profiles do not close into a solid: use Thin Feature or closed profiles")
    if base is None or base.isNull():
        return tool, tool
    if getattr(obj, "AlignEndFaces", False) and not getattr(obj, "Thin", False):
        tool = _align_ends(tool, ends, base, obj.SWStyleKind.startswith("Cut"))
    if obj.SWStyleKind.startswith("Cut"):
        return _scoped_cut(obj, base, tool), tool
    if not getattr(obj, "Merge", True):
        return Part.makeCompound(list(base.Solids) + list(tool.Solids)), tool
    return base.fuse(tool), tool


def _align_ends(tool, ends, base, cut):
    ""


    reach = base.BoundBox.DiagonalLength + tool.BoundBox.DiagonalLength
    extra = []
    for w in ends:
        try:
            face = Part.Face(w)
            c = face.CenterOfMass
            n = face.normalAt(0, 0)
            step = max(1e-3, w.BoundBox.DiagonalLength * 1e-3)
            if tool.isInside(c + n * step, 1e-7, False):
                n = n * -1
            grow = face.extrude(n * reach)
            pieces = grow.common(base) if cut else grow.cut(base)
            size = w.BoundBox.DiagonalLength
            for p in pieces.Solids:
                depth = max((v.Point - c).dot(n) for v in p.Vertexes)
                # the gap (or sliver) right at the end, meeting a face of the part: not a run out into space
                if p.distToShape(face)[0] < 1e-6 and depth <= size and (cut or p.distToShape(base)[0] < 1e-6):
                    extra.append(p)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: align with end faces: %s\n" % error)
    if not extra:
        return tool
    try:
        joined = tool.fuse(extra).removeSplitter()
        return joined if joined.Solids else tool
    except Exception:
        return tool


def _scoped_cut(obj, base, tool):
    """Feature Scope: the cut takes all the part's bodies, or only the ones picked."""
    solids = list(base.Solids)
    if len(solids) < 2 or getattr(obj, "Scope", "All bodies") == "All bodies" or getattr(obj, "AutoSelect", False):
        return base.cut(tool)      # Auto-select: every body the cut reaches, as All bodies does
    picked = [s for _o, s in sf.elements(obj, "Bodies")]
    keep = []
    for s in solids:
        hit = any(body_holds(s, p) for p in picked)
        keep.extend(s.cut(tool).Solids if hit else [s])
    return Part.makeCompound(keep)


def body_holds(solid, picked):
    """The picked item (a face, edge or vertex clicked on a body, or a solid) is on this body."""
    if picked is None or picked.isNull():
        return False
    if picked.Solids:
        return any(solid.isSame(p) or (abs(solid.Volume - p.Volume) < 1e-6 and solid.distToShape(p)[0] < 1e-6)
                   for p in picked.Solids)
    if any(picked.isSame(f) for f in solid.Faces) or any(picked.isSame(e) for e in solid.Edges):
        return True
    try:
        return solid.distToShape(picked)[0] < 1e-7 and solid.isInside(picked.CenterOfMass, 1e-6, True)
    except Exception as _fw_err:
        _fw_log("loftsweep.py:307", _fw_err)
        return False


# --------------------------------------------------------------------------- Loft
def _loft(obj, base):
    links = _links(obj, "Profiles")
    if len(links) < 2:
        return None, None
    ps0 = sp.connect(sp.profiles(links), getattr(obj, "Connectors", None))

    def build(d):
        ps = [_offset(p, d) for p in ps0]
        held = [(_Held(p), [""]) for p in ps]
        names = dict(Profiles=held, Guides=lambda o: _links(o, "Guides"), Centerline=lambda o: _links(o, "Centerline"),
                     StartVector=lambda o: _links(o, "StartVector"), EndVector=lambda o: _links(o, "EndVector"),
                     MergeTangent=lambda o: bool(o.MergeTangent), Close=lambda o: bool(o.Close))
        if any(getattr(obj, e + "Constraint") in ("Tangency To Face", "Curvature To Face") for e in ("Start", "End")):
            names["Profiles"] = links if abs(d) < 1e-12 else held     # the face beside the picked edge
        s = _Settings(obj, **names)
        guides = sp.wires(_links(obj, "Guides"))
        if guides and not _links(obj, "Centerline"):
            skin = sp.guided_loft(ps, guides, bool(obj.Close), per=max(2, int(obj.Sections)),
                                  influence=getattr(obj, "GuideInfluence", None) or "Global")
            if obj.MergeTangent:
                try:
                    skin = skin.removeSplitter()
                except Exception as _fw_err:
                    _fw_log("loftsweep.py:333", _fw_err)
        else:
            sp.SurfaceLoft.execute(object.__new__(sp.SurfaceLoft), s)
            skin = s.Shape
        return skin, ([] if obj.Close else [ps[0], ps[-1]])

    return _finish(obj, base, build)


def _end_fields(end):
    on = lambda kinds: (lambda o: getattr(o, end + "Constraint", "None") in kinds)
    return [
        Field(end + "Constraint", "enum", "%s constraint" % end, "None", values=list(CONSTRAINTS), box="Start/End Constraints"),
        Field(end + "Vector", "pick", "%s direction vector" % end, what=("Edge", "Face"), optional=True,
              shown=on(("Direction Vector",)), box="Start/End Constraints"),
        Field(end + "Reverse", "bool", "Reverse direction (%s)" % end.lower(), False,
              shown=on(CONSTRAINTS[1:]), box="Start/End Constraints"),
        Field(end + "Draft", "angle", "%s draft angle" % end, 0.0, low=0.0, high=89.0,
              shown=on(("Direction Vector", "Normal To Profile")), box="Start/End Constraints"),
        Field(end + "DraftReverse", "bool", "Reverse draft (%s)" % end.lower(), False,
              shown=on(("Direction Vector", "Normal To Profile")), box="Start/End Constraints"),
        Field(end + "Length", "float", "%s tangent length" % end, 1.0, low=0.0, high=10.0,
              shown=on(CONSTRAINTS[1:]), box="Start/End Constraints"),
    ]


def _thin_fields():
    on = lambda o: getattr(o, "Thin", False)
    return [
        Field("Thin", "bool", "Thin Feature", False, box="Thin Feature"),
        Field("ThinType", "enum", "Type", "One-Direction", values=list(THIN_TYPES), shown=on, box="Thin Feature"),
        Field("Thickness", "length", "Thickness", 1.0, shown=on, box="Thin Feature"),
        Field("ThinReverse", "bool", "Reverse direction", False,
              shown=lambda o: on(o) and getattr(o, "ThinType", "") == "One-Direction", box="Thin Feature"),
        Field("Thickness2", "length", "Direction 2 thickness", 1.0,
              shown=lambda o: on(o) and getattr(o, "ThinType", "") == "Two-Direction", box="Thin Feature"),
    ]


def _scope_fields():
    return [Field("Scope", "radio", "Feature Scope", "All bodies", values=list(SCOPES), box="Feature Scope"),
            Field("AutoSelect", "bool", "Auto-select", False,
                  shown=lambda o: getattr(o, "Scope", "") == "Selected bodies", box="Feature Scope",
                  tip="Cut every body the feature reaches; off: pick the bodies"),
            Field("Bodies", "pick", "Solid bodies to affect", what=("Face", "Edge", "Vertex"), many=True, optional=True,
                  shown=lambda o: getattr(o, "Scope", "") == "Selected bodies" and not getattr(o, "AutoSelect", False),
                  box="Feature Scope", tip="Click a face of each body to cut")]


def _loft_fields(cut):
    fields = [Field("Profiles", "pick", "Profiles", what=("Edge", "Face", "Vertex"), many=True, box="Profiles"),
              Field("Connectors", "pick", "Connectors", what=("Vertex",), many=True, optional=True, box="Profiles",
                    tip="A corner on each profile: the loft joins them with one edge")]
    fields += _end_fields("Start") + _end_fields("End")
    fields += [Field("Guides", "pick", "Guide curves", what=("Edge",), many=True, optional=True, box="Guide Curves",
                     group=True),
               Field("GuideInfluence", "enum", "Guide curves influence", "To Next Guide", values=list(sp.GUIDE_INFLUENCE),
                     box="Guide Curves", tip="How far along the profile each guide curve pulls it"),
               Field("Centerline", "pick", "Centerline", what=("Edge", ""), optional=True, box="Centerline Parameters"),
               Field("Sections", "int", "Number of sections", 12, low=2, high=100, box="Centerline Parameters"),
               Field("MergeTangent", "bool", "Merge tangent faces", True, box="Options"),
               Field("Close", "bool", "Close loft", False, box="Options"),
               Field("MicroTolerance", "bool", "Micro tolerance", False, box="Options",
                     tip="A finer tolerance for lofts of very small geometry")]
    if not cut:
        fields.append(Field("Merge", "bool", "Merge result", True, box="Options"))
    fields.append(Field("ShowPreview", "bool", "Show preview", True, box="Options"))
    fields += _thin_fields()
    if cut:
        fields += _scope_fields()
    return fields


LOFT = sf.Spec("SWStyle_SolidLoft", "Loft", "Loft",
               "Lofted Boss/Base with start/end constraints, guide curves, centerline and thin feature.",
               "FEATURES_LOFTED_BOSS", "PartDesign_AdditiveLoft", _loft_fields(False), _loft, needs_body=False)
CUT_LOFT = sf.Spec("SWStyle_SolidCutLoft", "Cut-Loft", "Cut-Loft",
                   "Lofted Cut with start/end constraints, guide curves, centerline, thin feature and feature scope.",
                   "FEATURES_LOFTED_CUT", "PartDesign_SubtractiveLoft", _loft_fields(True), _loft, subtractive=True)


# --------------------------------------------------------------------------- Sweep
def _turned_square(profile, path):
    """Start tangency Path Tangent: the profile turned about its centre to stand square to the path."""
    if isinstance(profile, Part.Vertex):
        return profile
    plane = profile.findPlane()
    if plane is None:
        return profile
    first = path.OrderedVertexes[0].Point
    e = path.OrderedEdges[0]
    t = e.tangentAt(e.FirstParameter if (e.valueAt(e.FirstParameter) - first).Length < 1e-6 else e.LastParameter)
    n = V(plane.Axis)
    if n.dot(t) < 0:
        n = -n
    rot = App.Rotation(n, t)
    c = sp._centre(profile)
    turned = profile.copy()
    turned.rotate(c, rot.Axis, math.degrees(rot.Angle))
    return turned


def _start_tangent(path):
    first = path.OrderedVertexes[0].Point
    e = path.OrderedEdges[0]
    t = e.tangentAt(e.FirstParameter if (e.valueAt(e.FirstParameter) - first).Length < 1e-6 else e.LastParameter)
    return first, V(t).normalize()


def _split_path(path, point):
    """The path cut where the profile sits: (from there to the path's end, from there back to its
    start), each starting at the cut. None when the profile is at an end of the path."""
    edges = list(path.OrderedEdges)
    best = min(range(len(edges)), key=lambda k: edges[k].distToShape(Part.Vertex(point))[0])
    e = edges[best]
    hit = e.distToShape(Part.Vertex(point))[1][0][0]
    u = e.Curve.parameter(hit)
    a, b = e.FirstParameter, e.LastParameter
    start, end = path.OrderedVertexes[0].Point, path.OrderedVertexes[-1].Point
    if (hit - start).Length < 1e-6 or (hit - end).Length < 1e-6:
        return None
    first_part = Part.Edge(e.Curve, a, u) if u - a > 1e-9 else None
    second_part = Part.Edge(e.Curve, u, b) if b - u > 1e-9 else None
    # the ordered path may run through this edge backwards
    if (e.valueAt(a) - path.OrderedVertexes[best].Point).Length > 1e-6:
        first_part, second_part = second_part, first_part
    before = edges[:best] + ([first_part] if first_part is not None else [])
    after = ([second_part] if second_part is not None else []) + edges[best + 1:]
    ahead = Part.Wire(Part.__sortEdges__(after)) if after else None
    behind = Part.Wire(Part.__sortEdges__(before)) if before else None
    if ahead is not None and (ahead.OrderedVertexes[0].Point - hit).Length > 1e-6:
        ahead = Part.Wire([x.reversed() for x in reversed(ahead.OrderedEdges)])
    if behind is not None and (behind.OrderedVertexes[0].Point - hit).Length > 1e-6:
        behind = Part.Wire([x.reversed() for x in reversed(behind.OrderedEdges)])
    return ahead, behind


# --------------------------------------------------------------------------- Swept Cut, Solid Profile
def _tool_solid(obj, base):
    """The tool body picked for a Solid Profile sweep: the part's body the pick is on, else the
    picked object's own solid."""
    picks = sf.elements(obj, "ToolBody")
    if not picks:
        return None
    source, shape = picks[0]
    solids = list(base.Solids) if base is not None and not base.isNull() else []
    for s in solids:            # a face, edge or vertex of one of the part's bodies, or the body itself
        if (shape.Solids and body_holds(s, shape)) or any(shape.isSame(x) for x in s.Faces + s.Edges + s.Vertexes):
            return s
    own = shape.Solids[0] if shape.Solids else None
    if own is None:
        whole = Part.getShape(source)
        own = whole.Solids[0] if whole.Solids else None
    try:
        here = obj.getParentGeoFeatureGroup()
        outside = source is not here and source.getParentGeoFeatureGroup() is not here
    except Exception:
        outside = False
    if outside and own is not None:
        # a solid of another object (a ball touching the part): its own solid, not the part it touches
        return own
    for s in solids:
        if body_holds(s, shape):
            return s
    return own


def _revolve_axis(solid):
    """(point, unit direction) of the axis a tool body is turned about, or None when it is not a
    body of revolution (its round faces share no axis, or a flat face is not square to it)."""
    axis, spheres = None, []
    for f in solid.Faces:
        s = f.Surface
        kind = type(s).__name__
        if kind in ("Cylinder", "Cone"):
            here = (V(s.Center) if kind == "Cylinder" else V(s.Apex), V(s.Axis).normalize())
        elif kind == "SurfaceOfRevolution":
            here = (V(s.Location), V(s.Direction).normalize())
        elif kind == "Sphere":
            spheres.append(V(s.Center))
            continue
        elif kind == "Plane":
            continue
        else:
            return None
        if axis is None:
            axis = here
        elif abs(abs(axis[1].dot(here[1])) - 1) > 1e-6 or (here[0] - axis[0]).cross(axis[1]).Length > 1e-5:
            return None
    if axis is None:
        return None if not spheres else (spheres[0], None)
    for c in spheres:
        if (c - axis[0]).cross(axis[1]).Length > 1e-5:
            return None
    for f in solid.Faces:
        if type(f.Surface).__name__ == "Plane" and abs(abs(V(f.Surface.Axis).dot(axis[1])) - 1) > 1e-6:
            return None
    return axis


def _path_tangents(path, n=16):
    out = []
    for e in path.Edges:
        a, b = e.FirstParameter, e.LastParameter
        for k in range(n + 1):
            out.append(V(e.tangentAt(a + (b - a) * k / n)).normalize())
    return out


def _solid_envelope(tool, path):
    ""



    first, t0 = _start_tangent(path)
    axis = _revolve_axis(tool)
    if axis is not None and axis[1] is None:
        # a sphere: any axis square to the path's plane
        plane = path.findPlane() if len(path.Edges) else None
        d = V(plane.Axis) if plane is not None else t0.cross(V(0, 0, 1) if abs(t0.z) < 0.9 else V(1, 0, 0))
        axis = (axis[0], d.normalize())
    exact = axis is not None and all(abs(t.dot(axis[1])) < 1e-6 for t in _path_tangents(path))
    if axis is not None:
        c, a = axis
        foot = c + a * ((first - c).dot(a))
    else:
        foot = tool.BoundBox.Center
    shift = foot - first
    moved = path.copy()
    moved.translate(shift)
    corners = [v.Point for v in moved.OrderedVertexes]
    pieces = []
    if exact:
        # edge by edge (a sharp corner is filled by the body placed there), each from its own start
        for e in moved.Edges:
            e = e.Curve.toShape(e.FirstParameter, e.LastParameter)     # its own direction: starts at FirstParameter
            p0 = e.valueAt(e.FirstParameter)
            t = V(e.tangentAt(e.FirstParameter)).normalize()
            here = tool.translated(p0 - foot)
            wires = here.slice(t, p0.dot(t))
            if not wires:
                raise RuntimeError("The tool body does not cross the path")
            ps = Part.BRepOffsetAPI.MakePipeShell(Part.Wire([e]))
            ps.setBiNormalMode(a)
            ps.add(wires[0], False, False)
            ps.build()
            ps.makeSolid()
            swept = ps.shape()
            if not swept.Solids:
                raise RuntimeError("The tool body's section does not sweep into a solid")
            pieces.append(swept)
    else:
        length = moved.Length
        size = max(tool.BoundBox.DiagonalLength, 1e-6)
        n = int(min(400, max(32, 6 * length / size)))
        for k in range(1, n):
            d = moved.discretize(Number=n + 1)[k]
            pieces.append(tool.translated(d - foot))
    for p in corners:
        pieces.append(tool.translated(p - foot))
    env = pieces[0].fuse(pieces[1:]) if len(pieces) > 1 else pieces[0]
    try:
        env = env.removeSplitter()
    except Exception as _fw_err:
        _fw_log("loftsweep.py:584", _fw_err)
    return env


def _solid_sweep(obj, base):
    paths = _links(obj, "Path")
    tool = _tool_solid(obj, base)
    if not paths or tool is None:
        return None, None
    path = sp.wires(paths)[0]
    env = _solid_envelope(tool, path)
    if base is None or base.isNull():
        raise RuntimeError("A Solid Profile sweep cuts the part: there is nothing to cut")
    keep = [s for s in base.Solids if not s.isSame(tool) and not (abs(s.Volume - tool.Volume) < 1e-6 and s.distToShape(tool)[0] < 1e-9 and s.isInside(tool.CenterOfMass, 1e-6, True))]
    others = Part.makeCompound(keep) if len(keep) != 1 else keep[0]
    cut = _scoped_cut(obj, others, env) if keep else Part.Shape()
    solids = list(cut.Solids) if not cut.isNull() else []
    if len(keep) < len(base.Solids):
        solids.append(tool)            # the tool body stays in the part (Solid Bodies)
    return Part.makeCompound(solids) if len(solids) != 1 else solids[0], env


def _profile_halves(obj, path=None, profile_links=None):
    """(ahead, behind): the path split at a sketch profile it runs through part way along, or None."""
    try:
        if path is None:
            path = sp.wires(_links(obj, "Path"))[0]
        prof = sp.wires(profile_links if profile_links is not None else _links(obj, "Profile"))[0]
        plane = prof.findPlane()
        centre = sp._centre(prof)
        gap, pairs, _i = path.distToShape(Part.Vertex(centre))
        on_plane = plane is not None and abs((pairs[0][0] - centre).dot(V(plane.Axis))) < 1e-6
        # only a profile the path runs through, part way along it
        if on_plane and gap < prof.BoundBox.DiagonalLength:
            return _split_path(path, centre)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sweep direction: %s\n" % error)
    return None


def _both_ways(obj):
    ""

    if not _links(obj, "Path") or not _links(obj, "Profile"):
        return False
    halves = _profile_halves(obj)
    return halves is not None and all(w is not None for w in halves)


def _native_both_ways(native):
    """_both_ways for FreeCAD's own Pipe (Profile, Spine)."""
    try:
        prof, spine = getattr(native, "Profile", None), getattr(native, "Spine", None)
        if not prof or not spine or prof[0] is None or spine[0] is None:
            return False

        def links(link):
            o, subs = link[0], link[1] if len(link) > 1 else []
            if o.isDerivedFrom("Sketcher::SketchObject") or not subs:
                return [(o, [""])]
            return [(o, [x]) for x in subs]
        path = sp.wires(links(spine))[0]
        halves = _profile_halves(native, path, links(prof))
        return halves is not None and all(w is not None for w in halves)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sweep direction (page): %s\n" % error)
        return False


def _sweep(obj, base):
    if getattr(obj, "ProfileType", "") == "Solid Profile":
        return _solid_sweep(obj, base)
    if not _links(obj, "Path") or (obj.ProfileType == "Sketch Profile" and not _links(obj, "Profile")):
        return None, None
    path = sp.wires(_links(obj, "Path"))[0]
    way = getattr(obj, "SweepDirection", "Direction 1")
    halves = _profile_halves(obj, path) if obj.ProfileType == "Sketch Profile" else None
    if halves is not None:

        # Direction 2): sweep from it each way asked for
        ahead, behind = halves
        chosen = {"Direction 1": [ahead], "Direction 2": [behind], "Bidirectional": [ahead, behind]}[way]
        chosen = [w for w in chosen if w is not None]
        if not chosen:
            return None, None
        if len(chosen) == 1:
            return _sweep_along(obj, base, chosen[0], held_path=True)

        def both(d):
            solids = [_solid(*_sweep_builder(obj, w, True)(d)) for w in chosen]
            return solids[0].fuse(solids[1:]).removeSplitter(), []
        return _finish(obj, base, both)
    return _sweep_along(obj, base, path)


def _sweep_along(obj, base, path, held_path=False):
    return _finish(obj, base, _sweep_builder(obj, path, held_path))


def _sweep_builder(obj, path, held_path=False):
    first, tangent = _start_tangent(path)
    circular = obj.ProfileType == "Circular Profile"
    square = "Path Tangent" in (obj.StartTangency, obj.EndTangency)
    sketch = None if circular else sp.wires(_links(obj, "Profile"))[0]
    if sketch is not None and square:
        # Path Tangent: the profile stands square to the path, so the sweep leaves the start and
        # meets the end along the path's own direction
        sketch = _turned_square(sketch, path)

    def build(d):
        names = dict(Path=(lambda o: [(_Held(path), [""])]) if held_path else (lambda o: _links(o, "Path")),
                     Guides=lambda o: _links(o, "Guides"),
                     DirectionVector=lambda o: _links(o, "DirectionVector"), Twist=obj.Twist,
                     TwistUnit=obj.TwistUnit, MergeTangent=lambda o: bool(o.MergeTangent))
        if circular:
            dia = float(obj.Diameter) + 2 * d
            if dia <= 0:
                raise RuntimeError("The thin feature is thicker than the circular profile")
            names["Diameter"] = App.Units.Quantity(dia, App.Units.Length)
            start = Part.Wire(Part.makeCircle(dia / 2, first, tangent))
        else:
            start = _offset(sketch, d)
            names["Profile"] = [(_Held(start), [""])] if (square or abs(d) > 1e-12) else (lambda o: _links(o, "Profile"))
        s = _Settings(obj, **names)
        sp.SurfaceSweep.execute(object.__new__(sp.SurfaceSweep), s)
        skin = s.Shape
        ends = [start]
        if skin is not None and not skin.Solids:
            if path.isClosed():
                ends = []
            else:
                # the far end: the free closed loop that is not the start profile
                c = sp._centre(start)
                loops = [Part.Wire(es) for es in Part.sortEdges(_open_edges(skin))]
                ends += [w for w in loops if w.isClosed() and (sp._centre(w) - c).Length > 1e-4][:1]
        return skin, ends

    return build


def _sweep_fields(cut):
    circ = lambda o: getattr(o, "ProfileType", "") == "Circular Profile"
    solid = lambda o: getattr(o, "ProfileType", "") == "Solid Profile"
    sketch = lambda o: not circ(o) and not solid(o)
    other = lambda o: not solid(o)
    twist = lambda o: getattr(o, "Twist", "") == "Specify Twist Value"
    fields = [
        Field("ProfileType", "radio", "Profile and Path", "Sketch Profile",
              values=list(CUT_PROFILES if cut else sp.SWEEP_PROFILES), box="Profile and Path"),

        Field("Profile", "pick", "Profile", what=("Edge", "Face", ""), many=True, optional=True, shown=sketch,
              box="Profile and Path"),
        Field("Path", "pick", "Path", what=("Edge", ""), many=True, box="Profile and Path", group=True),
        Field("SweepDirection", "radio", "Direction", "Direction 1", values=list(SWEEP_DIRECTIONS),
              shown=lambda o: sketch(o) and _both_ways(o),
              box="Profile and Path", tip="With the profile part way along the path: sweep one way, the other, or both"),
        Field("Diameter", "length", "Diameter", 10.0, shown=circ, box="Profile and Path"),
        Field("Orientation", "enum", "Profile orientation", "Follow Path", values=list(sp.SWEEP_ORIENTATIONS),
              box="Options"),
        Field("Twist", "enum", "Profile twist", "None", values=list(SWEEP_TWISTS), box="Options"),
        Field("TwistUnit", "enum", "Twist control", "Degrees", values=list(sp.TWIST_UNITS), shown=twist, box="Options"),
        Field("TwistValue", "float", "Twist value", 0.0, low=-36000.0, high=36000.0, shown=twist, box="Options"),
        Field("TwistReverse", "bool", "Reverse twist", False, shown=twist, box="Options"),
        Field("DirectionVector", "pick", "Direction vector", what=("Edge", "Face"), optional=True,
              shown=lambda o: getattr(o, "Twist", "") == "Specify Direction Vector", box="Options"),
        Field("MergeTangent", "bool", "Merge tangent faces", True, box="Options"),
    ]
    if not cut:
        fields.append(Field("Merge", "bool", "Merge result", True, box="Options"))
    fields += [Field("ShowPreview", "bool", "Show preview", True, box="Options"),
               Field("AlignEndFaces", "bool", "Align with end faces", False, box="Options",
                     tip="Carries the sweep on to the faces the path ends on, so its ends meet them"),
               Field("Guides", "pick", "Guide curves", what=("Edge",), many=True, optional=True, box="Guide Curves",
                     group=True),
               Field("MergeSmooth", "bool", "Merge smooth faces", True, box="Guide Curves",
                     tip="Off: the sweep is split into faces where the path or a guide curve has a corner or joint"),
               Field("StartTangency", "enum", "Start tangency type", "None", values=list(TANGENCY),
                     box="Start/End Tangency"),
               Field("EndTangency", "enum", "End tangency type", "None", values=list(TANGENCY),
                     box="Start/End Tangency")]
    fields += _thin_fields()
    if cut:
        fields += _scope_fields()
        # Solid Profile: a tool body moved along the path; the profile's own options do not apply
        at = next(i for i, f in enumerate(fields) if f.name == "Path")
        fields.insert(at, Field("ToolBody", "pick", "Tool body", what=("Face", "Edge", "Vertex"), optional=True,
                                shown=solid, box="Profile and Path",
                                tip="A body of revolution in the part (or another solid) that cuts as it moves along the path"))
        for f in fields:
            if f.box in ("Options", "Guide Curves", "Start/End Tangency", "Thin Feature") and f.name not in ("ShowPreview",):
                own = f.shown
                f.shown = (lambda o, own=own: other(o) and (own is None or own(o)))
    return fields


SWEEP = sf.Spec("SWStyle_SolidSweep", "Sweep", "Sweep",
                "Swept Boss/Base with circular profile, twist value, tangent to adjacent faces and thin feature.",
                "FEATURES_SWEPT_BOSS", "PartDesign_AdditivePipe", _sweep_fields(False), _sweep, needs_body=False)
CUT_SWEEP = sf.Spec("SWStyle_SolidCutSweep", "Cut-Sweep", "Cut-Sweep",
                    "Swept Cut with circular profile, twist value, thin feature and feature scope.",
                    "FEATURES_SWEPT_CUT", "PartDesign_SubtractivePipe", _sweep_fields(True), _sweep, subtractive=True)

ALL = [LOFT, CUT_LOFT, SWEEP, CUT_SWEEP]


def register():
    for spec in ALL:
        sf.register(spec)


# --------------------------------------------------------------------------- from FreeCAD's pages
def _pairs(link):
    """[(obj, [sub])] of a FreeCAD LinkSub / LinkSubList value."""
    if not link:
        return []
    if isinstance(link, tuple) and len(link) == 2 and isinstance(link[0], App.DocumentObject):
        link = [link]
    out = []
    for item in link:
        if isinstance(item, App.DocumentObject):
            out.append((item, [""]))
        else:
            o, subs = item
            subs = list(subs) if isinstance(subs, (list, tuple)) else [subs]
            out.append((o, subs or [""]))
    return out


def picks_of(native):
    """What the FreeCAD Loft or Pipe being edited holds, as this feature's picks and values."""
    picks, values = {}, {}
    if "Loft" in native.TypeId:
        profiles = _pairs(native.Profile) + _pairs(native.Sections)
        picks["Profiles"] = [(o, s) for o, subs in profiles for s in subs]
        values["Close"] = bool(native.Closed)
    else:
        picks["Profile"] = [(o, s) for o, subs in _pairs(native.Profile) for s in subs]
        picks["Path"] = [(o, s) for o, subs in _pairs(native.Spine) for s in subs]
        aux = _pairs(getattr(native, "AuxiliarySpine", None))
        if aux:
            picks["Guides"] = [(o, s) for o, subs in aux for s in subs]
    return picks, values


def convert(native, **values):
    """Moves the FreeCAD Loft or Pipe open in its page over to this feature, with the setting chosen
    (values), and opens this feature's page."""
    doc = native.Document
    spec = {"PartDesign::AdditiveLoft": LOFT, "PartDesign::SubtractiveLoft": CUT_LOFT,
            "PartDesign::AdditivePipe": SWEEP, "PartDesign::SubtractivePipe": CUT_SWEEP}[native.TypeId]
    picks, carried = picks_of(native)
    carried.update(values)
    # FreeCAD's path may be some of a sketch's edges: the new feature keeps those edges, not the sketch
    groups = {}
    for field in ("Path", "Guides"):
        by_source = {}
        for o, s in picks.get(field, []):
            by_source.setdefault(o, []).append(s)
        for o, subs in by_source.items():
            if (o.isDerivedFrom("Sketcher::SketchObject") or o.TypeId.startswith("Part::Part2D")) and _sketch_part(o, subs):
                groups.setdefault(field, []).append((o, subs))
    if values.get("ProfileType") == "Circular Profile" and picks.get("Profile") and not picks.get("Path"):

        # the profile on FreeCAD's page) is the path the circle runs along
        picks["Path"] = picks.pop("Profile")
    name = native.Name
    # FreeCAD's page was making a new feature (its "Make AdditivePipe" step is the last one): this

    made = "Make " + native.TypeId.split("::")[-1]
    try:
        tx = App.getActiveTransaction()
    except Exception:
        tx = None
    top = doc.UndoNames[0] if doc.UndoNames else None
    # FreeCAD 1.1 names the new feature's step after it ("Loft") and keeps it open while its page is:
    # an open step that is the top one is this page's new feature (an edit has no open step)
    new = top is not None and (top == made or (tx is not None and tx[0] == top))
    _cancel_page()
    old = doc.getObject(name)
    if new and old is not None:
        try:
            if doc.UndoNames and doc.UndoNames[0] == top:
                # features-479 (Reviewer): abort only this page's own open step; with another step open
                # nothing is undone here (the removal below still takes the feature away)
                cur = App.getActiveTransaction()
                if cur is not None and tx is not None and cur[0] == top:
                    doc.abortTransaction()
                elif cur is None:
                    doc.undo()
            if doc.getObject(name) is not None:
                body0 = old.getParentGeoFeatureGroup()
                if body0 is not None:
                    body0.removeObject(old)
                doc.removeObject(name)
            doc.recompute()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: drop FreeCAD's new %s: %s\n" % (name, error))
        old = doc.getObject(name)
        if old is None:
            return _keep_groups(sf.make(spec, picks=picks, **carried), groups, True)
    body = sf.body_of(doc)
    if old is not None and body is not None:
        # an existing feature: the new one takes its place in the tree
        doc.openTransaction(spec.title)
        body.Tip = old
        obj = body.newObject(spec.type, spec.internal)
        sf.Feature(obj, spec)
        sf.View(obj.ViewObject)
        label = old.Label
        for field, value in picks.items():
            setattr(obj, field, [(o, [e]) for o, e in value])
        for field, value in carried.items():
            setattr(obj, field, value)
        after = [o for o in old.InList if getattr(o, "BaseFeature", None) == old and o != obj]
        for o in after:
            o.BaseFeature = obj
        body.removeObject(old)
        doc.removeObject(old.Name)
        obj.Label = label           # after the old one is gone, or FreeCAD numbers it (Loft002)
        _keep_groups(obj, groups)
        doc.recompute()
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
        return obj
    return _keep_groups(sf.make(spec, picks=picks, **carried), groups, True)


def _keep_groups(obj, groups, recompute=False):
    if obj is None or not groups:
        return obj
    try:
        for field, pairs in groups.items():
            for o, subs in pairs[:1]:
                keep_edges(obj, field, o, subs)
        if recompute:
            obj.Document.recompute()
    except Exception as _fw_err:
        _fw_log("loftsweep.py:keep_groups", _fw_err)
    return obj


def _cancel_page():
    """Cancel on FreeCAD's page: a new feature goes, an edited one goes back as it was."""
    for box in QtWidgets.QApplication.allWidgets():
        if isinstance(box, QtWidgets.QDialogButtonBox) and box.isVisible():
            button = box.button(QtWidgets.QDialogButtonBox.Cancel)
            if button is not None and button.isVisible():
                button.click()
                break
    else:
        Gui.Control.closeDialog()
    for _i in range(5):
        QtWidgets.QApplication.processEvents()


# --------------------------------------------------------------------------- the boxes on FreeCAD's pages
def _later(native, **values):
    QtCore.QTimer.singleShot(0, lambda: convert(native, **values))


def _activate_soon(name):
    """After the page conversion queued by the same click (_later runs first: connected first)."""
    QtCore.QTimer.singleShot(0, lambda: _activate_box(name, 8))


def _in_task_panel(w):
    """features-479 (Reviewer): only a box of the open task panel in the main window, not a same-named box of
    another window."""
    try:
        if w.window() is not Gui.getMainWindow():
            return False
        p = w.parentWidget()
        while p is not None:
            if p.inherits("Gui::TaskView::TaskView") or "TaskView" in type(p).__name__ or p.objectName() == "TaskView":
                return True
            p = p.parentWidget()
    except Exception:
        return True
    return False


def _activate_box(name, tries):
    ""

    try:
        from . import pmlayout
        for w in QtWidgets.QApplication.allWidgets():
            if isinstance(w, QtWidgets.QListWidget) and w.objectName() == "SWStyle_" + name and w.window().isVisible() \
                    and _in_task_panel(w):
                g = w
                while g is not None and not g.inherits("QSint::ActionGroup"):
                    g = g.parentWidget()
                if g is not None and not pmlayout._group_open(g):
                    pmlayout._show_hide(g)
                if w.isVisible():
                    w.setFocus(QtCore.Qt.OtherFocusReason)
                    if QtWidgets.QApplication.focusWidget() is w and tries <= 4:
                        return
                break
    except Exception as _fw_err:
        _fw_log("loftsweep.py:activate_box", _fw_err)
        return
    if tries > 0:
        QtCore.QTimer.singleShot(250, lambda: _activate_box(name, tries - 1))


def _group(panel, title):
    box = QtWidgets.QGroupBox(title, panel)
    box.setObjectName("SWStyle_" + "".join(title.split()).replace("/", ""))
    box.setLayout(QtWidgets.QVBoxLayout())
    box.setCheckable(False)
    return box


def _row(box, label, widget):
    row = QtWidgets.QHBoxLayout()
    row.addWidget(QtWidgets.QLabel(label, box))
    row.addWidget(widget, 1)
    box.layout().addLayout(row)
    return widget


def _option_checks(panel, native, prefix, items):
    ""

    lay = panel.layout()
    for name, text, default, tip in items:
        cb = QtWidgets.QCheckBox(text, panel)
        cb.setObjectName("SWStyle_%s%s" % (prefix, name))
        cb.setChecked(default)
        cb.setToolTip(tip)
        cb.toggled.connect(lambda on, n=name, d=default: on != d and _later(native, **{n: on}))
        lay.addWidget(cb)


def add_loft_boxes(panel, native):
    """Start/End Constraints, Guide Curves, Centerline Parameters and Thin Feature on FreeCAD's Loft page."""
    if panel.findChild(QtWidgets.QGroupBox, "SWStyle_StartEndConstraints") is not None:
        return
    lay = panel.layout()
    ends = _group(panel, "Start/End Constraints")
    for end in ("Start", "End"):
        combo = QtWidgets.QComboBox(ends)
        combo.setObjectName("SWStyle_Loft%sConstraint" % end)
        combo.addItems(list(CONSTRAINTS))
        combo.setToolTip("%s constraint: how the loft leaves the %s profile" % (end, "first" if end == "Start" else "last"))
        _row(ends, "%s constraint:" % end, combo)
        combo.activated.connect(lambda i, e=end, c=combo: i and _later(native, **{e + "Constraint": c.itemText(i)}))
    guides = _group(panel, "Guide Curves")
    g = QtWidgets.QPushButton("Guide curves...", guides)
    g.setObjectName("SWStyle_LoftGuides")
    g.setToolTip("Pick the guide curves the loft follows between the profiles")
    guides.layout().addWidget(g)
    g.clicked.connect(lambda: (sf.focus_next("Guides"), _later(native)))     # the next pick is a guide curve
    centre = _group(panel, "Centerline Parameters")
    c = QtWidgets.QPushButton("Centerline...", centre)
    c.setObjectName("SWStyle_LoftCenterline")
    c.setToolTip("Pick a centerline: the loft's sections stay square to it")
    centre.layout().addWidget(c)
    c.clicked.connect(lambda: (sf.focus_next("Centerline"), _later(native)))     # the next pick is the centerline
    micro = QtWidgets.QCheckBox("Micro tolerance", panel)
    micro.setObjectName("SWStyle_LoftMicroTolerance")
    micro.setToolTip("A finer tolerance for lofts of very small geometry")

    g.clicked.connect(lambda: _activate_soon("Guides"))
    c.clicked.connect(lambda: _activate_soon("Centerline"))
    micro.toggled.connect(lambda on: on and _later(native, MicroTolerance=True))
    lay.addWidget(micro)
    _option_checks(panel, native, "Loft", (("MergeTangent", "Merge tangent faces", True, "Faces that meet tangent become one face"),
                                           ("ShowPreview", "Show preview", True, "Show the loft while you edit it")))
    thin = _group(panel, "Thin Feature")
    t = QtWidgets.QCheckBox("Thin Feature", thin)
    t.setObjectName("SWStyle_LoftThin")
    thin.layout().addWidget(t)
    t.toggled.connect(lambda on: on and _later(native, Thin=True))

    # Scope, Curvature Display (pmlayout puts Options in its place)
    boxes = [ends, guides, centre, _sketch_tools_box(panel, native), thin]
    if native.TypeId.startswith("PartDesign::Subtractive"):
        boxes.append(_scope_box(panel, native))
    boxes.append(_curvature_box(panel, native))
    for b in boxes:
        lay.addWidget(b)


def _curvature_box(panel, native):
    ""

    from . import curvdisplay
    box = _group(panel, "Curvature Display")
    name = (native.Document.Name, native.Name)

    def shape():
        obj = App.getDocument(name[0]).getObject(name[1])
        return obj.Shape if obj is not None else None
    curv = curvdisplay.CurvatureDisplay(shape, box)
    curv.setTitle("")
    curv.setFlat(True)
    box.layout().addWidget(curv)
    overlays = (curv.mesh_overlay, curv.comb_overlay)
    box.destroyed.connect(lambda *a: [o.clear() for o in overlays])
    return box


class _DragSketch(QtCore.QObject):
    ""


    def __init__(self, box, native):
        super().__init__(box)
        self.doc, self.name = native.Document.Name, native.Name
        self.undo_stack = []      # (sketch name, AttachmentOffset before)
        self.sketch = None
        lay = box.layout()
        row = QtWidgets.QHBoxLayout()
        self.drag = QtWidgets.QToolButton(box)
        self.drag.setObjectName("SWStyle_LoftDragSketch")
        self.drag.setText("Drag Sketch")
        self.drag.setCheckable(True)
        self.drag.setToolTip("Pick a profile sketch, then move it: the loft follows")
        self.undo = QtWidgets.QToolButton(box)
        self.undo.setObjectName("SWStyle_LoftUndoDrag")
        self.undo.setText("Undo sketch drag")
        self.undo.setEnabled(False)
        row.addWidget(self.drag)
        row.addWidget(self.undo)
        row.addStretch(1)
        lay.addLayout(row)
        self.which = QtWidgets.QLabel("", box)
        self.which.setObjectName("SWStyle_LoftDragWhich")
        lay.addWidget(self.which)
        self.move = QtWidgets.QDoubleSpinBox(box)
        self.move.setObjectName("SWStyle_LoftDragDistance")
        self.move.setRange(-1e5, 1e5)
        self.move.setDecimals(2)
        self.move.setSuffix(" mm")
        self.move.setSingleStep(1.0)
        self.move.setToolTip("How far the picked sketch moves along its normal")
        self.move.setVisible(False)
        lay.addWidget(self.move)
        self.base = None
        self.drag.toggled.connect(self._toggled)
        self.undo.clicked.connect(self.undo_drag)
        self.move.valueChanged.connect(self._moved)
        self._listening = False
        box.destroyed.connect(self._stop)

    def feature(self):
        try:
            return App.getDocument(self.doc).getObject(self.name)
        except Exception:
            return None

    def profiles(self):
        f = self.feature()
        if f is None:
            return []
        out = []
        prof = getattr(f, "Profile", None)
        prof = prof[0] if isinstance(prof, tuple) else prof
        if prof is not None:
            out.append(prof)
        for item in getattr(f, "Sections", []) or []:
            o = item[0] if isinstance(item, tuple) else item
            if o is not None and o not in out:
                out.append(o)
        return [o for o in out if o.TypeId == "Sketcher::SketchObject"]

    def _toggled(self, on):
        """Drag Sketch on: a click on a profile sketch in the view picks it (the click is kept from
        FreeCAD's page, which would take the sketch out of the loft), or pick it in the list."""
        if on:
            self._listen()
            self.which.setText("Pick a profile sketch" if self.sketch is None else self.which.text())
        else:
            self._stop()

    def _listen(self):
        if self._listening:
            return
        try:
            from pivy import coin
            self.view = Gui.ActiveDocument.ActiveView
            self.callback = self.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self._clicked)
            self._listening = True
        except Exception:
            self._listening = False

    def _stop(self, *args):
        if self._listening:
            try:
                from pivy import coin
                self.view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.callback)
            except Exception as _fw_err:
                _fw_log("loftsweep.py:1062", _fw_err)
            self._listening = False

    def _clicked(self, cb):
        from pivy import coin
        event = cb.getEvent()
        if not coin.SoMouseButtonEvent.isButtonPressEvent(event, coin.SoMouseButtonEvent.BUTTON1):
            return
        pos = event.getPosition().getValue()
        info = self.view.getObjectInfo((int(pos[0]), int(pos[1])))
        name = self.sketch_at(info)
        if name:
            cb.setHandled()
            from . import safe_later as _sl; _sl.later(0, lambda n=name: self.pick(n), self, "move")

    def sketch_at(self, info):
        if not info:
            return None
        names = [p.Name for p in self.profiles()]
        for key in ("Object", "SubName"):
            text = str(info.get(key, "") or "")
            for part in text.split("."):
                if part in names:
                    return part
        return None

    def pick(self, name):
        doc = App.getDocument(self.doc)
        sk = doc.getObject(name)
        if sk is None:
            return False
        self.sketch = name
        self.base = App.Placement(sk.AttachmentOffset)
        self.undo_stack.append((name, App.Placement(sk.AttachmentOffset)))
        self.undo.setEnabled(True)
        self.which.setText("Dragging %s" % sk.Label)
        self.move.blockSignals(True)
        self.move.setValue(0.0)
        self.move.blockSignals(False)
        self.move.setVisible(True)
        return True

    def _moved(self, value):
        doc = App.getDocument(self.doc)
        sk = doc.getObject(self.sketch) if self.sketch else None
        if sk is None or self.base is None:
            return
        offset = App.Placement(self.base)
        offset.Base = offset.Base + offset.Rotation.multVec(App.Vector(0, 0, 1)) * float(value)
        sk.AttachmentOffset = offset
        doc.recompute()

    def undo_drag(self):
        if not self.undo_stack:
            return False
        name, before = self.undo_stack.pop()
        doc = App.getDocument(self.doc)
        sk = doc.getObject(name)
        if sk is not None:
            sk.AttachmentOffset = before
            doc.recompute()
        if name == self.sketch:
            self.base = App.Placement(before)
            self.move.blockSignals(True)
            self.move.setValue(0.0)
            self.move.blockSignals(False)
        self.undo.setEnabled(bool(self.undo_stack))
        return True


def _sketch_tools_box(panel, native):
    box = _group(panel, "Sketch Tools")
    box._drag = _DragSketch(box, native)
    return box


def _scope_box(panel, native):
    scope = _group(panel, "Feature Scope")
    a = QtWidgets.QRadioButton("All bodies", scope)
    s = QtWidgets.QRadioButton("Selected bodies", scope)
    a.setChecked(True)
    scope.layout().addWidget(a)
    scope.layout().addWidget(s)
    s.setObjectName("SWStyle_ScopeSelected")
    s.toggled.connect(lambda on: on and _later(native, Scope="Selected bodies"))
    return scope


def add_sweep_boxes(panel, native):
    """Circular Profile, the other Profile twist values, Start/End Tangency and Thin Feature on
    FreeCAD's Pipe page."""
    if panel.findChild(QtWidgets.QGroupBox, "SWStyle_StartEndTangency") is not None:
        return
    lay = panel.layout()
    kind = QtWidgets.QRadioButton("Circular Profile", panel)
    kind.setObjectName("SWStyle_SweepCircular")
    kind.setToolTip("Sweep a circle of a set diameter along the path, with no profile sketch")
    sketch = QtWidgets.QRadioButton("Sketch Profile", panel)
    sketch.setChecked(True)
    lay.insertWidget(0, sketch)
    lay.insertWidget(1, kind)
    kind.toggled.connect(lambda on: on and _later(native, ProfileType="Circular Profile"))
    if native.TypeId == "PartDesign::SubtractivePipe":

        solid = QtWidgets.QRadioButton("Solid Profile", panel)
        solid.setObjectName("SWStyle_SweepSolid")
        solid.setToolTip("Cut with a tool body (a body of revolution) moved along the path")
        lay.insertWidget(2, solid)
        solid.toggled.connect(lambda on: on and _later(native, ProfileType="Solid Profile"))
    twist = panel.window().findChild(QtWidgets.QComboBox, "SWStyle_ProfileTwist")
    OWN_TWISTS = ("Specify Twist Value", "Tangent to Adjacent Faces", "Follow Path and 1st Guide Curve",
                  "Follow 1st and 2nd Guide Curves")
    if twist is not None and twist.findText("Specify Twist Value") < 0:
        for text in OWN_TWISTS:
            if twist.findText(text) < 0:
                twist.addItem(text)
        twist.activated.connect(lambda i, c=twist: c.itemText(i) in OWN_TWISTS and _later(native, Twist=c.itemText(i)))
    # Direction: with the profile part way along the path, sweep one way, the other, or both
    way = QtWidgets.QWidget(panel)
    way.setObjectName("SWStyle_SweepDirection")

    wl = QtWidgets.QGridLayout(way)
    wl.setContentsMargins(0, 0, 0, 0)
    wl.setHorizontalSpacing(6)
    wl.setVerticalSpacing(2)
    for i, text in enumerate(SWEEP_DIRECTIONS):
        b = QtWidgets.QRadioButton(text, way)
        b.setObjectName("SWStyle_Sweep" + text.replace(" ", ""))
        b.setChecked(i == 0)
        if i:
            b.toggled.connect(lambda on, t=text: on and _later(native, SweepDirection=t))
        wl.addWidget(b, i // 2, i % 2)
    lay.insertWidget(3 if native.TypeId == "PartDesign::SubtractivePipe" else 2, way)

    state = {"key": None}

    def _way_shown():
        try:
            key = (str(getattr(native, "Profile", None)), str(getattr(native, "Spine", None)))
            if key == state["key"]:
                return
            state["key"] = key
            on = _native_both_ways(native)
            if way.isHidden() == on:
                way.setVisible(on)
        except RuntimeError:
            timer.stop()
    timer = QtCore.QTimer(way)
    timer.timeout.connect(_way_shown)
    timer.start(400)
    way.hide()
    QtCore.QTimer.singleShot(0, _way_shown)
    _option_checks(panel, native, "Sweep", (("MergeTangent", "Merge tangent faces", True, "Faces that meet tangent become one face"),
                                            ("ShowPreview", "Show preview", True, "Show the sweep while you edit it"),
                                            ("AlignEndFaces", "Align with end faces", False, "Carry the sweep on to the faces its ends meet")))
    _align = panel.findChild(QtWidgets.QCheckBox, "SWStyle_SweepAlignEndFaces")
    if _align is not None:
        _align.setObjectName("SWStyle_SweepAlignEnds")     # the name the PC copy gave it
    ends = _group(panel, "Start/End Tangency")
    for end in ("Start", "End"):
        combo = QtWidgets.QComboBox(ends)
        combo.setObjectName("SWStyle_Sweep%sTangency" % end)
        combo.addItems(list(TANGENCY))
        _row(ends, "%s tangency type:" % end, combo)
        combo.activated.connect(lambda i, e=end: i and _later(native, **{e + "Tangency": "Path Tangent"}))
    thin = _group(panel, "Thin Feature")
    t = QtWidgets.QCheckBox("Thin Feature", thin)
    t.setObjectName("SWStyle_SweepThin")
    thin.layout().addWidget(t)
    t.toggled.connect(lambda on: on and _later(native, Thin=True))
    boxes = [ends, thin]
    if native.TypeId.startswith("PartDesign::Subtractive"):
        boxes.append(_scope_box(panel, native))
    boxes.append(_curvature_box(panel, native))
    for b in boxes:
        lay.addWidget(b)
