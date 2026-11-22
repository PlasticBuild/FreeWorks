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

TYPE = "PartDesign::FeaturePython"
PROFILES = ("Circular", "Conic Rho", "Conic Radius", "Curvature Continuous")
OVERFLOWS = ("Default", "Keep edge", "Keep surface")


def is_conic_fillet(obj):
    try:
        return obj.TypeId == TYPE and isinstance(obj.Proxy, ConicFilletFeature)
    except Exception:
        return False


def _curve(p0, corner, p2, profile, rho=0.5, conic_radius=None, theta=math.pi / 2):
    import Part
    if profile == "Line":           # a chamfer's flat
        return Part.LineSegment(p0, p2)
    if profile == "Curvature Continuous":
        c = Part.BezierCurve()
        c.setPoles([p0, p0 + (corner - p0) * 0.5, corner, corner + (p2 - corner) * 0.5, p2])
        return c
    c = Part.BezierCurve()
    c.setPoles([p0, corner, p2])
    if profile == "Conic Rho":
        if not 0.0 < rho < 1.0:
            raise RuntimeError("Rho must be between 0 and 1.")
        w = rho / (1.0 - rho)
    elif profile == "Conic Radius":
        if not conic_radius or conic_radius <= 0:
            raise RuntimeError("The conic radius must be more than zero.")
        w = _weight_for_radius(c, conic_radius)
    else:
        w = math.sin(theta / 2.0)       # the circle (stretched: the ellipse)
    c.setWeight(2, w)
    return c


def _weight_for_radius(c, radius):
    """The middle weight that gives the conic radius of curvature `radius` at its middle."""
    def r_at(w):
        c.setWeight(2, w)
        k = c.curvature(0.5)
        return 1.0 / k if k > 1e-12 else 1e12
    lo, hi = 1e-3, 1e3      # a bigger weight pulls the curve to the corner: a smaller radius
    if not (r_at(hi) <= radius <= r_at(lo)):
        raise RuntimeError("No conic fits this conic radius between these distances.")
    for _i in range(80):
        mid = math.sqrt(lo * hi)
        if r_at(mid) > radius:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


def _side(face, edge_point, t, n):
    """The unit direction from the edge into the face, square to the edge."""
    d = n.cross(t)
    d.normalize()
    probe = edge_point + d * 1e-3
    if face.distToShape(_vertex(probe))[0] > 1e-6:
        d = d * -1
    return d


def _vertex(p):
    import Part
    return Part.Vertex(p)


def _direction_at(edge, vertex):
    """The unit direction of the edge leaving the vertex."""
    # by parameter, not Vertexes[0]: a reversed edge lists its vertices the other way round
    first = (edge.valueAt(edge.FirstParameter) - vertex.Point).Length < \
        (edge.valueAt(edge.LastParameter) - vertex.Point).Length
    u = edge.FirstParameter if first else edge.LastParameter
    t = edge.Curve.tangent(u)[0]
    if not first:
        t = t * -1
    t.normalize()
    return t


def _sharp(shape, edge):
    import Part
    faces = shape.ancestorsOfType(edge, Part.Face)
    if len(faces) != 2:
        return False
    try:
        m = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        n1 = faces[0].normalAt(*faces[0].Surface.parameter(m))
        n2 = faces[1].normalAt(*faces[1].Surface.parameter(m))
        return n1.getAngle(n2) > 1e-3
    except Exception:
        return True


def supported(shape, edges):
    """True when every edge is straight and between two flat faces: what piece() can make. A
    chamfer on a round edge (a hole's rim) goes to FreeCAD's own Chamfer instead."""
    import Part
    if not edges:
        return False
    for e in edges:
        if e.Curve.__class__.__name__ not in ("Line", "LineSegment"):
            return False
        faces = shape.ancestorsOfType(e, Part.Face)
        if len(faces) != 2 or any(f.Surface.__class__.__name__ != "Plane" for f in faces):
            return False
    return True


def tangent_continued(shape, edges):
    ""

    for e in edges:
        for v in e.Vertexes:
            d = _direction_at(e, v)
            for g in shape.Edges:
                if g.isSame(e) or any(g.isSame(x) for x in edges):
                    continue
                if not any(x.isSame(v) for x in g.Vertexes):
                    continue
                try:
                    if _direction_at(g, v).getAngle(d * -1) < 1e-3 and _sharp(shape, g):
                        return True
                except Exception as _fw_err:
                    _fw_log("conicfillet.py:166", _fw_err)
                    continue
    return False


