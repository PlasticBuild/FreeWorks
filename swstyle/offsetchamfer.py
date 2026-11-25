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

TYPE = "PartDesign::FeaturePython"
MODES = ("Offset Face", "Face Face")
ICONS = {"Offset Face": "FEATURES_CHAMFER_OFFSET_FACE", "Face Face": "FEATURES_CHAMFER_FACE_FACE"}


def is_offset_chamfer(obj):
    try:
        return obj.TypeId == TYPE and isinstance(obj.Proxy, OffsetChamferFeature)
    except Exception:
        return False


def _normal(face, point):
    u, v = face.Surface.parameter(point)
    n = face.normalAt(u, v)
    n.normalize()
    return n


def along_faces(solid, edge, faces, d_a, d_b):
    """(distance along faces[0], distance along faces[1]) of the chamfer whose lines are the
    faces moved inward by d_a and d_b."""
    m = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
    n_a, n_b = _normal(faces[0], m), _normal(faces[1], m)
    phi = n_a.getAngle(n_b)                 # between the outward normals
    theta = math.pi - phi                   # the angle between the faces (convex or concave)
    if theta < math.radians(1) or theta > math.radians(179):
        raise RuntimeError("An edge between faces that are (almost) flat or folded back cannot be chamfered.")
    s_a = (d_b + d_a * math.cos(theta)) / math.sin(theta)
    s_b = s_a * math.cos(theta) + d_a * math.sin(theta)
    return s_a, s_b


def chamfer(solid, mode, edges, faces_set, d1, d2):
    """solid chamfered: Offset Face over edges, or Face Face between faces_set (two faces)."""
    import Part
    from . import multiradius
    work = []           # (edge, offset from its first face, offset from its second face)
    if mode == "Face Face":
        if len(faces_set) != 2:
            raise RuntimeError("Select two faces.")
        f1, f2 = faces_set
        shared = [e for e in f1.Edges if any(multiradius._same_edge(e, g) for g in f2.Edges)]
        if not shared:
            raise RuntimeError("The two faces must meet at an edge.")
        for e in shared:
            be = next((b for b in solid.Edges if multiradius._same_edge(b, e)), None)
            if be is None:
                continue
            anc = solid.ancestorsOfType(be, Part.Face)
            first_is_1 = _same_face(anc[0], f1)
            work.append((be, d1, d2) if first_is_1 else (be, d2, d1))
    else:
        for e in edges:
            work.append((e, d1, d2))
    rows = []
    for e, off_first, off_second in work:
        i = next((i for i, b in enumerate(solid.Edges, 1) if b.isSame(e)), None)
        if i is None:
            continue
        anc = solid.ancestorsOfType(solid.Edges[i - 1], Part.Face)
        if len(anc) != 2:
            raise RuntimeError("A chamfer edge must be between two faces.")
        # the offset of one face sets the distance along the other
        s_a, s_b = along_faces(solid, solid.Edges[i - 1], anc, off_first, off_second)
        rows.append((i, s_a, s_b))
    if not rows:
        raise RuntimeError("Select items to chamfer.")
    if min(min(a, b) for i, a, b in rows) <= 0:
        raise RuntimeError("Distances must be more than zero.")
    if mode == "Face Face":
        # only where the two faces meet: OpenCascade's chamfer runs on along every edge tangent to
        # the picked one (round a filleted corner it chamfered the whole outline of the face,
        # 38 mm3 for an 8.5 mm3 chamfer). The flat-profile cut stops at the edge's ends.
        out = _prism_chamfer(solid, rows)
        if out is not None:
            return out
    try:
        return multiradius.per_edge(solid, "Chamfer", rows)
    except RuntimeError:
        # OpenCascade's chamfer leaves a bad solid where the edge runs into another chamfer (a

        out = _prism_chamfer(solid, rows)
        if out is None:
            raise
        return out


