# SPDX-License-Identifier: LGPL-2.1-or-later
""









_FW_SEEN = set()



def _alive(obj):
    """False for None or an object deleted under its wrapper (teardown.alive, review 1119)."""
    from . import teardown
    return teardown.alive(obj)


def _doc_alive(doc):
    from . import teardown
    return teardown.doc_alive(doc)


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

from . import instant3d

ARM_PX = 60                       # arm length on screen
HIT_PX = 9                        # pointer this close to an arm grabs it
COLOR = (1.0, 0.55, 0.0)
HOVER = (1.0, 0.8, 0.2)
STEP = 0.01                       # mm the move is rounded to
RULER_GAP_PX = 30                 # ruler this far beside the arm
RULER_SNAP_PX = 14                # pointer this close to the ruler snaps to its marks
TICK_MIN_PX = 8                   # marks at least this far apart on screen
RULER_COLOR = (0.15, 0.15, 0.15)


def _sketch_picked():
    sel = Gui.Selection.getSelectionEx("", 0)
    if len(sel) != 1:
        return None
    s = sel[0]
    obj = s.Object
    subs = [x for x in s.SubElementNames if x]
    # a full path from the document (Body.Sketch.) resolves to the sketch
    if len(subs) == 1 and subs[0].endswith("."):
        name = subs[0].rstrip(".").split(".")[-1]
        child = obj.Document.getObject(name)
        if child is not None:
            obj, subs = child, []
    if subs or obj.TypeId != "Sketcher::SketchObject":
        return None
    return obj


