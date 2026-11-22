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

MIME = "application/x-freeworks-features"


# ----------------------------------------------------------------------------- the model
def _value(j):
    kind = ac.mate_type(j)
    if kind == "Distance":
        return ac.distance_value(j)
    if kind == "Angle":
        return getattr(j, "Angle", None)
    return None


def _refs(j):
    out = []
    for p in ("Reference1", "Reference2"):
        r = getattr(j, p, None)
        if not r:
            return None
        out.append((r[0], r[1][0] if r[1] else ""))
    return out


def _remake(asm, j, refs):
    try:
        return ac.add_mate(asm, ac.mate_type(j), refs[0], refs[1], value=_value(j), name=j.Label.split(" (")[0],
                           side=ac.distance_side(j) if ac.mate_type(j) == "Distance" else None)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: restructure, mate %s: %s\n" % (j.Label, error))
        return None


def holder(obj):
    """The subassembly component (in the top document) that obj sits in, else None."""
    for p in getattr(obj, "InList", []) or []:
        if ac.is_subassembly(p) and obj in ac.sub_components(p):
            return p
    return None


def _source_of(sub, inner):
    """The subassembly file's own component that inner (this document's copy) shows."""
    src = getattr(sub, "LinkedObject", None)
    if src is None:
        return None
    mine = ac.sub_components(sub)
    theirs = ac.components(src)
    if inner in mine and mine.index(inner) < len(theirs):
        return theirs[mine.index(inner)]
    return None


def _inner_of(sub, source_comp):
    src = getattr(sub, "LinkedObject", None)
    if src is None:
        return None
    theirs = ac.components(src)
    mine = ac.sub_components(sub)
    if source_comp in theirs and theirs.index(source_comp) < len(mine):
        return mine[theirs.index(source_comp)]
    return None


def _global(asm, comp):
    from . import asmexplode as ax
    try:
        return ax.gplacement(comp)
    except Exception:
        return App.Placement(comp.Placement)


def reorder(asm, comps, target, after=False):
    """Reorder: comps go just before (after) target in the tree."""
    group = list(asm.Group)
    if target in comps or target not in group:
        return False
    keep = [o for o in group if o not in comps]
    i = keep.index(target) + (1 if after else 0)
    moved = [o for o in group if o in comps]
    new = keep[:i] + moved + keep[i:]
    if new == group:
        return False
    asm.Group = new
    return True


def reorder_inside(sub, inners, target, after=False):
    """Reorder inside a subassembly: in its own file (this document's copies follow)."""
    src = getattr(sub, "LinkedObject", None)
    a = [_source_of(sub, i) for i in inners]
    t = _source_of(sub, target)
    if src is None or t is None or None in a:
        return False
    done = reorder(src, a, t, after)
    if done:
        src.Document.recompute()
        sub.Document.recompute()
    return done


def move_into(asm, comps, sub):
    """Components of asm move into the subassembly component sub, where they are now."""
    src = getattr(sub, "LinkedObject", None)
    comps = [c for c in comps if c is not sub and c in ac.components(asm)]
    if src is None or not comps:
        return []
    doc = asm.Document
    fixed = ac.grounded(asm)
    sub_g = App.Placement(sub.Placement)
    made = {}
    for c in comps:
        target = c.LinkedObject if c.TypeId in ("App::Link", "Assembly::AssemblyLink") else c
        link = ac.insert(src, target, sub_g.inverse().multiply(c.Placement))
        link.Placement = sub_g.inverse().multiply(c.Placement)
        made[c] = link
        if c in fixed:
            ac.fix(src, link)
    keep, inside = [], []
    for j in list(ac.mates(asm)):
        refs = _refs(j)
        if refs is None or not any(r[0] in made for r in refs):
            continue
        if all(r[0] in made for r in refs):
            inside.append((j, [(made[r[0]], r[1]) for r in refs]))
        else:
            keep.append((j, refs))
    for j, refs in inside:
        _remake(src, j, refs)
    src.Document.recompute()
    try:
        ac.solve(src)
    except Exception as _fw_err:
        _fw_log("asmrestructure.py:163", _fw_err)
    for c in comps:
        if c in fixed:
            doc.removeObject(fixed[c].Name)
    doc.recompute()                     # the subassembly's copies of its new components
    for j, refs in keep:
        new = []
        for owner, path in refs:
            if owner in made:
                inner = _inner_of(sub, made[owner])
                if inner is None:
                    new = None
                    break
                new.append((sub, inner.Name + "." + path))
            else:
                new.append((owner, path))
        if new:
            _remake(asm, j, new)
    for j, _r in inside + keep:
        if doc.getObject(j.Name) is not None:
            doc.removeObject(j.Name)
    for c in comps:
        doc.removeObject(c.Name)
    doc.recompute()
    ac.solve(asm)
    return list(made.values())


