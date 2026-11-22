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

from . import asmcore as ac

RED = (1.0, 0.25, 0.25)
TOUCH = 1e-3            # mm^3 of common volume that counts as a collision


def _shape(comp):
    try:
        return comp.Shape
    except Exception:
        return None


def overlap(a, b, gap=0.0):
    """The common volume of two components (0 when apart); gap > 0 counts near misses too."""
    sa, sb = _shape(a), _shape(b)
    if sa is None or sb is None or sa.isNull() or sb.isNull():
        return 0.0
    ba, bb = sa.BoundBox, sb.BoundBox
    if gap > 0:
        ba = App.BoundBox(ba)
        ba.enlarge(gap)
    if not ba.intersect(bb):
        return 0.0
    if gap > 0:
        try:
            if sa.distToShape(sb)[0] <= gap:
                return max(TOUCH * 2, sa.common(sb).Volume)
        except Exception as _fw_err:
            _fw_log("asmcollide.py:57", _fw_err)
    try:
        return sa.common(sb).Volume
    except Exception:
        return 0.0


SIMPLE = ("Part::GeomPlane", "Part::GeomCylinder", "Part::GeomCone", "Part::GeomSphere", "Part::GeomToroid")


def complex_only(comp):
    ""


    s = _shape(comp)
    if s is None or s.isNull() or not s.Faces:
        return False
    return all(f.Surface.TypeId not in SIMPLE for f in s.Faces)


def shown(comp):
    """This configuration: only components shown and not suppressed are checked."""
    vo = getattr(comp, "ViewObject", None)
    if vo is not None and not vo.Visibility:
        return False
    return not getattr(comp, "Suppressed", False)


def collisions(asm, moved, among=None, gap=0.0, ignore_complex=False, this_config=False):
    """[(moved component, other)] that overlap."""
    others = among if among else ac.components(asm)
    out = []
    for m in moved:
        if ignore_complex and complex_only(m):
            continue
        for o in others:
            if o is m or o in moved:
                continue
            if (ignore_complex and complex_only(o)) or (this_config and not shown(o)):
                continue
            if overlap(m, o, gap) > TOUCH:
                out.append((m, o))
    return out


def _contact_push(m, o, d):
    ""

    u = App.Vector(d)
    u.normalize()
    try:
        front = max(v.Point.dot(u) for v in m.Shape.Vertexes)
        back = min(v.Point.dot(u) for v in o.Shape.Vertexes)
    except Exception:
        return d
    go = min(d.Length, max(0.0, front - back))
    return u * go


def _mated(asm, comp):
    """comp has a live mate (one that can hold it where it is)."""
    for j in ac.mates(asm):
        if getattr(j, "Suppressed", False):
            continue
        for r in (getattr(j, "Reference1", None), getattr(j, "Reference2", None)):
            if r and r[0] is comp:
                return True
    return False


