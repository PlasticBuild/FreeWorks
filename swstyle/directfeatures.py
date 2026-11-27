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


def _fuse(base, tool):
    if base is None or base.isNull():
        return tool
    return base.fuse(tool, 1e-6)


def _grow(solid, distance):
    """A closed solid grown outwards by distance (each solid of a compound on its own)."""
    if len(getattr(solid, "Solids", [])) > 1:
        return Part.makeCompound([_grow(s, distance) for s in solid.Solids])
    try:
        grown = solid.makeOffsetShape(distance, 1e-6, False, False, 0, 0, False)
    except Exception:
        # OCC fails to offset some placed solids (a Part Sphere moved by its Placement): offset it where
        # it was made, then put it back
        moved = solid.copy()
        place = moved.Placement
        moved.Placement = App.Placement()
        grown = moved.makeOffsetShape(distance, 1e-6, False, False, 0, 0, False)
        grown.Placement = place.multiply(grown.Placement)
    if grown.ShapeType != "Solid" and not grown.Solids:
        grown = Part.Solid(grown.Shells[0] if grown.Shells else Part.Shell(grown.Faces))
    return grown


def _big_face(face, base):
    """A planar face made large enough to cross the whole part."""
    surface = face.Surface
    if not isinstance(surface, Part.Plane):
        return face
    box = base.BoundBox
    size = max(box.DiagonalLength, 1.0) * 2
    point = surface.projectPoint(box.Center) if hasattr(surface, "projectPoint") else surface.Position
    plane = Part.Plane(point, surface.Axis)
    u, v = plane.parameter(point)
    return plane.toShape(u - size, u + size, v - size, v + size)


def _normal(face, point):
    try:
        u, v = face.Surface.parameter(point)
        normal = face.normalAt(u, v) if face.isValid() else face.Surface.normal(u, v)
    except Exception:
        normal = face.Surface.normal(*face.Surface.parameter(point))
    return normal


# --------------------------------------------------------------------------- Scale
def _scale(obj, base):
    frame = App.Placement()
    if obj.About == "Origin":
        center = V(0, 0, 0)
    elif obj.About == "Coordinate System":
        cs = getattr(obj, "CoordinateSystem", None)
        if cs is None:
            raise RuntimeError("Pick the coordinate system to scale about")
        frame = cs.getGlobalPlacement() if hasattr(cs, "getGlobalPlacement") else cs.Placement
        body = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
        if body is not None:
            frame = body.getGlobalPlacement().inverse().multiply(frame)
        center = frame.Base
    else:
        center = base.Solids[0].CenterOfMass if len(base.Solids) == 1 else base.BoundBox.Center
    if obj.Uniform:
        factors = (obj.Factor,) * 3
    else:
        factors = (obj.FactorX, obj.FactorY, obj.FactorZ)
    if min(factors) <= 0:
        raise RuntimeError("Scale factors must be more than 0")
    matrix = App.Matrix()
    matrix.move(-center)
    scaling = App.Matrix()
    scaling.scale(V(*factors))
    matrix = scaling.multiply(matrix)
    back = App.Matrix()
    back.move(center)
    matrix = back.multiply(matrix)
    if not obj.Uniform and obj.About == "Coordinate System":
        # X, Y and Z are the coordinate system's own axes
        to_cs = frame.inverse().toMatrix()
        scaling = App.Matrix()
        scaling.scale(V(*factors))
        matrix = frame.toMatrix().multiply(scaling.multiply(to_cs))
    if obj.Uniform:
        result = base.copy()
        result.scale(obj.Factor, center)
    else:
        result = base.transformGeometry(matrix)
    return result, None


SCALE = sf.Spec(
    "SWStyle_Scale", "Scale", "Scale", "Scales the part about its centroid, the origin or a coordinate system.", "FEATURES_SCALE",
    "Part_Scale",
    [Field("About", "enum", "Scale about", "Centroid", values=["Centroid", "Origin", "Coordinate System"], box="Scale Parameters"),
     Field("CoordinateSystem", "pick", "Coordinate system", what="Feature", optional=True,
           shown=lambda o: o.About == "Coordinate System", box="Scale Parameters"),
     Field("Uniform", "bool", "Uniform scaling", True, box="Scale Parameters"),
     Field("Factor", "float", "Scale factor", 1.0, low=0.001, shown=lambda o: o.Uniform, box="Scale Parameters"),
     Field("FactorX", "float", "X", 1.0, low=0.001, shown=lambda o: not o.Uniform, box="Scale Parameters"),
     Field("FactorY", "float", "Y", 1.0, low=0.001, shown=lambda o: not o.Uniform, box="Scale Parameters"),
     Field("FactorZ", "float", "Z", 1.0, low=0.001, shown=lambda o: not o.Uniform, box="Scale Parameters")],
    _scale)


# --------------------------------------------------------------------------- Dome
def _pick_direction(obj):
    """Unit vector of the Direction pick (an edge's direction or a face's normal), or None."""
    picked = sf.elements(obj, "Direction") if "Direction" in obj.PropertiesList else []
    for _, shape in picked:
        if shape.ShapeType == "Edge":
            d = shape.valueAt(shape.LastParameter) - shape.valueAt(shape.FirstParameter)
        elif shape.ShapeType == "Face":
            d = _normal(shape, shape.CenterOfMass)
        else:
            continue
        if d.Length > 1e-9:
            return d.normalize()
    return None


def _constraint_point(obj):
    picked = sf.elements(obj, "Constraint") if "Constraint" in obj.PropertiesList else []
    for _, shape in picked:
        if shape.ShapeType == "Vertex":
            return shape.Point
        if shape.Vertexes:
            return shape.Vertexes[0].Point
    return None


def _continuous(face, direction, height):
    ""


    d = App.Vector(direction).normalize()
    try:
        u = face.Surface.Rotation.multVec(V(1, 0, 0))
    except Exception:
        u = V(1, 0, 0)
    u = u - d * u.dot(d)
    if u.Length < 1e-6:
        u = V(0, 1, 0) - d * d.y
    u.normalize()
    v = d.cross(u)
    centre = face.CenterOfMass
    xs = [(p.Point - centre).dot(u) for p in face.Vertexes]
    ys = [(p.Point - centre).dot(v) for p in face.Vertexes]
    for edge in face.Edges:
        for i in range(9):
            p = edge.valueAt(edge.FirstParameter + i * (edge.LastParameter - edge.FirstParameter) / 8) - centre
            xs.append(p.dot(u))
            ys.append(p.dot(v))
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 - x0 < 1e-6 or y1 - y0 < 1e-6:
        return None
    mid = centre + u * ((x0 + x1) / 2) + v * ((y0 + y1) / 2)
    a, b = (x1 - x0) / 2 * 1.02, (y1 - y0) / 2 * 1.02
    n = 11
    rows = []
    for i in range(n):
        x = -a + 2 * a * i / (n - 1)
        row = []
        for j in range(n):
            y = -b + 2 * b * j / (n - 1)
            z = height * max(1 - (x / a) ** 2, 0) * max(1 - (y / b) ** 2, 0)
            row.append(mid + u * x + v * y + d * z)
        rows.append(row)
    try:
        surface = Part.BSplineSurface()
        surface.interpolate(rows)
        pillow = Part.Face(surface)
        slab = pillow.extrude(d * -(height + 1.0))
        prism = face.extrude(d * (height * 1.001))
        cap = slab.common(prism, 1e-6)
    except Exception:
        return None
    if cap.isNull() or not cap.Solids or cap.Volume < 1e-6:
        return None
    solid = cap.Solids[0] if len(cap.Solids) == 1 else cap.Solids[0].fuse(cap.Solids[1:])
    return solid if solid.isValid() else None


def _half_ellipsoid(r, h):
    """The exact half ellipsoid of revolution (radius r, height h along +Z) for an Elliptical dome. A
    sphere scaled by a matrix became a B-spline 0.3 % short of the volume."""
    if h >= r:
        ell = Part.Ellipse(V(0, 0, h), V(r, 0, 0), V(0, 0, 0))
    else:
        ell = Part.Ellipse(V(r, 0, 0), V(0, 0, h), V(0, 0, 0))
    a, b = ell.parameter(V(r, 0, 0)), ell.parameter(V(0, 0, h))
    lo, hi = min(a, b), max(a, b)
    if hi - lo > math.pi:
        lo, hi = hi, lo + 2 * math.pi
    arc = Part.ArcOfEllipse(ell, lo, hi).toShape()
    wire = Part.Wire([Part.LineSegment(V(0, 0, 0), V(r, 0, 0)).toShape(), arc,
                      Part.LineSegment(V(0, 0, h), V(0, 0, 0)).toShape()])
    return Part.Face(wire).revolve(V(0, 0, 0), V(0, 0, 1), 360)


