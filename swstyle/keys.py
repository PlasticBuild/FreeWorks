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
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt

SHORTCUT = "User parameter:BaseApp/Preferences/Shortcut"

# (command, key); an empty key takes FreeCAD's own key off that command.
KEYS = (


    ("SWStyle_CloseDocument", "Ctrl+W"),
    ("Std_CloseActiveWindow", ""),
    # the standard views through namedviews.py, which keeps an Update Standard Views turn
    ("SWStyle_StandardFront", "Ctrl+1"),
    ("SWStyle_StandardBack", "Ctrl+2"),
    ("SWStyle_StandardLeft", "Ctrl+3"),
    ("SWStyle_StandardRight", "Ctrl+4"),
    ("SWStyle_StandardTop", "Ctrl+5"),
    ("SWStyle_StandardBottom", "Ctrl+6"),
    ("SWStyle_StandardIsometric", "Ctrl+7"),
    ("Std_ViewFront", ""),
    ("Std_ViewRear", ""),
    ("Std_ViewLeft", ""),
    ("Std_ViewRight", ""),
    ("Std_ViewTop", ""),
    ("Std_ViewBottom", ""),
    ("Std_ViewIsometric", ""),
    ("SWStyle_NormalTo", "Ctrl+8"),
    ("SWStyle_ZoomFit", "F"),
    ("SWStyle_ViewOrientation", "Space"),
    ("Std_ToggleVisibility", ""),
    ("SWStyle_ShortcutBar", "S"),
    ("Sketcher_ConstrainSymmetric", ""),
    ("Std_SelBack", ""),
    ("Std_SelForward", ""),
    ("Std_LinkSelectLinked", ""),
    ("Std_LinkSelectLinkedFinal", ""),

    ("SWStyle_SelectionFilterToolbar", "F5"),
    ("Std_Refresh", ""),
    ("SWStyle_ToggleSelectionFilters", "F6"),
    ("Std_MacroStartDebug", ""),
    ("SWStyle_FilterEdges", "E"),
    ("SWStyle_FilterVertices", "V"),
    ("SWStyle_FilterFaces", "X"),
    ("Sketcher_ConstrainEqual", ""),
    ("Sketcher_ConstrainVertical", ""),
    # FreeCAD's V, ... sequences would hold V back (V, F is fit all: F above)
    ("Std_OrthographicCamera", ""),
    ("Std_PerspectiveCamera", ""),
    ("Std_ToggleTransparency", ""),
    ("Std_ViewDock", ""),
    ("Std_ViewUndock", ""),
    ("Std_ViewFitSelection", ""),
    ("SWStyle_Rebuild", "Ctrl+B"),
    ("Std_ViewBoxZoom", ""),
    ("SWStyle_ForceRebuild", "Ctrl+Q"),
    ("Std_Quit", ""),
    ("Std_ViewZoomOut", "Z"),
    ("Std_ViewZoomIn", "Shift+Z"),
    ("SWStyle_PreviousView", "Ctrl+Shift+Z"),
    ("Std_Redo", "Ctrl+Y"),
    ("SWStyle_NewDocument", "Ctrl+N"),
    ("Std_New", ""),
    ("SWStyle_Open", "Ctrl+O"),
    ("Std_Open", ""),
    # FreeCAD's Z, ... sequences would hold Z back
    ("Sketcher_SelectElementsAssociatedWithConstraints", ""),
    ("Sketcher_SelectElementsWithDoFs", ""),
    ("Sketcher_SelectHorizontalAxis", ""),
    ("Sketcher_RestoreInternalAlignmentGeometry", ""),
    ("Sketcher_SelectConstraints", ""),
    ("Sketcher_SelectOrigin", ""),
    ("Sketcher_Rotate", ""),
    ("Sketcher_SelectConflictingConstraints", ""),
    ("Sketcher_SelectRedundantConstraints", ""),
    ("Sketcher_Scale", ""),
    ("Sketcher_RemoveAxesAlignment", ""),
    ("Sketcher_Symmetry", ""),
    ("Sketcher_Offset", ""),
    ("Sketcher_SelectVerticalAxis", ""),
    ("Sketcher_SwitchVirtualSpace", ""),

    ("SWStyle_MagnifiedSelection", "G"),
    ("Sketcher_CarbonCopy", ""),
    ("Sketcher_CompCreateArc", ""),
    ("Sketcher_CompCreateBSpline", ""),
    ("Sketcher_CompCreateConic", ""),
    ("Sketcher_CompCreateFillets", ""),
    ("Sketcher_CompCreateRectangles", ""),
    ("Sketcher_CompCreateRegularPolygon", ""),
    ("Sketcher_CompCurveEdition", ""),
    ("Sketcher_CompExternal", ""),
    ("Sketcher_CompSlot", ""),
    ("Sketcher_Create3PointArc", ""),
    ("Sketcher_Create3PointCircle", ""),
    ("Sketcher_CreateArc", ""),
    ("Sketcher_CreateArcOfEllipse", ""),
    ("Sketcher_CreateArcOfHyperbola", ""),
    ("Sketcher_CreateArcOfParabola", ""),
    ("Sketcher_CreateArcSlot", ""),
    ("Sketcher_CreateBSpline", ""),
    ("Sketcher_CreateBSplineByInterpolation", ""),
    ("Sketcher_CreateChamfer", ""),
    ("Sketcher_CreateCircle", ""),
    ("Sketcher_CreateEllipseBy3Points", ""),
    ("Sketcher_CreateEllipseByCenter", ""),
    ("Sketcher_CreateFillet", ""),
    ("Sketcher_CreateHeptagon", ""),
    ("Sketcher_CreateHexagon", ""),
    ("Sketcher_CreateLine", ""),
    ("Sketcher_CreateOblong", ""),
    ("Sketcher_CreateOctagon", ""),
    ("Sketcher_CreatePentagon", ""),
    ("Sketcher_CreatePeriodicBSpline", ""),
    ("Sketcher_CreatePeriodicBSplineByInterpolation", ""),
    ("Sketcher_CreatePoint", ""),
    ("Sketcher_CreatePolyline", ""),
    ("Sketcher_CreateRectangle", ""),
    ("Sketcher_CreateRectangle_Center", ""),
    ("Sketcher_CreateRegularPolygon", ""),
    ("Sketcher_CreateSlot", ""),
    ("Sketcher_CreateSquare", ""),
    ("Sketcher_CreateTriangle", ""),
    ("Sketcher_Extend", ""),
    ("Sketcher_Intersection", ""),
    ("Sketcher_Projection", ""),
    ("Sketcher_Split", ""),
    ("Sketcher_ToggleConstruction", ""),
    ("Sketcher_Trimming", ""),
    ("Std_ClarifySelection", ""),
    # the arrow keys belong to the 3D view (viewkeys.py)
    ("Std_ViewRotateLeft", ""),
    ("Std_ViewRotateRight", ""),
    ("Std_DockOverlayToggleLeft", ""),
    ("Std_DockOverlayToggleRight", ""),
    ("Std_DockOverlayToggleTop", ""),
    ("Std_DockOverlayToggleBottom", ""),

    ("SWStyle_BrowseRecentDocuments", "R"),

    ("SWStyle_Print", "Ctrl+P"),
    ("Std_Print", ""),
    ("FreeWorks_Line", "L"),
    ("SWStyle_SelectOverGeometry", "T"),        # Select over Geometry (boxselect.py)
    ("SWStyle_BoxSelection", ""),
    ("SWStyle_SearchCommands", "W"),
    ("Sketcher_Translate", ""),
    ("SWStyle_SearchHelp", "H"),
    ("SWStyle_Welcome", "Ctrl+F2"),

    # online help stays in Help > FreeCAD without a key
    ("FreeWorks_ContextHelp", "F1"),
    ("Std_OnlineHelp", ""),

    ("SWStyle_TaskPaneKey", "Ctrl+F1"),
    ("SWStyle_ToggleNotesUpperCase", "Shift+F3"),
    ("SWStyle_ToggleRadialDisplay", "Ctrl+D"),
    ("SWStyle_SelectAnnotationView", "'"),
    ("SWStyle_Redraw", "Ctrl+R"),
    ("SWStyle_RebuildAllConfigurations", "Ctrl+Shift+B"),
    ("SWStyle_ForceRebuildAllConfigurations", "Ctrl+Shift+Q"),
    ("SWStyle_CopyAppearance", "Ctrl+Shift+C"),
    ("SWStyle_PasteAppearance", "Ctrl+Shift+V"),
    ("Std_SetAppearance", ""),
    ("SWStyle_FindModify", "Ctrl+F"),
    ("SWStyle_ExpandCollapseTree", "C"),
    ("SWStyle_CollapseAllItems", "Shift+C"),
    ("SWStyle_TreeTop", "Home"),
    ("Std_ViewHome", ""),
    ("SWStyle_TreeBottom", "End"),
    ("Std_RecallWorkingView", ""),
    ("SWStyle_ToggleReferenceGeometry", "Q"),
    ("SWStyle_FeatureManagerArea", "F9"),
    ("Std_ToggleBreakpoint", ""),
    ("SWStyle_ToggleCommandManager", "F10"),
    ("Std_MacroStepOver", ""),
    ("Std_MainFullscreen", "F11"),
    ("Std_ViewFullscreen", ""),
    ("Std_MacroStepInto", ""),
    ("SWStyle_ViewSelectorKey", "Ctrl+Space"),
    ("SWStyle_NextCommandManagerTab", "Ctrl+PgDown"),
    ("SWStyle_PreviousCommandManagerTab", "Ctrl+PgUp"),
    ("SWStyle_QuickSnapsToggle", "F3"),
    ("SWStyle_NextEdge", "N"),
    ("SWStyle_AcceptEdge", "Y"),
    ("SWStyle_SearchFiles", "I"),
    ("SWStyle_FlatTreeView", "Ctrl+T"),
    ("SWStyle_DisplayPane", "F8"),
    ("FreeWorks_DrawSpellChecker", "F7"),

    ("SWStyle_SpeedPakGraphicsCircle", "Alt+S"),
    ("SWStyle_TakeSnapshot", "Alt+Space"),

    # Sketcher's Horizontal/Vertical and Dimension, TechDraw's Dimension, the Assembly's Distance joint and New Assembly.

    ("Sketcher_ConstrainHorVer", ""),
    ("TechDraw_Dimension", ""),
    ("Sketcher_Dimension", ""),
    ("Assembly_CreateJointDistance", ""),
    ("Assembly_CreateAssembly", ""),

    # (C, H, I, L, N, T, Q, F, G, R, S, W, X, Z, E, V: checked in every mode), so FreeCAD's key never ran its
    # command, yet its menu row and tip still showed it. They are taken off; each command stays in its menu and
    # toolbar, and Customize > Keyboard can give it a free key. Their own two-key sequences that start with one

    ("Sketcher_ConstrainCoincidentUnified", ""), ("Sketcher_ConstrainHorizontal", ""),
    ("Sketcher_ConstrainDistanceX", ""), ("Sketcher_ConstrainDistanceY", ""),
    ("Sketcher_ConstrainPerpendicular", ""), ("Sketcher_ConstrainTangent", ""),
    ("Sketcher_ViewSketch", ""), ("Sketcher_ViewSection", ""),
    ("Assembly_CreateJointFixed", ""), ("Assembly_CreateJointRevolute", ""), ("Assembly_CreateJointCylindrical", ""),
    ("Assembly_CreateJointSlider", ""), ("Assembly_CreateJointParallel", ""), ("Assembly_CreateJointAngle", ""),
    ("Assembly_CreateJointRackPinion", ""), ("Assembly_CreateJointScrew", ""), ("Assembly_CreateJointGears", ""),
    ("Assembly_CreateJointBelt", ""), ("Assembly_ToggleGrounded", ""), ("Assembly_CreateSimulation", ""),
    ("Assembly_CreateView", ""), ("Assembly_InsertLink", ""), ("Assembly_SolveAssembly", ""),
    ("FEM_Analysis", ""), ("FEM_SolverCalculiX", ""), ("FEM_SolverControl", ""), ("FEM_SolverRun", ""),
    ("FEM_SolverElmer", ""), ("FEM_SolverMystran", ""), ("FEM_SolverZ88", ""),
    ("FEM_ResultsPurge", ""), ("FEM_ResultShow", ""), ("FEM_PostFilterGlyph", ""),
    # Ctrl+Shift+Tab shows the hidden bodies in the 3D view (swkeys.HoverKeys)
    ("Std_ActivatePrevWindow", ""),
    ("SWStyle_BrowseOpenDocuments", "Ctrl+Tab"),
    ("SWStyle_SaveAs", "Ctrl+Shift+S"),
    ("SWStyle_Save", "Ctrl+S"),                         # swsave.py: a new drawing's first Save is Save As
    ("Std_Save", ""),
    ("Std_ActivateNextWindow", ""),
    # FreeCAD's T, ... tree and A, C axis sequences would hold T and A back (A switches line and arc)
    ("Std_DockOverlayMouseTransparent", ""),
    ("Std_TreeDrag", ""),
    ("Std_TreePreSelection", ""),
    ("Std_TreeRecordSelection", ""),
    ("Std_TreeSelection", ""),
    ("Std_TreeSyncPlacement", ""),
    ("Std_TreeSyncSelection", ""),
    ("Std_TreeSyncView", ""),
    ("Std_AxisCross", ""),
)


