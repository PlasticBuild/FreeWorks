""


import FreeCAD as App
import FreeCADGui as Gui

PROP = "FWShowHierarchyOnly"
KEY = "ShowHierarchyOnly"
LABEL = "Show Hierarchy Only"

_FW_SEEN = set()


def _fw_log(site, err):
    if site not in _FW_SEEN:
        _FW_SEEN.add(site)
        App.Console.PrintLog("FreeCAD: %s: %s\n" % (site, err))


def _assembly(doc):
    try:
        from . import asmcore
        return asmcore.assembly_of(doc)
    except Exception:
        return None


def on(doc=None):
    asm = _assembly(doc or App.ActiveDocument)
    return bool(asm is not None and getattr(asm, PROP, False))


def toggle(doc=None):
    asm = _assembly(doc or App.ActiveDocument)
    if asm is None:
        return
    if not hasattr(asm, PROP):
        asm.addProperty("App::PropertyBool", PROP, "FreeCAD", LABEL)
        asm.setEditorMode(PROP, 2)
    setattr(asm, PROP, not bool(getattr(asm, PROP, False)))
    try:
        from . import swkeys
        swkeys.rebuild_trees()
    except Exception as err:
        _fw_log("hierarchyonly rebuild", err)


def menu_item(target):
    """(key, label, run, enabled) for the top assembly row; the same row turns it off again."""
    doc = getattr(target, "Document", None) or App.ActiveDocument
    return (KEY, LABEL, lambda d=doc: toggle(d), _assembly(doc) is not None)


def _component_row(obj):
    if obj is None:
        return False
    try:
        from . import asmmenu, asmfolder
        return bool(asmmenu.is_component(obj) or asmfolder.is_component_folder(obj))
    except Exception:
        return False


def apply(view):
    """Hide every row under the assembly that is not a component (or a folder of components); call after the
    FeatureManager filter ran. Nothing happens while it is off."""
    fm = getattr(view, "fm", None)
    if fm is None or getattr(fm, "part", None) is None:
        return
    doc = getattr(getattr(fm.part, "obj", None), "Document", None) or App.ActiveDocument
    if not on(doc):
        return
    part = fm.index_of(fm.part)

    def visit(parent):
        for row in range(fm.rowCount(parent)):
            index = fm.index(row, 0, parent)
            node = fm.node(index)
            keep = _component_row(getattr(node, "obj", None))
            if not keep:
                view.setRowHidden(row, parent, True)
            else:
                visit(index)
    if part.isValid():
        visit(part)
