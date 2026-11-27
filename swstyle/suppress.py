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

ORDER_ONLY = ("BaseFeature", "Group", "Tip", "Origin", "_Body")
COMMANDS = {
    "SWStyle_Suppress": ("Suppress", "Turns off the selected features and the features that depend on them."),
    "SWStyle_Unsuppress": ("Unsuppress", "Turns the selected features back on."),
    "SWStyle_UnsuppressWithDependents": ("Unsuppress with Dependents",
                                         "Turns the selected features back on with the features that depend on them."),
}


def _suppressible(obj):
    return obj is not None and "Suppressed" in obj.PropertiesList and obj.TypeId.startswith("PartDesign::") \
        and obj.TypeId != "PartDesign::Body"


TOL = 1e-5
OWNERS = "SWParents"        # hidden: the features whose edges/faces this one picks, as last worked out
_names = {}                 # (TypeId, number of properties) -> its link property names
_owner = {}                 # (document, target, sub) -> (target shape hash, owner name)
_elements = {}              # (shape hash, kind) -> [(box, element)], while one question is answered


def _link_names(obj):
    props = obj.PropertiesList
    key = (obj.TypeId, len(props))
    got = _names.get(key)
    if got is None:
        got = []
        for name in props:
            if name in ORDER_ONLY:
                continue
            try:
                kind = obj.getTypeIdOfProperty(name)
            except Exception:
                continue
            if kind.startswith("App::PropertyLink") or kind.startswith("App::PropertyXLink"):
                got.append(name)
        _names[key] = got
    return got


def _flatten(value, out):
    if isinstance(value, App.DocumentObject):
        out.append((value, []))
    elif isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], App.DocumentObject) and not isinstance(value[1], App.DocumentObject):
            subs = value[1]
            subs = [subs] if isinstance(subs, str) else [x for x in (subs or ()) if isinstance(x, str)]
            out.append((value[0], subs))
            return
        for item in value:
            _flatten(item, out)


def _raw_links(obj):
    """[(object, [sub-element names])] of obj's link properties, other than its place in the tree."""
    out = []
    for name in _link_names(obj):
        try:
            _flatten(getattr(obj, name, None), out)
        except Exception as _fw_err:
            _fw_log("suppress.py:100", _fw_err)
            continue
    return out


def _short(sub):
    """'Edge12' from 'Edge12' or a mapped name ';#...;:H..,E.Edge12'; '' for a lost ('?Edge12') or
    whole-object pick."""
    sub = sub or ""
    if "?" in sub:
        return ""
    if "." in sub:
        sub = sub.rsplit(".", 1)[-1]
    return sub if sub.startswith(("Edge", "Face", "Vertex")) else ""


def _solid_feature(obj):
    try:
        return obj.isDerivedFrom("PartDesign::Feature")
    except Exception as _fw_err:
        _fw_log("suppress.py:120", _fw_err)
        return False


def _own_shape(feature):
    """feature's shape is what it built (a suppressed or failed feature shows the model before it)."""
    try:
        return not getattr(feature, "Suppressed", False) and "Invalid" not in feature.State \
            and not feature.Shape.isNull()
    except Exception:
        return False


def _point_sig(shape, sub):
    """('Edge'|'Face'|'Vertex', a point on it, its direction there) or None."""
    try:
        el = shape.getElement(sub)
        if sub.startswith("Vertex"):
            return ("Vertex", el.Point, None)
        if sub.startswith("Edge"):
            a, b = el.ParameterRange
            m = (a + b) / 2.0
            return ("Edge", el.valueAt(m), el.tangentAt(m))
        u0, u1, v0, v1 = el.ParameterRange
        tries = [(0.5, 0.5)] + [(i / 6.0, j / 6.0) for i in range(1, 6) for j in range(1, 6)]
        for fu, fv in tries:
            u, v = u0 + (u1 - u0) * fu, v0 + (v1 - v0) * fv
            p = el.valueAt(u, v)
            if el.isInside(p, TOL, True):
                return ("Face", p, el.normalAt(u, v))
        edge = el.Edges[0]            # a thin or odd face: a point of its outline
        a, b = edge.ParameterRange
        p = edge.valueAt((a + b) / 2.0)
        return ("Face", p, el.normalAt(*el.Surface.parameter(p)))
    except Exception:
        return None


