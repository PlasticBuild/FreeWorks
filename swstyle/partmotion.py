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
import math
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

FPS = 25
DURATION = 5.0
META, OPT_META = "FwPartMotion", "FwPartMotionOptions"
VIEW_ROW = "__view__"
STUDY_ROW = "__study__"
SPEEDS = ("0.1x", "0.25x", "0.5x", "1x", "2x", "5x")
MODES = ("Normal", "Loop", "Reciprocate")
PANE = {"dock": None, "camera": None, "looks": None}     # what the Model tab showed when the study opened
V = App.Vector
Qt = QtCore.Qt


def _view():
    try:
        return Gui.ActiveDocument.ActiveView
    except Exception:
        return None


def _center(doc):
    box = App.BoundBox()
    for o in doc.Objects:
        try:
            if o.ViewObject is not None and o.ViewObject.Visibility and hasattr(o, "Shape") and not o.Shape.isNull():
                box.add(o.Shape.BoundBox)
        except Exception as _fw_err:
            _fw_log("partmotion.py:center", _fw_err)
    return box.Center if box.isValid() else App.Vector()


def _say(text, ms=8000):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, ms)
    except Exception as _fw_err:
        _fw_log("partmotion.py:say", _fw_err)


def _tl():
    from . import asmtimeline
    return asmtimeline


class Spin:
    """Turns the camera about an axis through the model's centre: frame i of n is i/n of the turns."""

    AXES = {"Y (up)": App.Vector(0, 1, 0), "X": App.Vector(1, 0, 0), "Z": App.Vector(0, 0, 1)}

    def __init__(self, view, axis="Y (up)", turns=1.0, seconds=10.0):
        from pivy import coin
        self.coin = coin
        self.view = view
        self.cam = view.getCameraNode()
        q = self.cam.orientation.getValue().getValue()          # (x, y, z, w)
        self.q0 = App.Rotation(q[0], q[1], q[2], q[3])
        p = self.cam.position.getValue()
        self.p0 = App.Vector(p[0], p[1], p[2])
        self.c = _center(App.ActiveDocument)
        self.axis = self.AXES.get(axis, App.Vector(0, 1, 0))
        self.turns = turns
        self.frames = max(1, int(round(seconds * FPS)))

    def frame(self, i):
        angle = -360.0 * self.turns * i / self.frames
        turn = App.Rotation(self.q0.multVec(self.axis), angle)
        q = turn.multiply(self.q0)
        pos = self.c + turn.multVec(self.p0 - self.c)
        self.cam.orientation.setValue(self.coin.SbRotation(*q.Q))
        self.cam.position.setValue(pos.x, pos.y, pos.z)

    def reset(self):
        self.cam.orientation.setValue(self.coin.SbRotation(*self.q0.Q))
        self.cam.position.setValue(self.p0.x, self.p0.y, self.p0.z)


# ------------------------------------------------------------------------------ the study's store
class PartStudy:
    """The study of a part, for asmtimeline's key functions (which keep their keys in FwKeys and their
    options in FwStudyOptions): both live in the part's Document Meta, so nothing shows in the tree."""

    def __init__(self, doc):
        self.Document = doc

    def _get(self, key):
        try:
            return self.Document.Meta.get(key, "") or ""
        except Exception:
            return ""

    def _set(self, key, text):
        meta = dict(self.Document.Meta)
        if meta.get(key) != text:
            meta[key] = text
            self.Document.Meta = meta

    FwKeys = property(lambda self: self._get(META), lambda self, v: self._set(META, v))
    FwStudyOptions = property(lambda self: self._get(OPT_META), lambda self, v: self._set(OPT_META, v))

    def addProperty(self, *_a):
        return self

    def setEditorMode(self, *_a):
        return None

    @property
    def fps(self):
        return max(1, int(_tl().study_option(self, "anim_fps") or FPS))

    @property
    def cTimeStepOutput(self):          # save_animation's frame step
        return 1.0 / self.fps


def bodies(doc):
    """The part's bodies (PartDesign bodies, else the top-level shapes), as the MotionManager tree lists them."""
    out = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    if out:
        return out
    return [o for o in doc.Objects if hasattr(o, "Shape") and o.ViewObject is not None and not o.InList
            and o.TypeId not in ("App::Origin", "App::Line", "App::Plane", "Sketcher::SketchObject")
            and not o.TypeId.startswith("App::")]


def look_of(obj):
    """[shown, colour (r, g, b), transparency 0-100]."""
    vo = obj.ViewObject
    colour = None
    try:
        colour = [round(c, 4) for c in vo.ShapeColor[:3]]
    except Exception as _fw_err:
        _fw_log("partmotion.py:look_of", _fw_err)
    return [bool(obj.Visibility), colour, int(getattr(vo, "Transparency", 0) or 0)]


def apply_look(obj, look):
    vis, colour, transp = (list(look) + [None, None, None])[:3]
    if bool(obj.Visibility) != bool(vis):
        obj.Visibility = bool(vis)
    vo = obj.ViewObject
    try:
        if colour is not None and [round(c, 4) for c in vo.ShapeColor[:3]] != [round(c, 4) for c in colour]:
            vo.ShapeColor = tuple(colour)
        if transp is not None and int(vo.Transparency) != int(round(transp)):
            vo.Transparency = int(round(transp))
    except Exception as _fw_err:
        _fw_log("partmotion.py:apply_look", _fw_err)


