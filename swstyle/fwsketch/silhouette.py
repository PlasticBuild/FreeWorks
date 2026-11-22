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

MARK = "FreeWorksSilhouette"
LABEL = "Silhouette Edge"
PIXELS = 6.0


ANALYTIC = ("Cylinder", "Sphere")
FLAT = ("Plane",)
SAMPLES = 32          # per direction on a sampled face
MAX_FACES = 400       # curved faces looked at per part (hover stays quick on big parts)


def _faces_with_outline(shape):
    n = 0
    for i, face in enumerate(getattr(shape, "Faces", []) or []):
        name = type(face.Surface).__name__
        if name in FLAT:
            continue
        n += 1
        if n > MAX_FACES:
            return
        yield i, face, name


def _sides(face, kind, normal):
    if kind in ANALYTIC:
        exact = [outline(face, kind, side, normal) for side in (0, 1)]
        if any(e is not None for e in exact):
            return list(enumerate(exact))
        return [(100 + k, e) for k, e in enumerate(sampled_outlines(face, normal))]   # slanted: sampled
    return list(enumerate(sampled_outlines(face, normal)))


def outline(face, kind, side, normal):
    """The silhouette (Part.Edge) of a face seen along normal, or None. Cylinders and spheres
    exactly; cones, tori and other curved faces by sampling (sampled_outlines, rough)."""
    if kind not in ANALYTIC or side >= 100:
        found = sampled_outlines(face, normal)
        side = side - 100 if side >= 100 else side
        return found[side] if 0 <= side < len(found) else None
    import Part
    n = App.Vector(normal)
    if n.Length < 1e-12:
        return None
    n.normalize()
    s = face.Surface
    tol = 1e-6
    if kind == "Cylinder":
        axis = App.Vector(s.Axis)
        axis.normalize()
        if abs(axis.dot(n)) > 1e-6:
            return None          # seen end on or slanted: no straight outline in the sketch plane
        d = axis.cross(n)
        d.normalize()
        if side:
            d = d * -1.0
        r = s.Radius
        c = App.Vector(s.Center)
        # the axis extent of the face
        along = [(v.Point - c).dot(axis) for v in face.Vertexes]
        try:
            u0, u1, v0, v1 = face.ParameterRange
            along += [v0, v1] if abs(v1 - v0) < 1e9 else []
        except Exception as _fw_err:
            _fw_log("fwsketch/silhouette.py:96", _fw_err)
        if not along:
            return None
        lo, hi = min(along), max(along)
        if hi - lo < tol:
            return None
        p0 = c + axis * lo + d * r
        p1 = c + axis * hi + d * r
        mid = (p0 + p1) * 0.5
        try:
            if face.distToShape(Part.Vertex(mid))[0] > 1e-4:
                return None      # the face does not wrap round to that side
        except Exception:
            return None
        return Part.LineSegment(p0, p1).toShape()
    if kind == "Sphere":
        if side:
            return None
        c = App.Vector(s.Center)
        circle = Part.Circle(c, n, s.Radius)
        edge = circle.toShape()
        try:
            if face.distToShape(Part.Vertex(edge.valueAt(edge.FirstParameter)))[0] > 1e-4:
                return None
        except Exception:
            return None
        return edge
    return None


_cache = {}


def candidates(doc, normal, skip=()):
    """[(object, face index, side, edge)] of the shown solids' outlines seen along normal
    (kept while the shapes and the direction stay the same: hover asks on every move)."""
    try:
        key = (doc.Name, tuple(round(x, 9) for x in normal), tuple(skip),
               tuple((o.Name, o.Shape.hashCode(), bool(getattr(getattr(o, "ViewObject", None), "Visibility", True)))
                     for o in doc.Objects if hasattr(o, "Shape") and not getattr(o, MARK, False)))
    except Exception:
        key = None
    if key is not None and _cache.get("key") == key:
        return _cache["value"]
    out = _candidates(doc, normal, skip)
    _cache.clear()
    if key is not None:
        _cache.update(key=key, value=out)
    return out


def _candidates(doc, normal, skip):
    out = []
    for obj in doc.Objects:
        if obj.Name in skip or not hasattr(obj, "Shape") or getattr(obj, MARK, False):
            continue
        if obj.isDerivedFrom("Sketcher::SketchObject"):
            continue
        try:
            if App.GuiUp and not obj.ViewObject.Visibility:
                continue
        except Exception as _fw_err:
            _fw_log("fwsketch/silhouette.py:158", _fw_err)
        shape = obj.Shape
        if shape.isNull() or not shape.Solids:
            continue
        for i, face, kind in _faces_with_outline(shape):
            try:
                edges = _sides(face, kind, normal)
            except Exception:
                continue
            for side, edge in edges:
                if edge is not None:
                    out.append((obj, i, side, edge))
    return out


