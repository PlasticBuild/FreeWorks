# SPDX-License-Identifier: LGPL-2.1-or-later
""














import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

_SEEN = set()


def _log(site, err):
    if site not in _SEEN:
        _SEEN.add(site)
        try:
            App.Console.PrintLog("FreeCAD help %s: %s\n" % (site, err))
        except Exception:
            pass


def _esc(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------- which commands
def _part_tabs():
    from . import catalog
    try:
        from . import asmui
        part = getattr(asmui, "_part_tabs", None)
        if part:
            return tuple(part)
    except Exception as err:
        _log("part tabs", err)
    return tuple(catalog.TABS)


def tab_rows():
    """[(mode, tab title, [catalog keys])] for the part, assembly and drawing tab rows, each key once
    per mode, in the order the buttons show."""
    from . import catalog
    part = _part_tabs()
    modes = [("part", part)]
    try:
        from . import asmui
        modes.append(("assembly", tuple(asmui.assembly_tabs(part))))
    except Exception as err:
        _log("assembly tabs", err)
    try:
        if hasattr(catalog, "drawing_tabs"):
            modes.append(("drawing", tuple(catalog.drawing_tabs(part))))
    except Exception as err:
        _log("drawing tabs", err)
    out = []
    for mode, tabs in modes:
        seen = set()
        for title, spec in tabs:
            keys = []

            def walk(s):
                if isinstance(s, str):
                    if s in catalog.BY_KEY and s not in seen:
                        seen.add(s)
                        keys.append(s)
                elif isinstance(s, (tuple, list)):
                    for x in s:
                        walk(x)
            walk(spec)
            if keys:
                out.append((mode, title, keys))
    return out


def all_keys():
    """Every CommandManager command key, once, with the first (mode, tab) it shows on."""
    out = {}
    for mode, title, keys in tab_rows():
        for k in keys:
            out.setdefault(k, (mode, title))
    return out


# --------------------------------------------------------------------------- the text
GUIDE_TAB = {
    "Features": ("04-features.html", "adding-and-removing-material"),
    "Sketch": ("03-sketching.html", "drawing-tools"), "Sketch Ink": ("03-sketching.html", "drawing-tools"),
    "Surfaces": ("04-features.html", "surfaces-direct-editing-and-more"),
    "Direct Editing": ("04-features.html", "surfaces-direct-editing-and-more"),
    "Mold Tools": ("04-features.html", "surfaces-direct-editing-and-more"),
    "Sheet Metal": ("04-features.html", "sheet-metal"), "Weldments": ("04-features.html", "weldments"),
    "Structure System": ("04-features.html", "weldments"), "Evaluate": ("04-features.html", "evaluate"),
    "Assembly": ("05-assemblies.html", "starting-an-assembly"), "Drawing": ("06-drawings.html", "views"),
    "Annotation": ("06-drawings.html", "dimensions-and-annotations"), "Sheet Format": ("06-drawings.html", "sheets"),
    "3D Slicer": ("07-slicer.html", "sending-a-part"),
}
GUIDE_MODE = {"part": ("04-features.html", ""), "assembly": ("05-assemblies.html", ""), "drawing": ("06-drawings.html", "")}

# PropertyManager titles (pmhelp.HELP) of commands whose button name differs
PM_TITLE = {
    "Extruded Boss/Base": "Boss-Extrude", "Extruded Cut": "Cut-Extrude", "Revolved Boss/Base": "Revolve",
    "Revolved Cut": "Cut-Revolve", "Swept Boss/Base": "Sweep", "Swept Cut": "Cut-Sweep",
    "Lofted Boss/Base": "Loft", "Lofted Cut": "Cut-Loft", "Hole Wizard": "Hole Specification",
    "Helix and Spiral": "Helix/Spiral", "Boundary Boss/Base": "Boundary Boss/Base",
    "Extruded Surface": "Surface-Extrude", "Revolved Surface": "Surface-Revolve", "Swept Surface": "Surface-Sweep",
    "Lofted Surface": "Surface-Loft", "Boundary Surface": "Boundary-Surface", "Offset Surface": "Offset Surface",
    "Knit Surface": "Knit Surface", "Filled Surface": "Fill Surface", "Linear Pattern": "Linear Pattern", "Circular Pattern": "Circular Pattern",
    "Reference Geometry Copy": None,
}

# Hand-written steps for commands that open no page of their own in pmhelp.HELP
STEPS = {
    "MirrorBody": ["Pick a plane or a flat face to mirror about, then the body to copy.",
                   "OK adds the mirrored copy; Merge solids joins it to the body it touches."],
    "CenterOfMass": ["Click it with a part open: a point is added at the part's centre of mass.",
                     "The point moves with the part as it changes; delete it from the tree when you no longer need it."],
    "MateReference": ["Pick the faces, edges or vertices that will mate to other parts, and name the reference.",
                      "When the part goes into an assembly, those references mate first."],
    "ShapeBinder": ["Pick the faces, edges or sketches of another body or part to copy.",
                    "The copy follows the original; use it as a reference in this body."],
    "Curves": ["Opens the list of curve tools: Split Line, Projected Curve, Composite Curve, Curve Through "
               "Points, Helix and Spiral."],
    "CurveThroughXYZPoints": ["Type the X, Y and Z of each point in the table, or open a text file of points.",
                              "OK makes a smooth 3D curve through them, in order."],
    "Instant3D": ["Click to turn it on or off. While it is on, pick a face or a feature in the graphics area and drag "
                  "its arrow handles to change it; the ruler shows the value as you drag."],
    "ShadedSketchContours": ["Click to turn it on or off. While it is on, the closed areas of the sketch being edited "
                             "are shaded, so you can see which areas are closed."],
    "RapidSketch": ["Click to turn it on, then pick a plane or a flat face and start a sketch tool: the sketch opens "
                    "on the face without Edit Sketch first."],
    "Instant2D": ["Click to turn it on or off. While it is on, drag a dimension's handle in the sketch to change "
                  "its value directly."],
    "FullyDefineSketch": ["Opens a page that adds the relations and dimensions still missing, so the sketch becomes "
                          "fully defined (it turns black). Choose which relations and dimension style to use, then OK."],
    "Relations": ["Lists the relations of the sketch. Pick a filter to choose which ones show; a click on one "
                  "shows its entities in pink. Delete, Delete All and Suppressed act on the list."],
    "AddRelation": ["Pick the sketch entities first; the page offers only the relations that fit them. A click "
                    "adds one."],
    "RepairSketch": ["Finds small gaps, overlaps and duplicate entities in the sketch being edited and fixes them, "
                     "so its contours close."],
    "DeleteAllRelations": ["Takes every relation off the sketch being edited, in one step that Undo takes back."],
    "ConflictingRelations": ["Picks the relations that conflict, so you can see and delete them."],
    "RedundantRelations": ["Picks the relations that are not needed because others already hold the geometry."],
    "Sketch3D": ["Click it to start a 3D sketch, or pick one and click it to edit it. Draw with the sketch tools; "
                 "the Tab key changes which plane the next lines lie in.",
                 "Leave it with Exit Sketch in the confirmation corner at the top right."],
    "Measure": ["Click it, then pick faces, edges or points in the graphics area: the Measure window shows "
                "distances, angles, lengths and areas between them. Esc or the cross closes it."],
    "MassProperties": ["Click it with a part or assembly open: a window lists mass, volume, surface area, centre of "
                       "mass and the moments of inertia, using the material's density.",
                       "Pick bodies or components first to measure only those."],
    "SectionProperties": ["Pick a flat face, a planar section or a closed sketch: the window lists its area, "
                          "centroid and second moments of area."],
    "Interference": ["Pick the components to check (all of them by default), then Calculate: the clashes are "
                     "listed and shown in the graphics area."],
    "Zebra": ["Click to turn it on or off: stripes run over the faces so you can see where they meet smoothly."],
    "Curvature": ["Click to turn it on or off: faces are coloured by how tightly they curve."],
    "DraftAnalysis": ["Pick the pull direction and set the draft angle: faces are coloured by whether they have "
                      "enough draft to come out of a mould."],
    "ThicknessAnalysis": ["Set the target thickness, then Calculate: thin and thick areas are coloured on the part."],
}

FAMILY = {
    "dimension": ["Pick the entities to dimension (a line, two points, an arc...), then click where the "
                  "dimension goes.", "Type the value in the box that opens and press Enter: the sketch follows "
                  "the new value."],
    "snap": ["With a sketch tool running, choose this snap: the next point snaps only to that kind of place.",
             "Quick Snaps on the Sketch tab and the right-click menu hold the same list."],
    "relation": ["Pick the sketch entities first, then click the relation: it is added and its glyph shows next "
                 "to them.", "To take it off, right-click the glyph and choose Delete."],
    "entity": ["Click in the graphics area to place the points; the PropertyManager on the left shows the values "
               "as you go and takes typed values.", "Esc ends the tool; relations are added as you snap."],
    "sketchtool": ["Pick the sketch entities to work on, set the values in the PropertyManager, then OK."],
    "toggle": ["Click to turn it on or off; the button shows pressed while it is on."],
    "evaluate": ["Click it with a document open. If a PropertyManager opens, pick what to check there; the "
                 "results show in the panel or in the graphics area."],
    "feature": ["Click the button: its PropertyManager opens on the left. Fill the boxes from the top down "
                "(the pink box takes what you click in the graphics area or the tree).",
                "OK (the check) makes the feature; Cancel (the cross) leaves the part as it was."],
    "assembly": ["Click the button with an assembly open. If a PropertyManager opens, fill it from the top down "
                 "and click OK."],
    "drawing": ["Click the button with a drawing open. If a PropertyManager opens, pick the view or entity it asks "
                "for and click OK."],
    "drawdim": ["Pick the edges, points or circles in a drawing view, then click where the dimension goes on "
                "the sheet."],
    "menu": ["Click it to open its list, then pick the command you want."],
    "app": ["Click the button: it opens its own panel or window. Follow it from the top down."],
}

RELATION_KEYS = ("Horizontal", "Vertical", "Parallel", "Perpendicular", "Tangent", "Equal", "Symmetric", "Fix",
                 "Coincident", "Collinear", "Concentric", "Coradial", "Midpoint", "Merge", "Pierce")
SKETCH_TOOL_WORDS = ("Fillet", "Chamfer", "Split", "Join", "Pattern", "Move", "Copy", "Rotate", "Scale", "Stretch",
                     "Offset", "Convert", "Silhouette", "Intersection", "Trim", "Extend", "Mirror", "Segment")
APP_TABS = ("Add-Ins", "Simulation", "CAM", "Flow Simulation", "MBD", "MBD Dimensions", "Diotopo", "ScanRuler",
            "CircuitWorks", "Analysis Preparation", "3D Slicer", "Markup", "Freeshape")
EVAL_MAKES = ("DesignStudy", "Sensor")


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _checkable(cmd):
    try:
        for name in cmd.natives:
            c = Gui.Command.get(name)
            if c is None:
                continue
            act = c.getAction()
            if act and act[0].isCheckable():
                return True
    except Exception as err:
        _log("checkable", err)
    return False


def pm_text(label):
    """(what, steps) of the PropertyManager page the command opens, from pmhelp.HELP, or None."""
    try:
        from . import pmhelp
    except Exception:
        return None
    if label in PM_TITLE:
        title = PM_TITLE[label]
        return pmhelp.HELP.get(title) if title else None
    if label in pmhelp.HELP:
        return pmhelp.HELP[label]
    n = _norm(label)
    for title, text in pmhelp.HELP.items():
        if _norm(title) == n:
            return text
    return None


TOGGLE_WORDS = ("Do not ", "Hide all ", "Disable ", "Optimize ", "Suspend ")
_SKETCH_KEYS = []


def _sketch_keys():
    """Keys of the Sketch tabs' commands, and of buttons elsewhere with the same name (Basic Modeling Tools)."""
    if not _SKETCH_KEYS:
        from . import catalog
        keys = set()
        rows = tab_rows()
        for _mode, title, ks in rows:
            if title in ("Sketch", "Sketch Ink"):
                keys.update(ks)
        labels = set(catalog.BY_KEY[k].label for k in keys) - {"Point", "Sketch"}
        for _mode, title, ks in rows:
            keys.update(k for k in ks if catalog.BY_KEY[k].label in labels)
        _SKETCH_KEYS.append(keys)
    return _SKETCH_KEYS[0]


def family(key, cmd, mode, tab):
    label = cmd.label
    if cmd.call in ("menu", "scene_menu"):
        return "menu"
    if label.startswith(TOGGLE_WORDS):
        return "toggle"
    if mode == "drawing" and "Dimension" in label and tab != "MBD Dimensions":
        return "drawdim"
    if label == "Smart Dimension":
        return "dimension"
    if tab in ("Sketch", "Sketch Ink") or key in _sketch_keys():
        if "Dimension" in label:
            return "dimension"
        if key.startswith("QS") or key == "QuickSnaps":
            return "snap"
        if key in RELATION_KEYS:
            return "relation"
        if _checkable(cmd):
            return "toggle"
        if any(w in label for w in SKETCH_TOOL_WORDS):
            return "sketchtool"
        return "entity"
    if _checkable(cmd):
        return "toggle"
    if tab == "Evaluate":
        return "feature" if key in EVAL_MAKES else "evaluate"
    if tab in APP_TABS:
        return "app"
    if mode == "assembly":
        return "assembly"
    if mode == "drawing":
        return "drawing"
    return "feature"


# Hand-written steps of the most-used drawing commands (what each one does here, in our own words)
STEPS.update({
    "DrawModelView": [
        "Pick the part or assembly in the list of open documents, or Browse... for a file, then click "
        "Next >.",
        "Pick a view in Orientation (Front, Top, Isometric and so on). Create multiple views places several at once.",
        "Set the Display Style and the Scale, then click on the sheet where the view goes.",
        "With Auto-start projected view on, move the pointer away from the view and click to add projected views "
        "of it; OK when you have enough.",
    ],
    "DrawProjectedView": [
        "Click the view to project from (or pick it first, then the command).",
        "Move the pointer to the side, above or below it: the preview shows the view from that direction.",
        "Click to place it. It lines up with its parent and uses the parent's scale and display style until you "
        "change them in the PropertyManager.",
    ],
    "DrawSectionView": [
        "Pick the cutting line type: Vertical, Horizontal, Auxiliary or Aligned (or a Half Section shape).",
        "Click in a view to place the cutting line; it snaps to centres and edges. A pop-up offers offsets "
        "(arc, single or notch) before you go on.",
        "Click OK in the pop-up, then click where the section view goes. Flip Direction turns the arrows round.",
        "Set the hatch, Partial section, Slice section or Section depth in the PropertyManager, then OK.",
    ],
    "DrawDetailView": [
        "Click in a view for the centre of the detail circle, then click again to set its size (or pick "
        "Profile and click the corners of your own outline).",
        "Click on the sheet where the detail view goes.",
        "Set its scale (parent, sheet or your own), its outline and its label in the PropertyManager, then OK.",
    ],
    "DrawNote": [
        "Pick a leader type in Leader. No Leader gives plain text; Auto Leader adds one only when you start on a view.",
        "With a leader, click where it points, then where the note goes; without one, just click where the note goes.",
        "Type the text in the Text box. Text Format sets the font, and adds symbols, "
        "geometric tolerances, hole callouts or links to properties.",
        "The tool stays on for the next note: OK or Esc ends it.",
    ],
    "DrawBalloon": [
        "Click on a part in a view, then click where the balloon goes. It shows the part's item number from the "
        "Bill of Materials (add one first to number balloons in order).",
        "Settings chooses the shape, the size and what it shows (item number, quantity, text, a custom property "
        "or the file name).",
        "The tool stays on: click the next part, then OK. Auto Balloon does every part of a view at once.",
    ],
    "DrawBOM": [
        "Click a view of the assembly (or part) for its Bill of Materials.",
        "Choose the BOM type (Top-level only, Parts only or Indented), the template and the item numbers' "
        "start and step.",
        "With Attach to anchor point on, the table goes to the sheet's table anchor; otherwise click where it goes.",
        "Double-click a cell to edit it; right-click the table for its insert, sort and format commands.",
    ],
    "DrawHoleCallout": [
        "Click the edge of a hole in a view, then click where the callout goes.",
        "The callout lists the hole's size, depth and thread for a Hole Wizard hole, and the diameter for other "
        "round edges. Once it is placed, Callout variables... puts a value (depth, counterbore, thread...) into "
        "its text.",
        "Change the tolerance, precision and text in the PropertyManager. The tool stays on for the next hole: "
        "OK or Esc ends it.",
    ],
})

# Hand-written steps of the sketch tools. Every drawing tool snaps and adds relations as it goes:
_SNAP = ("As you click, the point snaps to nearby points, midpoints, curves and model edges; the yellow square "
         "by the pointer shows the relation the click adds (Ctrl+click: none).")
_OPTS = "For construction makes it construction geometry. Esc ends the tool."


def _ent(*clicks, extra=None):
    return list(clicks) + ([extra] if extra else []) + [_SNAP, _OPTS]


STEPS.update({
    # ---- sketch entities
    "Line": _ent("Click the start, then click each corner: the line chains on. Press, drag and release for a single "
                 "line instead.",
                 "Move back to the last end and away again for an arc (A switches); click the first point to close "
                 "the shape; double-click ends the chain.",
                 extra="Orientation (As sketched, Horizontal, Vertical, Angle) and Infinite length are in the "
                       "PropertyManager."),
    "Centerline": _ent("Click the start, then the end: a construction line used for mirrors, revolves and "
                       "symmetric relations. Keep clicking to chain."),
    "MidpointLine": _ent("Click the middle of the line, then one end: the other end mirrors it."),
    "CornerRectangle": _ent("Click the first corner, then the opposite corner.",
                            extra="The rectangle's sides get Horizontal and Vertical relations; the type buttons "
                                  "at the top of the PropertyManager switch to the other rectangles."),
    "CenterRectangle": _ent("Click the centre, then a corner.",
                            extra="Add construction lines draws its diagonals from the centre."),
    "ThreePointCornerRectangle": _ent("Click the first corner, then the second (this sets the angle), then the width."),
    "ThreePointCenterRectangle": _ent("Click the centre, then the middle of a side (this sets the angle), then a "
                                      "corner."),
    "Parallelogram": _ent("Click the first corner, the second, then the third: the fourth follows."),
    "Slot": _ent("Click the start of the slot's centre line, then its end, then move out and click for the width.",
                 extra="Add dimensions puts the length and width on as you place it."),
    "CenterpointSlot": _ent("Click the slot's centre, then one end, then move out and click for the width."),
    "ThreePointArcSlot": _ent("Click three points on the slot's centre arc, then move out and click for the width."),
    "ArcSlot": _ent("Click the centre of the arc, then the radius and start, then the angle, then the width."),
    "Circle": _ent("Click the centre, then move out and click for the radius.",
                   extra="Type the radius in Parameters to set it exactly."),
    "PerimeterCircle": _ent("Click three points on the rim: the circle runs through them."),
    "CenterArc": _ent("Click the centre, then the start of the arc, then its end."),
    "ThreePointArc": _ent("Click the start, then the end, then a third point that sets how far the arc bows out."),
    "TangentArc": _ent("Click the end of a line or arc: the new arc leaves it tangent. Click where the arc ends.",
                       extra="While drawing lines, M switches between line and arc."),
    "Polygon": _ent("Click the centre, then move out and click to set the size and the rotation.",
                    extra="Set the number of sides (U and J add and take away one) and Inscribed or Circumscribed "
                          "circle first."),
    "Ellipse": _ent("Click the centre, then the end of the first axis, then the second axis."),
    "PartialEllipse": _ent("Click the centre, then the first axis, then the second axis and the start of the arc, "
                           "then its end."),
    "Parabola": _ent("Click the focus, then the top of the parabola, then its two ends."),
    "Conic": _ent("Click the start and the end, then the top vertex, then move to set Rho (0.5 is a parabola, "
                  "less is an ellipse, more a hyperbola) and click."),
    "Spline": _ent("Click the points the spline runs through. Double-click (or Esc) ends it.",
                   extra="Afterwards drag its points and handles to reshape it."),
    "StyleSpline": _ent("Click the corners of the control polygon; the curve follows inside it. Double-click ends it."),
    "SplineOnSurface": ["Click points on a model face: the spline is drawn on the face. A 3D sketch starts when "
                        "none is open.", _OPTS],
    "EquationDrivenCurve": ["Choose Explicit (y as a function of x) or Parametric (x and y as functions of t), type "
                            "the equation and the start and end values, then OK."],
    "SketchPoint": _ent("Click where each point goes. Esc ends the tool."),
    "Text": ["Type the text and set the font, height, spacing, angle and position, then OK: its outlines go into "
             "the sketch, ready to extrude.", "Pick any part of a text and click it again to change it."],
    "Sketch": ["Pick a plane or a flat face, then click it: the sketch opens looking straight at it. With nothing "
               "picked, you are asked to pick one.",
               "Leave with Exit Sketch in the corner at the top right, or Esc twice."],
    "EditSketch": ["Pick a sketch or a feature made from one in the tree, then click it: the sketch opens to change it."],
    "Sketch3DPlane": ["In a 3D sketch, pick the points, lines or model plane it goes through, then OK: a sketch "
                      "plane is added. Double-click it (or Tab) to sketch on it."],
    "ScanEqual": ["Click it in a sketch: lines of the same length and circles or arcs of the same radius are listed.",
                  "Pick a set and click Set Equal, or Set All Equal; relations that would over-define are skipped."],
    "NormalTo": ["Pick a face or a plane (or nothing, in a sketch), then click it or press Ctrl+8: the view turns to "
                 "look straight at it. A second press looks from the other side; with two faces picked, the second "
                 "one faces up."],
    # ---- sketch tools
    "Trim": ["Power Trim (the default): drag the pointer across the bits to remove.",
             "Or pick another mode in the PropertyManager (Corner, Trim away inside or outside, Trim to closest) and "
             "click the entities.",
             "Keep trimmed entities as construction geometry keeps them as construction lines."],
    "Extend": ["Hover over a line or arc near the end to extend: a preview shows where it reaches. Click to extend "
               "it to the next entity. Esc ends the tool."],
    "Offset": ["Pick the entities, edges or faces, then set the distance (Select chain takes the whole connected "
               "chain).", "Reverse flips the side, Bi-directional offsets both ways and Cap ends closes the ends; "
               "Add dimensions puts the distance on. Then OK."],
    "Convert": ["Pick model edges, faces or other sketches' entities, then OK: they are copied into the sketch and "
                "stay linked to the model."],
    "MirrorEntities": ["Pick the entities to mirror, then the centerline or line to mirror about.",
                       "Copy keeps the originals; the copies get Symmetric relations. Then OK."],
    "MoveEntities": ["Pick the entities, then a base point and where it goes (or type X and Y). Keep relations "
                     "holds what they are tied to. Then OK."],
    "CopyEntities": ["Pick the entities, then a base point and where the copy goes (or type X and Y). Then OK."],
    "RotateEntities": ["Pick the entities, then the centre of rotation, and type the angle or drag. Then OK."],
    "ScaleEntities": ["Pick the entities, then the base point, and type the scale factor. Copy makes scaled copies. "
                      "Then OK."],
    "StretchEntities": ["Pick the entities, then the base point and where it goes: the points picked move, the rest "
                        "stay, and relations hold. Then OK."],
    "LinearSketchPattern": ["Pick the entities to repeat, then set the spacing, count and angle in each direction "
                            "(or drag the handles). Then OK."],
    "CircularSketchPattern": ["Pick the entities to repeat and the centre (the sketch origin by default), then set "
                              "the count and the angle. Then OK."],
    "SketchFillet": ["Pick two entities that meet, or their corner point, and set the radius. Keep constrained "
                     "corners keeps the corner's relations; Dimension each fillet adds a radius to each. Then OK."],
    "SketchChamfer": ["Pick two entities that meet, or their corner point, and set the chamfer's size. Then OK."],
    "Split": ["Click on a sketch entity where it should split: it becomes two at that point. Esc ends the tool."],
    "Join": ["Pick two curves that touch end to end, then click it: they become one."],
    "IntersectionCurve": ["Pick the faces, planes or bodies, then click it: the curves where they meet the sketch "
                          "plane (or each other, in a 3D sketch) are sketched."],
    "SilhouetteEntities": ["Pick the body (or faces), then OK: its outline as seen square to the sketch is sketched."],
    "OffsetOnSurface": ["In a 3D sketch pick edges or faces, then set the distance: the offset stays on the faces. "
                        "Then OK."],
    "CarbonCopy": ["Click it, then pick another sketch: its geometry is copied into this one and follows it."],
    # ---- relations (pick first)
    "Horizontal": ["Pick lines (or two points), then click it: they become horizontal. The sketch adds this one "
                   "itself when you draw a line close to level."],
    "Vertical": ["Pick lines (or two points), then click it: they become vertical. The sketch adds this one itself "
                 "when you draw a line close to plumb."],
    "Parallel": ["Pick two or more lines, then click it: they become parallel."],
    "Perpendicular": ["Pick two lines, then click it: they meet at a right angle."],
    "Tangent": ["Pick a line or arc and a curve that touch, then click it: they meet smoothly."],
    "Equal": ["Pick lines (same length) or circles and arcs (same radius), then click it."],
    "Symmetric": ["Pick two points or entities and a centerline, then click it: they mirror each other about it."],
    "Fix": ["Pick an entity or point, then click it: it is held where it is."],
    # ---- dimensions
    "SmartDimension": ["Click one entity (a line for its length, a circle for its diameter, an arc for its radius), "
                       "or two (the distance or angle between them).",
                       "Click where the number goes, type the value (units and sums work) and press Enter.",
                       "The first dimension scales the whole sketch in proportion. One that would over-define the "
                       "sketch asks whether to make it a driven (reference) dimension. " ],
    "HorizontalDimension": ["Click a line or two points, then where the number goes, and type the value: only the "
                            "horizontal distance is measured."],
    "VerticalDimension": ["Click a line or two points, then where the number goes, and type the value: only the "
                          "vertical distance is measured."],
    "AngularDimension": ["Click two lines (or three points, the corner first), then where the angle goes, and type "
                         "the value. Where you click picks which angle."],
    "RadiusDimension": ["Click a circle or an arc, then where the number goes, and type the value. The PropertyManager "
                        "switches between radius and diameter."],
    "OrdinateDimension": ["Select the zero point (a line, point, circle or arc), then each entity to dimension from it.",
                          "Choose Horizontal or Vertical. The check mark or Esc ends the tool."],
    "HorizontalOrdinateDimension": ["Select the zero point, then each entity: horizontal dimensions from the zero "
                                    "are added. The check mark or Esc ends the tool."],
    "VerticalOrdinateDimension": ["Select the zero point, then each entity: vertical dimensions from the zero are "
                                  "added. The check mark or Esc ends the tool."],
    "BaselineDimension": ["Select the baseline (a line, point, circle or arc), then each entity to dimension from it.",
                          "Choose Horizontal or Vertical. The check mark or Esc ends the tool."],
    "ChainDimension": ["Select where the chain starts, then each entity in turn: each dimension runs from the one "
                       "before. The check mark or Esc ends the tool."],
    "AngularRunningDimension": ["Select the line at 0 degrees, then the other lines: each angle is measured from it. "
                                "The check mark or Esc ends the tool."],
    "ChamferDimension": ["Select the chamfer (a sketch line) and the line it leads from: its length and angle are "
                         "added."],
    "SymmetricLinearDiameterDimension": ["Select the centerline first, then a point, line or circle beside it: the "
                                         "full width across the centerline is added, as on a revolve profile."],
    "PathLengthDimension": ["Pick the chain of sketch entities, then click it and type the total length (or leave it "
                            "driven to read it)."],
    # ---- Quick Snaps
    "QuickSnaps": ["Click it (or press F3) to switch all sketch snapping off or on; the status bar says which.",
                   "Its arrow lists the Quick Snaps, each one the only snap for the next entity."],
})
for _k, _what in (("QSPoint", "end points and sketch points"), ("QSCenterPoint", "the centres of circles and arcs"),
                  ("QSMidpoint", "the middles of lines and arcs"), ("QSQuadrant", "the quadrants of circles"),
                  ("QSIntersection", "where two curves cross"), ("QSNearest", "the nearest point on a curve"),
                  ("QSTangent", "tangent to circles and arcs"), ("QSPerpendicular", "square to lines"),
                  ("QSParallel", "parallel to lines"), ("QSHV", "horizontal and vertical directions"),
                  ("QSHVPoint", "level or plumb with woken points"), ("QSLength", "lengths in grid steps"),
                  ("QSGrid", "the grid"), ("QSAngle", "angles in steps (45 degrees by default)")):
    STEPS[_k] = ["While a sketch tool runs, click it: for the next entity the pointer snaps only to %s. Then every "
                 "snap comes back as it was." % _what, "Click it again to cancel."]

# Hand-written steps of the features (sheet metal, weldments, structure system, surfaces)
STEPS.update({
    "SM_BaseFlange": ["Pick a sketch (or start inside one), then click it. With nothing picked, pick a plane or flat "
                      "face: a sketch opens there and the PropertyManager opens when you close it.",
                      "A closed profile makes a flat plate; an open one is thickened and pulled out by Direction 1. "
                      "Set the sheet thickness and bend radius in Sheet Metal Parameters, then OK."],
    "SM_BaseShape": ["Click it, pick the shape (box, channel, angle, hat) and type its few sizes, then OK: a ready sheet "
                     "metal part is made."],
    "SM_EdgeFlange": ["Pick edges of the sheet metal part (before or after clicking it).",
                      "Set the angle, the length (and whether it is measured to the outer or inner virtual sharp) and "
                      "the flange position, then OK. The radius and relief start from the part's values."],
    "SM_MiterFlange": ["Pick a straight edge of the sheet: a sketch opens square to it. Sketch the flange profile "
                       "starting at the edge and close the sketch.",
                       "Pick more edges for the flange to run round (mitred corners), set the gap and offsets, then OK."],
    "SM_Hem": ["Pick edges of the sheet metal part, then choose the type (Closed, Open, Tear Drop or Rolled) and its "
               "length, gap or radius, and the position, then OK."],
    "SM_SweptFlange": ["Pick an open sketch for the profile, then a sketch or edges of the sheet for the path, then OK."],
    "SM_LoftedBend": ["Pick the two open profile sketches, choose Bent (facets) or Formed (smooth), set the thickness, "
                      "then OK."],
    "SM_Jog": ["Sketch one line on a face of the sheet and pick it, then click it. Pick the fixed face (the side that "
               "stays), set the offset, the position and the angle, then OK."],
    "SM_SketchedBend": ["Sketch the bend line on a face of the sheet and pick it, then click it. Pick the fixed face, "
                        "set the angle, radius and bend position, then OK."],
    "SM_Convert": ["Click it on a solid, pick the fixed face, set the thickness and bend radius, then pick the edges "
                   "that become bends. Corners that are not bends are ripped. Then OK."],
    "SM_InsertBends": ["Click it on a thin (shelled) part, pick the fixed face and set the bend radius: bends are added "
                       "at its sharp edges. Rip the corners first if they are closed."],
    "SM_Rip": ["Pick the inside or outside corner edges where two walls meet, set the rip gap, then OK."],
    "SM_NoBends": ["Click it on a part made with Insert Bends: it rolls back to before the bends so the solid can be "
                   "changed. Click again to put the bends back."],
    "SM_Flatten": ["Click it: the part shows as its flat pattern, with bend lines and the bounding box. Click it again "
                   "to fold it back."],
    "SM_Unfold": ["Pick the fixed face, then the bends to unfold (or Collect All Bends), then OK. Cut across the "
                  "flattened bends, then Fold them back."],
    "SM_Fold": ["After cutting across unfolded bends, click it, pick the fixed face and the bends to fold (or "
                "Collect All Bends), then OK."],
    "SM_UnfoldUpdate": ["Click it after the part changed: the unfolded pattern is made again."],
    "SM_NewSketch": ["Pick a face of the sheet metal part, then click it: a sketch opens on it, ready for a sheet "
                     "metal feature."],
    "SM_BendNotch": ["Pick bend lines (or Collect All Bends), choose the notch shape and its width and depth, then OK. "
                     "The notches show on the flat pattern only."],
    "SM_BreakCorner": ["Pick corner edges (the short edges through the thickness) or flange faces, choose Chamfer or "
                       "Fillet and its size, then OK."],
    "SM_ClosedCorner": ["Pick the end face of a flange at an open corner: the flange it meets is found. Choose Butt, "
                        "Overlap or Underlap and the gap, then OK."],
    "SM_Corners": ["Opens the corner tools: Closed Corner, Welded Corner, Break-Corner and Corner Relief."],
    "SM_CornerRelief": ["Choose 2 Bend or 3 Bend Corner, then Collect all corners (or pick the faces at one corner "
                        "and New Corner), pick each corner's relief type and size, then OK."],
    "SM_WeldedCorner": ["Pick a side face of a closed corner's gap (and a stopping point if needed), then OK: the gap "
                        "is filled with weld. Add fillet and Add weld symbol are options."],
    "SM_CrossBreak": ["Pick a flat rectangular face, set the break radius and angle (Reverse direction flips it), "
                      "then OK."],
    "SM_FormingTool": ["On a solid that is not sheet metal it makes the part a forming tool: pick the stopping face and "
                       "the faces to remove.",
                       "On a sheet metal part it applies a forming tool from the open documents: pick the face, the "
                       "angle and the positions, then OK."],
    "SM_Gusset": ["Pick the faces either side of a bend, then set the indent depth (or the profile sizes) and the "
                  "rib's width, then OK."],
    "SM_Stamp": ["Pick a closed sketch on a face of the sheet (or a face, to sketch one), then set the depth, draft and "
                 "radii, then OK."],
    "SM_NormalCut": ["Pick a face of a cut (Auto Propagation collects the whole cut), then OK: its walls become square "
                     "to the sheet."],
    "SM_TabAndSlot": ["Pick the tab edge, then the face the slots go in. Set the number or spacing of the tabs and "
                      "their size, then OK."],
    "SM_Vent": ["Pick the closed boundary of a vent sketch, then its ribs, spars and fill-in boundary, and set the "
                "widths and the face, then OK."],
    "WE_Weldment": ["Click it: the part becomes a weldment with a cut list. The first Structural Member does this too."],
    "WE_StructuralMember": ["Pick the profile (standard, type and size), then the sketch segments it runs along. "
                            "Connected segments get the corner treatment (miter or butt). Then OK."],
    "WE_TrimExtend": ["Choose the corner type, pick the members to trim, then the face, plane or members to trim them "
                      "to, then OK."],
    "WE_EndCap": ["Pick the end faces of members, set the thickness and whether the cap goes outward, inward or inside "
                  "the tube, then OK."],
    "WE_WeldBead": ["Pick the Weld From faces, then the Weld To faces (or Weld Path and pick edges), set the bead size "
                    "and whether it is full length or intermittent, then OK."],
    "WE_StructureSystem": ["Click it to enter the Structure System (the part becomes a weldment); add members with "
                           "Primary and Secondary Member, then click it again to leave."],
    "WE_EditStructureSystem": ["Pick a Structure System in the tree, then click it to go back in and add or change its "
                               "members."],
    "WE_PrimaryMember": ["In the Structure System, pick the member type (path segments, planes, points and length, or "
                         "faces crossing planes), then the references and the profile, then OK."],
    "WE_SecondaryMember": ["In the Structure System with members placed, pick pairs of members (and a plane, or a point) "
                           "for each new member between them, then OK."],
    "WE_PiercePoint": ["In a profile's own part, pick its sketch, a point of it and which pierce point it is, then OK."],
    "WE_DefineConnection": ["In the element's own part (a plate, a bracket), pick the references that place it and the "
                            "cuts it makes in the members, then OK."],
    "WE_InsertConnection": ["In a part with a Structure System, pick the connection element and the members' ends or "
                            "faces it sits on, then OK."],
    "WE_PatternConnection": ["Pick a placed connection element: it is copied to the similar corners of the structure."],
    "Freeform": ["Pick the face to deform, then drag the blue control points (or type their offsets) to push or "
                 "pull it. Set the boundary condition and accuracy, then OK."],
    "SurfaceFlatten": ["Pick the face or surface to flatten and a vertex (or a point on an edge) to flatten from, "
                       "then OK: it is laid out flat. A sketch or curve can add relief cuts."],
    "SimpleHole": ["Pick the sketch whose points place the holes, choose the hole type (simple, tapered, counterbored, "
                   "countersunk), set the diameter and depth (or Through All), then OK."],
    "ReferenceGeometry": ["Opens the reference geometry tools: Plane, Axis, Coordinate System, Point, Center of Mass "
                          "and Mate Reference."],
    "DesignStudy": ["Add Variable for each size to try and give it values (a list or a range), then Run. Each "
                    "combination is a row of results; Apply Scenario keeps the one you pick."],
    "Sensor": ["Choose the property to watch (mass, volume, surface area...), the alert and its limits, then OK. "
               "After each rebuild the Sensors folder alerts when the value goes out of range."],
})

# Assembly commands
_JOINT = ("Click it, then pick a face, edge or point on each of the two components the joint ties together. Set the "
          "offset or value if it has one, then OK.")
STEPS.update({
    "InsertComponents": ["Pick a part or assembly from the list of open documents, or Browse... for one.",
                         "It follows the pointer: click to drop it (or OK to put it at the origin). Pick more and "
                         "click again for each copy."],
    "Mate": ["Pick two faces, edges or points on two components: the mate that fits is applied at once as a preview, "
             "and a small mate toolbar opens by the pointer.",
             "Pick another mate on the toolbar or in the PropertyManager if needed, then the check keeps it. The "
             "PropertyManager stays open for the next pair.",
             "Quick mates: with no command running, Ctrl+pick two items and pick the mate on the toolbar."],
    "FixComponent": ["Pick components, then click it: they are held where they are, (f) in the tree."],
    "FloatComponent": ["Pick fixed components, then click it: they can move again, and mates position them."],
    "MoveComponent": ["Drag a component in the view: it moves as far as its mates allow.",
                      "The PropertyManager also offers Along Assembly XYZ, Along Entity, By Delta XYZ and To XYZ "
                      "Position, and Collision Detection."],
    "RotateComponent": ["Drag a component in the view: it turns as far as its mates allow. About Entity and By Delta "
                        "XYZ are in the PropertyManager."],
    "EditComponent": ["Pick a part in the assembly, then click it: you edit it in place while the others fade. Click "
                      "it again (or the corner check) to go back to the assembly."],
    "NewPartInAssembly": ["Click it, then pick a plane or a flat face: a new part goes in the tree and opens with a "
                          "sketch on that face. Esc instead leaves it at the origin."],
    "NewAssemblyInAssembly": ["Click it: a new empty subassembly is added to the assembly."],
    "CopyWithMates": ["Pick the components to copy, then Next. For each of their mates pick the new face or edge the "
                      "copy mates to (or Repeat). The copy is placed; OK starts the next one."],
    "LinearComponentPattern": ["Pick an edge or axis for the direction, the spacing and count, then the components to "
                               "repeat, then OK."],
    "CircularComponentPattern": ["Pick an axis (a round face or edge), the angle and count, then the components to "
                                 "repeat, then OK."],
    "SketchComponentPattern": ["Pick a sketch whose points place the copies, then the components to repeat, then OK."],
    "CurveComponentPattern": ["Pick a curve or edge, the spacing and count, then the components to repeat, then OK."],
    "ChainComponentPattern": ["Pick the path and the link components, choose Distance, Distance Linkage or Connection "
                              "Linkage, set the spacing or Fill path, then OK."],
    "PatternDrivenComponentPattern": ["Pick the components to repeat, then a pattern feature in a part: a copy goes on "
                                      "each instance of the pattern. Then OK."],
    "MirrorComponents": ["Pick a plane or flat face to mirror about, then the components, then OK."],
    "SmartFasteners": ["Click it with holes in the assembly: fasteners are added to them. It needs the Fasteners "
                       "add-on and says how to get it when it is not there."],
    "ShowHiddenComponents": ["Click it: the hidden components come up alone. Click the ones to show, then Exit "
                             "Show-Hidden (or Esc)."],
    "ExplodedView": ["Pick components and drag an arrow of the handle: the step is added with that direction and "
                     "distance. Add more steps the same way, then OK."],
    "ExplodeCollapse": ["Click it to collapse the exploded view, or explode it again."],
    "TakeSnapshot": ["Click it: the view and which components show are kept as a snapshot. Double-click a snapshot "
                     "in the tree to go back to it."],
    "ComponentPreview": ["Pick a component, then click it: it shows alone in a window beside the assembly. Picks there "
                         "count in the assembly, so Mate takes them. Click again to close it."],
    "BillOfMaterials": ["Set the template, BOM type and item numbers, then OK: the table floats over the view and "
                        "follows the assembly."],
    "NewMotionStudy": ["Click it: a motion study pane opens under the view. Add a Motor to a component, set the "
                       "duration, then Calculate and Play."],
    "UpdateSpeedPak": ["Click it: every SpeedPak in the assembly is made again from its part."],
    "LargeAssemblyMode": ["Click it to turn the mode on: the ticked settings below it are applied to the assembly. "
                          "Click again to put everything back."],
    "AsmGroundPlane": ["Pick a plane or a flat face, set the offset (Flip turns it over), then OK: components rest on "
                       "it in motion and physics."],
    "AsmMateReference": ["Name the reference, then pick up to three faces, edges or points with their mate type, then "
                         "OK. When the component is inserted, those references mate first."],
    "AsmSimpleHole": ["Pick a flat face where the hole goes, set the diameter and depth, then OK: it cuts through the "
                      "components in the assembly only."],
    "AsmHoleSeries": ["Pick the face of the first part and the hole's position, then set the head, middle and last "
                      "part's holes on their tabs, then OK."],
    "AsmWeldBead": ["Pick the Weld From faces of one component and the Weld To faces of another (or drag across them "
                    "with Smart Weld Selection), set the bead size, then OK."],
    "AsmBeltChain": ["Pick the pulleys or sprockets in order, set the belt thickness; Engage belt makes them turn "
                     "together. Then OK."],
    "Layout": ["Click it to open the assembly's layout sketch (made the first time); click again to close it."],
    "MakePartFromBlock": ["Pick a block of the layout sketch, then click it: a part is made from it and follows the "
                          "block."],
    "MakeBlock": ["Pick the sketch entities for the block, click the insertion point, then OK."],
    "InsertBlock": ["Pick a block of this document or Browse... for a block file, set the angle and scale, then click "
                    "where each copy goes."],
    "EditBlock": ["Pick a block, then click it: its entities can be changed; click entities to add or remove them. "
                  "The check rebuilds the block."],
    "AddRemoveBlockEntities": ["With a block open in Edit Block, click sketch entities to add them to it or take them "
                               "out."],
    "ExplodeBlock": ["Pick a block, then click it: it is broken back into plain sketch entities."],
    "SaveBlock": ["Pick a block, then click it and choose where to save the block file."],
    "AssemblyFeatures": ["Opens the assembly feature tools (cuts, holes, fillets, weld beads, belts...). They cut "
                         "through the components in the assembly only; the part files are not changed."],
    "LargeAssemblySettings": ["Opens Large Assembly Mode and the settings it turns on, each with a tick."],
    "AsmDesignChecker": ["Opens the Design Checker tools: Check Active Document, Check Against Existing File, Build "
                         "Checks and Learn Checks Wizard."],
    "FCA_Activate": ["Pick an assembly in the tree, then click it: it becomes the active one that new components and "
                     "joints go into."],
    "FCA_NewAssembly": ["Click it: a new assembly is added to this document."],
    "FCA_InsertLink": ["Click it, pick the part or assembly from the list, then click to place it."],
    "FCA_InsertNewPart": ["Click it, name the part and pick where it goes, then OK."],
    "FCA_Grounded": ["Pick a component, then click it: it is held where it is, or freed again."],
    "FCA_Solve": ["Click it: the joints of the active assembly are solved again."],
    "FCA_Bom": ["Click it: a bill of materials spreadsheet of the active assembly is made."],
    "FCA_View": ["Click it, pick components and drag them to add explode steps, then OK."],
    "FCA_Simulation": ["Click it: a simulation is added. Add motions to its joints and run it."],
    "FCA_ExportASMT": ["Click it and choose where to save the assembly's .asmt file."],
})
for _k in ("FCA_Angle", "FCA_Ball", "FCA_Belt", "FCA_Cylindrical", "FCA_Distance", "FCA_Fixed", "FCA_GearBelt",
           "FCA_Gears", "FCA_Parallel", "FCA_Perpendicular", "FCA_RackPinion", "FCA_Revolute", "FCA_Screw",
           "FCA_Slider"):
    STEPS[_k] = [_JOINT]
for _k in ("LargeHideRefs", "LargeNoAutoRecover", "LargeNoEdges", "LargeNoPreview", "LargeNoRebuildSwitch",
           "LargeNoVerify", "LargeOptimize", "LargeSuspend"):
    STEPS[_k] = ["Click to tick or untick it. Ticked settings apply while Large Assembly Mode is on; a change made "
                 "while it is on applies at once."]

# Evaluate
STEPS.update({
    "Check": ["Choose all, the picked items or a feature, tick what to look for (invalid faces and edges, short edges, "
              "radius, gaps), then run the check. Click a row of the results to pick that item."],
    "GeometryAnalysis": ["Tick what to find (knife edges, short edges, small or sliver faces...) and the size limit, "
                         "then run it. Click a row to pick the item."],
    "ImportDiagnostics": ["Click it on an imported body: faulty faces and gaps are listed. Attempt to Heal All fixes "
                          "what it can; right-click a row to heal only that one."],
    "DeviationAnalysis": ["Pick the edges between faces: the angle between the faces along them is shown (0 means they "
                          "join smoothly)."],
    "SymmetryCheck": ["Pick the plane and the bodies: symmetric, asymmetric and unique faces are coloured."],
    "UndercutAnalysis": ["Pick the direction of pull: faces the mould could not release are coloured."],
    "PartingLineAnalysis": ["Pick the direction of pull: the line where the mould would split shows."],
    "SurfaceCurvatureCombs": ["Pick faces, set the direction, number of curves and scale, then OK: the combs stay and "
                              "follow the part. Hide Curvature Combs takes them away."],
    "HideCurvatureCombs": ["Click it: all the surface curvature combs are taken away."],
    "BodyCompare": ["Pick the reference body and the comparison body: where their volumes differ is coloured (blue only "
                    "in the reference, red only in the comparison) and listed."],
    "CompareDocuments": ["Open both documents, pick the reference and the modified one, then Run Comparison. The tabs "
                         "show their properties, features, geometry, parts and dimensions side by side."],
    "PerformanceEvaluation": ["Click it: each feature's rebuild time is listed, slowest first."],
    "AssemblyPerformance": ["Click it: the assembly's counts and its components' rebuild times are listed, with advice."],
    "AssemblyVisualization": ["Click it and pick a property (mass, volume, faces, rebuild time...): the components are "
                              "listed by it and coloured from blue (least) to red (most)."],
    "ClearanceVerification": ["Pick the components (or none, for every pair), set the minimum clearance, then Calculate: "
                              "the gaps under it are listed."],
    "HoleAlignment": ["Set the hole centre deviation, then Calculate: holes in different components that line up but "
                      "are off centre are listed."],
    "PreviousReleaseCheck": ["Click it: the objects that an older setup could not open or rebuild are listed."],
    "EV_ReleaseCheck": ["Click it: the objects that an older setup could not open or rebuild are listed."],
    "CheckActiveDocument": ["Click it: the Design Checker standard runs on this document and each check shows Pass or "
                            "Fail. Double-click an object to pick it."],
    "AsmDesignCheck": ["Click it: the Design Checker standard runs on this document and each check shows Pass or Fail."],
    "DesignCheckBuild": ["Pick the checks and their values, then save the standard."],
    "AsmDesignBuild": ["Pick the checks and their values, then save the standard."],
    "DesignCheckLearn": ["Click it: the checks are filled in from the active document (units, radii, hole sizes, "
                         "material, properties), ready to save as a standard."],
    "AsmDesignLearn": ["Click it: the checks are filled in from the active document, ready to save as a standard."],
    "DesignCheckFile": ["Pick another model file: its settings become the standard this document is checked against."],
    "AsmDesignCheckFile": ["Pick another model file: its settings become the standard this document is checked against."],
    "DesignCheckFolder": ["Pick a folder: every model file in it is checked against the standard."],
    "DriveWorksXpress": ["Follow the wizard: pick the model, capture the sizes and features to drive, design the form, "
                         "write the rules, then Run to fill in the form and Create the new models."],
    "FloXpress": ["Follow the steps: check the closed fluid volume, pick the fluid, the inlet and outlet faces with "
                  "their flow, then Solve. Results show the flow paths coloured by speed."],
    "EV_Simulation": ["Click it and follow the tabs from left to right: Fixtures, Loads, Material, Run, then Results."],
    "EV_Costing": ["Click it on a part: its material and machining cost are worked out, per part and per batch."],
    "EV_DFM": ["Click it on a part: deep or small holes, sharp inside corners, thin walls and deep pockets are listed."],
    "EV_OnDemand": ["Click it: a STEP, an STL and the part file are packed together, ready to send for a quote."],
    "EV_PartReviewer": ["Click it: step through the tree one feature at a time, each with its comment."],
    "EV_Sustainability": ["Click it on a part with a material: the carbon, energy and water of its material and its "
                          "making are shown."],
})

# Sketch Ink and other small tools
STEPS.update({
    "PenDraw": ["Click it, then draw with the mouse or a pen: the strokes stay as ink in the sketch until they are "
                "converted."],
    "PenEraser": ["Click it, then drag over ink to rub it out."],
    "PenSelect": ["Click it, then click ink strokes to pick them; the convert tools then work on the picked ink only."],
    "PenPowerModify": ["Click it, then scratch back and forth over sketch entities or ink to delete them."],
    "PenRuler": ["Click it and drag to lay the ruler; ink drawn along it comes out straight."],
    "PenProtractor": ["Click it and drag from the centre out; ink drawn along its rim comes out round."],
    "PenAutoShape": ["Click to turn it on: each stroke becomes lines, arcs or circles as you draw it."],
    "PenAutoSpline": ["Click to turn it on: each stroke becomes a spline as you draw it."],
    "PenAutoSketchEntities": ["Click to turn it on: each stroke becomes the sketch entity it looks like."],
    "PenTouch": ["Click to turn it on: a finger on a touch screen draws ink too."],
    "InkColor": ["Click it and pick the colour of the next ink."],
    "Plane": ["Pick up to three references (faces, edges, points or planes) the plane follows, set the offset or "
              "angle, then OK."],
    "SectionView": ["Pick a plane (Front, Top, Right) or a flat face, drag the arrow or set the offset and the "
                    "rotations, then OK. Click it again to show the whole model."],
    "DrawCenterline": ["Click two edges of a view (the sides of a cylinder or a slot): a centerline goes between them. "
                       "The tool stays on for the next one."],
    "DrawMarkupDraw": ["Turn Markup on first, then press and drag on the sheet to draw; each stroke is one markup."],
    "DrawMarkupEraser": ["Turn Markup on first, then click the markups to erase. OK when done."],
    "DrawMarkupSelect": ["Turn Markup on first, then click a markup to pick it, to move or delete it."],
    "DrawMarkupColor": ["Turn Markup on first, then click it and pick the markup pen's colour."],
    "DrawQuickSnaps": ["Click it for the sketch snap options on the sheet."],
    "DrawAddRelation": ["Pick sketch entities on the sheet, then click it: only the relations that fit them are offered."],
    "DrawDisplayDeleteRelations": ["Pick sketch entities on the sheet, then click it: their relations are listed; pick "
                                   "one and Delete."],
})
for _c in ("Black", "Blue", "Green", "Orange", "Purple", "Red"):
    STEPS["InkColor" + _c] = ["Click it: the next ink is drawn in %s." % _c.lower()]
for _k, _how in (("DrawSketchLine", "Click the start, then the end; keep clicking to chain."),
                 ("DrawSketchCenterline", "Click the start, then the end of the centerline."),
                 ("DrawSketchMidpointLine", "Click the middle, then one end."),
                 ("DrawSketchRectangle", "Click one corner, then the opposite corner."),
                 ("DrawSketchCenterRectangle", "Click the centre, then a corner."),
                 ("DrawSketchCircle", "Click the centre, then the radius."),
                 ("DrawSketchPerimeterCircle", "Click three points on the rim."),
                 ("DrawSketchArc", "Click the centre, then the start, then the end."),
                 ("DrawSketchThreePointArc", "Click the start, the end, then a point on the arc."),
                 ("DrawSketchEllipse", "Click the centre, then each axis."),
                 ("DrawSketchPolygon", "Set the sides, then click the centre and a corner."),
                 ("DrawSketchSlot", "Click the start and end of the centre line, then the width."),
                 ("DrawSketchSpline", "Click the points it runs through; double-click ends it."),
                 ("DrawSketchPoint", "Click where each point goes.")):
    STEPS[_k] = [_how + " Click inside a view and it belongs to that view, on the empty sheet it belongs to the sheet.",
                 "Esc ends the tool."]
for _k, _how in (("DrawTrimEntities", "Drag across the bits to remove, or click them."),
                 ("DrawOffsetEntities", "Pick the entities, set the distance, then OK."),
                 ("DrawMirrorEntities", "Pick the entities and the line to mirror about, then OK."),
                 ("DrawMoveEntities", "Pick the entities, then the base point and where it goes, then OK."),
                 ("DrawCopyEntities", "Pick the entities, then the base point and where the copy goes, then OK."),
                 ("DrawRotateEntities", "Pick the entities, the centre and the angle, then OK."),
                 ("DrawScaleEntities", "Pick the entities, the base point and the factor, then OK."),
                 ("DrawLinearSketchPattern", "Pick the entities, set the spacing and count, then OK."),
                 ("DrawCircularSketchPattern", "Pick the entities and the centre, set the count, then OK."),
                 ("DrawSketchFillet", "Pick two entities that meet, set the radius, then OK."),
                 ("DrawSketchChamfer", "Pick two entities that meet, set the distances, then OK."),
                 ("DrawConvertEntities", "Pick model edges in a view, then OK: they become sketch entities.")):
    STEPS[_k] = [_how]

# Hand-written steps of the other drawing commands
_STAY = "The tool stays on for the next one: OK or Esc ends it."
_PICK_DIM = "Pick the dimensions first (Ctrl+click for more), then click it."
STEPS.update({
    # ---- Annotation tab: dimensions
    "DrawHorizontalDimension": ["Click two points, or a line, in a view: the horizontal distance follows the pointer.",
                                "Click where the dimension goes. " + _STAY],
    "DrawVerticalDimension": ["Click two points, or a line, in a view: the vertical distance follows the pointer.",
                              "Click where the dimension goes. " + _STAY],
    "DrawAngularDimension": ["Click two lines in a view: the angle between them follows the pointer.",
                             "Click where the dimension goes; which side you click picks which angle. " + _STAY],
    "DrawRadiusDimension": ["Click a circle or an arc in a view, then click where the dimension goes.",
                            "Switch between radius and diameter in the Dimension PropertyManager. " + _STAY],
    "DrawOrdinateDimension": ["Click the vertex that is the zero, then each vertex to dimension from it.",
                              "OK places them; texts that crowd are jogged apart."],
    "DrawHorizontalOrdinate": ["Click the vertex that is the zero, then each vertex to dimension from it.",
                               "OK places the horizontal ordinate dimensions."],
    "DrawVerticalOrdinate": ["Click the vertex that is the zero, then each vertex to dimension from it.",
                             "OK places the vertical ordinate dimensions."],
    "DrawBaselineDimension": ["Click the base vertex, then the vertices to dimension from it.",
                              "OK places them, each measured from the base."],
    "DrawChainDimension": ["Click the first vertex, then the next ones in turn.",
                           "OK places the chain, each dimension running from the vertex before it."],
    "DrawAngularRunningDimension": ["Click the centre (a vertex), then the vertex at 0 degrees, then the vertices "
                                    "to dimension.", "OK places the angles, all measured from the same zero line."],
    "DrawChamferDimension": ["Click the chamfer edge, then a lead-in edge next to it, then where the text goes.",
                             "The text shows the chamfer's distance and angle."],
    "DrawSymmetricLinearDiameterDimension": ["Click the edge, then the centerline it turns about (they must be "
                                             "parallel), then where the dimension goes.",
                                             "It shows the diameter across the centerline."],
    "DrawPathLengthDimension": ["Pick the chain of edges or arcs in a view first, then click it: their total length "
                                "is written next to them."],
    "DrawAutodimension": ["Choose all entities in the view or only the picked ones, and the scheme (baseline, chain "
                          "or ordinate) for each direction.", "Click the view to dimension it."],
    "DrawModelItems": ["Choose what to bring in: dimensions, annotations or reference geometry, and from the whole "
                       "model or the picked feature.",
                       "OK (or a click on a feature in a view) adds the model's own dimensions to the views."],
    # ---- Annotation tab: annotations
    "DrawAutoBalloon": ["Click a view: every part in it gets a balloon, laid out by the pattern you pick "
                        "(square, circular, top, bottom...).", "Click more views, then OK."],
    "DrawStackedBalloon": ["Click a part for the first balloon, then click where the stack goes.",
                           "Click more parts to add their balloons to the stack, then OK."],
    "DrawMagneticLine": ["Click the start and the end of the line.",
                         "Balloons, notes and symbols dragged near it snap onto it, evenly spaced."],
    "DrawSurfaceFinish": ["Pick the symbol and type the roughness.",
                          "Click where it points (an edge), then where the symbol goes. " + _STAY],
    "DrawGeometricTolerance": ["Build the feature control frame: the symbol, the tolerance value and the datums.",
                               "Click where it points, then where the frame goes. " + _STAY],
    "DrawDatumFeature": ["Click the edge the datum goes on, then where its label goes.",
                         "The next one takes the next letter. " + _STAY],
    "DrawDatumTarget": ["Click the target point on the part, then where the symbol goes. " + _STAY],
    "DrawWeldSymbol": ["Set the weld symbol and size for the Arrow Side (and the other side if needed).",
                       "Click the weld on the part, then where the symbol goes. " + _STAY],
    "DrawCaterpillar": ["Click the weld edge in a view: weld bead arcs are drawn along it. " + _STAY],
    "DrawEndTreatment": ["Click near the end of a weld edge in a view: a filled weld end is drawn there. " + _STAY],
    "DrawCenterMark": ["Click circles or arcs in a view to put center marks on them. " + _STAY,
                       "Auto Insert, For all holes, marks every hole of the view you click at once."],
    "DrawAreaHatch": ["Choose Hatch, Solid or None, and the pattern, its scale and angle.",
                      "Click inside a closed area of a view to hatch it (or pick Boundary and click the edges that "
                      "close it). " + _STAY],
    "DrawRevisionCloud": ["Click two opposite corners of the area that changed: the cloud is drawn round it. " + _STAY],
    "DrawRevisionSymbol": ["Click where the leader points, then where the symbol goes.",
                           "It shows the current revision of the revision table."],
    "DrawLinearNotePattern": ["Set the spacing, number of instances and angle of each direction.",
                              "Click the note, balloon or symbol to pattern."],
    "DrawCircularNotePattern": ["Click the pattern centre, then the note, balloon or symbol to pattern.",
                                "Set the number of instances and the angle."],
    "DrawFormatPainter": ["Click the dimension or annotation to copy the format from.",
                          "Then click the ones to paste it to; OK when done."],
    "DrawSpellChecker": ["Click it (or press F7): each word of the sheet's notes that is not in the word list "
                         "comes up in turn, with suggestions.",
                         "Change or Change All puts in the suggestion; Ignore, Ignore All or Add skip the word."],
    # ---- blocks
    "DrawMakeBlock": ["Pick the sketch entities and annotations for the block (or click them now).",
                      "Click on empty sheet for the insertion point, then OK."],
    "DrawInsertBlock": ["Pick one of this drawing's blocks, or Browse... for a block file.",
                        "Set the scale and angle, then click on the sheet to place it. " + _STAY],
    "DrawEditBlock": ["Pick a block, then click it: its entities come apart so you can move them or change the text.",
                      "OK rebuilds the block and every copy of it."],
    "DrawExplodeBlock": ["Pick a block, then click it: the block is broken back into its entities."],
    "DrawSaveBlock": ["Pick a block, then click it and choose where to save the block file."],
    # ---- tables
    "DrawHoleTable": ["Click the origin in a view (a corner of the part, or an X edge then a Y edge).",
                      "Click the holes, or a face for all its holes, then click where the table goes (or OK for "
                      "the anchor point). Next View adds holes from another view."],
    "DrawRevisionTable": ["Set the options, then OK (it goes to the anchor point) or click where the table goes.",
                          "Right-click the table, Revisions > Add Revision for each new revision."],
    "DrawGeneralTable": ["Set the number of rows and columns.",
                         "Click where the table goes (or OK for the anchor point). Double-click a cell to type in it."],
    "DrawTitleBlockTable": ["Set the options, then OK (it goes to the anchor point) or click where the table goes."],
    "DrawBendTable": ["Click the sheet metal view, then click where the table goes (or OK for the anchor point)."],
    "DrawPunchTable": ["Click the origin (a corner of the part) in a view, then click where the table goes."],
    "DrawWeldTable": ["Click a drawing view whose model has welds, then OK (anchor point) or click where the table goes."],
    "DrawFamilyTable": ["Click the view of the part family (a part with configurations).",
                        "Pick the columns and the dimensions that show letters, then click where the table goes "
                        "(or OK for the anchor point)."],
    # ---- Drawing tab: view tools
    "DrawStandard3View": ["Pick a part or assembly from the list, or Browse... for one.",
                          "OK puts its Front, Top and Right views on the sheet, lined up."],
    "DrawAuxiliaryView": ["Click a straight edge in a view: the new view looks square onto it.",
                          "Click where the view goes."],
    "DrawAlternatePosition": ["Click the assembly view, choose a component and move it with the boxes, then OK.",
                              "The second position is drawn over the view in phantom lines."],
    "DrawBreak": ["Click in a view for the first break line, then for the second.",
                  "Change the gap and the line style, then OK. The view keeps its scale."],
    "DrawBrokenOut": ["Click two corners of the area to break out.",
                      "Set the depth (or click an edge in a side view for it), then OK."],
    "DrawCrop": ["Click one corner of the area of the view to keep, then the opposite corner."],
    "DrawEmptyView": ["Click on the sheet to place the empty view, then sketch in it."],
    "DrawPredefinedView": ["Set the orientation and scale, then click on the sheet to place the view.",
                           "Tick Insert a model now to fill it at once, or leave it empty and put a model in later."],
    "DrawRelativeView": ["In the model's window pick a face for the first orientation and one for the second, "
                         "then OK.", "Click on the sheet to place the view."],
    "DrawRemovedSection": ["Click one edge of the view, then the opposite edge.",
                           "Click to place the section: it shows the slice between the two edges."],
    "DrawReplaceModel": ["Pick the drawing views to change and the new model, then OK.",
                         "The views then show the new model."],
    "DrawUpdateView": ["Pick the views (or none, for every view) and click it: they are drawn again from their models."],
    # ---- Sheet Format tab
    "DrawEditSheetFormat": ["Click it: the border, the title block and its texts can be changed; the views are hidden "
                            "meanwhile.", "Edit Sheet goes back to the sheet."],
    "DrawEditSheet": ["Click it to leave the sheet format and go back to the sheet."],
    "DrawTitleBlockFields": ["Click it: a table lists the title block's fields. Type the text of each one, then OK."],
    "DrawAutomaticBorder": ["While editing the sheet format, click it.",
                            "Set the zones (rows, columns, labels, start corner), the margins and the formatting, then OK."],
    # ---- Inspection tab
    "INSP_Create": ["Click it with the drawing open: the sheet's dimensions are numbered top to bottom, left to right, "
                    "and the inspection report opens."],
    "INSP_Balloon": ["Click it: a numbered balloon goes next to every dimension. They move and print like any balloon."],
    "INSP_RemoveBalloons": ["Click it to take the inspection balloons off the sheet again."],
    "INSP_Report": ["Click it: the report lists each dimension with its nominal value and limits.",
                    "Type what was measured; the result says Pass or Fail. Update from Drawing picks up changes."],
    "INSP_Excel": ["Click it and choose where to save: the report is saved as an Excel file."],
    "INSP_Csv": ["Click it and choose where to save: the report is saved as a CSV file."],
})

# Drawing Tools tab (FreeCAD's own drawing tools): pick first in a view, then click the button
_TDX = {
    "TDX_FillTemplate": "Click it: tick the title block fields to fill from the document's properties, then OK.",
    "TDX_Redraw": "Click it: the whole sheet is drawn again.",
    "TDX_StackTop": "Pick a view, then click it: it is drawn over all the others.",
    "TDX_StackUp": "Pick a view, then click it: it moves one step up in the stack.",
    "TDX_StackDown": "Pick a view, then click it: it moves one step down in the stack.",
    "TDX_StackBottom": "Pick a view, then click it: it is drawn under all the others.",
    "TDX_ShareView": "Pick a view, then click it and choose the other sheet that shows it too.",
    "TDX_MoveView": "Click it, choose the view, the sheet it is on and the sheet to move it to, then OK.",
    "TDX_ToggleLock": "Pick views, then click it: their position is locked, or unlocked again.",
    "TDX_SectionView": "Pick a view, then click it. Choose the direction of the cut and its position, then OK.",
    "TDX_ComplexSection": "Pick a view and the sketch of the cutting profile, then click it. Set the options, then OK.",
    "TDX_PositionSection": "Pick a section view, then click it: it lines up with its parent view.",
    "TDX_ActiveView": "Click it, set the picture's size and background, then OK: the 3D window is put on the sheet.",
    "TDX_DraftView": "Pick 2D drafting or BIM objects in the tree, then click it: they show on the sheet.",
    "TDX_ArchView": "Pick a BIM section plane in the tree, then click it: its cut shows on the sheet.",
    "TDX_ClipAdd": "Pick a view and a clip group, then click it: the view is shown inside the clip.",
    "TDX_Dimension": "Pick edges or points in a view, then click it: the dimension that fits what is picked is added.",
    "TDX_Length": "Pick an edge, or two points, in a view, then click it: the true length is added.",
    "TDX_Horizontal": "Pick an edge, or two points, in a view, then click it: the horizontal distance is added.",
    "TDX_Vertical": "Pick an edge, or two points, in a view, then click it: the vertical distance is added.",
    "TDX_Radius": "Pick a circle or an arc in a view, then click it: its radius is added.",
    "TDX_Diameter": "Pick a circle or an arc in a view, then click it: its diameter is added.",
    "TDX_Angle": "Pick two straight edges in a view, then click it: the angle between them is added.",
    "TDX_Angle3": "Pick three points in a view (the corner second), then click it: the angle at the corner is added.",
    "TDX_ArcLength": "Pick an arc in a view, then click it: the length along it is added.",
    "TDX_AxoLength": "In an isometric view pick an edge along the length, a second edge in the same plane and the "
                     "two points to measure between, then click it.",
    "TDX_HChain": "Pick three or more points in a view, then click it: horizontal dimensions are added end to end.",
    "TDX_VChain": "Pick three or more points in a view, then click it: vertical dimensions are added end to end.",
    "TDX_OChain": "Pick three or more points in a view, then click it: aligned dimensions are added end to end.",
    "TDX_HCoord": "Pick the base point first, then more points, then click it: horizontal dimensions from the base "
                  "are added.",
    "TDX_VCoord": "Pick the base point first, then more points, then click it: vertical dimensions from the base "
                  "are added.",
    "TDX_OCoord": "Pick the base point first, then more points, then click it: aligned dimensions from the base "
                  "are added.",
    "TDX_HChamfer": "Pick the two end points of a chamfer edge, then click it: its size and angle are added.",
    "TDX_VChamfer": "Pick the two end points of a chamfer edge, then click it: its size and angle are added.",
    "TDX_HExtent": "Pick edges in a view, then click it: their overall width is added.",
    "TDX_VExtent": "Pick edges in a view, then click it: their overall height is added.",
    "TDX_HPosChain": _PICK_DIM + " The horizontal dimensions line up on one line.",
    "TDX_VPosChain": _PICK_DIM + " The vertical dimensions line up on one line.",
    "TDX_OPosChain": _PICK_DIM + " The aligned dimensions line up on one line.",
    "TDX_HCascade": _PICK_DIM + " The horizontal dimensions are spaced evenly in a stair.",
    "TDX_VCascade": _PICK_DIM + " The vertical dimensions are spaced evenly in a stair.",
    "TDX_OCascade": _PICK_DIM + " The aligned dimensions are spaced evenly in a stair.",
    "TDX_HoleShaftFit": "Pick a diameter or length dimension, then click it and choose the fit (H7/g6 and so on).",
    "TDX_PrefixDia": _PICK_DIM + " A diameter sign goes before each value.",
    "TDX_PrefixSquare": _PICK_DIM + " A square sign goes before each value.",
    "TDX_PrefixRepeat": _PICK_DIM + " Type the count: 'n x' goes before each value.",
    "TDX_PrefixRemove": _PICK_DIM + " The prefix comes off each value.",
    "TDX_IncDecimal": _PICK_DIM + " Each one shows one more decimal place.",
    "TDX_DecDecimal": _PICK_DIM + " Each one shows one decimal place less.",
    "TDX_CustomFormat": "Pick a dimension or a label, then click it and edit its format text, then OK.",
    "TDX_AreaAnno": "Pick faces in a view, then click it: their area is written next to them.",
    "TDX_Area": "Pick a face in a view, then click it: its area is added.",
    "TDX_SelectLineAttr": "Click it and set the line style, width and colour that the next cosmetic lines use.",
    "TDX_ChangeLineAttr": "Pick cosmetic lines or centerlines, then click it: they take the line attributes set.",
    "TDX_ExtendLine": "Pick a cosmetic line or centerline, then click it: it gets longer at both ends.",
    "TDX_ShortenLine": "Pick a cosmetic line or centerline, then click it: it gets shorter at both ends.",
    "TDX_ShowAll": "Pick a view, then click it: its hidden edges show, or hide again.",
    "TDX_CircleCL": "Pick circles or arcs in a view, then click it: each gets center marks.",
    "TDX_2LineCL": "Pick two edges in a view, then click it: a centerline goes between them.",
    "TDX_2PointCL": "Pick two points in a view, then click it: a centerline goes through them.",
    "TDX_FaceCL": "Pick a face in a view, then click it: a centerline goes across it.",
    "TDX_BoltCircleCL": "Pick three or more hole circles in a view, then click it: a bolt circle goes through them.",
    "TDX_ThreadBoltSide": "Pick the two side edges of a bolt in a view, then click it: the cosmetic thread is drawn.",
    "TDX_ThreadBoltBottom": "Pick the bolt's circle in an end view, then click it: the cosmetic thread is drawn.",
    "TDX_ThreadHoleSide": "Pick the two side edges of a hole in a view, then click it: the cosmetic thread is drawn.",
    "TDX_ThreadHoleBottom": "Pick the hole's circle in an end view, then click it: the cosmetic thread is drawn.",
    "TDX_CosVertex": "Pick a view, then click it: click in the view where the point goes (or type its X and Y), "
                     "then OK.",
    "TDX_Midpoints": "Pick edges in a view, then click it: a point goes at the middle of each.",
    "TDX_Quadrants": "Pick circles in a view, then click it: points go at their quadrants.",
    "TDX_Intersection": "Pick two edges that cross in a view, then click it: points go where they cross.",
    "TDX_OffsetVertex": "Pick a point in a view, then click it and type the X and Y offset of the new point.",
    "TDX_Circle1": "Pick a view, then click it: set the circle's centre and radius in the panel, then OK.",
    "TDX_Circle2": "Pick the centre point, then a point on the circle, then click it: a cosmetic circle is drawn.",
    "TDX_Circle3": "Pick three points, then click it: a cosmetic circle is drawn through them.",
    "TDX_CosArc": "Pick the centre, then the start and end points, then click it: a cosmetic arc is drawn.",
    "TDX_2PointLine": "Pick two points in a view, then click it: a cosmetic line is drawn between them.",
    "TDX_Parallel": "Pick an edge and a point in a view, then click it: a cosmetic line parallel to the edge goes "
                    "through the point.",
    "TDX_Perpendicular": "Pick an edge and a point in a view, then click it: a cosmetic line square to the edge goes "
                         "through the point.",
    "TDX_Eraser": "Pick cosmetic lines, circles or points, then click it: they are deleted.",
    "TDX_AlignVertH": "Pick two points in a view, then click it: the view turns so they lie level.",
    "TDX_AlignVertV": "Pick two points in a view, then click it: the view turns so one is above the other.",
    "TDX_RichText": "Pick a view to attach it to (or nothing), then click it: type and format the text, then OK.",
}
STEPS.update({k: [v] for k, v in _TDX.items()})

# Hand-written steps of the add-in tabs' commands
STEPS.update({
    # Add-Ins
    "WB_Assembly": ["Click it: a new assembly opens and Begin Assembly starts. Pick the first part from the list "
                    "of open documents, or Browse... for one."],
    "FC_AllTools": [
        "Click it: a list opens with every installed FreeCAD workbench, then its toolbars, then their commands.",
        "Open a workbench (it loads then) and click a command to run it, without leaving this interface.",
    ],
    # 3D Slicer
    "SlicerOrca": [
        "Open the part or assembly, then click it: a panel opens with Orca Slicer's printer, filament and process "
        "presets, read from the slicer's own settings.",
        "Pick the presets, then Slice. Preview, Export G-code and Send to Printer use that slice.",
        "Orca Slicer must be downloaded first: Slicer Updates on this tab does that.",
    ],
    "SlicerBambu": [
        "Open the part or assembly, then click it: a panel opens with Bambu Studio's printer, filament and process "
        "presets, read from the slicer's own settings.",
        "Pick the presets, then Slice. Preview, Export G-code and Send to Printer use that slice.",
        "Bambu Studio must be downloaded first: Slicer Updates on this tab does that.",
    ],
    "SlicerSlice": [
        "Pick the presets in the Orca Slicer or Bambu Studio panel first, then click Slice.",
        "The part is sliced with that slicer's own engine; the print time and the filament used are shown.",
    ],
    "SlicerPreview": [
        "Slice first, then click Preview: the toolpaths show in the 3D view layer by layer.",
        "Drag the layer slider at the side. The legend lists each line type with its time and share; click one to "
        "hide it, or switch to another view such as speed.",
    ],
    "SlicerExport": [
        "Slice first, then click it and choose where to save: G-code, or a sliced project for Bambu Lab printers.",
    ],
    "SlicerSend": [
        "Slice first, then click it and pick the printer: the slice is sent and the print starts.",
        "Add the printer first with Add Printer.",
    ],
    "SlicerDevice": [
        "Click it to see a connected printer's state and camera.",
        "Its Controls set the print speed and fans, move the print head and send it home; each one asks before it acts.",
    ],
    "SlicerAddPrinter": [
        "Click it: printers on your network, or in your Bambu Lab account once you are logged in, are listed. "
        "Pick one to add it.",
    ],
    "SlicerLogin": [
        "Click it to log in to your Bambu Lab account for cloud printing. You sign in inside Bambu's own program, "
        "with your email and a code Bambu sends you; your password is never seen here.",
    ],
    "SlicerFullOrca": [
        "Click it: the real Orca Slicer opens in a tab inside FreeCAD with every tool it has. If it is not there "
        "yet, you are asked whether to download it.",
    ],
    "SlicerFullBambu": [
        "Click it: the real Bambu Studio opens in a tab inside FreeCAD with every tool it has. If it is not there "
        "yet, you are asked whether to download it.",
    ],
    "SlicerFullPrusa": [
        "Click it: the real PrusaSlicer opens in a tab inside FreeCAD. If it is not there yet, you are asked "
        "whether to download it.",
    ],
    "SlicerUpdate": [
        "Click it: Orca Slicer, Bambu Studio and PrusaSlicer are listed with their installed and latest versions.",
        "Click Download or Update for the one you want. Roll Back returns to the version before, What's New shows "
        "the release notes and Check Now looks again.",
    ],
    "SlicerApps": [
        "Click it, then drop another slicer's zip or installer on the box. For an installer you are shown who "
        "signed it and asked before it runs.",
    ],
    # ScanRuler
    "SR_Open": [
        "Click it: ScanRuler opens as a web page (it needs a connection; nothing is downloaded).",
        "Use Send Selection to ScanRuler to give it the part or mesh to inspect.",
    ],
    "SR_Send": [
        "Pick the part or mesh, then click it: it is saved as an STL for ScanRuler. Press Load there and it opens.",
    ],
    "SR_Update": ["Click it: ScanRuler's releases page is read and you are told whether a new version is out."],
    "SR_Notes": ["Click it to open ScanRuler's releases page."],
    # Markup (part and drawing)
    "MK_Draw": [
        "Click it: the Markup page opens. Drag over the model to draw.",
        "OK keeps the marks as a Markup in the Markups folder of the tree, with the view they were drawn in; the "
        "cross throws them away.",
    ],
    "MK_Erase": ["With the Markup page open, click it, then click a mark to erase it."],
    "MK_Select": ["With the Markup page open, click it to pick the model while the markup stays open."],
    "MK_Touch": ["Click it to draw the marks with a finger or a pen on a touch screen."],
    "MK_Note": ["Click it, type the note in the Note text box of the Markup page, then click on the model where "
                "it goes."],
    "MK_Color": ["Click it and pick the colour of the next marks."],
    "DrawMarkupTouch": ["Turn Markup on first, then click it to draw on the sheet with a finger or a pen."],
    "DrawMarkupNote": ["Turn Markup on first, then click it and click on the sheet where the note goes."],
    "DrawZoomToMarkup": ["Click it to zoom to the sheet's markups (there must be one on the sheet)."],
    "DrawMarkupOptions": ["Click it to set the markup pen's colour and width."],
    # MBD
    "MBD_RefDim": ["Click it, then pick the two items: a reference dimension (no tolerance) is added on the model."],
    "MBD_Note": ["Click it, type the note, then pick the face or edge its leader points to."],
    "MBD_SurfaceFinish": ["Click it, pick the face, then set the symbol, the roughness (Ra), the method and the lay, "
                          "and OK."],
    "MBD_Weld": ["Click it, pick the edge or face, then set the weld type and size (both sides, all around, "
                 "field weld), and OK."],
    "MBD_Capture": [
        "Turn the model to the view you want, then click it. Name the view and tick the annotations it shows, "
        "then OK.",
        "The view goes to the 3D Views tab with its picture.",
    ],
    "MBD_Views": [
        "Click it to show the 3D Views tab. Double-click a view to go back to it; right-click it to Update View, "
        "Rename or Delete it.",
    ],
    "MBD_Dynamic": ["Click to turn it on or off. While it is on, each annotation shows only in the 3D view it was "
                    "made in."],
    "MBD_PDF": ["Capture the 3D views first, then click it and choose where to save: each view becomes a page with "
                "the title block and the list of annotations."],
    "MBD_PDFTemplate": ["Click it to set the title block fields (company, title, author, revision, logo) and the "
                        "paper of published PDFs."],
    "MBD_STEP": ["Click it and choose where to save: the part is saved as STEP AP242."],
    "MBD_Compare": [
        "Open both parts, then click it. Pick the Reference part and the Modified one, then Compare.",
        "The table lists each annotation in both, coloured as changed, added or removed.",
    ],
    "MBD_CopyScheme": ["Pick the source configuration and the configurations to copy its annotations to, then OK. "
                       "Each copy shows only in its own configuration."],
    # Analysis Preparation and CircuitWorks
    "SplitBody": [
        "Pick the planes, faces, surfaces or sketches that cut the part (Trim Tools).",
        "Choose All bodies or Selected bodies, then Cut Part. OK keeps the resulting bodies.",
    ],
    "Defeature": ["Pick the faces to remove (fillets, holes and other details), then OK: the body is rebuilt "
                  "without them."],
    "ECAD_Open": ["Click it and pick an IDF board file (.emn, with its .emp next to it): the CircuitWorks window lists "
                  "the board and its components.",
                  "Filter by name, minimum height or side, untick what you don't want, then Build Model (an assembly) "
                  "or Build Model as Part."],
    "ECAD_Export": ["Open the board model and click it (or pick the board and its components first), then choose where "
                    "to save: the board, its cutouts, its round holes and its components are written as IDF 3.0 (.emn "
                    "and .emp)."],
    "ECAD_Update": ["With a model built from an ECAD file active, click it: the file is read again and components "
                    "move, come and go by reference designator."],
    "ECAD_Library": ["Add a model file (STEP or FreeCAD part) for a package name: Build Model uses it instead of the "
                     "package's outline."],
    "ECAD_Options": ["Choose whether Build Model makes an assembly or a part, which components the CircuitWorks window "
                     "shows, and whether Library models are used."],
    # Simulation
    "SIM_NewStudy": [
        "Open the part, then click it and pick the study type: static, frequency, buckling or thermal.",
        "Then add a material, fixtures and loads from this tab, and Run This Study.",
    ],
    "SIM_Advisor": ["Click it and answer what you want to find out (strength, vibration, buckling or heat): it "
                    "makes the right kind of study and says what to add next."],
    "SIM_Wizard": ["Click it and follow the tabs from left to right: Fixtures, Loads, Material, Run, then Results, "
                   "where the stress, displacement and factor of safety plots and the report are."],
    "SIM_Run": ["Click it: the active study is meshed if it needs it, then solved. The results show when it is done."],
    "SIM_Report": ["Run the study first, then click it: an HTML report of the active study is written. Include "
                   "Image for Report adds the current view to it."],
    "SIM_Mesh": ["Pick the part (or click it with one study open), set the element size, then OK: the part is "
                 "meshed with Gmsh."],
    "SIM_Fixed": ["Click it, pick the faces, edges or vertices to hold, then OK."],
    "SIM_Force": ["Click it, pick the faces, edges or vertices, type the force and its direction, then OK."],
    "SIM_Pressure": ["Click it, pick the faces, type the pressure, then OK."],
    "SIM_Results": ["Click it after the study has run: pick stress, displacement or strain to show on the part."],
    "SIM_Torque": ["Click it, pick the round faces, then the axis (an axis, a straight edge or a round face), type "
                   "the torque, then OK."],
    "SIM_RemoteLoad": ["Click it, pick the faces the load reaches, type where the load is (X, Y, Z) and its force and "
                       "moment, then OK."],
    "SIM_DistributedMass": ["Click it, pick the faces that carry the mass, type the mass, then OK."],
    "SIM_BearingConnector": ["Click it in an assembly study, pick the shaft's round face and the housing's round face, "
                             "choose Rigid or Flexible, then OK."],
    "SIM_RigidConnector": ["Click it in an assembly study, pick a face on each of the two parts, then OK: the two faces "
                           "keep their places to each other."],
    "SIM_MeshControl": ["Click it, pick the faces, edges or vertices to mesh finer, set the element size and the ratio, "
                        "then OK. Mesh the study again to use it."],
    "SIM_MeshQuality": ["Mesh the study first, then click it, pick Aspect Ratio or Jacobian, then OK: the mesh is "
                        "coloured element by element."],
    # CAM
    "CAM_Setup": ["Open the part, then click it: pick the model, the stock and the origin of the machining job, "
                  "then OK. Add tools and operations from this tab."],
    "CAM_Generate": ["Click it to recompute every toolpath of the job after a change."],
    "CAM_Simulate": ["Click it, pick the job and press play: the material removal is shown."],
    "CAM_Post": ["Click it with the job picked: the G-code is written with the job's post processor, and you "
                 "choose where to save it."],
    # Flow Simulation
    "FLOW_New": ["Pick the body that is the fluid region, then click it: a flow project is made with the Elmer "
                 "solver. Add the fluid, the inlet and outlet conditions and the mesh from this tab."],
})

# Steps of the other buttons on an add-in tab (by tab)
TAB_STEPS = {
    "Simulation": ["A study runs in order: New Study, a material, fixtures, loads, the mesh, then Run This Study.",
                   "Click the button, pick the faces, edges or vertices it acts on when it asks, set its values, "
                   "then OK. It goes into the active study."],
    "Flow Simulation": ["A flow project runs in order: New Project, the fluid, inlets and outlets, the mesh, then "
                        "run the solver.",
                        "Click the button, pick the faces it acts on when it asks, set its values, then OK."],
    "CAM": ["A machining job runs in order: Setup, the tools (Tool Library), operations, Simulate, then Post Process.",
            "Click the button, pick the faces or edges it machines when it asks, set its values, then OK. "
            "It goes into the active job."],
    "Freeshape": ["Start with a shape (QuadBall, Box, Cylinder, Torus, or a flat Rectangle, Disk or Ring), then "
                  "change it with Extrude Face, Insert Loop, Crease, Subdivide and the other buttons.",
                  "Click the button, pick the faces or edges it acts on when it asks, set its values, then OK. "
                  "Each one is a feature in the tree that you can edit later."],
    "MBD Dimensions": ["Click the button, then pick the faces, edges or features the dimension or tolerance is "
                       "for, set its values, then OK. It shows on the model."],
}

WORKBENCH_STEPS = ["Click it: FreeCAD switches to that workbench and its toolbars show on their own CommandManager "
                   "tab. The other tabs stay as they are."]

# Commands that work differently on a drawing sheet: their steps there
DRAWING_STEPS = {
    "SmartDimension": [
        "Click an edge, a circle or a point in a view: the dimension follows the pointer.",
        "Click a second item for a distance or an angle between them, or click a clear place to set this one.",
        "Click where the dimension goes. The Dimension PropertyManager opens for its tolerance, precision and text.",
        "The tool stays on for the next dimension: Esc, a right-click or Smart Dimension again ends it. "
        "Model Items brings in the part's own dimensions instead.",
    ],
}

# What those commands do on a drawing sheet
DRAWING_WHAT = {"SmartDimension": "Dimensions edges, circles and points of the views on the sheet."}

# PropertyManager titles whose drawing page differs from the part or sketch one
DRAWING_TITLES = {"Dimension": "SmartDimension"}

# User Guide sections of single commands, where the tab's section is not the closest one
KEY_GUIDE = {
    "DrawModelView": ("06-drawings.html", "starting-a-drawing"), "DrawBOM": ("06-drawings.html", "tables"),
    "DrawNote": ("06-drawings.html", "dimensions-and-annotations"),
    "DrawBalloon": ("06-drawings.html", "dimensions-and-annotations"),
    "DrawHoleCallout": ("06-drawings.html", "dimensions-and-annotations"),
}


def _on_drawing():
    """True while a drawing sheet is the active window."""
    try:
        from . import helpguide
        return bool(helpguide._drawing())
    except Exception as err:
        _log("on drawing", err)
        return False


def steps_for(key, mode=None, tab=None):
    """The 'How to use it' steps of a command, and where they came from ('pm', 'own', or a family name)."""
    from . import catalog
    cmd = catalog.BY_KEY[key]
    if mode is None or tab is None:
        mode, tab = all_keys().get(key, ("part", ""))
    if key in STEPS:
        return STEPS[key], "own"
    pm = pm_text(cmd.label) if tab not in ("Sketch", "Sketch Ink") and key not in _sketch_keys() else None
    if pm is not None:
        return list(pm[1]), "pm"
    fam = family(key, cmd, mode, tab)
    if fam == "app":
        if isinstance(cmd.call, str) and cmd.call.startswith("wb:"):
            return WORKBENCH_STEPS, "tab"
        if tab in TAB_STEPS:
            return TAB_STEPS[tab], "tab"
    return FAMILY[fam], fam


def _shortcut(cmd):
    try:
        for name in cmd.natives:
            a = Gui.Command.get(name)
            if a is not None and a.getShortcut():
                return a.getShortcut()
    except Exception as err:
        _log("shortcut", err)
    return ""


def page(key):
    """The HTML of a command's help page."""
    from . import catalog
    cmd = catalog.BY_KEY.get(key)
    if cmd is None:
        return "<h2>Help</h2><p>There is no command named %s.</p>" % _esc(key)
    mode, tab = all_keys().get(key, ("part", ""))
    steps, _src = steps_for(key, mode, tab)
    pm = pm_text(cmd.label) if tab not in ("Sketch", "Sketch Ink") and key not in _sketch_keys() else None
    what = cmd.tip or (pm[0] if pm else "")
    parts = ["<h2>%s</h2>" % _esc(cmd.label)]
    if what:
        parts.append("<p>%s</p>" % _esc(what))
    if pm and pm[0] != what:
        parts.append("<p>%s</p>" % _esc(pm[0]))
    parts.append("<h3>How to use it</h3><ul>%s</ul>" % "".join("<li>%s</li>" % _esc(s) for s in steps))
    if key in DRAWING_STEPS:
        parts.append("<h3>On a drawing sheet</h3><ul>%s</ul>" % "".join("<li>%s</li>" % _esc(s)
                                                                        for s in DRAWING_STEPS[key]))
    where = []
    if tab:
        where.append("the %s tab of the CommandManager" % _esc(tab))
    where.append("the command search box at the top right")
    short = _shortcut(cmd)
    parts.append("<p><b>Where:</b> %s.%s</p>" % (" or ".join(where),
                                                 (" <b>Shortcut:</b> %s." % _esc(short)) if short else ""))
    guide = KEY_GUIDE.get(key) or GUIDE_TAB.get(tab) or GUIDE_MODE.get(mode)
    if guide:
        parts.append("<p><b>More:</b> <a href='guide:%s#%s'>the User Guide section</a>.</p>" % guide)
    parts.append("<p><a href='run:%s'>Run it</a> | <a href='page:commands'>All commands</a> | "
                 "<a href='page:keys'>Keyboard shortcuts</a></p>" % _esc(key))
    return "".join(parts)


def coverage():
    """{source: count} over every CommandManager command, and the keys with no page (should be none)."""
    counts, missing = {}, []
    for key, (mode, tab) in all_keys().items():
        try:
            _steps, src = steps_for(key, mode, tab)
            counts[src] = counts.get(src, 0) + 1
        except Exception:
            missing.append(key)
    return counts, missing


# --------------------------------------------------------------------------- F1 and "?"
def open_pm_title():
    """The title of the PropertyManager on show (ours or a FreeCAD task panel), else ''."""
    try:
        dialog = bool(Gui.Control.activeDialog())
    except Exception:
        dialog = False
    try:
        from . import relationspm
        panels = [w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, relationspm.Panel) and w.isVisible()]
    except Exception:
        panels = []
    if not dialog and not panels:
        return ""           # a title left on show with nothing open is not a PropertyManager at work
    if panels and not dialog:
        return panels[0].title.text().strip()
    try:
        mw = Gui.getMainWindow()
        for w in mw.findChildren(QtWidgets.QLabel, "SWStyle_PMTitle"):
            if w.isVisible() and w.text().strip():
                return w.text().strip()
    except Exception as err:
        _log("pm title", err)
    return ""


