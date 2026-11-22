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
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, smflatten


def _pickable(obj, on):
    """The see-through pick copy stays clickable: selection through transparency (Options >
    Selection) would otherwise let the clicks pass through it."""
    try:
        from . import optionsextras2 as ox
        key = (obj.Document.Name, obj.Name)
        (ox.PICKABLE.add if on else ox.PICKABLE.discard)(key)
        if on:
            ox.apply_through(obj.Document)
            obj.ViewObject.Selectable = True
    except Exception as _fw_err:
        _fw_log("smconvert.py:63", _fw_err)
from .smbaseflange import ALLOWANCES, NOT_YET, RELIEFS, _add_sw_props, _box, _params, _spin
from .smedgeflange import _radio, error_label
from .smrip import DIRECTIONS, across, edge_at, rip
from .smunfold import _DeleteKey, _icon, _list, inside_point

CONVERT_COMMAND = "SWStyle_SMConvert"
INSERT_COMMAND = "SWStyle_SMInsertBends"
CONVERT_TITLE = "Convert To Sheet Metal"
INSERT_TITLE = "Bends"
GROUP = "Sheet Metal"
CORNER_TYPES = ("Open butt", "Overlap", "Underlap")
V = App.Vector
TOL = 1e-5
NO_SHEET = "The fixed face does not have the same thickness on its other side: pick a face of a wall."
CLOSED = ("A corner where three walls meet cannot bend. Rip one of its edges (Edges to rip) first.")


# ================================================================ geometry
def _plane(f):
    return f.Surface.TypeId == "Part::GeomPlane"


def _index(shape, sub, kind):
    items = shape.Faces if kind is Part.Face else shape.Edges
    return next((i for i, s in enumerate(items) if s.isSame(sub)), None)


def face_at(shape, p, planar=True):
    """The face of shape through point p, else None."""
    vp = Part.Vertex(p)
    best = None
    for i, f in enumerate(shape.Faces):
        if planar and not _plane(f):
            continue
        d = f.distToShape(vp)[0]
        if d < 1e-4 and (best is None or d < best[0]):
            best = (d, i)
    return best[1] if best else None


def edge_index(shape, p):
    name = edge_at(shape, p)
    return int(name[4:]) - 1 if name else None


def neighbours(shape, i):
    """(edge index, face index) for each face sharing an edge with face i."""
    out = []
    face = shape.Faces[i]
    for e in face.Edges:
        k = _index(shape, e, Part.Edge)
        for g in shape.ancestorsOfType(e, Part.Face):
            j = _index(shape, g, Part.Face)
            if j is not None and j != i:
                out.append((k, j))
    return out


def _tangent(shape, k):
    """True when the two faces on edge k meet smoothly (a round's edge)."""
    e = shape.Edges[k]
    faces = shape.ancestorsOfType(e, Part.Face)
    if len(faces) != 2:
        return False
    p = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
    n = []
    for f in faces:
        u, v = f.Surface.parameter(p)
        n.append(f.normalAt(u, v))
    return abs(n[0].dot(n[1]) - 1) < 1e-6


def rounds(shape):
    """The solid's rounds that can be bends: cylindrical faces met smoothly on both long sides."""
    out = []
    for i, f in enumerate(shape.Faces):
        if f.Surface.TypeId != "Part::GeomCylinder":
            continue
        lines = [e for e in f.Edges if e.Curve.TypeId == "Part::GeomLine"]
        if len(lines) >= 2 and all(_tangent(shape, _index(shape, e, Part.Edge)) for e in lines):
            out.append(i)
    return out


def solid_sheet(shape, fixed, bend_edges, bend_faces=()):
    """Convert to Sheet Metal: the sheet faces (the fixed face and the faces joined to it by bends)
    and the rip edges found (sheet faces meeting on an edge that is not a bend)."""
    bend_edges, bend_faces = set(bend_edges), set(bend_faces)
    keep, todo = {fixed}, [fixed]
    while todo:
        i = todo.pop()
        for k, j in neighbours(shape, i):
            if j in keep:
                continue
            if k in bend_edges or j in bend_faces or (i in bend_faces and _tangent(shape, k)):
                keep.add(j)
                todo.append(j)
    rips = set()
    for i in keep:
        for k, j in neighbours(shape, i):
            if j in keep and k not in bend_edges and not _tangent(shape, k):
                rips.add(k)
    return sorted(keep), sorted(rips)


def thin_sheet(shape, fixed):
    """Insert Bends: the faces on the fixed face's side of a thin-walled part, and its thickness.
    Faces without a face at the sheet thickness behind them (the rims, rip slots) are left out."""
    face = shape.Faces[fixed]
    other = across(shape, face)
    if other is None:
        raise ValueError(NO_SHEET)
    t = other[1]

    partners = {}

    def partner(j):
        """The face behind face j at the sheet thickness, else None."""
        if j not in partners:
            f = shape.Faces[j]
            a = across(shape, f) if _plane(f) else None
            partners[j] = _index(shape, a[0], Part.Face) if a is not None and abs(a[1] - t) < 1e-4 else None
        return partners[j]

    # grow over the longest shared edges first: a rip slot can join a face of the other side to
    # this side's faces by a short edge
    import heapq
    keep, behind, heap = [], set(), [(0.0, fixed)]
    while heap:
        _l, j = heapq.heappop(heap)
        if j in keep or j in behind or (j != fixed and (partner(j) is None or partner(j) in keep)):
            continue
        keep.append(j)
        behind.add(partner(j))
        for k, n in neighbours(shape, j):
            if n not in keep:
                heapq.heappush(heap, (-shape.Edges[k].Length, n))
    return sorted(keep), t


# ---------------------------------------------------------------- the sheet
def _engine():
    import SheetMetalFromSolid
    return SheetMetalFromSolid


def _face_dir(face, edge):
    """The direction in face's plane from edge into the face."""
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    u = (b - a).normalize()
    n = face.normalAt(0, 0)
    w = n.cross(u).normalize()
    mid = (a + b) * 0.5
    eps = 1e-3
    return w if face.isInside(mid + w * eps, 1e-7, True) else w * -1


def trim_face(face, edge, d):
    """face with a strip of width d cut away along edge (d < 0: a strip added beyond it)."""
    if abs(d) < 1e-9:
        return face
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    u = (b - a).normalize()
    w = _face_dir(face, edge)
    n = face.normalAt(0, 0)
    if d > 0:
        ext = 3 * d + 1e-3
        p = [a - u * ext, b + u * ext, b + u * ext + w * d, a - u * ext + w * d]
        strip = Part.Face(Part.makePolygon(p + [p[0]]))
        strip.translate(n * -1)
        cut = face.cut(strip.extrude(n * 2))
        return max(cut.Faces, key=lambda f: f.Area) if cut.Faces else face
    p = [a, b, b + w * d, a + w * d]
    strip = Part.Face(Part.makePolygon(p + [p[0]]))
    fused = face.fuse(strip).removeSplitter()
    return max(fused.Faces, key=lambda f: f.Area) if fused.Faces else face


