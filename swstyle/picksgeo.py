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

TOL = 1e-5


def signature(shape, sub):
    """('Edge'|'Face', point, direction, size) for shape's sub-element, or None."""
    try:
        el = shape.getElement(sub)
    except Exception:
        return None
    try:
        if sub.startswith("Edge"):
            a, b = el.ParameterRange
            m = (a + b) / 2.0
            return ("Edge", el.valueAt(m), el.tangentAt(m), el.Length)
        if sub.startswith("Face"):
            u0, u1, v0, v1 = el.ParameterRange
            p = el.valueAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
            if not el.isInside(p, TOL, True):
                p = el.CenterOfMass
            return ("Face", p, el.normalAt(*el.Surface.parameter(p)), el.Area)
    except Exception:
        return None
    return None


def _parallel(a, b):
    try:
        return abs(abs(a.normalize().dot(b.normalize())) - 1.0) < 1e-6
    except Exception:
        return False


def match(shape, sig):
    """The sub-element name in shape that is sig's pick, or None."""
    kind, point, direction, size = sig
    best = None
    vertex = None
    try:
        import Part
        vertex = Part.Vertex(point)
    except Exception:
        return None
    items = shape.Edges if kind == "Edge" else shape.Faces
    for i, el in enumerate(items):
        try:
            if el.distToShape(vertex)[0] > TOL:
                continue
            if kind == "Edge":
                d = el.tangentAt(el.Curve.parameter(point))
            else:
                d = el.normalAt(*el.Surface.parameter(point))
            if not _parallel(d, direction):
                continue
            got = el.Length if kind == "Edge" else el.Area
            score = abs(got - size)
            if best is None or score < best[0]:
                best = (score, "%s%d" % (kind, i + 1))
        except Exception:
            continue
    return best[1] if best else None


def dressups(objs):
    """[(feature, base, [(sub, signature)])] for the fillets, chamfers and drafts among objs."""
    out = []
    for obj in objs:
        try:
            if not obj.isDerivedFrom("PartDesign::DressUp") or "Invalid" in obj.State:
                continue
            base, subs = obj.Base
        except Exception:
            continue
        if base is None or not subs:
            continue
        key = (obj.Document.Name, obj.Name)
        if "Invalid" in base.State:
            # a failed base keeps an old shape: its faces are not the picks. The picks as they were
            # when it last built (a shell moved below a rib that then failed, and moved back)
            sigs = _good.get(key)
            if sigs:
                out.append((obj, base, sigs))
            continue
        sigs = [(sub, signature(base.Shape, sub)) for sub in subs]
        if all(s is not None for _sub, s in sigs):
            _good[key] = sigs
            out.append((obj, base, sigs))
    return out


_good = {}      # (document, feature) -> its picks' signatures the last time its base built


def remembered(obj):
    """The picks' signatures of obj from when its base last built, or None."""
    return _good.get((obj.Document.Name, obj.Name))


def same(shape, sub, sig):
    """True when shape's sub is still sig's pick."""
    got = signature(shape, sub)
    return got is not None and match(shape, sig) == sub


def repick(saved):
    """Pick each feature's edges again where they no longer are the edges it had. Returns the
    features changed."""
    changed = []
    for obj, _old_base, sigs in saved:
        try:
            base, subs = obj.Base
            if base is None or "Invalid" in base.State:
                continue        # an old shape: matching on it would pick the wrong faces
            want = [match(base.Shape, sig) for _sub, sig in sigs]
            if None in want:          # the earlier feature changed size: the nearest like edge
                want = [w or match_near(base.Shape, sig) for w, (_sub, sig) in zip(want, sigs)]
            if None in want:
                continue
            if list(subs) == want and "Invalid" not in obj.State:
                continue
            # (the same names on a failed feature: FreeCAD kept the names' history from the base it
            # had before the move, "Invalid edge link: ;#45:1;:H522,E.Edge1". Set again, they are
            # these edges of the base it has now.)
            obj.Base = (base, want)
            changed.append(obj)
        except Exception:
            continue
    return changed


# ---- any feature's picked faces and edges (Wrap, Split Line, Variable Fillet, ...) ---------------

# 10% deeper): the face that moved is still the face picked. FreeCAD loses its name ("?Face32").
# The picks of every feature's face/edge links are remembered by geometry when the feature builds,
# and found again on the new shape: where the point still lies on a face, as match(); else the
# nearest face of the same kind that runs the same way and is close in size.

_links_good = {}     # (document, feature) -> {property: [(object name, sub, signature)]}
SKIP = ("AttachmentSupport", "Support", "ExpressionEngine", "Profile", "ReferenceAxis", "Spine")


def _link_props(obj):
    out = []
    for p in obj.PropertiesList:
        if p in SKIP:
            continue
        try:
            t = obj.getTypeIdOfProperty(p)
        except Exception:
            continue
        if t in ("App::PropertyLinkSub", "App::PropertyLinkSubList", "App::PropertyLinkSubGlobal",
                 "App::PropertyLinkSubListGlobal"):
            out.append((p, t))
    return out