ORIENTATION = ("ViewFront", "ViewBack", "ViewLeft", "ViewRight", "ViewTop", "ViewBottom",
               "ViewIsometric", "ViewTrimetric", "ViewDimetric", "NormalTo")
# The S key's shortcut bar outside and inside a sketch: (keys, rows).

# with each flyout's commands from Toolbars\Flyouts, and the layout seen on Ati's screen 2026-11-01).
# (entries, buttons per row); an entry is a catalog key or (shown key, flyout keys). Every bar ends with a
# "Search All Commands" box under the buttons.
SELECT = ("Select", ("Select", "BoxSelect", "LassoSelect", "MagnifiedSelection", "BoxElementSelect", "SelectAll"))
PART_BAR = ((SELECT,
             ("BossExtrude", ("BossExtrude", "BossRevolve", "BossSweep", "BossLoft", "BossBoundary")),
             ("CutExtrude", ("CutExtrude", "CutRevolve", "CutSweep", "CutLoft", "CutBoundary")),
             ("Fillet", ("Fillet", "Chamfer")),
             ("ReferenceGeometry", ("Plane", "Axis", "CoordinateSystem", "Point", "CenterOfMass", "BoundingBox")),
             ("Hole", ("Hole", "AdvancedHole", "Thread"))), (4, 2))
