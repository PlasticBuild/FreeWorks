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

TYPE = "PartDesign::FeaturePython"
PARTIAL_CONDITIONS = ("None", "Distance", "Percentage")
ICON = "FEATURES_FILLET"
SEP = "/"


def is_setback_fillet(obj):
    try:
        return obj.TypeId == TYPE and isinstance(obj.Proxy, SetbackFilletFeature)
    except Exception:
        return False


def vertex_edges(shape, vertex):
    """The edges of shape that end at vertex (seams and degenerate edges left out)."""
    return [e for e in shape.Edges if any(v.isSame(vertex) for v in e.Vertexes)
            and e.Length > 1e-9 and not e.isClosed()]


def _away(edge, vertex):
    """Unit direction along the edge, away from the vertex (its chord, for a curved edge)."""
    a = edge.valueAt(edge.FirstParameter)
    b = edge.valueAt(edge.LastParameter)
    d = (b - a) if (a - vertex.Point).Length < (b - vertex.Point).Length else (a - b)
    d.normalize()
    return d


def _same(a, b):
    if a.isSame(b):
        return True
    try:
        return abs(a.Length - b.Length) < 1e-7 and (a.CenterOfMass - b.CenterOfMass).Length < 1e-7
    except Exception:
        return False


def _corner_region(vertex, dirs, dists):
    """The solid near vertex on its side of every setback plane."""
    import Part
    V = App.Vector
    v = vertex.Point
    size = 4.0 * max(dists)
    region = Part.makeBox(size, size, size, v - V(size / 2.0, size / 2.0, size / 2.0))
    for d, s in zip(dirs, dists):
        plane = Part.makePlane(4 * size, 4 * size, V(0, 0, 0), d)
        plane.translate(v + d * s - plane.CenterOfMass)
        region = region.cut(plane.extrude(d * size))
    return region


def _patch(keep, edges):
    """A face over the closed loop of edges, tangent to the kept faces along each of them."""
    import Part
    from . import multiradius
    scratch = multiradius._scratch_doc()
    holder = scratch.addObject("Part::Feature", "SetbackKeep")
    fill = None
    try:
        holder.Shape = Part.Compound(keep)
        shape = holder.Shape
        e_names, f_names = [], []
        for e in edges:
            i = next((i for i, g in enumerate(shape.Edges, 1) if _same(g, e)), None)
            k = next((k for k, f in enumerate(shape.Faces, 1) if any(_same(g, e) for g in f.Edges)), None)
            if i is None or k is None:
                raise RuntimeError("The setback corner could not be closed.")
            e_names.append("Edge%d" % i)
            f_names.append("Face%d" % k)
        fill = scratch.addObject("Surface::Filling", "SetbackPatch")
        fill.BoundaryEdges = [(holder, n) for n in e_names]
        fill.BoundaryFaces = f_names
        fill.BoundaryOrder = [1] * len(e_names)      # G1: tangent to every face round it
        scratch.recompute()
        out = fill.Shape.copy()
        if out.isNull() or not out.Faces:
            raise RuntimeError("The setback corner could not be blended.")
        return out.Faces[0]
    finally:
        for obj in (fill, holder):
            if obj is not None:
                try:
                    scratch.removeObject(obj.Name)
                except Exception as _fw_err:
                    _fw_log("setbackfillet.py:127", _fw_err)
        multiradius._not_modified(scratch)


