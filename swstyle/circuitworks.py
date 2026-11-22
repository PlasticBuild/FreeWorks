# SPDX-License-Identifier: LGPL-2.1-or-later
""












_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import datetime
import json
import math
import os
import shlex

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:      # pragma: no cover
    Gui = None

V = App.Vector
PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/CircuitWorks"
BOARD_COLOUR = (0.05, 0.45, 0.15)
COMPONENT_COLOUR = (0.25, 0.25, 0.27)
META = "FwEcad"              # doc.Meta: json {"file", "kind" (assembly/part), "comps": {refdes: object name}}
BOARD_EXT = (".emn", ".brd", ".bdf", ".idb")
LIB_EXT = (".emp", ".lib", ".ldf")
UNITS = {"MM": 1.0, "THOU": 0.0254, "MIL": 0.0254, "IN": 25.4, "TNM": 1e-5}


# ============================================================================= reading IDF
def _split(line):
    try:
        return shlex.split(line, posix=True)
    except ValueError:
        return line.split()


def _sections(text):
    """[(name, header words, [rows of words])] of an IDF file."""
    out, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(".END_"):
            cur = None
            continue
        if line.startswith("."):
            words = _split(line)
            cur = (words[0][1:].upper(), words[1:], [])
            out.append(cur)
            continue
        if cur is not None:
            cur[2].append(_split(line))
    return out


def _loops(rows, scale):
    """{loop label: [(x, y, angle)]} of an outline section."""
    loops = {}
    for r in rows:
        if len(r) < 4:
            continue
        try:
            loops.setdefault(int(r[0]), []).append((float(r[1]) * scale, float(r[2]) * scale, float(r[3])))
        except ValueError:
            continue
    return loops


def find_library(board):
    folder, name = os.path.split(board)
    stem = os.path.splitext(name)[0].lower()
    for other in sorted(os.listdir(folder or ".")):
        o_stem, o_ext = os.path.splitext(other)
        if o_stem.lower() == stem and o_ext.lower() in LIB_EXT:
            return os.path.join(folder, other)
    return None


def read(board):
    """The board file (and its component file next to it) as a dict:
    {name, units, thickness, outline {loop: points}, holes [(dia, x, y, kind, owner)], components [{refdes, part,
    package, x, y, z, rotation, side, height, outline points}], library path or None}. ValueError when not IDF."""
    with open(board, "r", errors="replace") as f:
        text = f.read()
    secs = _sections(text)
    head = next((s for s in secs if s[0] == "HEADER"), None)
    if head is None or not head[2] or head[2][0][0].upper() not in ("BOARD_FILE", "PANEL_FILE"):
        raise ValueError("This is not an IDF board file (.emn, .brd, .bdf or .idb from the ECAD program's IDF export).")
    name, units = "board", "MM"
    if len(head[2]) > 1:
        name = head[2][1][0] if head[2][1] else name
        units = head[2][1][1].upper() if len(head[2][1]) > 1 else units
    scale = UNITS.get(units, 1.0)
    out = {"name": name, "units": units, "thickness": 1.6, "outline": {}, "holes": [], "components": [],
           "library": find_library(board), "file": board}
    for sname, words, rows in secs:
        if sname in ("BOARD_OUTLINE", "PANEL_OUTLINE") and rows:
            try:
                out["thickness"] = float(rows[0][0]) * scale
            except (ValueError, IndexError):
                pass
            out["outline"] = _loops(rows[1:], scale)
        elif sname == "DRILLED_HOLES":
            for r in rows:
                try:
                    out["holes"].append((float(r[0]) * scale, float(r[1]) * scale, float(r[2]) * scale,
                                         r[3] if len(r) > 3 else "NPTH", r[4] if len(r) > 4 else "BOARD"))
                except (ValueError, IndexError):
                    continue
        elif sname == "PLACEMENT":
            for a, b in zip(rows[0::2], rows[1::2]):
                if len(a) < 3 or len(b) < 5:
                    continue
                try:
                    out["components"].append({"package": a[0], "part": a[1], "refdes": a[2],
                                              "x": float(b[0]) * scale, "y": float(b[1]) * scale,
                                              "z": float(b[2]) * scale, "rotation": float(b[3]),
                                              "side": b[4].upper(), "height": 0.0, "outline": []})
                except ValueError:
                    continue
    packages = read_library(out["library"]) if out["library"] else {}
    for c in out["components"]:
        p = packages.get((c["package"], c["part"])) or packages.get((c["package"], None))
        if p:
            c["height"], c["outline"] = p["height"], p["outline"]
    return out


