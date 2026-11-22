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
from PySide import QtCore, QtGui, QtWidgets


def _mark(box, active, need=False):
    try:
        from . import pmboxes
        pmboxes.mark(box, active, need=need)
    except Exception:
        box.setStyleSheet("QListWidget { background: %s; }" % ("#cfe3ff" if active else "white"))


def _error_css():
    try:
        from .propertymanager import error_css
        return error_css()
    except Exception:
        return "color: #c00000;"

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/RefPlane"
TITLE = "Plane"
Z = App.Vector(0, 0, 1)

# constraint -> (label, FreeCAD constraint icon)
CONSTRAINTS = {
    "Coincident": ("Coincident", "Constraint_PointOnPoint"),
    "Parallel": ("Parallel", "Constraint_Parallel"),
    "Perpendicular": ("Perpendicular", "Constraint_Perpendicular"),
    "Tangent": ("Tangent", "Constraint_Tangent"),
    "Distance": ("Offset distance", "Constraint_Length"),
    "Angle": ("Angle", "Constraint_InternalAngle"),
    "MidPlane": ("Mid Plane", "Constraint_Symmetric"),
    "Project": ("Project", "Constraint_PointOnObject"),
    "ParallelScreen": ("Parallel to Screen", "Constraint_Parallel"),
}

OFFERED = {
    "plane": ("Coincident", "Parallel", "Perpendicular", "Distance", "Angle", "MidPlane"),
    "line": ("Coincident", "Perpendicular", "Parallel"),
    "curve": ("Perpendicular", "Coincident"),
    "point": ("Coincident", "Project", "ParallelScreen"),
    "cylinder": ("Tangent",),
}


class PlaneError(Exception):
    pass


def _params():
    return App.ParamGet(PARAMS)


# --------------------------------------------------------------------------- references
def shape_of(obj, sub):
    """The reference's shape in its body's coordinates (where the datum plane is attached)."""
    import Part
    if sub:
        return obj.Shape.getElement(sub)
    return Part.getShape(obj)


def kind_of(obj, sub):
    """'plane', 'line', 'curve', 'point', 'cylinder' or None."""
    try:
        s = shape_of(obj, sub)
    except Exception:
        return None
    if s is None or s.isNull():
        return None
    if s.ShapeType == "Face":
        name = type(s.Surface).__name__
        if name == "Plane":
            return "plane"
        if name in ("Cylinder", "Cone"):
            return "cylinder"

        return "cylinder" if name in ("Sphere", "Toroid", "BSplineSurface", "BezierSurface",
                                      "SurfaceOfRevolution", "SurfaceOfExtrusion", "OffsetSurface") else None
    if s.ShapeType == "Edge":
        return "line" if type(s.Curve).__name__ in ("Line", "LineSegment") else "curve"
    if s.ShapeType == "Vertex":
        return "point"
    return None


def _plane_of(obj, sub):
    f = shape_of(obj, sub).Faces[0]
    return App.Vector(f.Surface.Position), App.Vector(f.normalAt(0, 0)).normalize()


def _line_of(obj, sub):
    e = shape_of(obj, sub).Edges[0]
    if len(e.Vertexes) >= 2:
        p = e.Vertexes[0].Point
        d = e.Vertexes[-1].Point - p
    else:
        p, d = e.Curve.Location, e.Curve.Direction
    return App.Vector(p), App.Vector(d).normalize()


def resolve(obj, sub):
    """A pick made through a container (Body > Pad.Face3) as (Pad, 'Face3')."""
    if sub and "." in sub:
        prefix, leaf = sub.rsplit(".", 1)
        try:
            inner = obj.getSubObject(prefix + ".", retType=1)
        except Exception:
            inner = None
        if inner is not None:
            return inner, leaf
    return obj, sub


def _frame_of(obj):
    """The global placement of the coordinates obj's shape is given in (its body or part, else the document)."""
    try:
        owner = obj.getParentGeoFeatureGroup()
        return owner.getGlobalPlacement() if owner is not None else App.Placement()
    except Exception:
        return App.Placement()


def datum_ref(obj, sub, body):
    ""





    try:
        if obj is None or body is None or not sub or not body.isDerivedFrom("PartDesign::Body"):
            return obj, sub
        if obj is body and getattr(body, "Tip", None) is not None and not sub.startswith("Origin"):
            # a face of the body itself: the datum sits in that body, so the body as its reference made a
            # cycle ("The graph must be a DAG", the body left touched); FreeCAD takes the tip feature's face
            return body.Tip, sub
        try:
            from . import sketchcenterlines as sc
            centerlines = sc.is_companion(obj)
        except Exception:
            centerlines = False
        if not centerlines:
            owner = obj.getParentGeoFeatureGroup()
            if owner is body or _frame_of(obj).isSame(body.getGlobalPlacement(), 1e-9):
                return obj, sub         # the same coordinates: FreeCAD attaches to it as it is
        for o in body.Group:
            if o.TypeId == "PartDesign::SubShapeBinder" and getattr(o, "FwDatumRef", "") == obj.Name:
                return o, sub
        binder = body.newObject("PartDesign::SubShapeBinder", "Reference")
        owner = obj.getParentGeoFeatureGroup()
        holders = []
        up = body.getParentGeoFeatureGroup()
        while up is not None:
            holders.append(up)
            up = up.getParentGeoFeatureGroup()
        if owner is None or owner in holders:
            binder.Support = [(obj, [""])]      # beside the body, in a part that holds it (or the document)
        else:
            binder.Support = [(owner, [obj.Name + "."])]    # in another body: through it, so its placement counts
        binder.addProperty("App::PropertyString", "FwDatumRef", "FreeWorks", "The object this datum reference copies")
        binder.setEditorMode("FwDatumRef", 2)
        binder.FwDatumRef = obj.Name
        sketch = getattr(obj, "Sketch", None) if centerlines else None
        binder.Label = "%s centerlines" % sketch.Label if sketch is not None else "Reference (%s)" % obj.Label
        binder.recompute()
        try:
            binder.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("refplane.py:datum_ref-hide", _fw_err)
        return binder, sub
    except Exception as _fw_err:
        _fw_log("refplane.py:datum_ref", _fw_err)
        return obj, sub


