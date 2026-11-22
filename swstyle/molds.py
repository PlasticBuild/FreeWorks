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
import Part

from . import simplefeature as sf
from . import surfacefeatures as surf
from .simplefeature import Field

try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

V = App.Vector


def _solid_of(obj):
    shape = Part.getShape(obj) if obj is not None else Part.Shape()
    if shape.isNull() or not shape.Solids:
        raise RuntimeError("Pick the part (a body with a solid)")
    return shape.Solids[0] if len(shape.Solids) == 1 else shape


def _pull(obj, field="Direction"):
    picked = sf.elements(obj, field)
    pull = V(0, 0, 1)
    if picked:
        shape = picked[0][1]
        if shape.ShapeType == "Face" and isinstance(shape.Surface, Part.Plane):
            pull = shape.Surface.Axis
        elif shape.ShapeType == "Edge" and len(shape.Vertexes) == 2:
            pull = shape.Vertexes[1].Point - shape.Vertexes[0].Point
        elif shape.ShapeType == "Face":
            pull = shape.normalAt(0, 0)
    pull = V(pull)
    pull.normalize()
    return pull * (-1 if getattr(obj, "Reverse", False) else 1)


def _same_edge(a, b):
    return a.isSame(b) or (abs(a.Length - b.Length) < 1e-7 and a.CenterOfMass.distanceToPoint(b.CenterOfMass) < 1e-7)


# --------------------------------------------------------------------------- Parting Line
def _split_edges(obj, solid):
    """Split faces: the curves across the faces that straddle the pull, at the +/- draft
    transition (side-on to the pull) or at the specified angle."""
    if not getattr(obj, "SplitFaces", False):
        return []
    from . import evaluate
    from .directfeatures import _silhouette_edges
    pull = _pull(obj)
    angle = float(getattr(obj, "SplitAngle", 0.0)) if getattr(obj, "SplitAt", "") == "At specified angle" else 0.0
    out = []
    for face in solid.Faces:
        if evaluate.classify_draft(face, pull, max(float(obj.DraftAngle), 1e-3)) != "straddle":
            continue
        try:
            out += [e for e in _silhouette_edges(face, pull, angle=angle) if e.Length > 1e-6]
        except Exception:
            continue
    return out


def parting_edges(obj):
    """The part's edges on the parting line: the picked ones, else those Parting Line Analysis finds,
    with the split-face curves when Split faces is on."""
    solid = _solid_of(obj.Part)
    picked = [e for _, e in sf.elements(obj, "Edges") if e.ShapeType == "Edge"]
    split = _split_edges(obj, solid)
    if picked:
        return solid, ([e for e in solid.Edges if any(_same_edge(e, p) for p in picked)] or picked) + split
    from . import partingline
    pull = _pull(obj)
    _, line = partingline.analyse(solid, pull, float(obj.DraftAngle))
    found = [solid.Edges[k] for k in line]
    try:
        found = [e for w in _outer_loops([Part.Wire(g) for g in Part.sortEdges(found)], pull) for e in w.Edges]
    except Exception as _fw_err:
        _fw_log("molds.py:102", _fw_err)
    return solid, found + split


_DRAFT = []        # the draft colours shown from inside the Parting Line page (one at a time)


def _drop_draft():
    while _DRAFT:
        w = _DRAFT.pop()
        try:
            w._fw_timer.stop()
        except Exception as _fw_err:
            _fw_log("molds.py:115", _fw_err)
        try:
            w.cleanup()
            w.deleteLater()
        except Exception as _fw_err:
            _fw_log("molds.py:120", _fw_err)


def _draft_in_page(obj):
    ""


    if _DRAFT:
        _drop_draft()
        return None
    from . import evalpm
    from PySide import QtCore
    w = evalpm.DraftWindow()
    w.pull = _pull(obj) * (-1 if getattr(obj, "Reverse", False) else 1)
    if hasattr(w, "reverse"):
        w.reverse.setChecked(bool(getattr(obj, "Reverse", False)))
    if hasattr(w, "direction"):
        w.direction.setText("Parting Line pull")
    w.angle.setValue(float(obj.DraftAngle))
    try:
        w.refresh()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Draft Analysis: %s\n" % error)
    _DRAFT.append(w)
    timer = QtCore.QTimer(w)
    timer.setInterval(400)
    timer.timeout.connect(lambda: None if Gui.Control.activeDialog() else _drop_draft())
    timer.start()
    w._fw_timer = timer
    return w


def _show_draft(obj):
    """The Draft Analysis button: the part's faces coloured by draft against this pull and angle."""
    if Gui is None:
        return
    if Gui.Control.activeDialog():
        return _draft_in_page(obj)
    Gui.runCommand("SWStyle_DraftAnalysis", 0)
    from PySide import QtWidgets
    for w in QtWidgets.QApplication.allWidgets():
        if w.objectName() in ("SWDraftAnalysis", "Draft Analysis") and hasattr(w, "angle") and hasattr(w, "pull"):
            w.pull = _pull(obj) * (-1 if getattr(obj, "Reverse", False) else 1)   # the window applies Reverse itself
            if hasattr(w, "reverse"):
                w.reverse.setChecked(bool(getattr(obj, "Reverse", False)))
            if hasattr(w, "direction"):
                w.direction.setText("Parting Line pull")
            w.angle.setValue(float(obj.DraftAngle))
            try:
                w.refresh()
            except Exception as _fw_err:
                _fw_log("molds.py:171", _fw_err)
            break


def _outer_loops(wires, pull):
    ""


    closed = [w for w in wires if w.isClosed()]
    if len(closed) < 2:
        return wires
    import math
    place = App.Placement(V(), App.Rotation(V(0, 0, 1), pull))
    flat = place.inverse().toMatrix()
    discs = {}
    for w in closed:
        try:
            pts = [flat.multiply(q) for q in w.discretize(Deflection=0.05)]
            pts = [V(q.x, q.y, 0) for q in pts]
            pts = [q for k, q in enumerate(pts) if k == 0 or q.distanceToPoint(pts[k - 1]) > 1e-7]
            if pts[-1].distanceToPoint(pts[0]) < 1e-7:
                pts.pop()
            discs[id(w)] = Part.Face(Part.makePolygon(pts + [pts[0]]))
        except Exception as _fw_err:
            _fw_log("molds.py:195", _fw_err)
    out = []
    for w in wires:
        d = discs.get(id(w))
        inside = d is not None and any(
            o is not w and id(o) in discs and discs[id(o)].Area > d.Area
            and discs[id(o)].common(d).Area > 0.999 * d.Area for o in closed)
        if not inside:
            out.append(w)
    return out or wires


