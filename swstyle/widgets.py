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
from PySide import QtCore, QtGui, QtWidgets

from . import catalog, checkstate, featureflow, icons, style


FLYOUT_LAST = "User parameter:BaseApp/Preferences/Mod/FreeWorks/FlyoutLast"


def last_flyout_pick(key, flyout_keys):
    try:
        saved = App.ParamGet(FLYOUT_LAST).GetString(key, "")
    except Exception:
        return key
    return saved if saved and saved in flyout_keys and saved in catalog.BY_KEY else key

T = style.T
# addon calls whose enabled state is their own even though they borrow a FreeCAD command's icon
OWN_STATE = ("rollback",)

Qt = QtCore.Qt

# Colours come from the theme's tokens (style.T: T.text, T.hover, ...), read when painting, so
# a theme change repaints every widget in its new colours.


ui_scale = style.ui_scale


def scaled(value, k=None):
    ""
    return int(round(value * (ui_scale() if k is None else k)))


def ui_font(bold=False, points=9.0):
    font = QtGui.QFont("Segoe UI")
    font.setPointSizeF(points)
    font.setBold(bold)
    return font


def colour(value):
    """QColor for a theme token name ("hover") or a "#rrggbb" string, or the QColor given."""
    if isinstance(value, QtGui.QColor):
        return value
    if isinstance(value, str) and not value.startswith("#"):
        return getattr(T, value)
    return QtGui.QColor(value)


def alive(obj):
    if obj is None:
        return False
    try:
        obj.objectName()
        return True
    except (RuntimeError, AttributeError):
        return False


def release_python_hooks():
    ""




    import gc
    app = QtWidgets.QApplication.instance()
    if app is None:
        return 0
    count = 0
    for obj in gc.get_objects():
        try:
            if not isinstance(obj, QtCore.QObject) or not alive(obj):
                continue
            module = type(obj).__module__ or ""
            if isinstance(obj, QtCore.QTimer):
                obj.stop()
                count += 1
                continue
            if module.startswith(__package__ or "swstyle"):
                app.removeEventFilter(obj)
                count += 1
        except Exception as _fw_err:
            _fw_log("widgets.py:93", _fw_err)
    return count


def popup_menu(menu, pos, on_hide=None):
    ""

    def hidden():
        if on_hide is not None:
            on_hide()
        QtCore.QTimer.singleShot(0, menu.deleteLater)
    menu.aboutToHide.connect(hidden)
    menu.popup(pos)
    return menu


class FlyoutMenu(QtWidgets.QMenu):
    ""




    ICON, LEFT, TEXT_X, ROW, RIGHT = 20, 4, 32, 24, 56

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWFlyout")

    def _k(self):
        return ui_scale()

    def _fit(self):
        k = self._k()
        fm = QtGui.QFontMetrics(self.font())
        widest = max([fm.horizontalAdvance(a.text().replace("&", "")) for a in self.actions() if not a.isSeparator()] + [0])
        self.setMinimumWidth(int(round((self.TEXT_X + self.RIGHT) * k + widest)))

    def showEvent(self, event):
        self._fit()
        super().showEvent(event)

    def paintEvent(self, event):
        k = self._k()
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), T.base)
        p.setPen(hairline_pen(T.line_mid))
        p.drawRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        fm = p.fontMetrics()
        n = int(round(self.ICON * k))
        for act in self.actions():
            if not act.isVisible():
                continue
            r = self.actionGeometry(act)
            if act.isSeparator():
                p.setPen(hairline_pen(T.tab))
                y = r.center().y() + 0.5
                p.drawLine(QtCore.QPointF(r.left() + 4 * k, y), QtCore.QPointF(r.right() - 4 * k, y))
                continue
            enabled = act.isEnabled()
            if act is self.activeAction() and enabled:
                p.fillRect(QtCore.QRect(1, r.top(), self.width() - 2, r.height()), T.menu_hover)
            box = QtCore.QRect(int(round(self.LEFT * k)), r.top() + (r.height() - n) // 2, n, n)
            icon = act.icon()
            if icon is not None and not icon.isNull():
                style.paint_icon(p, icon, box, Qt.AlignCenter, QtGui.QIcon.Normal if enabled else QtGui.QIcon.Disabled)
            elif act.isCheckable() and act.isChecked():
                p.setPen(QtGui.QPen(T.text, 1.6 * k))
                c = QtCore.QPointF(box.center())
                p.drawPolyline([c + QtCore.QPointF(-5 * k, 0), c + QtCore.QPointF(-1.5 * k, 3.5 * k), c + QtCore.QPointF(5 * k, -4 * k)])
            if act.isCheckable() and act.isChecked() and icon is not None and not icon.isNull():
                p.setPen(hairline_pen(T.hover_line))
                p.drawRect(QtCore.QRectF(box).adjusted(-1.5, -1.5, 1.5, 1.5))
            p.setPen(T.text if enabled else T.text_disabled)
            text = act.text()
            shortcut = ""
            if "\t" in text:
                text, shortcut = text.split("\t", 1)
            tr = QtCore.QRect(int(round(self.TEXT_X * k)), r.top(), r.width(), r.height())
            p.drawText(tr, int(Qt.AlignLeft | Qt.AlignVCenter | Qt.TextShowMnemonic), text)
            if shortcut:
                p.drawText(r.adjusted(0, 0, -int(round(12 * k)), 0), int(Qt.AlignRight | Qt.AlignVCenter), shortcut)
            if act.menu() is not None:
                draw_arrow_right(p, r.right() - 8 * k, r.center().y() + 0.5, T.arrow if enabled else T.arrow_disabled, 5 * k)
        p.end()


def draw_arrow_right(painter, cx, cy, color, width=5.0):
    half = width / 2.0
    path = QtGui.QPainterPath()
    path.moveTo(cx - half / 2.0, cy - half)
    path.lineTo(cx - half / 2.0, cy + half)
    path.lineTo(cx + half / 2.0, cy)
    path.closeSubpath()
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)
    painter.restore()