def _boxed(shape, kind):
    try:
        key = (shape.hashCode(), kind)
    except Exception:
        key = None
    got = _elements.get(key) if key is not None else None
    if got is None:
        items = shape.Edges if kind == "Edge" else shape.Faces if kind == "Face" else shape.Vertexes
        got = []
        for el in items:
            if kind == "Vertex":
                got.append((None, el))
            else:
                bb = el.BoundBox
                got.append(((bb.XMin - TOL, bb.YMin - TOL, bb.ZMin - TOL, bb.XMax + TOL, bb.YMax + TOL, bb.ZMax + TOL), el))
        if key is not None:
            _elements[key] = got
    return got


def _has(shape, sig):
    """shape has sig's edge or face: one through that point, running the same way."""
    kind, point, direction = sig
    try:
        if shape.isNull():
            return False
        if kind == "Vertex":
            return any(el.Point.distanceToPoint(point) <= TOL for _box, el in _boxed(shape, kind))
        import Part
        vertex = None
        x, y, z = point.x, point.y, point.z
        for box, el in _boxed(shape, kind):
            if x < box[0] or y < box[1] or z < box[2] or x > box[3] or y > box[4] or z > box[5]:
                continue
            try:
                if vertex is None:
                    vertex = Part.Vertex(point)
                if el.distToShape(vertex)[0] > TOL:
                    continue
                if kind == "Edge":
                    d = el.tangentAt(el.Curve.parameter(point))
                else:
                    d = el.normalAt(*el.Surface.parameter(point))
                if abs(abs(d.normalize().dot(App.Vector(direction).normalize())) - 1.0) < 1e-6:
                    return True
            except Exception:
                continue
    except Exception:
        return False
    return False


def owner(target, sub):
    """The feature that made target's edge/face/vertex sub: the earliest feature down target's
    tree whose own shape has it. target itself when it cannot be told."""
    sub = _short(sub)
    if not sub or not _solid_feature(target):
        return target
    try:
        shape = target.Shape
        stamp = shape.hashCode()
    except Exception as _fw_err:
        _fw_log("suppress.py:220", _fw_err)
        return target
    key = (target.Document.Name, target.Name, sub)
    got = _owner.get(key)
    if got is not None and got[0] == stamp:
        found = target.Document.getObject(got[1])
        if found is not None:
            return found
    sig = _point_sig(shape, sub)
    if sig is None:
        return target
    stages, item = [], target
    while item is not None and len(stages) < 5000:
        stages.append(item)
        item = getattr(item, "BaseFeature", None)
    known = {}

    def has(i):
        # a suppressed or failed feature shows the model before it: ask the one under it
        while i < len(stages) and not (_own_shape(stages[i]) if _solid_feature(stages[i]) else True):
            i += 1
        if i >= len(stages):
            return False
        if i not in known:
            try:
                known[i] = _has(stages[i].Shape, sig)
            except Exception:
                known[i] = False
        return known[i]

    lo, hi = 0, len(stages) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if has(mid):
            lo = mid
        else:
            hi = mid - 1
    while lo < len(stages) - 1 and _solid_feature(stages[lo]) and not _own_shape(stages[lo]):
        lo += 1                 # (the element is the feature's under a suppressed one)
    found = stages[lo]
    _owner[key] = (stamp, found.Name)
    if len(_owner) > 20000:
        _owner.clear()
    return found


def _quiet(obj):
    """obj's picks cannot be read from the model now: it is off, failed, or a sketch waiting for
    its suppressed face."""
    try:
        return bool(getattr(obj, "Suppressed", False)) or "Invalid" in obj.State or QUIET in obj.PropertiesList
    except Exception:
        return True


