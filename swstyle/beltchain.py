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

V = App.Vector
UNDEF = -2000


def _kind_ok(geo):
    return geo.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle")


def tangent_points(c1, r1, s1, c2, r2, s2):
    """The belt line from member 1 to member 2: (point on 1, point on 2). s = +1 when the member
    lies left of the belt as it runs (the loop's inside), -1 when right."""
    d = c2 - c1
    length = d.Length
    k = s1 * r1 - s2 * r2
    if length < 1e-9 or abs(k) > length:
        raise ValueError("Two members overlap too much for a belt between them")
    phi = math.atan2(d.y, d.x)
    theta = phi - math.acos(k / length)
    n = V(math.cos(theta), math.sin(theta), 0)
    return c1 + n * (s1 * r1), c2 + n * (s2 * r2)


def plan(members):
    """members: [(centre, radius, side)] in belt order. Returns (lines, arcs, length) with lines
    [(a, b)] from member i to member i+1 and arcs [(centre, radius, start angle, end angle)]
    counterclockwise, as Part.ArcOfCircle wants them."""
    n = len(members)
    if n < 2:
        raise ValueError("Pick at least two circles")
    lines = []
    for i in range(n):
        (c1, r1, s1), (c2, r2, s2) = members[i], members[(i + 1) % n]
        lines.append(tangent_points(c1, r1, s1, c2, r2, s2))
    arcs = []
    total = sum((b - a).Length for a, b in lines)
    for i, (c, r, s) in enumerate(members):
        come = lines[i - 1][1]          # where the belt arrives
        go = lines[i][0]                # where it leaves
        a_in = math.atan2(come.y - c.y, come.x - c.x)
        a_out = math.atan2(go.y - c.y, go.x - c.x)
        start, end = (a_in, a_out) if s > 0 else (a_out, a_in)
        while end <= start + 1e-9:
            end += 2 * math.pi
        arcs.append((c, r, start, end))
        total += r * (end - start)
    return lines, arcs, total


def make(sketch, picks, sides, thickness=0.0, engage=True):
    ""




    import Part
    import Sketcher
    C = Sketcher.Constraint
    members = []
    for g in picks:
        geo = sketch.Geometry[g]
        if not _kind_ok(geo):
            raise ValueError("Belt members are circles or arcs")
        members.append((geo.Center, geo.Radius + max(0.0, thickness), sides.get(g, 1)))
    lines, arcs, length = plan(members)
    first = sketch.GeometryCount
    arc_ids = [sketch.addGeometry(Part.ArcOfCircle(Part.Circle(c, V(0, 0, 1), r), a, b))
               for c, r, a, b in arcs]
    line_ids = [sketch.addGeometry(Part.LineSegment(a, b)) for a, b in lines]
    cons = []
    n = len(picks)
    for i, g in enumerate(picks):
        if not engage:
            cons.append(C("Radius", arc_ids[i], members[i][1]))
        elif thickness > 0:
            cons += [C("Coincident", arc_ids[i], 3, g, 3), C("Radius", arc_ids[i], members[i][1])]
        else:
            cons += [C("Coincident", arc_ids[i], 3, g, 3), C("Equal", arc_ids[i], g)]
    for i in range(n):
        j = (i + 1) % n
        # the line leaves arc i at its end (left side) or start (right side), and reaches arc j
        # at its start (left) or end (right)
        leave = 2 if members[i][2] > 0 else 1
        reach = 1 if members[j][2] > 0 else 2
        cons += [C("Tangent", line_ids[i], 1, arc_ids[i], leave), C("Tangent", line_ids[i], 2, arc_ids[j], reach)]
    sketch.addConstraint(cons)
    sketch.solve()
    return first, length


def belt_length(sketch, first, count):
    """The length of the belt made at first (count members) as the sketch is now."""
    total = 0.0
    for g in range(first, first + 2 * count):
        try:
            total += sketch.Geometry[g].length()
        except Exception as _fw_err:
            _fw_log("beltchain.py:125", _fw_err)
    return total


def drive_length(sketch, picks, first, target, steps=12):
    ""


    if len(picks) < 2:
        return None
    n = len(picks)
    mover, anchor = picks[-1], picks[-2]

    def centre(g):
        return V(sketch.Geometry[g].Center)

    d = centre(mover) - centre(anchor)
    if d.Length < 1e-9:
        return None
    d.normalize()

    import Sketcher

    def length_at(t, base):
        # the member's centre held at the trial place for one solve, then let go again
        to = base + d * t
        k = sketch.addConstraint([Sketcher.Constraint("DistanceX", -1, 1, mover, 3, to.x),
                                  Sketcher.Constraint("DistanceY", -1, 1, mover, 3, to.y)])
        sketch.solve()
        sketch.delConstraint(k[-1] if isinstance(k, (list, tuple)) else k + 1)
        sketch.delConstraint(k[0] if isinstance(k, (list, tuple)) else k)
        sketch.solve()
        return belt_length(sketch, first, n)

    base = centre(mover)
    l0 = belt_length(sketch, first, n)
    if abs(l0 - target) < 1e-6:
        return l0
    # the belt grows about twice as fast as the centre moves
    t0, t1 = 0.0, (target - l0) / 2.0
    f0 = l0 - target
    f1 = length_at(t1, base) - target
    if (centre(mover) - base).Length < 1e-9:
        return None
    for _ in range(steps):
        if abs(f1) < 1e-6 or abs(f1 - f0) < 1e-12:
            break
        t0, t1, f0 = t1, t1 - f1 * (t1 - t0) / (f1 - f0), f1
        f1 = length_at(t1, base) - target
    return f1 + target


