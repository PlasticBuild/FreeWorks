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
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtGui, QtWidgets

from . import paths, smflatten
from .smbaseflange import _box
from .smedgeflange import _radio, error_label
from .smunfold import _DeleteKey, _icon, _list

COMMAND = "SWStyle_SMExportDXF"
TITLE = "DXF / DWG Output"
V = App.Vector
LAYERS = {   # layer -> (DXF colour, line type)
    "GEOMETRY": (7, "CONTINUOUS"),
    "HIDDEN": (8, "DASHED"),
    "BEND_LINES": (3, "DASHDOT"),
    "SKETCHES": (5, "CONTINUOUS"),
    "BOUNDING_BOX": (1, "DASHDOT"),
    "LIBRARY_FEATURES": (6, "CONTINUOUS"),
    "FORMING_TOOLS": (4, "CONTINUOUS"),
}

# and Bounding box drew a cut's outline a second time (its sketch on top of its edges) and a frame round it
ENTITIES = (("Geometry", "GEOMETRY", True, True), ("Hidden edges", "HIDDEN", False, True),
            ("Bend lines", "BEND_LINES", True, True), ("Sketches", "SKETCHES", False, True),
            ("Library features", "LIBRARY_FEATURES", False, True), ("Forming tools", "FORMING_TOOLS", False, True),
            ("Bounding box", "BOUNDING_BOX", False, True))
TOL = 1e-6


# ================================================================ the flat pattern
def flat(body):
    """(flat shape, bend lines, the flat face on the fixed face's plane) of a sheet metal part, as
    Flatten makes them."""
    base = smflatten.root(body)
    own = smflatten.own_flat(base)
    if own is not None:
        shape, folds, face = own
        return shape, (Part.makeCompound(folds) if folds else None), face
    tip = smflatten._without_welds(body, body.Tip)
    face = smflatten.fixed_face(base, tip) if base is not None else None
    if face is None:
        raise ValueError("The part has no fixed face to flatten from")
    from . import smbendtable, smflatdisplay
    k = smbendtable.k_of(base, tip.Shape)
    # through smflatdisplay: the bundled unfolder tries again when the SheetMetal add-on's fails
    shape, folds, _n, _name, err, _s, _o = smflatdisplay.unfold("_dxf", {1: k}, tip, face, "ansi")
    if shape is None:
        raise ValueError("The part does not unfold (error %s)" % err)
    fp = smflatten.flat_pattern(body)
    if fp is not None:
        from . import smcornertrim
        shape = smcornertrim.apply_all(fp, shape)
    plane = tip.Shape.getElement(face)
    name = smflatten._plane_face(shape, plane.normalAt(0, 0), plane.CenterOfMass)
    return shape, folds, shape.getElement(name)


def _rotation(x, z):
    x = (x - z * x.dot(z)).normalize()
    y = z.cross(x)
    return App.Rotation(App.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, 0, 0, 0, 1))


def frame(body, face):
    """The drawing's placement on the flat face: as the Base Flange's sketch was drawn, else the fixed
    face seen from outside with X along the global X axis."""
    base = smflatten.root(body)
    n = face.normalAt(0, 0)
    point = face.Vertexes[0].Point
    sketch = getattr(base, "BendSketch", None)
    if sketch is not None:
        pl = sketch.getGlobalPlacement()
        z = pl.Rotation.multVec(V(0, 0, 1))
        if abs(abs(z.dot(n)) - 1) < 1e-7:
            origin = pl.Base + z * (point - pl.Base).dot(z)
            return App.Placement(origin, pl.Rotation)
    x = V(1, 0, 0) if abs(n.x) < 0.9 else V(0, 1, 0)
    return App.Placement(point, _rotation(x, n))


def aligned(placement, origin=None, xaxis=None, yaxis=None):
    """The drawing frame moved to the Output Alignment picks (a point and an X or Y direction)."""
    z = placement.Rotation.multVec(V(0, 0, 1))
    pos = placement.Base if origin is None else origin
    rot = placement.Rotation
    d = xaxis if xaxis is not None else None
    if d is None and yaxis is not None:
        d = yaxis.cross(z)          # x = y x z
    if d is not None:
        rot = _rotation(d, z)
    return App.Placement(pos, rot)


# ---------------------------------------------------------------- entities
def _p2(p):
    return (round(p.x, 9), round(p.y, 9))


def _entity(edge, layer):
    """One DXF entity of an edge already in the drawing frame (z ~ 0). Ellipses and splines also keep their
    points (e[2], e[3] as a polyline's), for the Cleanup window and R12 files."""
    c = edge.Curve
    if c.TypeId == "Part::GeomLine":
        a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        return ("LINE", layer, _p2(a), _p2(b))
    if c.TypeId == "Part::GeomCircle" and abs(abs(c.Axis.z) - 1) < 1e-7:
        if edge.isClosed():
            return ("CIRCLE", layer, _p2(c.Center), c.Radius)
        s, e = edge.valueAt(edge.FirstParameter), edge.valueAt(edge.LastParameter)
        if c.Axis.z < 0:
            s, e = e, s
        a0 = math.degrees(math.atan2(s.y - c.Center.y, s.x - c.Center.x)) % 360
        a1 = math.degrees(math.atan2(e.y - c.Center.y, e.x - c.Center.x)) % 360
        return ("ARC", layer, _p2(c.Center), c.Radius, a0, a1)
    pts = [_p2(p) for p in edge.discretize(Deflection=0.01)]
    closed = edge.isClosed()
    if c.TypeId == "Part::GeomEllipse" and abs(abs(c.Axis.z) - 1) < 1e-7:
        u0, u1 = edge.FirstParameter, edge.LastParameter
        t0 = (u0 if c.Axis.z > 0 else -u1) % (2 * math.pi)     # DXF ellipses run counter-clockwise
        t1 = t0 + (u1 - u0)
        major = c.XAxis * c.MajorRadius
        return ("ELLIPSE", layer, pts, closed, {
            "center": _p2(c.Center), "major": (major.x, major.y), "ratio": c.MinorRadius / c.MajorRadius,
            "t0": t0, "t1": t1 if closed or t1 <= 2 * math.pi + 1e-12 else t1 - 2 * math.pi})
    try:
        bs = c.toBSpline(edge.FirstParameter, edge.LastParameter)
        if bs.isPeriodic():
            bs.setNotPeriodic()
        m = bs.getMultiplicities()
        if min(m[0], m[-1]) < bs.Degree + 1:       # CAD programs read clamped splines (end knots degree + 1 times)
            bs.segment(bs.FirstParameter, bs.LastParameter)
        poles = [_p2(p) for p in bs.getPoles()]
        weights = list(bs.getWeights()) if bs.isRational() else []
        return ("SPLINE", layer, pts, closed, {"degree": bs.Degree, "knots": list(bs.KnotSequence),
                                               "poles": poles, "weights": weights})
    except Exception as _fw_err:
        _fw_log("smdxf.py:177", _fw_err)
        return ("POLYLINE", layer, pts, closed)


