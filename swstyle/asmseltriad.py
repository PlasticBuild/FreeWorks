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
from PySide import QtCore

from . import asmcore as ac
from . import instant3d

ARROW_PX = 95
HIT_PX = 8
ORANGE = (1.0, 0.55, 0.05)
HOVER = (1.0, 0.8, 0.2)
BALL = (0.62, 0.8, 1.0)          # the light-blue see-through ball in the middle
LABEL = (0.25, 0.25, 0.25)
AXES = (("X", App.Vector(1, 0, 0)), ("Y", App.Vector(0, 1, 0)), ("Z", App.Vector(0, 0, 1)))
RING = 0.8                       # ring radius / arrow length (the rings pass by the arrow heads)
SEGMENTS = 48

_TRIAD = None


def triad():
    return _TRIAD


def ensure():
    """Starts watching the selection (once); called when an assembly is made active."""
    global _TRIAD
    if _TRIAD is None:
        _TRIAD = CompTriad()
    _TRIAD.start()
    return _TRIAD


def _ring_points(centre, axis, radius):
    u = axis.cross(App.Vector(0, 0, 1) if abs(axis.z) < 0.9 else App.Vector(1, 0, 0))
    u.normalize()
    v = axis.cross(u)
    return [centre + u * (radius * math.cos(2 * math.pi * i / SEGMENTS)) + v * (radius * math.sin(2 * math.pi * i / SEGMENTS))
            for i in range(SEGMENTS + 1)]


