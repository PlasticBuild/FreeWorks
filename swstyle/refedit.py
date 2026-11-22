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

KINDS = {
    "PartDesign::Plane": "plane", "Part::DatumPlane": "plane",
    "PartDesign::Line": "axis", "Part::DatumLine": "axis",
    "PartDesign::CoordinateSystem": "cs",
    "PartDesign::Point": "point", "Part::DatumPoint": "point",
}
# what the check copies from the PropertyManager's result onto the feature being edited
ATTACH = ("AttachmentSupport", "MapMode", "MapReversed", "MapPathParameter", "AttachmentOffset")


def _picks(obj):
    out = []
    for link, subs in (getattr(obj, "AttachmentSupport", None) or []):
        for sub in (subs or ("",)):
            out.append((link, sub))
    return out[:3]


def _origin_item(obj):
    return any(p.TypeId == "App::Origin" for p in obj.InList)


def can_edit(obj):
    return (obj is not None and obj.TypeId in KINDS and not _origin_item(obj)
            and all(p in obj.PropertiesList for p in ATTACH[:2]))


def _same_picks(new, obj):
    try:
        from . import refgeom2
        return _picks(new) == _picks(obj) and new.MapMode == obj.MapMode and \
            (refgeom2.kept_cs_axes(new) or {}) == (refgeom2.kept_cs_axes(obj) or {})
    except Exception:
        return False


def _transfer_kept(new, obj):
    """rgdeep: what the PropertyManager keeps beside the attachment goes on the edited feature too: a coordinate
    system's axis picks (and its turn when a plane gives an axis), a point's distance along its curve."""
    from . import refgeom2
    if "FwAxes" in new.PropertiesList:
        import json
        try:
            data = json.loads(new.FwAxes or "{}")
        except Exception:
            data = {}
        refgeom2.keep_cs_axes(obj, refgeom2.kept_cs_axes(new) or {}, data.get("reverse") or (), data.get("rotation"))
        if new.MapMode == "Translate":
            obj.Placement = App.Placement(obj.Placement.Base, new.Placement.Rotation)
    if "FwAlongDistance" in new.PropertiesList or "FwAlongDistance" in obj.PropertiesList:
        if "FwAlongDistance" not in obj.PropertiesList:
            obj.addProperty("App::PropertyFloat", "FwAlongDistance", "FreeCAD references",
                            "Distance along the curve (mm) the point keeps; -1 for a percentage")
            obj.setEditorMode("FwAlongDistance", 2)
        obj.FwAlongDistance = float(getattr(new, "FwAlongDistance", -1.0))


def _transfer(new, obj):
    keep = ()
    if KINDS.get(obj.TypeId) in ("cs", "point") and _same_picks(new, obj) \
            and new.AttachmentOffset.isSame(App.Placement(), 1e-9):
        # the same picks with no numbers typed in this time: the position and rotation typed before stay
        keep = ("AttachmentOffset", "MapPathParameter")
    for prop in ATTACH:
        if prop in keep:
            continue
        if prop in new.PropertiesList and prop in obj.PropertiesList:
            try:
                setattr(obj, prop, getattr(new, prop))
            except Exception as _fw_err:
                _fw_log("refedit.py:copy %s" % prop, _fw_err)
    if not keep:
        try:
            _transfer_kept(new, obj)
        except Exception as _fw_err:
            _fw_log("refedit.py:copy kept", _fw_err)


def _drop(doc, new):
    try:
        group = new.getParentGeoFeatureGroup()
        if group is not None and hasattr(group, "removeObject"):
            group.removeObject(new)
    except Exception as _fw_err:
        _fw_log("refedit.py:drop group", _fw_err)
    if doc.getObject(new.Name) is not None:
        doc.removeObject(new.Name)


def _state(panel):
    """What the user can change in a Plane PropertyManager: its references and their constraints and values."""
    out = []
    for r in getattr(panel, "refs", None) or ():
        if r is None:
            out.append(None)
            continue
        out.append((getattr(r.obj, "Name", None), r.sub, r.constraint, round(float(r.value), 9), bool(r.flip),
                    int(r.count), bool(getattr(r, "flip_normal", False))))
    return tuple(out)


