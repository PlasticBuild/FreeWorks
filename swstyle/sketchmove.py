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
from . import unitbox

from . import contextbar, dimtools, relationspm, sketchtoolpm
from .widgets import alive
from . import geomkeep

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchMove"
_POSITION_DIMENSIONS = ("DistanceX", "DistanceY")


def _params():
    return App.ParamGet(PARAMS)


def _refs(c):
    return [x for x in (c.First, c.Second, c.Third) if x is not None and x > -2000]


def break_outside_relations(sketch, entities):
    """Deletes the constraints that tie entities to anything not in entities (origin and axes count
    as outside), and the position dimensions of single entity points; how many went."""
    inside = set(entities)
    doomed = []
    for i, c in enumerate(sketch.Constraints):
        refs = _refs(c)
        if not any(r in inside for r in refs):
            continue
        outside = any(r not in inside for r in refs)
        lone_position = c.Type in _POSITION_DIMENSIONS and len(refs) == 1
        lock = c.Type == "Block"
        if outside or lone_position or lock:
            doomed.append(i)
    for i in reversed(doomed):
        sketch.delConstraint(i)
    return len(doomed)


def _turned(sketch, entities, placement, in_place=False):
    """The entities moved by placement. in_place: for putting back over the originals, so each keeps
    its sketch state and Tag; otherwise plain copies, for adding as new geometry."""
    out = {}
    have = geomkeep.read(sketch) if in_place else sketch.Geometry
    for g in entities:
        geo = have[g].clone() if in_place else have[g].copy()
        geo.transform(placement.toMatrix())
        out[g] = geo
    return out


_UNDEF = -2000


def _quarter(placement):
    """(quarter turns 0-3 or None for another angle, the turn in radians) of placement about z."""
    import math
    r = placement.Rotation
    turn = r.Angle * (1.0 if r.Axis.z >= 0 else -1.0)
    q = math.degrees(turn) / 90.0
    return (int(round(q)) % 4 if abs(q - round(q)) < 1e-7 else None), turn


def _geo_point(geo, pos):
    if pos == 1:
        return geo.StartPoint
    if pos == 2:
        return geo.EndPoint
    if pos == 3:
        return geo.Center if hasattr(geo, "Center") else App.Vector(geo.X, geo.Y, 0)
    return None


def _turned_relations(items, placement, point):
    """The relations among turned entities, made to follow the turn (dimension review 11-19):
    items are (constraint, driving, name); point(geo, pos) gives a point where it is after the turn.
    A quarter turn swaps Horizontal/Vertical and DistanceX/DistanceY; another angle drops H/V,
    makes a DistanceX/Y an aligned Distance of the same size and turns a line's Angle."""
    C = dimtools._constraint
    k, turn = _quarter(placement)
    if k == 0:
        return list(items)
    out = []
    level = []      # (geo, "Horizontal"/"Vertical") of lines whose H/V another angle drops
    for c, driving, name in items:
        t, two = c.Type, c.Second not in (None, _UNDEF)
        if t in ("Horizontal", "Vertical"):
            if k is None or k == 2:
                if k == 2:
                    out.append((c, driving, name))
                elif not two:
                    level.append((c.First, t))
                continue
            n = "Vertical" if t == "Horizontal" else "Horizontal"
            c = C(n, c.First, c.FirstPos, c.Second, c.SecondPos) if two else C(n, c.First)
        elif t in ("DistanceX", "DistanceY") and two:
            a, b = point(c.First, c.FirstPos), point(c.Second, c.SecondPos)
            if a is None or b is None:
                continue
            if k is None:
                c = C("Distance", c.First, c.FirstPos, c.Second, c.SecondPos, (b - a).Length)
            else:
                n = t if k % 2 == 0 else ("DistanceY" if t == "DistanceX" else "DistanceX")
                v = (b.x - a.x) if n == "DistanceX" else (b.y - a.y)
                c = C(n, c.First, c.FirstPos, c.Second, c.SecondPos, v) if v >= 0 else \
                    C(n, c.Second, c.SecondPos, c.First, c.FirstPos, -v)
        elif t == "Angle" and not two and c.FirstPos == 0:
            c = C("Angle", c.First, c.Value + turn)       # a line's angle to the X axis turns with it
        out.append((c, driving, name))
    # the lines that were level or plumb keep their angles to each other: the first one is the
    # reference, the others are Parallel or Perpendicular to it, so a rotated rectangle stays a

    seen = []
    for geo, t in level:
        if any(g == geo for g, _t in seen):
            continue
        if seen:
            ref, rt = seen[0]
            out.append((C("Parallel" if t == rt else "Perpendicular", ref, geo), True, ""))
        seen.append((geo, t))
    return out


def _add_relations(sketch, items):
    """Adds (constraint, driving, name) in one go, then sets the driven ones and the names."""
    if not items:
        return
    n0 = sketch.ConstraintCount
    sketch.addConstraint([c for c, _d, _n in items])
    for k, (_c, driving, name) in enumerate(items):
        try:
            if not driving:
                sketch.setDriving(n0 + k, False)
            if name:
                sketch.renameConstraint(n0 + k, name)
        except Exception as _fw_err:
            _fw_log("sketchmove.py:relations", _fw_err)


