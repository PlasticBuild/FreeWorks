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
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

PREFS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/CommandManager"
DEFAULT_HIDDEN = ("Mold Tools", "Mesh Modeling", "Data Migration", "Direct Editing", "Render Tools")


ORDER = ("Features", "Freeshape", "Sketch", "Sketch Ink", "3D Slicer", "Surfaces", "Sheet Metal",
         "Structure System", "Weldments", "Mold Tools", "Mesh Modeling", "Data Migration", "Direct Editing",
         "Markup", "Evaluate", "MBD Dimensions", "MBD", "Render Tools", "Add-Ins")

# (key, label, commands, tip, caption, icon family) for buttons whose command has no catalog entry yet;
# the families are original drawings in resources\icons\png (interface land228)
KEYS = (
    ("FS_Extrude", "Extrude", "SWStyle_FreeshapeExtrude", "Freeshape Extrude", None, "FREESHAPE_EXTRUDE"),
    ("FS_Revolve", "Revolve", "SWStyle_FreeshapeRevolve", "Freeshape Revolve", None, "FREESHAPE_REVOLVE"),
    ("FS_Sweep", "Sweep", "SWStyle_FreeshapeSweep", "Freeshape Sweep", None, "FREESHAPE_SWEEP"),
    ("FS_Box", "Box", "SWStyle_FreeshapeBox", "A box cage", None, "FREESHAPE_BOX"),
    ("FS_QuadBall", "QuadBall", "SWStyle_FreeshapeQuadBall", "A ball cage", None, "FREESHAPE_QUADBALL"),
    ("FS_Cylinder", "Cylinder", "SWStyle_FreeshapeCylinder", "A cylinder cage", None, "FREESHAPE_CYLINDER"),
    ("FS_Torus", "Torus", "SWStyle_FreeshapeTorus", "A torus cage", None, "FREESHAPE_TORUS"),
    ("FS_Rectangle", "Rectangle", "SWStyle_FreeshapeRectangle", "A flat rectangle cage", None, "FREESHAPE_RECTANGLE"),
    ("FS_Disk", "Disk", "SWStyle_FreeshapeDisk", "A flat disk cage", None, "FREESHAPE_DISK"),
    ("FS_Ring", "Ring", "SWStyle_FreeshapeRing", "A flat ring cage", None, "FREESHAPE_RING"),
    ("FS_Merge", "Merge", "SWStyle_FreeshapeMerge", "Merges Freeshape bodies", None, "FREESHAPE_MERGE"),
    ("FS_EditMerge", "Edit Merge", "SWStyle_FreeshapeEditMerge", "Opens the Merge again", None, "FREESHAPE_EDIT_MERGE"),
    ("FS_Symmetry", "Symmetry", "SWStyle_FreeshapeSymmetry", "Makes the body symmetric about a plane", None, "FREESHAPE_SYMMETRY"),
    ("FS_ExtrudeFace", "Extrude Face", "SWStyle_FreeshapeExtrudeFace", "Pulls faces out", "Extrude\nFace", "FREESHAPE_EXTRUDE_FACE"),
    ("FS_Subdivide", "Subdivide", "SWStyle_FreeshapeSubdivide", "Smooths the body one level", None, "FREESHAPE_SUBDIVIDE"),
    ("FS_Crease", "Crease", "SWStyle_FreeshapeCrease", "Keeps the picked edges sharp", None, "FREESHAPE_CREASE"),
    ("FS_InsertLoop", "Insert Loop", "SWStyle_FreeshapeInsertLoop", "Adds edge loops", None, "FREESHAPE_INSERT_LOOP"),
    ("FS_FillHole", "Fill Hole", "SWStyle_FreeshapeFillHole", "Fills a hole", None, "FREESHAPE_FILL_HOLE"),
    ("FS_DeleteLoops", "Delete Loop / Face", "SWStyle_FreeshapeDeleteLoops", "Deletes faces and heals", None, "FREESHAPE_DELETE_LOOPS"),
    ("FS_Align", "Align", "SWStyle_FreeshapeAlign", "Moves the body onto a face", None, "FREESHAPE_ALIGN"),
    ("ImportedGeometry", "Imported Geometry", "SWStyle_InsertImported", "Brings a body in from a file", "Imported\nGeometry", "DATA_MIGRATION_IMPORTED_GEOMETRY"),
    ("RecognizeFeatures", "Recognize Features", "SWStyle_RecognizeFeatures", "Finds features on an imported body",
     "Recognize\nFeatures", "DATA_MIGRATION_RECOGNIZE_FEATURES"),
    ("DecimateMesh", "Decimate Mesh Body", "SWStyle_DecimateMesh", "Takes facets out of a mesh body", "Decimate\nMesh Body", "MESH_DECIMATE"),
    ("MK_Color", "Color", "SWStyle_MarkupColor", "The markup colour", None, "MARKUP_COLOR"),
    ("MK_Draw", "Draw", "SWStyle_MarkupDraw", "Draws freehand marks", None, "MARKUP_DRAW"),
    ("MK_Erase", "Erase", "SWStyle_MarkupErase", "Erases the mark you click", None, "MARKUP_ERASE"),
    ("MK_Select", "Select", "SWStyle_MarkupSelect", "Picks the model while marking up", None, "MARKUP_SELECT"),
    ("MK_Touch", "Touch", "SWStyle_MarkupTouch", "Draws with a finger or pen", None, "MARKUP_TOUCH"),
    ("MK_Note", "Note", "SWStyle_MarkupNote", "Puts a note where you click", None, "MARKUP_NOTE"),
    ("EditDecal", "Edit Decal", "SWStyle_EditDecal", "Puts a picture on a face", "Edit\nDecal", "RENDER_EDIT_DECAL"),
    ("MarkupFile", "Markup File", "SWStyle_MarkupFile", "Brings marks in from a markup file", None, "MARKUP_FILE"),
)


