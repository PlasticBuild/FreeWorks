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

import math

import FreeCAD as App

LINK_TYPES = ("App::PropertyLinkSub", "App::PropertyLinkSubList", "App::PropertyLinkSubHidden",
              "App::PropertyLinkSubListHidden")
SKIP_PROPS = ("ExpressionEngine", "Group", "Tip", "Origin", "BaseFeature", "Profile")
AGREE = 0.2          # the named element is still the pick (place moved less than this, in box units)
FIND = 0.25          # the farthest a pick is looked for (in box units)
BOX = 2.0            # the part's box grew or shrank more than this: too much changed to move picks
CLEAR = 0.6          # the best match must beat the second by this factor

_memo = {}           # (doc, owner, prop, target, n) -> the n-th pick's signature
_doubt = set()       # memo keys whose named element is not the pick and no clear match was found
_recomputing = set()
_box = {}            # (doc, owner, prop, target) -> the target's box diagonal when learned
_picked = {}         # (doc, owner, prop) -> [(target, short names)] as last learned
_learned = set()     # documents whose picks were learned as saved
_seen = {}           # (doc, owner, prop, target) -> target shape hash when last learned/checked
_busy = set()
_sides = {}          # memo key of an edge pick -> (its middle, the surfaces of the faces on either side)
_surfaces = {}       # shape hash -> the surfaces of its faces, while one check runs
gone = []            # (doc, owner label, prop, sub) of picks found to be gone, for the checks
last_scores = []     # the three best (score, sub) of the last find (for the checks)
moved = []           # (doc, owner label, prop, old sub, new sub) for the checks and the Report view


def _short(sub):
    """'Edge12' from 'Edge12', '?Edge12' or a mapped name ';#...;:H..,E.Edge12'."""
    sub = sub or ""
    if "." in sub and (";" in sub or sub.startswith("?")):
        sub = sub.rsplit(".", 1)[-1]
    return sub.lstrip("?")


def _norm(shape):
    bb = shape.BoundBox
    size = [max(bb.XLength, 1e-9), max(bb.YLength, 1e-9), max(bb.ZLength, 1e-9)]
    big = max(size)
    lo = (bb.XMin, bb.YMin, bb.ZMin)
    flat = [s < big * 1e-6 for s in size]

    def f(p):
        return tuple(0.0 if flat[i] else (p[i] - lo[i]) / size[i] for i in range(3))
    return f


def _name(obj):
    return type(obj).__name__


def _face_types(shape):
    """Edge hash -> the surface kinds of the faces around it, built once for a whole search
    (asking each edge for its faces is slow on a big part)."""
    around = {}
    for i, f in enumerate(shape.Faces):
        kind = _name(f.Surface)
        for e in f.Edges:
            around.setdefault(e.hashCode(), {})[i] = kind
    return {h: tuple(sorted(d.values())) for h, d in around.items()}


def signature(shape, sub, norm=None, around=None):
    """A description of shape's sub-element that survives a change of size, or None."""
    sub = _short(sub)
    try:
        el = shape.getElement(sub)
    except Exception:
        return None
    norm = norm or _norm(shape)
    try:
        import Part
        if sub.startswith("Edge"):
            curve = el.Curve
            a, b = el.ParameterRange
            mid = el.valueAt((a + b) / 2.0)
            axis = getattr(curve, "Axis", None) if _name(curve) in ("Circle", "Ellipse") else None
            direction = axis if axis is not None else el.tangentAt((a + b) / 2.0)
            if around is not None:
                faces = around.get(el.hashCode(), ())
            else:
                faces = tuple(sorted(_name(f.Surface) for f in shape.ancestorsOfType(el, Part.Face)))
            return ("Edge", _name(curve), norm(mid), direction, el.Length,
                    getattr(curve, "Radius", 0.0) if axis is not None else 0.0, faces)
        if sub.startswith("Face"):
            surf = el.Surface
            kind = _name(surf)
            if kind == "Plane":
                direction = el.normalAt(0, 0)
            elif hasattr(surf, "Axis"):
                direction = surf.Axis
            else:
                direction = None
            return ("Face", kind, norm(el.CenterOfMass), direction, el.Area,
                    getattr(surf, "Radius", 0.0), (len(el.Edges),))
        if sub.startswith("Vertex"):
            return ("Vertex", "Vertex", norm(el.Point), None, 1.0, 0.0,
                    (len(shape.ancestorsOfType(el, Part.Edge)),))
    except Exception:
        return None
    return None


