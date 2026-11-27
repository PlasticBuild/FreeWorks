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

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
    from . import pmboxes
except ImportError:
    Gui = None

TITLE = "Convert to Mesh Body"
COMMAND = "SWStyle_ConvertToMesh"


def deflection(size, level):
    """Refinement 1 (coarse) .. 10 (fine) -> (largest distance in mm, largest angle in degrees)."""
    size = max(size, 1e-3)
    t = (max(1, min(10, level)) - 1) / 9.0
    return size * (0.02 * (1 - t) + 0.0005 * t), 30.0 * (1 - t) + 5.0 * t


def mesh_of(shape, distance, angle):
    import math
    import MeshPart
    return MeshPart.meshFromShape(Shape=shape, LinearDeflection=max(distance, 1e-4),
                                  AngularDeflection=math.radians(max(angle, 0.5)), Relative=False)


def _shape_owner(obj):
    """What carries the body's shape: the Body for a feature inside it."""
    body = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
    if body is not None and body.TypeId == "PartDesign::Body":
        return body
    return obj


if Gui is not None:
    class MeshPanel:
        def __init__(self, doc, picks=()):
            self.doc = doc
            self.sources = []
            self.meshes = []
            self.opened = False
            page = QtWidgets.QWidget()
            page.setWindowTitle("Selections")
            page.setProperty("swstyle_pm_title", TITLE)
            page.setProperty("swstyle_pm_icon", "FEATURES_CONVERT_TO_MESH")
            lay = QtWidgets.QVBoxLayout(page)
            lay.addWidget(QtWidgets.QLabel("Bodies to convert"))
            self.list = QtWidgets.QListWidget(page)
            self.list.setObjectName("SWStyle_MeshBodies")
            self.list.setMaximumHeight(64)
            pmboxes.mark(self.list, True)
            lay.addWidget(self.list)
            self.keep = QtWidgets.QCheckBox("Keep original body", page)
            self.keep.setObjectName("SWStyle_MeshKeep")
            self.keep.setChecked(True)
            lay.addWidget(self.keep)
            fine = QtWidgets.QWidget()
            fine.setWindowTitle("Mesh Refinement")
            form = QtWidgets.QVBoxLayout(fine)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Coarse"))
            self.level = QtWidgets.QSlider(QtCore.Qt.Horizontal, fine)
            self.level.setObjectName("SWStyle_MeshLevel")
            self.level.setRange(1, 10)
            self.level.setValue(5)
            row.addWidget(self.level, 1)
            row.addWidget(QtWidgets.QLabel("Fine"))
            form.addLayout(row)
            self.advanced = QtWidgets.QCheckBox("Advanced refinement", fine)
            self.advanced.setObjectName("SWStyle_MeshAdvanced")
            form.addWidget(self.advanced)
            grid = QtWidgets.QFormLayout()
            self.distance = QtWidgets.QDoubleSpinBox(fine)
            self.distance.setObjectName("SWStyle_MeshDistance")
            self.distance.setDecimals(4)
            self.distance.setRange(0.0001, 1000.0)
            self.distance.setSuffix(" mm")
            self.angle = QtWidgets.QDoubleSpinBox(fine)
            self.angle.setObjectName("SWStyle_MeshAngle")
            self.angle.setRange(0.5, 90.0)
            self.angle.setSuffix("°")
            grid.addRow("Maximum distance", self.distance)
            grid.addRow("Maximum angle", self.angle)
            form.addLayout(grid)
            self.info = QtWidgets.QLabel("", fine)
            self.info.setObjectName("SWStyle_MeshInfo")
            form.addWidget(self.info)
            self.form = [page, fine]
            for obj in picks:
                self._add(obj)
            self._sync_numbers()
            self.level.valueChanged.connect(lambda _v: (self._sync_numbers(), self.update()))
            self.advanced.toggled.connect(lambda _on: (self._enable(), self.update()))
            self.distance.valueChanged.connect(lambda _v: self.update() if self.advanced.isChecked() else None)
            self.angle.valueChanged.connect(lambda _v: self.update() if self.advanced.isChecked() else None)
            self.keep.toggled.connect(lambda _on: self._show_sources())
            self._enable()
            self.update()
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def _size(self):
            sizes = [s.Shape.BoundBox.DiagonalLength for s in self.sources if not s.Shape.isNull()]
            return max(sizes) if sizes else 100.0

        def _sync_numbers(self):
            d, a = deflection(self._size(), self.level.value())
            for w, v in ((self.distance, d), (self.angle, a)):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)

        def _enable(self):
            on = self.advanced.isChecked()
            self.distance.setEnabled(on)
            self.angle.setEnabled(on)
            self.level.setEnabled(not on)

        def _add(self, obj):
            obj = _shape_owner(obj)
            shape = getattr(obj, "Shape", None)
            if shape is None or shape.isNull() or not (shape.Solids or shape.Faces) or obj in self.meshes:
                return False
            if obj in self.sources:
                self.sources.remove(obj)
            else:
                self.sources.append(obj)
            self.list.clear()
            self.list.addItems([s.Label for s in self.sources])
            return True

        def addSelection(self, doc, name, sub, pnt):
            if doc != self.doc.Name:
                return
            obj = self.doc.getObject(name)
            if obj is None:
                return
            if sub and "." in sub:
                try:
                    inner = obj.getSubObject(sub.rsplit(".", 1)[0] + ".", retType=1)
                    obj = inner or obj
                except Exception as _fw_err:
                    _fw_log("meshbody.py:164", _fw_err)
            from . import safe_later as _sl; _sl.later(0, lambda: self._picked(obj), self, "advanced")

        def _picked(self, obj):
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("meshbody.py:171", _fw_err)
            if self._add(obj):
                if not self.advanced.isChecked():
                    self._sync_numbers()
                self.update()

        def _clear(self):
            for m in self.meshes:
                try:
                    self.doc.removeObject(m.Name)
                except Exception as _fw_err:
                    _fw_log("meshbody.py:182", _fw_err)
            self.meshes = []

        def update(self):
            import Mesh
            if self.sources and not self.opened:
                self.doc.openTransaction(TITLE)
                self.opened = True
            self._clear()
            facets = 0
            for src in self.sources:
                mesh = mesh_of(src.Shape, self.distance.value(), self.angle.value())
                feat = self.doc.addObject("Mesh::Feature", "MeshBody")
                feat.Mesh = Mesh.Mesh(mesh)
                feat.Label = "%s-Mesh" % src.Label
                self.meshes.append(feat)
                facets += feat.Mesh.CountFacets
            self.doc.recompute()
            self.info.setText("%d facets" % facets if self.sources else "Select bodies to convert.")
            self._show_sources()

        def _show_sources(self):
            for src in self.sources:
                try:
                    src.ViewObject.Visibility = self.keep.isChecked() and not self.meshes
                except Exception as _fw_err:
                    _fw_log("meshbody.py:208", _fw_err)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def _close(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("meshbody.py:217", _fw_err)
            Gui.Control.closeDialog()

        def accept(self):
            if not self.meshes:
                self.info.setText("Select bodies to convert.")
                return False
            for src in self.sources:
                try:
                    src.ViewObject.Visibility = False
                except Exception as _fw_err:
                    _fw_log("meshbody.py:228", _fw_err)
            if not self.keep.isChecked():
                for src in self.sources:
                    try:
                        if src.TypeId != "PartDesign::Body":
                            self.doc.removeObject(src.Name)
                    except Exception as _fw_err:
                        _fw_log("meshbody.py:235", _fw_err)
            self.doc.commitTransaction()
            self._close()
            return True

        def reject(self):
            self._clear()
            for src in self.sources:
                try:
                    src.ViewObject.Visibility = True
                except Exception as _fw_err:
                    _fw_log("meshbody.py:246", _fw_err)
            if self.opened:
                self.doc.abortTransaction()
            self.doc.recompute()
            self._close()
            return True

    class Command:
        def GetResources(self):
            return {"MenuText": TITLE, "Pixmap": "Mesh_FromPartShape",
                    "ToolTip": "Converts solid or surface bodies to mesh bodies."}

        def IsActive(self):
            return App.ActiveDocument is not None and not Gui.Control.activeDialog()

        def Activated(self):
            doc = App.ActiveDocument
            picks = [s.Object for s in Gui.Selection.getSelectionEx(doc.Name)]
            QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(MeshPanel(doc, picks)))


def register():
    if Gui is None:
        return
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added (%s)\n" % (TITLE, error))
