# SPDX-License-Identifier: LGPL-2.1-or-later
""










_FW_SEEN = set()



def _qt_safe(fn):
    """A tree Model override that never lets an error out into Qt (FreeCAD on Windows aborts):
    rows of objects deleted while a document closes give no data."""
    def data(self, index, role=0):
        try:
            return fn(self, index, role)
        except Exception as error:
            if not isinstance(error, (ReferenceError, RuntimeError)):
                App.Console.PrintLog("FreeCAD: tree row: %r\n" % (error,))
            return None
    return data

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

from . import asmcore as ac
from . import paths
from .widgets import alive

Qt = QtCore.Qt
SOON = 150


def _assembly():
    return ac.assembly_of(App.ActiveDocument)


# ============================================================================= commands
class InsertComponentsCommand:
    def GetResources(self):
        from . import asmpm
        asmpm._load_icons()
        return {"MenuText": "Insert Components", "Pixmap": "Assembly_InsertLink",
                "ToolTip": "Brings a part or subassembly into the assembly."}

    def Activated(self):
        start_insert(begin=False)

    def IsActive(self):
        return _assembly() is not None and _free()


class MateCommand:
    def GetResources(self):
        return {"MenuText": "Mate", "Pixmap": "Assembly_CreateJointDistance",
                "ToolTip": "Places two components against each other with a mate."}

    def Activated(self):
        from . import asmpm
        asm = _assembly()
        if not asmpm.close_open():
            return
        Gui.Control.showDialog(asmpm.MatePanel(asm))

    def IsActive(self):
        asm = _assembly()
        return asm is not None and len(ac.components(asm)) > 0 and _free()


class _CompCommand:
    def _picked(self):
        asm = _assembly()
        out = []
        if asm is None:
            return asm, out
        comps = ac.components(asm)
        for sel in Gui.Selection.getSelectionEx("", 0):
            if sel.Object in comps:
                out.append(sel.Object)
            for sub in sel.SubElementNames:
                ref = ac.reference(asm, sel.Object, sub) if sub else None
                if ref is not None and ref[0] not in out:
                    out.append(ref[0])
        return asm, out


class FixCommand(_CompCommand):
    def GetResources(self):
        return {"MenuText": "Fix", "Pixmap": "Assembly_ToggleGrounded",
                "ToolTip": "Locks the component where it is."}

    def Activated(self):
        asm, comps = self._picked()
        asm.Document.openTransaction("Fix")
        try:
            for comp in comps:
                ac.fix(asm, comp)
        except BaseException:
            try:
                asm.Document.abortTransaction()
            except Exception:
                pass
            raise
        asm.Document.commitTransaction()
        refresh()

    def IsActive(self):
        asm, comps = self._picked()
        return bool(comps) and any(c not in ac.grounded(asm) for c in comps)


class FloatCommand(_CompCommand):
    def GetResources(self):
        return {"MenuText": "Float", "Pixmap": "Assembly_ToggleGrounded",
                "ToolTip": "Lets the component move; mates position it."}

    def Activated(self):
        asm, comps = self._picked()
        asm.Document.openTransaction("Float")
        try:
            for comp in comps:
                ac.float_(asm, comp)
        except BaseException:
            try:
                asm.Document.abortTransaction()
            except Exception:
                pass
            raise
        asm.Document.commitTransaction()
        refresh()

    def IsActive(self):
        asm, comps = self._picked()
        return bool(comps) and any(c in ac.grounded(asm) for c in comps)


class MoveComponentCommand:
    rotate = False

    def GetResources(self):
        return ({"MenuText": "Rotate Component", "Pixmap": "Std_TransformManip",
                 "ToolTip": "Turns a component as far as its mates allow."}
                if self.rotate else
                {"MenuText": "Move Component", "Pixmap": "Std_TransformManip",
                 "ToolTip": "Slides a component as far as its mates allow."})

    def Activated(self):
        from . import asmpm
        asm = _assembly()
        if not asmpm.close_open():
            return
        activate(asm)
        Gui.Control.showDialog(asmpm.MoveComponentPanel(asm, rotate=self.rotate))

    def IsActive(self):
        asm = _assembly()
        return asm is not None and bool(ac.components(asm)) and _free()


class RotateComponentCommand(MoveComponentCommand):
    rotate = True


class NewAssemblyCommand:
    def GetResources(self):
        return {"MenuText": "Assembly", "Pixmap": "Geoassembly",
                "ToolTip": "Makes a new assembly and starts Insert Components."}

    def Activated(self):
        doc = App.newDocument("Assem1")
        new_assembly(doc)

    def IsActive(self):
        return True


def new_assembly(doc):
    """What New > Assembly makes: the assembly in doc, the assembly tabs, and Begin Assembly
    (Options > Start command when creating new assembly)."""
    from . import asmpm
    try:
        Gui.activateWorkbench("AssemblyWorkbench")
    except Exception as _fw_err:
        _fw_log("asmui.py:172", _fw_err)
    doc.openTransaction("New Assembly")
    try:
        asm = ac.make_assembly(doc)
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    QtCore.QTimer.singleShot(0, _close_new_step)
    activate(asm)
    refresh()
    if paths.params().GetBool(asmpm.START_PARAM, True):
        QtCore.QTimer.singleShot(300, lambda: start_insert(begin=True))
    return asm


def _close_new_step():
    """New > Assembly run as a command: FreeCAD holds the command's step open after the commit, so
    the next change (or a Cancel of Begin Assembly) still went into "New Assembly" and one Undo took
    the assembly away with it. Closed once the command has returned (kept, not undone)."""
    try:
        active = App.getActiveTransaction()
        if active and active[0] == "New Assembly":
            App.closeActiveTransaction(False, active[1])
    except Exception as _fw_err:
        _fw_log("asmui.py:new step", _fw_err)


def activate(asm):
    """FreeCAD's active assembly (its edit mode): parts then drag within their mates."""
    try:
        gdoc = Gui.getDocument(asm.Document.Name)
        edit = gdoc.getInEdit()
        if edit is None:
            with ac.quiet_edit(asm):        # it holds already: no whole solve to open the edit
                gdoc.setEdit(asm)
        from . import asmoptions
        if hasattr(asm.ViewObject, "EnableMovement"):
            asm.ViewObject.EnableMovement = asmoptions.move_by_dragging()
        if hasattr(asm.ViewObject, "MoveOnlyPreselected"):

            # under the pointer: FreeCAD otherwise walks every mate for every picked part on each
            # pick (picking 200 parts took 200 s)
            asm.ViewObject.MoveOnlyPreselected = True
        try:
            from . import asmseltriad
            asmseltriad.ensure()
        except Exception as _fw_err:
            _fw_log("asmui.py:seltriad", _fw_err)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly not activated: %s\n" % error)
        from . import fwtell
        fwtell.tell("The assembly could not be made active for editing.", error)


def activate_opened(doc):
    ""


    gdoc = Gui.ActiveDocument
    if not doc.FileName or gdoc is None or gdoc.Document is not doc or gdoc.getInEdit() is not None \
            or Gui.Control.activeDialog():
        return
    asm = ac.assembly_of(doc)
    if asm is None:
        return
    try:
        from . import saveas
        if saveas.open_mode(doc) in ("Large Design Review", "Quick View"):
            return
    except Exception:
        pass
    activate(asm)


def _free():
    """No panel open, or an assembly PropertyManager the next command may close."""
    if not Gui.Control.activeDialog():
        return True
    from . import asmpm
    return asmpm.OPEN is not None


def start_insert(begin=False):
    from . import asmpm
    asm = _assembly()
    if asm is None:
        return None
    if not asmpm.close_open():
        Gui.Control.closeDialog()
    panel = asmpm.InsertComponentPanel(asm, begin=begin)
    Gui.Control.showDialog(panel)
    return panel


COMMANDS = (("SWStyle_InsertComponents", InsertComponentsCommand), ("SWStyle_Mate", MateCommand),
            ("SWStyle_FixComponent", FixCommand), ("SWStyle_FloatComponent", FloatCommand),
            ("SWStyle_MoveComponent", MoveComponentCommand), ("SWStyle_RotateComponent", RotateComponentCommand),
            ("SWStyle_NewAssembly", NewAssemblyCommand))


def _app_filter(name, types, flt, on=True):
    ""
    try:
        from . import events
        if on:
            events.register(name, types, flt.eventFilter)
        else:
            events.unregister(name)
        return True
    except ImportError:
        app = QtWidgets.QApplication.instance()
        (app.installEventFilter if on else app.removeEventFilter)(flt)
        return False


