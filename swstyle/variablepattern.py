# SPDX-License-Identifier: LGPL-2.1-or-later
""














import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtGui, QtWidgets

from . import naming
from . import simplefeature as sf
from .simplefeature import Field
from . import geomkeep

V = App.Vector
COMMAND = "SWStyle_VariablePattern"
DIMENSIONS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
EXTRUDES = ("PartDesign::Pad", "PartDesign::Pocket")
SCRATCH = "FreeWorksVariablePattern"


# --------------------------------------------------------------------------- the table
def parse(text):
    """(columns, rows); a row is a list of floats or None (blank, '-' or '*' = the seed's value)."""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return [], []
    columns = lines[0].split()
    rows = []
    for line in lines[1:]:
        cells = line.replace(",", " ").split()
        row = []
        for i in range(len(columns)):
            cell = cells[i] if i < len(cells) else ""
            try:
                row.append(float(cell))
            except ValueError:
                row.append(None)
        rows.append(row)
    return columns, rows


def write(columns, rows):
    def cell(value):
        return "*" if value is None else ("%.6g" % value)
    return "\n".join([" ".join(columns)] + [" ".join(cell(v) for v in row) for row in rows])


# --------------------------------------------------------------------------- dimensions
def _sketch(feature):
    profile = getattr(feature, "Profile", None)
    sketch = profile[0] if isinstance(profile, (list, tuple)) and profile else profile
    return sketch if sketch is not None and sketch.TypeId == "Sketcher::SketchObject" else None


def _constraint_key(sketch, index):
    c = sketch.Constraints[index]
    return c.Name if c.Name else "c%d" % (index + 1)


def _constraint_index(sketch, key):
    for i, c in enumerate(sketch.Constraints):
        if c.Name and c.Name == key:
            return i
    if key.startswith("c") and key[1:].isdigit():
        index = int(key[1:]) - 1
        if 0 <= index < len(sketch.Constraints):
            return index
    return None


def _side(feature):
    side = getattr(feature, "SideType", None)
    if side is None:          # FreeCAD before 1.1
        side = "Symmetric" if getattr(feature, "Midplane", False) else (
            "Two sides" if getattr(feature, "Type", "") == "TwoLengths" else "One side")
    return side


def _feature_params(feature):
    out = []
    if getattr(feature, "Type", "") == "Length":
        out.append(("Length", "Depth"))
    if _side(feature) == "Two sides" and getattr(feature, "Type2", "Length") == "Length":
        out.append(("Length2", "Depth2"))
    return out


def dimensions(features):
    """[(key, label, seed value, unit)] for the seeds' sketch dimensions and depths, in tree order."""
    out = []
    for feature in features:
        if feature.TypeId not in EXTRUDES:
            continue
        sketch = _sketch(feature)
        if sketch is not None:
            for i, c in enumerate(sketch.Constraints):
                if c.Type in DIMENSIONS and c.Driving:
                    name = c.Name or "D%d" % (i + 1)
                    if c.Type == "Angle":
                        value, unit = math.degrees(c.Value), "deg"
                    else:
                        value, unit = c.Value, "mm"
                    out.append(("%s:%s" % (sketch.Name, _constraint_key(sketch, i)),
                                "%s@%s" % (name, sketch.Label), value, unit))
        for param, label in _feature_params(feature):
            out.append(("%s:%s" % (feature.Name, param), "%s@%s" % (label, feature.Label),
                        float(getattr(feature, param).Value), "mm"))
    return out


def seed_values(features, columns):
    known = dict((key, value) for key, _, value, _ in dimensions(features))
    return [known.get(key) for key in columns]


# --------------------------------------------------------------------------- rebuilding a seed
def _scratch():
    doc = App.listDocuments().get(SCRATCH)
    if doc is None:
        active = App.ActiveDocument
        doc = App.newDocument(SCRATCH, hidden=True, temp=True)
        if active is not None:
            App.setActiveDocument(active.Name)
    return doc


def close_scratch():
    if SCRATCH in App.listDocuments():
        App.closeDocument(SCRATCH)


