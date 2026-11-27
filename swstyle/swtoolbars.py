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
from PySide import QtCore, QtWidgets

from . import catalog, customizedlg
from .widgets import CommandButton, alive

Qt = QtCore.Qt
PARAM = "User parameter:BaseApp/Preferences/Mod/SolidWorksStyle/Toolbars"
PREFIX = "SWToolbar_"
# Toolbars another module builds (the tick here shows or hides that one instead of making a _Bar):

FOREIGN = {"Layer": ("drawpmparts", "layer_bar")}


# A name with no keys that exist is shown greyed, as a toolbar there is nothing to put on.
TOOLBARS = (
    ("2D to 3D", ("2Dto3DFront", "2Dto3DTop", "2Dto3DRight", "2Dto3DBottom", "2Dto3DLeft", "2Dto3DBack",
                  "2Dto3DAuxiliary", "2Dto3DExtrude", "2Dto3DCut", "AlignSketch", "AlignGridOrigin", "RepairSketch")),
    ("Align", ("DrawAlignHorizontalOrigin", "DrawAlignVerticalOrigin", "DrawAlignHorizontalCenter",
               "DrawAlignVerticalCenter", "DrawDefaultAlignment", "DrawBreakAlignment",
               "DrawDimAutoArrange", "DrawDimAlignCollinear", "DrawDimAlignParallel", "DrawDimSpaceEvenly",
               "DrawDimBreakAlignment")),
    ("Annotation", ("DrawNote", "DrawBalloon", "DrawAutoBalloon", "DrawStackedBalloon", "DrawMagneticLine",
                    "DrawSurfaceFinish", "DrawWeldSymbol", "DrawGeometricTolerance", "DrawDatumFeature",
                    "DrawDatumTarget", "DrawHoleCallout", "DrawCenterMark", "DrawCenterline", "DrawAreaHatch",
                    "DrawRevisionSymbol", "DrawRevisionCloud", "DrawMultiJogLeader", "DrawDowelPin",
                    "DrawLocationLabel", "DrawModelItems", "DrawFormatPainter", "DrawSpellChecker")),
    ("Assembly", ("CreateAssembly", "InsertPart", "Interference", "Measure", "MassProperties")),
    ("Blocks", ("MakeBlock", "EditBlock", "InsertBlock", "AddRemoveBlockEntities", "RebuildBlocks", "SaveBlock",
                "ExplodeBlock")),
    ("Configurations", ("DesignTable", "Equations", "ChangeDisplayStates", "AddDisplayState")),
    ("Curves", ("SplitLine", "ProjectedCurve", "CompositeCurve", "CurveThroughXYZPoints",
                "CurveThroughReferencePoints", "HelixSpiral")),
    ("Dimensions/Relations", ("SmartDimension", "HorizontalDimension", "VerticalDimension", "BaselineDimension",
                              "OrdinateDimension", "HorizontalOrdinateDimension", "VerticalOrdinateDimension",
                              "ChamferDimension", "PathLengthDimension", "AddRelation", "ViewSketchRelations",
                              "ScanEqual", "FullyDefineSketch", "SketchXpert")),
    ("MBD Dimension", ("SmartDimension", "AngularDimension", "RadiusDimension", "ChainDimension",
                       "SymmetricLinearDiameterDimension", "DrawGeometricTolerance", "DrawDatumFeature")),
    ("Display States", ("ChangeDisplayStates", "AddDisplayState", "Transparency", "EditAppearance")),
    ("Drawing", ("DrawModelView", "DrawProjectedView", "DrawAuxiliaryView", "DrawSectionView", "DrawRemovedSection",
                 "DrawDetailView", "DrawRelativeView", "DrawStandard3View", "DrawBrokenOut", "DrawBreak", "DrawCrop",
                 "DrawAlternatePosition", "DrawEmptyView", "DrawPredefinedView", "DrawUpdateView",
                 "DrawReplaceModel")),
    ("Explode Sketch", ("Sketch3D", "Exit3DSketch", "Line", "JogLine", "RouteLine")),
    ("Features", ("BossExtrude", "BossRevolve", "BossSweep", "BossLoft", "BossBoundary", "CutExtrude", "Hole",
                  "CutRevolve", "CutSweep", "CutLoft", "CutBoundary", "Fillet", "Chamfer", "LinearPattern",
                  "CircularPattern", "Mirror", "Rib", "Draft", "Shell", "Wrap", "Intersect", "Combine", "SplitBody",
                  "MoveCopyBodies", "DeleteKeepBody", "Scale", "Dome", "Thread", "ReferenceGeometry", "Curves",
                  "Instant3D")),
    ("Formatting", ("Text", "DrawNote", "LineFormat", "LineColor", "LineThickness", "LineStyle")),
    ("FreeShape", ("Freeform", "Deform", "Flex", "Indent")),
    ("Layer", ("DrawLayerProperties", "LineFormat", "LineColor", "LineThickness", "LineStyle")),
    ("Layout Tools", ("Sketch", "MakeBlock", "EditBlock", "InsertBlock", "ExplodeBlock", "CreateAssembly")),
    ("Line Format", ("DrawLayerProperties", "LineFormat", "LineColor", "LineThickness", "LineStyle")),
    ("Macro", ("MacroRun", "MacroRecord", "MacroStop", "MacroNew", "MacroEdit")),
    ("Markup", ("Markup", "SketchInk", "PenDraw", "PenEraser", "PenSelect", "GoToMarkupView")),
    ("Mold Tools", ("PartingLine", "ShutOffSurfaces", "PartingSurface", "ToolingSplit", "MoldCore", "Cavity",
                    "MoldFolders", "DraftAnalysis", "UndercutAnalysis", "PartingLineAnalysis", "SplitLine",
                    "Draft", "MoveFace", "Scale", "RuledSurface", "KnitSurface", "PlanarSurface")),
    ("MotionManager", ("DesignStudy",)),
    ("Quick Snaps", ("QSPoint", "QSCenterPoint", "QSMidpoint", "QSQuadrant", "QSIntersection", "QSNearest",
                     "QSTangent", "QSPerpendicular", "QSParallel", "QSHV", "QSHVPoint", "QSLength", "QSGrid",
                     "QSAngle", "QuickSnaps")),
    ("Reference Geometry", ("Plane", "Axis", "CoordinateSystem", "Point", "CenterOfMass", "BoundingBox",
                            "ShapeBinder")),
    ("Render Tools", ("ApplyScene", "EditAppearance", "ViewSettings", "ShadowsInShadedMode", "Perspective",
                      "AddCamera", "Cartoon")),
    ("Screen Capture", ("TakeSnapshot", "AddWalkThrough", "PlayWalkThrough")),
    ("Selection Filter", ("PowerSelect", "InvertSelection", "SelectAll", "BoxSelect", "LassoSelect",
                          "MagnifiedSelection")),
    ("Sheet Format", ("DrawEditSheetFormat", "DrawEditSheet", "DrawTitleBlockFields", "DrawAutomaticBorder",
                      "DrawSaveSheetFormat", "DrawSheetProperties")),
    ("Sheet Metal", ("SM_BaseFlange", "SM_Convert", "SM_LoftedBend", "SM_EdgeFlange", "SM_MiterFlange", "SM_Hem",
                     "SM_SweptFlange", "SM_Jog", "SM_SketchedBend", "SM_CrossBreak", "SM_Corners", "SM_ClosedCorner",
                     "SM_WeldedCorner", "SM_BreakCorner", "SM_CornerTrim", "SM_CornerRelief", "SM_FormingTool",
                     "SM_Vent", "SM_TabAndSlot", "SM_NormalCut", "SM_Unfold", "SM_Fold", "SM_Flatten", "SM_NoBends",
                     "SM_InsertBends", "SM_Rip", "SM_Gusset", "SM_BendNotch", "SM_ExportDXF")),
    ("Sketch", ("Sketch", "Sketch3D", "SmartDimension", "Line", "CornerRectangle", "Slot", "Circle", "CenterArc",
                "Polygon", "Spline", "Ellipse", "SketchFillet", "Text", "SketchPoint", "Centerline", "Trim", "Extend",
                "Convert", "Offset", "MirrorEntities", "LinearSketchPattern", "MoveEntities", "AddRelation",
                "ViewSketchRelations", "RapidSketch", "QuickSnaps", "SketchPicture")),
    ("Sketch Ink", ("SketchInk", "PenSketch", "PenDraw", "PenEraser", "PenSelect", "PenRuler", "PenProtractor",
                    "PenConvertToShape", "PenConvertToEntities")),
    ("MBD", ("DrawGeometricTolerance", "DrawDatumFeature", "DrawDatumTarget", "DrawSurfaceFinish", "DrawWeldSymbol",
             "ViewAllAnnotations", "SmartDimension")),
    ("Add-Ins", ("WB_FEM", "WB_CAM", "WB_Spreadsheet", "WB_Draft", "WB_Mesh", "WB_Surface",
                            "WB_SheetMetal", "AddonManager")),
    ("Spline Tools", ("AddTangencyControl", "AddCurvatureControl", "InsertSplinePoint", "InsertControlVertex",
                      "SimplifySpline", "RelaxSpline", "FitSpline", "ShowSplineHandles", "ShowInflectionPoints",
                      "ShowMinimumRadius", "ShowCurvatureCombs", "ConvertToSpline", "ConvertToStyleSpline",
                      "SplineProportional")),
    ("Standard", ("New", "Open", "Save", "SaveAs", "SaveAll", "Print", "Undo", "Redo", "Select", "Rebuild",
                  "FileProperties", "Options", "Help")),
    ("Standard Views", ("ViewFront", "ViewBack", "ViewLeft", "ViewRight", "ViewTop", "ViewBottom", "ViewIsometric",
                        "ViewTrimetric", "ViewDimetric", "NormalTo", "ViewOrientation")),
    ("Structure System", ("WE_StructureSystem", "WE_PrimaryMember", "WE_SecondaryMember", "WE_DefineConnection",
                          "WE_InsertConnection", "WE_PatternConnection", "WE_PiercePoint")),
    ("Surfaces", ("ExtrudedSurface", "RevolvedSurface", "SweptSurface", "LoftedSurface", "BoundarySurface",
                  "FilledSurface", "PlanarSurface", "OffsetSurface", "MidSurface", "RuledSurface", "KnitSurface",
                  "ExtendSurface", "TrimSurface", "UntrimSurface", "SurfaceFillet", "Thicken", "ThickenedCut",
                  "CutWithSurface", "DeleteFace", "ReplaceFace", "SurfaceFlatten")),
    ("Table", ("DrawGeneralTable", "DrawTitleBlockTable", "DrawHoleTable", "DrawBOM", "DrawRevisionTable", "DrawWeldTable", "DrawBendTable",
               "DrawPunchTable", "DesignTable")),
    ("Task Pane", ("Home", "DrawViewPalette", "EditAppearance", "ViewSettings")),
    ("Tools", ("Measure", "MassProperties", "SectionProperties", "Interference", "Check", "DeviationAnalysis",
               "Equations", "FeaturePaint", "Sensor", "PerformanceEvaluation", "CompareDocuments", "Macros")),
    ("View", ("PreviousView", "Redraw", "ZoomFit", "ZoomArea", "ZoomSelection", "ViewSelector", "SectionView",
              "Wireframe", "HiddenLinesVisible", "HiddenLinesRemoved", "ShadedEdges", "Shaded", "Perspective",
              "HideShowItems", "ViewPlanes", "ViewOrigins", "ViewSketches", "ViewGrid")),
    ("View (Heads-Up)", ("ZoomFit", "ZoomArea", "PreviousView", "SectionView", "ViewOrientation", "DisplayStyle",
                         "HideShowItems", "EditAppearance", "ApplyScene", "ViewSettings")),
    ("Web", ("Help", "AddonManager")),
    ("Weldments", ("WE_Weldment", "WE_StructuralMember", "WE_TrimExtend", "WE_EndCap", "WE_Gusset", "WE_WeldBead",
                   "WE_CutList", "Sketch3D")),
    ("Lifecycle and Collaboration", ("SaveCopy", "Export", "Import", "FileProperties", "AddComment")),
)

