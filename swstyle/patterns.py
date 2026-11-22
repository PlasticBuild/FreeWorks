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
import Part

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
SUBTRACTIVE_WORDS = ("Pocket", "Hole", "Groove", "Subtractive", "Cut")


def _subtractive(feature):
    if any(word in feature.TypeId for word in SUBTRACTIVE_WORDS):
        return True
    base = getattr(feature, "BaseFeature", None)
    try:
        return base is not None and feature.Shape.Volume < base.Shape.Volume - 1e-9
    except Exception:
        return False


def _seeds(obj, base=None):
    """(shape, subtractive) of each seed: the features' material and, with the part given, the
    Faces to Pattern closed off into a solid (a boss's faces add, a pocket's faces cut)."""
    seeds = [f for f in (getattr(obj, "Features", None) or []) if hasattr(f, "AddSubShape")]
    out = _face_seeds(obj, base) if base is not None else []
    if not seeds:
        return out
    seeds, regions = _fold_dressups(seeds)
    out.extend(regions)
    for feature in seeds:
        if feature.AddSubShape.isNull():
            continue
        # AddSubShape is in the feature's own coordinates
        shape = feature.AddSubShape.copy()
        shape.Placement = feature.Placement.multiply(shape.Placement)
        out.append((shape, _subtractive(feature)))
    return out


def is_dressup(feature):
    try:
        return feature.isDerivedFrom("PartDesign::DressUp")
    except Exception:
        return False


def _dressed(feature):
    """The feature a dress-up (Fillet, Chamfer, Draft, Shell) is on."""
    base = getattr(feature, "Base", None)
    if isinstance(base, tuple):
        base = base[0]
    return base if base is not None else getattr(feature, "BaseFeature", None)


def _fold_dressups(features):
    ""





    dress = [f for f in features if is_dressup(f)]
    if not dress:
        return list(features), []
    plain = [f for f in features if not is_dressup(f)]
    top = {}                       # seed (or lone dress-up) -> the last dress-up on it
    for d in dress:
        start, seen = d, set()
        while is_dressup(start) and start.Name not in seen:
            seen.add(start.Name)
            below = _dressed(start)
            if below is None or below in plain:
                start = below if below is not None else start
                break
            if below in dress:
                start = below
                continue
            break                  # a dress-up on a feature not in the list: it stands alone
        key = start if start in plain else d
        last = top.get(key)
        if last is None or _later(d, last):
            top[key] = d
    regions = []
    for start, last in top.items():
        before = getattr(start, "BaseFeature", None)
        after = last.Shape
        if before is None or before.Shape.isNull():
            gained, lost = after.copy(), None
        else:
            gained = _boolean("cut", after, [before.Shape])
            lost = _boolean("cut", before.Shape, [after])
        for shape, subtractive in ((gained, False), (lost, True)):
            if shape is not None and not shape.isNull() and shape.Solids and shape.Volume > 1e-6:
                regions.append((Part.makeCompound(shape.Solids) if len(shape.Solids) > 1 else shape.Solids[0], subtractive))
    return [f for f in plain if f not in top], regions


def _later(a, b):
    """True when feature a comes after b in their body."""
    try:
        body = a.getParentGeoFeatureGroup()
        group = list(body.Group)
        return group.index(a) > group.index(b)
    except Exception:
        return False


def _face_seeds(obj, base):
    if "Faces" not in obj.PropertiesList or base is None or base.isNull():
        return []
    faces = [shape for _o, shape in sf.elements(obj, "Faces") if shape.ShapeType == "Face"]
    if not faces:
        return []
    solid = faces_solid(faces)
    hollow = solid.common(base).Volume < solid.Volume * 0.5
    return [(solid, hollow)]


def _bodies(obj, base):
    """The solids of the part picked for Bodies to Pattern (a face, edge or vertex of each)."""
    if "Bodies" not in obj.PropertiesList or base is None or base.isNull():
        return []
    from .loftsweep import body_holds
    out = []
    for _o, picked in sf.elements(obj, "Bodies"):
        for solid in base.Solids:
            if body_holds(solid, picked) and not any(solid.isSame(b) for b in out):
                out.append(solid)
                break
    return out


def _with_bodies(obj, base, made, placements):
    ""

    bodies = _bodies(obj, base)
    if not bodies:
        return made
    result, tool = made
    result = base if result is None else result
    copies = []
    for placement in placements:
        if placement.Base.Length < 1e-7 and abs(placement.Rotation.Angle) < 1e-9:
            continue
        for body in bodies:
            copy = body.copy()
            copy.Placement = placement.multiply(copy.Placement)
            copies.append(copy)
    if not copies:
        return made
    solids = list(result.Solids) + copies
    return Part.makeCompound(solids), Part.makeCompound(copies + ([tool] if tool is not None else []))


def _nothing(obj, base, seeds):
    """Nothing to pattern: no seed features or faces and no bodies picked."""
    return not seeds and not _bodies(obj, base)


def _center(seeds, obj=None, base=None):
    shapes = [s for s, _ in seeds]
    if not shapes and obj is not None:
        shapes = _bodies(obj, base)
    if not shapes:
        raise RuntimeError("Select the features, faces or bodies to pattern.")
    total = sum(s.Volume for s in shapes)
    if total <= 0:
        return shapes[0].BoundBox.Center
    point = V(0, 0, 0)
    for shape in shapes:
        point += shape.CenterOfMass * (shape.Volume / total)
    return point


def _apply(base, seeds, placements):
    """Copies of the seeds moved by each placement (App.Placement acting on body coordinates);
    a placement that leaves the seed where it is makes no copy."""
    adds, cuts = [], []
    for placement in placements:
        if placement.Base.Length < 1e-7 and abs(placement.Rotation.Angle) < 1e-9:
            continue
        for shape, subtractive in seeds:
            copy = shape.copy()
            copy.Placement = placement.multiply(copy.Placement)
            (cuts if subtractive else adds).append(copy)
    return _combine(base, adds, cuts)


def _plain(shape):
    """shape without FreeCAD's element names: 1.1's named boolean gave "Null shape" fusing copies of
    a loft between ellipse or closed spline sections onto the loft's own result (a fan's blades)."""
    solids = [Part.Solid(s) for s in shape.Solids]
    if not solids:
        return shape.copy()
    return solids[0] if len(solids) == 1 else Part.makeCompound(solids)


def _boolean(op, shape, tools):
    try:
        result = getattr(shape, op)(tools, 1e-6)
        if not result.isNull():
            return result
    except Exception as _fw_err:
        _fw_log("patterns.py:_boolean", _fw_err)
    return getattr(_plain(shape), op)([_plain(t) for t in tools], 1e-6)


def _combine(base, adds, cuts):
    if not adds and not cuts:
        return None, None
    result = base
    if adds:
        result = _boolean("fuse", result, adds)
    if cuts:
        result = _boolean("cut", result, cuts)
    return result, Part.makeCompound(adds + cuts)


def _moves(points, origin):
    return [App.Placement(p - origin, App.Rotation()) for p in points]


def _features_field():
    return Field("Features", "pick", "Features to pattern", tip="Pick the seed features in the tree",
                 what="Feature", many=True, optional=True, box="Features and Faces")


def _what_fields():
    ""

    return [_features_field(),
            Field("Faces", "pick", "Faces to Pattern", tip="The faces of a boss or a pocket", what=("Face",),
                  many=True, optional=True, box="Features and Faces"),
            Field("Bodies", "pick", "Solid/Surface Bodies to Pattern", tip="Pick a face of each body to copy",
                  what=("Face", "Edge", "Vertex"), many=True, optional=True, box="Bodies")]


def _skip_field():
    return Field("Skip", "text", "Instances to Skip", "", box="Instances to Skip",
                 tip="Instance numbers to leave out (the seed is 1), e.g. 3, 5")


def _option_fields(vary=False):
    ""
    out = [Field("VarySketch", "bool", "Vary sketch", False, box="Options")] if vary else []
    return out + [Field("GeometryPattern", "bool", "Geometry pattern", True, box="Options"),
                  Field("Propagate", "bool", "Propagate visual properties", True, box="Options")]


def _finish(obj, base, seeds, placements, skip=True):
    """Instances to Skip (by number, the seed being 1), then Geometry pattern / Vary sketch: on,
    copies of the seed; off (or Vary sketch), the seed made again at every instance."""
    if skip:
        gone = {i for i, _j in parse_skip(getattr(obj, "Skip", "") or "")}
        placements = [p for k, p in enumerate(placements, start=2) if k not in gone]
    vary = bool(getattr(obj, "VarySketch", False))
    if vary and getattr(obj, "GeometryPattern", True):
        raise RuntimeError("A pattern with variant sketch option is not suitable for geometry pattern.")
    if vary:
        return _with_bodies(obj, base, _apply_varied_sketch(obj, base, placements), placements)
    if not getattr(obj, "GeometryPattern", True):
        return _with_bodies(obj, base, _apply_regrown(obj, base, placements), placements)
    return _with_bodies(obj, base, _apply(base, seeds, placements), placements)


# --------------------------------------------------------------------------- Sketch Driven
def _sketch_points(sketch):
    placement = sketch.getGlobalPlacement() if hasattr(sketch, "getGlobalPlacement") else sketch.Placement
    points = []
    for index, geometry in enumerate(sketch.Geometry):
        if isinstance(geometry, Part.Point) and not sketch.getConstruction(index):
            points.append(placement.multVec(V(geometry.X, geometry.Y, geometry.Z)))
        elif isinstance(geometry, (Part.Circle, Part.ArcOfCircle)) and not sketch.getConstruction(index):
            points.append(placement.multVec(geometry.Center))
    return points


def _picked_point(obj, field):
    """The point a vertex (or a sketch point, or a round edge's centre) pick stands for, or None."""
    for _o, shape in sf.elements(obj, field):
        if shape.ShapeType == "Vertex":
            return shape.Point
        if shape.ShapeType == "Edge" and hasattr(shape.Curve, "Center"):
            return V(shape.Curve.Center)
        if shape.Vertexes:
            return shape.Vertexes[0].Point
    return None


