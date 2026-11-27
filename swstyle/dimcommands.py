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
from PySide import QtCore, QtGui, QtWidgets

from . import contextbar, dimtools, relationspm, sketchtoolpm

Qt = QtCore.Qt
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/FullyDefine"


def _params():
    return App.ParamGet(PARAMS)


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 8000)
    except Exception as _fw_err:
        _fw_log("dimcommands.py:46", _fw_err)


def _picked_geometry(sketch):
    """Own geometry ids of the picked sketch elements (a picked point counts for its curve)."""
    out = []
    for item in relationspm.items_of(sketch, relationspm.picked_subs(sketch)):
        if item.geo >= 0 and item.geo not in out:
            out.append(item.geo)
    return out


# --------------------------------------------------------------------------- Fully Define page
class DatumBox(QtWidgets.QListWidget):
    """A one-entry pick box; light blue while it takes the next pick."""

    def __init__(self, page, parent):
        super().__init__(parent)
        self.page = page
        self.value = dimtools.ORIGIN
        self.setFixedHeight(24)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("SWDatum")

    def set_value(self, value):
        self.value = value
        self.clear()
        self.addItem(sketchtoolpm.point_name(self.page.sketch, *value))

    def set_active(self, on):
        self.setObjectName("SWSelectedEntities" if on else "SWDatum")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        self.page.activate_box(self)
        super().mousePressEvent(event)


class FullyDefinePage(sketchtoolpm.ToolPage):
    TITLE = "Fully Define Sketch"
    ICON = "DIMENSIONS_FULLY_DEFINE_SKETCH"
    PIXMAP = "Constraint_Lock"

    def build(self):
        p = _params()
        self._calculated = False
        self._active_box = None
        # Entities to Fully Define
        g = self.group("Entities to Fully Define")
        self.all_entities = QtWidgets.QRadioButton("All entities in sketch", g.body)
        self.selected_entities = QtWidgets.QRadioButton("Selected entities", g.body)
        self.all_entities.setChecked(True)
        self.entity_list = QtWidgets.QListWidget(g.body)
        self.entity_list.setObjectName("SWSelectedEntities")
        self.entity_list.setFixedHeight(70)
        self.entity_list.setEnabled(False)
        self.selected_entities.toggled.connect(self._entities_mode)
        self.calc = QtWidgets.QPushButton("Calculate", g.body)
        self.calc.setObjectName("SWFullyDefineCalculate")
        self.calc.clicked.connect(self._calc_clicked)
        for w in (self.all_entities, self.selected_entities, self.entity_list, self.calc):
            g.content.addWidget(w)
        # Relations
        self.relations_group = g = self.group("Relations")
        self.relations_on = QtWidgets.QCheckBox("Relations", g.body)
        self.relations_on.setChecked(p.GetBool("Relations", True))
        g.content.addWidget(self.relations_on)
        self.relation_boxes = self.toggles(g, dimtools.RELATIONS, relationspm.relation_icon,
                                           lambda key: p.GetBool("Relation" + key, True))
        self.select_all = QtWidgets.QCheckBox("Select All", g.body)
        self.select_all.setChecked(all(b.isChecked() for b in self.relation_boxes.values()))
        self.select_all.toggled.connect(self._select_all)
        g.content.addWidget(self.select_all)

        self.deselect_all = QtWidgets.QCheckBox("Deselect All", g.body)
        self.deselect_all.setChecked(not any(b.isChecked() for b in self.relation_boxes.values()))
        self.deselect_all.toggled.connect(self._deselect_all)
        g.content.addWidget(self.deselect_all)
        for b in self.relation_boxes.values():
            b.toggled.connect(self._relation_toggled)
        self.relations_on.toggled.connect(self._relations_enabled)
        self._relations_enabled(self.relations_on.isChecked())
        # Dimensions
        self.dimensions_group = g = self.group("Dimensions")
        self.dimensions_on = QtWidgets.QCheckBox("Dimensions", g.body)
        self.dimensions_on.setChecked(p.GetBool("Dimensions", True))
        g.content.addWidget(self.dimensions_on)
        g.content.addWidget(QtWidgets.QLabel("Horizontal Dimensions Scheme:", g.body))
        self.h_scheme = self._scheme(g, p.GetString("HorizontalScheme", "Baseline"))
        g.content.addWidget(QtWidgets.QLabel("Datum - Vertical Model Edge, Model Vertex, Vertical Line or Point:", g.body))
        self.h_datum = DatumBox(self, g.body)
        self.h_datum.set_value(dimtools.ORIGIN)
        g.content.addWidget(self.h_datum)
        g.content.addWidget(QtWidgets.QLabel("Vertical Dimensions Scheme:", g.body))
        self.v_scheme = self._scheme(g, p.GetString("VerticalScheme", "Baseline"))
        g.content.addWidget(QtWidgets.QLabel("Datum - Horizontal Model Edge, Model Vertex, Horizontal Line or Point:", g.body))
        self.v_datum = DatumBox(self, g.body)
        self.v_datum.set_value(dimtools.ORIGIN)
        g.content.addWidget(self.v_datum)
        g.content.addWidget(QtWidgets.QLabel("Dimension placement:", g.body))
        self.above = QtWidgets.QRadioButton("Above sketch", g.body)
        self.below = QtWidgets.QRadioButton("Below sketch", g.body)
        self.right = QtWidgets.QRadioButton("Right of sketch", g.body)
        self.left = QtWidgets.QRadioButton("Left of sketch", g.body)
        for pair in ((self.above, self.below), (self.right, self.left)):
            group = QtWidgets.QButtonGroup(self)    # two choices, not one among four
            for b in pair:
                group.addButton(b)
                g.content.addWidget(b)
        (self.above if p.GetInt("HorizontalSide", 1) > 0 else self.below).setChecked(True)
        (self.right if p.GetInt("VerticalSide", 1) > 0 else self.left).setChecked(True)
        for label in g.body.findChildren(QtWidgets.QLabel):
            label.setWordWrap(True)
        self.dimensions_on.toggled.connect(self._dimensions_enabled)
        self._dimensions_enabled(self.dimensions_on.isChecked())
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        picked = _picked_geometry(self.sketch)
        if picked:
            self.selected_entities.setChecked(True)
        self.selection_changed()

    def _scheme(self, g, current):
        box = QtWidgets.QComboBox(g.body)
        box.addItems(list(dimtools.SCHEMES))
        box.setCurrentText(current if current in dimtools.SCHEMES else "Baseline")
        g.content.addWidget(box)
        return box

    def _entities_mode(self, on):
        self.entity_list.setEnabled(on)
        if on:
            self.activate_box(None)

    def _select_all(self, on):
        if getattr(self, "_syncing", False):
            return
        self._syncing = True
        for b in self.relation_boxes.values():
            b.setChecked(on)
        self._syncing = False
        self._relation_toggled()

    def _deselect_all(self, on):
        if getattr(self, "_syncing", False) or not on:
            return
        self._syncing = True
        for b in self.relation_boxes.values():
            b.setChecked(False)
        self._syncing = False
        self._relation_toggled()

    def _relation_toggled(self, *args):
        if getattr(self, "_syncing", False) or not hasattr(self, "deselect_all"):
            return
        states = [b.isChecked() for b in self.relation_boxes.values()]
        self._syncing = True
        self.select_all.setChecked(all(states))
        self.deselect_all.setChecked(not any(states))
        self._syncing = False

    def _relations_enabled(self, on):
        for b in list(self.relation_boxes.values()) + [self.select_all, getattr(self, "deselect_all", self.select_all)]:
            b.setEnabled(on)

    def _dimensions_enabled(self, on):
        for w in (self.h_scheme, self.v_scheme, self.h_datum, self.v_datum, self.above, self.below,
                  self.right, self.left):
            w.setEnabled(on)

    def activate_box(self, box):
        """A datum box takes the next pick; None gives picks back to the entity list."""
        for b in (self.h_datum, self.v_datum):
            b.set_active(b is box)
        self._active_box = box

    # ------------------------------------------------------------------ picks
    def picked(self, sub):
        box = self._active_box
        if box is None:
            self.selection_changed()
            return
        item = sketchtoolpm.item_of(self.sketch, sub)
        if item is None:
            return
        if item.root or (item.geo, item.pos) == dimtools.ORIGIN:
            value = dimtools.ORIGIN
        elif item.pos in (1, 2, 3):
            value = (item.geo, item.pos)
        elif item.kind == "line" and item.geo >= 0:
            value = (item.geo, 1)      # a line as datum: its points share the coordinate that counts
        else:
            return
        box.set_value(value)
        self.activate_box(None)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("dimcommands.py:246", _fw_err)

    def selection_changed(self):
        if self._active_box is not None:
            return
        self.entity_list.clear()
        names = relationspm._entity_names(self.sketch.Geometry)
        for g in _picked_geometry(self.sketch):
            if 0 <= g < len(names):
                self.entity_list.addItem(names[g])

    # ------------------------------------------------------------------ work
    def options(self):
        relations = [k for k, b in self.relation_boxes.items() if b.isChecked()] \
            if self.relations_on.isChecked() else []
        entities = _picked_geometry(self.sketch) if self.selected_entities.isChecked() else None
        return dict(relations=relations, dimensions=self.dimensions_on.isChecked(), entities=entities,
                    h_scheme=self.h_scheme.currentText(), v_scheme=self.v_scheme.currentText(),
                    h_datum=self.h_datum.value, v_datum=self.v_datum.value,
                    h_side=1 if self.above.isChecked() else -1, v_side=1 if self.right.isChecked() else -1)

    def remember(self):
        p = _params()
        p.SetBool("Relations", self.relations_on.isChecked())
        p.SetBool("Dimensions", self.dimensions_on.isChecked())
        for k, b in self.relation_boxes.items():
            p.SetBool("Relation" + k, b.isChecked())
        p.SetString("HorizontalScheme", self.h_scheme.currentText())
        p.SetString("VerticalScheme", self.v_scheme.currentText())
        p.SetInt("HorizontalSide", 1 if self.above.isChecked() else -1)
        p.SetInt("VerticalSide", 1 if self.right.isChecked() else -1)

    def _calc_clicked(self):
        ""
        if self._calculated:
            self.undo_work()
            sketchtoolpm._refresh(self.sketch)
            self._calculated = False
            self.calc.setText("Calculate")
            self.show_note("", False)
            return
        self.calculate()

    def calculate(self):
        options = self.options()
        if options["entities"] is not None and not options["entities"]:
            self.show_note("Pick the sketch entities to fully define, or choose All entities in sketch.", True)
            return
        self.undo_work()        # Calculate again starts from the sketch as it was
        self.begin()
        try:
            result = dimtools.fully_define(self.sketch, **options)
        except Exception as error:
            self.undo_work()
            self.show_note("Could not fully define the sketch: %s" % error, True)
            return
        sketchtoolpm._refresh(self.sketch)
        self._calculated = True
        self.calc.setText("Undo")
        self.remember()
        text = dimtools.describe(result)
        self.show_note(text, result.get("over", False))
        _status(text)

    def finish(self):
        if not self._calculated:
            self.calculate()

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("dimcommands.py:318", _fw_err)
        self.observer.page = None