def _parallel(a, b):
    if a is None or b is None:
        return a is None and b is None
    try:
        return abs(abs(App.Vector(a).normalize().dot(App.Vector(b).normalize())) - 1.0) < 1e-4
    except Exception:
        return False


TURN = 0.5          # loose match: score added per radian an edge turned (a loft's side edge when a section moves)


def _turn(a, b):
    try:
        c = abs(App.Vector(a).normalize().dot(App.Vector(b).normalize()))
        return math.acos(min(1.0, c))
    except Exception:
        return None


def score(a, b, loose=False):
    """How far b is from the pick a (0 = the same place and size), or None when b is another
    kind of element. loose: an edge that turned (not a circle's axis) still counts, the turn added."""
    if a is None or b is None or a[0] != b[0] or a[1] != b[1] or a[6] != b[6]:
        return None
    turn = 0.0
    if a[3] is not None and not _parallel(a[3], b[3]):
        if not (loose and a[0] == "Edge" and a[5] == 0.0 and b[3] is not None):
            return None
        turn = _turn(a[3], b[3])
        if turn is None or turn > 0.6:
            return None
    place = math.sqrt(sum((x - y) ** 2 for x, y in zip(a[2], b[2]))) + TURN * turn
    size = abs(math.log(max(a[4], 1e-12) / max(b[4], 1e-12)))
    radius = abs(math.log(max(a[5], 1e-12) / max(b[5], 1e-12))) if a[5] > 0 and b[5] > 0 else 0.0
    return place + 0.15 * size + 0.15 * radius


def find(shape, sig, taken=()):
    """The element of shape that clearly is sig's pick, or None."""
    if sig is None:
        return None
    kind = sig[0]
    items = shape.Edges if kind == "Edge" else shape.Faces if kind == "Face" else shape.Vertexes
    norm = _norm(shape)
    around = _face_types(shape) if kind == "Edge" else None
    sigs = []
    for i in range(len(items)):
        sub = "%s%d" % (kind, i + 1)
        if sub not in taken:
            sigs.append((sub, signature(shape, sub, norm, around)))
    scores = [(s, sub) for sub, s in ((sub, score(sig, other)) for sub, other in sigs) if s is not None]
    if kind == "Edge" and (not scores or min(scores)[0] > FIND):
        # no edge runs the same way: an edge of a loft or a draft turns when a section or an
        # angle changes (a propeller blade's tip edge when its plane moves); it is matched with
        # the turn counted against it
        scores = [(s, sub) for sub, s in ((sub, score(sig, other, True)) for sub, other in sigs) if s is not None]
    if not scores:
        return None
    scores.sort()
    best = scores[0]
    last_scores[:] = scores[:3]
    if best[0] > FIND:
        return None
    if len(scores) > 1 and scores[1][0] - best[0] < 0.02 and best[0] > CLEAR * scores[1][0]:
        return None          # two elements fit as well: not clear which one it was
    return best[1]


# ------------------------------------------------------------------- an edge that is gone
# A pick whose name is lost is looked for by its geometry (find). That is right when the edge
# moved with a dimension, and wrong when it was taken away: a filleted corner cut off by a notch
# has two new corners next to it, and the nearer one would get the fillet without a word. The two
# cases differ in the faces the edge ran between. When the edge moved, one of them moved (the
# side of a plate made wider). When both are still where they were and the edge found does not

