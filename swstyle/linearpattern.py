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
from .sketchpattern import _COPYABLE, _search, anchor, drop_redundant

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/LinearSketchPattern"
COMMAND = "SWStyle_LinearSketchPattern"


def _params():
    return App.ParamGet(PARAMS)


def _copy_relations(sketch, mapping, C):
    out = []
    for c in sketch.Constraints:
        if c.Type not in _COPYABLE or (c.Name or "").startswith("SWBlock:"):    # a block's hidden hold (reviewer 11-19)
            continue
        refs = [x for x in (c.First, c.Second, c.Third) if x is not None and x > -2000]
        if not refs or any(x < 0 for x in refs) or any(x not in mapping for x in refs):
            continue
        args = [c.Type, mapping[c.First], c.FirstPos]
        if c.Second is not None and c.Second > -2000:
            args += [mapping[c.Second], c.SecondPos]
        if c.Type == "Symmetric" and c.Third is not None and c.Third > -2000:
            args += [mapping[c.Third], c.ThirdPos]
        if c.Type in ("Equal", "Parallel", "Perpendicular", "Tangent") and c.FirstPos == 0 and c.SecondPos == 0:
            args = [c.Type, mapping[c.First], mapping[c.Second]]
        elif c.Type in ("Horizontal", "Vertical") and (c.Second is None or c.Second <= -2000):
            # a line's own Horizontal or Vertical: ("Horizontal", g, 0) would read as a relation
            # between line g and geometry 0, which crashes FreeCAD's solver
            args = [c.Type, mapping[c.First]]
        elif c.Type == "PointOnObject":
            args = [c.Type, mapping[c.First], c.FirstPos, mapping[c.Second]]
        try:
            out.append(C(*args))
        except Exception as _fw_err:
            _fw_log("linearpattern.py:71", _fw_err)
    return out


def sites(n1, s1, a1, n2, s2, a2):
    """{(i, j): (dx, dy)} offsets of every grid site from the original."""
    u = (math.cos(math.radians(a1)), math.sin(math.radians(a1)))
    v = (math.cos(math.radians(a2)), math.sin(math.radians(a2)))
    return {(i, j): (i * s1 * u[0] + j * s2 * v[0], i * s1 * u[1] + j * s2 * v[1])
            for i in range(max(1, n1)) for j in range(max(1, n2))}


