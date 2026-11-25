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
from . import events
from PySide import QtCore, QtWidgets

V = App.Vector
TITLE = "Walk-through"
UP = V(0, 0, 1)
TURN = 5.0          # degrees per step


class WalkObject:
    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyPythonObject", "Frames", TITLE,
                        "The recorded walk: (position, orientation quaternion) per step")
        obj.addProperty("App::PropertyLength", "StepLength", TITLE, "How far one step goes")
        obj.addProperty("App::PropertyInteger", "FrameTime", TITLE, "Milliseconds per step when played")
        obj.Frames = []
        obj.FrameTime = 60

    def execute(self, obj):
        return

    def dumps(self):
        return None

    def loads(self, state):
        return None


class WalkView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return "view-perspective"

    def setupContextMenu(self, vobj, menu):
        action = menu.addAction("Play Walk-through")
        action.triggered.connect(lambda: play(Gui.ActiveDocument.ActiveView, vobj.Object))

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_walk(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "WalkObject"


def frame(view):
    cam = view.getCameraNode()
    p = cam.position.getValue()
    q = cam.orientation.getValue().getValue()
    return (tuple(float(x) for x in p), tuple(float(x) for x in q))


def put(view, fr):
    from pivy import coin
    cam = view.getCameraNode()
    cam.position.setValue(*fr[0])
    cam.orientation.setValue(coin.SbRotation(*fr[1]))


def _look(view):
    from pivy import coin
    cam = view.getCameraNode()
    q = cam.orientation.getValue()
    d = q.multVec(coin.SbVec3f(0, 0, -1))
    return V(d[0], d[1], d[2])


def walk(view, distance):
    """Moves the eye along the floor (the view direction without its up part)."""
    d = _look(view)
    d.z = 0
    if d.Length < 1e-9:
        return
    d.normalize()
    cam = view.getCameraNode()
    p = V(*cam.position.getValue()) + d * distance
    cam.position.setValue(p.x, p.y, p.z)


def turn(view, degrees):
    """Turns the eye about the up direction, where it stands."""
    from pivy import coin
    cam = view.getCameraNode()
    q = cam.orientation.getValue()
    cam.orientation.setValue(q * coin.SbRotation(coin.SbVec3f(0, 0, 1), math.radians(degrees)))


def tilt(view, degrees):
    from pivy import coin
    cam = view.getCameraNode()
    q = cam.orientation.getValue()
    cam.orientation.setValue(coin.SbRotation(coin.SbVec3f(1, 0, 0), math.radians(degrees)) * q)


def _player():
    return _Play.instance


class _Play(QtCore.QObject):
    instance = None

    def __init__(self, view, frames, ms, done=None):
        super().__init__()
        self.view, self.frames, self.i, self.done = view, list(frames), 0, done
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(max(10, int(ms)))
        _Play.instance = self

    def tick(self):
        if self.i >= len(self.frames):
            self.stop()
            return
        try:
            put(self.view, self.frames[self.i])
        except Exception:
            self.stop()
            return
        self.i += 1

    def stop(self):
        self.timer.stop()
        if _Play.instance is self:
            _Play.instance = None
        if self.done:
            self.done()


def play(view, obj, done=None):
    if _Play.instance is not None:
        _Play.instance.stop()
    if not obj.Frames:
        return None
    view.setCameraType("Perspective")
    return _Play(view, obj.Frames, obj.FrameTime, done)


def _step_length(doc):
    from . import evaluate
    size = 0.0
    for o in evaluate.visible_bodies(doc):
        size = max(size, o.Shape.BoundBox.DiagonalLength)
    return max(size / 40.0, 1.0)


def _in_view(widget):
    """The 3D view's drawing area, or the view that holds it (it has the keyboard focus)."""
    from . import overridedrag
    gl = overridedrag._gl_class()
    if isinstance(widget, gl):
        return True
    viewport = getattr(widget, "viewport", None)
    try:
        return viewport is not None and isinstance(viewport(), gl)
    except Exception:
        return False


class _Keys(QtCore.QObject):
    KEYS = {QtCore.Qt.Key_Up: "forward", QtCore.Qt.Key_W: "forward",
            QtCore.Qt.Key_Down: "back", QtCore.Qt.Key_S: "back",
            QtCore.Qt.Key_Left: "left", QtCore.Qt.Key_A: "left",
            QtCore.Qt.Key_Right: "right", QtCore.Qt.Key_D: "right",
            QtCore.Qt.Key_PageUp: "up", QtCore.Qt.Key_PageDown: "down"}

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        events.register("walkthrough-keys", (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease, QtCore.QEvent.ShortcutOverride,), self.eventFilter)

    def stop(self):
        self.panel = None
        try:
            events.unregister("walkthrough-keys")
        except Exception as _fw_err:
            _fw_log("walkthrough.py:212", _fw_err)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if self.panel is None or t not in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease,
                                           QtCore.QEvent.ShortcutOverride):
            return False
        if not (_in_view(obj) or _in_view(QtWidgets.QApplication.focusWidget())):
            return False
        move = self.KEYS.get(event.key())
        if move is None or event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier):
            return False
        if t == QtCore.QEvent.ShortcutOverride:
            event.accept()          # the key walks: FreeCAD's shortcut on it (view keys...) waits
            return True
        if t == QtCore.QEvent.KeyRelease:
            return True             # nor does the view's own navigation see it
        self.panel.move(move)
        return True