def _reference(obj, seeds, fallback=None, base=None):
    """Reference point: the seed's centroid, or the point picked (Selected point)."""
    if getattr(obj, "ReferencePoint", "Centroid") in ("Selected point", "First sketch point"):
        point = _picked_point(obj, "RefPoint") if "RefPoint" in obj.PropertiesList else None
        if point is not None:
            return point
        if fallback is not None:
            return fallback
    return _center(seeds, obj, base) if base is not None else _center(seeds)


def _sketch_driven(obj, base):
    seeds = _seeds(obj, base)
    if _nothing(obj, base, seeds) or obj.Sketch is None:
        return None, None
    points = _sketch_points(obj.Sketch)
    if not points:
        raise RuntimeError("The sketch has no points")
    origin = _reference(obj, seeds, points[0], base)
    # Copies move in the sketch plane only: the seed keeps its height above the sketch
    placement = obj.Sketch.getGlobalPlacement() if hasattr(obj.Sketch, "getGlobalPlacement") else obj.Sketch.Placement
    normal = placement.Rotation.multVec(V(0, 0, 1))
    moves = []
    for point in points:
        shift = point - origin
        moves.append(App.Placement(shift - normal * shift.dot(normal), App.Rotation()))
    moves = [m for m in moves if m.Base.Length > 1e-7]      # the seed's own point
    return _finish(obj, base, seeds, moves)


def _ref_fields():
    return [Field("ReferencePoint", "radio", "Reference point", "Centroid", values=["Centroid", "Selected point"],
                  box="Reference point"),
            Field("RefPoint", "pick", "Reference vertex", what=("Vertex", "Edge"), optional=True,
                  shown=lambda o: getattr(o, "ReferencePoint", "") == "Selected point", box="Reference point")]


SKETCH_DRIVEN = sf.Spec(
    "SWStyle_SketchDrivenPattern", "Sketch Driven Pattern", "Sketch-Pattern",
    "Copies features to the points of a sketch.", "FEATURES_SKETCH_DRIVEN_PATTERN", "PartDesign_LinearPattern",
    [Field("Sketch", "pick", "Reference sketch", tip="A sketch with points (circle centres count too)",
           what="Feature", box="Selections")] + _ref_fields() + _what_fields() + [_skip_field()] + _option_fields(),
    _sketch_driven, first_pick="Sketch")


# --------------------------------------------------------------------------- Table Driven
def _table(text):
    points = []
    for line in text.replace(";", "\n").splitlines():
        parts = [p for p in line.replace(",", " ").replace("\t", " ").split() if p]
        if len(parts) < 2:
            continue
        try:
            values = [float(p) for p in parts[-3:] if p] if len(parts) > 3 else [float(p) for p in parts[:3]]
        except ValueError:
            continue
        points.append(V(values[0], values[1], values[2] if len(values) > 2 else 0.0))
    return points


def _table_driven(obj, base):
    seeds = _seeds(obj, base)
    points = _table(obj.Points)
    if _nothing(obj, base, seeds) or len(points) < 2:
        return None, None
    # the table's X Y are in the coordinate system picked (else the part's own)
    csys = getattr(obj, "CoordinateSystem", None)
    pl = App.Placement()
    if csys is not None:
        pl = csys.getGlobalPlacement() if hasattr(csys, "getGlobalPlacement") else csys.Placement

    # fills it in; the other points are where its copies go
    ref = pl.inverse().multVec(_reference(obj, seeds, base=base))
    lines = [l for l in obj.Points.replace(";", "\n").splitlines() if l.strip()]
    first = "%g %g" % (round(ref.x, 6), round(ref.y, 6))
    if lines and lines[0].strip() != first:
        obj.Points = "\n".join([first] + lines[1:])
        points = _table(obj.Points)
    world = [pl.multVec(p) for p in points]
    return _finish(obj, base, seeds, [App.Placement(p - world[0], App.Rotation()) for p in world[1:]])


def file_points(text):
    """The points of a pattern table file. Save as writes "index X Y" rows (the point number
    first, as the PM's table shows it); a file whose first column counts 0, 1, 2... is read that
    way, any other as X Y (or X Y Z) rows."""
    rows = _table(text)
    if len(rows) >= 1 and all(abs(p.x - i) < 1e-9 for i, p in enumerate(rows)):
        lines = [l for l in text.replace(";", "\n").splitlines()
                 if len([q for q in l.replace(",", " ").replace("\t", " ").split() if q]) == 3]
        if len(lines) == len(rows):
            return [V(p.y, p.z, 0.0) for p in rows]
    return rows


def _read_table(obj):
    from PySide import QtWidgets
    path, _f = QtWidgets.QFileDialog.getOpenFileName(None, "Read a pattern table", "",
                                                     "Pattern tables (*.sldptab *.txt *.csv);;All files (*)")
    if not path:
        return
    with open(path, encoding="utf-8", errors="replace") as handle:
        rows = file_points(handle.read())
    obj.Points = "\n".join("%g %g" % (p.x, p.y) for p in rows)
    obj.Document.recompute()


def _save_table(obj):
    from PySide import QtWidgets
    path, _f = QtWidgets.QFileDialog.getSaveFileName(None, "Save the pattern table", "pattern.sldptab",
                                                     "Pattern tables (*.sldptab *.txt);;All files (*)")
    if not path:
        return
    with open(path, "w", encoding="utf-8") as handle:
        for i, p in enumerate(_table(obj.Points)):
            handle.write("%d\t%g\t%g\n" % (i, p.x, p.y))


TABLE_DRIVEN = sf.Spec(
    "SWStyle_TableDrivenPattern", "Table Driven Pattern", "Table-Pattern",
    "Copies features to X-Y coordinates from a table.", "FEATURES_TABLE_DRIVEN_PATTERN", "PartDesign_LinearPattern",
    [Field("ReadFile", "button", "Read a file...", action=_read_table, box="Read a file from"),
     Field("SaveFile", "button", "Save as...", action=_save_table, box="Read a file from"),
     Field("CoordinateSystem", "pick", "Coordinate system", what="Feature", optional=True, box="Coordinate system"),
     Field("ReferencePoint", "radio", "Reference point", "Centroid", values=["Centroid", "Selected point"],
           box="Reference point"),
     Field("RefPoint", "pick", "Reference vertex", what=("Vertex", "Edge"), optional=True,
           shown=lambda o: getattr(o, "ReferencePoint", "") == "Selected point", box="Reference point"),
     *_what_fields(),
     Field("Points", "text", "Points (X Y per line; point 0 is the seed)", "0 0\n20 0\n20 20",
           tip="One point per line: X Y (or X Y Z), in mm, in the coordinate system"),
     _skip_field()] + _option_fields(),
    _table_driven)


# --------------------------------------------------------------------------- Curve Driven
def _curve(obj, field="Curve"):
    picked = sf.elements(obj, field)
    edges = []
    for _, shape in picked:
        edges += [shape] if shape.ShapeType == "Edge" else shape.Edges
    if not edges:
        return None
    return Part.Wire(Part.__sortEdges__(edges)) if len(edges) > 1 else Part.Wire(edges)


def _frame(t, n):
    """A rotation whose X is the curve's tangent and Z the face normal (or any square to the tangent)."""
    t = V(t).normalize()
    if n is None or abs(V(n).normalize().dot(t)) > 0.999:
        n = V(0, 0, 1) if abs(t.z) < 0.9 else V(1, 0, 0)
    n = V(n)
    z = (n - t * n.dot(t)).normalize()
    y = z.cross(t)
    m = App.Matrix(t.x, y.x, z.x, 0, t.y, y.y, z.y, 0, t.z, y.z, z.z, 0, 0, 0, 0, 1)
    return App.Rotation(m)


def _stations(obj, wire, count, equal, spacing, reverse):
    """(point, tangent) of each instance along the curve."""
    length = wire.Length
    closed = wire.isClosed()
    if equal:
        step = length / count if closed else (length / (count - 1) if count > 1 else 0)
    else:
        step = spacing
    edge = Part.Edge(wire.approximate(1e-4, 1e-4, 200, 3)) if len(wire.Edges) > 1 else wire.Edges[0]
    out = []
    for index in range(count):
        distance = index * step
        if distance > length + 1e-6:
            break
        distance = min(distance, length)
        along = length - distance if reverse else distance
        try:
            # the last instance sits on the curve's end: OCC can refuse the full length itself
            param = edge.getParameterByLength(min(max(along, 0.0), length * (1 - 1e-9)))
        except Exception:
            param = edge.FirstParameter if along < length / 2 else edge.LastParameter
        tangent = V(edge.tangentAt(param))
        out.append((edge.valueAt(param), -tangent if reverse else tangent))
    return out


def _curve_driven(obj, base):
    seeds = _seeds(obj, base)
    wire = _curve(obj)
    if _nothing(obj, base, seeds) or wire is None:
        return None, None
    normal_face = [s for _o, s in sf.elements(obj, "FaceNormal")] if "FaceNormal" in obj.PropertiesList else []

    def normal_at(p):
        if not normal_face:
            return None
        f = normal_face[0].Faces[0]
        u, v = f.Surface.parameter(p)
        return V(f.normalAt(u, v))

    stations = _stations(obj, wire, max(int(obj.Count), 1), obj.EqualSpacing, float(obj.Spacing), obj.Reverse)
    (s0, t0) = stations[0]
    seed_c = _center(seeds, obj, base)
    f0 = _frame(t0, normal_at(s0))
    tangent = getattr(obj, "Alignment", "Tangent to curve") in ("Tangent to curve", "Align to curve")
    transform = getattr(obj, "CurveMethod", "Transform curve") == "Transform curve"
    skips = parse_skip(getattr(obj, "Skip", "") or "")
    first = []
    for i, (p, t) in enumerate(stations):
        turn = _frame(t, normal_at(p)).multiply(f0.inverted())
        if transform:
            # Transform curve: the seed keeps its X/Y offset from the curve's start at every instance
            spot = p + (seed_c - s0)
        else:
            # Offset curve: the seed keeps its distance from the curve, the offset turning with it
            spot = p + turn.multVec(seed_c - s0)
        rot = turn if tangent else App.Rotation()
        first.append((i, App.Placement(spot, rot).multiply(App.Placement(-seed_c, App.Rotation()))))
    wire2 = _curve(obj, "Curve2") if getattr(obj, "UseDirection2", False) else None
    seconds = [(0, App.Placement())]
    if wire2 is not None:
        st2 = _stations(obj, wire2, max(int(obj.Count2), 1), obj.EqualSpacing2, float(obj.Spacing2), obj.Reverse2)
        seconds = [(j, App.Placement(p - st2[0][0], App.Rotation())) for j, (p, _t) in enumerate(st2)]
    placements = []
    for j, second in seconds:
        for i, placement in first:
            if (i + 1, j + 1) in skips:
                continue
            if j > 0 and i > 0 and getattr(obj, "SeedOnly", False):
                continue
            placements.append(second.multiply(placement))
    return _finish(obj, base, seeds, placements, skip=False)      # (i,j) skips are done above