def look_at(rows, t):
    """Hide/show changes at its key; colour and transparency fade from one key's to the next."""
    if not rows:
        return None
    if t <= rows[0][0]:
        return list(rows[0][1:])
    tl = _tl()
    for a, b in zip(rows, rows[1:]):
        if a[0] <= t < b[0]:
            f = 0.0 if b[0] <= a[0] else (t - a[0]) / (b[0] - a[0])
            f = tl.ease(f, b[4] if len(b) > 4 else "Linear")
            ca, cb = a[2], b[2]
            colour = [x + (y - x) * f for x, y in zip(ca, cb)] if ca is not None and cb is not None else ca
            ta, tb = a[3], b[3]
            transp = ta + (tb - ta) * f if ta is not None and tb is not None else ta
            return [b[1] if f >= 1.0 - 1e-9 else a[1], colour, transp]
    return list(rows[-1][1:4])


def same_look(a, b):
    if a is None or b is None:
        return a is b
    if bool(a[0]) != bool(b[0]) or abs((a[2] or 0) - (b[2] or 0)) > 0.5:
        return False
    if (a[1] is None) != (b[1] is None):
        return False
    return a[1] is None or all(abs(x - y) < 2e-3 for x, y in zip(a[1], b[1]))


# ------------------------------------------------------------------------------ keys
def data(study):
    d = _tl().data(study)
    d.setdefault("look", {})
    d.setdefault("cams", [])
    d.setdefault("view", [])
    d.setdefault("duration", DURATION)
    return d


def save(study, d):
    _tl().save(study, d)


def ensure_start(study):
    ""
    d = data(study)
    changed = False
    if not d["cams"]:
        cam = _tl().camera_now()
        if cam is not None:
            d["cams"] = [[0.0] + list(cam)]
            changed = True
    for b in bodies(study.Document):
        if b.Name not in d["look"]:
            d["look"][b.Name] = [[0.0] + look_of(b)]
            changed = True
    if changed:
        save(study, d)
    return d


def rows_of(d, row):
    return d["cams"] if row == VIEW_ROW else d["look"].get(row, [])


def key_times(study, row):
    d = data(study)
    if row == STUDY_ROW:
        return [float(d["duration"])]
    return [k[0] for k in rows_of(d, row)]


def set_key(study, row, t, value=None):
    """A key on row at t (the view or the body's look now, or value); a key already there is updated."""
    d = data(study)
    t = max(0.0, round(float(t), 4))
    if row == VIEW_ROW:
        value = value if value is not None else _tl().camera_now()
        rows = d["cams"]
    else:
        obj = study.Document.getObject(row)
        if obj is None:
            return False
        value = value if value is not None else look_of(obj)
        rows = d["look"].setdefault(row, [])
    if value is None:
        return False
    for k in rows:
        if abs(k[0] - t) < 1e-6:
            mode = k[5 if row == VIEW_ROW else 4:]
            k[1:] = list(value) + list(mode)
            break
    else:
        rows.append([t] + list(value))
        rows.sort(key=lambda k: k[0])
    if t > d["duration"]:
        d["duration"] = t
    save(study, d)
    return True


def delete_key(study, row, t):
    """Deletes the key (the key at 0 stays: every row starts with one)."""
    d = data(study)
    if row == STUDY_ROW or t <= 1e-6:
        return False
    rows = rows_of(d, row)
    keep = [k for k in rows if abs(k[0] - t) > 1e-6]
    if len(keep) == len(rows):
        return False
    if row == VIEW_ROW:
        d["cams"] = keep
    else:
        d["look"][row] = keep
    save(study, d)
    return True


def move_key(study, row, t, new_t):
    d = data(study)
    new_t = max(0.0, round(float(new_t), 4))
    if row == STUDY_ROW:
        d["duration"] = max(0.1, new_t, *[k[0] for r in [d["cams"]] + list(d["look"].values()) for k in r] or [0.1])
        save(study, d)
        return True
    if t <= 1e-6:
        return False                       # the start key stays at 0
    rows = rows_of(d, row)
    if any(abs(k[0] - new_t) < 1e-6 for k in rows if abs(k[0] - t) > 1e-6) or new_t <= 1e-6:
        return False
    for k in rows:
        if abs(k[0] - t) < 1e-6:
            k[0] = new_t
    rows.sort(key=lambda k: k[0])
    if new_t > d["duration"]:
        d["duration"] = new_t
    save(study, d)
    return True


def interpolation(study, row, t):
    d = data(study)
    i = 5 if row == VIEW_ROW else 4
    for k in rows_of(d, row):
        if abs(k[0] - t) < 1e-6:
            return k[i] if len(k) > i else "Linear"
    return None


def set_interpolation(study, row, t, mode):
    tl = _tl()
    if mode not in tl.INTERPOLATION:
        raise ValueError(mode)
    d = data(study)
    i = 5 if row == VIEW_ROW else 4
    for k in rows_of(d, row):
        if abs(k[0] - t) < 1e-6:
            del k[i:]
            if mode != "Linear":
                k.append(mode)
            save(study, d)
            return True
    return False