def L(key, fly=None):
    return ("large", key, fly)


def ST(*keys):
    return ("stack", tuple((k, None) if isinstance(k, str) else k for k in keys))


SEP = ("sep",)
FILLET = ("Fillet", "VariableFillet", "FaceFillet", "FullRoundFillet", "Chamfer")

TABS = {
    "Freeshape": (
        L("FS_Extrude", ("FS_Extrude", "FS_Revolve", "FS_Sweep")), L("ConvertToMesh"),
        L("FS_QuadBall", ("FS_QuadBall", "FS_Box", "FS_Cylinder", "FS_Torus")),
        L("FS_Rectangle", ("FS_Rectangle", "FS_Disk", "FS_Ring")), L("FS_Merge", ("FS_Merge", "FS_EditMerge")),
        SEP,
        L("FS_Symmetry"), L("FS_ExtrudeFace"), ST("FS_Subdivide", "FS_Crease", "FS_InsertLoop"),
        ST("FS_FillHole", "FS_DeleteLoops"),
        SEP,
        L("FS_Align"), L("FS_Revolve"), L("Scale"),
    ),
    "Mold Tools": (
        ST("PlanarSurface", "OffsetSurface", "RadiateSurface"), ST("RuledSurface", "FilledSurface", "KnitSurface"),
        SEP,
        ST("DraftAnalysis", "UndercutAnalysis", "PartingLineAnalysis"),
        SEP,
        ST("SplitLine", "Draft", "MoveFace"), ST("Scale"),
        SEP,
        L("MoldFolders"), L("PartingLine"), L("ShutOffSurfaces"), L("PartingSurface"), L("ToolingSplit"), L("MoldCore"),
    ),
    "Mesh Modeling": (
        L("ConvertToMesh"), L("DecimateMesh"), L("SegmentMesh"), L("SurfaceFromMesh"), L("Texture3D"), L("BodyCompare"),
        SEP,
        L("Plane"), L("SplitLine"), L("ProjectedCurve"), ST("SplitBody", "Intersect", "Combine"),
        ST("JoinParts", "Cavity", "DeleteKeepBody"), ST("MoveCopyBodies", "Thicken", "DeleteFace"),
        SEP,
        L("Fillet", FILLET), ST("Shell", "Scale", "CutWithSurface"),
        SEP,
        ST("TrimSurface", "ExtendSurface", "KnitSurface"), ST("ReplaceFace", "OffsetSurface"),
        SEP,
        L("EditAppearance"),
    ),
    "Data Migration": (
        L("Open"), L("ImportedGeometry"),
        SEP,
        L("ImportDiagnostics"), L("Check"), L("DraftAnalysis"),
        SEP,
        L("RecognizeFeatures"), L("HealEdges"), L("KnitSurface"), L("MoveCopyBodies"),
        ST("MoveFace", "DeleteFace", "ReplaceFace"), L("SplitBody"), L("Combine"),
        SEP,
        L("SM_Convert"), L("SM_InsertBends"),
    ),
    "Direct Editing": (
        L("MoveFace"), L("MoveCopyBodies"),
        SEP,
        L("Fillet"), L("Chamfer"),
        SEP,
        L("LinearPattern", ("LinearPattern", "CircularPattern", "Mirror", "CurveDrivenPattern", "SketchDrivenPattern",
                            "TableDrivenPattern", "FillPattern", "VariablePattern")),
        SEP,
        L("DeleteKeepBody"), L("DeleteFace"),
        SEP,
        L("SplitBody"), L("Combine"),
    ),
    "Markup": (
        L("Markup"),
        SEP,
        L("MK_Color"),
        SEP,
        L("MK_Draw"), L("MK_Erase"), L("MK_Select"),
        SEP,
        L("MK_Touch"), L("MK_Note"),
    ),
    "Render Tools": (
        L("EditAppearance"), L("CopyAppearance"), L("PasteAppearance"), L("ApplyScene"), L("EditDecal"),
        L("ChangeDisplayStates"),
    ),
}



