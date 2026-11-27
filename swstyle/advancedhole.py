# SPDX-License-Identifier: LGPL-2.1-or-later
""





















import math

import FreeCAD as App
import Part

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
KINDS = ("counterbore", "countersink", "straight", "tapered", "tap", "cone")   # longer names first
DEFAULT = "Counterbore 11 6.5\nStraight 6.6 through"
FIT_NAMES = ("Close", "Normal", "Loose")


def parse(text):
    """([(kind, diameter, depth_or_angle)], far stack)."""
    near, far, stack = [], [], None
    stack = near
    for line in text.splitlines():
        words = line.replace(",", " ").split()
        if not words:
            continue
        head = words[0].lower()
        if head in ("far", "far:", "farside", "far-side"):
            stack = far
            continue
        if head in ("near", "near:"):
            stack = near
            continue
        kind = head if head in KINDS else \
            next((k for k in KINDS if k.startswith(head) or head.startswith(k)), None)
        if kind is None or len(words) < 2:
            raise RuntimeError("Hole element not understood: %s" % line.strip())
        standard = _standard(words[1])
        if standard is not None and len(words) > 2:
            rest = words[3:]
            fit = "Normal"
            if rest and rest[0].capitalize() in FIT_NAMES:
                fit = rest[0].capitalize()
                rest = rest[1:]
            diameter, value = from_standard(kind, standard, words[2].replace("_", " "), fit)
            if rest and rest[0].lower().startswith("through"):
                amount = None
            elif rest:
                amount = float(rest[0])
            else:
                amount = value
            stack.append((kind, diameter, amount))
            continue
        diameter = float(words[1])
        if len(words) > 2 and words[2].lower().startswith("through"):
            amount = None
        else:
            amount = float(words[2]) if len(words) > 2 else (90.0 if kind == "countersink" else None)
        stack.append((kind, diameter, amount))
    return near, far


def _standard(word):
    from . import holedata
    w = word.replace("-", " ").replace("_", " ").lower()
    alias = {"inch": "ANSI Inch", "ansi inch": "ANSI Inch", "metric": "ANSI Metric", "ansi metric": "ANSI Metric"}
    if w in alias:
        return alias[w]
    return next((s for s in holedata.STANDARDS if s.lower() == w), None)


def from_standard(kind, standard, size, fit="Normal"):
    ""

    from . import holedata
    if kind == "counterbore":
        t = holedata.types("Counterbore", standard)[0]
        d = holedata.dims("Counterbore", standard, t, size, fit)
        return d["head_d"], d["head_depth"]
    if kind == "countersink":
        t = holedata.types("Countersink", standard)[0]
        d = holedata.dims("Countersink", standard, t, size, fit)
        return d["head_d"], d["head_angle"]
    if kind in ("tap", "tapered"):
        family = "Tapered Tap" if kind == "tapered" else "Straight Tap"
        t = holedata.types(family, standard)[0]
        d = holedata.dims(family, standard, t, size)
        return d["tap_drill"], 2 * d["major"]
    return holedata.clearance(standard, size, fit), None


def _profile(stack, through):
    """Revolve profile points (radius, depth) going down the hole, depth positive into material."""
    points = []
    depth = 0.0
    radius_above = None
    for index, (kind, diameter, amount) in enumerate(stack):
        radius = diameter / 2.0
        if kind == "countersink":
            angle = math.radians(amount or 90.0)
            below = stack[index + 1][1] / 2.0 if index + 1 < len(stack) else radius * 0.5
            drop = (radius - below) / math.tan(angle / 2.0)
            points += [(radius, depth), (below, depth + drop)]
            depth += drop
            radius_above = below
            continue
        length = through if amount is None else amount
        if kind in ("tapered", "cone") and amount is not None:
            tip = radius * 0.6
            points += [(radius, depth), (tip, depth + length)]
        else:
            if radius_above is not None and abs(radius_above - radius) > 1e-9:
                points.append((radius_above, depth))
            points += [(radius, depth), (radius, depth + length)]
        depth += length
        radius_above = radius
        if amount is None:
            break
    return points, depth


