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
from PySide import QtCore, QtWidgets

from . import extrudepm, pmboxes
from . import pmfields

DONE = "freeworks_revolvepm"
TYPES = ("PartDesign::Revolution", "PartDesign::Groove")
SELECT = "Select reference"


def _alive(w):
    return extrudepm._alive(w)


def _select_index(combo):
    for i in range(combo.count()):
        if combo.itemText(i).startswith(SELECT):
            return i
    return -1


def _construction(text, feature):
    """"Construction line 2" -> "Line6@Sketch": the sketch's second construction line."""
    try:
        n = int(text.split()[-1])
        sketch = feature.Profile[0] if isinstance(feature.Profile, (list, tuple)) else feature.Profile
        count = 0
        for i, geo in enumerate(sketch.Geometry):
            if sketch.getConstruction(i) and "Line" in type(geo).__name__:
                count += 1
                if count == n:
                    return "Line%d@%s" % (i + 1, sketch.Label)
    except Exception as _fw_err:
        _fw_log("revolvepm.py:69", _fw_err)
    return text


def sw_name(text, feature=None):
    ""
    if text.lower().startswith("construction line") and feature is not None:
        return _construction(text, feature)
    if ":" not in text:
        return text
    label, sub = text.split(":", 1)
    if not sub.startswith("Edge"):
        return "%s@%s" % (sub, label)
    n = sub[4:]
    doc = App.ActiveDocument
    found = doc.getObjectsByLabel(label) if doc is not None else []
    obj = found[0] if found else (doc.getObject(label) if doc is not None else None)
    if obj is not None and obj.TypeId == "Sketcher::SketchObject":
        try:
            geo = obj.Geometry[int(n) - 1]
            kind = "Line" if "Line" in type(geo).__name__ else type(geo).__name__.replace("Of", "")
        except Exception:
            kind = "Line"
        return "%s%s@%s" % (kind, n, label)
    return "Edge<%s>@%s" % (n, label)


class AxisBox(QtCore.QObject):
    """The Axis of Revolution pick box over FreeCAD's hidden axis drop-down."""

    def __init__(self, view, combo, label, fresh, feature=None):
        super().__init__(combo)
        self.view, self.combo = view, combo
        self.feature = feature
        self.waiting = False
        self._axis_generation = 0
        self.combo.currentIndexChanged.connect(self._selection_changed)
        panel = combo.parentWidget()
        self.title = QtWidgets.QLabel("Axis of Revolution", panel)
        self.title.setObjectName("SWStyle_AxisTitle")
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self.box = QtWidgets.QListWidget(panel)
        self.box.setObjectName("SWStyle_AxisOfRevolution")
        self.box.setFixedHeight(26)
        self.box.setToolTip("Axis of Revolution: click a line, an edge or an axis")
        self.box.viewport().installEventFilter(self)
        lay = panel.layout()
        if isinstance(lay, QtWidgets.QBoxLayout):
            lay.insertWidget(0, self.title)
            lay.insertWidget(1, self.box)
        combo.hide()
        if label is not None:
            label.hide()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.sync)
        self.timer.start(150)

        # while a value is typed, so the next click on a line or axis still goes into it
        for name in ("revolveAngle", "revolveAngle2"):
            spin = view.findChild(QtWidgets.QAbstractSpinBox, name)
            if spin is not None:
                try:
                    spin.valueChanged.connect(lambda *_a: QtCore.QTimer.singleShot(0, self._rearm))
                except Exception as _fw_err:
                    _fw_log("revolvepm.py:rearm", _fw_err)
                spin.editingFinished.connect(lambda: QtCore.QTimer.singleShot(0, self._rearm))
        if fresh:
            QtCore.QTimer.singleShot(0, self.first)
        self.sync()

    def first(self):
        ""
        if not _alive(self.combo):
            return
        for i in range(self.combo.count()):
            if self.combo.itemText(i).lower().startswith("construction line"):
                self._choose(i)
                return
        self.wait()

    def _choose(self, index):
        if not _alive(self.combo):
            return False
        self.combo.setCurrentIndex(index)
        if not _alive(self.combo) or self.combo.currentIndex() != index:
            return False
        generation = getattr(self, "_axis_generation", 0)
        QtCore.QTimer.singleShot(0, lambda: self._activate(index, generation))
        return True

    def _selection_changed(self, _index):
        # Any real change, including away/back, invalidates older deferred callbacks.
        self._axis_generation = getattr(self, "_axis_generation", 0) + 1

    def _activate(self, index, generation):
        # Let first()/wait() return before FreeCAD's native activated handler runs.
        # A closing panel or a superseded selection must not emit a stale activation.
        if not _alive(self.combo) or generation != getattr(self, "_axis_generation", 0) \
                or self.combo.currentIndex() != index:
            return
        self.combo.activated.emit(index)

    def _rearm(self):
        """Still waiting for the axis after a value change: put FreeCAD back in picking."""
        if self.waiting and _alive(self.combo) and self.combo.currentText().startswith(SELECT):
            index = self.combo.currentIndex()
            generation = getattr(self, "_axis_generation", 0)
            QtCore.QTimer.singleShot(0, lambda: self._activate(index, generation))

    def wait(self):
        i = _select_index(self.combo)
        if i < 0:
            return
        if not self._choose(i):
            return
        self.waiting = True
        self.sync()

    def _preview(self, on):
        ""


        if getattr(self, "_previewing", None) == on:
            return
        box = self.view.findChild(QtWidgets.QCheckBox, "showTransparentPreviewCheckBox") if _alive(self.view) else None
        if box is None:
            return
        self._previewing = on
        if box.isChecked() != on:
            box.setChecked(on)

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.MouseButtonPress:
            try:
                self.wait()
            except Exception as _fw_err:
                _fw_log("revolvepm.py:192", _fw_err)
        return False

    def sync(self):
        if not _alive(self.combo) or not _alive(self.box):
            self.timer.stop()
            return
        text = self.combo.currentText()
        if text.startswith(SELECT):
            self.waiting = True
        elif self.waiting:
            self.waiting = False
        shown = "" if self.waiting and text.startswith(SELECT) else sw_name(text, self.feature)
        if self.box.count() != (1 if shown else 0) or (shown and self.box.item(0).text() != shown):
            self.box.clear()
            if shown:
                self.box.addItem(shown)
        self._preview(not self.waiting)
        pmboxes.mark(self.box, self.waiting)
        if self.combo.isVisible():
            self.combo.hide()


