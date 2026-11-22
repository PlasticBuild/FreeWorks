# SPDX-License-Identifier: LGPL-2.1-or-later
""








class Cmd:
    __slots__ = ("key", "label", "natives", "icon", "tip", "call", "caption")

    def __init__(self, key, label, natives=(), icon=None, tip=None, call=None, caption=None):
        self.key = key
        self.label = label
        self.natives = tuple(natives)
        self.icon = icon
        self.tip = tip
        self.call = call
        self.caption = caption or label


_ALL = []


def c(key, label, natives=(), icon=None, tip=None, call=None, caption=None):
    cmd = Cmd(key, label, natives, icon, tip, call, caption)
    _ALL.append(cmd)
    return cmd


# ---- Quick access row --------------------------------------------------------------
c("Home", "Welcome to FreeCAD", ("SWStyle_Welcome", "Start_Start", "Std_Start"), "TASKPANE_HOME_TAB",
  "Opens the Welcome dialog: new and recent documents, learning and alerts.")
c("New", "New", ("SWStyle_NewDocument", "Std_New"), "STANDARD_NEW", "Create a new document.")
c("MakeDrawing", "Make Drawing from Part/Assembly", ("SWStyle_MakeDrawingFromPart",), "MAKE_DRAWING_FROM_PART",
  "Makes a drawing of the active part or assembly with its standard three views.")
c("MakeAssembly", "Make Assembly from Part/Assembly", ("SWStyle_MakeAssemblyFromPart",), "MAKE_ASSEMBLY_FROM_PART",
  "Makes a new assembly and starts Begin Assembly with the active part picked.")
c("Open", "Open", ("SWStyle_Open", "Std_Open",), "STANDARD_OPEN")
c("RecentFiles", "Recent Documents", ("SWStyle_BrowseRecentDocuments", "Std_RecentFiles"), "STANDARD_OPEN")
c("Save", "Save", ("SWStyle_Save", "Std_Save"), "STANDARD_SAVE")
c("SaveAs", "Save As", ("SWStyle_SaveAs", "Std_SaveAs",), "STANDARD_SAVEAS")
c("SaveAll", "Save All", ("SWStyle_SaveAll", "Std_SaveAll"), "STANDARD_SAVEALL")     # extapps78
c("SaveCopy", "Save a Copy", ("Std_SaveCopy",), "STANDARD_SAVE_WITH_OPTIONS_SWXPB")
c("Export", "Export", ("Std_Export",), "STANDARD_SAVEAS")
c("Import", "Import", ("Std_Import",), "STANDARD_OPEN")
c("Print", "Print", ("SWStyle_Print", "Std_Print"), "STANDARD_PRINT")
c("PrintPreview", "Print Preview", ("SWStyle_PrintPreview", "Std_PrintPreview"), "STANDARD_PRINT_PREVIEW")

c("PageSetup", "Page Setup", ("SWStyle_PageSetup",), "STANDARD_PAGE_SETUP",
  "Sets the paper, orientation, scale and margins for printing.")
c("Print3D", "Print3D", ("SWStyle_Print3D",), "STANDARD_PRINT3D", "Sends the part to a 3D printer through the slicer.")
c("PrintPdf", "Export PDF", ("Std_PrintPdf",), "STANDARD_PRINT")
c("Undo", "Undo", ("Std_Undo",), "STANDARD_UNDO")
c("Redo", "Redo", ("Std_Redo",), "STANDARD_REDO")
c("Select", "Select", (), "STANDARD_SELECT", "Select (press Esc to clear the selection).", call="clear_selection")
c("BoxSelect", "Box Selection", ("SWStyle_BoxSelection", "Std_BoxSelection"), "STANDARD_SELECT_OVER_GEOMETRY",
  "Drag in the graphics area to pick with a box: to the right picks what is wholly inside, to the left what it touches.")
c("LassoSelect", "Lasso Selection", ("SWStyle_LassoSelection",), "LASSO_SELECTION",
  "Drag in the graphics area to pick with a free loop: clockwise picks what is wholly inside, anticlockwise what it touches.")
c("BoxElementSelect", "Box Element Selection", ("Std_BoxElementSelection",), "SELECTIONFILTER_FACES")
c("MagnifiedSelection", "Magnified Selection", ("SWStyle_MagnifiedSelection",), None,
  "Shows a magnifying glass at the pointer (G) to pick small items without zooming the view.")
c("SelectAll", "Select All", ("Std_SelectAll",), "STANDARD_SELECT_ENTIRE_DOC")
c("Rebuild", "Rebuild", ("SWStyle_Rebuild", "Std_Refresh"), "STANDARD_REBUILD", "Rebuilds the features that changed. Ctrl+Q rebuilds every feature; What's Wrong lists any that failed.")
c("WhatsWrong", "What's Wrong", ("SWStyle_WhatsWrong",), "STANDARD_REBUILD", "Lists the features that failed to rebuild, with the reason for each.")
c("FileProperties", "File Properties", ("Std_ProjectInfo",), "STANDARD_FILE_PROP")
c("Options", "Options", ("SWStyle_Options", "Std_DlgPreferences"), "STANDARD_OPTIONS")
c("Customize", "Customize", ("SWStyle_Customize", "Std_DlgCustomize"), "STANDARD_OPTIONS",
  "Customizes toolbars, shortcut bars, commands, menus, keyboard shortcuts and mouse gestures.")
c("Macros", "Macros", ("Std_DlgMacroExecute",), "TOOLS_EQNS")

c("MacroRun", "Run Macro", ("SWStyle_MacroRun",), "TOOLS_EQNS", "Runs a macro file.")     # extapps91
c("MacroRecord", "Record Macro", ("Std_DlgMacroRecord",), "TOOLS_EQNS", "Starts recording what you do into a macro file.")
c("MacroStop", "Stop Macro Recording", ("SWStyle_MacroStop",), "TOOLS_EQNS", "Stops recording the macro and saves it.")
c("MacroNew", "New Macro", ("SWStyle_MacroNew",), "TOOLS_EQNS", "Makes a new macro file and opens it to write.")
c("MacroEdit", "Edit Macro", ("SWStyle_MacroEdit",), "TOOLS_EQNS", "Opens a macro file to change it.")
c("MacroNewButton", "New Macro Button...", ("SWStyle_MacroNewButton",), "TOOLS_EQNS",
  "Makes a toolbar button that runs a macro file you pick, with its own name, tooltip, prompt and icon.")
c("AddonManager", "Add-Ins", ("Std_AddonMgr",), "FLYOUT_ADD_INS")
c("Help", "Help", ("Std_WhatsThis", "Std_OnlineHelp"), "STANDARD_HELP")

# ---- Features tab ------------------------------------------------------------------
NA = "Not available in FreeCAD yet."
c("BossExtrude", "Extruded Boss/Base", ("PartDesign_Pad",), "FEATURES_EXTRUDE_BOSS",
  "Extrudes a sketch or selected sketch contours in one or two directions to create a solid feature.",
  caption="Extruded\nBoss/Base")
c("BossRevolve", "Revolved Boss/Base", ("PartDesign_Revolution",), "FEATURES_REVOLVED_BOSS_BASE",
  "Revolves a sketch or selected sketch contours around an axis to create a solid feature.",
  caption="Revolved\nBoss/Base")
c("BossSweep", "Swept Boss/Base", ("PartDesign_AdditivePipe",), "FEATURES_SWEPT_BOSS",
  "Sweeps a closed profile along an open or closed path to create a solid feature.")
c("BossLoft", "Lofted Boss/Base", ("PartDesign_AdditiveLoft",), "FEATURES_LOFTED_BOSS",
  "Adds material between two or more profiles to create a solid feature.")
c("BossBoundary", "Boundary Boss/Base", ("SWStyle_BoundaryBoss", "PartDesign_AdditiveLoft"), "FEATURES_BOUNDARY_BOSS",
  "Adds material through closed profiles in one direction, steered by guide curves in the other.")
c("BossHelix", "Helix Boss", ("PartDesign_AdditiveHelix",), "FEATURES_SWEPT_BOSS",
  "Sweeps a profile along a helix (FreeCAD Additive Helix).")
c("CutExtrude", "Extruded Cut", ("PartDesign_Pocket",), "FEATURES_EXTRUDE_CUT",
  "Cuts a solid model by extruding a sketched profile in one or two directions.",
  caption="Extruded\nCut")
c("Hole", "Hole Wizard", ("PartDesign_Hole",), "FEATURES_HOLE_WIZARD",
  "Inserts holes with a pre-defined cross section.", caption="Hole\nWizard")
c("CutRevolve", "Revolved Cut", ("PartDesign_Groove",), "FEATURES_REVOLVED_CUT",
  "Cuts a solid model by revolving a sketched profile around an axis.", caption="Revolved\nCut")
c("CutSweep", "Swept Cut", ("PartDesign_SubtractivePipe",), "FEATURES_SWEPT_CUT",
  "Cuts a solid model by sweeping a closed profile along a path.")
c("CutLoft", "Lofted Cut", ("PartDesign_SubtractiveLoft",), "FEATURES_LOFTED_CUT",
  "Cuts a solid model by removing material between two or more profiles.")
c("CutBoundary", "Boundary Cut", ("SWStyle_BoundaryCut", "PartDesign_SubtractiveLoft"), "FEATURES_BOUNDARY_CUT",
  "Removes material through closed profiles in one direction, steered by guide curves in the other.")
c("CutHelix", "Helix Cut", ("PartDesign_SubtractiveHelix",), "FEATURES_SWEPT_CUT",
  "Cuts by sweeping a profile along a helix (FreeCAD Subtractive Helix).")
c("Fillet", "Fillet", ("PartDesign_Fillet",), "FEATURES_FILLET",
  "Creates a rounded internal or external face along one or more edges.")
c("FaceFillet", "Face Fillet", ("SWStyle_FaceFillet", "PartDesign_Fillet"), "FEATURES_FACE_FILLET",
  "Rounds where two sets of faces meet.")
c("FullRoundFillet", "Full Round Fillet", ("SWStyle_FullRoundFillet", "PartDesign_Fillet"), "FEATURES_FULL_ROUND_FILLET",
  "Replaces a face with a half round touching the faces on each side.")
c("VariableFillet", "Variable Size Fillet", ("SWStyle_VariableFillet", "PartDesign_Fillet"), "FEATURES_VARIABLE_FILLET",
  "Rounds edges with a radius that changes along each edge.")
c("AdvancedHole", "Advanced Hole", ("SWStyle_AdvancedHole", "PartDesign_Hole"), "FEATURES_ADVANCED_HOLE",
  "Makes a hole from a stack of near-side and far-side elements.")
c("Chamfer", "Chamfer", ("PartDesign_Chamfer",), "FEATURES_CHAMFER",
  "Creates a bevel feature on selected edges.")
c("LinearPattern", "Linear Pattern", ("SWStyle_LinearPattern", "PartDesign_LinearPattern"), "FEATURES_LINEAR_PATTERN",
  "Patterns features in one or two linear directions.", caption="Linear\nPattern")
c("CircularPattern", "Circular Pattern", ("SWStyle_CircularPattern", "PartDesign_PolarPattern"), "FEATURES_CIRCULAR_PATTERN",
  "Patterns features around an axis.")
c("Mirror", "Mirror", ("SWStyle_Mirror", "PartDesign_Mirrored"), "FEATURES_MIRROR",
  "Mirrors features about a face or plane.")
c("MultiTransform", "Multi-Transform Pattern", ("PartDesign_MultiTransform",), "FEATURES_MIRROR_PATTERN",
  "Combines mirror, linear and circular patterns (FreeCAD MultiTransform).")
c("Scaled", "Scale", ("SWStyle_Scale", "PartDesign_Scaled", "Part_Scale"), "FEATURES_SCALE", "Scales the part about its centroid, origin or a coordinate system.")  # sweep pkg92: our Scale PM first
c("Rib", "Rib", ("SWStyle_Rib",), "FEATURES_RIB", "Adds a thin wall from an open sketch line to the part.")
c("Gusset", "Gusset", ("SWStyle_Gusset",), "WE_GUSSET",
  "A plate that braces the inside corner where two flat faces meet.")
c("GridSystem", "Grid System", ("SWStyle_GridSystem",), None,
  "Lays out a structure's grid lines and floor levels as planes and sketches.")
c("Texture3D", "3D Texture", ("SWStyle_Texture3D",), None,
  "Turns a texture picture into relief on the picked faces, as a mesh body.")
c("Draft", "Draft", ("PartDesign_Draft",), "FEATURES_DRAFT", "Tapers model faces using a specified angle.")
c("Shell", "Shell", ("PartDesign_Thickness",), "FEATURES_SHELL",
  "Removes material from a solid to create a thin-walled feature.")
c("Wrap", "Wrap", ("SWStyle_Wrap", "Part_ProjectionOnSurface"), "FEATURES_WRAP",
  "Wraps a closed sketch onto a cylindrical or flat face: emboss, deboss or scribe.")
c("Intersect", "Intersect", ("SWStyle_Intersect", "PartDesign_Boolean"), "FEATURES_INTERSECT",
  "Combines or intersects bodies (FreeCAD Boolean).")
# Insert > Features and Insert > Curves commands FreeCAD already has (commands/ROUTE-interface.md)
c("SimpleHole", "Simple Hole", ("SWStyle_SimpleHole", "PartDesign_Hole"), None,
  "A plain hole on a planar face (FreeCAD Hole with no thread or counterbore).")
c("Combine", "Combine", ("SWStyle_CombineBodies", "PartDesign_Boolean"), "FEATURES_COMBINE",
  "Adds, subtracts or keeps the common volume of solid bodies.")
c("SplitBody", "Split", ("SWStyle_Split", "Part_SliceApart", "Part_Slice"), "FEATURES_SPLIT",
  "Splits a body into separate bodies with planes, surfaces or sketches.")
c("MoveCopyBodies", "Move/Copy Bodies", ("SWStyle_MoveCopyBody", "Std_TransformManip", "Std_Placement"), "SKETCH_MOVE_ENTITIES",
  "Moves, rotates or copies solid bodies.")
c("DeleteKeepBody", "Delete/Keep Body", ("SWStyle_DeleteKeepBody",), None, "Deletes or keeps solid bodies.")
c("MirrorBody", "Mirror Body", ("SWStyle_MirrorBody",), "FEATURES_MIRROR", "Mirrors solid bodies about a face or plane.")
c("InsertPart", "Insert Part", ("SWStyle_InsertPart", "Part_Import"), None, "Brings the bodies of another part file in.")
c("DeleteFace", "Delete Face", ("SWStyle_DeleteFace", "Part_Defeaturing"), "FEATURES_DELETE_FACE",
  "Deletes faces of the part: leave it open, patch the gap, or fill it.")
c("ReplaceFace", "Replace Face", ("SWStyle_ReplaceFace", "Part_Offset"), "FEATURES_REPLACE_FACE",
  "Replaces faces of the part with a surface, the part growing or shrinking to meet it.")
c("Defeature", "Defeature", ("SWStyle_Defeature", "Part_Defeaturing"), None, "Removes details such as fillets and holes from a body.")
c("HealEdges", "Heal Edges", ("SWStyle_HealEdges", "Part_Defeaturing"), "FEATURES_HEAL_EDGES",
  "Merges short edges on faces of an imported body into longer edges.")
c("LiveSection", "Live Section Plane", ("SWStyle_LiveSectionPlane", "SWStyle_SectionView", "Part_SectionCut"), "I3DVIEW_SECT_VIEW", "A section plane you can move: drag its arrow or ring, the cut follows live.")
c("ConvertToMesh", "Convert to Mesh Body", ("SWStyle_ConvertToMesh", "Mesh_FromPartShape", "MeshPart_Mesher"), None,
  "Makes a mesh body from a solid.")
c("SegmentMesh", "Segment Mesh", ("SWStyle_SegmentMesh", "Mesh_Segmentation"), "FEATURES_SEGMENT_MESH", "Splits a mesh into regions.")
c("ProjectedCurve", "Projected Curve", ("SWStyle_ProjectedCurve", "Part_ProjectionOnSurface"), None,
  "Projects a sketch onto faces, or two sketches into one 3D curve.")
c("HelixSpiral", "Helix and Spiral", ("SWStyle_HelixSpiral", "PartDesign_AdditiveHelix"), None,
  "Makes a helix or spiral on a sketch circle.", caption="Helix and\nSpiral")
c("SplitLine", "Split Line", ("SWStyle_SplitLine", "Part_ProjectionOnSurface"), "FEATURES_SPLIT_LINE", "Projects a sketch onto faces to split them.")

# ---- Surfaces tab: FreeCAD's Part and Surface commands
c("ExtrudedSurface", "Extruded Surface", ("SWStyle_SurfaceExtrude", "Part_Extrude"), None, "A surface from an extruded sketch or edge.",
  caption="Extruded\nSurface")
c("RevolvedSurface", "Revolved Surface", ("SWStyle_SurfaceRevolve", "Part_Revolve"), None, "A surface from a revolved sketch or edge.",
  caption="Revolved\nSurface")
c("SweptSurface", "Swept Surface", ("SWStyle_SurfaceSweep", "Part_Sweep"), None, "A surface swept along a path.")
c("LoftedSurface", "Lofted Surface", ("SWStyle_SurfaceLoft", "Part_Loft"), None, "A surface lofted through profiles.")
c("BoundarySurface", "Boundary Surface", ("SWStyle_BoundarySurface", "Surface_GeomFillSurface"),
  "FEATURES_BOUNDARY_SURFACE", "A surface through curves in one or two directions.", caption="Boundary\nSurface")
c("FilledSurface", "Filled Surface", ("SWStyle_FilledSurface", "Surface_Filling"), None, "A patch bounded by edges.",
  caption="Filled\nSurface")
c("PlanarSurface", "Planar Surface", ("SWStyle_PlanarSurface", "Part_MakeFace"), None, "A flat face from a closed sketch.")
c("OffsetSurface", "Offset Surface", ("SWStyle_SurfaceOffset", "Part_Offset"), None, "Offsets faces by a distance.")
c("MidSurface", "Mid-Surface", ("SWStyle_MidSurface", "Part_Offset"), "FEATURES_MID_SURFACE",
  "The surface halfway between facing faces of a thin solid.")
c("RuledSurface", "Ruled Surface", ("SWStyle_SurfaceRuled", "Part_RuledSurface"), None,
  "A strip of surface out from model edges: tangent or normal to the faces, or set by a vector.")
c("KnitSurface", "Knit Surface", ("SWStyle_SurfaceKnit", "Part_Builder", "Part_MakeSolid"), None,
  "Knits surfaces together, into a solid when they close.")
c("ExtendSurface", "Extend Surface", ("SWStyle_ExtendSurface", "Surface_ExtendFace"), None, "Extends a face past its edges.")
c("SurfaceChamfer", "Chamfer", ("SWStyle_SurfaceChamfer",), None, "Bevels edges where surfaces meet.")
c("SurfaceFlatten", "Flatten", ("SWStyle_Flatten",), None, "Lays a curved face or surface out flat.")
c("SurfaceFromMesh", "Surface From Mesh", ("SWStyle_SurfaceFromMesh",), "SURFACES_FROM_MESH",
  "Makes surfaces (or a solid) from a mesh.")
c("TrimSurface", "Trim Surface", ("SWStyle_TrimSurface", "Part_BooleanFragments"), "FEATURES_TRIM_SURFACE",
  "Trims surfaces with a surface, plane or sketch, or with each other, keeping or removing the pieces you click.")
c("UntrimSurface", "Untrim Surface", ("SWStyle_UntrimSurface", "Surface_ExtendFace"), "FEATURES_UNTRIM_SURFACE",
  "Grows a trimmed surface back to its natural edges, filling its holes, its outline or both.")
c("SurfaceFillet", "Fillet", ("SWStyle_SurfaceFillet", "Part_Fillet"), "FEATURES_FILLET",
  "Rounds edges of a surface body, or between two surfaces (Face Fillet).")
c("ThickenedCut", "Thickened Cut", ("SWStyle_ThickenedCut", "Part_Thickness"), "FEATURES_THICKENED_CUT",
  "Cuts the part with a thickened surface.")
c("CutWithSurface", "Cut With Surface", ("SWStyle_CutWithSurface", "Part_Slice"), "FEATURES_CUT_WITH_SURFACE",
  "Cuts the part with a surface or plane, keeping one side.")
c("Scale", "Scale", ("SWStyle_Scale", "Part_Scale"), "FEATURES_SCALE", "Scales the part about its centroid, origin or a coordinate system.")
c("Dome", "Dome", ("SWStyle_Dome", "Part_Sphere"), "FEATURES_DOME", "Adds a dome to a face.")
c("Freeform", "Freeform", ("SWStyle_Freeform",), "FEATURES_FREEFORM",
  "Pushes and pulls a face by control points on control curves, keeping its edges.")
c("Deform", "Deform", ("SWStyle_Deform",), "FEATURES_DEFORM",
  "Bends the part smoothly: round a point, from curves to curves, or pushed by a tool body.")
c("Flex", "Flex", ("SWStyle_Flex", "Part_Shapebuilder"), "FEATURES_FLEX",
  "Bends, twists, tapers or stretches the part between two trim planes.")
c("Indent", "Indent", ("SWStyle_Indent", "Part_Cut"), "FEATURES_INDENT",
  "Presses the shape of a tool body into a target body, with a clearance.")
c("MountingBoss", "Mounting Boss", ("SWStyle_MountingBoss",), "FEATURES_MOUNTING_BOSS",
  "A boss for a screw or a pin, with fins, on a flat face.")
c("SnapHook", "Snap Hook", ("SWStyle_SnapHook",), "FEATURES_SNAP_HOOK", "A flexible hook with a catch lip, on a flat face.")
c("SnapHookGroove", "Snap Hook Groove", ("SWStyle_SnapHookGroove",), "FEATURES_SNAP_HOOK_GROOVE",
  "Cuts the groove a snap hook catches in, with a gap.")
c("LipGroove", "Lip/Groove", ("SWStyle_LipGroove",), "FEATURES_LIP_GROOVE",
  "A lip or a matching groove along the top of a wall, for parts that close together.")
