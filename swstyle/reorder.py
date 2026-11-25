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

BODY = "PartDesign::Body"


def body_of(obj):
    try:
        for parent in obj.InList:
            if parent.TypeId == BODY and obj in parent.Group:
                return parent
    except Exception as _fw_err:
        _fw_log("reorder.py:37", _fw_err)
    return None


PICK_FIELDS = ("Base", "NeutralPlane", "PullDirection", "Faces")


def _picks(obj, base):
    ""

    out = []
    for name in PICK_FIELDS:
        try:
            value = getattr(obj, name, None)
        except Exception:
            continue
        if isinstance(value, tuple) and len(value) == 2 and hasattr(value[0], "Name"):
            value = [value]
        if not isinstance(value, (list, tuple)):
            continue
        for item in value:
            try:
                o, subs = item
            except Exception:
                continue
            if o is not base:
                continue
            for sub in ([subs] if isinstance(subs, str) else list(subs or ())):
                if sub:
                    out.append((name, sub))
    return out


def _picks_on(obj, base):
    ""

    return bool(_picks(obj, base))


def _uses(obj):
    """What obj is built on (not the BaseFeature chain the body keeps)."""
    base = getattr(obj, "BaseFeature", None)
    return [d for d in obj.OutList if d is not base or _picks_on(obj, d)]


def _made_by(obj):
    ""


    try:
        from . import suppress
    except Exception:
        return []
    try:
        return [d for d in suppress._links(obj) if d is not obj and suppress._solid_feature(d)]
    except Exception:
        return []
    finally:
        suppress._elements.clear()


def unit(obj):
    """obj and the sketches only it uses, which go with it (they sit under it in the tree)."""
    body = body_of(obj)
    if body is None:
        return [obj]
    group = list(body.Group)
    out = []
    for d in _uses(obj):
        if d in group and d.isDerivedFrom("Sketcher::SketchObject") and \
                all(u is obj or u is body or u.TypeId in ("App::Origin",) or u.isDerivedFrom("App::DocumentObjectGroup")
                    for u in d.InList):
            out.append(d)
    out.sort(key=group.index)
    return out + [obj]


def new_order(objs, target, after):
    """The body's Group with objs' units moved before (or after) target's unit, or None."""
    objs = [o for o in objs if o is not None]
    if not objs or target is None:
        return None
    body = body_of(target)
    if body is None or any(body_of(o) is not body for o in objs):
        return None
    group = list(body.Group)
    moving = []
    for o in sorted(objs, key=group.index):
        for e in unit(o):
            if e not in moving:
                moving.append(e)
    if target in moving:
        return None
    rest = [o for o in group if o not in moving]
    tu = [e for e in unit(target) if e in rest]
    at = rest.index(tu[-1]) + 1 if after else rest.index(tu[0])
    return rest[:at] + moving + rest[at:]


def problem(order):
    """Why the order cannot be built (the first feature that would come before what it uses), or ''."""
    if order is None:
        return "Features can only move within their own body."
    place = {o.Name: i for i, o in enumerate(order)}

    def shown(o):
        """The tree's row for o: a sketch sits under the feature built on it."""
        if o.isDerivedFrom("Sketcher::SketchObject"):
            for u in o.InList:
                if u in order and o in unit(u):
                    return u.Label
        return o.Label
    for i, o in enumerate(order):
        for d in _uses(o):
            if d.Name in place and place[d.Name] > i and not _picks_found(o, d, order[:i]) \
                    and _support_face(o, d, order[:i]) is None:
                return "%s cannot come before %s: it is built on it." % (shown(o), shown(d))
        for d in _made_by(o):
            if d.Name in place and place[d.Name] > i:
                return "%s cannot come before %s: it is built on it." % (shown(o), shown(d))
    return ""


def _picks_found(obj, base, before):
    ""


    if base is not getattr(obj, "BaseFeature", None):
        return False
    solids = [o for o in before if o.isDerivedFrom("PartDesign::Feature") and o.TypeId != BODY]
    if not solids:
        return False
    try:
        from . import picksgeo
        subs = [sub.split(".")[-1].lstrip("?") for _f, sub in _picks(obj, base)]
        shape = solids[-1].Shape
        if "Invalid" in base.State:
            sigs = [sig for _sub, sig in (picksgeo.remembered(obj) or [])]
        else:
            sigs = [picksgeo.signature(base.Shape, sub) for sub in subs]
        if not sigs or None in sigs:
            return False
        return all(picksgeo.match(shape, sig) is not None for sig in sigs)
    except Exception:
        return False


def _support_face(sketch, base, before):
    ""



    try:
        if not sketch.isDerivedFrom("Sketcher::SketchObject"):
            return None
        support = list(sketch.AttachmentSupport or [])
    except Exception:
        return None
    if len(support) != 1 or support[0][0] is not base:
        return None
    subs = [x for x in (support[0][1] or []) if x]
    if len(subs) != 1 or not subs[0].startswith("Face"):
        return None
    solids = [o for o in before if o.isDerivedFrom("PartDesign::Feature") and o.TypeId != BODY]
    if not solids:
        return None
    try:
        from . import picksgeo
        sig = picksgeo.signature(base.Shape, subs[0])
        if sig is None:
            return None
        name = picksgeo.match(solids[-1].Shape, sig)
        return (solids[-1], name) if name else None
    except Exception:
        return None


