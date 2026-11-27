# SPDX-License-Identifier: LGPL-2.1-or-later
""


















from . import editobj

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

from . import instant3d
from . import pmfields, pmvalues

Qt = QtCore.Qt

DONE = "freeworks_extrudepm"
GIZMOS = "User parameter:BaseApp/Preferences/Gui/Gizmos"
ARROW_GREY = (0.45, 0.45, 0.45)
TYPES = ("PartDesign::Pad", "PartDesign::Pocket")


def _alive(w):
    try:
        w.objectName()
        return True
    except (RuntimeError, AttributeError):
        return False


def _edited():
    try:
        vp = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
        return editobj.of(vp) if vp is not None else None
    except Exception:
        return None


def _grid_of(widget):
    parent = widget.parentWidget()
    if parent is None:
        return None, None
    stack = [parent.layout()]
    while stack:
        lay = stack.pop()
        if lay is None:
            continue
        index = lay.indexOf(widget)
        if index >= 0:
            return lay, index
        for i in range(lay.count()):
            stack.append(pmfields.sub_layout(lay, i))
    return None, None


def _place_after(widget, new, own_row=True):
    """Put new where widget is (a grid row of its own below it, or after it in a box)."""
    lay, index = _grid_of(widget)
    if isinstance(lay, QtWidgets.QGridLayout):
        r, c, rs, cs = lay.getItemPosition(index)
        if own_row:
            # shift every row below down one
            pmfields.put_grid_rows(lay, pmfields.take_grid_rows(lay, lambda ir: ir <= r))
            lay.addWidget(new, r + 1, 0, 1, max(2, lay.columnCount()))
        else:
            lay.addWidget(new, r, c, rs, cs)
    elif isinstance(lay, QtWidgets.QBoxLayout):
        lay.insertWidget(index + 1, new)
    elif lay is not None:
        lay.addWidget(new)



SECTION = "swstyle_section"


FOLDS = {}


def _page_title(widget):
    try:
        from . import propertymanager
        header = propertymanager._header_of(widget)
        return header.title.text() if header is not None else ""
    except Exception:
        return ""


def _widgets_in(lay):
    """Every widget in a layout, sub-layouts included."""
    out = []
    for i in range(lay.count()):
        w = pmfields.sub_widget(lay, i)
        if w is not None:
            out.append(w)
        else:
            sub = pmfields.sub_layout(lay, i)
            if sub is not None:
                out.extend(_widgets_in(sub))
    return out


class _Fold(QtCore.QObject):
    ""


    def __init__(self, title, lay, row):
        self.button = QtWidgets.QToolButton(title.parentWidget())
        super().__init__(self.button)           # lives with its chevron: fold_of(button)
        self.title, self.lay, self.row = title, lay, row
        self.button.setObjectName("SWStyle_SectionFold")
        self.button.setAutoRaise(True)
        self.button.setArrowType(Qt.UpArrow)
        self.button.setFixedSize(18, 18)
        self.button.setToolTip("Collapse")
        if isinstance(lay, QtWidgets.QGridLayout):
            lay.addWidget(self.button, row, max(1, lay.columnCount() - 1), 1, 1, Qt.AlignRight | Qt.AlignVCenter)
        else:
            # a box layout: the title moves into a row of its own with the chevron at the right
            lay.removeWidget(title)
            line = QtWidgets.QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(title)
            line.addStretch(1)
            line.addWidget(self.button, 0, Qt.AlignRight | Qt.AlignVCenter)
            lay.insertLayout(row, line)
            self.line = line
        self.button.clicked.connect(self.toggle)
        self.folded = False
        self.hidden = []
        QtCore.QTimer.singleShot(0, self._apply_memory)

    def key(self):
        return (_page_title(self.title), self.title.text().replace("&", ""))

    def _stop(self, w):
        return (w.property(SECTION) or w.objectName() == "SWStyle_SectionRule"
                or isinstance(w, QtWidgets.QToolButton) and w.objectName() == "SWStyle_SectionFold" and w is not self.button)

    def _rows(self):
        """The rows of this section: after the title, up to the next section title or rule."""
        out = []
        grid = isinstance(self.lay, QtWidgets.QGridLayout)
        for i in range(self.lay.count()):
            if grid:
                r, c, rs, cs = self.lay.getItemPosition(i)
                if r <= self.row:
                    continue
            elif i <= self.lay.indexOf(self.line):
                continue
            w = pmfields.sub_widget(self.lay, i)
            sub = pmfields.sub_layout(self.lay, i)
            if w is None and sub is not None:
                w = pmfields.sub_widget(sub, 0)
                if w is None or not self._stop(w):
                    out.extend(_widgets_in(sub))
                    continue
            if w is None:
                continue
            if self._stop(w):
                break
            out.append(w)
        return out

    def _apply_memory(self):
        if FOLDS.get(self.key()) and not self.folded:
            self.toggle()

    def toggle(self):
        self.folded = not self.folded
        self.button.setArrowType(Qt.DownArrow if self.folded else Qt.UpArrow)
        self.button.setToolTip("Expand" if self.folded else "Collapse")
        if self.folded:
            self.hidden = [w for w in self._rows() if not w.isHidden()]
            for w in self.hidden:
                w.hide()
        else:
            for w in self.hidden:
                if _alive(w):
                    w.show()
            self.hidden = []
        FOLDS[self.key()] = self.folded