SW_ITEMS = ["Blind", "Up To Vertex", "Up To Surface", "Offset From Surface", "Mid Plane"]
FC_MODE = {"Blind": "Blind", "Up To Vertex": "Blind", "Up To Surface": "Up To Surface",
           "Offset From Surface": "Blind", "Mid Plane": "Blind"}
OFFSET = "Offset From Surface"
TWO = "Two Directions"


def _row_of(layout, widget):
    """The layout under layout that holds widget, and its index there."""
    if layout is None:
        return None, -1
    i = layout.indexOf(widget)
    if i >= 0:
        return layout, i
    for k in range(layout.count()):
        found, j = _row_of(pmfields.sub_layout(layout, k), widget)
        if found is not None:
            return found, j
    return None, -1


def _index_of_layout(outer, inner):
    for k in range(outer.count()):
        if pmfields.sub_layout(outer, k) is inner:
            return k
    return -1


def angle_to_vertex(feat, point):
    """The revolve angle (degrees, signed about the axis) from the profile to point."""
    import math
    base = App.Vector(feat.Base)
    d = App.Vector(feat.Axis)
    if d.Length < 1e-9:
        raise RuntimeError("Pick the Axis of Revolution first.")
    d.normalize()
    try:
        sketch = feat.Profile[0] if isinstance(feat.Profile, (list, tuple)) else feat.Profile
        c = sketch.Shape.BoundBox.Center
    except Exception:
        raise RuntimeError("Up To Vertex needs the profile sketch.")

    def across(p):
        v = p - base
        v = v - d * v.dot(d)
        if v.Length < 1e-9:
            raise RuntimeError("That vertex lies on the axis.")
        v.normalize()
        return v
    u, v = across(c), across(point)
    return math.degrees(math.atan2(u.cross(v).dot(d), u.dot(v)))


def angle_to_face(feat, face, offset=0.0, reverse=False):
    """Offset From Surface: the revolve angle (degrees, signed) from the profile round the axis to
    the face, less the offset (an arc of that length at the profile's centre; Reverse offset: past
    the face)."""
    import math
    import Part
    base, d = App.Vector(feat.Base), App.Vector(feat.Axis)
    if d.Length < 1e-9:
        raise RuntimeError("Pick the Axis of Revolution first.")
    d.normalize()
    sketch = feat.Profile[0] if isinstance(feat.Profile, (list, tuple)) else feat.Profile
    c = sketch.Shape.BoundBox.Center
    foot = base + d * (c - base).dot(d)
    r = (c - foot).Length
    if r < 1e-9:
        raise RuntimeError("The profile lies on the axis.")
    hits = Part.makeCircle(r, foot, d).section(face).Vertexes
    angles = [angle_to_vertex(feat, v.Point) for v in hits]
    angles = [a for a in angles if abs(a) > 1e-6]
    if not angles:
        raise RuntimeError("The revolve does not reach that face.")
    a = min(angles, key=abs)
    step = math.degrees(offset / r) * (1 if reverse else -1)
    return math.copysign(max(abs(a) + step, 0.01), a)


