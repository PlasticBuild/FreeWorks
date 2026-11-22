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
import Part
from PySide import QtCore, QtWidgets

from . import naming, wetrim

COMMAND = "SWStyle_WECutExtrude"
TITLE = "Cut-Extrude"
LABEL = "Cut-Extrude"
GROUP = "Cut-Extrude"
ENDS = ("Blind", "Through All", "Through All - Both", "Mid Plane")
ENDS2 = ("Blind", "Through All")
HINT = "Select a sketch with a closed profile."
TOL = 1e-6


def _load(text, default):
    try:
        return json.loads(text or "")
    except Exception:
        return default


def all_refs(doc):
    from . import wemember
    return ["%s:%d" % (sm.Name, k) for sm in wemember.structural_members(doc) for k in range(len(sm.Bodies))]


def wants(doc=None):
    """A weldment whose active Body has no solid: FreeCAD's Pocket would refuse."""
    doc = doc or App.ActiveDocument
    if doc is None or not all_refs(doc):
        return False
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception:
        body = None
    if body is None:
        return True
    try:
        return body.Shape.isNull() or not body.Shape.Solids
    except Exception as _fw_err:
        _fw_log("wecut.py:68", _fw_err)
        return True


def is_cut(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "WeldmentCut"


# ---------------------------------------------------------------- the cut
def tool(wc, size=None):
    """The solid the cut takes away."""
    sk = wc.Profile
    if sk is None or sk.Shape.isNull():
        raise RuntimeError(HINT)
    wires = [w for w in sk.Shape.Wires if w.isClosed()]
    if not wires:
        raise RuntimeError(HINT)
    face = Part.makeFace(wires, "Part::FaceMakerBullseye")
    n = sk.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
    if wc.Reversed:
        n = -n
    big = size or _size(wc.Document)

    def run(end, depth, d):
        if end == "Blind":
            return face.extrude(d * max(float(depth), TOL))
        if end == "Mid Plane":
            h = max(float(depth), TOL) / 2
            return face.translated(d * -h).extrude(d * (2 * h))
        if end == "Through All":
            return face.extrude(d * big)
        return face.translated(d * -big).extrude(d * (2 * big))
    solid = run(wc.EndCondition, wc.Depth, n)
    if getattr(wc, "Direction2", False) and wc.EndCondition in ("Blind", "Through All"):
        solid = solid.fuse(run(wc.EndCondition2, wc.Depth2, -n))
    if getattr(wc, "FlipSide", False):
        # Flip side to cut: what is outside the profile goes
        box = App.BoundBox()
        for ref in all_refs(wc.Document):
            tip = wetrim.member_tip(wc.Document, ref)
            if tip is not None and not tip.Shape.isNull():
                box.add(tip.Shape.BoundBox)
        box.enlarge(10.0)
        whole = Part.makeBox(box.XLength, box.YLength, box.ZLength, App.Vector(box.XMin, box.YMin, box.ZMin))
        solid = whole.cut(solid)
    return solid


def _size(doc):
    box = App.BoundBox()
    for ref in all_refs(doc):
        tip = wetrim.member_tip(doc, ref)
        if tip is not None and not tip.Shape.isNull():
            box.add(tip.Shape.BoundBox)
    return (box.DiagonalLength if box.isValid() else 1000.0) * 2 + 10.0


class WeldmentCut:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLink", "Profile", GROUP, "The sketch of the cut")
        add("App::PropertyString", "EndCondition", GROUP, "Through All - Both, Through All or Blind")
        add("App::PropertyLength", "Depth", GROUP, "Depth (Blind)")
        add("App::PropertyBool", "Reversed", GROUP, "Reverse Direction")
        _more(obj)
        add("App::PropertyBool", "ScopeAll", "Feature Scope", "All bodies")
        add("App::PropertyString", "Scope", "Feature Scope", "The bodies picked (JSON)")
        add("App::PropertyLinkList", "Created", GROUP, "Objects made by this feature")
        add("App::PropertyString", "Outputs", GROUP, "Newest shape of each cut body (JSON)")
        for name in ("Scope", "Created", "Outputs"):
            obj.setEditorMode(name, 2)
        obj.EndCondition = ENDS[0]
        obj.Depth = 10.0
        obj.ScopeAll = True
        obj.Scope = "[]"
        obj.Outputs = "{}"
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _more(obj):
    """Direction 2 and Flip side to cut (commands pkg188; older cuts get them when edited)."""
    if "FlipSide" in obj.PropertiesList:
        return
    add = obj.addProperty
    add("App::PropertyBool", "FlipSide", GROUP, "Flip side to cut")
    add("App::PropertyBool", "Direction2", GROUP, "Direction 2")
    add("App::PropertyString", "EndCondition2", GROUP, "Direction 2: Blind or Through All")
    add("App::PropertyLength", "Depth2", GROUP, "Direction 2 depth (Blind)")
    obj.EndCondition2 = "Blind"
    obj.Depth2 = 10.0


class CutBody:
    """A member with the cut taken away."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "TrimmedBody", GROUP, "The member before the cut")
        obj.addProperty("App::PropertyLink", "Cut", GROUP, "The Cut-Extrude")
        obj.Proxy = self

    def execute(self, obj):
        body, wc = obj.TrimmedBody, obj.Cut
        if body is None or wc is None or body.Shape.isNull():
            return
        shape = body.Shape.cut(tool(wc))
        try:
            shape = shape.removeSplitter()
        except Exception as _fw_err:
            _fw_log("wecut.py:183", _fw_err)
        obj.Shape = shape

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderCutBody:
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


def build(wc):
    """Cuts the members' current shapes."""
    doc = wc.Document
    refs = all_refs(doc) if wc.ScopeAll else [r for r in _load(wc.Scope, []) if r in all_refs(doc)]
    created, outputs = [], {}
    try:
        cutter = tool(wc)
    except Exception:
        cutter = None
    if cutter is not None:
        for ref in refs:
            tip = wetrim.current_tip(doc, ref, wc)
            if tip is None or tip.Shape.isNull():
                continue
            try:
                if tip.Shape.common(cutter).Volume < TOL:
                    continue
            except Exception:
                continue
            obj = doc.addObject("Part::FeaturePython", "MemberCut")
            CutBody(obj)
            if App.GuiUp:
                ViewProviderCutBody(obj.ViewObject)
            obj.TrimmedBody = tip
            obj.Cut = wc
            created.append(obj)
            outputs[ref] = obj.Name
    wc.Created = created
    wc.Outputs = json.dumps(outputs)
    if App.GuiUp:
        for o in created:
            try:
                o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("wecut.py:244", _fw_err)
    wc.touch()


class ViewProviderWeldmentCut:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return ":/icons/PartDesign_Pocket.svg"

    def claimChildren(self):
        if not hasattr(self, "Object"):     # asked before attach() on a reopened file (pkg123)
            return []
        return [self.Object.Profile] if getattr(self.Object, "Profile", None) is not None else []

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
        QtCore.QTimer.singleShot(0, lambda: wetrim._refresh_later(vobj.Object.Document))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(doc, sketch):
    obj = doc.addObject("App::FeaturePython", "WeldmentCut")
    WeldmentCut(obj)
    if App.GuiUp:
        ViewProviderWeldmentCut(obj.ViewObject)
    obj.Label = naming.next_label(doc, LABEL)
    obj.Profile = sketch
    if App.GuiUp:
        try:
            sketch.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("wecut.py:299", _fw_err)
    return obj


# ---------------------------------------------------------------- PropertyManager
class Panel:
    def __init__(self, obj, new):
        from . import wemember
        self.obj, self.new = obj, new
        self.busy = True
        _more(obj)
        self.scope = _load(obj.Scope, [])
        if not new:
            obj.Document.openTransaction(TITLE)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", obj.Label)
        self.form.setProperty("swstyle_pm_icon", "FEATURES_EXTRUDE_CUT")
        lay = QtWidgets.QVBoxLayout(self.form)
        box = QtWidgets.QGroupBox("Direction 1", self.form)
        bl = QtWidgets.QFormLayout(box)
        self.end = QtWidgets.QComboBox(box)
        self.end.addItems(ENDS)
        self.end.setCurrentText(obj.EndCondition)
        self.reverse = QtWidgets.QCheckBox("Reverse Direction", box)
        self.reverse.setChecked(obj.Reversed)
        self.depth = QtWidgets.QDoubleSpinBox(box)
        self.depth.setRange(0.001, 1e6)
        self.depth.setDecimals(2)
        self.depth.setSuffix(" mm")
        self.depth.setValue(float(obj.Depth))
        self.flip = QtWidgets.QCheckBox("Flip side to cut", box)
        self.flip.setChecked(obj.FlipSide)
        bl.addRow(self.end)
        bl.addRow(self.reverse)
        bl.addRow("Depth:", self.depth)
        bl.addRow(self.flip)
        lay.addWidget(box)
        self.dir2 = QtWidgets.QGroupBox("Direction 2", self.form)
        self.dir2.setCheckable(True)
        self.dir2.setChecked(obj.Direction2)
        d2 = QtWidgets.QFormLayout(self.dir2)
        self.end2 = QtWidgets.QComboBox(self.dir2)
        self.end2.addItems(ENDS2)
        self.end2.setCurrentText(obj.EndCondition2)
        self.depth2 = QtWidgets.QDoubleSpinBox(self.dir2)
        self.depth2.setRange(0.001, 1e6)
        self.depth2.setDecimals(2)
        self.depth2.setSuffix(" mm")
        self.depth2.setValue(float(obj.Depth2))
        d2.addRow(self.end2)
        d2.addRow("Depth:", self.depth2)
        lay.addWidget(self.dir2)
        scope = QtWidgets.QGroupBox("Feature Scope", self.form)
        sl = QtWidgets.QVBoxLayout(scope)
        self.all = QtWidgets.QCheckBox("All bodies", scope)
        self.all.setChecked(obj.ScopeAll)
        self.bodies = QtWidgets.QListWidget(scope)
        self.bodies.setMaximumHeight(90)
        sl.addWidget(self.all)
        sl.addWidget(self.bodies)
        lay.addWidget(scope)
        self.error = QtWidgets.QLabel(self.form)
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color:#d04040")
        self.error.hide()
        lay.addWidget(self.error)
        lay.addStretch(1)
        self.end.currentIndexChanged.connect(self._changed)
        self.reverse.toggled.connect(self._changed)
        self.depth.valueChanged.connect(self._changed)
        self.all.toggled.connect(self._changed)
        self.flip.toggled.connect(self._changed)
        self.dir2.toggled.connect(self._changed)
        self.end2.currentIndexChanged.connect(self._changed)
        self.depth2.valueChanged.connect(self._changed)
        self.busy = False
        self._show()
        Gui.Selection.addObserver(self)
        self._changed()

    def _show(self):
        self.depth.setEnabled(self.end.currentText() in ("Blind", "Mid Plane"))
        self.dir2.setEnabled(self.end.currentText() in ("Blind", "Through All"))
        self.depth2.setEnabled(self.end2.currentText() == "Blind")
        self.bodies.setEnabled(not self.all.isChecked())
        self.bodies.clear()
        doc = self.obj.Document
        for ref in self.scope:
            tip = wetrim.current_tip(doc, ref)
            self.bodies.addItem(tip.Label if tip is not None else ref)

    def _changed(self, *args):
        if self.busy:
            return
        obj = self.obj
        obj.EndCondition = self.end.currentText()
        obj.Reversed = self.reverse.isChecked()
        obj.Depth = self.depth.value()
        obj.ScopeAll = self.all.isChecked()
        obj.FlipSide = self.flip.isChecked()
        obj.Direction2 = self.dir2.isChecked() and self.dir2.isEnabled()
        obj.EndCondition2 = self.end2.currentText()
        obj.Depth2 = self.depth2.value()
        obj.Scope = json.dumps(self.scope)
        self._show()
        self.error.hide()
        from . import wemember
        try:
            wemember.refresh(obj.Document)
            if not obj.Created:
                raise RuntimeError("The cut does not reach any member.")
        except Exception as error:
            self.error.setText(str(error))
            self.error.show()

    # Feature Scope, Selected bodies: click members in the view
    def addSelection(self, doc, name, sub, point):
        if self.all.isChecked():
            return
        obj = App.getDocument(doc).getObject(name)
        ref = wetrim.ref_of(obj)
        if ref and ref not in self.scope:
            self.scope.append(ref)
            QtCore.QTimer.singleShot(0, self._changed)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("wecut.py:432", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("wecut.py:438", _fw_err)

    def accept(self):
        if not self.obj.Created:
            self.error.setText("The cut does not reach any member.")
            self.error.show()
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        from . import wemember
        try:
            wemember.refresh(doc)
        except Exception:
            doc.recompute()
        self._close()
        return True


def _picked_sketch():
    for s in Gui.Selection.getSelectionEx():
        if s.Object.TypeId == "Sketcher::SketchObject" and any(w.isClosed() for w in s.Object.Shape.Wires):
            return s.Object
    return None


def start():
    doc = App.ActiveDocument
    sketch = _picked_sketch()
    if doc is None or sketch is None:
        return False
    Gui.Selection.clearSelection()
    doc.openTransaction(TITLE)
    try:
        obj = make(doc, sketch)
        Gui.Control.showDialog(Panel(obj, True))
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    return True


def run():
    """Extruded Cut pressed in a weldment: True when it is handled here (featureflow)."""
    if not wants():
        return False
    from . import featureflow, sketchstart
    sketch = featureflow.editing_sketch()
    if sketch is not None:
        if not sketch.Geometry:
            return False
        doc = sketch.Document
        Gui.runCommand("Sketcher_LeaveSketch", 0)
        if featureflow.editing_sketch() is not None:
            return True
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, sketch.Name)
        return start()
    if _picked_sketch() is not None:
        return start()
    if Gui.Selection.getSelectionEx():
        entry = Gui.Selection.getSelectionEx()[-1]
        subs = [s for s in entry.SubElementNames if s]
        sub = subs[-1] if subs else ""
        if entry.Object.TypeId in sketchstart.PLANES and not sub or \
                (sub.startswith("Face") and sketchstart._is_flat(entry.Object, sub)):
            sketchstart._sketch_on(entry.Object, sub)
            sketchstart._then_feature(COMMAND)
            return True
        return False
    body = sketchstart._body()
    if body is None:
        return False
    Gui.Control.showDialog(sketchstart.PlanePicker(body, title=TITLE, icon="FEATURES_EXTRUDE_CUT",
                                                   message=sketchstart.FEATURE_MESSAGE, feature=COMMAND))
    return True


class Command:
    def GetResources(self):
        return {"Pixmap": "PartDesign_Pocket", "MenuText": "Extruded Cut",
                "ToolTip": "Cuts a solid model by extruding a sketched profile."}

    def IsActive(self):
        return wetrim._has_members() and not Gui.Control.activeDialog()

    def Activated(self):
        if not start():
            run()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
