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
from PySide import QtCore, QtGui, QtWidgets

from . import catalog, contextbar, customizedlg, events, paths, style
from .widgets import alive

_WATCH_TYPES = (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease,
                QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.Wheel)

Qt = QtCore.Qt

VIEW = "User parameter:BaseApp/Preferences/View"
NAVIGATION = "Gui::SolidWorksNavigationStyle"
PARAM = "MouseGestures"          # bool in the addon's parameters, on by default
COUNT = "MouseGestureCount"      # 4 (default) for the four straight directions, or 8


PART = ("ViewRight", "ViewTrimetric", "ViewTop", "ViewFront", "ViewLeft", "ViewBack", "ViewBottom", "ZoomArea")
SKETCH = ("Circle", "ExitSketch", "SmartDimension", "Convert", "Line", "Trim", "CornerRectangle", "SketchFillet")
# Shorter names on the ring than in the CommandManager
LABELS = {"CornerRectangle": "Corner Rectangle", "Trim": "Trim Entities", "Convert": "Convert Entities",
          "SketchFillet": "Sketch Fillet"}

START = 8        # px the pointer moves with the right button down before the ring shows
DEAD = 16        # px: letting go this close to the middle cancels
RING = 52        # px from the middle to the centre of each command; reaching it runs the command
BOX = 30         # px square behind each icon
ICON = 20
LABEL = 22       # px under the ring for the name of the command the pointer points at

T = style.T                      # the theme's colours, read when painting
DISC_LINE = QtGui.QColor(140, 148, 160, 220)
WEDGE = QtGui.QColor(190, 218, 244, 210)
ON_LINE = QtGui.QColor("#3c7fb1")

IDLE, PENDING, GESTURE, DONE = range(4)


def enabled_here():
    ""
    if not paths.params().GetBool(PARAM, True):
        return False
    return App.ParamGet(VIEW).GetString("NavigationStyle", "") == NAVIGATION


class Item:
    __slots__ = ("key", "label", "icon", "enabled", "angle")

    def __init__(self, key, label, icon, enabled, angle):
        self.key, self.label, self.icon, self.enabled, self.angle = key, label, icon, enabled, angle


def items_for(shell, mode, count):
    """The ring's commands: Customize > Mouse Gestures decides the count (2, 3, 4, 8 or 12) and the
    command of each direction for part, assembly, drawing and sketch."""
    if count in (4, 8):
        count = str(count)
    if count not in dict(customizedlg.GESTURE_COUNTS):
        count = customizedlg.gesture_count()
    out = []
    for key, angle in customizedlg.gesture_items(count, mode):
        if key not in catalog.BY_KEY:
            continue
        binding = shell.binding(key)
        cmd = binding.cmd
        if cmd.natives:
            on = contextbar.active_native(cmd) is not None
        else:
            on = bool(cmd.call and shell.special_enabled(cmd.call))
        out.append(Item(key, LABELS.get(key, cmd.label), binding.icon(), on, float(angle)))
    return out


def mode_now():
    ""
    if contextbar.sketch_in_edit() is not None:
        return "sketch"
    try:
        from . import swmenus
        if swmenus.drawing_in_front():
            return "drawing"
    except Exception as _fw_err:
        _fw_log("gestures.py:115", _fw_err)
    try:
        from . import asmcore
        if asmcore.is_assembly():
            from . import asmtools

            return "part" if asmtools.editing() is not None else "assembly"
    except Exception as _fw_err:
        _fw_log("gestures.py:123", _fw_err)
    return "part"


def pick(items, dx, dy):
    """Index of the command in the direction (dx, dy) from the middle (y down), or None in the
    middle or when that command cannot run now."""
    if not items or math.hypot(dx, dy) < DEAD:
        return None
    angle = math.degrees(math.atan2(-dy, dx)) % 360.0

    def off(item):
        d = abs(item.angle - angle) % 360.0
        return min(d, 360.0 - d)
    best = min(range(len(items)), key=lambda i: off(items[i]))
    return best if items[best].enabled else None


