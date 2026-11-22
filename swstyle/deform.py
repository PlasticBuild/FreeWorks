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

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector

def _refine_curve(c, spans):
    a, b = c.FirstParameter, c.LastParameter
    for k in range(1, spans):
        try: c.insertKnot(a + (b - a) * k / spans, 1, 1e-9)
        except Exception as _fw_err:
            _fw_log("deform.py:33", _fw_err)

def _refine_surface(s, spans):
    u0, u1, v0, v1 = s.bounds()
    for k in range(1, spans):
        try: s.insertUKnot(u0 + (u1 - u0) * k / spans, 1, 1e-9)
        except Exception as _fw_err:
            _fw_log("deform.py:40", _fw_err)
        try: s.insertVKnot(v0 + (v1 - v0) * k / spans, 1, 1e-9)
        except Exception as _fw_err:
            _fw_log("deform.py:43", _fw_err)

def warp(shape, fn, spans=8, tol=1e-2, only=None, face_fn=None):
    """shape with every control point p moved by fn(p). With only (face indices), just those faces
    change, their poles moved by face_fn(index, face, p) and their edges kept (fn = no move).
    A closed face with a hole in it (a cylinder after a Wrap or a hole) does not rebuild over its
    seam: when the result is broken, the closed faces are cut in two first and it is made again."""
    try:
        solid = _warp(shape, fn, spans, tol, only, face_fn)
        if solid.isValid() and len(solid.Faces) >= len(shape.Faces):
            return solid
        error = RuntimeError("The deformed faces could not be joined")
    except Exception as e:
        error = e
    if only is not None:
        raise error         # face indices refer to the faces as they are: no split
    from .flex import split_closed
    cut = split_closed(shape)
    if cut is shape or len(cut.Faces) == len(shape.Faces):
        raise error
    return _warp(cut, fn, spans, tol, None, face_fn)


def _warp(shape, fn, spans=8, tol=1e-2, only=None, face_fn=None):
    # a deep copy first: OCC's NURBS conversion crashed FreeCAD on a PartDesign feature's own
    # shape when one Deform/Freeform followed another
    nurbs = Part.Shape(shape).copy(True).toNurbs()
    edges = {}
    def new_edge(e):
        key = e.hashCode()
        if key not in edges:
            c = e.Curve
            if not isinstance(c, Part.BSplineCurve):
                c = c.toBSpline(e.FirstParameter, e.LastParameter)
            else:
                c = c.copy()
                if abs(c.FirstParameter - e.FirstParameter) > 1e-9 or abs(c.LastParameter - e.LastParameter) > 1e-9:
                    c.segment(e.FirstParameter, e.LastParameter)
            _refine_curve(c, spans)
            for i, p in enumerate(c.getPoles()):
                c.setPole(i + 1, p + fn(p))
            edges[key] = c.toShape()
        return edges[key]
    faces = []
    for index, f in enumerate(nurbs.Faces):
        if only is not None and index not in only:
            faces.append(f.copy())
            continue
        move = (lambda p, k=index, ff=f: face_fn(k, ff, p)) if face_fn is not None else fn
        s = f.Surface
        s = s.copy() if isinstance(s, Part.BSplineSurface) else s.toBSpline()
        _refine_surface(s, spans)
        poles = s.getPoles()
        for i, row in enumerate(poles):
            for j, p in enumerate(row):
                s.setPole(i + 1, j + 1, p + move(p))
        natural = len(f.Wires) == 1 and abs(f.Surface.toShape().Area - f.Area) < 1e-6 * max(f.Area, 1.0)
        if natural:
            face = s.toShape()          # the whole patch: its own edges, sewn to the rest below
            if f.Orientation == "Reversed":
                face.reverse()
            faces.append(face)
            continue
        wires = []
        for w in f.Wires:
            es = [new_edge(e) for e in w.Edges]
            wires.append(Part.Wire(Part.__sortEdges__(es)))
        outer = f.OuterWire
        oi = [k for k, w in enumerate(f.Wires) if w.isSame(outer)][0]
        face = Part.Face(s, wires[oi])
        inner = [w for k, w in enumerate(wires) if k != oi]
        if inner:
            face = face.cutHoles(inner) or face
        face.fix(tol, tol, tol)
        faces.append(face)
    from . import sewtol
    sewn = sewtol.sewn(faces, tol)
    shells = sewn.Shells
    if not nurbs.Solids:
        # a surface body (Freeform on a surface, look audit AJ3): it stays a surface
        if shells and len(shells) == 1 and len(shells[0].Faces) == len(faces):
            return shells[0]
        if len(faces) == 1:
            return faces[0]
        raise RuntimeError("The deformed faces could not be joined")
    if not shells:
        raise RuntimeError("The deformed faces could not be joined")
    solid = Part.Solid(shells[0])
    solid.fix(tol, tol, tol)
    if solid.Volume < 0:
        solid.reverse()
    return solid