def _copy_sketch(sketch):
    """The sketch's geometry and constraints in a scratch sketch with no links: external
    geometry becomes blocked construction geometry where it is now."""
    doc = _scratch()
    copy = doc.addObject("Sketcher::SketchObject", "Copy")
    geometry = list(geomkeep.read(sketch))
    count = len(geometry)
    external = list(getattr(sketch, "ExternalGeo", []))[2:]     # 0, 1 are the H and V axes
    mapped = {}
    for k, geo in enumerate(external):
        mapped[-(k + 3)] = count + k
        geometry.append(geo)
    copy.Geometry = geometry
    for index in range(count, len(geometry)):
        copy.setConstruction(index, True)
    constraints = []
    for c in sketch.Constraints:
        for attr in ("First", "Second", "Third"):
            if getattr(c, attr) in mapped:
                setattr(c, attr, mapped[getattr(c, attr)])
        constraints.append(c)
    copy.Constraints = constraints
    import Sketcher
    for index in range(count, len(geometry)):
        copy.addConstraint(Sketcher.Constraint("Block", index))
    return copy


def _profile(sketch, values):
    """The sketch's wires (global coordinates) with the dimensions in values ({key: number}) set."""
    if not values:
        return [w.copy() for w in sketch.Shape.Wires]
    copy = _copy_sketch(sketch)
    try:
        for key, value in values.items():
            index = _constraint_index(sketch, key)
            if index is None:
                raise RuntimeError("%s has no dimension %s" % (sketch.Label, key))
            c = sketch.Constraints[index]
            quantity = App.Units.Quantity("%r deg" % value) if c.Type == "Angle" else App.Units.Quantity("%r mm" % value)
            copy.setDatum(index, quantity)
        if copy.solve() != 0:
            raise RuntimeError("%s cannot be solved with these values" % sketch.Label)
        copy.recompute()
        wires = [w.copy() for w in copy.Shape.Wires]
    finally:
        copy.Document.removeObject(copy.Name)
    placement = sketch.getGlobalPlacement()
    for wire in wires:
        wire.Placement = placement.multiply(wire.Placement)
    return wires


def _extent(feature, base):
    box = base.BoundBox if base is not None and not base.isNull() else None
    return 2.0 * box.DiagonalLength + 10.0 if box is not None else 1000.0


def rebuild(feature, sketch_values, params, base):
    """The seed Extrude's tool solid made with other values; (solid, subtractive)."""
    sketch = _sketch(feature)
    if sketch is None:
        raise RuntimeError("%s has no sketch" % feature.Label)
    wires = _profile(sketch, sketch_values)
    if not wires:
        raise RuntimeError("%s has no closed profile" % sketch.Label)
    face = Part.makeFace(wires, "Part::FaceMakerBullseye")
    normal = sketch.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
    subtractive = feature.TypeId == "PartDesign::Pocket"
    direction = -normal if subtractive else V(normal)
    if getattr(feature, "UseCustomVector", False):
        direction = V(feature.Direction).normalize()
    if getattr(feature, "Reversed", False):
        direction = -direction
    if abs(getattr(feature, "TaperAngle", App.Units.Quantity(0)).Value) > 1e-9 or \
            abs(getattr(feature, "TaperAngle2", App.Units.Quantity(0)).Value) > 1e-9:
        raise RuntimeError("Variable Pattern cannot vary a tapered extrude yet (%s)" % feature.Label)
    side = _side(feature)

    def depth(kind, param):
        if kind == "ThroughAll":
            return _extent(feature, base)
        if kind == "Length":
            return params.get(param, getattr(feature, param).Value)
        raise RuntimeError("Variable Pattern needs Blind or Through All ends (%s is %s)" % (feature.Label, kind))
    first = depth(feature.Type, "Length")
    if side == "Symmetric":
        back, length = first / 2.0, first
    elif side == "Two sides":
        second = depth(getattr(feature, "Type2", "Length"), "Length2")
        back, length = second, first + second
    else:
        back, length = 0.0, first
    if length <= 0:
        raise RuntimeError("A depth must be more than 0")
    if back:
        face.translate(direction * -back)
    return face.extrude(direction * length), subtractive


def _seeds(obj):
    return [f for f in (obj.Features or []) if f.TypeId in EXTRUDES]