def move_out(asm, inners, before=None, after=False):
    """Components inside subassemblies (this document's copies) move up into asm, where they are
    now; their mates come with them. before: put them by that top-level row."""
    from . import asmexplode as ax
    doc = asm.Document
    groups = {}
    for m in inners:
        sub = holder(m)
        if sub is not None and sub in ac.components(asm):
            groups.setdefault(sub, []).append(m)
    out = []
    for sub, ms in groups.items():
        src = sub.LinkedObject
        sources = {m: _source_of(sub, m) for m in ms}
        if None in sources.values():
            continue
        src_fixed = ac.grounded(src)
        new = {}
        for m in ms:
            s = sources[m]
            target = s.LinkedObject if s.TypeId in ("App::Link", "Assembly::AssemblyLink") else s
            plc = ax.gplacement(m)
            link = ac.insert(asm, target, plc)
            link.Placement = plc
            new[s] = link
            if s in src_fixed:
                ac.fix(asm, link)
        # the subassembly's mates on them: up here (the other end still inside: through the subassembly)
        up, gone = [], []
        for j in list(ac.mates(src)):
            refs = _refs(j)
            if refs is None or not any(r[0] in new for r in refs):
                continue
            mapped = []
            for owner, path in refs:
                if owner in new:
                    mapped.append((new[owner], path))
                else:
                    inner = _inner_of(sub, owner)
                    mapped.append((sub, inner.Name + "." + path) if inner is not None else (None, path))
            if all(o is not None for o, _p in mapped):
                up.append((j, mapped))
            gone.append(j)
        # top mates that held them through the subassembly
        top = []
        names = {m.Name: new[sources[m]] for m in ms}
        for j in list(ac.mates(asm)):
            refs = _refs(j)
            if refs is None:
                continue
            mapped, hit = [], False
            for owner, path in refs:
                first, _dot, rest = path.partition(".")
                if owner is sub and first in names:
                    mapped.append((names[first], rest))
                    hit = True
                else:
                    mapped.append((owner, path))
            if hit:
                top.append((j, mapped))
        for j, refs in up + top:
            _remake(asm, j, refs)
        for j, _r in top:
            if doc.getObject(j.Name) is not None:
                doc.removeObject(j.Name)
        sdoc = src.Document
        for j in gone:
            if sdoc.getObject(j.Name) is not None:
                sdoc.removeObject(j.Name)
        for s in sources.values():
            if s in src_fixed and sdoc.getObject(src_fixed[s].Name) is not None:
                sdoc.removeObject(src_fixed[s].Name)
            sdoc.removeObject(s.Name)
        sdoc.recompute()
        out += list(new.values())
    doc.recompute()
    if out and before is not None and before in ac.components(asm):
        reorder(asm, out, before, after)
    ac.solve(asm)
    return out


# ----------------------------------------------------------------------------- the tree
def _transaction(doc, name, run):
    doc.openTransaction(name)
    try:
        return run()
    finally:
        doc.commitTransaction()


_KIND = {}