# ============================================================================= CommandManager
ASSEMBLY_BUTTONS = (

    ("EditComponent", "Edit Component", ("SWStyle_EditComponent",), "ASSEMBLIES_EDIT_COMPONENT",
     "Edits the selected part in the context of the assembly; click again to go back.", "Edit\nComponent"),
    ("NoExternalReferences", "No External References", ("SWStyle_NoExternalReferences",), None,
     "When on, editing a part in the assembly makes no external references.", None),
    ("InsertComponents", "Insert Components", ("SWStyle_InsertComponents",), "ASSEMBLIES_INSERT_COMPONENTS",
     "Brings a part or subassembly into the assembly.", "Insert\nComponents"),
    ("NewPartInAssembly", "New Part", ("SWStyle_NewPartInAssembly",), "ASSEMBLIES_NEW_PART",
     "Creates a new part in the assembly: select a plane or face for it.", None),
    ("CopyWithMates", "Copy with Mates", ("SWStyle_CopyWithMates",), "ASSEMBLIES_COPY_WITH_MATES",
     "Copies a component together with its mates; pick the new mate entities.", None),
    ("Mate", "Mate", ("SWStyle_Mate",), "ASSEMBLIES_MATE",
     "Places two components against each other with a mate.", None),
    ("ComponentPreview", "Component Preview Window", ("SWStyle_ComponentPreview",), "ASSEMBLIES_COMPONENT_PREVIEW",
     "Shows the selected component alone in a window beside the assembly; pick its faces there.",
     "Component\nPreview Window"),
    ("LinearComponentPattern", "Linear Component Pattern", ("SWStyle_LinearComponentPattern",),
     "ASSEMBLIES_LINEAR_PATTERN", "Patterns components in a linear direction.", "Linear Component\nPattern"),
    ("CircularComponentPattern", "Circular Component Pattern", ("SWStyle_CircularComponentPattern",),
     "ASSEMBLIES_CIRCULAR_PATTERN", "Patterns components around an axis.", None),
    ("PatternDrivenComponentPattern", "Pattern Driven Component Pattern", ("SWStyle_PatternDrivenComponentPattern",),
     "ASSEMBLIES_PATTERN_DRIVEN_PATTERN", "Patterns components after a pattern in a part.", None),
    ("SketchComponentPattern", "Sketch Driven Component Pattern", ("SWStyle_SketchComponentPattern",),
     "ASSEMBLIES_SKETCH_DRIVEN_PATTERN", "Patterns components at the points of a sketch.", None),
    ("CurveComponentPattern", "Curve Driven Component Pattern", ("SWStyle_CurveComponentPattern",),
     "ASSEMBLIES_CURVE_DRIVEN_PATTERN", "Patterns components along a curve.", None),
    ("ChainComponentPattern", "Chain Component Pattern", ("SWStyle_ChainComponentPattern",),
     "ASSEMBLIES_CHAIN_PATTERN", "Patterns components along a path, as the links of a chain.", None),
    ("MirrorComponents", "Mirror Components", ("SWStyle_MirrorComponents",), "ASSEMBLIES_MIRROR_COMPONENTS",
     "Mirrors components about a plane or a flat face.", None),
    ("SmartFasteners", "Smart Fasteners", ("SWStyle_SmartFasteners",), "ASSEMBLIES_SMART_FASTENERS",
     "Adds fasteners (screws, nuts, washers) to the assembly.", "Smart\nFasteners"),
    ("MoveComponent", "Move Component", ("SWStyle_MoveComponent",), "ASSEMBLIES_MOVE_COMPONENT",
     "Slides a component as far as its mates allow.", "Move\nComponent"),
    ("RotateComponent", "Rotate Component", ("SWStyle_RotateComponent",), "ASSEMBLIES_ROTATE_COMPONENT",
     "Turns a component as far as its mates allow.", None),
    ("FixComponent", "Fix", ("SWStyle_FixComponent",), None, "Locks the component where it is.", None),
    ("FloatComponent", "Float", ("SWStyle_FloatComponent",), None, "Lets the component move; mates position it.", None),
    ("Interference", "Interference Detection", ("SWStyle_AssemblyInterference",), "ASSEMBLIES_INTERFERENCE_DETECTION",
     "Finds interferences between components (in a part: between its bodies).", "Interference\nDetection"),
    ("ShowHiddenComponents", "Show Hidden Components", ("SWStyle_ShowHiddenComponents", "Std_ShowAll"),
     "ASSEMBLIES_SHOW_HIDDEN",
     "Shows hidden components.", "Show Hidden\nComponents"),
    ("DisplayGraphicsComponents", "Display Graphics Components", ("SWStyle_DisplayGraphicsComponents",),
     "ASSEMBLIES_DISPLAY_GRAPHICS_COMPONENTS", "Shows or hides graphics components: SpeedPak and mesh components.",
     "Display Graphics\nComponents"),
    ("UpdateSpeedPak", "Update SpeedPak", ("SWStyle_UpdateSpeedPak",), "ASSEMBLIES_UPDATE_SPEEDPAK",
     "Updates the SpeedPak components of the assembly from their parts.", "Update\nSpeedPak"),
    ("BillOfMaterials", "Bill of Materials", ("SWStyle_AssemblyBOM", "Assembly_CreateBom"), "ASSEMBLIES_BOM",
     "Adds a bill of materials.", "Bill of\nMaterials"),
    ("ExplodedView", "Exploded View", ("SWStyle_ExplodedView", "Assembly_CreateView"), "ASSEMBLIES_EXPLODED_VIEW",
     "Separates the components into an exploded view.", "Exploded\nView"),
    ("ExplodeCollapse", "Explode / Collapse", ("SWStyle_ExplodeCollapse",), "ASSEMBLIES_EXPLODED_VIEW",
     "Collapses the exploded assembly, or explodes it again.", "Explode /\nCollapse"),
    ("ExplodeLineSketch", "Explode Line Sketch", ("SWStyle_ExplodeLineSketch",), "ASSEMBLIES_EXPLODE_LINE_SKETCH",
     "A 3D sketch for the explode lines (Route Line, Jog).", "Explode Line\nSketch"),
    ("TakeSnapshot", "Take Snapshot", ("SWStyle_TakeSnapshot", "Std_ViewSaveCamera"), "ASSEMBLIES_TAKE_SNAPSHOT",
     "Saves the view and the shown components as a snapshot; double-click it to go back.", "Take\nSnapshot"),
    ("NewMotionStudy", "New Motion Study", ("SWStyle_NewMotionStudy",), "ASSEMBLIES_MOTION_STUDY",
     "Inserts a new motion study.", "New Motion\nStudy"),
)
ASSEMBLY = (
    ("large", "EditComponent", ("EditComponent", "NoExternalReferences")),
    ("large", "InsertComponents", ("InsertComponents", "NewPartInAssembly", "CopyWithMates")),
    ("large", "Mate", None),
    ("large", "ComponentPreview", None),
    ("large", "LinearComponentPattern", ("LinearComponentPattern", "CircularComponentPattern", "PatternDrivenComponentPattern", "SketchComponentPattern",
                                                 "CurveComponentPattern", "ChainComponentPattern", "MirrorComponents")),
    ("large", "SmartFasteners", None),
    ("large", "MoveComponent", ("MoveComponent", "RotateComponent", "FixComponent", "FloatComponent")),
    ("sep",),
    ("large", "ShowHiddenComponents", None),
    ("sep",),
    ("large", "AssemblyFeatures", ("AsmHoleSeries", "AsmHoleWizard", "AsmSimpleHole", "AsmExtrudedCut", "AsmRevolvedCut", "AsmSweptCut", "AsmFillet", "AsmChamfer", "AsmWeldBead", "AsmBeltChain")),
    ("large", "ReferenceGeometry", None),
    ("sep",),
    ("large", "NewMotionStudy", None),
    ("sep",),
    ("large", "BillOfMaterials", None),
    ("sep",),
    ("large", "ExplodedView", ("ExplodedView", "ExplodeLineSketch", "ExplodeCollapse")),
    ("sep",),
    ("large", "Instant3D", None),
    ("sep",),
    ("large", "UpdateSpeedPak", None),
    ("sep",),
    ("large", "TakeSnapshot", None),
    ("large", "LargeAssemblySettings", ("LargeAssemblyMode", "LargeNoAutoRecover", "LargeNoRebuildSwitch", "LargeHideRefs",
                                                 "LargeNoEdges", "LargeNoPreview", "LargeNoVerify", "LargeOptimize", "LargeSuspend")),
)
TAB = "Assembly"
_part_tabs = None
_showing = "part"


def extend_catalog():
    from . import catalog
    for key, label, natives, family, tip, caption in ASSEMBLY_BUTTONS:
        cmd = catalog.BY_KEY.get(key)
        if cmd is None:
            catalog.BY_KEY[key] = catalog.c(key, label, natives, family, tip, caption=caption)
            continue
        # A key the catalog already has (say "Mate" on FreeCAD's joint tool) must still open

        ours = tuple(n for n in natives if n.startswith("SWStyle_"))
        if ours:
            cmd.icon = cmd.icon or family
            cmd.natives = ours + tuple(n for n in cmd.natives if n not in ours)
    from . import asmevaluate
    for key, label, native, family, tip, caption in asmevaluate.CATALOG:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (native,), family, tip, caption=caption)
    if "AsmDefeature" not in catalog.BY_KEY:
        catalog.BY_KEY["AsmDefeature"] = catalog.c(
            "AsmDefeature", "Defeature", ("SWStyle_AsmDefeature",), None,
            "Makes a simplified part from the assembly: details removed, or each component's silhouette.")
    from . import asmlarge
    if "LargeAssemblySettings" not in catalog.BY_KEY:
        catalog.BY_KEY["LargeAssemblySettings"] = catalog.c(
            "LargeAssemblySettings", "Large Assembly Settings", (), "ASSEMBLIES_LARGE_ASSEMBLY_MODE",
            "Large Assembly Mode and the settings it turns on.", call="menu", caption="Large Assembly\nSettings")
    from . import asmfeature
    if "AssemblyFeatures" not in catalog.BY_KEY:
        catalog.BY_KEY["AssemblyFeatures"] = catalog.c(
            "AssemblyFeatures", "Assembly Features", (), "FEATURES_EXTRUDE_CUT",
            "Cuts made in the assembly: the parts are not changed.", call="menu", caption="Assembly\nFeatures")
    for key, label, native, family, tip in asmfeature.CATALOG:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (native,), family, tip)
    for key, label, native, tip in asmlarge.CATALOG:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (native,), None, tip)
    # The part tabs' big Assembly button switched to FreeCAD's own Assembly workbench, whose

    wb = catalog.BY_KEY.get("WB_Assembly")
    if wb is not None:
        wb.natives = ("SWStyle_NewAssembly",)
        wb.call = None
        wb.tip = "Makes an assembly and starts Begin Assembly."
    catalog.ALL = tuple(catalog._ALL)


def assembly_tabs(part_tabs):
    ""
    by_title = dict(part_tabs)
    tabs = [(TAB, ASSEMBLY)]
    from . import asmevaluate
    by_title["Evaluate"] = asmevaluate.EVALUATE
    for title in ("Sketch", "Evaluate", "Add-Ins"):
        if title in by_title:
            tabs.append((title, by_title[title]))
    return tuple(tabs)


