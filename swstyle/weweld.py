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

import json
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, wetrim
from . import pmboxes

COMMAND = "SWStyle_WEWeldBead"
TITLE = "Weld Bead"
LABEL = "Weld Bead"
GROUP = "Weld Bead"
TYPES = ("Full length", "Intermittent", "Staggered")
HINT = "Select the Weld From and Weld To faces."
PATH_HINT = "Select the edges to weld along."
SYMBOLS = ("None", "Fillet", "Square Groove", "V Groove", "Bevel Groove", "U Groove", "J Groove", "Flare-V",
           "Flare-Bevel", "Plug", "Spot", "Seam", "Edge")
BEADS = ("Fillet Bead", "Groove Bead")
GROOVES = ("Square", "Bevel", "V", "J", "U", "Flare-V", "Flare-Bevel")
GROOVE_SYMBOL = {"Square": "Square Groove", "Bevel": "Bevel Groove", "V": "V Groove", "J": "J Groove",
                 "U": "U Groove", "Flare-V": "Flare-V", "Flare-Bevel": "Flare-Bevel"}
_LAST = None
CONTOURS = ("None", "Flush", "Convex", "Concave")
TOL = 1e-5


def _weicon(name):
    from . import weprofile
    return weprofile.icon(name)

def is_weld_bead(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "WeldBead"


def _load(text, default):
    try:
        return json.loads(text or "")
    except Exception:
        return default


def new_path():
    return {"from": [], "to": [], "size": 3.0, "type": "Full length", "length": 10.0, "pitch": 20.0,
            "tangent": True, "mode": "Weld Geometry", "edges": [], "other": False, "other_size": 3.0,
            "bead": "Fillet Bead", "groove": "Bevel"}


# ---------------------------------------------------------------- faces
def face_ref(obj, sub):
    """What is stored for a picked face: a member body and a point on the face, or any object's face."""
    try:
        face = obj.Shape.getElement(sub)
    except Exception as _fw_err:
        _fw_log("weweld.py:94", _fw_err)
        return None
    if face.ShapeType != "Face":
        return None
    ref = wetrim.ref_of(obj)
    if ref is not None:
        u0, u1, v0, v1 = face.ParameterRange
        p = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
        if not face.isInside(p, 1e-6, True):
            p = face.CenterOfMass
        item = {"kind": "body", "ref": ref, "point": [p.x, p.y, p.z], "type": face.Surface.TypeId}
        if face.Surface.TypeId == "Part::GeomPlane":
            n = face.normalAt(0, 0)
            item["normal"] = [n.x, n.y, n.z]
        return item
    return {"kind": "face", "obj": obj.Name, "sub": sub}


def edge_ref(obj, sub):
    """What is stored for a picked edge (Weld Path): a member body and the edge's middle, or any object's edge."""
    try:
        edge = obj.Shape.getElement(sub)
    except Exception as _fw_err:
        _fw_log("weweld.py:117", _fw_err)
        return None
    if edge.ShapeType != "Edge":
        return None
    ref = wetrim.ref_of(obj)
    if ref is not None:
        p = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
        return {"kind": "body", "ref": ref, "point": [p.x, p.y, p.z], "edge": True}
    return {"kind": "edge", "obj": obj.Name, "sub": sub}


def _body_of(doc, item, sources):
    if item.get("kind") in ("face", "edge"):
        return doc.getObject(item.get("obj", ""))
    return next((s for s in sources if wetrim.ref_of(s) == item["ref"]), None) \
        or wetrim.current_tip(doc, item["ref"])


def resolve_edge(doc, item, sources):
    """(the body the edge is on, the edge)."""
    body = _body_of(doc, item, sources)
    if body is None:
        return None, None
    if item.get("kind") == "edge":
        try:
            return body, body.Shape.getElement(item["sub"])
        except Exception:
            return None, None
    p = Part.Vertex(App.Vector(*item["point"]))
    best = min(body.Shape.Edges, key=lambda e: e.distToShape(p)[0], default=None)
    return body, best


def _solids(doc, sources, skip):
    """The shapes a Weld Path edge can be welded to: the sources and the document's visible solids."""
    out = []
    for o in list(sources) + list(doc.Objects):
        if o is skip or o in out or is_weld_bead(o) or not hasattr(o, "Shape"):
            continue
        try:
            if not o.Shape.Solids or not o.Visibility:
                continue
        except Exception:
            continue
        out.append(o)
    return out


def _edge_chain(shape, edge):
    """The edge and the edges of shape running on from it tangent to it, end to end."""
    out = [edge]
    todo = [edge]
    while todo:
        e = todo.pop()
        for v in e.Vertexes:
            for g in shape.ancestorsOfType(v, Part.Edge):
                if any(g.isSame(x) for x in out):
                    continue
                te = e.tangentAt(e.Curve.parameter(v.Point))
                tg = g.tangentAt(g.Curve.parameter(v.Point))
                if abs(te.dot(tg)) > 1 - 1e-6:
                    out.append(g)
                    todo.append(g)
    return out


def edge_welds(doc, path, sources):
    """[(edge, from face, to face)] of a Weld Path: each picked edge where its body's face meets another
    body's face."""
    out = []
    for item in path.get("edges", []):
        body, edge = resolve_edge(doc, item, sources)
        if edge is None:
            continue
        edges = _edge_chain(body.Shape, edge) if path.get("tangent", True) else [edge]
        others = _solids(doc, sources, body)
        for e in edges:
            if any(_same(e, x[0]) for x in out):
                continue
            mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
            g = next((f for o in others for f in o.Shape.Faces if _on(e, f)), None)
            if g is None:
                continue
            ng = _normal(g, mid)
            f = next((h for h in body.Shape.ancestorsOfType(e, Part.Face)
                      if abs(_normal(h, mid).dot(ng)) < 1 - 1e-6), None)
            if f is not None:
                out.append((e, f, g))
    return out


def resolve(doc, item, sources):
    """(the shape the face is on, the face)."""
    if item.get("kind") == "face":
        obj = doc.getObject(item.get("obj", ""))
        try:
            return obj.Shape, obj.Shape.getElement(item["sub"])
        except Exception:
            return None, None
    body = next((s for s in sources if wetrim.ref_of(s) == item["ref"]), None) \
        or wetrim.current_tip(doc, item["ref"])
    if body is None:
        return None, None
    p = Part.Vertex(App.Vector(*item["point"]))
    normal = App.Vector(*item["normal"]) if "normal" in item else None
    best, best_d = None, None
    for f in body.Shape.Faces:
        if f.Surface.TypeId != item.get("type", f.Surface.TypeId):
            continue
        if normal is not None and f.normalAt(0, 0).dot(normal) < 1 - 1e-6:
            continue        # a plane keeps its direction (not the tube's inside face next to it)
        d = f.distToShape(p)[0]
        if best_d is None or d < best_d:
            best, best_d = f, d
    return body.Shape, best


def _tangent_chain(shape, face):
    """The face and the faces of shape tangent to it, edge to edge."""
    faces = [face]
    seen = {face.hashCode()}
    todo = [face]
    while todo:
        f = todo.pop()
        for e in f.Edges:
            mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
            for g in shape.ancestorsOfType(e, Part.Face):
                if g.hashCode() in seen or g.isSame(f):
                    continue
                if _normal(f, mid).dot(_normal(g, mid)) > 1 - 1e-6:
                    seen.add(g.hashCode())
                    faces.append(g)
                    todo.append(g)
    return faces


def _normal(face, point):
    u, v = face.Surface.parameter(point)
    n = face.normalAt(u, v)
    return n


def _on(edge, face):
    pts = edge.discretize(7)
    return all(face.distToShape(Part.Vertex(p))[0] < TOL for p in pts)


def weld_edges(froms, tos):
    """[(edge, from face, to face)]: edges of one set lying on a face of the other."""
    out = []
    for f in froms:
        for e in f.Edges:
            t = next((g for g in tos if _on(e, g)), None)
            if t is not None:
                out.append((e, f, t))
    for g in tos:
        for e in g.Edges:
            if any(e.isSame(x[0]) or _same(e, x[0]) for x in out):
                continue
            f = next((h for h in froms if _on(e, h)), None)
            if f is not None:
                out.append((e, f, g))
    return out


def _near_welds(froms, tos, gap):
    """[(edge, from face, to face)]: straight edges of the from faces running along a to face, at most gap
    away from it and parallel to its plane."""
    out = []
    for f in froms:
        for e in f.Edges:
            if e.Curve.TypeId != "Part::GeomLine" or e.Length < TOL:
                continue
            best = None
            for g in tos:
                if g.Surface.TypeId != "Part::GeomPlane":
                    continue
                n = g.normalAt(0, 0)
                if abs(e.tangentAt(e.FirstParameter).dot(n)) > 1e-6 or abs(_normal(f, e.CenterOfMass).dot(n)) > 1e-6:
                    continue        # the edge must run along the to face, and the from face stand square to it
                d = max(abs((v.Point - g.CenterOfMass).dot(n)) for v in e.Vertexes)
                if d <= gap and (best is None or d < best[0]):
                    best = (d, g)
            if best is not None:
                out.append((e, f, best[1]))
    if out:
        low = min(abs((x[0].Vertexes[0].Point - x[2].CenterOfMass).dot(x[2].normalAt(0, 0))) for x in out)
        out = [x for x in out if abs((x[0].Vertexes[0].Point - x[2].CenterOfMass).dot(x[2].normalAt(0, 0))) <= low + TOL]
    return out


def _same(a, b):
    return abs(a.Length - b.Length) < TOL and a.CenterOfMass.distanceToPoint(b.CenterOfMass) < TOL


def _pieces(edge, kind, length, pitch, start=0.0, backwards=False):
    if kind not in ("Intermittent", "Staggered") or length <= TOL or pitch <= TOL:
        return [edge]
    out, s = [], start
    total = edge.Length
    while s < total - TOL:
        e = min(s + length, total)
        a, b = (total - e, total - s) if backwards else (s, e)
        p0, p1 = edge.getParameterByLength(a), edge.getParameterByLength(b)
        out.append(Part.Edge(edge.Curve, p0, p1) if edge.Curve.TypeId != "Part::GeomLine"
                   else Part.LineSegment(edge.valueAt(p0), edge.valueAt(p1)).toShape())
        s += pitch
    return out


def bead(edge, f, g, size):
    """A fillet weld of leg `size` along edge, in the corner between faces f and g."""
    p = edge.valueAt(edge.FirstParameter)
    t = edge.tangentAt(edge.FirstParameter)
    n1, n2 = _normal(f, p), _normal(g, p)
    v1 = n1.cross(t)
    if v1.dot(n2) < 0:
        v1 = -v1
    v2 = n2.cross(t)
    if v2.dot(n1) < 0:
        v2 = -v2
    if v1.Length < 1e-9 or v2.Length < 1e-9:
        return None
    v1.normalize()
    v2.normalize()
    tri = Part.makePolygon([p, p + v1 * size, p + v2 * size, p])
    return _along(edge, tri, p)


def groove_bead(edge, f, g, size):
    """A groove weld along edge: the open wedge between face f (the prepared edge) and face g's plane, out to
    the far side of f; a fillet of `size` where the faces make no open groove."""
    p = edge.valueAt(edge.FirstParameter)
    t = edge.tangentAt(edge.FirstParameter)
    n1, n2 = _normal(f, p), _normal(g, p)
    v1 = n1.cross(t)
    if v1.dot(n2) < 0:
        v1 = -v1
    if v1.Length < 1e-9:
        return bead(edge, f, g, size)
    v1.normalize()
    reach = max([(v.Point - p).dot(v1) for v in f.Vertexes] + [0.0])
    q = p + v1 * reach
    r = q - n2 * (q - p).dot(n2)
    if reach < TOL or (q - r).Length < TOL or (r - q).dot(n1) <= TOL:
        return bead(edge, f, g, size)
    return _along(edge, Part.makePolygon([p, q, r, p]), p)


def _along(edge, tri, p):
    if edge.Curve.TypeId == "Part::GeomLine":
        return Part.Face(tri).extrude(edge.valueAt(edge.LastParameter) - p)
    sweep = Part.BRepOffsetAPI.MakePipeShell(Part.Wire(edge))
    sweep.setFrenetMode(True)
    sweep.add(tri)
    sweep.build()
    sweep.makeSolid()
    return sweep.shape()


def _other_side(welds, shapes, tos):
    """Other Side: where the face opposite each welded from-face (on the same body) meets the to-faces."""
    out = []
    for e0, f, _g in welds:
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        n = f.normalAt(0, 0)
        shape = next((s for s in shapes if any(f.isSame(x) for x in s.Faces)), None)
        if shape is None:
            continue
        opposite = [h for h in shape.Faces
                    if h.Surface.TypeId == "Part::GeomPlane" and h.normalAt(0, 0).dot(n) < -1 + 1e-6]
        if not opposite:
            continue
        # the outer wall across the body (a tube's inner wall faces the same way)
        far = min((h.CenterOfMass - f.CenterOfMass).dot(n) for h in opposite)
        for h in opposite:
            if (h.CenterOfMass - f.CenterOfMass).dot(n) > far + TOL * 100:
                continue
            for e in h.Edges:
                g = next((t for t in tos if _on(e, t)), None)
                if g is None or any(_same(e, x[0]) for x in welds + out):
                    continue
                t0, t = e0.tangentAt(e0.FirstParameter), e.tangentAt(e.FirstParameter)
                out.append((e, h, g, t.dot(t0) < 0))      # runs the other way: measured from its far end
    return out


def path_shapes(doc, path, sources):
    froms, tos, shapes = [], [], []
    if path.get("mode") == "Weld Path":
        welds = edge_welds(doc, path, sources)
        tos = [g for _e, _f, g in welds]
        for item in path.get("edges", []):
            body, _edge = resolve_edge(doc, item, sources)
            if body is not None:
                shapes.append(body.Shape)
    else:
        picked = {"from": [], "to": []}
        for key, out in (("from", froms), ("to", tos)):
            for item in path[key]:
                shape, face = resolve(doc, item, sources)
                if face is None:
                    continue
                picked[key].append(face)
                if key == "from":
                    shapes.append(shape)
                for x in (_tangent_chain(shape, face) if path.get("tangent", True) else [face]):
                    if not any(x.isSame(y) for y in out):
                        out.append(x)
        welds = weld_edges(froms, tos)
        if not any(any(f.isSame(p) for p in picked["from"]) for _e, f, _g in welds):
            # None of the welds runs along a picked Weld From face: Tangent propagation carried the

            # runs along the picked face's edge that meets the Weld To face across a gap smaller
            # than the bead (a member end under a tube's rounded corner).
            near = _near_welds(picked["from"], picked["to"], float(path.get("size", 3.0)))
            if near:
                welds = near
    kind, length, pitch = path.get("type"), float(path.get("length", 0)), float(path.get("pitch", 0))
    if kind == "Staggered" and not path.get("other"):
        kind = "Intermittent"
    sides = [(welds, float(path.get("size", 3.0)), 0.0)]
    if path.get("other"):
        sides.append((_other_side(welds, shapes, tos), float(path.get("other_size", path.get("size", 3.0))),
                      pitch / 2 if kind == "Staggered" else 0.0))
    beads = []
    for edges, size, start in sides:
        for edge, f, g, *back in edges:
            for piece in _pieces(edge, kind, length, pitch, start, bool(back and back[0])):
                b = (groove_bead if path.get("bead") == "Groove Bead" else bead)(piece, f, g, size)
                if b is not None and not b.isNull():
                    beads.append(b)
    return beads


# ---------------------------------------------------------------- the feature
def _symbol_prop(obj):
    if "SymbolText" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "SymbolText", GROUP, "The weld symbol, as shown in the 3D view")
        obj.setEditorMode("SymbolText", 1)
    if "SymbolAt" not in obj.PropertiesList:
        obj.addProperty("App::PropertyVectorList", "SymbolAt", GROUP, "Where each weld path's symbol points")
        obj.setEditorMode("SymbolAt", 2)


