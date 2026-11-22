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

_MEMO = {}          # (document, joint, property) -> (part doc gen, shape hash, signature, element name)
moved = []          # (joint label, property, old element, new element) for the checks


def _pr():
    try:
        from . import persistrefs
        return persistrefs
    except Exception:
        return None


def _part_shape(comp):
    target = getattr(comp, "LinkedObject", None)
    if target is None or comp.TypeId != "App::Link":
        return None, None
    try:
        shape = target.Shape
    except Exception:
        return None, None
    if shape is None or shape.isNull():
        return None, None
    return target, shape


def keep(asm):
    """Before a solve: every mate reference still on its element, moved to it when renumbered.
    Returns the number moved."""
    if _pr() is None or asm is None:
        return 0
    return sum(keep_joint(j) for j in list(ac.joint_group(asm).Group))


def keep_joint(j, force=False):
    pr = _pr()
    if pr is None:
        return 0
    from . import asmgen
    n = 0
    doc = j.Document
    for prop in ("Reference1", "Reference2"):
        ref = getattr(j, prop, None)
        if not ref or not ref[1]:
            continue
        comp, subs = ref[0], list(ref[1])
        name = pr._short(subs[-1] if len(subs) > 1 else subs[0])
        lost = any(str(x).startswith("?") for x in subs)    # FreeCAD lost the element's history
        if "." in name or name[:4] not in ("Face", "Edge", "Vert"):
            continue        # a path into a subassembly: FreeCAD follows it by name
        target = getattr(comp, "LinkedObject", None)
        if target is None:
            continue
        key = (doc.Name, j.Name, prop)
        memo = _MEMO.get(key)
        g = asmgen.gen(target.Document)
        if not force and not lost and memo is not None and g >= 0 and memo[0] == g and memo[3] == name:
            continue        # the part did not change since
        target, shape = _part_shape(comp)
        if shape is None:
            continue
        h = pr._hash(shape)
        if not lost and memo is not None and memo[1] == h and memo[3] == name:
            _MEMO[key] = (g, h, memo[2], name)
            continue
        now = pr.signature(shape, name)
        if memo is None or memo[3] != name:
            if memo is not None and now is not None and memo[1] != h and tuple(memo[2][:2]) != tuple(now[:2]):
                # FreeCAD renamed it while the part changed (a configuration switched an assembly
                # cut on or off), onto another kind of element: no pick of the user's, not learned
                # (a Concentric's bore was learned as a plane, then moved off the bore)
                continue
            if now is not None:     # first seen, or picked anew: learned as it is
                _MEMO[key] = (g, h, now, name)
            continue
        s = pr.score(memo[2], now) if now is not None else None
        if s is not None and s <= pr.AGREE:
            _MEMO[key] = (g, h, now, name)
            if not lost:
                continue
            new = name          # the same element under its number: the mate holds it again
        else:
            new = pr.find(shape, memo[2])
        if new and (new != name or lost):
            try:
                setattr(j, prop, (comp, [new, new]))
                moved.append((j.Label, prop, name, new))
                App.Console.PrintLog("FreeCAD: mate %s keeps its %s: %s -> %s\n" % (j.Label, prop, name, new))
                _MEMO[key] = (g, h, pr.signature(shape, new), new)
                n += 1
                continue
            except Exception as error:
                App.Console.PrintLog("FreeCAD: mate reference %s: %s\n" % (j.Label, error))
        _MEMO[key] = (g, h, memo[2], name)     # no clear match: keep looking for the old one
    if n:
        try:
            # FreeCAD may have run the mate on the lost name already ("Broken link in"): run
            # it again on the element it holds now, so What's Wrong has nothing to show
            j.touch()
            j.recompute()
        except Exception as _fw_err:
            _fw_log("asmpersist.py:120", _fw_err)
    return n


class _Watch:
    """A part's new shape: the mates on it move to their elements before they recompute
    (FreeCAD recomputes the assembly's mates with the part, and a lost name breaks them)."""

    def slotChangedObject(self, obj, prop):
        if prop != "Shape" or not _MEMO:
            return
        try:
            for link in obj.InList:
                if link.TypeId != "App::Link" or link.Document is obj.Document:
                    continue
                for j in link.InList:
                    if hasattr(j, "Reference1") and hasattr(j, "JointType"):
                        keep_joint(j, force=True)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: mate references: %s\n" % error)


_watch = []


def _lost(ref):
    return bool(ref) and any(str(x).startswith("?") for x in ref[1])


def _catch_lost():
    ""


    import JointObject
    cls = JointObject.Joint
    if getattr(cls, "_fw_lost", False):
        return
    original = cls.onChanged

    def onChanged(self, joint, prop):
        if prop in ("Reference1", "Reference2") and _MEMO:
            try:
                if _lost(getattr(joint, prop, None)):
                    keep_joint(joint, force=True)
                    if not _lost(getattr(joint, prop, None)):
                        return      # set again on its face: that change ran the mate
            except Exception as error:
                App.Console.PrintLog("FreeCAD: mate references: %s\n" % error)
        return original(self, joint, prop)
    cls.onChanged = onChanged
    cls._fw_lost = True


def install():
    if not _watch:
        _watch.append(_Watch())
        App.addDocumentObserver(_watch[0])
    try:
        _catch_lost()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: mate references: %s\n" % error)


def forget(joint=None):
    if joint is None:
        _MEMO.clear()
        return
    for k in [k for k in _MEMO if k[1] == joint.Name and k[0] == joint.Document.Name]:
        _MEMO.pop(k, None)
