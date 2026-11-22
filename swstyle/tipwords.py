# SPDX-License-Identifier: LGPL-2.1-or-later
""




REWORDS = {
    "Home": "Opens the Welcome page: new and recent files, learning, alerts.",
    "New": "Starts a new part, assembly or drawing.",
    "Customize": "Sets up toolbars, shortcut bars, menus, keys and mouse gestures.",
    "BossExtrude": "Pushes a sketch out into a solid, one way or both.",
    "BossRevolve": "Spins a sketch round an axis into a solid.",
    "BossSweep": "Drags a closed profile along a path to make a solid.",
    "BossLoft": "Blends two or more profiles into a solid.",
    "BossBoundary": "Builds a solid through profiles, shaped by guide curves.",
    "CutExtrude": "Pushes a sketch through the part to cut it, one way or both.",
    "Hole": "Puts a standard hole in the part, sized from a table.",
    "CutRevolve": "Spins a sketch round an axis to cut away material.",
    "CutSweep": "Drags a closed profile along a path to cut.",
    "CutLoft": "Cuts away the blend between two or more profiles.",
    "CutBoundary": "Cuts through profiles, shaped by guide curves.",
    "Fillet": "Rounds the picked edges.",
    "Chamfer": "Bevels the picked edges.",
    "LinearPattern": "Repeats features along one or two directions.",
    "CircularPattern": "Repeats features round an axis.",
    "Mirror": "Copies features across a plane or flat face.",
    "Rib": "Adds a thin supporting wall from an open sketch line.",
    "Draft": "Tilts faces by an angle so the part releases from a mould.",
    "Shell": "Hollows a solid, leaving walls of a chosen thickness.",
    "Thicken": "Gives a surface thickness, making a solid.",
    "DeleteKeepBody": "Removes bodies, or keeps only the ones you pick.",
    "Dome": "Raises a dome on a face.",
    "Thread": "Adds a helical thread to a round edge, cut in or built up.",
    "CosmeticThread": "Shows a thread on a shaft or hole without modelling it.",
    "Sketch": "Starts a new sketch, or edits an existing one.",
    "ExitSketch": "Leaves the sketch, keeping every change.",
    "Exit3DSketch": "Leaves the 3D sketch, keeping every change.",
    "SmartDimension": "Dimensions the picked sketch entities.",
    "Line": "Draws lines; keep clicking to chain them, or drag back over the end for an arc.",
    "MidpointLine": "Draws a line outward from its middle point.",
    "Circle": "Draws a circle: click the centre, then drag for the radius.",
    "PerimeterCircle": "Draws a circle through three points.",
    "CornerRectangle": "Draws a rectangle from two corners.",
    "CenterRectangle": "Draws a rectangle out from its centre.",
    "CenterArc": "Draws an arc: centre, start, then end.",
    "ThreePointArc": "Draws an arc through three points.",
    "Ellipse": "Draws a whole ellipse.",
    "Slot": "Draws a straight slot.",
    "CenterpointSlot": "Draws a straight slot out from its centre.",
    "Polygon": "Draws a regular polygon with the number of sides you set.",
    "SketchFillet": "Rounds the corner where two sketch entities meet.",
    "SketchPoint": "Places a point.",
    "Trim": "Cuts a sketch entity back to another, or stretches it to meet one.",
    "Convert": "Copies model edges or sketch entities into the sketch.",
    "Offset": "Draws entities a set distance from faces, edges or sketch entities.",
    "MirrorEntities": "Copies entities across a centerline.",
    "LinearSketchPattern": "Repeats sketch entities in rows and columns.",
    "MoveEntities": "Moves the picked sketch entities.",
    "CopyEntities": "Copies the picked sketch entities.",
    "Relations": "Lists the relations of the picked entities so they can be reviewed or deleted.",
    "AddRelation": "Ties the picked entities together with a relation.",
    "Suppress": "Turns the picked features and those built on them off; they stay in the tree, greyed.",
    "Unsuppress": "Turns suppressed features back on.",
    "UnsuppressWithDependents": "Turns the picked features and those built on them back on.",
    "ZoomFit": "Fits the whole model in the window.",
    "ZoomArea": "Zooms to a box you drag.",
    "PreviousView": "Goes back to the previous view.",
    "SectionView": "Cuts the model open along a plane or face to look inside.",
    "HideShowItems": "Switches items in the graphics area on and off.",
    "EditAppearance": "Changes the colour and finish of the picked item.",
    "ApplyScene": "Chooses the background scene.",
    "MassProperties": "Reports mass, volume, surface area and centre of mass of the selection.",
    "Measure": "Measures distance, angle, radius and size between picked items.",
    "Interference": "Finds where the bodies of the part overlap.",
    "Check": "Looks for invalid geometry in the picked bodies, or every visible body.",
    "SM_BaseFlange": "Starts the sheet metal body from a sketch, or adds a tab to it.",
    "SM_EdgeFlange": "Folds a flange up from one or more edges.",
    "SM_Hem": "Folds an edge back over itself.",
    "SM_Unfold": "Flattens the bends you pick so cuts can cross them.",
    "SM_Flatten": "Shows the part as its flat pattern.",
    "SM_BreakCorner": "Rounds or bevels the corners of the sheet.",
    "WE_WeldBead": "Lays a weld bead along a path, with its weld data.",
    "WE_CutList": "Lists the members with their lengths.",
    "ZoomFit": "Fits the whole model in the window.",
    "DrawZoomFit": "Fits the whole sheet in the window.",
    "DrawZoomArea": "Zooms to a box you drag on the sheet.",
    "DrawPreviousView": "Goes back to the previous zoom of the sheet.",
    "DisplayStyle": "How the model is drawn: shaded with edges, shaded, hidden lines removed or visible, or wireframe.",
}


def apply():
    """Puts the words into the catalog; returns how many tips changed."""
    from . import catalog
    n = 0
    for key, tip in REWORDS.items():
        cmd = catalog.BY_KEY.get(key)
        if cmd is not None and cmd.tip != tip:
            cmd.tip = tip
            n += 1
    return n