def camera_at(rows, t):
    """asmtimeline.camera_at with the arriving key's interpolation mode."""
    if not rows:
        return None
    if t <= rows[0][0]:
        return rows[0][1:5]
    tl = _tl()
    for a, b in zip(rows, rows[1:]):
        if a[0] <= t <= b[0]:
            f = 0.0 if b[0] <= a[0] else (t - a[0]) / (b[0] - a[0])
            f = tl.ease(f, b[5] if len(b) > 5 else "Linear")
            pos = [x + (y - x) * f for x, y in zip(a[1], b[1])]
            q = list(App.Rotation(*a[2]).slerp(App.Rotation(*b[2]), f).Q)
            return [pos, q, a[3] + (b[3] - a[3]) * f, a[4] + (b[4] - a[4]) * f]
    return rows[-1][1:5]


def turned(cam, centre, axis, degrees):
    """The camera turned about a world axis through the model's centre (the model seems to turn)."""
    if cam is None or axis is None or not degrees:
        return cam
    r = App.Rotation(V(*{"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[axis]), -degrees)
    rot = r.multiply(App.Rotation(*cam[1]))
    pos = centre + r.multVec(V(*cam[0]) - centre)
    return [[pos.x, pos.y, pos.z], list(rot.Q), cam[2], cam[3]]


def state_at(study, t, d=None, base_cam=None):
    """(camera or None, {body name: look}) at time t."""
    d = d or data(study)
    cam = None
    if len(d["cams"]) > 1 or d["view"]:
        cam = camera_at(d["cams"], t) if d["cams"] else base_cam
        axis, deg = _tl().view_angle(d, t)
        cam = turned(cam, _center(study.Document), axis, deg)
    looks = {}
    for name, rows in d["look"].items():
        if len(rows) > 1:
            looks[name] = look_at(rows, t)
    return cam, looks


def wizard_rotate(study, axis="Y", turns=1.0, clockwise=True, duration=10.0, start=0.0):
    _tl().wizard_rotate(study, axis, turns, clockwise, duration, start)
    d = data(study)
    if start + duration > d["duration"]:
        d["duration"] = round(start + duration, 4)
        save(study, d)
    return d


# ------------------------------------------------------------------------------ the pane
class Timeline(QtWidgets.QWidget):
    """The MotionManager tree (names on the left) and the timeline (ruler, key diamonds, time bar)."""

    ROW = 20
    RULER = 22
    NAMES = 200

    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.setObjectName("FW_PartMotionTimeline")
        self.setMouseTracking(True)
        self.setMinimumHeight(self.RULER + 3 * self.ROW + 4)
        self.scale = 60.0               # pixels per second
        self.offset = 0.0               # the time at the left edge of the timeline
        self.picked = set()             # {(row, t)}
        self.drag = None                # (row, t) of the key being dragged, or "bar"
        self.menu = None

    # rows and geometry ----------------------------------------------------------------------
    def rows(self):
        doc = self.pane.study.Document
        out = [(STUDY_ROW, doc.Label), (VIEW_ROW, "Orientation and Camera Views")]
        out += [(b.Name, b.Label) for b in bodies(doc)]
        return out

    def x_of(self, t):
        return self.NAMES + 8 + (t - self.offset) * self.scale

    def t_of(self, x):
        return max(0.0, self.offset + (x - self.NAMES - 8) / self.scale)

    def row_at(self, y):
        i = int((y - self.RULER) // self.ROW)
        rows = self.rows()
        return rows[i][0] if 0 <= i < len(rows) else None

    def key_at(self, pos):
        row = self.row_at(pos.y())
        if row is None or pos.x() < self.NAMES:
            return None
        for t in key_times(self.pane.study, row):
            if abs(self.x_of(t) - pos.x()) <= 6:
                return (row, t)
        return None

    def sizeHint(self):
        return QtCore.QSize(800, self.RULER + self.ROW * len(self.rows()) + 4)

    # painting -------------------------------------------------------------------------------
    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        w = self.width()
        study = self.pane.study
        d = data(study)
        # the ruler
        p.fillRect(QtCore.QRect(self.NAMES, 0, w - self.NAMES, self.RULER), pal.window())
        p.setPen(pal.text().color())
        step = 1.0 if self.scale >= 40 else 2.0 if self.scale >= 20 else 5.0
        t = math.floor(self.offset / step) * step
        while self.x_of(t) < w:
            x = self.x_of(t)
            if x >= self.NAMES + 4:
                p.drawLine(QtCore.QPointF(x, self.RULER - 6), QtCore.QPointF(x, self.RULER))
                p.drawText(QtCore.QPointF(x + 2, self.RULER - 8), "%g sec" % t)
            t += step
        # the rows
        grid = QtGui.QColor(pal.mid().color())
        for i, (row, label) in enumerate(self.rows()):
            y = self.RULER + i * self.ROW
            if i % 2:
                p.fillRect(QtCore.QRect(0, y, w, self.ROW), pal.alternateBase())
            p.setPen(pal.text().color())
            indent = 4 if row == STUDY_ROW else 18
            p.drawText(QtCore.QRectF(indent, y, self.NAMES - indent, self.ROW), int(Qt.AlignVCenter | Qt.AlignLeft), label)
            p.setPen(grid)
            p.drawLine(self.NAMES, y + self.ROW, w, y + self.ROW)
            times = key_times(study, row)

            if row != STUDY_ROW and len(times) > 1:
                p.setPen(Qt.NoPen)
                p.setBrush(QtGui.QColor(90, 140, 220, 110) if row == VIEW_ROW else QtGui.QColor(230, 160, 40, 110))
                p.drawRect(QtCore.QRectF(self.x_of(times[0]), y + 7, self.x_of(times[-1]) - self.x_of(times[0]), 6))
            if row == VIEW_ROW and d["view"]:
                p.setPen(Qt.NoPen)
                p.setBrush(QtGui.QColor(90, 140, 220, 110))
                for seg in d["view"]:
                    p.drawRect(QtCore.QRectF(self.x_of(seg[0]), y + 7, self.x_of(seg[1]) - self.x_of(seg[0]), 6))
            for t in times:
                x, cy = self.x_of(t), y + self.ROW / 2.0
                if x < self.NAMES:
                    continue
                picked = (row, t) in self.picked
                p.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20), 1))
                p.setBrush(QtGui.QColor(60, 120, 230) if picked else QtGui.QColor(250, 250, 250) if row == STUDY_ROW
                           else QtGui.QColor(160, 160, 160))
                diamond = QtGui.QPolygonF([QtCore.QPointF(x, cy - 5), QtCore.QPointF(x + 5, cy),
                                           QtCore.QPointF(x, cy + 5), QtCore.QPointF(x - 5, cy)])
                p.drawPolygon(diamond)
        # the names column edge and the time bar
        p.setPen(grid)
        p.drawLine(self.NAMES, 0, self.NAMES, self.height())
        x = self.x_of(self.pane.time)
        if x >= self.NAMES:
            p.setPen(QtGui.QPen(QtGui.QColor(30, 30, 30), 2))
            p.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, self.height()))
        p.end()

    # mouse ----------------------------------------------------------------------------------
    def mousePressEvent(self, e):
        pos = e.pos()
        if e.button() == Qt.RightButton:
            self.context_menu(pos)
            return
        if e.button() != Qt.LeftButton or pos.x() < self.NAMES:
            return
        hit = self.key_at(pos)
        if hit is not None:
            if e.modifiers() & Qt.ControlModifier:
                self.picked ^= {hit}
            elif hit not in self.picked:
                self.picked = {hit}
            self.drag = hit
        else:
            self.picked = set()
            self.drag = "bar"
            self.pane.set_time(self.t_of(pos.x()))
        self.update()

    def mouseMoveEvent(self, e):
        if self.drag == "bar":
            self.pane.set_time(self.t_of(e.pos().x()))
        elif self.drag is not None:
            self.update()

    def mouseReleaseEvent(self, e):
        if self.drag not in (None, "bar"):
            row, t = self.drag
            new_t = round(self.t_of(e.pos().x()) * self.pane.study.fps) / float(self.pane.study.fps)
            if abs(new_t - t) > 1e-6 and move_key(self.pane.study, row, t, new_t):
                self.picked = {(row, new_t)}
                self.pane.changed()
        self.drag = None
        self.update()

    def context_menu(self, pos):
        hit = self.key_at(pos)
        row = self.row_at(pos.y())
        t0 = self.t_of(pos.x())
        menu = QtWidgets.QMenu(self)
        if hit is not None and hit[0] != STUDY_ROW:
            if hit not in self.picked:
                self.picked = {hit}
            if hit[1] > 1e-6:      # the start key stays at 0, cannot go and has nothing before it to ease from
                menu.addAction("Edit Key Point Time...", lambda: self.edit_time(hit))
                menu.addAction("Delete", self.delete_picked)
                sub = menu.addMenu("Interpolation Mode")
                tl = _tl()
                now = interpolation(self.pane.study, hit[0], hit[1])
                for mode in tl.INTERPOLATION:
                    a = sub.addAction(tl.INTERPOLATION_TEXT[mode], lambda m=mode: self.interpolate(hit, m))
                    a.setCheckable(True)
                    a.setChecked(mode == now)
        elif hit is not None:
            menu.addAction("Edit Key Point Time...", lambda: self.edit_time(hit))
        else:
            if row not in (None, STUDY_ROW):
                menu.addAction("Place Key", lambda: self.pane.place_key(row, t0))
            menu.addAction("Move Time Bar", lambda: self.pane.set_time(t0))
        menu.addSeparator()
        menu.addAction("Select All", self.select_all)
        menu.addAction("Animation Wizard...", self.pane.wizard)
        self.menu = menu
        menu.exec_(self.mapToGlobal(pos))

    def select_all(self):
        self.picked = {(row, t) for row, _l in self.rows() if row != STUDY_ROW
                       for t in key_times(self.pane.study, row)}
        self.update()

    def delete_picked(self):
        n = 0
        for row, t in sorted(self.picked):
            n += bool(delete_key(self.pane.study, row, t))
        self.picked = set()
        if n:
            self.pane.changed()
        return n

    def interpolate(self, hit, mode):
        for row, t in (self.picked or {hit}):
            if row != STUDY_ROW and t > 1e-6:
                set_interpolation(self.pane.study, row, t, mode)
        self.pane.changed()

    def edit_time(self, hit, value=None):
        row, t = hit
        if value is None:
            value, ok = QtWidgets.QInputDialog.getDouble(self, "Edit Time", "Time (sec):", t, 0.0, 3600.0, 3)
            if not ok:
                return False
        if move_key(self.pane.study, row, t, value):
            self.picked = {(row, round(float(value), 4))} if row != STUDY_ROW else set()
            self.pane.changed()
            return True
        return False

    def zoom(self, factor):
        self.scale = max(2.0, min(800.0, self.scale * factor))
        self.update()

    def zoom_fit(self):
        end = max(0.5, float(data(self.pane.study)["duration"]))
        self.offset = 0.0
        self.scale = max(2.0, (self.width() - self.NAMES - 30) / end)
        self.update()