_TURNING = ("Horizontal", "Vertical", "DistanceX", "DistanceY", "Angle")


def move(sketch, entities, placement, keep_relations=False):
    """Moves entities by placement (sketch coordinates); their own relations follow a turn."""
    from .fwsketch import helpers as _helpers
    if not keep_relations:
        entities = _helpers.with_helpers(sketch, entities)
        break_outside_relations(sketch, entities)
    new = _turned(sketch, entities, placement, in_place=True)
    turned = []
    if _quarter(placement)[0] != 0:
        inside = set(entities)
        own = [i for i, c in enumerate(sketch.Constraints)
               if c.Type in _TURNING and _refs(c) and all(r in inside for r in _refs(c))]
        items = [(sketch.Constraints[i], sketch.Constraints[i].Driving, sketch.Constraints[i].Name) for i in own]
        turned = _turned_relations(items, placement,
                                   lambda g, pos: _geo_point(new[g], pos) if g in new else None)
        for i in reversed(own):
            sketch.delConstraint(i)
    ties = _outside_ties(sketch, entities) if keep_relations else []
    geos = geomkeep.read(sketch)
    for g, geo in new.items():
        geos[g] = geo
    sketch.Geometry = geos
    _add_relations(sketch, turned)
    _follow_ties(sketch, new, ties)
    sketch.solve()


def _outside_ties(sketch, entities):
    """fix302: (inside geo, pos, outside geo, pos) for each Coincident from a moved entity's point to an
    entity not moved (the origin and axes stay put)."""
    inside, out = set(entities), []
    for c in sketch.Constraints:
        if c.Type != "Coincident" or c.First is None or c.Second is None:
            continue
        a, b = (c.First, c.FirstPos), (c.Second, c.SecondPos)
        if a[0] in inside and b[0] not in inside and b[0] >= 0:
            out.append(a + b)
        elif b[0] in inside and a[0] not in inside and a[0] >= 0:
            out.append(b + a)
    return out


def _follow_ties(sketch, new, ties):
    ""

    if not ties:
        return
    geos = geomkeep.read(sketch)
    moved = False
    for g_in, p_in, g_out, p_out in ties:
        try:
            at = _geo_point(new[g_in], p_in) if g_in in new else None
            geo = geos[g_out]
            if at is None:
                continue
            at = App.Vector(at.x, at.y, 0)
            if isinstance(geo, Part.LineSegment) and p_out in (1, 2):
                a, b = (at, geo.EndPoint) if p_out == 1 else (geo.StartPoint, at)
                if (a - b).Length > 1e-9:
                    geo = geo.clone()
                    if p_out == 1:
                        geo.StartPoint = at
                    else:
                        geo.EndPoint = at
                    geos[g_out] = geo
                    moved = True
            elif isinstance(geo, Part.Point):
                geo = geo.clone(); geo.X, geo.Y = at.x, at.y
                geos[g_out] = geo
                moved = True
        except Exception as _fw_err:
            _fw_log("sketchmove.py: follow", _fw_err)
    if moved:
        sketch.Geometry = geos


def copy(sketch, entities, placement, keep_relations=False):
    ""





    C = dimtools._constraint
    from .fwsketch import helpers as _helpers
    entities = _helpers.with_helpers(sketch, entities)
    first_geo = sketch.GeometryCount
    new = _turned(sketch, entities, placement)
    mapping = {g: sketch.addGeometry(geo, sketch.getConstruction(g)) for g, geo in new.items()}
    cons = []
    outside = []
    for c in list(sketch.Constraints):
        refs = _refs(c)
        if not refs or not any(r in mapping for r in refs) or c.Type in ("InternalAlignment", "Block"):
            continue
        if any(r not in mapping for r in refs):
            if keep_relations and c.Type in _OUTSIDE_KEEP and not (c.Name or "").startswith("SWBlock:"):
                args = [c.Type]
                for geo, pos in ((c.First, c.FirstPos), (c.Second, c.SecondPos), (c.Third, c.ThirdPos)):
                    if geo is None or geo <= -2000:
                        break
                    args += [mapping.get(geo, geo), pos]
                try:
                    outside.append(C(*_tidy(args)))
                except Exception as _fw_err:
                    _fw_log("sketchmove.py:copy outside", _fw_err)
            continue
        if (c.Name or "").startswith("SWBlock:"):      # a block's hidden hold: not the copy's (reviewer 11-19)
            continue
        if c.Type in _POSITION_DIMENSIONS and len(refs) == 1:
            continue
        args = [c.Type]
        for geo, pos in ((c.First, c.FirstPos), (c.Second, c.SecondPos), (c.Third, c.ThirdPos)):
            if geo is None or geo <= -2000:
                break
            args += [mapping.get(geo, geo), pos]
        if c.Type in relationspm.DIMENSIONS:
            args.append(c.Value)
        try:
            cons.append((C(*_tidy(args)), c.Driving, ""))
        except Exception as _fw_err:
            _fw_log("sketchmove.py:115", _fw_err)
    cons += _block_hv(sketch, mapping)
    if cons and _quarter(placement)[0] != 0:
        copies = set(mapping.values())
        turning = [x for x in cons if x[0].Type in _TURNING and all(r in copies for r in _refs(x[0]))]
        rest = [x for x in cons if x not in turning]
        cons = rest + _turned_relations(turning, placement, sketch.getPoint)
    _add_relations(sketch, cons)
    _helpers.hide_new(sketch, first_geo)
    sketch.solve()
    if outside:
        _add_if_copy_only(sketch, outside, set(mapping.values()))
    return mapping


