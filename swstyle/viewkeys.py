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

import functools
import math
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import contextbar, middlemouse, wheelzoom
from .widgets import alive

Qt = QtCore.Qt

STEP = 15.0
TURN = 90.0          # with Shift
BURST = 0.6          # s: keys closer together than this make one view change
ARROWS = (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down)
MODS = Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
HISTORY = 11
SETTLE = 0.6         # s a view must stay put to count as a view
ENTER = (Qt.Key_Return, Qt.Key_Enter)
# fckeys-1126: FreeCAD's number keys for the standard views (0 Isometric, 1 Front, 2 Top, 3 Right, 4 Rear,

# view commands, so Update Standard Views holds for them too
DIGIT_VIEWS = {Qt.Key_0: "SWStyle_StandardIsometric", Qt.Key_1: "SWStyle_StandardFront", Qt.Key_2: "SWStyle_StandardTop",
               Qt.Key_3: "SWStyle_StandardRight", Qt.Key_4: "SWStyle_StandardBack", Qt.Key_5: "SWStyle_StandardBottom",
               Qt.Key_6: "SWStyle_StandardLeft"}
ZOOM_KEYS = {Qt.Key_Plus: "Std_ViewZoomIn", Qt.Key_Equal: "Std_ViewZoomIn", Qt.Key_Minus: "Std_ViewZoomOut"}
# Widgets that keep the keys when the pointer moves over the 3D view.
TYPING = (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)
# Commands Enter does not repeat (name prefixes): files, undo, deleting, dialogs, switches.
NOT_REPEATED = ("Std_Undo", "Std_Redo", "Std_Delete", "Std_Quit", "Std_New", "Std_Open", "Std_Save", "Std_Close",
                "Std_Export", "Std_Import", "Std_Print", "Std_Macro", "Std_DlgMacro", "Std_Recent", "Std_Workbench",
                "Std_Dlg", "Std_OnlineHelp", "Std_About", "Std_WhatsThis", "Std_PythonHelp", "Std_ToggleNavigation",
                "Std_UserEditMode", "Std_Edit", "Std_ProjectUtil", "Std_RestartInSafeMode", "Std_ReportBug",
                "Std_Revert", "Std_MergeProjects", "Std_SendToPythonConsole", "Sketcher_LeaveSketch",
                "SWStyle_ShortcutBar", "SWStyle_ViewOrientation", "SWStyle_MouseGestures", "SWStyle_AutomaticRelations",
                "SWStyle_Toggle", "SWStyle_ZoomAboutScreenCenter", "SWStyle_NewDocument", "SWStyle_Options",
                "SWStyle_Open", "SWStyle_SaveAs")


def repeatable(name):
    return bool(name) and not name.startswith(NOT_REPEATED)


def _view():
    try:
        doc = Gui.ActiveDocument
        view = doc.ActiveView if doc is not None else None
    except Exception:
        return None
    return view if view is not None and hasattr(view, "setCamera") else None


