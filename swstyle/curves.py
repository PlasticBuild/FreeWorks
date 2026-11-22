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
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from . import pmboxes

from .widgets import ui_font


def _add_feature(name, proxy_cls, label):
    doc = App.ActiveDocument
    obj = doc.addObject("Part::FeaturePython", name)
    proxy_cls(obj)
    if App.GuiUp:
        _CurveView(obj.ViewObject)
    obj.Label = label
    # a PartDesign Body only takes PartDesign features, so the curve sits next to the body in the
    # tree (it still follows the edges and points it was made from)
    return obj


def assembly_of(doc):
    """The assembly reference geometry is made in: the active one, else the document's only assembly (None in a part)."""
    asms = [o for o in doc.Objects if o.TypeId == "Assembly::AssemblyObject"]
    if not asms:
        return None
    try:
        active = Gui.ActiveDocument.ActiveView.getActiveObject("part") if App.GuiUp and Gui.ActiveDocument else None
    except Exception:
        active = None
    if active in asms:
        return active
    return asms[0] if len(asms) == 1 else None


def _put_in_assembly(obj):
    ""
    asm = assembly_of(obj.Document)
    if asm is not None and obj not in asm.Group:
        try:
            asm.addObject(obj)
        except Exception as _fw_err:
            _fw_log("curves.py:put_in_assembly", _fw_err)
    return asm


def assembly_components(asm, hidden=True):
    """The assembly's components with a solid (shown ones only unless hidden), for its Center of Mass and box."""
    try:
        from . import asmcore
        comps = asmcore.components(asm)
    except Exception as _fw_err:
        _fw_log("curves.py:components", _fw_err)
        return []
    out = []
    for c in comps:
        vo = getattr(c, "ViewObject", None)
        if not hidden and vo is not None and not vo.Visibility:
            continue
        if _solids(c):
            out.append(c)
    return out


def _solids(obj):
    """obj's solids where they sit (a component's link placed in the assembly)."""
    try:
        shape = obj.Shape
    except Exception:
        shape = None
    if shape is None or shape.isNull():
        try:
            import Part
            shape = Part.getShape(obj)
        except Exception:
            return []
    return list(shape.Solids) if shape is not None and not shape.isNull() else []


def _element(shape, sub):
    ""

    try:
        return shape.getElement(sub)
    except Exception:
        return shape.getElement(sub.split(".")[-1].lstrip("?"))


class _Base:
    def __init__(self, obj):
        obj.Proxy = self
        if "SWCurve" not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", "SWCurve", "Base", "A FreeCAD curve")
            obj.setEditorMode("SWCurve", 2)
        obj.SWCurve = True

    def dumps(self):
        return None

    def loads(self, state):
        return None


class CompositeCurve(_Base):
    """Insert > Curve > Composite: joins picked edges and sketch curves into one curve."""

    def __init__(self, obj):
        super().__init__(obj)
        obj.addProperty("App::PropertyLinkSubList", "Entities", "Composite Curve", "Edges to join")

    def execute(self, obj):
        import Part
        edges = []
        for link, subs in obj.Entities:
            shape = link.Shape
            if not subs or subs == ("",):
                edges += shape.Edges
            for sub in subs:
                if sub.startswith("Edge"):
                    edges.append(_element(shape, sub))
        if not edges:
            obj.Shape = Part.Shape()
            return
        try:
            wires = [Part.Wire(group) for group in Part.sortEdges(edges)]
        except Exception:
            wires = [Part.Wire(edges)]
        obj.Shape = wires[0] if len(wires) == 1 else Part.Compound(wires)


class CurveThroughPoints(_Base):
    """Insert > Curve > Curve Through XYZ Points (a table of points) and Curve Through Reference
    Points (picked vertices and points, kept as links)."""

    def __init__(self, obj):
        super().__init__(obj)
        obj.addProperty("App::PropertyVectorList", "Points", "Curve", "Points in order (XYZ table)")
        obj.addProperty("App::PropertyLinkSubList", "References", "Curve", "Picked points, used instead of the table")
        obj.addProperty("App::PropertyBool", "Closed", "Curve", "Closed curve")

    def execute(self, obj):
        import Part
        pts = []
        if not obj.References and getattr(obj, "CoordSystem", None) is not None:

            try:
                frame = obj.CoordSystem.getGlobalPlacement()
            except Exception:
                frame = obj.CoordSystem.Placement
            body = obj.getParentGeoFeatureGroup()
            if body is not None:
                frame = body.getGlobalPlacement().inverse().multiply(frame)
            pts = [frame.multVec(p) for p in obj.Points]
        elif obj.References:
            for link, subs in obj.References:
                shape = link.Shape
                if not subs or subs == ("",):
                    if shape.Vertexes:
                        pts.append(shape.Vertexes[0].Point)
                    continue
                for sub in subs:
                    el = _element(shape, sub)
                    if sub.split(".")[-1].lstrip("?").startswith("Vertex"):
                        pts.append(el.Point)
                    elif el.Vertexes:
                        pts.append(el.Vertexes[0].Point)
        if not pts and not obj.References:
            pts = list(obj.Points)
        if len(pts) < 2:
            obj.Shape = Part.Shape()
            return
        if len(pts) == 2:
            obj.Shape = Part.LineSegment(pts[0], pts[1]).toShape()
            return
        curve = Part.BSplineCurve()
        curve.interpolate(pts, PeriodicFlag=bool(obj.Closed))
        obj.Shape = curve.toShape()


