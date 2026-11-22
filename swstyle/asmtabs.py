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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import asmcore as ac

PREFS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/CommandManager"
DEFAULT_HIDDEN = ("Sketch Ink", "Render Tools", "Electrical", "Piping", "Tubing", "User Defined Route")
FC_TITLE = "FreeCAD Assembly"
ORDER = ("Assembly", "Layout", "Sketch", "Sketch Ink", "Markup", "Evaluate", "Render Tools", "Add-Ins",
         "Electrical", "Piping", "Tubing", "User Defined Route", "MBD", FC_TITLE)
SEP = ("sep",)


def L(key, fly=None):
    return ("large", key, fly)


def ST(*keys):
    return ("stack", tuple((k, None) for k in keys))


# --------------------------------------------------------------------- commands for "fw:" entries
# key, label, fw entry, tip, caption
FW_BUTTONS = (
    ("NewAssemblyInAssembly", "New Assembly", "new_assembly", "Makes a new subassembly in the assembly.", None),
    ("AsmRefCS", "Coordinate System", "ref_cs", "A coordinate system in the assembly.", None),
    ("AsmRefPoint", "Point", "ref_point", "A reference point in the assembly.", None),
    ("AsmMateReference", "Mate Reference", "mate_reference", "Entities a component mates with when it is inserted.", None),
    ("AsmGroundPlane", "Ground Plane", "ground_plane", "The floor components rest on.", None),
    ("AsmDesignCheck", "Check Active Document", "dc:check", "Runs the Design Checker standard on this document.",
     "Design\nChecker"),
    ("AsmDesignCheckFile", "Check Against Existing File", "dc:against", "Checks against the checks of another file.", None),
    ("AsmDesignBuild", "Build Checks", "dc:build", "Builds a Design Checker standard.", None),
    ("AsmDesignLearn", "Learn Checks Wizard", "dc:learn", "Learns checks from a reference document.", None),
    ("PipeStart", "Start at Point", "route_start:Pipe", "Starts a pipe route at a connection point.", "Start at\nPoint"),
    ("PipeAuto", "Auto Route", "route_auto:Pipe", "Draws the pipe route between connection points.", "Auto\nRoute"),
    ("TubeStart", "Start at Point", "route_start:Tube", "Starts a tube route at a connection point.", "Start at\nPoint"),
    ("TubeAuto", "Auto Route", "route_auto:Tube", "Draws the tube route between connection points.", "Auto\nRoute"),
    ("ElecStart", "Start at Point", "route_start:Electrical", "Starts a cable route at a connector's connection point.",
     "Start at\nPoint"),
    ("ElecAuto", "Auto Route", "route_auto:Electrical", "Draws the cable route between connectors, through clips.",
     "Auto\nRoute"),
    ("UserStart", "Start at Point", "route_start:User", "Starts a user defined route at a connection point.",
     "Start at\nPoint"),
    ("UserAuto", "Auto Route", "route_auto:User", "Draws the user defined route between connection points.",
     "Auto\nRoute"),
    ("PipeFitting", "Add Fitting", "fitting:Piping", "Adds an elbow, tee, reducer, flange... from the routing library.",
     "Add\nFitting"),
    ("TubeFitting", "Add Fitting", "fitting:Tubing", "Adds a tube union from the routing library.", "Add\nFitting"),
    ("InsertConnector", "Insert Connector", "fitting:Electrical", "Adds a connector or a clip from the routing library.",
     "Insert\nConnector"),
    ("EditWires", "Edit Wires", "elec:wires", "The wires the picked (or last) cable carries.", "Edit\nWires"),
    ("ImportFromTo", "Import From-To List", "elec:fromto", "Makes the cables of a From-To list (CSV).",
     "Import\nFrom-To"),
    ("FlattenRoute", "Flatten Route", "elec:flatten", "Lays the picked (or last) cable out flat with its lengths.",
     "Flatten\nRoute"),
    ("WireList", "Wire List", "elec:report", "Saves the harness's wire list with cut lengths.", None),
    ("WireLibrary", "Cable/Wire Library Wizard", "elec:library", "The wire specs routes use.", "Wire\nLibrary"),
    ("EditRoute", "Edit Route", "route_edit", "Edits the picked (or last) route.", "Edit\nRoute"),
    ("CreateConnectionPoint", "Create Connection Point", "route_cpoint", "A connection point on a round edge.",
     "Connection\nPoint"),
)
# key, label, function name in this module, tip, caption
OWN_BUTTONS = (
    ("Layout", "Layout", "toggle_layout", "Makes or edits the assembly's layout sketch.", None),
    ("MakePartFromBlock", "Make Part from Block", "start_make_part", "Makes a part from a block of the layout.",
     "Make Part\nfrom Block"),
)