_PANEL = {}


class WalkPanel:
    def __init__(self, doc):
        self.doc = doc
        self.view = Gui.ActiveDocument.ActiveView
        self.before = self.view.getCamera()
        self.view.setCameraType("Perspective")
        self.frames = []
        self.recording = False
        self.step = _step_length(doc)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", TITLE)
        lay = QtWidgets.QVBoxLayout(self.form)
        grid = QtWidgets.QGridLayout()
        for label, name, move, r, c in (("Look Up", "SWWalkUp", "up", 0, 0), ("Forward", "SWWalkForward", "forward", 0, 1),
                                        ("Look Down", "SWWalkDown", "down", 0, 2), ("Turn Left", "SWWalkLeft", "left", 1, 0),
                                        ("Back", "SWWalkBack", "back", 1, 1), ("Turn Right", "SWWalkRight", "right", 1, 2)):
            b = QtWidgets.QPushButton(label)
            b.setObjectName(name)
            b.setAutoRepeat(True)
            b.clicked.connect(lambda checked=False, m=move: self.move(m))
            grid.addWidget(b, r, c)
        lay.addLayout(grid)
        form = QtWidgets.QFormLayout()
        self.speed = QtWidgets.QDoubleSpinBox()
        self.speed.setObjectName("SWWalkStep")
        self.speed.setRange(0.01, 1e6)
        self.speed.setSuffix(" mm")
        self.speed.setValue(self.step)
        form.addRow("Step", self.speed)
        lay.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        self.record = QtWidgets.QPushButton("Record")
        self.record.setObjectName("SWWalkRecord")
        self.record.setCheckable(True)
        self.record.toggled.connect(self.set_recording)
        self.play_button = QtWidgets.QPushButton("Play")
        self.play_button.setObjectName("SWWalkPlay")
        self.play_button.clicked.connect(self.play)
        clear = QtWidgets.QPushButton("Clear")
        clear.setObjectName("SWWalkClear")
        clear.clicked.connect(self.clear)
        row.addWidget(self.record)
        row.addWidget(self.play_button)
        row.addWidget(clear)
        lay.addLayout(row)
        self.info = QtWidgets.QLabel("")
        self.info.setObjectName("SWWalkInfo")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self._say()
        self.keys = _Keys(self)
        _PANEL["open"] = self

    def _say(self):
        self.info.setText("Arrow keys or W A S D walk and turn; Page Up / Page Down look up and down. "
                          "%d steps recorded." % len(self.frames))

    def move(self, how):
        v = self.view
        d = self.speed.value()
        if how == "forward":
            walk(v, d)
        elif how == "back":
            walk(v, -d)
        elif how == "left":
            turn(v, TURN)
        elif how == "right":
            turn(v, -TURN)
        elif how == "up":
            tilt(v, TURN)
        elif how == "down":
            tilt(v, -TURN)
        if self.recording:
            self.frames.append(frame(v))
            self._say()

    def set_recording(self, on):
        self.recording = bool(on)
        self.record.setText("Stop Recording" if on else "Record")
        if on and not self.frames:
            self.frames.append(frame(self.view))
            self._say()

    def play(self):
        if not self.frames:
            self.info.setText("Record a walk first.")
            return
        self.record.setChecked(False)
        _Play(self.view, self.frames, 60)

    def clear(self):
        self.frames = []
        self._say()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        _PANEL.pop("open", None)
        self.keys.stop()
        if _Play.instance is not None:
            _Play.instance.stop()
        Gui.Control.closeDialog()

    def accept(self):
        doc = self.doc
        doc.openTransaction("Add Walk-through")
        try:
            obj = doc.addObject("App::FeaturePython", "Walkthrough")
            WalkObject(obj)
            obj.Frames = list(self.frames)
            obj.StepLength = self.speed.value()
            if App.GuiUp:
                WalkView(obj.ViewObject)
            obj.Label = "Walk-through%d" % (1 + sum(1 for o in doc.Objects if is_walk(o) and o is not obj))
            doc.recompute()
        finally:
            doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self._close()
        self.view.setCamera(self.before)
        return True


class _Add:
    def GetResources(self):
        return {"Pixmap": "view-perspective", "MenuText": "Add Walk-through",
                "ToolTip": "Walks the camera through the model with the arrow keys, and records the walk"}

    def IsActive(self):
        return Gui.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(WalkPanel(doc)))


class _Play_Cmd:
    def GetResources(self):
        return {"Pixmap": "media-playback-start", "MenuText": "Play Walk-through",
                "ToolTip": "Plays the picked walk-through (or the only one)"}

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.ActiveDocument is not None     # never greyed

    def Activated(self):
        picked = [o for o in Gui.Selection.getSelection() if is_walk(o)]
        walks = picked or [o for o in App.ActiveDocument.Objects if is_walk(o) and o.Frames]
        if walks:
            play(Gui.ActiveDocument.ActiveView, walks[0])
        elif not Gui.Control.activeDialog():
            Gui.runCommand("SWStyle_AddWalkThrough", 0)    # none recorded yet: record one


def register():
    if "SWStyle_AddWalkThrough" not in Gui.listCommands():
        Gui.addCommand("SWStyle_AddWalkThrough", _Add())
    if "SWStyle_PlayWalkThrough" not in Gui.listCommands():
        Gui.addCommand("SWStyle_PlayWalkThrough", _Play_Cmd())