def offset_on_face(face, edges, distance, reverse=False, euclidean=False):
    ""



    import Part
    if distance <= 0 or not edges:
        return Part.Shape()
    wire = None
    if face.Surface.__class__.__name__ == "Plane":
        try:
            wire = Part.Wire(Part.__sortEdges__(edges))
        except Exception:
            wire = None
    # a closed loop on a plane gets the exact 2D offset; an open chain has no plane of its own
    # for makeOffset2D (a single line), so it is walked like a curved face, which is exact there
    if wire is not None and wire.isClosed():
        best = None
        for d in (distance, -distance):
            try:
                off = wire.makeOffset2D(d, 0, False, False, False)
            except Exception:
                continue
            mid = off.Edges[0].valueAt(off.Edges[0].FirstParameter + 0.5 * (off.Edges[0].LastParameter - off.Edges[0].FirstParameter))
            inside = face.isInside(mid, 1e-6, True)
            if inside != reverse:
                best = off
                break
            best = best or off
        return best if best is not None else Part.Shape()
    out = [_march(face, e, distance, reverse, euclidean=euclidean) for e in edges]
    out = [e for e in out if e is not None]
    return Part.Compound(out) if out else Part.Shape()


def _march(face, edge, distance, reverse, steps=24, euclidean=False):
    """One edge walked across a curved face: each sample point steps square to the edge in the
    face's tangent plane and is pulled back onto the surface after every step. Euclidean walks on
    until the straight distance from the edge point reaches the offset."""
    import Part
    surf = face.Surface
    n = max(16, min(120, int(edge.Length / max(distance, 1e-3) * 4)))
    a, b = edge.FirstParameter, edge.LastParameter
    closed = edge.isClosed()
    count = n if closed else n + 1
    pts = []
    side = None
    for i in range(count):
        t = a + (b - a) * i / n
        p = start = edge.valueAt(t)
        tan = edge.tangentAt(t)
        h = distance / steps
        prev = None
        k = 0
        while True:
            u, v = surf.parameter(p)
            nrm = face.normalAt(u, v)
            d = nrm.cross(tan)
            if d.Length < 1e-12:
                return None
            d.normalize()
            if prev is not None:
                if d.dot(prev) < 0:
                    d = d * -1
            else:
                if side is None:
                    test = p + d * min(h, distance * 0.01)
                    uu, vv = surf.parameter(test)
                    inside = face.isInside(surf.value(uu, vv), 1e-6, True)
                    side = 1 if inside != reverse else -1
                d = d * side
            q = p + d * h
            uu, vv = surf.parameter(q)
            q = surf.value(uu, vv)
            k += 1
            if euclidean:
                reach = (q - start).Length
                if reach >= distance or k > steps * 8:
                    before = (p - start).Length
                    f = (distance - before) / (reach - before) if reach - before > 1e-12 else 1.0
                    m = p + (q - p) * f
                    uu, vv = surf.parameter(m)
                    p = surf.value(uu, vv)
                    break
            p = q
            prev = d
            if not euclidean and k >= steps:
                break
        pts.append(p)
    try:
        bs = Part.BSplineCurve()
        bs.interpolate(pts, PeriodicFlag=closed)
        return bs.toShape()
    except Exception:
        return None


OFFSET_MODES = ("Euclidean", "Geodesic")


def offset_groups(sources, reverse):
    """[(face, edges, reverse)] from picked faces and edges: a face offsets all its edges into it (out of it
    when reverse); an edge goes onto the picked face it bounds, else onto its first face (its other face
    when reverse)."""
    import Part
    out = []
    for link, subs in sources:
        shape = link.Shape
        names = [s for s in subs if s]
        faces = [s for s in names if s.split(".")[-1].lstrip("?").startswith("Face")]
        picked_faces = []
        for name in faces:
            f = _element(shape, name)
            picked_faces.append(f)
            out.append((f, f.Edges, reverse))
        for name in names:
            if not name.split(".")[-1].lstrip("?").startswith("Edge"):
                continue
            e = _element(shape, name)
            home = next((f for f in picked_faces if any(e.isSame(x) for x in f.Edges)), None)
            if home is not None:
                continue            # the face's own offset has it
            try:
                around = shape.ancestorsOfType(e, Part.Face)
            except Exception:
                around = []
            if not around:
                continue
            if reverse and len(around) > 1:
                out.append((around[1], [e], False))
            else:
                out.append((around[0], [e], reverse and len(around) == 1))
    return out


class OffsetOnSurface(_Base):
    ""


    def __init__(self, obj):
        super().__init__(obj)
        obj.addProperty("App::PropertyLinkSub", "Face", "Offset On Surface", "The face the offset stays on (older files)")
        obj.addProperty("App::PropertyStringList", "EdgeNames", "Offset On Surface", "Edges of the same object (older files)")
        obj.addProperty("App::PropertyLength", "Distance", "Offset On Surface", "Offset distance")
        obj.addProperty("App::PropertyBool", "Reverse", "Offset On Surface", "Reverse direction")
        obj.Distance = 5.0
        self.upgrade(obj)

    def upgrade(self, obj):
        if "Sources" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLinkSubList", "Sources", "Offset On Surface", "Edges and faces to offset")
        if "Mode" not in obj.PropertiesList:
            obj.addProperty("App::PropertyEnumeration", "Mode", "Offset On Surface",
                            "Euclidean: straight distance; Geodesic: along the surface")
            obj.Mode = list(OFFSET_MODES)
        for name in ("Face", "EdgeNames"):
            if name in obj.PropertiesList:
                obj.setEditorMode(name, 2)

    def onDocumentRestored(self, obj):
        self.upgrade(obj)

    def execute(self, obj):
        import Part
        d = obj.Distance.Value
        sources = list(getattr(obj, "Sources", []) or [])
        euclidean = getattr(obj, "Mode", "Geodesic") == "Euclidean"
        groups = offset_groups(sources, bool(obj.Reverse))
        if not sources and obj.Face is not None and obj.Face[1]:
            src, subs = obj.Face          # made before Sources: one face, its picked or outer edges
            face = _element(src.Shape, subs[0])
            edges = [_element(src.Shape, e) for e in obj.EdgeNames] or face.OuterWire.Edges
            groups = [(face, edges, bool(obj.Reverse))]
        shapes = []
        for face, edges, rev in groups:
            try:
                sh = offset_on_face(face, edges, d, rev, euclidean)
            except Exception:
                continue
            if not sh.isNull():
                shapes.append(sh)
        if not shapes:
            obj.Shape = Part.Shape()
        else:
            obj.Shape = shapes[0] if len(shapes) == 1 else Part.Compound(shapes)


