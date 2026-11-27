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
from PySide import QtWidgets
from . import unitbox

from . import contextbar, dimtools, relationspm, sketchtoolpm
from .sketchfillet import TOL, _corner_of_lines, _num
from . import geomkeep

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchChamfer"
COMMAND = "SWStyle_SketchChamfer"


def _params():
    return App.ParamGet(PARAMS)


def _line_ends_at(sketch, point):
    out = []
    for g, geo in enumerate(sketch.Geometry):
        if dimtools._kind(geo) != "line" or sketch.getConstruction(g):
            continue
        for pos in (1, 2):
            if (sketch.getPoint(g, pos) - point).Length < TOL:
                out.append((g, pos))
    return out


def _free_name(sketch, base):
    names = {c.Name for c in sketch.Constraints}
    k = 1
    while "%s%d" % (base, k) in names:
        k += 1
    return "%s%d" % (base, k)


def _tie_equal(sketch, shown, follower):
    ""

    name = _free_name(sketch, "Chamfer")
    sketch.renameConstraint(shown, name)
    sketch.renameConstraint(follower, name + "_t1")
    sketch.setVirtualSpace(follower, True)
    sketch.setExpression(".Constraints[%d]" % follower, ".Constraints.%s" % name)


def chamfer_corner(sketch, point, d1, second, angle_mode, first=None, equal=False):
    """Chamfers the corner of two lines at point. second is Distance 2, or with angle_mode the
    Direction 1 angle in degrees. first: the geo of Direction 1. equal: Equal distance (one shown
    dimension). Returns the chamfer line or None."""
    import Part
    C = dimtools._constraint
    ends = _line_ends_at(sketch, point)
    if len(ends) != 2:
        return None
    if first is not None and ends[1][0] == first:
        ends.reverse()
    (a, pa), (b, pb) = ends
    P = App.Vector(sketch.getPoint(a, pa))
    far_a = sketch.getPoint(a, 3 - pa)
    far_b = sketch.getPoint(b, 3 - pb)
    la, lb = (far_a - P).Length, (far_b - P).Length
    if la < TOL or lb < TOL:
        return None
    ua, ub = (far_a - P) * (1.0 / la), (far_b - P) * (1.0 / lb)
    phi = math.acos(max(-1.0, min(1.0, ua.dot(ub))))
    if angle_mode:
        theta = math.radians(second)
        k = math.sin(math.pi - theta - phi)
        if abs(k) < 1e-9 or theta <= 0 or theta + phi >= math.pi:
            return None
        d2 = d1 * math.sin(theta) / k
    else:
        d2 = second
    if not (0 < d1 < la - TOL and 0 < d2 < lb - TOL):
        return None
    ea, eb = P + ua * d1, P + ub * d2
    # constraints on the corner: the A-B join goes, the rest move to the virtual sharp
    corner = {(a, pa), (b, pb)}
    sharp = sketch.addGeometry(Part.Point(P), True)
    moved, doomed = [], []
    for i, c in enumerate(sketch.Constraints):
        refs = [(c.First, c.FirstPos), (c.Second, c.SecondPos), (c.Third, c.ThirdPos)]
        hits = [r for r in refs if r in corner]
        if not hits:
            continue
        doomed.append(i)
        if c.Type == "Coincident" and len(hits) == 2:
            continue
        moved.append(c)
    for i in reversed(doomed):
        sketch.delConstraint(i)
    geos = geomkeep.read(sketch)
    for g, pos, e in ((a, pa, ea), (b, pb, eb)):
        seg = geos[g]
        s, t = (e, seg.EndPoint) if pos == 1 else (seg.StartPoint, e)
        geos[g] = Part.LineSegment(s, t)
    sketch.Geometry = geos
    cham = sketch.addGeometry(Part.LineSegment(ea, eb), False)
    cons = [C("Coincident", cham, 1, a, pa), C("Coincident", cham, 2, b, pb),
            C("PointOnObject", sharp, 1, a), C("PointOnObject", sharp, 1, b)]
    for c in moved:
        args = [c.Type]
        for g, pos in ((c.First, c.FirstPos), (c.Second, c.SecondPos), (c.Third, c.ThirdPos)):
            if g is None or g <= -2000:
                break
            if (g, pos) in corner:
                g, pos = sharp, 1
            args += [g, pos]
        if c.Type in relationspm.DIMENSIONS:
            args.append(c.Value)
        try:
            from .sketchmove import _tidy
            cons.append(C(*_tidy(args)))
        except Exception as _fw_err:
            _fw_log("sketchchamfer.py:121", _fw_err)
    sketch.addConstraint(cons)
    dims = [C("Distance", sharp, 1, a, pa, float(d1))]
    if not angle_mode:
        dims.append(C("Distance", sharp, 1, b, pb, float(d2)))
    made = []
    for d in dims:
        try:
            i = sketch.addConstraint(d)
        except Exception as _fw_err:
            _fw_log("sketchchamfer.py:131", _fw_err)
            continue
        _, bad = dimtools.state(sketch)
        if bad:
            sketch.setDriving(i, False)
        made.append(i)
    if equal and not angle_mode and len(made) == 2 and all(sketch.Constraints[i].Driving for i in made):
        try:
            _tie_equal(sketch, made[0], made[1])
        except Exception as _fw_err:
            _fw_log("sketchchamfer.py:equal", _fw_err)
    if angle_mode:
        _angle_dimension(sketch, cham, a, pa, second)
    sketch.solve()
    return cham


