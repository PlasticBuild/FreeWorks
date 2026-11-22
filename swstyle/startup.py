# SPDX-License-Identifier: LGPL-2.1-or-later
"""Called from InitGui.py while FreeCAD starts, before its window is shown."""

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
from PySide import QtCore

from . import icons, paths

Qt = QtCore.Qt
_poll = None


class ToggleCommand:
    def GetResources(self):
        return {
            "MenuText": "Feature-based interface",
            "ToolTip": "Switch between the feature-based interface and the classic FreeCAD interface",
        }

    def Activated(self):
        from . import shell
        shell.toggle()

    def IsActive(self):
        return True


class Manipulator:
    ""



    def modifyMenuBar(self):
        have = set(Gui.listCommands())
        # "insert" with "after" does nothing when the anchor ends its menu; "append" puts it after
        items = [{"append": "SWStyle_Toggle", "menuItem": "Std_DlgPreferences"}]

        if "SWStyle_NewDocument" in have:
            items.append({"insert": "SWStyle_NewDocument", "menuItem": "Std_New"})

        for ours, theirs in (("SWStyle_Open", "Std_Open"), ("SWStyle_SaveAs", "Std_SaveAs")):
            if ours in have:
                items += [{"insert": ours, "menuItem": theirs}, {"remove": theirs}]
        if "SWStyle_Options" in have:
            items.append({"insert": "SWStyle_Options", "menuItem": "Std_DlgPreferences"})
        # Std_Measure is in FreeCAD 1.1's Tools menu in every build; the Addon Manager is not.

        tools = [name for name in ("SWStyle_AutomaticRelations", "SWStyle_DetachSegmentOnDrag", "SWStyle_OverrideDimsOnDrag",
                                   "SWStyle_NoSolveMove", "SWStyle_ShortcutBar", "SWStyle_MouseGestures") if name in have]
        items += [{"insert": name, "menuItem": "Std_Measure"} for name in tools]
        if "SWStyle_FeaturePaint" in have and "Std_ClarifySelection" in have:

            items.append({"insert": "SWStyle_FeaturePaint", "menuItem": "Std_ClarifySelection"})
        if "SWStyle_Compare" in have and "Std_ClarifySelection" in have:

            items.append({"insert": "SWStyle_Compare", "menuItem": "Std_ClarifySelection"})
        if "SWStyle_FindModify" in have and "Std_ClarifySelection" in have:
            items.append({"insert": "SWStyle_FindModify", "menuItem": "Std_ClarifySelection"})
        try:
            from . import sketchtoolsmenu
            items += sketchtoolsmenu.menu_items(set(Gui.listCommands()))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: no Sketch Tools menu (%s)\n" % error)
        try:
            from . import blocksmenu
            items += blocksmenu.menu_items(have)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: no Blocks menu (%s)\n" % error)
        if tools:
            items.append({"insert": "Separator", "menuItem": "Std_Measure"})
        try:
            from . import keys
            items += keys.menu_items(have)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: no key commands in menus (%s)\n" % error)
        try:
            from . import swkeys
            items += swkeys.menu_items(have)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: no key commands in menus (%s)\n" % error)
        try:
            from . import wheelzoom
            items += wheelzoom.menu_items(have)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: no zoom switch in the View menu (%s)\n" % error)
        try:
            from . import sectionview
            items += sectionview.menu_items(set(Gui.listCommands()))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: no Section View in the View menu (%s)\n" % error)

        # stands for Display), View > Modify has Rotate About Scene Floor and Turn Camera beside Zoom About Screen Center
        have = set(Gui.listCommands())
        tangent = [name for name in ("SWStyle_TangentEdgesRemoved", "SWStyle_TangentEdgesPhantom",
                                     "SWStyle_TangentEdgesVisible") if name in have]
        items += [{"insert": name, "menuItem": "Std_DrawStyle", "after": ""} for name in tangent]
        if "SWStyle_RotateAboutSceneFloor" in have and "SWStyle_ZoomAboutScreenCenter" in have:
            items.append({"insert": "SWStyle_RotateAboutSceneFloor", "menuItem": "SWStyle_ZoomAboutScreenCenter",
                          "after": ""})
        if "SWStyle_TurnCamera" in have and "SWStyle_ZoomAboutScreenCenter" in have:
            items.append({"insert": "SWStyle_TurnCamera", "menuItem": "SWStyle_ZoomAboutScreenCenter", "after": ""})
        # viewmenu.py sorts these into View > Lights and Cameras
        if "SWStyle_ZoomAboutScreenCenter" in have:
            items += [{"insert": name, "menuItem": "SWStyle_ZoomAboutScreenCenter", "after": ""}
                      for name in ("SWStyle_CameraView", "SWStyle_AddCamera", "SWStyle_GoToMarkupView",
                                   "SWStyle_ModelBreakView", "SWStyle_ToggleModelBreak", "SWStyle_ChangeDisplayStates",
                                   "SWStyle_AddDisplayState", "SWStyle_AddWalkThrough", "SWStyle_Cartoon",
                                   "SWStyle_DraftQualityHLR", "SWStyle_PlayWalkThrough") if name in have]

        if "SWStyle_OrientationMenu" in have and "SWStyle_StandardFront" in have:
            items.append({"insert": "SWStyle_OrientationMenu", "menuItem": "SWStyle_RotateAboutSceneFloor", "after": ""})
            items.append({"insert": "SWStyle_SetCurrentViewAsMenu", "menuItem": "SWStyle_OrientationMenu", "after": ""})
        return items


