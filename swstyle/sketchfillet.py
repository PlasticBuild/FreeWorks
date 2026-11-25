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

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchFillet"
TOL = 1e-6


def _params():
    return App.ParamGet(PARAMS)


def corner_at(sketch, point):
    """(geo, pos) of a line end at point that meets another curve's end there, else None."""
    ends = []
    for g, geo in enumerate(sketch.Geometry):
        kind = dimtools._kind(geo)
        if kind not in ("line", "arc"):
            continue
        for pos in (1, 2):
            if (sketch.getPoint(g, pos) - point).Length < TOL:
                ends.append((g, pos, kind))
    if len(ends) < 2:
        return None
    lines = [e for e in ends if e[2] == "line"]
    g, pos, _ = (lines or ends)[0]
    return g, pos


def _corner_of_lines(sketch, a, b):
    for i in (1, 2):
        for j in (1, 2):
            p = sketch.getPoint(a, i)
            if (p - sketch.getPoint(b, j)).Length < TOL:
                return p
    return None


TOO_LARGE = "The radius is too large: a line between the corners would have no length left."


def too_large(sketch, corners, radius):
    ""


    used = {}
    for point in corners:
        ends = []
        for g, geo in enumerate(sketch.Geometry):
            if dimtools._kind(geo) != "line":
                continue
            for pos in (1, 2):
                if (sketch.getPoint(g, pos) - point).Length < TOL:
                    ends.append((g, pos))
        if len(ends) != 2:
            continue
        (a, pa), (b, pb) = ends
        da = sketch.getPoint(a, 3 - pa) - point
        db = sketch.getPoint(b, 3 - pb) - point
        if da.Length < TOL or db.Length < TOL:
            continue
        cos = max(-1.0, min(1.0, da.dot(db) / (da.Length * db.Length)))
        angle = math.acos(cos)              # the corner's angle between the two lines
        if angle < 1e-9 or abs(angle - math.pi) < 1e-9:
            continue
        cut = float(radius) / math.tan(angle / 2)   # how far the fillet eats into each line
        used[a] = used.get(a, 0.0) + cut
        used[b] = used.get(b, 0.0) + cut
    for g, cut in used.items():
        if cut >= sketch.Geometry[g].length() - 1e-6:
            return True
    return False


def make_fillets(sketch, corners, radius, keep_corners=True, each=False):
    """Fillets every corner (points in sketch coordinates); (arcs made, corners that failed)."""
    arcs, failed = [], 0
    for point in corners:
        found = corner_at(sketch, point)
        if found is None:
            failed += 1
            continue
        before = len(sketch.Geometry)
        try:
            sketch.fillet(found[0], found[1], float(radius), True, bool(keep_corners))
        except Exception:
            failed += 1
            continue
        new = [g for g in range(before, len(sketch.Geometry)) if dimtools._kind(sketch.Geometry[g]) == "arc"]
        if new:
            arcs.append(new[-1])
        else:
            failed += 1
    C = dimtools._constraint
    for k, arc in enumerate(arcs):
        if k == 0 or each:
            sketch.addConstraint(C("Radius", arc, float(radius)))
        else:
            sketch.addConstraint(C("Equal", arcs[0], arc))
    sketch.solve()
    return arcs, failed


LOSING = ("A segment being filleted has a midpoint or equal length or equiDistant relation. EquiDistant "
          "relation will be deleted and the geometry might move if the fillet is created. Do you want to continue?")
ASK = []        # tests: a callable answering the question (True: Yes)


def ask_losing():
    for hook in ASK:
        return bool(hook(LOSING))
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "FreeCAD", LOSING,
                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, Gui.getMainWindow())
    return box.exec() == QtWidgets.QMessageBox.Yes


