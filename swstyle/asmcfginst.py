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

PROP = "FwConfiguration"
_BUSY = []


def is_copy(comp):
    return getattr(comp, "LinkCopyOnChange", "Disabled") not in ("Disabled", 0) \
        and getattr(comp, "LinkCopyOnChangeSource", None) is not None


def source(comp):
    """The part object an instance stands for (the part itself, not the copy it may link)."""
    if is_copy(comp):
        return comp.LinkCopyOnChangeSource
    return getattr(comp, "LinkedObject", None)


def _table(doc):
    try:
        from . import configmanager as cm
        return cm.table(doc)
    except Exception as _fw_err:
        _fw_log("asmcfginst.py:48", _fw_err)
        return None


def is_subassembly(comp):
    return getattr(comp, "TypeId", "") == "Assembly::AssemblyLink"


def configuration(comp):
    """The configuration this instance shows."""
    if (is_copy(comp) or is_subassembly(comp)) and getattr(comp, PROP, ""):
        return getattr(comp, PROP)
    src = source(comp)
    t = _table(src.Document) if src is not None else None
    return (t.active() if t is not None else None) or "Default"


def configuration_of_part(src):
    t = _table(src.Document)
    return t.active() if t is not None else None


def names(comp):
    src = source(comp)
    t = _table(src.Document) if src is not None else None
    return list(t.names()) if t is not None else ["Default"]


def _copy_sheet(comp):
    group = getattr(comp, "LinkCopyOnChangeGroup", None)
    for obj in (getattr(group, "ElementList", None) or []):
        if obj.TypeId == "Spreadsheet::Sheet" and "Configuration" in obj.PropertiesList:
            return obj
    return None


def _hide_group(comp):
    group = getattr(comp, "LinkCopyOnChangeGroup", None)
    if group is None or not App.GuiUp:
        return
    try:
        group.ViewObject.ShowInTree = False
        for obj in group.ElementList:
            obj.ViewObject.ShowInTree = False
            obj.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("asmcfginst.py:87", _fw_err)


def _revert(comp):
    src = source(comp)
    group = getattr(comp, "LinkCopyOnChangeGroup", None)
    comp.LinkCopyOnChange = "Disabled"
    if src is not None and comp.LinkedObject is not src:
        comp.LinkedObject = src
    if group is not None:
        doc = group.Document
        for obj in reversed(list(group.ElementList)):
            try:
                doc.removeObject(obj.Name)
            except Exception as _fw_err:
                _fw_log("asmcfginst.py:102", _fw_err)
        try:
            doc.removeObject(group.Name)
        except Exception as _fw_err:
            _fw_log("asmcfginst.py:106", _fw_err)


def _sub_hidden(t, sub_comp, name):
    """A subassembly's component is left out in its configuration name (suppressed or hidden there)."""
    from . import configs
    for alias in (configs.COMP + configs._safe(sub_comp.Name), "Hide_" + configs._safe(sub_comp.Name)):
        try:
            v = configs.cell_value(t, alias, name)
        except Exception:
            v = None
        if v is not None and v.strip() in ("1", "1.0"):
            return True
    return False


def _apply_sub(comp, t, name):
    """The instance's own rows (the subassembly link's children) shown as configuration name has
    them; the subassembly document itself is not changed. True when something changed."""
    changed = False
    for child in getattr(comp, "Group", None) or []:
        sub_comp = getattr(child, "LinkedObject", None)
        if sub_comp is None:
            continue
        want = not _sub_hidden(t, sub_comp, name)
        if bool(child.Visibility) != want:
            child.Visibility = want
            changed = True
    return changed


def _set_sub(comp, name, recompute):
    sub_asm = getattr(comp, "LinkedObject", None)
    t = _table(sub_asm.Document) if sub_asm is not None else None
    if t is None or name not in t.names():
        return False
    if PROP not in comp.PropertiesList:
        comp.addProperty("App::PropertyString", PROP, "FreeCAD", "The configuration this subassembly instance shows")
    setattr(comp, PROP, "" if name == t.active() else name)
    _apply_sub(comp, t, name)
    if recompute:
        comp.Document.recompute()
    return True