def face_width(face, edge, p_start, t, length, side):
    """How far the face reaches from the edge, square to it (to its nearest other edge)."""
    import Part
    best = None
    reach = face.BoundBox.DiagonalLength * 2.0 + 1.0
    # a line square to the edge from points along it (not its ends, where the face's side edges
    # start at width 0) to the first other edge it meets
    for k in (0.02, 0.25, 0.5, 0.75, 0.98):
        p = p_start + t * (length * k)
        try:
            ray = Part.LineSegment(p, p + side * reach).toShape()
        except Exception:
            continue
        for g in face.Edges:
            if g.isSame(edge):
                continue
            try:
                d, pairs, _info = ray.distToShape(g)
            except Exception:
                continue
            if d > 1e-6:
                continue
            for q, _q2 in pairs:
                w = (q - p).dot(side)
                if w > 1e-6 and (best is None or w < best):
                    best = w
    return best


def overflows(solid, edge, faces, d_first, d_second, symmetric_radius=None):
    """True when the fillet would run past an edge of one of its two faces."""
    import math as _m
    p_start = edge.Vertexes[0].Point
    t = edge.Vertexes[-1].Point - p_start
    length = t.Length
    t.normalize()
    sides = [_side(f, p_start, t, f.normalAt(0, 0)) for f in faces]
    theta = sides[0].getAngle(sides[1])
    if symmetric_radius is not None and 1e-6 < theta < _m.pi - 1e-6:
        d_first = d_second = symmetric_radius / _m.tan(theta / 2.0)
    for f, side, d in zip(faces, sides, (d_first, d_second)):
        w = face_width(f, edge, p_start, t, length, side)
        if w is not None and d > w + 1e-6:
            return True
    return False


def _clip(prism, solid, faces, edge):
    """Keep surface: the piece stops at the planes of the faces next to its two (the fillet is
    trimmed by the surface it would run over)."""
    import Part
    mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
    for f in solid.Faces:
        if any(f.isSame(x) for x in faces) or f.Surface.__class__.__name__ != "Plane":
            continue
        try:
            if f.distToShape(prism)[0] > 1e-6:
                continue
            n = f.normalAt(0, 0)
            c = f.CenterOfMass
            if abs((mid - c).dot(n)) < 1e-6:
                continue
            size = prism.BoundBox.DiagonalLength * 2.0 + 1.0
            if (mid - c).dot(n) < 0:
                n = n * -1
            half = Part.makePlane(4 * size, 4 * size, App.Vector(0, 0, 0), n)
            half.translate(c - half.CenterOfMass)
            prism = prism.common(half.extrude(n * size))
        except Exception:
            continue
    return prism


def piece(solid, edge, faces, d_first, d_second, profile, rho, conic_radius, symmetric_radius=None,
          chamfer_angle=0.0, overflow="Default"):
    """(the solid between the profile and the edge, True if it is cut away / False if added)."""
    import Part
    if edge.Curve.__class__.__name__ not in ("Line", "LineSegment"):
        raise RuntimeError("Asymmetric and conic fillets are made on straight edges for now.")
    for f in faces:
        if f.Surface.__class__.__name__ != "Plane":
            raise RuntimeError("Asymmetric and conic fillets are made between flat faces for now.")
    p_start = edge.Vertexes[0].Point
    p_end = edge.Vertexes[-1].Point
    t = p_end - p_start
    length = t.Length
    t.normalize()
    n_a = faces[0].normalAt(0, 0)
    n_b = faces[1].normalAt(0, 0)
    a = _side(faces[0], p_start, t, n_a)
    b = _side(faces[1], p_start, t, n_b)
    theta = a.getAngle(b)                  # the angle between the faces at the edge
    if theta < math.radians(1) or theta > math.radians(179):
        raise RuntimeError("An edge between (almost) flat faces cannot be filleted.")
    if symmetric_radius is not None:
        d_first = d_second = symmetric_radius / math.tan(theta / 2.0)
    if overflow == "Keep edge":
        # the fillet ends at the face's other edge: its section is squeezed, the edge stays
        w_a = face_width(faces[0], edge, p_start, t, length, a)
        w_b = face_width(faces[1], edge, p_start, t, length, b)
        if w_a is not None:
            d_first = min(d_first, w_a)
        if w_b is not None:
            d_second = min(d_second, w_b)
    if chamfer_angle:
        # Angle Distance: the flat leaves the first face at the angle; where it meets the other
        alpha = math.radians(chamfer_angle)
        if alpha + theta >= math.pi - 1e-6:
            raise RuntimeError("The chamfer angle does not meet the other face.")
        d_second = d_first * math.sin(alpha) / math.sin(math.pi - alpha - theta)
    p0 = p_start + a * d_first
    p2 = p_start + b * d_second
    c = _curve(p0, p_start, p2, profile, rho, conic_radius, theta)
    wire = Part.Wire(Part.__sortEdges__([Part.LineSegment(p0, p_start).toShape(),
                                         Part.LineSegment(p_start, p2).toShape(), c.toShape()]))
    prism = Part.Face(wire).extrude(t * length)
    if overflow == "Keep surface":
        prism = _clip(prism, solid, faces, edge)
    # inside edge: the corner's wedge is empty and the fillet fills it
    inside = (a + b)
    inside.normalize()
    probe = p_start + t * (length / 2.0) + inside * (min(d_first, d_second) * 0.05)
    convex = solid.isInside(probe, 1e-7, True)
    return prism, convex