c("StudWizard", "Stud Wizard", ("SWStyle_StudWizard",), "FEATURES_STUD_WIZARD", "A threaded stud standing on a flat face.")
c("Cavity", "Cavity", ("SWStyle_Cavity",), "FEATURES_CAVITY",
  "Cuts the shape of another body out of the part, scaled for shrinkage.")
c("MoldFolders", "Insert Mold Folders", ("SWStyle_MoldFolders",), "MOLD_FOLDERS",
  "Adds the Surface Bodies, Cavity, Core and Parting Surface Bodies folders a mould design keeps.")
c("PartingLine", "Parting Line", ("SWStyle_PartingLine",), "MOLD_PARTING_LINE",
  "Finds the edges where a mould opens, from the draft against the direction of pull.")
c("ShutOffSurfaces", "Shut-Off Surfaces", ("SWStyle_ShutOffSurfaces",), "MOLD_SHUT_OFF_SURFACES",
  "Patches the holes through the part so the core and cavity meet there.")
c("PartingSurface", "Parting Surface", ("SWStyle_PartingSurface",), "MOLD_PARTING_SURFACE",
  "A flange of surface out from the parting line, where the core and cavity meet.")
c("ToolingSplit", "Tooling Split", ("SWStyle_ToolingSplit",), "MOLD_TOOLING_SPLIT",
  "A block round the part, cut into the core and the cavity.")
c("MoldCore", "Core", ("SWStyle_Core",), "MOLD_CORE", "Pulls a side core out of the core or cavity block along a sketch.")
c("JoinParts", "Join", ("SWStyle_Join",), "FEATURES_JOIN", "Joins other bodies or parts into this part.")
c("CurveDrivenPattern", "Curve Driven Pattern", ("SWStyle_CurveDrivenPattern", "PartDesign_LinearPattern"),
  "FEATURES_CURVE_DRIVEN_PATTERN", "Repeats features along a curve.")
c("SketchDrivenPattern", "Sketch Driven Pattern", ("SWStyle_SketchDrivenPattern", "PartDesign_LinearPattern"),
  "FEATURES_SKETCH_DRIVEN_PATTERN", "Repeats features at the points of a sketch.")
c("TableDrivenPattern", "Table Driven Pattern", ("SWStyle_TableDrivenPattern", "PartDesign_LinearPattern"),
  "FEATURES_TABLE_DRIVEN_PATTERN", "Repeats features at X-Y positions from a table.")
c("FillPattern", "Fill Pattern", ("SWStyle_FillPattern", "PartDesign_LinearPattern"), "FEATURES_FILL_PATTERN",
  "Fills a face with copies of a feature.")
c("VariablePattern", "Variable Pattern", ("SWStyle_VariablePattern", "PartDesign_LinearPattern"),
  "FEATURES_VARIABLE_PATTERN", "Patterns features with instances that differ in their dimensions, from a table.")
c("SilhouetteEntities", "Silhouette Entities", ("SWStyle_SilhouetteEntities",), None,
  "Sketches the outline of a body as seen square to the sketch.")
c("Thicken", "Thicken", ("SWStyle_Thicken", "Part_Thickness"), "FEATURES_THICKEN", "Turns a surface into a solid by thickening it.")
c("BlendCurve", "Blend Curve", ("SWStyle_BlendCurve", "Surface_BlendCurve"), None, "A smooth curve joining two edges.")

# ---- Sketch, view and file commands FreeCAD already has (found by Search Commands)
# ---- Drawings: View Layout (drawings-land01, drawings.py)
c("DrawStandard3View", "Standard 3 View", ("FreeWorks_DrawStandard3View",), None,
  "Adds a part's or assembly's Front, Top and Right views to the sheet.", caption='Standard 3\nView')
c("DrawModelView", "Model View", ("FreeWorks_DrawModelView",), None,
  "Adds one view of a part or assembly in the orientation you pick, then views projected from it.", caption='Model\nView')
c("DrawProjectedView", "Projected View", ("FreeWorks_DrawProjectedView",), None,
  "Adds a view projected from the picked view: click to its right, left, above or below.", caption='Projected\nView')
c("DrawAuxiliaryView", "Auxiliary View", ("FreeWorks_DrawAuxiliaryView",), None,
  "Adds a view square to the picked straight edge of a view.", caption='Auxiliary\nView')
c("DrawSectionView", "Section View", ("FreeWorks_DrawSectionView",), None,
  "Cuts a view along a line you sketch and adds the section as a new view.", caption='Section\nView')
c("DrawDetailView", "Detail View", ("FreeWorks_DrawDetailView",), None,
  "Circles part of a view and adds it enlarged as a new view.", caption='Detail\nView')
c("DrawBreak", "Break View", ("FreeWorks_DrawBreak",), None, "Breaks a long view in two with a gap, keeping its scale.", caption='Break\nView')
c("DrawCrop", "Crop View", ("FreeWorks_DrawCrop",), None, "Keeps only the part of a view inside a closed sketch.", caption='Crop\nView')
c("DrawRemoveCrop", "Remove Crop", ("FreeWorks_DrawRemoveCrop",), None, "Shows the whole view again.")
c("DrawRelativeView", "Relative View", ("FreeWorks_DrawRelativeView",), None,
  "A view oriented by two faces of the model you pick.", caption='Relative\nView')
c("DrawEmptyView", "Empty View", ("FreeWorks_DrawEmptyView",), None, "An empty view to sketch in.", caption='Empty\nView')
c("DrawPredefinedView", "Predefined View", ("FreeWorks_DrawPredefinedView",), None,
  "A view placed now and filled with a model later.", caption='Predefined\nView')
c("DrawRemovedSection", "Removed Section", ("FreeWorks_DrawRemovedSection",), None,
  "A section through a view at a line, shown as a slice between two picked edges.", caption='Removed\nSection')
c("DrawBrokenOut", "Broken-out Section", ("FreeWorks_DrawBrokenOut",), None,
  "Cuts away part of a view inside a closed profile to show what is behind it.", caption='Broken-out\nSection')
# ---- Drawings: Annotation (drawings-land07, drawannot.py)
c("DrawModelItems", "Model Items", ("FreeWorks_DrawModelItems",), None,
  "Brings the model's sketch dimensions into the drawing views.", caption='Model\nItems')
c("DrawHoleCallout", "Hole Callout", ("FreeWorks_DrawHoleCallout",), None,
  "A callout with a hole's diameter and depth: click the hole's edge, then where the note goes.")
c("DrawCenterMark", "Center Mark", ("FreeWorks_DrawCenterMark",), None, "Marks the centre of circles and arcs.")
c("DrawCenterline", "Centerline", ("FreeWorks_DrawCenterline",), None, "A centerline between two parallel edges.")
c("DrawNote", "Note", ("FreeWorks_DrawNote",), None, "A text note on the sheet, with or without a leader.")
c("DrawBalloon", "Balloon", ("FreeWorks_DrawBalloon",), None, "An item-number balloon on a component in a view.")
c("DrawAutoBalloon", "Auto Balloon", ("FreeWorks_DrawAutoBalloon",), None, "Balloons for every component in the view at once.")
c("DrawSurfaceFinish", "Surface Finish", ("FreeWorks_DrawSurfaceFinish",), None, "A surface finish symbol on an edge or face.")
c("DrawGeometricTolerance", "Geometric Tolerance", ("FreeWorks_DrawGeometricTolerance",), None,
  "A feature control frame: tolerance symbol, value and datums.")
c("DrawDatumFeature", "Datum Feature", ("FreeWorks_DrawDatumFeature",), None, "A datum feature symbol on an edge.")
c("DrawRevisionSymbol", "Revision Symbol", ("FreeWorks_DrawRevisionSymbol",), None, "A revision symbol tied to the revision table.")
c("DrawGeneralTable", "General Table", ("FreeWorks_DrawGeneralTable",), None, "A table of rows and columns you fill in.", caption='Tables')
c("DrawTitleBlockTable", "Title Block Table", ("FreeWorks_DrawTitleBlockTable",), None, "A table of the title block's fields.")
c("DrawHoleTable", "Hole Table", ("FreeWorks_DrawHoleTable",), None, "A table of the holes in a view: tag, X, Y, size.")
c("DrawBOM", "Bill of Materials", ("FreeWorks_DrawBOM",), None, "A bill of materials of the assembly in a view.")
c("DrawRevisionTable", "Revision Table", ("FreeWorks_DrawRevisionTable",), None, "A revision table on the sheet.")
c("DrawWeldTable", "Weld Table", ("FreeWorks_DrawWeldTable",), None, "A table of the weld symbols on the sheet. Greyed until the sheet has a weld symbol.")
c("DrawBendTable", "Bend Table", ("FreeWorks_DrawBendTable",), None, "A table of the bends in a flat pattern view.")
c("DrawPunchTable", "Punch Table", ("FreeWorks_DrawPunchTable",), None, "A table of the forming tool punches in a flat pattern view.")
c("DrawAddRevision", "Add Revision", ("FreeWorks_DrawAddRevision",), None, "Adds a row to the revision table.")
c("DrawUpdateTable", "Update Table", ("FreeWorks_DrawUpdateTable",), None, "Refreshes a bill of materials or hole table from the model.")
c("DrawStackedBalloon", "Stacked Balloon", ("FreeWorks_DrawStackedBalloon",), None, "Balloons stacked on one leader.")
c("DrawWeldSymbol", "Weld Symbol", ("FreeWorks_DrawWeldSymbol",), None, "A weld symbol on an edge.")
c("DrawDatumTarget", "Datum Target", ("FreeWorks_DrawDatumTarget",), None, "A datum target point or area.")
c("DrawRevisionCloud", "Revision Cloud", ("FreeWorks_DrawRevisionCloud",), None, "A cloud drawn round a changed area.")
c("DrawMultiJogLeader", "Multi-jog Leader", ("FreeWorks_DrawMultiJogLeader",), None, "A leader with bends, for a note or symbol.")
c("DrawAreaHatch", "Area Hatch/Fill", ("FreeWorks_DrawAreaHatch",), None, "Hatches or fills a closed area of a view or sketch.")
c("DrawLinearNotePattern", "Linear Note Pattern", ("FreeWorks_DrawLinearNotePattern",), None, "Copies a note in rows and columns.", caption='Linear Note\nPattern')
c("DrawCircularNotePattern", "Circular Note Pattern", ("FreeWorks_DrawCircularNotePattern",), None, "Copies a note round a centre.")
c("DrawMagneticLine", "Magnetic Line", ("FreeWorks_DrawMagneticLine",), None, "A line that balloons snap to and line up on.")
c("DrawCaterpillar", "Caterpillar", ("FreeWorks_DrawCaterpillar",), None, "A caterpillar weld along an edge.")
c("DrawEndTreatment", "End Treatment", ("FreeWorks_DrawEndTreatment",), None, "A weld end treatment on a structural member's end.")
c("DrawDowelPin", "Dowel Pin Symbol", ("FreeWorks_DrawDowelPin",), None, "The dowel pin symbol on a hole.")
c("DrawLocationLabel", "Location Label", ("FreeWorks_DrawLocationLabel",), None, "A label saying which sheet a section or detail view is on.")
c("DrawAlternatePosition", "Alternate Position View", ("FreeWorks_DrawAlternatePosition",), None,
  "Shows the assembly in a second position over the view, in phantom lines.", caption='Alternate\nPosition View')
c("DrawViewPalette", "View Palette", ("FreeWorks_DrawViewPalette",), None,
  "The Task Pane's View Palette: drag a part's standard views onto the sheet.")
# ---- Drawings: view right-click (drawings-land13, right-click thread's menu)
c("DrawLockViewPosition", "Lock View Position", ("FreeWorks_DrawLockViewPosition",), None, "Keeps the view where it is on the sheet.")
c("DrawBreakAlignment", "Break Alignment", ("FreeWorks_DrawBreakAlignment",), None, "Frees the view from its parent's alignment.")
c("DrawDefaultAlignment", "Default Alignment", ("FreeWorks_DrawDefaultAlignment",), None, "Lines the view up with its parent again.")
c("DrawAlignHorizontalOrigin", "Align Horizontal by Origin", ("FreeWorks_DrawAlignHorizontalOrigin",), None, "Lines the view up horizontally with the view you click, by origin.")
c("DrawAlignVerticalOrigin", "Align Vertical by Origin", ("FreeWorks_DrawAlignVerticalOrigin",), None, "Lines the view up vertically with the view you click, by origin.")
c("DrawAlignHorizontalCenter", "Align Horizontal by Center", ("FreeWorks_DrawAlignHorizontalCenter",), None, "Lines the view up horizontally with the view you click, by centre.")
c("DrawAlignVerticalCenter", "Align Vertical by Center", ("FreeWorks_DrawAlignVerticalCenter",), None, "Lines the view up vertically with the view you click, by centre.")
# drawings-land45 (drawdimtools.py): drawing dimension tools (the sketch ones above work in sketches only)
c("DrawAutodimension", "Autodimension", ("FreeWorks_DrawAutodimension",), None, "Dimensions a view's entities at once, baseline, chain or ordinate.")
c("DrawOrdinateDimension", "Ordinate Dimension", ("FreeWorks_DrawOrdinateDimension",), None, "Ordinate dimensions from a zero point on the view.")
c("DrawHorizontalOrdinate", "Horizontal Ordinate Dimension", ("FreeWorks_DrawHorizontalOrdinate",), None, "Horizontal ordinate dimensions from a zero point.")
c("DrawVerticalOrdinate", "Vertical Ordinate Dimension", ("FreeWorks_DrawVerticalOrdinate",), None, "Vertical ordinate dimensions from a zero point.")
c("DrawBaselineDimension", "Baseline Dimension", ("FreeWorks_DrawBaselineDimension",), None, "Dimensions measured from one baseline.")
c("DrawChamferDimension", "Chamfer Dimension", ("FreeWorks_DrawChamferDimension",), None, "Dimensions a chamfer's distance and angle.")
c("DrawDimAutoArrange", "Auto Arrange Dimensions", ("FreeWorks_DrawDimAutoArrange",), None, "Arranges the selected dimensions around the view.")
c("DrawDimAlignCollinear", "Align Collinear/Radial", ("FreeWorks_DrawDimAlignCollinear",), None, "Lines the selected dimensions up collinear or radial.")
c("DrawDimAlignParallel", "Align Parallel/Concentric", ("FreeWorks_DrawDimAlignParallel",), None, "Lines the selected dimensions up parallel or concentric.")
c("DrawDimSpaceEvenly", "Space Evenly Linear/Diametric", ("FreeWorks_DrawDimSpaceEvenly",), None, "Spaces the selected dimensions evenly.")
c("DrawDimBreakAlignment", "Break Dimension Alignment", ("FreeWorks_DrawDimBreakAlignment",), None, "Frees the selected dimensions from their alignment group.")
c("DrawTangentVisible", "Tangent Edges Visible", ("FreeWorks_DrawTangentVisible",), None, "Draws tangent edges as solid lines.")
c("DrawTangentWithFont", "Tangent Edges With Font", ("FreeWorks_DrawTangentWithFont",), None, "Draws tangent edges as phantom lines.")
c("DrawTangentRemoved", "Tangent Edges Removed", ("FreeWorks_DrawTangentRemoved",), None, "Leaves tangent edges out.")
c("DrawTangentWithHiddenEnds", "Tangent Edges With Hidden Ends", ("FreeWorks_DrawTangentWithHiddenEnds",), None,
  "Shows tangent edges with their ends left out.")
c("DrawHideView", "Hide View", ("FreeWorks_DrawHideView",), None, "Hides the view on the sheet.")
c("DrawShowHiddenViews", "Show Hidden Views", ("FreeWorks_DrawShowHiddenViews",), None, "Shows the sheet's hidden views again.")
c("DrawOpenModel", "Open Part", ("FreeWorks_DrawOpenModel",), None, "Opens the part or assembly the view shows.")
c("DrawViewProperties", "View Properties", ("FreeWorks_DrawViewProperties",), None, "The view's name, scale, display style and configuration.")
c("DrawAddSheet", "Sheet...", ("FreeWorks_DrawAddSheet",), None, "Adds a sheet to the drawing.")
c("DrawMakeSectionLine", "Make Section Line", ("FreeWorks_DrawMakeSectionLine",), None,
  "Makes a section line from a sketched line on a view. Greyed until a view has a sketched line.")
# Drawing sketch tools (drawings-land16): sketched on the sheet, not in a part sketch
c("DrawSketchLine", "Line", ("FreeWorks_DrawSketchLine",), "SKETCH_LINE", "Sketches a line on the drawing sheet.")
c("DrawSketchCenterline", "Centerline", ("FreeWorks_DrawSketchCenterline",), "SKETCH_CENTERLINE", "Sketches a centerline on the drawing sheet.")
c("DrawSketchRectangle", "Corner Rectangle", ("FreeWorks_DrawSketchRectangle",), "SKETCH_CORNER_RECT", "Sketches a rectangle on the drawing sheet.")
c("DrawSketchCircle", "Circle", ("FreeWorks_DrawSketchCircle",), "SKETCH_CIRCLE", "Sketches a circle on the drawing sheet.")
c("DrawSketchArc", "Centerpoint Arc", ("FreeWorks_DrawSketchArc",), "SKETCH_CPRPT_ARC", "Sketches an arc from its center on the drawing sheet.")
c("DrawSketchPoint", "Point", ("FreeWorks_DrawSketchPoint",), "SKETCH_POINT", "Sketches a point on the drawing sheet.")
c("DrawSketchSpline", "Spline", ("FreeWorks_DrawSketchSpline",), "SKETCH_SPLINE", "Sketches a spline on the drawing sheet.")
c("DrawSketchCenterRectangle", "Center Rectangle", ("FreeWorks_DrawSketchCenterRectangle",), "SKETCH_CTR_RECT", "Sketches a rectangle from its center on the drawing sheet.")
c("DrawSketchSlot", "Straight Slot", ("FreeWorks_DrawSketchSlot",), "SKETCH_STRAIGHT_SLOT", "Sketches a straight slot on the drawing sheet.")
c("DrawSketchPerimeterCircle", "Perimeter Circle", ("FreeWorks_DrawSketchPerimeterCircle",), "SKETCH_CTRPT_CIRCLE", "Sketches a circle through three points on the drawing sheet.")
c("DrawSketchThreePointArc", "3 Point Arc", ("FreeWorks_DrawSketchThreePointArc",), "SKETCH_3PT_ARC", "Sketches an arc through three points on the drawing sheet.")
c("DrawSketchPolygon", "Polygon", ("FreeWorks_DrawSketchPolygon",), "SKETCH_POLYGON", "Sketches a polygon on the drawing sheet.")
c("DrawSketchEllipse", "Ellipse", ("FreeWorks_DrawSketchEllipse",), "SKETCH_ELLIPSE", "Sketches an ellipse on the drawing sheet.")
c("DrawSketchText", "Text", ("FreeWorks_DrawSketchText",), "SKETCH_TEXT", "Sketches text on the drawing sheet.")

c("DrawSketchMidpointLine", "Midpoint Line", ("FreeWorks_DrawSketchMidpointLine",), "SKETCH_LINE", "Sketches a line from its midpoint on the drawing sheet.")
c("DrawSketchFillet", "Sketch Fillet", ("FreeWorks_DrawSketchFillet",), "SKETCH_FILLET", "Rounds the corner between two sketch entities on the sheet.")
c("DrawSketchChamfer", "Sketch Chamfer", ("FreeWorks_DrawSketchChamfer",), "SKETCH_CHAMFER", "Bevels the corner between two sketch entities on the sheet.")
c("DrawTrimEntities", "Trim Entities", ("FreeWorks_DrawTrimEntities",), "SKETCH_TRIM", "Trims or extends sketch entities on the sheet.")
c("DrawConvertEntities", "Convert Entities", ("FreeWorks_DrawConvertEntities",), "SKETCH_CONVERT_ENTITIES", "Converts model edges of a view to sketch entities.")
c("DrawOffsetEntities", "Offset Entities", ("FreeWorks_DrawOffsetEntities",), "SKETCH_OFFSET_ENTITIES", "Offsets sketch entities on the sheet.")
c("DrawMirrorEntities", "Mirror Entities", ("FreeWorks_DrawMirrorEntities",), "SKETCH_MIRROR_ENTITIES", "Mirrors sketch entities about a line.")
c("DrawLinearSketchPattern", "Linear Sketch Pattern", ("FreeWorks_DrawLinearSketchPattern",), "SKETCH_LINEAR_PATTERN", "Repeats sketch entities in a row.")
c("DrawCircularSketchPattern", "Circular Sketch Pattern", ("FreeWorks_DrawCircularSketchPattern",), "SKETCH_CIR_PATTERN", "Repeats sketch entities about a point.")
c("DrawMoveEntities", "Move Entities", ("FreeWorks_DrawMoveEntities",), "SKETCH_MOVE_ENTITIES", "Moves selected sketch entities.")
c("DrawCopyEntities", "Copy Entities", ("FreeWorks_DrawCopyEntities",), "SKETCH_COPY_ENTITIES", "Copies selected sketch entities.")
c("DrawRotateEntities", "Rotate Entities", ("FreeWorks_DrawRotateEntities",), "SKETCH_ROTATE_ENTITIES", "Rotates selected sketch entities.")
c("DrawScaleEntities", "Scale Entities", ("FreeWorks_DrawScaleEntities",), "SKETCH_SCALE_ENTITIES", "Scales selected sketch entities.")
c("DrawDisplayDeleteRelations", "Display/Delete Relations", ("FreeWorks_DrawDisplayDeleteRelations",), "LAYOUT_DISPLAY_DEL_RELATION", "Lists the relations of the picked sketch entities, to delete them.")
c("DrawAddRelation", "Add Relation", ("FreeWorks_DrawAddRelation",), "LAYOUT_ADD_RELATION", "Adds a relation between picked sketch entities.")
c("DrawQuickSnaps", "Quick Snaps", ("FreeWorks_DrawQuickSnaps",), "FLYOUT_QUICK_SNAPS", "Sketch snap options on the sheet.", caption="Quick\nSnaps")
c("DrawLayerProperties", "Layer Properties", ("FreeWorks_DrawLayerProperties",), "FONTTOOLBAR_LAYER_PROP",
  "Layers box: each layer's colour, line style, thickness and on/off.")