def _solid(points, top, down):
    """A solid of revolution about the axis through top along down."""
    if not points:
        return None
    outline = [V(0, 0, 0)] + [V(r, 0, d) for r, d in points] + [V(0, 0, points[-1][1])]
    clean = [outline[0]]
    for p in outline[1:]:
        if (p - clean[-1]).Length > 1e-9:
            clean.append(p)
    wire = Part.makePolygon(clean + [clean[0]])
    solid = Part.Face(wire).revolve(V(0, 0, 0), V(0, 0, 1), 360)
    solid = Part.Solid(Part.Shell(solid.Faces)) if solid.ShapeType != "Solid" else solid
    if solid.Volume < 0:
        solid.reverse()
    solid.Placement = App.Placement(top, App.Rotation(V(0, 0, 1), down))
    return solid


def _points(obj, face):
    sketch = obj.Positions
    if sketch is None:
        clicked = list(getattr(obj, "PositionPoints", []) or [])     # pkg468: Positions clicked on the face
        return [V(p) for p in clicked] or [face.CenterOfMass]
    placement = sketch.getGlobalPlacement() if hasattr(sketch, "getGlobalPlacement") else sketch.Placement
    out = []
    for index, geometry in enumerate(sketch.Geometry):
        if sketch.getConstruction(index):
            continue
        if isinstance(geometry, Part.Point):
            out.append(placement.multVec(V(geometry.X, geometry.Y, geometry.Z)))
        elif isinstance(geometry, (Part.Circle, Part.ArcOfCircle)):
            out.append(placement.multVec(geometry.Center))
    return out or [face.CenterOfMass]


def _advanced_hole(obj, base):
    picked = sf.elements(obj, "Face")
    if not picked:
        return None, None
    face = picked[0][1]
    if not isinstance(face.Surface, Part.Plane):
        raise RuntimeError("Advanced Hole needs a flat near-side face")
    near, far = parse(obj.Elements)
    if not near and not far:
        raise RuntimeError("Add at least one hole element")
    center = face.CenterOfMass
    out = face.normalAt(*face.Surface.parameter(center))
    down = -out
    through = base.BoundBox.DiagonalLength * 2
    tools = []
    for point in _points(obj, face):
        top = point - out * out.dot(point - face.Surface.Position)    # onto the face plane
        if near:
            pts, _ = _profile(near, through)
            tools.append(_solid([(r, d - 0.01) if i == 0 else (r, d) for i, (r, d) in enumerate(pts)],
                                top - down * 0.01, down))
        if far:
            # the far face: where a line down the axis leaves the part
            line = Part.LineSegment(top, top + down * through).toShape()
            hits = line.common(base)
            exit_point = max((v.Point for v in hits.Vertexes), key=lambda p: (p - top).Length) if hits.Vertexes else top + down * through
            pts, _ = _profile(far, through)
            tools.append(_solid(pts, exit_point + down * 0.01, -down))
    tools = [t for t in tools if t is not None]
    if not tools:
        return None, None
    result = base.cut(tools, 1e-6)
    return result, Part.makeCompound(tools)


# --------------------------------------------------------------------------- element lists
TYPES = ["Counterbore", "Countersink", "Straight", "Straight Tap", "Tapered Tap"]
_WORD = {"Counterbore": "Counterbore", "Countersink": "Countersink", "Straight": "Straight",
         "Straight Tap": "Tap", "Tapered Tap": "Tapered"}
_TYPE = {"counterbore": "Counterbore", "countersink": "Countersink", "straight": "Straight",
         "tap": "Straight Tap", "tapered": "Tapered Tap", "cone": "Tapered Tap"}
_FAMILY = {"Counterbore": "Counterbore", "Countersink": "Countersink", "Straight": "Hole",
           "Straight Tap": "Straight Tap", "Tapered Tap": "Tapered Tap"}
CUSTOM = "Custom size"


def element(type_name="Straight", standard=None, size="", diameter=6.6, amount=None, fit="Normal"):
    """One row of a Near Side / Far Side list. amount: depth (None = Through All) or a countersink's angle."""
    return {"type": type_name, "standard": standard, "size": size, "diameter": float(diameter),
            "amount": amount, "fit": fit}


def has_fit(row):
    ""
    return bool(row.get("standard")) and row["type"] in ("Straight", "Counterbore", "Countersink")


