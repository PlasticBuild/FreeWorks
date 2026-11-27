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
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from . import unitbox

from . import contextbar, dimtools, relationspm, sketchtoolpm

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchPattern"
SPACING_NAME = "PatternSpacing"
_COPYABLE = ("Coincident", "Horizontal", "Vertical", "Parallel", "Perpendicular", "Tangent", "Equal",
             "PointOnObject", "Symmetric")


DROPPABLE = ("Equal", "Parallel", "Coincident", "PointOnObject", "Perpendicular", "Horizontal", "Vertical")
DIMENSIONS = ("Distance", "DistanceX", "DistanceY", "Angle", "Radius", "Diameter")


def _redundant(sketch):
    # two solves: the first one right after a delete can still report the sketch as it was
    # before the delete, redundant relations and DoF both (review 1119 pat1)
    sketch.solve()
    sketch.solve()
    return [i - 1 for i in getattr(sketch, "RedundantConstraints", []) or []]


def _dof(sketch):
    try:
        return int(sketch.DoF)
    except Exception:
        return None


def _delete(sketch, i):
    """delConstraint(i) that keeps the constraint expressions above i on their constraints
    (FreeCAD keys them by index and leaves them where they were)."""
    moved = []
    try:
        for path, expr in list(sketch.ExpressionEngine):
            m = re.match(r"^\.Constraints\[(\d+)\]$", path)
            if m and int(m.group(1)) >= i:
                moved.append((int(m.group(1)), expr))
                sketch.setExpression(path, None)
    except Exception:
        moved = []
    sketch.delConstraint(i)
    for m, expr in moved:
        if m > i:
            try:
                sketch.setExpression(".Constraints[%d]" % (m - 1), expr)
            except Exception as _fw_err:
                _fw_log("sketchpattern.py:78", _fw_err)


def drop_redundant(sketch, start):
    ""




    try:
        sketch.RedundantConstraints
    except Exception:
        return
    # the search runs first on a copy in a hidden document: there each switch-off and solve
    # costs no redraw (review 1119 pat2). What it finds is deleted here in one call, and the
    # search then runs here as well, where it normally reads the sketch clean at once.
    first = sorted(set(_offline_search(sketch, start)))
    _delete_many(sketch, first)
    second = sorted(set(_search(sketch, start)))
    _delete_many(sketch, second)
    # both lists in the numbering from before the first delete
    import bisect
    survivors = [i for i in range(len(sketch.Constraints) + len(first) + len(second)) if i not in set(first)]
    return first + [survivors[j] for j in second]


def _learn_template(sketch, trial):
    """Runs trial(copy) on a copy of the sketch in a hidden document and returns what it
    returns (the template keys of the relations found redundant); empty on any failure."""
    keep = [i for i, c in enumerate(sketch.Constraints)
            if not any(x is not None and -2000 < x <= -3 for x in (c.First, c.Second, c.Third))]
    doc = None
    active = App.ActiveDocument
    try:
        doc = App.newDocument("FwPatternTemplate", hidden=True, temp=True)
        doc.UndoMode = 0      # not part of the page's undo step (reviewer 11-19)
        tmp = doc.addObject("Sketcher::SketchObject", "Trial")
        tmp.addGeometry(sketch.Geometry)
        for i, g in enumerate(sketch.Geometry):
            if sketch.getConstruction(i):
                tmp.setConstruction(i, True)
        cons = sketch.Constraints
        tmp.addConstraint([cons[i] for i in keep])
        return set(trial(tmp) or ())
    except Exception as _fw_err:
        _fw_log("sketchpattern.py:_learn_template", _fw_err)
        return set()
    finally:
        if doc is not None:
            try:
                App.closeDocument(doc.Name)
            except Exception as _fw_err:
                _fw_log("sketchpattern.py:_learn_template close", _fw_err)
        try:
            if active is not None and App.ActiveDocument is not active:
                App.setActiveDocument(active.Name)
        except Exception as _fw_err:
            _fw_log("sketchpattern.py:_learn_template active", _fw_err)


def _offline_search(sketch, start):
    """_search on a copy of the sketch in a hidden document; returns the indices found in the
    sketch's own numbering. Constraints on external geometry stay out of the copy (the search
    on the sketch itself then deals with any redundancy they take part in)."""
    keep = [i for i, c in enumerate(sketch.Constraints)
            if not any(x is not None and -2000 < x <= -3 for x in (c.First, c.Second, c.Third))]
    if not any(i >= start for i in keep):
        return []
    doc = None
    active = App.ActiveDocument
    try:
        doc = App.newDocument("FwPatternCheck", hidden=True, temp=True)
        doc.UndoMode = 0      # not part of the page's undo step (reviewer 11-19)
        tmp = doc.addObject("Sketcher::SketchObject", "Check")
        tmp.addGeometry(sketch.Geometry)
        cons = sketch.Constraints
        tmp.addConstraint([cons[i] for i in keep])
        for j, i in enumerate(keep):
            if not cons[i].IsActive:
                tmp.setActive(j, False)
        start_j = next(j for j, i in enumerate(keep) if i >= start)
        return [keep[j] for j in _search(tmp, start_j)]
    except Exception as _fw_err:
        _fw_log("sketchpattern.py:_offline_search", _fw_err)
        return []
    finally:
        if doc is not None:
            try:
                App.closeDocument(doc.Name)
            except Exception as _fw_err:
                _fw_log("sketchpattern.py:_offline_search close", _fw_err)
        try:
            if active is not None and App.ActiveDocument is not active:
                App.setActiveDocument(active.Name)
        except Exception as _fw_err:
            _fw_log("sketchpattern.py:_offline_search active", _fw_err)


