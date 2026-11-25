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
import FreeCADGui as Gui
import Part
import Sketcher

from . import inference as I
from . import guides as G
from . import snap as S

VERTEX, VERTEX_NO_TANGENCY, CURVE = "vertex", "vertex_no_tangency", "curve"
START_OR_END = (I.START, I.END)


_NAMES = {"Symmetric": "Midpoint", "MidpointOf": "Midpoint", "PointOnObject": "On edge"}


class Suggestion:
    __slots__ = ("type", "geo", "pos")

    def __init__(self, type, geo=I.GEO_UNDEF, pos=I.NONE):
        self.type, self.geo, self.pos = type, geo, pos

    def __repr__(self):
        return "Suggestion(%s, %s, %s)" % (self.type, self.geo, self.pos)

    def key(self):
        return (self.type, self.geo, self.pos)


GENERAL_GROUP = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"
_box_pending = [False]


def _quadrant_at(snapper, geos, position, tol=1e-6):
    """(geo, centre) when position is a quadrant of one of geos' circles or arcs, else None."""
    for geo in geos:
        g = snapper.geometry(geo)
        if not isinstance(g, (Part.Circle, Part.ArcOfCircle)):
            continue
        c = I.point_of(g, I.MID)
        dx, dy = position[0] - c[0], position[1] - c[1]
        r = g.Radius
        if (abs(dx) < tol and abs(abs(dy) - r) < tol) or (abs(dy) < tol and abs(abs(dx) - r) < tol):
            return geo, c
    return None


def ask_about_skipped():
    ""



    if not App.GuiUp:
        return
    try:
        if not App.ParamGet(GENERAL_GROUP).GetBool("WarnAutoRelationsOverDefine", True):
            return
    except Exception:
        return
    if _box_pending[0]:
        return
    _box_pending[0] = True
    from PySide import QtCore, QtWidgets
    import FreeCADGui as Gui

    def show():
        _box_pending[0] = False
        main = Gui.getMainWindow()
        if main is None or main.findChild(QtWidgets.QMessageBox, "AutoRelationsOverDefine") is not None:
            return
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "Automatic Relations",
                                    "The automatic relations inferred by this operation would over define "
                                    "the sketch. They will not be added.", QtWidgets.QMessageBox.Ok, main)
        box.setObjectName("AutoRelationsOverDefine")
        check = QtWidgets.QCheckBox("Don't show again")
        box.setCheckBox(check)
        box.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        box.setWindowModality(QtCore.Qt.NonModal)
        box.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)  # the pointer and keys stay with the sketch

        def finished(_result):
            if check.isChecked():
                App.ParamGet(GENERAL_GROUP).SetBool("WarnAutoRelationsOverDefine", False)
        box.finished.connect(finished)
        box.show()

    QtCore.QTimer.singleShot(0, show)


ASK = [ask_about_skipped]  # replaced by the unit tests


def note_skipped(type, ask=False):
    """The 5 s status-bar note of patch 05; with ask, package 37's box as well (a relation that
    clashes, not a mere repeat)."""
    if ask:
        ASK[0]()
    if not App.GuiUp:
        return
    try:
        import FreeCADGui as Gui
        Gui.getMainWindow().showMessage("Automatic %s relation left out: it would over-define the sketch"
                                        % _NAMES.get(type, type), 5000)
    except Exception as _fw_err:
        _fw_log("fwsketch/relations.py:127", _fw_err)


def _add_tangent(snapper, out, geo, direction):
    g = snapper.geometry(geo)
    if g is None:
        return
    if type(g) is Part.LineSegment:
        ld = (g.EndPoint.x - g.StartPoint.x, g.EndPoint.y - g.StartPoint.y)
        n1, n2 = G.length(direction), G.length(ld)
        if n1 < 1e-8 or n2 < 1e-8 or abs(G.dot(direction, ld)) / (n1 * n2) > 0.995:
            return
    out.append(Suggestion("Tangent", geo))


TOUCH_SIN = 0.035   # about 2 degrees: a new circle counts as tangent where it touches within this


