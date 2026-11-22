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

import os
import time

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None


# ===================================================================== catalog keys
# (key, label, natives in order of preference, tip, caption). Icons come from the FreeCAD command.
KEYS = (
    # ---- Simulation
    ("SIM_NewStudy", "New Study", ("SWStyle_SimNewStudy", "FEM_Analysis"),
     "Starts a study on the active part: static, frequency, buckling or thermal, with material, mesh and solver.",
     "New\nStudy"),
    ("SIM_Analysis", "Empty Study", ("FEM_Analysis",), "An empty analysis container.", None),
    ("SIM_Advisor", "Simulation Advisor", ("SWStyle_SimStudyAdvisor",),
     "Asks what you want to find out (strength, vibration, buckling, heat), starts that type of study and walks through its steps.",
     "Simulation\nAdvisor"),
    ("SIM_Props", "Study Properties", ("SWStyle_SimStudyProps",),
     "The options of the active study's type: solver, frequencies, buckling modes, steady state or time.", "Study\nProperties"),
    ("SIM_Wizard", "Static Study Wizard", ("SWStyle_SimulationWizard", "SWStyle_SimNewStudy"),
     "Walks through a linear static study step by step (the SimulationXpress wizard).", "Static Study\nWizard"),
    ("SIM_ApplyMaterial", "Apply Material", ("FEM_MaterialSolid",), "Gives the study a solid material.", "Apply\nMaterial"),
    ("SIM_MaterialNonlinear", "Nonlinear Material", ("FEM_MaterialMechanicalNonlinear",), "Adds plasticity to a material.", None),
    ("SIM_MaterialReinforced", "Reinforced Material", ("FEM_MaterialReinforced",), "A reinforced (concrete) material.", None),
    ("SIM_Fixed", "Fixed Geometry", ("FEM_ConstraintFixed",), "Fixes faces, edges or vertices.", "Fixture\nAdvisor"),
    ("SIM_Roller", "Roller/Slider", ("FEM_ConstraintDisplacement",),
     "Fixes chosen directions only (displacement and rotation per axis).", None),
    ("SIM_Hinge", "Fixed Hinge", ("FEM_ConstraintPlaneRotation", "FEM_ConstraintDisplacement"),
     "Keeps a face's plane while it may turn.", None),
    ("SIM_Elastic", "Elastic Support", ("FEM_ConstraintSpring",), "A spring foundation on faces.", None),
    ("SIM_Rigid", "Rigid Connector", ("FEM_ConstraintRigidBody", "FEM_ConstraintTransform"), "Ties faces to a rigid reference.", None),
    ("SIM_Force", "Force", ("FEM_ConstraintForce",), "A force on faces, edges or vertices.", "External\nLoads"),
    ("SIM_Pressure", "Pressure", ("FEM_ConstraintPressure",), "A pressure normal to faces.", None),
    ("SIM_Gravity", "Gravity", ("SWStyle_SimGravity", "FEM_ConstraintSelfWeight"), "The part's own weight.", None),
    ("SIM_Centrifugal", "Centrifugal Force", ("FEM_ConstraintCentrif",), "Spins the part about an axis.", None),
    ("SIM_Bearing", "Bearing Load", ("FEM_ConstraintBearing",), "A bearing load on a cylindrical face.", None),
    ("SIM_Temperature", "Temperature", ("FEM_ConstraintTemperature",), "A temperature on faces.", None),
    ("SIM_HeatFlux", "Heat Flux", ("FEM_ConstraintHeatflux",), "Heat flux or convection on faces.", None),
    ("SIM_BodyHeat", "Heat Power", ("FEM_ConstraintBodyHeatSource",), "Heat made inside the body.", None),
    ("SIM_InitialTemp", "Initial Temperature", ("FEM_ConstraintInitialTemperature",), "The start temperature.", None),
    ("SIM_ThermalLoads", "Thermal Loads", ("FEM_ConstraintTemperature",), "Thermal loads of a thermal study.", "Thermal\nLoads"),
    ("SIM_Contact", "Contact Set", ("FEM_ConstraintContact",), "Contact between two faces.", "Connections\nAdvisor"),
    ("SIM_Bonded", "Bonded", ("FEM_ConstraintTie",), "Bonds two faces together.", None),
    ("SIM_Spring", "Spring", ("FEM_ConstraintSpring",), "A spring between the part and ground.", None),
    ("SIM_Shell", "Shell Manager", ("FEM_ElementGeometry2D",), "Shell thickness for faces.", "Shell\nManager"),
    ("SIM_Beam", "Beam", ("FEM_ElementGeometry1D",), "Beam cross-section for edges.", None),
    ("SIM_BeamRotation", "Beam Rotation", ("FEM_ElementRotation1D",), "Turns a beam section.", None),
    ("SIM_Mesh", "Create Mesh", ("FEM_MeshGmshFromShape", "FEM_MeshNetgenFromShape"), "Meshes the part (Gmsh).", "Create\nMesh"),
    ("SIM_MeshNetgen", "Create Mesh (Netgen)", ("FEM_MeshNetgenFromShape",), "Meshes the part with Netgen.", None),
    ("SIM_MeshControl", "Mesh Control", ("FEM_MeshRegion",), "A finer mesh on chosen faces, edges or vertices.", None),
    ("SIM_MeshBoundary", "Boundary Layer", ("FEM_MeshBoundaryLayer",), "Thin layers along walls.", None),
    ("SIM_MeshClear", "Delete Mesh", ("FEM_MeshClear", "FEM_FEMMeshClear"), "Deletes the mesh of the picked mesh object.", None),
    ("SIM_MeshInfo", "Mesh Details", ("FEM_MeshDisplayInfo", "FEM_FEMMeshDisplayInfo"), "Nodes and elements of the mesh.", None),
    ("SIM_Run", "Run This Study", ("SWStyle_SimRun", "FEM_SolverRun"), "Meshes if needed and runs the active study.",
     "Run This\nStudy"),
    ("SIM_SolverCcx", "CalculiX Solver", ("FEM_SolverCalculiXCcxTools", "FEM_SolverCalculiX"), "Adds a CalculiX solver.", None),
    ("SIM_SolverElmer", "Elmer Solver", ("FEM_SolverElmer",), "Adds an Elmer solver.", None),
    ("SIM_SolverZ88", "Z88 Solver", ("FEM_SolverZ88",), "Adds a Z88 solver.", None),
    ("SIM_SolverMystran", "Mystran Solver", ("FEM_SolverMystran",), "Adds a Mystran solver.", None),
    ("SIM_SolverControl", "Solver Job", ("FEM_SolverControl",), "Opens the solver's job panel.", None),
    ("SIM_Results", "Results", ("FEM_ResultShow", "FEM_PostPipelineFromResult"), "Shows stress, displacement and strain.",
     "Results\nAdvisor"),
    ("SIM_Plot", "New Plot", ("FEM_PostPipelineFromResult",), "A result plot you can filter.", None),
    ("SIM_Probe", "Probe", ("FEM_PostFilterDataAtPoint",), "The result value at a point.", None),
    ("SIM_ListLine", "List Along Line", ("FEM_PostFilterDataAlongLine",), "Result values along a line.", None),
    ("SIM_Section", "Section Clipping", ("FEM_PostFilterClipRegion", "FEM_PostFilterCutFunction"), "Cuts the plot with a plane.", None),
    ("SIM_IsoClip", "Iso Clipping", ("FEM_PostFilterClipScalar", "FEM_PostFilterContours"), "Shows only values above a limit.", None),
    ("SIM_Deform", "Deformed Result", ("FEM_PostFilterWarp",), "Shows the deformed shape, scaled.", "Deformed\nResult"),
    ("SIM_Linearized", "Linearized Stress", ("FEM_PostFilterLinearizedStresses",), "Stress through a section line.", None),
    ("SIM_ApplyChanges", "Update Plots", ("FEM_PostApplyChanges",), "Applies plot changes now.", None),
    ("SIM_Purge", "Delete Results", ("FEM_ResultsPurge",), "Deletes the study's results.", None),
    ("SIM_Diagnostic", "Diagnostic Tools", ("FEM_MeshDisplayInfo", "FEM_FEMMeshDisplayInfo", "FEM_MeshGmshFromShape"), "Checks the mesh: nodes and elements.",
     "Diagnostic\nTools"),
    ("SIM_PlotTools", "Plot Tools", ("FEM_PostFilterClipRegion", "FEM_PostFilterCutFunction"), "Section, probe and line plots.", None),
    ("SIM_Report", "Report", ("SWStyle_SimReport",), "Writes an HTML report of the active study.", None),
    ("SIM_ReportImage", "Include Image for Report", ("SWStyle_SimReportImage",), "Saves the view for the study report.", None),
    ("SIM_AllTools", "All Simulation Tools", ("SWStyle_AllTools_FEM",), "Every FEM command, by toolbar.", "All\nTools"),
    # ---- Flow Simulation
    ("FLOW_New", "New Project", ("SWStyle_FlowNewProject",),
     "Starts a flow project on the active body (the fluid region): Elmer solver, flow equation, fluid and mesh.",
     "New\nProject"),
    ("FLOW_Fluid", "Fluid", ("FEM_MaterialFluid",), "The fluid of the project.", None),
    ("FLOW_Velocity", "Inlet Velocity", ("FEM_ConstraintFlowVelocity",), "A velocity on an opening or wall.", "Boundary\nCondition"),
    ("FLOW_Pressure", "Environment Pressure", ("FEM_ConstraintPressure",), "A pressure on an opening.", None),
    ("FLOW_InitVel", "Initial Velocity", ("FEM_ConstraintInitialFlowVelocity",), "The start velocity everywhere.", "Initial\nConditions"),
    ("FLOW_InitPress", "Initial Pressure", ("FEM_ConstraintInitialPressure",), "The start pressure everywhere.", None),
    ("FLOW_Equation", "Flow Equation", ("FEM_EquationFlow",), "Adds the flow equation to the picked solver.", None),
    ("FLOW_Heat", "Heat Conduction", ("FEM_EquationHeat",), "Adds heat to the picked solver.", None),
    ("FLOW_Project", "Project", ("FEM_EquationHeat",), "Adds heat transfer to the picked solver.", None),
    ("FLOW_Sources", "Sources", ("FEM_ConstraintBodyHeatSource",), "Heat sources.", None),
    ("FLOW_Mesh", "Mesh Settings", ("FEM_MeshGmshFromShape", "FEM_MeshNetgenFromShape"), "Meshes the fluid region.", "Mesh\nSettings"),
    ("FLOW_Results", "Results", ("FEM_PostPipelineFromResult", "FEM_ResultShow"), "Flow result plots.", None),
    ("FLOW_AllTools", "All Flow Tools", ("SWStyle_AllTools_FEM",), "Every FEM command, by toolbar.", "All\nTools"),
    # ---- Flow (CFD): the CfdOF add-on (OpenFOAM), only when it is installed. A button whose command this CfdOF
    # version lacks is dropped on first show (_prune); "All CFD Tools" lists every command it does have.
    ("CFD_Analysis", "New Flow Analysis", ("CfdOF_Analysis",), "Starts a CFD analysis on the active body: solver, fluid and mesh.",
     "New Flow\nAnalysis"),
    ("CFD_Physics", "Physics Model", ("CfdOF_PhysicsModel",), "Steady or transient, laminar or turbulent, heat transfer.", "Physics\nModel"),
    ("CFD_Fluid", "Fluid Properties", ("CfdOF_FluidMaterial",), "The fluid: density, viscosity, thermal data.", "Fluid\nProperties"),
    ("CFD_Init", "Initial Conditions", ("CfdOF_InitialiseInternal",), "The velocity, pressure and temperature the flow starts from.",
     "Initial\nConditions"),
    ("CFD_Boundary", "Boundary Conditions", ("CfdOF_FluidBoundary",), "Inlets, outlets, walls and openings on the faces.",
     "Boundary\nConditions"),
    ("CFD_Porous", "Porous Zone", ("CfdOF_PorousZone", "CfdOF_ZoneCreate"), "A region the fluid passes through slowly.", None),
    ("CFD_InitZone", "Initialisation Zone", ("CfdOF_InitialisationZone",), "A region that starts with values of its own.",
     "Initialisation\nZone"),
    ("CFD_Goals", "Goals", ("CfdOF_ReportingFunctions",), "Forces, coefficients and probes the solver reports while it runs.",
     None),
    ("CFD_Mesh", "Mesh", ("CfdOF_MeshFromShape",), "Meshes the fluid region for OpenFOAM.", None),
    ("CFD_Refine", "Mesh Refinement", ("CfdOF_MeshRegion", "CfdOF_MeshRefinement"), "Finer cells near a face, edge or region.",
     "Mesh\nRefinement"),
    ("CFD_Solver", "Solver Settings", ("CfdOF_SolverControl",), "Writes the case, runs OpenFOAM and shows the progress.",
     "Run\nSolver"),
    ("CFD_Results", "View Results", ("CfdOF_ViewResults", "CfdOF_ParaviewResults"), "Opens the results to plot.", "View\nResults"),
    ("CFD_AllTools", "All CFD Tools", ("SWStyle_AllTools_CfdOF",), "Every CfdOF command, by toolbar.", "All\nTools"),
    # ---- CAM
    ("CAM_Setup", "Setup", ("CAM_Job",), "A machining job: model, stock and origin.", None),
    ("CAM_Stock", "Stock Manager", ("SWStyle_CAMStock",), "Opens the job's stock and setup.", None),
    ("CAM_Tools", "Tool Library", ("CAM_ToolBitLibraryOpen", "CAM_ToolBitDock"), "The tools you machine with.", "Tool\nLibrary"),
    ("CAM_ToolDock", "Tool Bit Dock", ("CAM_ToolBitDock",), "Adds tools to the job.", None),
    ("CAM_ToolController", "Tool Controller", ("CAM_ToolController",), "Feeds and speeds for a tool.", None),
    ("CAM_Profile", "Contour Mill", ("CAM_Profile",), "Mills around the outside or inside.", "Contour\nMill"),
    ("CAM_Pocket", "Pocket Mill", ("CAM_Pocket_Shape", "CAM_Pocket"), "Clears pockets.", None),
    ("CAM_Face", "Face Mill", ("CAM_MillFace",), "Faces the top of the stock.", None),
    ("CAM_Adaptive", "Adaptive Rough Mill", ("CAM_Adaptive",), "Roughing with constant tool load.", None),
    ("CAM_Helix", "Helix", ("CAM_Helix",), "Helical hole milling.", None),
    ("CAM_Slot", "Slot", ("CAM_Slot",), "Mills slots.", None),
    ("CAM_Engrave", "Engrave", ("CAM_Engrave",), "Engraves along edges.", None),
    ("CAM_Vcarve", "V-Carve", ("CAM_Vcarve",), "V-bit carving.", None),
    ("CAM_Deburr", "Deburr", ("CAM_Deburr",), "Chamfers edges with a chamfer tool.", None),
    ("CAM_Pocket3D", "3D Pocket", ("CAM_Pocket3D",), "Pockets in 3D.", None),
    ("CAM_Surface", "Area Clearance (3D)", ("CAM_Surface",), "3D surface milling.", None),
    ("CAM_Waterline", "Z Level", ("CAM_Waterline",), "Waterline finishing.", None),
    ("CAM_Drill", "Hole Machining", ("CAM_Drilling",), "Drills holes.", "Hole\nMachining"),
    ("CAM_Thread", "Thread Mill", ("CAM_ThreadMilling",), "Mills threads.", None),
    ("CAM_Tapping", "Tap", ("CAM_Tapping",), "Taps holes.", None),
    ("CAM_Dogbone", "Dogbone", ("CAM_DressupDogbone",), "Corner reliefs for inside corners.", "Dress-up"),
    ("CAM_Tag", "Holding Tags", ("CAM_DressupTag",), "Tabs that hold the part.", None),
    ("CAM_LeadInOut", "Lead In/Out", ("CAM_DressupLeadInOut",), "Leads into and out of the cut.", None),
    ("CAM_Ramp", "Ramp Entry", ("CAM_DressupRampEntry",), "Ramps down into the cut.", None),
    ("CAM_Boundary", "Boundary", ("CAM_DressupPathBoundary", "CAM_DressupBoundary"), "Keeps the path in a boundary.", None),
    ("CAM_Generate", "Generate Toolpath", ("SWStyle_CAMGenerate",), "Recomputes every toolpath.", "Generate\nToolpath"),
    ("CAM_Simulate", "Simulate Toolpath", ("CAM_SimulatorGL", "CAM_Simulator"), "Plays the material removal.", "Simulate\nToolpath"),
    ("CAM_SimulateOld", "Simulate (Classic)", ("CAM_Simulator",), "The classic simulator.", None),
    ("CAM_Inspect", "Step Thru Toolpath", ("CAM_Inspect",), "Lists the G-code of the picked path.", "Step Thru\nToolpath"),
    ("CAM_Post", "Post Process", ("CAM_Post",), "Writes G-code for your machine.", "Post\nProcess"),
    ("CAM_Sanity", "Check Job", ("CAM_Sanity",), "Checks the job for problems and writes a report.", "Check\nJob"),
    ("CAM_Array", "Pattern Toolpath", ("CAM_Array",), "Repeats a toolpath.", None),
    ("CAM_Copy", "Copy Operation", ("CAM_OperationCopy", "CAM_OpCopy"), "Copies an operation.", None),
    ("CAM_Active", "Suppress Operation", ("CAM_OpActiveToggle",), "Turns an operation off or on.", None),
    ("CAM_AllTools", "All CAM Tools", ("SWStyle_AllTools_CAM",), "Every CAM command, by toolbar.", "All\nTools"),
    # ---- ScanTo3D
    ("S3D_ImportMesh", "Open Scan", ("Mesh_Import",), "Opens an STL, OBJ, PLY or other mesh.", "Open\nScan"),
    ("S3D_ImportPoints", "Open Point Cloud", ("Points_Import",), "Opens a point cloud (ASC, PCD, PLY, E57).", None),
    ("S3D_Prep", "Mesh Prep Wizard", ("Mesh_Evaluation",), "Finds and fixes mesh errors.", "Mesh Prep\nWizard"),
    ("S3D_Normals", "Fix Normals", ("Mesh_HarmonizeNormals",), "Points every facet the same way.", None),
    ("S3D_FillHoles", "Fill Holes", ("Mesh_FillupHoles",), "Closes holes in the mesh.", None),
    ("S3D_RemoveParts", "Remove Noise", ("Mesh_RemoveComponents",), "Deletes small loose pieces.", None),
    ("S3D_Smooth", "Smooth", ("Mesh_Smoothing",), "Smooths the mesh.", None),
    ("S3D_Decimate", "Reduce", ("Mesh_Decimating",), "Takes facets out.", None),
    ("S3D_Scale", "Scale", ("Mesh_Scale",), "Scales the mesh.", None),
    ("S3D_Trim", "Trim", ("Mesh_PolyCut", "Mesh_TrimByPlane"), "Cuts mesh away with a drawn loop.", None),
    ("S3D_ToPoints", "Mesh to Points", ("Points_Convert",), "Makes a point cloud.", None),
    ("S3D_PointsStructure", "Structure Points", ("Points_Structure",), "Orders the points in a grid.", None),
    ("S3D_PointsMerge", "Merge Points", ("Points_Merge",), "Joins point clouds.", None),
    ("S3D_PointsCut", "Trim Points", ("Points_PolyCut",), "Deletes points inside a drawn loop.", None),
    ("S3D_Segment", "Segment Mesh", ("Mesh_Segmentation", "Reen_Segmentation"), "Splits the mesh into regions.", "Segment\nMesh"),
    ("S3D_SegmentFit", "Best-Fit Segments", ("Mesh_SegmentationBestFit",), "Planes, cylinders and spheres in the mesh.", None),
    ("S3D_SegmentManual", "Manual Segments", ("Reen_SegmentationManual",), "Picks regions by hand.", None),
    ("S3D_Surface", "Surface Wizard", ("Reen_ApproxSurface",), "Fits a B-spline surface to the scan.", "Surface\nWizard"),
    ("S3D_Plane", "Fit Plane", ("Reen_ApproxPlane",), "Fits a plane.", None),
    ("S3D_Cylinder", "Fit Cylinder", ("Reen_ApproxCylinder",), "Fits a cylinder.", None),
    ("S3D_Sphere", "Fit Sphere", ("Reen_ApproxSphere",), "Fits a sphere.", None),
    ("S3D_Poisson", "Poisson Surface", ("Reen_PoissonReconstruction",), "Makes a closed mesh from points.", None),
    ("S3D_Triangulate", "Triangulate Points", ("Reen_ViewTriangulation",), "A mesh from a structured point cloud.", None),
    ("S3D_ToBody", "Mesh to Body", ("Part_ShapeFromMesh",), "Turns the mesh into a body.", None),
    ("S3D_Curves", "Curve Wizard", ("Mesh_CrossSections",), "Section curves through the scan.", "Curve\nWizard"),
    ("S3D_Section", "Section Curve", ("Mesh_SectionByPlane",), "A curve where a plane cuts the mesh.", None),
    ("S3D_Boundary", "Boundary Curves", ("Reen_MeshBoundary",), "Curves along the open edges.", None),
    ("S3D_Deviation", "Deviation Analysis", ("Inspection_VisualInspection",), "Colours the gap between scan and model.",
     "Deviation\nAnalysis"),
    ("S3D_InspectPoint", "Deviation at Point", ("Inspection_InspectElement",), "The gap at one point.", None),
    ("S3D_Curvature", "Curvature", ("Mesh_VertexCurvature", "Mesh_CurvatureInfo"), "Curvature on the mesh.", None),
    # ---- CircuitWorks (circuitworks.py: IDF boards in the CircuitWorks window, Build Model, IDF 3.0 export)
    ("ECAD_Open", "Open ECAD File", ("SWStyle_ECADOpen",),
     "Opens an IDF board (.emn with its .emp) in the CircuitWorks window: filter its components, then Build Model.",
     "Open ECAD\nFile"),
    ("ECAD_Export", "Export to ECAD", ("SWStyle_ECADExport",),
     "Saves the board and its components as IDF 3.0 (.emn and .emp) for the ECAD program.", "Export\nto ECAD"),
    ("ECAD_Update", "Update Model", ("SWStyle_ECADUpdate",),
     "Reads the ECAD file again: components moved, added or removed by reference designator.", "Update\nModel"),
    ("ECAD_Library", "Library", ("SWStyle_ECADLibrary",), "The model used for each package when a board is built.", None),
    ("ECAD_Options", "CircuitWorks Options", ("SWStyle_ECADOptions",),
     "What Build Model makes and what the CircuitWorks window shows.", "CircuitWorks\nOptions"),
    ("FC_AllTools", "All FreeCAD Tools", ("SWStyle_AllFreeCADTools",),
     "Every command of every installed FreeCAD workbench, by workbench and toolbar, without leaving this interface.",
     "All FreeCAD\nTools"),
    ("S3D_AllTools", "All Scan Tools", ("SWStyle_AllTools_Scan",), "Every Mesh, Points, Reverse Engineering and Inspection command.",
     "All\nTools"),
)

