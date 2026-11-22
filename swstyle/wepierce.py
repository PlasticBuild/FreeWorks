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

import json
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import wemember
from . import pmboxes

COMMAND = "SWStyle_WEPiercePoint"
TITLE = "Predefine Pierce Point"
OPTIONS = ("Center", "Top Center", "Bottom Center", "Center Left", "Center Right", "Bottom Left", "Top Left",
           "Top Right", "Bottom Right")
PROPERTY = wemember.PIERCE_PROPERTY
NO_POINT = "Select at least one pierce point."
NOT_ON_PROFILE = "The pierce point must be a point of the profile's sketch."
NO_PROFILE = "Select the profile: its sketch."
V = App.Vector

_LAST = None


def _weicon(name):
    from . import weprofile
    return weprofile.icon(name)

def points_of(sketch):
    try:
        return {k: tuple(v) for k, v in json.loads(getattr(sketch, PROPERTY, "") or "{}").items()}
    except Exception as _fw_err:
        _fw_log("wepierce.py:56", _fw_err)
        return {}


def set_point(sketch, name, xy):
    if PROPERTY not in sketch.PropertiesList:
        sketch.addProperty("App::PropertyString", PROPERTY, "FreeCAD", "Predefined pierce points (JSON)")
        sketch.setEditorMode(PROPERTY, 2)
    pts = points_of(sketch)
    pts[name] = [float(xy[0]), float(xy[1])]
    setattr(sketch, PROPERTY, json.dumps(pts, sort_keys=True))


def local_point(sketch, sub):
    """The sketch's point a pick stands for, in the sketch's own coordinates (None when it isn't a point of the
    sketch)."""
    if not sub.startswith("Vertex") and not sub.startswith("RootPoint"):
        return None
    try:
        p = Part.getShape(sketch, sub, needSubElement=True).Vertexes[0].Point
    except Exception:
        if sub.startswith("RootPoint"):
            p = sketch.getGlobalPlacement().Base
        else:
            return None
    q = sketch.getGlobalPlacement().inverse().multVec(p)
    return (q.x, q.y)


def _bold(text):
    lab = QtWidgets.QLabel(text)
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    return lab


def _list(name, colour, tip):
    w = QtWidgets.QListWidget()
    w.setObjectName(name)
    w.setToolTip(tip)
    w.setMaximumHeight(26)
    if colour == "#d6ecff":
        pmboxes.mark(w, True)
    else:
        w.setStyleSheet("QListWidget { background: %s; }" % colour)
    return w


class _Keys(QtCore.QObject):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Delete:
            self.panel.remove_current(watched)
            return True
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            self.panel.activate(watched)
        return False