class WizardDialog(QtWidgets.QDialog):
    ""


    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.setObjectName("SWAnimationWizard")
        self.setWindowTitle("Select an Animation Type")
        lay = QtWidgets.QVBoxLayout(self)
        self.stack = QtWidgets.QStackedWidget(self)
        lay.addWidget(self.stack)
        p1 = QtWidgets.QWidget()
        l1 = QtWidgets.QVBoxLayout(p1)
        self.rotate = QtWidgets.QRadioButton("Rotate model")
        self.rotate.setObjectName("SWWizardRotate")
        self.rotate.setChecked(True)
        self.delete_all = QtWidgets.QCheckBox("Delete all existing paths")
        self.delete_all.setObjectName("SWWizardDeleteAll")
        l1.addWidget(self.rotate)
        l1.addWidget(QtWidgets.QLabel("Explode and Collapse animate an assembly's exploded view."))
        l1.addWidget(self.delete_all)
        l1.addStretch(1)
        self.stack.addWidget(p1)
        p2 = QtWidgets.QWidget()
        l2 = QtWidgets.QVBoxLayout(p2)
        l2.addWidget(QtWidgets.QLabel("Select an Axis of Rotation"))
        self.axes = {}
        for a in ("X", "Y", "Z"):
            r = QtWidgets.QRadioButton("%s-axis" % a)
            r.setObjectName("SWWizardAxis" + a)
            self.axes[a] = r
            l2.addWidget(r)
        self.axes["Y"].setChecked(True)
        f2 = QtWidgets.QFormLayout()
        self.turns = QtWidgets.QDoubleSpinBox()
        self.turns.setObjectName("SWWizardTurns")
        self.turns.setRange(0.25, 100)
        self.turns.setValue(1)
        f2.addRow("Number of Rotations:", self.turns)
        self.cw = QtWidgets.QRadioButton("Clockwise")
        self.cw.setChecked(True)
        self.ccw = QtWidgets.QRadioButton("Counterclockwise")
        f2.addRow(self.cw)
        f2.addRow(self.ccw)
        l2.addLayout(f2)
        self.stack.addWidget(p2)
        p3 = QtWidgets.QWidget()
        f3 = QtWidgets.QFormLayout(p3)
        f3.addRow(QtWidgets.QLabel("Animation Control Options"))
        self.duration = QtWidgets.QDoubleSpinBox()
        self.duration.setObjectName("SWWizardDuration")
        self.duration.setRange(0.1, 3600)
        self.duration.setValue(10.0)
        self.duration.setSuffix(" sec")
        self.start = QtWidgets.QDoubleSpinBox()
        self.start.setObjectName("SWWizardStart")
        self.start.setRange(0.0, 3600)
        self.start.setSuffix(" sec")
        f3.addRow("Duration:", self.duration)
        f3.addRow("Start Time:", self.start)
        self.stack.addWidget(p3)
        row = QtWidgets.QHBoxLayout()
        self.back = QtWidgets.QPushButton("< Back")
        self.next = QtWidgets.QPushButton("Next >")
        self.finish = QtWidgets.QPushButton("Finish")
        cancel = QtWidgets.QPushButton("Cancel")
        self.back.clicked.connect(lambda: self.go(-1))
        self.next.clicked.connect(lambda: self.go(1))
        self.finish.clicked.connect(self.done_ok)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        for b in (self.back, self.next, self.finish, cancel):
            row.addWidget(b)
        lay.addLayout(row)
        self.go(0)

    def go(self, step):
        i = max(0, min(2, self.stack.currentIndex() + step))
        self.stack.setCurrentIndex(i)
        self.back.setEnabled(i > 0)
        self.next.setEnabled(i < 2)
        self.finish.setEnabled(i == 2)

    def axis(self):
        return next(a for a, r in self.axes.items() if r.isChecked())

    def done_ok(self):
        self.pane.apply_wizard(self.axis(), self.turns.value(), self.cw.isChecked(), self.duration.value(),
                               self.start.value(), self.delete_all.isChecked())
        self.accept()


