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
from PySide import QtCore, QtWidgets
from . import unitbox

from . import contextbar, dimtools, relationspm, sketchtoolpm

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/OffsetEntities"
DIMENSION_NAME = "Offset"
CAP_KINDS = ("Arcs", "Lines")
TOL = 1e-7


class OffsetError(Exception):
    pass


def _params():
    return App.ParamGet(PARAMS)


def _kind(geo):
    name = type(geo).__name__
    return {"LineSegment": "line", "ArcOfCircle": "arc", "Circle": "circle"}.get(name)


def _v(x, y):
    return App.Vector(x, y, 0)


def _cross(a, b):
    return a.x * b.y - a.y * b.x


def _left(t):
    return _v(-t.y, t.x)


# --------------------------------------------------------------------------- chains
def _ends(geo):
    return geo.StartPoint, geo.EndPoint


def _geo(sketch, g):
    """The sketch's own geometry g, or for a model edge (external geometry, g <= -3) its copy in
    the sketch plane."""
    return sketch.Geometry[g] if g >= 0 else sketch.ExternalGeo[-g - 1]


RELATION_PREFIX = "FWOffset_"


def _name_relation(sketch, index):
    ""

    if index is None:
        return
    names = {c.Name for c in sketch.Constraints}
    k = 0
    while "%s%d" % (RELATION_PREFIX, k) in names:
        k += 1
    try:
        sketch.renameConstraint(index, "%s%d" % (RELATION_PREFIX, k))
    except Exception as _fw_err:
        _fw_log("offsetentities.py:102", _fw_err)


def _same(a, b):
    return (a - b).Length < 1e-6


def connected(sketch, geos):
    """Select chain: the picked entities and every line or arc joined to them end to end."""
    geometry = sketch.Geometry
    out = list(dict.fromkeys(geos))
    # model edges come as whole loops already (convertentities.expand); only sketch entities grow here
    todo = [g for g in out if g >= 0 and _kind(geometry[g]) in ("line", "arc")]
    while todo:
        g = todo.pop()
        for p in _ends(geometry[g]):
            for h, other in enumerate(geometry):
                if h in out or _kind(other) not in ("line", "arc"):
                    continue
                if sketch.getConstruction(h) != sketch.getConstruction(g):
                    continue
                if any(_same(p, q) for q in _ends(other)):
                    out.append(h)
                    todo.append(h)
    return out


def chains(sketch, geos):
    """The picked entities as chains: [(items, closed)], items [(geo, reversed)] in walking order."""
    geometry = _Geometry(sketch)
    out = []
    rest = []
    for g in geos:
        kind = _kind(geometry[g])
        if kind == "circle":
            out.append(([(g, False)], True))
        elif kind in ("line", "arc"):
            rest.append(g)

    def neighbours(p, skip):
        return [h for h in rest if h not in skip and any(_same(p, q) for q in _ends(geometry[h]))]

    used = set()
    while len(used) < len(rest):
        left = [g for g in rest if g not in used]
        start, rev = left[0], False
        for g in left:      # start at an open end when there is one
            s, e = _ends(geometry[g])
            if not neighbours(s, {g}):
                start, rev = g, False
                break
            if not neighbours(e, {g}):
                start, rev = g, True
                break
        items = [(start, rev)]
        used.add(start)
        first = _ends(geometry[start])[1 if rev else 0]
        here = _ends(geometry[start])[0 if rev else 1]
        while True:
            nxt = [h for h in neighbours(here, used)]
            if not nxt:
                break
            h = nxt[0]
            s, e = _ends(geometry[h])
            r = not _same(s, here)
            items.append((h, r))
            used.add(h)
            here = s if r else e
        closed = len(items) > 1 and _same(here, first)
        out.append((items, closed))
    return out


class _Geometry:
    """sketch.Geometry indexed by geo id, model edges (negative ids) included."""

    def __init__(self, sketch):
        self.sketch = sketch

    def __getitem__(self, g):
        return _geo(self.sketch, g)