# --------------------------------------------------------------------------- Scan Equal page
def equal_sets(sketch, lengths=True, radii=True):
    """[(label, [geo...])]: lines of one length and arcs and circles of one radius not yet all equal."""
    sk = dimtools.Sketch(sketch)
    names = relationspm._entity_names(sketch.Geometry)
    out = []
    for group in dimtools.equal_groups(sk, lengths, radii):
        if _all_equal(sketch, group):
            continue
        first = group[0]
        if sk.kinds[first] == "line":
            value = "length %s" % _mm(dimtools._direction(sk, first)[1])
        else:
            value = "radius %s" % _mm(sk.geos[first].Radius)
        label = "%s (%s)" % (", ".join(names[g] for g in group), value)
        out.append((label, group))
    return out


def _mm(value):
    return ("%.3f" % value).rstrip("0").rstrip(".") + " mm"


def _all_equal(sketch, group):
    """True when Equal relations already tie the whole group together."""
    parent = {g: g for g in group}

    def find(g):
        while parent[g] != g:
            g = parent[g]
        return g
    for c in sketch.Constraints:
        if c.Type == "Equal" and c.First in parent and c.Second in parent:
            parent[find(c.First)] = find(c.Second)
    return len({find(g) for g in group}) == 1


def set_equal(sketch, group):
    """Adds the Equal relations a set needs; the number kept."""
    kept = 0
    for g in group[1:]:
        if dimtools.attempt(sketch, dimtools._constraint("Equal", group[0], g)) is not None:
            kept += 1
    return kept


class ScanEqualPage(sketchtoolpm.ToolPage):
    TITLE = "Scan Equal"
    ICON = "DIMENSIONS_SCAN_EQUAL"
    PIXMAP = "Constraint_EqualLength"

    def build(self):
        g = self.group("Search")
        self.lengths = QtWidgets.QCheckBox("Equal lengths", g.body)
        self.radii = QtWidgets.QCheckBox("Equal radii", g.body)
        self.lengths.setChecked(True)
        self.radii.setChecked(True)
        self.scan = QtWidgets.QPushButton("Scan", g.body)
        self.scan.setObjectName("SWScanEqualScan")
        self.scan.clicked.connect(self.rescan)
        for w in (self.lengths, self.radii, self.scan):
            g.content.addWidget(w)
        g = self.group("Results")
        self.results = QtWidgets.QListWidget(g.body)
        self.results.setObjectName("SWScanEqualResults")
        self.results.setMinimumHeight(110)
        self.results.setWordWrap(True)
        self.results.currentRowChanged.connect(self._show_set)
        g.content.addWidget(self.results)
        row = QtWidgets.QHBoxLayout()
        self.set_one = QtWidgets.QPushButton("Set Equal", g.body)
        self.set_all = QtWidgets.QPushButton("Set All Equal", g.body)
        self.set_one.clicked.connect(self.equal_current)
        self.set_all.clicked.connect(self.equal_all)
        row.addWidget(self.set_one)
        row.addWidget(self.set_all)
        g.content.addLayout(row)
        self.sets = []
        self.rescan()

    def rescan(self):
        self.sets = equal_sets(self.sketch, self.lengths.isChecked(), self.radii.isChecked())
        self.results.clear()
        for label, group in self.sets:
            self.results.addItem(label)
        self.set_one.setEnabled(bool(self.sets))
        self.set_all.setEnabled(bool(self.sets))
        if self.sets:
            self.results.setCurrentRow(0)
            self.show_note("")
        else:
            self.show_note("No more entities of equal length or radius.")

    def _show_set(self, row):
        try:
            Gui.Selection.clearSelection()
            if 0 <= row < len(self.sets):
                for g in self.sets[row][1]:
                    Gui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Edge%d" % (g + 1))
        except Exception as _fw_err:
            _fw_log("dimcommands.py:422", _fw_err)

    def _apply(self, groups):
        self.begin()
        kept = sum(set_equal(self.sketch, group) for group in groups)
        sketchtoolpm._refresh(self.sketch)
        self.rescan()
        text = "Added %d Equal relation%s." % (kept, "" if kept == 1 else "s")
        if not kept:
            text = "The sketch takes no more Equal relations there (they would over-define it)."
        self.show_note(text, not kept)
        _status(text)

    def equal_current(self):
        row = self.results.currentRow()
        if 0 <= row < len(self.sets):
            self._apply([self.sets[row][1]])

    def equal_all(self):
        self._apply([group for _, group in self.sets])

    def closing(self):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("dimcommands.py:447", _fw_err)