def _parting_line(obj, base):
    if obj.Part is None:
        return None, None
    solid, edges = parting_edges(obj)
    if not edges:
        raise RuntimeError("No parting line: the part has no faces on both sides of the pull direction")
    try:
        wires = [Part.Wire(group) for group in Part.sortEdges(edges)]
        shape = Part.makeCompound(wires)
    except Exception:
        shape = Part.makeCompound(edges)
    text = "%d edges%s" % (len(edges), "" if all(w.isClosed() for w in shape.Wires) else " (the line is not closed)")
    if obj.Info != text:
        obj.Info = text
    return shape, None


# --------------------------------------------------------------------------- Parting Line edge buttons
def _edge_list(obj):
    """The open Parting Line page's edge box (a QListWidget), or None."""
    try:
        from PySide import QtWidgets
    except ImportError:
        return None
    for w in QtWidgets.QApplication.allWidgets():
        try:
            if w.objectName() == "SWStyle_Edges" and isinstance(w, QtWidgets.QListWidget) and w.isVisible():
                return w
        except RuntimeError:
            continue
    return None


def _set_edges(obj, pairs):
    """obj.Edges from (object, "EdgeN") pairs, rebuilt and shown in the page's box."""
    obj.Edges = [(o, [e]) for o, e in pairs]
    obj.Document.recompute()
    box = _edge_list(obj)
    if box is not None:
        box.clear()
        for o, e in pairs:
            box.addItem("%s.%s" % (o.Label, e))


def _edge_pairs(obj):
    out = []
    for source, subs in obj.Edges or []:
        for s in (subs if isinstance(subs, (list, tuple)) else [subs]):
            out.append((source, s))
    return out


def _part_holder(obj):
    """The object whose EdgeN names the part's edges (the body, or the part itself)."""
    return obj.Part


def add_selected_edges(obj):
    ""
    if Gui is None or obj.Part is None:
        return 0
    pairs = _edge_pairs(obj)
    solid = _solid_of(obj.Part)
    added = 0
    for sel in Gui.Selection.getSelectionEx(obj.Document.Name):
        for sub, shape in zip(sel.SubElementNames, sel.SubObjects):
            if shape.ShapeType != "Edge":
                continue
            k = next((i for i, e in enumerate(solid.Edges, 1) if _same_edge(e, shape)), None)
            if k is None:
                continue
            key = (_part_holder(obj), "Edge%d" % k)
            if key not in pairs:
                pairs.append(key)
                added += 1
    Gui.Selection.clearSelection()
    _set_edges(obj, pairs)
    return added


def next_edge(obj):
    ""


    if obj.Part is None:
        return None
    solid = _solid_of(obj.Part)
    pairs = _edge_pairs(obj)
    names = [e for _o, e in pairs]
    chosen = []
    for n in names:
        try:
            chosen.append(int(n[4:]) - 1)
        except ValueError as _fw_err:
            _fw_log("molds.py:301", _fw_err)
    if not chosen:
        return None
    from . import partingline
    pull = _pull(obj)
    _, line = partingline.analyse(solid, pull, float(obj.DraftAngle))
    line = set(line)
    last = solid.Edges[chosen[-1]]
    ends = [v.Point for v in last.Vertexes]
    if len(chosen) > 1:
        prev = solid.Edges[chosen[-2]]
        ends = [p for p in ends if all((p - v.Point).Length > 1e-6 for v in prev.Vertexes)] or ends
    best = None
    for k, e in enumerate(solid.Edges):
        if k in chosen or not any((p - v.Point).Length < 1e-6 for p in ends for v in e.Vertexes):
            continue
        try:
            t = e.tangentAt((e.FirstParameter + e.LastParameter) / 2.0)
            along = abs(t.dot(pull))
        except Exception:
            along = 1.0
        score = (0 if k in line else 1, along)
        if best is None or score < best[0]:
            best = (score, k)
    if best is None:
        return None
    name = "Edge%d" % (best[1] + 1)
    _set_edges(obj, pairs + [(_part_holder(obj), name)])
    return name


def zoom_to_edges(obj):
    ""
    if Gui is None or Gui.ActiveDocument is None:
        return False
    solid = _solid_of(obj.Part) if obj.Part is not None else None
    edges = []
    for _o, n in _edge_pairs(obj):
        try:
            edges.append(solid.Edges[int(n[4:]) - 1])
        except Exception as _fw_err:
            _fw_log("molds.py:342", _fw_err)
    if not edges:
        return False
    box = Part.makeCompound(edges).BoundBox
    box.enlarge(max(box.DiagonalLength * 0.1, 1.0))
    view = Gui.ActiveDocument.ActiveView
    try:
        from pivy import coin
        sep = coin.SoSeparator()
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, 2, [[box.XMin, box.YMin, box.ZMin], [box.XMax, box.YMax, box.ZMax]])
        sep.addChild(coords)
        sep.addChild(coin.SoPointSet())
        viewer = view.getViewer()
        region = viewer.getSoRenderManager().getViewportRegion()
        view.getCameraNode().viewAll(sep, region)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Zoom to selection: %s\n" % error)
        view.fitAll()
        return False


PARTING_LINE = sf.Spec(
    "SWStyle_PartingLine", "Parting Line", "Parting Line",
    "The edges where a two-part mould opens, from the draft against the direction of pull.",
    "MOLD_PARTING_LINE", "Part_Section",
    [Field("Part", "pick", "Part", tip="The part to mould (a body)", what="Object", box="Mold Parameters"),
     Field("Direction", "pick", "Direction of Pull", what=("Face", "Edge"), optional=True,
           tip="A plane, a flat face or a straight edge (Z when empty)", box="Mold Parameters"),
     Field("Reverse", "bool", "Reverse direction", False, box="Mold Parameters"),
     Field("DraftAngle", "angle", "Draft angle", 1.0, low=0.0, high=30.0, box="Mold Parameters"),
     Field("DraftAnalysis", "button", "Draft Analysis", action=lambda o: _show_draft(o),
           tip="Colours the part's faces by draft against this pull", box="Mold Parameters"),
     Field("UseForSplit", "bool", "Use for Core/Cavity Split", True, box="Mold Parameters"),
     Field("SplitFaces", "bool", "Split faces", False, box="Mold Parameters"),
     Field("SplitAt", "radio", "", "At +/- draft transition", values=["At +/- draft transition", "At specified angle"],
           shown=lambda o: getattr(o, "SplitFaces", False), box="Mold Parameters"),
     Field("SplitAngle", "angle", "Angle", 1.0, low=0.0, high=89.0,
           shown=lambda o: getattr(o, "SplitFaces", False) and getattr(o, "SplitAt", "") == "At specified angle", box="Mold Parameters"),
     Field("Edges", "pick", "Parting Line", what=("Edge",), many=True,
           optional=True, box="Parting Lines", tip="Empty: found from the draft"),
     Field("AddSelectedEdges", "button", "Add selected edges", action=lambda o: add_selected_edges(o),
           tip="Adds the edges picked in the graphics area to the parting line", box="Parting Lines"),
     Field("SelectNextEdge", "button", "Select next edge", action=lambda o: next_edge(o),
           tip="Adds the edge that carries the parting line on from the last one", box="Parting Lines"),
     Field("ZoomToSelection", "button", "Zoom to selection", action=lambda o: zoom_to_edges(o),
           tip="Zooms to the parting line edges", box="Parting Lines"),
     Field("Info", "info", "Messages", "", box="Parting Lines")],
    _parting_line, needs_body=False)


