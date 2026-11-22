# SPDX-License-Identifier: LGPL-2.1-or-later
""







import math

import FreeCAD as App
import Part

from . import advancedhole
from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
TYPES = ("Simple", "Tapered", "Counterbored", "Countersunk", "Counterdrilled")


def profile(kind, radius, depth, through, head_radius, head_depth, head_angle, taper, drill_angle):
    """[(radius, depth)] down the hole from the top face."""
    points = []
    d = 0.0
    if kind in ("Counterbored", "Counterdrilled") and head_radius > radius:
        points += [(head_radius, 0.0), (head_radius, head_depth)]
        d = head_depth
    if kind == "Countersunk" and head_radius > radius:
        drop = (head_radius - radius) / math.tan(math.radians(max(1.0, min(head_angle, 179.0))) / 2.0)
        points += [(head_radius, 0.0), (radius, drop)]
        d = drop
    if kind == "Counterdrilled" and head_radius > radius:
        drop = (head_radius - radius) / math.tan(math.radians(max(1.0, min(head_angle, 179.0))) / 2.0)
        points += [(radius, d + drop)]
        d += drop
    if kind == "Tapered":
        bottom = max(radius - depth * math.tan(math.radians(taper)), 0.01)
        points += [(radius, d), (bottom, d + depth)]
        return points
    end = depth if not through else depth
    points += [(radius, d), (radius, d + end)]
    if not through and drill_angle < 179.0:
        points.append((0.001, d + end + radius / math.tan(math.radians(drill_angle) / 2.0)))
    return points


def _legacy(obj, base):
    sketch = obj.Positions
    if sketch is None:
        raise RuntimeError("Pick a sketch with one point per hole")
    from . import holeslot
    points, normal, xaxis = holeslot.sketch_points(sketch)
    if not points:
        raise RuntimeError("The position sketch has no points")
    down = -normal
    reach = base.BoundBox.DiagonalLength * 2
    through = bool(obj.ThroughAll)
    depth = reach if through else float(obj.Depth)
    lip = 0.02
    tools = []
    for top in points:
        pts = profile(obj.HoleType, float(obj.Diameter) / 2.0, depth, through, float(obj.HeadDiameter) / 2.0,
                      float(obj.HeadDepth), float(obj.HeadAngle), float(obj.TaperAngle), float(obj.DrillAngle))
        first = pts[0][0]
        pts = [(first, 0.0)] + [(r, d + lip) for r, d in pts]
        solid = advancedhole._solid(pts, top - down * lip, down)
        if solid is not None:
            tools.append(solid)
    if not tools:
        return None, None
    return base.cut(tools, 1e-6), Part.makeCompound(tools)


LEGACY_HOLE = sf.Spec(
    "SWStyle_LegacyHole", "Legacy Hole", "Hole", "Legacy hole: simple, tapered, counterbored, countersunk or counterdrilled.",
    "FEATURES_HOLE_WIZARD", "PartDesign_Hole",
    [Field("Positions", "pick", "Positions", what="Feature", tip="The sketch with one point per hole"),
     Field("HoleType", "enum", "Hole Type", "Simple", values=list(TYPES)),
     Field("Diameter", "length", "Hole Diameter", 10.0),
     Field("HeadDiameter", "length", "C-Bore / C-Sink / C-Drill Diameter", 16.0),
     Field("HeadDepth", "length", "C-Bore / C-Drill Depth", 5.0),
     Field("HeadAngle", "angle", "C-Sink / C-Drill Angle", 90.0),
     Field("TaperAngle", "angle", "Taper angle", 5.0),
     Field("ThroughAll", "bool", "Through All", False),
     Field("Depth", "length", "Depth", 20.0),
     Field("DrillAngle", "angle", "Drill point angle", 118.0, tip="180 degrees gives a flat bottom")],
    _legacy, subtractive=True)


def make(sketch, spec, label="Hole"):
    """The legacy hole on sketch from the Type tab's choices (keys legacy_*)."""
    body = None
    for parent in sketch.InList:
        if parent.TypeId == "PartDesign::Body":
            body = parent
    if body is None:
        return None
    obj = body.newObject(LEGACY_HOLE.type, LEGACY_HOLE.internal)
    sf.Feature(obj, LEGACY_HOLE)
    if App.GuiUp and sketch.ViewObject is not None:
        sf.View(obj.ViewObject)
    obj.Label = label
    obj.Positions = sketch
    obj.HoleType = spec.get("legacy_type") if spec.get("legacy_type") in TYPES else "Simple"
    obj.Diameter = float(spec.get("legacy_dia") or 10.0)
    obj.HeadDiameter = float(spec.get("legacy_head_dia") or 16.0)
    obj.HeadDepth = float(spec.get("legacy_head_depth") or 5.0)
    obj.HeadAngle = float(spec.get("legacy_angle") or 90.0)
    obj.TaperAngle = float(spec.get("legacy_taper") or 5.0)
    obj.ThroughAll = spec.get("end") == "Through All"
    obj.Depth = max(float(spec.get("depth") or 20.0), 0.01)
    return obj


SIMPLE = "SWStyle_SimpleHole"


def simple_hole():
    ""


    import FreeCADGui as Gui
    from . import holespec, holewizard, sketchstart
    if App.ActiveDocument is None or Gui.Control.activeDialog():
        return None
    face = None
    for sel in Gui.Selection.getSelectionEx():
        subs = [s for s in sel.SubElementNames if s.startswith("Face")]
        if subs and holewizard.placeable(sel.Object, subs[-1]):
            face = (sel.Object, subs[-1])
    body = sketchstart._body()
    if body is None:
        return None
    Gui.Selection.clearSelection()
    panel = holespec.show(body, face, holewizard.start_on_face)
    try:
        panel._set_kind(holespec.LEGACY)
        panel.legacy_type.setCurrentText("Simple")
        panel._changed("legacy")
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Simple Hole: %s\n" % error)
    return panel


class _SimpleHole:
    def GetResources(self):
        return {"MenuText": "Simple Hole", "ToolTip": "A plain round hole on a flat face", "Pixmap": "PartDesign_Hole"}

    def IsActive(self):
        import FreeCADGui as Gui
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        simple_hole()


def register():
    sf.register(LEGACY_HOLE)
    try:
        import FreeCADGui as Gui
        if SIMPLE not in Gui.listCommands():
            Gui.addCommand(SIMPLE, _SimpleHole())
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Simple Hole command: %s\n" % error)
