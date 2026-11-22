# -*- coding: utf-8 -*-
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


import json
import os

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac
from . import swmenus

S = swmenus.S
C = swmenus.C
F = swmenus.F


def W(name):
    """An assembly entry run by this module (see ITEMS)."""
    return "fw:" + name



ROUTING_TOOLS = ("Routing Tools", (("Create Connection Point...", W("route_cpoint")), S,
                                    ("Cable/Wire Library Wizard...", W("elec:library"))))
ROUTING_ASM = ("Routing", (
    ("Electrical", (("Start at Point...", W("route_start:Electrical")), ("Auto Route", W("route_auto:Electrical")), S,
                    ("Insert Connector...", W("fitting:Electrical")), ("Edit Wires...", W("elec:wires")),
                    ("Import From-To List...", W("elec:fromto")), S,
                    ("Flatten Route", W("elec:flatten")), ("Wire List...", W("elec:report")))),
    ("Piping", (("Start at Point...", W("route_start:Pipe")), ("Auto Route", W("route_auto:Pipe")), S,
                ("Add Fitting...", W("fitting:Piping")))),
    ("Tubing", (("Start at Point...", W("route_start:Tube")), ("Auto Route", W("route_auto:Tube")), S,
                ("Add Fitting...", W("fitting:Tubing")))),
    ("User Defined Route", (("Start at Point...", W("route_start:User")), ("Auto Route", W("route_auto:User")))),
    S,
    ("Edit Route", W("route_edit")),
    S,
    ROUTING_TOOLS,
))
ROUTING_PART = ("Routing", (ROUTING_TOOLS,))
PART_FIND_MODIFY = ("Find/Modify", (
    ("Find and Replace Annotation...", W("find_replace")), ("Find/Modify Features...", "FindModify"),
    ("Simplify...", W("simplify")),
))
DESIGN_CHECKER = ("Design Checker", (
    ("Check Active Document", W("dc:check")), ("Check Against Existing File...", W("dc:against")),
    ("Build Checks", W("dc:build")), ("Learn Checks Wizard", W("dc:learn")),
))


DISPLAY_SCOPES = (("Current Display State", "cur"), ("All Display States", "all"),
                  ("Specified Display States...", "spec"))
CONFIG_SCOPES = (("This Configuration", "this"), ("All Configurations", "all"),
                 ("Specified Configurations...", "spec"))
DISPLAYS = ("Wireframe", "Hidden Lines Visible", "Hidden Lines Removed", "Shaded With Edges", "Shaded",
            "Default Display")


def _scoped(action, scopes):
    return tuple((label, W("%s:%s" % (action, scope))) for label, scope in scopes)


def _part(menu, title):
    """A submenu of a part menu, by title (the same entries in an assembly)."""
    for entry in menu[1]:
        if isinstance(entry, tuple) and entry[0] == title:
            return entry
    return None


def _without(entry, label):
    """A submenu entry with one item (by label) left out."""
    if entry is None:
        return None
    return (entry[0], tuple(e for e in entry[1] if not (isinstance(e, tuple) and e[0] == label)))


def _part_entries(menu, titles):
    return tuple(e for e in (_part(menu, t) for t in titles) if e is not None)


def _renamed(menu, names):
    ""
    out = []
    for e in menu[1]:
        if isinstance(e, tuple) and e[0] in names:
            e = (names[e[0]], e[1])
        elif isinstance(e, str) and e in names:
            e = (names[e], e)
        out.append(e)
    return tuple(out)


# --------------------------------------------------------------------------- the menus
def _with_publish(entries):
    ""


    entries = list(entries)
    if any(isinstance(e, tuple) and str(e[0]).startswith("Publish to 3D Viewer") for e in entries):
        return tuple((e[0], W("publish_view")) if isinstance(e, tuple) and str(e[0]).startswith("Publish to 3D Viewer")
                     else e for e in entries)
    out = []
    for e in entries:
        out.append(e)
        if isinstance(e, tuple) and e[0] == "Print3D...":
            out += [S, ("Publish to 3D Viewer", W("publish_view"))]
    return tuple(out)


def _file():
    entries = list(_renamed(swmenus.FILE, {"Make Drawing from Part": "Make Drawing from Assembly",
                                           "Make Assembly from Part": "Make Assembly from Assembly",
                                           "MakeDrawing": "Make Drawing from Assembly",
                                           "MakeAssembly": "Make Assembly from Assembly"}))

    out = []
    for e in entries:
        out.append(e)
        if isinstance(e, tuple) and e[0] in ("Reload", "Reload..."):
            out.append(("Replace...", W("replace")))
        if isinstance(e, tuple) and e[0] == "Find References...":
            out.append(("Derive Component Part...", W("derive")))
    return ("&File", _with_publish(out))


def _edit():
    return ("&Edit", (
        "Undo", "Redo",
        ("Repeat Last Command", C("SWStyle_RepeatLastCommand")),
        S,
        ("Select All", C("Std_SelectAll")),
        ("Cut", C("Std_Cut")), ("Copy", C("Std_Copy")), ("Paste", C("Std_Paste")), ("Delete", C("Std_Delete")),
        S,
        ("Copy to Adobe Illustrator", W("obj:illustrator")),
        S,
        "Rebuild",
        ("Rebuild All Configurations", C("SWStyle_RebuildAllConfigurations")),
        ("Rollback", W("rollback")),
        ("Roll to Previous", W("roll_previous")),
        ("Roll to End", W("roll_end")),
        S,
        ("Hide", _scoped("hide", DISPLAY_SCOPES)),
        ("Show", _scoped("show", DISPLAY_SCOPES)),
        ("Show with Dependents", _scoped("showdep", DISPLAY_SCOPES)),
        ("Component Display", tuple((n, _scoped("cd%d" % i, DISPLAY_SCOPES)) for i, n in enumerate(DISPLAYS))),
        S,
        ("Lightweight", W("lightweight")),
        ("Resolve", W("resolve")),
        ("Suppress", _scoped("sup", CONFIG_SCOPES)),
        ("Unsuppress", _scoped("unsup", CONFIG_SCOPES)),
        ("Unsuppress with Dependents", _scoped("unsupdep", CONFIG_SCOPES)),
        S,
        ("Part", W("edit_part")),
        ("Sketch", "EditFeatureSketch"),
        ("Sketch Plane...", C("Sketcher_MapSketch")),
        ("Dissolve Assembly", W("dissolve")),
        S,
        ("Excel Design Table", (("Edit Table", W("edit_table")),
                                ("Edit Table in New Window", W("edit_table_window")))),
        ("Object", (("Display Content", W("obj:content")), ("Display as Icon", W("obj:icon")),
                    ("Reset Size", W("obj:reset")))),
        S,
        ("Definition...", "EditFeature"),
        ("Flip Normal", W("obj:flip")),
        ("Appearance", (
            ("Appearance...", "EditAppearance"), ("Material...", "EditMaterial"),
            S,
            ("Copy Appearance", "CopyAppearance"), ("Paste Appearance", "PasteAppearance"),
            S,
            ("Sketch/Curve Color...", W("obj:curvecolor")),
        )),
        ("Properties...", C("Std_Properties")),
    ))


def _view():
    out = []
    for e in swmenus.VIEW[1]:
        if isinstance(e, tuple) and e[0] == "Hide / Show":
            rows = []
            for r in e[1]:
                rows.append(r)
                if isinstance(r, tuple) and r[0] == "All Annotations":
                    rows += [("Component Envelopes", W("env_comp")), ("Top Level Envelopes", W("env_top"))]
            e = (e[0], tuple(rows))
        elif isinstance(e, tuple) and e[0] == "Display":
            rows = []
            for r in e[1]:
                rows.append(r)
                if r == "SectionView":
                    rows.append("TakeSnapshot")
                if r == "Isolate":

                    rows += [("Isolate including suppressed", W("iso_supp")), S,
                             ("Display SpeedPak Graphics Circle", C("SWStyle_SpeedPakGraphicsCircle")),
                             ("Display Graphics Components", C("SWStyle_DisplayGraphicsComponents"))]   # off the Assembly tab (look pass 11-08)
            e = (e[0], tuple(rows))
        out.append(e)
    return ("&View", tuple(out))