def _fit(points):
    """A line, a circle or a spline through the outline's points (a Part.Edge), or None."""
    import Part
    pts = [App.Vector(p) for p in points]
    if len(pts) < 2:
        return None
    a, b = pts[0], pts[-1]
    closed = (a - b).Length < 1e-6 * max(1.0, max((p - a).Length for p in pts))
    span = max((p - a).Length for p in pts)
    if span < 1e-7:
        return None
    tol = max(1e-6, span * 2e-4)
    if not closed:
        d = b - a
        if d.Length > 1e-9:
            d.normalize()
            if all(((p - a) - d * (p - a).dot(d)).Length < tol for p in pts):
                return Part.LineSegment(a, b).toShape()
    if len(pts) >= 3:
        try:
            k = len(pts) // 3
            c = Part.Circle(pts[0], pts[k], pts[2 * k])
            if all(abs((p - c.Center).Length - c.Radius) < tol for p in pts) and \
                    all(abs((p - c.Center).dot(c.Axis)) < tol for p in pts):
                if closed:
                    return c.toShape()
                return Part.ArcOfCircle(pts[0], pts[len(pts) // 2], pts[-1]).toShape()
        except Exception as _fw_err:
            _fw_log("fwsketch/silhouette.py:201", _fw_err)
    try:
        spline = Part.BSplineCurve()
        if closed:
            spline.interpolate(pts[:-1], PeriodicFlag=True)
        else:
            spline.interpolate(pts)
        return spline.toShape()
    except Exception:
        return None


def _chains(rows, periodic):
    """Joins each row's crossings into curves: crossing k of a row goes on with the nearest
    crossing of the next row. rows: [[point, ...] per row]. Returns [[point, ...]]."""
    chains, open_ = [], []
    for row in rows:
        used = set()
        nxt = []
        for chain in open_:
            last = chain[-1]
            best = None
            for j, p in enumerate(row):
                if j in used:
                    continue
                d = (p - last).Length
                if best is None or d < best[0]:
                    best = (d, j)
            if best is None:
                chains.append(chain)
                continue
            used.add(best[1])
            chain.append(row[best[1]])
            nxt.append(chain)
        for j, p in enumerate(row):
            if j not in used:
                nxt.append([p])
        open_ = nxt
    chains += open_
    out = []
    for c in chains:
        if len(c) < 3:
            continue
        if periodic and (c[0] - c[-1]).Length < 3.0 * max((c[i] - c[i + 1]).Length for i in range(len(c) - 1)):
            c = c + [c[0]]
        out.append(c)
    return out


def sampled_outlines(face, normal):
    ""


    bb = face.BoundBox     # a freed shape's hashCode can come back for another one: its size too
    key = (face.hashCode() if hasattr(face, "hashCode") else id(face), round(face.Area, 9),
           tuple(round(x, 9) for x in (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)),
           tuple(round(x, 9) for x in normal))
    hit = _sampled_cache.get(key)
    if hit is not None:
        return hit
    n = App.Vector(normal)
    n.normalize()
    u0, u1, v0, v1 = face.ParameterRange
    big = 1e6
    if not all(abs(x) < big for x in (u0, u1, v0, v1)):
        return []
    surf = face.Surface

    def f(u, v):
        try:
            val = face.normalAt(u, v).dot(n)
        except Exception:
            return None
        return None if abs(val) < 1e-9 else val     # seen edge on there: no side to tell

    def inside(u, v):
        try:
            return face.isPartOfDomain(u, v)
        except Exception:
            return True

    def scan(along_u):
        rows = []
        a0, a1, b0, b1 = (u0, u1, v0, v1) if along_u else (v0, v1, u0, u1)
        try:
            closed = surf.isUClosed() if along_u else surf.isVClosed()
        except Exception:
            closed = False
        try:
            periodic = surf.isUPeriodic() if along_u else surf.isVPeriodic()
            whole = abs((a1 - a0) - (surf.UPeriod() if along_u else surf.VPeriod())) < 1e-7 if periodic else closed
        except Exception:
            whole = closed
        wrap = bool(closed or periodic) and whole
        step = (a1 - a0) / SAMPLES

        def at(a, b):
            if a > a1:
                a -= a1 - a0        # once round past the seam
            return (a, b) if along_u else (b, a)
        # a periodic face is sampled off its seam and once round past it (an outline on the
        # seam is found too)
        count = SAMPLES + 1 if wrap else SAMPLES + 1
        offset = 0.5 * step if wrap else 0.0
        for j in range(SAMPLES + 1):
            b = b0 + (b1 - b0) * j / SAMPLES
            row = []
            prev = None
            for i in range(count):
                a = a0 + offset + step * i      # past a1 once round: folded back by at()
                uv = at(a, b)
                val = f(*uv)
                if val is not None and prev is not None and prev[1] is not None and \
                        (prev[1] < 0.0) != (val < 0.0) and abs(val - prev[1]) < 1.5:
                    lo, hi, flo = prev[0], a, prev[1]
                    for _ in range(30):
                        mid = 0.5 * (lo + hi)
                        fm = f(*at(mid, b))
                        if fm is None:
                            lo = hi = mid       # right on it
                            break
                        if (fm < 0.0) == (flo < 0.0):
                            lo, flo = mid, fm
                        else:
                            hi = mid
                    m = 0.5 * (lo + hi)
                    puv = at(m, b)
                    if inside(*puv):
                        row.append(surf.value(*puv))
                if val is not None:
                    prev = (a, val)     # a sample right on the outline: compare across it
            rows.append(row)
        return rows

    found = []
    for along_u in (True, False):
        rows = scan(along_u)
        if sum(len(r) for r in rows) >= 3:
            periodic = (face.Surface.isUPeriodic() if not along_u else face.Surface.isVPeriodic()) \
                if hasattr(face.Surface, "isUPeriodic") else False
            for chain in _chains(rows, periodic):
                edge = _fit(chain)
                if edge is not None:
                    found.append(edge)
    found = _distinct(found)
    if len(_sampled_cache) > 2000:
        _sampled_cache.clear()
    _sampled_cache[key] = found
    return found


_sampled_cache = {}


def _distinct(edges):
    out = []
    for e in edges:
        m = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
        if any(abs(o.Length - e.Length) < 1e-5 and o.distToShape(Part_vertex(m))[0] < 1e-5 for o in out):
            continue
        out.append(e)
    return out


def Part_vertex(p):
    import Part
    return Part.Vertex(p)


def _sketch_normal(sketch):
    return sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))