c("DrawSheetProperties", "Sheet Properties", ("FreeWorks_DrawSheetProperties",), None,
  "The sheet's name, scale, projection type and sheet format.")
c("DrawEditSheetFormat", "Edit Sheet Format", ("FreeWorks_DrawEditSheetFormat",), None,
  "Edits the sheet format (the border and title block) instead of the sheet.", caption='Edit Sheet\nFormat')
c("DrawEditSheet", "Edit Sheet", ("FreeWorks_DrawEditSheet",), None, "Back to the sheet from editing its format.")
c("DrawTitleBlockFields", "Title Block Fields", ("FreeWorks_DrawTitleBlockFields",), None,
  "Marks the title block's fields while the sheet format is being edited.", caption='Title Block\nFields')
c("DrawUpdateView", "Update View", ("FreeWorks_DrawUpdateView",), None, "Redraws the picked views from their models.", caption='Update\nView')
c("DrawReplaceModel", "Replace Model", ("FreeWorks_DrawReplaceModel",), None, "Swaps the model behind the picked views.", caption='Replace\nModel')
c("DrawFormatPainter", "Format Painter", ("FreeWorks_DrawFormatPainter",), None,
  "Copies one annotation's format onto others.", caption='Format\nPainter')
c("DrawSpellChecker", "Spell Checker", ("FreeWorks_DrawSpellChecker",), None, "Checks the spelling of the sheet's notes (F7).", caption='Spell\nChecker')
c("DrawMakeBlock", "Make Block", ("FreeWorks_DrawMakeBlock",), "BLOCK_MAKE", "Makes a block from the picked sheet entities.",
  caption="Blocks")    # annotab-1121: the Annotation tab's Blocks flyout is captioned Blocks (Tables likewise)
c("DrawEditBlock", "Edit Block", ("FreeWorks_DrawEditBlock",), "BLOCK_EDIT", "Edits the picked block's entities.")
c("DrawInsertBlock", "Insert Block", ("FreeWorks_DrawInsertBlock",), "BLOCK_INSERT", "Places a saved block on the sheet.")
c("DrawSaveBlock", "Save Block", ("FreeWorks_DrawSaveBlock",), "BLOCK_SAVE", "Saves the picked block to a file.")
c("DrawExplodeBlock", "Explode Block", ("FreeWorks_DrawExplodeBlock",), "BLOCK_EXPLODE", "Breaks the picked block into its entities.")
c("DrawAutomaticBorder", "Automatic Border", ("FreeWorks_DrawAutomaticBorder",), None,
  "The sheet format's border and zone marks, kept to the sheet size (while editing the format).", caption='Automatic\nBorder')
c("DrawMarkupToggle", "Markup", ("FreeWorks_DrawMarkupToggle",), None, "Turns markup mode on or off.")
c("DrawMarkupTouch", "Touch", ("FreeWorks_DrawMarkupTouch",), None, "Draws markup by touch or pen.")
c("DrawMarkupDraw", "Draw", ("FreeWorks_DrawMarkupDraw",), None, "Draws an ink markup on the sheet.")
c("DrawMarkupNote", "Note", ("FreeWorks_DrawMarkupNote",), None, "Writes a markup note on the sheet.")
c("DrawMarkupEraser", "Eraser", ("FreeWorks_DrawMarkupEraser",), None, "Rubs out ink markup.")
c("DrawZoomToMarkup", "Zoom to Markup View", ("FreeWorks_DrawZoomToMarkup",), None, "Zooms to the markup's view.")
c("DrawMarkupOptions", "Markup Options", ("FreeWorks_DrawMarkupOptions",), None, "The markup pen's colour and width.")
c("DrawMarkupColor", "Color", ("FreeWorks_DrawMarkupColor",), None, "The markup pen's colour.")
c("DrawMarkupSelect", "Select", ("FreeWorks_DrawMarkupSelect",), None, "Selects ink markup to move or delete it.")
c("DrawSaveSheetFormat", "Save Sheet Format...", ("FreeWorks_DrawSaveSheetFormat",), None,
  "Saves the sheet's format as a file to use on other drawings.")
c("SketchPicture", "Sketch Picture", ("SWStyle_SketchPicture", "Std_ViewLoadImage"), None,
  "Places a picture on the sketch plane to trace.")
c("AlignSketch", "Align Sketch", ("Sketcher_ReorientSketch",), None, "Turns the sketch's axes to line up with an edge or the grid.")
c("AlignGridOrigin", "Align Grid/Origin", ("SWStyle_AlignGridOrigin",), "SKETCH_ALIGN_GRID",
  "Moves the sketch's origin to a point and turns its grid along a line; the sketch stays where it is.")
c("AddTangencyControl", "Add Tangency Control", ("FreeWorks_Sketch3DAddTangencyControl", "Sketcher_BSplineInsertKnot"), None,
  "Adds a tangent handle where you click on the spline.")
c("AddCurvatureControl", "Add Curvature Control", ("FreeWorks_Sketch3DAddCurvatureControl", "Sketcher_BSplineInsertKnot"), None,
  "Adds a curvature handle where you click on the spline.")
c("ConvertToStyleSpline", "Convert to Style Spline", ("FreeWorks_Sketch3DConvertStyleSpline", "Sketcher_BSplineConvertToNURBS"), None,
  "Changes the picked spline into a Style Spline (its control vertices).")
c("ConvertToSpline", "Convert to Spline", ("FreeWorks_Sketch3DConvertSpline", "Sketcher_BSplineConvertToNURBS"), None,
  "Changes the picked Style Spline into a spline through points.")
c("ConvertToGenericSpline", "Convert to Generic Spline", ("FreeWorks_Sketch3DConvertGenericSpline", "Sketcher_BSplineConvertToNURBS"), None,
  "Changes the picked spline into a generic spline: its shape kept, no handles.")
c("ShowSplineControlPolygon", "Show Spline Control Polygon", ("FreeWorks_Sketch3DShowControlPolygon", "Sketcher_BSplinePolygon"), None,
  "Shows the picked spline's control polygon.")
c("RouteLine", "Route Line", ("FreeWorks_Sketch3DRouteLine",), None,
  "Sketches a route of lines along X, Y and Z between two picked points.")
# ---- 2D to 3D and Pen Tools (sketch3d-land29/30: twodto3d.py, pentools.py)
c("2Dto3DFront", "Front", ("FreeWorks_2Dto3DFront",), "D2TO3D_FRONT", "Makes the picked entities the front view: back into the first sketch.")
c("2Dto3DTop", "Top", ("FreeWorks_2Dto3DTop",), "D2TO3D_TOP", "Turns the picked entities into the top view, above the front view.")
c("2Dto3DRight", "Right", ("FreeWorks_2Dto3DRight",), "D2TO3D_RIGHT", "Turns the picked entities into the right view.")
c("2Dto3DBottom", "Bottom", ("FreeWorks_2Dto3DBottom",), "D2TO3D_BOTTOM", "Turns the picked entities into the bottom view.")
c("2Dto3DLeft", "Left", ("FreeWorks_2Dto3DLeft",), "D2TO3D_LEFT", "Turns the picked entities into the left view.")
c("2Dto3DBack", "Back", ("FreeWorks_2Dto3DBack",), "D2TO3D_BACK", "Turns the picked entities into the back view.")
c("2Dto3DAuxiliary", "Auxiliary", ("FreeWorks_2Dto3DAuxiliary",), "D2TO3D_AUXILIARY",
  "Turns the picked entities into an auxiliary view, folded about the line picked last.")
c("2Dto3DExtrude", "Extrude...", ("FreeWorks_2Dto3DExtrude",), "D2TO3D_EXTRUDE", "Extrudes the picked closed entities as their own feature.")
c("2Dto3DCut", "Cut...", ("FreeWorks_2Dto3DCut",), "D2TO3D_CUT", "Cuts with the picked closed entities as their own feature.")
c("PenSketch", "Pen Sketch", ("FreeWorks_PenSketch",), "PEN_SKETCH", "Draws ink in the sketch with the pen or mouse and turns it into entities.")
c("PenDraw", "Draw", ("FreeWorks_PenDraw",), "PEN_DRAW", "Draws ink strokes.")
c("PenEraser", "Eraser", ("FreeWorks_PenEraser",), "PEN_ERASER", "Rubs out ink strokes.")
c("PenSelect", "Select", ("FreeWorks_PenSelect",), "PEN_SELECT", "Picks ink strokes.")
c("PenRuler", "Ruler", ("FreeWorks_PenRuler",), "PEN_RULER", "Lays a ruler: ink drawn along it comes out straight.")
c("PenProtractor", "Protractor", ("FreeWorks_PenProtractor",), "PEN_PROTRACTOR", "Lays a protractor: ink drawn along its rim comes out round.")
c("PenConvertToShape", "Convert to Shape", ("FreeWorks_PenConvertToShape",), "PEN_CONVERT_TO_SHAPE", "Turns the ink into lines, arcs and circles.")
c("PenConvertToEntities", "Convert to Entities", ("FreeWorks_PenConvertToEntities",), "PEN_CONVERT_TO_ENTITIES", "Turns the ink into splines.")

c("PenPowerModify", "Power Modify", ("FreeWorks_PenPowerModify",), "PEN_POWER_MODIFY",
  "Scratch back and forth over sketch entities or ink to delete them.")
c("PenTouch", "Ink with Touch", ("FreeWorks_PenTouch",), "PEN_TOUCH", "Draws ink with a finger on a touch screen too.")
c("PenAutoShape", "Auto Shape", ("FreeWorks_PenAutoShape",), "PEN_AUTO_SHAPE", "Each stroke becomes lines, arcs or circles as it is drawn.")
c("PenAutoSketchEntities", "Auto Sketch Entities", ("FreeWorks_PenAutoSketchEntities",), "PEN_AUTO_SKETCH_ENTITIES",
  "Each stroke becomes the sketch entity it looks like (line, arc, circle), else a spline.")
c("PenAutoSpline", "Auto Spline", ("FreeWorks_PenAutoEntities",), "PEN_AUTO_SPLINE", "Each stroke becomes a spline as it is drawn.")
c("InkColor", "Color", ("FreeWorks_InkColor",), "INK_COLOR", "The colour of the ink.")
for _name in ("Black", "Blue", "Red", "Green", "Orange", "Purple"):          # each with its colour swatch (resources/ink)
    c("InkColor" + _name, _name, ("FreeWorks_InkColor" + _name,),
      __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "resources", "ink",
                                 _name.lower() + ".svg"),
      "Draws the ink in %s." % _name.lower())
c("InsertSplinePoint", "Insert Spline Point", ("FreeWorks_Sketch3DInsertSplinePoint", "FreeWorks_InsertSplinePoint", "Sketcher_BSplineInsertKnot",), None,
  "Adds a spline point where you click on a spline; the shape stays.")
c("ShowSplineHandles", "Show Spline Handles", ("Sketcher_BSplinePolygon", "Sketcher_CompBSplineShowHideGeometryInformation"),
  "SKETCH_SPLINE", "Shows the spline's control polygon.")
c("SimplifySpline", "Simplify Spline", ("FreeWorks_SimplifySpline", "Sketcher_BSplineDecreaseDegree",), None,
  "Takes spline points away while the spline stays within a tolerance of its shape.")
c("RelaxSpline", "Relax Spline", ("FreeWorks_RelaxSpline",), None,
  "Lets the spline's handles go: the smoothest spline through the same points.")
c("SplineProportional", "Proportional", ("FreeWorks_SplineProportional",), None,
  "Dragging an end of the spline scales and turns all of it.")
c("ShowInflectionPoints", "Show Inflection Points", ("FreeWorks_ShowInflectionPoints", "SWStyle_ShowInflectionPoints",), None,
  "Shows where the picked spline changes the way it bends.")
c("ShowMinimumRadius", "Show Minimum Radius", ("FreeWorks_ShowMinimumRadius", "SWStyle_ShowMinimumRadius",), None,
  "Shows where the picked spline bends tightest, and that radius.")
c("ReverseEndpointTangent", "Flip Endpoint Tangent", ("SWStyle_ReverseEndpointTangent",), None,
  "The picked spline or tangent arc end leaves the other way.")
c("RepairDanglingRelations", "Repair Dangling Relations", ("SWStyle_RepairDanglingRelations",), None,
  "Re-attaches the sketch's dangling relations to the model edges now in their place.")
c("AutoRepairRelation", "Auto Repair Sketch Relation or Dimension", ("SWStyle_AutoRepairRelation",), None,
  "Re-attaches the picked dangling relation to the model edge now in its place.")
c("DetachSegmentOnDrag", "Detach Segment on Drag", ("SWStyle_DetachSegmentOnDrag",), None,
  "Dragging a sketch segment pulls it loose from the entities its ends are joined to.")
c("OverrideDimsOnDrag", "Override Dims on Drag/Move", ("SWStyle_OverrideDimsOnDrag",), None,
  "Dragging a sketch entity changes the dimensions that hold it.")
c("NoSolveMove", "No Solve Move", ("SWStyle_NoSolveMove",), None,
  "Dragging a sketch entity moves it alone; its relations are solved when it is let go.")
c("BeltChain", "Belt/Chain", ("SWStyle_BeltChain",), "SKETCH_BELT_CHAIN",
  "Wraps a belt round circles picked in order: tangent lines and arcs that follow the circles.")
c("JogLine", "Jog Line", ("SWStyle_JogLine",), "SKETCH_JOG_LINE", "Puts a rectangular jog into a line.")
c("CloseSketchToModel", "Close Sketch to Model", ("SWStyle_CloseSketchToModel",), "SKETCH_CLOSE_SKETCH_TO_MODEL",
  "Closes an open profile with the model's edges.")
c("SketchInk", "Sketch Ink", ("SWStyle_SketchInk",), "SKETCH_INK",
  "Strokes drawn freehand become lines, arcs, circles or splines.")
c("ShowCurvatureCombs", "Show Curvature Combs", ("FreeWorks_ShowCurvatureCombs", "Sketcher_BSplineComb",), None,
  "Shows the picked spline's curvature comb.")
c("InsertControlVertex", "Insert Control Vertex", ("Sketcher_BSplineInsertKnot",), None,
  "Adds a control vertex to a spline where it is clicked (FreeCAD inserts a knot).")
c("Slicing", "Slicing", ("SWStyle_Slicing", "Part_CrossSections"), None, "Section curves through the model at planes.")
c("Equations", "Equations", ("Spreadsheet_CreateSheet",), None,
  "Global variables and equations (FreeCAD: a spreadsheet; use its cells in expressions).")
c("DesignTable", "Design Table", ("SWStyle_InsertDesignTable", "Spreadsheet_CreateSheet"), "TABLES_DESIGN_TABLE",
  "A table of values that drive dimensions (FreeCAD spreadsheet).")
c("Redraw", "Redraw", (), None, "Redraws the graphics area.", call="redraw")
c("TakeSnapshot", "Take Snapshot", ("Std_ViewSaveCamera",), None, "Remembers the view to come back to.")
c("Reload", "Reload", ("SWStyle_Reload", "Std_Revert"), None,
  "Reloads the document and the documents it references from disk, or makes them read-only.")
c("EditMaterial", "Edit Material", ("SWStyle_EditMaterial", "Std_SetMaterial"), "TREE_MATERIAL_FOLDER", "Sets the part's material.")
c("LineFormat", "Line Format", ("SWStyle_LineFormatToolbar", "Std_SetAppearance"), None,
  "Shows or hides the Line Format toolbar: line colour, thickness and style.")
c("LineColor", "Line Color", ("SWStyle_LineColor",), None,
  "Changes the color of the selected sketch or sketch entities.")
c("LineThickness", "Line Thickness", ("SWStyle_LineThickness",), None,
  "Changes the line thickness of the selected sketch.")
c("LineStyle", "Line Style", ("SWStyle_LineStyle",), None,
  "Changes the line style of the selected sketch entities.")
c("MakeBlock", "Make Block", ("SWStyle_MakeBlock",), "BLOCK_MAKE", "Makes a block from the selected sketch entities.")
c("EditBlock", "Edit Block", ("SWStyle_EditBlock",), "BLOCK_EDIT", "Edits the selected block.")
c("InsertBlock", "Insert Block", ("SWStyle_InsertBlock",), "BLOCK_INSERT",
  "Inserts a block of this document or of a block file.")
c("AddRemoveBlockEntities", "Add/Remove Entities", ("SWStyle_AddRemoveBlockEntities",), "BLOCK_ADD_REMOVE",
  "Adds entities to the selected block or takes them out.")
c("RebuildBlocks", "Rebuild", ("SWStyle_RebuildBlocks",), "BLOCK_REBUILD", "Rebuilds the blocks of the sketch.")
c("SaveBlock", "Save Block", ("SWStyle_SaveBlock",), "BLOCK_SAVE", "Saves the selected block to a file.")
c("ExplodeBlock", "Explode Block", ("SWStyle_ExplodeBlock",), "BLOCK_EXPLODE",
  "Breaks the selected block into its sketch entities.")
c("HideShowBlock", "Hide Block", ("SWStyle_HideShowBlock",), "I3DVIEW_HIDE_SHOW_ITEMS",
  "Hides the selected block's entities; Show in the block's tree row brings them back.")
c("PowerSelect", "Power Select", ("Std_SelectVisibleObjects",), None, "Selects entities by type (FreeCAD: all visible).")

c("Plane", "Plane", ("SWStyle_RefPlane", "PartDesign_Plane"), "REFGEO_PLANE", "Adds a reference plane.")
c("Axis", "Axis", ("SWStyle_RefAxis", "PartDesign_Line"), "REFGEO_AXIS", "Adds a reference axis.")
c("CoordinateSystem", "Coordinate System", ("SWStyle_RefCoordinateSystem", "PartDesign_CoordinateSystem"), "REFGEO_CSYS",
  "Adds a reference coordinate system.")
c("Point", "Point", ("SWStyle_RefPoint", "PartDesign_Point"), "REFGEO_POINT", "Adds a reference point.")
c("ShapeBinder", "Reference Geometry Copy", ("PartDesign_SubShapeBinder", "PartDesign_ShapeBinder"),
  None, "Copies geometry from another body (FreeCAD Shape Binder).")
c("ReferenceGeometry", "Reference Geometry", ("SWStyle_RefPlane", "PartDesign_Plane"), "FLYOUT_REF_GEO",
  "Reference geometry commands.", caption="Reference\nGeometry")
c("MateReference", "Mate Reference", ("SWStyle_MateReference",), "REFGEO_MATE_REF",
  "Names faces, edges or planes the part mates by when it goes into an assembly.")
c("BoundingBox", "Bounding Box", ("SWStyle_BoundingBox",), None,
  "Adds the box round the part, with its length, width and height.")
c("InvertSelection", "Invert Selection", ("SWStyle_InvertSelection",), None,
  "Selects every other face, edge or body of the same kind instead.")
c("DeleteHole", "Delete Hole", ("SWStyle_DeleteHole",), None, "Fills the holes of a surface face.")
c("SaveBodies", "Save Bodies", ("SWStyle_SaveBodies",), None, "Saves the part's bodies as separate files.")
c("CreateAssembly", "Create Assembly", ("SWStyle_CreateAssembly",), "FEATURES_CREATE_ASSEMBLY",
  "Saves the part's bodies as parts and makes an assembly of them.")
c("CenterOfMass", "Center of Mass", ("SWStyle_CenterOfMass",), None,
  "Adds a point at the part's centre of mass that follows the part.")
c("CompositeCurve", "Composite Curve", ("SWStyle_CompositeCurve",), None,
  "Joins the selected edges and sketch curves into one curve.")
c("CurveThroughXYZPoints", "Curve Through XYZ Points", ("SWStyle_CurveThroughXYZPoints",), None,
  "Makes a curve through points typed in or read from a file.")
c("CurveThroughReferencePoints", "Curve Through Reference Points", ("SWStyle_CurveThroughReferencePoints",),
  "CURVES_REF_POINTS", "Makes a curve through the selected vertices and points.")
c("Curves", "Curves", ("SWStyle_CompositeCurve",), None, "Curve commands.")
c("Suppress", "Suppress", ("SWStyle_Suppress",), None,
  "Removes the selected features and their children from the model; they stay in the tree, greyed.")
c("Unsuppress", "Unsuppress", ("SWStyle_Unsuppress",), None,
  "Puts suppressed features back into the model.")
c("UnsuppressWithDependents", "Unsuppress with Dependents", ("SWStyle_UnsuppressWithDependents",),
  "FEATURES_UNSUPPRESS_DEPENDENTS", "Puts the selected features and their children back into the model.")
c("Thread", "Thread", ("SWStyle_Thread", "PartDesign_SubtractiveHelix"), None,
  "Cuts or adds a helical thread on a cylindrical edge.")
c("CosmeticThread", "Cosmetic Thread", ("SWStyle_CosmeticThread", "PartDesign_Hole"), "FEATURES_COSMETIC_THREAD",
  "Shows a thread on a round shaft or hole without modelling it.")
c("MoveFace", "Move Face", ("SWStyle_MoveFace", "Part_Offset"), None,
  "Offsets, moves or rotates faces of the solid directly.")
c("Body", "Insert Body", ("PartDesign_Body",), "ASSEM_SOLID_BODY_FOLDER",
  "Creates a new FreeCAD body to hold features.")

# ---- Sketch tab ----------------------------------------------------------------------
c("Sketch", "Sketch", ("PartDesign_NewSketch", "Sketcher_NewSketch"), "SKETCH_SKETCH",
  "Creates a new sketch, or edits an existing sketch.")
c("Sketch3D", "3D Sketch", ("FreeWorks_Sketch3D",), "SKETCH_3D_SKETCH",
  "Adds a new 3D sketch, or edits the picked one. Tab changes the sketch plane.")
c("Sketch3DOnPlane", "3D Sketch On Plane", ("FreeWorks_Sketch3DOnPlane",), "SKETCH_3D_SKETCH",
  "Adds a 3D sketch that draws on the picked plane or flat face.")
c("Exit3DSketch", "Exit Sketch", ("FreeWorks_Sketch3DExit",), "EXIT_SKETCH_CANCEL",
  "Exits the 3D sketch and keeps all changes.", caption="Exit\nSketch")
