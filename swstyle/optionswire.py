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

THIN = ("Display", "Optimize for thin parts", True)
SCROLL = ("Display", "Display scrollbars in graphics view for drawings", True)
PROXIMITY = ("Performance", "Magnetic mate proximity", "More")
PROXIMITY_SCALE = {"Less": 0.4, "Medium": 0.7, "More": 1.0}
REF_KIND = ("External References", "Reference component type", "Any component")
REF_CONTEXT = ("External References", "In the context of", "Top level assembly")
DESIGN_TABLE = "Excel Design Table"
THIN_FACTOR = 0.2
THIN_NAME = "SWThinParts"
_state = {"installed": False, "observer": None, "mdi": None}


def kept(row):
    from . import optionspages
    page, text, default = row
    try:
        return optionspages.stored(page, text, default)
    except Exception as _fw_err:
        _fw_log("optionswire.kept", _fw_err)
        return default


def set_kept(row, value):
    from . import optionspages
    optionspages.set_stored(row[0], row[1], value)


# ---------------------------------------------------------------- Display: Optimize for thin parts
def _offsets(vobj):
    from pivy import coin
    sa = coin.SoSearchAction()
    sa.setType(coin.SoPolygonOffset.getClassTypeId())
    sa.setInterest(coin.SoSearchAction.ALL)
    sa.apply(vobj.RootNode)
    paths = sa.getPaths()
    return [paths[i].getTail() for i in range(paths.getLength())]


def apply_thin_object(obj, on=None):
    """The part's own face offset (FreeCAD's 1, 1) set for thin parts or back; others left alone."""
    vobj = getattr(obj, "ViewObject", None)
    if vobj is None or not obj.isDerivedFrom("Part::Feature"):
        return 0
    on = bool(kept(THIN)) if on is None else on
    n = 0
    for node in _offsets(vobj):
        name = str(node.getName())
        if name not in ("", THIN_NAME) or abs(node.units.getValue() - 1.0) > 1e-6:
            continue
        f = node.factor.getValue()
        if abs(f - 1.0) > 1e-6 and abs(f - THIN_FACTOR) > 1e-6:
            continue
        node.factor.setValue(THIN_FACTOR if on else 1.0)
        node.setName(THIN_NAME)
        n += 1
    return n


def apply_thin(doc=None, on=None):
    n = 0
    for d in ([doc] if doc is not None else App.listDocuments().values()):
        for obj in d.Objects:
            try:
                n += apply_thin_object(obj, on)
            except Exception as _fw_err:
                _fw_log("optionswire.thin", _fw_err)
    return n


class _Observer:
    def slotCreatedObject(self, obj):
        from PySide import QtCore
        doc, name = obj.Document.Name, obj.Name

        def later():
            try:
                o = App.getDocument(doc).getObject(name)
            except Exception:
                return
            if o is not None:
                try:
                    apply_thin_object(o)
                except Exception as _fw_err:
                    _fw_log("optionswire.thin-new", _fw_err)
        QtCore.QTimer.singleShot(0, later)

    def slotFinishRestoreDocument(self, doc):
        from PySide import QtCore
        name = doc.Name

        def later():
            try:
                apply_thin(App.getDocument(name))
            except Exception as _fw_err:
                _fw_log("optionswire.thin-open", _fw_err)
        QtCore.QTimer.singleShot(0, later)


# ---------------------------------------------------------------- Display: scroll bars on drawings
def drawing_views():
    from PySide import QtWidgets
    try:
        import FreeCADGui as Gui
        mw = Gui.getMainWindow()
    except Exception:
        return []
    return [v for v in mw.findChildren(QtWidgets.QGraphicsView)
            if v.metaObject().className() == "TechDrawGui::QGVPage"]


def apply_scrollbars():
    from PySide import QtCore
    policy = QtCore.Qt.ScrollBarAsNeeded if kept(SCROLL) else QtCore.Qt.ScrollBarAlwaysOff
    views = drawing_views()
    for v in views:
        if v.horizontalScrollBarPolicy() != policy:
            v.setHorizontalScrollBarPolicy(policy)
        if v.verticalScrollBarPolicy() != policy:
            v.setVerticalScrollBarPolicy(policy)
    return len(views)