def _shell():
    try:
        from . import shell
        sh = shell.shell()
        return sh if sh is not None and getattr(sh, "enabled", False) else None
    except Exception as _fw_err:
        _fw_log("asmui.py:421", _fw_err)
        return None


def _drawing():
    """A drawing is active: its document holds a TechDraw page."""
    doc = App.ActiveDocument
    try:
        return doc is not None and any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects)
    except Exception as _fw_err:
        _fw_log("asmui.py:431", _fw_err)
        return False


def _review():
    """Large Design Review from saved graphics: the assembly's window, with no assembly loaded in it."""
    try:
        from . import asmreview
        return asmreview.is_review(App.ActiveDocument)
    except Exception:
        return False


def update_tabs(force=False):
    """The assembly tabs while an assembly is active, the part tabs otherwise."""
    global _part_tabs, _showing
    from . import catalog
    sh = _shell()
    if sh is None or not alive(getattr(sh, "topbar", None)):
        return
    from . import asmtools
    want = "edit" if asmtools.editing() else ("assembly" if _assembly() is not None or _review() else
                                               ("drawing" if _drawing() else "part"))
    if want == "drawing" and not hasattr(catalog, "drawing_tabs"):
        want = "part"           # no drawing tabs in this catalog: the part tabs
    _part_tabs = catalog.TABS
    if want == _showing and not force:
        return
    _showing = want
    try:
        from . import swtoolbars          # customtabs-1119: the toolbars shown for this document type
        swtoolbars.apply_kind(sh)
    except Exception as _fw_err:
        _fw_log("asmui.py:toolbars-kind", _fw_err)
    if want == "assembly":
        catalog.TABS = assembly_tabs(_part_tabs)
    elif want == "edit":
        catalog.TABS = ((TAB, ASSEMBLY),) + tuple(t for t in _part_tabs if t[0] != TAB)
    elif want == "drawing":    # a drawing: Drawing, Sketch, Evaluate, Add-Ins (the interface's catalog)
        catalog.TABS = catalog.drawing_tabs(_part_tabs)
    try:
        sh._build_pages()
        sh.topbar.select(TAB if want == "assembly" else "Drawing" if want == "drawing" else "Features")
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: assembly tabs: %s\n" % error)
    finally:
        catalog.TABS = _part_tabs      # other modules add their tabs to the part list


# ============================================================================= tree and status
def _tree():
    sh = _shell()
    pane = getattr(sh, "left_pane", None) if sh is not None else None
    try:
        return pane.tree_widget() if pane is not None and alive(pane) else None
    except Exception as _fw_err:
        _fw_log("asmui.py:473", _fw_err)
        return None


def _rows(model, parent=QtCore.QModelIndex(), depth=0):
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        yield index
        if depth < 6 and model.rowCount(index):         # nested subassemblies' mates sit deep
            yield from _rows(model, index, depth + 1)


def plain(text):
    """The label behind a row's text: without "(f) ", "(-) " or a mate's "(A,B)"."""
    if not text:
        return text or ""
    for mark in (ac.FIXED_PREFIX, ac.FLOAT_PREFIX, ac.OVER_PREFIX):
        if text.startswith(mark):
            text = text[len(mark):]
    return text


def tree_names():
    ""
    p = paths.params()
    return p.GetBool("TreeConfigNames", True), p.GetBool("TreeDisplayStateNames", True)


def component_suffix(comp, show=None):
    ""

    cfg_on, state_on = show or tree_names()
    if not cfg_on and not state_on:
        return ""
    try:
        from . import asmmenu
        cfg = asmmenu.config_names(comp)[1] or "Default"
    except Exception:
        cfg = "Default"

    return (" (%s)" % cfg if cfg_on else "") + (" <<%s>_Display State 1>" % cfg if state_on else "")


def top_text(asm, show=None):
    """The assembly's top row: the document's name (it follows Save As), its configuration and
    display state: "Assem1 (Default) <Display State-1>"."""
    doc = asm.Document
    cfg_on, state_on = show or tree_names()
    text = doc.Label
    cfg = "Default"
    try:
        from . import configmanager
        t = configmanager.table(doc)
        if t is not None:
            cfg = t.active() or cfg
    except Exception as _fw_err:
        _fw_log("asmui.py:502", _fw_err)
    out = text + (" (%s)" % cfg if cfg_on else "")
    if state_on:
        state = None
        try:
            from . import asmdisplay
            state = asmdisplay.state_of(doc, cfg)
        except Exception as _fw_err:
            _fw_log("asmui.py:510", _fw_err)
        out += " <%s>" % (state or "Display State-1")
    return out


def wanted_texts(asm):
    """{label: text the row should show} for the components, the mates and the Mates folder."""
    out = {}
    state = ac.defined(asm)
    over = ac.over_defined(asm)
    for comp in ac.components(asm):
        out[comp.Label] = ac.prefix(asm, comp, state, over) + comp.Label
    for joint in ac.mates(asm):
        out[joint.Label] = ac.mate_text(joint)
    for comp in ac.components(asm):
        if not ac.is_subassembly(comp):
            continue
        # a flexible subassembly's rows: its components by their own names, its mates folder "Mates"
        kids = list(getattr(comp, "Group", []) or [])
        kids += [o for o in getattr(comp, "OutList", []) or [] if o.TypeId == "App::Origin" and o not in kids]
        for o in kids:
            if o.TypeId == "Assembly::JointGroup":
                out[o.Label] = "Mates"
                for j in getattr(o, "Group", []) or []:
                    if ac.mate_type(j):
                        out[j.Label] = _sub_mate_text(j)
            elif o.TypeId in ("App::Link", "Assembly::AssemblyLink"):
                out[o.Label] = _sub_prefix(comp, o) + ac.source_label(o)
            elif o.TypeId == "App::Origin":

                out[o.Label] = "Origin"
                for f in getattr(o, "OriginFeatures", None) or []:
                    name = ORIGIN_ROLE_NAMES.get(getattr(f, "Role", ""))
                    if name and f.Label != name:
                        out[f.Label] = name
    try:
        from . import asmextref
        docs = {}
        for comp in ac.components(asm):
            body = asmextref._body_of(comp)
            if body is not None:
                docs[body.Document.Name] = body.Document
        for d in docs.values():
            for label, text in asmextref.marks(d).items():
                out.setdefault(label, text)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: external reference marks: %s\n" % error)
    return out


EDIT_BLUE = "#0a64d8"
ORIGIN_ROLE_NAMES = {"XZ_Plane": "Front Plane", "XY_Plane": "Top Plane", "YZ_Plane": "Right Plane",
                     "X_Axis": "X-axis", "Y_Axis": "Y-axis", "Z_Axis": "Z-axis", "Origin": "Origin"}


def _sub_mate_text(joint):
    names = []
    for prop in ("Reference1", "Reference2"):
        ref = getattr(joint, prop, None)
        if ref and ref[0] is not None:
            names.append(ac.source_label(ref[0]))
    base = joint.Label.split(" (")[0]
    return "%s (%s)" % (base, ",".join(names)) if names else base


def _sub_prefix(comp, obj):
    """(f) / (-) / (+) as the component stands in its own subassembly."""
    try:
        sub = comp.LinkedObject
        own = getattr(obj, "LinkedObject", None)
        if own in ac.components(sub):
            return ac.prefix(sub, own, ac.defined(sub), ac.over_defined(sub))
    except Exception as _fw_err:
        _fw_log("asmui.py:583", _fw_err)
    return ""


_applying = False


SHOWN = {}       # row text -> the text drawn (configuration and display state added), for _NameDelegate
PLAIN_INK = set()
                    # is suppressed (a hidden component shows by its icon; Origin is never grey)
GREY_INK = set()    # suppressed components: grey whatever FreeCAD's own status colour says


from . import treerowlook as _treerowlook


class _NameDelegate(_treerowlook.RowDelegate):
    ""



    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        try:
            text = option.text
            fg = index.data(Qt.ForegroundRole)
            blue = fg is not None and hasattr(fg, "color") and fg.color().name().lower() == QtGui.QColor(EDIT_BLUE).name()
            if (text in PLAIN_INK or text in GREY_INK) and not blue:      # in-context edit stays blue
                view = self.parent()
                pal = view.palette() if view is not None else option.palette
                ink = pal.color(QtGui.QPalette.Disabled, QtGui.QPalette.Text) if text in GREY_INK \
                    else pal.color(QtGui.QPalette.Text)
                option.palette.setColor(QtGui.QPalette.Text, ink)
            if text in SHOWN:
                option.text = SHOWN[text]
        except Exception as _fw_err:
            _fw_log("asmui.py:616", _fw_err)


def _shown_texts(asm, want):
    out = {}
    show = tree_names()
    try:
        from . import asmextref     # "Part1<1> ->": a component whose part references another
        marks = {c.Label: asmextref.component_mark(c) for c in ac.components(asm)}
    except Exception as error:
        App.Console.PrintLog("FreeCAD: component reference marks: %s\n" % error)
        marks = {}
    for comp in ac.components(asm):
        text = want.get(comp.Label)
        mark = marks.get(comp.Label)
        if text and (show[0] or show[1] or mark):
            out[text] = text + (" " + mark if mark else "") + component_suffix(comp, show)
    out[asm.Label] = top_text(asm, show)
    return out