SYMBOL_COLOR = (0.1, 0.2, 0.75)
SYMBOL_FONT = "Century Gothic"
_H = 14.0          # weld symbol height, pixels


def _symbol_lines(kind, x0, d):
    """(polylines, width) of one weld symbol on the reference line (y 0), starting at x0, on the side d
    (-1 arrow side, below the line; +1 other side, above it). Units are pixels."""
    import math
    h = _H

    def arc(cx, cy, r, a0, a1, n=10):
        return [(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + d * r * math.sin(a0 + (a1 - a0) * i / n))
                for i in range(n + 1)]
    if kind == "Fillet":
        return [[(x0, 0), (x0, d * h), (x0 + h, 0)]], h
    if kind == "Square Groove":
        return [[(x0, 0), (x0, d * h)], [(x0 + 5, 0), (x0 + 5, d * h)]], 5
    if kind == "V Groove":
        return [[(x0, d * h), (x0 + h / 2, 0), (x0 + h, d * h)]], h
    if kind == "Bevel Groove":
        return [[(x0, d * h), (x0, 0), (x0 + 0.8 * h, d * h)]], 0.8 * h
    if kind == "U Groove":
        r = h / 2
        return [[(x0 + r, 0), (x0 + r, d * 0.3 * h)], arc(x0 + r, 0.3 * h * d + d * r, r, math.pi, 2 * math.pi)], h
    if kind == "J Groove":
        r = 0.6 * h
        return [[(x0, 0), (x0, d * h)], [(x0, 0), (x0, d * 0.3 * h)] + arc(x0, 0.3 * h * d + d * r, r, 1.5 * math.pi, 2 * math.pi)], r
    if kind == "Flare-V":
        r = h / 2
        return [arc(x0, 0, r, 0, 0.5 * math.pi), arc(x0 + 2 * r + 3, 0, r, math.pi, 0.5 * math.pi)], 2 * r + 3
    if kind == "Flare-Bevel":
        r = h / 2
        return [[(x0, 0), (x0, d * h)], arc(x0 + r + 3, 0, r, math.pi, 0.5 * math.pi)], r + 3
    if kind in ("Plug", "Edge"):
        return [[(x0, 0), (x0, d * 0.6 * h), (x0 + h, d * 0.6 * h), (x0 + h, 0)]], h
    if kind in ("Spot", "Seam"):
        pts = arc(x0 + h / 2, 0, h / 2, 0, 2 * math.pi, 16)
        out = [pts]
        if kind == "Seam":
            out += [[(x0 - 2, d * 2), (x0 + h + 2, d * 2)], [(x0 - 2, -d * 2), (x0 + h + 2, -d * 2)]]
        return out, h
    return [], 0