# --------------------------------------------------------------------------- camera text
class Camera:
    """FreeCAD's camera text (View.getCamera, an Inventor camera node) read and rewritten."""

    def __init__(self, text):
        self.text = text
        self.kind = ""
        self.fields = {}
        for line in text.splitlines():
            words = line.split()
            if not words or words[0].startswith("#"):
                continue
            if not self.kind and words[0].endswith("Camera"):
                self.kind = words[0]
                continue
            values = []
            for word in words[1:]:
                try:
                    values.append(float(word))
                except ValueError:
                    break
            if values:
                self.fields[words[0]] = values

    @property
    def position(self):
        return App.Vector(*self.fields["position"][:3])

    @property
    def rotation(self):
        x, y, z, angle = (self.fields.get("orientation") or [0.0, 0.0, 1.0, 0.0])[:4]
        if x == y == z == 0.0:
            z = 1.0
        return App.Rotation(App.Vector(x, y, z), math.degrees(angle))

    @property
    def focal(self):
        return (self.fields.get("focalDistance") or [0.0])[0]

    @property
    def size(self):
        return (self.fields.get("height") or self.fields.get("heightAngle") or [0.0])[0]

    def focal_point(self):
        return self.position - self.rotation.multVec(App.Vector(0, 0, 1)) * self.focal

    def same(self, other):
        """The same view, give or take the rounding in the text; the clipping distances, which
        FreeCAD works out again for every picture, do not count."""
        if other is None or self.kind != other.kind or "position" not in self.fields \
                or "position" not in other.fields:
            return False
        scale = max(abs(self.size), abs(self.focal), self.position.Length, 1.0)
        if (self.position - other.position).Length > 1e-6 * scale:
            return False
        if abs(self.size - other.size) > 1e-6 * max(abs(self.size), 1e-9):
            return False
        if abs(self.focal - other.focal) > 1e-6 * scale:
            return False
        a, b = self.rotation.Q, other.rotation.Q
        return abs(sum(x * y for x, y in zip(a, b))) > 1.0 - 1e-10

    def same_pose(self, other):
        """The same place and direction whatever the projection (Perspective toggled in between)."""
        if other is None or "position" not in self.fields or "position" not in other.fields:
            return False
        # FreeCAD's toggle moves the camera along its line of sight and keeps what it looks at
        scale = max(abs(self.focal), abs(other.focal), self.position.Length, 1.0)
        if (self.focal_point() - other.focal_point()).Length > 1e-4 * scale:
            return False
        a, b = self.rotation.Q, other.rotation.Q
        return abs(sum(x * y for x, y in zip(a, b))) > 1.0 - 1e-9

    def with_pose(self, position, rotation):
        axis, angle = rotation.Axis, rotation.Angle
        lines = []
        for line in self.text.splitlines():
            words = line.split()
            indent = line[:len(line) - len(line.lstrip())]
            if words and words[0] == "position":
                line = "%sposition %.9g %.9g %.9g" % (indent, position.x, position.y, position.z)
            elif words and words[0] == "orientation":
                line = "%sorientation %.9g %.9g %.9g %.9g" % (indent, axis.x, axis.y, axis.z, angle)
            lines.append(line)
        return "\n".join(lines) + "\n"


def turn_rotation(rotation, key, angle, roll=False):
    """The turn of the camera, in model space, for an arrow key. The model turns the way the
    arrow points, so the camera goes the other way about the screen's up, right or
    out-of-screen axis."""
    right = rotation.multVec(App.Vector(1, 0, 0))
    up = rotation.multVec(App.Vector(0, 1, 0))
    out = rotation.multVec(App.Vector(0, 0, 1))
    if roll:
        # Alt+Left turns the model clockwise on the screen, Alt+Right anticlockwise
        return App.Rotation(out, angle if key == Qt.Key_Left else -angle)
    if key in (Qt.Key_Left, Qt.Key_Right):
        return App.Rotation(up, angle if key == Qt.Key_Left else -angle)
    return App.Rotation(right, angle if key == Qt.Key_Up else -angle)


def model_centre(camera):
    ""

    box = middlemouse.model_box()
    if box is not None:
        return box.Center
    return camera.focal_point()


# --------------------------------------------------------------------------- view history
class ViewHistory:
    ""

    def __init__(self):
        self.docs = {}       # document key -> {"views": [Camera], "seen": Camera, "since": time}

    def _entry(self, key):
        return self.docs.setdefault(key, {"views": [], "seen": None, "since": 0.0})

    def prune(self, live):
        """perf-1126: forget the documents that are closed (their views grew without limit)."""
        for key in [k for k in self.docs if k not in live]:
            del self.docs[key]

    def sample(self, key, text, now):
        """Called a few times a second with the current camera: a view that stays put for
        SETTLE seconds is added."""
        entry = self._entry(key)
        camera = Camera(text)
        if not camera.same(entry["seen"]):
            entry["seen"], entry["since"] = camera, now
            return
        if now - entry["since"] >= SETTLE:
            self._add(entry, camera)

    def push(self, key, text):
        """The view about to be left by a command, added at once."""
        entry = self._entry(key)
        self._add(entry, Camera(text))
        entry["seen"] = None    # the view being left must not count as settled again before the move starts

    def _add(self, entry, camera):
        views = entry["views"]
        if not views or not camera.same(views[-1]):
            views.append(camera)
            del views[:-HISTORY]

    def previous(self, key, text):
        """Camera text of the view before the current one, or None. Views it steps back over are
        dropped, so the next call goes one further back."""
        entry = self.docs.get(key)
        if not entry:
            return None
        current = Camera(text)
        views = entry["views"]
        while views and (current.same(views[-1]) or
                         (views[-1].kind != current.kind and current.same_pose(views[-1]))):
            views.pop()
        # the view being left was settled long ago: a sample taken before the move's first frame
        # would add it back, and the next Previous View would only go there and back
        entry["seen"] = None
        if not views:
            return None
        back = views[-1]
        if back.kind != current.kind:

            # and the projection stays as it is now (it turned Perspective off, and stayed put)
            # (looking at the same point from the current distance: a perspective camera at an
            # orthographic one's place stood too close)
            at = back.focal_point() + back.rotation.multVec(App.Vector(0, 0, 1)) * current.focal
            return current.with_pose(at, back.rotation)
        return back.text

    def has_previous(self, key, text):
        entry = self.docs.get(key)
        if not entry or not entry["views"]:
            return False
        current = Camera(text)
        return any(not current.same(v) for v in entry["views"])

    def count(self, key):
        entry = self.docs.get(key)
        return len(entry["views"]) if entry else 0


