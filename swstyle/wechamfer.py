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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import naming, wetrim

COMMAND = "SWStyle_WEChamfer"
TITLE = "Chamfer"
LABEL = "Chamfer"
GROUP = "Chamfer"
HINT = "Select edges of structural members to chamfer."
TOL = 1e-6
FIND = 0.05


def _load(text, default):
    try:
        return json.loads(text or "")
    except Exception:
        return default


def is_chamfer(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "WeldmentChamfer"


def find_edges(shape, points):
    """The edges of shape through the points picked."""
    import Part
    out = []
    for p in points:
        v = Part.Vertex(App.Vector(*p))
        best, dist = None, FIND
        for e in shape.Edges:
            try:
                d = e.distToShape(v)[0]
            except Exception:
                continue
            if d < dist:
                best, dist = e, d
        if best is not None and not any(best.isSame(e) for e in out):
            out.append(best)
    return out


class WeldmentChamfer:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "Picks", GROUP, "Edges as [member, point] (JSON)")
        add("App::PropertyLength", "Distance", GROUP, "Distance 1")
        add("App::PropertyLength", "Distance2", GROUP, "Distance 2")
        add("App::PropertyBool", "EqualDistance", GROUP, "Equal distance")
        _more(obj)
        add("App::PropertyLinkList", "Created", GROUP, "Objects made by this feature")
        add("App::PropertyString", "Outputs", GROUP, "Newest shape of each chamfered body (JSON)")
        for name in ("Picks", "Created", "Outputs"):
            obj.setEditorMode(name, 2)
        obj.Picks = "[]"
        obj.Outputs = "{}"
        obj.Distance = obj.Distance2 = 1.0
        obj.EqualDistance = True
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


TYPES = ("Angle Distance", "Distance Distance")


def _more(obj):
    """Chamfer Type, Angle and Flip direction (commands pkg188; older chamfers are Distance Distance)."""
    if "ChamferType" in obj.PropertiesList:
        return
    add = obj.addProperty
    add("App::PropertyString", "ChamferType", GROUP, "Angle Distance or Distance Distance")
    add("App::PropertyAngle", "Angle", GROUP, "Angle (Angle Distance)")
    add("App::PropertyBool", "Flip", GROUP, "Flip direction")
    obj.ChamferType = "Distance Distance" if obj.Picks not in ("", "[]") else "Angle Distance"
    obj.Angle = 45.0


def distances(ch):
    import math
    d1 = float(ch.Distance)
    if getattr(ch, "ChamferType", "Distance Distance") == "Angle Distance":
        d2 = d1 * math.tan(math.radians(float(ch.Angle)))
    else:
        d2 = d1 if ch.EqualDistance else float(ch.Distance2)
    return (d2, d1) if getattr(ch, "Flip", False) else (d1, d2)