# a reference instead of moving it.
def _surface_key(face):
    """A plane or cylinder as numbers that do not depend on the face's outline, or None."""
    try:
        surf = face.Surface
        kind = _name(surf)
        if kind == "Plane":
            n = App.Vector(surf.Axis)
            n.normalize()
            d = n.dot(surf.Position)
            return ("Plane", n, d)
        if kind == "Cylinder":
            a = App.Vector(surf.Axis)
            a.normalize()
            c = surf.Center
            return ("Cylinder", a, c - a * c.dot(a), surf.Radius)
    except Exception:
        pass
    return None


def _same_surface(a, b, tol):
    if a is None or b is None or a[0] != b[0]:
        return False
    if a[0] == "Plane":
        dot = a[1].dot(b[1])
        return abs(abs(dot) - 1.0) < 1e-7 and abs(a[2] - (b[2] if dot > 0 else -b[2])) < tol
    return abs(abs(a[1].dot(b[1])) - 1.0) < 1e-7 and (a[2] - b[2]).Length < tol and abs(a[3] - b[3]) < tol


def _on_surface(key, point, tol):
    if key[0] == "Plane":
        return abs(key[1].dot(point) - key[2]) < tol
    rel = point - key[2]
    return abs((rel - key[1] * rel.dot(key[1])).Length - key[3]) < tol


def _edge_sides(shape, sub):
    """(the edge's middle, [the surfaces of the faces it runs between]) or None."""
    try:
        import Part
        el = shape.getElement(_short(sub))
        a, b = el.ParameterRange
        return (el.valueAt((a + b) / 2.0), [_surface_key(f) for f in shape.ancestorsOfType(el, Part.Face)])
    except Exception:
        return None


def _faces_with(shape):
    h = _hash(shape)
    got = _surfaces.get(h)
    if got is None:
        got = [(_surface_key(f), f) for f in shape.Faces]
        got = [(k, f) for k, f in got if k is not None]
        if h is not None:
            _surfaces[h] = got
    return got


def _gone(shape, mk, found):
    """True when the edge pick mk is gone from shape and found is another edge: the faces it ran
    between are both still at the place, and found does not lie on both."""
    sides = _sides.get(mk)
    if sides is None:
        sides = next((v for k, v in _sides.items() if k[:3] == mk[:3] and k[4] == mk[4]), None)
    if sides is None:
        return False
    middle, keys = sides
    if len(keys) != 2 or None in keys:
        return False
    try:
        import Part
        tol = max(shape.BoundBox.DiagonalLength, 1.0) * 1e-6
        near = max(shape.BoundBox.DiagonalLength * 0.25, 1.0)
        spot = Part.Vertex(middle)
        for key in keys:
            if not any(_same_surface(key, k, tol) and f.distToShape(spot)[0] <= near for k, f in _faces_with(shape)):
                return False        # a side moved or went: the edge may have moved with it
        el = shape.getElement(found)
        a, b = el.ParameterRange
        point = el.valueAt((a + b) / 2.0)
        return not all(_on_surface(key, point, tol * 10) for key in keys)
    except Exception:
        return False


# ----------------------------------------------------------------------------- the links
def _owners(doc):
    for obj in doc.Objects:
        try:
            if obj.isDerivedFrom("PartDesign::Feature") or obj.TypeId == "Sketcher::SketchObject" \
                    or obj.TypeId.startswith("PartDesign::") and "Datum" in obj.TypeId \
                    or obj.TypeId in ("PartDesign::Plane", "PartDesign::Line", "PartDesign::Point"):
                yield obj
        except Exception:
            continue