def compute(obj, base):
    seeds = _seeds(obj)
    columns, rows = parse(obj.Table)
    if not seeds or not rows:
        return None, None
    bad = [f.Label for f in (obj.Features or []) if f.TypeId not in EXTRUDES]
    if bad:
        raise RuntimeError("Variable Pattern varies Extrude features made from a sketch (%s is not)" % ", ".join(bad))
    adds, cuts = [], []
    try:
        for row in rows:
            for feature in seeds:
                sketch = _sketch(feature)
                sketch_values, params = {}, {}
                for key, value in zip(columns, row):
                    if value is None or ":" not in key:
                        continue
                    owner, name = key.split(":", 1)
                    if sketch is not None and owner == sketch.Name:
                        sketch_values[name] = value
                    elif owner == feature.Name:
                        params[name] = value
                if not sketch_values and not params:
                    continue          # a row that changes nothing of this seed would sit on it
                solid, subtractive = rebuild(feature, sketch_values, params, base)
                (cuts if subtractive else adds).append(solid)
    finally:
        close_scratch()
    if not adds and not cuts:
        return None, None
    result = base
    if adds:
        result = result.fuse(adds, 1e-6)
    if cuts:
        result = result.cut(cuts, 1e-6)
    return result, Part.makeCompound(adds + cuts)


SPEC = sf.Spec(
    COMMAND, "Variable Pattern", "VarPattern",
    "Patterns features with instances that differ in their dimensions, from a table.",
    "FEATURES_VARIABLE_PATTERN", "PartDesign_LinearPattern",
    [Field("Features", "pick", "Features to Pattern", tip="Pick the seed Extrude features in the tree",
           what="Feature", many=True),
     Field("Table", "text", "Pattern table", "", shown=lambda obj: False)],
    compute)


# --------------------------------------------------------------------------- PropertyManager
_open = {"panel": None}


class _DimClicks(QtCore.QObject):
    """pkg466: a click on a shown seed dimension picks it for the table (not the face behind it)."""

    def __init__(self, panel):
        QtCore.QObject.__init__(self)
        self.panel = panel

    def eventFilter(self, widget, event):
        if event.type() not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) or \
                event.button() != QtCore.Qt.LeftButton:
            return False
        try:
            from . import featuredimshow
            view = Gui.ActiveDocument.ActiveView
            x, y, ratio = featuredimshow._coin_pos(widget, event)
            dims = [d for s in getattr(self.panel, "_shown", []) for d in s.dims]
            d = featuredimshow.dim_at(view, x, y, ratio, dims)
        except Exception as _fw_err:
            App.Console.PrintLog("FreeCAD: variable pattern click: %r\n" % (_fw_err,))
            return False
        if d is None:
            return False
        if event.type() == QtCore.QEvent.MouseButtonPress:
            QtCore.QTimer.singleShot(0, lambda: _open["panel"] is self.panel and self.panel.dim_clicked(d))
        return True


def current():
    """The Variable Pattern PropertyManager that is open, or None."""
    return _open["panel"]


