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

from . import refplane

TITLE = "Axis"


ICONS = {
    "Line": "SKETCH_LINE", "Planes": "VIEW_PRIMARY_PLANES", "Points": "QS_POINT",
    "Cylinder": "FREESHAPE_CYLINDER", "PointFace": "REFGEO_POINT"}
def _type_icon(key):
    try:
        from . import icons
        icon = icons.family(ICONS.get(key, ""))
        return icon if icons.paints(icon) else None
    except Exception:
        return None


TYPES = (
    ("Line", "One Line/Edge/Axis"),
    ("Planes", "Two Planes"),
    ("Points", "Two Points/Vertices"),
    ("Cylinder", "Cylindrical/Conical Face"),
    ("PointFace", "Point and Face/Plane"),
)


class AxisError(Exception):
    pass


def guess(kinds):
    ""
    k = sorted(kinds)
    if k == ["line"]:
        return "Line"
    if k == ["plane", "plane"]:
        return "Planes"
    if k == ["point", "point"]:
        return "Points"
    if k == ["cylinder"]:
        return "Cylinder"
    if k in (["plane", "point"], ["cylinder", "point"]):
        return "PointFace"
    return None


def _round_edge(obj, sub):
    """A circular (or elliptic) edge of a cylinder or cone face, for FreeCAD's axis of curvature."""
    # one shape for the face and the edge list: an assembly component (App::Link) makes a new shape on
    # each .Shape read, and isSame never matches across two of them (asmax-fix01)
    whole = obj.Shape
    face = whole.getElement(sub) if sub else None
    edges = [e for e in face.Edges if type(e.Curve).__name__ in ("Circle", "Ellipse")] if face is not None else []
    if not edges or not sub:
        raise AxisError("The face has no round edge to take its axis from.")
    for i, e in enumerate(whole.Edges):
        if any(e.isSame(x) for x in edges):
            return "Edge%d" % (i + 1)
    raise AxisError("The face has no round edge to take its axis from.")


def recipe(picks, way=None):
    """(support, FreeCAD mode) for the picks [(obj, sub, kind)], else AxisError with what is missing."""
    if not picks:
        raise AxisError("Select references to define the axis.")
    kinds = [p[2] for p in picks]
    way = way or guess(kinds)
    want = {
        "Line": (["line"], "Select one line, edge or axis."),
        "Planes": (["plane", "plane"], "Select two planes or flat faces."),
        "Points": (["point", "point"], "Select two points or vertices."),
        "Cylinder": (["cylinder"], "Select one cylindrical or conical face."),
    }
    if way in want:
        need, message = want[way]
        if sorted(kinds) != need:
            raise AxisError(message)
        if way == "Line":
            return [picks[0][:2]], "TwoPointLine"
        if way == "Planes":
            a, b = (refplane._plane_of(*p[:2]) for p in picks)
            if abs(abs(a[1].dot(b[1])) - 1.0) < 1e-9:
                raise AxisError("The two planes are parallel and do not meet.")
            return [p[:2] for p in picks], "IntersectionLine"
        if way == "Points":
            a, b = (refplane._point_of(*p[:2]) for p in picks)
            if (a - b).Length < 1e-7:
                raise AxisError("The two points are the same point.")
            return [p[:2] for p in picks], "TwoPointLine"
        obj, sub = picks[0][:2]
        return [(obj, _round_edge(obj, sub))], "AxisOfCurvature"
    if way == "PointFace":
        if sorted(kinds) not in (["plane", "point"], ["cylinder", "point"]):
            raise AxisError("Select one point and one face or plane.")
        point = next(p for p in picks if p[2] == "point")
        face = next(p for p in picks if p[2] != "point")
        return [face[:2], point[:2]], "FaceNormal"
    raise AxisError("These selections do not define an axis. Select an edge, two planes, two points, "
                    "a cylindrical face, or a point and a face.")


def place(line, support, mode):
    try:
        line.MapMode = "Deactivated"        # a new support may not suit the last mode
        line.AttachmentSupport = support
        line.MapMode = mode
    except Exception as error:
        raise AxisError(str(error))
    line.Document.recompute()
    if "Invalid" in line.State:
        raise AxisError(line.getStatusString())


class _Escape(QtCore.QObject):
    ""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) and event.key() == QtCore.Qt.Key_Escape \
                and not (event.modifiers() & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)):
            if t == QtCore.QEvent.KeyPress and current() is self.panel:
                QtCore.QTimer.singleShot(0, self.panel.reject)
            return True
        return False


_current = None


def current():
    """The open Axis PropertyManager, or None."""
    return _current


