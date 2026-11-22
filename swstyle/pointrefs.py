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
import Part

TOL = 1e-4


def _props(obj, prop):
    names = ("FW%sRefs" % prop, "FW%sAt" % prop, "FW%sWhere" % prop)
    if names[0] not in obj.PropertiesList:
        obj.addProperty("App::PropertyLinkSubListGlobal", names[0], "FreeCAD", "The faces or edges of %s" % prop)
        obj.addProperty("App::PropertyVectorList", names[1], "FreeCAD", "%s when they were linked" % prop)
        obj.addProperty("App::PropertyFloatList", names[2], "FreeCAD", "Where on its face or edge each point sat")
        for n in names:
            obj.setEditorMode(n, 2)
    sides = "FW%sSides" % prop
    if sides not in obj.PropertiesList:
        # an edge's two faces: FreeCAD can lose the edge itself (a Shell made wider renames its corner

        obj.addProperty("App::PropertyLinkSubListGlobal", sides, "FreeCAD", "The two faces of each edge of %s" % prop)
        obj.setEditorMode(sides, 2)
    return names


def _flat(value):
    out = []
    for item in list(value or []):
        src, subs = item
        for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
            out.append((src, sub.split(".")[-1]))
    return out


def _normal(face, p):
    u, v = face.Surface.parameter(p)
    n = face.normalAt(u, v)
    return n


def _find(shape, p, kind):
    """(element name, where) for point p on shape: kind edge (straight edges only), anyedge, face, bend."""
    vp = Part.Vertex(p)
    best = None
    if kind in ("edge", "anyedge"):
        for i, e in enumerate(shape.Edges, 1):
            if kind == "edge" and e.Curve.TypeId != "Part::GeomLine":
                continue
            d = e.distToShape(vp)[0]
            if d < TOL and (best is None or d < best[0]):
                best = (d, "Edge%d" % i, e)
        if best is None:
            return None
        e = best[2]
        try:
            t = e.Curve.parameter(p)
            lo, hi = e.FirstParameter, e.LastParameter
            where = (t - lo) / (hi - lo) if hi > lo else 0.5
        except Exception:
            where = 0.5
        return best[1], where
    for i, f in enumerate(shape.Faces, 1):
        if kind == "bend" and "Cylinder" not in f.Surface.TypeId:
            continue
        d, pts, _info = f.distToShape(vp)
        if (kind == "face" and d < TOL or kind == "bend") and (best is None or d < best[0]):
            best = (d, "Face%d" % i, f, pts[0][0])
    if best is None:
        return None
    if kind == "face":
        return best[1], 0.0
    f, q = best[2], best[3]
    return best[1], (p - q).dot(_normal(f, q))


def _sides_of(shape, edge_name):
    """The names of the two faces that meet at the edge (or [])."""
    try:
        e = shape.getElement(edge_name)
    except Exception:
        return []
    out = ["Face%d" % i for i, f in enumerate(shape.Faces, 1) if any(x.isSame(e) for x in f.Edges)]
    return out if len(out) == 2 else []


def _meet(shape, a, b):
    """The name of the edge where faces a and b of shape meet now, or None."""
    try:
        fa, fb = shape.getElement(a), shape.getElement(b)
    except Exception:
        return None
    for e in fa.Edges:
        if any(e.isSame(x) for x in fb.Edges):
            k = next((i for i, x in enumerate(shape.Edges, 1) if x.isSame(e)), None)
            if k is not None:
                return "Edge%d" % k
    return None


def _place(shape, name, kind, where, old):
    """The point on element name of shape as it is now, or None."""
    try:
        el = shape.getElement(name)
    except Exception:
        return None
    vp = Part.Vertex(old)
    if kind in ("edge", "anyedge"):
        if el.distToShape(vp)[0] < TOL:
            return old
        lo, hi = el.FirstParameter, el.LastParameter
        return el.valueAt(lo + (hi - lo) * min(max(where, 0.0), 1.0))
    if kind == "face":
        if el.distToShape(vp)[0] < TOL:
            return old
        from .smnormalcut import inside_point
        return inside_point(el)
    # bend: the point as deep under the bend face as it was
    d, pts, _info = el.distToShape(vp)
    q = pts[0][0]
    if abs(d - abs(where)) < TOL and el.isInside(q, TOL, True):
        return old
    from .smnormalcut import inside_point
    q = inside_point(el)
    return q + _normal(el, q) * where


def follow(obj, source, prop, kind):
    """Puts the points of obj.prop (a vector or a vector list) back on their faces or edges of
    source (an object) as they are now. A zero vector (no pick) is left as it is."""
    try:
        if source is None or source.Shape.isNull():
            return
        single = not isinstance(getattr(obj, prop), (list, tuple))
        points = [getattr(obj, prop)] if single else list(getattr(obj, prop))
        if single and points[0].Length < 1e-12:
            points = []
        refs_name, at_name, where_name = _props(obj, prop)
        refs, at, where = _flat(getattr(obj, refs_name)), list(getattr(obj, at_name)), list(getattr(obj, where_name))
        shape = source.Shape
        same = len(at) == len(points) == len(refs) == len(where) and \
            all((a - p).Length < 1e-9 for a, p in zip(at, points)) and all(s is source for s, _n in refs)
        sides = _flat(getattr(obj, "FW%sSides" % prop))
        if same and points:
            new = []
            for k, ((src, name), p, w) in enumerate(zip(refs, points, where)):
                q = _place(shape, name, kind, w, p) if name and not name.startswith("?") else None
                if q is None and kind in ("edge", "anyedge") and len(sides) == 2 * len(points):
                    (_s1, a), (_s2, b) = sides[2 * k], sides[2 * k + 1]
                    if a and b and not a.startswith("?") and not b.startswith("?"):
                        met = _meet(shape, a, b)
                        q = _place(shape, met, kind, w, p) if met else None
                new.append(q if q is not None else p)
            if any((a - b).Length > 1e-9 for a, b in zip(new, points)):
                setattr(obj, prop, new[0] if single else new)
                setattr(obj, at_name, new)
            return
        if same:
            return
        # new or changed picks: link them
        found = [_find(shape, p, kind) for p in points]
        if not all(found):
            if getattr(obj, refs_name):
                setattr(obj, refs_name, [])
                setattr(obj, at_name, [])
                setattr(obj, where_name, [])
            return
        setattr(obj, refs_name, [(source, n) for n, _w in found])
        setattr(obj, at_name, points)
        setattr(obj, where_name, [float(w) for _n, w in found])
        if kind in ("edge", "anyedge"):
            two = [_sides_of(shape, n) for n, _w in found]
            setattr(obj, "FW%sSides" % prop,
                    [(source, f) for pair in two for f in pair] if all(len(t) == 2 for t in two) else [])
    except Exception as _fw_err:
        _fw_log("pointrefs.follow", _fw_err)