def read_library(path):
    """{(package, part number): {height, outline points}} (also keyed (package, None))."""
    with open(path, "r", errors="replace") as f:
        text = f.read()
    secs = _sections(text)
    head = next((s for s in secs if s[0] == "HEADER"), None)
    units_default = "MM"
    out = {}
    for sname, words, rows in secs:
        if sname not in ("ELECTRICAL", "MECHANICAL") or not rows or len(rows[0]) < 4:
            continue
        pkg, part, units = rows[0][0], rows[0][1], rows[0][2].upper()
        scale = UNITS.get(units, UNITS.get(units_default))
        try:
            height = float(rows[0][3]) * scale
        except ValueError:
            height = 1.0
        loops = _loops([r for r in rows[1:] if len(r) >= 4 and r[0].lstrip("-").isdigit()], scale)
        entry = {"height": height, "outline": loops.get(0) or (next(iter(loops.values())) if loops else [])}
        out[(pkg, part)] = entry
        out.setdefault((pkg, None), entry)
    del head
    return out


# ============================================================================= shapes
def _edges(points):
    """IDF loop points -> Part edges (angle 0: line; 360: a circle about the previous point; else an arc with that
    included angle, counterclockwise when positive)."""
    import Part
    edges = []
    for (x0, y0, _a0), (x1, y1, a) in zip(points, points[1:]):
        p0, p1 = V(x0, y0, 0), V(x1, y1, 0)
        if abs(a) >= 359.999:
            edges.append(Part.Circle(p0, V(0, 0, 1), (p1 - p0).Length).toShape())
        elif abs(a) > 1e-9:
            chord = p1 - p0
            half = math.radians(a) / 2.0
            r = chord.Length / (2.0 * math.sin(abs(half)))
            mid = (p0 + p1) * 0.5
            n = V(-chord.y, chord.x, 0)
            n.normalize()
            d = r * math.cos(half)
            centre = mid + n * (d if a > 0 else -d) * (1 if abs(a) <= 180 else 1)
            ang0 = math.atan2(p0.y - centre.y, p0.x - centre.x)
            ang_mid = ang0 + math.radians(a) / 2.0
            pm = centre + V(r * math.cos(ang_mid), r * math.sin(ang_mid), 0)
            edges.append(Part.Arc(p0, pm, p1).toShape())
        elif (p1 - p0).Length > 1e-9:
            edges.append(Part.LineSegment(p0, p1).toShape())
    return edges


def _face(points):
    import Part
    edges = _edges(points)
    if not edges:
        return None
    wire = Part.Wire(Part.__sortEdges__(edges))
    if not wire.isClosed():
        wire = Part.Wire(Part.__sortEdges__(edges + [Part.LineSegment(wire.Vertexes[-1].Point,
                                                                         wire.Vertexes[0].Point).toShape()]))
    return Part.Face(wire)


def board_shape(b):
    """The board: its outline (loop 0) extruded by its thickness, less the cutouts (other loops) and the holes."""
    import Part
    outer = _face(b["outline"].get(0, []))
    if outer is None:
        raise ValueError("The board file has no board outline.")
    solid = outer.extrude(V(0, 0, b["thickness"]))
    cuts = []
    for label, pts in b["outline"].items():
        if label != 0:
            f = _face(pts)
            if f is not None:
                cuts.append(f.extrude(V(0, 0, b["thickness"] + 2)).translate(V(0, 0, -1)))
    for dia, x, y, _k, _o in b["holes"]:
        if dia > 0:
            cuts.append(Part.makeCylinder(dia / 2.0, b["thickness"] + 2, V(x, y, -1)))
    if cuts:
        solid = solid.cut(Part.makeCompound(cuts) if len(cuts) > 1 else cuts[0])
    return solid


def component_shape(c):
    """The component's own shape at the origin: its IDF outline extruded to its height (a 1 mm square when the
    component file has none)."""
    import Part
    f = _face(c["outline"]) if c.get("outline") else None
    h = max(0.01, float(c.get("height") or 1.0))
    if f is None:
        return Part.makeBox(1, 1, h, V(-0.5, -0.5, 0))
    return f.extrude(V(0, 0, h))


def component_placement(b, c):
    """Top: on the board's top face; bottom: under the board, mirrored (turned about X)."""
    rot = App.Rotation(V(0, 0, 1), c["rotation"])
    if c["side"].startswith("BOT"):
        return App.Placement(V(c["x"], c["y"], -c.get("z", 0.0)), App.Rotation(V(1, 0, 0), 180).multiply(
            App.Rotation(V(0, 0, 1), -c["rotation"])))
    return App.Placement(V(c["x"], c["y"], b["thickness"] + c.get("z", 0.0)), rot)


# ============================================================================= filters, library, options
def options():
    g = App.ParamGet(PARAM)
    return {"build": g.GetString("Build", "Assembly"), "min_height": g.GetFloat("MinHeight", 0.0),
            "use_library": g.GetBool("UseLibrary", True), "board_colour": g.GetBool("BoardColour", True),
            "top": g.GetBool("ShowTop", True), "bottom": g.GetBool("ShowBottom", True)}