class AxisPanel:
    ""

    def __init__(self, doc, body, picks=()):
        global _current
        _current = self
        self.doc, self.body = doc, body
        self.picks = []         # [(obj, sub, kind)]
        self.way = None         # a button pressed by hand, else the guess
        self.line = None
        self.opened = False
        self.ok = False
        box = QtWidgets.QWidget()
        box.setWindowTitle("Selections")
        box.setProperty("swstyle_pm_title", TITLE)
        box.setProperty("swstyle_pm_icon", "REFGEO_AXIS")
        lay = QtWidgets.QVBoxLayout(box)
        self.list = QtWidgets.QListWidget(box)
        self.list.setObjectName("SWAxisSelections")
        self.list.setFixedHeight(64)
        lay.addWidget(self.list)
        try:

            from . import pmboxes
            pmboxes.bind(self.list, self.remove_pick, self.clear_picks)
        except Exception as _fw_err:
            _fw_log("refaxis.py:bind", _fw_err)
        self.buttons = {}
        group = QtWidgets.QButtonGroup(box)
        for key, label in TYPES:
            b = QtWidgets.QToolButton(box)
            b.setObjectName("SWAxis%s" % key)
            b.setText(label)
            b.setCheckable(True)
            b.setAutoRaise(True)
            icon = _type_icon(key)
            if icon is not None:
                b.setIcon(icon)
                b.setIconSize(QtCore.QSize(20, 20))
                b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            else:
                b.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
            b.clicked.connect(lambda _c=False, k=key: self.set_way(k))
            group.addButton(b)
            lay.addWidget(b)
            self.buttons[key] = b
        self.message = QtWidgets.QLabel("", box)
        self.message.setObjectName("SWAxisMessage")
        self.message.setWordWrap(True)
        lay.addWidget(self.message)
        self.form = box
        for obj, sub in picks:
            self._add(obj, sub)
        self.update()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        self._views = []
        self._esc = _Escape(self)
        try:
            # stock FreeCAD 1.1: findChildren(QOpenGLWidget) finds nothing from Python
            for w in [v for v in Gui.getMainWindow().findChildren(QtWidgets.QWidget) if v.inherits("QOpenGLWidget")]:
                w.installEventFilter(self._esc)
                self._views.append(w)
        except Exception as _fw_err:
            _fw_log("refaxis.py:228", _fw_err)

    # --- picks
    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        if obj is None:
            return
        obj, sub = refplane.resolve(obj, sub)
        if obj is self.line:
            return
        QtCore.QTimer.singleShot(0, lambda: self._picked(obj, sub))

    def _picked(self, obj, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("refaxis.py:246", _fw_err)
        self._add(obj, sub)
        self.update()

    def _add(self, obj, sub):
        obj, sub = refplane.resolve(obj, sub or "")
        obj, sub = refplane.datum_ref(obj, sub, self.body)
        kind = refplane.kind_of(obj, sub)
        if kind not in ("line", "plane", "point", "cylinder"):
            return
        for i, p in enumerate(self.picks):
            if p[0] == obj and p[1] == sub:
                del self.picks[i]
                return
        self.picks.append((obj, sub, kind))
        if len(self.picks) > 2:
            del self.picks[0]
        self.way = None

    def remove_pick(self, row):
        if 0 <= row < len(self.picks):
            del self.picks[row]
            self.way = None
            self.update()

    def clear_picks(self):
        if self.picks:
            self.picks = []
            self.way = None
            self.update()

    def set_way(self, key):
        self.way = key
        self.update()

    # --- the axis
    def _line(self, on):
        if on and self.line is None:
            if not self.opened:
                self.doc.openTransaction(TITLE)
                self.opened = True
            from . import refgeom2
            self.line = refgeom2.new_datum(self.doc, self.body, "PartDesign::Line", "Axis")
        elif not on and self.line is not None:
            from . import refgeom2
            refgeom2.drop(self.doc, self.body, self.line)
            self.line = None

    def update(self):
        way = self.way or guess([p[2] for p in self.picks])
        try:
            support, mode = recipe(self.picks, way)
            self._line(True)
            place(self.line, support, mode)
            self.message.setText("")
            self.message.setStyleSheet("")
            self.message.setVisible(False)
            self.ok = True
        except AxisError as error:
            self._line(False)
            self.doc.recompute()
            text = str(error) if self.picks else ""
            self.message.setText(text)

            self.message.setStyleSheet(refplane._error_css() if text else "")
            self.message.setVisible(bool(text))
            self.ok = False
        self.list.clear()
        try:
            from . import refplanelook
            texts = refplanelook.sw_labels([(obj, sub) for obj, sub, kind in self.picks])
        except Exception as _fw_err:
            _fw_log("refaxis.py:sw_labels", _fw_err)
            texts = ["%s@%s" % (sub, obj.Label) if sub else obj.Label for obj, sub, kind in self.picks]
        for text in texts:
            self.list.addItem(text)
        refplane._mark(self.list, True, need=not self.picks)
        for key, b in self.buttons.items():
            b.setChecked(key == way)

    # --- check and cross
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        global _current
        _current = None
        for w in self._views:
            try:
                w.removeEventFilter(self._esc)
            except Exception as _fw_err:
                _fw_log("refaxis.py:318", _fw_err)
        self._views = []
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("refaxis.py:323", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if not self.ok:
            return False
        self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        if self.opened:
            self.doc.abortTransaction()
        self.doc.recompute()
        self._close()
        return True


class AxisCommand:
    def GetResources(self):
        return {"Pixmap": "PartDesign_Line", "MenuText": TITLE,
                "ToolTip": "Adds a reference axis: an edge, two planes, two points, a cylindrical face, or a point and a face"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        body = refplane.body_of(doc)

        picks = refplane._picks_before(doc)[:2]
        QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(AxisPanel(doc, body, picks)))


COMMAND = "SWStyle_RefAxis"


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, AxisCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