def _screen_distance(view, edge, pos):
    """Pixels from pos (x, y, Coin's bottom-up) to the edge as seen in view."""
    try:
        pts = edge.discretize(Deflection=0.05) if edge.Length > 0 else []
    except Exception:
        pts = [v.Point for v in edge.Vertexes]
    best = None
    prev = None
    for p in pts:
        q = view.getPointOnViewport(p)
        q = (q[0], q[1])
        if prev is not None:
            ax, ay = prev
            bx, by = q
            dx, dy = bx - ax, by - ay
            ll = dx * dx + dy * dy
            t = 0.0 if ll < 1e-12 else max(0.0, min(1.0, ((pos[0] - ax) * dx + (pos[1] - ay) * dy) / ll))
            d = math.hypot(ax + t * dx - pos[0], ay + t * dy - pos[1])
            best = d if best is None or d < best else best
        prev = q
    return best if best is not None else 1e18


def _near_on_screen(view, bb, pos, pixels):
    """The pointer is within pixels of the box's outline on screen (cheap test before sampling)."""
    xs, ys = [], []
    for x in (bb.XMin, bb.XMax):
        for y in (bb.YMin, bb.YMax):
            for z in (bb.ZMin, bb.ZMax):
                q = view.getPointOnViewport(App.Vector(x, y, z))
                xs.append(q[0]); ys.append(q[1])
    return min(xs) - pixels <= pos[0] <= max(xs) + pixels and min(ys) - pixels <= pos[1] <= max(ys) + pixels