def apply_tree():
    global _applying
    tree = _tree()
    asm = _assembly()
    if tree is None or asm is None:
        return 0
    model = tree.model()
    want = wanted_texts(asm)
    try:
        SHOWN.clear()
        SHOWN.update(_shown_texts(asm, want))
        from . import asmcomp
        PLAIN_INK.clear()
        GREY_INK.clear()
        for c in ac.components(asm):
            (GREY_INK if asmcomp.is_suppressed(c) else PLAIN_INK).add(want.get(c.Label))
        PLAIN_INK.add("Origin")
        for view in [tree] + Gui.getMainWindow().findChildren(QtWidgets.QAbstractItemView, "SWFeatureTree"):
            if not isinstance(view.itemDelegateForColumn(0), _NameDelegate):
                view.setItemDelegateForColumn(0, _NameDelegate(view))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: tree names: %s\n" % error)
    by_text = {}
    for label, text in list(want.items()):
        by_text[plain(text)] = text
    for label, text in want.items():
        by_text[label] = text           # a row's own label wins over another row's bare name
    for text in want.values():
        by_text[text] = text            # a row already showing its text keeps it
    errors = {ac.mate_text(j) for j in ac.mates(asm) if ac.mate_error(j)}
    from . import asmrefopts
    missing = {ac.mate_text(j) for j in ac.mates(asm) if asmrefopts.missing_reference(j)}
    missing_colour = asmrefopts.missing_colour()
    from . import asmtools
    ed = asmtools.editing()
    edited = want.get(ed[1].Label) if ed and ed[0] is asm else None     # Edit Part: its row blue
    comp_texts = {want.get(c.Label) for c in ac.components(asm)}
    n = 0
    _applying = True
    try:
        for index in _rows(model):
            text = index.data(Qt.DisplayRole)
            if not text:
                continue
            target = by_text.get(text) or by_text.get(plain(text))
            if target is not None and text != target:
                model.setData(index, target, Qt.DisplayRole)
                n += 1
            if target is not None and target in comp_texts:
                blue = target == edited
                has = index.data(Qt.ForegroundRole)
                # pkg314: by colour, not presence: FreeCAD greys the edited part's row itself, so a
                # brush was already there and the blue never went on
                is_blue = has is not None and hasattr(has, "color") and has.color().name() == EDIT_BLUE
                if blue and not is_blue:
                    model.setData(index, QtGui.QBrush(QtGui.QColor(EDIT_BLUE)), Qt.ForegroundRole)
                elif not blue and is_blue:
                    model.setData(index, None, Qt.ForegroundRole)
                if blue and index.data(Qt.BackgroundRole) is not None:

                    model.setData(index, None, Qt.BackgroundRole)
            if target is not None and target in want.values() and " (" in target:

                # a missing face: yellow warning, or red with Messages > Treat missing mate references as errors
                colour = "#e03030" if target in errors else (missing_colour if target in missing else None)
                has = index.data(Qt.ForegroundRole)
                has = has.color().name() if has is not None and hasattr(has, "color") else None
                if has != colour:
                    model.setData(index, QtGui.QBrush(QtGui.QColor(colour)) if colour else None, Qt.ForegroundRole)
    finally:
        _applying = False
    return n


class _Status:
    def __init__(self):
        self.label = None
        self.timer = None

    def show(self, asm):
        mw = Gui.getMainWindow()
        bar = mw.statusBar()
        if self.label is None or not alive(self.label):
            self.label = QtWidgets.QLabel()
            self.label.setObjectName("FW_AssemblyStatus")
            bar.addPermanentWidget(self.label)

            for w in list(bar.findChildren(QtWidgets.QWidget)):
                if type(w).__name__ in ("UnitsButton", "RebuildIndicator") and w.parent() is not None:
                    shown = w.isVisibleTo(bar)
                    bar.removeWidget(w)
                    bar.addPermanentWidget(w)
                    w.setVisible(shown)
            try:

                # "Under Defined  Editing Assembly" goes right after 'Editing Part', before the units
                from . import simplifiedui
                order = tuple(simplifiedui.ORDER)
                if "FW_AssemblyStatus" not in order:
                    i = order.index("SWStatusInfo") + 1 if "SWStatusInfo" in order else 0
                    simplifiedui.ORDER = order[:i] + ("FW_AssemblyStatus",) + order[i:]
                simplifiedui.order()
            except Exception as _fw_err:
                _fw_log("asmui.py:725", _fw_err)
        if asm is None:
            self.label.hide()
            return
        state = ac.assembly_state(asm)
        self.label.setText(state)       # "Editing Assembly" follows it (the status bar's own label)
        self.label.setStyleSheet("color: #e03030;" if state == "Over Defined" else "")
        self._follow()
        if self.timer is None or not alive(self.timer):

            # label then reads "Under Defined  Editing Sketch1"), the assembly's otherwise
            self.timer = QtCore.QTimer(self.label)
            self.timer.setInterval(400)
            self.timer.timeout.connect(self._follow)
            self.timer.start()

    def _follow(self):
        try:
            if self.label is None or not alive(self.label):
                return
            if _assembly() is None:
                self.label.hide()
                return
            self.label.setVisible(not _sketch_in_edit())
        except Exception as _fw_err:
            _fw_log("asmui.py:_Status._follow", _fw_err)


def _sketch_in_edit():
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        obj = getattr(edit, "Object", None) if edit is not None else None
        return obj is not None and obj.TypeId in ("Sketcher::SketchObject", "Part::Part2DObjectPython") \
            or (obj is not None and "Sketch" in obj.TypeId)
    except Exception:
        return False


_status = _Status()


def refresh():
    asm = _assembly()
    if asm is not None:
        try:
            from . import asmfmoptions
            asmfmoptions.attach_tree()      # Enable preview of hidden components: the tree's hover
        except Exception as _fw_err:
            _fw_log("asmui.py:745", _fw_err)
        try:
            from . import asmlight          # a lightweight component expanded in the tree resolves
            asmlight.attach_expand([_tree()] + Gui.getMainWindow().findChildren(QtWidgets.QTreeView, "SWFeatureTree"))
        except Exception as _fw_err:
            _fw_log("asmui.py:750", _fw_err)
    update_tabs()
    try:
        if asm is not None:
            ac.quiet_all(asm)
            from . import asmcomp
            asmcomp.reapply_displays(asm)
        apply_tree()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly tree: %s\n" % error)
    try:
        _status.show(asm)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly status: %s\n" % error)


_TREE_HELD = []


def _tree_hold(on):
    ""


    try:
        if on:
            if _TREE_HELD:
                return
            views = [v for v in Gui.getMainWindow().findChildren(QtWidgets.QAbstractItemView, "SWFeatureTree") if v.isVisible()]
            for v in views:
                v.viewport().setUpdatesEnabled(False)
                _TREE_HELD.append(v)
            if views:
                QtCore.QTimer.singleShot(1000, _tree_watch)
        else:
            while _TREE_HELD:
                v = _TREE_HELD.pop()
                try:
                    v.viewport().setUpdatesEnabled(True)
                    v.viewport().update()
                except RuntimeError:
                    pass        # the tree was deleted meanwhile
    except Exception as _fw_err:
        _fw_log("asmui.py:tree hold", _fw_err)


def _tree_watch():
    """A drag whose release was never seen (the window lost the pointer): the tree is drawn again."""
    if not _TREE_HELD:
        return
    if QtWidgets.QApplication.mouseButtons() & Qt.LeftButton:
        QtCore.QTimer.singleShot(1000, _tree_watch)
    else:
        _tree_hold(False)


class _DragStart(QtCore.QObject):
    ""





    def __init__(self):
        super().__init__()
        self.press = None
        self.sending = False

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t == QtCore.QEvent.KeyPress and _smart.get("first") is not None:
            try:
                if event.key() == Qt.Key_Tab:

                    _smart["flip"] = not _smart.get("flip", False)
                    Gui.getMainWindow().statusBar().showMessage(
                        "SmartMates: %s" % ("Aligned" if _smart["flip"] else "Anti-Aligned"), 3000)
                    return True
            except Exception as _fw_err:
                _fw_log("asmui.py:791", _fw_err)
            return False
        if self.sending or t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                                     QtCore.QEvent.MouseButtonRelease):
            return False
        try:
            if not obj.inherits("QOpenGLWidget"):
                return False
            if t == QtCore.QEvent.MouseButtonPress:
                self.press = None
                try:
                    from . import asmisland
                    if asmisland.STATE["active"]:
                        asmisland.end(now=True)     # a drag whose release was never seen
                except Exception as _fw_err:
                    _fw_log("asmui.py:806", _fw_err)
                _smart["first"] = None
                _smart["flip"] = False
                _smart_cursor(None)
                if event.button() == Qt.LeftButton and _dragging_assembly() and event.modifiers() & Qt.AltModifier:
                    asm = ac.assembly_of(App.ActiveDocument)
                    if asm is not None:
                        _smart["first"] = smart_ref_at(asm, obj, event.position())
                        if _smart["first"] is not None:
                            _smart["start"] = App.Placement(_smart["first"][0].Placement)
                if event.button() == Qt.LeftButton and _dragging_assembly():
                    self.press = (QtCore.QPointF(event.position()), QtCore.QPointF(event.globalPosition()),
                                  event.modifiers())
                    asm = ac.assembly_of(App.ActiveDocument)
                    if asm is not None:
                        ac.rezero(asm)      # screws start from where they are now
                        _dragged["comp"] = _pressed(asm, obj, event)
                        if _dragged["comp"] is not None:
                            _tree_hold(True)    # the tree is not drawn again at every step of the drag
            elif t == QtCore.QEvent.MouseButtonRelease:
                self.press = None
                if event.button() == Qt.LeftButton and _dragging_assembly():
                    _symmetric_now()        # pkg304: before FreeCAD's last solve of the drag (same Undo step)
                    _patterns_now()         # pkg305: pattern instances with their seed, in the drag's Undo step
                if _TREE_HELD:
                    QtCore.QTimer.singleShot(0, lambda: _tree_hold(False))
                try:
                    from . import asmisland
                    if asmisland.STATE["active"]:
                        QtCore.QTimer.singleShot(0, asmisland.end)     # after FreeCAD ends its drag
                except Exception as _fw_err:
                    _fw_log("asmui.py:830", _fw_err)
                _smart_cursor(None)
                if event.button() == Qt.LeftButton and _smart.get("first") is not None:
                    first, _smart["first"] = _smart["first"], None
                    flip = _smart.pop("flip", False)
                    pos = QtCore.QPointF(event.position())
                    QtCore.QTimer.singleShot(0, lambda: smart_drop(first, obj, pos, flip=flip))
                elif event.button() == Qt.LeftButton and _dragging_assembly():
                    QtCore.QTimer.singleShot(0, _path_after_drag)   # after the drag ends: ranges, screws
                    QtCore.QTimer.singleShot(0, _symmetric_after_drag)      # pkg304
                    QtCore.QTimer.singleShot(0, _patterns_now)      # pkg305
            elif t == QtCore.QEvent.MouseMove and _smart.get("first") is not None \
                    and (event.buttons() & Qt.LeftButton):
                _smart_hover(obj, QtCore.QPointF(event.position()))
            elif t == QtCore.QEvent.MouseMove and (event.buttons() & Qt.LeftButton) and self.press is None \
                    and _dragging_assembly():
                QtCore.QTimer.singleShot(0, _path_after_drag)       # couplers follow the drag live
                _symmetric_now()        # pkg304: the Symmetric distance follows the first entity live
                QtCore.QTimer.singleShot(0, _patterns_now)      # pkg305: instances follow their seed live
            elif self.press is not None:
                local, glob, mods = self.press
                self.press = None
                if (event.position() - local).manhattanLength() > 0.5:
                    if _smart.get("first") is None:
                        try:
                            from . import asmisland     # the drag solves only what it can move
                            asmisland.begin(ac.assembly_of(App.ActiveDocument), _dragged.get("comp"))
                        except Exception as error:
                            App.Console.PrintLog("FreeCAD: drag island: %s\n" % error)
                    self.sending = True
                    try:
                        QtWidgets.QApplication.sendEvent(obj, QtGui.QMouseEvent(
                            QtCore.QEvent.MouseMove, local, glob, Qt.NoButton, Qt.LeftButton, mods))
                    finally:
                        self.sending = False
        except Exception as error:
            self.press = None
            App.Console.PrintLog("FreeCAD: assembly drag start: %s\n" % error)
        return False