# Add-Ins tab: the stock workbenches the catalog's tab leaves out (key, label, workbench, caption)
MORE_WB = (
    ("WB_BIM", "BIM", "BIMWorkbench", None),
    ("WB_Material", "Material", "MaterialWorkbench", None),
    ("WB_Points", "Points", "PointsWorkbench", None),
    ("WB_Reen", "Reverse Engineering", "ReverseEngineeringWorkbench", "Reverse\nEngineering"),
    ("WB_Inspection", "Inspection", "InspectionWorkbench", None),
    ("WB_OpenSCAD", "OpenSCAD", "OpenSCADWorkbench", None),
    ("WB_Robot", "Robot", "RobotWorkbench", None),
    ("WB_Sketcher", "Sketcher", "SketcherWorkbench", None),
    ("WB_Test", "Test", "TestWorkbench", None),
)

# where the commands come from: (workbench, modules that register its commands, a command it has)
SOURCES = {
    "FEM": (("FemWorkbench", ("Fem", "FemGui", "femcommands.commands"), "FEM_Analysis"),),
    "CAM": (("CAMWorkbench", (), "CAM_Job"),),
    "CfdOF": (("CfdOFWorkbench", (), "CfdOF_Analysis"),),
    "Scan": (("MeshWorkbench", ("Mesh", "MeshGui"), "Mesh_Evaluation"),
             ("PointsWorkbench", ("Points", "PointsGui"), "Points_Convert"),
             ("ReverseEngineeringWorkbench", ("ReverseEngineering", "ReverseEngineeringGui"), "Reen_ApproxPlane"),
             ("InspectionWorkbench", ("Inspection", "InspectionGui"), "Inspection_VisualInspection"),
             ("PartWorkbench", ("PartGui",), "Part_ShapeFromMesh")),
}
PREFIXES = {"FEM": ("FEM_",), "CAM": ("CAM_", ), "CfdOF": ("CfdOF_",), "Scan": ("Mesh_", "Points_", "Reen_", "Inspection_")}
CFD_TAB = "Flow (CFD)"      # only on installs that have the CfdOF workbench (_install adds it, else it does not exist)
TAB_SOURCE = {"Simulation": "FEM", "Flow Simulation": "FEM", "CAM": "CAM", "ScanTo3D": "Scan", CFD_TAB: "CfdOF"}