def angle_round(feat, point, sense):
    """The angle (degrees, 0..360) from the profile round the axis to point, going the sense way
    (+1: the right-hand way about the axis)."""
    a = angle_to_vertex(feat, point) * sense
    return a % 360.0


def angle_to_face_way(feat, face, sense, offset=0.0, reverse=False):
    """angle_to_face going one way round (Direction 2 goes the other way from Direction 1)."""
    import math
    import Part
    base, d = App.Vector(feat.Base), App.Vector(feat.Axis)
    if d.Length < 1e-9:
        raise RuntimeError("Pick the Axis of Revolution first.")
    d.normalize()
    sketch = feat.Profile[0] if isinstance(feat.Profile, (list, tuple)) else feat.Profile
    c = sketch.Shape.BoundBox.Center
    foot = base + d * (c - base).dot(d)
    r = (c - foot).Length
    if r < 1e-9:
        raise RuntimeError("The profile lies on the axis.")
    hits = Part.makeCircle(r, foot, d).section(face).Vertexes
    angles = [angle_round(feat, v.Point, sense) for v in hits]
    angles = [a for a in angles if 1e-6 < a < 360 - 1e-6]
    if not angles:
        raise RuntimeError("The revolve does not reach that face.")
    step = math.degrees(offset / r) * (1 if reverse else -1)
    return max(min(angles) + step, 0.01)


def _ref_shape(o, sub):
    """The vertex point or face shape a remembered pick stands for."""
    import Part
    if sub:
        el = o.Shape.getElement(sub)
        return el.Point if el.ShapeType == "Vertex" else el
    pl = o.getGlobalPlacement()
    return Part.Plane(pl.Base, pl.Rotation.multVec(App.Vector(0, 0, 1))).toShape(-1e4, 1e4, -1e4, 1e4)


END_PROPS = ("SWEndCondition", "SWEndRef", "SWEndOffset", "SWEndReverse")


def remember(feat, which, choice, ref=None, offset=0.0, reverse=False):
    ""

    kinds = ("App::PropertyString", "App::PropertyLinkSub", "App::PropertyFloat", "App::PropertyBool")
    for name, kind in zip(END_PROPS, kinds):
        if not hasattr(feat, name + which):
            if not choice:
                return
            feat.addProperty(kind, name + which, "End Condition", "End condition kept for Edit Feature")
            try:
                feat.setEditorMode(name + which, 2)
            except Exception as _fw_err:
                _fw_log("revolvepm.py:remember mode", _fw_err)
    setattr(feat, "SWEndCondition" + which, choice or "")
    setattr(feat, "SWEndRef" + which, ref if (choice and ref) else None)
    setattr(feat, "SWEndOffset" + which, float(offset))
    setattr(feat, "SWEndReverse" + which, bool(reverse))


def recall(feat, which):
    """(choice, (object, sub), offset, reverse) kept on the feature, or None."""
    try:
        choice = getattr(feat, "SWEndCondition" + which, "")
        if not choice:
            return None
        ref = getattr(feat, "SWEndRef" + which, None)
        if ref is not None and isinstance(ref, tuple) and ref[0] is not None:
            subs = ref[1] if isinstance(ref[1], (list, tuple)) else [ref[1]]
            ref = (ref[0], subs[0] if subs else "")
        else:
            ref = None
        return choice, ref, float(getattr(feat, "SWEndOffset" + which, 0.0)), bool(getattr(feat, "SWEndReverse" + which, False))
    except Exception as _fw_err:
        _fw_log("revolvepm.py:recall", _fw_err)
        return None


ITEMS2 = ["Blind", "Up To Vertex", "Up To Surface", "Offset From Surface"]