def _contour(kind, x0, w, d):
    import math
    y = d * (_H + 3)
    if kind == "Flush":
        return [[(x0, y), (x0 + w, y)]]
    if kind in ("Convex", "Concave"):
        b = 3 if kind == "Convex" else -3
        return [[(x0 + w * i / 10.0, y + d * b * math.sin(math.pi * i / 10.0)) for i in range(11)]]
    return []


def _draw_symbol(sep, sym):
    ""

    import math
    from pivy import coin
    kx, ky = 40.0, 40.0                     # the bend where the arrow meets the reference line

    def on_line(pl):
        return [(px, py + ky) for px, py in pl]
    lines = [[(0.0, 0.0), (kx, ky)]]        # the arrow
    fills = [[(0.0, 0.0), (9.0, 3.4), (3.4, 9.0)]]       # its head, on the bead
    texts = []                              # (x, y, text, right-justified), y from the reference line
    x = kx + 32
    end = x
    for key, d in (("arrow", -1), ("other", 1)):
        side = sym.get(key) or {}
        kind = side.get("symbol", "None")
        if kind == "None":
            continue
        x0 = x + (_H + 4 if key == "other" and sym.get("stagger") else 0)
        pl, w = _symbol_lines(kind, x0, d)
        base = -_H if d < 0 else 3
        if not pl:
            texts.append((x0, base, kind.upper(), False))
            w = 8 * len(kind)
        lines += [on_line(q) for q in pl + _contour(side.get("contour", "None"), x0, w, d)]
        if side.get("size"):
            texts.append((x0 - 5, base, side["size"], True))
        if side.get("lp"):
            texts.append((x0 + w + 3, base, side["lp"], False))
        end = max(end, x0 + w + (7 * len(side["lp"]) + 6 if side.get("lp") else 0))
    end += 24
    lines.append([(kx, ky), (end, ky)])     # the reference line
    if sym.get("around"):
        lines.append([(kx + 5 * math.cos(2 * math.pi * i / 16), ky + 5 * math.sin(2 * math.pi * i / 16))
                      for i in range(17)])
    if sym.get("field"):
        lines.append([(kx, ky), (kx, ky + 16)])
        fills.append([(kx, ky + 16), (kx + 9, ky + 13), (kx, ky + 10)])
    if sym.get("process"):
        lines += [[(end, ky), (end + 8, ky + 8)], [(end, ky), (end + 8, ky - 8)]]
        texts.append((end + 11, -4, sym["process"], False))
    pts = [(px, py, 0.0) for pl in lines for px, py in pl]
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(pts), pts)
    ls = coin.SoLineSet()
    ls.numVertices.setValues(0, len(lines), [len(pl) for pl in lines])
    fpts = [(px, py, 0.0) for f in fills for px, py in f]
    fc = coin.SoCoordinate3()
    fc.point.setValues(0, len(fpts), fpts)
    fs = coin.SoFaceSet()
    fs.numVertices.setValues(0, len(fills), [len(f) for f in fills])
    font = coin.SoFont()
    font.name = SYMBOL_FONT
    font.size = 12
    for n in (coords, ls, fc, fs, font):
        sep.addChild(n)
    for tx, ty, s, right in texts:
        ts = coin.SoSeparator()
        tr = coin.SoTranslation()
        tr.translation = (tx, ty + ky, 0)
        t2 = coin.SoText2()
        t2.string = s
        if right:
            t2.justification = coin.SoText2.RIGHT
        ts.addChild(tr)
        ts.addChild(t2)
        sep.addChild(ts)
    return {"lines": lines, "texts": texts, "fills": fills}


