# SPDX-License-Identifier: LGPL-2.1-or-later
""








import FreeCAD as App
import Part

from . import swapp

V = App.Vector
TOL = 1e-3          # mm
ANG = 1e-6

KINDS = {"COINCIDENT": "Coincident", "CONCENTRIC": "Concentric", "PERPENDICULAR": "Perpendicular",
         "PARALLEL": "Parallel", "TANGENT": "Tangent", "DISTANCE": "Distance", "ANGLE": "Angle",
         "LOCK": "Lock"}


def read(asm, links, path):
    ""
    try:
        from swstyle import asmcore
    except Exception:
        return 0, 0, ["mates not made: FreeCAD's assemblies (swstyle) are not installed"]
    res = swapp.run("mates", [path], "Reading the mates from SolidWorks...")
    notes = list(res.get("errors", []))
    made = 0
    total = len(res.get("mates", []))
    for row in res.get("mates", []):
        why = make(asmcore, asm, links, row)
        if why is None:
            made += 1
        else:
            notes.append("%s: %s" % (row["name"], why))
    for name in res.get("fixed", []):
        link = _link(links, name)
        if link is not None:
            asmcore.fix(asm, link)
    asm.Document.recompute()
    return made, total, notes


def _link(links, name):
    if not name:
        return None
    return links.get(name.split("/")[-1])


def make(asmcore, asm, links, row):
    kind = KINDS.get(row["type"])
    if kind is None:
        return "%s mates are not made in FreeCAD yet" % row["type"].title()
    if row.get("suppressed"):
        return "suppressed in SolidWorks, so it was left out"
    ents = row["entities"]
    if len(ents) != 2:
        return "SolidWorks gave %d sides for it" % len(ents)
    refs = []
    for e in ents:
        link = _link(links, e["component"])
        if link is None:
            return "component %s is not in the assembly" % e["component"]
        sub = "Face1" if kind == "Lock" else find(_shape(link), e)
        if sub is None:
            return "its %s on %s was not found" % (e["ref"].lower(), e["component"])
        refs.append((link, sub))
    value = None
    a, b = ents
    if kind == "Distance":
        if row.get("value") is not None:
            value = row["value"] * 1000.0
        else:
            n = V(*a["dir"])
            value = abs((V(*b["point"]) - V(*a["point"])).dot(n.normalize())) if n.Length else 0.0
    elif kind == "Angle":
        import math
        if row.get("value") is not None:
            value = math.degrees(row["value"])
        else:
            value = math.degrees(V(*a["dir"]).getAngle(V(*b["dir"])))
    before = {c: App.Placement(c.Placement) for c in asmcore.components(asm)}
    joint = asmcore.add_mate(asm, kind, refs[0], refs[1], value=value)
    if not _moved(before):
        return None
    # FreeCAD lines the two picked faces up when a joint is made, which can slide or turn a


    for flip in (False, True):
        _restore(asm, before)
        if flip:
            joint.Proxy.flipOnePart(joint)
            _restore(asm, before)
        if asmcore.solve(asm) and not _moved(before) and asmcore.satisfied(joint):
            return None
    asm.Document.removeObject(joint.Name)
    _restore(asm, before)
    return "FreeCAD would move a component to make it"


def _restore(asm, before):
    for c, pl in before.items():
        c.Placement = pl
    asm.Document.recompute()


def _moved(before):
    for c, pl in before.items():
        if (c.Placement.Base - pl.Base).Length > TOL or not c.Placement.Rotation.isSame(pl.Rotation, ANG):
            return True
    return False


def _shape(link):
    return Part.getShape(link, "", needSubElement=False, transform=True)


def _parallel(a, b):
    return abs(abs(a.normalize().dot(b.normalize())) - 1.0) < 1e-6


def _on_line(p, origin, d):
    v = p - origin
    return (v - d.normalize() * v.dot(d.normalize())).Length < TOL


def find(shape, e):
    """The element name ("Face3", "Edge7", "Vertex2") of shape with the mated geometry."""
    p, d, r = V(*e["point"]), V(*e["dir"]), e.get("radius", 0.0)
    ref = e["ref"]
    if ref == "Plane":
        for i, f in enumerate(shape.Faces):
            s = f.Surface
            if s.TypeId == "Part::GeomPlane" and _parallel(V(s.Axis), d) and \
                    abs((p - V(s.Position)).dot(V(s.Axis).normalize())) < TOL:
                return "Face%d" % (i + 1)
    elif ref in ("Cylinder", "Cone"):
        for i, f in enumerate(shape.Faces):
            s = f.Surface
            if s.TypeId in ("Part::GeomCylinder", "Part::GeomCone") and _parallel(V(s.Axis), d) and \
                    _on_line(p, V(s.Center if s.TypeId == "Part::GeomCylinder" else s.Apex), V(s.Axis)) and \
                    (ref == "Cone" or abs(s.Radius - r) < TOL):
                return "Face%d" % (i + 1)
    elif ref == "Circle":
        for i, ed in enumerate(shape.Edges):
            c = ed.Curve
            if c.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle") and (V(c.Center) - p).Length < TOL \
                    and _parallel(V(c.Axis), d) and abs(c.Radius - r) < TOL:
                return "Edge%d" % (i + 1)
    elif ref == "Line":
        for i, ed in enumerate(shape.Edges):
            c = ed.Curve
            if c.TypeId in ("Part::GeomLine", "Part::GeomLineSegment"):
                a, b = ed.Vertexes[0].Point, ed.Vertexes[-1].Point
                if (b - a).Length > 1e-9 and _parallel(b - a, d) and _on_line(a, p, d):
                    return "Edge%d" % (i + 1)
        for i, f in enumerate(shape.Faces):          # an axis: the round face around it
            s = f.Surface
            if s.TypeId == "Part::GeomCylinder" and _parallel(V(s.Axis), d) and _on_line(V(s.Center), p, d):
                return "Face%d" % (i + 1)
    elif ref in ("Point", "Sphere"):
        for i, v in enumerate(shape.Vertexes):
            if (v.Point - p).Length < TOL:
                return "Vertex%d" % (i + 1)
        for i, f in enumerate(shape.Faces):
            s = f.Surface
            if s.TypeId == "Part::GeomSphere" and (V(s.Center) - p).Length < TOL:
                return "Face%d" % (i + 1)
        for i, ed in enumerate(shape.Edges):
            c = ed.Curve
            if c.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle") and (V(c.Center) - p).Length < TOL:
                return "Edge%d" % (i + 1)
    return None