def draw_arrow(painter, cx, cy, color, width=5.0):
    ""
    half = width / 2.0
    path = QtGui.QPainterPath()
    path.moveTo(cx - half, cy - half / 2.0)
    path.lineTo(cx + half, cy - half / 2.0)
    path.lineTo(cx, cy + half / 2.0)
    path.closeSubpath()
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)
    painter.restore()


def hairline_pen(color):
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setCosmetic(True)
    pen.setWidth(1)
    return pen


def device_rect(widget, rect):
    """Rect snapped to physical pixels for 1-device-pixel frames."""
    return QtCore.QRectF(rect).adjusted(0.25, 0.25, -0.25, -0.25)


# --------------------------------------------------------------------------- binding
# buttons whose picture follows the style in use (the five styles of their flyout)
STYLE_BUTTONS = {"DisplayStyle": ("ShadedEdges", "Shaded", "HiddenLinesVisible", "HiddenLinesRemoved", "Wireframe")}


def _offers(key, native, takes=False):
    """A CAM, Flow Simulation or MBD button whose command cannot act yet: on, it offers what it needs (setupoffer)."""
    try:
        from . import setupoffer
        return setupoffer.takes(key, native) if takes else setupoffer.enabled(key, native)
    except Exception as _fw_err:
        _fw_log("widgets.py:offers", _fw_err)
        return False



# empty Part2 and Part9 with no sketch open). solidfirst-1126: NO DEAD CONTROLS overrides that. In an empty part
# every one of them opens its own page (the cuts, Hole, Fillet... open their flow, or solidfirstlive's "a solid
# comes first" page; the sketch tools start a sketch first), on the ribbon and on the S-key bar alike, so only
# the two that do nothing without an open sketch stay grey (bench, greykeys check).
NEEDS_SOLID = frozenset()
NEEDS_PROFILE = frozenset()
NEEDS_PROFILES = frozenset()
NEEDS_SOLID_IN_SKETCH = frozenset()
NOT_IN_2D_SKETCH = frozenset(("OffsetOnSurface", "Sketch3DPlane"))   # cmgrey3-1121 + nodead-1126: 3D sketch tools, grey in a 2D sketch
NEEDS_OPEN_SKETCH = frozenset()   # sketchfirst-1126: Repair Sketch and Sketch Chamfer open a "open a sketch first" page
_PART_STATE = [None, 0.0, None]     # (doc name, object count), time read, (is part, has solid, has sketch)


def _part_state():
    """(is part, has solid, number of sketches) for the active document; None when there is none. Read at most every
    0.3 s and again whenever the document's object count changes."""
    import time
    doc = App.ActiveDocument
    if doc is None:
        return None
    key = (doc.Name, len(doc.Objects), getattr(doc, "UndoCount", 0))
    now = time.time()
    if _PART_STATE[0] == key and now - _PART_STATE[1] < 0.3:
        return _PART_STATE[2]
    part = solid = False
    sketch = 0
    try:
        types = [o.TypeId for o in doc.Objects]
        part = not any(t.startswith(("TechDraw::", "Assembly::")) for t in types)
        sketch = sum(1 for t in types if t == "Sketcher::SketchObject")
        for o in doc.Objects:
            shape = getattr(o, "Shape", None)
            if shape is not None and o.isDerivedFrom("Part::Feature") and not o.isDerivedFrom("Part::Part2DObject"):
                try:
                    if shape.Solids:
                        solid = True
                        break
                except Exception:
                    continue
    except Exception as _fw_err:
        _fw_log("widgets.py:cmgrey", _fw_err)
        part = False
    _PART_STATE[:] = [key, now, (part, solid, sketch)]
    return _PART_STATE[2]


def sw_greyed(key):
    ""
    if not any(key in group for group in (NEEDS_SOLID, NEEDS_PROFILE, NEEDS_PROFILES, NEEDS_OPEN_SKETCH,
                                          NEEDS_SOLID_IN_SKETCH, NOT_IN_2D_SKETCH)):
        return False
    state = _part_state()
    if state is None or not state[0]:
        return False
    part, solid, sketch = state
    if key in NEEDS_OPEN_SKETCH:
        if featureflow.editing_sketch() is not None:
            return False
        try:
            from . import sketch3d
            if sketch3d.editing():
                return False
        except Exception as _fw_err:
            _fw_log("widgets.py:cmgrey-3d", _fw_err)
        return True
    if key in NOT_IN_2D_SKETCH:
        return featureflow.editing_sketch() is not None
    if key in NEEDS_SOLID:
        if key == "Fillet" and not solid:

            # while the part has a surface body, as the click then opens that page (sfvar440 on the PC)
            try:
                from . import solidfirstlive
                if solidfirstlive.has_surface(App.ActiveDocument):
                    return False
            except Exception as _fw_err:
                _fw_log("widgets.py:cmgrey-surface", _fw_err)
        return not solid
    if key in NEEDS_SOLID_IN_SKETCH:
        return not solid and featureflow.editing_sketch() is not None
    if key in NEEDS_PROFILES:
        return not (solid or sketch >= 2)
    return not (solid or sketch)


# greycm-1126: what to do first, for the buttons sw_greyed keeps from running
SW_GREY_TEXTS = {
    "OffsetOnSurface": "Offset On Surface works in a 3D sketch. Exit the 2D sketch first, or start a 3D Sketch.",
    "Sketch3DPlane": "3D Sketch On Plane works in a 3D sketch. Exit the 2D sketch first, or start a 3D Sketch.",
}