_dragged = {}
_smart = {"first": None}


def _refs_at(asm, widget, pos):
    """(component, element) for each assembly element under the point, nearest first."""
    out = []
    try:
        view = Gui.ActiveDocument.ActiveView
        dpr = widget.devicePixelRatioF()
        pt = (int(pos.x() * dpr), int((widget.height() - pos.y()) * dpr))
        infos = view.getObjectsInfo(pt) or []
    except Exception:
        infos = []
    for info in infos:
        try:
            root = info.get("ParentObject") or App.getDocument(info["Document"]).getObject(info["Object"])
            ref = ac.reference(asm, root, info.get("SubName", "") or info.get("Component", ""))
        except Exception:
            ref = None
        if ref is not None and ref[1]:
            out.append(ref)
    return out


def smart_ref_at(asm, widget, pos):
    refs = _refs_at(asm, widget, pos)
    return refs[0] if refs else None


def smart_kind(first, target):
    """The SmartMate an Alt-drag would make on target: "Peg-in-Hole", or the mate's type."""
    from . import asmpm
    s1, s2 = ac.element(*first), ac.element(*target)
    if s1 is None or s2 is None:
        return None
    if asmpm.peg_faces(first, target, s1, s2) is not None:
        return "Peg-in-Hole"
    try:
        return ac.first_choice(s1, s2)
    except Exception:
        return "Coincident"


_CURSOR = {"kind": None, "at": 0.0}


def _smart_cursor(kind):
    ""

    app = QtWidgets.QApplication
    if kind == _CURSOR["kind"]:
        return
    if _CURSOR["kind"] is not None:
        app.restoreOverrideCursor()
    _CURSOR["kind"] = kind
    if kind is None:
        return
    try:
        from . import asmpm
        icon = asmpm.mate_icon("Concentric" if kind == "Peg-in-Hole" else kind)
        from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
        pm = _hidpi.canvas(40, 40)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        try:
            p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 1))
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawPolygon(QtGui.QPolygon([QtCore.QPoint(0, 0), QtCore.QPoint(0, 16), QtCore.QPoint(4, 12),
                                          QtCore.QPoint(7, 18), QtCore.QPoint(9, 17), QtCore.QPoint(6, 11),
                                          QtCore.QPoint(11, 11)]))
            if icon is not None and not icon.isNull():
                p.drawPixmap(16, 16, icon.pixmap(22, 22))
        finally:
            p.end()
        app.setOverrideCursor(QtGui.QCursor(pm, 0, 0))
    except Exception as error:
        _CURSOR["kind"] = None
        App.Console.PrintLog("FreeCAD: SmartMates pointer: %s\n" % error)


def _smart_hover(widget, pos):
    """Alt-drag over the model: the pointer shows the mate the drop would make (checked at
    most every 80 ms, what is under the pointer takes a pick)."""
    import time
    now = time.time()
    if now - _CURSOR["at"] < 0.08:
        return
    _CURSOR["at"] = now
    first = _smart.get("first")
    try:
        asm = ac.assembly_of(first[0].Document)
        target = next((r for r in _refs_at(asm, widget, pos) if r[0] is not first[0]), None) if asm else None
        kind = smart_kind(first, target) if target is not None else None
    except Exception:
        kind = None
    _smart["hover"] = kind
    _smart_cursor(kind)


def smart_drop(first, widget, pos, refs=None, flip=False):
    """Alt-drag released: the first entity under the drop that is on another component gets the
    SmartMate (the dragged component goes back to where the drag began, then to the mate)."""
    asm = ac.assembly_of(first[0].Document)
    if asm is None:
        return None
    if refs is None:
        refs = _refs_at(asm, widget, pos)
    target = next((r for r in refs if r[0] is not first[0]), None)
    start = _smart.pop("start", None)
    if target is None:
        return None
    if start is not None:
        first[0].Placement = start
    from . import asmpm
    joint = asmpm.smart_mate(asm, first, target)
    if joint is not None and flip:
        # Tab pressed during the drag: the other alignment (a peg-in-hole flips its Coincident)
        doc = asm.Document
        doc.openTransaction("Flip Mate Alignment")
        try:
            asmpm.flip_smart(asm, joint)
        finally:
            doc.commitTransaction()
        doc.recompute()
    refresh()
    if joint is not None:
        try:
            show_smart_popup(asm, joint, first, target, start)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: SmartMates pop-up: %s\n" % error)
    return joint


class _SmartPopup:
    ""


    def __init__(self, asm, joint, first, target, start):
        self.asm, self.joint, self.first, self.target, self.start = asm, joint, first, target, start
        self.anti = QtWidgets.QCheckBox()
        self.kind = ac.mate_type(joint)
        self.popup = None
        # the pop-up's Distance / Angle value box edits these (the Mate PM's own boxes are not up)
        self.distance = QtWidgets.QDoubleSpinBox()
        self.distance.setRange(0.0, 1.0e6)
        self.distance.setDecimals(2)
        self.distance.setSuffix("mm")
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setRange(0.0, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix("deg")
        self._sync_value()
        self.distance.valueChanged.connect(lambda v: self._typed("Distance", v))
        self.angle.valueChanged.connect(lambda v: self._typed("Angle", v))

    def _sync_value(self):
        j = self.joint
        for box, kind, prop in ((self.distance, "Distance", "Distance"), (self.angle, "Angle", "Angle")):
            if self.kind == kind:
                v = getattr(j, prop, 0.0)
                box.blockSignals(True)
                box.setValue(abs(float(getattr(v, "Value", v))))
                box.blockSignals(False)

    def _typed(self, kind, value):
        if self.kind != kind:
            return
        import UtilsAssembly
        doc = self.asm.Document
        doc.openTransaction("SmartMates")
        try:
            before = UtilsAssembly.saveAssemblyPartsPlacements(self.asm)
            turns = {c.Name: App.Rotation(c.Placement.Rotation) for c in ac.components(self.asm)}

            def turned():
                return any(not c.Placement.Rotation.isSame(turns[c.Name], 1e-6)
                           for c in ac.components(self.asm) if c.Name in turns)
            ac.change_mate(self.asm, self.joint, kind, value)
            if kind == "Distance" and value and turned():

                # keeps its orientation and goes to the other side, so try the other sign
                UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, before)
                ac.change_mate(self.asm, self.joint, kind, -value)
                if turned():
                    UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, before)
                    ac.change_mate(self.asm, self.joint, kind, value)
        finally:
            doc.commitTransaction()
        doc.recompute()
        refresh()

    def choose(self, kind):
        from . import asmquickmates as qm
        s1, s2 = ac.element(*self.first), ac.element(*self.target)
        doc = self.asm.Document
        doc.openTransaction("SmartMates")
        try:
            ac.change_mate(self.asm, self.joint, kind, qm.current_value(kind, s1, s2))
        finally:
            doc.commitTransaction()
        doc.recompute()
        self.kind = kind
        self._sync_value()
        if self.popup is not None:
            self.popup.mark(kind)
        refresh()

    def flip_alignment(self):
        doc = self.asm.Document
        doc.openTransaction("Flip Mate Alignment")
        try:
            from . import asmpm
            asmpm.flip_smart(self.asm, self.joint)
        finally:
            doc.commitTransaction()
        doc.recompute()
        self.anti.setChecked(not self.anti.isChecked())
        refresh()

    def drop(self):
        """Undo: the mate goes and the component back where the drag began."""
        doc = self.asm.Document
        doc.openTransaction("Undo SmartMates")
        try:
            from . import asmpm
            partner = asmpm.peg_partner(self.asm, self.joint)
            if partner is not None:
                asmpm.PEG.pop(self.joint.Name, None)
                doc.removeObject(partner.Name)
            if doc.getObject(self.joint.Name) is not None:
                doc.removeObject(self.joint.Name)
            if self.start is not None:
                self.first[0].Placement = self.start
        finally:
            doc.commitTransaction()
        doc.recompute()
        self.close()
        refresh()

    def keep(self):
        self.close()

    def close(self):
        if self.popup is not None:
            try:
                self.popup.hide()
                self.popup.deleteLater()
            except RuntimeError as _fw_err:
                _fw_log("asmui.py:1117", _fw_err)
            self.popup = None
        SMART_POPUP.pop("open", None)