def _line_of(obj, name="PartingLine", split=True):
    line = getattr(obj, name, None)
    if line is None:
        return None
    if getattr(line, "SWStyleKind", "") != PARTING_LINE.internal:
        raise RuntimeError("Pick a Parting Line feature")
    if split and not getattr(line, "UseForSplit", True):
        raise RuntimeError("The parting line is not for the core/cavity split: check Use for Core/Cavity Split on it")
    return line


# --------------------------------------------------------------------------- Shut-Off Surfaces
LOOP_TYPES = ("Contact", "Tangent", "No Fill")


def _overrides(obj):
    out = {}
    for item in (getattr(obj, "LoopTypes", "") or "").split(";"):
        if ":" in item:
            k, v = item.split(":", 1)
            if k.strip().isdigit() and v in LOOP_TYPES:
                out[int(k)] = v
    return out


def _set_prop(obj, name, value):
    if getattr(obj, name) != value:
        setattr(obj, name, value)


def _shut_off(obj, base):
    line = _line_of(obj)
    if line is None:
        return None, None
    solid = _solid_of(line.Part)
    pull = _pull(line)
    # Reset All Patch Types: a new choice there clears the loops set one by one
    reset = getattr(obj, "PatchType", "All Contact")
    default = reset.replace("All ", "")
    if getattr(obj, "LastReset", reset) != reset:
        _set_prop(obj, "LoopTypes", "")
        _set_prop(obj, "LoopType", default)
    _set_prop(obj, "LastReset", reset)
    picked = [e for _, e in sf.elements(obj, "Loops") if e.ShapeType == "Edge"]
    wires = []
    if picked:
        for group in Part.sortEdges(picked):
            wire = Part.Wire(group)
            if not wire.isClosed():
                raise RuntimeError("Each shut-off loop must be closed")
            wires.append(wire)
    else:
        # holes through the part: inner loops of the faces that look up the pull direction
        for face in solid.Faces:
            if not isinstance(face.Surface, Part.Plane) or face.normalAt(0, 0).dot(pull) < 0.99:
                continue
            for wire in face.Wires:
                if wire.isSame(face.OuterWire):
                    continue
                patch = Part.Face(wire)
                # Filter loops: only holes that go through (a ray down the pull from the patch leaves the part)
                probe = patch.CenterOfMass - pull * 1e-3
                if not getattr(obj, "FilterLoops", True) or not solid.isInside(probe, 1e-6, False):
                    wires.append(wire)
        wires += _side_loops(solid, pull, float(getattr(line, "DraftAngle", 1.0)))

    over = _overrides(obj)
    k = int(getattr(obj, "Loop", 1) or 1)
    if getattr(obj, "LastLoop", str(k)) not in ("", str(k)):
        _set_prop(obj, "LoopType", over.get(k, default))      # show the picked loop's type
    elif getattr(obj, "LoopType", default) != over.get(k, default) and 1 <= k <= len(wires):
        over[k] = obj.LoopType
        _set_prop(obj, "LoopTypes", ";".join("%d:%s" % (n, v) for n, v in sorted(over.items())))
    _set_prop(obj, "LastLoop", str(k))
    patches, notes, marks = [], [], []
    for n, wire in enumerate(wires, 1):
        kind = over.get(n, default)
        notes.append("%d %s" % (n, kind))
        marks.append((wire.CenterOfMass, "%d: %s" % (n, kind)))
        if kind != "No Fill":
            patches.append(_patch(solid, wire, "All " + kind))
    _callouts(obj, marks if getattr(obj, "ShowCallouts", False) else [])
    text = "%d loops, %d shut-off patches%s" % (len(wires), len(patches), (": " + ", ".join(notes)) if notes else "")
    _set_prop(obj, "Info", text)
    if not patches:
        return Part.makeCompound([]), None
    if getattr(obj, "Knit", True) and len(patches) > 1:
        return surf._sew(patches), None
    return Part.makeCompound(patches), None


def _side_loops(solid, pull, angle):
    ""



    from . import evaluate
    out = []
    faces = solid.Faces
    for face in faces:
        if len(face.Wires) < 2:
            continue
        if isinstance(face.Surface, Part.Plane) and abs(face.normalAt(*_mid_uv(face)).dot(pull)) > 0.99:
            continue        # a flat face square to the pull: _shut_off's own search has its holes
        # (a curved face that looks up the pull, a domed or cylindrical top, is searched here: a slot
        # through it is a shut-off loop as much as a hole through a flat top)
        if evaluate.classify_draft(face, pull, max(angle, 1e-3)) != "positive":
            continue
        for wire in face.Wires:
            if wire.isSame(face.OuterWire):
                continue
            if _through(faces, face, wire):
                out.append(wire)
    return out


def _mid_uv(face):
    u0, u1, v0, v1 = face.ParameterRange
    return 0.5 * (u0 + u1), 0.5 * (v0 + v1)


def _through(faces, face, wire):
    """The hole's walls (the faces round the loop) end in an inner loop of another face."""
    ring = list(wire.Edges)
    walls = [f for f in faces if not f.isSame(face) and any(e.isSame(r) for e in f.Edges for r in ring)]
    if not walls:
        return False
    far = [e for w in walls for e in w.Edges
           if not any(e.isSame(r) for r in ring) and sum(1 for x in walls for y in x.Edges if y.isSame(e)) < 2]
    for f in faces:
        if f.isSame(face) or any(f.isSame(w) for w in walls):
            continue
        for w in f.Wires:
            if w.isSame(f.OuterWire):
                continue
            if any(e.isSame(x) for e in w.Edges for x in far):
                return True
    return False