class Panel:
    def __init__(self, doc):
        global _LAST
        _LAST = self
        self.doc = doc
        self.sketch, self.point, self.busy = None, None, True
        self.keys = _Keys(self)
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWPPPanel")
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", TITLE)
        self.form.setProperty("swstyle_pm_icon", COMMAND)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        msg = QtWidgets.QLabel("Pick the profile's sketch, a point of it, then which pierce point it is.")
        msg.setWordWrap(True)
        lay.addWidget(msg)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("SWPPError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        from . import pickprompt
        pickprompt.style(self.error)     # look audit AI1: the start prompt in the yellow box
        self.error.hide()
        lay.addWidget(self.error)
        lay.addWidget(_bold("Profile"))
        self.profile = _list("SWPPProfile", "#d6ecff", "The profile: its sketch")
        self.profile.installEventFilter(self.keys)
        lay.addWidget(self.profile)
        lay.addWidget(_bold("Pierce Point"))
        self.pick = _list("SWPPPoint", "#ffd6ec", "A point or vertex of the profile's sketch")
        self.pick.installEventFilter(self.keys)
        lay.addWidget(self.pick)
        lay.addWidget(_bold("Options"))
        self.options = QtWidgets.QButtonGroup(self.form)
        for k, name in enumerate(OPTIONS):
            b = QtWidgets.QRadioButton(name)
            b.setObjectName("SWPP" + name.replace(" ", ""))
            self.options.addButton(b, k)
            lay.addWidget(b)
        self.options.button(0).setChecked(True)
        self.options.buttonClicked.connect(self._option)
        lay.addStretch(1)
        self.active = self.profile
        self.busy = False
        self._show()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def option(self):
        return OPTIONS[max(0, self.options.checkedId())]

    def _show(self):
        self.profile.clear()
        if self.sketch is not None:
            self.profile.addItem(self.sketch.Label)
        self.pick.clear()
        if self.point is not None:
            self.pick.addItem("Point (%g, %g)" % (round(self.point[0], 4), round(self.point[1], 4)))
        defined = points_of(self.sketch) if self.sketch is not None else {}
        for k, name in enumerate(OPTIONS):
            b = self.options.button(k)
            b.setToolTip("Predefined at (%g, %g)" % tuple(round(x, 4) for x in defined[name])
                         if name in defined else "Not predefined")
        for b in (self.profile, self.pick):
            b.setStyleSheet(b.styleSheet().replace("border: 2px solid #3874d8;", ""))
        self.active.setStyleSheet(self.active.styleSheet() + "border: 2px solid #3874d8;")

    def _option(self, *_a):
        """An option already predefined shows its point."""
        if self.sketch is not None and self.point is None:
            pts = points_of(self.sketch)
            if self.option() in pts:
                self.point = pts[self.option()]
        self._show()

    def show_error(self, text):
        self.error.setText(text or "")
        self.error.setVisible(bool(text))

    def activate(self, box):
        if box in (self.profile, self.pick):
            self.active = box
            self._show()

    def remove_current(self, w):
        if w is self.profile:
            self.sketch, self.point = None, None
        elif w is self.pick:
            self.point = None
        self._show()

    def addSelection(self, doc, name, sub, point):
        QtCore.QTimer.singleShot(0, lambda: self.picked(doc, name, sub))

    def picked(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("wepierce.py:216", _fw_err)
        if doc_name != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        if obj is None:
            return
        if self.active is self.profile or self.sketch is None:
            if obj.TypeId != "Sketcher::SketchObject":
                self.show_error(NO_PROFILE)
                return
            self.sketch, self.point = obj, None
            self.active = self.pick
            self.show_error(None)
            if sub.startswith("Vertex"):
                self.picked(doc_name, name, sub)
                return
            self._show()
            return
        if obj is not self.sketch:
            self.show_error(NOT_ON_PROFILE)
            return
        xy = local_point(obj, sub)
        if xy is None:
            self.show_error(NOT_ON_PROFILE)
            return
        self.point = xy
        self.show_error(None)
        self._show()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("wepierce.py:252", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if self.sketch is None:
            self.show_error(NO_PROFILE)
            return False
        if self.point is None:
            self.show_error(NO_POINT)
            return False
        self.doc.openTransaction(TITLE)
        try:
            set_point(self.sketch, self.option(), self.point)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise
        self.doc.commitTransaction()
        self.doc.recompute()
        self._close()
        return True

    def reject(self):
        self._close()
        return True


def start():
    doc = App.ActiveDocument
    if doc is None:
        return
    panel = Panel(doc)
    Gui.Control.showDialog(panel)
    for s in Gui.Selection.getSelectionEx():
        for sub in (s.SubElementNames or [""]):
            panel.picked(doc.Name, s.Object.Name, sub)


class Command:
    def GetResources(self):
        try:
            pixmap = _weicon("custom_profile.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Pierce Point",
                "ToolTip": "Predefines a profile's pierce points: the sketch points members can run through."}

    def IsActive(self):
        doc = App.ActiveDocument
        if doc is None or not any(o.TypeId == "Sketcher::SketchObject" for o in doc.Objects):
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