def setback_corner(solid, vertex, dirs, dists):
    """solid (already filleted) with the corner at vertex cut back and blended."""
    import Part
    region = _corner_region(vertex, dirs, dists)
    cut = solid.cut(region)
    if len(cut.Solids) == 1:
        cut = cut.Solids[0]
    planes = [(vertex.Point + d * s, d) for d, s in zip(dirs, dists)]

    def on_plane(f):
        if f.Surface.__class__.__name__ != "Plane":
            return False
        try:
            n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
        except Exception:
            return False
        return any(abs((f.CenterOfMass - p).dot(d)) < 1e-6 and abs(abs(n.dot(d)) - 1) < 1e-6
                   for p, d in planes)

    cap = [f for f in cut.Faces if on_plane(f)]
    keep = [f for f in cut.Faces if not any(f.isSame(c) for c in cap)]
    if not cap:
        raise RuntimeError("The setback corner could not be made: try other distances.")
    loop = []
    for f in cap:
        for e in f.Edges:
            if any(any(e.isSame(g) for g in k.Edges) for k in keep) and not any(e.isSame(x) for x in loop):
                loop.append(e)
    try:
        loop = Part.__sortEdges__(loop)     # Surface Filling takes its edges end to end
        closed = Part.Wire(loop).isClosed()
    except Exception:
        closed = False
    if not closed:
        raise RuntimeError("The setback corner could not be made: try other distances.")
    patch = _patch(keep, loop)
    shell = Part.Shell(keep + [patch])
    shell.sewShape()
    out = Part.Solid(Part.Shell(shell.Faces))
    try:
        out.fix(1e-7, 1e-7, 1e-7)
    except Exception as _fw_err:
        _fw_log("setbackfillet.py:173", _fw_err)
    if out.Volume < 0:
        out.reverse()
    if out.isNull() or not out.isValid() or out.Volume <= 0:
        raise RuntimeError("The setback corner could not be made: try other distances.")
    return out


def engulfed_faces(shape, edges, radii, whole=True):
    """Faces of features (bosses, cuts) inside the fillet's reach of the picked edges: not one
    of the faces the edges join, not a face at an edge's end, and within the radius. whole: with
    every face joined to them (the whole boss or cut, see _whole_features)."""
    import Part
    tubes, near, ends = [], [], []
    for e, r in zip(edges, radii):
        try:
            tubes.append(Part.Wire([e]).makePipeShell([Part.Wire(Part.makeCircle(
                r, e.valueAt(e.FirstParameter), e.tangentAt(e.FirstParameter)))], True, True))
        except Exception:
            a = e.valueAt(e.FirstParameter)
            b = e.valueAt(e.LastParameter)
            tubes.append(Part.makeCylinder(r, (b - a).Length, a, b - a))
        near += list(shape.ancestorsOfType(e, Part.Face))
        ends += list(e.Vertexes)
    if not tubes:
        return []
    zone = Part.makeCompound(tubes)
    out = []
    for f in shape.Faces:
        if any(f.isSame(a) for a in near) or any(any(v.isSame(w) for w in f.Vertexes) for v in ends):
            continue
        try:
            if f.common(zone).Area > 1e-6:
                out.append(f)
        except Exception:
            continue
    return _whole_features(shape, out, near) if whole else out


def _whole_features(shape, seeds, near):
    """The seeds and every face joined to them up to the faces the picked edges join: the
    whole boss or cut (its cap too), which OpenCascade's defeaturing needs to take it out."""
    import Part
    out = list(seeds)
    todo = list(seeds)
    while todo:
        f = todo.pop()
        for e in f.Edges:
            for g in shape.ancestorsOfType(e, Part.Face):
                if any(g.isSame(o) for o in out) or any(g.isSame(a) for a in near):
                    continue
                out.append(g)
                todo.append(g)
        if len(out) > 200:
            return list(seeds)      # it ran into the whole part: keep to what is in reach
    return out


def _too_much(base, faces, near=()):
    """Not a feature under the fillet: the far side of a wall the radius is thicker than (a flat
    face facing the opposite way to a face the edge joins), or more faces or area than a boss or
    cut has (a handful of faces, a small part of the part's area)."""
    try:
        if len(faces) > 24 or sum(f.Area for f in faces) > 0.25 * base.Area:
            return True
        flats = [n for n in (_normal(f) for f in near) if n is not None]
        for f in faces:
            m = _normal(f)
            if m is not None and any(m.dot(n) < -1 + 1e-6 for n in flats):
                return True
        return False
    except Exception:
        return True


def _normal(face):
    """The outward normal of a flat face, else None."""
    try:
        if type(face.Surface).__name__ != "Plane":
            return None
        u, v = face.Surface.parameter(face.CenterOfMass)
        return face.normalAt(u, v)
    except Exception:
        return None