def _dome(obj, base):
    picked = sf.elements(obj, "Faces")
    if not picked:
        return None, None
    height = float(obj.Distance)
    point = _constraint_point(obj)
    chosen = _pick_direction(obj)
    adds, cuts = [], []
    for _, face in picked:
        if not isinstance(face.Surface, Part.Plane):
            raise RuntimeError("Dome needs a flat face")
        center = face.CenterOfMass
        normal = _normal(face, center).normalize()
        reverse = bool(obj.Reverse)
        direction = chosen if chosen is not None else normal
        if direction.dot(normal) < 0:
            direction = direction * -1
        if point is not None:
            # the dome's height is the point's height over the face, along the direction
            signed = (point - center).dot(direction)
            height = abs(signed)
            reverse = signed < 0
        if height <= 0:
            raise RuntimeError("Dome height must be more than 0")
        if reverse:
            direction = direction * -1
        radius = max(v.Point.distanceToPoint(center) for v in face.Vertexes) if face.Vertexes else 0
        for edge in face.Edges:
            radius = max(radius, max(edge.valueAt(edge.FirstParameter + i * (edge.LastParameter - edge.FirstParameter) / 16)
                                     .distanceToPoint(center) for i in range(17)))
        cap = None
        if getattr(obj, "Continuous", False):
            cap = _continuous(face, direction, height)
        if cap is None:
            if obj.Elliptical:
                ball = _half_ellipsoid(radius, height)
                ball.Placement = App.Placement(center, App.Rotation(V(0, 0, 1), direction))
            else:
                big = (radius * radius + height * height) / (2 * height)
                ball = Part.makeSphere(big, center + direction * (height - big))
            prism = face.extrude(direction * height * 1.001)
            cap = ball.common(prism, 1e-6)
        (cuts if reverse else adds).append(cap)
    result = base
    if adds:
        result = result.fuse(adds, 1e-6)
    if cuts:
        result = result.cut(cuts, 1e-6)
    return result, Part.makeCompound(adds + cuts)


DOME_BOX = "Parameters"
DOME = sf.Spec(
    "SWStyle_Dome", "Dome", "Dome", "Adds a dome to a flat face.", "FEATURES_DOME", "Part_Sphere_Parametric",
    [Field("Faces", "pick", "Faces to dome", tip="Flat faces to put a dome on", what=("Face",), many=True, box=DOME_BOX),
     Field("Distance", "length", "Distance", 5.0, tip="Height of the dome", box=DOME_BOX),
     Field("Reverse", "bool", "Reverse Direction", False, flip=True,
           tip="Reverse Direction: a concave dome (cut into the face)", box=DOME_BOX),
     Field("Constraint", "pick", "Constraint Point or Sketch", what=("Vertex",), optional=True,
           tip="A point the dome rises to: its height over the face sets the Distance", box=DOME_BOX),
     Field("Direction", "pick", "Direction", what=("Edge", "Face"), optional=True,
           tip="An edge or a flat face giving the direction the dome rises in (the face's normal when empty)", box=DOME_BOX),
     Field("Elliptical", "bool", "Elliptical dome", False, box=DOME_BOX),
     Field("Continuous", "bool", "Continuous dome", False,
           tip="A dome that rises evenly from every edge of the face (for polygon faces)", box=DOME_BOX),
     Field("ShowPreview", "bool", "Show preview", True, box=DOME_BOX)],
    _dome, cache=True)


# --------------------------------------------------------------------------- Cut with Surface
def _same_way(faces):
    """The faces of one surface turned so that their normals agree across every shared edge (in a
    surface that is one sheet, a shared edge runs the opposite way in its two faces). The first face
    keeps its side."""
    out = {0: faces[0]}
    todo = [0]
    while todo:
        i = todo.pop()
        for edge in out[i].Edges:
            for j, other in enumerate(faces):
                if j in out:
                    continue
                twin = next((e for e in other.Edges if e.isSame(edge)), None)
                if twin is None:
                    continue
                out[j] = other.reversed() if twin.Orientation == edge.Orientation else other
                todo.append(j)
    return [out.get(i, f) for i, f in enumerate(faces)]


def _knife(source, shape, base):
    ""


    face = shape if shape.ShapeType == "Face" else (shape.Faces[0] if shape.Faces else None)
    if face is None:
        raise RuntimeError("Pick a plane, a flat face or a surface")
    try:
        whole = Part.getShape(source)
    except Exception:
        whole = None
    if whole is None or whole.isNull() or whole.Solids or len(whole.Faces) < 2:
        knife = _big_face(face, base)
        return knife, [knife]
    sheets = _surfaces([(source, whole)])
    middle = face.CenterOfMass
    sheet = min(sheets, key=lambda s: s.distToShape(Part.Vertex(middle))[0])     # the sheet that was clicked
    faces = list(sheet.Faces) if sheet.ShapeType != "Face" else [sheet]
    first = min(range(len(faces)), key=lambda i: (faces[i].CenterOfMass - middle).Length + abs(faces[i].Area - face.Area))
    faces = [faces[first]] + faces[:first] + faces[first + 1:]
    if _normal(faces[0], middle).dot(_normal(face, middle)) < 0:
        faces[0] = faces[0].reversed()          # the clicked face's own side, as it is shown
    return sheet, _same_way(faces)


def _side(point, faces):
    """> 0 when point is on the normal side of the surface (of its nearest face)."""
    best = None
    probe = Part.Vertex(point)
    for face in faces:
        try:
            dist, pairs, _info = face.distToShape(probe)
            foot = pairs[0][0]
        except Exception:
            continue
        if best is None or dist < best[0]:
            best = (dist, face, foot)
    if best is None:
        return 0.0
    _dist, face, foot = best
    normal = _normal(face, foot)
    if face.Orientation == "Reversed" and not face.isValid():
        normal = normal * -1
    return (point - foot).dot(normal)


def _cut_surface(obj, base):
    picked = sf.elements(obj, "Surface")
    if not picked:
        return None, None
    source, shape = picked[0]
    knife, faces = _knife(source, shape, base)
    from BOPTools import SplitAPI
    pieces = SplitAPI.slice(base, [knife], "Split", 1e-6).Solids
    if len(pieces) < 2:
        # the surface lies wholly outside the part (or only touches it): flipping would not help
        raise RuntimeError("The surface does not cut the part")
    keep, removed = [], []
    for piece in pieces:
        side = _side(piece.CenterOfMass, faces)
        (removed if (side > 0) != obj.Flip else keep).append(piece)
    if not keep:
        raise RuntimeError("Cut with Surface would remove the whole part: flip the side")
    if not removed:
        raise RuntimeError("The surface does not cut the part")
    result = keep[0] if len(keep) == 1 else keep[0].fuse(keep[1:])
    return result, Part.makeCompound(removed)


CUT_SURFACE = sf.Spec(
    "SWStyle_CutWithSurface", "Cut with Surface", "Surface-Cut", "Cuts the part with a plane or a surface.",
    "FEATURES_CUT_WITH_SURFACE", "Part_Slice",
    [Field("Surface", "pick", "Surface or plane to cut with", what=("Face", ""), many=False, box="Surface Cut Parameters"),
     Field("Flip", "bool", "Flip cut", False, box="Surface Cut Parameters")],
    _cut_surface, subtractive=True)


# --------------------------------------------------------------------------- Thicken / Thickened Cut
def _surfaces(picked):
    ""


    faces = []
    for src, shape in picked:
        if shape.ShapeType == "Face" and src is not None:

            # Knit does (drawings-land277: a knit of a trim and its fill thickened only the trim before)
            try:
                whole = Part.getShape(src)
                if not whole.Solids and len(whole.Faces) > 1 and any(
                        shape.isSame(g) or (abs(shape.Area - g.Area) < 1e-6 and
                                            (shape.CenterOfMass - g.CenterOfMass).Length < 1e-6)
                        for g in whole.Faces):
                    shape = whole
            except Exception as _fw_err:
                _fw_log("directfeatures.py:_surfaces", _fw_err)
        for f in ([shape] if shape.ShapeType == "Face" else shape.Faces):
            if not any(f.isSame(g) for g in faces):
                faces.append(f)
    if len(faces) == 1:
        return [faces[0]]
    try:
        sewn = Part.Shell([f.copy() for f in faces])
        sewn.sewShape(1e-6)
        shells = [s for s in (sewn.Shells or [sewn]) if s.Faces]
        if shells and sum(len(s.Faces) for s in shells) == len(faces):
            return shells
    except Exception as _fw_err:
        _fw_log("directfeatures.py:339", _fw_err)
    try:
        comp = Part.Compound([f.copy() for f in faces])
        comp.sewShape(1e-6)
        if comp.Shells:
            return list(comp.Shells)
    except Exception as _fw_err:
        _fw_log("directfeatures.py:346", _fw_err)
    return [Part.Shell(faces)]


def _solid_of(shell):
    solid = Part.Solid(shell)
    if solid.Volume < 0:
        solid.reverse()
    return solid