class CenterOfMass(_Base):
    """Insert > Reference Geometry > Center of Mass: a point at the part's centre of mass that
    follows the part."""

    def __init__(self, obj):
        super().__init__(obj)
        obj.SWCurve = False
        obj.addProperty("App::PropertyLinkList", "Bodies", "Center of Mass", "Bodies measured; empty = every visible body")

    def execute(self, obj):
        import Part
        bodies = list(obj.Bodies)
        asm = assembly_of(obj.Document)
        if asm is not None and obj in asm.Group:

            bodies = bodies + [c for c in assembly_components(asm, hidden=False) if c not in bodies]
            bodies = [b for b in bodies if getattr(getattr(b, "ViewObject", None), "Visibility", True)]
        if not bodies:
            from .evaluate import visible_bodies
            bodies = [b for b in visible_bodies(obj.Document) if b != obj]

        # density (it sat at the volume centre), and a part's Override Mass Properties centre of mass moves it
        own = {}
        try:
            from . import massprops
            for b in bodies:
                own[b.Name] = massprops.body_material(b)[1]
            if asm is None or obj not in asm.Group:
                over = massprops.overrides(obj.Document).get("center")
                if over:
                    obj.Shape = Part.Vertex(App.Vector(*[float(x) for x in over]))
                    return
        except Exception as _fw_err:
            _fw_log("curves.py:com-mass", _fw_err)
        part = 1.0
        if any(own.values()):
            try:
                from . import material
                part = float(material.density(obj.Document) or 1000.0)
            except Exception:
                part = 1000.0
        total, c = 0.0, App.Vector()
        for b in bodies:
            weight = own.get(b.Name) or part
            for s in _solids(b):
                total += s.Volume * weight
                c += s.CenterOfMass * (s.Volume * weight)
        if total <= 0:
            obj.Shape = Part.Shape()
            return
        obj.Shape = Part.Vertex(c * (1.0 / total))


BOX_REFERENCES = ["Best Fit", "Custom Plane", "Coordinate System"]


def ensure_box_props(obj, new=False):
    ""
    add = obj.addProperty
    have = obj.PropertiesList
    if "Reference" not in have:
        add("App::PropertyEnumeration", "Reference", "Bounding Box", "Best Fit, Custom Plane or Coordinate System")
        obj.Reference = BOX_REFERENCES
    elif list(obj.getEnumerationsOfProperty("Reference")) != BOX_REFERENCES:
        was = obj.Reference
        obj.Reference = BOX_REFERENCES
        obj.Reference = was
    if "CoordSystem" not in have:
        add("App::PropertyLinkGlobal", "CoordSystem", "Bounding Box", "The coordinate system whose axes the box follows")
    if "FixDirections" not in have:

        # on, each stays on its axis (X, Y, Z). Boxes from before keep their axes.
        add("App::PropertyBool", "FixDirections", "Bounding Box", "Length, Width, Thickness stay on X, Y, Z")
        obj.FixDirections = not new
    if "Plane" not in have:
        add("App::PropertyLinkSubGlobal", "Plane", "Bounding Box", "The plane or flat face the box sits on (Custom Plane)")
    if "IncludeHidden" not in have:
        add("App::PropertyBool", "IncludeHidden", "Bounding Box", "Include hidden bodies")
    if "IncludeSurfaces" not in have:
        add("App::PropertyBool", "IncludeSurfaces", "Bounding Box", "Include surfaces")
    if "BoxType" not in have:
        add("App::PropertyEnumeration", "BoxType", "Bounding Box", "Rectangular box or cylinder round the part")
        obj.BoxType = BOX_TYPES
    for name, tip in (("CylinderDiameter", "Cylindrical: diameter"), ("CylinderLength", "Cylindrical: length along its axis")):
        if name not in have:
            add("App::PropertyLength", name, "Bounding Box", tip)
            obj.setEditorMode(name, 1)


BOX_TYPES = ["Rectangular", "Cylindrical"]


def _cloud(shapes):
    """Points on the shapes for the enclosing cylinder: vertices and points along every edge."""
    pts = []
    for s in shapes:
        size = max(s.BoundBox.DiagonalLength, 1e-6)
        pts += [v.Point for v in s.Vertexes]
        for e in s.Edges:
            try:
                pts += e.discretize(Deflection=size * 2e-4)
            except Exception as _fw_err:
                _fw_log("curves.py:405", _fw_err)
    return pts


def _circle_of(pts):
    """The smallest circle round 2D points [(x, y)] (Welzl, iterative): (cx, cy, r)."""
    import random
    p = list(pts)
    random.Random(7).shuffle(p)

    def two(a, b):
        cx, cy = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        return cx, cy, math.hypot(a[0] - cx, a[1] - cy)

    def three(a, b, c):
        ax, ay, bx, by, cx, cy = a[0], a[1], b[0], b[1], c[0], c[1]
        d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if abs(d) < 1e-14:
            pairs = [two(a, b), two(a, c), two(b, c)]
            return max(pairs, key=lambda t: t[2])
        ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
        uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
        return ux, uy, math.hypot(ax - ux, ay - uy)

    def inside(c, q):
        return math.hypot(q[0] - c[0], q[1] - c[1]) <= c[2] * (1 + 1e-12) + 1e-9
    c = None
    for i, a in enumerate(p):
        if c is None or not inside(c, a):
            c = (a[0], a[1], 0.0)
            for j in range(i):
                b = p[j]
                if not inside(c, b):
                    c = two(a, b)
                    for k in range(j):
                        if not inside(c, p[k]):
                            c = three(a, b, p[k])
    return c or (0.0, 0.0, 0.0)