def _callouts(obj, marks):
    """Show callouts: a label at each loop with its number and patch type, drawn over the model."""
    if Gui is None or getattr(obj, "ViewObject", None) is None:
        return
    try:
        from pivy import coin
        root = obj.ViewObject.RootNode
    except Exception:
        return
    for i in reversed(range(root.getNumChildren())):
        if root.getChild(i).getName().getString() == "SWStyleCallouts":
            root.removeChild(i)
    if not marks:
        return
    group = coin.SoSeparator()
    group.setName("SWStyleCallouts")
    colour = coin.SoBaseColor()
    colour.rgb = (0.1, 0.1, 0.1)
    group.addChild(colour)
    for point, text in marks:
        sep = coin.SoSeparator()
        move = coin.SoTranslation()
        move.translation = (point.x, point.y, point.z)
        label = coin.SoText2()
        label.string = text
        sep.addChild(move)
        sep.addChild(label)
        group.addChild(sep)
    root.addChild(group)


def _patch(solid, wire, kind):
    """A shut-off patch over a loop: Contact (flat or filled) or Tangent to the faces round it."""
    edges = wire.OrderedEdges
    if kind == "All Tangent":
        owners = [surf._owner(solid.Faces, e) for e in edges]
        try:
            return surf.plate_face(edges, (), owners, "Tangent")
        except Exception as _fw_err:
            _fw_log("molds.py:569", _fw_err)
    try:
        return Part.Face(wire)
    except Exception:
        return Part.makeFilledFace(edges)


SHUT_OFF = sf.Spec(
    "SWStyle_ShutOffSurfaces", "Shut-Off Surfaces", "Shut-Off Surface",
    "Patches over the holes through the part, so the mould closes there.", "MOLD_SHUT_OFF_SURFACES",
    "Surface_Filling",
    [Field("PartingLine", "pick", "Parting Line", what="Object"),
     Field("Loops", "pick", "Edges", what=("Edge",), many=True, optional=True,
           tip="Empty: every through hole"),
     Field("PatchType", "radio", "Reset All Patch Types", "All Contact", values=["All Contact", "All Tangent", "All No Fill"]),
     Field("Loop", "int", "Loop", 1, low=1, high=999, tip="The loop whose patch type to set (its callout number)"),
     Field("LoopType", "radio", "Patch type of this loop", "Contact", values=list(LOOP_TYPES)),
     Field("LoopTypes", "info", "Loops set one by one", ""),
     Field("Knit", "bool", "Knit", True),
     Field("FilterLoops", "bool", "Filter loops", True),
     Field("ShowPreview", "bool", "Show preview", True),
     Field("ShowCallouts", "bool", "Show callouts", True),
     Field("LastReset", "info", "", "All Contact", shown=lambda o: False),
     Field("LastLoop", "info", "", "", shown=lambda o: False),
     Field("Info", "info", "Messages", "")],
    _shut_off, needs_body=False)


# --------------------------------------------------------------------------- Parting Surface
def _parting_surface(obj, base):
    line = _line_of(obj)
    if line is None:
        return None, None
    solid, edges = parting_edges(line)
    pull = _pull(line)
    distance = float(obj.Distance)
    if distance <= 0:
        raise RuntimeError("The distance must be more than 0")
    import math
    kind = getattr(obj, "Type", "Perpendicular to pull")
    angle = math.degrees(math.radians(float(getattr(obj, "Angle", 0.0))))
    # the flange runs out from the outer parting loop; holes inside it are the shut-offs' job
    try:
        loops = [Part.Wire(group) for group in Part.sortEdges(edges)]
        outer = max(loops, key=lambda w: w.BoundBox.DiagonalLength)
        edges = [e for e in edges if any(_same_edge(e, x) for x in outer.Edges)] or edges
    except Exception as _fw_err:
        _fw_log("molds.py:615", _fw_err)

    manual = []
    if getattr(obj, "ManualMode", False):
        manual = [e for _o, e in sf.elements(obj, "ManualEdges") if e.ShapeType == "Edge"]

    def way_at(edge, t):
        own = any(_same_edge(edge, m) for m in manual)
        p = edge.valueAt(t)
        tangent = edge.tangentAt(t)
        out = pull.cross(tangent)
        if out.Length < 1e-9:
            return None
        out.normalize()
        if solid.isInside(p + out * 1e-2, 1e-6, True):
            out = out * -1
        if kind != "Perpendicular to pull":
            way = _surface_way(solid, edge, t, out, kind)
            if way is not None:
                out = way
        tilt = float(getattr(obj, "ManualAngle", 0.0)) if own else angle
        if tilt:
            # tilt about the edge, towards the pull (Manual mode: a negative angle tilts away)
            rot = App.Rotation(tangent, abs(tilt))
            tilted, back = rot.multVec(out), rot.inverted().multVec(out)
            towards = tilted if tilted.dot(pull) >= back.dot(pull) else back
            out = towards if tilt > 0 else (back if towards is tilted else tilted)
        flip = obj.Reverse != (own and bool(getattr(obj, "ManualFlip", False)))
        return out * (-1 if flip else 1)

    faces = []
    for edge in edges:
        straight = type(edge.Curve).__name__ in ("Line", "LineSegment")
        if straight:
            out = way_at(edge, (edge.FirstParameter + edge.LastParameter) / 2.0)
            if out is not None:
                faces.extend(edge.extrude(out * distance).Faces)
            continue
        # a curved edge: each point goes out its own way, and a ruled face joins the two curves
        far = []
        for i in range(17):
            t = edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * i / 16.0
            out = way_at(edge, t)
            if out is None:
                break
            far.append(edge.valueAt(t) + out * distance)
        if len(far) < 17:
            continue
        curve = Part.BSplineCurve()
        curve.interpolate(far)
        try:
            faces.extend(Part.makeRuledSurface(edge, curve.toShape()).Faces)
        except Exception:
            continue
    if not faces:
        raise RuntimeError("The parting line has no edges across the pull direction")
    if getattr(obj, "Smoothing", "Sharp") == "Smooth":
        faces = _smooth_corners(faces, float(getattr(obj, "SmoothDistance", 1.0)))
    else:
        faces = _sharp_corners(faces)
    if not getattr(obj, "KnitAll", True):
        return Part.makeCompound(faces), None
    return surf._sew(faces), None


def _surface_way(solid, edge, t, out, kind):
    """Tangent to surface: the way the part's face beside the edge carries on; Normal to surface:
    that face's normal. The face picked is the one the flange leaves from (most along out)."""
    best = None
    for face in solid.Faces:
        if not any(_same_edge(edge, e) for e in face.Edges):
            continue
        try:
            if kind == "Tangent to surface":
                way = App.Vector(surf._out_at(face, edge, t))
            else:
                u, v = face.Surface.parameter(edge.valueAt(t))
                way = App.Vector(face.normalAt(u, v))
                if face.Orientation == "Reversed":
                    way = way * -1
        except Exception:
            continue
        if best is None or way.dot(out) > best.dot(out):
            best = way
    if best is None or best.Length < 1e-9:
        return None
    best.normalize()
    return best if best.dot(out) > -0.999 else None


