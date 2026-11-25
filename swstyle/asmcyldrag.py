# SPDX-License-Identifier: LGPL-2.1-or-later
""











import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

V = App.Vector
STATE = {"filtered": set(), "drag": None, "why": ""}
CLICK = 4           # pixels: less is a click (a pick), not a drag
STEP_MS = 25        # at most one solve per this many ms while dragging


def _ac():
    from . import asmcore
    return asmcore


def _active_assembly():
    try:
        import UtilsAssembly
        asm = UtilsAssembly.activeAssembly()
        if asm is not None:
            return asm
    except Exception:
        pass
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        obj = getattr(edit, "Object", None)
        if obj is not None and obj.TypeId == "Assembly::AssemblyObject":
            return obj
    except Exception:
        pass
    return None


def _joints_on(asm, comp):
    """(the joints that hold comp, the other mate rows on it)."""
    ac = _ac()
    joints, rows = [], []
    for j in ac.joint_group(asm).Group:
        if getattr(j, "Suppressed", False) or hasattr(j, "ObjectToGround"):
            continue
        refs = [getattr(j, p, None) for p in ("Reference1", "Reference2")]
        if not any(r and r[0] is comp for r in refs):
            continue
        (joints if hasattr(j, "JointType") else rows).append(j)
    return joints, rows


def candidate(asm, comp):
    """The Cylindrical joint when comp is held by it alone (range mates allowed), else None."""
    ac = _ac()
    if comp is None or comp.TypeId != "App::Link" or comp in ac.grounded(asm):
        return None
    joints, rows = _joints_on(asm, comp)
    if len(joints) != 1 or getattr(joints[0], "JointType", "") != "Cylindrical":
        return None
    if any(getattr(r, ac.MATE_PROP, "") not in ac.LIMITS for r in rows):
        return None         # a Path, Cam or Width row drives it as well: FreeCAD's drag
    return joints[0]


def axis_of(asm, comp, joint):
    """(origin, unit direction) of the joint's axis, in the assembly's space."""
    side = "2" if getattr(joint, "Reference2", None) and joint.Reference2[0] is comp else "1"
    frame = asm.Placement.multiply(comp.Placement).multiply(getattr(joint, "Placement" + side))
    return V(frame.Base), frame.Rotation.multVec(V(0, 0, 1)).normalize()


def _ray(view, x, y):
    """The pointer's ray (origin, unit direction) for device pixels x, y (y from the bottom)."""
    p = V(view.getPoint((int(x), int(y))))
    cam = view.getCameraNode()
    if cam.getTypeId().getName().getString() == "PerspectiveCamera":
        o = V(*cam.position.getValue().getValue())
        return o, (p - o).normalize()
    d = V(view.getViewDirection()).normalize()
    return p - d * 1e5, d


def closest_on_axis(o, z, q, d):
    """The axis parameter where the ray q + u d passes closest to the line o + s z."""
    w = o - q
    b = z.dot(d)
    den = 1.0 - b * b
    if den < 1e-9:
        return None         # looking straight along the axis
    return (b * w.dot(d) - w.dot(z)) / den


def _angle(z, a, b):
    a = a - z * a.dot(z)
    b = b - z * b.dot(z)
    if a.Length < 1e-9 or b.Length < 1e-9:
        return 0.0
    a, b = V(a).normalize(), V(b).normalize()
    return math.degrees(math.atan2(z.dot(a.cross(b)), a.dot(b)))


