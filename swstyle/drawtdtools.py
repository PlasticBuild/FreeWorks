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

TAB = "Drawing Tools"

# (key, label, FreeCAD command, tip); icons come from FreeCAD's own command
KEYS = (
    # ---- sheet
    ("TDX_FillTemplate", "Update Template Fields", "TechDraw_FillTemplateFields",
     "Fills the title block fields from the document's properties."),
    ("TDX_Redraw", "Redraw Sheet", "TechDraw_RedrawPage", "Draws the whole sheet again."),
    ("TDX_StackTop", "Bring to Front", "TechDraw_StackTop", "Draws the picked view over all others."),
    ("TDX_StackBottom", "Send to Back", "TechDraw_StackBottom", "Draws the picked view under all others."),
    ("TDX_StackUp", "Bring Forward", "TechDraw_StackUp", "Draws the picked view one step further up."),
    ("TDX_StackDown", "Send Backward", "TechDraw_StackDown", "Draws the picked view one step further down."),
    ("TDX_MoveView", "Move View to Sheet", "TechDraw_MoveView", "Moves the picked view to another sheet."),
    ("TDX_ShareView", "Share View", "TechDraw_ShareView", "Shows the picked view on another sheet too."),
    # ---- views
    ("TDX_ActiveView", "Active 3D View", "TechDraw_ActiveView", "Places a picture of the 3D window on the sheet."),
    ("TDX_DraftView", "Draft Objects View", "TechDraw_DraftView", "Shows picked Draft or Arch objects on the sheet."),
    ("TDX_SectionView", "Simple Section", "TechDraw_SectionView", "FreeCAD's section of a picked view along a plane."),
    ("TDX_ComplexSection", "Complex Section", "TechDraw_ComplexSection",
     "FreeCAD's section along a picked profile (offset or aligned)."),
    ("TDX_PositionSection", "Position Section View", "TechDraw_ExtensionPositionSectionView",
     "Lines a section view up with its parent view."),
    ("TDX_ToggleLock", "Toggle View Lock", "TechDraw_ExtensionLockUnlockView",
     "Locks or unlocks the picked views' position."),
    ("TDX_ArchView", "BIM View", "TechDraw_ArchView", "Shows a BIM section plane's cut on the sheet."),
    ("TDX_ClipAdd", "Add View to Clip Group", "TechDraw_ClipGroupAdd", "Puts the picked view in the picked clip group."),
    # ---- dimensions
    ("TDX_Dimension", "FreeCAD Dimension", "TechDraw_Dimension", "FreeCAD's own dimension tool, by what is picked."),
    ("TDX_Length", "Length Dimension", "TechDraw_LengthDimension", "A true length between two points or along an edge."),
    ("TDX_Horizontal", "Horizontal Dimension", "TechDraw_HorizontalDimension", "A horizontal distance."),
    ("TDX_Vertical", "Vertical Dimension", "TechDraw_VerticalDimension", "A vertical distance."),
    ("TDX_Radius", "Radius Dimension", "TechDraw_RadiusDimension", "The radius of a circle or arc."),
    ("TDX_Diameter", "Diameter Dimension", "TechDraw_DiameterDimension", "The diameter of a circle or arc."),
    ("TDX_Angle", "Angle Dimension", "TechDraw_AngleDimension", "The angle between two edges."),
    ("TDX_Angle3", "3 Point Angle Dimension", "TechDraw_3PtAngleDimension", "The angle at a vertex between two points."),
    ("TDX_Area", "Area Annotation", "TechDraw_AreaDimension", "The area of a picked face."),
    ("TDX_ArcLength", "Arc Length Dimension", "TechDraw_ExtensionCreateLengthArc", "The length along an arc."),
    ("TDX_HExtent", "Horizontal Extent", "TechDraw_HorizontalExtentDimension", "The overall width of picked edges."),
    ("TDX_VExtent", "Vertical Extent", "TechDraw_VerticalExtentDimension", "The overall height of picked edges."),
    ("TDX_HChain", "Horizontal Chain", "TechDraw_ExtensionCreateHorizChainDimension", "Horizontal dimensions end to end."),
    ("TDX_VChain", "Vertical Chain", "TechDraw_ExtensionCreateVertChainDimension", "Vertical dimensions end to end."),
    ("TDX_OChain", "Oblique Chain", "TechDraw_ExtensionCreateObliqueChainDimension", "Aligned dimensions end to end."),
    ("TDX_HCoord", "Horizontal Coordinate", "TechDraw_ExtensionCreateHorizCoordDimension",
     "Horizontal dimensions from one base point."),
    ("TDX_VCoord", "Vertical Coordinate", "TechDraw_ExtensionCreateVertCoordDimension",
     "Vertical dimensions from one base point."),
    ("TDX_OCoord", "Oblique Coordinate", "TechDraw_ExtensionCreateObliqueCoordDimension",
     "Aligned dimensions from one base point."),
    ("TDX_HChamfer", "Horizontal Chamfer", "TechDraw_ExtensionCreateHorizChamferDimension", "A chamfer's size and angle."),
    ("TDX_VChamfer", "Vertical Chamfer", "TechDraw_ExtensionCreateVertChamferDimension", "A chamfer's size and angle."),
    ("TDX_HCascade", "Horizontal Cascade", "TechDraw_ExtensionCascadeHorizDimension",
     "Spaces picked horizontal dimensions evenly in a stair."),
    ("TDX_VCascade", "Vertical Cascade", "TechDraw_ExtensionCascadeVertDimension",
     "Spaces picked vertical dimensions evenly in a stair."),
    ("TDX_OCascade", "Oblique Cascade", "TechDraw_ExtensionCascadeObliqueDimension",
     "Spaces picked aligned dimensions evenly in a stair."),
    ("TDX_HPosChain", "Line Up Horizontal Chain", "TechDraw_ExtensionPosHorizChainDimension",
     "Puts picked horizontal dimensions on one line."),
    ("TDX_VPosChain", "Line Up Vertical Chain", "TechDraw_ExtensionPosVertChainDimension",
     "Puts picked vertical dimensions on one line."),
    ("TDX_OPosChain", "Line Up Oblique Chain", "TechDraw_ExtensionPosObliqueChainDimension",
     "Puts picked aligned dimensions on one line."),
    ("TDX_AreaAnno", "Area Annotation (Faces)", "TechDraw_ExtensionAreaAnnotation", "Writes the area of picked faces."),
    ("TDX_AxoLength", "Axonometric Length", "TechDraw_AxoLengthDimension", "A length in an isometric view."),
    ("TDX_HoleShaftFit", "Hole/Shaft Fit", "TechDraw_HoleShaftFit", "Adds an ISO fit (H7/g6 and so on) to a dimension."),
    ("TDX_PrefixDia", "Insert Diameter Prefix", "TechDraw_ExtensionInsertDiameter", "Puts a diameter sign before the value."),
    ("TDX_PrefixSquare", "Insert Square Prefix", "TechDraw_ExtensionInsertSquare", "Puts a square sign before the value."),
    ("TDX_PrefixRepeat", "Insert Repeat Prefix", "TechDraw_ExtensionInsertRepetition", "Puts 'n x' before the value."),
    ("TDX_PrefixRemove", "Remove Prefix", "TechDraw_ExtensionRemovePrefixChar", "Takes the prefix off the value."),
    ("TDX_IncDecimal", "Increase Decimal Places", "TechDraw_ExtensionIncreaseDecimal", "One more decimal place."),
    ("TDX_DecDecimal", "Decrease Decimal Places", "TechDraw_ExtensionDecreaseDecimal", "One decimal place less."),
    ("TDX_CustomFormat", "Customize Format Label", "TechDraw_ExtensionCustomizeFormat",
     "Edits the format text of a dimension or label."),
    # ---- line format
    ("TDX_SelectLineAttr", "Line Attributes", "TechDraw_ExtensionSelectLineAttributes",
     "Sets the line style, width and color the next two tools use."),
    ("TDX_ChangeLineAttr", "Change Line Attributes", "TechDraw_ExtensionChangeLineAttributes",
     "Gives picked cosmetic lines the line attributes set."),
    ("TDX_ExtendLine", "Extend Line", "TechDraw_ExtensionExtendLine", "Makes a cosmetic line or centerline longer."),
    ("TDX_ShortenLine", "Shorten Line", "TechDraw_ExtensionShortenLine", "Makes a cosmetic line or centerline shorter."),
    ("TDX_ShowAll", "Toggle Edge Visibility", "TechDraw_ShowAll", "Shows or hides the hidden edges of a view."),
    # ---- centerlines and cosmetic geometry
    ("TDX_CircleCL", "Circle Centerlines", "TechDraw_ExtensionCircleCenterLines", "Center marks on picked circles."),
    ("TDX_BoltCircleCL", "Bolt Circle Centerlines", "TechDraw_ExtensionHoleCircle",
     "A bolt circle through three or more picked holes."),
    ("TDX_FaceCL", "Centerline Faces", "TechDraw_FaceCenterLine", "A centerline across a picked face."),
    ("TDX_2LineCL", "Centerline 2 Lines", "TechDraw_2LineCenterLine", "A centerline between two lines."),
    ("TDX_2PointCL", "Centerline 2 Points", "TechDraw_2PointCenterLine", "A centerline through two points."),
    ("TDX_ThreadHoleSide", "Thread Hole Side View", "TechDraw_ExtensionThreadHoleSide", "Cosmetic thread of a hole, side on."),
    ("TDX_ThreadHoleBottom", "Thread Hole Bottom View", "TechDraw_ExtensionThreadHoleBottom",
     "Cosmetic thread of a hole, end on."),
    ("TDX_ThreadBoltSide", "Thread Bolt Side View", "TechDraw_ExtensionThreadBoltSide", "Cosmetic thread of a bolt, side on."),
    ("TDX_ThreadBoltBottom", "Thread Bolt Bottom View", "TechDraw_ExtensionThreadBoltBottom",
     "Cosmetic thread of a bolt, end on."),
    ("TDX_CosVertex", "Cosmetic Vertex", "TechDraw_CosmeticVertex", "Adds a point at a picked place."),
    ("TDX_Midpoints", "Midpoint Vertices", "TechDraw_Midpoints", "Adds points at the middles of picked edges."),
    ("TDX_Quadrants", "Quadrant Vertices", "TechDraw_Quadrants", "Adds points at the quadrants of picked circles."),
    ("TDX_Intersection", "Intersection Vertices", "TechDraw_ExtensionVertexAtIntersection",
     "Adds points where two picked edges cross."),
    ("TDX_OffsetVertex", "Offset Vertex", "TechDraw_CommandAddOffsetVertex", "Adds a point at an offset from a vertex."),
    ("TDX_Circle1", "Cosmetic Circle", "TechDraw_CosmeticCircle", "A cosmetic circle from a center and a point."),
    ("TDX_Circle2", "Cosmetic 2 Point Circle", "TechDraw_ExtensionDrawCosmCircle", "A cosmetic circle through two points."),
    ("TDX_Circle3", "Cosmetic 3 Point Circle", "TechDraw_ExtensionDrawCosmCircle3Points",
     "A cosmetic circle through three points."),
    ("TDX_CosArc", "Cosmetic Arc", "TechDraw_ExtensionDrawCosmArc", "A cosmetic arc from a center and two points."),
    ("TDX_Parallel", "Cosmetic Parallel Line", "TechDraw_ExtensionLineParallel", "A cosmetic line parallel to an edge."),
    ("TDX_Perpendicular", "Cosmetic Perpendicular Line", "TechDraw_ExtensionLinePerpendicular",
     "A cosmetic line square to an edge."),
    ("TDX_Eraser", "Cosmetic Eraser", "TechDraw_CosmeticEraser", "Deletes picked cosmetic lines, circles and points."),
    ("TDX_AlignVertH", "Align Vertices Horizontally", "TechDraw_AlignVertexesHorizontally",
     "Turns the view so the two picked points lie level."),
    ("TDX_AlignVertV", "Align Vertices Vertically", "TechDraw_AlignVertexesVertically",
     "Turns the view so the two picked points lie one above the other."),
    ("TDX_2PointLine", "Cosmetic Line 2 Points", "TechDraw_2PointCosmeticLine", "A cosmetic line between two points."),
    # ---- annotation
    ("TDX_RichText", "Rich Text Annotation", "TechDraw_RichTextAnnotation", "A formatted text block, with or without a leader."),
)
NATIVE = {k: n for k, _l, n, _t in KEYS}
OWN = "FreeWorks_"