_OUTSIDE_KEEP = ("Coincident", "PointOnObject", "Tangent", "Parallel", "Perpendicular", "Equal", "Collinear",
                 "Horizontal", "Vertical", "Symmetric")


def _where(geo):
    out = []
    for name in ("StartPoint", "EndPoint", "Center"):
        v = getattr(geo, name, None)
        if v is not None:
            out += [v.x, v.y]
    for name in ("X", "Y", "Radius", "MajorRadius", "MinorRadius"):
        v = getattr(geo, name, None)
        if isinstance(v, float):
            out.append(v)
    return out


def _add_if_copy_only(sketch, items, copies):
    """fix310: each relation from the copy to the rest of the sketch stays only when, solved, nothing but
    the copy moved (and the sketch still solves)."""
    def bad():
        return len(sketch.ConflictingConstraints) + len(sketch.RedundantConstraints)
    sketch.solve()
    base = bad()
    for c in items:
        before = {g: _where(geo) for g, geo in enumerate(sketch.Geometry) if g not in copies}
        try:
            i = sketch.addConstraint(c)
        except Exception as _fw_err:
            _fw_log("sketchmove.py:copy keep", _fw_err)
            continue
        ok = sketch.solve() == 0 and bad() <= base
        if ok:
            geos = sketch.Geometry
            ok = all(len(v) == len(_where(geos[g])) and all(abs(a - b) < 1e-6 for a, b in zip(v, _where(geos[g])))
                     for g, v in before.items())
        if not ok:
            try:
                sketch.delConstraint(i)
                sketch.solve()
            except Exception as _fw_err:
                _fw_log("sketchmove.py:copy drop", _fw_err)


def _block_hv(sketch, mapping):
    """The Horizontal and Vertical a block keeps in its record while it holds its shape, for the
    copies of its entities (a copy is plain entities: they would be lost)."""
    import Sketcher
    out = []
    try:
        from . import blocks
        recs = blocks.records(sketch)
        ids = blocks._ids(sketch) if recs else {}
        for rec in recs:
            angle = float(rec.get("angle", 0.0))
            for h in rec.get("hv") or []:
                t = blocks._hv_at(h[0], angle - h[5])
                f = ids.get(h[1])
                s = ids.get(h[3]) if h[3] is not None else None
                if t is None or f not in mapping or (h[3] is not None and s not in mapping):
                    continue
                c = Sketcher.Constraint(t, mapping[f]) if s is None else \
                    Sketcher.Constraint(t, mapping[f], h[2], mapping[s], h[4])
                out.append((c, True, ""))
    except Exception as _fw_err:
        _fw_log("sketchmove.py:block hv", _fw_err)
    return out


def _tidy(args):
    """Constraint() wants edge-to-edge relations without positions (Equal, Parallel...)."""
    kind = args[0]
    rest = args[1:]
    if kind in ("Equal", "Parallel", "Perpendicular", "Horizontal", "Vertical", "Block") and all(
            p == 0 for p in rest[1::2][:2]):
        return [kind] + rest[0::2][:2] if len(rest) >= 4 else [kind, rest[0]]
    if kind == "Tangent" and len(rest) >= 4 and rest[1] == 0 and rest[3] == 0:
        return [kind, rest[0], rest[2]]
    if kind in ("Distance", "Radius", "Diameter", "Angle") and len(rest) == 3 and rest[1] == 0:
        return [kind, rest[0], rest[2]]
    if kind == "Angle" and len(rest) == 5 and rest[1] == 0 and rest[3] == 0:
        return [kind, rest[0], rest[2], rest[4]]
    if kind == "PointOnObject" and len(rest) >= 4:
        return [kind, rest[0], rest[1], rest[2]]
    return args