def _insert():

    reference = ("Reference Geometry", (
        "Plane", "Axis", ("Coordinate System...", W("ref_cs")), ("Point...", W("ref_point")),
        ("Center of Mass", "CenterOfMass"), ("Mate Reference...", W("mate_reference")),
        S,
        ("Curve Through Reference Points...", "CurveThroughReferencePoints"),
        ("Curve Through XYZ Points...", "CurveThroughXYZPoints"),
        ("Grid System", "GridSystem"), ("Ground Plane...", W("ground_plane")), ("Bounding Box", "BoundingBox"),
    ))
    notes = (
        ("Note...", "DrawNote"), ("Balloon...", "DrawBalloon"), ("Stacked Balloon...", "DrawStackedBalloon"),
        ("Surface Finish Symbol...", "DrawSurfaceFinish"), ("Weld Symbol...", "DrawWeldSymbol"),
        ("Geometric Tolerance...", "DrawGeometricTolerance"), ("Datum Feature Symbol...", "DrawDatumFeature"),
        ("Datum Target...", "DrawDatumTarget"), ("Cosmetic Thread...", "CosmeticThread"),
        S,
        ("Area Hatch/Fill", "DrawAreaHatch"), ("Location Label", "DrawLocationLabel"),
    )
    return ("&Insert", (
        ("Component", (
            ("Existing Part/Assembly...", "InsertComponents"),
            ("New Part...", "NewPartInAssembly"),
            ("New Assembly...", W("new_assembly")),
            ("Insert Part from Block...", W("part_from_block")),
            ("Assembly from Selected Components...", W("form_subassembly")),
            ("Insert from Design Library", W("partsupply")),     # pkg258: no product name
            ("Copy with Mates...", "CopyWithMates"),
        )),
        ("Mate...", "Mate"),
        ("Mate Controller...", W("mate_controller")),
        S,
        ("Component Pattern", (
            ("Linear Pattern...", "LinearComponentPattern"), ("Circular Pattern...", "CircularComponentPattern"),
            ("Pattern Driven...", "PatternDrivenComponentPattern"), ("Sketch Driven...", "SketchComponentPattern"),
            ("Curve Driven...", "CurveComponentPattern"), ("Chain Pattern...", "ChainComponentPattern"),
        )),
        ("Mirror Components...", "MirrorComponents"),
        ("Smart Fasteners...", "SmartFasteners"),
        ("Smart Features...", W("smart_features")),
        ("Exploded View...", "ExplodedView"),
        ("Explode Line Sketch", W("explode_lines")),
        ("Model Break View...", "ModelBreakView"),
        ("New Motion Study", "NewMotionStudy"),
        S,
        ("Assembly Feature", (
            ("Fillet...", "AsmFillet"), ("Chamfer...", "AsmChamfer"),
            ("Cut", (("Extrude...", "AsmExtrudedCut"), ("Revolve...", "AsmRevolvedCut"), ("Sweep...", "AsmSweptCut"))),
            ("Hole", (("Simple Hole...", "AsmSimpleHole"), ("Hole Wizard...", "AsmHoleWizard"),
                      ("Hole Series", "AsmHoleSeries"))),
            ("Weld Bead...", "AsmWeldBead"),
            S,
            ("Linear Pattern...", "AsmLinearPattern"), ("Circular Pattern...", "AsmCircularPattern"),
            ("Mirror...", "AsmMirror"), ("Table Driven Pattern...", "AsmTableDrivenPattern"),
            ("Sketch Driven Pattern...", "AsmSketchDrivenPattern"),
            S,
            ("Belt/Chain", "AsmBeltChain"),
        )),
        reference,
        S,
        "Sketch", "Sketch3D", ("Layout", "Layout"), "Sketch3DOnPlane", "DerivedSketch",
        ("Sketch From Drawing", C("SWStyle_SketchFromDrawing")), ("Slicing...", "Slicing"),
        ("Design Study", (("Add...", "DesignStudy"), ("Parameters...", C("SWStyle_DesignParameters")))),
        S,
        ("Tables", (
            ("Bill of Materials...", "BillOfMaterials"), ("Excel Design Table", "DesignTable"),
            ("Title Block Table...", "DrawTitleBlockTable"), ("General Table...", "DrawGeneralTable"),
            ("General Tolerance...", C("SWStyle_GeneralTolerance")),
        )),
        ("Annotations", notes),
        S,
        ("Object...", W("obj:object")), ("Hyperlink...", W("obj:hyperlink")), ("Picture...", W("obj:picture")),
    ))


def _tools():
    sketch = _part_entries(swmenus.TOOLS, ("Sketch Entities", "Sketch Tools", "Sketch Settings", "Blocks",
                                           "Spline Tools", "Dimensions", "Relations", "Quick Snaps"))
    return ("&Tools", (
        ("FreeCAD Applications", (
            ("Sustainability...", C("SWStyle_Sustainability")), ("Costing", C("SWStyle_Costing")),
            ("Part Reviewer", C("SWStyle_PartReviewer")), ("FreeCAD Task Scheduler...", C("SWStyle_TaskScheduler")),
        )),
    ) + ((("Lifecycle and Collaboration", swmenus.LIFECYCLE),) if hasattr(swmenus, "LIFECYCLE") else ()) + (
        ("Xpress Products", (
            ("Design Automation...", C("SWStyle_DriveWorksXpress")),
            ("SimulationXpress...", C("SWStyle_SimulationWizard")),
            ("FloXpress...", C("SWStyle_FloXpress")),
            ("SustainabilityXpress...", C("SWStyle_Sustainability")),
        )),
        S,
        ("Asset Publisher...", W("asset_publisher")),
        ("Envelope Publisher...", W("envelope_publisher")),
        ("Publish to 3D Viewer...", W("publish_view")),     # one row, the assembly publisher as File's
        ("Magnetic Mate ON/OFF", W("magnetic")),
        S,
        _without(_part(swmenus.TOOLS, "Selection"), "Select Bodies by Size..."),   # a part-only item
        S,
        ("Compare", (
            ("DrawCompare...", C("SWStyle_DrawCompare")),
            ("Documents...", W("compare:Documents")), ("Features...", W("compare:Features")),
            ("Geometry...", W("compare:Geometry")), ("BOM...", W("compare:BOM")),
            ("3D PMI...", C("SWStyle_Compare3DPMI")),
            S,
            ("Report Manager...", C("SWStyle_CompareReportManager")),
        )),
        ("Find/Modify", (
            ("Find and Replace Annotation...", W("find_replace")), ("Simplify...", W("simplify")),
        )),
        DESIGN_CHECKER,
        ("Format Painter...", C("SWStyle_FormatPainter")),
        ("Component Selection", (
            ("Volume Select...", W("volume_select")),
            ("Select Suppressed", W("select:suppressed")),
            ("Select Hidden", W("select:hidden")),
            ("Select Mated To...", W("select:mated")),
            ("Select Identical Components", W("select:identical")),
            ("Select Internal Components", W("select:internal")),
            ("Select by Size...", W("select_by_size")),
            ("Select Toolbox", W("select:toolbox")),
            ("Select Flexible Subassembly", W("select:flexible")),
            S,
            ("Advanced Select...", W("advanced_select")),
        )),
        S,
        ("Component", (("Rotate", "RotateComponent"), ("Move", "MoveComponent"), ("Preview Window", "ComponentPreview"),
                       ("Prefix/Suffix...", W("prefix_suffix")))),
        S,
    ) + sketch + (
        S,

        # assembly they could only be greyed (NO DEAD CONTROLS, rcmenus pkg187)
        _without(_without(_part(swmenus.TOOLS, "MBD Dimension"), "General Profile Tolerance"), "Import Scheme..."),
        S,
        ("Reorganize Components...", W("reorganize")),
        "Equations",
        S,
        "ImportDiagnostics", "DeviationAnalysis", "SymmetryCheck",
        S,
        ("Large Assembly Settings", "LargeAssemblyMode"),
        S,
        ("Defeature...", C("SWStyle_AsmDefeature")),
        ("Make Multibody Part", W("multibody")),
        ("Make Smart Component...", W("make_smart")),
        S,
        ROUTING_ASM,
        S,
        _part(swmenus.TOOLS, "Macro"),
        S,
        ("Evaluate", (
            "Measure", ("Markup View", "Markup"), "MassProperties", "SectionProperties", "Check",
            ("Assembly Visualization", "AssemblyVisualization"), ("Performance Evaluation", "AssemblyPerformance"),
            ("MateXpert...", "MateXpert"), ("Temporary Fix/Group", W("temporary_fix")),
            ("Interference Detection...", "Interference"), ("Clearance Verification...", "ClearanceVerification"),
            ("Hole Alignment...", "HoleAlignment"), ("Previous Release Check...", "PreviousReleaseCheck"),
        )),
        S,
        ("Add-Ins...", "AddonManager"),
        ("Save/Restore Settings...", C("SWStyle_SaveRestoreSettings")),
        "Customize",
        "Options",
        S,
        ("FreeCAD", F("freecad")),
    ))


