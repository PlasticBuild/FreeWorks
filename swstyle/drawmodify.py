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

CMD = "FreeWorks_DrawModifySketch"
_DLG = []


def _sheet_sketches():
    return [o for o in Gui.Selection.getSelection() if getattr(o, "SWAnnotation", "") == "SheetSketch"]


def _views():
    try:
        from . import drawselect as DS
        return [v for v in DS.picked_views() if getattr(v, "SWSketchEntities", None)]
    except Exception:
        return []


def modify_view(v, dx=0.0, dy=0.0, deg=0.0, factor=1.0, about=None):
    """Moves (sheet mm), turns (degrees) and scales the whole drawing sketch of view v about the sketch origin
    (the view's centre) or about=(x, y) in the view's geometry. Fixed entities stay. Returns the entities moved."""
    from . import drawsketch as SK, drawsketchedit as SE, drawviews as DV
    k = DV.view_scale(v)
    c = about or (0.0, 0.0)
    ents = SK.entities(v)
    todo = [i for i in range(len(ents)) if not SE.fixed(v, i)]
    out = []
    for i in todo:
        kind, _t, pts = ents[i]
        if abs(factor - 1.0) > 1e-12:
            pts = SE.scaled(pts, c, factor)
        if abs(deg) > 1e-12:
            pts = SE.rotated(pts, c, deg)
        pts = SE.moved(pts, dx / k, dy / k)
        out.append((kind, pts))
    for i in sorted(todo, reverse=True):
        SK.consume(v, i)
    for kind, pts in out:
        SE.add(v, kind, pts)
    return len(out)


def modify_sheet_sketch(s, dx=0.0, dy=0.0, deg=0.0, factor=1.0):
    """The same on a sheet sketch graphic, about its own centre."""
    s.X, s.Y = float(s.X) + dx, float(s.Y) + dy
    if abs(deg) > 1e-12:
        s.Rotation = (float(s.Rotation) + deg) % 360.0
    if abs(factor - 1.0) > 1e-12 and "Scale" in s.PropertiesList:
        try:
            s.ScaleType = "Custom"
        except Exception as _fw_err:
            _fw_log("drawmodify.py:77", _fw_err)
        s.Scale = float(s.Scale) * factor
    return 1


class ModifySketchDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWModifySketchDialog")
        self.setWindowTitle("Modify Sketch")
        self.setModal(False)
        lay = QtWidgets.QVBoxLayout(self)

        def spin(name, lo, hi, val, suffix):
            w = QtWidgets.QDoubleSpinBox(self)
            w.setObjectName(name)
            w.setRange(lo, hi)
            w.setDecimals(3)
            w.setValue(val)
            w.setSuffix(suffix)
            return w

        scale = QtWidgets.QGroupBox("Scale About", self)
        g = QtWidgets.QGridLayout(scale)
        self.origin = QtWidgets.QRadioButton("Sketch origin", scale)
        self.origin.setObjectName("SWModifyAboutOrigin")
        self.origin.setChecked(True)
        self.moveable = QtWidgets.QRadioButton("Moveable origin", scale)
        self.moveable.setObjectName("SWModifyAboutMoveable")
        g.addWidget(self.origin, 0, 0)
        g.addWidget(self.moveable, 0, 1)
        self.ox = spin("SWModifyOriginX", -1e5, 1e5, 0.0, " mm")
        self.oy = spin("SWModifyOriginY", -1e5, 1e5, 0.0, " mm")
        g.addWidget(QtWidgets.QLabel("Origin X:"), 1, 0)
        g.addWidget(self.ox, 1, 1)
        g.addWidget(QtWidgets.QLabel("Origin Y:"), 2, 0)
        g.addWidget(self.oy, 2, 1)
        self.factor = spin("SWModifyFactor", 0.001, 1000.0, 1.0, "")
        g.addWidget(QtWidgets.QLabel("Factor:"), 3, 0)
        g.addWidget(self.factor, 3, 1)
        lay.addWidget(scale)
        move = QtWidgets.QGroupBox("Translate", self)
        g = QtWidgets.QGridLayout(move)
        self.dx = spin("SWModifyX", -1e5, 1e5, 0.0, " mm")
        self.dy = spin("SWModifyY", -1e5, 1e5, 0.0, " mm")
        g.addWidget(QtWidgets.QLabel("X value:"), 0, 0)
        g.addWidget(self.dx, 0, 1)
        g.addWidget(QtWidgets.QLabel("Y value:"), 1, 0)
        g.addWidget(self.dy, 1, 1)
        lay.addWidget(move)
        rot = QtWidgets.QGroupBox("Rotate", self)
        g = QtWidgets.QGridLayout(rot)
        self.deg = spin("SWModifyRotate", -360.0, 360.0, 0.0, " deg")
        g.addWidget(self.deg, 0, 0)
        lay.addWidget(rot)
        self.status = QtWidgets.QLabel("", self)
        self.status.setObjectName("SWModifyStatus")
        lay.addWidget(self.status)
        row = QtWidgets.QHBoxLayout()
        apply_ = QtWidgets.QPushButton("Apply", self)
        apply_.setObjectName("SWModifyApply")
        apply_.setDefault(True)
        close = QtWidgets.QPushButton("Close", self)
        close.setObjectName("SWModifyClose")
        row.addStretch(1)
        row.addWidget(apply_)
        row.addWidget(close)
        lay.addLayout(row)
        apply_.clicked.connect(self.apply)
        close.clicked.connect(self.close)
        self.moveable.toggled.connect(self._enable)
        self._enable()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.read)
        self._timer.start(300)
        self.read()

    def _enable(self, *_):
        if not getattr(self, "_fw_live", False):     # never greyed: an origin typed turns Moveable origin on
            self._fw_live = True
            from . import drawlive as DL
            DL.sets(self.moveable, True, self.ox, self.oy)

    def read(self):
        if _views() or _sheet_sketches():
            self.status.setText("")
        else:
            self.status.setText("Select a drawing view with a sketch, or a sketch on the sheet.")

    def apply(self):
        views, sketches = _views(), _sheet_sketches()
        if not views and not sketches:
            self.read()
            return 0
        doc = (views or sketches)[0].Document
        doc.openTransaction("Modify Sketch")
        n = 0
        try:
            args = (self.dx.value(), self.dy.value(), self.deg.value(), self.factor.value())
            for v in views:
                about = None
                if self.moveable.isChecked():
                    from . import drawviews as DV
                    k = DV.view_scale(v)
                    about = (self.ox.value() / k, self.oy.value() / k)
                n += modify_view(v, *args, about=about)
            for s in sketches:
                n += modify_sheet_sketch(s, *args)
            doc.recompute()
        finally:
            doc.commitTransaction()
        self.status.setText("%d sketch entities changed." % n)
        return n

    def closeEvent(self, event):
        self._timer.stop()
        if self in _DLG:
            _DLG.remove(self)
        super().closeEvent(event)


def show():
    if _DLG:
        _DLG[0].raise_()
        _DLG[0].activateWindow()
        return _DLG[0]
    d = ModifySketchDialog()
    _DLG.append(d)
    d.show()
    return d


class _Command:
    def GetResources(self):
        from . import drawings as D
        return {"MenuText": "Modify...", "Pixmap": D.pixmap("Sketcher_Move"),
                "ToolTip": "Moves, turns or scales the whole drawing sketch (Modify Sketch)."}

    def IsActive(self):
        try:
            from . import drawings as D
            return D.active_page() is not None
        except Exception:
            return False

    def Activated(self, checked=None):
        show()


def install():
    if CMD not in Gui.listCommands():
        Gui.addCommand(CMD, _Command())
