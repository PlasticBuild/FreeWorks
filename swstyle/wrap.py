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
from .simplefeature import Field

V = App.Vector
COMMAND = "SWStyle_Wrap"
STEP = 0.5            # mm between the points each sketch edge is followed through
OVERLAP = 0.02        # mm the band reaches past the face, so the boolean is not face on face


def _thin(wire):
    """A closed loop with (next to) no area: a single-line font's stroke drawn there and back."""
    try:
        area = abs(Part.Face(wire).Area)
    except Exception:
        return True
    return area < 1e-3 * max(wire.Length, 1e-9)


def _regions(sketch, scribe=False):
    shape = sketch.Shape
    wires = [w for w in shape.Wires if w.isClosed() and not (scribe and _thin(w))]
    if not wires:
        if scribe:
            return []
        raise RuntimeError("The sketch needs closed contours to wrap")
    return Part.makeFace(wires, "Part::FaceMakerBullseye").Faces


def strokes(sketch):
    ""

    out = []
    seen = []
    for w in sketch.Shape.Wires:
        if w.isClosed() and not _thin(w):
            continue
        edges = []
        for e in w.OrderedEdges:
            try:
                mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
            except Exception:
                continue
            if any((mid - m).Length < 1e-6 and abs(e.Length - L) < 1e-6 for m, L in seen):
                continue        # the way back along a stroke
            seen.append((mid, e.Length))
            edges.append(e)
        if not edges:
            continue
        try:
            out.extend(Part.Wire(chain) for chain in Part.sortEdges(edges))
        except Exception:
            out.extend(Part.Wire([e]) for e in edges)
    return out


def _target(obj, base):
    picked = sf.elements(obj, "Face")
    if not picked:
        return None
    face = picked[0][1]
    # the same face of the part so far, so the outward side is known
    for f in base.Faces:
        if f.isSame(face) or (abs(f.Area - face.Area) < 1e-6 and (f.CenterOfMass - face.CenterOfMass).Length < 1e-6):
            return f
    return face


# --------------------------------------------------------------------------- the cylinder
class _Unroll:
    """Sketch points to the (u, v) parameters of the cylinder they wrap to."""

    def __init__(self, sketch, surface):
        self.surface = surface
        place = sketch.getGlobalPlacement()
        normal = place.Rotation.multVec(V(0, 0, 1))
        axis, centre, radius = V(surface.Axis), V(surface.Center), surface.Radius
        offset = (place.Base - centre).dot(normal)
        side = normal * (-1.0 if offset < -1e-6 else 1.0)
        if abs(side.dot(axis)) > 1e-6:
            raise RuntimeError("The sketch plane must run along the cylinder's axis")
        across = axis.cross(side)
        across.normalize()
        self.axis, self.centre, self.radius, self.across = axis, centre, radius, across
        self.u0, self.v0 = surface.parameter(centre + side * radius)
        # which way u and v run on this cylinder
        p0 = surface.value(self.u0, self.v0)
        self.su = 1.0 if (surface.value(self.u0 + 1e-3, self.v0) - p0).dot(across) > 0 else -1.0
        self.sv = 1.0 if (surface.value(self.u0, self.v0 + 1.0) - p0).dot(axis) > 0 else -1.0
        self.side = side

    def uv(self, p):
        s = (p - self.centre).dot(self.across)
        z = (p - self.centre).dot(self.axis) - (self.surface.value(self.u0, self.v0) - self.centre).dot(self.axis)
        return App.Base.Vector2d(self.u0 + self.su * s / self.radius, self.v0 + self.sv * z)


def _curve2d(edge, unroll):
    n = max(12, int(edge.Length / STEP) + 1)
    a, b = edge.FirstParameter, edge.LastParameter
    points = [unroll.uv(edge.valueAt(a + (b - a) * k / (n - 1.0))) for k in range(n)]
    curve = Part.Geom2d.BSplineCurve2d()
    if edge.isClosed():
        curve.interpolate(points[:-1], PeriodicFlag=True)
    else:
        curve.interpolate(points)
    return curve


def _on(curves, surface):
    return [c.toShape(surface, c.FirstParameter, c.LastParameter) for c in curves]