# Access row and the Heads-Up row), so none starts shown; every row can be shown from the menu.


def _param():
    return App.ParamGet(PARAM)


def doc_kind():
    ""
    try:
        from . import asmui
        kind = getattr(asmui, "_showing", None) or "part"
    except Exception:
        kind = "part"
    return "part" if kind == "edit" else kind


KINDS = ("part", "assembly", "drawing")


def _shown_names(kind=None):
    g = _param()
    key = "Shown." + (kind or doc_kind())
    text = g.GetString(key, "") if key in g.GetStrings() else g.GetString("Shown", "")   # older: one list for all
    return [n for n in text.split("|") if n]


def _remember(name, on):
    names = _shown_names()
    if on and name not in names:
        names.append(name)
    if not on and name in names:
        names.remove(name)
    g = _param()
    have = g.GetStrings()
    if not any(("Shown." + k) in have for k in KINDS):
        legacy = g.GetString("Shown", "")
        for k in KINDS:               # the one older list becomes each type's starting list
            g.SetString("Shown." + k, legacy)
    g.SetString("Shown." + doc_kind(), "|".join(names))


_KIND = []


def apply_kind(shell, force=False):
    ""
    kind = doc_kind()
    if _KIND == [kind] and not force:
        return False
    _KIND[:] = [kind]
    want = set(_shown_names(kind))
    for name, _keys in TOOLBARS:
        try:
            if (name in want) != is_shown(name):
                show(shell, name, name in want, remember=False)
        except Exception as _fw_err:
            _fw_log("swtoolbars.py:apply_kind", _fw_err)
    return True