# because the two copies' catalogs differ
OVERRIDE = {
    "Surfaces": (
        L("ExtrudedSurface"), L("RevolvedSurface"), L("SweptSurface"), L("LoftedSurface"), L("BoundarySurface"),
        L("FilledSurface"), L("Freeform"),
        SEP,
        ST("PlanarSurface", "OffsetSurface", "RuledSurface"), L("SurfaceFlatten"), L("SurfaceFillet"),
        SEP,
        ST("DeleteFace", "ReplaceFace", "DeleteHole"),
        SEP,
        ST("ExtendSurface", "TrimSurface", "UntrimSurface"), L("KnitSurface"),
        SEP,
        ST("Thicken", "ThickenedCut", "CutWithSurface"),
        SEP,
        L("ReferenceGeometry", ("Plane", "Axis", "CoordinateSystem", "Point", "CenterOfMass", "BoundingBox")),
        L("Curves", ("SplitLine", "ProjectedCurve", "CompositeCurve", "CurveThroughXYZPoints",
                     "CurveThroughReferencePoints", "HelixSpiral", "Slicing")),
    ),
}


# --------------------------------------------------------------------- preferences
def hidden():
    p = App.ParamGet(PREFS)
    if not p.GetBool("Saved", False):
        return list(DEFAULT_HIDDEN)
    text = p.GetString("HiddenTabs", "")
    return [t for t in text.split("|") if t]


def set_hidden(titles):
    p = App.ParamGet(PREFS)
    p.SetString("HiddenTabs", "|".join(titles))
    p.SetBool("Saved", True)


# --------------------------------------------------------------------- catalog
_ALL_TABS = []


def _add_keys():
    from . import catalog, evaltools, mbd, mbdtab
    for key, label, native, tip, caption, icon in KEYS:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (native,), icon, tip, caption=caption)
    for key, label, native, caption, *icon in mbd.KEYS + evaltools.KEYS + mbdtab.KEYS:   # (..., icon family) when drawn
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (native,), icon[0] if icon else None, label, caption=caption)
    TABS.setdefault(mbd.TAB[0], mbd.TAB[1])
    TABS.setdefault(mbdtab.TAB[0], mbdtab.TAB[1])
    catalog.ALL = tuple(catalog._ALL)



ADDIN_TABS = {"mbd": ("MBD Dimensions", "MBD")}


def addin_off():
    try:
        from . import addins
        return [t for module, titles in ADDIN_TABS.items() if not addins.module_active(module) for t in titles]
    except Exception as _fw_err:
        _fw_log("cmtabs.py:223", _fw_err)
        return []


def _rank(title):
    return ORDER.index(title) if title in ORDER else len(ORDER)


def all_tabs():
    ""
    from . import catalog
    have = {t[0]: t for t in _ALL_TABS}
    for t in catalog.TABS:
        have.setdefault(t[0], t)
    for title, layout in TABS.items():
        have.setdefault(title, (title, layout))
    for title, layout in OVERRIDE.items():
        if title in have:
            have[title] = (title, layout)
    if "Evaluate" in have:
        from . import evaltools, floxpress, dwxpress
        for mod in (floxpress, dwxpress):          # their keys must be in the catalog before the tab is built
            try:
                mod.register()
            except Exception as _fw_err:
                _fw_log("cmtabs.py:evaluate", _fw_err)
        layout = tuple(have["Evaluate"][1])
        if "EV_Simulation" not in repr(layout):
            have["Evaluate"] = ("Evaluate", layout + (("sep",),) + tuple(evaltools.GROUP))
    keep = list(have.values())
    original = [t[0] for t in keep]
    keep.sort(key=lambda t: (_rank(t[0]), original.index(t[0])))
    _ALL_TABS[:] = keep
    return keep