def _search(sketch, start, droppable=DROPPABLE):
    """The pattern's relations (index >= start) that are redundant. They are left switched off
    for the caller to delete. A redundant dimension becomes driven instead."""
    off = []                               # switched off as redundant
    kept = []                              # named by the solver, but switching them off freed the sketch
    fresh = None                           # the reading taken right after the last switch-off
    # relations are switched off (setActive), not deleted, while the search runs: a delete shifts
    # every constraint index and each expression above it had to be moved, one recompute each,
    # which made a 12-copy circular pattern take 5 minutes (review 1119 pat2)
    try:
        for _round in range(400):
            red = fresh if fresh is not None else _redundant(sketch)
            fresh = None
            if not red:
                break
            cons = sketch.Constraints
            mine = [i for i in red if start <= i < len(cons) and i not in off and i not in kept]
            if mine:
                i = max(mine)
                if cons[i].Type in droppable:
                    before = _dof(sketch)
                    sketch.setActive(i, False)
                    fresh = _redundant(sketch)
                    after = _dof(sketch)
                    if before is not None and after is not None and after > before:
                        # the solver named a relation that was still needed (at an exact
                        # rectangle its rank test is not reliable): it stays
                        sketch.setActive(i, True)
                        kept.append(i)
                        fresh = None
                    else:
                        off.append(i)
                    continue
                if cons[i].Type in DIMENSIONS and cons[i].Driving:
                    sketch.setDriving(i, False)
                    continue
                if droppable is DROPPABLE:
                    break
            dof = _dof(sketch)
            for i in range(len(cons) - 1, start - 1, -1):
                c = cons[i]
                if i in off or c.Type not in ("Equal", "Parallel") or c.Name:
                    continue
                sketch.setActive(i, False)
                _redundant(sketch)
                if dof is not None and _dof(sketch) == dof:
                    off.append(i)                  # no freedom gained: it was one of the redundant ones
                    break
                sketch.setActive(i, True)          # it was needed: back on
            else:
                break
    except Exception as _fw_err:
        _fw_log("sketchpattern.py:_search", _fw_err)
    return off


def _delete_many(sketch, indices):
    """Deletes these constraints in one call. FreeCAD keys constraint expressions by index and
    leaves them where they were, so the ones above are moved down to their constraints once."""
    import bisect
    gone = sorted(set(indices))
    if not gone:
        return
    moved = []
    try:
        for path, expr in list(sketch.ExpressionEngine):
            m = re.match(r"^\.Constraints\[(\d+)\]$", path)
            if m and int(m.group(1)) >= gone[0]:
                moved.append((int(m.group(1)), expr))
                sketch.setExpression(path, None)
    except Exception:
        moved = []
    sketch.delConstraints(gone)
    for m, expr in moved:
        if m in gone:
            continue
        try:
            sketch.setExpression(".Constraints[%d]" % (m - bisect.bisect_left(gone, m)), expr)
        except Exception as _fw_err:
            _fw_log("sketchpattern.py:_delete_many", _fw_err)


def _params():
    return App.ParamGet(PARAMS)


def anchor(sketch, geo):
    """The point an instance hangs on: a circle's or arc's centre, else the start point."""
    kind = dimtools._kind(sketch.Geometry[geo])
    return (geo, 3) if kind in ("circle", "arc") else (geo, 1)


def _spacing(count, total, equal):
    if count < 2:
        return 0.0
    if not equal:
        return total
    return total / count if abs(abs(total) - 360.0) < 1e-9 else total / (count - 1)


def _free_name(sketch, base):
    names = {c.Name for c in sketch.Constraints}
    name, k = base, 1
    while name in names:
        k += 1
        name = "%s%d" % (base, k)
    return name