class RevolveFields(QtCore.QObject):
    ""

    def __init__(self, view, mode, feat):
        super().__init__(mode)
        self.view, self.mode, self.feat = view, mode, feat
        panel = mode.parentWidget()
        self.midplane = panel.findChild(QtWidgets.QCheckBox, "checkBoxMidplane")
        self.face_button = panel.findChild(QtWidgets.QPushButton, "buttonFace")
        self.face_line = panel.findChild(QtWidgets.QLineEdit, "lineFaceName")
        self.angle2 = panel.findChild(QtWidgets.QAbstractSpinBox, "revolveAngle2")
        self.label2 = panel.findChild(QtWidgets.QLabel, "labelAngle2")
        self.choice = None          # "Up To Vertex" (FreeCAD cannot tell it from Blind)
        self.vertex = None          # (label, point) picked for Up To Vertex
        row, i = _row_of(panel.layout(), mode)
        self.end = QtWidgets.QComboBox(panel)
        self.end.setObjectName("SWStyle_EndCondition")
        self.end.addItems(SW_ITEMS)
        self.end.setSizePolicy(mode.sizePolicy())
        if row is not None:
            row.insertWidget(i, self.end)
        mode.hide()
        label = panel.findChild(QtWidgets.QLabel, "labelAngle")
        if label is not None:
            label.setText("Angle")
        if self.midplane is not None:
            self.midplane.hide()
        # Up To Vertex / Up To Surface pick boxes, under the end condition
        outer = panel.layout()
        at = _index_of_layout(outer, row) + 1 if row is not None else 2
        self.vertex_box = QtWidgets.QListWidget(panel)
        self.vertex_box.setObjectName("SWStyle_UpToVertex")
        self.vertex_box.setFixedHeight(26)
        self.vertex_box.setToolTip("Vertex: click the vertex the revolve goes up to")
        self.vertex_box.viewport().installEventFilter(self)
        self.face_box = QtWidgets.QListWidget(panel)
        self.face_box.setObjectName("SWStyle_UpToSurface")
        self.face_box.setFixedHeight(26)
        self.face_box.setToolTip("Face/Plane: click the face the revolve goes up to")
        self.face_box.viewport().installEventFilter(self)
        outer.insertWidget(at, self.face_box)
        outer.insertWidget(at, self.vertex_box)
        # Offset From Surface: the face, the offset distance and Reverse offset
        self.offset_face = None     # (label, face shape)
        self.offset_box = QtWidgets.QListWidget(panel)
        self.offset_box.setObjectName("SWStyle_OffsetSurface")
        self.offset_box.setFixedHeight(26)
        self.offset_box.setToolTip("Face/Plane: click the face the revolve stops short of")
        self.offset_box.viewport().installEventFilter(self)
        self.offset = QtWidgets.QDoubleSpinBox(panel)
        self.offset.setObjectName("SWStyle_OffsetDistance")
        self.offset.setRange(0.0, 1e5)
        self.offset.setDecimals(2)
        self.offset.setSuffix(" mm")
        self.offset.setToolTip("Offset distance from the face")
        pmboxes.bind(self.vertex_box, lambda row: self.take_out("vertex"), lambda: self.take_out("vertex"))
        pmboxes.bind(self.face_box, lambda row: self.take_out("face"), lambda: self.take_out("face"))
        pmboxes.bind(self.offset_box, lambda row: self.take_out("offset"), lambda: self.take_out("offset"))
        try:
            # Up To Surface / Offset From Surface waiting for the face: a click by its edge stays on the face
            from . import facehover
            facehover.faces_only(self, lambda me: me.face_button is not None and _alive(me.face_button)
                                 and me.face_button.isChecked() and me.face_button.window().isVisible())
        except Exception:
            pass
        self.offset_reverse = QtWidgets.QCheckBox("Reverse offset", panel)
        self.offset_reverse.setObjectName("SWStyle_ReverseOffset")
        for w in (self.offset_reverse, self.offset, self.offset_box):
            outer.insertWidget(at + 2, w)
        self.offset.valueChanged.connect(lambda v: self._apply_offset())
        self.offset_reverse.toggled.connect(lambda on: self._apply_offset())
        # Direction 2: a check box box with its own angle (FreeCAD: the Two Directions type)
        self.second = QtWidgets.QCheckBox("Direction2", panel)
        self.second.setObjectName("SWStyle_Direction2")
        row2, _j = _row_of(outer, self.angle2) if self.angle2 is not None else (None, -1)
        k = _index_of_layout(outer, row2) if row2 is not None else -1
        if k >= 0:
            outer.insertWidget(k, self.second)
        else:
            outer.addWidget(self.second)
        extrudepm.section_header(self.second)
        if self.label2 is not None:
            self.label2.setText("Angle")

        # Surface; FreeCAD's second angle is set from the pick
        self.choice2, self.ref2, self.arm2 = None, None, False      # ref2: (label, point or face, (object, sub))
        self.offset_ref = None
        self.end2 = QtWidgets.QComboBox(panel)
        self.end2.setObjectName("SWStyle_EndCondition2")
        self.end2.addItems(ITEMS2)
        self.end2.setSizePolicy(mode.sizePolicy())
        self.box2 = QtWidgets.QListWidget(panel)
        self.box2.setObjectName("SWStyle_UpToRef2")
        self.box2.setFixedHeight(26)
        self.box2.viewport().installEventFilter(self)
        self.offset2 = QtWidgets.QDoubleSpinBox(panel)
        self.offset2.setObjectName("SWStyle_OffsetDistance2")
        self.offset2.setRange(0.0, 1e5)
        self.offset2.setDecimals(2)
        self.offset2.setSuffix(" mm")
        self.offset2.setToolTip("Offset distance from the face")
        self.reverse2 = QtWidgets.QCheckBox("Reverse offset", panel)
        self.reverse2.setObjectName("SWStyle_ReverseOffset2")
        k2 = outer.indexOf(self.second) + 1
        for w in (self.reverse2, self.offset2, self.box2, self.end2):
            outer.insertWidget(k2, w)
        for w in (self.end2, self.box2, self.offset2, self.reverse2):
            w.hide()
        pmboxes.bind(self.box2, lambda row: self.take_out("ref2"), lambda: self.take_out("ref2"))
        self.end2.activated.connect(self._end2_picked)
        self.offset2.valueChanged.connect(lambda v: self._apply2())
        self.reverse2.toggled.connect(lambda on: self._apply2())
        rev = view.findChild(QtWidgets.QCheckBox, "checkBoxReversed")
        if rev is not None:
            rev.toggled.connect(lambda on: QtCore.QTimer.singleShot(0, self._apply2))
        self.end.activated.connect(self._end_picked)
        self.second.toggled.connect(self._second_toggled)
        mode.currentIndexChanged.connect(lambda i: self.sync())
        if self.midplane is not None:
            self.midplane.toggled.connect(lambda on: self.sync())
        if self.face_line is not None:
            self.face_line.textChanged.connect(lambda t: self.sync())
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(200)
        try:
            self._recall()
        except Exception as _fw_err:
            _fw_log("revolvepm.py:recall fields", _fw_err)
        self.sync()

    def _recall(self):
        ""
        r = recall(self.feat, "")
        if r and r[0] in ("Up To Vertex", OFFSET) and self._fc() in ("Blind", TWO) and \
                not (self.midplane is not None and self.midplane.isChecked()):
            choice, ref, off, rv = r
            self.choice = choice
            if ref is not None:
                shape = _ref_shape(*ref)
                label = "%s@%s" % (ref[1] or "Plane", ref[0].Label)
                if choice == "Up To Vertex":
                    self.vertex = (label, shape)
                else:
                    self.offset_face = (label, shape)
                    self.offset_ref = ref
            for w, v in ((self.offset, off), (self.offset_reverse, rv)):
                w.blockSignals(True)
                w.setValue(v) if w is self.offset else w.setChecked(v)
                w.blockSignals(False)
        r2 = recall(self.feat, "2")
        if r2 and self._fc() == TWO and r2[0] in ITEMS2[1:]:
            choice, ref, off, rv = r2
            self.choice2 = choice
            if ref is not None:
                self.ref2 = ("%s@%s" % (ref[1] or "Plane", ref[0].Label), _ref_shape(*ref), ref)
            for w, v in ((self.offset2, off), (self.reverse2, rv)):
                w.blockSignals(True)
                w.setValue(v) if w is self.offset2 else w.setChecked(v)
                w.blockSignals(False)


    def _fc(self):
        return self.mode.currentText()

    def current(self):
        if self.midplane is not None and self.midplane.isChecked():
            return "Mid Plane"
        if self._fc() == "Up To Surface":
            return "Up To Surface"
        if self.choice in ("Up To Vertex", OFFSET):
            return self.choice
        return "Blind"

    def _set_mode(self, text):
        for i in range(self.mode.count()):
            if self.mode.itemText(i) == text:
                if self.mode.currentIndex() != i:
                    self.mode.setCurrentIndex(i)
                    self.mode.activated.emit(i)
                return

    def _end_picked(self, index):
        item = self.end.itemText(index)
        self.choice = item if item in ("Up To Vertex", OFFSET) else None
        self.arm2 = False
        if self.choice is None:
            remember(self.feat, "", "")
        if self.midplane is not None and self.midplane.isChecked() != (item == "Mid Plane"):
            self.midplane.setChecked(item == "Mid Plane")
        if self.second.isChecked() and item in ("Up To Surface", "Mid Plane"):      # FreeCAD: these have no second angle
            self.second.blockSignals(True)
            self.second.setChecked(False)
            self.second.blockSignals(False)
        self._set_mode(TWO if self.second.isChecked() else FC_MODE[item])
        if item == "Up To Surface":
            self._arm_face()
        if item in ("Up To Vertex", OFFSET):
            self.vertex = None
            self.offset_face = None
            self._arm_vertex()
        else:
            self._disarm_vertex()
        self.sync()

    def _second_toggled(self, on):
        if on:
            if self.current() in ("Up To Surface", "Mid Plane"):
                self.choice = None
                remember(self.feat, "", "")
            if self.midplane is not None and self.midplane.isChecked():
                self.midplane.setChecked(False)
            self._set_mode(TWO)
        else:
            self._set_mode("Blind")
            self.choice2, self.ref2 = None, None
            remember(self.feat, "2", "")
            if self.arm2:
                self.arm2 = False
                self._disarm_vertex()
        self.sync()

    # --- Direction 2's end condition
    def _end2_picked(self, index):
        item = self.end2.itemText(index)
        self.choice2 = None if item == "Blind" else item
        self.ref2 = None
        if self.choice2 is None:
            remember(self.feat, "2", "")
            self.arm2 = False
            self._disarm_vertex()
        else:
            self.arm2 = True
            self._arm_vertex()
        self.sync()

    def _pick2(self, doc, obj, sub):
        o = App.getDocument(doc).getObject(obj)
        want = self.choice2
        try:
            if want == "Up To Vertex":
                if not sub.startswith("Vertex"):
                    return
                self.ref2 = ("%s@%s" % (sub, o.Label), o.Shape.getElement(sub).Point, (o, sub))
            elif want in ("Up To Surface", OFFSET):
                plane = not sub and o is not None and o.TypeId in ("App::Plane", "PartDesign::Plane")
                if not (sub.startswith("Face") or plane):
                    return
                self.ref2 = ("%s@%s" % (sub or "Plane", o.Label), _ref_shape(o, sub), (o, sub))
            else:
                return
        except Exception as error:
            App.Console.PrintError("FreeCAD: Direction 2 %s: %s\n" % (want, error))
            return
        self.arm2 = False
        QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)
        self._disarm_vertex()
        self._apply2()
        self.sync()

    def _apply2(self):
        """Direction 2's angle up to the picked vertex or face (less or past the offset)."""
        if not self.choice2 or self.ref2 is None or not _alive(self.end2):
            return
        rev = self.view.findChild(QtWidgets.QCheckBox, "checkBoxReversed")
        sense = 1 if (rev is not None and rev.isChecked()) else -1       # the other way from Direction 1
        try:
            if self.choice2 == "Up To Vertex":
                a = angle_round(self.feat, self.ref2[1], sense)
            else:
                off = self.choice2 == OFFSET
                a = angle_to_face_way(self.feat, self.ref2[1], sense, self.offset2.value() if off else 0.0,
                                      off and self.reverse2.isChecked())
        except Exception as error:
            App.Console.PrintError("FreeCAD: Direction 2 %s: %s\n" % (self.choice2, error))
            return
        if self.angle2 is not None and _alive(self.angle2):
            self.angle2.setProperty("rawValue", a)
            try:
                self.angle2.editingFinished.emit()
            except Exception as _fw_err:
                _fw_log("revolvepm.py:angle2", _fw_err)
        remember(self.feat, "2", self.choice2, self.ref2[2], self.offset2.value(), self.reverse2.isChecked())

    # --- Up To Surface: FreeCAD's Face button takes the next face click
    def _arm_face(self):
        if self.face_button is not None and not self.face_button.isChecked():
            self.face_button.click()

    # --- Up To Vertex: the next vertex click sets the angle
    def _arm_vertex(self):
        if getattr(self, "_observing", False):
            return
        self._observing = True
        Gui.Selection.addObserver(self)
        Gui.Selection.clearSelection()

    def _disarm_vertex(self):
        if getattr(self, "_observing", False):
            self._observing = False
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("revolvepm.py:453", _fw_err)

    def addSelection(self, doc, obj, sub, pnt):
        if self.arm2 and _alive(self.end2):
            self._pick2(doc, obj, sub)
            return
        if self.choice == OFFSET and _alive(self.end):
            o = App.getDocument(doc).getObject(obj)
            if sub.startswith("Face") or (not sub and o is not None and o.TypeId in ("App::Plane", "PartDesign::Plane")):
                try:
                    if sub:
                        face = o.Shape.getElement(sub)
                    else:
                        import Part
                        pl = o.getGlobalPlacement()
                        face = Part.Plane(pl.Base, pl.Rotation.multVec(App.Vector(0, 0, 1))).toShape(-1e4, 1e4, -1e4, 1e4)
                    self.offset_face = ("%s@%s" % (sub or "Plane", o.Label), face)
                    self.offset_ref = (o, sub)
                    self._apply_offset()
                except Exception as error:
                    App.Console.PrintError("FreeCAD: Offset From Surface: %s\n" % error)
                QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)
                self._disarm_vertex()
                self.sync()
            return
        if not sub.startswith("Vertex") or not _alive(self.end):
            return
        try:
            o = App.getDocument(doc).getObject(obj)
            p = o.Shape.getElement(sub).Point
            angle = angle_to_vertex(self.feat, p)
        except Exception as error:
            App.Console.PrintError("FreeCAD: Up To Vertex: %s\n" % error)
            return
        self.vertex = ("%s@%s" % (sub, o.Label), p)
        remember(self.feat, "", "Up To Vertex", (o, sub))
        spin = self.view.findChild(QtWidgets.QAbstractSpinBox, "revolveAngle")
        rev = self.view.findChild(QtWidgets.QCheckBox, "checkBoxReversed")
        if rev is not None and rev.isChecked() != (angle < 0):
            rev.setChecked(angle < 0)
        if spin is not None:
            spin.setProperty("rawValue", abs(angle))
            try:
                spin.editingFinished.emit()
            except Exception as _fw_err:
                _fw_log("revolvepm.py:493", _fw_err)
        QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)
        self._disarm_vertex()
        self.sync()

    def _apply_offset(self):
        """The angle up to the face, less the offset, as the Blind angle."""
        if self.offset_face is None or not _alive(self.end):
            return
        try:
            angle = angle_to_face(self.feat, self.offset_face[1], self.offset.value(), self.offset_reverse.isChecked())
        except Exception as error:
            App.Console.PrintError("FreeCAD: Offset From Surface: %s\n" % error)
            return
        spin = self.view.findChild(QtWidgets.QAbstractSpinBox, "revolveAngle")
        rev = self.view.findChild(QtWidgets.QCheckBox, "checkBoxReversed")
        if rev is not None and rev.isChecked() != (angle < 0):
            rev.setChecked(angle < 0)
        if spin is not None:
            spin.setProperty("rawValue", abs(angle))
            try:
                spin.editingFinished.emit()
            except Exception as _fw_err:
                _fw_log("revolvepm.py:516", _fw_err)
        if self.offset_ref is not None:
            remember(self.feat, "", OFFSET, self.offset_ref, self.offset.value(), self.offset_reverse.isChecked())

    def removeSelection(self, *args):
        pass

    def setSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def take_out(self, which):
        """Delete / Clear Selections in a pick box: the pick goes, the box takes the next one."""
        try:
            if which == "ref2":
                self.ref2 = None
                self.arm2 = True
                self._arm_vertex()
            elif which == "vertex":
                self.arm2 = False
                self.vertex = None
                self._arm_vertex()
            elif which == "offset":
                self.arm2 = False
                self.offset_face = None
                self._arm_vertex()
            else:
                self.arm2 = False
                self._arm_face()
            self.sync()
        except Exception as _fw_err:
            _fw_log("revolvepm.py:540", _fw_err)

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.MouseButtonPress:
            try:
                if watched is self.box2.viewport():
                    self.ref2 = None
                    self.arm2 = True
                    self._arm_vertex()
                elif watched is self.vertex_box.viewport():
                    self.arm2 = False
                    self.vertex = None
                    self._arm_vertex()
                elif watched is self.offset_box.viewport():
                    self.arm2 = False
                    self.offset_face = None
                    self._arm_vertex()
                elif watched is self.face_box.viewport():
                    self.arm2 = False
                    self._arm_face()
                self.sync()
            except Exception as _fw_err:
                _fw_log("revolvepm.py:557", _fw_err)
        return False

    def _tick(self):
        if not _alive(self.end):
            self.timer.stop()
            self._disarm_vertex()
            return
        # FreeCAD re-shows its Mid Plane box and re-labels the angle on every mode change
        for w in (self.face_button, self.face_line, self.midplane):
            if w is not None and not w.isHidden():
                w.hide()
        for name in ("labelAngle", "labelAngle2"):
            label = self.view.findChild(QtWidgets.QLabel, name)
            if label is not None and label.text() not in ("Angle", "") and not label.property("swlayout"):
                label.setText("Angle")      # pkg90: pmlayout shows the angle glyph instead

    def sync(self):
        if not _alive(self.end):
            return
        cur = self.current()
        if self.end.currentText() != cur:
            self.end.setCurrentIndex(max(0, self.end.findText(cur)))
        two = self._fc() == TWO
        if self.second.isChecked() != two:
            self.second.blockSignals(True)
            self.second.setChecked(two)
            self.second.blockSignals(False)
        self.vertex_box.setVisible(cur == "Up To Vertex")
        self.face_box.setVisible(cur == "Up To Surface")
        for w in (self.offset_box, self.offset, self.offset_reverse):
            w.setVisible(cur == OFFSET)
        if cur == OFFSET:
            self._fill(self.offset_box, self.offset_face[0] if self.offset_face else "", not self.offset_face)
        if cur == "Up To Vertex":
            text = self.vertex[0] if self.vertex else ""
            waiting = not self.vertex
            self._fill(self.vertex_box, text, waiting)
        if cur == "Up To Surface":
            text = self.face_line.text() if self.face_line is not None else ""
            if ":" in text:
                a, b = text.split(":", 1)
                text = "%s@%s" % (b, a)
            self._fill(self.face_box, text, not text or (self.face_button is not None and self.face_button.isChecked()))

        picked = cur in ("Up To Vertex", OFFSET)
        for name in ("revolveAngle", "labelAngle"):
            w = self.view.findChild(QtWidgets.QWidget, name)
            if w is not None and _alive(w):
                if picked and not w.isHidden():
                    w.hide()
                elif cur in ("Blind", "Mid Plane") and w.isHidden():
                    w.show()
        c2 = self.choice2 or "Blind"
        if self.end2.currentText() != c2:
            self.end2.setCurrentIndex(max(0, self.end2.findText(c2)))
        self.end2.setVisible(two)
        self.box2.setVisible(two and c2 != "Blind")
        for w in (self.offset2, self.reverse2):
            w.setVisible(two and c2 == OFFSET)
        if two and c2 != "Blind":
            self.box2.setToolTip("Vertex: click the vertex Direction 2 goes up to" if c2 == "Up To Vertex"
                                 else "Face/Plane: click the face Direction 2 goes up to")
            self._fill(self.box2, self.ref2[0] if self.ref2 else "", self.arm2 or not self.ref2)
        for w in (self.label2, self.angle2):
            if w is not None:
                pmfields.set_shown(w, two and c2 == "Blind")

    def _fill(self, box, text, waiting):
        if box.count() != (1 if text else 0) or (text and box.item(0).text() != text):
            box.clear()
            if text:
                box.addItem(text)
        pmboxes.mark(box, waiting)