def make_pattern(sketch, entities, n1, s1, a1, n2=1, s2=0.0, a2=90.0, skip=(),
                 dim_x=True, dim_y=True, fix_x=False, dim_angle=False, _drop=None, _learn=False):
    """Adds the translated copies; returns {(i, j): [geo ids]} of the instances made."""
    import Part
    C = dimtools._constraint
    from .fwsketch import helpers as _helpers
    entities = _helpers.with_helpers(sketch, [g for g in entities if g >= 0])   # an arc slot's centre line comes along (reviewer 11-19)
    _first_geo = sketch.GeometryCount
    entities = [g for g in sorted(set(entities)) if g >= 0]
    n1, n2 = max(1, int(n1)), max(1, int(n2))
    if not entities or n1 * n2 < 2:
        return {}
    if n1 > 1 and abs(s1) < 1e-9 or n2 > 1 and abs(s2) < 1e-9:
        raise ValueError("the spacing is zero")
    skip = {tuple(k) for k in skip} - {(0, 0)}
    first_new = len(sketch.Constraints)
    t1, t2 = min(n1, 3), min(n2, 2)
    if _drop is None and not _learn and n1 * n2 > t1 * t2:
        # every copy gets the same relations, so which of them are spare is learnt once on a
        # small trial grid in a hidden copy of the sketch and left out of every copy: the search
        # over the whole pattern took minutes on big grids (review 1119 pat2)
        from .sketchpattern import _learn_template
        _drop = _learn_template(sketch, lambda tmp: make_pattern(
            tmp, entities, t1, s1, a1, t2, s2, a2, (), dim_x, dim_y, fix_x, dim_angle, _learn=True))
    _drop = set(_drop or ())
    learn_key = (n1 - 1, n2 - 1)                 # the trial learns from its last copy
    tags, learnt = [], {}
    offsets = sites(n1, s1, a1, n2, s2, a2)
    original = sketch.Geometry
    ag, apos = anchor(sketch, entities[0])
    a0 = sketch.getPoint(ag, apos)
    cons = []
    made = {}
    site_ref = {(0, 0): (ag, apos)}
    # a line with its own Horizontal or Vertical: the copy gets that relation, and a Parallel on
    # top would over-define the sketch (fix67)
    own_hv = {c.First for c in sketch.Constraints if c.Type in ("Horizontal", "Vertical")
              and (c.Second is None or c.Second <= -2000)}
    for key in sorted(offsets):
        if key == (0, 0):
            continue
        dx, dy = offsets[key]
        if key in skip:
            pt = sketch.addGeometry(Part.Point(App.Vector(a0.x + dx, a0.y + dy, 0)), True)
            site_ref[key] = (pt, 1)
            continue
        mapping = {}
        for g in entities:
            copy = original[g].copy()
            copy.translate(App.Vector(dx, dy, 0))
            mapping[g] = sketch.addGeometry(copy, sketch.getConstruction(g))
        # the copy's own relations first, the pattern's Equal/Parallel last: of a redundant
        # group FreeCAD names the newest, so drop_redundant drops a spare Equal and the copy
        # keeps the seed's H/V (review 1119 pat1: a 3 x 2 rectangle pattern lost both Verticals
        # of one copy, which could then shear)
        rel = _copy_relations(sketch, mapping, C)
        for g, n in mapping.items():
            kind = dimtools._kind(original[g])
            if kind in ("line", "circle", "arc"):
                rel.append(C("Equal", g, n))
            if kind == "line" and g not in own_hv:
                rel.append(C("Parallel", g, n))
        for p, c in enumerate(rel):
            if p in _drop:
                continue
            if _learn and key == learn_key:
                tags.append((len(cons), p))
            cons.append(c)
        made[key] = sorted(mapping.values())
        site_ref[key] = (mapping[ag], apos)
    base = len(sketch.Constraints)
    sketch.addConstraint(cons)
    learnt = {base + j: p for j, p in tags}
    cons = []

    def link(k1, k2):
        (g1, p1), (g2, p2) = site_ref[k1], site_ref[k2]
        e1, e2 = sketch.getPoint(g1, p1), sketch.getPoint(g2, p2)
        line = sketch.addGeometry(Part.LineSegment(App.Vector(e1.x, e1.y, 0), App.Vector(e2.x, e2.y, 0)), True)
        cons.append(C("Coincident", line, 1, g1, p1))
        cons.append(C("Coincident", line, 2, g2, p2))
        return line

    first1 = first2 = None
    for j in range(n2):                  # rows along Direction 1
        for i in range(1, n1):
            line = link((i - 1, j), (i, j))
            if first1 is None:
                first1 = line
            else:
                cons.append(C("Equal", first1, line))
                cons.append(C("Parallel", first1, line))
    for j in range(1, n2):               # the first column along Direction 2
        line = link((0, j - 1), (0, j))
        if first2 is None:
            first2 = line
        else:
            cons.append(C("Equal", first2, line))
            cons.append(C("Parallel", first2, line))
    if first1 is not None:
        if dim_x:
            cons.append(C("Distance", first1, abs(s1)))
        if fix_x:
            ang = a1 % 180.0
            if abs(ang) < 1e-9 or abs(ang - 180.0) < 1e-9:
                cons.append(C("Horizontal", first1))
            elif abs(ang - 90.0) < 1e-9:
                cons.append(C("Vertical", first1))
            else:
                cons.append(C("Angle", first1, math.radians(a1 if s1 >= 0 else a1 + 180.0)))
    if first2 is not None:
        if dim_y:
            cons.append(C("Distance", first2, abs(s2)))
        if dim_angle and first1 is not None:
            u = sketch.Geometry[first1]
            w = sketch.Geometry[first2]
            du, dw = u.EndPoint - u.StartPoint, w.EndPoint - w.StartPoint
            between = math.atan2(du.x * dw.y - du.y * dw.x, du.x * dw.x + du.y * dw.y)
            if between >= 0:
                cons.append(C("Angle", first1, 1, first2, 1, between))
            else:
                cons.append(C("Angle", first2, 1, first1, 1, -between))
    if cons:
        sketch.addConstraint(cons)
    if _learn:
        return {learnt[i] for i in _search(sketch, first_new, ("Equal", "Parallel")) if i in learnt}
    drop_redundant(sketch, first_new)
    _helpers.hide_new(sketch, _first_geo)
    sketch.solve()
    return made


