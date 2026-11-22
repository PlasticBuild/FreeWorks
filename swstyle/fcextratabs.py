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

try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

# (key, label, FreeCAD commands in order of preference, tip, caption); icons come from FreeCAD's command
KEYS = (
    # ---- 2D Drafting (Draft)
    ("FCX_DLine", "Line", ("Draft_Line",), "Draws a straight 2D line on the working plane.", None),
    ("FCX_DWire", "Polyline", ("Draft_Wire",), "Draws a chain of straight segments.", None),
    ("FCX_DBSpline", "B-Spline", ("Draft_BSpline",), "Draws a smooth curve through picked points.", None),
    ("FCX_DBezier", "Bezier Curve", ("Draft_BezCurve",), "Draws a Bezier curve from control points.", None),
    ("FCX_DCubicBezier", "Cubic Bezier Curve", ("Draft_CubicBezCurve",), "Draws a Bezier curve by dragging tangents.", None),
    ("FCX_DCircle", "Circle", ("Draft_Circle",), "Draws a 2D circle from a center and a radius.", None),
    ("FCX_DArc", "Arc", ("Draft_Arc",), "Draws an arc from a center, a radius and two angles.", None),
    ("FCX_DArc3", "3-Point Arc", ("Draft_Arc_3Points",), "Draws an arc through three points.", None),
    ("FCX_DEllipse", "Ellipse", ("Draft_Ellipse",), "Draws an ellipse inside two picked corners.", None),
    ("FCX_DRectangle", "Rectangle", ("Draft_Rectangle",), "Draws a 2D rectangle from two corners.", None),
    ("FCX_DPolygon", "Polygon", ("Draft_Polygon",), "Draws a regular polygon.", None),
    ("FCX_DPoint", "Point", ("Draft_Point",), "Places a single point.", None),
    ("FCX_DFillet", "2D Fillet", ("Draft_Fillet",), "Rounds the corner between two 2D lines.", None),
    ("FCX_DHatch", "Hatch", ("Draft_Hatch",), "Fills a face with a hatch pattern.", None),
    ("FCX_DFacebinder", "Facebinder", ("Draft_Facebinder",), "Makes a surface from picked faces that follows them.", None),
    ("FCX_DText", "Text", ("Draft_Text",), "Places a multi-line text.", None),
    ("FCX_DDimension", "Dimension", ("Draft_Dimension",), "Places a Draft length, radius or angle dimension.", None),
    ("FCX_DLabel", "Label", ("Draft_Label",), "Places a leader with a text that can show object data.", None),
    ("FCX_DAnnoStyles", "Annotation Styles", ("Draft_AnnotationStyleEditor",), "Edits the text and dimension styles.",
     "Annotation\nStyles"),
    ("FCX_DMove", "Move", ("Draft_Move",), "Moves or copies objects between two points.", None),
    ("FCX_DMirror", "Mirror", ("Draft_Mirror",), "Mirrors objects about a line.", None),
    ("FCX_DOffset", "Offset", ("Draft_Offset",), "Offsets a 2D object by a distance.", None),
    ("FCX_DTrimex", "Trim/Extend", ("Draft_Trimex",), "Trims or extends a 2D object.", None),
    ("FCX_DStretch", "Stretch", ("Draft_Stretch",), "Stretches the points inside a picked box.", None),
    ("FCX_DSplit", "Split", ("Draft_Split",), "Splits a line or wire at a point.", None),
    ("FCX_DJoin", "Join", ("Draft_Join",), "Joins lines and wires that touch into one wire.", None),
    ("FCX_DUpgrade", "Upgrade", ("Draft_Upgrade",), "Joins picked objects into the next more complex kind.", None),
    ("FCX_DDowngrade", "Downgrade", ("Draft_Downgrade",), "Breaks picked objects into simpler pieces.", None),
    ("FCX_DOrthoArray", "Linear Array", ("Draft_OrthoArray",), "Copies objects in rows and columns.", "Array"),
    ("FCX_DPolarArray", "Polar Array", ("Draft_PolarArray",), "Copies objects around a center.", None),
    ("FCX_DCircularArray", "Circular Array", ("Draft_CircularArray",), "Copies objects in rings.", None),
    ("FCX_DPathArray", "Path Array", ("Draft_PathArray",), "Copies objects along a path.", None),
    ("FCX_DPathLinkArray", "Path Link Array", ("Draft_PathLinkArray",), "A path array made of links.", None),
    ("FCX_DPointArray", "Point Array", ("Draft_PointArray",), "Copies objects onto points.", None),
    ("FCX_DPointLinkArray", "Point Link Array", ("Draft_PointLinkArray",), "A point array made of links.", None),
    ("FCX_DClone", "Clone", ("Draft_Clone",), "Makes copies that follow the original.", None),
    ("FCX_DShape2D", "Shape 2D View", ("Draft_Shape2DView",), "Projects a solid flat onto a plane.", None),
    ("FCX_DToSketch", "Draft to Sketch", ("Draft_Draft2Sketch",), "Turns Draft objects into a sketch, or back.", None),
    ("FCX_DEdit", "Edit Points", ("Draft_Edit",), "Drags the points of a Draft object.", None),
    ("FCX_DWireToBSpline", "Wire to B-Spline", ("Draft_WireToBSpline",), "Turns a polyline into a B-spline, or back.", None),
    ("FCX_DSlope", "Set Slope", ("Draft_Slope",), "Gives a line a slope.", None),
    ("FCX_DFlipDim", "Flip Dimension", ("Draft_FlipDimension",), "Turns a Draft dimension's text the other way.", None),
    ("FCX_DSubelem", "Highlight Subelements", ("Draft_SubelementHighlight",), "Shows the points and edges to edit.", None),
    ("FCX_DLayers", "Layers", ("Draft_LayerManager",), "Adds, renames and styles layers.", None),
    ("FCX_DAddToLayer", "Add to Layer", ("Draft_AddToLayer",), "Moves picked objects to a layer.", None),
    ("FCX_DAddToGroup", "Add to Group", ("Draft_AddToGroup",), "Moves picked objects to a group.", None),
    ("FCX_DNamedGroup", "New Named Group", ("Draft_AddNamedGroup",), "Puts picked objects in a new named group.", None),
    ("FCX_DSelectGroup", "Select Group", ("Draft_SelectGroup",), "Selects everything in the picked group.", None),
    ("FCX_DConstruction", "Add to Construction", ("Draft_AddConstruction",), "Moves picked objects to the construction group.", None),
    ("FCX_DWPProxy", "Working Plane Proxy", ("Draft_WorkingPlaneProxy",), "Saves the working plane as an object.", None),
    ("FCX_DGrid", "Toggle Grid", ("Draft_ToggleGrid",), "Shows or hides the Draft grid.", None),
    ("FCX_DWireframe", "Toggle Wireframe", ("Draft_ToggleDisplayMode",), "Switches picked objects between wireframe and shaded.", None),
    ("FCX_DSnapLock", "Snap Lock", ("Draft_Snap_Lock",), "Turns Draft snapping on or off.", "Snaps"),
    ("FCX_DSnapEnd", "Snap Endpoint", ("Draft_Snap_Endpoint",), "Draft snap to end points.", None),
    ("FCX_DSnapMid", "Snap Midpoint", ("Draft_Snap_Midpoint",), "Draft snap to midpoints.", None),
    ("FCX_DSnapCenter", "Snap Center", ("Draft_Snap_Center",), "Draft snap to centers.", None),
    ("FCX_DSnapAngle", "Snap Angle", ("Draft_Snap_Angle",), "Draft snap to quarter points of circles.", None),
    ("FCX_DSnapInter", "Snap Intersection", ("Draft_Snap_Intersection",), "Draft snap to intersections.", None),
    ("FCX_DSnapPerp", "Snap Perpendicular", ("Draft_Snap_Perpendicular",), "Draft snap square to an edge.", None),
    ("FCX_DSnapExt", "Snap Extension", ("Draft_Snap_Extension",), "Draft snap along an edge's extension.", None),
    ("FCX_DSnapPar", "Snap Parallel", ("Draft_Snap_Parallel",), "Draft snap parallel to an edge.", None),
    ("FCX_DSnapSpecial", "Snap Special", ("Draft_Snap_Special",), "Draft snap to special points of objects.", None),
    ("FCX_DSnapNear", "Snap Near", ("Draft_Snap_Near",), "Draft snap to the nearest point on an edge.", None),
    ("FCX_DSnapOrtho", "Snap Ortho", ("Draft_Snap_Ortho",), "Draft snap at right angles.", None),
    ("FCX_DSnapGrid", "Snap Grid", ("Draft_Snap_Grid",), "Draft snap to grid points.", None),
    ("FCX_DSnapWP", "Snap Working Plane", ("Draft_Snap_WorkingPlane",), "Keeps Draft snaps on the working plane.", None),
    ("FCX_DSnapDims", "Snap Dimensions", ("Draft_Snap_Dimensions",), "Shows distances while snapping.", None),
    # ---- Part Tools (Part, PartDesign, OpenSCAD, containers)
    ("FCX_PPrimitives", "Primitives", ("Part_Primitives",), "Makes a plane, box, wedge, helix, spiral and other shapes from sizes.",
     None),
    ("FCX_PBox", "Cube", ("Part_Box",), "Makes a box solid.", None),
    ("FCX_PCylinder", "Cylinder", ("Part_Cylinder",), "Makes a cylinder solid.", None),
    ("FCX_PCone", "Cone", ("Part_Cone",), "Makes a cone solid.", None),
    ("FCX_PSphere", "Sphere", ("Part_Sphere",), "Makes a sphere solid.", None),
    ("FCX_PTorus", "Torus", ("Part_Torus",), "Makes a torus solid.", None),
    ("FCX_PTube", "Tube", ("Part_Tube",), "Makes a hollow tube solid.", None),
    ("FCX_AddBox", "Additive Box", ("SWStyle_FCXAdditiveBox",), "Adds a box to the body.", "Additive\nPrimitive"),
    ("FCX_AddCylinder", "Additive Cylinder", ("SWStyle_FCXAdditiveCylinder",), "Adds a cylinder to the body.", None),
    ("FCX_AddSphere", "Additive Sphere", ("SWStyle_FCXAdditiveSphere",), "Adds a sphere to the body.", None),
    ("FCX_AddCone", "Additive Cone", ("SWStyle_FCXAdditiveCone",), "Adds a cone to the body.", None),
    ("FCX_AddEllipsoid", "Additive Ellipsoid", ("SWStyle_FCXAdditiveEllipsoid",), "Adds an ellipsoid to the body.", None),
    ("FCX_AddTorus", "Additive Torus", ("SWStyle_FCXAdditiveTorus",), "Adds a torus to the body.", None),
    ("FCX_AddPrism", "Additive Prism", ("SWStyle_FCXAdditivePrism",), "Adds a prism to the body.", None),
    ("FCX_AddWedge", "Additive Wedge", ("SWStyle_FCXAdditiveWedge",), "Adds a wedge to the body.", None),
    ("FCX_SubBox", "Subtractive Box", ("SWStyle_FCXSubtractiveBox",), "Cuts a box out of the body.", "Subtractive\nPrimitive"),
    ("FCX_SubCylinder", "Subtractive Cylinder", ("SWStyle_FCXSubtractiveCylinder",), "Cuts a cylinder out of the body.", None),
    ("FCX_SubSphere", "Subtractive Sphere", ("SWStyle_FCXSubtractiveSphere",), "Cuts a sphere out of the body.", None),
    ("FCX_SubCone", "Subtractive Cone", ("SWStyle_FCXSubtractiveCone",), "Cuts a cone out of the body.", None),
    ("FCX_SubEllipsoid", "Subtractive Ellipsoid", ("SWStyle_FCXSubtractiveEllipsoid",), "Cuts an ellipsoid out of the body.", None),
    ("FCX_SubTorus", "Subtractive Torus", ("SWStyle_FCXSubtractiveTorus",), "Cuts a torus out of the body.", None),
    ("FCX_SubPrism", "Subtractive Prism", ("SWStyle_FCXSubtractivePrism",), "Cuts a prism out of the body.", None),
    ("FCX_SubWedge", "Subtractive Wedge", ("SWStyle_FCXSubtractiveWedge",), "Cuts a wedge out of the body.", None),
    ("FCX_PBoolean", "Boolean", ("Part_Boolean",), "Unites, cuts or intersects two shapes in a dialog.", None),
    ("FCX_PCompound", "Make Compound", ("Part_Compound",), "Groups shapes into one compound.", None),
    ("FCX_PExplode", "Explode Compound", ("Part_ExplodeCompound",), "Splits a compound into its shapes.", None),
    ("FCX_PCompFilter", "Compound Filter", ("Part_CompoundFilter",), "Keeps chosen shapes of a compound.", None),
    ("FCX_PFragments", "Boolean Fragments", ("Part_BooleanFragments",), "Splits shapes into all their pieces.", None),
    ("FCX_PSliceApart", "Slice Apart", ("Part_SliceApart",), "Cuts shapes with others into loose pieces.", None),
    ("FCX_PSlice", "Slice to Compound", ("Part_Slice",), "Cuts shapes with others into a compound.", None),
    ("FCX_PXOR", "XOR", ("Part_XOR",), "Keeps what an odd number of shapes covers.", None),
    ("FCX_PJoinConnect", "Connect Shapes", ("Part_JoinConnect",), "Joins walls of shapes, inside left open.", None),
    ("FCX_PJoinEmbed", "Embed Shapes", ("Part_JoinEmbed",), "Sinks one walled shape into another.", None),
    ("FCX_PJoinCutout", "Cutout for Shape", ("Part_JoinCutout",), "Cuts a walled shape's room out of another.", None),
    ("FCX_PMirror", "Mirror Shape", ("Part_Mirror",), "Mirrors a shape about a plane as a new object.", None),
    ("FCX_POffset", "3D Offset", ("Part_Offset",), "Offsets a whole shape outward or inward.", None),
    ("FCX_POffset2D", "2D Offset", ("Part_Offset2D",), "Offsets a flat face or wire.", None),
    ("FCX_PColorFace", "Appearance per Face", ("Part_ColorPerFace",), "Gives single faces their own color.", None),
    ("FCX_PDClone", "Body Clone", ("PartDesign_Clone",), "Makes a body that copies another body's shape.", None),
    ("FCX_Refine", "Refine Shape", ("OpenSCAD_RefineShapeFeature", "Part_RefineShape"),
     "Merges faces that lie in one surface.", None),
    ("FCX_IncTol", "Increase Tolerance", ("OpenSCAD_IncreaseToleranceFeature",), "Raises a shape's tolerance.", None),
    ("FCX_ExplodeGroup", "Explode Group", ("OpenSCAD_ExplodeGroup",), "Breaks up a fused group.", None),
    ("FCX_ReplaceObj", "Replace Object", ("OpenSCAD_ReplaceObject",), "Swaps one object in a feature's inputs for another.", None),
    ("FCX_RemoveTree", "Remove with Children", ("OpenSCAD_RemoveSubtree",), "Deletes objects and what they are made from.", None),
    ("FCX_StdPart", "New Part Container", ("Std_Part",), "Adds a Part container with its own placement.", None),
    ("FCX_StdGroup", "New Group", ("Std_Group",), "Adds a group folder to the tree.", None),
    ("FCX_VarSet", "Variable Set", ("Std_VarSet",), "Adds a set of variables for expressions.", None),
    # ---- Mesh Tools
    ("FCX_MUnion", "Mesh Union", ("Mesh_Union",), "Joins two meshes.", None),
    ("FCX_MDifference", "Mesh Difference", ("Mesh_Difference",), "Cuts one mesh out of another.", None),
    ("FCX_MIntersection", "Mesh Intersection", ("Mesh_Intersection",), "Keeps what two meshes share.", None),
    ("FCX_MTrim", "Trim Mesh", ("Mesh_PolyTrim",), "Cuts facets inside a drawn loop.", None),
    ("FCX_MAddFacet", "Add Triangle", ("Mesh_AddFacet",), "Adds one facet at a hole's edge.", None),
    ("FCX_MCloseHole", "Close Hole", ("Mesh_FillInteractiveHole",), "Closes the hole you click.", None),
    ("FCX_MFlip", "Flip Normals", ("Mesh_FlipNormals",), "Turns every facet the other way.", None),
    ("FCX_MRemesh", "Remesh", ("Mesh_RemeshGmsh",), "Makes the mesh again with even facets (Gmsh).", None),
    ("FCX_MMerge", "Merge Meshes", ("Mesh_Merge",), "Puts picked meshes into one.", None),
    ("FCX_MSplit", "Split by Components", ("Mesh_SplitComponents",), "Makes each loose piece its own mesh.", None),
    ("FCX_MEvalSolid", "Check Solid", ("Mesh_EvaluateSolid",), "Tells whether the mesh is closed.", None),
    ("FCX_MFaceInfo", "Facet Info", ("Mesh_EvaluateFacet",), "Shows data of the facet you click.", None),
    ("FCX_MBox", "Bounding Box", ("Mesh_BoundingBox",), "Shows the mesh's size.", None),
    ("FCX_MRegular", "Regular Solid", ("Mesh_BuildRegularSolid",), "Makes a mesh cube, sphere, cylinder or other shape.", None),
    ("FCX_MExport", "Export Mesh", ("Mesh_Export",), "Saves the mesh as STL, OBJ, PLY or another format.", None),
    ("FCX_PtsExport", "Export Points", ("Points_Export",), "Saves a point cloud.", None),
    # ---- FreeCAD Utilities
    ("FCX_SNew", "New Spreadsheet", ("Spreadsheet_CreateSheet",), "Adds a spreadsheet to the document.", "Spreadsheet"),
    ("FCX_SImport", "Import Spreadsheet", ("Spreadsheet_Import",), "Reads a CSV file into a new spreadsheet.", None),
    ("FCX_SExport", "Export Spreadsheet", ("Spreadsheet_Export",), "Saves the open spreadsheet as CSV.", None),
    ("FCX_SAlias", "Set Alias", ("Spreadsheet_SetAlias",), "Names a cell so expressions can use it.", None),
    ("FCX_SMerge", "Merge Cells", ("Spreadsheet_MergeCells",), "Joins the picked cells into one.", None),
    ("FCX_SSplit", "Split Cell", ("Spreadsheet_SplitCell",), "Splits a merged cell again.", None),
    ("FCX_SBold", "Bold", ("Spreadsheet_StyleBold",), "Bold text in the picked cells.", None),
    ("FCX_SItalic", "Italic", ("Spreadsheet_StyleItalic",), "Italic text in the picked cells.", None),
    ("FCX_SUnderline", "Underline", ("Spreadsheet_StyleUnderline",), "Underlined text in the picked cells.", None),
    ("FCX_SLeft", "Align Left", ("Spreadsheet_AlignLeft",), "Puts cell text at the left.", "Align"),
    ("FCX_SCenter", "Align Center", ("Spreadsheet_AlignCenter",), "Centers cell text across.", None),
    ("FCX_SRight", "Align Right", ("Spreadsheet_AlignRight",), "Puts cell text at the right.", None),
    ("FCX_STop", "Align Top", ("Spreadsheet_AlignTop",), "Puts cell text at the top.", None),
    ("FCX_SVCenter", "Align Middle", ("Spreadsheet_AlignVCenter",), "Centers cell text up and down.", None),
    ("FCX_SBottom", "Align Bottom", ("Spreadsheet_AlignBottom",), "Puts cell text at the bottom.", None),
    ("FCX_AInsert", "FreeCAD Insert Component", ("Assembly_Insert",), "FreeCAD's own dialog for adding parts to an assembly.",
     None),
    ("FCX_ASolve", "Solve Assembly", ("Assembly_SolveAssembly",), "Solves the assembly's joints again.", None),
    ("FCX_AGearBelt", "Gear/Belt Joint", ("Assembly_CreateJointGearBelt",), "Ties two turning parts like gears or a belt.",
     None),
    ("FCX_DatumCS", "Coordinate System", ("Part_CoordinateSystem",), "Adds a Part coordinate system.", "Datums"),
    ("FCX_DatumPlane", "Part Datum Plane", ("Part_DatumPlane",), "Adds a Part datum plane.", None),
    ("FCX_DatumLine", "Part Datum Line", ("Part_DatumLine",), "Adds a Part datum line.", None),
    ("FCX_DatumPoint", "Part Datum Point", ("Part_DatumPoint",), "Adds a Part datum point.", None),
    ("FCX_SurfSections", "Surface from Sections", ("Surface_Sections",), "A surface through picked section edges.", None),
    ("FCX_CurveOnMesh", "Curve on Mesh", ("Surface_CurveOnMesh",), "Draws a spline that lies on a mesh.", None),
    ("FCX_MaterialEdit", "Material Editor", ("Material_Edit",), "Opens FreeCAD's material library editor.", None),
    ("FCX_TSyncView", "Sync View", ("Std_TreeSyncView",), "The 3D view follows the tree's picked document.", "Tree\nOptions"),
    ("FCX_TSyncSel", "Sync Selection", ("Std_TreeSyncSelection",), "The tree scrolls to what is picked in 3D.", None),
    ("FCX_TSyncPlace", "Sync Placement", ("Std_TreeSyncPlacement",), "Dragging in the tree keeps where objects are.", None),
    ("FCX_TPreSel", "Tree Preselection", ("Std_TreePreSelection",), "Hovering a tree row highlights it in 3D.", None),
    ("FCX_TRecSel", "Record Selection", ("Std_TreeRecordSelection",), "Remembers picks for Back and Forward.", None),
    ("FCX_TSingle", "Single Document", ("Std_TreeSingleDocument",), "The tree shows only the active document.", None),
    ("FCX_TMulti", "Multi Document", ("Std_TreeMultiDocument",), "The tree shows every open document.", None),
    ("FCX_TCollapseDoc", "Collapse/Expand Document", ("Std_TreeCollapseDocument",), "Folds documents as they switch.", None),
    ("FCX_TDrag", "Start Dragging", ("Std_TreeDrag",), "Drags the picked tree rows.", None),
    ("FCX_TGoSel", "Go to Selection", ("Std_TreeSelection",), "Scrolls the tree to what is picked.", None),
    ("FCX_TBack", "Selection Back", ("Std_SelBack",), "Goes back to the pick before.", None),
    ("FCX_TForward", "Selection Forward", ("Std_SelForward",), "Goes forward to the next pick.", None),
    ("FCX_RCreate", "Place Robot", ("Robot_Create",), "Adds a robot from FreeCAD's library.", "Robot"),
    ("FCX_RTraj", "Trajectory", ("Robot_CreateTrajectory",), "Adds an empty robot trajectory.", None),
    ("FCX_RWaypoint", "Insert in Trajectory", ("Robot_InsertWaypoint",), "Adds the robot's pose as a waypoint.", None),
    ("FCX_RWaypointPre", "Insert at Preselection", ("Robot_InsertWaypointPreselect",), "Adds the hovered point as a waypoint.",
     None),
    ("FCX_REdge", "Edge to Trajectory", ("Robot_Edge2Trac",), "Makes a trajectory from picked edges.", None),
    ("FCX_RDressUp", "Dress-Up Trajectory", ("Robot_TrajectoryDressUp",), "Changes speed and tool of a trajectory.", None),
    ("FCX_RCompound", "Trajectory Compound", ("Robot_TrajectoryCompound",), "Joins trajectories into one.", None),
    ("FCX_RSimulate", "Simulate Trajectory", ("Robot_Simulate",), "Plays the trajectory on the robot.", None),
    ("FCX_RSetHome", "Set Home Position", ("Robot_SetHomePos",), "Saves the robot's pose as home.", None),
    ("FCX_RHome", "Move to Home", ("Robot_RestoreHomePos",), "Puts the robot back home.", None),
    ("FCX_Test", "Self-Test", ("Test_Test",), "Runs FreeCAD's own test dialog.", "Self-\nTest"),
    ("FCX_TestAll", "Test All", ("Test_TestAll",), "Runs all of FreeCAD's tests.", None),
    ("FCX_TestBase", "Test Base", ("Test_TestBase",), "Runs FreeCAD's base tests.", None),
    ("FCX_TestDoc", "Test Document", ("Test_TestDoc",), "Runs FreeCAD's document tests.", None),
)