class WeldBead:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "Paths", GROUP, "Weld paths (JSON)")
        add("App::PropertyLinkList", "Sources", GROUP, "The shapes the welded faces are on")
        add("App::PropertyLinkList", "Created", GROUP, "Objects made by this feature")
        add("App::PropertyString", "Outputs", GROUP, "Unused: a weld bead changes no member")
        add("App::PropertyFloat", "TotalLength", GROUP, "Length of all the beads")
        _symbol_prop(obj)
        for name in ("Paths", "Sources", "Created", "Outputs"):
            obj.setEditorMode(name, 2)
        obj.setEditorMode("TotalLength", 1)
        obj.Paths = json.dumps([new_path()])
        obj.Outputs = "{}"
        obj.Proxy = self

    def execute(self, obj):
        beads = []
        texts = []
        at = []
        for path in _load(obj.Paths, []):
            made = path_shapes(obj.Document, path, list(obj.Sources))
            solids = [s for b in made for s in b.Solids]
            at.append(solids[0].BoundBox.Center if solids else App.Vector())
            beads += made
            texts.append(symbol_text(path))
        _symbol_prop(obj)
        if list(obj.SymbolAt) != at:
            obj.SymbolAt = at
        if obj.SymbolText != "\n".join(texts):
            obj.SymbolText = "\n".join(texts)
        obj.TotalLength = sum(_bead_length(b) for b in beads)
        obj.Shape = Part.makeCompound(beads) if beads else Part.Shape()

    def dumps(self):
        return None

    def loads(self, state):
        return None


def symbol_of(path):
    """The path's weld symbol, from Define Weld Symbol or else from its settings (a fillet of the bead size)."""
    inter = path.get("type") in ("Intermittent", "Staggered")
    lp = "%g-%g" % (path.get("length", 10.0), path.get("pitch", 20.0)) if inter else ""
    kind = GROOVE_SYMBOL.get(path.get("groove"), "Bevel Groove") if path.get("bead") == "Groove Bead" else "Fillet"
    sym = {"arrow": {"symbol": kind, "size": "%g" % path.get("size", 3.0), "lp": lp, "contour": "None"},
           "other": {"symbol": kind if path.get("other") else "None",
                     "size": "%g" % path.get("other_size", path.get("size", 3.0)) if path.get("other") else "",
                     "lp": lp if path.get("other") else "", "contour": "None"},
           "field": False, "around": False, "stagger": path.get("type") == "Staggered", "process": ""}
    stored = path.get("symbol") or {}
    for k, v in stored.items():
        if isinstance(v, dict):
            sym[k].update(v)
        else:
            sym[k] = v
    return sym


def symbol_text(path):
    """One line for the 3D view: arrow side / other side, as SIZE SYMBOL L-P (CONTOUR), and the flags."""
    sym = symbol_of(path)
    sides = []
    for key, name in (("arrow", ""), ("other", "OTHER SIDE ")):
        side = sym[key]
        if side.get("symbol", "None") == "None":
            continue
        words = [side.get("size", ""), side["symbol"].upper(), side.get("lp", "")]
        if side.get("contour", "None") != "None":
            words.append("(%s)" % side["contour"].upper())
        sides.append(name + " ".join(w for w in words if w))
    flags = [f for f, on in (("STAGGERED", sym.get("stagger")), ("ALL AROUND", sym.get("around")),
                             ("FIELD WELD", sym.get("field"))) if on]
    if sym.get("process"):
        flags.append(sym["process"])
    return " / ".join(sides + flags)


