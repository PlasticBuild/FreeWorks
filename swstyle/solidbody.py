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
except ImportError:
    Gui = None

_SKIP = ("PartDesign::", "App::", "Sketcher::", "Spreadsheet::", "TechDraw::", "Part::Datum")


def _solid(o):
    try:
        return not o.Shape.isNull() and bool(o.Shape.Solids)
    except Exception:
        return False


_GEN = [0]            # bumped by any document change (an object changed, added, removed, a rebuild)
_CACHE = {}           # document name -> (_GEN, its loose solids)


class _Changes:
    def _bump(self, *args):
        _GEN[0] += 1
    slotChangedObject = slotCreatedObject = slotDeletedObject = slotRecomputedDocument = _bump
    slotDeletedDocument = slotUndoDocument = slotRedoDocument = _bump


_OBSERVER = []


def loose_solids(doc):
    """Top-level shown solids not used by another feature, in a part with no PartDesign Body.

    Many Features commands ask this from IsActive, which FreeCAD polls several times a second: the
    answer is kept until something in a document changes (on 144 loose parts it cost 9 ms a call)."""
    if doc is None:
        return []
    if not _OBSERVER:
        try:
            _OBSERVER.append(_Changes())
            App.addDocumentObserver(_OBSERVER[0])
        except Exception:
            pass
    kept = _CACHE.get(doc.Name) if _OBSERVER else None
    if kept is not None and kept[0] == _GEN[0] and all(_alive(o) for o in kept[1]):
        return list(kept[1])
    out = _loose_solids(doc)
    _CACHE[doc.Name] = (_GEN[0], list(out))
    return out


def _alive(o):
    try:
        return o.Document is not None and o.isValid()
    except Exception:
        return False


def _in_cam_job(o):
    """o belongs to a CAM Job (its Model group's copy of the part, its Stock): the Job keeps those
    as solids of its own, so with a Job in the file Split and Intersect found no single part (Add-Ins
    sweep, 11-19)."""
    def job(u):
        return u.TypeId.startswith(("Path::", "CAM::")) or type(getattr(u, "Proxy", None)).__name__ == "ObjectJob"
    try:
        for u in o.InList:
            # linked by the Job itself (Stock), or in one of its groups (Model): not a solid that merely
            # feeds a member of the Job (the design part the Job's model copies)
            if job(u) or (u.TypeId.startswith("App::DocumentObjectGroup") and any(job(g) for g in u.InList)):
                return True
    except Exception as _fw_err:
        _fw_log("solidbody.py:cam", _fw_err)
    return False


def _cam_part(u):
    """u is a CAM Job or one of its members (the model clone, the stock): using a solid does not make it
    a step of another feature."""
    proxy = getattr(u, "Proxy", None)
    return u.TypeId.startswith(("Path::", "CAM::")) or type(proxy).__name__ == "ObjectJob" or _in_cam_job(u)


def _cam_tool(o):
    """A Body a CAM Job keeps for a tool bit's shape: not a body of the design."""
    try:
        return any(_cam_part(u) for u in o.InListRecursive)
    except Exception:
        return False


def _loose_solids(doc):
    if any(o.TypeId == "PartDesign::Body" and not _cam_tool(o) for o in doc.Objects):
        return []
    out = []
    for o in doc.Objects:
        if o.TypeId.startswith(_SKIP) or not hasattr(o, "Shape") or not _solid(o):
            continue
        users = [u for u in o.InList if not u.TypeId.startswith(("App::DocumentObjectGroup", "App::Part"))
                 and not _cam_part(u)]
        if users:
            continue                                  # the input of a boolean or a body already
        if _in_cam_job(o):
            continue                                  # a CAM Job's model copy or stock: no part of the design
        try:
            if not o.ViewObject.Visibility:
                continue
        except Exception as _fw_err:
            _fw_log("solidbody.py:52", _fw_err)
        out.append(o)
    return out


def loose_solid(doc):
    """The solid a feature would go on: the picked one, or the only one."""
    found = loose_solids(doc)
    if Gui is not None:
        try:
            picked = [s.Object for s in Gui.Selection.getSelectionEx(doc.Name)]
            for o in picked:
                if o in found:
                    return o
        except Exception as _fw_err:
            _fw_log("solidbody.py:67", _fw_err)
    return found[0] if len(found) == 1 else None


def adopt(doc, solid=None):
    """A PartDesign Body with solid as its base feature, made the active body. None if nothing fits."""
    solid = solid or loose_solid(doc)
    if solid is None:
        return None
    doc.openTransaction("Body")
    try:
        body = doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = solid
        try:
            for group in solid.InList:
                if group.TypeId == "App::Part":
                    group.addObject(body)
                    break
        except Exception as _fw_err:
            _fw_log("solidbody.py:86", _fw_err)
        doc.recompute()
    finally:
        doc.commitTransaction()
    if Gui is not None:
        try:
            Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
        except Exception as _fw_err:
            _fw_log("solidbody.py:94", _fw_err)
    return body


def tip_or_base(body):
    """The body's tip, or its base feature when no feature was added yet."""
    tip = getattr(body, "Tip", None)
    return tip if tip is not None else getattr(body, "BaseFeature", None)
