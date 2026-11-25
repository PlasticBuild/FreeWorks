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
import Part
from PySide import QtCore, QtWidgets

from . import naming, smflatten
from .smbaseflange import _box, _spin
from .smedgeflange import error_label
from .smunfold import _DeleteKey, _icon, _list

COMMAND = "SWStyle_SMCrossBreak"
TITLE = "Cross Break"
GROUP = "Cross Break"
ICON = "SheetMetal_SketchOnSheet"
V = App.Vector
MESSAGE = "Select a planar rectangular face for Cross Break insertion."
PREVIEW = (1.0, 1.0, 0.0)       # the lines while the PropertyManager is open
LINES = (0.1, 0.1, 0.1)


# ================================================================ geometry
def rectangle(face):
    """The four corners of a flat rectangular face (its outer outline), else None."""
    if face.Surface.TypeId != "Part::GeomPlane":
        return None
    edges = face.OuterWire.OrderedEdges
    if len(edges) != 4 or any(e.Curve.TypeId != "Part::GeomLine" for e in edges):
        return None
    corners = [v.Point for v in face.OuterWire.OrderedVertexes]
    if len(corners) != 4:
        return None
    for k in range(4):
        a = corners[k] - corners[k - 1]
        b = corners[(k + 1) % 4] - corners[k]
        if abs(a.normalize().dot(b.normalize())) > 1e-6:
            return None
    return corners


def face_at(shape, p, normal=None):
    """The flat face of shape through point p (and facing along normal), else None."""
    vp = Part.Vertex(p)
    best = None
    for i, f in enumerate(shape.Faces):
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        if normal is not None and abs(abs(f.normalAt(0, 0).dot(normal)) - 1) > 1e-7:
            continue
        d = f.distToShape(vp)[0]
        if d < 1e-4 and (best is None or d < best[0]):
            best = (d, i)
    return best[1] if best else None


def diagonals(corners):
    return [Part.LineSegment(corners[0], corners[2]), Part.LineSegment(corners[1], corners[3])]


# ================================================================ feature
_LAST = None        # the open Cross Break PropertyManager


class SWCrossBreak:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "Face", GROUP, "The face, as picked")
        add("App::PropertyVector", "FacePoint", GROUP, "A point on the face")
        add("App::PropertyVector", "FaceNormal", GROUP, "The face's normal")
        add("App::PropertyBool", "Reverse", GROUP, "The break goes the other way (down instead of up)")
        add("App::PropertyLength", "Radius", GROUP, "Break radius")
        add("App::PropertyAngle", "Angle", GROUP, "Break angle")
        add("App::PropertyLink", "Profile", GROUP, "The cross profile: a sketch of the break lines")
        from .smbaseflange import inch_part
        obj.Radius = 0.635 if inch_part(obj.Document) else 0.5      # 0.025 in, or 0.5 mm in a metric part
        obj.Angle = 90.0
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Cross Break: needs a sheet metal part")
        shape = base.Shape.copy()
        if obj.Face:
            i = face_at(shape, obj.FacePoint, obj.FaceNormal)
            if i is None or rectangle(shape.Faces[i]) is None:
                raise ValueError(MESSAGE)
        obj.Shape = shape

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_cross_break(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWCrossBreak"


class ViewProviderCrossBreak:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return _icon(ICON)

    def claimChildren(self):
        p = getattr(self.Object, "Profile", None)
        return [p] if p is not None else []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + obj.Label)
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
        p = vobj.Object.Profile
        if p is not None:
            try:
                vobj.Object.Profile = None
                p.Document.removeObject(p.Name)
            except Exception as _fw_err:
                _fw_log("smcrossbreak.py:157", _fw_err)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(body):
    doc = body.Document
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", "CrossBreak")
    SWCrossBreak(obj)
    if App.GuiUp:
        ViewProviderCrossBreak(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, "Cross-Break")
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smcrossbreak.py:180", _fw_err)
    return obj


def profile(obj, face_name):
    """The cross profile: a sketch on the face with its two diagonals (made or redrawn)."""
    body = next((p for p in obj.InList if p.TypeId == "PartDesign::Body"), None)
    base = obj.BaseFeature
    face = base.Shape.getElement(face_name)
    corners = rectangle(face)
    sk = obj.Profile
    if sk is None:
        sk = body.newObject("Sketcher::SketchObject", "CrossProfile")
        sk.Label = naming.next_label(obj.Document, "Sketch")
        obj.Profile = sk
        # the sketch belongs to the cross break, not to the body's chain of features
        if body.Tip is sk:
            body.Tip = obj
    sk.AttachmentSupport = [(base, face_name)]
    sk.MapMode = "FlatFace"
    sk.recompute()
    inv = sk.getGlobalPlacement().inverse()
    sk.deleteAllGeometry()
    for line in diagonals([inv.multVec(c) for c in corners]):
        line.StartPoint = V(line.StartPoint.x, line.StartPoint.y, 0)
        line.EndPoint = V(line.EndPoint.x, line.EndPoint.y, 0)
        sk.addGeometry(line)
    return sk


def _colour(sk, colour):
    try:
        sk.ViewObject.LineColor = colour
        sk.ViewObject.PointColor = colour
        sk.ViewObject.LineWidth = 2.0
        sk.ViewObject.Visibility = True
    except Exception as _fw_err:
        _fw_log("smcrossbreak.py:217", _fw_err)