def _sharp_corners(faces):
    ""


    out = list(faces)
    try:
        shell = surf._sew(faces)
        free = [e for e in shell.Edges if len(shell.ancestorsOfType(e, Part.Face)) == 1]
    except Exception:
        return out
    # a flange's side edge has one end on the parting line (two faces meet there) and one free end; the
    # parting line's own edges have both ends shared and are not sides
    sides = [e for e in free if sum(len(shell.ancestorsOfType(v, Part.Face)) >= 2 for v in e.Vertexes) == 1]

    def far_end(edge, p):
        ends = [v.Point for v in edge.Vertexes if v.Point.distanceToPoint(p) > 1e-6]
        return ends[0] if ends else None

    def outer_way(point, side):
        """The direction the flange's outer edge runs away from its corner point."""
        for e in free:
            if e.isSame(side) or not any(v.Point.distanceToPoint(point) < 1e-6 for v in e.Vertexes):
                continue
            if type(e.Curve).__name__ not in ("Line", "LineSegment"):
                return None
            other = far_end(e, point)
            if other is None:
                return None
            w = point - other
            w.normalize()
            return w
        return None

    used = set()
    for i, a in enumerate(sides):
        for j in range(i + 1, len(sides)):
            b = sides[j]
            if i in used or j in used:
                continue
            shared = [v for v in a.Vertexes for w in b.Vertexes if v.Point.distanceToPoint(w.Point) < 1e-6]
            if not shared:
                continue
            p = shared[0].Point
            fa, fb = far_end(a, p), far_end(b, p)
            if fa is None or fb is None or fa.distanceToPoint(fb) < 1e-6:
                continue
            try:
                if Part.Vertex((fa + fb) * 0.5).distToShape(shell)[0] < 1e-4:
                    continue            # an inside corner: the flanges overlap, nothing to fill
                ta, tb = outer_way(fa, a), outer_way(fb, b)
                if ta is None or tb is None:
                    continue
                # where the two outer edges, carried on past fa and fb, meet
                n = ta.cross(tb)
                if n.Length < 1e-9:
                    continue
                d = fb - fa
                s_ = d.cross(tb).dot(n) / n.dot(n)
                q = fa + ta * s_
                if (q - fb).cross(tb).Length > 1e-6 or s_ <= 0:
                    continue            # the edges do not meet ahead (a tilted or skew flange)
                quad = Part.makePolygon([p, fa, q, fb, p])
                out.append(Part.Face(quad))
                used.update((i, j))
            except Exception as _fw_err:
                _fw_log("molds.py:sharp corner", _fw_err)
                continue
    return out


def _smooth_corners(faces, distance):
    """Smooth: the gaps between neighbouring flanges at outside corners filled with a patch whose
    outer edge bulges out by the smoothing distance."""
    out = list(faces)
    try:
        shell = surf._sew(faces)
        free = [e for e in shell.Edges if len(shell.ancestorsOfType(e, Part.Face)) == 1]
    except Exception:
        return out
    # a corner gap is a pair of free side edges sharing a vertex on the parting line
    # a flange's side edge has one end on the parting line (two faces meet there) and one free end; the
    # parting line's own edges have both ends shared and are not sides
    sides = [e for e in free if sum(len(shell.ancestorsOfType(v, Part.Face)) >= 2 for v in e.Vertexes) == 1]
    used = set()
    for i, a in enumerate(sides):
        for j in range(i + 1, len(sides)):
            b = sides[j]
            if i in used or j in used:
                continue
            shared = [v for v in a.Vertexes for w in b.Vertexes if v.Point.distanceToPoint(w.Point) < 1e-6]
            if not shared:
                continue
            p = shared[0].Point
            fa = [v.Point for v in a.Vertexes if v.Point.distanceToPoint(p) > 1e-6]
            fb = [v.Point for v in b.Vertexes if v.Point.distanceToPoint(p) > 1e-6]
            if not fa or not fb or fa[0].distanceToPoint(fb[0]) < 1e-6:
                continue
            try:
                m = (fa[0] + fb[0]) * 0.5
                bulge = m - p
                bulge.normalize()
                arc = Part.Arc(fa[0], m + bulge * max(distance, 1e-3), fb[0]).toShape()
                out.append(Part.Face(Part.Wire([a, arc, b])))
                used.update((i, j))
            except Exception:
                try:
                    out.append(Part.Face(Part.makePolygon([p, fa[0], fb[0], p])))
                    used.update((i, j))
                except Exception:
                    continue
    return out


PARTING_SURFACE = sf.Spec(
    "SWStyle_PartingSurface", "Parting Surface", "Parting Surface",
    "A surface out from the parting line, square to the pull, that splits the mould block.",
    "MOLD_PARTING_SURFACE", "Part_Extrude",
    [Field("Type", "radio", "", "Perpendicular to pull",
           values=["Tangent to surface", "Normal to surface", "Perpendicular to pull"], box="Mold Parameters"),
     Field("PartingLine", "pick", "Parting Line", what="Object", box="Mold Parameters"),
     Field("Distance", "length", "Distance", 20.0, box="Parting Surface"),
     Field("Reverse", "bool", "Reverse alignment", False, tip="The surface goes inwards instead",
           box="Parting Surface"),
     Field("Angle", "angle", "Angle", 0.0, low=0.0, high=89.0, box="Parting Surface",
           shown=lambda o: getattr(o, "Type", "") in ("Tangent to surface", "Normal to surface")),
     Field("Smoothing", "radio", "Smoothing", "Sharp", values=["Sharp", "Smooth"], box="Parting Surface"),
     Field("SmoothDistance", "length", "Distance", 1.0, shown=lambda o: getattr(o, "Smoothing", "Sharp") == "Smooth",
           box="Parting Surface"),
     Field("KnitAll", "bool", "Knit all surfaces", True, box="Options"),
     Field("ShowPreview", "bool", "Show preview", True, box="Options"),
     Field("ManualMode", "bool", "Manual mode", False, box="Options",
           tip="Set the direction of chosen parting line edges yourself"),
     Field("ManualEdges", "pick", "Edges to set by hand", what=("Edge",), many=True, optional=True,
           shown=lambda o: getattr(o, "ManualMode", False), box="Options",
           tip="Parting line edges whose surface goes its own way"),
     Field("ManualAngle", "angle", "Their angle (towards the pull)", 0.0, low=-89.0, high=89.0,
           shown=lambda o: getattr(o, "ManualMode", False), box="Options"),
     Field("ManualFlip", "bool", "Flip their direction", False, shown=lambda o: getattr(o, "ManualMode", False),
           box="Options")],
    _parting_surface, needs_body=False)