def set_options(values):
    g = App.ParamGet(PARAM)
    for k, v in values.items():
        key = {"build": "Build", "min_height": "MinHeight", "use_library": "UseLibrary",
               "board_colour": "BoardColour", "top": "ShowTop", "bottom": "ShowBottom"}[k]
        if isinstance(v, bool):
            g.SetBool(key, v)
        elif isinstance(v, float):
            g.SetFloat(key, v)
        else:
            g.SetString(key, str(v))


def library():
    """{package name: model file} (the CircuitWorks Library)."""
    try:
        return dict(json.loads(App.ParamGet(PARAM).GetString("Library", "{}") or "{}"))
    except ValueError:
        return {}


def set_library(entries):
    App.ParamGet(PARAM).SetString("Library", json.dumps(dict(entries), sort_keys=True))


def passes(c, min_height=0.0, text="", top=True, bottom=True):
    """The CircuitWorks window's filter: height at least min_height, the name in refdes/part/package, the side."""
    if float(c.get("height") or 0.0) < float(min_height) - 1e-9:
        return False
    if text and text.lower() not in " ".join((c["refdes"], c["part"], c["package"])).lower():
        return False
    bottom_side = c["side"].startswith("BOT")
    return bottom if bottom_side else top


def _library_shape(c):
    path = library().get(c["package"])
    if not path or not os.path.isfile(path):
        return None
    import Part
    try:
        if path.lower().endswith((".step", ".stp", ".iges", ".igs", ".brep", ".brp")):
            s = Part.read(path)
        else:
            doc = App.openDocument(path, hidden=True)
            try:
                shapes = [o.Shape for o in doc.Objects if hasattr(o, "Shape") and not o.InList and not o.Shape.isNull()]
                s = Part.makeCompound(shapes) if len(shapes) > 1 else shapes[0]
            finally:
                App.closeDocument(doc.Name)
        return s if not s.isNull() else None
    except Exception as _fw_err:
        _fw_log("circuitworks.py:library", _fw_err)
        return None


# ============================================================================= Build Model / Update Model
def _meta(doc):
    try:
        return json.loads(doc.Meta.get(META, "") or "{}")
    except ValueError:
        return {}


def _set_meta(doc, d):
    meta = dict(doc.Meta)
    meta[META] = json.dumps(d)
    doc.Meta = meta


def _colour(obj, rgb):
    try:
        if obj.ViewObject is not None:
            obj.ViewObject.ShapeColor = rgb
    except Exception as _fw_err:
        _fw_log("circuitworks.py:colour", _fw_err)


def _package_feature(doc, holder, c, cache):
    key = c["package"] + "|" + c["part"]
    if key in cache:
        return cache[key]
    shape = (_library_shape(c) if options()["use_library"] else None) or component_shape(c)
    f = doc.addObject("Part::Feature", "Pkg")
    f.Label = c["package"]
    f.Shape = shape
    holder.addObject(f)
    _colour(f, COMPONENT_COLOUR)
    if f.ViewObject is not None:
        f.ViewObject.Visibility = False
    cache[key] = f
    return f


def build(b, picked=None, kind=None, doc=None):
    """Build Model: kind "Assembly" (the board fixed and one component per placement, linking the package models) or
    "Part" (one part, a body per component). picked: the reference designators to build (all when None).
    Returns the document."""
    kind = kind or options()["build"]
    comps = [c for c in b["components"] if picked is None or c["refdes"] in picked]
    if doc is None:
        doc = App.newDocument("".join(ch if ch.isalnum() else "_" for ch in b["name"]) or "Board")
        doc.Label = b["name"]
    board = doc.addObject("Part::Feature", "Board")
    board.Label = "Board"
    board.Shape = board_shape(b)
    if options()["board_colour"]:
        _colour(board, BOARD_COLOUR)
    meta = {"file": b.get("file"), "kind": kind, "comps": {}, "board": board.Name}
    if kind == "Part":
        part = doc.addObject("App::Part", "Part")
        part.Label = b["name"]
        part.addObject(board)
        for c in comps:
            f = doc.addObject("Part::Feature", "Component")
            f.Label = c["refdes"]
            shape = (_library_shape(c) if options()["use_library"] else None) or component_shape(c)
            f.Shape = shape
            f.Placement = component_placement(b, c)
            part.addObject(f)
            _colour(f, COMPONENT_COLOUR)
            meta["comps"][c["refdes"]] = f.Name
        meta["part"] = part.Name
    else:
        from . import asmcore as ac
        holder = doc.addObject("App::DocumentObjectGroup", "CircuitWorksModels")
        holder.Label = "CircuitWorks Models"
        holder.addObject(board)
        board.Label = "Board model"          # the hidden model; its component in the assembly is "Board"
        if board.ViewObject is not None:
            board.ViewObject.Visibility = False
        asm = ac.make_assembly(doc)
        link = ac.insert(asm, board, App.Placement())
        link.Label = "Board"
        if not ac.grounded(asm):
            ac.fix(asm, link)
        meta["board_link"] = link.Name
        cache = {}
        for c in comps:
            pkg = _package_feature(doc, holder, c, cache)
            comp = ac.insert(asm, pkg, component_placement(b, c))
            comp.Label = c["refdes"]
            meta["comps"][c["refdes"]] = comp.Name
        meta["asm"] = asm.Name
        if holder.ViewObject is not None:
            holder.ViewObject.Visibility = False
    _set_meta(doc, meta)
    doc.recompute()
    return doc


