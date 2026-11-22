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
from PySide import QtCore, QtGui, QtWidgets

from . import pmfields

V = App.Vector
TYPES = ("PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution", "PartDesign::Groove")
SKETCH = "Sketcher::SketchObject"
BOX = "SWStyle_SelectedContours"
LIST = "SWStyle_SelectedContoursList"
TITLE = "Selected Contours"
HINT = ("Pick a sketch entity for its closed contour, or pick inside an area bounded by "
        "sketch geometry for a region.")
SHADE = (0.93, 0.62, 0.5)


# ---- regions of a sketch ------------------------------------------------------------------

def _local(sketch):
    """The sketch's edges (not construction) in its own plane, as a shape.

    Built from the sketch's Geometry, which is in the sketch's plane already: once a feature has used
    a sketch whose geometry crosses itself, FreeCAD 1.1 can rebuild sketch.Shape with pieces left out
    (EX504: the lower half of the R24 circle went missing, so three of the four upright regions could
    no longer be picked and the Boss came out a "Null shape")."""
    try:
        geo = list(sketch.Geometry)
        edges = []
        for i, g in enumerate(geo):
            if sketch.getConstruction(i) or g.TypeId == "Part::GeomPoint":
                continue
            try:
                edges += g.toShape().Edges
            except Exception:
                continue
        if edges:
            wires = []
            for group in Part.sortEdges(edges):
                try:
                    wires.append(Part.Wire(group))
                except Exception:
                    wires += [Part.Wire([e]) for e in group]
            return Part.makeCompound(wires)
    except Exception as _fw_err:
        _fw_log("contours.py:74", _fw_err)
    shape = sketch.Shape.copy()
    shape.transformShape(sketch.getGlobalPlacement().inverse().toMatrix())
    return shape


def _external_edges(sketch):
    ""

    out = []
    try:
        for geo in list(sketch.ExternalGeo)[2:]:        # the first two are the sketch's own axes
            try:
                edge = geo.toShape()
            except Exception:
                continue
            if edge.Edges and edge.BoundBox.ZLength < 1e-7 and abs(edge.BoundBox.ZMin) < 1e-7:
                out.extend(edge.Edges)
    except Exception as _fw_err:
        _fw_log("contours.py:93", _fw_err)
    return out


def regions(sketch):
    """[face] the areas bounded by the sketch's geometry (with its external edges), in the
    sketch's own plane (z = 0)."""
    shape = _local(sketch)
    if not shape.Edges:
        return []
    external = _external_edges(sketch)
    if external:
        shape = Part.makeCompound(shape.Edges + external)
    bb = shape.BoundBox
    m = max(bb.DiagonalLength * 0.1, 1.0)
    big = Part.makePlane(bb.XLength + 2 * m, bb.YLength + 2 * m, V(bb.XMin - m, bb.YMin - m, 0))
    try:
        pieces, _map = big.generalFuse(shape.Edges)
    except Exception:
        return []
    corners = [v.Point for v in big.Vertexes]
    out = []
    for face in pieces.Faces:
        if any(v.Point.distanceToPoint(c) < 1e-7 for v in face.Vertexes for c in corners):
            continue          # the piece around everything
        out.append(face)
    return out


def crossing(sketch):
    ""
    edges = _local(sketch).Edges
    if len(edges) < 2:
        return False
    try:
        pieces, _map = edges[0].generalFuse(edges[1:])
    except Exception:
        return False
    return len(pieces.Edges) > len(edges)


def region_at(faces, point):
    """The smallest face holding point (a local point, z = 0), or None."""
    hits = [f for f in faces if f.isInside(V(point.x, point.y, 0), 1e-6, True)]
    return min(hits, key=lambda f: f.Area) if hits else None


def _element_map(sketch):
    try:
        return dict(sketch.Shape.ElementMap or {})
    except Exception:
        return {}


def stable_edge(sketch, edge_name):
    ""


    for mapped, element in _element_map(sketch).items():
        if element == edge_name and mapped.endswith(";SKT") and mapped[0] == "g" and "v" not in mapped:
            return mapped[:-4]
    return edge_name


def edge_name(sketch, key):
    """The sketch's EdgeN for a contour pick's key (g<id> or an older EdgeN), or None."""
    if key.startswith("Edge"):
        return key
    return _element_map(sketch).get(key + ";SKT")


def contour_of(sketch, edge_name_or_key):
    """The closed wire of the sketch (local) holding that edge, or None."""
    shape = _local(sketch)
    name = edge_name(sketch, edge_name_or_key)
    if not name:
        return None
    try:
        edge = shape.getElement(name)
    except Exception:
        return None
    for wire in shape.Wires:
        if wire.isClosed() and any(e.isSame(edge) for e in wire.Edges):
            return wire
    return None


def _parse(pick):
    kind, _, rest = pick.partition(":")
    if kind == "R":
        x, y = (float(t) for t in rest.split(","))
        return "R", V(x, y, 0)
    return "C", rest


def picked_faces(sketch, picks):
    """[face] the picks make, in the sketch's own plane."""
    faces = regions(sketch)
    out = []
    wires = []
    for pick in picks:
        kind, value = _parse(pick)
        if kind == "R":
            face = region_at(faces, value)
            if face is not None and not any(face.isSame(f) for f in out):
                out.append(face)
        else:
            wire = contour_of(sketch, value)
            if wire is not None:
                wires.append(wire)
    if wires:
        try:
            out.append(Part.makeFace(wires, "Part::FaceMakerBullseye"))
        except Exception:
            out += [Part.Face(w) for w in wires]
    return out


def _merged(faces):
    if not faces:
        return Part.Shape()
    if len(faces) == 1:
        return faces[0]
    total = sum(f.Area for f in faces)
    fused = faces[0].fuse(faces[1:])
    shape = fused
    try:
        refined = fused.removeSplitter()
        # OpenCascade's refine can drop pieces of regions that wrap a hole (EX504: four regions round
        # a bore became one wrong face, then "Null shape"): keep it only when it covers the same area
        if refined.Faces and abs(sum(f.Area for f in refined.Faces) - total) <= 1e-6 * max(total, 1.0):
            shape = refined
        else:
            shape = _from_boundary(fused, total) or fused
    except Exception as _fw_err:
        _fw_log("contours.py:201", _fw_err)
    return Part.makeCompound(shape.Faces) if len(shape.Faces) > 1 else shape.Faces[0]


def _from_boundary(fused, total):
    """The fused regions as faces rebuilt from their outline: the edges only one region has (outer
    loops and the loops round holes), made into faces with holes. None when it does not add up."""
    try:
        edges = fused.Edges
        faces = fused.Faces
        free = [e for e in edges if sum(1 for f in faces if any(x.isSame(e) for x in f.Edges)) == 1]
        if not free:
            return None
        wires = [w for w in Part.sortEdges(free)]
        loops = [Part.Wire(w) for w in wires]
        if not all(w.isClosed() for w in loops):
            return None
        face = Part.makeFace(loops, "Part::FaceMakerBullseye")
        if face.Faces and abs(sum(f.Area for f in face.Faces) - total) <= 1e-6 * max(total, 1.0):
            return face
    except Exception as _fw_err:
        _fw_log("contours.py:222", _fw_err)
    return None


def _sides(kind, t1, t2, reverse):
    """(thickness to the outside / left, thickness to the inside / right) of a thin wall."""
    if kind == "Mid-Plane":
        return t1 / 2.0, t1 / 2.0
    if kind == "Two-Direction":
        return (t2, t1) if reverse else (t1, t2)
    return (0.0, t1) if reverse else (t1, 0.0)