class PropertiesDialog(QtWidgets.QDialog):
    """Motion Study Properties of an Animation: Frames per second and the view key options."""

    def __init__(self, pane):
        super().__init__(pane)
        self.pane = pane
        self.setObjectName("SWMotionStudyProperties")
        self.setWindowTitle("Motion Study Properties")
        tl = _tl()
        opts = tl.study_options(pane.study)
        lay = QtWidgets.QFormLayout(self)
        self.fps = QtWidgets.QSpinBox()
        self.fps.setObjectName("SWStudyFps")
        self.fps.setRange(1, 240)
        self.fps.setValue(int(opts.get("anim_fps") or FPS))
        lay.addRow("Frames per second:", self.fps)
        self.no_view_keys = QtWidgets.QCheckBox("Disable view key creation")
        self.no_view_keys.setChecked(bool(opts.get("no_view_keys")))
        self.no_view_playback = QtWidgets.QCheckBox("Disable playback of view keys")
        self.no_view_playback.setChecked(bool(opts.get("no_view_playback")))
        lay.addRow(self.no_view_keys)
        lay.addRow(self.no_view_playback)
        self.make_default = QtWidgets.QCheckBox("Use as default for new studies")
        lay.addRow(self.make_default)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def ok(self):
        _tl().set_study_options(self.pane.study, {"anim_fps": self.fps.value(), "no_view_keys": self.no_view_keys.isChecked(),
                                                  "no_view_playback": self.no_view_playback.isChecked()},
                                self.make_default.isChecked())
        self.pane.changed()
        self.accept()