def _add_tangent_if_touching(snapper, out, geo, direction, position):
    ""



    g = snapper.geometry(geo)
    n1 = G.length(direction)
    if g is None or n1 < 1e-8:
        return
    if type(g) is Part.LineSegment:
        ld = (g.EndPoint.x - g.StartPoint.x, g.EndPoint.y - g.StartPoint.y)
        n2 = G.length(ld)
        if n2 < 1e-8 or abs(G.dot(direction, ld)) / (n1 * n2) > TOUCH_SIN:
            return
    elif isinstance(g, (Part.Circle, Part.ArcOfCircle)):
        r = (position[0] - g.Center.x, position[1] - g.Center.y)
        n2 = G.length(r)
        if n2 < 1e-8 or abs(direction[0] * r[1] - direction[1] * r[0]) / (n1 * n2) > TOUCH_SIN:
            return
    else:
        return
    out.append(Suggestion("Tangent", geo))


def _tilted(g):
    """An ellipse whose axes are not horizontal and vertical: its axis ends are not level with
    the centre, so only On Entity holds them."""
    try:
        u = g.XAxis
        return abs(u.x) > 1e-9 and abs(u.y) > 1e-9
    except Exception:
        return False


POINT_PULL_MM = 0.1     # an end on an existing point gets H/V only when that point is this close to level
AXIS_RELATIONS = False   # True: an end snapped onto the hidden origin axes gets On (FreeCAD)


def from_decision(snapper, d, target, direction):
    """Suggestions for the snap decision d, or None when the decision says nothing specific
    (snapping to objects off, or a curve target on a sketch curve)."""
    vertex = target in (VERTEX, VERTEX_NO_TANGENCY)
    out = []
    if vertex and snapper.p.alignment_adds_relation:
        for geo, pos, horizontal in d.aligned_points:
            out.append(Suggestion("Horizontal" if horizontal else "Vertical", geo, pos))
    w = d.winner
    if w == S.SKETCH_POINT:
        out.append(Suggestion("Coincident" if vertex else "PointOnObject", d.geo, d.pos))
    elif w == S.MIDPOINT:
        if vertex:
            g = snapper.geometry(d.geo)
            out.append(Suggestion("Symmetric" if type(g) is Part.LineSegment else "PointOnObject", d.geo))
        else:
            _add_tangent_if_touching(snapper, out, d.geo, direction, d.position)
    elif w == S.QUADRANT:
        g = snapper.geometry(d.geo)
        if vertex and g is not None:
            c = I.point_of(g, I.MID)
            out.append(Suggestion("PointOnObject", d.geo))
            if not _tilted(g):
                out.append(Suggestion("Vertical" if I.is_vertical_quadrant(d.position, c) else "Horizontal", d.geo, I.MID))
        elif not vertex:
            _add_tangent_if_touching(snapper, out, d.geo, direction, d.position)
    elif w == S.INTERSECTION:
        if vertex:
            quad = _quadrant_at(snapper, (d.geo, d.geo2), d.position)
            if quad is not None:

                # circle, Vertical/Horizontal to its centre) and leaves the crossing curve alone (tester Entry 9)
                geo, c = quad
                out.append(Suggestion("PointOnObject", geo))
                out.append(Suggestion("Vertical" if I.is_vertical_quadrant(d.position, c) else "Horizontal", geo, I.MID))
            else:
                for geo in (d.geo, d.geo2):
                    if geo in (I.H_AXIS, I.V_AXIS) and not AXIS_RELATIONS:
                        continue    # no axis lines in the sketch: no relation to one (as on the axis alone)
                    out.append(Suggestion("PointOnObject", geo))
    elif w == S.LINE_MIDPOINT:
        if vertex:
            out.append(Suggestion("MidpointOf", d.geo, d.pos))
    elif w in (S.SKETCH_CURVE, S.AXIS, S.AXIS_GRID):
        if not vertex:
            if S.is_model_geo(d.geo):
                _add_tangent(snapper, out, d.geo, direction)
                return out
            return None
        if d.geo in (-1, -2) and not AXIS_RELATIONS:

            # origin only shows the dotted inference to it, no relation (Beginners-1 0:24-0:33)
            return out
        out.append(Suggestion("PointOnObject", d.geo))
    elif w in (S.FREE, S.GRID, S.AXIS_ALIGN, S.AXIS_ALIGN_GRID, S.ALIGNMENT, S.PARALLEL, S.PERPENDICULAR,
               S.ARC_TANGENT, S.ARC_RADIAL, S.ANGLE_STEP):
        return out if snapper.p.objects else None
    elif w == S.EXTENSION:
        if vertex and snapper.p.extension_adds_relation:
            out.append(Suggestion("PointOnObject", d.geo))
    elif w == S.TANGENT_POINT:
        if vertex:
            out.append(Suggestion("PointOnObject", d.geo))
            if not S.is_model_geo(d.geo):

                # Tangent, even where the line meets it tangent (tester E14B-03, rib line to a crown)
                out.append(Suggestion("Tangent", d.geo))
    elif w == S.NORMAL_POINT:
        if vertex:
            out.append(Suggestion("PointOnObject", d.geo))
            out.append(Suggestion("Perpendicular", d.geo))
    elif w == S.DISABLED:
        return None
    return out  # Suppressed: nothing