def _prism_chamfer(solid, rows):
    """The chamfers of rows (edge index, size on its first face, size on its second) cut one by one
    as flat-profile prisms (conicfillet's "Line"), for straight edges between flat faces."""
    import Part
    from . import conicfillet
    work = []
    for i, a, b in rows:
        e = solid.Edges[i - 1]
        faces = solid.ancestorsOfType(e, Part.Face)
        if e.Curve.__class__.__name__ not in ("Line", "LineSegment") or len(faces) != 2 or \
                any(f.Surface.__class__.__name__ != "Plane" for f in faces):
            return None
        mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
        first = faces[0].normalAt(*faces[0].Surface.parameter(mid))
        work.append((mid, e.Length, first, a, b))
    out = solid
    try:
        for mid, length, first, a, b in work:
            e = next((x for x in out.Edges if abs(x.Length - length) < 1e-6
                      and x.distToShape(Part.Vertex(mid))[0] < 1e-6), None)
            if e is None:
                return None
            faces = out.ancestorsOfType(e, Part.Face)
            n0 = faces[0].normalAt(*faces[0].Surface.parameter(mid))
            reverse = n0.dot(first) < 0.999
            out = conicfillet.conic_fillet(out, [e], a, b, "Line", 0.5, 1.0, None, reverse)
    except Exception:
        return None
    return out if out.isValid() else None


def _same_face(a, b):
    if a.isSame(b):
        return True
    try:
        return abs(a.Area - b.Area) < 1e-7 and (a.CenterOfMass - b.CenterOfMass).Length < 1e-7
    except Exception:
        return False


class OffsetChamferFeature:
    def __init__(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def setup(self, obj):
        props = obj.PropertiesList
        if "Base" not in props:
            obj.addProperty("App::PropertyLinkSub", "Base", "Chamfer", "Items to chamfer")
        if "Mode" not in props:
            obj.addProperty("App::PropertyEnumeration", "Mode", "Chamfer", "Chamfer type")
            obj.Mode = list(MODES)
        for name, tip in (("Distance1", "Distance 1 (offset of the first face)"),
                          ("Distance2", "Distance 2 (offset of the second face)")):
            if name not in props:
                obj.addProperty("App::PropertyLength", name, "Chamfer", tip)
                setattr(obj, name, 1.0)
        if "Symmetric" not in props:
            obj.addProperty("App::PropertyBool", "Symmetric", "Chamfer", "Distance 1 for both")
            obj.Symmetric = True
        if "FlipDirection" not in props:
            obj.addProperty("App::PropertyBool", "FlipDirection", "Chamfer", "Swap Distance 1 and 2")

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
        if base is None or base.isNull():
            raise RuntimeError("Chamfer needs a part")
        from . import multiradius
        source = obj.Base[0].Shape if obj.Base else base
        subs = list(obj.Base[1]) if obj.Base else []
        d1 = obj.Distance1.Value
        d2 = d1 if obj.Symmetric else obj.Distance2.Value
        if obj.FlipDirection:
            d1, d2 = d2, d1
        edges, faces = [], []
        for sub in subs:
            name = sub.split(".")[-1].lstrip("?")
            try:
                g = source.getElement(name)
            except Exception:
                continue
            if name.startswith("Face"):
                f = next((f for f in base.Faces if _same_face(f, g)), None)
                if f is not None:
                    faces.append(f)
                    if obj.Mode == "Offset Face":
                        for e in f.Edges:
                            b = next((b for b in base.Edges if multiradius._same_edge(b, e)), None)
                            if b is not None and not any(b.isSame(x) for x in edges):
                                edges.append(b)
            elif name.startswith("Edge"):
                b = next((b for b in base.Edges if multiradius._same_edge(b, g)), None)
                if b is not None and not any(b.isSame(x) for x in edges):
                    edges.append(b)
        obj.Shape = chamfer(base, obj.Mode, edges, faces, d1, d2)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class OffsetChamferView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            for name in (ICONS.get(self.Object.Mode, ""), "FEATURES_CHAMFER"):
                if not name:
                    continue
                icon = icons.family(name)
                if not icon.isNull():
                    return icon
        except Exception as _fw_err:
            _fw_log("offsetchamfer.py:236", _fw_err)
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
    OffsetChamferFeature(obj)
    if App.GuiUp:
        OffsetChamferView(obj.ViewObject)
    return obj


def new(body, name="Chamfer"):
    label = None
    try:
        from . import naming
        # counted before the object exists: its own FreeCAD label ("Chamfer001" once a removed
        # one held "Chamfer") read as Chamfer1 and made it Chamfer2
        label = naming.next_label(body.Document, "Chamfer")
    except Exception as _fw_err:
        _fw_log("offsetchamfer.py:283", _fw_err)
    obj = body.newObject(TYPE, name)
    setup_new(obj)
    if label:
        obj.Label = label
    return obj