def menus():
    """{top title: (title, entries)} in an assembly."""
    out = {}
    for build in (_file, _edit, _view, _insert, _tools):
        title, entries = build()
        out[title] = (title, tuple(e for e in entries if e is not None))
    return out


# --------------------------------------------------------------------------- helpers
def _assembly():
    try:
        from . import asmtools
        if asmtools.editing():
            return None
    except Exception as _fw_err:
        _fw_log("asmmenubar.py:400", _fw_err)
    return ac.assembly_of(App.ActiveDocument)


def _picked(asm):
    try:
        from . import asmtools
        return asmtools._picked_components(asm)
    except Exception as _fw_err:
        _fw_log("asmmenubar.py:414", _fw_err)
        return []


def _tell(title, text):
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, title, text,
                                QtWidgets.QMessageBox.Ok, Gui.getMainWindow())
    box.setObjectName("SWAsmMenuMessage")
    box.open()
    return box


def _transaction(doc, name, run):
    doc.openTransaction(name)
    try:
        result = run()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    return result


def _refresh(doc=None):
    try:
        (doc or App.ActiveDocument).recompute()
    except Exception as _fw_err:
        _fw_log("asmmenubar.py:435", _fw_err)
    try:
        Gui.updateGui()
    except Exception as _fw_err:
        _fw_log("asmmenubar.py:439", _fw_err)


def _select(objs):
    Gui.Selection.clearSelection()
    for o in objs:
        try:
            Gui.Selection.addSelection(o.Document.Name, o.Name)
        except Exception:
            Gui.Selection.addSelection(o)
    return objs


# --------------------------------------------------------------------------- display states
def _states(doc):
    from . import displaystates as ds
    return ds._data(doc)


def state_names(doc):
    from . import displaystates as ds
    return ds.names(doc) or ["Display State-1"]


def _apply_stored(doc, names, comps, key, value):
    """Writes key=value for comps into the stored (not active) display states named."""
    from . import displaystates as ds
    data = ds._data(doc)
    states = data.get("states", {})
    touched = False
    for n in names:
        if n == data.get("active") or n not in states:
            continue
        for c in comps:
            states[n].setdefault(c.Name, {"v": True})[key] = value
            touched = True
    if touched:
        ds._save(doc, data)


def _scope_names(doc, scope):
    """The display states a scope reaches: names, or None while the Specify box is open."""
    from . import displaystates as ds
    active = ds.active(doc)
    if scope == "cur":
        return [active] if active else [None]
    if scope == "all":
        return list(ds.names(doc)) or [None]
    return scope            # a list from the Specify box


def _with_scope(doc, scope, run):
    """run(names): names is a list of display state names (None = the one showing)."""
    if scope == "spec":
        return specify_display_states(doc, run)
    return run(_scope_names(doc, scope))


def specify_display_states(doc, run, parent=None):
    """Specified Display States...: tick the display states; OK runs run(names)."""
    from . import displaystates as ds
    box = QtWidgets.QDialog(parent or Gui.getMainWindow())
    box.setObjectName("SWSpecifyDisplayStates")
    box.setWindowTitle("Specify Display States")
    lay = QtWidgets.QVBoxLayout(box)
    lst = QtWidgets.QListWidget()
    lst.setObjectName("SWSpecifyDisplayStatesList")
    active = ds.active(doc)
    for n in state_names(doc):
        it = QtWidgets.QListWidgetItem(n)
        it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
        it.setCheckState(QtCore.Qt.Checked if n == active or not ds.names(doc) else QtCore.Qt.Unchecked)
        lst.addItem(it)
    lay.addWidget(lst)
    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    bb.accepted.connect(box.accept)
    bb.rejected.connect(box.reject)
    lay.addWidget(bb)
    box.list = lst

    def done(result):
        if not result:
            return
        names = [lst.item(i).text() for i in range(lst.count()) if lst.item(i).checkState() == QtCore.Qt.Checked]
        if not ds.names(doc):
            names = [None] if names else []
        if names:
            run(names)
    box.finished.connect(done)
    SPECIFY[:] = [box]
    box.open()
    return box


SPECIFY = []        # the open Specify box (checks reach it here)


def _live(doc, names):
    from . import displaystates as ds
    active = ds.active(doc)
    return None in names or (active is not None and active in names)


def dependents(comp):
    """The component and, for a subassembly, the components inside it."""
    out = [comp]
    if ac.is_subassembly(comp):
        for m in ac.sub_components(comp):
            out += dependents(m)
    return out


def set_visible(doc, comps, on, names):
    """Hide / Show in the display states named."""
    if _live(doc, names):
        for c in comps:
            if c.ViewObject is not None:
                c.ViewObject.Visibility = bool(on)
    _apply_stored(doc, [n for n in names if n], [c for c in comps if c.Document is doc], "v", bool(on))
    _refresh(doc)
    return comps


def set_display(doc, comps, display, names):
    """Component Display in the display states named."""
    from . import asmcomp
    if _live(doc, names):
        for c in comps:
            asmcomp.component_display(c, display)
    _apply_stored(doc, [n for n in names if n], comps, "cd", display)
    _refresh(doc)
    return comps


def _patch_display_states():
    """Display states keep each component's Component Display ("cd") too."""
    from . import displaystates as ds
    if getattr(ds, "_fw_cd", False):
        return
    capture0, restore0 = ds.capture, ds.restore

    def capture(doc):
        out = capture0(doc)
        try:
            from . import asmcomp
            for obj in doc.Objects:
                if obj.Name in out and hasattr(obj, asmcomp.DISPLAY_PROP):
                    out[obj.Name]["cd"] = asmcomp.display_of(obj)
        except Exception as _fw_err:
            _fw_log("asmmenubar.py:588", _fw_err)
        return out

    def restore(doc, look):
        restore0(doc, look)
        try:
            from . import asmcomp
            for name, item in look.items():
                obj = doc.getObject(name)
                if obj is not None and "cd" in item and asmcomp.display_of(obj) != item["cd"]:
                    asmcomp.component_display(obj, item["cd"])
        except Exception as error:
            App.Console.PrintLog("FreeCAD: display state component display: %s\n" % error)
    ds.capture, ds.restore = capture, restore
    ds._fw_cd = True


# --------------------------------------------------------------------------- configurations
def suppress(asm, comps, on, scope, dependents_too=False):
    """Suppress / Unsuppress (with Dependents) in This / All / Specified configurations."""
    from . import asmcomp, asmmenu, configmanager
    doc = asm.Document
    has_table = configmanager.table(doc) is not None

    def run(names):
        def go():
            for c in comps:
                if has_table:
                    from . import configs
                    configs.suppress_component(c, on, names)
                else:
                    asmcomp.suppress(c, on, solve=False)
                if dependents_too and not on:
                    for j in asmmenu.mates_of(c):      # its mates come back too, even ones suppressed on their own
                        if getattr(j, "Suppressed", False):
                            asmmenu.suppress(j, False)
            if not on:
                ac.solve(asm)                          # once for them all (suppressing moves nothing)
        return _transaction(doc, "Unsuppress" if not on else "Suppress", go)

    if scope == "spec" and has_table:
        from . import configs
        return configs.specify(doc, run)
    return run(scope if scope != "spec" else "this")