def _half(wire, d, left):
    """The band d wide along one side of an open wire, ends square (OCC's filled one-sided
    offset: a negative distance fills to the left of the wire's direction)."""
    try:
        band = wire.makeOffset2D(-d if left else d, join=2, fill=True, openResult=True)
        if band.Faces:
            return band.Faces[0] if len(band.Faces) == 1 else _merged(band.Faces)
    except Exception as _fw_err:
        _fw_log("contours.py:243", _fw_err)
    return _straight_band(wire, d, left)


def _straight_band(wire, d, left):
    """PATCH-MERGE (PM thread pkg110): a wire of straight lines in one line has no plane, so OCC
    cannot offset it (Revolve of a single open line with Thin Feature came out empty). The band
    is the rectangle beside it in the sketch plane (z = 0)."""
    edges = wire.Edges
    if not edges or any(not isinstance(e.Curve, Part.Line) for e in edges):
        return None
    a, b = wire.Vertexes[0].Point, wire.Vertexes[-1].Point
    if wire.OrderedVertexes:
        a, b = wire.OrderedVertexes[0].Point, wire.OrderedVertexes[-1].Point
    t = b - a
    if t.Length < 1e-9:
        return None
    t.normalize()
    if any(abs(abs(e.Curve.Direction.dot(t)) - 1.0) > 1e-9 for e in edges):
        return None
    n = V(0, 0, 1).cross(t)
    if not left:
        n = -n
    n.multiply(d)
    return Part.Face(Part.makePolygon([a, b, b + n, a + n, a]))


def _rounded(wire, radius, left_d, right_d):
    ""


    edges = wire.OrderedEdges if hasattr(wire, "OrderedEdges") else wire.Edges
    if radius <= 0 or len(edges) < 2 or any(not isinstance(e.Curve, Part.Line) for e in edges):
        return wire
    pts = [v.Point for v in wire.OrderedVertexes]
    if len(pts) != len(edges) + 1:
        return wire
    starts = [pts[0]]
    arcs = []
    for i in range(1, len(pts) - 1):
        a, p, b = pts[i - 1], pts[i], pts[i + 1]
        u = p - a
        w = b - p
        if u.Length < 1e-9 or w.Length < 1e-9:
            return wire
        u.normalize()
        w.normalize()
        turn = u.cross(w).z
        if abs(turn) < 1e-9:
            arcs.append(None)
            starts.append(p)
            continue
        r = radius + (left_d if turn > 0 else right_d)
        half = math.acos(max(-1.0, min(1.0, (-u).dot(w)))) / 2.0      # half the corner's angle
        back = r / math.tan(half)
        p1 = p - u * back
        p2 = p + w * back
        mid = -u + w
        mid.normalize()
        centre = p + mid * (r / math.sin(half))
        towards = p - centre
        towards.normalize()
        arcs.append((p1, centre + towards * r, p2))
        starts.append(None)
    edges_out = []
    here = pts[0]
    for i in range(1, len(pts)):
        arc = arcs[i - 1] if i - 1 < len(arcs) else None
        end = arc[0] if arc is not None else pts[i]
        if (end - here).Length > 1e-9:
            edges_out.append(Part.LineSegment(here, end).toShape())
        if arc is not None:
            edges_out.append(Part.Arc(arc[0], arc[1], arc[2]).toShape())
            here = arc[2]
        else:
            here = end
    try:
        return Part.Wire(edges_out)
    except Exception as _fw_err:
        _fw_log("contours.py:_rounded", _fw_err)
        return wire


def thin_faces(wires, kind, t1, t2, reverse, part="wall", fillet=0.0):
    """[face] the thin wall of each wire (in its plane, z = 0). With Cap ends the solid is the
    whole outer face (part="outer") less a cavity of the inner face (part="inner"). fillet: the
    Auto-fillet corners radius of an open chain (0: sharp corners)."""
    out_d, in_d = _sides(kind, t1, t2, reverse)
    out = []
    for wire in wires:
        if fillet > 0 and not wire.isClosed():
            wire = _rounded(wire, fillet, out_d, in_d)
        if wire.isClosed():
            face = Part.Face(wire)
            if face.normalAt(0, 0).z < 0:
                face.reverse()
            outer = face.makeOffset2D(out_d, join=2) if out_d > 0 else face
            inner = face.makeOffset2D(-in_d, join=2) if in_d > 0 else face
            if part == "outer":
                out += outer.Faces
            elif part == "inner":
                out += inner.Faces
            else:
                out += outer.cut(inner).Faces
        elif part == "inner":
            continue
        else:
            for d, left in ((out_d, True), (in_d, False)):
                if d > 0:
                    band = _half(wire, d, left)
                    if band is not None:
                        out.append(band)
    return out


def _from_distance(sketch, opts):
    ""
    mode = getattr(opts, "From", "") or "Sketch Plane"
    if mode == "Offset":
        return float(opts.FromOffset)
    if mode not in ("Surface/Face/Plane", "Vertex"):
        return 0.0
    ref = opts.FromRef
    if not ref or ref[0] is None:
        return 0.0
    place = sketch.getGlobalPlacement()
    normal = place.Rotation.multVec(V(0, 0, 1))
    obj, subs = ref
    shape = Part.getShape(obj, subs[0] if subs and subs[0] else "", needSubElement=True) if subs and subs[0] \
        else Part.getShape(obj)
    if mode == "Vertex":
        if not shape.Vertexes:
            raise RuntimeError("From Vertex needs a vertex")
        return (shape.Vertexes[0].Point - place.Base).dot(normal)
    face = _from_face(sketch, opts, shape)
    if face is not None:
        return 0.0              # profile_shape lays the profile onto the face itself
    return (shape.Faces[0].CenterOfMass - place.Base).dot(normal)


def _from_face(sketch, opts, shape=None):
    ""



    if (getattr(opts, "From", "") or "") != "Surface/Face/Plane":
        return None
    if shape is None:
        ref = opts.FromRef
        if not ref or ref[0] is None:
            return None
        obj, subs = ref
        shape = Part.getShape(obj, subs[0], needSubElement=True) if subs and subs[0] else Part.getShape(obj)
    faces = shape.Faces
    if not faces:
        raise RuntimeError("From Surface/Face/Plane needs a face or a plane")
    face = faces[0]
    normal = sketch.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
    if face.Surface.TypeId == "Part::GeomPlane":
        u, v = face.Surface.parameter(face.CenterOfMass)
        if abs(abs(face.normalAt(u, v).dot(normal)) - 1.0) <= 1e-6:
            return None
        # a flat face or a plane counts as its whole plane (a datum plane's square is only drawn)
        place = sketch.getGlobalPlacement()
        plane = face.Surface.copy()
        plane.Position = plane.projectPoint(place.Base)
        r = 4.0 * (plane.Position - place.Base).Length + 1.0e4
        return plane.toShape(-r, r, -r, r)
    return face


