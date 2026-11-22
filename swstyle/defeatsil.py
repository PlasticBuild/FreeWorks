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

V = App.Vector
KINDS = ("Bounding box", "Cylindrical", "Polygon outline", "Tight fit outline")
OUTPUTS = ("Save as New Document", "Create New Configuration")
TYPE = "SWStyle::DefeatureSilhouette"


def _hull(points):
    """Convex hull (2D, x/y) of the points, counter-clockwise."""
    pts = sorted(set((round(p.x, 9), round(p.y, 9)) for p in points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _outer_only(flat):
    """The flat shadow with its holes filled."""
    faces = []
    for f in flat.Faces:
        try:
            faces.append(Part.Face(f.OuterWire))
        except Exception:
            faces.append(f)
    if len(faces) == 1:
        return faces[0]
    try:
        return faces[0].multiFuse(faces[1:]).removeSplitter()
    except Exception:
        return Part.makeCompound(faces)


def outline_solid(shape, normal, kind="Tight fit outline", keep_loops=True):
    """The outline shape casts on the plane square to normal, extruded through shape."""
    from . import measure
    n = V(normal)
    if n.Length < 1e-12:
        n = V(0, 0, 1)
    n.normalize()
    got = measure.shadow([shape], n)
    if got is None:
        return None
    flat, u, w = got
    if kind == "Polygon outline":
        hull = _hull([v.Point for v in flat.Vertexes])
        if len(hull) < 3:
            return None
        flat = Part.Face(Part.makePolygon([V(x, y, 0) for x, y in hull] + [V(hull[0][0], hull[0][1], 0)]))
    elif not keep_loops:
        flat = _outer_only(flat)
    heights = [v.Point.dot(n) for v in shape.Vertexes]
    try:
        pts, _tris = shape.tessellate(shape.BoundBox.DiagonalLength * 0.002)
        heights += [p.dot(n) for p in pts]
    except Exception as _fw_err:
        _fw_log("defeatsil.py:98", _fw_err)
    lo, hi = min(heights), max(heights)
    m = App.Matrix(u.x, w.x, n.x, n.x * lo,
                   u.y, w.y, n.y, n.y * lo,
                   u.z, w.z, n.z, n.z * lo,
                   0, 0, 0, 1)
    placed = flat.copy()
    placed.transformShape(m)
    solid = placed.extrude(n * max(hi - lo, 1e-6))
    try:
        solid = solid.removeSplitter()
    except Exception as _fw_err:
        _fw_log("defeatsil.py:110", _fw_err)
    return solid


def silhouette(shape, kind="Bounding box", normal=V(0, 0, 1), keep_loops=True):
    from . import asmdefeature
    if kind in ("Polygon outline", "Tight fit outline"):
        got = outline_solid(shape, normal, kind, keep_loops)
        if got is not None:
            return got
        kind = "Bounding box"
    return asmdefeature.silhouette(shape, "Cylinder" if kind == "Cylindrical" else "Bounding box")


# --------------------------------------------------------------------------- the feature (configuration)
class SilhouetteFeature:
    """Defeature (Silhouette) at the end of a Body: the Body's shape before it, simplified."""
    Type = TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        props = obj.PropertiesList
        if "Simplify" not in props:
            obj.addProperty("App::PropertyEnumeration", "Simplify", "Defeature", "The simple solid that replaces the bodies")
            obj.Simplify = list(KINDS)
        if "Direction" not in props:
            obj.addProperty("App::PropertyVector", "Direction", "Defeature", "Normal of the outline plane")
            obj.Direction = V(0, 0, 1)
        if "KeepInternalLoops" not in props:
            obj.addProperty("App::PropertyBool", "KeepInternalLoops", "Defeature", "Keep holes in a tight fit outline")
            obj.KeepInternalLoops = True

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        base = getattr(obj, "BaseFeature", None)
        if base is None or base.Shape.isNull():
            obj.Shape = Part.Shape()
            return
        obj.Shape = silhouette(base.Shape, obj.Simplify, obj.Direction, obj.KeepInternalLoops)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class _View:
    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        return "Part_Defeaturing"

    def attach(self, vobj):
        self.Object = vobj.Object

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _label(doc, base):
    try:
        from . import naming
        return naming.next_label(doc, base)
    except Exception:
        return base + "1"


def to_new_document(body, kind, normal, keep_loops):
    """Save as New Document: a new part (Defeature of <part>) holding the silhouette."""
    shape = silhouette(body.Shape, kind, normal, keep_loops)
    src = body.Document
    name = "%s_Defeature" % src.Name
    doc = App.newDocument(name)
    try:
        doc.Label = "%s - Defeature" % src.Label
    except Exception as _fw_err:
        _fw_log("defeatsil.py:196", _fw_err)
    obj = doc.addObject("Part::Feature", "Defeature")
    obj.Label = "Defeature1"
    obj.Shape = shape
    doc.recompute()
    if App.GuiUp:
        try:
            import FreeCADGui as Gui
            Gui.ActiveDocument.ActiveView.viewIsometric()
            Gui.SendMsgToActiveView("ViewFit")
        except Exception as _fw_err:
            _fw_log("defeatsil.py:207", _fw_err)
    return doc, obj


def to_new_configuration(body, kind, normal, keep_loops, name="Defeature"):
    """Create New Configuration: the Defeature feature at the end of the Body, shown in the new
    configuration and suppressed in every other one."""
    from . import configmanager as cm, configs
    doc = body.Document
    t = cm.table(doc) or cm.insert_table(doc, "Default")
    others = list(t.names())
    new = name
    k = 1
    while new in others:
        k += 1
        new = "%s%d" % (name, k)
    doc.openTransaction("Defeature")
    try:
        obj = doc.addObject("PartDesign::FeaturePython", "Defeature")
        SilhouetteFeature(obj)
        if App.GuiUp:
            _View(obj.ViewObject)
        obj.Label = _label(doc, "Defeature")
        body.addObject(obj)
        obj.Simplify = kind
        obj.Direction = V(normal)
        obj.KeepInternalLoops = bool(keep_loops)
        doc.recompute()
    finally:
        doc.commitTransaction()

    # follows the parent's later changes
    parent = t.active()
    if not cm.add_derived(t, parent, new):
        cm.add(t, new)
    t = cm.table(doc)
    # the others first: a derived configuration follows its parent's change, so it is set after
    configs.set_suppressed(obj, True, others)
    configs.set_suppressed(obj, False, [new])
    doc.recompute()
    return obj, new