class _EntitiesPage(sketchtoolpm.ToolPage):
    """Shared by Move, Copy and Rotate."""
    COPY = False

    def build(self):
        p = _params()
        self.entities = []
        self._filling = True
        self._base_point = None
        self._to_point = None
        self.times = 1
        g = self.group("Entities to %s" % self.VERB)
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWSelectedEntities")
        self.list.setFixedHeight(90)
        # movepm-1121: a plain white selection box with the command's glyph at its left (2025 video),
        # not the Properties page's boxed rows
        self.list.setStyleSheet("QListWidget { background: %s; color: %s; border: 1px solid %s; }"
                                " QListWidget::item { border: none; margin: 0px; }" % (
                                    relationspm._field("field", "#ffffff").name(),
                                    relationspm._field("field_text", "#000000").name(),
                                    relationspm._field("field_line", "#a9a9a9").name()))
        box_row = QtWidgets.QHBoxLayout()
        box_row.setSpacing(6)
        glyph = QtWidgets.QLabel(g.body)
        glyph.setObjectName("SWStyle_BoxGlyph")
        glyph.setFixedWidth(20)
        glyph.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        icon = self.title_icon()
        if icon is not None:
            glyph.setPixmap(icon.pixmap(16, 16))
        glyph.setToolTip("Entities to %s" % self.VERB)
        box_row.addWidget(glyph)
        box_row.addWidget(self.list, 1)
        g.content.addLayout(box_row)
        self.keep = QtWidgets.QCheckBox("Keep relations", g.body)
        self.keep.setChecked(p.GetBool("KeepRelations", False))
        self.keep.setToolTip("Off: the relations and dimensions to the rest of the sketch are broken")
        g.content.addWidget(self.keep)
        g = self.group("Parameters")
        self.parameters(g)
        self.repeat = QtWidgets.QPushButton("Repeat", g.body)
        self.repeat.setToolTip("%s the same again" % self.VERB)
        self.repeat.clicked.connect(self.again)
        # movepm-1121: Repeat at its own width, centred under the fields
        self.repeat.setMinimumWidth(max(self.repeat.sizeHint().width() + 16, 80))
        self.repeat.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        repeat_row = QtWidgets.QHBoxLayout()
        repeat_row.addStretch(1)
        repeat_row.addWidget(self.repeat)
        repeat_row.addStretch(1)
        g.content.addLayout(repeat_row)
        self.keep.toggled.connect(self.changed)
        self._filling = False
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        self._bulk_on = True
        for sub in relationspm.picked_subs(self.sketch):
            self.picked(sub)
        self._bulk_on = False
        self.free = _FreeClick(self)

    def follow(self, point):
        pass

    def number(self, g, value, suffix, low, high, tip):
        box = unitbox.UnitSpinBox(g.body)
        box.setRange(low, high)
        box.setDecimals(3)
        box.setSuffix(suffix)
        box.setValue(value)
        box.setToolTip(tip)
        box.setKeyboardTracking(False)
        box.valueChanged.connect(self.changed)
        return box

    def _bulk(self):
        """Several sketch elements picked at once (a box, or picked before the command): they are
        the entities, and the ends of those segments are not From/To points (tester run 4: the
        polygon moved as the page opened)."""
        if getattr(self, "_bulk_on", False):
            return True
        try:
            many = len(relationspm.picked_subs(self.sketch)) > 1
        except Exception:
            many = False
        if many:
            self._bulk_on = True
            QtCore.QTimer.singleShot(0, lambda: setattr(self, "_bulk_on", False))
        return many

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        bulk = self._bulk()
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("sketchmove.py:211", _fw_err)
        if item is None:
            return
        if bulk:
            # a box or a pick made before the command: entities only, never a From/To point
            if item.geo < 0 or item.pos in (1, 2, 3) and dimtools._kind(self.sketch.Geometry[item.geo]) != "point":
                return
        else:
            if self.wants_point() and item.pos in (1, 2, 3) or (self.wants_point() and item.geo < 0):
                self.point_picked(self.sketch.getPoint(item.geo, item.pos if item.pos else 1), item)
                return
            if self.wants_point() and dimtools._kind(self.sketch.Geometry[item.geo]) != "point":
                return      # a click on a line gives the point under the pointer (_FreeClick)
        if item.geo < 0 or item.geo in self.entities or item.pos not in (relationspm.NONE,) and \
                dimtools._kind(self.sketch.Geometry[item.geo]) != "point":
            return
        self.entities.append(item.geo)
        self.list.addItem(relationspm._entity_names(self.sketch.Geometry)[item.geo])
        self.changed()

    def wants_point(self):
        return False

    def point_picked(self, point, item):
        pass

    def selection_changed(self):
        pass

    def again(self):
        # only once there is a move to repeat (not while From/To still waits for its points)
        if self.entities and self.ready() and self._open and self.placed():
            self.times += 1
            self.changed()

    def changed(self, *args):
        if self._filling:
            return
        self.undo_work()
        if not self.entities or not self.ready():
            return
        self.begin()
        try:
            placement = self.placement()
            if self.COPY:
                for k in range(1, self.times + 1):
                    copy(self.sketch, self.entities, _power(placement, k), self.keep.isChecked())
            else:
                move(self.sketch, self.entities, _power(placement, self.times), self.keep.isChecked())
        except Exception as error:
            self.show_note("Could not %s: %s" % (self.VERB.lower(), error), True)
            return
        sketchtoolpm._refresh(self.sketch)
        bad = list(self.sketch.ConflictingConstraints) + list(self.sketch.RedundantConstraints)
        self.show_note("This over-defines the sketch." if bad else "", bool(bad))

    def ready(self):
        return True

    def placed(self):
        """The move is set (Move/Copy From/To: the To point is in, not just followed)."""
        return True

    def finish(self):
        _params().SetBool("KeepRelations", self.keep.isChecked())

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("sketchmove.py:281", _fw_err)
        self.observer.page = None
        free = getattr(self, "free", None)
        if free is not None:
            free.detach()
            free.page = None