c("Sketch3DPlane", "Plane", ("FreeWorks_Sketch3DPlane",), "REFGEO_PLANE",
  "Adds a sketch plane to the 3D sketch (only in a 3D sketch).")
c("ExitSketch", "Exit Sketch", ("Sketcher_LeaveSketch",), "EXIT_SKETCH_CANCEL",
  "Exits the sketch and keeps all changes.", caption="Exit\nSketch")
c("EditSketch", "Edit Sketch", ("Sketcher_EditSketch",), "SKETCH_MODIFY")
c("SmartDimension", "Smart Dimension", ("FreeWorks_SmartDimension", "Sketcher_Dimension", "Sketcher_ConstrainDistance"), "LAYOUT_SMART_DIM",
  "Creates a dimension for one or more selected entities.", caption="Smart\nDimension")
c("HorizontalDimension", "Horizontal Dimension", ("Sketcher_ConstrainDistanceX",), "DIMENSIONS_HORIZ", tip="Dimensions the horizontal distance between two points or along a line.")
c("VerticalDimension", "Vertical Dimension", ("Sketcher_ConstrainDistanceY",), "DIMENSIONS_VERT", tip="Dimensions the vertical distance between two points or along a line.")
c("AngularDimension", "Angular Dimension", ("Sketcher_ConstrainAngle",), "DIMENSIONS_ANGULAR", tip="Dimensions the angle between two lines or three points.")
c("RadiusDimension", "Radius/Diameter Dimension", ("Sketcher_ConstrainRadiam", "Sketcher_ConstrainRadius"), "SKETCH_ADD_DIM", tip="Dimensions the radius of an arc or the diameter of a circle.")
# dimensioning and sketch tools (relations thread, packages 13b and 14)
c("BaselineDimension", "Baseline Dimension", ("SWStyle_BaselineDimension",), "DIMENSIONS_BASELINE")
c("ChainDimension", "Chain Dimension", ("SWStyle_ChainDimension",), "DIMENSIONS_CHAIN", tip="Dimensions a run of points or edges, each measured from the one before it.")
c("OrdinateDimension", "Ordinate Dimension", ("SWStyle_OrdinateDimension",), "DIMENSIONS_ORDINATE")
c("HorizontalOrdinateDimension", "Horizontal Ordinate Dimension", ("SWStyle_HorizontalOrdinateDimension",), "DIMENSIONS_ORDINATE")
c("VerticalOrdinateDimension", "Vertical Ordinate Dimension", ("SWStyle_VerticalOrdinateDimension",), "DIMENSIONS_ORDINATE")
c("AngularRunningDimension", "Angular Running Dimension", ("SWStyle_AngularRunningDimension",), "DIMENSIONS_ANGULAR", tip="Dimensions a set of angles, all measured from the same zero line.")
c("SymmetricLinearDiameterDimension", "Symmetric Linear Diameter Dimension",
  ("SWStyle_SymmetricLinearDiameterDimension",), "DIMENSIONS_SYMMETRIC_DIAMETER",
  "Dimensions the diameter of a revolved profile, measured across its centreline.")
c("ChamferDimension", "Chamfer Dimension", ("SWStyle_ChamferDimension",), "DIMENSIONS_CHAMFER")
c("PathLengthDimension", "Path Length Dimension", ("SWStyle_PathLengthDimension", "Sketcher_ConstrainDistance"),
  "SKETCH_PATH_LENGTH_DIMENSION", "The total length of a chain of sketch entities, driving or driven.")
c("FullyDefineSketch", "Fully Define Sketch", ("SWStyle_FullyDefineSketch",), "DIMENSIONS_FULLY_DEFINE_SKETCH",
  "Adds the fitting relations, then dimensions, until the sketch is fully defined.")
c("AutoInsertDimension", "Auto Insert Dimension", ("SWStyle_AutoInsertDimension",), "SKETCH_AUTO_DIM",
  "Dimensions the sketch, or the picked entities, until nothing is free.")
c("ScanEqual", "Scan Equal", ("SWStyle_ScanEqual",), "DIMENSIONS_SCAN_EQUAL",
  "Finds lines of equal length and arcs or circles of equal radius, and sets them equal.")
c("DynamicMirror", "Dynamic Mirror Entities", ("SWStyle_DynamicMirror",), "SKETCH_DYNAMIC_MIRROR",
  "Pick a centerline, then sketch: each entity gets a mirrored copy. Click again to stop.")
c("RapidSketch", "Rapid Sketch", ("SWStyle_RapidSketch",), "RAPID_SKETCH",
  "When on, a click on a flat face with a sketch tool running starts a sketch there with the same tool.")
c("Instant2D", "Instant2D", ("SWStyle_Instant2D",), "SKETCH_INSTANT_2D", "When on, dragging a dimension changes its value.")
c("SketchXpert", "SketchXpert", ("SWStyle_SketchXpert",), None,
  "Finds ways to fix an over-defined sketch, or deletes the clashing relations and dimensions.")
c("EditPolygon", "Edit Polygon", ("SWStyle_EditPolygon",), "SKETCH_POLYGON",
  "Changes a picked polygon's sides, size, centre and angle.")
c("ViewSketchRelations", "Sketch Relations", ("SWStyle_ViewSketchRelations",), "VIEW_SKETCH_RELATIONS",
  "Shows or hides the relation glyphs of the sketch being edited.")
c("ViewSketchDimensions", "Sketch Dimensions", ("SWStyle_ViewSketchDimensions",), "VIEW_SKETCH_DIMENSIONS",
  "Shows or hides the dimensions of the sketch being edited.")
c("DerivedSketch", "Derived Sketch", ("SWStyle_DerivedSketch",), None,
  "Pick a sketch and a plane or face: a copy goes on the plane and follows the original's dimensions.")
c("SketchDimensionDriven", "Sketch Dimension Driven", ("Sketcher_ToggleDrivingConstraint",), None,
  "Switches a picked dimension between driving and driven.")

# tool: segments chain, back over the end point and away gives a tangent or normal arc,
# A switches line/arc, one Esc ends the tool.
c("Line", "Line", ("FreeWorks_Line", "Sketcher_CreatePolyline",), "SKETCH_LINE",
  "Sketches a line. Keep clicking to chain lines; move back over the end point for an arc.")
c("Polyline", "Single Line", ("Sketcher_CreateLine",), "SKETCH_LINE", "Sketches one line at a time (FreeCAD's Line tool).")
c("MidpointLine", "Midpoint Line", ("FreeWorks_MidpointLine", "Sketcher_CreateMidpointLine",), "SKETCH_MIDPOINT_LINE",
  "Sketches a line from its midpoint: the first click sets the middle, the line is symmetric about it.")
c("Centerline", "Centerline", ("FreeWorks_Centerline", "SWStyle_Centerline",), "SKETCH_CENTERLINE",
  "Sketches centerlines: the Line tool with For construction ticked.")
c("Circle", "Circle", ("FreeWorks_Circle", "Sketcher_CreateCircle",), "SKETCH_CIRCLE", "Sketches a circle. Select the center and drag to set the radius.")
c("PerimeterCircle", "Perimeter Circle", ("FreeWorks_PerimeterCircle", "Sketcher_Create3PointCircle",), "SKETCH_CTRPT_CIRCLE",
  "Sketches a circle through three points on its perimeter.")
c("Spline", "Spline", ("FreeWorks_Spline", "Sketcher_CreateBSpline",), "SKETCH_SPLINE",
  "Sketches a spline through the points you click; double-click or Esc ends it.")
c("StyleSpline", "Style Spline", ("FreeWorks_StyleSpline", "Sketcher_CreateBSpline"), "SKETCH_STYLE_SPLINE",
  "Sketches a spline shaped by its control polygon: click the vertices, double-click or Esc ends it.")
c("SplineOnSurface", "Spline on Surface", ("FreeWorks_Sketch3DSplineOnSurface",), "SKETCH_SPLINE_ON_SURFACE",
  "Sketches a spline on a model face (starts a 3D sketch when none is open).")
c("SplineInterpolation", "Spline Through Points", ("Sketcher_CreateBSplineByInterpolation",), "SKETCH_STYLE_SPLINE")
c("PeriodicSpline", "Closed Spline", ("Sketcher_CreatePeriodicBSpline",), "SKETCH_SPLINE")
c("ConstructionPlane", "Construction Geometry", ("Sketcher_ToggleConstruction",), "SKETCH_CONSTRUCT_GEOM",
  "Toggles construction geometry mode.")
c("CornerRectangle", "Corner Rectangle", ("FreeWorks_CornerRectangle", "Sketcher_CreateRectangle",), "SKETCH_CORNER_RECT", "Sketches a rectangle.")
c("CenterRectangle", "Center Rectangle", ("FreeWorks_CenterRectangle", "Sketcher_CreateRectangle_Center",), "SKETCH_CTR_RECT",
  "Sketches a rectangle at a center point.")
c("ThreePointCornerRectangle", "3 Point Corner Rectangle", ("FreeWorks_3PointCornerRectangle", "SWStyle_3PointCornerRectangle"), "SKETCH_3PT_CORNER_RECT",
  "Sketches a rectangle at an angle: two corners, then the width.")
c("ThreePointCenterRectangle", "3 Point Center Rectangle", ("FreeWorks_3PointCenterRectangle", "SWStyle_3PointCenterRectangle"), "SKETCH_3PT_CENTER_RECT",
  "Sketches a rectangle at an angle from its center point.")
c("Parallelogram", "Parallelogram", ("FreeWorks_Parallelogram", "SWStyle_Parallelogram"), "SKETCH_PARALLELOGRAM",
  "Sketches a parallelogram: two corners, then the third.")
c("Oblong", "Rounded Rectangle", ("Sketcher_CreateOblong",), None, "Sketches a rectangle with rounded corners.")
c("CenterArc", "Centerpoint Arc", ("FreeWorks_CenterArc", "Sketcher_CreateArc",), "SKETCH_CPRPT_ARC",
  "Sketches an arc from a center point, a start point, and an end point.")
c("TangentArc", "Tangent Arc", ("FreeWorks_TangentArc", "Sketcher_CreatePolyline",), "SKETCH_TANGET_ARC",
  "Sketches tangent arcs from line ends (FreeCAD Polyline arc mode, press M to switch).")
c("ThreePointArc", "3 Point Arc", ("FreeWorks_ThreePointArc", "Sketcher_Create3PointArc",), "SKETCH_3PT_ARC",
  "Sketches an arc by specifying three points.")
c("Ellipse", "Ellipse", ("FreeWorks_Ellipse", "Sketcher_CreateEllipseByCenter"), "SKETCH_ELLIPSE", "Sketches a complete ellipse.")
c("PartialEllipse", "Partial Ellipse", ("FreeWorks_PartialEllipse", "Sketcher_CreateArcOfEllipse"), "SKETCH_PARTIAL_ELLIPSE")
c("Parabola", "Parabola", ("Sketcher_CreateArcOfParabola",), "SKETCH_PARABOLA")
c("Conic", "Conic", ("SWStyle_Conic", "Sketcher_CreateArcOfHyperbola"), "SKETCH_CONIC",
  "Sketches a conic: start, end, top vertex, then Rho (0.5 parabola, less an ellipse, more a hyperbola).")
c("Text", "Text", ("SWStyle_SketchText",), "SKETCH_TEXT",
  "Sketches text whose outlines can be extruded; pick a text and click again to edit it.")
c("DissolveSketchText", "Dissolve Sketch Text", ("SWStyle_DissolveSketchText",), None,
  "Turns the selected sketch text into plain sketch entities.")
c("Slot", "Straight Slot", ("FreeWorks_StraightSlot", "Sketcher_CreateSlot",), "SKETCH_STRAIGHT_SLOT", "Sketches a straight slot.")
c("CenterpointSlot", "Centerpoint Straight Slot", ("FreeWorks_CenterpointStraightSlot", "SWStyle_CenterpointStraightSlot",), "SKETCH_CTRPT_STRAIGHT_SLOT",
  "Sketches a straight slot from its center point.")
c("ThreePointArcSlot", "3 Point Arc Slot", ("FreeWorks_ThreePointArcSlot", "SWStyle_3PointArcSlot",), "SKETCH_3PT_ARC_SLOT",
  "Sketches an arc slot through three points on its centre arc.")
c("ArcSlot", "Centerpoint Arc Slot", ("FreeWorks_CenterpointArcSlot", "Sketcher_CreateArcSlot",), "SKETCH_CTRPT_ARC_SLOT")
c("Polygon", "Polygon", ("FreeWorks_Polygon", "Sketcher_CreateRegularPolygon", "Sketcher_CreateHexagon"), "SKETCH_POLYGON",
  "Sketches a polygon; choose the number of sides.")
c("RegularPolygon", "Polygon (choose sides)", ("Sketcher_CreateRegularPolygon",), "SKETCH_POLYGON")
c("SketchFillet", "Sketch Fillet", ("SWStyle_SketchFillet", "Sketcher_CreateFillet"), "SKETCH_FILLET",
  "Rounds the corner at the intersection of two sketch entities.")
c("SketchChamfer", "Sketch Chamfer", ("SWStyle_SketchChamfer", "Sketcher_CreateChamfer"), "SKETCH_CHAMFER")
c("SketchPoint", "Point", ("FreeWorks_Point", "Sketcher_CreatePoint",), "SKETCH_POINT", "Sketches a point.")
c("EquationDrivenCurve", "Equation Driven Curve", ("SWStyle_EquationDrivenCurve",), "SKETCH_EQUATION_CURVE",
  "Sketches a curve from an explicit y = f(x) or parametric x(t), y(t) equation.")
c("FitSpline", "Fit Spline", ("SWStyle_FitSpline",), "SKETCH_FIT_SPLINE",
  "Replaces a chain of sketch entities with one spline that follows them.")
c("Segment", "Segment", ("SWStyle_Segment",), "SKETCH_SEGMENT",
  "Splits a sketch entity into equal segments or adds equally spaced points on it.")
c("FaceCurves", "Face Curves", ("SWStyle_FaceCurves",), "SKETCH_FACE_CURVES", "Makes a grid of curves across a face.")
c("Trim", "Trim Entities", ("FreeWorks_Trim", "Sketcher_Trimming",), "SKETCH_TRIM",
  "Trims or extends a sketch entity to be coincident to another.", caption="Trim\nEntities")
c("Extend", "Extend Entities", ("FreeWorks_Extend", "Sketcher_Extend"), "SKETCH_EXTEND_ENTITIES")
c("Split", "Split Entities", ("FreeWorks_Split", "Sketcher_Split"), "SKETCH_SPLIT_ENTITIES")
c("Join", "Join Curves", ("Sketcher_JoinCurves",), "SKETCH_MAKE_PATH")
c("Convert", "Convert Entities", ("SWStyle_ConvertEntities", "Sketcher_Projection", "Sketcher_External"), "SKETCH_CONVERT_ENTITIES",
  "Converts selected model edges or sketch entities into sketch segments.", caption="Convert\nEntities")
c("IntersectionCurve", "Intersection Curve", ("FreeWorks_Sketch3DIntersectionCurve", "Sketcher_Intersection",), "SKETCH_INTERSECTION_CURVE")
c("CarbonCopy", "Copy Sketch", ("Sketcher_CarbonCopy",), "SKETCH_COPY_ENTITIES")
c("Offset", "Offset Entities", ("SWStyle_OffsetEntities", "Sketcher_Offset"), "SKETCH_OFFSET_ENTITIES",
  "Adds sketch entities by offsetting faces, edges, curves or sketch entities.", caption="Offset\nEntities")
c("OffsetOnSurface", "Offset On Surface", ("FreeWorks_Sketch3DOffsetOnSurface", "SWStyle_OffsetOnSurface",), "SKETCH_OFFSET_ON_SURFACE",
  "Offsets edges and faces across their faces, staying on them, in a 3D sketch.",
  caption="Offset\nOn\nSurface")
c("MirrorEntities", "Mirror Entities", ("SWStyle_MirrorEntities", "Sketcher_Symmetry"), "SKETCH_MIRROR_ENTITIES",
  "Mirrors selected entities about a centerline.")
c("MakePath", "Make Path", ("SWStyle_MakePath",), "SKETCH_MAKE_PATH",
  "Makes one path of the selected sketch entities, joined end to end.")
c("DissolvePath", "Dissolve Path", ("SWStyle_DissolvePath",), None, "Breaks the selected path into its sketch entities.")
c("LinearSketchPattern", "Linear Sketch Pattern", ("SWStyle_LinearSketchPattern", "Sketcher_Translate", "Sketcher_RectangularArray"),
  "SKETCH_LINEAR_PATTERN", "Adds a linear pattern of sketch entities.")
c("CircularSketchPattern", "Circular Sketch Pattern", ("SWStyle_CircularSketchPattern", "Sketcher_Rotate"), "SKETCH_CIR_PATTERN")
c("MoveEntities", "Move Entities", ("SWStyle_MoveEntities", "Sketcher_Translate"), "SKETCH_MOVE_ENTITIES", "Moves selected sketch entities.")
c("CopyEntities", "Copy Entities", ("SWStyle_CopyEntities", "Sketcher_Translate"), "SKETCH_COPY_ENTITIES", "Copies selected sketch entities.")
c("RotateEntities", "Rotate Entities", ("SWStyle_RotateEntities", "Sketcher_Rotate"), "SKETCH_ROTATE_ENTITIES")
c("ScaleEntities", "Scale Entities", ("SWStyle_ScaleEntities", "Sketcher_Scale"), "SKETCH_SCALE_ENTITIES")
c("StretchEntities", "Stretch Entities", ("SWStyle_StretchEntities", "Sketcher_Translate"), "SKETCH_STRETCH_ENTITIES",
  "Stretches sketch entities: the points picked move, the rest stay, relations kept.")
c("ReplaceEntity", "Replace Entity", ("SWStyle_ReplaceEntity", "Sketcher_SwitchVirtualSpace"), "SKETCH_REPLACE_ENTITY",
  "Replaces a sketch entity with another, keeping its relations, dimensions and the features that use it.")
c("Dissolve", "Dissolve", ("FreeWorks_Sketch3DDissolve", "SWStyle_DissolveSketchText"), None,
  "Dissolves the selected sketch text or 3D sketch entities into plain sketch geometry.")
c("CreateSketchFromSelections", "Create Sketch from Selections", ("FreeWorks_SketchFromSelections",), "2DTO3D_CREATE_SKETCH_FROM_SEL",
  "Makes a new sketch from the picked sketch entities, keeping the original sketch.",
  caption="Create Sketch\nfrom Selections")
c("Relations", "Display/Delete Relations", ("SWStyle_DisplayDeleteRelations", "Sketcher_SelectConstraints"), "LAYOUT_DISPLAY_DEL_RELATION",
  "Shows the relations of the selected entities so they can be reviewed or deleted.",
  caption="Display/Delete\nRelations")
c("AddRelation", "Add Relation", ("SWStyle_AddRelations", "Sketcher_ConstrainCoincidentUnified", "Sketcher_ConstrainCoincident"),
  "LAYOUT_ADD_RELATION", "Adds geometric relations between the picked entities.")
c("Horizontal", "Horizontal", ("Sketcher_ConstrainHorizontal",), "DIMENSIONS_HORIZ")
c("Vertical", "Vertical", ("Sketcher_ConstrainVertical",), "DIMENSIONS_VERT")
c("Parallel", "Parallel", ("Sketcher_ConstrainParallel",), "INFERENCE_PARALLEL_SNAP")
c("Perpendicular", "Perpendicular", ("Sketcher_ConstrainPerpendicular",), "INFERENCE_PERP_SNAP")
c("Tangent", "Tangent", ("Sketcher_ConstrainTangent",), "INFERENCE_TANGENT_SNAP")
c("Equal", "Equal", ("Sketcher_ConstrainEqual",), "DIMENSIONS_SCAN_EQUAL")
c("Symmetric", "Symmetric", ("Sketcher_ConstrainSymmetric",), "SKETCH_DYNAMIC_MIRROR")
c("Fix", "Fix", ("Sketcher_ConstrainBlock", "Sketcher_ConstrainLock"), "PIN_ACTIVE")
c("ConflictingRelations", "Select Conflicting Relations", ("Sketcher_SelectConflictingConstraints",), "OVERLAY_FMTREE_ERROR")
c("RedundantRelations", "Select Redundant Relations", ("Sketcher_SelectRedundantConstraints",), "OVERLAY_FMTREE_WARNING")
c("MalformedRelations", "Select Malformed Relations", ("Sketcher_SelectMalformedConstraints",), "OVERLAY_FMTREE_ERROR",
  "Selects the relations that point at missing geometry (FreeCAD).")
c("PartiallyRedundantRelations", "Select Partially Redundant Relations", ("Sketcher_SelectPartiallyRedundantConstraints",),
  "OVERLAY_FMTREE_WARNING", "Selects the relations that are partly said by others (FreeCAD).")

c("SplineShowDegree", "Show Degree", ("Sketcher_BSplineDegree",), None, "Shows or hides the degree of every spline (FreeCAD).")
c("SplineShowKnotMultiplicity", "Show Knot Multiplicity", ("Sketcher_BSplineKnotMultiplicity",), None,
  "Shows or hides the knot multiplicity of every spline (FreeCAD).")
c("SplineShowPoleWeight", "Show Control Point Weight", ("Sketcher_BSplinePoleWeight",), None,
  "Shows or hides the weight of every spline control point (FreeCAD).")
c("SplineShowPolygon", "Show Control Polygon", ("Sketcher_BSplinePolygon",), None,
  "Shows or hides the control polygon of every spline (FreeCAD).")
c("SplineShowComb", "Show Curvature Comb", ("Sketcher_BSplineComb",), None,
  "Shows or hides the curvature comb of every spline (FreeCAD).")
c("SketchArcOverlay", "Show Arc Helpers", ("Sketcher_ArcOverlay",), None,
  "Shows or hides the full circle of every arc (FreeCAD).")
c("DeleteAllRelations", "Delete All Relations", ("Sketcher_DeleteAllConstraints",), "STANDARD_DELETE")
c("Instant3D", "Instant3D", ("SWStyle_Instant3D",), None,
  "Pick an extrude's end face and drag its arrow to change the depth on screen.")