def _stored(obj):
    """The owners remembered on obj (remember()), or None."""
    try:
        if OWNERS not in obj.PropertiesList:
            return None
        names = [n for n in getattr(obj, OWNERS).split(";") if n]
        found = [obj.Document.getObject(n) for n in names]
        return [o for o in found if o is not None]
    except Exception as _fw_err:
        _fw_log("suppress.py:284", _fw_err)
        return None


def _links(obj):
    """Objects obj uses through its link properties, other than its place in the tree. A picked
    edge or face counts as a use of the feature that made it (owner())."""
    out, picks = [], []
    for target, subs in _raw_links(obj):
        if subs and _solid_feature(target) and any(x for x in subs):
            picks.append((target, subs))
        else:
            out.append(target)
    if not picks:
        return out
    stored = _stored(obj) if (_quiet(obj) or any(not _short(x) for _t, subs in picks for x in subs if x)) else None
    if stored is not None:
        return out + stored
    for target, subs in picks:
        if _quiet(obj):
            out.append(target)          # nothing remembered: FreeCAD's link, as before
            continue
        for sub in subs:
            found = owner(target, sub) if _short(sub) else target
            if found not in out:
                out.append(found)
    return out


def remember(doc):
    """Write on each feature and sketch whose picks can be read now which features made them, so
    the parent/child relation is still known while they are suppressed or in error."""
    for obj in doc.Objects:
        try:
            if _quiet(obj):
                continue
            names = []
            for target, subs in _raw_links(obj):
                if not (subs and _solid_feature(target)):
                    continue
                for sub in subs:
                    if not sub:
                        continue
                    found = owner(target, sub) if _short(sub) else target
                    if found.Name not in names:
                        names.append(found.Name)
            if not names and OWNERS not in obj.PropertiesList:
                continue
            value = ";".join(names)
            if OWNERS not in obj.PropertiesList:
                obj.addProperty("App::PropertyString", OWNERS, "FreeCAD", "the features whose edges and faces this one uses")
                obj.setPropertyStatus(OWNERS, ["Hidden", "Output", "NoRecompute"])
            if getattr(obj, OWNERS) != value:
                setattr(obj, OWNERS, value)
        except Exception as _fw_err:
            _fw_log("suppress.py:339", _fw_err)
            continue


def _users(doc):
    """{feature name: [the objects that use it]} for the whole document."""
    out = {}
    for user in doc.Objects:
        try:
            for used in _links(user):
                if used is not user:
                    out.setdefault(used.Name, []).append(user)
        except Exception as _fw_err:
            _fw_log("suppress.py:352", _fw_err)
            continue
    return out


def _children(obj, users=None):
    """Direct children: objects that use obj (a sketch on its face, a fillet on its edges ...)."""
    if users is None:
        users = _users(obj.Document)
    return list(users.get(obj.Name, ()))


def dependents(obj):
    ""
    try:
        users = _users(obj.Document)
        seen, stack, out = set(), list(_children(obj, users)), []
        while stack:
            item = stack.pop()
            if item.Name in seen:
                continue
            seen.add(item.Name)
            out.append(item)
            stack.extend(_children(item, users))
        return [o for o in out if _suppressible(o)]
    finally:
        _elements.clear()


def parents(obj):
    """Every feature obj needs (through sketches too)."""
    try:
        seen, stack, out = set(), list(_links(obj)), []
        while stack:
            item = stack.pop()
            if item.Name in seen or item.TypeId in ("PartDesign::Body", "App::Origin", "App::Plane", "App::Line"):
                continue
            seen.add(item.Name)
            out.append(item)
            stack.extend(_links(item))
        return [o for o in out if _suppressible(o)]
    finally:
        _elements.clear()


def configured(obj):
    """Suppressed is driven by the configuration table (a per-configuration suppress state)."""
    try:
        return any(p == "Suppressed" for p, _e in obj.ExpressionEngine)
    except Exception as _fw_err:
        _fw_log("suppress.py:402", _fw_err)
        return False