class _FreeClick(QtCore.QObject):
    ""



    def __init__(self, page):
        super().__init__()
        self.page = page
        self.press = None
        self.widgets = []
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.attach)
        self.timer.start()
        self.attach()

    def attach(self):
        shell = sketchtoolpm._shell()
        view = shell.view_widget() if shell is not None else None
        want = []
        if view is not None and alive(view):
            want = [view.viewport()] if hasattr(view, "viewport") and view.viewport() else [view]
        if want == self.widgets:
            return
        self.detach(stop=False)
        self.widgets = want
        for w in want:
            w.installEventFilter(self)

    def detach(self, stop=True):
        if stop:
            self.timer.stop()
        for w in self.widgets:
            if alive(w):
                w.removeEventFilter(self)
        self.widgets = []

    def _sketch_point(self, widget, pos):
        view = Gui.ActiveDocument.ActiveView
        ratio = widget.devicePixelRatioF() if hasattr(widget, "devicePixelRatioF") else 1.0
        x, y = int(round(pos.x() * ratio)), int(round((widget.height() - pos.y()) * ratio))
        p = view.getPoint(x, y)
        local = self.page.sketch.getGlobalPlacement().inverse().multVec(p)
        return self._snapped(App.Vector(local.x, local.y, 0), x, y)

    def _snapped(self, point, x, y):
        """The point snapped as sketching snaps it (ends, centres, midpoints, edges, alignments;
        tester SK9-11: a Copy To click near a cap centre landed 0.44 mm off it). For the To point
        the entities riding with the pointer (and a Copy's preview copies) are no target."""
        page = self.page
        try:
            from .fwsketch import snap as S
            from .fwsketch.toolbase import ViewMath
            vm = ViewMath()
            vm.setup_view(Gui.ActiveDocument, page.sketch)
            snapper = S.Snapper(page.sketch, grid_size=vm._grid_size, view_box=vm._view_box)
            base = getattr(page, "_base_point", None)
            if base is not None:
                snap = getattr(page, "_snapshot", None)
                count = len(snap[0]) if snap else len(page.sketch.Geometry)
                skip = set(getattr(page, "entities", ()))
                skip.update(g for g, _p in getattr(page, "points_picked", ()))
                skip.update(range(count, len(page.sketch.Geometry)))
                snapper.excluded.update(skip)
                snapper.set_reference((base.x, base.y))
            d = snapper.snap((point.x, point.y), vm.pixel_size(x, y))
            return App.Vector(d.position[0], d.position[1], 0)
        except Exception:
            return point

    def _on_point(self):
        """The pointer is over a sketch point: the selection hands that one over exactly."""
        try:
            pre = Gui.Selection.getPreselection()
            subs = [sub.split(".")[-1] for sub in getattr(pre, "SubElementNames", ())]
        except Exception:
            return False
        # fix288: a line under the pointer gives the point under the pointer on every page (Stretch
        # took the line's start for its base point)
        return any(sub.startswith("Vertex") or sub == "RootPoint" for sub in subs)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter354(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter sketchmove.py: %s\n" % exc)
            return False

    def _fw_filter354(self, obj, event):
        page = self.page
        if page is None or not alive(page):
            return False
        t = event.type()
        try:
            if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                self.press = (event.pos(), self._on_point()) if page.wants_point() else None
            elif t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
                press, self.press = self.press, None
                if press is not None and not press[1] and page.wants_point() \
                        and (event.pos() - press[0]).manhattanLength() < 5:
                    point = self._sketch_point(obj, event.pos())
                    QtCore.QTimer.singleShot(0, lambda: alive(page) and page.wants_point()
                                             and page.point_picked(point, None))
            elif t == QtCore.QEvent.MouseMove and not event.buttons():
                page.follow(self._sketch_point(obj, event.pos()))
        except Exception as _fw_err:
            _fw_log("sketchmove.py:399", _fw_err)
        return False


def _power(placement, k):
    out = App.Placement()
    for _ in range(k):
        out = placement.multiply(out)
    return out


class MovePage(_EntitiesPage):
    TITLE = "Move"
    VERB = "Move"
    ICON = "SKETCH_MOVE_ENTITIES"
    PIXMAP = "Sketcher_Translate"
    TRANSACTION = "Move Entities"

    def parameters(self, g):
        self.from_to = QtWidgets.QRadioButton("From/To", g.body)
        self.by_xy = QtWidgets.QRadioButton("X/Y", g.body)
        group = QtWidgets.QButtonGroup(g.body)
        group.addButton(self.from_to)
        group.addButton(self.by_xy)
        (self.by_xy if _params().GetBool("ByXY", False) else self.from_to).setChecked(True)
        self.mode_group = group
        self._hover = None
        g.content.addWidget(self.from_to)
        self.points = QtWidgets.QLabel("", g.body)
        self.points.setWordWrap(True)
        g.content.addWidget(self.points)
        g.content.addWidget(self.by_xy)
        form = QtWidgets.QFormLayout()
        self.dx = self.number(g, 0.0, " mm", -1e6, 1e6, "Distance along X")
        self.dy = self.number(g, 0.0, " mm", -1e6, 1e6, "Distance along Y")
        form.addRow("ΔX:", self.dx)
        form.addRow("ΔY:", self.dy)
        g.content.addLayout(form)
        self._delta_form = form
        self.from_to.toggled.connect(self._mode)
        self._mode()

    def _mode(self, *args):
        ft = self.from_to.isChecked()

        for box in (self.dx, self.dy):
            box.setEnabled(True)
            box.setVisible(not ft)
            label = self._delta_form.labelForField(box)
            if label is not None:
                label.setVisible(not ft)
        self._show_points()
        self.changed()

    def _show_points(self):
        if not self.from_to.isChecked():
            self.points.setText("")
        elif self._base_point is None:
            self.points.setText("Pick the base point.")
        elif self._to_point is None:
            self.points.setText("Base point picked; pick the point to move it to.")
        else:
            self.points.setText("From (%s, %s) to (%s, %s)" % tuple(_num(v) for v in (
                self._base_point.x, self._base_point.y, self._to_point.x, self._to_point.y)))

        self.points.setVisible(bool(self.points.text()))

    def wants_point(self):
        return bool(self.entities) and self.from_to.isChecked() and self._to_point is None

    def point_picked(self, point, item):
        self._hover = None
        if self._base_point is None:
            self._base_point = App.Vector(point)
        else:
            self._to_point = App.Vector(point)
        self._show_points()
        self.changed()

    def placed(self):
        return not self.from_to.isChecked() or self._to_point is not None

    def follow(self, point):
        """After the base point, the entities ride with the pointer until the To click."""
        if self.from_to.isChecked() and self._base_point is not None and self._to_point is None and self.entities:
            if self._hover is not None and (self._hover - point).Length < 1e-9:
                return
            self._hover = point
            self.changed()

    def ready(self):
        if self.from_to.isChecked() and self._base_point is not None and self._to_point is None:
            return getattr(self, "_hover", None) is not None
        return not self.from_to.isChecked() or (self._base_point is not None and self._to_point is not None)

    def placement(self):
        if self.from_to.isChecked():
            d = (self._to_point if self._to_point is not None else self._hover) - self._base_point
        else:
            d = App.Vector(self.dx.value(), self.dy.value(), 0)
        return App.Placement(App.Vector(d.x, d.y, 0), App.Rotation())

    def finish(self):
        super().finish()
        _params().SetBool("ByXY", self.by_xy.isChecked())


class CopyPage(MovePage):
    TITLE = "Copy"
    VERB = "Copy"
    ICON = "SKETCH_COPY_ENTITIES"
    PIXMAP = "Sketcher_Clone"
    TRANSACTION = "Copy Entities"
    COPY = True

    def build(self):
        super().build()

        # those to the rest of the sketch that move only the copy
        self.keep.setToolTip("On: the copy also keeps its relations to the rest of the sketch that move only the copy. "
                             "Off: only the relations among the copied entities are copied")


class RotatePage(_EntitiesPage):
    TITLE = "Rotate"
    VERB = "Rotate"
    ICON = "SKETCH_ROTATE_ENTITIES"
    PIXMAP = "Sketcher_Rotate"
    TRANSACTION = "Rotate Entities"

    def parameters(self, g):
        self.centre_note = QtWidgets.QLabel("Center of rotation: pick a point.", g.body)
        self.centre_note.setWordWrap(True)
        g.content.addWidget(self.centre_note)
        form = QtWidgets.QFormLayout()

        # starting at 0 (16-minute guide 8:20); the centre boxes stay as hidden holders
        self.cx = self.number(g, 0.0, " mm", -1e6, 1e6, "Center X")
        self.cy = self.number(g, 0.0, " mm", -1e6, 1e6, "Center Y")
        self.cx.hide()
        self.cy.hide()
        self.angle = self.number(g, 0.0, "°", -360.0, 360.0, "Angle")
        form.addRow("Angle:", self.angle)
        g.content.addLayout(form)
        self._centre_picked = False
        for box in (self.cx, self.cy):           # a typed centre counts as picked
            box.valueChanged.connect(self._typed_point)

    def wants_point(self):
        return bool(self.entities) and not self._centre_picked

    def ready(self):
        # no preview about the origin before the centre is in (tester SK9-12: a live 90 degree
        # preview at the origin as the page opened)
        return self._centre_picked

    def _typed_point(self, *args):
        if not self._filling and not self._centre_picked:
            self._centre_picked = True
            self.centre_note.setText("Rotate Point Defined")
            self.changed()

    def point_picked(self, point, item):
        self._centre_picked = True
        self._filling = True
        self.cx.setValue(point.x)
        self.cy.setValue(point.y)
        self._filling = False
        self.centre_note.setText("Rotate Point Defined")
        self.changed()

        QtCore.QTimer.singleShot(0, self._angle_focus)

    def _angle_focus(self):
        if alive(self.angle):
            self.angle.setFocus(QtCore.Qt.OtherFocusReason)
            self.angle.selectAll()

    def placement(self):
        return App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), self.angle.value()),
                             App.Vector(self.cx.value(), self.cy.value(), 0))

    def finish(self):
        super().finish()
        _params().SetFloat("Angle", self.angle.value())


