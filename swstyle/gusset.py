# SPDX-License-Identifier: LGPL-2.1-or-later
""









import FreeCAD as App
import Part

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
COMMAND = "SWStyle_Gusset"
TITLE = "Gusset"


def _plane(face):
    surface = face.Surface
    if not hasattr(surface, "Axis") or surface.TypeId != "Part::GeomPlane":
        raise RuntimeError("Gusset needs two flat supporting faces")
    n = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
    return face.CenterOfMass, n


def frame(f1, f2):
    """(point on the shared line, line direction, u1, u2): u1 lies in face 1 square to the line,
    pointing into it; u2 likewise in face 2."""
    c1, n1 = _plane(f1)
    c2, n2 = _plane(f2)
    e = n1.cross(n2)
    if e.Length < 1e-6:
        raise RuntimeError("The supporting faces are parallel: pick two faces that meet")
    e.normalize()
    if max((e.x, e.y, e.z), key=abs) < 0:
        e = e * -1          # Start is the lower end of the shared line, along its main axis
    lines = Part.Plane(c1, n1).intersect(Part.Plane(c2, n2))
    line = lines[0]
    p0 = V(line.Location)

    def into(n, c):
        w = c - p0
        w = w - e * w.dot(e)
        d = e.cross(n)
        if d.dot(w) < 0:
            d = d * -1
        d.normalize()
        return d

    u1, u2 = into(n1, c1), into(n2, c2)
    # the stretch of the line both faces reach
    def span(face):
        ts = [(v.Point - p0).dot(e) for v in face.Vertexes]
        return min(ts), max(ts)
    a1, b1 = span(f1)
    a2, b2 = span(f2)
    lo, hi = max(a1, a2), min(b1, b2)
    if hi < lo:
        lo, hi = min(a1, a2), max(b1, b2)
    return p0, e, u1, u2, lo, hi


def profile(kind, d1, d2, d3, chamfer):
    """The profile's corners in (along face 1, along face 2)."""
    if kind == "Polygonal" and 0 < d3 < min(d1, d2):
        pts = [(d1, 0), (d1, d3), (d3, d2), (0, d2)]
    else:
        pts = [(d1, 0), (0, d2)]
    if chamfer > 0 and chamfer < min(d1, d2):
        corner = [(0, chamfer), (chamfer, 0)]
    else:
        corner = [(0, 0)]
    return corner + pts


def make_gusset(f1, f2, kind="Triangular", d1=20.0, d2=20.0, d3=5.0, chamfer=0.0, thickness=5.0,
                side="Both sides", location="Mid point", offset=0.0):
    p0, e, u1, u2, lo, hi = frame(f1, f2)
    if location == "Start":
        t = lo + offset
    elif location == "End":
        t = hi - offset
    else:
        t = (lo + hi) / 2.0 + offset
    if side == "Both sides":
        start = t - thickness / 2.0
    elif side == "Side 1":
        start = t
    else:
        start = t - thickness
    origin = p0 + e * start
    pts = [origin + u1 * x + u2 * y for x, y in profile(kind, d1, d2, d3, chamfer)]
    wire = Part.makePolygon(pts + [pts[0]])
    plate = Part.Face(wire).extrude(e * thickness)
    return plate


def _compute(obj, base):
    faces = [f for _, f in sf.elements(obj, "SupportingFaces") if f.ShapeType == "Face"]
    if len(faces) < 2:
        return None, None
    plate = make_gusset(faces[0], faces[1], obj.Profile, obj.D1.Value, obj.D2.Value, obj.D3.Value,
                        obj.CornerChamfer.Value, obj.Thickness.Value, obj.ThicknessSide, obj.Location,
                        obj.Offset.Value)
    probe = plate.CenterOfMass
    if base.isInside(probe, 1e-6, False):
        raise RuntimeError("The faces meet at an outside corner: a gusset goes in an inside corner")
    result = base.fuse(plate)
    return result, plate


SPEC = sf.Spec(
    COMMAND, TITLE, TITLE,
    "A plate that braces the inside corner where two flat faces meet.",
    "WE_GUSSET", "PartDesign_AdditiveWedge",
    [Field("SupportingFaces", "pick", "Supporting Faces", what=("Face",), many=True, box="Supporting Faces",
           tip="The two flat faces the gusset braces"),
     Field("Profile", "enum", "Profile", "Triangular", values=["Triangular", "Polygonal"], box="Profile"),
     Field("D1", "length", "Profile Distance1 (d1)", 20.0, box="Profile", tip="Along the first face"),
     Field("D2", "length", "Profile Distance2 (d2)", 20.0, box="Profile", tip="Along the second face"),
     Field("D3", "length", "Profile Distance3 (d3)", 5.0, box="Profile", tip="Height of the square-cut ends",
           shown=lambda o: o.Profile == "Polygonal"),
     Field("CornerChamfer", "length", "Chamfer (d5)", 0.0, box="Profile",
           tip="Clips the inside corner, as room for a weld; 0 = none"),
     Field("ThicknessSide", "enum", "Thickness", "Both sides", values=["Both sides", "Side 1", "Side 2"],
           box="Profile"),
     Field("Thickness", "length", "Gusset Thickness", 5.0, box="Profile"),
     Field("Location", "enum", "Location", "Mid point", values=["Start", "Mid point", "End"], box="Location"),
     Field("Offset", "distance", "Offset", 0.0, box="Location", tip="Moves the gusset along the shared line")],
    _compute)


def register():
    sf.register(SPEC)
