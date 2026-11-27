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


import FreeCADGui as Gui

from . import tool
from . import sketchfirst

# command name -> (menu text, tooltip, FreeCAD icon to borrow until the add-on's own, starter)
COMMANDS = {
    "FreeWorks_Line": ("Line", "Sketches lines that chain; back over the end point or A for an arc "
                       "(click-click or press, drag, release)", "Sketcher_CreatePolyline", tool.start_line),
    "FreeWorks_Centerline": ("Centerline", "Sketches centerlines: the Line tool with For construction on",
                             "Sketcher_CreatePolyline", tool.start_centerline),
    "FreeWorks_MidpointLine": ("Midpoint Line", "Sketches a line from its middle: click the middle, then one end",
                               "Sketcher_CreateLine", tool.start_midpoint_line),
    "FreeWorks_CornerRectangle": ("Corner Rectangle", "Sketches a rectangle from two corners",
                                  "Sketcher_CreateRectangle", tool.start_rectangle),
    "FreeWorks_CenterRectangle": ("Center Rectangle", "Sketches a rectangle from its center and a corner",
                                  "Sketcher_CreateRectangle_Center", tool.start_center_rectangle),
    "FreeWorks_3PointCornerRectangle": ("3 Point Corner Rectangle", "Sketches a rectangle at an angle: two "
                                        "corners, then the width", "Sketcher_CreateRectangle",
                                        tool.start_three_point_corner_rectangle),
    "FreeWorks_3PointCenterRectangle": ("3 Point Center Rectangle", "Sketches a rectangle at an angle from its "
                                        "center: the center, the middle of a side, then a corner",
                                        "Sketcher_CreateRectangle_Center", tool.start_three_point_center_rectangle),
    "FreeWorks_Parallelogram": ("Parallelogram", "Sketches a parallelogram: two corners, then the third",
                                "Sketcher_CreateRectangle", tool.start_parallelogram),
    "FreeWorks_Circle": ("Circle", "Sketches a circle from its center and a point on the rim",
                         "Sketcher_CreateCircle", tool.start_circle),
    "FreeWorks_PerimeterCircle": ("Perimeter Circle", "Sketches a circle through three points on the rim",
                                  "Sketcher_Create3PointCircle", tool.start_perimeter_circle),
    "FreeWorks_CenterArc": ("Centerpoint Arc", "Sketches an arc from its center, start and end",
                            "Sketcher_CreateArc", tool.start_arc),
    "FreeWorks_ThreePointArc": ("3 Point Arc", "Sketches an arc through its two ends and a point on it",
                                "Sketcher_Create3PointArc", tool.start_three_point_arc),
    "FreeWorks_SmartDimension": ("Smart Dimension", "Dimensions what you pick: a line, two lines, a point and a "
                                 "line, a circle, two points, an edge of the part; the next click places it",
                                 "Constraint_Dimension", lambda: tool.start_dimension()),

    # commands that asked the value in FreeCAD's Insert Length dialog at the first pick
    "FreeWorks_HorizontalDimension": ("Horizontal Dimension", "Dimensions the horizontal distance between two points "
                                      "or along a line; the next click places it",
                                      "Constraint_HorizontalDistance", lambda: tool.start_dimension("DistanceX")),
    "FreeWorks_VerticalDimension": ("Vertical Dimension", "Dimensions the vertical distance between two points "
                                    "or along a line; the next click places it",
                                    "Constraint_VerticalDistance", lambda: tool.start_dimension("DistanceY")),
    "FreeWorks_TangentArc": ("Tangent Arc", "Sketches an arc tangent to the end of a line or arc",
                             "Sketcher_CreateArc", tool.start_tangent_arc),
    "FreeWorks_StraightSlot": ("Straight Slot", "Sketches a straight slot from end center to end center, then the width",
                               "Sketcher_CreateSlot", tool.start_slot),
    "FreeWorks_CenterpointStraightSlot": ("Centerpoint Straight Slot", "Sketches a straight slot from its center, "
                                          "an end center, then the width", "Sketcher_CreateSlot",
                                          tool.start_centerpoint_slot),
    "FreeWorks_CenterpointArcSlot": ("Centerpoint Arc Slot", "Sketches an arc slot from its center, the arc's start "
                                     "and end, then the width", "Sketcher_CreateArcSlot", tool.start_arc_slot),
    "FreeWorks_ThreePointArcSlot": ("3 Point Arc Slot", "Sketches an arc slot from the arc's start, end and a point "
                                    "on it, then the width", "Sketcher_CreateArcSlot", tool.start_three_point_arc_slot),
    "FreeWorks_Point": ("Point", "Sketches points: each click places one, with its relations to what it is on",
                        "Sketcher_CreatePoint", tool.start_point),
    "FreeWorks_Ellipse": ("Ellipse", "Sketches an ellipse: the center, the first axis, then the second axis",
                          "Sketcher_CreateEllipseByCenter", tool.start_ellipse),
    "FreeWorks_PartialEllipse": ("Partial Ellipse", "Sketches an elliptical arc: the center, the first axis, the "
                                 "second axis and the start, then the end", "Sketcher_CreateElliptical_Arc",
                                 tool.start_partial_ellipse),
    "FreeWorks_Polygon": ("Polygon", "Sketches a regular polygon from its center; U and J change the number of sides",
                          "Sketcher_CreateRegularPolygon", tool.start_polygon),
    "FreeWorks_Spline": ("Spline", "Sketches a spline through the points you click: double-click or Esc ends it, "
                         "a click on the first point closes it; drag a handle to shape it",
                         "Sketcher_CreateBSpline", tool.start_spline),
    "FreeWorks_StyleSpline": ("Style Spline", "Sketches a spline shaped by its control polygon: click the vertices, "
                              "double-click or Esc ends it; drag a vertex to shape it",
                              "Sketcher_CreateBSpline", tool.start_style_spline),
    "FreeWorks_Extend": ("Extend Entities", "Extends a line or an arc to the next entity it meets: move over it to "
                         "see the extension, click to make it", "Sketcher_Extend", tool.start_extend),
    "FreeWorks_Split": ("Split Entities", "Splits an entity where you click: a circle or ellipse takes two split "
                        "points", "Sketcher_Split", tool.start_split),
    "FreeWorks_Trim": ("Trim Entities", "Trims a curve at its crossings: click the piece to remove (right-click "
                       "options: keep the piece as construction, ignore construction geometry)",
                       "Sketcher_Trimming", tool.start_trim),
}