def _fw(entry, label):
    from . import asmmenubar
    try:
        return asmmenubar.item(entry, label)
    except Exception as _fw_err:
        _fw_log("asmtabs.py:103", _fw_err)
        return None


class _FwCmd:
    def __init__(self, entry, label, tip):
        self.entry, self.label, self.tip = entry, label, tip

    def GetResources(self):
        return {"MenuText": self.label, "ToolTip": self.tip}

    def IsActive(self):
        it = _fw(self.entry, self.label)
        return bool(it is not None and it.enabled)

    def Activated(self):
        it = _fw(self.entry, self.label)
        if it is not None and it.enabled:
            it.run()


class _OwnCmd:
    def __init__(self, func, label, tip):
        self.func, self.label, self.tip = func, label, tip

    def GetResources(self):
        return {"MenuText": self.label, "ToolTip": self.tip}

    def IsActive(self):
        return bool(globals()["can_" + self.func]())

    def Activated(self):
        globals()[self.func]()


def command_name(key):
    return "SWStyle_Asm_" + key


def register():
    watch()                     # parts made from layout blocks follow their blocks
    from . import catalog
    have = set(Gui.listCommands())
    for key, label, entry, tip, caption in FW_BUTTONS:
        name = command_name(key)
        if name not in have:
            Gui.addCommand(name, _FwCmd(entry, label, tip))
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (name,), None, tip, caption=caption)
    for key, label, func, tip, caption in OWN_BUTTONS:
        name = command_name(key)
        if name not in have:
            Gui.addCommand(name, _OwnCmd(func, label, tip))
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (name,), None, tip, caption=caption)
    for key, menu in (("AsmRefGeometry", "Reference Geometry"), ("AsmDesignChecker", "Design Checker")):
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, menu, (), None, menu, call="menu", caption=menu.replace(" ", "\n", 1))
    try:
        from . import asmfpattern
        for row in asmfpattern.CATALOG:
            if row[0] not in catalog.BY_KEY:
                catalog.BY_KEY[row[0]] = catalog.c(row[0], row[1], (row[2],), row[3], row[4] if len(row) > 4 else None)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly feature patterns: %s\n" % error)
    try:
        _register_freecad()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: FreeCAD Assembly tab: %s\n" % error)
    catalog.ALL = tuple(catalog._ALL)


# --------------------------------------------------------------------- FreeCAD's own Assembly commands
# The extra "FreeCAD Assembly" tab: every stock Assembly workbench command, so a FreeCAD user keeps them