def _point_of(obj, sub):
    return App.Vector(shape_of(obj, sub).Vertexes[0].Point)


class Ref:
    """One reference box: the pick, what it is, its constraint and its value."""

    def __init__(self, obj, sub):
        self.obj, self.sub = obj, sub
        self.kind = kind_of(obj, sub)
        self.constraint = None
        self.value = 0.0
        self.flip = False
        self.count = 1
        self.flip_normal = False
        self.on_curve = False       # Normal to curve through a point: Set origin on curve
        self.screen = None          # Parallel to Screen: the view's rotation (a quaternion) when picked

    def support(self):
        return (self.obj, self.sub)

    def name(self):
        if self.sub:
            return "%s@%s" % (self.sub, self.obj.Label)
        return self.obj.Label


def _point_on_line(refs):
    try:
        import Part
        line = next(r for r in refs if r.kind == "line")
        point = next(r for r in refs if r.kind == "point")
        return shape_of(*line.support()).distToShape(Part.Vertex(_point_of(*point.support())))[0] < 1e-6
    except Exception:
        return False


def defaults(refs, distance=10.0, angle=45.0):
    ""
    kinds = sorted(r.kind for r in refs)
    guess = {
        ("plane",): {"plane": "Distance"},
        ("line", "plane"): {"plane": "Angle", "line": "Coincident"},
        ("plane", "plane"): {"plane": "MidPlane"},
        ("plane", "point"): {"plane": "Parallel", "point": "Coincident"},
        ("line", "point"): {"line": "Coincident", "point": "Coincident"},
        ("curve",): {"curve": "Perpendicular"},
        ("curve", "point"): {"curve": "Perpendicular", "point": "Coincident"},
        ("cylinder", "point"): {"cylinder": "Tangent", "point": "Coincident"},
        ("cylinder", "plane"): {"cylinder": "Tangent", "plane": "Perpendicular"},
        ("plane", "point", "point"): {"plane": "Perpendicular", "point": "Coincident"},
    }.get(tuple(kinds), {})
    if kinds and set(kinds) == {"point"}:
        guess = {"point": "Coincident"}
    if tuple(kinds) == ("line", "point") and _point_on_line(refs):
        guess = {"line": "Perpendicular", "point": "Coincident"}     # a line and its own point: normal to it
    for r in refs:
        if r.kind in guess:
            r.constraint = guess[r.kind]
        elif r.constraint not in OFFERED.get(r.kind, ()):
            r.constraint = OFFERED[r.kind][0] if OFFERED.get(r.kind) else None
        if r.constraint == "Distance" and r.value <= 0:
            r.value = distance
        if r.constraint == "Angle" and (r.value <= 0 or r.value > 360):
            r.value = angle
    lines = [r for r in refs if r.kind == "line"]
    if tuple(kinds) == ("line", "line"):
        # two edges: through both when they lie in one plane, else through the first, parallel to the other
        try:
            (pa, da), (pb, db) = _line_of(*lines[0].support()), _line_of(*lines[1].support())
            cross = da.cross(db)
            flat = cross.Length < 1e-9 or abs((pb - pa).dot(cross.normalize())) < 1e-6
        except Exception:
            flat = True
        lines[0].constraint = "Coincident"
        lines[1].constraint = "Coincident" if flat else "Parallel"
    elif tuple(kinds) == ("line", "line", "point"):
        for r in lines:
            r.constraint = "Parallel"
        next(r for r in refs if r.kind == "point").constraint = "Coincident"


# --------------------------------------------------------------------------- what to attach
class Recipe:
    """How to attach each plane: support, FreeCAD map mode and a way to get its offset."""

    def __init__(self, support, mode, offsets=None, make_offset=None):
        self.support, self.mode = support, mode
        self.offsets = offsets or [App.Placement()]     # one plane per offset
        self.make_offset = make_offset                  # f(base placement) -> [offsets], when it needs the frame


def recipe(refs):
    ""
    rec = _recipe(refs)
    picked = [r for r in refs if r.kind]
    rec.flip_normal = bool(picked and picked[0].flip_normal)
    return rec


def _screen_rotation():
    try:
        return tuple(Gui.ActiveDocument.ActiveView.getCameraOrientation().Q)
    except Exception:
        return (0.0, 0.0, 0.0, 1.0)


