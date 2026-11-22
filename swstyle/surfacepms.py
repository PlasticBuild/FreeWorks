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

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
    from . import pmboxes
except ImportError:     # FreeCAD without its interface
    Gui = QtCore = QtWidgets = None

V = App.Vector
GROUP = "Surface"
BIG = 1e4

EXTRUDE_ENDS = ("Blind", "Up To Vertex", "Up To Surface", "Offset From Surface", "Up To Body", "Mid Plane")
EXTRUDE_ENDS2 = EXTRUDE_ENDS[:-1]
EXTRUDE_FROM = ("Sketch Plane", "Surface/Face/Plane", "Vertex", "Offset")
REVOLVE_ENDS = ("Blind", "Up To Vertex", "Up To Surface", "Offset From Surface", "Mid-Plane")
REVOLVE_ENDS2 = REVOLVE_ENDS[:-1]
SWEEP_PROFILES = ("Sketch Profile", "Circular Profile")
SWEEP_ORIENTATIONS = ("Follow Path", "Keep Normal Constant")
SWEEP_TWISTS = ("None", "Specify Twist Value", "Specify Direction Vector", "Tangent to Adjacent Faces", "Natural",
                "Follow Path and 1st Guide Curve", "Follow 1st and 2nd Guide Curves")
TWIST_UNITS = ("Degrees", "Radians", "Turns")
SWEEP_TANGENCY = ("None", "Path Tangent")
GUIDE_INFLUENCE = ("To Next Guide", "To Next Sharp", "To Next Edge", "Global")
LOFT_CONSTRAINTS = ("Default", "None", "Direction Vector", "Normal To Profile", "Tangency To Face",
                    "Curvature To Face")
RULED_TYPES = ("Tangent to Surface", "Normal to Surface", "Tapered to Vector", "Perpendicular to Vector", "Sweep")
RULED_VECTOR = RULED_TYPES[2:]
PLANES = ("App::Plane", "PartDesign::Plane")


# --------------------------------------------------------------------------- geometry from links
def items(links):
    """[(obj, sub)] of a LinkSubList, a whole object as sub ""."""
    out = []
    for obj, subs in links or []:
        subs = subs if isinstance(subs, (list, tuple)) else [subs]
        for sub in subs or [""]:
            out.append((obj, sub))
    return out


def _kind(sub):
    return sub.split(".")[-1].lstrip("?").rstrip("0123456789")


def _is_sketch(obj):
    return obj.isDerivedFrom("Sketcher::SketchObject")


def _shape(obj, sub):
    return obj.Shape.getElement(sub) if sub else obj.Shape


def _wires_of(shape):
    if shape.Wires:
        wires = list(shape.Wires)
        used = set(e.hashCode() for w in wires for e in w.Edges)
        loose = [e for e in shape.Edges if e.hashCode() not in used]
    else:
        wires, loose = [], list(shape.Edges)
    return wires + [Part.Wire(es) for es in Part.sortEdges(loose)] if loose else wires


def wires(links):
    """The wires the picks make: a sketch or body gives its wires, a face its outer wire, loose edges are
    chained into wires."""
    out, edges = [], []
    for obj, sub in items(links):
        shape = _shape(obj, sub)
        if not sub:
            out.extend(_wires_of(shape))
        elif _kind(sub) == "Face":
            out.append(shape.OuterWire)
        elif _kind(sub) == "Edge":
            edges.append(shape)
    if edges:
        out.extend(Part.Wire(es) for es in Part.sortEdges(edges))
    return out


GROUP_MESSAGE = "Select a continuous group of entities."


def groups(links, sizes=None):
    """The picks of links as profiles: [[(obj, sub)], ...]. sizes (a loft's ProfileGroups) joins runs of picks
    into one SelectionManager group; without them (or when they don't add up) each pick is its own profile."""
    flat = items(links)
    sizes = [int(n) for n in (sizes or [])]
    if not sizes or sum(sizes) != len(flat) or min(sizes) < 1:
        return [[e] for e in flat]
    out, k = [], 0
    for n in sizes:
        out.append(flat[k:k + n])
        k += n
    return out


def group_wire(group):
    """One wire through a SelectionManager group of edges (any order, either way round), and whether it
    closes; ValueError("Select a continuous group of entities.") when they don't make one chain."""
    try:
        edges = [_shape(obj, sub) for obj, sub in group]
        edges = [e.Edges[0] for e in edges if e.Edges]
        if len(edges) != len(group) or len(Part.sortEdges(edges)) != 1:
            raise ValueError(GROUP_MESSAGE)
        wire = Part.Wire(Part.__sortEdges__(edges))
    except Exception:
        raise ValueError(GROUP_MESSAGE)
    return wire, wire.isClosed()


def profiles(links, sizes=None):
    """One profile per pick, in order (Loft): a sketch's wire, a face's outer wire, an edge, a vertex; a
    SelectionManager group (sizes) is one wire through its edges."""
    out = []
    for group in groups(links, sizes):
        if len(group) > 1:
            out.append(group_wire(group)[0])
            continue
        obj, sub = group[0]
        shape = _shape(obj, sub)
        if not sub:
            w = _wires_of(shape)
            if w:
                out.append(w[0])
        elif _kind(sub) == "Face":
            out.append(shape.OuterWire)
        elif _kind(sub) == "Edge":
            out.append(Part.Wire(shape))
        elif _kind(sub) == "Vertex":
            out.append(shape)
    return out


def start_at(wire, point, tol=1e-6):
    """The closed wire rebuilt to start at its vertex nearest point (a Loft connector): the loft joins
    the profiles' start vertices, so this sets which corners line up."""
    if wire is None or isinstance(wire, Part.Vertex) or not getattr(wire, "isClosed", lambda: False)():
        return wire
    try:
        edges = list(wire.OrderedEdges)
        verts = list(wire.OrderedVertexes)
        if len(verts) < 2 or len(edges) != len(verts):
            return wire
        k = min(range(len(verts)), key=lambda i: (verts[i].Point - point).Length)
        if k == 0:
            return wire
        new = Part.Wire(edges[k:] + edges[:k])
        if (new.OrderedVertexes[0].Point - verts[k].Point).Length > max(tol, 1e-4):
            return wire
        return new
    except Exception:
        return wire


def connect(ps, links):
    ""

    points = []
    for obj, sub in items(links):
        try:
            v = _shape(obj, sub)
            if isinstance(v, Part.Vertex):
                points.append(v.Point)
        except Exception:
            continue
    if not points:
        return ps
    out = list(ps)
    taken = set()
    for pt in points:
        best = None
        for i, w in enumerate(out):
            if i in taken or isinstance(w, Part.Vertex):
                continue
            try:
                d = w.distToShape(Part.Vertex(pt))[0]
            except Exception:
                continue
            if best is None or d < best[0]:
                best = (d, i)
        if best is not None and best[0] < 1e-3:
            out[best[1]] = start_at(out[best[1]], pt)
            taken.add(best[1])
    return out


def _edge_points(wire, k, m):
    """m points along edge k of the wire, in the wire's own direction."""
    e = wire.OrderedEdges[k]
    start = wire.OrderedVertexes[k].Point
    pts = e.discretize(Number=m)
    if (pts[0] - start).Length > (pts[-1] - start).Length:
        pts.reverse()
    return pts


def connected_loft(sections, closed=False, m=24):
    """A loft that keeps each profile's start where it is (FreeCAD's makeLoft turns the profiles to the
    least twist, which would undo connectors): edge k of every profile lofts into strip k, a surface
    through the edges' points in order, and the strips are sewn together. None when the profiles do not
    have the same number of edges."""
    ws = [w for w in sections if not isinstance(w, Part.Vertex)]
    if len(ws) != len(sections) or len(ws) < 2:
        return None
    counts = set(len(w.OrderedEdges) for w in ws)
    if len(counts) != 1 or any(len(w.OrderedVertexes) != len(w.OrderedEdges) for w in ws):
        return None
    n = counts.pop()
    rows = ws + ([ws[0]] if closed else [])
    faces = []
    for k in range(n):
        grid = [_edge_points(w, k, m) for w in rows]
        surf = Part.BSplineSurface()
        surf.interpolate(grid)
        faces.append(surf.toShape())
    shell = Part.makeShell(faces)
    try:
        from . import sewtol
        shell = sewtol.sewn(faces, 1e-3)
        shell = shell.Shells[0] if shell.Shells else shell
    except Exception as _fw_err:
        _fw_log("surfacepms.py:250", _fw_err)
    return shell


def _bent(points):
    """An edge through the points: a line when they are in one line, else a curve through them."""
    a, b = points[0], points[-1]
    span = b - a
    if span.Length > 1e-9:
        u = V(span)
        u.normalize()
        if all(((p - a) - u * (p - a).dot(u)).Length < 1e-7 for p in points):
            return Part.LineSegment(a, b).toShape()
    curve = Part.BSplineCurve()
    curve.interpolate(points)
    return curve.toShape()


