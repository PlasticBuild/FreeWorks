# SPDX-License-Identifier: LGPL-2.1-or-later
""







import math

import FreeCAD as App

V = App.Vector


def _vec(v):
    return [round(v.x, 9), round(v.y, 9), round(v.z, 9)]


def _frame(placement):
    r = placement.Rotation
    return {"origin": _vec(placement.Base), "x": _vec(r.multVec(V(1, 0, 0))),
            "y": _vec(r.multVec(V(0, 1, 0))), "z": _vec(r.multVec(V(0, 0, 1)))}


# ---------------------------------------------------------------- sketches
CONSTRAINTS = {
    "Coincident": "coincident", "Horizontal": "horizontal", "Vertical": "vertical",
    "Parallel": "parallel", "Perpendicular": "perpendicular", "Tangent": "tangent",
    "Equal": "equal", "PointOnObject": "on_curve", "Symmetric": "symmetric",
    "Block": "fix", "Distance": "distance", "DistanceX": "distance_x", "DistanceY": "distance_y",
    "Radius": "radius", "Diameter": "diameter", "Angle": "angle",
}


def _geometry(g, construction):
    import Part
    d = {"construction": bool(construction)}
    if isinstance(g, Part.LineSegment):
        d.update(kind="line", start=_vec(g.StartPoint), end=_vec(g.EndPoint))
    elif isinstance(g, Part.ArcOfCircle):
        d.update(kind="arc", center=_vec(g.Center), radius=g.Radius, start=_vec(g.StartPoint),
                 end=_vec(g.EndPoint), ccw=g.Axis.z > 0)
    elif isinstance(g, Part.Circle):
        d.update(kind="circle", center=_vec(g.Center), radius=g.Radius)
    elif isinstance(g, Part.Point):
        d.update(kind="point", at=[g.X, g.Y, g.Z])
    elif isinstance(g, Part.ArcOfEllipse):
        d.update(kind="ellipse_arc", center=_vec(g.Center), major=g.MajorRadius, minor=g.MinorRadius,
                 start=_vec(g.StartPoint), end=_vec(g.EndPoint))
    elif isinstance(g, Part.Ellipse):
        d.update(kind="ellipse", center=_vec(g.Center), major=g.MajorRadius, minor=g.MinorRadius,
                 major_dir=_vec(g.XAxis))
    elif isinstance(g, Part.BSplineCurve):
        d.update(kind="spline", points=[_vec(p) for p in g.getPoles()], degree=g.Degree)
    else:
        d.update(kind="unsupported", type=type(g).__name__)
    return d


def sketch_data(sk):
    geo = [_geometry(g, sk.getConstruction(i)) for i, g in enumerate(sk.Geometry)]
    cons = []
    for c in sk.Constraints:
        kind = CONSTRAINTS.get(c.Type)
        if kind is None:
            continue
        row = {"kind": kind, "first": c.First, "first_pos": c.FirstPos, "second": c.Second,
               "second_pos": c.SecondPos, "third": c.Third, "driving": bool(c.Driving)}
        if c.Type in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter"):
            row["value"] = c.Value
        elif c.Type == "Angle":
            row["value"] = math.degrees(c.Value)
        cons.append(row)
    return {"kind": "sketch", "name": sk.Label, "frame": _frame(sk.getGlobalPlacement()),
            "geometry": geo, "constraints": cons}


# ---------------------------------------------------------------- features
def _edge_points(shape, names):
    pts = []
    for n in names:
        try:
            e = shape.getElement(n)
        except Exception:
            continue
        a, b = e.FirstParameter, e.LastParameter
        pts.append([_vec(e.valueAt(a + (b - a) * t)) for t in (0.25, 0.5, 0.75)])
    return pts


def _face_point(face):
    """A point that lies on the face (its centre of mass may not, for a ring or an L)."""
    u0, u1, v0, v1 = face.ParameterRange
    for fu, fv in ((0.5, 0.5), (0.25, 0.5), (0.75, 0.5), (0.5, 0.25), (0.5, 0.75), (0.3, 0.3), (0.7, 0.7)):
        p = face.valueAt(u0 + (u1 - u0) * fu, v0 + (v1 - v0) * fv)
        if face.isInside(p, 1e-6, True):
            return p
    return face.Vertexes[0].Point


def _face_points(shape, names):
    pts = []
    for n in names:
        try:
            pts.append(_vec(_face_point(shape.getElement(n))))
        except Exception:
            continue
    return pts