# FreeCAD 1.1 keeps no reference to a manipulator: an unreferenced one is dropped with its entries.
_manipulator = None


_cover = {"widget": None, "filter": None, "covered": 0.0, "built": 0.0, "uncovered": 0.0}
COVER_MS = 250          # after the shell is built: its own placing passes (0 and 200 ms) are done by then
COVER_LIMIT_MS = 20000  # never longer than this, whatever happens at start-up


class _CoverFilter(QtCore.QObject):
    """Keeps the cover over the whole window and over anything FreeCAD adds while it starts."""

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        w = _cover["widget"]
        if w is None:
            return False
        try:
            t = event.type()
            if t == QtCore.QEvent.Resize:
                w.setGeometry(obj.rect())
            elif t == QtCore.QEvent.ChildAdded:
                QtCore.QTimer.singleShot(0, _raise_cover)
        except Exception as _fw_err:
            _fw_log("startup.py:cover-filter", _fw_err)
        return False


def _raise_cover():
    w = _cover["widget"]
    if w is not None:
        try:
            w.raise_()
        except Exception as _fw_err:
            _fw_log("startup.py:cover-raise", _fw_err)


def _cover_start(mw):
    """hudbelow-1122: a cold start showed stock FreeCAD's toolbars and panes for a moment before the
    add-on's window was built over them. A plain panel in the theme's chrome colour covers the main
    window from its first paint until the add-on's window is in place (or COVER_LIMIT_MS at most).
    Option: CoverStart in the add-on's settings (paths.params, default True)."""
    import time
    from PySide import QtGui, QtWidgets
    from . import style
    w = QtWidgets.QWidget(mw)
    w.setObjectName("FW_StartCover")
    w.setAutoFillBackground(True)
    pal = w.palette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor(style.tokens()["pane"]))
    w.setPalette(pal)
    w.setGeometry(mw.rect())
    w.show()
    w.raise_()
    f = _CoverFilter(mw)
    mw.installEventFilter(f)
    _cover.update(widget=w, filter=f, covered=time.time())
    QtCore.QTimer.singleShot(COVER_LIMIT_MS, _uncover)


def _uncover():
    import time
    w, f = _cover["widget"], _cover["filter"]
    _cover["widget"] = _cover["filter"] = None
    if w is None:
        return
    _cover["uncovered"] = time.time()
    try:
        mw = w.parentWidget()
        if mw is not None and f is not None:
            mw.removeEventFilter(f)
        w.hide()
        w.deleteLater()
        if f is not None:
            f.deleteLater()
    except Exception as _fw_err:
        _fw_log("startup.py:uncover", _fw_err)