# --------------------------------------------------------------------------- Baseline, Chain, Ordinate
def _target_point(sketch, item):
    """The point a pick is measured at: a vertex itself, a circle's or arc's centre, a line's start."""
    if item.root:
        return dimtools.ORIGIN
    if item.pos in (1, 2, 3):
        return (item.geo, item.pos)
    if item.geo >= 0:
        kind = dimtools._kind(sketch.Geometry[item.geo])
        if kind in ("circle", "arc", "ellipse", "conic_arc"):
            return (item.geo, 3)
        if kind == "line":
            return (item.geo, 1)
    if item.geo in (dimtools.H_AXIS, dimtools.V_AXIS):
        return dimtools.ORIGIN
    return None


def _line_direction(sketch, item):
    """'x' for a vertical line (it measures across, horizontally), 'y' for a horizontal one."""
    if item.pos != relationspm.NONE:
        return None
    if item.geo == dimtools.V_AXIS:
        return "x"
    if item.geo == dimtools.H_AXIS:
        return "y"
    if item.geo >= 0 and dimtools._kind(sketch.Geometry[item.geo]) == "line":
        a, b = sketch.getPoint(item.geo, 1), sketch.getPoint(item.geo, 2)
        return "x" if abs(b.x - a.x) <= abs(b.y - a.y) else "y"
    return None


def place_dimension(sketch, axis, a, b, stack):
    """A horizontal (x) or vertical (y) dimension from point a to point b at the geometry's own
    value, stacked outward; driven when driving would over-define. (index, driven) or None."""
    pa, pb = sketch.getPoint(*a), sketch.getPoint(*b)
    value = (pb.x - pa.x) if axis == "x" else (pb.y - pa.y)
    if abs(value) < dimtools.LENGTH_TOL:
        return None
    c = dimtools._distance(axis, a, b, value)
    try:
        index = sketch.addConstraint(c)
    except Exception:
        return None
    driven = False
    _, bad = dimtools.state(sketch)
    if bad:
        sketch.setDriving(index, False)
        sketch.solve()
        driven = True
    sk = dimtools.Sketch(sketch)
    size, _ = sk.size()
    gap = max(size * 0.08, 2.0)
    c = sketch.Constraints[index]
    p1, p2 = sketch.getPoint(c.First, c.FirstPos), sketch.getPoint(c.Second, c.SecondPos)
    if axis == "x":
        want = (max(p1.y, p2.y) - min(p1.y, p2.y)) + gap * stack
        want = want if p2.y >= p1.y else want
    else:
        want = -((max(p1.x, p2.x) - min(p1.x, p2.x)) + gap * stack)
    try:
        sketch.setLabelDistance(index, want)
    except Exception as _fw_err:
        _fw_log("dimcommands.py:513", _fw_err)
    return index, driven


class RunningDimensionPage(sketchtoolpm.ToolPage):
    """Baseline: every pick is dimensioned from the first one. Chain: each pick from the one before.
    Ordinate: as Baseline, all from the zero point, the labels in one row (FreeCAD has no
    ordinate dimension: the values show as dimensions from the zero point)."""

    MODE = "Baseline"

    def build(self):
        self.base = None
        self.axis = None
        self.stack = 0
        self.made = []
        g = self.group("Message")
        self.message = QtWidgets.QLabel(g.body)
        self.message.setWordWrap(True)
        g.content.addWidget(self.message)
        g = self.group("Direction")
        self.horizontal = QtWidgets.QRadioButton("Horizontal", g.body)
        self.vertical = QtWidgets.QRadioButton("Vertical", g.body)
        self.horizontal.setChecked(self.AXIS != "y")
        self.vertical.setChecked(self.AXIS == "y")
        for b in (self.horizontal, self.vertical):
            g.content.addWidget(b)
        g = self.group("Dimensions")
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWSelectedEntities")
        self.list.setFixedHeight(90)
        g.content.addWidget(self.list)
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        self._prompt()
        for sub in relationspm.picked_subs(self.sketch)[:1]:
            QtCore.QTimer.singleShot(0, lambda s=sub: self.picked(s))

    AXIS = None

    def _prompt(self):
        if self.base is None:
            first = {"Baseline": "the baseline", "Chain": "where the chain starts",
                     "Ordinate": "the zero point"}[self.MODE]
            self.message.setText("Select %s: a line, point, circle or arc." % first)
        else:
            self.message.setText("Select the entities to dimension. The check mark or Esc ends the tool.")

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("dimcommands.py:566", _fw_err)
        if item is None:
            return
        point = _target_point(self.sketch, item)
        if point is None:
            self.show_note("That entity cannot be dimensioned this way.", True)
            return
        if self.base is None:
            self.base = point
            direction = _line_direction(self.sketch, item)
            if direction is not None:
                (self.horizontal if direction == "x" else self.vertical).setChecked(True)
            self.show_note("")
            self._prompt()
            return
        axis = "x" if self.horizontal.isChecked() else "y"
        self.begin()
        self.stack += 1
        made = place_dimension(self.sketch, axis, self.base, point,
                               1 if self.MODE == "Ordinate" else self.stack)
        sketchtoolpm._refresh(self.sketch)
        if made is None:
            self.stack -= 1
            self.show_note("Nothing to measure: that point is level with the last one.", True)
            return
        index, driven = made
        c = self.sketch.Constraints[index]
        self.made.append(index)
        self.list.addItem("%s%s" % (_mm(abs(c.Value)), " (driven)" if driven else ""))
        self.show_note("Driven: a driving dimension would over-define the sketch." if driven else "")
        if self.MODE == "Chain":
            self.base = point

    def selection_changed(self):
        pass

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("dimcommands.py:606", _fw_err)
        self.observer.page = None


class BaselinePage(RunningDimensionPage):
    TITLE = "Baseline Dimension"
    MODE = "Baseline"
    ICON = "DIMENSIONS_BASELINE"
    PIXMAP = "Constraint_HorizontalDistance"