def _installed(key):
    """rcmenus pkg230: a workbench button (Add-Ins toolbar) whose workbench this FreeCAD does not have is left
    out, as the Add-Ins CommandManager tab leaves it out (addintabs), instead of sitting greyed for good."""
    cmd = catalog.BY_KEY.get(key)
    call = getattr(cmd, "call", None) or ""
    if not call.startswith("wb:"):
        return True
    try:
        return call[3:] in Gui.listWorkbenches()
    except Exception:
        return True


def keys_of(name, extras=True):
    """The toolbar's commands, with the ones added to it in Customize > Commands after them."""
    for title, keys in TOOLBARS:
        if title == name:
            out = tuple(k for k in keys if k in catalog.BY_KEY and _installed(k))
            if extras:
                out += tuple(k for k in customizedlg.toolbar_extras(name) if k not in out)
            return out
    return ()


def _area_int(area):
    """Qt.ToolBarArea as a number: PySide 6's enums are not int()-able (customize239 found
    'int() argument must be ... not ToolBarArea' when a toolbar was shown from Customize)."""
    try:
        return int(area)
    except TypeError:
        return int(getattr(area, "value", 4))


def _object_name(name):
    return PREFIX + "".join(ch if ch.isalnum() else "_" for ch in name)


def _foreign(name):
    """The other module's toolbar for a FOREIGN name, or None."""
    spec = FOREIGN.get(name)
    if not spec:
        return None
    try:
        import importlib
        return getattr(importlib.import_module(__package__ + "." + spec[0]), spec[1])()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: toolbar %s: %s\n" % (name, error))
        return None