def _closed_wall(surface, side, thickness):
    ""



    shells = [surface] if surface.ShapeType == "Shell" else list(getattr(surface, "Shells", []) or [])
    if len(shells) != 1 or not shells[0].isClosed():
        return None
    shell = shells[0]

    def at(d):
        if abs(d) < 1e-12:
            return _solid_of(shell)
        off = shell.makeOffsetShape(d, 1e-6, False, False, 0, 0, False)
        offs = off.Shells if off.ShapeType != "Shell" else [off]
        return _solid_of(offs[0])
    if side == "Both sides":
        outer, inner = at(thickness / 2), at(-thickness / 2)
    elif side == "Side 2":
        outer, inner = at(0), at(-thickness)
    else:
        outer, inner = at(thickness), at(0)
    if outer.Volume < inner.Volume:
        outer, inner = inner, outer
    return outer.cut(inner)


def _thick_offset(surface, distance):
    ""

    try:
        return surface.makeOffsetShape(distance, 1e-6, False, False, 0, 0, True)
    except Exception as first:
        try:
            return surface.makeOffsetShape(distance, 1e-6, False, False, 0, 2, True)
        except Exception:
            raise first


def _slab(obj, base):
    picked = sf.elements(obj, "Surface")
    if not picked:
        return None
    thickness = float(obj.Thickness)
    if thickness <= 0:
        raise RuntimeError("Thickness must be more than 0")
    tools = []
    for surface in _surfaces(picked):
        wall = _closed_wall(surface, obj.Side, thickness)
        if wall is not None:
            tools.append(wall)
            continue
        if obj.Side == "Both sides":
            tools.append(_thick_offset(surface, thickness / 2))
            tools.append(_thick_offset(surface, -thickness / 2))
        else:
            sign = -1 if obj.Side == "Side 2" else 1
            tools.append(_thick_offset(surface, sign * thickness))
    tool = tools[0] if len(tools) == 1 else tools[0].fuse(tools[1:])
    return tool


def _enclosed(obj):
    """Create solid from enclosed volume: the picked faces (all of them together) knitted shut
    and made a solid."""
    faces = []
    for _, shape in sf.elements(obj, "Surface"):
        faces.extend([shape] if shape.ShapeType == "Face" else shape.Faces)
    solids = []
    if faces:
        sewn = Part.Compound([f.copy() for f in faces])
        try:
            from . import sewtol
            sewn = sewtol.sewn(faces, 1e-4)
        except Exception as _fw_err:
            _fw_log("directfeatures.py:420", _fw_err)
        for shell in sewn.Shells or [sewn]:
            try:
                if shell.ShapeType != "Shell" or not shell.isClosed():
                    continue
                solid = Part.Solid(shell)
                if solid.Volume < 0:
                    solid.reverse()
                solids.append(solid)
            except Exception:
                continue
    if not solids:
        raise RuntimeError("The surface does not close a volume: knit it shut first")
    return solids[0] if len(solids) == 1 else solids[0].fuse(solids[1:])


def _thicken(obj, base):
    if getattr(obj, "EnclosedSolid", False):
        if not sf.elements(obj, "Surface"):
            return None, None
        tool = _enclosed(obj)
    else:
        tool = _slab(obj, base)
    if tool is None:
        return None, None
    if base is None or base.isNull() or not base.Solids:
        # no solid to merge with (a new part, or a solid turned into a surface by Delete Face): the
        # thickened body is the part's solid; fusing with a bare shell failed "Null shape" (surface run 11-27)
        return tool, tool
    if not getattr(obj, "Merge", True):
        # Merge result off: the thickened body stays a body of its own
        return Part.makeCompound(list(base.Solids) + list(tool.Solids)), tool
    return _fuse(base, tool), tool


def _thick_cut(obj, base):
    tool = _slab(obj, base)
    if tool is None:
        return None, None
    return base.cut(tool, 1e-6), tool


_SIDE_ICONS = {}


def _side_icon(side):
    ""

    icon = _SIDE_ICONS.get(side)
    if icon is not None:
        return icon
    from PySide import QtCore, QtGui
    icon = QtGui.QIcon()
    for size in (24, 32, 48):
        pix = QtGui.QPixmap(size, size)
        pix.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        m, mid, h = size * 0.12, size * 0.5, size * 0.26
        blue = QtGui.QColor("#5b9bd5")
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(blue)
        if side in ("Side 1", "Both sides"):
            p.drawRect(QtCore.QRectF(m, mid - h, size - 2 * m, h))
        if side in ("Side 2", "Both sides"):
            p.drawRect(QtCore.QRectF(m, mid, size - 2 * m, h))
        p.setPen(QtGui.QPen(QtGui.QColor("#404040"), max(1.5, size / 14.0)))
        p.drawLine(QtCore.QPointF(m, mid), QtCore.QPointF(size - m, mid))
        p.end()
        icon.addPixmap(pix)
    _SIDE_ICONS[side] = icon
    return icon


_THICK_FIELDS = lambda what: [
    Field("Surface", "pick", "Surface to thicken", tip="A surface body or faces", what=("Face", ""), many=True,
          box="Thicken Parameters"),

    Field("Side", "icons", "Thicken side", "Side 1", values=["Side 1", "Both sides", "Side 2"],
          icons={"Side 1": lambda: _side_icon("Side 1"), "Both sides": lambda: _side_icon("Both sides"),
                 "Side 2": lambda: _side_icon("Side 2")},
          shown=lambda o: not getattr(o, "EnclosedSolid", False), box="Thicken Parameters"),
    Field("Thickness", "length", "Thickness", 2.0, shown=lambda o: not getattr(o, "EnclosedSolid", False),
          box="Thicken Parameters")] + ([
    Field("EnclosedSolid", "bool", "Create solid from enclosed volume", False, box="Thicken Parameters"),
    Field("Merge", "bool", "Merge result", True, box="Thicken Parameters")] if what == "add" else [])

THICKEN = sf.Spec(
    "SWStyle_Thicken", "Thicken", "Thicken", "Makes a solid by thickening a surface.", "FEATURES_THICKEN",
    "Part_Thickness", _THICK_FIELDS("add"), _thicken, needs_body=False)

THICK_CUT = sf.Spec(
    "SWStyle_ThickenedCut", "Thickened Cut", "Thicken-Cut", "Cuts the part with a thickened surface.",
    "FEATURES_THICKENED_CUT", "Part_Thickness", _THICK_FIELDS("cut"), _thick_cut, subtractive=True)
THICKEN.whole_surfaces = THICK_CUT.whole_surfaces = ("Surface",)    # a click on a surface takes the whole surface body


# --------------------------------------------------------------------------- Indent
def indent_regions(obj, solids=None):
    """The tool body's regions (its solids) the Indent uses: with Keep Selections the ones a
    picked face belongs to (all of them with none picked), with Remove Selections all the others."""
    tool_body = obj.ToolBody
    if solids is None:
        solids = list(tool_body.Shape.Solids) if tool_body is not None else []
    picked = []
    for _o, face in sf.elements(obj, "ToolRegions") if "ToolRegions" in obj.PropertiesList else []:
        for i, sol in enumerate(solids):
            if i not in picked and any(face.isSame(f) or (abs(face.Area - f.Area) < 1e-6 and
                                                          (face.CenterOfMass - f.CenterOfMass).Length < 1e-6)
                                       for f in sol.Faces):
                picked.append(i)
    if not picked:
        return solids
    keep = getattr(obj, "Selections", "Keep Selections") != "Remove Selections"
    return [sol for i, sol in enumerate(solids) if (i in picked) == keep]


def _indent_same_body(obj, base):
    ""

    solids = list(base.Solids) if base is not None else []
    if len(solids) < 2:
        raise RuntimeError("Indent needs a second solid body as the tool")
    picked = indent_regions(obj, solids)
    tools = picked if len(picked) < len(solids) else solids[-1:]
    targets = [sol for sol in solids if not any(sol.isSame(t) for t in tools)]
    if not targets:
        raise RuntimeError("Pick a face of the tool body (Tool body region)")
    target = targets[0] if len(targets) == 1 else Part.makeCompound(targets)
    tool_shape = tools[0] if len(tools) == 1 else Part.makeCompound(tools)
    clearance = float(obj.Clearance)
    signed = -clearance if getattr(obj, "ReverseClearance", False) else clearance
    tool = _grow(tool_shape, signed) if clearance > 0 else tool_shape
    if obj.Remove:
        result = target.cut(tool, 1e-6)
    else:
        overlap = target.common(tool, 1e-6)
        if overlap.isNull() or overlap.Volume < 1e-9:
            raise RuntimeError("The tool body does not touch the part")
        result = target
        thickness = float(obj.Thickness)
        if thickness > 0:
            # grown from the tool itself (an offset of an offset surface can fail)
            wall = _grow(tool_shape, (signed if clearance > 0 else 0.0) + thickness).cut(tool, 1e-6)
            box = overlap.BoundBox
            box.enlarge(thickness * 1.01)
            limit = Part.makeBox(box.XLength, box.YLength, box.ZLength, V(box.XMin, box.YMin, box.ZMin))
            result = result.fuse(wall.common(limit, 1e-6), 1e-6)
        result = result.cut(tool, 1e-6)
    return Part.makeCompound(list(result.Solids) + [t for t in tools]), tool