def _sheet_info(engine):
    class Info(engine.smfsShapeInfo):
        """The engine's shape analysis, with each rip trimmed per wall (the engine trims the whole
        wall all round by the widest rip, which shortens its open edges)."""
        trims = None

        def ripSeams(self):
            rest = []
            for group in self.flatFaceGroups:
                for info in group:
                    if info.isRemoved:
                        continue
                    if not _plane(info.face):
                        rest.append(info)
                        continue
                    for e in info.face.OuterWire.Edges:
                        einfo = self.edgeInfoDict[e.hashCode()]
                        if einfo.type != "seam":
                            continue
                        d = self.trims(einfo, info)
                        info.modifiedFace = trim_face(info.modifiedFace, e, d)
            if rest:
                engine.smfsShapeInfo.ripSeams(self)

        def cutBends(self):
            bends = [e for e in self.edgeInfoDict.values() if e.type == "bend"]
            for e in bends:
                e.cutRadius1 = self.cutBend(e, e.faceInf1)
                e.cutRadius2 = self.cutBend(e, e.faceInf2)
            for e in bends:
                _bend_edge(engine, e.faceInf1, e, e.cutRadius1)
                _bend_edge(engine, e.faceInf2, e, e.cutRadius2)
    return Info


def _bend_edge(engine, finfo, einfo, radius):
    """The engine's detectBendEdge, skipping face edges that reach past the bend's ends (a wall
    lengthened over a rip)."""
    corner, along = einfo.edge, einfo.edgeDir
    for edge in finfo.modifiedFace.Edges:
        d = (edge.Vertexes[0].Point - edge.Vertexes[1].Point).normalize()
        if engine.smCompareDirections(d, along) == "other":
            continue
        dist, points, _x = edge.Vertexes[0].distToShape(corner)
        if abs(dist - radius) > 1e-4:
            continue
        p1 = points[0][1]
        _d, points, _x = edge.Vertexes[1].distToShape(corner)
        p2 = points[0][1]
        if p1.distanceToPoint(p2) < 1e-7:
            continue
        einfo.adjustBendEdge(Part.makeLine(p1, p2))


def make_sheet(skin, seams, radius, thickness, inward, corner="Open butt", gap=0.1, ratio=0.5):
    """The sheet metal solid on the shell of faces skin: bends of the inside radius at its edges,
    rips at the edges in seams (edges of skin) with the corner type, gap and overlap ratio."""
    import math
    engine = _engine()
    names = []
    for e in seams:
        k = next((i for i, s in enumerate(skin.Edges) if s.isSame(e)), None)
        if k is not None:
            names.append("Edge%d" % (k + 1))
    Info = _sheet_info(engine)

    def trims(einfo, finfo):
        outer = inward != (einfo.concavityType == "concave")
        angle = einfo.tangent1.getAngle(einfo.tangent2)
        f = 1 / math.tan(angle / 2) if 1e-6 < angle < math.pi - 1e-6 else 1.0
        stop = (thickness * f if outer else 0.0) + gap
        if corner == "Open butt":
            return stop
        f1, f2 = einfo.face1, einfo.face2
        big = f1 if f1.Area >= f2.Area else f2
        covers = finfo.face.isSame(big) == (corner == "Overlap")
        if not covers:
            return stop
        return (1 - ratio) * thickness * f if outer else -ratio * thickness * f

    Info.trims = staticmethod(trims)
    info = Info(skin, names, [])
    info.analyzeEdges(radius, thickness, inward, gap)
    info.groupFaces()
    info.adjustFacesShape()
    t = -thickness if inward else thickness
    info.ripSeams()
    info.cutBends()
    info.generateBends()
    shell = info.makeShell()
    if not info.verifyNormal(shell):
        shell.reverse()
    solid = None
    try:
        for part in shell.Shells:
            s = part.makeOffsetShape(t, 0.001, fill=True)
            solid = s if solid is None else solid.fuse(s)
    except Exception:
        for face in shell.Faces:
            s = face.makeOffsetShape(t, 0.001, fill=True)
            solid = s if solid is None else solid.fuse(s)
    if solid is None or solid.isNull():
        raise ValueError("The sheet could not be made")
    solids = solid.Solids
    return (solids[0] if len(solids) == 1 else Part.makeCompound(solids)).removeSplitter()


def closed_corners(shape, faces):
    """Corners where three sheet faces meet on sharp edges (they cannot all bend)."""
    count = {}
    for i in faces:
        for k, j in neighbours(shape, i):
            if j in faces and j > i and not _tangent(shape, k):
                for v in shape.Edges[k].Vertexes:
                    key = tuple(round(c, 5) for c in v.Point)
                    count[key] = count.get(key, 0) + 1
    return [k for k, n in count.items() if n >= 3]


# ================================================================ features
def is_converted(obj):
    return type(getattr(obj, "Proxy", None)).__name__ in ("SWConvertSolid", "SWInsertBends")


def _common(obj, radius):
    add = obj.addProperty
    add("App::PropertyString", "FixedFace", GROUP, "Fixed face as picked")
    add("App::PropertyVector", "FixedPoint", GROUP, "A point on the fixed face")
    add("App::PropertyVector", "FixedNormal", GROUP, "The fixed face's normal")
    add("App::PropertyLength", "Thickness", GROUP, "Sheet thickness")
    add("App::PropertyLength", "Radius", GROUP, "Bend radius (inside)")
    obj.Radius = radius
    _add_sw_props(obj)
    p = _params()
    obj.SWBendAllowanceType = "K-Factor"
    obj.SWKFactor = p.GetFloat("KFactor", 0.5)
    obj.SWAutoRelief = p.GetString("AutoRelief", "Rectangular")
    obj.SWUseReliefRatio = p.GetBool("UseReliefRatio", True)
    obj.SWReliefRatio = p.GetFloat("ReliefRatio", 0.5)


def _fixed(shape, obj):
    i = face_at(shape, obj.FixedPoint)
    if i is None:
        raise ValueError("The fixed face is gone; edit the feature and pick it again")
    return i