def _angle_dimension(sketch, cham, a, pa, degrees):
    """The Direction 1 angle between the chamfer and line A, as an angle between the two lines
    (FreeCAD's line-line Angle picks the pair of directions from the stored ends)."""
    C = dimtools._constraint
    ga, gc = sketch.Geometry[a], sketch.Geometry[cham]
    da = ga.EndPoint - ga.StartPoint
    dc = gc.EndPoint - gc.StartPoint
    want = math.radians(degrees)
    best = None
    for sa in (1, -1):
        for sc in (1, -1):
            u, v = da * sa, dc * sc
            ang = math.atan2(u.x * v.y - u.y * v.x, u.x * v.x + u.y * v.y)
            # fix267: FreeCAD measures from the first line to the second, counterclockwise; a chamfer
            # turning clockwise from line A is measured from the chamfer to A instead (it read 135
            # degrees for a 45 degree chamfer on one corner of a rectangle)
            for swap, value in ((False, ang), (True, -ang)):
                if value < 0:
                    continue
                if best is None or abs(value - want) < abs(best[0] - want):
                    best = (value, sa, sc, swap)
    if best is None:
        return
    _, sa, sc, swap = best
    # Angle(line1, pos1, line2, pos2): the directions point away from the given ends
    p1 = 1 if sa > 0 else 2
    p2 = 1 if sc > 0 else 2
    try:
        if swap:
            i = sketch.addConstraint(C("Angle", cham, p2, a, p1, best[0]))
        else:
            i = sketch.addConstraint(C("Angle", a, p1, cham, p2, best[0]))
    except Exception:
        return
    _, bad = dimtools.state(sketch)
    if bad:
        sketch.setDriving(i, False)