c("ModifySketch", "Modify Sketch", ("SWStyle_ModifySketch",), None, "Moves or turns the whole sketch on its plane.")
c("ShadedSketchContours", "Shaded Sketch Contours", ("SWStyle_ShadedSketchContours",), None,
  "Fills the closed areas of the sketch being edited.", caption="Shaded Sketch\nContours")
c("CheckSketchForFeature", "Check Sketch for Feature", ("SWStyle_CheckSketchForFeature",), None,
  "Says whether the sketch can make the chosen feature, and what stops it.")
c("RadiateSurface", "Radiate Surface", ("SWStyle_RadiateSurface",), None,
  "Makes a surface running out from planar edges, in their plane.")
c("AddComment", "Add Comment", ("SWStyle_AddComment",), None, "Adds a comment to the selected feature.")
c("DeviationAnalysis", "Deviation Analysis", ("SWStyle_DeviationAnalysis",), None,
  "Measures the angle between faces along the picked edges.")
c("ViewPrimaryPlanes", "View Primary Planes", ("SWStyle_ViewPrimaryPlanes",), "VIEW_PRIMARY_PLANES",
  "Shows or hides the Front, Top and Right planes only.")
c("ViewTemporaryAxes", "Temporary Axes", ("SWStyle_ViewTemporaryAxes",), "VIEW_TEMPORARY_AXES",
  "Shows or hides the axes of cylindrical and conical faces.")
c("ViewCenterOfMass", "View Center of Mass", ("SWStyle_ViewCenterOfMass",), "VIEW_CENTER_OF_MASS", "Shows or hides the Center of Mass point.")
c("ViewBoundingBox", "View Bounding Box", ("SWStyle_ViewBoundingBox",), "VIEW_BOUNDING_BOX", "Shows or hides the Bounding Box.")
c("RepairSketch", "Repair Sketch", ("SWStyle_RepairSketch", "Sketcher_ValidateSketch"), "TOOLS_CHECK",
  "Finds and repairs sketch errors.", caption="Repair\nSketch")
c("QSPoint", "Point Snap", ("SWStyle_QuickSnapPoint",), "QS_POINT", "Only this snap for the next entity.")
c("QSCenterPoint", "Center Point Snap", ("SWStyle_QuickSnapCenterPoint",), "QS_CENTER_POINT", "Only this snap for the next entity.")
c("QSMidpoint", "Midpoint Snap", ("SWStyle_QuickSnapMidpoint",), "QS_MIDPOINT", "Only this snap for the next entity.")
c("QSQuadrant", "Quadrant Snap", ("SWStyle_QuickSnapQuadrant",), "QS_QUADRANT", "Only this snap for the next entity.")
c("QSIntersection", "Intersection Snap", ("SWStyle_QuickSnapIntersection",), "QS_INTERSECTION", "Only this snap for the next entity.")
c("QSNearest", "Nearest Snap", ("SWStyle_QuickSnapNearest",), "QS_NEAREST", "Only this snap for the next entity.")
c("QSTangent", "Tangent Snap", ("SWStyle_QuickSnapTangent",), "QS_TANGENT", "Only this snap for the next entity.")
c("QSPerpendicular", "Perpendicular Snap", ("SWStyle_QuickSnapPerpendicular",), "QS_PERPENDICULAR", "Only this snap for the next entity.")
c("QSParallel", "Parallel Snap", ("SWStyle_QuickSnapParallel",), "QS_PARALLEL", "Only this snap for the next entity.")
c("QSHV", "Horizontal/Vertical Snap", ("SWStyle_QuickSnapHV",), "QS_HV", "Only this snap for the next entity.")
c("QSHVPoint", "Horizontal/Vertical to Points Snap", ("SWStyle_QuickSnapHVPoint",), "QS_HV_POINT", "Only this snap for the next entity.")
c("QSLength", "Length Snap", ("SWStyle_QuickSnapLength",), "QS_LENGTH", "Only this snap for the next entity.")
c("QSGrid", "Grid Snap", ("SWStyle_QuickSnapGrid",), "QS_GRID", "Only this snap for the next entity.")
c("QSAngle", "Angle Snap", ("SWStyle_QuickSnapAngle",), "QS_ANGLE", "Only this snap for the next entity.")
c("QuickSnaps", "Quick Snaps", ("Sketcher_Snap", "Sketcher_Grid"), "FLYOUT_QUICK_SNAPS",
  "Sketch snap and grid options.", caption="Quick\nSnaps")
c("SketchGrid", "Grid", ("Sketcher_Grid",), "SKETCH_GRID_SNAP")
c("ViewSketch", "Normal To Sketch", ("Sketcher_ViewSketch",), "VIEWORIENT_NORMAL_TO")
c("SectionSketch", "Section View", ("Sketcher_ViewSection",), "I3DVIEW_SECT_VIEW")

c("MergeSketches", "Merge Sketches", ("Sketcher_MergeSketches",), None,
  "Makes one new sketch from the sketches picked in the tree (FreeCAD).")
c("MirrorSketch", "Mirror Sketch", ("Sketcher_MirrorSketch",), None,
  "Makes a mirrored copy of the sketches picked in the tree (FreeCAD).")
c("RemoveAxesAlignment", "Remove Axes Alignment", ("Sketcher_RemoveAxesAlignment",), None,
  "Swaps the picked entities' Horizontal and Vertical for relations that keep them as they are when turned (FreeCAD).")
c("SplineIncreaseDegree", "Increase Degree", ("Sketcher_BSplineIncreaseDegree",), None,
  "Raises the picked spline's degree by one, keeping its shape (FreeCAD).")
c("SplineDecreaseDegree", "Decrease Degree", ("Sketcher_BSplineDecreaseDegree",), None,
  "Lowers the picked spline's degree by one (FreeCAD).")
c("SplineIncreaseKnotMultiplicity", "Increase Knot Multiplicity", ("Sketcher_BSplineIncreaseKnotMultiplicity",), None,
  "Raises the multiplicity of the picked knot (FreeCAD).")
c("SplineDecreaseKnotMultiplicity", "Decrease Knot Multiplicity", ("Sketcher_BSplineDecreaseKnotMultiplicity",), None,
  "Lowers the multiplicity of the picked knot (FreeCAD).")
c("SelectAssociatedGeometry", "Select Associated Geometry", ("Sketcher_SelectElementsAssociatedWithConstraints",), None,
  "Selects the entities the picked relations and dimensions are on (FreeCAD).")
c("ToggleInternalGeometry", "Show/Hide Internal Geometry", ("Sketcher_RestoreInternalAlignmentGeometry",), None,
  "Shows or hides the construction lines and points of the picked ellipse or spline (FreeCAD).")

# ---- Evaluate tab --------------------------------------------------------------------
c("DesignStudy", "Design Study", ("SWStyle_DesignStudy",), "TOOLS_DESIGN_STUDY",
  "Tries the part over sets of values for some of its sizes and compares the results.", caption="Design\nStudy")
c("DesignStudyParameters", "Parameters", ("SWStyle_DesignParameters",), None,
  "Names the model's dimensions so a Design Study's variables can use them.")
c("Interference", "Interference Detection", ("SWStyle_InterferenceDetection",), "ASSEMBLIES_INTERFERENCE_DETECTION",
  "Finds overlapping volumes between the bodies of the part.", caption="Interference\nDetection")
c("MassProperties", "Mass Properties", (), "TOOLS_MASS_PROPS",
  "Shows mass, volume, surface area and center of mass of the selected body.",
  call="mass_properties", caption="Mass\nProperties")
c("Measure", "Measure", ("SWStyle_Measure", "Std_Measure", "Part_Measure_Linear"), "TOOLS_MEASURE",
  "Measures distance, angle, radius and size of selected entities.")
c("FeaturePaint", "Feature Paint", ("SWStyle_FeaturePaint",), "TOOLS_FEATURE_PAINT",
  "Copies one feature's settings onto other features of the same kind.")
c("Markup", "Markup", ("SWStyle_Markup",), "FLYOUT_ANNOTATIONS",
  "Draws freehand marks and notes over the model, kept with the view.")
c("GoToMarkupView", "Go to Markup View", ("SWStyle_GoToMarkupView",), "VIEW_MARKUPS",
  "Turns the view back to the one the picked markup was drawn in.")
c("Sensor", "Sensor", ("SWStyle_Sensor",), "TOOLS_SENSOR",
  "Watches a mass property after every rebuild and alerts when it goes out of its limits.")
c("SectionProperties", "Section Properties", ("SWStyle_SectionProperties",), "TOOLS_SECTION_PROPS",
  "Area, centroid and area moments of the selected planar faces or sketch.")
c("ImportDiagnostics", "Import Diagnostics", ("SWStyle_ImportDiagnostics", "Part_CheckGeometry"), "TOOLS_IMPORT_DIAGNOSTICS",
  "Finds faults in imported geometry (FreeCAD Check geometry; it reports, it does not repair).")
c("PerformanceEvaluation", "Performance Evaluation", ("SWStyle_PerformanceEvaluation",), "TOOLS_STATS",
  "Rebuild time of every feature, slowest first.")
c("GeometryAnalysis", "Geometry Analysis", ("SWStyle_GeometryAnalysis",), "TOOLS_GEOM_ANALYSIS",
  "Finds short edges, small and sliver faces and knife edges.")
c("BodyCompare", "Body Compare", ("SWStyle_BodyCompare",), "I3DVIEW_BODYCOMPARISON",
  "Compares two bodies and shows where their volumes differ.")
c("CompareDocuments", "Compare", ("SWStyle_Compare",), "TOOLS_COMPARE",
  "Compares two open documents: their properties, features and geometry.")
c("FindModify", "Find/Modify", ("SWStyle_FindModify",), "TOOLS_FIND_MODIFY",
  "Finds the part's sizes by feature type and value, and changes them all at once.")
c("FloXpress", "FloXpress Analysis Wizard", ("SWStyle_FloXpress",), None,
  "A first look at a fluid flowing through the model.", caption="FloXpress\nAnalysis Wizard")
c("CheckActiveDocument", "Check Active Document", ("SWStyle_DesignCheckActive",), None,
  "Checks the active document against the Design Checker standard.", caption="Check Active\nDocument")
c("DesignCheckBuild", "Build Checks", ("SWStyle_DesignCheckBuild",), None, "Makes a standard of design checks.")
c("DesignCheckLearn", "Learn Checks Wizard", ("SWStyle_DesignCheckLearn",), None, "Makes a standard from the active document.")
c("DesignCheckFile", "Check Against Existing File", ("SWStyle_DesignCheckFile",), None,
  "Checks the active document against another model's settings.")
c("DesignCheckFolder", "Check Folder", ("SWStyle_DesignCheckFolder",), None, "Checks every model file in a folder.")
c("Check", "Check", ("SWStyle_Check",), "TOOLS_CHECK",
  "Checks the selected bodies, or every visible body, for invalid geometry.")
c("DraftAnalysis", "Draft Analysis", ("SWStyle_DraftAnalysis",), "I3DVIEW_DRAFT_ANALYSIS",
  "Colours faces by their draft against a direction of pull.", caption="Draft\nAnalysis")
c("UndercutAnalysis", "Undercut Analysis", ("SWStyle_UndercutAnalysis",), "I3DVIEW_UNDERCUT_ANALYSIS",
  "Colours the faces a two-part mould pulling along a direction could not release.")
c("ThicknessAnalysis", "Thickness Analysis", ("SWStyle_ThicknessAnalysis",), "I3DVIEW_THICKNESS_ANALYSIS",
  "Colours the faces by the wall thickness under them, against a target thickness.")
c("PartingLineAnalysis", "Parting Line Analysis", ("SWStyle_PartingLineAnalysis",), "MOLD_PARTING_LINE_ANALYSIS",
  "Shows where a two-part mould pulling along a direction would split the part.")
c("Zebra", "Zebra Stripes", ("SWStyle_ZebraStripes",), "I3DVIEW_ZEBRA",
  "Shows stripes reflected in the faces to check that faces join smoothly.")
c("Curvature", "Curvature", ("SWStyle_Curvature",), "I3DVIEW_CURVATURE",
  "Colours faces by how tightly they curve: black flat, red tight; the pointer shows the radius.")
c("SurfaceCurvatureCombs", "Surface Curvature Combs", ("SWStyle_SurfaceCurvatureCombs",), "I3DVIEW_CURVATURE",
  "Shows curvature combs across the picked faces.")
c("HideCurvatureCombs", "Hide Curvature Combs", ("SWStyle_HideCurvatureCombs",), "I3DVIEW_CURVATURE",
  "Takes all the surface curvature combs away.")
c("SymmetryCheck", "Symmetry Check", ("SWStyle_SymmetryCheck",), "TOOLS_SYM_CHECK",
  "Colours faces that are symmetric or asymmetric about a plane.")

# ---- Add-Ins tab (other FreeCAD workbenches) -------------------------------------------
c("WB_PartDesign", "Part Design", (), "FEATURES_EXTRUDE_BOSS", call="wb:PartDesignWorkbench", caption="Part\nDesign")
c("WB_Part", "Part", (), "PART", call="wb:PartWorkbench")
c("WB_Assembly", "Assembly", (), "ASSEMBLY_TAB", call="wb:AssemblyWorkbench")
c("WB_TechDraw", "Drawing", (), "DRAWINGS_SECTION_VIEW", call="wb:TechDrawWorkbench")
c("WB_FEM", "Simulation", (), "FLYOUT_SIMULATION", call="wb:FemWorkbench")
c("WB_CAM", "CAM", (), "FLYOUT_TOOLS", call="wb:CAMWorkbench")
c("WB_Spreadsheet", "Spreadsheet", (), "CONFIGURATION_TABLE", call="wb:SpreadsheetWorkbench")
c("WB_Draft", "2D Drafting", (), "FLYOUT_2D_TO_3D", call="wb:DraftWorkbench", caption="2D\nDrafting")
c("WB_Mesh", "Mesh", (), "FEATURES_SEGMENT_MESH", call="wb:MeshWorkbench")
c("WB_Surface", "Surfaces", (), "FLYOUT_SURFACES", call="wb:SurfaceWorkbench")
c("WB_SheetMetal", "Sheet Metal", (), "TREE_SHEET_METAL", call="wb:SMWorkbench", caption="Sheet\nMetal")

# ---- Sheet Metal tab (engine: the SheetMetal add-on; see smengine) -----------------------
c("SM_BaseFlange", "Base Flange/Tab", ("SWStyle_SMBaseFlange", "SheetMetal_AddBase"), "SM_BASE_FLANGE",
  "Makes the first sheet metal body from a sketch, or adds a tab to it.", caption="Base\nFlange/Tab")
c("SM_Convert", "Convert to Sheet Metal", ("SWStyle_SMConvert", "SheetMetal_FromSolid"), "SM_CONVERT_TO_SHEET_METAL",
  "Turns a solid into sheet metal from a fixed face and its bend edges.", caption="Convert to\nSheet Metal")
c("SM_LoftedBend", "Lofted-Bend", ("SWStyle_SMLoftedBend",), "SM_LOFTED_BEND", "Makes a sheet metal transition between two open profiles.")
c("SM_EdgeFlange", "Edge Flange", ("SWStyle_SMEdgeFlange", "SheetMetal_AddWall"), "SM_EDGE_FLANGE", "Adds a flange on one or more edges.")
c("SM_MiterFlange", "Miter Flange", ("SWStyle_SMMiterFlange", "SheetMetal_AddWall"), "SM_MITER_FLANGE",
  "Adds flanges along a chain of edges with mitered corners.")
c("SM_Hem", "Hem", ("SWStyle_SMHem", "SheetMetal_AddHem"), "SM_HEM", "Folds an edge back on itself.")
c("SM_SweptFlange", "Swept Flange", ("SWStyle_SMSweptFlange",), "SM_SWEPT_FLANGE", "Sweeps a flange profile along a path.")
c("SM_Jog", "Jog", ("SWStyle_SMJog",), "SM_JOG", "Adds two bends from one sketch line, offsetting the sheet.")
c("SM_SketchedBend", "Sketched Bend", ("SWStyle_SMSketchedBend", "SheetMetal_AddFoldWall"), "SM_SKETCHED_BEND", "Bends the sheet along a sketch line.")
c("SM_CrossBreak", "Cross-Break", ("SWStyle_SMCrossBreak",), "SM_CROSS_BREAK", "Adds crossed stiffening lines on a face.")
c("SM_Corners", "Corners", ("SWStyle_SMClosedCorner",), "SM_CORNERS",
  "Closed Corner, Welded Corner, Break-Corner and Corner Relief (the button itself is Closed Corner).")
c("SM_ClosedCorner", "Closed Corner", ("SWStyle_SMClosedCorner",), "SM_CLOSED_CORNER", "Extends flange faces to close the gap at a corner.")
c("SM_WeldedCorner", "Welded Corner", ("SWStyle_SMWeldedCorner",), "SM_WELDED_CORNER", "Adds a weld bead where flanges meet at a corner.")
c("SM_BreakCorner", "Break-Corner/Corner-Trim", ("SWStyle_SMBreakCorner",), "SM_BREAK_CORNER", "Chamfers or fillets sheet corners.")
c("SM_CornerTrim", "Corner Trim", ("SWStyle_SMCornerTrim",), "SM_CORNER_TRIM",
  "Adds reliefs and broken corners to the flat pattern (the part must be flattened).")
c("SM_BendNotch", "Bend Notch", ("SWStyle_SMBendNotch",), "SM_BEND_NOTCH",
  "Cuts notches in the flat pattern where the bend lines meet its edge, to line up bends.")
c("SM_CornerRelief", "Corner Relief", ("SWStyle_SMCornerRelief", "SheetMetal_AddCornerRelief"), "SM_CORNER_RELIEF",
  "Cuts a relief where two bends meet.")
c("SM_FormingTool", "Forming Tool", ("SWStyle_SMFormingTool", "SheetMetal_Forming"), "SM_FORMING_TOOL",
  "Presses a tool shape (louver, emboss, lance) into the sheet.", caption="Forming\nTool")
c("SM_BendTableNew", "Bend Table: New", ("SWStyle_SMBendTableNew",), "SM_BEND_TABLE_NEW",
  "Makes a new bend table (bend allowance, bend deduction or K-Factor by thickness, radius and angle).")
c("SM_BendTableFile", "Bend Table: From File", ("SWStyle_SMBendTableFile",), "SM_BEND_TABLE_FROM_FILE",
  "Adds a bend table from a file to the part.")
c("SM_Stamp", "Stamp", ("SWStyle_SMStamp",), "SM_STAMP", "Presses a sketched outline into the sheet to a depth.")
c("SM_TabAndSlot", "Tab and Slot", ("SWStyle_SMTabAndSlot",), "SM_TAB_AND_SLOT", "Adds matching tabs and slots between two bodies.")
c("SM_Vent", "Vent", ("SWStyle_SMVent",), "SM_VENT", "Cuts a vent from a sketch of ribs, spars and a boundary.")
c("SM_NormalCut", "Normal Cut", ("SWStyle_SMNormalCut", "SheetMetal_AddCutout"), "SM_NORMAL_CUT",
  "Cuts through the sheet square to its faces.", caption="Normal\nCut")
c("SM_Unfold", "Unfold", ("SWStyle_SMUnfold",), "SM_UNFOLD", "Flattens the bends you pick, to add cuts across them.")
c("SM_Fold", "Fold", ("SWStyle_SMFold",), "SM_FOLD", "Folds back bends that were unfolded.")
c("SM_Flatten", "Flatten", ("SWStyle_SMFlatten", "SheetMetal_Unfold"), "SM_FLATTEN", "Shows the part as its flat pattern.")
c("SM_NoBends", "No Bends", ("SWStyle_SMNoBends",), "SM_NO_BENDS", "Shows the part with its bends rolled back.")
c("SM_ExportDXF", "Export to DXF/DWG", ("SWStyle_SMExportDXF", "SheetMetal_UnfoldExport"), "SM_EXPORT_TO_DXF_DWG",
  "Saves the flat pattern as a DXF drawing (right-click Flat-Pattern).")
c("SM_InsertBends", "Insert Bends", ("SWStyle_SMInsertBends", "SheetMetal_AddBend"), "SM_INSERT_BENDS",
  "Turns a shelled part into sheet metal by adding bends at its sharp edges.")
c("SM_Rip", "Rip", ("SWStyle_SMRip", "SheetMetal_AddJunction"), "SM_RIP", "Cuts a gap along an edge so the part can unfold.")
c("SM_Gusset", "Sheet Metal Gusset", ("SWStyle_SMGusset",), "SM_GUSSET", "Presses a stiffening rib across a bend.")

c("SM_BaseShape", "Base Shape", ("SheetMetal_BaseShape",), None,
  "Makes a ready sheet metal shape (box, channel, angle, hat) from a few sizes.", caption="Base\nShape")
c("SM_NewSketch", "Sheet Metal Sketch", ("PartDesign_NewSketch", "Sketcher_NewSketch", "SheetMetal_NewSketch"), None,
  "Starts a sketch on the picked face or plane, as Sketch does.")     # look audit T2: never the add-on's sketch type box
c("SM_UnfoldUpdate", "Update Unfold", ("SheetMetal_UnfoldUpdate",), None,
  "Makes the unfolded pattern again after the part changed.")

# ---- Weldments tab (engine: the FrameForge add-on) ----------------------------------------
c("WE_Weldment", "Weldment", ("SWStyle_WEWeldment",), "WE_WELDMENT", "Makes the part a weldment, with a cut list of its members.")
c("WE_StructuralMember", "Structural Member", ("SWStyle_WEStructuralMember", "FrameForge_CreateProfiles"), "WE_STRUCTURAL_MEMBER",
  "Places a standard profile along sketch segments.", caption="Structural\nMember")
c("WE_StructureSystem", "Structure System", ("SWStyle_WEStructureSystem",), "WE_STRUCTURE_SYSTEM",
  "Enters or leaves the Structure System, where primary members are placed.")
c("WE_EditStructureSystem", "Edit Structure System", ("SWStyle_WEEditStructureSystem",), "WE_STRUCTURE_SYSTEM",
  "Enters an existing Structure System to add or change its members.")
c("WE_PrimaryMember", "Primary Member", ("SWStyle_WEPrimaryMember",), "WE_PRIMARY_MEMBER",
  "Places primary structural members in the Structure System.")