def _indent(obj, base):
    _indent_fix_loop(obj)
    tool_body = obj.ToolBody
    if tool_body is None:
        return None, None
    own = obj.getParentGeoFeatureGroup()
    if tool_body is own or (own is not None and tool_body.TypeId != "PartDesign::Body"
                            and tool_body.getParentGeoFeatureGroup() is own):
        label = own.Label if own is not None else tool_body.Label
        if "TargetBody" in obj.PropertiesList and obj.TargetBody != label:
            obj.TargetBody = label
        return _indent_same_body(obj, base)
    shape = tool_body.Shape
    if shape.isNull() or not shape.Solids:
        raise RuntimeError("The tool body has no solid")
    if "TargetBody" in obj.PropertiesList:
        body = obj.getParentGeoFeatureGroup()
        label = body.Label if body is not None else ""
        if obj.TargetBody != label:
            obj.TargetBody = label
    regions = indent_regions(obj)
    if not regions:
        raise RuntimeError("Every region of the tool body is removed: keep at least one")
    shape = regions[0] if len(regions) == 1 else Part.makeCompound(regions)
    clearance = float(obj.Clearance)
    signed = -clearance if getattr(obj, "ReverseClearance", False) else clearance   # reverse: inside the tool
    tool = _grow(shape, signed) if clearance > 0 else shape
    if obj.Remove:
        return base.cut(tool, 1e-6), tool

    # thin target bulges out on the far side
    thickness = float(obj.Thickness)
    overlap = base.common(tool, 1e-6)
    if overlap.isNull() or overlap.Volume < 1e-9:
        raise RuntimeError("The tool body does not touch the part")
    result = base
    if thickness > 0:
        wall = _grow(shape, (signed if clearance > 0 else 0.0) + thickness).cut(tool, 1e-6)
        box = overlap.BoundBox
        box.enlarge(thickness * 1.01)
        limit = Part.makeBox(box.XLength, box.YLength, box.ZLength, V(box.XMin, box.YMin, box.ZMin))
        result = result.fuse(wall.common(limit, 1e-6), 1e-6)
    result = result.cut(tool, 1e-6)
    return result, tool


INDENT = sf.Spec(
    "SWStyle_Indent", "Indent", "Indent", "Presses a tool body into the part with a thickness and clearance.",
    "FEATURES_INDENT", "Part_Cut",
    [Field("TargetBody", "info", "Target body", "", box="Selections"),
     Field("Selections", "radio", "Selections", "Keep Selections", values=["Keep Selections", "Remove Selections"],
           box="Selections"),
     Field("ToolBody", "pick", "Tool body", tip="The body that presses into this part", what="Object",
           box="Selections"),
     Field("ToolRegions", "pick", "Tool body region", tip="Faces of the tool body's regions to keep or remove "
           "(none: the whole tool body)", what=("Face",), many=True, optional=True, box="Selections"),
     Field("Thickness", "length", "Thickness", 1.0, box="Parameters"),
     Field("Clearance", "length", "Clearance", 0.0, box="Parameters"),
     Field("ReverseClearance", "bool", "Reverse direction", False, box="Parameters", tip="The clearance goes inside the tool"),
     Field("Remove", "bool", "Cut", False, box="Parameters", tip="Removes the tool region only")],
    _indent, subtractive=True)


def _indent_route(obj, name, holder, element):
    ""

    if name == "ToolRegions" and getattr(obj, "ToolBody", None) is None and holder is not None:
        try:
            body = holder if holder.TypeId == "PartDesign::Body" else (holder.getParentGeoFeatureGroup() or holder)
            obj.ToolBody = _indent_tool_link(obj, body, holder)
        except Exception as _fw_err:
            _fw_log("directfeatures.py:indent_route", _fw_err)
    return name


def _indent_tool_link(obj, body, holder=None):
    """A link from the Indent to its own body is a loop (the body's tip is the Indent), so the
    feature would never finish rebuilding. A tool body in the same part is named by one of its
    earlier features instead; _indent reads that as the same-body (multibody) case."""
    own = obj.getParentGeoFeatureGroup()
    if body is None or body is not own:
        return body
    if holder is not None and holder is not own and holder is not obj:
        return holder
    return getattr(obj, "BaseFeature", None) or body


def _indent_fix_loop(obj):
    tool = getattr(obj, "ToolBody", None)
    if tool is not None and tool is obj.getParentGeoFeatureGroup():
        link = _indent_tool_link(obj, tool)
        if link is not tool:
            obj.ToolBody = link


INDENT.route = _indent_route


# --------------------------------------------------------------------------- Intersect
def _capped(shape):
    """Cap planar openings: flat faces on the open planar loops of a surface tool."""
    try:
        shells = shape.Shells or [Part.makeShell(shape.Faces)]
        loops = [Part.Wire(es) for sh in shells for es in Part.sortEdges(sh.getFreeEdges().Edges)]
    except Exception:
        return shape
    caps = []
    for w in loops:
        if w.isClosed() and w.findPlane() is not None:
            try:
                caps.append(Part.Face(w))
            except Exception as _fw_err:
                _fw_log("directfeatures.py:640", _fw_err)
    return Part.makeCompound([shape] + caps) if caps else shape


def _own_solid(base, shape):
    """The part's solid body a picked face (or the body itself) belongs to, else None."""
    try:
        if base is None or base.isNull() or len(base.Solids) < 2:
            return None
        if shape.ShapeType == "Solid":
            return next((b for b in base.Solids if b.isSame(shape)), None)
        if shape.ShapeType != "Face":
            return None
        for b in base.Solids:
            if any(f.isSame(shape) for f in b.Faces):
                return b
        for b in base.Solids:
            if any(abs(f.Area - shape.Area) < 1e-7 and (f.BoundBox.Center - shape.BoundBox.Center).Length < 1e-7
                   for f in b.Faces):
                return b
    except Exception as _fw_err:
        _fw_log("directfeatures.py:own", _fw_err)
    return None


def _intersect(obj, base):
    picked = sf.elements(obj, "Tools")
    if not picked:
        obj.Regions = ""
        return None, None
    tools = []
    own = []
    for source, shape in picked:
        body = _own_solid(base, shape)
        if body is not None:
            if not any(body.isSame(o) for o in own):
                own.append(body)
            continue
        if shape.ShapeType == "Face" and isinstance(shape.Surface, Part.Plane):
            shape = _big_face(shape, base)
        elif getattr(obj, "CapPlanar", False) and not shape.Solids and shape.Faces:
            shape = _capped(shape)
        tools.append(shape)
    internal = getattr(obj, "Create", "Intersect regions") == "Internal regions"
    if internal:
        # Internal regions: the volumes the selections close off on their own, inside a box round
        # everything (a region touching the box is outside)
        box = Part.Compound(tools).BoundBox
        box.enlarge(max(box.DiagonalLength * 0.1, 1.0))
        outer = Part.makeBox(box.XLength, box.YLength, box.ZLength, V(box.XMin, box.YMin, box.ZMin))
        pieces = [outer] + tools
        fused, _ = pieces[0].generalFuse(pieces[1:], 1e-6)
        skin = outer.Faces
        regions = [r for r in fused.Solids
                   if not any(f.distToShape(r)[0] < 1e-6 for f in skin)]
        regions.sort(key=lambda solid: -solid.Volume)
    elif own:
        # the bodies picked cut each other (and the other selections cut them): their regions; the
        # part's other bodies stay as they are
        pieces = own + tools
        fused, _ = pieces[0].generalFuse(pieces[1:], 1e-6)
        regions = sorted([r for r in fused.Solids if any(o.common(r).Volume > 1e-6 * max(r.Volume, 1e-9) for o in own)],
                         key=lambda solid: -solid.Volume)
    else:
        fused, _ = base.generalFuse(tools, 1e-6)
        regions = sorted(fused.Solids, key=lambda solid: -solid.Volume)
    if not regions:
        raise RuntimeError("Intersect found no regions")
    picked = set()
    for word in obj.Exclude.replace(",", " ").split():
        if word.isdigit():
            picked.add(int(word))

    if getattr(obj, "ExcludeSelected", True):
        excluded = picked
    else:
        excluded = set(range(1, len(regions) + 1)) - picked
    obj.Regions = "\n".join("%d: %.1f mm\u00b3%s" % (i + 1, r.Volume, " (excluded)" if i + 1 in excluded else "")
                            for i, r in enumerate(regions))
    keep = [r for i, r in enumerate(regions) if i + 1 not in excluded]
    if not keep:
        raise RuntimeError("Every region is excluded" if getattr(obj, "ExcludeSelected", True)
                           else "Tick the regions to keep")
    if obj.Merge and len(keep) > 1:
        result = keep[0].fuse(keep[1:], 1e-6)
    else:
        result = keep[0] if len(keep) == 1 else Part.makeCompound(keep)
    if own and not internal:
        rest = [b for b in base.Solids if not any(b.isSame(o) for o in own)]
        if rest:
            result = Part.makeCompound(list(result.Solids) + rest)
    if getattr(obj, "Consume", False):

        for source, shape in picked:
            if not shape.Solids and getattr(source, "ViewObject", None) is not None:
                try:
                    source.ViewObject.Visibility = False
                except Exception as _fw_err:
                    _fw_log("directfeatures.py:700", _fw_err)
    return result, None