def _pairs(value):
    """[(object, sub)] of a LinkSub or LinkSubList value."""
    out = []
    if not value:
        return out
    if isinstance(value, tuple) and len(value) == 2 and hasattr(value[0], "Name"):
        value = [value]
    for item in value:
        try:
            o, subs = item
        except Exception:
            continue
        if isinstance(subs, str):
            subs = [subs]
        for s in subs or ():
            out.append((o, s))
    return out


def _clean(sub):
    return sub.split(".")[-1].lstrip("?")


def remember_links(objs):
    """Remembers the face/edge picks of the built features among objs (not the fillets: dressups())."""
    for obj in objs:
        try:
            if "Invalid" in obj.State or obj.isDerivedFrom("PartDesign::DressUp"):
                continue
            key = (obj.Document.Name, obj.Name)
            rec = {}
            for p, _t in _link_props(obj):
                got = []
                for o, sub in _pairs(getattr(obj, p)):
                    s = _clean(sub)
                    if not (s.startswith("Face") or s.startswith("Edge")) or o is None or "Invalid" in o.State:
                        got = None
                        break
                    sig = signature(o.Shape, s)
                    if sig is None:
                        got = None
                        break
                    got.append((o.Name, s, sig, _rel(o.Shape, sig[1])))
                if got:
                    rec[p] = got
            if rec:
                _links_good[key] = rec
        except Exception:
            continue


def _rel(shape, point):
    """point as a fraction of shape's bounding box on each axis (a top edge stays at the top)."""
    bb = shape.BoundBox
    out = []
    for p, lo, size in ((point.x, bb.XMin, bb.XLength), (point.y, bb.YMin, bb.YLength), (point.z, bb.ZMin, bb.ZLength)):
        out.append((p - lo) / size if size > 1e-9 else 0.5)
    return tuple(out)


def match_near(shape, sig, rel=None):
    """match(), or else the nearest element of sig's kind that runs the same way, close in size.
    Only a clear winner is taken: when two are about as near, None (the error stays, as the feature
    can't tell them apart). rel (where the pick sat in its shape's box) is kept for later use."""
    exact = match(shape, sig)
    if exact:
        return exact
    kind, point, direction, size = sig
    rel_box = rel
    try:
        import Part
        vertex = Part.Vertex(point)
    except Exception as _fw_err:
        _fw_log("picksgeo.py:252", _fw_err)
        return None
    scored = []
    items = shape.Edges if kind == "Edge" else shape.Faces
    for i, el in enumerate(items):
        try:
            near = el.distToShape(vertex)
            dist, foot = near[0], near[1][0][0]
            if kind == "Edge":
                d = el.tangentAt(el.Curve.parameter(foot))
            else:
                d = el.normalAt(*el.Surface.parameter(foot))
            if not _parallel(d, direction):
                continue
            if kind == "Face" and d.dot(direction) < 0:
                continue          # a face that faces the other way is not the one picked
            got = el.Length if kind == "Edge" else el.Area
            rel = abs(got - size) / max(size, 1e-9)
            if rel > 0.6:
                continue
            score = dist + rel * max(size, 1.0) ** (0.5 if kind == "Face" else 1.0)
            scored.append((score, "%s%d" % (kind, i + 1), dist))
        except Exception as _fw_err:
            _fw_log("picksgeo.py:275", _fw_err)
            continue
    if not scored:
        return None
    scored.sort()
    best = scored[0]
    if len(scored) > 1 and scored[1][0] < best[0] * 2.0 + 1e-6:
        return None             # two about as near: a guess could build on the wrong one; leave the error
    lim = max(shape.BoundBox.DiagonalLength * 0.25, 1.0)
    return best[1] if best[2] <= lim else None


def repick_links(objs):
    """Sets the remembered picks again, found on the shapes as they are now. Returns the changed."""
    changed = []
    for obj in objs:
        rec = _links_good.get((obj.Document.Name, obj.Name))
        if not rec:
            continue
        for p, items in rec.items():
            try:
                t = obj.getTypeIdOfProperty(p)
                doc = obj.Document
                new = []
                for item in items:
                    oname, sig = item[0], item[2]
                    rel = item[3] if len(item) > 3 else None
                    o = doc.getObject(oname)
                    if o is None or "Invalid" in o.State:
                        new = None
                        break
                    m = match_near(o.Shape, sig, rel)
                    if m is None:
                        new = None
                        break
                    new.append((o, m))
                if not new:
                    continue
                if t in ("App::PropertyLinkSub", "App::PropertyLinkSubGlobal"):
                    value = (new[0][0], [m for _o, m in new])
                else:
                    groups = []
                    for o, m in new:
                        if groups and groups[-1][0] is o:
                            groups[-1][1].append(m)
                        else:
                            groups.append((o, [m]))
                    value = [(o, tuple(ms)) for o, ms in groups]
                setattr(obj, p, value)
                changed.append(obj)
            except Exception:
                continue
    return changed