def follow(o, z, s0, radial0, q, d, t_now=0.0):
    """(slide, turn in degrees) that put the grabbed point under the pointer: where the pointer's
    ray meets the cylinder the grabbed point turns on; past its sides, the slide where the ray
    passes the axis closest and the turn towards the ray."""
    r = radial0.Length
    w = q - o
    if r > 1e-3:
        qp = w - z * w.dot(z)
        dp = d - z * d.dot(z)
        a2 = dp.dot(dp)
        if a2 > 1e-12:
            b2 = 2.0 * qp.dot(dp)
            c2 = qp.dot(qp) - r * r
            disc = b2 * b2 - 4.0 * a2 * c2
            if disc >= 0.0:
                u = (-b2 - math.sqrt(disc)) / (2.0 * a2)
                hit = q + d * u
                return (hit - o).dot(z) - s0, _angle(z, radial0, hit - o)
    den = d.dot(z)
    if r > 1e-3 and abs(den) >= 0.5:
        # looking (nearly) along the axis: it turns where the ray crosses the grabbed point's plane
        c = o + z * (s0 + t_now)
        hit = q + d * ((c - q).dot(z) / den)
        return t_now, _angle(z, radial0, hit - o)
    s = closest_on_axis(o, z, q, d)
    if s is None:
        return None
    if r <= 1e-3:
        return s - s0, 0.0
    u = d.dot(o + z * s - q)
    near = q + d * u
    return s - s0, _angle(z, radial0, near - o)


class _Drag:
    def __init__(self, asm, comp, joint, view, pos, info, sub):
        self.asm, self.comp, self.joint, self.view = asm, comp, joint, view
        self.press = QtCore.QPointF(pos)
        self.sub = sub
        self.moved = False
        self.start = App.Placement(comp.Placement)
        self.good = App.Placement(comp.Placement)
        self.good_t, self.good_a = 0.0, 0.0
        self.o, self.z = axis_of(asm, comp, joint)
        self.g = V(info.get("x", 0.0), info.get("y", 0.0), info.get("z", 0.0))
        self.s0 = (self.g - self.o).dot(self.z)
        foot = self.o + self.z * self.s0
        self.radial0 = self.g - foot
        self.pending = None
        self.timer = QtCore.QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.step)

    def target(self, x, y):
        q, d = _ray(self.view, x, y)
        tg = follow(self.o, self.z, self.s0, self.radial0, q, d, self.good_t)
        if tg is None:
            return None
        t, a = tg
        return t, self.good_a + ((a - self.good_a + 180.0) % 360.0 - 180.0)    # past half a turn: on round

    def placement(self, t, a):
        world0 = self.asm.Placement.multiply(self.start)
        turn = App.Placement(V(), App.Rotation(self.z, a), self.o)
        slide = App.Placement(self.z * t, App.Rotation())
        return self.asm.Placement.inverse().multiply(slide.multiply(turn).multiply(world0))

    def _try(self, t, a):
        ac = _ac()
        before = ac._save_placements(self.asm)
        self.comp.Placement = self.placement(t, a)
        with ac.temp_ground(self.asm, [self.comp]):
            ok = ac.solve(self.asm, before)
        if ok and ac.satisfied(self.joint):
            self.good = App.Placement(self.comp.Placement)
            self.good_t, self.good_a = t, a
            return True
        self.comp.Placement = App.Placement(self.good)
        with ac.temp_ground(self.asm, [self.comp]):
            ac.solve(self.asm)
        return False

    def go(self, t, a):
        if self._try(t, a):
            return
        lo_t, lo_a = self.good_t, self.good_a      # as far as the mates allow: halve the way there
        hi_t, hi_a = t, a
        for _ in range(7):
            mt, ma = (lo_t + hi_t) / 2.0, (lo_a + hi_a) / 2.0
            if self._try(mt, ma):
                lo_t, lo_a = mt, ma
            else:
                hi_t, hi_a = mt, ma

    def move(self, x, y):
        self.pending = (x, y)
        if not self.timer.isActive():
            self.timer.start(STEP_MS)

    def step(self):
        if self.pending is None:
            return
        x, y = self.pending
        self.pending = None
        tg = self.target(x, y)
        if tg is not None:
            self.go(*tg)
            Gui.updateGui()

    def finish(self):
        self.timer.stop()
        self.step()


def _device(widget, pos):
    dpr = widget.devicePixelRatioF()
    return pos.x() * dpr, (widget.height() - pos.y()) * dpr


def _pick(view, widget, pos):
    x, y = _device(widget, pos)
    try:
        return view.getObjectInfo((int(x), int(y)))
    except Exception:
        return None