def _in_frame(shape, placement):
    s = shape.copy()
    s.transformShape(placement.inverse().toMatrix(), True)
    return s


def _key(edge):
    return (round(edge.Length, 4),) + tuple(round(v, 4) for v in edge.CenterOfMass)


def _drop(edge):
    """An edge of the drawing frame put on z = 0 (edges parallel to the drawing move straight down)."""
    zs = [p.z for p in edge.discretize(8)]
    if max(zs) - min(zs) < 1e-6:
        e = edge.copy()
        e.translate(V(0, 0, -zs[0]))
        return e
    pts = [V(p.x, p.y, 0) for p in edge.discretize(Deflection=0.01)]
    return Part.makePolygon(pts) if len(pts) > 1 else None


def entities(body, placement, which, shape=None, folds=None, face=None):
    """The drawing of the flat pattern: [(kind, layer, ...)] for the layers in which."""
    if shape is None:
        shape, folds, face = flat(body)
    out = []
    seen = set()
    if "GEOMETRY" in which:
        for e in _in_frame(face, placement).Edges:
            seen.add(_key(e))
            out.append(_entity(e, "GEOMETRY"))
    if "HIDDEN" in which:
        # the far side's edges that the near side does not cover (cuts and forms on the other side)
        n = face.normalAt(0, 0)
        for f in shape.Faces:
            if f.isSame(face) or f.Surface.TypeId != "Part::GeomPlane" or abs(abs(f.normalAt(0, 0).dot(n)) - 1) > 1e-7:
                continue
            for e in _in_frame(f, placement).Edges:
                if abs(e.Vertexes[0].Point.z) < 1e-6:
                    continue
                e = _drop(e)
                if e is None or e.Length < TOL or _key(e) in seen:
                    continue
                seen.add(_key(e))
                out.append(_entity(e, "HIDDEN"))
    if "BEND_LINES" in which and folds is not None and not folds.isNull():
        for e in _in_frame(folds, placement).Edges:
            e = _drop(e)
            if e is not None:
                out.append(_entity(e, "BEND_LINES"))
    if "SKETCHES" in which:
        for sk in body.Group:
            if sk.TypeId != "Sketcher::SketchObject" or not sk.ViewObject or not sk.ViewObject.Visibility:
                continue
            for e in _in_frame(sk.Shape, placement).Edges:
                e = _drop(e)
                if e is not None:
                    out.append(_entity(e, "SKETCHES"))
    if "BOUNDING_BOX" in which:
        for e in _in_frame(smflatten._bounding_box(face), placement).Edges:
            out.append(_entity(e, "BOUNDING_BOX"))
    for layer, test in (("FORMING_TOOLS", _is_form), ("LIBRARY_FEATURES", _is_stamp)):
        if layer in which:
            for e in footprints(body, shape, face, test):
                e = _drop(_in_frame(e, placement))
                if e is not None and e.Length > TOL:
                    out.append(_entity(e, layer))
    return out


def _is_form(o):
    from .smformingtool import is_form_feature
    return is_form_feature(o)


def _is_stamp(o):
    return type(getattr(o, "Proxy", None)).__name__ == "SWStamp"


def footprints(body, flat_shape, face, test):
    """The outlines, at the sheet's mid-plane under the flat face, of the material the features passing
    test add or take away: where they sit on the flat face (forms on flanges fold away and are left out)."""
    from .smnormalcut import baked
    n = face.normalAt(0, 0)
    point = face.Vertexes[0].Point
    ds = [v.Point.dot(n) for v in flat_shape.Vertexes]
    t = max(ds) - min(ds)
    level = point.dot(n)
    mid = level - t / 2 if flat_shape.isInside(point - n * (t / 2), 1e-6, True) else level + t / 2
    out = []
    for o in body.Group:
        if not test(o) or o.BaseFeature is None or "Invalid" in o.State or o.Shape.isNull():
            continue
        try:
            base, made = baked(o.BaseFeature.Shape), baked(o.Shape)
            changed = [x for x in (made.cut(base), base.cut(made)) if x.Volume > 1e-9]
        except Exception as _fw_err:
            _fw_log("smdxf.py:278", _fw_err)
            continue
        region = changed[0].fuse(changed[1:]).removeSplitter() if len(changed) > 1 else (changed[0] if changed else None)
        if region is None:
            continue
        for w in region.slice(n, mid):
            c = w.CenterOfMass if hasattr(w, "CenterOfMass") else w.BoundBox.Center
            if face.isInside(c + n * (level - c.dot(n)), 1e-4, True) or _in_face(face, w, n, level):
                out += w.Edges
    return out


def _in_face(face, wire, n, level):
    """Any point of the wire, moved onto the face's plane, on the face."""
    for v in wire.Vertexes:
        p = v.Point + n * (level - v.Point.dot(n))
        if face.isInside(p, 1e-4, True):
            return True
    return False


# ---------------------------------------------------------------- Annotation views (TechDraw)
def drawing_views(body):
    """The TechDraw part views of the body (or of its features), on any drawing page of the document."""
    members = set([body.Name] + [o.Name for o in getattr(body, "Group", None) or []])
    out = []
    for o in body.Document.Objects:
        if not o.isDerivedFrom("TechDraw::DrawViewPart"):
            continue
        if any(getattr(s, "Name", "") in members for s in (getattr(o, "Source", None) or [])):
            out.append(o)
    return out