def without_features(base, pairs):
    """(base with the engulfed features taken out, pairs on its edges); unchanged when none."""
    edges = [base.Edges[i - 1] for i, r in pairs]
    seeds = engulfed_faces(base, edges, [r for i, r in pairs], whole=False)
    if not seeds:
        return base, pairs
    import Part
    near = [f for e in edges for f in base.ancestorsOfType(e, Part.Face)]
    clean = None
    # the faces in reach alone first (a hole is its one wall): growing them to every joined face
    # can run on round a through-cut into the part's own faces, and nothing comes out at all
    for faces in (seeds, _whole_features(base, seeds, near)):
        if _too_much(base, faces, near):
            # a radius reaching the part's own walls (R10 round a shelled 8 mm flange took its
            # inside walls and bottom): OpenCascade's defeaturing of those never came back and
            # froze FreeCAD as the Fillet page opened; these are no feature to take off
            continue
        try:
            got = base.defeaturing(faces)
        except Exception:
            continue
        if got is None or got.isNull() or not got.isValid() or abs(got.Volume - base.Volume) < 1e-9:
            continue
        clean = got
        break
    if clean is None:
        raise RuntimeError("The features under the fillet could not be taken out: tick Keep features.")
    if len(clean.Solids) == 1:
        clean = clean.Solids[0]
    out = {}
    for i, r in pairs:
        e = base.Edges[i - 1]
        m = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
        for k, g in enumerate(clean.Edges, 1):
            if g.distToShape(Part_vertex(m))[0] < 1e-6:
                out[k] = r
    return clean, sorted(out.items())


def Part_vertex(p):
    import Part
    return Part.Vertex(p)


ROUND_REACH = 1.5     # Round corners: how far back along each edge, in fillet radii


def mitre_corners(base, pairs, skip=()):
    """(vertex, directions, distances) of every corner where two or more picked edges meet,
    not all the edges there are picked, and the picked ones are not tangent: FreeCAD's fillets
    meet there in a sharp mitre."""
    radius = dict(pairs)
    out = []
    for v in base.Vertexes:
        if any((v.Point - x.Point).Length < 1e-7 for x in skip):
            continue
        edges = vertex_edges(base, v)
        idx = [next((i for i, g in enumerate(base.Edges, 1) if g.isSame(e)), None) for e in edges]
        picked = [i for i in idx if i in radius]
        if len(picked) < 2 or len(picked) == len(edges):
            continue
        dirs = [_away(e, v) for e in edges]
        pd = [d for d, i in zip(dirs, idx) if i in radius]
        if all(abs(abs(a.dot(b)) - 1) < 1e-6 for a in pd for b in pd):
            continue        # tangent (one smooth run of edges): no mitre
        reach = ROUND_REACH * max(radius[i] for i in picked)
        if any(reach >= e.Length - 1e-9 for e in edges):
            raise RuntimeError("Round corners: an edge at a corner is shorter than %s the radius."
                               % ROUND_REACH)
        out.append((v, dirs, [reach] * len(dirs)))
    return out


def _edge_on(shape, edge):
    """The index (1-based) of shape's edge that edge lies on (by its middle), else None."""
    m = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
    return next((k for k, g in enumerate(shape.Edges, 1) if g.distToShape(Part_vertex(m))[0] < 1e-6), None)


def ordered_fillet(base, pairs, first):
    """base filleted with the edges in first (indices) first, then the rest over them."""
    from . import multiradius
    head = [(i, r) for i, r in pairs if i in first]
    rest = [(i, r) for i, r in pairs if i not in first]
    if not head or not rest:
        return multiradius.multi_fillet(base, pairs)
    out = multiradius.multi_fillet(base, head)
    moved = []
    for i, r in rest:
        k = _edge_on(out, base.Edges[i - 1])
        if k is None:
            raise RuntimeError("An edge was lost under the first fillet of the corner.")
        moved.append((k, r))
    return multiradius.multi_fillet(out, moved)