def _start(widget, event):
    STATE["why"] = ""
    if Gui.Control.activeDialog():
        STATE["why"] = "a PropertyManager is open"
        return None
    asm = _active_assembly()
    if asm is None:
        STATE["why"] = "no assembly being edited"
        return None
    if not getattr(asm.ViewObject, "EnableMovement", True):
        STATE["why"] = "moving by dragging is off"
        return None
    view = Gui.ActiveDocument.ActiveView
    try:
        if view.graphicsView().viewport() is not widget:
            STATE["why"] = "not the active view"
            return None
    except Exception:
        return None
    info = _pick(view, widget, event.position())
    if not info:
        STATE["why"] = "nothing under the pointer"
        return None
    sub = info.get("SubName") or ""
    parent = info.get("ParentObject")
    names = sub.split(".")
    if parent is not asm and getattr(parent, "Name", None) != asm.Name:
        # the assembly under a Part or nested: the path names it first
        if asm.Name not in names:
            STATE["why"] = "not in the active assembly"
            return None
        names = names[names.index(asm.Name) + 1:]
        sub = ".".join(names)
    comp = asm.Document.getObject(names[0]) if names else None
    if comp is None or comp not in asm.Group:
        STATE["why"] = "not a component"
        return None
    joint = candidate(asm, comp)
    if joint is None:
        STATE["why"] = "not held by one Concentric alone"
        return None
    return _Drag(asm, comp, joint, view, event.position(), info, sub)


def _select(drag, event):
    """A click without a drag picks, as FreeCAD's own press would have."""
    try:
        doc = drag.asm.Document
        if not (event.modifiers() & QtCore.Qt.ControlModifier):
            Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, drag.asm.Name, drag.sub)
    except Exception:
        pass


class _Filter(QtCore.QObject):
    def eventFilter(self, obj, event):
        t = event.type()
        if t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease):
            return False
        try:
            return self._mouse(obj, event, t)
        except Exception as error:
            STATE["drag"] = None
            App.Console.PrintLog("FreeCAD: Concentric drag: %s\n" % error)
            return False

    def _mouse(self, obj, event, t):
        drag = STATE["drag"]
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() != QtCore.Qt.LeftButton or event.modifiers() & (QtCore.Qt.ShiftModifier | QtCore.Qt.AltModifier):
                return False
            drag = _start(obj, event)
            STATE["drag"] = drag
            return drag is not None
        if drag is None:
            return False
        if t == QtCore.QEvent.MouseMove:
            if not drag.moved:
                if (event.position() - drag.press).manhattanLength() < CLICK:
                    return True
                drag.moved = True
                drag.asm.Document.openTransaction("Move Component")
            x, y = _device(obj, event.position())
            drag.move(x, y)
            return True
        if event.button() != QtCore.Qt.LeftButton:
            return True
        STATE["drag"] = None
        if not drag.moved:
            _select(drag, event)
            return True
        x, y = _device(obj, event.position())
        drag.move(x, y)
        drag.finish()
        doc = drag.asm.Document
        doc.commitTransaction()
        try:
            from . import asmui
            asmui.refresh()
        except Exception:
            pass
        return True


_FILTER = []


def watch(viewport):
    if viewport is None or id(viewport) in STATE["filtered"]:
        return
    if not _FILTER:
        _FILTER.append(_Filter())
    viewport.installEventFilter(_FILTER[0])
    STATE["filtered"].add(id(viewport))
    viewport.destroyed.connect(lambda *_a, k=id(viewport): STATE["filtered"].discard(k))


def _watch_active(*_args):
    try:
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is not None and hasattr(view, "graphicsView"):
            watch(view.graphicsView().viewport())
    except Exception:
        pass


def install():
    """Watches each 3D view as it becomes active (only mouse presses do any work)."""
    if STATE.get("installed"):
        return
    STATE["installed"] = True
    mw = Gui.getMainWindow()
    area = mw.findChild(QtWidgets.QMdiArea)
    if area is not None:
        area.subWindowActivated.connect(lambda *_a: QtCore.QTimer.singleShot(0, _watch_active))
    _watch_active()