def rows(text):
    """The Near Side and Far Side lists of an Elements text: ([element], [element])."""
    near, far = [], []
    stack = near
    for line in (text or "").splitlines():
        words = line.replace(",", " ").split()
        if not words:
            continue
        head = words[0].lower()
        if head in ("far", "far:", "farside", "far-side"):
            stack = far
            continue
        if head in ("near", "near:"):
            stack = near
            continue
        (kind, diameter, amount), = parse(line)[0]
        standard = _standard(words[1]) if len(words) > 2 else None
        size = words[2].replace("_", " ") if standard else ""
        fit = words[3].capitalize() if standard and len(words) > 3 and words[3].capitalize() in FIT_NAMES else "Normal"
        stack.append(element(_TYPE.get(kind, "Straight"), standard, size, diameter, amount, fit))
    return near, far


def _number(value):
    return ("%.4f" % value).rstrip("0").rstrip(".")


def _line(row):
    word = _WORD.get(row["type"], "Straight")
    amount = row.get("amount")
    if row["type"] == "Countersink":
        tail = _number(amount if amount is not None else 90.0)
    else:
        tail = "through" if amount is None else _number(amount)
    if row.get("standard") and row.get("size"):
        fit = row.get("fit", "Normal")
        fit = (" " + fit) if fit != "Normal" and has_fit(row) else ""
        return "%s %s %s%s %s" % (word, row["standard"].replace(" ", "-"), row["size"].replace(" ", "_"), fit, tail)
    return "%s %s %s" % (word, _number(row["diameter"]), tail)


def text(near, far=()):
    """The Elements text of two lists."""
    lines = [_line(r) for r in near]
    if far:
        lines.append("far")
        lines += [_line(r) for r in far]
    return "\n".join(lines)


def sizes(type_name, standard):
    from . import holedata
    family = _FAMILY.get(type_name, "Hole")
    try:
        kinds = holedata.types(family, standard)
        if family == "Hole":
            kind = "Screw Clearances"
        else:
            kind = kinds[0] if kinds else ""
        return list(holedata.sizes(family, standard, kind))
    except Exception:
        return []


def with_size(row, standard, size):
    """The row with a standard size: its diameter and default depth / angle from the Hole Wizard tables."""
    out = dict(row)
    if not standard or not size:
        out["standard"], out["size"] = None, ""
        return out
    kind = {"Straight Tap": "tap", "Tapered Tap": "tapered"}.get(row["type"], row["type"].lower())
    diameter, value = from_standard(kind, standard, size, row.get("fit", "Normal") if has_fit(dict(row, standard=standard)) else "Normal")
    out.update(standard=standard, size=size, diameter=float(diameter))
    if row["type"] == "Countersink" or (value is not None and row.get("amount") is not None):
        out["amount"] = value
    return out


try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:      # bench without a GUI
    QtWidgets = None