def fold_of(button):
    """The _Fold behind a SWStyle_SectionFold chevron."""
    for child in button.children():
        if isinstance(child, _Fold):
            return child


def section_header(widget, line_above=True):
    ""


    if widget is None or not _alive(widget) or widget.property(SECTION):
        return
    widget.setProperty(SECTION, True)
    font = widget.font()
    font.setBold(True)
    widget.setFont(font)
    _rule_above(widget, line_above)
    if isinstance(widget, QtWidgets.QLabel):
        lay0, index0 = _grid_of(widget)
        if isinstance(lay0, QtWidgets.QGridLayout):
            r0, _c, _rs, _cs = lay0.getItemPosition(index0)
            _Fold(widget, lay0, r0)
        elif isinstance(lay0, QtWidgets.QVBoxLayout):
            _Fold(widget, lay0, index0)


def _rule_above(widget, line_above):
    if not line_above:
        return
    parent = widget.parentWidget()
    lay, index = _grid_of(widget)
    rule = QtWidgets.QFrame(parent)
    rule.setObjectName("SWStyle_SectionRule")
    rule.setFrameShape(QtWidgets.QFrame.HLine)
    rule.setFrameShadow(QtWidgets.QFrame.Plain)
    rule.setStyleSheet("color: palette(mid);")
    if isinstance(lay, QtWidgets.QHBoxLayout):
        # a title row of its own (FreeCAD's "Direction 2" row: title, then a line): the title
        # goes first, no extra rule (PC check 11-01 showed the rule pushing it to the right)
        rule.deleteLater()
        if index != 0:
            pmfields.take_item(lay, index)
            lay.insertWidget(0, widget)
        return
    if isinstance(lay, QtWidgets.QBoxLayout):
        lay.insertWidget(index, rule)
    elif isinstance(lay, QtWidgets.QGridLayout):
        r, c, rs, cs = lay.getItemPosition(index)
        # a rule in the row above: shift this row and the rows below down one
        pmfields.put_grid_rows(lay, pmfields.take_grid_rows(lay, lambda ir: ir < r))
        lay.addWidget(rule, r, 0, 1, max(2, lay.columnCount()))
    widget.destroyed.connect(lambda *a, r=rule: _alive(r) and r.deleteLater())


def _move_after(anchor, widget):
    """Takes widget out of its row and puts it on a row of its own after anchor's row."""
    if anchor is None or widget is None or not (_alive(anchor) and _alive(widget)):
        return False
    if widget.property("swstyle_moved"):
        return False
    widget.setProperty("swstyle_moved", True)
    lay, index = _grid_of(widget)
    if lay is not None and index is not None:
        pmfields.take_item(lay, index)
    _place_after(anchor, widget)
    return True


