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
import FreeCADGui as Gui

MESH = ("FCX_M", "S3D_", "DecimateMesh", "SegmentMesh", "Cavity")
ASM_KEYS = ("Mate", "MoveComponent", "RotateComponent", "ExplodedView", "MirrorComponents", "Interference",
            "LinearComponentPattern", "CircularComponentPattern", "CurveComponentPattern", "ChainComponentPattern",
            "PatternDrivenComponentPattern", "SketchComponentPattern")

# (what it works on, what to do first), first match wins
HINTS = (
    (lambda k: k.startswith("FCX_Std") or k.startswith("FCX_Var") or k.startswith("FCX_Datum"),
     "works in a document with something to act on", "Pick an object in the FeatureManager design tree or start a part"),
    (lambda k: k.startswith(MESH), "works on a mesh",
     "Insert a mesh first (Insert > Mesh), pick it in the FeatureManager design tree"),
    (lambda k: k.startswith("FCX_S"), "works on spreadsheet cells",
     "Open a spreadsheet and pick the cells"),
    (lambda k: k.startswith("FCX_D"), "works on 2D drafting objects",
     "Draw or pick a 2D drafting object first"),
    (lambda k: k.startswith(("FCA_", "FCX_A")), "works in an Assembly",
     "Start an assembly (New Assembly on the FreeCAD Assembly tab), insert parts into it"),
    (lambda k: k in ASM_KEYS, "works on the components of an assembly",
     "Insert the components first, then pick them"),
    (lambda k: k.startswith("FCX_P") or k.startswith("FCX_R"), "works on the solids and shapes of the part",
     "Pick one or more shapes in the FeatureManager design tree or the graphics area"),
    (lambda k: k.startswith("FLOW_"), "works on a flow project",
     "Start a flow project first (Wizard or New Project), then use it"),
    (lambda k: k.startswith("SIM_"), "works on a Simulation study",
     "Start a study first (New Study on the Simulation tab), then use it"),
    (lambda k: k.startswith("MBD_"), "works on the model's faces, edges and dimensions",
     "Pick the faces, edges or dimensions to annotate"),
    (lambda k: k.startswith("FS_"), "works on a freeform shape",
     "Pick a freeform surface or a mesh body to edit"),
    (lambda k: k.startswith("MK_") or k == "Markup", "works on the model in the graphics area",
     "Switch Markup on, then draw on the view"),
    (lambda k: k.startswith("Draw") and "Sketch" in k, "works in a sketch on the drawing sheet",
     "Open a sketch on the sheet first"),
    (lambda k: k.startswith("Draw"), "works on a drawing view",
     "Insert a Model View first (Drawing tab), or pick a view on the sheet"),
    (lambda k: k.startswith("EV_"), "works on the model",
     "Pick the part or the faces to review"),
)