# --------------------------------------------------------------------------- offset curves
def _tangent(geo, rev, at_end):
    """The walking direction at the start (at_end False) or the end of an entity."""
    if _kind(geo) == "line":
        t = geo.EndPoint - geo.StartPoint
    else:
        p = (geo.EndPoint if at_end != rev else geo.StartPoint) - geo.Center
        t = _v(-p.y, p.x)
    t = _v(t.x, t.y)
    t.normalize()
    return -t if rev else t


def _point_at_start(geo, rev):
    return geo.EndPoint if rev else geo.StartPoint


def _point_at_end(geo, rev):
    return geo.StartPoint if rev else geo.EndPoint


def _offset_curve(geo, rev, d):
    """('line', point, direction) or ('circle', centre, radius) at d to the left of the walk."""
    if _kind(geo) == "line":
        t = _tangent(geo, rev, False)
        return ("line", _point_at_start(geo, rev) + _left(t) * d, t)
    r = geo.Radius + (d if rev else -d)
    if r <= TOL:
        raise OffsetError("The offset distance is too large for the arc's radius.")
    return ("circle", geo.Center, r)


def _meet(c1, c2, near):
    """Where two offset curves meet, nearest to `near`."""
    roots = []
    if c1[0] == "line" and c2[0] == "line":
        den = _cross(c1[2], c2[2])
        if abs(den) > 1e-12:
            s = _cross(c2[1] - c1[1], c2[2]) / den
            roots.append(c1[1] + c1[2] * s)
    elif c1[0] == "circle" and c2[0] == "circle":
        d = c2[1] - c1[1]
        L = d.Length
        if L > TOL and abs(c1[2] - c2[2]) <= L <= c1[2] + c2[2] + 1e-9:
            a = (c1[2] ** 2 - c2[2] ** 2 + L * L) / (2 * L)
            h = math.sqrt(max(c1[2] ** 2 - a * a, 0.0))
            m = c1[1] + d * (a / L)
            n = _left(d * (1.0 / L))
            roots += [m + n * h, m - n * h]
    else:
        line, circle = (c1, c2) if c1[0] == "line" else (c2, c1)
        p, t = line[1], line[2]
        f = p - circle[1]
        b = f.dot(t)
        disc = b * b - (f.dot(f) - circle[2] ** 2)
        if disc >= -1e-9:
            s = math.sqrt(max(disc, 0.0))
            roots += [p + t * (-b + s), p + t * (-b - s)]
    if not roots:
        return None
    return min(roots, key=lambda q: (q - near).Length)


def offset_chain(sketch, items, closed, d):
    """The offset of one chain at d (positive: left of the walk): a list of
    (Part geometry, base geo, reversed, tangent-joined-to-next)."""
    import Part
    geos = [_geo(sketch, g) for g, _r in items]
    if len(items) == 1 and _kind(geos[0]) == "circle":
        c = geos[0]
        r = c.Radius - d
        if r <= TOL:
            raise OffsetError("The offset distance is too large for the circle's radius.")
        return [(Part.Circle(c.Center, App.Vector(0, 0, 1), r), items[0][0], False, False)]
    curves = [_offset_curve(geo, rev, d) for geo, (_g, rev) in zip(geos, items)]
    n = len(items)
    joints = n if closed else n - 1
    starts = [None] * n
    ends = [None] * n
    tangent = [False] * n
    for k in range(joints):
        j = (k + 1) % n
        q = _point_at_end(geos[k], items[k][1])
        t1 = _tangent(geos[k], items[k][1], True)
        t2 = _tangent(geos[j], items[j][1], False)
        if abs(_cross(t1, t2)) < 1e-9 and t1.dot(t2) > 0:
            p = q + _left(t1) * d
            tangent[k] = True
        else:
            p = _meet(curves[k], curves[j], q + (_left(t1) + _left(t2)) * (0.5 * d))
            if p is None:
                raise OffsetError("The offset of two joined entities does not meet: try a smaller distance.")
        ends[k] = p
        starts[j] = p
    if not closed:
        starts[0] = _point_at_start(geos[0], items[0][1]) + _left(_tangent(geos[0], items[0][1], False)) * d
        ends[-1] = _point_at_end(geos[-1], items[-1][1]) + _left(_tangent(geos[-1], items[-1][1], True)) * d
    out = []
    for k, (geo, (g, rev)) in enumerate(zip(geos, items)):
        ps, pe = starts[k], ends[k]
        if _kind(geo) == "line":
            t = _tangent(geo, rev, False)
            if (pe - ps).Length < 1e-6 or (pe - ps).dot(t) <= 0:
                raise OffsetError("The offset distance is too large: a line would turn back.")
            out.append((Part.LineSegment(ps, pe), g, False, tangent[k]))
        else:
            c, r = curves[k][1], curves[k][2]
            a_s = math.atan2(ps.y - c.y, ps.x - c.x)
            a_e = math.atan2(pe.y - c.y, pe.x - c.x)
            lo, hi = (a_e, a_s) if rev else (a_s, a_e)
            while hi <= lo + 1e-9:
                hi += 2 * math.pi
            sweep = geo.LastParameter - geo.FirstParameter
            if abs((hi - lo) - sweep) > math.pi:
                raise OffsetError("The offset distance is too large: an arc would turn inside out.")
            out.append((Part.ArcOfCircle(Part.Circle(c, App.Vector(0, 0, 1), r), lo, hi), g, rev, tangent[k]))
    return out