FC_ASSEMBLY = (
    ("FCA_Solve", "Solve Assembly", "Assembly_SolveAssembly", "FreeCAD's solver on the active assembly.", "Solve\nAssembly"),
    ("FCA_Activate", "Activate Assembly", "Assembly_ActivateAssembly", "Makes the picked assembly the active one.",
     "Activate\nAssembly"),
    ("FCA_Insert", "Insert Component", "Assembly_Insert", "FreeCAD's Insert Component panel.", "Insert\nComponent"),
    ("FCA_InsertLink", "Insert Link", "Assembly_InsertLink", "Inserts a part or assembly as a link.", None),
    ("FCA_InsertNewPart", "Insert New Part", "Assembly_InsertNewPart", "Makes a new part in the assembly.", None),
    ("FCA_Grounded", "Toggle Grounded", "Assembly_ToggleGrounded", "Grounds the picked component, or frees it.",
     "Toggle\nGrounded"),
    ("FCA_Fixed", "Fixed Joint", "Assembly_CreateJointFixed", "FreeCAD's Fixed joint.", "Joints"),
    ("FCA_Revolute", "Revolute Joint", "Assembly_CreateJointRevolute", "FreeCAD's Revolute joint.", None),
    ("FCA_Cylindrical", "Cylindrical Joint", "Assembly_CreateJointCylindrical", "FreeCAD's Cylindrical joint.", None),
    ("FCA_Slider", "Slider Joint", "Assembly_CreateJointSlider", "FreeCAD's Slider joint.", None),
    ("FCA_Ball", "Ball Joint", "Assembly_CreateJointBall", "FreeCAD's Ball joint.", None),
    ("FCA_Distance", "Distance Joint", "Assembly_CreateJointDistance", "FreeCAD's Distance joint.", None),
    ("FCA_Parallel", "Parallel Joint", "Assembly_CreateJointParallel", "FreeCAD's Parallel joint.", None),
    ("FCA_Perpendicular", "Perpendicular Joint", "Assembly_CreateJointPerpendicular", "FreeCAD's Perpendicular joint.", None),
    ("FCA_Angle", "Angle Joint", "Assembly_CreateJointAngle", "FreeCAD's Angle joint.", None),
    ("FCA_RackPinion", "Rack and Pinion Joint", "Assembly_CreateJointRackPinion", "FreeCAD's Rack and Pinion joint.",
     "Mechanical\nJoints"),
    ("FCA_Screw", "Screw Joint", "Assembly_CreateJointScrew", "FreeCAD's Screw joint.", None),
    ("FCA_GearBelt", "Gears/Belt Joint", "Assembly_CreateJointGearBelt", "FreeCAD's Gears and Belt joints.", None),
    ("FCA_Gears", "Gears Joint", "Assembly_CreateJointGears", "FreeCAD's Gears joint.", None),
    ("FCA_Belt", "Belt Joint", "Assembly_CreateJointBelt", "FreeCAD's Belt joint.", None),
    ("FCA_View", "Exploded View", "Assembly_CreateView", "FreeCAD's exploded view.", "Exploded\nView"),
    ("FCA_Simulation", "Simulation", "Assembly_CreateSimulation", "FreeCAD's assembly simulation.", None),
    ("FCA_Bom", "Bill of Materials", "Assembly_CreateBom", "FreeCAD's bill of materials spreadsheet.", "Bill of\nMaterials"),
    ("FCA_ExportASMT", "Export ASMT", "Assembly_ExportASMT", "Writes the assembly as an OndselSolver .asmt file.",
     "Export\nASMT"),
    ("FCA_NewAssembly", "New Assembly", "Assembly_CreateAssembly", "FreeCAD's Create Assembly (an assembly in this document).",
     "New\nAssembly"),
)
FC_MODULES = ("CommandCreateAssembly", "CommandInsertLink", "CommandInsertNewPart", "CommandCreateJoint",
              "CommandSolveAssembly", "CommandExportASMT", "CommandCreateView", "CommandCreateBom",
              "CommandCreateSimulation")


def _fca(*keys):
    return tuple("FCA_" + k for k in keys)


FC_TAB = (
    L("FCA_Solve"), L("FCA_Activate"),
    SEP,
    L("FCA_Insert", _fca("Insert", "InsertLink", "InsertNewPart")), L("FCA_Grounded"),
    SEP,
    L("FCA_Fixed", _fca("Fixed", "Revolute", "Cylindrical", "Slider", "Ball", "Distance", "Parallel", "Perpendicular",
                        "Angle")),
    L("FCA_RackPinion", _fca("RackPinion", "Screw", "GearBelt", "Gears", "Belt")),
    ST("FCA_Revolute", "FCA_Cylindrical", "FCA_Slider"), ST("FCA_Ball", "FCA_Distance", "FCA_Angle"),
    SEP,
    L("FCA_View"), L("FCA_Simulation"), L("FCA_Bom"),
    SEP,
    L("FCA_ExportASMT"), L("FCA_NewAssembly"),
)


def load_freecad_commands():
    """FreeCAD registers some Assembly commands only when its workbench starts: import their modules."""
    import importlib
    for mod in FC_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: %s: %s\n" % (mod, error))
    have = set(Gui.listCommands())
    return [row[2] for row in FC_ASSEMBLY if row[2] in have]


def _register_freecad():
    from . import catalog
    have = set(load_freecad_commands())
    for key, label, native, tip, caption in FC_ASSEMBLY:
        if native in have and key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (native,), None, tip, caption=caption)