# drawn straight from the model (no drawing needed). name -> (direction to the viewer, X direction of the view)
STANDARD_VIEWS = (("*Front", (0, -1, 0), (1, 0, 0)), ("*Back", (0, 1, 0), (-1, 0, 0)),
                  ("*Left", (-1, 0, 0), (0, -1, 0)), ("*Right", (1, 0, 0), (0, 1, 0)),
                  ("*Top", (0, 0, 1), (1, 0, 0)), ("*Bottom", (0, 0, -1), (1, 0, 0)))
CURRENT_VIEW = "*Current"


def _current_view():
    """The graphics area's view: (direction to the viewer, X direction on screen)."""
    try:
        cam = Gui.ActiveDocument.ActiveView.getCameraOrientation()
        r = App.Rotation(*cam.Q) if hasattr(cam, "Q") else App.Rotation(*cam.getValue())
        return r.multVec(V(0, 0, 1)), r.multVec(V(1, 0, 0))
    except Exception as _fw_err:
        _fw_log("smdxf.py:_current_view", _fw_err)
        return V(0, 0, 1), V(1, 0, 0)


def model_view_entities(shape, name, hidden=False):
    """A standard view of the model at full size, in the view's own 2D frame (X right, Y up)."""
    if name == CURRENT_VIEW:
        z, x = _current_view()
    else:
        _n, z, x = next(v for v in STANDARD_VIEWS if v[0] == name)
        z, x = V(*z), V(*x)
    pl = App.Placement(V(), _rotation(x, z))
    flat_shape = _in_frame(shape, pl)
    import TechDraw
    got = TechDraw.projectEx(flat_shape, V(0, 0, 1))
    out = []
    keep = [("GEOMETRY", got[0]), ("GEOMETRY", got[3])]
    if hidden:
        keep += [("HIDDEN", got[5]), ("HIDDEN", got[8])]
    for layer, part in keep:
        if part is None or part.isNull():
            continue
        for e in part.Edges:
            e = _drop(e)
            if e is not None and e.Length > TOL:
                out.append(_entity(e, layer))
    return out


def view_entities(view, hidden=True):
    """A drawing view's lines at full size (the view's scale taken out), in its own 2D frame."""
    scale = float(getattr(view, "Scale", 1.0)) or 1.0
    m = App.Matrix()
    m.scale(1 / scale, -1 / scale, 1)       # TechDraw keeps Y pointing down
    out = []
    for layer, edges in (("GEOMETRY", view.getVisibleEdges()), ("HIDDEN", view.getHiddenEdges() if hidden else [])):
        for shape in edges:
            for e in shape.transformGeometry(m).Edges:
                e = _drop(e)
                if e is not None and e.Length > TOL:
                    out.append(_entity(e, layer))
    return out


def _shifted(ents, dx):
    """The entities moved dx along X (views side by side in one file)."""
    out = []
    for e in ents:
        kind = e[0]
        if kind == "LINE":
            out.append((kind, e[1], (e[2][0] + dx, e[2][1]), (e[3][0] + dx, e[3][1])))
        elif kind in ("CIRCLE", "ARC"):
            out.append((kind, e[1], (e[2][0] + dx, e[2][1])) + tuple(e[3:]))
        else:
            moved = (kind, e[1], [(x + dx, y) for x, y in e[2]], e[3])
            if len(e) > 4:
                data = dict(e[4])
                if "center" in data:
                    data["center"] = (data["center"][0] + dx, data["center"][1])
                if "poles" in data:
                    data["poles"] = [(x + dx, y) for x, y in data["poles"]]
                moved += (data,)
            out.append(moved)
    return out


def _span(ents):
    xs = []
    for e in ents:
        if e[0] == "LINE":
            xs += [e[2][0], e[3][0]]
        elif e[0] in ("CIRCLE", "ARC"):
            xs += [e[2][0] - e[3], e[2][0] + e[3]]
        else:
            xs += [p[0] for p in e[2]]
    return (min(xs), max(xs)) if xs else (0.0, 0.0)


def face_entities(faces, origin=None, xaxis=None, yaxis=None):
    """Faces/loops/edges: each picked face's outlines, drawn in its own plane."""
    out = []
    for f in faces:
        z = f.normalAt(0, 0)
        x = V(1, 0, 0) if abs(z.x) < 0.9 else V(0, 1, 0)
        pl = aligned(App.Placement(f.Vertexes[0].Point, _rotation(x, z)), origin, xaxis, yaxis)
        out.append([_entity(e, "GEOMETRY") for e in _in_frame(f, pl).Edges])
    return out


# ---------------------------------------------------------------- DXF (ASCII)

# splines, by default). R12 has no splines or ellipses: they go out as polylines.
VERSIONS = ("R12", "R2000-2002")
SPLINES = ("Export all splines as splines", "Export all splines as polylines")
LTYPES = (("CONTINUOUS", "Solid line", ()), ("DASHED", "Dashed __ __ __", (5.0, -2.5)),
          ("DASHDOT", "Dash dot __ . __ .", (6.0, -2.0, 0.0, -2.0)))


def shared_options():
    ""

    try:
        from . import drawexport
        return drawexport.options()
    except Exception as _fw_err:
        _fw_log("smdxf.py:shared_options", _fw_err)
        return None


def version():
    """The flavour this module writes: R12, else R2000-2002 (a later Version is written by drawdxf.convert)."""
    o = shared_options()
    if o is None:
        v = paths.params().GetString("DXFVersion", VERSIONS[1])
        return v if v in VERSIONS else VERSIONS[1]
    return VERSIONS[0] if o["version"] == "R12" else VERSIONS[1]


def splines_as_splines():
    o = shared_options()
    if o is None:
        return paths.params().GetBool("DXFSplinesAsSplines", True)
    return o["splines"] != "Polylines"


def _pairs(*items):
    return "".join("%d\n%s\n" % (c, v) for c, v in items)


def _as_polyline(e):
    return ("POLYLINE",) + tuple(e[1:4])