def _own_box(view, axis_box):
    """Axis of Revolution as a box of its own: the panel's box takes that title and a Direction 1
    title follows the axis box (as extrudepm's From box)."""
    panel = axis_box.box.parentWidget()
    group = panel
    while group is not None and not group.inherits("QSint::ActionGroup"):
        group = group.parentWidget()
    if group is None:
        return
    for header in group.findChildren(QtWidgets.QWidget):
        if header.inherits("QSint::TaskHeader"):
            labels = [l for l in header.findChildren(QtWidgets.QWidget)
                      if hasattr(l, "text") and callable(l.text) and l.text() == "Direction 1"]
            if labels:
                labels[0].setText("Axis of Revolution")
            break
    axis_box.title.hide()
    d1 = QtWidgets.QLabel("Direction1", panel)
    d1.setObjectName("SWStyle_Direction1Title")
    lay = panel.layout()
    lay.insertWidget(lay.indexOf(axis_box.box) + 1, d1)
    extrudepm.section_header(d1)


def install(view):
    feat = extrudepm._edited()
    if feat is None or feat.TypeId not in TYPES:
        return
    combo = view.findChild(QtWidgets.QComboBox, "axis")
    if combo is None or combo.property(DONE):
        return
    combo.setProperty(DONE, True)
    fresh = _just_made(feat)     # made by the command just now (not an edit)
    axis_box = AxisBox(view, combo, view.findChild(QtWidgets.QLabel, "textLabel1"), fresh, feat)
    rev = view.findChild(QtWidgets.QCheckBox, "checkBoxReversed")
    mode = view.findChild(QtWidgets.QComboBox, "changeMode")
    if rev is not None and mode is not None:
        extrudepm.ReverseButton(view, rev, mode)
    if mode is not None:
        RevolveFields(view, mode, feat)
    try:
        _own_box(view, axis_box)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: revolve boxes: %s\n" % error)
    if feat.TypeId == "PartDesign::Groove":
        angle = view.findChild(QtWidgets.QAbstractSpinBox, "revolveAngle")
        if angle is not None:
            try:
                extrudepm._flip_side(view, angle)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: Cut-Revolve Flip side to cut: %s\n" % error)
    extrudepm._hide_native_extras(view)
    tidy = QtCore.QTimer(combo)
    tidy.timeout.connect(lambda: _alive(view) and extrudepm._hide_native_extras(view))
    tidy.start(150)


_made = {}


def _just_made(feat):
    t = _made.get(feat.Document.Name + "." + feat.Name)
    import time
    return t is not None and time.time() - t < 5.0


class _AppObserver:
    def slotCreatedObject(self, obj):
        try:
            if obj.TypeId in TYPES and not obj.Document.Restoring:
                import time
                _made[obj.Document.Name + "." + obj.Name] = time.time()
        except Exception as _fw_err:
            _fw_log("revolvepm.py:686", _fw_err)


_observers = []


def startup():
    if not _observers:
        o = _AppObserver()
        App.addDocumentObserver(o)
        _observers.append(o)