# --------------------------------------------------------------------- the tabs
def assembly_tab():
    ""
    from . import asmui
    out = []
    for e in asmui.ASSEMBLY:
        if e[0] == "large" and e[1] == "InsertComponents":
            e = L("InsertComponents", ("InsertComponents", "NewPartInAssembly", "NewAssemblyInAssembly", "CopyWithMates"))
        elif e[0] == "large" and e[1] == "AssemblyFeatures":
            e = L("AssemblyFeatures", tuple(e[2] or ()) + ("AsmLinearPattern", "AsmCircularPattern", "AsmMirror",
                                                           "AsmTableDrivenPattern", "AsmSketchDrivenPattern"))
        elif e[0] == "large" and e[1] == "ReferenceGeometry":
            e = L("ReferenceGeometry", ("Plane", "Axis", "AsmRefCS", "AsmRefPoint", "CenterOfMass", "AsmMateReference",
                                        "AsmGroundPlane"))
        out.append(e)
    return tuple(out)


LAYOUT = (
    L("Layout"), L("SmartDimension", None),
    SEP,
    ("grid", (
        (("Line", None), ("CornerRectangle", None), ("Slot", None), ("Circle", None)),
        (("CenterArc", None), ("Polygon", None), ("Spline", None), ("Ellipse", None)),
        (("SketchFillet", None), ("Sketch3DPlane", None), ("Text", None), ("SketchPoint", None)),
    )),
    SEP,
    L("Trim"), L("Convert"), L("Offset"), L("OffsetOnSurface"),
    ST("MirrorEntities", "LinearSketchPattern", "MoveEntities"),
    SEP,
    L("Relations"), L("RepairSketch"),
    SEP,
    L("QuickSnaps"),
    SEP,
    ST("MakeBlock", "EditBlock", "InsertBlock"), ST("AddRemoveBlockEntities", "SaveBlock", "ExplodeBlock"),
    SEP,
    L("MakePartFromBlock"), L("InsertComponents"), L("Mate"), L("MoveComponent"),
    SEP,
    L("ShowHiddenComponents"),
)

EVALUATE = (
    L("DesignStudy"),
    SEP,
    L("Interference"), L("ClearanceVerification"), L("HoleAlignment"), L("MassProperties"),
    ST("Measure", "Markup", "Sensor"), ST("SectionProperties", "AssemblyVisualization", "AssemblyPerformance"),
    SEP,
    ST("Curvature", "SymmetryCheck", "BodyCompare"),
    SEP,
    ("stack", (("CompareDocuments", None), ("AsmDesignChecker", ("AsmDesignCheck", "AsmDesignCheckFile",
                                                                  "AsmDesignBuild", "AsmDesignLearn")))),
    SEP,

    # SustainabilityXpress, On Demand Manufacturing, Previous Release Check (evaltools' commands,
    # on the assembly's whole shape)
    ST("EV_Simulation", "FloXpress", "DriveWorksXpress"), ST("EV_Costing", "EV_Sustainability", "EV_OnDemand"),
    ST("PreviousReleaseCheck"),
)

ELECTRICAL = (
    L("WireLibrary"),
    SEP,
    ST("ElecStart", "ElecAuto", "ImportFromTo"),
    SEP,
    L("EditRoute"),
    SEP,
    ST("EditWires", "InsertConnector", "FlattenRoute"),
    ST("WireList", "CreateConnectionPoint"),
    SEP,
    ST("Line", "Spline"),
)
PIPING = (
    L("PipeStart"), L("PipeAuto"), L("EditRoute"),
    SEP,
    L("PipeFitting"),
    SEP,
    L("CreateConnectionPoint"),
    SEP,
    ST("Line"),
)
TUBING = (
    L("TubeStart"), L("TubeAuto"), L("EditRoute"),
    SEP,
    L("TubeFitting"),
    SEP,
    L("CreateConnectionPoint"),
    SEP,
    ST("Line", "Spline"),
)
USER_ROUTE = (
    L("UserStart"), L("UserAuto"), L("EditRoute"),
    SEP,
    L("CreateConnectionPoint"),
    SEP,
    ST("Line"),
)