# ================================================================ PropertyManager
class Panel:
    """The Cross Break PropertyManager."""

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        self.pick_error = ""
        box = _box("Cross Break Parameters")
        f = box.layout()
        self.face = _list("SWSMCrossFace", "#d6ecff", "A flat rectangular face")
        f.addRow(self.face)
        row = QtWidgets.QHBoxLayout()
        self.reverse = QtWidgets.QToolButton()
        self.reverse.setObjectName("SWSMCrossReverse")
        self.reverse.setCheckable(True)
        self.reverse.setChecked(bool(obj.Reverse))
        self.reverse.setText("⇅")
        self.reverse.setToolTip("Reverse direction: the break goes down instead of up")
        self.reverse.toggled.connect(self._changed)
        row.addWidget(self.reverse)
        self.edit = QtWidgets.QPushButton("Edit Cross Profile")
        self.edit.setObjectName("SWSMCrossEdit")
        self.edit.clicked.connect(self.edit_profile)
        row.addWidget(self.edit)
        f.addRow(row)
        self.radius = _spin("SWSMCrossRadius", float(obj.Radius), 0.0, 1000.0, step=0.1)
        self.radius.setToolTip("Break radius")
        f.addRow("Radius:", self.radius)
        self.angle = _spin("SWSMCrossAngle", float(obj.Angle), 0.0, 180.0, suffix=" deg", step=1.0)
        self.angle.setToolTip("Break angle")
        f.addRow("Angle:", self.angle)
        self.error = error_label()
        f.addRow(self.error)
        box.setProperty("swstyle_pm_title", TITLE)
        box.setProperty("swstyle_pm_icon", ICON)
        self.form = [box]
        self.keys = _DeleteKey(self)
        self.face.installEventFilter(self.keys)
        self.radius.valueChanged.connect(self._changed)
        self.angle.valueChanged.connect(self._changed)
        if obj.Profile is not None:
            _colour(obj.Profile, PREVIEW)
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def set_active(self, w):
        pass

    def _fill(self):
        self.face.clear()
        if self.obj.Face:
            self.face.addItem(self.obj.Face)
        self.edit.setEnabled(bool(self.obj.Face))

    def remove_current(self, w):
        self.obj.Face = ""
        p = self.obj.Profile
        if p is not None:
            self.obj.Profile = None
            p.Document.removeObject(p.Name)
        self._apply()

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        if sub.startswith("Face"):
            at = App.Vector(*point) if point else None
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smcrossbreak.py:297", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        face = picked.Shape.getElement(sub)
        if at is None or face.distToShape(Part.Vertex(at))[0] > 1e-4:
            at = face.distToShape(Part.Vertex(face.CenterOfMass))[1][0][0]
        base = self.obj.BaseFeature.Shape
        i = face_at(base, at)
        if i is None or rectangle(base.Faces[i]) is None:
            self.pick_error = MESSAGE
            self._report()
            return
        self.pick_error = ""
        self.obj.Face = "Face%d" % (i + 1)
        self.obj.FacePoint = at
        self.obj.FaceNormal = base.Faces[i].normalAt(0, 0)
        _colour(profile(self.obj, self.obj.Face), PREVIEW)
        self._apply()

    # ---------------------------------------------------------------- result
    def _changed(self, *_a):
        self.obj.Reverse = self.reverse.isChecked()
        self.obj.Radius = self.radius.value()
        self.obj.Angle = self.angle.value()
        self._apply()

    def _apply(self):
        doc = self.obj.Document
        if doc.Recomputing:
            QtCore.QTimer.singleShot(50, self._apply)
            return
        self.obj.touch()
        doc.recompute()
        self._fill()
        self._report()

    def _report(self):
        if "Invalid" in self.obj.State:
            text = self.obj.getStatusString()
        elif self.pick_error:
            text = self.pick_error
        elif not self.obj.Face:
            text = MESSAGE
        else:
            text = ""
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text

    def edit_profile(self):
        """Edit Cross Profile: OK, then the profile sketch opens for editing."""
        sk = self.obj.Profile
        if sk is None or not self.accept():
            return
        Gui.ActiveDocument.setEdit(sk.Name)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smcrossbreak.py:361", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smcrossbreak.py:367", _fw_err)

    def accept(self):
        self.pick_error = ""
        if not self._report():
            return False
        if self.obj.Profile is not None:
            _colour(self.obj.Profile, LINES)
        try:
            self.obj.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("smcrossbreak.py:378", _fw_err)
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        base = self.obj.BaseFeature if self.new else None
        doc.abortTransaction()
        doc.recompute()
        if base is not None:
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smcrossbreak.py:392", _fw_err)
        if self.obj is not None and not self.new and self.obj.Profile is not None:
            _colour(self.obj.Profile, LINES)
        self._close()
        return True


# ================================================================ command
def _sheet_body():
    """The active body when it is sheet metal, folded and not in a dialog."""
    if App.ActiveDocument is None or smflatten.blocked():
        return None
    try:
        if Gui.Control.activeDialog():
            return None
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody") or smflatten._body()
    except Exception as _fw_err:
        _fw_log("smcrossbreak.py:417", _fw_err)
        return None
    if body is None or smflatten.root(body) is None or body.Tip is None or body.Tip.Shape.isNull():
        return None
    return body


def start():
    body = _sheet_body()
    if body is None:
        return
    picked = [(o.Document.Name, o.Object.Name, sub, App.Vector(p)) for o in Gui.Selection.getSelectionEx()
              for sub, p in zip(o.SubElementNames, o.PickedPoints) if sub.startswith("Face")]
    doc = body.Document
    doc.openTransaction(TITLE)
    try:
        obj = make(body)
        doc.recompute()
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    for doc_name, name, sub, at in picked[:1]:
        panel._picked(doc_name, name, sub, at)


class Command:
    def GetResources(self):
        return {"Pixmap": _icon(ICON), "MenuText": "Cross-Break",
                "ToolTip": "Marks a flat rectangular face with crossed break lines."}

    def IsActive(self):
        return _sheet_body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