def alignment(snapper, direction):
    """The relation of the new element's direction: the direction guide it follows, else the
    horizontal/vertical band."""
    g = snapper.last_direction_guide_along(direction)
    if g is not None:
        t = {G.PARALLEL: "Parallel", G.PERPENDICULAR: "Perpendicular", G.ARC_TANGENT: "Tangent",
             G.ARC_RADIAL: "Perpendicular"}.get(g.kind)
        if t:
            return [Suggestion(t, g.geo)]
    band = snapper.axis_band(direction)
    return [Suggestion(band)] if band else []


def seek(snapper, position, direction, target):
    """All suggestions for a point of the new element placed at position (the snapped point of
    the last move), direction = the element's direction there, zero when unknown."""
    if S.inference_suppressed():
        return []
    out = []
    d = snapper.last_decision_at(position)
    if d is not None:
        found = from_decision(snapper, d, target, direction)
        if found is not None:
            out.extend(found)
    if G.length(direction) > 1e-8 and target != CURVE:
        found = alignment(snapper, direction)
        if found and d is not None and d.winner == S.SKETCH_POINT and found[0].type in ("Horizontal", "Vertical"):
            # the end is on a point that is already there: Horizontal/Vertical would move that point,
            # so the end must be level (plumb) within the screen band and never more than POINT_PULL_MM
            # off, whatever the zoom (snap review 11-19, T7d: zoomed out it pulled a point 5 mm)
            off = abs(direction[1]) if found[0].type == "Horizontal" else abs(direction[0])
            limit = POINT_PULL_MM
            if snapper.pixel_size > 0.0:
                limit = min(limit, snapper.p.band_pixels * snapper.pixel_size)
            if off > limit:
                found = []
        out.extend(found)
    unique = []
    for s in out:
        if not any(s.key() == u.key() for u in unique):
            unique.append(s)
    return unique


# --- cleaning up between the two ends of a line ------------------------------------------------
def _circle_of(geometry_of, sug):
    for s in sug:
        if s.type in ("PointOnObject", "Tangent") and s.pos == I.NONE and s.geo != I.GEO_UNDEF:
            g = geometry_of(s.geo)
            if isinstance(g, (Part.Circle, Part.ArcOfCircle)):
                return s.geo
    return I.GEO_UNDEF