# Other editing modes that take these commands over (the add-on's 3D sketch): objects with
# claims(name) -> None (not theirs now), True (they run it) or False (greyed there), and run(name).
HOOKS = []


def _hook(name):
    for h in HOOKS:
        try:
            claim = h.claims(name)
        except Exception:
            claim = None
        if claim is not None:
            return h, claim
    return None, None


import time as _time
_LIVE = [0.0, False]           # (when, answer) shared by the sketch tools' IsActive


def sketch_in_edit():
    gdoc = Gui.ActiveDocument
    vp = gdoc.getInEdit() if gdoc else None
    return getattr(vp, "Object", None) is not None and vp.Object.isDerivedFrom("Sketcher::SketchObject")


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.tip, self.icon, self.start = COMMANDS[name]

    def GetResources(self):
        # CmdType ForEdit: FreeCAD disables every command without it while a task panel (the
        # sketch's) is open, whatever IsActive says, so a toolbar or menu button made from these
        # commands would be dead inside a sketch. NoTransaction: a button click runs Activated inside
        # FreeCAD's own AutoTransaction, which on return closed the tool's transaction ("Dimension",
        # "Line"...), so Escape could not take a picked part edge's hidden reference back; the tools
        # keep their own transactions. (Both found 2026-10-30 with real toolbar clicks.)
        return {"Pixmap": self.icon, "MenuText": self.text, "ToolTip": self.tip, "CmdType": "ForEdit NoTransaction"}

    def IsActive(self):
        hook, claim = _hook(self.name)
        if hook is not None:
            return claim

        now = _time.monotonic()
        if now - _LIVE[0] > 0.02:       # one answer for the ~40 tools of one update pass (extapps/61)
            _LIVE[0], _LIVE[1] = now, bool(sketch_in_edit() or sketchfirst.can_start())
        return _LIVE[1]

    def Activated(self):
        hook, claim = _hook(self.name)
        if hook is not None:
            if claim:
                hook.run(self.name)
            return
        if not sketch_in_edit():
            sketchfirst.start_sketch_then(self.name)
            return
        running = tool.active()
        if running is not None and running.title() == self.text:
            running.end()  # the button of the running tool toggles it off
            return
        self.start()


class _ToggleSnaps:
    ""

    def GetResources(self):
        # fix290 (look audit BB37): "Snap_Lock" is Draft's icon, there only once Draft has loaded ("Cannot
        # find icon" without it); the drawn Quick Snaps toggle is always there
        import os as _os
        drawn = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "resources",
                              "icons-drawn", "FW_SWStyle_QuickSnapsToggle.svg")
        return {"Pixmap": drawn if _os.path.isfile(drawn) else "", "MenuText": "Toggle Sketch Snaps",
                "ToolTip": "Turns sketch snapping on or off (F3)", "CmdType": "ForEdit NoTransaction"}

    def IsActive(self):
        return True

    def Activated(self):
        from . import snap
        snap.toggle_snaps()


