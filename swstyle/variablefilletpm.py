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

from . import simplefeature as sf

HIDDEN = ("StartRadius", "EndRadius", "ControlPoints", "PointRadii", "PointPositions", "Transition")
TRANSITIONS = ("Smooth transition", "Straight transition")


def _numbers(text):
    from .directfeatures import _numbers as numbers
    try:
        return numbers(text)
    except Exception:
        return []


def _fmt(value):
    return ("%.4f" % value).rstrip("0").rstrip(".")


def rows_of(obj):
    """[(name, radius or None, position % or None)]: V1, P1..Pn, V2."""
    count = int(getattr(obj, "ControlPoints", 0) or 0)
    radii = _numbers(getattr(obj, "PointRadii", ""))
    where = _numbers(getattr(obj, "PointPositions", ""))
    if len(where) != count:
        where = [100.0 * (k + 1.0) / (count + 1.0) for k in range(count)]
    out = [("V1", float(obj.StartRadius), None)]
    for k in range(count):
        r = radii[k] if k < len(radii) and radii[k] > 0 else None
        out.append(("P%d" % (k + 1), r, where[k]))
    out.append(("V2", float(obj.EndRadius), None))
    return out


def write(obj, rows):
    """Store rows (as rows_of gives them) on the feature."""
    points = rows[1:-1]
    obj.StartRadius = rows[0][1] or 0.001
    obj.EndRadius = rows[-1][1] or 0.001
    obj.ControlPoints = len(points)
    obj.PointRadii = ", ".join(_fmt(r) if r else "0" for _n, r, _p in points)
    obj.PointPositions = ", ".join(_fmt(p) for _n, _r, p in points)


def set_instances(rows, count):
    """Number of instances: control points spread evenly again, radii kept where there were points."""
    old = rows[1:-1]
    points = []
    for k in range(count):
        r = old[k][1] if k < len(old) else None
        points.append(("P%d" % (k + 1), r, 100.0 * (k + 1.0) / (count + 1.0)))
    return [rows[0]] + points + [rows[-1]]


def _fw_retyped(spin):
    """True when the field's text is not what its value shows: a number typed and not taken yet.
    An untouched field is left alone (taking its rounded text again moved linked values: Flex's
    Radius 26.74 turned a typed Angle back to 89.99)."""
    try:
        return spin.text() != spin.prefix() + spin.textFromValue(spin.value()) + spin.suffix()
    except Exception:
        return True


class _StripHost:
    """What the selection toolbar (selectiontoolbar.Strip) works on: the part before the fillet, the
    picked edges' names on it, and a way to add a set of them to the box."""

    def __init__(self, panel):
        self.panel = panel
        self.items = []

    @property
    def base(self):
        return self.panel.obj.BaseFeature

    @property
    def overlay(self):
        return self.panel.overlay

    def update(self):
        self.panel.take_edges([n for n in self.items if n])
        self.items = []