def prefer_tangent_between_circles(sketch, geometry_of, sug1, sug2):
    ""





    line = sketch.Geometry[sketch.GeometryCount - 1] if sketch.GeometryCount else None
    if not isinstance(line, Part.LineSegment):
        return
    circle1, circle2 = _circle_of(geometry_of, sug1), _circle_of(geometry_of, sug2)
    two_circles = circle1 != I.GEO_UNDEF and circle2 != I.GEO_UNDEF and circle1 != circle2
    horizontal_or_vertical = any(s.type in ("Horizontal", "Vertical") and s.geo == I.GEO_UNDEF and s.pos == I.NONE
                                 for s in sug2)
    if not two_circles and not (horizontal_or_vertical and circle1 != circle2):
        return
    start = (line.StartPoint.x, line.StartPoint.y)
    end = (line.EndPoint.x, line.EndPoint.y)
    d = (end[0] - start[0], end[1] - start[1])
    n = G.length(d)
    if n < 1e-7:
        return
    d = (d[0] / n, d[1] / n)
    tolerance = math.sin(math.radians(15.0 if two_circles else 5.0))

    def prefer(sug, circle, point):
        c = I.point_of(geometry_of(circle), I.MID)
        radial = (point[0] - c[0], point[1] - c[1])
        rn = G.length(radial)
        if rn < 1e-7 or abs((radial[0] * d[0] + radial[1] * d[1]) / rn) > tolerance:
            return
        sug[:] = [s for s in sug if not (s.type in ("Horizontal", "Vertical") and s.geo == circle and s.pos == I.MID)]
        if not any(s.type == "Tangent" and s.geo == circle for s in sug):
            sug.append(Suggestion("Tangent", circle))

    if circle1 != I.GEO_UNDEF:
        prefer(sug1, circle1, start)
    if circle2 != I.GEO_UNDEF:
        prefer(sug2, circle2, end)


def remove_redundant_hv(sketch, sug1, sug2, geometry_of=None):
    """A Horizontal/Vertical line from the origin or an axis keeps the H/V, not the relation to
    the axis; a line fixed at both ends (externals, origin + axis) gets no H/V."""
    if geometry_of is not None:
        prefer_tangent_between_circles(sketch, geometry_of, sug1, sug2)
    hv = [s.type for s in sug2 if s.type in ("Horizontal", "Vertical")]
    if hv:
        # only the axis the line runs along: a Vertical line ending on the X axis keeps both
        along = -1 if hv[0] == "Horizontal" else -2
        on_axis = lambda s: s.type == "PointOnObject" and s.geo == along and s.pos == I.NONE
        sug1[:] = [s for s in sug1 if not on_axis(s)]
        sug2[:] = [s for s in sug2 if not on_axis(s)]
    if not sug1 or not sug2:
        return

    def detect(sug):
        ext = orig = axis = False
        for s in sug:
            if s.type == "Coincident" and not ext:
                ext = s.geo < 0 or S.is_model_geo(s.geo)
                orig = s.geo == -1 and s.pos == I.START
                if s.geo >= 0:
                    # a sketch point already joined to an external or the origin
                    for c in sketch.Constraints:
                        if c.Type != "Coincident":
                            continue
                        pts = ((c.First, c.FirstPos), (c.Second, c.SecondPos))
                        if (s.geo, s.pos) in pts:
                            other = pts[1] if pts[0] == (s.geo, s.pos) else pts[0]
                            ext = ext or other[0] < 0
                            orig = orig or (other[0] == -1 and other[1] == I.START)
            elif s.type == "PointOnObject" and not axis:
                axis = s.geo in (-1, -2) and s.pos == I.NONE
        return ext, orig, axis

    e1, o1, a1 = detect(sug1)
    e2, o2, a2 = detect(sug2)
    if (e1 and e2) or (o1 and a2) or (o2 and a1):
        for s in list(sug2):
            if s.type in ("Horizontal", "Vertical"):
                note_skipped(s.type)
                sug2.remove(s)


# --- from suggestions to constraints ------------------------------------------------------------
class Pending:
    """A constraint to add: type, first, first_pos, second, second_pos, third, third_pos."""
    __slots__ = ("type", "first", "first_pos", "second", "second_pos", "third", "third_pos")

    def __init__(self, type, first=I.GEO_UNDEF, first_pos=I.NONE, second=I.GEO_UNDEF, second_pos=I.NONE,
                 third=I.GEO_UNDEF, third_pos=I.NONE):
        self.type, self.first, self.first_pos = type, first, first_pos
        self.second, self.second_pos, self.third, self.third_pos = second, second_pos, third, third_pos

    def involves(self, geo):
        return geo in (self.first, self.second, self.third)

    def to_constraint(self):
        t = self.type
        if t in ("Horizontal", "Vertical") and self.second == I.GEO_UNDEF:
            return Sketcher.Constraint(t, self.first)
        if t in ("Parallel", "Perpendicular", "Equal"):
            return Sketcher.Constraint(t, self.first, self.second)
        if t == "Symmetric":
            return Sketcher.Constraint(t, self.first, self.first_pos, self.second, self.second_pos, self.third, self.third_pos)
        if t == "PointOnObject":
            return Sketcher.Constraint(t, self.first, self.first_pos, self.second)
        if t == "Tangent":
            if self.first_pos != I.NONE and self.second_pos != I.NONE:
                return Sketcher.Constraint(t, self.first, self.first_pos, self.second, self.second_pos)
            if self.first_pos != I.NONE:
                return Sketcher.Constraint(t, self.first, self.first_pos, self.second)
            return Sketcher.Constraint(t, self.first, self.second)
        return Sketcher.Constraint(t, self.first, self.first_pos, self.second, self.second_pos)

    def __repr__(self):
        return "Pending(%s %s:%s %s:%s %s:%s)" % (self.type, self.first, self.first_pos, self.second,
                                                 self.second_pos, self.third, self.third_pos)