# --------------------------------------------------------------------------- Dissolve Assembly
def dissolve(asm, sub):
    """Dissolve Assembly: the subassembly's components become components of this assembly, where
    they are; the subassembly's mates come up with them and the top mates on its parts follow."""
    from . import asmexplode as ax
    if not ac.is_subassembly(sub):
        return []
    doc = asm.Document
    inner = ac.sub_components(sub)
    source = getattr(sub, "LinkedObject", None)
    source_comps = ac.components(source) if source is not None else []
    fixed = sub in ac.grounded(asm)
    new = {}
    from . import asmreorg
    for m in inner:
        target = m.LinkedObject if m.TypeId in ("App::Link", "Assembly::AssemblyLink") else m
        config = None
        if target in source_comps:
            # the subassembly's copy links its component: the new one links that component's part
            target, config = asmreorg._part_of(target)
        plc = ax.gplacement(m)
        link = ac.insert(asm, target, plc)
        link.Placement = plc
        if config:
            asmreorg._same_configuration(link, config)
        new[m] = link
    # the subassembly's own mates (on its source document), owners matched by order
    by_source = dict(zip(source_comps, inner))
    sub_mates = ac.mates(source) if source is not None else []
    _remake = []
    for j in sub_mates:
        refs = [getattr(j, p, None) for p in ("Reference1", "Reference2")]
        if not all(refs):
            continue
        owners = [by_source.get(r[0]) for r in refs]
        if not all(o in new for o in owners):
            continue
        _remake.append((j, [(new[owners[i]], refs[i][1][0]) for i in range(2)]))
    # top mates that held the subassembly's parts
    moved = []
    for j in list(ac.mates(asm)):
        refs = [getattr(j, p, None) for p in ("Reference1", "Reference2")]
        if not all(refs) or not any(r[0] is sub or r[0] in new for r in refs):
            continue
        mapped = []
        for r in refs:
            owner, path = r[0], r[1][0]
            if owner is sub:
                first, _dot, rest = path.partition(".")
                hit = [m for m in inner if m.Name == first]
                owner, path = (new[hit[0]], rest) if hit else (None, path)
            elif owner in new:
                owner = new[owner]
            mapped.append((owner, path))
        if all(m[0] is not None for m in mapped):
            _remake.append((j, mapped))
        moved.append(j)
    for j, refs in _remake:
        kind = ac.mate_type(j)
        value = ac.distance_value(j) if kind == "Distance" else (
            getattr(j, "Angle", None) if kind == "Angle" else None)
        try:
            ac.add_mate(asm, kind, refs[0], refs[1], value=value, name=j.Label.split(" (")[0],
                        side=ac.distance_side(j) if kind == "Distance" else None)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: dissolve, mate %s: %s\n" % (j.Label, error))
    for j in moved:
        doc.removeObject(j.Name)
    if fixed:
        doc.removeObject(ac.grounded(asm)[sub].Name)
        source_fixed = set(ac.grounded(source)) if source is not None else set()
        for s, m in by_source.items():
            if s in source_fixed and new.get(m) is not None and new[m] not in ac.grounded(asm):
                ac.fix(asm, new[m])
    from . import asmcomp
    virtual = source if asmcomp.is_virtual_sub(sub) else None
    kids = [k for k in getattr(sub, "Group", []) or []]
    doc.removeObject(sub.Name)
    for k in kids:      # FreeCAD leaves the subassembly component's own copies behind
        try:
            if doc.getObject(k.Name) is not None:
                doc.removeObject(k.Name)
        except Exception as _fw_err:
            _fw_log("asmmenubar.py:717", _fw_err)
    if virtual is not None:
        asmcomp.remove_virtual_source(virtual)      # a virtual subassembly goes with its component
        for link in new.values():       # the names its components held are free again: Pin<1>, not Pin<1>004
            plain = asmcomp.plain_label(link.Label)
            if plain != link.Label and not doc.getObjectsByLabel(plain):
                link.Label = plain
    for link in new.values():
        try:
            link.Placement = link.Placement
        except Exception as _fw_err:
            _fw_log("asmmenubar.py:728", _fw_err)
    doc.recompute()
    ac.solve(asm)
    return list(new.values())


# --------------------------------------------------------------------------- New Assembly
def new_assembly(asm, path=None):
    """Insert > Component > New Assembly: an empty assembly file (Assem<n>), in the folder of
    this one, inserted at the origin as a subassembly."""
    from . import asmcomp
    if path is None:

        sub = asmcomp.virtual_assembly(asm.Document)
        link = ac.insert(asm, sub, App.Placement())
        asmcomp.mark_virtual(asm, link)
        asm.Document.recompute()
        return link
    folder = os.path.dirname(asm.Document.FileName or "") or App.getUserAppDataDir()
    name = asmcomp._next_assembly_name(folder)
    path = path or os.path.join(folder, name + ".FCStd")
    keep = App.ActiveDocument
    new_doc = App.newDocument(name)
    sub = ac.make_assembly(new_doc)
    new_doc.saveAs(path)
    new_doc.Label = os.path.splitext(os.path.basename(path))[0]
    sub.Label = new_doc.Label
    new_doc.save()
    link = ac.insert(asm, sub, App.Placement())
    _front(keep)
    asm.Document.recompute()
    return link


def _front(doc):
    try:
        from . import designlib
        designlib._front(doc)
    except Exception:
        try:
            App.setActiveDocument(doc.Name)
            Gui.setActiveDocument(doc.Name)
        except Exception as _fw_err:
            _fw_log("asmmenubar.py:771", _fw_err)


# --------------------------------------------------------------------------- Make Multibody Part
def multibody_part(asm, name=None, linked=False, solids=True, surfaces=True):
    ""


    from . import asmtools, asmcomp, asmdefrules
    keep = App.ActiveDocument
    doc = App.newDocument(name or (asm.Document.Label + "_Multibody"))
    if linked:

        # saves the new part before it links it
        import os
        folder = os.path.dirname(asm.Document.FileName or "")
        if not folder:
            linked = False
        else:
            stem = os.path.join(folder, doc.Label)
            path, n = stem + ".FCStd", 1
            while os.path.exists(path):
                n += 1
                path = "%s%d.FCStd" % (stem, n)
            doc.saveAs(path)
    made = []
    for unit in asmtools.units(asm, subassemblies=False):
        if asmcomp.is_suppressed(unit):
            continue
        try:
            shape = asmtools._global_shape(unit)
        except Exception:
            shape = None
        if shape is None or shape.isNull():
            continue
        solid = bool(shape.Solids)
        if (solid and not solids) or (not solid and not surfaces):
            continue
        if linked:
            body = doc.addObject("PartDesign::SubShapeBinder", "Body")
            path = _unit_path(asm, unit)
            body.Support = [(asm, [path])]
            try:
                body.BindMode = "Synchronized"
            except Exception as _fw_err:
                _fw_log("asmmenubar.py:816", _fw_err)
            body.addProperty("App::PropertyString", MULTIBODY_PROP, "FreeCAD", "Linked to (assembly file, component)")
            body.setEditorMode(MULTIBODY_PROP, 2)
            setattr(body, MULTIBODY_PROP, json.dumps([asm.Document.FileName or asm.Document.Name, unit.Label]))
        else:
            body = doc.addObject("Part::Feature", "Body")
            body.Shape = shape
        body.Label = asmtools.unit_label(unit)
        asmdefrules.propagate_visuals(unit, body)
        made.append(body)
    doc.recompute()
    if linked:
        try:
            doc.save()
        except Exception as _fw_err:
            _fw_log("asmmenubar.py:831", _fw_err)
    try:
        Gui.SendMsgToActiveView("ViewFit")
    except Exception as _fw_err:
        _fw_log("asmmenubar.py:835", _fw_err)
    return doc, made


# --------------------------------------------------------------------------- component name prefix / suffix
def _split_label(label):
    """("Bracket", "<2>") of "Bracket<2>"; the instance number stays at the end."""
    if label.endswith(">") and "<" in label:
        i = label.rfind("<")
        return label[:i], label[i:]
    return label, ""


def add_prefix_suffix(comps, prefix="", suffix="", remove=False):
    ""

    done = []
    for c in comps:
        base, num = _split_label(c.Label)
        if remove:
            new = base
            if prefix and new.startswith(prefix):
                new = new[len(prefix):]
            if suffix and new.endswith(suffix):
                new = new[:-len(suffix)]
        else:
            new = base
            if prefix and not new.startswith(prefix):
                new = prefix + new
            if suffix and not new.endswith(suffix):
                new = new + suffix
        if new != base:
            c.Label = new + num
            done.append(c)
    return done