def _onto(sketch, shape, face):
    """The profile (flat, in the sketch's own coordinates) laid onto face along the sketch's normal:
    the part of the face straight above or below it."""
    local = face.copy()
    local.transformShape(sketch.getGlobalPlacement().inverse().toMatrix())
    box = local.BoundBox
    if not box.isValid() or box.ZLength < 0:
        raise RuntimeError("The From face has no size")
    low, high = box.ZMin - 1.0, box.ZMax + 1.0
    prism = shape.extrude(V(0, 0, high - low))
    prism.translate(V(0, 0, low))
    piece = local.common(prism)
    faces = [f for f in piece.Faces if f.Area > 1e-9]
    if not faces:
        raise RuntimeError("The profile does not lie over the From face")
    if len(faces) > 1:
        # a face that wraps round (a cylinder) lies over the profile twice: keep the side the sketch
        # looks at (highest along its normal), piece by piece where the pieces do not overlap
        kept, columns = [], []
        for f in sorted(faces, key=lambda f: -f.CenterOfMass.z):
            if any(c.isInside(f.CenterOfMass, 1e-7, False) for c in columns):
                continue        # under a piece already kept
            col = f.extrude(V(0, 0, 2.0 * (high - low) + 2.0))
            col.translate(V(0, 0, low - high - 1.0))
            kept.append(f)
            columns.append(col)
        faces = kept
    laid = faces[0] if len(faces) == 1 else Part.makeCompound(faces)
    # the face must cover the whole profile: its shadow on the sketch plane is the profile's area
    shadow = sum(abs(f.extrude(V(0, 0, 1.0)).Volume) for f in faces)
    if shadow < shape.Area * (1.0 - 1e-2):      # (a curved face's volume is integrated: not exact)
        raise RuntimeError("The From face does not cover the whole profile")
    return laid


def profile_shape(sketch, picks, opts=None, part=None, at=None):
    """The faces the feature is made from, placed with the sketch: the picks (or the whole
    sketch), as a thin wall when Thin is on, moved to where From says (or to `at` along the
    sketch's normal). part: "outer" or "inner" for a thin feature with Cap ends."""
    thin = opts is not None and getattr(opts, "Thin", False)
    if part is None:
        part = "outer" if thin and getattr(opts, "CapEnds", False) else "wall"
    if picks:
        faces = picked_faces(sketch, picks)
        wires = [w for f in faces for w in f.Wires]
    else:
        local = _local(sketch)
        wires = local.Wires
        faces = []
        if not thin:
            closed = [w for w in wires if w.isClosed()]
            if closed:
                try:
                    faces = Part.makeFace(closed, "Part::FaceMakerBullseye").Faces
                except Exception:
                    faces = [Part.Face(w) for w in closed]
    if thin:
        rounds = float(getattr(opts, "FilletRadius", 0) or 0) if getattr(opts, "AutoFillet", False) else 0.0
        faces = thin_faces(wires, opts.ThinType or "One-Direction", float(opts.ThinT1), float(opts.ThinT2),
                           bool(opts.ThinReverse), part, rounds)
    shape = _merged(faces)
    if shape.isNull():
        return shape
    if picks and opts is not None and getattr(opts, "FlipSide", False):
        shape = _outside(sketch, shape)
    d = _from_distance(sketch, opts) if opts is not None else 0.0
    start = _from_face(sketch, opts) if opts is not None and at is None else None
    if start is not None:
        shape = _onto(sketch, shape, start)
    if at is not None:
        d = float(at)
    if abs(d) > 1e-12:
        shape.translate(V(0, 0, d))
    frame = _frame(sketch, getattr(opts, "AxisRef", "") if opts is not None else "")
    if frame.isIdentity():
        shape.Placement = sketch.getGlobalPlacement().multiply(shape.Placement)
    else:
        # the geometry itself in the frame's coordinates (a rigid transformShape only moves the
        # shape's location, and the object's Placement would then lose the frame)
        shape = shape.transformed(frame.inverse().multiply(shape.Placement).toMatrix(), True)
        # (transformed with copy, not transformGeometry: that turned circles and arcs into
        # B-splines, so a revolved hole was no longer a true torus or cylinder and came out
        # 0.5-3 % off in volume)
        shape.Placement = sketch.getGlobalPlacement().multiply(frame)
    return shape


def _outside(sketch, shape):
    """Flip side to cut with picked contours: a square larger than the part, less the picks."""
    size = shape.BoundBox.DiagonalLength
    body = _body(sketch)
    try:
        if body is not None and not body.Shape.isNull():
            size = max(size, body.Shape.BoundBox.DiagonalLength)
    except Exception as _fw_err:
        _fw_log("contours.py:381", _fw_err)
    centre = shape.BoundBox.Center
    r = size + 10.0
    square = Part.makePlane(2 * r, 2 * r, V(centre.x - r, centre.y - r, 0))
    out = square.cut(shape)
    return Part.makeCompound(out.Faces) if len(out.Faces) > 1 else out.Faces[0]


def names(sketch, picks):
    """The list's entries: Sketch7-Region<1>, Sketch7-Contour<1> ... in the order picked."""
    count = {"R": 0, "C": 0}
    out = []
    for pick in picks:
        kind = pick[0]
        count[kind] += 1
        out.append("%s-%s<%d>" % (sketch.Label, "Region" if kind == "R" else "Contour", count[kind]))
    return out


# ---- the hidden profile object ------------------------------------------------------------

FROM_MODES = ("Sketch Plane", "Surface/Face/Plane", "Vertex", "Offset")
THIN_TYPES = ("One-Direction", "Mid-Plane", "Two-Direction")


def options(obj):
    """Adds From and Thin Feature to a profile object (also to one from an older file)."""
    have = obj.PropertiesList
    for kind, name, group, tip in (
            ("App::PropertyString", "From", "From", "Sketch Plane, Surface/Face/Plane, Vertex or Offset"),
            ("App::PropertyDistance", "FromOffset", "From", "Offset: how far from the sketch plane it starts"),
            ("App::PropertyLinkSub", "FromRef", "From", "Surface/Face/Plane or Vertex: where it starts"),
            ("App::PropertyBool", "Thin", "Thin Feature", "A thin wall along the profile instead of its area"),
            ("App::PropertyString", "ThinType", "Thin Feature", "One-Direction, Mid-Plane or Two-Direction"),
            ("App::PropertyLength", "ThinT1", "Thin Feature", "Thickness (Direction 1)"),
            ("App::PropertyLength", "ThinT2", "Thin Feature", "Thickness of Direction 2 (Two-Direction)"),
            ("App::PropertyBool", "ThinReverse", "Thin Feature", "The wall goes to the other side"),
            ("App::PropertyBool", "CapEnds", "Thin Feature",
             "Cap ends: the thin base extrude is closed at both ends (a hollow body)"),
            ("App::PropertyLength", "CapT", "Thin Feature", "Cap Thickness"),
            ("App::PropertyBool", "AutoFillet", "Thin Feature",
             "Auto-fillet corners: a round at each corner of an open profile's wall"),
            ("App::PropertyLength", "FilletRadius", "Thin Feature", "Auto-fillet corners: the rounds' inside radius"),
            ("App::PropertyBool", "FlipSide", "Selected Contours",
             "Flip side to cut: the cut takes away everything outside the picked contours"),
            ("App::PropertyString", "AxisRef", "Selected Contours",
             "The sketch's construction line (AxisN) a revolve turns about: this object's V axis")):
        if name not in have:
            obj.addProperty(kind, name, group, tip)
    if not obj.From:
        obj.From = "Sketch Plane"
    if not obj.ThinType:
        obj.ThinType = "One-Direction"
    if float(obj.ThinT1) <= 0:
        obj.ThinT1 = 1.0
    if float(obj.ThinT2) <= 0:
        obj.ThinT2 = 1.0
    if float(obj.CapT) <= 0:
        obj.CapT = float(obj.ThinT1)
    if float(obj.FilletRadius) <= 0:
        obj.FilletRadius = 1.0


def needed(obj):
    """The feature needs its profile object (not just the sketch)."""
    return bool(obj.Picks) or (obj.From or "Sketch Plane") != "Sketch Plane" or bool(obj.Thin) or \
        bool(getattr(obj, "FlipSide", False))