c("WE_SecondaryMember", "Secondary Member", ("SWStyle_WESecondaryMember",), "WE_SECONDARY_MEMBER",
  "Creates a secondary member between existing members.")
c("WE_DefineConnection", "Define Connection Element", ("SWStyle_WEDefineConnection",), "WE_DEFINE_CONNECTION_ELEMENT",
  "Makes this part a connection element: the references that place it and the features that cut the members.")
c("WE_InsertConnection", "Insert Connection Element", ("SWStyle_WEInsertConnection",), "WE_INSERT_CONNECTION_ELEMENT",
  "Places a connection element on the Structure System's members.")
c("WE_PatternConnection", "Pattern Connection Element", ("SWStyle_WEPatternConnection",), "WE_PATTERN_CONNECTION_ELEMENT",
  "Copies a connection element at a corner to the similar corners.")
c("WE_PiercePoint", "Pierce Point", ("SWStyle_WEPiercePoint",), "WE_PIERCE_POINT",
  "Predefines a profile's pierce points: the sketch points members can run through.")
c("WE_TrimExtend", "Trim/Extend", ("SWStyle_WETrimExtend", "FrameForge_TrimProfiles"), "WE_TRIM_EXTEND",
  "Trims or extends members against other members or faces.")
c("WE_EndCap", "End Cap", ("SWStyle_WEEndCap",), "WE_END_CAP", "Closes the open end of a member with a plate.")
c("WE_Gusset", "Gusset", ("SWStyle_WEGusset",), "WE_GUSSET", "Adds a plate between two faces of members.")
c("WE_WeldBead", "Weld Bead", ("SWStyle_WEWeldBead",), "WE_WELD_BEAD", "Adds a weld bead along a path, with its weld data.")
c("WE_CutList", "Weldment Cut List", ("SWStyle_WECutList", "FrameForge_CreateBOM"), "WE_WELDMENT_CUT_LIST", "Lists the members with their lengths.")

# ---- Heads-up view toolbar --------------------------------------------------------------
c("ZoomFit", "Zoom to Fit", ("SWStyle_ZoomFit", "Std_ViewFitAll"), "I3DVIEW_ZOOM_FIT", "Zooms the model to fit the window.", call="push_view")
c("ZoomArea", "Zoom to Area", ("SWStyle_ViewZoomArea", "Std_ViewBoxZoom"), "I3DVIEW_ZOOM_AREA", "Zooms to an area you select with a bounding box.", call="push_view")
c("ZoomSelection", "Zoom to Selection", ("SWStyle_ZoomToSelection", "Std_ViewFitSelection"), "I3DVIEW_ZOOM_SELECTION", call="push_view")
c("PreviousView", "Previous View", (), "I3DVIEW_PREV_VIEW", "Displays the previous view.", call="previous_view")
c("SectionView", "Section View", ("SWStyle_SectionView", "Std_ToggleClipPlane"), "I3DVIEW_SECT_VIEW",
  "Displays a cutaway of a part or assembly using planes or faces.")
# standard views go through namedviews (Update Standard Views keeps a turn); FreeCAD's own otherwise
c("ViewFront", "Front", ("SWStyle_StandardFront", "Std_ViewFront"), "VIEWORIENT_FRONT", call="push_view")
c("ViewBack", "Back", ("SWStyle_StandardBack", "Std_ViewRear"), "VIEWORIENT_BACK", call="push_view")
c("ViewLeft", "Left", ("SWStyle_StandardLeft", "Std_ViewLeft"), "VIEWORIENT_LEFT", call="push_view")
c("ViewRight", "Right", ("SWStyle_StandardRight", "Std_ViewRight"), "VIEWORIENT_RIGHT", call="push_view")
c("ViewTop", "Top", ("SWStyle_StandardTop", "Std_ViewTop"), "VIEWORIENT_TOP", call="push_view")
c("ViewBottom", "Bottom", ("SWStyle_StandardBottom", "Std_ViewBottom"), "VIEWORIENT_BOTTOM", call="push_view")
c("ViewIsometric", "Isometric", ("SWStyle_StandardIsometric", "Std_ViewIsometric"), "VIEWORIENT_ISOMETRIC", call="push_view")
c("ViewTrimetric", "Trimetric", ("SWStyle_StandardTrimetric", "Std_ViewTrimetric"), "VIEWORIENT_TRIMETRIC", call="push_view")
c("ViewDimetric", "Dimetric", ("SWStyle_StandardDimetric", "Std_ViewDimetric"), "VIEWORIENT_DIAMETRIC", call="push_view")

c("NormalTo", "Normal To", ("SWStyle_NormalTo", "Std_AlignToSelection", "Sketcher_ViewSketch"), "VIEWORIENT_NORMAL_TO", call="push_view")
c("YUpViewOrientation", "Y-Up", ("SWStyle_YUpViewOrientation",), None,
  "Standard views with the Y axis up.")
c("ZUpViewOrientation", "Z-Up", ("SWStyle_ZUpViewOrientation",), None,
  "Standard views with the Z axis up: Front looks at the Top Plane.")
c("SingleView", "Single View", (), "VIEWPORT_SINGLE", "One view of the model in the window.", call="viewport:single")
c("TwoViewHorizontal", "Two View - Horizontal", (), "VIEWPORT_TWO_H", "Two views, one above the other.", call="viewport:two-h")
c("TwoViewVertical", "Two View - Vertical", (), "VIEWPORT_TWO_V", "Two views side by side.", call="viewport:two-v")
c("FourView", "Four View", (), "VIEWPORT_FOUR", "Four views: Front, Top, Right and Isometric.", call="viewport:four")
c("LinkViews", "Link Views", (), "VIEWPORT_LINK", "Turning, zooming or moving one view does the same in the others.",
  call="link_views")
c("NewView", "New View", ("SWStyle_NewView",), "VIEWORIENT_NEW_VIEW", "Saves the current view under a name.")
c("UpdateStandardViews", "Update Standard Views", ("SWStyle_UpdateStandardViews",), "VIEWORIENT_UPDATE_STD",
  "Makes the current view the chosen standard view.")
c("ResetStandardViews", "Reset Standard Views", ("SWStyle_ResetStandardViews",), "VIEWORIENT_RESET_STD",
  "Puts back the default standard views.")
c("ViewOrientation", "View Orientation", (), "I3DVIEW_CHANGE_VIEW_ORIENT",
  "The standard views; Space opens the Orientation box with the View Selector.", call="menu")
c("ViewSelector", "View Selector", (), "VIEW_SELECTOR",
  "A box around the model in the 3D view: click a face, edge or corner to look from there (Space).",
  call="view_selector")
# FreeCAD 1.1 has one Std_DrawStyle command with a list of styles (0 As is, 1 Points, 2 Wireframe,

# Hidden Lines Visible (hidden edges dashed) has no FreeCAD style: hlv.py draws it over Hidden line.
c("ShadedEdges", "Shaded With Edges", (), "I3DVIEW_SHADED_EDGES",
  "Shaded faces with their edges drawn (FreeCAD's Flat lines).", call="draw_style:6")
c("Shaded", "Shaded", (), "I3DVIEW_SHADED", "Shaded faces without edges.", call="draw_style:5")
c("HiddenLinesRemoved", "Hidden Lines Removed", ("SWStyle_HiddenLinesRemoved",), "I3DVIEW_HLR",
  "White faces and black edges, with the hidden ones left out.")
c("HiddenLinesVisible", "Hidden Lines Visible", ("SWStyle_HiddenLinesVisible",), "I3DVIEW_HLV",
  "Edges only: visible edges solid, hidden edges grey and dashed.")
c("Wireframe", "Wireframe", (), "I3DVIEW_WIREFRAME", "Every edge, the hidden ones too.", call="draw_style:2")
c("Cartoon", "Cartoon", ("SWStyle_Cartoon",), None,
  "Draws the model in flat bands of colour with thick black outlines.")
c("DraftQualityHLR", "Draft Quality HLR/HLV", ("SWStyle_DraftQualityHLR",), None,
  "Hidden Lines Visible draws its hidden edges from coarser curves: quicker, rougher.")
# the drawing sheet's heads-up bar (HEADS_UP_SHEET below; drawings-land50 display commands)
c("DrawZoomFit", "Zoom to Fit", ("FreeWorks_DrawZoomFit", "Std_ViewFitAll"), "I3DVIEW_ZOOM_FIT", "Zooms the sheet to fit the window.")
c("DrawZoomArea", "Zoom to Area", ("FreeWorks_DrawZoomArea",), "I3DVIEW_ZOOM_AREA", "Zooms to an area of the sheet you select with a box.")
c("DrawPreviousView", "Previous View", ("FreeWorks_DrawPreviousView",), "I3DVIEW_PREV_VIEW", "Displays the previous zoom of the sheet.")
c("Draw3DDrawingView", "3D Drawing View", ("FreeWorks_Draw3DDrawingView",), None, "Turns a drawing view in 3D to pick hidden edges.")
c("DrawDisplayStyle", "Display Style", ("FreeWorks_DrawDisplayShadedEdges",), "I3DVIEW_DISPLAY_STYLE",
  "How the picked views (or every view) are drawn: shaded with edges, shaded, hidden lines removed or visible, or wireframe.")
c("DrawDisplayShadedEdges", "Shaded With Edges", ("FreeWorks_DrawDisplayShadedEdges",), "I3DVIEW_SHADED_EDGES", "A shaded picture of the model under the view's edges.")
c("DrawDisplayShaded", "Shaded", ("FreeWorks_DrawDisplayShaded",), "I3DVIEW_SHADED", "A shaded picture of the model, no edges.")
c("DrawDisplayHiddenRemoved", "Hidden Lines Removed", ("FreeWorks_DrawDisplayHiddenRemoved",), "I3DVIEW_HLR", "Visible edges only.")
c("DrawDisplayHiddenVisible", "Hidden Lines Visible", ("FreeWorks_DrawDisplayHiddenVisible",), "I3DVIEW_HLV", "Visible edges solid, hidden edges dashed.")
c("DrawDisplayWireframe", "Wireframe", ("FreeWorks_DrawDisplayWireframe",), "I3DVIEW_WIREFRAME", "Every edge, the hidden ones too.")
c("DisplayStyle", "Display Style", (), "I3DVIEW_DISPLAY_STYLE",
  "How the model is drawn: shaded with edges, shaded, hidden lines removed or visible, or wireframe.", call="draw_style:6")

# list. FreeCAD's Toggle Visibility (greyed without a pick) is the list's first entry.
c("HideShowItems", "Hide/Show Items", (), "I3DVIEW_HIDE_SHOW_ITEMS",
  "Changes the visibility of items in the graphics area.", call="menu")
c("ToggleVisibility", "Toggle Visibility", ("Std_ToggleVisibility",), "I3DVIEW_HIDE_SHOW_ITEMS",
  "Hides the picked items that show and shows the picked hidden ones.")
c("ShowSelection", "Show", ("Std_ShowSelection",), "I3DVIEW_HIDE_SHOW_ITEMS")
c("HideSelection", "Hide", ("Std_HideSelection",), "I3DVIEW_HIDE_SHOW_ITEMS")
c("ShowAll", "Show All", ("Std_ShowObjects",), "I3DVIEW_HIDE_SHOW_ITEMS")
c("ViewPlanes", "View Planes", ("SWStyle_ViewPlanes",), "I3DVIEW_PLANES", "Shows or hides all planes.")
c("ToggleAxisCross", "View Axes", ("SWStyle_ViewAxes", "Std_AxisCross"), "I3DVIEW_AXES", "Shows or hides all axes.")
c("ViewOrigins", "View Origins", ("SWStyle_ViewOrigins",), "I3DVIEW_ORIGINS", "Shows or hides the origins.")
c("ViewCoordinateSystems", "View Coordinate Systems", ("SWStyle_ViewCoordinateSystems",), "VIEW_COORDINATE_SYSTEMS",
  "Shows or hides all coordinate systems.")
c("ViewPoints", "View Points", ("SWStyle_ViewPoints",), "VIEW_POINTS", "Shows or hides all reference points.")
c("ViewSketches", "View Sketches", ("SWStyle_ViewSketches",), "I3DVIEW_SKETCHES",
  "Shows or hides all sketches, also those used by features.")
c("ViewCurves", "View Curves", ("SWStyle_ViewCurves",), "VIEW_CURVES", "Shows or hides curves.")
c("ViewBodies", "Bodies", ("SWStyle_ViewBodies",), "VIEW_BODIES", "Shows or hides all solid and surface bodies.")
c("ViewAllAnnotations", "All Annotations", ("SWStyle_ViewAllAnnotations",), "VIEW_ALL_ANNOTATIONS",
  "Shows or hides all annotations in the graphics area.")
c("ViewGrid", "Grid", ("SWStyle_ViewGrid",), "VIEW_GRID", "Shows or hides the sketch grid.")
c("ViewDimensionNames", "Dimension Names", ("SWStyle_ViewDimensionNames",), "VIEW_DIMENSION_NAMES",
  "Shows the names of named sketch dimensions.")
c("ViewSketchPlanes", "Sketch Planes", ("SWStyle_ViewSketchPlanes",), "VIEW_SKETCH_PLANES", "Shows or hides the plane of every sketch.")
c("ViewCameras", "Cameras", ("SWStyle_ViewCameras",), "VIEW_CAMERAS", "Shows or hides the cameras.")
c("ViewLights", "Lights", ("SWStyle_ViewLights",), "VIEW_LIGHTS", "Turns the added lights on and off.")
c("ViewPartingLines", "Parting Lines", ("SWStyle_ViewPartingLines",), "VIEW_PARTING_LINES", "Shows or hides the parting lines.")
c("ViewMarkups", "Markups", ("SWStyle_ViewMarkups",), "VIEW_MARKUPS", "Shows or hides the markups.")
c("ViewBendLines", "Bend Lines", ("SWStyle_ViewBendLines",), "VIEW_BEND_LINES", "Shows or hides the sheet metal bend lines.")
c("ViewWeldBead", "Weld Bead", ("SWStyle_ViewWeldBead",), "VIEW_WELD_BEAD", "Shows or hides the weld beads.")
c("TangentEdgesVisible", "Tangent Edges Visible", ("SWStyle_TangentEdgesVisible",), None,
  "Draws tangent edges like other edges.")
c("TangentEdgesPhantom", "Tangent Edges as Phantom", ("SWStyle_TangentEdgesPhantom",), None,
  "Draws tangent edges as phantom lines.")
c("TangentEdgesRemoved", "Tangent Edges Removed", ("SWStyle_TangentEdgesRemoved",), None, "Leaves tangent edges out.")
c("RotateAboutSceneFloor", "Rotate About Scene Floor", ("SWStyle_RotateAboutSceneFloor",), None,
  "Rotates the view about the vertical axis of the screen.")
c("TurnCamera", "Turn Camera", ("SWStyle_TurnCamera",), None,
  "Turns the camera where it stands: drag to look round; Esc ends.")
c("Isolate", "Isolate", ("SWStyle_Isolate",), None, "Shows only the selected bodies until Exit Isolate.")
c("HideAllTypes", "Hide All Types", ("SWStyle_HideAllTypes",), None,
  "Hides planes, axes, origins, coordinate systems, points, sketches, curves and annotations; press again to show them.")
c("EditAppearance", "Edit Appearance", ("SWStyle_Appearance", "Std_SetAppearance", "Std_SetMaterial", "Std_RandomColor"),
  "I3DVIEW_EDIT_APPEAR", "Edits the color and appearance of the selected entity.")
c("CopyAppearance", "Copy Appearance", ("SWStyle_CopyAppearance",), "STANDARD_COPY",
  "Copies the appearance of the picked face, feature or body.")
c("PasteAppearance", "Paste Appearance", ("SWStyle_PasteAppearance",), "STANDARD_PASTE",
  "Pastes the copied appearance onto the picked faces, features or bodies.")
c("Transparency", "Change Transparency", ("SWStyle_ChangeTransparency", "Std_ToggleTransparency"), "RENDERING_EDIT_APPEARANCE")
c("ApplyScene", "Apply Scene", (), "I3DVIEW_APPLY_SCENE", "Applies a background scene.", call="scene_menu")
c("DynamicAnnotationViews", "Dynamic Annotation Views", ("SWStyle_MBDDynamicViews",), None,
  "Annotations show only in the view they were made in.")
c("ViewSettings", "View Settings", (), "I3DVIEW_SETTINGS",
  "Shadows In Shaded Mode, Perspective and Cartoon.", call="menu")
c("RealViewGraphics", "RealView Graphics", ("SWStyle_RealViewGraphics",), "I3DVIEW_REAL_VIEW_GRAPHICS",
  "Lights the model from the side and behind as well, for a fuller shaded look.")
c("AmbientOcclusion", "Ambient Occlusion", ("SWStyle_AmbientOcclusion",), "I3DVIEW_SETTINGS",
  "Darkens the corners and hollows of the model.")
c("ShadowsInShadedMode", "Shadows In Shaded Mode", ("SWStyle_ShadowsInShadedMode",), "I3DVIEW_SHADOWS_IN_SHADED",
  "Drops a shadow of the model on the floor while it is shaded.")
c("Perspective", "Perspective", ("SWStyle_PerspectiveToggle", "Std_PerspectiveCamera"), "I3DVIEW_PERSPECTIVE")
c("AddCamera", "Add Camera", ("SWStyle_AddCamera",), "VIEW_CAMERAS",
  "Adds a camera standing where the view's eye is, looking where it looks.")
c("CameraView", "Camera View", ("SWStyle_CameraView",), "I3DVIEW_CAMERA_VIEW",
  "Looks through the picked camera; again goes back to the view as it was.")
c("ModelBreakView", "Model Break View", ("SWStyle_ModelBreakView",), None,
  "Shows a long part shortened, with stretches taken out; the part itself is unchanged.")
c("ToggleModelBreak", "Toggle Model Break View", ("SWStyle_ToggleModelBreak",), None,
  "Shows the part whole, or broken again.")
c("ChangeDisplayStates", "Change Display States", ("SWStyle_ChangeDisplayStates",), None,
  "Lists the part's display states: activate, add, rename or delete one.")
c("AddDisplayState", "Add Display State", ("SWStyle_AddDisplayState",), None,
  "Keeps the look as it is now as a new display state and makes it active.")
c("AddWalkThrough", "Add Walk-through", ("SWStyle_AddWalkThrough",), None,
  "Walks the camera through the model with the arrow keys, and records the walk.")
c("PlayWalkThrough", "Play Walk-through", ("SWStyle_PlayWalkThrough",), None,
  "Plays the picked walk-through (or the only one).")
c("Orthographic", "Orthographic", ("Std_OrthographicCamera",), "VIEWORIENT_FRONT")

# ---- Context toolbar (contextbar.py) ---------------------------------------------------
# Edit Feature and its Edit Sketch act on the feature that made the picked face or edge.
c("EditFeature", "Edit Feature", (), None,
  "Edits the feature that made the selected face, edge or vertex.", call="edit_feature")
c("EditFeatureSketch", "Edit Sketch", (), "SKETCH_MODIFY",
  "Edits the sketch of the selected feature.", call="edit_feature_sketch")
# Rollback puts the rollback bar just above the picked feature (rollbackbar.py). FreeCAD's Set Tip
# gives the icon only: it would put the bar under the feature.
c("Rollback", "Rollback", ("PartDesign_MoveTip",), "STANDARD_UNDO",
  "Rolls the part back to just before the selected feature; with nothing selected, one feature back.", call="rollback")

c("PM_OK", "OK", (), "CHECK_MARK", "Accepts the open PropertyManager (its green check).", call="pm_ok")
c("PM_Cancel", "Cancel", (), "STANDARD_CANCEL", "Closes the open PropertyManager without applying it.", call="pm_cancel")
c("ShortcutBar", "Shortcut Bar", ("SWStyle_ShortcutBar",), None, "The shortcut bar at the pointer (the S key).")
c("Pan", "Pan", ("SWStyle_ViewPan",), "I3DVIEW_PAN", "Drag to move the view.")


# own constraint icons show the relation itself.
c("RelHorizontal", "Make Horizontal", ("Sketcher_ConstrainHorizontal",), tip="Adds a horizontal relation to the selection(s).")
c("RelVertical", "Make Vertical", ("Sketcher_ConstrainVertical",), tip="Adds a vertical relation to the selection(s).")
c("RelMerge", "Merge Points", ("Sketcher_ConstrainCoincidentUnified", "Sketcher_ConstrainCoincident"), tip="Adds a merge relation to the selection(s).")
c("RelOnEdge", "Make Coincident", ("Sketcher_ConstrainCoincidentUnified", "Sketcher_ConstrainPointOnObject"), tip="Adds a coincident relation to the selection(s).")
c("RelMidpoint", "Make Midpoint", ("Sketcher_ConstrainSymmetric",), tip="Adds a midpoint relation to the selection(s).")
c("RelCollinear", "Make Collinear", ("Sketcher_ConstrainTangent",), tip="Adds a collinear relation to the selection(s).")
c("RelParallel", "Make Parallel", ("Sketcher_ConstrainParallel",), tip="Adds a parallel relation to the selection(s).")
c("RelPerpendicular", "Make Perpendicular", ("Sketcher_ConstrainPerpendicular",), tip="Adds a perpendicular relation to the selection(s).")
c("RelTangent", "Make Tangent", ("Sketcher_ConstrainTangent",), tip="Adds a tangent relation to the selection(s).")
c("RelConcentric", "Make Concentric", ("Sketcher_ConstrainCoincidentUnified", "Sketcher_ConstrainCoincident"), tip="Adds a concentric relation to the selection(s).")
c("RelEqual", "Make Equal", ("Sketcher_ConstrainEqual",), tip="Adds an equal relation to the selection(s).")
c("RelSymmetric", "Make Symmetric", ("Sketcher_ConstrainSymmetric",), tip="Adds a symmetric relation to the selection(s).")
c("RelFix", "Fix", ("Sketcher_ConstrainBlock",))
c("RelFixPoint", "Fix", ("Sketcher_ConstrainLock",))
c("RelConstruction", "Construction Geometry", ("Sketcher_ToggleConstruction",), "SKETCH_CONSTRUCT_GEOM")