def _signature(shape, sub):
    from . import picksgeo
    if sub.startswith("Face"):
        # a point that is on the face (its middle can lie in a hole)
        got = _point_sig(shape, sub)
        try:
            return ("Face", got[1], got[2], shape.getElement(sub).Area) if got else None
        except Exception as _fw_err:
            _fw_log("suppress.py:414", _fw_err)
            return None
    return picksgeo.signature(shape, sub)


KEPT = "SWPickedGeometry"
PICKS = (("PartDesign::DressUp", "Base"), ("Sketcher::SketchObject", "AttachmentSupport"),
         ("PartDesign::Plane", "AttachmentSupport"), ("PartDesign::Line", "AttachmentSupport"),
         ("PartDesign::Point", "AttachmentSupport"))


def _held(obj):
    """obj or a feature under it (its BaseFeature chain) is suppressed."""
    seen = 0
    while obj is not None and seen < 500:
        if getattr(obj, "Suppressed", False):
            return True
        obj = getattr(obj, "BaseFeature", None)
        seen += 1
    return False


def _keep(saved):
    """Store each valid feature's picks by geometry on the feature itself (hidden), so a later
    Unsuppress, even after the file was saved and opened again, can find the edges again."""
    import json
    for obj, prop, base, sigs in saved:
        if _quiet(obj):
            continue
        data = json.dumps({"prop": prop, "base": base.Name,
                           "picks": [[sub, sig[0], [sig[1].x, sig[1].y, sig[1].z], [sig[2].x, sig[2].y, sig[2].z], sig[3]]
                                     for sub, sig in sigs]})
        try:
            if KEPT not in obj.PropertiesList:
                obj.addProperty("App::PropertyString", KEPT, "FreeCAD", "picked edges/faces by geometry")
                obj.setPropertyStatus(KEPT, ["Hidden", "Output", "NoRecompute"])
            if getattr(obj, KEPT) != data:
                setattr(obj, KEPT, data)
        except Exception as _fw_err:
            _fw_log("suppress.py:149", _fw_err)


def _kept(obj):
    import json
    try:
        data = json.loads(getattr(obj, KEPT))
        base = obj.Document.getObject(data["base"])
        sigs = [(sub, (kind, App.Vector(*c), App.Vector(*d), size)) for sub, kind, c, d, size in data["picks"]]
        return (obj, data["prop"], base, sigs) if base is not None else None
    except Exception as _fw_err:
        _fw_log("suppress.py:464", _fw_err)
        return None


def _pick_prop(obj):
    for kind, prop in PICKS:
        try:
            if obj.isDerivedFrom(kind) and prop in obj.PropertiesList:
                return prop
        except Exception as _fw_err:
            _fw_log("suppress.py:474", _fw_err)
            continue
    return None


def _one_pick(obj, prop):
    """(feature, [names]) when obj's prop picks edges/faces of one solid feature, else None."""
    try:
        got = []
        _flatten(getattr(obj, prop), got)
    except Exception as _fw_err:
        _fw_log("suppress.py:485", _fw_err)
        return None
    got = [(t, subs) for t, subs in got if t is not None]
    if len(got) != 1:
        return None
    base, subs = got[0]
    if not _solid_feature(base) or not subs or not all(_short(x) for x in subs):
        return None
    return base, [_short(x) for x in subs]


def _snapshot(objs):
    """Each picked edge or face of these (a fillet's edges, the face a sketch is on ...), by its
    geometry."""
    out = []
    for obj in objs:
        prop = _pick_prop(obj)
        if prop is None:
            continue
        if _quiet(obj):
            got = _kept(obj)
            if got is not None:
                out.append(got)
            continue
        one = _one_pick(obj, prop)
        if one is None:
            continue
        base, subs = one
        try:
            shape = base.Shape
        except Exception:
            continue
        sigs = [(sub, _signature(shape, sub)) for sub in subs]
        if all(sig is not None for _s, sig in sigs):
            out.append((obj, prop, base, sigs))
    return out


