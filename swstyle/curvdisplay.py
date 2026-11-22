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

from . import paths

MESH_COLOUR = (0.2, 0.2, 0.2)
COMB_COLOUR = (0.85, 0.1, 0.85)


def _p():
    return paths.params()


def mesh_lines(shape, density=5):
    """[[points]] of the faces' u/v iso lines, density lines each way (Mesh preview)."""
    out = []
    n = max(1, int(density))
    for f in getattr(shape, "Faces", []):
        try:
            u0, u1, v0, v1 = f.ParameterRange
            s = f.Surface
            for i in range(1, n + 1):
                u = u0 + (u1 - u0) * i / (n + 1)
                v = v0 + (v1 - v0) * i / (n + 1)
                out.append([s.value(u, v0 + (v1 - v0) * k / 20.0) for k in range(21)])
                out.append([s.value(u0 + (u1 - u0) * k / 20.0, v) for k in range(21)])
        except Exception:
            continue
    return out


def comb_lines(shape, scale=10.0, density=20, direction=1):
    """[[base, tip]] of curvature combs across each face in one iso direction (Curvature combs): the
    tooth length is the normal curvature times scale (in mm per 1/mm)."""
    out = []
    n = max(2, int(density))
    for f in getattr(shape, "Faces", []):
        try:
            u0, u1, v0, v1 = f.ParameterRange
            for row in (0.25, 0.5, 0.75):
                for k in range(n + 1):
                    if direction == 1:
                        u, v = u0 + (u1 - u0) * k / n, v0 + (v1 - v0) * row
                    else:
                        u, v = u0 + (u1 - u0) * row, v0 + (v1 - v0) * k / n
                    p = f.valueAt(u, v)
                    nrm = f.normalAt(u, v)
                    try:
                        c = f.curvatureAt(u, v)[0 if direction == 1 else 1]
                    except Exception:
                        c = 0.0
                    out.append([p, p + nrm * (c * scale * 100.0)])
        except Exception:
            continue
    return out


class Overlay:
    """Lines drawn over the model in the active 3D view."""

    def __init__(self):
        self.node = None

    def draw(self, lines, colour, width=1.0):
        self.clear()
        if not lines or not App.GuiUp or Gui.ActiveDocument is None:
            return 0
        from pivy import coin
        sep = coin.SoSeparator()
        light = coin.SoLightModel()
        light.model.setValue(coin.SoLightModel.BASE_COLOR)
        col = coin.SoBaseColor()
        col.rgb.setValue(*colour)
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(width)
        pts, counts = [], []
        for line in lines:
            pts += [(p.x, p.y, p.z) for p in line]
            counts.append(len(line))
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(pts), pts)
        ls = coin.SoLineSet()
        ls.numVertices.setValues(0, len(counts), counts)
        for c in (light, col, style, coords, ls):
            sep.addChild(c)
        Gui.ActiveDocument.ActiveView.getSceneGraph().addChild(sep)
        self.node = sep
        return len(lines)

    def clear(self):
        if self.node is not None:
            try:
                Gui.ActiveDocument.ActiveView.getSceneGraph().removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("curvdisplay.py:113", _fw_err)
        self.node = None