def _dir2(name):
    return lambda o: getattr(o, "UseDirection2", False)


CURVE_DRIVEN = sf.Spec(
    "SWStyle_CurveDrivenPattern", "Curve Driven Pattern", "Curve-Pattern",
    "Copies features along a curve.", "FEATURES_CURVE_DRIVEN_PATTERN", "PartDesign_LinearPattern",
    [Field("Curve", "pick", "Pattern Direction", tip="The curve the pattern follows. Edges or a sketch to follow", what=("Edge", ""),
           many=True, box="Direction 1"),
     Field("Reverse", "bool", "Reverse direction", False, box="Direction 1"),
     Field("Count", "int", "Number of instances", 4, low=1, box="Direction 1"),
     Field("EqualSpacing", "bool", "Equal spacing", True, box="Direction 1"),
     Field("Spacing", "length", "Spacing", 10.0, shown=lambda o: not o.EqualSpacing, box="Direction 1"),
     Field("CurveMethod", "radio", "Curve method", "Transform curve", values=["Transform curve", "Offset curve"],
           box="Direction 1"),
     Field("Alignment", "radio", "Alignment method", "Tangent to curve", values=["Tangent to curve", "Align to source"],
           box="Direction 1"),
     Field("FaceNormal", "pick", "Face normal (3D curves)", what=("Face",), optional=True, box="Direction 1"),
     Field("UseDirection2", "bool", "Direction 2", False, box="Direction 2"),
     Field("Curve2", "pick", "Pattern Direction", what=("Edge", ""), many=True, optional=True,
           shown=_dir2("Curve2"), box="Direction 2", tip="The curve the pattern follows"),
     Field("Reverse2", "bool", "Reverse direction", False, shown=_dir2("Reverse2"), box="Direction 2"),
     Field("Count2", "int", "Number of instances", 2, low=1, shown=_dir2("Count2"), box="Direction 2"),
     Field("EqualSpacing2", "bool", "Equal spacing", True, shown=_dir2("EqualSpacing2"), box="Direction 2"),
     Field("Spacing2", "length", "Spacing", 10.0, shown=lambda o: _dir2("")(o) and not o.EqualSpacing2, box="Direction 2"),
     Field("SeedOnly", "bool", "Pattern seed only", False, shown=_dir2("SeedOnly"), box="Direction 2"),
     *_what_fields(),
     Field("Skip", "text", "Instances to Skip", "", tip="(i,j) pairs", box="Instances to Skip")]
    + _option_fields(vary=True),
    _curve_driven, first_pick="Curve")


# --------------------------------------------------------------------------- Fill Pattern
FILL_LAYOUTS = ["Perforation", "Circular", "Square", "Polygon"]
SEED_SHAPES = ["Circle", "Square", "Diamond", "Polygon"]


def _loops(obj, origin, along, across, reach):
    """The instance points of the Circular, Square and Polygon layouts: loops round the seed, each
    LoopSpacing further out, the instances on a loop spaced by Spacing (Target spacing) or so many a
    loop (Instances per loop)."""
    loop = float(obj.LoopSpacing)
    if loop <= 0:
        raise RuntimeError("Loop spacing must be more than 0")
    sides = {"Circular": 0, "Square": 4}.get(obj.Layout, max(3, int(obj.Sides)))
    per = obj.SpacingMode == "Instances per loop"
    points = [origin]
    k = 1
    while k * loop <= reach:
        r = k * loop
        if sides == 0:
            n = max(int(obj.PerLoop), 1) if per else max(int(round(2 * math.pi * r / float(obj.Spacing))), 1)
            for i in range(n):
                a = 2 * math.pi * i / n
                points.append(origin + along * (r * math.cos(a)) + across * (r * math.sin(a)))
        else:
            corner = r / math.cos(math.pi / sides) if sides != 4 else r * math.sqrt(2)
            verts = [origin + along * (corner * math.cos(2 * math.pi * i / sides + (math.pi / 4 if sides == 4 else 0)))
                     + across * (corner * math.sin(2 * math.pi * i / sides + (math.pi / 4 if sides == 4 else 0)))
                     for i in range(sides)]
            for i in range(sides):
                a, b = verts[i], verts[(i + 1) % sides]
                side = (b - a).Length
                n = max(int(obj.PerLoop), 1) if per else max(int(round(side / float(obj.Spacing))), 1)
                for m in range(n):
                    points.append(a + (b - a) * (m / n))
        k += 1
    return points


def _seed_cut(obj, face, centre, along, across, normal):
    """Create seed cut: a Circle, Square, Diamond or Polygon of the set size through the part at
    the seed position."""
    size = float(obj.SeedSize)
    if size <= 0:
        raise RuntimeError("The seed cut size must be more than 0")
    turn = App.Rotation(normal, float(obj.SeedRotation))
    a, c = turn.multVec(along), turn.multVec(across)
    if obj.SeedShape == "Circle":
        wire = Part.Wire(Part.makeCircle(size / 2, centre, normal))
    else:
        n = {"Square": 4, "Diamond": 4}.get(obj.SeedShape, max(3, int(obj.SeedSides)))
        start = math.pi / 4 if obj.SeedShape == "Square" else 0.0
        r = size / 2 / math.cos(math.pi / n) if obj.SeedShape != "Diamond" else size / 2
        pts = [centre + a * (r * math.cos(start + 2 * math.pi * i / n)) + c * (r * math.sin(start + 2 * math.pi * i / n))
               for i in range(n)]
        wire = Part.makePolygon(pts + pts[:1])
    depth = face.BoundBox.DiagonalLength + 1e3
    tool = Part.Face(wire)
    tool.translate(normal * (-depth / 2))
    return tool.extrude(normal * depth)


def _fill(obj, base):
    picked = sf.elements(obj, "Boundary")
    make_seed = getattr(obj, "Seed", "Selected features") == "Create seed cut"
    seeds = [] if make_seed else _seeds(obj, base)
    if not picked or (_nothing(obj, base, seeds) and not make_seed):
        return None, None
    face = picked[0][1]
    if face.ShapeType != "Face" or not isinstance(face.Surface, Part.Plane):
        raise RuntimeError("Fill Pattern needs a flat face")
    spacing = float(obj.Spacing)
    if spacing <= 0:
        raise RuntimeError("Spacing must be more than 0")
    normal = face.Surface.Axis.normalize()
    direction = [s for _o, s in sf.elements(obj, "Direction")] if "Direction" in obj.PropertiesList else []
    if direction and direction[0].ShapeType == "Edge":
        e = direction[0]
        along = e.Vertexes[-1].Point - e.Vertexes[0].Point
    else:
        first = face.Edges[0]
        along = (first.Vertexes[-1].Point - first.Vertexes[0].Point) if len(first.Vertexes) > 1 else V(1, 0, 0)
    if along.Length < 1e-9 or abs(along.normalize().dot(normal)) > 0.99:
        along = V(1, 0, 0) if abs(normal.x) < 0.9 else V(0, 1, 0)
    along = (along - normal * along.dot(normal)).normalize()
    across = normal.cross(along).normalize()
    if make_seed:
        at = _picked_point(obj, "SeedPoint") if "SeedPoint" in obj.PropertiesList else None
        origin = at if at is not None else face.CenterOfMass
        origin = origin - normal * (origin - face.Surface.Position).dot(normal)
        seeds = [(_seed_cut(obj, face, origin, along, across, normal), True)]
    else:
        origin = _center(seeds, obj, base)
        origin = origin - normal * (origin - face.Surface.Position).dot(normal)
    reach = face.BoundBox.DiagonalLength
    if obj.Layout == "Perforation":
        # rows Spacing apart along the pattern direction, each row turned by the stagger angle
        stagger = math.radians(float(obj.Angle) or 60.0)
        row = along * math.cos(stagger) + across * math.sin(stagger)
        steps = int(reach / (spacing * max(math.sin(stagger), 0.1))) + 2
        points = [origin + along * (i * spacing) + row * (j * spacing)
                  for i in range(-2 * steps, 2 * steps + 1) for j in range(-steps, steps + 1)]
    else:
        points = _loops(obj, origin, along, across, reach)
    margin = float(obj.Margin)
    kept = []
    for point in points:
        if not face.isInside(point, 1e-6, True):
            continue
        if margin > 0 and any(w.distToShape(Part.Vertex(point))[0] < margin for w in face.Wires):
            continue
        kept.append(point)
    kept.sort(key=lambda p: (p - origin).Length)
    moves = [App.Placement(p - origin, App.Rotation()) for p in kept]
    if make_seed:
        gone = {i for i, _j in parse_skip(getattr(obj, "Skip", "") or "")}
        moves = [App.Placement()] + [m for k, m in enumerate([m for m in moves if m.Base.Length > 1e-6], start=2)
                                     if k not in gone]
        cuts = []
        for m in moves:
            copy = seeds[0][0].copy()
            copy.Placement = m.multiply(copy.Placement)
            cuts.append(copy)
        return _combine(base, [], cuts)
    moves = [m for m in moves if m.Base.Length > 1e-6]
    return _finish(obj, base, seeds, moves)


def _layout(*kinds):
    return lambda o: getattr(o, "Layout", "") in kinds


def _seeding(on):
    return lambda o: (getattr(o, "Seed", "") == "Create seed cut") == on