def sw_grey_tell(key):
    """notready's Message page; over an open sketch (its own page stays) a tip at the pointer and the status bar."""
    text = SW_GREY_TEXTS.get(key, "Exit the 2D sketch first, or start a 3D Sketch.")
    try:
        from . import notready
        if notready.show(key, text=text):
            return
    except TypeError:       # notready before greyrows-1126: no text of its own
        pass
    except Exception as _fw_err:
        _fw_log("widgets.py:greycm", _fw_err)
    try:
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), text)
        Gui.getMainWindow().statusBar().showMessage(text, 8000)
    except Exception as _fw_err:
        _fw_log("widgets.py:greycm-tip", _fw_err)


def _pm_open():
    """pmlive-1120: a PropertyManager (FreeCAD task dialog) is open, other than an edited sketch's
    (featureflow handles the sketch: a feature closes it and starts)."""
    try:
        if not Gui.Control.activeDialog():
            return False
        return featureflow.editing_sketch() is None
    except Exception:
        return False


class Binding(QtCore.QObject):
    """One catalog entry bound to a real FreeCAD command (or an addon action)."""

    changed = QtCore.Signal()

    def __init__(self, cmd, shell):
        super().__init__(shell)
        self.cmd = cmd
        self.shell = shell
        self.native = None
        self.action = None
        self.info = {}
        self._enabled = False
        self._checked = False
        self.resolve()
        self.update_state()

    @property
    def implemented(self):
        from . import smengine

        return bool(self.native or self.cmd.call) and (
            not smengine.is_sheet_metal_command(self.cmd.key) or smengine.enabled()
        )

    def resolve(self):
        if self.action is not None and alive(self.action):
            return
        self.action = None
        for name in self.cmd.natives:
            try:
                command = Gui.Command.get(name)
            except Exception:
                command = None
            if command is None:
                continue
            self.native = name
            try:
                self.info = command.getInfo() or {}
            except Exception:
                self.info = {}
            try:
                actions = [a for a in command.getAction() if isinstance(a, QtGui.QAction)]
            except Exception:
                actions = []
            if actions:
                self.action = actions[0]
                try:
                    self.action.changed.connect(self.update_state)
                except Exception as _fw_err:
                    _fw_log("widgets.py:273", _fw_err)
            return

    def update_state(self):
        enabled, checked = False, False
        if self.cmd.call and (not self.cmd.natives or self.cmd.call in OWN_STATE):
            enabled = self.shell.special_enabled(self.cmd.call)
            checked = self.shell.special_checked(self.cmd.call)
        elif self.action is not None and alive(self.action):
            enabled = self.action.isEnabled() or featureflow.enabled(self.native) or _offers(self.cmd.key, self.native)
            checked = self.action.isCheckable() and self.action.isChecked()
            if checkstate.known(self.native):
                checked = checkstate.checked(self.native)
        elif self.native:
            try:
                enabled = bool(Gui.Command.get(self.native).isActive())
            except Exception:
                enabled = False
            enabled = enabled or featureflow.enabled(self.native) or _offers(self.cmd.key, self.native)
            # addon toggles (View Planes...) have no QAction until a FreeCAD menu holds them
            checked = checkstate.checked(self.native)

        # another command closes the open page and starts it. A command that refuses only because a page is

        pm = _pm_open()
        self._pm_override = False
        if not pm:
            self._free_enabled = enabled
        elif not enabled and self.native and not self.cmd.call and getattr(
                self, "_free_enabled", App.ActiveDocument is not None and self.native.startswith(("SWStyle_", "FreeWorks_"))):
            enabled = self._pm_override = True
        self._sw_grey = False
        if sw_greyed(self.cmd.key):
            enabled = self._sw_grey = True     # greycm-1126: NO DEAD CONTROLS: live, a click says what to do first
        self._notready = False
        if (not enabled and self.native and not self.cmd.call and App.ActiveDocument is not None
                and self.cmd.key not in CommandButton.IDLE_HIDDEN and not sw_greyed(self.cmd.key)):
            try:        # notready-1126: no greyed button; a click that finds the command still inactive opens a page
                from . import notready
                if notready.exists(self.native):
                    enabled = self._notready = True
            except Exception as _fw_err:
                _fw_log("widgets.py:notready", _fw_err)
        shown = self._style_key() if self.cmd.key in STYLE_BUTTONS else None
        if enabled != self._enabled or checked != self._checked or shown != getattr(self, "_shown", None):
            self._enabled, self._checked, self._shown = enabled, checked, shown
            self.changed.emit()

    def _style_key(self):
        ""
        for key in STYLE_BUTTONS[self.cmd.key]:
            try:
                b = self.shell.binding(key)
                b.update_state()
                if b.checked:
                    return key
            except Exception as _fw_err:
                _fw_log("widgets.py:308", _fw_err)
        return None

    def poll(self):
        # A workbench switch can delete FreeCAD's QAction under us: find the new one.
        if self.cmd.natives and (self.action is None or not alive(self.action)):
            self.resolve()
        if self.action is None or self.cmd.call or featureflow.handles(self.native):
            self.update_state()

    @property
    def enabled(self):
        return self._enabled

    @property
    def checked(self):
        return self._checked

    def icon(self):
        shown = getattr(self, "_shown", None)
        if shown:
            try:
                return self.shell.binding(shown).icon()
            except Exception as _fw_err:
                _fw_log("widgets.py:332", _fw_err)
        icon = icons.family(self.cmd.icon) if self.cmd.icon else QtGui.QIcon()
        if not icons.paints(icon):

            # (resources/icons-drawn, drawnicons-1119)
            for own in (icons.family("FW_" + self.cmd.key), icons.drawn(self.cmd.key)):
                if icons.paints(own):
                    icon = own
                    break
        if not icons.paints(icon) and self.action is not None and alive(self.action):
            icon = self.action.icon()
        if not icons.paints(icon) and self.info and self.info.get("pixmap"):
            # a FreeCAD command not in any of FreeCAD's menus has no QAction yet: its own picture
            try:
                icon = Gui.getIcon(self.info["pixmap"])
            except Exception as _fw_err:
                _fw_log("widgets.py:341", _fw_err)
        if not icons.paints(icon):

            own = icons.family("FW_" + self.cmd.key)
            if icons.paints(own):
                icon = own
        if not icons.paints(icon):
            # no picture anywhere (no icon pack, a Python command without a Pixmap): a plain tile with
            # the command's initials, so no button is blank
            icon = icons.initials(self.cmd.label)
        return icon

    def tooltip(self):
        cmd = self.cmd
        # Customize > Toolbars > Tooltips: none, small (the name), or large (name and help)
        try:
            from . import customizedlg
            if not customizedlg.option("ShowTooltips"):
                return ""
            if customizedlg.option("TooltipStyle") == 2:
                return cmd.label
        except Exception as _fw_err:
            _fw_log("widgets.py:363", _fw_err)
        parts = ["<b>%s</b>%s" % (cmd.label, self._key_text())]
        if cmd.tip:
            parts.append(cmd.tip)
        menu = self.info.get("menuText") if self.info else None
        if self.native and menu:
            pass
        elif not self.implemented:
            parts.append("<span style='color:%s'>Not available in FreeCAD yet.</span>" % T.hex("text_dim"))
        text = "<br>".join(parts)
        try:

            # "without images" keeps the text alone
            from . import customizedlg
            if customizedlg.option("TooltipStyle") == 0:
                path = _tip_picture(cmd.key, self.icon())
                if path:
                    text = ("<table cellspacing=0 cellpadding=2><tr><td valign=top><img src='%s' width=32 height=32></td>"
                            "<td valign=top>%s</td></tr></table>" % (path, text))
        except Exception as _fw_err:
            _fw_log("widgets.py:tip-image", _fw_err)
        return text

    def _key_text(self):
        ""
        try:
            key = Gui.Command.get(self.native).getShortcut() if self.native else ""
        except Exception:
            key = ""
        if not key:
            return ""
        key = QtGui.QKeySequence(key).toString(QtGui.QKeySequence.NativeText) or key
        return " (%s)" % key.replace("<", "&lt;")

    def _after_pm(self, tries):
        if _pm_open() and tries < 40:
            QtCore.QTimer.singleShot(50, lambda: self._after_pm(tries + 1))
            return
        self._pm_override = False
        if not _pm_open():
            self.update_state()
            if self._enabled:
                self.run()

    def run(self):
        if not self._enabled:
            # nothing polls the bindings of the Orientation box or the View Selector, and an addon
            # command without a QAction sends no change signal: its state now
            self.update_state()
        if not self._enabled:
            return
        if getattr(self, "_sw_grey", False) and sw_greyed(self.cmd.key):
            sw_grey_tell(self.cmd.key)
            QtCore.QTimer.singleShot(0, self.update_state)
            return
        if getattr(self, "_pm_override", False):
            # refnest: Plane, Axis, Point, Coordinate System run over an open feature page and go back to it

            try:
                from . import refnest
                if refnest.busy():
                    refnest.cancel_nested()
                if refnest.nest(self.native):
                    QtCore.QTimer.singleShot(0, self.update_state)
                    return
            except Exception as _fw_err:
                _fw_log("widgets.py:refnest", _fw_err)
            # pmlive-1120: the open page closes (its Cancel), then this command starts
            from . import pmconfirm
            if pmconfirm.cancel():
                self._after_pm(0)
                return
        call = self.cmd.call
        if call and self.shell.special(call, self):
            return
        if featureflow.run(self.native):
            QtCore.QTimer.singleShot(0, self.update_state)
            return
        if _offers(self.cmd.key, self.native, takes=True):
            from . import setupoffer      # CAM / Flow / MBD: picks what the command needs, or offers to make it
            setupoffer.run(self.cmd.key, self.native)
            QtCore.QTimer.singleShot(0, self.update_state)
            return
        if getattr(self, "_notready", False):
            from . import notready
            if not notready.can_act(self.native):
                notready.show(self.cmd.key)       # notready-1126: says what it works on and what to do first
                QtCore.QTimer.singleShot(0, self.update_state)
                return
        if self.action is not None and alive(self.action):
            self.action.trigger()
        elif self.native:
            try:
                Gui.runCommand(self.native, 0)
            except Exception as error:
                App.Console.PrintError("FreeCAD: %s failed: %s\n" % (self.native, error))
        QtCore.QTimer.singleShot(0, self.update_state)