def centerline_loft(ps, path, n=12, m=24):
    ""



    ws = [w for w in ps if not isinstance(w, Part.Vertex)]
    if len(ws) != len(ps) or len(ws) < 2 or not all(w.isClosed() for w in ws):
        return None
    counts = set(len(w.OrderedEdges) for w in ws)
    if len(counts) != 1 or any(len(w.OrderedVertexes) != len(w.OrderedEdges) for w in ws):
        return None
    pts = path.discretize(Number=400)
    if len(pts) < 3:
        return None
    lengths = [0.0]
    for i in range(1, len(pts)):
        lengths.append(lengths[-1] + (pts[i] - pts[i - 1]).Length)
    total = lengths[-1]
    if total < 1e-9:
        return None

    def at(s):
        """(point, tangent) at the length s along the centerline."""
        s = max(0.0, min(total, s))
        j = max(1, min(len(pts) - 1, next((i for i, x in enumerate(lengths) if x >= s), len(pts) - 1)))
        f = (s - lengths[j - 1]) / max(1e-12, lengths[j] - lengths[j - 1])
        p = pts[j - 1] + (pts[j] - pts[j - 1]) * f
        t = pts[min(len(pts) - 1, j + 1)] - pts[max(0, j - 2)]
        t.normalize()
        return p, t

    def nearest(c):
        k = min(range(len(pts)), key=lambda i: (pts[i] - c).Length)
        return lengths[k]

    places = []
    for w in ws:
        face = Part.Face(w)
        s = nearest(face.CenterOfMass)
        p, t = at(s)
        nrm = V(face.normalAt(0, 0))
        if nrm.dot(t) < 0:
            nrm = -nrm
        turn = App.Rotation(V(0, 0, 1), nrm).inverted()
        local = [[turn.multVec(q - p) for q in _edge_points(w, k, m)] for k in range(len(w.OrderedEdges))]
        places.append((s, local, nrm))
    if any(places[i + 1][0] <= places[i][0] + 1e-6 for i in range(len(places) - 1)):
        return None
    each = max(2, int(n) // (len(ws) - 1))
    rows = [places[0][1]]
    for k in range(len(ws) - 1):
        (s0, la, na), (s1, lb, nb) = places[k], places[k + 1]
        for i in range(1, each):
            f = float(i) / each
            p, t = at(s0 + (s1 - s0) * f)
            # square to the centerline away from the profiles, turning from each profile's own plane
            # near it (a section tipped right beside a profile would bulge the loft past it)
            g = math.sin(math.pi * f)
            way = (na * (1 - f) + nb * f) * (1 - g) + t * g
            if way.Length < 1e-9:
                way = t
            way.normalize()
            turn = App.Rotation(V(0, 0, 1), way)
            rows.append([[p + turn.multVec(a * (1 - f) + b * f) for a, b in zip(ea, eb)] for ea, eb in zip(la, lb)])
        rows.append(lb)
    sections = []
    for j, row in enumerate(rows):
        if j % each == 0:
            sections.append(ws[j // each])
            continue
        try:
            sections.append(Part.Wire([_bent(points) for points in row]))
        except Exception:
            return None
    return Part.makeLoft(sections, False, False, False)


def normal_of(links, ws):
    """The profile's plane normal: a sketch's own, else the plane the wires lie in."""
    for obj, sub in items(links):
        if _is_sketch(obj):
            return obj.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
    plane = Part.Compound(ws).findPlane() if ws else None
    if plane is None:
        return None
    return V(plane.Axis)


def _face_of(obj, sub):
    """The face a pick stands for: a picked face, or a datum or origin plane as a big flat face."""
    if obj.TypeId in PLANES and not sub:
        pl = obj.getGlobalPlacement()
        return Part.Plane(pl.Base, pl.Rotation.multVec(V(0, 0, 1))).toShape(-BIG, BIG, -BIG, BIG)
    shape = _shape(obj, sub)
    if not shape.Faces:
        raise ValueError("Pick a face or plane.")
    return shape.Faces[0]


def line_of(links):
    """(point, direction) of a picked straight edge, a face's normal at its centre, or None."""
    for obj, sub in items(links):
        if not sub and obj.TypeId == "App::Line":       # an origin axis
            pl = obj.getGlobalPlacement()
            return pl.Base, pl.Rotation.multVec(V(1, 0, 0))
        shape = _shape(obj, sub)
        if isinstance(shape, Part.Edge) or (shape.Edges and not shape.Faces and len(shape.Edges) == 1):
            e = shape if isinstance(shape, Part.Edge) else shape.Edges[0]
            if isinstance(e.Curve, (Part.Line, Part.LineSegment)) or e.Curve.TypeId == "Part::GeomLine":
                a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
                return a, (b - a).normalize()
        if shape.Faces:
            f = shape.Faces[0]
            u0, u1, v0, v1 = f.ParameterRange
            return f.CenterOfMass, f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    return None


def _centre(shape):
    """The centre of a profile's edges, by length (a compound of wires has no CenterOfMass)."""
    es = shape.Edges
    total = sum(e.Length for e in es)
    if total < 1e-12:
        return shape.BoundBox.Center
    c = V()
    for e in es:
        c += e.CenterOfMass * (e.Length / total)
    return c


def _sew(faces, tol=1e-6):
    comp = Part.Compound(faces)
    try:
        from . import sewtol
        comp = sewtol.sewn(faces, tol)
    except Exception:
        return comp
    shells = comp.Shells
    return shells[0] if len(shells) == 1 and len(shells[0].Faces) == len(comp.Faces) else comp


def _free_edges(shape):
    """The open edges of shape. A seam (a cylinder's join) is in one face only, yet it is not open:
    the shell's own free-edge check leaves it out (Cap end on a round profile found no closed end).
    Faces that the sewing could not join (a gap wider than its precision, the gaps Knit lists) are not one
    shell: each shell, and each face on its own, gives its open edges."""
    try:
        if shape.ShapeType == "Shell":
            return list(shape.getFreeEdges().Edges)
        out, done = [], set()
        for sh in shape.Shells:
            out.extend(sh.getFreeEdges().Edges)
            done.update(f.hashCode() for f in sh.Faces)
        for f in shape.Faces:
            if f.hashCode() not in done:
                out.extend(Part.Shell([f]).getFreeEdges().Edges)
        return out
    except Exception:
        return [e for e in shape.Edges if len(shape.ancestorsOfType(e, Part.Face)) == 1]


def _touching(shape, ref, tol=1e-4):
    """The faces of shape that touch ref (the profile): what is left on the profile's side after a cut."""
    keep, todo = [], [f for f in shape.Faces]
    near = [f for f in todo if f.distToShape(ref)[0] < tol]
    keep.extend(near)
    rest = [f for f in todo if f not in near]
    grown = True
    while grown and rest:           # and the faces joined to those
        grown = False
        for f in list(rest):
            if any(f.distToShape(k)[0] < tol for k in keep):
                keep.append(f)
                rest.remove(f)
                grown = True
    return keep


def _caps(shell, axis):
    """Flat faces closing each open end of shell (Cap end): free edges grouped by their height on axis."""
    groups = {}
    for es in Part.sortEdges(_free_edges(shell)):
        w = Part.Wire(es)
        if not w.isClosed():
            continue
        key = round(w.CenterOfMass.dot(axis), 3)
        groups.setdefault(key, []).append(w)
    out = []
    for ws in groups.values():
        try:
            out.extend(Part.makeFace(ws, "Part::FaceMakerBullseye").Faces)
        except Exception as _fw_err:
            _fw_log("surfacepms.py:368", _fw_err)
    return out


# --------------------------------------------------------------------------- features
# A surface feature sits beside the Body, its picks inside it: global links, so FreeCAD does not warn
# "Link(s) to object(s) ... go out of the allowed scope" on every recompute
GLOBAL = {"App::PropertyLinkSubList": "App::PropertyLinkSubListGlobal"}


def _prop(obj, kind, name, doc, default=None):
    kind = GLOBAL.get(kind, kind)
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, GROUP, doc)
        if default is not None:
            setattr(obj, name, default)
    elif kind != obj.getTypeIdOfProperty(name) and obj.getTypeIdOfProperty(name) in GLOBAL:
        # a file from before: the same picks, now in a global link
        value = getattr(obj, name)
        obj.removeProperty(name)
        obj.addProperty(kind, name, GROUP, doc)
        setattr(obj, name, value)


def _enum(obj, name, values, doc, default=None):
    if name not in obj.PropertiesList:
        obj.addProperty("App::PropertyEnumeration", name, GROUP, doc)
        setattr(obj, name, list(values))
        setattr(obj, name, default or values[0])
    elif list(obj.getEnumerationsOfProperty(name)) != list(values):
        now = getattr(obj, name)
        setattr(obj, name, list(values))
        setattr(obj, name, now if now in values else default or values[0])


class _Feature:
    NAME = ""

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class SurfaceExtrude(_Feature):
    NAME = "Surface-Extrude"

    def setup(self, obj):
        _prop(obj, "App::PropertyLinkSubList", "Profile", "Sketch, edges or faces extruded (Selected Contours)")
        _enum(obj, "From", EXTRUDE_FROM, "Where the extrusion starts")
        _prop(obj, "App::PropertyLinkSubList", "FromEntity", "The face, plane or vertex the extrusion starts from")
        _prop(obj, "App::PropertyDistance", "FromOffset", "Start offset from the sketch plane", 0.0)
        _prop(obj, "App::PropertyBool", "FromReverse", "Reverse the start offset", False)
        _prop(obj, "App::PropertyLinkSubList", "Direction", "Edge or face giving the direction (else normal to the sketch)")
        _prop(obj, "App::PropertyBool", "Reverse", "Reverse Direction 1", False)
        _enum(obj, "Condition", EXTRUDE_ENDS, "End Condition of Direction 1")
        _prop(obj, "App::PropertyLength", "Depth", "Depth of Direction 1", 10.0)
        _prop(obj, "App::PropertyLinkSubList", "UpTo", "Vertex, face or body Direction 1 goes up to")
        _prop(obj, "App::PropertyLength", "Offset", "Offset Distance from the surface (Direction 1)", 0.0)
        _prop(obj, "App::PropertyBool", "ReverseOffset", "Reverse offset: past the surface (Direction 1)", False)
        _prop(obj, "App::PropertyBool", "TranslateSurface", "Translate surface: the end is the surface moved along the direction (Direction 1)", False)
        _prop(obj, "App::PropertyBool", "Draft", "Draft On/Off (Direction 1)", False)
        _prop(obj, "App::PropertyAngle", "DraftAngle", "Draft angle", 1.0)
        _prop(obj, "App::PropertyBool", "DraftOutward", "Draft outward", False)
        _prop(obj, "App::PropertyBool", "Direction2", "Direction 2 on", False)
        _enum(obj, "Condition2", EXTRUDE_ENDS2, "End Condition of Direction 2")
        _prop(obj, "App::PropertyLength", "Depth2", "Depth of Direction 2", 10.0)
        _prop(obj, "App::PropertyLinkSubList", "UpTo2", "Vertex, face or body Direction 2 goes up to")
        _prop(obj, "App::PropertyLength", "Offset2", "Offset Distance from the surface (Direction 2)", 0.0)
        _prop(obj, "App::PropertyBool", "ReverseOffset2", "Reverse offset: past the surface (Direction 2)", False)
        _prop(obj, "App::PropertyBool", "TranslateSurface2", "Translate surface: the end is the surface moved along the direction (Direction 2)", False)
        _prop(obj, "App::PropertyBool", "CapEnd", "Cap end: close the ends of a closed profile", False)

    def execute(self, obj):
        ws = wires(obj.Profile)
        if not ws:
            raise ValueError("Pick a sketch, edges or faces to extrude.")
        picked = line_of(obj.Direction)
        d = picked[1] if picked else normal_of(obj.Profile, ws)
        if d is None:
            raise ValueError("A straight profile has no plane: pick a Direction of Extrusion.")
        d = V(d).normalize()
        if obj.Reverse:
            d = -d
        ws = self._start(obj, ws, d)
        closed = all(w.isClosed() for w in ws)
        ref = Part.Compound(ws)
        faces = []
        if obj.Condition == "Mid Plane":
            half = obj.Depth.Value / 2
            faces += self._side(obj, ws, ref, d, "Blind", half, None, 0, obj.Draft)
            faces += self._side(obj, ws, ref, -d, "Blind", half, None, 0, obj.Draft)
        else:
            faces += self._side(obj, ws, ref, d, obj.Condition, obj.Depth.Value, obj.UpTo,
                                obj.Offset.Value * (-1 if obj.ReverseOffset else 1), obj.Draft, obj.TranslateSurface)
            if obj.Direction2:
                faces += self._side(obj, ws, ref, -d, obj.Condition2, obj.Depth2.Value, obj.UpTo2,
                                    obj.Offset2.Value * (-1 if obj.ReverseOffset2 else 1), False, obj.TranslateSurface2)
        shell = _sew(faces)
        if obj.CapEnd and closed:
            shell = _sew(shell.Faces + _caps(shell, d))
        obj.Shape = shell

    def _start(self, obj, ws, d):
        """The profile moved to where From starts it: by the offset, to the plane through a vertex (parallel to
        the sketch), or along the direction onto a face or plane (the start takes the face's shape)."""
        if obj.From == "Sketch Plane":
            return ws
        if obj.From == "Offset":
            off = obj.FromOffset.Value * (-1 if obj.FromReverse else 1)
            return [w.translated(d * off) for w in ws] if off else ws
        target = items(obj.FromEntity)
        if not target:
            raise ValueError("Pick the %s the extrusion starts from." % ("vertex" if obj.From == "Vertex" else "face or plane"))
        if obj.From == "Vertex":
            p = _shape(*target[0]).Vertexes[0].Point
            n = normal_of(obj.Profile, ws) or d
            if abs(d.dot(n)) < 1e-9:
                raise ValueError("The direction runs along the sketch plane: pick another direction.")
            t = (p - ws[0].Vertexes[0].Point).dot(n) / d.dot(n)
            return [w.translated(d * t) for w in ws]
        face = _face_of(*target[0])
        if face.Surface.TypeId == "Part::GeomPlane":
            m = V(face.Surface.Axis)
            if abs(d.dot(m)) < 1e-9:
                raise ValueError("The direction runs along the start plane: pick another plane.")
            out = []
            for w in ws:        # each point slides along the direction onto the plane
                t = (face.Surface.Position - w.Vertexes[0].Point).dot(m) / d.dot(m)
                if all(abs((v.Point + d * t - face.Surface.Position).dot(m)) < 1e-7 for v in w.Vertexes):
                    out.append(w.translated(d * t))
                else:
                    out.extend(self._project(face, w, d))
            return out
        return [x for w in ws for x in self._project(face, w, d)]

    def _project(self, face, w, d):
        """w slid along the direction onto face; where the face is met twice, the nearer landing."""
        es = face.makeParallelProjection(w, d).Edges
        if not es:
            raise ValueError("The profile does not land on the start face along the direction.")
        landed = [Part.Wire(g) for g in Part.sortEdges(es)]
        if len(landed) > 1 and w.isClosed():
            landed = [min((x for x in landed if x.isClosed()) or landed, key=lambda x: x.distToShape(w)[0])]
        return landed

    def _side(self, obj, ws, ref, d, condition, depth, upto, offset, draft, translate=False):
        if condition == "Blind":
            return self._sweep(obj, ws, d, depth, draft)
        target = items(upto)
        if not target:
            raise ValueError("Pick the %s for %s." % ("vertex" if condition == "Up To Vertex" else
                                                       "body" if condition == "Up To Body" else "face", condition))
        tobj, tsub = target[0]
        if condition == "Up To Vertex":
            p = _shape(tobj, tsub).Vertexes[0].Point
            length = max((p - v.Point).dot(d) for w in ws for v in w.Vertexes)
            if length <= 1e-7:
                raise ValueError("The vertex is behind the profile: reverse the direction.")
            return self._sweep(obj, ws, d, length, draft)
        if condition == "Up To Body":
            tool = tobj.Shape
        else:
            tool = self._half_space(_face_of(tobj, tsub), ref, d, offset if condition == "Offset From Surface" else 0,
                                    translate)
        reach = max(tool.distToShape(v)[0] for w in ws for v in w.Vertexes)
        length = reach * 4 + max(ref.BoundBox.DiagonalLength, 1) * 4 + 10
        long = Part.Compound(self._sweep(obj, ws, d, length, draft))
        cut = long.cut(tool)
        kept = _touching(cut, ref)
        if not kept:
            raise ValueError("The extrusion does not reach the %s." % ("body" if condition == "Up To Body" else "surface"))
        return kept

    def _half_space(self, face, ref, d, offset, translate=False):
        """The solid beyond the picked surface, seen from the profile: cutting with it stops the extrusion
        at the surface (moved back toward the profile by offset, or past it when offset is less than 0;
        translate moves it along the direction instead of offsetting it)."""
        f = face.Faces[0] if face.Faces else None
        if f is None:
            raise ValueError("Pick a face for the end condition.")
        if offset and translate:
            f = f.translated(-d * offset).Faces[0]
            offset = 0
        if f.Surface.TypeId == "Part::GeomPlane":
            n = V(f.Surface.Axis).normalize()
            if n.dot(d) < 0:
                n = -n
            c = ref.BoundBox.Center
            o = c - n * (c - f.Surface.Position).dot(n)
            big = Part.Plane(o - n * offset, n).toShape(-BIG, BIG, -BIG, BIG)
            return big.extrude(n * BIG * 2)
        if offset:
            moved = [f.makeOffsetShape(s * abs(offset), 1e-6) for s in (1, -1)]
            f = (min if offset > 0 else max)(moved, key=lambda m: m.distToShape(ref)[0])
            f = f.Faces[0]
        return f.extrude(d * BIG)

    def _sweep(self, obj, ws, d, length, draft):
        if not draft:
            return [f for w in ws for f in w.extrude(d * length).Faces]
        sign = 1 if obj.DraftOutward else -1
        grow = sign * length * math.tan(math.radians(obj.DraftAngle.Value))
        faces = []
        for w in ws:
            if not w.isClosed():

                # in its plane (Draft outward takes the other side)
                try:
                    top = w.makeOffset2D(-grow, 0, False, True)
                except Exception:
                    top = _straight_offset(w, d, grow)       # one straight line has no plane of its own
                faces += Part.makeRuledSurface(w, top.translated(d * length)).Faces
                continue
            inner = any(o is not w and Part.Face(o).isInside(w.Vertexes[0].Point, 1e-6, True)
                        for o in ws if o.isClosed())
            top = w.makeOffset2D(-grow if inner else grow, 0, False, False)
            faces += Part.makeLoft([w, top.translated(d * length)], False, True).Faces
        return faces


def _straight_offset(wire, d, grow):
    """An open profile that is one straight line, offset by grow in the plane square to d (the
    extrusion direction), on the side makeOffset2D takes for a bent profile (d x the line)."""
    a, b = wire.OrderedVertexes[0].Point, wire.OrderedVertexes[-1].Point
    t = b - a
    if t.Length < 1e-9 or any(e.Curve.TypeId != "Part::GeomLine" and not isinstance(e.Curve, Part.Line)
                              for e in wire.Edges) or abs(wire.Length - t.Length) > 1e-7:
        raise ValueError("Draft: the open profile is not flat.")
    side = V(d).cross(t)
    if side.Length < 1e-9:
        raise ValueError("Draft: the profile runs along the extrude direction.")
    side.normalize()
    return wire.translated(side * grow)


class SurfaceRevolve(_Feature):
    NAME = "Surface-Revolve"

    def setup(self, obj):
        _prop(obj, "App::PropertyLinkSubList", "Profile", "Sketch, edges or faces revolved (Selected Contours)")
        _prop(obj, "App::PropertyLinkSubList", "Axis", "Axis of Revolution: a line, edge or axis (else the sketch's centerline)")
        _prop(obj, "App::PropertyBool", "Reverse", "Reverse Direction 1", False)
        _enum(obj, "Condition", REVOLVE_ENDS, "Revolve Type of Direction 1")
        _prop(obj, "App::PropertyAngle", "Angle", "Angle of Direction 1", 360.0)
        _prop(obj, "App::PropertyLinkSubList", "UpTo", "Vertex, face or plane Direction 1 goes up to")
        _prop(obj, "App::PropertyLength", "Offset", "Offset Distance from the surface (Direction 1)", 0.0)
        _prop(obj, "App::PropertyBool", "ReverseOffset", "Reverse offset: past the surface (Direction 1)", False)
        _prop(obj, "App::PropertyBool", "Direction2", "Direction 2 on", False)
        _enum(obj, "Condition2", REVOLVE_ENDS2, "Revolve Type of Direction 2")
        _prop(obj, "App::PropertyAngle", "Angle2", "Angle of Direction 2", 360.0)
        _prop(obj, "App::PropertyLinkSubList", "UpTo2", "Vertex, face or plane Direction 2 goes up to")
        _prop(obj, "App::PropertyLength", "Offset2", "Offset Distance from the surface (Direction 2)", 0.0)
        _prop(obj, "App::PropertyBool", "ReverseOffset2", "Reverse offset: past the surface (Direction 2)", False)

    def execute(self, obj):
        ws = wires(obj.Profile)
        if not ws:
            raise ValueError("Pick a sketch, edges or faces to revolve.")
        axis = line_of(obj.Axis) or centerline(obj.Profile)
        if axis is None:
            raise ValueError("Pick the Axis of Revolution: a centerline, line, edge or axis.")
        base, d = axis
        if obj.Reverse:
            d = -d
        ref = Part.Compound(ws)
        if obj.Condition == "Mid-Plane":
            a1 = a2 = obj.Angle.Value / 2
        else:
            a1 = self._angle(obj.Condition, obj.Angle.Value, obj.UpTo, ref, base, d,
                             obj.Offset.Value * (-1 if obj.ReverseOffset else 1))
            a2 = self._angle(obj.Condition2, obj.Angle2.Value, obj.UpTo2, ref, base, -d,
                             obj.Offset2.Value * (-1 if obj.ReverseOffset2 else 1)) if obj.Direction2 else 0
        total = min(a1 + a2, 360.0)
        faces = []
        for w in ws:
            start = w.copy()
            if a2:
                start.rotate(base, d, -a2)
            faces += start.revolve(base, d, total).Faces
        obj.Shape = _sew(faces)

    def _angle(self, condition, angle, upto, ref, base, d, offset=0.0):
        if condition in ("Blind", "Mid-Plane"):
            return angle
        target = items(upto)
        if not target:
            raise ValueError("Pick the %s for %s." % ("vertex" if condition == "Up To Vertex" else "face or plane",
                                                     condition))
        if condition == "Up To Vertex":
            return self._turn(_centre(ref), _shape(*target[0]).Vertexes[0].Point, base, d)
        face = _face_of(*target[0])
        if condition == "Offset From Surface" and offset:
            # the profile's centre stops short of the surface by the offset (past it when reversed)
            hits = [self._hit(m, ref, base, d) for m in self._offsets(face, abs(offset))]
            hits = [a for a in hits if a is not None]
            if not hits:
                raise ValueError("The revolve does not reach the offset surface.")
            return min(hits) if offset > 0 else max(hits)
        a = self._hit(face, ref, base, d)
        if a is None:
            raise ValueError("The revolve does not reach the surface.")
        return a

    def _turn(self, c, p, base, d):
        """The angle about the axis from point c round to point p, 0 to 360."""
        def flat(q):
            r = q - base
            return r - d * r.dot(d)
        u, w = flat(c), flat(p)
        a = math.degrees(math.atan2(d.dot(u.cross(w)), u.dot(w)))
        return a if a > 1e-6 else a + 360.0

    def _hit(self, face, ref, base, d):
        """The first angle at which the profile's centre, going round the axis, meets the face (None if it
        never does)."""
        c = _centre(ref)
        r = c - base
        centre = base + d * r.dot(d)
        radius = (c - centre).Length
        if radius < 1e-9:
            raise ValueError("The profile's centre is on the axis.")
        circle = Part.makeCircle(radius, centre, d)
        points = [v.Point for v in face.section(circle).Vertexes]
        angles = [self._turn(c, p, base, d) for p in points]
        angles = [a for a in angles if 1e-6 < a < 360.0 - 1e-6]
        return min(angles) if angles else None

    def _offsets(self, face, offset):
        if face.Surface.TypeId == "Part::GeomPlane":
            n, o = V(face.Surface.Axis), face.Surface.Position
            return [Part.Plane(o + n * s * offset, n).toShape(-BIG, BIG, -BIG, BIG) for s in (1, -1)]
        return [face.makeOffsetShape(s * offset, 1e-6).Faces[0] for s in (1, -1)]


def centerline(links):
    ""
    for obj, sub in items(links):
        if not _is_sketch(obj):
            continue
        lines = [g for i, g in enumerate(obj.Geometry)
                 if obj.getConstruction(i) and isinstance(g, Part.LineSegment)]
        if len(lines) == 1:
            pl = obj.getGlobalPlacement()
            a, b = pl.multVec(lines[0].StartPoint), pl.multVec(lines[0].EndPoint)
            return a, (b - a).normalize()
    return None


class SurfaceSweep(_Feature):
    NAME = "Surface-Sweep"

    def setup(self, obj):
        _enum(obj, "ProfileType", SWEEP_PROFILES, "Sketch Profile or Circular Profile")
        _prop(obj, "App::PropertyLinkSubList", "Profile", "Profile: a sketch, edges or a face")
        _prop(obj, "App::PropertyLinkSubList", "Path", "Path: a sketch or edges")
        _prop(obj, "App::PropertyLength", "Diameter", "Diameter of the circular profile", 10.0)
        _enum(obj, "Orientation", SWEEP_ORIENTATIONS, "Profile orientation")
        _enum(obj, "Twist", SWEEP_TWISTS, "Profile twist")
        _enum(obj, "TwistUnit", TWIST_UNITS, "Twist control: degrees, radians or turns")
        _prop(obj, "App::PropertyFloat", "TwistValue", "Twist along the path, in TwistUnit", 0.0)
        _prop(obj, "App::PropertyBool", "TwistReverse", "Reverse the twist", False)
        _prop(obj, "App::PropertyLinkSubList", "DirectionVector", "Direction vector: a line, edge, face or plane")
        _prop(obj, "App::PropertyLinkSubList", "Guides", "Guide curves: sketches or edges the profile follows")
        _prop(obj, "App::PropertyBool", "MergeTangent", "Merge tangent faces", True)
        _prop(obj, "App::PropertyBool", "MergeSmooth",
              "Merge smooth faces (Guide Curves): off, the sweep is split where the path or a guide has a corner or joint", True)
        _enum(obj, "StartTangency", SWEEP_TANGENCY, "Start tangency type: Path Tangent turns the profile square to the path")
        _enum(obj, "EndTangency", SWEEP_TANGENCY, "End tangency type: Path Tangent keeps the end square to the path")

    def execute(self, obj):
        paths = wires(obj.Path)
        if not paths:
            raise ValueError("Pick the path.")
        path = paths[0]
        edges = path.OrderedEdges
        first = path.OrderedVertexes[0].Point
        e = edges[0]
        if (e.valueAt(e.FirstParameter) - first).Length < 1e-6:
            tangent = e.tangentAt(e.FirstParameter)
        else:
            tangent = -e.tangentAt(e.LastParameter)
        if obj.ProfileType == "Circular Profile":
            if obj.Diameter.Value <= 0:
                raise ValueError("The diameter must be more than 0.")
            profile = Part.Wire(Part.makeCircle(obj.Diameter.Value / 2, first, tangent))
            normal = tangent
        else:
            ws = wires(obj.Profile)
            if not ws:
                raise ValueError("Pick the profile.")
            profile = ws[0]
            normal = normal_of(obj.Profile, ws) or tangent
        guides = wires(obj.Guides)
        twist = self._twist(obj) if obj.Twist == "Specify Twist Value" else 0.0
        if guides or abs(twist) > 1e-9:
            merge = getattr(obj, "MergeSmooth", True)
            shape = sections_sweep(profile, path, first, V(normal), obj.Orientation == "Keep Normal Constant",
                                   twist, guides, obj.Twist == "Follow Path and 1st Guide Curve",
                                   merge_smooth=merge is None or bool(merge))
        else:
            maker = Part.BRepOffsetAPI.MakePipeShell(path)
            if obj.Orientation == "Keep Normal Constant":
                maker.setTrihedronMode(first, V(normal))
            elif obj.Twist == "Specify Direction Vector":
                picked = line_of(obj.DirectionVector)
                if picked is None:
                    raise ValueError("Pick the direction vector: a line, edge, face or plane.")
                maker.setBiNormalMode(V(picked[1]))
            elif obj.Twist == "Natural":
                maker.setFrenetMode(True)       # the profile turns with the path's own curvature
            elif obj.Twist == "Tangent to Adjacent Faces":
                support = self._path_faces(obj)
                if support is None:
                    raise ValueError("Tangent to Adjacent Faces needs a path made of edges of the part's faces.")
                maker.setSpineSupport(support)  # the profile keeps its angle to the faces along the path
            # Start/End tangency Path Tangent: the profile is turned square to the path where it starts

            square = "Path Tangent" in (obj.StartTangency, obj.EndTangency)
            maker.add(profile, False, square)
            maker.build()
            shape = maker.shape()
        if obj.MergeTangent:
            try:
                shape = shape.removeSplitter()
            except Exception as _fw_err:
                _fw_log("surfacepms.py:784", _fw_err)
        obj.Shape = shape


    def _path_faces(self, obj):
        """The faces the picked path edges lie on (for Tangent to Adjacent Faces), else None."""
        faces = []
        for src, sub in items(obj.Path):
            if _kind(sub) != "Edge":
                return None
            edge = src.Shape.getElement(sub)
            for f in src.Shape.Faces:
                if any(e.isSame(edge) for e in f.Edges) and not any(f.isSame(g) for g in faces):
                    faces.append(f)
        return Part.makeShell(faces) if faces else None

    def _twist(self, obj):
        v = obj.TwistValue * (-1 if obj.TwistReverse else 1)
        return {"Degrees": v, "Radians": math.degrees(v), "Turns": v * 360.0}[obj.TwistUnit]


def _path_samples(path, n):
    """n + 1 (point, tangent) pairs evenly along the path, from its first ordered vertex."""
    edges, at = [], path.OrderedVertexes[0].Point
    for e in path.OrderedEdges:
        forward = (e.valueAt(e.FirstParameter) - at).Length < (e.valueAt(e.LastParameter) - at).Length
        edges.append((e, forward))
        at = e.valueAt(e.LastParameter if forward else e.FirstParameter)
    total = sum(e.Length for e, _ in edges)
    out = []
    for i in range(n + 1):
        s = total * i / n
        for e, forward in edges:
            if s <= e.Length + 1e-9 or e is edges[-1][0]:
                s = min(max(s, 0.0), e.Length)
                u = e.getParameterByLength(s if forward else e.Length - s)
                t = e.tangentAt(u)
                out.append((e.valueAt(u), V(t if forward else -t).normalize()))
                break
            s -= e.Length
    return out


def _perp(t):
    a = V(1, 0, 0) if abs(t.x) < 0.9 else V(0, 1, 0)
    return (a - t * a.dot(t)).normalize()


def _frames(samples, ref):
    """Rotation-minimising frames (r, t x r, t) along the samples (double reflection), r starting from ref."""
    r = ref - samples[0][1] * ref.dot(samples[0][1])
    r = r.normalize() if r.Length > 1e-9 else _perp(samples[0][1])
    out = [r]
    for (x0, t0), (x1, t1) in zip(samples, samples[1:]):
        v1 = x1 - x0
        c1 = v1.dot(v1)
        if c1 < 1e-18:
            out.append(r)
            continue
        rl = r - v1 * (2 / c1 * v1.dot(r))
        tl = t0 - v1 * (2 / c1 * v1.dot(t0))
        v2 = t1 - tl
        c2 = v2.dot(v2)
        r = rl - v2 * (2 / c2 * v2.dot(rl)) if c2 > 1e-18 else rl
        out.append(r)
    return out


def _matrix(cols, move):
    """The 4x4 matrix with these three columns and translation."""
    a, b, c = cols
    return App.Matrix(a.x, b.x, c.x, move.x, a.y, b.y, c.y, move.y, a.z, b.z, c.z, move.z, 0, 0, 0, 1)


def _guide_point(guide, p, t, near):
    """Where the guide crosses the section plane at p (normal t), nearest to the previous one."""
    plane = Part.Plane(p, t).toShape(-BIG, BIG, -BIG, BIG)
    hits = [v.Point for v in guide.section(plane).Vertexes]
    if not hits:
        raise ValueError("A guide curve does not run the length of the path.")
    return min(hits, key=lambda q: (q - near).Length)


def _joints(path, guides, samples):
    ""

    out = set()
    for w in [path] + list(guides):
        edges = w.OrderedEdges
        for a, b in zip(edges, edges[1:]):
            try:
                pa = a.valueAt(a.LastParameter)
                q = b.Vertexes[0].Point if (b.Vertexes[0].Point - pa).Length < (b.Vertexes[-1].Point - pa).Length \
                    else b.Vertexes[-1].Point
            except Exception:
                continue
            k = min(range(len(samples)), key=lambda i: abs((q - samples[i][0]).dot(samples[i][1])) +
                    (0 if w is not path else (q - samples[i][0]).Length))
            if 0 < k < len(samples) - 1:
                out.add(k)
    return sorted(out)


def sections_sweep(profile, path, start, normal, constant, twist, guides, turn=False, count=None, merge_smooth=True):
    """A sweep built as a loft through copies of the profile along the path. Each copy is turned with the path
    (or kept square to normal), twisted by its share of twist, and, with guide curves, stretched in its own
    plane so that the profile's points on the guides stay on them (one guide: turned and scaled; two: a full
    linear map of the section)."""
    curved = any(not isinstance(e.Curve, (Part.Line, Part.LineSegment)) for e in path.Edges)
    n = count or min((40 if curved or guides else 12) + int(abs(twist) / 15), 400)
    samples = _path_samples(path, n)
    if constant:
        samples = [(p, normal) for p, _t in samples]
    t0 = samples[0][1]
    frames = _frames(samples, _perp(t0)) if not constant else [_perp(normal)] * len(samples)
    e1, e2 = frames[0], t0.cross(frames[0])
    p0 = samples[0][0]
    starts = []
    for g in guides[:2]:
        q = min((v.Point for v in g.Vertexes), key=lambda q: profile.distToShape(Part.Vertex(q))[0])
        if profile.distToShape(Part.Vertex(q))[0] > 1e-4:
            raise ValueError("Each guide curve must start on the profile.")
        starts.append(q)
    back = _matrix((e1, e2, t0), V()).inverse()        # world to the first section's frame
    sections, near = [], list(starts)
    for i, ((p, t), r) in enumerate(zip(samples, frames)):
        b1, b2 = r, t.cross(r)
        angle = math.radians(twist) * i / n
        c, s_ = math.cos(angle), math.sin(angle)
        b1, b2 = b1 * c + b2 * s_, b2 * c - b1 * s_
        move = _matrix((b1, b2, t), p) * back
        rigid = True
        if starts:
            local = [back.multVec(q - p0) for q in starts]         # guide starts in the first frame
            target = []
            for k, g in enumerate(guides[:2]):
                near[k] = _guide_point(g, p, t, near[k])
                d = near[k] - p
                target.append(V(d.dot(b1), d.dot(b2), 0))
            m = _plane_map(local, target, turn)
            if m is not None:
                move = _matrix((b1, b2, t), p) * m * back
                rigid = False
        shifted = profile.translated(-p0)
        if not rigid and len(starts) == 1:
            # one guide: a turn and a uniform scale; scaling the shape keeps circles circles and lines lines
            # (transformGeometry makes B-splines, and the loft through them came out about 1% fuller)
            k = math.sqrt(abs(m.A11 * m.A22 - m.A12 * m.A21))
            if k > 1e-12:
                spin = App.Matrix(m.A11 / k, m.A12 / k, 0, 0, m.A21 / k, m.A22 / k, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
                local_shape = shifted.transformed(back)
                local_shape.scale(k, V(0, 0, 0))
                sec = local_shape.transformed(_matrix((b1, b2, t), p) * spin)
                sections.append(sec.Wires[0] if sec.Wires else sec)
                continue
        sec = shifted.transformGeometry(move) if not rigid else shifted.transformed(move)
        sections.append(sec.Wires[0] if sec.Wires else sec)
    cuts = [] if merge_smooth or not guides else _joints(path, guides, samples)
    if not cuts:
        return Part.makeLoft(sections, False, False, False)
    # Merge smooth faces off: one loft per stretch between joints, so the faces split there
    faces, last = [], 0
    for k in cuts + [len(sections) - 1]:
        if k - last >= 1:
            faces += Part.makeLoft(sections[last:k + 1], False, False, False).Faces
        last = k
    shell = Part.makeShell(faces)
    try:
        shell.sewShape()
    except Exception as _fw_err:
        _fw_log("surfacepms.py:954", _fw_err)
    return shell


def _plane_map(local, target, turn=True):
    """The in-plane map (a 4x4 matrix) taking the profile's guide points (local) onto the guides (target). One
    guide scales the section (and turns it with the guide when turn is on); two map it fully."""
    if len(local) == 1:
        a, b = local[0], target[0]
        la, lb = math.hypot(a.x, a.y), math.hypot(b.x, b.y)
        if la < 1e-9:
            return None
        turn = math.atan2(b.y, b.x) - math.atan2(a.y, a.x) if turn else 0.0
        c, s_ = math.cos(turn) * lb / la, math.sin(turn) * lb / la
        return App.Matrix(c, -s_, 0, 0, s_, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    (a, b), (c, d) = local, target
    det = a.x * b.y - b.x * a.y
    if abs(det) < 1e-9 * max(1.0, (a.x * a.x + a.y * a.y + b.x * b.x + b.y * b.y)):
        # the two guides on a line through the centre (either side of a circle): the section is moved,

        za, zb, zc, zd = complex(a.x, a.y), complex(b.x, b.y), complex(c.x, c.y), complex(d.x, d.y)
        if abs(za - zb) < 1e-9:
            raise ValueError("The two guide curves cross the profile at the same point: pick other guides.")
        k = (zc - zd) / (za - zb)
        m = zc - k * za
        return App.Matrix(k.real, -k.imag, 0, m.real, k.imag, k.real, 0, m.imag, 0, 0, 1, 0, 0, 0, 0, 1)
    # A [a b] = [c d]  ->  A = [c d] [a b]^-1
    ia = (b.y / det, -b.x / det, -a.y / det, a.x / det)
    m11 = c.x * ia[0] + d.x * ia[2]
    m12 = c.x * ia[1] + d.x * ia[3]
    m21 = c.y * ia[0] + d.y * ia[2]
    m22 = c.y * ia[1] + d.y * ia[3]
    return App.Matrix(m11, m12, 0, 0, m21, m22, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def merge_tangent_chains(wire, angle=1e-3):
    """The wire with each run of edges that meet tangent (a slot's lines and arcs) made one B-spline
    edge, so a loft through it gives one face per run (Merge tangent faces). Corners stay corners."""
    try:
        edges = list(Part.Wire(wire).OrderedEdges)
    except Exception:
        return wire
    if len(edges) < 2:
        return wire

    def tangent(a, b):
        ta = a.tangentAt(a.LastParameter) if a.Orientation != "Reversed" else -a.tangentAt(a.FirstParameter)
        tb = b.tangentAt(b.FirstParameter) if b.Orientation != "Reversed" else -b.tangentAt(b.LastParameter)
        if ta.Length < 1e-12 or tb.Length < 1e-12:
            return False
        return ta.getAngle(tb) < angle

    smooth = [tangent(edges[i], edges[(i + 1) % len(edges)]) for i in range(len(edges))]
    if not any(smooth):
        return wire
    closed = Part.Wire(edges).isClosed()
    start = 0
    if closed and not all(smooth):
        start = (smooth.index(False) + 1) % len(edges)      # begin a run at a corner
    order = edges[start:] + edges[:start]
    flags = smooth[start:] + smooth[:start]
    runs, run = [], [order[0]]
    for e, joins in zip(order[1:], flags[:-1]):
        if joins:
            run.append(e)
        else:
            runs.append(run)
            run = [e]
    runs.append(run)
    out = []
    for r in runs:
        if len(r) == 1:
            out.append(r[0])
            continue
        try:
            curve = Part.Wire(r).approximate(1e-7, 1e-5, 200, 7)
            out.append(curve.toShape())
        except Exception:
            out.extend(r)
    try:
        merged = Part.Wire(out)
        return merged if merged.isClosed() == closed else wire
    except Exception:
        return wire


def held_closed_ok(a, b, kinds):
    ""


    if any(k not in ("None", "Default", "Tangency To Face", "Curvature To Face", "Normal To Profile",
                     "Direction Vector") for k in kinds):
        return False
    for w in (a, b):
        es = w.OrderedEdges if hasattr(w, "OrderedEdges") else w.Edges
        for e, f in zip(es, es[1:] + es[:1]):
            if len(es) == 1:
                break
            try:
                ta, tb = e.tangentAt(e.LastParameter), f.tangentAt(f.FirstParameter)
                if e.Orientation == "Reversed":
                    ta = e.tangentAt(e.FirstParameter) * -1
                if f.Orientation == "Reversed":
                    tb = f.tangentAt(f.LastParameter) * -1
                if ta.getAngle(tb) > 0.02 and ta.getAngle(tb * -1) > 0.02:
                    return False
            except Exception:
                return False
    return True


def held_points(a, b, m=40):
    """Matching points on two profiles for the held (exact tangency) build: m along an open
    profile, end to end; m round a closed one (no repeat), each from its start vertex (as a loft
    joins closed profiles vertex to vertex), the second run the same way round as the first."""
    if not a.isClosed():
        pa, pb = a.discretize(Number=m), b.discretize(Number=m)
        if (pa[0] - pb[0]).Length + (pa[-1] - pb[-1]).Length > (pa[0] - pb[-1]).Length + (pa[-1] - pb[0]).Length:
            pb = pb[::-1]
        return pa, pb
    pa, pb = a.discretize(Number=m + 1)[:-1], b.discretize(Number=m + 1)[:-1]
    ca, cb = _centre(a), _centre(b)
    back = pb[:1] + pb[1:][::-1]        # the same start (the profile's vertex), the other way round
    cost = lambda run: sum(((pa[i] - ca) - (run[i] - cb)).Length for i in range(m))
    return pa, min((pb, back), key=cost)


def _end_offset(shape, a, b, samples=48):
    """How far the held loft's two end edges stray from the profiles a and b (largest gap)."""
    try:
        face = shape.Faces[0]
        surf = face.Surface
        u0, u1, v0, v1 = face.ParameterRange
        worst = 0.0
        for v, w in ((v0, a), (v1, b)):
            iso = surf.vIso(v)
            for k in range(samples):
                p = iso.value(u0 + (u1 - u0) * (k + 0.5) / samples)
                worst = max(worst, w.distToShape(Part.Vertex(p))[0])
        return worst
    except Exception:
        return 0.0


def held_surface(r0, r1, r2, r3, closed=False):
    """A cubic across two profiles: rows of points r0 (the first profile), r1 and r2 (the way each
    end leaves, pushed off by the handle) and r3 (the second profile), one per profile point. All
    four rows are interpolated with the same parameters, so they share knots and the surface leaves
    each end exactly along its row of handles."""
    pts = list(r0) + ([r0[0]] if closed else [])
    u = [0.0]
    for p, q in zip(pts, pts[1:]):
        u.append(u[-1] + max((q - p).Length, 1e-9))
    u = [x / u[-1] for x in u]
    rows = []
    for row in (r0, r1, r2, r3):
        c = Part.BSplineCurve()
        if closed:
            c.interpolate(Points=list(row), PeriodicFlag=True, Parameters=u)
            c.setNotPeriodic()      # the same curve, clamped at the start point: a face that sews to the caps
        else:
            c.interpolate(Points=list(row), Parameters=u)
        rows.append(c)
    k0 = rows[0]
    poles = [[r.getPole(i + 1) for r in rows] for i in range(k0.NbPoles)]
    surf = Part.BSplineSurface()
    surf.buildFromPolesMultsKnots(poles, k0.getMultiplicities(), [4, 4], k0.getKnots(), [0.0, 1.0],
                                  False, False, k0.Degree, 3)
    return surf.toShape()


class SurfaceLoft(_Feature):
    NAME = "Surface-Loft"

    def __init__(self, obj):
        super().__init__(obj)
        obj.GuideInfluence = "To Next Guide"

    def setup(self, obj):
        _enum(obj, "GuideInfluence", GUIDE_INFLUENCE, "Guide curves influence: how far along the profile each "
              "guide pulls it (to the next guide, sharp corner or edge end, or the whole profile)", "Global")
        _prop(obj, "App::PropertyLinkSubList", "Profiles", "Profiles in order: sketches, edges, faces or a point at an end")
        _prop(obj, "App::PropertyIntegerList", "ProfileGroups", "Picks per profile in order: a number over 1 is a "
              "SelectionManager group of edges lofted as one profile; empty: one profile per pick")
        _prop(obj, "App::PropertyBool", "MergeTangent", "Merge tangent faces", True)
        _prop(obj, "App::PropertyBool", "Close", "Close loft: the last profile joins back to the first", False)
        _prop(obj, "App::PropertyLinkSubList", "Guides", "Guide curves: sketches or edges running across the profiles")
        _prop(obj, "App::PropertyLinkSubList", "Centerline", "Centerline: the loft's sections stay square to it")
        _prop(obj, "App::PropertyInteger", "Sections", "Number of sections the loft is built through along the "
              "centerline", 12)
        _prop(obj, "App::PropertyLinkSubList", "Connectors", "Connectors: a vertex on each profile; the loft joins "
              "them with one edge (which corners line up)")
        _prop(obj, "App::PropertyBool", "MicroTolerance", "Micro tolerance: a finer tolerance for very small geometry", False)
        for end in ("Start", "End"):
            _enum(obj, end + "Constraint", LOFT_CONSTRAINTS, "%s constraint" % end)
            _prop(obj, "App::PropertyLinkSubList", end + "Vector", "%s direction vector: a line, edge, face or plane" % end)
            _prop(obj, "App::PropertyBool", end + "Reverse", "Reverse the %s direction" % end.lower(), False)
            _prop(obj, "App::PropertyAngle", end + "Draft", "Draft angle at the %s" % end.lower(), 0.0)
            _prop(obj, "App::PropertyBool", end + "DraftReverse", "Reverse the %s draft angle" % end.lower(), False)
            _prop(obj, "App::PropertyFloat", end + "Length", "%s tangent length" % end, 1.0)

    def execute(self, obj):
        ps = profiles(obj.Profiles, getattr(obj, "ProfileGroups", None))
        if len(ps) < 2:
            raise ValueError("Pick two profiles at least.")
        ps = connect(ps, getattr(obj, "Connectors", None))
        centre, guides = wires(obj.Centerline), wires(obj.Guides)
        if centre:
            shape = None
            try:
                shape = centerline_loft(ps, centre[0], getattr(obj, "Sections", 12) or 12)
            except Exception as _fw_err:
                _fw_log("surfacepms.py:centerline_loft", _fw_err)
            if shape is None:
                maker = Part.BRepOffsetAPI.MakePipeShell(centre[0])
                for p in ps:
                    maker.add(p, False, False)
                maker.build()
                shape = maker.shape()
        elif guides:
            shape = guided_loft(ps, guides, bool(obj.Close), influence=getattr(obj, "GuideInfluence", "Global"))
        else:
            if obj.MergeTangent:
                ps = [merge_tangent_chains(p) for p in ps]
            shape = self._held_loft(obj, ps)
            if shape is not None:
                if obj.MergeTangent:
                    try:
                        shape = shape.removeSplitter()
                    except Exception as _fw_err:
                        _fw_log("surfacepms.py:1169", _fw_err)
                obj.Shape = shape
                return
            start = self._constraint(obj, "Start", ps[0], ps[1])
            end = self._constraint(obj, "End", ps[-1], ps[-2])
            sections = ps[:1] + ([start] if start else []) + ps[1:-1] + ([end] if end else []) + ps[-1:]
            shape = None
            if getattr(obj, "Connectors", None):
                shape = connected_loft(sections, bool(obj.Close))
            if shape is None:
                shape = Part.makeLoft(sections, False, False, bool(obj.Close))
        if obj.MicroTolerance:
            try:
                shape = shape.copy()
                shape.fixTolerance(1e-7)        # small details keep their own edges
            except Exception as _fw_err:
                _fw_log("surfacepms.py:1185", _fw_err)
        if obj.MergeTangent:
            try:
                shape = shape.removeSplitter()
            except Exception as _fw_err:
                _fw_log("surfacepms.py:1190", _fw_err)
        obj.Shape = shape


    def _face_way(self, obj, end, c, cn):
        """Tangency/Curvature To Face: the way the face beside the end profile carries on past it
        (the profile an edge of a face or surface; with two faces there, the one the loft goes on
        from)."""
        picks = items(obj.Profiles)
        src, sub = picks[0] if end == "Start" else picks[-1]
        if _kind(sub) == "Face":
            f = src.Shape.getElement(sub)
            n = V(f.normalAt(*f.Surface.parameter(f.CenterOfMass)))
            return n if n.dot(cn - c) >= 0 else -n
        if _kind(sub) != "Edge":
            raise ValueError("The %s profile must be an edge of a face for %s." % (end.lower(), getattr(obj, end + "Constraint")))
        from .surfacefeatures import _out_at
        edge = src.Shape.getElement(sub)
        t = (edge.FirstParameter + edge.LastParameter) / 2.0
        ways = []
        for f in src.Shape.Faces:
            if any(e.isSame(edge) for e in f.Edges):
                try:
                    ways.append(V(_out_at(f, edge, t)))
                except Exception as _fw_err:
                    _fw_log("surfacepms.py:1215", _fw_err)
        if not ways:
            raise ValueError("The %s profile is not an edge of a face." % end.lower())
        n = max(ways, key=lambda w: w.dot(cn - c))
        n.normalize()
        return n

    HANDLE = {"Tangency To Face": 0.4, "Curvature To Face": 0.6, "Normal To Profile": 0.4, "Direction Vector": 0.4}

    def _held_loft(self, obj, ps, m=40):
        ""



        if len(ps) != 2 or obj.Close or getattr(obj, "Connectors", None):
            return None
        kinds = [getattr(obj, e + "Constraint") for e in ("Start", "End")]
        if all(k in ("None", "Default") for k in kinds):
            return None
        a, b = ps
        if isinstance(a, Part.Vertex) or isinstance(b, Part.Vertex) or a.isClosed() != b.isClosed():
            return None
        shut = a.isClosed()
        if shut and not held_closed_ok(a, b, kinds):
            return self._held_by_edges(obj, a, b, kinds)
        best = None
        for count in (m, m * 2, m * 4, m * 8):     # finer until the loft's ends lie on the profiles (so it knits)
            shape = self._held_build(obj, a, b, kinds, shut, count)
            off = _end_offset(shape, a, b)
            if best is None or off < best[0]:
                best = (off, shape)
            if off < 1e-6:
                break
        return best[1]

    def _held_by_edges(self, obj, a, b, kinds, n=16):
        """Closed profiles with corners (two squares) and Normal To Profile, a direction vector or To
        Face at an end: one held cubic patch per pair of matching edges, so the loft leaves each
        profile exactly along the constraint and the corners stay corners (the helper section left it
        a few degrees off). None when the profiles' edges do not pair up."""
        if any(k not in ("None", "Default", "Tangency To Face", "Curvature To Face", "Normal To Profile",
                         "Direction Vector") for k in kinds):
            return None
        from .boundarysurface import _edge_runs, _lined_runs
        try:
            ra, rb = _edge_runs(a, n), _edge_runs(b, n)
        except Exception:
            return None
        if len(ra) != len(rb) or len(ra) < 2:
            return None
        rb = _lined_runs(ra, rb)
        ca, cb = _centre(a), _centre(b)
        gap = (cb - ca).Length
        flat = {}
        for end, wire, here, there, kind in (("Start", a, ca, cb, kinds[0]), ("End", b, cb, ca, kinds[1])):
            if kind in ("Normal To Profile", "Direction Vector"):
                whole = wire.discretize(Number=4 * n)
                flat[end] = self._ways(obj, end, kind, whole, here, there)[0]
        faces = []
        for ea, eb in zip(ra, rb):
            rows = []
            for end, pts, other, kind in (("Start", ea, eb, kinds[0]), ("End", eb, ea, kinds[1])):
                if kind in ("None", "Default"):
                    rows.append([p + (q - p) * (1.0 / 3.0) for p, q in zip(pts, other)])
                    continue
                here, there = (ca, cb) if end == "Start" else (cb, ca)
                ways = [flat[end]] * len(pts) if end in flat else self._ways(obj, end, kind, pts, here, there)
                ways = self._drafted(obj, end, kind, ways, pts, here)
                sign = -1.0 if getattr(obj, end + "Reverse") else 1.0
                handle = gap * self.HANDLE.get(kind, 0.4) * max(getattr(obj, end + "Length"), 1e-6)
                rows.append([p + w * (sign * handle) for p, w in zip(pts, ways)])
            faces.append(held_surface(ea, rows[0], rows[1], eb, False).Faces[0])
        shell = Part.Shell(faces)
        try:
            shell.sewShape()
        except Exception as _fw_err:
            _fw_log("surfacepms.py:held_by_edges", _fw_err)
        return shell

    def _held_build(self, obj, a, b, kinds, shut, m):
        pa, pb = held_points(a, b, m)
        ca, cb = _centre(a), _centre(b)
        gap = (cb - ca).Length
        rows1, rows2 = [], []
        for end, pts, other, kind, out in (("Start", pa, pb, kinds[0], rows1), ("End", pb, pa, kinds[1], rows2)):
            if kind in ("None", "Default"):
                out.extend(p + (q - p) * (1.0 / 3.0) for p, q in zip(pts, other))
                continue
            here, there = (ca, cb) if end == "Start" else (cb, ca)
            ways = self._drafted(obj, end, kind, self._ways(obj, end, kind, pts, here, there), pts, here)
            sign = -1.0 if getattr(obj, end + "Reverse") else 1.0
            handle = gap * self.HANDLE.get(kind, 0.4) * max(getattr(obj, end + "Length"), 1e-6)
            out.extend(p + w * (sign * handle) for p, w in zip(pts, ways))
        return held_surface(pa, rows1, rows2, pb, shut)

    def _drafted(self, obj, end, kind, ways, pts, centre):
        """Draft angle (Normal To Profile, Direction Vector): each direction tilted by the angle, away from the
        profile's centre (towards it with Reverse draft), so the loft leaves the profile at exactly that angle."""
        if kind not in ("Normal To Profile", "Direction Vector"):
            return ways
        a = math.radians(getattr(obj, end + "Draft").Value)
        if not a:
            return ways
        if getattr(obj, end + "DraftReverse"):
            a = -a
        out = []
        for w, p in zip(ways, pts):
            r = p - centre
            r = r - w * r.dot(w)
            if r.Length < 1e-9:
                out.append(w)
                continue
            r.normalize()
            v = w * math.cos(a) + r * math.sin(a)
            out.append(v * (1.0 / math.cos(a)))       # the same rise along the direction, plus the draft's spread
        return out

    def _ways(self, obj, end, kind, pts, here, there):
        """The unit direction the loft leaves the profile with, at each of its points."""
        if kind == "Normal To Profile" or kind == "Direction Vector":
            if kind == "Normal To Profile":
                try:
                    plane = Part.Wire([Part.LineSegment(p, q).toShape() for p, q in zip(pts, pts[1:])]).findPlane()
                except Exception:
                    plane = None
                if plane is None:
                    raise ValueError("The %s profile is not flat: use a direction vector." % end.lower())
                n = V(plane.Axis)
            else:
                picked = line_of(getattr(obj, end + "Vector"))
                if picked is None:
                    raise ValueError("Pick the %s direction vector: a line, edge, face or plane." % end.lower())
                n = V(picked[1])
            n.normalize()
            if n.dot(there - here) < 0:
                n = -n
            return [n] * len(pts)
        picks = items(obj.Profiles)
        src, sub = picks[0] if end == "Start" else picks[-1]
        if _kind(sub) == "Face":
            f = src.Shape.getElement(sub)
            out = []
            for p in pts:
                n = V(f.normalAt(*f.Surface.parameter(p)))
                out.append(n if n.dot(there - here) >= 0 else -n)
            return out
        sizes = list(getattr(obj, "ProfileGroups", None) or [])
        group = []
        if sizes:
            k = sizes[0] if end == "Start" else sizes[-1]
            group = picks[:k] if end == "Start" else picks[-k:]
        group = group or [(src, sub)]
        edges = [(o, o.Shape.getElement(s)) for o, s in group if _kind(s) == "Edge"]
        if not edges:
            raise ValueError("The %s profile must be an edge of a face for %s." % (end.lower(), kind))
        from .surfacefeatures import _out_at
        out = []
        for p in pts:
            o, e = min(edges, key=lambda oe: oe[1].distToShape(Part.Vertex(p))[0])
            t = e.Curve.parameter(p)
            t = min(max(t, e.FirstParameter), e.LastParameter)
            cands = []
            for f in o.Shape.Faces:
                if any(g.isSame(e) for g in f.Edges):
                    try:
                        cands.append(V(_out_at(f, e, t)))
                    except Exception as _fw_err:
                        _fw_log("surfacepms.py:1318", _fw_err)
            if not cands:
                raise ValueError("The %s profile is not an edge of a face." % end.lower())
            w = max(cands, key=lambda c: c.dot(there - here))
            w.normalize()
            out.append(w)
        return out

    def _constraint(self, obj, end, p, nxt):
        """A helper section just off the end profile that makes the loft leave it along the constraint's
        direction (Normal To Profile or the picked vector), flared by the draft angle; the tangent length sets
        how far the direction holds."""
        kind = getattr(obj, end + "Constraint")
        if kind in ("None", "Default") or obj.Close:
            return None
        if isinstance(p, Part.Vertex):
            raise ValueError("A point at the %s can't take a constraint." % end.lower())
        c, cn = _centre(p), _centre(nxt)
        if kind == "Normal To Profile":
            plane = p.findPlane()
            if plane is None:
                raise ValueError("The %s profile is not flat: use a direction vector." % end.lower())
            n = V(plane.Axis).normalize()
            if n.dot(cn - c) < 0:
                n = -n
        elif kind in ("Tangency To Face", "Curvature To Face"):
            n = self._face_way(obj, end, c, cn)
        else:
            picked = line_of(getattr(obj, end + "Vector"))
            if picked is None:
                raise ValueError("Pick the %s direction vector: a line, edge, face or plane." % end.lower())
            n = V(picked[1]).normalize()
        if getattr(obj, end + "Reverse"):
            n = -n
        length = getattr(obj, end + "Length")
        if kind == "Curvature To Face":
            length *= 2.0       # the face's direction held further, so the loft keeps bending with it
        if length <= 0:
            return None
        step = (cn - c).Length * 0.2 * length
        helper = p.translated(n * step)
        draft = getattr(obj, end + "Draft").Value
        if draft and p.isClosed():
            grow = step * math.tan(math.radians(draft)) * (-1 if getattr(obj, end + "DraftReverse") else 1)
            helper = helper.makeOffset2D(grow, 2, False, False)   # corners stay corners, so the edges still pair up
        return helper


def _resample(wire, start, m):
    """m points along the wire; a closed wire's list starts at start (the point nearest the guide)."""
    if not wire.isClosed():
        return wire.discretize(Number=m)
    pts = wire.discretize(Number=m + 1)[:-1]
    i = min(range(len(pts)), key=lambda k: (pts[k] - start).Length)
    pts = pts[i:] + pts[:i]
    pts[0] = start
    return pts


def _winding(pts, c, t):
    return sum((a - c).cross(b - c).dot(t) for a, b in zip(pts, pts[1:] + pts[:1]))


def _interp(pts, closed):
    bs = Part.BSplineCurve()
    bs.interpolate(pts, PeriodicFlag=closed)
    return Part.Wire(bs.toShape())


def _stops(profile, pts, marks, influence):
    """Indexes of pts where a guide's pull ends: the other guides, the profile's sharp corners or its edge ends."""
    if influence == "To Next Guide":
        return set(marks)
    found = set()
    edges = profile.Edges if hasattr(profile, "Edges") else []
    for v in profile.Vertexes:
        if influence == "To Next Sharp":
            touching = [e for e in edges if any(v.isSame(x) for x in e.Vertexes)]
            if len(touching) == 2:
                try:
                    t = [e.tangentAt(e.Curve.parameter(v.Point)).normalize() for e in touching]
                    if abs(t[0].dot(t[1])) > math.cos(math.radians(10)):
                        continue        # smooth join: not a sharp corner
                except Exception as _fw_err:
                    _fw_log("surfacepms.py:1402", _fw_err)
        found.add(min(range(len(pts)), key=lambda k: (pts[k] - v.Point).Length))
    return found


def _weights(n, marks, stops, closed):
    """How much of the guides' pull each of n points takes: 1 at a guide, falling to 0 at the next stop
    each way along the profile (1 all the way when there is no stop that way)."""
    w = [0.0] * n
    for g in marks:
        w[g] = 1.0
        for step in (1, -1):
            path, stop = [], None
            for d in range(1, n):
                j = g + step * d
                if not closed and not 0 <= j < n:
                    break
                path.append(j % n)
                if j % n in stops and j % n != g:
                    stop = d
                    break
            for d, idx in enumerate(path, 1):
                w[idx] = max(w[idx], 1.0 if stop is None else 1.0 - d / float(stop))
    return w


def guided_loft(ps, guides, close=False, per=12, m=48, influence="Global"):
    """A loft held to guide curves (see _guided_loft). OCC's loft can fail when the resampled points land
    exactly on a profile's corners (a square with a guide at an edge's middle, 48 points: "BRep_API: command
    not done"): it is tried again with a few other point counts before giving up (features/166)."""
    error = None
    for count in (m, m + 1, m + 3, 2 * m + 1):
        try:
            return _guided_loft(ps, guides, close, per, count, influence)
        except ValueError:
            raise
        except Exception as e:
            error = e
    raise error


def _pieces(wire, hits):
    """A closed profile as pieces [(edge, u0, u1)] in order round the loop from hits[0], split where each
    guide crosses it, or None when that cannot be done (an open or self-touching profile)."""
    if not wire.isClosed():
        return None
    edges = Part.Wire(wire.Edges).OrderedEdges if not isinstance(wire, Part.Wire) else wire.OrderedEdges
    loop = []
    here = None
    for e in edges:
        a, b = e.valueAt(e.FirstParameter), e.valueAt(e.LastParameter)
        if here is None:
            nxt = edges[1] if len(edges) > 1 else e
            ends = [nxt.valueAt(nxt.FirstParameter), nxt.valueAt(nxt.LastParameter)]
            forward = min((b - q).Length for q in ends) <= min((a - q).Length for q in ends)
        else:
            forward = (a - here).Length <= (b - here).Length
        u0, u1 = (e.FirstParameter, e.LastParameter) if forward else (e.LastParameter, e.FirstParameter)
        loop.append((e, u0, u1))
        here = e.valueAt(u1)
    # split every piece at the hits on it
    for h in hits:
        for i, (e, u0, u1) in enumerate(loop):
            if e.distToShape(Part.Vertex(h))[0] > 1e-6:
                continue
            u = e.Curve.parameter(h)
            lo, hi = min(u0, u1), max(u0, u1)
            if not (lo - 1e-9 <= u <= hi + 1e-9):
                continue
            if (e.valueAt(u0) - h).Length < 1e-6 or (e.valueAt(u1) - h).Length < 1e-6:
                break           # on a corner already
            loop[i:i + 1] = [(e, u0, u), (e, u, u1)]
            break
        else:
            return None
    start = min(range(len(loop)), key=lambda i: (loop[i][0].valueAt(loop[i][1]) - hits[0]).Length)
    if (loop[start][0].valueAt(loop[start][1]) - hits[0]).Length > 1e-6:
        return None
    # start at the beginning of the profile edge the first guide crosses (its pieces stay together)
    size = len(loop)
    for _step in range(size):
        prev = (start - 1) % size
        if not _same_edge(loop[prev], loop[start]):
            break
        start = prev
    return loop[start:] + loop[:start]


def _same_edge(a, b):
    """Two pieces of one profile edge that meet (a ends where b starts)."""
    return a[0].isSame(b[0]) and abs(a[2] - b[1]) < 1e-9


def _reversed_pieces(loop, hit):
    out = [(e, u1, u0) for e, u0, u1 in reversed(loop)]
    start = min(range(len(out)), key=lambda i: (out[i][0].valueAt(out[i][1]) - hit).Length)
    for _step in range(len(out)):
        prev = (start - 1) % len(out)
        if not _same_edge(out[prev], out[start]):
            break
        start = prev
    return out[start:] + out[:start]


def _groups(loop):
    """[[piece index, ...]]: the pieces of each profile edge, in order."""
    out = []
    for i, pc in enumerate(loop):
        if out and _same_edge(loop[out[-1][-1]], pc):
            out[-1].append(i)
        else:
            out.append([i])
    return out


def _piece_points(piece, q):
    e, u0, u1 = piece
    if abs(u1 - u0) < 1e-12:
        return [e.valueAt(u0)] * q
    lo, hi = min(u0, u1), max(u0, u1)
    pts = e.Curve.toShape(lo, hi).discretize(Number=q)
    if (pts[0] - e.valueAt(u0)).Length > (pts[-1] - e.valueAt(u0)).Length:
        pts = pts[::-1]
    pts[0], pts[-1] = e.valueAt(u0), e.valueAt(u1)
    return pts


def _piece_edge(piece):
    e, u0, u1 = piece
    lo, hi = min(u0, u1), max(u0, u1)
    return e.Curve.toShape(lo, hi)


def _straight(piece):
    return type(piece[0].Curve).__name__ in ("Line", "LineSegment")


def _guided_loft_pieces(ps, guides, close, per, m, influence="Global"):
    """_guided_loft keeping each profile's edges: corresponding edges of the profiles (split where the guides
    cross them) are blended and mapped piece by piece, so the sections keep the profile's corners and straight
    sides, and the loft has one face per edge, its edges along the guides. One closed BSpline per section
    rounded a square's corners into a wavy 76-pole face that no Shell could offset (Engine Cover, 11-20)."""
    centres = [_centre(p) for p in ps]
    run = centres[-1] - centres[0]
    run = run.normalize() if run.Length > 1e-9 else V(0, 0, 1)
    loops = []
    for p in ps:
        hits = []
        for g in guides:
            d, pairs, _i = g.distToShape(p)
            if d > 1e-3:
                raise ValueError("Each guide curve must cross every profile.")
            hits.append(pairs[0][1])
        wire = p.Wires[0] if hasattr(p, "Wires") and len(p.Wires) == 1 else None
        loop = _pieces(wire, hits) if wire is not None else None
        if loop is None:
            return None
        loops.append((loop, hits))
    n = len(loops[0][0])
    if any(len(l) != n for l, _h in loops):
        return None
    # the same winding as the first profile
    first = [l[1] for l in loops[0][0]]

    def winding(loop, c):
        pts = [e.valueAt(u0) for e, u0, _u1 in loop]
        mids = [e.valueAt((u0 + u1) / 2.0) for e, u0, u1 in loop]
        ring = [q for pair in zip(pts, mids) for q in pair]
        return _winding(ring, c, run)
    w0 = winding(loops[0][0], centres[0])
    for k in range(1, len(loops)):
        if winding(loops[k][0], centres[k]) * w0 < 0:
            loops[k] = (_reversed_pieces(loops[k][0], loops[k][1][0]), loops[k][1])
    groups = _groups(loops[0][0])
    if any(_groups(l) != groups for l, _h in loops):
        return None
    # guide marks: the piece starting at each guide's hit
    marks = []
    for j, h in enumerate(loops[0][1]):
        idx = min(range(n), key=lambda i: (loops[0][0][i][0].valueAt(loops[0][0][i][1]) - h).Length)
        marks.append(idx)
    qs = [max(4, max(int(math.ceil(m * _piece_edge(l[0][i]).Length / max(1e-9, sum(_piece_edge(x).Length for x in l[0]))))
                     for l in loops) + 1) for i in range(n)]
    samples = [[_piece_points(l[0][i], qs[i]) for i in range(n)] for l in loops]
    straight = [all(_straight(l[0][i]) for l in loops) for i in range(n)]
    weights = None
    if influence != "Global":
        # the guides' pull fades to the next guide / sharp corner / edge end, round the loop
        flat, start = [], []
        for pc in samples[0]:
            start.append(len(flat))
            flat.extend(pc[:-1])
        flat_marks = [start[idx] for idx in marks]
        wflat = _weights(len(flat), flat_marks, _stops(ps[0], flat, flat_marks, influence), True)
        weights = []
        for j, pc in enumerate(samples[0]):
            row = [wflat[start[j] + k] for k in range(len(pc) - 1)]
            row.append(wflat[start[(j + 1) % n]])
            weights.append(row)
    def whole(loop):
        """The profile again, an edge per profile edge (the guides' split points are not corners)."""
        out = []
        for g in groups:
            e, u0, u1 = loop[g[0]][0], loop[g[0]][1], loop[g[-1]][2]
            out.append(_piece_edge((e, u0, u1)))
        return Part.Wire(out)
    gstraight = [all(straight[i] for i in g) for g in groups]
    sections = [whole(loops[0][0])]
    near = [None] * len(marks)
    for i in range(len(ps) - 1):
        a, b, ca, cb = samples[i], samples[i + 1], centres[i], centres[i + 1]
        t = (cb - ca).normalize()
        e1 = _perp(t)
        e2 = t.cross(e1)
        for k in range(1, per):
            f = k / per
            c = ca * (1 - f) + cb * f
            pieces = [[c + (pa - ca) * (1 - f) + (pb - cb) * f for pa, pb in zip(pa_, pb_)] for pa_, pb_ in zip(a, b)]
            local, target = [], []
            for j, idx in enumerate(marks):
                q = pieces[idx][0]
                start = near[j] if near[j] is not None else q
                near[j] = _guide_point(guides[j], c, t, start)
                v, w = q - c, near[j] - c
                local.append(V(v.dot(e1), v.dot(e2), 0))
                target.append(V(w.dot(e1), w.dot(e2), 0))
            mat = _plane_map(local, target, True)
            if mat is not None:
                def moved(q):
                    r = q - c
                    x = mat.multVec(V(r.dot(e1), r.dot(e2), 0))
                    return c + e1 * x.x + e2 * x.y + t * r.dot(t)
                if weights is None:
                    pieces = [[moved(q) for q in pc] for pc in pieces]
                else:
                    pieces = [[q + (moved(q) - q) * w for q, w in zip(pc, wr)] for pc, wr in zip(pieces, weights)]
            for j in range(1, n):
                pieces[j][0] = pieces[j - 1][-1]       # the very same corner point
            pieces[0][0] = pieces[-1][-1]
            edges = []
            for gi, g in enumerate(groups):
                pc = pieces[g[0]][:]
                for j in g[1:]:
                    pc += pieces[j][1:]
                if gstraight[gi] and len(g) == 1:
                    edges.append(Part.LineSegment(pc[0], pc[-1]).toShape())
                else:
                    bs = Part.BSplineCurve()
                    bs.interpolate(pc)
                    edges.append(bs.toShape())
            sections.append(Part.Wire(edges))
        sections.append(whole(loops[i + 1][0]))
    return Part.makeLoft(sections, False, False, close)


def _guided_loft(ps, guides, close=False, per=12, m=48, influence="Global"):
    ""


    if any(isinstance(p, Part.Vertex) for p in ps):
        raise ValueError("Guide curves need profiles at both ends, not points.")
    if all(p.isClosed() for p in ps) and all(len(p.Edges) > 1 for p in ps):
        try:
            skin = _guided_loft_pieces(ps, guides, close, per, m, influence)
            if skin is not None and not skin.isNull() and skin.isValid() and skin.Faces:
                return skin
        except ValueError:
            raise
        except Exception as _fw_err:
            _fw_log("surfacepms.py:guided pieces", _fw_err)
    closed = all(p.isClosed() for p in ps)
    centres = [_centre(p) for p in ps]
    run = centres[-1] - centres[0]
    run = run.normalize() if run.Length > 1e-9 else V(0, 0, 1)
    pts_list = []
    for p, c in zip(ps, centres):
        hit = guides[0].distToShape(p)[1][0][1]
        if guides[0].distToShape(p)[0] > 1e-3:
            raise ValueError("Each guide curve must cross every profile.")
        pts = _resample(p, hit, m)
        if closed and pts_list and _winding(pts, c, run) * _winding(pts_list[0], centres[0], run) < 0:
            pts = pts[:1] + pts[1:][::-1]
        pts_list.append(pts)
    marks = [0]
    if len(guides) > 1:
        a = pts_list[0]
        marks.append(min(range(len(a)), key=lambda k: guides[1].distToShape(Part.Vertex(a[k]))[0]))
    weights = None if influence == "Global" else \
        _weights(len(pts_list[0]), marks, _stops(ps[0], pts_list[0], marks, influence), closed)
    sections = [ps[0]]
    near = [None] * len(marks)
    for i in range(len(ps) - 1):
        a, b, ca, cb = pts_list[i], pts_list[i + 1], centres[i], centres[i + 1]
        t = (cb - ca).normalize()
        e1 = _perp(t)
        e2 = t.cross(e1)
        for k in range(1, per):
            f = k / per
            c = ca * (1 - f) + cb * f
            pts = [c + (pa - ca) * (1 - f) + (pb - cb) * f for pa, pb in zip(a, b)]
            local, target = [], []
            for j, idx in enumerate(marks):
                start = near[j] if near[j] is not None else pts[idx]
                near[j] = _guide_point(guides[j], c, t, start)
                v, w = pts[idx] - c, near[j] - c
                local.append(V(v.dot(e1), v.dot(e2), 0))
                target.append(V(w.dot(e1), w.dot(e2), 0))
            mat = _plane_map(local, target, True)
            if mat is not None:
                out = []
                for q in pts:
                    r = q - c
                    x = mat.multVec(V(r.dot(e1), r.dot(e2), 0))
                    out.append(c + e1 * x.x + e2 * x.y + t * r.dot(t))
                if weights is not None:
                    out = [q + (o - q) * wt for q, o, wt in zip(pts, out, weights)]
                pts = out
            sections.append(_interp(pts, closed))
        sections.append(ps[i + 1])
    return Part.makeLoft(sections, False, False, close)


class SurfaceKnit(_Feature):
    NAME = "Surface-Knit"

    def setup(self, obj):
        _prop(obj, "App::PropertyLinkSubList", "Surfaces", "Surfaces and faces to knit")
        _prop(obj, "App::PropertyBool", "CreateSolid", "Create solid when the knit closes", False)
        _prop(obj, "App::PropertyBool", "MergeEntities", "Merge entities: faces on the same surface become one", True)
        _prop(obj, "App::PropertyBool", "GapControl", "Gap Control: knit across gaps up to the tolerance", True)
        _prop(obj, "App::PropertyLength", "Tolerance", "Knitting tolerance", 0.0025)
        _prop(obj, "App::PropertyInteger", "Gaps", "Open edges left after knitting", 0)
        obj.setEditorMode("Gaps", 1)
        _prop(obj, "App::PropertyLength", "GapMin", "Show gaps in range: smallest", 0.0025)
        _prop(obj, "App::PropertyLength", "GapMax", "Show gaps in range: largest", 0.1)
        _prop(obj, "App::PropertyStringList", "GapList", "The gaps in range between open edges (size, edges)")
        obj.setEditorMode("GapList", 1)
        _prop(obj, "App::PropertyStringList", "GapKeys", "Where each listed gap is (its two edges' middles)")
        obj.setEditorMode("GapKeys", 1)
        _prop(obj, "App::PropertyStringList", "GapsKnit", "The gaps (by GapKeys) to knit across")

    def execute(self, obj):
        faces = []
        for o, sub in items(obj.Surfaces):
            picked = _shape(o, sub)
            if sub and sub.startswith("Face") and not o.Shape.Solids:
                picked = o.Shape
            for f in picked.Faces:
                # each face is knit once: a surface picked twice, or one a Fill Surface with Merge result
                # already took in (the fill's body holds its own copy of the surface around it), would
                # put a face twice in the shell; that solid crosses itself and every later cut goes
                # straight through it (Car Surface: the wheel arches cut nothing)
                if not any(_same_face(f, g) for g in faces):
                    faces.append(f)
        if not faces:
            raise ValueError("Pick the surfaces to knit.")
        shape = _sew(faces, 1e-4)
        if obj.GapControl:
            # FreeCAD's sewing does not close gaps wider than its own precision, so the gaps up to the knitting
            # tolerance, and the ones ticked in the list, are knit across with a strip
            tol, lo, hi = obj.Tolerance.Value, obj.GapMin.Value, obj.GapMax.Value
            ticked = [float(k.split("|")[0]) for k in obj.GapsKnit if "|" in k]       # knit even when out of range
            gaps = _gaps(shape, 0.0, max([hi, tol] + ticked) + 1e-6)
            shown = [g for g in gaps if g[0] > tol and lo - 1e-9 <= g[0] <= hi + 1e-9]
            listed = ["%.4f mm: %s" % (size, name) for size, _a, _b, name in shown]
            keys = [_gap_key(a, b, size) for size, a, b, _n in shown]
            if list(obj.GapList) != listed or list(obj.GapKeys) != keys:
                obj.GapList, obj.GapKeys = listed, keys
            bridges = [_bridge(a, b) for size, a, b, _n in gaps if size <= tol or _gap_key(a, b, size) in obj.GapsKnit]
            if bridges:
                shape = _sew(shape.Faces + bridges, 1e-4)
        elif obj.GapList:
            obj.GapList, obj.GapKeys = [], []
        if obj.CreateSolid and shape.ShapeType == "Shell" and shape.isClosed():
            solid = Part.Solid(shape)
            if solid.Volume < 0:
                solid.reverse()
            shape = solid
        if obj.MergeEntities:
            try:
                shape = shape.removeSplitter()
            except Exception as _fw_err:
                _fw_log("surfacepms.py:1558", _fw_err)
        obj.Gaps = len(_free_edges(shape)) if shape.ShapeType != "Solid" else 0
        obj.Shape = shape


def _same_face(a, b):
    """The same face, or a copy of it lying on it (same surface kind, area, middle and corners)."""
    if a.isSame(b):
        return True
    try:
        if type(a.Surface) is not type(b.Surface) or abs(a.Area - b.Area) > 1e-6 * max(a.Area, 1.0):
            return False
        if a.CenterOfMass.distanceToPoint(b.CenterOfMass) > 1e-5 or len(a.Vertexes) != len(b.Vertexes):
            return False
        return all(any(v.Point.distanceToPoint(w.Point) < 1e-5 for w in b.Vertexes) for v in a.Vertexes)
    except Exception:
        return False


def _gaps(shape, lo, hi):
    ""

    free = _free_edges(shape)
    index = {e.hashCode(): i for i, e in enumerate(shape.Edges, 1)}
    out = []
    for i, a in enumerate(free):
        for b in free[i + 1:]:
            if a.distToShape(b)[0] > hi:
                continue
            short, other = (a, b) if a.Length <= b.Length else (b, a)       # the gap along the shorter edge
            size = max(other.distToShape(Part.Vertex(p))[0] for p in short.discretize(Number=7))
            if lo - 1e-9 <= size <= hi + 1e-9 and size > 1e-7:
                out.append((size, a, b, "Edge%d / Edge%d" % (index.get(a.hashCode(), 0), index.get(b.hashCode(), 0))))
    return sorted(out, key=lambda g: g[0])


def _gap_key(a, b, size=None):
    """A gap's name that stays put while the tolerance or range change: its size and its edges' middles."""
    mid = sorted("%.3f,%.3f,%.3f" % tuple(e.valueAt((e.FirstParameter + e.LastParameter) / 2)) for e in (a, b))
    if size is None:
        short, other = (a, b) if a.Length <= b.Length else (b, a)
        size = max(other.distToShape(Part.Vertex(p))[0] for p in short.discretize(Number=7))
    return "%.4f|%s" % (size, " ".join(mid))


def _bridge(a, b):
    """A strip of surface across a gap, from edge a to edge b (b turned to run the same way)."""
    pa, qa = a.valueAt(a.FirstParameter), a.valueAt(a.LastParameter)
    pb, qb = b.valueAt(b.FirstParameter), b.valueAt(b.LastParameter)
    if (pa - pb).Length + (qa - qb).Length > (pa - qb).Length + (qa - pb).Length:
        c = b.Curve.toBSpline(b.FirstParameter, b.LastParameter)
        c.reverse()
        b = c.toShape()
    return Part.makeRuledSurface(a, b).Faces[0]


class SurfaceOffset(_Feature):
    NAME = "Surface-Offset"

    def setup(self, obj):
        _prop(obj, "App::PropertyLinkSubList", "Faces", "Surfaces or faces to offset")
        _prop(obj, "App::PropertyDistance", "Distance", "Offset distance", 10.0)
        _prop(obj, "App::PropertyBool", "Flip", "Flip offset direction", False)
        _prop(obj, "App::PropertyBool", "SkipFailed", "Create offset surface without failed faces", False)
        _prop(obj, "App::PropertyInteger", "FailedFaces", "Faces that could not be offset (left out)", 0)

    def execute(self, obj):
        faces = []
        for o, sub in items(obj.Faces):
            faces.extend(_shape(o, sub).Faces)
        if not faces:
            raise ValueError("Pick the surfaces or faces to offset.")
        shell = _sew([f.copy() for f in faces])
        dist = obj.Distance.Value * (-1 if obj.Flip else 1)
        obj.FailedFaces = 0
        if abs(dist) < 1e-9:
            obj.Shape = shell
            return
        # oriented as in the sewn shell, so each face's own offset goes the shell's way
        own = list(shell.Faces) if len(shell.Faces) == len(faces) else [f.copy() for f in faces]
        failed = [i for i, f in enumerate(own) if not offset_ok(f, dist)]
        if not failed:
            obj.Shape = _offset_parts(shell, dist)
            return
        if not getattr(obj, "SkipFailed", False):
            raise ValueError("%d face%s cannot be offset by this distance (smaller curvature radius than the "
                             "offset). Tick Create offset surface without failed faces to leave %s out."
                             % (len(failed), "" if len(failed) == 1 else "s", "it" if len(failed) == 1 else "them"))
        good = [f for i, f in enumerate(own) if i not in failed]
        if not good:
            raise ValueError("No face can be offset by this distance.")
        obj.FailedFaces = len(failed)
        obj.Shape = _offset_parts(_sew([f.copy() for f in good]), dist)


def _offset_parts(shape, dist):
    ""



    shells = list(shape.Shells)
    parts = shells + [f for f in shape.Faces if not any(f.isSame(g) for s in shells for g in s.Faces)]
    out = []
    for part in parts:
        got = None
        try:
            got = part.makeOffsetShape(dist, 1e-6, False, False, 0, 0, False)
            if got.isNull() or not got.isValid() or len(got.Faces) < len(part.Faces):
                got = None
        except Exception as _fw_err:
            _fw_log("surfacepms.py:offset_parts", _fw_err)
        if got is None:
            got = _sew([f.makeOffsetShape(dist, 1e-6).Faces[0] for f in part.Faces])
        out.append(got)
    return out[0] if len(out) == 1 else Part.makeCompound(out)


def offset_ok(face, dist):
    """True when the face alone offsets by dist to a valid face (a fillet of radius under the
    offset collapses: OpenCascade either refuses it or, offsetting a whole shell, drops it)."""
    try:
        out = face.makeOffsetShape(dist, 1e-6)
    except Exception:
        return False
    return not out.isNull() and out.isValid() and len(out.Faces) == 1 and out.Area > 1e-9


class SurfaceRuled(_Feature):
    ""

    NAME = "Ruled Surface"

    def setup(self, obj):
        _enum(obj, "Type", RULED_TYPES, "Type of ruled surface")
        _prop(obj, "App::PropertyLinkSubList", "Edges", "Model edges the surface runs from (Edge Selection)")
        _prop(obj, "App::PropertyLength", "Distance", "Distance: the width of the surface", 10.0)
        _prop(obj, "App::PropertyBool", "AlternateSide", "Alternate Side: the other way from the edges", False)
        _prop(obj, "App::PropertyBool", "AlternateFace", "Alternate Face: measure from the other face at each edge", False)
        _prop(obj, "App::PropertyLinkSubList", "Vector", "Reference Vector: an edge, axis or face normal")
        _prop(obj, "App::PropertyAngle", "Angle", "Angle to the reference vector (Tapered to Vector)", 10.0)
        _prop(obj, "App::PropertyBool", "TrimKnit", "Trim and knit the surfaces of neighbouring edges", True)
        _prop(obj, "App::PropertyBool", "Connecting", "Connecting surface: fill the corner between neighbouring strips", True)

    def execute(self, obj):
        picks = [(o, sub) for o, sub in items(obj.Edges) if sub]
        if not picks:
            raise ValueError("Pick the edges the ruled surface runs from.")
        vec = None
        if obj.Type in RULED_VECTOR:
            line = line_of(obj.Vector)
            if line is None:
                raise ValueError("Pick the Reference Vector: an edge, axis or face.")
            vec = V(line[1]).normalize()
        faces = []
        for o, sub in picks:
            edge = o.Shape.getElement(sub)
            beside = o.Shape.ancestorsOfType(edge, Part.Face)
            face = None
            if beside:
                face = beside[1] if obj.AlternateFace and len(beside) > 1 else beside[0]
            if face is None and obj.Type in RULED_TYPES[:2]:
                raise ValueError("%s needs an edge of a face." % obj.Type)
            faces.append((edge, self._strip(obj, edge, face, vec)))
        strips = [s_ for _e, s_ in faces]
        extra = []
        for i, (ea, sa) in enumerate(faces):
            for j, (eb, sb) in enumerate(faces):
                if j <= i:
                    continue
                shared = [v.Point for v in ea.Vertexes if any((v.Point - w.Point).Length < 1e-6 for w in eb.Vertexes)]
                if not shared:
                    continue
                if self._crosses(sa, sb, shared[0]):
                    if obj.TrimKnit:        # where the strips run into each other, each stops at the other
                        strips[i] = self._trim(strips[i], sb, ea)
                        strips[j] = self._trim(strips[j], sa, eb)
                elif obj.Connecting:
                    extra += self._connect(sa, sb, shared[0])
        all_faces = [f for s_ in strips for f in s_.Faces] + extra
        shape = _sew(all_faces) if obj.TrimKnit and len(faces) > 1 else Part.Compound(all_faces)
        obj.Shape = shape

    def _radial(self, strip, at):
        """The far end of the strip's side edge at vertex at (None if it has none there)."""
        for e in strip.Edges:
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            if (a - at).Length < 1e-6 and (b - at).Length > 1e-6:
                return b
            if (b - at).Length < 1e-6 and (a - at).Length > 1e-6:
                return a
        return None

    def _crosses(self, sa, sb, at):
        """True where the two strips run into each other past their shared corner (an inside corner)."""
        try:
            common = sa.section(sb)
        except Exception:
            return False
        return any((v.Point - at).Length > 1e-4 for v in common.Vertexes)

    def _trim(self, strip, other, edge):
        """The part of strip that runs along its edge, cut where the other strip crosses it."""
        try:
            pieces = strip.generalFuse([other])[0]
        except Exception:
            return strip
        mine = [f for f in pieces.Faces if strip.distToShape(Part.Vertex(f.CenterOfMass))[0] < 1e-6]
        keep = [f for f in mine if any(e.Length > 1e-6 and edge.distToShape(Part.Vertex(e.CenterOfMass))[0] < 1e-6
                                       for e in f.Edges)]
        return Part.Compound(keep) if keep else strip

    def _connect(self, sa, sb, at):
        """A flat corner piece from the shared vertex across to the far ends of the two strips' side edges."""
        fa, fb = self._radial(sa, at), self._radial(sb, at)
        if fa is None or fb is None or (fa - fb).Length < 1e-6:
            return []
        return [Part.Face(Part.makePolygon([at, fa, fb, at]))]

    def _strip(self, obj, edge, face, vec):
        width = obj.Distance.Value
        if width <= 0:
            raise ValueError("The distance must be more than 0.")
        sign = -1 if obj.AlternateSide else 1
        n = max(12, min(60, int(edge.Length / 2) + 2))
        if isinstance(edge.Curve, (Part.Line, Part.LineSegment)) or edge.Curve.TypeId == "Part::GeomLine":
            n = 2
        params = [edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * i / (n - 1) for i in range(n)]
        points, ends = [], []
        for t in params:
            p = edge.valueAt(t)
            d = self._direction(obj.Type, edge, t, p, face, vec, obj.Angle.Value) * sign
            points.append(p)
            ends.append(p + d * width)
        first = ends[0] - points[0]
        if all((e - q - first).Length < 1e-7 for e, q in zip(ends, points)):
            return edge.extrude(first)          # one direction all along: an exact extrusion
        if (points[0] - points[-1]).Length < 1e-7:
            # a closed edge (a loft's round end): the far curve cannot start and end on one point, so the
            # strip is made in two halves and knit
            t0, t1 = edge.FirstParameter, edge.LastParameter
            tm = (t0 + t1) / 2.0
            halves = [Part.Edge(edge.Curve, a, b) for a, b in ((t0, tm), (tm, t1))]
            return _sew([f for h in halves for f in self._strip(obj, h, face, vec).Faces])
        far = Part.BSplineCurve()
        far.interpolate(ends)
        return Part.makeRuledSurface(edge, Part.Edge(far))

    def _direction(self, kind, edge, t, p, face, vec, angle):
        tangent = edge.tangentAt(t)
        if kind == "Sweep":
            return vec
        if kind == "Perpendicular to Vector":
            d = vec.cross(tangent)
            if d.Length < 1e-9:
                raise ValueError("The reference vector runs along the edge.")
            return d.normalize()
        if kind == "Tapered to Vector":
            r = App.Rotation(tangent, angle)
            return r.multVec(vec).normalize()
        u, v = face.Surface.parameter(p)
        normal = face.normalAt(u, v)
        if kind == "Normal to Surface":
            return normal.normalize()
        d = tangent.cross(normal).normalize()       # in the face's tangent plane, square to the edge
        probe = p + d * 1e-3
        if face.isInside(probe, 1e-6, True):
            d = -d                                  # out from the face, not back over it
        return d


FEATURES = {cls.__name__: cls for cls in (SurfaceExtrude, SurfaceRevolve, SurfaceSweep, SurfaceLoft,
                                          SurfaceKnit, SurfaceOffset, SurfaceRuled)}


def _waiting_execute(run):
    """Empty picks while the PM is open: no error, the PM waits (pickwait)."""
    def execute(self, obj):
        from . import pickwait
        try:
            run(self, obj)
        except Exception as error:
            if not pickwait.waits(obj, error):
                raise
            obj.Shape = Part.Shape()
            return
        pickwait.done(obj)
    execute._fw_wait = True
    return execute


for _cls in FEATURES.values():
    if not getattr(_cls.execute, "_fw_wait", False):
        _cls.execute = _waiting_execute(_cls.execute)
ICONS = {"SurfaceRuled": "Part_RuledSurface", "SurfaceExtrude": "Part_Extrude", "SurfaceRevolve": "Part_Revolve", "SurfaceSweep": "Part_Sweep",
         "SurfaceLoft": "Part_Loft", "SurfaceKnit": "Part_Shapebuilder", "SurfaceOffset": "Part_Offset"}
# the links whose whole sketches the feature uses up: hidden on OK and shown under it in the tree
CONSUMED = {"SurfaceExtrude": ("Profile",), "SurfaceRevolve": ("Profile",), "SurfaceSweep": ("Profile", "Path"),
            "SurfaceLoft": ("Profiles",), "SurfaceKnit": ("Surfaces",), "SurfaceOffset": (), "SurfaceRuled": ()}


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
                _fw_log("surfacepms.py:1850", _fw_err)
    return None


class View:
    def __init__(self, vobj):
        self.kind = type(vobj.Object.Proxy).__name__
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def onChanged(self, vobj, prop):
        # a reopened file: FreeCAD restores the view properties (and calls this), not attach()
        if getattr(self, "Object", None) is None:
            try:
                self.Object = vobj.Object
            except Exception as _fw_err:
                _fw_log("surfacepms.py:1868", _fw_err)

    def _kind(self):
        kind = getattr(self, "kind", "")
        if not kind:
            obj = _view_owner(self)
            kind = type(getattr(obj, "Proxy", None)).__name__ if obj is not None else ""
            if kind in ICONS:
                self.kind = kind
        return kind

    def getIcon(self):
        name = ICONS.get(self._kind(), "Part_Feature")
        try:
            import PartGui  # noqa: F401  (the Part icons are in its resources, under tools/)
            from PySide import QtGui
            if not QtGui.QIcon(":/icons/tools/%s.svg" % name).isNull():
                return ":/icons/tools/%s.svg" % name
        except ImportError:
            pass
        return ":/icons/%s.svg" % name

    def claimChildren(self):
        obj = _view_owner(self)
        if obj is None:
            return []
        out = []
        for prop in CONSUMED.get(type(obj.Proxy).__name__, ()):
            for o, sub in items(getattr(obj, prop, None)):
                if not sub and _is_sketch(o) and o not in out:
                    out.append(o)
        return out

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + obj.Label)
        try:
            Gui.Control.showDialog(PANELS[type(obj.Proxy).__name__](obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return getattr(self, "kind", None)

    def loads(self, state):
        self.kind = state


# --------------------------------------------------------------------------- PropertyManagers
_LAST = None
ACTIVE_STYLE = "QListWidget { background: #d6ecff; }"
IDLE_STYLE = "QListWidget { background: palette(base); }"


def _fits(kinds, obj, sub):
    k = _kind(sub) if sub else ""
    if "Sketch" in kinds and _is_sketch(obj):
        return True
    if "Body" in kinds and not sub:
        return True
    if "Body" in kinds and k == "Face" and not _is_sketch(obj):
        return True
    if "Line" in kinds and k == "Edge":
        e = _shape(obj, sub)
        return e.Curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment")
    if "Line" in kinds and obj.TypeId in ("PartDesign::Line", "App::Line"):
        return True
    if "Plane" in kinds and obj.TypeId in PLANES and not sub:
        return True
    return bool(sub) and k in kinds


def _entry(kinds, obj, sub):
    """What a pick goes in a box as: a sketch as the whole sketch where the box takes sketches, a face as
    its whole body where the box takes bodies."""
    if "Sketch" in kinds and _is_sketch(obj):
        return obj, ""
    if "Body" in kinds and not ("Face" in kinds and sub):
        return obj, ""
    if obj.TypeId in ("PartDesign::Line", "App::Line") + PLANES:
        return obj, ""
    return obj, sub


def _name(obj, sub):
    if not sub:
        return obj.Label
    name = sub.split(".")[-1].lstrip("?")
    kind = _kind(sub)
    return "%s<%s>@%s" % (kind, name[len(kind):], obj.Label)


class Panel:
    ""

    TITLE = ""
    KIND = ""

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj, self.new, self.busy = obj, new, True
        self.saved = {p: getattr(obj, p) for p in obj.PropertiesList
                      if obj.getGroupOfProperty(p) == GROUP and p != "Gaps"}
        self.boxes, self.order, self.pages, self.fields = {}, [], [], {}
        self.active = None
        self.note = None
        self.build()
        for p in self.pages:
            # boxes have a fixed height: without a stretch at the foot a page shares its spare height out

            p.layout().addStretch(1)
            # and its list boxes (vertically Expanding) must not make the whole group grow into the spare

            p.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        first = self.pages[0]
        first.setProperty("swstyle_pm_title", self.TITLE)
        first.setProperty("swstyle_pm_icon", ICONS[self.KIND])
        self.note = QtWidgets.QLabel("")
        self.note.setObjectName("SWSurfNote")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #c00000;")
        self.note.hide()
        first.layout().insertWidget(0, self.note)
        self.form = self.pages
        self.activate(next((p for p in self.order if not getattr(obj, p)), self.order[0]))
        self.busy = False
        self.sync()
        Gui.Selection.addObserver(self)

    # -- building
    def page(self, title, checkable=None):
        w = QtWidgets.QWidget()
        w.setWindowTitle(title)
        w.setObjectName("SWSurfPage" + title.replace(" ", ""))
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        if checkable:
            box = QtWidgets.QCheckBox(title)
            box.setObjectName("SWSurf" + checkable)
            box.setChecked(bool(getattr(self.obj, checkable)))
            box.toggled.connect(lambda on, p=checkable: self.set(p, on))
            self.fields[checkable] = box
            lay.addWidget(box)
        self.pages.append(w)
        return lay

    def box(self, lay, prop, tip, kinds, single=False, height=70):
        lst = QtWidgets.QListWidget()
        lst.setObjectName("SWSurf" + prop)
        lst.setToolTip(tip)
        lst.setMaximumHeight(height)
        lst.installEventFilter(self._filter_for(prop))
        lst.kinds, lst.single = tuple(kinds), single
        from . import pmboxes           # right-click Clear Selections / Delete act on this box
        pmboxes.bind(lst, lambda row, p=prop: self._remove_row(p, row), lambda p=prop: self.clear_box(p))
        lay.addWidget(lst)
        self.boxes[prop] = lst
        self.order.append(prop)
        return lst

    def _filter_for(self, prop):
        panel = self

        class Filter(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                t = event.type()
                if t in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
                    panel.activate(prop)
                elif t == QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
                    panel.remove_current(prop)
                    return True
                return False
        f = Filter()
        self.__dict__.setdefault("_filters", []).append(f)
        return f

    def combo(self, lay, prop, values, tip):
        c = QtWidgets.QComboBox()
        c.setObjectName("SWSurf" + prop)
        c.setToolTip(tip)
        c.addItems(list(values))
        c.setCurrentText(getattr(self.obj, prop))
        c.currentTextChanged.connect(lambda text, p=prop: self.set(p, text))
        lay.addWidget(c)
        self.fields[prop] = c
        return c

    def number(self, lay, prop, tip, suffix=" mm", lo=0.0, hi=1e6, decimals=2, step=1.0):
        s = QtWidgets.QDoubleSpinBox()
        s.setObjectName("SWSurf" + prop)
        s.setToolTip(tip)
        s.setRange(lo, hi)
        s.setDecimals(decimals)
        s.setSingleStep(step)
        s.setSuffix(suffix)
        value = getattr(self.obj, prop)
        s.setValue(getattr(value, "Value", value))
        s.valueChanged.connect(lambda v, p=prop: self.set(p, v))
        lay.addWidget(s)
        self.fields[prop] = s
        return s

    def check(self, lay, prop, text, tip=""):
        c = QtWidgets.QCheckBox(text)
        c.setObjectName("SWSurf" + prop)
        c.setToolTip(tip or text)
        c.setChecked(bool(getattr(self.obj, prop)))
        c.toggled.connect(lambda on, p=prop: self.set(p, on))
        lay.addWidget(c)
        self.fields[prop] = c
        return c

    def flip(self, prop, tip):
        b = QtWidgets.QToolButton()
        b.setObjectName("SWSurf" + prop)
        from . import pmvalues
        b.setIcon(pmvalues.reverse_icon())
        b.setToolTip(tip)
        b.setCheckable(True)
        b.setChecked(bool(getattr(self.obj, prop)))
        b.toggled.connect(lambda on, p=prop: self.set(p, on))
        self.fields[prop] = b
        return b

    def row(self, lay, *widgets):
        r = QtWidgets.QHBoxLayout()
        for w in widgets:
            r.addWidget(w, 1 if isinstance(w, (QtWidgets.QDoubleSpinBox, QtWidgets.QComboBox)) else 0)
        lay.addLayout(r)
        return r

    # -- state
    def set(self, prop, value):
        if self.busy:
            return
        setattr(self.obj, prop, value)
        self.sync()
        self.rebuild()

    def sync(self):
        """Fill the boxes from the properties; subclasses also show/hide fields that depend on others."""
        before = {p for p, lst in self.boxes.items() if not lst.isHidden()}
        self.update_fields()
        for prop, lst in self.boxes.items():
            now = items(getattr(self.obj, prop))
            keep = [(o, sub) for o, sub in now if _fits(lst.kinds, o, sub)]
            if keep != now:         # a choice changed what the box takes: what no longer fits drops out
                self._store(prop, keep)
                if not keep:
                    before.discard(prop)        # and the emptied box is the one to fill
            lst.clear()
            for o, sub in keep:
                lst.addItem(_name(o, sub))
        shown = [p for p in self.order if p not in before and not self.boxes[p].isHidden() and not getattr(self.obj, p)]
        if shown:
            self.activate(shown[0])
        elif self.active in self.boxes and self.boxes[self.active].isHidden():
            self.activate(next(p for p in self.order if not self.boxes[p].isHidden()))

    def update_fields(self):
        pass

    def activate(self, prop):
        self.active = prop
        for p, lst in self.boxes.items():
            pmboxes.mark(lst, p == prop)

    def rebuild(self):
        doc = self.obj.Document
        if doc.Recomputing:
            QtCore.QTimer.singleShot(50, self.rebuild)
            return
        self.obj.touch()
        doc.recompute()
        self.show_state()
        if getattr(self, "curv", None) is not None:
            self.curv.refresh()

    def show_state(self, on_ok=False):
        bad = "Invalid" in self.obj.State or "Error" in self.obj.State
        message = ""
        if bad:
            try:
                message = self.obj.getStatusString()
            except Exception:
                message = "The surface cannot be made with these settings."
            if not on_ok and message.startswith("Pick "):

                # line above the Axis of Revolution box left a blank band, look audit AA1); OK says it
                message = ""
        else:
            from . import pickwait
            message = pickwait.message(self.obj)
        if self.note is not None:
            self.note.setText(message)
            self.note.setVisible(bool(message))
        return not bad

    # -- picks
    def addSelection(self, doc, name, sub, point):
        QtCore.QTimer.singleShot(0, lambda: self.picked(doc, name, sub))

    def picked(self, doc_name, name, sub):
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken
        lst = self.boxes.get(self.active)
        if lst is None or not shiboken.isValid(lst):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("surfacepms.py:2179", _fw_err)
            return
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("surfacepms.py:2184", _fw_err)
        doc = App.getDocument(doc_name)
        obj = doc.getObject(name) if doc else None
        if obj is None or obj is self.obj:
            return
        self.take(obj, sub)

    def take(self, obj, sub):
        """A pick goes in the active box when that box takes it, else in the first box that does."""
        for prop in [self.active] + [p for p in self.order if p != self.active and not self.boxes[p].isHidden()]:
            lst = self.boxes[prop]
            if _fits(lst.kinds, obj, sub):
                self.toggle(prop, *_entry(lst.kinds, obj, sub))
                return True
        return False

    def toggle(self, prop, obj, sub):
        lst = self.boxes[prop]
        now = items(getattr(self.obj, prop))
        if (obj, sub) in now:
            now.remove((obj, sub))
        elif lst.single:
            now = [(obj, sub)]
        else:
            now.append((obj, sub))
        self._store(prop, now)
        if lst.single and now and prop == self.active:
            nxt = next((p for p in self.order if p != prop and not getattr(self.obj, p)
                        and not self.boxes[p].isHidden()), None)
            if nxt:
                self.activate(nxt)
        self.sync()
        self.rebuild()

    def _store(self, prop, entries):
        setattr(self.obj, prop, [(o, [s]) for o, s in entries])

    def _remove_row(self, prop, row):
        now = items(getattr(self.obj, prop))
        if 0 <= row < len(now):
            self.toggle(prop, *now[row])

    def clear_box(self, prop):
        if items(getattr(self.obj, prop)):
            self._store(prop, [])
            self.sync()
            self.rebuild()

    def remove_current(self, prop):
        lst = self.boxes[prop]
        row = lst.currentRow()
        now = items(getattr(self.obj, prop))
        if 0 <= row < len(now):
            self.toggle(prop, *now[row])

    def move(self, prop, step):
        lst = self.boxes[prop]
        row = lst.currentRow()
        now = items(getattr(self.obj, prop))
        to = row + step
        if 0 <= row < len(now) and 0 <= to < len(now):
            now[row], now[to] = now[to], now[row]
            self._store(prop, now)
            self.sync()
            lst.setCurrentRow(to)
            self.rebuild()

    # -- OK / Cancel
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("surfacepms.py:2259", _fw_err)
        if getattr(self, "curv", None) is not None:
            self.curv.close()
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("surfacepms.py:2267", _fw_err)

    def accept(self):
        self.rebuild()
        if not self.show_state(on_ok=True) or self.obj.Shape.isNull():
            if not self.note.text():
                self.note.setText("Pick what the surface is made from.")
            self.note.show()
            return False
        try:
            self.obj.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("surfacepms.py:2279", _fw_err)
        for prop in CONSUMED.get(self.KIND, ()):
            for o, sub in items(getattr(self.obj, prop)):

                if (not sub or self.KIND == "SurfaceKnit") and o.ViewObject is not None:
                    o.ViewObject.Visibility = False     # the sketch or surface is used up by the feature
        if self.KIND == "SurfaceKnit" and getattr(self.obj, "CreateSolid", False):
            solid_into_body(self.obj)
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        name = self.obj.Name
        self._close()
        doc.abortTransaction()
        try:
            App.closeActiveTransaction(True)
        except Exception as _fw_err:
            _fw_log("surfacepms.py:2298", _fw_err)
        if self.new and doc.getObject(name) is not None:
            doc.removeObject(name)
        elif doc.getObject(name) is not None:
            for p, v in self.saved.items():     # an edit puts its values back even when the undo step closed
                try:
                    setattr(self.obj, p, v)
                except Exception as _fw_err:
                    _fw_log("surfacepms.py:2306", _fw_err)
        doc.recompute()
        return True


class ExtrudePanel(Panel):
    TITLE = "Surface-Extrude"
    KIND = "SurfaceExtrude"

    def build(self):
        lay = self.page("From")
        self.combo(lay, "From", EXTRUDE_FROM, "Start condition")
        self.box(lay, "FromEntity", "The face, plane or vertex the extrusion starts from", ("Face", "Plane"),
                 single=True, height=26)
        holder = QtWidgets.QVBoxLayout()
        self.row(lay, self.flip("FromReverse", "Reverse Direction"),
                 self.number(holder, "FromOffset", "Offset from the sketch plane"))
        lay = self.page("Direction 1")
        self.row(lay, self.flip("Reverse", "Reverse Direction"),
                 self._combo_only("Condition", EXTRUDE_ENDS, "End Condition"))
        self.box(lay, "Direction", "Direction of Extrusion: an edge or face (optional)", ("Line", "Face"), single=True,
                 height=26)
        self.box(lay, "UpTo", "The vertex, face or body the extrusion goes up to", ("Vertex", "Face", "Body"),
                 single=True, height=26)
        self.number(lay, "Depth", "Depth")
        self.number(lay, "Offset", "Offset Distance")
        self.check(lay, "ReverseOffset", "Reverse offset")
        self.check(lay, "TranslateSurface", "Translate surface")
        # Boss-Extrude's draft row (look audit AA1): the Draft On/Off button at the left, the angle beside it,
        # Draft outward under it
        holder = QtWidgets.QVBoxLayout()
        draft = self.flip("Draft", "Draft On/Off")
        from . import icons
        pic = icons.family("FEATURES_DRAFT")
        if pic.isNull():
            draft.setText("Draft")
        else:
            draft.setIcon(pic)
        r = self.row(lay, draft, self.number(holder, "DraftAngle", "Draft Angle", suffix="°", hi=89.0))
        r.setAlignment(draft, QtCore.Qt.AlignLeft)
        self.check(lay, "DraftOutward", "Draft outward")
        self.check(lay, "CapEnd", "Cap end", "Closes the ends of a closed profile")
        lay = self.page("Direction 2", checkable="Direction2")
        self.combo(lay, "Condition2", EXTRUDE_ENDS2, "End Condition")
        self.box(lay, "UpTo2", "The vertex, face or body Direction 2 goes up to", ("Vertex", "Face", "Body"),
                 single=True, height=26)
        self.number(lay, "Depth2", "Depth")
        self.number(lay, "Offset2", "Offset Distance")
        self.check(lay, "ReverseOffset2", "Reverse offset")
        self.check(lay, "TranslateSurface2", "Translate surface")
        lay = self.page("Selected Contours")
        self.box(lay, "Profile", "Sketch, edges or faces to extrude", ("Sketch", "Edge", "Face"), height=90)
        self.order.remove("Profile")
        self.order.insert(0, "Profile")

    def _combo_only(self, prop, values, tip):
        holder = QtWidgets.QVBoxLayout()
        c = self.combo(holder, prop, values, tip)
        return c

    def update_fields(self):
        o, f = self.obj, self.fields
        up = o.Condition in ("Up To Vertex", "Up To Surface", "Offset From Surface", "Up To Body")
        self.boxes["UpTo"].setVisible(up)
        self.boxes["UpTo"].kinds = _upto_kinds(o.Condition)
        f["Depth"].setVisible(o.Condition in ("Blind", "Mid Plane"))
        for name in ("Offset", "ReverseOffset", "TranslateSurface"):
            f[name].setVisible(o.Condition == "Offset From Surface")
        f["FromOffset"].setVisible(o.From == "Offset")
        f["FromReverse"].setVisible(o.From == "Offset")
        self.boxes["FromEntity"].setVisible(o.From in ("Surface/Face/Plane", "Vertex"))
        self.boxes["FromEntity"].kinds = ("Vertex",) if o.From == "Vertex" else ("Face", "Plane")
        f["DraftAngle"].setVisible(o.Draft)
        f["DraftOutward"].setVisible(o.Draft)
        closed = bool(o.Profile) and all(w.isClosed() for w in _safe(wires, o.Profile))
        f["Draft"].setEnabled(True)
        f["CapEnd"].setVisible(closed or o.CapEnd)     # only a closed profile can be capped (no greyed box)
        on2 = o.Direction2 and o.Condition != "Mid Plane"
        f["Direction2"].setVisible(o.Condition != "Mid Plane")
        for w in (f["Condition2"], f["Depth2"], f["Offset2"], f["ReverseOffset2"], f["TranslateSurface2"],
                  self.boxes["UpTo2"]):
            w.setVisible(on2)
        if on2:
            self.boxes["UpTo2"].setVisible(o.Condition2 != "Blind")
            self.boxes["UpTo2"].kinds = _upto_kinds(o.Condition2)
            f["Depth2"].setVisible(o.Condition2 == "Blind")
            for name in ("Offset2", "ReverseOffset2", "TranslateSurface2"):
                f[name].setVisible(o.Condition2 == "Offset From Surface")


def _upto_kinds(condition):
    return {"Up To Vertex": ("Vertex",), "Up To Body": ("Body",)}.get(condition, ("Face", "Plane"))


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as _fw_err:
        _fw_log("surfacepms.py:2402", _fw_err)
        return []


class RevolvePanel(Panel):
    TITLE = "Surface-Revolve"
    KIND = "SurfaceRevolve"

    def build(self):
        lay = self.page("Axis of Revolution")
        self.box(lay, "Axis", "Axis of Revolution: a centerline, line, edge or axis", ("Line",), single=True, height=26)
        lay = self.page("Direction1")
        c = QtWidgets.QVBoxLayout()
        self.row(lay, self.flip("Reverse", "Reverse Direction"), self.combo(c, "Condition", REVOLVE_ENDS, "Revolve Type"))
        self.box(lay, "UpTo", "The vertex, face or plane the revolve goes up to", ("Vertex",), single=True, height=26)
        self.number(lay, "Angle", "Angle", suffix="°", hi=360.0)
        self.number(lay, "Offset", "Offset Distance")
        self.check(lay, "ReverseOffset", "Reverse offset")
        lay = self.page("Direction2", checkable="Direction2")
        self.combo(lay, "Condition2", REVOLVE_ENDS2, "Revolve Type")
        self.box(lay, "UpTo2", "The vertex, face or plane Direction 2 goes up to", ("Vertex",), single=True, height=26)
        self.number(lay, "Angle2", "Angle", suffix="°", hi=360.0)
        self.number(lay, "Offset2", "Offset Distance")
        self.check(lay, "ReverseOffset2", "Reverse offset")
        lay = self.page("Selected Contours")
        self.box(lay, "Profile", "Sketch, edges or faces to revolve", ("Sketch", "Edge", "Face"), height=90)
        self.order.remove("Profile")
        self.order.insert(0, "Profile")

    def update_fields(self):
        o, f = self.obj, self.fields
        self.boxes["UpTo"].setVisible(o.Condition not in ("Blind", "Mid-Plane"))
        self.boxes["UpTo"].kinds = _upto_kinds(o.Condition)
        f["Angle"].setVisible(o.Condition in ("Blind", "Mid-Plane"))
        f["Offset"].setVisible(o.Condition == "Offset From Surface")
        f["ReverseOffset"].setVisible(o.Condition == "Offset From Surface")
        f["Direction2"].setVisible(o.Condition != "Mid-Plane")
        on2 = o.Direction2 and o.Condition != "Mid-Plane"
        f["Condition2"].setVisible(on2)
        self.boxes["UpTo2"].setVisible(on2 and o.Condition2 != "Blind")
        self.boxes["UpTo2"].kinds = _upto_kinds(o.Condition2)
        f["Angle2"].setVisible(on2 and o.Condition2 == "Blind")
        f["Offset2"].setVisible(on2 and o.Condition2 == "Offset From Surface")
        f["ReverseOffset2"].setVisible(on2 and o.Condition2 == "Offset From Surface")


class SweepPanel(Panel):
    TITLE = "Surface-Sweep"
    KIND = "SurfaceSweep"

    def build(self):
        lay = self.page("Profile and Path")
        kinds = QtWidgets.QWidget()        # its own parent, so the two radios are exclusive only together
        kl = QtWidgets.QVBoxLayout(kinds)
        kl.setContentsMargins(0, 0, 0, 0)
        self.radios = {}
        for name in SWEEP_PROFILES:
            r = QtWidgets.QRadioButton(name)
            r.setObjectName("SWSurf" + name.replace(" ", ""))
            r.setChecked(self.obj.ProfileType == name)
            r.toggled.connect(lambda on, n=name: on and self.set("ProfileType", n))
            self.radios[name] = r
            kl.addWidget(r)
        lay.addWidget(kinds)
        self.box(lay, "Profile", "Profile: a sketch, edges or a face", ("Sketch", "Edge", "Face"), single=True,
                 height=26)
        self.box(lay, "Path", "Path: a sketch or edges", ("Sketch", "Edge"), height=50)
        self.number(lay, "Diameter", "Diameter")
        lay = self.page("Guide Curves")
        self.box(lay, "Guides", "Guide curves: sketches or edges, each starting on the profile", ("Sketch", "Edge"),
                 height=60)
        up, down = QtWidgets.QPushButton("Move Up"), QtWidgets.QPushButton("Move Down")
        up.setObjectName("SWSurfGuideUp")
        down.setObjectName("SWSurfGuideDown")
        up.clicked.connect(lambda: self.move("Guides", -1))
        down.clicked.connect(lambda: self.move("Guides", 1))
        self.row(lay, up, down)
        self.check(lay, "MergeSmooth", "Merge smooth faces",
                   "Off: the sweep is split into faces where the path or a guide curve has a corner or joint")
        lay = self.page("Options")
        lay.addWidget(QtWidgets.QLabel("Profile orientation:"))
        self.combo(lay, "Orientation", SWEEP_ORIENTATIONS, "Profile orientation")
        lay.addWidget(QtWidgets.QLabel("Profile twist:"))
        self.combo(lay, "Twist", SWEEP_TWISTS, "Profile twist")
        self.box(lay, "DirectionVector", "Direction vector: a line, edge, face or plane", ("Line", "Face", "Plane"),
                 single=True, height=26)
        self.combo(lay, "TwistUnit", TWIST_UNITS, "Twist control")
        holder = QtWidgets.QVBoxLayout()
        self.row(lay, self.flip("TwistReverse", "Reverse Direction"),
                 self.number(holder, "TwistValue", "Direction 1: the twist along the path", suffix="", lo=-1e6,
                             decimals=3, step=15.0))
        self.check(lay, "MergeTangent", "Merge tangent faces")
        self._preview(lay)

    def _tangency(self):
        lay = self.page("Start and End Tangency")
        for end in ("Start", "End"):
            lay.addWidget(QtWidgets.QLabel("%s tangency type:" % end))
            self.combo(lay, end + "Tangency", SWEEP_TANGENCY, "%s tangency type" % end)

    def _preview(self, lay):
        c = QtWidgets.QCheckBox("Show preview")
        c.setObjectName("SWSurfShowPreview")
        c.setChecked(True)
        c.toggled.connect(lambda on: setattr(self.obj.ViewObject, "Visibility", on))
        lay.addWidget(c)
        if self.KIND == "SurfaceSweep":
            self._tangency()
        from . import curvdisplay
        self.curv = curvdisplay.CurvatureDisplay(lambda: self.obj.Shape)
        self.curv.setTitle("")           # the group's title already says Curvature Display (look audit AA4)
        self.curv.setFlat(True)
        self.page("Curvature Display").addWidget(self.curv)

    def set(self, prop, value):
        if prop == "TwistUnit" and not self.busy and value != self.obj.TwistUnit:
            per = {"Degrees": 1.0, "Radians": 180.0 / math.pi, "Turns": 360.0}     # the twist stays the same
            v = self.obj.TwistValue * per[self.obj.TwistUnit] / per[value]
            self.busy = True
            self.obj.TwistValue = v
            self.fields["TwistValue"].setValue(v)
            self.busy = False
        Panel.set(self, prop, value)

    def twists(self):
        ""
        o = self.obj
        out = ["None", "Specify Twist Value"]
        if o.Orientation == "Follow Path":
            out.append("Specify Direction Vector")
            if items(o.Path) and all(_kind(sub) == "Edge" for _src, sub in items(o.Path)):
                out.append("Tangent to Adjacent Faces")     # a path on the part's edges
            out.append("Natural")
        guides = len(items(o.Guides))
        if guides >= 1:
            out.append("Follow Path and 1st Guide Curve")
        if guides >= 2:
            out.append("Follow 1st and 2nd Guide Curves")
        return out

    def update_fields(self):
        o, f = self.obj, self.fields
        circular = o.ProfileType == "Circular Profile"
        self.boxes["Profile"].setVisible(not circular)
        f["Diameter"].setVisible(circular)
        if circular and self.active == "Profile":
            self.activate("Path")
        choices = self.twists()
        if o.Twist not in choices:
            o.Twist = "None"
        combo = f["Twist"]
        if [combo.itemText(i) for i in range(combo.count())] != choices:
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(choices)
            combo.blockSignals(False)
        combo.blockSignals(True)
        combo.setCurrentText(o.Twist)
        combo.blockSignals(False)
        value = o.Twist == "Specify Twist Value"
        for name in ("TwistUnit", "TwistValue", "TwistReverse"):
            f[name].setVisible(value)
        f["TwistValue"].setSuffix({"Degrees": "°", "Radians": " rad", "Turns": " turns"}[o.TwistUnit])
        self.boxes["DirectionVector"].setVisible(o.Twist == "Specify Direction Vector")


class LoftPanel(SweepPanel):
    TITLE = "Surface-Loft"
    KIND = "SurfaceLoft"

    def build(self):
        lay = self.page("Profiles")
        self._group = []
        lst = self.box(lay, "Profiles", "Profiles in order: sketches, edges, faces, or a point at an end",
                       ("Sketch", "Edge", "Face", "Vertex"), height=110)
        lst.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        lst.customContextMenuRequested.connect(self._profile_menu)
        up, down = QtWidgets.QPushButton("Move Up"), QtWidgets.QPushButton("Move Down")
        up.setObjectName("SWSurfUp")
        down.setObjectName("SWSurfDown")
        up.clicked.connect(lambda: self.move("Profiles", -1))
        down.clicked.connect(lambda: self.move("Profiles", 1))

        # 348 px wide and cut its right side off); SelectionManager is in the Profiles box's right-click menu
        self.row(lay, up, down)
        self.group_bar = QtWidgets.QFrame()
        bar = QtWidgets.QHBoxLayout(self.group_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        self.group_buttons = QtWidgets.QButtonGroup(self.group_bar)
        self.group_buttons.setExclusive(True)
        for text, name, callback in (("Open Group", "SWSurfSMOpen", None),
                                     ("Closed Group", "SWSurfSMClosed", None),
                                     ("OK", "SWSurfSMOk", self._group_ok),
                                     ("Cancel", "SWSurfSMCancel", self._group_cancel)):
            button = QtWidgets.QToolButton()
            button.setText(text)
            button.setObjectName(name)
            if callback is None:
                button.setCheckable(True)
                self.group_buttons.addButton(button)
                if text == "Open Group":
                    self.group_open = button
                else:
                    self.group_closed = button
            else:
                button.clicked.connect(callback)
            bar.addWidget(button)
        lay.addWidget(self.group_bar)
        self.group_bar.hide()
        lay = self.page("Start/End Constraints")
        self.ends_note = QtWidgets.QLabel("The guide curves, the centerline or Close loft set the ends.")
        self.ends_note.setObjectName("SWSurfLoftEndsNote")
        self.ends_note.setWordWrap(True)
        self.ends_note.hide()
        lay.addWidget(self.ends_note)
        for end in ("Start", "End"):
            self.fields[end + "ConstraintLabel"] = QtWidgets.QLabel("%s constraint:" % end)
            lay.addWidget(self.fields[end + "ConstraintLabel"])
            self.combo(lay, end + "Constraint", LOFT_CONSTRAINTS, "%s constraint" % end)
            self.box(lay, end + "Vector", "%s direction vector: a line, edge, face or plane" % end, ("Line", "Face", "Plane"),
                     single=True, height=26)
            holder = QtWidgets.QVBoxLayout()
            self.row(lay, self.flip(end + "DraftReverse", "Reverse Direction (draft)"),
                     self.number(holder, end + "Draft", "Draft angle", suffix="°", hi=89.0))
            holder = QtWidgets.QVBoxLayout()
            self.row(lay, self.flip(end + "Reverse", "Reverse Direction"),
                     self.number(holder, end + "Length", "%s Tangent Length" % end, suffix="", hi=10.0, step=0.1))
        lay = self.page("Guide Curves")
        lay.addWidget(QtWidgets.QLabel("Guide curves influence:"))
        self.combo(lay, "GuideInfluence", GUIDE_INFLUENCE, "How far along the profile each guide curve pulls it")
        self.box(lay, "Guides", "Guide curves: sketches or edges crossing every profile", ("Sketch", "Edge"), height=60)
        up, down = QtWidgets.QPushButton("Move Up"), QtWidgets.QPushButton("Move Down")
        up.setObjectName("SWSurfGuideUp")
        down.setObjectName("SWSurfGuideDown")
        up.clicked.connect(lambda: self.move("Guides", -1))
        down.clicked.connect(lambda: self.move("Guides", 1))
        self.row(lay, up, down)
        lay = self.page("Centerline Parameters")
        self.box(lay, "Centerline", "Centerline: a sketch or edges the sections stay square to", ("Sketch", "Edge"),
                 single=True, height=26)

        label = QtWidgets.QLabel("Number of sections:")
        lay.addWidget(label)
        spin = QtWidgets.QSpinBox()
        spin.setObjectName("SWSurfSections")
        spin.setToolTip("Number of sections: more sections follow the centerline more closely")
        spin.setRange(2, 100)
        spin.setValue(int(getattr(self.obj, "Sections", 12) or 12))
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(lambda v: self.set("Sections", int(v)))
        lay.addWidget(spin)
        self.fields["Sections"], self.fields["SectionsLabel"] = spin, label
        lay = self.page("Options")
        self.check(lay, "MergeTangent", "Merge tangent faces")
        self.check(lay, "Close", "Close loft")
        self._preview(lay)
        self.check(lay, "MicroTolerance", "Micro tolerance")

    def _profile_entries(self):
        """The Profiles box's rows: [[(obj, sub)], ...], a SelectionManager group as one row."""
        return groups(self.obj.Profiles, getattr(self.obj, "ProfileGroups", None))

    def sync(self):
        super().sync()
        lst = self.boxes["Profiles"]
        lst.clear()
        number = 0
        for group in self._profile_entries():
            if len(group) > 1:
                number += 1
                try:
                    closed = group_wire(group)[1]
                except ValueError:
                    closed = False
                lst.addItem("%s Group<%d>" % ("Closed" if closed else "Open", number))
            else:
                lst.addItem(_name(*group[0]))

    def _store(self, prop, entries):
        if prop != "Profiles":
            return super()._store(prop, entries)
        if entries and all(isinstance(e, tuple) for e in entries):     # a flat list (the base sync's filter)
            keep = set(entries)
            rows = [[e for e in r if e in keep] for r in self._profile_entries()]
            rows = [r for r in rows if r]
        else:
            rows = [e if isinstance(e, list) else [e] for e in entries]
        sizes = [len(r) for r in rows]
        setattr(self.obj, "Profiles", [(o, [s]) for r in rows for o, s in r])
        self.obj.ProfileGroups = sizes if any(n > 1 for n in sizes) else []

    def toggle(self, prop, obj, sub):
        if prop != "Profiles":
            return super().toggle(prop, obj, sub)
        rows = self._profile_entries()
        if [(obj, sub)] in rows:
            rows.remove([(obj, sub)])
        else:
            rows.append([(obj, sub)])
        self._store(prop, rows)
        self.sync()
        self.rebuild()

    def remove_current(self, prop):
        if prop != "Profiles":
            return super().remove_current(prop)
        rows = self._profile_entries()
        row = self.boxes[prop].currentRow()
        if 0 <= row < len(rows):
            del rows[row]
            self._store(prop, rows)
            self.sync()
            self.rebuild()

    def move(self, prop, step):
        if prop != "Profiles":
            return super().move(prop, step)
        rows = self._profile_entries()
        lst = self.boxes[prop]
        row = lst.currentRow()
        to = row + step
        if 0 <= row < len(rows) and 0 <= to < len(rows):
            rows[row], rows[to] = rows[to], rows[row]
            self._store(prop, rows)
            self.sync()
            lst.setCurrentRow(to)
            self.rebuild()

    def _profile_menu(self, pos):
        lst = self.boxes["Profiles"]
        menu = QtWidgets.QMenu(lst)
        action = menu.addAction("SelectionManager")
        if menu.exec_(lst.mapToGlobal(pos)) == action:
            self._start_group()

    def _start_group(self):
        self.activate("Profiles")
        if self.group_bar.isHidden():
            self._group = []
            self.group_open.setChecked(True)
            self.group_bar.show()

    def take(self, obj, sub):
        if not self.group_bar.isHidden() and _kind(sub) == "Edge":
            entry = (obj, sub)
            if entry in self._group:
                self._group.remove(entry)
            else:
                self._group.append(entry)
            return True
        return super().take(obj, sub)

    def _group_ok(self):
        """SelectionManager OK: the picked edges go in Profiles as one Open/Closed Group."""
        group = list(self._group)
        try:
            if len(group) < 1 or any(o is not group[0][0] for o, sub in group):
                raise ValueError(GROUP_MESSAGE)
            closed = group_wire(group)[1]
            if self.group_closed.isChecked() and not closed:
                raise ValueError(GROUP_MESSAGE)
        except ValueError:
            if self.note is not None:
                self.note.setText(GROUP_MESSAGE)
                self.note.show()
            return False
        rows = self._profile_entries()
        rows.append(group)
        self._store("Profiles", rows)
        self._group_cancel()
        self.sync()
        self.rebuild()
        return True

    def _group_cancel(self):
        self._group = []
        self.group_bar.hide()
        if self.note is not None:
            self.note.clear()
            self.note.hide()

    def update_fields(self):
        o, f = self.obj, self.fields
        free = not (o.Guides or o.Centerline or o.Close)
        for name in ("Sections", "SectionsLabel"):
            if name in f:
                f[name].setVisible(bool(o.Centerline))
        if getattr(self, "ends_note", None) is not None:
            self.ends_note.setVisible(not free)
        for end in ("Start", "End"):
            if not free and getattr(o, end + "Constraint") not in ("None", "Default"):
                setattr(o, end + "Constraint", "Default")   # guides, a centerline or Close loft set the ends
                f[end + "Constraint"].blockSignals(True)
                f[end + "Constraint"].setCurrentText("Default")
                f[end + "Constraint"].blockSignals(False)
            kind = getattr(o, end + "Constraint")
            # guides, a centerline or Close loft set the ends: the lists go and a note says so (no greyed lists)
            f[end + "Constraint"].setVisible(free)
            f[end + "ConstraintLabel"].setVisible(free)
            self.boxes[end + "Vector"].setVisible(kind == "Direction Vector")
            for name in ("Draft", "DraftReverse", "Length", "Reverse"):
                f[end + name].setVisible(kind not in ("None", "Default") and
                                         not (name in ("Draft", "DraftReverse") and kind.endswith("To Face")))


class KnitPanel(Panel):
    TITLE = "Knit Surface"
    KIND = "SurfaceKnit"

    def build(self):
        lay = self.page("Selections")
        self.box(lay, "Surfaces", "Surfaces and faces to knit", ("Body", "Face"), height=110)
        self.check(lay, "CreateSolid", "Create solid")
        self.solid_note = QtWidgets.QLabel("")
        self.solid_note.setObjectName("SWSurfCreateSolidNote")
        self.solid_note.setWordWrap(True)
        self.solid_note.setStyleSheet("color: #c00000;")
        self.solid_note.setVisible(False)
        lay.addWidget(self.solid_note)
        self.check(lay, "MergeEntities", "Merge entities")
        lay = self.page("Gap Control", checkable="GapControl")
        self.gap_labels = [QtWidgets.QLabel("Knitting tolerance:"), QtWidgets.QLabel("Show gaps in range:")]
        lay.addWidget(self.gap_labels[0])
        self.number(lay, "Tolerance", "Knitting tolerance", lo=1e-7, decimals=4, step=0.001)
        lay.addWidget(self.gap_labels[1])
        self.number(lay, "GapMin", "Smallest gap shown", decimals=4, step=0.001)
        self.number(lay, "GapMax", "Largest gap shown", decimals=4, step=0.01)
        for name in ("Tolerance", "GapMin", "GapMax"):

            # page-wide unit pass would round it to 0.00
            self.fields[name].setProperty("fw_keep_mm", True)
        self.gaplist = QtWidgets.QListWidget()
        self.gaplist.setObjectName("SWSurfGapList")
        self.gaplist.setToolTip("Gaps in range: tick a gap to knit across it")
        self.gaplist.setMaximumHeight(90)
        self.gaplist.itemChanged.connect(self._gap_ticked)
        self.gaplist.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.gaplist.customContextMenuRequested.connect(self._gap_menu)
        lay.addWidget(self.gaplist)
        self.gaps = QtWidgets.QLabel("")
        self.gaps.setObjectName("SWSurfGaps")
        lay.addWidget(self.gaps)

    def take(self, obj, sub):
        ""

        if sub and _kind(sub) == "Face" and not _is_sketch(obj):
            try:
                whole = Part.getShape(obj)
                if not whole.Solids and len(whole.Faces) >= 1:
                    sub = ""
            except Exception as _fw_err:
                _fw_log("surfacepms.py:knit-take", _fw_err)
        return Panel.take(self, obj, sub)

    def _gap_ticked(self, item):
        if self.busy:
            return
        keys = list(self.obj.GapKeys)
        shown = set(keys)
        ticked = [k for k in self.obj.GapsKnit if k not in shown]       # ticks on gaps out of range stay
        ticked += [keys[i] for i in range(min(self.gaplist.count(), len(keys)))
                   if self.gaplist.item(i).checkState() == QtCore.Qt.Checked]
        self.set("GapsKnit", ticked)

    def _gap_menu(self, pos):
        """Right-click on a listed gap: Increase Tolerance (the knitting tolerance just past this gap, so it
        and every smaller gap are knit) and Decrease Tolerance (just under the largest gap the tolerance
        knits now, so that one opens again and is listed)."""
        item = self.gaplist.itemAt(pos)
        menu = QtWidgets.QMenu(self.gaplist)
        menu.setObjectName("SWSurfGapMenu")
        up = menu.addAction("Increase Tolerance")
        row = self.gaplist.row(item) if item is not None else -1
        up.setEnabled(0 <= row < len(self.obj.GapKeys))
        up.triggered.connect(lambda checked=False: self.increase_tolerance(row))
        down = menu.addAction("Decrease Tolerance")
        down.setEnabled(bool(self.closed_gaps()))
        down.triggered.connect(lambda checked=False: self.decrease_tolerance())
        menu.popup(self.gaplist.viewport().mapToGlobal(pos))
        self._menu = menu
        return menu

    def increase_tolerance(self, row):
        keys = list(self.obj.GapKeys)
        if not 0 <= row < len(keys):
            return None
        size = float(keys[row].split("|")[0])
        tol = size * 1.001 + 1e-6
        self.set("Tolerance", tol)
        return tol

    def closed_gaps(self):
        """Sizes of the gaps the knitting tolerance closes now (not ticks), smallest first."""
        try:
            faces = []
            for o, sub in items(self.obj.Surfaces):
                faces.extend(_shape(o, sub).Faces)
            if not faces:
                return []
            tol = self.obj.Tolerance.Value
            return [g[0] for g in _gaps(_sew(faces, 1e-4), 0.0, tol + 1e-9) if g[0] <= tol]
        except Exception:
            return []

    def decrease_tolerance(self):
        closed = self.closed_gaps()
        if not closed:
            return None
        below = [g for g in closed if g < closed[-1] - 1e-9]
        tol = max(closed[-1] * 0.999, (below[-1] * 1.001 + 1e-6) if below else 1e-7)
        tol = max(tol, 1e-7)
        self.set("Tolerance", tol)
        return tol

    def update_fields(self):
        o = self.obj
        for name in ("Tolerance", "GapMin", "GapMax"):
            self.fields[name].setVisible(o.GapControl)
        self.gaplist.setVisible(o.GapControl)
        was, self.busy = self.busy, True
        self.gaplist.clear()
        for k, text in enumerate(o.GapList, 1):
            item = QtWidgets.QListWidgetItem("Gap %d  %s" % (k, text))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            key = o.GapKeys[k - 1] if k <= len(o.GapKeys) else None
            item.setCheckState(QtCore.Qt.Checked if key in o.GapsKnit else QtCore.Qt.Unchecked)
            self.gaplist.addItem(item)
        self.busy = was
        self.gaps.setText("Open edges: %d" % o.Gaps)
        closed = o.Shape is not None and not o.Shape.isNull() and (o.Shape.ShapeType == "Solid" or (
            o.Shape.ShapeType == "Shell" and o.Shape.isClosed()))
        self.fields["CreateSolid"].setVisible(closed or o.CreateSolid)     # shown once the surfaces close a volume

    def rebuild(self):
        super().rebuild()
        self.update_fields()

    _fields_before = update_fields

    def update_fields(self):
        ""


        self._fields_before()
        o = self.obj
        for label in getattr(self, "gap_labels", []):
            label.setVisible(bool(o.GapControl))
        box = self.fields.get("CreateSolid")
        if box is not None:
            box.setVisible(True)
            box.setEnabled(True)
        note = getattr(self, "solid_note", None)
        if note is not None:
            closed = o.Shape is not None and not o.Shape.isNull() and (o.Shape.ShapeType == "Solid" or (
                o.Shape.ShapeType == "Shell" and o.Shape.isClosed()))
            note.setText("The surfaces do not close a volume, so no solid is made (%d open edges)." % o.Gaps)
            note.setVisible(bool(o.CreateSolid) and not closed)


def _wrap_check(check):
    """A check box whose long text wraps on two lines instead of widening the pane past 300 px:
    the box keeps no text and a word-wrapped label beside it toggles it when clicked."""
    text = check.text()
    holder = QtWidgets.QWidget()
    row = QtWidgets.QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    label = QtWidgets.QLabel(text)
    label.setWordWrap(True)
    label.setObjectName(check.objectName() + "Label")
    label.setToolTip(check.toolTip())
    label.mousePressEvent = lambda event, c=check: c.toggle()
    check.setText("")
    check.setAccessibleName(text)
    owner = _layout_holding(check)
    if owner is None:
        return check
    index = owner.indexOf(check)
    owner.removeWidget(check)
    row.addWidget(check, 0, QtCore.Qt.AlignTop)
    row.addWidget(label, 1)
    owner.insertWidget(index, holder)
    return check


def _layout_holding(widget):
    lay = widget.parentWidget().layout() if widget.parentWidget() is not None else None
    stack = [lay] if lay is not None else []
    while stack:
        l = stack.pop()
        if l.indexOf(widget) >= 0 and isinstance(l, QtWidgets.QBoxLayout):
            return l
        for i in range(l.count()):
            sub = l.itemAt(i).layout()
            if sub is not None:
                stack.append(sub)
    return None


class OffsetPanel(Panel):
    TITLE = "Offset Surface"
    KIND = "SurfaceOffset"

    def build(self):
        lay = self.page("Offset Parameters")
        self.box(lay, "Faces", "Surfaces or faces to offset", ("Face", "Body"), height=90)
        self.row(lay, self.flip("Flip", "Flip Offset Direction"), self._dist())
        c = self.check(lay, "SkipFailed", "Create offset surface without failed faces",
                       "Faces that cannot be offset by the distance are left out instead of failing the feature")
        _wrap_check(c)
        lay.setSpacing(4)
        lay.addStretch(1)

    def _dist(self):
        holder = QtWidgets.QVBoxLayout()
        return self.number(holder, "Distance", "Offset Distance", lo=0.0)


class RuledPanel(Panel):
    TITLE = "Ruled Surface"
    KIND = "SurfaceRuled"

    def build(self):
        lay = self.page("Type")
        kinds = QtWidgets.QWidget()        # its own parent: the radios are exclusive only with each other
        kl = QtWidgets.QVBoxLayout(kinds)
        kl.setContentsMargins(0, 0, 0, 0)
        self.radios = {}
        for name in RULED_TYPES:
            r = QtWidgets.QRadioButton(name)
            r.setObjectName("SWSurf" + name.replace(" ", ""))
            r.setChecked(self.obj.Type == name)
            r.toggled.connect(lambda on, n=name: on and self.set("Type", n))
            self.radios[name] = r
            kl.addWidget(r)
        lay.addWidget(kinds)
        lay = self.page("Distance/Direction")
        self.row(lay, self.flip("AlternateSide", "Alternate Side"), self._width())
        self.box(lay, "Vector", "Reference Vector: an edge, axis or face", ("Line", "Face"), single=True, height=26)
        self.number(lay, "Angle", "Angle", suffix="\u00b0", hi=180.0)
        lay = self.page("Edge Selection")
        self.box(lay, "Edges", "Edges the surface runs from", ("Edge",), height=90)
        alt = QtWidgets.QPushButton("Alternate Face")
        alt.setObjectName("SWSurfAlternateFace")
        alt.setToolTip("Measure from the other face at the edges")
        alt.setCheckable(True)
        alt.setChecked(bool(self.obj.AlternateFace))
        alt.toggled.connect(lambda on: self.set("AlternateFace", on))
        self.fields["AlternateFace"] = alt
        lay.addWidget(alt)
        lay = self.page("Options")
        self.check(lay, "TrimKnit", "Trim and knit")
        self.check(lay, "Connecting", "Connecting surface")
        self.order.remove("Edges")
        self.order.insert(0, "Edges")

    def _width(self):
        holder = QtWidgets.QVBoxLayout()
        return self.number(holder, "Distance", "Distance")

    def update_fields(self):
        t = self.obj.Type
        self.boxes["Vector"].setVisible(t in RULED_VECTOR)
        self.fields["Angle"].setVisible(t == "Tapered to Vector")
        self.fields["AlternateFace"].setVisible(t in RULED_TYPES[:2])


PANELS = {"SurfaceRuled": RuledPanel, "SurfaceExtrude": ExtrudePanel, "SurfaceRevolve": RevolvePanel, "SurfaceSweep": SweepPanel,
          "SurfaceLoft": LoftPanel, "SurfaceKnit": KnitPanel, "SurfaceOffset": OffsetPanel}


def _solid_features(body):
    skip = ("PartDesign::Body", "Sketcher::SketchObject", "PartDesign::Plane", "PartDesign::Line",
            "PartDesign::Point", "PartDesign::CoordinateSystem", "PartDesign::ShapeBinder", "PartDesign::SubShapeBinder")
    return [o for o in body.Group if o.TypeId.startswith("PartDesign::") and o.TypeId not in skip]


def solid_into_body(obj):
    ""



    shape = obj.Shape
    if shape.isNull() or not shape.Solids:
        return None
    doc = obj.Document
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    body = None
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody") if App.GuiUp else None
    except Exception:
        body = None
    if body is None and len(bodies) == 1:
        body = bodies[0]
    if body is None and not bodies:
        body = doc.addObject("PartDesign::Body", "Body")
    if body is None or body.BaseFeature is obj:
        return body
    if body.BaseFeature is not None or _solid_features(body):
        return None
    try:
        body.BaseFeature = obj
        doc.recompute()
        if App.GuiUp:
            try:
                Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
            except Exception as _fw_err:
                _fw_log("surfacepms.py:3033", _fw_err)
            for o in (obj, body):
                try:
                    o.ViewObject.Visibility = o is body
                except Exception as _fw_err:
                    _fw_log("surfacepms.py:3038", _fw_err)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: knit solid into %s: %s\n" % (body.Label, error))
        return None
    return body


def make(doc, kind):
    from . import naming
    cls = FEATURES[kind]
    obj = doc.addObject("Part::FeaturePython", kind)
    cls(obj)
    if App.GuiUp:
        View(obj.ViewObject)
    obj.Label = naming.next_label(doc, cls.NAME)
    return obj


def start(kind):
    """The tool clicked: its PM opens with the first box active; picks made before go in."""
    doc = App.ActiveDocument
    if doc is None or Gui.Control.activeDialog():
        return None
    picks = []
    for s in Gui.Selection.getSelectionEx():
        for sub in s.SubElementNames or [""]:
            picks.append((s.Object, sub))
    doc.openTransaction(FEATURES[kind].NAME)
    try:
        obj = make(doc, kind)
        panel = PANELS[kind](obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    Gui.Selection.clearSelection()
    for o, sub in picks:
        if o is not obj:
            panel.take(o, sub)

    # Direction) is the active one, so the next pick goes there (Alloy Wheel 2026, 5:10)
    if picks and panel.active == "Profile" and getattr(obj, "Profile", None):
        empty = next((p for p in panel.order if p != "Profile" and not panel.boxes[p].isHidden()
                      and not getattr(obj, p)), None)
        if empty is not None:
            panel.activate(empty)
    return obj


COMMANDS = {
    "SWStyle_SurfaceExtrude": ("SurfaceExtrude", "Extruded Surface", "A surface from an extruded sketch or edges."),
    "SWStyle_SurfaceRevolve": ("SurfaceRevolve", "Revolved Surface", "A surface from a sketch or edges revolved about an axis."),
    "SWStyle_SurfaceSweep": ("SurfaceSweep", "Swept Surface", "A surface swept along a path: a profile or a circle."),
    "SWStyle_SurfaceLoft": ("SurfaceLoft", "Lofted Surface", "A surface lofted through profiles in order."),
    "SWStyle_SurfaceKnit": ("SurfaceKnit", "Knit Surface", "Knits surfaces into one, into a solid when they close."),
    "SWStyle_SurfaceOffset": ("SurfaceOffset", "Offset Surface", "Offsets surfaces or faces by a distance."),
    "SWStyle_SurfaceRuled": ("SurfaceRuled", "Ruled Surface", "A strip of surface out from model edges: tangent or normal to the faces, or set by a vector."),
}


class _Cmd:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        kind, menu, tip = COMMANDS[self.name]
        return {"MenuText": menu, "ToolTip": tip, "Pixmap": ICONS[kind]}

    def Activated(self):
        kind = COMMANDS[self.name][0]
        sketch = _open_sketch() if kind in FROM_SKETCH else None
        if sketch is None and kind == "SurfaceExtrude" and not Gui.Selection.getSelectionEx():

            # and waits for a sketch, or a plane or flat face to sketch on, as Extruded Boss/Base does
            from . import sketchstart
            body = sketchstart._body()
            if body is not None:
                Gui.Control.showDialog(sketchstart.PlanePicker(body, title="Extrude", icon=EXTRUDE_ICON,
                                                               message=EXTRUDE_MESSAGE, feature=self.name))
                return
        if sketch is None:
            start(kind)
            return

        doc = sketch.Document
        Gui.getDocument(doc.Name).resetEdit()
        doc.recompute()

        def go(tries=10):
            if Gui.Control.activeDialog() and tries > 0:
                QtCore.QTimer.singleShot(100, lambda: go(tries - 1))
                return
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, sketch.Name, "")
            start(kind)
        QtCore.QTimer.singleShot(0, go)

    def IsActive(self):
        if App.ActiveDocument is None:
            return False
        if COMMANDS[self.name][0] in FROM_SKETCH and _open_sketch() is not None:
            return True
        return not Gui.Control.activeDialog()


EXTRUDE_ICON = "Part_Extrude"          # as the Surface-Extrude page shows it (ICONS)
EXTRUDE_MESSAGE = ("Select:\n"
                   "1) An existing sketch to extrude.\n"
                   "2) A plane or a planar face to sketch the profile on.")


# the surface tools an open sketch is the profile of (Extruded/Revolved/Swept/Lofted Surface)
FROM_SKETCH = ("SurfaceExtrude", "SurfaceRevolve", "SurfaceSweep", "SurfaceLoft")


def _open_sketch():
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        if edit is not None and edit.Object.TypeId == "Sketcher::SketchObject":
            return edit.Object
    except Exception as _fw_err:
        _fw_log("surfacepms.py:3141", _fw_err)
    return None


def register():
    for name in COMMANDS:
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _Cmd(name))
    try:
        from . import radiatepm        # Radiate Surface's PropertyManager (parttools' feature)
        radiatepm.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Radiate Surface PM: %s\n" % error)
