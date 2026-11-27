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

from . import naming, paths, smallowance, smbaseflange
from . import smlive
from . import pmboxes
from .smbaseflange import ALLOWANCES, _active_body, _box, _spin
from .smedgeflange import _radio, _root, error_label

COMMAND = "SWStyle_SMSketchedBend"
TITLE = "Sketched Bend"
LABEL = "Sketched Bend"

POSITIONS = (("Bend Centerline", "middle"), ("Material Inside", "backward"), ("Material Outside", "forward"),
             ("Bend Outside", "intersection of planes"))
PICK_MESSAGE = "Select a face of the sheet on which to sketch the bend line, or an existing sketch."


def _engine():
    import SheetMetalFoldCmd
    return SheetMetalFoldCmd


def is_sketched_bend(obj):
    proxy = getattr(obj, "Proxy", None)
    return proxy is not None and type(proxy).__name__ == "SMFoldWall"


def _sheet_under(sketch):
    """The sheet metal feature the bend line sketch sits on (its support), else the body's tip."""
    try:
        for obj, _subs in sketch.AttachmentSupport:
            if hasattr(obj, "Shape") and obj.TypeId != "App::Plane" and not obj.TypeId.startswith("App::"):
                return obj
    except Exception as _fw_err:
        _fw_log("smsketchedbend.py:57", _fw_err)
    body = smbaseflange._body_of(sketch) or _active_body(sketch.Document)
    tip = body.Tip if body is not None else None
    return tip if tip is not sketch else None


def _line_face(base, sketch):
    """The face of the sheet that holds the bend line (the engine bends that face along the line)."""
    try:
        for obj, subs in sketch.AttachmentSupport:
            if obj is base and subs and subs[0].startswith("Face"):
                return subs[0]
    except Exception as _fw_err:
        _fw_log("smsketchedbend.py:70", _fw_err)
    try:
        edge = sketch.Shape.Edges[0]
        mid = edge.valueAt(edge.FirstParameter + 0.5 * (edge.LastParameter - edge.FirstParameter))
        normal = sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
    except Exception:
        return None
    for i, f in enumerate(base.Shape.Faces, 1):
        try:
            if f.Surface.TypeId != "Part::GeomPlane":
                continue
            n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
            if abs(abs(n.dot(normal)) - 1) < 1e-6 and abs((mid - f.CenterOfMass).dot(n)) < 1e-6:
                return "Face%d" % i
        except Exception:
            continue
    return None


def make(base, face, sketch):
    doc = base.Document
    engine = _engine()
    body = next((p for p in base.InList if p.TypeId == "PartDesign::Body"), None) or _active_body(doc)
    doc.openTransaction(TITLE)
    try:
        obj = doc.addObject("PartDesign::FeaturePython", "Fold")
        engine.SMFoldWall(obj, base, [face], sketch)
        if App.GuiUp:
            engine.SMFoldViewProvider(obj.ViewObject)
        if body is not None:
            body.addObject(obj)
        root = _root(base)
        if root is not None and hasattr(root, "Radius"):
            obj.radius = root.Radius
        obj.Position = "middle"
        obj.Label = naming.next_label(doc, LABEL)
        for o in (base, sketch):
            try:
                o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("smsketchedbend.py:109", _fw_err)
        doc.recompute()
        return obj
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


