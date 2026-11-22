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

from . import convertentities

V = App.Vector
TITLE = "Close Sketch to Model"
_TOL = 1e-5


def _local(sketch):
    return sketch.getGlobalPlacement().inverse()


def open_ends(sketch):
    """[(geo, pos, point)] of the profile ends no other entity meets."""
    ends = []
    for i, g in enumerate(sketch.Geometry):
        if sketch.getConstruction(i) or not hasattr(g, "StartPoint") or g.TypeId == "Part::GeomPoint":
            continue
        try:
            if g.isClosed():
                continue
        except Exception as _fw_err:
            _fw_log("closetomodel.py:49", _fw_err)
        ends.append((i, 1, g.StartPoint))
        ends.append((i, 2, g.EndPoint))
    return [e for e in ends
            if not any(o is not e and (o[2] - e[2]).Length < _TOL for o in ends)]


def _sources(sketch):
    """Objects whose flat faces may close the profile: the sketch's support first."""
    out = []
    for obj, _subs in getattr(sketch, "AttachmentSupport", None) or []:
        if obj not in out:
            out.append(obj)
    mine = set(o.Name for o in sketch.InListRecursive) | {sketch.Name}
    body = None
    try:
        body = sketch.getParentGeoFeatureGroup()
    except Exception as _fw_err:
        _fw_log("closetomodel.py:67", _fw_err)
    if body is not None and body.isDerivedFrom("PartDesign::Body"):
        feature = getattr(sketch, "BaseFeature", None)
        for obj in ([feature] if feature is not None else []) + [body.Tip]:
            if obj is not None and obj not in out and obj.Name not in mine:
                out.append(obj)
    for obj in sketch.Document.Objects:
        shape = getattr(obj, "Shape", None)
        if obj in out or obj.Name in mine or shape is None or shape.isNull() or not shape.Faces:
            continue
        if obj.isDerivedFrom("PartDesign::Body") or not getattr(obj, "Visibility", False):
            continue
        out.append(obj)
    return [o for o in out if getattr(o, "Shape", None) is not None and not o.Shape.isNull()]


def _in_plane(face, sketch):
    """A flat face lying in the sketch's plane."""
    try:
        if face.Surface.__class__.__name__ != "Plane":
            return False
        pl = sketch.getGlobalPlacement()
        n = pl.Rotation.multVec(V(0, 0, 1))
        if abs(abs(face.normalAt(0, 0).dot(n)) - 1.0) > 1e-6:
            return False
        return abs((face.Vertexes[0].Point - pl.Base).dot(n)) < 1e-6
    except Exception as _fw_err:
        _fw_log("closetomodel.py:95", _fw_err)
        return False


def _walk(wire):
    """The wire's edges in order round it: [(edge, t at its start, t at its end)]."""
    edges = list(wire.OrderedEdges)
    out = []
    at = None
    for k, e in enumerate(edges):
        a, b = e.FirstParameter, e.LastParameter
        pa, pb = e.valueAt(a), e.valueAt(b)
        if at is None:
            nxt = edges[(k + 1) % len(edges)] if len(edges) > 1 else e
            ends = [v.Point for v in nxt.Vertexes]
            forward = len(edges) == 1 or any((pb - q).Length < 1e-6 for q in ends)
        else:
            forward = (pa - at).Length <= (pb - at).Length
        out.append((e, a, b) if forward else (e, b, a))
        at = pb if forward else pa
    return out


def _param(edge, t0, t1, point):
    """Where point lies along edge, as a fraction from t0 to t1; None when it is off the edge."""
    import Part
    if edge.distToShape(Part.Vertex(point))[0] > 1e-5:
        return None
    t = edge.Curve.parameter(point)
    lo, hi = min(t0, t1), max(t0, t1)
    if edge.Curve.isPeriodic():
        period = edge.Curve.period()
        while t < lo - 1e-9:
            t += period
        while t > hi + 1e-9:
            t -= period
    if abs(t1 - t0) < 1e-12:
        return 0.0
    return min(1.0, max(0.0, (t - t0) / (t1 - t0)))


