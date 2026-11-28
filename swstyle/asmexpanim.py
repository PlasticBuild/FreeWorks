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

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac
from . import asmexplode as ax

STEP_TIME = 1.0         # s per explode step
FPS = 30
MODES = ("Normal", "Loop", "Reciprocate")


def poses(asm, view):
    """[{name: Placement}] the assembly's look before the first step and after each step. The
    assembly is left as it was (exploded or collapsed)."""
    was = ax.is_exploded(view)
    if was:
        ax.collapse(asm, view)
    comps = ac.components(asm) + ax.nested_parts(asm)
    base = {c.Name: App.Placement(c.Placement) for c in comps}
    out = [dict(base)]
    com, size = ax._ua().getComAndSize(asm)
    try:
        for step in view.Group:
            data = ax.step_data(step)
            if data:
                ax._apply_own(asm, step, data)
            else:
                step.Proxy.applyStep(step, com, size)
            out.append({c.Name: App.Placement(c.Placement) for c in comps})
    finally:
        for c in comps:
            c.Placement = base[c.Name]
        ax._clear_lines(view)
        for obj in [asm] + comps:
            obj.purgeTouched()
    if was:
        ax.explode(asm, view)
    return out


def _lerp(a, b, f):
    base = a.Base + (b.Base - a.Base) * f
    try:
        rot = a.Rotation.slerp(b.Rotation, f)
    except Exception:
        rot = b.Rotation if f >= 0.5 else a.Rotation
    return App.Placement(base, rot)