def _split_from(view, length):
    ""

    start = view.findChild(QtWidgets.QWidget, "SWStyle_From")
    if start is None or start.property("swstyle_split") or start.parentWidget() is not length.parentWidget():
        return
    group = start
    while group is not None and not group.inherits("QSint::ActionGroup"):
        group = group.parentWidget()
    if group is None:
        return
    title = None
    for header in group.findChildren(QtWidgets.QWidget):
        if header.inherits("QSint::TaskHeader"):
            # the title is a QSint::ActionLabel (a tool button), not a QLabel
            labels = [l for l in header.findChildren(QtWidgets.QWidget)
                      if hasattr(l, "text") and callable(l.text) and l.text() == "Direction 1"]
            title = labels[0] if labels else None
            break
    if title is None:
        return
    start.setProperty("swstyle_split", True)
    title.setText("From")
    for label in start.findChildren(QtWidgets.QLabel):
        if label.text() == "From":
            label.hide()            # the box title says it now
            break
    d1 = QtWidgets.QLabel("Direction 1", start.parentWidget())
    d1.setObjectName("SWStyle_Direction1Title")
    _place_after(start, d1)
    section_header(d1)


_picks = []


class DirectionPick(QtCore.QObject):
    ""



    ACTIVE = "QLineEdit { background: #cce4f7; color: #000000; border: 1px solid #7eb4ea; }"

    def __init__(self, view, combo):
        super().__init__(view)
        self.combo = combo
        group = combo.parentWidget()
        self.box = QtWidgets.QLineEdit(group)
        self.box.setObjectName("SWStyle_DirectionOfExtrusion")
        self.box.setProperty("swpickbox", True)     # a selection box: gets its colour strip
        self.box.setReadOnly(True)
        self.box.setPlaceholderText("Direction of Extrusion")
        self.box.setToolTip("Direction of Extrusion: pick a line, edge, axis or planar face; "
                            "empty = normal to the sketch")
        self.box.setContextMenuPolicy(Qt.CustomContextMenu)
        lay, index = _grid_of(combo)
        label = view.findChild(QtWidgets.QLabel, "labelEdge")
        if isinstance(lay, QtWidgets.QGridLayout):
            r, c, rs, cs = lay.getItemPosition(index)
            lay.addWidget(self.box, r, 0, 1, max(2, lay.columnCount()))
        elif lay is not None:
            lay.insertWidget(index, self.box)
        for w in (combo, label):
            if w is not None:
                w.hide()
        if isinstance(group, QtWidgets.QGroupBox):
            group.setTitle("")
            group.setFlat(True)
            group.setStyleSheet("QGroupBox { border: none; margin: 0; padding: 0; }")
        self.box.installEventFilter(self)
        self.box.customContextMenuRequested.connect(self._menu)
        combo.currentIndexChanged.connect(self.sync)
        self.sync()

    def waiting(self):
        return _alive(self.combo) and self.combo.currentIndex() == 1 and \
            self.combo.currentText().endswith(("\u2026", "..."))

    def sync(self, *args):
        if not (_alive(self.combo) and _alive(self.box)):
            return
        # FreeCAD shows its X/Y/Z direction and "Length along sketch normal" while it waits for

        from . import safe_later as _sl; _sl.later(0, self._hide_extras, self, "box")
        QtCore.QTimer.singleShot(0, self._repair)
        text = self.combo.currentText()
        normal = self.combo.currentIndex() == 0 or text.endswith(":N_Axis")     # dirbox-1127: the profile's normal
        self.box.setText("" if normal or self.waiting() else text)
        self.box.setStyleSheet(self.ACTIVE if self.waiting() else "")

    def _repair(self):
        """FreeCAD's "Sketch normal" entry can name the sketch while the profile is its Selected
        Contours object: the reference follows the profile (ChatGPT 2B02)."""
        try:
            from . import pmfields
            feat = _edited()
            if feat is not None and pmfields.repair_axis(feat):
                feat.Document.recompute()
        except Exception as _fw_err:
            _fw_log("extrudepm.py:378", _fw_err)

    def _hide_extras(self):
        try:
            view = self.box.window()
            for cls, name in ((QtWidgets.QGroupBox, "groupBoxDirection"),
                              (QtWidgets.QCheckBox, "checkBoxAlongDirection")):
                w = view.findChild(cls, name)
                if w is not None and _alive(w) and not w.isHidden():
                    w.hide()
        except RuntimeError as _fw_err:
            _fw_log("extrudepm.py:389", _fw_err)

    def start(self):
        if not self.waiting():
            # as if picked in FreeCAD's list: its panel acts on the user's choice (activated)
            self.combo.setCurrentIndex(1)
            self.combo.activated.emit(1)        # FreeCAD waits for the reference pick
        self.sync()

    def clear(self):
        if _alive(self.combo) and self.combo.currentIndex() != 0:
            self.combo.setCurrentIndex(0)
            self.combo.activated.emit(0)
        self.sync()

    def _menu(self, pos):
        menu = QtWidgets.QMenu(self.box)
        menu.addAction("Clear Selections", self.clear)
        menu.exec(self.box.mapToGlobal(pos))

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        try:
            t = event.type()
            if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self.start()
                return False
            if t == QtCore.QEvent.KeyPress and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                self.clear()
                return True
        except RuntimeError as _fw_err:
            _fw_log("extrudepm.py:421", _fw_err)
        return False


