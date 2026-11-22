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
KINDS = ("Slot", "Counterbore Slot", "Countersink Slot")


def sketch_points(sketch):
    """([points], normal, x axis) of a sketch's points and circle centres, global."""
    placement = sketch.getGlobalPlacement() if hasattr(sketch, "getGlobalPlacement") else sketch.Placement
    normal = placement.Rotation.multVec(V(0, 0, 1))
    xaxis = placement.Rotation.multVec(V(1, 0, 0))
    out = []
    for index, geometry in enumerate(sketch.Geometry):
        try:
            if sketch.getConstruction(index):
                continue
        except Exception as _fw_err:
            _fw_log("holeslot.py:45", _fw_err)
        if isinstance(geometry, Part.Point):
            out.append(placement.multVec(V(geometry.X, geometry.Y, geometry.Z)))
        elif isinstance(geometry, (Part.Circle, Part.ArcOfCircle)):
            out.append(placement.multVec(geometry.Center))
    return out, normal, xaxis


def stadium(centre, u, n, length, width):
    """A closed stadium wire: overall length along u, width across, in the plane with normal n."""
    r = width / 2.0
    half = max(length - width, 0.0) / 2.0
    v = n.cross(u)
    v.normalize()
    c1, c2 = centre - u * half, centre + u * half
    if half < 1e-9:
        return Part.Wire([Part.Circle(centre, n, r).toShape()])
    edges = [Part.LineSegment(c1 + v * r, c2 + v * r).toShape(),
             Part.Arc(c2 + v * r, c2 + u * r, c2 - v * r).toShape(),
             Part.LineSegment(c2 - v * r, c1 - v * r).toShape(),
             Part.Arc(c1 - v * r, c1 - u * r, c1 + v * r).toShape()]
    return Part.Wire(edges)


def prism(centre, u, n, down, length, width, depth, lip=0.02):
    face = Part.Face(stadium(centre - down * lip, u, n, length, width))
    return face.extrude(down * (depth + lip))


def funnel(centre, u, n, down, length_top, width_top, width_bottom, angle, lip=0.02):
    """A countersink stadium: wide at the top, narrowing at the angle to the hole's width."""
    drop = (width_top - width_bottom) / 2.0 / math.tan(math.radians(max(1.0, min(angle, 179.0))) / 2.0)
    top = stadium(centre - down * lip, u, n, length_top + 2 * lip / math.tan(math.radians(angle) / 2.0), width_top + 2 * lip / math.tan(math.radians(angle) / 2.0))
    bottom = stadium(centre + down * drop, u, n, length_top - (width_top - width_bottom), width_bottom)
    return Part.makeLoft([top, bottom], True, True)


def _slot(obj, base):
    sketch = obj.Positions
    if sketch is None:
        raise RuntimeError("Pick a sketch with one point per slot")
    points, normal, xaxis = sketch_points(sketch)
    if not points:
        raise RuntimeError("The position sketch has no points")
    down = -normal
    u = App.Rotation(normal, float(obj.Angle)).multVec(xaxis)
    width = float(obj.Diameter)
    length = max(float(obj.SlotLength), width)
    reach = base.BoundBox.DiagonalLength * 2
    depth = reach if obj.ThroughAll else float(obj.Depth)
    tools = []
    for centre in points:
        tools.append(prism(centre, u, normal, down, length, width, depth))
        head_w = float(obj.HeadDiameter)
        if obj.Kind == "Counterbore Slot" and head_w > width:
            tools.append(prism(centre, u, normal, down, length + head_w - width, head_w, float(obj.HeadDepth)))
        elif obj.Kind == "Countersink Slot" and head_w > width:
            tools.append(funnel(centre, u, normal, down, length + head_w - width, head_w, width, float(obj.HeadAngle)))
    result = base.cut(tools, 1e-6)
    return result, Part.makeCompound(tools)


SLOT_HOLE = sf.Spec(
    "SWStyle_SlotHole", "Slot Hole", "Slot", "A slot, counterbore slot or countersink slot at each sketch point.",
    "FEATURES_HOLE_WIZARD", "PartDesign_Hole",
    [Field("Positions", "pick", "Positions", what="Feature", tip="The sketch with one point per slot"),
     Field("Kind", "enum", "Hole Type", "Slot", values=list(KINDS)),
     Field("Diameter", "length", "Diameter", 6.6, tip="Width of the slot"),
     Field("SlotLength", "length", "Slot length", 13.2, tip="Overall length, end to end"),
     Field("HeadDiameter", "length", "C-Bore / C-Sink Diameter", 11.0),
     Field("HeadDepth", "length", "C-Bore Depth", 6.5),
     Field("HeadAngle", "angle", "C-Sink Angle", 90.0),
     Field("ThroughAll", "bool", "Through All", False),
     Field("Depth", "length", "Depth", 10.0),
     Field("Angle", "angle", "Slot angle", 0.0, tip="About the hole, measured from the sketch's X axis")],
    _slot, subtractive=True)


def make(sketch, kind, diameter, length, head_diameter=0.0, head_depth=0.0, head_angle=90.0,
         through=False, depth=10.0, label="Slot"):
    """The slot feature on sketch, in its body, named label (no page: the Type tab chose it all)."""
    body = None
    for parent in sketch.InList:
        if parent.TypeId == "PartDesign::Body":
            body = parent
    if body is None:
        return None
    obj = body.newObject(SLOT_HOLE.type, SLOT_HOLE.internal)
    sf.Feature(obj, SLOT_HOLE)
    if App.GuiUp and sketch.ViewObject is not None:
        sf.View(obj.ViewObject)
    obj.Label = label
    obj.Positions = sketch
    obj.Kind = kind if kind in KINDS else "Slot"
    obj.Diameter, obj.SlotLength = float(diameter), float(length)
    obj.HeadDiameter, obj.HeadDepth, obj.HeadAngle = float(head_diameter or 0.0), float(head_depth or 0.0), float(head_angle or 90.0)
    obj.ThroughAll, obj.Depth = bool(through), float(depth)
    return obj


def register():
    sf.register(SLOT_HOLE)