class Panel(sf.Panel):
    ""

    def __init__(self, obj):
        _open["panel"] = self
        sf.Panel.__init__(self, obj)
        # the Table text is kept behind the grid: hide its own row
        table = self.widgets["Table"]
        table.setVisible(False)
        for label in table.parentWidget().findChildren(QtWidgets.QLabel):
            if label.text() == "Pattern table":
                label.setVisible(False)
        self.table_box = QtWidgets.QWidget()
        self.table_box.setWindowTitle("Pattern Table")
        layout = QtWidgets.QVBoxLayout(self.table_box)
        layout.addWidget(QtWidgets.QLabel("Dimensions to vary"))
        self.dims = QtWidgets.QListWidget()
        self.dims.setObjectName("SWStyle_VariableDimensions")
        self.dims.setMaximumHeight(110)
        self.dims.itemChanged.connect(self._dims_changed)
        layout.addWidget(self.dims)
        self.grid = QtWidgets.QTableWidget()
        self.grid.setObjectName("SWStyle_VariableTable")
        self.grid.setMinimumHeight(140)
        self.grid.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.grid.itemChanged.connect(self._cell_changed)
        layout.addWidget(self.grid)
        row = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton("Add Instance")
        self.add_button.setToolTip("Adds an instance; its values step on from the last two rows")
        self.add_button.clicked.connect(self.add_instance)
        self.delete_button = QtWidgets.QPushButton("Delete Instance")
        self.delete_button.clicked.connect(self.delete_instance)
        row.addWidget(self.add_button)
        row.addWidget(self.delete_button)
        layout.addLayout(row)
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        forms = self.form if isinstance(self.form, list) else [self.form]
        self.form = forms + [self.table_box]
        self._fill()

    # what is in the table
    def _state(self):
        columns, rows = parse(self.obj.Table)
        return columns, rows

    def _store(self, columns, rows):
        text = write(columns, rows) if columns else ""
        if text == self.obj.Table:
            return
        widget = self.widgets["Table"]
        widget.blockSignals(True)
        widget.setPlainText(text)
        widget.blockSignals(False)
        self._changed()
        self._fill()

    def _show(self):
        sf.Panel._show(self)
        if hasattr(self, "grid"):
            self._fill()

    def _fill(self):
        features = _seeds(self.obj)
        available = dimensions(features)
        columns, rows = self._state()
        self.busy_table = True
        self.dims.blockSignals(True)
        self.dims.clear()
        for key, label, value, unit in available:
            item = QtWidgets.QListWidgetItem("%s  (%.6g %s)" % (label, value, unit))
            item.setData(QtCore.Qt.UserRole, key)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if key in columns else QtCore.Qt.Unchecked)
            self.dims.addItem(item)
        self.dims.blockSignals(False)
        labels = dict((key, label) for key, label, _, _ in available)
        seed = seed_values(features, columns)
        self.grid.blockSignals(True)
        self.grid.clear()
        self.grid.setColumnCount(len(columns))
        self.grid.setRowCount(len(rows) + 1)
        self.grid.setHorizontalHeaderLabels([labels.get(k, k) for k in columns])
        self.grid.setVerticalHeaderLabels(["Seed"] + ["%d" % (i + 2) for i in range(len(rows))])
        for c in range(len(columns)):
            item = QtWidgets.QTableWidgetItem("" if seed[c] is None else "%.6g" % seed[c])
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            item.setForeground(self.grid.palette().brush(QtGui.QPalette.Disabled, QtGui.QPalette.Text))
            self.grid.setItem(0, c, item)
            for r, row in enumerate(rows):
                value = row[c]
                self.grid.setItem(r + 1, c, QtWidgets.QTableWidgetItem(
                    "%.6g" % (seed[c] if value is None and seed[c] is not None else value) if
                    (value is not None or seed[c] is not None) else ""))
        self.grid.blockSignals(False)
        names = sorted(f.Name for f in features)
        if names != getattr(self, "_dims_for", None) or not getattr(self, "_shown", None):
            self._dims_for = names
            self._dims_on()
        # no grey buttons (NO DEAD CONTROLS): a click with nothing to act on says what to do first
        if not features:
            self.note.setText("Pick the seed features first.")
        elif not columns:
            self.note.setText("Click the dimensions to vary in the graphics area, then add instances.")
        else:
            self.note.setText("")
        self.busy_table = False

    def _dims_changed(self, item):
        key = item.data(QtCore.Qt.UserRole)
        columns, rows = self._state()
        if item.checkState() == QtCore.Qt.Checked and key not in columns:
            columns.append(key)
            rows = [row + [None] for row in rows]
        elif item.checkState() != QtCore.Qt.Checked and key in columns:
            i = columns.index(key)
            columns.pop(i)
            rows = [row[:i] + row[i + 1:] for row in rows]
        if not columns:
            rows = []
        self._store(columns, rows)

    def _cell_changed(self, item):
        if getattr(self, "busy_table", False) or item.row() == 0:
            return
        columns, rows = self._state()
        r, c = item.row() - 1, item.column()
        if r >= len(rows) or c >= len(columns):
            return
        text = item.text().strip().replace(",", ".")
        for suffix in ("mm", "deg", "°"):
            text = text.replace(suffix, "").strip()
        try:
            rows[r][c] = float(text)
        except ValueError:
            rows[r][c] = None
        self._store(columns, rows)

    def _first(self, text):
        self.note.setText(text)
        try:
            Gui.getMainWindow().statusBar().showMessage(text, 0)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: variable pattern note: %r\n" % (error,))

    def add_instance(self):
        columns, rows = self._state()
        if not columns:
            self._first("Pick the seed features first." if not _seeds(self.obj) else
                        "Tick the dimensions to vary first, then add instances.")
            return
        seed = seed_values(_seeds(self.obj), columns)
        full = [seed] + [[s if v is None else v for v, s in zip(row, seed)] for row in rows]
        last = full[-1]
        before = full[-2] if len(full) > 1 else None
        new = []
        for i, value in enumerate(last):
            if value is None:
                new.append(None)
            elif before is not None and before[i] is not None:
                new.append(value + (value - before[i]))
            else:
                new.append(value)
        # the first instance starts as the seed's values, to be typed over (doubling the first column put an
        # X position of 802 mm at 1604 mm, far off the part)
        rows.append(new)
        self._store(columns, rows)

    def _close(self):
        _open["panel"] = None
        self._dims_off()
        sf.Panel._close(self)


    def _dims_on(self):
        from . import featuredimshow
        self._dims_off()
        shown = []
        for feature in _seeds(self.obj):
            s = featuredimshow._Shown()
            try:
                s.show(feature)
            except Exception as _fw_err:
                App.Console.PrintLog("FreeCAD: variable pattern dimensions: %r\n" % (_fw_err,))
                continue
            shown.append(s)
        self._shown = shown
        if shown and getattr(self, "_dim_filter", None) is None:
            widget = featuredimshow._viewport()
            if widget is not None:
                self._dim_filter = _DimClicks(self)
                self._dim_widget = widget
                widget.installEventFilter(self._dim_filter)

    def _dims_off(self):
        for s in getattr(self, "_shown", []):
            try:
                s.hide()
            except Exception as _fw_err:
                App.Console.PrintLog("FreeCAD: variable pattern dimensions: %r\n" % (_fw_err,))
        self._shown = []
        f, w = getattr(self, "_dim_filter", None), getattr(self, "_dim_widget", None)
        if f is not None and w is not None:
            try:
                w.removeEventFilter(f)
            except RuntimeError as _fw_err:
                App.Console.PrintLog("FreeCAD: variable pattern dimensions: %r\n" % (_fw_err,))
        self._dim_filter = self._dim_widget = None

    def dim_clicked(self, d):
        """A shown dimension was clicked: it becomes a column of the table (a second click takes it out)."""
        key = None
        if d.prop is not None:
            key = "%s:%s" % (d.obj.Name, d.prop)
        elif d.index is not None:
            key = "%s:%s" % (d.obj.Name, _constraint_key(d.obj, d.index))
        for i in range(self.dims.count()):
            item = self.dims.item(i)
            if item.data(QtCore.Qt.UserRole) == key:
                item.setCheckState(QtCore.Qt.Unchecked if item.checkState() == QtCore.Qt.Checked else QtCore.Qt.Checked)
                return True
        self._first("That dimension cannot be varied: pick a sketch dimension or the depth of a seed Extrude.")
        return True

    def delete_instance(self):
        columns, rows = self._state()
        if not rows:
            self._first("There is no instance to delete: add an instance first.")
            return
        r = self.grid.currentRow() - 1
        rows.pop(r if 0 <= r < len(rows) else len(rows) - 1)
        self._store(columns, rows)