FILL = sf.Spec(
    "SWStyle_FillPattern", "Fill Pattern", "Fill-Pattern",
    "Fills a flat face with copies of the features.", "FEATURES_FILL_PATTERN", "PartDesign_LinearPattern",
    [Field("Boundary", "pick", "Fill boundary", tip="A flat face to fill", what=("Face",), box="Fill Boundary"),
     Field("Layout", "radio", "Pattern layout", "Square", values=FILL_LAYOUTS, box="Pattern Layout"),
     Field("Spacing", "length", "Instance spacing", 10.0, box="Pattern Layout"),
     Field("Angle", "angle", "Stagger angle", 60.0, shown=_layout("Perforation"), box="Pattern Layout"),
     Field("LoopSpacing", "length", "Loop spacing", 10.0, shown=_layout("Circular", "Square", "Polygon"),
           box="Pattern Layout"),
     Field("Sides", "int", "Number of sides", 6, low=3, high=24, shown=_layout("Polygon"), box="Pattern Layout"),
     Field("SpacingMode", "radio", "Instances", "Target spacing", values=["Target spacing", "Instances per loop"],
           shown=_layout("Circular", "Square", "Polygon"), box="Pattern Layout"),
     Field("PerLoop", "int", "Instances per loop", 6, low=1,
           shown=lambda o: _layout("Circular", "Square", "Polygon")(o) and o.SpacingMode == "Instances per loop",
           box="Pattern Layout", tip="For a square or polygon layout: per side"),
     Field("Margin", "length", "Margin", 2.0, box="Pattern Layout"),
     Field("Direction", "pick", "Pattern direction", what=("Edge",), optional=True, box="Pattern Layout"),
     Field("Seed", "radio", "Features to Pattern", "Selected features", values=["Selected features", "Create seed cut"],
           box="Features to Pattern"),
     Field("SeedShape", "radio", "Seed cut", "Circle", values=SEED_SHAPES, shown=_seeding(True), box="Features to Pattern"),
     Field("SeedSize", "length", "Diameter / size", 4.0, shown=_seeding(True), box="Features to Pattern"),
     Field("SeedSides", "int", "Polygon sides", 6, low=3, high=24,
           shown=lambda o: _seeding(True)(o) and o.SeedShape == "Polygon", box="Features to Pattern"),
     Field("SeedRotation", "angle", "Rotate", 0.0, shown=_seeding(True), box="Features to Pattern"),
     Field("SeedPoint", "pick", "Vertex or sketch point", what=("Vertex",), optional=True,
           shown=_seeding(True), box="Features to Pattern", tip="Where the seed cut sits"),
     Field("Features", "pick", "Features to pattern", tip="Pick the seed features in the tree",
           what="Feature", many=True, optional=True, shown=_seeding(False), box="Features to Pattern"),
     Field("Faces", "pick", "Faces to Pattern", tip="The faces of a boss or a pocket", what=("Face",),
           many=True, optional=True, shown=_seeding(False), box="Features to Pattern"),
     Field("Bodies", "pick", "Solid/Surface Bodies to Pattern", tip="Pick a face of each body to copy",
           what=("Face", "Edge", "Vertex"), many=True, optional=True, box="Bodies"),
     _skip_field()] + _option_fields(vary=True),
    _fill, first_pick="Boundary")


# --------------------------------------------------------------------------- Linear and Circular

# Instances to Skip, Pattern seed only, a second circular direction, Geometry pattern off (the
# feature is made again at every instance, so Up To Surface and Through All ends follow the
# part there) and Vary sketch. The page (patternpm) uses FreeCAD's pattern until one of these
# is wanted, then swaps in one of these features.
def _origin_line(obj, sub):
    """An axis of the origin (or a reference axis): an infinite line along the X of its placement,
    whose edge has no vertices to take a direction from."""
    return not sub and getattr(obj, "TypeId", "") in ("App::Line", "PartDesign::Line")


def _line_dir(obj):
    """An origin axis (App::Line) runs along the X of its placement; a reference axis
    (PartDesign::Line) along its Z, as its own shape does."""
    local = V(0, 0, 1) if obj.TypeId == "PartDesign::Line" else V(1, 0, 0)
    return obj.Placement.Rotation.multVec(local).normalize()


def direction_of(obj, sub):
    """The unit direction a pick stands for: a straight edge or axis, else a flat face's normal."""
    from . import refplane
    if _origin_line(obj, sub):
        return _line_dir(obj)
    shape = refplane.shape_of(obj, sub)
    if shape.ShapeType == "Face":
        if hasattr(shape.Surface, "Axis") and not isinstance(shape.Surface, Part.Plane):
            return V(shape.Surface.Axis).normalize()
        return V(shape.normalAt(0, 0)).normalize()
    if shape.ShapeType == "Edge":
        if hasattr(shape.Curve, "Axis") and not isinstance(shape.Curve, (Part.Line, Part.LineSegment)):
            return V(shape.Curve.Axis).normalize()
        d = shape.Vertexes[-1].Point - shape.Vertexes[0].Point
        if d.Length > 1e-9:
            return d.normalize()
    raise RuntimeError("Pick a straight edge, an axis or a flat face for the direction")


def axis_of(obj, sub):
    """(point, unit direction) of a pick: a straight edge or axis, a round edge, a round face."""
    from . import refplane
    if _origin_line(obj, sub):
        return V(obj.Placement.Base), _line_dir(obj)
    shape = refplane.shape_of(obj, sub)
    if shape.ShapeType == "Face" and hasattr(shape.Surface, "Axis") and not isinstance(shape.Surface, Part.Plane):
        return V(shape.Surface.Center), V(shape.Surface.Axis).normalize()
    if shape.ShapeType == "Edge":
        if isinstance(shape.Curve, (Part.Circle, Part.ArcOfCircle)):
            return V(shape.Curve.Center), V(shape.Curve.Axis).normalize()
        d = shape.Vertexes[-1].Point - shape.Vertexes[0].Point
        if d.Length > 1e-9:
            return V(shape.Vertexes[0].Point), d.normalize()
    raise RuntimeError("Pick an axis, a straight edge, a round edge or a round face for the axis")


def parse_skip(text):
    ""

    out = set()
    for part in text.replace("(", " ").replace(")", " ").replace(";", " ").split():
        nums = [n for n in part.split(",") if n.strip()]
        try:
            if len(nums) == 1:
                out.add((int(nums[0]), 1))
            elif len(nums) >= 2:
                out.add((int(nums[0]), int(nums[1])))
        except ValueError:
            continue
    return out


def replace_feature(body, old, wanted, spec=None, name="Pattern"):
    ""


    doc = old.Document
    label = old.Label
    was_tip = body.Tip is old
    new = doc.addObject(wanted, name)
    if spec is not None and wanted == spec.type:
        sf.Feature(new, spec)
        if new.ViewObject is not None:
            sf.View(new.ViewObject)
    body.insertObject(new, old, True)
    body.removeObject(old)
    doc.removeObject(old.Name)
    new.Label = label
    if was_tip:
        body.Tip = new
    try:
        new.ViewObject.Visibility = True
    except Exception as _fw_err:
        _fw_log("patterns.py:745", _fw_err)
    return new


def format_skip(skips):
    return " ".join("(%d,%d)" % ij for ij in sorted(skips))


UP_TO_REFERENCE = "Up to reference"
SPACING_MODES = ["Spacing and instances", UP_TO_REFERENCE]


def _reach(obj, k, d, seeds, base):
    """Up to reference: how far along d the last instance sits, from the seed's reference point
    (its centroid or the seed vertex picked) to the reference picked (a vertex, edge, face or
    plane), less the offset (or plus, with Reverse offset)."""
    picks = sf.elements(obj, "Reference%d" % k)
    if not picks:
        raise RuntimeError("Select the reference geometry for Direction %d." % k)
    start = None
    if getattr(obj, "RefFrom%d" % k, "Centroid") == "Selected reference":
        start = _picked_point(obj, "SeedReference%d" % k)
    if start is None:
        start = _center(seeds, obj, base)
    source, shape = picks[0]
    if source.TypeId in ("App::Plane", "PartDesign::Plane") and shape.isNull() is False and not shape.Faces:
        shape = Part.getShape(source)
    far = None
    face = shape.Faces[0] if shape.ShapeType in ("Face", "Shell", "Compound") and shape.Faces else None
    if face is not None and isinstance(face.Surface, Part.Plane):
        n = V(face.Surface.Axis)
        if abs(d.dot(n)) > 1e-9:
            far = (V(face.Surface.Position) - start).dot(n) / d.dot(n)
    if far is None:
        # the point of the reference nearest the seed, measured along the direction
        _dist, pairs, _info = shape.distToShape(Part.Vertex(start))
        far = (pairs[0][0] - start).dot(d)
    offset = float(getattr(obj, "Offset%d" % k, 0.0))
    far = far + offset if getattr(obj, "ReverseOffset%d" % k, False) else far - offset
    if far <= 1e-7:
        raise RuntimeError("The reference for Direction %d is behind the seed: use Reverse direction." % k)
    return far


def _direction(obj, k, seeds, base):
    """(unit direction, spacing, instances) of Direction k."""
    picks = getattr(obj, "Direction%d" % k)
    if not picks:
        raise RuntimeError("Select an edge, axis or face for Direction %d." % k)
    o, subs = picks[0] if isinstance(picks, list) else picks
    d = direction_of(o, subs[0] if subs else "")
    if getattr(obj, "Reverse%d" % k):
        d = d * -1
    spacing, count = float(getattr(obj, "Spacing%d" % k)), max(int(getattr(obj, "Count%d" % k)), 1)
    if getattr(obj, "Mode%d" % k, SPACING_MODES[0]) == UP_TO_REFERENCE:
        far = _reach(obj, k, d, seeds, base)
        if getattr(obj, "SetBy%d" % k, "Set spacing") == "Set spacing":
            if spacing <= 1e-7:
                raise RuntimeError("Spacing must be more than 0")
            count = int(math.floor(far / spacing + 1e-6)) + 1
        else:
            spacing = far / (count - 1) if count > 1 else 0.0
    return d, spacing, count


