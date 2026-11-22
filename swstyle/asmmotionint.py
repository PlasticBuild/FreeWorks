# SPDX-License-Identifier: LGPL-2.1-or-later
""




import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import asmcore as ac


def find(pane, comps=None, step=1, stop_first=False):
    """[(frame, time s, label a, label b, volume mm^3)] over the study's calculated frames."""
    from . import asmtools
    if pane.frames <= 0 and not pane.calculate():
        return []
    asm = pane.asm
    keep = {c.Name: App.Placement(c.Placement) for c in ac.components(asm)}
    dt = float(pane.sim.cTimeStepOutput)
    out = []
    try:
        for i in range(1, pane.frames, max(1, int(step))):
            pane.show_frame(i)
            for hit in asmtools.interferences(asm, comps or None):
                if hit["a"] is hit["b"]:
                    continue
                out.append((i, (i - 1) * dt, hit["labels"][0], hit["labels"][1], hit["volume"]))
            if stop_first and out:
                break
    finally:
        for name, plc in keep.items():
            obj = asm.Document.getObject(name)
            if obj is not None:
                obj.Placement = plc
    return out


class FindPanel:
    def __init__(self, pane):
        from . import asmpm, asmtools
        self.pane, self.asm = pane, pane.asm
        box, lay = asmpm._box("Parts to Test", "Find Interferences", "ASSEMBLIES_INTERFERENCE_DETECTION")
        self.parts = QtWidgets.QListWidget()
        self.parts.setObjectName("FW_MotionIntParts")
        self.parts.setStyleSheet(asmpm.PICK_STYLE)
        self.parts.setFixedHeight(asmpm._rows(self.parts, 4))
        lay.addWidget(self.parts)
        self.comps = list(asmtools._picked_components(self.asm))
        for c in self.comps:
            self.parts.addItem(c.Label)
        if not self.comps:
            self.parts.addItem("All components")
        opt, olay = asmpm._box("Options")
        self.stop = QtWidgets.QCheckBox("Stop at first interference")
        self.stop.setObjectName("FW_MotionIntStop")
        olay.addWidget(self.stop)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Every"))
        self.step = QtWidgets.QSpinBox()
        self.step.setObjectName("FW_MotionIntStep")
        self.step.setRange(1, 100)
        self.step.setSuffix(" frame(s)")
        row.addWidget(self.step)
        row.addStretch(1)
        olay.addLayout(row)
        self.go = QtWidgets.QPushButton("Find Now")
        self.go.setObjectName("FW_MotionIntFind")
        self.go.clicked.connect(self.run)
        olay.addWidget(self.go)
        res, rlay = asmpm._box("Interference Results")
        self.table = QtWidgets.QTreeWidget()
        self.table.setObjectName("FW_MotionIntResults")
        self.table.setHeaderLabels(["Time", "Interfering Parts", "Volume"])
        self.table.setRootIsDecorated(False)
        self.table.itemClicked.connect(self._go_to)
        rlay.addWidget(self.table)
        self.summary = QtWidgets.QLabel("")
        self.summary.setObjectName("FW_MotionIntSummary")
        rlay.addWidget(self.summary)
        self.form = [box, opt, res]
        self.rows = []

    def run(self):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.rows = find(self.pane, self.comps or None, self.step.value(), self.stop.isChecked())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.table.clear()
        for frame, t, a, b, vol in self.rows:
            it = QtWidgets.QTreeWidgetItem(["%.2f sec" % t, "%s, %s" % (a, b), "%.2fmm^3" % vol])
            it.setData(0, QtCore.Qt.UserRole, frame)
            self.table.addTopLevelItem(it)
        times = sorted(set(round(r[1], 6) for r in self.rows))
        self.summary.setText("%d interference(s) at %d time step(s)" % (len(self.rows), len(times))
                             if self.rows else "No interferences found")
        return self.rows

    def _go_to(self, item, col=0):
        frame = item.data(0, QtCore.Qt.UserRole)
        self.pane.slider.setValue(int(frame))
        self.pane.show_frame(int(frame))
        a, b = item.text(1).split(", ", 1)
        Gui.Selection.clearSelection()
        for c in ac.components(self.asm):
            if c.Label in (a, b):
                Gui.Selection.addSelection(self.asm.Document.Name, self.asm.Name, c.Name + ".")

    def accept(self):
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


OPEN = []


def open_panel(pane):
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    panel = FindPanel(pane)
    OPEN[:] = [panel]
    Gui.Control.showDialog(panel)
    return panel