def generate(pending, suggestions, geo1, pos1, geometry_of):
    """Append the constraints for suggestions on point pos1 of the new element geo1 to pending
    (generateOneAutoConstraintFromSuggestion). geometry_of(geo) gives sketch geometry."""
    for s in suggestions:
        geo2, pos2 = s.geo, s.pos
        g1, p1 = geo1, pos1
        t = s.type
        if t == "Coincident":
            if p1 == I.NONE:
                continue
            tan = None
            if p1 in START_OR_END and pos2 in START_OR_END:
                tan = next((c for c in pending if c.type == "Tangent" and c.first == g1 and c.second == geo2), None)
            if tan is not None:
                tan.first_pos, tan.second_pos = p1, pos2
            else:
                pending.append(Pending("Coincident", g1, p1, geo2, pos2))
        elif t == "PointOnObject":
            if p1 == I.NONE:
                g1, geo2 = geo2, g1
                p1, pos2 = pos2, p1
            tan = None
            if p1 in START_OR_END:
                tan = next((c for c in pending if c.type == "Tangent" and c.involves(g1) and c.involves(geo2)), None)
            if tan is not None:
                if tan.first != g1:
                    tan.first, tan.second = tan.second, tan.first
                tan.first_pos = p1
            else:
                pending.append(Pending("PointOnObject", g1, p1, geo2))
        elif t == "Symmetric":
            pending.append(Pending("Symmetric", geo2, I.START, geo2, I.END, g1, p1))
        elif t == "MidpointOf":
            # the point (geo2, pos2) sits at the middle of the new line g1
            pending.append(Pending("Symmetric", g1, I.START, g1, I.END, geo2, pos2))
        elif t in ("Horizontal", "Vertical"):
            if pos2 != I.NONE:
                if p1 == I.NONE or geo2 == I.GEO_UNDEF or (geo2 == g1 and pos2 == p1):
                    continue
                pending.append(Pending(t, g1, p1, geo2, pos2))
            else:
                pending.append(Pending(t, geo2 if geo2 != I.GEO_UNDEF else g1))
        elif t in ("Parallel", "Perpendicular"):
            if geo2 == I.GEO_UNDEF or g1 == I.GEO_UNDEF or geo2 == g1:
                continue
            pending.append(Pending(t, g1, I.NONE, geo2))
        elif t == "Tangent":
            geom1, geom2 = geometry_of(g1), geometry_of(geo2)
            if geom1 is None or geom2 is None:
                continue
            if isinstance(geom1, (Part.Ellipse, Part.ArcOfEllipse)) or isinstance(geom2, (Part.Ellipse, Part.ArcOfEllipse)):
                continue  # needs an intermediate element: left to FreeCAD's own tools
            coincident = next((c for c in pending if c.type == "Coincident" and c.first == g1 and c.second == geo2), None)
            on_object = next((c for c in pending if c.type == "PointOnObject" and c.involves(g1) and c.involves(geo2)), None)
            circles = (Part.Circle, Part.ArcOfCircle)
            if coincident is not None and coincident.first_pos in START_OR_END and coincident.second_pos in START_OR_END:
                coincident.type = "Tangent"
            elif on_object is not None and on_object.first_pos in START_OR_END:
                on_object.type = "Tangent"
            elif coincident is not None and coincident.first_pos == I.MID and coincident.second_pos == I.MID \
                    and isinstance(geom1, circles) and isinstance(geom2, circles):
                pending.append(Pending("Equal", g1, I.NONE, geo2))
            else:
                pending.append(Pending("Tangent", g1, I.NONE, geo2))