class Panel(sf.Panel):
    ""


    def addSelection(self, doc, name, sub, point):

        # centre there (on the near side face's plane), as the Hole Wizard's Positions tab
        if getattr(self, "active", None) == "Positions" and point is not None and sub and \
                sub.split(".")[-1].startswith("Face"):
            p = App.Vector(*point)
            QtCore.QTimer.singleShot(0, lambda: self._alive() and self._place(p))
            return
        sf.Panel.addSelection(self, doc, name, sub, point)

    def _place(self, point):
        """The clicked hole centres are kept on the feature (no sketch object of their own: one Undo or Cancel
        takes them with the hole)."""
        import FreeCADGui as Gui
        obj = self.obj
        if "PositionPoints" not in obj.PropertiesList:
            obj.addProperty("App::PropertyVectorList", "PositionPoints", "Advanced Hole",
                            "Hole centres clicked on the near side face (Positions)")
        obj.PositionPoints = list(obj.PositionPoints) + [point]
        try:
            Gui.Selection.clearSelection()
            Gui.getMainWindow().statusBar().showMessage("%d hole position(s): click for another, or OK" % len(obj.PositionPoints), 6000)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: advanced hole position: %r\n" % (error,))
        self._changed()

    def __init__(self, obj):
        super().__init__(obj)
        text_box = self.widgets["Elements"]
        text_box.setVisible(False)
        layout = text_box.parentWidget().layout()
        label = layout.labelForField(text_box) if isinstance(layout, QtWidgets.QFormLayout) else None
        if label is not None:
            label.setVisible(False)
        self.near, self.far = rows(obj.Elements)
        self.side = "near"
        self.current = 0 if self.near else -1
        self.lists_ui = {}
        self._side_box(layout, "near")
        far_box = QtWidgets.QWidget()
        far_box.setWindowTitle("Far Side")
        far_layout = QtWidgets.QFormLayout(far_box)
        self.far_on = QtWidgets.QCheckBox("Far Side")
        self.far_on.setObjectName("SWAdvancedHole_FarSide")
        self.far_on.setToolTip("Adds elements cut from the far side of the part")
        self.far_on.setChecked(bool(self.far))
        self.far_on.toggled.connect(self._far_toggled)
        far_layout.addRow(self.far_on)
        self._kept_far = list(self.far)
        self._side_box(far_layout, "far")
        spec_box = QtWidgets.QWidget()
        spec_box.setWindowTitle("Element Specification")
        self._spec_box(QtWidgets.QFormLayout(spec_box))
        boxes = self.form if isinstance(self.form, list) else [self.form]
        at = next((i for i, b in enumerate(boxes) if b.windowTitle() == "Near Side"), 0) + 1
        boxes[at:at] = [far_box, spec_box]
        self.form = boxes
        self._fill()

    # ---- the lists
    def _side_box(self, layout, side):
        lst = QtWidgets.QListWidget()
        lst.setObjectName("SWAdvancedHole_%sList" % side.title())
        lst.setToolTip(("Near Side" if side == "near" else "Far Side") +
                       " elements, from the face into the part. Click one to edit it.")
        lst.setMaximumHeight(96)
        lst.currentRowChanged.connect(lambda row, s=side: self._pick_row(s, row))
        layout.addRow(lst)
        row = QtWidgets.QHBoxLayout()
        add = QtWidgets.QToolButton()
        add.setObjectName("SWAdvancedHole_%sInsert" % side.title())
        add.setText("Insert Element")
        add.setToolTip("Insert element below active element")
        add.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(add)
        for type_name in TYPES:
            action = menu.addAction(type_name)
            action.setObjectName("SWAdvancedHole_%sInsert_%s" % (side.title(), type_name.replace(" ", "")))
            action.triggered.connect(lambda checked=False, s=side, t=type_name: self.insert(s, t))
        add.setMenu(menu)
        delete = QtWidgets.QToolButton()
        delete.setObjectName("SWAdvancedHole_%sDelete" % side.title())
        delete.setText("Delete Element")
        delete.setToolTip("Delete active element")
        delete.clicked.connect(lambda checked=False, s=side: self.delete(s))
        row.addWidget(add)
        row.addWidget(delete)
        row.addStretch(1)
        holder = QtWidgets.QWidget()
        holder.setLayout(row)
        layout.addRow(holder)
        self.lists_ui[side] = (lst, add, delete, holder)

    def _stack(self, side):
        return self.near if side == "near" else self.far

    def insert(self, side, type_name):
        """Insert Element: a new element of type_name below the active element of that side."""
        if side == "far" and not self.far_on.isChecked():
            self.far_on.setChecked(True)
        stack = self._stack(side)
        before = stack[self.current] if self.side == side and 0 <= self.current < len(stack) else \
            (stack[-1] if stack else None)
        diameter = before["diameter"] * (0.6 if type_name in ("Straight", "Straight Tap") else 1.0) \
            if before else 6.6
        amount = {"Countersink": 90.0}.get(type_name, 5.0)
        if type_name in ("Straight", "Straight Tap") and side == "near" and before is not None:
            amount = None
        new = element(type_name, None, "", round(diameter, 3), amount)
        at = (self.current + 1) if self.side == side and 0 <= self.current < len(stack) else len(stack)
        stack.insert(at, new)
        self.side, self.current = side, at
        self._write()

    def delete(self, side):
        stack = self._stack(side)
        if self.side != side or not (0 <= self.current < len(stack)):
            return
        if side == "near" and len(stack) == 1:
            self.error.setText("The near side keeps at least one element")
            self.error.setVisible(True)
            return
        del stack[self.current]
        self.current = min(self.current, len(stack) - 1)
        self._write()

    def _far_toggled(self, on):
        if on:
            if not self.far:
                self.far[:] = self._kept_far or [element("Counterbore", None, "", 11.0, 5.0)]
        else:
            self._kept_far = list(self.far)
            self.far[:] = []
            if self.side == "far":
                self.side, self.current = "near", 0
        self._write()

    def _pick_row(self, side, row):
        if getattr(self, "_filling", False) or row < 0:
            return
        self.side, self.current = side, row
        self._filling = True
        try:
            other = self.lists_ui["far" if side == "near" else "near"][0]
            other.clearSelection()
            other.setCurrentRow(-1)
        finally:
            self._filling = False
        self._show_spec()

    # ---- Element Specification
    def _spec_box(self, layout):
        self.e_type = QtWidgets.QComboBox()
        self.e_type.setObjectName("SWAdvancedHole_Type")
        self.e_type.addItems(TYPES)
        self.e_standard = QtWidgets.QComboBox()
        self.e_standard.setObjectName("SWAdvancedHole_Standard")
        from . import holedata
        self.e_standard.addItems([CUSTOM] + list(holedata.STANDARDS))
        self.e_size = QtWidgets.QComboBox()
        self.e_size.setObjectName("SWAdvancedHole_Size")
        self.e_fit = QtWidgets.QComboBox()
        self.e_fit.setObjectName("SWAdvancedHole_Fit")
        self.e_fit.addItems(list(FIT_NAMES))
        self.e_diameter = QtWidgets.QDoubleSpinBox()
        self.e_diameter.setObjectName("SWAdvancedHole_Diameter")
        self.e_diameter.setRange(0.01, 10000.0)
        self.e_diameter.setDecimals(3)
        self.e_diameter.setSuffix(" mm")
        self.e_end = QtWidgets.QComboBox()
        self.e_end.setObjectName("SWAdvancedHole_End")
        self.e_end.addItems(["Blind", "Through All"])
        self.e_amount = QtWidgets.QDoubleSpinBox()
        self.e_amount.setObjectName("SWAdvancedHole_Depth")
        self.e_amount.setRange(0.01, 10000.0)
        self.e_amount.setDecimals(3)
        layout.addRow("Element Type", self.e_type)
        layout.addRow("Standard", self.e_standard)
        layout.addRow("Size", self.e_size)
        layout.addRow("Fit", self.e_fit)
        layout.addRow("Diameter", self.e_diameter)
        layout.addRow("End Condition", self.e_end)
        layout.addRow("Depth", self.e_amount)
        self.e_layout = layout
        self.e_type.currentIndexChanged.connect(lambda *a: self._edit("type"))
        self.e_standard.currentIndexChanged.connect(lambda *a: self._edit("standard"))
        self.e_size.currentIndexChanged.connect(lambda *a: self._edit("size"))
        self.e_fit.currentIndexChanged.connect(lambda *a: self._edit("fit"))
        self.e_diameter.valueChanged.connect(lambda *a: self._edit("diameter"))
        self.e_end.currentIndexChanged.connect(lambda *a: self._edit("end"))
        self.e_amount.valueChanged.connect(lambda *a: self._edit("amount"))

    def active_element(self):
        stack = self._stack(self.side)
        return stack[self.current] if 0 <= self.current < len(stack) else None

    def _show_spec(self):
        row = self.active_element()
        widgets = (self.e_type, self.e_standard, self.e_size, self.e_fit, self.e_diameter, self.e_end, self.e_amount)
        for w in widgets:
            w.setEnabled(row is not None)
        if row is None:
            return
        self._filling = True
        try:
            self.e_type.setCurrentText(row["type"])
            self.e_standard.setCurrentText(row["standard"] or CUSTOM)
            self.e_size.clear()
            if row["standard"]:
                self.e_size.addItems(sizes(row["type"], row["standard"]))
                self.e_size.setCurrentText(row["size"])
            self.e_size.setEnabled(bool(row["standard"]))
            self.e_fit.setCurrentText(row.get("fit", "Normal"))
            self.e_fit.setEnabled(has_fit(row))
            self.e_diameter.setValue(row["diameter"])
            self.e_diameter.setEnabled(not row["standard"])
            sink = row["type"] == "Countersink"
            self.e_end.setVisible(not sink)
            self.e_layout.labelForField(self.e_end).setVisible(not sink)
            self.e_end.setCurrentText("Through All" if row["amount"] is None and not sink else "Blind")
            self.e_layout.labelForField(self.e_amount).setText("Angle" if sink else "Depth")
            self.e_amount.setSuffix(" \u00b0" if sink else " mm")
            self.e_amount.setVisible(sink or row["amount"] is not None)
            self.e_layout.labelForField(self.e_amount).setVisible(sink or row["amount"] is not None)
            if row["amount"] is not None:
                self.e_amount.setValue(row["amount"])
        finally:
            self._filling = False

    def _edit(self, what):
        if getattr(self, "_filling", False):
            return
        row = self.active_element()
        if row is None:
            return
        if what == "type":
            row["type"] = self.e_type.currentText()
            row["standard"], row["size"] = None, ""
            if row["type"] == "Countersink":
                row["amount"] = 90.0
            elif row["amount"] is not None and row["amount"] > 60:
                row["amount"] = 5.0
        elif what == "standard":
            standard = self.e_standard.currentText()
            if standard == CUSTOM:
                row["standard"], row["size"] = None, ""
            else:
                choices = sizes(row["type"], standard)
                if choices:
                    keep = row["size"] if row["size"] in choices else choices[min(len(choices) // 2, len(choices) - 1)]
                    row.update(with_size(row, standard, keep))
        elif what == "size" and row["standard"]:
            if self.e_size.currentText():
                row.update(with_size(row, row["standard"], self.e_size.currentText()))
        elif what == "fit":
            row["fit"] = self.e_fit.currentText()
            if row["standard"] and row["size"]:
                row.update(with_size(row, row["standard"], row["size"]))
        elif what == "diameter":
            row["diameter"] = self.e_diameter.value()
        elif what == "end":
            row["amount"] = None if self.e_end.currentText() == "Through All" else (self.e_amount.value() or 5.0)
        elif what == "amount":
            row["amount"] = self.e_amount.value()
        self._write()

    # ---- the stored text
    def _write(self):
        self.obj.Elements = text(self.near, self.far)
        self.widgets["Elements"].blockSignals(True)
        self.widgets["Elements"].setPlainText(self.obj.Elements)
        self.widgets["Elements"].blockSignals(False)
        self._fill()
        self.obj.Document.recompute()
        self._preview()
        self._show()

    def _fill(self):
        self._filling = True
        try:
            for side in ("near", "far"):
                lst, add, delete, holder = self.lists_ui[side]
                lst.clear()
                for r in self._stack(side):
                    lst.addItem(_row_text(r))
                if side == "far":
                    on = self.far_on.isChecked()
                    lst.setVisible(on)
                    holder.setVisible(on)
            lst = self.lists_ui[self.side][0]
            if 0 <= self.current < lst.count():
                lst.setCurrentRow(self.current)
        finally:
            self._filling = False
        self._show_spec()


def _row_text(row):
    if row["type"] == "Countersink":
        end = "%s\u00b0" % _number(row["amount"] if row["amount"] is not None else 90.0)
    else:
        end = "Through All" if row["amount"] is None else "%s deep" % _number(row["amount"])
    size = ("%s %s" % (row["standard"], row["size"])) if row["standard"] else "\u00d8%s" % _number(row["diameter"])
    return "%s  %s  %s" % (row["type"], size, end)


ADVANCED_HOLE = sf.Spec(
    "SWStyle_AdvancedHole", "Advanced Hole", "Advanced Hole",
    "A hole made of a stack of elements (counterbore, countersink, straight, tapered) from both sides.",
    "FEATURES_ADVANCED_HOLE", "PartDesign_Hole",
    [Field("Face", "pick", "Near side face", what=("Face",), box="Near Side"),
     Field("Elements", "text", "Elements (near side first; a line 'far' starts the far side)", DEFAULT,
           box="Near Side",
           tip="One per line: Counterbore D depth / Countersink D angle / Straight D depth|through / "
               "Tapered D depth"),
     Field("Positions", "pick", "Hole positions (click on the face, or a sketch with points)", what="Feature", box="Positions",
           optional=True)],
    _advanced_hole, subtractive=True, first_pick="Face", panel=Panel if QtWidgets is not None else None)


def register():
    sf.register(ADVANCED_HOLE)