class View(sf.View):
    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(Panel(vobj.Object))
        return True


def make(doc=None, features=None, edit=True, table=""):
    doc = doc or App.ActiveDocument
    body = sf.body_of(doc) if doc is not None else None
    if body is None or body.Tip is None:
        App.Console.PrintWarning("FreeCAD: Variable Pattern needs a body with a solid\n")
        return None
    doc.openTransaction(SPEC.title)
    obj = body.newObject(SPEC.type, SPEC.internal)
    sf.Feature(obj, SPEC)
    if App.GuiUp and Gui.ActiveDocument is not None:
        View(obj.ViewObject)
    obj.Label = naming.next_label(doc, SPEC.label)
    if features:
        obj.Features = list(features)
    if table:
        obj.Table = table
    doc.recompute()
    if edit and App.GuiUp:
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
    else:
        doc.commitTransaction()
    return obj


def _picked_features():
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        doc = sel.Object.Document
        for sub in sel.SubElementNames or [""]:
            holder = sel.Object
            for part in sub.split(".")[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    holder = found
            if holder.TypeId == "Sketcher::SketchObject":
                users = [o for o in holder.InList if o.TypeId in EXTRUDES]
                holder = users[0] if users else holder
            if holder.TypeId in EXTRUDES and holder not in out:
                out.append(holder)
    return out


class Command(sf.Command):
    def Activated(self):
        make(features=_picked_features())


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, Command(SPEC))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Variable Pattern command not added (%s)\n" % error)