def L(key, fly=None):
    return ("large", key, fly)


def ST(*keys):
    return ("stack", tuple((k, None) if isinstance(k, str) else k for k in keys))


SEP = ("sep",)

TABS = {

    "Simulation": (
        L("SIM_NewStudy", ("SIM_NewStudy", "SIM_Advisor", "SIM_Props", "SIM_Wizard", "SIM_Duplicate", "SIM_Analysis")),
        SEP,
        L("SIM_ApplyMaterial", ("SIM_ApplyMaterial", "SIM_MaterialNonlinear", "SIM_MaterialReinforced")),
        L("SIM_FixAdvisor", ("SIM_FixAdvisor", "SIM_Fixed", "SIM_Roller", "SIM_Hinge", "SIM_Elastic", "SIM_Rigid")),
        L("SIM_LoadAdvisor", ("SIM_LoadAdvisor", "SIM_BaseExcitation", "SIM_Force", "SIM_Torque", "SIM_Pressure", "SIM_Gravity", "SIM_Centrifugal", "SIM_Bearing",
                        "SIM_RemoteLoad", "SIM_DistributedMass",
                        "SIM_Temperature", "SIM_Convection", "SIM_HeatFlux", "SIM_BodyHeat", "SIM_Radiation",
                        "SIM_InitialTemp")),
        L("SIM_ThermalLoads", ("SIM_Temperature", "SIM_Convection", "SIM_HeatFlux", "SIM_BodyHeat", "SIM_Radiation",
                               "SIM_InitialTemp")),
        L("SIM_ConnAdvisor", ("SIM_ConnAdvisor", "SIM_Contact", "SIM_Bonded", "SIM_Interaction", "SIM_SpringConnector", "SIM_Pin", "SIM_Bolt",
                              "SIM_BearingConnector", "SIM_RigidConnector")),
        L("SIM_Shell", ("SIM_Shell", "SIM_Beam", "SIM_BeamRotation")),
        L("SIM_Diagnostic", ("SIM_MeshInfo", "SIM_Mesh", "SIM_MeshNetgen", "SIM_MeshControl", "SIM_MeshQuality", "SIM_MeshBoundary", "SIM_MeshClear")),
        L("SIM_Run", ("SIM_Run", "SIM_RunAll", "SIM_SolverCcx", "SIM_SolverElmer", "SIM_SolverZ88", "SIM_SolverMystran",
                      "SIM_SolverControl")),
        SEP,
        L("SIM_ResAdvisor", ("SIM_ResAdvisor", "SIM_Results", "SIM_Plot", "SIM_ApplyChanges", "SIM_Purge")),
        L("SIM_Deform"),
        L("SIM_Compare"),
        ST("SIM_IsoClip", ("SIM_PlotTools", ("SIM_Section", "SIM_Probe", "SIM_ListLine", "SIM_Linearized"))),
        SEP,
        ST("SIM_Report", "SIM_ReportImage"),
        SEP,
        L("SIM_AllTools"),
    ),

    "Flow Simulation": (
        ST("FLOW_Wizard", "FLOW_NewDefault", "FLOW_Clone"), L("FLOW_General"),
        ST("FLOW_Domain", ("FLOW_Project", ("FLOW_Project", "FLOW_Equation", "FLOW_Heat", "SIM_SolverElmer", "SIM_SolverControl"))),
        SEP,
        L("FLOW_Conditions", ("FLOW_Velocity", "FLOW_Pressure", "FLOW_InitVel", "FLOW_InitPress", "SIM_Temperature", "SIM_HeatFlux")),
        L("FLOW_Sources", ("SIM_BodyHeat", "SIM_Temperature")),
        SEP,
        L("FLOW_Mesh", ("SIM_Mesh", "SIM_MeshControl", "SIM_MeshBoundary", "SIM_MeshInfo")),
        SEP,
        L("SIM_Run"), L("FLOW_BatchRun"),
        SEP,
        L("FLOW_Results", ("SIM_Plot", "SIM_Results", "SIM_Purge")), L("SIM_Section", ("SIM_Section", "SIM_IsoClip")),
        L("SIM_Probe", ("SIM_Probe", "SIM_ListLine")), L("FLOW_Capture", ("FLOW_Capture", "SIM_ReportImage")),
        SEP,
        ST("Check", "FLOW_EngDB", ("FLOW_Tools", ("FLOW_Tools", "FLOW_Fluid"))),
        SEP,
        L("FLOW_AllTools"),
    ),
    CFD_TAB: (
        L("CFD_Analysis"), L("CFD_Physics"), L("CFD_Fluid"),
        SEP,
        L("CFD_Init", ("CFD_Init", "CFD_InitZone")), L("CFD_Boundary"), L("CFD_Porous"),
        SEP,
        L("CFD_Mesh", ("CFD_Mesh", "CFD_Refine")),
        SEP,
        L("CFD_Goals"), L("CFD_Solver"), L("CFD_Results"),
        SEP,
        L("CFD_AllTools"),
    ),
    "Analysis Preparation": (
        L("BossExtrude"), L("BossRevolve"),
        SEP,
        L("SplitLine"), L("SplitBody"), L("Intersect"),
        SEP,
        L("MidSurface"), L("Defeature"), ST("DeleteFace", "ExtendSurface", "ExtrudedSurface"),
        SEP,
        L("ReferenceGeometry", ("Plane", "Axis", "CoordinateSystem", "Point")),
    ),

    "CAM": (
        L("CAM_Machine"), ST("CoordinateSystem", "CAM_Stock", ("CAM_Setup", ("CAM_Setup", "CAM_ToolController"))),
        SEP,
        L("CAM_Generate"), L("CAM_Simulate", ("CAM_Simulate", "CAM_SimulateOld")), ST("CAM_Inspect", "CAM_Sanity"),
        L("CAM_Post"),
        SEP,
        L("CAM_Sort", ("CAM_Sort", "CAM_Active", "CAM_Copy", "CAM_Array")),
        SEP,
        L("CAM_Profile", ("CAM_Profile", "CAM_Pocket", "CAM_Face", "CAM_Adaptive", "CAM_Helix", "CAM_Slot",
                          "CAM_Engrave", "CAM_Vcarve", "CAM_Deburr")),
        L("CAM_Drill", ("CAM_Drill", "CAM_Thread", "CAM_Tapping")),
        L("CAM_Surface", ("CAM_Surface", "CAM_Waterline", "CAM_Pocket3D")),
        L("CAM_Dogbone", ("CAM_Dogbone", "CAM_Tag", "CAM_LeadInOut", "CAM_Ramp", "CAM_Boundary")),
        L("CAM_Probe"),
        SEP,
        ST("CAM_Tools", "CAM_ToolDock"),
        SEP,
        L("CAM_Options"), L("CAM_AllTools"),
    ),
    "ScanTo3D": (
        L("S3D_ImportMesh", ("S3D_ImportMesh", "S3D_ImportPoints")),
        L("S3D_Prep", ("S3D_Prep", "S3D_Normals", "S3D_FillHoles", "S3D_RemoveParts", "S3D_Smooth", "S3D_Decimate",
                       "S3D_Scale", "S3D_Trim")),
        ST("S3D_ToPoints", "S3D_PointsStructure", ("S3D_PointsMerge", ("S3D_PointsMerge", "S3D_PointsCut"))),
        SEP,
        L("S3D_Segment", ("S3D_Segment", "S3D_SegmentFit", "S3D_SegmentManual")),
        L("S3D_Surface", ("S3D_Surface", "S3D_Plane", "S3D_Cylinder", "S3D_Sphere", "S3D_Poisson", "S3D_Triangulate")),
        L("S3D_ToBody"), L("S3D_Curves", ("S3D_Curves", "S3D_Section", "S3D_Boundary")),
        SEP,
        L("S3D_Deviation", ("S3D_Deviation", "S3D_InspectPoint")), L("S3D_Curvature"),
        SEP,
        L("S3D_AllTools"),
    ),
}
TABS["CircuitWorks"] = (L("ECAD_Open"), L("ECAD_Export"), L("ECAD_Update"), SEP, L("ECAD_Library"), L("ECAD_Options"),
                        SEP, L("Interference"), L("Measure"))




# feature tools, made of the Sketch and Features tabs' own buttons; Interface's read of Ati's tab will adjust it.
BASIC_TITLE = "Basic Modeling Tools"
BASIC = (
    ("large", "Sketch", ("Sketch", "Sketch3D", "EditSketch")),
    ("large", "SmartDimension", None),
    ("sep",),
    ("grid", (
        (("Line", ("Line", "Centerline", "MidpointLine")), ("Circle", ("Circle", "PerimeterCircle")),
         ("Slot", ("Slot", "CenterpointSlot", "ThreePointArcSlot", "ArcSlot"))),
        (("CornerRectangle", ("CornerRectangle", "CenterRectangle", "ThreePointCornerRectangle",
                              "ThreePointCenterRectangle", "Parallelogram")),
         ("CenterArc", ("CenterArc", "TangentArc", "ThreePointArc")), ("Polygon", None)),
    )),
    ("large", "Trim", ("Trim", "Extend")),
    ("stack", (("Convert", None), ("Offset", None), ("MirrorEntities", None))),
    ("sep",),
    ("large", "BossExtrude", None),
    ("large", "BossRevolve", None),
    ("large", "CutExtrude", None),
    ("large", "CutRevolve", None),
    ("large", "Hole", ("Hole", "SimpleHole")),
    ("sep",),
    ("large", "Fillet", ("Fillet", "Chamfer")),
    ("stack", (("Shell", None), ("Draft", None), ("Rib", None))),
    ("large", "LinearPattern", ("LinearPattern", "CircularPattern")),
    ("large", "Mirror", None),
    ("sep",),
    ("large", "ReferenceGeometry", ("Plane", "Axis", "CoordinateSystem", "Point")),
    ("large", "Measure", None),
)


ORDER = ("Simulation", "CAM", "Analysis Preparation", "CircuitWorks", "Flow Simulation", CFD_TAB, "ScanTo3D")
DEFAULT_HIDDEN = ("ScanTo3D",)


# ===================================================================== loading the workbenches
_loaded = set()


def _has(name):
    try:
        return Gui.Command.get(name) is not None
    except Exception:
        return False


def _editing():
    try:
        if Gui.Control.activeDialog():
            return True
    except Exception as _fw_err:
        _fw_log("addintabs.py:415", _fw_err)
    try:
        return bool(Gui.ActiveDocument and Gui.ActiveDocument.getInEdit())
    except Exception as _fw_err:
        _fw_log("addintabs.py:424", _fw_err)
        return False