def _recipe(refs):
    """The attachment for these references and constraints, else PlaneError with what is missing."""
    picked = [r for r in refs if r.kind]
    if not picked:
        raise PlaneError("Select references and constraints.")
    # a point's Project falls on the other references the way Coincident does here
    combo = sorted((r.kind, "Coincident" if r.constraint == "Project" else r.constraint) for r in picked)
    if combo == [("point", "ParallelScreen")]:
        point = picked[0]
        if point.screen is None:
            point.screen = _screen_rotation()
        rot = App.Rotation(*point.screen)
        # FreeCAD's Translate mode keeps the global axes, so the plane is set at the point, facing
        # the view; the plane keeps its point and follows it after each rebuild (follow)
        at = _point_of(*point.support())
        return Recipe([point.support()], "Deactivated", [App.Placement(at, rot)])

    if combo == [("plane", "Distance")]:
        r = picked[0]
        sign = -1.0 if r.flip else 1.0
        return Recipe([r.support()], "FlatFace",
                      [App.Placement(App.Vector(0, 0, sign * r.value * k), App.Rotation()) for k in range(1, r.count + 1)])
    if combo == [("plane", "Coincident")]:
        return Recipe([picked[0].support()], "FlatFace")
    if combo in ([("line", "Coincident"), ("plane", "Angle")], [("line", "Coincident"), ("plane", "Perpendicular")]):
        plane = next(r for r in picked if r.kind == "plane")
        line = next(r for r in picked if r.kind == "line")
        step = 90.0 if plane.constraint == "Perpendicular" else plane.value
        sign = -1.0 if plane.flip else 1.0
        count = plane.count if plane.constraint == "Angle" else 1
        p, d = _line_of(line.obj, line.sub)

        def turned(base):
            n = base.Rotation.multVec(Z)
            if abs(n.dot(d)) > 1e-6:
                raise PlaneError("The edge or axis must lie along the plane.")
            # the plane moved to hold the line, then turned about it
            shift = n * (p - base.Base).dot(n)
            held = App.Placement(base.Base + shift, base.Rotation)
            out = []
            for k in range(1, count + 1):
                turn = App.Rotation(d, sign * step * k)
                about = App.Placement(p, App.Rotation()) .multiply(App.Placement(App.Vector(), turn)) \
                    .multiply(App.Placement(-p, App.Rotation()))
                out.append(base.inverse().multiply(about.multiply(held)))
            return out
        return Recipe([plane.support()], "FlatFace", make_offset=turned)
    if combo == [("plane", "Parallel"), ("point", "Coincident")]:
        plane = next(r for r in picked if r.kind == "plane")
        point = _point_of(*next(r for r in picked if r.kind == "point").support())

        def moved(base):
            n = base.Rotation.multVec(Z)
            return [App.Placement(App.Vector(0, 0, (point - base.Base).dot(n)), App.Rotation())]
        return Recipe([plane.support()], "FlatFace", make_offset=moved)
    if combo == [("plane", "MidPlane"), ("plane", "MidPlane")]:
        a, b = picked[0], picked[1]
        pb, nb = _plane_of(b.obj, b.sub)

        def middle(base):
            n = base.Rotation.multVec(Z)
            if abs(abs(n.dot(nb)) - 1.0) > 1e-6:

                # where they meet, half way round from the first to the second
                d = n.cross(nb)
                d.normalize()
                angle = math.degrees(math.acos(max(-1.0, min(1.0, n.dot(nb)))))
                # a point on both planes: the first plane's origin moved onto the second along the
                # first plane, at right angles to the meeting line
                along = d.cross(n)
                t = (pb - base.Base).dot(nb) / along.dot(nb)
                p = base.Base + along * t
                turn = App.Placement(p, App.Rotation()).multiply(App.Placement(App.Vector(), App.Rotation(d, angle / 2.0))) \
                    .multiply(App.Placement(-p, App.Rotation()))
                return [base.inverse().multiply(turn.multiply(base))]
            return [App.Placement(App.Vector(0, 0, (pb - base.Base).dot(n) / 2.0), App.Rotation())]
        return Recipe([a.support()], "FlatFace", make_offset=middle)
    if combo == [("point", "Coincident")] * 3:
        return Recipe([r.support() for r in picked], "ThreePointsPlane")
    if combo == [("line", "Coincident"), ("point", "Coincident")]:
        line = next(r for r in picked if r.kind == "line")
        point = next(r for r in picked if r.kind == "point")
        return Recipe([line.support(), point.support()], "ThreePointsPlane")
    if combo in ([("curve", "Perpendicular")], [("line", "Perpendicular")]):
        return Recipe([picked[0].support()], "NormalToEdge")
    if combo in ([("curve", "Perpendicular"), ("point", "Coincident")], [("line", "Perpendicular"), ("point", "Coincident")]):
        curve = next(r for r in picked if r.kind in ("curve", "line"))
        point = next(r for r in picked if r.kind == "point")
        rec = Recipe([curve.support(), point.support()], "NormalToEdge")
        if not curve.on_curve:

            # FreeCAD puts it on the curve, so it is slid across the plane to the point
            at = _point_of(point.obj, point.sub)

            def to_point(base, at=at):
                if at is None:
                    return [App.Placement()]
                local = base.Rotation.inverted().multVec(at - base.Base)
                return [App.Placement(App.Vector(local.x, local.y, 0), App.Rotation())]
            rec.make_offset = to_point
        return rec
    if combo == [("line", "Coincident"), ("plane", "Parallel")]:
        # through the edge, parallel to the plane (the edge must run along the plane)
        plane = next(r for r in picked if r.kind == "plane")
        p, d = _line_of(*next(r for r in picked if r.kind == "line").support())

        def through_line(base):
            n = base.Rotation.multVec(Z)
            if abs(n.dot(d)) > 1e-6:
                raise PlaneError("The edge or axis must run parallel to the plane.")
            return [App.Placement(App.Vector(0, 0, (p - base.Base).dot(n)), App.Rotation())]
        return Recipe([plane.support()], "FlatFace", make_offset=through_line)
    if combo == [("plane", "Perpendicular"), ("point", "Coincident"), ("point", "Coincident")]:
        # through two points, at right angles to the plane
        plane = next(r for r in picked if r.kind == "plane")
        a, b = [_point_of(*r.support()) for r in picked if r.kind == "point"]

        def through_points(base):
            n = base.Rotation.multVec(Z)
            m = (b - a).cross(n)
            if m.Length < 1e-9:
                raise PlaneError("The two points lie along the plane's normal: pick points across it.")
            m.normalize()
            if plane.flip:
                m = -m
            return [base.inverse().multiply(App.Placement(a, App.Rotation(Z, m)))]
        return Recipe([plane.support()], "FlatFace", make_offset=through_points)
    if combo == [("curve", "Coincident")]:

        edge = shape_of(*picked[0].support()).Edges[0]
        if type(edge.Curve).__name__ in ("Circle", "ArcOfCircle", "Ellipse", "ArcOfEllipse"):
            return Recipe([picked[0].support()], "Concentric")
        raise PlaneError("Coincident needs a circle or arc here; pick Perpendicular for a plane across the curve.")
    if combo == [("cylinder", "Tangent"), ("plane", "Angle")]:
        face = next(r for r in picked if r.kind == "cylinder")
        flat = next(r for r in picked if r.kind == "plane")
        return Recipe([flat.support()], "FlatFace", make_offset=lambda base: [_tangent_place(face, flat, base)])
    if combo == [("cylinder", "Tangent"), ("point", "Coincident")]:
        face = next(r for r in picked if r.kind == "cylinder")
        point = next(r for r in picked if r.kind == "point")
        return Recipe([face.support(), point.support()], "TangentPlane")
    if combo == [("cylinder", "Tangent")]:

        face = picked[0]
        shape = shape_of(face.obj, face.sub).Faces[0]
        names = ["Vertex%d" % (i + 1) for i, v in enumerate(face.obj.Shape.Vertexes)
                 if any(v.isSame(w) for w in shape.Vertexes)]
        if not names:
            raise PlaneError("Select another reference to define the plane.")
        radius = getattr(shape.Surface, "Radius", 0.0)
        flip = [App.Placement(App.Vector(0, 0, -2 * radius), App.Rotation(App.Vector(1, 0, 0), 180))] \
            if face.flip and radius else None
        return Recipe([face.support(), (face.obj, names[0])], "TangentPlane", flip)
    if combo in ([("cylinder", "Tangent"), ("plane", "Perpendicular")], [("cylinder", "Tangent"), ("plane", "Parallel")]):
        face = next(r for r in picked if r.kind == "cylinder")
        flat = next(r for r in picked if r.kind == "plane")
        return Recipe([flat.support()], "FlatFace", make_offset=lambda base: [_tangent_place(face, flat, base)])
    lines = _two_lines(picked, combo)
    if lines is not None:
        return lines
    if len(picked) == 1 and picked[0].kind == "point":
        raise PlaneError("Select two more points, or an edge or a plane, to define the plane.")
    if len(picked) == 1:
        raise PlaneError("Select another reference to define the plane.")
    raise PlaneError("These references and constraints do not define a plane. Change a constraint or a reference.")