STACK = ("TDX_StackTop", "TDX_StackBottom", "TDX_StackUp", "TDX_StackDown")
SECTION = ("TDX_SectionView", "TDX_ComplexSection")
DIMENSIONS = ("TDX_Dimension", "TDX_Length", "TDX_Horizontal", "TDX_Vertical", "TDX_Radius", "TDX_Diameter", "TDX_Angle",
              "TDX_Angle3", "TDX_Area", "TDX_ArcLength", "TDX_HExtent", "TDX_VExtent")
CHAIN = ("TDX_HChain", "TDX_VChain", "TDX_OChain", "TDX_HCoord", "TDX_VCoord", "TDX_OCoord", "TDX_HChamfer", "TDX_VChamfer")
PREFIX = ("TDX_PrefixDia", "TDX_PrefixSquare", "TDX_PrefixRepeat", "TDX_PrefixRemove")
DECIMALS = ("TDX_IncDecimal", "TDX_DecDecimal")
EXTEND = ("TDX_ExtendLine", "TDX_ShortenLine")
CIRCLE_CL = ("TDX_CircleCL", "TDX_BoltCircleCL")
CENTERLINES = ("TDX_FaceCL", "TDX_2LineCL", "TDX_2PointCL")
THREADS = ("TDX_ThreadHoleSide", "TDX_ThreadHoleBottom", "TDX_ThreadBoltSide", "TDX_ThreadBoltBottom")
VERTICES = ("TDX_CosVertex", "TDX_Midpoints", "TDX_Quadrants", "TDX_Intersection", "TDX_OffsetVertex")
CIRCLES = ("TDX_Circle1", "TDX_Circle2", "TDX_Circle3", "TDX_CosArc")
LINES = ("TDX_2PointLine", "TDX_Parallel", "TDX_Perpendicular")
SHARE = ("TDX_MoveView", "TDX_ShareView")
OTHER_VIEWS = ("TDX_ActiveView", "TDX_DraftView", "TDX_ArchView", "TDX_ClipAdd")
CASCADE = ("TDX_HCascade", "TDX_VCascade", "TDX_OCascade", "TDX_HPosChain", "TDX_VPosChain", "TDX_OPosChain")
EDIT_COSMETIC = ("TDX_Eraser", "TDX_AlignVertH", "TDX_AlignVertV")