# scheme copy/import (they work on a part's own faces), so here they would be greyed for good
PART_ONLY_MBD = ("MBD_GenProfile", "MBD_CopyScheme", "MBD_ImportScheme")


def _without(layout, keys):
    out = []
    for e in layout:
        if e[0] == "large":
            if e[1] in keys:
                continue
            fly = tuple(k for k in (e[2] or ()) if k not in keys) or None
            out.append(("large", e[1], fly))
        elif e[0] == "stack":
            rows = tuple((k, fly) for k, fly in e[1] if k not in keys)
            if rows:
                out.append(("stack", rows))
        elif e[0] == "grid":
            out.append(("grid", tuple(tuple((k, f) for k, f in row if k not in keys) for row in e[1])))
        else:
            out.append(e)
    return tuple(out)


def _fix_keys(layout):
    """Flyout lists with keys this catalog lacks lose them (a dead row is worse than none)."""
    from . import catalog

    def ok(k):
        return k in catalog.BY_KEY

    out = []
    for e in layout:
        if e[0] == "large":
            if not ok(e[1]):
                continue
            fly = tuple(k for k in (e[2] or ()) if ok(k)) or None
            out.append(("large", e[1], fly))
        elif e[0] == "stack":
            rows = tuple((k, tuple(f for f in (fly or ()) if ok(f)) or None) for k, fly in e[1] if ok(k))
            if rows:
                out.append(("stack", rows))
        elif e[0] == "grid":
            out.append(("grid", tuple(tuple((k, f) for k, f in row if ok(k)) for row in e[1])))
        else:
            out.append(e)
    return tuple(out)


def every_tab(part_tabs):
    ""
    from . import cmtabs
    part = dict(part_tabs)
    for t, lay in cmtabs.all_tabs():
        part.setdefault(t, lay)
    tabs = {"Assembly": assembly_tab(), "Layout": LAYOUT, "Evaluate": EVALUATE, "Piping": PIPING, "Tubing": TUBING,
            "Electrical": ELECTRICAL, "User Defined Route": USER_ROUTE, FC_TITLE: FC_TAB}
    for t in ("Sketch", "Sketch Ink", "Markup", "Render Tools", "Add-Ins"):
        if t in part:
            tabs[t] = part[t]
        elif t in cmtabs.TABS:
            tabs[t] = cmtabs.TABS[t]
    mbd = part.get("MBD Dimensions") or cmtabs.TABS.get("MBD Dimensions")
    if mbd:
        tabs["MBD"] = _without(mbd, PART_ONLY_MBD)
    return [(t, _fix_keys(tabs[t])) for t in ORDER if t in tabs]


def hidden():
    p = App.ParamGet(PREFS)
    if not p.GetBool("AsmSaved", False):
        return list(DEFAULT_HIDDEN)
    return [t for t in p.GetString("AsmHiddenTabs", "").split("|") if t]


def set_hidden(titles):
    p = App.ParamGet(PREFS)
    p.SetString("AsmHiddenTabs", "|".join(titles))
    p.SetBool("AsmSaved", True)


def assembly_tabs(part_tabs):
    off = set(hidden())
    tabs = [t for t in every_tab(part_tabs) if t[0] not in off or t[0] == "Assembly"]
    tabs = [t for t in tabs if t[0] != FC_TITLE] + [t for t in tabs if t[0] == FC_TITLE]
    return tuple(tabs)


def _assembly_active():
    try:
        return ac.assembly_of(App.ActiveDocument) is not None
    except Exception as _fw_err:
        _fw_log("asmtabs.py:445", _fw_err)
        return False


def tabs_menu(parent=None):
    """Right-click the tab row > Tabs, in an assembly: the assembly's tabs."""
    from . import catalog
    menu = QtWidgets.QMenu(parent)
    sub = menu.addMenu("Tabs")
    off = set(hidden())
    from . import asmui
    for title, _lay in every_tab(asmui._part_tabs or catalog.TABS):
        act = sub.addAction(title)
        act.setCheckable(True)
        act.setChecked(title not in off)
        act.setEnabled(title != "Assembly")
        act.toggled.connect(lambda on, t=title: toggle(t, on))
    return menu


def toggle(title, on):
    off = [t for t in hidden() if t != title]
    if not on:
        off.append(title)
    set_hidden(off)
    from . import asmui
    asmui.update_tabs(force=True)


