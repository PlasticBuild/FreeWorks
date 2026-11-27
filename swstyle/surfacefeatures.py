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

import FreeCAD as App
import Part

from . import naming
from . import simplefeature as sf
from .simplefeature import Field

try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

V = App.Vector
SPECS = {}


class SurfaceFeature(sf.Feature):
    """A simplefeature Spec made as a free surface (Part::FeaturePython) instead of a Body feature."""

    def __init__(self, obj, spec):
        # simplefeature's PropertyManager looks at BaseFeature: a surface has none
        obj.addProperty("App::PropertyLink", "BaseFeature", "Base", "Not used by surfaces")
        obj.setEditorMode("BaseFeature", 2)
        super().__init__(obj, spec)

    def execute(self, obj):
        from . import pickwait
        spec = self.spec(obj)
        ckey = None
        try:
            if spec.cache:
                # a surface made from a part keys on the part's shape as it uses it (spec.held), so
                # a change after that point (a Flex preview further down the body) rebuilds nothing
                from . import fcache
                held = getattr(spec, "held", None)
                ckey = fcache.key(obj, held(obj) if held else None, getattr(spec, "cache_skip", ()))
                hit = fcache.get(ckey)
                if hit is not None:
                    pickwait.done(obj)
                    obj.Shape = hit[0] if hit[0] is not None else Part.Shape()
                    return
            shape, _ = spec.compute(obj, None)
        except Exception as error:
            if not pickwait.waits(obj, error):
                raise
            obj.Shape = Part.Shape()        # the PM waits for its picks
            return
        pickwait.done(obj)
        obj.Shape = shape if shape is not None else Part.Shape()
        if ckey is not None and shape is not None:
            # keyed on the inputs as the build leaves them (a build may set a property)
            fcache.put(fcache.key(obj, held(obj) if held else None, getattr(spec, "cache_skip", ())), shape)


def make(spec, doc=None, picks=None, edit=True, **values):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    doc.openTransaction(spec.title)
    obj = doc.addObject("Part::FeaturePython", spec.internal)
    SurfaceFeature(obj, spec)
    if App.GuiUp and Gui.ActiveDocument is not None:
        sf.View(obj.ViewObject)
    obj.Label = naming.next_label(doc, spec.label)
    for name, value in (picks or {}).items():
        field = [f for f in spec.fields if f.name == name][0]
        if field.what in sf.WHOLE:
            setattr(obj, name, value)
        else:
            setattr(obj, name, [(o, [e]) for o, e in value])
    for name, value in values.items():
        setattr(obj, name, value)
    from . import pickwait
    with pickwait.opening(obj, edit and App.GuiUp):     # its PM opens next: empty picks wait for it
        doc.recompute()
    if edit and App.GuiUp:
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
    else:
        doc.commitTransaction()
    return obj


class Command:
    def __init__(self, spec):
        self.spec = spec

    def GetResources(self):
        return {"MenuText": self.spec.title, "ToolTip": self.spec.tip, "Pixmap": self.spec.pixmap}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        make(self.spec, picks=sf.preselected(self.spec))


def _sew(faces, tol=1e-4):
    shell = Part.makeShell(faces)
    try:
        from . import sewtol
        return sewtol.sewn(faces, tol)
    except Exception:
        return shell


def _source_faces(obj, field):
    """The faces of the surfaces the picked edges belong to (each source's shape once)."""
    seen, out = set(), []
    for source, _ in sf.elements(obj, field):
        if source.Name in seen:
            continue
        seen.add(source.Name)
        out.extend(Part.getShape(source).Faces)
    return out


_MERGED = set()      # Filled Surfaces whose Merge result hid the surfaces round the opening (this session)


def _show_sources(obj, field):
    for source, _ in sf.elements(obj, field):
        try:
            if source.ViewObject is not None and not source.ViewObject.Visibility:
                source.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("surfacefeatures.py:show", _fw_err)


def _hide_sources(obj, field):
    for source, _ in sf.elements(obj, field):
        try:
            if source.ViewObject is not None and source.ViewObject.Visibility:
                source.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("surfacefeatures.py:127", _fw_err)


# --------------------------------------------------------------------------- Extend Surface
def _outward(face, edge):
    """The direction, in the face, pointing from the edge's middle away from the face."""
    mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
    tangent = edge.tangentAt((edge.FirstParameter + edge.LastParameter) / 2.0)
    u, v = face.Surface.parameter(mid)
    normal = face.normalAt(u, v)
    side = normal.cross(tangent)
    side.normalize()
    probe = mid + side * (edge.Length * 1e-3 + 1e-4)
    inside = face.isInside(probe, 1e-6, True)
    return side * -1 if inside else side


def _side(face, edge):
    """Which parameter side (0: u min, 1: u max, 2: v min, 3: v max) of an untrimmed face the edge is on."""
    u0, u1, v0, v1 = face.ParameterRange
    u, v = face.Surface.parameter(edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0))
    gaps = [abs(u - u0) / max(u1 - u0, 1e-12), abs(u - u1) / max(u1 - u0, 1e-12),
            abs(v - v0) / max(v1 - v0, 1e-12), abs(v - v1) / max(v1 - v0, 1e-12)]
    best = min(range(4), key=lambda k: gaps[k])
    return best if gaps[best] < 1e-3 else None


def _param_reach(face, side, distance):
    """How far past its side (0: u min, 1: u max, 2: v min, 3: v max) the face's parameter goes for the
    surface to run on by distance, measured on the surface across the middle. The surface's own pace at the
    edge counts, not its average: a loft with tangency at its ends runs slowly there, and the average gave
    a third of the length (Nozzle video N5: 3.5 mm for 10)."""
    u0, u1, v0, v1 = face.ParameterRange
    surface = face.Surface
    if side < 2:
        end, sign, span = (u0, -1.0, u1 - u0) if side == 0 else (u1, 1.0, u1 - u0)
        at = lambda t: surface.value(end + sign * t, (v0 + v1) / 2.0)
    else:
        end, sign, span = (v0, -1.0, v1 - v0) if side == 2 else (v1, 1.0, v1 - v0)
        at = lambda t: surface.value((u0 + u1) / 2.0, end + sign * t)

    def run(t, n=48):
        pts = [at(t * k / n) for k in range(n + 1)]
        return sum((pts[k + 1] - pts[k]).Length for k in range(n))
    h = span * 1e-4
    t = distance * h / max(run(h, 1), 1e-12)        # the pace at the edge
    for _ in range(8):
        got = run(t)
        if got <= 1e-12:
            break
        if abs(got - distance) < distance * 1e-4:
            break
        t *= distance / got
    return t