class ChainPage(RunningDimensionPage):
    TITLE = "Chain Dimension"
    MODE = "Chain"
    ICON = "DIMENSIONS_CHAIN"
    PIXMAP = "Constraint_HorizontalDistance"


class OrdinatePage(RunningDimensionPage):
    TITLE = "Ordinate Dimension"
    MODE = "Ordinate"
    ICON = "DIMENSIONS_ORDINATE"
    PIXMAP = "Constraint_HorizontalDistance"


class HorizontalOrdinatePage(OrdinatePage):
    TITLE = "Horizontal Ordinate Dimension"
    AXIS = "x"


class VerticalOrdinatePage(OrdinatePage):
    TITLE = "Vertical Ordinate Dimension"
    AXIS = "y"
    PIXMAP = "Constraint_VerticalDistance"


# --------------------------------------------------------------------------- Angular Running, Symmetric
# --------------------------------------------------------------------------- Linear Diameter, Chamfer
def add_kept(sketch, constraint):
    """Adds a dimension; driven (reference) when driving it would over-define. (index, driven) or None."""
    try:
        index = sketch.addConstraint(constraint)
    except Exception:
        return None
    _, bad = dimtools.state(sketch)
    if bad:
        sketch.setDriving(index, False)
        sketch.solve()
        return index, True
    return index, False


def _line_angle(sketch, g):
    a, b = sketch.getPoint(g, 1), sketch.getPoint(g, 2)
    return math.atan2(b.y - a.y, b.x - a.x)


def _is_line(sketch, g):
    if g in (dimtools.H_AXIS, dimtools.V_AXIS):
        return True
    return g >= 0 and dimtools._kind(sketch.Geometry[g]) == "line"


def _degrees(rad):
    return ("%.2f" % math.degrees(rad)).rstrip("0").rstrip(".") + "\u00b0"


class PickDimensionPage(sketchtoolpm.ToolPage):
    """A page that takes a first pick (the reference) and then dimensions each further pick."""

    FIRST = "the reference"
    NEXT = "Select the entities to dimension. The check mark or Esc ends the tool."

    def build(self):
        self.base = None
        self.made = []
        g = self.group("Message")
        self.message = QtWidgets.QLabel(g.body)
        self.message.setWordWrap(True)
        g.content.addWidget(self.message)
        g = self.group("Dimensions")
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWSelectedEntities")
        self.list.setFixedHeight(90)
        g.content.addWidget(self.list)
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        self._prompt()
        for sub in relationspm.picked_subs(self.sketch)[:1]:
            QtCore.QTimer.singleShot(0, lambda s=sub: self.picked(s))

    def _prompt(self):
        self.message.setText(("Select %s." % self.FIRST) if self.base is None else self.NEXT)

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("dimcommands.py:705", _fw_err)
        if item is None:
            return
        if self.base is None:
            if self.take_base(item):
                self.show_note("")
            self._prompt()
            return
        self.begin()
        text = self.dimension(item)
        sketchtoolpm._refresh(self.sketch)
        if text:
            self.list.addItem(text)
        self._prompt()

    def report(self, made, text):
        """List text for what dimension() made, and the note about driven ones."""
        if made is None:
            return None
        index, driven = made
        self.made.append(index)
        self.show_note("Driven: a driving dimension would over-define the sketch." if driven else "")
        return text + (" (driven)" if driven else "")

    def take_base(self, item):
        return False

    def dimension(self, item):
        return None

    def selection_changed(self):
        pass

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("dimcommands.py:742", _fw_err)
        self.observer.page = None


class AngularRunningPage(PickDimensionPage):
    ""


    TITLE = "Angular Running Dimension"
    ICON = "DIMENSIONS_ANGULAR_RUNNING"
    PIXMAP = "Constraint_InternalAngle"
    FIRST = "the line that is 0 degrees"
    NEXT = "Select the lines to dimension; each angle runs from the first line."

    def take_base(self, item):
        if item.pos != relationspm.NONE or not _is_line(self.sketch, item.geo):
            self.show_note("Angular Running Dimension starts from a line.", True)
            return False
        self.base = item.geo
        return True

    def dimension(self, item):
        if item.pos != relationspm.NONE or not _is_line(self.sketch, item.geo) or item.geo == self.base:
            self.show_note("Select a line.", True)
            return None
        angle = (_line_angle(self.sketch, item.geo) - _line_angle(self.sketch, self.base)) % (2 * math.pi)
        if angle < 1e-9:
            self.show_note("That line runs at 0 degrees: nothing to dimension.", True)
            return None
        made = add_kept(self.sketch, dimtools._constraint("Angle", self.base, item.geo, angle))
        if made is not None:
            try:
                self.sketch.setLabelDistance(made[0], 8.0 + 3.0 * len(self.made))
            except Exception as _fw_err:
                _fw_log("dimcommands.py:776", _fw_err)
        return self.report(made, _degrees(angle))


def _mirror(point, a, b):
    d = b - a
    t = (point - a).dot(d) / d.dot(d)
    foot = a + d * t
    return foot * 2 - point


class SymmetricDiameterPage(PickDimensionPage):
    ""



    TITLE = "Symmetric Linear Diameter Dimension"
    ICON = "DIMENSIONS_SYMMETRIC_DIAMETER"
    PIXMAP = "Constraint_Symmetric"
    FIRST = "the centerline (a line or an axis)"
    NEXT = "Select the points, lines or circles to dimension across the centerline."

    def take_base(self, item):
        if item.pos != relationspm.NONE or not _is_line(self.sketch, item.geo):
            self.show_note("Symmetric Linear Diameter starts from a centerline.", True)
            return False
        self.base = item.geo
        return True

    def _axis_points(self):
        if self.base == dimtools.H_AXIS:
            return App.Vector(0, 0, 0), App.Vector(1, 0, 0)
        if self.base == dimtools.V_AXIS:
            return App.Vector(0, 0, 0), App.Vector(0, 1, 0)
        return self.sketch.getPoint(self.base, 1), self.sketch.getPoint(self.base, 2)

    def dimension(self, item):
        point = _target_point(self.sketch, item)
        if point is None or point[0] == self.base or point == dimtools.ORIGIN:
            self.show_note("Select a point, line or circle beside the centerline.", True)
            return None
        import Part
        a, b = self._axis_points()
        p = self.sketch.getPoint(*point)
        m = _mirror(p, a, b)
        width = (m - p).Length
        if width < dimtools.LENGTH_TOL:
            self.show_note("That point is on the centerline.", True)
            return None
        mirror = self.sketch.addGeometry(Part.Point(m), True)
        self.sketch.addConstraint(dimtools._constraint("Symmetric", point[0], point[1], mirror, 1, self.base))
        made = add_kept(self.sketch, dimtools._constraint("Distance", point[0], point[1], mirror, 1, width))
        return self.report(made, "\u00d8" + _mm(width))