def L(key, fly=None):
    return ("large", key, fly)


def ST(*keys):
    return ("stack", tuple((k, None) if isinstance(k, str) else k for k in keys))


SEP = ("sep",)
SNAPS = ("FCX_DSnapLock", "FCX_DSnapEnd", "FCX_DSnapMid", "FCX_DSnapCenter", "FCX_DSnapAngle", "FCX_DSnapInter",
         "FCX_DSnapPerp", "FCX_DSnapExt", "FCX_DSnapPar", "FCX_DSnapSpecial", "FCX_DSnapNear", "FCX_DSnapOrtho",
         "FCX_DSnapGrid", "FCX_DSnapWP", "FCX_DSnapDims")
ARRAYS = ("FCX_DOrthoArray", "FCX_DPolarArray", "FCX_DCircularArray", "FCX_DPathArray", "FCX_DPathLinkArray",
          "FCX_DPointArray", "FCX_DPointLinkArray")
ADDITIVE = ("FCX_AddBox", "FCX_AddCylinder", "FCX_AddSphere", "FCX_AddCone", "FCX_AddEllipsoid", "FCX_AddTorus",
            "FCX_AddPrism", "FCX_AddWedge")
SUBTRACTIVE = tuple(k.replace("FCX_Add", "FCX_Sub") for k in ADDITIVE)

