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

TYPE = "PartDesign::FeaturePython"
ICON = "FEATURES_CHAMFER_VERTEX"


def is_vertex_chamfer(obj):
    try:
        return obj.TypeId == TYPE and isinstance(obj.Proxy, VertexChamferFeature)
    except Exception:
        return False


def _point_along(edge, vertex, d):
    """The point d along edge from the vertex end."""
    p = vertex.Point
    # which end of the curve's parameter range the vertex is at (Vertexes[0] follows the edge's
    # orientation, which a reversed edge has the other way round from its curve)
    try:
        first = (edge.valueAt(edge.FirstParameter) - p).Length <= (edge.valueAt(edge.LastParameter) - p).Length
    except Exception:
        first = (edge.Vertexes[0].Point - p).Length < 1e-7
    length = edge.Length
    if d >= length - 1e-9:
        raise RuntimeError("A chamfer distance is as long as an edge at the vertex.")
    try:
        if first:
            u = edge.getParameterByLength(d)
        else:
            u = edge.getParameterByLength(length - d)
        return edge.valueAt(u)
    except Exception:
        q = edge.Vertexes[-1].Point if first else edge.Vertexes[0].Point
        v = q - p
        v.normalize()
        return p + v * d


def corner_cut(solid, vertex, distances):
    """The tetrahedron cut off at vertex, distances in the order of its edges."""
    import Part
    edges = [e for e in solid.Edges if any(v.isSame(vertex) for v in e.Vertexes)]
    # a seam or a degenerate edge is not a corner edge
    edges = [e for e in edges if e.Length > 1e-9 and not e.isClosed()]
    if len(edges) != 3:
        raise RuntimeError("A vertex chamfer needs a corner where three edges meet (this one has %d)."
                           % len(edges))
    pts = [_point_along(e, vertex, d) for e, d in zip(edges, distances)]
    p = vertex.Point
    faces = []
    for a, b, c in ((p, pts[0], pts[1]), (p, pts[1], pts[2]), (p, pts[2], pts[0]), (pts[0], pts[1], pts[2])):
        faces.append(Part.Face(Part.makePolygon([a, b, c, a])))
    tetra = Part.Solid(Part.Shell(faces))
    if tetra.Volume < 0:
        tetra.reverse()
    return tetra


def vertex_chamfer(solid, vertices, distances):
    cuts = [corner_cut(solid, v, distances) for v in vertices]
    if not cuts:
        return solid
    out = solid.cut(cuts) if len(cuts) > 1 else solid.cut(cuts[0])
    try:
        out = out.removeSplitter()
    except Exception as _fw_err:
        _fw_log("vertexchamfer.py:89", _fw_err)
    if len(out.Solids) == 1:
        out = out.Solids[0]
    if out.isNull() or not out.isValid():
        raise RuntimeError("The vertex chamfer could not be made at these distances.")
    return out


class VertexChamferFeature:
    def __init__(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def setup(self, obj):
        props = obj.PropertiesList
        if "Base" not in props:
            obj.addProperty("App::PropertyLinkSub", "Base", "Chamfer", "Vertices to chamfer")
        for name, tip in (("Distance1", "Distance 1"), ("Distance2", "Distance 2"), ("Distance3", "Distance 3")):
            if name not in props:
                obj.addProperty("App::PropertyLength", name, "Chamfer", tip)
                setattr(obj, name, 1.0)
        if "EqualDistance" not in props:
            obj.addProperty("App::PropertyBool", "EqualDistance", "Chamfer", "All three distances the same")
            obj.EqualDistance = True

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
        if base is None or base.isNull():
            raise RuntimeError("Chamfer needs a part")
        source = obj.Base[0] if obj.Base else obj.BaseFeature
        subs = list(obj.Base[1]) if obj.Base else []
        vertices = []
        for sub in subs:
            try:
                g = source.Shape.getElement(sub.split(".")[-1].lstrip("?"))
            except Exception:
                continue
            v = next((v for v in base.Vertexes if (v.Point - g.Point).Length < 1e-7), None)
            if v is not None:
                vertices.append(v)
        if not vertices:
            raise RuntimeError("Select vertices to chamfer.")
        d1 = obj.Distance1.Value
        ds = [d1, d1, d1] if obj.EqualDistance else [d1, obj.Distance2.Value, obj.Distance3.Value]
        obj.Shape = vertex_chamfer(base, vertices, ds)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class VertexChamferView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            for name in (ICON, "FEATURES_CHAMFER"):
                icon = icons.family(name)
                if not icon.isNull():
                    return icon
        except Exception as _fw_err:
            _fw_log("vertexchamfer.py:161", _fw_err)
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
    VertexChamferFeature(obj)
    if App.GuiUp:
        VertexChamferView(obj.ViewObject)
    return obj


def new(body, name="Chamfer"):
    label = None
    try:
        from . import naming
        # counted before the object exists: its own FreeCAD label ("Chamfer001" once a removed
        # one held "Chamfer") read as Chamfer1 and made it Chamfer2
        label = naming.next_label(body.Document, "Chamfer")
    except Exception as _fw_err:
        _fw_log("vertexchamfer.py:208", _fw_err)
    obj = body.newObject(TYPE, name)
    setup_new(obj)
    if label:
        obj.Label = label
    return obj