def make_pattern(sketch, entities, centre, count, total_deg, equal=True, reverse=False,
                 dim_radius=True, dim_spacing=True, skip=(), centre_point=None, _drop=None, _learn=False):
    ""


    C = dimtools._constraint
    import Part
    from .fwsketch import helpers as _helpers
    entities = _helpers.with_helpers(sketch, [g for g in entities if g >= 0])   # an arc slot's centre line comes along (reviewer 11-19)
    _first_geo = sketch.GeometryCount
    entities = [g for g in sorted(set(entities)) if g >= 0]
    if not entities or count < 2:
        return []
    first_new = len(sketch.Constraints)
    step = _spacing(count, total_deg, equal) * (-1 if reverse else 1)
    if _drop is None and not _learn and count > 2:
        # every copy gets the same relations, so which of them are redundant is learnt once,
        # on a two-instance pattern in a hidden copy of the sketch, and those are left out of
        # every copy. The search over the whole pattern was what took minutes (review 1119 pat2).
        _drop = _learn_template(sketch, lambda tmp: make_pattern(
            tmp, entities, centre, 3, 2 * abs(step), True, step < 0, dim_radius, dim_spacing, (), None,
            _learn=True))
    _drop = set(_drop or ())
    tags = []                                    # (index in cons, template key) for the first copy
    learnt = {}                                  # constraint index: template key, learnt copy only
    gap_ids = []                                 # gap angles to tie to the spacing, after the clean-up
    spacing_name = None
    cx, cy = centre
    at_origin = abs(cx) < 1e-9 and abs(cy) < 1e-9
    cons = []
    if at_origin:
        centre_ref = (-1, 1)
    elif centre_point is not None:

        # (fix305: a second point of its own, tied to nothing, let the picked one walk away)
        centre_ref = (int(centre_point[0]), int(centre_point[1]))
    else:
        centre_ref = (sketch.addGeometry(Part.Point(App.Vector(cx, cy, 0)), True), 1)
    ag, apos = anchor(sketch, entities[0])
    a0 = sketch.getPoint(ag, apos)
    radius = math.hypot(a0.x - cx, a0.y - cy)
    skip = {int(k[0] if isinstance(k, (tuple, list)) else k) for k in skip} - {0}
    instances = []
    locks = []                                   # (seed line, its copy, k): H/V lines turned
    sites = []                                   # (k, mapping or None)
    original = sketch.Geometry
    for k in range(1, count):
        turn = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), step * k), App.Vector(cx, cy, 0))
        if k in skip:
            sites.append((k, None, turn))
            instances.append({})
            continue
        mapping = {}
        for g in entities:
            copy = original[g].copy()
            copy.transform(turn.toMatrix())
            mapping[g] = sketch.addGeometry(copy, sketch.getConstruction(g))
        instances.append(mapping)
        sites.append((k, mapping, turn))
        rel = []
        for c in sketch.Constraints:
            if c.Type not in _COPYABLE or (c.Name or "").startswith("SWBlock:"):    # a block's hidden hold (reviewer 11-19)
                continue
            refs = [x for x in (c.First, c.Second, c.Third) if x is not None and x > -2000]
            if not refs or any(x not in mapping for x in refs if x >= 0) or not any(x >= 0 for x in refs):
                continue
            if any(x < 0 for x in refs):
                continue
            args = [c.Type, mapping[c.First], c.FirstPos]
            if c.Second is not None and c.Second > -2000:
                args += [mapping[c.Second], c.SecondPos]
            if c.Type == "Symmetric" and c.Third is not None and c.Third > -2000:
                args += [mapping[c.Third], c.ThirdPos]
            if c.Type in ("Equal", "Parallel", "Perpendicular", "Tangent") and c.FirstPos == 0 and c.SecondPos == 0:
                args = [c.Type, mapping[c.First], mapping[c.Second]]
            elif c.Type in ("Horizontal", "Vertical") and c.Second is not None and c.Second <= -2000:
                # a rotated copy is no longer horizontal or vertical: it keeps its turn from the
                # seed instead, so a fully defined seed gives fully defined instances (2025)
                locks.append((c.First, mapping[c.First], k))
                continue
            try:
                rel.append(C(*args))
            except Exception as _fw_err:
                _fw_log("sketchpattern.py:220", _fw_err)
        # the pattern's Equals last: of a redundant group the newest is the one named, so a
        # spare Equal goes and the copy keeps the seed's own relations (review 1119 pat1/pat2)
        for g, n in mapping.items():
            if dimtools._kind(original[g]) in ("line", "circle", "arc"):
                rel.append(C("Equal", g, n))
        for p, c in enumerate(rel):
            if ("r", p) in _drop:
                continue
            if k == (count - 1 if _learn else 1):
                tags.append((len(cons), ("r", p)))
            cons.append(c)
    if radius > 1e-9:
        anchors = [(ag, apos)] + [(m[ag], apos) if m else None for _k, m, _t in sites]
        lines = []
        for k, a in enumerate(anchors):
            if a is not None:
                end = sketch.getPoint(*a)
            else:                                # a skipped site: the spoke alone holds it
                end = sites[k - 1][2].multVec(App.Vector(a0.x, a0.y, 0))
            line = sketch.addGeometry(Part.LineSegment(App.Vector(cx, cy, 0), App.Vector(end.x, end.y, 0)), True)
            lines.append(line)
            cons.append(C("Coincident", line, 1, centre_ref[0], centre_ref[1]))
            if a is not None:
                cons.append(C("Coincident", line, 2, a[0], a[1]))
        anchors = [(line, 2) for line in lines]      # the spoke ends: skipped sites included
        for line in lines[1:]:
            cons.append(C("Equal", lines[0], line))
        if dim_radius:
            cons.append(C("Distance", lines[0], radius))
        base = len(sketch.Constraints)
        sketch.addConstraint(cons)
        learnt = {base + j: key for j, key in tags}
        tags = []
        cons = []
        if dim_spacing and len(lines) > 1:
            # one spacing dimension, between the first two spokes; the other gaps follow it through
            # Equal construction chords (equal chords on equal spokes are equal angles), and each
            # turned H/V line keeps its angle to its own spoke. No expressions: setting one cost a
            # full redraw each and a 12-copy pattern took minutes (review 1119 pat2)
            gaps = []                            # (index in cons) of the gap angles after the first
            first_angle = len(sketch.Constraints)
            for k in range(1, len(lines)):
                a, b = (lines[k - 1], lines[k]) if step > 0 else (lines[k], lines[k - 1])
                if k > 1:
                    gaps.append(len(cons))
                cons.append(C("Angle", a, 1, b, 1, math.radians(abs(step))))
            geo = sketch.Geometry
            first_k = count - 1 if _learn else 1
            seen = {}
            for g, n, k in locks:
                q = seen.get(k, 0)
                seen[k] = q + 1
                if ("l", q) in _drop:
                    continue
                if k == first_k:
                    tags.append((len(cons), ("l", q)))
                spoke = lines[k]
                du = geo[spoke].EndPoint - geo[spoke].StartPoint
                dw = geo[n].EndPoint - geo[n].StartPoint
                pos = 1
                if du.x * dw.x + du.y * dw.y < 0:
                    # measured from the line's other end, so the angle stays within 90 degrees:
                    # at 180 FreeCAD's angle wraps and the solver fails on a spacing edit
                    dw, pos = -dw, 2
                between = math.atan2(du.x * dw.y - du.y * dw.x, du.x * dw.x + du.y * dw.y)
                if between >= 0:
                    cons.append(C("Angle", spoke, 1, n, pos, between))
                else:
                    cons.append(C("Angle", n, pos, spoke, 1, -between))
            base = len(sketch.Constraints)
            sketch.addConstraint(cons)
            learnt.update({base + j: key for j, key in tags})
            tags = []
            cons = []
            spacing_name = _free_name(sketch, SPACING_NAME)
            sketch.renameConstraint(first_angle, spacing_name)
            # the other gaps follow the named one through expressions, set once the clean-up has
            # run: a delete below an expression meant moving every expression, one recompute each
            # (review 1119 pat2)
            gap_ids = [base + j for j in gaps]
        elif equal and len(anchors) > 2:
            # no spacing dimension, yet the spacing stays equal (tester SK9-08: a radius edit
            # left 42/48 degree gaps): construction chords between neighbours are Equal; on equal
            # spokes, equal chords mean equal angles
            chords = []
            pairs = list(zip(anchors, anchors[1:]))
            if abs(abs(total_deg) - 360.0) < 1e-9:
                pairs.append((anchors[-1], anchors[0]))      # full circle: the closing gap too
            for (g1, p1), (g2, p2) in pairs:
                e1 = sketch.getPoint(g1, p1)
                e2 = sketch.getPoint(g2, p2)
                ch = sketch.addGeometry(Part.LineSegment(App.Vector(e1.x, e1.y, 0), App.Vector(e2.x, e2.y, 0)), True)
                chords.append(ch)
                cons.append(C("Coincident", ch, 1, g1, p1))
                cons.append(C("Coincident", ch, 2, g2, p2))
            for ch in chords[1:]:
                cons.append(C("Equal", chords[0], ch))
            sketch.addConstraint(cons)
            cons = []
    elif cons:
        base = len(sketch.Constraints)
        sketch.addConstraint(cons)
        learnt = {base + j: key for j, key in tags}
    if _learn:
        # on the trial only spare Equals go: a copy that keeps all its corners joined and its turn
        # solves reliably; with a corner left to the lengths the spacing could not be edited
        return {learnt[i] for i in _search(sketch, first_new, ("Equal", "Parallel")) if i in learnt}
    gone = drop_redundant(sketch, first_new) or []
    if spacing_name and gap_ids:
        import bisect
        gone = sorted(gone)
        hidden = []
        for i in gap_ids:
            if i in gone:
                continue
            try:
                j = i - bisect.bisect_left(gone, i)

                # (<name>_t<k>: exprkeep takes them with it when it is deleted)
                sketch.renameConstraint(j, _free_name(sketch, "%s_t%d" % (spacing_name, j)))
                hidden.append(j)
                sketch.setExpression(".Constraints[%d]" % j, ".Constraints.%s" % spacing_name)
            except Exception as _fw_err:
                _fw_log("sketchpattern.py:gap expression", _fw_err)
        if hidden:
            try:
                sketch.setVirtualSpace(hidden, True)
            except Exception as _fw_err:
                _fw_log("sketchpattern.py:gap hide", _fw_err)
    _helpers.hide_new(sketch, _first_geo)
    sketch.solve()
    return [sorted(m.values()) for m in instances]