ALIGN = ("FCX_SLeft", "FCX_SCenter", "FCX_SRight", "FCX_STop", "FCX_SVCenter", "FCX_SBottom")
TREE = ("FCX_TSyncView", "FCX_TSyncSel", "FCX_TSyncPlace", "FCX_TPreSel", "FCX_TRecSel", "FCX_TSingle", "FCX_TMulti",
        "FCX_TCollapseDoc", "FCX_TDrag", "FCX_TGoSel", "FCX_TBack", "FCX_TForward")
DATUMS = ("FCX_DatumCS", "FCX_DatumPlane", "FCX_DatumLine", "FCX_DatumPoint")
TESTS = ("FCX_Test", "FCX_TestAll", "FCX_TestBase", "FCX_TestDoc")


TABS = {
    "2D Drafting": (
        L("FCX_DLine", ("FCX_DLine", "FCX_DWire", "FCX_DBSpline", "FCX_DBezier", "FCX_DCubicBezier")),
        L("FCX_DCircle", ("FCX_DCircle", "FCX_DArc", "FCX_DArc3", "FCX_DEllipse")),
        ST("FCX_DRectangle", "FCX_DPolygon", "FCX_DPoint"), ST("FCX_DFillet", "FCX_DHatch", "FCX_DFacebinder"),
        SEP,
        ST("FCX_DText", "FCX_DDimension", "FCX_DLabel"), L("FCX_DAnnoStyles"),
        SEP,
        ST("FCX_DMove", "FCX_DMirror", "FCX_DOffset"), ST("FCX_DTrimex", "FCX_DStretch", "FCX_DSplit"),
        ST("FCX_DJoin", "FCX_DUpgrade", "FCX_DDowngrade"), L("FCX_DOrthoArray", ARRAYS),
        ST("FCX_DClone", "FCX_DShape2D", "FCX_DToSketch"), ST("FCX_DEdit", "FCX_DWireToBSpline", "FCX_DSlope"),
        ST("FCX_DFlipDim", "FCX_DSubelem"),
        SEP,
        L("FCX_DLayers"), ST("FCX_DAddToLayer", "FCX_DAddToGroup", "FCX_DNamedGroup"),
        ST("FCX_DSelectGroup", "FCX_DConstruction", "FCX_DWPProxy"), ST("FCX_DGrid", "FCX_DWireframe"),
        L("FCX_DSnapLock", SNAPS),
    ),
    "Part Tools": (
        L("FCX_PPrimitives"), ST("FCX_PBox", "FCX_PCylinder", "FCX_PCone"), ST("FCX_PSphere", "FCX_PTorus", "FCX_PTube"),
        L("FCX_AddBox", ADDITIVE), L("FCX_SubBox", SUBTRACTIVE),
        SEP,
        L("FCX_PBoolean"), ST("FCX_PCompound", "FCX_PExplode", "FCX_PCompFilter"),
        ST("FCX_PFragments", "FCX_PSliceApart", "FCX_PSlice"), ST("FCX_PXOR", "FCX_PJoinConnect", "FCX_PJoinEmbed"),
        ST("FCX_PJoinCutout"),
        SEP,
        ST("FCX_PMirror", "FCX_POffset", "FCX_POffset2D"), ST("FCX_PColorFace", "FCX_PDClone", "FCX_Refine"),
        ST("FCX_IncTol", "FCX_ExplodeGroup", "FCX_ReplaceObj"), ST("FCX_RemoveTree"),
        SEP,
        ST("FCX_StdPart", "FCX_StdGroup", "FCX_VarSet"),
    ),
    "Mesh Tools": (
        ST("FCX_MUnion", "FCX_MDifference", "FCX_MIntersection"),
        SEP,
        ST("FCX_MTrim", "FCX_MAddFacet", "FCX_MCloseHole"), ST("FCX_MFlip", "FCX_MRemesh"),
        ST("FCX_MMerge", "FCX_MSplit"),
        SEP,
        ST("FCX_MEvalSolid", "FCX_MFaceInfo", "FCX_MBox"),
        SEP,
        L("FCX_MRegular"), ST("FCX_MExport", "FCX_PtsExport"),
    ),
    "FreeCAD Utilities": (
        L("FCX_SNew"), ST("FCX_SImport", "FCX_SExport", "FCX_SAlias"), ST("FCX_SMerge", "FCX_SSplit"),
        ST("FCX_SBold", "FCX_SItalic", "FCX_SUnderline"), L("FCX_SLeft", ALIGN),
        SEP,
        ST("FCX_AInsert", "FCX_ASolve", "FCX_AGearBelt"), L("FCX_DatumCS", DATUMS),
        ST("FCX_SurfSections", "FCX_CurveOnMesh", "FCX_MaterialEdit"),
        SEP,
        L("FCX_TSyncView", TREE),
        SEP,
        L("FCX_RCreate"), ST("FCX_RTraj", "FCX_RWaypoint", "FCX_RWaypointPre"), ST("FCX_REdge", "FCX_RDressUp", "FCX_RCompound"),
        ST("FCX_RSimulate", "FCX_RSetHome", "FCX_RHome"),
        SEP,
        L("FCX_Test", TESTS),
    ),
}