# --------------------------------------------------------------------------- buttons
_TIP_ICONS = {}


def _with_icon(html, icon, key):
    """The tooltip text with the command's picture beside it (a table: Qt tooltips are rich text)."""
    try:
        if not icons.paints(icon):
            return html
        path = _TIP_ICONS.get(key)
        if path is None:
            import os
            import re
            import tempfile
            folder = os.path.join(tempfile.gettempdir(), "swstyle-tips")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, re.sub(r"[^A-Za-z0-9_.-]", "_", str(key)) + ".png")
            if not icon.pixmap(32, 32).save(path):
                return html
            path = path.replace("\\", "/")
            _TIP_ICONS[key] = path
        return ("<table cellspacing='0' cellpadding='0'><tr><td valign='top' style='padding-right:6px'>"
                "<img src='%s' width='32' height='32'></td><td valign='top'>%s</td></tr></table>" % (path, html))
    except Exception:
        return html


def _tip_style():
    """Customize > Toolbars > Tooltips: 0 large with images, 1 large without images, 2 small."""
    try:
        from . import customizedlg
        return int(customizedlg.option("TooltipStyle") or 0)
    except Exception:
        return 0


def tip_picture(key):
    ""

    try:
        from . import paths
        path = paths.ADDON_DIR / "swstyle" / "resources" / "tips" / ("%s.png" % key)
        return str(path).replace("\\", "/") if path.is_file() else None
    except Exception:
        return None