ASSEMBLY_BAR = ((SELECT,
                 ("InsertComponents", ("InsertComponents", "NewPartInAssembly")),
                 "Mate", "EditComponent", "ShowHiddenComponents"), (5,))
SKETCH_BAR = ((SELECT,
               ("SmartDimension", ("SmartDimension", "HorizontalDimension", "VerticalDimension", "BaselineDimension",
                                   "ChainDimension", "SymmetricLinearDiameterDimension", "OrdinateDimension",
                                   "HorizontalOrdinateDimension", "VerticalOrdinateDimension",
                                   "AngularRunningDimension", "PathLengthDimension", "ChamferDimension")),
               "ExitSketch",
               ("Line", ("Line", "Centerline", "MidpointLine")),
               ("CornerRectangle", ("CornerRectangle", "CenterRectangle", "ThreePointCornerRectangle",
                                    "ThreePointCenterRectangle", "Parallelogram")),
               ("Slot", ("Slot", "CenterpointSlot", "ThreePointArcSlot", "ArcSlot")),
               ("Circle", ("Circle", "PerimeterCircle")),
               ("CenterArc", ("CenterArc", "TangentArc", "ThreePointArc")),
               ("SketchFillet", ("SketchFillet", "SketchChamfer")),
               ("Spline", ("Spline", "StyleSpline", "EquationDrivenCurve")),
               ("Trim", ("Trim", "Extend")),
               ("Convert", ("Convert", "SilhouetteEntities", "IntersectionCurve")),
               "Offset"), (4, 3, 3, 3))

# the view flyout, Center Mark, Centerline, Hole Callout, Surface Finish, Weld Symbol, Geometric Tolerance,
# Datum Feature, Revision Cloud
DRAWING_BAR = ((SELECT,
                ("SmartDimension", ("SmartDimension", "HorizontalDimension", "VerticalDimension", "BaselineDimension",
                                    "ChainDimension", "OrdinateDimension", "ChamferDimension")),
                "DrawNote",
                ("DrawBalloon", ("DrawBalloon", "DrawAutoBalloon")),
                ("DrawModelView", ("DrawModelView", "DrawProjectedView", "DrawAuxiliaryView", "DrawSectionView",
                                   "DrawDetailView", "DrawStandard3View")),
                "DrawCenterMark", "DrawCenterline", "DrawHoleCallout", "DrawSurfaceFinish", "DrawWeldSymbol",
                "DrawGeometricTolerance", "DrawDatumFeature", "DrawRevisionCloud"), (4, 5, 4))
BARS = {"sketch": SKETCH_BAR, "assembly": ASSEMBLY_BAR, "drawing": DRAWING_BAR, "part": PART_BAR}
LAST_USED = ("CornerRectangle", "Slot", "Circle", "CenterArc")
_last = {}                       # flyout's first key -> key picked last (this session)
ARROW = 11                       # px wide drop-down arrow beside a flyout's button
BUTTON = (28, 26)
ICON = 20


def settings():
    """(group, type, name, value) entries for style.SETTINGS."""
    return tuple((SHORTCUT, "String", name, key) for name, key in KEYS)


def _shell():
    try:
        from . import shell
        s = shell.shell()
    except Exception:
        return None
    return s if s is not None and s.enabled else None


def _run_later(func):
    """Run once a popup's own event loop has ended, not inside it."""
    def attempt(tries=0):
        if QtWidgets.QApplication.activePopupWidget() is not None and tries < 50:
            QtCore.QTimer.singleShot(10, lambda: attempt(tries + 1))
            return
        try:
            func()
        except Exception as error:
            App.Console.PrintError("FreeCAD: %s\n" % error)
    QtCore.QTimer.singleShot(0, attempt)


# --------------------------------------------------------------------------- shortcut bar
class BarSearch(QtWidgets.QLineEdit):
    """The bar's own "Search All Commands" box: what is typed goes on in the title row's search box,
    whose list of matches drops down there, and the bar closes."""

    def __init__(self, bar, parent):
        super().__init__(parent)
        self.bar = bar
        self.setObjectName("SWShortcutBarSearch")
        self.setPlaceholderText("Search All Commands")
        try:
            from . import ribbon
            self.setFont(ribbon.ui_font())
            self.addAction(ribbon.search_icon(self.devicePixelRatioF()), QtWidgets.QLineEdit.TrailingPosition)
        except Exception as _fw_err:
            _fw_log("keys.py:356", _fw_err)
        self.setMinimumWidth(self.fontMetrics().horizontalAdvance("Search All Commands") + 44)
        self.textEdited.connect(self._typed)

    def _typed(self, text):
        shell = self.bar.shell
        self.bar.close()

        def hand_over(text=text):
            try:
                box = shell.topbar.qat.search
            except Exception:
                return
            box.setFocus(Qt.ShortcutFocusReason)
            box.setText(text)
            box._typed(text)
        _run_later(hand_over)