_LENGTHS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter")


def _scaled_geo(geo, c, f):
    """geo scaled by f about c. Not Geometry.scale(): on a line segment it scales the parameter
    range as well and returns a segment of the wrong length."""
    import Part

    def at(p):
        return c + (App.Vector(p) - c) * f
    t = geo.TypeId
    # clones changed in place where FreeCAD allows it: the entity keeps its Tag (what Sketch Text and
    # Fit Spline find it by) and its sketch state
    try:
        out = geo.clone()
        if t == "Part::GeomLineSegment":
            a, b = at(geo.StartPoint), at(geo.EndPoint)
            out.StartPoint = a
            out.EndPoint = b
            if (out.StartPoint - a).Length > 1e-9 or (out.EndPoint - b).Length > 1e-9:
                raise ValueError("line ends")
            return out
        if t == "Part::GeomPoint":
            p = at(App.Vector(geo.X, geo.Y, geo.Z))
            out.X, out.Y, out.Z = p.x, p.y, p.z
            return out
        if t in ("Part::GeomCircle", "Part::GeomArcOfCircle"):
            out.Center = at(geo.Center)
            out.Radius = geo.Radius * f
            return out
    except Exception as _fw_err:
        _fw_log("sketchmove.py:595", _fw_err)
    t = geo.TypeId
    if t == "Part::GeomLineSegment":
        out = Part.LineSegment(at(geo.StartPoint), at(geo.EndPoint))
    elif t == "Part::GeomPoint":
        out = Part.Point(at(App.Vector(geo.X, geo.Y, geo.Z)))
    elif t == "Part::GeomCircle":
        out = Part.Circle(at(geo.Center), geo.Axis, geo.Radius * f)
    elif t == "Part::GeomArcOfCircle":
        out = Part.ArcOfCircle(Part.Circle(at(geo.Center), geo.Axis, geo.Radius * f),
                               geo.FirstParameter, geo.LastParameter)
    else:
        out = geo.clone()
        m = App.Matrix()
        m.move(c * -1)
        s = App.Matrix()
        s.scale(f, f, f)
        m = s.multiply(m)
        back = App.Matrix()
        back.move(c)
        out.transform(back.multiply(m))
        return out
    geomkeep.like(geo, out)
    for name in ("Construction",):
        try:
            setattr(out, name, getattr(geo, name))
        except Exception as _fw_err:
            _fw_log("sketchmove.py:622", _fw_err)
    return out


