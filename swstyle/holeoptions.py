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

from . import advancedhole
from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector


def _points(hole):
    sketch = hole.Profile[0] if hole.Profile else None
    if sketch is None:
        return [], V(0, 0, 1)
    placement = sketch.getGlobalPlacement() if hasattr(sketch, "getGlobalPlacement") else sketch.Placement
    normal = placement.Rotation.multVec(V(0, 0, 1))
    out = []
    for index, geometry in enumerate(sketch.Geometry):
        try:
            if sketch.getConstruction(index):
                continue
        except Exception as _fw_err:
            _fw_log("holeoptions.py:47", _fw_err)
        if isinstance(geometry, Part.Point):
            out.append(placement.multVec(V(geometry.X, geometry.Y, geometry.Z)))
        elif isinstance(geometry, (Part.Circle, Part.ArcOfCircle)):
            out.append(placement.multVec(geometry.Center))
    return out, normal


def _cone(top, down, big, small, angle):
    """A countersink cone: big radius at top, narrowing to small along down at the angle."""
    if big <= small + 1e-6:
        return None
    drop = (big - small) / math.tan(math.radians(max(1.0, min(angle, 179.0))) / 2.0)
    lip = 0.02
    return advancedhole._solid([(big + lip, 0.0), (big, lip), (small, lip + drop), (small, lip + drop + 0.01)],
                               top - down * lip, down)


def _countersinks(obj, base):
    hole = obj.Hole
    if hole is None or hole.TypeId != "PartDesign::Hole":
        raise RuntimeError("Pick a Hole Wizard hole")
    points, normal = _points(hole)
    if not points:
        return None, None
    down = normal if getattr(hole, "Reversed", False) else -normal
    radius = float(hole.Diameter) / 2.0
    cut = str(getattr(hole, "HoleCutType", "None")) != "None"
    rim = float(hole.HoleCutDiameter) / 2.0 if cut else radius
    cbore_depth = float(hole.HoleCutDepth) if cut and "ountersink" not in str(hole.HoleCutType) else 0.0
    before = hole.BaseFeature.Shape if hole.BaseFeature is not None else base
    reach = base.BoundBox.DiagonalLength * 2
    tools = []
    for top in points:
        if obj.NearSide:
            tools.append(_cone(top, down, float(obj.NearDiameter) / 2.0, rim, float(obj.NearAngle)))
        if obj.UnderHead and cbore_depth > 1e-6:
            tools.append(_cone(top + down * cbore_depth, down, float(obj.UnderDiameter) / 2.0, radius,
                               float(obj.UnderAngle)))
        if obj.FarSide:
            line = Part.LineSegment(top, top + down * reach).toShape()
            try:
                hits = line.common(before)
            except Exception:
                hits = None
            if hits is None or not hits.Vertexes:
                continue
            exit_point = max((v.Point for v in hits.Vertexes), key=lambda p: (p - top).Length)
            tools.append(_cone(exit_point, -down, float(obj.FarDiameter) / 2.0, radius, float(obj.FarAngle)))
    tools = [t for t in tools if t is not None]
    if not tools:
        return None, None
    result = base.cut(tools, 1e-6)
    return result, Part.makeCompound(tools)


HOLE_OPTIONS = sf.Spec(
    "SWStyle_HoleOptions", "Hole Options", "Hole Options",
    "Near side, under head and far side countersinks of a Hole Wizard hole.",
    "FEATURES_HOLE_WIZARD", "PartDesign_Hole",
    [Field("Hole", "pick", "Hole", what="Feature", tip="The Hole Wizard hole"),
     Field("NearSide", "bool", "Near side countersink", False),
     Field("NearDiameter", "length", "Near Side Countersink Diameter", 8.0, tip="Near Side countersink diameter"),
     Field("NearAngle", "angle", "Near Side Countersink Angle", 90.0, tip="Near Side countersink angle"),
     Field("UnderHead", "bool", "Under head countersink", False),
     Field("UnderDiameter", "length", "Under Head Countersink Diameter", 7.0, tip="Under Head countersink diameter"),
     Field("UnderAngle", "angle", "Under Head Countersink Angle", 90.0, tip="Under Head countersink angle"),
     Field("FarSide", "bool", "Far side countersink", False),
     Field("FarDiameter", "length", "Far Side Countersink Diameter", 7.0, tip="Far Side countersink diameter"),
     Field("FarAngle", "angle", "Far Side Countersink Angle", 90.0, tip="Far Side countersink angle")],
    _countersinks, subtractive=True)