def install():
    from . import asmui, cmtabs, asmmenubar
    if getattr(asmui, "_fw_asmtabs", False):
        return
    register()
    asmui.assembly_tabs = assembly_tabs
    old_menu = cmtabs.tabs_menu

    def menu(parent=None):
        return tabs_menu(parent) if _assembly_active() else old_menu(parent)
    cmtabs.tabs_menu = menu
    old_update = asmui.update_tabs

    def update_tabs(force=False):
        if _assembly_active():
            asmmenubar.load_assembly_commands()     # New Part, Bill of Materials work from the tab at once
        return old_update(force)
    asmui.update_tabs = update_tabs
    asmui._fw_asmtabs = True


# --------------------------------------------------------------------- Layout
LAYOUT_PROP = "FwLayout"


def layout_sketch(asm, make=False):
    for o in asm.Group:
        if getattr(o, LAYOUT_PROP, False):
            return o
    if not make:
        return None
    doc = asm.Document
    sk = asm.newObject("Sketcher::SketchObject", "Layout")
    sk.addProperty("App::PropertyBool", LAYOUT_PROP, "FreeCAD", "The assembly's layout sketch")
    setattr(sk, LAYOUT_PROP, True)
    try:
        xy = next(f for f in asm.Origin.OriginFeatures if getattr(f, "Role", "") == "XY_Plane")
        sk.AttachmentSupport = [(xy, "")]
        sk.MapMode = "FlatFace"
    except Exception as _fw_err:
        _fw_log("asmtabs.py:511", _fw_err)
    sk.Label = "Layout"
    doc.recompute()
    return sk


def can_toggle_layout():
    return _assembly_active()


def toggle_layout(asm=None):
    ""
    asm = asm or ac.assembly_of(App.ActiveDocument)
    if asm is None:
        return None
    gdoc = Gui.getDocument(asm.Document.Name)
    sk = layout_sketch(asm)
    editing = gdoc.getInEdit()
    if sk is not None and editing is not None and getattr(editing, "Object", None) == sk:
        gdoc.resetEdit()
        asm.Document.recompute()
        return sk
    if sk is None:
        asm.Document.openTransaction("Layout")
        try:
            sk = layout_sketch(asm, True)
        except BaseException:
            try:
                asm.Document.abortTransaction()
            except Exception:
                pass
            raise
        asm.Document.commitTransaction()
    gdoc.setEdit(sk.Name)
    return sk


# --------------------------------------------------------------------- Make Part from Block
def block_names(sketch):
    from . import blocks
    return [r.get("name") for r in blocks.records(sketch)]


def make_part_from_block(asm, sketch, name, folder=None, constraint="On Block"):
    """A new part (a body with a sketch of the block's entities) put in the assembly where the block is."""
    from . import blocks
    rec = next((r for r in blocks.records(sketch) if r.get("name") == name), None)
    if rec is None:
        return None
    idx = [i for i in blocks.indices(sketch, rec)[0] if i >= 0]
    geos = [sketch.Geometry[i].copy() for i in idx if not sketch.getConstruction(i)]
    if not geos:
        return None
    base = asm.Document.FileName
    folder = folder or (os.path.dirname(base) if base else App.getUserAppDataDir())
    part_name = name.split("-")[0] if "-" in name else name

    # FreeCAD link to another document needs a saved assembly, so the part's body goes in the
    # assembly's own document, hidden, and the component links to it.
    virtual = not base
    doc = asm.Document if virtual else App.newDocument(part_name)
    if not virtual:
        doc.Label = part_name
    body = doc.addObject("PartDesign::Body", "Body")
    if virtual:
        body.Label = "%s^%s" % (part_name, asm.Document.Label)
    sk = body.newObject("Sketcher::SketchObject", "Sketch1")
    try:
        sk.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
        sk.MapMode = "FlatFace"
    except Exception as _fw_err:
        _fw_log("asmtabs.py:575", _fw_err)
    sk.addGeometry(geos)
    sk.addProperty("App::PropertyString", "FwFromBlock", "FreeCAD", "The layout block this part was made from")
    sk.FwFromBlock = "%s|%s|%s" % (asm.Document.Name, sketch.Name, name)
    base = _insertion(sketch, rec)
    doc.recompute()
    if virtual:
        try:
            body.Visibility = False
        except Exception as _fw_err:
            _fw_log("asmtabs.py:585", _fw_err)
    else:
        path = os.path.join(folder, part_name + ".FCStd")
        n = 1
        while os.path.exists(path):
            n += 1
            path = os.path.join(folder, "%s%d.FCStd" % (part_name, n))
        doc.saveAs(path)
    Gui.setActiveDocument(asm.Document.Name)
    App.setActiveDocument(asm.Document.Name)
    comp = ac.insert(asm, body, sketch.getGlobalPlacement())
    _tie(comp, sketch, name, base, constraint, sk, float(rec.get("angle", 0.0)))
    asm.Document.recompute()
    return comp


