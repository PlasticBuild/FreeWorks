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

from . import rcmenus

T_PIN = "Pin Dialog"
T_REF_GEOMETRY = "Reference Geometry Display"
T_SHOW_HIDDEN = "Show Hidden Components"
T_TEMP_FIX = "Temporary Fix/Group"
T_MOVE = "Move Component"



# under the heading; Dissolve Subassembly after Form New Subassembly; Make Subassembly Flexible / Rigid is on the
# icon row (row 2), not in the menu (pkg211)
A1_COMPONENT = (("Hidden Tree Items", False), ("Save Part (in External File)", False),
                ("Save Assembly (in External File)", False), ("Make Virtual", False), ("Isolate", False),
                ("Configure Component", False), ("Add to Library", True), ("Component Display", False),
                ("Set to Lightweight", True), ("Float", False), ("Move with Triad", False), ("Add/Edit Mates", True), (T_TEMP_FIX, False),
                ("Form New Subassembly", False), ("Dissolve Subassembly", False), ("Reload", True), ("Replace Components", True),
                ("Make Independent", False), ("Copy with Mates", False), ("Add Configuration", True),
                ("Delete", False), ("Parent/Child", False), ("External References", False), (T_REF_GEOMETRY, False), ("Add to Favorites", False),
                ("Save Selection", False), ("Add to New Folder", False), ("Comment", False), ("Material", False))
A2_SKIP = ("Hidden Tree Items", "Save Selection", "Add to New Folder")
INNER_SKIP = ("Float", "Form New Subassembly", "Copy with Mates", "Make Independent", "Delete")

# inside a subassembly has no Fix or Float (read 11-19 A2: Move with Triad, Temporary Fix/Group, ..., Delete), pkg255
INNER_REACHED = ("Delete",)


def inner_skip(comp):
    """INNER_SKIP for this inner part, without Fix / Float and Delete when they reach the subassembly."""
    try:
        from . import asmmenu
        if asmmenu.inner_source(comp) is not None:
            return tuple(k for k in INNER_SKIP if k not in INNER_REACHED)
    except Exception:
        pass
    return INNER_SKIP
A1_TAIL = ("Create New Folder", "Rename tree item", "Hide/Show Tree Items", "Collapse Items")
ROW1 = ("Open Part", "Open Part in Position", "Open Drawing", "Edit Part", "Hide Components", "Change Transparency",
        "Suppress", "Mate", "View Mates", "Component Properties")
A1_ROW2 = ("ZoomSelection", "ComponentPreview", "EditAppearance")
A2_ROW2 = ("EditFeature", "EditAppearance", "CopyAppearance")
A2_ROW3 = ("SelectOther", "Sketch", "ZoomSelection", "ComponentPreview", "NormalTo", "Fillet", "Chamfer")
A3_ROW = ("BoxSelect", "LassoSelect", "SelectionFilter", "SelectOther", "Select", "MagnifiedSelection")
ALIASES = {"float": ("float", "fix"), "hide components": ("hide components", "show components"),
           "suppress": ("suppress", "resolve", "unsuppress"), "isolate": ("isolate", "isolate component"),
           "delete": ("delete", "delete component")}


def _norm(text):
    return (text or "").replace("&", "").rstrip(". ").strip().lower()


def _asm():
    try:
        from . import asmcore
        doc = Gui.ActiveDocument.Document if Gui.ActiveDocument is not None else App.ActiveDocument
        return asmcore.assembly_of(doc)
    except Exception:
        return None


def in_assembly():
    return _asm() is not None


# --------------------------------------------------------------------------- the commands
_POOLS = {}


def _pool(comp, long_form=True):
    """{normalised label: rcmenus.Item} of every command for comp, newest source first. Kept until the
    event loop runs again: one right-click asked for it twice (face items, then the component section)."""
    try:
        key = (comp.Document.Name, comp.Name, long_form)
    except Exception:
        key = None
    if key is not None and key in _POOLS:
        return dict(_POOLS[key])
    pool = _pool_now(comp, long_form)
    if key is not None:
        if not _POOLS:
            QtCore.QTimer.singleShot(0, _POOLS.clear)
        _POOLS[key] = dict(pool)
    return pool