INTERSECT = sf.Spec(
    "SWStyle_Intersect", "Intersect", "Intersect",
    "Splits the part with planes, surfaces or other bodies into regions; keep the ones you want.",
    "FEATURES_INTERSECT", "Part_BooleanFragments",
    [Field("Tools", "pick", "Selections", what=("Face", ""), many=True, box="Selections", tip="Planes, surfaces or bodies"),
     Field("Create", "radio", "Create", "Intersect regions", values=["Intersect regions", "Internal regions"],
           box="Selections"),
     Field("CapPlanar", "bool", "Cap planar openings", False, box="Selections"),
     Field("Regions", "info", "Regions (biggest first)", "", box="Regions to Exclude"),
     Field("Exclude", "text", "Regions to exclude (numbers)", "", tip="e.g. 2 3", box="Regions to Exclude"),
     Field("ExcludeSelected", "bool", "Exclude selected", True, box="Regions to Exclude",
           tip="Ticked: the regions ticked in the list are left out. Cleared: only the ticked regions are kept"),
     Field("Merge", "bool", "Merge result", False, box="Options"),
     Field("Consume", "bool", "Consume surfaces", False, box="Options")],
    _intersect, panel=lambda obj, *a, **k: _intersect_panel()(obj, *a, **k))


_INTERSECT_PANEL = []


def _intersect_panel():
    ""

    if _INTERSECT_PANEL:
        return _INTERSECT_PANEL[0]
    from PySide import QtCore, QtWidgets

    class IntersectPanel(sf.Panel):
        def __init__(self, obj, *args, **kw):
            super().__init__(obj, *args, **kw)
            first = None
            for name in ("Regions", "Exclude"):
                w = self.widgets.get(name)
                if w is None:
                    continue
                form = w.parentWidget().layout()
                row, _role = form.getWidgetPosition(w)
                first = row if first is None else min(first, row)
                for r in (row - 1, row):
                    for role in (QtWidgets.QFormLayout.SpanningRole, QtWidgets.QFormLayout.LabelRole,
                                 QtWidgets.QFormLayout.FieldRole):
                        item = form.itemAt(r, role)
                        if item is not None and item.widget() is not None and \
                                item.widget() is not self.widgets.get("ExcludeSelected"):
                            item.widget().hide()
            sel = self.widgets["Tools"]
            sform = sel.parentWidget().layout()
            self.button = QtWidgets.QPushButton("Intersect")
            self.button.setObjectName("SWIntersectButton")
            self.button.setToolTip("Finds the regions the selections close off")
            self.button.clicked.connect(self.intersect)
            sform.addRow(self.button)
            ex = self.widgets["Exclude"]
            form = ex.parentWidget().layout()
            self.list = QtWidgets.QListWidget()
            self.list.setObjectName("SWIntersectRegions")
            self.list.setMinimumHeight(90)
            self.list.itemChanged.connect(self._ticked)
            form.insertRow(max(first or 0, 0), self.list)
            self.fill()

        def regions(self):
            out = []
            for line in (getattr(self.obj, "Regions", "") or "").splitlines():
                head, _sep, rest = line.partition(":")
                if head.strip().isdigit():
                    out.append((int(head), rest.replace("(excluded)", "").strip()))
            return out

        def ticked(self):
            return [int(w) for w in self.obj.Exclude.replace(",", " ").split() if w.isdigit()]

        def fill(self):
            ticked = set(self.ticked())
            self.list.blockSignals(True)
            self.list.clear()
            for number, size in self.regions():
                item = QtWidgets.QListWidgetItem("Region %d (%s)" % (number, size))
                item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                item.setCheckState(QtCore.Qt.Checked if number in ticked else QtCore.Qt.Unchecked)
                self.list.addItem(item)
            self.list.blockSignals(False)

        def intersect(self):
            self.obj.touch()
            self.obj.Document.recompute()
            self.fill()
            self._show()

        def set_ticked(self, numbers):
            text = " ".join(str(n) for n in sorted(numbers))
            box = self.widgets["Exclude"]       # hidden, but the page writes it back on every change
            box.blockSignals(True)
            box.setPlainText(text)
            box.blockSignals(False)
            self.obj.Exclude = text
            self.obj.Document.recompute()
            self.fill()
            self._show()

        def _ticked(self, _item):
            numbers = [self.regions()[r][0] for r in range(self.list.count())
                       if self.list.item(r).checkState() == QtCore.Qt.Checked]
            self.set_ticked(numbers)

    _INTERSECT_PANEL.append(IntersectPanel)
    return IntersectPanel


# --------------------------------------------------------------------------- Split Line
def _pull_of(obj):
    picked = sf.elements(obj, "Direction")
    if not picked:
        return None
    shape = picked[0][1]
    if shape.ShapeType == "Face":
        pull = shape.Surface.Axis if isinstance(shape.Surface, Part.Plane) else shape.normalAt(0, 0)
    elif shape.ShapeType == "Edge" and len(shape.Vertexes) == 2:
        pull = shape.Vertexes[1].Point - shape.Vertexes[0].Point
    elif shape.Faces:
        pull = shape.Faces[0].normalAt(0, 0)
    elif shape.Edges and hasattr(shape.Edges[0].Curve, "Direction"):
        pull = shape.Edges[0].Curve.Direction        # an axis or datum line
    else:
        raise RuntimeError("Pick a plane, flat face or straight edge for the direction of pull")
    pull = V(pull)
    pull.normalize()
    return pull


def _silhouette_edges(face, pull, rows=40, angle=0.0):
    """Edges on the face where it turns side-on to the pull (its normal at right angles to it, or at
    90 degrees less the Angle, as a draft line), found in the face's own u-v space and laid back on
    its surface. Rows of constant v are searched across u; a line that runs along u (a sphere's
    equator, PATCH-MERGE PM thread pkg147) is found searching rows of constant u across v."""
    return _silhouette_scan(face, pull, rows, angle, False) or _silhouette_scan(face, pull, rows, angle, True)


def _silhouette_scan(face, pull, rows, angle, along_v):
    import math
    u0, u1, v0, v1 = face.ParameterRange
    lean = math.sin(math.radians(angle))
    if along_v:     # search across v in rows of constant u
        a0, a1, b0, b1 = v0, v1, u0, u1
        uv = lambda a, b: (b, a)
        periodic = face.Surface.isVPeriodic()
    else:
        a0, a1, b0, b1 = u0, u1, v0, v1
        uv = lambda a, b: (a, b)
        periodic = face.Surface.isUPeriodic()
    def f(a, b):
        return face.normalAt(*uv(a, b)).dot(pull) - lean
    grid = [f(a0 + (a1 - a0) * i / 8, b0 + (b1 - b0) * j / 8) for i in range(9) for j in range(9)]
    if max(abs(x) for x in grid) < 1e-9:
        return []        # side-on everywhere (a wall along the pull): no line to split it on
    chains = {}
    steps = 60
    for r in range(rows + 1):
        b = b0 + (b1 - b0) * r / rows
        roots = []
        last = f(a0, b)
        for i in range(1, steps + 1):
            a = a0 + (a1 - a0) * i / steps
            now = f(a, b)
            if abs(now) < 1e-12 or last * now < 0:
                lo, hi = a - (a1 - a0) / steps, a
                for _ in range(40):
                    mid = (lo + hi) / 2
                    if f(lo, b) * f(mid, b) <= 0:
                        hi = mid
                    else:
                        lo = mid
                root = (lo + hi) / 2
                if not roots or abs(root - roots[-1]) > (a1 - a0) / steps * 0.5:
                    roots.append(root)
            last = now
        if len(roots) > 1 and periodic and \
                abs((roots[0] - a0) + (a1 - roots[-1])) < (a1 - a0) / steps * 0.5:
            roots.pop()          # the same line found at both ends of a closed face
        for k, a in enumerate(roots):
            chains.setdefault(k, []).append(uv(a, b))
    edges = []
    for points in chains.values():
        points = [p for p in points if face.isPartOfDomain(*p)]
        if len(points) < 2:
            continue
        line = Part.Geom2d.BSplineCurve2d()
        line.interpolate([App.Base.Vector2d(u, v) for u, v in points])
        try:
            edge = line.toShape(face.Surface, line.FirstParameter, line.LastParameter)
        except Exception:
            continue
        if edge.Length > 1e-6:
            edges.append(edge)
    return edges