def pose_at(frames, t, collapse=False):
    """{name: Placement} at time t (s) of the explode (or collapse: played backwards)."""
    n = len(frames) - 1
    if n <= 0:
        return dict(frames[0]) if frames else {}
    total = n * STEP_TIME
    t = max(0.0, min(total, t))
    if collapse:
        t = total - t
    i = min(n - 1, int(t // STEP_TIME))
    f = (t - i * STEP_TIME) / STEP_TIME
    a, b = frames[i], frames[i + 1]
    return {k: _lerp(a[k], b[k], f) for k in a if k in b}


# asmpkg373: the controller's pictures: the pack's MotionManager family, else the drawn Motion set, else Qt's media icons
_BUTTON_ART = {"Start": ("MOTION_PLAY_FROM_START", "SP_MediaSkipBackward"), "Rewind": (None, "SP_MediaSeekBackward"),
               "Play": ("MOTION_PLAY", "SP_MediaPlay"), "FastForward": (None, "SP_MediaSeekForward"),
               "End": (None, "SP_MediaSkipForward"), "Pause": (None, "SP_MediaPause"),
               "Stop": ("MOTION_STOP", "SP_MediaStop"), "Save": ("MOTION_SAVE_ANIMATION", "SP_DialogSaveButton")}


def _button_icon(widget, key):
    family, std = _BUTTON_ART.get(key, (None, None))
    try:
        if family:
            from . import icons
            icon = icons.family(family)
            if icons.paints(icon):
                return icon
            from . import simicons
            path = simicons.svg(family)
            if path:
                return QtGui.QIcon(path)
        if std:
            return widget.style().standardIcon(getattr(QtWidgets.QStyle, std))
    except Exception as _fw_err:
        _fw_log("asmexpanim._button_icon", _fw_err)
    return None


def _place(bar):
    ""

    try:
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        area = mdi.viewport() if mdi is not None else Gui.getMainWindow()
        top_left = area.mapToGlobal(QtCore.QPoint(24, 64))     # under the heads-up view toolbar
        bar.adjustSize()
        bar.move(top_left)
    except Exception as _fw_err:
        _fw_log("asmexpanim._place", _fw_err)


class AnimationController(QtWidgets.QWidget):
    ""

    def __init__(self, asm, view, collapse=False):
        super().__init__(Gui.getMainWindow(), QtCore.Qt.Tool)
        self.setObjectName("FW_AnimationController")
        self.setWindowTitle("Animation Controller")
        self.asm, self.view, self.collapse = asm, view, collapse
        self.doc_name, self.view_name = asm.Document.Name, view.Name
        if ax.is_exploded(view) and not collapse:
            ax.collapse(asm, view)
        self.frames = poses(asm, view)
        if collapse and not ax.is_exploded(view):
            ax.explode(asm, view)
        self.total = max(STEP_TIME, (len(self.frames) - 1) * STEP_TIME)
        self.t = 0.0
        self.direction = 1
        self.speed = 1.0
        self.mode = "Normal"
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.buttons = {}
        for key, text, tip, slot in (
                ("Start", "|<", "Start", self.to_start), ("Rewind", "<<", "Rewind", self.rewind),
                ("Play", ">", "Play", self.play), ("FastForward", ">>", "Fast Forward", self.fast_forward),
                ("End", ">|", "End", self.to_end), ("Pause", "||", "Pause", self.pause),
                ("Stop", "[]", "Stop", self.stop), ("Save", "Save", "Save Animation", self.save_dialog)):
            b = QtWidgets.QToolButton(self)
            b.setObjectName("FW_Anim" + key)
            b.setText(text)
            b.setToolTip(tip)
            icon = _button_icon(self, key)
            if icon is not None:
                b.setIcon(icon)
                b.setIconSize(QtCore.QSize(20, 20))
                b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
            b.clicked.connect(slot)
            lay.addWidget(b)
            self.buttons[key] = b
        self.mode_box = QtWidgets.QComboBox(self)
        self.mode_box.setObjectName("FW_AnimMode")
        self.mode_box.addItems(["Normal", "Loop", "Reciprocate"])
        self.mode_box.currentTextChanged.connect(self.set_mode)
        lay.addWidget(self.mode_box)
        self.speed_box = QtWidgets.QComboBox(self)
        self.speed_box.setObjectName("FW_AnimSpeed")
        self.speed_box.addItems(["Slow Play (0.5x)", "Normal Play (1x)", "Fast Play (2x)"])
        self.speed_box.setCurrentIndex(1)
        self.speed_box.currentIndexChanged.connect(lambda i: setattr(self, "speed", (0.5, 1.0, 2.0)[i]))
        lay.addWidget(self.speed_box)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self.slider.setObjectName("FW_AnimSlider")
        self.slider.setRange(0, int(self.total * FPS))
        self.slider.setMinimumWidth(160)
        self.slider.valueChanged.connect(lambda v: self.set_time(v / float(FPS), from_slider=True))
        lay.addWidget(self.slider)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(int(1000 / FPS))
        self.timer.timeout.connect(self._tick)
        self.set_time(0.0)

    # ---- the model at a time
    def _asm(self):
        d = App.listDocuments().get(self.doc_name)
        return (d.getObject(self.asm.Name), d.getObject(self.view_name)) if d is not None else (None, None)

    def set_time(self, t, from_slider=False):
        asm, view = self._asm()
        if asm is None:
            return
        self.t = max(0.0, min(self.total, t))
        pose = pose_at(self.frames, self.t, self.collapse)
        doc = asm.Document
        for name, plc in pose.items():
            obj = doc.getObject(name)
            if obj is not None:
                obj.Placement = plc
        for obj in [asm] + [doc.getObject(n) for n in pose]:
            if obj is not None:
                obj.purgeTouched()
        if not from_slider:
            self.slider.blockSignals(True)
            self.slider.setValue(int(round(self.t * FPS)))
            self.slider.blockSignals(False)
        Gui.updateGui()

    def _tick(self):
        dt = self.speed / FPS * self.direction
        t = self.t + dt
        if t >= self.total or t <= 0.0:
            if self.mode == "Loop" and self.direction > 0:
                t = 0.0
            elif self.mode == "Reciprocate":
                self.direction = -self.direction
                t = max(0.0, min(self.total, t))
            else:
                self.set_time(max(0.0, min(self.total, t)))
                self.timer.stop()
                self._settle()      # played to the end: the view is exploded (or collapsed) now
                return
        self.set_time(t)

    # ---- the buttons
    def play(self):
        if self.t >= self.total and self.direction > 0:
            self.t = 0.0
        self.direction = 1 if self.direction == 0 else self.direction
        self.timer.start()

    def pause(self):
        self.timer.stop()

    def stop(self):
        self.timer.stop()
        self.direction = 1
        self.set_time(0.0)

    def to_start(self):
        self.timer.stop()
        self.set_time(0.0)

    def to_end(self):
        self.timer.stop()
        self.set_time(self.total)

    def rewind(self):
        self.set_time(self.t - STEP_TIME)

    def fast_forward(self):
        self.set_time(self.t + STEP_TIME)

    def set_mode(self, mode):
        self.mode = mode

    def play_through(self):
        """For checks: every frame at once, as Play does them."""
        n = 0
        self.set_time(0.0)
        while self.t < self.total - 1e-9:
            self.set_time(self.t + 1.0 / FPS)
            n += 1
        return n

    # ---- Save Animation
    def save(self, path, width=800, height=600):
        """The animation as an AVI (Motion JPEG) or a series of PNG files."""
        from . import asmtimeline
        gview = Gui.getDocument(self.doc_name).ActiveView
        frames = int(self.total * FPS) + 1
        import shutil
        import tempfile
        stem, ext = os.path.splitext(path)
        avi = ext.lower() == ".avi"
        # an AVI: the frames in a folder of their own, removed once the movie is written
        folder = tempfile.mkdtemp(prefix="fwanim") if avi else os.path.dirname(path) or "."
        os.makedirs(folder, exist_ok=True)
        pngs = []
        for i in range(frames):
            self.set_time(i / float(FPS))
            name = os.path.join(folder, "%s%04d.png" % (os.path.basename(stem), i))
            gview.saveImage(name, width, height, "Current")
            pngs.append(name)
        if avi:
            try:
                asmtimeline.write_mjpeg_avi(path, pngs, FPS)
            finally:
                shutil.rmtree(folder, ignore_errors=True)
        return path

    def save_dialog(self):
        path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save Animation to File", "Animation1.avi",
                                                         "AVI (*.avi);;Series of PNG files (*.png)")
        if path:
            self.save(path)

    def closeEvent(self, e):
        ""
        self.timer.stop()
        self._settle()
        _OPEN.pop("bar", None)
        super().closeEvent(e)

    def _settle(self):
        """The exploded view's state as the animation left it: exploded at the end of Animate
        explode, collapsed at the end of Animate collapse (its right-click and the tree follow)."""
        asm, view = self._asm()
        if asm is not None and view is not None:
            end = self.t >= self.total - 1e-6
            exploded = end != self.collapse
            if ax.is_exploded(view):
                ax.collapse(asm, view)          # back to the mated positions it kept
            else:
                for name, plc in self.frames[0].items():
                    o = asm.Document.getObject(name)
                    if o is not None:
                        o.Placement = plc
            if exploded:
                ax.explode(asm, view)
            for obj in [asm] + ac.components(asm):
                obj.purgeTouched()


_OPEN = {}


def animate(view, collapse=False):
    asm = ac.assembly_of(view.Document)
    if asm is None:
        return None
    old = _OPEN.get("bar")
    if old is not None:
        try:
            old.close()
        except RuntimeError as _fw_err:
            _fw_log("asmexpanim.py:293", _fw_err)
    bar = AnimationController(asm, view, collapse)
    _OPEN["bar"] = bar
    _place(bar)
    bar.show()
    bar.play()
    return bar


def is_view(obj):
    try:
        return obj is not None and obj.TypeId == "App::FeaturePython" and type(obj.Proxy).__name__ == "ExplodedView"
    except Exception:
        return False


def view_items(view):
    ""
    asm = ac.assembly_of(view.Document)
    on = ax.is_exploded(view)

    def explode_collapse(c):
        doc = asm.Document
        doc.openTransaction("Collapse" if c else "Explode")
        try:
            (ax.collapse if c else ax.explode)(asm, view)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
    items = [("ExplodeView", "Collapse" if on else "Explode", lambda: explode_collapse(on), asm is not None),
             ("AnimateExplode", "Animate explode", lambda: animate(view, False), asm is not None and not on),
             ("AnimateCollapse", "Animate collapse", lambda: animate(view, True), asm is not None and on),
             ("EditExplode", "Edit Feature", lambda: ax.edit_view(view), True)]
    try:
        from . import asmexplines
        items.append(("SmartLines", "Smart Explode Lines",
                      lambda: asmexplines._in_transaction(asm, "Smart Explode Lines",
                                                         lambda: asmexplines.smart_lines(asm, view)), on))
    except Exception as _fw_err:
        _fw_log("asmexpanim.py:328", _fw_err)

    # Animate explode while collapsed): nothing greyed
    return [i for i in items if i[3]]
