""







import json

import FreeCAD as App

PROP = "SWSectionView"          # on the drawing view: the saved section view it shows ("" = none)
KIND = "FWSavedSection"


def _fw_log(site, err):
    try:
        App.Console.PrintLog("FreeCAD: %s: %s\n" % (site, err))
    except Exception:
        pass


def _std_place(doc, name):
    """Front/Top/Right in the model file: its body's origin plane (one body), else the global plane."""
    from . import sectionview as sv
    feature, rotation = sv.STANDARD[name]
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"] if doc is not None else []
    origin = getattr(bodies[0], "Origin", None) if len(bodies) == 1 else None
    if origin is not None:
        for item in origin.OriginFeatures:
            if getattr(item, "Role", "") == feature:
                try:
                    return item.getGlobalPlacement()
                except Exception:
                    break
    return App.Placement(App.Vector(), rotation)


def settings_for(doc, data):
    """The saved section's settings, its standard planes fixed to doc's (not the active file's)."""
    from . import sectionview as sv, sectionmore as sm
    s = sm._unpack(json.loads(data) if isinstance(data, str) else data, sv.Settings())
    sm.defaults(s)
    for x in [s] + list(getattr(s, "extra", [])):
        ref = tuple(getattr(x, "ref", ()) or ())
        if ref and ref[0] == "std":
            x.ref_place = _std_place(doc, ref[1])
            x.ref = ("saved",) + ref[1:]
    return s


def cut_shape(objs, data):
    """The model objs as the saved section shows them: every cut body without the removed region."""
    import Part
    from . import sectionmore as sm
    shapes = []
    for o in objs or []:
        try:
            sh = o.Shape.copy()
        except Exception as _fw_err:
            _fw_log("secdrawview shape", _fw_err)
            continue
        if not sh.isNull():
            shapes.append((o.Name, sh))
    if not shapes:
        return Part.Shape()
    box = App.BoundBox()
    for _n, sh in shapes:
        box.add(sh.BoundBox)
    size = max(box.DiagonalLength, 1.0)
    doc = objs[0].Document
    s = settings_for(doc, data)
    region = sm.removed_region(s, size, box.Center)
    out = []
    for name, sh in shapes:
        out.append(sm.kept(sh, region) if sm.body_cut(s, name) else sh)
    out = [x for x in out if not x.isNull()]
    return out[0] if len(out) == 1 else Part.makeCompound(out)


class SavedSectionShape:
    """The model as a saved section view cuts it, kept up to date with the model."""

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        for kind, name, tip in (("App::PropertyXLinkList", "Base", "the model"),
                                ("App::PropertyString", "SectionName", "the saved section view"),
                                ("App::PropertyString", "SectionData", "the section's settings")):
            if not hasattr(obj, name):
                obj.addProperty(kind, name, "FreeCAD", tip)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        obj.Shape = cut_shape(list(obj.Base or []), obj.SectionData or "{}")


def _holder(v):
    return next((o for o in list(getattr(v, "Source", []) or []) if hasattr(o, "SectionData")), None)


def _reproject(v):
    page = None
    try:
        page = next((p for p in v.InList if p.isDerivedFrom("TechDraw::DrawPage")), None)
    except Exception:
        page = None
    keep = getattr(page, "KeepUpdated", True) if page is not None else True
    try:
        if page is not None and not keep:
            page.KeepUpdated = True
        v.touch()
        v.Document.recompute()
    except Exception as _fw_err:
        _fw_log("secdrawview recompute", _fw_err)
    finally:
        if page is not None and not keep:
            page.KeepUpdated = False


def apply(v, name):
    """The view shows the saved section view name of its model (cut), or the whole model again when name is not
    a saved section. Returns True when the view is cut."""
    from . import sectionmore as sm, drawings as D
    holder = _holder(v)
    if holder is not None:
        model = list(holder.Base)
        mdoc = model[0].Document if model else None
    else:
        model = list(getattr(v, "XSource", []) or [])
        mdoc = model[0].Document if model else None
    data = sm.saved(mdoc).get(name) if (mdoc is not None and name) else None
    if PROP not in v.PropertiesList:
        v.addProperty("App::PropertyString", PROP, "FreeCAD", "the saved section view the view shows")
    if data is None:
        if holder is not None:
            v.Source = [o for o in v.Source if o is not holder]
            D.link_source(v, model)
            v.Document.removeObject(holder.Name)
            _reproject(v)
        v.SWSectionView = ""
        return False
    if holder is None:
        doc = v.Document
        holder = doc.addObject("Part::FeaturePython", KIND)
        SavedSectionShape(holder)
        holder.Base = model
        holder.Label = "%s (%s)" % (name, v.Label)
        try:
            holder.ViewObject.Proxy = 0
            holder.ViewObject.Visibility = False
            holder.ViewObject.ShowInTree = False
        except Exception as _fw_err:
            _fw_log("secdrawview view object", _fw_err)
        v.XSource = []
        v.Source = [holder]
    holder.SectionName = name
    holder.SectionData = json.dumps(data)
    holder.recompute()
    v.SWSectionView = name
    _reproject(v)
    return True


def after_named(v, name):
    try:
        if v is not None and (name in _saved_names(v) or _holder(v) is not None):
            apply(v, name)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: section in drawing view: %s\n" % error)


def _saved_names(v):
    from . import sectionmore as sm
    holder = _holder(v)
    model = list(holder.Base) if holder is not None else list(getattr(v, "XSource", []) or [])
    return set(sm.saved(model[0].Document)) if model else set()


_DONE = []


def install():
    """Wraps the View Palette's place() and the drawing views' named orientation (Model View's More views)."""
    if _DONE:
        return
    _DONE.append(True)
    from . import drawpalette as DP, drawings as D
    place0 = DP.place

    def place(page, doc, name, at, *a, **k):
        v = place0(page, doc, name, at, *a, **k)
        if v is not None and isinstance(name, str) and name.startswith(DP.NAMED):
            after_named(v, name[len(DP.NAMED):])
        return v
    place.__wrapped__ = place0
    DP.place = place

    named0 = getattr(D, "_name_orientation", None)
    if named0 is not None:
        def _name_orientation(v, name):
            named0(v, name)
            after_named(v, name)
        _name_orientation.__wrapped__ = named0
        D._name_orientation = _name_orientation
    try:
        from . import drawselect as DS
        orient0 = DS.set_orientation

        def set_orientation(v, name):
            orient0(v, name)
            if _holder(v) is not None:
                apply(v, "")             # a standard orientation picked: the whole model again
        set_orientation.__wrapped__ = orient0
        DS.set_orientation = set_orientation
    except Exception as _fw_err:
        _fw_log("secdrawview drawselect", _fw_err)