def _pool_now(comp, long_form=True):
    from . import asmmenu
    pool = {}
    sh = rcmenus.shell()

    def put(key, label, run, enabled=True, short=False):
        if not key or not label or _norm(label) in pool:
            return
        if isinstance(run, (list, tuple)):     # a submenu: [(key, label, run, checked)] (Component Display)
            pool[_norm(label)] = rcmenus.submenu(key, label, [
                rcmenus.action(k, t, r, checked=c) for k, t, r, c in (tuple(x)[:4] for x in run)])
        elif hasattr(run, "fill"):
            pool[_norm(label)] = rcmenus.dynamic(key, label.rstrip("."), run.fill)
        else:
            pool[_norm(label)] = rcmenus.action(key, label, run, enabled=enabled and run is not None)
    fn = getattr(asmmenu, "sw_component_items", None)
    if fn is not None:
        try:
            for it in fn(comp, long_form):
                put(*it[:4])
        except Exception as error:
            App.Console.PrintLog("FreeCAD: sw_component_items: %s\n" % error)
    try:
        for key, label, run, enabled in asmmenu.component_items(comp):
            put(key, label, run, enabled)
    except Exception as _fw_err:
        _fw_log("asmviewmenu.py:133", _fw_err)
    try:
        from . import fmmenu
        for r in fmmenu.entries(sh, comp):
            if r[0] and r[0] not in ("-", "Customize"):
                put(*r[:4])
    except Exception as error:
        App.Console.PrintLog("FreeCAD: component tree entries: %s\n" % error)
    try:
        from . import fmmenu
        if "hidden tree items" not in pool:
            pool["hidden tree items"] = rcmenus.dynamic("HiddenTreeItems", "Hidden Tree Items", fmmenu._hidden_items_menu)
        part = _part_document(comp)
        if "material" not in pool and part is not None:
            pool["material"] = rcmenus.dynamic("Material", "Material", lambda m, d=part: fmmenu._material_menu(m, sh, d))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: component tree extras: %s\n" % error)
    if _norm(T_REF_GEOMETRY) not in pool:
        pool[_norm(T_REF_GEOMETRY)] = rcmenus.dynamic("ReferenceGeometryDisplay", T_REF_GEOMETRY,
                                                      lambda m, c=comp: fill_reference_geometry(m, c))
    return pool


def _part_document(comp):
    try:
        target = comp.getLinkedObject(True) if comp.TypeId == "App::Link" else comp
        return target.Document
    except Exception:
        return None


def _find(pool, label):
    n = _norm(label)
    for name in ALIASES.get(n, (n,)):
        if name in pool:
            return pool[name]
    for k, v in pool.items():
        if k.startswith(n):
            return v
    return None


def _short_set(comp):
    from . import asmmenu
    fn = getattr(asmmenu, "sw_component_items", None)
    if fn is None:
        return None
    try:
        return {_norm(it[1]) for it in fn(comp, False)}
    except Exception:
        return None


def component_section(comp, skip=(), long_only=()):
    pool = _pool(comp)
    out = [rcmenus.header("Component (%s)" % comp.Label.split("<")[0], "HeaderComponent")]
    for label, more in A1_COMPONENT:
        if label in skip:
            continue
        if label == "Move with Triad" and "float" in pool:
            continue
        it = _find(pool, label)
        if it is None or not getattr(it, "enabled", True):
            continue        # nothing greyed: an entry that cannot work on this component is left out (pkg208)
        if label == T_REF_GEOMETRY and not _ref_groups(comp)[1]:
            continue        # no planes, axes or origin to show
        it.more = more or label in long_only
        out.append(it)
    return out


def _ref_groups(comp):
    """(origin, [(name, objects)] that have something): the component's planes, axes and origin points."""
    try:
        target = comp.getLinkedObject(True) if comp.TypeId == "App::Link" else comp
    except Exception:
        return None, []
    origin = getattr(target, "Origin", None)
    feats = list(getattr(origin, "OriginFeatures", []) or [])
    groups = (("Planes", [f for f in feats if f.TypeId.endswith("Plane")]),
              ("Axes", [f for f in feats if f.TypeId.endswith("Line")]),
              ("Origins", [f for f in feats if f.TypeId.endswith("Point")]))
    return origin, [g for g in groups if g[1]]