class ShortcutBar(QtWidgets.QMenu):
    ""


    def __init__(self, shell, mode, parent=None):
        super().__init__(parent or shell.window)
        self.setObjectName("SWShortcutBar")
        self.mode = mode
        self.shell = shell
        entries, rows = BARS.get(mode, PART_BAR)
        try:
            # Customize > Shortcut Bars: the buttons dragged onto this bar come after the stock ones
            from . import customizedlg
            have = [e if isinstance(e, str) else e[0] for e in entries]
            entries = tuple(entries) + tuple(k for k in customizedlg.shortcut_extras(mode) if k not in have)
            gone = customizedlg.shortcut_removed(mode)      # stock buttons taken off the bar
            if gone:
                entries = tuple(e for e in entries if (e if isinstance(e, str) else e[0]) not in gone)
            # the order the buttons were dragged into on the Shortcut Bars tab (cmorder-1121)
            entries = tuple(customizedlg.shortcut_ordered(mode, entries, lambda e: e if isinstance(e, str) else e[0]))
        except Exception as _fw_err:
            _fw_log("keys.py:394", _fw_err)
        grid_widget = QtWidgets.QWidget(self)
        column = QtWidgets.QVBoxLayout(grid_widget)
        column.setContentsMargins(4, 4, 4, 4)
        column.setSpacing(2)
        cells = [c for c in (self._cell(e, grid_widget) for e in entries) if c is not None]
        self.buttons = []
        self.flyouts = {}            # shown key -> the flyout's keys
        self.rows = []
        counts = list(rows)
        while sum(counts) < len(cells):
            counts.append(counts[-1])
        start = 0
        for count in counts:
            part = cells[start:start + count]
            start += count
            if not part:
                break
            line = QtWidgets.QHBoxLayout()
            line.setSpacing(2)
            for cell, button, flyout in part:
                line.addWidget(cell)
                self.buttons.append(button)
                if flyout:
                    self.flyouts[button.entry.key] = flyout
            line.addStretch(1)
            column.addLayout(line)
            self.rows.append([b.entry.key for _, b, _ in part])
        self.search = BarSearch(self, grid_widget)
        column.addWidget(self.search)
        self._search_first = False
        try:
            # Customize > Shortcut Bars: Show Command Search in the shortcut bars / Activate Command Search when the

            from . import customizedlg
            shown = customizedlg.option("ShortcutBarSearch")
            self.search.setVisible(bool(shown))
            self._search_first = bool(shown and customizedlg.option("ShortcutBarSearchActivate"))
        except Exception as _fw_err:
            _fw_log("keys.py:bar-search", _fw_err)
        action = QtWidgets.QWidgetAction(self)
        action.setDefaultWidget(grid_widget)
        self.addAction(action)
        grid_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        grid_widget.customContextMenuRequested.connect(self._customize_menu)

    def showEvent(self, e):
        super().showEvent(e)
        if self._search_first:
            QtCore.QTimer.singleShot(0, lambda: self.search.setFocus(Qt.PopupFocusReason))

    def mousePressEvent(self, e):
        # sbarmenu-1127: a popup gets no ContextMenu event, so the right press opens the menu here
        if e.button() == Qt.RightButton:
            e.accept()
            self._customize_menu(None)
            return
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton:      # sbarmenu-1127: the right release must not close the bar
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def _customize_menu(self, pos):
        ""
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWShortcutBarMenu")
        act = menu.addAction("Customize...")
        act.setObjectName("SWShortcutBarCustomize")

        def customize():
            self.close()
            try:
                from . import customizedlg
                box = customizedlg.show(self.shell)
                box.tabs.setCurrentIndex(1)
                box.sb_mode.setCurrentIndex([m for m, _n in customizedlg.MODES].index(self.mode))
            except Exception as error:
                App.Console.PrintLog("FreeCAD: Customize from the shortcut bar: %s\n" % error)
        act.triggered.connect(customize)
        menu.exec_(self.sender().mapToGlobal(pos) if pos is not None and self.sender() is not None
                   else QtGui.QCursor.pos())       # sbarmenu-1127
        menu.deleteLater()      # sbarmenu-1127-v2: one menu per right-click, freed after it closes

    def _entry(self, key):
        from . import contextbar
        if key.startswith("cmd:"):
            name = key[4:]
            try:
                info = Gui.Command.get(name).getInfo()
            except Exception:
                return None
            label = (info.get("menuText") or name).replace("&", "")
            pixmap = info.get("pixmap") or ""
            icon = Gui.getIcon(pixmap) if pixmap else QtGui.QIcon()
            return contextbar.Entry(key, label, icon, contextbar._tip(label, info.get("toolTip") or ""),
                                    lambda name=name: Gui.runCommand(name, 0)), True
        if key not in _catalog_keys():
            return None
        binding = self.shell.binding(key)
        cmd = binding.cmd
        run = lambda shell=self.shell, key=key: contextbar.run_key(shell, key)
        if cmd.natives:
            enabled = contextbar.active_native(cmd) is not None
            if not enabled and App.ActiveDocument is not None:
                # sbarlive-1126: no dead button on the bar. A command that cannot act yet, and that the ribbon lets
                # you click (it opens the page that says what it needs, notready-1126), does the same here.
                try:
                    binding.resolve()
                    binding.update_state()
                    if binding.enabled:
                        enabled, run = True, binding.run
                except Exception as _fw_err:
                    _fw_log("keys.py:sbarlive", _fw_err)
        else:
            enabled = bool(cmd.call and self.shell.special_enabled(cmd.call))
        return contextbar.Entry(key, cmd.label, binding.icon(), contextbar._tip(cmd.label, cmd.tip or ""), run), enabled

    def _cell(self, spec, parent):
        """(widget, main button, flyout keys) for one entry, or None when nothing backs it."""
        from . import contextbar
        if isinstance(spec, str):
            shown, flyout = spec, ()
        else:
            shown, flyout = spec
            flyout = tuple(k for k in flyout if k in _catalog_keys())
            if shown in LAST_USED and _last.get(shown) in flyout:
                shown = _last[shown]
            elif shown not in _catalog_keys() and flyout:
                shown = flyout[0]
        made = self._entry(shown)
        if made is None:
            return None
        entry, enabled = made
        first = spec[0] if not isinstance(spec, str) else spec
        b = contextbar.Button(entry, parent)
        b.setFixedSize(*BUTTON)
        b.setEnabled(enabled)
        b.clicked.connect(lambda checked=False, e=entry, f=first: self._chosen(e, f))
        if len(flyout) < 2:
            return b, b, ()
        cell = QtWidgets.QWidget(parent)
        row = QtWidgets.QHBoxLayout(cell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        b.setParent(cell)
        row.addWidget(b)
        arrow = QtWidgets.QToolButton(cell)
        arrow.setObjectName("SWShortcutBarArrow")
        arrow.setArrowType(Qt.DownArrow)
        arrow.setAutoRaise(True)
        arrow.setFocusPolicy(Qt.NoFocus)
        arrow.setFixedSize(ARROW, BUTTON[1])
        arrow.setToolTip(entry.label)
        arrow.clicked.connect(lambda checked=False, a=arrow, f=flyout, k=first: self._open_flyout(a, f, k))
        row.addWidget(arrow)
        b.arrow = arrow
        return cell, b, flyout

    def _open_flyout(self, arrow, flyout, first):
        menu = self.shell.menu_for_keys(())
        menu.setObjectName("SWShortcutBarFlyout")
        for key in flyout:
            self.shell._add_binding_action(menu, key, on_chosen=lambda k, f=first: self._picked(f, k))
        menu.popup(arrow.mapToGlobal(QtCore.QPoint(0, arrow.height())))
        return menu

    def _picked(self, first, key):
        if first in LAST_USED:
            _last[first] = key
        self.close()

    def keys(self):
        return [b.entry.key for b in self.buttons]

    def button(self, key):
        for b in self.buttons:
            if b.entry.key == key:
                return b
        return None

    def _chosen(self, entry, first=None):
        if first in LAST_USED:
            _last[first] = entry.key
        self.close()
        _run_later(entry.run)


def _catalog_keys():
    from . import catalog
    return catalog.BY_KEY


def _assembly():
    try:
        from . import asmcore
        return bool(asmcore.is_assembly(App.ActiveDocument))
    except Exception:
        return False


def bar_mode():
    ""
    from . import contextbar
    if contextbar.sketch_in_edit() is not None:
        return "sketch"
    try:
        from . import swmenus
        if swmenus.drawing_in_front():
            return "drawing"
    except Exception as _fw_err:
        _fw_log("keys.py:566", _fw_err)
    if _assembly():
        try:
            from . import asmtools
            if asmtools.editing() is not None:
                return "part"
        except Exception as _fw_err:
            _fw_log("keys.py:573", _fw_err)
        return "assembly"
    return "part"


def show_shortcut_bar(pos=None):
    shell = _shell()
    if shell is None:
        return None
    from . import contextbar
    mode = bar_mode()
    bar = ShortcutBar(shell, mode)
    bar.setAttribute(Qt.WA_DeleteOnClose, True)
    pos = pos or QtGui.QCursor.pos()

    bar.popup(pos - QtCore.QPoint(BUTTON[0] // 2 + 4, BUTTON[1] // 2 + 4))
    return bar


def show_orientation_menu(pos=None):
    shell = _shell()
    if shell is None:
        return None
    menu = shell.menu_for_keys(ORIENTATION)
    menu.setObjectName("SWOrientationMenu")
    menu.setAttribute(Qt.WA_DeleteOnClose, True)
    menu.popup(pos or QtGui.QCursor.pos())
    return menu


# --------------------------------------------------------------------------- commands
class _Command:
    MENU, TIP = "", ""
    # FreeCAD greys out a Python command while a task dialog (a sketch, a feature) is open unless it
    # says it works in edit mode.
    FOR_EDIT = True

    def GetResources(self):
        res = {"MenuText": self.MENU, "ToolTip": self.TIP}
        if self.FOR_EDIT:
            res["CmdType"] = "ForEdit"
        return res


class ViewOrientationCommand(_Command):
    MENU, TIP = "View Orientation", "The Orientation box and the View Selector (Space)"

    def Activated(self):
        shell = _shell()
        if shell is not None and shell.orientation is not None:
            shell.toggle_orientation()
        else:
            show_orientation_menu()

    def IsActive(self):
        return _shell() is not None and Gui.ActiveDocument is not None


class ShortcutBarCommand(_Command):
    MENU, TIP = "Shortcut Bar", "Part or sketch commands at the pointer (S)"

    def Activated(self):
        show_shortcut_bar()

    def IsActive(self):
        return _shell() is not None


class CloseDocumentCommand(_Command):
    MENU, TIP = "Close", "Closes the active document (Ctrl+W)"
    FOR_EDIT = True

    def Activated(self):
        doc = App.ActiveDocument
        try:
            if Gui.ActiveDocument is not None and Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
                QtWidgets.QApplication.processEvents()
        except Exception as _fw_err:
            _fw_log("keys.py:652", _fw_err)
        name = doc.Name if doc is not None else None
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        for _ in range(30):
            count = len(mdi.subWindowList()) if mdi is not None else 0
            Gui.runCommand("Std_CloseActiveWindow")
            QtWidgets.QApplication.processEvents()
            if name is None or name not in App.listDocuments() or App.ActiveDocument is None \
                    or App.ActiveDocument.Name != name:
                break
            if mdi is not None and len(mdi.subWindowList()) >= count:
                break       # the user cancelled the save prompt

    def IsActive(self):
        return App.ActiveDocument is not None


NORMAL_TO = {"key": None, "orientation": None, "flips": 0}     # the last Normal To, for the flip


def _normal_key():
    try:
        picks = tuple((s.DocumentName, s.ObjectName, tuple(s.SubElementNames)) for s in Gui.Selection.getSelectionEx())
    except Exception:
        picks = ()
    from . import contextbar
    sketch = contextbar.sketch_in_edit()
    return (picks, sketch.Name if sketch is not None else None)


def _camera():
    try:
        view = Gui.ActiveDocument.ActiveView
        return view.getCameraNode() if hasattr(view, "getCameraNode") else None
    except Exception:
        return None


def _orientation_tuple(cam):
    q = cam.orientation.getValue().getValue()
    return tuple(round(float(c), 3) for c in q)


def _remember_normal(key):
    cam = _camera()
    NORMAL_TO["key"] = key
    NORMAL_TO["orientation"] = _orientation_tuple(cam) if cam is not None else None


def flip_view():
    ""

    try:
        from . import camanim
        if camanim.animate_change(lambda view: _flip_now()):
            return True
    except Exception as _fw_err:
        _fw_log("keys.py:flip-anim", _fw_err)
    return _flip_now()


def _flip_now():
    from pivy import coin
    cam = _camera()
    if cam is None:
        return False
    orientation = cam.orientation.getValue()
    up = orientation.multVec(coin.SbVec3f(0, 1, 0))
    direction = orientation.multVec(coin.SbVec3f(0, 0, -1))
    focal = cam.position.getValue() + direction * cam.focalDistance.getValue()
    turned = orientation * coin.SbRotation(up, 3.141592653589793)
    new_dir = turned.multVec(coin.SbVec3f(0, 0, -1))
    cam.orientation.setValue(turned)
    cam.position.setValue(focal - new_dir * cam.focalDistance.getValue())
    return True


def _is_plane(obj):
    return obj is not None and (obj.TypeId == "Sketcher::SketchObject" or obj.isDerivedFrom("App::Plane")
                                or obj.isDerivedFrom("PartDesign::Plane"))


def feature_sketch(obj, depth=0):
    ""




    try:
        if obj is None or depth > 3:
            return None
        if _is_plane(obj):
            return obj
        if obj.isDerivedFrom("PartDesign::Body"):
            return feature_sketch(getattr(obj, "Tip", None), depth + 1)
        prof = getattr(obj, "Profile", None)
        if isinstance(prof, (tuple, list)):
            prof = prof[0] if prof else None
        if prof is not None and getattr(prof, "TypeId", "") == "Sketcher::SketchObject":
            return prof
        if "Groups" in getattr(obj, "PropertiesList", ()):          # a weldment Structural Member
            from . import wemember
            if wemember.is_structural_member(obj):
                for group in wemember.groups(obj):
                    for name, _edge in group.get("segments", []):
                        sk = obj.Document.getObject(name)
                        if sk is not None and sk.TypeId == "Sketcher::SketchObject":
                            return sk
    except Exception as _fw_err:
        _fw_log("keys.py:feature-sketch", _fw_err)
    return None


def _pick_normal(doc_name, obj_name, sub):
    """Outward normal (global) of a picked planar face, datum plane or sketch, else None."""
    try:
        import Part
        obj = App.getDocument(doc_name).getObject(obj_name)
        element = (sub or "").split(".")[-1]
        if element.startswith("Face"):
            face = Part.getShape(obj, sub, needSubElement=True)
            if face.isNull() or face.Surface.__class__.__name__ != "Plane":
                return None
            u0, u1, v0, v1 = face.ParameterRange
            n = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        else:
            leaf = obj.getSubObject(sub, retType=1) if sub else obj
            leaf = leaf if leaf is not None else obj
            if element:
                return None
            leaf = feature_sketch(leaf)         # a sketch or plane itself, or a whole feature's sketch
            if leaf is None:
                return None
            n = leaf.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
        return n.normalize() if n.Length > 1e-9 else None
    except Exception:
        return None


def _picked_normals():
    """Normals of the picks, in pick order (None for a pick that has none)."""
    out = []
    try:
        for sel in Gui.Selection.getSelectionEx("", 0):
            subs = sel.SubElementNames or ("",)
            for sub in subs:
                out.append(_pick_normal(sel.DocumentName, sel.ObjectName, sub))
    except Exception as _fw_err:
        _fw_log("keys.py:752", _fw_err)
    return out


def _datum_picked():
    """The one picked sketch or datum plane (also an origin plane picked through its Body), else None."""
    try:
        sel = Gui.Selection.getSelectionEx("", 0)
        if len(sel) != 1 or len(sel[0].SubElementNames) > 1:
            return None
        sub = sel[0].SubElementNames[0] if sel[0].SubElementNames else ""
        if sub.split(".")[-1]:
            return None         # a face, edge or vertex
        leaf = sel[0].Object.getSubObject(sub, retType=1) if sub else sel[0].Object
        leaf = leaf if leaf is not None else sel[0].Object
        return feature_sketch(leaf)
    except Exception as _fw_err:
        _fw_log("keys.py:771", _fw_err)
    return None


def _view_direction():
    try:
        return App.Vector(*Gui.ActiveDocument.ActiveView.getViewDirection()).normalize()
    except Exception:
        return None


def _snap_axis(v, skip=None):
    """The global axis (+-X, +-Y, +-Z) nearest v, leaving out skip's axis."""
    best = None
    for a in (App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1)):
        if skip is not None and abs(a.dot(skip)) > 0.5:
            continue
        d = v.dot(a)
        if best is None or abs(d) > abs(best[0]):
            best = (d, a * (1 if d >= 0 else -1))
    return best[1]


def _nearest_axes_view():
    """Turns the view to look along the global axis nearest its direction, with up along the global axis
    nearest its up (Normal To with nothing picked). False when there is no 3D view."""
    try:
        view = Gui.ActiveDocument.ActiveView
        rot = App.Rotation(*view.getCameraOrientation().Q)
    except Exception:
        return False
    direction = rot.multVec(App.Vector(0, 0, -1))
    up = rot.multVec(App.Vector(0, 1, 0))
    d = _snap_axis(direction)
    u = _snap_axis(up, skip=d)
    return look_along(d, u)


def look_along(direction, up):
    """Turns the camera about its focal point to look along direction with up pointing up."""
    from pivy import coin
    cam = _camera()
    if cam is None:
        return False
    try:
        Gui.ActiveDocument.ActiveView.stopAnimating()
    except Exception as _fw_err:
        _fw_log("keys.py:791", _fw_err)
    z = App.Vector(-direction.x, -direction.y, -direction.z).normalize()     # the camera looks down -Z
    y = (up - z * up.dot(z)).normalize()
    x = y.cross(z)
    m = App.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, 0, 0, 0, 1)
    q = App.Rotation(m).Q
    old_dir = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
    focal = cam.position.getValue() + old_dir * cam.focalDistance.getValue()
    try:
        from . import camanim
        if camanim.animate_to(Gui.ActiveDocument.ActiveView, App.Rotation(*q), fit=False):
            return True
    except Exception as _fw_err:
        _fw_log("keys.py:look_along", _fw_err)
    turned = coin.SbRotation(q[0], q[1], q[2], q[3])
    cam.orientation.setValue(turned)
    cam.position.setValue(focal - turned.multVec(coin.SbVec3f(0, 0, -1)) * cam.focalDistance.getValue())
    return True


class NormalToCommand(_Command):
    MENU, TIP = ("Normal To", "Turns the view to look straight at the selected face, or at the sketch; "
                              "a second press looks from the other side. With two faces picked, the "
                              "second one faces up")

    def Activated(self):
        key = _normal_key()
        normals = _picked_normals()
        first = normals[0] if normals else None
        if first is None and not normals:
            from . import contextbar
            sketch = contextbar.sketch_in_edit()
            if sketch is not None:
                first = sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1)).normalize()
        now = _view_direction()
        if first is not None and now is not None and abs(now.dot(first)) > 0.9998:
            # already looking straight at it (or at its back): each press looks from the other side, as in

            # remembered right after the first press was still mid-turn and the flip never came)
            if flip_view():
                NORMAL_TO["flips"] += 1
                return
        second = normals[1] if len(normals) > 1 else None
        if first is not None and second is not None and abs(first.dot(second)) < 0.9998:

            if look_along(App.Vector(-first.x, -first.y, -first.z), second):
                _remember_normal(key)
                return
        datum = _datum_picked() if first is not None and len(normals) == 1 else None
        if datum is not None:
            # a sketch or datum plane (FreeCAD's Align to Selection skips them): look straight at it
            try:
                from . import camanim
                wait = 400
                if camanim.animate_to(Gui.ActiveDocument.ActiveView, datum.getGlobalPlacement().Rotation, fit=False):
                    wait = camanim.DURATION_MS + 150
                else:
                    Gui.ActiveDocument.ActiveView.setCameraOrientation(datum.getGlobalPlacement().Rotation.Q)
                QtCore.QTimer.singleShot(wait, lambda: _remember_normal(key))
                return
            except Exception as _fw_err:
                _fw_log("keys.py:841", _fw_err)
        if first is None and not Gui.Selection.getSelectionEx():


            if _nearest_axes_view():
                QtCore.QTimer.singleShot(400, lambda: _remember_normal(key))
                return
        # FreeCAD calls Align to Selection active with nothing picked, where it does nothing: inside

        names = ("Std_AlignToSelection", "Sketcher_ViewSketch")
        if not Gui.Selection.getSelectionEx():
            names = names[::-1]
        for name in names:
            try:
                command = Gui.Command.get(name)
                if command is not None and command.isActive():
                    try:
                        from . import camanim
                        ran = camanim.animate_command(name)
                    except Exception as _fw_err:
                        _fw_log("keys.py:normal-anim", _fw_err)
                        ran = False
                    if ran:
                        QtCore.QTimer.singleShot(camanim.DURATION_MS + 150, lambda: _remember_normal(key))
                        return
                    Gui.runCommand(name, 0)
                    try:
                        wait = App.ParamGet("User parameter:BaseApp/Preferences/View").GetInt("AnimationDuration", 250)
                    except Exception:
                        wait = 250
                    QtCore.QTimer.singleShot(int(wait) + 150, lambda: _remember_normal(key))
                    return
            except Exception:
                continue

    def IsActive(self):
        return Gui.ActiveDocument is not None