def enclosing_cylinder(shapes, frames, axes=(0, 1, 2)):
    ""

    pts = _cloud(shapes)
    if not pts:
        return None
    best = None
    for frame in frames:
        rot = frame.Rotation
        for k in axes:
            z = rot.multVec((App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1))[k])
            x = rot.multVec((App.Vector(0, 1, 0), App.Vector(0, 0, 1), App.Vector(1, 0, 0))[k])
            y = z.cross(x)
            o = frame.Base
            flat = [((q - o).dot(x), (q - o).dot(y)) for q in pts]
            hs = [(q - o).dot(z) for q in pts]
            cx, cy, r = _circle_of(flat)
            lo, hi = min(hs), max(hs)
            vol = math.pi * r * r * (hi - lo)
            if best is None or vol < best[0] - 1e-6:
                best = (vol, o + x * cx + y * cy + z * lo, z, r, hi - lo)
    return best


def _looks_at(p):
    """Reference geometry and curves (a Center of Mass point, another box, a curve) only look at a body: it is still
    the part's body to box (a Center of Mass made the box find no body)."""
    return "SWCurve" in getattr(p, "PropertiesList", ()) or type(getattr(p, "Proxy", None)).__name__ in \
        ("CenterOfMass", "BoundingBox")


def box_candidates(obj):
    """Every body the box may take in (before the hidden-bodies and surfaces options)."""
    doc = obj.Document
    picked = list(obj.Bodies)
    if picked:
        return picked
    asm = assembly_of(doc)
    if asm is not None and obj in asm.Group:
        return assembly_components(asm)          # an assembly's box: round its components
    return [o for o in doc.Objects if o is not obj and getattr(o, "Shape", None) is not None
                 and not getattr(o, "SWCurve", False) and type(getattr(o, "Proxy", None)).__name__ not in
                 ("BoundingBox", "CenterOfMass")
                 and not any(p.isDerivedFrom("PartDesign::Body") or p.isDerivedFrom("Part::Feature") and p is not obj
                             and not _looks_at(p) and o in getattr(p, "OutList", []) for p in o.InList)
                 and not o.isDerivedFrom("Sketcher::SketchObject")
                 and not o.TypeId.startswith(("PartDesign::Plane", "PartDesign::Line", "PartDesign::Point",
                                              "PartDesign::CoordinateSystem", "App::", "Part::Datum"))]


def watch_bodies(obj):
    ""

    if "Watched" not in obj.PropertiesList:
        obj.addProperty("App::PropertyLinkList", "Watched", "Bounding Box", "Bodies the box follows")
        obj.setEditorMode("Watched", 2)
    try:
        cands = [o for o in box_candidates(obj) if obj not in o.OutListRecursive]
    except Exception:
        cands = []
    if list(obj.Watched) != cands:
        obj.Watched = cands


def _box_shapes(obj):
    """The shapes boxed: the picked bodies, or every body of the part; hidden ones and surfaces
    only when the options say so."""
    picked = list(obj.Bodies)
    cands = box_candidates(obj)
    out = []
    hidden_ok = getattr(obj, "IncludeHidden", False)
    surf_ok = getattr(obj, "IncludeSurfaces", False)
    for b in cands:
        vo = getattr(b, "ViewObject", None)
        if not picked and not hidden_ok and vo is not None and not vo.Visibility:
            continue
        try:
            shape = b.Shape
        except Exception:
            shape = None
        if shape is None or shape.isNull():
            import Part
            try:
                shape = Part.getShape(b)
            except Exception:
                continue
            if shape.isNull():
                continue
        out += list(shape.Solids)
        if surf_ok:
            out += [sh for sh in shape.Shells if not any(sh.isSame(x) for so in shape.Solids for x in so.Shells)]
            if not shape.Solids and not shape.Shells:
                out += list(shape.Faces)
    return out


def _plane_frame(link):
    """The Custom Plane's frame: its normal as Z."""
    import Part
    obj, subs = link
    if subs and subs[0]:
        face = obj.Shape.getElement(subs[0])
        n = face.normalAt(*face.Surface.parameter(face.CenterOfMass)) if hasattr(face, "Surface") else App.Vector(0, 0, 1)
        return App.Placement(face.CenterOfMass, App.Rotation(App.Vector(0, 0, 1), n))
    try:
        return obj.getGlobalPlacement()
    except Exception:
        return obj.Placement


def _box_in(shapes, frame):
    import Part
    inv = frame.inverse().toMatrix()
    box = None
    for s in shapes:
        c = s.copy()
        c.transformShape(inv)
        bb = c.optimalBoundingBox() if hasattr(c, "optimalBoundingBox") else c.BoundBox
        if box is None:
            box = bb
        else:
            box.add(bb)
    return box


def _best_frames(shapes):
    """The frames tried for Best Fit: the part's axes, then the main body's principal axes."""
    out = [App.Placement()]
    solids = [s for s in shapes if s.ShapeType == "Solid"]
    if solids:
        big = max(solids, key=lambda s: s.Volume)
        try:
            pp = big.PrincipalProperties
            x, y = App.Vector(pp["FirstAxis"]), App.Vector(pp["SecondAxis"])
            z = x.cross(y)
            if z.Length > 1e-9:
                m = App.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0)
                out.append(App.Placement(App.Vector(), App.Rotation(m)))
        except Exception as _fw_err:
            _fw_log("curves.py:546", _fw_err)
        # the part's biggest flat faces: the box standing on each, turned to each of its straight edges
        # (a part rotated or with a slanted base boxes tight on it, not only on the axes it was drawn on)
        flats = [f for f in big.Faces if type(f.Surface).__name__ == "Plane"]
        for f in sorted(flats, key=lambda f: -f.Area)[:3]:
            try:
                n = App.Vector(f.normalAt(*f.Surface.parameter(f.CenterOfMass)))
                dirs = [App.Vector(e.Curve.Direction) for e in f.Edges if type(e.Curve).__name__ in ("Line", "LineSegment")]
                for x in (dirs[:4] or [n.cross(App.Vector(1, 0, 0)) if abs(n.x) < 0.9 else n.cross(App.Vector(0, 1, 0))]):
                    x = x - n * x.dot(n)
                    if x.Length < 1e-9:
                        continue
                    x.normalize()
                    y = n.cross(x)
                    m = App.Matrix(x.x, y.x, n.x, 0, x.y, y.y, n.y, 0, x.z, y.z, n.z, 0)
                    out.append(App.Placement(App.Vector(), App.Rotation(m)))
            except Exception as _fw_err:
                _fw_log("curves.py:best_faces", _fw_err)
    return out