def load(source):
    """Makes the commands of a tab's workbenches exist. True when anything new came in."""
    if Gui is None or source in _loaded:
        return False
    import importlib
    changed = False
    pending = False
    for wb, modules, probe in SOURCES.get(source, ()):
        if _has(probe):
            continue
        for mod in modules:
            try:
                importlib.import_module(mod)
            except Exception as _fw_err:
                _fw_log("addintabs.py:436", _fw_err)
        if not _has(probe) and wb in Gui.listWorkbenches():
            if _editing():
                pending = True       # never switch workbench under a sketch or a task: next time
                continue
            try:
                current = Gui.activeWorkbench().name()
            except Exception:
                current = "PartDesignWorkbench"
            try:
                Gui.activateWorkbench(wb)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: %s did not load (%s)\n" % (wb, error))
            try:
                Gui.activateWorkbench(current if current not in ("", "NoneWorkbench") else "PartDesignWorkbench")
            except Exception as _fw_err:
                _fw_log("addintabs.py:452", _fw_err)
        changed = changed or _has(probe)
    if not pending:
        _loaded.add(source)
    return changed


def _refresh_buttons():
    sh = _shell()
    if sh is None:
        return
    for b in list(getattr(sh, "bindings", {}).values()):
        try:
            b.resolve()
            b.update_state()
        except Exception as _fw_err:
            _fw_log("addintabs.py:468", _fw_err)
    try:
        page = sh.topbar.current_page()
        if page is not None:
            page.update()
            for b in page.buttons():
                b.update()
    except Exception as _fw_err:
        _fw_log("addintabs.py:476", _fw_err)


MINE = tuple(k[0] for k in KEYS)


def _alive(key):
    """False for one of our buttons whose FreeCAD command this install does not have."""
    if key not in MINE:
        return True
    from . import catalog
    cmd = catalog.BY_KEY.get(key)
    return cmd is not None and any(_has(n) for n in cmd.natives)


def _prune(layout):
    out = []
    for item in layout:
        if item[0] == "large":
            fly = tuple(k for k in (item[2] or ()) if _alive(k)) or None
            key = item[1] if _alive(item[1]) else (fly[0] if fly else None)
            if key:
                out.append(("large", key, fly if fly and len(fly) > 1 else None))
        elif item[0] == "stack":
            rows = []
            for key, fly in item[1]:
                fly = tuple(k for k in (fly or ()) if _alive(k)) or None
                key = key if _alive(key) else (fly[0] if fly else None)
                if key:
                    rows.append((key, fly if fly and len(fly) > 1 else None))
            if rows:
                out.append(("stack", tuple(rows)))
        elif out and out[-1][0] != "sep":
            out.append(item)
    while out and out[-1][0] == "sep":
        out.pop()
    return tuple(out)


def _after_load(source, shown_title):
    """Loads the source's workbenches; then drops the buttons this install has no command for
    (no dead controls) and rebuilds the CommandManager on the same tab."""
    load(source)
    if source not in _loaded:
        _refresh_buttons()
        return
    from . import cmtabs
    redo = []
    for title, src in TAB_SOURCE.items():
        if src != source or title not in cmtabs.TABS:
            continue
        new = _prune(TABS[title])
        if new != tuple(cmtabs.TABS.get(title, ())):
            cmtabs.TABS[title] = new
            redo.append(title)
    if not redo:
        _refresh_buttons()
        return
    from . import catalog
    cmtabs._ALL_TABS[:] = [t for t in cmtabs._ALL_TABS if t[0] not in redo]
    catalog.TABS = tuple(t for t in catalog.TABS if t[0] not in redo)
    cmtabs.apply(rebuild=True)
    sh = _shell()
    try:
        titles = [p.title for p in sh.topbar.pages]
        if shown_title in titles:
            sh.topbar.tabs.set_current(titles.index(shown_title))
    except Exception as _fw_err:
        _fw_log("addintabs.py:544", _fw_err)
    _refresh_buttons()


def _shell():
    try:
        from . import swmenus
        return swmenus._shell()
    except Exception as _fw_err:
        _fw_log("addintabs.py:559", _fw_err)
        return None


ASM_ADDINS = ("Simulation", "CAM")


def _hook_assembly_tabs():
    ""
    from . import asmtabs
    if getattr(asmtabs.every_tab, "_fw_addins", False):
        return
    order = list(asmtabs.ORDER)
    if "Simulation" not in order:
        order.insert(order.index("MBD") if "MBD" in order else len(order), "Simulation")
    if "CAM" not in order:
        order.append("CAM")
    asmtabs.ORDER = tuple(order)
    original = asmtabs.every_tab

    def every_tab(part_tabs):
        from . import cmtabs
        tabs = dict(original(part_tabs))
        for t in ASM_ADDINS:
            if t in cmtabs.TABS:
                tabs[t] = cmtabs.TABS[t]
        return [(t, tabs[t]) for t in asmtabs.ORDER if t in tabs]

    every_tab._fw_addins = True
    asmtabs.every_tab = every_tab


def idf_staged(path):
    """(problem, board path for FreeCAD's IDF importer). The importer reads the component file only as <name>.emp next
    to a board named <name>.emn (lower case), so the board and its .emp / .lib (any case) are copied to a temporary
    folder under those names. problem is a plain message when the file is not an IDF board."""
    import shutil, tempfile
    try:
        with open(path, "r", errors="replace") as f:
            head = f.read(4096)
    except OSError as error:
        return "The file could not be opened: %s" % error, None
    if ".HEADER" not in head.upper() or not any(w in head.upper() for w in ("BOARD_FILE", "PANEL_FILE")):
        return "This is not an IDF board file (.emn, .brd, .bdf or .idb from the ECAD program's IDF export).", None
    folder, name = os.path.split(path)
    stem = os.path.splitext(name)[0]
    lib = None
    for other in sorted(os.listdir(folder or ".")):
        o_stem, o_ext = os.path.splitext(other)
        if o_stem.lower() == stem.lower() and o_ext.lower() in (".emp", ".lib", ".ldf"):
            lib = os.path.join(folder, other)
            break
    if lib is None:
        return ("The board's component file (%s.emp) is not next to it: export both files of the IDF from the ECAD "
                "program into one folder." % stem), None
    if name.endswith(".emn") and lib == os.path.join(folder, stem + ".emp"):
        return None, path
    tmp = tempfile.mkdtemp(prefix="fw_idf_")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem) or "board"
    shutil.copyfile(path, os.path.join(tmp, safe + ".emn"))
    shutil.copyfile(lib, os.path.join(tmp, safe + ".emp"))
    return None, os.path.join(tmp, safe + ".emn")


def _hook_page_shown():
    from . import shell as shell_mod
    cls = shell_mod.Shell
    if getattr(cls.page_shown, "_fw_addins", False):
        return
    original = cls.page_shown

    def page_shown(self, page):
        source = TAB_SOURCE.get(getattr(page, "title", ""))
        if source and source not in _loaded:
            # after the click: the tab shows first, then its workbench loads and its buttons light up
            QtCore.QTimer.singleShot(0, lambda: _after_load(source, page.title))
        return original(self, page)

    page_shown._fw_addins = True
    cls.page_shown = page_shown


# ===================================================================== commands
def _doc():
    return App.ActiveDocument


def _main_solid(doc):
    try:
        from . import evaltools
        obj = evaltools._main(doc)
        if obj is not None:
            return obj
    except Exception as _fw_err:
        _fw_log("addintabs.py:614", _fw_err)
    sel = [o for o in Gui.Selection.getSelection() if hasattr(o, "Shape") and o.Shape.Solids]
    if sel:
        return sel[0]
    solids = [o for o in doc.Objects if hasattr(o, "Shape") and o.Shape.Solids and o.isDerivedFrom("PartDesign::Body")]
    solids = solids or [o for o in doc.Objects if hasattr(o, "Shape") and o.Shape.Solids and not o.InList]
    return solids[0] if solids else None


def _steel():
    try:
        from . import evaltools
        dens, _y, e_mpa, nu = evaltools.MATERIALS["Plain Carbon Steel"][:4]
    except Exception:
        dens, e_mpa, nu = 7800, 210000, 0.28
    return {"Name": "Plain Carbon Steel", "YoungsModulus": "%g MPa" % e_mpa, "PoissonRatio": str(nu),
            "Density": "%g kg/m^3" % dens, "ThermalConductivity": "43 W/m/K",
            "ThermalExpansionCoefficient": "1.3e-05 m/m/K", "SpecificHeat": "440 J/kg/K",

            "YieldStrength": "220.594 MPa", "UltimateTensileStrength": "399.826 MPa"}


def _set_active(analysis):
    try:
        import FemGui
        FemGui.setActiveAnalysis(analysis)
    except Exception as _fw_err:
        _fw_log("addintabs.py:639", _fw_err)
    try:
        from . import simplots
        shown = simplots.SHOWN.get("a")
        if shown is not None and shown is not analysis:
            simplots.clear()
    except Exception as _fw_err:
        _fw_log("addintabs.py:set_active clear plot", _fw_err)


def _active_analysis(doc):
    try:
        import FemGui
        a = FemGui.getActiveAnalysis()
        if a is not None and a.Document == doc:
            return a
    except Exception as _fw_err:
        _fw_log("addintabs.py:649", _fw_err)
    for o in Gui.Selection.getSelection():
        if o.isDerivedFrom("Fem::FemAnalysis"):
            return o
        for parent in o.InList:
            if parent.isDerivedFrom("Fem::FemAnalysis"):
                return parent
    found = [o for o in doc.Objects if o.isDerivedFrom("Fem::FemAnalysis")]
    return found[-1] if found else None


def _gmsh(doc, obj, analysis, second_order=True):
    import ObjectsFem
    mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
    mesh.Shape = obj
    if second_order:
        from . import simxpress
        simxpress.high_quality(mesh)
    try:
        mesh.CharacteristicLengthMax = "%g mm" % max(obj.Shape.BoundBox.DiagonalLength / 25.0, 0.5)
    except Exception as _fw_err:
        _fw_log("addintabs.py:667", _fw_err)
    try:
        # a Standard mesh as the Mesh PM writes it (Automatic transition off): sizes from the global size alone,
        # not FreeCAD's 12 elements per circle, which made 4x the nodes on parts with many small holes
        mesh.CharacteristicLengthMin = "0 mm"
        mesh.MeshSizeFromCurvature = 0
    except Exception as _fw_err:
        _fw_log("addintabs.py:_gmsh standard", _fw_err)
    analysis.addObject(mesh)
    return mesh


STUDIES = (("Static", "static"), ("Frequency", "frequency"), ("Buckling", "buckling"),
           ("Thermal", "thermomech"), ("Check (no solve)", "check"))


def new_study(doc, obj, kind="static", name=None):
    """A CalculiX study on obj: analysis, solver of that kind, steel, Gmsh mesh. Returns the analysis."""
    import ObjectsFem
    analysis = ObjectsFem.makeAnalysis(doc, "Study")
    analysis.Label = name or "%s 1" % dict((v, k) for k, v in STUDIES).get(kind, "Static")
    maker = getattr(ObjectsFem, "makeSolverCalculiXCcxTools", None) or getattr(ObjectsFem, "makeSolverCalculiX")
    solver = maker(doc, "Solver")
    try:
        if kind in solver.getEnumerationsOfProperty("AnalysisType"):
            solver.AnalysisType = kind
    except Exception as _fw_err:
        _fw_log("addintabs.py:687", _fw_err)
    try:
        from . import simstudy
        simstudy.apply_defaults(solver, kind)       # Frequency 5 modes, Buckling 1 mode, Thermal steady state
    except Exception as error:
        App.Console.PrintLog("FreeCAD: study defaults not set (%s)\n" % error)
    analysis.addObject(solver)
    mat = ObjectsFem.makeMaterialSolid(doc, "Material")
    mat.Material = _steel()
    analysis.addObject(mat)
    try:
        from . import simmaterial
        if not simmaterial.from_part(analysis):
            # no material on the part: the study's default steel goes on the part too, so the FeatureManager's
            # Material row and the study's part row name the same material (look-audit M6)
            from . import materialdlg
            found = materialdlg.find("Plain Carbon Steel")
            if found is not None and doc.getObject(getattr(obj, "Name", "")) is not None:
                materialdlg.give_part(doc, found[2])
    except Exception as _fw_err:
        _fw_log("addintabs.py:frompart", _fw_err)
    try:
        from . import simstudy
        simstudy.after_new(doc, analysis, kind)     # a thermal study's initial temperature
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: study extras not added (%s)\n" % error)
    if obj is not None:
        _gmsh(doc, obj, analysis)
    doc.recompute()
    return analysis