class SWConvertSolid:
    def __init__(self, obj):
        _common(obj, 1.0)
        add = obj.addProperty
        add("App::PropertyBool", "ReverseThickness", GROUP, "Off: the sheet lies inside the solid's faces")
        add("App::PropertyBool", "KeepBody", GROUP, "Keep the solid as a second body")
        add("App::PropertyStringList", "BendEdges", GROUP, "Bend edges, as picked")
        add("App::PropertyVectorList", "BendPoints", GROUP, "A point on each bend edge")
        add("App::PropertyVectorList", "RoundPoints", GROUP, "A point on each round collected as a bend")
        add("App::PropertyStringList", "RipEdges", GROUP, "Rip edges found (read-only)")
        add("App::PropertyEnumeration", "CornerType", GROUP, "Corner default for the rips")
        add("App::PropertyLength", "Gap", GROUP, "Default gap")
        add("App::PropertyFloat", "OverlapRatio", GROUP, "Default overlap ratio")
        add("App::PropertyLinkGlobal", "KeptBody", GROUP, "The solid kept as a second body (outside the Body)")
        _convert_props(obj)
        obj.CornerType = list(CORNER_TYPES)
        obj.Gap = 0.1
        obj.OverlapRatio = 0.5
        obj.Thickness = 1.0
        obj.setEditorMode("RipEdges", 1)
        obj.Proxy = self

    def onDocumentRestored(self, obj):
        # pkg110 made KeptBody a plain link, which may not leave the Body
        if obj.getTypeIdOfProperty("KeptBody") == "App::PropertyLink":
            kept = obj.KeptBody
            obj.removeProperty("KeptBody")
            obj.addProperty("App::PropertyLinkGlobal", "KeptBody", GROUP, "The solid kept as a second body (outside the Body)")
            obj.KeptBody = kept

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Convert to Sheet Metal: needs a solid")
        shape = base.Shape
        if not obj.FixedFace:
            obj.Shape = shape.copy()
            return
        fixed = _fixed(shape, obj)
        bends = [edge_index(shape, p) for p in obj.BendPoints]
        if None in bends:
            raise ValueError("A bend edge is gone; edit the feature and pick it again")
        faces = [face_at(shape, p, planar=False) for p in obj.RoundPoints]
        faces, rips = solid_sheet(shape, fixed, bends, [i for i in faces if i is not None])
        names = ["Edge%d" % (k + 1) for k in rips]
        if list(obj.RipEdges) != names:
            obj.RipEdges = names
        skin_faces, holes = _without_holes([shape.Faces[i] for i in faces])
        skin = Part.makeShell(skin_faces)
        seams = [e for e in skin.Edges if any(_same_edge(e, shape.Edges[k]) for k in rips)]
        n = shape.Faces[fixed].normalAt(0, 0)
        obj.FixedNormal = n
        sheet = make_sheet(skin, seams, float(obj.Radius), float(obj.Thickness), not obj.ReverseThickness,
                           obj.CornerType, float(obj.Gap), float(obj.OverlapRatio))
        _convert_props(obj)
        if obj.RipSketches:
            sheet = rip_lines(sheet, shape, sketch_lines(obj.RipSketches), float(obj.Gap), float(obj.Thickness),
                              not obj.ReverseThickness)
        if holes:
            sheet = _cut_holes(sheet, holes, float(obj.Thickness))
        obj.Shape = sheet

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _without_holes(faces):
    ""


    out, holes = [], []
    for f in faces:
        if _plane(f) and len(f.Wires) > 1:
            try:
                outer = Part.Face(f.Surface, f.OuterWire)
                if not outer.isValid():
                    outer.fix(1e-7, 1e-7, 1e-7)
                n = f.normalAt(0, 0)
                holes += [(w.copy(), n) for w in f.Wires if not w.isSame(f.OuterWire)]
                out.append(outer)
                continue
            except Exception as _fw_err:
                _fw_log("smconvert.py:475", _fw_err)
        out.append(f.copy())
    return out, holes


def _cut_holes(sheet, holes, thickness):
    reach = 2 * thickness + 2.0
    tools = []
    for wire, n in holes:
        try:
            face = Part.Face(wire)
            tools.append(face.translated(n * -(thickness + 1.0)).extrude(n * reach))
        except Exception as _fw_err:
            _fw_log("smconvert.py:488", _fw_err)
    if not tools:
        return sheet
    cut = sheet.cut(tools[0] if len(tools) == 1 else Part.makeCompound(tools))
    solids = cut.Solids
    if not solids:
        return sheet
    return (solids[0] if len(solids) == 1 else Part.makeCompound(solids)).removeSplitter()


def _convert_props(obj):
    """Rip Sketches and Show callouts (older Convert features had neither)."""
    if "RipSketches" not in obj.PropertiesList:
        obj.addProperty("App::PropertyLinkList", "RipSketches", GROUP, "Sketches whose lines rip the sheet")
    if "ShowCallouts" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "ShowCallouts", GROUP, "Label the bends and rips in the 3D view")
        obj.ShowCallouts = True


def sketch_lines(sketches):
    """The straight edges of the rip sketches, placed."""
    out = []
    for sk in sketches:
        try:
            out += [e for e in sk.Shape.Edges if e.Curve.TypeId == "Part::GeomLine"]
        except Exception as _fw_err:
            _fw_log("smconvert.py:514", _fw_err)
    return out


def rip_lines(sheet, solid, lines, gap, thickness, inward):
    """Rip Sketches: a slot gap wide through the sheet along each line lying on a face of the solid."""
    if not lines:
        return sheet
    gap = max(gap, 0.01)
    cuts = []
    for e in lines:
        mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
        i = face_at(solid, mid, planar=True)
        if i is None or solid.Faces[i].distToShape(Part.Vertex(mid))[0] > 1e-4:
            raise ValueError("A rip sketch line is not on a flat face of the solid.")
        f = solid.Faces[i]
        n = f.normalAt(*f.Surface.parameter(mid))
        if solid.isInside(mid + n * 1e-3, 1e-7, False):
            n = n * -1
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        d = (b - a).normalize()
        w = n.cross(d).normalize() * (gap / 2)
        a, b = a - d * 1e-3, b + d * 1e-3
        depth = thickness + 1.0
        base = n * (1.0 if inward else depth)
        pts = [a + w + base, b + w + base, b - w + base, a - w + base]
        cuts.append(Part.Face(Part.makePolygon(pts + pts[:1])).extrude(n * -(depth + 1.0)))
    out = sheet.cut(Part.makeCompound(cuts) if len(cuts) > 1 else cuts[0])
    solids = out.Solids
    return (solids[0] if len(solids) == 1 else Part.makeCompound(solids)).removeSplitter()


