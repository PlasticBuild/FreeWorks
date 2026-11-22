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

WORDS = ("Invalid edge link", "Invalid face link", "Invalid vertex link", "Invalid shape name",
         "Invalid element", "Invalid link", "Base feature's TopoShape is invalid")

_busy = set()
_retries = [0]     # how many retries ran (for the checks)
_stuck = {}        # document name -> the failures a retry could not mend (not retried again)
RECOMPUTES = [0]   # document rebuilds seen (What's Wrong keys the messages it saved on it)


def lost_names(doc):
    """The features whose rebuild failed on a lost element name."""
    out = []
    for obj in doc.Objects:
        try:
            if "Invalid" in obj.State and any(w in (obj.getStatusString() or "") for w in WORDS):
                out.append(obj)
        except Exception as _fw_err:
            _fw_log("rebuildretry.py:53", _fw_err)
    return out


def moved_picks(doc):
    """Failed fillets, chamfers and drafts whose edges are no longer the ones picked: FreeCAD gave
    the names to other edges in this rebuild (after suppress and back it does so now and then, and
    the fillet then fails "due to the geometry"). The picked edges are still there, where they were."""
    out = []
    try:
        from . import picksgeo
    except Exception:
        return out
    for obj in doc.Objects:
        try:
            if "Invalid" not in obj.State or not obj.isDerivedFrom("PartDesign::DressUp"):
                continue
            sigs = picksgeo.remembered(obj)
            base, subs = obj.Base
            if not sigs or base is None or "Invalid" in base.State:
                continue
            want = [picksgeo.match(base.Shape, sig) or picksgeo.match_near(base.Shape, sig) for _sub, sig in sigs]
            if None not in want and want != list(subs):
                out.append(obj)
        except Exception:
            continue
    return out


def _failures(doc):
    seen = set()
    out = []
    for o in lost_names(doc) + moved_picks(doc):
        if o.Name not in seen:
            seen.add(o.Name)
            out.append(o)
    return out


def _sign(objs):
    out = []
    for o in objs:
        try:
            out.append((o.Name, (o.getStatusString() or "").split(":")[0]))   # without the changing ids
        except Exception as _fw_err:
            _fw_log("rebuildretry.py:98", _fw_err)
    return tuple(sorted(out))


def _after(obj):
    """obj and the features after it in its body."""
    body = None
    try:
        body = obj.getParentGeoFeatureGroup()
    except Exception as _fw_err:
        _fw_log("rebuildretry.py:108", _fw_err)
    if body is None or body.TypeId != "PartDesign::Body":
        return [obj]
    group = list(body.Group)
    return group[group.index(obj):] if obj in group else [obj]


def retry(doc):
    """Rebuild the features that lost an element name (or whose picks moved), and those after them.
    True when it ran."""
    failed = _failures(doc)
    if not failed or doc.Name in _busy:
        return False
    sign = _sign(failed)
    if _stuck.get(doc.Name) == sign:
        return False            # a retry did not mend these: real errors, not rebuilt twice each time
    _busy.add(doc.Name)
    try:
        _repick_failed(doc, failed)
        seen = set()
        for obj in failed:
            for o in _after(obj):
                if o.Name not in seen:
                    seen.add(o.Name)
                    try:
                        o.touch()
                    except Exception as _fw_err:
                        _fw_log("rebuildretry.py:135", _fw_err)
        doc.recompute()
        _retries[0] += 1
        left = _failures(doc)
        _stuck[doc.Name] = _sign(left) if left else None
        return True
    finally:
        _busy.discard(doc.Name)


def _remember(doc):
    """The fillets', chamfers' and drafts' picks by geometry, where they were when picked: the first
    good rebuild after the file opened or the picks changed. Not on every rebuild: with an earlier
    feature suppressed a fillet can still build, on other edges of the same names."""
    try:
        from . import picksgeo
    except Exception:
        return
    new = []
    for o in doc.Objects:
        try:
            if "Invalid" in o.State or not o.isDerivedFrom("PartDesign::DressUp"):
                continue
            had = picksgeo.remembered(o)
            if had and [sub for sub, _sig in had] == list(o.Base[1]):
                continue
            new.append(o)
        except Exception:
            continue
    if new:
        try:
            picksgeo.dressups(new)
        except Exception as _fw_err:
            _fw_log("rebuildretry.py:168", _fw_err)
    try:                       # any feature's face/edge picks (Wrap, Split Line, Variable Fillet ...)
        fresh = [o for o in doc.Objects if "Invalid" not in o.State and "Error" not in o.State
                 and not o.isDerivedFrom("PartDesign::DressUp")]
        if fresh:
            picksgeo.remember_links(fresh)
    except Exception as _fw_err:
        _fw_log("rebuildretry.py:175", _fw_err)