def scale_in_place(sketch, geos, centre, factor):
    """Scales geos about centre (sketch x, y); the length dimensions among them scale too."""
    inside = set(geos)
    c = App.Vector(centre[0], centre[1], 0)
    out = geomkeep.read(sketch)
    for g in geos:
        out[g] = _scaled_geo(out[g], c, factor)
    dims = [(i, k.Value) for i, k in enumerate(sketch.Constraints)
            if k.Type in _LENGTHS and k.Driving and _refs(k) and all(r in inside for r in _refs(k))]
    # the dimensions take their scaled values first, then the scaled geometry goes in over
    # whatever the solver made of the old one: the two agree and nothing slides
    for i, value in dims:
        try:
            sketch.setDatum(i, App.Units.Quantity(value * factor, App.Units.Length))
        except Exception as _fw_err:
            _fw_log("sketchmove.py:641", _fw_err)
    sketch.Geometry = out
    sketch.solve()


def scale(sketch, entities, centre, factor, copies=0):
    ""

    if copies <= 0:
        break_outside_relations(sketch, entities)
        scale_in_place(sketch, list(entities), centre, factor)
        return {}
    # every copy first, then all of them scaled in one Geometry write: a Geometry write reads back
    # stale until the next recompute, so scaling copy by copy put the first copy back at full size
    # (fix282: Scale Copy x0.5, 2 copies gave R10 and R2.5)
    made = {k: copy(sketch, entities, App.Placement(), False) for k in range(1, copies + 1)}
    c = App.Vector(centre[0], centre[1], 0)
    out = geomkeep.read(sketch)
    for k, mapping in made.items():
        for g in mapping.values():
            out[g] = _scaled_geo(out[g], c, factor ** k)
        # fix310: the copy keeps its own relations; its length dimensions scale with it (as scale_in_place)
        mine = set(mapping.values())
        for i, d in enumerate(sketch.Constraints):
            if d.Type in _LENGTHS and d.Driving and _refs(d) and all(r in mine for r in _refs(d)):
                try:
                    sketch.setDatum(i, App.Units.Quantity(d.Value * factor ** k, App.Units.Length))
                except Exception as _fw_err:
                    _fw_log("sketchmove.py:scale copy dims", _fw_err)
    sketch.Geometry = out
    sketch.solve()
    return made


