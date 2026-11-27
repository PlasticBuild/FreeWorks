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

import json
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, wetrim
from . import pmboxes

COMMAND = "SWStyle_WEEndCap"
TITLE = "End Cap"
LABEL = "End cap"
GROUP = "End Cap"
DIRECTIONS = ("Outward", "Inward", "Internal")


class NeedsHollow(RuntimeError):
    """Internal picked on a solid member's end: an error on the End Cap itself, not a member rebuild."""
CORNERS = ("Chamfer", "Fillet")
HINT = "Select the end faces of structural members."
TOL = 1e-6


def _weicon(name):
    from . import weprofile
    return weprofile.icon(name)

def is_end_cap(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "EndCap"


def _load(text, default):
    try:
        return json.loads(text or "")
    except Exception:
        return default


# ---------------------------------------------------------------- geometry
def _offset(obj, base):
    if obj.UseRatio:
        return obj.Ratio * float(getattr(base, "Thickness", 0.0) or 0.0)
    return float(obj.OffsetValue)


def _shrink(wire, d, normal):
    """The wire made smaller by d in its plane (sharp corners stay sharp)."""
    if d <= TOL:
        return wire
    face = Part.Face(wire)
    if face.normalAt(0, 0).dot(normal) < 0:
        face.reverse()
    return face.makeOffset2D(-d, 2).OuterWire


def cap_shape(obj, body, end):
    """One end cap on a member body's end."""
    face, u = wetrim.end_face(body, end)
    if face is None:
        raise RuntimeError("End Cap: no planar end face on %s" % body.Label)
    base = wetrim.base_of(body)
    n = face.normalAt(0, 0)
    if n.dot(u) < 0:
        n = -n
    off = _offset(obj, base)
    thk = float(obj.Thickness)
    if obj.Direction == "Internal":
        inner = [w for w in face.Wires if not w.isSame(face.OuterWire)]
        if not inner:
            raise NeedsHollow("End Cap: Internal needs a hollow member; this one is solid.")
        wire = _shrink(max(inner, key=lambda w: Part.Face(w).Area), off, n)
        start = -n * (float(obj.Inset) + thk)
    else:
        wire = _shrink(face.OuterWire, off, n)
        start = App.Vector() if obj.Direction == "Outward" else -n * thk
    plate = Part.Face(wire)
    plate.translate(start)
    solid = plate.extrude(n * thk)
    if obj.CornerTreatment and float(obj.CornerSize) > TOL:
        edges = [e for e in solid.Edges if e.Curve.TypeId == "Part::GeomLine"
                 and abs(abs((e.Vertexes[1].Point - e.Vertexes[0].Point).normalize().dot(n)) - 1) < 1e-7
                 and all(f.Surface.TypeId == "Part::GeomPlane" for f in solid.ancestorsOfType(e, Part.Face))]
        size = float(obj.CornerSize)
        if not edges:
            # a rounded profile (a tube with its corner radii) has no sharp straight corners: the treatment
            # then goes on the cap's outer face edge all round, so the option never does nothing
            far = max(solid.Faces, key=lambda f: f.CenterOfMass.dot(n) if f.normalAt(0, 0).dot(n) > 0.99 else -1e9)
            edges = list(far.OuterWire.Edges)
        for make in ((solid.makeFillet if obj.CornerType == "Fillet" else solid.makeChamfer),):
            try:
                solid = make(size, edges)
            except Exception as _fw_err:
                _fw_log("weendcap.py:corner", _fw_err)
                raise RuntimeError("End Cap: the %s of %g does not fit this cap; use a smaller size."
                                   % (obj.CornerType.lower(), size))
    return solid


# ---------------------------------------------------------------- the feature
class EndCap:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "Caps", GROUP, "Member ends (JSON: body, end)")
        add("App::PropertyLinkList", "Sources", GROUP, "The member shapes the caps sit on")
        add("App::PropertyString", "Used", GROUP, "The caps Sources are for (JSON)")
        add("App::PropertyString", "Direction", GROUP, "Outward, Inward or Internal")
        add("App::PropertyDistance", "Thickness", GROUP, "Cap thickness")
        add("App::PropertyDistance", "Inset", GROUP, "Inset distance (Internal)")
        add("App::PropertyBool", "UseRatio", GROUP, "Use thickness ratio")
        add("App::PropertyFloat", "Ratio", GROUP, "Thickness ratio")
        add("App::PropertyDistance", "OffsetValue", GROUP, "Offset value")
        add("App::PropertyBool", "CornerTreatment", GROUP, "Corner treatment")
        add("App::PropertyString", "CornerType", GROUP, "Chamfer or Fillet")
        add("App::PropertyDistance", "CornerSize", GROUP, "Chamfer distance or fillet radius")
        add("App::PropertyLinkList", "Created", GROUP, "Objects made by this feature")
        add("App::PropertyString", "Outputs", GROUP, "Newest shape of each shortened body (JSON)")
        for name in ("Caps", "Sources", "Used", "Created", "Outputs"):
            obj.setEditorMode(name, 2)
        obj.Caps = obj.Used = "[]"
        obj.Outputs = "{}"
        obj.Direction = "Outward"
        obj.Thickness = 5.0
        obj.Inset = 5.0
        obj.UseRatio = True
        obj.Ratio = 0.5
        obj.OffsetValue = 1.0
        obj.CornerType = "Chamfer"
        obj.CornerSize = 1.0
        obj.Proxy = self

    def execute(self, obj):
        from . import wemember
        shapes = []
        for (ref, end), src in zip(_load(obj.Used, []), obj.Sources):
            try:
                shapes.append(cap_shape(obj, src, end))
            except NeedsHollow:
                raise           # the member is fine, the choice is not: say so even mid-rebuild (we100)
            except Exception:
                if wemember.refreshing():
                    return      # the members are being rebuilt (pkg123): build() links the new ones next
                raise
        obj.Shape = Part.makeCompound(shapes) if shapes else Part.Shape()

    def dumps(self):
        return None

    def loads(self, state):
        return None