def _area(sketch, items):
    """Signed area inside a closed chain (positive: the walk runs anticlockwise)."""
    pts = []
    for g, rev in items:
        geo = _geo(sketch, g)
        ps = [geo.value(geo.FirstParameter + (geo.LastParameter - geo.FirstParameter) * i / 8.0)
              for i in range(9)] if _kind(geo) == "arc" else [geo.StartPoint, geo.EndPoint]
        pts += list(reversed(ps)) if rev else ps
    return 0.5 * sum(_cross(a, b) for a, b in zip(pts, pts[1:] + pts[:1]))


def side(sketch, items, closed, reverse):
    """+1: offset to the left of the walk, -1: to the right. Closed chains go outwards
    unless reversed; circles count as walked anticlockwise."""
    if closed:
        ccw = True if len(items) == 1 and _kind(_geo(sketch, items[0][0])) == "circle" \
            else _area(sketch, items) > 0
        s = -1 if ccw else 1
    else:
        s = 1
    return -s if reverse else s


# --------------------------------------------------------------------------- making it
def _pos(geo, rev, at_end):
    """The sketch point id of a new entity's walking start or end."""
    if _kind(geo) == "line":
        return 2 if at_end else 1
    return (1 if at_end else 2) if rev else (2 if at_end else 1)


def _free_name(sketch, base):
    names = {c.Name for c in sketch.Constraints}
    name, k = base, 1
    while name in names:
        k += 1
        name = "%s%d" % (base, k)
    return name


def _tie_dimensions(sketch, distances):
    """The first distance is the dimension shown; the others are hidden and follow it."""
    distances = [i for i in distances if i is not None]
    if not distances:
        return None
    name = _free_name(sketch, DIMENSION_NAME)
    sketch.renameConstraint(distances[0], name)
    if len(distances) > 1:
        sketch.setVirtualSpace(distances[1:], True)
        for k, i in enumerate(distances[1:], 1):
            # named after the shown one, so they can go with it (FollowerWatch)
            sketch.renameConstraint(i, _free_name(sketch, "%s_t%d" % (name, k)))
            sketch.setExpression(".Constraints[%d]" % i, ".Constraints.%s" % name)
    return distances[0]


class FollowerWatch:
    ""




    def __init__(self):
        self.busy = False

    def slotChangedObject(self, obj, prop):
        if prop != "Constraints" or self.busy or getattr(obj, "TypeId", "") != "Sketcher::SketchObject":
            return
        try:
            engine = obj.ExpressionEngine
        except Exception:
            return
        if not engine:
            return
        prefix = ".Constraints." + DIMENSION_NAME
        dangling = [(path, expr[len(".Constraints."):]) for path, expr in engine if expr.startswith(prefix)]
        if not dangling:
            return
        names = {c.Name for c in obj.Constraints if c.Name}
        gone = [(path, name) for path, name in dangling if name not in names]
        if not gone:
            return
        self.busy = True
        try:
            for path, _name in gone:
                try:
                    obj.setExpression(path, None)
                except Exception as _fw_err:
                    _fw_log("offsetentities.py:392", _fw_err)
            lost = {name for _path, name in gone}
            mine = sorted((i for i, c in enumerate(obj.Constraints)
                           if c.Name and any(c.Name.startswith(n + "_t") for n in lost)), reverse=True)
            if mine:
                obj.delConstraints(mine) if hasattr(obj, "delConstraints") else [obj.delConstraint(i) for i in mine]
        except Exception as error:
            App.Console.PrintLog("FreeCAD offset followers: %s\n" % error)
        finally:
            self.busy = False


