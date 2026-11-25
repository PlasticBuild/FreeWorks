# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Hole Wizard's other End Conditions: Up To Next, Up To Vertex, Up To Surface and Offset From
Surface.

FreeCAD's Hole goes a set depth or through all. These end conditions work out the depth from the
part: Up To Next stops where the hole first comes out of the material, Up To Vertex at the
vertex's height, Up To Surface where the hole meets the picked face or plane, and Offset From
Surface that far short of it (Reverse offset: past it). The depth follows the part: when the
part or the picked face moves, the hole's depth is worked out again after the rebuild.
With more than one position the deepest one sets the depth, as one FreeCAD Hole has one depth.
"""
import FreeCAD as App
import Part

V = App.Vector
ENDS = ("Blind", "Through All", "Up To Next", "Up To Vertex", "Up To Surface", "Offset From Surface")
PICKED = {"Up To Vertex": "Vertex", "Up To Surface": "Face", "Offset From Surface": "Face"}
PLANES = ("App::Plane", "PartDesign::Plane")
FAR = 1e5


def needs(end):
    """What the end condition needs picked: "Vertex", "Face" or None."""
    return PICKED.get(end)


def target_text(obj, sub):
    return "%s:%s" % (obj.Name, sub)


def _target(doc, text):
    if not text or ":" not in text:
        return None, ""
    name, sub = text.split(":", 1)
    obj = doc.getObject(name)
    return (obj, sub) if obj is not None else (None, "")


def _points(hole):
    """The hole positions (global) and the sketch's normal."""
    sketch = hole.Profile[0] if hole.Profile else None
    if sketch is None:
        return [], V(0, 0, 1)
    pl = sketch.getGlobalPlacement()
    pts = []
    for i, g in enumerate(sketch.Geometry):
        if sketch.getConstruction(i):
            continue
        if isinstance(g, Part.Point):
            pts.append(pl.multVec(V(g.X, g.Y, g.Z)))
        elif isinstance(g, (Part.Circle, Part.ArcOfCircle)):
            pts.append(pl.multVec(g.Center))
    return pts, pl.Rotation.multVec(V(0, 0, 1))


def _ray(p, d):
    return Part.LineSegment(p, p + d * FAR).toShape()


def _into(solid, pts, n):
    """The way the holes go: into the material from the sketch (FreeCAD drills against the
    sketch normal unless Reversed)."""
    if solid is None or solid.isNull() or not pts:
        return -n
    probe = 0.05
    for d in (-n, n):
        if any(solid.isInside(p + d * probe, 1e-6, True) for p in pts):
            return d
    return -n


def _surface_hits(face_shape, p, d):
    hits = []
    for v in _ray(p - d * 1e-6, d).section(face_shape).Vertexes:
        hits.append((v.Point - p).dot(d))
    return [h for h in hits if h > 1e-6]


def depth(hole, end, target="", offset=0.0, reverse=False):
    """The depth the end condition gives the hole, or None when it can't be worked out."""
    pts, n = _points(hole)
    if not pts:
        return None
    base = hole.BaseFeature.Shape if hole.BaseFeature is not None else None
    d = _into(base, pts, n)
    out = []
    if end == "Up To Next":
        if base is None or base.isNull():
            return None
        for p in pts:
            inside = _ray(p - d * 1e-6, d).common(base)
            spans = sorted(((e.Vertexes[0].Point - p).dot(d), (e.Vertexes[-1].Point - p).dot(d)) for e in inside.Edges)
            spans = [(min(a, b), max(a, b)) for a, b in spans]
            first = [b for a, b in sorted(spans) if a < 1e-3]
            if first:
                out.append(first[0])
        return max(out) if out else None
    obj, sub = _target(hole.Document, target)
    if obj is None:
        return None
    if end == "Up To Vertex":
        v = obj.Shape.getElement(sub) if sub else None
        if v is None or not hasattr(v, "Point"):
            return None
        reach = max((v.Point - p).dot(d) for p in pts)
        return reach if reach > 1e-6 else None
    if obj.TypeId in PLANES and not sub:
        pl = obj.getGlobalPlacement()
        face = Part.Plane(pl.Base, pl.Rotation.multVec(V(0, 0, 1))).toShape(-FAR, FAR, -FAR, FAR)
    else:
        face = obj.Shape.getElement(sub) if sub else obj.Shape
        if getattr(face, "Faces", None) and face.Faces and isinstance(face.Faces[0].Surface, Part.Plane):
            f = face.Faces[0]
            face = Part.Plane(f.CenterOfMass, f.normalAt(0, 0)).toShape(-FAR, FAR, -FAR, FAR)
    for p in pts:
        hits = _surface_hits(face, p, d)
        if hits:
            out.append(min(hits))
    if not out:
        return None
    reach = max(out)
    if end == "Offset From Surface":
        reach += offset if reverse else -offset
    return reach if reach > 1e-6 else None


