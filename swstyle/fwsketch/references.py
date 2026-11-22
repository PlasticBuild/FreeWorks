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

PROPERTY = "FreeWorksAutoRefs"


def _name(obj):
    return obj if isinstance(obj, str) else obj.Name


def _element(sub):
    """Edge2 from Edge2, ;g2;SKT.Edge2 or a mapped name."""
    return sub.rsplit(";", 1)[-1].rsplit(".", 1)[-1]


def _link_list(sketch):
    out = []
    for obj, subs in sketch.ExternalGeometry:
        for sub in (subs if isinstance(subs, (list, tuple)) else (subs,)):
            out.append((obj.Name, _element(sub)))
    return out


def _ref(geo):
    try:
        import Sketcher
        return Sketcher.ExternalGeometryFacade(geo).Ref
    except Exception:
        return ""


def _links(sketch):
    """(object name, element) behind every external geometry, in geo order (-3, -4, ...).
    One link can give several geometries (an intersection), and they carry its "Box.Face1" ref;
    stock 1.1.4 leaves the ref of a projected vertex empty, so such a geometry takes the next
    link in order."""
    links = _link_list(sketch)
    out, j = [], -1
    for geo in sketch.ExternalGeo[2:]:
        ref = _ref(geo)
        if "." in ref:
            name, element = ref.split(".", 1)
            key = (name, _element(element))
            hit = next((k for k in range(max(j, 0), len(links)) if links[k] == key), None)
            j = hit if hit is not None else j + 1
        else:
            j += 1
        out.append(links[j] if 0 <= j < len(links) else (None, None))
    return out


def _record(sketch):
    try:
        return list(getattr(sketch, PROPERTY))
    except AttributeError:
        return []


def _store(sketch, keys):
    if not hasattr(sketch, PROPERTY):
        if not keys:
            return
        sketch.addProperty("App::PropertyStringList", PROPERTY, "FreeCAD",
                           "Part references FreeCAD made for relations (hidden)")
        try:
            sketch.setEditorMode(PROPERTY, 2)
        except Exception as _fw_err:
            _fw_log("fwsketch/references.py:98", _fw_err)
    if list(getattr(sketch, PROPERTY)) != keys:
        setattr(sketch, PROPERTY, keys)


def _key(name, element):
    return "%s.%s" % (name, _element(element))


def _binder_name(sketch, name):
    """The hidden ExtRef binder (convertentities.binder_for) that stands in for the object called
    name in this sketch's Body, when there is one: a Body's sketch cannot link outside its Body."""
    try:
        body = sketch.getParentGeoFeatureGroup()
        obj = sketch.Document.getObject(name)
        if body is None or obj is None:
            return None
        for o in body.Group:
            if getattr(o, "FWExtRefOf", None) is obj:
                return o.Name
    except Exception as _fw_err:
        _fw_log("fwsketch/references.py:119", _fw_err)
    return None


def source_of(obj):
    """The object a reference really points at: the outside solid behind an ExtRef binder."""
    return getattr(obj, "FWExtRefOf", None) or obj


def find(sketch, obj, element):
    name, element = _name(obj), _element(element)
    links = _links(sketch)
    for k, link in enumerate(links):
        if link == (name, element):
            return -3 - k
    if any(link[1] == element for link in links):
        binder = _binder_name(sketch, name)
        if binder:
            for k, link in enumerate(links):
                if link == (binder, element):
                    return -3 - k
    return None


def ref_of(sketch, geo):
    if hasattr(sketch, "getExternalReference"):
        try:
            ref = sketch.getExternalReference(geo)[0]
            if "." in ref:
                name, element = ref.split(".", 1)
                return name, _element(element)
        except Exception as _fw_err:
            _fw_log("fwsketch/references.py:151", _fw_err)
    links = _links(sketch)
    k = -geo - 3
    if 0 <= k < len(links):
        return links[k]
    return None, None


def is_automatic(sketch, geo):
    if hasattr(sketch, "getExternalReference"):
        try:
            return bool(sketch.getExternalReference(geo)[1])
        except Exception as _fw_err:
            _fw_log("fwsketch/references.py:164", _fw_err)
    name, element = ref_of(sketch, geo)
    return name is not None and _key(name, element) in _record(sketch)


def automatic(sketch):
    return [-3 - k for k in range(len(_links(sketch))) if is_automatic(sketch, -3 - k)]


def mark(sketch, name, element, on=True):
    keys = _record(sketch)
    key = _key(_name(name), element)
    if on and key not in keys:
        keys.append(key)
    elif not on and key in keys:
        keys.remove(key)
    _store(sketch, keys)


def add(sketch, obj, element):
    """geo of the reference to element of obj; a new one is automatic. None when FreeCAD cannot
    reference it."""
    name = _name(obj)
    if hasattr(sketch, "addAutomaticReference"):
        try:
            return sketch.addAutomaticReference(name, _element(element))
        except Exception as _fw_err:
            _fw_log("fwsketch/references.py:191", _fw_err)
    geo = find(sketch, name, element)
    if geo is not None:
        return geo
    try:
        sketch.addExternal(name, _element(element))
    except ValueError:
        # outside the sketch's Body: through its hidden ExtRef binder (same element names)
        try:
            from .. import convertentities
            source = sketch.Document.getObject(name)
            b = convertentities.binder_for(sketch, source) if source is not None else None
            if b is None:
                return None
            geo = find(sketch, b.Name, element)
            if geo is not None:
                return geo
            sketch.addExternal(b.Name, _element(element))
            name = b.Name
        except Exception:
            return None
    except Exception:
        return None
    geo = find(sketch, name, element)
    if geo is not None:
        mark(sketch, name, element, True)
    return geo


def _used(sketch):
    used = set()
    for c in sketch.Constraints:
        for g in (c.First, c.Second, c.Third):
            if g is not None and g <= -3:
                used.add(g)
    return used


def prune(sketch):
    ""

    used = _used(sketch)
    links = _links(sketch)
    gone = {links[-g - 3] for g in automatic(sketch) if g not in used}
    gone -= {links[-g - 3] for g in used if 0 <= -g - 3 < len(links)}  # a link's other geometry is used
    if not gone:
        return 0
    keys = _record(sketch)
    order = _link_list(sketch)
    for k in sorted((order.index(link) for link in gone), reverse=True):
        name, element = order[k]
        types = list(sketch.ExternalTypes)
        sketch.delExternal(k)  # the link's index: the higher ones go first, the rest keep theirs
        if len(types) > k and list(sketch.ExternalTypes) == types:
            # stock 1.1.4 leaves ExternalTypes unshifted, so an intersection link would pass its
            # type to the next one (which then goes missing)
            sketch.ExternalTypes = types[:k] + types[k + 1:]
        if _key(name, element) in keys:
            keys.remove(_key(name, element))
    _store(sketch, keys)
    return len(gone)