def _face(surface, wires):
    """A face on surface inside the outer wire, less the holes; each loop is turned the way that
    gives it a positive area."""
    def single(wire):
        for _ in range(2):
            fix = Part.ShapeFix.Face(surface, 1e-6, True)
            fix.add(wire)
            fix.perform()
            face = fix.face()
            if face.Area > 0 and face.isValid():
                return face
            wire = wire.copy()
            wire.reverse()
        raise RuntimeError("A sketch contour could not be wrapped")
    face = single(wires[0])
    for hole in wires[1:]:
        cut = face.cut(single(hole))
        if cut.Faces:
            face = cut.Faces[0]
    return face


def _band(region, unroll, r1, r2):
    """The solid between radii r1 and r2 under one sketch region."""
    loops = [region.OuterWire] + [w for w in region.Wires if not w.isSame(region.OuterWire)]
    curves = [[_curve2d(e, unroll) for e in w.OrderedEdges] for w in loops]
    inner, outer = unroll.surface.copy(), unroll.surface.copy()
    inner.Radius, outer.Radius = r1, r2
    faces = [_face(s, [Part.Wire(_on(c, s)) for c in curves]) for s in (inner, outer)]
    for loop in curves:
        for e1, e2 in zip(_on(loop, inner), _on(loop, outer)):
            faces.append(Part.makeRuledSurface(e1, e2).Faces[0])
    shell = Part.makeShell(faces)
    shell.sewShape()
    solid = Part.Solid(Part.Shell(shell.Faces) if shell.ShapeType != "Shell" else shell)
    fix = Part.ShapeFix.Shape(solid)
    fix.perform()
    solid = fix.shape()
    if solid.ShapeType != "Solid" and solid.Solids:
        solid = solid.Solids[0]
    if solid.Volume < 0:
        solid.reverse()
    return solid


def _cylinder_tools(obj, base, face, sketch):
    surface = face.Surface
    unroll = _Unroll(sketch, surface)
    # out of the material: the face's own normal
    u0, u1, v0, v1 = face.ParameterRange
    p = face.valueAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
    radial = (p - unroll.centre) - unroll.axis * (p - unroll.centre).dot(unroll.axis)
    out = 1.0 if face.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1)).dot(radial) > 0 else -1.0
    if obj.Reverse:
        out = -out
    r, t = unroll.radius, obj.Thickness.Value
    if obj.WrapType == "Emboss":
        a, b = r - out * OVERLAP, r + out * t
    else:
        a, b = r - out * t, r + out * OVERLAP
    a, b = min(a, b), max(a, b)
    if a <= 0:
        raise RuntimeError("The wrap is thicker than the cylinder's radius")
    if obj.WrapType == "Scribe":
        loops = [w for region in _regions(sketch, True) for w in region.Wires] + strokes(sketch)
        if not loops:
            raise RuntimeError("The sketch has nothing to scribe")
        return [], [Part.Wire(_on([_curve2d(e, unroll) for e in w.OrderedEdges], surface)) for w in loops]
    regions = _regions(sketch)
    return [_band(region, unroll, a, b) for region in regions], []


# --------------------------------------------------------------------------- the flat face
def _pull_direction(obj):
    """Unit vector of the Pull Direction pick (an edge's direction or a face's normal), or None."""
    if "PullDirection" not in obj.PropertiesList:
        return None
    for _, shape in sf.elements(obj, "PullDirection"):
        if shape.ShapeType == "Edge":
            d = shape.valueAt(shape.LastParameter) - shape.valueAt(shape.FirstParameter)
        elif shape.ShapeType == "Face" and hasattr(shape.Surface, "Axis"):
            d = V(shape.Surface.Axis)
        else:
            continue
        if d.Length > 1e-9:
            return d.normalize()
    return None


