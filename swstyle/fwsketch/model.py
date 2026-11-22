# SPDX-License-Identifier: LGPL-2.1-or-later
""






import math

import FreeCAD as App
import Part

from . import inference as I

CONFUSION = 1e-7  # Precision::Confusion()
TWO_PI = 2 * math.pi
V = App.Vector


class ModelElement:
    __slots__ = ("name", "geometry", "start_vertex", "end_vertex", "projected")

    def __init__(self, name, geometry, start_vertex="", end_vertex="", projected=False):
        self.name, self.geometry = name, geometry   # geometry in sketch coordinates (z = 0)
        self.start_vertex, self.end_vertex = start_vertex, end_vertex
        self.projected = projected

    def __repr__(self):
        return "%s%s %s" % (self.name, " projected" if self.projected else "", type(self.geometry).__name__)


def _flat(p):
    return V(p.x, p.y, 0.0)


def _same(p, q):
    return (p - q).Length <= CONFUSION


class _Occluders:
    """The shape's planar faces parallel to the sketch plane: each hides what lies behind it,
    further from someone looking at the sketch along -z, within its outline."""

    def __init__(self, shape, placement, tolerance):
        self.placement = placement
        self.tol = max(tolerance, CONFUSION)
        self.faces = []
        to_sketch = placement.inverse()
        rot = to_sketch.Rotation
        for face in shape.Faces:
            surf = face.Surface
            if not isinstance(surf, Part.Plane):
                continue
            normal = rot.multVec(surf.Axis)
            if abs(abs(normal.z) - 1.0) > 1e-9:
                continue
            bb = face.BoundBox
            if not bb.isValid():
                continue
            z = to_sketch.multVec(surf.Position).z
            xs, ys = [], []
            for x in (bb.XMin, bb.XMax):
                for y in (bb.YMin, bb.YMax):
                    for zz in (bb.ZMin, bb.ZMax):
                        c = to_sketch.multVec(V(x, y, zz))
                        xs.append(c.x)
                        ys.append(c.y)
            self.faces.append((face, z, min(xs), max(xs), min(ys), max(ys)))

    def hides(self, p):
        """p in sketch coordinates with its own z."""
        t = self.tol
        for face, z, xmin, xmax, ymin, ymax in self.faces:
            if p.z >= z - t or p.x < xmin - t or p.x > xmax + t or p.y < ymin - t or p.y > ymax + t:
                continue
            on_face = self.placement.multVec(V(p.x, p.y, z))
            # As BRepClass_FaceClassifier state IN: on the face and not on its boundary
            # (Face.isInside counts the boundary too, so the wires are checked apart).
            if face.isInside(on_face, t, False):
                vertex = Part.Vertex(on_face)
                if all(w.distToShape(vertex)[0] > t for w in face.Wires):
                    return True
        return False

    def hides_any(self, points):
        return any(self.hides(p) for p in points)


def _append_points(g, points):
    if type(g) is Part.Point:
        points.append(V(g.X, g.Y, g.Z))
    elif type(g) is Part.LineSegment:
        points.append(g.StartPoint)
        points.append(g.EndPoint)
    elif type(g) is Part.ArcOfCircle:
        a, b = I.arc_ends_ccw(g)
        points.append(V(a[0], a[1], 0))
        points.append(V(b[0], b[1], 0))
        points.append(g.Center)
    elif type(g) is Part.Circle:
        points.append(g.Center)


def _distance_to(g, p):
    """Distance in the sketch plane from p to a point, line, circle or arc; inf otherwise."""
    if type(g) is Part.Point:
        return (V(g.X, g.Y, g.Z) - p).Length
    if type(g) is Part.LineSegment:
        s = g.StartPoint
        d = g.EndPoint - s
        l2 = d.dot(d)
        t = min(max((p - s).dot(d) / l2, 0.0), 1.0) if l2 > 0.0 else 0.0
        return (s + d * t - p).Length
    if type(g) is Part.ArcOfCircle:
        d = I.distance_to_curve(0, g, (p.x, p.y))
        return d if d >= 0.0 else math.inf
    if type(g) is Part.Circle:
        return abs((p - g.Center).Length - g.Radius)
    return math.inf


def same_geometry(a, b):
    """Two snap geometries of the same kind at the same place (a line also with ends swapped)."""
    if a is None or b is None or type(a) is not type(b):
        return False
    if type(a) is Part.Point:
        return _same(V(a.X, a.Y, a.Z), V(b.X, b.Y, b.Z))
    if type(a) is Part.LineSegment:
        return (_same(a.StartPoint, b.StartPoint) and _same(a.EndPoint, b.EndPoint)) or \
               (_same(a.StartPoint, b.EndPoint) and _same(a.EndPoint, b.StartPoint))
    if type(a) is Part.Circle:
        return _same(a.Center, b.Center) and abs(a.Radius - b.Radius) <= CONFUSION
    if type(a) is Part.ArcOfCircle:
        sa, ea = I.arc_ends_ccw(a)
        sb, eb = I.arc_ends_ccw(b)
        return _same(a.Center, b.Center) and abs(a.Radius - b.Radius) <= CONFUSION and \
            _same(V(sa[0], sa[1], 0), V(sb[0], sb[1], 0)) and _same(V(ea[0], ea[1], 0), V(eb[0], eb[1], 0))
    return False