def update(doc, path=None):
    """Update Model: the file read again; components moved, added and removed by reference designator.
    Returns (moved, added, removed) reference designators."""
    meta = _meta(doc)
    path = path or meta.get("file")
    if not meta or not path:
        raise ValueError("This model was not built from an ECAD file.")
    b = read(path)
    board = doc.getObject(meta.get("board", ""))
    if board is not None:
        board.Shape = board_shape(b)
    by = {c["refdes"]: c for c in b["components"]}
    moved, added, removed = [], [], []
    for ref, name in list(meta["comps"].items()):
        obj = doc.getObject(name)
        if ref not in by:
            if obj is not None:
                doc.removeObject(name)
            del meta["comps"][ref]
            removed.append(ref)
            continue
        plc = component_placement(b, by[ref])
        if obj is not None and not obj.Placement.isSame(plc, 1e-6):
            obj.Placement = plc
            moved.append(ref)
    new = [c for r, c in by.items() if r not in meta["comps"]]
    if new:
        if meta.get("kind") == "Part":
            part = doc.getObject(meta.get("part", ""))
            for c in new:
                f = doc.addObject("Part::Feature", "Component")
                f.Label = c["refdes"]
                f.Shape = component_shape(c)
                f.Placement = component_placement(b, c)
                if part is not None:
                    part.addObject(f)
                _colour(f, COMPONENT_COLOUR)
                meta["comps"][c["refdes"]] = f.Name
                added.append(c["refdes"])
        else:
            from . import asmcore as ac
            asm = doc.getObject(meta.get("asm", ""))
            holder = doc.getObject("CircuitWorksModels")
            cache = {}
            for c in new:
                pkg = _package_feature(doc, holder, c, cache)
                comp = ac.insert(asm, pkg, component_placement(b, c))
                comp.Label = c["refdes"]
                meta["comps"][c["refdes"]] = comp.Name
                added.append(c["refdes"])
    meta["file"] = path
    _set_meta(doc, meta)
    doc.recompute()
    return moved, added, removed


# ============================================================================= Export to ECAD (IDF 3.0)
def _fmt(v):
    return ("%.4f" % v).rstrip("0").rstrip(".") if abs(v) > 1e-9 else "0"


def _loop_rows(wire, label, z):
    """IDF rows of a wire at the bottom of the board: each edge's end point, with an arc's included angle; a
    lone circle as its centre then a point on it with 360."""
    edges = wire.OrderedEdges if hasattr(wire, "OrderedEdges") else wire.Edges
    if len(edges) == 1 and "Circle" in type(edges[0].Curve).__name__ and edges[0].isClosed():
        c, r = edges[0].Curve.Center, edges[0].Curve.Radius
        return [(label, c.x, c.y, 0.0), (label, c.x + r, c.y, 360.0)]
    rows = []
    start = edges[0].Vertexes[0].Point if not wire.Vertexes else wire.OrderedVertexes[0].Point
    rows.append((label, start.x, start.y, 0.0))
    cur = start
    for e in edges:
        a, bpt = e.Vertexes[0].Point, e.Vertexes[-1].Point
        end = bpt if (a - cur).Length <= (bpt - cur).Length else a
        ang = 0.0
        if "Circle" in type(e.Curve).__name__:
            span = math.degrees(e.LastParameter - e.FirstParameter)
            ccw = e.Curve.Axis.z > 0
            forward = (end - bpt).Length < 1e-7
            ang = span * (1 if ccw == forward else -1)
        elif "Line" not in type(e.Curve).__name__:
            pts = e.discretize(Deflection=0.01)
            if (pts[0] - cur).Length > (pts[-1] - cur).Length:
                pts.reverse()
            for p in pts[1:-1]:
                rows.append((label, p.x, p.y, 0.0))
        rows.append((label, end.x, end.y, ang))
        cur = end
    return rows