def _linear_grid(obj, seeds=(), base=None):
    """[(i, j, placement)] for every instance but the seed, after Pattern seed only and the skips."""
    d1, s1, n1 = _direction(obj, 1, seeds, base)
    d2, s2, n2 = None, 0.0, 1
    if obj.UseDirection2 and obj.Direction2:
        d2, s2, n2 = _direction(obj, 2, seeds, base)
    skips = parse_skip(obj.Skip)
    out = []
    for i in range(n1):
        for j in range(n2):
            if i == 0 and j == 0:
                continue
            if obj.SeedOnly and i > 0 and j > 0:
                continue
            if (i + 1, j + 1) in skips:
                continue
            move = d1 * _spaced(obj, s1, i, 1)
            if d2 is not None:
                move = move + d2 * _spaced(obj, s2, j, 2)
            out.append((i, j, App.Placement(move, App.Rotation())))
    return out


def _spaced(obj, spacing, i, direction):
    """How far instance i sits from the seed: i spacings, each gap growing by the Instances to Vary
    spacing increment."""
    inc = float(getattr(obj, "VarySpacing%d" % direction, 0.0)) if getattr(obj, "VaryInstances", False) else 0.0
    return spacing * i + inc * i * (i - 1) / 2.0


def _circular_ring(obj):
    """[(k, placement)] for a circular pattern: k = 1.. the instance number around the axis,
    negative for the second direction."""
    picks = obj.Axis
    if not picks:
        raise RuntimeError("Select an axis, a round edge or a round face for the pattern axis.")
    o, subs = picks[0] if isinstance(picks, list) else picks
    point, axis = axis_of(o, subs[0] if subs else "")
    if obj.Reverse1:
        axis = axis * -1
    n = max(int(obj.Count1), 1)
    total = float(obj.Angle)
    if obj.EqualSpacing:
        step = total / n if abs(total - 360.0) < 1e-6 else (total / (n - 1) if n > 1 else 0.0)
    else:
        step = total
    skips = {i for i, _ in parse_skip(obj.Skip)}
    out = []
    for k in range(1, n):
        if (k + 1) in skips:
            continue
        out.append((k, App.Placement(V(0, 0, 0), App.Rotation(axis, _spaced(obj, step, k, 1)), point)))
    if obj.UseDirection2:
        n2 = max(int(obj.Count1 if obj.Symmetric else obj.Count2), 1)
        step2 = step
        total2 = float(getattr(obj, "Angle2", 0.0))
        if not obj.Symmetric and total2 > 1e-9:
            # Direction 2's own angle and spacing (0 in files made before it: as Direction 1)
            if getattr(obj, "EqualSpacing2", True):
                step2 = total2 / n2 if abs(total2 - 360.0) < 1e-6 else (total2 / (n2 - 1) if n2 > 1 else 0.0)
            else:
                step2 = total2
        for k in range(1, n2):
            if (-k - 1) in skips:
                continue
            out.append((-k, App.Placement(V(0, 0, 0), App.Rotation(axis, -_spaced(obj, step2, k, 2)), point)))
    return out


def _regrown(feature, placement):
    """The feature made again at the placement (Geometry pattern off): a Pad or Pocket whose
    sketch is moved and extruded again with the same end condition; None when it cannot be."""
    def move(shape):
        shape.Placement = placement.multiply(shape.Placement)
        return shape
    return _regrown_by(feature, move, placement.Rotation.multVec)


def _regrown_by(feature, move, move_dir, longer=0.0):
    """_regrown with the sketch moved by move(shape) and directions by move_dir(vector); longer is
    added to a Blind depth (Instances to Vary)."""
    if feature.TypeId not in ("PartDesign::Pad", "PartDesign::Pocket") or not feature.Profile:
        return None
    sketch = feature.Profile[0]
    try:
        shape = move(sketch.Shape.copy())
        closed = [w for w in shape.Wires if w.isClosed()]
        if not closed:
            return None
        try:        # a profile with a loop inside another (a ring) keeps its island, as the feature does
            face = Part.makeFace(closed, "Part::FaceMakerBullseye")
        except Exception:
            faces = [Part.Face(w) for w in closed]
            face = faces[0] if len(faces) == 1 else Part.makeCompound(faces)
        normal = sketch.getGlobalPlacement().Rotation.multVec(V(0, 0, 1)) if hasattr(sketch, "getGlobalPlacement") \
            else sketch.Placement.Rotation.multVec(V(0, 0, 1))
        normal = move_dir(normal)
        if feature.Reversed:
            normal = normal * -1
        if feature.TypeId == "PartDesign::Pocket":
            normal = normal * -1
        kind = str(feature.Type)
        length = float(feature.Length) + longer
        reach = feature.BaseFeature.Shape.BoundBox.DiagonalLength * 2 if feature.BaseFeature is not None else 1000.0
        if kind == "ThroughAll" or kind == "UpToFace" or kind == "UpToLast" or kind == "UpToFirst":
            length = reach
        elif kind == "TwoLengths":
            length = float(feature.Length) + float(feature.Length2)
            face = face.translate(normal * -float(feature.Length2))
        if length <= 0:
            return None

        # files: Midplane. One side only made the copies cut or add to one side of the sketch.
        side = str(getattr(feature, "SideType", "One side") or "One side")
        if kind == "TwoLengths":
            side = "One side"       # (both lengths are in the prism already)
        elif side == "One side" and getattr(feature, "Midplane", False):
            side = "Symmetric"
        if side == "Symmetric":
            face = face.copy().translate(normal * (-length / 2.0 if kind == "Length" else -length))
            length = length if kind == "Length" else 2 * length
        prism = face.extrude(normal * length)
        if side == "Two sides":
            kind2 = str(getattr(feature, "Type2", "Length"))
            length2 = float(getattr(feature, "Length2", 0.0)) if kind2 == "Length" else reach
            if length2 > 0:
                prism = prism.fuse(face.extrude(normal * -length2))
        if kind in ("UpToFace", "UpToLast", "UpToFirst") and not _subtractive(feature) \
                and feature.BaseFeature is not None:
            # a boss up to a face stops where it first meets the part there
            try:
                pieces = prism.cut(feature.BaseFeature.Shape).Solids
                near = [p for p in pieces if p.distToShape(face)[0] < 1e-6]
                if near:
                    prism = near[0] if len(near) == 1 else near[0].fuse(near[1:])
            except Exception as _fw_err:
                _fw_log("patterns.py:927", _fw_err)
        return prism
    except Exception:
        return None


def _apply_regrown(obj, base, placements):
    """Geometry pattern off: Up To Surface / Through All seeds are extruded again at every
    instance and stopped by the part there; anything else is a copy."""
    seeds = [f for f in (getattr(obj, "Features", None) or []) if hasattr(f, "AddSubShape")]
    seeds, regions = _fold_dressups(seeds)      # a fillet on a seed: the filleted seed is copied
    adds, cuts = [], []
    for shape, subtractive in _face_seeds(obj, base) + regions:
        for placement in placements:
            copy = shape.copy()
            copy.Placement = placement.multiply(copy.Placement)
            (cuts if subtractive else adds).append(copy)
    for placement in placements:
        for feature in seeds:
            subtractive = _subtractive(feature)
            kind = str(getattr(feature, "Type", ""))
            grown = _regrown(feature, placement) if kind in ("ThroughAll", "UpToFace", "UpToLast", "UpToFirst") else None
            if grown is None:
                if feature.AddSubShape.isNull():
                    continue
                grown = feature.AddSubShape.copy()
                grown.Placement = feature.Placement.multiply(grown.Placement)
                grown.Placement = placement.multiply(grown.Placement)
            elif kind in ("UpToFace", "UpToLast", "UpToFirst") and not subtractive:
                # a boss up to a face: keep what reaches the part, as a rebuilt feature would
                pass
            (cuts if subtractive else adds).append(grown)
    return _combine(base, adds, cuts)


def _sketch_moved(sketch, placement):
    """The seed sketch solved again with its plane moved by placement (Vary sketch): the sketch's
    relations to model edges hold at the new place, so its shape can change there. The sketch is put
    back as it was. Returns its edges (body coordinates) and its normal there."""
    old_offset = App.Placement(sketch.AttachmentOffset)
    old_place = App.Placement(sketch.Placement)
    attached = sketch.MapMode != "Deactivated" and bool(sketch.AttachmentSupport)
    try:
        if attached:
            support = old_place.multiply(old_offset.inverse())
            sketch.AttachmentOffset = support.inverse().multiply(placement.multiply(old_place))
        else:
            sketch.Placement = placement.multiply(old_place)
        sketch.recompute()
        if "Invalid" in sketch.State or sketch.Shape.isNull() or not sketch.Shape.Edges:
            return None, None
        if hasattr(sketch, "solve") and sketch.solve() != 0:
            return None, None
        shape = sketch.Shape.copy()
        normal = sketch.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        return shape, normal
    finally:
        if attached:
            sketch.AttachmentOffset = old_offset
        else:
            sketch.Placement = old_place
        sketch.recompute()
        sketch.purgeTouched()


def _extruded_like(feature, profile, normal):
    """profile (a moved sketch's edges) extruded the way the seed Pad / Pocket is (Blind, Mid Plane,
    two lengths); None for any other end condition."""
    kind = str(getattr(feature, "Type", ""))
    if kind not in ("Length", "TwoLengths") or feature.TypeId not in ("PartDesign::Pad", "PartDesign::Pocket"):
        return None
    wires = [w for w in profile.Wires if w.isClosed()]
    if not wires:
        return None
    face = Part.makeFace(wires, "Part::FaceMakerBullseye")
    custom = getattr(feature, "UseCustomVector", False)
    way = App.Vector(feature.Direction) if custom else App.Vector(normal)
    if way.Length < 1e-12:
        return None
    way.normalize()
    if feature.TypeId == "PartDesign::Pocket" and not custom:
        way = way * -1
    if getattr(feature, "Reversed", False):
        way = way * -1
    length = float(feature.Length)
    back = float(getattr(feature, "Length2", 0.0)) if kind == "TwoLengths" else 0.0
    if getattr(feature, "Midplane", False) and kind == "Length":
        back = length / 2.0
        length = length / 2.0
    solid = face.extrude(way * (length + back))
    if back:
        solid.translate(way * -back)
    return solid