class BoundingBox(_Base):
    ""




    def __init__(self, obj):
        super().__init__(obj)
        obj.SWCurve = False
        obj.addProperty("App::PropertyLinkList", "Bodies", "Bounding Box", "Bodies boxed; empty = every body")
        obj.addProperty("App::PropertyLength", "BoxLength", "Bounding Box", "Size along X")
        obj.addProperty("App::PropertyLength", "BoxWidth", "Bounding Box", "Size along Y")
        obj.addProperty("App::PropertyLength", "BoxHeight", "Bounding Box", "Size along Z")
        obj.addProperty("App::PropertyFloat", "BoxVolume", "Bounding Box", "Box volume in mm^3")
        for name in ("BoxLength", "BoxWidth", "BoxHeight", "BoxVolume"):
            obj.setEditorMode(name, 1)
        ensure_box_props(obj, new=True)

    def onDocumentRestored(self, obj):
        ensure_box_props(obj)

    def execute(self, obj):
        import Part
        shapes = _box_shapes(obj)
        if not shapes:
            obj.Shape = Part.Shape()
            return
        custom = getattr(obj, "Reference", "Best Fit") == "Custom Plane" and getattr(obj, "Plane", None)
        csys = getattr(obj, "Reference", "Best Fit") == "Coordinate System" and getattr(obj, "CoordSystem", None)
        if csys:
            try:
                frames = [obj.CoordSystem.getGlobalPlacement()]
            except Exception:
                frames = [obj.CoordSystem.Placement]
            custom = True       # a cylinder stands on its XY plane, as on a Custom Plane
        elif custom:
            frames = [_plane_frame(obj.Plane)]
        else:
            frames = _best_frames(shapes)
        if getattr(obj, "BoxType", "Rectangular") == "Cylindrical":
            self._cylinder(obj, shapes, frames, bool(custom))
            return
        best = None
        for frame in frames:
            box = _box_in(shapes, frame)
            if box is None or not box.isValid():
                continue
            vol = box.XLength * box.YLength * box.ZLength
            if best is None or vol < best[0] - 1e-6:
                best = (vol, box, frame)
        if best is None:
            obj.Shape = Part.Shape()
            return
        vol, box, frame = best
        sizes = [box.XLength, box.YLength, box.ZLength]
        if not getattr(obj, "FixDirections", True):
            sizes.sort(reverse=True)
        obj.BoxLength, obj.BoxWidth, obj.BoxHeight = sizes
        obj.BoxVolume = vol
        edges = []
        p = [frame.multVec(App.Vector(x, y, z)) for z in (box.ZMin, box.ZMax) for y in (box.YMin, box.YMax)
             for x in (box.XMin, box.XMax)]
        for a, b in ((0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)):
            if p[a].distanceToPoint(p[b]) > 1e-9:
                edges.append(Part.LineSegment(p[a], p[b]).toShape())
        obj.Shape = Part.Compound(edges)

    def _cylinder(self, obj, shapes, frames, custom):
        """The cylinder round the part: its two end circles and four lines along it. With Custom
        Plane its axis is the plane's normal (it stands on the plane)."""
        import Part
        found = enclosing_cylinder(shapes, frames, (2,) if custom else (0, 1, 2))
        if found is None or found[3] <= 0:
            obj.Shape = Part.Shape()
            return
        vol, base, axis, r, length = found
        obj.CylinderDiameter, obj.CylinderLength = 2 * r, length
        obj.BoxLength, obj.BoxWidth, obj.BoxHeight = 2 * r, 2 * r, length
        obj.BoxVolume = vol
        top = base + axis * length
        ref = App.Vector(1, 0, 0) if abs(axis.x) < 0.9 else App.Vector(0, 1, 0)
        u = axis.cross(ref)
        u.normalize()
        v = axis.cross(u)
        edges = [Part.Circle(base, axis, r).toShape(), Part.Circle(top, axis, r).toShape()]
        if length > 1e-9:
            for d in (u, v, u * -1, v * -1):
                edges.append(Part.LineSegment(base + d * r, top + d * r).toShape())
        obj.Shape = Part.Compound(edges)


# PropertyManagers that edit a curve again (Edit Feature / double-click): Proxy class name -> f(obj)
EDITORS = {}