def _base_shape(feat):
    base = getattr(feat, "BaseFeature", None)
    return base.Shape if base is not None and hasattr(base, "Shape") else None


def feature_data(f):
    t = f.TypeId
    d = {"name": f.Label, "type": t.split("::")[-1]}
    if t in ("PartDesign::Pad", "PartDesign::Pocket"):
        d.update(kind="extrude", cut=t.endswith("Pocket"), profile=f.Profile[0].Label if f.Profile else None,
                 end=str(f.Type), length=float(f.Length), length2=float(getattr(f, "Length2", 0)),
                 midplane=bool(f.Midplane), reversed=bool(f.Reversed),
                 side=str(getattr(f, "SideType", "One side")))
    elif t in ("PartDesign::Revolution", "PartDesign::Groove"):
        axis = f.ReferenceAxis
        d.update(kind="revolve", cut=t.endswith("Groove"), profile=f.Profile[0].Label if f.Profile else None,
                 angle=float(f.Angle), reversed=bool(f.Reversed), midplane=bool(f.Midplane),
                 axis=[axis[0].Label, list(axis[1])] if axis else None,
                 axis_line=_axis_line(f))
    elif t in ("PartDesign::Fillet", "PartDesign::Chamfer"):
        names = list(f.Base[1]) if f.Base else []
        base = _base_shape(f)
        d.update(kind="fillet" if t.endswith("Fillet") else "chamfer",
                 size=float(f.Radius if t.endswith("Fillet") else f.Size),
                 edges=_edge_points(base, names) if base is not None else [])
    elif t in ("PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::Mirrored"):
        d.update(kind="pattern", seeds=[o.Label for o in f.Originals],
                 whole=str(getattr(f, "TransformMode", "Features")) == "Whole shape")
        if t.endswith("LinearPattern"):
            d.update(pattern="linear", count=int(f.Occurrences), spacing=_spacing(f, ""),
                     direction=_dir(f, "Direction"), reversed=bool(getattr(f, "Reversed", False)))
            if int(getattr(f, "Occurrences2", 1)) > 1:
                d.update(count2=int(f.Occurrences2), spacing2=_spacing(f, "2"),
                         direction2=_dir(f, "Direction2"), reversed2=bool(getattr(f, "Reversed2", False)))
        elif t.endswith("PolarPattern"):
            n, angle = int(f.Occurrences), float(f.Angle)
            if str(getattr(f, "Mode", "Extent")) == "Spacing":
                step = float(f.Offset)
            else:               # FreeCAD: a full turn spreads n instances, any other angle n-1 gaps
                step = angle / n if abs(angle - 360.0) < 1e-9 else angle / max(n - 1, 1)
            d.update(pattern="circular", count=n, step=step, axis_line=_axis_line(f, "Axis"),
                     reversed=bool(getattr(f, "Reversed", False)))
        else:
            d.update(pattern="mirror", plane=_plane(f))
    elif t == "PartDesign::Hole":
        d.update(kind="hole", profile=f.Profile[0].Label if f.Profile else None,
                 diameter=float(f.Diameter), depth=float(f.Depth), depth_type=str(f.DepthType),
                 cut_type=str(f.HoleCutType), cut_diameter=float(f.HoleCutDiameter),
                 cut_depth=float(f.HoleCutDepth), cut_angle=float(f.HoleCutCountersinkAngle),
                 drill_point=str(f.DrillPoint), drill_angle=float(f.DrillPointAngle),
                 reversed=bool(f.Reversed))
    elif t == "PartDesign::Thickness":
        base = _base_shape(f)
        names = list(f.Base[1]) if f.Base else []
        grow = base is not None and f.Shape.BoundBox.DiagonalLength > base.BoundBox.DiagonalLength + 1e-6
        d.update(kind="shell", thickness=float(f.Value), outward=bool(grow),
                 faces=_face_points(base, names) if base is not None else [],
                 join=str(getattr(f, "Join", "Arc")))
    elif t == "PartDesign::Draft":
        base = _base_shape(f)
        names = list(f.Base[1]) if f.Base else []
        neutral = None
        try:
            obj, subs = f.NeutralPlane[0], list(f.NeutralPlane[1])
            if obj.TypeId in ("App::Plane", "PartDesign::Plane"):
                pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
                neutral = {"point": _vec(pl.Base), "normal": _vec(pl.Rotation.multVec(V(0, 0, 1)))}
            elif subs and hasattr(obj, "Shape"):
                face = obj.Shape.getElement(subs[0])
                neutral = {"point": _vec(_face_point(face)), "normal": _vec(face.normalAt(0, 0)), "face": True}
        except Exception:
            neutral = None
        d.update(kind="draft", angle=float(f.Angle), reversed=bool(f.Reversed), neutral=neutral,
                 faces=_face_points(base, names) if base is not None else [])
    elif t in ("PartDesign::AdditivePipe", "PartDesign::SubtractivePipe"):
        d.update(kind="sweep", cut=t.startswith("PartDesign::Subtractive"),
                 profile=f.Profile[0].Label if f.Profile else None,
                 path=f.Spine[0].Label if f.Spine else None, mode=str(getattr(f, "Mode", "Standard")),
                 transition=str(getattr(f, "Transition", "Transformed")))
    elif t in ("PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft"):
        secs = []
        for s_ in getattr(f, "Sections", []) or []:
            secs.append((s_[0] if isinstance(s_, tuple) else s_).Label)
        d.update(kind="loft", cut=t.startswith("PartDesign::Subtractive"),
                 profiles=([f.Profile[0].Label] if f.Profile else []) + secs,
                 ruled=bool(getattr(f, "Ruled", False)), closed=bool(getattr(f, "Closed", False)))
    elif getattr(f, "SWStyleKind", "") in ("Dome", "VariableSizeFillet", "Wrap", "BoundaryBoss", "BoundaryCut"):
        d.update(_swstyle_data(f))
    elif type(getattr(f, "Proxy", None)).__name__ == "RibFeature":
        sk = getattr(f, "Sketch", None)
        d.update(kind="rib", profile=sk.Label if sk is not None else None, thickness=float(f.Thickness),
                 flip=bool(getattr(f, "Flip", False)), side=str(getattr(f, "ThicknessSide", "Both")),
                 direction=str(getattr(f, "ExtrusionDirection", "Parallel")),
                 draft=float(f.DraftAngle) if getattr(f, "DraftOn", False) else 0.0,
                 outward=bool(getattr(f, "DraftOutward", False)))
    elif t in ("PartDesign::Plane",):
        d.update(kind="plane", frame=_frame(f.Placement))
    elif t in ("PartDesign::Line", "PartDesign::Point", "PartDesign::CoordinateSystem"):
        d.update(kind="reference")
    else:
        d.update(kind="unsupported")
    return d