def _apply_varied_sketch(obj, base, placements):
    ""




    seeds = [f for f in (getattr(obj, "Features", None) or []) if hasattr(f, "AddSubShape")]
    adds, cuts = [], []
    for shape, subtractive in _face_seeds(obj, base):
        for placement in placements:
            copy = shape.copy()
            copy.Placement = placement.multiply(copy.Placement)
            (cuts if subtractive else adds).append(copy)
    for feature in seeds:
        subtractive = _subtractive(feature)
        profile = getattr(feature, "Profile", None)
        sketch = profile[0] if isinstance(profile, (list, tuple)) and profile else profile
        if sketch is not None and getattr(sketch, "TypeId", "") != "Sketcher::SketchObject":
            sketch = None
        for number, placement in enumerate(placements, start=2):
            grown = None
            if sketch is not None:
                moved, normal = _sketch_moved(sketch, placement)
                if moved is None:
                    raise RuntimeError("Vary sketch: the sketch of %s cannot be solved at instance %d"
                                       % (feature.Label, number))
                grown = _extruded_like(feature, moved, normal)
            if grown is None:
                kind = str(getattr(feature, "Type", ""))
                grown = _regrown(feature, placement) if kind in ("ThroughAll", "UpToFace", "UpToLast", "UpToFirst") else None
            if grown is None:
                if feature.AddSubShape.isNull():
                    continue
                grown = feature.AddSubShape.copy()
                grown.Placement = feature.Placement.multiply(grown.Placement)
                grown.Placement = placement.multiply(grown.Placement)
            (cuts if subtractive else adds).append(grown)
    return _combine(base, adds, cuts)


def _vary_check(obj):
    if obj.VarySketch and obj.GeometryPattern:
        raise RuntimeError("A pattern with variant sketch option is not suitable for geometry pattern.")


def _varied(obj, base, grid):
    """Instances to Vary: each instance's seed made again with its depth and size changed by the
    increments times its place in Direction 1 and Direction 2 (Pad and Pocket seeds; any other seed
    is copied as it is)."""
    adds, cuts = [], []
    for i, j, placement in grid:
        longer = float(obj.VaryDepth1) * i + float(obj.VaryDepth2) * j
        grow = 1.0 + (float(obj.VaryScale1) * i + float(obj.VaryScale2) * j) / 100.0
        if grow <= 0:
            raise RuntimeError("The size increment shrinks an instance to nothing")
        for shape, subtractive in _face_seeds(obj, base):
            copy = shape.copy()
            copy.Placement = placement.multiply(copy.Placement)
            (cuts if subtractive else adds).append(copy)
        for feature in [f for f in (getattr(obj, "Features", None) or []) if hasattr(f, "AddSubShape")]:
            def move(shape, grow=grow, placement=placement):
                if abs(grow - 1.0) > 1e-12:
                    shape = shape.copy()
                    shape.scale(grow, shape.BoundBox.Center)    # keeps circles circles
                shape.Placement = placement.multiply(shape.Placement)
                return shape
            grown = _regrown_by(feature, move, placement.Rotation.multVec, longer)
            if grown is None:
                if feature.AddSubShape.isNull():
                    continue
                grown = feature.AddSubShape.copy()
                grown.Placement = placement.multiply(feature.Placement.multiply(grown.Placement))
            (cuts if _subtractive(feature) else adds).append(grown)
    return _combine(base, adds, cuts)


def _linear(obj, base):
    _vary_check(obj)
    seeds = _seeds(obj, base)
    if _nothing(obj, base, seeds):
        return None, None
    grid = _linear_grid(obj, seeds, base)
    placements = [p for _, _, p in grid]
    if getattr(obj, "VaryInstances", False):
        return _with_bodies(obj, base, _varied(obj, base, grid), placements)
    if obj.VarySketch:
        return _with_bodies(obj, base, _apply_varied_sketch(obj, base, placements), placements)
    if not obj.GeometryPattern:
        return _with_bodies(obj, base, _apply_regrown(obj, base, placements), placements)
    return _with_bodies(obj, base, _apply(base, seeds, placements), placements)


def _circular(obj, base):
    _vary_check(obj)
    seeds = _seeds(obj, base)
    if _nothing(obj, base, seeds):
        return None, None
    ring = _circular_ring(obj)
    placements = [p for _, p in ring]
    if getattr(obj, "VaryInstances", False):

        made = _varied(obj, base, [(k, 0, p) if k > 0 else (0, -k, p) for k, p in ring])
        return _with_bodies(obj, base, made, placements)
    if obj.VarySketch:
        return _with_bodies(obj, base, _apply_varied_sketch(obj, base, placements), placements)
    if not obj.GeometryPattern:
        return _with_bodies(obj, base, _apply_regrown(obj, base, placements), placements)
    return _with_bodies(obj, base, _apply(base, seeds, placements), placements)


def _up_to(k):
    return lambda o: getattr(o, "Mode%d" % k, "") == UP_TO_REFERENCE


def _spacing_shown(k):
    return lambda o: not _up_to(k)(o) or getattr(o, "SetBy%d" % k, "") == "Set spacing"


def _count_shown(k):
    return lambda o: not _up_to(k)(o) or getattr(o, "SetBy%d" % k, "") == "Set number of instances"


LINEAR = sf.Spec(
    "SWStyle_LinearPatternFeature", "Linear Pattern", "LPattern",
    "Copies features along one or two directions.", "FEATURES_LINEAR_PATTERN", "PartDesign_LinearPattern",
    [Field("Direction1", "pick", "Direction 1", tip="An edge, axis or flat face", what=("Edge", "Face"), box="Direction 1"),
     Field("Reverse1", "bool", "Reverse direction", False, box="Direction 1"),
     Field("Mode1", "radio", "Spacing", SPACING_MODES[0], values=SPACING_MODES, box="Direction 1"),
     Field("Reference1", "pick", "Reference geometry", tip="A vertex, edge, face or plane the pattern runs up to",
           what=("Vertex", "Edge", "Face"), optional=True, shown=_up_to(1), box="Direction 1"),
     Field("Offset1", "length", "Offset distance", 0.0, shown=_up_to(1), box="Direction 1"),
     Field("ReverseOffset1", "bool", "Reverse offset", False, shown=_up_to(1), box="Direction 1"),
     Field("RefFrom1", "radio", "Seed reference", "Centroid", values=["Centroid", "Selected reference"],
           shown=_up_to(1), box="Direction 1"),
     Field("SeedReference1", "pick", "Seed reference vertex", what=("Vertex", "Edge"), optional=True,
           shown=lambda o: _up_to(1)(o) and getattr(o, "RefFrom1", "") == "Selected reference", box="Direction 1"),
     Field("SetBy1", "radio", "Instances", "Set spacing", values=["Set spacing", "Set number of instances"],
           shown=_up_to(1), box="Direction 1"),
     Field("Spacing1", "length", "Spacing", 10.0, shown=_spacing_shown(1), box="Direction 1"),
     Field("Count1", "int", "Number of instances", 2, shown=_count_shown(1), box="Direction 1"),
     Field("UseDirection2", "bool", "Direction 2", False, box="Direction 2"),
     Field("Direction2", "pick", "Direction 2", tip="An edge, axis or flat face", what=("Edge", "Face"), box="Direction 2", optional=True),
     Field("Reverse2", "bool", "Reverse direction", False, box="Direction 2"),
     Field("Mode2", "radio", "Spacing", SPACING_MODES[0], values=SPACING_MODES, box="Direction 2"),
     Field("Reference2", "pick", "Reference geometry", tip="A vertex, edge, face or plane the pattern runs up to",
           what=("Vertex", "Edge", "Face"), optional=True, shown=_up_to(2), box="Direction 2"),
     Field("Offset2", "length", "Offset distance", 0.0, shown=_up_to(2), box="Direction 2"),
     Field("ReverseOffset2", "bool", "Reverse offset", False, shown=_up_to(2), box="Direction 2"),
     Field("RefFrom2", "radio", "Seed reference", "Centroid", values=["Centroid", "Selected reference"],
           shown=_up_to(2), box="Direction 2"),
     Field("SeedReference2", "pick", "Seed reference vertex", what=("Vertex", "Edge"), optional=True,
           shown=lambda o: _up_to(2)(o) and getattr(o, "RefFrom2", "") == "Selected reference", box="Direction 2"),
     Field("SetBy2", "radio", "Instances", "Set spacing", values=["Set spacing", "Set number of instances"],
           shown=_up_to(2), box="Direction 2"),
     Field("Spacing2", "length", "Spacing", 10.0, shown=_spacing_shown(2), box="Direction 2"),
     Field("Count2", "int", "Number of instances", 2, shown=_count_shown(2), box="Direction 2"),
     Field("SeedOnly", "bool", "Pattern seed only", False, box="Direction 2"),
     *_what_fields(),
     Field("Skip", "text", "Instances to Skip", "", tip="(i,j) pairs", box="Instances to Skip"),
     Field("VaryInstances", "bool", "Instances to Vary", False, box="Instances to Vary"),
     Field("VarySpacing1", "distance", "Direction 1 spacing increment", 0.0, box="Instances to Vary"),
     Field("VaryDepth1", "distance", "Direction 1 depth increment", 0.0, box="Instances to Vary", tip="Added to the seed extrude's depth at each instance"),
     Field("VaryScale1", "float", "Direction 1 size increment (%)", 0.0, low=-99.0, high=1000.0, box="Instances to Vary"),
     Field("VarySpacing2", "distance", "Direction 2 spacing increment", 0.0, box="Instances to Vary"),
     Field("VaryDepth2", "distance", "Direction 2 depth increment", 0.0, box="Instances to Vary", tip="Added to the seed extrude's depth at each instance"),
     Field("VaryScale2", "float", "Direction 2 size increment (%)", 0.0, low=-99.0, high=1000.0, box="Instances to Vary"),
     Field("VarySketch", "bool", "Vary sketch", False, box="Options"),
     Field("GeometryPattern", "bool", "Geometry pattern", True, box="Options"),
     Field("Propagate", "bool", "Propagate visual properties", True, box="Options")],
    _linear, first_pick="Direction1")