def conic_fillet(solid, edges, d1, d2, profile, rho, conic_radius, symmetric_radius=None, reverse=False,
                 chamfer_angle=0.0, overflow="Default"):
    import Part
    cuts, adds = [], []
    for e in edges:
        faces = solid.ancestorsOfType(e, Part.Face)
        if len(faces) != 2:
            raise RuntimeError("A fillet edge must be between two faces.")
        if reverse and chamfer_angle:

            # swapping the distances does nothing there, the second one comes from the angle
            faces = [faces[1], faces[0]]
            first, second = d1, d2
        else:
            first, second = (d2, d1) if reverse else (d1, d2)
        prism, convex = piece(solid, e, faces, first, second, profile, rho, conic_radius, symmetric_radius,
                              chamfer_angle, overflow)
        (cuts if convex else adds).append(prism)
    if not cuts and not adds:
        raise RuntimeError("Select items to fillet.")
    out = solid
    if cuts:
        out = out.cut(cuts) if len(cuts) > 1 else out.cut(cuts[0])
    if adds:
        out = out.fuse(adds) if len(adds) > 1 else out.fuse(adds[0])
    try:
        out = out.removeSplitter()
    except Exception as _fw_err:
        _fw_log("conicfillet.py:312", _fw_err)
    if len(out.Solids) == 1:
        out = out.Solids[0]
    if out.isNull() or not out.isValid():
        raise RuntimeError("The fillet could not be made at these sizes: try smaller ones.")
    return out