def _same_surface(face, edges, distance):
    """The face grown on its own surface past the given edges, or None when it cannot be."""
    if len(face.Edges) != 4 or isinstance(face.Surface, Part.Plane):
        return None
    u0, u1, v0, v1 = face.ParameterRange
    grow = [0.0, 0.0, 0.0, 0.0]
    for edge in edges:
        side = _side(face, edge)
        if side is None:
            return None
        spline = isinstance(face.Surface, (Part.BSplineSurface, Part.BezierSurface))
        grow[side] = 1.0 if spline else _param_reach(face, side, distance)
    if isinstance(face.Surface, (Part.BSplineSurface, Part.BezierSurface)):
        # a spline's own polynomial runs wild past its ends: grown on its curvature instead
        try:
            sides = [k for k in range(4) if grow[k] > 0]
            return _spline_grown(face, sides, distance)
        except Exception as _fw_err:
            _fw_log("surfacefeatures.spline_grow", _fw_err)
            return None
    try:
        surface = face.Surface      # a B-spline cannot grow past its own knots: then None (linear)
        return surface.toShape(u0 - grow[0], u1 + grow[1], v0 - grow[2], v1 + grow[3])
    except Exception:
        return None


def _arc_on(p0, d1, d2, s):
    """The point at arc length s from p0 along the curve's circle of curvature (d1, d2: its first and second
    derivatives there): the surface goes on as it bends at the edge, curvature continuous."""
    speed = d1.Length
    t = d1 * (1.0 / speed)
    k = (d2 - t * d2.dot(t)) * (1.0 / (speed * speed))
    kappa = k.Length
    if kappa < 1e-9:
        return p0 + t * s
    n = k * (1.0 / kappa)
    import math
    return p0 + t * (math.sin(kappa * s) / kappa) + n * ((1.0 - math.cos(kappa * s)) / kappa)


def _spline_grown(face, sides, distance, n_along=24, n_across=24, n_out=8):
    """A spline face grown by distance past the sides given (0: u min, 1: u max, 2: v min, 3: v max), one
    face: the face sampled, every row run on along its circle of curvature at the edge, and one spline
    fitted through it all."""
    surf = face.Surface
    u0, u1, v0, v1 = face.ParameterRange
    us = [u0 + (u1 - u0) * i / n_across for i in range(n_across + 1)]
    vs = [v0 + (v1 - v0) * j / n_along for j in range(n_along + 1)]
    grid = [[surf.value(u, v) for v in vs] for u in us]        # grid[i][j]: u rows, v columns

    def outward(u, v, du, dv, sign):
        d1 = surf.getDN(u, v, du, dv) * sign
        d2 = surf.getDN(u, v, 2 * du, 2 * dv)
        return d1, d2
    steps = [distance * k / n_out for k in range(1, n_out + 1)]
    for side in sides:
        if side in (2, 3):
            v = v0 if side == 2 else v1
            sign = -1.0 if side == 2 else 1.0
            for i, u in enumerate(us):
                d1, d2 = outward(u, v, 0, 1, sign)
                ext = [_arc_on(surf.value(u, v), d1, d2, st) for st in steps]
                grid[i] = (list(reversed(ext)) + grid[i]) if side == 2 else (grid[i] + ext)
        else:
            u = u0 if side == 0 else u1
            sign = -1.0 if side == 0 else 1.0
            cols = len(grid[0])
            # the v values of the columns as they now stand: rows grown on v keep their own ends
            rows = []
            for k, st in enumerate(steps):
                row = []
                for j in range(cols):
                    jj = min(max(j - (n_out if 2 in sides else 0), 0), n_along)
                    v = vs[jj]
                    d1, d2 = outward(u, v, 1, 0, sign)
                    base = grid[0][j] if side == 0 else grid[-1][j]
                    row.append(_arc_on(base, d1, d2, st))
                rows.append(row)
            grid = (list(reversed(rows)) + grid) if side == 0 else (grid + rows)
    fit = Part.BSplineSurface()
    fit.approximate(Points=grid, DegMin=3, DegMax=5, Continuity=2, Tolerance=1e-3, ParamType="ChordLength")
    out = fit.toShape()
    if out.isNull() or not out.isValid():
        return None
    return out


def _same_edge(a, b):
    return a.isSame(b) or (abs(a.Length - b.Length) < 1e-7 and a.CenterOfMass.distanceToPoint(b.CenterOfMass) < 1e-7)


def _owners(faces, edge):
    """Every face the edge borders (Alternate Face picks the second)."""
    return [f for f in faces if any(_same_edge(edge, e) for e in f.Edges)]


def edge_settings(obj):
    """Filled Surface per-edge settings {row: {"control": ..., "alternate": bool}} (rows of Patch Boundary)."""
    import json
    try:
        return json.loads(getattr(obj, "EdgeSettings", "") or "{}")
    except Exception:
        return {}


def set_edge_setting(obj, row, **values):
    import json
    if "EdgeSettings" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "EdgeSettings", "Filled Surface", "Per-edge curvature control")
        obj.setEditorMode("EdgeSettings", 2)
    data = edge_settings(obj)
    data.setdefault(str(row), {}).update(values)
    obj.EdgeSettings = json.dumps(data)
    obj.touch()


def _owner(faces, edge):
    for face in faces:
        if any(edge.isSame(e) or (abs(e.Length - edge.Length) < 1e-7 and
                                  e.CenterOfMass.distanceToPoint(edge.CenterOfMass) < 1e-7) for e in face.Edges):
            return face
    return None


def _reach(obj, face, edge):
    """How far the edge goes out for Up To Point / Up To Surface: along the face's way out at the
    edge's middle, to the point (its distance ahead) or to where that line meets the surface."""
    mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
    out = _outward(face, edge)
    target = sf.elements(obj, "UpTo")
    if not target:
        raise RuntimeError("Pick the %s to extend up to" % ("point" if obj.EndCondition == "Up To Point" else "surface"))
    shape = target[0][1]
    if obj.EndCondition == "Up To Point":
        p = shape.Vertexes[0].Point if shape.Vertexes else shape.BoundBox.Center
        d = (p - mid).dot(out)
    else:
        size = max(shape.BoundBox.DiagonalLength, face.BoundBox.DiagonalLength, 1.0) * 10
        ray = Part.LineSegment(mid, mid + out * size).toShape()
        dist, pairs, _info = ray.distToShape(shape)
        if dist > 1e-4:
            raise RuntimeError("The surface is not ahead of the edges")
        d = (pairs[0][0] - mid).Length
    if d <= 1e-7:
        raise RuntimeError("The point or surface must be beyond the edges")
    return d