CIRCULAR = sf.Spec(
    "SWStyle_CircularPatternFeature", "Circular Pattern", "CirPattern",
    "Copies features around an axis.", "FEATURES_CIRCULAR_PATTERN", "PartDesign_PolarPattern",
    [Field("Axis", "pick", "Pattern Axis", tip="An axis, a straight or round edge, or a round face", what=("Edge", "Face"), box="Direction 1"),
     Field("Reverse1", "bool", "Reverse direction", False, box="Direction 1"),
     Field("EqualSpacing", "bool", "Equal spacing", True, box="Direction 1"),
     Field("Angle", "angle", "Angle", 360.0, box="Direction 1"),
     Field("Count1", "int", "Number of instances", 4, box="Direction 1"),
     Field("UseDirection2", "bool", "Direction 2", False, box="Direction 2"),
     Field("Symmetric", "bool", "Symmetric", False, box="Direction 2"),
     Field("EqualSpacing2", "bool", "Equal spacing", True, shown=lambda o: not o.Symmetric, box="Direction 2"),
     Field("Angle2", "angle", "Angle", 360.0, shown=lambda o: not o.Symmetric, box="Direction 2", legacy=0.0),
     Field("Count2", "int", "Number of instances", 2, shown=lambda o: not o.Symmetric, box="Direction 2"),
     *_what_fields(),
     Field("Skip", "text", "Instances to Skip", "", tip="Instance numbers", box="Instances to Skip"),
     Field("VaryInstances", "bool", "Instances to Vary", False, box="Instances to Vary"),
     Field("VarySpacing1", "angle", "Direction 1 spacing increment", 0.0, box="Instances to Vary"),
     Field("VaryDepth1", "distance", "Direction 1 depth increment", 0.0, box="Instances to Vary", tip="Added to the seed extrude's depth at each instance"),
     Field("VaryScale1", "float", "Direction 1 size increment (%)", 0.0, low=-99.0, high=1000.0, box="Instances to Vary"),
     Field("VarySpacing2", "angle", "Direction 2 spacing increment", 0.0, box="Instances to Vary"),
     Field("VaryDepth2", "distance", "Direction 2 depth increment", 0.0, box="Instances to Vary", tip="Added to the seed extrude's depth at each instance"),
     Field("VaryScale2", "float", "Direction 2 size increment (%)", 0.0, low=-99.0, high=1000.0, box="Instances to Vary"),
     Field("VarySketch", "bool", "Vary sketch", False, box="Options"),
     Field("GeometryPattern", "bool", "Geometry pattern", True, box="Options"),
     Field("Propagate", "bool", "Propagate visual properties", True, box="Options")],
    _circular, first_pick="Axis")


# --------------------------------------------------------------------------- Mirror
UP_TO_KINDS = ("ThroughAll", "UpToFace", "UpToLast", "UpToFirst")


def mirror_plane(obj, sub):
    """(point, normal) of a mirror face, or an origin / datum plane."""
    if sub:
        f = obj.Shape.getElement(sub)
        return App.Vector(f.Surface.Position), App.Vector(f.normalAt(0, 0)).normalize()
    if obj.TypeId in ("App::Plane", "PartDesign::Plane"):
        place = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
        return App.Vector(place.Base), place.Rotation.multVec(V(0, 0, 1))
    f = Part.getShape(obj).Faces[0]
    return App.Vector(f.Surface.Position), App.Vector(f.normalAt(0, 0)).normalize()


def _planes_of(obj, field):
    out = []
    for item in (getattr(obj, field, None) or []):
        source, subs = item
        subs = subs if isinstance(subs, (list, tuple)) else [subs]
        for sub in (subs or [""]):
            out.append(mirror_plane(source, sub))
    return out


def _reflect(v, point, normal):
    return v - normal * (2 * v.dot(normal))


def _tool_shape(feature):
    if feature.AddSubShape.isNull():
        return None
    shape = feature.AddSubShape.copy()
    shape.Placement = feature.Placement.multiply(shape.Placement)
    return shape


def faces_solid(faces):
    ""

    shell = Part.Shell(faces)
    free = shell.getFreeEdges().Edges
    lids = []
    for group in Part.sortEdges(free):
        wire = Part.Wire(group)
        try:
            lids.append(Part.Face(wire))
        except Exception:
            lids.append(Part.makeFilledFace(wire.Edges))
    shell = Part.Shell(faces + lids)
    solid = Part.Solid(shell)
    try:
        solid.fix(1e-6, 1e-6, 1e-6)
    except Exception as _fw_err:
        _fw_log("patterns.py:1171", _fw_err)
    if not solid.isValid() or solid.Volume < 1e-9:
        solid = Part.makeSolid(shell)
        if solid.Volume < 0:
            solid.reverse()
    if not solid.isValid() or solid.Volume < 1e-9:
        raise RuntimeError("The faces do not close off a solid to mirror.")
    return solid


def _mirror(obj, base):
    planes = _planes_of(obj, "Plane")
    if not planes:
        return None, None
    point, normal = planes[0]
    second = _planes_of(obj, "Plane2")

    def about(shape, p, n):
        return shape.mirror(p, n)

    tools = []          # (shape to copy, subtractive)
    for feature in [f for f in (obj.Features or []) if not hasattr(f, "AddSubShape") and getattr(f, "Originals", None)]:

        # seeds plus the material its copies added or took away
        for seed in [o for o in feature.Originals if hasattr(o, "AddSubShape")]:
            shape = _tool_shape(seed)
            if shape is not None:
                tools.append((shape, _subtractive(seed), False))
        before = getattr(feature, "BaseFeature", None)
        if before is not None and not before.Shape.isNull() and not feature.Shape.isNull():
            taken, added = before.Shape.cut(feature.Shape), feature.Shape.cut(before.Shape)
            if taken.Volume > 1e-9:
                tools.append((taken, True, False))
            if added.Volume > 1e-9:
                tools.append((added, False, False))
    for feature in [f for f in (obj.Features or []) if hasattr(f, "AddSubShape")]:
        grown = None
        if not obj.GeometryPattern and str(getattr(feature, "Type", "")) in UP_TO_KINDS:
            grown = _regrown_by(feature, lambda sh: about(sh, point, normal), lambda d: _reflect(d, point, normal))
            if grown is not None:
                tools.append((grown, _subtractive(feature), feature))
                continue
        shape = _tool_shape(feature)
        if shape is not None:
            tools.append((shape, _subtractive(feature), False))
    faces = [shape for _, shape in sf.elements(obj, "Faces") if shape.ShapeType == "Face"]
    if faces:
        solid = faces_solid(faces)
        # a boss's faces close off material (the copy adds); a pocket's close off a hole (it cuts)
        hollow = solid.common(base).Volume < solid.Volume * 0.5
        tools.append((solid, hollow, False))
    if obj.Whole:
        tools.append((base, False, False))
    base, made = _mirror_bodies(obj, base, lambda sh: about(sh, point, normal))
    adds, cuts = [], []
    for shape, subtractive, grown in tools:
        copies = [shape if grown else about(shape, point, normal)]
        for p2, n2 in second:
            if grown is not False:
                # (shape is the copy already made about the first plane: the seed is made again
                # about the second one, which was missing; the copy of the copy follows below)
                again = _regrown_by(grown, lambda sh, p2=p2, n2=n2: about(sh, p2, n2),
                                    lambda d, n2=n2: _reflect(d, p2, n2))
                if again is None:
                    again = _tool_shape(grown)
                    again = about(again, p2, n2) if again is not None else None
                if again is not None:
                    copies.append(again)
            else:
                copies.append(about(shape, p2, n2))
            if not getattr(obj, "SeedOnly", False):     # Mirror seed only: no copy of the first copy (pkg125)
                copies.append(about(copies[0], p2, n2))
        (cuts if subtractive else adds).extend(copies)
    result, tool = _combine(base, adds, cuts)
    if made and result is None:
        return base, Part.makeCompound(made)
    if made:
        tool = Part.makeCompound(made + ([tool] if tool is not None else []))
    return result, tool


def _mirror_bodies(obj, base, about):
    ""


    picked = _bodies(obj, base)
    if not picked:
        return base, []
    merge = getattr(obj, "MergeSolids", True)
    out, made = [], []
    for solid in base.Solids:
        if not any(solid.isSame(p) for p in picked):
            out.append(solid)
            continue
        copy = about(solid)
        made.append(copy)
        if merge and solid.distToShape(copy)[0] < 1e-6:
            fused = solid.fuse(copy)
            try:
                fused = fused.removeSplitter()
            except Exception as _fw_err:
                _fw_log("patterns.py:1261", _fw_err)
            out.extend(fused.Solids)
        else:
            out.extend([solid] + list(copy.Solids))
    return Part.makeCompound(out), made


MIRROR = sf.Spec(
    "SWStyle_MirrorFeature", "Mirror", "Mirror",
    "Mirrors features, faces or the body about a face or plane.", "FEATURES_MIRROR", "PartDesign_Mirrored",
    [Field("Plane", "pick", "Mirror Face/Plane", tip="A flat face or a plane", what=("Face",), box="Mirror Face/Plane"),
     Field("Plane2", "pick", "Secondary Mirror Face/Plane", tip="A second flat face or plane: the copies are mirrored about it too",
           what=("Face",), box="Secondary Mirror Face/Plane", optional=True),
     Field("SeedOnly", "bool", "Mirror seed only", False, box="Secondary Mirror Face/Plane"),
     Field("Features", "pick", "Features to Mirror", tip="Pick the features in the tree", what="Feature", many=True, optional=True),
     Field("Faces", "pick", "Faces to Mirror", tip="The faces of a boss or a pocket", what=("Face",), many=True, optional=True),
     Field("Whole", "bool", "Bodies to Mirror", False),
     Field("Bodies", "pick", "Solid Bodies to Mirror", tip="Pick a face of each body to mirror",
           what=("Face", "Edge", "Vertex"), many=True, optional=True),
     Field("MergeSolids", "bool", "Merge solids", True),
     Field("GeometryPattern", "bool", "Geometry pattern", False, box="Options"),
     Field("Propagate", "bool", "Propagate visual properties", True, box="Options")],
    _mirror, first_pick="Plane")


ALL = [CURVE_DRIVEN, SKETCH_DRIVEN, TABLE_DRIVEN, FILL, LINEAR, CIRCULAR, MIRROR]