# drawings-land85: drawing twins of the dimension tools
for _key, _native in (('HorizontalDimension', 'FreeWorks_DrawHorizontalDimension'), ('VerticalDimension', 'FreeWorks_DrawVerticalDimension'), ('AngularDimension', 'FreeWorks_DrawAngularDimension'), ('RadiusDimension', 'FreeWorks_DrawRadiusDimension'), ('ChainDimension', 'FreeWorks_DrawChainDimension'), ('AngularRunningDimension', 'FreeWorks_DrawAngularRunning'), ('PathLengthDimension', 'TechDraw_ExtensionArcLengthAnnotation'), ('SymmetricLinearDiameterDimension', 'FreeWorks_DrawSymmetricDiameter')):
    _base = next((x for x in _ALL if x.key == _key), None)
    if _base is not None and not any(x.key == "Draw" + _key for x in _ALL):
        c("Draw" + _key, _base.label, (_native,) + tuple(_base.natives), _base.icon, _base.tip, caption=_base.caption)


BY_KEY = {cmd.key: cmd for cmd in _ALL}
ALL = tuple(_ALL)

# ---- Layouts -------------------------------------------------------------------------
# ("large", key, flyout_keys)          tall icon over caption, ▾ under it when it has a flyout
# ("stack", ((key, flyout_keys), ...)) up to three icon + text rows
# ("grid", (((key, flyout), ...), ...)) rows of small icon-only buttons with ▾
# ("sep",)                              thin vertical separator
FEATURES = (
    ("large", "BossExtrude", None),
    ("large", "BossRevolve", None),
    ("stack", (("BossSweep", None), ("BossLoft", None), ("BossBoundary", None))),
    ("sep",),
    ("large", "CutExtrude", None),

    # left them live in the Insert menu (swmenus) or in their PropertyManager, nothing lost
    ("large", "Hole", ("Hole", "AdvancedHole", "Thread", "StudWizard")),
    ("large", "CutRevolve", None),
    ("stack", (("CutSweep", None), ("CutLoft", None), ("CutBoundary", None))),
    ("sep",),
    ("large", "Fillet", ("Fillet", "Chamfer")),      # Variable/Face/Full Round: the Fillet PM's Fillet Type buttons
    ("large", "LinearPattern", ("LinearPattern", "CircularPattern", "Mirror", "CurveDrivenPattern", "SketchDrivenPattern",
                                "TableDrivenPattern", "FillPattern", "VariablePattern")),
    ("stack", (("Rib", None), ("Draft", None), ("Shell", None))),
    ("stack", (("Wrap", None), ("Intersect", None), ("Mirror", None))),
    ("sep",),
    ("large", "ReferenceGeometry", ("Plane", "Axis", "CoordinateSystem", "Point", "CenterOfMass", "BoundingBox",
                                    "MateReference")),

    ("large", "Curves", ("SplitLine", "ProjectedCurve", "CompositeCurve", "CurveThroughXYZPoints",
                         "CurveThroughReferencePoints", "HelixSpiral")),
    ("sep",),
    ("large", "Instant3D", None),
)

SKETCH = (
    ("large", "Sketch", ("Sketch", "Sketch3D", "Sketch3DOnPlane")),
    ("large", "SmartDimension", ("SmartDimension", "HorizontalDimension", "VerticalDimension",
                                 "BaselineDimension", "ChainDimension", "SymmetricLinearDiameterDimension",
                                 "OrdinateDimension", "HorizontalOrdinateDimension", "VerticalOrdinateDimension",
                                 "PathLengthDimension")),
    ("sep",),
    ("grid", (
        (("Line", ("Line", "Centerline", "MidpointLine")), ("Circle", ("Circle", "PerimeterCircle")),
         ("Spline", ("Spline", "StyleSpline", "EquationDrivenCurve")), ("Sketch3DPlane", None)),
        (("CornerRectangle", ("CornerRectangle", "CenterRectangle", "ThreePointCornerRectangle",
                                "ThreePointCenterRectangle", "Parallelogram")),
         ("CenterArc", ("CenterArc", "TangentArc", "ThreePointArc")),
         ("Ellipse", ("Ellipse", "PartialEllipse", "Parabola", "Conic")), ("Text", None)),
        (("Slot", ("Slot", "CenterpointSlot", "ThreePointArcSlot", "ArcSlot")), ("Polygon", None),
         ("SketchFillet", ("SketchFillet", "SketchChamfer")), ("SketchPoint", None)),
    )),
    ("sep",),
    ("large", "Trim", ("Trim", "Extend")),
    ("large", "Convert", ("Convert", "SilhouetteEntities", "IntersectionCurve")),
    ("large", "Offset", None),
    ("large", "OffsetOnSurface", None),
    ("stack", (("MirrorEntities", None),
               ("LinearSketchPattern", ("LinearSketchPattern", "CircularSketchPattern")),
               ("MoveEntities", ("MoveEntities", "CopyEntities", "RotateEntities", "ScaleEntities", "StretchEntities")))),
    ("sep",),
    ("large", "Relations", ("Relations", "AddRelation")),
    ("large", "RepairSketch", None),
    ("sep",),

    ("large", "QuickSnaps", ("QuickSnaps", "QSPoint", "QSCenterPoint", "QSMidpoint", "QSQuadrant",
                             "QSIntersection", "QSNearest", "QSTangent", "QSHVPoint", "QSGrid")),
    ("sep",),
    ("large", "RapidSketch", None),
    ("large", "Instant2D", None),
    ("large", "ShadedSketchContours", None),
)

SURFACES = (
                            # flyouts: Mid-Surface under Offset, Radiate under Ruled, Blend Curve under Curves
    ("large", "ExtrudedSurface", None),
    ("large", "RevolvedSurface", None),
    ("large", "SweptSurface", None),
    ("large", "LoftedSurface", None),
    ("large", "BoundarySurface", None),
    ("large", "FilledSurface", None),
    ("large", "Freeform", None),
    ("sep",),
    ("stack", (("PlanarSurface", None), ("OffsetSurface", None), ("RuledSurface", None))),    # cmflyout-1120
    ("large", "SurfaceFlatten", None),
    ("large", "SurfaceFillet", ("SurfaceFillet", "Chamfer")),
    ("sep",),
    ("stack", (("DeleteFace", None), ("ReplaceFace", None), ("DeleteHole", None))),
    ("sep",),
    ("stack", (("ExtendSurface", None), ("TrimSurface", None), ("UntrimSurface", None))),
    ("large", "KnitSurface", None),
    ("sep",),
    ("stack", (("Thicken", None), ("ThickenedCut", None), ("CutWithSurface", None))),
    ("sep",),
    ("large", "ReferenceGeometry", ("Plane", "Axis", "CoordinateSystem", "Point", "CenterOfMass", "BoundingBox",
                                    "MateReference")),
    ("large", "Curves", ("SplitLine", "ProjectedCurve", "CompositeCurve", "CurveThroughXYZPoints",
                         "CurveThroughReferencePoints", "HelixSpiral")),
)

EVALUATE = (
                            # (commands/swreg/cm-options.txt Tab13, shots/18b): the Xpress wizards follow (cmtabs)
    ("large", "DesignStudy", ("DesignStudy", "DesignStudyParameters")),   # dsparams-1121: Design Study flyout: Design Study, Parameters
    ("sep",),
    ("large", "Interference", None),
    ("large", "MassProperties", None),
    ("stack", (("Measure", None), ("Markup", None), ("Sensor", None))),
    ("stack", (("SectionProperties", None), ("ImportDiagnostics", None), ("PerformanceEvaluation", None))),
    ("stack", (("GeometryAnalysis", None), ("BodyCompare", None), ("Check", None))),
    ("sep",),
    ("large", "DraftAnalysis", None),
    ("stack", (("Zebra", None), ("Curvature", None),        # cmflyout-1120: combs are in View > Display
               ("SymmetryCheck", None))),
    ("stack", (("UndercutAnalysis", None), ("PartingLineAnalysis", None), ("ThicknessAnalysis", None))),
    ("grid", ((("CompareDocuments", None),),
              (("CheckActiveDocument", ("CheckActiveDocument", "DesignCheckFile", "DesignCheckBuild",
                                        "DesignCheckLearn")),),
              (("DeviationAnalysis", None),))),
)

ADDINS = (
    ("large", "WB_PartDesign", None),
    ("large", "WB_Part", None),
    ("large", "WB_Assembly", None),
    ("large", "WB_TechDraw", None),
    ("large", "WB_FEM", None),
    ("large", "WB_CAM", None),
    ("sep",),
    ("large", "WB_Spreadsheet", None),
    ("large", "WB_Draft", None),
    ("large", "WB_Surface", None),
    ("large", "WB_Mesh", None),
    ("large", "WB_SheetMetal", None),
)

SHEET_METAL = (

    ("large", "SM_BaseFlange", None),
    ("large", "SM_Convert", None),
    ("large", "SM_LoftedBend", None),
    ("sep",),
    ("stack", (("SM_EdgeFlange", None), ("SM_MiterFlange", None), ("SM_Hem", None))),
    ("stack", (("SM_Jog", None), ("SM_SketchedBend", None), ("SM_CrossBreak", None))),
    ("large", "SM_SweptFlange", None),
    ("sep",),
    ("large", "SM_Corners", ("SM_ClosedCorner", "SM_WeldedCorner", "SM_BreakCorner", "SM_CornerRelief")),
    ("sep",),
    ("stack", (("SM_FormingTool", None), ("SM_Gusset", None), ("SM_TabAndSlot", None))),
    ("large", "SM_Stamp", None),
    ("sep",),
    ("stack", (("CutExtrude", None), ("SimpleHole", None), ("SM_Vent", None))),
    ("stack", (("SM_NormalCut", None), ("SM_BendNotch", None))),
    ("sep",),
    ("stack", (("SM_Unfold", None), ("SM_Fold", None), ("SM_Flatten", None))),
    ("large", "SM_NoBends", None),
    ("sep",),
    ("large", "SM_Rip", None),
    ("large", "SM_InsertBends", None),
    ("sep",),
    ("stack", (("SM_BaseShape", None), ("SM_NewSketch", None), ("SM_UnfoldUpdate", None))),
)

STRUCTURE_SYSTEM = (

    ("large", "WE_StructureSystem", None),
    ("large", "WE_PrimaryMember", None),
    ("large", "WE_SecondaryMember", None),
    ("sep",),
    ("large", "WE_DefineConnection", None),
    ("large", "WE_InsertConnection", None),
    ("large", "WE_PatternConnection", None),
    ("sep",),
    ("large", "WE_PiercePoint", None),
)

WELDMENTS = (

    ("large", "Sketch3D", None),
    ("large", "WE_Weldment", None),
    ("sep",),
    ("large", "WE_StructuralMember", None),
    ("large", "WE_TrimExtend", None),
    ("large", "BossExtrude", None),
    ("sep",),
    ("stack", (("WE_EndCap", None), ("WE_Gusset", None), ("WE_WeldBead", None))),
    ("sep",),
    ("stack", (("CutExtrude", None), ("Hole", None), ("Chamfer", None))),
    ("sep",),
    ("large", "ReferenceGeometry", ("Plane", "Axis", "CoordinateSystem", "Point", "CenterOfMass", "BoundingBox",
                                    "ShapeBinder")),
)

SKETCH_INK = (
    ("large", "Sketch", ("Sketch", "Sketch3D", "EditSketch")),
    ("sep",),
    ("large", "InkColor", ("InkColor", "InkColorBlack", "InkColorBlue", "InkColorRed", "InkColorGreen",
                           "InkColorOrange", "InkColorPurple")),
    ("sep",),
    ("large", "PenDraw", None),
    ("large", "PenEraser", None),
    ("large", "PenSelect", None),
    ("large", "PenPowerModify", None),
    ("sep",),
    ("large", "PenRuler", ("PenRuler", "PenProtractor")),
    ("large", "PenTouch", None),
    ("large", "PenAutoShape", None),
    ("large", "PenAutoSketchEntities", None),
    ("large", "PenAutoSpline", None),
    ("sep",),
    ("large", "Instant2D", None),
    ("large", "ShadedSketchContours", None),
    ("large", "NormalTo", None),
)

DRAWING = (
    ("large", "DrawModelView", None),
    ("sep",),
    ("large", "DrawProjectedView", None),
    ("large", "DrawAuxiliaryView", None),
    ("large", "DrawSectionView", None),
    ("large", "DrawRemovedSection", None),
    ("large", "DrawDetailView", None),
    ("large", "DrawRelativeView", None),
    ("large", "DrawStandard3View", None),
    ("sep",),
    ("large", "DrawBrokenOut", None),
    ("large", "DrawBreak", None),
    ("large", "DrawCrop", None),
    ("large", "DrawAlternatePosition", None),
    ("sep",),
    ("large", "DrawEmptyView", None),
    ("large", "DrawPredefinedView", None),
    ("sep",),
    ("large", "DrawUpdateView", None),
    ("large", "DrawReplaceModel", None),
)
VIEW_LAYOUT = DRAWING               # the tab's name up to land218; older checks read this


ANNOTATION = (
    ("large", "SmartDimension", ("SmartDimension", "DrawHorizontalDimension", "DrawVerticalDimension",
                                 "DrawAngularDimension", "DrawRadiusDimension", "DrawBaselineDimension", "DrawChainDimension",
                                 "DrawOrdinateDimension", "DrawHorizontalOrdinate", "DrawVerticalOrdinate",
                                 "DrawAngularRunningDimension", "DrawChamferDimension", "DrawPathLengthDimension",
                                 "DrawSymmetricLinearDiameterDimension", "DrawAutodimension")),   # drawings-land45 dimension tools
    ("sep",),
    ("large", "DrawModelItems", None),
    ("sep",),
    ("large", "DrawSpellChecker", None),
    ("sep",),
    ("large", "DrawFormatPainter", None),
    ("sep",),
    ("large", "DrawNote", None),
    ("large", "DrawLinearNotePattern", ("DrawLinearNotePattern", "DrawCircularNotePattern")),
    ("stack", (("DrawBalloon", ("DrawBalloon", "DrawStackedBalloon")), ("DrawAutoBalloon", None), ("DrawMagneticLine", None))),
    ("stack", (("DrawSurfaceFinish", None), ("DrawWeldSymbol", ("DrawWeldSymbol", "DrawCaterpillar", "DrawEndTreatment")),
               ("DrawHoleCallout", None))),
    ("stack", (("DrawGeometricTolerance", None), ("DrawDatumFeature", None), ("DrawDatumTarget", None))),
    ("sep",),
    ("large", "DrawMakeBlock", ("DrawMakeBlock", "DrawEditBlock", "DrawInsertBlock", "DrawSaveBlock", "DrawExplodeBlock")),   # Blocks flyout
    ("sep",),
    ("stack", (("DrawCenterMark", None), ("DrawCenterline", None), ("DrawAreaHatch", None))),
    ("stack", (("DrawRevisionSymbol", None), ("DrawRevisionCloud", None))),
    ("sep",),
    ("large", "DrawGeneralTable", ("DrawGeneralTable", "DrawHoleTable", "DrawBOM", "DrawRevisionTable", "DrawWeldTable", "DrawBendTable", "DrawPunchTable", "DrawTitleBlockTable")),
)


SHEET_FORMAT = (
    ("large", "DrawEditSheetFormat", ("DrawEditSheetFormat", "DrawEditSheet")),
    ("large", "DrawTitleBlockFields", None),
    ("large", "DrawAutomaticBorder", None),
)


DRAW_MARKUP = (
    ("large", "DrawMarkupToggle", None),
    ("large", "DrawMarkupColor", None),
    ("sep",),
    ("large", "DrawMarkupDraw", None),
    ("large", "DrawMarkupEraser", None),
    ("large", "DrawMarkupSelect", None),
    ("sep",),
    ("large", "DrawMarkupTouch", None),
    ("large", "DrawMarkupNote", None),
    ("sep",),
    ("large", "DrawZoomToMarkup", None),
    ("large", "DrawMarkupOptions", None),
)


DRAW_SKETCH = (
    ("large", "SmartDimension", None),
    ("sep",),
    ("grid", (
        (("DrawSketchLine", ("DrawSketchLine", "DrawSketchCenterline", "DrawSketchMidpointLine")),
         ("DrawSketchCircle", ("DrawSketchCircle", "DrawSketchPerimeterCircle")),
         ("DrawSketchSpline", None), ("DrawSketchPoint", None)),
        (("DrawSketchRectangle", ("DrawSketchRectangle", "DrawSketchCenterRectangle")),
         ("DrawSketchArc", ("DrawSketchArc", "DrawSketchThreePointArc")),
         ("DrawSketchEllipse", None)),
        (("DrawSketchSlot", None), ("DrawSketchPolygon", None),
         ("DrawSketchFillet", ("DrawSketchFillet", "DrawSketchChamfer"))),
    )),
    ("sep",),
    ("large", "DrawTrimEntities", None),
    ("large", "DrawConvertEntities", None),
    ("large", "DrawOffsetEntities", None),
    ("sep",),
    ("stack", (("DrawMirrorEntities", None),
               ("DrawLinearSketchPattern", ("DrawLinearSketchPattern", "DrawCircularSketchPattern")),
               ("DrawMoveEntities", ("DrawMoveEntities", "DrawCopyEntities", "DrawRotateEntities", "DrawScaleEntities")))),
    ("sep",),
    ("large", "DrawDisplayDeleteRelations", ("DrawDisplayDeleteRelations", "DrawAddRelation")),
    ("sep",),
    ("large", "DrawQuickSnaps", None),
)


def drawing_tabs(part_tabs):
    ""


    by_title = dict(part_tabs)
    tabs = [("Drawing", DRAWING), ("Annotation", ANNOTATION), ("Sketch", DRAW_SKETCH), ("Markup", DRAW_MARKUP)]
    for title in ("Evaluate", "Add-Ins"):
        if title in by_title:
            tabs.append((title, by_title[title]))
    tabs.append(("Sheet Format", SHEET_FORMAT))
    return tuple(tabs)


TABS = (("Features", FEATURES), ("Sketch", SKETCH), ("Sketch Ink", SKETCH_INK), ("Surfaces", SURFACES), ("Sheet Metal", SHEET_METAL),
        ("Structure System", STRUCTURE_SYSTEM), ("Weldments", WELDMENTS), ("Evaluate", EVALUATE), ("Add-Ins", ADDINS))

# Quick access row, left to right: (key, flyout_keys)
QUICK_ACCESS = (
    ("Home", None),
    ("New", ("New", "MakeDrawing", "MakeAssembly")),
    ("Open", ("Open", "RecentFiles", "Import")),
    ("Save", ("Save", "SaveAs", "SaveAll", "SaveCopy", "Export")),
    ("Print", ("Print", "PrintPreview", "PageSetup", "Print3D", "PrintPdf")),
    ("Undo", ("Undo",)),            # the flyout lists the undo history
    ("Redo", ("Redo",)),
    ("Select", ("Select", "BoxSelect", "LassoSelect", "MagnifiedSelection", "BoxElementSelect", "SelectAll")),
    ("Rebuild", None),
    ("FileProperties", None),
    ("Options", ("Options", "Customize", "Macros", "AddonManager")),
)

HEADS_UP = (
    ("ZoomFit", None),
    ("ZoomArea", None),
    ("PreviousView", None),
    ("SectionView", None),
    ("DynamicAnnotationViews", None),
    ("ViewOrientation", ("ViewSelector", "ViewFront", "ViewBack", "ViewLeft", "ViewRight", "ViewTop", "ViewBottom",
                         "ViewIsometric", "ViewTrimetric", "ViewDimetric", "NormalTo", "YUpViewOrientation",
                         "ZUpViewOrientation", "SingleView", "TwoViewHorizontal", "TwoViewVertical", "FourView",
                         "LinkViews", "NewView", "UpdateStandardViews", "ResetStandardViews")),
    ("DisplayStyle", ("ShadedEdges", "Shaded", "HiddenLinesRemoved", "HiddenLinesVisible", "Wireframe")),

    ("HideShowItems", ("ToggleVisibility", "ShowSelection", "HideSelection", "ShowAll", "HideAllTypes",
                       "ViewAllAnnotations", "ToggleAxisCross", "ViewTemporaryAxes", "ViewCameras", "ViewCenterOfMass",
                       "ViewBoundingBox", "ViewCoordinateSystems", "ViewCurves", "ViewDimensionNames", "ViewLights",
                       "ViewOrigins", "ViewPartingLines",
                       "ViewPlanes", "ViewPoints", "ViewSketches", "ViewBendLines", "ViewSketchDimensions",
                       "ViewSketchPlanes", "ViewWeldBead", "ViewMarkups",
                       "ViewGrid", "ViewSketchRelations", "ViewBodies", "ViewPrimaryPlanes")),
    ("EditAppearance", None),
    ("ApplyScene", None),
    ("ViewSettings", ("RealViewGraphics", "ShadowsInShadedMode", "AmbientOcclusion", "Perspective", "Cartoon")),
)


# Previous View, 3D Drawing View, Display Style, Hide/Show Items (rows next to DisplayStyle above).
HEADS_UP_SHEET = (
    ("DrawZoomFit", None),
    ("DrawZoomArea", None),
    ("DrawPreviousView", None),
    ("Draw3DDrawingView", None),
    ("DrawDisplayStyle", ("DrawDisplayShadedEdges", "DrawDisplayShaded", "DrawDisplayHiddenRemoved",
                          "DrawDisplayHiddenVisible", "DrawDisplayWireframe")),
    [e for e in HEADS_UP if e[0] == "HideShowItems"][0],
)

# Context toolbar for each kind of pick outside a sketch (contextbar.py). A command that

CONTEXT = {
    "face": ("EditFeature", "EditFeatureSketch", "HideSelection", "EditAppearance", "CopyAppearance", "Sketch", "NormalTo",
             "ZoomSelection"),
    "edge": ("EditFeature", "EditFeatureSketch", "HideSelection", "Fillet", "Chamfer", "ZoomSelection"),
    "vertex": ("EditFeature", "EditFeatureSketch", "HideSelection", "ZoomSelection"),
    "plane": ("EditFeature", "Sketch", "HideSelection", "ZoomSelection", "NormalTo"),
    "datum": ("EditFeature", "HideSelection"),
    "sketch": ("EditFeatureSketch", "HideSelection", "NormalTo", "ZoomSelection"),
    "feature": ("EditFeature", "EditFeatureSketch", "Rollback", "HideSelection", "EditAppearance", "ZoomSelection"),
    "body": ("HideSelection", "EditAppearance", "ZoomSelection", "Isolate"),
}
# Order of the relation buttons inside a sketch.
RELATIONS = ("RelHorizontal", "RelVertical", "RelMerge", "RelOnEdge", "RelMidpoint", "RelCollinear",
             "RelParallel", "RelPerpendicular", "RelTangent", "RelConcentric", "RelEqual", "RelSymmetric",
             "RelFix", "RelFixPoint", "RelConstruction")