def set_configuration(comp, name, recompute=True):
    """This instance shows the part's configuration name (only this instance). True when it does."""
    if is_subassembly(comp):
        return _set_sub(comp, name, recompute)
    src = source(comp)
    t = _table(src.Document) if src is not None else None
    if t is None or name not in t.names():
        return False
    doc = comp.Document
    if name == t.active():
        if is_copy(comp):
            _revert(comp)                       # the part itself shows it: link the part again
    else:
        if PROP not in src.PropertiesList:
            src.addProperty("App::PropertyString", PROP, "FreeCAD",
                            "The configuration an assembly instance of this part shows")
            src.setPropertyStatus(PROP, "CopyOnChange")
        if not is_copy(comp):
            comp.LinkCopyOnChange = "Tracking"
        if getattr(comp, PROP, None) == name and _copy_sheet(comp) is None:
            setattr(comp, PROP, "")             # the copy is made on a change of the value
        setattr(comp, PROP, name)
        _hide_group(comp)
        reapply(comp)
    if recompute:
        doc.recompute()
    return True


def reapply(comp):
    """The copy's table shows the instance's configuration again (FreeCAD remakes the copy when the
    part changes, with the part's active configuration). True when it changed something."""
    if is_subassembly(comp):
        sub_asm = getattr(comp, "LinkedObject", None)
        t = _table(sub_asm.Document) if sub_asm is not None else None
        if t is None:
            return False
        return _apply_sub(comp, t, getattr(comp, PROP, "") or t.active())
    if not is_copy(comp):
        return False
    want = getattr(comp, PROP, "")
    sheet = _copy_sheet(comp)
    if not want or sheet is None:
        return False
    if want not in names(comp):
        # cfg130: the part's configuration was deleted: the instance kept its name and its old size. As

        src = source(comp)
        App.Console.PrintWarning("FreeCAD: %s: configuration \"%s\" of %s no longer exists; it shows \"%s\".\n"
                                 % (comp.Label, want, src.Document.Label if src is not None else "the part",
                                    names(comp)[0] if src is None else (configuration_of_part(src) or "Default")))
        setattr(comp, PROP, "")
        _revert(comp)
        return True
    if sheet.Configuration == want:
        return False
    try:
        sheet.Configuration = want
    except Exception:
        return False
    _hide_group(comp)
    return True


def instances(doc):
    return [o for o in doc.Objects if PROP in o.PropertiesList and getattr(o, PROP, "")
            and ((o.TypeId == "App::Link" and is_copy(o)) or is_subassembly(o))]


def reapply_all(doc):
    changed = False
    for comp in instances(doc):
        changed = reapply(comp) or changed
    if changed and not _BUSY:
        _BUSY.append(1)
        try:
            doc.recompute()
        finally:
            _BUSY.pop()
    return changed


class _Observer:
    def slotRecomputedDocument(self, doc):
        if _BUSY:
            return
        try:
            if not any(True for _ in instances(doc)):
                return
        except Exception:
            return
        try:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda n=doc.Name: _later(n))
        except Exception:
            reapply_all(doc)

    def slotFinishRestoreDocument(self, doc):
        self.slotRecomputedDocument(doc)

    def slotCreatedDocument(self, doc):
        # FreeCAD 1.1 never calls slotFinishRestoreDocument on Python observers
        try:
            from . import asmgen
            asmgen.after_load(doc.Name, self.slotRecomputedDocument)
        except Exception as _fw_err:
            _fw_log("asmcfginst.py:247", _fw_err)


def _later(name):
    doc = App.listDocuments().get(name)
    if doc is not None:
        reapply_all(doc)


_observer = None


def install():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
