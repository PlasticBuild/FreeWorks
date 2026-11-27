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
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac
from . import selguard

STUDY_PROP = "FwMotionStudy"
KIND_PROP = "FwStudyType"           # Animation, Basic Motion or Motion Analysis
GRAVITY_PROP = "FwGravity"          # "x,y,z,mm/s^2" or "" (no gravity)
STUDY_TYPES = ("Animation", "Basic Motion", "Motion Analysis")

MOTOR_PROP = "FwMotor"              # json: the Motor PM's values
TYPES = ("Rotary Motor", "Linear Motor (Actuator)")
MOTIONS = ("Constant Speed", "Distance", "Oscillating", "Segments", "Data Points", "Expression")
FUNCTION_MOTIONS = ("Segments", "Data Points", "Expression")   # the Function Builder (asmfunction)
ROTARY_JOINTS = ("Revolute", "Cylindrical")
LINEAR_JOINTS = ("Slider", "Cylindrical")
SPEEDS = ("0.1x", "0.25x", "0.5x", "1x", "2x", "5x", "10x")
MODES = ("Playback Mode: Normal", "Playback Mode: Loop", "Playback Mode: Reciprocate")
DURATION = 5.0
FPS = 25
PANE = {"dock": None}


# ---------------------------------------------------------------- studies and motors
def studies(asm):
    import UtilsAssembly
    out = []
    for obj in asm.OutList:
        if obj.TypeId == "Assembly::SimulationGroup":
            out += [s for s in obj.Group if getattr(s, STUDY_PROP, False)]
    return out


def _next(names, base, sep=""):
    n = 1
    while "%s%s%d" % (base, sep, n) in names:
        n += 1
    return "%s%s%d" % (base, sep, n)


def new_study(asm):
    import UtilsAssembly
    import CommandCreateSimulation as CS
    group = UtilsAssembly.getSimulationGroup(asm)
    if App.GuiUp and group.ViewObject is not None:
        try:
            group.ViewObject.ShowInTree = False
        except Exception as _fw_err:
            _fw_log("asmmotion.py:80", _fw_err)
    sim = group.newObject("App::FeaturePython", "MotionStudy")
    CS.Simulation(sim)
    if App.GuiUp and sim.ViewObject is not None:
        CS.ViewProviderSimulation(sim.ViewObject)
    sim.addProperty("App::PropertyBool", STUDY_PROP, "FreeCAD", "A motion study of the assembly")
    sim.setPropertyStatus(STUDY_PROP, "Hidden")
    setattr(sim, STUDY_PROP, True)
    sim.Label = _next({s.Label for s in studies(asm)}, "Motion Study", " ")     # "Motion Study 1"
    _study_props(sim)
    sim.bTimeEnd = DURATION
    sim.cTimeStepOutput = 1.0 / FPS
    sim.jFramesPerSecond = FPS
    return sim


def _study_props(sim):
    for prop, doc in ((KIND_PROP, "Study type"), (GRAVITY_PROP, "Gravity: x,y,z,mm/s^2")):
        if not hasattr(sim, prop):
            sim.addProperty("App::PropertyString", prop, "FreeCAD", doc)
            sim.setPropertyStatus(prop, "Hidden")
    if not getattr(sim, KIND_PROP):
        setattr(sim, KIND_PROP, STUDY_TYPES[0])


def study_type(sim):
    return getattr(sim, KIND_PROP, "") or STUDY_TYPES[0]


def gravity(sim):
    """(direction, mm/s^2) or None."""
    text = getattr(sim, GRAVITY_PROP, "") or ""
    try:
        x, y, z, g = (float(v) for v in text.split(","))
    except ValueError:
        return None
    return App.Vector(x, y, z), g


def set_gravity(sim, direction, value):
    _study_props(sim)
    setattr(sim, GRAVITY_PROP, "" if direction is None else "%.12g,%.12g,%.12g,%.12g" % (
        direction.x, direction.y, direction.z, value))


def motors(sim):
    return [m for m in sim.Group if getattr(m, MOTOR_PROP, "")]


def motor_values(motor):
    import json
    try:
        return json.loads(getattr(motor, MOTOR_PROP, "") or "{}")
    except ValueError:
        return {}


def joint_for(asm, comp, rotary, relative=None):
    ""

    kinds = ROTARY_JOINTS if rotary else LINEAR_JOINTS
    for j in ac.joint_group(asm).Group:
        if getattr(j, "JointType", None) not in kinds or getattr(j, "Suppressed", False):
            continue
        refs = [getattr(j, p, None) for p in ("Reference1", "Reference2")]
        if not any(r and r[0] is comp for r in refs):
            continue
        if relative is not None and not any(r and r[0] is relative for r in refs):
            continue
        return j
    return None


def _relative(asm, values):
    name = values.get("relative") or ""
    return next((c for c in ac.components(asm) if c.Name == name), None) if name else None


def formula(values, duration, fps=25):
    """The motion as FreeCAD's formula of time: radians for a rotary motor, mm for a linear one."""
    rotary = values.get("type", TYPES[0]) == TYPES[0]
    sign = _sign(values)
    motion = values.get("motion", MOTIONS[0])
    if motion in FUNCTION_MOTIONS:
        from . import asmfunction
        func = values.get("function") or asmfunction.default(motion, rotary)
        try:
            return asmfunction.formula(func, duration, fps, sign * (math.pi / 180.0 if rotary else 1.0))
        except ValueError:
            return "0*time"
    if motion == "Constant Speed":
        rate = values.get("speed", 100.0) * (2 * math.pi / 60.0 if rotary else 1.0)   # RPM or mm/s
        return "%.12g*time" % (sign * rate)
    if motion == "Distance":
        total = values.get("distance", 90.0) * (math.pi / 180.0 if rotary else 1.0)    # deg or mm
        start, span = _window(values, duration)
        if start <= 1e-12 and abs(span - duration) < 1e-9:
            return "%.12g*time" % (sign * total / max(duration, 1e-9))

        # after: (|t-s| - |t-s-d|)/2 + d/2, written with FreeCAD's (x^2)^0.5
        a, b = "(time-%.12g)" % start, "(time-%.12g)" % (start + span)
        k = sign * total / max(span, 1e-9)
        return "%.12g*((%s^2)^0.5-(%s^2)^0.5)+%.12g" % (k / 2.0, a, b, k * span / 2.0)
    amp = values.get("amplitude", 30.0) * (math.pi / 180.0 if rotary else 1.0)
    freq = values.get("frequency", 1.0)
    phase = math.radians(values.get("phase", 0.0))
    if abs(phase) > 1e-12:
        return "%.12g*sin(%.12g*time+%.12g)" % (sign * amp, 2 * math.pi * freq, phase)
    return "%.12g*sin(%.12g*time)" % (sign * amp, 2 * math.pi * freq)


def _window(values, duration):
    """A Distance motor's Start Time and Duration (s): the whole study when not set."""
    start = max(0.0, float(values.get("start", 0.0) or 0.0))
    span = values.get("duration")
    span = float(span) if span else max(duration - start, 1e-9)
    return start, max(span, 1e-9)


def _sign(values):
    """+1 or -1: Reverse Direction, and a Motor Direction picked against the mate's own axis."""
    sign = -1.0 if values.get("reverse") else 1.0
    return -sign if values.get("axis_flip") else sign


def joint_axis(comp, joint):
    """The axis (global) along or about which joint moves comp."""
    side1 = bool(getattr(joint, "Reference1", None)) and joint.Reference1[0] is comp
    g = comp.Placement.multiply(joint.Placement1 if side1 else joint.Placement2)
    return g.Rotation.multVec(App.Vector(0, 0, 1))


def add_motor(asm, sim, values, motor=None):
    import json
    import CommandCreateSimulation as CS
    rotary = values.get("type", TYPES[0]) == TYPES[0]
    comp = next((c for c in ac.components(asm) if c.Name == values.get("component")), None)
    joint = joint_for(asm, comp, rotary, _relative(asm, values)) if comp is not None else None
    if joint is None:
        return None
    values = dict(values)
    values.pop("axis_flip", None)
    if values.get("direction"):
        try:
            values["axis_flip"] = joint_axis(comp, joint).dot(App.Vector(*values["direction"])) < 0
        except Exception as _fw_err:
            _fw_log("asmmotion.py:199", _fw_err)
    text = formula(values, float(sim.bTimeEnd), int(sim.jFramesPerSecond))
    kind = "Angular" if rotary else "Linear"
    if motor is None:
        motor = asm.newObject("App::FeaturePython", "Motor")
        CS.Motion(motor, kind, joint, text)
        if App.GuiUp and motor.ViewObject is not None:
            CS.ViewProviderMotion(motor.ViewObject)
            try:
                motor.ViewObject.ShowInTree = False
            except Exception as _fw_err:
                _fw_log("asmmotion.py:210", _fw_err)
        motor.addProperty("App::PropertyString", MOTOR_PROP, "FreeCAD", "The Motor PM's values")
        motor.setPropertyStatus(MOTOR_PROP, "Hidden")
        motor.Label = _next({m.Label for s in studies(asm) for m in motors(s)},
                            "RotaryMotor" if rotary else "LinearMotor")
        sim.Group = sim.Group + [motor]
    else:
        motor.MotionType = kind
        motor.Joint = joint
        motor.Formula = text
    setattr(motor, MOTOR_PROP, json.dumps(values))
    return motor


def remove_motor(sim, motor):
    sim.Group = [m for m in sim.Group if m is not motor]
    motor.Document.removeObject(motor.Name)


def calculate(asm, sim, duration=None, fps=None):
    ""


    n = _calculate(asm, sim, duration, fps)
    if n:
        try:
            from . import asmcam
            key = (asm.Document.Name, sim.Name)
            frames = asmcam.follow_frames(asm, HELD.get(key), n)
            if frames is not None:
                HELD[key] = frames
        except Exception as _fw_err:
            _fw_log("asmmotion.py:cam frames", _fw_err)
    return n