def _one_plane_face(face, merged):
    """The coplanar faces of merged (a plane grown by strips and corners) as one face: its free
    edges make the outline; None when the plane has holes or the outline is not one loop."""
    try:
        if len(face.Wires) != 1:
            return None
        counts = {}
        for f in merged.Faces:
            for e in f.Edges:
                key = None
                for k in counts:
                    if counts[k][0].isSame(e) or (counts[k][0].Length - e.Length < 1e-7 and counts[k][0].CenterOfMass.distanceToPoint(e.CenterOfMass) < 1e-7):
                        key = k
                        break
                if key is None:
                    counts[len(counts)] = [e, 1]
                else:
                    counts[key][1] += 1
        free = [v[0] for v in counts.values() if v[1] == 1]
        wires = Part.sortEdges(free)
        if len(wires) != 1:
            return None
        wire = Part.Wire(wires[0])
        grown = Part.Face(wire)
        if not grown.isValid() or abs(grown.Area - merged.Area) > 1e-6 * max(1.0, merged.Area):
            return None
        if grown.normalAt(0, 0).dot(face.normalAt(0, 0)) < 0:
            grown.reverse()
        return grown
    except Exception as _fw_err:
        _fw_log("surfacefeatures.one_plane_face", _fw_err)
        return None


def _plane_corners(face, edges, d):
    """The corner patches where two extended edges of a plane meet, so the plane grows as one face
    (a rectangle extended on all four edges is a bigger rectangle, corners included)."""
    out = []
    for i, e1 in enumerate(edges):
        for e2 in edges[i + 1:]:
            shared = [a.Point for a in e1.Vertexes for b in e2.Vertexes if a.Point.distanceToPoint(b.Point) < 1e-7]
            if not shared or e1.Curve.__class__.__name__ != "Line" or e2.Curve.__class__.__name__ != "Line":
                continue
            v = shared[0]
            o1, o2 = _outward(face, e1), _outward(face, e2)
            det = 1.0 - o1.dot(o2) ** 2
            if det < 1e-9:
                continue
            # the point p with p.o1 = d and p.o2 = d
            a = d * (1.0 - o1.dot(o2)) / det
            p = v + o1 * a + o2 * a
            try:
                out.append(Part.Face(Part.makePolygon([v, v + o1 * d, p, v + o2 * d, v])))
            except Exception as _fw_err:
                _fw_log("surfacefeatures.plane_corner", _fw_err)
    return out


def _extend(obj, base):
    picked = sf.elements(obj, "Edges")
    if not picked:
        return None, None
    distance = float(obj.Distance)
    condition = getattr(obj, "EndCondition", "Distance")
    if condition == "Distance" and distance <= 0:
        raise RuntimeError("The distance must be more than 0")
    faces = _source_faces(obj, "Edges")
    by_face = {}
    for _, edge in picked:
        if edge.ShapeType == "Face":

            index = next((i for i, f in enumerate(faces) if f.isSame(edge) or (
                abs(f.Area - edge.Area) < 1e-7 and f.CenterOfMass.distanceToPoint(edge.CenterOfMass) < 1e-7)), None)
            if index is None:
                raise RuntimeError("Pick edges or faces of a surface")
            own = faces[index]
            others = [f for i, f in enumerate(faces) if i != index]
            free = [e for e in own.OuterWire.Edges if not any(_owner([o], e) for o in others)]
            by_face.setdefault(index, []).extend(free)
            continue
        if edge.ShapeType != "Edge":
            continue
        owner = _owner(faces, edge)
        if owner is None:
            raise RuntimeError("Pick edges of a surface")
        by_face.setdefault(faces.index(owner), []).append(edge)
    by_face = {k: v for k, v in by_face.items() if v}
    if not by_face:
        return None, None
    result = list(faces)
    added = []
    for index, edges in by_face.items():
        face = faces[index]
        if condition != "Distance":
            distance = max(_reach(obj, face, e) for e in edges)
        grown = _same_surface(face, edges, distance) if obj.Type == "Same surface" else None
        if grown is not None:
            result[index] = grown
            continue
        strips = []
        for edge in edges:
            d = _reach(obj, face, edge) if condition != "Distance" else distance
            strips.extend(edge.extrude(_outward(face, edge) * d).Faces)
        if obj.Type == "Same surface" and isinstance(face.Surface, Part.Plane) and strips:

            try:
                if condition == "Distance":
                    strips = strips + _plane_corners(face, edges, distance)
                merged = face.fuse(strips).removeSplitter()
                if len(merged.Faces) == 1 and merged.Faces[0].isValid():
                    result[index] = merged.Faces[0]
                    continue
                one = _one_plane_face(face, merged)
                if one is not None:
                    result[index] = one
                    continue
            except Exception as _fw_err:
                _fw_log("surfacefeatures.extend_plane", _fw_err)
        added.extend(strips)
    _hide_sources(obj, "Edges")
    return _sew(result + added), None


EXTEND = sf.Spec(
    "SWStyle_ExtendSurface", "Extend Surface", "Surface-Extend", "Makes a surface bigger past its edges.",
    "SURFACES_EXTEND_SURFACE", "Surface_ExtendFace",

    [Field("Edges", "pick", "Edges/Faces to Extend", tip="Edges or faces of a surface", what=("Edge", "Face"), many=True,
           box="Edges/Faces to Extend"),
     Field("EndCondition", "radio", "End Condition", "Distance", tip="End Condition",
           values=["Distance", "Up To Point", "Up To Surface"], box="End Condition"),
     Field("Distance", "length", "Distance", 10.0, shown=lambda o: getattr(o, "EndCondition", "Distance") == "Distance",
           box="End Condition"),
     Field("UpTo", "pick", "Point or surface to extend up to", what=("Vertex", "Face", ""), optional=True,
           shown=lambda o: getattr(o, "EndCondition", "Distance") != "Distance", box="End Condition"),
     Field("Type", "radio", "Extension Type", "Same surface", tip="Extension Type", values=["Same surface", "Linear"],
           box="Extension Type")],
    _extend, needs_body=False)