# --------------------------------------------------------------------------- repeat last command
def _entries_by_text(name):
    """Menu text -> command for the entries of one of the style's submenus (keys.py)."""
    try:
        from . import keys
        out = {}
        for child in keys.group_commands(name):
            text = (Gui.Command.get(child).getInfo() or {}).get("menuText", "")
            out[text.replace("&", "")] = child
        return out
    except Exception:
        return {}


class LastCommand(QtCore.QObject):
    ""


    def __init__(self, parent=None):
        super().__init__(parent)
        self.name = None
        self._hooked = {}            # command name -> [(QAction, slot)] connected to note()

    def hook(self):
        """Watch the QActions of every command FreeCAD has made one for. Commands of a workbench
        get theirs when it is first opened, so this runs again after a workbench change."""
        try:
            names = Gui.listCommands()
        except Exception:
            return
        known = set(names)
        for name in names:
            if name in self._hooked or not repeatable(name):
                continue
            try:
                actions = [a for a in Gui.Command.get(name).getAction() if isinstance(a, QtGui.QAction)]
            except Exception:
                actions = []
            if not actions:
                continue
            hooked = []
            entries = None
            for action in actions:
                # a group command's entries are commands of their own
                sub = action.objectName()
                if sub not in known:
                    # a Python group command's entries carry no name: found by their text
                    if entries is None:
                        entries = _entries_by_text(name)
                    sub = entries.get(action.text().replace("&", ""), name)
                slot = functools.partial(self._triggered, sub)
                action.triggered.connect(slot)
                hooked.append((action, slot))
            self._hooked[name] = hooked

    def unhook(self):
        """Takes off only this object's connections: FreeCAD's own stay."""
        for hooked in self._hooked.values():
            for action, slot in hooked:
                if alive(action):
                    try:
                        action.triggered.disconnect(slot)
                    except Exception as _fw_err:
                        _fw_log("viewkeys.py:304", _fw_err)
        self._hooked = {}

    def _triggered(self, name, *args):
        self.note(name)

    def note(self, name):
        if repeatable(name):
            try:
                if Gui.Command.get(name) is None:
                    return
            except Exception:
                return
            self.name = name

    def ready(self):
        """The command Enter would run now, or None."""
        name = self.name
        if not name:
            return None
        try:
            command = Gui.Command.get(name)
            return name if command is not None and command.isActive() else None
        except Exception:
            return None

    def run(self):
        name = self.ready()
        if name is None:
            return False
        from . import featureflow
        try:
            if not featureflow.run(name):
                Gui.runCommand(name, 0)
        except Exception as error:
            App.Console.PrintError("FreeCAD: %s failed: %s\n" % (name, error))
        return True