def _cutting_faces(obj, base, split_all=True):
    """The splitting faces; with Split all a plane reaches right across the part (otherwise a face
    splits only where it actually is)."""
    out = []
    size = max(base.BoundBox.DiagonalLength, 1.0) * 2
    for _, shape in sf.elements(obj, "Tools"):
        for face in shape.Faces:
            if split_all and isinstance(face.Surface, Part.Plane):
                plane = face.Surface
                point = plane.projectPoint(base.BoundBox.Center)
                big = Part.Plane(point, plane.Axis)
                u, v = big.parameter(point)
                out.append(big.toShape(u - size, u + size, v - size, v + size))
            else:
                out.append(face)
    return out


def _split_line(obj, base):
    picked = sf.elements(obj, "Faces")
    kind = getattr(obj, "Type", "Projection")
    if not picked:
        return None, None
    surface = base is None
    if surface:
        # a surface body (no PartDesign solid): its faces are split, the result is a new surface body
        base = Part.getShape(picked[0][0])
    cutters = []
    if kind == "Projection":
        sketch = obj.Sketch
        if sketch is None:
            return None, None
        placement = sketch.getGlobalPlacement() if hasattr(sketch, "getGlobalPlacement") else sketch.Placement
        direction = placement.Rotation.multVec(V(0, 0, 1))
        if obj.Reverse:
            direction = -direction
        curves = [e for e in sketch.Shape.Edges]
        if not curves:
            raise RuntimeError("The sketch has no lines")
        single = getattr(obj, "SingleDirection", False)
        for _, face in picked:
            for curve in curves:
                try:
                    found = face.makeParallelProjection(curve, direction).Edges
                except Exception:
                    continue
                if single:
                    # Single direction: only what lies ahead of the sketch, along the direction
                    found = [e for e in found
                             if (e.valueAt((e.FirstParameter + e.LastParameter) / 2) - placement.Base).dot(direction) >= -1e-6]
                cutters += found
        if not cutters:
            raise RuntimeError("The sketch does not fall on the picked faces")
    elif kind == "Intersection":
        tools = _cutting_faces(obj, base, getattr(obj, "SplitAll", True))
        if not tools:
            return None, None
        for _, face in picked:
            for tool in tools:
                try:
                    found = face.section(tool).Edges
                except Exception:
                    continue
                if getattr(obj, "SurfaceSplit", "Natural") == "Linear":
                    # Linear: each split runs straight between where it meets the face's edges
                    found = [Part.LineSegment(e.Vertexes[0].Point, e.Vertexes[-1].Point).toShape()
                             if len(e.Vertexes) == 2 and e.Vertexes[0].Point.distanceToPoint(e.Vertexes[-1].Point) > 1e-6
                             else e for e in found]
                cutters += found
        if not cutters:
            raise RuntimeError("The splitting planes or faces do not cross the picked faces")
    else:
        pull = _pull_of(obj)
        if pull is None:
            return None, None
        for _, face in picked:
            cutters += _silhouette_edges(face, pull, angle=float(getattr(obj, "Angle", 0.0) or 0.0))
        if not cutters:
            raise RuntimeError("The picked faces do not turn side-on to the direction of pull")
    fused, _ = base.generalFuse(cutters, 1e-6)
    if surface:
        faces = [f for f in fused.Faces]
        if len(faces) <= len(base.Faces):
            raise RuntimeError("The split line does not cross the picked faces")
        try:
            shell = Part.Shell(faces)
            return (shell if shell.isValid() else Part.makeCompound(faces)), None
        except Exception:
            return Part.makeCompound(faces), None
    solids = fused.Solids
    if not solids:
        raise RuntimeError("Split Line could not split the faces")
    result = solids[0] if len(solids) == 1 else Part.makeCompound(solids)
    if len(result.Faces) <= len(base.Faces):
        raise RuntimeError("The split line does not cross the picked faces")
    return result, None


SPLIT_LINE = sf.Spec(
    "SWStyle_SplitLine", "Split Line", "Split Line",
    "Splits faces of the part along a silhouette, a projected sketch or where planes and faces cross them.",
    "FEATURES_SPLIT_LINE", "Part_Slice",
    [Field("Type", "radio", "Type of Split", "Projection", values=["Silhouette", "Projection", "Intersection"],
           box="Type of Split"),
     Field("Direction", "pick", "Direction of Pull", what=("Face", "Edge", ""),
           shown=lambda o: o.Type == "Silhouette", optional=True, tip="A plane, face or edge", box="Selections"),
     Field("Sketch", "pick", "Sketch to project", what="Feature", shown=lambda o: o.Type == "Projection",
           optional=True, box="Selections"),
     Field("Tools", "pick", "Splitting bodies, faces or planes", what=("Face", ""), many=True,
           shown=lambda o: o.Type == "Intersection", optional=True, box="Selections"),
     Field("Faces", "pick", "Faces to split", what=("Face",), many=True, box="Selections"),
     Field("Angle", "angle", "Angle", 0.0, low=0.0, high=89.0, shown=lambda o: o.Type == "Silhouette", box="Selections"),
     Field("SingleDirection", "bool", "Single direction", False, shown=lambda o: o.Type == "Projection", box="Selections"),
     Field("Reverse", "bool", "Reverse direction", False, shown=lambda o: o.Type == "Projection", box="Selections"),
     Field("SplitAll", "bool", "Split all", True, shown=lambda o: o.Type == "Intersection", box="Selections"),
     Field("SurfaceSplit", "enum", "Surface split options", "Natural", values=["Natural", "Linear"],
           shown=lambda o: o.Type == "Intersection", box="Selections")],
    _split_line, refine=False, first_pick="Sketch", cache=True)


def _split_route(obj, active, holder, element):
    ""


    kind = getattr(obj, "Type", "")
    if kind == "Projection":

        # a face of the part goes to Faces to split (fix155: a face click landed in the sketch box)
        try:
            if holder.isDerivedFrom("Sketcher::SketchObject"):
                return "Sketch"
        except Exception as _fw_err:
            _fw_log("directfeatures.py:1032", _fw_err)
        if element.startswith("Face"):
            return "Faces"
        return active
    if kind != "Intersection":
        return active
    is_plane = not element and (holder.TypeId in ("App::Plane", "PartDesign::Plane", "Part::DatumPlane"))
    if is_plane:
        return "Tools"
    if element.startswith("Face") and holder is obj.BaseFeature and active == "Tools" and obj.Tools:
        return "Faces"
    return active


SPLIT_LINE.route = _split_route


SPLIT_LINE_SURFACE = sf.Spec(
    "SWStyle_SplitLine", "Split Line", "Split Line", SPLIT_LINE.tip, "FEATURES_SPLIT_LINE", "Part_Slice",
    SPLIT_LINE.fields, _split_line, refine=False, first_pick="Sketch", cache=True, needs_body=False)
SPLIT_LINE_SURFACE.internal = "SplitLineSurface"
sf.SPECS["SplitLineSurface"] = SPLIT_LINE_SURFACE
sf.SPECS["SplitLine"] = SPLIT_LINE
SPLIT_LINE_SURFACE.route = _split_route


class SplitLineCommand(sf.Command):
    """Split Line works on the solid when there is one, and on surface bodies when there is none."""

    @staticmethod
    def _surfaces(doc):
        from . import deleteface
        return [o for o in doc.Objects if deleteface.free_source(o) is not None]

    def IsActive(self):
        import FreeCADGui as Gui
        doc = App.ActiveDocument
        if doc is None or Gui.Control.activeDialog():
            return False
        return sf.ready(self.spec, doc) or bool(self._surfaces(doc))

    def Activated(self):
        import FreeCADGui as Gui
        doc = App.ActiveDocument
        body = sf.body_of(doc)
        if body is not None and sf.has_solid(body):
            return super().Activated()
        from . import surfacefeatures as surf
        # each pick in its own box: planes split (Intersection), a sketch projects, faces are split
        planes, sketches, faces = [], [], []
        for sel in Gui.Selection.getSelectionEx():         # resolved: an origin plane is itself
            o = sel.Object
            subs = [x for x in (sel.SubElementNames or []) if x] or [""]
            if o.TypeId in ("App::Plane", "PartDesign::Plane", "Part::DatumPlane"):
                planes.append((o, ""))
            elif o.TypeId.startswith("Sketcher::"):
                sketches.append(o)
            else:
                faces += [(o, x.split(".")[-1]) for x in subs if x.split(".")[-1].startswith("Face")]
        picks, values = {}, {}
        if planes:
            picks["Tools"], values["Type"] = planes, "Intersection"
        if sketches:
            picks["Sketch"] = sketches[0]
        if faces:
            picks["Faces"] = faces
        surf.make(SPLIT_LINE_SURFACE, picks=picks, **values)


# --------------------------------------------------------------------------- Variable Size Fillet
def _picked_edges(obj):
    """[(source object, edge)] of the Variable Size Fillet's picks, in order."""
    out = []
    for source, shape in sf.elements(obj, "Edges"):
        out += [(source, e) for e in ([shape] if shape.ShapeType == "Edge" else shape.Edges)]
    return out