class ZoomFitCommand(_Command):
    MENU, TIP = "Zoom to Fit", "Zooms the model to fit the window (F)"

    def GetResources(self):
        res = _Command.GetResources(self)
        try:
            res["Pixmap"] = Gui.Command.get("Std_ViewFitAll").getInfo().get("pixmap", "") or ""
        except Exception as _fw_err:
            _fw_log("keys.py:zoomfit-icon", _fw_err)
        return res

    def Activated(self):

        try:
            from . import camanim, namedviews
            view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None
            if view is not None and hasattr(view, "getCameraNode"):
                namedviews._push_current()
                if camanim.animate_to(view, None, fit=True):
                    return
        except Exception as _fw_err:
            _fw_log("keys.py:zoomfit", _fw_err)
        Gui.runCommand("Std_ViewFitAll", 0)

    def IsActive(self):
        try:
            command = Gui.Command.get("Std_ViewFitAll")
            return command is not None and command.isActive()
        except Exception:
            return Gui.ActiveDocument is not None


class PreviousViewCommand(_Command):
    MENU, TIP = "Previous View", "Goes back to the view before the last view change (Ctrl+Shift+Z)"

    def Activated(self):
        shell = _shell()
        if shell is not None:
            shell.previous_view()

    def IsActive(self):
        shell = _shell()
        return shell is not None and shell.special_enabled("previous_view")