def _board_bottom(shape):
    faces = [f for f in shape.Faces if "Plane" in f.Surface.TypeId and abs(abs(f.normalAt(0, 0).z) - 1) < 1e-6]
    if not faces:
        raise ValueError("The board needs flat top and bottom faces (a plate on the XY plane).")
    zmin = min(f.BoundBox.ZMin for f in faces)
    bottom = max((f for f in faces if abs(f.BoundBox.ZMin - zmin) < 1e-6), key=lambda f: f.Area)
    return bottom, zmin


def export_idf(board_obj, components, path):
    """Writes path (.emn) and the .emp beside it: the board's outline (its bottom face's outer wire), cutouts (other
    wires), round holes as drilled holes, and each component as a placed package (its footprint and height).
    Returns (board file, component file)."""
    shape = board_obj.Shape
    bottom, zmin = _board_bottom(shape)
    thickness = shape.BoundBox.ZMax - zmin
    tops = [f for f in shape.Faces if "Plane" in f.Surface.TypeId and abs(f.normalAt(0, 0).z - 1) < 1e-6]
    if tops:
        thickness = max(f.BoundBox.ZMax for f in tops) - zmin
    stem = os.path.splitext(path)[0]
    emn, emp = stem + ".emn", stem + ".emp"
    name = board_obj.Label.replace('"', "'")
    stamp = datetime.datetime.now().strftime("%Y/%m/%d.%H:%M:%S")
    rows, holes = [], []
    label = 1
    for w in bottom.Wires:
        if w.isSame(bottom.OuterWire):
            rows = _loop_rows(w, 0, zmin) + rows
            continue
        es = w.Edges
        if len(es) == 1 and "Circle" in type(es[0].Curve).__name__:
            c = es[0].Curve
            holes.append((2 * c.Radius, c.Center.x, c.Center.y))
        else:
            rows += _loop_rows(w, label, zmin)
            label += 1
    out = ['.HEADER', 'BOARD_FILE 3.0 "FreeCAD" %s 1' % stamp, '"%s" MM' % name, '.END_HEADER',
           '.BOARD_OUTLINE MCAD', _fmt(thickness)]
    out += ["%d %s %s %s" % (lb, _fmt(x), _fmt(y), _fmt(a)) for lb, x, y, a in rows]
    out.append('.END_BOARD_OUTLINE')
    if holes:
        out.append('.DRILLED_HOLES')
        out += ["%s %s %s NPTH BOARD MTG MCAD" % (_fmt(d), _fmt(x), _fmt(y)) for d, x, y in holes]
        out.append('.END_DRILLED_HOLES')
    lib, placed = [], []
    seen = {}
    top_z = zmin + thickness
    for obj in components:
        bb = obj.Shape.BoundBox
        bottom_side = bb.ZMax <= zmin + 1e-6
        pkg = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in obj.Label) or "PKG"
        w, d, h = bb.XLength, bb.YLength, bb.ZLength
        key = (round(w, 4), round(d, 4), round(h, 4))
        if pkg not in seen:
            seen[pkg] = key
            lib += ['.ELECTRICAL', '"%s" "%s" MM %s' % (pkg, pkg, _fmt(h)),
                    "0 %s %s 0" % (_fmt(-w / 2), _fmt(-d / 2)), "0 %s %s 0" % (_fmt(w / 2), _fmt(-d / 2)),
                    "0 %s %s 0" % (_fmt(w / 2), _fmt(d / 2)), "0 %s %s 0" % (_fmt(-w / 2), _fmt(d / 2)),
                    "0 %s %s 0" % (_fmt(-w / 2), _fmt(-d / 2)), '.END_ELECTRICAL']
        z = (zmin - bb.ZMax) if bottom_side else (bb.ZMin - top_z)
        placed += ['"%s" "%s" "%s"' % (pkg, pkg, obj.Label.replace('"', "'")),
                   "%s %s %s 0 %s MCAD" % (_fmt(bb.Center.x), _fmt(bb.Center.y), _fmt(max(0.0, z)),
                                           "BOTTOM" if bottom_side else "TOP")]
    if placed:
        out += ['.PLACEMENT'] + placed + ['.END_PLACEMENT']
    with open(emn, "w") as f:
        f.write("\n".join(out) + "\n")
    with open(emp, "w") as f:
        f.write("\n".join(['.HEADER', 'LIBRARY_FILE 3.0 "FreeCAD" %s 1' % stamp, '.END_HEADER'] + lib) + "\n")
    return emn, emp