class PrefixSuffixPanel:
    """Component name Prefix / Suffix: the picked components (all, with none picked)."""

    def __init__(self, asm):
        from . import asmpm
        self.asm = asm
        picks = [o for o in Gui.Selection.getSelection() if o in ac.components(asm)]
        self.comps = picks or list(ac.components(asm))
        box, lay = asmpm._box("Component Names", "Prefix/Suffix")
        box.setObjectName("FW_PrefixSuffix")
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_PrefixSuffixComponents")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 4))
        for c in self.comps:
            self.list.addItem(c.Label)
        lay.addWidget(self.list)
        form = QtWidgets.QFormLayout()
        self.prefix = QtWidgets.QLineEdit()
        self.prefix.setObjectName("FW_Prefix")
        self.suffix = QtWidgets.QLineEdit()
        self.suffix.setObjectName("FW_Suffix")
        form.addRow("Prefix:", self.prefix)
        form.addRow("Suffix:", self.suffix)
        lay.addLayout(form)
        self.remove = QtWidgets.QCheckBox("Remove prefix and suffix")
        self.remove.setObjectName("FW_PrefixSuffixRemove")
        lay.addWidget(self.remove)
        self.form = [box]

    def accept(self):
        doc = self.asm.Document
        doc.openTransaction("Prefix/Suffix")
        try:
            add_prefix_suffix(self.comps, self.prefix.text(), self.suffix.text(), self.remove.isChecked())
        finally:
            doc.commitTransaction()
        Gui.Control.closeDialog()
        try:
            from . import asmui
            asmui.refresh()
        except Exception as _fw_err:
            _fw_log("asmmenubar.py:914", _fw_err)
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


MULTIBODY_PROP = "FwMultibodyFrom"


def _unit_path(asm, unit):
    """The subname of a component (or a component inside a subassembly) under asm."""
    path = [unit.Name]
    parent = None
    for c in ac.components(asm):
        if c is unit:
            return unit.Name + "."
        try:
            if unit in c.getLinkedObject(True).OutListRecursive:
                parent = c
        except Exception as _fw_err:
            _fw_log("asmmenubar.py:939", _fw_err)
    if parent is not None:
        return "%s.%s." % (parent.Name, unit.Name)
    return ".".join(path) + "."


class MultibodyPanel:
    ""

    def __init__(self, asm):
        from . import asmpm
        self.asm = asm
        box, lay = asmpm._box("Options", "Make Multibody Part")
        box.setObjectName("FW_MakeMultibody")
        self.link = QtWidgets.QCheckBox("Link to assembly")
        self.link.setObjectName("FW_MultibodyLink")
        self.link.setToolTip("The bodies follow the components when the assembly changes")
        self.link.setChecked(True)
        lay.addWidget(self.link)
        tbox, tl = asmpm._box("Bodies to transfer")
        self.solids = QtWidgets.QCheckBox("Solid bodies")
        self.solids.setObjectName("FW_MultibodySolids")
        self.solids.setChecked(True)
        self.surfaces = QtWidgets.QCheckBox("Surface bodies")
        self.surfaces.setObjectName("FW_MultibodySurfaces")
        self.surfaces.setChecked(True)
        tl.addWidget(self.solids)
        tl.addWidget(self.surfaces)
        self.form = [box, tbox]
        self.result = None

    def accept(self):
        if not (self.solids.isChecked() or self.surfaces.isChecked()):
            return False
        opts = dict(linked=self.link.isChecked(), solids=self.solids.isChecked(), surfaces=self.surfaces.isChecked())
        Gui.Control.closeDialog()       # it deletes the PM's widgets: the options are read first
        self.result = multibody_part(self.asm, **opts)
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def open_multibody(asm):
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    panel = MultibodyPanel(asm)
    OPEN[:] = [panel]
    Gui.Control.showDialog(panel)
    return panel


# --------------------------------------------------------------------------- Derive Component Part
DERIVED_PROP = "FwDerivedFrom"


def derive_component_part(asm, comp, name=None):
    """File > Derive Component Part: a new part made from the component, where the assembly has
    it; the part remembers the assembly and the component it came from."""
    from . import asmtools
    shape = asmtools._global_shape(comp)
    doc = App.newDocument(name or (ac.part_name(comp) + "_Derived"))
    feat = doc.addObject("Part::Feature", "DerivedPart")
    feat.Label = ac.part_name(comp)
    feat.Shape = shape
    feat.addProperty("App::PropertyString", DERIVED_PROP, "FreeCAD", "Derived from (assembly file, component)")
    setattr(feat, DERIVED_PROP, json.dumps([asm.Document.FileName or asm.Document.Name, comp.Label]))
    doc.recompute()
    return doc, feat


# --------------------------------------------------------------------------- Component Selection
def select_where(asm, test):
    return _select([c for c in ac.components(asm) if test(c)])


def _hidden(c):
    try:
        return c.ViewObject is not None and not c.ViewObject.Visibility
    except Exception:
        return False


def mated_to(asm, comps):
    from . import asmmenu
    out = []
    for c in comps:
        for j in asmmenu.mates_of(c):
            for p in ("Reference1", "Reference2"):
                r = getattr(j, p, None)
                if r and r[0] is not c and r[0] not in out and r[0] not in comps:
                    out.append(r[0])
    return out


def identical(asm, comps):
    targets = {id(getattr(c, "LinkedObject", c)) for c in comps}
    return [c for c in ac.components(asm) if id(getattr(c, "LinkedObject", c)) in targets]


def _box(c):
    from . import asmtools
    try:
        s = asmtools._global_shape(c)
        return None if s.isNull() else s.BoundBox
    except Exception as _fw_err:
        _fw_log("asmmenubar.py:1055", _fw_err)
        return None


def internal(asm):
    """Components that sit inside others (their box inside another component's box)."""
    comps = [c for c in ac.components(asm) if not _hidden(c)]
    boxes = {c: _box(c) for c in comps}
    out = []
    for c in comps:
        b = boxes[c]
        if b is None:
            continue
        for o in comps:
            ob = boxes[o]
            if o is c or ob is None:
                continue
            if ob.isInside(b) and (ob.DiagonalLength > b.DiagonalLength + 1e-6):
                out.append(c)
                break
    return out


def by_size(asm, percent):
    """Select by Size: the components whose size is at most percent of the assembly's."""
    comps = ac.components(asm)
    boxes = {c: _box(c) for c in comps}
    whole = None
    for b in boxes.values():
        if b is None:
            continue
        if whole is None:
            whole = App.BoundBox(b)
        else:
            whole.add(b)
    if whole is None or whole.DiagonalLength <= 0:
        return []
    limit = whole.DiagonalLength * percent / 100.0
    return [c for c in comps if boxes[c] is not None and boxes[c].DiagonalLength <= limit + 1e-9]