AIR = {"Name": "Air", "Density": "1.204 kg/m^3", "DynamicViscosity": "1.81e-05 Pa*s",
       "KinematicViscosity": "15.11 mm^2/s", "ThermalConductivity": "0.0262 W/m/K", "SpecificHeat": "1006 J/kg/K",
       "SpecificHeatRatio": "1.4", "ThermalExpansionCoefficient": "0.00343 m/m/K"}
WATER = {"Name": "Water", "Density": "998 kg/m^3", "DynamicViscosity": "1.002e-03 Pa*s",
         "KinematicViscosity": "1.004 mm^2/s", "ThermalConductivity": "0.598 W/m/K", "SpecificHeat": "4182 J/kg/K",
         "ThermalExpansionCoefficient": "0.000207 m/m/K"}


def new_flow(doc, obj, fluid="Air"):
    """An Elmer flow project on obj (the fluid region): analysis, solver + flow equation, fluid, mesh."""
    import ObjectsFem
    analysis = ObjectsFem.makeAnalysis(doc, "FlowProject")
    analysis.Label = "Flow 1"
    solver = ObjectsFem.makeSolverElmer(doc, "SolverElmer")
    analysis.addObject(solver)
    try:
        eq = ObjectsFem.makeEquationFlow(doc, solver)
        if eq is not None and eq not in solver.Group:
            solver.addObject(eq)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: flow equation not added (%s)\n" % error)
    mat = ObjectsFem.makeMaterialFluid(doc, "Fluid")
    mat.Material = dict(WATER if fluid == "Water" else AIR)
    analysis.addObject(mat)
    if obj is not None:
        _gmsh(doc, obj, analysis, second_order=False)      # the flow solver keeps first-order cells
    doc.recompute()
    return analysis


def _solver(analysis):
    for o in analysis.Group:
        if o.isDerivedFrom("Fem::FemSolverObjectPython") or o.isDerivedFrom("Fem::FemSolverObject"):
            return o
    return None


MESH_SIG = "FwMeshGeometry"


def geometry_signature(m):
    """What the mesh was made from: the meshed shape's volume, area, box and face/edge counts (rounded)."""
    try:
        sh = m.Shape.Shape
        bb = sh.BoundBox
        vals = (sh.Volume, sh.Area, bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)
        return "%d/%d/" % (len(sh.Faces), len(sh.Edges)) + "/".join("%.4g" % v for v in vals)
    except Exception:
        return ""


def mark_meshed(m):
    """Remember the geometry a mesh was made from (Run remeshes once the part has changed since)."""
    try:
        if MESH_SIG not in m.PropertiesList:
            m.addProperty("App::PropertyString", MESH_SIG, "Base", "The geometry this mesh was made from")
            m.setEditorMode(MESH_SIG, 2)
        m.FwMeshGeometry = "%s|%d" % (geometry_signature(m), m.FemMesh.NodeCount)
    except Exception as _fw_err:
        _fw_log("addintabs.py:markmesh", _fw_err)


def mesh_out_of_date(m):
    ""

    try:
        sig, _sep, nodes = (getattr(m, MESH_SIG, "") or "").rpartition("|")
        if sig and nodes == str(m.FemMesh.NodeCount):
            return sig != geometry_signature(m)
        mb, pb = m.FemMesh.BoundBox, m.Shape.Shape.BoundBox
        tol = max(1e-3 * pb.DiagonalLength, 1e-4)
        return any(abs(x - y) > tol for x, y in ((mb.XMin, pb.XMin), (mb.YMin, pb.YMin), (mb.ZMin, pb.ZMin),
                                                  (mb.XMax, pb.XMax), (mb.YMax, pb.YMax), (mb.ZMax, pb.ZMax)))
    except Exception:
        return False


def _ensure_mesh(analysis):
    for m in analysis.Group:
        if getattr(getattr(m, "Proxy", None), "Type", "") == "Fem::FemMeshGmsh":
            try:
                empty = not m.FemMesh.Nodes
            except Exception:
                empty = True
            stale = not empty and mesh_out_of_date(m)
            if empty or stale:
                part = getattr(m, "Shape", None)
                try:
                    nothing = part is None or part.Shape.isNull() or not (part.Shape.Solids or part.Shape.Faces)
                except Exception:
                    nothing = True
                if nothing:
                    # Gmsh's own words here are "cannot determine type of null shape"
                    raise RuntimeError("%s has no geometry to mesh. Fix the part's failed features, then run again."
                                       % getattr(part, "Label", "The part"))
                if stale:
                    App.Console.PrintMessage("FreeCAD: %s changed since it was meshed: meshing it again.\n"
                                             % getattr(getattr(m, "Shape", None), "Label", "The part"))
                from . import simrun
                t0 = time.time()
                simrun.mesh(m)                       # Gmsh with the run window live
                mark_meshed(m)
                try:                                 # Mesh Details' "Time to complete mesh" (rcmenus simmeshinfo)
                    from . import simmeshinfo
                    simmeshinfo.TIMES[m.Name] = time.time() - t0
                except Exception:
                    pass


def zero_result(analysis):
    """True when a static study with loads came out with no displacement anywhere (the loads reached no node)."""
    try:
        res = [o for o in analysis.Group if o.isDerivedFrom("Fem::FemResultObject")]
        loads = [o for o in analysis.Group if any(t in o.TypeId + getattr(getattr(o, "Proxy", None), "Type", "")
                                                  for t in ("ConstraintForce", "ConstraintPressure", "ConstraintSelfWeight"))]
        if not res or not loads:
            return False
        d = list(res[-1].DisplacementLengths or [])
        return bool(d) and max(abs(v) for v in d) == 0.0
    except Exception:
        return False


def no_loads_result(analysis):
    """True when a static study with no external load at all came out with no displacement anywhere: the run
    finished with an all-zero plot and nothing said why."""
    try:
        from . import simtypes
        if simtypes.study_type(analysis) != "static":
            return False
        res = [o for o in analysis.Group if o.isDerivedFrom("Fem::FemResultObject")]
        if not res:
            return False
        d = list(res[-1].DisplacementLengths or [])
        return bool(d) and max(abs(v) for v in d) == 0.0 and not zero_result(analysis)
    except Exception:
        return False


def _number(value):
    try:
        return float(getattr(value, "Value", value) or 0.0)
    except Exception:
        return 0.0


def buckling_factors(analysis):
    """The buckling load factors CalculiX wrote (its .dat text, kept in the study as ccx_dat_file), in mode order."""
    import re
    for o in reversed(analysis.Group if analysis is not None else ()):
        text = getattr(o, "Text", None)
        if not isinstance(text, str) or "B U C K L I N G" not in text:
            continue
        block = text.split("B U C K L I N G", 1)[1].split("E I G E N V A L U E", 1)[0]
        sign = -1.0 if getattr(analysis, BUCKLING_SIGN, 1) == -1 else 1.0
        return [sign * float(n) for n in re.findall(r"^\s*\d+\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*$", block, re.M)]
    return []


def study_summary(solver, res, analysis=None):
    """What Run This Study reports, by study type: natural frequencies, buckling load factors, temperatures, or the
    largest stress and displacement (of the last step)."""
    import re
    kind = str(getattr(solver, "AnalysisType", "static"))
    if kind == "frequency":
        modes = sorted((int(_number(getattr(r, "Eigenmode", 0))), _number(getattr(r, "EigenmodeFrequency", 0.0))) for r in res)
        modes = [m for m in modes if m[0] > 0]
        try:
            from . import simtypes as _st
            if analysis is not None:
                have = {m[0] for m in modes}
                modes = sorted(modes + [(n, 0.0) for n in _st.rigid_modes(analysis) if n not in have])
        except Exception as _fw_err:
            _fw_log("addintabs.py:rigid", _fw_err)
        if modes:
            return "Natural frequencies:\n" + "\n".join("Mode %d: %.5g Hz" % m for m in modes[:12])
    if kind == "buckling":
        factors = buckling_factors(analysis)
        if factors:
            lines = ["Buckling load factors:"] + ["Mode %d: %.5g" % (n, f) for n, f in enumerate(factors[:12], 1)]
            positive = [f for f in factors if f > 0]
            if positive:
                lowest = min(positive)
                lines.append("The part buckles at %.4g times the applied loads%s."
                             % (lowest, ": it buckles under them" if lowest < 1 else ""))
            else:
                lines.append("Every factor is negative: the part buckles only if the loads are reversed.")
            return "\n".join(lines)
    r = res[-1]
    lines = []
    temps = list(getattr(r, "Temperature", None) or [])
    if kind == "thermomech" and temps:
        lines.append("Temperature: %.4g K to %.4g K" % (min(temps), max(temps)))
    vm = max(r.vonMises) if getattr(r, "vonMises", None) else 0.0
    disp = max(r.DisplacementLengths) if getattr(r, "DisplacementLengths", None) else 0.0
    if not lines or vm > 0.0 or disp > 0.0:
        if _inch_units(analysis):
            lines.append("Max von Mises stress: %.4g psi" % (vm * 145.0377))
            lines.append("Max displacement: %.4g in" % (disp / 25.4))
        else:
            lines.append("Max von Mises stress: %.4g MPa" % vm)
            lines.append("Max displacement: %.4g mm" % disp)
    return "\n".join(lines)


def _inch_units(analysis):
    """True when the study's document works in inches or feet (its own unit system, else FreeCAD's)."""
    try:
        doc = analysis.Document if analysis is not None else App.ActiveDocument
        schema = None
        if doc is not None and hasattr(doc, "UnitSystem"):
            schema = doc.getEnumerationsOfProperty("UnitSystem").index(doc.UnitSystem)
        if schema is None:
            schema = App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("UserSchema", 0)
        from . import unitspage
        return unitspage.SCHEMA_LENGTH.get(schema, "millimeters") in ("inches", "feet", "feet & inches")
    except Exception as _fw_err:
        _fw_log("addintabs.py:inch_units", _fw_err)
        return False


def _need_program(solver_name, label):
    """Says so (RuntimeError, shown as a message) when the solver program is not set in the FEM preferences nor on PATH;
    when FreeCAD cannot tell, the solver run is left to say it."""
    try:
        import shutil
        from femsolver import settings
        path = settings.get_binary(solver_name, silent=True)
    except Exception as _fw_err:
        _fw_log("addintabs.py:831", _fw_err)
        return
    if not path:
        # FreeCAD gives no path when the program is neither set nor on PATH: its own run then only writes
        # "The binary has not been found" in the Report view and nothing happens on screen
        raise RuntimeError("%s is not installed. Install it, or set its path in Edit > Preferences > FEM > %s."
                           % (label, label))
    if not (os.path.isfile(path) or shutil.which(path)):
        raise RuntimeError("%s was not found (%s). Install it, or set its path in Edit > Preferences > FEM > %s."
                           % (label, path, label))


# FreeCAD's check_prerequisites lines, in the study's own words (the rest are shown as FreeCAD wrote them)
PREREQUISITES = (
    ("No mechanical boundary conditions", "The part is not held: add a fixture (Fixtures in the study tree, or the "
                                          "Fixtures Advisor), then run again."),
    ("No material object defined", "No material is applied to the part: right-click the part in the study tree, "
                                   "Apply/Edit Material..., then run again."),
    ("No YoungsModulus defined", "The material has no Elastic Modulus: edit the material and enter it, then run again."),
    ("No PoissonRatio defined", "The material has no Poisson's Ratio: edit the material and enter it, then run again."),
    ("FEM mesh has no volume elements", "The mesh has no solid elements: a surface needs a shell thickness. Study a "
                                        "solid body, or give the surface a thickness, then run again."),
)