class Panel:
    """The Sketched Bend PropertyManager; obj is None until the Fixed face is picked."""

    def __init__(self, obj, new, sketch=None):
        self.obj = obj
        self.new = new
        self.sketch = obj.BendLine if obj is not None else sketch
        self.base = obj.baseObject[0] if obj is not None else _sheet_under(self.sketch)
        self.busy = True
        root = _root(self.base) if self.base is not None else None
        self.root_radius = root.Radius.Value if root is not None and hasattr(root, "Radius") else None
        self.root_k = getattr(root, "SWKFactor", 0.5) if root is not None else 0.5

        params = _box("Bend Parameters")
        f = params.layout()
        self.face = QtWidgets.QListWidget()
        self.face.setObjectName("SWSMFixedFace")
        self.face.setMaximumHeight(40)
        self.face.setToolTip("Fixed face: the side of the sheet that stays where it is")
        pmboxes.mark(self.face, True)

        pmboxes.bind(self.face, remove=lambda row: self._drop_face(), clear=self._drop_face)
        f.addRow(QtWidgets.QLabel("Fixed face"))
        f.addRow(self.face)
        self.positions = QtWidgets.QButtonGroup(params)
        current = obj.Position if obj else "middle"
        for i, (text, value) in enumerate(POSITIONS):
            b = _radio("SWSMBendPosition" + text.replace(" ", ""), text)
            b.setChecked(value == current)
            self.positions.addButton(b, i)
            f.addRow(b)
        if self.positions.checkedButton() is None:
            self.positions.button(0).setChecked(True)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        self.reverse.setObjectName("SWSMBendReverse")
        self.reverse.setChecked(bool(obj.invert) if obj else False)
        self.angle = _spin("SWSMBendAngle", obj.angle.Value if obj else 90.0, 0.01, 180.0, suffix=" deg")
        self.angle.setToolTip("Bend angle")
        self.default_radius = QtWidgets.QCheckBox("Use default radius")
        self.default_radius.setObjectName("SWSMDefaultRadius")
        radius = obj.radius.Value if obj else (self.root_radius or 1.0)
        self.radius = _spin("SWSMRadius", radius, 0.0, 10000.0)
        self.radius.setToolTip("Bend radius")
        self.default_radius.setChecked(self.root_radius is not None and abs(radius - self.root_radius) < 1e-9)
        f.addRow(self.reverse)
        f.addRow("Angle", self.angle)
        f.addRow(self.default_radius)
        f.addRow("Radius", self.radius)

        allowance = _box("Custom Bend Allowance")
        f = allowance.layout()
        self.custom_k = QtWidgets.QCheckBox("Custom Bend Allowance")
        self.custom_k.setObjectName("SWSMCustomAllowance")
        self.allowance = QtWidgets.QComboBox()
        self.allowance.setObjectName("SWSMAllowance")
        self.allowance.addItems(ALLOWANCES)
        k = float(obj.kfactor) if obj is not None else self.root_k
        self.custom_k.setChecked(abs(k - self.root_k) > 1e-9)
        self.kfactor = _spin("SWSMKFactor", k, 0.0, 1.0, suffix="", decimals=4, step=0.05)
        f.addRow(self.custom_k)
        f.addRow(self.allowance)
        f.addRow("K", self.kfactor)
        self.custom = smallowance.CustomAllowance(self.allowance, self.kfactor, f, obj, self._changed)
        self.custom_k.setChecked(self.custom_k.isChecked() or self.custom.kind() != "K-Factor")

        self.error = error_label()
        params.layout().addRow(self.error)
        params.setProperty("swstyle_pm_title", TITLE)
        params.setProperty("swstyle_pm_icon", "SheetMetal_AddFoldWall")
        self.form = [params, allowance]
        if obj is not None:
            for sub in obj.baseObject[1]:
                self.face.addItem(sub)
        else:
            self.error.setText("Please specify the planar face to be fixed when creating the bend.")
            self.error.show()
        smlive.live(self)          # before _changed: using a box turns its option on first
        for w in (self.angle, self.radius, self.kfactor):
            w.valueChanged.connect(self._changed)
        for w in (self.reverse, self.default_radius, self.custom_k):
            w.toggled.connect(self._changed)
        self.positions.buttonClicked.connect(self._changed)
        self._show()
        self.busy = False
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ---------------------------------------------------------------- selection
    def _drop_face(self):
        self.face.clear()
        pmboxes.mark(self.face, True, need=True)       # OK waits for a fixed face again

    def addSelection(self, doc, name, sub, point):
        if sub.startswith("Face"):
            at = App.Vector(*point) if point else None
            from . import safe_later as _sl; _sl.later(0, lambda: self._picked(doc, name, sub, at), self, "face")

    def _picked(self, doc_name, name, sub, at=None):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smsketchedbend.py:214", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        base = self.base
        if base is None:
            base = self.base = picked
        if picked is not base:
            face = picked.Shape.getElement(sub)
            match = [i for i, f in enumerate(base.Shape.Faces, 1)
                     if abs(f.Area - face.Area) < 1e-6 and f.CenterOfMass.distanceToPoint(face.CenterOfMass) < 1e-6]
            if not match:
                return
            sub = "Face%d" % match[0]
        line_face = _line_face(base, self.sketch) or sub
        self.face.clear()
        self.face.addItem(sub)
        pmboxes.mark(self.face, True)          # picked: no longer waiting
        if self.obj is None:
            self.obj = make(base, line_face, self.sketch)
            self.busy = True
            self._changed_values()
            self.busy = False
        else:
            self.obj.baseObject = (base, [line_face])
        self._fix_side(at)
        self._report()

    def _fix_side(self, at):
        ""
        if at is None or self.obj is None:
            return
        import Part
        obj = self.obj
        point = Part.Vertex(at)
        for flag in (False, True):
            obj.invertbend = flag
            obj.Document.recompute()
            if "Invalid" not in obj.State and obj.Shape.distToShape(point)[0] < 1e-3:
                return
        obj.invertbend = False
        obj.Document.recompute()

    # ---------------------------------------------------------------- values
    def _show(self):
        smlive.show(self)                  # nothing greyed: using a box turns its option on

    def _changed(self, *args):
        if self.busy:
            return
        self._changed_values()

    def _changed_values(self):
        if self.default_radius.isChecked() and self.root_radius is not None:
            busy, self.busy = self.busy, True
            self.radius.setValue(self.root_radius)
            self.busy = busy
        self._show()
        obj = self.obj
        if obj is None:
            return
        obj.Position = POSITIONS[max(0, self.positions.checkedId())][1]
        obj.invert = self.reverse.isChecked()
        obj.angle = self.angle.value()
        obj.radius = self.radius.value()
        obj.kfactor = smallowance.k_for(self, obj, self.angle.value()) if self.custom_k.isChecked() else self.root_k
        self.custom.save(obj)
        obj.Document.recompute()
        self._report()
        smallowance.report(self)

    def _report(self):
        if self.obj is None:
            self.error.setVisible(True)
            return False
        invalid = "Invalid" in self.obj.State
        self.error.setText(naming.status_text(self.obj, "The bend") if invalid else "")
        self.error.setVisible(invalid)
        return not invalid

    # ---------------------------------------------------------------- closing
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smsketchedbend.py:305", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smsketchedbend.py:311", _fw_err)

    def accept(self):
        self._changed()
        if not self._report():
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        if self.obj is not None:
            doc = self.obj.Document
            shown = (self.base, self.sketch) if self.new else ()
            doc.abortTransaction()
            doc.recompute()
            for o in shown:
                try:
                    o.ViewObject.Visibility = True
                except Exception as _fw_err:
                    _fw_log("smsketchedbend.py:331", _fw_err)
        self._close()
        return True