class SelectBySizeBox(QtWidgets.QDialog):
    """Select by Size: a percent of the assembly's size; components no bigger are selected, live."""

    def __init__(self, asm, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.asm = asm
        self.setObjectName("SWSelectBySize")
        self.setWindowTitle("Select by Size")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Select components smaller than (% of the assembly size):"))
        row = QtWidgets.QHBoxLayout()
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setObjectName("SWSelectBySizeSlider")
        self.slider.setRange(0, 100)
        self.spin = QtWidgets.QSpinBox()
        self.spin.setObjectName("SWSelectBySizePercent")
        self.spin.setRange(0, 100)
        self.spin.setSuffix("%")
        row.addWidget(self.slider)
        row.addWidget(self.spin)
        lay.addLayout(row)
        self.count = QtWidgets.QLabel()
        self.count.setObjectName("SWSelectBySizeCount")
        lay.addWidget(self.count)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        self.spin.valueChanged.connect(self.update_pick)
        self.before = list(Gui.Selection.getSelection())
        self.rejected.connect(lambda: _select(self.before))
        self.spin.setValue(10)
        self.update_pick()

    def update_pick(self, *_a):
        picked = by_size(self.asm, self.spin.value())
        _select(picked)
        self.count.setText("%d component(s) selected" % len(picked))


class VolumeSelect(QtCore.QObject):
    """Volume Select: drag a box in the graphics area; the components inside it or crossing it
    are selected. Esc or a right-click ends it."""

    def __init__(self, asm):
        super().__init__()
        self.asm = asm
        self.view = Gui.ActiveDocument.ActiveView
        self.gl = self._viewport()
        self.start = None
        self.band = None
        if self.gl is not None:
            self.gl.installEventFilter(self)
            self.gl.setCursor(QtCore.Qt.CrossCursor)
        ACTIVE[:] = [self]

    def _viewport(self):
        try:
            gv = self.view.graphicsView()
            if gv is not None:
                return gv.viewport()
        except Exception as _fw_err:
            _fw_log("asmmenubar.py:1153", _fw_err)
        mw = Gui.getMainWindow()
        for w in mw.findChildren(QtWidgets.QWidget):
            if w.inherits("QOpenGLWidget") and w.isVisible():
                return w
        return None

    def finish(self):
        if self.gl is not None:
            try:
                self.gl.removeEventFilter(self)
                self.gl.unsetCursor()
            except Exception as _fw_err:
                _fw_log("asmmenubar.py:1166", _fw_err)
        if self.band is not None:
            self.band.hide()
            self.band.deleteLater()
            self.band = None
        ACTIVE[:] = []

    def components_in(self, rect):
        """Components whose box, as the view shows it, meets rect (viewport pixels)."""
        out = []
        h = self.gl.height()
        for c in ac.components(self.asm):
            if _hidden(c):
                continue
            b = _box(c)
            if b is None:
                continue
            xs, ys = [], []
            for i in range(8):
                p = b.getPoint(i)
                try:
                    x, y = self.view.getPointOnViewport(p)
                except Exception:
                    continue
                xs.append(x)
                ys.append(h - y)
            if not xs:
                continue
            seen = QtCore.QRectF(QtCore.QPointF(min(xs), min(ys)), QtCore.QPointF(max(xs), max(ys)))
            if QtCore.QRectF(rect).intersects(seen):
                out.append(c)
        return out

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            self.finish()
            return True
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.RightButton:
                self.finish()
                return True
            if event.button() == QtCore.Qt.LeftButton:
                self.start = event.pos()
                self.band = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Rectangle, self.gl)
                self.band.setObjectName("SWVolumeSelectBand")
                self.band.setGeometry(QtCore.QRect(self.start, QtCore.QSize()))
                self.band.show()
                return True
        if t == QtCore.QEvent.MouseMove and self.start is not None and self.band is not None:
            self.band.setGeometry(QtCore.QRect(self.start, event.pos()).normalized())
            return True
        if t == QtCore.QEvent.MouseButtonRelease and self.start is not None and event.button() == QtCore.Qt.LeftButton:
            rect = QtCore.QRect(self.start, event.pos()).normalized()
            self.start = None
            picked = self.components_in(rect)
            add = bool(event.modifiers() & QtCore.Qt.ControlModifier)
            if add:
                for c in picked:
                    Gui.Selection.addSelection(c.Document.Name, c.Name)
            else:
                _select(picked)
            self.picked = picked
            self.finish()
            return True
        return False


ACTIVE = []         # the running Volume Select


# --------------------------------------------------------------------------- envelopes
def envelopes(asm, top=True):
    from . import asminsert
    comps = ac.components(asm)
    if top:
        return [c for c in comps if asminsert.is_envelope(c)]
    out = []
    for c in comps:
        if ac.is_subassembly(c):
            out += [m for m in dependents(c)[1:] if asminsert.is_envelope(m)]
    return out


def envelopes_shown(asm, top=True):
    env = envelopes(asm, top)
    return bool(env) and all(not _hidden(c) for c in env)


def show_envelopes(asm, top, on):
    for c in envelopes(asm, top):
        if c.ViewObject is not None:
            c.ViewObject.Visibility = bool(on)
    _refresh(asm.Document)


# --------------------------------------------------------------------------- Edit Table
def edit_table(asm, window=False):
    ""

    from . import configmanager
    t = configmanager.table(asm.Document)
    if t is None:
        return None
    return configmanager.edit_table(t, window)     # the design table window (dtedit), its own place in New Window


# --------------------------------------------------------------------------- the "fw:" items
def _item(label, enabled, run, checked=None):
    return swmenus.Item(label, enabled, run, None, "", checked)


def _has_shapes(doc):
    return doc is not None and any(getattr(o, "Shape", None) is not None and not o.Shape.isNull()
                                   and o.Shape.Faces for o in doc.Objects if hasattr(o, "Shape"))


def _yields_dialog():
    ""

    if not Gui.Control.activeDialog():
        return True
    try:
        from . import asmpm
        p = getattr(asmpm, "OPEN", None)
        form = getattr(p, "form", None)
        form = form[0] if isinstance(form, (list, tuple)) and form else form
        return isinstance(p, asmpm.InsertComponentPanel) and form is not None and form.isVisible()
    except Exception as _fw_err:
        _fw_log("asmmenubar.py:1313", _fw_err)
        return False


def _close_yielding():
    if Gui.Control.activeDialog() and _yields_dialog():
        Gui.Control.closeDialog()
        try:
            QtWidgets.QApplication.processEvents()
        except Exception as _fw_err:
            _fw_log("asmmenubar.py:1315", _fw_err)