def dxf_text(ents, ver=None, splines=None):
    """An ASCII DXF of the entities, in millimetres: AutoCAD R2000-2002 (splines and ellipses kept, unless
    splines is False) or R12."""
    ver = version() if ver is None else ver
    splines = splines_as_splines() if splines is None else splines
    if ver == "R12":
        return _r12([_as_polyline(e) if e[0] in ("SPLINE", "ELLIPSE") else e for e in ents])
    return _r2000([_as_polyline(e) if e[0] == "SPLINE" and not splines else e for e in ents])


def _r12(ents):
    """An AutoCAD R12 DXF."""
    used = sorted({e[1] for e in ents} | {"GEOMETRY"})
    out = [_pairs((0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, "AC1009"), (9, "$MEASUREMENT"), (70, 1),
                  (9, "$INSUNITS"), (70, 4), (0, "ENDSEC"))]
    out.append(_pairs((0, "SECTION"), (2, "TABLES"), (0, "TABLE"), (2, "LTYPE"), (70, 3)))
    for name, text, pattern in LTYPES:
        out.append(_pairs((0, "LTYPE"), (2, name), (70, 0), (3, text), (72, 65), (73, len(pattern)),
                          (40, "%.4f" % sum(abs(p) for p in pattern))))
        out.append("".join(_pairs((49, "%.4f" % p)) for p in pattern))
    out.append(_pairs((0, "ENDTAB"), (0, "TABLE"), (2, "LAYER"), (70, len(used))))
    for name in used:
        colour, ltype = LAYERS.get(name, (7, "CONTINUOUS"))
        out.append(_pairs((0, "LAYER"), (2, name), (70, 0), (62, colour), (6, ltype)))
    out.append(_pairs((0, "ENDTAB"), (0, "ENDSEC"), (0, "SECTION"), (2, "ENTITIES")))
    f = "%.6f"
    for e in ents:
        kind, layer = e[0], e[1]
        if kind == "LINE":
            (x1, y1), (x2, y2) = e[2], e[3]
            out.append(_pairs((0, "LINE"), (8, layer), (10, f % x1), (20, f % y1), (30, "0.0"),
                              (11, f % x2), (21, f % y2), (31, "0.0")))
        elif kind == "CIRCLE":
            (x, y), r = e[2], e[3]
            out.append(_pairs((0, "CIRCLE"), (8, layer), (10, f % x), (20, f % y), (30, "0.0"), (40, f % r)))
        elif kind == "ARC":
            (x, y), r, a0, a1 = e[2], e[3], e[4], e[5]
            out.append(_pairs((0, "ARC"), (8, layer), (10, f % x), (20, f % y), (30, "0.0"), (40, f % r),
                              (50, f % a0), (51, f % a1)))
        else:
            pts, closed = e[2], e[3]
            out.append(_pairs((0, "POLYLINE"), (8, layer), (66, 1), (10, "0.0"), (20, "0.0"), (30, "0.0"),
                              (70, 1 if closed else 0)))
            for x, y in pts:
                out.append(_pairs((0, "VERTEX"), (8, layer), (10, f % x), (20, f % y), (30, "0.0")))
            out.append(_pairs((0, "SEQEND"), (8, layer)))
    out.append(_pairs((0, "ENDSEC"), (0, "EOF")))
    return "".join(out)


class _Handles:
    def __init__(self, first=0x20):
        self.next = first

    def __call__(self):
        h = "%X" % self.next
        self.next += 1
        return h