def fill_reference_geometry(menu, comp):
    """Reference Geometry Display >: the component's planes, axes and origin shown or hidden (only the
    kinds it has: nothing greyed)."""
    origin, groups = _ref_groups(comp)
    for name, objs in groups:
        a = menu.addAction(name)
        a.setObjectName("SWToolMenu_RefGeom" + name)
        on = bool(objs) and all(getattr(o.ViewObject, "Visibility", False) for o in objs)
        a.setCheckable(True)
        a.setChecked(on)
        a.setEnabled(bool(objs))
        a.triggered.connect(lambda _c=False, o=objs, v=not on: _show(origin, o, v))


def _show(origin, objs, on):
    try:
        if on and origin is not None:
            origin.ViewObject.Visibility = True
        for o in objs:
            o.ViewObject.Visibility = on
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (T_REF_GEOMETRY, error))


# --------------------------------------------------------------------------- icon rows
def _entry_from(it, comp):
    from . import contextbar, rcextras
    if isinstance(it, contextbar.Entry):
        return it
    key, label, run, enabled = it[:4]
    icon = QtGui.QIcon()
    try:
        from . import asmmenu
        icon = asmmenu._icon(rcmenus.shell(), key)
    except Exception as _fw_err:
        _fw_log("asmviewmenu.py:241", _fw_err)
    if icon.isNull():
        icon = rcextras._icon(label)
    return contextbar.Entry(key, label, icon, rcextras._tip(label, comp.Label), run or (lambda: None),
                            bool(enabled) and run is not None)


def _catalog(keys, comp=None):
    from . import rcextras, partmenu, contextbar
    sh = rcmenus.shell()
    out = []
    for k in keys:
        if k == "SelectOther":
            out.append(partmenu._select_other_entry())
            continue
        if k == "SelectionFilter":
            out.append(contextbar.Entry(k, "Selection Filters", rcextras._icon("Selection Filter", "SELECTIONFILTER_FACES"),
                                        rcextras._tip("Selection Filters", "F5"), partmenu.selection_filter))
            continue
        e = rcextras._entry(sh, k)
        if e is not None and k == "EditAppearance":

            e = contextbar.Entry(e.key, "Appearances", e.icon, rcextras._tip("Appearances"), e.run, e.enabled)
        if e is not None:
            out.append(e)
    return out


def component_rows(comp):
    """(row 1: the 10 component icons, row 2 of the tree menu: Zoom to Selection, Component
    Preview Window, Appearances)."""
    from . import asmmenu
    fn = getattr(asmmenu, "sw_component_rows", None)
    if fn is not None:
        try:
            one, two = fn(comp)
            return [_entry_from(e, comp) for e in one], [_entry_from(e, comp) for e in two]
        except Exception as error:
            App.Console.PrintLog("FreeCAD: sw_component_rows: %s\n" % error)
    pool = {}
    try:
        for it in asmmenu.component_items(comp):
            pool[_norm(it[1])] = it
    except Exception as _fw_err:
        _fw_log("asmviewmenu.py:285", _fw_err)
    one = []
    for label in ROW1:
        found = None
        for name in ALIASES.get(_norm(label), (_norm(label),)):
            found = pool.get(name)
            if found:
                break
        if found is not None:
            one.append(_entry_from(found, comp))
        elif label == "Mate":
            one += _catalog(("Mate",))
        elif label == "Open Drawing":
            from . import contextbar, rcextras
            one.append(contextbar.Entry("OpenDrawing", label, rcextras._icon(label), rcextras._tip(label),
                                        lambda: Gui.runCommand("SWStyle_OpenDrawing", 0)))
    return one, _catalog(A1_ROW2)


# --------------------------------------------------------------------------- A1 tree
def tree_items(comp, view=None):
    pool = _pool(comp)
    out = [it for it in (_find(pool, "Invert Selection"), _find(pool, "Go To")) if it is not None]
    # the tree's short menu has no Move with Triad, even on a floating part (holds read: Pin shows
    # Fix, then Temporary Fix/Group); the long form keeps it, and the graphics area menu shows it
    out += component_section(comp, long_only=("Move with Triad",))
    out.append(rcmenus.separator())
    out += [it for it in (_find(pool, t) for t in A1_TAIL) if it is not None]
    return out