def arrange(view):
    ""


    try:
        if not _alive(view):
            return
        length = view.findChild(QtWidgets.QAbstractSpinBox, "lengthEdit")
        if length is None:
            return
        direction = view.findChild(QtWidgets.QGroupBox, "groupBox")
        merge = view.findChild(QtWidgets.QCheckBox, "SWStyle_MergeResult")
        end = view.findChild(QtWidgets.QComboBox, "SWStyle_EndCondition")
        if direction is not None and end is not None and direction.parentWidget() is end.parentWidget():
            _move_after(end, direction)
        if merge is not None:
            holder = merge if merge.parentWidget() is length.parentWidget() else merge.parentWidget()
            if holder is not None and holder.parentWidget() is length.parentWidget():
                _move_after(length, holder)
        _split_from(view, length)
        _flip_side(view, length)
        combo = view.findChild(QtWidgets.QComboBox, "directionCB")
        if combo is not None and not combo.property("swstyle_pick"):
            combo.setProperty("swstyle_pick", True)
            _picks[:] = [p for p in _picks if _alive(p.box)]
            _picks.append(DirectionPick(view, combo))
        section_header(view.findChild(QtWidgets.QCheckBox, "SWStyle_Direction2"))
        section_header(view.findChild(QtWidgets.QCheckBox, "SWStyle_ThinFeatureOn"))
    except RuntimeError as _fw_err:
        _fw_log("extrudepm.py:454", _fw_err)


def _editing_type():
    try:
        edit = Gui.ActiveDocument.getInEdit()
        return editobj.type_id(edit) if edit is not None else None
    except Exception:
        return None


def _flip_side(view, length):
    ""


    if _editing_type() not in ("PartDesign::Pocket", "PartDesign::Groove") or \
            view.findChild(QtWidgets.QCheckBox, "SWStyle_FlipSideToCut"):
        return
    from . import flipside
    try:
        pocket = Gui.ActiveDocument.getInEdit().Object
    except Exception:
        return
    box = QtWidgets.QCheckBox("Flip side to cut", length.parentWidget())
    box.setObjectName("SWStyle_FlipSideToCut")
    box.setChecked(flipside.is_flipped(pocket))

    def toggled(on, pocket=pocket):
        try:
            if flipside.set_flipped(pocket, on):
                pocket.Document.recompute()
        except Exception as error:
            App.Console.PrintError("FreeCAD: Flip side to cut: %s\n" % error)
            box.blockSignals(True)
            box.setChecked(flipside.is_flipped(pocket))
            box.blockSignals(False)
    box.toggled.connect(toggled)
    _place_after(length, box)
    # FreeCAD's Cancel on an edit does not undo the profile change: put it back as it was
    was = flipside.is_flipped(pocket)
    doc_name, name = pocket.Document.Name, pocket.Name

    def cancelled(*args):
        try:
            obj = App.getDocument(doc_name).getObject(name)
        except Exception:
            obj = None
        if obj is None:
            return          # a new cut cancelled: FreeCAD's undo took the helper with it
        try:
            if flipside.set_flipped(obj, was):
                obj.Document.recompute()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Flip side to cut on Cancel: %s\n" % error)

    def hook():
        for bb in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox):
            b = bb.button(QtWidgets.QDialogButtonBox.Cancel)
            if b is not None and bb.window() is Gui.getMainWindow() and not b.property("swstyle_flip_hook"):
                b.setProperty("swstyle_flip_hook", True)
                # pressed: clicked comes after FreeCAD has already deleted the panel
                b.pressed.connect(lambda *a: QtCore.QTimer.singleShot(300, cancelled))
    QtCore.QTimer.singleShot(0, hook)