_WATCH = None


def _held(sketch, geo):
    """'Horizontal' or 'Vertical' when a relation holds the line so, else None."""
    for c in sketch.Constraints:
        if c.Type in ("Horizontal", "Vertical") and c.First == geo and c.Second in (None, -2000) \
                and getattr(c, "Driving", True):
            return c.Type
    return None


def _distance(sketch, base, g, d):
    """The offset's distance from its base. A point-to-line or circle-to-circle distance has no
    side, so a big change to the base can flip the offset across it; for a base line held
    horizontal or vertical a DistanceY or DistanceX between the start points keeps the side."""
    C = dimtools._constraint
    geo = sketch.Geometry[g]
    if _kind(geo) != "line":
        return C("Distance", base, g, d)
    held = _held(sketch, base)
    if held:
        a, b = sketch.getPoint(base, 1), sketch.getPoint(g, 1)
        kind, delta = ("DistanceY", b.y - a.y) if held == "Horizontal" else ("DistanceX", b.x - a.x)
        return C(kind, base, 1, g, 1, d) if delta > 0 else C(kind, g, 1, base, 1, d)
    return C("Distance", g, 1, base, d)


def plan_offset(sketch, geos, distance, reverse=False, bidirectional=False, select_chain=True):
    """Works out every offset without touching the sketch, so that a distance that is too large
    adds nothing: [(items, closed, [(d, parts)])]. Raises OffsetError with the reason."""
    if distance <= TOL:
        raise OffsetError("The offset distance must be more than zero.")
    picked = connected(sketch, geos) if select_chain else list(geos)
    groups = chains(sketch, picked)
    if not groups:
        raise OffsetError("Select lines, arcs or circles to offset.")
    plans = []
    for items, closed in groups:
        s = side(sketch, items, closed, reverse)
        sides = [s * distance] + ([-s * distance] if bidirectional else [])
        plans.append((items, closed, [(d, offset_chain(sketch, items, closed, d)) for d in sides]))
    return plans