def _panel(obj):
    doc = obj.Document
    kind = KINDS[obj.TypeId]
    from . import refplane
    body = refplane.body_of(doc)
    picks = _picks(obj)
    if kind == "plane":
        refs, _index = refplane.kept_refs(obj)
        if refs:
            picks = [(r.obj, r.sub) for r in refs]
        panel = refplane.PlanePanel(doc, body, picks)
        if refs:
            for i, kept in enumerate(refs[:3]):
                r = panel.refs[i]
                if r is None:
                    continue
                for name in ("constraint", "value", "flip", "count", "flip_normal", "on_curve", "screen"):
                    setattr(r, name, getattr(kept, name))
            panel.update(keep=True)
        panel.untouched = None if refs else _state(panel)    # a plane made otherwise: no constraints kept
        return panel, "planes"
    if kind == "axis":
        from . import refaxis
        return refaxis.AxisPanel(doc, body, picks), None
    from . import refgeom2
    if kind == "cs":
        return _cs_panel(obj, picks), "made"
    return refgeom2.PointPM(doc, picks), "made"


def _cs_axes(obj, picks):
    """rgdeep: (origin, {axis: pick}) of a coordinate system: the kept axis picks, else read from FreeCAD's mode
    (OZX: the second reference is the Z axis, the third the X axis). Put in the boxes one after another, a Z-only
    system's Z edge went in the X box, and OK turned the system."""
    from . import refgeom2
    origin = picks[0] if picks else None
    kept = refgeom2.kept_cs_axes(obj)
    if kept is not None:
        return origin, kept
    mode = getattr(obj, "MapMode", "")
    axes = {}
    if len(mode) == 3 and mode[0] == "O" and all(c in "XYZ" for c in mode[1:]):
        for letter, pick in zip(mode[1:], picks[1:3]):
            axes[letter] = pick
    return origin, axes


def _cs_panel(obj, picks):
    from . import refgeom2
    origin, axes = _cs_axes(obj, picks)
    panel = refgeom2.CoordinateSystemPM(obj.Document, [origin] if origin is not None else [])
    try:
        for a, pick in axes.items():
            box = panel.axis_box[a]
            box.items = [pick]
            box.show_items()
        if axes:
            panel.update()
    except Exception as _fw_err:
        _fw_log("refedit.py:cs_panel", _fw_err)
    return panel


def edit(obj):
    """Opens obj's PropertyManager to edit it; False when obj is not reference geometry this module edits."""
    if not can_edit(obj) or Gui.Control.activeDialog():
        return False
    doc = obj.Document
    before = {o.Name for o in doc.Objects}
    shown = bool(obj.ViewObject.Visibility) if obj.ViewObject is not None else True
    try:
        panel, made_attr = _panel(obj)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: %s not opened in its PropertyManager: %s\n" % (obj.Label, error))
        return False
    if obj.ViewObject is not None:
        obj.ViewObject.Visibility = False        # the preview stands in for it while it is edited
    accept, reject = panel.accept, panel.reject

    def _restore():
        try:
            if doc.getObject(obj.Name) is not None and obj.ViewObject is not None:
                obj.ViewObject.Visibility = shown
        except Exception as _fw_err:
            _fw_log("refedit.py:restore", _fw_err)

    def _accept():
        if not getattr(panel, "ok", False):
            return accept()
        news = [o for o in doc.Objects if o.Name not in before and o.TypeId == obj.TypeId]
        same = getattr(panel, "untouched", None) is not None and _state(panel) == panel.untouched
        if news:
            if not same:        # a plane made outside the PM, OK with nothing changed: it stays where it is
                _transfer(news[0], obj)
            for n in news:
                _drop(doc, n)
            if made_attr:
                # unchanged: nothing is kept on it either (kept constraints would move it at the next rebuild)
                setattr(panel, made_attr, [] if same else [obj])
            if hasattr(panel, "line"):
                panel.line = obj
            doc.recompute()
        done = accept()
        _restore()
        return done

    def _reject():
        done = reject()
        _restore()
        return done

    panel.accept, panel.reject = _accept, _reject
    panel.editing = obj
    Gui.Control.showDialog(panel)
    return True