# --------------------------------------------------------------------------- Tooling Split
def _frame(pull):
    return App.Placement(V(), App.Rotation(V(0, 0, 1), pull))


def _tooling_split(obj, base):
    line = _line_of(obj)
    psurf = obj.PartingSurface
    if line is None or psurf is None:
        return None, None
    solid = _solid_of(line.Part)
    pull = _pull(line)
    place = _frame(pull)
    inverse = place.inverse()
    local = solid.transformed(inverse.toMatrix())
    box = local.BoundBox
    _, edges = parting_edges(line)
    level = sum(inverse.multVec(e.CenterOfMass).z for e in edges) / max(len(edges), 1)
    margin = float(obj.Margin)
    up, down = float(obj.DepthUp), float(obj.DepthDown)
    if margin <= 0 or up <= 0 or down <= 0:
        raise RuntimeError("Block margin and depths must be more than 0")
    plane = _sketch_level(obj, inverse)
    if plane is None:       # no block sketch: the depths reach past the part's own height
        top = max(box.ZMax - level, 0) + up
        bottom = max(level - box.ZMin, 0) + down
    else:
        up, down = _auto_depths(obj, up, down, box.ZMax - plane, plane - box.ZMin)
        top, bottom = plane - level + up, level - plane + down
        if top < box.ZMax - level - 1e-6 or bottom < level - box.ZMin - 1e-6:
            raise RuntimeError("The block does not take in the whole part: make Depth in Direction 1 at least "
                               "%.2f mm and Depth in Direction 2 at least %.2f mm"
                               % (box.ZMax - plane, plane - box.ZMin))
    outline = _block_outline(obj, place, inverse, box, margin, level)
    block = _drafted_block(outline, level, top, bottom,
                           float(obj.Draft1) if getattr(obj, "DraftOn1", False) else 0.0,
                           float(obj.Draft2) if getattr(obj, "DraftOn2", False) else 0.0)
    block = block.transformed(place.toMatrix())
    knives = list(Part.getShape(psurf).Faces)
    if obj.ShutOff is not None:
        knives.extend(Part.getShape(obj.ShutOff).Faces)
    # the parting surface must reach the block's sides: carry it on as a flat plane at the parting level
    plane_point = place.multVec(V(0, 0, level))
    big = Part.Plane(plane_point, pull).toShape(-1e4, 1e4, -1e4, 1e4)
    try:
        # only outside the part's outer parting loop: inside it the shut-offs decide
        loops = [Part.Wire(group) for group in Part.sortEdges(edges)]
        outer = max((w for w in loops if w.isClosed()), key=lambda w: w.BoundBox.DiagonalLength)
        inside = Part.Face(outer).extrude(pull * 1e-2)
        inside.translate(pull * -5e-3)
        big = big.cut(inside).Faces[0] if big.cut(inside).Faces else big
    except Exception as _fw_err:
        _fw_log("molds.py:821", _fw_err)
    if getattr(obj, "Interlock", False):
        lock = _interlock(psurf, place, inverse, level, float(obj.InterlockAngle), min(up, down) * 0.5)
        if lock is not None:
            band, lower = lock
            knives.append(band)
            big = lower
    mould = block.cut(solid)
    from BOPTools import SplitAPI

    def sides(cutters):
        try:
            pieces = SplitAPI.slice(mould, cutters, "Split", 1e-5).Solids
        except Exception:
            return [], []
        # the core is what stands on the block's bottom, the cavity what hangs from its top: a
        # cup's core reaches up inside it, so its centre of mass can be above the parting level
        low, high = level - bottom, level + top
        core, cavity = [], []
        for p in pieces:
            z = p.transformed(inverse.toMatrix()).BoundBox
            if z.ZMin < low + 1e-3 and z.ZMax < high - 1e-3:
                core.append(p)
            elif z.ZMax > high - 1e-3 and z.ZMin > low + 1e-3:
                cavity.append(p)
            elif inverse.multVec(p.CenterOfMass).z < level:
                core.append(p)
            else:
                cavity.append(p)
        return core, cavity

    core, cavity = sides(knives)
    if not core or not cavity:
        # the surfaces do not reach the block sides: carry them on as a flat plane at the parting level
        core, cavity = sides(knives + [big])
    if not core or not cavity:
        raise RuntimeError("The parting surface does not split the block in two")
    fuse = lambda ps: ps[0] if len(ps) == 1 else ps[0].fuse(ps[1:]).removeSplitter()
    core, cavity = fuse(core), fuse(cavity)
    gap = float(obj.Separation)
    if gap > 0:
        cavity.translate(pull * gap)
        core.translate(pull * -gap)
    show = obj.Show
    kept = [core] if show == "Core" else [cavity] if show == "Cavity" else [core, cavity]
    text = "Core %.0f mm3, cavity %.0f mm3" % (core.Volume, cavity.Volume)
    if obj.Info != text:
        obj.Info = text
    return Part.makeCompound(kept), None


def _auto_depths(obj, up, down, need_up, need_down):
    ""


    if "SWAutoDepths" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "SWAutoDepths", "Tooling Split", "Depths filled in from the part")
        obj.setEditorMode("SWAutoDepths", 2)
    try:
        last = [float(x) for x in obj.SWAutoDepths.split(",")]
    except ValueError:
        last = [15.0, 15.0]
    out = []
    for prop, value, need, before in (("DepthUp", up, need_up, last[0]), ("DepthDown", down, need_down, last[1])):
        if abs(value - before) < 1e-6 and value < need - 1e-6:
            value = round(need + 10.0, 2)
            setattr(obj, prop, value)
        out.append(value)
    text = "%g,%g" % tuple(out)
    if obj.SWAutoDepths != text:
        obj.SWAutoDepths = text
    return out


def _sketch_level(obj, inverse):
    """Height of the block sketch's plane along the pull (None when there is no block sketch)."""
    sketch = getattr(obj, "BlockSketch", None)
    if sketch is None:
        return None
    wires = [w for w in Part.getShape(sketch).Wires if w.isClosed()]
    if not wires:
        return None
    flat = max(wires, key=lambda x: x.BoundBox.DiagonalLength).copy()
    flat.transformShape(inverse.toMatrix())
    return flat.BoundBox.ZMin