def _match(shape, sig):
    from . import picksgeo
    return picksgeo.match(shape, sig)


def _write(obj, prop, base, subs):
    if obj.getTypeIdOfProperty(prop).startswith("App::PropertyLinkSubList"):
        setattr(obj, prop, [(base, tuple(subs))])
    else:
        setattr(obj, prop, (base, list(subs)))


def _repair(saved):
    ""



    fixed = []
    for obj, prop, base, sigs in saved:
        try:
            if getattr(obj, "Suppressed", False) or QUIET in obj.PropertiesList:
                continue
            one = _one_pick(obj, prop)
            if one is not None:
                base, now = one
            else:
                got = []
                _flatten(getattr(obj, prop), got)
                if len(got) != 1 or got[0][0] is None:
                    continue
                base, now = got[0][0], None        # a lost name ("?Edge4"): found again below
            subs = [_match(base.Shape, sig) for _sub, sig in sigs]
            if None in subs and prop == "AttachmentSupport":
                # the face a sketch is on changed where its point was (a boss came back there)
                from . import picksgeo
                subs = [x or picksgeo.match_near(base.Shape, sig) for x, (_sub, sig) in zip(subs, sigs)]
            if None in subs or now == subs:
                continue
            _write(obj, prop, base, subs)
            fixed.append(obj)
        except Exception as _fw_err:
            _fw_log("suppress.py:564", _fw_err)
            continue
    return fixed


def _set(objs, value, title):
    objs = [o for o in objs if _suppressible(o) and bool(o.Suppressed) != value]
    if not objs:
        return []
    doc = objs[0].Document
    try:
        remember(doc)
        saved = _snapshot([o for o in doc.Objects if _pick_prop(o)])
        _keep(saved)
    finally:
        _elements.clear()
    table_driven = [o for o in objs if configured(o)]
    plain = [o for o in objs if o not in table_driven]
    if plain:
        doc.openTransaction(title)
        try:
            for obj in plain:
                obj.Suppressed = value
        finally:
            doc.commitTransaction()
    if table_driven:

        from . import configs
        for obj in table_driven:
            configs.set_suppressed(obj, value, "this")
    _sketches_follow(doc)
    doc.recompute()
    for _round in range(4):
        if not _repair(saved):
            break
        doc.recompute()
    return objs


QUIET = "SWSuppressedMapMode"


def _supports(sketch):
    out = []
    for item in (getattr(sketch, "AttachmentSupport", None) or []):
        obj = item[0] if isinstance(item, (list, tuple)) else item
        if isinstance(obj, App.DocumentObject):
            out.append(obj)
    return out


def _face_makers(sketch):
    """The features that made the faces sketch sits on: as remembered (remember()), else the
    features FreeCAD links it to."""
    stored = _stored(sketch)
    if stored:
        return [o for o in stored if _solid_feature(o)]
    return _supports(sketch)


def _sketches_follow(doc):
    ""



    for sk in doc.Objects:
        if sk.TypeId != "Sketcher::SketchObject":
            continue
        held = any(getattr(o, "Suppressed", False) for o in _face_makers(sk))
        try:
            if held and QUIET not in sk.PropertiesList and sk.MapMode != "Deactivated":
                sk.addProperty("App::PropertyString", QUIET, "FreeCAD", "attachment while its face is suppressed")
                sk.setPropertyStatus(QUIET, ["Hidden"])
                vo = getattr(sk, "ViewObject", None)
                setattr(sk, QUIET, "%s|%d" % (sk.MapMode, 1 if vo is not None and vo.Visibility else 0))
                place = App.Placement(sk.Placement)
                sk.MapMode = "Deactivated"
                sk.Placement = place
                if vo is not None:
                    vo.Visibility = False
            elif not held and QUIET in sk.PropertiesList:
                mode, _sep, shown = getattr(sk, QUIET).partition("|")
                sk.removeProperty(QUIET)
                sk.MapMode = mode or "FlatFace"
                vo = getattr(sk, "ViewObject", None)
                if vo is not None and shown == "1":
                    vo.Visibility = True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: suppress %s: %s\n" % (sk.Label, error))