def links(obj):
    """[(prop, [(target, [subs])])] for obj's links to sub-elements."""
    out = []
    for prop in obj.PropertiesList:
        if prop in SKIP_PROPS:
            continue
        try:
            if obj.getTypeIdOfProperty(prop) not in LINK_TYPES:
                continue
            value = getattr(obj, prop)
        except Exception:
            continue
        if not value:
            continue
        if isinstance(value, tuple) and len(value) == 2 and not isinstance(value[0], tuple):
            value = [value]
        items = []
        for item in value:
            try:
                target, subs = item
            except Exception:
                continue
            if target is None:
                continue
            subs = [subs] if isinstance(subs, str) else list(subs or [])
            subs = [s for s in subs if s]
            if subs and hasattr(target, "Shape"):
                items.append((target, subs))
        if items:
            out.append((prop, items))
    return out


def _target_ok(target):
    ""

    try:
        if target.Shape.isNull():
            return False
        if "Invalid" not in target.State:
            return True
        base = getattr(target, "BaseFeature", None)
        return base is not None and target.Shape.isPartner(base.Shape)
    except Exception:
        return False


def _built(target):
    try:
        return "Invalid" not in target.State and not target.Shape.isNull()
    except Exception:
        return False


def _hash(shape):
    try:
        return shape.hashCode()
    except Exception:
        return None


def learn(doc, saved=False):
    """Remember every pick as it is now (saved=True: as the file has it, before any rebuild)."""
    supp = _any_suppressed(doc)         # extapps/66: once for the pass, not once per owner
    for obj in _owners(doc):
        if not saved and "Invalid" in obj.State:
            continue
        if not saved and (getattr(obj, "Suppressed", False) or _upstream_suppressed(obj, supp)):
            # a suppressed feature, or one whose parent is: its names are not read against the model
            # now (the edge is not there, the name is another edge's). Learned here, that other edge
            # would be "found" as the pick when the feature comes back.
            continue
        for prop, items in links(obj):
            _picked[(doc.Name, obj.Name, prop)] = [(t.Name, [_short(x) for x in subs]) for t, subs in items]
            for target, subs in items:
                if not saved and not _built(target):
                    continue        # not on a failed feature's stand-in shape: the picks as they were before
                try:
                    shape = target.Shape
                except Exception:
                    continue
                if shape.isNull():
                    continue
                norm = _norm(shape)
                for n, sub in enumerate(subs):
                    k = (doc.Name, obj.Name, prop, target.Name, n)
                    if k in _doubt or (not saved and "?" in sub):
                        continue        # (a name FreeCAD marks as lost names nothing to learn)
                    sig = signature(shape, sub, norm)
                    if sig is not None:
                        _memo[k] = sig
                        if sig[0] == "Edge":
                            sides = _edge_sides(shape, sub)
                            if sides is not None:
                                _sides[k] = sides
                _seen[(doc.Name, obj.Name, prop, target.Name)] = _hash(shape)
                _box[(doc.Name, obj.Name, prop, target.Name)] = shape.BoundBox.DiagonalLength