def _plane_tools(obj, base, face, sketch):
    normal = face.normalAt(*face.Surface.parameter(face.CenterOfMass)[:2])
    pull = _pull_direction(obj)
    if pull is not None and abs(pull.dot(normal)) > 1e-6:
        normal = pull if pull.dot(normal) > 0 else pull * -1      # pulled along the picked direction
    if obj.Reverse:
        normal = -normal
    place = sketch.getGlobalPlacement()
    sketch_normal = place.Rotation.multVec(V(0, 0, 1))
    face_normal = face.normalAt(*face.Surface.parameter(face.CenterOfMass)[:2])
    if abs(abs(sketch_normal.dot(face_normal)) - 1) > 1e-6 and pull is None:
        raise RuntimeError("On a flat face the sketch must be parallel to the face")
    gap = (face.CenterOfMass - place.Base).dot(face_normal) / max(abs(normal.dot(face_normal)), 1e-9)
    t = obj.Thickness.Value
    tools, lines = [], []
    tilted = abs(abs(sketch_normal.dot(face_normal)) - 1) > 1e-6
    if obj.WrapType == "Scribe" and not tilted:
        for w in strokes(sketch):       # single-line font strokes and open curves
            w = w.copy()
            w.translate(normal * gap)
            lines.append(w)
    for region in _regions(sketch, obj.WrapType == "Scribe"):
        if tilted:
            # pulled along the picked direction onto the face: each contour projected
            wires = []
            for wire in region.Wires:
                shadow = face.makeParallelProjection(wire, normal)
                try:
                    wires.append(Part.Wire(Part.__sortEdges__(shadow.Edges)))
                except Exception:
                    raise RuntimeError("The sketch does not pull onto the face along that direction")
            if not wires:
                continue
            on_face = Part.Face(wires[0]) if len(wires) == 1 else Part.Face(wires[0], wires[1:])
            if on_face.Area < 1e-9:
                continue
        else:
            on_face = region.copy()
            on_face.translate(normal * gap)
        if obj.WrapType == "Scribe":
            lines.extend(on_face.Wires)
        elif obj.WrapType == "Emboss":
            start = on_face.copy()
            start.translate(-normal * OVERLAP)
            tools.append(start.extrude(normal * (t + OVERLAP)))
        else:
            start = on_face.copy()
            start.translate(-normal * t)
            tools.append(start.extrude(normal * (t + OVERLAP)))
    return tools, lines


# --------------------------------------------------------------------------- any face (Spline Surface)
def _patch(face, region, direction, reach):
    """The part of face under the region, looked at along direction: the region pushed through
    the part as a prism, in common with the face."""
    start = region.copy()
    start.translate(direction * -reach)
    prism = start.extrude(direction * (2.0 * reach))
    patch = face.common(prism, 1e-6)
    return patch.Faces


def _outward(face):
    u0, u1, v0, v1 = face.ParameterRange
    return face.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))


def accuracy_tolerance(obj):
    ""

    level = min(max(int(getattr(obj, "Accuracy", 8)), 1), 10)
    return 10.0 ** (-1.0 - 0.4 * level)


def _thick(patch, offset, tol=1e-4):
    """The solid between patch and patch moved by offset along its normal."""
    solid = patch.makeOffsetShape(offset, tol, False, False, 0, 0, True)
    if solid.ShapeType != "Solid" and solid.Solids:
        solid = solid.Solids[0]
    if not solid.Solids and solid.Shells:
        solid = Part.Solid(solid.Shells[0])
    return solid


def _spline_tools(obj, base, face, sketch):
    ""

    place = sketch.getGlobalPlacement()
    direction = place.Rotation.multVec(V(0, 0, 1))
    if (face.CenterOfMass - place.Base).dot(direction) < 0:
        direction = -direction
    pull = _pull_direction(obj)
    if pull is not None:
        direction = pull if pull.dot(direction) >= 0 else -pull
    box = base.BoundBox
    reach = box.DiagonalLength + (place.Base - box.Center).Length + 1.0
    sign = -1.0 if obj.Reverse else 1.0
    t = obj.Thickness.Value
    tools, lines = [], []
    for region in _regions(sketch):
        # only the side of the face that looks back at the sketch (the prism crosses a cone twice)
        near = [f for f in _patch(face, region, direction, reach) if _outward(f).dot(direction) < 0] \
            or _patch(face, region, direction, reach)
        for patch in near:
            if obj.WrapType == "Scribe":
                lines.extend(patch.Wires)
                continue
            # the patch keeps the face's normal: outward from the material (Reverse turns it)
            tol = accuracy_tolerance(obj)
            if obj.WrapType == "Emboss":
                tools.append(_thick(patch, sign * t, tol))
            else:
                tools.append(_thick(patch, -sign * t, tol))
    if not tools and not lines:
        raise RuntimeError("The sketch does not fall on the face along its normal")
    return tools, lines