def _bead_length(b):
    """A bead's length: its volume over its cross-section (a triangle)."""
    try:
        f = min(b.Faces, key=lambda x: x.Area if len(x.Edges) == 3 else 1e99)
        return b.Volume / f.Area
    except Exception as _fw_err:
        _fw_log("weweld.py:503", _fw_err)
        return 0.0


def build(obj):
    """Links the beads to the members' current shapes, so they rebuild after them."""
    doc = obj.Document
    sources = []
    for path in _load(obj.Paths, []):
        for item in path["from"] + path["to"] + path.get("edges", []):
            if item.get("kind") == "body":
                o = wetrim.current_tip(doc, item["ref"], obj)
            else:
                o = doc.getObject(item.get("obj", ""))
            if o is not None and o not in sources:
                sources.append(o)
        if path.get("mode") == "Weld Path":
            # the members a picked edge may be welded to rebuild before the bead too
            from . import wemember
            for sm in wemember.structural_members(doc):
                for k in range(len(sm.Bodies)):
                    o = wetrim.current_tip(doc, "%s:%d" % (sm.Name, k), obj)
                    if o is not None and o not in sources:
                        sources.append(o)
    obj.Sources = sources
    obj.touch()


class ViewProviderWeldBead:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        self.label = None
        self.sensor = None
        self.camera = None
        try:
            from pivy import coin
            self.label = coin.SoSwitch()       # on top of the model, shown and hidden with the bead
            self.label.whichChild = 0 if vobj.Visibility else -1
            self.symbols = coin.SoAnnotation()
            self.label.addChild(self.symbols)
            vobj.RootNode.addChild(self.label)
            self._show_symbol(vobj.Object)
        except Exception:
            self.label = None

    def updateData(self, obj, prop):
        if prop in ("Shape", "SymbolText", "Paths"):
            self._show_symbol(obj)

    def onChanged(self, vobj, prop):
        if prop == "Visibility" and getattr(self, "label", None) is not None:
            self.label.whichChild = 0 if vobj.Visibility else -1

    def _show_symbol(self, obj):
        ""



        if getattr(self, "label", None) is None:
            return
        from pivy import coin
        self.symbols.removeAllChildren()
        self.frames = []
        shape = obj.Shape
        if shape.isNull() or not shape.Solids:
            return
        paths = _load(getattr(obj, "Paths", "[]"), [])
        at = list(getattr(obj, "SymbolAt", []) or [])
        for k, path in enumerate(paths):
            if k < len(at):
                point = at[k]
            elif k == 0:
                point = shape.Solids[0].BoundBox.Center
            else:
                continue
            if not symbol_text(path):
                continue
            sep = coin.SoSeparator()
            move = coin.SoTranslation()
            move.translation = tuple(point)
            turn = coin.SoTransform()
            color = coin.SoBaseColor()
            color.rgb = SYMBOL_COLOR
            style = coin.SoDrawStyle()
            style.lineWidth = 1.5
            light = coin.SoLightModel()
            light.model = coin.SoLightModel.BASE_COLOR
            for n in (move, turn, light, color, style):
                sep.addChild(n)
            _draw_symbol(sep, symbol_of(path))
            self.symbols.addChild(sep)
            self.frames.append((turn, App.Vector(point)))
        self._follow_camera()

    def _follow_camera(self, *_args):
        """Turn the symbols to face the screen and scale them to pixels; runs on every camera change."""
        try:
            from pivy import coin
            view = Gui.getDocument(self.Object.Document.Name).activeView()
            cam = view.getCameraNode()
            if cam is not self.camera:
                if self.sensor is not None:
                    self.sensor.detach()
                self.sensor = coin.SoNodeSensor(self._follow_camera, None)
                self.sensor.attach(cam)
                self.camera = cam
            h = max(view.getSize()[1], 1)
            rot = cam.orientation.getValue()
            look = rot.multVec(coin.SbVec3f(0, 0, -1))
            pos = App.Vector(*cam.position.getValue().getValue())
            look = App.Vector(*look.getValue())
            for turn, point in getattr(self, "frames", []):
                if cam.isOfType(coin.SoPerspectiveCamera.getClassTypeId()):
                    import math
                    dist = max((point - pos).dot(look), 1e-6)
                    s = 2.0 * dist * math.tan(cam.heightAngle.getValue() / 2.0) / h
                else:
                    s = cam.height.getValue() / h
                turn.rotation = rot
                turn.scaleFactor = (s, s, s)
        except Exception:
            pass

    def getIcon(self):
        try:
            return _weicon("joincurve.svg")
        except Exception:
            return ""

    def claimChildren(self):
        return []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + TITLE)
        try:
            Gui.Control.showDialog(Panel(obj, False))
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

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(doc):
    obj = doc.addObject("Part::FeaturePython", "WeldBead")
    WeldBead(obj)
    if App.GuiUp:
        ViewProviderWeldBead(obj.ViewObject)
        obj.ViewObject.ShapeColor = (0.45, 0.45, 0.48)
    obj.Label = naming.next_label(doc, LABEL)
    return obj


# ---------------------------------------------------------------- PropertyManager
def _box(title):
    box = QtWidgets.QWidget()
    box.setWindowTitle(title)
    QtWidgets.QFormLayout(box)
    return box


def _spin(name, value, lo=0.0, hi=10000.0):
    w = QtWidgets.QDoubleSpinBox()
    w.setObjectName(name)
    w.setRange(lo, hi)
    w.setDecimals(2)
    w.setSuffix(" mm")
    w.setValue(value)
    w.setKeyboardTracking(False)     # the bead updates on Enter / Tab: "0.5in" is read whole, not "0.5" mid-typing
    return w


class _Keys(QtCore.QObject):
    def __init__(self, panel, which):
        super().__init__()
        self.panel, self.which = panel, which

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.FocusIn:
            self.panel.set_active(self.which)
        elif event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Delete:
            self.panel.remove_current(self.which)
            return True
        return False


