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

import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

V = App.Vector
CMD = "FreeWorks_DrawRotateView"
_DLG = []


def _dependents(v):
    from . import drawselect as DS
    out = []
    for w in v.Document.Objects:
        if w is v or not w.isDerivedFrom("TechDraw::DrawViewPart"):
            continue
        try:
            if DS.parent_of(w) is v or getattr(w, "BaseView", None) is v:
                out.append(w)
        except Exception as _fw_err:
            _fw_log("drawrotate.py:42", _fw_err)
    return out


def _cross_lines(v):
    """{tag: (start, end)} of v's center mark cross lines (two lines with the same midpoint)."""
    lines = {}
    for tag in list(getattr(v, "SWCenterMarks", []) or []):
        try:
            ce = v.getCosmeticEdge(tag)
            a, b = V(ce.Start), V(ce.End)
        except Exception:
            continue
        if (a - b).Length > 1e-9:
            lines[tag] = (a, b)
    mids = {}
    for tag, (a, b) in lines.items():
        m = (a + b) * 0.5
        mids.setdefault((round(m.x, 5), round(m.y, 5)), []).append(tag)
    return {t: lines[t] for ts in mids.values() if len(ts) >= 2 for t in ts}


def _turn_marks(v, deg):
    """Turns v's center mark crosses deg about their centres (keeps them square to the sheet when the view
    turns -deg)."""
    ca, sa = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    n = 0
    for tag, (a, b) in _cross_lines(v).items():
        m = (a + b) * 0.5
        d = (b - a) * 0.5
        r = V(d.x * ca - d.y * sa, d.x * sa + d.y * ca, 0)
        try:
            ce = v.getCosmeticEdge(tag)
            ce.Start, ce.End = m - r, m + r
            if hasattr(v, "replaceCosmeticEdge"):      # FreeCAD 1.1 has none: the edge is changed in place
                v.replaceCosmeticEdge(ce)
            n += 1
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Rotate View center mark: %s\n" % error)
    if n:
        _turn_anchors(v, deg)
    return n


def _turn_anchors(v, deg):
    """The marks' remembered angle turns too, so a mark drawn again after a model change (follow_center_marks)
    stays as it was turned."""
    rows = list(getattr(v, "SWCenterMarkAnchors", []) or [])
    out = []
    for row in rows:
        f = row.split("|")
        if len(f) == 8:
            try:
                f[6] = "%.6g" % ((float(f[6]) + deg) % 360.0)
            except ValueError:
                pass
        out.append("|".join(f))
    if out != rows:
        v.SWCenterMarkAnchors = out


def rotate_to(v, angle, dependents=True, center_marks=True):
    """Sets view v's angle on the sheet (degrees); dependents turn by the same amount; center_marks False keeps
    the center mark crosses square to the sheet. Returns the views turned."""
    turn = (float(angle) - float(v.Rotation)) % 360.0
    if abs(turn) < 1e-9 or abs(turn - 360.0) < 1e-9:
        return []
    todo, done = [v], []
    while todo:
        w = todo.pop(0)
        if w in done:
            continue
        w.Rotation = (float(w.Rotation) + turn) % 360.0
        if not center_marks:
            _turn_marks(w, -turn)
        done.append(w)
        if dependents:
            todo += _dependents(w)
    v.Document.recompute()
    return done


class RotateViewDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWRotateViewDialog")
        self.setWindowTitle("Rotate Drawing View")
        self.setModal(False)
        lay = QtWidgets.QGridLayout(self)
        lay.addWidget(QtWidgets.QLabel("Drawing view angle:"), 0, 0)
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setObjectName("SWRotateViewAngle")
        self.angle.setRange(-360.0, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix(" deg")
        lay.addWidget(self.angle, 0, 1)
        apply_ = QtWidgets.QPushButton("Apply")
        apply_.setObjectName("SWRotateViewApply")
        apply_.setDefault(True)
        close = QtWidgets.QPushButton("Close")
        close.setObjectName("SWRotateViewClose")
        lay.addWidget(apply_, 0, 2)
        lay.addWidget(close, 1, 2)
        self.dependents = QtWidgets.QCheckBox("Dependent views update to change in orientation")
        self.dependents.setObjectName("SWRotateViewDependents")
        self.dependents.setChecked(True)
        self.marks = QtWidgets.QCheckBox("Rotate center marks with view")
        self.marks.setObjectName("SWRotateViewCenterMarks")
        self.marks.setChecked(True)
        lay.addWidget(self.dependents, 1, 0, 1, 2)
        lay.addWidget(self.marks, 2, 0, 1, 2)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("SWRotateViewStatus")
        lay.addWidget(self.status, 3, 0, 1, 3)
        apply_.clicked.connect(self.apply)
        close.clicked.connect(self.close)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.read)
        self._timer.start(300)
        self._last = None
        self.read()

    def views(self):
        try:
            from . import drawselect as DS
            return DS.picked_views()
        except Exception:
            return []

    def read(self):
        vs = self.views()
        key = tuple(v.Name for v in vs)
        if key == self._last:
            return
        self._last = key
        if vs:
            self.angle.setValue(float(vs[0].Rotation))
            self.status.setText("")
        else:
            self.status.setText("Select a drawing view to rotate.")

    def apply(self):
        vs = self.views()
        if not vs:
            self.status.setText("Select a drawing view to rotate.")
            return []
        doc = vs[0].Document
        doc.openTransaction("Rotate View")
        done = []
        if self.dependents.isChecked():
            # a picked view that turns with another picked view (its section, detail, projection...) is left to it
            under = set()
            for v in vs:
                todo = list(_dependents(v))
                while todo:
                    w = todo.pop()
                    if w.Name not in under:
                        under.add(w.Name)
                        todo += _dependents(w)
            vs = [v for v in vs if v.Name not in under] or vs
        try:
            for v in vs:
                if v not in done:
                    done += rotate_to(v, self.angle.value() % 360.0, self.dependents.isChecked(),
                                      self.marks.isChecked())
        finally:
            doc.commitTransaction()
        return done

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
    d = RotateViewDialog()
    _DLG.append(d)
    d.show()
    return d


class _Command:
    def GetResources(self):
        from . import drawings as D
        return {"MenuText": "Rotate View...", "Pixmap": D.pixmap("TechDraw_View"),
                "ToolTip": "Rotates a drawing view on the sheet by an angle (Rotate Drawing View)."}

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