LAYOUT = (
    ("stack", (("TDX_FillTemplate", None), ("TDX_Redraw", None), ("TDX_StackTop", STACK))),
    ("stack", (("TDX_MoveView", SHARE),)),
    ("sep",),
    ("stack", (("TDX_SectionView", SECTION), ("TDX_PositionSection", None), ("TDX_ToggleLock", None))),
    ("stack", (("TDX_ActiveView", OTHER_VIEWS), ("TDX_DraftView", None))),
    ("sep",),
    ("large", "TDX_Dimension", DIMENSIONS),
    ("stack", (("TDX_HChain", CHAIN), ("TDX_AxoLength", None), ("TDX_HoleShaftFit", None))),
    ("stack", (("TDX_PrefixDia", PREFIX), ("TDX_IncDecimal", DECIMALS), ("TDX_CustomFormat", None))),
    ("stack", (("TDX_HCascade", CASCADE), ("TDX_AreaAnno", None))),
    ("sep",),
    ("stack", (("TDX_SelectLineAttr", None), ("TDX_ChangeLineAttr", None), ("TDX_ExtendLine", EXTEND))),
    ("stack", (("TDX_ShowAll", None),)),
    ("sep",),
    ("stack", (("TDX_CircleCL", CIRCLE_CL), ("TDX_FaceCL", CENTERLINES), ("TDX_ThreadHoleSide", THREADS))),
    ("stack", (("TDX_CosVertex", VERTICES), ("TDX_Circle1", CIRCLES), ("TDX_2PointLine", LINES))),
    ("stack", (("TDX_Eraser", EDIT_COSMETIC),)),
    ("sep",),
    ("large", "TDX_RichText", None),
)