class SketchChamferPage(sketchtoolpm.ToolPage):
    TITLE = "Sketch Chamfer"
    ICON = "SKETCH_CHAMFER"
    PIXMAP = "Sketcher_CreateChamfer"

    def build(self):
        p = _params()
        self.corners = []                 # (point, first line or None)
        self._first_line = None
        g = self.group("Chamfer Parameters")
        self.angle_distance = QtWidgets.QRadioButton("Angle-distance", g.body)
        self.distance_distance = QtWidgets.QRadioButton("Distance-distance", g.body)
        (self.angle_distance if p.GetBool("AngleDistance", False) else self.distance_distance).setChecked(True)
        self.equal = QtWidgets.QCheckBox("Equal distance", g.body)
        self.equal.setChecked(p.GetBool("EqualDistance", True))
        self.d1 = self._number(g, p.GetFloat("Distance1", 10.0), " mm", "Distance 1")
        self.d2 = self._number(g, p.GetFloat("Distance2", 10.0), " mm", "Distance 2")
        self.angle = unitbox.UnitSpinBox(g.body)
        self.angle.setRange(0.01, 179.99)
        self.angle.setDecimals(2)
        self.angle.setSuffix("°")
        self.angle.setValue(p.GetFloat("Angle", 45.0))
        self.angle.setToolTip("Direction 1 Angle")
        for w in (self.angle_distance, self.distance_distance, self.equal):
            g.content.addWidget(w)
        self.form = form = QtWidgets.QFormLayout()
        form.addRow("Distance 1:", self.d1)
        form.addRow("Direction 1 Angle:", self.angle)
        form.addRow("Distance 2:", self.d2)
        g.content.addLayout(form)
        g = self.group("Entities to Chamfer")
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWSelectedEntities")
        self.list.setFixedHeight(90)
        g.content.addWidget(self.list)
        hint = QtWidgets.QLabel("Pick corners, or the two lines of a corner (the first is Direction 1).", g.body)
        hint.setWordWrap(True)
        g.content.addWidget(hint)
        for w in (self.angle_distance, self.distance_distance, self.equal):
            w.toggled.connect(self._mode)
        self._mode()
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        for sub in relationspm.picked_subs(self.sketch):
            self.picked(sub)

    def _number(self, g, value, suffix, tip):
        box = unitbox.UnitSpinBox(g.body)
        box.setRange(0.001, 1e6)
        box.setDecimals(3)
        box.setSuffix(suffix)
        box.setValue(value)
        box.setToolTip(tip)
        return box

    def _mode(self, *args):
        ang = self.angle_distance.isChecked()
        self.equal.setVisible(not ang)
        self.form.setRowVisible(self.angle, ang) if hasattr(self.form, "setRowVisible") else self.angle.setVisible(ang)
        two = not ang and not self.equal.isChecked()
        if hasattr(self.form, "setRowVisible"):
            self.form.setRowVisible(self.d2, two)
        else:
            self.d2.setVisible(two)
            lab = self.form.labelForField(self.d2)
            if lab is not None:
                lab.setVisible(two)
            lab = self.form.labelForField(self.angle)
            if lab is not None:
                lab.setVisible(ang)

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("sketchchamfer.py:248", _fw_err)
        if item is None or item.geo < 0:
            return
        point, first = None, None
        if item.pos in (1, 2):
            point = self.sketch.getPoint(item.geo, item.pos)
        elif item.pos == relationspm.NONE and dimtools._kind(self.sketch.Geometry[item.geo]) == "line":
            if self._first_line is None or self._first_line == item.geo:
                self._first_line = item.geo
                self.show_note("Now pick the other line of the corner.")
                return
            point = _corner_of_lines(self.sketch, self._first_line, item.geo)
            first = self._first_line
            self._first_line = None
        if point is None or len(_line_ends_at(self.sketch, point)) != 2:
            self.show_note("That is not a corner where two sketch lines meet.", True)
            return
        if any((point - c[0]).Length < TOL for c in self.corners):
            return
        self.corners.append((App.Vector(point), first))
        self.list.addItem("Corner at (%s, %s)" % (_num(point.x), _num(point.y)))
        self.show_note("")

    def selection_changed(self):
        pass

    def values(self):
        ang = self.angle_distance.isChecked()
        d1 = self.d1.value()
        if ang:
            return d1, self.angle.value(), True
        return d1, (d1 if self.equal.isChecked() else self.d2.value()), False

    def finish(self):
        if not self.corners:
            return
        p = _params()
        p.SetBool("AngleDistance", self.angle_distance.isChecked())
        p.SetBool("EqualDistance", self.equal.isChecked())
        p.SetFloat("Distance1", self.d1.value())
        p.SetFloat("Distance2", self.d2.value())
        p.SetFloat("Angle", self.angle.value())
        self.begin()
        d1, second, ang = self.values()
        failed = 0
        for point, first in self.corners:
            if chamfer_corner(self.sketch, point, d1, second, ang, first,
                              equal=not ang and self.equal.isChecked()) is None:
                failed += 1
        sketchtoolpm._refresh(self.sketch)
        if failed:
            Gui.getMainWindow().statusBar().showMessage(
                "Sketch Chamfer: %d corner%s could not take that chamfer." % (failed, "" if failed == 1 else "s"), 8000)

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("sketchchamfer.py:305", _fw_err)
        self.observer.page = None


class SketchChamferCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_CreateChamfer", "MenuText": "Sketch Chamfer",
                "ToolTip": "Chamfers sketch corners: Angle-distance or Distance-distance",
                "CmdType": "ForEdit"}

    def IsActive(self):
        # sketchfirst-1126: live with a document; with no sketch open it shows the "open a sketch first" page
        return contextbar.sketch_in_edit() is not None or App.ActiveDocument is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(SketchChamferPage(sketch))
        else:
            from . import solidfirstlive
            solidfirstlive.sketch_first("SketchChamfer")


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, SketchChamferCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