def _watch_windows():
    from PySide import QtCore, QtWidgets
    try:
        import FreeCADGui as Gui
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    except Exception:
        mdi = None
    if mdi is None or _state["mdi"] is mdi:
        return
    _state["mdi"] = mdi
    mdi.subWindowActivated.connect(lambda _w=None: QtCore.QTimer.singleShot(0, _safe_scrollbars))


def _safe_scrollbars():
    try:
        apply_scrollbars()
    except Exception as _fw_err:
        _fw_log("optionswire.scrollbars", _fw_err)


# ---------------------------------------------------------------- Display: SpeedPak circle Off
def _patch_speedpak():
    from . import asmoptions
    if getattr(asmoptions, "_fw_speedpak_off", False):
        return
    base = asmoptions.speedpak_opacity

    def speedpak_opacity():
        try:
            if asmoptions._p().GetInt(asmoptions.SPEEDPAK_OPACITY, 100) <= 0:
                return 0            # the slider's Off stop
        except Exception as _fw_err:
            _fw_log("optionswire.speedpak", _fw_err)
        return base()
    asmoptions.speedpak_opacity = speedpak_opacity
    asmoptions._fw_speedpak_off = True


# ---------------------------------------------------------------- Performance: magnetic mate proximity
def proximity_scale():
    return PROXIMITY_SCALE.get(str(kept(PROXIMITY)), 1.0)


def _patch_magnet():
    from . import asmmagnet
    if getattr(asmmagnet, "_fw_proximity", False):
        return
    base = asmmagnet.snap_distance

    def snap_distance(comp):
        return base(comp) * proximity_scale()
    asmmagnet.snap_distance = snap_distance
    asmmagnet._fw_proximity = True


# ---------------------------------------------------------------- External References: which components
def _parent(asm, comp, depth=0):
    """The assembly (or subassembly component) whose own components include comp, or None."""
    from . import asmcore as ac
    try:
        comps = ac.components(asm)
    except Exception:
        return None
    if comp in comps:
        return asm
    if depth > 6:
        return None
    for c in comps:
        if ac.is_subassembly(c):
            got = _parent(c, comp, depth + 1)
            if got is not None:
                return got
    return None


def refused(asm, edited, other):
    """Why a part edited in context may not take a reference from other (None: it may)."""
    if other is None or edited is None or other is edited:
        return None
    if kept(REF_KIND) == "Only envelope component":
        try:
            from . import asminsert
            envelope = asminsert.is_envelope(other)
        except Exception:
            envelope = False
        if not envelope:
            return ("%s is not an envelope component. Reference component type is set to Only envelope "
                    "component (Options, External References)." % other.Label)
    if kept(REF_CONTEXT) == "Same subassembly":
        mine, theirs = _parent(asm, edited), _parent(asm, other)
        if mine is not None and theirs is not mine:
            return ("%s is not in the same subassembly as %s. In the context of is set to Same subassembly "
                    "(Options, External References)." % (other.Label, edited.Label))
    return None


def _say(text):
    App.Console.PrintWarning("FreeCAD: %s\n" % text)
    try:
        import FreeCADGui as Gui
        Gui.getMainWindow().statusBar().showMessage(text, 8000)
    except Exception as _fw_err:
        _fw_log("optionswire.say", _fw_err)


def _edited():
    try:
        from . import asmtools
        ed = asmtools.editing()
        return (ed[0], ed[1]) if ed else (None, None)
    except Exception:
        return None, None