class Panel:
    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        self.busy = True
        self.paths = _load(obj.Paths, []) or [new_path()]
        self.current = 0
        self.active = "from"
        self._filters = []

        paths = _box("Weld Path")
        f = paths.layout()
        self.path_list = QtWidgets.QListWidget()
        self.path_list.setObjectName("SWWEWeldPaths")
        self.path_list.setMaximumHeight(60)
        f.addRow(self.path_list)
        self.new_path = QtWidgets.QPushButton("New Weld Path")
        self.new_path.setObjectName("SWWEWeldNewPath")
        f.addRow(self.new_path)
        self.smart = QtWidgets.QPushButton("Smart Weld Selection Tool")
        self.smart.setObjectName("SWWEWeldSmart")
        self.smart.setCheckable(True)
        self.smart.setToolTip("Drag across the faces to weld: the first body's faces go in Weld From, the "
                              "others' in Weld To")
        self.smart_cbs = None
        self.stroke = None
        f.addRow(self.smart)

        settings = _box("Settings")
        f = settings.layout()
        row = QtWidgets.QHBoxLayout()
        self.geometry = QtWidgets.QRadioButton("Weld Geometry")
        self.geometry.setObjectName("SWWEWeldGeometry")
        self.geometry.setChecked(True)
        self.by_path = QtWidgets.QRadioButton("Weld Path")
        self.by_path.setObjectName("SWWEWeldByPath")
        self.by_path.setToolTip("Weld along picked edges")
        self.geometry.setToolTip("Weld where the Weld From faces meet the Weld To faces")
        row.addWidget(self.geometry)
        row.addWidget(self.by_path)
        # look-audit smwe-1120: its own exclusive pair (the bead type radios share this box's parent)
        self._mode_group = QtWidgets.QButtonGroup(settings)
        self._mode_group.addButton(self.geometry)
        self._mode_group.addButton(self.by_path)
        row.addStretch(1)
        f.addRow(row)
        self.edges_label = QtWidgets.QLabel("Weld Path:")
        f.addRow(self.edges_label)
        self.edge_list = QtWidgets.QListWidget()
        self.edge_list.setObjectName("SWWEWeldEdges")
        self.edge_list.setMaximumHeight(70)
        self.edge_list.setToolTip("The edges to weld along")
        f.addRow(self.edge_list)
        self.from_label = QtWidgets.QLabel("Weld From:")
        f.addRow(self.from_label)
        self.from_list = QtWidgets.QListWidget()
        self.from_list.setObjectName("SWWEWeldFrom")
        self.from_list.setMaximumHeight(52)
        f.addRow(self.from_list)
        self.to_label = QtWidgets.QLabel("Weld To:")
        f.addRow(self.to_label)
        self.to_list = QtWidgets.QListWidget()
        self.to_list.setObjectName("SWWEWeldTo")
        self.to_list.setMaximumHeight(52)
        f.addRow(self.to_list)
        row = QtWidgets.QHBoxLayout()
        self.beads = {}
        self._bead_group = QtWidgets.QButtonGroup(settings)      # look-audit smwe-1120: apart from Weld Geometry/Path
        for name in BEADS:
            b = QtWidgets.QRadioButton(name)
            b.setObjectName("SWWEWeld" + name.replace(" ", ""))
            self._bead_group.addButton(b)
            self.beads[name] = b
            row.addWidget(b)
        row.addStretch(1)
        f.addRow(row)
        self.groove = QtWidgets.QComboBox()
        self.groove.setObjectName("SWWEWeldGroove")
        self.groove.addItems(list(GROOVES))
        self.groove.setToolTip("Groove type")
        self.groove_label = QtWidgets.QLabel("Groove type")
        f.addRow(self.groove_label, self.groove)
        self.size = _spin("SWWEWeldSize", 3.0, 0.01)
        f.addRow("Bead size", self.size)
        self.tangent = QtWidgets.QCheckBox("Tangent propagation")
        self.tangent.setObjectName("SWWEWeldTangent")
        f.addRow(self.tangent)
        self.kinds = QtWidgets.QComboBox()
        self.kinds.setObjectName("SWWEWeldType")
        self.kinds.addItems(list(TYPES))
        self.kinds.setItemData(2, "Intermittent beads on both sides, the other side's half a pitch on (needs Other Side)",
                               QtCore.Qt.ToolTipRole)
        f.addRow(self.kinds)
        self.length = _spin("SWWEWeldLength", 10.0, 0.01)
        self.length_label = QtWidgets.QLabel("Weld length")
        f.addRow(self.length_label, self.length)
        self.pitch = _spin("SWWEWeldPitch", 20.0, 0.01)
        self.pitch_label = QtWidgets.QLabel("Pitch")
        f.addRow(self.pitch_label, self.pitch)
        self.symbol = QtWidgets.QPushButton("Define Weld Symbol...")
        self.symbol.setObjectName("SWWEWeldSymbol")
        self.symbol.setToolTip("Sets the weld symbol shown with the bead")
        f.addRow(self.symbol)
        self.other = QtWidgets.QCheckBox("Other Side")
        self.other.setObjectName("SWWEWeldOther")
        self.other.setToolTip("Also welds the far side of the joint")
        f.addRow(self.other)
        self.other_size = _spin("SWWEWeldOtherSize", 3.0, 0.01)
        self.other_size_label = QtWidgets.QLabel("Bead size")
        f.addRow(self.other_size_label, self.other_size)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("SWWEWeldError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        from . import pickprompt
        pickprompt.style(self.error)     # look audit AI1: the start prompt in the yellow box
        f.addRow(self.error)

        for w in (paths, settings):
            w.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        paths.setProperty("swstyle_pm_title", TITLE)
        paths.setProperty("swstyle_pm_icon", "SWStyle_WEWeldBead")
        self.form = [paths, settings]
        for which, w in (("from", self.from_list), ("to", self.to_list), ("edges", self.edge_list)):
            k = _Keys(self, which)
            self._filters.append(k)
            w.installEventFilter(k)
        self._show()

        self.new_path.clicked.connect(self._add_path)
        pmboxes.bind(self.path_list, remove=self._drop_path)
        self.smart.toggled.connect(self._smart)
        self.symbol.clicked.connect(self.define_symbol)
        self.path_list.currentRowChanged.connect(self._path_picked)
        self.kinds.currentIndexChanged.connect(self._changed)
        self.groove.currentIndexChanged.connect(self._changed)
        self.beads["Groove Bead"].toggled.connect(self._changed)
        for w in (self.size, self.length, self.pitch, self.other_size):
            w.valueChanged.connect(self._changed)
        for w in (self.tangent, self.other, self.by_path):
            w.toggled.connect(self._changed)
        self.busy = False
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ---------------------------------------------------------------- state
    def set_active(self, which):
        self.active = which
        for name, w in (("from", self.from_list), ("to", self.to_list), ("edges", self.edge_list)):
            pmboxes.mark(w, name == which)

    def _label(self, k, item):
        doc = self.obj.Document
        if item.get("kind") == "body":
            tip = wetrim.current_tip(doc, item["ref"])
            label = tip.Label if tip is not None else item["ref"]
        else:
            o = doc.getObject(item.get("obj", ""))
            label = o.Label if o is not None else item.get("obj", "")
        return "%s<%d>@%s" % ("Edge" if item.get("edge") or item.get("kind") == "edge" else "Face", k, label)

    def _show(self):
        busy, self.busy = self.busy, True
        self.path_list.clear()
        for i in range(len(self.paths)):
            self.path_list.addItem("Weld Path%d" % (i + 1))
        self.path_list.setCurrentRow(self.current)
        p = self.paths[self.current]
        by_path = p.get("mode") == "Weld Path"
        (self.by_path if by_path else self.geometry).setChecked(True)
        for w in (self.edges_label, self.edge_list):
            w.setVisible(by_path)
        for w in (self.from_label, self.from_list, self.to_label, self.to_list):
            w.setVisible(not by_path)
        if by_path and self.active != "edges":
            self.active = "edges"
        elif not by_path and self.active == "edges":
            self.active = "from"
        k = 0
        for lst, key in ((self.from_list, "from"), (self.to_list, "to"), (self.edge_list, "edges")):
            lst.clear()
            for item in p.get(key, []):
                k += 1
                lst.addItem(self._label(k, item))
        groove = p.get("bead") == "Groove Bead"
        self.beads["Groove Bead" if groove else "Fillet Bead"].setChecked(True)
        self.groove.setCurrentText(p.get("groove", "Bevel"))
        for w in (self.groove, self.groove_label):
            w.setVisible(groove)
        self.size.setValue(float(p.get("size", 3.0)))
        self.tangent.setChecked(bool(p.get("tangent", True)))
        other = bool(p.get("other"))
        self.other.setChecked(other)
        self.other_size.setValue(float(p.get("other_size", p.get("size", 3.0))))
        for w in (self.other_size, self.other_size_label):
            w.setVisible(other)
        self.kinds.model().item(2).setEnabled(other)
        self.kinds.setCurrentText(p.get("type", "Full length"))
        inter = p.get("type") in ("Intermittent", "Staggered")
        for w in (self.length, self.length_label, self.pitch, self.pitch_label):
            w.setVisible(inter)
        self.length.setValue(float(p.get("length", 10.0)))
        self.pitch.setValue(float(p.get("pitch", 20.0)))
        self.set_active(self.active)
        if not _ready(p):
            self.error.setText(PATH_HINT if by_path else HINT)
            self.error.setVisible(True)
        self.busy = busy

    def _add_path(self):
        self.paths.append(new_path())
        self.current = len(self.paths) - 1
        self.active = "from"
        self._show()

    def _drop_path(self, row):
        ""
        if len(self.paths) < 2 or not 0 <= row < len(self.paths):
            return
        del self.paths[row]
        self.current = min(self.current if self.current < row else max(0, self.current - 1), len(self.paths) - 1)
        self._show()
        self._changed()

    def _path_picked(self, row):
        if self.busy or row < 0:
            return
        self.current = row
        self._show()

    def _changed(self, *args):
        if self.busy:
            return
        p = self.paths[self.current]
        p["size"] = self.size.value()
        p["bead"] = "Groove Bead" if self.beads["Groove Bead"].isChecked() else "Fillet Bead"
        p["groove"] = self.groove.currentText()
        p["tangent"] = self.tangent.isChecked()
        p["other"] = self.other.isChecked()
        p["other_size"] = self.other_size.value()
        p["type"] = self.kinds.currentText()
        if p["type"] == "Staggered" and not p["other"]:
            p["type"] = "Intermittent"          # Staggered needs both sides
        p["mode"] = "Weld Path" if self.by_path.isChecked() else "Weld Geometry"
        p["length"] = self.length.value()
        p["pitch"] = self.pitch.value()
        obj = self.obj
        obj.Paths = json.dumps(self.paths)
        self.error.hide()
        self._show()
        try:
            build(obj)
            obj.Document.recompute()
            if "Invalid" in obj.State:
                raise RuntimeError(obj.getStatusString())
        except Exception as error:
            self.error.setText(str(error))
            self.error.show()

    # ---------------------------------------------------------------- weld symbol
    def define_symbol(self):
        """Define Weld Symbol: the Weld Symbol dialog for the current path."""
        p = self.paths[self.current]
        dlg = WeldSymbolDialog(symbol_of(p), Gui.getMainWindow())
        self.symbol_dialog = dlg
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            p["symbol"] = dlg.value()
            self._changed()
        self.symbol_dialog = None

    # ---------------------------------------------------------------- Smart Weld Selection Tool
    def _smart(self, on):
        if on:
            self._start_smart()
        else:
            self._stop_smart()

    def _start_smart(self):
        try:
            from pivy import coin
            view = Gui.ActiveDocument.ActiveView
        except Exception:
            return
        if self.paths[self.current].get("mode") == "Weld Path":
            self.by_path.setChecked(False)          # the tool picks faces
            self.geometry.setChecked(True)

        def button(cb):
            ev = cb.getEvent()
            if ev.getButton() != coin.SoMouseButtonEvent.BUTTON1:
                return
            pos = tuple(ev.getPosition().getValue())
            if ev.getState() == coin.SoButtonEvent.DOWN:
                self.stroke = [pos]
                cb.setHandled()
            elif self.stroke is not None:
                points, self.stroke = self.stroke + [pos], None
                cb.setHandled()
                QtCore.QTimer.singleShot(0, lambda: self.smart_stroke(points))

        def motion(cb):
            if self.stroke is not None:
                self.stroke.append(tuple(cb.getEvent().getPosition().getValue()))
                cb.setHandled()

        self.smart_cbs = (view, button, motion,
                          view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), button),
                          view.addEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), motion))

    def _stop_smart(self):
        if self.smart_cbs is None:
            return
        try:
            from pivy import coin
            view = self.smart_cbs[0]
            view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.smart_cbs[3])
            view.removeEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), self.smart_cbs[4])
        except Exception as _fw_err:
            _fw_log("weweld.py:965", _fw_err)
        self.smart_cbs = None
        self.stroke = None

    def smart_stroke(self, points):
        """The faces a stroke (3D-view pixels, as mouse events give them) crosses: the first body's go in
        Weld From, the other bodies' in Weld To."""
        try:
            view = Gui.ActiveDocument.ActiveView
        except Exception:
            return
        doc = self.obj.Document
        samples = []
        for (x0, y0), (x1, y1) in zip(points, points[1:] or points):
            n = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) / 3))
            samples += [(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1)]
        hits = []
        for x, y in samples:
            try:
                info = view.getObjectInfo((int(round(x)), int(round(y))))
            except Exception:
                info = None
            if not info or not str(info.get("Component", "")).startswith("Face"):
                continue
            o = doc.getObject(info.get("Object", ""))
            if o is None or o is self.obj or is_weld_bead(o):
                continue
            if (o.Name, info["Component"]) not in hits:
                hits.append((o.Name, info["Component"]))
        bodies = list(dict.fromkeys(name for name, _sub in hits))
        if len(bodies) < 2:
            self.error.setText("Drag across the faces of two bodies.")
            self.error.show()
            return
        p = self.paths[self.current]
        p["mode"] = "Weld Geometry"
        for name, sub in hits:
            item = face_ref(doc.getObject(name), sub)
            if item is None or item in p["from"] or item in p["to"]:
                continue
            p["from" if name == bodies[0] else "to"].append(item)
        self._show()
        self._changed()

    # ---------------------------------------------------------------- selection
    def addSelection(self, doc, name, sub, point):
        if sub.startswith("Edge" if self.paths[self.current].get("mode") == "Weld Path" else "Face"):
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub))

    def _picked(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("weweld.py:1018", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or picked is self.obj:
            return
        p = self.paths[self.current]
        if p.get("mode") == "Weld Path":
            item = edge_ref(picked, sub)
            if item is None or item in p.setdefault("edges", []):
                return
            p["edges"].append(item)
            self._changed()
            return
        item = face_ref(picked, sub)
        if item is None:
            return
        if item in p["from"] or item in p["to"]:
            return
        p[self.active].append(item)
        if self.active == "from" and not p["to"]:
            self.active = "to"
        self._changed()

    def remove_current(self, which):
        lst = {"from": self.from_list, "to": self.to_list, "edges": self.edge_list}[which]
        row = lst.currentRow()
        if row < 0:
            return
        del self.paths[self.current][which][row]
        self._changed()

    # ---------------------------------------------------------------- closing
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        self._stop_smart()
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("weweld.py:1057", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("weweld.py:1063", _fw_err)

    def accept(self):
        if not any(_ready(p) for p in self.paths) or "Invalid" in self.obj.State:
            self.error.setText(self.error.text() or HINT)
            self.error.show()
            return False
        self.paths = [p for p in self.paths if _ready(p)]
        self.obj.Paths = json.dumps(self.paths)
        self.obj.Document.recompute()
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        doc.recompute()
        self._close()
        return True


class WeldSymbolDialog(QtWidgets.QDialog):
    ""


    def __init__(self, sym, parent=None):
        super().__init__(parent)
        self.setObjectName("SWWEWeldSymbolDialog")
        self.setWindowTitle("Weld Symbol")
        lay = QtWidgets.QVBoxLayout(self)
        self.sides = {}
        for key, title in (("other", "Other Side"), ("arrow", "Arrow Side")):
            box = QtWidgets.QGroupBox(title)
            f = QtWidgets.QFormLayout(box)
            side = sym[key]
            w = {"symbol": QtWidgets.QComboBox(), "size": QtWidgets.QLineEdit(side.get("size", "")),
                 "lp": QtWidgets.QLineEdit(side.get("lp", "")), "contour": QtWidgets.QComboBox()}
            w["symbol"].addItems(list(SYMBOLS))
            w["symbol"].setCurrentText(side.get("symbol", "None"))
            w["contour"].addItems(list(CONTOURS))
            w["contour"].setCurrentText(side.get("contour", "None"))
            for name, widget in w.items():
                widget.setObjectName("SWWESym%s%s" % (key.title(), name.title()))
            f.addRow("Weld symbol", w["symbol"])
            f.addRow("Size", w["size"])
            f.addRow("Length-Pitch", w["lp"])
            f.addRow("Contour", w["contour"])
            self.sides[key] = w
            lay.addWidget(box)
        self.field = QtWidgets.QCheckBox("Field/Site")
        self.field.setObjectName("SWWESymField")
        self.field.setChecked(bool(sym.get("field")))
        self.around = QtWidgets.QCheckBox("Weld all around")
        self.around.setObjectName("SWWESymAround")
        self.around.setChecked(bool(sym.get("around")))
        self.stagger = QtWidgets.QCheckBox("Stagger")
        self.stagger.setObjectName("SWWESymStagger")
        self.stagger.setChecked(bool(sym.get("stagger")))
        for w in (self.field, self.around, self.stagger):
            lay.addWidget(w)
        row = QtWidgets.QFormLayout()
        self.process = QtWidgets.QLineEdit(sym.get("process", ""))
        self.process.setObjectName("SWWESymProcess")
        row.addRow("Process", self.process)
        lay.addLayout(row)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.setObjectName("SWWESymButtons")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def value(self):
        out = {k: {"symbol": w["symbol"].currentText(), "size": w["size"].text().strip(),
                   "lp": w["lp"].text().strip(), "contour": w["contour"].currentText()}
               for k, w in self.sides.items()}
        out.update(field=self.field.isChecked(), around=self.around.isChecked(), stagger=self.stagger.isChecked(),
                   process=self.process.text().strip())
        return out


def _ready(p):
    """The path has its picks: edges for a Weld Path, else faces on both sides."""
    return bool(p.get("edges")) if p.get("mode") == "Weld Path" else bool(p["from"] and p["to"])


def start():
    doc = App.ActiveDocument
    if doc is None:
        return
    picked, edges = [], []
    for s in Gui.Selection.getSelectionEx():
        for sub in s.SubElementNames:
            item = face_ref(s.Object, sub) if sub.startswith("Face") else edge_ref(s.Object, sub)
            out = picked if sub.startswith("Face") else edges
            if item is not None and item not in out:
                out.append(item)
    doc.openTransaction(TITLE)
    try:
        obj = make(doc)
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    if edges and not picked:
        panel.paths[0]["mode"] = "Weld Path"
        panel.paths[0]["edges"] = edges
        panel.active = "edges"
        panel._show()
        panel._changed()
    elif picked:
        panel.paths[0]["from"] = picked[:1]
        panel.paths[0]["to"] = picked[1:]
        panel.active = "to"
        panel._changed()


class Command:
    def GetResources(self):
        try:
            pixmap = _weicon("joincurve.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Weld Bead",
                "ToolTip": "Adds a weld bead along a path, with its weld data."}

    def IsActive(self):
        if App.ActiveDocument is None:
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