def show_tree_menu(comp, pos, view=None):
    one, two = component_rows(comp)
    b = rcmenus.Builder("AsmTreeComponent", tree_items(comp, view), row=(one, two, set()), chevron=True)
    return rcmenus.show(b, pos)


# --------------------------------------------------------------------------- A2 / A3 graphics area
def component_under(item):
    """The component of a graphics area pick (doc, root, sub, xyz), else None."""
    from . import asmcore
    asm = _asm()
    if asm is None or item is None:
        return None
    try:
        root = App.getDocument(item[0]).getObject(item[1])
        ref = asmcore.reference(asm, root, item[2]) if root is asm else None
        if ref is not None:
            return ref[0]
        first = item[2].split(".")[0]
        obj = asm.Document.getObject(first)
        return obj if obj in asmcore.components(asm) else None
    except Exception:
        return None


def _feature_of(item):
    """The part feature that made the picked face (in the part's own document)."""
    try:
        root = App.getDocument(item[0]).getObject(item[1])
        sub = item[2]
        leaf = sub.split(".")[-1]
        owner = root.getSubObject(sub[: len(sub) - len(leaf)], retType=1)
        if owner is not None and owner.TypeId == "App::Link":
            owner = owner.getLinkedObject(True)
        if owner is not None and owner.TypeId == "PartDesign::Body":
            from . import contextbar
            found = contextbar.owner_feature(owner, leaf)
            return found or owner.Tip
        return owner
    except Exception:
        return None


def _select_only(obj):
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj)


def face_items(item, comp, sub=None):
    from . import partextras as px, rcextras
    out = []
    leaf = item[2].split(".")[-1]
    try:
        from . import asmcore
        sub = sub if sub is not None else comp
        if asmcore.is_subassembly(sub) and item[2].count(".") >= 2:

            # first (pkg212); the rest of the menu is the part's (pkg213)
            out.append(rcmenus.action("SelectSubassembly", "Select Subassembly", lambda c=sub: _select_only(c)))
    except Exception as _fw_err:
        _fw_log("asmviewmenu.py:select-subassembly", _fw_err)
    if leaf.startswith("Face") and px.has_tangent(item):
        out.append(rcmenus.action("SelectTangency", rcmenus.T_SELECT_TANGENCY, lambda: px.select_face_tangency(item)))
    elif leaf.startswith("Edge"):
        # a component's edge: as on a part's edge (read 2 D2), with the component's section
        edge = item[:3]
        out += [rcmenus.action("SelectMidpoint", rcmenus.T_SELECT_MIDPOINT, lambda: rcmenus.select_edge_midpoint(edge)),
                rcmenus.action("SelectLoop", rcmenus.T_SELECT_LOOP, lambda: rcmenus.select_loop(edge)),
                rcmenus.action("ContourSelect", rcmenus.T_CONTOUR_SELECT, lambda: px.contour_select_tool(item), more=True)]
    elif leaf.startswith("Vertex"):
        out.append(rcmenus.action("SelectOther", rcmenus.T_SELECT_OTHER, rcmenus.select_other))
    out += [rcmenus.selection_tools_menu(), rcmenus.zoom_menu()]
    if not leaf.startswith("Vertex"):
        out.append(rcextras.set_view_menu(True))
    pool = _pool(comp)
    save = _find(pool, "Save Selection")
    if save is not None:
        out.append(save)
    inner = sub is not None and sub is not comp
    # a part inside a subassembly (pkg213): the entries that act on it from the top assembly; Form New Subassembly,
    # Copy with Mates and Make Independent do not reach a part inside the subassembly yet, so they are left out
    # rather than shown doing nothing (NO DEAD CONTROLS). Fix / Float and Delete reach it once the Assemblies
    # thread's asmmenu.inner_source is there (pkg270), and come back then (pkg215).
    out += component_section(comp, skip=A2_SKIP + (inner_skip(comp) if inner else ()))
    feature = _feature_of(item)
    if feature is not None and leaf.startswith("Face"):
        rows = {}
        try:
            from . import fmmenu
            rows = {r[0]: r for r in fmmenu.entries(rcmenus.shell(), feature) if r[0]}
        except Exception as _fw_err:
            _fw_log("asmviewmenu.py:388", _fw_err)
        out.append(rcmenus.header("Feature (%s)" % feature.Label, "HeaderFeature"))
        pc = rows.get("ParentChild")
        if pc is not None:
            out.append(rcmenus.action("FeatureParentChild", pc[1], pc[2], more=True))
        out.append(rcmenus.action("GoToFeature", px.T_GO_TO_FEATURE, lambda: px.go_to_feature(feature), more=True))
        fav = rows.get("Favorites")
        if fav is not None:
            out.append(rcmenus.action("FeatureFavorites", fav[1], fav[2]))
    if leaf.startswith("Face"):
        from . import partmenu
        out += [rcmenus.header("Face", "HeaderFace"),
                rcmenus.entry("Curvature", "Curvature", more=True),
                rcmenus.entry("Zebra", "Zebra Stripes...", more=True),
                rcmenus.entry("SurfaceCurvatureCombs", "Surface Curvature Combs..."),
                rcmenus.action("PlaneParallelToScreen", partmenu.T_PLANE_SCREEN,
                               lambda: partmenu.create_plane_parallel_to_screen(item)),
                rcmenus.action("FaceProperties", px.T_FACE_PROPERTIES, lambda: px.entity_properties(item, "Face"), more=True)]
    elif leaf.startswith("Edge"):
        from . import partmenu
        out += [rcmenus.header("Edge", "HeaderEdge"),
                rcmenus.action("EdgeProperties", px.T_EDGE_PROPERTIES, lambda: px.entity_properties(item, "Edge"), more=True),
                rcmenus.action("PlaneParallelToScreen", partmenu.T_PLANE_SCREEN,
                               lambda: partmenu.create_plane_parallel_to_screen(item))]
    return [i for i in out if i is not None]