def make_offset(sketch, geos, distance, reverse=False, bidirectional=False, cap=None,
                select_chain=True, base_construction=False, offset_construction=False, dimensions=True,
                plans=None):
    """Adds the offset of the entities; returns the new geo ids and the dimensions shown."""
    import Part
    C = dimtools._constraint
    if plans is None:
        plans = plan_offset(sketch, geos, distance, reverse, bidirectional, select_chain)
    new, shown = [], []
    for items, closed, sides in plans:
        made = []
        # with arc caps on an open chain the caps hold the second side (Tangent at both ends, round
        # the base ends): its own distances would make the cap ends redundant, so the solver dropped
        # them and a later distance edit opened the outline (tester SK9-03). One dimension drives both.
        arc_caps = cap == "Arcs" and bidirectional and not closed and len(sides) == 2
        for side_index, (d, parts) in enumerate(sides):
            ids = [sketch.addGeometry(p, offset_construction) for p, _b, _r, _t in parts]
            new += ids
            made.append((d, parts, ids))
            n = len(parts)
            cons = []
            for k in range(n if closed and n > 1 else n - 1):
                j = (k + 1) % n
                a = (ids[k], _pos(parts[k][0], parts[k][2], True))
                b = (ids[j], _pos(parts[j][0], parts[j][2], False))
                cons.append(C("Tangent" if parts[k][3] else "Coincident", a[0], a[1], b[0], b[1]))
            if cons:
                sketch.addConstraint(cons)

            for (p, base, _r, _t), g in zip(parts, ids):
                if _kind(p) == "line":
                    held = dimtools.attempt(sketch, C("Parallel", g, base))
                else:
                    held = dimtools.attempt(sketch, C("Coincident", g, 3, base, 3))
                if base < 0:
                    _name_relation(sketch, held)
            if not dimensions or (arc_caps and side_index == 1):
                continue
            dists = []
            for (p, base, _r, _t), g in sorted(zip(parts, ids), key=lambda x: _kind(x[0][0]) != "line"):
                dists.append(dimtools.attempt(sketch, _distance(sketch, base, g, abs(d))))
            if not closed:
                for k, at_end in ((0, False), (n - 1, True)):
                    base, rev = items[k]
                    bgeo = _geo(sketch, base)
                    bpos = (2 if at_end else 1) if not rev else (1 if at_end else 2)
                    bp = bgeo.EndPoint if bpos == 2 else bgeo.StartPoint
                    opos = _pos(parts[k][0], parts[k][2], at_end)
                    op = sketch.getPoint(ids[k], opos)
                    line = sketch.addGeometry(Part.LineSegment(bp, op), True)
                    first = len(sketch.Constraints)
                    sketch.addConstraint([C("Coincident", line, 1, base, bpos), C("Coincident", line, 2, ids[k], opos)])
                    square = C("Perpendicular", line, base) if _kind(bgeo) == "line" else C("PointOnObject", base, 3, line)
                    if dimtools.attempt(sketch, square) is None:
                        sketch.delGeometry(line)
                    else:
                        sketch.setVirtualSpace(list(range(first, len(sketch.Constraints))), True)
            dim = _tie_dimensions(sketch, dists)
            if dim is not None:
                shown.append(dim)
        if cap and len(made) == 2 and not closed:
            (d1, p1, i1), (d2, p2, i2) = made
            n = len(items)
            for k, at_end in ((0, False), (n - 1, True)):
                base, rev = items[k]
                bgeo = _geo(sketch, base)
                bpos = (2 if at_end else 1) if not rev else (1 if at_end else 2)
                centre = bgeo.EndPoint if bpos == 2 else bgeo.StartPoint
                pos1 = _pos(p1[k][0], p1[k][2], at_end)
                pos2 = _pos(p2[k][0], p2[k][2], at_end)
                a, b = sketch.getPoint(i1[k], pos1), sketch.getPoint(i2[k], pos2)
                if cap == "Lines":
                    g = sketch.addGeometry(Part.LineSegment(a, b), offset_construction)
                    ends = ((g, 1, i1[k], pos1), (g, 2, i2[k], pos2))
                else:
                    t = _tangent(bgeo, rev, at_end)
                    away = centre + (t if at_end else -t) * distance
                    a1 = math.atan2(a.y - centre.y, a.x - centre.x)
                    a2 = math.atan2(b.y - centre.y, b.x - centre.x)
                    mid = math.atan2(away.y - centre.y, away.x - centre.x)
                    lo, hi = a1, a2
                    while hi <= lo:
                        hi += 2 * math.pi
                    m = mid
                    while m < lo:
                        m += 2 * math.pi
                    flipped = m > hi
                    if flipped:
                        lo, hi = a2, a1
                        while hi <= lo:
                            hi += 2 * math.pi
                    g = sketch.addGeometry(Part.ArcOfCircle(Part.Circle(centre, App.Vector(0, 0, 1), distance), lo, hi),
                                           offset_construction)
                    ends = ((g, 2 if flipped else 1, i1[k], pos1), (g, 1 if flipped else 2, i2[k], pos2))
                    dimtools.attempt(sketch, C("Coincident", g, 3, base, bpos))
                new.append(g)
                for k_end, c in enumerate(ends):
                    if cap != "Lines" and k_end == 1:

                        if dimtools.attempt(sketch, C("Tangent", *c)) is not None:
                            continue
                    dimtools.attempt(sketch, C("Coincident", *c))
    if base_construction:
        for g in dict.fromkeys(g for items, _c, _s in plans for g, _r in items):
            if g >= 0 and not sketch.getConstruction(g):
                sketch.toggleConstruction(g)
    sketch.solve()
    return new, shown