class SelectedContours:
    Type = "SWStyle::SelectedContours"

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Sketch", TITLE, "The sketch the contours come from")
        obj.addProperty("App::PropertyStringList", "Picks", TITLE,
                        "R:x,y = the region around that sketch point; C:g<id> = the contour of that entity (geometry id; older files: C:EdgeN)")
        options(obj)

    def execute(self, obj):
        if obj.Sketch is None:
            return
        part = None
        if getattr(obj, "Thin", False) and getattr(obj, "CapEnds", False):

            # tick must not turn the thin wall into the whole outer area (alloy wheel ring, real-use pass)
            users = [o for o in obj.InList if getattr(o, "Profile", None) and o.Profile[0] == obj]
            if users and not any(caps_allowed(u) for u in users):
                part = "wall"
        shape = profile_shape(obj.Sketch, obj.Picks, obj, part=part)
        obj.Shape = shape
        if not shape.isNull():
            obj.Placement = shape.Placement

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        options(obj)
        try:        # contour picks from older files (EdgeN): keyed by the entity from now on
            picks = list(obj.Picks)
            new = [("C:" + stable_edge(obj.Sketch, p[2:])) if p.startswith("C:Edge") and obj.Sketch is not None else p
                   for p in picks]
            if new != picks:
                obj.Picks = new
        except Exception as _fw_err:
            _fw_log("contours.py:restore", _fw_err)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _view_owner(view):
    """The object whose view provider is view. FreeCAD restores these views from a file without
    calling attach() (dumps() keeps nothing), so the object is found on first need."""
    obj = getattr(view, "Object", None)
    if obj is not None:
        return obj
    for doc in App.listDocuments().values():
        for o in doc.Objects:
            try:
                vo = o.ViewObject
                if vo is not None and vo.Proxy is view:
                    view.Object = o
                    return o
            except Exception as _fw_err:
                _fw_log("contours.py:495", _fw_err)
    return None


class SelectedContoursView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        try:
            vobj.ShowInTree = False
        except Exception as _fw_err:
            _fw_log("contours.py:508", _fw_err)

    def onChanged(self, vobj, prop):
        # a reopened file: FreeCAD restores the view properties (and calls this), not attach()
        if getattr(self, "Object", None) is None:
            try:
                self.Object = vobj.Object
            except Exception as _fw_err:
                _fw_log("contours.py:516", _fw_err)

    def getIcon(self):
        return "Sketcher_Sketch"

    def claimChildren(self):
        sketch = getattr(_view_owner(self), "Sketch", None)
        return [sketch] if sketch is not None else []

    def onDelete(self, vobj, subelements):
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