# where each tab's commands come from: (workbench, modules that register them, a command it has)
SOURCES = {
    "Draft": (("DraftWorkbench", ("DraftTools",), "Draft_Line"),),
    "PartTools": (("PartWorkbench", ("PartGui",), "Part_Tube"),
                  ("PartWorkbench", ("CompoundTools._CommandCompoundFilter", "CompoundTools._CommandExplodeCompound"),
                   "Part_CompoundFilter"),
                  ("PartDesignWorkbench", ("PartDesignGui",), "PartDesign_CompPrimitiveAdditive"),
                  ("OpenSCADWorkbench", (), "OpenSCAD_RefineShapeFeature")),
    "MeshTools": (("MeshWorkbench", ("Mesh", "MeshGui"), "Mesh_Union"),
                  ("PointsWorkbench", ("Points", "PointsGui"), "Points_Export")),
}
SOURCES["Utilities"] = (("SpreadsheetWorkbench", ("Spreadsheet", "SpreadsheetGui"), "Spreadsheet_MergeCells"),
                        ("AssemblyWorkbench", (), "Assembly_SolveAssembly"),
                        ("PartWorkbench", ("PartGui",), "Part_CoordinateSystem"),
                        ("SurfaceWorkbench", ("Surface", "SurfaceGui"), "Surface_Sections"),
                        ("MaterialWorkbench", ("Materials", "MatGui"), "Material_Edit"),
                        ("RobotWorkbench", ("Robot", "RobotGui"), "Robot_Create"),
                        ("TestWorkbench", ("TestGui",), "Test_Test"))
