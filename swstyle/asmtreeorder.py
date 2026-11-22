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

ORDER_PROP = "FwTreeOrder"
PLANES = ("XY_Plane", "XZ_Plane", "YZ_Plane")


def order(asm):
    return list(getattr(asm, ORDER_PROP, None) or [])


def set_order(asm, names):
    if not hasattr(asm, ORDER_PROP):
        asm.addProperty("App::PropertyStringList", ORDER_PROP, "FreeCAD",
                        "The tree's row order (components and folders move freely)")
        asm.setPropertyStatus(ORDER_PROP, "Hidden")
    setattr(asm, ORDER_PROP, list(names))


def _key(node):
    o = node.obj
    if o is None:
        return None
    try:
        if getattr(o, "Role", "") in PLANES or o.TypeId == "App::Origin":
            return "Origin"
        return o.Name
    except Exception:
        return None


def blocks(part):
    """(head, [(key, [nodes])]): the fixed first rows and the movable blocks of the top rows."""
    head, out = [], []
    for node in part.children:
        key = _key(node)
        if key is None and not out:
            head.append(node)
            continue
        if key is None:
            key = "#%d" % len(out)
        if out and out[-1][0] == key:
            out[-1][1].append(node)
        else:
            out.append((key, [node]))
    return head, out


def arranged(keys, wanted):
    """keys (the default order) put in the wanted order; keys not in it stay after the key they
    followed by default."""
    listed = [k for k in wanted if k in keys]
    out = list(listed)
    for i, k in enumerate(keys):
        if k in listed:
            continue
        prev = next((keys[j] for j in range(i - 1, -1, -1) if keys[j] in out), None)
        out.insert(out.index(prev) + 1 if prev is not None else 0, k)
    return out


def apply(part, asm):
    """asmui.assembly_layout: the top rows in the assembly's saved order."""
    wanted = order(asm)
    if not wanted or part is None:
        return
    head, bl = blocks(part)
    keys = [k for k, _n in bl]
    by = dict(bl)
    new = arranged(keys, wanted)
    if new == keys:
        return
    part.children = []
    for node in head:
        part.add(node)
    for k in new:
        for node in by[k]:
            part.add(node)


def _component_names(asm):
    """The names of asm's components, once per pass of the event loop (asked per tree row)."""
    try:
        from . import tickcache
        return tickcache.get(("component_names", asm.Document.Name, asm.Name),
                             lambda: frozenset(c.Name for c in ac.components(asm)))
    except ImportError:
        return frozenset(c.Name for c in ac.components(asm))


def movable(obj, asm):
    """A top-level component, subassembly or component folder of asm."""
    from . import asmfolder
    if obj is None or asm is None:
        return False
    try:
        if asmfolder.is_component_folder(obj):
            return True
        return obj.Name in _component_names(asm) and asmfolder.component_folder_of(obj) is None
    except Exception:
        return False


def move(asm, part, objs, target_key, after):
    """Moves the rows of objs before (or after) the block target_key. Returns True when moved."""
    _head, bl = blocks(part)
    keys = [k for k, _n in bl]
    names = [o.Name for o in objs]
    if target_key not in keys or target_key in names:
        return False
    rest = [k for k in keys if k not in names]
    at = rest.index(target_key) + (1 if after else 0)
    new = rest[:at] + [n for n in names if n in keys] + rest[at:]
    if new == keys:
        return False
    doc = asm.Document
    if not hasattr(asm, ORDER_PROP):
        set_order(asm, [])      # pkg307: made before the step, so Ctrl+Z gives the old order back (not no list)
    doc.openTransaction("Reorder")
    try:
        set_order(asm, [k for k in new if not k.startswith("#")])
    finally:
        doc.commitTransaction()
    return True


def into_folder(folder, objs):
    from . import asmfolder
    comps = [o for o in objs if not asmfolder.is_component_folder(o)]
    if not comps:
        return False
    doc = folder.Document
    doc.openTransaction("Move to Folder")
    try:
        members = asmfolder.component_members(folder)
        setattr(folder, asmfolder.COMP_LIST_PROP, members + [c for c in comps if c not in members])
    finally:
        doc.commitTransaction()
    return True