# --------------------------------------------------------------------------- on the hole
PROPS = (("App::PropertyString", "HoleEnd", "Hole Wizard end condition"),
         ("App::PropertyString", "HoleEndTarget", "Picked vertex or face (object:element)"),
         ("App::PropertyLength", "HoleEndOffset", "Offset From Surface distance"),
         ("App::PropertyBool", "HoleEndReverse", "Reverse offset"))


def attach(hole, spec):
    """Gives a new or edited hole the end condition from the Hole Wizard choices."""
    end = spec.get("end", "Blind")
    if end in ("Blind", "Through All"):
        if "HoleEnd" in hole.PropertiesList:
            hole.HoleEnd = ""
        return
    for kind, name, tip in PROPS:
        if name not in hole.PropertiesList:
            hole.addProperty(kind, name, "Hole Wizard", tip)
    hole.HoleEnd = end
    hole.HoleEndTarget = spec.get("end_target", "") or ""
    hole.HoleEndOffset = float(spec.get("end_offset") or 0.0)
    hole.HoleEndReverse = bool(spec.get("end_reverse"))
    hole.DepthType = "Dimension"
    update(hole)
    _watch()


def _follow_target(hole):
    """HoleEndTarget names the picked vertex or face as text: it follows an edit before the hole
    (elementrefs). True when it changed."""
    from . import elementrefs
    obj, sub = _target(hole.Document, hole.HoleEndTarget)

    def apply(moved):
        if obj is not None and (obj.Name, sub) in moved:
            hole.HoleEndTarget = "%s:%s" % (obj.Name, moved[(obj.Name, sub)])
    return elementrefs.follow(hole, lambda: [(obj, sub)] if obj is not None and sub else [], apply)


def update(hole):
    """Sets the hole's depth from its end condition; True when it changed."""
    end = getattr(hole, "HoleEnd", "")
    if not end:
        return False
    if end not in ("Up To Next",):
        _follow_target(hole)
    try:
        value = depth(hole, end, hole.HoleEndTarget, float(hole.HoleEndOffset), bool(hole.HoleEndReverse))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: hole end condition: %s\n" % error)
        return False
    if value is None or abs(hole.Depth.Value - value) < 1e-6:
        return False
    hole.Depth = value
    return True


class _Follow:
    """After a rebuild, holes with an end condition get their depth worked out again."""

    def __init__(self):
        self.busy = False

    def slotRecomputedDocument(self, doc):
        if self.busy:
            return
        changed = False
        for obj in doc.findObjects("PartDesign::Hole"):
            if obj.TypeId == "PartDesign::Hole" and getattr(obj, "HoleEnd", ""):
                changed = update(obj) or changed
        if changed:
            self.busy = True
            try:
                doc.recompute()
            finally:
                self.busy = False


_follow = None


def _watch():
    global _follow
    if _follow is None:
        _follow = _Follow()
        App.addDocumentObserver(_follow)


def restored(doc):
    if any(getattr(o, "HoleEnd", "") for o in doc.Objects if o.TypeId == "PartDesign::Hole"):
        _watch()