def _patch_references():
    from . import asmextref, asmincontext
    if getattr(asmextref, "_fw_ref_rules", False):
        return
    sketch0 = asmextref.sketch_on_reference

    def sketch_on_reference(asm, comp, other, sub):
        why = refused(asm, comp, other)
        if why:
            try:
                from . import asmrefopts
                asmrefopts.message(why)
            except Exception:
                _say(why)
            return None, None
        return sketch0(asm, comp, other, sub)
    asmextref.sketch_on_reference = sketch_on_reference

    items0 = asmextref.in_context_items

    def in_context_items(sketch, obj, name, detach=True):
        asm, comp = _edited()
        why = refused(asm, comp, obj) if asm is not None else None
        if why:
            _say(why)
            return []
        return items0(sketch, obj, name, detach)
    asmextref.in_context_items = in_context_items

    pick0 = asmincontext.map_pick

    def map_pick(obj, sub=""):
        ctx = asmincontext._context()
        if ctx is not None:
            asm, comp, _body = ctx
            try:
                other = asmincontext._component_of(asm, obj, sub)
            except Exception:
                other = None
            why = refused(asm, comp, other)
            if why:
                _say(why)
                return obj
        return pick0(obj, sub)
    asmincontext.map_pick = map_pick
    asmextref._fw_ref_rules = True


# ---------------------------------------------------------------- File Locations
def _folders(kind):
    from . import optionspages
    try:
        return [f for f in optionspages.folders(kind) if f]
    except Exception:
        return []


def first_folder(kind):
    for f in _folders(kind):
        try:
            os.makedirs(f, exist_ok=True)
            return f
        except OSError as _fw_err:
            _fw_log("optionswire.folder", _fw_err)
    return ""


def material_default():
    return os.path.join(App.getResourceDir(), "Mod", "Material", "Resources", "Materials")


def sheet_default():
    return os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates")


def folders_changed(kind, values):
    """File Locations saved: hand the folders to what reads them."""
    values = [v for v in values if v]
    if kind == "Sheet Formats":
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Files")
        if values:
            p.SetString("TemplateDir", values[0])
        else:
            p.RemString("TemplateDir")
    elif kind == "Material Databases":
        own = [v for v in values if os.path.normcase(os.path.normpath(v)) !=
               os.path.normcase(os.path.normpath(material_default()))]
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Material/Resources")
        p.SetBool("UseMaterialsFromCustomDir", bool(own))
        if own:
            p.SetString("CustomMaterialsDir", own[0])
    elif kind == "Design Library":
        from . import designlib
        App.ParamGet(designlib.PARAM).SetString("Root", values[0] if values else "")
    elif kind == "Bend Tables":
        _bend_folder()


def _bend_folder():
    from . import smbendtable
    if not hasattr(smbendtable, "_fw_folder0"):
        smbendtable._fw_folder0 = smbendtable.FOLDER
    own = first_folder("Bend Tables")
    # FOLDER is joined to the user data folder; an absolute path replaces it in that join
    smbendtable.FOLDER = own or smbendtable._fw_folder0


def _patch_decals():
    from . import decalpm
    if getattr(decalpm, "_fw_folder", False):
        return
    base = decalpm.user_folder

    def user_folder():
        return first_folder("Decals") or base()
    decalpm.user_folder = user_folder
    decalpm._fw_folder = True


def extra_template_tabs():
    """[(tab, [(label, path)])] from the Document Templates folders: each sub-folder is a tab, files
    straight in a folder go on a tab named after it."""
    out = []
    for folder in _folders("Document Templates"):
        if not os.path.isdir(folder):
            continue
        groups = [(os.path.basename(os.path.normpath(folder)) or folder, folder)]
        try:
            groups += [(n, os.path.join(folder, n)) for n in sorted(os.listdir(folder))
                       if os.path.isdir(os.path.join(folder, n))]
        except OSError as _fw_err:
            _fw_log("optionswire.templates", _fw_err)
        for tab, path in groups:
            try:
                files = [(os.path.splitext(f)[0], os.path.join(path, f)) for f in sorted(os.listdir(path))
                         if f.lower().endswith(".fcstd")]
            except OSError:
                files = []
            if files:
                out.append((tab, files))
    return out