def bevels(shape, faces):
    """The beveled faces at the sheet's edges: flat faces next to a sheet face, at a slant to it (not square,
    not parallel), with no face behind them at the sheet thickness (chamfers on the sheet's edges)."""
    keep = set(faces)
    out = []
    for i, f in enumerate(shape.Faces):
        if i in keep or not _plane(f):
            continue
        n = f.normalAt(0, 0)
        near = [shape.Faces[j] for _k, j in neighbours(shape, i)]
        walls = [g for _k, j in neighbours(shape, i) for g in [shape.Faces[j]]
                 if j in keep and _plane(g) and 1e-3 < abs(n.dot(g.normalAt(0, 0))) < 0.999]
        # a chamfer goes part way through the sheet: it does not reach the face behind the wall (a slanted
        # face through the whole thickness, as a rip's, is the sheet's end, not a bevel)
        if walls and not any(_plane(g) and abs(g.normalAt(0, 0).dot(w.normalAt(0, 0))) > 0.999 and not g.isSame(w)
                             for w in walls for g in near):
            out.append(i)
    return out


def keep_bevels(sheet, shape, bevel_faces, thickness):
    """Ignore beveled faces: around each beveled face the sheet takes the part's own shape, so the
    chamfers on its edges stay chamfers (the sheet, built from the faces on one side, stops square where
    that side's face stops)."""
    if not bevel_faces:
        return sheet
    for i in bevel_faces:
        box = shape.Faces[i].BoundBox
        box.enlarge(thickness)
        local = Part.makeBox(box.XLength, box.YLength, box.ZLength, V(box.XMin, box.YMin, box.ZMin))
        sheet = sheet.fuse(shape.common(local))
    solids = sheet.Solids
    return (solids[0] if len(solids) == 1 else Part.makeCompound(solids)).removeSplitter()


def _same_edge(a, b):
    return abs(a.Length - b.Length) < 1e-6 and a.CenterOfMass.distanceToPoint(b.CenterOfMass) < 1e-6


class SWInsertBends:
    def __init__(self, obj):
        _common(obj, 1.0)
        add = obj.addProperty
        add("App::PropertyBool", "IgnoreBeveledFaces", GROUP, "Beveled faces do not become bends")
        add("App::PropertyBool", "AutoRelief", GROUP, "Auto Relief")
        add("App::PropertyStringList", "RipEdges", GROUP, "Edges to rip, as picked")
        add("App::PropertyVectorList", "RipPoints", GROUP, "A point on each edge to rip")
        add("App::PropertyIntegerList", "RipDirections", GROUP, "0: both walls, 1: first wall keeps the corner, 2: second")
        add("App::PropertyLength", "RipGap", GROUP, "Rip gap")
        obj.IgnoreBeveledFaces = True
        obj.AutoRelief = True
        obj.RipGap = 0.1
        obj.setEditorMode("Thickness", 1)
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Insert Bends: needs a thin-walled part")
        shape = base.Shape
        if not obj.FixedFace:
            obj.Shape = shape.copy()
            return
        if obj.RipPoints:
            edges = []
            for p in obj.RipPoints:
                k = edge_index(shape, p)
                if k is None:
                    raise ValueError("An edge to rip is gone; edit the feature and pick it again")
                edges.append(shape.Edges[k])
            dirs = list(obj.RipDirections) + [0] * (len(edges) - len(obj.RipDirections))
            shape = rip(shape, edges, float(obj.RipGap), dirs)
        fixed = _fixed(shape, obj)
        faces, t = thin_sheet(shape, fixed)
        if abs(float(obj.Thickness) - t) > 1e-7:
            obj.Thickness = t
        obj.FixedNormal = shape.Faces[fixed].normalAt(0, 0)
        if closed_corners(shape, faces):
            raise ValueError(CLOSED)
        skin_faces, holes = _without_holes([shape.Faces[i] for i in faces])
        skin = Part.makeShell(skin_faces)
        sheet = make_sheet(skin, [], float(obj.Radius), t, True)
        added = Part.Shape()
        if obj.IgnoreBeveledFaces:
            square = sheet
            sheet = keep_bevels(sheet, shape, bevels(shape, faces), t)
            if sheet is not square:
                added = sheet.cut(square)
        if "BevelShape" not in obj.PropertiesList:
            obj.addProperty("Part::PropertyPartShape", "BevelShape", GROUP, "The chamfered edges kept (left out of "
                            "the flat pattern: the unfolder cannot lay them flat)")
            obj.setEditorMode("BevelShape", 2)
        obj.BevelShape = added
        obj.Shape = sheet

    def dumps(self):
        return None

    def loads(self, state):
        return None


# ================================================================ view providers
_LAST = None        # the open Convert To Sheet Metal / Bends PropertyManager