def set_one(obj, value, title="Suppress"):
    """One feature on or off, through the configuration table when it drives the feature."""
    return _set([obj], bool(value), title)


def _unique(objs):
    seen, out = set(), []
    for obj in objs:
        if obj.Name not in seen:
            seen.add(obj.Name)
            out.append(obj)
    return out


def suppress(objs):
    every = []
    for obj in objs:
        every += [obj] + dependents(obj)
    return _set(_unique(every), True, "Suppress")


def unsuppress(objs, with_dependents=False):
    every = []
    for obj in objs:
        every += parents(obj) + [obj]
        if with_dependents:
            every += dependents(obj)
    return _set(_unique(every), False, "Unsuppress with Dependents" if with_dependents else "Unsuppress")


def _picked():
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        obj = sel.Object
        # A pick on the model names the body; the sub-element path holds the feature
        for path in sel.SubElementNames or [""]:
            found = obj
            for part in path.split(".")[:-1]:
                child = obj.Document.getObject(part)
                if child is not None:
                    found = child
            out.append(found)
    return [o for o in _unique(out) if _suppressible(o)]


class _Command:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        label, tip = COMMANDS[self.name]
        return {"MenuText": label, "ToolTip": tip}

    def IsActive(self):
        picked = _picked()
        if not picked or Gui.Control.activeDialog():
            return False
        if self.name == "SWStyle_Suppress":
            return any(not o.Suppressed for o in picked)
        if self.name == "SWStyle_Unsuppress":
            return any(o.Suppressed for o in picked)
        if any(o.Suppressed for o in picked):
            return True
        if not any(getattr(o, "Suppressed", False) for o in picked[0].Document.Objects):
            return False            # nothing is off: no need to work out who depends on whom
        return any(any(d.Suppressed for d in dependents(o)) for o in picked)

    def Activated(self):
        picked = _picked()
        if self.name == "SWStyle_Suppress":
            suppress(picked)
        else:
            unsuppress(picked, self.name == "SWStyle_UnsuppressWithDependents")


class _Manipulator:
    """Suppress / Unsuppress on the tree's right-click menu for PartDesign features."""

    def modifyContextMenu(self, recipient):
        if recipient != "Tree":
            return []
        picked = _picked()
        if not picked:
            return []
        out = []
        if any(not o.Suppressed for o in picked):
            out.append({"append": "SWStyle_Suppress"})
        if any(o.Suppressed for o in picked):
            out.append({"append": "SWStyle_Unsuppress"})
            out.append({"append": "SWStyle_UnsuppressWithDependents"})
        return out


# ----------------------------------------------------------------------------- a suppressed primitive's place
PLACE = "FwSuppressedPlacement"


def _own_place(obj):
    """A feature whose Placement is the user's own (an additive or subtractive primitive, not attached)."""
    try:
        return obj.isDerivedFrom("PartDesign::FeaturePrimitive") and getattr(obj, "MapMode", "Deactivated") == "Deactivated"
    except Exception:
        return False


def _restoring(obj):
    try:
        return bool(obj.Document.Restoring) or "Restore" in obj.State
    except Exception:
        return False