def belt_part(sketch, first, count):
    ""

    doc = sketch.Document
    body = doc.addObject("PartDesign::Body", "Belt")
    body.Label = "Belt"
    copy = body.newObject("Sketcher::SketchObject", "BeltSketch")
    copy.Label = "Belt Sketch"
    copy.MapMode = "Deactivated"
    copy.Placement = sketch.getGlobalPlacement()
    for g in range(first, first + 2 * count):
        try:
            copy.addGeometry(sketch.Geometry[g].copy())
        except Exception as _fw_err:
            _fw_log("beltchain.py:191", _fw_err)
    doc.recompute()
    return body


def _page_class():
    import FreeCADGui as Gui
    from PySide import QtWidgets
    from . import relationspm, sketchtoolpm

    class BeltPage(sketchtoolpm.ToolPage):
        TITLE = "Belt/Chain"
        ICON = "SKETCH_BELT_CHAIN"
        PIXMAP = "Sketcher_CreateCircle"
        TRANSACTION = "Belt/Chain"

        def build(self):
            self.count = self.sketch.GeometryCount     # the preview's belt comes after
            self.picks = []
            self.sides = {}
            g = self.group("Belt Members")
            self.list = QtWidgets.QListWidget(g.body)
            self.list.setObjectName("SWBeltMembers")
            self.list.setFixedHeight(100)
            g.content.addWidget(self.list)
            row = QtWidgets.QHBoxLayout()
            self.flip = QtWidgets.QPushButton("Flip belt side", g.body)
            self.flip.setObjectName("SWBeltFlip")
            self.flip.setToolTip("The belt goes round the picked member on its other side")
            self.flip.clicked.connect(self.flip_side)
            self.remove = QtWidgets.QPushButton("Remove", g.body)
            self.remove.setObjectName("SWBeltRemove")
            self.remove.clicked.connect(self.remove_member)
            self.up = QtWidgets.QPushButton("Up", g.body)
            self.up.setObjectName("SWBeltUp")
            self.up.setToolTip("Moves the picked member earlier in the belt's order")
            self.up.clicked.connect(lambda: self.move_member(-1))
            self.down = QtWidgets.QPushButton("Down", g.body)
            self.down.setObjectName("SWBeltDown")
            self.down.setToolTip("Moves the picked member later in the belt's order")
            self.down.clicked.connect(lambda: self.move_member(1))
            row.addWidget(self.up)
            row.addWidget(self.down)
            row.addWidget(self.flip)
            row.addWidget(self.remove)
            g.content.addLayout(row)
            g = self.group("Properties")
            self.driving = QtWidgets.QCheckBox("Driving", g.body)
            self.driving.setObjectName("SWBeltDriving")
            self.driving.setToolTip("The belt length you type sets the belt: the last member moves to fit it")
            g.content.addWidget(self.driving)
            self.length = QtWidgets.QLabel("Belt length: -", g.body)
            self.length.setObjectName("SWBeltLength")
            g.content.addWidget(self.length)
            self.length_box = QtWidgets.QDoubleSpinBox(g.body)
            self.length_box.setObjectName("SWBeltLengthValue")
            self.length_box.setRange(0.0, 1e7)
            self.length_box.setDecimals(2)
            self.length_box.setSuffix(" mm")
            self.length_box.setKeyboardTracking(False)
            self.length_box.setEnabled(False)
            g.content.addWidget(self.length_box)
            self.use_thickness = QtWidgets.QCheckBox("Use belt thickness", g.body)
            self.use_thickness.setObjectName("SWBeltUseThickness")
            g.content.addWidget(self.use_thickness)
            self.thickness = QtWidgets.QDoubleSpinBox(g.body)
            self.thickness.setObjectName("SWBeltThickness")
            self.thickness.setRange(0.0, 1e5)
            self.thickness.setDecimals(2)
            self.thickness.setSuffix(" mm")
            self.thickness.setValue(1.0)
            self.thickness.setKeyboardTracking(False)
            self.thickness.setEnabled(False)
            g.content.addWidget(self.thickness)
            self.engage = QtWidgets.QCheckBox("Engage belt", g.body)
            self.engage.setObjectName("SWBeltEngage")
            self.engage.setToolTip("Cleared, the belt is not tied to the members and does not hold them")
            self.engage.setChecked(True)
            g.content.addWidget(self.engage)
            self.part = QtWidgets.QCheckBox("Create belt part", g.body)
            self.part.setObjectName("SWBeltCreatePart")
            self.part.setToolTip("On OK, a Belt body is made holding a sketch of the belt")
            g.content.addWidget(self.part)
            self.driving.toggled.connect(self._driving)
            self.length_box.valueChanged.connect(self.changed)
            self.use_thickness.toggled.connect(self.thickness.setEnabled)
            self.use_thickness.toggled.connect(self.changed)
            self.thickness.valueChanged.connect(self.changed)
            self.engage.toggled.connect(self.changed)
            self.first = None
            self.observer = sketchtoolpm.PickObserver(self)
            Gui.Selection.addObserver(self.observer)
            for sub in relationspm.picked_subs(self.sketch):
                self.picked(sub)

        def _names(self):
            names = relationspm._entity_names(self.sketch.Geometry)
            self.list.clear()
            for g in self.picks:
                self.list.addItem(names[g] + ("  (flipped)" if self.sides.get(g, 1) < 0 else ""))

        def picked(self, sub):
            item = sketchtoolpm.item_of(self.sketch, sub)
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("beltchain.py:297", _fw_err)
            if item is None or item.geo < 0 or item.geo >= self.count or item.pos not in (0, 3):
                return
            if not _kind_ok(self.sketch.Geometry[item.geo]) or item.geo in self.picks:
                return
            self.picks.append(item.geo)
            self._names()
            self.list.setCurrentRow(len(self.picks) - 1)
            self.changed()

        def selection_changed(self):
            pass

        def flip_side(self):
            row = self.list.currentRow()
            if 0 <= row < len(self.picks):
                g = self.picks[row]
                self.sides[g] = -self.sides.get(g, 1)
                self._names()
                self.list.setCurrentRow(row)
                self.changed()

        def move_member(self, step):
            row = self.list.currentRow()
            to = row + step
            if 0 <= row < len(self.picks) and 0 <= to < len(self.picks):
                self.picks[row], self.picks[to] = self.picks[to], self.picks[row]
                self._names()
                self.list.setCurrentRow(to)
                self.changed()

        def _driving(self, on):
            self.length_box.setEnabled(on)
            if on and self.first is not None:
                self.length_box.blockSignals(True)
                self.length_box.setValue(belt_length(self.sketch, self.first, len(self.picks)))
                self.length_box.blockSignals(False)
            self.changed()

        def remove_member(self):
            row = self.list.currentRow()
            if 0 <= row < len(self.picks):
                g = self.picks.pop(row)
                self.sides.pop(g, None)
                self._names()
                self.changed()

        def changed(self, *args):
            self.undo_work()
            self.first = None
            self.length.setText("Belt length: -")
            if len(self.picks) < 2:
                self.show_note("Pick the circles in the order the belt runs round them.")
                return
            self.begin()
            try:
                thick = self.thickness.value() if self.use_thickness.isChecked() else 0.0
                first, total = make(self.sketch, self.picks, self.sides, thick, self.engage.isChecked())
            except Exception as error:
                self.undo_work()
                self.show_note(str(error), True)
                return
            self.first = first
            note = ""
            if self.driving.isChecked() and self.length_box.value() > 0:
                try:
                    got = drive_length(self.sketch, self.picks, first, self.length_box.value())
                except Exception as error:
                    got = None
                    App.Console.PrintWarning("FreeCAD: Belt/Chain driving length: %s\n" % error)
                if got is None:
                    note = "The members are held by their relations: the belt length cannot move them."
                elif abs(got - self.length_box.value()) > 1e-3:
                    note = "The belt cannot be made that long here."
            sketchtoolpm._refresh(self.sketch)
            length = belt_length(self.sketch, first, len(self.picks))
            self.length.setText("Belt length: %.2f mm" % length)
            if not self.driving.isChecked():
                self.length_box.blockSignals(True)
                self.length_box.setValue(length)
                self.length_box.blockSignals(False)
            self.show_note(note, bool(note))

        def finish(self):
            if self.first is not None:

                try:
                    from . import blocks
                    n = 2 * len(self.picks)
                    self.belt_block = blocks.make_belt(self.sketch, list(range(self.first, self.first + n)),
                                                       self.picks[0])
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: Belt/Chain: not made a block: %s\n" % error)
            if self.part.isChecked() and self.first is not None:
                self.made_part = belt_part(self.sketch, self.first, len(self.picks))

        def closing(self):
            try:
                Gui.Selection.removeObserver(self.observer)
            except Exception as _fw_err:
                _fw_log("beltchain.py:397", _fw_err)
            self.observer.page = None

    return BeltPage


class _Command:
    def GetResources(self):
        return {"Pixmap": "Sketcher_CreateCircle", "MenuText": "Belt/Chain",
                "ToolTip": "Wraps a belt round circles picked in order: tangent lines and arcs that follow the circles",
                "CmdType": "ForEdit"}

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
        if "SWStyle_BeltChain" not in Gui.listCommands():
            Gui.addCommand("SWStyle_BeltChain", _Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Belt/Chain command not added (%s)\n" % error)