def _start_when_ready():
    global _poll
    mw = Gui.getMainWindow()
    try:
        active = Gui.activeWorkbench() is not None
    except Exception:
        active = False
    if mw is None or not mw.isVisible() or not active:
        return
    _poll.stop()
    _poll = None
    try:
        # extapps/64: the add-on's application filters, held while FreeCAD started and while the shell below is built,
        # are installed once this start-up step is over (in the order they were asked for)
        from . import safeguards as _safeguards
        QtCore.QTimer.singleShot(0, _safeguards.release)
    except Exception as _fw_err:
        _fw_log("startup.py:release", _fw_err)
    from . import shell
    try:
        shell.set_enabled(True)
    except Exception:
        import traceback
        App.Console.PrintError("FreeCAD could not start:\n%s\n" % traceback.format_exc())
        try:
            shell.set_enabled(False)
        except Exception as _fw_err:
            _fw_log("startup.py:152", _fw_err)
        paths.params().SetBool("Enabled", True)
    finally:
        if _cover["widget"] is not None:
            import time
            _cover["built"] = time.time()
            QtCore.QTimer.singleShot(COVER_MS, _uncover)


REQUEST_FILE = "swstyle-theme.request"


def theme_request():
    """A theme asked for from outside FreeCAD (a file with Light, Dark or AMOLED in FreeCAD's user
    data folder, written while FreeCAD runs or is closed): stored as the theme at the next start,
    the theme's own viewport, and the file removed. FreeCAD rewrites user.cfg when it closes, so
    the setting itself cannot be edited from outside while it runs."""
    import os
    from . import style
    path = os.path.join(App.getUserAppDataDir(), REQUEST_FILE)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            name = f.read().strip()
        os.remove(path)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: theme request not read: %s\n" % error)
        return None
    match = [t for t in style.THEMES if t.lower() == name.lower()]
    if not match:
        App.Console.PrintWarning("FreeCAD: unknown theme requested: %r\n" % name)
        return None
    store = paths.params()
    store.SetString(style.THEME_SETTING, match[0])
    store.SetInt(style.SCENE_SETTING, -1)
    App.Console.PrintLog("FreeCAD: theme %s requested from outside\n" % match[0])
    return match[0]