SMART_POPUP = {}


def show_smart_popup(asm, joint, first, target, start=None):
    from . import asmpm, asmquickmates as qm
    try:
        from . import paths
        if not paths.params().GetBool(asmpm.POPUP_PARAM, True):
            return None             # the Mate PM's Show popup dialog off: none after SmartMates either
    except Exception as _fw_err:
        _fw_log("asmui.py:1132", _fw_err)
    old = SMART_POPUP.get("open")
    if old is not None:
        old.close()
    s1, s2 = ac.element(*first), ac.element(*target)
    kinds = qm.kinds(s1, s2, (first, target)) or [ac.mate_type(joint)]
    adapter = _SmartPopup(asm, joint, first, target, start)
    adapter.popup = asmpm.MatePopup(adapter, kinds, adapter.kind)
    adapter.popup.move(QtGui.QCursor.pos() + QtCore.QPoint(18, 18))
    adapter.popup.show()
    SMART_POPUP["open"] = adapter
    return adapter


def _pressed(asm, widget, event):
    """The component under the press (it drives the couplers while dragged)."""
    try:
        view = Gui.ActiveDocument.ActiveView
        dpr = widget.devicePixelRatioF()
        pos = event.position()
        info = view.getObjectInfo((int(pos.x() * dpr), int((widget.height() - pos.y()) * dpr)))
        names = (info or {}).get("SubName", "") or ""
        comps = {c.Name: c for c in ac.components(asm)}
        for part in names.split("."):
            if part in comps:
                return comps[part]
    except Exception as _fw_err:
        _fw_log("asmui.py:1159", _fw_err)
    return None


def _symmetric_now():
    ""

    try:
        asm = ac.assembly_of(App.ActiveDocument)
        if asm is not None and any(getattr(j, ac.MATE_PROP, "") == "Symmetric" for j in ac.mates(asm)):
            ac.sync_symmetric(asm)
            return asm
    except Exception as error:
        App.Console.PrintLog("FreeCAD: symmetric drag: %s\n" % error)
    return None


def _patterns_now():
    ""

    try:
        from . import asmcpattern
        asm = ac.assembly_of(App.ActiveDocument)
        if asm is not None and asmcpattern.patterns(asm):
            asmcpattern.follow(asm)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: pattern drag: %s\n" % error)


def _symmetric_after_drag():
    """After the drag: a Symmetric mate the drag's own solve left off is solved again."""
    try:
        asm = _symmetric_now()
        if asm is not None and not all(ac.symmetric_holds(j) for j in ac.mates(asm)
                                       if getattr(j, ac.MATE_PROP, "") == "Symmetric"
                                       and not getattr(j, "Suppressed", False)):
            ac.solve(asm)
            asm.Document.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: symmetric after drag: %s\n" % error)


def _path_after_drag():
    """Path Mate: FreeCAD dragged the component off the path; it slides back on.
    Linear/Linear Coupler: the dragged component's travel moves the other."""
    try:
        from . import asmpath, asmcoupler
        asm = ac.assembly_of(App.ActiveDocument)
        if asm is None:
            return
        moved = bool(asmpath.path_mates(asm)) and asmpath.place(asm)
        moved = (bool(asmcoupler.couplers(asm)) and asmcoupler.couple(asm, _dragged.get("comp"))) or moved
        from . import asmcam
        moved = (bool(asmcam.cams(asm)) and asmcam.follow(asm)) or moved
        moved = ac.width_free_clamp(asm) or moved
        moved = ac.slot_free_clamp(asm) or moved      # pkg304: a Free slot stops the pin at its ends
        moved = ac.range_clamp(asm) or moved      # a Distance range dragged past its end comes back
        for joint in ac.mates(asm):
            if ac.mate_type(joint) == "Screw":
                ac._screw_store(joint)          # FreeCAD coupled the screw in the drag itself
        if moved:
            asm.Document.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: path mate after drag: %s\n" % error)


def _dragging_assembly():
    """An assembly is the edited object and lets components be dragged."""
    gdoc = Gui.ActiveDocument
    vp = gdoc.getInEdit() if gdoc is not None else None
    if vp is None or "Assembly" not in type(vp).__name__:
        return False
    asm = ac.assembly_of(gdoc.Document)
    return asm is not None and bool(getattr(asm.ViewObject, "EnableMovement", False))


_drag_start = None


class _Observer:
    def __init__(self):
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.setInterval(SOON)
        self.timer.timeout.connect(self._due)

    def _due(self):
        """A drag in the graphics area moves the component at every pointer step: the tree's
        names and marks are worked out once the button comes up, not 7 times a second during
        the drag (a 300-component tree took a third of each drag step)."""
        try:
            if QtWidgets.QApplication.mouseButtons() != Qt.NoButton:
                self.timer.start()
                return
        except Exception as _fw_err:
            _fw_log("asmui.py:_due", _fw_err)
        refresh()

    def soon(self, *args):
        if not _applying:
            self.timer.start()

    def slotCreatedObject(self, obj):
        self.soon()

    def slotDeletedObject(self, obj):
        self.soon()

    def slotChangedObject(self, obj, prop):
        if prop in ("Label", "Placement", "Reference1", "Reference2", "JointType", "ObjectToGround", "Group"):
            self.soon()

    def slotRecomputedDocument(self, doc):
        self.soon()

    def slotActivateDocument(self, doc):
        self.soon()


class _GuiObserver:
    def __init__(self, owner):
        self.owner = owner

    def slotActivateDocument(self, doc):
        self.owner.soon()


_observer = None


# ============================================================================= tree layout
def assembly_layout(model, doc):
    ""

    from . import fmtree
    asm = ac.assembly_of(doc)
    if asm is None:
        return False
    src = model.src
    tops = [src.index(r, 0, QtCore.QModelIndex()) for r in range(src.rowCount(QtCore.QModelIndex()))]
    doc_index = next((i for i in tops if plain(i.data(Qt.DisplayRole)) == doc.Label), None)
    if doc_index is None:
        return False
    kids = model._children(doc_index)
    asm_index = next((i for i in kids if fmtree._object(doc, i.data(Qt.DisplayRole)) is asm), None)
    if asm_index is None:
        return False

    part = model.part = model.root.add(fmtree.Node(src=QtCore.QPersistentModelIndex(asm_index), obj=asm))
    model.by_id.setdefault(asm_index.internalId(), []).append(part)
    for name, _draw, tip in fmtree.VIRTUAL:
        part.add(fmtree.Node(text=name, icon=model.icons[name], tip=tip))
    rows = [(i, fmtree._object(doc, plain(i.data(Qt.DisplayRole)))) for i in model._children(asm_index)]

    from . import asmbom
    tables = [(i, o) for i, o in rows if asmbom.is_bom(o)]
    if tables:
        folder = part.add(fmtree.Node(text="Tables", icon=QtGui.QIcon(":/icons/Spreadsheet.svg"),
                                      tip="The assembly's tables"))
        for i, o in tables:
            model._mirror(folder, i, doc, deep=False)
        rows = [(i, o) for i, o in rows if not asmbom.is_bom(o)]
    origin = next(((i, o) for i, o in rows if o is not None and o.TypeId == fmtree.ORIGIN), None)
    if origin is not None:
        roles = {f.Name: getattr(f, "Role", "") for f in getattr(origin[1], "OriginFeatures", None) or []}
        okids = [(i, fmtree._object(doc, i.data(Qt.DisplayRole))) for i in model._children(origin[0])]
        planes = {roles.get(o.Name): i for i, o in okids if o is not None and roles.get(o.Name) in fmtree.PLANES}
        for role in fmtree.PLANES:
            if role in planes:
                model._mirror(part, planes[role], doc)
        node = model._mirror(part, origin[0], doc, deep=False)
        for i, o in okids:
            # as in a part: the origin point is the Origin row itself, not listed again under it
            if o is None or roles.get(o.Name) not in fmtree.PLANES + ("Origin",):
                model._mirror(node, i, doc)
    mates_rows, feature_rows = [], []
    from . import asmfeature, asmfolder, asmcpattern
    in_folders = {m.Name for f in asmfolder.component_folders(asm) for m in asmfolder.component_members(f)}
    for i, o in rows:
        if origin is not None and o is origin[1]:
            continue
        if o is not None and asmfolder.is_component_folder(o):
            asmfolder.lay_out_components(model, part, [(i, o)] + [(j, p) for j, p in rows if p is not None
                                                                   and p.Name in in_folders], doc)
            continue
        if o is not None and o.Name in in_folders:
            continue                    # under its folder
        if o is not None and o.TypeId == "Assembly::JointGroup":
            mates_rows.append(i)
            continue
        if asmfeature.is_feature(o) or asmcpattern.is_pattern(o):
            feature_rows.append(i)
            continue
        if o is not None and ac.is_subassembly(o):
            lay_out_subassembly(model, part, i, doc, o)
            continue
        model._mirror(part, i, doc)
    for i in mates_rows:
        node = model._mirror(part, i, doc, deep=False)
        asmfolder.lay_out(model, node, i, doc)      # mate folders with their mates under them
    for i in feature_rows:
        model._mirror(part, i, doc)
    try:
        _component_mates(model, part, doc, asm, mates_rows)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Mates in folders: %s\n" % error)
    return True


def _has_rows(comp):
    """The component's part shows rows of its own under it (a Body's features), once opened."""
    try:
        target = comp.getLinkedObject(True)
        vo = getattr(target, "ViewObject", None)
        return bool(vo.claimChildren()) if vo is not None else bool(target.OutList)
    except Exception:
        return True