def _block_outline(obj, place, inverse, box, margin, level):
    ""

    sketch = getattr(obj, "BlockSketch", None)
    if sketch is not None:
        wires = [w for w in Part.getShape(sketch).Wires if w.isClosed()]
        if not wires:
            raise RuntimeError("The block sketch needs a closed profile")
        flat = max(wires, key=lambda x: x.BoundBox.DiagonalLength).copy()
        flat.transformShape(inverse.toMatrix())
        if flat.BoundBox.ZLength > 1e-5:
            raise RuntimeError("The block sketch must be on a plane square to the direction of pull")
        flat.translate(V(0, 0, level - flat.BoundBox.ZMin))
        foot = Part.makePlane(box.XLength, box.YLength, V(box.XMin, box.YMin, level))
        if Part.Face(flat).common(foot).Area < foot.Area * 0.999:
            raise RuntimeError("The block sketch must go round the part")
        return flat
    x0, y0, x1, y1 = box.XMin - margin, box.YMin - margin, box.XMax + margin, box.YMax + margin
    return Part.makePolygon([V(x0, y0, level), V(x1, y0, level), V(x1, y1, level), V(x0, y1, level), V(x0, y0, level)])


def _interlock(psurf, place, inverse, level, angle, height):
    """Interlock surface: round the parting surface's outer edge a band drops towards the core,
    flaring out by the angle, and the split carries on flat below it, so the core and the cavity
    key into each other. (band, the flat surface past it) in world terms, or None."""
    import math
    try:
        shell = Part.getShape(psurf)
        free = [e for e in shell.Edges if len(shell.ancestorsOfType(e, Part.Face)) == 1]
        loops = [Part.Wire(g) for g in Part.sortEdges(free)]
        outer = max((w for w in loops if w.isClosed()), key=lambda w: w.BoundBox.DiagonalLength)
    except Exception:
        return None
    local = outer.copy()
    local.transformShape(inverse.toMatrix())
    pts = [V(p.x, p.y, level) for p in local.discretize(Number=max(8, 6 * len(local.Edges)))]
    flat = Part.makePolygon(pts + [pts[0]]) if (pts[0] - pts[-1]).Length > 1e-6 else Part.makePolygon(pts)
    far = flat.makeOffset2D(math.tan(math.radians(max(angle, 0.1))) * height, 2)
    far.translate(V(0, 0, -height))
    band = Part.makeLoft([flat, far], False, True)
    plane = Part.Plane(V(0, 0, level - height), V(0, 0, 1)).toShape(-1e4, 1e4, -1e4, 1e4)
    try:
        plane = plane.cut(Part.Face(far).extrude(V(0, 0, 1e-2)).translated(V(0, 0, -5e-3))).Faces[0]
    except Exception as _fw_err:
        _fw_log("molds.py:952", _fw_err)
    return band.transformed(place.toMatrix()), plane.transformed(place.toMatrix())


def _drafted_block(outline, level, top, bottom, draft1, draft2):
    ""

    import math

    def side(height, draft, sign):
        far = outline.copy()
        if draft > 0:
            far = far.makeOffset2D(-math.tan(math.radians(draft)) * height, 2)
        far.translate(V(0, 0, sign * height))
        return Part.makeLoft([outline, far], True, True)

    return side(top, draft1, 1).fuse(side(bottom, draft2, -1)).removeSplitter()


TOOLING_SPLIT = sf.Spec(
    "SWStyle_ToolingSplit", "Tooling Split", "Tooling Split",
    "A block round the part, cut into the core and the cavity by the parting and shut-off surfaces.",
    "MOLD_TOOLING_SPLIT", "Part_BooleanFragments",

    [Field("BlockSketch", "pick", "Block profile sketch", what="Object",
           optional=True, box="Block Size", tip="Empty: the margin round the part"),
     Field("Margin", "length", "Block margin", 15.0, tip="Round the part",
           shown=lambda o: getattr(o, "BlockSketch", None) is None, box="Block Size"),
     Field("DepthUp", "length", "Depth in direction 1", 15.0, box="Block Size", tip="Cavity side"),
     Field("DraftOn1", "bool", "Draft On/Off", False, box="Block Size", tip="Direction 1"),
     Field("Draft1", "angle", "Draft angle", 1.0, low=0.0, high=45.0, shown=lambda o: getattr(o, "DraftOn1", False), box="Block Size"),
     Field("DepthDown", "length", "Depth in direction 2", 15.0, box="Block Size", tip="Core side"),
     Field("DraftOn2", "bool", "Draft On/Off", False, box="Block Size", tip="Direction 2"),
     Field("Draft2", "angle", "Draft angle", 1.0, low=0.0, high=45.0, shown=lambda o: getattr(o, "DraftOn2", False), box="Block Size"),
     Field("Interlock", "bool", "Interlock surface", False, box="Block Size"),
     Field("InterlockAngle", "angle", "Interlock angle", 5.0, low=0.1, high=45.0,
           shown=lambda o: getattr(o, "Interlock", False), box="Block Size"),
     Field("PartingLine", "pick", "Parting Line", what="Object", box="Parting Surface"),
     Field("PartingSurface", "pick", "Parting Surface", what="Object", box="Parting Surface"),
     Field("ShutOff", "pick", "Shut-Off Surfaces", what="Object", optional=True, box="Parting Surface"),
     Field("Show", "enum", "Show", "Core and cavity", values=["Core and cavity", "Core", "Cavity"], box="Options"),
     Field("Separation", "length", "Separate core and cavity by", 0.0, box="Options"),
     Field("Info", "info", "Messages", "", box="Options")],
    _tooling_split, needs_body=False, first_pick="PartingLine")