def item(name, label):
    """swmenus.Item for an "fw:" entry, or None when it doesn't apply here."""
    if name == "mate_reference":          # parts and assemblies
        from . import asmrefgeom
        doc = App.ActiveDocument

        return _item(label, (_has_shapes(doc) or ac.assembly_of(doc) is not None) and _yields_dialog(),
                     lambda: (_close_yielding(), asmrefgeom.edit_mate_reference(doc=doc)))
    if name == "asset_publisher":         # parts and assemblies
        from . import asmpublish
        doc = App.ActiveDocument
        return _item(label, _has_shapes(doc) and not Gui.Control.activeDialog(),
                     lambda: asmpublish.start_asset_publisher(doc))
    if name == "publish_view":            # parts and assemblies
        from . import publishview
        doc = App.ActiveDocument
        return _item(label, _has_shapes(doc), lambda: publishview.start(doc))
    if name in ("simplify", "find_replace"):   # parts and assemblies
        from . import simplify
        doc = App.ActiveDocument
        if name == "simplify":
            return _item(label, _has_shapes(doc), lambda: simplify.open_simplify(doc))
        return _item(label, doc is not None, lambda: simplify.open_find_replace(doc))
    if name.startswith("dc:"):             # parts and assemblies
        from . import designchecker as dc      # the one Design Checker, parts and assemblies
        doc = App.ActiveDocument
        run = {"dc:check": lambda: dc.check_active(doc), "dc:against": lambda: dc.check_against(doc),
               "dc:build": dc.build_checks, "dc:learn": dc.learn_wizard}[name]
        return _item(label, doc is not None, run)
    if name == "elec:library":             # parts and assemblies
        from . import asmelec
        return _item(label, App.ActiveDocument is not None, asmelec.wire_library_wizard)
    if name == "route_cpoint":             # parts and assemblies
        from . import asmroute
        doc = App.ActiveDocument
        return _item(label, _has_shapes(doc) and not Gui.Control.activeDialog(),
                     lambda: asmroute.start_connection_point(doc))
    if name.startswith("obj:"):            # parts and assemblies
        from . import asmobjects as ob
        doc = App.ActiveDocument
        what = name[4:]
        if what == "illustrator":
            return _item(label, Gui.ActiveDocument is not None, ob.copy_to_illustrator)
        if what in ("content", "icon", "reset"):
            picked = ob.picked_objects()
            run = {"content": lambda: ob.set_icon(picked, False), "icon": lambda: ob.set_icon(picked, True),
                   "reset": lambda: ob.reset_size(picked)}[what]
            checked = None
            if picked and what != "reset":
                checked = all(o.AsIcon for o in picked) == (what == "icon")
            return _item(label, bool(picked), run, checked=checked)
        if what == "flip":
            picked = ob.flippable()
            return _item(label, bool(picked), lambda: ob.flip_normal(picked))
        if what == "curvecolor":
            picked = ob.curves()
            return _item(label, bool(picked), lambda: ob.pick_curve_colour(picked))
        free = not Gui.Control.activeDialog()
        run = {"object": lambda: ob.start_object(doc), "hyperlink": lambda: ob.start_hyperlink(doc),
               "picture": lambda: ob.start_picture(doc)}.get(what)
        return _item(label, free and run is not None, run)
    asm = ac.assembly_of(App.ActiveDocument)
    if asm is None:
        if name == "envelope_publisher":
            return _item(label, False, lambda: None)
        return None
    if name.startswith("compare:"):
        from . import asmcompare
        asmcompare.install()
        tab = name.partition(":")[2]
        return _item(label, True, lambda: asmcompare.open_tab(tab))
    if name in ("make_smart", "smart_features"):
        from . import asmsmart
        free = not Gui.Control.activeDialog()
        if name == "make_smart":
            return _item(label, free and len(ac.components(asm)) >= 2, lambda: asmsmart.start_make_smart(asm))
        return _item(label, free and any(asmsmart.is_smart(c) for c in ac.components(asm) if c.TypeId == "App::Link"),
                     lambda: asmsmart.start_smart_features(asm))
    if name == "magnetic":
        from . import asmmagnet
        return _item(label, True, asmmagnet.toggle, checked=asmmagnet.enabled())
    if name.startswith("fitting:"):
        from . import asmrlib
        return _item(label, not Gui.Control.activeDialog(),
                     lambda: asmrlib.start_fitting(asm, name.partition(":")[2]))
    if name.startswith("elec:"):
        from . import asmroute, asmelec
        cables = [r for r in asmroute.routes(asm) if r.Kind == "Electrical"]
        free = not Gui.Control.activeDialog()
        what = name[5:]
        if what == "fromto":
            return _item(label, free and bool(asmroute.ports(asm)), lambda: asmelec.import_from_to_ask(asm))
        run = {"wires": lambda: asmelec.edit_wires(asm), "flatten": lambda: asmelec.flatten_picked(asm),
               "report": lambda: asmelec.harness_report_ask(asm)}.get(what)
        return _item(label, free and bool(cables) and run is not None, run)
    if name.startswith("route_"):
        from . import asmroute
        action, _sep, kind = name.partition(":")
        free = not Gui.Control.activeDialog()
        if action == "route_edit":
            return _item(label, free and bool(asmroute.routes(asm)), lambda: asmroute.edit(asm=asm))
        return _item(label, free and len(asmroute.ports(asm)) >= 2,
                     lambda: asmroute.start_route(asm, kind or "Pipe"))
    if name == "envelope_publisher":
        from . import asmpublish
        return _item(label, bool(asmpublish.subassemblies(asm)) and not Gui.Control.activeDialog(),
                     lambda: asmpublish.start_envelope_publisher(asm))
    if name in ("ref_cs", "ref_point"):
        from . import asmrefgeom
        return _item(label, not Gui.Control.activeDialog(),
                     lambda: asmrefgeom.datum(asm, "cs" if name == "ref_cs" else "point"))
    if name == "part_from_block":
        from . import asmtabs
        return _item(label, asmtabs.can_start_make_part() and not Gui.Control.activeDialog(), asmtabs.start_make_part)
    if name == "ground_plane":
        from . import asmrefgeom
        return _item(label, not Gui.Control.activeDialog(), lambda: asmrefgeom.start_ground_plane(asm))
    doc = asm.Document
    picked = _picked(asm)
    one = picked[0] if len(picked) == 1 else None
    action, _sep, scope = name.partition(":")

    if action in ("hide", "show", "showdep"):
        on = action != "hide"

        def run(action=action, scope=scope, picked=picked, on=on):
            comps = picked if action != "showdep" else [d for c in picked for d in dependents(c)]
            _with_scope(doc, scope, lambda names: set_visible(doc, comps, on, names))
        return _item(label, bool(picked), run)
    if action.startswith("cd") and action[2:].isdigit():
        display = DISPLAYS[int(action[2:])]
        return _item(label, bool(picked), lambda: _with_scope(doc, scope, lambda names: set_display(doc, picked, display, names)))
    if action in ("sup", "unsup", "unsupdep"):
        from . import asmcomp
        on = action == "sup"
        can = [c for c in picked if asmcomp.is_suppressed(c) != on]
        return _item(label, bool(can), lambda: suppress(asm, can, on, scope, action == "unsupdep"))
    if action == "lightweight":
        from . import asmcomp
        can = [c for c in picked if not asmcomp.is_lightweight(c) and not asmcomp.is_suppressed(c)]
        return _item(label, bool(can), lambda: [asmcomp.set_lightweight(c, True) for c in can])
    if action == "resolve":
        from . import asmcomp
        can = [c for c in picked if asmcomp.is_lightweight(c) or asmcomp.is_suppressed(c)]

        def run():
            def go():
                for c in can:
                    asmcomp.set_lightweight(c, False)
                    if asmcomp.is_suppressed(c):
                        asmcomp.suppress(c, False)
            _transaction(doc, "Resolve", go)
        return _item(label, bool(can), run)
    if action == "edit_part":
        return _item(label, one is not None, lambda: Gui.runCommand("SWStyle_EditComponent", 0))
    if action == "dissolve":
        subs = [c for c in picked if ac.is_subassembly(c)]
        return _item(label, bool(subs), lambda: _transaction(doc, "Dissolve Assembly",
                                                             lambda: [dissolve(asm, s) for s in subs]))
    if action in ("edit_table", "edit_table_window"):
        from . import configmanager
        return _item(label, configmanager.table(doc) is not None, lambda: edit_table(asm, action == "edit_table_window"))
    if action == "partsupply":
        from . import taskpane
        return _item(label, True, lambda: taskpane.open_tab(1))
    if action == "new_assembly":
        return _item(label, True, lambda: _transaction(doc, "New Assembly", lambda: new_assembly(asm)))
    if action == "form_subassembly":
        from . import asmcomp
        can = [c for c in picked if not ac.is_subassembly(c)]
        return _item(label, bool(can), lambda: _transaction(doc, "Form New Subassembly",
                                                            lambda: asmcomp.form_new_subassembly(asm, can)))
    if action == "volume_select":
        return _item(label, Gui.ActiveDocument is not None, lambda: VolumeSelect(asm))
    if action == "select":
        from . import asmcomp
        if scope == "suppressed":
            return _item(label, True, lambda: select_where(asm, asmcomp.is_suppressed))
        if scope == "hidden":
            return _item(label, True, lambda: select_where(asm, _hidden))
        if scope == "mated":
            return _item(label, bool(picked), lambda: _select(mated_to(asm, picked)))
        if scope == "identical":
            return _item(label, bool(picked), lambda: _select(identical(asm, picked)))
        if scope == "internal":
            return _item(label, True, lambda: _select(internal(asm)))
        if scope == "toolbox":
            from . import toolbox, asmtools

            def is_tb(c):
                return toolbox.is_fastener(c) or asmtools.is_fastener(c)
            return _item(label, True, lambda: select_where(asm, is_tb))
        if scope == "flexible":
            return _item(label, True, lambda: select_where(asm, ac.is_flexible))
        return None
    if action == "select_by_size":
        return _item(label, True, lambda: _open(SelectBySizeBox(asm)))
    if action == "temporary_fix":
        from . import asmcomp
        temp = bool(asmcomp.temporary_joints(asm))
        if temp:
            return _item("Release Temporary Fix/Group", True,
                         lambda: _transaction(doc, "Temporary Fix/Group", lambda: asmcomp.release_temporary(asm)))
        return _item(label, bool(picked), lambda: _transaction(doc, "Temporary Fix/Group",
                                                               lambda: asmcomp.temporary_fix(asm, picked)))
    if action in ("rollback", "roll_previous", "roll_end"):
        from . import asmrollback as rbk
        if action == "rollback":
            picks = [o for o in Gui.Selection.getSelection() if rbk.can_roll_back(o)]
            if not picks and not Gui.Selection.getSelection():
                items = rbk.rollable(asm)      # nothing picked: the bar up one item
                t = rbk.tip(asm)
                k = [o.Name for o in items].index(t.Name)
                return _item(label, k > 0, lambda: rbk.roll(asm, items[k - 1]))
            return _item(label, bool(picks), lambda: rbk.roll_back_to(picks[0]))
        if action == "roll_previous":
            return _item(label, rbk.previous(asm) is not None, lambda: rbk.roll_to_previous(asm))
        return _item(label, bool(getattr(asm, rbk.TIP_PROP, "")), lambda: rbk.roll_to_end(asm))
    if action == "mate_controller":
        from . import asmmatectrl as mc
        return _item(label, bool(mc.supported(asm) or mc.controllers(asm)), lambda: mc.start(asm))
    if action == "explode_lines":
        from . import asmexplode, asmexplines
        return _item(label, asmexplode.exploded_view(asm) is not None, lambda: asmexplines.start(asm))
    if action == "reorganize":
        from . import asmreorg
        return _item(label, any(ac.is_subassembly(c) for c in ac.components(asm)),
                     lambda: _open(_reorg(asmreorg, asm, picked)))
    if action == "advanced_select":
        from . import asmreorg
        return _item(label, True, lambda: _open(asmreorg.AdvancedSelectBox(asm)))
    if action == "prefix_suffix":
        return _item(label, bool(ac.components(asm)), lambda: _open(PrefixSuffixPanel(asm)))
    if action == "multibody":
        return _item(label, bool(ac.components(asm)), lambda: open_multibody(asm))
    if action == "replace":
        from . import asmreplacecomp
        return _item(label, True, lambda: asmreplacecomp.start(one))
    if action == "derive":
        return _item(label, one is not None and not ac.is_subassembly(one), lambda: derive_component_part(asm, one))
    if action == "iso_supp":
        from . import asmisolate
        return _item(label, bool(asmisolate.picked(asm)), asmisolate.isolate_including_suppressed)
    if action in ("env_comp", "env_top"):
        top = action == "env_top"
        shown = envelopes_shown(asm, top)
        return _item(label, bool(envelopes(asm, top)), lambda: show_envelopes(asm, top, not shown), checked=shown)
    return None