# Every family the addon may draw; the icon copier extracts these plus the
# FreeCAD icon-name overrides below.
def families():
    names = {cmd.icon for cmd in ALL if cmd.icon}
    names.update(UI_FAMILIES)
    names.update(FREECAD_ICON_NAMES.values())
    return sorted(names)


UI_FAMILIES = (
    "PART_TAB", "CONFIGURATION_TAB", "FLYOUT_DIMXPERT", "DISPLAY_MANAGER_TAB", "DRAG_SEL_LIST_TAB",
    "CONTENT_MANAGER_TAB", "ASSY_VISUALIZATION_TAB", "DVE_TAB", "APPEARANCE_MANAGER_TAB_DISABLED",
    "TREE_FEATURE_FILTER", "TREE_EXPANDED_NORMAL", "TREE_COLLAPSED_NORMAL", "PART", "TREE_HISTORY_FOLDER",
    "TREE_SENSOR_FOLDER", "TREE_ANNOTATION_FOLDER", "TREE_MATERIAL_FOLDER", "TREE_ORIGIN",
    "TASKPANE_HOME_TAB", "FILE_EXPLORER_TAB", "DISPMGR_APPEAR", "DISPMGR_SCENE", "DISPMGR_DECAL",
    "CONFIG_HIDE_SHOW_CUSTOM_PROPS", "STANDARD_PROPERTIES", "CMD_PROPERTIES", "TOOLBOX", "ASSEMBLY_LIBRARY",
    "BTN_DROPDOWN_ARROW", "BTN_DISABLED_DROPDOWN_ARROW", "HORZ_TB_CHEVRON", "COLLAPSE_NORMAL",
    "EXPANDER_NORMAL", "FILEMENU_EXPAND", "FILEMENU_COLLAPSE", "PIN_NORMAL", "PIN_ACTIVE", "ICON_PINNED",
    "ICON_UNPINNED", "SEARCH_COMMANDS", "MINMAX_HELP", "MINMAX_LOGGED_OUT", "MINMAX_MINIMIZE",
    "MINMAX_MAXIMIZE", "MINMAX_RESTORE", "MINMAX_CLOSE", "MINMAX_CLOSE_HOVER", "CHECK_MARK",
    "STANDARD_CLOSE_DLG", "STANDARD_CANCEL", "PM_HELP", "PM_SK_CLOSE", "EDIT_EXIT_NOSAVE",
    "EXIT_SKETCH_CANCEL", "EDITCOMP_EXIT", "TASKPANE_EXPAND", "TASKPANE_COLLAPSE", "TASKPANE_OPTIONS",
    "OVERLAY_FMTREE_ERROR", "OVERLAY_FMTREE_WARNING", "OVERLAY_EDUCATIONAL", "SKETCH_NEW_SKETCH",
    "SKETCH_3D_SKETCH", "SKETCH_SELECT", "TOOLS_EQNS", "STANDARD_DELETE", "PART_HIDDEN",
    "FEATMGR_COLLAPSE_TAB", "FEATMGR_EXPAND_TAB", "COLLAPSE_HORIZ", "EXPAND_HORIZ",
    "I3DVIEW_ORIGINS", "I3DVIEW_PLANES", "I3DVIEW_SKETCHES", "I3DVIEW_ROTATE_VIEW", "I3DVIEW_PAN",
    "I3DVIEW_ZOOM_IN_OUT", "VIEWORIENT_VIEW_SELECTOR", "VIEWORIENT_SINGLE_VIEW",
)


# Tree icons for PartDesign features use the ".svg" spelling; commands use the
# bare name. The copier writes both spellings.
FREECAD_ICON_NAMES = {
    # documents / standard commands
    "document-new": "STANDARD_NEW", "document-open": "STANDARD_OPEN", "document-save": "STANDARD_SAVE",
    "document-save-as": "STANDARD_SAVEAS", "Std_SaveAll": "STANDARD_SAVEALL", "document-print": "STANDARD_PRINT",
    "document-print-preview": "STANDARD_PRINT_PREVIEW", "edit-undo": "STANDARD_UNDO", "edit-redo": "STANDARD_REDO",
    "edit-cut": "STANDARD_CUT", "edit-copy": "STANDARD_COPY", "edit-paste": "STANDARD_PASTE",
    "edit-delete": "STANDARD_DELETE", "view-refresh": "STANDARD_REBUILD", "preferences-system": "STANDARD_OPTIONS",
    "document-properties": "STANDARD_FILE_PROP", "help-browser": "STANDARD_HELP",
    "edit-select-all": "STANDARD_SELECT_ENTIRE_DOC", "edit-select-box": "STANDARD_SELECT_OVER_GEOMETRY",
    # view
    "zoom-all": "I3DVIEW_ZOOM_FIT", "zoom-border": "I3DVIEW_ZOOM_AREA", "zoom-selection": "I3DVIEW_ZOOM_SELECTION",
    "zoom-in": "I3DVIEW_ZOOM_IN_OUT", "zoom-out": "I3DVIEW_ZOOM_IN_OUT",
    "view-front": "VIEWORIENT_FRONT", "view-rear": "VIEWORIENT_BACK", "view-left": "VIEWORIENT_LEFT",
    "view-right": "VIEWORIENT_RIGHT", "view-top": "VIEWORIENT_TOP", "view-bottom": "VIEWORIENT_BOTTOM",
    "view-axonometric": "VIEWORIENT_ISOMETRIC", "view-isometric": "VIEWORIENT_ISOMETRIC",
    "Std_ViewDimetric": "VIEWORIENT_DIAMETRIC", "Std_ViewTrimetric": "VIEWORIENT_TRIMETRIC",
    "align-to-selection": "VIEWORIENT_NORMAL_TO", "Std_ToggleClipPlane": "I3DVIEW_SECT_VIEW",
    "view-perspective": "I3DVIEW_PERSPECTIVE", "Std_AxisCross": "I3DVIEW_AXES",
    "DrawStyleFlatLines": "I3DVIEW_SHADED_EDGES", "DrawStyleShaded": "I3DVIEW_SHADED",
    "DrawStyleHiddenLine": "I3DVIEW_HLR", "DrawStyleNoShading": "I3DVIEW_HLV",
    "DrawStyleWireFrame": "I3DVIEW_WIREFRAME",
    # tree
    "Document": "PART", "Std_CoordinateSystem": "TREE_ORIGIN", "Std_Plane": "REFGEO_PLANE",
    "Std_Axis": "REFGEO_AXIS", "Std_Point": "REFGEO_POINT", "Sketcher_Sketch": "SKETCH_SKETCH",
    # part design commands + tree features
    "PartDesign_Body": "PART", "PartDesign_Pad": "FEATURES_EXTRUDE_BOSS", "PartDesign_Pocket": "FEATURES_EXTRUDE_CUT",
    "PartDesign_Revolution": "FEATURES_REVOLVED_BOSS_BASE", "PartDesign_Groove": "FEATURES_REVOLVED_CUT",
    "PartDesign_Hole": "FEATURES_HOLE_WIZARD", "PartDesign_AdditivePipe": "FEATURES_SWEPT_BOSS",
    "PartDesign_SubtractivePipe": "FEATURES_SWEPT_CUT", "PartDesign_AdditiveLoft": "FEATURES_LOFTED_BOSS",
    "PartDesign_SubtractiveLoft": "FEATURES_LOFTED_CUT", "PartDesign_AdditiveHelix": "FEATURES_SWEPT_BOSS",
    "PartDesign_SubtractiveHelix": "FEATURES_SWEPT_CUT", "PartDesign_Fillet": "FEATURES_FILLET",
    "PartDesign_Chamfer": "FEATURES_CHAMFER", "PartDesign_Draft": "FEATURES_DRAFT",
    "PartDesign_Thickness": "FEATURES_SHELL", "PartDesign_Mirrored": "FEATURES_MIRROR",
    "PartDesign_LinearPattern": "FEATURES_LINEAR_PATTERN", "PartDesign_PolarPattern": "FEATURES_CIRCULAR_PATTERN",
    "PartDesign_MultiTransform": "FEATURES_MIRROR_PATTERN", "PartDesign_Scaled": "FEATURES_SCALE",
    "PartDesign_Boolean": "FEATURES_COMBINE", "PartDesign_Plane": "REFGEO_PLANE", "PartDesign_Line": "REFGEO_AXIS",
    "PartDesign_Point": "REFGEO_POINT", "PartDesign_CoordinateSystem": "REFGEO_CSYS",
    "PartDesign_ShapeBinder": "REFGEO_MATE_REF", "PartDesign_SubShapeBinder": "REFGEO_MATE_REF",
    "Sketcher_NewSketch": "SKETCH_SKETCH",
    # sketcher commands
    "Sketcher_LeaveSketch": "EXIT_SKETCH_CANCEL", "Sketcher_EditSketch": "SKETCH_MODIFY",
    "Sketcher_ViewSketch": "VIEWORIENT_NORMAL_TO", "Sketcher_ViewSection": "I3DVIEW_SECT_VIEW",
    "Sketcher_ValidateSketch": "TOOLS_CHECK",
    "Sketcher_CreatePoint": "SKETCH_POINT", "Sketcher_CreateLine": "SKETCH_LINE",
    "Sketcher_CreatePolyline": "SKETCH_LINE", "Sketcher_CreateArc": "SKETCH_CPRPT_ARC",
    "Sketcher_Create3PointArc": "SKETCH_3PT_ARC", "Sketcher_CreateElliptical_Arc": "SKETCH_PARTIAL_ELLIPSE",
    "Sketcher_CreateHyperbolic_Arc": "SKETCH_CONIC", "Sketcher_CreateParabolic_Arc": "SKETCH_PARABOLA",
    "Sketcher_CreateCircle": "SKETCH_CIRCLE", "Sketcher_Create3PointCircle": "SKETCH_CTRPT_CIRCLE",
    "Sketcher_CreateEllipseByCenter": "SKETCH_ELLIPSE", "Sketcher_CreateEllipse_3points": "SKETCH_ELLIPSE",
    "Sketcher_CreateRectangle": "SKETCH_CORNER_RECT", "Sketcher_CreateRectangle_Center": "SKETCH_CTR_RECT",
    "Sketcher_CreateOblong": "SKETCH_3PT_CENTER_RECT", "Sketcher_CreateHexagon": "SKETCH_POLYGON",
    "Sketcher_CreateRegularPolygon": "SKETCH_POLYGON", "Sketcher_CreateSlot": "SKETCH_STRAIGHT_SLOT",
    "Sketcher_CreateArcSlot": "SKETCH_CTRPT_ARC_SLOT", "Sketcher_CreateBSpline": "SKETCH_SPLINE",
    "Sketcher_Create_Periodic_BSpline": "SKETCH_SPLINE", "Sketcher_CreateBSplineByInterpolation": "SKETCH_STYLE_SPLINE",
    "Sketcher_CreateFillet": "SKETCH_FILLET", "Sketcher_CreateChamfer": "SKETCH_CHAMFER",
    "Sketcher_Trimming": "SKETCH_TRIM", "Sketcher_Extend": "SKETCH_EXTEND_ENTITIES", "Sketcher_Split": "SKETCH_SPLIT_ENTITIES",
    "Sketcher_Projection": "SKETCH_CONVERT_ENTITIES", "Sketcher_Intersection": "SKETCH_INTERSECTION_CURVE",
    "Sketcher_CarbonCopy": "SKETCH_COPY_ENTITIES", "Sketcher_Symmetry": "SKETCH_MIRROR_ENTITIES",
    "Sketcher_Offset": "SKETCH_OFFSET_ENTITIES", "Sketcher_Rotate": "SKETCH_ROTATE_ENTITIES",
    "Sketcher_Scale": "SKETCH_SCALE_ENTITIES", "Sketcher_Translate": "SKETCH_MOVE_ENTITIES",
    "Sketcher_ToggleConstruction": "SKETCH_CONSTRUCT_GEOM", "Sketcher_RectangularArray": "SKETCH_LINEAR_PATTERN",
    # evaluate
    "umf-measurement": "TOOLS_MEASURE", "Part_CheckGeometry": "TOOLS_CHECK",
}


# ---- Sketch tab tools live with no sketch open (fwsketch-fix42) --------------------------------

# they ask for a plane, open a sketch on it and start. swstyle.sketchfirstlive registers a
# SWStyle_SF_<native> wrapper for each native below; the wrapper goes first on these buttons
# (where it is missing, the buttons fall back to the native as before).
SKETCH_FIRST_NATIVES = (
    "Sketcher_CreateLine", "SWStyle_3PointCornerRectangle", "SWStyle_3PointCenterRectangle", "SWStyle_Parallelogram",
    "Sketcher_CreateOblong", "Sketcher_CreateEllipseByCenter", "Sketcher_CreateArcOfEllipse",
    "Sketcher_CreateArcOfParabola", "SWStyle_Conic", "SWStyle_SketchText", "Sketcher_CreatePoint",
    "SWStyle_EquationDrivenCurve", "SWStyle_ConvertEntities", "SWStyle_SilhouetteEntities",
    "Sketcher_Intersection", "SWStyle_OffsetEntities",
)
SKETCH_FIRST_KEYS = ("Polyline", "ThreePointCornerRectangle", "ThreePointCenterRectangle", "Parallelogram", "Oblong",
                     "Ellipse", "PartialEllipse", "Parabola", "Conic", "Text", "SketchPoint", "EquationDrivenCurve",
                     "Convert", "SilhouetteEntities", "IntersectionCurve", "Offset")
for _c in _ALL:
    if _c.key in SKETCH_FIRST_KEYS and not any(n.startswith("SWStyle_SF_") for n in _c.natives):
        _n = _c.natives[0] if _c.natives else None     # only where that native is the button's own
        if _n in SKETCH_FIRST_NATIVES:
            _c.natives = ("SWStyle_SF_" + _n,) + _c.natives

# ---- Features tab buttons live in a part with no solid yet (look audit 11-20, no greyed buttons) -----
# swstyle.solidfirstlive registers SWStyle_EP_<native>: with a solid (or a sketch for a sweep or loft)
# it starts the native as before; in an empty part it says a boss comes first and starts one.
SOLID_FIRST_KEYS = ("CutBoundary", "Fillet", "Chamfer", "Draft", "Shell", "Wrap", "Intersect",
                    # Insert > Features entries that were grey in an empty part (features-395)
                    "SplitBody", "Dome", "Thread", "Scale", "Freeform", "Deform", "Flex", "Indent",
                    "AdvancedHole", "StudWizard",
                    # Surfaces tab cuts in a surfaces-only part (look audit AJ3)
                    "ThickenedCut", "CutWithSurface")
for _c in _ALL:
    if _c.key in SOLID_FIRST_KEYS and _c.natives and not _c.natives[0].startswith("SWStyle_EP_"):
        _c.natives = ("SWStyle_EP_" + _c.natives[0],) + _c.natives

# One-line tips (our own words) for the buttons that had none, so every CommandManager button

_TIPS = {
    "Open": "Opens an existing document.",
    "RecentFiles": "Lists the documents you worked on lately.",
    "Save": "Saves the active document.",
    "SaveAs": "Saves the active document under a new name or format.",
    "SaveAll": "Saves every open document that has changes.",
    "SaveCopy": "Saves a copy of the document and keeps working on the original.",
    "Export": "Writes the picked items or the document to another file format.",
    "Import": "Brings a file of another format into the document.",
    "Print": "Prints the active document.",
    "PrintPreview": "Shows how the document will look on paper.",
    "PrintPdf": "Prints the active document to a PDF file.",
    "Undo": "Takes back the last change.",
    "Redo": "Puts back the change you just undid.",
    "BoxElementSelect": "Drag a box to pick the entities inside it.",
    "SelectAll": "Picks every item of the active document.",
    "FileProperties": "Shows and edits the document's summary and custom properties.",
    "Options": "Changes system options and document properties.",
    "Macros": "Records, edits and runs macros.",
    "AddonManager": "Finds and installs add-ins.",
    "Help": "Opens the help for FreeCAD.",
    "EditSketch": "Opens the sketch for editing.",
    "HorizontalDimension": "Adds a horizontal dimension between two picked items.",
    "VerticalDimension": "Adds a vertical dimension between two picked items.",
    "AngularDimension": "Adds an angle dimension between two lines.",
    "RadiusDimension": "Adds a radius dimension to an arc or circle.",
    "BaselineDimension": "Adds dimensions that all start from one base line.",
    "ChainDimension": "Adds dimensions that run one after another in a chain.",
    "OrdinateDimension": "Adds ordinate dimensions measured from a zero point.",
    "HorizontalOrdinateDimension": "Adds horizontal ordinate dimensions from a zero point.",
    "VerticalOrdinateDimension": "Adds vertical ordinate dimensions from a zero point.",
    "AngularRunningDimension": "Adds running angle dimensions from a zero line.",
    "SymmetricLinearDiameterDimension": "Dimensions a revolved profile as a diameter across a centerline.",
    "ChamferDimension": "Dimensions a chamfer by its length and angle.",
    "SplineInterpolation": "Sketches a spline through the points you click.",
    "PeriodicSpline": "Sketches a closed spline with no seam.",
    "PartialEllipse": "Sketches part of an ellipse from its center and two ends.",
    "Parabola": "Sketches a parabola from its focus, top and two ends.",
    "ArcSlot": "Sketches a slot that follows an arc.",
    "RegularPolygon": "Sketches a polygon with equal sides.",
    "SketchChamfer": "Cuts the corner of two sketch entities at an angle.",
    "Extend": "Lengthens a sketch entity until it meets another one.",
    "Split": "Splits a sketch entity in two at the point you click.",
    "Join": "Joins touching sketch entities into one.",
    "IntersectionCurve": "Sketches the curve where a plane or face crosses the model.",
    "CarbonCopy": "Copies the geometry of another sketch into this one.",
    "CircularSketchPattern": "Repeats sketch entities around a center point.",
    "RotateEntities": "Turns the picked sketch entities about a point.",
    "ScaleEntities": "Makes the picked sketch entities larger or smaller.",
    "Horizontal": "Makes the picked lines or points horizontal.",
    "Vertical": "Makes the picked lines or points vertical.",
    "Parallel": "Makes the picked lines parallel.",
    "Perpendicular": "Makes two lines meet at a right angle.",
    "Tangent": "Makes a line or arc touch a curve smoothly.",
    "Equal": "Gives the picked entities the same length or radius.",
    "Symmetric": "Makes two entities mirror each other about a centerline.",
    "Fix": "Holds the picked entity where it is.",
    "ConflictingRelations": "Lists the relations that fight each other and lets you fix them.",
    "RedundantRelations": "Lists the relations that say the same thing twice.",
    "DeleteAllRelations": "Takes every relation out of the sketch.",
    "SketchGrid": "Shows or hides the sketch grid.",
    "ViewSketch": "Looks straight at the sketch plane.",
    "SectionSketch": "Cuts the model at the sketch plane so the sketch is easy to see.",
    "WB_PartDesign": "Switches to the Part Design tools.",
    "WB_Part": "Switches to the Part tools.",
    "WB_Assembly": "Switches to the Assembly tools.",
    "WB_TechDraw": "Switches to the drawing tools.",
    "WB_FEM": "Switches to the simulation tools.",
    "WB_CAM": "Switches to the CAM tools.",
    "WB_Spreadsheet": "Switches to the spreadsheet tools.",
    "WB_Draft": "Switches to the Draft tools.",
    "WB_Mesh": "Switches to the mesh tools.",
    "WB_Surface": "Switches to the surface tools.",
    "WB_SheetMetal": "Switches to the sheet metal tools.",
    "ZoomSelection": "Zooms to the picked items.",
    "ViewFront": "Turns the view to look at the front.",
    "ViewBack": "Turns the view to look at the back.",
    "ViewLeft": "Turns the view to look at the left side.",
    "ViewRight": "Turns the view to look at the right side.",
    "ViewTop": "Turns the view to look down from the top.",
    "ViewBottom": "Turns the view to look up from the bottom.",
    "ViewIsometric": "Turns the view to the isometric angle.",
    "ViewTrimetric": "Turns the view to the trimetric angle.",
    "ViewDimetric": "Turns the view to the dimetric angle.",
    "NormalTo": "Turns the view to look straight at the picked face or plane.",
    "ShowSelection": "Shows the picked hidden items.",
    "HideSelection": "Hides the picked items.",
    "ShowAll": "Shows every hidden item.",
    "Transparency": "Makes the picked item see-through, or solid again.",
    "Perspective": "Shows the model with perspective.",
    "Orthographic": "Shows the model without perspective.",
    "RelHorizontal": "Makes the picked lines or points horizontal.",
    "RelVertical": "Makes the picked lines or points vertical.",
    "RelMerge": "Joins two points into one.",
    "RelOnEdge": "Puts a point on a line, arc or edge.",
    "RelMidpoint": "Keeps a point at the middle of a line.",
    "RelCollinear": "Puts the picked lines on one straight line.",
    "RelParallel": "Makes the picked lines parallel.",
    "RelPerpendicular": "Makes two lines meet at a right angle.",
    "RelTangent": "Makes a line or arc touch a curve smoothly.",
    "RelConcentric": "Gives arcs and circles the same center.",
    "RelEqual": "Gives the picked entities the same length or radius.",
    "RelSymmetric": "Makes two entities mirror each other about a centerline.",
    "RelFix": "Holds the picked entity where it is.",
    "RelFixPoint": "Holds the picked point where it is.",
    "RelConstruction": "Turns the picked entities into construction geometry, or back.",
}
for _c in _ALL:
    if not _c.tip and _c.key in _TIPS:
        _c.tip = _TIPS[_c.key]
