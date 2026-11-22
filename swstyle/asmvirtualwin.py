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

from . import asmcore as ac

OPEN = {}       # temporary document name -> {"top": doc name, "src": object name, "map": {tmp comp: src comp}, "key": ...}
_observer = []


def _plain(label):
    import re
    return re.sub(r"(<\d+>)\d{3}$", r"\1", label)


def window_of(link):
    src = link.LinkedObject
    for name, e in OPEN.items():
        if e["top"] == link.Document.Name and e["src"] == src.Name and name in App.listDocuments():
            return App.getDocument(name)
    return None


def open_virtual(link):
    """The virtual subassembly in a window of its own; returns that document."""
    from . import asmcomp
    if not asmcomp.is_virtual_sub(link):
        return None
    have = window_of(link)
    if have is not None:
        Gui.setActiveDocument(have.Name)
        return have
    _install()
    src = link.LinkedObject
    top = link.Document
    label = src.Label
    try:
        tmp = App.newDocument(label.replace("^", "_").replace(" ", "_"), label, False, True)   # temporary: no save prompt
    except TypeError:
        tmp = App.newDocument(label.replace("^", "_").replace(" ", "_"))
        tmp.Label = label
    asm = ac.make_assembly(tmp)
    asm.Label = label
    mp = {}
    for c in ac.components(src):
        n = asm.newObject("App::Link", "Component")
        n.LinkedObject = c.LinkedObject
        n.Placement = c.Placement
        n.Label = _plain(c.Label)
        mp[n] = c
    tmp.recompute()
    back = {v: k for k, v in mp.items()}
    fixed = ac.grounded(src)
    for c in ac.components(src):
        if c in fixed:
            ac.fix(asm, back[c])
    from . import asmcomp as acomp
    for j in ac.mates(src):
        try:
            acomp._remake_mate(asm, j, back)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: virtual window, mate %s: %s\n" % (j.Label, error))
    for t, c in mp.items():     # the places the subassembly has, not where a solve put them
        t.Placement = c.Placement
    tmp.recompute()
    OPEN[tmp.Name] = {"top": top.Name, "src": src.Name, "map": {t.Name: c.Name for t, c in mp.items()},
                      "key": _key(asm, {t.Name: c.Name for t, c in mp.items()})}
    try:
        from . import asmui
        Gui.setActiveDocument(tmp.Name)
        asmui.activate(asm)
    except Exception as _fw_err:
        _fw_log("asmvirtualwin.py:93", _fw_err)
    return tmp


def _key(asm, mp):
    """What the window's mates are, to see when they changed."""
    rows = []
    for j in ac.mates(asm):
        refs = []
        for p in ("Reference1", "Reference2"):
            r = getattr(j, p, None)
            refs.append((r[0].Name, tuple(r[1])) if r else None)
        rows.append((ac.mate_type(j), tuple(refs), str(getattr(j, "Distance", "")), str(getattr(j, "Angle", "")),
                     bool(getattr(j, "Suppressed", False)), bool(getattr(j, ac.LOCK_PROP, False))))
    rows.append(("fixed", tuple(sorted(c.Name for c in ac.grounded(asm)))))
    return tuple(rows)


def sync(tmp):
    """The window's assembly written back to its virtual subassembly; the top solves again."""
    e = OPEN.get(tmp.Name)
    if e is None or e["top"] not in App.listDocuments():
        return False
    top = App.getDocument(e["top"])
    src = top.getObject(e["src"])
    asm = ac.assembly_of(tmp)
    if src is None or asm is None:
        return False
    mp = e["map"]
    comps = ac.components(asm)
    live = {c.Name for c in comps}
    # components: deleted, added, moved
    for tname, sname in list(mp.items()):
        if tname not in live:
            s = top.getObject(sname)
            if s is not None:
                for j in [j for j in ac.mates(src) if any(getattr(j, p, None) and getattr(j, p)[0] is s
                                                         for p in ("Reference1", "Reference2"))]:
                    top.removeObject(j.Name)
                g = ac.grounded(src).get(s)
                if g is not None:
                    top.removeObject(g.Name)
                top.removeObject(sname)
            mp.pop(tname)
    # FreeCAD keeps the subassembly component's copy of a deleted component: it goes too
    have = set(ac.components(src))
    for holder in [o for o in top.Objects if o.TypeId == "Assembly::AssemblyLink" and o.LinkedObject is src]:
        for kid in list(getattr(holder, "Group", []) or []):
            if kid.TypeId == "App::Link" and kid.LinkedObject not in have:
                try:
                    top.removeObject(kid.Name)
                except Exception as _fw_err:
                    _fw_log("asmvirtualwin.py:145", _fw_err)
    for c in comps:
        s = top.getObject(mp.get(c.Name, "")) if c.Name in mp else None
        if s is None:
            s = src.newObject("App::Link", "Component")
            s.LinkedObject = c.LinkedObject
            s.Label = c.Label
            mp[c.Name] = s.Name
        if not s.Placement.isSame(c.Placement, 1e-9):
            s.Placement = c.Placement
        if s.LinkedObject is not c.LinkedObject:
            s.LinkedObject = c.LinkedObject
    key = _key(asm, mp)
    if key != e["key"]:
        # mates or fixes changed: the subassembly's are made again from the window's
        for j in list(ac.mates(src)):
            top.removeObject(j.Name)
        for g in list(ac.grounded(src).values()):
            top.removeObject(g.Name)
        to_src = {c: top.getObject(mp[c.Name]) for c in comps}
        for c in ac.grounded(asm):
            ac.fix(src, to_src[c])
        from . import asmcomp
        for j in ac.mates(asm):
            try:
                asmcomp._remake_mate(src, j, to_src)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: virtual window write-back, mate %s: %s\n" % (j.Label, error))
        for c in comps:
            to_src[c].Placement = c.Placement
        e["key"] = key
    top.recompute()
    top_asm = ac.assembly_of(top)
    if top_asm is not None:
        ac.solve(top_asm)
        top.recompute()
    return True


class _Watch:
    def slotRecomputedDocument(self, doc):
        if doc.Name in OPEN and not _busy:
            _busy.append(doc.Name)
            try:
                sync(doc)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: virtual window write-back: %s\n" % error)
            finally:
                _busy.remove(doc.Name)

    def slotDeletedDocument(self, doc):
        OPEN.pop(doc.Name, None)


_busy = []


def _install():
    if not _observer:
        _observer.append(_Watch())
        App.addDocumentObserver(_observer[0])