def rebuild(force=False):
    ""


    doc = App.ActiveDocument
    if doc is None:
        return 0


    # sketch). Ati 00:19Z: "the stop light still doesn't work like it should".
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        # an assembly being edited (the active assembly, or a part edited in it) is in edit through
        # its C++ view provider, which has no .Object: nothing to close then
        obj = getattr(edit, "Object", None) if edit is not None else None
        if obj is not None and obj.TypeId == "Sketcher::SketchObject":
            gdoc.resetEdit()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sketch not closed for the rebuild: %s\n" % error)
    if force:
        for obj in doc.Objects:
            try:
                obj.touch()
            except Exception as _fw_err:
                _fw_log("keys.py:900", _fw_err)
    # Ctrl+Q is a real rebuild of every feature: the slow-feature cache (fcache) is not used
    try:
        from . import fcache
        fcache.BYPASS[0] = bool(force)
    except Exception:
        fcache = None
    try:
        count = doc.recompute()
    except Exception as error:
        App.Console.PrintError("FreeCAD: rebuild failed: %s\n" % error)
        count = 0
    finally:
        if fcache is not None:
            fcache.BYPASS[0] = False
    try:
        from . import whatswrong
        whatswrong.after_rebuild(doc)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: What's Wrong not shown: %s\n" % error)
    return count or 0