# --------------------------------------------------------------------------- Filled Surface
def _out_at(face, edge, t):
    """At parameter t of the edge: the direction in the face, square to the edge, pointing away
    from the face (the way the face would carry on past the edge)."""
    p = edge.valueAt(t)
    tangent = edge.tangentAt(t)
    u, v = face.Surface.parameter(p)
    side = face.normalAt(u, v).cross(tangent)
    side.normalize()
    probe = p + side * (edge.Length * 1e-3 + 1e-4)
    return side * -1 if face.isInside(probe, 1e-6, True) else side


def _carry_on_points(edges, owners, size):
    """Curvature: points a short way past each boundary edge on the neighbour face's own surface,
    so the patch keeps bending the way that face bends (the filler's own G2 mode does nothing)."""
    out = []
    for edge, face in zip(edges, owners):
        if face is None:
            continue
        n = max(6, int(edge.Length / max(size / 10.0, 1e-6)))
        for i in range(n):
            t = edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * (i + 0.5) / float(n)
            p = edge.valueAt(t)
            try:
                guess = p + _out_at(face, edge, t) * (size * 0.08)
                u, v = face.Surface.parameter(guess)
                q = face.Surface.value(u, v)
            except Exception:
                continue
            if (q - p).Length > size * 0.02 and not face.isInside(q, size * 1e-4, True):
                out.append(q)       # a point back on the face itself (a surface that ends at the edge) is no carry-on
    return out


def _whole_loop(edges, faces):
    ""

    try:
        if Part.Wire(Part.__sortEdges__(list(edges))).isClosed():
            return edges
    except Exception:
        pass
    for f in faces:
        for w in f.Wires:
            we = w.OrderedEdges
            if all(any(_same_edge(e, x) for x in we) for e in edges) and w.isClosed():
                return we
    return edges


def _close_gaps(edges, tol=1e-6):
    """Fix up boundary: straight lines across the gaps between the picked edges' ends."""
    try:
        return Part.Wire(Part.__sortEdges__(edges)).OrderedEdges
    except Exception as _fw_err:
        _fw_log("surfacefeatures.py:340", _fw_err)
    ends = [(e, e.Vertexes[0].Point, e.Vertexes[-1].Point) for e in edges]
    chain = [ends.pop(0)]
    out = [chain[0][0]]
    tip = chain[0][2]
    start = chain[0][1]
    while ends:
        k, flip = min(((i, f) for i in range(len(ends)) for f in (0, 1)),
                      key=lambda x: (ends[x[0]][1 + x[1]] - tip).Length)
        e, a, b = ends.pop(k)
        if flip:
            a, b = b, a
        if (a - tip).Length > tol:
            out.append(Part.LineSegment(tip, a).toShape())
        out.append(e)
        tip = b
    if (start - tip).Length > tol:
        out.append(Part.LineSegment(tip, start).toShape())
    return out


LEVELS = {"Contact": 0, "Tangent": 1, "Curvature": 2}



RESOLUTION = {1: (3, 6, 1), 2: (3, 10, 2), 3: (3, 15, 3), 4: (3, 20, 3), 5: (3, 25, 4)}   # (Degree, NbPtsOnCur, NbIter)


def _carry_on(edge, face, t):
    """At edge parameter t: the direction across the edge leading off the face (its surface carried on)."""
    p = edge.valueAt(t)
    u, v = face.Surface.parameter(p)
    d = edge.tangentAt(t).cross(face.normalAt(u, v))
    if d.Length < 1e-9:
        return None
    d.normalize()
    size = max(edge.Length * 1e-3, 1e-4)
    if face.isInside(p + d * size, 1e-6, True):
        d = d * -1
    return d


def _bulge_point(edges, owners, levels, face):
    """A point to dome the patch out to, when the patch came back without the tangency the edges ask
    for (None when it holds it, or when the faces round the opening do not lean one way)."""
    off, aims, rim = 0.0, App.Vector(), []
    for e, f, lv in zip(edges, owners, levels):
        if not lv or f is None:
            continue
        for k in (0.25, 0.5, 0.75):
            t = e.FirstParameter + k * (e.LastParameter - e.FirstParameter)
            p = e.valueAt(t)
            try:
                uf, vf = f.Surface.parameter(p)
                up, vp = face.Surface.parameter(p)
                a, b = f.normalAt(uf, vf), face.normalAt(up, vp)
                off = max(off, min(a.getAngle(b), a.getAngle(b * -1)))
                d = _carry_on(e, f, t)
            except Exception:
                continue
            if d is not None:
                aims += d
                rim.append(p)
    if off < 0.09 or len(rim) < 3:      # within about 5 degrees: the patch holds the tangency
        return None
    aim = aims * (1.0 / len(rim))
    if aim.Length < 0.3:
        return None                     # the faces lean every way (a flat flange): no way to dome
    centre = sum(rim, App.Vector()) * (1.0 / len(rim))
    reach = sum((p - centre).Length for p in rim) / len(rim)
    return centre + App.Vector(aim).normalize() * (0.3 * reach)