def _frame(at, x, n):
    """A placement at `at` with its Z along n and its X along x (made square to n)."""
    n = App.Vector(n).normalize()
    x = App.Vector(x) - n * App.Vector(x).dot(n)
    if x.Length < 1e-9:
        x = n.cross(App.Vector(1, 0, 0)) if abs(n.x) < 0.9 else n.cross(App.Vector(0, 1, 0))
    x.normalize()
    y = n.cross(x)
    m = App.Matrix(x.x, y.x, n.x, 0, x.y, y.y, n.y, 0, x.z, y.z, n.z, 0)
    return App.Placement(at, App.Rotation(m))


def _two_lines(picked, combo):
    ""


    lines = [r for r in picked if r.kind == "line"]
    if len(lines) != 2:
        return None
    a, b = lines
    (pa, da), (pb, db) = _line_of(*a.support()), _line_of(*b.support())
    cross = da.cross(db)
    want = None
    if combo == [("line", "Coincident"), ("line", "Parallel")]:
        on = a if a.constraint == "Coincident" else b
        (p, d), (_q, e) = (_line_of(*on.support()), _line_of(*(b if on is a else a).support()))
        n = d.cross(e)
        if n.Length < 1e-9:
            raise PlaneError("The two lines are parallel: a plane through one parallel to the other is not defined. "
                             "Add a point.")
        want, holder = _frame(p, d, n), on
    elif combo == [("line", "Coincident"), ("line", "Coincident")]:
        gap = pb - pa
        if cross.Length < 1e-9:
            n = da.cross(gap)
            if n.Length < 1e-9:
                raise PlaneError("The two lines are on one line: select another reference.")
        else:
            if abs(gap.dot(cross.normalize())) > 1e-6:
                raise PlaneError("The two lines are not in one plane.")
            n = cross
        want, holder = _frame(pa, da, n), a
    elif combo == [("line", "Coincident"), ("line", "Perpendicular")]:
        on = a if a.constraint == "Coincident" else b
        other = b if on is a else a
        (p, d), (_q, e) = _line_of(*on.support()), _line_of(*other.support())
        if abs(d.dot(e)) > 1e-6:
            raise PlaneError("The lines are not at right angles: no plane through one is perpendicular to the other.")
        want, holder = _frame(p, d, e), on
    elif combo == [("line", "Parallel"), ("line", "Parallel"), ("point", "Coincident")]:
        if cross.Length < 1e-9:
            raise PlaneError("The two lines are parallel: select another reference.")
        point = next(r for r in picked if r.kind == "point")
        want, holder = _frame(_point_of(*point.support()), da, cross), a
    else:
        return None
    for r in lines:
        if r.flip:
            want = want.multiply(App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 180)))
            break
    return Recipe([holder.support()], "NormalToEdge", make_offset=lambda base: [base.inverse().multiply(want)])