def build(obj):
    """Links the caps to the bodies' current shapes; Inward also shortens the members."""
    doc = obj.Document
    caps = _load(obj.Caps, [])
    sources, used, created, outputs = [], [], [], {}
    for ref, end in caps:
        tip = doc.getObject(outputs[ref]) if ref in outputs else wetrim.current_tip(doc, ref, obj)
        if tip is None:
            continue
        sources.append(tip)
        used.append([ref, end])
        if obj.Direction == "Inward":
            tp = wetrim._trim_plane(doc, "endface", Body=tip, Trimmed=tip, End=end)
            tp.Offset = obj.Thickness
            created.append(tp)
            doc.recompute([tp])
            trim = wetrim._trim(doc, tip, [(tp, ["Face1"])], "End Trim", "Simple fit")
            created.append(trim)
            outputs[ref] = trim.Name
    obj.Sources = sources
    obj.Used = json.dumps(used)
    obj.Created = created
    obj.Outputs = json.dumps(outputs)
    if App.GuiUp:
        for o in created:
            try:
                o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("weendcap.py:190", _fw_err)
    obj.touch()


class ViewProviderEndCap:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            return _weicon("box.svg")
        except Exception:
            return ""

    def claimChildren(self):
        return []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + TITLE)
        try:
            Gui.Control.showDialog(Panel(obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        doc = obj.Document
        wetrim.clear(obj)
        QtCore.QTimer.singleShot(0, lambda: wetrim._refresh_later(doc))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(doc):
    obj = doc.addObject("Part::FeaturePython", "EndCap")
    EndCap(obj)
    if App.GuiUp:
        ViewProviderEndCap(obj.ViewObject)
        obj.ViewObject.ShapeColor = (0.62, 0.65, 0.70)
    obj.Label = naming.next_label(doc, LABEL)
    return obj


def end_of(obj, sub):
    """(body reference, end) for a picked face of a member body, else None."""
    ref = wetrim.ref_of(obj)
    if ref is None:
        return None
    base = wetrim.base_of(obj)
    try:
        face = obj.Shape.getElement(sub)
    except Exception as _fw_err:
        _fw_log("weendcap.py:266", _fw_err)
        return None
    if face.ShapeType != "Face" or face.Surface.TypeId != "Part::GeomPlane":
        return None
    p0, p1 = wetrim.line_of(base)
    u = (p1 - p0).normalize()
    if abs(face.normalAt(0, 0).dot(u)) < 0.3:
        return None             # a side face, not an end
    end = 1 if (face.CenterOfMass - p0).dot(u) > (p1 - p0).Length / 2 else 0
    return ref, end


# ---------------------------------------------------------------- PropertyManager
def _box(title):
    box = QtWidgets.QWidget()
    box.setWindowTitle(title)
    QtWidgets.QFormLayout(box)
    return box


def _spin(name, value, lo=0.0, hi=10000.0, suffix=" mm", step=1.0, decimals=2):
    w = QtWidgets.QDoubleSpinBox()
    w.setObjectName(name)
    w.setRange(lo, hi)
    w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setSuffix(suffix)
    w.setValue(value)
    return w


class _Keys(QtCore.QObject):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Delete:
            self.panel.remove_current()
            return True
        return False


class Panel:
    def __init__(self, obj, new):
        self.obj = obj
        self.new = new
        self.busy = True
        self.caps = _load(obj.Caps, [])

        params = _box("Parameters")
        f = params.layout()
        self.faces = QtWidgets.QListWidget()
        self.faces.setObjectName("SWWECapFaces")
        self.faces.setMaximumHeight(70)
        pmboxes.mark(self.faces, True)
        self.faces.setToolTip("End faces of structural members. Delete removes one.")
        self._keys = _Keys(self)
        self.faces.installEventFilter(self._keys)
        f.addRow(self.faces)
        f.addRow(QtWidgets.QLabel("Thickness direction:"))
        row = QtWidgets.QHBoxLayout()
        self.directions = QtWidgets.QButtonGroup(params)
        for i, text in enumerate(DIRECTIONS):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWWECap" + text)
            b.setText(text)
            b.setToolTip(text)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setChecked(text == obj.Direction)
            from . import pmpics
            pmpics.picture(b, "cap", text)
            self.directions.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        f.addRow(row)
        self.thickness = _spin("SWWECapThickness", float(obj.Thickness), 0.01)
        self.thickness.setToolTip("Thickness")
        f.addRow("Thickness", self.thickness)
        self.inset = _spin("SWWECapInset", float(obj.Inset), 0.0)
        self.inset_label = QtWidgets.QLabel("Inset distance")
        f.addRow(self.inset_label, self.inset)

        offset = _box("Offset")
        f = offset.layout()

        self.use_ratio = QtWidgets.QRadioButton("Thickness Ratio")
        self.use_ratio.setObjectName("SWWECapUseRatio")
        self.use_value = QtWidgets.QRadioButton("Offset Value")
        self.use_value.setObjectName("SWWECapUseValue")
        self.offset_kind = QtWidgets.QButtonGroup(offset)
        self.offset_kind.addButton(self.use_ratio, 0)
        self.offset_kind.addButton(self.use_value, 1)
        (self.use_ratio if obj.UseRatio else self.use_value).setChecked(True)
        self.ratio = _spin("SWWECapRatio", obj.Ratio, 0.0, 0.99, "", 0.1, 2)
        self.ratio.setToolTip("Thickness ratio")
        self.offset = _spin("SWWECapOffset", float(obj.OffsetValue), 0.0)
        self.offset.setToolTip("Offset value")
        f.addRow(self.use_ratio)
        f.addRow(self.ratio)
        f.addRow(self.use_value)
        f.addRow(self.offset)

        corner = _box("Corner Treatment")
        f = corner.layout()
        self.corner_on = QtWidgets.QCheckBox("Corner Treatment")
        self.corner_on.setObjectName("SWWECapCorner")
        self.corner_on.setChecked(obj.CornerTreatment)
        f.addRow(self.corner_on)
        self.corner_types = QtWidgets.QButtonGroup(corner)
        for i, text in enumerate(CORNERS):
            b = QtWidgets.QRadioButton(text)
            b.setObjectName("SWWECap" + text)
            b.setChecked(text == obj.CornerType)
            self.corner_types.addButton(b, i)
            f.addRow(b)
        self.corner_size = _spin("SWWECapCornerSize", float(obj.CornerSize), 0.01)
        self.corner_label = QtWidgets.QLabel("Chamfer Distance")
        f.addRow(self.corner_label, self.corner_size)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("SWWECapError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        from . import pickprompt
        pickprompt.style(self.error)     # look audit AI1: the start prompt in the yellow box
        f.addRow(self.error)

        for w in (params, offset, corner):
            w.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        params.setProperty("swstyle_pm_title", TITLE)
        params.setProperty("swstyle_pm_icon", "SWStyle_WEEndCap")
        self.form = [params, offset, corner]
        self._show()

        self.directions.buttonClicked.connect(self._changed)
        self.corner_types.buttonClicked.connect(self._changed)
        for w in (self.thickness, self.inset, self.ratio, self.offset, self.corner_size):
            w.valueChanged.connect(self._changed)
        for w in (self.use_ratio, self.corner_on):
            w.toggled.connect(self._changed)
        self.busy = False
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _show(self):
        busy, self.busy = self.busy, True
        doc = self.obj.Document
        self.faces.clear()
        for k, (ref, end) in enumerate(self.caps, 1):
            tip = wetrim.current_tip(doc, ref)
            self.faces.addItem("Face<%d>@%s" % (k, tip.Label if tip is not None else ref))
        internal = DIRECTIONS[max(0, self.directions.checkedId())] == "Internal"
        self.inset.setVisible(internal)
        self.inset_label.setVisible(internal)
        ratio = self.use_ratio.isChecked()
        from . import smlive            # nothing greyed: the boxes that do not apply are hidden (drawings-land281)
        smlive.row(self.ratio, ratio)
        smlive.row(self.offset, not ratio)
        on = self.corner_on.isChecked()
        for b in self.corner_types.buttons():
            smlive.row(b, on)
        smlive.row(self.corner_size, on)
        fillet = CORNERS[max(0, self.corner_types.checkedId())] == "Fillet"
        self.corner_label.setText("Fillet Radius" if fillet else "Chamfer Distance")
        if not self.caps:
            self.error.setText(HINT)
            self.error.setVisible(True)
        self.busy = busy

    def _changed(self, *args):
        if self.busy:
            return
        obj = self.obj
        obj.Caps = json.dumps(self.caps)
        obj.Direction = DIRECTIONS[max(0, self.directions.checkedId())]
        obj.Thickness = self.thickness.value()
        obj.Inset = self.inset.value()
        obj.UseRatio = self.use_ratio.isChecked()
        obj.Ratio = self.ratio.value()
        obj.OffsetValue = self.offset.value()
        obj.CornerTreatment = self.corner_on.isChecked()
        obj.CornerType = CORNERS[max(0, self.corner_types.checkedId())]
        obj.CornerSize = self.corner_size.value()
        self.error.hide()
        self._show()
        from . import wemember
        try:
            wemember.refresh(obj.Document)
            if "Invalid" in obj.State:
                raise RuntimeError(obj.getStatusString())
        except Exception as error:
            self.error.setText(str(error))
            self.error.show()

    # ---------------------------------------------------------------- selection
    def addSelection(self, doc, name, sub, point):
        # a PropertyManager closed without its own close (Esc through the PM keys) must not keep
        # clearing every pick in the view
        try:
            from .widgets import alive
            forms = self.form if isinstance(self.form, (list, tuple)) else [self.form]
            if not (Gui.Control.activeDialog() and any(alive(f) and _in_tasks(f) for f in forms)):
                Gui.Selection.removeObserver(self)
                return
        except Exception:
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("weendcap.py:454", _fw_err)
            return
        if sub.startswith("Face"):
            from . import safe_later as _sl; _sl.later(0, lambda: self._picked(doc, name, sub), self, "error")

    def _picked(self, doc_name, name, sub):
        # The panel can close between addSelection and this queued callback. Recheck before touching
        # selection or the model, and fail closed if the Qt wrapper is already gone.
        try:
            from .widgets import alive
            forms = self.form if isinstance(self.form, (list, tuple)) else [self.form]
            if not (Gui.Control.activeDialog() and any(alive(f) and _in_tasks(f) for f in forms)):
                Gui.Selection.removeObserver(self)
                return
        except Exception:
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("weendcap.py:472", _fw_err)
            return
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("weendcap.py:477", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        found = end_of(picked, sub)
        if found is None:
            self.error.setText(HINT)
            self.error.show()
            return
        if list(found) in self.caps:
            return
        self.caps.append(list(found))
        self._changed()

    def remove_current(self):
        row = self.faces.currentRow()
        if row < 0:
            return
        del self.caps[row]
        self._changed()

    # ---------------------------------------------------------------- closing
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("weendcap.py:506", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("weendcap.py:512", _fw_err)

    def accept(self):
        if not self.caps:
            self.error.setText(HINT)
            self.error.show()
            return False
        if "Invalid" in self.obj.State:
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        doc.recompute()
        self._close()
        return True


def start():
    doc = App.ActiveDocument
    if doc is None:
        return
    picked = []
    for s in Gui.Selection.getSelectionEx():
        for sub in s.SubElementNames:
            found = end_of(s.Object, sub)
            if found is not None and list(found) not in picked:
                picked.append(list(found))
    doc.openTransaction(TITLE)
    try:
        obj = make(doc)
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    if picked:
        panel.caps = picked
        panel._changed()


class Command:
    def GetResources(self):
        try:
            pixmap = _weicon("box.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "End Cap",
                "ToolTip": "Closes the open end of a member with a plate."}

    def IsActive(self):
        if not wetrim.weldment_ready():
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        if not wetrim.need_members("End Cap"):
            return
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())


def _in_tasks(w):
    """The form still sits in FreeCAD's task view: shown, or hidden behind the FeatureManager tab."""
    try:
        p = w
        while p is not None:
            if p.metaObject().className() in ("Gui::TaskView::TaskView", "Gui::TaskView::TaskBox"):
                return True
            p = p.parentWidget()
    except (RuntimeError, AttributeError):
        return False
    return False