PREFIXES = {"Utilities": ("Spreadsheet_", "Robot_", "Test_", "Assembly_", "Surface_", "Material_"), "Draft": ("Draft_",), "PartTools": ("Part_", "OpenSCAD_"), "MeshTools": ("Mesh_", "Points_")}
TAB_SOURCE = {"2D Drafting": "Draft", "Part Tools": "PartTools", "Mesh Tools": "MeshTools", "FreeCAD Utilities": "Utilities"}
ORDER = ("2D Drafting", "Part Tools", "Mesh Tools", "FreeCAD Utilities")
ASM = ("FreeCAD Utilities",)
SEEN = "FCExtraTabsSeen"
SHAPES = ("Box", "Cylinder", "Sphere", "Cone", "Ellipsoid", "Torus", "Prism", "Wedge")   # FreeCAD's action order


class PrimitiveCommand:
    """One PartDesign additive/subtractive primitive. FreeCAD has them only as actions of one group
    button (PartDesign_CompPrimitiveAdditive), so each gets its own command here for the flyout."""

    def __init__(self, kind, index):
        self.kind, self.index = kind, index
        self.group = "PartDesign_CompPrimitive" + kind

    def GetResources(self):
        shape = SHAPES[self.index]
        return {"MenuText": "%s %s" % (self.kind, shape), "Pixmap": "PartDesign_%s%s" % (self.kind, shape),
                "ToolTip": ("Adds a %s to the active body." if self.kind == "Additive"
                            else "Cuts a %s out of the active body.") % shape.lower()}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        cmd = Gui.Command.get(self.group)
        if cmd is None or len(cmd.getAction()) <= self.index:
            App.Console.PrintWarning("FreeCAD: Part Design primitives are not loaded yet\n")
            return
        Gui.runCommand(self.group, self.index)