def _r2000(ents):
    """An AutoCAD R2000-2002 DXF (AC1015): the tables, blocks and objects AutoCAD needs, with handles."""
    used = sorted({e[1] for e in ents} | {"GEOMETRY"})
    new = _Handles()
    t = {k: new() for k in ("VPORT", "LTYPE", "LAYER", "STYLE", "VIEW", "UCS", "APPID", "DIMSTYLE",
                            "BLOCK_RECORD", "ROOT", "GROUP")}
    model, paper = new(), new()
    f = "%.6f"

    def table(name, records, extra=()):
        out = [_pairs((0, "TABLE"), (2, name), (5, t[name]), (330, 0), (100, "AcDbSymbolTable"),
                      (70, len(records)), *extra)]
        out += records
        out.append(_pairs((0, "ENDTAB")))
        return "".join(out)

    def record(kind, sub, table_name, *items, code=5):
        return _pairs((0, kind), (code, new()), (330, t[table_name]), (100, "AcDbSymbolTableRecord"),
                      (100, sub), *items)

    tables = [table("VPORT", [record("VPORT", "AcDbViewportTableRecord", "VPORT", (2, "*Active"), (70, 0),
                                     (10, 0.0), (20, 0.0), (11, 1.0), (21, 1.0), (12, 0.0), (22, 0.0),
                                     (40, 1000.0), (41, 1.34))])]
    ltypes = [record("LTYPE", "AcDbLinetypeTableRecord", "LTYPE", (2, n), (70, 0), (3, ""), (72, 65), (73, 0),
                     (40, 0.0)) for n in ("ByBlock", "ByLayer")]
    for name, text, pattern in LTYPES:
        dashes = [item for p in pattern for item in ((49, "%.4f" % p), (74, 0))]
        ltypes.append(record("LTYPE", "AcDbLinetypeTableRecord", "LTYPE", (2, name), (70, 0), (3, text), (72, 65),
                             (73, len(pattern)), (40, "%.4f" % sum(abs(p) for p in pattern)), *dashes))
    tables.append(table("LTYPE", ltypes))
    layers = [record("LAYER", "AcDbLayerTableRecord", "LAYER", (2, "0"), (70, 0), (62, 7), (6, "CONTINUOUS"))]
    for name in used:
        colour, ltype = LAYERS.get(name, (7, "CONTINUOUS"))
        layers.append(record("LAYER", "AcDbLayerTableRecord", "LAYER", (2, name), (70, 0), (62, colour), (6, ltype)))
    tables.append(table("LAYER", layers))
    tables.append(table("STYLE", [record("STYLE", "AcDbTextStyleTableRecord", "STYLE", (2, "Standard"), (70, 0),
                                         (40, 0.0), (41, 1.0), (50, 0.0), (71, 0), (42, 2.5), (3, "txt"),
                                         (4, ""))]))
    tables.append(table("VIEW", []))
    tables.append(table("UCS", []))
    tables.append(table("APPID", [record("APPID", "AcDbRegAppTableRecord", "APPID", (2, "ACAD"), (70, 0))]))
    tables.append(table("DIMSTYLE", [record("DIMSTYLE", "AcDbDimStyleTableRecord", "DIMSTYLE", (2, "Standard"),
                                            (70, 0), code=105)], extra=((100, "AcDbDimStyleTable"),)))
    records = []
    for handle, name in ((model, "*Model_Space"), (paper, "*Paper_Space")):
        records.append(_pairs((0, "BLOCK_RECORD"), (5, handle), (330, t["BLOCK_RECORD"]),
                              (100, "AcDbSymbolTableRecord"), (100, "AcDbBlockTableRecord"), (2, name)))
    tables.append(table("BLOCK_RECORD", records))
    blocks = []
    for handle, name in ((model, "*Model_Space"), (paper, "*Paper_Space")):
        blocks.append(_pairs((0, "BLOCK"), (5, new()), (330, handle), (100, "AcDbEntity"), (8, "0"),
                             (100, "AcDbBlockBegin"), (2, name), (70, 0), (10, 0.0), (20, 0.0), (30, 0.0),
                             (3, name), (1, ""),
                             (0, "ENDBLK"), (5, new()), (330, handle), (100, "AcDbEntity"), (8, "0"),
                             (100, "AcDbBlockEnd")))
    body = []
    for e in ents:
        kind, layer = e[0], e[1]
        head = ((0, "LWPOLYLINE" if kind == "POLYLINE" else kind), (5, new()), (330, model), (100, "AcDbEntity"),
                (8, layer))
        if kind == "LINE":
            (x1, y1), (x2, y2) = e[2], e[3]
            body.append(_pairs(*head, (100, "AcDbLine"), (10, f % x1), (20, f % y1), (30, "0.0"),
                               (11, f % x2), (21, f % y2), (31, "0.0")))
        elif kind == "CIRCLE":
            (x, y), r = e[2], e[3]
            body.append(_pairs(*head, (100, "AcDbCircle"), (10, f % x), (20, f % y), (30, "0.0"), (40, f % r)))
        elif kind == "ARC":
            (x, y), r, a0, a1 = e[2], e[3], e[4], e[5]
            body.append(_pairs(*head, (100, "AcDbCircle"), (10, f % x), (20, f % y), (30, "0.0"), (40, f % r),
                               (100, "AcDbArc"), (50, f % a0), (51, f % a1)))
        elif kind == "ELLIPSE":
            d = e[4]
            body.append(_pairs(*head, (100, "AcDbEllipse"), (10, f % d["center"][0]), (20, f % d["center"][1]),
                               (30, "0.0"), (11, f % d["major"][0]), (21, f % d["major"][1]), (31, "0.0"),
                               (210, "0.0"), (220, "0.0"), (230, "1.0"), (40, "%.9f" % d["ratio"]),
                               (41, "%.9f" % d["t0"]), (42, "%.9f" % d["t1"])))
        elif kind == "SPLINE":
            d = e[4]
            flags = 8 | (4 if d["weights"] else 0)
            items = [(100, "AcDbSpline"), (210, "0.0"), (220, "0.0"), (230, "1.0"), (70, flags),
                     (71, d["degree"]), (72, len(d["knots"])), (73, len(d["poles"])), (74, 0),
                     (42, "0.0000001"), (43, "0.0000001")]
            items += [(40, "%.12g" % k) for k in d["knots"]]
            items += [(41, "%.12g" % w) for w in d["weights"]]
            for x, y in d["poles"]:
                items += [(10, f % x), (20, f % y), (30, "0.0")]
            body.append(_pairs(*head, *items))
        else:
            pts, closed = e[2], e[3]
            if closed and len(pts) > 2 and pts[0] == pts[-1]:
                pts = pts[:-1]
            items = [(100, "AcDbPolyline"), (90, len(pts)), (70, 1 if closed else 0), (43, "0.0")]
            for x, y in pts:
                items += [(10, f % x), (20, f % y)]
            body.append(_pairs(*head, *items))
    objects = _pairs((0, "DICTIONARY"), (5, t["ROOT"]), (330, 0), (100, "AcDbDictionary"), (281, 1),
                     (3, "ACAD_GROUP"), (350, t["GROUP"]),
                     (0, "DICTIONARY"), (5, t["GROUP"]), (330, t["ROOT"]), (100, "AcDbDictionary"), (281, 1))
    header = _pairs((0, "SECTION"), (2, "HEADER"), (9, "$ACADVER"), (1, "AC1015"), (9, "$HANDSEED"),
                  (5, "%X" % new.next), (9, "$MEASUREMENT"), (70, 1), (9, "$INSUNITS"), (70, 4),
                  (0, "ENDSEC"), (0, "SECTION"), (2, "CLASSES"), (0, "ENDSEC"))
    return "".join([header, _pairs((0, "SECTION"), (2, "TABLES")), *tables, _pairs((0, "ENDSEC")),
                    _pairs((0, "SECTION"), (2, "BLOCKS")), *blocks, _pairs((0, "ENDSEC")),
                    _pairs((0, "SECTION"), (2, "ENTITIES")), *body, _pairs((0, "ENDSEC")),
                    _pairs((0, "SECTION"), (2, "OBJECTS")), objects, _pairs((0, "ENDSEC"), (0, "EOF"))])


def write(path, ents, doc=None):
    """The DXF file, with the Export > DXF/DWG options: Version, Splines and End points merge (dxfopts91),
    in the document's own units (units105: an IPS part's flat pattern in inches, $INSUNITS 1)."""
    o = shared_options() or {}
    later = o.get("version") not in (None, "R12", "R14", "2000-2002")
    merge = float(o.get("merge_distance", 0.0)) if o.get("merge") else 0.0
    from . import drawdxf
    units, size = drawdxf.doc_units(doc or App.ActiveDocument)
    if not later and merge <= 0 and units == 4:
        with open(path, "w", newline="\r\n") as fh:
            fh.write(dxf_text(ents))
        return path
    import tempfile
    tmp = os.path.join(tempfile.mkdtemp(prefix="fw_dxf_"), "part.dxf")
    with open(tmp, "w", newline="\r\n") as fh:
        fh.write(dxf_text(ents))
    ver = o.get("version") if (later or merge > 0) and o.get("version") else \
        ("R12" if version() == "R12" else "2000-2002")
    drawdxf.convert(tmp, path, version=ver, scale=1.0 / size, splines=splines_as_splines(), merge=merge / size,
                    units=units)
    return path


