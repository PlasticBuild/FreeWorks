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

COMMAND = "SWStyle_EditSketchPlane"
TITLE = "Sketch Plane"
SKETCH = "Sketcher::SketchObject"
PLANES = ("App::Plane", "PartDesign::Plane", "Part::DatumPlane")
MESSAGE = "Select a plane or a flat face for the sketch."


def _flat(obj, sub):
    try:
        face = obj.Shape.getElement(sub)
    except Exception:
        return False
    if face.ShapeType != "Face":
        return False
    if type(face.Surface).__name__ == "Plane":
        return True
    try:
        return face.findPlane() is not None
    except Exception:
        return False


def usable(obj, sub):
    """(obj, sub) as the sketch's new support, or None: a plane, or a flat face."""
    if obj is None:
        return None
    if obj.isDerivedFrom("App::Plane") or obj.TypeId in PLANES:
        return (obj, "")
    if sub and sub.startswith("Face") and _flat(obj, sub):
        return (obj, sub)
    return None


def _base_of(sketch):
    """The part as it is just before the feature built from this sketch (its BaseFeature), or None."""
    for user in getattr(sketch, "InList", ()):
        prof = getattr(user, "Profile", None)
        prof = prof[0] if isinstance(prof, tuple) else prof
        if prof is sketch and getattr(user, "BaseFeature", None) is not None:
            return user.BaseFeature
    return None


def earlier(sketch, obj, sub):
    ""




    try:
        if obj is not sketch and sketch not in obj.OutListRecursive:
            return obj, sub
    except Exception:
        return obj, sub
    base = _base_of(sketch)
    if base is None or base is obj:
        return None
    try:
        face = obj.Shape.getElement(sub)
        u0, u1, v0, v1 = face.ParameterRange
        normal = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        point = face.valueAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
    except Exception:
        return None
    best, area = None, 1e-6
    for i, f in enumerate(base.Shape.Faces):
        try:
            if not _flat(base, "Face%d" % (i + 1)):
                continue
            a0, a1, b0, b1 = f.ParameterRange
            n = f.normalAt((a0 + a1) / 2.0, (b0 + b1) / 2.0)
            if abs(abs(n.dot(normal)) - 1.0) > 1e-7 or abs((point - f.Vertexes[0].Point).dot(n)) > 1e-6:
                continue
            common = f.common(face).Area
        except Exception:
            continue
        if common > area:
            best, area = "Face%d" % (i + 1), common
    return (base, best) if best else None


def _support(sketch):
    return list(getattr(sketch, "AttachmentSupport", None) or getattr(sketch, "Support", None) or [])


def move_to(sketch, obj, sub):
    """Attach sketch to the plane or flat face (obj, sub)."""
    prop = "AttachmentSupport" if hasattr(sketch, "AttachmentSupport") else "Support"
    setattr(sketch, prop, [(obj, sub)] if sub else [(obj, "")])
    sketch.MapMode = "FlatFace"
    sketch.Document.recompute()


def label(support):
    if not support:
        return ""
    obj, subs = support[0]
    sub = subs[0] if isinstance(subs, (list, tuple)) and subs else (subs if isinstance(subs, str) else "")
    return "%s@%s" % (sub, obj.Label) if sub else obj.Label


class SketchPlanePanel:
    def __init__(self, sketch):
        self.sketch, self.doc = sketch, sketch.Document
        self.start = (_support(sketch), sketch.MapMode)
        self.doc.openTransaction("Edit Sketch Plane")
        try:
            self.form = form = QtWidgets.QWidget()
            form.setObjectName("SWSketchPlanePM")
            form.setWindowTitle(TITLE)
            lay = QtWidgets.QVBoxLayout(form)
            group = QtWidgets.QGroupBox("Sketch Plane/Face", form)
            g = QtWidgets.QVBoxLayout(group)
            self.list = QtWidgets.QListWidget(group)
            self.list.setObjectName("SWSketchPlaneFace")
            self.list.setFixedHeight(40)
            g.addWidget(self.list)
            lay.addWidget(group)
            self.note = QtWidgets.QLabel(MESSAGE, form)
            self.note.setObjectName("SWSketchPlaneNote")
            self.note.setWordWrap(True)
            lay.addWidget(self.note)
            lay.addStretch(1)
            self.show(self.start[0])
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)
            self._observing = True
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise

    def show(self, support):
        self.list.clear()
        text = label(support)
        if text:
            self.list.addItem(text)

    # selection observer
    def addSelection(self, doc, obj, sub, pnt):
        if doc != self.doc.Name:
            return
        from . import safe_later as _sl; _sl.later(0, lambda o=obj, s=sub: self.take(o, s), self, "note")

    def take(self, name, sub):
        obj = self.doc.getObject(name)
        if obj is None or obj == self.sketch:
            return
        sub = (sub or "").rsplit(".", 1)[-1]
        pick = usable(obj, sub)
        if pick is None:
            self.note.setText("That is not a plane or a flat face. " + MESSAGE)
            return
        if pick[1]:
            pick = earlier(self.sketch, *pick)
            if pick is None:
                self.note.setText("That face is made by a feature built on this sketch: pick a plane or a "
                                  "face of the part before it.")
                return
        try:
            move_to(self.sketch, *pick)
        except Exception as error:
            self.note.setText("The sketch cannot go there: %s" % error)
            return
        self.show(_support(self.sketch))
        self.note.setText(MESSAGE)
        Gui.Selection.clearSelection()

    def _stop(self):
        if getattr(self, "_observing", False):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("sketchplane.py:138", _fw_err)
            self._observing = False

    def getStandardButtons(self):
        return int(QtWidgets.QDialogButtonBox.Ok.value | QtWidgets.QDialogButtonBox.Cancel.value) \
            if hasattr(QtWidgets.QDialogButtonBox.Ok, "value") else \
            int(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)

    def accept(self):
        self._stop()
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._stop()
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


def _picked_sketch():
    for o in Gui.Selection.getSelection():      # resolved: the sketch, not its Body
        if o.TypeId == SKETCH:
            return o
    return None


def open_for(sketch):
    """Open the Sketch Plane PM for sketch; False when another dialog is up."""
    if sketch is None or Gui.Control.activeDialog():
        return False
    gdoc = Gui.ActiveDocument
    if gdoc is not None and gdoc.getInEdit() is not None:
        try:
            gdoc.resetEdit()
        except Exception as _fw_err:
            _fw_log("sketchplane.py:177", _fw_err)
    Gui.Control.showDialog(SketchPlanePanel(sketch))
    return True


class EditSketchPlaneCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_MapSketch", "MenuText": "Edit Sketch Plane",
                "ToolTip": "Moves the sketch to another plane or flat face"}

    def IsActive(self):
        return _picked_sketch() is not None and not Gui.Control.activeDialog()

    def Activated(self):
        open_for(_picked_sketch())


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, EditSketchPlaneCommand())