def _picks(f, prop):
    ""
    out = []
    for item in getattr(f, prop, None) or []:
        if isinstance(item, tuple) and len(item) == 2 and hasattr(item[0], "Shape"):
            subs = item[1] if isinstance(item[1], (list, tuple)) else [item[1]]
            out.append((item[0].Shape, [x for x in subs if x]))
    return out


def _dome_outline(fc):
    ""

    if fc.Surface.TypeId != "Part::GeomPlane" or len(fc.Wires) != 1:
        return None
    c = fc.CenterOfMass
    n = fc.normalAt(*fc.Surface.parameter(c))
    radius = max(v.Point.distanceToPoint(c) for v in fc.Vertexes) if fc.Vertexes else 0.0
    edges = []
    for e in fc.Wires[0].Edges:
        a, b = e.FirstParameter, e.LastParameter
        radius = max(radius, max(e.valueAt(a + i * (b - a) / 16).distanceToPoint(c) for i in range(17)))
        p, q = e.valueAt(a), e.valueAt(b)
        t = e.Curve.TypeId
        if t == "Part::GeomLine" or t == "Part::GeomLineSegment":
            edges.append({"kind": "line", "start": _vec(p), "end": _vec(q)})
        elif t == "Part::GeomCircle" and not e.isClosed():
            edges.append({"kind": "arc", "center": _vec(e.Curve.Center), "radius": float(e.Curve.Radius),
                          "start": _vec(p), "end": _vec(q), "axis": _vec(e.Curve.Axis)})
        else:
            return None
    return {"center": _vec(c), "normal": _vec(n), "radius": float(radius), "outline": edges}