POWERS = {"Minimum": 4, "Medium": 2, "Maximum": 1}     # Stiffness: a stiffer part spreads the deform wider
_POWER = [2]


def _falloff(t):
    return (1 - t * t) ** _POWER[0] if t < 1 else 0.0


def _held(obj, field):
    """Deform Region > Fixed curves/edges/faces: points on them stay; near them they move less."""
    fixed = [shape for _, shape in sf.elements(obj, "Fixed")] if "Fixed" in obj.PropertiesList else []
    if not fixed:
        return field
    held = Part.makeCompound(fixed)
    reach = max(float(getattr(obj, "Radius", 20.0)) * 0.5, 1e-3)

    def weighted(p):
        move = field(p)
        if move.Length < 1e-12:
            return move
        d = Part.Vertex(p).distToShape(held)[0]
        w = min(1.0, d / reach)
        return move * (w * w * (3 - 2 * w))
    return weighted


def _direction(obj, fallback):
    picked = sf.elements(obj, "Direction")
    d = None
    if picked:
        shape = picked[0][1]
        if shape.ShapeType == "Face":
            d = shape.normalAt(*shape.Surface.parameter(shape.CenterOfMass)) if not isinstance(shape.Surface, Part.Plane) \
                else shape.Surface.Axis
        elif shape.Edges and len(shape.Edges[0].Vertexes) == 2:
            d = shape.Edges[0].Vertexes[1].Point - shape.Edges[0].Vertexes[0].Point
        elif shape.Edges and hasattr(shape.Edges[0].Curve, "Direction"):
            d = shape.Edges[0].Curve.Direction
        elif shape.Faces:
            d = shape.Faces[0].normalAt(0, 0)
    d = V(d if d is not None else fallback)
    if d.Length < 1e-12:
        raise RuntimeError("Pick a direction for the deform")
    d.normalize()
    return -d if getattr(obj, "Reverse", False) else d


def _point_field(obj, base):
    picked = sf.elements(obj, "Point")
    if not picked:
        return None
    shape = picked[0][1]
    if shape.ShapeType == "Vertex":
        centre = shape.Point
        faces = [f for f in base.Faces if f.distToShape(shape)[0] < 1e-6]
        normal = V()
        for f in faces:
            normal += f.normalAt(*f.Surface.parameter(centre))
    else:
        face = shape.Faces[0] if shape.Faces else None
        if face is None:
            raise RuntimeError("Pick a point or a face for the deform point")
        centre = face.CenterOfMass
        centre = face.Surface.value(*face.Surface.parameter(centre))
        normal = face.normalAt(*face.Surface.parameter(centre))
    move = _direction(obj, normal) * float(obj.Distance)
    if not getattr(obj, "DeformRegion", True):

        # deform a ridge along the line through the point parallel to it
        box = base.BoundBox
        radius = max(box.DiagonalLength, 1e-6)
        axis = None
        for _o, shape in (sf.elements(obj, "Axis") if "Axis" in obj.PropertiesList else []):
            edges = shape.Edges
            if edges and edges[0].Curve.TypeId == "Part::GeomLine":
                a = edges[0].Vertexes
                axis = (a[-1].Point - a[0].Point)
                if axis.Length > 1e-9:
                    axis.normalize()
                else:
                    axis = None
        if axis is not None:
            def along(p, axis=axis):
                d = p - centre
                return (d - axis * d.dot(axis)).Length
            return lambda p: move * _falloff(along(p) / radius)
        return lambda p: move * _falloff((p - centre).Length / radius)
    radius = float(obj.Radius)
    if radius <= 0:
        raise RuntimeError("The deform region radius must be more than 0")
    return lambda p: move * _falloff((p - centre).Length / radius)