class ChamferDimensionPage(PickDimensionPage):
    ""



    TITLE = "Chamfer Dimension"
    ICON = "DIMENSIONS_CHAMFER"
    PIXMAP = "Sketcher_CreateChamfer"
    FIRST = "the chamfer line"
    NEXT = "Select the line next to the chamfer."

    def take_base(self, item):
        if item.pos != relationspm.NONE or item.geo < 0 or not _is_line(self.sketch, item.geo):
            self.show_note("Select the chamfer: a sketch line.", True)
            return False
        self.base = item.geo
        return True

    def _shared(self, a, b):
        sk = self.sketch
        for i in (1, 2):
            for j in (1, 2):
                if (sk.getPoint(a, i) - sk.getPoint(b, j)).Length < 1e-6:
                    return i, j
        return None

    def _line_at(self, point, skip):
        """A sketch line other than skip with an end at point."""
        sk = self.sketch
        for g, geo in enumerate(sk.Geometry):
            if g in skip or dimtools._kind(geo) != "line":
                continue
            for j in (1, 2):
                if (sk.getPoint(g, j) - point).Length < 1e-6:
                    return g
        return None

    def dimension(self, item):
        sk = self.sketch
        chamfer, other = self.base, item.geo
        if item.pos != relationspm.NONE or other < 0 or not _is_line(sk, other) or other == chamfer:
            self.show_note("Select the sketch line next to the chamfer.", True)
            return None
        shared = self._shared(chamfer, other)
        if shared is None:
            self.show_note("That line does not meet the chamfer.", True)
            return None
        i, j = shared

        u = sk.getPoint(chamfer, 3 - i) - sk.getPoint(chamfer, i)       # along the chamfer, away from the line
        v = sk.getPoint(other, 3 - j) - sk.getPoint(other, j)           # along the line, away from the chamfer
        acute = math.pi - math.acos(max(-1.0, min(1.0, u.dot(v) / (u.Length * v.Length))))
        # FreeCAD's angle from the picked line's direction to the chamfer's (the drawn one: nothing moves)
        value = (_line_angle(sk, chamfer) - _line_angle(sk, other)) % (2 * math.pi)
        far = self._line_at(sk.getPoint(chamfer, 3 - i), (chamfer, other))
        if far is not None and abs(dimtools._angle_between(v, sk.getPoint(far, 2) - sk.getPoint(far, 1))
                                   - math.pi / 2) < dimtools.ANGLE_TOL:
            leg = u.Length * math.cos(acute)
            first = add_kept(sk, dimtools._constraint("Distance", chamfer, i, far, leg))
        else:
            leg = u.Length
            first = add_kept(sk, dimtools._constraint("Distance", chamfer, leg))
        second = add_kept(sk, dimtools._constraint("Angle", other, chamfer, value))
        self.base = None        # the next chamfer starts over
        driven = any(m is not None and m[1] for m in (first, second))
        for m in (first, second):
            if m is not None:
                self.made.append(m[0])
        self.show_note("Driven: a driving dimension would over-define the sketch." if driven else "")
        return "%s x %s%s" % (_mm(leg), _degrees(acute), " (driven)" if driven else "")


# --------------------------------------------------------------------------- Dynamic Mirror
def mirror_entities(sketch, geos, axis):
    """Mirrored copies of geos about the line axis, tied to the originals with Symmetric (and Equal
    for circles) so they stay mirrored. The copies' ids."""
    if not geos:
        return []
    from .fwsketch import helpers as _helpers
    geos = _helpers.with_helpers(sketch, geos)       # an arc slot's centre line comes along (reviewer 11-19)
    first_geo = sketch.GeometryCount
    first_con = sketch.ConstraintCount
    # fix271: a spline's own points and control polygon come along and are mirrored too, so the copy
    # follows when the original is reshaped (only its ends were tied: a bare copy kept its old shape)
    asked = list(geos)
    inner = []
    for c in sketch.Constraints:
        if c.Type == "InternalAlignment" and c.Second in asked and c.First not in asked and c.First not in inner:
            inner.append(c.First)
    geos = asked + inner
    made = sketch.addSymmetric(list(geos), axis, 0)
    # FreeCAD copies the hidden relations too: a block's hold left the copy rigid with nothing to
    # show or remove it (reviewer 11-19); a helper's are kept and hidden again below
    try:
        stray = [i for i in range(first_con, sketch.ConstraintCount) if sketch.getVirtualSpace(i)
                 and not _helpers.refers_to_helper(sketch, sketch.Constraints[i])]
        if stray:
            sketch.delConstraints(stray)
    except Exception as _fw_err:
        _fw_log("dimcommands.py:mirror hidden", _fw_err)
    copies = list(made) if isinstance(made, (tuple, list)) else list(range(len(sketch.Geometry) - len(geos),
                                                                           len(sketch.Geometry)))
    a, b = _axis_ends(sketch, axis)
    owners = set(c.Second for c in sketch.Constraints if c.Type == "InternalAlignment" and c.First in inner)
    for g, c in zip(geos, copies):
        if g in owners:
            continue  # fix271: its control polygon is held below, so its ends need nothing more
        if g in inner:
            if type(sketch.Geometry[g]).__name__ != "Circle":
                continue  # a knot point follows its spline
            dimtools.attempt(sketch, dimtools._constraint("Symmetric", g, 3, c, 3, axis))
            dimtools.attempt(sketch, dimtools._constraint("Equal", g, c))  # same weight
            continue
        kind = dimtools._kind(sketch.Geometry[g])
        positions = dimtools._positions(kind)
        # an arc: both ends first, then Equal holds the radius; centre-first left one end of the
        # copy free (tester SK9-10: only the centre and one pair of ends were Symmetric)
        order = (1, 2, 3) if kind in ("arc", "conic_arc") else positions
        for pos in order:
            target = _mirror(sketch.getPoint(g, pos), a, b)
            match = min(positions, key=lambda q: (sketch.getPoint(c, q) - target).Length)
            if (sketch.getPoint(g, pos) - target).Length < 1e-7:

                # (a Symmetric of two points in one place held nothing: the copy stayed Under Defined)
                if dimtools.attempt(sketch, dimtools._constraint("Coincident", g, pos, c, match)) is None:
                    dimtools.attempt(sketch, dimtools._constraint("PointOnObject", c, match, axis))
                continue
            dimtools.attempt(sketch, dimtools._constraint("Symmetric", g, pos, c, match, axis))
        if kind in ("circle", "arc"):
            dimtools.attempt(sketch, dimtools._constraint("Equal", g, c))
    _helpers.hide_new(sketch, first_geo)
    return copies[:len(asked)]


def _axis_ends(sketch, axis):
    if axis == dimtools.H_AXIS:
        return App.Vector(0, 0, 0), App.Vector(1, 0, 0)
    if axis == dimtools.V_AXIS:
        return App.Vector(0, 0, 0), App.Vector(0, 1, 0)
    return sketch.getPoint(axis, 1), sketch.getPoint(axis, 2)


def _on_axis(sketch, g, a, b):
    """True when the geometry lies on the mirror line (its copy would be itself)."""
    kind = dimtools._kind(sketch.Geometry[g])
    pts = [sketch.getPoint(g, p) for p in dimtools._positions(kind)]
    return bool(pts) and kind in ("line", "point") and all((_mirror(p, a, b) - p).Length < 1e-6 for p in pts)


