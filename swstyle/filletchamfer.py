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

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import icons, paths

PARAMS = paths.PARAM_PATH + "/FilletChamfer"
FILLET_ROW = "SWStyle_FilletType"
CHAMFER_ROW = "SWStyle_ChamferType"


FILLET_TYPES = (
    ("Constant Size", "FEATURES_FILLET", "PartDesign::Fillet", "PartDesign_Fillet"),
    ("Variable Size", "FEATURES_VARIABLE_FILLET", "VariableSizeFillet", "SWStyle_VariableFillet"),
    ("Face Fillet", "FEATURES_FACE_FILLET", "FaceFillet", "SWStyle_FaceFillet"),
    ("Full Round", "FEATURES_FULL_ROUND_FILLET", "FullRoundFillet", "SWStyle_FullRoundFillet"),
)
EDGE_TYPES = ("Constant Size", "Variable Size")       # the types that take the picked edges
CHAMFER_TYPES = ("Angle Distance", "Distance Distance")
FREECAD_CHAMFER = ("Equal distance", "Two distances", "Distance and Angle")

_fresh = {}       # "doc.name" -> time made; a new feature gets the last values when its panel opens
_observer = None
_live = {}        # row name -> the row shown now


def params():
    return App.ParamGet(PARAMS)


def last_values():
    return params().GetBool("LastValues", True)


# ------------------------------------------------------------------ which feature
def _edited():
    try:
        vp = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
        return vp.Object if vp is not None else None
    except Exception:
        return None


def fillet_type(obj):
    """The Fillet Type text of a fillet feature, or None."""
    kind = getattr(obj, "SWStyleKind", None) if obj.TypeId != "PartDesign::Fillet" else obj.TypeId
    for text, _icon, key, _cmd in FILLET_TYPES:
        if key == kind:
            return text
    return None


def _key(obj):
    return obj.Document.Name + "." + obj.Name


def _is_fresh(obj):
    made = _fresh.get(_key(obj))
    return made is not None and time.time() - made < 30.0


def not_fresh(obj):
    """obj is being edited, not made: its panel keeps the feature's own values."""
    try:
        _fresh.pop(_key(obj), None)
    except Exception:
        pass


# ------------------------------------------------------------------ the panel
def _form_of(view):
    """The form of the panel's first box (FreeCAD's own parameters box)."""
    boxes = [w for w in view.findChildren(QtWidgets.QWidget) if w.inherits("QSint::ActionGroup")]
    if not boxes:
        return None
    target = boxes[0]
    forms = [w for w in target.findChildren(QtWidgets.QWidget) if w.layout() is not None
             and w.parentWidget() is not None and w.parentWidget().parentWidget() is target]
    return forms[0] if forms else None


def _on_top(form, widget):
    lay = form.layout()
    if isinstance(lay, QtWidgets.QBoxLayout):
        lay.insertWidget(0, widget)
    elif isinstance(lay, QtWidgets.QGridLayout):
        items = []
        while lay.count():
            index = lay.count() - 1
            r, c, rs, cs = lay.getItemPosition(index)
            items.append((lay.takeAt(index), r, c, rs, cs))
        lay.addWidget(widget, 0, 0, 1, max(2, lay.columnCount()))
        for item, r, c, rs, cs in items:
            if item.widget() is not None:
                lay.addWidget(item.widget(), r + 1, c, rs, cs)
            elif item.layout() is not None:
                lay.addLayout(item.layout(), r + 1, c, rs, cs)
    elif isinstance(lay, QtWidgets.QFormLayout):
        lay.insertRow(0, widget)
    else:
        lay.addWidget(widget)


def _header(parent, text):
    label = QtWidgets.QLabel(text, parent)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def _type_button(parent, name, text, family):
    button = QtWidgets.QToolButton(parent)
    button.setObjectName(name)
    button.setCheckable(True)
    button.setAutoRaise(True)
    button.setText(text)
    button.setToolTip(text)
    icon = icons.family(family) if family else QtGui.QIcon()
    if not icon.isNull():
        button.setIcon(icon)
        button.setIconSize(QtCore.QSize(20, 20))
        button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    else:
        button.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
    button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    return button


def _spins(view):
    return [w for w in view.findChildren(QtWidgets.QAbstractSpinBox) if w.inherits("Gui::QuantitySpinBox")]


def _spin(view, name):
    for w in view.findChildren(QtWidgets.QAbstractSpinBox, name):
        return w
    return None


def _set_spin(spin, value):
    if spin is not None:
        spin.setProperty("rawValue", float(value))


def _native_combo(view):
    """FreeCAD's own chamfer type list (its three entries, in FreeCAD's order)."""
    for combo in view.findChildren(QtWidgets.QComboBox, "chamferType"):
        return combo
    for combo in view.findChildren(QtWidgets.QComboBox):
        if [combo.itemText(i).lower() for i in range(combo.count())] == [t.lower() for t in FREECAD_CHAMFER]:
            return combo
    return None