def nearest(view, sketch, pos=None, pixels=PIXELS):
    """(source object, face index, side, edge) of the outline under the pointer, or None. Only
    faces whose box is under the pointer are looked at (a big part stays quick on hover)."""
    pos = pos or view.getCursorPos()
    normal = _sketch_normal(sketch)
    found = None
    for obj in sketch.Document.Objects:
        if obj is sketch or not hasattr(obj, "Shape") or getattr(obj, MARK, False) \
                or obj.isDerivedFrom("Sketcher::SketchObject"):
            continue
        try:
            if App.GuiUp and not obj.ViewObject.Visibility:
                continue
        except Exception as _fw_err:
            _fw_log("fwsketch/silhouette.py:422", _fw_err)
        shape = obj.Shape
        if shape.isNull() or not shape.Solids or not _near_on_screen(view, shape.BoundBox, pos, pixels):
            continue
        for i, face, kind in _faces_with_outline(shape):
            if not _near_on_screen(view, face.BoundBox, pos, pixels):
                continue
            try:
                edges = _sides(face, kind, normal)
            except Exception:
                continue
            for side, edge in edges:
                if edge is None:
                    continue
                d = _screen_distance(view, edge, pos)
                if d <= pixels and (found is None or d < found[0]):
                    found = (d, (obj, i, side, edge))
    return found[1] if found else None


class SilhouetteFeature:
    """The outline of a face as seen along Direction (see the module)."""

    def __init__(self, obj):
        obj.Proxy = self
        self._props(obj)

    @staticmethod
    def _props(obj):
        if not hasattr(obj, "Source"):
            obj.addProperty("App::PropertyLink", "Source", "Silhouette", "The part whose face it outlines")
        if not hasattr(obj, "Face"):
            obj.addProperty("App::PropertyInteger", "Face", "Silhouette", "0-based face index")
        if not hasattr(obj, "Side"):
            obj.addProperty("App::PropertyInteger", "Side", "Silhouette", "Which of the two outlines")
        if not hasattr(obj, "Direction"):
            obj.addProperty("App::PropertyVector", "Direction", "Silhouette", "Seen along (sketch normal)")
        if not hasattr(obj, MARK):
            obj.addProperty("App::PropertyBool", MARK, "Silhouette", "FreeCAD silhouette edge")
            setattr(obj, MARK, True)
            obj.setEditorMode(MARK, 2)

    def onDocumentRestored(self, obj):
        self._props(obj)

    def execute(self, obj):
        import Part
        src = obj.Source
        edge = None
        try:
            face = src.Shape.Faces[obj.Face]
            edge = outline(face, type(face.Surface).__name__, obj.Side, obj.Direction)
        except Exception:
            edge = None
        if edge is None:

            if obj.Shape.isNull():
                obj.Shape = Part.Shape()
            return
        obj.Shape = edge

    def dumps(self):
        return None

    def loads(self, state):
        return None


def number_of(obj):
    """n of 'Silhouette Edge<n>' (the order they were made in the document)."""
    rows = [o for o in obj.Document.Objects if getattr(o, MARK, False)]
    try:
        return rows.index(obj) + 1
    except ValueError:
        return 1


def is_silhouette(obj):
    return bool(obj is not None and getattr(obj, MARK, False))


def name_of(obj):
    ""
    src = getattr(obj, "Source", None)
    return "%s<%d>@%s" % (LABEL, number_of(obj), src.Label if src is not None else obj.Label)


def make(sketch, source, face, side):
    """The silhouette object for that outline (the same one again when it exists)."""
    doc = sketch.Document
    normal = _sketch_normal(sketch)
    for o in doc.Objects:
        if getattr(o, MARK, False) and o.Source == source and o.Face == face and o.Side == side \
                and (o.Direction - normal).Length < 1e-9:
            return o
    obj = doc.addObject("Part::FeaturePython", "SilhouetteEdge")
    SilhouetteFeature(obj)
    obj.Source, obj.Face, obj.Side, obj.Direction = source, face, side, normal
    obj.Label = "%s%d" % (LABEL.replace(" ", ""), number_of(obj))
    if App.GuiUp:
        try:
            vo = obj.ViewObject
            vo.Visibility = False
            vo.ShowInTree = False
            if vo.Proxy is None:
                vo.Proxy = 0
        except Exception as _fw_err:
            _fw_log("fwsketch/silhouette.py:529", _fw_err)
    obj.recompute()
    return obj


def prune(doc):
    """Removes outlines nothing refers to (a pick that was not used). Returns how many."""
    gone = 0
    for o in list(doc.Objects):
        if getattr(o, MARK, False) and not [x for x in o.InList if x is not o]:
            try:
                doc.removeObject(o.Name)
                gone += 1
            except Exception as _fw_err:
                _fw_log("fwsketch/silhouette.py:543", _fw_err)
    return gone