def _tangent_place(face, flat, base):
    """The plane tangent to the cylinder and perpendicular (or parallel) to the flat reference, as
    an offset from the flat reference's frame."""
    surface = shape_of(face.obj, face.sub).Faces[0].Surface
    if not hasattr(surface, "Radius") or not hasattr(surface, "Axis"):
        raise PlaneError("Tangent here needs a cylindrical face.")
    axis, centre, radius = App.Vector(surface.Axis), App.Vector(surface.Center), surface.Radius
    _, n = _plane_of(flat.obj, flat.sub)
    if flat.constraint == "Angle":
        # turned from the flat reference's normal about the cylinder's axis by the angle: 0 is
        # parallel to it, 90 at right angles
        if abs(n.dot(axis)) > 1e-6:
            raise PlaneError("The cylinder's axis must run along the plane for a tangent plane at an angle.")
        m = App.Rotation(axis, -flat.value if flat.flip else flat.value).multVec(n)
    elif flat.constraint == "Perpendicular":
        m = n.cross(axis)
        if m.Length < 1e-9:
            raise PlaneError("The plane is at right angles to the cylinder's axis: any tangent plane is "
                             "perpendicular to it. Pick another reference.")
    else:
        if abs(n.dot(axis)) > 1e-6:
            raise PlaneError("A plane parallel to this one cannot touch the cylinder along its length.")
        m = App.Vector(n)
    m.normalize()
    if face.flip:
        m = -m
    # the tangent line nearest the flat reference's origin side unless flipped
    point = centre + m * radius
    target = App.Placement(point, App.Rotation(Z, m))
    return base.inverse().multiply(target)


def body_of(doc):
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception:
        body = None
    if body is not None:
        return body
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    return bodies[0] if len(bodies) == 1 else None


def place(planes, rec):
    """Attaches the datum planes (one per offset); extra planes are hidden."""
    doc = planes[0].Document
    if rec.mode == "Deactivated":
        offsets = rec.offsets
        if getattr(rec, "flip_normal", False):
            offsets = [off.multiply(App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 180))) for off in offsets]
        for pl, off in zip(planes, offsets):
            pl.MapMode = "Deactivated"
            pl.AttachmentSupport = None
            pl.AttachmentOffset = App.Placement()
            pl.Placement = off
        doc.recompute()
        return len(offsets)
    for pl in planes:
        try:
            pl.MapMode = "Deactivated"      # a new support may not suit the last mode
            pl.AttachmentSupport = rec.support
            pl.MapMode = rec.mode
        except Exception as error:
            raise PlaneError(str(error))
        pl.AttachmentOffset = App.Placement()
    doc.recompute()
    offsets = rec.offsets
    if rec.make_offset is not None:
        offsets = rec.make_offset(planes[0].Placement)
    if getattr(rec, "flip_normal", False):
        offsets = [off.multiply(App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 180))) for off in offsets]
    for pl, off in zip(planes, offsets):
        pl.AttachmentOffset = off
    doc.recompute()
    bad = [pl for pl in planes if "Invalid" in pl.State]
    if bad:
        raise PlaneError(bad[0].getStatusString())
    return len(offsets)


# --------------------------------------------------------------------------- the PropertyManager
def _icon(name):
    """FreeCAD's Sketcher constraint icon (its resources load with SketcherGui)."""
    try:
        import SketcherGui  # noqa: F401
    except Exception as _fw_err:
        _fw_log("refplane.py:583", _fw_err)
    for path in (":/icons/constraints/%s.svg" % name, ":/icons/%s.svg" % name):
        if QtCore.QFile.exists(path):
            return QtGui.QIcon(path)
    return QtGui.QIcon()


