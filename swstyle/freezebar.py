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

from . import paths

PARAM = "FreezeBar"
BODY = "PartDesign::Body"


def enabled():
    return paths.params().GetBool(PARAM, False)


def set_enabled(on):
    paths.params().SetBool(PARAM, bool(on))


def frozen(obj):
    """FreeCAD's freeze on obj. An object in error reports its error, not "Freezed", in its status
    string; a freeze also makes every property read-only, Label too (features-438: a frozen fillet in
    error was never thawed, and FreeCAD refuses to save a document with a frozen object)."""
    try:
        if "Freez" in (obj.getStatusString() or ""):
            return True
        if obj.isValid():
            return False
        return "ReadOnly" in (obj.getPropertyStatus("Label") or [])
    except Exception:
        return False


def thaw_for_save(doc):
    ""


    if Gui is None:
        return []
    held = [o for o in doc.Objects if frozen(o)]
    for o in reversed(held):
        if frozen(o):
            _toggle([o])
    return [o.Name for o in held]


def refreeze_after_save(doc, names):
    """The objects thaw_for_save thawed, frozen again in tree order (the Freeze bar as it was)."""
    if Gui is None or not names:
        return
    g = Gui.getDocument(doc.Name)
    was = g.Modified if g is not None else None     # a save leaves it clean; an autosave leaves it as it was
    for n in names:
        o = doc.getObject(n)
        if o is not None and not frozen(o):
            _toggle([o])
    try:
        if g is not None and was is not None and g.Modified != was:
            g.Modified = was
    except Exception as _fw_err:
        _fw_log("freezebar.py:refreeze", _fw_err)


def body_of(obj):
    for parent in getattr(obj, "InList", []):
        if parent.isDerivedFrom(BODY):
            return parent
    return None


def features(body):
    """The body's features in tree order (the ones the bar can freeze)."""
    return [o for o in body.Group if not o.isDerivedFrom("App::Origin")]


def bar(body):
    """The last frozen feature of the body (the bar sits under it), or None (bar at the top)."""
    last = None
    for o in features(body):
        if frozen(o):
            last = o
    return last


def _toggle(objs):
    """FreeCAD's Std_ToggleFreeze on these objects only."""
    if not objs:
        return
    sel = Gui.Selection.getSelectionEx("*", 0)
    Gui.Selection.clearSelection()
    try:
        for o in objs:
            Gui.Selection.addSelection(o)
        Gui.runCommand("Std_ToggleFreeze", 0)
    finally:
        Gui.Selection.clearSelection()
        for s in sel:
            try:
                Gui.Selection.addSelection(s.Object, s.SubElementNames)
            except Exception as _fw_err:
                _fw_log("freezebar.py:88", _fw_err)


def freeze_to(feature, body=None):
    """The bar under feature: it and every feature above it in its body frozen, the rest thawed.
    feature None puts the bar at the top of body (nothing frozen). One recompute after."""
    body = body or (body_of(feature) if feature is not None else None)
    if body is None:
        return False
    items = features(body)
    if feature is not None and feature not in items:
        return False
    try:
        from . import editguard
        if feature is not None and editguard.rolled_back(feature):
            return False
    except Exception as _fw_err:
        _fw_log("freezebar.py:105", _fw_err)
    cut = items.index(feature) + 1 if feature is not None else 0
    want = {o.Name: i < cut for i, o in enumerate(items)}
    thaw = [o for o in reversed(items) if frozen(o) and not want[o.Name]]
    freeze = [o for o in items if not frozen(o) and want[o.Name]]
    # thaw from the bottom up and one at a time: FreeCAD's toggle also thaws an object's dependents
    for o in thaw:
        if frozen(o):
            _toggle([o])
    for o in thaw:
        try:
            o.touch()             # changed while frozen (an edited dimension): it rebuilds now
        except Exception as _fw_err:
            _fw_log("freezebar.py:118", _fw_err)
    for o in freeze:
        if not frozen(o):
            _toggle([o])
    body.Document.recompute()
    return True


def unfreeze_all(doc=None):
    doc = doc or App.ActiveDocument
    for body in [o for o in (doc.Objects if doc else []) if o.isDerivedFrom(BODY)]:
        freeze_to(None, body)


def can_edit(obj):
    ""
    return not frozen(obj)