def _tip_card(html, key):
    ""

    path = tip_picture(key)
    if not path:
        return None
    head, _, rest = html.partition("<br>")
    return ("<table width='284' cellspacing='0' cellpadding='0'><tr><td>%s</td></tr>"
            "<tr><td style='padding-top:4px;padding-bottom:4px'><img src='%s' width='280' height='160'></td></tr>"
            "<tr><td>%s</td></tr></table>" % (head, path, rest))


_HOVER = {"text": None}


def _hover_status(button, on):
    ""

    try:
        mw = button.window()
        bar = mw.statusBar() if hasattr(mw, "statusBar") else None
        if bar is None:
            import FreeCADGui
            bar = FreeCADGui.getMainWindow().statusBar()
        now = bar.currentMessage()
        if on:
            cmd = button.binding.cmd
            text = (cmd.tip or cmd.label or "").strip().split("\n")[0]
            if text and (not now or now == _HOVER["text"]):
                bar.showMessage(text, 0)
                _HOVER["text"] = text
        elif _HOVER["text"] is not None and now == _HOVER["text"]:
            bar.clearMessage()
            _HOVER["text"] = None
    except Exception as _fw_err:
        _fw_log("widgets.py:460", _fw_err)


_TIP_PICTURES = {}


def _tip_picture(key, icon):
    """A 32 px copy of a command's icon in the user cache, for the large tooltip's picture (Qt's
    tooltips show pictures from files only). None when the icon draws nothing."""
    if key in _TIP_PICTURES:
        return _TIP_PICTURES[key]
    path = None
    try:
        if icons.paints(icon):
            import os
            folder = os.path.join(App.getUserCachePath(), "SWStyleTips")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "".join(ch if ch.isalnum() else "_" for ch in key) + ".png")
            if not icon.pixmap(64, 64).save(path, "PNG"):
                path = None
            else:
                path = path.replace("\\", "/")
    except Exception as _fw_err:
        _fw_log("widgets.py:tip-picture", _fw_err)
        path = None
    _TIP_PICTURES[key] = path
    return path