def plain_prerequisites(message):
    """check_prerequisites' message, each line said once in the study's words."""
    out = []
    for line in str(message).splitlines():
        line = line.strip()
        if not line:
            continue
        said = next((text for key, text in PREREQUISITES if key in line), line)
        if said not in out:
            out.append(said)
    return "\n".join(out)


_CCX_OK = {}


def ccx_ready():
    """CalculiX as FreeCAD's setup_ccx finds it (the FEM preference's path, else ccx on PATH), checked once per file:
    raises ONE plain message when it is missing or is another program. FreeCAD's own check shows two "wrong ccx
    binary" boxes and a "not found" box for a program that is not CalculiX, then the run says nothing ran."""
    import shutil, subprocess
    path = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Fem/Ccx").GetString("ccxBinaryPath", "")
    found = shutil.which(path) if path else shutil.which("ccx")
    where = "Edit > Preferences > FEM > CalculiX"
    if not found:
        raise RuntimeError("CalculiX was not found%s. Install it, or set its path in %s."
                           % (" (%s)" % path if path else "", where))
    try:
        key = (found, os.path.getmtime(found))
    except OSError:
        key = (found, None)
    if _CCX_OK.get(key):
        return found
    try:
        kw = {}
        try:
            import femtools.femutils as fu
            kw["startupinfo"] = fu.startProgramInfo("")
        except Exception as _fw_err:
            _fw_log("addintabs.py:ccxinfo", _fw_err)
        p = subprocess.run([found], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                           timeout=30, **kw)
        said = (p.stdout or b"") + (p.stderr or b"")
    except Exception as error:
        raise RuntimeError("CalculiX (%s) could not be started: %s. Set its path in %s." % (found, error, where))
    if b"CalculiX" not in said:
        raise RuntimeError("The program set as CalculiX (%s) is not CalculiX. Set CalculiX's path in %s."
                           % (found, where))
    _CCX_OK[key] = True
    return found


def _safe_icon(pixmap):
    """Gui.getIcon without FreeCAD's "Cannot find icon" line for a workbench's icon not loaded yet (FEM's, before
    the FEM workbench has been opened): a bare name is looked up in the resources first."""
    from PySide import QtCore, QtGui
    if pixmap and pixmap.startswith("FEM_") and "/" not in pixmap and "\\" not in pixmap:   # FemGui's resources
        if not any(QtCore.QFile.exists(":/icons/%s%s" % (pixmap, ext)) for ext in (".svg", ".png", "")):
            return QtGui.QIcon()
    return Gui.getIcon(pixmap)


def run_study(analysis):
    """Meshes when needed and runs the study. Returns a summary text for CalculiX, else None. The run window
    (simrun) shows while it meshes and solves; Cancel there raises simrun.Cancelled."""
    from . import simrun
    simrun.begin(analysis)
    try:
        said = _run_study(analysis)
        said = _buckling_pull(analysis, said)
        try:                                      # what this run solved: a later change marks the study "*" (simlook)
            from . import simpressure
            simpressure.stamp(analysis)
        except Exception as _fw_err:
            _fw_log("addintabs.py:stamp", _fw_err)
        return said
    finally:
        simrun.end()


LARGE_DISP = ("Excessive displacements were calculated in this model. If your system is properly restrained, "
              "consider using the Large Displacement option to improve the accuracy of the calculations.\n\n"
              "Otherwise, continue with current settings and review the causes of these displacements.\n\n"
              "Click 'Yes' to solve with the Large displacement flag activated. Click 'No' to solve with small "
              "displacement. Click Cancel to end the solution.")


def excessive(a, share=0.02):
    ""

    try:
        from . import simtypes, simplots
        if simtypes.study_type(a) != "static":
            return False
        s = _solver(a)
        if s is None or getattr(s, "GeometricalNonlinearity", "linear") == "nonlinear":
            return False
        r = simplots.result(a)
        if r is None or not getattr(r, "DisplacementLengths", None):
            return False
        bb = r.Mesh.FemMesh.BoundBox
        return max(r.DisplacementLengths) > share * bb.DiagonalLength
    except Exception as _fw_err:
        _fw_log("addintabs.py:excessive", _fw_err)
        return False


def _large_displacement(a, text):
    ""


    if not excessive(a):
        return text
    box = QtWidgets.QMessageBox
    answer = box.question(Gui.getMainWindow(), "Simulation", LARGE_DISP, box.Yes | box.No | box.Cancel, box.No)
    if answer == box.Yes:
        from . import simtypes
        s = _solver(a)
        s.GeometricalNonlinearity = "nonlinear"
        try:                                    # the study's Properties follow (Use large displacement formulation)
            if hasattr(simtypes, "set_large_displacement"):
                simtypes.set_large_displacement(a, True)
        except Exception as _fw_err:
            _fw_log("addintabs.py:large flag", _fw_err)
        a.Document.recompute()
        return run_study(a)
    if answer == box.Cancel:
        for o in [o for o in a.Group if o.isDerivedFrom("Fem::FemResultObject")]:
            a.removeObject(o)
            a.Document.removeObject(o.Name)
        try:
            from . import simplots
            simplots.clear()
        except Exception:
            pass
        a.Document.recompute()
        Gui.getMainWindow().statusBar().showMessage("%s: solution ended, no results." % a.Label, 8000)
        return False
    return text


BUCKLING_SIGN = "FwBucklingSign"


def _flip_loads(analysis):
    """Every load of the study the other way (Force and Pressure Reversed, Gravity's direction)."""
    for o in analysis.Group:
        if o.TypeId in ("Fem::ConstraintForce", "Fem::ConstraintPressure") and "Reversed" in o.PropertiesList:
            o.Reversed = not o.Reversed
        elif getattr(getattr(o, "Proxy", None), "Type", "") == "Fem::ConstraintSelfWeight":
            for k in ("GravityDirection",):
                if k in o.PropertiesList:
                    v = getattr(o, k)
                    setattr(o, k, App.Vector(-v.x, -v.y, -v.z))


def _buckling_pull(analysis, said):
    ""


    try:
        from . import simtypes
        if simtypes.study_type(analysis) != "buckling":
            return said
    except Exception:
        return said
    _set_sign(analysis, 1)
    factors = buckling_factors(analysis)
    if not factors or any(f > 0 for f in factors):
        return said
    from . import simrun
    simrun.say("The loads pull: solving again with them reversed for the buckling load factors.")
    _flip_loads(analysis)
    try:
        analysis.Document.recompute()
        said = _run_study(analysis)
    finally:
        _flip_loads(analysis)
        analysis.Document.recompute()
    _set_sign(analysis, -1)
    solver, res = _solver(analysis), [o for o in analysis.Group if o.isDerivedFrom("Fem::FemResultObject")]
    return study_summary(solver, res, analysis) if res else said


def _set_sign(analysis, sign):
    try:
        if BUCKLING_SIGN not in analysis.PropertiesList:
            analysis.addProperty("App::PropertyInteger", BUCKLING_SIGN, "FreeWorks", "-1: the factors are of the reversed loads")
            analysis.setEditorMode(BUCKLING_SIGN, 2)
        setattr(analysis, BUCKLING_SIGN, sign)
    except Exception as _fw_err:
        _fw_log("addintabs.py:buckling sign", _fw_err)


def _run_study(analysis):
    from . import simrun
    doc = analysis.Document
    solver = _solver(analysis)
    if solver is None:
        raise RuntimeError("The study has no solver: add one from the Run This Study arrow.")
    _ensure_mesh(analysis)
    doc.recompute()
    if getattr(getattr(solver, "Proxy", None), "Type", "") == "Fem::SolverCcxTools":
        ccx_ready()
        from femtools import ccxtools
        fea = ccxtools.FemToolsCcx(analysis, solver)
        fea.update_objects()
        fea.setup_working_dir()
        fea.setup_ccx()
        message = fea.check_prerequisites()
        if message:
            raise RuntimeError(plain_prerequisites(message))
        fea.purge_results()
        simrun.stage("Writing the input file")
        fea.write_inp_file()
        try:                                         # cyclic symmetry fixtures (PM pkg355): no fixture on a tie's dependent nodes
            from . import simpms
            if hasattr(simpms, "cyclic_inp"):
                simpms.cyclic_inp(fea, analysis)
        except Exception as _fw_err:
            _fw_log("addintabs.py:cyclic", _fw_err)
        from . import simxpress
        simxpress.solver_stopped(fea, simxpress.run_ccx(fea))
        simrun.stage("Reading the results")
        fea.load_results()
        simrun.stage("Reading the results", 100)
        res = [o for o in analysis.Group if o.isDerivedFrom("Fem::FemResultObject")]
        if not res:
            raise RuntimeError("The solver gave no result.")
        r = res[-1]
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(r)
        # FreeCAD 1.1 makes the result pipeline itself when it loads the results: only make one when there is none
        piped = any(o.isDerivedFrom("Fem::FemPostPipeline") for o in analysis.Group)
        if not piped and _has("FEM_PostPipelineFromResult"):
            try:
                Gui.runCommand("FEM_PostPipelineFromResult", 0)
            except Exception as _fw_err:
                _fw_log("addintabs.py:785", _fw_err)
        return study_summary(solver, res, analysis)
    if "elmer" in (type(getattr(solver, "Proxy", None)).__module__ or "").lower() or "elmer" in solver.Name.lower():
        _need_program("ElmerGrid", "Elmer")
        _need_program("ElmerSolver", "Elmer")
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(solver)
    Gui.runCommand("FEM_SolverRun", 0)
    return None