def _make_arc(center, radius, a0, a1):
    """CCW arc in the sketch plane from angle a0 to a1 (a0 < a1)."""
    return Part.ArcOfCircle(Part.Circle(_flat(center), V(0, 0, 1), radius), a0, a1)


def model_elements(shape, placement):
    """The edges and vertices of shape as snap targets of a sketch placed at placement. In-plane
    edges first, then projections (nearest the viewer first), then lone vertices as points.
    Left out: what the shape's faces parallel to the plane hide, projections that are no line,
    circle or arc, and repeats."""
    elements = []
    if shape is None or shape.isNull():
        return elements
    to_sketch = placement.inverse()
    rot = to_sketch.Rotation
    local = to_sketch.multVec
    tolerance = 1e-7 * (1.0 + shape.BoundBox.DiagonalLength)
    in_plane = lambda p: abs(p.z) <= tolerance
    occluders = _Occluders(shape, placement, tolerance)

    edges = shape.Edges
    vertexes = shape.Vertexes
    # Vertex index by hash: FreeCAD's VertexN numbering is the order of shape.Vertexes
    vindex = {}
    for i, v in enumerate(vertexes):
        vindex.setdefault(v.hashCode(), i + 1)

    def vertex_name(v):
        i = vindex.get(v.hashCode(), 0) if v is not None else 0
        return "Vertex%d" % i if i > 0 else ""

    def candidate_of(i):
        """(element, samples, first, last) for edge i (1-based) or None."""
        edge = edges[i - 1]
        if edge.isNull() or edge.Degenerated:
            return None
        vs = edge.Vertexes
        first = vs[0] if vs else None
        last = vs[-1] if len(vs) > 1 else first
        if edge.Orientation == "Reversed" and len(vs) > 1:
            first, last = last, first
        curve = edge.Curve
        name = "Edge%d" % i
        samples = []
        if isinstance(curve, Part.Line) or type(curve) is Part.LineSegment:
            if first is None or last is None:
                return None
            start, end = local(first.Point), local(last.Point)
            if (_flat(end) - _flat(start)).Length <= tolerance:
                return None
            geo = Part.LineSegment(_flat(start), _flat(end))
            el = ModelElement(name, geo, vertex_name(first), vertex_name(last),
                              not in_plane(start) or not in_plane(end))
            for t in (0.0, 0.25, 0.5, 0.75, 1.0):
                samples.append(start + (end - start) * t)
            return el, samples, first, last
        if isinstance(curve, Part.Circle):
            center = local(curve.Center)
            axis = rot.multVec(curve.Axis)
            if abs(abs(axis.z) - 1.0) > 1e-9:
                return None
            projected = not in_plane(center)
            u0, u1 = edge.FirstParameter, edge.LastParameter
            for k in range(8):
                samples.append(local(edge.valueAt(u0 + (u1 - u0) * k / 8.0)))
            if abs((u1 - u0) - TWO_PI) <= 1e-9:
                geo = Part.Circle(_flat(center), V(0, 0, 1), curve.Radius)
                return ModelElement(name, geo, "", "", projected), samples, first, last
            samples.append(local(edge.valueAt(u1)))
            start, end = local(edge.valueAt(u0)), local(edge.valueAt(u1))
            if axis.z < 0.0:
                start, end = end, start
            a0 = math.atan2(start.y - center.y, start.x - center.x)
            a1 = math.atan2(end.y - center.y, end.x - center.x)
            while a1 <= a0:
                a1 += TWO_PI
            geo = _make_arc(center, curve.Radius, a0, a1)
            sv = ev = ""
            if first is not None and last is not None:
                first_at_start = (local(first.Point) - start).Length <= (local(last.Point) - start).Length
                sv = vertex_name(first if first_at_start else last)
                ev = vertex_name(last if first_at_start else first)
            return ModelElement(name, geo, sv, ev, projected), samples, first, last
        return None

    vertex_on_edge = set()
    points = []

    def accept(cand):
        el, samples, first, last = cand
        for v in (first, last):
            if v is not None:
                vertex_on_edge.add(vindex.get(v.hashCode(), 0))
        _append_points(el.geometry, points)
        elements.append(el)

    def repeats(g):
        return any(same_geometry(e.geometry, g) for e in elements)

    n = len(edges)
    cands = [candidate_of(i) for i in range(1, n + 1)]
    for c in cands:
        if c and not c[0].projected and not occluders.hides_any(c[1]):
            accept(c)
    projections = []
    for c in cands:
        if c and c[0].projected:
            z = sum(s.z for s in c[1]) / len(c[1])
            projections.append((z, c))
    projections.sort(key=lambda zc: -zc[0])
    for z, c in projections:
        if not occluders.hides_any(c[1]) and not repeats(c[0].geometry):
            accept(c)


    # sketch plane, of a sphere (fix58). FreeCAD has no element for them: a point placed there
    # is related through a hidden Silhouette Edge object (silhouette.py, snap.py; fix226).
    for sil, samples in _silhouettes(shape, local, rot, tolerance):
        if not occluders.hides_any(samples) and not repeats(sil.geometry):
            elements.append(sil)
            _append_points(sil.geometry, points)

    for i, v in enumerate(vertexes, 1):
        if i in vertex_on_edge or vindex.get(v.hashCode()) != i:
            continue
        p = local(v.Point)
        q = _flat(p)
        if occluders.hides(p) or any(_same(q, o) for o in points) or \
                any(_distance_to(e.geometry, q) <= CONFUSION for e in elements):
            continue
        points.append(q)
        elements.append(ModelElement("Vertex%d" % i, Part.Point(q), "", "", not in_plane(p)))
    return elements