class RebuildCommand(_Command):
    ""



    MENU, TIP = "Rebuild", "Rebuilds the features that changed (Ctrl+B)"
    count = 0

    def Activated(self):
        RebuildCommand.count += 1
        rebuild()

    def IsActive(self):
        return App.ActiveDocument is not None


class ForceRebuildCommand(_Command):
    MENU, TIP = "Forced Rebuild", "Rebuilds every feature of the part (Ctrl+Q)"

    # every feature (fwsketch fix132). In any other edit (a feature's PropertyManager) it stays grey.
    FOR_EDIT = True
    count = 0

    def Activated(self):
        ForceRebuildCommand.count += 1
        rebuild(force=True)

    def IsActive(self):
        if App.ActiveDocument is None:
            return False
        try:
            gdoc = Gui.ActiveDocument
            edit = gdoc.getInEdit() if gdoc is not None else None
        except Exception:
            edit = None
        return edit is None or getattr(getattr(edit, "Object", None), "TypeId", "") == "Sketcher::SketchObject"


class WhatsWrongCommand(_Command):
    MENU, TIP = "What's Wrong", "Lists the features that failed to rebuild, with the reason"

    def Activated(self):
        from . import whatswrong
        whatswrong.show()

    def IsActive(self):
        return App.ActiveDocument is not None



