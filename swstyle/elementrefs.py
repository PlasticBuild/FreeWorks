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


LINK, NAMES = "FWElementRefs", "FWElementNames"


def _flat(value):
    out = []
    for item in list(value or []):
        if not isinstance(item, tuple):
            continue
        src, subs = item
        for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
            out.append((src, sub.split(".")[-1]))
    return out


def follow(obj, entries, apply):
    """entries(): [(object, element name)] the feature's text names now; apply(moved) rewrites the
    text with moved = {(object name, old name): new name}. Returns True when the text changed."""
    try:
        if LINK not in obj.PropertiesList:
            obj.addProperty("App::PropertyLinkSubListGlobal", LINK, "FreeCAD", "The elements the feature names as text")
            obj.addProperty("App::PropertyStringList", NAMES, "FreeCAD", "Those names when they were written")
            obj.setEditorMode(LINK, 2)
            obj.setEditorMode(NAMES, 2)
        was = list(getattr(obj, NAMES))
        now = _flat(getattr(obj, LINK))
        changed = False
        if was and len(was) == len(now):
            moved = {}
            for text, (src, name) in zip(was, now):
                oname, _sep, old = text.partition(":")
                if src is not None and src.Name == oname and name and not name.startswith("?") and name != old:
                    moved[(oname, old)] = name
            if moved:
                apply(moved)
                changed = True
        current = [(o, n) for o, n in entries() if o is not None and n]
        texts = ["%s:%s" % (o.Name, n) for o, n in current]
        linked = ["%s:%s" % (o.Name, n) for o, n in _flat(getattr(obj, LINK)) if o is not None]
        if texts != was or linked != texts:
            setattr(obj, LINK, [(o, n) for o, n in current])
            setattr(obj, NAMES, texts)
        return changed
    except Exception as _fw_err:
        _fw_log("elementrefs.follow", _fw_err)
        return False