SILHOUETTE = "Silhouette"


def is_silhouette(element):
    return element.name.startswith(SILHOUETTE)


def _silhouettes(shape, local, rot, tolerance):
    """[(ModelElement, samples)] of the outline lines of cylindrical faces whose axis lies along
    the sketch plane and the outline circles of spherical faces, in sketch coordinates."""
    out = []
    for k, face in enumerate(shape.Faces, 1):
        surf = face.Surface
        name = "%s%d" % (SILHOUETTE, k)
        try:
            if isinstance(surf, Part.Cylinder):
                axis = rot.multVec(surf.Axis)
                if abs(axis.z) > 1e-7:
                    continue
                d = V(axis.x, axis.y, 0)
                d.normalize()
                n = V(-d.y, d.x, 0)
                c = local(surf.Center)
                u0, u1, v0, v1 = face.ParameterRange
                # the silhouette is where the surface normal lies in the plane: u where the
                # radial direction is +-n; keep the side the face really covers
                for sign in (1.0, -1.0):
                    a = c + n * (sign * surf.Radius)
                    p0, p1 = _flat(a + d * v0), _flat(a + d * v1)
                    probe = a + d * (0.5 * (v0 + v1))
                    if (p1 - p0).Length <= tolerance or not _on_face(face, local, probe):
                        continue
                    geo = Part.LineSegment(p0, p1)
                    samples = [a + d * (v0 + (v1 - v0) * t) for t in (0.1, 0.5, 0.9)]
                    out.append((ModelElement("%s_%s" % (name, "a" if sign > 0 else "b"), geo, "", "", True), samples))
            elif isinstance(surf, Part.Sphere):
                c = local(surf.Center)
                geo = Part.Circle(_flat(c), V(0, 0, 1), surf.Radius)
                samples = [c + V(math.cos(t), math.sin(t), 0) * surf.Radius for t in (0.0, 2.1, 4.2)]
                if all(_on_face(face, local, s) for s in samples[:1]):
                    out.append((ModelElement(name, geo, "", "", True), samples))
        except Exception:
            continue
    return out


def _on_face(face, local, p_sketch):
    """True when the sketch-coordinate point p_sketch lies on face (world coordinates)."""
    try:
        return face.isInside(_to_world(local, p_sketch), 1e-4, True)
    except Exception:
        return True


def _to_world(local, p):
    """local is placement.inverse().multVec: undo it numerically (3 probes)."""
    o = local(V(0, 0, 0))
    ex, ey, ez = local(V(1, 0, 0)) - o, local(V(0, 1, 0)) - o, local(V(0, 0, 1)) - o
    m = App.Matrix(ex.x, ey.x, ez.x, o.x, ex.y, ey.y, ez.y, o.y, ex.z, ey.z, ez.z, o.z)
    return m.inverse().multVec(p)


def model_elements_in_plane(shape, placement):
    return [e for e in model_elements(shape, placement) if not e.projected]


def reference_target(element, pos):
    """(element name, pos) a snap to pos of element refers to: an end of an open edge refers to
    the vertex there (its point is start)."""
    if type(element.geometry) is Part.Point:
        return element.name, I.START
    if pos == I.START and element.start_vertex:
        return element.start_vertex, I.START
    if pos == I.END and element.end_vertex:
        return element.end_vertex, I.START
    return element.name, pos


def find_external_reference(sketch, obj, element):
    """geoId of the sketch's external geometry for element of obj, or None (references.py maps
    links to geometries, also when an intersection link gives several)."""
    from . import references
    if obj is None:
        return None
    return references.find(sketch, obj, element)


def add_reference(sketch, obj, element):
    """geoId of the external reference to element of obj, adding it when missing. On stock
    FreeCAD a normal, visible external reference; references.py records it as automatic (the
    C++ build's hidden AutomaticReference flag), so the relations panel names it Edge<n>@Part
    and drops it with its last relation. None when it cannot be referenced."""
    from . import references
    if obj is None:
        return None
    return references.add(sketch, obj, element)