# notready-1126b: what each of the most used buttons needs, in its own words (the rest use the HINTS above)
TEXTS = {
    # Assembly tab
    "Mate": "Mate needs two faces, edges or points on two different components. Insert the components first, then pick the two items to mate.",
    "MoveComponent": "Move Component needs a component to drag. Insert components into the assembly first, then pick one.",
    "RotateComponent": "Rotate Component needs a component to turn. Insert components into the assembly first, then pick one.",
    "ExplodedView": "Exploded View needs an assembly with components. Insert components first, then pick the ones to move apart.",
    "MirrorComponents": "Mirror Components needs a mirror plane and the components to mirror. Pick a plane or flat face, then the components.",
    "Interference": "Interference Detection needs an assembly with at least two components. Insert the components first.",
    "LinearComponentPattern": "Linear Component Pattern needs a component to repeat and an edge for the direction. Pick them in the assembly.",
    "CircularComponentPattern": "Circular Component Pattern needs a component to repeat and an axis to turn it about. Pick them in the assembly.",
    "CurveComponentPattern": "Curve Driven Component Pattern needs a component to repeat and a curve or edge to follow. Pick them in the assembly.",
    "ChainComponentPattern": "Chain Component Pattern needs a component to repeat and a sketch with the chain's points. Pick them in the assembly.",
    "PatternDrivenComponentPattern": "Pattern Driven Component Pattern needs a component to repeat and a feature pattern in another component to follow.",
    "SketchComponentPattern": "Sketch Driven Component Pattern needs a component to repeat and a sketch with points to place it at.",
    "FCA_NewAssembly": "New Assembly starts an assembly in this document. Click it again once the document is ready for one.",
    "FCA_Insert": "Insert Component needs an assembly to put the part in. Start one with New Assembly first.",
    "FCA_InsertLink": "Insert Link needs an assembly to put the link in. Start one with New Assembly first.",
    "FCA_InsertNewPart": "Insert New Part needs an assembly to add the part to. Start one with New Assembly first.",
    "FCA_Grounded": "Toggle Grounded needs a component of an assembly. Pick one in the tree.",
    "FCA_Solve": "Solve Assembly needs an assembly with joints. Insert components and add joints first.",
    "FCA_Fixed": "Fixed Joint needs two items of two components: pick a face, edge or point on each.",
    "FCA_Revolute": "Revolute Joint needs two items of two components: pick a circular edge or face on each.",
    "FCA_Cylindrical": "Cylindrical Joint needs two items of two components: pick a cylindrical face or edge on each.",
    "FCA_Slider": "Slider Joint needs two items of two components: pick a face or edge on each that sets the sliding direction.",
    "FCA_Ball": "Ball Joint needs two items of two components: pick a point or spherical face on each.",
    "FCA_Distance": "Distance Joint needs two items of two components: pick a face, edge or point on each.",
    "FCA_Parallel": "Parallel Joint needs two items of two components: pick a face or edge on each.",
    "FCA_Perpendicular": "Perpendicular Joint needs two items of two components: pick a face or edge on each.",
    "FCA_Angle": "Angle Joint needs two items of two components: pick a face or edge on each.",
    "FCA_Screw": "Screw Joint needs two items of two components: pick a cylindrical face or axis on each.",
    # Features and direct editing
    "CurveDrivenPattern": "Curve Driven Pattern needs a feature to repeat and a curve or edge to follow. Pick the feature, then the curve.",
    "SketchDrivenPattern": "Sketch Driven Pattern needs a feature to repeat and a sketch with points. Pick the feature, then the sketch.",
    "TableDrivenPattern": "Table Driven Pattern needs a feature to repeat and a coordinate system. Pick the feature first.",
    "FillPattern": "Fill Pattern needs a flat face to fill and a feature to repeat. Pick the face, then the feature.",
    "VariablePattern": "Variable Pattern needs a feature to repeat and a direction edge. Pick the feature first.",
    "MateReference": "Mate Reference needs a face, edge or point to mark for mating. Pick one on the part.",
    "SplitLine": "Split Line needs a face to split and a sketch, plane or edge to split it with. Pick the face first.",
    "ReplaceFace": "Replace Face needs the faces to replace and the face or surface to replace them with. Pick the faces first.",
    "MoveFace": "Move Face needs one or more faces to move. Pick faces on the part, then use it.",
    "HealEdges": "Heal Edges needs the edges or faces to heal on an imported body. Pick the body first.",
    "Cavity": "Cavity needs a tool body and a body to cut it from. Pick them in the tree.",
    "VariableFillet": "Variable Size Fillet needs an edge to round. Pick an edge of a solid first.",
    "FaceFillet": "Face Fillet needs two faces to blend. Pick the two faces of a solid first.",
    "FullRoundFillet": "Full Round Fillet needs three faces: two side faces and the face between them. Pick them on the solid.",
    "Defeature": "Defeature needs a solid to simplify. Pick the body first.",
    "RecognizeFeatures": "Recognize Features needs an imported solid. Pick the body first.",
    "ShapeBinder": "Reference Geometry Copy needs the faces, edges or sketch to copy. Pick them first.",
    "CopyAppearance": "Copy Appearance needs a face, body or component whose look to copy. Pick one first.",
    "PasteAppearance": "Paste Appearance needs a look copied first (Copy Appearance) and a face, body or component to paste it to.",
    "EditAppearance": "Edit Appearance needs a face, body or component. Pick one first.",
    "EditDecal": "Edit Decal needs a decal on the part. Add one with Decals first, then pick it.",
    "ChangeDisplayStates": "Change Display States needs a component of an assembly. Pick one first.",
    # Mesh and scan
    "FCX_MUnion": "Mesh Union needs two meshes. Pick both in the tree first.",
    "FCX_MDifference": "Mesh Difference needs two meshes. Pick the first, then the one to take away.",
    "FCX_MIntersection": "Mesh Intersection needs two meshes. Pick both in the tree first.",
    "FCX_MMerge": "Merge Meshes needs two or more meshes. Pick them in the tree first.",
    "FCX_MTrim": "Trim Mesh needs a mesh. Pick it in the tree, then use it and draw the cut outline.",
    "FCX_MCloseHole": "Close Hole needs a mesh with a hole. Pick the mesh, then click at the hole's edge.",
    "FCX_MFlip": "Flip Normals needs a mesh. Pick it in the tree first.",
    "FCX_MRemesh": "Remesh needs a solid or a face to mesh. Pick it in the tree first.",
    "FCX_MSplit": "Split by Components needs a mesh. Pick it in the tree first.",
    "FCX_MAddFacet": "Add Triangle needs a mesh. Pick it in the tree first.",
    "S3D_Prep": "Mesh Prep Wizard needs a mesh. Insert one first (Insert > Mesh), pick it in the tree, then run the wizard.",
    "S3D_Normals": "Fix Normals needs a mesh. Pick it in the tree first.",
    "S3D_FillHoles": "Fill Holes needs a mesh with holes. Pick the mesh first.",
    "S3D_RemoveParts": "Remove Noise needs a mesh. Pick it in the tree first.",
    "S3D_Smooth": "Smooth needs a mesh. Pick it in the tree first.",
    "S3D_Decimate": "Reduce needs a mesh. Pick it in the tree first.",
    "S3D_Scale": "Scale needs a mesh. Pick it in the tree first.",
    "S3D_Trim": "Trim needs a mesh. Pick it in the tree, then draw the outline to cut.",
    "S3D_Segment": "Segment Mesh needs a mesh. Pick it in the tree first.",
    "S3D_ToBody": "Mesh to Body needs a mesh. Pick it in the tree first.",
    "S3D_Section": "Section Curve needs a mesh and a plane. Pick the mesh first.",
    "S3D_Curvature": "Curvature needs a mesh. Pick it in the tree first.",
    "DecimateMesh": "Decimate Mesh Body needs a mesh body. Pick it in the tree first.",
    "SegmentMesh": "Segment Mesh needs a mesh body. Pick it in the tree first.",
    # Drawings
    "DrawModelView": "Model View needs a part or assembly to show. Open it, or pick it when asked, then place the view on the sheet.",
    "DrawStandard3View": "Standard 3 View needs a part or assembly to show. Open it, or pick it when asked.",
    "DrawPredefinedView": "Predefined View needs a part or assembly to show. Open it, or pick it when asked.",
    "DrawRelativeView": "Relative View needs a part or assembly to show, and two faces to orient it. Open the model first.",
    "DrawEmptyView": "Empty View needs a drawing sheet. Open or start a drawing first.",
    "DrawBreak": "Break View needs a drawing view. Insert a Model View first, then pick it.",
    "DrawCrop": "Crop View needs a drawing view. Insert a Model View first, then pick it.",
    "DrawAutodimension": "Autodimension needs a drawing view to dimension. Insert a Model View first.",
    "DrawHorizontalDimension": "Horizontal Dimension needs a view edge or two points on the sheet. Insert a Model View first.",
    "DrawVerticalDimension": "Vertical Dimension needs a view edge or two points on the sheet. Insert a Model View first.",
    "DrawRadiusDimension": "Radius/Diameter Dimension needs a circle or arc in a view. Insert a Model View first.",
    "DrawAngularDimension": "Angular Dimension needs two lines in a view. Insert a Model View first.",
    "DrawChainDimension": "Chain Dimension needs a drawing view with edges to dimension. Insert a Model View first.",
    "DrawBaselineDimension": "Baseline Dimension needs a drawing view with edges to dimension. Insert a Model View first.",
    "DrawBalloon": "Balloon needs a part or component in a drawing view. Insert a Model View first, then pick it.",
    "DrawAutoBalloon": "Auto Balloon needs an assembly view. Insert a Model View of an assembly first.",
    "DrawCenterMark": "Center Mark needs a circle or arc in a view. Insert a Model View first.",
    "DrawCenterline": "Centerline needs two edges in a view. Insert a Model View first.",
    "DrawNote": "Note needs a drawing sheet. Open or start a drawing first.",
    "DrawHoleCallout": "Hole Callout needs a hole in a drawing view. Insert a Model View first.",
    "DrawSurfaceFinish": "Surface Finish needs an edge or face in a view. Insert a Model View first.",
    "DrawGeometricTolerance": "Geometric Tolerance needs a drawing sheet with a view. Insert a Model View first.",
    "DrawAreaHatch": "Area Hatch/Fill needs a closed region in a view. Insert a Model View first.",
    "DrawModelItems": "Model Items needs a drawing view of a part with dimensions. Insert a Model View first.",
    "DrawGeneralTable": "General Table needs a drawing sheet. Open or start a drawing first.",
    "DrawTitleBlockTable": "Title Block Table needs a drawing sheet. Open or start a drawing first.",
    "DrawRevisionTable": "Revision Table needs a drawing sheet. Open or start a drawing first.",
    # Sketch tools on a drawing sheet
    "DrawSketchPoint": "Point draws in a sketch on the sheet. Open a sketch on the sheet first.",
    "DrawSketchEllipse": "Ellipse draws in a sketch on the sheet. Open a sketch on the sheet first.",
    "DrawSketchPolygon": "Polygon draws in a sketch on the sheet. Open a sketch on the sheet first.",
    "DrawSketchSlot": "Straight Slot draws in a sketch on the sheet. Open a sketch on the sheet first.",
    "DrawSketchFillet": "Sketch Fillet works in a sketch on the sheet. Open one with lines that meet first.",
    "DrawTrimEntities": "Trim Entities works in a sketch on the sheet. Open one with lines to trim first.",
    # MBD, Freeshape, markup
    "MBD_Size": "Size Dimension needs a cylindrical face, a slot or a width to measure. Pick it on the model.",
    "MBD_Location": "Location Dimension needs a feature to locate and a datum or edge to measure from. Pick them on the model.",
    "MBD_Datum": "Datum needs a face to mark as a datum. Pick one on the model.",
    "MBD_GTol": "Geometric Tolerance needs a face, edge or dimension to attach it to. Pick one on the model.",
    "MBD_Auto": "Auto Dimension Scheme needs a part with solid geometry. Pick the part first.",
    "MBD_Note": "Note needs a face or edge to attach to. Pick one on the model.",
    "FS_Subdivide": "Subdivide needs a freeform surface. Pick one first.",
    "FS_ExtrudeFace": "Extrude Face needs a face of a freeform surface. Pick one first.",
    "MK_Draw": "Draw needs Markup switched on. Click Markup first, then draw on the view.",
    "MK_Note": "Note needs Markup switched on. Click Markup first, then place the note.",
}


