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

from . import asmcore as ac

FOLDER_PROP = "FwMateFolder"
LIST_PROP = "FwMates"


class Folder:
    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderFolder:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        try:
            from pivy import coin
            vobj.addDisplayMode(coin.SoGroup(), "Default")     # a row with no display mode shows greyed
        except Exception as _fw_err:
            _fw_log("asmfolder.py:53", _fw_err)

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return ":/icons/folder.svg"

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_folder(obj):
    return obj is not None and bool(getattr(obj, FOLDER_PROP, False))


def folders(asm):
    return [o for o in ac.joint_group(asm).Group if is_folder(o)]


def members(folder):
    return [m for m in (getattr(folder, LIST_PROP, None) or []) if m is not None]


def folder_of(mate):
    asm = ac.assembly_of(mate.Document)
    if asm is None:
        return None
    return next((f for f in folders(asm) if mate in members(f)), None)


def _next_name(asm):
    taken = {o.Label for o in ac.joint_group(asm).Group}
    n = 1
    while "Folder%d" % n in taken:
        n += 1
    return "Folder%d" % n


def make_folder(asm, mates):
    """Folder<n> under Mates holding mates (taken out of any folder they were in)."""
    group = ac.joint_group(asm)
    folder = group.newObject("App::FeaturePython", "MateFolder")
    Folder(folder)
    folder.addProperty("App::PropertyBool", FOLDER_PROP, "FreeCAD", "A folder of mates")
    folder.setPropertyStatus(FOLDER_PROP, "Hidden")
    folder.addProperty("App::PropertyLinkListHidden", LIST_PROP, "FreeCAD", "The mates in the folder")
    setattr(folder, FOLDER_PROP, True)
    n = int(_next_name(asm)[6:])
    for k in range(n, n + 100):     # a name FreeCAD still holds (undo) comes back changed: the next one
        folder.Label = "Folder%d" % k
        if folder.Label == "Folder%d" % k:
            break
    if App.GuiUp and folder.ViewObject is not None:
        ViewProviderFolder(folder.ViewObject)
    for mate in mates:
        old = folder_of(mate)
        if old is not None:
            setattr(old, LIST_PROP, [m for m in members(old) if m is not mate])
    setattr(folder, LIST_PROP, list(mates))
    asm.Document.recompute()
    return folder


def dissolve(folder):
    """The folder goes; its mates stay in Mates."""
    folder.Document.removeObject(folder.Name)


def add_to_new_folder(mates):
    from . import asmmenu
    mates = [m for m in mates if m is not None]
    if not mates:
        return None
    asm = ac.assembly_of(mates[0].Document)
    doc = asm.Document
    doc.openTransaction("Add to New Folder")
    try:
        folder = make_folder(asm, mates)
    finally:
        doc.commitTransaction()
    asmmenu._refresh()
    return folder


def remove_folder(folder, label="Dissolve Folder"):
    from . import asmmenu
    doc = folder.Document
    doc.openTransaction(label)
    try:
        dissolve(folder)
    finally:
        doc.commitTransaction()
    asmmenu._refresh()


def lay_out(model, node, index, doc):
    """fmtree: the Mates folder's rows, each folder's mates under it (FreeCAD's own rows)."""
    from . import fmtree
    kids = [(i, fmtree._object(doc, i.data(0))) for i in model._children(index)]
    in_folders = {}
    for i, o in kids:
        if is_folder(o):
            for m in members(o):
                in_folders[m.Name] = o
    by_obj = {o.Name: i for i, o in kids if o is not None}
    for i, o in kids:
        if o is not None and o.Name in in_folders:
            continue
        child = model._mirror(node, i, doc, deep=not is_folder(o))
        if is_folder(o):
            for m in members(o):
                if m.Name in by_obj:
                    model._mirror(child, by_obj[m.Name], doc)


# ----------------------------------------------------------------------------- component folders
COMP_FOLDER_PROP = "FwComponentFolder"
COMP_LIST_PROP = "FwComponents"