class Watch(QtCore.QObject):
    """Follows the placements while the Move Component PM is open: each tick the components
    that moved since the last clean tick are checked."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.asm = panel.asm
        self.good = {}
        self.lit = {}
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.snapshot()

    def snapshot(self):
        self.good = {c.Name: App.Placement(c.Placement) for c in ac.components(self.asm)}

    def start(self):
        self.snapshot()
        self.drag_start = dict(self.good)
        self.timer.start(30)

    def stop(self):
        self.timer.stop()
        self.unlight()

    def moved(self):
        comps = {c.Name: c for c in ac.components(self.asm)}
        out = []
        for n, p in self.good.items():
            c = comps.get(n)
            if c is not None and ((c.Placement.Base - p.Base).Length > 1e-9
                                  or not c.Placement.Rotation.isSame(p.Rotation, 1e-12)):
                out.append(c)
        return out

    def keep_to_mode(self, moved):
        """Along Assembly XYZ / Along Entity / About Entity: the dragged component kept to it."""
        start = getattr(self, "drag_start", None) or self.good
        fn = getattr(self.panel, "constrain", None)
        if fn is None:
            return False
        dragged = [c for c in moved if c in self.panel.comps] or moved[:1]
        changed = False
        for c in dragged:
            s = start.get(c.Name)
            if s is None:
                continue
            want = fn(c, s)
            if want is not None and not want.isSame(c.Placement, 1e-9):
                c.Placement = want
                changed = True
        if changed and len(moved) > len(dragged):
            try:
                ac.solve(self.asm)
            except Exception as _fw_err:
                _fw_log("asmcollide.py:183", _fw_err)
        return changed

    def tick(self):
        p = self.panel
        mode = p.option()
        moved = self.moved()
        if moved:
            self.keep_to_mode(moved)
            moved = self.moved()
        if moved and getattr(p, "clearance_stop", None) is not None and p.clearance_stop():
            for c in moved:         # Stop at specified clearance: back to the last spot that kept it
                c.Placement = self.good[c.Name]
            p.clearance()
            return []
        if mode == "Standard Drag":
            self.snapshot()
            return []
        if not moved:
            return []
        dragged = [c for c in moved if c in p.comps] or moved[:1]
        # Dragged part only is a Collision Detection option (shown only there)
        check = dragged if mode == "Physical Dynamics" or p.dragged_only.isChecked() else moved
        among = p.these() if p.check_these.isChecked() else None
        flags = dict(ignore_complex=getattr(p, "ignore_complex", None) is not None and p.ignore_complex.isChecked(),
                     this_config=getattr(p, "this_config", None) is not None and p.this_config.isChecked())
        if mode == "Collision Detection" and p.stop_at.isChecked():
            # a big step (a fast drag, a typed rotation) checked on the way, so it cannot jump
            # through a thin wall: it stops at the last clean spot along the path
            back = self._sweep(dragged, check, among, flags)
            if back:
                if p.highlight.isChecked():
                    self.light({c for pair in back for c in pair})
                if p.sound.isChecked():
                    QtWidgets.QApplication.beep()
                return back
        hits = collisions(self.asm, check, among, **flags)
        if mode == "Physical Dynamics":
            # a free component the dragged one runs into (or comes within the sensitivity of) is pushed along
            fixed = set(ac.grounded(self.asm))
            gap = p.sensitivity.value() / 10.0
            free = [c for c in (among or ac.components(self.asm)) if c not in fixed]
            blocked = []
            for m, o in collisions(self.asm, check, free, gap, **flags):
                d = m.Placement.Base - self.good[m.Name].Base
                if d.Length > 0 and d.dot(o.Shape.BoundBox.Center - m.Shape.BoundBox.Center) > 0:
                    start = App.Vector(o.Placement.Base)
                    d = _contact_push(m, o, d)
                    o.Placement = App.Placement(o.Placement.Base + d, o.Placement.Rotation)
                    if _mated(self.asm, o) and not self._push_holds(o, start, d, dragged):
                        blocked.append(o)       # its mates hold it: it stops the drag as a fixed one would
            if blocked:
                for c in ac.components(self.asm):
                    if c not in dragged and c.Name in self.good:
                        c.Placement = self.good[c.Name]
                self._sweep(dragged, check, blocked, flags)
                if p.highlight.isChecked():
                    self.light(set(blocked) | set(dragged))
                self.snapshot()
                return [(m, o) for m in dragged for o in blocked]
            hits = [(m, o) for m, o in hits if o in fixed]
        if hits:
            if p.highlight.isChecked():
                self.light({c for pair in hits for c in pair})
            if p.sound.isChecked():
                QtWidgets.QApplication.beep()
            if mode == "Collision Detection" and p.stop_at.isChecked() or mode == "Physical Dynamics":
                comps = {c.Name: c for c in ac.components(self.asm)}
                for c in moved:
                    c.Placement = self.good[c.Name]
                return hits
        else:
            self.unlight()
        self.snapshot()
        return hits

    def _push_holds(self, o, start, d, dragged):
        """o pushed by d: the mates solved with the dragged components where they are. True
        when o could go (its mates let it move that way), else everything the solve moved is
        put back."""
        keep = {c.Name: App.Placement(c.Placement) for c in dragged}
        try:
            ac.solve(self.asm)
        except Exception as _fw_err:
            _fw_log("asmcollide.py:266", _fw_err)
        for c in dragged:
            c.Placement = keep[c.Name]
        went = o.Placement.Base - start
        return (went - d).Length < 1e-4 * max(1.0, d.Length)

    def _sweep(self, dragged, check, among, flags):
        """The dragged components moved in small steps from where they were clean to where they
        are now; at the first step that collides they go back one step. The hits, or []."""
        import math
        ends = {}
        n = 1
        for c in dragged:
            a, b = self.good.get(c.Name), App.Placement(c.Placement)
            if a is None:
                continue
            size = max(min(c.Shape.BoundBox.XLength, c.Shape.BoundBox.YLength, c.Shape.BoundBox.ZLength), 1e-3)
            turn = math.degrees(a.Rotation.inverted().multiply(b.Rotation).Angle)
            reach = c.Shape.BoundBox.DiagonalLength / 2.0
            arc = math.radians(turn) * reach
            n = max(n, int(math.ceil(((b.Base - a.Base).Length + arc) / (0.25 * size))))
            ends[c.Name] = (c, a, b)
        if n <= 1 or not ends:
            return []
        n = min(n, 60)
        def put(f):
            for c, a, b in ends.values():
                c.Placement = a.sclerp(b, f) if hasattr(a, "sclerp") else App.Placement(
                    a.Base + (b.Base - a.Base) * f, App.Rotation(a.Rotation).slerp(b.Rotation, f))
        for i in range(1, n + 1):
            f = float(i) / n
            put(f)
            hits = collisions(self.asm, check, among, **flags)
            if hits:
                lo, hi = float(i - 1) / n, f
                for _ in range(6):
                    mid = (lo + hi) / 2.0
                    put(mid)
                    if collisions(self.asm, check, among, **flags):
                        hi = mid
                    else:
                        lo = mid
                put(lo)
                if lo > 0:
                    self.snapshot()
                return hits
        return []

    def light(self, comps):
        for c in comps:
            vo = getattr(c, "ViewObject", None)
            if vo is None or c.Name in self.lit:
                continue
            try:
                self.lit[c.Name] = (vo.OverrideMaterial, vo.ShapeMaterial)
                m = App.Material()
                m.DiffuseColor = RED
                vo.ShapeMaterial = m
                vo.OverrideMaterial = True
            except Exception as _fw_err:
                _fw_log("asmcollide.py:326", _fw_err)

    def unlight(self):
        comps = {c.Name: c for c in ac.components(self.asm)}
        for name, (override, material) in list(self.lit.items()):
            c = comps.get(name)
            if c is not None:
                try:
                    c.ViewObject.ShapeMaterial = material
                    c.ViewObject.OverrideMaterial = override
                except Exception as _fw_err:
                    _fw_log("asmcollide.py:337", _fw_err)
        self.lit = {}


class _Press(QtCore.QObject):
    """A left press in the 3D view starts the watch; the release ends it."""

    def __init__(self, watch):
        super().__init__()
        self.watch = watch

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress and getattr(event, "button", lambda: None)() == QtCore.Qt.LeftButton:
            if obj.inherits("QOpenGLWidget") or (obj.parent() is not None and obj.parent().inherits("QGraphicsView")):
                self.watch.start()
        elif t == QtCore.QEvent.MouseButtonRelease and self.watch.timer.isActive():
            self.watch.tick()
            self.watch.timer.stop()
        return False


def _app_filter(name, types, flt, on=True):
    ""
    try:
        from . import events
        if on:
            events.register(name, types, flt.eventFilter)
        else:
            events.unregister(name)
        return True
    except ImportError:
        app = QtWidgets.QApplication.instance()
        (app.installEventFilter if on else app.removeEventFilter)(flt)
        return False


def install(panel):
    watch = Watch(panel)
    press = _Press(watch)
    _app_filter("asm.collide", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease), press)
    watch._press = press
    return watch


def remove(watch):
    if watch is None:
        return
    watch.stop()
    try:
        _app_filter("asm.collide", (), watch._press, False)
    except Exception as _fw_err:
        _fw_log("asmcollide.py:391", _fw_err)