class CapCavity:
    """The cavity of a thin extrude with Cap ends: the profile's inner face, in the middle of the
    extrude, for a hidden Pocket (Midplane, CavityLength) right after it."""
    Type = "SWStyle::CapCavity"

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Source", TITLE, "The Selected Contours of the extrude")
        obj.addProperty("App::PropertyLink", "Feature", TITLE, "The thin extrude the caps close")
        obj.addProperty("App::PropertyLength", "CavityLength", TITLE, "Extrude length less the two caps")

    def execute(self, obj):
        src, pad = obj.Source, obj.Feature
        if src is None or pad is None or src.Sketch is None:
            return
        sketch = src.Sketch
        place = sketch.getGlobalPlacement()
        normal = place.Rotation.multVec(V(0, 0, 1))
        solid = Part.getShape(pad)
        if solid.isNull() or not solid.Vertexes:
            raise RuntimeError("Cap ends: the extrude has no shape yet")
        zs = [(v.Point - place.Base).dot(normal) for v in solid.Vertexes]
        cap = float(src.CapT)
        length = max(zs) - min(zs) - 2 * cap
        if length <= 1e-6:
            raise RuntimeError("Cap Thickness is too large for the extrude's depth")
        obj.CavityLength = length
        shape = profile_shape(sketch, src.Picks, src, part="inner", at=(max(zs) + min(zs)) / 2.0)
        if shape.isNull():
            raise RuntimeError("Cap ends need a closed profile")
        obj.Shape = shape
        obj.Placement = shape.Placement

    def onDocumentRestored(self, obj):
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_helper(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == SelectedContours.Type


def cavity_of(feature):
    """The hidden Cap ends pocket of a thin extrude, or None."""
    for obj in feature.InList:
        if obj.TypeId == "PartDesign::Pocket" and getattr(obj, "Profile", None) and \
                getattr(getattr(obj.Profile[0], "Proxy", None), "Type", None) == CapCavity.Type and \
                obj.Profile[0].Feature == feature:
            return obj
    return None


def caps_allowed(feature):
    ""
    if feature.TypeId != "PartDesign::Pad" or getattr(feature, "BaseFeature", None) is not None:
        return False
    sketch = sketch_of(feature)
    if sketch is None:
        return False
    helper = helper_of(feature)
    try:
        if helper is not None and helper.Picks:
            wires = [w for f in picked_faces(sketch, helper.Picks) for w in f.Wires]
        else:
            wires = _local(sketch).Wires
    except Exception:
        return False
    return bool(wires) and all(w.isClosed() for w in wires)


def _set_caps(feature, helper, on):
    """Makes or removes the hidden cavity pocket of a thin extrude with Cap ends."""
    pocket = cavity_of(feature)
    doc = feature.Document
    body = _body(feature)
    if not on:
        if pocket is not None:
            cav = pocket.Profile[0]
            if body is not None and body.Tip == pocket:
                body.Tip = feature
            for obj in (pocket, cav):
                if body is not None:
                    body.removeObject(obj)
                doc.removeObject(obj.Name)
        return None
    if pocket is not None:
        return pocket
    cav = doc.addObject("Part::Part2DObjectPython", "CapCavity")
    CapCavity(cav)
    cav.Label = feature.Label + " Cap ends profile"
    cav.Source = helper
    cav.Feature = feature
    pocket = doc.addObject("PartDesign::Pocket", "CapEnds")
    pocket.Label = feature.Label + " Cap ends"
    if body is not None:
        body.insertObject(cav, feature, True)
        body.insertObject(pocket, cav, True)
    pocket.Profile = (cav, [])
    pocket.Type = "Length"
    pocket.SideType = "Symmetric"
    pocket.setExpression("Length", cav.Name + ".CavityLength")
    if App.GuiUp:
        SelectedContoursView(cav.ViewObject)
        cav.ViewObject.Visibility = False
        try:
            pocket.ViewObject.ShowInTree = False
        except Exception as _fw_err:
            _fw_log("contours.py:647", _fw_err)
    if body is not None and body.Tip == feature:
        body.Tip = pocket
    return pocket


def helper_of(feature):
    profile = feature.Profile[0] if getattr(feature, "Profile", None) else None
    return profile if profile is not None and is_helper(profile) else None


def sketch_of(feature):
    profile = feature.Profile[0] if getattr(feature, "Profile", None) else None
    if profile is None:
        return None
    if is_helper(profile):
        return profile.Sketch
    return profile if profile.TypeId == SKETCH else None


def _body(obj):
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None


def _axis_to(feature, old, new):
    """References to the profile's own axes follow the profile: FreeCAD finds a sketch's axes
    (N_Axis, V_Axis, H_Axis, AxisN = its Nth construction line) only on the feature's profile.
    A construction line axis becomes the profile object's V_Axis (its frame is laid on it)."""
    axis = getattr(feature, "ReferenceAxis", None)
    if not axis or axis[0] != old or not axis[1]:
        return
    sub = axis[1][0]
    if is_helper(new) and sub.startswith("Axis") and (sub[4:].isdigit() or sub == "Axis"):
        new.AxisRef = "Axis%d" % int(sub[4:] or 0)       # FreeCAD reads Axis0 back as "Axis"
        new.recompute()
        feature.ReferenceAxis = (new, ["V_Axis"])
    elif is_helper(old) and getattr(old, "AxisRef", "") and sub == "V_Axis":
        feature.ReferenceAxis = (new, [old.AxisRef])
    elif sub in ("N_Axis", "V_Axis", "H_Axis"):
        feature.ReferenceAxis = (new, list(axis[1]))


def _construction_axis(sketch, name):
    """(start, end) in the sketch's plane of its construction line AxisN, or None."""
    try:
        n = int(name[4:])
    except ValueError:
        return None
    lines = [g for i, g in enumerate(sketch.Geometry)
             if sketch.getConstruction(i) and g.TypeId == "Part::GeomLineSegment"]
    if not 0 <= n < len(lines):
        return None
    return lines[n].StartPoint, lines[n].EndPoint


def _frame(sketch, axis_ref):
    """The profile object's frame in the sketch's plane: the sketch's own, or one whose V axis
    is the construction line the revolve turns about."""
    line = _construction_axis(sketch, axis_ref) if axis_ref else None
    if line is None:
        return App.Placement()
    a, b = line
    y = b - a
    if y.Length < 1e-12:
        return App.Placement()
    y.normalize()
    z = V(0, 0, 1)
    x = y.cross(z)
    return App.Placement(a, App.Rotation(x, y, z, "ZXY"))


class _Plain:
    """The settings of a feature without a profile object: all off."""
    Picks = []
    From = "Sketch Plane"
    FromOffset = 0.0
    FromRef = None
    Thin = False
    ThinType = "One-Direction"
    ThinT1 = 1.0
    ThinT2 = 1.0
    ThinReverse = False
    CapEnds = False
    CapT = 1.0
    FlipSide = False


def settings(feature):
    """The feature's profile object, or the plain settings when it has none."""
    return helper_of(feature) or _Plain()


def set_options(feature, **values):
    """Changes the feature's Selected Contours, From or Thin Feature settings (picks=, From=,
    FromOffset=, FromRef=, Thin=, ThinType=, ThinT1=, ThinT2=, ThinReverse=). The profile object
    is made when a setting needs it and deleted when none does."""
    sketch = sketch_of(feature)
    if sketch is None:
        return None
    helper = helper_of(feature)
    doc = feature.Document
    if "picks" in values:
        # a contour picked as EdgeN is kept by its entity (g<id>), so it stays put when the sketch is edited
        values["Picks"] = [("C:" + stable_edge(sketch, p[2:])) if p.startswith("C:Edge") else p
                           for p in values.pop("picks")]
    current = {k: getattr(settings(feature), k, False) for k in ("Picks", "From", "Thin", "FlipSide")}
    current.update({k: v for k, v in values.items() if k in current})
    wanted = bool(current["Picks"]) or (current["From"] or "Sketch Plane") != "Sketch Plane" or \
        bool(current["Thin"]) or (bool(current["FlipSide"]) and bool(current["Picks"]))
    if not wanted:
        if helper is not None:
            _set_caps(feature, helper, False)
            feature.Profile = (sketch, [])
            _axis_to(feature, helper, sketch)
            if not [o for o in helper.InList if o.TypeId != "PartDesign::Body"]:
                body = _body(helper)
                if body is not None:
                    body.removeObject(helper)
                doc.removeObject(helper.Name)
        feature.recompute()
        return None
    if helper is None:
        helper = doc.addObject("Part::Part2DObjectPython", "SelectedContours")
        SelectedContours(helper)
        if App.GuiUp:
            SelectedContoursView(helper.ViewObject)
            helper.ViewObject.Visibility = False
        helper.Label = sketch.Label + " Selected Contours"
        helper.Sketch = sketch
        body = _body(sketch)
        if body is not None:
            body.insertObject(helper, sketch, True)
    for key, value in values.items():
        if value is None and key == "FromRef":
            helper.FromRef = None
        else:
            setattr(helper, key, value)
    helper.recompute()
    if feature.Profile[0] != helper:
        feature.Profile = (helper, [])
        _axis_to(feature, sketch, helper)
    feature.recompute()
    caps = bool(helper.Thin) and bool(helper.CapEnds) and caps_allowed(feature)
    pocket = _set_caps(feature, helper, caps)
    if pocket is not None:
        pocket.Profile[0].recompute()
        pocket.recompute()
    return helper


def set_picks(feature, picks):
    """Makes feature from the picks (no picks: from its whole sketch again)."""
    return set_options(feature, picks=picks)


# ---- the box on the feature's panel -------------------------------------------------------

def _edited():
    try:
        vp = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
        return vp.Object if vp is not None else None
    except Exception:
        return None


def _ray_hit(view, pos, placement):
    """The point (sketch-local) where the click at pos meets the sketch's plane, or None."""
    on_focal = V(view.getPoint(int(pos[0]), int(pos[1])))
    cam = view.getCameraNode()
    if cam.getTypeId().getName() == "PerspectiveCamera":
        eye = V(*cam.position.getValue().getValue())
        direction = on_focal - eye
        origin = eye
    else:
        direction = V(view.getViewDirection())
        origin = on_focal
    normal = placement.Rotation.multVec(V(0, 0, 1))
    denom = direction.dot(normal)
    if abs(denom) < 1e-12:
        return None
    t = (placement.Base - origin).dot(normal) / denom
    return placement.inverse().multVec(origin + direction * t)


def _no_body(feature):
    try:
        return not feature.isValid() or feature.Shape.isNull()
    except Exception:
        return True


class Contours(QtCore.QObject):
    """The Selected Contours box: a header that opens it and the list of picks."""

    def __init__(self, host, feature):
        super().__init__(host)
        self.doc = feature.Document.Name
        self.name = feature.Name
        self.sketch_name = sketch_of(feature).Name
        helper = helper_of(feature)
        self.picks = list(helper.Picks) if helper is not None else []
        self.callback = None
        self.view = None
        self.overlay = None
        self.sketch_was = None
        self.box = QtWidgets.QWidget(host)
        self.box.setObjectName(BOX)
        lay = QtWidgets.QVBoxLayout(self.box)
        lay.setContentsMargins(0, 6, 0, 0)
        self.header = QtWidgets.QToolButton(self.box)
        self.header.setObjectName(BOX + "Header")
        self.header.setText(TITLE)
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.header.setAutoRaise(True)
        font = self.header.font()
        font.setBold(True)
        self.header.setFont(font)
        lay.addWidget(self.header)
        self.list = QtWidgets.QListWidget(self.box)
        self.list.setObjectName(LIST)
        self.list.setToolTip(HINT)
        self.list.setMaximumHeight(110)
        self.list.setContextMenuPolicy(QtCore.Qt.ActionsContextMenu)
        delete = QtGui.QAction("Delete", self.list)
        delete.triggered.connect(self.delete_current)
        clear = QtGui.QAction("Clear Selections", self.list)
        clear.setObjectName("swstyle_clear_selections")     # selectionbox's name: it adds no second one
        clear.triggered.connect(self.clear)
        self.list.addAction(delete)
        self.list.addAction(clear)
        lay.addWidget(self.list)
        self.hint = QtWidgets.QLabel(HINT, self.box)
        self.hint.setWordWrap(True)
        self.hint.setObjectName(BOX + "Hint")
        lay.addWidget(self.hint)
        self.header.toggled.connect(self.opened)
        self.box.destroyed.connect(lambda *a, s=self: s.closed())
        self.fill()
        sketch = sketch_of(feature)
        waiting = not self.picks and regions(sketch) and (not feature.isValid() or crossing(sketch))
        self.header.setChecked(bool(self.picks or waiting))
        self.opened(self.header.isChecked())
        if not self.header.isChecked() and _no_body(feature) and App.GuiUp:

            # FreeCAD hides it, and with no preview the view went blank (tester run 3)
            self.sketch_was = sketch.ViewObject.Visibility
            sketch.ViewObject.Visibility = True

    # -- state
    def feature(self):
        try:
            return App.getDocument(self.doc).getObject(self.name)
        except Exception:
            return None

    def sketch(self):
        try:
            return App.getDocument(self.doc).getObject(self.sketch_name)
        except Exception:
            return None

    def fill(self):
        sketch = self.sketch()
        self.list.clear()
        if sketch is not None:
            self.list.addItems(names(sketch, self.picks))
        pass        # pkg90: the fold chevron at the right (pmlayout) shows the state

    def apply(self):
        feature = self.feature()
        if feature is None:
            return
        set_picks(feature, self.picks)
        self.fill()
        self.draw()

    def toggle(self, pick):
        sketch = self.sketch()
        kind, value = _parse(pick)
        if kind == "R":
            faces = regions(sketch)
            face = region_at(faces, value)
            if face is None:
                return False
            for old in list(self.picks):
                k, v = _parse(old)
                if k == "R" and face.isInside(v, 1e-6, True):
                    self.picks.remove(old)
                    self.apply()
                    return True
        else:
            wire = contour_of(sketch, value)
            if wire is None:
                return False
            for old in list(self.picks):
                k, v = _parse(old)
                other = contour_of(sketch, v) if k == "C" else None
                if old == pick or (other is not None and other.isSame(wire)):
                    self.picks.remove(old)       # any entity of a picked contour un-picks it
                    self.apply()
                    return True
        self.picks.append(pick)
        self.apply()
        return True

    def delete_current(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.picks):
            del self.picks[row]
            self.apply()

    def clear(self):
        self.picks = []
        self.apply()

    # -- open / closed
    def opened(self, on):
        self.list.setVisible(on)
        self.hint.setVisible(on)
        pass        # pkg90: the fold chevron at the right (pmlayout) shows the state
        sketch = self.sketch()
        if on:
            self._listen()
            if sketch is not None and App.GuiUp:
                if self.sketch_was is None:
                    self.sketch_was = sketch.ViewObject.Visibility
                sketch.ViewObject.Visibility = True
            try:
                Gui.getMainWindow().statusBar().showMessage(HINT)
            except Exception as _fw_err:
                _fw_log("contours.py:975", _fw_err)
        else:
            self._unlisten()
            if sketch is not None and self.sketch_was is not None:
                sketch.ViewObject.Visibility = self.sketch_was
                self.sketch_was = None
        self.draw()

    def closed(self):
        """The panel went away (OK or Cancel)."""
        self._unlisten()
        self._clear_overlay()
        QtCore.QTimer.singleShot(0, self._settle)

    def _settle(self):
        sketch = self.sketch()
        if sketch is None:
            return
        feature = self.feature()
        try:
            # kept: the sketch goes back under the feature, hidden; cancelled new feature: shown
            sketch.ViewObject.Visibility = feature is None
        except Exception as _fw_err:
            _fw_log("contours.py:998", _fw_err)

    # -- clicks in the view
    def _listen(self):
        if self.callback is not None:
            return
        try:
            from pivy import coin
            view = Gui.ActiveDocument.ActiveView
            self.view = view
            self.callback = view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self._clicked)
        except Exception as error:
            App.Console.PrintLog("FreeCAD Selected Contours: no click watch (%s)\n" % error)
            self.callback = None

    def _unlisten(self):
        if self.callback is None:
            return
        try:
            from pivy import coin
            self.view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.callback)
        except Exception as _fw_err:
            _fw_log("contours.py:1020", _fw_err)
        self.callback = None

    def _busy(self):
        """Another pick box of the panel is waiting for a pick (FreeCAD's Select face...)."""
        try:
            root = self.box.window()
            for b in root.findChildren(QtWidgets.QAbstractButton):
                if b is not self.header and b.isCheckable() and b.isChecked() and b.isVisible() \
                        and isinstance(b, QtWidgets.QPushButton):
                    return True
        except RuntimeError:
            return True
        return False

    def _clicked(self, cb):
        from pivy import coin
        event = cb.getEvent()
        if event.getButton() != coin.SoMouseButtonEvent.BUTTON1 or self._busy():
            return
        if not coin.SoMouseButtonEvent.isButtonPressEvent(event, coin.SoMouseButtonEvent.BUTTON1):
            if coin.SoMouseButtonEvent.isButtonReleaseEvent(event, coin.SoMouseButtonEvent.BUTTON1) and \
                    getattr(self, "_took", False):
                cb.setHandled()
                self._took = False
            return
        pos = event.getPosition().getValue()
        sketch = self.sketch()
        if sketch is None:
            return
        pick = None
        info = self.view.getObjectInfo((int(pos[0]), int(pos[1])))
        if info and info.get("Object") == sketch.Name and str(info.get("Component", "")).startswith("Edge"):
            if contour_of(sketch, info["Component"]) is not None:
                pick = "C:" + stable_edge(sketch, info["Component"])
        if pick is None:
            hit = _ray_hit(self.view, pos, sketch.getGlobalPlacement())
            if hit is not None and region_at(regions(sketch), hit) is not None:
                pick = "R:%.6g,%.6g" % (hit.x, hit.y)
        if pick is None:
            return
        cb.setHandled()
        self._took = True
        QtCore.QTimer.singleShot(0, lambda p=pick: self._take(p))

    def _take(self, pick):
        doc = App.getDocument(self.doc)
        self.toggle(pick)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("contours.py:1071", _fw_err)
        doc.recompute()

    # -- shading of the picked areas
    def _clear_overlay(self):
        if self.overlay is not None:
            view, node = self.overlay
            try:
                view.getSceneGraph().removeChild(node)
            except Exception as _fw_err:
                _fw_log("contours.py:1081", _fw_err)
            self.overlay = None

    def draw(self):
        self._clear_overlay()
        if not self.header.isChecked() or not self.picks:
            return
        sketch = self.sketch()
        if sketch is None:
            return
        try:
            shape = _merged(picked_faces(sketch, self.picks))
            shape.Placement = sketch.getGlobalPlacement()
        except Exception:
            return
        if shape.isNull():
            return
        from pivy import coin
        root = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*SHADE)
        mat.transparency.setValue(0.25)
        offset = coin.SoPolygonOffset()
        offset.factor = -1.0
        offset.units = -1.0
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
        for n in (pick, light, mat, offset, hints):
            root.addChild(n)
        points, tris = shape.tessellate(0.05)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
        faces = coin.SoIndexedFaceSet()
        index = []
        for a, b, c in tris:
            index += [a, b, c, -1]
        faces.coordIndex.setValues(0, len(index), index)
        root.addChild(coords)
        root.addChild(faces)
        view = Gui.ActiveDocument.ActiveView
        view.getSceneGraph().addChild(root)
        self.overlay = (view, root)