def _reattach(order):
    """Sketches moved above the feature they were drawn on go onto the same face of the feature now
    above them."""
    for i, o in enumerate(order):
        try:
            support = list(o.AttachmentSupport or []) if o.isDerivedFrom("Sketcher::SketchObject") else []
        except Exception:
            continue
        if len(support) != 1 or support[0][0] not in order or order.index(support[0][0]) < i:
            continue
        got = _support_face(o, support[0][0], order[:i])
        if got is not None:
            o.AttachmentSupport = [(got[0], got[1])]


def can_move(objs, target, after=False):
    order = new_order(objs, target, after)
    return order is not None and order != list(body_of(target).Group) and not problem(order)


def why_not(objs, target, after=False):
    order = new_order(objs, target, after)
    if order is not None and order == list(body_of(target).Group):
        return "The features are there already."
    if order is None and target is not None and body_of(target) is not None and \
            all(body_of(o) is body_of(target) for o in objs if o is not None):
        return "%s goes with %s: it cannot move next to itself." % (target.Label, objs[0].Label)
    return problem(order)


def _solids(body):
    return [o for o in body.Group if o.isDerivedFrom("PartDesign::Feature") and o.TypeId != BODY]


def move(objs, target, after=False):
    """Reorder (one Undo step) and rebuild. Returns True when the features moved."""
    order = new_order(objs, target, after)
    if order is None or problem(order) or order == list(body_of(target).Group):
        return False
    body = body_of(target)
    doc = body.Document
    old = list(body.Group)
    tip = body.Tip
    tip_at_end = bool(_solids(body)) and tip is _solids(body)[-1]
    moving = [o for o in order if o in set(old) and (o in objs or o in sum((unit(x) for x in objs), []))]
    from . import picksgeo
    saved = picksgeo.dressups(old)
    faces = _face_picks(old)
    doc.openTransaction("Reorder")
    try:
        for e in moving:
            body.removeObject(e)
        for e in moving:
            i = order.index(e)
            # next to what is in the body already: a block moved to the top has no row before it,
            # and the row after it may be one of the moving ones, not put back yet
            group = list(body.Group)
            before = next((order[j] for j in range(i - 1, -1, -1) if order[j] in group), None)
            if before is not None:
                body.insertObject(e, before, True)
            else:
                later = next((order[j] for j in range(i + 1, len(order)) if order[j] in group), None)
                if later is not None:
                    body.insertObject(e, later, False)
                else:
                    body.addObject(e)
        _reattach(order)
        # the rollback bar stays where it was: at the end, or under the same feature
        solids = _solids(body)
        if tip_at_end and solids:
            body.Tip = solids[-1]
        elif tip is not None and tip in body.Group:
            body.Tip = tip
        doc.recompute()
        for _round in range(4):       # a repaired fillet renames the edges of the features after it
            if not picksgeo.repick(saved) and not _follow_faces(faces, body):
                break
            doc.recompute()
        _leave_folders(body, moving)
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    return [o.Name for o in body.Group] == [o.Name for o in order]


def _face_picks(objs):
    ""

    from . import picksgeo
    out = []
    for obj in objs:
        base = getattr(obj, "BaseFeature", None)
        if base is None or "Faces" not in obj.PropertiesList or obj.isDerivedFrom("PartDesign::DressUp"):
            continue
        picks = [sub for f, sub in _picks(obj, base) if f == "Faces"]
        if not picks:
            continue
        try:
            shape = base.Shape
            got = []
            for sub in picks:
                plain = sub.split(".")[-1].lstrip("?")
                got.append((plain, picksgeo.signature(shape, plain), len(shape.Faces), shape.getElement(plain).Surface.TypeId))
        except Exception:
            continue
        if all(sig is not None for _s, sig, _n, _k in got):
            out.append((obj, base.Name, got))
    return out


def _follow_faces(saved, body):
    ""

    from . import picksgeo
    changed = []
    for obj, old_base, picks in saved:
        base = getattr(obj, "BaseFeature", None)
        if base is None or base.Name == old_base or "Invalid" in base.State:
            continue
        try:
            value = list(getattr(obj, "Faces", None) or [])
            if not value or any((item[0] if isinstance(item, tuple) else item) is base for item in value):
                continue
        except Exception:
            continue
        shape = base.Shape
        names = []
        for plain, sig, count, kind in picks:
            name = picksgeo.match(shape, sig) or picksgeo.match_near(shape, sig)
            if name is None:
                # a Scale or Move Face above changed the face's size or place but not the part's
                # faces: the same face by number, when it is the same kind of surface
                try:
                    if len(shape.Faces) == count and shape.getElement(plain).Surface.TypeId == kind:
                        name = plain
                except Exception:
                    name = None
            if name is None:
                break
            names.append(name)
        if len(names) != len(picks):
            continue
        try:
            obj.Faces = [(base, tuple(names))]
            changed.append(obj)
        except Exception as error:
            _fw_log("reorder.py:follow faces", error)
    return changed


def _leave_folders(body, moving):
    ""

    try:
        from . import treefolders
    except Exception:
        return
    group = [o.Name for o in body.Group]
    for folder in treefolders.folders(body.Document):
        names = [n for n in folder.Items if n in group]
        if not names:
            continue
        rows = sorted(group.index(n) for n in names)
        solids = [n for n in group if body.Document.getObject(n).isDerivedFrom("PartDesign::Feature")]
        feat = [n for n in solids if n in names]
        if not feat:
            continue
        span = solids[solids.index(feat[0]):solids.index(feat[-1]) + 1]
        strays = [n for n in span if n not in names]
        if not strays:
            continue
        # keep the larger run of the folder's features together, the moved ones go out
        out = [o.Name for o in moving if o.Name in names]
        if out:
            folder.Items = [n for n in folder.Items if n not in out]