# --------------------------------------------------------------------- the part follows its block
BLOCK_PROP = "FwBlockTie"       # "layout sketch|block|x0|y0|On Block or Project|part sketch name"


def _insertion(sketch, rec):
    from . import blocks
    _idx, base = blocks.indices(sketch, rec)
    if base is None:
        return App.Vector()
    g = sketch.Geometry[base]
    return App.Vector(g.X, g.Y, 0)


def _tie(comp, sketch, name, base, constraint, part_sketch, angle=0.0):
    ""



    if BLOCK_PROP not in comp.PropertiesList:
        comp.addProperty("App::PropertyString", BLOCK_PROP, "FreeCAD", "The layout block this component follows")
        comp.setEditorMode(BLOCK_PROP, 2)
    setattr(comp, BLOCK_PROP, "|".join([sketch.Name, name, repr(base.x), repr(base.y), constraint, part_sketch.Name,
                                        repr(float(angle))]))


def tie_of(comp):
    raw = getattr(comp, BLOCK_PROP, "") or ""
    bits = raw.split("|")
    if len(bits) not in (6, 7):
        return None
    return {"sketch": bits[0], "block": bits[1], "base": App.Vector(float(bits[2]), float(bits[3]), 0),
            "constraint": bits[4], "part_sketch": bits[5],
            "angle": float(bits[6]) if len(bits) == 7 else None}     # None: a tie made before turning was kept


def _block_move(sketch, rec, t):
    """The block's move since the part was made, in layout sketch coordinates: about its insertion
    point, turned by the change in the block's angle, then moved."""
    base1 = _insertion(sketch, rec)
    turn = 0.0 if t.get("angle") is None else float(rec.get("angle", 0.0)) - t["angle"]
    return (App.Placement(base1, App.Rotation())
            .multiply(App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), turn)))
            .multiply(App.Placement(-t["base"], App.Rotation())))


def _block_geos(sketch, rec):
    from . import blocks
    idx = [i for i in blocks.indices(sketch, rec)[0] if i >= 0]
    return [sketch.Geometry[i].copy() for i in idx if not sketch.getConstruction(i)]


def _same(a, b):
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if type(x) is not type(y):
            return False
        try:
            sx, sy = x.toShape(), y.toShape()
            if sx.BoundBox.DiagonalLength and (sx.BoundBox.Center - sy.BoundBox.Center).Length > 1e-6:
                return False
            if abs(sx.Length - sy.Length) > 1e-6:
                return False
        except Exception:
            return False
    return True


def follow(asm):
    """After the layout changes: each part made from a block follows it. Returns the components moved
    or reshaped."""
    from . import blocks
    done = []
    for comp in ac.components(asm):
        t = tie_of(comp)
        if t is None:
            continue
        sketch = asm.Document.getObject(t["sketch"])
        if sketch is None:
            continue
        rec = next((r for r in blocks.records(sketch) if r.get("name") == t["block"]), None)
        if rec is None:
            continue
        move = _block_move(sketch, rec, t)
        gp = sketch.getGlobalPlacement()
        want = gp.multiply(move)
        if t["constraint"] == "Project":
            # in plane only: the part's own distance off the layout plane stays
            local = gp.inverse().multiply(comp.Placement)
            want = gp.multiply(App.Placement(move.Base + App.Vector(0, 0, local.Base.z), move.Rotation))
        changed = False
        if not comp.Placement.isSame(want, 1e-9):
            comp.Placement = want
            changed = True
        # the part's sketch: the block's entities, back where the part was made
        try:
            psk = comp.LinkedObject.Document.getObject(t["part_sketch"])
        except Exception:
            psk = None
        if psk is not None:
            geos = []
            for g in _block_geos(sketch, rec):
                g.transform(move.inverse().toMatrix())
                geos.append(g)
            if geos and not _same(geos, [g for i, g in enumerate(psk.Geometry) if not psk.getConstruction(i)]):
                psk.deleteAllGeometry()
                psk.addGeometry(geos)
                psk.Document.recompute()
                changed = True
        if changed:
            done.append(comp)
    if done:
        asm.Document.recompute()
    return done