# ---- From and Thin Feature ------------------------------------------------------------------

FROM_BOX = "SWStyle_From"
THIN_BOX = "SWStyle_ThinFeature"
EXTRUDES = ("PartDesign::Pad", "PartDesign::Pocket")


def _length_box(parent, name, value, low=0.0):
    box = QtWidgets.QDoubleSpinBox(parent)
    box.setObjectName(name)
    box.setRange(low, 1e6)
    box.setDecimals(2)
    box.setSuffix(" mm")
    box.setValue(value)
    box.setKeyboardTracking(False)
    return box


def _header(parent, text):
    label = QtWidgets.QLabel(text, parent)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


class _Part(QtCore.QObject):
    """A box of the feature's panel that changes the feature's profile settings."""

    def __init__(self, host, feature):
        super().__init__(host)
        self.doc = feature.Document.Name
        self.name = feature.Name

    def feature(self):
        try:
            return App.getDocument(self.doc).getObject(self.name)
        except Exception:
            return None

    def change(self, **values):
        feature = self.feature()
        if feature is None:
            return
        try:
            set_options(feature, **values)
            self.note("")
        except Exception as error:
            self.note(str(error))
        feature.Document.recompute()

    def note(self, text):
        pass


class FromBox(_Part):
    ""

    def __init__(self, host, feature):
        super().__init__(host, feature)
        opts = settings(feature)
        self.callback = None
        self.view = None
        self.box = QtWidgets.QWidget(host)
        self.box.setObjectName(FROM_BOX)
        lay = QtWidgets.QVBoxLayout(self.box)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.addWidget(_header(self.box, "From"))
        self.mode = QtWidgets.QComboBox(self.box)
        self.mode.setObjectName(FROM_BOX + "Mode")
        self.mode.addItems(FROM_MODES)
        self.mode.setCurrentText(opts.From or "Sketch Plane")
        lay.addWidget(self.mode)
        row = QtWidgets.QHBoxLayout()
        self.flip = QtWidgets.QToolButton(self.box)
        self.flip.setObjectName(FROM_BOX + "Reverse")
        self.flip.setCheckable(True)
        self.flip.setText("\u21c5")
        self.flip.setToolTip("Reverse Direction")
        offset = float(opts.FromOffset)
        self.flip.setChecked(offset < 0)
        self.offset = _length_box(self.box, FROM_BOX + "Offset", abs(offset) or 10.0)
        row.addWidget(self.flip)
        row.addWidget(self.offset)
        lay.addLayout(row)
        self.ref = QtWidgets.QLineEdit(self.box)
        self.ref.setObjectName(FROM_BOX + "Ref")
        self.ref.setReadOnly(True)
        self.ref.setPlaceholderText("Pick a face or plane")
        lay.addWidget(self.ref)
        self.msg = QtWidgets.QLabel(self.box)
        self.msg.setObjectName(FROM_BOX + "Note")
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color: #d03a3a")
        lay.addWidget(self.msg)
        self._show_ref(opts.FromRef)
        self.mode.activated.connect(self.mode_picked)
        self.offset.valueChanged.connect(self.offset_changed)
        self.flip.toggled.connect(self.offset_changed)
        self.box.destroyed.connect(lambda *a, s=self: s._unlisten())
        self.layout_for()

    def note(self, text):
        try:
            self.msg.setText(text)
            self.msg.setVisible(bool(text))
        except RuntimeError as _fw_err:
            _fw_log("contours.py:1236", _fw_err)

    def _show_ref(self, ref):
        if ref and ref[0] is not None:
            sub = ref[1][0] if ref[1] and ref[1][0] else ""
            self.ref.setText(("%s of %s" % (sub, ref[0].Label)) if sub else ref[0].Label)
        else:
            self.ref.clear()

    def layout_for(self):
        mode = self.mode.currentText()
        self.offset.setVisible(mode == "Offset")
        self.flip.setVisible(mode == "Offset")
        self.ref.setVisible(mode in ("Surface/Face/Plane", "Vertex"))
        self.ref.setPlaceholderText("Pick a vertex" if mode == "Vertex" else "Pick a face or plane")
        if mode in ("Surface/Face/Plane", "Vertex"):
            self._listen()
        else:
            self._unlisten()
        self.note(self.msg.text() if self.msg.text() else "")

    def mode_picked(self, *args):
        mode = self.mode.currentText()
        self.ref.clear()
        if mode == "Offset":
            self.change(From=mode, FromOffset=self._signed(), FromRef=None)
        elif mode == "Sketch Plane":
            self.change(From=mode, FromOffset=0.0, FromRef=None)
        else:
            self.note("")       # waits for a pick; the feature stays where it was until then
        self.layout_for()

    def _signed(self):
        return -self.offset.value() if self.flip.isChecked() else self.offset.value()

    def offset_changed(self, *args):
        if self.mode.currentText() == "Offset":
            self.change(From="Offset", FromOffset=self._signed())

    # -- picking the face or vertex
    def _listen(self):
        if self.callback is not None:
            return
        try:
            from pivy import coin
            self.view = Gui.ActiveDocument.ActiveView
            self.callback = self.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self._clicked)
        except Exception:
            self.callback = None

    def _unlisten(self):
        if self.callback is None:
            return
        try:
            from pivy import coin
            self.view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.callback)
        except Exception as _fw_err:
            _fw_log("contours.py:1293", _fw_err)
        self.callback = None

    def _clicked(self, cb):
        from pivy import coin
        event = cb.getEvent()
        if not coin.SoMouseButtonEvent.isButtonPressEvent(event, coin.SoMouseButtonEvent.BUTTON1):
            return
        pos = event.getPosition().getValue()
        info = self.view.getObjectInfo((int(pos[0]), int(pos[1])))
        if not info:
            return
        doc = App.getDocument(self.doc)
        obj = doc.getObject(info.get("Object", ""))
        sub = str(info.get("Component", "") or "")
        if obj is None:
            return
        mode = self.mode.currentText()
        plane = obj.TypeId in ("PartDesign::Plane", "App::Plane", "Part::DatumPlane")
        if mode == "Vertex" and not sub.startswith("Vertex"):
            return
        if mode != "Vertex" and not (sub.startswith("Face") or plane):
            return
        cb.setHandled()
        ref = (obj, [sub if not plane else ""])
        QtCore.QTimer.singleShot(0, lambda: self._take(mode, ref))

    def _take(self, mode, ref):
        self._show_ref(ref)
        self.change(From=mode, FromRef=ref)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("contours.py:1326", _fw_err)