class MirrorCommand(sf.Command):
    ""



    def IsActive(self):
        import FreeCADGui as Gui
        doc = App.ActiveDocument
        if doc is None or Gui.Control.activeDialog():
            return False
        return sf.ready(self.spec, doc) or bool(self._free(doc))

    @staticmethod
    def _free(doc):
        from . import mirrorpm
        body = sf.body_of(doc)
        return [o for o in doc.Objects if mirrorpm.free_body(o, body)]

    def Activated(self):
        import FreeCADGui as Gui
        doc = App.ActiveDocument
        body = sf.body_of(doc)
        if body is not None and sf.has_solid(body):
            picks = []
            for entry in Gui.Selection.getSelectionEx(doc.Name):
                for sub in (entry.SubElementNames or ("",)):
                    picks.append((entry.Object, sub))
            result = super().Activated()
            if picks:
                self._feed_later(picks)
            return result
        Gui.runCommand("SWStyle_Mirror", 0)

    @staticmethod
    def _feed_later(picks, tries=10):
        ""


        from PySide import QtCore

        def feed():
            import FreeCADGui as Gui
            from . import mirrorpm
            try:
                panel = Gui.Control.activeDialog() and getattr(mirrorpm, "_current", None)
            except Exception:
                panel = None
            if panel is None or not hasattr(panel, "_add"):
                if tries > 0:
                    MirrorCommand._feed_later(picks, tries - 1)
                return
            if panel.plane is not None:
                return
            try:
                for obj, sub in picks:
                    panel._add(obj, sub)
                panel.update()
                Gui.Selection.clearSelection()
            except Exception as error:
                App.Console.PrintLog("FreeCAD Mirror: pre-picks: %r\n" % error)
        QtCore.QTimer.singleShot(100, feed)


# --------------------------------------------------------------------------- Propagate visual properties
def _app_colour(app):
    return tuple(round(c, 4) for c in tuple(app.DiffuseColor)[:3])


def recolour(obj):
    """Propagate visual properties on every rebuild (not only when the PM closes): the faces of the
    copies (inside the boxes of the feature's AddSubShape solids) take the seed features' colour,
    the rest the part's. Off, the feature is one colour again."""
    vobj = getattr(obj, "ViewObject", None)
    if vobj is None or "Propagate" not in obj.PropertiesList or obj.Shape.isNull():
        return False
    try:
        apps = list(vobj.ShapeAppearance)
    except Exception:
        return False
    sources = [o for o in (getattr(obj, "Features", None) or getattr(obj, "Originals", None) or [])]
    if "Faces" in obj.PropertiesList:
        sources += [o for o, _subs in (obj.Faces or [])]
    # the part's colour: the feature before, going back past the seeds (a seed is often just before)
    base_obj = getattr(obj, "BaseFeature", None)
    seen = 0
    while base_obj is not None and base_obj in sources and seen < 100:
        base_obj = getattr(base_obj, "BaseFeature", None)
        seen += 1
    try:
        base_app = base_obj.ViewObject.ShapeAppearance[0] if base_obj is not None else apps[0]
    except Exception:
        base_app = apps[0]
    if not obj.Propagate:
        if len(apps) > 1 or _app_colour(apps[0]) != _app_colour(base_app):
            vobj.ShapeAppearance = [base_app]
        return True
    colour = None
    for src in sources:
        try:
            app = src.ViewObject.ShapeAppearance[0]
        except Exception:
            continue
        if _app_colour(app) != _app_colour(base_app):
            colour = app
            break
    if colour is None:
        if len(apps) > 1:
            vobj.ShapeAppearance = [base_app]
        return True
    tool = getattr(obj, "AddSubShape", None)
    if tool is None or tool.isNull():
        return False
    tool = tool.copy()
    tool.Placement = obj.Placement.multiply(tool.Placement)
    pieces = list(tool.Solids or [tool])
    for src in sources:                 # the seeds themselves (AddSubShape holds only the copies)
        seed = getattr(src, "AddSubShape", None)
        if seed is not None and not seed.isNull():
            seed = seed.copy()
            seed.Placement = src.Placement.multiply(seed.Placement)
            pieces += list(seed.Solids or [seed])
    boxes = []
    for piece in pieces:
        box = piece.BoundBox
        box.enlarge(1e-3)
        boxes.append((box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax))

    def inside(face):
        fb = face.BoundBox          # a copy's face lies wholly in its copy's box (cheaper than CenterOfMass)
        for x0, x1, y0, y1, z0, z1 in boxes:
            if x0 <= fb.XMin and fb.XMax <= x1 and y0 <= fb.YMin and fb.YMax <= y1 and z0 <= fb.ZMin and fb.ZMax <= z1:
                return True
        return False
    want = [colour if inside(f) else base_app for f in obj.Shape.Faces]
    if len(want) != len(apps) or any(_app_colour(a) != _app_colour(b) for a, b in zip(want, apps)):
        vobj.ShapeAppearance = want
    return True


class _Recolour:
    """Re-applies Propagate visual properties after each rebuild of a pattern or mirror (a Count
    change, a seed edit): the new instances keep the seed's colour."""

    def __init__(self):
        self.pending = set()

    def slotRecomputedObject(self, obj):
        try:
            if "Propagate" not in obj.PropertiesList:
                return
            key = (obj.Document.Name, obj.Name)
        except Exception:
            return
        if key in self.pending:
            return
        self.pending.add(key)
        try:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda k=key: self.run(k))
        except Exception:
            self.run(key)

    def run(self, key):
        self.pending.discard(key)
        try:
            doc = App.getDocument(key[0])
            obj = doc.getObject(key[1]) if doc is not None else None
            if obj is not None:
                recolour(obj)
        except Exception as _fw_err:
            _fw_log("patterns.py:1459", _fw_err)


_OBSERVER = []


def watch_colours():
    if not _OBSERVER:
        _OBSERVER.append(_Recolour())
        App.addDocumentObserver(_OBSERVER[0])


# --------------------------------------------------------------------------- FreeCAD's patterns that would do nothing
# FreeCAD's LinearPattern, PolarPattern and Mirrored copy nothing of a Pad or Pocket made from


STOCK_PATTERNS = ("PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::Mirrored")


def odd_profile(feature):
    """True for a Pad / Pocket whose profile is not a sketch (FreeCAD's patterns skip it)."""
    prof = getattr(feature, "Profile", None)
    src = prof[0] if isinstance(prof, (list, tuple)) and prof else prof
    if src is None or not hasattr(feature, "AddSubShape"):
        return False
    return src.TypeId != "Sketcher::SketchObject"


def _link(value):
    """(obj, [subs]) of a FreeCAD link property value, or None."""
    if not value:
        return None
    if isinstance(value, tuple) and len(value) == 2 and not isinstance(value[0], tuple):
        o, subs = value
    else:
        o, subs = value[0] if isinstance(value, list) else value, [""]
    subs = list(subs) if isinstance(subs, (list, tuple)) else [subs]
    return o, subs or [""]


def _stock_values(old):
    ""
    originals = [f for f in old.Originals]
    if old.TypeId == "PartDesign::Mirrored":
        o, subs = _link(old.MirrorPlane)
        return MIRROR, {"Plane": [(o, subs)], "Features": originals}
    count = max(int(old.Occurrences), 1)
    mode = str(getattr(old, "Mode", "Extent"))
    if old.TypeId == "PartDesign::LinearPattern":
        o, subs = _link(old.Direction)
        if mode == "Spacing":
            spacing = float(old.Offset)
        else:
            spacing = float(old.Length) / (count - 1) if count > 1 else float(old.Length)
        return LINEAR, {"Direction1": [(o, subs)], "Reverse1": bool(old.Reversed), "Spacing1": spacing,
                        "Count1": count, "Features": originals}
    o, subs = _link(old.Axis)
    if mode == "Spacing":
        return CIRCULAR, {"Axis": [(o, subs)], "Reverse1": bool(old.Reversed), "EqualSpacing": False,
                          "Angle": float(old.Offset), "Count1": count, "Features": originals}
    return CIRCULAR, {"Axis": [(o, subs)], "Reverse1": bool(old.Reversed), "EqualSpacing": True,
                      "Angle": float(old.Angle), "Count1": count, "Features": originals}


def own_for_stock(old):
    ""
    from . import refplane
    spec, values = _stock_values(old)
    body = refplane.body_of(old.Document)
    for b in old.Document.Objects:
        if b.TypeId == "PartDesign::Body" and old in b.Group:
            body = b
    new = replace_feature(body, old, spec.type, spec, spec.internal)
    for name, value in values.items():
        try:
            setattr(new, name, value)
        except Exception:
            if name == "Features":
                setattr(new, name, [(f, [""]) for f in value])
            else:
                raise
    new.touch()
    return new


def _in_edit(obj):
    try:
        import FreeCADGui as Gui
        vp = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
        return vp is not None and vp.Object is obj
    except Exception:
        return False


class _StockWatch:
    ""


    def __init__(self):
        self.busy = False

    def slotRecomputedDocument(self, doc):
        if self.busy:
            return
        try:
            todo = [o for t in STOCK_PATTERNS for o in doc.findObjects(t)
                    if o.TypeId == t and any(odd_profile(f) for f in o.Originals)]
        except Exception:
            return
        if not todo:
            return
        from PySide import QtCore
        name = doc.Name
        QtCore.QTimer.singleShot(300, lambda: self._swap(name))

    def _swap(self, name, tries=0):
        try:
            doc = App.getDocument(name)
        except Exception:
            return
        todo = [o for o in doc.Objects if o.TypeId in STOCK_PATTERNS and any(odd_profile(f) for f in o.Originals)]
        if not todo:
            return
        if any(_in_edit(o) for o in todo):
            if tries < 240:
                from PySide import QtCore
                QtCore.QTimer.singleShot(500, lambda: self._swap(name, tries + 1))
            return
        self.busy = True
        try:
            for o in todo:
                try:
                    own_for_stock(o)
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: %s kept as FreeCAD's pattern: %s\n" % (o.Label, error))
            doc.recompute()
        finally:
            self.busy = False


_STOCK = []


def watch_stock():
    if not _STOCK:
        _STOCK.append(_StockWatch())
        App.addDocumentObserver(_STOCK[0])


def register():
    import FreeCADGui as Gui
    watch_colours()
    watch_stock()
    for spec in ALL:
        if spec is MIRROR:
            try:
                if spec.command not in Gui.listCommands():
                    Gui.addCommand(spec.command, MirrorCommand(spec))
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Mirror command not added (%s)\n" % error)
            continue
        sf.register(spec)