def plate_face(edges, points=(), owners=None, order="Contact", optimize=False, curves=(), resolution=3):
    ""


    orders = list(order) if isinstance(order, (list, tuple)) else [order] * len(edges)
    levels = [LEVELS.get(o, 0) for o in orders] + [0] * max(0, len(edges) - len(orders))
    level = max(levels) if levels else 0
    owners = list(owners or [None] * len(edges))
    try:
        fill = Part.BRepOffsetAPI.MakeFilling()
        degree, points_on, iters = RESOLUTION.get(int(resolution or 3), RESOLUTION[3])
        if optimize:          # Optimize surface: a lighter patch at the same resolution
            fill.setResolParam(Degree=min(degree, 3), NbPtsOnCur=max(6, points_on - 5), NbIter=1)
        else:
            fill.setResolParam(Degree=degree, NbPtsOnCur=points_on, NbIter=iters)
        extra = []
        if level == 2:
            size = Part.Compound(list(edges)).BoundBox.DiagonalLength
            curving = [(e, f) for e, f, lv in zip(edges, owners, levels) if lv == 2]
            extra = _carry_on_points([e for e, _f in curving], [f for _e, f in curving], size)
        for e, f, lv in zip(edges, owners, levels):
            if lv and f is not None:
                own = [x for x in f.Edges if x.isSame(e) or (abs(x.Length - e.Length) < 1e-7 and
                       x.CenterOfMass.distanceToPoint(e.CenterOfMass) < 1e-7)]
                fill.add(own[0] if own else e, f, 1, True)   # the face's own edge carries its pcurve
            else:
                fill.add(e, 0, True)
        for e in curves:
            fill.add(e, 0, False)
        for p in list(points) + extra:
            fill.add(App.Vector(p))
        fill.build()
        face = fill.shape().Faces[0]
        if not face.isValid():
            face = face.copy()
            face.fix(1e-7, 1e-7, 1e-7)     # a mixed G0 / G1 boundary can come back with a misoriented wire
        if level and not points and face.isValid():
            guide = _bulge_point(edges, owners, levels, face)
            if guide is not None:
                # OpenCascade's plate gives up the tangency where the faces round the opening carry on
                # steeply (a loft that leaves its end square, a cylinder's end): it comes back flat. A

                return plate_face(edges, [guide], owners, orders, optimize, curves, resolution)
        if face.isValid() and face.Area > 0:
            return face
    except Exception as _fw_err:
        _fw_log("surfacefeatures.py:407", _fw_err)
    if curves and points:
        # OpenCascade's plate can refuse a free constraint curve together with points (BRep_API: command not

        # the curve and the points
        along = [e.valueAt(e.FirstParameter + (e.LastParameter - e.FirstParameter) * i / 12.0)
                 for e in curves for i in range(13)]
        try:
            return plate_face(edges, list(points) + along, owners, order, optimize, (), resolution)
        except Exception as _fw_err:
            _fw_log("surfacefeatures.py:plate curve points", _fw_err)
    return Part.makeFilledFace(list(edges) + list(curves))


def _hole_loops(edges, faces):
    ""

    try:
        if Part.Wire(Part.__sortEdges__(list(edges))).isClosed():
            return edges
    except Exception:
        pass
    out = list(edges)
    for f in faces:
        for w in f.Wires:
            if w.isSame(f.OuterWire):
                continue
            mine = [e for e in w.Edges if any(_same_edge(e, p) for p in edges)]
            if mine and len(mine) < len(w.Edges):
                out.extend(e for e in w.Edges if not any(_same_edge(e, p) for p in out))
    return out


def _filled(obj, base):
    picked = sf.elements(obj, "Boundary")
    if not picked:
        return None, None
    edges = [e for _, s in picked for e in (s.Edges if s.ShapeType != "Edge" else [s])]
    if getattr(obj, "FixUp", True):
        edges = _hole_loops(edges, _source_faces(obj, "Boundary"))
    points = [s.Point for _, s in sf.elements(obj, "Points") if s.ShapeType == "Vertex"]
    curves = []
    for source, s in sf.elements(obj, "Curves"):
        if s.ShapeType != "Vertex" and getattr(source, "TypeId", "") == "Sketcher::SketchObject":
            # a sketch's own points are not in its shape: read them from its geometry
            for g in source.Geometry:
                if type(g).__name__ == "Point":
                    points.append(source.getGlobalPlacement().multVec(App.Vector(g.X, g.Y, g.Z)))
        if s.ShapeType == "Vertex":
            points.append(s.Point)
        else:

            # is not on any of the sketch's edges
            curves.extend(s.Edges)
            for v in s.Vertexes:
                if not any(e.distToShape(v)[0] < 1e-6 for e in s.Edges):
                    points.append(v.Point)
    edges = _whole_loop(edges, _source_faces(obj, "Boundary"))
    if getattr(obj, "FixUp", True):
        edges = _close_gaps(edges)
    else:
        try:
            loop = Part.Wire(Part.__sortEdges__(edges))
        except Exception:
            loop = None
        if loop is None or not loop.isClosed():
            raise RuntimeError("The patch boundary is not closed: close the gaps or check Fix up boundary")
        edges = loop.OrderedEdges   # the filler needs the loop in order
    order = getattr(obj, "CurvatureControl", "Contact")
    neighbours = _source_faces(obj, "Boundary")
    per_edge = edge_settings(obj)
    orders, owners = [], []
    for e in edges:
        # the Patch Boundary row the edge came from (a gap closed by Fix up has none: Contact)
        k = next((i for i, (_o, p) in enumerate(picked) if any(_same_edge(q, e) for q in p.Edges)), None)
        own = per_edge.get(str(k), {}) if k is not None else {}
        orders.append(order if getattr(obj, "ApplyAll", True) or k is None else own.get("control", order))
        faces = _owners(neighbours, e)
        alt = k is not None and own.get("alternate", False) and len(faces) > 1
        owners.append(faces[1] if alt else (faces[0] if faces else None))
    order = orders
    try:
        face = plate_face(edges, points, owners, order, getattr(obj, "Optimize", False), curves,
                          getattr(obj, "Resolution", 3))
    except Exception:
        try:
            face = Part.makeFilledFace(edges + curves)
        except Exception:
            raise RuntimeError("The patch boundary must be a closed loop of edges (Fix up boundary closes small gaps)")
    if face is None or face.isNull() or not face.isValid() or face.Area < 1e-6:
        raise RuntimeError("The patch boundary must be a closed loop of edges: pick every edge round the opening")
    if getattr(obj, "ReverseSurface", False):
        face = face.reversed()
    shape = face
    if obj.Merge:
        if neighbours:
            shape = _sew(neighbours + [face])
            if obj.Solid:
                try:
                    solid = Part.Solid(shape)
                    if solid.isValid() and solid.Volume > 0:
                        shape = solid
                except Exception as _fw_err:
                    _fw_log("surfacefeatures.py:461", _fw_err)
            _hide_sources(obj, "Boundary")
            _MERGED.add((obj.Document.Name, obj.Name))
    elif (obj.Document.Name, obj.Name) in _MERGED:
        # Merge result unticked again: the surfaces it had taken in are their own bodies again
        _MERGED.discard((obj.Document.Name, obj.Name))
        _show_sources(obj, "Boundary")
    return shape, None