class DynamicMirror(QtCore.QObject):
    ""





    def __init__(self):
        super().__init__()
        self.sketch = None
        self.axis = None
        self.count = 0
        self.made = set()           # fix268: the copies made since start (a chain's copies are joined)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.tick)

    def active(self):
        return self.sketch is not None

    def start(self, sketch, axis):
        self.sketch, self.axis = sketch, axis
        self.count = len(sketch.Geometry)
        self.made = set()
        self.timer.start()
        _status("Dynamic Mirror Entities is on: what you sketch is mirrored about the picked line. "
                "Click Dynamic Mirror again to stop.")

    def stop(self, quiet=False):
        self.timer.stop()
        self.sketch = self.axis = None
        if not quiet:
            _status("Dynamic Mirror Entities is off.")

    def tick(self):
        sketch = self.sketch
        try:
            alive_sketch = sketch is not None and sketch.isValid() if hasattr(sketch, "isValid") else sketch is not None
        except Exception:
            alive_sketch = False
        if not alive_sketch or contextbar.sketch_in_edit() is not sketch:
            self.stop()
            return
        n = len(sketch.Geometry)
        if n < self.count:
            self.count = n          # something was deleted: count from here
            return
        if n == self.count:
            return
        shell = sketchtoolpm._shell()
        if shell is not None and contextbar.tool_running(shell) and not _placed_as_drawn():
            return                  # the tool still works on its newest entity
        if self.axis >= n:
            self.stop()
            return
        a, b = _axis_ends(sketch, self.axis)
        new = [g for g in range(self.count, n) if g != self.axis and not _on_axis(sketch, g, a, b)]
        doc = sketch.Document
        doc.openTransaction("Dynamic Mirror Entities")
        try:
            copies = mirror_entities(sketch, new, self.axis)
            _join_copies(sketch, copies, self.made)
            self.made.update(copies)
            doc.commitTransaction()
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintWarning("FreeCAD: Dynamic Mirror: %s\n" % error)
        sketchtoolpm._refresh(sketch)
        self.count = len(sketch.Geometry)


def _join_copies(sketch, copies, made):
    ""


    for c in copies:
        if dimtools._kind(sketch.Geometry[c]) not in ("line", "arc"):
            continue
        for pos in (1, 2):
            p = sketch.getPoint(c, pos)
            other = None
            for o in sorted(made):
                if o >= len(sketch.Geometry) or dimtools._kind(sketch.Geometry[o]) not in ("line", "arc"):
                    continue
                for q in (1, 2):
                    if (sketch.getPoint(o, q) - p).Length < 1e-6:
                        other = (o, q)
                        break
                if other:
                    break
            if other is None:
                continue
            sym = [i for i, k in enumerate(sketch.Constraints) if k.Type == "Symmetric" and
                   ((k.First == c and k.FirstPos == pos) or (k.Second == c and k.SecondPos == pos))]
            try:
                if sym:
                    sketch.delConstraint(sym[-1])
                sketch.addConstraint(dimtools._constraint("Coincident", other[0], other[1], c, pos))
            except Exception as _fw_err:
                _fw_log("dimcommands.py: join copies", _fw_err)
    try:
        sketch.solve()
    except Exception as _fw_err:
        _fw_log("dimcommands.py: join solve", _fw_err)


def _placed_as_drawn():
    ""


    try:
        from .fwsketch import tool as fwtool
        t = fwtool.active()
        return t is not None and any(k.__name__ == "LineTool" for k in type(t).__mro__)
    except Exception as _fw_err:
        _fw_log("dimcommands.py: placed as drawn", _fw_err)
        return False


_dynamic_mirror = None


def dynamic_mirror():
    global _dynamic_mirror
    if _dynamic_mirror is None:
        _dynamic_mirror = DynamicMirror()
    return _dynamic_mirror


class DynamicMirrorPage(PickDimensionPage):
    """Asks for the mirror line when Dynamic Mirror starts with nothing picked."""

    TITLE = "Mirror"
    ICON = "SKETCH_DYNAMIC_MIRROR"
    PIXMAP = "Sketcher_Symmetry"
    FIRST = "a centerline or line to mirror about"

    def build(self):
        super().build()
        self.list.parentWidget().parentWidget().hide()      # no Dimensions group here

    def take_base(self, item):
        if item.pos != relationspm.NONE or not _is_line(self.sketch, item.geo):
            self.show_note("Select a centerline or line.", True)
            return False
        sketch, axis = self.sketch, item.geo
        QtCore.QTimer.singleShot(0, lambda: (self.accept(), dynamic_mirror().start(sketch, axis)))
        return True


# --------------------------------------------------------------------------- Instant2D
INSTANT2D = "Instant2D"
LINEAR = ("Distance", "DistanceX", "DistanceY")
RADIAL = ("Radius", "Diameter")


def instant2d_on():
    return _params().GetBool(INSTANT2D, False)


def _nice_step(size):
    """The ruler step for a pointer move of size mm: 1, 2 or 5 times a power of ten."""
    if size <= 0:
        return 1.0
    power = 10 ** math.floor(math.log10(size))
    for m in (1, 2, 5, 10):
        if size <= m * power:
            return m * power
    return 10 * power