A2_EDGE_ROW3 = ("SelectOther", "ZoomSelection", "ComponentPreview", "NormalTo", "Fillet", "Chamfer")


def face_rows(comp, leaf="Face"):
    one, _two = component_rows(comp)
    one = [e for e in one if getattr(e, "enabled", True)]       # nothing greyed: Open Part with no part file (pkg213)
    if leaf.startswith("Vertex"):
        return (one, [], set())         # a vertex: the component's line only (read 2 D3 has none of its own)
    if leaf.startswith("Edge"):

        return (one, _catalog(("EditAppearance",)), set(), _catalog(A2_EDGE_ROW3))      # (pkg212)
    return (one, [e for e in _catalog(A2_ROW2) if getattr(e, "enabled", True)], set(),
            [e for e in _catalog(A2_ROW3) if getattr(e, "enabled", True)])


def temporary_fix(comps=None):
    """Temporary Fix/Group on the picked components (asmmenu's), or a hint when none is picked."""
    from . import asmmenu, asmcore
    asm = _asm()
    comps = comps if comps is not None else [o for o in Gui.Selection.getSelection()
                                             if asm is not None and o in asmcore.components(asm)]
    if not comps:
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "Temporary Fix/Group: select the components to fix or group, then choose it again", 8000)
        except Exception as _fw_err:
            _fw_log("asmviewmenu.py:438", _fw_err)
        return False
    pool = _pool(comps[0])
    it = _find(pool, T_TEMP_FIX)
    if it is not None and it.run is not None:
        it.run()
        return True
    return False


def empty_items():
    from . import partmenu, partextras as px, rcextras
    out = [rcmenus.entry("ZoomFit", "Zoom to Fit"), rcmenus.entry("ZoomArea", "Zoom to Area"),
           rcmenus.action("ZoomInOut", "Zoom In/Out", lambda: partmenu.start_mode("zoom")),
           rcmenus.action("RotateView", "Rotate View", lambda: partmenu.start_mode("rotate")),
           rcmenus.action("Pan", "Pan", lambda: partmenu.start_mode("pan")),
           rcmenus.action("RollView", "Roll View", lambda: partmenu.start_mode("roll")),
           rcmenus.entry("RotateAboutSceneFloor", "Rotate About Scene Floor"),
           rcextras.set_view_menu(True),
           rcmenus.entry("ViewOrientation", "View Orientation..."),
           rcmenus.action("EditScene", "Edit Scene", partmenu.edit_scene),
           rcmenus.entry("ShowHiddenComponents", T_SHOW_HIDDEN),
           partmenu._command("SWStyle_OpenDrawing", "OpenDrawing", "Open Drawing"),
           rcmenus.entry("MoveComponent", T_MOVE, more=True),
           rcmenus.action("TemporaryFix", T_TEMP_FIX, temporary_fix),
           rcmenus.action("ContourSelect", rcmenus.T_CONTOUR_SELECT, px.contour_select_tool, more=True)]
    return [i for i in out if i is not None]