def _curve_field(obj, base):
    first = [s for _, shape in sf.elements(obj, "Initial") for s in shape.Edges]
    second = [s for _, shape in sf.elements(obj, "Target") for s in shape.Edges]
    if not first or not second:
        return None
    if len(first) != len(second):
        raise RuntimeError("Pick as many target curves as initial curves (%d and %d)" % (len(first), len(second)))
    pairs = []
    for a, b in zip(first, second):
        # by the curves' own parameters (an edge's vertex order can run the other way)
        a0, a1 = a.valueAt(a.FirstParameter), a.valueAt(a.LastParameter)
        b0, b1 = b.valueAt(b.FirstParameter), b.valueAt(b.LastParameter)
        same = (a0 - b0).Length + (a1 - b1).Length
        turned = (a0 - b1).Length + (a1 - b0).Length
        pairs.append((a, b, turned < same))
    radius = float(obj.Radius)
    if radius <= 0:
        raise RuntimeError("The deform region radius must be more than 0")

    def field(p):
        total = V()
        for a, b, turned in pairs:
            point = a.Curve.parameter(p)
            point = min(max(point, a.FirstParameter), a.LastParameter)
            q0 = a.valueAt(point)
            t = (point - a.FirstParameter) / max(a.LastParameter - a.FirstParameter, 1e-12)
            if turned:
                t = 1 - t
            q1 = b.valueAt(b.FirstParameter + t * (b.LastParameter - b.FirstParameter))
            total += (q1 - q0) * _falloff((p - q0).Length / radius)
        return total
    return field


TOOL_TYPES = ("Polygon", "Rectangle", "Circle", "Ellipse", "Ellipsoid", "Sphere", "Select body")


def _frame(d):
    """Two directions square to d."""
    x = V(1, 0, 0) if abs(d.x) < 0.9 else V(0, 1, 0)
    x = (x - d * x.dot(d)).normalize()
    return x, d.cross(x).normalize()


def built_in_tool(kind, centre, d, size, size2, depth, sides=6):
    ""


    import math
    x, y = _frame(d)
    a, b = size / 2.0, (size2 or size) / 2.0
    rot = App.Rotation(x, y, d, "ZXY")
    if kind in ("Sphere", "Ellipsoid"):
        r = a
        solid = Part.makeSphere(r)
        if kind == "Ellipsoid":
            m = App.Matrix()
            m.scale(1.0, b / r, max(depth, 1e-3) / r)
            solid = solid.transformGeometry(m)
            solid.Placement = App.Placement(centre, rot)            # its tip goes depth into the part
        else:
            solid.Placement = App.Placement(centre + d * (depth - r), rot)
        return solid
    if kind == "Rectangle":
        pts = [V(-a, -b, 0), V(a, -b, 0), V(a, b, 0), V(-a, b, 0)]
        wire = Part.makePolygon(pts + [pts[0]])
    elif kind == "Polygon":
        pts = [V(a * math.cos(2 * math.pi * k / sides), a * math.sin(2 * math.pi * k / sides), 0) for k in range(sides)]
        wire = Part.makePolygon(pts + [pts[0]])
    elif kind == "Ellipse" and abs(a - b) > 1e-9:
        e = Part.Ellipse(V(), max(a, b), min(a, b))
        wire = Part.Wire(e.toShape())
        if b > a:
            wire.rotate(V(), V(0, 0, 1), 90)
    else:
        wire = Part.Wire(Part.makeCircle(a))
    height = max(depth, 1e-3) * 2.0
    solid = Part.Face(wire).extrude(V(0, 0, height))
    try:
        solid = solid.makeFillet(min(a, b, height) * 0.25, [e for e in solid.Edges
                                                             if abs(e.BoundBox.ZMin - height) < 1e-6 and abs(e.BoundBox.ZMax - height) < 1e-6])
    except Exception as _fw_err:
        _fw_log("deform.py:289", _fw_err)
    solid.Placement = App.Placement(V(), App.Rotation(x, y, d, "ZXY"))
    # the pad stands on the far side: its rounded end goes depth into the part along d
    solid.translate(centre + d * (depth - height))
    return solid


def _tool_solid(obj, target):
    """(tool solid, push direction) for Surface push, or (None, None)."""
    kind = getattr(obj, "ToolType", "Select body") or "Select body"
    if kind == "Select body":
        tool = obj.Tool
        if tool is None:
            return None, None
        shape = Part.getShape(tool)
        if shape.isNull() or not shape.Solids:
            raise RuntimeError("The tool body has no solid")
        solid = shape.Solids[0] if len(shape.Solids) == 1 else shape
        return solid, _direction(obj, target.CenterOfMass - solid.CenterOfMass)
    picked = sf.elements(obj, "Point")
    if picked:
        shape = picked[0][1]
        centre = shape.Point if shape.ShapeType == "Vertex" else shape.Faces[0].CenterOfMass
        faces = [f for f in target.Faces if f.distToShape(Part.Vertex(centre))[0] < 1e-6]
        normal = faces[0].normalAt(*faces[0].Surface.parameter(centre)) if faces else V(0, 0, 1)
    else:
        bb = target.BoundBox
        centre, normal = V(bb.Center.x, bb.Center.y, bb.ZMax), V(0, 0, 1)
    d = _direction(obj, normal * -1)
    solid = built_in_tool(kind, centre, d, float(getattr(obj, "ToolSize", 20.0)), float(getattr(obj, "ToolSize2", 0.0)),
                          float(getattr(obj, "Distance", 10.0)), int(getattr(obj, "ToolSides", 6) or 6))
    return solid, d