class _LayoutWatch:
    def __init__(self):
        self.busy = False

    def slotRecomputedObject(self, obj):
        try:
            if not getattr(obj, LAYOUT_PROP, False) or self.busy:
                return
            name = obj.Document.Name
        except Exception:
            return
        QtCore.QTimer.singleShot(0, lambda: self._run(name))

    def _run(self, name):
        doc = App.listDocuments().get(name)
        asm = ac.assembly_of(doc) if doc is not None else None
        if asm is None:
            return
        self.busy = True
        try:
            follow(asm)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: parts from blocks: %s\n" % error)
        finally:
            self.busy = False


_WATCH = []


def watch():
    if not _WATCH:
        _WATCH.append(_LayoutWatch())
        App.addDocumentObserver(_WATCH[0])


def _picked_layout_block():
    from . import blocks
    asm = ac.assembly_of(App.ActiveDocument)
    sk = layout_sketch(asm) if asm is not None else None
    if sk is None:
        return None, None, []
    picked = []
    try:
        rec = blocks.picked_block(sk)
        if rec is not None:
            picked.append(rec.get("name"))
    except Exception as _fw_err:
        _fw_log("asmtabs.py:765", _fw_err)
    return asm, sk, picked


def can_start_make_part():
    asm, sk, _p = _picked_layout_block()
    return sk is not None and bool(block_names(sk))


class MakePartPanel:
    """Make Part from Block: Selected Blocks, Block-to-Part Constraint (On Block / Project)."""

    def __init__(self, asm, sketch, picked=()):
        self.asm, self.sketch = asm, sketch
        form = QtWidgets.QWidget()
        form.setObjectName("SWMakePartFromBlock")
        form.setWindowTitle("Make Part From Block")
        form.setProperty("swstyle_pm_title", "Make Part From Block")
        lay = QtWidgets.QVBoxLayout(form)
        box = QtWidgets.QGroupBox("Selected Blocks", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.list = QtWidgets.QListWidget(box)
        self.list.setObjectName("SWMakePartBlocks")
        for n in block_names(sketch):
            it = QtWidgets.QListWidgetItem(n)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if (n in picked or not picked) else QtCore.Qt.Unchecked)
            self.list.addItem(it)
        bl.addWidget(self.list)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Block to Part Constraint", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.on_block = QtWidgets.QRadioButton("On Block", box)
        self.project = QtWidgets.QRadioButton("Project", box)
        self.on_block.setChecked(True)
        self.on_block.setToolTip("The part sits on its block and moves with it")
        self.project.setToolTip("The part follows the block in the layout plane; it can move off the plane")
        bl.addWidget(self.on_block)
        bl.addWidget(self.project)
        lay.addWidget(box)
        lay.addStretch(1)
        self.form = form
        self.made = []

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self, folder=None):
        names = [self.list.item(i).text() for i in range(self.list.count())
                 if self.list.item(i).checkState() == QtCore.Qt.Checked]
        constraint = "Project" if self.project.isChecked() else "On Block"
        Gui.Control.closeDialog()
        for n in names:
            c = make_part_from_block(self.asm, self.sketch, n, folder, constraint)
            if c is not None:
                self.made.append(c)
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


OPEN = []


def start_make_part():
    asm, sk, picked = _picked_layout_block()
    if sk is None:
        return None
    gdoc = Gui.getDocument(asm.Document.Name)
    if gdoc.getInEdit() is not None:
        gdoc.resetEdit()
        asm.Document.recompute()
    if Gui.Control.activeDialog():
        return None
    p = MakePartPanel(asm, sk, picked)
    OPEN[:] = [p]
    Gui.Control.showDialog(p)
    return p