def _calculate(asm, sim, duration=None, fps=None):
    if duration is not None:
        sim.bTimeEnd = float(duration)
    if fps is not None:
        sim.jFramesPerSecond = int(fps)
        sim.cTimeStepOutput = 1.0 / max(1, int(fps))
    for m in motors(sim):       # a Distance motor spreads over the duration
        v = motor_values(m)
        if v:
            m.Formula = formula(v, float(sim.bTimeEnd), int(sim.jFramesPerSecond))
    if study_type(sim) != STUDY_TYPES[0]:
        return None             # Basic Motion and Motion Analysis: physics()
    if not motors(sim):
        return 0

    # the other side of the mate it drives is held still while the frames are made, unless another
    # motor moves it (FreeCAD drives the mate, which would share the turn between the two)
    moved = set()
    for m in motors(sim):
        v = motor_values(m) or {}
        moved.add(v.get("component"))
    hold = []
    for m in motors(sim):
        v = motor_values(m) or {}
        j = getattr(m, "Joint", None)
        j = j[0] if isinstance(j, (tuple, list)) and j else j
        if j is None:
            continue
        for prop in ("Reference1", "Reference2"):
            ref = getattr(j, prop, None)
            comp = ref[0] if ref else None
            if comp is not None and comp.Name != v.get("component") and comp.Name not in moved and comp not in hold:
                hold.append(comp)
    key = (asm.Document.Name, sim.Name)
    HELD.pop(key, None)
    want = int(round(float(sim.bTimeEnd) * int(sim.jFramesPerSecond))) + 1
    if not hold:
        n = _generate(asm, sim, moved)
        if n < want - 1:
            n = _stepped(asm, sim, hold, key, n)
        return n
    with ac.temp_ground(asm, hold):
        n = _generate(asm, sim, moved)
        # FreeCAD re-solves each frame it shows with the mates as they are then: the frames are
        # kept as placements while the held components are held, and shown from those
        frames = []
        comps = ac.components(asm)
        for k in range(n):
            try:
                asm.updateForFrame(k)
            except Exception:
                break
            frames.append({c.Name: App.Placement(c.Placement) for c in comps})
        if frames:
            for c in comps:
                if c.Name in frames[0]:
                    c.Placement = frames[0][c.Name]
    HELD[key] = frames
    if n < want - 1:
        n = _stepped(asm, sim, hold, key, n)
    return n


def _motor_at(values, t, duration):
    """A motor's angle (radians) or distance (mm) at time t, from its PropertyManager values."""
    rotary = values.get("type", TYPES[0]) == TYPES[0]
    unit = math.pi / 180.0 if rotary else 1.0
    sign = _sign(values)
    motion = values.get("motion", MOTIONS[0])
    if motion == "Constant Speed":
        return sign * values.get("speed", 100.0) * (2 * math.pi / 60.0 if rotary else 1.0) * t
    if motion == "Distance":
        start, span = _window(values, duration)
        f = min(1.0, max(0.0, (t - start) / span))
        return sign * values.get("distance", 90.0) * unit * f
    if motion in FUNCTION_MOTIONS:
        return None
    return sign * values.get("amplitude", 30.0) * unit * math.sin(2 * math.pi * values.get("frequency", 1.0) * t
                                                                   + math.radians(values.get("phase", 0.0)))


def _stepped(asm, sim, hold, key, n):
    ""



    duration = float(sim.bTimeEnd)
    fps = int(sim.jFramesPerSecond)
    want = int(round(duration * fps)) + 1
    drives = []
    for m in motors(sim):
        v = motor_values(m) or {}
        comp = next((c for c in ac.components(asm) if c.Name == v.get("component")), None)
        j = getattr(m, "Joint", None)
        j = j[0] if isinstance(j, (tuple, list)) and j else j
        if comp is None or j is None or _motor_at(v, 0.0, duration) is None:
            return n
        side1 = j.Reference1[0] is comp if getattr(j, "Reference1", None) else False
        g = comp.Placement.multiply(j.Placement1 if side1 else j.Placement2)
        drives.append((comp, v, g.Base, g.Rotation.multVec(App.Vector(0, 0, 1)), App.Placement(comp.Placement)))
    if not drives:
        return n
    comps = ac.components(asm)
    start = {c.Name: App.Placement(c.Placement) for c in comps}
    try:
        asm.updateForFrame(0)
    except Exception as _fw_err:
        _fw_log("asmmotion.py:334", _fw_err)
    for c in comps:
        c.Placement = start[c.Name]
    frames = [dict(start)]
    held = list(hold) + [d[0] for d in drives]
    t0 = time.time()
    try:
        def place(t):
            for comp, v, point, axis, plc in drives:
                x = _motor_at(v, t, duration)
                if v.get("type", TYPES[0]) == TYPES[0]:
                    deg = (math.degrees(x) + 180.0) % 360.0 - 180.0     # many turns: the same turn within one
                    move = App.Placement(App.Vector(), App.Rotation(axis, deg), point)
                else:
                    move = App.Placement(axis * x, App.Rotation())
                new = move.multiply(plc)
                q = new.Rotation.Q
                if q[3] < 0:        # the same turn written the short way: FreeCAD's solver can fail on the other
                    new = App.Placement(new.Base, App.Rotation(-q[0], -q[1], -q[2], -q[3]))
                comp.Placement = new

        def solved():
            with ac.temp_ground(asm, held):
                ok = ac.solve(asm)
            return ok and all(ac.satisfied(j) for j in ms)
        ms = [j for j in ac.mates(asm) if not getattr(j, "Suppressed", False)]
        for k in range(want):
            t = k / float(fps)
            place(t)
            if not solved() and k > 0:
                # a step the solver took the long way round: from the last frame in small steps
                for c in comps:
                    c.Placement = frames[-1][c.Name]
                ok = True
                for sub in range(1, 5):
                    place((k - 1 + sub / 4.0) / float(fps))
                    ok = solved()
                if not ok:
                    # pkg323: FreeCAD's solver can fail at one exact crank angle (its "vector::_M_range_check"):
                    # from the last frame, a hair either side of the frame's time, then back onto it
                    for nudge in (1e-4, -1e-4):
                        for c in comps:
                            c.Placement = frames[-1][c.Name]
                        place(t + nudge / fps)
                        if solved():
                            place(t)
                            ok = solved()
                            if not ok:
                                place(t + nudge / fps)
                                ok = solved()      # the frame a hair off its time: well within a pixel
                        if ok:
                            break
                if not ok:
                    STEP_FAILS.append((sim.Name, k, [j.Label for j in ms if not ac.satisfied(j)]))
            frames.append({c.Name: App.Placement(c.Placement) for c in comps})
            if time.time() - t0 > 600:
                break
    finally:
        for c in comps:
            c.Placement = start[c.Name]
    HELD[key] = frames
    App.Console.PrintLog("FreeCAD: motion study: %d frames made by stepping (FreeCAD's stopped at %d)\n" % (len(frames), n))
    return len(frames)


def _generate(asm, sim, moved=()):
    """FreeCAD's simulation, once more when it stops short: a pin free to spin on its axis that has
    spun half a turn (dragged round) stops FreeCAD's simulation at its first step. Such spins are
    taken back first (nothing else moves)."""
    asm.generateSimulation(sim)
    n = asm.numberOfFrames()
    want = int(round(float(sim.bTimeEnd) * int(sim.jFramesPerSecond))) + 1
    if n < want - 1 and ac.unspin(asm, exclude=set(moved)):
        asm.generateSimulation(sim)
        n = asm.numberOfFrames()
    return n


STEP_FAILS = []     # (study, frame, mates not holding) where a stepped frame could not be solved
HELD = {}       # (document, study) -> [{component: placement}] per frame, made with components held
CALCULATED = {}     # (document, study, study type) -> (frames, duration, fps): the last Basic Motion / Motion Analysis


def physics(asm, sim):
    """Basic Motion / Motion Analysis: gravity and motors on the free components (asmphysics)."""
    from . import asmphysics
    drives = []
    for m in motors(sim):
        joint = m.Joint[0] if isinstance(m.Joint, (tuple, list)) else m.Joint
        if joint is None:
            continue
        text = m.Formula
        v = motor_values(m)
        # a linear motor: the formula is in mm already, and it slides its component (asmpkg360)
        drives.append((joint, text, bool(v and v.get("type", TYPES[0]) != TYPES[0])))
    from . import asmloads
    from . import asmtimeline as tl
    o = tl.study_options(sim)
    # Basic Motion's 3D contact resolution (50 = ten steps a frame) and Use precise contact
    sub = max(2, int(round(int(o.get("contact_res", 50)) / 5.0)))
    if o.get("precise_contact"):
        sub *= 4
    return asmphysics.simulate(asm, float(sim.bTimeEnd), int(sim.jFramesPerSecond), gravity(sim), drives,
                               asmloads.updated(asm, asmloads.loads(sim)), sub=sub)


# ---------------------------------------------------------------- the Motion Study pane
class _MotorList(QtWidgets.QListWidget):
    """The study's motors: double-click edits, Delete (or the right-click Delete) removes."""

    def __init__(self, pane):
        super().__init__()
        self._pane = pane
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def event(self, e):
        if e.type() == QtCore.QEvent.ShortcutOverride and e.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            e.accept()          # the motor's Delete, not FreeCAD's Delete of the selection
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self._pane.delete_current()
            return
        super().keyPressEvent(e)

    def _menu(self, pos):
        item = self.itemAt(pos)
        menu = QtWidgets.QMenu(self)
        if item is not None:
            self.setCurrentItem(item)
            menu.addAction("Edit Feature", lambda: self._pane._edit_motor(item))
            menu.addAction("Delete", self._pane.delete_current)
            menu.addSeparator()
        from . import asmmotionint
        menu.addAction("Check Interference...", lambda: asmmotionint.open_panel(self._pane))
        menu.popup(self.mapToGlobal(pos))


_TOOL_ICONS = {
    "FW_MotionCalculate": ("MOTION_CALCULATE", QtWidgets.QStyle.SP_BrowserReload),
    "FW_MotionPlayStart": ("MOTION_PLAY_FROM_START", QtWidgets.QStyle.SP_MediaSkipBackward),
    "FW_MotionPlay": ("MOTION_PLAY", QtWidgets.QStyle.SP_MediaPlay),
    "FW_MotionStop": ("MOTION_STOP", QtWidgets.QStyle.SP_MediaStop),
    "FW_MotionSave": ("MOTION_SAVE_ANIMATION", QtWidgets.QStyle.SP_DialogSaveButton),
    "FW_MotionWizard": ("MOTION_WIZARD", None),
    "FW_MotionAutokey": ("MOTION_AUTOKEY", None),
    "FW_MotionAddKey": ("MOTION_ADD_KEY", None),
    "FW_MotionMotor": ("MOTION_MOTOR", None),
    "FW_MotionSpring": ("MOTION_SPRING", None),
    "FW_MotionDamper": ("MOTION_DAMPER", None),
    "FW_MotionForce": ("MOTION_FORCE", None),
    "FW_MotionContact": ("MOTION_CONTACT", None),
    "FW_MotionGravity": ("MOTION_GRAVITY", None),
    "FW_MotionResults": ("MOTION_RESULTS", QtWidgets.QStyle.SP_FileDialogDetailedView),
    "FW_MotionProperties": ("MOTION_STUDY_PROPERTIES", QtWidgets.QStyle.SP_FileDialogInfoView),
    "FW_MotionCollapse": ("MOTION_COLLAPSE", None),
}


