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


import weakref

import FreeCAD as App
import FreeCADGui as Gui

SKETCH = "Sketcher::SketchObject"
ICON = "BLOCK_MAKE"
_rows = weakref.WeakKeyDictionary()      # tree node -> (doc name, sketch name, block name)


def children(sketch, parent=None):
    """[(text, tooltip, block name)] for the blocks of sketch, in the order they were made: those
    of the sketch itself, or with parent (a block's name) those nested right inside that block."""
    if sketch is None or getattr(sketch, "TypeId", "") != SKETCH:
        return []
    try:
        from . import blocks
        recs = blocks.records(sketch)
    except Exception:
        return []
    names = {r["name"] for r in recs}
    return [(_text(sketch, r), "Block %s (%s)%s" % (r["name"], r.get("definition", ""),
                                                   ", hidden" if blocks.is_hidden(r) else ""), r["name"])
            for r in recs if (r.get("parent") if r.get("parent") in names else None) == parent]


def _text(sketch, rec):
    ""
    from . import blocks
    try:
        loose = blocks.under_defined(sketch, rec)
    except Exception:
        loose = None
    return ("(-) " if loose else "") + rec["name"]


def menu(node, pos, parent=None):
    ""

    entry = _rows.get(node)
    if entry is None:
        return False
    from PySide import QtWidgets
    from . import blocks
    doc_name, sketch_name, name = entry
    try:
        sketch = App.getDocument(doc_name).getObject(sketch_name)
    except Exception:
        return True
    rec = next((r for r in blocks.records(sketch) if r["name"] == name), None) if sketch is not None else None
    if rec is None:
        return True
    m = QtWidgets.QMenu(parent)
    m.setObjectName("SWBlockRowMenu")
    hidden = blocks.is_hidden(rec)
    act = m.addAction("Show" if hidden else "Hide")
    act.setObjectName("SWBlockRowHideShow")
    act.triggered.connect(lambda: blocks.set_hidden(sketch, name, not hidden))
    try:
        from . import contextbar
        editing = contextbar.sketch_in_edit() is sketch
    except Exception:
        editing = False
    if editing:
        m.addSeparator()
        for text, cmd in (("Edit Block", "SWStyle_EditBlock"), ("Save Block...", "SWStyle_SaveBlock"),
                          ("Explode Block", "SWStyle_ExplodeBlock")):
            a = m.addAction(text)
            a.triggered.connect(lambda checked=False, c=cmd: (picked(node), Gui.runCommand(c, 0)))
    _LAST[:] = [m]
    m.popup(pos)
    return True


_LAST = []          # the block row menu shown last (tests)


def icon():
    try:
        from . import icons
        i = icons.family(ICON)
        if not i.isNull():
            return i
    except Exception as _fw_err:
        _fw_log("sketchblocktree.py:105", _fw_err)
    try:
        return Gui.getIcon("Sketcher_CreateBlock") if hasattr(Gui, "getIcon") else None
    except Exception:
        return None


def remember(node, sketch, name):
    _rows[node] = (sketch.Document.Name, sketch.Name, name)


def add_rows(model, node, node_class):
    """fmtree hook: block rows under the sketch row node (node.obj is the sketch)."""
    sketch = getattr(node, "obj", None)
    rows = children(sketch)
    if not rows:
        return
    ic = icon()

    def put(under, rows, depth=0):
        for text, tip, name in rows:
            child = under.add(node_class(text=text, icon=ic, tip=tip))
            remember(child, sketch, name)
            if depth < 16:
                put(child, children(sketch, name), depth + 1)     # nested blocks under their block
    put(node, rows)


def is_block_row(node):
    return node in _rows


def picked(node):
    """A click on a block row: its entities are selected. True when node is a block row."""
    entry = _rows.get(node)
    if entry is None:
        return False
    doc_name, sketch_name, name = entry
    try:
        doc = App.getDocument(doc_name)
        sketch = doc.getObject(sketch_name)
        from . import blocks
        rec = next((r for r in blocks.records(sketch) if r["name"] == name), None)
        if rec is None:
            return True
        geos, _base = blocks.indices(sketch, rec)
        Gui.Selection.clearSelection()
        for g in geos:
            Gui.Selection.addSelection(doc_name, sketch_name, "Edge%d" % (g + 1))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: block row: %s\n" % error)
    return True


def changed(sketch=None):
    """blocks.py: the records changed; the feature tree rebuilds its rows soon."""
    try:
        from . import sketchtoolpm
        shell = sketchtoolpm._shell()
        fmgr = getattr(shell, "feature_manager", None)
        view = getattr(fmgr, "view", None)
        model = getattr(view, "fm", None)
        if model is not None:
            model.soon()
    except Exception as _fw_err:
        _fw_log("sketchblocktree.py:170", _fw_err)