def _cancel_button(view):
    for box in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox):
        button = box.button(QtWidgets.QDialogButtonBox.Cancel)
        if button is not None and box.window() is Gui.getMainWindow():
            return button
    return None


class FilletRow(QtCore.QObject):
    """Fillet Type: Constant Size, Variable Size, Face Fillet, Full Round."""

    def __init__(self, view, feature, current):
        super().__init__(view)
        self.view = view
        self.doc = feature.Document.Name
        self.name = feature.Name
        self.box = QtWidgets.QWidget()
        self.box.setObjectName(FILLET_ROW)
        lay = QtWidgets.QVBoxLayout(self.box)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.addWidget(_header(self.box, "Fillet Type"))
        grid = QtWidgets.QGridLayout()      # two by two: four names fit the panel's width
        grid.setSpacing(2)
        self.group = QtWidgets.QButtonGroup(self.box)
        for index, (text, family, _key, command) in enumerate(FILLET_TYPES):
            button = _type_button(self.box, FILLET_ROW + "_" + text.replace(" ", ""), text, family)
            button.setChecked(text == current)
            self.group.addButton(button)
            grid.addWidget(button, index // 2, index % 2)
            if text != current:
                button.clicked.connect(lambda checked=False, c=command, t=text: self.switch(c, t))
        lay.addLayout(grid)

    def feature(self):
        try:
            return App.getDocument(self.doc).getObject(self.name)
        except Exception:
            return None

    def picked_edges(self):
        """[(object, "EdgeN")] the fillet being made has, for a type that takes edges."""
        obj = self.feature()
        if obj is None:
            return []
        picks = []
        if obj.TypeId == "PartDesign::Fillet":
            base = obj.Base
            if base:
                picks = [(base[0], sub) for sub in base[1] if sub.startswith("Edge")]
        else:
            for link in getattr(obj, "Edges", None) or []:
                holder, subs = link[0], link[1]
                picks += [(holder, sub) for sub in subs if sub.startswith("Edge")]
        return picks

    def switch(self, command, text):
        picks = self.picked_edges() if text in EDGE_TYPES else []
        picks = [(o.Document.Name, o.Name, sub) for o, sub in picks]
        cancel = _cancel_button(self.view)
        if cancel is None:
            return
        cancel.click()

        def start():
            if Gui.Control.activeDialog():
                return
            Gui.Selection.clearSelection()
            for doc, name, sub in picks:
                try:
                    Gui.Selection.addSelection(doc, name, sub)
                except Exception as _fw_err:
                    _fw_log("filletchamfer.py:256", _fw_err)
            run(command)
        QtCore.QTimer.singleShot(150, start)


def run(command):
    """Start a fillet type the way its ribbon button does."""
    try:
        from . import featureflow
        if featureflow.run(command):
            return
    except Exception as _fw_err:
        _fw_log("filletchamfer.py:268", _fw_err)
    Gui.runCommand(command, 0)


class ChamferRow(QtCore.QObject):
    """Chamfer Type: Angle Distance, Distance Distance (Symmetric / Asymmetric)."""

    def __init__(self, view, feature):
        super().__init__(view)
        self.view = view
        self.box = QtWidgets.QWidget()
        self.box.setObjectName(CHAMFER_ROW)
        lay = QtWidgets.QVBoxLayout(self.box)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.addWidget(_header(self.box, "Chamfer Type"))
        row = QtWidgets.QHBoxLayout()
        self.group = QtWidgets.QButtonGroup(self.box)
        self.buttons = {}
        for text in CHAMFER_TYPES:
            button = _type_button(self.box, CHAMFER_ROW + "_" + text.replace(" ", ""), text, None)
            self.group.addButton(button)
            self.buttons[text] = button
            row.addWidget(button)
            button.clicked.connect(self.changed)
        lay.addLayout(row)
        self.symmetric = QtWidgets.QComboBox(self.box)
        self.symmetric.setObjectName(CHAMFER_ROW + "_Symmetric")
        self.symmetric.addItems(["Symmetric", "Asymmetric"])
        self.symmetric.activated.connect(self.changed)
        lay.addWidget(self.symmetric)
        kind = feature.ChamferType
        self.buttons["Angle Distance" if kind == "Distance and Angle" else "Distance Distance"].setChecked(True)
        self.symmetric.setCurrentIndex(1 if kind == "Two distances" else 0)
        self.symmetric.setVisible(kind != "Distance and Angle")
        native = _native_combo(view)
        if native is not None:
            # Our row replaces FreeCAD's type list (it still does the work underneath).
            native.hide()
            label = _label_for(native)
            if label is not None:
                label.hide()

    def wanted(self):
        if self.buttons["Angle Distance"].isChecked():
            return "Distance and Angle"
        return "Two distances" if self.symmetric.currentIndex() == 1 else "Equal distance"

    def changed(self, *args):
        kind = self.wanted()
        self.symmetric.setVisible(kind != "Distance and Angle")
        native = _native_combo(self.view)
        if native is not None and native.currentIndex() != FREECAD_CHAMFER.index(kind):
            native.setCurrentIndex(FREECAD_CHAMFER.index(kind))
            native.activated.emit(native.currentIndex())
        params().SetString("ChamferType", kind)


def _label_for(widget):
    parent = widget.parentWidget()
    if parent is None:
        return None
    lay = parent.layout()
    if isinstance(lay, QtWidgets.QGridLayout):
        index = lay.indexOf(widget)
        if index >= 0:
            r, c, rs, cs = lay.getItemPosition(index)
            for col in range(lay.columnCount()):
                item = lay.itemAtPosition(r, col)
                if item is not None and isinstance(item.widget(), QtWidgets.QLabel):
                    return item.widget()
    if isinstance(lay, QtWidgets.QFormLayout):
        return lay.labelForField(widget)
    if isinstance(lay, QtWidgets.QBoxLayout):
        index = lay.indexOf(widget)
        if index > 0 and isinstance(lay.itemAt(index - 1).widget(), QtWidgets.QLabel):
            return lay.itemAt(index - 1).widget()
    return None


# ------------------------------------------------------------------ last values
def _start_values(view, feature):
    ""
    _fresh.pop(_key(feature), None)
    if not last_values():
        return
    p = params()
    if feature.TypeId == "PartDesign::Fillet":
        spins = _spins(view)
        _set_spin(_spin(view, "filletRadius") or (spins[0] if spins else None), p.GetFloat("FilletRadius", 10.0))
    elif feature.TypeId == "PartDesign::Chamfer":
        # Read everything first: the type change below is remembered as it happens.
        kind = p.GetString("ChamferType", "Distance and Angle")
        values = (("chamferSize", p.GetFloat("ChamferSize", 10.0)), ("chamferSize2", p.GetFloat("ChamferSize2", 10.0)),
                  ("chamferAngle", p.GetFloat("ChamferAngle", 45.0)))
        native = _native_combo(view)
        if native is not None and kind in FREECAD_CHAMFER and native.currentIndex() != FREECAD_CHAMFER.index(kind):
            native.setCurrentIndex(FREECAD_CHAMFER.index(kind))
            native.activated.emit(native.currentIndex())

        def sizes():
            # After FreeCAD's panel has taken the type change (it re-reads its fields then).
            for name, value in values:
                _set_spin(_spin(view, name), value)
        QtCore.QTimer.singleShot(0, sizes)


def remember(feature):
    p = params()
    try:
        if feature.TypeId == "PartDesign::Fillet":
            p.SetFloat("FilletRadius", feature.Radius.Value)
        elif feature.TypeId == "PartDesign::Chamfer":
            p.SetString("ChamferType", feature.ChamferType)
            p.SetFloat("ChamferSize", feature.Size.Value)
            p.SetFloat("ChamferSize2", feature.Size2.Value)
            p.SetFloat("ChamferAngle", feature.Angle.Value)
    except Exception as _fw_err:
        _fw_log("filletchamfer.py:385", _fw_err)


class _DocObserver:
    def slotCreatedObject(self, obj):
        try:
            if obj.Document.Restoring:
                return
        except Exception:
            return
        if obj.TypeId in ("PartDesign::Fillet", "PartDesign::Chamfer") or obj.TypeId.endswith("Python"):
            now = time.time()
            for key in [k for k, t in _fresh.items() if now - t > 60.0]:
                del _fresh[key]
            _fresh[_key(obj)] = now

    def slotChangedObject(self, obj, prop):
        if prop not in ("Radius", "Size", "Size2", "Angle", "ChamferType"):
            return
        if obj.TypeId in ("PartDesign::Fillet", "PartDesign::Chamfer") and _edited() is obj \
                and "SWBreakPicks" not in obj.PropertiesList:
            remember(obj)


def install_observer():
    global _observer
    if _observer is None:
        _observer = _DocObserver()
        App.addDocumentObserver(_observer)


# ------------------------------------------------------------------ hook
def install(view):
    """Adds the Fillet Type / Chamfer Type row to the panel being shown (idempotent; called on
    each refresh of the PropertyManager)."""
    feature = _edited()
    if feature is None or "SWBreakPicks" in feature.PropertiesList:     # a sheet metal Break-Corner
        return
    is_chamfer = feature.TypeId == "PartDesign::Chamfer"
    current = None if is_chamfer else fillet_type(feature)
    if not is_chamfer and current is None:
        return
    name = CHAMFER_ROW if is_chamfer else FILLET_ROW
    if view.findChild(QtWidgets.QWidget, name) is not None:
        return
    fresh = _is_fresh(feature)
    if not is_chamfer and not fresh:
        return              # an existing fillet keeps its type
    form = _form_of(view)
    if form is None:
        return
    if fresh:
        _start_values(view, feature)
    row = ChamferRow(view, feature) if is_chamfer else FilletRow(view, feature, current)
    _on_top(form, row.box)
    _live[name] = row
    row.box.destroyed.connect(lambda *a, n=name: _live.pop(n, None))