if Gui is not None:
    def _warn(title, text):
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), title, text)

    class _Base:
        def IsActive(self):
            return App.ActiveDocument is not None

    class SimNewStudy(_Base):
        def GetResources(self):
            return {"MenuText": "New Study", "ToolTip": KEYS[0][3], "Pixmap": "FEM_Analysis"}

        def Activated(self):
            load("FEM")
            doc = _doc()
            obj = _main_solid(doc)
            if obj is None:
                _warn("New Study", "The document has no solid body to study.")
                return
            names = [n for n, _k in STUDIES]
            pick, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "New Study", "Type of study:", names, 0, False)
            if not ok:
                return
            doc.openTransaction("New Study")
            try:
                a = new_study(doc, obj, dict(STUDIES)[pick])
            except Exception as error:
                doc.abortTransaction()
                _warn("New Study", str(error))
                return
            doc.commitTransaction()
            _set_active(a)
            _refresh_buttons()

    def _show_first_plot(a):
        try:
            from . import simplots
            made = simplots.defaults(a)
            if made and simplots.result(a) is not None:
                simplots.show(a, made[0]["name"])
                return True
        except Exception as _fw_err:
            _fw_log("addintabs.py:firstplot", _fw_err)
        return False

    class SimRun(_Base):
        def GetResources(self):
            return {"MenuText": "Run This Study", "ToolTip": "Meshes if needed and runs the active study.",
                    "Pixmap": "FEM_SolverRun"}

        def Activated(self):
            load("FEM")
            doc = _doc()
            a = _active_analysis(doc)
            if a is None:
                _warn("Run This Study", "There is no study yet: start one with New Study.")
                return
            # no wait cursor: the run window (simrun) stays live with Pause and Cancel while it runs
            from . import simrun
            simrun.begin(a)                   # one window for the whole run (fatigue events, dynamic, topology passes)
            try:
                text = run_study(a)
            except simrun.Cancelled:
                simrun.end()
                QtWidgets.QApplication.restoreOverrideCursor()
                doc.recompute()
                Gui.getMainWindow().statusBar().showMessage("%s: run cancelled." % a.Label, 8000)
                return
            except Exception as error:
                simrun.end()
                QtWidgets.QApplication.restoreOverrideCursor()
                _warn("Run This Study", str(error))
                return
            simrun.end()
            QtWidgets.QApplication.restoreOverrideCursor()
            doc.recompute()
            text = _large_displacement(a, text)
            if text is False:                         # Cancel: the solution ended, no results kept
                return
            if zero_result(a):
                _warn("Run This Study", "%s ran, but nothing moved: the loads reached no part of the mesh. Check that "
                      "the fixtures and loads are on the part's faces, then run again." % a.Label)
            elif no_loads_result(a):
                _warn("Run This Study", "%s ran, but nothing moved: the study has no loads. Add one under External Loads "
                      "(Force, Pressure, Gravity...), then run again." % a.Label)

            # message box; the numbers go to the status bar
            try:
                from . import simreport
                simreport.hide_fem_display(doc)      # no mesh, raw result or FreeCAD colour bar left on the model
            except Exception as _fw_err:
                _fw_log("addintabs.py:hidefem", _fw_err)
            shown = _show_first_plot(a)
            if text and shown:
                Gui.getMainWindow().statusBar().showMessage("%s finished. %s" % (a.Label, " ".join(text.split())), 15000)
            elif text:
                QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Run This Study", "%s finished.\n\n%s" % (a.Label, text))

    class FlowNewProject(_Base):
        def GetResources(self):
            return {"MenuText": "New Project", "ToolTip": "Starts a flow project on the fluid region body.",
                    "Pixmap": "FEM_EquationFlow"}

        def Activated(self):
            load("FEM")
            doc = _doc()
            obj = _main_solid(doc)
            if obj is None:
                _warn("New Project", "Model the fluid region as a solid body first.")
                return
            pick, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "New Project", "Fluid:", ["Air", "Water"], 0, False)
            if not ok:
                return
            doc.openTransaction("New Flow Project")
            try:
                a = new_flow(doc, obj, pick)
            except Exception as error:
                doc.abortTransaction()
                _warn("New Project", str(error))
                return
            doc.commitTransaction()
            _set_active(a)
            _refresh_buttons()

    class CAMGenerate(_Base):
        def GetResources(self):
            return {"MenuText": "Generate Toolpath", "ToolTip": "Recomputes every toolpath.", "Pixmap": "view-refresh"}

        def Activated(self):
            doc = _doc()
            paths = [o for o in doc.Objects if o.TypeId == "Path::FeaturePython"]
            if not paths:

                _warn("Generate Toolpath", "There are no toolpaths to generate.\n\n"
                      "Create a Job (New Part / Stock) and add an operation first.")
                return
            for o in paths:
                o.touch()
            doc.recompute()
            App.Console.PrintMessage("FreeCAD: %d toolpath object(s) generated\n" % len(paths))

    class AllTools:
        """A menu of every command of a tab's workbenches, grouped by their toolbars."""

        def __init__(self, source, title):
            self.source, self.title = source, title

        def GetResources(self):
            return {"MenuText": self.title, "ToolTip": "Every command of the FreeCAD workbench behind this tab.",
                    "Pixmap": "freecad"}

        def IsActive(self):
            return True

        def _groups(self):
            groups, seen = [], set()
            for wb, _m, _p in SOURCES.get(self.source, ()):
                try:
                    items = Gui.getWorkbench(wb).getToolbarItems()
                except Exception:
                    items = {}
                for bar, names in items.items():
                    names = [n for n in names if n != "Separator" and _has(n) and n not in seen]
                    seen.update(names)
                    if names:
                        groups.append((bar, names))
            rest = sorted(n for n in Gui.listCommands() if n.startswith(PREFIXES[self.source]) and n not in seen)
            if rest:
                groups.append(("More", rest))
            return groups

        def Activated(self):
            load(self.source)
            menu = QtWidgets.QMenu(Gui.getMainWindow())
            menu.setObjectName("FWAllTools")
            for bar, names in self._groups():
                sub = menu.addMenu(bar)
                for n in names:
                    try:
                        info = Gui.Command.get(n).getInfo() or {}
                    except Exception:
                        info = {}
                    text = (info.get("menuText") or n).replace("&", "")
                    act = sub.addAction(text)
                    try:
                        if info.get("pixmap"):
                            act.setIcon(_safe_icon(info["pixmap"]))
                    except Exception as _fw_err:
                        _fw_log("addintabs.py:943", _fw_err)
                    act.setToolTip(info.get("toolTip") or "")
                    act.triggered.connect(lambda _c=False, n=n: Gui.runCommand(n, 0))
            if menu.isEmpty():
                menu.addAction("The workbench is not installed").setEnabled(False)
            menu.exec_(QtGui.QCursor.pos())

    def _report_dir(doc):
        import os, tempfile
        base = os.path.dirname(doc.FileName) if doc.FileName else tempfile.gettempdir()
        path = os.path.join(base, (doc.Label or "Part") + "-report")
        os.makedirs(path, exist_ok=True)
        return path

    class SimReportImage(_Base):
        def GetResources(self):
            return {"MenuText": "Include Image for Report", "ToolTip": "Saves the view for the study report.",
                    "Pixmap": "Std_ViewScreenShot"}

        def Activated(self):
            import os, time
            doc = _doc()
            out = os.path.join(_report_dir(doc), "image-%s.png" % time.strftime("%H%M%S"))
            Gui.ActiveDocument.ActiveView.saveImage(out, 1200, 800, "Current")
            App.Console.PrintMessage("FreeCAD: report image %s\n" % out)
            try:        # cmsweep-1119: the click says what it did (it was silent)
                Gui.getMainWindow().statusBar().showMessage("Image saved for the report: %s" % os.path.basename(out), 6000)
            except Exception as _fw_err:
                _fw_log("addintabs.py:report-image", _fw_err)

    class SimReport(_Base):
        def GetResources(self):
            return {"MenuText": "Report", "ToolTip": "Writes an HTML report of the active study.", "Pixmap": "document-print"}

        def Activated(self):
            import html, os
            doc = _doc()
            a = _active_analysis(doc)
            if a is None:
                _warn("Report", "There is no study yet: start one with New Study.")
                return
            folder = _report_dir(doc)
            rows = []
            for o in a.Group:
                info = ""
                if hasattr(o, "Material") and isinstance(o.Material, dict):
                    info = ", ".join("%s %s" % kv for kv in o.Material.items() if kv[0] != "CardName")
                elif hasattr(o, "References"):
                    info = "; ".join("%s %s" % (r[0].Label, ",".join(r[1])) for r in o.References)
                if o.isDerivedFrom("Fem::FemResultObject"):
                    vm = max(o.vonMises) if getattr(o, "vonMises", None) else 0.0
                    d = max(o.DisplacementLengths) if getattr(o, "DisplacementLengths", None) else 0.0
                    info = "max von Mises %.4g MPa, max displacement %.4g mm" % (vm, d)
                rows.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (html.escape(o.Label),
                            html.escape(o.TypeId), html.escape(info)))
            images = "".join('<p><img src="%s" width="800"></p>' % n for n in sorted(os.listdir(folder)) if n.endswith(".png"))
            text = ("<html><head><meta charset='utf-8'><title>%s</title></head><body><h1>%s: %s</h1>"
                    "<table border='1' cellpadding='4'><tr><th>Item</th><th>Type</th><th>Details</th></tr>%s</table>%s"
                    "</body></html>") % (html.escape(a.Label), html.escape(doc.Label), html.escape(a.Label), "".join(rows), images)
            out = os.path.join(folder, "report.html")
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
            try:
                Gui.getMainWindow().statusBar().showMessage("Report saved: %s" % out, 10000)
            except Exception as _fw_err:
                _fw_log("addintabs.py:report", _fw_err)
            App.Console.PrintMessage("FreeCAD: study report %s\n" % out)
            if not os.environ.get("SWCHECK_OUT"):      # a check run never opens the browser
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(out))

    class CAMStock(_Base):
        def GetResources(self):
            return {"MenuText": "Stock Manager", "ToolTip": "Opens the job's stock and setup.", "Pixmap": "CAM_Job"}

        def Activated(self):
            doc = _doc()
            jobs = [o for o in doc.Objects if o.Name.startswith("Job") and hasattr(o, "Stock")]
            if not jobs:
                Gui.runCommand("CAM_Job", 0)
                return
            Gui.ActiveDocument.setEdit(jobs[0].Name)

    class ECADOpen(_Base):
        def GetResources(self):
            return {"MenuText": "Open ECAD File", "ToolTip": "Builds a board and its parts from an IDF file.", "Pixmap": "document-open"}

        def IsActive(self):
            return True

        def Activated(self):
            path, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Open ECAD File", "",
                                                             "IDF board (*.emn *.brd *.bdf *.idb);;All files (*)")
            if not path:
                return
            try:
                import Idf
            except Exception as error:
                _warn("Open ECAD File", "FreeCAD's IDF importer is not installed (%s)." % error)
                return
            problem, board = idf_staged(path)
            if problem:
                _warn("Open ECAD File", problem)
                return
            before = set(App.listDocuments())
            try:
                if App.ActiveDocument is None:
                    Idf.open(board)
                    doc = App.ActiveDocument
                    if doc is not None and doc.Name not in before:
                        doc.Label = os.path.splitext(os.path.basename(path))[0]
                else:
                    Idf.insert(board, App.ActiveDocument.Name)
            except Exception as error:
                for name in set(App.listDocuments()) - before:      # the empty document of a failed open
                    try:
                        App.closeDocument(name)
                    except Exception as _fw_err:
                        _fw_log("addintabs.py:idf-close", _fw_err)
                _warn("Open ECAD File", "The board could not be read: %s" % error)
                return
            try:
                Gui.SendMsgToActiveView("ViewFit")
            except Exception as _fw_err:
                _fw_log("addintabs.py:1043", _fw_err)

    class ECADExport(_Base):
        def GetResources(self):
            return {"MenuText": "Export to ECAD", "ToolTip": "Saves the board as STEP for the ECAD program.", "Pixmap": "document-save-as"}

        def Activated(self):
            doc = _doc()
            objs = Gui.Selection.getSelection() or [o for o in doc.RootObjects if hasattr(o, "Shape")]
            if not objs:
                _warn("Export to ECAD", "Nothing to export.")
                return
            base = os.path.splitext(doc.FileName)[0] if doc.FileName else doc.Label
            path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Export to ECAD", base + ".step",
                                                             "STEP (*.step *.stp)")
            if path:
                import ImportGui
                ImportGui.export(objs, path)

    def load_workbench(name):
        """Makes a workbench's commands exist without leaving the active one (a quick switch and back,
        never during a sketch or a task). True when it is loaded."""
        try:
            wb = Gui.getWorkbench(name)
        except Exception as _fw_err:
            _fw_log("addintabs.py:1155", _fw_err)
            return False
        try:
            if wb.getToolbarItems():
                return True
        except Exception as _fw_err:
            _fw_log("addintabs.py:1073", _fw_err)
        if _editing():
            return False
        try:
            current = Gui.activeWorkbench().name()
        except Exception:
            current = "PartDesignWorkbench"
        try:
            Gui.activateWorkbench(name)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s did not load (%s)\n" % (name, error))
        try:
            Gui.activateWorkbench(current if current not in ("", "NoneWorkbench") else "PartDesignWorkbench")
        except Exception as _fw_err:
            _fw_log("addintabs.py:1087", _fw_err)
        return True

    def _fill(menu, names):
        for n in names:
            try:
                info = Gui.Command.get(n).getInfo() or {}
            except Exception as _fw_err:
                _fw_log("addintabs.py:1183", _fw_err)
                continue
            act = menu.addAction((info.get("menuText") or n).replace("&", ""))
            try:
                if info.get("pixmap"):
                    act.setIcon(_safe_icon(info["pixmap"]))
            except Exception as _fw_err:
                _fw_log("addintabs.py:1101", _fw_err)
            act.setToolTip(info.get("toolTip") or "")
            act.triggered.connect(lambda _c=False, n=n: Gui.runCommand(n, 0))

    class AllFreeCADTools:
        """Every installed workbench > its toolbars > its commands. A workbench loads when its menu opens."""

        def GetResources(self):
            return {"MenuText": "All FreeCAD Tools", "Pixmap": "freecad",
                    "ToolTip": "Every command of every installed FreeCAD workbench."}

        def IsActive(self):
            return True

        def _open(self, sub, name):
            sub.clear()
            if not load_workbench(name):
                sub.addAction("Finish the sketch or task first").setEnabled(False)
                return
            try:
                items = Gui.getWorkbench(name).getToolbarItems()
            except Exception:
                items = {}
            for bar, names in items.items():
                names = [n for n in names if n != "Separator" and _has(n)]
                if names:
                    _fill(sub.addMenu(bar), names)
            if sub.isEmpty():
                sub.addAction("No commands").setEnabled(False)

        def Activated(self):
            menu = QtWidgets.QMenu(Gui.getMainWindow())
            menu.setObjectName("FWAllFreeCADTools")
            wbs = sorted(Gui.listWorkbenches().items(), key=lambda kv: getattr(kv[1], "MenuText", kv[0]).lower())
            for name, wb in wbs:
                if name in ("NoneWorkbench", "StartWorkbench"):
                    continue
                sub = menu.addMenu(getattr(wb, "MenuText", name))
                try:
                    icon = wb.Icon if isinstance(getattr(wb, "Icon", None), str) else None
                    if icon:
                        sub.setIcon(QtGui.QIcon(icon) if not icon.startswith("/*") else QtGui.QIcon())
                except Exception as _fw_err:
                    _fw_log("addintabs.py:1144", _fw_err)
                sub.addAction("...")
                sub.aboutToShow.connect(lambda sub=sub, name=name: self._open(sub, name))
            menu.exec_(QtGui.QCursor.pos())

    COMMANDS = {"SWStyle_SimNewStudy": SimNewStudy(), "SWStyle_SimRun": SimRun(),
                "SWStyle_AllFreeCADTools": AllFreeCADTools(),
                "SWStyle_SimReport": SimReport(), "SWStyle_SimReportImage": SimReportImage(), "SWStyle_CAMStock": CAMStock(),
                "SWStyle_FlowNewProject": FlowNewProject(), "SWStyle_CAMGenerate": CAMGenerate(),
                "SWStyle_AllTools_FEM": AllTools("FEM", "All Simulation Tools"),
                "SWStyle_AllTools_CAM": AllTools("CAM", "All CAM Tools"),
                "SWStyle_AllTools_Scan": AllTools("Scan", "All Scan Tools"),
                "SWStyle_AllTools_CfdOF": AllTools("CfdOF", "All CFD Tools")}
    from . import circuitworks as _cw          # Open ECAD File, Export to ECAD, Update Model, Library, Options
    COMMANDS.update(_cw.COMMANDS)