class CommandButton(QtWidgets.QWidget):
    """Painted button. kind: large | stack | grid | qat | hud | menu-only."""

    ICON = 20

    # at 20 px the icons on the big Sketch / Features buttons read as text-only buttons in the dark theme
    LARGE_ICON = 26

    # a button with nothing to act on yet (no markup on the sheet...): hidden from its tab, not greyed (NO DEAD
    # CONTROLS); the tab closes up round it and it comes back once its command can act
    IDLE_HIDDEN = {"DrawMarkupEraser", "DrawMarkupSelect", "DrawZoomToMarkup",
                   "OffsetOnSurface",   # fix230 (look audit K6): 3D sketch only, so off the tab in a 2D sketch
                   "Sketch3D", "Sketch3DOnPlane",   # nodead-1126: they cannot start inside a 2D sketch: off, not grey
                   "Sketch3DPlane"}   # nodead-1126: the Sketch tab's Plane cell is a 3D sketch tool too


    # COMPACT (cmgr-1119): Use Large Buttons with Text off, every CommandManager button a small icon in one row
    FULL, NO_TEXT, COMPACT = 0, 1, 2

    def __init__(self, shell, key, flyout=None, kind="large", parent=None):
        super().__init__(parent)
        self.shell = shell
        self.kind = kind
        self.flyout_keys = tuple(flyout or ())
        if kind == "grid" and self.flyout_keys and self.flyout_keys[0] == key:
            key = last_flyout_pick(key, self.flyout_keys)
        self.binding = shell.binding(key)
        self.binding.changed.connect(self.update)
        if key in self.IDLE_HIDDEN:
            self.binding.changed.connect(self._idle_changed)
        self._hover = None       # None | "main" | "arrow"
        self._pressed = None
        self._menu_open = False
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFont(ui_font())
        self.setToolTip(self.binding.tooltip())
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self._lines = self.binding.cmd.caption.split("\n") if kind == "large" else [self.binding.cmd.label]
        self.k = ui_scale()
        self.icon = scaled(self.ICON, self.k)
        self.large_icon = scaled(self.LARGE_ICON, self.k)     # bigicons-1127
        self.show_mode = self.FULL

    def s(self, value):
        ""
        return value * self.k

    def idle(self):
        """Hidden from its tab while its command has nothing to act on (IDLE_HIDDEN)."""
        return self.binding.cmd.key in self.IDLE_HIDDEN and not self.binding.enabled

    def _idle_changed(self):
        if self.idle() == self.isHidden():
            return
        w = self.parentWidget()
        while w is not None and not hasattr(w, "_layout_pages"):
            w = w.parentWidget()
        if w is not None:
            QtCore.QTimer.singleShot(0, w._layout_pages)
        elif self.idle():
            self.hide()

    def set_show_mode(self, mode):
        """FULL: icon and text; NO_TEXT: the icon alone (large and stack buttons)."""
        if mode != self.show_mode:
            self.show_mode = mode
            self.updateGeometry()
            self.update()

    def shows_text(self):
        return self.show_mode == self.FULL

    def shape(self):
        """How the button is drawn: a large or stacked CommandManager button drawn small when COMPACT."""
        if self.show_mode == self.COMPACT and self.kind in ("large", "stack"):
            return "grid"
        return self.kind

    # -- sizing ----------------------------------------------------------------------
    def has_arrow(self):
        if self.flyout_keys:
            return True
        return self.binding.cmd.call in ("menu", "scene_menu")

    def sizeHint(self):
        fm = QtGui.QFontMetrics(self.font())
        s = self.s
        size = lambda w, h: QtCore.QSize(int(round(w)), int(round(h)))
        if self.shape() == "grid":
            return size(s(33) if self.has_arrow() else s(24), s(23))
        if self.kind == "large":
            if not self.shows_text():
                return size(self.large_icon + s(10), s(70))
            text = max([fm.horizontalAdvance(line) for line in self._lines] + [self.large_icon + s(4)])
            return QtCore.QSize(int(text + s(6) + 0.999), int(round(s(70))))
        if self.kind == "stack":
            if not self.shows_text():
                return size(s(2) + self.icon + (s(13) if self.has_arrow() else s(2)), s(23))
            text = fm.horizontalAdvance(self._lines[0])
            arrow = s(14) if self.has_arrow() else s(4)
            return size(s(2) + self.icon + s(4) + text + arrow, s(23))
        if self.kind == "grid":
            return size(s(33) if self.has_arrow() else s(24), s(23))
        if self.kind == "qat":
            return size(s(28) + (s(11) if self.has_arrow() else 0), s(30))
        if self.kind == "hud":
            return size(s(24) + (s(9) if self.has_arrow() else 0), s(24))
        return size(s(24), s(24))

    def minimumSizeHint(self):
        return self.sizeHint()

    # -- geometry of the two click areas ---------------------------------------------
    def arrow_rect(self):
        if not self.has_arrow():
            return QtCore.QRect()
        r = self.rect()
        s = lambda v: int(round(self.s(v)))
        if self.shape() == "grid":
            return QtCore.QRect(s(22), 0, r.width() - s(22), r.height())
        if self.kind == "large":
            return QtCore.QRect(0, s(54), r.width(), r.height() - s(54))
        if self.kind == "stack":
            return QtCore.QRect(r.width() - s(12), 0, s(12), r.height())
        if self.kind == "grid":
            return QtCore.QRect(s(22), 0, r.width() - s(22), r.height())
        if self.kind == "qat":
            return QtCore.QRect(r.width() - s(11), 0, s(11), r.height())
        if self.kind == "hud":
            return QtCore.QRect(r.width() - s(9), 0, s(9), r.height())
        return QtCore.QRect()

    def main_rect(self):
        arrow = self.arrow_rect()
        if arrow.isNull():
            return self.rect()
        r = self.rect()
        if self.shape() == "large":
            return QtCore.QRect(0, 0, r.width(), arrow.top())
        return QtCore.QRect(0, 0, arrow.left(), r.height())

    def _area(self, pos):
        arrow = self.arrow_rect()
        if not arrow.isNull() and arrow.contains(pos):
            return "arrow"
        return "main"

    # -- events ------------------------------------------------------------------------
    def event(self, event):
        if event.type() == QtCore.QEvent.ToolTip:
            tip = self.binding.tooltip()
            if "<br>" in tip and _tip_style() == 0:


                # look-audit tipcard-1120: tooltip() already set the picture beside the text, so the card is built from the
                # text alone (cutting the picture's table at <br> broke the card's layout) and no second picture
                import re as _re
                inner = _re.match(r"^<table[^>]*><tr><td[^>]*><img [^>]*></td><td[^>]*>(.*)</td></tr></table>$", tip, _re.S)
                plain = inner.group(1) if inner else tip
                card = _tip_card(plain, self.binding.cmd.key)
                tip = card or (tip if inner else _with_icon(tip, self.binding.icon(), self.binding.cmd.key))
            self.setToolTip(tip)
        return super().event(event)

    def enterEvent(self, event):
        self.update()
        _hover_status(self, True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = None
        self.update()
        _hover_status(self, False)
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        area = self._area(event.position().toPoint())
        if area != self._hover:
            self._hover = area
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self._pressed = self._area(event.position().toPoint())
        self.update()
        if self._pressed == "main" and self._eye():
            return
        if self._pressed == "arrow" or (self.binding.cmd.call in ("menu", "scene_menu")):
            self._pressed = "arrow"
            self.show_flyout()

    def _eye(self):
        ""

        return self.kind == "hud" and self.binding.cmd.key == "HideShowItems"

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(event)
        pressed, self._pressed = self._pressed, None
        self.update()
        if pressed == "main" and self.rect().contains(event.position().toPoint()):
            if self._eye():
                Gui.runCommand("SWStyle_HideAllTypes")
                return
            self.binding.run()

    def show_flyout(self):
        menu = self.shell.build_flyout(self)
        if menu is None or menu.isEmpty():
            self._pressed = None
            self.update()
            return
        self._menu_open = True
        self.update()
        if self.kind in ("large",):
            pos = self.mapToGlobal(QtCore.QPoint(0, self.height()))
        else:
            pos = self.mapToGlobal(QtCore.QPoint(0, self.height()))
        popup_menu(menu, pos, self._flyout_hidden)

    def _flyout_hidden(self):
        if alive(self):
            self._menu_open = False
            self._pressed = None
            self._hover = None
            self.update()

    # -- painting ----------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        enabled = self.binding.enabled
        hover = self.underMouse() and enabled
        down = self._pressed is not None or self._menu_open
        checked = self.binding.checked
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if checked or (down and self._pressed == "main"):
            self._frame(painter, r, T.down, T.down_line)
        elif hover or self._menu_open:
            self._frame(painter, r, T.hover, T.hover_line)
            if self.has_arrow() and self.shape() != "large":
                a = QtCore.QRectF(self.arrow_rect())
                painter.setPen(hairline_pen(T.hover_line))
                painter.drawLine(QtCore.QPointF(a.left() + 0.5, r.top()), QtCore.QPointF(a.left() + 0.5, r.bottom()))
        mode = QtGui.QIcon.Normal if enabled else QtGui.QIcon.Disabled
        icon = self.binding.icon()
        painter.setFont(self.font())
        painter.setPen(T.text if enabled else T.text_disabled)
        arrow_color = T.arrow if enabled else T.arrow_disabled
        k = self.shape()
        s = self.s
        n = self.large_icon if k == "large" else self.icon     # bigicons-1127
        box = lambda x, y: QtCore.QRect(int(round(x)), int(round(y)), n, n)
        arrow = s(5)
        if k == "large":
            x = (self.width() - n) / 2.0
            if not self.shows_text():
                # the icon alone, a little above the middle, the flyout arrow where it always is
                style.paint_icon(painter, icon, box(x, s(19)), Qt.AlignCenter, mode)
            else:
                # bigicons-1127: the 26 px icon at the top, the text close under it, the flyout arrow kept clear
                style.paint_icon(painter, icon, box(x, s(2)), Qt.AlignCenter, mode)
                baseline = s(40)
                for line in self._lines[:3]:
                    w = painter.fontMetrics().horizontalAdvance(line)
                    painter.drawText(QtCore.QPointF((self.width() - w) / 2.0, baseline), line)
                    baseline += s(14)
            if self.has_arrow():
                draw_arrow(painter, self.width() / 2.0, s(63), arrow_color, arrow)
        elif k == "stack":
            style.paint_icon(painter, icon, box(s(2), s(1)), Qt.AlignCenter, mode)
            if self.shows_text():
                painter.drawText(QtCore.QPointF(s(2) + n + s(4), s(16)), self._lines[0])
            if self.has_arrow():
                draw_arrow(painter, self.width() - s(6.5), s(11.5), arrow_color, arrow)
        elif k == "grid":
            style.paint_icon(painter, icon, box(s(1), s(1)), Qt.AlignCenter, mode)
            if self.has_arrow():
                draw_arrow(painter, s(26.5), s(11.5), arrow_color, arrow)
        elif k == "qat":
            style.paint_icon(painter, icon, box(s(4), (self.height() - n) / 2.0), Qt.AlignCenter, mode)
            if self.has_arrow():
                draw_arrow(painter, self.width() - s(5.5), self.height() / 2.0 + s(0.5), arrow_color, arrow)
        elif k == "hud":
            style.paint_icon(painter, icon, box(s(2), s(2)), Qt.AlignCenter, mode)
            if self.has_arrow():
                draw_arrow(painter, self.width() - s(4.5), s(12), arrow_color, s(4.5))
        else:
            style.paint_icon(painter, icon, box(s(2), s(2)), Qt.AlignCenter, mode)
        painter.end()

    @staticmethod
    def _frame(painter, rect, fill, line):
        painter.save()
        painter.setPen(hairline_pen(line))
        painter.setBrush(fill)
        painter.drawRect(rect)
        painter.restore()


class FlatButton(QtWidgets.QAbstractButton):
    """Icon-only chrome button (window controls, chevrons, pane tabs)."""

    def __init__(self, icon=None, tooltip="", size=(36, 33), icon_size=20, parent=None,
                 hover_fill="hover", down_fill="down", glyph=None):
        super().__init__(parent)
        self._icon = icon or QtGui.QIcon()
        self.k = ui_scale()
        self._icon_size = scaled(icon_size, self.k)
        self._glyph = glyph
        # a token name ("hover") follows the theme; a "#rrggbb" stays as given
        self.hover_fill = hover_fill or None
        self.down_fill = down_fill or None
        self.hover_icon = None
        self.setToolTip(tooltip)
        self.setFixedSize(scaled(size[0], self.k), scaled(size[1], self.k))
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.ArrowCursor)

    def set_icon(self, icon):
        self._icon = icon
        self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        if self.isDown() and self.down_fill is not None:
            painter.fillRect(self.rect(), colour(self.down_fill))
        elif self.underMouse() and self.isEnabled() and self.hover_fill is not None:
            painter.fillRect(self.rect(), colour(self.hover_fill))
        icon = self.hover_icon if (self.hover_icon is not None and self.underMouse()) else self._icon
        s = self._icon_size
        rect = QtCore.QRect((self.width() - s) // 2, (self.height() - s) // 2, s, s)
        if icon is not None and not icon.isNull():
            style.paint_icon(painter, icon, rect, Qt.AlignCenter,
                       QtGui.QIcon.Normal if self.isEnabled() else QtGui.QIcon.Disabled)
        elif self._glyph:

            c = QtCore.QRectF(rect).center()
            painter.translate(c)
            painter.scale(self.k, self.k)
            painter.translate(-c / self.k)
            self._glyph(painter, QtCore.QRectF(rect.x() / self.k, rect.y() / self.k, s / self.k, s / self.k), self)
        painter.end()


def glyph_chevron_right(painter, rect, widget):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(T.arrow)
    pen.setWidthF(1.0)
    painter.setPen(pen)
    c = rect.center()
    for dx in (-2.5, 1.5):
        painter.drawLine(QtCore.QPointF(c.x() + dx - 1.5, c.y() - 3), QtCore.QPointF(c.x() + dx + 1.5, c.y()))
        painter.drawLine(QtCore.QPointF(c.x() + dx + 1.5, c.y()), QtCore.QPointF(c.x() + dx - 1.5, c.y() + 3))
    painter.restore()


def glyph_caret_up(painter, rect, widget):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(T.text)
    pen.setWidthF(1.4)
    painter.setPen(pen)
    c = rect.center()
    painter.drawLine(QtCore.QPointF(c.x() - 4, c.y() + 2), QtCore.QPointF(c.x(), c.y() - 2))
    painter.drawLine(QtCore.QPointF(c.x(), c.y() - 2), QtCore.QPointF(c.x() + 4, c.y() + 2))
    painter.restore()


def glyph_caret_down(painter, rect, widget):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(T.text)
    pen.setWidthF(1.4)
    painter.setPen(pen)
    c = rect.center()
    painter.drawLine(QtCore.QPointF(c.x() - 4, c.y() - 2), QtCore.QPointF(c.x(), c.y() + 2))
    painter.drawLine(QtCore.QPointF(c.x(), c.y() + 2), QtCore.QPointF(c.x() + 4, c.y() - 2))
    painter.restore()


def glyph_triangle_right(painter, rect, widget):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(T.arrow_dim if not widget.underMouse() else T.arrow)
    c = rect.center()
    path = QtGui.QPainterPath()
    path.moveTo(c.x() - 2.5, c.y() - 5)
    path.lineTo(c.x() + 3, c.y())
    path.lineTo(c.x() - 2.5, c.y() + 5)
    path.closeSubpath()
    painter.drawPath(path)
    painter.restore()


def glyph_ellipsis(painter, rect, widget):
    ""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(T.text)
    base = rect.center().y() + 5
    for dx in (-2.0, 2.0):
        painter.drawEllipse(QtCore.QPointF(rect.center().x() + dx, base), 0.9, 0.9)
    painter.restore()


def glyph_minimize(painter, rect, widget):
    painter.save()
    painter.fillRect(QtCore.QRectF(rect.center().x() - 5.5, rect.center().y() + 4, 11, 1.5), T.text)
    painter.restore()


def glyph_span(painter, rect, widget):
    """Span the screen height: an up-and-down arrow between two bars. Drawn because the
    private icon copy has no MINMAX_SPAN_TB, and an icon-less button paints nothing (Ati 00:44Z:
    "a invisible button ... third from the right")."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(T.text)
    pen.setWidthF(1.0)
    painter.setPen(pen)
    c = rect.center()
    for sy in (-1, 1):
        painter.drawLine(QtCore.QPointF(c.x() - 5.5, c.y() + sy * 7), QtCore.QPointF(c.x() + 5.5, c.y() + sy * 7))
        tip = c.y() + sy * 5
        painter.drawLine(QtCore.QPointF(c.x() - 3, tip - sy * 3), QtCore.QPointF(c.x(), tip))
        painter.drawLine(QtCore.QPointF(c.x() + 3, tip - sy * 3), QtCore.QPointF(c.x(), tip))
    painter.drawLine(QtCore.QPointF(c.x(), c.y() - 5), QtCore.QPointF(c.x(), c.y() + 5))
    painter.restore()


def glyph_maximize(painter, rect, widget):
    painter.save()
    pen = QtGui.QPen(T.text)
    pen.setWidthF(1.0)
    painter.setPen(pen)
    c = rect.center()
    painter.drawRect(QtCore.QRectF(c.x() - 7, c.y() - 6, 14, 12))
    painter.drawLine(QtCore.QPointF(c.x() - 7, c.y() - 5), QtCore.QPointF(c.x() + 7, c.y() - 5))
    painter.restore()


def glyph_close(painter, rect, widget):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor("#ffffff") if widget.underMouse() else T.text)
    pen.setWidthF(1.2)
    painter.setPen(pen)
    c = rect.center()
    painter.drawLine(QtCore.QPointF(c.x() - 5.5, c.y() - 5.5), QtCore.QPointF(c.x() + 5.5, c.y() + 5.5))
    painter.drawLine(QtCore.QPointF(c.x() + 5.5, c.y() - 5.5), QtCore.QPointF(c.x() - 5.5, c.y() + 5.5))
    painter.restore()


def glyph_help(painter, rect, widget):
    """Help: a question mark in a ring (helpglyph-1127; drawn when the pack has no MINMAX_HELP)."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(T.text)
    pen.setWidthF(1.1)
    painter.setPen(pen)
    c = rect.center()
    painter.drawEllipse(c, 7.5, 7.5)
    f = QtGui.QFont(widget.font())
    f.setPixelSize(11)
    f.setBold(True)
    painter.setFont(f)
    painter.drawText(QtCore.QRectF(c.x() - 7, c.y() - 7, 14, 14), Qt.AlignCenter, "?")
    painter.restore()


class Separator(QtWidgets.QWidget):
    """1-device-pixel vertical line with 1 logical px of air on both sides."""

    def __init__(self, color="line_light", height=70, parent=None):
        super().__init__(parent)
        self.color = color      # a token name or "#rrggbb"
        self.setFixedSize(3, height)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        dpr = self.devicePixelRatioF()
        painter.scale(1.0 / dpr, 1.0 / dpr)
        x = int(round(1.0 * dpr))
        painter.fillRect(QtCore.QRect(x, int(round(1 * dpr)) - 1 if dpr > 1 else 1, 1,
                                      int(self.height() * dpr) - 2 * int(round(1 * dpr)) + 2),
                         colour(self.color))
        painter.end()