class MotionPane(QtWidgets.QWidget):
    """The part's MotionManager: toolbar, then the tree and timeline."""

    BUTTONS = (("FW_PartMotionCalculate", "Calculate", "MOTION_CALCULATE", "calculate"),
               ("FW_PartMotionPlayStart", "Play from Start", "MOTION_PLAY_FROM_START", "play_start"),
               ("FW_PartMotionPlay", "Play", "MOTION_PLAY", "play"),
               ("FW_PartMotionStop", "Stop", "MOTION_STOP", "stop"))
    BUTTONS2 = (("FW_PartMotionSave", "Save Animation", "MOTION_SAVE_ANIMATION", "save"),
                ("FW_PartMotionWizard", "Animation Wizard", "MOTION_WIZARD", "wizard"))

    def __init__(self, parent=None, doc=None):
        super().__init__(parent)
        self.setObjectName("FW_PartMotionPane")
        self.study = PartStudy(doc or App.ActiveDocument)
        self.asm = self.study            # save_animation reads pane.asm.Document
        self.sim = self.study
        self.time = 0.0
        self.frames = 0                  # calculated frames (frame i is time (i - 1) / fps)
        self.calc_key = None
        self.dir = 1
        self.i = 1
        self.base_cam = _tl().camera_now()
        self._applying = False
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._step)
        ensure_start(self.study)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        bar = QtWidgets.QHBoxLayout()
        self.kind = QtWidgets.QLabel(" Animation ")      # a part has one study type: shown, not a one-entry list
        self.kind.setObjectName("FW_PartMotionType")
        self.kind.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.kind.setToolTip("Type of study. Basic Motion and Motion Analysis move an assembly's components.")
        bar.addWidget(self.kind)
        for name, text, icon, slot in self.BUTTONS:
            bar.addWidget(self._button(name, text, icon, getattr(self, slot)))
        self.speed = QtWidgets.QComboBox()
        self.speed.setObjectName("FW_PartMotionSpeed")
        self.speed.addItems(list(SPEEDS))
        self.speed.setCurrentText("1x")
        self.speed.setToolTip("Playback speed")
        self.speed.currentTextChanged.connect(lambda *_a: self._interval())
        self.mode = QtWidgets.QComboBox()
        self.mode.setObjectName("FW_PartMotionMode")
        self.mode.addItems(list(MODES))
        self.mode.setToolTip("Playback mode")
        bar.addWidget(self.speed)
        bar.addWidget(self.mode)
        for name, text, icon, slot in self.BUTTONS2:
            bar.addWidget(self._button(name, text, icon, getattr(self, slot)))
        self.autokey = self._button("FW_PartMotionAutokey", "Autokey", "MOTION_AUTOKEY", None)
        self.autokey.setCheckable(True)
        self.autokey.setChecked(True)
        bar.addWidget(self.autokey)
        bar.addWidget(self._button("FW_PartMotionAddKey", "Add/Update Key", "MOTION_ADD_KEY", self.add_key))
        bar.addWidget(self._button("FW_PartMotionProperties", "Motion Study Properties", "MOTION_STUDY_PROPERTIES",
                                   self.properties))
        self.collapse_btn = self._button("FW_PartMotionCollapse", "Collapse MotionManager", "MOTION_COLLAPSE", None)
        self.collapse_btn.setCheckable(True)
        self.collapse_btn.toggled.connect(self.collapse)
        bar.addWidget(self.collapse_btn)
        bar.addStretch(1)
        self.time_label = QtWidgets.QLabel("0.00 sec")
        self.time_label.setObjectName("FW_PartMotionTime")
        bar.addWidget(self.time_label)
        for name, text, slot in (("FW_PartMotionZoomIn", "Zoom In", lambda: self.timeline.zoom(1.5)),
                                 ("FW_PartMotionZoomOut", "Zoom Out", lambda: self.timeline.zoom(1 / 1.5)),
                                 ("FW_PartMotionZoomFit", "Zoom to Fit", lambda: self.timeline.zoom_fit())):
            b = QtWidgets.QToolButton()
            b.setObjectName(name)
            b.setText({"Zoom In": "+", "Zoom Out": "-", "Zoom to Fit": "[ ]"}[text])
            b.setToolTip(text)
            b.clicked.connect(lambda _c=False, f=slot: f())
            bar.addWidget(b)
        lay.addLayout(bar)
        self.timeline = Timeline(self)
        self.area = QtWidgets.QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setWidget(self.timeline)
        lay.addWidget(self.area, 1)
        # the frame slider save_animation drives (frames 1..n); the time bar is the timeline's
        self.slider = QtWidgets.QSlider(Qt.Horizontal)
        self.slider.setObjectName("FW_PartMotionFrames")
        self.slider.setVisible(False)
        self.fps = QtWidgets.QSpinBox()
        self.fps.setRange(1, 240)
        self.fps.setValue(self.study.fps)
        self.fps.setVisible(False)
        self.duration = QtWidgets.QDoubleSpinBox()
        self.duration.setRange(0.1, 3600)
        self.duration.setValue(float(data(self.study)["duration"]))
        self.duration.setVisible(False)
        self._interval()
        self.last_seen = self._seen()
        QtCore.QTimer.singleShot(0, self.timeline.zoom_fit)

    def _button(self, name, text, icon, slot):
        b = QtWidgets.QToolButton()
        b.setObjectName(name)
        b.setText(text)
        b.setToolTip(text)
        try:
            from . import simicons
            pic = simicons.picture(icon)
            if not pic.isNull():
                b.setIcon(pic)
                b.setToolButtonStyle(Qt.ToolButtonIconOnly)
        except Exception as _fw_err:
            _fw_log("partmotion.py:icon", _fw_err)
        if slot is not None:
            b.clicked.connect(lambda _c=False, f=slot: f())
        return b

    # time and state -------------------------------------------------------------------------
    def _seen(self):
        """What the view and the bodies show now, to tell a change the user made (Autokey)."""
        doc = self.study.Document
        return (_tl().camera_now(), {b.Name: look_of(b) for b in bodies(doc)})

    def _expected(self, t):
        d = data(self.study)
        cam, looks = state_at(self.study, t, d, self.base_cam)
        if cam is None:
            cam = self.last_seen[0]
        for b in bodies(self.study.Document):
            if b.Name not in looks:
                rows = d["look"].get(b.Name)
                looks[b.Name] = look_at(rows, t) if rows else look_of(b)
        return cam, looks

    def autokey_changes(self):
        """Autokey: what the user changed at the time bar (away from 0) becomes keys there."""
        if not self.autokey.isChecked() or self.time <= 1e-6 or self._applying:
            return 0
        n = 0
        cam_now, looks_now = self._seen()
        cam_was, looks_was = self._expected(self.time)
        tl = _tl()
        if not tl.study_option(self.study, "no_view_keys") and cam_now is not None \
                and not tl.same_camera(cam_now, cam_was, 1e-3):
            set_key(self.study, VIEW_ROW, self.time, cam_now)
            n += 1
        for name, look in looks_now.items():
            if not same_look(look, looks_was.get(name)):
                set_key(self.study, name, self.time, look)
                n += 1
        if n:
            self.changed(redraw_only=True)
        return n

    def apply(self, t):
        self._applying = True
        try:
            cam, looks = state_at(self.study, t, None, self.base_cam)
            if cam is not None and not _tl().study_option(self.study, "no_view_playback"):
                _tl().set_camera(cam)
            doc = self.study.Document
            for name, look in looks.items():
                obj = doc.getObject(name)
                if obj is not None and look is not None:
                    apply_look(obj, look)
            v = _view()
            if v is not None:
                v.redraw()
        finally:
            self._applying = False
        self.last_seen = self._seen()

    def set_time(self, t):
        self.autokey_changes()
        d = data(self.study)
        self.time = max(0.0, min(float(t), max(float(d["duration"]), float(t))))
        self.apply(self.time)
        self.time_label.setText("%.2f sec" % self.time)
        self.timeline.update()

    def changed(self, redraw_only=False):
        self.duration.setValue(float(data(self.study)["duration"]))
        self.fps.setValue(self.study.fps)
        if not redraw_only:
            self.apply(self.time)
        self.timeline.update()

    # toolbar --------------------------------------------------------------------------------
    def _key(self):
        return (self.study.FwKeys, self.study.fps)

    def calculate(self):
        ""
        self.autokey_changes()
        d = data(self.study)
        fps = self.study.fps
        self.frames = int(round(float(d["duration"]) * fps)) + 1
        self.slider.blockSignals(True)
        self.slider.setRange(1, self.frames)
        self.slider.blockSignals(False)
        self.calc_key = self._key()
        if len(d["cams"]) <= 1 and not d["view"] and all(len(r) <= 1 for r in d["look"].values()):
            _say("Nothing moves yet: with the time bar away from 0, turn the view or change a body's look (Autokey), "
                 "or use the Animation Wizard.")
            return self.frames
        self.slider.setValue(self.frames)      # as the assembly's Calculate: the study ends on its last frame
        self.show_frame(self.frames)
        return self.frames

    def show_frame(self, i):
        fps = self.study.fps
        self.time = (max(1, int(i)) - 1) / float(fps)
        self.apply(self.time)
        self.time_label.setText("%.2f sec" % self.time)
        self.timeline.update()

    def _interval(self):
        try:
            k = float(self.speed.currentText()[:-1])
        except ValueError:
            k = 1.0
        self.timer.setInterval(max(1, int(1000.0 / (self.study.fps * k))))

    def play_start(self):
        self.stop()
        self.i, self.dir = 1, 1
        self.play()

    def play(self):
        if self.frames <= 0 or self.calc_key != self._key():
            self.calculate()                    # changed since the last Calculate
        if self.frames <= 1:
            return False
        if self.mode.currentText() == "Normal" and self.i >= self.frames:
            self.i, self.dir = 1, 1             # at the end: Play plays it again
        self._interval()
        self.timer.start()
        return True

    def stop(self):
        self.timer.stop()

    def _step(self):
        if self.i > self.frames or self.i < 1:
            mode = self.mode.currentText()
            if mode == "Loop":
                self.i = 1
            elif mode == "Reciprocate":
                self.dir = -self.dir
                self.i = max(1, min(self.frames, self.i + 2 * self.dir))
            else:
                self.i = self.frames
                self.timer.stop()
                return
        try:
            self.show_frame(self.i)
        except Exception as _fw_err:
            _fw_log("partmotion.py:step", _fw_err)
            self.timer.stop()
            return
        self.i += self.dir

    def add_key(self):
        """Add/Update Key: the view and every body at the time bar."""
        set_key(self.study, VIEW_ROW, self.time)
        for b in bodies(self.study.Document):
            set_key(self.study, b.Name, self.time)
        self.changed(redraw_only=True)
        _say("Keys added or updated at %.2f sec: the view and every body." % self.time)

    def place_key(self, row, t):
        """Place Key: the row's value at that time (what playback shows there) becomes a key."""
        if row == VIEW_ROW:
            value = self._expected(t)[0]
        else:
            value = self._expected(t)[1].get(row)
        set_key(self.study, row, t, value)
        self.changed(redraw_only=True)

    def wizard(self):
        dlg = WizardDialog(self)
        self.dialog = dlg
        dlg.show()
        return dlg

    def apply_wizard(self, axis, turns, clockwise, duration, start, delete_all=False):
        self.stop()
        if delete_all:
            d = data(self.study)
            d["view"] = []
            d["cams"] = d["cams"][:1]
            d["look"] = {k: v[:1] for k, v in d["look"].items()}
            save(self.study, d)
        self.base_cam = (data(self.study)["cams"] or [[0.0] + list(self.base_cam or [])])[0][1:5] or self.base_cam
        wizard_rotate(self.study, axis, turns, clockwise, duration, start)
        self.calculate()
        self.changed()
        self.timeline.zoom_fit()

    def save(self):
        self.stop()
        dlg = _tl().SaveAnimationDialog(self)
        self.dialog = dlg
        dlg.show()
        return dlg

    def properties(self):
        dlg = PropertiesDialog(self)
        self.dialog = dlg
        dlg.show()
        return dlg

    def collapse(self, on):
        self.area.setVisible(not on)

    def restore(self):
        """Back on the Model tab: the view and the bodies' looks as they were."""
        self.stop()