FILLED = sf.Spec(
    "SWStyle_FilledSurface", "Filled Surface", "Surface-Fill", "Fills a closed loop of edges with a patch.",
    "SURFACES_FILLED_SURFACE", "Surface_Filling",
    [Field("Boundary", "pick", "Patch Boundary", tip="Edges or a sketch that close a loop", what=("Edge", ""),
           many=True, box="Patch Boundary"),
     Field("AlternateFace", "button", "Alternate Face", box="Patch Boundary",
           tip="Tangent / Curvature to the other face at the picked edge"),
     Field("CurvatureControl", "enum", "Edge settings:", "Contact", values=["Contact", "Tangent", "Curvature"],
           box="Patch Boundary",
           tip="How the patch meets the face beside the picked edge (every edge with Apply to all edges)"),
     Field("ApplyAll", "bool", "Apply to all edges", False, box="Patch Boundary",
           tip="One curvature control for every boundary edge; off: pick an edge in the list to set its own"),
     Field("Optimize", "bool", "Optimize surface", True, box="Patch Boundary"),
     Field("ShowPreview", "bool", "Show preview", True, box="Patch Boundary",
           tip="Show the patch while the PropertyManager is open"),


     # the separate Constraint Points box shows only for a part saved with points in it
     Field("Curves", "pick", "Constraint Curves", what=("Edge", "Vertex", ""), many=True, optional=True,
           box="Constraint Curves", tip="Curves or points the patch must pass through (sketched points or splines)"),
     Field("Points", "pick", "Constraint Points", what=("Vertex",), many=True, optional=True,
           box="Constraint Curves", shown=lambda o: bool(getattr(o, "Points", None))),

     # each Filled Surface is its own body until Knit (or Merge result) joins it
     Field("FixUp", "bool", "Fix up boundary", False, box="Options"),
     Field("Merge", "bool", "Merge result", False, box="Options"),
     Field("Solid", "bool", "Create solid", False, box="Options"),
     Field("ReverseSurface", "bool", "Reverse direction", False, box="Options"),
     Field("Resolution", "int", "Resolution control", 3, low=1, high=5, legacy=3, box="Resolution Control",
           tip="1 = coarse, light patch; 5 = fine patch that follows the boundary more closely")],
    _filled, needs_body=False, panel=None)


if Gui is not None:
    from PySide import QtWidgets as _Qw

    class FilledPanel(sf.Panel):
        ""



        def __init__(self, obj):
            self.row = None
            super().__init__(obj)
            form = self.form[0] if isinstance(self.form, list) else self.form
            form.setProperty("swstyle_pm_title", "Fill Surface")
            box = self.lists.get("Boundary")
            if box is not None:
                box.currentRowChanged.connect(self._row)
            try:
                self._edge_settings_rows()
            except Exception as error:
                App.Console.PrintLog("FreeCAD: Fill Surface rows: %r\n" % error)

        def _edge_settings_rows(self):
            """filledge-1121: Patch Boundary reads as the Surfaces video shows it: "Edge settings:" on a
            row of its own, the Alternate Face button centred under it at its own width, then the combo
            across the full width (before: the label sat beside the combo, under a full-width button)."""
            combo, alt = self.widgets.get("CurvatureControl"), self.widgets.get("AlternateFace")
            lay = combo.parentWidget().layout() if combo is not None and combo.parentWidget() else None
            if alt is None or not isinstance(lay, _Qw.QFormLayout) or alt.parentWidget() is not combo.parentWidget():
                return
            label = lay.labelForField(combo)
            row = lay.getWidgetPosition(combo)[0]
            arow = lay.getWidgetPosition(alt)[0]
            if label is None or row < 0 or arow < 0 or arow > row:
                return
            lay.takeRow(row)
            lay.takeRow(arow)
            label.setObjectName("SWStyle_EdgeSettingsLabel")
            holder = _Qw.QWidget(combo.parentWidget())
            holder.setObjectName("SWStyle_AlternateFaceRow")
            line = _Qw.QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.addStretch(1)
            line.addWidget(alt)
            line.addStretch(1)
            alt.setMinimumWidth(max(alt.sizeHint().width() + 24, 120))
            alt.setSizePolicy(_Qw.QSizePolicy.Fixed, alt.sizePolicy().verticalPolicy())
            lay.insertRow(arow, label)
            lay.insertRow(arow + 1, holder)
            lay.insertRow(arow + 2, combo)
            for w in (label, holder, alt, combo):
                w.show()

        def _row(self, row):
            self.row = row if row >= 0 else None
            self._sync_combo()

        def _control(self, row):
            if getattr(self.obj, "ApplyAll", True) or row is None:
                return self.obj.CurvatureControl
            return edge_settings(self.obj).get(str(row), {}).get("control", self.obj.CurvatureControl)

        def _sync_combo(self):
            combo = self.widgets.get("CurvatureControl")
            if combo is not None:
                combo.blockSignals(True)
                combo.setCurrentText(self._control(self.row))
                combo.blockSignals(False)

        def _changed(self, *args):
            if self.busy:
                return
            combo = self.widgets["CurvatureControl"]
            apply_all = self.widgets["ApplyAll"].isChecked()
            if not apply_all and self.row is not None and combo.currentText() != self._control(self.row):
                set_edge_setting(self.obj, self.row, control=combo.currentText())
                combo.blockSignals(True)
                combo.setCurrentText(self.obj.CurvatureControl)   # the all-edges value stays as it was
                combo.blockSignals(False)
            super()._changed(*args)

        def _run(self, field):
            if field.name != "AlternateFace":
                return super()._run(field)
            rows = [self.row] if self.row is not None else list(range(self.lists["Boundary"].count()))
            for row in rows:
                now = edge_settings(self.obj).get(str(row), {}).get("alternate", False)
                set_edge_setting(self.obj, row, alternate=not now)
            self.obj.touch()
            self.obj.Document.recompute()
            self._preview()
            self._show()

        def _show(self):
            super()._show()
            box = self.lists.get("Boundary")
            if box is None:
                return
            box.blockSignals(True)
            settings = edge_settings(self.obj)
            for i in range(box.count()):
                item = box.item(i)
                tag = self._control(i) if not getattr(self.obj, "ApplyAll", True) else ""
                if settings.get(str(i), {}).get("alternate"):
                    tag = (tag + ", " if tag else "") + "alternate face"
                if tag:
                    item.setText("%s <%s>" % (item.text(), tag))
            if self.row is not None and self.row < box.count():
                box.setCurrentRow(self.row)
            box.blockSignals(False)
            self._sync_combo()

    FILLED.panel = FilledPanel