# --------------------------------------------------------------------------- the ring
class Guide(QtWidgets.QWidget):
    """The ring of commands, painted over the 3D view; it never takes the mouse."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SWGestureGuide")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.radius = RING + BOX // 2 + 8
        self.items = []
        self.current = None
        self.mode = None
        side = 2 * self.radius + 2
        self.resize(side, side + LABEL)
        self.hide()

    def centre(self):
        return QtCore.QPointF(self.radius + 1, self.radius + 1)

    def show_at(self, pos, mode, items):
        """pos: the middle of the ring in the parent's coordinates."""
        self.mode, self.items, self.current = mode, items, None
        self.move(pos - self.centre().toPoint())
        self.show()
        self.raise_()
        self.update()

    def set_current(self, index):
        if index != self.current:
            self.current = index
            self.update()

    def keys(self):
        return [item.key for item in self.items]

    def item_centre(self, item):
        a = math.radians(item.angle)
        c = self.centre()
        return QtCore.QPointF(c.x() + RING * math.cos(a), c.y() - RING * math.sin(a))

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        c = self.centre()
        r = self.radius
        pen = QtGui.QPen(DISC_LINE)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(T.rgba("base", 200))
        p.drawEllipse(c, r, r)
        if self.current is not None and self.items:
            span = 360.0 / max(len(self.items), 1)
            angle = self.items[self.current].angle
            outer = QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
            inner = QtCore.QRectF(c.x() - DEAD, c.y() - DEAD, 2 * DEAD, 2 * DEAD)
            path = QtGui.QPainterPath()
            path.arcMoveTo(outer, angle - span / 2)
            path.arcTo(outer, angle - span / 2, span)
            path.arcTo(inner, angle + span / 2, -span)
            path.closeSubpath()
            p.fillPath(path, WEDGE)
        p.setBrush(T.rgba("pane", 235))
        p.drawEllipse(c, DEAD, DEAD)
        p.setPen(Qt.NoPen)
        p.setBrush(T.text_dim)
        p.drawEllipse(c, 2, 2)
        for i, item in enumerate(self.items):
            on = i == self.current
            m = self.item_centre(item)
            box = QtCore.QRectF(m.x() - BOX / 2, m.y() - BOX / 2, BOX, BOX)
            line = QtGui.QPen(ON_LINE if on else T.line_mid)
            line.setCosmetic(True)
            p.setPen(line)
            p.setBrush(T.menu_hover if on else T.rgba("base", 240))
            p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            rect = QtCore.QRect(int(m.x() - ICON / 2), int(m.y() - ICON / 2), ICON, ICON)
            if item.icon is not None and not item.icon.isNull():
                style.paint_icon(p, item.icon, rect, Qt.AlignCenter, QtGui.QIcon.Normal if item.enabled else QtGui.QIcon.Disabled)
        if self.current is not None and self.items:
            text = self.items[self.current].label
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(text) + 12
            h = fm.height() + 4
            label = QtCore.QRectF(c.x() - w / 2, 2 * r + 2 + (LABEL - h) / 2, w, h)
            pen = QtGui.QPen(DISC_LINE)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(T.rgba("base", 235))
            p.drawRoundedRect(label.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            p.setPen(T.text)
            p.drawText(label, Qt.AlignCenter, text)
        p.end()


class _Watch(QtCore.QObject):
    """Application-wide filter, only while the ring shows: Esc or leaving the window cancels."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) and event.key() == Qt.Key_Escape:
            if t == QtCore.QEvent.KeyPress:
                self.owner.cancel()
            return True
        if t == QtCore.QEvent.WindowDeactivate and obj is self.owner.mw:
            self.owner.cancel()
        return False


# --------------------------------------------------------------------------- the right button
class Gestures(QtCore.QObject):
    """Watches the right button on the active 3D view."""

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.mw = shell.window
        self.guide = Guide(self.mw)
        self.state = IDLE
        self._press = None          # (widget, local pos, global pos, modifiers) of a held-back press
        self._replaying = False
        self._menu = None           # (widget, pos, global pos) of a context menu held with the press
        self._triad = None          # triadclick.Clicks: left clicks on the reference triad
        self._watching = False
        self._watch = _Watch(self)
        self._watched = []
        self.ran = []               # keys run by gestures, newest last, for checks
        self.mdi = self.mw.findChild(QtWidgets.QMdiArea)
        if self.mdi is not None:
            self.mdi.subWindowActivated.connect(self.attach)
        QtCore.QTimer.singleShot(0, self.attach)

    def attach(self, *args):
        """Watch the active 3D view. Installing again puts this filter first, ahead of the context
        toolbar's and FreeCAD's, which must not see a press that starts a gesture."""
        self._watched = [w for w in self._watched if alive(w)]
        view = self.shell.view_widget()
        if view is not None and alive(view) and not hasattr(view, "viewport"):

            pages = view.findChildren(QtWidgets.QGraphicsView)
            view = pages[0] if pages else None
        if view is None or not alive(view) or not hasattr(view, "viewport"):
            return
        widget = view.viewport()
        if widget is None:
            return
        widget.installEventFilter(self)
        if widget not in self._watched:
            self._watched.append(widget)

    def remove(self):
        self.cancel()
        self.state = IDLE
        for widget in self._watched:
            if alive(widget):
                widget.removeEventFilter(self)
        self._watched = []
        if self.mdi is not None and alive(self.mdi):
            try:
                self.mdi.subWindowActivated.disconnect(self.attach)
            except Exception as _fw_err:
                _fw_log("gestures.py:309", _fw_err)
        if alive(self.guide):
            self.guide.hide()
            self.guide.deleteLater()

    # ------------------------------------------------------------------ events
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if self._replaying:
            return False
        t = event.type()
        if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick) \
                and self.state == IDLE and self.shell.enabled:
            try:
                if self._triad is None:
                    from . import triadclick
                    self._triad = triadclick.Clicks(self.shell)
                if self._triad.handle(event):
                    return True
            except Exception as error:
                App.Console.PrintLog("FreeCAD: triad click: %s\n" % error)
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() == Qt.RightButton:
                if self.state != IDLE:
                    self._reset()      # a release went missing
                if event.buttons() == Qt.RightButton and event.modifiers() == Qt.NoModifier \
                        and self.shell.enabled and enabled_here():
                    self._press = (obj, QtCore.QPointF(event.position()), QtCore.QPointF(event.globalPosition()),
                                   event.modifiers())
                    self.state = PENDING
                    self._menu = None
                    return True
                return False
            if self.state == IDLE:
                return False
            # another button during a gesture ends it, and nothing else happens
            self.cancel()
            return True
        if t == QtCore.QEvent.MouseMove:
            if self.state == IDLE:
                return False
            d = event.position() - self._press[1] if self._press is not None else QtCore.QPointF()
            near = math.hypot(d.x(), d.y()) < START
            if not event.buttons() & Qt.RightButton:
                if self.state == PENDING and near:
                    return True        # a late move from before the press, on the same spot
                self._reset()          # the release went elsewhere
                return False
            if self.state == PENDING:
                if near:
                    return True
                self._begin()
            if self.state == GESTURE:
                self._track(event.position())
            return True
        if t == QtCore.QEvent.MouseButtonRelease:
            if event.button() != Qt.RightButton:
                return self.state != IDLE
            state, self.state = self.state, IDLE
            if state == PENDING:
                # no drag: FreeCAD gets its right-click, the press first
                self._replay()
                menu, self._menu = self._menu, None
                if menu is not None and alive(menu[0]):
                    QtWidgets.QApplication.sendEvent(menu[0], QtGui.QContextMenuEvent(
                        QtGui.QContextMenuEvent.Mouse, menu[1], menu[2]))
                return False
            if state == GESTURE:
                d = event.position() - self._press[1]
                index = pick(self.guide.items, d.x(), d.y())
                if index is None:
                    self._end()
                else:
                    self._run(index)
            self._press = None
            return state != IDLE
        if t == QtCore.QEvent.MouseButtonDblClick:
            return self.state != IDLE
        if t == QtCore.QEvent.ContextMenu:
            # Linux sends the context menu on the press: held back with the press, so a drawing
            # sheet's menu does not open over the ring; it comes after the press on a plain click
            if self.state == PENDING:
                self._menu = (obj, event.pos(), event.globalPos())
                return True
            return self.state in (GESTURE, DONE)
        if t == QtCore.QEvent.Wheel:
            return self.state in (GESTURE, DONE)
        return False

    def _begin(self):
        widget, local, _, _ = self._press
        mode = mode_now()
        count = customizedlg.gesture_count()
        items = items_for(self.shell, mode, count)
        try:
            from . import pmconfirm
            if pmconfirm.open():
                items = pmconfirm.gesture_items(items)     # OK up, Cancel down (pkg93)
        except Exception as _fw_err:
            _fw_log("gestures.py:409", _fw_err)
        self.guide.show_at(widget.mapTo(self.mw, local.toPoint()), mode, items)
        self.state = GESTURE
        if not self._watching:
            events.register("gestures", _WATCH_TYPES, self._watch.eventFilter)
            self._watching = True

    def _track(self, pos):
        d = pos - self._press[1]
        index = pick(self.guide.items, d.x(), d.y())
        self.guide.set_current(index)
        if index is not None and math.hypot(d.x(), d.y()) >= RING:

            self._run(index)
            self.state = DONE

    def _run(self, index):
        key = self.guide.items[index].key
        self._end()
        self.ran.append(key)
        QtCore.QTimer.singleShot(0, lambda: self._execute(key))

    def _execute(self, key):
        try:
            from . import pmconfirm
            if pmconfirm.run_key(key):
                return
            contextbar.run_key(self.shell, key)
        except Exception as error:
            App.Console.PrintError("FreeCAD: mouse gesture %s: %s\n" % (key, error))

    def _end(self):
        if alive(self.guide):
            self.guide.hide()
            self.guide.set_current(None)
        if self._watching:
            events.unregister("gestures")
            self._watching = False

    def cancel(self):
        """Esc, another button, or the window losing focus: no command, and the rest of the drag
        does nothing until the right button comes up."""
        if self.state in (PENDING, GESTURE):
            self.state = DONE
        self._end()

    def _reset(self):
        self._end()
        self.state = IDLE
        self._press = None

    def _replay(self):
        press, self._press = self._press, None
        if press is None:
            return
        widget, local, glob, mods = press
        if not alive(widget):
            return
        event = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, local, glob, Qt.RightButton, Qt.RightButton, mods)
        self._replaying = True
        try:
            QtWidgets.QApplication.sendEvent(widget, event)
        finally:
            self._replaying = False


# --------------------------------------------------------------------------- Tools > Mouse Gestures
class MouseGesturesCommand:
    def GetResources(self):
        return {
            "MenuText": "Mouse Gestures",
            "ToolTip": "Right-drag in the 3D view for a ring of commands",
            "Checkable": paths.params().GetBool(PARAM, True),
            "CmdType": "ForEdit",
        }

    def Activated(self, checked):
        paths.params().SetBool(PARAM, bool(checked))

    def IsActive(self):
        on = paths.params().GetBool(PARAM, True)
        try:
            actions = Gui.Command.get("SWStyle_MouseGestures").getAction()
        except Exception:
            actions = []
        for action in actions:
            if action.isChecked() != on:
                blocked = action.blockSignals(True)
                action.setChecked(on)
                action.blockSignals(blocked)
        return True


def register():
    Gui.addCommand("SWStyle_MouseGestures", MouseGesturesCommand())
    try:
        from . import tbkeys
        tbkeys.register()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: toolbar keys: %s\n" % error)