def shown():
    dock = PANE["dock"]
    try:
        return dock is not None and dock.isVisible()
    except RuntimeError:
        return False


def pane():
    dock = PANE["dock"]
    try:
        return dock.widget() if dock is not None else None
    except RuntimeError:
        return None


def show_pane():
    mw = Gui.getMainWindow()
    doc = App.ActiveDocument
    if not shown():
        try:
            view = _view()
            PANE["camera"] = (view, view.getCamera()) if view is not None else None
        except Exception:
            PANE["camera"] = None
        try:
            PANE["looks"] = (doc, {b.Name: look_of(b) for b in bodies(doc)}) if doc is not None else None
        except Exception:
            PANE["looks"] = None
    dock = PANE["dock"]
    try:
        alive = dock is not None and dock.objectName() is not None
    except RuntimeError:
        alive = False
    if alive:
        try:
            if dock.widget().study.Document is not doc:     # another part: a pane of its own
                dock.setWidget(MotionPane(dock, doc))
        except RuntimeError:
            alive = False
    if not alive:
        dock = QtWidgets.QDockWidget("Motion Study 1", mw)
        dock.setObjectName("FW_PartMotionManager")
        dock.setWidget(MotionPane(dock, doc))
        mw.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)
        PANE["dock"] = dock
    dock.show()
    dock.raise_()
    return dock


def hide_pane():
    dock = PANE["dock"]
    try:
        if dock is not None:
            w = dock.widget()
            w.autokey_changes()
            w.stop()
            dock.hide()
    except RuntimeError as _fw_err:
        _fw_log("partmotion.py:hide", _fw_err)
    saved, PANE["camera"] = PANE["camera"], None
    if saved is not None:
        try:
            saved[0].setCamera(saved[1])
        except Exception as _fw_err:
            _fw_log("partmotion.py:camera", _fw_err)
    looks, PANE["looks"] = PANE["looks"], None
    if looks is not None:
        doc, by_name = looks
        try:
            for name, look in by_name.items():
                obj = doc.getObject(name)
                if obj is not None:
                    apply_look(obj, look)
        except Exception as _fw_err:
            _fw_log("partmotion.py:looks", _fw_err)