# ================================================================ DXF/DWG Cleanup
def _path(e):
    path = QtGui.QPainterPath()
    kind = e[0]
    if kind == "LINE":
        path.moveTo(e[2][0], -e[2][1])
        path.lineTo(e[3][0], -e[3][1])
    elif kind == "CIRCLE":
        (x, y), r = e[2], e[3]
        path.addEllipse(QtCore.QPointF(x, -y), r, r)
    elif kind == "ARC":
        (x, y), r, a0, a1 = e[2], e[3], e[4], e[5]
        sweep = (a1 - a0) % 360 or 360
        rect = QtCore.QRectF(x - r, -y - r, 2 * r, 2 * r)
        path.arcMoveTo(rect, a0)
        path.arcTo(rect, a0, sweep)
    else:
        pts = e[2]
        path.moveTo(pts[0][0], -pts[0][1])
        for x, y in pts[1:]:
            path.lineTo(x, -y)
        if e[3]:
            path.closeSubpath()
    return path


class Cleanup(QtWidgets.QDialog):
    """The DXF/DWG Cleanup window: the drawing on black; Remove Entities with undo/redo; Save, Cancel."""
    COLOURS = {"GEOMETRY": "#ffffff", "HIDDEN": "#9a9a9a", "BEND_LINES": "#ffffff", "SKETCHES": "#4aa3ff",
               "BOUNDING_BOX": "#ffffff"}

    def __init__(self, title, files, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWDXFCleanup")
        self.setWindowTitle("DXF/DWG Cleanup - " + title)
        self.files = files              # [(path, entities)]
        self.page = 0
        self.undo, self.redo = [], []
        lay = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        bar.addStretch()
        self.buttons = {}
        for name, icon, tip, slot in (("select", "mouse_pointer", "Select", lambda: self.set_pan(False)),
                                      ("zoomin", "zoom-in", "Zoom In", lambda: self.view.scale(1.25, 1.25)),
                                      ("zoomout", "zoom-out", "Zoom Out", lambda: self.view.scale(0.8, 0.8)),
                                      ("fit", "zoom-fit-best", "Zoom to Fit", self.fit),
                                      ("pan", "cursor-pan", "Pan", lambda: self.set_pan(True))):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWDXF_" + name)
            b.setIcon(QtGui.QIcon(":/icons/%s.svg" % icon))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            bar.addWidget(b)
            self.buttons[name] = b
        bar.addStretch()
        for name in ("select", "pan"):
            self.buttons[name].setCheckable(True)
        self.buttons["select"].setChecked(True)
        lay.addLayout(bar)
        self.scene = QtWidgets.QGraphicsScene(self)
        self.view = QtWidgets.QGraphicsView(self.scene)
        self.view.setObjectName("SWDXFView")
        self.view.setBackgroundBrush(QtGui.QBrush(QtGui.QColor("#000000")))
        self.view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.view.setMinimumSize(420, 340)
        self.view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        lay.addWidget(self.view)
        row = QtWidgets.QHBoxLayout()
        self.remove = QtWidgets.QPushButton("Remove Entities")
        self.remove.setObjectName("SWDXFRemove")
        self.remove.clicked.connect(self.remove_selected)
        self.undo_b = QtWidgets.QToolButton()
        self.undo_b.setObjectName("SWDXFUndo")
        self.undo_b.setIcon(QtGui.QIcon(":/icons/edit-undo.svg"))
        self.undo_b.clicked.connect(self.do_undo)
        self.redo_b = QtWidgets.QToolButton()
        self.redo_b.setObjectName("SWDXFRedo")
        self.redo_b.setIcon(QtGui.QIcon(":/icons/edit-redo.svg"))
        self.redo_b.clicked.connect(self.do_redo)
        self.save = QtWidgets.QPushButton("Save")
        self.save.setObjectName("SWDXFSave")
        self.save.clicked.connect(self.save_all)
        self.cancel = QtWidgets.QPushButton("Cancel")
        self.cancel.setObjectName("SWDXFCancel")
        self.cancel.clicked.connect(self.reject)
        for w in (self.remove, self.undo_b, self.redo_b):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(self.save)
        row.addWidget(self.cancel)
        lay.addLayout(row)
        self.saved = []
        self.resize(640, 520)
        self._draw()

    def set_pan(self, pan):
        ""
        self.view.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag if pan else QtWidgets.QGraphicsView.RubberBandDrag)
        self.buttons["select"].setChecked(not pan)
        self.buttons["pan"].setChecked(pan)

    def showEvent(self, event):
        super().showEvent(event)
        from . import safe_later as _sl; _sl.later(0, self.fit, self, "scene")

    def _draw(self):
        self.scene.clear()
        _path_, ents = self.files[self.page]
        for i, e in enumerate(ents):
            pen = QtGui.QPen(QtGui.QColor(self.COLOURS.get(e[1], "#ffffff")))
            pen.setCosmetic(True)
            if LAYERS.get(e[1], (0, "CONTINUOUS"))[1] == "DASHDOT":
                pen.setStyle(QtCore.Qt.DashDotLine)
            elif LAYERS.get(e[1], (0, "CONTINUOUS"))[1] == "DASHED":
                pen.setStyle(QtCore.Qt.DashLine)
            item = self.scene.addPath(_path(e), pen)
            item.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)
            item.setData(0, i)
        self._buttons()
        from . import safe_later as _sl; _sl.later(0, self.fit, self, "scene")

    def fit(self):
        r = self.scene.itemsBoundingRect()
        if not r.isEmpty():
            m = max(r.width(), r.height()) * 0.05
            self.view.fitInView(r.adjusted(-m, -m, m, m), QtCore.Qt.KeepAspectRatio)

    def _buttons(self):
        self.undo_b.setEnabled(bool(self.undo))
        self.redo_b.setEnabled(bool(self.redo))

    def remove_selected(self):
        idx = sorted(it.data(0) for it in self.scene.selectedItems())
        if not idx:
            return
        path, ents = self.files[self.page]
        self.undo.append(list(ents))
        self.redo.clear()
        self.files[self.page] = (path, [e for i, e in enumerate(ents) if i not in idx])
        self._draw()

    def do_undo(self):
        if self.undo:
            path, ents = self.files[self.page]
            self.redo.append(ents)
            self.files[self.page] = (path, self.undo.pop())
            self._draw()

    def do_redo(self):
        if self.redo:
            path, ents = self.files[self.page]
            self.undo.append(ents)
            self.files[self.page] = (path, self.redo.pop())
            self._draw()

    def save_all(self):
        self.saved = [write(path, ents) for path, ents in self.files]
        self.accept()