def _patch_templates():
    from . import newdoc
    if getattr(newdoc, "_fw_template_folders", False):
        return
    base = newdoc.template_tabs

    def template_tabs():
        tabs = base()
        names = [t for t, _e in tabs]
        for tab, entries in extra_template_tabs():
            if tab in names:
                held = tabs[names.index(tab)][1]
                held += [e for e in entries if e not in held]
            else:
                tabs.append((tab, entries))
                names.append(tab)
        return tabs
    newdoc.template_tabs = template_tabs
    newdoc._fw_template_folders = True


# ---------------------------------------------------------------- FeatureManager: Excel Design Table
def is_design_table(obj):
    return (getattr(obj, "TypeId", "") == "Spreadsheet::Sheet" and
            str(getattr(obj, "Label", "")).startswith("Design Table"))


def _patch_tree():
    from . import fmmenu, fmtree
    items = list(fmmenu.TREE_ITEMS)
    if DESIGN_TABLE not in [n for n, _d in items]:
        at = next((i + 1 for i, (n, _d) in enumerate(items) if n == "Mate References"), len(items))
        items.insert(at, (DESIGN_TABLE, "Automatic"))
        fmmenu.TREE_ITEMS = tuple(items)
    if getattr(fmtree, "_fw_design_table", False):
        return
    base = fmtree._tree_item_name

    def _tree_item_name(node):
        obj = getattr(node, "obj", None)
        if obj is not None and getattr(node, "src", None) is not None and is_design_table(obj):
            from . import paths
            # Automatic and Show both keep it (the row is there only when the part has a table)
            return DESIGN_TABLE if paths.params().GetString("TreeItem." + DESIGN_TABLE, "Automatic") == "Hide" else None
        return base(node)
    fmtree._tree_item_name = _tree_item_name
    fmtree._fw_design_table = True


# ---------------------------------------------------------------- after Options OK, and at start
def apply_edge_styles():
    """Hidden edges displayed as / Edge display in shaded with edges mode: the open view redraws with the
    choice (it was read only when a style was picked)."""
    from . import hlv
    from . import optionspages as op
    h = hlv.HIDDEN
    if h.mode == "hlv":
        h.draw()                    # Solid or Dashed hidden edges
        return
    shaded_edges = op.stored("Radio", "ShadedEdges", "HLR")
    if h.mode == "swe" and shaded_edges != "Wireframe":
        h.set(False)
    elif h.mode is None and shaded_edges == "Wireframe":
        import FreeCADGui as Gui
        try:        # Shaded With Edges is FreeCAD's Flat lines style, checked in the Std_DrawStyle group
            actions = Gui.Command.get("Std_DrawStyle").getAction()
            if actions[hlv.FLAT_LINES].isChecked():
                h.set("swe")
        except Exception as _fw_err:
            _fw_log("optionswire.edgestyle", _fw_err)


def refresh():
    for fn in (apply_thin, _watch_windows, apply_scrollbars, _bend_folder, apply_edge_styles):
        try:
            fn()
        except Exception as _fw_err:
            _fw_log("optionswire.refresh." + fn.__name__, _fw_err)


def install():
    if _state["installed"]:
        return
    _state["installed"] = True
    for fn in (_patch_speedpak, _patch_magnet, _patch_references, _patch_decals, _patch_templates, _patch_tree,
               _bend_folder, _watch_windows):
        try:
            fn()
        except Exception as _fw_err:
            _fw_log("optionswire.install." + fn.__name__, _fw_err)
    if _state["observer"] is None:
        _state["observer"] = _Observer()
        App.addDocumentObserver(_state["observer"])
        try:        # FreeCAD 1.1 sends no restore signal: the hook reports opened files
            from . import restorehook
            restorehook.on_restored(_opened, 200)
        except Exception as _fw_err:
            _fw_log("optionswire.restore", _fw_err)
    refresh()


def _opened(doc):
    try:
        apply_thin(doc)
    except Exception as _fw_err:
        _fw_log("optionswire.opened", _fw_err)