class DraftRow(QtCore.QObject):
    """[Draft On/Off] [angle]  /  Draft outward, driving FreeCAD's taper field."""

    def __init__(self, view, taper, label, n):
        super().__init__(taper)
        self.taper = taper
        self.n = n
        self.box = QtWidgets.QWidget(taper.parentWidget())
        self.box.setObjectName("SWStyle_Draft%d" % n)
        lay = QtWidgets.QGridLayout(self.box)
        lay.setContentsMargins(0, 0, 0, 0)
        self.on = QtWidgets.QToolButton(self.box)
        self.on.setObjectName("SWStyle_DraftOnOff%d" % n)
        self.on.setCheckable(True)
        self.on.setToolTip("Draft On/Off")
        from . import icons
        icon = icons.family("FEATURES_DRAFT")
        if icon.isNull():
            self.on.setText("Draft")
        else:
            self.on.setIcon(icon)
        self.angle = QtWidgets.QDoubleSpinBox(self.box)
        self.angle.setObjectName("SWStyle_DraftAngle%d" % n)
        self.angle.setRange(0.0, 89.99)
        self.angle.setDecimals(2)
        self.angle.setSuffix("°")
        self.angle.setKeyboardTracking(False)
        self.angle.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.outward = QtWidgets.QCheckBox("Draft outward", self.box)
        self.outward.setObjectName("SWStyle_DraftOutward%d" % n)
        lay.addWidget(self.on, 0, 0, QtCore.Qt.AlignLeft)     # at the left of the draft row (look audit Z2)
        lay.addWidget(self.angle, 0, 1)
        lay.setColumnStretch(1, 1)
        lay.addWidget(self.outward, 1, 1)
        value = self._native()
        self.on.setChecked(abs(value) > 1e-9)
        self.angle.setValue(abs(value) if abs(value) > 1e-9 else 1.0)
        self.outward.setChecked(value > 1e-9)
        self._enable()
        self.on.toggled.connect(self._changed)
        self.angle.valueChanged.connect(self._changed)
        self.outward.toggled.connect(self._changed)
        _place_after(taper, self.box)
        self.label = label
        self.tidy()

    def tidy(self):
        """FreeCAD shows its taper field again whenever its mode changes: keep it hidden, and
        show Direction 2's row only with Direction 2."""
        if not (_alive(self.taper) and _alive(self.box)):
            return
        for w in (self.taper, self.label):
            if w is not None and _alive(w) and not w.isHidden():
                w.hide()
        feat = _edited()
        shown = self.n == 1 or (feat is not None and getattr(feat, "SideType", "") == "Two sides")
        pmfields.set_shown(self.box, shown)

    def _native(self):
        try:
            return float(self.taper.property("rawValue"))
        except Exception:
            return 0.0

    def _enable(self):
        # NO DEAD CONTROLS: with draft off the angle and Draft outward are not shown (not greyed);
        # the On/Off button stays at the left of the row
        on = self.on.isChecked()
        for w in (self.angle, self.outward):
            w.setEnabled(True)
            pmfields.set_shown(w, on)

    def _changed(self, *args):
        self._enable()
        if not _alive(self.taper):
            return
        a = self.angle.value() if self.on.isChecked() else 0.0
        self.taper.setProperty("rawValue", a if self.outward.isChecked() else -a)


class ReverseButton(QtCore.QObject):
    ""

    def __init__(self, view, reversed_box, end):
        super().__init__(reversed_box)
        self.box = reversed_box
        b = QtWidgets.QToolButton(end.parentWidget())
        b.setObjectName("SWStyle_ReverseDirection")
        b.setCheckable(True)
        b.setToolTip("Reverse Direction")
        b.setIcon(pmvalues.reverse_icon())
        b.setIconSize(QtCore.QSize(16, 16))
        b.setChecked(reversed_box.isChecked())
        b.toggled.connect(lambda on: reversed_box.setChecked(on))
        reversed_box.toggled.connect(lambda on: _alive(b) and b.isChecked() != on and b.setChecked(on))
        lay, index = _grid_of(end)
        if isinstance(lay, QtWidgets.QGridLayout):
            r, c, rs, cs = lay.getItemPosition(index)
            label = pmfields.cell_widget(lay, r, 0)
            if label is not None and label is not end:
                label.hide()
                lay.addWidget(b, r, 0, 1, 1, QtCore.Qt.AlignLeft)
        elif isinstance(lay, QtWidgets.QBoxLayout):
            # Revolve: a row "label | list": the button takes the label's place
            for i in range(lay.count()):
                w = pmfields.sub_widget(lay, i)
                if isinstance(w, QtWidgets.QLabel):
                    w.hide()
                    break
            lay.insertWidget(0, b)
        reversed_box.hide()
        self.button = b