def _target(model, row, parent):
    """(block key, after, folder) for a drop among the top rows, else None."""
    from . import asmfolder
    part = model.part
    node = model.node(parent) if parent.isValid() else model.root
    if node is None:
        return None
    if node is part:
        _head, bl = blocks(part)
        if not bl:
            return None
        if row < 0 or row >= len(part.children):
            return bl[-1][0], True, None
        tnode = part.children[row]
        key = _key(tnode)
        if key is None:          # above History etc.: before the first block
            return bl[0][0], False, None
        return key, False, None
    if node.parent is part:
        key = _key(node)
        if row < 0 and node.obj is not None and asmfolder.is_component_folder(node.obj):
            return key, False, node.obj
        if row < 0 and node.obj is not None and ac.is_subassembly(node.obj):
            return None          # dropped onto a subassembly: it goes into it (Restructure), not after it
        if row < 0 and key is not None:
            return key, True, None
    return None


def install():
    from . import fmtree
    M = fmtree.Model
    if getattr(M, "_fw_treeorder", False):
        return
    flags0, can0, drop0 = M.flags, M.canDropMimeData, M.dropMimeData
    from PySide import QtCore
    Qt = QtCore.Qt

    def _asm(self):
        doc = getattr(self, "doc", None)
        part = getattr(self, "part", None)
        asm = ac.assembly_of(doc) if doc is not None else None
        return asm if asm is not None and part is not None and part.obj is asm else None

    def flags(self, index):
        f = flags0(self, index)
        try:
            asm = _asm(self)
            if asm is not None and index.isValid():
                node = self.node(index)
                if node is not None and node.parent is self.part and not node.link:
                    if movable(node.obj, asm):
                        f |= Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
                    elif _key(node) is not None:
                        f |= Qt.ItemIsDropEnabled
                elif node is self.part:
                    f |= Qt.ItemIsDropEnabled
        except Exception as _fw_err:
            _fw_log("asmtreeorder.py:212", _fw_err)
        return f

    def _ours(self, data):
        asm = _asm(self)
        objs = self._dropped(data) if asm is not None else []
        return asm, objs if objs and all(movable(o, asm) for o in objs) else []

    def can(self, data, action, row, column, parent):
        try:
            asm, objs = _ours(self, data)
            if objs:
                t = _target(self, row, parent)
                if t is not None:
                    return True
        except Exception as _fw_err:
            _fw_log("asmtreeorder.py:228", _fw_err)
        return can0(self, data, action, row, column, parent)

    def drop(self, data, action, row, column, parent):
        try:
            asm, objs = _ours(self, data)
            if objs:
                t = _target(self, row, parent)
                if t is None:
                    return drop0(self, data, action, row, column, parent)
                key, after, folder = t
                done = into_folder(folder, objs) if folder is not None else move(asm, self.part, objs, key, after)
                if done:
                    self.soon()
                return False
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: reorder: %s\n" % error)
            return False
        return drop0(self, data, action, row, column, parent)

    M.flags, M.canDropMimeData, M.dropMimeData = flags, can, drop
    M._fw_treeorder = True
    # the saved order goes on the assembly's rows once asmui has laid them out
    from . import asmui
    layout0 = asmui.assembly_layout
    if not getattr(layout0, "_fw_treeorder", False):
        def assembly_layout(model, doc):
            done = layout0(model, doc)
            if done:
                try:
                    apply(model.part, ac.assembly_of(doc))
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: tree order: %s\n" % error)
            return done
        assembly_layout._fw_treeorder = True
        asmui.assembly_layout = assembly_layout
    _watch_undo()


class _UndoWatch:
    """pkg307: Undo and Redo of a Reorder change only the assembly's hidden order list, which the tree
    is not rebuilt for: the tree is laid out again after each Undo/Redo of an assembly document."""

    def _again(self, doc):
        try:
            if doc is not None and ac.assembly_of(doc) is not None:
                from PySide import QtCore
                QtCore.QTimer.singleShot(0, _relayout)
        except Exception as _fw_err:
            _fw_log("asmtreeorder.py:undo watch", _fw_err)

    def slotUndoDocument(self, doc):
        self._again(doc)

    def slotRedoDocument(self, doc):
        self._again(doc)


_WATCH = []


def _watch_undo():
    if not _WATCH:
        _WATCH.append(_UndoWatch())
        App.addDocumentObserver(_WATCH[0])


def _relayout():
    try:
        import FreeCADGui as Gui
        from PySide import QtWidgets
        from . import fmtree
        for view in Gui.getMainWindow().findChildren(QtWidgets.QTreeView):
            model = view.model()
            if isinstance(model, fmtree.Model):
                model.soon()
    except Exception as _fw_err:
        _fw_log("asmtreeorder.py:relayout", _fw_err)