def _add_commands():
    have = Gui.listCommands()
    for kind in ("Additive", "Subtractive"):
        for i, shape in enumerate(SHAPES):
            name = "SWStyle_FCX%s%s" % (kind, shape)
            if name not in have:
                Gui.addCommand(name, PrimitiveCommand(kind, i))


def _hide_once(cmtabs):
    """New tabs start hidden, also for someone who already saved a tab choice (once only)."""
    p = App.ParamGet(cmtabs.PREFS)
    if p.GetBool(SEEN, False):
        return
    if p.GetBool("Saved", False):
        have = [t for t in p.GetString("HiddenTabs", "").split("|") if t]
        p.SetString("HiddenTabs", "|".join(have + [t for t in ORDER if t not in have]))
    if p.GetBool("AsmSaved", False):
        have = [t for t in p.GetString("AsmHiddenTabs", "").split("|") if t]
        p.SetString("AsmHiddenTabs", "|".join(have + [t for t in ASM if t not in have]))
    p.SetBool(SEEN, True)


def _hook_assembly():
    from . import asmtabs, cmtabs
    if getattr(asmtabs.every_tab, "_fw_fcx", False):
        return
    order = list(asmtabs.ORDER)
    at = order.index("Add-Ins") if "Add-Ins" in order else len(order)
    for t in ASM:
        if t not in order:
            order.insert(at, t)
            at += 1
    asmtabs.ORDER = tuple(order)
    asmtabs.DEFAULT_HIDDEN = tuple(asmtabs.DEFAULT_HIDDEN) + tuple(t for t in ASM if t not in asmtabs.DEFAULT_HIDDEN)
    original = asmtabs.every_tab

    def every_tab(part_tabs):
        tabs = dict(original(part_tabs))
        for t in ASM:
            if t in cmtabs.TABS:
                tabs[t] = cmtabs.TABS[t]
        return [(t, tabs[t]) for t in asmtabs.ORDER if t in tabs]

    every_tab._fw_fcx = True
    asmtabs.every_tab = every_tab