S = None


def _sub(keys):
    label = {k: l for k, l, _n, _t in KEYS}
    return tuple((label[k], OWN + k + "|" + NATIVE[k]) for k in keys)


# Tools > Drawing Tools, the same groups as submenus (drawmenus' layout: (label, command) or (label, [entries]))
MENU = (
    ("Sheet", _sub(("TDX_FillTemplate", "TDX_Redraw")) + (S,) + _sub(STACK) + (S,) + _sub(SHARE)),
    ("Views", _sub(SECTION + ("TDX_PositionSection", "TDX_ToggleLock")) + (S,) + _sub(OTHER_VIEWS)),
    ("Dimensions", _sub(DIMENSIONS) + (S,) + _sub(CHAIN) + (S,) + _sub(("TDX_AxoLength", "TDX_HoleShaftFit")) + (S,)
     + _sub(PREFIX) + (S,) + _sub(DECIMALS + ("TDX_CustomFormat",)) + (S,) + _sub(CASCADE) + (S,)
     + _sub(("TDX_AreaAnno",))),
    ("Line Format", _sub(("TDX_SelectLineAttr", "TDX_ChangeLineAttr")) + _sub(EXTEND) + (S,) + _sub(("TDX_ShowAll",))),
    ("Centerlines", _sub(CIRCLE_CL + CENTERLINES) + (S,) + _sub(THREADS)),
    ("Cosmetic Geometry", _sub(VERTICES) + (S,) + _sub(CIRCLES) + (S,) + _sub(LINES) + (S,) + _sub(EDIT_COSMETIC)),
    ("Rich Text Annotation", OWN + "TDX_RichText|TechDraw_RichTextAnnotation"),
)