# --------------------------------------------------------------------------- the keys
class ViewKeys(QtCore.QObject):
    """Watches the keys on the active 3D view (the viewer takes the keys, its GL viewport the
    mouse: both are watched, ahead of FreeCAD's own filters)."""

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.mw = shell.window
        self._watched = []
        self._last = 0.0             # time of the last turn
        self._centre = None          # (document, point) the current run of keys turns about
        self.turns = 0               # for checks
        self.fits = 0                # middle double-clicks, for checks
        self.last = LastCommand(self)
        self.wheel = wheelzoom.WheelZoom()
        self.middle = middlemouse.MiddleMouse(self)
        self.mdi = self.mw.findChild(QtWidgets.QMdiArea)
        if self.mdi is not None:
            self.mdi.subWindowActivated.connect(self.attach)
        QtCore.QTimer.singleShot(0, self.attach)
        QtCore.QTimer.singleShot(0, self.last.hook)

    def attach(self, *args):
        """Installing again puts this filter first, ahead of FreeCAD's."""
        self._watched = [w for w in self._watched if alive(w)]
        view = self.shell.view_widget()
        if view is None or not alive(view):
            return
        widgets = [view]
        if hasattr(view, "viewport") and view.viewport() is not None:
            widgets.append(view.viewport())

        # only its keys are watched there, the sheet keeps its own wheel and mouse
        sheets = getattr(self, "_sheet_keys", None)
        if sheets is None:
            sheets = self._sheet_keys = []
        sheets[:] = [w for w in sheets if alive(w)]
        if "View3DInventor" not in view.metaObject().className():
            for g in view.findChildren(QtWidgets.QGraphicsView):
                for w in (g, g.viewport()):
                    if w is not None and w not in widgets:
                        widgets.append(w)
                        if w not in sheets:
                            sheets.append(w)
        for widget in widgets:
            widget.installEventFilter(self)
            if widget not in self._watched:
                self._watched.append(widget)

    def remove(self):
        self.last.unhook()
        self.middle.remove()
        for widget in self._watched:
            if alive(widget):
                widget.removeEventFilter(self)
        self._watched = []
        if self.mdi is not None and alive(self.mdi):
            try:
                self.mdi.subWindowActivated.disconnect(self.attach)
            except Exception as _fw_err:
                _fw_log("viewkeys.py:391", _fw_err)

    def _action(self, event):
        key = event.key()
        mods = event.modifiers() & MODS
        try:        # filterkeys-1126: Enter (Repeat Last Command) and D follow Customize > Keyboard
            from . import filterkeys
            key, mods = filterkeys.logical(key, mods)
        except Exception as _fw_err:
            _fw_log("viewkeys.py:filterkeys", _fw_err)
        if key in ARROWS:
            if mods == Qt.NoModifier:
                return "turn", key, wheelzoom.arrow_step()
            if mods == Qt.ShiftModifier:
                return "turn", key, TURN
            if mods == Qt.AltModifier and key in (Qt.Key_Left, Qt.Key_Right):
                return "roll", key, wheelzoom.arrow_step()
            if mods == Qt.ControlModifier:
                return "pan", key, 0.0
            return None
        if key == Qt.Key_Escape and mods == Qt.NoModifier and self._may_clear():
            return "clear", key, 0.0
        if key == Qt.Key_D and mods == Qt.NoModifier and (self._crumbs_shown() or self._corner_shown()):
            return "crumbs", key, 0.0      # D moves the breadcrumbs and the confirmation corner to the pointer
        if key in ENTER and mods == Qt.NoModifier:
            return self._enter()
        if key in DIGIT_VIEWS and mods == Qt.NoModifier and not contextbar.tool_running(self.shell):
            return "cmd", DIGIT_VIEWS[key], 0.0        # fckeys-1126 (a sketch tool keeps its typed numbers)
        if key in ZOOM_KEYS and mods in (Qt.ControlModifier, Qt.ControlModifier | Qt.ShiftModifier):
            return "cmd", ZOOM_KEYS[key], 0.0
        return None

    def _enter(self):
        """Enter: OK while a feature is being edited, else repeat the last command; never while a
        tool that picks with the mouse runs (Enter is its own then)."""
        if contextbar.tool_running(self.shell):
            return None
        try:
            # fix262: a sketch tool page (Mirror / Offset Entities, Fully Define ...) is open: Enter
            # is its OK (sketchtoolpm). Repeating the last command here opened that command again,
            # which threw the open page's work away (Video walk F15c: Mirror made nothing)
            from . import sketchtoolpm
            page = sketchtoolpm.current()
            if page is not None and alive(page):
                return None
        except Exception as _fw_err:
            _fw_log("viewkeys.py:enter page", _fw_err)
        if contextbar.dialog_open() and contextbar.sketch_in_edit() is None:
            corner = getattr(getattr(self.shell, "overlay", None), "confirm", None)
            if corner is None or not alive(corner):
                return None
            corner.refresh()
            ok = corner.ok_native
            # The PropertyManager look may hide FreeCAD's own button row: the corner's OK still
            # presses it, as a click on the green check does.
            if corner.mode == "dialog" and ok is not None and alive(ok) and ok.isEnabled():
                return "ok", Qt.Key_Return, 0.0
            return None
        if self.last.ready() is not None:
            return "repeat", Qt.Key_Return, 0.0
        return None

    def _corner_shown(self):
        corner = getattr(getattr(self.shell, "overlay", None), "confirm", None)
        return corner is not None and not corner.isHidden()

    def _crumbs_shown(self):
        crumbs = getattr(self.shell, "breadcrumbs", None)
        trail = getattr(crumbs, "trail", None)
        return trail is not None and alive(trail) and not trail.isHidden()

    def _may_clear(self):
        ""

        if contextbar.tool_running(self.shell):
            return False
        if contextbar.sketch_in_edit() is not None:
            if self.shell.tasks_wanted():
                return False         # a sketch tool's PropertyManager is up: its Esc
            try:
                from . import sketchtoolpm
                if sketchtoolpm.current() is not None:


                    return False
            except Exception as _fw_err:
                _fw_log("viewkeys.py:sketch page", _fw_err)
        elif contextbar.dialog_open():
            return False
        try:
            return bool(Gui.Selection.getSelectionEx())
        except Exception:
            return False

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        sheet = obj in (getattr(self, "_sheet_keys", None) or ())
        if sheet:
            return self._sheet_key(event) if t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress) else False
        if t == QtCore.QEvent.Wheel:
            return self.shell.enabled and self.wheel.filter(obj, event, _view())
        if t in middlemouse.MOUSE:
            return self.shell.enabled and self.middle.filter(obj, event, _view())
        if t == QtCore.QEvent.Enter and self.shell.enabled:
            self._take_focus(obj)
            return False
        if t == QtCore.QEvent.MouseButtonDblClick:
            if event.button() == Qt.MiddleButton and not (event.modifiers() & MODS) and self.shell.enabled \
                    and _view() is not None:

                self.middle.double_clicked()
                Gui.SendMsgToActiveView("ViewFit")
                self.fits += 1
                return True
            if event.button() == Qt.MiddleButton and self.shell.enabled:
                return self.middle.double_with_keys(obj, event, _view())
            return False
        if t not in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress) or not self.shell.enabled:
            return False
        action = self._action(event)
        if action is None or _view() is None:
            return False
        if t == QtCore.QEvent.ShortcutOverride:
            # The key goes to the view, not to a menu shortcut
            event.accept()
            return True
        kind, key, angle = action
        if kind == "pan":
            return False             # FreeCAD pans on an arrow key itself
        if kind == "clear":
            Gui.Selection.clearSelection()
            return True
        if kind == "crumbs":
            # D: the confirmation corner (while a feature or sketch is being edited) and the breadcrumbs
            # (while something is picked) come to the pointer; a second D sends them back
            corner = getattr(self.shell.overlay, "confirm", None)
            if corner is not None:
                corner.to_pointer()
            self.shell.breadcrumbs.to_pointer()
            return True
        if kind == "ok":
            self.shell.overlay.confirm.ok.click()
            return True
        if kind == "repeat":
            QtCore.QTimer.singleShot(0, self.last.run)
            return True
        if kind == "cmd":           # fckeys-1126
            QtCore.QTimer.singleShot(0, functools.partial(Gui.runCommand, key, 0))
            return True
        try:
            self.turn(key, angle, kind == "roll")
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: view keys: %s\n" % error)
        return True

    def _sheet_key(self, event):
        ""
        if not self.shell.enabled or _view() is not None:
            return False
        action = self._action(event)
        if action is None or action[0] != "repeat":
            return False
        if event.type() == QtCore.QEvent.ShortcutOverride:
            event.accept()
            return True
        QtCore.QTimer.singleShot(0, self.last.run)
        return True

    def _take_focus(self, obj):
        ""


        focus = QtWidgets.QApplication.focusWidget()
        if focus is not None and focus.isVisible() and (isinstance(focus, TYPING) or (
                isinstance(focus, QtWidgets.QComboBox) and focus.isEditable())):
            return
        if QtWidgets.QApplication.activePopupWidget() is not None or QtWidgets.QApplication.activeModalWidget() is not None:
            return
        if QtWidgets.QApplication.activeWindow() is not self.mw:
            return
        view = self.shell.view_widget()
        if view is not None and alive(view) and not view.hasFocus():
            view.setFocus(Qt.MouseFocusReason)

    def turn(self, key, angle, roll=False):
        """Turns the view at once (a held key repeats), about the model's middle."""
        view = _view()
        if view is None:
            return
        doc = Gui.ActiveDocument.Document.Name
        now = time.monotonic()
        camera = Camera(view.getCamera())
        if self._centre is None or self._centre[0] != doc or now - self._last > BURST:
            self.shell.push_view()
            self._centre = (doc, model_centre(camera))
        self._last = now
        centre = self._centre[1]
        rotation = camera.rotation
        q = turn_rotation(rotation, key, angle, roll)
        position = centre + q.multVec(camera.position - centre)
        view.setCamera(camera.with_pose(position, q.multiply(rotation)))
        self.turns += 1