def check(doc):
    """Move the picks whose name now points elsewhere back to their element. Returns the owners
    changed; learns the picks that are right."""
    changed = []
    supp = _any_suppressed(doc)         # extapps/66: once for the pass, not once per owner
    for obj in _owners(doc):
        if getattr(obj, "Suppressed", False):
            continue            # a suppressed feature is not rebuilt: its picks wait as they are
        hold = _upstream_suppressed(obj, supp)
        for prop, items in links(obj):
            new_items, touched = [], False
            for target, subs in items:
                if not _target_ok(target):
                    new_items.append((target, subs))
                    continue
                shape = target.Shape
                key = (doc.Name, obj.Name, prop, target.Name)
                h = _hash(shape)
                lost = any(s.startswith("?") or "?" in s for s in subs)
                if h is not None and _seen.get(key) == h and not lost and "Invalid" not in obj.State:
                    new_items.append((target, subs))
                    continue
                norm = _norm(shape)
                was = _box.get(key)
                diag = shape.BoundBox.DiagonalLength
                wild = was is not None and (diag > was * BOX or diag * BOX < was)   # e.g. the first feature suppressed
                out, taken = [], set()
                for n, sub in enumerate(subs):
                    short = _short(sub)
                    mk = (doc.Name, obj.Name, prop, target.Name, n)
                    _doubt.discard(mk)
                    memo = _memo.get(mk)
                    if memo is None:
                        memo = _moved_target(doc.Name, obj.Name, prop, target.Name, n)
                    now = signature(shape, short, norm)
                    s = score(memo, now) if memo is not None else None
                    if memo is None or (s is not None and s <= AGREE and not sub.startswith("?")):
                        out.append(short if sub.startswith("?") else sub)
                        taken.add(short)
                        continue
                    found = None if wild else find(shape, memo, taken)
                    if found and found != short and memo[0] == "Edge" and _gone(shape, mk, found):
                        # not moved: taken away (the faces it ran between no longer meet there)
                        gone.append((doc.Name, obj.Label, prop, sub))
                        App.Console.PrintLog("FreeCAD: %s %s %s is gone from the model (not moved to %s)\n"
                                             % (obj.Label, prop, sub, found))
                        found = None
                    if hold and found != short:
                        found = None        # only a lost name put back on the same element
                    if found and found != short:
                        moved.append((doc.Name, obj.Label, prop, sub, found, [round(x, 3) for x, _y in last_scores], wild))
                        App.Console.PrintLog("FreeCAD: %s %s %s -> %s (found by its geometry)\n"
                                             % (obj.Label, prop, sub, found))
                        out.append(found)
                        taken.add(found)
                        touched = True
                    elif found == short and sub.startswith("?"):
                        out.append(found)
                        taken.add(found)
                        touched = True
                    else:
                        if found is None and not hold:
                            _doubt.add(mk)      # keep the pick as it was; do not learn the wrong one
                        out.append(sub)
                        taken.add(short)
                new_items.append((target, out))
                _seen[key] = h
            if touched:
                try:
                    _write(obj, prop, new_items)
                    _picked[(doc.Name, obj.Name, prop)] = [(t.Name, [_short(x) for x in subs]) for t, subs in new_items]
                    changed.append(obj)
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: could not repick %s.%s (%s)\n" % (obj.Label, prop, error))
    _surfaces.clear()
    return changed


def _any_suppressed(doc):
    """Anything in the document suppressed (extapps/66: asked once per pass over the owners)."""
    try:
        return any(getattr(o, "Suppressed", False) for o in doc.Objects)
    except Exception:
        return True             # unknown: let _upstream_suppressed look as before


def _upstream_suppressed(obj, any_suppressed=None):
    ""




    try:
        if any_suppressed is False or (any_suppressed is None and
                                       not any(getattr(o, "Suppressed", False) for o in obj.Document.Objects)):
            return False
        from . import suppress
        return any(getattr(p, "Suppressed", False) for p in suppress.parents(obj))
    except Exception:
        return False


def _moved_target(doc, owner, prop, target, n):
    """The pick's signature from the feature it pointed into before: a feature inserted before
    a fillet (rolled back, a cut added, rolled forward) becomes the fillet's base, and its edges
    are looked for on the new base."""
    for k, sig in _memo.items():
        if k[0] == doc and k[1] == owner and k[2] == prop and k[4] == n and k[3] != target:
            return sig
    return None


def _write(obj, prop, items):
    kind = obj.getTypeIdOfProperty(prop)
    if kind in ("App::PropertyLinkSub", "App::PropertyLinkSubHidden"):
        target, subs = items[0]
        setattr(obj, prop, (target, subs))
    else:
        setattr(obj, prop, [(target, tuple(subs)) for target, subs in items])