class _CurveView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        try:
            vobj.LineWidth = 2.0
            vobj.PointSize = 8.0
            vobj.LineColor = (0.55, 0.1, 0.65)
            vobj.PointColor = (0.55, 0.1, 0.65)
        except Exception as _fw_err:
            _fw_log("curves.py:657", _fw_err)

    def getIcon(self):
        if type(getattr(self.Object, "Proxy", None)).__name__ == "OffsetOnSurface":
            return ":/icons/Sketcher_Sketch.svg"
        return ""

    def setEdit(self, vobj, mode=0):
        kind = type(getattr(vobj.Object, "Proxy", None)).__name__
        if mode == 0 and kind in EDITORS:
            QtCore.QTimer.singleShot(0, lambda o=vobj.Object: EDITORS[kind](o))
            return False
        if mode != 0 or kind != "OffsetOnSurface":
            return None
        obj = vobj.Object
        obj.Proxy.upgrade(obj)
        obj.Document.openTransaction("Edit Offset On Surface")
        try:
            Gui.Control.showDialog(OffsetPanel(obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        kind = type(getattr(vobj.Object, "Proxy", None)).__name__
        if kind in EDITORS:
            EDITORS[kind](vobj.Object)
            return True
        if kind != "OffsetOnSurface":
            return False
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


# ------------------------------------------------------------------ commands
def _picked_edges():
    out = []
    for sel in Gui.Selection.getSelectionEx():
        subs = tuple(s for s in sel.SubElementNames if s.startswith("Edge"))
        if subs:
            out.append((sel.Object, subs))
        elif sel.Object.isDerivedFrom("Sketcher::SketchObject"):
            out.append((sel.Object, ("",)))
    return out


def _picked_points():
    out = []
    for sel in Gui.Selection.getSelectionEx():
        subs = tuple(s for s in sel.SubElementNames if s.startswith("Vertex"))
        if subs:
            out.append((sel.Object, subs))
        elif sel.Object.TypeId in ("PartDesign::Point", "Part::Vertex") or sel.Object.isDerivedFrom("App::Point"):
            out.append((sel.Object, ("",)))
    return out


def composite_curve(confirmed=False):
    """Insert > Curve > Composite: its PropertyManager (Entities to Join), picks made first or not.
    Without the GUI page, picks made first still wait for OK (commands pkg189)."""
    if App.GuiUp and App.ActiveDocument is not None:
        try:
            from . import curvepms
            return curvepms.composite_curve()
        except ImportError:
            pass
    edges = _picked_edges()
    if not edges or not confirmed:
        from . import pickfirst
        return pickfirst.ask("Composite Curve", "Entities to Join", ("Edge", "Sketch"),
                             lambda: composite_curve(True))
    doc = App.ActiveDocument
    doc.openTransaction("Composite Curve")
    try:
        obj = _add_feature("CompositeCurve", CompositeCurve, "Composite Curve")
        obj.Entities = edges
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return obj


def curve_through_reference_points():
    """Its PropertyManager: Through Points (in order) and Closed curve."""
    if App.GuiUp and App.ActiveDocument is not None:
        try:
            from . import curvepms
            return curvepms.curve_through_reference_points()
        except ImportError:
            pass
    pts = _picked_points()
    if sum(len(s) for _, s in pts) < 2:
        from . import pickfirst
        point = lambda o, sub: (not sub and (o.TypeId in ("PartDesign::Point", "Part::Vertex")
                                             or o.isDerivedFrom("App::Point")))
        return pickfirst.ask("Curve Through Reference Points", "Through Points (in order)", ("Vertex", point),
                             curve_through_reference_points, minimum=2)
    doc = App.ActiveDocument
    doc.openTransaction("Curve Through Reference Points")
    try:
        obj = _add_feature("CurveThroughPoints", CurveThroughPoints, "Curve")
        obj.References = pts
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return obj


_UNITS = {"": 1.0, "mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "\"": 25.4, "ft": 304.8, "'": 304.8,
          "um": 0.001}


def doc_unit(doc=None):
    ""

    try:
        from . import unitspage
        sym, mm = unitspage.length_unit(doc or App.ActiveDocument)
        return sym, float(mm)
    except Exception as _fw_err:
        _fw_log("curves.py:doc_unit", _fw_err)
        return "mm", 1.0


def _length(text):
    ""

    import re
    m = re.match(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-zA-Z\"']*)\s*$", text)
    if m is None or m.group(2).lower() not in _UNITS:
        return None
    unit = m.group(2).lower()
    return float(m.group(1)) * (doc_unit()[1] if unit == "" else _UNITS[unit])


def cell_text(v):
    """A coordinate in mm as the points table shows it: in the part's unit."""
    return "%g" % round(v / doc_unit()[1], 10)


def read_points_file(path):
    ""
    pts = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.replace(",", " ").replace(";", " ").split()
            nums = []
            for p in parts[:3]:
                value = _length(p)
                if value is None:
                    break
                nums.append(value)
            if len(nums) == 3:
                pts.append(App.Vector(*nums))
    return pts


class XYZDialog(QtWidgets.QDialog):
    """The Curve File dialog: a Point / X / Y / Z table, Browse, Save, Insert, OK, Cancel."""

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle("Curve File")
        self.setFont(ui_font())
        self.resize(420, 380)
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(4, 3)
        self.table.setHorizontalHeaderLabels(["X", "Y", "Z"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        self.path = ""
        browse = QtWidgets.QPushButton("Browse...")
        browse.setObjectName("SWCurveFileBrowse")
        browse.clicked.connect(self.browse)
        save = QtWidgets.QPushButton("Save")
        save.setObjectName("SWCurveFileSave")
        save.clicked.connect(lambda: self.save(False))
        save_as = QtWidgets.QPushButton("Save As...")
        save_as.setObjectName("SWCurveFileSaveAs")
        save_as.clicked.connect(lambda: self.save(True))
        add = QtWidgets.QPushButton("Insert")
        add.setObjectName("SWCurveFileInsert")
        add.clicked.connect(lambda: self.table.insertRow(max(0, self.table.currentRow() + 1)))
        self.closed = QtWidgets.QCheckBox("Closed curve")
        row.addWidget(browse)
        row.addWidget(save)
        row.addWidget(save_as)
        row.addWidget(add)
        row.addWidget(self.closed)
        row.addStretch(1)
        lay.addLayout(row)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Curve file", "", "Curves (*.sldcrv *.txt *.csv);;All files (*)")
        if path:
            self.path = path
            self.set_points(read_points_file(path))

    def save(self, ask=False):
        ""

        path = self.path
        if ask or not path:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save curve file", path or "curve.sldcrv",
                                                            "Curves (*.sldcrv);;Text (*.txt);;All files (*)")
        if not path:
            return False
        write_points_file(path, self.points())
        self.path = path
        return True

    def set_points(self, pts):
        self.table.setRowCount(max(4, len(pts)))
        for i, p in enumerate(pts):
            for j, v in enumerate((p.x, p.y, p.z)):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(cell_text(v)))

    def points(self):
        out = []
        for i in range(self.table.rowCount()):
            vals = []
            for j in range(3):
                it = self.table.item(i, j)
                if it is None or not it.text().strip():
                    continue
                v = _length(it.text())          # the part's unit, or the unit typed after it
                if v is None:
                    _fw_log("curves.py:873", it.text())
                else:
                    vals.append(v)
            if len(vals) == 3:
                out.append(App.Vector(*vals))
        return out


def write_points_file(path, points):
    ""
    sym, mm = doc_unit()
    with open(path, "w", encoding="utf-8") as f:
        for p in points:
            f.write("\t".join("%g%s" % (round(v / mm, 10), sym) for v in (p.x, p.y, p.z)) + "\n")


def make_xyz_curve(points, closed=False):
    doc = App.ActiveDocument
    doc.openTransaction("Curve Through XYZ Points")
    try:
        obj = _add_feature("CurveThroughXYZ", CurveThroughPoints, "Curve")
        obj.Points = points
        obj.Closed = closed
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return obj


def ensure_xyz_props(obj):
    if "CoordSystem" not in obj.PropertiesList:
        obj.addProperty("App::PropertyLinkGlobal", "CoordSystem", "Curve", "The points' coordinate system (empty: the part's origin)")


def curve_through_xyz_points():
    if App.GuiUp:
        from . import curvepms
        return curvepms.curve_through_xyz_points()
    dlg = XYZDialog()
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return None
    pts = dlg.points()
    if len(pts) < 2:
        return None
    return make_xyz_curve(pts, dlg.closed.isChecked())


OFFSET_PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/OffsetOnSurface"
_OFFSET_PANEL = None


def _sub_kind(sub):
    return sub.split(".")[-1].lstrip("?").rstrip("0123456789")


class OffsetPanel:
    """The Offset On Surface PropertyManager: Parameters (Reverse, distance, Euclidean / Geodesic) and
    the edges and faces to offset. The box takes picks as soon as it opens (or the ones made before the
    command); a second click on an item takes it out. The offset shows as it will be made."""

    def __init__(self, obj, new):
        global _OFFSET_PANEL
        _OFFSET_PANEL = self
        self.obj, self.new, self.busy = obj, new, True
        self.saved = (list(obj.Sources), obj.Distance.Value, bool(obj.Reverse), obj.Mode)
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWOOSPanel")
        self.form.setWindowTitle("Offset On Surface")
        self.form.setProperty("swstyle_pm_title", "Offset On Surface")
        self.form.setProperty("swstyle_pm_icon", "SWStyle_OffsetOnSurface")
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        head = QtWidgets.QLabel("Parameters")
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        lay.addWidget(head)
        row = QtWidgets.QHBoxLayout()
        self.reverse = QtWidgets.QToolButton()
        self.reverse.setObjectName("SWOOSReverse")
        from . import pmvalues
        self.reverse.setIcon(pmvalues.reverse_icon())
        self.reverse.setToolTip("Reverse Direction")
        self.reverse.setCheckable(True)
        self.reverse.setChecked(bool(obj.Reverse))
        self.distance = QtWidgets.QDoubleSpinBox()
        self.distance.setObjectName("SWOOSDistance")
        self.distance.setRange(0.001, 1e6)
        self.distance.setDecimals(2)
        self.distance.setSuffix(" mm")
        self.distance.setValue(obj.Distance.Value)
        self.distance.setToolTip("Offset distance")
        row.addWidget(self.reverse)
        row.addWidget(self.distance, 1)
        lay.addLayout(row)
        modes = QtWidgets.QWidget()          # its own parent: these two are exclusive only with each other
        ml = QtWidgets.QHBoxLayout(modes)
        ml.setContentsMargins(0, 0, 0, 0)
        self.mode_buttons = {}
        for name, tip in zip(OFFSET_MODES, ("Euclidean offset: the straight distance from the edge",
                                            "Geodesic offset: the distance along the surface")):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWOOS" + name)
            b.setText(name)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setChecked(obj.Mode == name)
            b.clicked.connect(self._changed)
            self.mode_buttons[name] = b
            ml.addWidget(b)
        ml.addStretch(1)
        lay.addWidget(modes)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWOOSEntities")
        self.list.setToolTip("Edges and faces to offset: pick them in the graphics area")
        self.list.setMaximumHeight(110)
        pmboxes.mark(self.list, True)
        self.list.installEventFilter(self._keys())
        lay.addWidget(self.list)
        lay.addStretch(1)
        self.reverse.toggled.connect(self._changed)
        self.distance.valueChanged.connect(self._changed)
        self._colour(True)
        self.busy = False
        self._fill()
        Gui.Selection.addObserver(self)

    def _keys(self):
        panel = self

        class Keys(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if event.type() == QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Delete,
                                                                               QtCore.Qt.Key_Backspace):
                    panel.remove_current()
                    return True
                return False
        self._filter = Keys()
        return self._filter

    def _colour(self, preview):
        try:
            vo = self.obj.ViewObject
            vo.LineColor = vo.PointColor = (1.0, 0.85, 0.0) if preview else (0.55, 0.1, 0.65)
        except Exception as _fw_err:
            _fw_log("curves.py:1016", _fw_err)

    def items(self):
        return [(o, s) for o, subs in self.obj.Sources for s in (subs or [""]) if s]

    def _fill(self):
        self.list.clear()
        for o, sub in self.items():
            name = sub.split(".")[-1].lstrip("?")
            kind = _sub_kind(sub)
            self.list.addItem("%s<%s>@%s" % (kind, name[len(kind):], o.Label))

    def _changed(self, *_a):
        if self.busy:
            return
        o = self.obj
        o.Distance = self.distance.value()
        o.Reverse = self.reverse.isChecked()
        o.Mode = next((n for n, b in self.mode_buttons.items() if b.isChecked()), o.Mode)
        self._apply()

    def _apply(self):
        doc = self.obj.Document
        if doc.Recomputing:
            QtCore.QTimer.singleShot(50, self._apply)
            return
        self.obj.touch()
        doc.recompute()

    def toggle(self, obj, sub):
        items = self.items()
        if (obj, sub) in items:
            items.remove((obj, sub))
        else:
            items.append((obj, sub))
        grouped = {}
        for o, s in items:
            grouped.setdefault(o, []).append(s)
        self.obj.Sources = [(o, subs) for o, subs in grouped.items()]
        self._fill()
        self._apply()

    def remove_current(self):
        row = self.list.currentRow()
        items = self.items()
        if 0 <= row < len(items):
            self.toggle(*items[row])

    def addSelection(self, doc, name, sub, point):
        if not sub or _sub_kind(sub) not in ("Edge", "Face"):
            return
        QtCore.QTimer.singleShot(0, lambda: self.picked(doc, name, sub))

    def picked(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("curves.py:1073", _fw_err)
        obj = App.getDocument(doc_name).getObject(name)
        if obj is None or obj is self.obj:
            return
        self.toggle(obj, sub)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("curves.py:1086", _fw_err)
        self._colour(False)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("curves.py:1093", _fw_err)

    def accept(self):
        if self.obj.Shape.isNull() or not self.obj.Shape.Edges:
            return False
        App.ParamGet(OFFSET_PARAMS).SetFloat("Distance", self.obj.Distance.Value)
        App.ParamGet(OFFSET_PARAMS).SetString("Mode", self.obj.Mode)
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        self._close()
        doc.abortTransaction()
        try:
            App.closeActiveTransaction(True)
        except Exception as _fw_err:
            _fw_log("curves.py:1111", _fw_err)
        if not self.new and doc.getObject(self.obj.Name) is not None:
            # an edit puts its values back even when the undo step was already closed
            o = self.obj
            o.Sources, o.Distance, o.Reverse, o.Mode = self.saved
        doc.recompute()
        return True


def make_offset_on_surface(obj, face_name, edge_names=(), distance=5.0, reverse=False):
    doc = obj.Document
    doc.openTransaction("Offset On Surface")
    try:
        off = _new_offset(doc)
        off.Face = (obj, [face_name])       # a face and some of its edges: those edges on that face
        off.EdgeNames = list(edge_names)
        off.Distance = distance
        off.Reverse = reverse
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return off


def _new_offset(doc):
    from . import naming
    off = doc.addObject("Part::FeaturePython", "OffsetOnSurface")
    OffsetOnSurface(off)
    if App.GuiUp:
        _CurveView(off.ViewObject)
    off.Label = naming.next_label(doc, "3DSketch")
    p = App.ParamGet(OFFSET_PARAMS)
    off.Distance = p.GetFloat("Distance", 10.0)
    off.Mode = p.GetString("Mode", "Euclidean") if p.GetString("Mode", "Euclidean") in OFFSET_MODES else "Euclidean"
    return off


def offset_on_surface():
    ""

    doc = App.ActiveDocument
    if doc is None:
        return None
    picks = [(s.Object, n) for s in Gui.Selection.getSelectionEx() for n in s.SubElementNames
             if _sub_kind(n) in ("Edge", "Face")]
    doc.openTransaction("Offset On Surface")
    try:
        off = _new_offset(doc)
        panel = OffsetPanel(off, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    Gui.Selection.clearSelection()
    for o, n in picks:
        panel.toggle(o, n)
    return off


def center_of_mass():
    doc = App.ActiveDocument
    old = [o for o in doc.Objects if getattr(o, "Proxy", None).__class__.__name__ == "CenterOfMass"]
    if old:
        return old[0]
    doc.openTransaction("Center of Mass")
    try:
        obj = _add_feature("CenterOfMass", CenterOfMass, "Center of Mass")
        from .evaluate import visible_bodies
        # linked so the point follows the part when it changes (an assembly's: its components)
        asm = _put_in_assembly(obj)
        obj.Bodies = assembly_components(asm, hidden=False) if asm is not None else [b for b in visible_bodies(doc) if b != obj]
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return obj


def existing_bounding_box(doc):
    old = [o for o in doc.Objects if getattr(o, "Proxy", None).__class__.__name__ == "BoundingBox"]
    return old[0] if old else None


def new_bounding_box(doc):
    ""
    App.setActiveDocument(doc.Name)
    obj = _add_feature("BoundingBox", BoundingBox, "Bounding Box")
    _put_in_assembly(obj)
    watch_bodies(obj)
    doc.recompute()
    return obj


def bounding_box():
    ""

    doc = App.ActiveDocument
    if App.GuiUp:
        from . import refgeom2
        return refgeom2.bounding_box()
    old = existing_bounding_box(doc)
    if old:
        return old
    doc.openTransaction("Bounding Box")
    try:
        obj = new_bounding_box(doc)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return obj


COMMANDS = {
    "SWStyle_CompositeCurve": ("Composite Curve", "Joins the selected edges and sketch curves into one curve.", composite_curve),
    "SWStyle_CurveThroughXYZPoints": ("Curve Through XYZ Points", "Makes a curve through points typed in or read from a file.", curve_through_xyz_points),
    "SWStyle_CurveThroughReferencePoints": ("Curve Through Reference Points", "Makes a curve through the selected vertices and points.", curve_through_reference_points),
    "SWStyle_OffsetOnSurface": ("Offset On Surface", "Offsets edges and faces across their faces, staying on them, in a 3D sketch.", offset_on_surface),
    "SWStyle_CenterOfMass": ("Center of Mass", "Adds a point at the part's centre of mass that follows the part.", center_of_mass),
    "SWStyle_BoundingBox": ("Bounding Box", "Adds the box round the part, with its length, width and height.", bounding_box),
}


class _Cmd:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        menu, tip, _ = COMMANDS[self.name]
        return {"MenuText": menu, "ToolTip": tip}

    def Activated(self):
        COMMANDS[self.name][2]()

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()


_installed = False


def install():
    global _installed
    if _installed:
        return
    for name in COMMANDS:
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _Cmd(name))
    try:
        # tool first for the FreeCAD commands the Surfaces tab maps (pickfirst.NATIVES)
        from . import pickfirst
        pickfirst.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: tool-first commands not added: %s\n" % error)
    try:
        # Coordinate System, Point, Helix/Spiral, Projected Curve and Bounding Box PropertyManagers
        from . import refgeom2
        refgeom2.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: reference geometry PropertyManagers not added: %s\n" % error)
    try:

        from . import surfacepms
        surfacepms.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: surface PropertyManagers not added: %s\n" % error)
    _installed = True