def open_on(sketch):
    Gui.Selection.clearSelection()
    Gui.Control.showDialog(Panel(None, True, sketch=sketch))


def start():
    doc = App.ActiveDocument
    if doc is None:
        return
    gdoc = Gui.ActiveDocument
    edit = gdoc.getInEdit() if gdoc is not None else None
    if edit is not None and editobj.type_id(edit) == "Sketcher::SketchObject":
        sketch = editobj.of(edit)
        Gui.runCommand("Sketcher_LeaveSketch", 0)
        if sketch.Geometry:
            QtCore.QTimer.singleShot(0, lambda: open_on(sketch))
        return
    picked = [s.Object for s in Gui.Selection.getSelectionEx()]
    sketches = [o for o in picked if o.TypeId == "Sketcher::SketchObject"]
    if len(sketches) == 1:
        open_on(sketches[0])
        return
    smbaseflange._pick_plane(doc, then=open_on, title=TITLE, icon="SheetMetal_AddFoldWall", message=PICK_MESSAGE)


class Command:
    def GetResources(self):
        try:
            import SheetMetalTools, os
            pixmap = os.path.join(SheetMetalTools.icons_path, "SheetMetal_AddFoldWall.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Sketched Bend", "ToolTip": "Bends the sheet along a sketch line."}

    def IsActive(self):
        return smbaseflange.Command().IsActive()

    def Activated(self):
        start()


_patched = {}


class _BendLine:
    """Stands in for the bend line sketch while the fold is made: its lines reach across the fold face."""

    def __init__(self, shape, sketch):
        self.Shape = shape
        self.Name, self.Label = sketch.Name, sketch.Label


def reach_across(sketch, face, overhang=1.0):
    ""



    import Part
    bb = face.BoundBox
    corners = [App.Vector(x, y, z) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)]
    edges = []
    for e in sketch.Shape.Edges:
        if "Line" not in type(e.Curve).__name__ or len(e.Vertexes) != 2:
            edges.append(e)
            continue
        p0, p1 = e.Vertexes[0].Point, e.Vertexes[1].Point
        d = p1 - p0
        length = d.Length
        if length < 1e-9:
            edges.append(e)
            continue
        d.normalize()
        ts = [(c - p0).dot(d) for c in corners]
        t0, t1 = min(min(ts) - overhang, 0.0), max(max(ts) + overhang, length)
        edges.append(Part.LineSegment(p0 + d * t0, p0 + d * t1).toShape())
    return Part.Compound(edges) if len(edges) != 1 else edges[0]


NO_SPLIT = ("The bend line does not divide the face into two pieces. Draw it across the fixed face, clear of other "
            "bends and flanges.")


def _patch_fold():
    """Makes the engine's fold use the bend line reached across the fold face (see reach_across)."""
    import sys
    mod = sys.modules.get("SheetMetalFoldCmd")
    if mod is None or getattr(mod.smFold, "_freeworks", False):
        return
    original = mod.smFold

    def smFold(*args, **kwargs):
        try:
            sketch, main = kwargs.get("bendlinesketch"), kwargs.get("MainObject")
            names = kwargs.get("selFaceNames")
            if sketch is not None and main is not None and names and not args:
                tools = sys.modules.get("SheetMetalTools")
                name = tools.getElementFromTNP(names[0]) if tools is not None else names[0]
                face = main.Shape.getElement(name)
                kwargs["bendlinesketch"] = _BendLine(reach_across(sketch, face), sketch)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: bend line across the face: %s\n" % error)
        try:
            return original(*args, **kwargs)
        except IndexError:
            # the engine found no piece of the face on one side of the line (FreeCAD wrote "list index out of range")
            raise RuntimeError(NO_SPLIT)
    smFold._freeworks = True
    mod.smFold = smFold


def register():
    try:
        _patch_fold()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Sketched Bend line: %s\n" % error)
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
    view = _engine().SMFoldViewProvider
    if "setEdit" not in _patched:
        _patched["setEdit"] = view.setEdit

        def setEdit(self, vobj, mode=0, original=_patched["setEdit"]):
            obj = vobj.Object
            if mode != 0 or not is_sketched_bend(obj) or not paths.params().GetBool("Enabled", True):
                return original(self, vobj, mode)
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
        view.setEdit = setEdit