class Instant2D(QtCore.QObject):
    ""




    def __init__(self):
        super().__init__()
        self.widgets = []
        self.drag = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.attach)

    def start(self):
        self.timer.start()
        self.attach()

    def attach(self):
        """Watch the 3D view while a sketch is edited and Instant2D is on."""
        want = []
        if instant2d_on() and contextbar.sketch_in_edit() is not None:
            shell = sketchtoolpm._shell()
            view = shell.view_widget() if shell is not None else None
            if view is not None and sketchtoolpm.alive(view):
                want = [view.viewport()] if hasattr(view, "viewport") and view.viewport() is not None else [view]
        if want == self.widgets:
            return
        for w in self.widgets:
            if sketchtoolpm.alive(w):
                w.removeEventFilter(self)
        self.widgets = want
        for w in want:
            w.installEventFilter(self)

    # ------------------------------------------------------------------ geometry
    def _view(self):
        try:
            return Gui.ActiveDocument.ActiveView
        except Exception:
            return None

    def _sketch_point(self, widget, pos):
        """The pointer in the sketch's own coordinates."""
        view = self._view()
        ratio = widget.devicePixelRatioF() if hasattr(widget, "devicePixelRatioF") else 1.0
        x, y = pos.x() * ratio, (widget.height() - pos.y()) * ratio
        p = view.getPoint(int(round(x)), int(round(y)))
        local = self.sketch.getGlobalPlacement().inverse().multVec(p)
        return App.Vector(local.x, local.y, 0)

    def _pixel_size(self, widget, pos):
        a = self._sketch_point(widget, pos)
        b = self._sketch_point(widget, QtCore.QPoint(pos.x() + 1, pos.y()))
        return max((b - a).Length, 1e-9)

    def _hovered(self):
        """(index, constraint) of the driving dimension under the pointer, else None."""
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return None
        try:
            pre = Gui.Selection.getPreselection()
            full = list(getattr(pre, "SubElementNames", ()))
            subs = [sub.split(".")[-1] for sub in full]
            obj = pre.Object
        except Exception:
            return None
        if obj is None:
            return None
        if obj.Name != sketch.Name:
            # a sketch in a Body (or Part) is preselected through its container: Body + "Sketch.Constraint3"
            subs = [sub.split(".")[-1] for sub in full if len(sub.split(".")) > 1 and sub.split(".")[-2] == sketch.Name]
            if not subs:
                return None
        for sub in subs:
            if sub.startswith("Constraint"):
                try:
                    index = int(sub[len("Constraint"):]) - 1
                    c = sketch.Constraints[index]
                except (ValueError, IndexError):
                    return None
                if c.Driving and c.Type in LINEAR + RADIAL:
                    return sketch, index, c
        return None

    def _direction(self, c):
        """Unit vector along which the value grows, or None for radial ones (they follow the distance)."""
        sk = self.sketch
        if c.Type == "DistanceX":          # signed: the second point's x minus the first's
            return App.Vector(1, 0, 0)
        if c.Type == "DistanceY":
            return App.Vector(0, 1, 0)
        if c.Type == "Distance":
            if c.Second == -2000 and c.FirstPos == 0:                 # a line's length
                d = sk.getPoint(c.First, 2) - sk.getPoint(c.First, 1)
            elif c.Second == -2000:
                return None
            elif c.SecondPos == 0:                                    # point to line: across the line
                a, b = sk.getPoint(c.Second, 1), sk.getPoint(c.Second, 2)
                p = sk.getPoint(c.First, c.FirstPos)
                t = b - a
                foot = a + t * ((p - a).dot(t) / t.dot(t))
                d = p - foot
            else:
                d = sk.getPoint(c.Second, c.SecondPos) - sk.getPoint(c.First, c.FirstPos)
            return d * (1.0 / d.Length) if d.Length > 0 else None
        return None

    def _handles(self, c):
        ""

        sk = self.sketch
        V = App.Vector
        if c.Type in RADIAL:
            ctr = sk.getPoint(c.First, 3)
            g = sk.Geometry[c.First]
            r = getattr(g, "Radius", None)
            if r is None:
                return []
            a = float(getattr(c, "LabelPosition", 0.0))
            u = V(math.cos(a), math.sin(a), 0)
            return [ctr + u * r] + ([ctr - u * r] if c.Type == "Diameter" else [])
        if c.Type not in ("Distance", "DistanceX", "DistanceY"):
            return []
        if c.Second == -2000:
            if c.FirstPos != 0:
                return []
            p1, p2 = sk.getPoint(c.First, 1), sk.getPoint(c.First, 2)
        elif c.SecondPos == 0 and c.Type == "Distance":
            a, b = sk.getPoint(c.Second, 1), sk.getPoint(c.Second, 2)
            p1 = sk.getPoint(c.First, c.FirstPos)
            t = b - a
            p2 = a + t * ((p1 - a).dot(t) / t.dot(t))
        else:
            p1, p2 = sk.getPoint(c.First, c.FirstPos), sk.getPoint(c.Second, c.SecondPos)
        if c.Type == "DistanceX":
            p2 = V(p2.x, p1.y, 0)
        elif c.Type == "DistanceY":
            p2 = V(p1.x, p2.y, 0)
        d = p2 - p1
        if d.Length < 1e-12:
            return []
        d = d * (1.0 / d.Length)
        n = V(-d.y, d.x, 0) * float(getattr(c, "LabelDistance", 0.0))
        return [p1 + n, p2 + n]

    def _on_handle(self, widget, pos, c):
        try:
            tips = self._handles(c)
        except Exception as _fw_err:
            _fw_log("dimcommands.py:handles", _fw_err)
            return False
        if not tips:
            return False
        here = self._sketch_point(widget, pos)
        reach = 8.0 * self._pixel_size(widget, pos)
        return any(math.hypot(here.x - q.x, here.y - q.y) <= reach for q in tips)

    # ------------------------------------------------------------------ events
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter1142(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter dimcommands.py: %s\n" % exc)
            return False

    def _fw_filter1142(self, obj, event):
        t = event.type()
        try:
            if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton and self.drag is None:
                return self._press(obj, event)
            if t == QtCore.QEvent.MouseMove and self.drag is not None:
                self._move(obj, event)
                return True
            if t == QtCore.QEvent.MouseButtonRelease and self.drag is not None and event.button() == Qt.LeftButton:
                self._release()
                return True
            if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) and self.drag is not None \
                    and event.key() == Qt.Key_Escape:
                if t == QtCore.QEvent.KeyPress:
                    self._cancel()
                event.accept()
                return True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Instant2D: %s\n" % error)
            self.drag = None
        return False

    def _press(self, widget, event):
        shell = sketchtoolpm._shell()
        if shell is not None and contextbar.tool_running(shell):
            return False
        found = self._hovered()
        if found is None:
            return False
        self.sketch, index, c = found
        pos = event.pos()
        if not self._on_handle(widget, pos, c):
            return False
        self.drag = {"index": index, "start": c.Value, "type": c.Type, "press": pos, "moved": False,
                     "from": self._sketch_point(widget, pos), "dir": self._direction(c), "last": c.Value,
                     "pixel": self._pixel_size(widget, pos), "widget": widget}
        return True

    def _move(self, widget, event):
        d = self.drag
        if not d["moved"]:
            if (event.pos() - d["press"]).manhattanLength() < QtWidgets.QApplication.startDragDistance():
                return
            d["moved"] = True
            self.sketch.Document.openTransaction("Instant2D")
        here = self._sketch_point(widget, event.pos())
        c = self.sketch.Constraints[d["index"]]
        if d["type"] in RADIAL:
            centre = self.sketch.getPoint(c.First, 3)
            grab = (d["from"] - centre).Length
            value = d["start"] + ((here - centre).Length - grab) * (2 if d["type"] == "Diameter" else 1)
        elif d["dir"] is not None:
            value = d["start"] + (here - d["from"]).dot(d["dir"])
        else:
            return
        if not (event.modifiers() & Qt.ControlModifier):
            step = _nice_step(d["pixel"] * 8)
            value = round(value / step) * step
        if d["type"] not in ("DistanceX", "DistanceY") and value <= 0:
            return
        if abs(value - d["last"]) < 1e-12:
            return
        try:
            self.sketch.setDatum(d["index"], App.Units.Quantity("%.9g mm" % value))
            if self.sketch.solve() != 0:
                raise ValueError("no solution")
            d["last"] = value
        except Exception:
            try:
                self.sketch.setDatum(d["index"], App.Units.Quantity("%.9g mm" % d["last"]))
                self.sketch.solve()
            except Exception as _fw_err:
                _fw_log("dimcommands.py:1252", _fw_err)
            return
        _status("%s" % _mm(abs(value)))

    def _release(self):
        d, self.drag = self.drag, None
        if not d["moved"]:
            # a plain click: select the dimension, as without Instant2D
            try:
                Gui.Selection.addSelection(self.sketch.Document.Name, self.sketch.Name,
                                           "Constraint%d" % (d["index"] + 1))
            except Exception as _fw_err:
                _fw_log("dimcommands.py:1264", _fw_err)
            return
        self.sketch.Document.commitTransaction()
        sketchtoolpm._refresh(self.sketch)

    def _cancel(self):
        d, self.drag = self.drag, None
        if d["moved"]:
            self.sketch.Document.abortTransaction()
            sketchtoolpm._refresh(self.sketch)
        _status("Instant2D: dimension put back.")


_instant2d = None


def instant2d():
    global _instant2d
    if _instant2d is None:
        _instant2d = Instant2D()
        _instant2d.start()
    return _instant2d