class ConicFilletFeature:
    def __init__(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def setup(self, obj):
        props = obj.PropertiesList
        if "Base" not in props:
            obj.addProperty("App::PropertyLinkSub", "Base", "Fillet", "Items to fillet")
        if "Symmetric" not in props:
            obj.addProperty("App::PropertyBool", "Symmetric", "Fillet", "One radius (else two distances)")
            obj.Symmetric = True
        if "Radius" not in props:
            obj.addProperty("App::PropertyLength", "Radius", "Fillet", "Radius (Symmetric)")
            obj.Radius = 1.0
        for name, tip in (("Distance1", "Distance 1 on the edge's first face (Asymmetric)"),
                          ("Distance2", "Distance 2 on the other face (Asymmetric)")):
            if name not in props:
                obj.addProperty("App::PropertyLength", name, "Fillet", tip)
                setattr(obj, name, 1.0)
        if "Reverse" not in props:
            obj.addProperty("App::PropertyBool", "Reverse", "Fillet", "Swap Distance 1 and 2")
        if "Profile" not in props:
            obj.addProperty("App::PropertyEnumeration", "Profile", "Fillet", "Fillet profile")
            obj.Profile = list(PROFILES)
        if "Rho" not in props:
            obj.addProperty("App::PropertyFloat", "Rho", "Fillet", "Conic Rho (0 to 1)")
            obj.Rho = 0.5
        if "ConicRadius" not in props:
            obj.addProperty("App::PropertyLength", "ConicRadius", "Fillet", "Conic Radius")
            obj.ConicRadius = 1.0
        if "KeepFeatures" not in props:
            obj.addProperty("App::PropertyBool", "KeepFeatures", "Fillet",
                            "Chamfer Options: off takes out the bosses and cuts the chamfer runs into")
            obj.KeepFeatures = True
        if "TangentPropagation" not in props:
            obj.addProperty("App::PropertyBool", "TangentPropagation", "Fillet",
                            "Off: only the picked edges, not the tangent edges they run into")
            obj.TangentPropagation = True
        if "Kind" not in props:
            obj.addProperty("App::PropertyEnumeration", "Kind", "Fillet", "Fillet or Chamfer")
            obj.Kind = ["Fillet", "Chamfer"]
        if "Overflow" not in props:
            obj.addProperty("App::PropertyEnumeration", "Overflow", "Fillet Options",
                            "Overflow type: what happens where the fillet runs past a face's edge")
            obj.Overflow = list(OVERFLOWS)
        if "ChamferAngle" not in props:
            obj.addProperty("App::PropertyAngle", "ChamferAngle", "Fillet", "Chamfer Angle Distance (0: two distances)")

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
        if base is None or base.isNull():
            raise RuntimeError("Fillet needs a part")
        if "Overflow" not in obj.PropertiesList:
            self.setup(obj)
        from . import multiradius
        source = obj.Base[0].Shape if obj.Base else base
        subs = list(obj.Base[1]) if obj.Base else []
        picked = []
        for sub in subs or [""]:
            name = sub.split(".")[-1].lstrip("?")
            try:
                if not name:
                    picked += list(source.Edges)
                else:
                    g = source.getElement(name)
                    picked += list(g.Edges) if name.startswith("Face") else [g]
            except Exception:
                continue
        edges = []
        for e in picked:
            b = next((b for b in base.Edges if multiradius._same_edge(b, e)), None)
            if b is not None and not any(b.isSame(x) for x in edges):
                edges.append(b)
        if obj.Kind == "Chamfer":
            d1 = obj.Distance1.Value
            d2 = d1 if obj.Symmetric else obj.Distance2.Value
            reach = max(d1, d2, _angle_reach(d1, obj.ChamferAngle.Value))
            clean, clean_edges = _without_features(base, edges, reach)

            def cut(shape, along):
                return conic_fillet(shape, along, d1, d2, "Line", 0.5, 1.0, None, obj.Reverse, obj.ChamferAngle.Value)
            if clean is base:
                obj.Shape = cut(base, edges)
            elif not getattr(obj, "KeepFeatures", True):
                obj.Shape = cut(clean, clean_edges)          # the features in the way are gone
            else:
                obj.Shape = _put_back(base, clean, cut(clean, clean_edges))
            return
        obj.Shape = conic_fillet(base, edges, obj.Distance1.Value, obj.Distance2.Value, obj.Profile,
                                 obj.Rho, obj.ConicRadius.Value,
                                 obj.Radius.Value if obj.Symmetric else None, obj.Reverse,
                                 0.0, obj.Overflow)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _angle_reach(d, angle):
    import math
    if not angle or angle >= 89.9:
        return d
    return d * max(1.0, math.tan(math.radians(angle)))


def _without_features(base, edges, reach):
    ""

    from . import setbackfillet
    pairs = [(i, reach) for i, b in enumerate(base.Edges, 1) if any(b.isSame(e) for e in edges)]
    clean, new_pairs = setbackfillet.without_features(base, pairs)
    if clean is base:
        return base, edges
    return clean, [clean.Edges[k - 1] for k, _r in new_pairs]


def _put_back(base, clean, done):
    ""

    out = done
    added, taken = base.cut(clean), clean.cut(base)
    if added.Volume > 1e-9:
        out = out.fuse(added)
    if taken.Volume > 1e-9:
        out = out.cut(taken)
    try:
        out = out.removeSplitter()
    except Exception as _fw_err:
        _fw_log("conicfillet.py:455", _fw_err)
    if len(out.Solids) == 1:
        out = out.Solids[0]
    return out if not out.isNull() and out.isValid() else done


class ConicFilletView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            icon = icons.family("FEATURES_CHAMFER" if getattr(self.Object, "Kind", "") == "Chamfer" else "FEATURES_FILLET")
            if not icon.isNull():
                return icon
        except Exception as _fw_err:
            _fw_log("conicfillet.py:475", _fw_err)
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
    ConicFilletFeature(obj)
    if App.GuiUp:
        ConicFilletView(obj.ViewObject)
    return obj


def new(body, name="Fillet"):
    label = None
    try:
        from . import naming
        label = naming.next_label(body.Document, name)     # counted before it exists
    except Exception as _fw_err:
        _fw_log("conicfillet.py:520", _fw_err)
    obj = body.newObject(TYPE, name)
    setup_new(obj)
    if label:
        obj.Label = label
    return obj