class _RefBox(QtWidgets.QWidget):
    """First, Second or Third Reference: the pick, the constraint buttons, the value."""

    def __init__(self, panel, index):
        super().__init__()
        self.panel, self.index = panel, index
        self.setWindowTitle(("First", "Second", "Third")[index] + " Reference")
        lay = QtWidgets.QVBoxLayout(self)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)   # no stretched gap (pkg124)
        self.pick = QtWidgets.QListWidget(self)
        self.pick.setObjectName("SWPlaneRef%d" % (index + 1))
        self.pick.setFixedHeight(26)
        lay.addWidget(self.pick)
        self.buttons = {}
        for key, (label, icon) in CONSTRAINTS.items():
            b = QtWidgets.QToolButton(self)
            b.setObjectName("SWPlane%s%d" % (key, index + 1))
            b.setText(label)
            b.setIcon(_icon(icon))
            b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _c=False, k=key: panel.set_constraint(self.index, k))
            lay.addWidget(b)
            self.buttons[key] = b
        row = QtWidgets.QHBoxLayout()
        from .pmspin import TrimSpin
        self.value = TrimSpin(self)
        self.value.setObjectName("SWPlaneValue%d" % (index + 1))
        self.value.setDecimals(3)
        self.value.setRange(0.0, 1e6)
        self.value.setKeyboardTracking(False)
        row.addWidget(self.value)
        lay.addLayout(row)
        self.flip = QtWidgets.QCheckBox("Flip offset", self)
        self.flip.setObjectName("SWPlaneFlip%d" % (index + 1))
        lay.addWidget(self.flip)
        row = QtWidgets.QHBoxLayout()
        self.count_label = QtWidgets.QLabel("Number of planes to create:", self)
        self.count = QtWidgets.QSpinBox(self)
        self.count.setObjectName("SWPlaneCount%d" % (index + 1))
        self.count.setRange(1, 100)
        row.addWidget(self.count_label)
        row.addWidget(self.count)
        lay.addLayout(row)
        self.flip_normal = QtWidgets.QCheckBox("Flip normal", self)
        self.flip_normal.setObjectName("SWPlaneFlipNormal%d" % (index + 1))
        lay.addWidget(self.flip_normal)
        self.on_curve = QtWidgets.QCheckBox("Set origin on curve", self)
        self.on_curve.setObjectName("SWPlaneOriginOnCurve%d" % (index + 1))
        lay.addWidget(self.on_curve)
        self.on_curve.toggled.connect(lambda on: panel.set_on_curve(self.index, on))
        self.flip_normal.toggled.connect(lambda on: panel.set_flip_normal(self.index, on))
        self._k = 1.0
        self.value.valueChanged.connect(lambda v: panel.set_value(self.index, v * self._k))
        self.flip.toggled.connect(lambda on: panel.set_flip(self.index, on))
        self.count.valueChanged.connect(lambda n: panel.set_count(self.index, n))

    def show_ref(self, ref, active, need=False):
        self.pick.clear()
        if ref is not None:
            try:
                from . import refplanelook
                self.pick.addItem(refplanelook.sw_name(ref, self.panel.refs))
            except Exception as _fw_err:
                _fw_log("refplane.py:sw_name", _fw_err)
                self.pick.addItem(ref.name())
        _mark(self.pick, active, need=need)
        offered = OFFERED.get(ref.kind, ()) if ref is not None else ()
        try:
            from . import refplanelook
            refplanelook.order(self, offered, ref is not None and ref.kind in ("curve", "line"))
        except Exception as _fw_err:
            _fw_log("refplane.py:order", _fw_err)
        for key, b in self.buttons.items():
            b.setVisible(key in offered)
            b.setChecked(ref is not None and ref.constraint == key)
        valued = ref is not None and ref.constraint in ("Distance", "Angle")
        self.value.setVisible(valued)
        tangent = ref is not None and ref.constraint == "Tangent"
        self.flip.setVisible(valued or tangent)
        if tangent:
            self.flip.blockSignals(True)
            self.flip.setText("Flip")
            self.flip.setChecked(ref.flip)
            self.flip.blockSignals(False)
        self.count.setVisible(valued)
        self.count_label.setVisible(valued)


        # reference picked takes it (no greyed control: Ati's rule)
        self.flip_normal.setVisible(self.index == 0)
        self.flip_normal.setEnabled(True)
        self.flip_normal.blockSignals(True)
        self.flip_normal.setChecked(ref.flip_normal if ref is not None else self.panel.flip_pending)
        self.flip_normal.blockSignals(False)
        point_too = any(r is not None and r.kind == "point" for r in self.panel.refs)
        curve = ref is not None and ref.kind in ("curve", "line") and ref.constraint == "Perpendicular"
        self.on_curve.setVisible(bool(curve and point_too))
        if ref is not None:
            self.on_curve.blockSignals(True)
            self.on_curve.setChecked(ref.on_curve)
            self.on_curve.blockSignals(False)
        if valued:
            for w in (self.value, self.flip, self.count):
                w.blockSignals(True)
            if ref.constraint == "Distance":    # in the part's unit (Document Properties > Units), kept in mm
                try:
                    from . import evaluate
                    sym, k = evaluate.doc_unit()
                except Exception as _fw_err:
                    _fw_log("refplane.py:unit", _fw_err)
                    sym, k = "mm", 1.0
                suffix, top, dec = " " + sym, 1e6 / k, (3 if k == 1.0 else 4)
            else:
                suffix, top, dec, k = "°", 360.0, 3, 1.0
            self._k = k
            if self.value.decimals() != dec:
                self.value.setDecimals(dec)
            if self.value.suffix() not in (suffix, {" mm": "mm", " in": "in", "°": "deg"}.get(suffix)):   # pkg106: each setter re-renders the edit
                self.value.setSuffix(suffix)        # and would drop a value being typed
            if abs(self.value.maximum() - top) > 1e-9:
                self.value.setRange(0.0, top)
            if not _typing(self.value):
                self.value.setValue(ref.value / k)   # not over a value being typed (pkg106)
            self.flip.setText("Flip offset")
            self.flip.setChecked(ref.flip)
            self.count.setValue(ref.count)
            for w in (self.value, self.flip, self.count):
                w.blockSignals(False)


def _typing(spin):
    """The field holds typed text its value has not taken yet: a refresh must not wipe it
    (pkg106 real-use pass: 20 typed, a refresh before Enter put 10.000 mm back)."""
    try:
        edit = spin.lineEdit()
        return spin.hasFocus() and edit is not None and edit.isModified()
    except Exception:
        return False


_current = None


def current():
    """The open Plane PropertyManager, or None."""
    return _current


class _Escape(QtCore.QObject):
    ""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) and event.key() == QtCore.Qt.Key_Escape \
                and not (event.modifiers() & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)):
            if t == QtCore.QEvent.KeyPress and current() is self.panel:
                QtCore.QTimer.singleShot(0, self.panel.reject)
            return True
        return False