def resolve_model(snapper, suggestions):
    """Replace model snap targets in suggestions with external references (added as needed)."""
    out = []
    for s in suggestions:
        if S.is_model_geo(s.geo):
            if s.type == "Tangent":

                # (on the edge) even where the line meets it tangent (tester E14B-03)
                continue
            r = snapper.resolve_model_reference(s.geo, s.pos)
            if r is None:
                continue
            s = Suggestion(s.type, r[0], r[1])
        out.append(s)
    return out


def _problem(sketch):
    return bool(sketch.RedundantConstraints) or bool(sketch.ConflictingConstraints) \
        or bool(getattr(sketch, "PartiallyRedundantConstraints", []))


COLLAPSE_MM = 1e-6


def _sweep(g):
    """An arc's sweep in radians (a full circle: 2 pi)."""
    if isinstance(g, Part.ArcOfCircle):
        return abs(g.LastParameter - g.FirstParameter)
    return 6.283185307179586


def _sound_entities(sketch):
    """Indexes of the lines with a length and the circles and arcs with a radius."""
    out = set()
    try:
        for i, g in enumerate(sketch.Geometry):
            if isinstance(g, Part.LineSegment):
                if (g.EndPoint - g.StartPoint).Length > COLLAPSE_MM:
                    out.add(i)
            elif isinstance(g, (Part.Circle, Part.ArcOfCircle)):
                if g.Radius > COLLAPSE_MM and _sweep(g) > 1e-9 \
                        and not (isinstance(g, Part.ArcOfCircle) and _sweep(g) >= 6.283185307179586 - 1e-9):
                    out.add(i)
    except Exception:
        pass
    return out


def _collapsed(sketch, sound):
    """True when an entity of sound is now a point (zero length or radius)."""
    if not sound:
        return False
    try:
        geos = sketch.Geometry
        for i in sound:
            if i >= len(geos):
                continue
            g = geos[i]
            if isinstance(g, Part.LineSegment):
                if (g.EndPoint - g.StartPoint).Length <= COLLAPSE_MM:
                    return True
            elif isinstance(g, (Part.Circle, Part.ArcOfCircle)) and (g.Radius <= COLLAPSE_MM or _sweep(g) <= 1e-9
                                                                     or (isinstance(g, Part.ArcOfCircle) and _sweep(g) >= 6.283185307179586 - 1e-9)):
                # a point, or an arc whose ends met: no sweep left, or (the solver may go either
                # way from the same start, review 1119 perf3) a whole turn
                return True
    except Exception:
        return False
    return False


def _put_back(sketch, shape):
    """After a relation was taken out again: the geometry as it was before it went in (the solver may
    have moved it on the way: an arc closed to no sweep, a rectangle shrunk), then solved."""
    try:
        if shape is not None and len(shape) == len(sketch.Geometry):
            sketch.Geometry = shape
    except Exception as error:
        App.Console.PrintLog("fwsketch: shape not put back: %s\n" % error)
    sketch.solve()


def _readings(sketch):
    return (frozenset(sketch.RedundantConstraints), frozenset(sketch.ConflictingConstraints),
            frozenset(getattr(sketch, "PartiallyRedundantConstraints", []) or []))