def _push_field(obj, base):
    target = base.Solids[0] if base.Solids else base
    solid, d = _tool_solid(obj, target)
    if solid is None:
        return None
    reach = solid.BoundBox.DiagonalLength + base.BoundBox.DiagonalLength

    def field(p):
        if not solid.isInside(p, 1e-6, True):
            return V()
        lo, hi = 0.0, reach
        for _ in range(30):
            mid = (lo + hi) / 2
            if solid.isInside(p + d * mid, 1e-6, True):
                lo = mid
            else:
                hi = mid
        return d * hi
    return field


def _deform(obj, base):
    if base is None or base.isNull():
        return None, None
    _POWER[0] = POWERS.get(getattr(obj, "Stiffness", "Medium"), 2)
    field = {"Point": _point_field, "Curve to curve": _curve_field, "Surface push": _push_field}[obj.Type](obj, base)
    if field is None:
        return None, None
    field = _held(obj, field)
    spans = 2 + int(obj.Accuracy)
    solids = base.Solids or [base]
    out = []
    for solid in solids:
        try:
            out.append(warp(solid, field, spans))
        except Exception as error:
            raise RuntimeError("The deform could not be made with these settings (%s)" % error)
    if obj.Type == "Surface push" and getattr(obj, "Tool", None) is not None and \
            getattr(obj, "ToolType", "Select body") == "Select body":
        try:
            if obj.Tool.ViewObject is not None:
                obj.Tool.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("deform.py:366", _fw_err)
    return (out[0] if len(out) == 1 else Part.makeCompound(out)), None


DEFORM = sf.Spec(
    "SWStyle_Deform", "Deform", "Deform",
    "Bends the part smoothly: round a point, from curves to curves, or pushed by a tool body.",
    "FEATURES_DEFORM", "Part_Offset",
    [Field("Type", "radio", "Deform Type", "Point", values=["Point", "Curve to curve", "Surface push"],
           box="Deform Type"),
     Field("Point", "pick", "Deform point", what=("Vertex", "Face"), optional=True,
           shown=lambda o: o.Type == "Point" or (o.Type == "Surface push" and getattr(o, "ToolType", "") != "Select body"), tip="A vertex, or a point on a face"),
     Field("Distance", "length", "Deform distance", 10.0,
           shown=lambda o: o.Type == "Point" or (o.Type == "Surface push" and getattr(o, "ToolType", "") != "Select body")),
     Field("Initial", "pick", "Initial curves", what=("Edge",), many=True, optional=True,
           shown=lambda o: o.Type == "Curve to curve"),
     Field("Target", "pick", "Target curves", what=("Edge",), many=True, optional=True,
           shown=lambda o: o.Type == "Curve to curve"),
     Field("ToolType", "enum", "Tool body", "Ellipse", values=list(TOOL_TYPES), shown=lambda o: o.Type == "Surface push",
           legacy="Select body", tip="Tool bodies, or Select body for a body of the part"),
     Field("Tool", "pick", "Tool body", what="Object", optional=True,
           shown=lambda o: o.Type == "Surface push" and getattr(o, "ToolType", "Select body") == "Select body", tip="The body that pushes into the part"),
     Field("ToolSize", "length", "Tool size", 20.0,
           shown=lambda o: o.Type == "Surface push" and getattr(o, "ToolType", "") != "Select body"),
     Field("ToolSize2", "length", "Tool size 2", 0.0, tip="Rectangle, ellipse, ellipsoid: the second size (0: the same as the first)",
           shown=lambda o: o.Type == "Surface push" and getattr(o, "ToolType", "") in ("Rectangle", "Ellipse", "Ellipsoid")),
     Field("ToolSides", "int", "Polygon sides", 6, low=3, high=24,
           shown=lambda o: o.Type == "Surface push" and getattr(o, "ToolType", "") == "Polygon"),
     Field("Direction", "pick", "Deform direction", what=("Edge", "Face", ""),
           optional=True, shown=lambda o: o.Type != "Curve to curve", tip="An edge, face or plane; empty: the face's normal"),
     Field("Reverse", "bool", "Reverse direction", False, shown=lambda o: o.Type != "Curve to curve"),
     Field("ShowPreview", "bool", "Show preview", True),
     Field("DeformRegion", "bool", "Deform region", True, shown=lambda o: o.Type == "Point", box="Deform Region",
           tip="On: the deform fades out within the radius; off: the whole body takes part"),
     Field("Radius", "length", "Deform region radius", 20.0,
           shown=lambda o: o.Type == "Curve to curve" or (o.Type == "Point" and getattr(o, "DeformRegion", True)),
           box="Deform Region"),
     Field("Fixed", "pick", "Fixed curves/edges/faces", what=("Edge", "Face"), many=True, optional=True,
           box="Deform Region", tip="Geometry that stays where it is; the deform fades out near it"),
     Field("Axis", "pick", "Deform axis", what=("Edge",), optional=True, box="Shape Options",
           shown=lambda o: o.Type == "Point" and not getattr(o, "DeformRegion", True),
           tip="A straight edge: the deform rises along a line through the point, parallel to it"),
     Field("Stiffness", "radio", "Stiffness", "Medium", values=["Minimum", "Medium", "Maximum"], box="Shape Options",
           tip="Maximum spreads the deform wider and smoother, Minimum keeps it close to the point"),
     Field("Accuracy", "int", "Shape accuracy", 6, low=1, high=10, tip="1 coarse .. 10 fine", box="Shape Options")],
    _deform, refine=False, first_pick="Point")