def _kind_kept(asm, obj):
    """_comp_kind, kept while the document is unchanged (the tree asks it for every row each time
    the selection changes: 300 selected components asked it 90,000 times)."""
    from . import asmgen
    if obj is None:
        return None
    doc = asm.Document
    key = (asmgen.gen(doc), id(asm))
    kept = _KIND.get(doc.Name)
    if kept is None or kept[0] != key or key[0] < 0:
        kept = _KIND[doc.Name] = (key, {})
    try:
        name = obj.FullName
    except Exception:
        return _comp_kind(asm, obj)
    try:
        return kept[1][name]
    except KeyError:
        k = kept[1][name] = _comp_kind(asm, obj)
        return k


def _comp_kind(asm, obj):
    """'top' (a component of asm), 'inner' (a component of one of its subassemblies), else None."""
    if obj is None:
        return None
    if _top(asm, obj):
        return "top"
    h = holder(obj)
    if h is not None and (_top(asm, h) or holder(h) is not None):
        return "inner"
    return None


_COMP_TYPES = ("App::Link", "Assembly::AssemblyLink")


def _top(asm, obj):
    """obj is one of asm's own components (as ac.components, without listing them all: the
    tree asks this for every row on every paint)."""
    try:
        if obj.TypeId not in _COMP_TYPES and not (obj.isDerivedFrom("Part::Feature") and obj.TypeId != "Assembly::JointGroup"
                                                and not obj.isDerivedFrom("Part::Part2DObject")):
            return False
        return obj.getParentGroup() is asm or (asm in obj.InList and obj in asm.Group)
    except Exception:
        return obj in ac.components(asm)


def plan(asm, objs, target, row, parent_obj, parent_is_top):
    """What a drop does: (action, args) or None.
    target: the row's object dropped on (row < 0) or by (row >= 0, then the row's object there);
    parent_obj: the object of the row the drop is under (None: the top assembly)."""
    kinds = {_comp_kind(asm, o) for o in objs}
    if None in kinds or not objs:
        return None
    if row < 0:
        # dropped ON a row
        if target is not None and ac.is_subassembly(target) and target not in objs:
            if kinds == {"top"}:
                return ("into", target)
            if kinds == {"inner"} and all(holder(o) is not target for o in objs) and holder(target) is None:
                return ("out_into", target)
            return None
        if target is None and parent_is_top and kinds == {"inner"}:
            return ("out", None, False)
        return None
    # dropped between rows
    if parent_is_top:
        if target is None or target in objs or _comp_kind(asm, target) != "top":
            return ("out", None, False) if kinds == {"inner"} else None
        if kinds == {"top"}:
            return ("reorder", target)
        if kinds == {"inner"}:
            return ("out", target, False)
        return None
    if parent_obj is not None and ac.is_subassembly(parent_obj) and target is not None:
        if kinds == {"inner"} and all(holder(o) is parent_obj for o in objs) and holder(target) is parent_obj:
            return ("reorder_inside", parent_obj, target)
        if kinds == {"top"} and holder(target) is parent_obj:
            return ("into", parent_obj)
    return None


def run(asm, action):
    kind = action[0]
    doc = asm.Document
    if kind == "reorder":
        return lambda objs: _transaction(doc, "Reorder", lambda: reorder(asm, objs, action[1]))
    if kind == "reorder_inside":
        return lambda objs: reorder_inside(action[1], objs, action[2])
    if kind == "into":
        return lambda objs: _transaction(doc, "Move to Subassembly", lambda: move_into(asm, objs, action[1]))
    if kind == "out":
        return lambda objs: _transaction(doc, "Move out of Subassembly",
                                         lambda: move_out(asm, objs, action[1], action[2]))
    if kind == "out_into":
        def both(objs):
            def go():
                up = move_out(asm, objs)
                return move_into(asm, up, action[1])
            return _transaction(doc, "Move to Subassembly", go)
        return both
    return None