def is_component_folder(obj):
    return obj is not None and bool(getattr(obj, COMP_FOLDER_PROP, False))


def component_folders(asm):
    return [o for o in asm.Group if is_component_folder(o)]


def component_members(folder):
    return [m for m in (getattr(folder, COMP_LIST_PROP, None) or []) if m is not None]


_FOLDER_OF = {}     # (document, assembly) -> (change count, {component name: folder})


def _folder_map(asm):
    """Each component's folder, kept while the document's change count (asmgen) stays the same:
    the tree asks for every row on every paint, and walking every folder for each row made
    opening a 300-component assembly seconds slower."""
    try:
        from . import asmgen
        g = asmgen.gen(asm.Document)
    except Exception:
        g = -1
    key = (asm.Document.Name, asm.Name)
    hit = _FOLDER_OF.get(key)
    if g >= 0 and hit is not None and hit[0] == g:
        return hit[1]
    out = {}
    for f in component_folders(asm):
        for c in component_members(f):
            out.setdefault(c.Name, f)
    if g >= 0:
        _FOLDER_OF[key] = (g, out)
    return out


def component_folder_of(comp):
    asm = ac.assembly_of(comp.Document)
    if asm is None:
        return None
    f = _folder_map(asm).get(comp.Name)
    if f is not None and comp in component_members(f):
        return f
    return None


def _next_comp_name(asm):
    taken = {o.Label for o in asm.Document.Objects}
    n = 1
    while "Folder%d" % n in taken:
        n += 1
    return "Folder%d" % n


def make_component_folder(asm, comps=()):
    ""


    folder = asm.newObject("App::FeaturePython", "ComponentFolder")
    Folder(folder)
    folder.addProperty("App::PropertyBool", COMP_FOLDER_PROP, "FreeCAD", "A folder of components")
    folder.setPropertyStatus(COMP_FOLDER_PROP, "Hidden")
    folder.addProperty("App::PropertyLinkListHidden", COMP_LIST_PROP, "FreeCAD", "The components in the folder")
    setattr(folder, COMP_FOLDER_PROP, True)
    folder.Label = _next_comp_name(asm)
    if App.GuiUp and folder.ViewObject is not None:
        ViewProviderFolder(folder.ViewObject)
    for comp in comps:
        old = component_folder_of(comp)
        if old is not None:
            setattr(old, COMP_LIST_PROP, [m for m in component_members(old) if m is not comp])
    setattr(folder, COMP_LIST_PROP, list(comps))
    asm.Document.recompute()
    return folder


def add_components_to_new_folder(comps, label="Add to New Folder"):
    from . import asmmenu
    comps = [c for c in comps if c is not None]
    if not comps:
        return None
    asm = ac.assembly_of(comps[0].Document)
    doc = asm.Document
    doc.openTransaction(label)
    try:
        folder = make_component_folder(asm, comps)
    finally:
        doc.commitTransaction()
    asmmenu._refresh()
    return folder


def create_new_folder(asm):
    from . import asmmenu
    doc = asm.Document
    doc.openTransaction("Create New Folder")
    try:
        folder = make_component_folder(asm, [])
    finally:
        doc.commitTransaction()
    asmmenu._refresh()
    return folder


def lay_out_components(model, part, rows, doc):
    """fmtree: the component rows, those in a folder under its row (FreeCAD's own rows).
    rows: [(index, object)] in tree order. Returns the rows it placed."""
    asm = ac.assembly_of(doc)
    placed = set()
    if asm is None:
        return placed
    by_name = {o.Name: i for i, o in rows if o is not None}
    for i, o in rows:
        if not is_component_folder(o):
            continue
        node = model._mirror(part, i, doc, deep=False)
        placed.add(o.Name)
        for m in component_members(o):
            if m.Name in by_name:
                model._mirror(node, by_name[m.Name], doc)
                placed.add(m.Name)
    return placed