# --------------------------------------------------------------------------- Freeform
def _heights(text, n, m):
    """The control point offsets: rows (direction 2) of numbers (direction 1), "0 5 0 / 0 8 0"."""
    rows = [r for r in (text or "").replace(";", "/").split("/")]
    out = [[0.0] * n for _ in range(m)]
    for j, row in enumerate(rows[:m]):
        for i, value in enumerate(row.replace(",", " ").split()[:n]):
            try:
                out[j][i] = float(value)
            except ValueError:
                raise RuntimeError("Point offsets: %r is not a number" % value)
    return out


def symmetric(heights, sym1=False, sym2=False):
    ""

    m = len(heights)
    n = len(heights[0]) if heights else 0
    out = [row[:] for row in heights]
    if sym1:
        for row in out:
            for i in range(n // 2):
                row[n - 1 - i] = row[i]
    if sym2:
        for j in range(m // 2):
            out[m - 1 - j] = out[j][:]
    return out


def _freeform(obj, base):
    _POWER[0] = 2
    picked = sf.elements(obj, "Face")
    if not picked or base is None or base.isNull():
        return None, None
    face = picked[0][1]
    index = next((i for i, f in enumerate(base.Faces) if f.isSame(face)), None)
    if index is None:
        index = next((i for i, f in enumerate(base.Faces) if abs(f.Area - face.Area) < 1e-6 and
                      f.CenterOfMass.distanceToPoint(face.CenterOfMass) < 1e-6), None)
    if index is None:
        raise RuntimeError("The face is not on the part")
    n, m = max(1, int(obj.Curves1)), max(1, int(obj.Curves2))
    heights = symmetric(_heights(obj.Offsets, n, m), getattr(obj, "Symmetry1", False), getattr(obj, "Symmetry2", False))
    reach_pts = 2.5 if getattr(obj, "CurveType", "Through points") == "Control polygon" else 1.5
    if not any(h for row in heights for h in row):
        raise RuntimeError("Give the control points an offset (Point offsets)")
    target = base.Faces[index]
    u0, u1, v0, v1 = target.ParameterRange
    reach = max(target.BoundBox.DiagonalLength, 1e-6)
    outer = target.OuterWire
    power = {"Contact": 1, "Tangent": 2, "Curvature": 3}[obj.Boundary]
    sign = -1.0 if obj.Flip else 1.0

    def face_fn(k, f, p):
        su, sv = f.Surface.parameter(p)
        uu = (su - u0) / max(u1 - u0, 1e-12)
        vv = (sv - v0) / max(v1 - v0, 1e-12)
        total = 0.0
        for j in range(m):
            for i in range(n):
                h = heights[j][i]
                if h:
                    du = (uu - (i + 1.0) / (n + 1)) * (n + 1)
                    dv = (vv - (j + 1.0) / (m + 1)) * (m + 1)
                    total += h * _falloff(min(1.0, (du * du + dv * dv) ** 0.5 / reach_pts))
        if not total:
            return V()
        on = f.Surface.value(su, sv)
        edge = Part.Vertex(on).distToShape(outer)[0]
        mask = min(1.0, edge / (0.25 * reach)) ** power
        return target.normalAt(su, sv) * (sign * total * mask)

    spans = 2 + int(obj.Accuracy)
    try:
        solid = warp(base.Solids[0] if len(base.Solids) == 1 else base, lambda p: V(), spans,
                     only={index}, face_fn=face_fn)
    except Exception as error:
        raise RuntimeError("The freeform could not be made with these settings (%s)" % error)
    return solid, None


# --------------------------------------------------------------------------- dragging the points
def _grid_points(obj):
    """[(i, j, point on the face, normal)] of the control points, from the base shape's face."""
    picked = sf.elements(obj, "Face")
    if not picked:
        return []
    face = picked[0][1]
    if face.ShapeType != "Face":
        return []
    n, m = max(1, int(obj.Curves1)), max(1, int(obj.Curves2))
    u0, u1, v0, v1 = face.ParameterRange
    out = []
    for j in range(m):
        for i in range(n):
            u = u0 + (u1 - u0) * (i + 1.0) / (n + 1)
            v = v0 + (v1 - v0) * (j + 1.0) / (m + 1)
            out.append((i, j, face.Surface.value(u, v), face.normalAt(u, v)))
    return out


def _offsets_text(heights):
    fmt = lambda h: ("%.3f" % h).rstrip("0").rstrip(".") or "0"
    return " / ".join(" ".join(fmt(h) for h in row) for row in heights)


try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None


if Gui is not None:
    class _DragFilter(QtCore.QObject):
        def __init__(self, panel):
            super().__init__()
            self.panel = panel

        def eventFilter(self, widget, event):
            if not isinstance(event, QtCore.QEvent):
                return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
            return self.panel.eventFilter(widget, event)

    class FreeformPanel(sf.Panel):
        ""

        PICK = 12          # pixels

        def __init__(self, obj):
            super().__init__(obj)
            self.node = None
            self.coords = None
            self.lines = None
            self.drag = None
            self.views = []
            self.filter = _DragFilter(self)
            gl = [v for v in Gui.getMainWindow().findChildren(QtWidgets.QWidget) if v.inherits("QOpenGLWidget")]
            try:
                size = tuple(Gui.ActiveDocument.ActiveView.getSize())
                gl = [v for v in gl if (v.width() * v.devicePixelRatioF(), v.height() * v.devicePixelRatioF()) == size] or gl
            except Exception as _fw_err:
                _fw_log("deform.py:557", _fw_err)
            for w in gl:            # the 3D view only (not the small preview views)
                w.installEventFilter(self.filter)
                self.views.append(w)
            try:
                self._make_node()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD Freeform: no point handles (%s)\n" % error)
            self._display()

        def _display(self):
            ""

            from . import curvdisplay
            page = self.form[-1] if isinstance(self.form, list) else self.form
            form = page.layout()
            self.transparency = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.transparency.setObjectName("SWFreeformTransparency")
            self.transparency.setRange(0, 100)
            try:
                self._transparency_was = self.obj.ViewObject.Transparency
            except Exception:
                self._transparency_was = 0
            self.transparency.setValue(self._transparency_was)
            self.transparency.valueChanged.connect(self._transparent)
            form.addRow("Face transparency", self.transparency)
            self.curv = curvdisplay.CurvatureDisplay(lambda: self.obj.Shape)
            form.addRow(self.curv)

        def _transparent(self, value):
            try:
                self.obj.ViewObject.Transparency = int(value)
            except Exception as _fw_err:
                _fw_log("deform.py:590", _fw_err)

        # the points in the view
        def _make_node(self):
            from pivy import coin
            self.node = coin.SoSeparator()
            self.node.setName("FreeWorksFreeformPoints")
            try:
                top = coin.SoDepthBuffer()
                top.test = False
                self.node.addChild(top)
            except Exception as _fw_err:
                _fw_log("deform.py:602", _fw_err)
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            self.node.addChild(pick)
            colour = coin.SoBaseColor()
            colour.rgb = (0.1, 0.45, 1.0)
            self.node.addChild(colour)
            style = coin.SoDrawStyle()
            style.pointSize = 9
            style.lineWidth = 2
            self.node.addChild(style)
            self.coords = coin.SoCoordinate3()
            self.node.addChild(self.coords)
            self.lines = coin.SoIndexedLineSet()
            self.node.addChild(self.lines)
            self.marks = coin.SoMarkerSet()
            self.marks.markerIndex = coin.SoMarkerSet.CIRCLE_FILLED_9_9
            self.node.addChild(self.marks)
            Gui.ActiveDocument.ActiveView.getSceneGraph().addChild(self.node)
            self._refresh()

        def _heights(self):
            obj = self.obj
            return _heights(obj.Offsets, max(1, int(obj.Curves1)), max(1, int(obj.Curves2)))

        def points(self):
            """[(i, j, shown point, base point, normal)]."""
            heights = self._heights()
            sign = -1.0 if self.obj.Flip else 1.0
            out = []
            for i, j, p, normal in _grid_points(self.obj):
                out.append((i, j, p + normal * (sign * heights[j][i]), p, normal))
            return out

        def _refresh(self):
            if self.coords is None:
                return
            pts = self.points()
            self.coords.point.setValues(0, len(pts), [tuple(p[2]) for p in pts])
            self.coords.point.setNum(len(pts))
            n, m = max(1, int(self.obj.Curves1)), max(1, int(self.obj.Curves2))
            index = []
            if len(pts) == n * m:
                for j in range(m):                  # control curves along direction 1
                    if n > 1:
                        index += [j * n + i for i in range(n)] + [-1]
                for i in range(n):                  # and along direction 2
                    if m > 1:
                        index += [j * n + i for j in range(m)] + [-1]
            self.lines.coordIndex.setValues(0, len(index), index)
            self.lines.coordIndex.setNum(len(index))

        def _show(self):
            super()._show()
            try:
                self._refresh()
            except Exception as _fw_err:
                _fw_log("deform.py:659", _fw_err)

        # mouse
        def _screen(self, widget, point):
            view = Gui.ActiveDocument.ActiveView
            x, y = view.getPointOnViewport(point)
            ratio = widget.devicePixelRatioF() if hasattr(widget, "devicePixelRatioF") else 1.0
            return x / ratio, widget.height() - y / ratio

        def _ray(self, widget, pos):
            view = Gui.ActiveDocument.ActiveView
            ratio = widget.devicePixelRatioF() if hasattr(widget, "devicePixelRatioF") else 1.0
            x, y = pos.x() * ratio, (widget.height() - pos.y()) * ratio
            return view.getPoint(int(x), int(y)), V(*view.getViewDirection())

        def nearest(self, widget, pos):
            best = None
            for k, item in enumerate(self.points()):
                sx, sy = self._screen(widget, item[2])
                d = ((sx - pos.x()) ** 2 + (sy - pos.y()) ** 2) ** 0.5
                if d <= self.PICK and (best is None or d < best[0]):
                    best = (d, k, item)
            return best

        def height_at(self, widget, pos, base, normal):
            """The offset along the normal nearest to the mouse's ray."""
            origin, look = self._ray(widget, pos)
            w0 = base - origin
            b = normal.dot(look)
            d, e = normal.dot(w0), look.dot(w0)
            den = 1.0 - b * b
            if abs(den) < 1e-9:          # looking straight down the normal: no change
                return None
            return (b * e - d) / den

        def set_height(self, i, j, h):
            heights = self._heights()
            heights[j][i] = h * (-1.0 if self.obj.Flip else 1.0)
            self.obj.Offsets = _offsets_text(heights)
            box = self.widgets.get("Offsets")
            if box is not None:
                box.blockSignals(True)
                box.setPlainText(self.obj.Offsets)
                box.blockSignals(False)

        def eventFilter(self, widget, event):
            if not isinstance(event, QtCore.QEvent):
                return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
            t = event.type()
            try:
                if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                    hit = self.nearest(widget, event.position())
                    if hit is None:
                        return False
                    _, _, (i, j, shown, base, normal) = hit
                    self.drag = (i, j, base, normal)
                    return True
                if t == QtCore.QEvent.MouseMove and self.drag is not None:
                    i, j, base, normal = self.drag
                    h = self.height_at(widget, event.position(), base, normal)
                    if h is not None:
                        self.set_height(i, j, h)
                        self._refresh()          # the point follows the mouse; the shape on release
                    return True
                if t == QtCore.QEvent.MouseButtonRelease and self.drag is not None:
                    self.drag = None
                    self.obj.Document.recompute()
                    self._show()
                    return True
            except Exception as error:
                self.drag = None
                App.Console.PrintLog("FreeCAD Freeform drag: %s\n" % error)
            return False

        def _close(self):
            for w in self.views:
                try:
                    w.removeEventFilter(self.filter)
                except Exception as _fw_err:
                    _fw_log("deform.py:738", _fw_err)
            self.views = []
            try:
                if self.node is not None:
                    Gui.ActiveDocument.ActiveView.getSceneGraph().removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("deform.py:744", _fw_err)
            self.node = None
            try:
                self.curv.close()
                self.obj.ViewObject.Transparency = self._transparency_was
            except Exception as _fw_err:
                _fw_log("deform.py:750", _fw_err)
            super()._close()

    class FreeformSurfacePanel(FreeformPanel):
        ""


        def accept(self):
            sources = [o for o, _ in sf.elements(self.obj, "Face")]
            if not super().accept():
                return False
            for o in sources:
                try:
                    if o.ViewObject is not None:
                        o.ViewObject.Visibility = False
                except Exception as _fw_err:
                    _fw_log("deform.py:surface", _fw_err)
            return True


FREEFORM = sf.Spec(
    "SWStyle_Freeform", "Freeform", "Freeform",
    "Pushes and pulls a face by control points on control curves, keeping its edges.",
    "FEATURES_FREEFORM", "Surface_GeomFillSurface",
    [Field("Face", "pick", "Face to deform", what=("Face",)),
     Field("Boundary", "enum", "Boundary condition", "Contact", tip="On all edges", values=["Contact", "Tangent", "Curvature"]),
     Field("Curves1", "int", "Control curves, direction 1", 1, low=1, high=9),
     Field("Curves2", "int", "Control curves, direction 2", 1, low=1, high=9),
     Field("Offsets", "text", "Point offsets", "10",
           tip="Drag a control point in the view, or type one number per point along direction 1, rows split by /"),
     Field("Flip", "bool", "Flip direction", False),
     Field("Symmetry1", "bool", "Direction 1 symmetry", False),
     Field("Symmetry2", "bool", "Direction 2 symmetry", False),
     Field("CurveType", "enum", "Control type", "Through points", values=["Through points", "Control polygon"]),
     Field("Accuracy", "int", "Shape accuracy", 6, low=1, high=10, tip="1 coarse .. 10 fine")],
    _freeform, refine=False, panel=FreeformPanel if Gui is not None else None)


def _freeform_surface(obj, base):
    """Freeform on a surface body (no solid in the part): the picked face's surface body is the base."""
    picked = sf.elements(obj, "Face")
    if not picked:
        return None, None
    source = picked[0][0]
    shape = Part.getShape(source)
    if shape.isNull() or not shape.Faces:
        raise RuntimeError("Pick a face of a surface body")
    return _freeform(obj, shape)


FREEFORM_SURFACE = sf.Spec(
    "SWStyle_Freeform", "Freeform", "Freeform", FREEFORM.tip, FREEFORM.icon,
    "Surface_GeomFillSurface", FREEFORM.fields, _freeform_surface, refine=False, needs_body=False,
    panel=FreeformSurfacePanel if Gui is not None else None)
FREEFORM_SURFACE.internal = "FreeformSurface"
sf.SPECS["FreeformSurface"] = FREEFORM_SURFACE
sf.SPECS[FREEFORM.internal] = FREEFORM


def _surface_bodies(doc):
    from . import deleteface
    return [o for o in doc.Objects if deleteface.free_source(o) is not None and not Part.getShape(o).Solids]


if Gui is not None:
    class FreeformCommand(sf.Command):
        ""


        def IsActive(self):
            doc = App.ActiveDocument
            if doc is None or Gui.Control.activeDialog():
                return False
            return sf.ready(self.spec, doc) or bool(_surface_bodies(doc))

        def Activated(self):
            doc = App.ActiveDocument
            if doc is not None and not sf.ready(self.spec, doc) and _surface_bodies(doc):
                from . import surfacefeatures as surf
                picks = {k: v for k, v in sf.preselected(FREEFORM_SURFACE).items()
                         if k == "Face" and v and v[0][0] in _surface_bodies(doc)}
                surf.make(FREEFORM_SURFACE, picks=picks)
                return
            super().Activated()


def register():
    sf.register(DEFORM)
    try:
        if FREEFORM.command not in Gui.listCommands():
            Gui.addCommand(FREEFORM.command, FreeformCommand(FREEFORM))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Freeform command not added (%s)\n" % error)