# --------------------------------------------------------------------------- Core
def _core(obj, base):
    """Pulls a side core (a slider) out of the tooling: the sketch profile carried through the core
    or cavity block becomes its own body, and the block keeps the hole it leaves."""
    split, sketch = obj.ToolingSplit, obj.Sketch
    if split is None or sketch is None:
        return None, None
    tooling = Part.getShape(split)
    if tooling.isNull() or not tooling.Solids:
        raise RuntimeError("Pick a Tooling Split")
    wires = [w for w in Part.getShape(sketch).Wires if w.isClosed()]
    if not wires:
        raise RuntimeError("The sketch needs a closed profile")
    profile = Part.Face(wires[0]) if len(wires) == 1 else Part.makeFace(wires, "Part::FaceMakerBullseye")
    one, two = float(obj.Depth), float(obj.Depth2)
    if one <= 0 and two <= 0:
        raise RuntimeError("The extract depth must be more than 0")

    import math
    draft = float(obj.DraftAngle) if getattr(obj, "DraftOn", False) else 0.0
    draft2 = float(getattr(obj, "DraftAngle2", 0.0)) if getattr(obj, "DraftOn2", False) else 0.0
    out1 = -1.0 if getattr(obj, "DraftOutward", False) else 1.0
    out2 = -1.0 if getattr(obj, "DraftOutward2", False) else 1.0

    def leg(normal, length, angle, outward):
        # one direction of the extract: the profile carried length along normal, narrowing by the
        # draft as it goes (Draft outward: widening)
        if length <= 0:
            return None
        if angle <= 0:
            return profile.extrude(normal * length)
        near = profile.OuterWire
        far = near.makeOffset2D(-outward * math.tan(math.radians(angle)) * length, 2)
        far.translate(normal * length)
        return Part.makeLoft([near, far], True, True)

    def prism_along(normal):
        legs = [x for x in (leg(normal, one, draft, out1), leg(-normal, two, draft2, out2)) if x is not None]
        return legs[0] if len(legs) == 1 else legs[0].fuse(legs[1]).removeSplitter()


    # Extract Direction (an edge, a plane or a planar face) sets the direction instead of the sketch normal
    if sf.elements(obj, "ExtractDirection"):
        normal = _pull(obj, "ExtractDirection")      # Reverse is in it
    else:
        normal = profile.normalAt(0, 0)
        overlap = lambda n: sum(s.common(prism_along(n)).Volume for s in tooling.Solids)
        if overlap(-normal) > overlap(normal):
            normal = -normal
        if obj.Reverse:
            normal = -normal
    prism = prism_along(normal)
    cores, kept = [], []
    for solid in tooling.Solids:
        piece = solid.common(prism)
        if not piece.isNull() and piece.Volume > 1e-6:
            cores.extend(piece.Solids)
            kept.extend(solid.cut(prism).Solids)
        else:
            kept.append(solid)
    if not cores:
        raise RuntimeError("The sketch profile does not reach the tooling")
    if getattr(obj, "CapEnds", True):
        # Cap ends: the core runs the whole extract depth, closed flat at its end, even past the block
        cores = list(prism.Solids)
    text = "Core %.0f mm3 pulled out of %d tooling bodies" % (sum(c.Volume for c in cores), len(tooling.Solids))
    if obj.Info != text:
        obj.Info = text
    for source in (split, sketch):
        try:
            if source.ViewObject is not None:
                source.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("molds.py:1069", _fw_err)
    return Part.makeCompound(kept + cores), None


CORE = sf.Spec(
    "SWStyle_Core", "Core", "Core",
    "Pulls a side core out of the core or cavity block along a sketch profile.",
    "MOLD_CORE", "Part_Extrude",
    [Field("ToolingSplit", "pick", "Tooling body", what="Object", tip="The Tooling Split body"),
     Field("Sketch", "pick", "Sketch", what="Object", tip="A closed profile on a tooling face"),
     Field("ExtractDirection", "pick", "Extract Direction",
           what=("Edge", "Face", ""), optional=True, tip="An edge or a plane; empty: normal to the sketch"),
     Field("Depth", "length", "Direction 1 depth", 20.0),
     Field("Reverse", "bool", "Reverse direction", False),
     Field("DraftOn", "bool", "Draft On/Off", False),
     Field("DraftAngle", "angle", "Draft angle", 1.0, low=0.0, high=45.0, shown=lambda o: getattr(o, "DraftOn", False)),
     Field("DraftOutward", "bool", "Draft outward", False, shown=lambda o: getattr(o, "DraftOn", False)),
     Field("Depth2", "length", "Direction 2 depth", 0.0),
     Field("DraftOn2", "bool", "Direction 2 Draft On/Off", False, shown=lambda o: float(getattr(o, "Depth2", 0)) > 0),
     Field("DraftAngle2", "angle", "Direction 2 draft angle", 1.0, low=0.0, high=45.0,
           shown=lambda o: float(getattr(o, "Depth2", 0)) > 0 and getattr(o, "DraftOn2", False)),
     Field("DraftOutward2", "bool", "Direction 2 draft outward", False,
           shown=lambda o: float(getattr(o, "Depth2", 0)) > 0 and getattr(o, "DraftOn2", False)),
     Field("CapEnds", "bool", "Cap ends", True),
     Field("Info", "info", "Messages", "")],
    _core, needs_body=False)


# --------------------------------------------------------------------------- Insert Mold Folders
FOLDERS = ("Surface Bodies", "Cavity Surface Bodies", "Core Surface Bodies", "Parting Surface Bodies")


class MoldFolders:
    def GetResources(self):
        return {"MenuText": "Insert Mold Folders", "ToolTip": "Adds the folders for the mould's surface bodies.",
                "Pixmap": "folder"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        doc.openTransaction("Insert Mold Folders")
        have = set(o.Label for o in doc.Objects if o.TypeId == "App::DocumentObjectGroup")
        parent = None
        for label in FOLDERS:
            if label in have:
                continue
            group = doc.addObject("App::DocumentObjectGroup", label.replace(" ", ""))
            group.Label = label
            if parent is None:
                parent = group
            else:
                parent.addObject(group)
        doc.commitTransaction()
        doc.recompute()


ALL = [PARTING_LINE, SHUT_OFF, PARTING_SURFACE, TOOLING_SPLIT, CORE]


class MoldCommand(surf.Command):
    ""



    KINDS = {"PartingLine": "PARTING_LINE", "PartingSurface": "PARTING_SURFACE", "ShutOff": "SHUT_OFF",
             "ToolingSplit": "TOOLING_SPLIT"}

    def Activated(self):
        doc = App.ActiveDocument
        spec = self.spec
        picked = []
        for sel in Gui.Selection.getSelectionEx("", 0):
            picked.append(sel.Object)
        picks = {}
        rest = []
        kinds = {name: globals()[k].internal for name, k in self.KINDS.items()}
        fields = [f for f in spec.fields if f.kind == "pick" and f.what == "Object"]
        for o in picked:
            kind = getattr(o, "SWStyleKind", "")
            box = next((f.name for f in fields if kinds.get(f.name) == kind and f.name not in picks), None)
            if box:
                picks[box] = o
            else:
                rest.append(o)
        for f in fields:
            if f.name in picks or f.name not in kinds or doc is None:
                continue
            found = [o for o in doc.Objects if getattr(o, "SWStyleKind", "") == kinds[f.name]]
            if found:
                picks[f.name] = found[-1]       # the newest one, as the folders list them
        free = [f for f in fields if f.name not in picks]
        for f, o in zip(free, rest):
            picks[f.name] = o
        if spec is PARTING_LINE and "Part" not in picks and doc is not None:

            # box starts filled, so OK works without a click in it (video follow-along, mold tools)
            bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body" and not o.Shape.isNull() and o.Shape.Solids]
            if len(bodies) == 1:
                picks["Part"] = bodies[0]
        surf.make(spec, picks=picks)


def register():
    for spec in ALL:
        try:
            if spec.command not in Gui.listCommands():
                Gui.addCommand(spec.command, MoldCommand(spec))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s command not added (%s)\n" % (spec.title, error))
    if "SWStyle_MoldFolders" not in Gui.listCommands():
        Gui.addCommand("SWStyle_MoldFolders", MoldFolders())