# --------------------------------------------------------------------------- the page
class OffsetPage(sketchtoolpm.ToolPage):
    TITLE = "Offset Entities"
    ICON = "SKETCH_OFFSET_ENTITIES"
    PIXMAP = "Sketcher_Offset"
    TRANSACTION = "Offset Entities"

    def build(self):
        p = _params()
        self.entities = []
        self.model_picks = []
        self.made = []
        self._filling = True
        g = self.group("Parameters")
        self.distance = unitbox.UnitSpinBox(g.body)
        self.distance.setObjectName("SWOffsetDistance")
        self.distance.setRange(0.001, 1e6)
        self.distance.setDecimals(3)
        self.distance.setSuffix(" mm")
        self.distance.setValue(p.GetFloat("Distance", 10.0))
        self.distance.setToolTip("Offset distance")
        self.distance.setKeyboardTracking(False)
        g.content.addWidget(self.distance)

        def box(name, text, value):
            b = QtWidgets.QCheckBox(text, g.body)
            b.setObjectName(name)
            b.setChecked(value)
            g.content.addWidget(b)
            b.toggled.connect(self.changed)
            return b

        self.dims = box("SWOffsetAddDimensions", "Add dimensions", p.GetBool("AddDimensions", True))
        self.reverse = box("SWOffsetReverse", "Reverse", False)
        self.chain = box("SWOffsetSelectChain", "Select chain", p.GetBool("SelectChain", True))
        self.bidir = box("SWOffsetBidirectional", "Bi-directional", p.GetBool("Bidirectional", False))
        self.cap = box("SWOffsetCapEnds", "Cap ends", p.GetBool("CapEnds", False))
        self.cap_kind = QtWidgets.QButtonGroup(g.body)
        chosen = p.GetString("CapKind", CAP_KINDS[1])
        for i, name in enumerate(CAP_KINDS):
            b = QtWidgets.QRadioButton(name, g.body)
            b.setObjectName("SWOffsetCap" + name)
            b.setChecked(name == chosen)
            self.cap_kind.addButton(b, i)
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(20, 0, 0, 0)
            row.addWidget(b)
            row.addStretch(1)
            g.content.addLayout(row)
        if self.cap_kind.checkedButton() is None:
            self.cap_kind.button(0).setChecked(True)
        self.cap_kind.buttonClicked.connect(self.changed)
        label = QtWidgets.QLabel("Construction geometry:", g.body)
        g.content.addWidget(label)
        self.base_c = box("SWOffsetBaseConstruction", "Base geometry", p.GetBool("BaseConstruction", False))
        self.offset_c = box("SWOffsetOffsetConstruction", "Offset geometry", p.GetBool("OffsetConstruction", False))
        self.distance.valueChanged.connect(self.changed)
        self._filling = False
        self._enable()
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        # a click on a model edge or face goes to the page (Convert Entities' picker)
        from . import convertentities
        self.model_picker = convertentities._Picker(self)
        self.model_picker.install()
        self.show_note("Select the sketch entities to offset.")
        # entities picked before the command: taken once the command has returned, as
        # FreeCAD commits a history entry opened while a command runs
        QtCore.QTimer.singleShot(0, self._picked_before)

    def _picked_before(self):
        if not sketchtoolpm.alive(self):
            return
        for sub in relationspm.picked_subs(self.sketch):
            self.picked(sub)
        from . import convertentities
        for obj, sub in convertentities._picks_before(self.sketch):
            if sub.startswith(("Edge", "Face")):
                self.picked_model(obj, sub)

    def source_of(self, sub):
        """For the model picker: a click on the sketch's own geometry stays the sketch's."""
        return None

    def picked_model(self, obj, sub):
        ""
        if not sub.startswith(("Edge", "Face")):
            return
        if (obj, sub) in self.model_picks:
            self.model_picks.remove((obj, sub))     # a second pick takes it out
        else:
            self.model_picks.append((obj, sub))
        self.changed()

    def _model_geos(self):
        """External geometry for the model picks (in the open history step): their geo ids."""
        from . import convertentities
        out = []
        for obj, sub in self.model_picks:
            for name in convertentities.expand(self.sketch, obj, sub, self.chain.isChecked()):
                if not name.startswith("Edge"):
                    continue
                before = len(self.sketch.ExternalGeo)
                try:
                    self.sketch.addExternal(obj.Name, name)
                except ValueError:
                    if convertentities.add_external_linked(self.sketch, obj, name) is not None:
                        self.sketch.solve()
                        for k in range(before, len(self.sketch.ExternalGeo)):
                            if _kind(self.sketch.ExternalGeo[k]) is not None:
                                out.append(-(k + 1))
                        continue
                    # no binder: a construction copy to offset from
                    try:
                        out += convertentities.add_plain(self.sketch, obj.Shape.getElement(name).Edges, True)
                    except Exception as _fw_err:
                        _fw_log("offsetentities.py:675", _fw_err)
                    continue
                except Exception:
                    continue
                self.sketch.solve()
                for k in range(before, len(self.sketch.ExternalGeo)):
                    if _kind(self.sketch.ExternalGeo[k]) is not None:
                        out.append(-(k + 1))
        return out

    def _enable(self):
        # no greyed choices: Cap ends shows with Bi-directional, Arcs/Lines with Cap ends
        self.cap.setEnabled(True)
        self.cap.setVisible(self.bidir.isChecked())
        for b in self.cap_kind.buttons():
            b.setEnabled(True)
            b.setVisible(self.bidir.isChecked() and self.cap.isChecked())

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("offsetentities.py:695", _fw_err)
        if item is None or item.geo < 0 or item.geo in self.made:
            return
        if _kind(self.sketch.Geometry[item.geo]) is None:
            return
        if item.geo in self.entities:
            self.entities.remove(item.geo)
        else:
            self.entities.append(item.geo)
        self.changed()

    def selection_changed(self):
        pass

    def changed(self, *args):
        if self._filling:
            return
        self._enable()
        self.undo_work()
        self.made = []
        if not self.entities and not self.model_picks:
            self.show_note("Select the sketch entities to offset.")
            return
        cap = self.cap_kind.checkedButton().text() if self.bidir.isChecked() and self.cap.isChecked() else None
        entities = list(self.entities)
        if self.model_picks:
            # model edges are taken in as external geometry first, in the same history step
            self.begin()
            entities += self._model_geos()
        try:
            # worked out before the history entry opens: FreeCAD keeps an entry that was opened
            # and aborted with nothing in it
            plans = plan_offset(self.sketch, entities, self.distance.value(), self.reverse.isChecked(),
                                self.bidir.isChecked(), self.chain.isChecked())
        except OffsetError as error:
            if self.model_picks:
                self.undo_work()
            self.show_note(str(error), True)
            return
        except Exception as error:
            if self.model_picks:
                self.undo_work()
            self.show_note("Could not offset: %s" % error, True)
            return
        if not self.model_picks:
            self.begin()
        try:
            self.made, _shown = make_offset(self.sketch, entities, self.distance.value(),
                                            self.reverse.isChecked(), self.bidir.isChecked(), cap,
                                            self.chain.isChecked(), self.base_c.isChecked(),
                                            self.offset_c.isChecked(), self.dims.isChecked(), plans)
        except Exception as error:
            self.undo_work()
            self.show_note("Could not offset: %s" % error, True)
            return
        sketchtoolpm._refresh(self.sketch)
        bad = list(self.sketch.ConflictingConstraints) + list(self.sketch.RedundantConstraints)
        self.show_note("The offset over-defines the sketch." if bad else "", bool(bad))

    def finish(self):
        p = _params()
        p.SetFloat("Distance", self.distance.value())
        p.SetBool("AddDimensions", self.dims.isChecked())
        p.SetBool("SelectChain", self.chain.isChecked())
        p.SetBool("Bidirectional", self.bidir.isChecked())
        p.SetBool("CapEnds", self.cap.isChecked())
        p.SetString("CapKind", self.cap_kind.checkedButton().text())
        p.SetBool("BaseConstruction", self.base_c.isChecked())
        p.SetBool("OffsetConstruction", self.offset_c.isChecked())

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("offsetentities.py:769", _fw_err)
        self.observer.page = None
        picker = getattr(self, "model_picker", None)
        if picker is not None:
            picker.remove()


class OffsetCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_Offset", "MenuText": "Offset Entities",
                "ToolTip": "Adds sketch entities by offsetting sketch entities by a distance",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(OffsetPage(sketch))


COMMAND = "SWStyle_OffsetEntities"


def register():
    global _WATCH
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, OffsetCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
    if _WATCH is None:
        _WATCH = FollowerWatch()
        App.addDocumentObserver(_WATCH)