def _component_mates(model, part, doc, asm, mates_rows):
    ""

    from . import fmtree
    by_name, todo = {}, list(mates_rows)
    while todo:
        i = todo.pop()
        for k in model._children(i):
            o = fmtree._object(doc, plain(k.data(Qt.DisplayRole)))
            if o is None:
                continue
            if ac.mate_type(o) and hasattr(o, "Reference1"):
                by_name[o.Name] = k
            elif o.isDerivedFrom("App::DocumentObjectGroup"):
                todo.append(k)
    if not by_name:
        return
    joints = [j for j in ac.mates(asm) if j.Name in by_name]
    comps = {c.Name for c in ac.components(asm)}
    held = {}       # component name -> its mates, in mate order (one pass, not one per component)
    for j in joints:
        for n in {getattr(j.Reference1[0], "Name", None), getattr(j.Reference2[0], "Name", None)}:
            held.setdefault(n, []).append(j)
    icon = model.icons.get("Mates") if hasattr(model, "icons") and isinstance(model.icons, dict) else None
    if icon is None:
        try:
            icon = row_icon(ac.joint_group(asm)) or ac.joint_group(asm).ViewObject.Icon
        except Exception:
            icon = QtGui.QIcon()
    title = "Mates in %s" % (asm.Document.Label or asm.Label)
    walk = list(part.children)
    while walk:
        node = walk.pop()
        o = node.obj
        if o is None or o.Name not in comps:
            if node.src is not None and o is not None and o.isDerivedFrom("App::DocumentObjectGroup") \
                    and not ac.mate_type(o) and o.TypeId != "Assembly::JointGroup":
                walk.extend(node.children)      # component folders
            continue
        mine = held.get(o.Name, [])
        if not mine or (not node.children and _has_rows(o)):
            continue        # an unopened component: FreeCAD fills its rows when it is opened, then this runs again
        folder = fmtree.Node(text=title, icon=icon, tip="The mates that hold %s" % o.Label)
        folder.parent = node
        node.children.insert(0, folder)
        for r, child in enumerate(node.children):
            child.row = r
        for j in mine:
            model._mirror(folder, by_name[j.Name], doc, deep=False)




SUB_ORIGIN_NAMES = {"XZ_Plane": "Front Plane", "XY_Plane": "Top Plane", "YZ_Plane": "Right Plane"}


def lay_out_subassembly(model, parent, index, doc, comp):
    ""


    from . import fmtree
    node = model._mirror(parent, index, doc, deep=False)
    rows = [(i, fmtree._object(doc, plain(i.data(Qt.DisplayRole)))) for i in model._children(index)]
    origin = next(((i, o) for i, o in rows if o is not None and o.TypeId == fmtree.ORIGIN), None)
    if origin is not None:
        roles = {f.Name: getattr(f, "Role", "") for f in getattr(origin[1], "OriginFeatures", None) or []}
        okids = [(i, fmtree._object(doc, i.data(Qt.DisplayRole))) for i in model._children(origin[0])]
        planes = {roles.get(o.Name): i for i, o in okids if o is not None and roles.get(o.Name) in fmtree.PLANES}
        for role in fmtree.PLANES:
            if role in planes:
                model._mirror(node, planes[role], doc, deep=False).text = SUB_ORIGIN_NAMES[role]
        model._mirror(node, origin[0], doc, deep=False).text = "Origin"
    mates = []
    for i, o in rows:
        if origin is not None and o is origin[1]:
            continue
        if o is not None and o.TypeId == "Assembly::JointGroup":
            mates.append(i)
            continue
        if o is not None and ac.mate_type(o):
            continue                            # a mate shown outside its folder: it is under Mates
        if o is not None and ac.is_subassembly(o):
            lay_out_subassembly(model, node, i, doc, o)
            continue
        model._mirror(node, i, doc)
    for i in mates:
        model._mirror(node, i, doc)
    if not mates:
        _rigid_mates(node, comp)
    return node


def _rigid_mates(node, comp):
    ""
    from . import fmtree
    try:
        sub = comp.LinkedObject
        group = next((o for o in sub.Group if o.TypeId == "Assembly::JointGroup"), None)
        joints = [j for j in ac.mates(sub)]
    except Exception:
        return None
    if group is None:
        return None

    def icon(o):
        own = row_icon(o)
        if own is not None:
            return own
        try:
            return o.ViewObject.Icon
        except Exception:
            return QtGui.QIcon()
    folder = node.add(fmtree.Node(text="Mates", icon=icon(group),
                                  tip="The mates of %s (edit them in the subassembly)" % comp.Label))
    for j in joints:
        folder.add(fmtree.Node(text=ac.mate_text(j), icon=icon(j), tip="A mate of %s" % sub.Document.Label))
    return folder


_FLEX_ICONS = {}