def _hide_native_extras(view):
    for name in ("checkBoxUpdateView",):
        w = view.findChild(QtWidgets.QCheckBox, name)
        if w is not None:
            if not w.isChecked():
                w.setChecked(True)
            w.hide()
    overlay = view.findChild(QtWidgets.QCheckBox, "showTransparentPreviewCheckBox")
    if overlay is not None and overlay.isVisible():
        overlay.hide()
    final = view.findChild(QtWidgets.QCheckBox, "showFinalCheckBox")
    if final is not None:

        box = final
        while box is not None and not box.inherits("QSint::ActionGroup"):
            box = box.parentWidget()
        if box is not None:
            box.hide()


# --------------------------------------------------------------------------- the drag arrows
def _profile_centre(feature):
    sketch = feature.Profile[0] if isinstance(feature.Profile, (list, tuple)) else feature.Profile
    if sketch is None:
        return None, None
    try:
        shape = sketch.Shape
        import Part
        try:
            face = Part.Face(Part.Wire(shape.Wires[0])) if shape.Wires else None
        except Exception:
            face = None
        centre = face.CenterOfMass if face is not None else shape.BoundBox.Center
    except Exception:
        return None, None
    normal = sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
    return App.Vector(centre), normal


class PMArrow(instant3d._Instant3D):
    """One drag arrow (Direction 1 or 2) on the feature being edited; dragging sets the panel's
    Depth field, so FreeCAD's panel stays in charge of the feature and the Undo step."""

    def __init__(self, view, side):
        super().__init__()
        self.pm_view = view
        self.side = side

    def spin(self):
        name = "lengthEdit" if self.side == 1 else "lengthEdit2"
        w = self.pm_view.findChild(QtWidgets.QAbstractSpinBox, name) if _alive(self.pm_view) else None
        return w if w is not None and _alive(w) else None

    def poll(self):
        if self.drag is not None:
            return
        feat = _edited()
        spin = self.spin()
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None
        if feat is None or feat.TypeId not in TYPES or spin is None or not spin.isVisible() or view is None \
                or not hasattr(view, "getPoint"):
            self.clear()
            return
        centre, normal = _profile_centre(feat)
        if centre is None:
            self.clear()
            return
        mode = getattr(feat, "SideType", "One side")
        kind = feat.Type if self.side == 1 else getattr(feat, "Type2", "Length")
        if kind not in ("Length", "Dimension") or (self.side == 2 and mode != "Two sides"):
            self.clear()
            return
        out = normal * (1 if feat.TypeId == "PartDesign::Pad" else -1)
        if feat.Reversed:
            out = out * -1
        if self.side == 2:
            out = out * -1
        factor = 1.0
        prop = "Length" if self.side == 1 else "Length2"
        value = getattr(feat, prop).Value
        if mode == "Symmetric":
            factor = 2.0
        base = centre + out * (value / factor)
        length = self._arrow_mm(view, base)
        key = (feat.Name, self.side, tuple(round(x, 6) for x in base), tuple(round(x, 6) for x in out),
               round(length, 4), value, id(view))
        if key == self.key:
            return
        self.clear()
        self.target = (feat, prop, base, out, factor)
        self.length = length
        self.key = key
        self._draw(view)
        if self.parts is not None:
            self.parts[1].diffuseColor.setValue(*ARROW_GREY)

    def _set_hover(self, on):
        if self.parts is None or on == self.hover:
            return
        self.hover = on
        self.parts[1].diffuseColor.setValue(*(instant3d.HOVER if on else ARROW_GREY))

    def press(self, pos):
        feat, prop, base, direction, factor = self.target
        t0 = instant3d._ray_param(self.view, pos, base, direction)
        if t0 is None:
            return False
        v0 = getattr(feat, prop).Value
        self.drag = {"t0": t0, "v0": v0, "doc": feat.Document, "shift": 0.0, "value": None,
                     "snapped": False, "made": None, "mid": False}
        self._ruler_start()
        _hook(self)
        self._set_hover(True)
        self._show_value(v0)
        return True

    def _apply(self):
        if self.drag is None or self.drag["value"] is None:
            return
        spin = self.spin()
        if spin is not None:
            spin.setProperty("rawValue", float(self.drag["value"]))

    def release(self):
        if self.drag is None:
            return
        if self.recompute_timer is not None:
            self.recompute_timer.stop()
        self._apply()
        self._ruler_clear()
        self.drag = None
        self.key = None
        self._show_value_clear()
        _unhook(self)

    def cancel(self):
        if self.drag is None:
            return
        if self.recompute_timer is not None:
            self.recompute_timer.stop()
        spin = self.spin()
        if spin is not None:
            spin.setProperty("rawValue", float(self.drag["v0"]))
        self._ruler_clear()
        self.drag = None
        self.key = None
        self.swallow = True
        if self.parts is not None:
            self.parts[2].string.setValue("")
        # the release of the held button still comes here (swallow): unhooked on the next press
        # or when the page closes