class ChamferBody:
    """A member with its picked edges chamfered."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "TrimmedBody", GROUP, "The member before the chamfer")
        obj.addProperty("App::PropertyLink", "Chamfer", GROUP, "The Chamfer")
        obj.addProperty("App::PropertyString", "Points", GROUP, "Points on the edges (JSON)")
        obj.addProperty("App::PropertyBool", "Failed", GROUP, "The chamfer could not be made")
        obj.setEditorMode("Points", 2)
        obj.setEditorMode("Failed", 2)
        obj.Proxy = self

    def execute(self, obj):
        body, ch = obj.TrimmedBody, obj.Chamfer
        if body is None or ch is None or body.Shape.isNull():
            return
        shape = body.Shape
        if shape.ShapeType != "Solid" and len(shape.Solids) == 1:
            shape = shape.Solids[0]
        edges = find_edges(shape, _load(obj.Points, []))
        obj.Failed = False
        if not edges:
            obj.Shape = shape.copy()
            return
        d1, d2 = distances(ch)
        try:
            obj.Shape = shape.makeChamfer(d1, edges) if abs(d2 - d1) < 1e-9 else shape.makeChamfer(d1, d2, edges)
        except Exception as error:

            obj.Failed = True
            obj.Shape = shape.copy()
            App.Console.PrintWarning("%s: %s\n" % (ch.Label, error))

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderChamferBody:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def claimChildren(self):
        return []

    def dumps(self):
        return None

    def loads(self, state):
        return None


def build(ch):
    doc = ch.Document
    by_ref = {}
    for ref, p in _load(ch.Picks, []):
        by_ref.setdefault(ref, []).append(p)
    created, outputs = [], {}
    for ref, points in by_ref.items():
        tip = wetrim.current_tip(doc, ref, ch)
        if tip is None or tip.Shape.isNull() or not find_edges(tip.Shape, points):
            continue
        obj = doc.addObject("Part::FeaturePython", "MemberChamfer")
        ChamferBody(obj)
        if App.GuiUp:
            ViewProviderChamferBody(obj.ViewObject)
        obj.TrimmedBody = tip
        obj.Chamfer = ch
        obj.Points = json.dumps(points)
        created.append(obj)
        outputs[ref] = obj.Name
    ch.Created = created
    ch.Outputs = json.dumps(outputs)
    if App.GuiUp:
        for o in created:
            try:
                o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("wechamfer.py:205", _fw_err)
    ch.touch()


class ViewProviderWeldmentChamfer:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return ":/icons/PartDesign_Chamfer.svg"

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(Panel(vobj.Object, False))
        return True

    def unsetEdit(self, vobj, mode=0):
        return None

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def onDelete(self, vobj, subelements):
        wetrim.clear(vobj.Object)
        QtCore.QTimer.singleShot(0, lambda doc=vobj.Object.Document: wetrim._refresh_later(doc))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(doc):
    obj = doc.addObject("App::FeaturePython", "WeldmentChamfer")
    WeldmentChamfer(obj)
    if App.GuiUp:
        ViewProviderWeldmentChamfer(obj.ViewObject)
    obj.Label = naming.next_label(doc, LABEL)
    return obj


def pick_of(obj, sub, point=None):
    """[member ref, point on the edge] for an edge of a member body, else None."""
    if not sub.startswith("Edge"):
        return None
    ref = wetrim.ref_of(obj)
    if ref is None:
        return None
    try:
        e = obj.Shape.getElement(sub)
    except Exception as _fw_err:
        _fw_log("wechamfer.py:264", _fw_err)
        return None
    p = e.valueAt(e.FirstParameter + 0.5 * (e.LastParameter - e.FirstParameter))
    return [ref, [p.x, p.y, p.z]]


# ---------------------------------------------------------------- PropertyManager
class Panel:
    def __init__(self, obj, new):
        self.obj, self.new = obj, new
        self.busy = True
        _more(obj)
        self.picks = _load(obj.Picks, [])
        if not new:
            obj.Document.openTransaction(TITLE)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", TITLE if new else obj.Label)
        self.form.setProperty("swstyle_pm_icon", "FEATURES_CHAMFER")
        lay = QtWidgets.QVBoxLayout(self.form)
        box = QtWidgets.QGroupBox("Items To Chamfer", self.form)
        bl = QtWidgets.QVBoxLayout(box)
        self.items = QtWidgets.QListWidget(box)
        self.items.setMaximumHeight(110)
        self.items.setContextMenuPolicy(QtCore.Qt.ActionsContextMenu)
        clear = QtGui.QAction("Clear Selections", self.items)
        clear.triggered.connect(self._clear)
        self.items.addAction(clear)
        bl.addWidget(self.items)
        lay.addWidget(box)
        par = QtWidgets.QGroupBox("Chamfer Parameters", self.form)
        pl = QtWidgets.QFormLayout(par)
        row = QtWidgets.QHBoxLayout()
        self.types = QtWidgets.QButtonGroup(par)
        for k, t in enumerate(TYPES):
            b = QtWidgets.QRadioButton(t, par)
            b.setChecked(obj.ChamferType == t)
            self.types.addButton(b, k)
            row.addWidget(b)
        pl.addRow(row)
        self.d1 = self._spin(par, obj.Distance)
        self.d1.setObjectName("SWWEChamferDistance1")     # pmlast keeps each field's last value by its name
        self.flip = QtWidgets.QCheckBox("Flip direction", par)
        self.flip.setChecked(obj.Flip)
        self.angle = QtWidgets.QDoubleSpinBox(par)
        self.angle.setObjectName("SWWEChamferAngle")
        self.angle.setRange(0.1, 89.9)
        self.angle.setDecimals(2)
        self.angle.setSuffix(" deg")
        self.angle.setValue(float(obj.Angle))
        self.equal = QtWidgets.QCheckBox("Equal distance", par)
        self.equal.setChecked(obj.EqualDistance)
        self.d2 = self._spin(par, obj.Distance2)
        self.d2.setObjectName("SWWEChamferDistance2")
        pl.addRow("Distance 1:", self.d1)
        pl.addRow(self.flip)
        pl.addRow("Angle:", self.angle)
        pl.addRow(self.equal)
        pl.addRow("Distance 2:", self.d2)
        self.form_rows = pl
        lay.addWidget(par)
        self.error = QtWidgets.QLabel(HINT, self.form)
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        lay.addStretch(1)
        for w in (self.d1, self.d2):
            w.valueChanged.connect(self._changed)
        self.equal.toggled.connect(self._changed)
        self.flip.toggled.connect(self._changed)
        self.angle.valueChanged.connect(self._changed)
        self.types.buttonClicked.connect(self._changed)
        self.busy = False
        self._show()
        Gui.Selection.addObserver(self)

    @staticmethod
    def _spin(parent, value):
        s = QtWidgets.QDoubleSpinBox(parent)
        s.setRange(0.001, 1e5)
        s.setDecimals(2)
        s.setSuffix(" mm")
        s.setValue(float(value))
        return s

    def _show(self):
        angle = self.types.checkedId() == 0
        self.angle.setVisible(angle)
        self.form_rows.labelForField(self.angle).setVisible(angle)
        self.equal.setVisible(not angle)
        self.d2.setVisible(not angle)
        self.form_rows.labelForField(self.d2).setVisible(not angle)
        self.d2.setEnabled(not self.equal.isChecked())
        self.items.clear()
        doc = self.obj.Document
        for ref, _p in self.picks:
            tip = wetrim.current_tip(doc, ref)
            self.items.addItem("Edge <%s>" % (tip.Label if tip is not None else ref))

    def _clear(self):
        self.picks = []
        self._changed()

    def _changed(self, *args):
        if self.busy:
            return
        obj = self.obj
        obj.Picks = json.dumps(self.picks)
        obj.Distance = self.d1.value()
        obj.EqualDistance = self.equal.isChecked()
        obj.Distance2 = self.d2.value()
        obj.ChamferType = TYPES[max(0, self.types.checkedId())]
        obj.Angle = self.angle.value()
        obj.Flip = self.flip.isChecked()
        self._show()
        from . import wemember
        try:
            wemember.refresh(obj.Document)
            bad = [o for o in obj.Created if getattr(o, "Failed", False) or "Invalid" in o.State]
            if bad:
                raise RuntimeError("The chamfer is too large for the edge.")
            self.error.setText("" if self.picks else HINT)
            self.error.setStyleSheet("")
        except Exception as error:
            self.error.setText(str(error))
            self.error.setStyleSheet("color:#d04040")

    def add(self, pick):
        if pick is not None and pick not in self.picks:
            self.picks.append(pick)
            self._changed()

    def addSelection(self, doc, name, sub, point):
        obj = App.getDocument(doc).getObject(name)
        pick = pick_of(obj, sub)
        QtCore.QTimer.singleShot(0, lambda: (self.add(pick), Gui.Selection.clearSelection()))

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("wechamfer.py:402", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("wechamfer.py:408", _fw_err)

    def accept(self):
        if not self.picks:
            self.error.setText(HINT)
            self.error.setStyleSheet("color:#d04040")
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        # The abort put the members back as they were. Rebuilding them anyway (wemember.refresh)
        # removed and remade the trim objects outside any step, which FreeCAD kept as a separate

        # Undo step. Rebuild only when the abort left something to recompute.
        stale = []
        for o in doc.Objects:
            try:
                if o.isTouched() or "Invalid" in o.State:
                    stale.append(o)
            except Exception as _fw_err:
                _fw_log("wechamfer.py:reject", _fw_err)
        if stale:
            from . import wemember
            try:
                wemember.refresh(doc)
            except Exception:
                doc.recompute()
        self._close()
        return True


def _picked():
    out = []
    for s in Gui.Selection.getSelectionEx():
        for sub in s.SubElementNames:
            p = pick_of(s.Object, sub)
            if p is not None and p not in out:
                out.append(p)
    return out


def run():
    """Chamfer pressed in a weldment with no solid in the active Body, or with member edges picked:
    True when it is handled here (featureflow)."""
    from . import wecut
    picked = _picked()
    if not picked and not wecut.wants():
        return False
    if not picked and Gui.Selection.getSelectionEx():
        return False
    doc = App.ActiveDocument
    Gui.Selection.clearSelection()
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
        panel.picks = picked
        panel._changed()
    return True


class Command:
    def GetResources(self):
        return {"Pixmap": "PartDesign_Chamfer", "MenuText": "Chamfer",
                "ToolTip": "Chamfers the edges of structural members."}

    def IsActive(self):
        return wetrim._has_members() and not Gui.Control.activeDialog()

    def Activated(self):
        if not run():
            from . import wecut
            if not wecut.wants():
                Gui.runCommand("PartDesign_Chamfer", 0)


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
