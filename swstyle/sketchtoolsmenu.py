# SPDX-License-Identifier: LGPL-2.1-or-later
""


import FreeCAD as App
import FreeCADGui as Gui

ENTITY_KEYS = ("Line", "CornerRectangle", "CenterRectangle", "ThreePointCornerRectangle", "ThreePointCenterRectangle",
               "Parallelogram", "Slot", "CenterpointSlot", "ThreePointArcSlot", "ArcSlot", "Polygon", "Circle",
               "PerimeterCircle", "CenterArc", "TangentArc", "ThreePointArc", "Ellipse", "PartialEllipse",
               "Parabola", "Conic", "Spline", "StyleSpline", "EquationDrivenCurve", "SketchPoint", "Centerline", "MidpointLine",
               "Text", "BeltChain", "FitSpline")
KEYS = ("SketchFillet", "SketchChamfer", "Offset", "Convert", "IntersectionCurve", "Trim", "Extend", "Split", "JogLine", "CloseSketchToModel",
        "MirrorEntities", "DynamicMirror", "StretchEntities", "MoveEntities", "RotateEntities", "ScaleEntities",
        "CopyEntities", "LinearSketchPattern", "CircularSketchPattern", "ReplaceEntity",
        "CheckSketchForFeature", "RepairSketch", "SketchXpert",

        "AlignSketch", "AlignGridOrigin")
SPLINE_KEYS = ("InsertSplinePoint", "InsertControlVertex", "ShowInflectionPoints", "ShowMinimumRadius",
               "ShowCurvatureCombs", "SimplifySpline", "ShowSplineHandles")
MENUS = (("SWStyle_SketchEntitiesMenu", "Sketch Entities", "Sketch entities", ENTITY_KEYS),
         ("SWStyle_SketchToolsMenu", "Sketch Tools", "Sketch tools", KEYS),
         ("SWStyle_SplineToolsMenu", "Spline Tools", "Spline tools", SPLINE_KEYS))


def commands(have=None, keys=KEYS):
    from . import catalog
    have = set(Gui.listCommands()) if have is None else have
    names = []
    for key in keys:
        cmd = catalog.BY_KEY.get(key)
        if cmd is None:
            continue
        name = next((n for n in cmd.natives if n in have), None)
        if name and name not in names:
            names.append(name)
    return tuple(names)


class ToolsMenu:
    def __init__(self, text, tip, keys):
        self.text, self.tip, self.keys = text, tip, keys

    def GetCommands(self):
        return commands(keys=self.keys)

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "DropDownMenu": True, "Exclusive": False}

    def IsActive(self):
        return App.ActiveDocument is not None


def register():
    have = set(Gui.listCommands())
    for name, text, tip, keys in MENUS:
        if name not in have:
            Gui.addCommand(name, ToolsMenu(text, tip, keys))


def menu_items(have):
    """Tools > Sketch Entities, Sketch Tools and Spline Tools, with the look's other Tools entries (before Measure)."""
    return [{"insert": name, "menuItem": "Std_Measure"} for name, _t, _p, _k in MENUS if name in have]