# --------------------------------------------------------------------------- commands
class _SketchCommand:
    MENU = ""
    TIP = ""
    PIXMAP = "Constraint_Lock"

    def GetResources(self):
        return {"Pixmap": self.PIXMAP, "MenuText": self.MENU, "ToolTip": self.TIP, "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None


class FullyDefineSketchCommand(_SketchCommand):
    MENU = "Fully Define Sketch"
    TIP = "Fully defines a sketch: adds the fitting relations, then dimensions, until nothing is free"

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(FullyDefinePage(sketch))


class AutoInsertDimensionCommand(_SketchCommand):
    MENU = "Auto Insert Dimension"
    TIP = "Dimensions the sketch (or the picked entities) until it is fully defined; adds no relations"
    PIXMAP = "Constraint_Length"

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return
        p = _params()
        picked = _picked_geometry(sketch)
        doc = sketch.Document
        doc.openTransaction("Auto Insert Dimension")
        try:
            result = dimtools.fully_define(
                sketch, relations=(), dimensions=True, entities=picked or None,
                h_scheme=p.GetString("HorizontalScheme", "Baseline"), v_scheme=p.GetString("VerticalScheme", "Baseline"),
                h_side=p.GetInt("HorizontalSide", 1), v_side=p.GetInt("VerticalSide", 1))
        except Exception as error:
            doc.abortTransaction()
            _status("Auto Insert Dimension: %s" % error)
            return
        doc.commitTransaction()
        sketchtoolpm._refresh(sketch)
        _status(dimtools.describe(result))


class ScanEqualCommand(_SketchCommand):
    MENU = "Scan Equal"
    TIP = "Finds lines of equal length and arcs or circles of equal radius, and sets them equal"
    PIXMAP = "Constraint_EqualLength"

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(ScanEqualPage(sketch))


def _page_command(page_class, menu, tip, pixmap):
    class Command(_SketchCommand):
        MENU, TIP, PIXMAP = menu, tip, pixmap

        def Activated(self):
            sketch = contextbar.sketch_in_edit()
            if sketch is not None:
                sketchtoolpm.open_page(page_class(sketch))
    return Command


class DynamicMirrorCommand(_SketchCommand):
    MENU = "Dynamic Mirror Entities"
    TIP = "Mirrors what you sketch about a picked line as you go; click again to stop"
    PIXMAP = "Sketcher_Symmetry"

    def Activated(self):
        mirror = dynamic_mirror()
        if mirror.active():
            mirror.stop()
            return
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return
        lines = [i for i in relationspm.items_of(sketch, relationspm.picked_subs(sketch))
                 if i.pos == relationspm.NONE and _is_line(sketch, i.geo)]
        if lines:
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("dimcommands.py:1379", _fw_err)
            mirror.start(sketch, lines[0].geo)
        else:
            sketchtoolpm.open_page(DynamicMirrorPage(sketch))


class Instant2DCommand(_SketchCommand):
    MENU = "Instant2D"
    TIP = "Drag a dimension in the sketch to change its value"
    PIXMAP = "Constraint_Length"

    def GetResources(self):
        res = super().GetResources()
        res["Checkable"] = instant2d_on()
        try:
            from . import simicons      # its own drawing, not the Length constraint's
            res["Pixmap"] = simicons.svg("Instant2D") or res.get("Pixmap")
        except Exception as _fw_err:
            _fw_log("dimcommands.py:pixmap", _fw_err)
        return res

    def IsActive(self):
        # the button's pressed look follows the setting (the action toggles itself when clicked)
        on = instant2d_on()
        try:
            actions = Gui.Command.get("SWStyle_Instant2D").getAction()
        except Exception:
            actions = []
        for action in actions:
            if action.isChecked() != on:
                blocked = action.blockSignals(True)
                action.setChecked(on)
                action.blockSignals(blocked)
        return App.ActiveDocument is not None

    def Activated(self, checked=0):
        try:
            has_action = bool(Gui.Command.get("SWStyle_Instant2D").getAction())
        except Exception:
            has_action = False
        # a toolbar or menu action toggles itself and says its new state; without one
        # (Gui.runCommand), each run switches it over
        on = bool(checked) if has_action else not instant2d_on()
        _params().SetBool(INSTANT2D, on)
        instant2d().attach()
        _status("Instant2D is %s: %s" % ("on" if on else "off",
                "drag a dimension to change its value." if on else "dragging a dimension moves its text."))


COMMANDS = {
    "SWStyle_FullyDefineSketch": FullyDefineSketchCommand,
    "SWStyle_AutoInsertDimension": AutoInsertDimensionCommand,
    "SWStyle_ScanEqual": ScanEqualCommand,
    "SWStyle_BaselineDimension": _page_command(
        BaselinePage, "Baseline Dimension", "Dimensions several entities from one baseline",
        "Constraint_HorizontalDistance"),
    "SWStyle_ChainDimension": _page_command(
        ChainPage, "Chain Dimension", "Dimensions entities end to end, each from the one before",
        "Constraint_HorizontalDistance"),
    "SWStyle_OrdinateDimension": _page_command(
        OrdinatePage, "Ordinate Dimension", "Dimensions entities from a zero point",
        "Constraint_HorizontalDistance"),
    "SWStyle_HorizontalOrdinateDimension": _page_command(
        HorizontalOrdinatePage, "Horizontal Ordinate Dimension",
        "Horizontal dimensions of entities from a zero point", "Constraint_HorizontalDistance"),
    "SWStyle_AngularRunningDimension": _page_command(
        AngularRunningPage, "Angular Running Dimension", "Angles of several lines, running from one line at 0 degrees",
        "Constraint_InternalAngle"),
    "SWStyle_SymmetricLinearDiameterDimension": _page_command(
        SymmetricDiameterPage, "Symmetric Linear Diameter Dimension",
        "Full width of entities across a centerline, as on a revolve profile", "Constraint_Symmetric"),
    "SWStyle_ChamferDimension": _page_command(
        ChamferDimensionPage, "Chamfer Dimension", "Length and angle of a sketch chamfer", "Sketcher_CreateChamfer"),
    "SWStyle_DynamicMirror": DynamicMirrorCommand,
    "SWStyle_Instant2D": Instant2DCommand,
    "SWStyle_VerticalOrdinateDimension": _page_command(
        VerticalOrdinatePage, "Vertical Ordinate Dimension",
        "Vertical dimensions of entities from a zero point", "Constraint_VerticalDistance"),
}


def register():
    try:
        have = set(Gui.listCommands())
    except Exception:
        have = set()
    for name, cls in COMMANDS.items():
        if name in have:
            continue
        try:
            Gui.addCommand(name, cls())
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (name, error))
    try:
        from . import sketchxpert, polygonpm, sketchview, derivedsketch, sketchfillet, sketchpattern, sketchmove
        derivedsketch.register()
        sketchfillet.register()
        sketchpattern.register()
        sketchmove.register()
        sketchxpert.register()
        polygonpm.register()
        sketchview.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: SketchXpert, Edit Polygon, sketch view toggles: %s\n" % error)
    try:
        instant2d()     # watches the sketch view whenever Instant2D is on
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Instant2D: %s\n" % error)


register()