def commands():
    """Every FreeCAD command the tab and the menu run (the reach check)."""
    return [n for _k, _l, n, _t in KEYS]


def _have():
    try:
        import TechDrawGui  # noqa: F401  (registers TechDraw's commands, extensions too)
    except Exception as _fw_err:
        _fw_log("drawtdtools.py:226", _fw_err)
    try:
        import TechDrawTools  # noqa: F401  (FreeCAD's Python drawing tools: template fields, axonometric length, fits)
    except Exception as _fw_err:
        _fw_log("drawtdtools.py:230", _fw_err)
    return set(Gui.listCommands())


def layout(have=None):
    """LAYOUT with the buttons this FreeCAD has no command for left out."""
    have = _have() if have is None else have
    ok = lambda k: NATIVE.get(k) in have
    out = []
    for e in LAYOUT:
        if e[0] == "sep":
            if out and out[-1][0] != "sep":
                out.append(e)
        elif e[0] == "large":
            fly = tuple(k for k in (e[2] or ()) if ok(k)) or None
            if ok(e[1]):
                out.append(("large", e[1], fly))
            elif fly:
                out.append(("large", fly[0], fly))
        else:
            rows = []
            for key, fly in e[1]:
                f = tuple(k for k in (fly or ()) if ok(k)) or None
                if ok(key):
                    rows.append((key, f))
                elif f:
                    rows.append((f[0], f))
            if rows:
                out.append(("stack", tuple(rows)))
    while out and out[-1][0] == "sep":
        out.pop()
    return tuple(out)