class _Triad:
    def __init__(self):
        self.timer = None
        self.sep = None
        self.parts = None           # (transform, [arm materials])
        self.view = None
        self.widget = None
        self.filter = None
        self.sketch = None
        self.key = None
        self.base = None            # world origin of the sketch
        self.axes = None            # world X and Y of the sketch
        self.length = 0.0
        self.drag = None
        self.hover = None

    # ---------------------------------------------------------------- watching the selection
    def start(self):
        if self.timer is None:
            self.timer = QtCore.QTimer()
            self.timer.setInterval(150)
            self.timer.timeout.connect(self.poll)
        self.timer.start()

    def stop(self):
        if self.timer is not None:
            self.timer.stop()
        self.cancel()
        self.clear()

    def poll(self):
        if self.drag is not None:
            return
        gdoc = Gui.ActiveDocument
        try:
            busy = gdoc is None or gdoc.getInEdit() is not None or bool(Gui.Control.activeDialog())
        except Exception:
            busy = True
        sketch = None if busy else _sketch_picked()
        view = gdoc.ActiveView if gdoc is not None else None
        if sketch is None or not hasattr(view, "getPoint"):
            self.clear()
            return
        gpl = sketch.getGlobalPlacement()
        base = gpl.Base
        axes = (gpl.Rotation.multVec(App.Vector(1, 0, 0)), gpl.Rotation.multVec(App.Vector(0, 1, 0)))
        length = self._arm_mm(view, base)
        key = (sketch.Name, tuple(round(x, 6) for x in base), tuple(round(x, 6) for x in axes[0]),
               tuple(round(x, 6) for x in axes[1]), round(length, 4), id(view))
        if key == self.key:
            return
        self.clear()
        self.sketch, self.base, self.axes, self.length, self.key = sketch, base, axes, length, key
        self._draw(view)

    def _arm_mm(self, view, base):
        try:
            s = view.getPointOnScreen(base)
            a = view.getPoint(int(s[0]), int(s[1]))
            b = view.getPoint(int(s[0]) + 100, int(s[1]))
            return max((b - a).Length / 100.0 * ARM_PX, 1e-6)
        except Exception:
            return 10.0

    # ---------------------------------------------------------------- drawing
    def _arm(self, coin, direction):
        sep = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*COLOR)
        sep.addChild(mat)
        rot = coin.SoTransform()
        q = App.Rotation(App.Vector(0, 1, 0), direction).Q
        rot.rotation.setValue(coin.SbRotation(q[0], q[1], q[2], q[3]))
        sep.addChild(rot)
        L = self.length
        shaft = coin.SoSeparator()
        st = coin.SoTranslation()
        st.translation.setValue(0, L * 0.4, 0)
        cyl = coin.SoCylinder()
        cyl.radius.setValue(L * 0.025)
        cyl.height.setValue(L * 0.8)
        shaft.addChild(st)
        shaft.addChild(cyl)
        head = coin.SoSeparator()
        ht = coin.SoTranslation()
        ht.translation.setValue(0, L * 0.9, 0)
        cone = coin.SoCone()
        cone.bottomRadius.setValue(L * 0.07)
        cone.height.setValue(L * 0.2)
        head.addChild(ht)
        head.addChild(cone)
        sep.addChild(shaft)
        sep.addChild(head)
        return sep, mat

    def _draw(self, view):
        from pivy import coin
        root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
        light = coin.SoLightModel()
        light.model.setValue(coin.SoLightModel.BASE_COLOR)
        xf = coin.SoTranslation()
        root.addChild(pick)
        root.addChild(light)
        root.addChild(xf)
        mats = []
        for axis in self.axes:
            sep, mat = self._arm(coin, axis)
            root.addChild(sep)
            mats.append(mat)
        # the small ball at the origin
        ball = coin.SoSeparator()
        bm = coin.SoMaterial()
        bm.diffuseColor.setValue(*COLOR)
        sphere = coin.SoSphere()
        sphere.radius.setValue(self.length * 0.06)
        ball.addChild(bm)
        ball.addChild(sphere)
        root.addChild(ball)
        xf.translation.setValue(self.base.x, self.base.y, self.base.z)
        view.getSceneGraph().addChild(root)
        self.sep, self.view, self.parts = root, view, (xf, mats)
        self._hook()

    def clear(self):
        if self.sep is not None and self.view is not None and _alive(self.view):
            try:
                self.view.getSceneGraph().removeChild(self.sep)
            except Exception as _fw_err:
                _fw_log("sketchtriad.py:190", _fw_err)
        self._unhook()
        self.sep = self.parts = self.sketch = self.key = None
        self.hover = None

    def _set_hover(self, arm):
        if self.parts is None or arm == self.hover:
            return
        self.hover = arm
        for i, mat in enumerate(self.parts[1]):
            mat.diffuseColor.setValue(*(HOVER if i == arm else COLOR))

    def _arm_under(self, pos):
        if self.sketch is None or self.view is None:
            return None
        shift = self.drag["shift"] if self.drag else App.Vector()
        base = self.base + shift
        try:
            a = self.view.getPointOnScreen(base)
            for i, axis in enumerate(self.axes):
                b = self.view.getPointOnScreen(base + axis * self.length)
                if instant3d._seg_dist(pos, a, b) <= HIT_PX:
                    return i
        except Exception as _fw_err:
            _fw_log("sketchtriad.py:214", _fw_err)
        return None

    # ---------------------------------------------------------------- the pointer
    def _hook(self):
        widget = instant3d._viewport()
        if widget is None or widget is self.widget:
            return
        self._unhook()
        if self.filter is None:
            self.filter = instant3d._Filter(self)
        widget.installEventFilter(self.filter)
        widget.setMouseTracking(True)
        if widget.parentWidget() is not None:
            widget.parentWidget().installEventFilter(self.filter)
        self.widget = widget

    def _unhook(self):
        if self.widget is not None and _alive(self.widget):
            try:
                self.widget.removeEventFilter(self.filter)
                if self.widget.parentWidget() is not None:
                    self.widget.parentWidget().removeEventFilter(self.filter)
            except Exception as _fw_err:
                _fw_log("sketchtriad.py:238", _fw_err)
        self.widget = None

    def coin_pos(self, event):
        g = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
        qpos = self.widget.mapFromGlobal(g)
        ratio = self.widget.devicePixelRatioF()
        return qpos.x() * ratio, (self.widget.height() - qpos.y()) * ratio

    def on_event(self, event):
        t = event.type()
        QE = QtCore.QEvent
        if t == QE.ShortcutOverride and self.drag is not None:
            event.accept()
            return True
        if t == QE.KeyPress:
            if self.drag is None:
                return False
            if event.key() == QtCore.Qt.Key_Escape:
                self.cancel()
            return True
        if not hasattr(event, "button") or self.widget is None:
            return False
        if t == QE.MouseButtonPress and event.button() == QtCore.Qt.LeftButton and self.drag is None:
            arm = self._arm_under(self.coin_pos(event))
            if arm is not None:
                return self.press(arm, self.coin_pos(event))
        elif t == QE.MouseMove:
            pos = self.coin_pos(event)
            if self.drag is not None:
                if not event.buttons() & QtCore.Qt.LeftButton:
                    self.release()          # the release went to another window
                    return False
                self.move(pos)
                return True
            self._set_hover(self._arm_under(pos))
        elif t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton and self.drag is not None:
            self.release()
            return True
        elif t == QE.MouseButtonDblClick and self.drag is not None:
            return True
        return False

    # ---------------------------------------------------------------- the drag
    def press(self, arm, pos):
        axis = self.axes[arm]
        t0 = instant3d._ray_param(self.view, pos, self.base, axis)
        if t0 is None:
            return False
        sk = self.sketch
        attached = getattr(sk, "MapMode", "Deactivated") != "Deactivated"
        prop = "AttachmentOffset" if attached else "Placement"
        doc = sk.Document
        doc.openTransaction("Move Sketch")
        try:
            self.drag = {"arm": arm, "t0": t0, "doc": doc, "prop": prop, "start": App.Placement(getattr(sk, prop)),
                         "shift": App.Vector(), "d": 0.0, "snapped": False, "ruler": None}
            QtWidgets.QApplication.instance().installEventFilter(self.filter)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        self._set_hover(arm)
        self._ruler_start(arm)
        return True

    def move(self, pos):
        d = self.value_at(pos)
        if d is None or abs(d - self.drag["d"]) < 1e-9:
            return
        arm = self.drag["arm"]
        self.drag["d"] = d
        self.drag["shift"] = self.axes[arm] * d
        self.parts[0].translation.setValue(*(self.base + self.drag["shift"]))
        self._ruler_draw(d)
        # the model follows at most every 80 ms (as Instant3D): a recompute on every pointer move
        # took 50-90 ms each, so the triad lagged behind the pointer
        if self.drag.get("timer") is None:
            timer = QtCore.QTimer()
            timer.setSingleShot(True)
            timer.setInterval(80)
            timer.timeout.connect(self._apply)
            self.drag["timer"] = timer
        if not self.drag["timer"].isActive():
            self.drag["timer"].start()

    def value_at(self, pos):
        """The move for the pointer at pos: on the ruler a mark, off it the pointer rounded to STEP."""
        arm = self.drag["arm"]
        r = self.drag.get("ruler")
        if r is not None and self._on_ruler(pos):
            t = instant3d._ray_param(self.view, pos, r["zero"], self.axes[arm])
            if t is not None:
                self.drag["snapped"] = True
                return round(t / r["tick"]) * r["tick"]
        self.drag["snapped"] = False
        t = instant3d._ray_param(self.view, pos, self.base, self.axes[arm])
        if t is None:
            return None
        return round((t - self.drag["t0"]) / STEP) * STEP

    # ---------------------------------------------------------------- the ruler
    def _ruler_start(self, arm):
        """A ruler along the dragged arm through the sketch's starting origin, beside the arm on the
        side away from the other arm."""
        axis, other = self.axes[arm], self.axes[1 - arm]
        try:
            look = App.Vector(self.view.getViewDirection())
        except Exception:
            return
        side = axis.cross(look)
        if side.Length < 0.2:
            return                       # looking (nearly) along the arm: no room for a ruler
        side.normalize()
        if side.dot(other) > 0:
            side = side * -1
        mm_px = self.length / ARM_PX
        tick = instant3d.nice_step(TICK_MIN_PX * mm_px)
        major = 10 ** (math.floor(math.log10(tick) + 1e-9) + 1)
        self.drag["ruler"] = {"zero": self.base + side * (RULER_GAP_PX * mm_px), "side": side, "tick": tick,
                              "major": float(major), "mm_px": mm_px, "end": 0.0, "node": None}
        self._ruler_draw(0.0)

    def ruler_point(self, v):
        r = self.drag["ruler"]
        return r["zero"] + self.axes[self.drag["arm"]] * v

    def _on_ruler(self, pos):
        r = self.drag.get("ruler")
        if r is None:
            return False
        try:
            a = self.view.getPointOnScreen(self.ruler_point(-r["end"]))
            b = self.view.getPointOnScreen(self.ruler_point(r["end"]))
        except Exception:
            return False
        return instant3d._seg_dist(pos, a, b) <= RULER_SNAP_PX

    def _ruler_draw(self, value):
        """(Re)build the ruler so it reaches well past value both ways."""
        from pivy import coin
        r = self.drag.get("ruler") if self.drag else None
        if r is None or self.sep is None:
            return
        reach = abs(value) + 3 * ARM_PX * r["mm_px"]
        if r["node"] is not None and r["end"] >= reach - 1e-9:
            return
        end = math.ceil(reach / r["major"]) * r["major"]
        if r["node"] is not None:
            self.sep.removeChild(r["node"])
        node = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*RULER_COLOR)
        node.addChild(mat)
        pts, counts = [self.ruler_point(-end), self.ruler_point(end)], [2]
        n = int(round(end / r["tick"]))
        labels = []
        for k in range(-n, n + 1):
            v = k * r["tick"]
            major = abs(v / r["major"] - round(v / r["major"])) < 1e-6
            p = self.ruler_point(v)
            pts += [p, p + r["side"] * (r["mm_px"] * (10 if major else 5))]
            counts.append(2)
            if major:
                labels.append((v, p + r["side"] * (r["mm_px"] * 13)))
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(pts), [(q.x, q.y, q.z) for q in pts])
        lines = coin.SoLineSet()
        lines.numVertices.setValues(0, len(counts), counts)
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(1.5)
        node.addChild(style)
        node.addChild(coords)
        node.addChild(lines)
        font = coin.SoFont()
        font.size.setValue(11)
        node.addChild(font)
        for v, q in labels:
            lab = coin.SoSeparator()
            tr = coin.SoTranslation()
            tr.translation.setValue(q.x, q.y, q.z)
            txt = coin.SoText2()
            txt.justification.setValue(coin.SoText2.CENTER)
            txt.string.setValue("%g" % round(v, 6))
            lab.addChild(tr)
            lab.addChild(txt)
            node.addChild(lab)
        # after the pick style and light model, before the triad's translation: world coordinates
        self.sep.insertChild(node, 2)
        r["node"], r["end"] = node, end

    def _apply(self):
        sk, drag = self.sketch, self.drag
        if drag is None or sk is None:
            return
        start = drag["start"]
        if drag["prop"] == "AttachmentOffset":
            # the offset is in the sketch's attachment frame: its own X and Y
            local = App.Vector(drag["d"], 0, 0) if drag["arm"] == 0 else App.Vector(0, drag["d"], 0)
            moved = App.Placement(start.Base + start.Rotation.multVec(local), start.Rotation)
        else:
            moved = App.Placement(start.Base + drag["shift"], start.Rotation)
        setattr(sk, drag["prop"], moved)
        sk.Document.recompute()

    def _end(self):
        timer = self.drag.get("timer") if self.drag else None
        if timer is not None:
            timer.stop()
        try:
            QtWidgets.QApplication.instance().removeEventFilter(self.filter)
        except Exception as _fw_err:
            _fw_log("sketchtriad.py:431", _fw_err)
        self.drag = None
        self.key = None            # redraw at the sketch's new origin

    def release(self):
        drag = self.drag
        if abs(drag["d"]) < 1e-9:
            drag["doc"].abortTransaction()
        else:
            self._apply()               # the last pointer position, even inside the 80 ms wait
            drag["doc"].commitTransaction()
        self._end()

    def cancel(self):
        if self.drag is None:
            return
        drag = self.drag
        try:
            setattr(self.sketch, drag["prop"], drag["start"])
            drag["doc"].abortTransaction()
            drag["doc"].recompute()
        except Exception as _fw_err:
            _fw_log("sketchtriad.py:452", _fw_err)
        self._end()
        self.clear()


_triad = None


def install():
    global _triad
    if _triad is None:
        _triad = _Triad()
    _triad.start()


def uninstall():
    if _triad is not None:
        _triad.stop()