def corner_alternatives(base, pairs, vertex):
    """[(label, key, shape)] for the corner at vertex: the fillets together, one of the corner's
    edges first, and run round; only shapes that differ."""
    radius = dict(pairs)
    edges = vertex_edges(base, vertex)
    idx = [next((i for i, g in enumerate(base.Edges, 1) if g.isSame(e)), None) for e in edges]
    picked = [i for i in idx if i in radius]
    out = []

    def add(label, key, shape):
        if shape is None or shape.isNull() or not shape.isValid():
            return
        if any(abs(shape.Volume - s.Volume) < 1e-6 and len(shape.Faces) == len(s.Faces) for _l, _k, s in out):
            return
        out.append((label, key, shape))
    try:
        add("Default", "", setback_fillet(base, pairs, []))
    except Exception as _fw_err:
        _fw_log("setbackfillet.py:340", _fw_err)
    for n, i in enumerate(picked, 1):
        try:
            add("Edge %d first" % n, "Edge%d" % i, ordered_fillet(base, pairs, [i]))
        except Exception:
            continue
    try:
        add("Round", "round", setback_fillet(base, pairs, [], False, [(vertex, "round")]))
    except Exception as _fw_err:
        _fw_log("setbackfillet.py:349", _fw_err)
    return out


def setback_fillet(base, pairs, setbacks, round_corners=False, corners=()):
    """base filleted with (edge index, radius) pairs, then every (vertex, [(edge index,
    distance)]) setback corner cut back and blended; with round_corners, every mitre corner
    too. corners: [(vertex, "round" or edge index filleted first)] from the Corner tab."""
    from . import multiradius
    first = [c for v, c in corners if c != "round"]
    out = ordered_fillet(base, pairs, first) if first else multiradius.multi_fillet(base, pairs)
    rounds = [v for v, c in corners if c == "round"]
    skip = [v for v, _rows in setbacks]
    if round_corners:
        for vertex, dirs, dists in mitre_corners(base, pairs, skip):
            out = setback_corner(out, vertex, dirs, dists)
            skip.append(vertex)
    radius = dict(pairs)
    for vertex in rounds:
        if any((vertex.Point - v.Point).Length < 1e-7 for v in skip):
            continue
        edges = vertex_edges(base, vertex)
        picked = [radius[i] for i, e in ((next((i for i, g in enumerate(base.Edges, 1) if g.isSame(e)), None), e)
                                         for e in edges) if i in radius]
        if not picked:
            continue
        reach = ROUND_REACH * max(picked)
        out = setback_corner(out, vertex, [_away(e, vertex) for e in edges], [reach] * len(edges))
    radius = dict(pairs)
    for vertex, rows in setbacks:
        dirs, dists = [], []
        for i, s in rows:
            if i not in radius:
                raise RuntimeError("A setback vertex needs all its edges in Items To Fillet.")
            if s <= radius[i] + 1e-9:
                raise RuntimeError("Setback distances must be larger than the fillet radius.")
            e = base.Edges[i - 1]
            if s >= e.Length - 1e-9:
                raise RuntimeError("A setback distance is as long as an edge at the vertex.")
            dirs.append(_away(e, vertex))
            dists.append(s)
        out = setback_corner(out, vertex, dirs, dists)
    return out


def _clean(base, pairs, setbacks):
    """Keep features off: the base without its engulfed features, with the picked edges and
    setback corners found again on it."""
    clean, new_pairs = without_features(base, pairs)
    if clean is base:
        return base, pairs, setbacks
    old_to_new = {}
    for i, r in pairs:
        e = base.Edges[i - 1]
        m = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
        k = next((k for k, g in enumerate(clean.Edges, 1) if g.distToShape(Part_vertex(m))[0] < 1e-6), None)
        old_to_new[i] = k
    out = []
    for vertex, rows in setbacks:
        v = next((x for x in clean.Vertexes if (x.Point - vertex.Point).Length < 1e-7), None)
        if v is None:
            continue
        out.append((v, [(old_to_new.get(i), s) for i, s in rows if old_to_new.get(i)]))
    return clean, new_pairs, out