def _swstyle_data(f):
    ""
    k = f.SWStyleKind
    if k == "Dome":
        faces, round_ = [], True
        for shape, names in _picks(f, "Faces"):
            faces += _face_points(shape, names)
            for n in names:
                try:
                    round_ = round_ and all(e.Curve.TypeId == "Part::GeomCircle" for e in shape.getElement(n).Edges)
                except Exception:
                    round_ = False
        disc = None                      # one round flat face: its centre, outward normal and radius
        picks = _picks(f, "Faces")
        if round_ and len(picks) == 1 and len(picks[0][1]) == 1:
            try:
                fc = picks[0][0].getElement(picks[0][1][0])
                outer = max(fc.Edges, key=lambda e: e.Curve.Radius)
                if len(fc.Edges) == 1:
                    disc = {"center": _vec(outer.Curve.Center), "radius": float(outer.Curve.Radius),
                            "normal": _vec(fc.normalAt(*fc.Surface.parameter(outer.Curve.Center)))}
            except Exception:
                disc = None
        polygon = None                   # one flat face of lines and arcs: its outline for a stand-in
        if disc is None and len(picks) == 1 and len(picks[0][1]) == 1:
            try:
                polygon = _dome_outline(picks[0][0].getElement(picks[0][1][0]))
            except Exception:
                polygon = None
        if polygon is not None:
            polygon["continuous"] = bool(getattr(f, "Continuous", False))
            polygon["point"] = bool(getattr(f, "Constraint", None))
            polygon["direction"] = bool(getattr(f, "Direction", None))
        return {"kind": "dome", "faces": faces, "round": round_, "disc": disc, "polygon": polygon,
                "height": float(f.Distance), "reverse": bool(f.Reverse),
                "elliptical": bool(getattr(f, "Elliptical", False))}
    if k == "VariableSizeFillet":
        edges = []
        for shape, names in _picks(f, "Edges"):
            for n in names:
                try:
                    e = shape.getElement(n)
                except Exception:
                    continue
                a, b = e.FirstParameter, e.LastParameter
                edges.append({"points": [_vec(e.valueAt(a + (b - a) * t)) for t in (0.25, 0.5, 0.75)],
                              "start": _vec(e.valueAt(a)), "end": _vec(e.valueAt(b))})
        def nums(text):
            out = []
            for w in str(text or "").replace(";", ",").split(","):
                w = w.strip().rstrip("%").replace("mm", "").strip()
                try:
                    out.append(float(w))
                except ValueError:
                    pass
            return out
        return {"kind": "varfillet", "edges": edges, "start_radius": float(f.StartRadius),
                "point_radii": nums(getattr(f, "PointRadii", "")),
                "point_positions": nums(getattr(f, "PointPositions", "")),
                "end_radius": float(f.EndRadius),
                "control_points": int(getattr(f, "ControlPoints", 0) or 0) if any(
                    ch.isdigit() for ch in str(getattr(f, "PointRadii", "") or "")) else 0}
    if k == "Wrap":
        faces = []
        for shape, names in _picks(f, "Face"):
            faces += _face_points(shape, names)
        sk = getattr(f, "Sketch", None)
        if isinstance(sk, (list, tuple)):
            sk = sk[0] if sk else None
            sk = sk[0] if isinstance(sk, tuple) else sk
        return {"kind": "wrap", "profile": sk.Label if sk is not None else None, "faces": faces,
                "wrap_type": str(f.WrapType), "method": str(getattr(f, "WrapMethod", "Analytical")),
                "thickness": float(f.Thickness), "reverse": bool(f.Reverse)}
    profiles = []
    for item in getattr(f, "Direction1", None) or []:
        obj = item[0] if isinstance(item, tuple) else item
        profiles.append(obj.Label)
    return {"kind": "boundary", "cut": k == "BoundaryCut", "profiles": profiles,
            "guides": len(getattr(f, "Direction2", None) or [])}


def _spacing(f, n):
    """Distance between neighbouring instances of a linear pattern, in mm."""
    count = int(getattr(f, "Occurrences" + n))
    if str(getattr(f, "Mode" + n, "Extent")) == "Spacing":
        return float(getattr(f, "Offset" + n))
    return float(getattr(f, "Length" + n)) / max(count - 1, 1)