def hint(key):
    for test, what, todo in HINTS:
        try:
            if test(key):
                return what, todo
        except Exception as _fw_err:
            _fw_log("notready.py:hint", _fw_err)
    return "works on the objects you pick", "Pick what it works on in the graphics area or the FeatureManager design tree"


def label_icon(key):
    try:
        from . import catalog
        c = catalog.BY_KEY.get(key)
        if c is not None:
            return c.label, c.icon
    except Exception as _fw_err:
        _fw_log("notready.py:label", _fw_err)
    return key, None


class NotReadyPage:
    ""

    def __init__(self, key, text=None, title=None):
        from PySide import QtWidgets
        self.key = key
        label, icon = label_icon(key)
        if title:
            label = title       # greyrows-1126: a menu row brings its own name and words
        what, todo = hint(key)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Message")
        self.form.setProperty("swstyle_pm_title", label)
        if icon:
            self.form.setProperty("swstyle_pm_icon", icon)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        own = text or TEXTS.get(key)
        text = QtWidgets.QLabel(own if own else "%s %s, and nothing here is ready for it yet. %s, then use %s again." %
                                (label, what, todo, label))
        text.setObjectName("SWNotReadyMessage")
        text.setWordWrap(True)
        lay.addWidget(text)
        lay.addStretch(1)

    def getStandardButtons(self):
        from PySide import QtWidgets
        return QtWidgets.QDialogButtonBox.Cancel

    def reject(self):
        Gui.Control.closeDialog()
        return True


def can_act(native):
    try:
        c = Gui.Command.get(native)
        return c is not None and bool(c.isActive())
    except Exception:
        return False


def exists(native):
    try:
        return Gui.Command.get(native) is not None
    except Exception:
        return False


def show(key, text=None, title=None):
    """The page for key; False when a PropertyManager is open already."""
    try:
        if Gui.Control.activeDialog():
            return False
    except Exception:
        pass
    Gui.Selection.clearSelection()
    Gui.Control.showDialog(NotReadyPage(key, text, title))
    return True