def guess_board(doc, objs=None):
    """(board, components): the flattest plate among the shapes is the board; the rest are its components."""
    objs = objs or [o for o in doc.Objects if not o.InList and o.TypeId in ("Part::Feature", "PartDesign::Body")
                     or (o.TypeId.startswith("Part::") and not o.InList)]
    objs = [o for o in objs if hasattr(o, "Shape") and not o.Shape.isNull() and o.Shape.Solids]
    meta = _meta(doc)
    if meta.get("comps"):        # a model CircuitWorks built: its board and its components
        board = doc.getObject(meta.get("board_link") or meta.get("board", ""))
        comps = [doc.getObject(n) for n in meta["comps"].values() if doc.getObject(n) is not None]
        if board is not None:
            return board, comps
    if not objs:
        return None, []

    def flat(o):
        bb = o.Shape.BoundBox
        return bb.ZLength / max(1e-9, max(bb.XLength, bb.YLength)), -bb.XLength * bb.YLength
    board = min(objs, key=flat)
    return board, [o for o in objs if o is not board]


# ============================================================================= windows
if Gui is not None:
    class CircuitWorksWindow(QtWidgets.QDialog):
        ""

        def __init__(self, board, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.setObjectName("SWCircuitWorks")
            self.board = board
            self.setWindowTitle("CircuitWorks - %s" % os.path.basename(board.get("file") or board["name"]))
            o = options()
            lay = QtWidgets.QVBoxLayout(self)
            filt = QtWidgets.QHBoxLayout()
            self.text = QtWidgets.QLineEdit()
            self.text.setObjectName("SWCircuitWorksFilterText")
            self.text.setPlaceholderText("Filter by name")
            self.min_h = QtWidgets.QDoubleSpinBox()
            self.min_h.setObjectName("SWCircuitWorksMinHeight")
            self.min_h.setRange(0, 1000)
            self.min_h.setDecimals(3)
            self.min_h.setSuffix(" mm")
            self.min_h.setValue(o["min_height"])
            self.top = QtWidgets.QCheckBox("Top")
            self.top.setObjectName("SWCircuitWorksTop")
            self.top.setChecked(o["top"])
            self.bottom = QtWidgets.QCheckBox("Bottom")
            self.bottom.setObjectName("SWCircuitWorksBottom")
            self.bottom.setChecked(o["bottom"])
            filt.addWidget(self.text, 1)
            filt.addWidget(QtWidgets.QLabel("Minimum height:"))
            filt.addWidget(self.min_h)
            filt.addWidget(self.top)
            filt.addWidget(self.bottom)
            lay.addLayout(filt)
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setObjectName("SWCircuitWorksTree")
            self.tree.setHeaderLabels(["Name", "Part number", "Package", "Height", "Side"])
            lay.addWidget(self.tree, 1)
            self.info = QtWidgets.QLabel()
            self.info.setObjectName("SWCircuitWorksInfo")
            lay.addWidget(self.info)
            row = QtWidgets.QHBoxLayout()
            self.build_btn = QtWidgets.QPushButton("Build Model")
            self.build_btn.setObjectName("SWCircuitWorksBuild")
            self.part_btn = QtWidgets.QPushButton("Build Model as Part")
            self.part_btn.setObjectName("SWCircuitWorksBuildPart")
            close = QtWidgets.QPushButton("Close")
            self.build_btn.clicked.connect(lambda *_a: self.build("Assembly"))
            self.part_btn.clicked.connect(lambda *_a: self.build("Part"))
            close.clicked.connect(self.reject)
            row.addStretch(1)
            for b in (self.build_btn, self.part_btn, close):
                row.addWidget(b)
            lay.addLayout(row)
            for w in (self.top, self.bottom):
                w.toggled.connect(lambda *_a: self.refresh())
            self.text.textChanged.connect(lambda *_a: self.refresh())
            self.min_h.valueChanged.connect(lambda *_a: self.refresh())
            self.resize(720, 480)
            self.refresh()

        def refresh(self):
            self.tree.clear()
            b = self.board
            root = QtWidgets.QTreeWidgetItem([b["name"], "", "Board", "%g" % b["thickness"], ""])
            self.tree.addTopLevelItem(root)
            holes = QtWidgets.QTreeWidgetItem(["Holes (%d)" % len(b["holes"]), "", "", "", ""])
            cut = QtWidgets.QTreeWidgetItem(["Cutouts (%d)" % (len(b["outline"]) - 1 if b["outline"] else 0), "", "", "", ""])
            comps = QtWidgets.QTreeWidgetItem(["Components", "", "", "", ""])
            for it in (holes, cut, comps):
                root.addChild(it)
            shown = 0
            for c in b["components"]:
                if not passes(c, self.min_h.value(), self.text.text(), self.top.isChecked(), self.bottom.isChecked()):
                    continue
                it = QtWidgets.QTreeWidgetItem([c["refdes"], c["part"], c["package"], "%g" % c["height"],
                                                "Bottom" if c["side"].startswith("BOT") else "Top"])
                it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(0, QtCore.Qt.Checked)
                comps.addChild(it)
                shown += 1
            root.setExpanded(True)
            comps.setExpanded(True)
            self.info.setText("%d of %d components shown" % (shown, len(b["components"])))

        def picked(self):
            comps = self.tree.topLevelItem(0).child(2)
            return {comps.child(i).text(0) for i in range(comps.childCount())
                    if comps.child(i).checkState(0) == QtCore.Qt.Checked}

        def build(self, kind):
            try:
                self.doc = build(self.board, self.picked(), kind)
            except Exception as error:
                QtWidgets.QMessageBox.warning(self, "Build Model", "The model could not be built: %s" % error)
                return None
            try:
                Gui.SendMsgToActiveView("ViewFit")
            except Exception as _fw_err:
                _fw_log("circuitworks.py:fit", _fw_err)
            self.accept()
            return self.doc

    class LibraryDialog(QtWidgets.QDialog):
        """The CircuitWorks Library: which model stands for each package when a board is built."""

        def __init__(self, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.setObjectName("SWCircuitWorksLibrary")
            self.setWindowTitle("CircuitWorks Library")
            lay = QtWidgets.QVBoxLayout(self)
            self.table = QtWidgets.QTableWidget(0, 2)
            self.table.setObjectName("SWCircuitWorksLibraryTable")
            self.table.setHorizontalHeaderLabels(["Package", "Model file"])
            self.table.horizontalHeader().setStretchLastSection(True)
            for pkg, path in sorted(library().items()):
                self.add(pkg, path)
            lay.addWidget(self.table, 1)
            row = QtWidgets.QHBoxLayout()
            for text, fn in (("Add...", self.browse), ("Remove", self.remove)):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("SWCircuitWorksLibrary" + text.strip(".").replace(" ", ""))
                b.clicked.connect(lambda *_a, fn=fn: fn())
                row.addWidget(b)
            row.addStretch(1)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.ok)
            bb.rejected.connect(self.reject)
            row.addWidget(bb)
            lay.addLayout(row)
            self.resize(560, 320)

        def add(self, pkg="", path=""):
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(pkg))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(path))
            return r

        def browse(self, path=None, pkg=None):
            if path is None:
                path, _f = QtWidgets.QFileDialog.getOpenFileName(self, "Model for a package", "",
                                                                 "Models (*.step *.stp *.FCStd *.iges *.igs *.brep)")
                if not path:
                    return None
            return self.add(pkg or os.path.splitext(os.path.basename(path))[0], path)

        def remove(self):
            r = self.table.currentRow()
            if r < 0:
                r = self.table.rowCount() - 1
            if r >= 0:
                self.table.removeRow(r)

        def entries(self):
            out = {}
            for r in range(self.table.rowCount()):
                pkg = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
                path = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
                if pkg and path:
                    out[pkg] = path
            return out

        def ok(self):
            set_library(self.entries())
            self.accept()

    class OptionsDialog(QtWidgets.QDialog):
        """CircuitWorks Options: what Build Model makes and what the CircuitWorks window shows by default."""

        def __init__(self, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.setObjectName("SWCircuitWorksOptions")
            self.setWindowTitle("CircuitWorks Options")
            o = options()
            lay = QtWidgets.QFormLayout(self)
            self.build = QtWidgets.QComboBox()
            self.build.setObjectName("SWCircuitWorksOptBuild")
            self.build.addItems(["Assembly", "Part"])
            self.build.setCurrentText(o["build"])
            lay.addRow("Build the model as:", self.build)
            self.min_h = QtWidgets.QDoubleSpinBox()
            self.min_h.setObjectName("SWCircuitWorksOptMinHeight")
            self.min_h.setRange(0, 1000)
            self.min_h.setDecimals(3)
            self.min_h.setSuffix(" mm")
            self.min_h.setValue(o["min_height"])
            lay.addRow("Leave out components lower than:", self.min_h)
            self.top = QtWidgets.QCheckBox("Top side components")
            self.top.setChecked(o["top"])
            self.bottom = QtWidgets.QCheckBox("Bottom side components")
            self.bottom.setChecked(o["bottom"])
            self.use_lib = QtWidgets.QCheckBox("Use Library models for components")
            self.use_lib.setObjectName("SWCircuitWorksOptLibrary")
            self.use_lib.setChecked(o["use_library"])
            self.colour = QtWidgets.QCheckBox("Colour the board green")
            self.colour.setChecked(o["board_colour"])
            for w in (self.top, self.bottom, self.use_lib, self.colour):
                lay.addRow(w)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.ok)
            bb.rejected.connect(self.reject)
            lay.addRow(bb)

        def ok(self):
            set_options({"build": self.build.currentText(), "min_height": float(self.min_h.value()),
                         "top": self.top.isChecked(), "bottom": self.bottom.isChecked(),
                         "use_library": self.use_lib.isChecked(), "board_colour": self.colour.isChecked()})
            self.accept()

    LAST = {}

    def _warn(title, text):
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), title, text)

    def open_file(path=None):
        """Open ECAD File: the board in the CircuitWorks window."""
        if path is None:
            path, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Open ECAD File", "",
                                                             "IDF board (*.emn *.brd *.bdf *.idb);;All files (*)")
            if not path:
                return None
        try:
            b = read(path)
        except (OSError, ValueError) as error:
            _warn("Open ECAD File", str(error))
            return None
        if not b["outline"]:
            _warn("Open ECAD File", "The board file has no board outline.")
            return None
        if b["library"] is None and b["components"]:
            App.Console.PrintWarning("FreeCAD: %s has no component file (.emp) next to it: components are built "
                                     "as 1 mm squares.\n" % os.path.basename(path))
        dlg = CircuitWorksWindow(b)
        LAST["window"] = dlg
        dlg.show()
        return dlg

    def export_active(path=None):
        """Export to ECAD: the active model as IDF 3.0."""
        doc = App.ActiveDocument
        if doc is None:
            _warn("Export to ECAD", "Open the board model first.")
            return None
        sel = [o for o in Gui.Selection.getSelection() if hasattr(o, "Shape")]
        board, comps = guess_board(doc, sel or None)
        if board is None:
            _warn("Export to ECAD", "There is no board to export: a flat plate (the board) is needed.")
            return None
        if path is None:
            base = os.path.splitext(doc.FileName)[0] if doc.FileName else doc.Label
            path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Export to ECAD", base + ".emn",
                                                             "IDF 3.0 board (*.emn)")
            if not path:
                return None
        try:
            files = export_idf(board, comps, path)
        except Exception as error:
            _warn("Export to ECAD", "The board could not be exported: %s" % error)
            return None
        App.Console.PrintMessage("FreeCAD: IDF written: %s and %s\n" % files)
        return files

    def update_active(path=None):
        doc = App.ActiveDocument
        if doc is None or not _meta(doc).get("comps") and not _meta(doc).get("board"):
            _warn("Update Model", "The active model was not built from an ECAD file (Open ECAD File, Build Model).")
            return None
        meta = _meta(doc)
        if path is None and not (meta.get("file") and os.path.isfile(meta["file"])):
            path, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Update Model", "",
                                                             "IDF board (*.emn *.brd *.bdf *.idb)")
            if not path:
                return None
        try:
            out = update(doc, path)
        except (OSError, ValueError) as error:
            _warn("Update Model", str(error))
            return None
        App.Console.PrintMessage("FreeCAD: model updated: %d moved, %d added, %d removed\n" % tuple(len(x) for x in out))
        return out

    def built_here():
        doc = App.ActiveDocument
        return doc is not None and bool(_meta(doc).get("board"))

    class _Cmd:
        def __init__(self, text, tip, run, active=None, pixmap="freecad"):
            self.text, self.tip, self.run, self.active, self.pixmap = text, tip, run, active, pixmap

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": self.pixmap}

        def IsActive(self):
            return True if self.active is None else bool(self.active())

        def Activated(self, *_a):
            self.run()

    def _show(dlg_cls):
        dlg = dlg_cls()
        LAST["dialog"] = dlg
        dlg.show()
        return dlg

    COMMANDS = {
        "SWStyle_ECADOpen": _Cmd("Open ECAD File", "Opens an IDF board (.emn with its .emp) in the CircuitWorks window: "
                                 "filter its components, then Build Model.", lambda: open_file(), None, "document-open"),
        "SWStyle_ECADExport": _Cmd("Export to ECAD", "Saves the board and its components as IDF 3.0 (.emn and .emp) "
                                   "for the ECAD program.", lambda: export_active(), lambda: App.ActiveDocument is not None,
                                   "document-save-as"),
        "SWStyle_ECADUpdate": _Cmd("Update Model", "Reads the ECAD file again: components moved, added or removed by "
                                   "reference designator.", lambda: update_active(), built_here, "view-refresh"),
        "SWStyle_ECADLibrary": _Cmd("Library", "The model used for each package when a board is built.",
                                    lambda: _show(LibraryDialog), None, "freecad"),
        "SWStyle_ECADOptions": _Cmd("CircuitWorks Options", "What Build Model makes and what the CircuitWorks window "
                                    "shows.", lambda: _show(OptionsDialog), None, "preferences-system"),
    }

    def register():
        for name, cmd in COMMANDS.items():
            try:
                Gui.addCommand(name, cmd)
            except Exception as _fw_err:
                _fw_log("circuitworks.py:register", _fw_err)