def _axis_line(f, prop="ReferenceAxis"):
    """The axis as a point and a direction in model space, whatever it references."""
    try:
        ref = getattr(f, prop)
        obj, subs = ref[0], list(ref[1]) or [""]
        sub = subs[0]
        if obj.TypeId == "Sketcher::SketchObject":
            pl = obj.getGlobalPlacement()
            if sub in ("V_Axis", "H_Axis"):
                d = V(0, 1, 0) if sub == "V_Axis" else V(1, 0, 0)
                return {"point": _vec(pl.Base), "dir": _vec(pl.Rotation.multVec(d))}
            if sub.startswith("Axis"):
                axes = [i for i, gg in enumerate(obj.Geometry) if obj.getConstruction(i)
                        and gg.TypeId == "Part::GeomLineSegment"]
                seg = obj.Geometry[axes[int(sub[4:])]]
                p, q = pl.multVec(seg.StartPoint), pl.multVec(seg.EndPoint)
                return {"point": _vec(p), "dir": _vec((q - p).normalize())}
        if hasattr(obj, "Shape") and sub:
            e = obj.Shape.getElement(sub)
            if hasattr(e, "Curve") and hasattr(e.Curve, "Direction"):
                return {"point": _vec(e.Vertexes[0].Point), "dir": _vec(e.Curve.Direction)}
            if hasattr(e, "Surface") and hasattr(e.Surface, "Axis"):
                return {"point": _vec(e.Surface.Center), "dir": _vec(e.Surface.Axis)}
        if obj.TypeId in ("App::Line", "PartDesign::Line"):
            pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
            return {"point": _vec(pl.Base), "dir": _vec(pl.Rotation.multVec(V(0, 0, 1) if obj.TypeId ==
                                                                             "PartDesign::Line" else V(1, 0, 0)))}
    except Exception:
        pass
    return None


def _dir(f, prop):
    line = _axis_line(f, prop)
    return line["dir"] if line else None


def _plane(f):
    try:
        obj, subs = f.MirrorPlane[0], list(f.MirrorPlane[1]) or [""]
        sub = subs[0]
        if obj.TypeId == "Sketcher::SketchObject":
            pl = obj.getGlobalPlacement()
            n = V(1, 0, 0) if sub == "V_Axis" else V(0, 1, 0) if sub == "H_Axis" else V(0, 0, 1)
            return {"point": _vec(pl.Base), "normal": _vec(pl.Rotation.multVec(n))}
        if obj.TypeId in ("App::Plane", "PartDesign::Plane"):
            pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
            return {"point": _vec(pl.Base), "normal": _vec(pl.Rotation.multVec(V(0, 0, 1)))}
        if hasattr(obj, "Shape") and sub:
            face = obj.Shape.getElement(sub)
            return {"point": _vec(face.Surface.Position), "normal": _vec(face.Surface.Axis)}
    except Exception:
        pass
    return None


def body_data(body):
    feats, done = [], set()
    for obj in body.Group:

        prof = getattr(obj, "Profile", None)
        firsts = [prof[0] if prof else None]
        spine = getattr(obj, "Spine", None)
        firsts.append(spine[0] if spine else None)
        for s_ in getattr(obj, "Sections", None) or []:
            firsts.append(s_[0] if isinstance(s_, tuple) else s_)
        rib_sketch = getattr(obj, "Sketch", None)
        if isinstance(rib_sketch, (list, tuple)):          # a pick list (Wrap)
            rib_sketch = rib_sketch[0] if rib_sketch else None
            rib_sketch = rib_sketch[0] if isinstance(rib_sketch, tuple) else rib_sketch
        if rib_sketch is not None:
            firsts.append(rib_sketch)
        for s_ in getattr(obj, "Direction1", None) or [] if getattr(obj, "SWStyleKind", "") else []:
            firsts.append(s_[0] if isinstance(s_, tuple) else s_)
        for sk in firsts:
            if sk is not None and getattr(sk, "TypeId", "") == "Sketcher::SketchObject" and sk.Name not in done:
                feats.append(sketch_data(sk))
                done.add(sk.Name)
        if obj.TypeId == "Sketcher::SketchObject":
            if obj.Name not in done:
                feats.append(sketch_data(obj))
                done.add(obj.Name)
        elif obj.TypeId == "PartDesign::FeatureBase":
            feats.append({"name": obj.Label, "kind": "unsupported", "type": "BaseFeature"})
        elif obj.isDerivedFrom("PartDesign::Feature") or obj.TypeId.startswith("PartDesign::"):
            row = feature_data(obj)
            try:
                if obj.isDerivedFrom("PartDesign::FeatureAddSub") or row.get("kind") in ("pattern", "fillet",
                                                                                          "chamfer", "hole",
                                                                                          "shell", "draft", "rib", "dome", "varfillet",
                                                                                          "wrap", "boundary"):
                    row["volume"] = obj.Shape.Volume
            except Exception:
                pass
            feats.append(row)
        if obj == body.Tip:
            break
    return {"name": body.Label, "features": feats}