def start_points(obj, picked=None):
    """V1 of each picked edge (a point, or None): the end its Start radius goes at. An edge's own
    direction is not kept by an edit before the fillet (a sketch line redrawn the other way round
    turns the edge round, and the small end of the fillet went to the other corner), so V1 is kept
    as a vertex in StartVertices, a link FreeCAD renames with the part, taken from the edge's
    direction when the edges were picked."""
    picked = _picked_edges(obj) if picked is None else picked
    if "StartVertices" not in obj.PropertiesList:
        obj.addProperty("App::PropertyLinkSubListGlobal", "StartVertices", "Variable Size Fillet",
                        "V1 of each picked edge, where its Start radius goes")
        obj.setEditorMode("StartVertices", 2)
        obj.addProperty("App::PropertyLinkSubListGlobal", "StartEdges", "Variable Size Fillet",
                        "The Edges picks StartVertices was taken for (another pick takes it again)")
        obj.setEditorMode("StartEdges", 2)

    def flat_of(value):
        out = []
        for item in list(value or []):
            if isinstance(item, App.DocumentObject):
                out.append((item, ""))
                continue
            src, subs = item
            for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
                out.append((src, sub))
        return out
    flat = flat_of(obj.StartVertices)
    picks_now = [(src.Name, sub) for src, sub in flat_of(obj.Edges)]
    picks_then = [(src.Name, sub) for src, sub in flat_of(obj.StartEdges)]
    if len(flat) != len(picked) or any(f[0] is not p[0] for f, p in zip(flat, picked)) or picks_now != picks_then:
        flat = []
        for src, e in picked:
            p = e.Vertexes[0].Point if e.Vertexes else None
            shape = getattr(src, "Shape", None)
            k = next((k for k, v in enumerate(shape.Vertexes, 1) if p is not None and (v.Point - p).Length < 1e-7),
                     None) if shape is not None else None
            flat.append((src, "Vertex%d" % k if k else ""))
        try:
            obj.StartVertices = [(src, sub) for src, sub in flat if sub] if all(sub for _s, sub in flat) else []
            obj.StartEdges = list(obj.Edges or [])
        except Exception as _fw_err:
            _fw_log("directfeatures.py:start_points", _fw_err)
    out = []
    for src, sub in flat:
        try:
            out.append(src.Shape.getElement(sub.split(".")[-1].lstrip("?")).Point if sub and not sub.startswith("?") else None)
        except Exception:
            out.append(None)
    return out


def _starts_at_end(edge, point):
    """True when V1 (point) is the edge's last vertex: the radii run the other way along it."""
    if point is None or len(edge.Vertexes) < 2:
        return False
    return (edge.Vertexes[-1].Point - point).Length < 1e-6 < (edge.Vertexes[0].Point - point).Length


def _variable_fillet(obj, base):
    picked_pairs = _picked_edges(obj)
    if not picked_pairs:
        return None, None
    edges = [e for _src, e in picked_pairs]
    starts = start_points(obj, picked_pairs)
    # Elements of the earlier feature are the same edges in base: find them by geometry
    own = []
    v1 = {}
    for edge, start in zip(edges, starts):
        match = [e for e in base.Edges if e.isSame(edge)] or \
            [e for e in base.Edges if abs(e.Length - edge.Length) < 1e-6 and
             e.CenterOfMass.distanceToPoint(edge.CenterOfMass) < 1e-6]
        if match:
            own.append(match[0])
            v1[len(own) - 1] = start
    if not own:
        raise RuntimeError("The picked edges are not on the part")
    start, end = float(obj.StartRadius), float(obj.EndRadius)
    if start <= 0 or end <= 0:
        raise RuntimeError("Radii must be more than 0")
    law = control_law(obj, start, end)
    continuous = bool(getattr(obj, "ContinuousBlend", False))
    straight = str(getattr(obj, "Transition", "Straight transition")) != "Smooth transition"
    turned = any(_starts_at_end(e, v1.get(k)) for k, e in enumerate(own))
    if law is None and not turned and not (continuous and len(own) > 1) and not (straight and abs(start - end) > 1e-9):
        return base.makeFillet(start, end, own), None
    if law is None:
        law = [(0.0, start), (1.0, end)]
    if straight:
        law = straight_law(law)
    else:
        law = smooth_law(law)
    return variable_fillet(base, own, law, continuous, [v1.get(k) for k in range(len(own))]), None


def straight_law(law, step=0.125):
    ""



    out = [law[0]]
    for (f0, r0), (f1, r1) in zip(law, law[1:]):
        if abs(r1 - r0) > 1e-9:
            n = max(1, int(math.ceil((f1 - f0) / step - 1e-9)))
            for k in range(1, n):
                f = f0 + (f1 - f0) * k / n
                out.append((f, r0 + (r1 - r0) * k / n))
        out.append((f1, r1))
    return out


def tangent_chains(edges, angle=1.0):
    ""

    tol = 1e-6
    cos = math.cos(math.radians(angle))
    left = list(edges)
    chains = []

    def ends(e, rev):
        a, b = e.valueAt(e.FirstParameter), e.valueAt(e.LastParameter)     # the curve's own direction
        return (b, a) if rev else (a, b)

    def tangent(e, rev, at_end):
        p = e.LastParameter if at_end != rev else e.FirstParameter
        t = App.Vector(e.tangentAt(p))
        return t * -1 if rev else t

    while left:
        chain = [(left.pop(0), False)]
        grown = True
        while grown:
            grown = False
            for e in list(left):
                head, hrev = chain[0]
                tail, trev = chain[-1]
                for rev in (False, True):
                    s0, s1 = ends(e, rev)
                    if (s0 - ends(tail, trev)[1]).Length < tol and \
                            tangent(tail, trev, True).dot(tangent(e, rev, False)) >= cos:
                        chain.append((e, rev)); left.remove(e); grown = True
                        break
                    if (s1 - ends(head, hrev)[0]).Length < tol and \
                            tangent(e, rev, True).dot(tangent(head, hrev, False)) >= cos:
                        chain.insert(0, (e, rev)); left.remove(e); grown = True
                        break
                if grown:
                    break
        if chain[0][1]:          # start the chain on an edge that runs its way (see variable_fillet)
            chain = [(e, not rev) for e, rev in reversed(chain)]
            if chain[0][1]:
                chain = [(e, not rev) for e, rev in reversed(chain)]
        chains.append(chain)
    return chains


def smooth_law(law, between=3):
    ""


    xs = [f for f, _r in law]
    ys = [r for _f, r in law]
    n = len(xs)
    if n < 3:
        return law
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    d = [(ys[i + 1] - ys[i]) / max(h[i], 1e-12) for i in range(n - 1)]
    m = [d[0]] + [0.0] * (n - 2) + [d[-1]]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    out = []
    for i in range(n - 1):
        out.append(law[i])
        for k in range(1, between + 1):
            t = k / (between + 1.0)
            h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
            h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
            r = h00 * ys[i] + h10 * h[i] * m[i] + h01 * ys[i + 1] + h11 * h[i] * m[i + 1]
            out.append((xs[i] + t * h[i], max(r, 1e-3)))
    out.append(law[-1])
    return out


def _numbers(text):
    out = []
    for word in (text or "").replace(";", ",").split(","):
        word = word.strip().rstrip("%").replace("mm", "").strip()
        if word:
            out.append(float(word))
    return out


def control_law(obj, start, end):
    ""

    count = int(getattr(obj, "ControlPoints", 0) or 0)
    radii = _numbers(getattr(obj, "PointRadii", ""))
    if count <= 0 or not radii:
        return None
    where = [p / 100.0 for p in _numbers(getattr(obj, "PointPositions", ""))]
    if len(where) != count:
        where = [(k + 1.0) / (count + 1.0) for k in range(count)]
    law = [(0.0, start)]
    pairs = [(min(max(f, 0.001), 0.999), radii[k] if k < len(radii) and radii[k] > 0 else None)
             for k, f in enumerate(where)]
    for f, r in sorted(pairs, key=lambda t: t[0]):     # each radius stays with its own point
        if r is None:      # an unset point follows the line between its neighbours
            continue
        law.append((f, r))
    law.append((1.0, end))
    return law if len(law) > 2 else None


def _radius_at(law, f):
    for (f0, r0), (f1, r1) in zip(law, law[1:]):
        if f <= f1 + 1e-12:
            return r0 + (r1 - r0) * (f - f0) / max(f1 - f0, 1e-12)
    return law[-1][1]


def _fraction(edge, point):
    """How far along edge (0 at its start, 1 at its end) the point is."""
    param = edge.Curve.parameter(point)
    lo, hi = edge.FirstParameter, edge.LastParameter
    param = min(max(param, lo), hi)
    try:
        return Part.Edge(edge.Curve, lo, param).Length / edge.Length if param > lo else 0.0
    except Exception:
        return (param - lo) / (hi - lo)