class LinearPatternPage(sketchtoolpm.ToolPage):
    TITLE = "Linear Pattern"
    ICON = "SKETCH_LINEAR_PATTERN"
    PIXMAP = "Sketcher_RectangularArray"
    TRANSACTION = "Linear Sketch Pattern"
    KIND = "linear"
    STATE = ("rev1", "s1", "dim_x", "n1", "count1", "a1", "fix_x", "rev2", "s2", "dim_y", "n2", "count2", "a2",
             "dim_angle")

    def build(self):
        p = _params()
        self._original = (len(self.sketch.Geometry), len(self.sketch.Constraints))
        self.entities = []
        self.skip = []
        self.instances = {}
        self.skip_active = False
        self._filling = True
        g = self.group("Direction 1")
        self.dir_active = None
        self.dir1 = self._dir_box(g, "X-axis", "Direction 1: click here, then a line or edge to run along")
        self.rev1 = QtWidgets.QCheckBox("Reverse direction", g.body)
        self.s1 = self._number(g, p.GetFloat("Spacing1", 10.0), " mm", 0.0, 1e6, "Spacing")
        self.dim_x = QtWidgets.QCheckBox("Dimension X spacing", g.body)
        self.dim_x.setChecked(p.GetBool("DimensionX", True))
        self.n1 = self._count(g, p.GetInt("Instances1", 2))
        self.count1 = QtWidgets.QCheckBox("Display instance count", g.body)
        self.count1.setChecked(p.GetBool("DisplayCount1", True))
        self.a1 = self._number(g, p.GetFloat("Angle1", 0.0), "°", -360.0, 360.0, "Angle")
        self.fix_x = QtWidgets.QCheckBox("Fix X-axis direction", g.body)
        self.fix_x.setChecked(p.GetBool("FixX", False))
        self._rows(g, self.rev1, ("Spacing:", self.s1), self.dim_x, ("Instances:", self.n1), self.count1,
                   ("Angle:", self.a1), self.fix_x)
        g = self.group("Direction 2")
        self.dir2 = self._dir_box(g, "Y-axis", "Direction 2: click here, then a line or edge to run along")
        self.rev2 = QtWidgets.QCheckBox("Reverse direction", g.body)
        self.s2 = self._number(g, p.GetFloat("Spacing2", 10.0), " mm", 0.0, 1e6, "Spacing")
        self.dim_y = QtWidgets.QCheckBox("Dimension Y spacing", g.body)
        self.dim_y.setChecked(p.GetBool("DimensionY", True))
        self.n2 = self._count(g, 1)
        self.count2 = QtWidgets.QCheckBox("Display instance count", g.body)
        self.count2.setChecked(p.GetBool("DisplayCount2", True))
        self.a2 = self._number(g, p.GetFloat("Angle2", 90.0), "°", -360.0, 360.0, "Angle")
        self.dim_angle = QtWidgets.QCheckBox("Dimension angle between axes", g.body)
        self.dim_angle.setChecked(p.GetBool("DimensionAngle", True))
        self._rows(g, self.rev2, ("Spacing:", self.s2), self.dim_y, ("Instances:", self.n2), self.count2,
                   ("Angle:", self.a2), self.dim_angle)
        self.callout = QtWidgets.QLabel("", g.body)
        self.callout.setObjectName("SWToolInfo")
        g.content.addWidget(self.callout)
        self.view_callouts = []
        try:
            from . import filletpm
            view = filletpm._view_widget()
            if view is not None:
                for k in (1, 2):
                    c = filletpm.Callout(self, view)
                    c.setObjectName("SWPatternCallout%d" % k)
                    self.view_callouts.append(c)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: pattern callout: %s\n" % error)
        g = self.group("Entities to Pattern")
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWSelectedEntities")
        self.list.setFixedHeight(90)
        g.content.addWidget(self.list)
        g = self.group("Instances to Skip")
        self.skip_list = QtWidgets.QListWidget(g.body)
        self.skip_list.setObjectName("SWSkipInstances")
        self.skip_list.setFixedHeight(70)
        self.skip_list.setToolTip("Click here, then click the instances to skip in the view; "
                                  "double-click an entry to bring it back")
        self.skip_list.installEventFilter(self)
        self.list.installEventFilter(self)
        self.skip_list.itemDoubleClicked.connect(self._unskip)
        g.content.addWidget(self.skip_list)
        for w in (self.s1, self.a1, self.s2, self.a2, self.n1, self.n2):
            w.setKeyboardTracking(False)
            w.valueChanged.connect(self.changed)
        for box in (self.rev1, self.dim_x, self.count1, self.fix_x, self.rev2, self.dim_y, self.count2,
                    self.dim_angle):
            box.toggled.connect(self.changed)
        self._filling = False
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        for sub in relationspm.picked_subs(self.sketch):
            self.picked(sub)
        from .sketchmove import _FreeClick
        self.free = _FreeClick(self)          # clicks in the view while Instances to Skip is active
        from .sketchpattern import _from_edit
        _from_edit(self)

    def remake(self, rec):
        st = rec["state"]
        s1 = -st["s1"] if st["rev1"] else st["s1"]
        s2 = -st["s2"] if st["rev2"] else st["s2"]
        make_pattern(self.sketch, rec["seed"], st["n1"], s1, st["a1"], st["n2"], s2, st["a2"],
                     [tuple(k) for k in st.get("skip", [])], st["dim_x"], st["dim_y"], st["fix_x"], st["dim_angle"])

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

    def _dir_box(self, g, text, tip):
        box = QtWidgets.QListWidget(g.body)
        box.setObjectName("SWPatternDirection")
        box.setFixedHeight(26)
        box.setToolTip(tip)
        box.addItem(text)
        box.installEventFilter(self)
        g.content.addWidget(box)
        return box

    def _dir_on(self, which):
        """Makes a direction box the active one (the next line picked sets that direction)."""
        self.dir_active = which
        for k, box in ((1, getattr(self, "dir1", None)), (2, getattr(self, "dir2", None))):
            if box is None:
                continue
            box.setProperty("swActive", k == which)
            box.style().unpolish(box)
            box.style().polish(box)

    def _direction_picked(self, item):
        ""

        import math
        g = item.geo
        if g == -1:
            angle, name = 0.0, "X-axis"
        elif g == -2:
            angle, name = 90.0, "Y-axis"
        else:
            try:
                geo = self.sketch.Geometry[g] if g >= 0 else self.sketch.ExternalGeo[-g - 1]
                d = geo.EndPoint - geo.StartPoint
            except Exception:
                return False
            if d.Length < 1e-9:
                return False
            angle = math.degrees(math.atan2(d.y, d.x))
            try:
                name = item.name
            except Exception:
                name = "Line"
        which = self.dir_active
        box, spin = (self.dir1, self.a1) if which == 1 else (self.dir2, self.a2)
        box.clear()
        box.addItem(name)
        spin.setValue(round(angle, 6))
        self._dir_on(None)
        return True

    def _count(self, g, value):
        box = QtWidgets.QSpinBox(g.body)
        box.setRange(1, 1000)
        box.setValue(max(1, value))
        box.setToolTip("Number of instances, the original included")
        return box

    def _rows(self, g, *items):
        for item in items:
            if isinstance(item, tuple):
                form = QtWidgets.QFormLayout()
                form.addRow(item[0], item[1])
                g.content.addLayout(form)
            else:
                g.content.addWidget(item)

    # --- picks --------------------------------------------------------------------------------
    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("linearpattern.py:370", _fw_err)
        if item is None:
            return
        if self.dir_active and item.pos == relationspm.NONE:
            self._direction_picked(item)
            return
        if self.wants_point():
            if item.geo >= 0:
                g = item.geo
                pos = item.pos if item.pos in (1, 2, 3) else (3 if dimtools._kind(self.sketch.Geometry[g]) in
                                                              ("circle", "arc") else 1)
                self.point_picked(self.sketch.getPoint(g, pos), item)
            return
        if item.geo < 0 or item.geo in self.entities or item.geo >= self._original[0]:
            return
        if item.pos not in (relationspm.NONE,) and dimtools._kind(self.sketch.Geometry[item.geo]) != "point":
            return
        self.entities.append(item.geo)
        self.list.addItem(relationspm._entity_names(self.sketch.Geometry)[item.geo])
        self.changed()

    def selection_changed(self):
        pass

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter308(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter linearpattern.py: %s\n" % exc)
            return False

    def _fw_filter308(self, obj, event):
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            if obj is getattr(self, "dir1", None):
                self._dir_on(1)
            elif obj is getattr(self, "dir2", None):
                self._dir_on(2)
            elif obj is getattr(self, "skip_list", None):
                self._dir_on(None)
                self._skip_box(True)
            elif obj is getattr(self, "list", None):
                self._dir_on(None)
                self._skip_box(False)
        return False

    def _skip_box(self, on):
        ""

        self.skip_active = bool(on)
        for box, active in ((self.skip_list, self.skip_active), (self.list, not self.skip_active)):
            box.setProperty("swActive", active)
            box.style().unpolish(box)
            box.style().polish(box)

    # sketchmove._FreeClick asks these
    def wants_point(self):
        return self.skip_active and bool(self.entities)

    def point_picked(self, point, item):
        self._skip_clicked(point.x, point.y)

    def follow(self, point):
        pass

    def _offsets(self):
        s1 = -self.s1.value() if self.rev1.isChecked() else self.s1.value()
        s2 = -self.s2.value() if self.rev2.isChecked() else self.s2.value()
        return sites(self.n1.value(), s1, self.a1.value(), self.n2.value(), s2, self.a2.value())

    def _skip_clicked(self, x, y):
        if not self.entities:
            return
        g, pos = anchor(self.sketch, self.entities[0])
        try:
            a0 = self.sketch.getPoint(g, pos)
        except Exception:
            return
        offsets = self._offsets()
        step = min([v for v in (self.s1.value(), self.s2.value() if self.n2.value() > 1 else 0) if v > 0] or [1.0])
        best = min(offsets, key=lambda k: math.hypot(a0.x + offsets[k][0] - x, a0.y + offsets[k][1] - y))
        far = math.hypot(a0.x + offsets[best][0] - x, a0.y + offsets[best][1] - y)
        if best != (0, 0) and far <= 0.4 * step:
            if best in self.skip:
                self.skip.remove(best)
            else:
                self.skip.append(best)
            self._fill_skip()
            self.changed()

    def _fill_skip(self):
        self.skip_list.clear()
        for i, j in sorted(self.skip):
            self.skip_list.addItem("(%d, %d)" % (i + 1, j + 1))

    def _unskip(self, item):
        row = self.skip_list.row(item)
        keys = sorted(self.skip)
        if 0 <= row < len(keys):
            self.skip.remove(keys[row])
            self._fill_skip()
            self.changed()

    # --- work ---------------------------------------------------------------------------------
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
            App.Console.PrintWarning("FreeCAD: Linear Pattern clean-up: %s\n" % error)

    def changed(self, *args):
        if self._filling:
            return
        self.undo_work()
        self.instances = {}
        n1, n2 = self.n1.value(), self.n2.value()
        valid = {k for k in self._offsets()}
        self.skip = [k for k in self.skip if k in valid]
        self._fill_skip()
        if not self.entities or n1 * n2 < 2:
            self.callout.setText("")
            self._show_view_callouts()
            return
        self.begin()
        s1 = -self.s1.value() if self.rev1.isChecked() else self.s1.value()
        s2 = -self.s2.value() if self.rev2.isChecked() else self.s2.value()
        try:
            self.instances = make_pattern(self.sketch, self.entities, n1, s1, self.a1.value(), n2, s2,
                                          self.a2.value(), self.skip, self.dim_x.isChecked(),
                                          self.dim_y.isChecked(), self.fix_x.isChecked(),
                                          self.dim_angle.isChecked())
        except Exception as error:
            self.show_note("Could not pattern: %s" % error, True)
            return
        sketchtoolpm._refresh(self.sketch)
        bad = list(self.sketch.ConflictingConstraints) + list(self.sketch.RedundantConstraints)
        self.show_note("The pattern over-defines the sketch." if bad else "", bool(bad))
        parts = []
        if self.count1.isChecked():
            parts.append("Direction 1: %d" % n1)
        if self.count2.isChecked() and n2 > 1:
            parts.append("Direction 2: %d" % n2)
        self.callout.setText("   ".join(parts))
        self._show_view_callouts()

    def _show_view_callouts(self):
        ""
        base = None
        if self.entities:
            try:
                base = self.sketch.getPoint(*anchor(self.sketch, sorted(set(self.entities))[0]))
            except Exception:
                base = None
        place = self.sketch.getGlobalPlacement()
        for k, c in enumerate(self.view_callouts):
            n, sp, ang, rev, show = ((self.n1, self.s1, self.a1, self.rev1, self.count1) if k == 0 else
                                     (self.n2, self.s2, self.a2, self.rev2, self.count2))
            if base is None or not show.isChecked() or n.value() < 2:
                c.anchor = None
                c.hide()
                continue
            d = (-1.0 if rev.isChecked() else 1.0) * sp.value() * (n.value() - 1)
            a = math.radians(ang.value())
            at = App.Vector(base.x + d * math.cos(a), base.y + d * math.sin(a), 0)
            c.set_rows([("Spacing", sp.value(), "mm", sp.setValue),
                        ("Instances", float(n.value()), "", lambda v, box=n: box.setValue(int(round(v))))],
                       place.multVec(at))

    def finish(self):
        from . import patternedit
        patternedit.remember(self)
        p = _params()
        p.SetFloat("Spacing1", self.s1.value())
        p.SetInt("Instances1", self.n1.value())
        p.SetFloat("Angle1", self.a1.value())
        p.SetFloat("Spacing2", self.s2.value())
        p.SetFloat("Angle2", self.a2.value())
        p.SetBool("DimensionX", self.dim_x.isChecked())
        p.SetBool("DimensionY", self.dim_y.isChecked())
        p.SetBool("FixX", self.fix_x.isChecked())
        p.SetBool("DimensionAngle", self.dim_angle.isChecked())
        p.SetBool("DisplayCount1", self.count1.isChecked())
        p.SetBool("DisplayCount2", self.count2.isChecked())

    def closing(self):
        for c in getattr(self, "view_callouts", []):
            try:
                c.timer.stop()
                c.hide()
                c.deleteLater()
            except Exception as _fw_err:
                _fw_log("linearpattern.py:575", _fw_err)
        self.view_callouts = []
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("linearpattern.py:580", _fw_err)
        self.observer.page = None
        free = getattr(self, "free", None)
        if free is not None:
            free.detach()
            free.page = None


class LinearPatternCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_RectangularArray", "MenuText": "Linear Sketch Pattern",
                "ToolTip": "Copies sketch entities in rows along one or two directions, tied by the spacing",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(LinearPatternPage(sketch))


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, LinearPatternCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