def find(name):
    if name in FOREIGN:
        return _foreign(name)
    mw = Gui.getMainWindow()
    return mw.findChild(QtWidgets.QToolBar, _object_name(name)) if mw is not None else None



# Toolbars) these two rows are the panes themselves, ticked while shown (read chrome.md A3, READ-LIST-1119)
PANES = ("Task Pane", "MotionManager")


def listed_shown(name):
    if name in PANES:
        try:
            from . import uiextras
            if name == "Task Pane":
                return bool(uiextras.task_pane_shown() and uiextras._tasks_widget() is not None)
            return bool(uiextras.motion_manager_shown())
        except Exception as _fw_err:
            _fw_log("swtoolbars.py:pane-shown", _fw_err)
            return False
    return is_shown(name)


def listed_show(shell, name, on):
    if name in PANES:
        from . import uiextras
        (uiextras.set_task_pane if name == "Task Pane" else uiextras.set_motion_manager)(bool(on))
        return None
    return show(shell, name, on)


def is_shown(name):
    bar = find(name)
    return bar is not None and alive(bar) and bar.isVisible()


class _Bar(QtWidgets.QToolBar):
    ""

    def __init__(self, shell, name, parent):
        super().__init__(name, parent)
        self.setObjectName(_object_name(name))
        self.name = name
        self.setAllowedAreas(Qt.AllToolBarAreas)
        locked = customizedlg.option("LockToolbars")
        self.setMovable(not locked)
        self.setFloatable(not locked)
        self.setIconSize(QtCore.QSize(customizedlg.icon_px(), customizedlg.icon_px()))
        self.setAcceptDrops(True)
        self.shell = shell
        self.buttons = []
        for key in keys_of(name):
            try:
                # a flyout-only button (Hide/Show Items, View Settings) keeps its list here too: without
                # it a click would do nothing
                flyout = None
                cmd = catalog.BY_KEY.get(key)
                if cmd is not None and cmd.call in ("menu", "scene_menu"):
                    flyout = dict((k, f) for k, f in catalog.HEADS_UP).get(key)
                b = CommandButton(shell, key, flyout, "stack", self)
                if hasattr(b, "set_show_mode"):
                    b.set_show_mode(CommandButton.NO_TEXT)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: toolbar %s: no button for %s: %s\n" % (name, key, error))
                continue
            self.addWidget(b)
            self.buttons.append(b)
        self.visibilityChanged.connect(self._visible)

    def _visible(self, on):
        _remember(self.name, bool(on))


    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(customizedlg.MIME) and customizedlg.is_open():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        self.dragEnterEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasFormat(customizedlg.MIME) and customizedlg.is_open():
            key = bytes(e.mimeData().data(customizedlg.MIME)).decode()
            customizedlg._open[0].add_to_toolbar(self.name, key)
            e.acceptProposedAction()
        else:
            e.ignore()