def show(key):
    """Open the help on a command's page: its entry in the User Guide, else the help window."""
    try:
        from . import helpguide
        guide = helpguide.show_command(key)
        if guide is not None:
            return guide
    except Exception as err:
        _log("guide", err)
    from . import helpmenu
    win = helpmenu.show("cmd:" + key)
    return win


def show_context():
    """F1: the open PropertyManager's page (as its '?'), else the User Guide page for what is on screen."""
    title = open_pm_title()
    if title:
        try:
            from . import pmhelp
            mw = Gui.getMainWindow()
            view = None
            for w in mw.findChildren(QtWidgets.QLabel, "SWStyle_PMTitle"):
                if w.isVisible() and w.text().strip() == title:
                    view = w.window() if w.window() is not mw else w.parentWidget().parentWidget()
                    break
            return pmhelp.show(view, title)
        except Exception as err:
            _log("F1 pm", err)
    from . import helpguide
    page, anchor = helpguide.context()
    return helpguide.show(page, anchor)


def title_steps(title):
    """(what, steps) for a PropertyManager title with no hand-written page: the command of that name's
    page text, else None."""
    from . import catalog
    if title in DRAWING_TITLES and _on_drawing():
        key = DRAWING_TITLES[title]
        return DRAWING_WHAT.get(key, catalog.BY_KEY[key].tip or ""), list(DRAWING_STEPS[key])
    n = _norm(title)
    keys = all_keys()
    for key, (mode, tab) in keys.items():
        cmd = catalog.BY_KEY[key]
        if _norm(cmd.label) == n or _norm(cmd.caption) == n:
            steps, _src = steps_for(key, mode, tab)
            return cmd.tip or "", list(steps)
    return None