class ScalePage(_EntitiesPage):
    ""


    TITLE = "Scale"
    VERB = "Scale"
    ICON = "SKETCH_SCALE_ENTITIES"
    PIXMAP = "Sketcher_Scale"
    TRANSACTION = "Scale Entities"

    def build(self):
        super().build()
        self.keep.hide()
        self.repeat.hide()

    def parameters(self, g):
        p = _params()
        self.centre_note = QtWidgets.QLabel("Scale about: pick a point, or type it.", g.body)
        self.centre_note.setWordWrap(True)
        g.content.addWidget(self.centre_note)
        form = QtWidgets.QFormLayout()
        self.cx = self.number(g, 0.0, " mm", -1e6, 1e6, "Scale about X")
        self.cy = self.number(g, 0.0, " mm", -1e6, 1e6, "Scale about Y")
        self.factor = self.number(g, p.GetFloat("ScaleFactor", 1.0), "", 0.001, 1e4, "Scale Factor")
        for box in (self.cx, self.cy):           # a typed point counts as picked
            box.valueChanged.connect(self._typed_point)
        form.addRow("X:", self.cx)
        form.addRow("Y:", self.cy)
        form.addRow("Scale Factor:", self.factor)
        g.content.addLayout(form)
        self.copy_box = QtWidgets.QCheckBox("Copy", g.body)
        self.copy_box.setChecked(p.GetBool("ScaleCopy", False))
        g.content.addWidget(self.copy_box)
        form = QtWidgets.QFormLayout()
        self.copies = QtWidgets.QSpinBox(g.body)
        self.copies.setRange(1, 100)
        self.copies.setValue(max(1, p.GetInt("ScaleCopies", 1)))
        self.copies.setToolTip("Number of copies")
        self.copies.setKeyboardTracking(False)
        form.addRow("Copies:", self.copies)
        g.content.addLayout(form)
        self._copies_form = form
        self._show_copies(self.copy_box.isChecked())
        self.copy_box.toggled.connect(self._show_copies)
        self.copy_box.toggled.connect(self.changed)
        self.copies.valueChanged.connect(self.changed)
        self._centre_picked = False

    def _show_copies(self, on):
        # no greyed box: Copies shows while Copy is ticked
        self.copies.setEnabled(True)
        self.copies.setVisible(bool(on))
        label = self._copies_form.labelForField(self.copies)
        if label is not None:
            label.setVisible(bool(on))

    def wants_point(self):
        return bool(self.entities) and not self._centre_picked

    def _typed_point(self, *args):
        if not self._filling and not self._centre_picked:
            self._centre_picked = True
            self.centre_note.setText("Scale Point Defined")
            self.changed()

    def point_picked(self, point, item):
        self._centre_picked = True
        self._filling = True
        self.cx.setValue(point.x)
        self.cy.setValue(point.y)
        self._filling = False
        self.centre_note.setText("Scale Point Defined")
        self.changed()

    def changed(self, *args):
        if self._filling or not hasattr(self, "factor"):
            return
        self.undo_work()
        if not self._centre_picked:
            return                       # the preview waits for the Scale about point
        if not self.entities or abs(self.factor.value() - 1.0) < 1e-12 and not self.copy_box.isChecked():
            return
        self.begin()
        try:
            scale(self.sketch, self.entities, (self.cx.value(), self.cy.value()), self.factor.value(),
                  self.copies.value() if self.copy_box.isChecked() else 0)
        except Exception as error:
            self.show_note("Could not scale: %s" % error, True)
            return
        sketchtoolpm._refresh(self.sketch)
        bad = list(self.sketch.ConflictingConstraints) + list(self.sketch.RedundantConstraints)
        self.show_note("This over-defines the sketch." if bad else "", bool(bad))

    def finish(self):
        super().finish()
        p = _params()
        p.SetFloat("ScaleFactor", self.factor.value())
        p.SetBool("ScaleCopy", self.copy_box.isChecked())
        p.SetInt("ScaleCopies", self.copies.value())


def _num(v):
    return ("%.3f" % v).rstrip("0").rstrip(".")


class _PageCommand:
    def __init__(self, page, menu, tip, pixmap):
        self.page, self.menu, self.tip, self.pixmap = page, menu, tip, pixmap

    def GetResources(self):
        return {"Pixmap": self.pixmap, "MenuText": self.menu, "ToolTip": self.tip, "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(self.page(sketch))


COMMANDS = {
    "SWStyle_MoveEntities": (MovePage, "Move Entities", "Moves sketch entities: From/To or X/Y", "Sketcher_Translate"),
    "SWStyle_CopyEntities": (CopyPage, "Copy Entities", "Copies sketch entities: From/To or X/Y", "Sketcher_Clone"),
    "SWStyle_RotateEntities": (RotatePage, "Rotate Entities", "Turns sketch entities about a center",
                               "Sketcher_Rotate"),
    "SWStyle_ScaleEntities": (ScalePage, "Scale Entities", "Scales sketch entities about a point by a factor",
                              "Sketcher_Scale"),
}


def register():
    for name, args in COMMANDS.items():
        try:
            if name not in Gui.listCommands():
                Gui.addCommand(name, _PageCommand(*args))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (name, error))