# ===================================================================== install
def tab_missing(title, have_wb):
    """True when something the tab is made of is not on this install, so the tab should not exist at all (hidden, not
    greyed): none of the workbenches its commands come from, or FreeCAD's IDF importer for CircuitWorks."""
    src = TAB_SOURCE.get(title)
    if src and not any(wb in have_wb for wb, _modules, _probe in SOURCES.get(src, ())):
        return True
    if title == "CircuitWorks":
        try:
            import importlib.util
            return importlib.util.find_spec("Idf") is None
        except Exception:
            return False
    return False


def install():
    """After cmtabs.install(): our keys, tabs and Add-Ins row, then the CommandManager again."""
    try:
        _install()
    except Exception as error:
        App.Console.PrintError("FreeCAD: add-in tabs not added (%s)\n" % error)


def _install():
    if Gui is None:
        return
    from . import catalog, cmtabs
    for name, cmd in COMMANDS.items():
        if name not in Gui.listCommands():
            Gui.addCommand(name, cmd)
    try:
        from . import simstudy
        simstudy.register()                # Study Advisor, Study Properties
        from . import studytools
        studytools.install()               # Compare Results, Run All Studies, Duplicate Study, Batch Run, CAM Options...
        from . import flowcam
        flowcam.install()                  # Flow General Settings, Computational Domain; CAM Define Machine, Sort Operations
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: study advisor not added (%s)\n" % error)
    for key, label, natives, tip, caption in KEYS:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, natives, None, tip, caption=caption)
    try:
        from . import simicons
        simicons.install()                 # Simulation / Flow / MBD pictures instead of FreeCAD's FEM icons
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: simulation icons not added (%s)\n" % error)
    try:
        from . import simtree
        simtree.install()                  # study tabs of a part, the Simulation study tree, the Flow analysis tree
        simtree.install_context_commands()  # mesh, solver, material and result tools pick their object themselves
        from . import simmaterial
        simmaterial.install()
        from . import simreport
        simreport.install()
        from . import simfit
        simfit.install()                    # the Simulation tab shows only what the active study's type can use
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: study tree not added (%s)\n" % error)
    try:
        from . import asmsim
        asmsim.install()                   # assembly studies: interactions, Bolt / Pin / Spring connectors
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: assembly simulation not added (%s)\n" % error)
    try:
        from . import simtypes
        simtypes.install()                 # Thermal, Frequency, Buckling, Fatigue, Drop Test, Design Study study types
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: study types not added (%s)\n" % error)
    try:
        from . import simnames
        simnames.install()
    except ImportError:
        pass
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Simulation names not added (%s)\n" % error)
    try:
        from . import simadvisor
        simadvisor.install()               # the Simulation Advisor in the Task Pane (Study, Fixtures, Loads ... Results)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Simulation Advisor not added (%s)\n" % error)
    have_wb = Gui.listWorkbenches()
    extra = []
    for key, label, wb, caption in MORE_WB:
        if wb in have_wb:
            if key not in catalog.BY_KEY:
                catalog.BY_KEY[key] = catalog.c(key, label, (), "FLYOUT_ADD_INS", call="wb:" + wb, caption=caption)
            extra.append(("large", key, None))
    catalog.ALL = tuple(catalog._ALL)
    # drop buttons whose workbench is missing on this install (no dead controls)
    def keep(item):
        if item[0] != "large":
            return True
        cmd = catalog.BY_KEY.get(item[1])
        return not (cmd and cmd.call and cmd.call.startswith("wb:") and cmd.call[3:] not in have_wb)
    addins = tuple(i for i in getattr(catalog, "ADDINS", ()) if keep(i))
    if extra and not any(i[0] == "large" and i[1] == extra[0][1] for i in addins):
        cmtabs.OVERRIDE["Add-Ins"] = (("large", "FC_AllTools", None), SEP) + addins + (SEP,) + tuple(extra)
    for title, layout in TABS.items():
        if tab_missing(title, have_wb):
            continue                  # no CfdOF / FEM / CAM / Mesh / IDF importer here: no such tab (hidden, not greyed)
        cmtabs.TABS.setdefault(title, layout)
    _add_basic(catalog, cmtabs)
    cmtabs.ORDER = tuple(cmtabs.ORDER) + tuple(t for t in ORDER if t not in cmtabs.ORDER and not tab_missing(t, have_wb))


    order = list(cmtabs.ORDER)
    if "MBD" in order and "Simulation" in order and order.index("MBD") < order.index("Simulation"):
        order.remove("MBD")
        order.insert(order.index("Simulation") + 1, "MBD")
        cmtabs.ORDER = tuple(order)
    cmtabs.DEFAULT_HIDDEN = tuple(cmtabs.DEFAULT_HIDDEN) + tuple(t for t in DEFAULT_HIDDEN if t not in cmtabs.DEFAULT_HIDDEN)
    try:
        _hook_assembly_tabs()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: add-in tabs in assemblies: %s\n" % error)
    try:
        _hook_page_shown()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: add-in tabs load on first use only by button (%s)\n" % error)
    try:
        from . import extapps
        extapps.install()      # ScanRuler and Diotopo tabs (# look-audit addinapps-1120: settings in Tools > Add-Ins)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: add-in apps not added (%s)\n" % error)
    try:
        from . import inspection
        inspection.install()   # the Inspection tab on drawings (Tools > Add-Ins lists it)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Inspection tab not added (%s)\n" % error)
    try:
        from . import renderout
        renderout.install()    # Render Tools: Integrated Preview, Preview Window, Final Render, Options, Schedule, Recall
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: render tools not added (%s)\n" % error)
    try:
        from . import otherwbtabs
        otherwbtabs.install()  # owbtabs-1122: Addon Manager workbenches (SubD...) as their own tabs, no workbench switch
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: tabs for other workbenches not added (%s)\n" % error)
    cmtabs.apply(rebuild=_shell() is not None)
    QtCore.QTimer.singleShot(10000, lambda: (_quiet(_reset_selection_filter_bar), _quiet(log_toolbars),
                                             _quiet(order_status_bar)))


def _add_basic(catalog, cmtabs):
    """Basic Modeling Tools, first, with only buttons whose key exists here (no dead controls)."""
    def ok(key):
        return key in catalog.BY_KEY

    def flyout(keys):
        return tuple(k for k in keys if ok(k)) or None if keys else None

    layout = []
    for item in BASIC:
        kind = item[0]
        if kind == "large":
            if ok(item[1]):
                layout.append(("large", item[1], flyout(item[2])))
        elif kind == "stack":
            rows = tuple((k, flyout(f)) for k, f in item[1] if ok(k))
            if rows:
                layout.append(("stack", rows))
        elif kind == "grid":
            rows = tuple(tuple((k, flyout(f)) for k, f in row if ok(k)) for row in item[1])
            rows = tuple(r for r in rows if r)
            if rows:
                layout.append(("grid", rows))
        elif layout and layout[-1][0] != "sep":
            layout.append(item)
    while layout and layout[-1][0] == "sep":
        layout.pop()
    cmtabs.TABS.setdefault(BASIC_TITLE, tuple(layout))
    if BASIC_TITLE not in cmtabs.ORDER:
        cmtabs.ORDER = (BASIC_TITLE,) + tuple(cmtabs.ORDER)


def _reset_selection_filter_bar():
    ""

    from . import selfilter
    p = selfilter._params()
    if p.GetBool("SelectionFilterToolbarReset2", False):
        return
    p.SetBool("SelectionFilterToolbarReset2", True)
    p.SetBool("SelectionFilterToolbar", False)
    tb = selfilter.toolbar(create=False)
    if tb is not None and tb.isVisible():
        tb.setVisible(False)


def order_status_bar():
    ""

    sh = _shell()
    info, units = getattr(sh, "status_info", None), getattr(sh, "status_units", None)
    if info is None or units is None:
        return
    sb = Gui.getMainWindow().statusBar()
    if info.x() < units.x():
        return
    right = sorted((w for w in sb.findChildren(QtWidgets.QWidget)
                    if w.parent() is sb and w.isVisible() and w.x() >= units.x() and w is not info), key=lambda w: w.x())
    for w in [info] + right:
        sb.removeWidget(w)
    for w in [info] + right:
        sb.addPermanentWidget(w)
        w.show()
    App.Console.PrintLog("FreeCAD: status bar ordered: %s\n" % [type(w).__name__ for w in [info] + right])


def _quiet(fn):
    try:
        fn()
    except Exception as error:
        App.Console.PrintLog("FreeCAD toolbars log: %s\n" % error)


# ===================================================================== toolbar log (look pass item 3)
def log_toolbars(tag="startup"):
    ""

    import os
    mw = Gui.getMainWindow()
    names = {QtCore.Qt.TopToolBarArea: "top", QtCore.Qt.BottomToolBarArea: "bottom",
             QtCore.Qt.LeftToolBarArea: "left", QtCore.Qt.RightToolBarArea: "right"}
    lines = []
    for tb in mw.findChildren(QtWidgets.QToolBar):
        if not tb.isVisible():
            continue
        try:
            area = names.get(mw.toolBarArea(tb), "floating" if tb.isFloating() else "other")
        except Exception:
            area = "?"
        acts = [a for a in tb.actions() if not a.isSeparator()]
        first = ", ".join((a.objectName() or a.text().replace("&", "")) for a in acts[:6])
        parent = tb.parentWidget().objectName() if tb.parentWidget() is not None else ""
        lines.append("%s | %s | %s | %s | parent=%s | %d actions: %s" % (
            tag, tb.objectName() or "(no name)", tb.metaObject().className(), area, parent, len(acts), first))
    text = "\n".join(lines) + "\n"
    App.Console.PrintLog("FreeCAD toolbars:\n" + text)
    try:
        with open(os.path.join(App.getUserAppDataDir(), "FreeWorks-toolbars.log"), "a", encoding="utf-8") as f:
            f.write(text)
    except Exception as _fw_err:
        _fw_log("addintabs.py:1344", _fw_err)
    return lines