class CircularPatternPage(sketchtoolpm.ToolPage):
    TITLE = "Circular Pattern"
    ICON = "SKETCH_CIR_PATTERN"
    PIXMAP = "Sketcher_Rotate"
    TRANSACTION = "Circular Sketch Pattern"
    KIND = "circular"
    STATE = ("cx", "cy", "reverse", "count", "angle", "equal", "dim_radius", "dim_spacing", "show_count")

    def build(self):
        p = _params()
        # the sketch as the page found it: Cancel and every new preview go back to exactly this
        # (an aborted history entry alone left an earlier preview behind, tester SK9-09)
        self._original = (len(self.sketch.Geometry), len(self.sketch.Constraints))
        self.entities = []
        self.instances = []
        self.skip = []                   # [(k,)]: instance k (1 .. count-1) left out
        self.skip_active = False
        self._filling = True
        g = self.group("Parameters")

        self.centre_active = False
        self.centre_box = QtWidgets.QListWidget(g.body)
        self.centre_box.setObjectName("SWPatternCentre")
        self.centre_box.setFixedHeight(26)
        self.centre_box.setToolTip("Center: click here, then a point, an arc or a circle to pattern about")
        self.centre_box.addItem("Point1@Origin")
        self.centre_box.installEventFilter(self)
        g.content.addWidget(self.centre_box)
        form = QtWidgets.QFormLayout()
        self.cx = self._number(g, 0.0, " mm", -1e6, 1e6, "Center X")
        self.cy = self._number(g, 0.0, " mm", -1e6, 1e6, "Center Y")
        self.reverse = QtWidgets.QCheckBox("Reverse direction", g.body)
        self.count = QtWidgets.QSpinBox(g.body)
        self.count.setRange(2, 1000)
        self.count.setValue(p.GetInt("Instances", 4))
        self.count.setToolTip("Number of instances, the original included")
        self.angle = self._number(g, p.GetFloat("Angle", 360.0), "°", -360.0, 360.0, "Total angle")
        self.equal = QtWidgets.QCheckBox("Equal spacing", g.body)
        self.equal.setChecked(p.GetBool("EqualSpacing", True))

        # changing them moves the centre, moving the centre changes them
        self.radius = self._number(g, 0.0, " mm", 0.0, 1e6, "Radius")
        self.radius.setObjectName("SWCircularPatternRadius")
        self.arc_angle = self._number(g, 0.0, "°", -360.0, 360.0, "Arc Angle")
        self.arc_angle.setObjectName("SWCircularPatternArcAngle")
        form.addRow("Center X:", self.cx)
        form.addRow("Center Y:", self.cy)
        form.addRow("Radius:", self.radius)
        form.addRow("Arc Angle:", self.arc_angle)
        g.content.addLayout(form)
        g.content.addWidget(self.reverse)
        form = QtWidgets.QFormLayout()
        form.addRow("Angle:", self.angle)
        form.addRow("Instances:", self.count)
        g.content.addLayout(form)
        g.content.addWidget(self.equal)
        self.dim_radius = QtWidgets.QCheckBox("Dimension radius", g.body)
        self.dim_radius.setChecked(p.GetBool("DimensionRadius", True))
        self.dim_spacing = QtWidgets.QCheckBox("Dimension angular spacing", g.body)
        self.dim_spacing.setChecked(p.GetBool("DimensionSpacing", True))
        self.show_count = QtWidgets.QCheckBox("Display instance count", g.body)
        self.show_count.setChecked(p.GetBool("DisplayCount", True))
        for box in (self.dim_radius, self.dim_spacing, self.show_count):
            g.content.addWidget(box)
        self.callout = QtWidgets.QLabel("", g.body)
        self.callout.setObjectName("SWToolInfo")
        g.content.addWidget(self.callout)
        self.view_callout = None
        try:
            from . import filletpm
            view = filletpm._view_widget()
            if view is not None:
                self.view_callout = filletpm.Callout(self, view)
                self.view_callout.setObjectName("SWPatternCallout")
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: pattern callout: %s\n" % error)
        g = self.group("Entities to Pattern")
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWSelectedEntities")
        self.list.setFixedHeight(56)
        g.content.addWidget(self.list)
        g = self.group("Instances to Skip")
        self.skip_list = QtWidgets.QListWidget(g.body)
        self.skip_list.setObjectName("SWSkipInstances")
        self.skip_list.setFixedHeight(56)
        self.skip_list.setToolTip("Click here, then click the instances to skip in the view; "
                                  "double-click an entry to bring it back")
        self.skip_list.installEventFilter(self)
        self.list.installEventFilter(self)
        self.skip_list.itemDoubleClicked.connect(self._unskip)
        g.content.addWidget(self.skip_list)
        for w in (self.cx, self.cy, self.angle, self.count):
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self.changed)
        for w in (self.radius, self.arc_angle):
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self._polar_changed)
        for box in (self.reverse, self.equal, self.dim_radius, self.dim_spacing, self.show_count):
            box.toggled.connect(self.changed)
        self._filling = False
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        for sub in relationspm.picked_subs(self.sketch):
            self.picked(sub)
        from .sketchmove import _FreeClick
        self.free = _FreeClick(self)          # clicks in the view while Instances to Skip is active
        _from_edit(self)

    def remake(self, rec):
        st = rec["state"]
        make_pattern(self.sketch, rec["seed"], (st["cx"], st["cy"]), st["count"], st["angle"], st["equal"],
                     st["reverse"], st["dim_radius"], st["dim_spacing"], [tuple(k) for k in st.get("skip", [])])

    # --- Instances to Skip (as Linear Pattern) ----------------------------------------------------
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter259(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter sketchpattern.py: %s\n" % exc)
            return False

    def _fw_filter259(self, obj, event):
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            if obj is getattr(self, "centre_box", None):
                self._centre_on(True)
            elif obj is getattr(self, "skip_list", None):
                self._centre_on(False)
                self._skip_box(True)
            elif obj is getattr(self, "list", None):
                self._centre_on(False)
                self._skip_box(False)
        return False

    def _centre_on(self, on):
        self.centre_active = bool(on)
        box = self.centre_box
        box.setProperty("swActive", self.centre_active)
        box.style().unpolish(box)
        box.style().polish(box)

    def _centre_picked(self, item):
        """A point, the origin, or an arc/circle (its centre) becomes the pattern's centre."""
        from . import sketchtoolpm as _stp
        g, pos = item.geo, item.pos
        if g == -1 and pos in (1, relationspm.START):
            q, name = App.Vector(0, 0, 0), "Point1@Origin"
        else:
            if pos not in (1, 2, 3):
                if g >= 0 and dimtools._kind(self.sketch.Geometry[g]) in ("circle", "arc"):
                    pos = 3
                elif g >= 0 and dimtools._kind(self.sketch.Geometry[g]) == "point":
                    pos = 1
                else:
                    return False
            try:
                q = self.sketch.getPoint(g, pos)
            except Exception:
                return False
            name = getattr(item, "name", "") if item.pos in (1, 2, 3) else ""
            if not name.startswith("Point"):
                name = _stp.point_name(self.sketch, g, pos) if g >= 0 else "Point"
        self.centre_box.clear()
        self.centre_box.addItem(name)
        # fix305: known before Center X/Y change, so the pattern their change makes goes round this point
        self.centre_point = (g, pos, q.x, q.y) if g >= 0 or g <= -3 else None
        self.cx.setValue(q.x)
        self.cy.setValue(q.y)
        self._centre_on(False)
        return True

    def _centre_point(self):
        """(geo, pos) of the picked centre point while Center X/Y still say where it is."""
        cp = getattr(self, "centre_point", None)
        tol = max(1e-6, 0.6 * 10.0 ** -self.cx.decimals())     # fix305: Center X/Y show 3 decimals
        if cp is None or abs(cp[2] - self.cx.value()) > tol or abs(cp[3] - self.cy.value()) > tol:
            return None
        return cp[:2]

    def _skip_box(self, on):
        self.skip_active = bool(on)
        for box, active in ((self.skip_list, self.skip_active), (self.list, not self.skip_active)):
            box.setProperty("swActive", active)
            box.style().unpolish(box)
            box.style().polish(box)

    def wants_point(self):
        return self.skip_active and bool(self.entities)

    def point_picked(self, point, item):
        self._skip_clicked(point.x, point.y)

    def follow(self, point):
        pass

    def sites(self):
        """{k: (x, y)} where instance k's anchor goes (0 = the original)."""
        if not self.entities:
            return {}
        g, pos = anchor(self.sketch, self.entities[0])
        try:
            a0 = self.sketch.getPoint(g, pos)
        except Exception:
            return {}
        cx, cy = self.cx.value(), self.cy.value()
        step = _spacing(self.count.value(), self.angle.value(), self.equal.isChecked()) * \
            (-1 if self.reverse.isChecked() else 1)
        out = {}
        for k in range(self.count.value()):
            t = math.radians(step * k)
            dx, dy = a0.x - cx, a0.y - cy
            out[k] = (cx + dx * math.cos(t) - dy * math.sin(t), cy + dx * math.sin(t) + dy * math.cos(t))
        return out

    def _skip_clicked(self, x, y):
        where = self.sites()
        if len(where) < 2:
            return
        best = min(where, key=lambda k: math.hypot(where[k][0] - x, where[k][1] - y))
        gap = min(math.hypot(where[0][0] - where[k][0], where[0][1] - where[k][1]) for k in where if k) or 1.0
        if best == 0 or math.hypot(where[best][0] - x, where[best][1] - y) > 0.5 * gap:
            return
        key = (best,)
        if key in self.skip:
            self.skip.remove(key)
        else:
            self.skip.append(key)
        self._fill_skip()
        self.changed()

    def _fill_skip(self):
        self.skip_list.clear()
        for (k,) in sorted(self.skip):
            self.skip_list.addItem("Instance %d" % (k + 1))

    def _unskip(self, item):
        row = self.skip_list.row(item)
        keys = sorted(self.skip)
        if 0 <= row < len(keys):
            self.skip.remove(keys[row])
            self._fill_skip()
            self.changed()

    def reject(self):
        super().reject()
        from . import patternedit
        patternedit.restore(self)

    def _number(self, g, value, suffix, low, high, tip):
        box = unitbox.UnitSpinBox(g.body)
        box.setRange(low, high)
        box.setDecimals(3)
        box.setSuffix(suffix)
        box.setValue(value)
        box.setToolTip(tip)
        return box

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("sketchpattern.py:552", _fw_err)
        if item is not None and self.centre_active:
            self._centre_picked(item)
            return
        if item is not None and item.geo >= 0 and self.wants_point():
            g, pos = (item.geo, item.pos) if item.pos in (1, 2, 3) else anchor(self.sketch, item.geo)
            self.point_picked(self.sketch.getPoint(g, pos), item)      # Instances to Skip
            return
        if item is None or item.geo < 0 or item.geo in self.entities:
            return
        if self.instances and item.geo >= self._base:
            return          # a copy: not a pattern entity
        if item.pos not in (relationspm.NONE,) and dimtools._kind(self.sketch.Geometry[item.geo]) != "point":
            return          # an end point: pick the entity itself
        self.entities.append(item.geo)
        self.list.addItem(_entity_name(self.sketch, item.geo))
        self.changed()

    def selection_changed(self):
        pass

    def undo_work(self):
        super().undo_work()
        orig = getattr(self, "_original", None)
        if orig is None:
            return
        sk = self.sketch
        try:
            extra = list(range(orig[0], len(sk.Geometry)))
            if extra:
                sk.delGeometries(extra)
            for i in range(len(sk.Constraints) - 1, orig[1] - 1, -1):
                sk.delConstraint(i)
            if extra or len(sk.Constraints) != orig[1]:
                sk.solve()
                sketchtoolpm._refresh(sk)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Circular Pattern clean-up: %s\n" % error)

    def _anchor_point(self):
        if not self.entities:
            return None
        try:
            g, pos = anchor(self.sketch, sorted(set(self.entities))[0])
            return self.sketch.getPoint(g, pos)
        except Exception:
            return None

    def _show_polar(self):
        """Radius and Arc Angle from the centre boxes."""
        a = self._anchor_point()
        if a is None:
            return
        r = math.hypot(a.x - self.cx.value(), a.y - self.cy.value())
        ang = math.degrees(math.atan2(a.y - self.cy.value(), a.x - self.cx.value())) if r > 1e-9 else 0.0
        self._filling = True
        try:
            self.radius.setValue(r)
            self.arc_angle.setValue(ang)
        finally:
            self._filling = False

    def _polar_changed(self, *args):
        """Radius or Arc Angle typed: the centre moves, the entities stay."""
        if self._filling:
            return
        a = self._anchor_point()
        if a is None:
            return
        r, t = self.radius.value(), math.radians(self.arc_angle.value())
        self._filling = True
        try:
            self.cx.setValue(a.x - r * math.cos(t))
            self.cy.setValue(a.y - r * math.sin(t))
        finally:
            self._filling = False
        self.changed()

    def changed(self, *args):
        if self._filling:
            return
        self.undo_work()
        self._show_polar()
        self.instances = []
        if not self.entities:
            self.callout.setText("")
            self._show_view_callout()
            return
        self.begin()
        self._base = len(self.sketch.Geometry)
        try:
            self.instances = make_pattern(self.sketch, self.entities, (self.cx.value(), self.cy.value()),
                                          self.count.value(), self.angle.value(), self.equal.isChecked(),
                                          self.reverse.isChecked(), self.dim_radius.isChecked(),
                                          self.dim_spacing.isChecked(),
                                          [k for k in self.skip if k[0] < self.count.value()],
                                          self._centre_point())
        except Exception as error:
            self.show_note("Could not pattern: %s" % error, True)
            return
        sketchtoolpm._refresh(self.sketch)
        bad = list(self.sketch.ConflictingConstraints) + list(self.sketch.RedundantConstraints)
        self.show_note("The pattern over-defines the sketch." if bad else "", bool(bad))
        spacing = _spacing(self.count.value(), self.angle.value(), self.equal.isChecked())
        self.callout.setText("Instances: %d   Spacing: %s°" % (self.count.value(), _num(spacing))
                             if self.show_count.isChecked() else "")
        self._show_view_callout(spacing)

    def _show_view_callout(self, spacing=None):
        c = self.view_callout
        if c is None:
            return
        a = self._anchor_point() if self.entities and self.show_count.isChecked() else None
        if a is None:
            c.anchor = None
            c.hide()
            return
        if spacing is None:
            spacing = _spacing(self.count.value(), self.angle.value(), self.equal.isChecked())
        c.set_rows([("Instances", float(self.count.value()), "", self.set_instances),
                    ("Spacing", spacing, "°", self.set_spacing)], self.sketch.getGlobalPlacement().multVec(a))

    def set_instances(self, value):
        """The callout's Instances, typed: the PM's Instances box follows."""
        self.count.setValue(int(round(value)))

    def set_spacing(self, value):
        """The callout's Spacing, typed: the Angle that gives it (with Equal spacing, over the instances)."""
        n, total = self.count.value(), self.angle.value()
        if not self.equal.isChecked() or n < 2:
            self.angle.setValue(value)
        elif abs(abs(total) - 360.0) < 1e-9 and abs(value * n) <= 360.0 + 1e-9:
            self.angle.setValue(value * n)
        else:
            self.angle.setValue(value * (n - 1))

    def finish(self):
        from . import patternedit
        patternedit.remember(self)
        p = _params()
        p.SetInt("Instances", self.count.value())
        p.SetFloat("Angle", self.angle.value())
        p.SetBool("EqualSpacing", self.equal.isChecked())
        p.SetBool("DimensionRadius", self.dim_radius.isChecked())
        p.SetBool("DimensionSpacing", self.dim_spacing.isChecked())
        p.SetBool("DisplayCount", self.show_count.isChecked())

    def closing(self):
        c, self.view_callout = getattr(self, "view_callout", None), None
        if c is not None:
            try:
                c.timer.stop()
                c.hide()
                c.deleteLater()
            except Exception as _fw_err:
                _fw_log("sketchpattern.py:707", _fw_err)
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("sketchpattern.py:711", _fw_err)
        self.observer.page = None
        free = getattr(self, "free", None)
        if free is not None:
            try:
                free.detach()
            except Exception as _fw_err:
                _fw_log("sketchpattern.py:718", _fw_err)


def _from_edit(page):
    """Edit Linear/Circular Pattern opened this page: its old settings and seed come back."""
    from . import patternedit
    rec = patternedit._pending
    if rec is None or rec.get("kind") != page.KIND:
        return
    page._filling = True
    try:
        patternedit.apply_state(page, rec)
    finally:
        page._filling = False
    page.changed()


def _entity_name(sketch, geo):
    return relationspm._entity_names(sketch.Geometry)[geo]


def _num(v):
    return ("%.3f" % v).rstrip("0").rstrip(".")


class CircularPatternCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_Rotate", "MenuText": "Circular Sketch Pattern",
                "ToolTip": "Copies sketch entities around a center, tied by a radius and an angular spacing",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(CircularPatternPage(sketch))


COMMAND = "SWStyle_CircularSketchPattern"


def register():
    try:
        from . import linearpattern, patternedit, ordinatealign
        linearpattern.register()
        ordinatealign.register()        # Tools > Dimensions > Align Ordinate (kept here with the other Tools menu adds)
        from . import sketchchamfer, fitsplinepm
        sketchchamfer.register()
        fitsplinepm.install()           # Constrained fit splines follow their source
        from . import sketchfirstlive
        sketchfirstlive.register()      # Sketch tab tools live with no sketch open
        from . import solidfirstlive
        solidfirstlive.register()       # Features tab buttons live in a part with no solid yet
        from . import sketchrepair
        sketchrepair.register()         # Repair Sketch inside a 2D sketch
        from . import sketchinktab
        sketchinktab.register()         # the Sketch Ink tab's Color flyout
        from . import dimensionpm
        dimensionpm.register()          # the Dimension PropertyManager (Value, Leaders, Other)
        from . import sketchpicture
        sketchpicture.register()        # Sketch Picture with its PropertyManager
        for name, kind, cls, menu in (
                ("SWStyle_EditLinearPattern", "linear", linearpattern.LinearPatternPage, "Edit Linear Pattern..."),
                ("SWStyle_EditCircularPattern", "circular", CircularPatternPage, "Edit Circular Pattern...")):
            if name not in Gui.listCommands():
                Gui.addCommand(name, patternedit.EditCommand(kind, cls, menu))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Linear Sketch Pattern not added: %s\n" % error)
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, CircularPatternCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