def add_without_redundancy(sketch, pending, avoid_redundant=True):
    """Add the pending constraints one by one; one the solver reports redundant (a repeat) is
    removed again quietly, one that conflicts, or that makes a sound sketch unsound (the solver
    may blame an older constraint for the repeat), is removed with package 37's box. Returns
    the number kept (removeRedundantAutoConstraints + overDefines)."""
    if not pending:
        return 0
    if not avoid_redundant:
        for c in pending:
            sketch.addConstraint(c.to_constraint())
        return len(pending)
    if _add_all_at_once(sketch, pending):
        return len(pending)
    kept = 0
    for c in pending:
        solved = sketch.solve()
        had_problem = _problem(sketch)
        sound = _sound_entities(sketch)
        shape_before = sketch.Geometry
        before = sketch.ConstraintCount
        try:
            sketch.addConstraint(c.to_constraint())
        except Exception as error:      # a pairing FreeCAD refuses outright: no relation, no fuss
            App.Console.PrintLog("fwsketch: automatic %s left out: %s\n" % (c.type, error))
            continue
        if sketch.ConstraintCount == before:
            continue
        code = sketch.solve()
        index = before + 1  # the solver numbers constraints from 1
        # a relation FreeCAD cannot hold between these two entities (Perpendicular between a spline
        # and an arc as whole curves: "malformed", solve() -5) or one that breaks the solver (-1):
        # the sketch would stop solving for good, so it goes again, quietly
        if index in getattr(sketch, "MalformedConstraints", []) or (solved >= 0 and code in (-1, -5)):
            sketch.delConstraint(before)
            _put_back(sketch, shape_before)
            App.Console.PrintLog("fwsketch: automatic %s left out: FreeCAD cannot hold it here (solve %s)\n" % (c.type, code))
            continue
        if code >= 0 and _collapsed(sketch, sound):
            # the solver holds it only by shrinking an entity to a point (a rectangle corner dropped

            # relation (zero-length entity): it is left out with the over-define note
            sketch.delConstraint(before)
            _put_back(sketch, shape_before)
            App.Console.PrintLog("fwsketch: automatic %s left out: it shrinks an entity to a point\n" % c.type)
            note_skipped(c.type, ask=True)
            continue
        redundant = index in sketch.RedundantConstraints or index in getattr(sketch, "PartiallyRedundantConstraints", [])
        conflicting = index in sketch.ConflictingConstraints
        over_defines = not had_problem and _problem(sketch) and not redundant and not conflicting
        if redundant or conflicting or over_defines:
            sketch.delConstraint(before)
            _put_back(sketch, shape_before)
            note_skipped(c.type, ask=conflicting or over_defines)
        else:
            kept += 1
    mark_solved(sketch)
    return kept


def _add_all_at_once(sketch, pending):
    """All the pending constraints in one add and one solve (review 1119 perf3: a solve costs
    about 0.3 s in a 960-relation sketch, and the one-by-one way below takes two a relation).
    They stay when FreeCAD takes them all, the solver names none of them, its other readings are
    as at the last solve, none is malformed and nothing shrank to a point: then the one-by-one
    way keeps each of them too. Otherwise they go again, the geometry is put back as it was, and
    False sends the caller to the one-by-one way."""
    first = sketch.ConstraintCount
    before = _readings(sketch)       # from the last solve (tools solve after each action)
    if any(before):
        return False                 # a sketch with a problem already: the one-by-one way sorts it out
    sound = _sound_entities(sketch)
    shape_before = sketch.Geometry
    try:
        sketch.addConstraint([c.to_constraint() for c in pending])
    except Exception as error:
        App.Console.PrintLog("fwsketch: automatic relations one by one: %s\n" % error)
    if sketch.ConstraintCount != first + len(pending):
        if sketch.ConstraintCount > first:
            sketch.delConstraints(list(range(first, sketch.ConstraintCount)))
            _put_back(sketch, shape_before)
        return False
    sketch.solve()
    code = sketch.solve()            # read twice: right after an add one solve can still report the sketch as it was
    after = _readings(sketch)
    new = set(range(first + 1, first + len(pending) + 1))   # the solver numbers from 1
    if code not in (-1, -5) and after == before and not new & set().union(*after) \
            and not getattr(sketch, "MalformedConstraints", []) and not _collapsed(sketch, sound):
        mark_solved(sketch)
        return True
    sketch.delConstraints(list(range(first, sketch.ConstraintCount)))
    _put_back(sketch, shape_before)
    return False


_SOLVED = {}


def mark_solved(sketch):
    """Note that the sketch was just solved as it stands (its geometry and relation counts)."""
    _SOLVED[sketch.FullName] = (sketch.GeometryCount, sketch.ConstraintCount)


def still_solved(sketch):
    """True when the sketch was solved by mark_solved's caller and nothing was added since."""
    return _SOLVED.pop(sketch.FullName, None) == (sketch.GeometryCount, sketch.ConstraintCount)