class SetbackFilletFeature:
    def __init__(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def setup(self, obj):
        props = obj.PropertiesList
        if "Base" not in props:
            obj.addProperty("App::PropertyLinkSub", "Base", "Fillet", "Items to fillet")
        if "Radius" not in props:
            obj.addProperty("App::PropertyLength", "Radius", "Fillet", "Radius")
            obj.Radius = 1.0
        if "ItemRadii" not in props:
            obj.addProperty("App::PropertyFloatList", "ItemRadii", "Fillet",
                            "Multi Radius Fillet: each item's radius, in mm, in the order of Base")
        if "SetbackVertices" not in props:
            obj.addProperty("App::PropertyStringList", "SetbackVertices", "Setback Parameters",
                            "Setback vertices (vertices of the base)")
        if "SetbackEdges" not in props:
            obj.addProperty("App::PropertyStringList", "SetbackEdges", "Setback Parameters",
                            "Vertex/Edge of every setback distance (names in the base)")
        if "KeepFeatures" not in props:
            obj.addProperty("App::PropertyBool", "KeepFeatures", "Fillet Options",
                            "Off: the fillet rolls over the bosses and cuts inside its radius")
            obj.KeepFeatures = True
        if "RoundCorners" not in props:
            obj.addProperty("App::PropertyBool", "RoundCorners", "Fillet Options",
                            "The fillets run round the corners where they meet")
            obj.RoundCorners = False
        if "CornerFirst" not in props:
            obj.addProperty("App::PropertyStringList", "CornerFirst", "Fillet Options",
                            "FilletXpert Corner: Vertex/Edge filleted first at that corner, or Vertex/round")
        if "SetbackDistances" not in props:
            obj.addProperty("App::PropertyFloatList", "SetbackDistances", "Setback Parameters",
                            "Setback distances, in mm, in the order of SetbackEdges")
        if "PartialStart" not in props:
            for end in ("Start", "End"):
                obj.addProperty("App::PropertyEnumeration", "Partial" + end, "Partial Edge Parameters",
                                "%s condition of a partial edge fillet" % end)
                setattr(obj, "Partial" + end, list(PARTIAL_CONDITIONS))
                obj.addProperty("App::PropertyFloat", "Partial%sValue" % end, "Partial Edge Parameters",
                                "%s offset: a distance in mm, or a percentage of the edge" % end)
            obj.addProperty("App::PropertyBool", "PartialFlip", "Partial Edge Parameters",
                            "Measure from the edge's other end")
        if "SetbackRefs" not in props:
            # the setback and corner names as a link, so FreeCAD renames them with the part
            obj.addProperty("App::PropertyLinkSub", "SetbackRefs", "Setback Parameters",
                            "The vertices and edges the setback and corner lists name (kept up to date)")
            obj.addProperty("App::PropertyStringList", "SetbackRefNames", "Setback Parameters",
                            "The names in SetbackRefs when they were last written")
            obj.setEditorMode("SetbackRefs", 2)
            obj.setEditorMode("SetbackRefNames", 2)

    def execute(self, obj):
        if "PartialStart" not in obj.PropertiesList or "SetbackRefs" not in obj.PropertiesList:
            self.setup(obj)
        follow_names(obj)
        whole = self._execute(obj)
        base = obj.BaseFeature.Shape
        obj.Shape = partial_edge(base, whole, self._pairs, *partial_span(obj))

    def _execute(self, obj):
        from . import multiradius
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
        if base is None or base.isNull():
            raise RuntimeError("Fillet needs a part")
        source = obj.Base[0] if obj.Base else obj.BaseFeature
        subs = list(obj.Base[1]) if obj.Base else []
        pairs = multiradius.edge_radii(base, source.Shape, subs, list(obj.ItemRadii), obj.Radius.Value)
        self._pairs = list(pairs)
        shape = source.Shape
        rows = {}
        for key, s in zip(obj.SetbackEdges, obj.SetbackDistances):
            vname, _sep, ename = key.partition(SEP)
            rows.setdefault(vname, []).append((ename, float(s)))
        setbacks = []
        for vname in obj.SetbackVertices:
            try:
                p = shape.getElement(vname).Point
            except Exception:
                continue
            vertex = next((v for v in base.Vertexes if (v.Point - p).Length < 1e-7), None)
            if vertex is None:
                continue
            out = []
            for ename, s in rows.get(vname, []):
                try:
                    g = shape.getElement(ename)
                except Exception:
                    continue
                i = next((i for i, e in enumerate(base.Edges, 1) if multiradius._same_edge(e, g)), None)
                if i is not None:
                    out.append((i, s))
            if len(out) < 3:
                raise RuntimeError("A setback vertex needs three or more filleted edges meeting at it.")
            setbacks.append((vertex, out))
        corners = []
        for key in obj.CornerFirst:
            vname, _sep, what = key.partition(SEP)
            try:
                p = shape.getElement(vname).Point
                vertex = next(v for v in base.Vertexes if (v.Point - p).Length < 1e-7)
            except Exception:
                continue
            if what == "round":
                corners.append((vertex, "round"))
                continue
            try:
                g = shape.getElement(what)
                i = next(i for i, e in enumerate(base.Edges, 1) if multiradius._same_edge(e, g))
                corners.append((vertex, i))
            except Exception:
                continue
        if not obj.KeepFeatures:
            base, pairs, setbacks = _clean(base, pairs, setbacks)
            corners = [(next((x for x in base.Vertexes if (x.Point - v.Point).Length < 1e-7), v),
                        c if c == "round" else _edge_on(base, obj.BaseFeature.Shape.Edges[c - 1]))
                       for v, c in corners]
            return setback_fillet(base, pairs, setbacks, obj.RoundCorners, corners)
        try:
            kept = keep_features(base, pairs, setbacks, obj.RoundCorners, corners, obj)
        except Exception:
            kept = None
        # no feature in reach (or it could not be taken off and put back): FreeCAD's own fillet
        return kept if kept is not None else setback_fillet(base, pairs, setbacks, obj.RoundCorners, corners)

    # (these three sat after keep_features' return, inside that function, so the feature never had
    # them: an opened file did not get the newer properties until its first rebuild)
    def onDocumentRestored(self, obj):
        self.setup(obj)
        obj.Proxy = self
        try:        # an older file: link the names now, while they still name the saved part
            follow_names(obj)
        except Exception as _fw_err:
            _fw_log("setbackfillet.py:restore", _fw_err)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _list_names(obj):
    names = []
    for v in obj.SetbackVertices:
        names.append(v)
    for key in list(obj.SetbackEdges) + list(obj.CornerFirst):
        v, _sep, what = key.partition(SEP)
        names.append(v)
        if what and what != "round":
            names.append(what)
    out = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


def follow_names(obj):
    ""



    source = obj.Base[0] if obj.Base else obj.BaseFeature
    if source is None:
        return
    link = obj.SetbackRefs
    was = list(obj.SetbackRefNames)
    if link is not None and link[0] == source and was and len(link[1]) == len(was):
        now = [sub.split(".")[-1] for sub in link[1]]
        moved = {w: n for w, n in zip(was, now) if n and not n.startswith("?") and n != w}
        if moved:
            def m(name):
                return moved.get(name, name)

            def key(text):
                v, sep, what = text.partition(SEP)
                return m(v) + sep + (what if what in ("", "round") else m(what))
            verts = [m(v) for v in obj.SetbackVertices]
            edges = [key(k) for k in obj.SetbackEdges]
            corners = [key(k) for k in obj.CornerFirst]
            if verts != list(obj.SetbackVertices):
                obj.SetbackVertices = verts
            if edges != list(obj.SetbackEdges):
                obj.SetbackEdges = edges
            if corners != list(obj.CornerFirst):
                obj.CornerFirst = corners
    names = _list_names(obj)
    current = [sub.split(".")[-1] for sub in link[1]] if link is not None and link[0] == source else None
    if names != was or current != names:
        try:
            obj.SetbackRefs = (source, names) if names else None
            obj.SetbackRefNames = names
        except Exception as _fw_err:
            _fw_log("setbackfillet.py:follow_names", _fw_err)


def partial_span(obj):
    """(start, end) of a partial edge fillet as fractions of the edge (0 and 1: the whole edge)."""
    out = []
    for end in ("Start", "End"):
        kind = str(getattr(obj, "Partial" + end, "None") or "None")
        value = float(getattr(obj, "Partial%sValue" % end, 0.0) or 0.0)
        out.append((kind, value))
    return out[0], out[1], bool(getattr(obj, "PartialFlip", False))


def _fraction(edge, kind, value):
    if kind == "Distance":
        return max(0.0, value) / max(edge.Length, 1e-12)
    if kind == "Percentage":
        return max(0.0, value) / 100.0
    return 0.0


def partial_edge(base, whole, pairs, start, end, flip):
    ""



    if (start[0] == "None" and end[0] == "None") or len(pairs) != 1:
        return whole
    import Part
    edge = base.Edges[pairs[0][0] - 1]
    radius = float(pairs[0][1])
    a = _fraction(edge, *start)
    b = 1.0 - _fraction(edge, *end)
    if flip:
        a, b = 1.0 - b, 1.0 - a
    if b - a < 1e-6:
        raise RuntimeError("The start and end offsets overlap: the partial fillet has no length.")
    if a <= 1e-9 and b >= 1.0 - 1e-9:
        return whole
    u0, u1 = edge.FirstParameter, edge.LastParameter
    reach = 3.0 * radius + 1.0

    def tube(t0, t1):
        piece = edge.Curve.toShape(u0 + (u1 - u0) * t0, u0 + (u1 - u0) * t1)
        p = piece.valueAt(piece.FirstParameter)
        d = piece.tangentAt(piece.FirstParameter)
        ring = Part.Wire(Part.makeCircle(reach, p, d))
        pipe = Part.Wire(piece).makePipeShell([ring], True, True)
        return pipe

    taken = base.cut(whole)
    keep = []
    for t0, t1 in ((0.0, a), (b, 1.0)):
        if t1 - t0 > 1e-9:
            keep.append(taken.common(tube(t0, t1)))
    out = whole
    for k in keep:
        if k.Volume > 1e-9:
            out = out.fuse(k)
    try:
        out = out.removeSplitter()
    except Exception as _fw_err:
        _fw_log("setbackfillet.py:partial", _fw_err)
    if len(out.Solids) == 1:
        out = out.Solids[0]
    return out


def keep_features(base, pairs, setbacks, round_corners, corners, obj):
    ""


    clean, new_pairs, new_setbacks = _clean(base, pairs, setbacks)
    if clean is base:
        return None
    new_corners = [(next((x for x in clean.Vertexes if (x.Point - v.Point).Length < 1e-7), v),
                    c if c == "round" else _edge_on(clean, obj.BaseFeature.Shape.Edges[c - 1]))
                   for v, c in corners]
    rounded = setback_fillet(clean, new_pairs, new_setbacks, round_corners, new_corners)
    added = base.cut(clean)
    taken = clean.cut(base)
    out = rounded
    if added.Volume > 1e-9:
        out = out.fuse(added)
    if taken.Volume > 1e-9:
        out = out.cut(taken)
    try:
        out = out.removeSplitter()
    except Exception as _fw_err:
        _fw_log("setbackfillet.py:540", _fw_err)
    if len(out.Solids) == 1:
        out = out.Solids[0]
    if out.isNull() or not out.isValid():
        return None
    return out


class SetbackFilletView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            icon = icons.family(ICON)
            if not icon.isNull():
                return icon
        except Exception as _fw_err:
            _fw_log("setbackfillet.py:572", _fw_err)
        return ""

    def claimChildren(self):
        return []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        from . import filletpm
        if Gui.Control.activeDialog():
            return False
        return bool(filletpm.open_page(vobj.Object))

    def unsetEdit(self, vobj, mode=0):
        return True

    def doubleClicked(self, vobj):
        import FreeCADGui as Gui
        from . import filletpm
        if not Gui.Control.activeDialog():
            filletpm.open_page(vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def setup_new(obj):
    SetbackFilletFeature(obj)
    if App.GuiUp:
        SetbackFilletView(obj.ViewObject)
    return obj


def new(body, name="Fillet"):
    label = None
    try:
        from . import naming
        label = naming.next_label(body.Document, "Fillet")
    except Exception as _fw_err:
        _fw_log("setbackfillet.py:617", _fw_err)
    obj = body.newObject(TYPE, name)
    setup_new(obj)
    if label:
        obj.Label = label
    return obj