# --------------------------------------------------------------------------- Surface Chamfer
def _chamfer(obj, base):
    picked = sf.elements(obj, "Items")
    if not picked:
        return None, None
    sources = {s.Name: s for s, _ in picked}
    if len(sources) != 1:
        raise RuntimeError("Pick edges of one surface body")
    source = list(sources.values())[0]
    shape = Part.getShape(source)
    edges = []
    for _, e in picked:
        found = [x for x in shape.Edges if x.isSame(e) or (abs(x.Length - e.Length) < 1e-7 and
                                                        x.CenterOfMass.distanceToPoint(e.CenterOfMass) < 1e-7)]
        if found:
            edges.append(found[0])
    d1 = float(obj.Distance)
    d2 = float(obj.Distance2) if obj.Type == "Distance distance" else d1
    if d1 <= 0 or d2 <= 0:
        raise RuntimeError("The chamfer distance must be more than 0")
    try:
        result = shape.makeChamfer(d1, d2, edges)
    except Exception:
        raise RuntimeError("The chamfer does not fit these edges")
    _hide_sources(obj, "Items")
    return result, None


CHAMFER = sf.Spec(
    "SWStyle_SurfaceChamfer", "Chamfer", "Surface-Chamfer", "Bevels edges where surfaces meet.",
    "SURFACES_CHAMFER", "Part_Chamfer",
    [Field("Items", "pick", "Items To Chamfer", tip="Edges between two faces of a surface body", what=("Edge",),
           many=True),
     Field("Type", "enum", "Chamfer Type", "Equal distance", values=["Equal distance", "Distance distance"]),
     Field("Distance", "length", "Distance", 2.0),
     Field("Distance2", "length", "Distance 2", 2.0, shown=lambda o: o.Type == "Distance distance")],
    _chamfer, needs_body=False)


# --------------------------------------------------------------------------- Flatten
def _unwrap(face, accuracy):
    """(flat face in the XY plane, map) for one face: map takes a 3D point on the face to its place on the flat."""
    if isinstance(face.Surface, Part.Plane):
        rot = App.Rotation(face.Surface.Axis, V(0, 0, 1))
        flat = face.copy()
        flat.Placement = App.Placement(V(), rot).multiply(flat.Placement)
        return flat, lambda p: rot.multVec(p)
    import flatmesh
    nurbs = face.toNurbs().Faces[0].Surface
    nurbs.setUNotPeriodic()
    nurbs.setVNotPeriodic()
    bs = nurbs.toBSpline(accuracy, "C0", "C0", 3, 3, 10)
    tess = bs.toShape()
    tess.tessellate(accuracy)
    unwrapper = flatmesh.FaceUnwrapper(tess)
    unwrapper.findFlatNodes(5, 0.99)
    poles = unwrapper.interpolateFlatFace(tess)
    fs = bs.copy()
    nu, nv = len(bs.getPoles()), len(bs.getPoles()[0])
    i = 0
    for u in range(nu):
        for v in range(nv):
            fs.setPole(u + 1, v + 1, V(poles[i][0], poles[i][1], 0))
            i += 1

    def place(p):
        u, v = bs.parameter(p)
        q = fs.value(u, v)
        return V(q.x, q.y, 0)
    # the face's own boundary (its trims, holes and relief cuts) carried onto the flat surface
    wires = []
    for wire in face.Wires:
        edges = []
        for edge in wire.OrderedEdges:
            if edge.Degenerated or edge.Length < 1e-9:      # a sphere's pole: no edge on the flat
                continue
            n = max(8, min(200, int(edge.Length / max(accuracy * 20, 0.05))))
            pts = [place(x) for x in edge.discretize(n)]
            if len(pts) > 1 and pts[0].distanceToPoint(pts[-1]) > 1e-9:
                edges.append(Part.makePolygon(pts) if not isinstance(edge.Curve, Part.Line) else
                             Part.LineSegment(pts[0], pts[-1]).toShape())
        if edges:
            try:
                w = Part.Wire(Part.__sortEdges__([e for x in edges for e in x.Edges]))
                if not w.isClosed():
                    w = Part.Wire(w.Edges + [Part.LineSegment(w.Vertexes[-1].Point, w.Vertexes[0].Point).toShape()])
                wires.append(w)
            except Exception as _fw_err:
                _fw_log("surfacefeatures.py:660", _fw_err)
    flat = None
    if wires:
        try:
            flat = Part.makeFace(wires, "Part::FaceMakerBullseye")
        except Exception:
            flat = None
    if flat is None or flat.isNull() or flat.Area < 1e-9:
        flat = fs.toShape()
    return flat, place


def _frame(face, point):
    """The face's normal and a tangent at point."""
    u, v = face.Surface.parameter(point)
    n = face.normalAt(u, v)
    try:
        du = next((t for t in face.Surface.tangent(u, v) if t is not None and t.Length > 1e-12), None)
    except Exception:
        du = None
    if du is None:          # a pole: any direction in the tangent plane
        du = n.cross(V(1, 0, 0)) if abs(n.x) < 0.9 else n.cross(V(0, 1, 0))
    return n, du


def _pieces(obj, face):
    """Relief cuts: the face split along the picked sketch or curves (projected onto it)."""
    picked = sf.elements(obj, "ReliefCuts") if "ReliefCuts" in obj.PropertiesList else []
    edges = []
    for _o, shape in picked:
        edges += list(shape.Edges)
    if not edges:
        return [face], 0
    try:
        cut = face.project(edges)
        result, _map = face.generalFuse([cut], 1e-7)
        faces = [f for f in result.Faces if f.Area > 1e-9]
    except Exception:
        faces = []
    return (faces, len(edges)) if len(faces) > 1 else ([face], len(edges))