class ViewProviderConvert:
    ICON = "SheetMetal_FromSolid"

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return _icon(self.ICON)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + obj.Label)
        try:
            panel = InsertPanel if is_insert_bends(obj) else ConvertPanel
            Gui.Control.showDialog(panel(obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def claimChildren(self):
        kept = getattr(self.Object, "KeptBody", None)
        return [kept] if kept is not None else []

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderInsert(ViewProviderConvert):
    ICON = "SheetMetal_AddBend"


def is_convert(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWConvertSolid"


def is_insert_bends(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWInsertBends"


def make(body, insert=False):
    doc = body.Document
    base = body.Tip
    name, proxy, vp, label = (("InsertBends", SWInsertBends, ViewProviderInsert, "Process-Bends") if insert else
                              ("ConvertSolid", SWConvertSolid, ViewProviderConvert, "Convert-Solid"))
    obj = doc.addObject("PartDesign::FeaturePython", name)
    proxy(obj)
    if App.GuiUp:
        vp(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, label)
    p = _params()
    obj.Radius = p.GetFloat("Radius", 1.0)
    if not insert:
        obj.Thickness = p.GetFloat("Thickness", 2.0)
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smconvert.py:722", _fw_err)
    return obj


# ================================================================ PropertyManagers
def _check(name, text, checked=False, enabled=True):
    box = QtWidgets.QCheckBox(text)
    box.setObjectName(name)
    box.setChecked(checked)
    if not enabled:
        box.setEnabled(False)
        box.setToolTip(NOT_YET)
    return box


def _allowance_box(obj, title, changed):
    """The bend allowance box: K-Factor, Bend Table, Bend Allowance, Bend Deduction or Bend Calculation."""
    from . import smallowance
    box = _box(title)
    f = box.layout()
    combo = QtWidgets.QComboBox()
    combo.setObjectName("SWSMAllowance")
    combo.addItems(ALLOWANCES)
    k = _spin("SWSMKFactor", obj.SWKFactor, 0.0, 1.0, suffix="", decimals=4, step=0.05)
    k.setToolTip("K-Factor")
    f.addRow(combo)
    f.addRow("K", k)
    return box, k, smallowance.CustomAllowance(combo, k, f, obj, changed)


def _relief_box(obj, title):
    box = _box(title)
    f = box.layout()
    combo = QtWidgets.QComboBox()
    combo.setObjectName("SWSMRelief")
    combo.addItems(RELIEFS)
    combo.setCurrentText(obj.SWAutoRelief)
    on = _check("SWSMReliefRatioOn", "Use relief ratio", bool(obj.SWUseReliefRatio))
    ratio = _spin("SWSMReliefRatio", obj.SWReliefRatio, 0.05, 2.0, suffix="", decimals=2, step=0.05)
    ratio.setToolTip("Relief ratio")
    f.addRow(combo)
    f.addRow(on)
    f.addRow("Ratio", ratio)
    return box, combo, on, ratio


class _Panel:
    """What the two PropertyManagers share: the selection lists fed from picks on the part before
    the feature (shown while the PropertyManager is open, the result see-through over it), and
    OK/Cancel."""

    def _start(self, obj, new, lists, boxes):
        global _LAST
        _LAST = self
        self.obj, self.new, self.lists = obj, new, lists
        self.pick_error = ""
        self.form = boxes
        self.keys = _DeleteKey(self)
        for w in lists:
            w.installEventFilter(self.keys)
        self.active = lists[1] if obj.FixedFace else lists[0]
        self._mark()
        self._preview(True)
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _preview(self, on):
        ""

        doc = self.obj.Document
        if on:
            base = self.obj.BaseFeature
            if base is None or getattr(self, "ghost", None) is not None:
                return
            ghost = doc.addObject("Part::Feature", "SWConvertPick")
            ghost.Label = "Pick"
            ghost.Shape = base.Shape.copy()
            self.ghost = ghost
            try:
                vo = ghost.ViewObject
                vo.ShowInTree = False
                vo.ShapeAppearance = self.obj.ViewObject.ShapeAppearance
                vo.Transparency = 70
                self.obj.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smconvert.py:809", _fw_err)
            _pickable(ghost, True)
            return
        ghost, self.ghost = getattr(self, "ghost", None), None
        if ghost is not None:
            _pickable(ghost, False)
            try:
                doc.removeObject(ghost.Name)
            except Exception as _fw_err:
                _fw_log("smconvert.py:818", _fw_err)

    def set_active(self, w):
        if w in self.lists:
            self.active = w
            self._mark()

    def _mark(self):
        for w in self.lists:
            w.setProperty("swstyle_active", w is self.active)
            w.setFrameShape(QtWidgets.QFrame.Box if w is self.active else QtWidgets.QFrame.StyledPanel)

    def addSelection(self, doc, name, sub, point):
        o = App.getDocument(doc).getObject(name)
        if sub.startswith(("Face", "Edge")) or (o is not None and o.TypeId == "Sketcher::SketchObject"):
            at = App.Vector(*point) if point else None
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smconvert.py:840", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or picked.Shape.isNull():
            return
        if picked.TypeId == "Sketcher::SketchObject" and hasattr(self, "pick_sketch"):
            self.pick_error = ""
            self.pick_sketch(picked)
            self._apply()
            return
        if not sub:
            return
        item = picked.Shape.getElement(sub)
        if at is None or item.distToShape(Part.Vertex(at))[0] > 1e-4:
            at = inside_point(item) if sub.startswith("Face") else item.valueAt(
                (item.FirstParameter + item.LastParameter) / 2)
        self.pick_error = ""
        self.pick(sub[:4], item, at)
        self._apply()

    def _base(self):
        return self.obj.BaseFeature.Shape

    def _set_fixed(self, i, label, p):
        base = self._base()
        self.obj.FixedFace = label
        self.obj.FixedPoint = p
        self.obj.FixedNormal = base.Faces[i].normalAt(0, 0)
        self.set_active(self.lists[1])

    def _apply(self):
        if self.obj.Document.Recomputing:      # a pick during a recompute: apply it after
            QtCore.QTimer.singleShot(50, self._apply)
            return
        self.obj.touch()
        self.obj.Document.recompute()
        self._fill()
        self._report()

    def _report(self):
        """The red message: why the feature fails, else a wrong pick, else what to select next."""
        if "Invalid" in self.obj.State:
            text = self.obj.getStatusString()
        elif self.pick_error:
            text = self.pick_error
        elif getattr(self, "value_problem", ""):
            text = self.value_problem
        elif not self.obj.FixedFace:
            text = self.HINT_FIXED
        else:
            text = self.hint()
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return "Invalid" not in self.obj.State and bool(self.obj.FixedFace)

    def hint(self):
        return ""

    def _set_k(self, thickness, radius):
        """The part's K-Factor from the allowance choice, for a 90 degree bend."""
        from . import smallowance
        try:
            self.obj.SWKFactor = self.custom.k(thickness, radius, 90.0)
        except ValueError as e:
            self.value_problem = self.value_problem or str(e)
        self.custom.save(self.obj)
        smallowance.add_props(self.obj)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        if hasattr(self, "hide_callouts"):
            self.hide_callouts()
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smconvert.py:916", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smconvert.py:922", _fw_err)

    def _save(self):
        p = _params()
        p.SetFloat("Radius", float(self.obj.Radius))
        p.SetFloat("KFactor", float(self.obj.SWKFactor))
        p.SetString("AutoRelief", self.obj.SWAutoRelief)
        p.SetBool("UseReliefRatio", bool(self.obj.SWUseReliefRatio))
        p.SetFloat("ReliefRatio", float(self.obj.SWReliefRatio))

    def accept(self):
        self._sync()
        self._apply()
        if not self._report():
            return False
        self._preview(False)
        self._kept()
        body = next((p for p in self.obj.InList if p.TypeId == "PartDesign::Body"), None)
        if self.new and body is not None:
            smflatten.ensure(body)      # the Flat-Pattern comes with the part's sheet metal start
        self.obj.Document.commitTransaction()
        self._save()
        self._close()
        return True

    def _kept(self):
        pass

    def reject(self):
        self._preview(False)
        doc = self.obj.Document
        base = self.obj.BaseFeature if self.new else None
        doc.abortTransaction()
        doc.recompute()
        if base is not None:
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smconvert.py:960", _fw_err)
        self._close()
        return True


class ConvertPanel(_Panel):
    """The Convert To Sheet Metal PropertyManager."""
    HINT_FIXED = "Select a fixed face for the sheet metal part."
    HINT_BENDS = "Select the edges to bend."

    def __init__(self, obj, new):
        self.busy = True
        gauges = _box("Sheet Metal Gauges")
        self.gauge = _check("SWSMGauge", "Use gauge table")
        gauges.layout().addRow(self.gauge)

        params = _box("Sheet Metal Parameters")
        f = params.layout()
        self.fixed = _list("SWSMConvertFixed", "#d6ecff", "Fixed face: the face that stays where it is in the flat pattern")
        f.addRow(self.fixed)
        self.thickness = _spin("SWSMThickness", float(obj.Thickness), 0.01, 1000.0, decimals=3)
        self.thickness.setToolTip("Sheet thickness")
        f.addRow("T1", self.thickness)
        self.reverse = _check("SWSMThicknessReverse", "Reverse thickness", bool(obj.ReverseThickness))
        self.reverse.setToolTip("Puts the sheet outside the solid's faces")
        f.addRow(self.reverse)
        self.keep = _check("SWSMKeepBody", "Keep body", bool(obj.KeepBody))
        self.keep.setToolTip("Keeps the solid as a second body")
        f.addRow(self.keep)
        self.radius = _spin("SWSMRadius", float(obj.Radius), 0.0, 10000.0, decimals=3)
        self.radius.setToolTip("Default radius for bends")
        f.addRow("R1", self.radius)
        self.error = error_label()
        f.addRow(self.error)
        self.params_layout = f

        bends = _box("Bend Edges")
        f = bends.layout()
        self.bends = _list("SWSMConvertBends", "#ffd6ec", "Bend edges", rows=4)
        f.addRow(self.bends)
        f.addRow(QtWidgets.QLabel("Rip edges found (Read-only):"))
        self.rips = _list("SWSMConvertRips", "#eeeeee", "Rip edges found", rows=3)
        self.rips.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.rips.setFocusPolicy(QtCore.Qt.NoFocus)
        f.addRow(self.rips)
        self.collect = QtWidgets.QPushButton("Collect all bends")
        self.collect.setObjectName("SWSMCollectBends")
        self.collect.setToolTip("Adds the solid's rounds as bends")
        self.collect.clicked.connect(self.collect_all)
        f.addRow(self.collect)
        _convert_props(obj)
        self.callouts_on = _check("SWSMShowCallouts", "Show callouts", bool(obj.ShowCallouts))
        self.callouts_on.setToolTip("Labels each bend with its radius and each rip with its gap")
        f.addRow(self.callouts_on)

        sketches = _box("Rip Sketches")
        self.rip_sketches = _list("SWSMRipSketches", "#eeeeee", "Rip sketches: sketches of lines on the solid's "
                                  "faces, to rip the sheet there", rows=2)
        sketches.layout().addRow(self.rip_sketches)
        self.callouts = None

        corner = _box("Corner Defaults")
        f = corner.layout()
        self.kinds = []
        for kind, name in zip(CORNER_TYPES, ("SWSMOpenButt", "SWSMOverlap", "SWSMUnderlap")):
            b = _radio(name, kind)
            b.setChecked(obj.CornerType == kind)
            self.kinds.append(b)
            f.addRow(b)
        self.gap = _spin("SWSMGap", float(obj.Gap), 0.0, 100.0, step=0.1)
        self.gap.setToolTip("Default gap")
        f.addRow("Gap", self.gap)
        self.ratio = _spin("SWSMOverlapRatio", float(obj.OverlapRatio), 0.0, 1.0, suffix="", decimals=2, step=0.1)
        self.ratio.setToolTip("Default overlap ratio")
        f.addRow("Ratio", self.ratio)

        allowance, self.kfactor, self.custom = _allowance_box(obj, "Custom Bend Allowance", self._changed)
        relief, self.relief, self.ratio_on, self.relief_ratio = _relief_box(obj, "Custom Relief Type")
        from . import smgauge
        self.gauges = smgauge.GaugeRows(obj, None, self.gauge, gauges.layout(), self.params_layout, self.thickness,
                                        self.radius, self.kfactor, self._changed)

        gauges.setProperty("swstyle_pm_title", CONVERT_TITLE)
        gauges.setProperty("swstyle_pm_icon", "SheetMetal_FromSolid")
        for w in (self.thickness, self.radius, self.gap, self.ratio, self.kfactor, self.relief_ratio):
            w.valueChanged.connect(self._changed)
        for w in [self.reverse, self.keep, self.ratio_on, self.callouts_on] + self.kinds:
            w.toggled.connect(self._changed)
        self.relief.currentIndexChanged.connect(self._changed)
        self._start(obj, new, [self.fixed, self.bends, self.rip_sketches],
                    [gauges, params, bends, sketches, corner, allowance, relief])
        self.busy = False

    def hint(self):
        if not self.obj.BendEdges and not self.obj.RoundPoints:
            return self.HINT_BENDS
        return ""

    def _fill(self):
        obj = self.obj
        self.fixed.clear()
        if obj.FixedFace:
            self.fixed.addItem(obj.FixedFace)
        self.bends.clear()
        for n in obj.BendEdges:
            self.bends.addItem(n)
        base = self._base()
        for p in obj.RoundPoints:
            i = face_at(base, p, planar=False)
            self.bends.addItem("Face%d" % (i + 1) if i is not None else "?")
        self.rips.clear()
        for n in obj.RipEdges:
            self.rips.addItem(n)
        self.rip_sketches.clear()
        for sk in obj.RipSketches:
            self.rip_sketches.addItem(sk.Label)
        self.ratio.setEnabled(obj.CornerType != "Open butt")
        self.custom.show(True)
        self.gauges.show(True)
        self.show_callouts()

    def callout_texts(self):
        """[(point, text)]: each bend edge's radius and each rip's gap, as Show callouts labels them."""
        obj, base = self.obj, self._base()
        out = []
        r, g = float(obj.Radius), float(obj.Gap)
        for p in list(obj.BendPoints) + list(obj.RoundPoints):
            out.append((p, "Radius: %.2fmm" % r))
        for n in obj.RipEdges:
            try:
                e = base.getElement(n)
                out.append((e.valueAt((e.FirstParameter + e.LastParameter) / 2), "Gap: %.2fmm" % g))
            except Exception as _fw_err:
                _fw_log("smconvert.py:1093", _fw_err)
        for e in sketch_lines(obj.RipSketches):
            out.append((e.valueAt((e.FirstParameter + e.LastParameter) / 2), "Gap: %.2fmm" % g))
        return out

    def show_callouts(self):
        """The callouts in the 3D view while the PropertyManager is open."""
        try:
            from pivy import coin
            root = Gui.ActiveDocument.ActiveView.getSceneGraph()
        except Exception:
            return
        if self.callouts is None:
            self.callouts = coin.SoSeparator()
            root.addChild(self.callouts)
        self.callouts.removeAllChildren()
        if not self.callouts_on.isChecked():
            return
        color = coin.SoBaseColor()
        color.rgb = (0.0, 0.0, 0.0)
        font = coin.SoFont()
        font.size = 11
        self.callouts.addChild(color)
        self.callouts.addChild(font)
        for p, text in self.callout_texts():
            sep = coin.SoSeparator()
            at = coin.SoTranslation()
            at.translation = (p.x, p.y, p.z)
            label = coin.SoText2()
            label.string = text
            sep.addChild(at)
            sep.addChild(label)
            self.callouts.addChild(sep)

    def hide_callouts(self):
        if self.callouts is None:
            return
        try:
            Gui.ActiveDocument.ActiveView.getSceneGraph().removeChild(self.callouts)
        except Exception as _fw_err:
            _fw_log("smconvert.py:1133", _fw_err)
        self.callouts = None

    def shown_callouts(self):
        if self.callouts is None:
            return []
        return [self.callouts.getChild(i).getChild(1).string[0].getString()
                for i in range(2, self.callouts.getNumChildren())]

    def remove_current(self, w):
        row = w.currentRow()
        if row < 0:
            return
        obj = self.obj
        if w is self.rip_sketches:
            links = list(obj.RipSketches)
            del links[row]
            obj.RipSketches = links
        elif w is self.fixed:
            obj.FixedFace = ""
        else:
            n = len(obj.BendEdges)
            if row < n:
                names, points = list(obj.BendEdges), list(obj.BendPoints)
                del names[row], points[row]
                obj.BendEdges, obj.BendPoints = names, points
            else:
                rounds_ = list(obj.RoundPoints)
                del rounds_[row - n]
                obj.RoundPoints = rounds_
        self._apply()

    def pick_sketch(self, sketch):
        """A sketch picked (in the tree or the 3D view): in or out of the rip sketches."""
        links = list(self.obj.RipSketches)
        if sketch in links:
            links.remove(sketch)
        else:
            links.append(sketch)
        self.obj.RipSketches = links
        self.set_active(self.rip_sketches)

    def pick(self, kind, item, at):
        base = self._base()
        obj = self.obj
        if kind == "Face":
            i = face_at(base, at, planar=False)
            if i is None:
                return
            if self.active is self.fixed or not obj.FixedFace:
                if not _plane(base.Faces[i]):
                    self.pick_error = "The fixed face must be a flat face."
                    return
                self._set_fixed(i, "Face%d" % (i + 1), at)
            elif i in rounds(base):
                self._toggle_round(i, at)
            return
        k = edge_index(base, at)
        if k is None or self.active is not self.bends:
            return
        names, points = list(obj.BendEdges), list(obj.BendPoints)
        name = "Edge%d" % (k + 1)
        if name in names:
            j = names.index(name)
            del names[j], points[j]
        else:
            names.append(name)
            points.append(at)
        obj.BendEdges, obj.BendPoints = names, points

    def _toggle_round(self, i, at):
        base = self._base()
        pts = list(self.obj.RoundPoints)
        hit = [j for j, p in enumerate(pts) if face_at(base, p, planar=False) == i]
        if hit:
            del pts[hit[0]]
        else:
            pts.append(at)
        self.obj.RoundPoints = pts

    def collect_all(self):
        base = self._base()
        self.obj.RoundPoints = [inside_point(base.Faces[i]) for i in rounds(base)]
        self._apply()

    def _sync(self):
        obj = self.obj
        self.value_problem = self.gauges.apply()
        obj.Thickness = self.thickness.value()
        obj.Radius = self.radius.value()
        obj.ReverseThickness = self.reverse.isChecked()
        obj.ShowCallouts = self.callouts_on.isChecked()
        obj.KeepBody = self.keep.isChecked()
        obj.CornerType = next(k for k, b in zip(CORNER_TYPES, self.kinds) if b.isChecked())
        obj.Gap = self.gap.value()
        obj.OverlapRatio = self.ratio.value()
        self._set_k(self.thickness.value(), self.radius.value())
        obj.SWAutoRelief = self.relief.currentText()
        obj.SWUseReliefRatio = self.ratio_on.isChecked()
        obj.SWReliefRatio = self.relief_ratio.value()

    def _changed(self, *_a):
        if self.busy:
            return
        if self.sender_is_untoggled():
            return
        self._sync()
        self._apply()

    def sender_is_untoggled(self):
        # a radio button group sends toggled twice (off, then on): act on the second only
        return not any(b.isChecked() for b in self.kinds)

    def _save(self):
        _Panel._save(self)
        _params().SetFloat("Thickness", float(self.obj.Thickness))

    def _kept(self):
        """Keep body: the solid stays as a second body beside the sheet metal part."""
        obj, doc = self.obj, self.obj.Document
        kept = obj.KeptBody
        if obj.KeepBody and kept is None:
            kept = doc.addObject("PartDesign::SubShapeBinder", "KeptBody")
            kept.Support = [(obj.BaseFeature, ("",))]
            kept.Label = naming.next_label(doc, "Body-Keep")
            obj.KeptBody = kept
            doc.recompute()
        elif not obj.KeepBody and kept is not None:
            obj.KeptBody = None
            doc.removeObject(kept.Name)


class InsertPanel(_Panel):
    """The Bends PropertyManager (Insert Bends)."""
    HINT_FIXED = "Select a fixed face or edge."

    def __init__(self, obj, new):
        self.busy = True
        bend = _box("Bend Parameters")
        f = bend.layout()
        self.fixed = _list("SWSMInsertFixed", "#d6ecff", "Fixed face or edge: stays where it is in the flat pattern")
        f.addRow(self.fixed)
        self.radius = _spin("SWSMRadius", float(obj.Radius), 0.0, 10000.0)
        self.radius.setToolTip("Bend radius")
        f.addRow("R1", self.radius)
        self.beveled = _check("SWSMIgnoreBeveled", "Ignore beveled faces", bool(obj.IgnoreBeveledFaces))
        self.beveled.setToolTip("On: chamfers on the sheet's edges stay chamfers; off: the edges come out square")
        f.addRow(self.beveled)
        self.error = error_label()
        f.addRow(self.error)

        allowance, self.kfactor, self.custom = _allowance_box(obj, "Bend Allowance", self._changed)
        relief, self.relief, self.ratio_on, self.relief_ratio = _relief_box(obj, "Auto Relief")
        self.auto = _check("SWSMAutoRelief", "Auto Relief", bool(obj.AutoRelief))
        relief.layout().insertRow(0, self.auto)

        rip = _box("Rip Parameters")
        f = rip.layout()
        self.rip_edges = _list("SWSMRipEdges", "#ffd6ec", "Edges to rip", rows=4)
        f.addRow(self.rip_edges)
        self.change = QtWidgets.QPushButton("Change Direction")
        self.change.setObjectName("SWSMRipChangeDirection")
        self.change.setToolTip("Change the direction of the selected rip: both walls, then one wall, then the other")
        self.change.clicked.connect(self.change_direction)
        f.addRow(self.change)
        self.gap = _spin("SWSMRipGap", float(obj.RipGap), 0.001, 100.0, step=0.1)
        self.gap.setToolTip("Rip gap")
        f.addRow("Rip gap:", self.gap)

        bend.setProperty("swstyle_pm_title", INSERT_TITLE)
        bend.setProperty("swstyle_pm_icon", "SheetMetal_AddBend")
        for w in (self.radius, self.kfactor, self.relief_ratio, self.gap):
            w.valueChanged.connect(self._changed)
        for w in (self.auto, self.ratio_on, self.beveled):
            w.toggled.connect(self._changed)
        self.relief.currentIndexChanged.connect(self._changed)
        self._start(obj, new, [self.fixed, self.rip_edges], [bend, allowance, relief, rip])
        self.busy = False

    def _dirs(self):
        return list(self.obj.RipDirections) + [0] * (len(self.obj.RipEdges) - len(self.obj.RipDirections))

    def _fill(self):
        obj = self.obj
        self.fixed.clear()
        if obj.FixedFace:
            self.fixed.addItem(obj.FixedFace)
        row = self.rip_edges.currentRow()
        self.rip_edges.clear()
        for n, d in zip(obj.RipEdges, self._dirs()):
            self.rip_edges.addItem(n if d == 0 else "%s (%s)" % (n, DIRECTIONS[d]))
        if 0 <= row < self.rip_edges.count():
            self.rip_edges.setCurrentRow(row)
        on = self.auto.isChecked()
        for w in (self.relief, self.ratio_on, self.relief_ratio):
            w.setEnabled(on)
        self.custom.show(True)

    def remove_current(self, w):
        row = w.currentRow()
        if row < 0:
            return
        obj = self.obj
        if w is self.fixed:
            obj.FixedFace = ""
        else:
            names, points, dirs = list(obj.RipEdges), list(obj.RipPoints), self._dirs()
            del names[row], points[row], dirs[row]
            obj.RipEdges, obj.RipPoints, obj.RipDirections = names, points, dirs
        self._apply()

    def pick(self, kind, item, at):
        base = self._base()
        obj = self.obj
        if self.active is self.fixed or not obj.FixedFace:
            if kind == "Face":
                i = face_at(base, at)
                if i is None:
                    self.pick_error = "The fixed face must be a flat face."
                    return
                self._set_fixed(i, "Face%d" % (i + 1), at)
            else:
                k = edge_index(base, at)
                if k is None:
                    return
                faces = [f for f in base.ancestorsOfType(base.Edges[k], Part.Face) if _plane(f)]
                if not faces:
                    return
                face = max(faces, key=lambda f: f.Area)
                i = _index(base, face, Part.Face)
                self._set_fixed(i, "Edge%d" % (k + 1), inside_point(face))
            return
        if kind != "Edge":
            return
        k = edge_index(base, at)
        if k is None:
            return
        name = "Edge%d" % (k + 1)
        names, points, dirs = list(obj.RipEdges), list(obj.RipPoints), self._dirs()
        if name in names:
            j = names.index(name)
            del names[j], points[j], dirs[j]
        else:
            names.append(name)
            points.append(at)
            dirs.append(0)
        obj.RipEdges, obj.RipPoints, obj.RipDirections = names, points, dirs

    def change_direction(self):
        row = self.rip_edges.currentRow()
        if row < 0:
            row = self.rip_edges.count() - 1
        if row < 0:
            return
        dirs = self._dirs()
        dirs[row] = (dirs[row] + 1) % 3
        self.obj.RipDirections = dirs
        self._apply()
        self.rip_edges.setCurrentRow(row)

    def _sync(self):
        obj = self.obj
        obj.Radius = self.radius.value()
        obj.RipGap = self.gap.value()
        obj.AutoRelief = self.auto.isChecked()
        obj.IgnoreBeveledFaces = self.beveled.isChecked()
        self.value_problem = ""
        self._set_k(float(obj.Thickness), self.radius.value())
        obj.SWAutoRelief = self.relief.currentText()
        obj.SWUseReliefRatio = self.ratio_on.isChecked()
        obj.SWReliefRatio = self.relief_ratio.value()

    def _changed(self, *_a):
        if self.busy:
            return
        self._sync()
        self._apply()


# ================================================================ commands
def _part_body():
    """The active body when its last feature is a solid and nothing else is open."""
    if App.ActiveDocument is None or smflatten.blocked():
        return None
    try:
        if Gui.Control.activeDialog():
            return None
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception as _fw_err:
        _fw_log("smconvert.py:1430", _fw_err)
        return None
    if body is None or body.Tip is None or body.Tip.Shape.isNull() or not body.Tip.Shape.Solids:
        return None
    return body


def start(insert=False):
    body = _part_body()
    if body is None:
        return
    picked = [(o.Document.Name, o.Object.Name, sub, App.Vector(p)) for o in Gui.Selection.getSelectionEx()
              for sub, p in zip(o.SubElementNames, o.PickedPoints) if sub.startswith(("Face", "Edge"))]
    doc = body.Document
    doc.openTransaction(INSERT_TITLE if insert else CONVERT_TITLE)
    try:
        obj = make(body, insert)
        doc.recompute()
        panel = (InsertPanel if insert else ConvertPanel)(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    for doc_name, name, sub, at in picked:
        panel._picked(doc_name, name, sub, at)


class ConvertCommand:
    def GetResources(self):
        return {"Pixmap": _icon("SheetMetal_FromSolid"), "MenuText": "Convert to Sheet Metal",
                "ToolTip": "Turns a solid into sheet metal from a fixed face and its bend edges."}

    def IsActive(self):
        return _part_body() is not None

    def Activated(self):
        start(False)


class InsertCommand:
    def GetResources(self):
        return {"Pixmap": _icon("SheetMetal_AddBend"), "MenuText": "Insert Bends",
                "ToolTip": "Turns a shelled part into sheet metal by adding bends at its sharp edges."}

    def IsActive(self):
        return _part_body() is not None

    def Activated(self):
        start(True)


def register():
    if CONVERT_COMMAND not in Gui.listCommands():
        Gui.addCommand(CONVERT_COMMAND, ConvertCommand())
    if INSERT_COMMAND not in Gui.listCommands():
        Gui.addCommand(INSERT_COMMAND, InsertCommand())