# --------------------------------------------------------------------------- the feature
def _compute(obj, base):
    picked = sf.elements(obj, "Sketch")
    sketch = picked[0][0] if picked else None
    face = _target(obj, base)
    if sketch is None or face is None:
        return None, None
    kind = type(face.Surface).__name__
    spline = getattr(obj, "WrapMethod", "Analytical") == "Spline Surface"
    if kind == "Plane":
        tools, lines = _plane_tools(obj, base, face, sketch)
    elif kind == "Cylinder" and not spline:
        tools, lines = _cylinder_tools(obj, base, face, sketch)
    elif spline:
        tools, lines = _spline_tools(obj, base, face, sketch)
    else:
        raise RuntimeError("Analytical wraps cylindrical and flat faces: pick Spline Surface for a %s face"
                           % kind.lower())
    if lines:
        pieces, _ = base.generalFuse([w for w in lines], 1e-6)
        solids = pieces.Solids
        if not solids:
            raise RuntimeError("The scribe lines could not be put on the face")
        # every body of the part stays (a multibody part lost all but the first body)
        return (solids[0] if len(solids) == 1 else Part.makeCompound(solids)), None
    tool = tools[0] if len(tools) == 1 else Part.makeCompound(tools)
    result = base.fuse(tools, 1e-6) if obj.WrapType == "Emboss" else base.cut(tools, 1e-6)
    try:
        result = result.removeSplitter()
    except Exception as _fw_err:
        _fw_log("wrap.py:382", _fw_err)
    return result, tool


SPEC = sf.Spec(
    COMMAND, "Wrap", "Wrap",
    "Wraps a closed sketch onto a cylindrical or flat face: emboss, deboss or scribe.",
    "FEATURES_WRAP", "Part_ProjectionOnSurface",
    [Field("WrapType", "icons", "Wrap type", "Emboss", values=["Emboss", "Deboss", "Scribe"], box="Wrap Type",
           icons={"Emboss": "FEATURES_WRAP_EMBOSS", "Deboss": "FEATURES_WRAP_DEBOSS", "Scribe": "FEATURES_WRAP_SCRIBE"}),
     Field("WrapMethod", "icons", "Wrap method", "Analytical", values=["Analytical", "Spline Surface"],
           box="Wrap Method", icons={"Analytical": "FEATURES_WRAP_ANALYTICAL", "Spline Surface": "FEATURES_WRAP_SPLINE"},
           tip="Analytical: onto cylinders and flat faces by unrolling. Spline Surface: onto any face "
               "(cones, spheres, freeform), the sketch laid on it along its normal"),
     Field("Sketch", "pick", "Source Sketch", what="Feature", box="Wrap Parameters",
           tip="The sketch to wrap: closed contours"),
     Field("Face", "pick", "Face for Wrap Sketch", what=("Face",), box="Wrap Parameters",
           tip="A face of the part (any face with Spline Surface)"),
     Field("Thickness", "length", "Thickness", 1.0, box="Wrap Parameters",
           shown=lambda o: o.WrapType != "Scribe"),
     Field("Reverse", "bool", "Reverse direction", False, box="Wrap Parameters",
           shown=lambda o: o.WrapType != "Scribe"),
     Field("Accuracy", "int", "Accuracy", 8, low=1, high=10, box="Wrap Method",
           shown=lambda o: getattr(o, "WrapMethod", "") == "Spline Surface",
           tip="Spline Surface: from 1 (fast, coarse) to 10 (slow, exact)"),
     Field("PullDirection", "pick", "Pull Direction", what=("Edge", "Face"), box="Pull Direction", optional=True,
           tip="An edge or a flat face: the direction the sketch is pulled onto a flat face (its normal when empty)")],
    _compute, refine=False, first_pick="Sketch")          # Scribe keeps its split faces; the others refine themselves



[f for f in SPEC.fields if f.name == "Sketch"][0].kinds = ("Sketcher::",)


def _route(obj, name, holder, element):
    """A face of the part clicked while Source Sketch is active goes to Face for Wrap Sketch."""
    if name == "Sketch" and (element or "").startswith("Face") and             not getattr(holder, "TypeId", "").startswith("Sketcher::"):
        return "Face"
    return name


SPEC.route = _route


def register():
    sf.register(SPEC)