def _path(walk, start, end):
    """Pieces [(edge, t from, t to)] round the loop from start (k, fraction) to end."""
    n = len(walk)
    k1, f1 = start
    k2, f2 = end

    def at(k, f):
        e, t0, t1 = walk[k]
        return t0 + (t1 - t0) * f

    pieces = []
    if k1 == k2 and f2 > f1 + 1e-9:
        return [(walk[k1][0], at(k1, f1), at(k1, f2))]
    if n == 1:
        # one closed edge (a circle): round it from start to end, across its seam
        e, t0, t1 = walk[0]
        a, b = at(0, f1), at(0, f2)
        b += (t1 - t0)
        return [(e, a, b)]
    if f1 < 1 - 1e-9:
        pieces.append((walk[k1][0], at(k1, f1), walk[k1][2]))
    k = (k1 + 1) % n
    guard = 0
    while k != k2 and guard <= n:
        pieces.append(walk[k])
        k = (k + 1) % n
        guard += 1
    if f2 > 1e-9:
        pieces.append((walk[k2][0], walk[k2][1], at(k2, f2)))
    return pieces


def _length(pieces):
    import Part
    total = 0.0
    for e, a, b in pieces:
        try:
            total += Part.Edge(e.Curve, min(a, b), max(a, b)).Length
        except Exception:
            total += e.Length
    return total


def plan(sketch, reverse=False):
    """(object, the two ends [(geo, pos, point)], pieces [(edge, t from, t to)]) closing the
    sketch's open profile; ValueError says why it cannot."""
    ends = open_ends(sketch)
    if not ends:
        raise ValueError("The sketch has no open profile to close.")
    if len(ends) != 2:
        raise ValueError("Close Sketch to Model closes one open profile; this sketch has %d open ends."
                         % len(ends))
    place = sketch.getGlobalPlacement()
    world = [place.multVec(p) for _g, _pos, p in ends]
    for obj in _sources(sketch):
        for face in obj.Shape.Faces:
            if not _in_plane(face, sketch):
                continue
            for wire in face.Wires:
                walk = _walk(wire)
                spots = []
                for p in world:
                    spot = None
                    for k, (e, t0, t1) in enumerate(walk):
                        f = _param(e, t0, t1, p)
                        if f is not None:
                            spot = (k, f)
                            break
                    spots.append(spot)
                if None in spots:
                    continue
                one = _path(walk, spots[0], spots[1])
                other = _path(walk, spots[1], spots[0])
                short, long_ = (one, other) if _length(one) <= _length(other) else (other, one)
                pieces = long_ if reverse else short
                if pieces is short and _length(one) > _length(other):
                    ends = [ends[1], ends[0]]
                elif pieces is long_ and _length(one) <= _length(other):
                    ends = [ends[1], ends[0]]
                return obj, ends, pieces
    raise ValueError("The profile's ends must lie on the edges of a model face in the sketch's plane.")


def _add_checked(sketch, constraint):
    """Adds constraint unless it makes the sketch redundant or conflicting; its index or None."""
    sketch.solve()
    before = len(sketch.RedundantConstraints) + len(sketch.ConflictingConstraints)
    k = sketch.addConstraint(constraint)
    sketch.solve()
    if len(sketch.RedundantConstraints) + len(sketch.ConflictingConstraints) > before:
        sketch.delConstraint(k)
        sketch.solve()
        return None
    return k


def _external(sketch, obj, name):
    """The external geometry index of obj's element name, added when the sketch has none."""
    k = 2                   # ExternalGeo starts with the sketch's own H and V axes
    for o, subs in sketch.ExternalGeometry:
        for sub in subs:
            if o == obj and sub == name:
                return -(k + 1)
            k += 1
    before = len(sketch.ExternalGeo)
    sketch.addExternal(obj.Name, name)
    sketch.solve()
    if len(sketch.ExternalGeo) <= before:
        return None
    return -(before + 1)


