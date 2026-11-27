# SPDX-License-Identifier: LGPL-2.1-or-later
""








import math

import FreeCAD as App
import Part

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
COMMAND = "SWStyle_HealEdges"


def _inside_vertices(shape, faces):
    """The vertices whose every edge lies on the picked faces: the only ones healing may take."""
    on = [e for f in faces for e in f.Edges]
    inside = []
    seen = set()
    for f in faces:
        for v in f.Vertexes:
            if v.hashCode() in seen:
                continue
            seen.add(v.hashCode())
            if all(any(a.isSame(e) for e in on) for a in shape.ancestorsOfType(v, Part.Edge)):
                inside.append(v)
    return inside


def merge_edges(shape, faces, angle):
    """shape with the edges of faces merged where they meet at less than angle (degrees)."""
    inside = {v.hashCode() for v in _inside_vertices(shape, faces)}
    keep = [v for v in shape.Vertexes if v.hashCode() not in inside]
    u = Part.ShapeUpgrade.UnifySameDomain(shape, True, False, True)
    u.setAngularTolerance(math.radians(max(angle, 1e-6)))
    u.setLinearTolerance(1e-4)
    if keep:
        u.keepShapes(keep)
    u.build()
    return u.shape()


def heal(shape, faces, angle, length):
    """shape with the edges of faces (all faces when none) merged where they meet at less than
    angle; then each edge shorter than length is merged with its neighbour whatever the angle
    (up to 45 degrees)."""
    # the picks come from another copy of the shape: find them in this one
    faces = [f for f in shape.Faces if any(_same(f, g) for g in faces)] if faces else list(shape.Faces)
    result = merge_edges(shape, faces, angle)
    if length > 0:
        picked = [f for f in result.Faces if any(_near(f, g) for g in faces)]
        short = [e for f in picked for e in f.Edges if e.Length < length]
        if short:
            inside = {v.hashCode() for v in _inside_vertices(result, picked)}
            ends = {v.hashCode() for e in short for v in e.Vertexes} & inside
            keep = [v for v in result.Vertexes if v.hashCode() not in ends]
            u = Part.ShapeUpgrade.UnifySameDomain(result, True, False, True)
            u.setAngularTolerance(math.radians(45.0))
            u.setLinearTolerance(1e-4)
            if keep:
                u.keepShapes(keep)
            u.build()
            result = u.shape()
    if not result.isValid():
        result.fix(1e-7, 1e-7, 1e-4)
    return result


def _same(a, b):
    return a.isSame(b) or (abs(a.Area - b.Area) < 1e-6 and (a.CenterOfMass - b.CenterOfMass).Length < 1e-6)


def _near(a, b):
    return abs(a.Area - b.Area) < 0.05 * max(b.Area, 1e-9) + 1.0 and \
        (a.CenterOfMass - b.CenterOfMass).Length < 0.05 * max(b.BoundBox.DiagonalLength, 1e-9) + 0.5


def _compute(obj, base):
    faces = [f for _, f in sf.elements(obj, "Faces") if f.ShapeType == "Face"]
    result = heal(base, faces, obj.AngleTolerance.Value, obj.EdgeLength.Value)
    if not result.Solids or not result.isValid():
        raise RuntimeError("Healing would break the body: try a smaller tolerance")
    result = result.Solids[0] if len(result.Solids) == 1 else Part.makeCompound(result.Solids)
    obj.Healed = "%d edges merged" % max(0, len(base.Edges) - len(result.Edges))
    return result, None


SPEC = sf.Spec(
    COMMAND, "Heal Edges", "Heal Edges",
    "Merges short edges on faces of an imported body into longer edges.",
    "FEATURES_HEAL_EDGES", "Part_Refine_Shape",
    [Field("Faces", "pick", "Faces to heal", what=("Face",), many=True, optional=True, box="Heal Edges",
           tip="The faces whose edges are merged; none heals the whole body"),
     Field("AngleTolerance", "angle", "Angle tolerance", 1.0, low=0.0, high=45.0, box="Heal Edges",
           tip="Edges that meet at less than this are merged into one"),
     Field("EdgeLength", "length", "Edge length tolerance", 0.1, box="Heal Edges",
           tip="Edges shorter than this are merged with a neighbor whatever the angle"),
     Field("Healed", "info", "Result", "", box="Heal Edges")],
    _compute, refine=False)


def register():
    sf.register(SPEC)