def after_rebuild(doc):
    """check(), then one rebuild of what moved (no loop), then learn what is right."""
    if doc.Name in _busy:
        return []
    _busy.add(doc.Name)
    try:
        changed = []
        for _round in range(6):         # down the tree: a pick on a re-linked feature is found once it rebuilt
            now = check(doc)
            if not now:
                break
            changed += [o for o in now if o not in changed]
            for obj in now:
                try:
                    obj.touch()
                except Exception as _fw_err:
                    _fw_log("persistrefs.py:414", _fw_err)
            doc.recompute()
            try:
                from . import rebuildretry
                rebuildretry.carry_on(doc)      # past a failed feature, so the next round sees the model
            except Exception as _fw_err:
                _fw_log("persistrefs.py:420", _fw_err)
        learn(doc)
        return changed
    finally:
        _busy.discard(doc.Name)


def forget(obj, prop=None):
    """The user picked again (an edit, not a rebuild): what they picked now is the pick."""
    name = obj.Document.Name
    for d in (_memo, _seen, _picked, _box, _sides):
        for k in [k for k in d if k[0] == name and k[1] == obj.Name and (prop is None or k[2] == prop)]:
            del d[k]
    for k in [k for k in _doubt if k[0] == name and k[1] == obj.Name and (prop is None or k[2] == prop)]:
        _doubt.discard(k)


class _Watch:
    def slotBeforeRecomputeDocument(self, doc):
        if doc.Name not in _learned and not doc.Restoring:
            _restored(doc)          # the first rebuild after opening: the picks as saved first
        _recomputing.add(doc.Name)

    def slotChangedObject(self, obj, prop):
        try:
            doc = obj.Document.Name
        except Exception:
            return
        if doc in _recomputing or doc in _busy or prop in SKIP_PROPS:
            return
        try:
            if obj.Document.Transacting:
                return          # Undo / Redo puts an older pick back: what it was picked as still holds
        except Exception as _fw_err:
            _fw_log("persistrefs.py:454", _fw_err)
        try:
            from . import rebuildretry
            if doc in rebuildretry._busy:
                return          # a feature rebuilt past a failed one (carry_on), not the user
        except Exception as _fw_err:
            _fw_log("persistrefs.py:460", _fw_err)
        try:
            if obj.getTypeIdOfProperty(prop) not in LINK_TYPES:
                return
            now = [(t.Name, [_short(x) for x in subs]) for t, subs in dict(links(obj)).get(prop, [])]
            had = _picked.get((doc, obj.Name, prop))
            if had is not None and had == now:
                return          # FreeCAD only re-marked a name (?Edge35): the same picks
            if had is not None and [x for _t, x in had] == [x for _t, x in now] and \
                    getattr(obj, "BaseFeature", None) is not None and \
                    [t for t, _x in now] == [obj.BaseFeature.Name] * len(now):
                # a feature went in before this one (rolled back, a cut added): FreeCAD moved the
                # picks onto the new base under the same names. They are still the user's picks:
                # keep what they were, so check() finds them on the new base.
                _picked[(doc, obj.Name, prop)] = now
                return
            forget(obj, prop)
        except Exception as _fw_err:
            _fw_log("persistrefs.py:478", _fw_err)

    def slotRecomputedDocument(self, doc):
        _recomputing.discard(doc.Name)
        if doc.Name in _busy:
            return
        try:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda name=doc.Name: _later(name))
        except Exception as _fw_err:
            _fw_log("persistrefs.py:488", _fw_err)

    def slotDeletedDocument(self, doc):
        name = doc.Name
        for d in (_memo, _seen, _picked, _box, _sides):
            for k in [k for k in d if k[0] == name]:
                del d[k]
        _recomputing.discard(name)
        _learned.discard(name)


def _later(name):
    try:
        doc = App.getDocument(name)
    except Exception:
        return
    after_rebuild(doc)


def _restored(doc):
    if doc.Name in _learned:
        return
    _learned.add(doc.Name)
    try:
        learn(doc, saved=True)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: persistent references: %s\n" % error)


_watch = []


def install():
    if _watch:
        return
    _watch.append(_Watch())
    App.addDocumentObserver(_watch[0])
    try:
        from . import restorehook
        restorehook.on_restored(_restored)
    except Exception as _fw_err:
        _fw_log("persistrefs.py:529", _fw_err)