class Panel(sf.Panel):
    def __init__(self, obj):
        super().__init__(obj)
        labels = {f.name: f.label for f in self.spec.fields}
        for name in HIDDEN:
            w = self.widgets.get(name)
            if w is None:
                continue
            for x in (w if isinstance(w, list) else [w]):
                x.setVisible(False)
                form = x.parentWidget().layout() if x.parentWidget() else None
                label = form.labelForField(x) if isinstance(form, QtWidgets.QFormLayout) else None
                if label is not None:
                    label.setVisible(False)
                elif x.parentWidget() is not None:
                    # a text field has its heading on a row of its own ("Control point radii" was left
                    # showing over nothing)
                    for heading in x.parentWidget().findChildren(QtWidgets.QLabel):
                        if heading.text() == labels.get(name):
                            heading.setVisible(False)
        self.rows = rows_of(obj)
        self.callouts = []
        self._items_extras()
        box = QtWidgets.QWidget()
        box.setWindowTitle("Variable Radius Parameters")
        lay = QtWidgets.QFormLayout(box)
        self.points = QtWidgets.QListWidget(box)
        self.points.setObjectName("SWVarFilletPoints")
        self.points.setToolTip("Vertices and control points of the edge: click one (Ctrl for more) to set its radius")
        self.points.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.points.setMaximumHeight(110)
        self.points.itemSelectionChanged.connect(self._row_picked)
        lay.addRow(self.points)
        self.radius = QtWidgets.QDoubleSpinBox(box)
        self.radius.setObjectName("SWVarFilletRadius")
        self.radius.setRange(0.001, 1e6)
        self.radius.setDecimals(3)
        self.radius.setSuffix(" mm")
        self.radius.setValue(self.rows[0][1] or 2.0)
        self.radius.setKeyboardTracking(False)      # taken when the typing ends (Enter, Tab, OK)
        self.radius.valueChanged.connect(self._radius_typed)
        lay.addRow("R", self.radius)
        self.position = QtWidgets.QDoubleSpinBox(box)
        self.position.setObjectName("SWVarFilletPosition")
        self.position.setRange(0.1, 99.9)
        self.position.setDecimals(1)
        self.position.setSuffix(" %")
        self.position.setKeyboardTracking(False)      # taken when the typing ends (Enter, Tab, OK)
        self.position.valueChanged.connect(self._position_typed)
        lay.addRow("P", self.position)
        buttons = QtWidgets.QHBoxLayout()
        self.set_unassigned = QtWidgets.QPushButton("Set Unassigned", box)
        self.set_unassigned.setObjectName("SWVarFilletSetUnassigned")
        self.set_unassigned.clicked.connect(lambda: self.set_rows_radius(False))
        self.set_all = QtWidgets.QPushButton("Set All", box)
        self.set_all.setObjectName("SWVarFilletSetAll")
        self.set_all.clicked.connect(lambda: self.set_rows_radius(True))
        buttons.addWidget(self.set_unassigned)
        buttons.addWidget(self.set_all)
        lay.addRow(buttons)
        self.instances = QtWidgets.QSpinBox(box)
        self.instances.setObjectName("SWVarFilletInstances")
        self.instances.setRange(0, 25)
        self.instances.setValue(len(self.rows) - 2)
        self.instances.setKeyboardTracking(False)      # taken when the typing ends (Enter, Tab, OK)
        self.instances.setToolTip("Number of instances: control points along each edge")
        self.instances.valueChanged.connect(self._instances_typed)
        lay.addRow("Number of instances", self.instances)
        self.transition = []
        group = QtWidgets.QButtonGroup(box)
        current = str(getattr(obj, "Transition", TRANSITIONS[0]))
        for text in TRANSITIONS:
            r = QtWidgets.QRadioButton(text, box)
            r.setObjectName("SWVarFillet" + text.split()[0])
            r.setChecked(text == current)
            group.addButton(r)
            r.toggled.connect(lambda on, t=text: on and self._transition(t))
            lay.addRow(r)
            self.transition.append(r)
        boxes = self.form if isinstance(self.form, list) else [self.form]
        boxes.insert(2 if getattr(self, "head", None) is not None else 1, box)    # after Items To Fillet
        self.form = boxes
        self._fill()
        if self.points.count():
            self.points.item(0).setSelected(True)


    # Fillet Type): the edge box with no heading of its own, Show selection toolbar, Full / Partial
    # / No preview. The settings are the Constant Size page's (FilletSelectionToolbar, FilletPreview).
    def _items_extras(self):
        from . import filletpm
        self.preview_buttons = []
        self.toolbar_box = None
        self.overlay = None
        self.strip = None
        self._base_shown = False
        self._edge_subs = self._base_subs()
        edges = self.widgets.get("Edges")
        heading = getattr(self, "headings", {}).get("Edges")
        if heading is not None:
            heading.hide()          # the group's title (Items To Fillet) names the box
        form = edges.parentWidget().layout() if edges is not None and edges.parentWidget() else None
        if not isinstance(form, QtWidgets.QFormLayout):
            return
        row = form.getWidgetPosition(edges)[0] + 1
        self.toolbar_box = QtWidgets.QCheckBox("Show selection toolbar")
        self.toolbar_box.setObjectName("SWVarFilletSelectionToolbar")
        self.toolbar_box.setToolTip("After an edge is picked, show buttons next to it that add its loop, "
                                    "its feature's edges, or all convex or concave edges")
        self.toolbar_box.setChecked(filletpm.params().GetBool("FilletSelectionToolbar", True))
        self.toolbar_box.toggled.connect(self._toolbar_toggled)
        form.insertRow(row, self.toolbar_box)
        group = QtWidgets.QButtonGroup(self.toolbar_box)
        chosen = filletpm.params().GetString("FilletPreview", filletpm.PREVIEWS[0])
        for k, text in enumerate(filletpm.PREVIEWS):
            r = QtWidgets.QRadioButton(text)
            r.setObjectName("SWVarFillet%s" % text.replace(" ", ""))
            r.setChecked(text == chosen)
            group.addButton(r)
            form.insertRow(row + 1 + k, r)
            self.preview_buttons.append(r)
            r.toggled.connect(lambda on, t=text: on and self._preview_changed(t))
        try:
            self.overlay = filletpm.Overlay()
            view = filletpm._view_widget()
            if view is not None:
                from . import selectiontoolbar
                self.strip = selectiontoolbar.Strip(_StripHost(self), view)
        except Exception as _fw_err:
            _fw_log("variablefilletpm.py:extras", _fw_err)

    def preview_mode(self):
        for b in getattr(self, "preview_buttons", None) or []:
            if b.isChecked():
                return b.text()
        return "Full preview"

    def _preview_changed(self, text):
        from . import filletpm
        filletpm.params().SetString("FilletPreview", text)
        self._preview()

    def _preview(self, on=None):
        """Full preview: the filleted part. No preview: the part as it was. Partial preview: the part
        as it was with the new faces of the first edge drawn over it (the Constant Size page's way)."""
        super()._preview(on)
        try:
            obj = self.obj
            base = getattr(obj, "BaseFeature", None)
            vobj = getattr(obj, "ViewObject", None)
            if vobj is None or base is None or getattr(base, "ViewObject", None) is None:
                return
            if on is not None:              # the page closes: the result shows as usual
                if self._base_shown:
                    base.ViewObject.Visibility = False
                    self._base_shown = False
                vobj.Visibility = bool(on)
                if self.overlay is not None:
                    self.overlay.show_preview([])
                return
            mode = self.preview_mode()
            full = mode == "Full preview" or "Invalid" in obj.State
            vobj.Visibility = full
            base.ViewObject.Visibility = not full
            self._base_shown = not full
            faces = []
            if mode == "Partial preview" and "Invalid" not in obj.State:
                from . import filletpm
                edge = self._edge()
                faces = filletpm.new_faces(base.Shape, obj.Shape)
                if edge is not None:
                    reach = max([r for _n, r, _p in self.rows if r] + [0.1]) * 1.5
                    faces = [f for f in faces if f.distToShape(edge)[0] < reach]
            if self.overlay is not None:
                self.overlay.show_preview(faces)
        except Exception as _fw_err:
            _fw_log("variablefilletpm.py:preview", _fw_err)

    def _base_subs(self):
        """The picked edges' names on the part before the fillet (the names the toolbar's sets use)."""
        base = getattr(self.obj, "BaseFeature", None)
        out = []
        for source, subs in getattr(self.obj, "Edges", None) or []:
            for s in (subs if isinstance(subs, (list, tuple)) else [subs]):
                if source is base and s and s not in out:
                    out.append(s)
        return out

    def _toolbar_toggled(self, on):
        from . import filletpm
        filletpm.params().SetBool("FilletSelectionToolbar", on)
        if self.strip is None:
            return
        subs = self._base_subs()
        if on and subs:
            self.strip.show_for(subs[-1])
        else:
            self.strip.close_strip()

    def _strip_after(self):
        ""
        before = getattr(self, "_edge_subs", [])
        now = self._base_subs()
        self._edge_subs = now
        if self.strip is None or now == before:
            return
        added = [s for s in now if s not in before]
        if self.toolbar_box is not None and self.toolbar_box.isChecked() and len(added) == 1 \
                and added[0].startswith("Edge"):
            self.strip.show_for(added[0])
        else:
            self.strip.close_strip()

    def take_edges(self, names):
        """The selection toolbar's set: its edges go in the box (on the part before the fillet)."""
        base = getattr(self.obj, "BaseFeature", None)
        if base is None:
            return
        pairs = []
        for source, subs in getattr(self.obj, "Edges", None) or []:
            for s in (subs if isinstance(subs, (list, tuple)) else [subs]):
                pairs.append((source, s))
        for n in names:
            if (base, n) not in pairs:
                pairs.append((base, n))
        merged = []
        for source, s in pairs:
            for k, (src, subs) in enumerate(merged):
                if src is source:
                    merged[k] = (src, subs + [s])
                    break
            else:
                merged.append((source, [s]))
        self.obj.Edges = [(src, tuple(subs)) for src, subs in merged]
        self._edge_subs = self._base_subs()
        self._store()

    # ---- rows
    def _fill(self):
        keep = [i.row() for i in self.points.selectedIndexes()]
        self.points.blockSignals(True)
        self.points.clear()

        self._listed = self._edge() is not None
        for name, r, p in (self.rows if self._listed else []):
            text = "%s   R %s" % (name, (_fmt(r) + " mm") if r else "Unassigned")
            if p is not None:
                text += "   P %s%%" % _fmt(p)
            self.points.addItem(text)
        for i in keep:
            if i < self.points.count():
                self.points.item(i).setSelected(True)
        self.points.blockSignals(False)
        self._callouts()

    def _show(self):
        super()._show()
        try:
            if getattr(self, "toolbar_box", None) is not None:
                self._strip_after()
        except Exception as _fw_err:
            _fw_log("variablefilletpm.py:strip", _fw_err)
        try:
            if getattr(self, "points", None) is not None and getattr(self, "_listed", None) != (self._edge() is not None):
                self._fill()            # the first edge picked (or the last one taken out)
                if self._listed and self.points.count() and not self.points.selectedIndexes():
                    self.points.item(0).setSelected(True)
        except Exception as _fw_err:
            _fw_log("variablefilletpm.py:show", _fw_err)

    def picked_rows(self):
        return sorted({i.row() for i in self.points.selectedIndexes()})

    def _row_picked(self):
        rows = self.picked_rows()
        if not rows:
            return
        name, r, p = self.rows[rows[-1]]
        self.radius.blockSignals(True)
        if r:
            self.radius.setValue(r)
        self.radius.blockSignals(False)
        self.position.blockSignals(True)
        self.position.setEnabled(p is not None)
        if p is not None:
            self.position.setValue(p)
        self.position.blockSignals(False)

    def _store(self):
        write(self.obj, self.rows)
        self.obj.Document.recompute()
        self._preview()
        self._show()
        self._fill()

    def set_radius(self, rows, value):
        for i in rows:
            name, _r, p = self.rows[i]
            self.rows[i] = (name, float(value), p)
        self._store()

    def _radius_typed(self, value):
        rows = self.picked_rows()
        if rows:
            self.set_radius(rows, value)

    def set_position(self, row, value):
        name, r, p = self.rows[row]
        if p is None:
            return
        self.rows[row] = (name, r, min(max(float(value), 0.1), 99.9))
        self._store()

    def _position_typed(self, value):
        rows = [i for i in self.picked_rows() if self.rows[i][2] is not None]
        if rows:
            self.set_position(rows[-1], value)

    def set_rows_radius(self, every):
        """Set Unassigned / Set All: the R value goes to the unassigned rows, or to all of them."""
        value = self.radius.value()
        self.rows = [(n, value if (every or not r) else r, p) for n, r, p in self.rows]
        self._store()

    def _instances_typed(self, count):
        self.rows = set_instances(self.rows, count)
        self._store()

    def _transition(self, text):
        self.obj.Transition = text
        self.obj.Document.recompute()
        self._preview()
        self._show()

    # ---- callouts on the model, one per row on the first edge
    def _edge(self):
        try:
            picked = sf.elements(self.obj, "Edges")
            base = self.obj.BaseFeature.Shape
            for _src, shape in picked:
                for e in ([shape] if shape.ShapeType == "Edge" else shape.Edges):
                    return e
        except Exception as _fw_err:
            _fw_log("variablefilletpm.py:249", _fw_err)
        return None

    def _callouts(self):
        from . import filletpm
        edge = self._edge()
        view = filletpm._view_widget()
        if edge is None or view is None:
            for c in self.callouts:
                c.hide()
            return
        while len(self.callouts) < len(self.rows):
            self.callouts.append(filletpm.Callout(self, view))
        for c in self.callouts[len(self.rows):]:
            c.anchor = None
            c.hide()
        turned = False      # V1 at the edge's far end (directfeatures.start_points)
        try:
            from . import directfeatures
            turned = directfeatures._starts_at_end(edge, (directfeatures.start_points(self.obj) or [None])[0])
        except Exception as _fw_err:
            _fw_log("variablefilletpm.py:v1", _fw_err)
        for i, ((name, r, p), c) in enumerate(zip(self.rows, self.callouts)):
            f = 0.0 if i == 0 else 1.0 if i == len(self.rows) - 1 else p / 100.0
            if turned:
                f = 1.0 - f
            point = edge.valueAt(edge.getParameterByLength(f * edge.Length))
            rows = [(name + " R", r or 0.0, "mm", lambda v, i=i: self.set_radius([i], v))]
            if p is not None:
                rows.append(("P", p, "%", lambda v, i=i: self.set_position(i, v)))
            c.set_rows(rows, point)

    def set_size(self, value):          # Callout.set() of a one-row callout
        rows = self.picked_rows() or [0]
        self.set_radius(rows, value)

    def accept(self):
        for spin in (self.radius, self.position, self.instances):
            try:
                if _fw_retyped(spin):
                    spin.interpretText()    # a number still being typed when OK is clicked counts
            except Exception as _fw_err:
                _fw_log("variablefilletpm.py:accept", _fw_err)
        return super().accept()

    def _close(self):
        for extra in (getattr(self, "strip", None), getattr(self, "overlay", None)):
            try:
                if extra is not None:
                    extra.remove()
            except Exception as _fw_err:
                _fw_log("variablefilletpm.py:close-extras", _fw_err)
        self.strip = None
        self.overlay = None
        for c in self.callouts:
            try:
                c.anchor = None
                c.timer.stop()
                c.hide()
                c.deleteLater()
            except Exception as _fw_err:
                _fw_log("variablefilletpm.py:285", _fw_err)
        self.callouts = []
        super()._close()