class CurvatureDisplay(QtWidgets.QGroupBox):
    """The group itself. shape() gives the feature's current shape; refresh() redraws (call it after
    each recompute of the feature); close() takes everything away."""

    def __init__(self, shape, parent=None):
        super().__init__("Curvature Display", parent)
        self.setObjectName("SWCurvatureDisplay")
        self.shape = shape
        self.mesh_overlay, self.comb_overlay = Overlay(), Overlay()
        self._zebra_was = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.mesh = QtWidgets.QCheckBox("Mesh preview")
        self.mesh.setObjectName("SWCurvMesh")
        lay.addWidget(self.mesh)
        row = QtWidgets.QHBoxLayout()
        self.mesh_label = QtWidgets.QLabel("Mesh density:")
        row.addWidget(self.mesh_label)
        self.mesh_density = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.mesh_density.setRange(1, 20)
        self.mesh_density.setValue(_p().GetInt("CurvMeshDensity", 5))
        row.addWidget(self.mesh_density, 1)
        lay.addLayout(row)
        self.zebra = QtWidgets.QCheckBox("Zebra stripes")
        self.zebra.setObjectName("SWCurvZebra")
        lay.addWidget(self.zebra)
        self.combs = QtWidgets.QCheckBox("Curvature combs")
        self.combs.setObjectName("SWCurvCombs")
        lay.addWidget(self.combs)
        row = QtWidgets.QHBoxLayout()
        self.dir1 = QtWidgets.QCheckBox("Direction 1")
        self.dir1.setChecked(True)
        self.dir2 = QtWidgets.QCheckBox("Direction 2")
        row.addWidget(self.dir1)
        row.addWidget(self.dir2)
        lay.addLayout(row)

        row = QtWidgets.QGridLayout()
        row.setVerticalSpacing(2)
        self.scale_label = QtWidgets.QLabel("Scale:")
        row.addWidget(self.scale_label, 0, 0)
        self.scale = QtWidgets.QSpinBox()
        self.scale.setRange(1, 100)
        self.scale.setValue(_p().GetInt("CurvCombScale", 10))
        row.addWidget(self.scale, 0, 1)
        self.density_label = QtWidgets.QLabel("Density:")
        row.addWidget(self.density_label, 1, 0)
        self.density = QtWidgets.QSpinBox()
        self.density.setRange(2, 100)
        self.density.setValue(_p().GetInt("CurvCombDensity", 20))
        row.addWidget(self.density, 1, 1)
        row.setColumnStretch(1, 1)
        lay.addLayout(row)
        for w in (self.mesh, self.combs, self.dir1, self.dir2):
            w.toggled.connect(self.refresh)
        for w in (self.mesh_density, self.scale, self.density):
            w.valueChanged.connect(self.refresh)
        self.zebra.toggled.connect(self._zebra)
        self._enable()
        self._seen = None
        self.timer = QtCore.QTimer(self)          # the feature rebuilt: draw again
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._watch)
        self.timer.start()

    def _watch(self):
        if not (self.mesh.isChecked() or self.combs.isChecked()):
            return
        try:
            sh = self.shape()
            key = (round(sh.Area, 6), len(sh.Faces)) if sh is not None and not sh.isNull() else None
        except Exception:
            key = None
        if key != self._seen:
            self.refresh()

    def _enable(self):
        """The mesh density row shows only with Mesh preview on, the comb rows only with Curvature combs on
        (greyed rows would be dead controls)."""
        for w in (self.mesh_label, self.mesh_density):
            w.setVisible(self.mesh.isChecked())
        for w in (self.dir1, self.dir2, self.scale_label, self.scale, self.density_label, self.density):
            w.setVisible(self.combs.isChecked())

    def _zebra(self, on):
        try:
            from . import evaluate2
            z = evaluate2.ZEBRA
            if self._zebra_was is None:
                self._zebra_was = bool(z.on)
            (z.show if on else z.hide)()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: curvature display zebra: %s\n" % error)

    def refresh(self, *args):
        self._enable()
        p = _p()
        p.SetInt("CurvMeshDensity", self.mesh_density.value())
        p.SetInt("CurvCombScale", self.scale.value())
        p.SetInt("CurvCombDensity", self.density.value())
        try:
            shape = self.shape()
        except Exception:
            shape = None
        try:
            self._seen = (round(shape.Area, 6), len(shape.Faces)) if shape is not None and not shape.isNull() else None
        except Exception:
            self._seen = None
        if shape is None or shape.isNull():
            self.mesh_overlay.clear()
            self.comb_overlay.clear()
            return
        if self.mesh.isChecked():
            self.mesh_overlay.draw(mesh_lines(shape, self.mesh_density.value()), MESH_COLOUR)
        else:
            self.mesh_overlay.clear()
        if self.combs.isChecked():
            lines = []
            if self.dir1.isChecked():
                lines += comb_lines(shape, self.scale.value(), self.density.value(), 1)
            if self.dir2.isChecked():
                lines += comb_lines(shape, self.scale.value(), self.density.value(), 2)
            self.comb_overlay.draw(lines, COMB_COLOUR)
        else:
            self.comb_overlay.clear()

    def close(self):
        self.timer.stop()
        self.mesh_overlay.clear()
        self.comb_overlay.clear()
        if self.zebra.isChecked() and not self._zebra_was:
            try:
                from . import evaluate2
                evaluate2.ZEBRA.hide()
            except Exception as _fw_err:
                _fw_log("curvdisplay.py:246", _fw_err)