def init():
    global _poll, _manipulator
    try:
        # first: observers and Python-owned Qt objects go before FreeCAD shuts down (exit crashes, review 1119)
        from . import teardown
        teardown.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: teardown guard: %s\n" % error)
    try:

        # own recovery box, shown before the window is up, does not list them
        from . import recovery
        recovery.hold_for_task_pane()
    except Exception as _fw_err:
        _fw_log("startup.py:recovery", _fw_err)
    try:
        # extapps/64: FreeCADGui.getMainWindow() leaks a connection per call in FreeCAD 1.1.4 (mainwin.py)
        from . import mainwin
        mainwin.install()
    except Exception as _fw_err:
        _fw_log("startup.py:mainwin", _fw_err)
    try:

        # leaves stock FreeCAD as it was (toolbars showing again at every close)
        from . import stockrestore
        stockrestore.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: stock settings baseline: %s\n" % error)
    try:

        from . import safeguards
        safeguards.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: event filter guard: %s\n" % error)
    try:
        # one document observer for the property changes the others ask for (each change was 38 Python calls)
        from . import obshub
        obshub.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: observer hub: %s\n" % error)
    try:
        # the pollers rest while nothing happens (extapps/58): installed before any of them starts
        from . import ticks
        ticks.install_hook()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: idle rest: %s\n" % error)
    try:

        from . import migrate
        migrate.run()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: old settings not copied: %s\n" % error)
    try:
        # documents saved before the name left the interface: property group and tooltip say FreeCAD
        from . import fwnames
        fwnames.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: property names: %s\n" % error)
    try:
        # freshdark-1121: stock FreeCAD's navigation indicator names the style with another company's name
        from . import navlabel
        navlabel.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: navigation label: %s\n" % error)
    try:
        # message boxes draw the add-on's own pictures instead of the Windows stock ones
        from . import msgicons
        msgicons.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: message box pictures: %s\n" % error)
    params = paths.params()
    Gui.addCommand("SWStyle_Toggle", ToggleCommand())
    try:
        # Multibody parts: Solid Bodies folder, Merge result, Delete/Keep, Move/Copy, Combine, Mirror Body
        from . import multibody
        multibody.install()
        from . import memtrim             # extapps/63: shape caches let go of a part when it closes
        memtrim.install()
        from . import surfacebodies       # the Surface Bodies folder
        surfacebodies.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: multibody parts not added: %s\n" % error)
    try:
        # the SheetMetal and FrameForge add-ons' commands, behind the Sheet Metal and Weldments tabs
        from . import smengine
        smengine.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sheet metal and weldments engines not loaded: %s\n" % error)
    try:
        # Sketcher > Relations/Snaps and > Sketch in Options, the Automatic Relations command
        from . import sketchoptions
        sketchoptions.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sketch options not added: %s\n" % error)
    try:


        from .fwsketch import commands as fwsketch_commands
        fwsketch_commands.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Python sketch tools not added: %s\n" % error)
    try:
        # Fully Define Sketch, Auto Insert Dimension and the other dimensioning commands
        from . import checkstate, dimcommands, sketchview
        dimcommands.register()
        # the CommandManager's toggles show pressed while on (no QAction to read for them)
        checkstate.register("SWStyle_Instant2D", dimcommands.instant2d_on)
        checkstate.register("SWStyle_ViewSketchRelations", lambda: sketchview.shown("Relations"))
        checkstate.register("SWStyle_ViewSketchDimensions", lambda: sketchview.shown("Dimensions"))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: dimension commands not added: %s\n" % error)
    try:

        from . import newdoc, options
        newdoc.register()
        from . import saveas
        saveas.register()
        options.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: New and Options boxes not added: %s\n" % error)
    try:
        # View Orientation (Space), Shortcut Bar (S), Normal To (Ctrl+8), Forced Rebuild (Ctrl+Q)
        from . import keys
        keys.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: key commands not added: %s\n" % error)
    try:

        from . import swkeys
        swkeys.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: key commands not added: %s\n" % error)
    try:
        # File menu: Page Setup, Print Preview, Print (Ctrl+P), Print3D, Pack and Go, Send To, Find References
        from . import filecmds
        filecmds.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: File menu commands not added: %s\n" % error)
    try:
        # Tools > Blocks: sketch blocks (Make, Edit, Insert, Add/Remove, Rebuild, Save, Explode)
        from . import blocksmenu
        blocksmenu.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sketch blocks not added: %s\n" % error)
    try:
        # Tools > Sketch Tools > Make Path / Dissolve Path (sketchpath.py)
        from . import sketchpath
        sketchpath.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Make Path not added: %s\n" % error)
    try:
        # Tools > Mouse Gestures
        from . import gestures
        gestures.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: mouse gestures switch not added: %s\n" % error)
    try:
        # Display > View in Options, Zoom About Screen Center in the View menu
        from . import wheelzoom
        wheelzoom.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: view options not added: %s\n" % error)
    try:

        # the View Selector
        from . import themeoptions
        themeoptions.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: look options not added: %s\n" % error)
    try:

        from . import firststart
        firststart.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Start page theme row not linked: %s\n" % error)
    try:
        # 3D Slicer tab after Sketch: Orca Slicer and Bambu Studio (before the CommandManager is built)
        from . import slicerui
        slicerui.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: 3D Slicer tab not added: %s\n" % error)
    try:

        from . import asmui
        asmui.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: assemblies not added: %s\n" % error)
    try:
        # Evaluate tab: Section Properties, Interference Detection, Draft Analysis, Geometry Analysis,
        # Performance Evaluation, Symmetry Check, Check
        from . import evaluate
        evaluate.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: evaluate tools not added: %s\n" % error)
    try:
        # Hide/Show Items by type (View Planes, View Sketches... Hide All Types) and Curves
        # (Composite, Through XYZ Points, Through Reference Points) + Center of Mass
        from . import viewtypes, curves, sketchextras
        viewtypes.install()
        curves.install()
        sketchextras.install()
        from . import featurecopy
        featurecopy.install()           # Ctrl+C / Ctrl+V and Ctrl-drag of a feature onto a face
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: view types, curves and sketch extras not added: %s\n" % error)
    try:
        # Tangent edges visible/phantom/removed, Rotate About Scene Floor, Isolate
        from . import displayextras
        displayextras.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: display extras not added: %s\n" % error)
    try:
        # New View, Update/Reset Standard Views, Set Current View As
        from . import namedviews
        namedviews.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: named views not added: %s\n" % error)
    try:
        # Curvature, Zebra Stripes, Body Compare, Sensor; Invert Selection, Delete Hole, Save Bodies;
        # Quick Snaps (one-shot snap filters)
        from . import evaluate2, parttools, quicksnaps, pmprompts
        evaluate2.install()
        pmprompts.install()
        parttools.install()
        quicksnaps.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: evaluate extras, part tools and quick snaps not added: %s\n" % error)
    try:
        # Instant3D: drag an arrow on a picked extrude face to change its depth; Sketch Text and
        # Dissolve Sketch Text; the move triad on a picked sketch
        from . import instant3d, sketchtext, deleteface, sketchtriad, rapidsketch, slicingpm, pmconfirm
        instant3d.install()
        sketchtriad.install()
        rapidsketch.install()      # Rapid Sketch (Sketch tab)
        sketchtext.install()
        deleteface.install()
        slicingpm.install()
        pmconfirm.install()      # Enter = OK, Esc = Cancel on every PropertyManager (pkg93)
        from . import pmundo
        pmundo.start()           # Ctrl+Z inside a PropertyManager (pkg96)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Instant3D and sketch text not added: %s\n" % error)
    try:
        # Options that need something running: spin box increments, the unsaved reminder,
        # open last used documents at startup
        from . import optionsextras
        optionsextras.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: options extras not added: %s\n" % error)
    try:

        from . import dismissedicon
        dismissedicon.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: dismissed messages icon not added: %s\n" % error)
    try:
        # Selection Filter toolbar (F5) and its filters (F6, E, V, X)
        from . import selfilter
        selfilter.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: selection filter not added: %s\n" % error)
    try:
        # Line Format toolbar (off by default): Line Color, Line Thickness, Line Style
        from . import linebar
        linebar.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Line Format toolbar not added: %s\n" % error)
    try:

        from . import viewmenu
        viewmenu.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: View menu not grouped: %s\n" % error)
    try:

        from . import undowording
        undowording.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Undo wording not added: %s\n" % error)
    try:

        from . import windowmenu
        windowmenu.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Window menu not added: %s\n" % error)
    try:

        from . import swmenus, swkeys
        swmenus.install()
        swkeys.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: menus not added: %s\n" % error)
    try:

        from . import closeprompt
        closeprompt.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: close prompt not added: %s\n" % error)
    try:
        # parts saved with FreeCAD's shiny default look are shown matte
        from . import matte
        matte.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: matte faces not set: %s\n" % error)
    try:
        # Tools > Evaluate > Import Diagnostics: faulty faces and gaps of an imported body, healed
        from . import importdiag
        importdiag.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Import Diagnostics not added: %s\n" % error)
    try:
        # Insert Line and Trim PropertyManagers beside FreeCAD's tools; Mirror Entities page
        from . import nativepms
        nativepms.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Line, Trim and Mirror PropertyManagers not added: %s\n" % error)
    try:

        from . import confirmdelete
        confirmdelete.install()
        QtCore.QTimer.singleShot(3000, confirmdelete.install)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Confirm Delete not added: %s\n" % error)
    try:

        from . import stoprepair
        stoprepair.install()
        from . import rebuilderrors          # dangling relations, error tooltips (features/84)
        rebuilderrors.install()
        from . import featuredimshow         # double-click shows a feature's dimensions (features/85)
        featuredimshow.install()
        from . import treefilter             # Tags and the tree filter's funnel menu (features/88)
        treefilter.install()
        from . import treerefs
        treerefs.install()
        from . import insertpart, bodycheck  # Insert > Part, Bodies to Keep (features/89)
        insertpart.register()
        bodycheck.install()
        from . import upbody     # Up To Body in multibody parts (features/91)
        upbody.install()
        from . import refpattern     # planes / axes / points in patterns and mirrors (features/256)
        refpattern.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Stop and Repair not added: %s\n" % error)
    try:
        # "Rebuilding, Please wait ..." in the status bar while the part rebuilds
        from . import rebuildstatus
        rebuildstatus.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: rebuild message not added: %s\n" % error)
    try:

        from . import filletchamfer
        filletchamfer.install_observer()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Fillet and Chamfer last values not added: %s\n" % error)
    try:

        from . import offsetentities
        offsetentities.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Offset Entities not added: %s\n" % error)
    try:

        # is viewtypes' SWStyle_ViewDimensionNames)
        from . import dimensionnames
        dimensionnames.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Dimension Names not set: %s\n" % error)
    try:

        from . import convertentities
        convertentities.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Convert Entities not added: %s\n" % error)
    try:

        from . import refplane
        refplane.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Plane PropertyManager not added: %s\n" % error)
    try:

        from . import refaxis
        refaxis.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Axis PropertyManager not added: %s\n" % error)
    try:

        from . import mirrorpm
        mirrorpm.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Mirror PropertyManager not added: %s\n" % error)
    try:

        from . import appearance
        appearance.register()
        from . import scenepm     # Edit Scene PropertyManager (features/90)
        scenepm.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Appearances not added: %s\n" % error)
    try:

        from . import filletpm
        filletpm.install()
        from . import extrudepm
        extrudepm.startup()
        from . import pmtakeover
        pmtakeover.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Fillet/Chamfer PropertyManagers not added: %s\n" % error)
    try:

        from . import patternpm
        patternpm.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Pattern PropertyManagers not added: %s\n" % error)
    try:

        from . import revolveaxis
        revolveaxis.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Revolve centerline not added: %s\n" % error)
    try:

        from . import filletkinds
        filletkinds.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Face / Full Round Fillet not added: %s\n" % error)
    try:

        from . import shapetypes
        shapetypes.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: rectangle and slot types not added: %s\n" % error)
    try:

        from . import measure
        measure.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Measure not added: %s\n" % error)
    try:

        from . import hlv
        hlv.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Hidden Lines Visible not added: %s\n" % error)
    try:

        from . import boxselect
        boxselect.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: box selection not added: %s\n" % error)
    try:

        from . import stretch
        stretch.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Stretch Entities not added: %s\n" % error)
    try:

        from . import magnify
        magnify.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Magnified Selection not added: %s\n" % error)
    try:

        from . import bodysize
        bodysize.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Select Bodies by Size not added: %s\n" % error)
    try:

        from . import conic
        conic.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Conic not added: %s\n" % error)
    try:

        from . import variablepattern
        variablepattern.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Variable Pattern not added: %s\n" % error)
    try:

        from . import trimsurface
        trimsurface.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Trim Surface not added: %s\n" % error)
    try:

        from . import boundarysurface
        boundarysurface.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Boundary Surface not added: %s\n" % error)
    try:

        from . import flex
        flex.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Flex not added: %s\n" % error)
    try:

        from . import replaceentity
        replaceentity.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Replace Entity not added: %s\n" % error)
    try:

        from . import pathlength
        pathlength.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Path Length Dimension not added: %s\n" % error)
    try:

        from . import wrap
        wrap.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Wrap not added: %s\n" % error)
    try:

        from . import boundaryboss
        boundaryboss.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Boundary Boss/Cut not added: %s\n" % error)
    try:

        from . import cosmeticthread
        cosmeticthread.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Cosmetic Thread not added: %s\n" % error)
    try:

        from . import splinetools
        splinetools.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Spline Tools not added: %s\n" % error)
    try:

        from . import sketch3d
        sketch3d.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: 3D Sketch not added: %s\n" % error)
    try:

        from . import drawings
        drawings.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing views not added: %s\n" % error)
    try:

        from . import drawsheet
        drawsheet.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing sheets not added: %s\n" % error)
    try:

        from . import drawviews
        drawviews.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: section and detail views not added: %s\n" % error)
    try:

        from . import drawannot
        drawannot.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing annotations not added: %s\n" % error)
    try:

        from . import drawtables
        drawtables.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing tables not added: %s\n" % error)
    try:

        from . import replaceface
        replaceface.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Replace Face not added: %s\n" % error)
    try:

        from . import untrimsurface
        untrimsurface.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Untrim Surface not added: %s\n" % error)
    try:

        from . import rollbackhold
        rollbackhold.start()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: rollback hold not started: %s\n" % error)
    try:

        from . import surfacefillet
        surfacefillet.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Surface Fillet not added: %s\n" % error)
    try:

        from . import midsurface
        midsurface.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Mid-Surface not added: %s\n" % error)
    try:

        from . import aligngrid
        aligngrid.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Align Grid/Origin not added: %s\n" % error)
    try:

        from . import healedges
        healedges.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Heal Edges not added: %s\n" % error)
    try:

        from . import detachdrag
        detachdrag.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Detach Segment on Drag not added: %s\n" % error)
    try:

        from . import beltchain
        beltchain.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Belt/Chain not added: %s\n" % error)
    try:

        from . import undercut
        undercut.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Undercut Analysis not added: %s\n" % error)
    try:

        from . import jogline
        jogline.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Jog Line not added: %s\n" % error)
    try:

        from . import closetomodel
        closetomodel.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Close Sketch to Model not added: %s\n" % error)
    try:

        from . import overridedrag
        overridedrag.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Override Dims on Drag/Move not added: %s\n" % error)
    try:

        from . import nosolvemove
        nosolvemove.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: No Solve Move not added: %s\n" % error)
    try:

        from . import thickness
        thickness.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Thickness Analysis not added: %s\n" % error)
    try:

        from . import partingline
        partingline.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Parting Line Analysis not added: %s\n" % error)
    try:

        from . import compare
        compare.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Compare not added: %s\n" % error)
    try:

        from . import findmodify
        findmodify.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Find/Modify not added: %s\n" % error)
    try:

        from . import sketchink
        sketchink.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Sketch Ink not added: %s\n" % error)
    try:

        from . import turncamera
        turncamera.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Turn Camera not added: %s\n" % error)
    try:

        from . import designstudy
        designstudy.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Design Study not added: %s\n" % error)
    try:

        from . import cameras
        cameras.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Cameras not added: %s\n" % error)
    try:

        from . import curvaturecombs
        curvaturecombs.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Curvature Combs not added: %s\n" % error)
    try:

        from . import texture3d
        texture3d.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: 3D Texture not added: %s\n" % error)
    try:

        from . import gridsystem
        gridsystem.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Grid System not added: %s\n" % error)
    try:

        from . import cartoon
        cartoon.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Cartoon not added: %s\n" % error)
    try:

        from . import viewsettings
        viewsettings.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: View Settings not added: %s\n" % error)
    try:

        from . import gusset
        gusset.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Gusset not added: %s\n" % error)
    try:

        from . import walkthrough
        walkthrough.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Walk-through not added: %s\n" % error)
    try:

        from . import displaystates
        displaystates.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Display States not added: %s\n" % error)
    try:

        from . import modelbreak
        modelbreak.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Model Break View not added: %s\n" % error)
    try:

        from . import markup
        markup.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Markup not added: %s\n" % error)
    try:

        from . import edgetip
        edgetip.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: feature tip not added: %s\n" % error)
    try:

        from . import recentvalues
        recentvalues.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: recent values list not added: %s\n" % error)
    try:

        from . import featurepaint
        featurepaint.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Feature Paint not added: %s\n" % error)
    try:

        from . import sketchtoolsmenu
        sketchtoolsmenu.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Sketch Entities/Tools menus not added: %s\n" % error)
    try:
        _manipulator = Manipulator()
        Gui.addWorkbenchManipulator(_manipulator)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: no menu entry (%s)\n" % error)
    if not params.GetBool("Enabled", True):
        return
    try:
        from . import optionsextras4      # Options > Colors > Icon color = Classic: FreeCAD's own icons
        classic = optionsextras4.is_classic_icons()
    except Exception:
        classic = False
    if not classic and icons.install_freecad_overrides():
        App.Console.PrintLog("FreeCAD: icon overrides from %s\n" % icons.root())
    # Before the Start page can pick FreeCAD's dark theme for a new profile.
    try:
        from . import style
        theme_request()
        style.apply_settings()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: settings not applied at start: %s\n" % error)
    mw = Gui.getMainWindow()
    if params.GetBool("Frameless", True) and mw is not None and not mw.isVisible():
        mw.setWindowFlag(Qt.FramelessWindowHint, True)
    try:
        if params.GetBool("CoverStart", True) and mw is not None and not mw.isVisible():
            _cover_start(mw)
    except Exception as _fw_err:
        _fw_log("startup.py:cover", _fw_err)
    try:
        from .widgets import release_python_hooks
        QtCore.QCoreApplication.instance().aboutToQuit.connect(release_python_hooks)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: quit hook not set: %s\n" % error)
    try:
        from . import safeguards as _safeguards
        QtCore.QTimer.singleShot(30000, _safeguards.release)     # extapps/64: in case start-up never gets there
    except Exception as _fw_err:
        _fw_log("startup.py:release-fallback", _fw_err)
    _poll = QtCore.QTimer()
    _poll.setInterval(100)
    _poll.timeout.connect(_start_when_ready)
    _poll.start()