class _KeepPlace:
    """FreeCAD 1.1 puts a suppressed primitive at its base's placement and remembers its own one
    only in memory: saved and opened again, Unsuppress brought it back at the origin (a hole or a
    boss in the wrong place). The place is kept in the file while it is suppressed and put back
    when it is unsuppressed, however that happens (Suppress, a configuration, the property)."""

    def slotBeforeChangeObject(self, obj, prop):
        if prop != "Suppressed" or _restoring(obj) or not _own_place(obj):
            return
        try:
            if not obj.Suppressed:          # about to be suppressed: its place now is its own
                if PLACE not in obj.PropertiesList:
                    obj.addProperty("App::PropertyPlacement", PLACE, "FreeCAD", "its place while suppressed")
                    obj.setPropertyStatus(PLACE, ["Hidden"])
                setattr(obj, PLACE, obj.Placement)
        except Exception as error:
            _fw_log("suppress.py:keep place", error)

    def slotChangedObject(self, obj, prop):
        if prop != "Suppressed" or _restoring(obj) or obj.Suppressed or PLACE not in obj.PropertiesList:
            return
        try:
            place = App.Placement(getattr(obj, PLACE))
            if _own_place(obj) and not obj.Placement.isSame(place, 1e-12):
                obj.Placement = place
        except Exception as error:
            _fw_log("suppress.py:put place back", error)


    def slotRecomputedDocument(self, doc):
        name = doc.Name
        if Gui is not None and App.GuiUp:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda: show_built(name))


def _shown(obj):
    try:
        return bool(obj.ViewObject.Visibility)
    except Exception:
        return False


def _show(obj, on):
    try:
        if bool(obj.ViewObject.Visibility) != on:
            obj.ViewObject.Visibility = on
    except Exception as _fw_err:
        _fw_log("suppress.py:show", _fw_err)


_STAND_INS = set()      # (document Uid, feature ID) shown by show_built in place of a suppressed tip: a closed
                        # document's entries can never match a new document or feature of the same name


def _stand_key(doc, obj):
    return (doc.Uid, obj.ID)


def _prune_stand_ins():
    """Entries of closed documents go (no stamp of theirs comes back)."""
    if _STAND_INS:
        open_ids = {d.Uid for d in App.listDocuments().values()}
        for key in [k for k in _STAND_INS if k[0] not in open_ids]:
            _STAND_INS.discard(key)


def _page_open():
    try:
        return Gui is not None and Gui.Control.activeDialog()
    except Exception:
        return False


def show_built(name):
    ""



    doc = App.listDocuments().get(name)
    if doc is None or not App.GuiUp:
        return
    _prune_stand_ins()
    for body in [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]:
        try:
            tip = body.Tip
            if tip is None or not _solid_feature(tip):
                continue
            feats = [f for f in body.Group if _solid_feature(f)]
            if tip not in feats:
                continue
            before = feats[:feats.index(tip)]
            built = [f for f in before if _own_shape(f)]
            if getattr(tip, "Suppressed", False):
                if _shown(tip) and built:
                    _show(tip, False)
                    _show(built[-1], True)
                    _STAND_INS.add(_stand_key(doc, built[-1]))
            elif not _shown(tip) and _shown(body):
                stand = [f for f in before if _shown(f)]
                if len(stand) == 1 and getattr(stand[0], "Suppressed", False) is False and stand[0] in built \
                        and (_stand_key(doc, stand[0]) in _STAND_INS or not _page_open()):
                    # not while a page shows the part before the feature it makes (Fillet, Chamfer, Shell:
                    # their setback vertices and edges must stay pickable), unless this stand-in is ours
                    _STAND_INS.discard(_stand_key(doc, stand[0]))
                    _show(stand[0], False)              # the stand-in shown while the tip was suppressed
                    _show(tip, True)
        except Exception as _fw_err:
            _fw_log("suppress.py:show built", _fw_err)


_KEEP = []


def install_keep_place():
    if not _KEEP:
        _KEEP.append(_KeepPlace())
        App.addDocumentObserver(_KEEP[0])


_registered = False
_manipulator = None


def register():
    global _registered, _manipulator
    if _registered:
        return
    _registered = True
    install_keep_place()
    for name in COMMANDS:
        Gui.addCommand(name, _Command(name))
    try:
        _manipulator = _Manipulator()
        Gui.addWorkbenchManipulator(_manipulator)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: no Suppress on the tree menu (%s)\n" % error)