class ToolCommand:
    ""



    def __init__(self, key, label, native, tip):
        self.key, self.label, self.native, self.tip = key, label, native, tip

    def _cmd(self):
        try:
            return Gui.Command.get(self.native)
        except Exception:
            return None

    def GetResources(self):
        info = {}
        c = self._cmd()
        try:
            info = (c.getInfo() or {}) if c is not None else {}
        except Exception as _fw_err:
            _fw_log("drawtdtools.py:284", _fw_err)
        pm = info.get("pixmap") or ""
        if not pm:
            try:        # TechDraw's GUI not loaded yet (start-up): its icon, put on once it loads
                from . import drawings as D
                pm = D.pixmap(self.native)
            except Exception:
                pm = ""
        return {"MenuText": self.label, "ToolTip": self.tip, "Pixmap": pm}

    def IsActive(self):
        c = self._cmd()
        try:
            return bool(c is not None and c.isActive())
        except Exception:
            return False

    def Activated(self):
        _close_view_pm()
        if self.native in SECTION_TOOLS and not _view_picked():

            try:
                if "FreeWorks_DrawSectionView" in Gui.listCommands():
                    Gui.runCommand("FreeWorks_DrawSectionView", 0)
                    return
            except Exception as error:
                App.Console.PrintLog("FreeCAD: Drawing Tools section: %s\n" % error)
        want = PICK_COUNT.get(self.native)
        if want and not _fits(want[0]):
            # FreeCAD's tool would only say "Wrong selection" / "No sub-elements selected": its page says what to

            try:
                from . import toolfirst
                if toolfirst.show_wait(OWN + self.key, self.key, want[1], want[0]) is not None:
                    return
            except Exception as error:
                App.Console.PrintLog("FreeCAD: Drawing Tools pick: %s\n" % error)
        need = PICK_FIRST.get(self.native)
        if need:
            try:        # case 1625: with the wrong pick FreeCAD's command only says "Wrong selection": wait for it
                from . import toolfirst
                if not toolfirst.fits(need):
                    toolfirst.show_wait(OWN + self.key, self.key)
                    return
            except Exception as error:
                App.Console.PrintLog("FreeCAD: Drawing Tools pick: %s\n" % error)
        try:
            from . import drawscene
            if self.native in FACES_FIRST and not _face_picked():
                drawscene.face_mode(run=self.native)        # pick the face, the tool then runs on it
                return
            if self.native in FACES_LIVE and not Gui.Selection.getSelection():
                drawscene.face_mode(interactive=True)       # FreeCAD's Dimension tool picks as it runs
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Drawing Tools faces: %s\n" % error)
        if self.key == "TDX_MoveView":
            self.move_task = _move_view()
            return
        if self.key in NATIVE_TRANSACTION_TOOLS and App.getActiveTransaction() is None:
            self._run_native_edit()
            return
        Gui.runCommand(self.native, 0)

    def _run_native_edit(self):
        doc = App.ActiveDocument
        if doc is None:
            return
        doc.openTransaction(self.label)
        try:
            Gui.runCommand(self.native, 0)
        except Exception:
            doc.abortTransaction()
            raise
        doc.commitTransaction()