def _flatten(obj, base):
    picked = sf.elements(obj, "Faces")
    if not picked:
        return None, None
    try:
        import flatmesh  # noqa: F401
    except ImportError:
        raise RuntimeError("Flatten needs FreeCAD's flatmesh module")
    accuracy = float(obj.Accuracy)
    flats, x, notes = [], 0.0, []
    anchor = _anchor_point(obj)
    for n_face, (_, face) in enumerate(f for f in picked if f[1].ShapeType == "Face"):
        pieces, n_cuts = _pieces(obj, face)
        if n_cuts and len(pieces) == 1:
            notes.append("the relief cut does not split the face (it must run to the face's edge)")
        # the piece with the vertex first; the others follow it across the cuts they share
        here = anchor if anchor is not None and n_face == 0 else face.Vertexes[0].Point
        pieces.sort(key=lambda f: f.distToShape(Part.Vertex(here))[0])
        laid = []
        for k, piece in enumerate(pieces):
            flat, place = _unwrap(piece, accuracy)
            if k:
                # turn and move the piece in the plane so a cut edge it shares with a laid piece meets it
                for done, done_place, done_flat in laid:
                    shared = [e for e in piece.Edges for d in done.Edges if e.isSame(d) or
                              (abs(e.Length - d.Length) < 1e-6 and e.CenterOfMass.distanceToPoint(d.CenterOfMass) < 1e-6)]
                    if shared:
                        a, b = shared[0].Vertexes[0].Point, shared[0].Vertexes[-1].Point
                        if a.distanceToPoint(b) < 1e-9:
                            a, b = shared[0].valueAt(shared[0].FirstParameter), shared[0].CenterOfMass
                        a1, b1 = place(a), place(b)
                        a0, b0 = done_place(a), done_place(b)
                        import math
                        ang = math.atan2((b0 - a0).y, (b0 - a0).x) - math.atan2((b1 - a1).y, (b1 - a1).x)
                        rot = App.Rotation(V(0, 0, 1), math.degrees(ang))
                        move = App.Placement(a0 - rot.multVec(a1), rot)
                        flat = flat.transformGeometry(move.toMatrix())
                        place = (lambda f, m: (lambda p: m.multVec(f(p))))(place, move)
                        break
            laid.append((piece, place, flat))
        group = [f for _p, _pl, f in laid]
        shape = group[0] if len(group) == 1 else Part.makeCompound(group)
        first, first_place = laid[0][0], laid[0][1]
        if n_face == 0:

            # it flattens from, with that point staying where it is
            p3 = here if first.distToShape(Part.Vertex(here))[0] < 1e-4 else first.Vertexes[0].Point
            n3, t3 = _frame(first, p3)
            p2 = first_place(p3)
            t3 = t3 - n3 * t3.dot(n3)
            if t3.Length > 1e-12:
                t3.normalize()
            q2 = first_place(first.Surface.projectPoint(p3 + t3 * 1e-3 * max(first.BoundBox.DiagonalLength, 1.0))) - p2
            if t3.Length < 1e-12 or q2.Length < 1e-12:
                t3, q2 = V(1, 0, 0), V(1, 0, 0)
            t3.normalize(); q2.normalize()
            z = V(0, 0, 1)
            r2 = App.Rotation(q2, z.cross(q2), z, "ZXY")
            r3 = App.Rotation(t3, n3.cross(t3), n3, "ZXY")
            rot = r3.multiply(r2.inverted())
            shape = shape.transformGeometry(App.Placement(p3 - rot.multVec(p2), rot).toMatrix())
        else:
            box = shape.BoundBox
            shape.translate(V(x - box.XMin, -box.YMin, -box.ZMin))
        x += shape.BoundBox.XLength + float(obj.Spacing)
        flats.append(shape)
    if not flats:
        return None, None
    if "Info" in obj.PropertiesList:
        area = sum(f.Area for f in flats)
        text = "Flat area %.2f mm2" % area + ("; " + "; ".join(notes) if notes else "")
        if obj.Info != text:
            obj.Info = text
    return (flats[0] if len(flats) == 1 else Part.makeCompound(flats)), None


def _anchor_point(obj):
    picked = sf.elements(obj, "Anchor")
    if not picked:
        return None
    shape = picked[0][1]
    if shape.ShapeType == "Vertex":
        return shape.Point
    if shape.ShapeType == "Edge":         # a point on an edge: its middle
        return shape.valueAt(shape.FirstParameter + 0.5 * (shape.LastParameter - shape.FirstParameter))
    return None


FLATTEN = sf.Spec(
    "SWStyle_Flatten", "Flatten", "Surface-Flatten", "Lays a curved face or surface out flat.",
    "SURFACES_FLATTEN", "MeshPart_CreateFlatFace",
    [Field("Faces", "pick", "Face/Surface to Flatten", what=("Face",), many=True),
     Field("Anchor", "pick", "Vertex or point on edge to flatten from", what=("Vertex", "Edge"), optional=True),
     Field("Accuracy", "float", "Accuracy", 0.05, tip="Smaller: finer", low=0.001, high=1.0),
     Field("ReliefCuts", "pick", "Sketch or curve to create relief cut", what=("Edge", ""), many=True,
           optional=True, box="Relief Cuts"),
     Field("Spacing", "length", "Spacing", 5.0),
     Field("Info", "info", "Messages", "")],
    _flatten, needs_body=False)


# --------------------------------------------------------------------------- Surface From Mesh
def _from_mesh(obj, base):
    mesh_obj = obj.Mesh
    if mesh_obj is None:
        return None, None
    mesh = getattr(mesh_obj, "Mesh", None)
    if mesh is None:
        raise RuntimeError("Pick a mesh body")
    shape = Part.Shape()
    shape.makeShapeFromMesh(mesh.Topology, float(obj.Tolerance))
    if obj.Refine:
        try:
            shape = shape.removeSplitter()
        except Exception as _fw_err:
            _fw_log("surfacefeatures.py:817", _fw_err)
    if obj.Solid:
        try:
            solid = Part.Solid(Part.Shell(shape.Faces))
            if solid.isValid():
                shape = solid
        except Exception as _fw_err:
            _fw_log("surfacefeatures.py:824", _fw_err)
    return shape, None


FROM_MESH = sf.Spec(
    "SWStyle_SurfaceFromMesh", "Surface From Mesh", "Surface-Mesh", "Makes surfaces (or a solid) from a mesh.",
    "SURFACES_FROM_MESH", "Part_ShapeFromMesh",
    [Field("Mesh", "pick", "Mesh body", what="Object"),
     Field("Tolerance", "float", "Sewing tolerance", 0.1, low=0.0, high=10.0),
     Field("Refine", "bool", "Merge flat triangles into faces", True),
     Field("Solid", "bool", "Make a solid when the mesh is closed", True)],
    _from_mesh, needs_body=False)


ALL = [EXTEND, FILLED, CHAMFER, FLATTEN, FROM_MESH]


def register():
    for spec in ALL:
        try:
            if spec.command not in Gui.listCommands():
                Gui.addCommand(spec.command, Command(spec))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s command not added (%s)\n" % (spec.title, error))