def rebuild(shell, name):
    """Makes the toolbar again (its commands changed in Customize), keeping it where it was."""
    bar = find(name)
    if name in FOREIGN or bar is None or not alive(bar):
        return bar
    mw = Gui.getMainWindow()
    shown = bar.isVisible()
    try:
        _param().SetInt("Area_" + bar.objectName(), _area_int(mw.toolBarArea(bar)))
        bar.blockSignals(True)
        mw.removeToolBar(bar)
        bar.setObjectName(bar.objectName() + "_gone")       # find() must not see it until deleteLater runs
        bar.deleteLater()
    except Exception as _fw_err:
        _fw_log("swtoolbars.py:275", _fw_err)
    return show(shell, name, True) if shown else None


def apply_icon_size():
    ""
    mw = Gui.getMainWindow()
    px = customizedlg.icon_px()
    for bar in mw.findChildren(QtWidgets.QToolBar) if mw is not None else ():
        if bar.objectName().startswith(PREFIX):
            bar.setIconSize(QtCore.QSize(px, px))
            for b in getattr(bar, "buttons", ()):
                if hasattr(b, "set_icon_px"):
                    b.set_icon_px(px)


def apply_lock():
    """Customize > Customization > Lock CommandManager and toolbars."""
    mw = Gui.getMainWindow()
    locked = customizedlg.option("LockToolbars")
    for bar in mw.findChildren(QtWidgets.QToolBar) if mw is not None else ():
        if bar.objectName().startswith(PREFIX):
            bar.setMovable(not locked)
            bar.setFloatable(not locked)


def show(shell, name, on=True, remember=True):
    ""
    mw = Gui.getMainWindow()
    bar = find(name)
    if not on:
        if bar is not None and alive(bar):
            bar.hide()
        if remember:
            _remember(name, False)
        return bar
    if name in FOREIGN:
        if bar is not None and alive(bar):
            bar.show()
            if remember:
                _remember(name, True)
        return bar
    if not keys_of(name):
        return None
    if bar is None or not alive(bar):
        bar = _Bar(shell, name, mw)
        area = _param().GetInt("Area_" + _object_name(name), _area_int(Qt.TopToolBarArea))
        try:
            mw.addToolBar(Qt.ToolBarArea(area), bar)
        except Exception:
            mw.addToolBar(Qt.TopToolBarArea, bar)
    bar.show()
    if remember:
        _remember(name, True)
    return bar


def toggle(shell, name):
    return show(shell, name, not is_shown(name))


def restore(shell):
    ""
    for name in _shown_names():
        try:
            show(shell, name, True)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: toolbar %s not restored: %s\n" % (name, error))


def remove():
    mw = Gui.getMainWindow()
    if mw is None:
        return
    for bar in mw.findChildren(QtWidgets.QToolBar):
        if bar.objectName().startswith(PREFIX):
            try:
                _param().SetInt("Area_" + bar.objectName(), _area_int(mw.toolBarArea(bar)))
                bar.blockSignals(True)
                mw.removeToolBar(bar)
                bar.deleteLater()
            except Exception as _fw_err:
                _fw_log("swtoolbars.py:354", _fw_err)


# --------------------------------------------------------------------------- the CommandManager tick
def command_manager_enabled(shell):
    bar = getattr(shell, "topbar", None) if shell is not None else None
    return bar is not None and alive(bar) and not getattr(bar, "collapsed", False)


def toggle_command_manager(shell):
    bar = getattr(shell, "topbar", None) if shell is not None else None
    if bar is not None and alive(bar) and hasattr(bar, "toggle_collapsed"):
        bar.toggle_collapsed()


def customize():
    ""
    try:
        customizedlg.show()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Customize did not open: %s\n" % error)
        try:
            Gui.runCommand("Std_DlgCustomize", 0)
        except Exception as _fw_err:
            _fw_log("swtoolbars.py:378", _fw_err)


def fill_menu(menu, shell):
    ""
    act = menu.addAction("Enable CommandManager")
    act.setCheckable(True)
    act.setChecked(command_manager_enabled(shell))
    act.triggered.connect(lambda checked=False: toggle_command_manager(shell))
    menu.addSeparator()
    for name, _ in TOOLBARS:
        act = menu.addAction(name)
        act.setCheckable(True)
        act.setChecked(listed_shown(name))           # cmmenu-1126
        act.setEnabled(bool(keys_of(name)) or name in PANES or (name in FOREIGN and find(name) is not None))
        act.triggered.connect(lambda checked=False, n=name: listed_show(shell, n, not listed_shown(n)))
    menu.addSeparator()
    act = menu.addAction("Customize...")
    act.triggered.connect(customize)
    return True