def flexible_icon(base):
    ""

    if not isinstance(base, QtGui.QIcon) or base.isNull():
        return base
    key = base.cacheKey()
    if key in _FLEX_ICONS:
        return _FLEX_ICONS[key]
    icon = QtGui.QIcon()
    for size in (16, 24, 32):
        src = base.pixmap(size, size)
        if src.isNull():
            continue
        pm = QtGui.QPixmap(size, size)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.drawPixmap(QtCore.QRect(0, 0, size, size), src)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = size * 0.5
        rect = QtCore.QRectF(size - r - 0.5, size - r - 0.5, r, r)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(255, 255, 255, 230))
        p.drawEllipse(rect)
        pen = QtGui.QPen(QtGui.QColor("#1f6fd1"), max(1.2, size / 14.0))
        pen.setCapStyle(QtCore.Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        inner = rect.adjusted(r * 0.22, r * 0.22, -r * 0.22, -r * 0.22)
        p.drawArc(inner, 30 * 16, 120 * 16)         # the bend
        p.drawArc(inner, 210 * 16, 120 * 16)
        p.end()
        icon.addPixmap(pm)
    _FLEX_ICONS[key] = icon
    return icon


_HOLLOW_ICONS = {}


def _hidden_component(obj):
    try:
        if obj.TypeId not in ("App::Link", "Assembly::AssemblyLink") or getattr(obj, "ElementCount", 0):
            return False
        return obj.ViewObject is not None and not obj.ViewObject.Visibility
    except Exception:
        return False


def hollow_icon(base):
    ""

    if not isinstance(base, QtGui.QIcon) or base.isNull():
        return base
    key = base.cacheKey()
    if key in _HOLLOW_ICONS:
        return _HOLLOW_ICONS[key]
    icon = QtGui.QIcon()
    for size in (16, 24, 32):
        img = base.pixmap(size, size).toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
        if img.isNull():
            continue
        w, h = img.width(), img.height()
        alpha = [[QtGui.qAlpha(img.pixel(x, y)) for x in range(w)] for y in range(h)]
        out = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
        out.fill(QtCore.Qt.transparent)
        line, fill = QtGui.QColor(70, 70, 70).rgba(), QtGui.QColor(255, 255, 255).rgba()
        for y in range(h):
            for x in range(w):
                if alpha[y][x] < 96:
                    continue
                edge = any(not (0 <= x + dx < w and 0 <= y + dy < h) or alpha[y + dy][x + dx] < 96
                           for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                c = QtGui.QColor(img.pixel(x, y))
                dark = c.lightnessF() < 0.35            # the picture's own strokes stay
                out.setPixel(x, y, line if edge or dark else fill)
        icon.addPixmap(QtGui.QPixmap.fromImage(out))
    _HOLLOW_ICONS[key] = icon
    return icon


def _patch_fmtree():
    from . import fmtree
    if getattr(fmtree.Model, "_fw_assembly", False):
        return
    original = fmtree.Model._build

    def _build(self):
        doc = App.ActiveDocument
        if doc is not None and ac.assembly_of(doc) is not None:
            self.root, self.by_id, self.part, self.flat = fmtree.Node(), {}, None, None
            self.doc = doc
            try:
                if assembly_layout(self, doc):
                    return
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: assembly tree layout: %s\n" % error)
        original(self)

    fmtree.Model._build = _build
    fmtree.Model._fw_assembly = True
    data0 = fmtree.Model.data

    def data(self, index, role=Qt.DisplayRole):
        # a mirrored row given its own text (a subassembly's "Top Plane") shows that text
        if role == Qt.DisplayRole and index.isValid():
            node = self.node(index)
            if node is not None and node.src is not None and node.text:
                return node.text
        if role == Qt.DecorationRole and index.isValid():
            node = self.node(index)
            obj = getattr(node, "obj", None) if node is not None else None
            try:
                flexible = obj is not None and ac.is_flexible(obj)
            except ReferenceError:      # its document is closing
                flexible = False
            own = row_icon(obj) if obj is not None and node is not self.part else None
            if flexible:
                own = flexible_icon(own or data0(self, index, role))
            if own is not None and _hidden_component(obj):
                return hollow_icon(own)
            if own is not None:
                return own
        return data0(self, index, role)
    fmtree.Model.data = _qt_safe(data)
    # rows that show "(f) Plate<1>" still name their component
    from . import sketchstatus
    for mark in (ac.FIXED_PREFIX,):
        if mark not in sketchstatus.PREFIXES:
            sketchstatus.PREFIXES = tuple(sketchstatus.PREFIXES) + (mark,)


def row_icon(obj):
    ""

    try:
        from . import icons
        if ac.assembly_of(obj.Document) is None:
            return None             # a part document's rows keep their pictures
        t = obj.TypeId
        if t == "Assembly::JointGroup":
            key = "TreeMates"
        elif t in ("App::Link", "Assembly::AssemblyLink"):
            if getattr(obj, "ElementCount", 0):
                return None         # a link array: FreeCAD's own picture
            key = "TreeSubassembly" if ac.is_subassembly(obj) else "TreeComponent"
        else:
            kind = ac.mate_type(obj)
            if not kind:
                return None
            from . import asmpm
            return asmpm.drawn_mate_icon(kind)
        icon = icons.drawn(key)
        return icon if icons.paints(icon) else None
    except Exception:
        return None


def _isometric():
    try:
        Gui.activeView().viewIsometric()
    except Exception as _fw_err:
        _fw_log("asmui.py:1461", _fw_err)


def _patch_newdoc():
    from . import newdoc
    if getattr(newdoc, "_fw_assembly", False):
        return
    original = newdoc.make

    def make(kind):
        if kind != "Assembly":
            return original(kind)
        name = newdoc._next_name("Assem")
        doc = App.newDocument(name)
        doc.Label = name
        asm = None
        try:
            asm = newdoc.apply_template(doc, newdoc.assembly_template())   # Options > Default Templates
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: assembly template: %s\n" % error)
        if asm is None:
            new_assembly(doc)
        else:
            try:
                Gui.activateWorkbench("AssemblyWorkbench")
            except Exception as _fw_err:
                _fw_log("asmui.py:1487", _fw_err)
            activate(asm)
            refresh()
            from . import asmpm
            if paths.params().GetBool(asmpm.START_PARAM, True):
                QtCore.QTimer.singleShot(300, lambda: start_insert(begin=True))
        try:
            if hasattr(newdoc, "apply_up_axis"):
                newdoc.apply_up_axis(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: up axis: %s\n" % error)
        QtCore.QTimer.singleShot(200, _isometric)
        return doc

    newdoc.make = make
    newdoc._fw_assembly = True


def _patch_joint_edit():
    """A mate's double-click (and Edit Feature) opens the Mate PropertyManager on it, not
    FreeCAD's joint panel."""
    import JointObject
    cls = JointObject.ViewProviderJoint
    if getattr(cls, "_fw_mate", False):
        return
    original = cls.doubleClicked

    def doubleClicked(self, vobj):
        joint = vobj.Object
        if not getattr(joint, ac.MATE_PROP, ""):
            return original(self, vobj)
        return edit_mate(joint)

    cls.doubleClicked = doubleClicked
    cls._fw_mate = True



JOINT_MATES = {0: "Lock", 2: "Concentric", 3: "Concentric", 5: "Coincident", 6: "Parallel",
               7: "Perpendicular", 8: "Angle"}


def _patch_joint_create():
    ""


    import CommandCreateJoint
    import JointObject
    if getattr(CommandCreateJoint, "_fw_mate", False):
        return
    original = CommandCreateJoint.activateJoint

    def activateJoint(index):
        asm = _assembly()
        if asm is not None and index in JOINT_MATES and not Gui.Control.activeDialog():
            from . import asmpm
            panel = asmpm.MatePanel(asm)
            Gui.Control.showDialog(panel)
            try:
                panel.choose(JOINT_MATES[index])
            except Exception as _fw_err:
                _fw_log("asmui.py:1548", _fw_err)
            return
        return original(index)

    CommandCreateJoint.activateJoint = activateJoint
    CommandCreateJoint._fw_mate = True
    task = JointObject.TaskAssemblyCreateJoint
    isolate = task.updateIsolation

    def updateIsolation(self, *args):
        try:
            self.jForm.isolateType.blockSignals(True)
            self.jForm.isolateType.setCurrentIndex(3)
            self.jForm.isolateType.blockSignals(False)
        except Exception as _fw_err:
            _fw_log("asmui.py:1563", _fw_err)
        return isolate(self)

    task.updateIsolation = updateIsolation


def edit_mate(joint):
    from . import asmpm
    asm = ac.assembly_of(joint.Document)
    if asm is None:
        return False
    try:
        App.closeActiveTransaction(True)
    except Exception as _fw_err:
        _fw_log("asmui.py:1577", _fw_err)
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    activate(asm)
    Gui.Control.showDialog(asmpm.MatePanel(asm, joint))
    return True


def _patch_shell():
    # FreeCAD's own Assembly toolbars get no extra tab: the Assembly tab here stands for them
    from . import shell
    if "AssemblyWorkbench" not in shell.NATIVE_COVERED:
        shell.NATIVE_COVERED = tuple(shell.NATIVE_COVERED) + ("AssemblyWorkbench",)


def register():
    global _observer
    try:
        from . import selguard          # selection observers left behind by a closed document
        selguard.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: selection guard: %s\n" % error)
    try:
        from . import asmnewcfg         # Hide / Suppress new components, Suppress new mates per configuration
        asmnewcfg.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: new components in configurations: %s\n" % error)
    try:
        from . import asmexplcfg        # exploded views under their configuration (ConfigurationManager)
        asmexplcfg.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: exploded views in the ConfigurationManager: %s\n" % error)
    from . import asmtools
    have = set(Gui.listCommands())
    from . import asmexplode, asmpattern, asmpreview, asmsnap, asmcopy, asmfeature
    for name, cls in COMMANDS + asmtools.COMMANDS + asmexplode.COMMANDS + asmpattern.COMMANDS + asmpreview.COMMANDS + asmsnap.COMMANDS + asmcopy.COMMANDS + asmfeature.COMMANDS:
        if name not in have:
            Gui.addCommand(name, cls())
    from . import asmlarge, asmspeedpak, asmmotion, asmevaluate
    asmevaluate.register()
    asmlarge.register()
    asmspeedpak.register()
    asmmotion.register()
    from . import asmdefeature
    asmdefeature.register()
    from . import dwxpress
    dwxpress.register()          # Tools > Xpress Products > DriveWorksXpress
    from . import taskscheduler
    taskscheduler.register()     # Tools > Applications > Task Scheduler
    from . import floxpress
    floxpress.register()         # Tools > Xpress Products > FloXpress
    from . import asmbom
    asmbom.register()
    from . import asmnewpart
    asmnewpart.register()
    from . import asmisolate
    asmisolate.install()
    from . import asmoptions
    asmoptions.install_display_rows()
    asmoptions.install()        # Options > Assemblies rows that act on save and open
    from . import asmfmoptions
    asmfmoptions.install()
    from . import asmrefopts
    asmrefopts.install()        # System Options' assembly rows (External References, Colors, Messages, Toolbox)
    from . import asminsert
    asminsert.install_bom_filter()
    try:
        from . import configs
        configs.install()
        from . import asmconfigure
        asmconfigure.install()
        from . import asmdisplay
        asmdisplay.install()
        from . import asmpackgo
        asmpackgo.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: configurations: %s\n" % error)     # Envelope components left out of the bill of materials
    asminsert.patch_massprops()        # and out of mass properties
    try:
        from . import asmenvelope
        asmenvelope.install()          # envelope Advanced Select, drawing BOMs
    except Exception as error:
        App.Console.PrintLog("FreeCAD: envelope: %s\n" % error)
    try:
        from . import asmdrawing
        asmdrawing.install()           # assembly drawing views: configuration, display state, exploded
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly drawings: %s\n" % error)
    try:
        from . import asmrestructure
        asmrestructure.install()       # drag and drop in the tree: reorder, into / out of subassemblies
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly structure editing: %s\n" % error)
    extend_catalog()
    for patch in (_patch_fmtree, _patch_newdoc, _patch_shell, _patch_menus):
        try:
            patch()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: assemblies: %s\n" % error)
    try:
        from . import asmhealth
        asmhealth.install()            # missing files, circular references, mate error marks, View Mates
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly problems: %s\n" % error)
    try:
        from . import asmcfginst
        asmcfginst.install()           # a configuration per instance stays shown after a rebuild or reopen
    except Exception as error:
        App.Console.PrintLog("FreeCAD: instance configurations: %s\n" % error)
    try:
        from . import asmgen
        asmgen.install()               # tree answers kept till the document changes; no tree paints mid-rebuild
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly change count: %s\n" % error)
    try:
        from . import asmloadprogress
        asmloadprogress.install()
        from . import asmautorepair
        asmautorepair.install()        # Auto Repair on a component pattern whose pick is gone
    except Exception as error:
        App.Console.PrintLog("FreeCAD: open progress: %s\n" % error)
    try:
        from . import asmincontext
        asmincontext.install()         # Join, Cavity... take other components while a part is edited in context
    except Exception as error:
        App.Console.PrintLog("FreeCAD: in-context picks: %s\n" % error)
    _patch_later()
    global _drag_start
    if _drag_start is None:
        _drag_start = _DragStart()
        _app_filter("asm.dragstart", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease,
                                       QtCore.QEvent.KeyPress), _drag_start)
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
        try:
            Gui.addDocumentObserver(_GuiObserver(_observer))
        except Exception as _fw_err:
            _fw_log("asmui.py:1715", _fw_err)


def _patch_menus():
    from . import asmmenu, asmmenubar
    asmmenu.install()
    from . import asmquickmates
    asmquickmates.install()      # Quick Mates on two picks (after asmmenu's component toolbar)
    asmmenubar.install()
    from . import asmrollback
    asmrollback.install()       # the rollback bar in an assembly
    from . import asmexplines
    asmexplines.install()       # explode lines show while exploded; Smart Explode Lines
    from . import asmexplode
    asmexplode.install()        # exploded views kept through rebuild, save and reopen
    from . import asmpublisher
    asmpublisher.install()      # Configuration Publisher panel on insert and on select
    try:
        from . import asmldr
        asmldr.install()        # File > Open Mode, Large Design Review
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Large Design Review: %s\n" % error)
    try:
        from . import asmlight
        asmlight.install()      # lightweight feather, Set Lightweight to Resolved, Performance rows
        from . import asmspconfig
        asmspconfig.install()   # SpeedPak per configuration (ConfigurationManager, Referenced configuration)
        from . import asmctrlcopy
        asmctrlcopy.install()   # Ctrl+drag copies a component; tree drag into the view adds one
        from . import asmappearance
        asmappearance.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: lightweight: %s\n" % error)
    try:
        from . import asmstudytabs
        asmstudytabs.install()  # Model / Motion Study tabs under the graphics area
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: motion study tabs: %s\n" % error)


def _patch_later():
    """JointObject loads with FreeCAD's Assembly workbench, which may come after start-up."""
    try:
        import JointObject  # noqa: F401
    except Exception:
        QtCore.QTimer.singleShot(2000, _patch_later)
        return
    try:
        _patch_joint_edit()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: mate editing: %s\n" % error)
    try:
        from . import asmexplode
        asmexplode.patch_view_provider()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: exploded view editing: %s\n" % error)
    try:
        _patch_joint_create()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: mate commands: %s\n" % error)