def _move_view():
    # Keep the Move View transaction open until the task completes.
    from TechDrawTools import TaskMoveView, TDToolsMovers

    doc = App.ActiveDocument
    if doc is None or Gui.Control.activeDialog() or App.getActiveTransaction() is not None:
        return None

    class MoveViewTask(TaskMoveView):
        def __init__(self):
            super().__init__()
            self.transaction = App.getActiveTransaction()

        def reject(self):
            if self.transaction and App.getActiveTransaction() == self.transaction:
                App.closeActiveTransaction(True)
            return True

        def accept(self):
            if (App.ActiveDocument is not doc or not self.transaction
                    or App.getActiveTransaction() != self.transaction):
                return False
            view, source, target = (doc.getObject(name) for name in
                                    (self.viewName, self.fromPageName, self.toPageName))
            if (view is None or source is None or target is None or source is target
                    or not source.isDerivedFrom("TechDraw::DrawPage")
                    or not target.isDerivedFrom("TechDraw::DrawPage") or view not in source.Views):
                App.Console.PrintWarning("Select a drawing view and two different sheets.\n")
                return False
            try:
                TDToolsMovers.moveView(view, source, target)
            except Exception:
                self.reject()
                raise
            App.closeActiveTransaction(False)
            return True

    picked = [item for item in Gui.Selection.getSelection() if item.Document is doc]
    view = next((item.Name for item in picked if item.isDerivedFrom("TechDraw::DrawView")), "")
    pages = [item.Name for item in picked if item.isDerivedFrom("TechDraw::DrawPage")]
    source, target = (pages + ["", ""])[:2]
    task = MoveViewTask()
    try:
        task.setValues(view, source, target)
        Gui.Control.showDialog(task)
    except Exception:
        task.reject()
        raise
    return task


NATIVE_TRANSACTION_TOOLS = ("TDX_PositionSection", "TDX_AlignVertH", "TDX_AlignVertV")
PICK_FIRST = {"TechDraw_ArchView": "bimsection", "TechDraw_DraftView": "model"}      # toolfirst.fits kinds
FACES_FIRST = ("TechDraw_FaceCenterLine", "TechDraw_ExtensionAreaAnnotation", "TechDraw_AreaDimension")
FACES_LIVE = ("TechDraw_Dimension",)


SECTION_TOOLS = ("TechDraw_SectionView", "TechDraw_ComplexSection")
_EDGES_POINTS = "Select edges or points of a drawing view."
PICK_COUNT = {         # what FreeCAD's tool needs picked first: (toolfirst pick, the page's text)
    "TechDraw_ComplexSection": ("viewprofile", "Select the view, then the sketch or wire that is the cutting profile "
                                               "(Ctrl+click both)."),
    "TechDraw_ExtensionCreateLengthArc": ("sub:Edge:1", "Select an arc of a drawing view."),
    "TechDraw_ExtensionCreateHorizChainDimension": ("sub:Vertex:2", "Select the points to dimension, in order."),
    "TechDraw_ExtensionCreateVertChainDimension": ("sub:Vertex:2", "Select the points to dimension, in order."),
    "TechDraw_ExtensionCreateObliqueChainDimension": ("sub:Vertex:2", "Select the points to dimension, in order."),
    "TechDraw_ExtensionCreateHorizCoordDimension": ("sub:Vertex:2", "Select the base point, then the points to dimension."),
    "TechDraw_ExtensionCreateVertCoordDimension": ("sub:Vertex:2", "Select the base point, then the points to dimension."),
    "TechDraw_ExtensionCreateObliqueCoordDimension": ("sub:Vertex:2",
                                                      "Select the base point, then the points to dimension."),
    "TechDraw_ExtensionCreateHorizChamferDimension": ("sub:Vertex:2", "Select the two end points of the chamfer."),
    "TechDraw_ExtensionCreateVertChamferDimension": ("sub:Vertex:2", "Select the two end points of the chamfer."),
    "TechDraw_AxoLengthDimension": ("sub:Edge:2", "Select two edges of the view: the one to measure, then one "
                                                  "along the same axis."),
    "TechDraw_HoleShaftFit": ("dims:1", "Select a length or diameter dimension."),
    "TechDraw_ExtensionCascadeHorizDimension": ("dims:2", "Select the horizontal dimensions to space out."),
    "TechDraw_ExtensionCascadeVertDimension": ("dims:2", "Select the vertical dimensions to space out."),
    "TechDraw_ExtensionCascadeObliqueDimension": ("dims:2", "Select the aligned dimensions to space out."),
    "TechDraw_ExtensionPosHorizChainDimension": ("dims:2", "Select the horizontal dimensions to line up."),
    "TechDraw_ExtensionPosVertChainDimension": ("dims:2", "Select the vertical dimensions to line up."),
    "TechDraw_ExtensionPosObliqueChainDimension": ("dims:2", "Select the aligned dimensions to line up."),
    "TechDraw_ExtensionHoleCircle": ("sub:Edge:3", "Select three or more circles of a drawing view."),
    "TechDraw_2LineCenterLine": ("sub:Edge:2", "Select two edges of a drawing view."),
    "TechDraw_2PointCenterLine": ("sub:Vertex:2", "Select two points of a drawing view."),
    "TechDraw_Midpoints": ("sub:Edge:1", "Select edges of a drawing view."),
    "TechDraw_Quadrants": ("sub:Edge:1", "Select circles or arcs of a drawing view."),
    "TechDraw_CommandAddOffsetVertex": ("sub:Vertex:1", "Select a point of a drawing view."),
    "TechDraw_CosmeticCircle": ("sub:Vertex:1", "Select the point for the circle's center."),
    "TechDraw_2PointCosmeticLine": ("sub:Vertex:2", "Select two points of a drawing view."),
}