def _reorg(asmreorg, asm, picked):
    box = asmreorg.ReorganizePanel(asm)
    box.pick(picked)
    return box


def _open(box):
    OPEN[:] = [box]
    if hasattr(box, "form"):
        Gui.Control.closeDialog()
        Gui.Control.showDialog(box)
    else:
        box.open()
    return box


OPEN = []


# --------------------------------------------------------------------------- hooking swmenus
_loaded = []


def load_assembly_commands():
    """FreeCAD's Assembly commands (New Part, Bill of Materials, Exploded View) are made when its
    workbench first opens; the menus need them before that."""
    if _loaded:
        return
    _loaded.append(True)
    have = set(Gui.listCommands())
    if "Assembly_InsertNewPart" in have and "Assembly_CreateBom" in have:
        return
    try:
        import Assembly_rc  # noqa: F401
        import CommandInsertNewPart, CommandCreateBom, CommandCreateView  # noqa: F401
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly commands: %s\n" % error)


built = []          # (title, assembly?) at each open, for checks


def _part_insert(entries):
    ""
    out = []
    for e in entries:
        if isinstance(e, tuple) and e[0] == "Reference Geometry" and isinstance(e[1], tuple) and \
                not any(isinstance(x, tuple) and x[0] == "Mate Reference..." for x in e[1]):
            e = (e[0], tuple(e[1]) + (S, ("Mate Reference...", W("mate_reference"))))
        out.append(e)
    return tuple(out)


def _part_tools(entries):
    ""

    # Envelope Publisher is left out: a part has no subassembly to envelope, so it could only be greyed
    PUB = [("Asset Publisher...", W("asset_publisher"))]
    if any(isinstance(e, tuple) and e[0] == "Asset Publisher..." for e in entries):
        return entries
    out = list(entries)
    i = next((n for n, e in enumerate(out) if isinstance(e, tuple) and e[0] == "Xpress Products"), None)
    if i is None:
        j = next((n for n, e in enumerate(out) if isinstance(e, tuple) and e[0] == "Macro"), None)
        out[(j + 1 if j is not None else len(out)):(j + 1 if j is not None else len(out))] = [S] + PUB
    elif i + 1 < len(out) and out[i + 1] == S:
        out[i + 2:i + 2] = PUB
    else:
        out[i + 1:i + 1] = [S] + PUB + [S]
    out += [S, ROUTING_PART]
    if not any(isinstance(e, tuple) and e[0] == "Design Checker" for e in out):
        i = next((n + 1 for n, e in enumerate(out) if e == "FindModify"), None)
        if i is not None:
            out.insert(i, DESIGN_CHECKER)
        else:
            out += [DESIGN_CHECKER]

    out = [PART_FIND_MODIFY if e == "FindModify" else e for e in out]
    return tuple(out)


# the "fw:" entries other menus use by command name (interface's part Edit menu)
COMMANDS = {
    "SWStyle_CopyToIllustrator": ("obj:illustrator", "Copy to Adobe Illustrator", "The view as vector graphics on the clipboard"),
    "SWStyle_ObjectDisplayContent": ("obj:content", "Display Content", "The picked OLE objects show their content"),
    "SWStyle_ObjectDisplayIcon": ("obj:icon", "Display as Icon", "The picked OLE objects show as icons"),
    "SWStyle_ObjectResetSize": ("obj:reset", "Reset Size", "The picked OLE objects back to their own size"),
    "SWStyle_AssetPublisher": ("asset_publisher", "Asset Publisher...", "Adds connection points and mounting faces for a library part"),
    "SWStyle_EnvelopePublisher": ("envelope_publisher", "Envelope Publisher...", "Publishes components of a top-level assembly as envelopes in a subassembly"),
}


class _EntryCommand:
    def __init__(self, entry, label, tip):
        self.entry, self.label, self.tip = entry, label, tip

    def GetResources(self):
        return {"MenuText": self.label, "ToolTip": self.tip}

    def _it(self):
        try:
            return item(self.entry, self.label)
        except Exception as _fw_err:
            _fw_log("asmmenubar.py:1679", _fw_err)
            return None

    def IsActive(self):
        it = self._it()
        return bool(it is not None and it.enabled)

    def Activated(self):
        it = self._it()
        if it is not None and it.enabled and it.run is not None:
            it.run()


def register_commands():
    have = set(Gui.listCommands())
    for name, (entry, label, tip) in COMMANDS.items():
        if name not in have:
            Gui.addCommand(name, _EntryCommand(entry, label, tip))


def install():
    try:
        register_commands()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: menu bar commands: %s\n" % error)
    if getattr(swmenus, "_fw_asm", False):
        return
    opened0, resolve0 = swmenus._opened, swmenus.resolve

    def _opened(menu, title, entries):
        asm = _assembly()
        if asm is not None:
            load_assembly_commands()
            lists = menus()
            if title in lists:
                entries = lists[title][1]
        elif title == swmenus.INSERT[0]:
            entries = _part_insert(entries)
        elif title == swmenus.TOOLS[0]:
            entries = _part_tools(entries)
        elif title == swmenus.FILE[0] and _has_shapes(App.ActiveDocument):
            entries = _with_publish(entries)
        built.append((title, asm is not None))
        del built[:-50]
        return opened0(menu, title, entries)

    def resolve(shell, entry):
        if isinstance(entry, tuple) and len(entry) == 2 and isinstance(entry[1], str) and entry[1].startswith("fw:"):
            try:
                it = item(entry[1][3:], entry[0])
            except Exception as error:
                App.Console.PrintLog("FreeCAD: assembly menu %s: %s\n" % (entry[0], error))
                it = None
            return (it.label, it) if it is not None else None
        return resolve0(shell, entry)

    swmenus._opened, swmenus.resolve = _opened, resolve
    swmenus._fw_asm = True
    try:
        from . import asmrefgeom
        asmrefgeom.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: assembly reference geometry: %s\n" % error)
    try:
        from . import asmmagnet, asmsmart
        asmmagnet.install()
        try:
            from . import asmtabslot
            asmtabslot.install()            # Sheet Metal Tab and Slot across components
        except Exception as error:
            App.Console.PrintLog("FreeCAD: assembly Tab and Slot: %s\n" % error)
        asmsmart.install()
        from . import asmtabs
        asmtabs.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: magnetic mates: %s\n" % error)
    _patch_display_states()