def apply(rebuild=True):
    """catalog.TABS = the shown tabs; rebuilds the CommandManager when it is up."""
    from . import catalog
    off = set(hidden()) | set(addin_off())
    every = all_tabs()
    shown = tuple(t for t in every if t[0] not in off) or tuple(every[:1])
    catalog.TABS = shown
    if rebuild:
        sh = _shell()
        if sh is not None:
            try:
                from . import asmui
                asmui.update_tabs(force=True)
            except Exception:
                try:
                    sh._build_pages()
                except Exception as _fw_err:
                    _fw_log("cmtabs.py:273", _fw_err)
            _hook_tab_row(sh)
    return shown


def _shell():
    try:
        from . import swmenus
        return swmenus._shell()
    except Exception as _fw_err:
        _fw_log("cmtabs.py:285", _fw_err)
        return None


# --------------------------------------------------------------------- right-click > Tabs
if Gui is not None:
    class _TabsMenu(QtCore.QObject):
        def eventFilter(self, obj, event):
            if not isinstance(event, QtCore.QEvent):
                return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
            if event.type() == QtCore.QEvent.ContextMenu:
                tabs_menu(obj).exec_(event.globalPos())
                return True
            return False

    _FILTER = []

    def _hook_tab_row(sh):
        row = getattr(getattr(sh, "topbar", None), "tabs", None)
        if not isinstance(row, QtWidgets.QWidget) or row.property("fw_tabs_menu"):
            return
        if not _FILTER:
            _FILTER.append(_TabsMenu())
        row.installEventFilter(_FILTER[0])
        row.setProperty("fw_tabs_menu", True)

    def tabs_menu(parent=None):
        ""
        menu = QtWidgets.QMenu(parent)
        sub = menu.addMenu("Tabs")
        off = set(hidden())
        for title, _layout in all_tabs():
            act = sub.addAction(title)
            act.setCheckable(True)
            act.setChecked(title not in off)
            act.toggled.connect(lambda on, t=title: toggle(t, on))
        menu.addSeparator()
        menu.addAction("Customize Tabs...", lambda: TabsDialog().exec_())
        return menu

    def toggle(title, on):
        off = [t for t in hidden() if t != title]
        if not on:
            off.append(title)
        set_hidden(off)
        apply()

    class TabsDialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.setWindowTitle("CommandManager Tabs")
            lay = QtWidgets.QVBoxLayout(self)
            lay.addWidget(QtWidgets.QLabel("Tabs shown in the CommandManager:"))
            off = set(hidden())
            self.boxes = []
            for title, _layout in all_tabs():
                cb = QtWidgets.QCheckBox(title)
                cb.setChecked(title not in off)
                lay.addWidget(cb)
                self.boxes.append(cb)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)

        def accept(self):
            set_hidden([cb.text() for cb in self.boxes if not cb.isChecked()])
            apply()
            super().accept()

    class _TabsCmd:
        def GetResources(self):
            return {"MenuText": "Customize CommandManager Tabs...",
                    "ToolTip": "Shows or hides CommandManager tabs (right-click the tab row > Tabs)."}

        def IsActive(self):
            return True

        def Activated(self):
            TabsDialog().exec_()


def install():
    """Called at startup, after the other modules' tabs: our keys and tabs, then the shown set."""
    _add_keys()
    apply(rebuild=_shell() is not None)
    if Gui is not None:
        if "SWStyle_CommandManagerTabs" not in Gui.listCommands():
            Gui.addCommand("SWStyle_CommandManagerTabs", _TabsCmd())
        # the tab row is made with the CommandManager: hook its right-click once it is up
        def later(tries=[0]):
            sh = _shell()
            if sh is not None and getattr(sh, "topbar", None) is not None:
                _hook_tab_row(sh)
            elif tries[0] < 20:
                tries[0] += 1
                QtCore.QTimer.singleShot(1000, later)
        QtCore.QTimer.singleShot(1000, later)