def empty_row():
    from . import partextras as px, contextbar, rcextras
    line = _catalog(A3_ROW)
    if px.has_previous():
        at = next((i for i, e in enumerate(line) if e.key == "SelectionFilter"), len(line) - 1) + 1
        line.insert(at, contextbar.Entry("PreviousSelection", px.T_PREVIOUS, rcextras._icon(px.T_PREVIOUS, "PREVIOUS_SELECTION", "FW_PreviousSelection"),
                                         rcextras._tip(px.T_PREVIOUS), px.previous_selection))
    return (line, [], {"Select"})


def edit_assembly_item():
    ""

    try:
        from . import asmtools
        e = asmtools.editing()
    except Exception:
        return None
    if not e:
        return None
    asm = e[0]
    label = getattr(getattr(asm, "Document", None), "Label", "") or getattr(asm, "Label", "")

    return rcmenus.action("EditAssembly", "Edit Assembly: %s" % label, asmtools.end_edit)


def _with_edit_assembly(items):
    back = edit_assembly_item()
    return ([back] if back is not None else []) + items


def show_view_menu(pos, item):
    """The graphics area menu in an assembly (partmenu calls it)."""
    from . import partmenu
    if item is None:
        return rcmenus.show(rcmenus.Builder("AsmEmpty", _with_edit_assembly(empty_items()), row=empty_row(),
                                            chevron=True), pos)
    comp = component_under(item)
    if comp is None:
        return None
    partmenu.pick(item)
    leaf = item[2].split(".")[-1]
    name = "AsmEdge" if leaf.startswith("Edge") else "AsmVertex" if leaf.startswith("Vertex") else "AsmFace"

    # (Component (Plate)), with Select Subassembly first for the subassembly itself (pkg213)
    target = inner_component(item, comp) or comp
    return rcmenus.show(rcmenus.Builder(name, _with_edit_assembly(face_items(item, target, sub=comp)),
                                        row=face_rows(target, leaf), chevron=True), pos)


def inner_component(item, comp):
    """The part a pick goes through inside the subassembly comp ("Sub.Part.Face1"), else None."""
    try:
        from . import asmcore
        parts = item[2].split(".")
        if not asmcore.is_subassembly(comp) or len(parts) < 3 or parts[0] != comp.Name:
            return None
        for holder in (comp, comp.getLinkedObject(True)):
            for o in getattr(holder, "Group", []) or []:
                if o.Name == parts[1]:
                    return o
        return None
    except Exception:
        return None


# --------------------------------------------------------------------------- A4 Mate PM
def mate_panel():
    try:
        from . import asmpm
        p = asmpm.OPEN
        return p if isinstance(p, asmpm.MatePanel) and Gui.Control.activeDialog() else None
    except Exception:
        return None


def pinned(panel):
    ""

    pin = getattr(panel, "pin", None)
    try:
        if pin is not None:
            return bool(pin.isChecked())
    except RuntimeError as _fw_err:
        _fw_log("asmviewmenu.py:532", _fw_err)
    return bool(getattr(panel, "fw_pinned", True))


def set_pinned(panel, on):
    panel.fw_pinned = bool(on)
    pin = getattr(panel, "pin", None)
    try:
        if pin is not None:
            pin.setChecked(bool(on))
    except RuntimeError as _fw_err:
        _fw_log("asmviewmenu.py:543", _fw_err)