# ================================================================ PropertyManager
_LAST = None


def _separate(path, n):
    stem, ext = os.path.splitext(path)
    return [path] if n <= 1 else ["%s-%d%s" % (stem, i + 1, ext or ".dxf") for i in range(n)]


class Panel:
    """The DXF / DWG Output PropertyManager."""

    def __init__(self, body, path, shape=None):
        global _LAST
        _LAST = self
        self.body, self.path = body, path

        # Faces/loops/edges and Annotation views only)
        self.sheet = body is not None and body.TypeId == "PartDesign::Body" and smflatten.root(body) is not None
        self.shape = shape if shape is not None else body.Shape
        self.cleanup = None
        export = _box("Export")
        f = export.layout()
        self.kinds = [_radio("SWDXFSheetMetal", "Sheet metal"), _radio("SWDXFFaces", "Faces / loops / edges"),
                      _radio("SWDXFAnnotation", "Annotation views")]
        for b in self.kinds:
            f.addRow(b)
        self.kinds[0].setVisible(self.sheet)
        self.faces = _list("SWDXFFaceList", "#d6ecff", "Faces to export", rows=3)
        self.faces.setVisible(False)
        f.addRow(self.faces)
        self.views = QtWidgets.QListWidget()
        self.views.setObjectName("SWDXFViews")
        self.views.setToolTip("The part's views on its drawings: tick the ones to export")
        self.views.setMaximumHeight(90)
        drawn = drawing_views(body)
        for name in [v[0] for v in STANDARD_VIEWS] + [CURRENT_VIEW]:
            item = QtWidgets.QListWidgetItem(name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if name == "*Front" and not drawn else QtCore.Qt.Unchecked)
            item.setData(QtCore.Qt.UserRole, name)
            self.views.addItem(item)
        for v in drawn:
            item = QtWidgets.QListWidgetItem(v.Label)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            item.setData(QtCore.Qt.UserRole, v.Name)
            self.views.addItem(item)
        self.views.setMaximumHeight(150)
        self.views.setVisible(False)
        f.addRow(self.views)
        self.hidden_row = QtWidgets.QCheckBox("Hidden edges")
        self.hidden_row.setObjectName("SWDXFViewHidden")
        self.hidden_row.setToolTip("Also export the edges hidden behind the part, dashed")
        self.hidden_row.setVisible(False)
        f.addRow(self.hidden_row)

        ents = _box("Entities To Export")
        f = ents.layout()
        self.checks = {}
        for text, layer, on, _live in ENTITIES:
            c = QtWidgets.QCheckBox(text)
            c.setObjectName("SWDXF" + text.replace(" ", ""))
            c.setChecked(on)
            f.addRow(c)
            if layer:
                self.checks[layer] = c
        self.entities_box = ents

        align = _box("Output Alignment")
        f = align.layout()
        self.origin = _list("SWDXFOrigin", "#ffd6ec", "Origin: a vertex of the flat pattern")
        self.xaxis = _list("SWDXFXAxis", "#ffd6ec", "X axis: an edge of the flat pattern")
        self.yaxis = _list("SWDXFYAxis", "#ffd6ec", "Y axis: an edge of the flat pattern")
        f.addRow(self.origin)
        f.addRow("X axis:", self.xaxis)
        f.addRow("Y axis:", self.yaxis)
        self.align_box = align
        if not self.sheet:
            self.origin.setToolTip("Origin: a vertex of the part")
            self.xaxis.setToolTip("X axis: a straight edge of the part")
            self.yaxis.setToolTip("Y axis: a straight edge of the part")

        options = _box("Export Options")
        f = options.layout()
        self.single = _radio("SWDXFSingle", "Single file")
        self.separate = _radio("SWDXFSeparate", "Separate files")
        self.single.setChecked(True)
        f.addRow(self.single)
        f.addRow(self.separate)
        self.error = error_label()
        f.addRow(self.error)

        export.setProperty("swstyle_pm_title", TITLE)
        export.setProperty("swstyle_pm_icon", "SheetMetal_UnfoldExport")
        self.form = [export, ents, align, options]
        self.picks = {"origin": None, "x": None, "y": None, "faces": []}
        self.lists = [self.origin, self.xaxis, self.yaxis, self.faces]
        self.active = self.origin
        self.keys = _DeleteKey(self)
        for w in self.lists:
            w.installEventFilter(self.keys)
        for b in self.kinds:
            b.toggled.connect(self._mode)
        self.was_flat = True
        if self.sheet:
            self.kinds[0].setChecked(True)
            self.was_flat = smflatten.is_flat(body.Document)
            if not self.was_flat:
                smflatten.set_flat(body, True)      # the flat pattern shows while exporting
        picked = self._preselected_faces()
        if not self.sheet:
            self.kinds[1 if picked else 2].setChecked(True)
            self._mode()
        for item, sub in picked:
            self.picks["faces"].append(item)
            self.faces.addItem(sub)
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _preselected_faces(self):
        ""
        out = []
        try:
            for sel in Gui.Selection.getSelectionEx(self.body.Document.Name):
                for sub, item in zip(sel.SubElementNames, sel.SubObjects):
                    if sub.startswith("Face") and item.Surface.__class__.__name__ == "Plane":
                        out.append((item.copy(), sub))
        except Exception as _fw_err:
            _fw_log("smdxf.py:_preselected_faces", _fw_err)
        return out

    def faces_mode(self):
        return self.kinds[1].isChecked()

    def views_mode(self):
        return self.kinds[2].isChecked()

    def _mode(self, *_a):
        on = self.faces_mode()
        self.faces.setVisible(on)
        self.views.setVisible(self.views_mode())
        self.entities_box.setVisible(self.sheet and not on and not self.views_mode())    # dxf90: hidden, not greyed
        self.hidden_row.setVisible(self.views_mode())
        self.align_box.setVisible(not self.views_mode())      # views keep their own frame
        if on:
            self.set_active(self.faces)
        self.error.setText("")
        self.error.setVisible(False)

    def checked_views(self):
        """The ticked views: a standard view's name (*Front ...) or a drawing view."""
        doc = self.body.Document
        out = []
        for i in range(self.views.count()):
            item = self.views.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                key = item.data(QtCore.Qt.UserRole)
                v = key if key.startswith("*") else doc.getObject(key)
                if v is not None:
                    out.append(v)
        return out

    def set_active(self, w):
        if w in self.lists:
            self.active = w

    def remove_current(self, w):
        key = {id(self.origin): "origin", id(self.xaxis): "x", id(self.yaxis): "y"}.get(id(w))
        if key:
            self.picks[key] = None
            w.clear()
        elif w is self.faces and w.currentRow() >= 0:
            del self.picks["faces"][w.currentRow()]
            w.takeItem(w.currentRow())

    def addSelection(self, doc, name, sub, point):
        QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, point))

    def _picked(self, doc, name, sub, point):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smdxf.py:866", _fw_err)
        obj = App.getDocument(doc).getObject(name)
        if obj is None or not sub:
            return
        item = obj.Shape.getElement(sub)
        w = self.active
        if w is self.faces and sub.startswith("Face"):
            self.picks["faces"].append(item.copy())
            self.faces.addItem(sub)
        elif w is self.origin and sub.startswith("Vertex"):
            self.picks["origin"] = item.Point
            self.origin.clear()
            self.origin.addItem(sub)
            self.set_active(self.xaxis)
        elif w in (self.xaxis, self.yaxis) and sub.startswith("Edge") and item.Curve.TypeId == "Part::GeomLine":
            a, b = item.Vertexes[0].Point, item.Vertexes[-1].Point
            d = b - a
            if self.picks["origin"] is not None and (a - self.picks["origin"]).Length > (b - self.picks["origin"]).Length:
                d = a - b       # pointing away from the origin
            self.picks["x" if w is self.xaxis else "y"] = d
            w.clear()
            w.addItem(sub)

    def layers(self):
        return [layer for layer, c in self.checks.items() if c.isChecked()]

    def drawing(self):
        """[(path, entities)] as they will be written."""
        if self.views_mode():
            views = self.checked_views()
            if not views:
                raise ValueError("Tick the views to export.")
            hidden = self.hidden_row.isChecked()
            pages = [model_view_entities(self.shape, v, hidden) if isinstance(v, str) else view_entities(v, hidden)
                     for v in views]
            if self.separate.isChecked():
                return list(zip(_separate(self.path, len(pages)), pages))
            out, x = [], 0.0
            for ents in pages:                  # side by side, 20 mm apart
                lo, hi = _span(ents)
                out += _shifted(ents, x - lo)
                x += (hi - lo) + 20.0
            return [(self.path, out)]
        if self.faces_mode():
            if not self.picks["faces"]:
                raise ValueError("Select the faces to export.")
            pages = face_entities(self.picks["faces"], self.picks["origin"], self.picks["x"], self.picks["y"])
            if self.separate.isChecked():
                return list(zip(_separate(self.path, len(pages)), pages))
            return [(self.path, [e for page in pages for e in page])]
        shape, folds, face = flat(self.body)
        pl = aligned(frame(self.body, face), self.picks["origin"], self.picks["x"], self.picks["y"])
        return [(self.path, entities(self.body, pl, self.layers(), shape, folds, face))]

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smdxf.py:926", _fw_err)
        if self.sheet and not self.was_flat:
            smflatten.set_flat(self.body, False)
        Gui.Control.closeDialog()

    def accept(self):
        try:
            files = self.drawing()
        except Exception as error:
            self.error.setText(str(error))
            self.error.show()
            return False
        fp = smflatten.flat_pattern(self.body) if self.sheet else None
        self.cleanup = Cleanup(fp.Label if fp is not None else
                               ("Flat-Pattern" if self.sheet else self.body.Document.Label), files)
        self._close()
        self.cleanup.open()
        return True

    def reject(self):
        self._close()
        return True