class PlanePanel:
    ""

    def __init__(self, doc, body, picks=()):
        global _current
        _current = self
        self.doc, self.body = doc, body
        self.refs = [None, None, None]
        self.flip_pending = False       # Flip normal ticked before the first reference is picked
        self.active = 0
        self.planes = []
        p = _params()
        self.distance = p.GetFloat("Distance", 10.0)
        self.angle = p.GetFloat("Angle", 45.0)
        self.opened = False
        self.ok = False
        self._filters = []
        message = QtWidgets.QWidget()
        message.setWindowTitle("Message")
        lay = QtWidgets.QVBoxLayout(message)
        self.message = QtWidgets.QLabel("", message)
        self.message.setObjectName("SWPlaneMessage")
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        message.setProperty("swstyle_pm_title", TITLE)
        message.setProperty("swstyle_pm_icon", "REFGEO_PLANE")
        self.boxes = [_RefBox(self, i) for i in range(3)]
        for i, box in enumerate(self.boxes):
            box.pick.installEventFilter(self._focus(i))
            try:
                # right-click Delete / Clear Selections and the Delete key take the reference out
                from . import pmboxes
                pmboxes.bind(box.pick, lambda row, i=i: self.clear_ref(i), lambda i=i: self.clear_ref(i))
            except Exception as _fw_err:
                _fw_log("refplane.py:769", _fw_err)

        options = QtWidgets.QWidget()
        options.setWindowTitle("Options")
        QtWidgets.QVBoxLayout(options).addWidget(self.boxes[0].flip_normal)
        self.form = [message] + self.boxes + [options]
        for obj, sub in picks:
            self._add(obj, sub)
        self.update()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        self._views = []
        self._esc = _Escape(self)
        try:
            # stock FreeCAD 1.1: findChildren(QOpenGLWidget) finds nothing from Python
            for w in [v for v in Gui.getMainWindow().findChildren(QtWidgets.QWidget) if v.inherits("QOpenGLWidget")]:
                w.installEventFilter(self._esc)
                self._views.append(w)
        except Exception as _fw_err:
            _fw_log("refplane.py:784", _fw_err)

    # --- picks
    def _focus(self, index):
        panel = self

        class F(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
                    panel.active = index
                    panel._show()
                return False
        f = F(self.boxes[index])
        self._filters.append(f)
        return f

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        if obj is None:
            return
        obj, sub = resolve(obj, sub)
        if obj in self.planes:
            return
        QtCore.QTimer.singleShot(0, lambda: self._picked(obj, sub))

    def _picked(self, obj, sub):
        if self._gone():
            return
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("refplane.py:819", _fw_err)
        before = [r is not None for r in self.refs]
        self._add(obj, sub)
        self.update()
        if sum(r is not None for r in self.refs) > sum(before):
            self._focus_value()

    def _focus_value(self):
        ""

        def go():
            try:
                for b in reversed(self.boxes):
                    w = b.value
                    if w.isVisible() and w.isEnabled() and not w.isReadOnly():
                        w.setFocus(QtCore.Qt.OtherFocusReason)
                        w.selectAll()
                        return
            except Exception as _fw_err:
                _fw_log("refplane.py:838", _fw_err)
        QtCore.QTimer.singleShot(0, go)

    def _add(self, obj, sub):
        obj, sub = resolve(obj, sub or "")
        obj, sub = datum_ref(obj, sub, self.body)
        if kind_of(obj, sub) is None:
            return
        for i, r in enumerate(self.refs):
            if r is not None and r.obj == obj and r.sub == sub:
                self.refs[i] = None
                self.active = i
                return
        slot = self.active if self.refs[self.active] is None else \
            next((i for i, r in enumerate(self.refs) if r is None), self.active)
        self.refs[slot] = Ref(obj, sub)
        if slot == 0 and self.flip_pending:
            self.refs[slot].flip_normal = True
            self.flip_pending = False
        self.active = next((i for i, r in enumerate(self.refs) if r is None), slot)

    def clear_ref(self, index):
        """Delete / Clear Selections in a reference box: that reference goes, the box takes the next pick."""
        self.refs[index] = None
        self.active = index
        self.update()

    # --- constraint edits from the boxes
    def set_constraint(self, index, key):
        r = self.refs[index]
        if r is None:
            return
        r.constraint = key
        if key == "Distance" and r.value <= 0:
            r.value = self.distance
        if key == "Angle" and (r.value <= 0 or r.value > 360):
            r.value = self.angle
        self.update(keep=True)

    def set_value(self, index, v):
        r = self.refs[index]
        if r is not None:
            r.value = v
            self.update(keep=True)

    def set_flip(self, index, on):
        r = self.refs[index]
        if r is not None:
            r.flip = on
            self.update(keep=True)

    def set_flip_normal(self, index, on):
        r = self.refs[index]
        if r is not None:
            r.flip_normal = on
            self.update(keep=True)
        elif index == 0:
            self.flip_pending = on

    def set_on_curve(self, index, on):
        r = self.refs[index]
        if r is not None:
            r.on_curve = on
            self.update(keep=True)

    def set_count(self, index, n):
        r = self.refs[index]
        if r is not None:
            r.count = n
            self.update(keep=True)

    # --- the planes
    def _planes(self, n):
        if n and not self.opened:
            self.doc.openTransaction(TITLE)
            self.opened = True
        while len(self.planes) < n:
            from . import refgeom2
            pl = refgeom2.new_datum(self.doc, self.body, "PartDesign::Plane", "Plane")
            self.planes.append(pl)
        while len(self.planes) > n:
            pl = self.planes.pop()
            from . import refgeom2
            refgeom2.drop(self.doc, self.body, pl)

    def _gone(self):
        """The PM closed: a pick or update still queued (QTimer) must not touch its deleted labels."""
        try:
            import shiboken6 as shiboken
        except ImportError:
            try:
                import shiboken2 as shiboken
            except ImportError:
                return False
        try:
            return not shiboken.isValid(self.message)
        except Exception:
            return True

    def update(self, keep=False):
        if self._gone():
            return
        refs = [r for r in self.refs if r is not None]
        if not keep:
            defaults(refs, self.distance, self.angle)
        try:
            rec = recipe(refs)
            n = len(rec.offsets) if rec.make_offset is None else max(1, max((r.count for r in refs), default=1))
            self._planes(n)
            made = place(self.planes, rec)
            self._planes(made)
            self.message.setText("Fully defined")
            self.message.setStyleSheet("color: #2e7d32;")
            self.ok = True
        except PlaneError as error:
            self._planes(0)
            self.doc.recompute()
            self.message.setText(str(error))
            self.message.setStyleSheet("" if not refs else _error_css())
            self.ok = False
        self._show()
        try:
            from . import refplanelook          # green message, references in their colours, preview
            refplanelook.after_update(self)
        except Exception as _fw_err:
            _fw_log("refplane.py:look", _fw_err)

    def _show(self):
        for i, box in enumerate(self.boxes):
            box.show_ref(self.refs[i], i == self.active, need=i == self.active and self.refs[i] is None and not self.ok)
            box.setVisible(True)

    # --- check and cross
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        global _current
        _current = None
        try:
            from . import refplanelook
            refplanelook.close(self)
        except Exception as _fw_err:
            _fw_log("refplane.py:look-close", _fw_err)
        for w in self._views:
            try:
                w.removeEventFilter(self._esc)
            except Exception as _fw_err:
                _fw_log("refplane.py:970", _fw_err)
        self._views = []
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("refplane.py:975", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if not self.ok:
            return False
        p = _params()
        for r in self.refs:
            if r is not None and r.constraint == "Distance":
                p.SetFloat("Distance", r.value)
            if r is not None and r.constraint == "Angle":
                p.SetFloat("Angle", r.value)
        refs = [r for r in self.refs if r is not None]
        for k, pl in enumerate(self.planes):
            try:
                remember(pl, refs, k)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: plane references not kept: %s\n" % error)
        try:
            from . import refplanelook          # the plane kept takes its usual look
            refplanelook.restore_planes(self)
        except Exception as _fw_err:
            _fw_log("refplane.py:look-restore", _fw_err)
        self.doc.recompute()                       # the new plane shows rebuilt, not touched
        self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        if self.opened:
            self.doc.abortTransaction()
        self.doc.recompute()
        self._close()
        return True


# --------------------------------------------------------------------------- every reference kept

# them and rebuilds the plane from them. So each plane keeps its references and constraints too
# (plain properties, safe in stock FreeCAD), and after each recompute a plane whose offset was
# worked out from the other references (angle, parallel through a point, mid plane, tangent) is
# worked out again, so it follows the model.
KEEP = "FreeCAD references"


def remember(plane, refs, index=0):
    import json
    for i in range(3):
        prop = "Reference%d" % (i + 1)
        if prop not in plane.PropertiesList:
            plane.addProperty("App::PropertyLinkSubGlobal", prop, KEEP, "Plane reference %d" % (i + 1))
        r = refs[i] if i < len(refs) else None
        setattr(plane, prop, (r.obj, [r.sub] if r.sub else []) if r is not None else None)
    if "Constraints" not in plane.PropertiesList:
        plane.addProperty("App::PropertyString", "Constraints", KEEP, "Constraint, value and flip of each reference")
        plane.setEditorMode("Constraints", 1)
    plane.Constraints = json.dumps({"index": index, "refs": [
        {"constraint": r.constraint, "value": r.value, "flip": r.flip, "count": r.count,
         "flip_normal": r.flip_normal, "on_curve": r.on_curve, "screen": r.screen} for r in refs]})


def kept_refs(plane):
    """The plane's references as Ref objects, or None for a plane made otherwise."""
    import json
    if "Constraints" not in plane.PropertiesList or not plane.Constraints:
        return None, 0
    data = json.loads(plane.Constraints)
    refs = []
    for i, item in enumerate(data.get("refs", [])):
        link = getattr(plane, "Reference%d" % (i + 1), None)
        if not link or link[0] is None:
            return None, 0
        obj, subs = link[0], link[1]
        r = Ref(obj, subs[0] if subs else "")
        r.constraint, r.value = item.get("constraint"), float(item.get("value", 0.0))
        r.flip, r.count = bool(item.get("flip")), int(item.get("count", 1))
        r.flip_normal = bool(item.get("flip_normal"))
        r.on_curve = bool(item.get("on_curve", True))   # planes kept before 149 sat on the curve
        r.screen = tuple(item["screen"]) if item.get("screen") else None
        refs.append(r)
    return refs, int(data.get("index", 0))


_following = set()


def follow(doc):
    """Works the kept planes out again from all their references (after the model changed)."""
    if doc.Name in _following or current() is not None:
        return
    changed = False
    for plane in [o for o in doc.Objects if o.TypeId == "PartDesign::Plane"]:
        try:
            refs, index = kept_refs(plane)
            if not refs:
                continue
            rec = recipe(refs)
            if rec.mode == "Deactivated":
                # Parallel to Screen: the plane is set at its point (it has no attachment)
                new = rec.offsets[min(index, len(rec.offsets) - 1)]
                if not new.isSame(plane.Placement, 1e-7):
                    plane.Placement = new
                    changed = True
                continue
            if rec.make_offset is None:
                continue
            base = plane.Placement.multiply(plane.AttachmentOffset.inverse())
            offsets = rec.make_offset(base)
            if index >= len(offsets):
                continue
            new = offsets[index]
            if not new.isSame(plane.AttachmentOffset, 1e-7):
                plane.AttachmentOffset = new
                changed = True
        except Exception as error:
            App.Console.PrintLog("FreeCAD: %s not worked out again: %s\n" % (plane.Label, error))
    if changed:
        _following.add(doc.Name)
        try:
            doc.recompute()
        finally:
            _following.discard(doc.Name)


class _Follow:
    def slotRecomputedDocument(self, doc):
        follow(doc)
        try:
            from . import refgeom2      # rgdeep: coordinate systems turned by a plane, points a distance along
            refgeom2.follow(doc)
        except Exception as _fw_err:
            _fw_log("refplane.py:follow-refgeom2", _fw_err)


_observer = None


def _picks_before(doc):
    out = []
    for entry in Gui.Selection.getSelectionEx(doc.Name):
        subs = entry.SubElementNames or ("",)
        for sub in subs:
            out.append(resolve(entry.Object, sub))
    return out[:3]


class PlaneCommand:
    def GetResources(self):
        return {"Pixmap": "PartDesign_Plane", "MenuText": TITLE,
                "ToolTip": "Adds a plane placed by up to three references"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        body = body_of(doc)

        # goes in the document (Part::DatumPlane) instead of asking for an active body
        picks = _picks_before(doc)
        QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(PlanePanel(doc, body, picks)))


COMMAND = "SWStyle_RefPlane"


def register():
    global _observer
    if _observer is None:
        _observer = _Follow()
        App.addDocumentObserver(_observer)
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, PlaneCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