def _alive_widget(widget):
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False


def _thin_label(feature, thin):
    ""

    import re
    try:
        from . import naming
        label = feature.Label
        for word in ("Boss-Extrude", "Cut-Extrude", "Revolve", "Cut-Revolve"):
            plain = re.match(r"^%s(\d+)$" % re.escape(word), label)
            thinned = re.match(r"^%s-Thin(\d+)$" % re.escape(word), label)
            if thin and plain:
                feature.Label = naming.next_label(feature.Document, word + "-Thin")
            elif not thin and thinned:
                feature.Label = naming.next_label(feature.Document, word)
            else:
                continue
            return
    except Exception as _fw_err:
        _fw_log("contours.py:1355", _fw_err)


def _open_only(feature):
    """The feature's sketch has curves and no closed loop (a line, an arc, an open chain)."""
    try:
        sketch = sketch_of(feature)
        if sketch is None:
            return False
        wires = _local(sketch).Wires
        return bool(wires) and not any(w.isClosed() for w in wires)
    except Exception:
        return False


class ThinBox(_Part):
    ""

    def __init__(self, host, feature):
        super().__init__(host, feature)
        opts = settings(feature)
        self.box = QtWidgets.QWidget(host)
        self.box.setObjectName(THIN_BOX)
        lay = QtWidgets.QVBoxLayout(self.box)
        lay.setContentsMargins(0, 6, 0, 0)
        self.on = QtWidgets.QCheckBox("Thin Feature", self.box)
        self.on.setObjectName(THIN_BOX + "On")
        font = self.on.font()
        font.setBold(True)
        self.on.setFont(font)
        self.on.setChecked(bool(opts.Thin))
        lay.addWidget(self.on)
        self.body = QtWidgets.QWidget(self.box)
        inner = QtWidgets.QVBoxLayout(self.body)
        inner.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        self.reverse = QtWidgets.QToolButton(self.body)
        self.reverse.setObjectName(THIN_BOX + "Reverse")
        self.reverse.setCheckable(True)
        self.reverse.setText("\u21c5")
        self.reverse.setToolTip("Reverse Direction")
        self.reverse.setChecked(bool(opts.ThinReverse))
        self.kind = QtWidgets.QComboBox(self.body)
        self.kind.setObjectName(THIN_BOX + "Type")
        self.kind.addItems(THIN_TYPES)
        self.kind.setCurrentText(opts.ThinType or "One-Direction")
        row.addWidget(self.reverse)
        row.addWidget(self.kind)
        inner.addLayout(row)
        form = QtWidgets.QFormLayout()
        self.t1 = _length_box(self.body, THIN_BOX + "T1", float(opts.ThinT1) or 1.0, 0.01)
        self.t2 = _length_box(self.body, THIN_BOX + "T2", float(opts.ThinT2) or 1.0, 0.01)
        form.addRow("T1", self.t1)
        self.t2_label = QtWidgets.QLabel("T2", self.body)
        form.addRow(self.t2_label, self.t2)
        inner.addLayout(form)
        self.caps_ok = caps_allowed(feature)
        self.cap = QtWidgets.QCheckBox("Cap ends", self.body)
        self.cap.setObjectName(THIN_BOX + "CapEnds")
        self.cap.setChecked(bool(getattr(opts, "CapEnds", False)))
        inner.addWidget(self.cap)
        cap_form = QtWidgets.QFormLayout()
        self.capt = _length_box(self.body, THIN_BOX + "CapT", float(getattr(opts, "CapT", 0) or 0)
                                or float(opts.ThinT1) or 1.0, 0.01)
        self.capt_label = QtWidgets.QLabel("Cap Thickness", self.body)
        cap_form.addRow(self.capt_label, self.capt)
        inner.addLayout(cap_form)

        self.rounds_ok = _open_only(feature) and getattr(feature, "TypeId", "") == "PartDesign::Pad"
        self.rounds = QtWidgets.QCheckBox("Auto-fillet corners", self.body)
        self.rounds.setObjectName(THIN_BOX + "AutoFillet")
        self.rounds.setChecked(bool(getattr(opts, "AutoFillet", False)))
        inner.addWidget(self.rounds)
        rounds_form = QtWidgets.QFormLayout()
        self.radius = _length_box(self.body, THIN_BOX + "FilletRadius", float(getattr(opts, "FilletRadius", 0) or 0) or 1.0, 0.01)
        self.radius_label = QtWidgets.QLabel("Fillet Radius", self.body)
        rounds_form.addRow(self.radius_label, self.radius)
        inner.addLayout(rounds_form)
        lay.addWidget(self.body)
        self.on.toggled.connect(self.changed)
        self.kind.activated.connect(self.changed)
        self.reverse.toggled.connect(self.changed)
        self.t1.valueChanged.connect(self.changed)
        self.t2.valueChanged.connect(self.changed)
        self.cap.toggled.connect(self.changed)
        self.capt.valueChanged.connect(self.changed)
        self.rounds.toggled.connect(self.changed)
        self.radius.valueChanged.connect(self.changed)
        self.layout_for()
        if not opts.Thin and _open_only(feature):

            QtCore.QTimer.singleShot(0, lambda: self.on.setChecked(True) if _alive_widget(self.on) else None)

    def layout_for(self):
        self.body.setVisible(self.on.isChecked())
        two = self.kind.currentText() == "Two-Direction"
        self.t2.setVisible(two)
        self.t2_label.setVisible(two)
        self.reverse.setEnabled(self.kind.currentText() != "Mid-Plane")
        self.cap.setVisible(self.caps_ok)
        capped = self.caps_ok and self.cap.isChecked()
        self.capt.setVisible(capped)
        self.capt_label.setVisible(capped)
        self.rounds.setVisible(self.rounds_ok)
        rounded = self.rounds_ok and self.rounds.isChecked()
        self.radius.setVisible(rounded)
        self.radius_label.setVisible(rounded)

    def changed(self, *args):
        self.layout_for()
        _thin_label(self.feature(), self.on.isChecked())
        self.change(Thin=self.on.isChecked(), ThinType=self.kind.currentText(), ThinT1=self.t1.value(),
                    ThinT2=self.t2.value(), ThinReverse=self.reverse.isChecked(),
                    CapEnds=self.cap.isChecked(), CapT=self.capt.value(),
                    AutoFillet=self.rounds_ok and self.rounds.isChecked(), FilletRadius=self.radius.value())