# once the command sits in a menu or toolbar, so they go in a View > Selection Filter submenu.
SELECTION_FILTER_KEYED = ("SWStyle_SelectionFilterToolbar", "SWStyle_ToggleSelectionFilters", "SWStyle_ClearAllFilters",
                          "SWStyle_SelectAllFilters", "SWStyle_FilterVertices", "SWStyle_FilterEdges",
                          "SWStyle_FilterFaces")


class SelectionFilterMenu:
    def GetCommands(self):
        have = set(Gui.listCommands())
        return tuple(name for name in SELECTION_FILTER_KEYED if name in have)

    def GetResources(self):
        return {"MenuText": "Selection Filter", "ToolTip": "Selection filters (F5 shows the toolbar)",
                "DropDownMenu": True, "Exclusive": False, "CmdType": "ForEdit"}

    def IsActive(self):
        return True


class _Group:
    """A View menu submenu of other commands (FreeCAD gives their keys to the submenu's entries)."""
    MENU, TIP, NAMES = "", "", ()

    def GetCommands(self):
        have = set(Gui.listCommands())
        return tuple(name for name in self.NAMES if name in have)

    def GetResources(self):
        return {"MenuText": self.MENU, "ToolTip": self.TIP, "DropDownMenu": True, "Exclusive": False}

    def IsActive(self):
        return App.ActiveDocument is not None


class OrientationMenu(_Group):
    ""

    MENU, TIP = "Orientation", "Standard views, New View, Update and Reset Standard Views"
    NAMES = tuple("SWStyle_Standard" + key for key in ("Front", "Back", "Left", "Right", "Top", "Bottom", "Isometric",
                                                       "Trimetric", "Dimetric")) + \
        ("SWStyle_YUpViewOrientation", "SWStyle_ZUpViewOrientation",
         "SWStyle_NewView", "SWStyle_UpdateStandardViews", "SWStyle_ResetStandardViews")


class SetCurrentViewAsMenu(_Group):
    MENU, TIP = "Set Current View As", "Makes the current view a standard view; the others turn with it"
    NAMES = tuple("SWStyle_SetCurrentViewAs" + key for key in ("Front", "Back", "Top", "Bottom", "Left", "Right"))


COMMANDS = (("SWStyle_ViewOrientation", ViewOrientationCommand), ("SWStyle_ShortcutBar", ShortcutBarCommand),
            ("SWStyle_NormalTo", NormalToCommand), ("SWStyle_PreviousView", PreviousViewCommand),
            ("SWStyle_Rebuild", RebuildCommand), ("SWStyle_ForceRebuild", ForceRebuildCommand),
            ("SWStyle_WhatsWrong", WhatsWrongCommand), ("SWStyle_SelectionFilterMenu", SelectionFilterMenu),
            ("SWStyle_OrientationMenu", OrientationMenu), ("SWStyle_SetCurrentViewAsMenu", SetCurrentViewAsMenu),
            ("SWStyle_CloseDocument", CloseDocumentCommand), ("SWStyle_ZoomFit", ZoomFitCommand))


def drop_group_copies(window=None):
    """FreeCAD's group buttons (Standard Views and the like) copy the key of the command they
    show, so Ctrl+7 sits on Std_ViewIsometric and on Std_ViewGroup and Qt answers it with
    "Ambiguous shortcut overload" and runs neither. Takes the key off every other command's
    action. Returns the names it cleared."""
    window = window or Gui.getMainWindow()
    owner = {QtGui.QKeySequence(key).toString(): name for name, key in KEYS if key}
    try:
        from . import customizedlg      # Customize > Keyboard's keys win over the defaults (rcmenus 11-26)
        for name, key in customizedlg.key_overrides().items():
            owner = {k: n for k, n in owner.items() if n != name}
            if key:
                owner[QtGui.QKeySequence(key).toString()] = name
    except Exception as _fw_err:
        _fw_log("keys.py:drop-overrides", _fw_err)
    have = set(Gui.listCommands())
    cleared = []
    for action in window.findChildren(QtGui.QAction):
        name = action.objectName()
        key = action.shortcut().toString()
        if key in owner and name in have and name != owner[key]:
            action.setShortcut(QtGui.QKeySequence())
            cleared.append(name)
    return cleared


def group_commands(name):
    """The entries of one of the submenus above (View > Selection Filter, Orientation...), else ()."""
    for n, cls in COMMANDS:
        if n == name and hasattr(cls, "GetCommands"):
            return cls().GetCommands()
    return ()


def register():
    """Adds the commands. Call once while FreeCAD starts; startup.Manipulator puts them in menus,
    which a FreeCAD key needs."""
    for name, cls in COMMANDS:
        Gui.addCommand(name, cls())


def menu_items(have):
    """Workbench manipulator entries for the View and Edit menus (have: the registered commands).
    Anchors are top-level entries FreeCAD 1.1 has in every build."""
    items = [{"insert": name, "menuItem": "Std_OrthographicCamera"}
             for name in ("SWStyle_ViewOrientation", "SWStyle_NormalTo", "SWStyle_PreviousView", "SWStyle_ZoomFit")
             if name in have]
    if "SWStyle_SelectionFilterMenu" in have and "SWStyle_SelectionFilterToolbar" in have:
        items.append({"insert": "SWStyle_SelectionFilterMenu", "menuItem": "Std_OrthographicCamera"})
    if items:
        items.append({"insert": "Separator", "menuItem": "Std_OrthographicCamera"})

    # "append" would put them at the end of the menu.
    for name in ("SWStyle_Rebuild", "SWStyle_ForceRebuild"):
        if name in have:
            items.append({"insert": name, "menuItem": "Std_BoxSelection"})

    if "SWStyle_CloseDocument" in have:
        items.append({"insert": "SWStyle_CloseDocument", "menuItem": "Std_CloseActiveWindow"})
        items.append({"remove": "Std_CloseActiveWindow"})
    # Magnified Selection (G) next to Select All: a key works only for a command in a menu
    if "SWStyle_MagnifiedSelection" in have:
        items.append({"insert": "SWStyle_MagnifiedSelection", "menuItem": "Std_SelectAll"})
    # F1 (Help on This): a key works only for a command in a menu, and swmenus adds the guide's
    # commands after this runs, so they are registered here first (register adds each one once).
    try:
        from . import helpguide
        helpguide.register()
        items.append({"insert": "FreeWorks_ContextHelp", "menuItem": "Std_OnlineHelp"})
    except Exception as error:
        App.Console.PrintLog("User Guide: F1 not put in the Help menu (%s)\n" % error)
    return items