class CompTriad(instant3d._Instant3D):
    """The orange triad on a picked component, and its drag."""

    def __init__(self):
        super().__init__()
        self.comp = None
        self.asm = None
        self.centre = None
        self.handle = None          # ("arrow" | "ring", axis index) under the pointer or dragged
        self.mats = {}

    # ---------------------------------------------------------------- the pick
    def _component(self):
        """The one component picked whole, with its assembly, or None."""
        gdoc = Gui.ActiveDocument
        if gdoc is None:
            return None
        try:
            edit = gdoc.getInEdit()
        except Exception:
            edit = None
        if edit is not None and getattr(edit, "Object", None) is not None:
            return None             # editing a part, a sketch or Move with Triad
        if Gui.Control.activeDialog():
            return None             # a PropertyManager is up (Mate, Move Component...)
        sel = Gui.Selection.getSelectionEx("", 0)
        if len(sel) != 1 or len(sel[0].SubElementNames) > 1:
            return None
        obj = sel[0].Object
        sub = sel[0].SubElementNames[0] if sel[0].SubElementNames else ""
        if sub and not sub.endswith("."):
            return None             # a face, edge or vertex picked, not the component
        sig = (obj.Document.Name, obj.Name, sub)
        if sig == getattr(self, "_sig", None) and self._found is not None and not _alive(self._found):
            self._sig, self._found = None, None     # the document was closed and one with the same names opened
        if sig == getattr(self, "_sig", None):
            # the same pick: not walked again every tick (large assemblies); Fix still ends the triad
            if self._found is not None and self._found[0] in ac.grounded(self._found[1]):
                return None
            return self._found
        self._sig, self._found = sig, None
        names = [n for n in sub.split(".") if n]
        doc = obj.Document
        chain = [obj] + [doc.getObject(n) for n in names]
        if any(o is None for o in chain):
            return None
        comp, asm = chain[-1], (chain[-2] if len(chain) > 1 else None)
        if asm is None:
            from . import asmmenu
            asm = asmmenu.assembly_of(comp)
        if asm is None or getattr(asm, "TypeId", "") != "Assembly::AssemblyObject":
            return None
        if comp not in ac.components(asm) or comp in ac.grounded(asm):
            return None
        self._found = (comp, asm)
        return self._found

    def _centre(self, comp):
        """The box centre, read again only when the component moves (a big part's Shape is slow)."""
        plc = tuple(comp.Placement.toMatrix().A) if hasattr(comp, "Placement") else ()
        cache = getattr(self, "_bb", None)
        if cache is not None and cache[0] == (comp.Name, plc):
            return cache[1]
        try:
            bb = comp.Shape.BoundBox if hasattr(comp, "Shape") and not comp.Shape.isNull() else None
        except Exception:
            bb = None
        centre = bb.Center if bb is not None else comp.Placement.Base
        self._bb = ((comp.Name, plc), centre)
        return centre

    def poll(self):
        if self.drag is not None:
            return
        found = self._component() if instant3d.enabled() else None
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None
        if found is None or view is None or not hasattr(view, "getPoint"):
            self.clear()
            return
        comp, asm = found
        centre = self._centre(comp)
        length = self._arrow_mm(view, centre)
        key = (comp.Name, tuple(round(x, 6) for x in centre), round(length, 4), id(view))
        if key == self.key:
            return
        self.clear()
        self.comp, self.asm, self.centre, self.length, self.key = comp, asm, centre, length, key
        self._draw(view)

    def _arrow_mm(self, view, base):
        try:
            s = view.getPointOnScreen(base)
            a = view.getPoint(int(s[0]), int(s[1]))
            b = view.getPoint(int(s[0]) + 100, int(s[1]))
            return max((b - a).Length / 100.0 * ARROW_PX, 1e-6)
        except Exception:
            return 10.0

    # ---------------------------------------------------------------- the triad
    def _draw(self, view):
        from pivy import coin
        L = self.length
        root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
        light = coin.SoLightModel()
        light.model.setValue(coin.SoLightModel.BASE_COLOR)
        xf = coin.SoTransform()
        c = self.centre
        xf.translation.setValue(c.x, c.y, c.z)
        root.addChild(pick)
        root.addChild(light)
        root.addChild(xf)
        self.mats = {}
        zero = App.Vector()
        # the ball and the centre dot
        ball = coin.SoSeparator()
        bm = coin.SoMaterial()
        bm.diffuseColor.setValue(*BALL)
        bm.transparency.setValue(0.65)
        sph = coin.SoSphere()
        sph.radius.setValue(L * RING * 0.75)
        ball.addChild(bm)
        ball.addChild(sph)
        root.addChild(ball)
        dot = coin.SoSeparator()
        dm = coin.SoMaterial()
        dm.diffuseColor.setValue(1, 1, 1)
        ds = coin.SoSphere()
        ds.radius.setValue(L * 0.05)
        dot.addChild(dm)
        dot.addChild(ds)
        root.addChild(dot)
        for i, (name, axis) in enumerate(AXES):
            # the ring round the axis
            ring = coin.SoSeparator()
            rm = coin.SoMaterial()
            rm.diffuseColor.setValue(*ORANGE)
            style = coin.SoDrawStyle()
            style.lineWidth.setValue(4)
            pts = _ring_points(zero, axis, L * RING)
            co = coin.SoCoordinate3()
            co.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
            ls = coin.SoLineSet()
            ls.numVertices.setValue(len(pts))
            for n in (rm, style, co, ls):
                ring.addChild(n)
            root.addChild(ring)
            self.mats[("ring", i)] = rm
            # the arrow: a thin shaft and a cone, along +axis (Coin's cylinder and cone stand on Y)
            arrow = coin.SoSeparator()
            am = coin.SoMaterial()
            am.diffuseColor.setValue(*ORANGE)
            rot = coin.SoRotation()
            q = App.Rotation(App.Vector(0, 1, 0), axis).Q
            rot.rotation.setValue(coin.SbRotation(q[0], q[1], q[2], q[3]))
            st = coin.SoTranslation()
            st.translation.setValue(0, L * 0.4, 0)
            cyl = coin.SoCylinder()
            cyl.radius.setValue(L * 0.02)
            cyl.height.setValue(L * 0.8)
            ht = coin.SoTranslation()
            ht.translation.setValue(0, L * 0.5, 0)
            cone = coin.SoCone()
            cone.bottomRadius.setValue(L * 0.08)
            cone.height.setValue(L * 0.2)
            for n in (am, rot, st, cyl, ht, cone):
                arrow.addChild(n)
            root.addChild(arrow)
            self.mats[("arrow", i)] = am
            # its letter past the tip
            lab = coin.SoSeparator()
            lt = coin.SoTranslation()
            tip = axis * (L * 1.12)
            lt.translation.setValue(tip.x, tip.y, tip.z)
            lm = coin.SoMaterial()
            lm.diffuseColor.setValue(*LABEL)
            font = coin.SoFont()
            font.name.setValue("Sans")
            font.size.setValue(13)
            text = coin.SoText2()
            text.string.setValue(name)
            for n in (lt, lm, font, text):
                lab.addChild(n)
            root.addChild(lab)
        view.getSceneGraph().addChild(root)
        self.sep, self.view = root, view
        self.parts = (xf,)
        self._hook(view)

    def clear(self):
        super().clear()
        self.comp = self.asm = self.centre = None
        self.handle = None
        self.mats = {}

    # ---------------------------------------------------------------- where the pointer is
    def _handle_at(self, pos):
        if self.comp is None or self.view is None:
            return None
        c, L = self.centre, self.length
        best, which = HIT_PX, None
        try:
            for i, (_n, axis) in enumerate(AXES):
                a = self.view.getPointOnScreen(c + axis * (L * 0.15))
                b = self.view.getPointOnScreen(c + axis * L)
                d = instant3d._seg_dist(pos, a, b)
                if d <= best:
                    best, which = d, ("arrow", i)
            for i, (_n, axis) in enumerate(AXES):
                pts = [self.view.getPointOnScreen(p) for p in _ring_points(c, axis, L * RING)]
                for a, b in zip(pts, pts[1:]):
                    d = instant3d._seg_dist(pos, a, b)
                    if d < best:
                        best, which = d, ("ring", i)
        except Exception as _fw_err:
            _fw_log("asmseltriad.py:handle", _fw_err)
            return None
        return which

    def over_arrow(self, pos):
        return self._handle_at(pos) is not None

    def _set_hover(self, on, which=None):
        which = which if on else None
        if which == self.handle and on == self.hover:
            return
        for key, mat in self.mats.items():
            mat.diffuseColor.setValue(*(HOVER if key == which else ORANGE))
        self.hover, self.handle = on, which

    def on_event(self, event):
        t = event.type()
        QE = QtCore.QEvent
        if t == QE.ShortcutOverride and self.drag is not None:
            event.accept()
            return True
        if t == QE.KeyPress:
            if self.drag is not None and event.key() == QtCore.Qt.Key_Escape:
                self.cancel()
                return True
            return self.drag is not None
        if not hasattr(event, "button"):
            return False
        if t == QE.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            pos = self.coin_pos(event)
            which = self._handle_at(pos)
            if self.drag is None and which is not None:
                return self.press(pos, which)
        elif t == QE.MouseMove:
            pos = self.coin_pos(event)
            if self.drag is not None:
                self.move(pos)
                return True
            which = self._handle_at(pos)
            self._set_hover(which is not None, which)
        elif t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton and self.drag is not None:
            self.release()
            return True
        elif t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton and self.swallow:
            self.swallow = False        # the button coming up after Escape: FreeCAD never saw the press
            return True
        elif t == QE.MouseButtonDblClick and self.drag is not None:
            return True
        return False

    # ---------------------------------------------------------------- the drag
    def _ring_angle(self, pos, axis):
        """The pointer's angle round axis through the centre, on the ring's plane."""
        try:
            ray_from = App.Vector(self.view.getPoint(int(pos[0]), int(pos[1])))
            look = App.Vector(self.view.getViewDirection())
        except Exception:
            return None
        denom = look.dot(axis)
        if abs(denom) < 0.05:
            return None
        t = (self.centre - ray_from).dot(axis) / denom
        r = ray_from + look * t - self.centre
        u = axis.cross(App.Vector(0, 0, 1) if abs(axis.z) < 0.9 else App.Vector(1, 0, 0))
        u.normalize()
        v = axis.cross(u)
        return math.degrees(math.atan2(r.dot(v), r.dot(u)))

    def press(self, pos, which=None):
        which = which or self._handle_at(pos)
        if which is None or self.comp is None:
            return False
        kind, i = which
        axis = AXES[i][1]
        start = self._ring_angle(pos, axis) if kind == "ring" else instant3d._ray_param(self.view, pos, self.centre, axis)
        if start is None:
            return False
        doc = self.comp.Document
        doc.openTransaction("Move Component")
        self.drag = {"which": which, "start": start, "p0": App.Placement(self.comp.Placement),
                     "doc": doc, "shift": 0.0, "last": start}
        from . import events
        events.register("asmseltriad-%d" % id(self), instant3d.DRAG_EVENTS, self.filter.eventFilter)
        self._set_hover(True, which)
        return True

    def move(self, pos):
        d = self.drag
        kind, i = d["which"]
        axis = AXES[i][1]
        p0 = d["p0"]
        if kind == "arrow":
            t = instant3d._ray_param(self.view, pos, self.centre, axis)
            if t is None:
                return
            shift = t - d["start"]
            self.comp.Placement = App.Placement(p0.Base + axis * shift, p0.Rotation)
            d["shift"] = shift
            if self.parts:
                c = self.centre + axis * shift
                self.parts[0].translation.setValue(c.x, c.y, c.z)
        else:
            a = self._ring_angle(pos, axis)
            if a is None:
                return
            turn = App.Rotation(axis, a - d["start"])
            moved = App.Placement(App.Vector(), turn, self.centre).multiply(p0)
            self.comp.Placement = moved
        if hasattr(self.view, "redraw"):
            self.view.redraw()

    def _end(self):
        from . import events
        events.unregister("asmseltriad-%d" % id(self))
        self.drag = None
        self.key = None             # drawn again where the component is now
        self._sig = None
        self._set_hover(False)

    def release(self):
        d = self.drag
        try:
            ac.solve(self.asm)
            d["doc"].commitTransaction()
            d["doc"].recompute()
        except Exception as error:
            _fw_log("asmseltriad.py:release", error)
            try:
                d["doc"].abortTransaction()
            except Exception as _fw_err:
                _fw_log("asmseltriad.py:abort", _fw_err)
        self._end()

    def cancel(self):
        d = self.drag
        if d is None:
            return
        try:
            self.comp.Placement = d["p0"]
            d["doc"].abortTransaction()
        except Exception as _fw_err:
            _fw_log("asmseltriad.py:cancel", _fw_err)
        self.swallow = True
        self._end()


def _alive(found):
    """The cached (component, assembly) still there (not deleted with a closed document)."""
    try:
        return all(o is not None and o.Document is not None and o.Name for o in found[:2])
    except Exception:       # ReferenceError: a deleted object
        return False