def variable_fillet(base, edges, law, continuous=False, starts=None):
    """A variable size fillet through control points: the part is split square to each edge at
    its control points, every piece of the edge gets the radii of its two ends (OpenCascade's
    start-to-end fillet), and the cut lines on the flat faces are taken away again. With
    continuous (Continuous edge blend) a chain of tangent edges is one edge: the radii run from
    the chain's start to its end and the control points are spread along all of it."""
    from BOPTools import SplitAPI
    from . import multiradius
    size = base.BoundBox.DiagonalLength * 2 + 10
    chains = tangent_chains(edges) if continuous else [[(e, False)] for e in edges]
    # V1 (starts, a point per edge) sets which way the radii run: a chain whose V1 is at its far end
    # is turned round
    v1 = {}
    for e, p in zip(edges, starts or []):
        if p is not None:
            v1[id(e)] = p
    for k, chain in enumerate(chains):
        for e, rev in chain:
            p = v1.get(id(e))
            if p is None or len(e.Vertexes) < 2:
                continue
            first, last = (e.Vertexes[-1].Point, e.Vertexes[0].Point) if rev else (e.Vertexes[0].Point, e.Vertexes[-1].Point)
            if (last - p).Length < 1e-6 < (first - p).Length:
                chains[k] = [(x, not r) for x, r in reversed(chain)]
            break
    paths = []          # [(edge, reversed, length before it on the chain, chain length)]
    for chain in chains:
        total = sum(e.Length for e, _rev in chain)
        before = 0.0
        for e, rev in chain:
            paths.append((e, rev, before, total))
            before += e.Length
    planes = []
    for e, rev, before, total in paths:
        for f, _r in law[1:-1]:
            at = f * total - before
            if not -1e-9 < at < e.Length + 1e-9:
                continue
            at = min(max(at, 0.0), e.Length)
            param = e.getParameterByLength(e.Length - at if rev else at)
            p, t = e.valueAt(param), App.Vector(e.tangentAt(param))
            planes.append(Part.makePlane(size, size, App.Vector(0, 0, 0), t).translated(
                p - _plane_corner_offset(size, t)))
    if planes:
        pieces = SplitAPI.slice(base, planes, "Split")
        solids = pieces.Solids
        split = solids[0].multiFuse(solids[1:]) if len(solids) > 1 else solids[0]
        if len(split.Solids) == 1:
            split = split.Solids[0]
    else:
        split = base

    def where(e, rev, before, total, point):
        f = _fraction(e, point)
        return (before + (1.0 - f if rev else f) * e.Length) / max(total, 1e-12)
    rows, order = [], []
    for i, piece in enumerate(split.Edges, 1):
        mid = piece.valueAt(0.5 * (piece.FirstParameter + piece.LastParameter))
        for e, rev, before, total in paths:
            if e.distToShape(Part.Vertex(mid))[0] > 1e-6 or piece.Length > e.Length + 1e-6:
                continue
            a = where(e, rev, before, total, piece.valueAt(piece.FirstParameter))
            b = where(e, rev, before, total, piece.valueAt(piece.LastParameter))
            if continuous:
                # OpenCascade fillets a tangent chain as one spine that runs the way its first
                # edge runs: each piece's radii go in the chain's direction, first piece first
                lo, hi = min(a, b), max(a, b)
                order.append((paths.index((e, rev, before, total)), lo, i))
                rows.append((i, _radius_at(law, lo), _radius_at(law, hi)))
            else:
                rows.append((i, _radius_at(law, a), _radius_at(law, b)))
            break
    if continuous and order:
        rank = {i: k for k, (_p, _lo, i) in enumerate(sorted(order))}
        rows.sort(key=lambda row: rank.get(row[0], len(rank)))
    if not rows:
        raise RuntimeError("The edges could not be split at the control points")
    out = multiradius.per_edge(split, "Fillet", rows)
    try:
        clean = out.removeSplitter()
        if clean.isValid():
            out = clean
    except Exception as _fw_err:
        _fw_log("directfeatures.py:1322", _fw_err)
    return out


def _plane_corner_offset(size, normal):
    """Part.makePlane puts the plane's corner at its base point: the vector to put its middle there."""
    face = Part.makePlane(size, size, App.Vector(0, 0, 0), normal)
    return face.CenterOfMass


BOX_ITEMS = "Items To Fillet"
VARIABLE_FILLET = sf.Spec(
    "SWStyle_VariableFillet", "Variable Size Fillet", "VarFillet",
    "Rounds edges with a radius that changes from the start to the end of each edge.",
    "FEATURES_VARIABLE_FILLET", "PartDesign_Fillet",
    [Field("Edges", "pick", "Edges to fillet", what=("Edge",), many=True, box=BOX_ITEMS),
     Field("StartRadius", "length", "Start radius", 2.0, box=BOX_ITEMS),
     Field("EndRadius", "length", "End radius", 5.0, box=BOX_ITEMS),
     Field("ControlPoints", "int", "Number of control points", 3, box=BOX_ITEMS,
           tip="Points along each edge between its start and end"),
     Field("PointRadii", "text", "Control point radii", "", box=BOX_ITEMS,
           tip="A radius for each control point, e.g. 3, 6, 3 (blank: straight from start to end)"),
     Field("PointPositions", "text", "Control point positions (%)", "", box=BOX_ITEMS,
           tip="Where the points are along the edge, e.g. 25, 50, 75 (blank: evenly spaced)"),
     Field("Transition", "enum", "Transition", "Smooth transition", box=BOX_ITEMS,
           values=["Smooth transition", "Straight transition"], legacy="Straight transition",
           tip="Smooth: the radius blends through the control points; Straight: it changes in straight lines"),
     Field("ContinuousBlend", "bool", "Continuous edge blend", False, legacy=False, box=BOX_ITEMS,
           tip="Tangent edges are filleted as one edge: the radius runs from the start of the chain to its end")],
    _variable_fillet, cache=True)
try:
    from . import variablefilletpm as _vfpm
    VARIABLE_FILLET.panel = _vfpm.Panel
except Exception as _fw_err:
    _fw_log("directfeatures.py:1355", _fw_err)


def _fillet_type_box(obj):
    from . import filletchamfer
    return filletchamfer.type_box(obj)


VARIABLE_FILLET.head_box = _fillet_type_box
VARIABLE_FILLET.pm_title = "Fillet"


ALL = [SCALE, DOME, CUT_SURFACE, THICKEN, THICK_CUT, INDENT, INTERSECT, SPLIT_LINE, VARIABLE_FILLET]


def register():
    import FreeCADGui as Gui
    for spec in ALL:
        if spec is SPLIT_LINE:
            try:
                if spec.command not in Gui.listCommands():
                    Gui.addCommand(spec.command, SplitLineCommand(spec))
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Split Line command not added (%s)\n" % error)
            continue
        sf.register(spec)
    from . import fastening, insertfeatures, molds, surfacefeatures    # Insert > Fastening Feature, Features, Molds, Surface
    fastening.register()
    insertfeatures.register()
    surfacefeatures.register()
    molds.register()
    from . import loftsweep           # Loft/Sweep with constraints, guides, thin feature, scope
    loftsweep.register()
    from . import holeends            # Hole Wizard Up To Next/Vertex/Surface depths follow the part
    holeends._watch()
    from . import createassembly    # Insert > Features > Create Assembly
    createassembly.register()
    from . import meshbody          # Insert > Features > Convert to Mesh Body
    meshbody.register()
    from . import segmesh
    segmesh.register()
    from . import deform            # Insert > Features > Deform
    deform.register()
    from . import toolsextras       # Tools menu: Automatic Solve, Simplify, Format Painter, Macro, Save/Restore Settings
    toolsextras.register()
    from . import designchecker     # Tools > Design Checker
    designchecker.register()
    from . import editextras        # Edit menu: Roll to Previous/End, Suppress per configuration, Design Table, Flip Normal
    editextras.register()
    from . import viewextras        # View menu: Record Video, Rotate/Pan/Roll, lights, more Hide/Show types
    viewextras.register()
    from . import insertextras      # Insert menu: Imported, FeatureWorks, Mate Reference, Fillet Bead, Mirror Part, Tables...
    insertextras.register()
    from . import freeshape         # Insert > Freeshape
    freeshape.register()
    from . import mbd               # MBD Dimensions tab: 3D annotations
    mbd.register()
    from . import evaltools         # Evaluate: Simulation Wizard, Manufacturability, Sustainability, Costing...
    evaltools.register()
    from . import equations         # Tools > Equations: global variables, equations, dimensions
    equations.register()
    from . import fileprops         # File > Properties: Summary, Custom, Configuration Specific
    fileprops.register()
    from . import proptabbuilder    # Property Tab Builder (the Custom Properties tab's designer, PM pkg137)
    proptabbuilder.register()
    from . import cmtabs            # CommandManager: Freeshape, Mold Tools, Mesh Modeling, Data Migration, Direct Editing, Markup, Render Tools tabs
    cmtabs.install()
    from . import addintabs         # add-in tabs: Simulation, Flow Simulation, Analysis Preparation, CAM, ScanTo3D; full Add-Ins
    addintabs.install()
