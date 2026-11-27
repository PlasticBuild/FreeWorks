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

TITLE = "Face Curves"
MESSAGE = "Select a face."


def _face_of(obj, sub):
    try:
        f = obj.Shape.getElement(sub)
        return f if f.ShapeType == "Face" else None
    except Exception:
        return None


class FaceCurvesPanel:
    def __init__(self, picks=()):
        self.doc = App.ActiveDocument
        self.face = None                 # (obj, sub)
        self.point = None                # Position: the clicked point
        self.obj = None                  # the preview
        self.doc.openTransaction(TITLE)
        try:
            self.form = form = QtWidgets.QWidget()
            form.setObjectName("SWFaceCurvesPM")
            form.setWindowTitle(TITLE)
            lay = QtWidgets.QVBoxLayout(form)
            sel = QtWidgets.QGroupBox("Selections", form)
            sl = QtWidgets.QVBoxLayout(sel)
            self.list = QtWidgets.QListWidget(sel)
            self.list.setObjectName("SWFaceCurvesFace")
            self.list.setFixedHeight(40)
            sl.addWidget(self.list)
            row = QtWidgets.QHBoxLayout()
            self.mesh = QtWidgets.QRadioButton("Mesh", sel)
            self.mesh.setObjectName("SWFaceCurvesMesh")
            self.position = QtWidgets.QRadioButton("Position", sel)
            self.position.setObjectName("SWFaceCurvesPosition")
            self.mesh.setChecked(True)
            row.addWidget(self.mesh); row.addWidget(self.position)
            sl.addLayout(row)
            self.boxes = {}
            for key, label in (("d1", "Direction 1"), ("d2", "Direction 2")):
                line = QtWidgets.QHBoxLayout()
                on = QtWidgets.QCheckBox(label, sel)
                on.setObjectName("SWFaceCurves%sOn" % key.upper())
                on.setChecked(True)
                n = QtWidgets.QSpinBox(sel)
                n.setObjectName("SWFaceCurves%sCount" % key.upper())
                n.setRange(1, 200)
                n.setValue(5)
                n.setToolTip("Number of curves")
                line.addWidget(on); line.addWidget(n, 1)
                sl.addLayout(line)
                self.boxes[key] = (on, n)
            lay.addWidget(sel)
            opt = QtWidgets.QGroupBox("Options", form)
            ol = QtWidgets.QVBoxLayout(opt)
            self.constrain = QtWidgets.QCheckBox("Constrain to model", opt)
            self.constrain.setObjectName("SWFaceCurvesConstrain")
            self.constrain.setChecked(True)
            self.holes = QtWidgets.QCheckBox("Ignore holes", opt)
            self.holes.setObjectName("SWFaceCurvesIgnoreHoles")
            ol.addWidget(self.constrain); ol.addWidget(self.holes)
            lay.addWidget(opt)
            self.note = QtWidgets.QLabel(MESSAGE, form)
            self.note.setObjectName("SWFaceCurvesNote")
            self.note.setWordWrap(True)
            lay.addWidget(self.note)
            lay.addStretch(1)
            for w in (self.mesh, self.position, self.holes):
                w.toggled.connect(self.update)
            for on, n in self.boxes.values():
                on.toggled.connect(self.update)
                n.valueChanged.connect(self.update)
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)
            self._observing = True
            for obj, sub in picks:
                self.take(obj.Name, sub, None)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise

    # selection
    def addSelection(self, doc, obj, sub, pnt):
        if doc != self.doc.Name:
            return
        from . import safe_later as _sl; _sl.later(0, lambda o=obj, s=sub, p=pnt: self.take(o, s, p), self, "position")

    def take(self, name, sub, pnt):
        obj = self.doc.getObject(name)
        sub = (sub or "").rsplit(".", 1)[-1]
        if obj is None or obj == self.obj or _face_of(obj, sub) is None:
            return
        if self.position.isChecked() and self.face == (obj, sub) and pnt is not None:
            self.point = App.Vector(*pnt) if not isinstance(pnt, App.Vector) else pnt
        else:
            self.face = (obj, sub)
            if pnt is not None and self.point is None:
                self.point = App.Vector(*pnt) if not isinstance(pnt, App.Vector) else pnt
        Gui.Selection.clearSelection()
        self.update()

    def values(self):
        (o1, n1), (o2, n2) = self.boxes["d1"], self.boxes["d2"]
        return (n1.value() if o1.isChecked() else 0), (n2.value() if o2.isChecked() else 0)

    def update(self, *args):
        self.list.clear()
        if self.face is None:
            self.note.setText(MESSAGE)
            return
        obj, sub = self.face
        self.list.addItem("%s@%s" % (sub, obj.Label))
        n1, n2 = self.values()
        for key in ("d1", "d2"):
            self.boxes[key][1].setEnabled(self.mesh.isChecked() and self.boxes[key][0].isChecked())
        if self.obj is None:
            from . import sketchextras
            self.obj = sketchextras.make_face_curves(obj, sub, n1, n2, transaction=False)
        fc = self.obj
        fc.Face = (obj, [sub])
        fc.Direction1, fc.Direction2 = n1, n2
        fc.Mode = "Position" if self.position.isChecked() else "Mesh"
        if self.point is not None:
            fc.PositionPoint = self.point
        fc.IgnoreHoles = self.holes.isChecked()
        self.doc.recompute()
        self.note.setText("Click on the face where the curves go through." if self.position.isChecked() else "")

    def _stop(self):
        if getattr(self, "_observing", False):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("facecurvespm.py:157", _fw_err)
            self._observing = False

    def getStandardButtons(self):
        ok, cancel = QtWidgets.QDialogButtonBox.Ok, QtWidgets.QDialogButtonBox.Cancel
        return (ok.value | cancel.value) if hasattr(ok, "value") else int(ok | cancel)

    def accept(self):
        self._stop()
        self.made = []
        if self.obj is not None:

            from . import sketchextras
            self.made = sketchextras.face_curves_to_sketches(self.obj, self.constrain.isChecked())
            self.obj = None
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


def open_panel(picks=()):
    if App.ActiveDocument is None or Gui.Control.activeDialog():
        return None
    panel = FaceCurvesPanel(picks)
    Gui.Control.showDialog(panel)
    return panel