def install():
    if Gui is None:
        return
    try:
        _install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: FreeCAD tool tabs not added (%s)\n" % error)


def _install():
    from . import addintabs, catalog, cmtabs
    if "FCX_DLine" in catalog.BY_KEY and "2D Drafting" in cmtabs.TABS:
        return
    _add_commands()
    for key, label, natives, tip, caption in KEYS:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, natives, None, tip, caption=caption)
    catalog.ALL = tuple(catalog._ALL)
    # addintabs loads a tab's workbench on first show and drops buttons this install lacks
    addintabs.SOURCES.update(SOURCES)
    addintabs.PREFIXES.update(PREFIXES)
    addintabs.TAB_SOURCE.update(TAB_SOURCE)
    for title, layout in TABS.items():
        addintabs.TABS.setdefault(title, layout)
        cmtabs.TABS.setdefault(title, layout)
    addintabs.MINE = tuple(addintabs.MINE) + tuple(k[0] for k in KEYS if k[0] not in addintabs.MINE)
    order = [t for t in cmtabs.ORDER if t not in ORDER]
    at = order.index("Add-Ins") if "Add-Ins" in order else len(order)
    cmtabs.ORDER = tuple(order[:at]) + ORDER + tuple(order[at:])
    cmtabs.DEFAULT_HIDDEN = tuple(cmtabs.DEFAULT_HIDDEN) + tuple(t for t in ORDER if t not in cmtabs.DEFAULT_HIDDEN)
    try:
        _hook_assembly()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: FreeCAD Utilities in assemblies: %s\n" % error)
    _hide_once(cmtabs)
    try:
        addintabs._hook_page_shown()
    except Exception as _fw_err:
        _fw_log("fcextratabs.py:450", _fw_err)
    cmtabs.apply(rebuild=cmtabs._shell() is not None)