def make(hole, spec):
    """The Hole Options feature after hole, from the Type tab's choices; None when none are on."""
    on = [k for k in ("near", "under", "far") if spec.get(k)]
    if not on:
        return None
    doc = hole.Document
    body = None
    for parent in hole.InList:
        if parent.TypeId == "PartDesign::Body":
            body = parent
    if body is None:
        return None
    obj = body.newObject(HOLE_OPTIONS.type, HOLE_OPTIONS.internal)
    sf.Feature(obj, HOLE_OPTIONS)
    if App.GuiUp and hole.ViewObject is not None:
        sf.View(obj.ViewObject)
    obj.Label = hole.Label + " Countersinks"
    obj.Hole = hole
    obj.NearSide, obj.UnderHead, obj.FarSide = bool(spec.get("near")), bool(spec.get("under")), bool(spec.get("far"))
    for key, prop in (("near", "Near"), ("under", "Under"), ("far", "Far")):
        if spec.get(key + "_dia"):
            setattr(obj, prop + "Diameter", float(spec[key + "_dia"]))
        if spec.get(key + "_angle"):
            setattr(obj, prop + "Angle", float(spec[key + "_angle"]))
    return obj


def existing(hole):
    """The Hole Options feature of hole, or None."""
    for obj in hole.InList:
        if getattr(obj, "SWStyleKind", "") == HOLE_OPTIONS.internal and getattr(obj, "Hole", None) is hole:
            return obj
    return None


def sync(hole, spec):
    """Edit Feature: the Hole Options feature follows the Type tab's choices (made, changed or removed)."""
    on = [k for k in ("near", "under", "far") if spec.get(k)]
    obj = existing(hole)
    if not on:
        if obj is not None:
            doc = obj.Document
            body = None
            for parent in obj.InList:
                if parent.TypeId == "PartDesign::Body":
                    body = parent
            if body is not None:
                was_tip = body.Tip is obj
                body.removeObject(obj)
                if was_tip:
                    body.Tip = hole
            doc.removeObject(obj.Name)
            if App.GuiUp and hole.ViewObject is not None:
                hole.ViewObject.Visibility = True
        return None
    if obj is None:
        obj = make(hole, spec)
        if obj is not None and App.GuiUp and hole.ViewObject is not None and obj.ViewObject is not None:
            for prop in ("ShapeAppearance", "LineColor", "PointColor", "Transparency", "DisplayMode"):
                try:
                    setattr(obj.ViewObject, prop, getattr(hole.ViewObject, prop))
                except Exception as _fw_err:
                    _fw_log("holeoptions.py:182", _fw_err)
            hole.ViewObject.Visibility = False
            obj.ViewObject.Visibility = True
        return obj
    obj.NearSide, obj.UnderHead, obj.FarSide = bool(spec.get("near")), bool(spec.get("under")), bool(spec.get("far"))
    for key, prop in (("near", "Near"), ("under", "Under"), ("far", "Far")):
        if spec.get(key + "_dia"):
            setattr(obj, prop + "Diameter", float(spec[key + "_dia"]))
        if spec.get(key + "_angle"):
            setattr(obj, prop + "Angle", float(spec[key + "_angle"]))
    return obj


def register():
    sf.register(HOLE_OPTIONS)