def _hook(arrow):
    """The drag's mouse and keys through the add-on's one event dispatcher (events.py), as
    Instant3D does; an older tree without it gets the application filter of before."""
    try:
        from . import events
        events.register("extrudepm-%d" % id(arrow), instant3d.DRAG_EVENTS, arrow.filter.eventFilter)
        return
    except Exception as _fw_err:
        _fw_log("extrudepm.py:791", _fw_err)
    QtWidgets.QApplication.instance().installEventFilter(arrow.filter)


def _unhook(arrow):
    try:
        from . import events
        if events.unregister("extrudepm-%d" % id(arrow)):
            return
    except Exception as _fw_err:
        _fw_log("extrudepm.py:801", _fw_err)
    try:
        QtWidgets.QApplication.instance().removeEventFilter(arrow.filter)
    except Exception as _fw_err:
        _fw_log("extrudepm.py:805", _fw_err)


class Arrows(QtCore.QObject):
    """Both arrows for one open panel; they go with the panel. Also keeps the rows tidy."""

    def __init__(self, view, owner, rows=()):
        super().__init__(owner)
        self.view = view
        self.rows = list(rows)
        self.tidy_timer = QtCore.QTimer(self)
        self.tidy_timer.timeout.connect(self.tidy)
        self.tidy_timer.start(150)
        self.arrows = [PMArrow(view, 1), PMArrow(view, 2)]
        self.gizmos = App.ParamGet(GIZMOS)
        self.had = self.gizmos.GetBool("EnableGizmos", True)
        if self.had:
            self.gizmos.SetBool("EnableGizmos", False)
        for a in self.arrows:
            a.start()
        owner.destroyed.connect(self.stop)

    def tidy(self):
        for r in self.rows:
            r.tidy()
        if _alive(self.view):
            label = self.view.findChild(QtWidgets.QLabel, "side1Label")
            if label is not None and not label.isHidden():
                label.hide()
            _hide_native_extras(self.view)

    def stop(self, *args):
        try:
            self.tidy_timer.stop()
        except Exception as _fw_err:
            _fw_log("extrudepm.py:840", _fw_err)
        for a in self.arrows:
            try:
                _unhook(a)
                a.stop()
            except Exception as _fw_err:
                _fw_log("extrudepm.py:846", _fw_err)
        if self.had:
            self.gizmos.SetBool("EnableGizmos", True)


_arrows = []


def startup():
    ""

    try:
        from . import flipside
        flipside.install()      # flipped cuts follow their sketches in parts opened later
    except Exception as _fw_err:
        _fw_log("extrudepm.py:861", _fw_err)
    p = App.ParamGet(GIZMOS)
    ours = App.ParamGet(instant3d.paths.PARAM_PATH + "/Extrude")
    if not ours.GetBool("GizmosTaken", False):
        ours.SetBool("GizmosWere", p.GetBool("EnableGizmos", True))
        ours.SetBool("GizmosTaken", True)
    p.SetBool("EnableGizmos", False)
    from . import revolvepm
    revolvepm.startup()
    try:
        from . import pmfields
        pmfields.watch_axes()       # stale profile-axis references in saved files repair themselves
    except Exception as _fw_err:
        _fw_log("extrudepm.py:874", _fw_err)