def close(sketch, reverse=False):
    """Closes the open profile with the model's edges; the new geometry indexes."""
    import Part
    import Sketcher
    C = Sketcher.Constraint
    obj, ends, pieces = plan(sketch, reverse)
    inv = _local(sketch)
    z = V(0, 0, 1)
    new = []
    joins = []              # (new geo, pos, point) to tie to the profile's ends
    for e, a, b in pieces:
        name = convertentities._edge_name(obj.Shape, e)
        if name is None:
            raise ValueError("A closing edge is not an edge of %s." % obj.Label)
        lo, hi = e.FirstParameter, e.LastParameter
        whole = abs(min(a, b) - lo) < 1e-9 and abs(max(a, b) - hi) < 1e-9
        if whole:
            made = convertentities.convert(sketch, [(obj, name)])
            for g in made:
                geo = sketch.Geometry[g]
                joins += [(g, 1, geo.StartPoint), (g, 2, geo.EndPoint)]
            new += made
            continue
        gid = _external(sketch, obj, name)
        if gid is None:
            raise ValueError("FreeCAD could not take %s.%s into the sketch." % (obj.Label, name))
        ext = sketch.ExternalGeo[-gid - 1]
        pa, pb = inv.multVec(e.valueAt(a)), inv.multVec(e.valueAt(b))
        pa.z = pb.z = 0
        kind = type(ext).__name__
        if kind == "LineSegment":
            g = sketch.addGeometry(Part.LineSegment(pa, pb))
            points = {1: pa, 2: pb}
        elif kind in ("ArcOfCircle", "Circle"):
            c = V(ext.Center.x, ext.Center.y, 0)
            mid = inv.multVec(e.valueAt((a + b) / 2))
            ang = lambda p: math.atan2(p.y - c.y, p.x - c.x)
            s, t, m = ang(pa), ang(pb), ang(mid)
            span = lambda x, y: (y - x) % (2 * math.pi)
            if span(s, m) < span(s, t):
                lo_p, hi_p, start, finish = pa, pb, s, s + span(s, t)
            else:
                lo_p, hi_p, start, finish = pb, pa, t, t + span(t, s)
            g = sketch.addGeometry(Part.ArcOfCircle(Part.Circle(c, z, ext.Radius), start, finish))
            sketch.addConstraint(C("Coincident", g, 3, gid, 3))
            points = {1: lo_p, 2: hi_p}
        else:
            raise ValueError("Only straight and round model edges can be cut to close the profile.")
        for pos, p in points.items():
            at_vertex = False
            ext_ends = ((1, ext.StartPoint), (2, ext.EndPoint)) if hasattr(ext, "StartPoint") else ()
            for epos, ep in ext_ends:
                if (V(ep.x, ep.y, 0) - p).Length < 1e-6:
                    sketch.addConstraint(C("Coincident", g, pos, gid, epos))
                    at_vertex = True
                    break
            if not at_vertex:
                _add_checked(sketch, C("PointOnObject", g, pos, gid))
            joins.append((g, pos, p))
        new.append(g)
    # the closing entities meet the profile's ends
    for geo, pos, p in ends:
        for g, gpos, gp in joins:
            if (gp - p).Length < 1e-6:
                _add_checked(sketch, C("Coincident", geo, pos, g, gpos))
                break
    sketch.solve()
    return new


def _page_class():
    from PySide import QtCore, QtWidgets
    from . import sketchtoolpm

    class ClosePage(sketchtoolpm.ToolPage):
        TITLE = TITLE
        ICON = "SKETCH_CLOSE_SKETCH_TO_MODEL"
        PIXMAP = "Sketcher_CreatePolyline"
        TRANSACTION = TITLE

        def build(self):
            g = self.group("Close Sketch to Model")
            text = QtWidgets.QLabel("The open profile is closed along the model's edges.", g.body)
            text.setWordWrap(True)
            g.content.addWidget(text)
            self.reverse = QtWidgets.QCheckBox("Reverse direction of closure", g.body)
            self.reverse.setObjectName("SWCloseReverse")
            self.reverse.toggled.connect(self.changed)
            g.content.addWidget(self.reverse)
            # after the command returns: FreeCAD commits what a command opens while it runs
            QtCore.QTimer.singleShot(0, self.changed)

        def changed(self, *args):
            if not sketchtoolpm.alive(self):
                return
            self.undo_work()
            self.begin()
            try:
                close(self.sketch, self.reverse.isChecked())
            except Exception as error:
                self.undo_work()
                self.show_note(str(error), True)
                return
            sketchtoolpm._refresh(self.sketch)
            self.show_note("")

    return ClosePage


class _Command:
    def GetResources(self):
        return {"Pixmap": "Sketcher_CreatePolyline", "MenuText": TITLE,
                "ToolTip": "Closes an open profile with the model's edges", "CmdType": "ForEdit"}

    def IsActive(self):
        from . import contextbar
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        from . import contextbar, sketchtoolpm
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(_page_class()(sketch))


def register():
    import FreeCADGui as Gui
    try:
        if "SWStyle_CloseSketchToModel" not in Gui.listCommands():
            Gui.addCommand("SWStyle_CloseSketchToModel", _Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Close Sketch to Model command not added (%s)\n" % error)