def node_object(model, node):
    """The object of a tree row; a subassembly's component row (shown with the subassembly's own
    label, "PB<1>", not this document's copy "PB<1>001") is found among the subassembly's copies."""
    obj = getattr(node, "obj", None) if node is not None else None
    up = getattr(node, "parent", None)
    sub = getattr(up, "obj", None) if up is not None else None
    if sub is None or not ac.is_subassembly(sub):
        return obj
    if obj is not None and obj in ac.sub_components(sub):
        return obj
    try:
        from PySide import QtCore
        from . import sketchstatus
        text = sketchstatus.label_of(str(model.data(model.index_of(node), QtCore.Qt.DisplayRole) or ""))
    except Exception as _fw_err:
        _fw_log("asmrestructure.py:407", _fw_err)
        return obj
    for c in ac.sub_components(sub):
        if ac.source_label(c) == text or c.Label == text:
            return c
    return obj


def install():
    from . import fmtree
    from PySide import QtCore
    Qt = QtCore.Qt
    M = fmtree.Model
    if getattr(M, "_fw_restructure", False):
        return
    M._fw_restructure = True
    flags0, can0, drop0, mime0 = M.flags, M.canDropMimeData, M.dropMimeData, M.mimeData

    def _asm(self):
        try:
            return ac.assembly_of(self.doc) if self.doc is not None else None
        except Exception as _fw_err:
            _fw_log("asmrestructure.py:429", _fw_err)
            return None

    def flags(self, index):
        f = flags0(self, index)
        asm = _asm_kept(self)
        if asm is None or not index.isValid():
            return f
        node = self.node(index)
        obj = node_object(self, node)
        if node is self.part:
            return f | Qt.ItemIsDropEnabled
        k = _kind_kept(asm, obj)
        if k is not None:
            f |= Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        return f

    def _asm_kept(self):
        from . import asmgen
        doc = self.doc
        if doc is None:
            return None
        key = (asmgen.gen(doc), id(doc))
        kept = self.__dict__.get("_fw_asm_kept")
        if kept is not None and kept[0] == key and key[0] >= 0:
            return kept[1]
        asm = _asm(self)
        self.__dict__["_fw_asm_kept"] = (key, asm)
        return asm

    def mimeData(self, indexes):
        asm = _asm(self)
        if asm is None:
            return mime0(self, indexes)
        names = []
        for index in indexes:
            node = self.node(index)
            o = node_object(self, node)
            if o is not None and o.Name not in names:
                names.append(o.Name)
        data = QtCore.QMimeData()
        data.setData(MIME, QtCore.QByteArray("\n".join(names).encode()))
        return data

    def _plan(self, data, row, parent):
        asm = _asm(self)
        if asm is None:
            return None, None, []
        objs = self._dropped(data)
        if not objs or any(_comp_kind(asm, o) is None for o in objs):
            return asm, None, objs
        pnode = self.node(parent) if parent.isValid() else self.root
        if pnode is None:
            return asm, None, objs
        if row < 0:
            target = node_object(self, pnode) if pnode is not self.part else None
            up = pnode.parent
            is_top = pnode is self.part
            pobj = getattr(up, "obj", None) if up is not None else None
        else:
            kids = pnode.children
            node = kids[row] if row < len(kids) else (kids[-1] if kids else None)
            target = node_object(self, node) if node is not None else None
            is_top = pnode is self.part
            pobj = getattr(pnode, "obj", None)
        return asm, plan(asm, objs, target, row, pobj, is_top), objs

    def canDropMimeData(self, data, action, row, column, parent):
        asm, act, objs = _plan(self, data, row, parent)
        if asm is None or (objs and any(_comp_kind(asm, o) is None for o in objs)):
            return can0(self, data, action, row, column, parent)
        return act is not None

    def dropMimeData(self, data, action, row, column, parent):
        asm, act, objs = _plan(self, data, row, parent)
        if asm is None or (objs and any(_comp_kind(asm, o) is None for o in objs)):
            return drop0(self, data, action, row, column, parent)
        if act is None:
            return False
        fn = run(asm, act)
        try:
            fn(objs)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: assembly structure: %s\n" % error)
        self.soon()
        return False

    M.flags, M.mimeData, M.canDropMimeData, M.dropMimeData = flags, mimeData, canDropMimeData, dropMimeData