def restore():
    ours = App.ParamGet(instant3d.paths.PARAM_PATH + "/Extrude")
    if ours.GetBool("GizmosTaken", False):
        App.ParamGet(GIZMOS).SetBool("EnableGizmos", ours.GetBool("GizmosWere", True))
        ours.SetBool("GizmosTaken", False)


def _looks_flat(feat):
    """True when the 3D view looks straight at the feature's sketch (as after Exit Sketch)."""
    try:
        profile = feat.Profile[0] if isinstance(feat.Profile, (list, tuple)) else feat.Profile
        normal = profile.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
        look = App.Vector(*Gui.ActiveDocument.ActiveView.getViewDirection())
        return abs(normal.dot(look)) > 0.999
    except Exception:
        return False


def _profile_in_view(feat):
    """True when the whole profile sketch shows in the 3D view."""
    try:
        profile = feat.Profile[0] if isinstance(feat.Profile, (list, tuple)) else feat.Profile
        box = profile.Shape.BoundBox
        if not box.isValid():
            return True
        view = Gui.ActiveDocument.ActiveView
        w, h = view.getSize()
        for x in (box.XMin, box.XMax):
            for y in (box.YMin, box.YMax):
                for z in (box.ZMin, box.ZMax):
                    px, py = view.getPointOnViewport(App.Vector(x, y, z))
                    if not (0 <= px <= w and 0 <= py <= h):
                        return False
        return True
    except Exception:
        return True


def frame_profile(feat):
    ""

    def go():
        if _edited() is feat and not _profile_in_view(feat):
            Gui.SendMsgToActiveView("ViewFit")
    QtCore.QTimer.singleShot(700, go)


def turn_trimetric(feat):
    ""

    def go():
        if _edited() is feat and _looks_flat(feat):
            from . import newdoc
            newdoc._trimetric()
    if _looks_flat(feat):
        QtCore.QTimer.singleShot(300, go)


def install(view):
    feat = _edited()
    try:
        from . import configedits          # a depth typed here goes into the shown configuration's cell
        configedits.install()
        configedits.arm(view, feat)
    except Exception as _fw_err:
        _fw_log("extrudepm.py:configedits", _fw_err)
    if feat is not None and feat.TypeId in ("PartDesign::Revolution", "PartDesign::Groove"):
        from . import revolvepm
        revolvepm.install(view)
        return
    if feat is not None and feat.TypeId.startswith(("PartDesign::AdditivePipe", "PartDesign::SubtractivePipe",
                                                    "PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft")):
        from . import sweeploftpm
        sweeploftpm.install(view)
        return
    if feat is None or feat.TypeId not in TYPES:
        return
    try:
        from . import featuremenu
        featuremenu.install()
    except Exception as _fw_err:
        _fw_log("extrudepm.py:951", _fw_err)
    end = view.findChild(QtWidgets.QComboBox, "SWStyle_EndCondition")
    length = view.findChild(QtWidgets.QAbstractSpinBox, "lengthEdit")
    if length is None or length.property(DONE):
        return
    length.setProperty(DONE, True)
    try:
        from . import pmfields
        pmfields.watch_axes()
        if pmfields.repair_axis(feat):
            feat.Document.recompute()
    except Exception as _fw_err:
        _fw_log("extrudepm.py:963", _fw_err)
    turn_trimetric(feat)
    frame_profile(feat)
    rows = []
    for n, (taper, label) in enumerate((("taperEdit", "labelTaperAngle"), ("taperEdit2", "labelTaperAngle2")), 1):
        t = view.findChild(QtWidgets.QAbstractSpinBox, taper)
        if t is not None:
            rows.append(DraftRow(view, t, view.findChild(QtWidgets.QLabel, label), n))
    rev = view.findChild(QtWidgets.QCheckBox, "checkBoxReversed")
    if rev is not None and end is not None:
        ReverseButton(view, rev, end)
    _hide_native_extras(view)
    _arrows.append(Arrows(view, length, rows))
    # Merge result and Thin Feature come from other modules on the same refresh: after them
    QtCore.QTimer.singleShot(0, lambda: arrange(view))
    QtCore.QTimer.singleShot(400, lambda: arrange(view))