class SketchFilletPage(sketchtoolpm.ToolPage):
    TITLE = "Sketch Fillet"
    ICON = "SKETCH_FILLET"
    PIXMAP = "Sketcher_CreateFillet"

    def build(self):
        p = _params()
        self.corners = []
        self._first_line = None
        g = self.group("Entities to Fillet")
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWSelectedEntities")
        self.list.setFixedHeight(90)
        g.content.addWidget(self.list)
        hint = QtWidgets.QLabel("Pick corners, or the two lines of a corner.", g.body)
        hint.setWordWrap(True)
        g.content.addWidget(hint)
        g = self.group("Fillet Parameters")
        self.radius = unitbox.UnitSpinBox(g.body)
        self.radius.setRange(0.001, 1e6)
        self.radius.setDecimals(3)
        self.radius.setSuffix(" mm")
        self.radius.setValue(p.GetFloat("Radius", 10.0))
        self.radius.setToolTip("Fillet radius")
        g.content.addWidget(self.radius)
        self.keep = QtWidgets.QCheckBox("Keep constrained corners", g.body)
        self.keep.setChecked(p.GetBool("KeepCorners", True))
        self.each = QtWidgets.QCheckBox("Dimension each fillet", g.body)
        self.each.setChecked(p.GetBool("DimensionEach", False))
        g.content.addWidget(self.keep)
        g.content.addWidget(self.each)
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        self._preselected(relationspm.picked_subs(self.sketch))

    def _preselected(self, subs):
        """Entities picked before the tool: every corner where two of the picked lines or arcs
        meet (a just-drawn rectangle, still picked, gets all four), and any picked vertex."""
        curves = []
        for sub in subs:
            item = sketchtoolpm.item_of(self.sketch, sub)
            if item is not None and item.geo >= 0 and item.pos == relationspm.NONE \
                    and dimtools._kind(self.sketch.Geometry[item.geo]) in ("line", "arc"):
                curves.append(item.geo)
            else:
                self.picked(sub)
        if len(curves) == 1:
            self.picked("Edge%d" % (curves[0] + 1))
            return
        for k, a in enumerate(curves):
            for b in curves[k + 1:]:
                point = _corner_of_lines(self.sketch, a, b)
                if point is None or corner_at(self.sketch, point) is None:
                    continue
                if any((point - c).Length < TOL for c in self.corners):
                    continue
                self.corners.append(point)
                self._listed(point)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("sketchfillet.py:167", _fw_err)

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("sketchfillet.py:174", _fw_err)
        if item is None or item.geo < 0:
            return
        point = None
        if item.pos in (1, 2):
            point = self.sketch.getPoint(item.geo, item.pos)
        elif item.pos == relationspm.NONE and dimtools._kind(self.sketch.Geometry[item.geo]) == "line":
            if self._first_line is None or self._first_line == item.geo:
                self._first_line = item.geo
                self.show_note("Now pick the other line of the corner.")
                return
            point = _corner_of_lines(self.sketch, self._first_line, item.geo)
            self._first_line = None
        if point is None or corner_at(self.sketch, point) is None:
            self.show_note("That is not a corner where two sketch entities meet.", True)
            return
        if any((point - c).Length < TOL for c in self.corners):
            return
        self.corners.append(point)
        self._listed(point)
        self.show_note("")

    def _listed(self, point):
        ""

        item = QtWidgets.QListWidgetItem("Fillet<%d>" % (self.list.count() + 1))
        item.setToolTip("Corner at (%s, %s)" % (_num(point.x), _num(point.y)))
        self.list.addItem(item)
        try:
            Gui.getMainWindow().statusBar().showMessage("Please review your selection.", 8000)
        except Exception as _fw_err:
            _fw_log("sketchfillet.py:205", _fw_err)

    def selection_changed(self):
        pass

    def _losing(self):
        ""

        lines = set()
        for point in self.corners:
            for g, geo in enumerate(self.sketch.Geometry):
                if dimtools._kind(geo) != "line":
                    continue
                for pos in (1, 2):
                    if (self.sketch.getPoint(g, pos) - point).Length < TOL:
                        lines.add(g)
        out = []
        for i, c in enumerate(self.sketch.Constraints):
            if c.Type == "Equal" and (c.First in lines or c.Second in lines):
                out.append(i)
            elif c.Type == "Symmetric" and c.First == c.Second and c.First in lines \
                    and {int(c.FirstPos), int(c.SecondPos)} == {1, 2}:
                out.append(i)       # a point on the line's midpoint
        return out

    def accept(self):
        # a radius that would leave a line with no length: the page stays open with the reason,
        # nothing is made, so a smaller radius can be typed
        if self.corners and too_large(self.sketch, self.corners, self.radius.value()):
            self.show_note(TOO_LARGE, True)
            return
        super().accept()

    def finish(self):
        if not self.corners:
            return
        losing = self._losing()
        if losing and not ask_losing():
            return
        if losing:
            self.begin()
            for i in sorted(losing, reverse=True):
                self.sketch.delConstraint(i)
        p = _params()
        p.SetFloat("Radius", self.radius.value())
        p.SetBool("KeepCorners", self.keep.isChecked())
        p.SetBool("DimensionEach", self.each.isChecked())
        self.begin()
        arcs, failed = make_fillets(self.sketch, self.corners, self.radius.value(), self.keep.isChecked(),
                                    self.each.isChecked())
        sketchtoolpm._refresh(self.sketch)
        if failed:
            Gui.getMainWindow().statusBar().showMessage(
                "Sketch Fillet: %d corner%s could not take that radius." % (failed, "" if failed == 1 else "s"), 8000)

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("sketchfillet.py:256", _fw_err)
        self.observer.page = None


def _num(v):
    return ("%.3f" % v).rstrip("0").rstrip(".")


class SketchFilletCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_CreateFillet", "MenuText": "Sketch Fillet",
                "ToolTip": "Rounds sketch corners: one radius dimension, Equal on the other fillets",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(SketchFilletPage(sketch))


COMMAND = "SWStyle_SketchFillet"


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, SketchFilletCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