# ================================================================ command
def _sheet_body():
    if App.ActiveDocument is None:
        return None
    try:
        if Gui.Control.activeDialog():
            return None
    except Exception as _fw_err:
        _fw_log("smdxf.py:957", _fw_err)
    return smflatten._body()


def start(path=None):
    body = _sheet_body()
    if body is None:
        return None
    if path is None:
        doc = body.Document
        folder = os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~")
        path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save As",
                                                         os.path.join(folder, doc.Label + ".dxf"), "DXF (*.dxf)")
        if not path:
            return None
        if not path.lower().endswith(".dxf"):
            path += ".dxf"
    panel = Panel(body, path)
    Gui.Control.showDialog(panel)
    return panel


def start_part(doc, path, objs):
    ""

    try:
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
    except Exception as _fw_err:
        _fw_log("smdxf.py:start_part", _fw_err)
    body = smflatten._body(doc)
    if body is None:
        try:
            body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
        except Exception:
            body = None
    if body is None or body.Document is not doc:
        body = next((o for o in objs if o.TypeId == "PartDesign::Body"), None) or objs[0]
    shape = Part.makeCompound([o.Shape for o in objs]) if len(objs) > 1 else None
    panel = Panel(body, path, shape)
    Gui.Control.showDialog(panel)
    return panel


class Command:
    def GetResources(self):
        return {"Pixmap": _icon("SheetMetal_UnfoldExport"), "MenuText": "Export to DXF/DWG",
                "ToolTip": "Saves the flat pattern as a DXF drawing."}

    def IsActive(self):
        return _sheet_body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