def _repick_failed(doc, failed):
    ""


    try:
        from . import picksgeo
    except Exception:
        return []
    saved = []
    for obj in failed:
        try:
            if not obj.isDerivedFrom("PartDesign::DressUp"):
                continue
        except Exception:
            continue
        sigs = picksgeo.remembered(obj)
        if sigs:
            saved.append((obj, None, sigs))
    done = picksgeo.repick(saved) if saved else []
    try:
        done += picksgeo.repick_links([o for o in failed if not o.isDerivedFrom("PartDesign::DressUp")])
    except Exception as _fw_err:
        _fw_log("rebuildretry.py:200", _fw_err)
    return done


def _solid(obj):
    try:
        return obj.isDerivedFrom("PartDesign::Feature")
    except Exception:
        return False


def _chain(body):
    """The body's features up to the rollback bar (its Tip), in tree order."""
    group = list(body.Group)
    tip = body.Tip
    return group[:group.index(tip) + 1] if tip in group else group


def _failed_bodies(doc):
    out = []
    for body in doc.Objects:
        try:
            if body.TypeId == "PartDesign::Body" and any(_solid(o) and "Invalid" in o.State for o in _chain(body)):
                out.append(body)
        except Exception as _fw_err:
            _fw_log("rebuildretry.py:225", _fw_err)
    return out


def _fallback(obj):
    ""
    base = getattr(obj, "BaseFeature", None)
    if base is None:
        return False
    try:
        want = base.Shape
        if want.isNull():
            return False
        have = obj.Shape
        if not have.isNull() and have.isPartner(want):
            return False
        obj.Shape = want
        return True
    except Exception:
        return False


_carried = [0]      # how many carry_on passes changed something (for the checks)


def carry_on(doc):
    ""
    if doc.Name in _busy:
        return False
    changed = False
    _busy.add(doc.Name)
    try:
        for body in _failed_bodies(doc):
            chain = _chain(body)
            first = next(i for i, o in enumerate(chain) if _solid(o) and "Invalid" in o.State)
            here = False
            dirty = False       # something before changed: the rest is rebuilt on it
            for o in chain[first:]:
                try:
                    if o is not chain[first] and (dirty or "Touched" in o.State):
                        if o.recompute() and "Invalid" not in o.State:
                            o.purgeTouched()
                        here = dirty = True
                    if _solid(o) and "Invalid" in o.State and _fallback(o):
                        here = dirty = True
                except Exception as _fw_err:
                    _fw_log("rebuildretry.py:271", _fw_err)
            if here:
                changed = True
                try:
                    body.recompute()
                except Exception as _fw_err:
                    _fw_log("rebuildretry.py:277", _fw_err)
        if changed:
            _carried[0] += 1
    finally:
        _busy.discard(doc.Name)
    if changed:
        try:
            from . import persistrefs       # picks on the model as it was before the failed feature
            persistrefs.after_rebuild(doc)
        except Exception as _fw_err:
            _fw_log("rebuildretry.py:287", _fw_err)
    return changed


class _Watch:
    def slotDeletedDocument(self, doc):
        try:
            from . import picksgeo          # a document opened later under the same name starts clean
            for k in [k for k in picksgeo._good if k[0] == doc.Name]:
                picksgeo._good.pop(k, None)
            for k in [k for k in picksgeo._links_good if k[0] == doc.Name]:
                picksgeo._links_good.pop(k, None)
        except Exception as _fw_err:
            _fw_log("rebuildretry.py:300", _fw_err)
        _stuck.pop(doc.Name, None)
        try:
            from . import whatswrong
            whatswrong.forget(doc.Name)
        except Exception:
            pass

    def slotRecomputedDocument(self, doc):
        RECOMPUTES[0] += 1
        if doc.Name in _busy:
            return
        failed = _failures(doc)
        _remember(doc)
        later = _later if failed and _stuck.get(doc.Name) != _sign(failed) else _carry_later
        if later is _carry_later and not _failed_bodies(doc):
            return
        # not inside FreeCAD's own recompute: right after it
        try:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda name=doc.Name: later(name))
        except Exception as _fw_err:
            _fw_log("rebuildretry.py:317", _fw_err)


def _later(name):
    try:
        doc = App.getDocument(name)
    except Exception:
        return
    if retry(doc):
        carry_on(doc)
        try:
            from . import whatswrong
            getattr(whatswrong, "after_recompute", whatswrong.after_rebuild)(doc)
        except Exception as _fw_err:
            _fw_log("rebuildretry.py:331", _fw_err)
    else:
        _carry_later(name)


def _carry_later(name):
    try:
        doc = App.getDocument(name)
    except Exception:
        return
    changed = carry_on(doc)
    try:
        from . import whatswrong
        # a real error is shown even when no fallback shape changed; after_recompute keeps the box

        getattr(whatswrong, "after_recompute", whatswrong.after_rebuild)(doc)
        if changed:
            box = whatswrong.dialog()
            if box is not None and box.isVisible() and box.doc_name == doc.Name:
                box.fill(doc, whatswrong.errors(doc))
    except Exception as _fw_err:
        _fw_log("rebuildretry.py:350", _fw_err)


_watch = []


def install():
    if not _watch:
        _watch.append(_Watch())
        App.addDocumentObserver(_watch[0])