_registered = False
SWITCH = "User parameter:BaseApp/Preferences/Mod/FreeWorks"


def patched_sketcher():
    """True on a build whose SketcherGui has the C++ snap engine (patch 01's parameter name is
    compiled in); stock FreeCAD has no such name (same check as the add-on's native.py)."""
    try:
        import os
        import SketcherGui
        path = getattr(SketcherGui, "__file__", None)
        if path and os.path.isfile(path):
            with open(path, "rb") as f:
                return b"SnapToIntersections" in f.read()
    except Exception as _fw_err:
        _fw_log("fwsketch/commands.py:183", _fw_err)
    return False


def wanted():
    ""


    import FreeCAD as App
    grp = App.ParamGet(SWITCH)
    if grp.GetBool("PythonSketchToolsSet", False):
        return grp.GetBool("PythonSketchTools", True)
    return not patched_sketcher()


def register(force=False):
    """Add the commands when wanted() (or force). Returns True when they are registered."""
    global _registered
    if _registered:
        return True
    if not force and not wanted():
        return False
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    if "FreeWorks_ToggleSketchSnaps" not in Gui.listCommands():
        Gui.addCommand("FreeWorks_ToggleSketchSnaps", _ToggleSnaps())
    from . import curvelength, dimedit, dragwatch, glyphs, modelpick, overdefined, splinehandles
    glyphs.install()
    dragwatch.start()    # drag to connect goes with the tools
    from . import toolbase
    toolbase._watch_steps()   # Undo under a running tool; a stale selection after Undo
    try:

        from .. import checkstate
        checkstate.register("Sketcher_LeaveSketch", lambda: bool(sketch_in_edit()))
        from .. import sketch3d as _s3d
        checkstate.register("FreeWorks_Sketch3DExit", lambda: _s3d.editing() is not None)
    except Exception as error:
        import FreeCAD as App
        App.Console.PrintLog("FreeCAD: Exit Sketch pressed look: %s\n" % error)
    try:
        from . import undoclose
        undoclose.start()    # one Ctrl+Z after closing a sketch undoes the change (fix229)
    except Exception as error:
        import FreeCAD as App
        App.Console.PrintLog("FreeCAD: undo after closing a sketch: %s\n" % error)
    overdefined.start()  # the over-defined look too
    dimedit.start()      # double-click on a dimension: the Modify box
    try:
        from . import pointtriad
        pointtriad.start()
    except Exception as error:
        import FreeCAD as App
        App.Console.PrintLog("FreeCAD: spline point triad: %s\n" % error)
    try:
        from . import groupadd
        groupadd.start()     # Ctrl-pick a group's relation icon: the picked entity joins the group
    except Exception as error:
        import FreeCAD as App
        App.Console.PrintLog("FreeCAD: relation groups: %s\n" % error)
    modelpick.start()    # part edges and corners can be picked in a sketch
    curvelength.start()  # Equal Curve Length's lines follow their arcs (stock stand-in)
    splinehandles.start()  # a picked spline shows its tangent handles
    try:
        from . import selcolour
        selcolour.start()  # picked sketch entities light blue while sketching
    except Exception as error:
        import FreeCAD
        FreeCAD.Console.PrintWarning("FreeCAD: sketch selection colour: %s\n" % error)
    from . import ctrlcopy
    ctrlcopy.start()
    from . import virtualsharps
    virtualsharps.start()  # virtual sharps in the Document Properties > Virtual Sharps style
    from . import bigsketch
    bigsketch.start()      # Options > Sketch: Automatic Solve and Undo off in very big sketches
    from . import exprkeep
    exprkeep.start()       # expressions on dimensions follow them when constraints are deleted
    try:
        from .. import intersectioncurve
        intersectioncurve.register()
    except Exception as error:
        import FreeCAD
        FreeCAD.Console.PrintWarning("FreeCAD: Intersection Curve not added: %s\n" % error)
    try:
        from .. import sketchplane
        sketchplane.register()
    except Exception as error:
        import FreeCAD
        FreeCAD.Console.PrintWarning("FreeCAD: Edit Sketch Plane not added: %s\n" % error)
    from . import pointshow
    pointshow.start()      # Options > Sketch: arc centrepoints and entity points shown or not
    from . import splinecommands
    splinecommands.register()  # Insert Spline Point, Simplify, Relax, Proportional, the Show entries
    _registered = True
    return True