def _fits(pick):
    try:
        from . import toolfirst
        return toolfirst.fits(pick)
    except Exception:
        return True                       # never block the tool when the check itself fails


def _view_picked():
    try:
        return any(o.isDerivedFrom("TechDraw::DrawViewPart") for o in Gui.Selection.getSelection())
    except Exception:
        return False


def _face_picked():
    try:
        return any(str(n).split(".")[-1].startswith("Face") for s in Gui.Selection.getSelectionEx()
                   for n in s.SubElementNames)
    except Exception:
        return False


def _close_view_pm():
    ""


    try:
        from . import drawings as D
        if not (D.VIEW_PM and Gui.Control.activeDialog()):
            return
        picked = [(s.DocumentName, s.ObjectName, list(s.SubElementNames)) for s in Gui.Selection.getSelectionEx()]
        from . import drawselect
        drawselect.close_open()
        Gui.Selection.clearSelection()
        for doc, name, subs in picked:
            for sub in (subs or [""]):
                Gui.Selection.addSelection(doc, name, sub)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Drawing Tools: %s\n" % error)


def _add_commands():
    ""

    have = set(Gui.listCommands())
    for key, label, native, tip in KEYS:
        if OWN + key not in have:
            Gui.addCommand(OWN + key, ToolCommand(key, label, native, tip))


def _hidden():
    try:
        from . import cmtabs
        return TAB in cmtabs.hidden()
    except Exception as _fw_err:
        _fw_log("drawtdtools.py:340", _fw_err)
        return False


def install():
    """The catalog keys and the wrapped catalog.drawing_tabs (once)."""
    if Gui is None:
        return
    try:
        from . import catalog
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Drawing Tools tab not added (%s)\n" % error)
        return
    _add_commands()
    for key, label, native, tip in KEYS:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (OWN + key, native), None, tip)
    catalog.ALL = tuple(catalog._ALL)
    original = getattr(catalog, "drawing_tabs", None)
    if original is None or getattr(original, "_fw_tdx", False):
        return

    def drawing_tabs(part_tabs):
        tabs = list(original(part_tabs))
        if _hidden():
            return tuple(tabs)
        spec = layout()
        if spec:
            tabs.append((TAB, spec))
        return tuple(tabs)

    drawing_tabs._fw_tdx = True
    drawing_tabs.__doc__ = original.__doc__
    catalog.drawing_tabs = drawing_tabs


def register():
    try:
        install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Drawing Tools tab not added (%s)\n" % error)
