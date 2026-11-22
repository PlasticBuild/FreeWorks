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
from PySide import QtCore

from . import asmcore as ac

MIN_MATES = 30      # below this a whole solve is quick: the drag stays as FreeCAD does it
MIN_OFF = 10        # fewer mates to leave out than this: not worth it
STATE = {"doc": None, "off": [], "active": False, "frozen": []}
THAW_MS = 400       # after the mates are back: FreeCAD's tree re-reads their state, then it paints
STATS = {"drags": 0, "left_out": 0}


def _refs(joint):
    out = []
    for prop in ("Reference1", "Reference2"):
        ref = getattr(joint, prop, None)
        if ref and ref[0] is not None:
            out.append(ref[0])
    return out


def _held_by_table(joint):
    try:
        return "Suppressed" in dict(joint.ExpressionEngine)
    except Exception:
        return True


def island(asm, comp):
    """The mates a drag of comp needs: every mate reachable from it through components that are
    not fixed. Returns (needed, others), or None when it cannot be told."""
    comps = ac.components(asm)
    if comp not in comps:
        return None
    if any(ac.is_flexible(c) for c in comps if ac.is_subassembly(c)):
        return None
    fixed = set(ac.grounded(asm))
    group = ac.joint_group(asm)
    joints = list(group.Group) if group is not None else []
    by_comp = {}
    live = []
    for j in joints:
        if "Suppressed" not in j.PropertiesList or getattr(j, "Suppressed", False):
            continue
        if getattr(j, "JointType", None) is None:
            continue        # a grounding: always kept
        refs = _refs(j)
        if not refs or any(r not in comps for r in refs):
            return None     # a reference into a subassembly or elsewhere: no shortcut
        live.append(j)
        for r in refs:
            by_comp.setdefault(r, []).append(j)
    seen, need, todo = {comp}, set(), [comp]
    while todo:
        c = todo.pop()
        for j in by_comp.get(c, []):
            if j in need:
                continue
            need.add(j)
            for r in _refs(j):
                if r not in seen and r not in fixed:
                    seen.add(r)
                    todo.append(r)
    others = [j for j in live if j not in need and not _held_by_table(j)
              and not getattr(j, ac.PART_OF_PROP, "")]
    return need, others


class _Guard:
    """A save (or a close) while mates are off for a drag puts them back first: a file never holds
    a mate switched off only for a drag."""
    def slotStartSaveDocument(self, doc, path):
        if STATE["active"] and doc.Name == STATE["doc"]:
            end(now=True)

    def slotDeletedDocument(self, doc):
        if STATE["active"] and doc.Name == STATE["doc"]:
            STATE.update(doc=None, off=[], active=False)
            _thaw_trees()


_guard = []


def begin(asm, comp):
    """Before FreeCAD's drag starts: the mates comp cannot move switched off for the drag."""
    if STATE["active"]:
        end(now=True)       # a drag whose end was never seen (focus lost): put them back first
    if asm is None or comp is None:
        return False
    if not _guard:
        _guard.append(_Guard())
        App.addDocumentObserver(_guard[0])
    try:
        doc = asm.Document
        if getattr(doc, "HasPendingTransaction", False):
            return False    # an undo step is open (a PropertyManager): nothing changed under it
        if len(ac.mates(asm)) < MIN_MATES:
            return False
        got = island(asm, comp)
        if got is None:
            return False
        need, others = got
        if len(others) < MIN_OFF:
            return False
        off = []
        STATE.update(doc=doc.Name, off=off, active=True)
        _freeze_trees()
        from . import asmgen
        asmgen.OVERLAY_HOLD.append(True)     # the mate rows' marks as before the drag
        STATE["topo"] = asmgen.topo(doc)
        for j in others:
            j.Suppressed = True
            off.append(j.Name)
            j.purgeTouched()
        STATE["topo_off"] = asmgen.topo(doc)
        STATS["drags"] += 1
        STATS["left_out"] += len(off)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: drag island: %s\n" % error)
        end(now=True)
        return False


def end(now=False, tries=40):
    """After the drag: the mates switched off come back, once FreeCAD closed its undo step."""
    if not STATE["active"]:
        return
    doc = App.listDocuments().get(STATE["doc"] or "")
    if doc is None:
        STATE.update(doc=None, off=[], active=False)
        from . import asmgen
        del asmgen.OVERLAY_HOLD[:]
        _thaw_trees()
        return
    if not now and tries > 0 and getattr(doc, "HasPendingTransaction", False):
        QtCore.QTimer.singleShot(50, lambda: end(tries=tries - 1))
        return
    names, STATE["off"] = STATE["off"], []
    STATE.update(doc=None, active=False)
    from . import asmgen
    same = asmgen.topo(doc) == STATE.get("topo_off")     # nothing else changed during the drag
    for name in names:
        j = doc.getObject(name)
        if j is None:
            continue
        try:
            j.Suppressed = False
            j.purgeTouched()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: mate %s not switched back on after a drag: %s\n" % (name, error))
    if same and STATE.get("topo") is not None:
        asmgen.restamp_overlays(doc, STATE["topo"], asmgen.topo(doc))
    del asmgen.OVERLAY_HOLD[:]
    _thaw_trees_later(now)


def _trees():
    try:
        import FreeCADGui as Gui
        from PySide import QtWidgets
        mw = Gui.getMainWindow()
        return [t for t in mw.findChildren(QtWidgets.QTreeView) if t.isVisible()]
    except Exception:
        return []


def _freeze_trees():
    for t in _trees():
        if t.updatesEnabled():
            t.setUpdatesEnabled(False)
            STATE["frozen"].append(t)


def _thaw_trees():
    if STATE["active"]:
        return              # a new drag began meanwhile: the trees stay as they are
    while STATE["frozen"]:
        t = STATE["frozen"].pop()
        try:
            t.setUpdatesEnabled(True)
            t.viewport().update()
        except Exception as _fw_err:
            _fw_log("asmisland.py:198", _fw_err)


def _thaw_trees_later(now=False):
    if now:
        _thaw_trees()
    else:
        QtCore.QTimer.singleShot(THAW_MS, _thaw_trees)


def is_off(joint):
    """True while joint is switched off only for a drag."""
    try:
        return STATE["active"] and joint.Document.Name == STATE["doc"] and joint.Name in STATE["off"]
    except Exception:
        return False
