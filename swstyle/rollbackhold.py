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

try:
    import FreeCADGui as Gui
except ImportError:         # console mode: nothing to do
    Gui = None

BODY = "PartDesign::Body"
_held = {}          # document name -> [(document name, object name)] frozen for this recompute
_observer = None
_saving = {}        # document name -> objects thawed for a save, frozen again after it


def _frozen(obj):
    from . import freezebar          # also an object in error, whose status string is its error
    return freezebar.frozen(obj)


def below_bar(body):
    """The body's objects from the first solid feature past its Tip on (the features under the
    rollback bar and what comes after them), or [] when the body is not rolled back. A sketch or
    plane just past the Tip with no solid feature after it is new work at the bar (or a sketch
    not used yet at the end of the part): it rebuilds as usual."""
    tip = body.Tip
    if tip is None:
        return []
    group = [o for o in body.Group if not o.isDerivedFrom("App::Origin")]
    if tip not in group:
        return []
    try:
        from . import rollbackbar
        solids = set(o.Name for o in rollbackbar.solid_features(body))
    except Exception as _fw_err:
        _fw_log("rollbackhold.py:solids", _fw_err)
        return []
    after = group[group.index(tip) + 1:]
    first = next((i for i, o in enumerate(after) if o.Name in solids), None)
    return after[first:] if first is not None else []


def _toggle(objs):
    from . import freezebar          # FreeCAD's Std_ToggleFreeze on these objects only, selection kept
    freezebar._toggle(objs)


def _pending(obj):
    """obj is due to rebuild in this recompute (touched, or a property changed)."""
    try:
        if "Touched" in obj.State:
            return True
        return bool(obj.mustExecute())
    except Exception:
        return False


def _due(objs, doc):
    """The objects under the bar this recompute would rebuild: touched themselves, or using something
    touched. A body counts for nothing here: moving the bar touches the body, not its features.
    Only these are held (reviewer 11-20: holding and later touching every feature under the bar made a
    roll back and Roll to End 5x slower, 0.17 s -> 0.92 s on 10 features)."""
    touched = set(o.Name for o in doc.Objects if o.TypeId != BODY and _pending(o))
    if not touched:
        return []
    out = []
    for o in objs:
        if o.Name in touched:
            out.append(o)
            continue
        try:
            if any(x.Name in touched for x in o.OutListRecursive):
                out.append(o)
        except Exception:
            out.append(o)
    return out


class _Observer:
    def slotBeforeRecomputeDocument(self, doc):
        try:
            if Gui is None or doc.Name in _held:
                return
            hold = []
            for body in [o for o in doc.Objects if o.TypeId == BODY]:
                hold += [o for o in below_bar(body) if not _frozen(o)]
            hold = _due(hold, doc) if hold else []
            if not hold:
                return
            _toggle(hold)
            _held[doc.Name] = [o.Name for o in hold if _frozen(o)]
        except Exception as _fw_err:
            _fw_log("rollbackhold.py:before", _fw_err)

    def slotStartSaveDocument(self, doc, _path):
        # FreeCAD refuses to save with any object frozen (Freeze bar, or a hold left over): thawed for
        # the save, frozen again after (Freeze bar ones only; a hold is never refrozen)
        try:
            from . import freezebar
            _held.pop(doc.Name, None)
            _saving[doc.Name] = freezebar.thaw_for_save(doc)
        except Exception as _fw_err:
            _fw_log("rollbackhold.py:save", _fw_err)

    def slotFinishSaveDocument(self, doc, _path):
        names = _saving.pop(doc.Name, None)
        if not names:
            return
        try:
            from . import freezebar
            keep = []
            for n in names:
                o = doc.getObject(n)
                body = freezebar.body_of(o) if o is not None else None
                if body is None or o not in below_bar(body):     # a rollback hold stays thawed
                    keep.append(n)
            freezebar.refreeze_after_save(doc, keep)
        except Exception as _fw_err:
            _fw_log("rollbackhold.py:saved", _fw_err)

    def slotRecomputedDocument(self, doc):
        # thawed at once, in this signal: a script or a Roll to End that rebuilds right after must find
        # them live (FreeCAD logs the thaw's own recompute request as recursive and skips it)
        _thaw(doc.Name)


def _thaw(doc_name):
    names = _held.pop(doc_name, None)
    doc = App.listDocuments().get(doc_name)
    if not names or doc is None:
        return
    if True:
        try:
            objs = [doc.getObject(n) for n in names]
            objs = [o for o in objs if o is not None]
            # thaw from the bottom up, one at a time (FreeCAD's toggle also thaws an object's dependents)
            for o in reversed(objs):
                if _frozen(o):
                    _toggle([o])
            for o in objs:
                try:
                    o.touch()       # its inputs may have changed: it rebuilds when the bar moves down
                except Exception as _fw_err:
                    _fw_log("rollbackhold.py:touch", _fw_err)
        except Exception as _fw_err:
            _fw_log("rollbackhold.py:after", _fw_err)


def start():
    global _observer
    if _observer is None and Gui is not None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