def mate_pm_items(panel, ok, cancel):
    """Screen read 2, A4."""
    out = []
    try:
        from . import boxselect
        for kind in ("Box", "Lasso"):
            out.append(rcmenus.action(kind + "Select", "%s Selection" % kind, lambda k=kind: boxselect.set_bulk(k)))
    except Exception as _fw_err:
        _fw_log("asmviewmenu.py:554", _fw_err)
    out.append(rcmenus.action("ClearSelections", rcmenus.T_CLEAR, panel.drop))
    from . import partmenu
    item = partmenu.under_pointer()
    comp = component_under(item) if item is not None else None
    if comp is not None:
        out.append(rcmenus.action("SelectOther", rcmenus.T_SELECT_OTHER, rcmenus.select_other))
    style = QtWidgets.QApplication.style()
    out.append(rcmenus.action("OK", rcmenus.T_OK, ok, icon=style.standardIcon(QtWidgets.QStyle.SP_DialogApplyButton)))
    out.append(rcmenus.action("Cancel", rcmenus.T_CANCEL, cancel,
                              icon=style.standardIcon(QtWidgets.QStyle.SP_DialogCancelButton)))
    out.append(rcmenus.action("PinDialog", T_PIN, None, checked=pinned(panel), toggle=lambda on: set_pinned(panel, on)))
    if comp is not None:
        from . import asmmenu
        out.append(rcmenus.header("Component (%s)" % comp.Label.split("<")[0], "HeaderComponent"))
        out.append(rcmenus.action("HideComponent", "Hide", lambda: asmmenu.hide_show(comp)))
        if _ref_groups(comp)[1]:    # pkg227: no planes, axes or origin to show: no empty submenu
            out.append(rcmenus.dynamic("ReferenceGeometryDisplay", T_REF_GEOMETRY,
                                       lambda m, c=comp: fill_reference_geometry(m, c)))
    return out


# --------------------------------------------------------------------------- hooks
def install():
    """The tree menu of a component goes through show_tree_menu (fmmenu.show hook)."""
    from . import fmmenu
    if getattr(fmmenu, "_fw_asm_view_menu", False):
        return
    original = fmmenu.show

    def show(shell, target, global_pos, view=None, *more, **named):
        try:
            from . import asmmenu
            if not (QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier) and \
                    asmmenu.kind(target) == "component":
                if not Gui.Selection.isSelected(target):
                    Gui.Selection.clearSelection()
                    Gui.Selection.addSelection(target)
                menu = show_tree_menu(target, global_pos, view)
                if menu is not None:
                    fmmenu.LAST[0] = menu
                    return menu
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: component menu: %s\n" % error)
        return original(shell, target, global_pos, view, *more, **named)

    fmmenu.show = show
    fmmenu._fw_asm_view_menu = True
    try:
        hook_component_bar()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: component context toolbar: %s\n" % error)


# ----------------------------------------------------------------------------- the pick's context toolbar
def bar_for(comp, leaf=None):
    """The left-click context toolbar of a component: the icons over its shortcut menu (read 2
    A1 in the tree, A2/D2/D3 in the graphics area), in one row, without Select Other."""
    if leaf:
        rows = face_rows(comp, leaf)
        lines = [rows[0], rows[1]] + (list(rows[3:4]) if len(rows) > 3 else [])
    else:
        one, two = component_rows(comp)
        lines = [one, two]
    out = []
    for line in lines:
        out += [e for e in line if getattr(e, "key", "") != "SelectOther"]
    return out


def _picked_leaf():
    try:
        sels = Gui.Selection.getSelectionEx("", 0)
        subs = [s for s in sels[0].SubElementNames if s] if len(sels) == 1 else []
        return subs[0].split(".")[-1] if len(subs) == 1 else None
    except Exception:
        return None


def hook_component_bar():
    from . import contextbar, asmmenu
    asmmenu.install()           # theirs first (row_entries); this one wraps it
    if getattr(contextbar, "_fw_asm_view_bar", False):
        return
    original_part = contextbar.part_entries

    def part_entries(shell, obj, sub, *more, **named):
        try:
            if asmmenu.kind(obj) == "component":
                return bar_for(obj, (sub or "").split(".")[-1] or None)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: component bar: %s\n" % error)
        return original_part(shell, obj, sub, *more, **named)

    original_sel = contextbar.entries_for_selection

    def entries_for_selection(shell, *more, **named):
        try:
            if contextbar.sketch_in_edit() is None and not contextbar.dialog_open() \
                    and not contextbar.tool_running(shell):
                comp = asmmenu.picked_component()
                if comp is not None:
                    return "part", bar_for(comp, _picked_leaf())
        except Exception as error:
            App.Console.PrintLog("FreeCAD: component bar: %s\n" % error)
        return original_sel(shell, *more, **named)

    contextbar.part_entries = part_entries
    contextbar.entries_for_selection = entries_for_selection
    contextbar._fw_asm_view_bar = True