def _form_of(view):
    boxes = [w for w in view.findChildren(QtWidgets.QWidget) if w.inherits("QSint::ActionGroup")]
    target = boxes[0] if boxes else None
    if target is None:
        return None
    forms = [w for w in target.findChildren(QtWidgets.QWidget) if isinstance(w, QtWidgets.QWidget)    # not a stale layout-item wrapper
             and w.layout() is not None and w.parentWidget() is not None and w.parentWidget().parentWidget() is target]
    return forms[0] if forms else None


def install(view):
    """Adds From (Extrude and Cut), Thin Feature and Selected Contours to the extrude or revolve
    being edited (idempotent; called on each refresh of the PropertyManager)."""
    feature = _edited()
    if feature is None or feature.TypeId not in TYPES or sketch_of(feature) is None:
        return
    if view.findChild(QtWidgets.QWidget, BOX) is not None:
        return
    form = _form_of(view)
    if form is None:
        return
    key = feature.Document.Name + "." + feature.Name
    lay = form.layout()
    if feature.TypeId in EXTRUDES:
        start = FromBox(form, feature)
        if isinstance(lay, QtWidgets.QBoxLayout):
            lay.insertWidget(0, start.box)
        elif isinstance(lay, QtWidgets.QGridLayout):
            # FreeCAD's panel is a grid: move its rows down one and put From on top
            items = pmfields.take_grid_rows(lay, lambda r: False)
            lay.addWidget(start.box, 0, 0, 1, max(2, lay.columnCount()))
            pmfields.put_grid_rows(lay, items)
        else:
            lay.addWidget(start.box)
        _live[key + ".from"] = start
        start.box.destroyed.connect(lambda *a, k=key + ".from": _live.pop(k, None))
    thin = ThinBox(form, feature)
    lay.addWidget(thin.box) if not isinstance(lay, QtWidgets.QGridLayout) else \
        lay.addWidget(thin.box, lay.rowCount(), 0, 1, max(2, lay.columnCount()))
    _live[key + ".thin"] = thin
    thin.box.destroyed.connect(lambda *a, k=key + ".thin": _live.pop(k, None))
    box = Contours(form, feature)
    lay.addWidget(box.box) if not isinstance(lay, QtWidgets.QGridLayout) else \
        lay.addWidget(box.box, lay.rowCount(), 0, 1, max(2, lay.columnCount()))
    _live[key] = box
    box.box.destroyed.connect(lambda *a, k=key: _live.pop(k, None))


_live = {}