class MotionPane(QtWidgets.QWidget):
    @property
    def _applying(self):
        return getattr(self, "_fw_applying", False)

    @_applying.setter
    def _applying(self, on):
        self._fw_applying = bool(on)
        if not on:          # what the pane put on the parts is not a change to key
            watch = getattr(Gui, "_fw_lookwatch", None)
            if watch is not None and hasattr(watch, "resync"):
                watch.resync(self)

    def __init__(self, asm, sim):
        super().__init__()
        self.asm, self.sim = asm, sim
        self.frames = 0
        self.direction = 1
        self.setObjectName("FW_MotionPane")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        row = QtWidgets.QHBoxLayout()
        self.kind = self._combo("FW_MotionType", STUDY_TYPES)
        _study_props(sim)
        self.kind.setCurrentText(study_type(sim))
        self.kind.currentTextChanged.connect(self._kind_changed)
        row.addWidget(self.kind)
        self.own = None         # Basic Motion / Motion Analysis: (frames, results)
        self.start = {c.Name: App.Placement(c.Placement) for c in ac.components(asm)}   # the study's time 0
        for name, text, slot in (("FW_MotionCalculate", "Calculate", self.calculate),
                                 ("FW_MotionPlayStart", "Play from Start", self.play_from_start),
                                 ("FW_MotionPlay", "Play", self.play),
                                 ("FW_MotionStop", "Stop", self.stop)):
            b = QtWidgets.QToolButton()
            b.setObjectName(name)
            b.setText(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        self.speed = self._combo("FW_MotionSpeed", SPEEDS)
        self.speed.setCurrentText("1x")
        row.addWidget(self.speed)
        self.mode = self._combo("FW_MotionMode", MODES)
        row.addWidget(self.mode)
        from . import asmtimeline as tl
        self._applying = False
        self.camera = tl._Camera()
        self.camera.capture()
        tl.ensure_start(asm, sim)
        for name, text, slot in (("FW_MotionSave", "Save Animation", self.save_animation),
                                 ("FW_MotionWizard", "Animation Wizard", self.animation_wizard)):
            b = QtWidgets.QToolButton()
            b.setObjectName(name)
            b.setText(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        self.autokey = QtWidgets.QToolButton()
        self.autokey.setObjectName("FW_MotionAutokey")
        self.autokey.setText("Autokey")
        self.autokey.setCheckable(True)
        self.autokey.setChecked(True)
        row.addWidget(self.autokey)
        b = QtWidgets.QToolButton()
        b.setObjectName("FW_MotionAddKey")
        b.setText("Add/Update Key")
        b.clicked.connect(self.add_key)
        row.addWidget(b)
        motor = QtWidgets.QToolButton()
        motor.setObjectName("FW_MotionMotor")
        motor.setText("Motor")
        motor.clicked.connect(lambda: open_motor(self.asm, self.sim))
        row.addWidget(motor)
        props = QtWidgets.QToolButton()
        props.setObjectName("FW_MotionProperties")
        props.setText("Motion Study Properties")
        props.clicked.connect(self.study_properties)
        self.gravity_btn = QtWidgets.QToolButton()
        self.gravity_btn.setObjectName("FW_MotionGravity")
        self.gravity_btn.setText("Gravity")
        self.gravity_btn.clicked.connect(lambda: open_gravity(self.asm, self.sim))
        from . import asmloads
        self.load_btns = []
        for name, text, cls in (("FW_MotionSpring", "Spring", asmloads.SpringPanel),
                                ("FW_MotionDamper", "Damper", asmloads.DamperPanel),
                                ("FW_MotionForce", "Force", asmloads.ForcePanel),
                                ("FW_MotionContact", "Contact", asmloads.ContactPanel)):
            b = QtWidgets.QToolButton()
            b.setObjectName(name)
            b.setText(text)
            b.clicked.connect(lambda _c=False, k=cls: asmloads.open_panel(k, self.asm, self.sim))
            row.addWidget(b)
            self.load_btns.append(b)
        row.addWidget(self.gravity_btn)
        self.results_btn = QtWidgets.QToolButton()  # then Results and Plots and Motion Study Properties
        self.results_btn.setObjectName("FW_MotionResults")
        self.results_btn.setText("Results and Plots")
        self.results_btn.clicked.connect(self.open_results)
        row.addWidget(self.results_btn)
        row.addWidget(props)
        self.collapse_btn = QtWidgets.QToolButton()
        self.collapse_btn.setObjectName("FW_MotionCollapse")
        self.collapse_btn.setText("Collapse MotionManager")
        self.collapse_btn.setCheckable(True)
        self.collapse_btn.toggled.connect(self.collapse)
        row.addWidget(self.collapse_btn)
        row.addWidget(QtWidgets.QLabel("Duration:"))
        self.duration = QtWidgets.QDoubleSpinBox()
        self.duration.setObjectName("FW_MotionDuration")
        self.duration.setRange(0.1, 3600.0)
        self.duration.setSuffix(" sec")
        self.duration.setValue(float(sim.bTimeEnd))
        row.addWidget(self.duration)
        row.addWidget(QtWidgets.QLabel("Frames per second:"))
        self.fps = QtWidgets.QSpinBox()
        self.fps.setObjectName("FW_MotionFps")
        self.fps.setRange(1, 240)
        self.fps.setValue(int(sim.jFramesPerSecond))
        row.addWidget(self.fps)
        row.addStretch(1)
        lay.addLayout(row)
        body = QtWidgets.QHBoxLayout()
        self.list = _MotorList(self)
        self.list.setObjectName("FW_MotionMotors")
        self.list.setFixedWidth(220)
        self.list.itemDoubleClicked.connect(self._edit_motor)
        body.addWidget(self.list)

        # (the timeline's left column, where double-click edits and Delete removes them)
        self.list.hide()
        right = QtWidgets.QVBoxLayout()
        self.timeline = tl.Timeline(self)
        self.timeline_bar = tl.TimelineBar(self.timeline)
        right.addWidget(self.timeline_bar)
        right.addWidget(self.timeline, 1)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setObjectName("FW_MotionTime")
        self.slider.setRange(0, 0)
        self.slider.valueChanged.connect(self.show_frame)
        right.addWidget(self.slider)
        self.time = QtWidgets.QLabel("0.00 sec")
        self.time.setObjectName("FW_MotionTimeLabel")
        right.addWidget(self.time)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("FW_MotionStatus")
        right.addWidget(self.status)
        body.addLayout(right, 1)
        lay.addLayout(body)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.refresh()
        self._kind_changed(self.kind.currentText())
        self.duration.valueChanged.connect(lambda *_: (self.stale(), self.timeline.update()))
        _KEYWATCH["pane"] = self
        self.looks = {c.Name: tl.look_of(c) for c in ac.components(asm)}   # appearances before any change
        self.mate0 = {j.Name: tl.mate_value(j) for j in tl.keyable_mates(asm)}   # mate values before any key
        self.cam0 = tl.camera_now()             # the view before any view key
        self.last_cam = self.cam0
        self.cam_watch = QtCore.QTimer(self)
        self.cam_watch.setInterval(300)
        self.cam_watch.timeout.connect(self.view_changed)
        self.cam_watch.start()
        self.fps.valueChanged.connect(self._fps_changed)
        self._iconify()

    def _fps_changed(self, v):
        from . import asmtimeline as tl
        if hasattr(self.sim, tl.OPTIONS_PROP):
            key = {STUDY_TYPES[0]: "anim_fps", STUDY_TYPES[2]: "ma_fps"}.get(self.kind.currentText(), "basic_fps")
            if tl.study_option(self.sim, key) != v:
                tl.set_study_options(self.sim, {key: int(v)})

    # ------------------------------------------------------------ keys (asmtimeline)
    def stale(self):
        """The keys changed: the frames are calculated again on the next Play."""
        if self.own is not None and isinstance(self.own[1], dict):
            self.own = None
            self.frames = 0

    def at_time(self, t):
        """The time bar moved to t (the timeline): the calculated frame there, or the keys' positions."""
        from . import asmtimeline as tl
        if self.frames > 0:
            step = float(self.sim.cTimeStepOutput) or 1.0 / max(1, self.fps.value())
            self.slider.setValue(max(self.slider.minimum(), min(self.slider.maximum(), 1 + int(round(t / step)))))
            return
        d = tl.live_data(self.sim)       # suppressed keys are passed over
        self._applying = True
        try:
            doc = self.asm.Document
            for name, rows in d["comps"].items():
                obj = doc.getObject(name)
                plc = tl.placement_at(rows, t)
                if obj is not None and plc is not None and not obj.Placement.isSame(plc, 1e-9):
                    obj.Placement = plc
            axis, deg = tl.view_angle(d, t)
            tl.apply_looks(self.asm, self.sim, t)
            tl.apply_mates(self.asm, self.sim, t)
            self._view_at(axis, deg, t)
            self.last_cam = tl.camera_now()         # the study turned the view, not a hand
            self.time.setText("%.2f sec" % t)
            Gui.updateGui()
        finally:
            self._applying = False

    def add_key(self):
        """Add/Update Key: the picked components (all when none is picked) keyed at the time bar."""
        from . import asmtimeline as tl
        comps = ac.components(self.asm)
        names = {c.Name for c in comps}
        picked = []
        for s in Gui.Selection.getSelectionEx(self.asm.Document.Name):
            if s.ObjectName in names:
                picked.append(s.Object)
            for sub in s.SubElementNames or ():
                head = sub.split(".")[0]
                if head in names:
                    picked.append(self.asm.Document.getObject(head))
        doc = self.asm.Document
        doc.openTransaction("Add/Update Key")
        try:
            for c in picked or comps:
                tl.set_key(self.sim, c, self.timeline.time)
        finally:
            doc.commitTransaction()
        self.stale()
        self.timeline.update()
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "Keys added or updated at %.2f sec: %s." % (self.timeline.time, ", ".join(c.Label for c in (picked or comps))
                                                           or "no components"), 8000)
        except Exception as _fw_err:
            _fw_log("asmmotion.py:add_key", _fw_err)
        return picked or comps

    def moved(self, obj):
        """Autokey: a component moved by hand with the pane open gets a key at the time bar."""
        from . import asmtimeline as tl
        if self._applying or self.timer.isActive() or not self.autokey.isChecked():
            return
        import time
        if time.monotonic() < getattr(self, "_mate_until", 0.0):
            return                              # moved by a keyed mate's solve
        if obj.Name not in {c.Name for c in ac.components(self.asm)}:
            return
        tl.set_key(self.sim, obj, self.timeline.time)
        self.stale()
        self.timeline.update()

    def mate_changed(self, j):
        """Autokey: a Distance or Angle mate's value changed with the time bar away from 0."""
        from . import asmtimeline as tl
        if self._applying or self.timer.isActive() or not self.autokey.isChecked():
            return
        if j.Name not in {m.Name for m in tl.keyable_mates(self.asm)}:
            return
        v = tl.mate_value(j)
        t = self.timeline.time
        if t <= 0 and not tl.mate_keys(self.sim, j.Name):
            self.mate0[j.Name] = v
            return
        tl.set_mate_key(self.sim, j.Name, t, v, self.mate0.get(j.Name))
        self.stale()
        self.timeline.update()

    def view_changed(self):
        """Autokey: the view turned, zoomed or panned with the time bar away from 0 puts a view key
        on Orientation and Camera Views (unless Disable View Key Creation)."""
        from . import asmtimeline as tl
        try:
            if not self.isVisible() or self._applying or self.timer.isActive():
                return
            if Gui.ActiveDocument is None or Gui.ActiveDocument.Document is not self.asm.Document:
                return
            name = getattr(self.sim, "Name", None)     # a deleted study's Name reads None
            if not name or self.asm.Document.getObject(name) is not self.sim:
                raise ReferenceError("the study was deleted")
        except (RuntimeError, ReferenceError):      # the pane or its assembly is gone
            try:
                self.cam_watch.stop()
                if PANE["dock"] is not None and PANE["dock"].widget() is self:
                    PANE["dock"].hide()
            except Exception as _fw_err:
                _fw_log("asmmotion.py:745", _fw_err)
            return
        cam = tl.camera_now()
        if cam is None or tl.same_camera(cam, self.last_cam):
            return
        if not self.autokey.isChecked() or tl.study_option(self.sim, "no_view_keys") or (
                self.timeline.time <= 0 and not tl.view_keys(self.sim)):
            if self.timeline.time <= 0 and not tl.view_keys(self.sim):
                self.cam0 = cam                 # at 0 it is just the starting view
            self.last_cam = cam
            return
        tl.set_view_key(self.sim, self.timeline.time, cam, self.cam0)
        self.last_cam = cam
        self.stale()
        self.timeline.update()

    def look_changed(self, obj):
        """Autokey: a component hidden, shown or recoloured with the time bar away from 0."""
        from . import asmtimeline as tl
        if self._applying or self.timer.isActive() or not self.autokey.isChecked():
            return
        if obj.Name not in {c.Name for c in ac.components(self.asm)}:
            return
        t = self.timeline.time
        before = self.looks.get(obj.Name)
        now = tl.look_of(obj)
        if t <= 0 and not tl.look_keys(self.sim, obj.Name):
            self.looks[obj.Name] = now          # at 0 it is simply how the part looks
            return
        tl.set_look_key(self.sim, obj, t, now, before)
        self.looks[obj.Name] = now
        self.stale()
        self.timeline.update()

    def animation_wizard(self):
        from . import asmtimeline as tl
        self.wizard = tl.AnimationWizard(self.asm, self.sim, self)
        self.wizard.pane = self
        self.wizard.finished.connect(lambda code: code and self._after_wizard())
        self.wizard.show()
        return self.wizard

    def _after_wizard(self):
        self.duration.setValue(float(self.sim.bTimeEnd))
        self.stale()
        self.timeline.update()

    def collapse(self, on=True):
        """Collapse MotionManager: only the toolbar stays; the tree, timeline and time bar fold away (and back)."""
        for w in (self.timeline_bar, self.timeline, self.slider, self.time, self.status):
            w.setVisible(not on)
        if self.collapse_btn.isChecked() != bool(on):
            self.collapse_btn.setChecked(bool(on))
        self.collapse_btn.setText("Expand MotionManager" if on else "Collapse MotionManager")
        self.collapse_btn.setToolTip(self.collapse_btn.text())

    def study_properties(self):
        from . import asmtimeline as tl
        self.properties_dialog = tl.MotionStudyProperties(self, self)
        self.properties_dialog.show()
        return self.properties_dialog

    def apply_study_fps(self):
        """Motion Study Properties: the frames per second of the study's type."""
        from . import asmtimeline as tl
        key = {STUDY_TYPES[0]: "anim_fps", STUDY_TYPES[2]: "ma_fps"}.get(self.kind.currentText(), "basic_fps")
        if hasattr(self.sim, tl.OPTIONS_PROP):
            self.fps.setValue(int(tl.study_option(self.sim, key)))

    def save_animation(self):
        from . import asmtimeline as tl
        self.save_dialog = tl.SaveAnimationDialog(self, self)
        self.save_dialog.show()
        return self.save_dialog

    def _kind_changed(self, text):
        ""
        _study_props(self.sim)
        if getattr(self.sim, KIND_PROP) != text:
            setattr(self.sim, KIND_PROP, text)
            self.frames = 0
            self.own = None
        # a button the study type cannot use is not shown (it comes back with the type): no greyed tools
        self.gravity_btn.setVisible(text != STUDY_TYPES[0])
        for b in getattr(self, "load_btns", ()):

            # Motion Analysis only
            only_analysis = b.objectName() in ("FW_MotionDamper", "FW_MotionForce")
            b.setVisible(text == STUDY_TYPES[2] if only_analysis else text != STUDY_TYPES[0])
        if hasattr(self, "timeline"):
            self.apply_study_fps()
        self.results_btn.setVisible(text == STUDY_TYPES[2])

    def open_results(self):
        ""

        if self.own is None and not self.calculate():
            return None
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        panel = ResultsPanel(self)
        RESULTS[:] = [panel]
        Gui.Control.showDialog(panel)
        return panel

    def _combo(self, name, items):
        c = QtWidgets.QComboBox()
        c.setObjectName(name)
        c.addItems(list(items))
        return c

    def delete_current(self):
        from . import asmloads
        row = self.list.currentRow()
        ms = motors(self.sim)
        ls = asmloads.loads(self.sim)
        if len(ms) <= row < len(ms) + len(ls):
            doc = self.asm.Document
            doc.openTransaction("Delete")
            try:
                asmloads.remove_load(self.sim, ls[row - len(ms)]["name"])
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            self.frames, self.own = 0, None
            self.refresh()
            return
        if 0 <= row < len(ms):
            doc = self.asm.Document
            doc.openTransaction("Delete motor")
            try:
                remove_motor(self.sim, ms[row])
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            self.refresh()

    def refresh(self):
        from . import asmloads
        self.list.clear()
        for m in motors(self.sim):
            self.list.addItem(m.Label)
        for r in asmloads.loads(self.sim):
            self.list.addItem(r["name"])
        if hasattr(self, "timeline"):
            # a new motor (spring, force) is a new MotionManager tree row: the pane grows to show
            # it (it stayed below the pane's bottom edge, out of reach of a click and Delete)
            t = self.timeline
            t.setMinimumHeight(t.TOP + t.ROW * max(3, min(12, len(t.rows()))))
            t.update()
        asmloads.watch_springs()
        asmloads.draw_springs(self.asm, self.sim)     # the study's springs drawn as coils

    def _edit_motor(self, item):
        from . import asmloads
        row = self.list.row(item)
        ms = motors(self.sim)
        ls = asmloads.loads(self.sim)
        if 0 <= row < len(ms):
            open_motor(self.asm, self.sim, ms[row])
        elif row < len(ms) + len(ls):
            asmloads.edit(self.asm, self.sim, ls[row - len(ms)]["name"])

    def _iconify(self):
        ""

        try:
            from . import icons
        except Exception:
            icons = None
        for name, (family, std) in _TOOL_ICONS.items():
            b = self.findChild(QtWidgets.QToolButton, name)
            if b is None:
                continue
            icon = icons.family(family) if icons is not None else QtGui.QIcon()
            if icon.isNull():
                from . import simicons
                drawn = simicons.svg(family)
                icon = QtGui.QIcon(drawn) if drawn else icon
            if icon.isNull() and std is not None:
                icon = self.style().standardIcon(std)
            if icon.isNull():
                continue
            b.setIcon(icon)
            b.setToolTip(b.text())
            b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
            b.setAutoRaise(True)

    def calculate(self):
        self.stop()
        if study_type(self.sim) != STUDY_TYPES[0]:
            self.sim.bTimeEnd = self.duration.value()
            self.sim.jFramesPerSecond = self.fps.value()
            self.sim.cTimeStepOutput = 1.0 / self.fps.value()
            for m in motors(self.sim):
                v = motor_values(m)
                if v:
                    m.Formula = formula(v, float(self.sim.bTimeEnd), int(self.sim.jFramesPerSecond))
            for c in ac.components(self.asm):      # every calculation starts from time 0
                if c.Name in self.start and c.Placement != self.start[c.Name]:
                    c.Placement = self.start[c.Name]
            self.own = physics(self.asm, self.sim)
            # kept for the Animation Wizard's Import motion from Basic Motion / Motion Analysis
            CALCULATED[(self.asm.Document.Name, self.sim.Name, study_type(self.sim))] = (
                list(self.own[0]), float(self.sim.bTimeEnd), int(self.sim.jFramesPerSecond))
            if not self.own[1]:
                self.status.setText("Nothing moves: no component turns or slides on a mate to a fixed one.")
            elif gravity(self.sim) is None and not motors(self.sim) and not __import__(
                    "swstyle.asmloads", fromlist=["loads"]).loads(self.sim):
                self.status.setText("Nothing moves yet: add Gravity, a Motor, a Spring or a Force.")
            else:
                self.status.setText("")
            self.frames = len(self.own[0]) + 1
            self.slider.setRange(1, max(1, self.frames - 1))
            if study_type(self.sim) == STUDY_TYPES[2]:
                # Motion Study Properties > Motion Analysis: Animate during simulation, Replay speed
                from . import asmtimeline as tl
                o = tl.study_options(self.sim)
                if o.get("ma_animate"):
                    for i in range(1, self.frames, max(1, self.frames // 60)):
                        self.slider.setValue(i)
                        self.show_frame(i)
                        QtWidgets.QApplication.processEvents()
                rep = tl.REPLAY_SPEEDS[int(o.get("ma_replay", 1))]
                self.speed.setCurrentText("1x" if rep == "Real time" else rep)
            self.slider.setValue(max(1, self.frames - 1))
            self.show_frame(self.slider.value())
            return self.frames
        fc_before = self.own is None and self.frames > 0
        if self.own is not None and isinstance(self.own[1], dict) and self.own[1].get("motor"):
            fc_before = True        # last time motors and keys together: back to time 0 the same way
            for c in ac.components(self.asm):
                if c.Name in self.start and c.Placement != self.start[c.Name]:
                    c.Placement = self.start[c.Name]
        self.own = None
        from . import asmtimeline as tl
        if not motors(self.sim) and tl.has_motion(self.sim):
            # an animation of key points (moved components, the Animation Wizard)
            self.sim.bTimeEnd = self.duration.value()
            self.sim.jFramesPerSecond = self.fps.value()
            self.sim.cTimeStepOutput = 1.0 / self.fps.value()
            fr, views = tl.frames(self.asm, self.sim, self.duration.value(), self.fps.value())
            self.camera.capture() if not tl.data(self.sim)["view"] else None
            self.own = (fr, {"keyed": True, "views": views})
            self.status.setText("")
            self.frames = len(fr) + 1
            self.slider.setRange(1, max(1, self.frames - 1))
            self.slider.setValue(max(1, self.frames - 1))
            self.show_frame(self.slider.value())
            return self.frames
        if not motors(self.sim):
            self.status.setText("Nothing moves yet: add a Motor on a component's round face, or move a component "
                                "with the time bar away from 0 (Autokey).")
            return 0
        self.status.setText("")
        if fc_before and self._shown_now():

            # was moved since (that is the new start)
            try:
                self.asm.updateForFrame(0)
            except Exception as _fw_err:
                _fw_log("asmmotion.py:975", _fw_err)
            for c in ac.components(self.asm):
                if c.Name in self.start and c.Placement != self.start[c.Name]:
                    c.Placement = self.start[c.Name]
        self.frames = calculate(self.asm, self.sim, self.duration.value(), self.fps.value())
        if self.frames > 0 and tl.has_motion(self.sim):
            self._with_keys(tl)          # motors and key points together (a motor, then the Animation Wizard's explode)
        self.slider.setRange(1, max(1, self.frames - 1))     # FreeCAD's frame 0 repeats the start
        self.slider.setValue(max(1, self.frames - 1))
        self.show_frame(self.slider.value())
        return self.frames

    def _with_keys(self, tl):
        ""


        doc = self.asm.Document
        d = tl.live_data(self.sim)
        keyed = [n for n, rows in d.get("comps", {}).items()
                 if rows and len({repr(r[1:]) for r in rows}) > 1]
        # the Animation Wizard's Rotate model, view keys and hide/show or colour keys play with the motors too
        turned = bool(d.get("view")) or len(d.get("cams", [])) > 1 or \
            any(len(rows) > 1 for rows in d.get("look", {}).values())
        if not keyed and not turned:
            return
        fps = float(self.fps.value())
        keys, views = tl.frames(self.asm, self.sim, self.duration.value(), self.fps.value())
        held = HELD.get((doc.Name, self.sim.Name))
        start = {c.Name: App.Placement(c.Placement) for c in ac.components(self.asm)}
        out = []
        for k in range(len(keys)):
            frame = {}
            if held:
                frame.update(held[min(len(held) - 1, k + 1)])
            else:
                try:
                    self.asm.updateForFrame(k + 1)
                except Exception as _fw_err:
                    _fw_log("asmmotion.py:1010", _fw_err)
                frame.update({c.Name: App.Placement(c.Placement) for c in ac.components(self.asm)})
            for n in keyed:
                if keys[k].get(n) is not None:
                    frame[n] = keys[k][n]
            out.append(frame)
        for c in ac.components(self.asm):
            if c.Name in start:
                c.Placement = start[c.Name]
        self.own = (out, {"keyed": True, "views": views, "motor": True})
        self.frames = len(out) + 1

    def _view_at(self, axis, deg, t):
        """The view at t: the Orientation and Camera Views keys, then the Animation Wizard's Rotate model
        turn on top of them (asmpkg360: a view key used to undo the wizard's turn, its start row too)."""
        from . import asmtimeline as tl
        keyed = tl.apply_view_keys(self.sim, t)
        if axis is None:
            return
        if keyed:
            cam = tl._Camera()
            cam.capture()
            cam.turn(tl.model_centre(self.asm), axis, deg)
        else:
            self.camera.turn(tl.model_centre(self.asm), axis, deg)

    def show_frame(self, i):
        if self.frames <= 0:
            self.time.setText("0.00 sec")
            return
        if self.own is not None and isinstance(self.own[1], dict) and self.own[1].get("keyed"):
            from . import asmtimeline as tl
            k = min(len(self.own[0]) - 1, max(0, int(i) - 1))
            was = self._applying
            self._applying = True
            try:
                doc = self.asm.Document
                for name, plc in self.own[0][k].items():
                    obj = doc.getObject(name)
                    if obj is not None and plc is not None:
                        obj.Placement = plc
                axis, deg = self.own[1]["views"][k]
                tl.apply_looks(self.asm, self.sim, k * float(self.sim.cTimeStepOutput))
                self._view_at(axis, deg, k * float(self.sim.cTimeStepOutput))
                self.last_cam = tl.camera_now()
            finally:
                self._applying = was        # still the study moving them while the view updates below
            self.timeline.time = k * float(self.sim.cTimeStepOutput)
            self.timeline.update()
        elif self.own is not None:
            frame = self.own[0][min(len(self.own[0]) - 1, max(0, int(i) - 1))]
            for c in ac.components(self.asm):
                if c.Name in frame:
                    c.Placement = frame[c.Name]
        else:
            held = HELD.get((self.asm.Document.Name, self.sim.Name))
            if held:
                frame = held[min(len(held) - 1, max(0, int(i)))]
                for c in ac.components(self.asm):
                    if c.Name in frame and c.Placement != frame[c.Name]:
                        c.Placement = frame[c.Name]
            else:
                try:
                    self.asm.updateForFrame(int(i))
                except Exception:
                    return
            self._shown = self._placements()
        t = max(0, int(i) - 1) * float(self.sim.cTimeStepOutput)
        if abs(float(getattr(self.timeline, "time", 0.0)) - t) > 1e-9:
            self.timeline.time = t          # the timeline's time bar follows the slider: Autokey keys there
            self.timeline.update()
        self.time.setText("%.2f sec" % t)
        try:
            Gui.updateGui()
        except Exception as _fw_err:
            _fw_log("asmmotion.py:1069", _fw_err)

    def _placements(self):
        return {c.Name: tuple(c.Placement.toMatrix().A) for c in ac.components(self.asm)}

    def _shown_now(self):
        """True when the components are where the last shown frame put them (nobody moved one since)."""
        shown = getattr(self, "_shown", None)
        if not shown:
            return False
        now = self._placements()
        return now.keys() == shown.keys() and all(
            max(abs(a - b) for a, b in zip(now[k], shown[k])) < 1e-7 for k in now)

    def _interval(self):
        speed = float(self.speed.currentText().rstrip("x"))
        return max(1, int(1000.0 / max(1, self.fps.value()) / speed))

    def play_from_start(self):
        if self.frames <= 0 and not self.calculate():
            return
        self.slider.setValue(self.slider.minimum())
        self.play()

    def play(self):
        if self.frames <= 0 and not self.calculate():
            return
        if self.slider.value() >= self.slider.maximum():
            self.slider.setValue(self.slider.minimum())
        self.direction = 1
        self.timer.start(self._interval())

    def stop(self):
        self.timer.stop()

    def _tick(self):
        i = self.slider.value() + self.direction
        first, last = self.slider.minimum(), self.slider.maximum()
        mode = self.mode.currentIndex()
        if i > last or i < first:
            if mode == 0:
                self.stop()
                return
            if mode == 1:
                i = first
            else:
                self.direction = -self.direction
                i = self.slider.value() + self.direction
        self.slider.setValue(i)


_KEYWATCH = {"pane": None}


def _quiet(method):
    """The study moving components (Calculate, a frame shown) is no hand move for Autokey."""
    def wrapped(self, *a, **k):
        was = self._applying
        self._applying = True
        try:
            return method(self, *a, **k)
        finally:
            self._applying = was
    wrapped.__name__ = method.__name__
    return wrapped


MotionPane.calculate = _quiet(MotionPane.calculate)
MotionPane.show_frame = _quiet(MotionPane.show_frame)


def close_pane_of(doc=None, obj=None):
    ""

    dock = PANE["dock"]
    p = dock.widget() if dock is not None else None
    if p is None:
        return False
    try:
        mine = (obj is not None and obj is p.sim) or (doc is not None and doc is p.asm.Document)
    except (RuntimeError, ReferenceError):
        mine = True
    if not mine:
        return False
    try:
        p.cam_watch.stop()
        p.timer.stop()
    except Exception as _fw_err:
        _fw_log("asmmotion.py:1157", _fw_err)
    if _KEYWATCH.get("pane") is p:
        _KEYWATCH["pane"] = None
    dock.hide()
    dock.setWidget(QtWidgets.QWidget())
    p.deleteLater()
    return True


class _KeyWatch:
    """Autokey: a component's Placement changed while a Motion Study pane is open."""

    def slotDeletedObject(self, obj):
        try:
            close_pane_of(obj=obj)
        except Exception as _fw_err:
            _fw_log("asmmotion.py:1173", _fw_err)

    def slotDeletedDocument(self, doc):
        try:
            close_pane_of(doc=doc)
        except Exception as _fw_err:
            _fw_log("asmmotion.py:1179", _fw_err)

    def slotChangedObject(self, obj, prop):
        if prop not in ("Placement", "Visibility", "Distance", "Angle"):
            return
        p = _KEYWATCH.get("pane")
        try:
            if p is None or not p.isVisible() or obj.Document is not p.asm.Document:
                return
            if p._applying or p.timer.isActive():
                return                          # the study itself moving it, not a hand move
        except ReferenceError:                  # the object or the pane's assembly is gone
            return
        except RuntimeError:
            _KEYWATCH["pane"] = None
            return
        name, dn = obj.Name, obj.Document.Name
        if prop in ("Distance", "Angle"):
            import time
            p._mate_until = time.monotonic() + 1.5   # the solve that follows moves parts: no position keys
        QtCore.QTimer.singleShot(0, lambda: _moved(p, dn, name, prop))


class _LookWatch:
    """Autokey for a colour or show/hide change: while the MotionManager pane is up, a timer
    compares each component's look. No Gui document observer: one with slotChangedObject makes
    FreeCAD's FEM mesh view providers fail ("Cannot add static property")."""

    def __init__(self):
        self.seen = {}
        self.timer = QtCore.QTimer()
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def resync(self, p):
        try:
            from . import asmtimeline as tl
            for obj in ac.components(p.asm):
                self.seen[(obj.Document.Name, obj.Name)] = repr(tl.look_of(obj))
        except Exception as _fw_err:
            _fw_log("asmmotion.py:1220", _fw_err)

    def tick(self):
        p = _KEYWATCH.get("pane")
        try:
            if p is None or not p.isVisible():
                self.seen.clear()
                return
            from . import asmtimeline as tl
            comps = ac.components(p.asm)
        except (RuntimeError, AttributeError, ReferenceError):
            self.seen.clear()
            return
        except Exception:
            return
        busy = p._applying or p.timer.isActive()
        for obj in comps:
            try:
                key = (obj.Document.Name, obj.Name)
                now = repr(tl.look_of(obj))
            except Exception:
                continue
            before = self.seen.get(key)
            self.seen[key] = now
            if before is not None and before != now and not busy:
                _moved(p, key[0], key[1], "look")


def _moved(p, dn, name, prop="Placement"):
    try:
        obj = App.getDocument(dn).getObject(name)
        if obj is None:
            return
        if prop in ("Distance", "Angle"):
            p.mate_changed(obj)
        elif prop == "Placement":
            p.moved(obj)
        else:
            p.look_changed(obj)
    except Exception as _fw_err:
        _fw_log("asmmotion.py:1260", _fw_err)


if not getattr(App, "_fw_keywatch", None):
    App._fw_keywatch = _KeyWatch()
    App.addDocumentObserver(App._fw_keywatch)
_old_watch = getattr(Gui, "_fw_lookwatch", None)
if _old_watch is not None and not isinstance(getattr(_old_watch, "timer", None), QtCore.QTimer):
    try:
        Gui.removeDocumentObserver(_old_watch)      # an earlier load's Gui observer
    except Exception as _fw_err:
        _fw_log("asmmotion.py:1271", _fw_err)
    _old_watch = None
if _old_watch is None:
    Gui._fw_lookwatch = _LookWatch()


def show_pane(asm, sim):
    mw = Gui.getMainWindow()
    dock = PANE["dock"]
    if dock is None:
        dock = QtWidgets.QDockWidget(mw)
        dock.setObjectName("FW_MotionManager")

        dock.setTitleBarWidget(QtWidgets.QWidget(dock))
        mw.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)
        PANE["dock"] = dock
    old = dock.widget()
    pane = MotionPane(asm, sim)
    dock.setWidget(pane)
    if old is not None:
        old.deleteLater()
    dock.setWindowTitle(sim.Label)
    dock.show()
    dock.raise_()
    return pane


def pane():
    dock = PANE["dock"]
    return dock.widget() if dock is not None and dock.isVisible() else None


# ---------------------------------------------------------------- the Motor PM
class _BoxFocus(QtCore.QObject):
    ""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, obj, event):
        try:
            if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
                self.panel.active = "direction" if obj is self.panel.dir_edit else \
                    "relative" if obj is getattr(self.panel, "rel_edit", None) else "location"
        except RuntimeError as _fw_err:
            _fw_log("asmmotion.py:1314", _fw_err)
        return False


class MotionGraph(QtWidgets.QWidget):
    ""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setObjectName("FW_MotorGraph")
        self.setMinimumHeight(90)
        self.setToolTip("The motion over the study: displacement against time")

    def samples(self, n=120):
        p = self.panel
        try:
            values = p.values()
            dur = p._study_time()
            if values.get("motion") in FUNCTION_MOTIONS:
                from . import asmfunction
                d = asmfunction.displacement(p.func or asmfunction.default(values["motion"], values["type"] == TYPES[0]), dur)
                return [(dur * i / n, d(dur * i / n)) for i in range(n + 1)]
            unit = 180.0 / math.pi if values.get("type", TYPES[0]) == TYPES[0] else 1.0
            return [(dur * i / n, _motor_at(values, dur * i / n, dur) * unit) for i in range(n + 1)]
        except Exception as _fw_err:
            _fw_log("asmmotion.py:graph", _fw_err)
            return []

    def paintEvent(self, _e):
        from PySide import QtGui
        pts = self.samples()
        q = QtGui.QPainter(self)
        q.setRenderHint(QtGui.QPainter.Antialiasing)
        r = self.rect().adjusted(6, 6, -6, -6)
        pal = self.palette()
        q.setPen(QtGui.QPen(pal.color(QtGui.QPalette.Mid), 1))
        q.drawRect(r)
        if len(pts) < 2:
            q.end()
            return
        ys = [y for _t, y in pts]
        lo, hi = min(ys + [0.0]), max(ys + [0.0])
        if hi - lo < 1e-12:
            hi, lo = lo + 1.0, lo - 1.0
        t1 = pts[-1][0] or 1.0
        X = lambda t: r.left() + r.width() * t / t1
        Y = lambda y: r.bottom() - r.height() * (y - lo) / (hi - lo)
        q.setPen(QtGui.QPen(pal.color(QtGui.QPalette.Mid), 1, QtCore.Qt.DotLine))
        q.drawLine(QtCore.QPointF(r.left(), Y(0.0)), QtCore.QPointF(r.right(), Y(0.0)))
        q.setPen(QtGui.QPen(QtGui.QColor("#1f6fd1"), 1.6))
        path = QtGui.QPainterPath(QtCore.QPointF(X(pts[0][0]), Y(pts[0][1])))
        for t, y in pts[1:]:
            path.lineTo(QtCore.QPointF(X(t), Y(y)))
        q.drawPath(path)
        q.end()


class MotorPanel:
    def __init__(self, asm, sim, motor=None):
        from . import asmpm
        self.asm, self.sim, self.motor, self.doc = asm, sim, motor, asm.Document
        values = motor_values(motor) if motor is not None else {}
        tbox, tlay = asmpm._box("Motor Type", "Motor", "MOTION_MOTOR")
        self.type = QtWidgets.QComboBox()
        self.type.setObjectName("FW_MotorType")
        self.type.addItems(list(TYPES))
        tlay.addWidget(self.type)
        from . import asmlook
        self.type_buttons = asmlook.type_buttons(self.type, tlay, {"Linear Motor (Actuator)": "Linear Motor"})
        cbox, clay = asmpm._box("Component/Direction")
        clay.addWidget(QtWidgets.QLabel("Motor Location:"))
        self.where = QtWidgets.QLineEdit()
        self.where.setObjectName("FW_MotorLocation")
        self.where.setReadOnly(True)
        self.where.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
        clay.addWidget(self.where)

        clay.addWidget(QtWidgets.QLabel("Motor Direction:"))
        self.dir_edit = QtWidgets.QLineEdit()
        self.dir_edit.setObjectName("FW_MotorDirection")
        self.dir_edit.setReadOnly(True)
        self.dir_edit.setPlaceholderText("Along the mate's axis")
        self.dir_edit.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
        clay.addWidget(self.dir_edit)
        self.direction = None
        self.active = "location"
        self._focus = _BoxFocus(self)
        self.where.installEventFilter(self._focus)
        self.dir_edit.installEventFilter(self._focus)

        self.reverse = asmpm.reverse_button("FW_MotorReverse")
        clay.removeWidget(self.dir_edit)
        drow = QtWidgets.QHBoxLayout()
        drow.setContentsMargins(0, 0, 0, 0)
        drow.addWidget(self.reverse)
        drow.addWidget(self.dir_edit, 1)
        clay.addLayout(drow)

        # mate it has; a component: the mate between the two)
        clay.addWidget(QtWidgets.QLabel("Component to move relative to:"))
        self.rel_edit = QtWidgets.QLineEdit()
        self.rel_edit.setObjectName("FW_MotorRelative")
        self.rel_edit.setReadOnly(True)
        self.rel_edit.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
        self.rel_edit.installEventFilter(self._focus)
        clay.addWidget(self.rel_edit)
        self.relative = None
        mbox, mlay = asmpm._box("Motion")
        self.motion = QtWidgets.QComboBox()
        self.motion.setObjectName("FW_MotorMotion")
        self.motion.addItems(list(MOTIONS))
        mlay.addWidget(self.motion)
        form = QtWidgets.QFormLayout()
        self.value = QtWidgets.QDoubleSpinBox()
        self.value.setObjectName("FW_MotorValue")
        self.value.setRange(-1.0e6, 1.0e6)
        self.value.setDecimals(3)
        self.freq = QtWidgets.QDoubleSpinBox()
        self.freq.setObjectName("FW_MotorFrequency")
        self.freq.setRange(0.001, 1000.0)
        self.freq.setDecimals(3)
        self.freq.setSuffix(" Hz")
        self.value_label = QtWidgets.QLabel("Speed:")
        self.freq_label = QtWidgets.QLabel("Frequency:")
        form.addRow(self.value_label, self.value)
        form.addRow(self.freq_label, self.freq)

        self.start = QtWidgets.QDoubleSpinBox()
        self.start.setObjectName("FW_MotorStart")
        self.start.setRange(0.0, 1.0e5)
        self.start.setDecimals(3)
        self.start.setSuffix(" s")
        self.span = QtWidgets.QDoubleSpinBox()
        self.span.setObjectName("FW_MotorDuration")
        self.span.setRange(0.001, 1.0e5)
        self.span.setDecimals(3)
        self.span.setSuffix(" s")
        self.phase = QtWidgets.QDoubleSpinBox()
        self.phase.setObjectName("FW_MotorPhase")
        self.phase.setRange(-360.0, 360.0)
        self.phase.setDecimals(2)
        self.phase.setSuffix(" deg")
        self.start_label, self.span_label = QtWidgets.QLabel("Start Time:"), QtWidgets.QLabel("Duration:")
        self.phase_label = QtWidgets.QLabel("Phase Shift:")
        form.addRow(self.start_label, self.start)
        form.addRow(self.span_label, self.span)
        form.addRow(self.phase_label, self.phase)
        mlay.addLayout(form)

        self.graph = MotionGraph(self)
        mlay.addWidget(self.graph)
        for w in (self.value, self.freq, self.start, self.span, self.phase):
            w.valueChanged.connect(lambda *_: self.graph.update())

        # the Function Builder again)
        self.func = None
        self.func_text = QtWidgets.QLabel("")
        self.func_text.setObjectName("FW_MotorFunctionText")
        self.func_text.setWordWrap(True)
        mlay.addWidget(self.func_text)
        self.func_edit = QtWidgets.QPushButton("Edit Function...")
        self.func_edit.setObjectName("FW_MotorFunction")
        self.func_edit.clicked.connect(self.edit_function)
        mlay.addWidget(self.func_edit)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("FW_MotorError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #d04040;")
        self.error.hide()
        mlay.addWidget(self.error)
        self.form = [tbox, cbox, mbox]
        self.comp = None
        self._defaults = {}
        self.type.currentIndexChanged.connect(lambda *_: self._units(True))
        self.motion.currentIndexChanged.connect(lambda *_: self._units(True))
        self.motion.activated.connect(self._motion_picked)
        if values:
            self.func = values.get("function")
            self.type.setCurrentText(values.get("type", TYPES[0]))
            self.motion.setCurrentText(values.get("motion", MOTIONS[0]))
            self.reverse.setChecked(bool(values.get("reverse")))
            self.comp = next((c for c in ac.components(asm) if c.Name == values.get("component")), None)
            if self.comp is not None:
                self.where.setText(values.get("location") or self.comp.Label)
            if values.get("direction"):
                self.direction = App.Vector(*values["direction"])
                self.dir_edit.setText(values.get("direction_label") or "Direction")
            self.relative = _relative(asm, values)
            if self.relative is not None:
                self.rel_edit.setText(self.relative.Label)
        self._units(not values)
        if values:
            key = {"Constant Speed": "speed", "Distance": "distance"}.get(self.motion.currentText(), "amplitude")
            self.value.setValue(values.get(key, self.value.value()))
            self.freq.setValue(values.get("frequency", 1.0))
            self.start.setValue(values.get("start", 0.0))
            self.span.setValue(values.get("duration") or max(self._study_time() - values.get("start", 0.0), 0.001))
            self.phase.setValue(values.get("phase", 0.0))
        Gui.Selection.addObserver(self, 0)

    def _units(self, reset):
        rotary = self.type.currentIndex() == 0
        motion = self.motion.currentText()
        if motion == "Constant Speed":
            self.value_label.setText("Speed:")
            self.value.setSuffix(" RPM" if rotary else " mm/s")
            default = 100.0 if rotary else 10.0
        elif motion == "Distance":
            self.value_label.setText("Displacement:")
            self.value.setSuffix(" deg" if rotary else " mm")
            default = 90.0 if rotary else 10.0
        else:
            self.value_label.setText("Amplitude:")
            self.value.setSuffix(" deg" if rotary else " mm")
            default = 30.0 if rotary else 10.0
        osc = motion == "Oscillating"
        self.freq.setVisible(osc)
        self.freq_label.setVisible(osc)
        self.phase.setVisible(osc)
        self.phase_label.setVisible(osc)
        dist = motion == "Distance"
        for w in (self.start, self.span, self.start_label, self.span_label):
            w.setVisible(dist)
        fn = motion in FUNCTION_MOTIONS
        self.value.setVisible(not fn)
        self.value_label.setVisible(not fn)
        self.func_text.setVisible(fn)
        self.func_edit.setVisible(fn)
        if fn:
            from . import asmfunction
            if not self.func or self.func.get("kind") != motion:
                self.func = asmfunction.default(motion, rotary)
            self.func_text.setText(asmfunction.summary(self.func))
        if reset:
            self.value.setValue(default)
            self.freq.setValue(1.0)
            self.start.setValue(0.0)
            self.span.setValue(self._study_time())
            self.phase.setValue(0.0)
        self.graph.update()

    def _study_time(self):
        try:
            return float(self.sim.bTimeEnd)
        except Exception:
            return 5.0

    def _motion_picked(self, i):
        ""
        if self.motion.itemText(i) in FUNCTION_MOTIONS:
            from . import safe_later as _sl; _sl.later(0, self.edit_function, self, "motion")

    def edit_function(self, modal=True):
        from . import asmfunction
        motion = self.motion.currentText()
        if motion not in FUNCTION_MOTIONS:
            return None
        rotary = self.type.currentIndex() == 0
        func = self.func if self.func and self.func.get("kind") == motion else asmfunction.default(motion, rotary)
        out = asmfunction.edit(func, rotary, float(self.sim.bTimeEnd), modal)
        if not modal:
            out.accepted.connect(lambda: self._function_set(out.func))
            return out
        if out is not None:
            self._function_set(out)
        return out

    def _function_set(self, func):
        from . import asmfunction
        self.func = func
        self.func_text.setText(asmfunction.summary(func))

    def addSelection(self, doc, obj, sub, pnt):
        self.doc.Name      # its document closed: this raises here and selguard drops the observer
        from . import safe_later as _sl; _sl.later(0, lambda: selguard.quiet(lambda: self._pick(self.doc.getObject(obj), sub)), self, "where")

    def removeSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def setPreselection(self, *args):
        pass

    def _pick_direction(self, root, sub):
        try:
            shape = root.getSubObject(sub)
        except Exception as _fw_err:
            _fw_log("asmmotion.py:1505", _fw_err)
            return False
        d = None
        try:
            kind = shape.Surface.TypeId if shape.ShapeType == "Face" else shape.Curve.TypeId
            if shape.ShapeType == "Face" and kind == "Part::GeomPlane":
                u0, u1, v0, v1 = shape.ParameterRange
                d = shape.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
            elif shape.ShapeType == "Face" and kind in ("Part::GeomCylinder", "Part::GeomCone"):
                d = shape.Surface.Axis
            elif shape.ShapeType == "Edge" and kind == "Part::GeomLine":
                d = shape.Vertexes[-1].Point - shape.Vertexes[0].Point
            elif shape.ShapeType == "Edge" and kind == "Part::GeomCircle":
                d = shape.Curve.Axis
        except Exception:
            d = None
        if d is None or d.Length < 1e-12:
            return False
        self.direction = App.Vector(d).normalize()
        ref = ac.reference(self.asm, root, sub)
        self.dir_edit.setText("%s@%s" % (sub.split(".")[-1], ref[0].Label if ref else root.Label))
        self.active = "location"
        return True

    def _pick(self, root, sub):
        if root is None or not sub or getattr(self, "closed", False):
            return
        if self.active == "direction":
            if self._pick_direction(root, sub):
                return
        ref = ac.reference(self.asm, root, sub)
        if ref is None:
            return
        if self.active == "relative":
            self.relative = ref[0] if ref[0] is not self.comp else None
            self.rel_edit.setText(self.relative.Label if self.relative is not None else "")
            self.active = "location"
            return
        self.comp = ref[0]
        self.where.setText("%s@%s" % (ref[1].split(".")[-1], ref[0].Label))
        self.error.hide()

    def values(self):
        motion = self.motion.currentText()
        out = {"type": self.type.currentText(), "motion": motion, "reverse": self.reverse.isChecked(),
               "component": self.comp.Name if self.comp is not None else "", "location": self.where.text()}
        if self.direction is not None:
            out["direction"] = [self.direction.x, self.direction.y, self.direction.z]
            out["direction_label"] = self.dir_edit.text()
        if self.relative is not None:
            out["relative"] = self.relative.Name
        key = {"Constant Speed": "speed", "Distance": "distance"}.get(motion, "amplitude")
        if motion in FUNCTION_MOTIONS:
            out["function"] = self.func
            return out
        out[key] = self.value.value()
        if motion == "Oscillating":
            out["frequency"] = self.freq.value()
            out["phase"] = self.phase.value()
        if motion == "Distance":
            out["start"] = self.start.value()
            out["duration"] = self.span.value()
        return out

    def _close(self):
        self.closed = True
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmmotion.py:1547", _fw_err)

    def accept(self):
        if self.comp is None:
            self.error.setText("Pick where the motor goes: a round face or an edge of a component.")
            self.error.show()
            return False
        values = self.values()
        rotary = values["type"] == TYPES[0]
        if joint_for(self.asm, self.comp, rotary, self.relative) is None:
            if self.relative is not None:
                self.error.setText("%s has no mate with %s it can %s on." % (self.comp.Label, self.relative.Label,
                                                                            "turn" if rotary else "slide"))
            else:
                self.error.setText("%s has no mate it can %s on: add a Concentric or Hinge mate first."
                                   % (self.comp.Label, "turn" if rotary else "slide"))
            self.error.show()
            return False
        self._close()
        self.doc.openTransaction("Motor")
        try:
            add_motor(self.asm, self.sim, values, self.motor)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        p = pane()
        if p is not None:
            p.refresh()
        return True

    def reject(self):
        self._close()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


OPEN = []
RESULTS = []


class GravityPanel:
    ""

    def __init__(self, asm, sim):
        from . import asmpm
        self.asm, self.sim, self.doc = asm, sim, asm.Document
        box, lay = asmpm._box("Gravity Parameters", "Gravity", "MOTION_GRAVITY")
        row = QtWidgets.QHBoxLayout()
        self.axes = {}
        for name in ("X", "Y", "Z"):
            r = QtWidgets.QRadioButton(name)
            r.setObjectName("FW_Gravity" + name)
            row.addWidget(r)
            self.axes[name] = r
        lay.addLayout(row)

        self.ref_dir = None
        self.ref = QtWidgets.QLineEdit()
        self.ref.setObjectName("FW_GravityReference")
        self.ref.setReadOnly(True)
        self.ref.setPlaceholderText("Direction Reference (face or edge)")
        self.ref.setToolTip("Direction Reference: pick a flat face or a straight edge. Pick X, Y or Z to go back to an axis.")
        self.ref.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
        lay.addWidget(self.ref)
        for r in self.axes.values():
            r.clicked.connect(lambda *_a: self._clear_ref())
        self.reverse = QtWidgets.QCheckBox("Reverse Direction")
        from . import pmvalues
        self.reverse.setIcon(pmvalues.reverse_icon())
        self.reverse.setObjectName("FW_GravityReverse")
        lay.addWidget(self.reverse)
        form = QtWidgets.QFormLayout()
        self.value = QtWidgets.QDoubleSpinBox()
        self.value.setObjectName("FW_GravityValue")
        self.value.setRange(0.0, 1.0e9)
        self.value.setDecimals(2)
        self.value.setSuffix(" mm/s^2")
        form.addRow("Numeric gravity value:", self.value)
        lay.addLayout(form)
        self.form = [box]
        g = gravity(sim)
        if g is None:
            self.axes["Y"].setChecked(True)
            self.value.setValue(9806.65)
        else:
            d, v = g
            name = max(("X", "Y", "Z"), key=lambda n: abs(getattr(d, n.lower())))
            self.axes[name].setChecked(True)
            self.value.setValue(v)
            if d.Length > 1e-12 and abs(abs(getattr(d, name.lower())) - d.Length) > 1e-9 * d.Length:
                self.ref_dir = App.Vector(d).normalize()      # a direction from a reference: kept as it is
                self.ref.setText("Direction (%.3g, %.3g, %.3g)" % (d.x, d.y, d.z))
            else:
                self.reverse.setChecked(getattr(d, name.lower()) > 0)
        Gui.Selection.addObserver(self, 0)

    def _clear_ref(self):
        self.ref_dir = None
        self.ref.clear()

    def addSelection(self, doc, obj, sub, pnt=None, *args):
        """A flat face or a straight edge picked: its direction is gravity's."""
        try:
            top = App.getDocument(doc).getObject(obj)
            shape = top.getSubObject(sub) if sub else None
        except Exception:
            return
        if shape is None or shape.isNull():
            return
        d = None
        try:
            if shape.ShapeType == "Face" and shape.Surface.TypeId == "Part::GeomPlane":
                u0, u1, v0, v1 = shape.ParameterRange
                d = shape.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
            elif shape.ShapeType == "Edge" and shape.Curve.TypeId == "Part::GeomLine":
                d = shape.Vertexes[-1].Point - shape.Vertexes[0].Point
        except Exception:
            d = None
        if d is None or d.Length < 1e-12:
            return
        self.ref_dir = App.Vector(d).normalize()
        for r in self.axes.values():        # the reference wins; picking an axis again clears it
            r.setAutoExclusive(False)
            r.setChecked(False)
            r.setAutoExclusive(True)
        parts = sub.split(".")
        owner = App.getDocument(doc).getObject(parts[-2]) if len(parts) > 1 else None
        self.ref.setText("%s@%s" % (parts[-1], (owner or top).Label))

    def _end(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmmotion.py:1677", _fw_err)

    def direction(self):
        if self.ref_dir is not None:
            return self.ref_dir * -1 if self.reverse.isChecked() else App.Vector(self.ref_dir)
        name = next((n for n, r in self.axes.items() if r.isChecked()), "Y")
        d = App.Vector(*(1.0 if n == name else 0.0 for n in ("X", "Y", "Z")))
        return d if self.reverse.isChecked() else d * -1

    def accept(self):
        self.doc.openTransaction("Gravity")
        try:
            set_gravity(self.sim, self.direction(), self.value.value())
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise
        self.doc.commitTransaction()
        self._end()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._end()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def open_gravity(asm, sim):
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    panel = GravityPanel(asm, sim)
    OPEN[:] = [panel]
    Gui.Control.showDialog(panel)
    return panel


CATEGORIES = ("Displacement/Velocity/Acceleration",)
SUBS = ("Angular Displacement", "Angular Velocity", "Angular Acceleration",
        "Linear Displacement", "Linear Velocity", "Linear Acceleration")


class _Chart(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("FW_ResultsChart")
        self.setMinimumSize(420, 240)
        self.points, self.ylabel = [], ""

    def paintEvent(self, _e):
        from PySide import QtGui
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(255, 255, 255))
        m = 48
        w, h = self.width() - m - 12, self.height() - m - 12
        p.setPen(QtGui.QColor(60, 60, 60))
        p.drawRect(m, 12, w, h)
        p.drawText(m, self.height() - 8, "Time (sec)")
        p.drawText(4, 10, self.ylabel)
        if len(self.points) > 1:
            xs = [a for a, _b in self.points]
            ys = [b for _a, b in self.points]
            x0, x1 = min(xs), max(xs) or 1.0
            y0, y1 = min(ys), max(ys)
            if abs(y1 - y0) < 1e-12:
                y0, y1 = y0 - 1, y1 + 1
            p.drawText(4, 24, "%.4g" % y1)
            p.drawText(4, 12 + h, "%.4g" % y0)
            p.drawText(m + w - 30, self.height() - 22, "%.2f" % x1)
            p.setPen(QtGui.QPen(QtGui.QColor(30, 90, 200), 2))
            pts = [QtCore.QPointF(m + (x - x0) / (x1 - x0 or 1) * w, 12 + h - (y - y0) / (y1 - y0) * h)
                   for x, y in self.points]
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
        p.end()


PLOTS = []


class ResultsPanel:
    ""



    def __init__(self, pane):
        from . import asmpm
        self.pane = pane
        self.closed = False
        rbox, rlay = asmpm._box("Results")
        rbox.setObjectName("FW_ResultsPM")
        self.category = QtWidgets.QComboBox()
        self.category.setObjectName("FW_ResultsCategory")
        self.category.addItems(list(CATEGORIES))
        rlay.addWidget(self.category)
        self.sub = QtWidgets.QComboBox()
        self.sub.setObjectName("FW_ResultsSub")
        rlay.addWidget(self.sub)
        rlay.addWidget(QtWidgets.QLabel("Component:"))
        self.comp = QtWidgets.QComboBox()       # a pick in the graphics area chooses it too
        self.comp.setObjectName("FW_ResultsComponent")
        self.comp.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QComboBox"))
        rlay.addWidget(self.comp)
        pbox, play = asmpm._box("Plot Results")
        self.against = QtWidgets.QComboBox()
        self.against.setObjectName("FW_ResultsAgainst")
        self.against.addItem("Plot results vs: Time")
        play.addWidget(self.against)
        self.form = [rbox, pbox]
        results = pane.own[1] if pane.own else {}
        comps = {c.Name: c for c in ac.components(pane.asm)}
        for name in results:
            self.comp.addItem(comps[name].Label if name in comps else name, name)
        self.comp.currentIndexChanged.connect(lambda *_: self._subs())
        self._subs()
        Gui.Selection.addObserver(self, 0)

    def _subs(self):
        results = self.pane.own[1] if self.pane.own else {}
        r = results.get(self.comp.currentData(), {})
        turn = r.get("kind", "turn") == "turn"
        keep = self.sub.currentText()
        self.sub.clear()
        self.sub.addItems([s for s in SUBS if s.startswith("Angular") == turn])
        if self.sub.findText(keep) >= 0:
            self.sub.setCurrentText(keep)

    def series(self):
        return _series(self.pane, self.comp.currentData(), self.sub.currentText())

    def addSelection(self, doc, obj, sub, pnt):
        from . import safe_later as _sl; _sl.later(0, lambda: self._pick(doc, obj, sub), self, "comp")

    def _pick(self, doc, obj, sub):
        if self.closed:
            return
        try:
            root = App.getDocument(doc).getObject(obj)
            ref = ac.reference(self.pane.asm, root, sub) if sub else None
            comp = ref[0] if ref else root
            k = self.comp.findData(comp.Name)
            if k >= 0:
                self.comp.setCurrentIndex(k)
        except Exception as _fw_err:
            _fw_log("asmmotion.py:ResultsPanel._pick", _fw_err)

    def removeSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def setPreselection(self, *args):
        pass

    def _close(self):
        self.closed = True
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmmotion.py:ResultsPanel._close", _fw_err)

    def plot(self):
        """The plot of what is chosen, in a new window (Plot1, Plot2...)."""
        PLOTS[:] = [w for w in PLOTS if _alive(w)]
        win = ResultsDialog(self.pane, self.comp.currentData(), self.sub.currentText(), len(PLOTS) + 1)
        win.show()
        PLOTS.append(win)
        return win

    def accept(self):
        if self.comp.currentData() is None:
            return False
        self.plot()
        self._close()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._close()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def _alive(w):
    try:
        w.isVisible()
        return True
    except RuntimeError:
        return False


def _series(pane, name, text):
    results = pane.own[1] if pane.own else {}
    r = results.get(name)
    if not r:
        return []
    key = "x" if "Displacement" in text else "v" if "Velocity" in text else "a"
    k = 180.0 / math.pi if text.startswith("Angular") else 1.0     # deg, deg/sec, deg/sec^2
    return [(t, y * k) for t, y in zip(r["t"], r[key])]


class ResultsDialog(QtWidgets.QDialog):
    ""


    def __init__(self, pane, name, text, number=1):
        super().__init__(Gui.getMainWindow())
        self.pane, self.name, self.number = pane, name, number
        self.setObjectName("FW_ResultsDialog")
        lay = QtWidgets.QVBoxLayout(self)
        self.sub = QtWidgets.QComboBox()
        self.sub.setObjectName("FW_ResultsSub")
        results = pane.own[1] if pane.own else {}
        turn = results.get(name, {}).get("kind", "turn") == "turn"
        self.sub.addItems([s for s in SUBS if s.startswith("Angular") == turn])
        self.sub.setCurrentText(text)
        lay.addWidget(self.sub)
        self.chart = _Chart()
        lay.addWidget(self.chart, 1)
        self.resize(560, 380)
        self.sub.currentIndexChanged.connect(lambda *_: self.plot())
        self.plot()

    def series(self):
        return _series(self.pane, self.name, self.sub.currentText())

    def plot(self):
        text = self.sub.currentText()
        unit = {"Angular Displacement": "deg", "Angular Velocity": "deg/sec", "Angular Acceleration": "deg/sec^2",
                "Linear Displacement": "mm", "Linear Velocity": "mm/sec", "Linear Acceleration": "mm/sec^2"}.get(text, "")
        self.chart.points = self.series()
        self.chart.ylabel = "%s (%s)" % (text, unit)
        self.setWindowTitle("Plot%d: %s" % (self.number, text))
        self.chart.update()


def open_motor(asm, sim, motor=None):
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    panel = MotorPanel(asm, sim, motor)
    OPEN[:] = [panel]
    Gui.Control.showDialog(panel)
    picks = []
    try:
        picks = [(s.Object, sub) for s in Gui.Selection.getSelectionEx("", 0) for sub in s.SubElementNames]
    except Exception as _fw_err:
        _fw_log("asmmotion.py:1822", _fw_err)
    for obj, sub in picks:      # pick first, Motor second
        panel._pick(obj, sub)
    return panel


# ---------------------------------------------------------------- commands
def _assembly():
    try:
        from . import asmtools
        return asmtools._assembly()
    except Exception as _fw_err:
        _fw_log("asmmotion.py:1864", _fw_err)
        return None


def _tell(title, text):
    try:
        from . import asmtools
        asmtools._tell(title, text)
    except Exception:
        App.Console.PrintMessage(text + "\n")


class NewMotionStudyCommand:
    def GetResources(self):
        return {"MenuText": "New Motion Study", "Pixmap": "Assembly_CreateSimulation",
                "ToolTip": "Adds a motion study."}

    def Activated(self, *args):
        asm = _assembly()
        if asm is None:
            return
        doc = asm.Document
        doc.openTransaction("New Motion Study")
        try:
            sim = new_study(asm)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        doc.recompute()
        show_pane(asm, sim)

    def IsActive(self):
        return _assembly() is not None


class MotorCommand:
    def GetResources(self):
        return {"MenuText": "Motor", "Pixmap": "button_rotate",
                "ToolTip": "Adds a rotating or sliding motor to the motion study."}

    def Activated(self, *args):
        asm = _assembly()
        p = pane()
        if asm is None:
            return
        sim = p.sim if p is not None else (studies(asm) or [None])[-1]
        if sim is None:
            doc = asm.Document
            doc.openTransaction("New Motion Study")
            try:
                sim = new_study(asm)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            show_pane(asm, sim)
        open_motor(asm, sim)

    def IsActive(self):
        return _assembly() is not None


COMMANDS = [("SWStyle_NewMotionStudy", NewMotionStudyCommand()), ("SWStyle_MotionMotor", MotorCommand())]


def register():
    for name, cmd in COMMANDS:
        try:
            Gui.addCommand(name, cmd)
        except Exception as _fw_err:
            _fw_log("asmmotion.py:1896", _fw_err)
