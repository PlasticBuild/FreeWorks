# SPDX-License-Identifier: LGPL-2.1-or-later
"""Graphics-area chrome: heads-up view toolbar, task pane tabs, model tab row."""

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

from . import catalog, icons, paths, style
from .widgets import CommandButton, FlatButton, alive, popup_menu, scaled, ui_font, ui_scale

Qt = QtCore.Qt

T = style.T                        # the theme's colours, read when painting


def dev(v, dpr):
    return int(round(v * dpr))


# --------------------------------------------------------------------------- heads-up bar
def _strip_top():
    """How far the CommandManager tab row reaches over the view's top (tabstrip.py), 0 when not there."""
    try:
        from . import tabstrip
        return tabstrip.top()
    except Exception:
        return 0


def _strip_row():
    try:
        from . import tabstrip
        return tabstrip.row_geometry()
    except Exception:
        return None


class HeadsUpBar(QtWidgets.QWidget):
    """Transparent row of view tools floating at the top centre of the 3D view."""

    def __init__(self, shell, parent=None, spec=None, name="SWHeadsUp"):
        super().__init__(parent)
        self.setObjectName(name)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.buttons = []
        x = 0
        for key, flyout in (catalog.HEADS_UP if spec is None else spec):
            b = CommandButton(shell, key, flyout, "hud", self)
            b._hud_key = key
            b.resize(b.sizeHint())
            b.move(x, 0)
            x += b.width() + 1
            self.buttons.append(b)
        self.resize(x, max([b.height() for b in self.buttons] + [scaled(24)]))
        self._optional = [b for b in self.buttons if getattr(b, "_hud_key", None) in self.ONLY_WITH_PMI]
        if self._optional:
            self._opt_timer = QtCore.QTimer(self)
            self._opt_timer.setObjectName("FW_HudOptional")
            self._opt_timer.timeout.connect(self._relayout)
            self._opt_timer.start(1000)
            QtCore.QTimer.singleShot(0, self._relayout)


    # annotations (a new part's bar: Zoom to Fit, Zoom to Area, Previous View, Section View, View
    # Orientation, Display Style, Hide/Show Items, Edit Appearance, Apply Scene, View Settings)
    ONLY_WITH_PMI = ("DynamicAnnotationViews",)

    @staticmethod
    def _has_pmi():
        try:
            from . import mbd
            d = App.ActiveDocument
            return d is not None and any(mbd.is_pmi(o) for o in d.Objects)
        except Exception:
            return True

    @staticmethod
    def _user_hidden():
        """The tools the user unticked (the heads-up bar's right-click menu, Customize): they stay hidden."""
        try:
            from . import chromemenus
            return set(chromemenus.hidden_hud())
        except Exception:
            return set()

    def _relayout(self):
        show = self._has_pmi()
        hidden = self._user_hidden()
        # pack the visible buttons left to right; when nothing changes (same visibility, same x
        # positions and width) leave the bar alone. Checked by position as well as visibility so a
        # bar that started with a button already hidden still closes up the gap (PC run of hud164)
        want, x = [], 0
        for b in self.buttons:
            if (b in self._optional and not show) or getattr(b, "_hud_key", None) in hidden:
                want.append((b, None))
                continue
            want.append((b, x))
            x += b.width() + 1
        if all((b.isVisibleTo(self) == (px is not None)) and (px is None or b.x() == px) for b, px in want) \
                and self.width() == x:
            return
        for b, px in want:
            if px is None:
                b.setVisible(False)
            else:
                b.setVisible(True)
                b.move(px, 0)
        self.resize(x, self.height())
        self.place()

    def place(self):
        host = self.parentWidget()
        if host is None:
            return
        width = host.width() - host.contentsMargins().right()     # a pinned Task Pane takes the right side
        x, y = max(0, (width - self.width()) // 2), scaled(5)
        g = _strip_row()
        if g is not None:
            # hudbelow-1122: under the CommandManager tabs on the view's top strip, still centred over the

            # width with their whole names and the view tools sit on a row of their own below them)
            tl = host.mapFrom(host.window(), g.topLeft())
            if tl.y() + g.height() > 0:
                y = max(0, tl.y() + g.height()) + scaled(5)
        self.move(x, y)
        self.raise_()


class TaskPaneTabs(QtWidgets.QWidget):
    ""


    # the commands here only stand in when a page cannot be made)
    ITEMS = (
        ("TASKPANE_HOME_TAB", "FreeCAD Resources", ("Start_Start", "Std_Start")),
        ("ASSEMBLY_LIBRARY", "Design Library", ("Std_AddonMgr",)),
        ("FILE_EXPLORER_TAB", "File Explorer", "recent"),
        ("DVE_TAB", "View Palette", ("Std_DlgMacroExecute",)),
        ("DISPMGR_APPEAR", "Appearances, Scenes, and Decals", ("Std_SetAppearance", "Std_SetMaterial")),
        ("CONFIG_HIDE_SHOW_CUSTOM_PROPS", "Custom Properties", ("Std_ProjectInfo",)),
        ("DATA_MIGRATION_IMPORTED_GEOMETRY", "Import Model", "import"),
    )

    BOX_W, BOX_H = 25.5, 23.5

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.shell = shell
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.icons = [icons.family(i[0]) for i in self.ITEMS]
        self.hover = -1
        self.active = 0
        self.k = ui_scale()
        self.box_h = self.BOX_H * self.k
        self.resize(self.width_here(), int(len(self.ITEMS) * self.box_h + 1))

    @classmethod
    def width_here(cls):
        return int(cls.BOX_W * ui_scale() + 1.5)

    def _index(self, pos):
        i = int(pos.y() // self.box_h)
        return i if 0 <= i < len(self.ITEMS) else -1

    def mouseMoveEvent(self, e):
        i = self._index(e.position())
        if i != self.hover:
            self.hover = i
            self.update()

    def leaveEvent(self, e):
        self.hover = -1
        self.update()

    def event(self, e):
        if e.type() == QtCore.QEvent.ToolTip:
            i = self._index(QtCore.QPointF(e.pos()))
            if i >= 0:
                QtWidgets.QToolTip.showText(e.globalPos(), self.ITEMS[i][1], self)
            return True
        return super().event(e)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        i = self._index(e.position())
        if i < 0:
            return

        # tab again slides it shut
        try:
            from . import taskpane
            # after the press, not inside it: building a page can load FreeCAD modules (New
            # Assembly / New Drawing ask whether their workbench loads), which crashed FreeCAD on
            # Windows when done inside the mouse press (land178c)
            QtCore.QTimer.singleShot(0, lambda i=i: alive(self) and taskpane.pane_of(self).toggle(i))
            return
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Task Pane: %s\n" % error)
        self.active = i
        self.update()
        target = self.ITEMS[i][2]
        if target == "recent":
            self.shell.show_recent_menu(self.mapToGlobal(QtCore.QPoint(0, int((i + 1) * self.box_h))))
            return
        for name in target:
            try:
                if Gui.Command.get(name) is not None:
                    Gui.runCommand(name, 0)
                    return
            except Exception:
                continue

    def place(self):
        host = self.parentWidget()
        if host is None:
            return
        self.move(host.width() - self.width() + 1, scaled(26, self.k) + _strip_top())
        self.raise_()
        pane = getattr(self, "_pane", None)
        if pane is not None and alive(pane):
            from . import taskpane
            taskpane.pane_of(self).place()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        dpr = self.devicePixelRatioF()
        p.save()
        p.scale(1.0 / dpr, 1.0 / dpr)
        W = dev(self.width(), dpr)
        bh = dev(self.box_h, dpr)
        for i in range(len(self.ITEMS)):
            y = i * bh
            fill = T.pane if i == self.active else (T.tab_hover if i == self.hover else T.tab)
            p.fillRect(0, y, W, bh, fill)
            p.fillRect(0, y, W, 1, T.line)
            p.fillRect(0, y, 1, bh, T.line)
        p.fillRect(0, len(self.ITEMS) * bh, W, 1, T.line)
        p.restore()
        for i, icon in enumerate(self.icons):
            if not icon.isNull():
                style.paint_icon(p, icon, QtCore.QRect(scaled(3, self.k), int(i * self.box_h + 2 * self.k),
                                                       scaled(20, self.k), scaled(20, self.k)))
        p.end()


# --------------------------------------------------------------------------- triad and view name
# FreeCAD's standard camera orientations (Gui/Camera.cpp) as quaternions (x, y, z, w),

_R = 0.70710678
STANDARD_VIEWS = (
    ("*Top", (0.0, 0.0, 0.0, 1.0)),
    ("*Bottom", (1.0, 0.0, 0.0, 0.0)),
    ("*Front", (_R, 0.0, 0.0, _R)),
    ("*Back", (0.0, _R, _R, 0.0)),
    ("*Right", (0.5, 0.5, 0.5, 0.5)),
    ("*Left", (-0.5, 0.5, 0.5, -0.5)),
    ("*Isometric", (0.424708, 0.17592, 0.339851, 0.820473)),
    ("*Dimetric", (0.567952, 0.103751, 0.146726, 0.803205)),
    ("*Trimetric", (0.446015, 0.119509, 0.229575, 0.856787)),
)
# Half a degree: FreeCAD's view animations end exactly on the standard orientation.
_SAME_VIEW = math.cos(math.radians(0.5) / 2.0)


def _unit(q):
    n = math.sqrt(sum(v * v for v in q)) or 1.0
    return tuple(v / n for v in q)


def _turned_standard():
    """The standard orientations with an Update Standard Views turn applied (namedviews.py)."""
    try:
        from . import namedviews
        if not namedviews.turned():
            return STANDARD_VIEWS
        turn = namedviews.turn()
        return tuple((name, tuple(turn.multiply(App.Rotation(*std)).Q)) for name, std in STANDARD_VIEWS)
    except Exception:
        return STANDARD_VIEWS


def standard_view_name(q):
    """'*Isometric' when the camera is in that standard orientation, else ''."""
    q = _unit(q)
    for name, std in _turned_standard():
        if abs(sum(a * b for a, b in zip(q, _unit(std)))) >= _SAME_VIEW:
            return name
    return ""


def to_camera(q, v):
    """World vector v in the camera's frame (x right, y up, z towards the viewer):
    the inverse of the camera orientation q applied to v."""
    x, y, z, w = _unit(q)
    x, y, z = -x, -y, -z
    vx, vy, vz = v
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    return (vx + w * tx + (y * tz - z * ty),
            vy + w * ty + (z * tx - x * tz),
            vz + w * tz + (x * ty - y * tx))


def camera_quaternion():
    try:
        view = Gui.activeView()
        if view is None or not hasattr(view, "getCameraOrientation"):
            return None
        return tuple(float(v) for v in view.getCameraOrientation().Q)
    except Exception:
        return None


def _has_family(name):
    try:
        families = QtGui.QFontDatabase.families()
    except TypeError:
        families = QtGui.QFontDatabase().families()
    return name in families


def view_font(points):
    ""
    if _has_family("Century Gothic"):
        font = QtGui.QFont("Century Gothic")
        font.setPointSizeF(points)
        return font
    return ui_font(points=points)


def triad_shown():
    """Options > Display > Display reference triad."""
    return paths.params().GetBool("ReferenceTriad", True)


def confirmation_corner_on():
    """Options > General > Enable Confirmation Corner."""
    return paths.params().GetBool("ConfirmationCorner", True)


class ViewCorner(QtWidgets.QWidget):
    ""




    # the scale its ribbon heights give): arrows 29 long, 3.6 wide, heads 8.5 x 7.5,
    # origin 38 from the left and 47 from the bottom, name 5 from the left.
    W, H = 110, 90
    ORIGIN = (38.0, 43.0)
    LENGTH = 29.0
    HEAD = 8.5
    HEAD_W = 7.5
    SHAFT_W = 3.6

    LABEL_GAP = 5.0
    LABEL_SHIFT = (0.5, -2.0)
    # axis, letter, (light, base, dark) for the shaded arrow, letter colour
    AXES = (((1.0, 0.0, 0.0), "X", ("#e66e6e", "#a30000", "#6e0000"), "#ff0000"),
            ((0.0, 1.0, 0.0), "Y", ("#78dc78", "#289628", "#005200"), "#008000"),
            ((0.0, 0.0, 1.0), "Z", ("#6e6ee6", "#0000a3", "#00006e"), "#0000ff"))
    # look-audit triad-1121: over a dark viewport, lifted shades of the same colours (the dark blue Z and the
    # shaded sides vanished on the dark grey), as the sketch colours are lifted in Dark
    AXES_DARK = {"X": (("#ffb0b0", "#e84a4a", "#a82828"), "#ff6666"),
                 "Y": (("#b4f0b4", "#45c845", "#237a23"), "#55dd55"),
                 "Z": (("#b8bcff", "#5a6cff", "#2c3cc0"), "#8c9aff")}

    def _view_dark(self):
        try:
            return bool(style.viewport_dark())
        except Exception:
            return False

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.setObjectName("SWViewCorner")
        self.shell = shell
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFixedSize(self.W, self.H)
        self.quat = None
        self.name = ""
        self.name_font = view_font(9.0)
        self.axis_font = view_font(6.5)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def _tabs_h(self):
        ""

        host = self.parentWidget()
        try:
            tabs = host.findChild(QtWidgets.QTabBar, "FW_StudyTabs") if host is not None else None
            if tabs is not None and alive(tabs) and tabs.isVisible():
                return tabs.height()
        except Exception as _fw_err:
            _fw_log("chrome.py:399", _fw_err)
        return 0

    def place(self):
        host = self.parentWidget()
        if host is None:
            return
        self._tabs = self._tabs_h()
        self.move(0, max(0, host.height() - self.H - self._tabs))
        self.raise_()

    def poll(self):
        if not self.isVisible():
            return
        if self._tabs_h() != getattr(self, "_tabs", 0):
            self.place()
        dark = self._view_dark()        # triad-1121: a theme or scene change repaints the triad
        if dark != getattr(self, "_dark", None):
            self._dark = dark
            self.update()
        q = camera_quaternion()
        if q is None:
            if self.quat is not None:
                self.quat, self.name = None, ""
                self.update()
            return
        if self.quat is not None and max(abs(a - b) for a, b in zip(q, self.quat)) < 1e-6:
            return
        self.quat = q
        self.name = standard_view_name(q)
        self.update()

    def arrows(self):
        """(depth, axis entry, tip x, tip y, screen length) per axis, farthest first."""
        ox, oy = self.ORIGIN
        out = []
        for entry in self.AXES:
            cx, cy, cz = to_camera(self.quat, entry[0])
            out.append((cz, entry, ox + cx * self.LENGTH, oy - cy * self.LENGTH,
                        math.hypot(cx, cy) * self.LENGTH))
        out.sort(key=lambda a: a[0])
        return out

    def _gradient(self, mid, nx, ny, half, colours):
        light, base, dark = colours
        g = QtGui.QLinearGradient(mid.x() - nx * half, mid.y() - ny * half, mid.x() + nx * half, mid.y() + ny * half)
        g.setColorAt(0.0, QtGui.QColor(light))
        g.setColorAt(0.45, QtGui.QColor(base))
        g.setColorAt(1.0, QtGui.QColor(dark))
        return QtGui.QBrush(g)

    def paintEvent(self, e):
        if self.quat is None:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        ox, oy = self.ORIGIN
        origin = QtCore.QPointF(ox, oy)
        dark = getattr(self, "_dark", None)
        if dark is None:
            dark = self._dark = self._view_dark()
        for depth, (axis, letter, colours, text_colour), tx, ty, length in (self.arrows() if triad_shown() else ()):
            if dark:
                colours, text_colour = self.AXES_DARK.get(letter, (colours, text_colour))
            if length < 2.5:
                # pointing at the viewer: the arrow head seen end on
                r = self.HEAD_W / 2.0
                p.setBrush(self._gradient(origin, 0.7071, 0.7071, r, colours))
                p.drawEllipse(origin, r, r)
                label = QtCore.QPointF(ox + self.LABEL_GAP, oy - self.LABEL_GAP)
            else:
                ux, uy = (tx - ox) / length, (ty - oy) / length
                nx, ny = -uy, ux
                head = max(3.0, min(self.HEAD, length * 0.6))
                bx, by = tx - ux * head, ty - uy * head
                half = self.SHAFT_W / 2.0
                shaft = QtGui.QPolygonF([QtCore.QPointF(ox + nx * half, oy + ny * half),
                                         QtCore.QPointF(bx + nx * half, by + ny * half),
                                         QtCore.QPointF(bx - nx * half, by - ny * half),
                                         QtCore.QPointF(ox - nx * half, oy - ny * half)])
                p.setBrush(self._gradient(QtCore.QPointF((ox + bx) / 2.0, (oy + by) / 2.0), nx, ny, half, colours))
                p.drawPolygon(shaft)
                hw = self.HEAD_W / 2.0
                cone = QtGui.QPolygonF([QtCore.QPointF(bx + nx * hw, by + ny * hw), QtCore.QPointF(tx, ty),
                                        QtCore.QPointF(bx - nx * hw, by - ny * hw)])
                p.setBrush(self._gradient(QtCore.QPointF(bx, by), nx, ny, hw, colours))
                p.drawPolygon(cone)
                label = QtCore.QPointF(tx + ux * self.LABEL_GAP, ty + uy * self.LABEL_GAP)
            p.setFont(self.axis_font)
            p.setPen(QtGui.QColor(text_colour))
            lx, ly = label.x() + self.LABEL_SHIFT[0], label.y() + self.LABEL_SHIFT[1]
            p.drawText(QtCore.QRectF(lx - 8.0, ly - 8.0, 16.0, 16.0), Qt.AlignCenter, letter)
            p.setPen(Qt.NoPen)
        if self.name:
            p.setFont(self.name_font)
            p.setPen(style.viewport_ink())
            p.drawText(QtCore.QPointF(5.0, self.H - 3.0), self.name)
        p.end()


# --------------------------------------------------------------------------- confirmation corner
OK_GREEN = "#74a257"
CANCEL_RED = "#d9261c"


def tinted(icon, colour):
    """The icon's shape in one colour (the pack's check mark is black)."""
    if icon is None or icon.isNull():
        return QtGui.QIcon()
    result = QtGui.QIcon()
    for size in icon.availableSizes() or [QtCore.QSize(32, 32)]:
        pixmap = icon.pixmap(size)
        painter = QtGui.QPainter(pixmap)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QtGui.QColor(colour))
        painter.end()
        result.addPixmap(pixmap)
    return result


def glyph_check(painter, rect, widget):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(OK_GREEN if widget.isEnabled() else T.hex("text_disabled")))
    pen.setWidthF(max(2.0, rect.width() / 4.5))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    w, h, x, y = rect.width(), rect.height(), rect.x(), rect.y()
    path = QtGui.QPainterPath(QtCore.QPointF(x + 0.15 * w, y + 0.55 * h))
    path.lineTo(QtCore.QPointF(x + 0.40 * w, y + 0.80 * h))
    path.lineTo(QtCore.QPointF(x + 0.85 * w, y + 0.22 * h))
    painter.drawPath(path)
    painter.restore()


def glyph_cross(painter, rect, widget):
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(CANCEL_RED if widget.isEnabled() else T.hex("text_disabled")))
    pen.setWidthF(max(2.0, rect.width() / 4.5))
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    m = rect.adjusted(rect.width() * 0.2, rect.height() * 0.2, -rect.width() * 0.2, -rect.height() * 0.2)
    painter.drawLine(m.topLeft(), m.bottomRight())
    painter.drawLine(m.topRight(), m.bottomLeft())
    painter.restore()


def _class_name(widget):
    try:
        return widget.metaObject().className()
    except Exception:
        return ""


def dialog_buttons(box):
    """The native button that confirms and the one that cancels in a task panel's
    button box. A lone Close (Sketch, some tools) confirms; a lone Cancel cancels."""
    roles = QtWidgets.QDialogButtonBox
    natives = [b for b in box.buttons()
               if isinstance(b, QtWidgets.QAbstractButton) and not b.isHidden()]
    ok = cancel = None
    for b in natives:
        role = box.buttonRole(b)
        if role in (roles.AcceptRole, roles.YesRole, roles.ApplyRole) and ok is None:
            ok = b
        elif role in (roles.RejectRole, roles.NoRole, roles.DestructiveRole) and cancel is None:
            cancel = b
    if len(natives) == 1 and box.standardButton(natives[0]) != roles.Cancel:
        ok, cancel = natives[0], None
    return ok, cancel


def _end_sketch_tool():
    ""

    try:
        from .fwsketch import toolbase
        t = toolbase.active()
        if t is not None:
            t.end()
    except Exception as _fw_err:
        _fw_log("chrome.py:573", _fw_err)
    try:
        from . import sketchtoolpm
        page = sketchtoolpm.current()
        if page is not None:
            sketchtoolpm.ToolPage.accept(page)
    except Exception as _fw_err:
        _fw_log("chrome.py:580", _fw_err)


def _editing_component():
    """Edit Component is on in the active assembly window (asmtools)."""
    try:
        from . import asmtools
        editing = asmtools.editing()
        return editing is not None and App.ActiveDocument is not None and editing[0].Document is App.ActiveDocument
    except Exception:
        return False


class ConfirmationCorner(QtWidgets.QWidget):
    ""




    CELL = 32
    ICON = 26
    MARGIN = 4

    # apart across and 31 px down, both faint (about 35 % over the view) until pointed at
    STEP = (44, 31)
    TOP = 8
    FAINT = 0.38

    # dark-blue Exit Sketch icon and the red X all but vanish at that strength
    FAINT_DARK = 0.7

    def faint(self):
        try:
            return self.FAINT_DARK if style.viewport_dark() else self.FAINT
        except Exception:
            return self.FAINT

    def _set_faint(self):
        level = self.faint()
        for b in (self.ok, self.cancel):
            effect = b.graphicsEffect()
            if effect is not None and not b.underMouse():
                effect.setOpacity(level)

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.setObjectName("SWConfirmationCorner")
        self.shell = shell
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        size = (self.CELL, self.CELL)
        self.ok = FlatButton(None, "OK", size, self.ICON, self, glyph=glyph_check)
        self.cancel = FlatButton(None, "Cancel", size, self.ICON, self, glyph=glyph_cross)
        self.ok.setObjectName("SWConfirmOK")
        self.cancel.setObjectName("SWConfirmCancel")
        self.ok.clicked.connect(self._press_ok)
        self.cancel.clicked.connect(self._press_cancel)
        for b in (self.ok, self.cancel):
            effect = QtWidgets.QGraphicsOpacityEffect(b)
            effect.setOpacity(self.faint())
            b.setGraphicsEffect(effect)
            b.installEventFilter(self)
        self._icons = {
            "ok": tinted(icons.family("CHECK_MARK"), OK_GREEN),
            "cancel": icons.family("STANDARD_CANCEL"),
            "exit": icons.family("EXIT_SKETCH_CANCEL"),
            "component": icons.family("ASSEMBLIES_EDIT_COMPONENT"),
        }
        if self._icons["component"] is None or self._icons["component"].isNull():
            self._icons["component"] = QtGui.QIcon(":/icons/PartDesign_Body.svg")
        self.mode = None
        self.at_pointer = None      # where D put the corner, in the view's coordinates, or None (its own corner)
        self._dressed = None
        self.ok_native = self.cancel_native = None
        self._control = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.hide()

    # ---------------------------------------------------------------- state
    def _edit_control(self):
        """FreeCAD's TaskEditControl (the task panel's button row), cached."""
        control = self._control
        if control is not None and alive(control):
            return control
        self._control = None
        import time
        now = time.monotonic()
        if now - getattr(self, "_control_miss", -10.0) < 1.0:
            return None             # looked a moment ago and there was none: no full walk every 150 ms
        pane = getattr(self.shell, "left_pane", None)
        page = pane.pages.get("Tasks") if pane is not None and alive(pane) else None
        roots = [page] if page is not None and alive(page) else []
        roots.append(self.shell.window)
        for root in roots:
            for child in root.findChildren(QtWidgets.QWidget):
                if _class_name(child).endswith("TaskEditControl"):
                    self._control = child
                    return child
        self._control_miss = now
        return None

    def state(self):
        ""

        try:
            if not Gui.Control.activeDialog():
                return ("component", None, None) if _editing_component() else (None, None, None)
        except Exception:
            return None, None, None
        try:
            in_sketch = self.shell.in_sketch()
        except Exception:
            in_sketch = False
        if in_sketch:
            return "sketch", None, None
        control = self._edit_control()
        box = control.findChild(QtWidgets.QDialogButtonBox) if control is not None else None
        if box is None:
            return None, None, None
        ok, cancel = dialog_buttons(box)
        if ok is None and cancel is None:
            return None, None, None
        return "dialog", ok, cancel

    def refresh(self):
        host = self.parentWidget()
        mode, ok, cancel = (None, None, None) if host is None or not confirmation_corner_on() else self.state()
        self.mode, self.ok_native, self.cancel_native = mode, ok, cancel
        if mode is None:
            self.at_pointer = None          # the next edit starts in the corner again
            if not self.isHidden():
                self.hide()
            return
        if mode != self._dressed:
            self._dressed = mode
            if mode == "component":
                self.ok.set_icon(self._icons["component"])
                self.ok.setToolTip("Edit Component: back to editing the assembly")
            elif mode == "sketch":
                self.ok.set_icon(self._icons["exit"])
                self.ok.setToolTip("Exit Sketch")
                self.cancel.set_icon(self._icons["cancel"])
                self.cancel.setToolTip("Exit sketch and discard changes")
            else:
                self.ok.set_icon(self._icons["ok"])
                self.ok.setToolTip("OK")
                self.cancel.set_icon(self._icons["cancel"])
                self.cancel.setToolTip("Cancel")
        if mode == "component":
            self.ok.setEnabled(True)
            self.ok.setVisible(True)
            self.cancel.setVisible(False)
        elif mode == "sketch":
            self.ok.setEnabled(True)
            self.ok.setVisible(True)
            # the red X only when the sketch's content was kept as its editing began
            watcher = getattr(self.shell, "sketch_exit", None)
            self.cancel.setEnabled(True)
            self.cancel.setVisible(watcher is not None and watcher.ready() is not None)
        else:
            # NO DEAD CONTROLS: the corner's OK is never greyed; pressed before the page is ready it
            # says in red what is still missing (pmkeys.accept). A Cancel the page greys is left out.
            self.ok.setVisible(ok is not None)
            self.ok.setEnabled(True)
            self.cancel.setVisible(cancel is not None and cancel.isEnabled())
            self.cancel.setEnabled(True)
        shown = [b for b in (self.ok, self.cancel) if not b.isHidden()]
        cell, dx, dy = scaled(self.CELL), scaled(self.STEP[0]), scaled(self.STEP[1])
        if len(shown) == 2:
            self.ok.move(0, 0)
            self.cancel.move(dx, dy)
            size = QtCore.QSize(dx + cell, dy + cell)
        else:
            for b in shown:
                b.move(0, 0)
            size = QtCore.QSize(cell, cell)
        if self.size() != size:
            self.resize(size)
        # only the buttons take the pointer: the empty corners of this box belong to the graphics

        region = QtGui.QRegion()
        for b in shown:
            region = region.united(QtGui.QRegion(b.geometry()))
        if region != self.mask():
            self.setMask(region)
        self.place()
        if self.isHidden():
            self._set_faint()           # corner-1121: the viewport may have changed since the last edit
            self.show()
        self.raise_()

    def place(self):
        host = self.parentWidget()
        if host is None:
            return
        # left of the task pane tabs on the right edge
        taken = host.contentsMargins().right()      # a pinned Task Pane (with the tabs) sits there
        right = host.width() - (taken or TaskPaneTabs.width_here()) - scaled(self.MARGIN)
        # cmrow-1120: never over the Task Pane's tab column (a PM open could leave a small right margin that

        try:
            cols = [w for w in host.children() if isinstance(w, TaskPaneTabs) and w.isVisible()]
            if cols:
                right = min(right, min(w.x() for w in cols) - scaled(self.MARGIN))
        except RuntimeError:
            pass
        # each button keeps its own place whether or not the other one shows
        left = right - scaled(self.STEP[0]) - scaled(self.CELL)
        top = scaled(self.TOP) + _strip_top()             # under the CommandManager tabs on the view's top strip
        if self.ok.isHidden() and not self.cancel.isHidden():
            left, top = left + scaled(self.STEP[0]), top + scaled(self.STEP[1])
        if self.at_pointer is not None:
            # D put it at the pointer: its middle on the pointer, kept inside the view
            left = max(0, min(self.at_pointer.x() - self.width() // 2, host.width() - self.width()))
            top = max(0, min(self.at_pointer.y() - self.height() // 2, host.height() - self.height()))
        self.move(left, top)

    def to_pointer(self):
        """D: the confirmation corner at the pointer, and back to the corner on the next D. False when it
        is not showing (nothing is being edited)."""
        host = self.parentWidget()
        if host is None or self.isHidden():
            return False
        if self.at_pointer is not None:
            self.at_pointer = None
        else:
            self.at_pointer = host.mapFromGlobal(QtGui.QCursor.pos())
        self.place()
        return True

    def eventFilter(self, obj, event):
        ""
        if obj in (self.ok, self.cancel) and event.type() in (QtCore.QEvent.Enter, QtCore.QEvent.Leave):
            effect = obj.graphicsEffect()
            if effect is not None:
                effect.setOpacity(1.0 if event.type() == QtCore.QEvent.Enter else self.faint())
        return False

    # ---------------------------------------------------------------- actions
    def _press_ok(self):
        if self.mode == "component":
            try:
                from . import asmtools
                asmtools.end_edit()
            except Exception as error:
                App.Console.PrintWarning("FreeWorks: Edit Component: %s\n" % error)
        elif self.mode == "sketch":
            _end_sketch_tool()
            try:
                Gui.runCommand("Sketcher_LeaveSketch", 0)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Exit Sketch failed: %s\n" % error)
        elif self.ok_native is not None and alive(self.ok_native):
            from . import pmkeys
            pmkeys.accept(self.ok_native)       # the page's own checks; early: what is missing, in red
        QtCore.QTimer.singleShot(0, self.refresh)

    def _press_cancel(self):
        if self.mode == "sketch":
            from . import sketchexit
            sketchexit.discard(getattr(self.shell, "sketch_exit", None), self.window())
        elif self.mode == "dialog" and self.cancel_native is not None and alive(self.cancel_native):
            self.cancel_native.click()
        QtCore.QTimer.singleShot(0, self.refresh)


def _model_workbench():
    ""



    try:
        if Gui.activeWorkbench().name() != "TechDrawWorkbench":
            return
        doc = App.ActiveDocument
        if doc is None or any(o.isDerivedFrom("TechDraw::DrawPage") for o in doc.Objects):
            return
        asm = any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects)
        Gui.activateWorkbench("AssemblyWorkbench" if asm else "PartDesignWorkbench")
    except Exception as error:
        App.Console.PrintLog("FreeCAD: model workbench after a drawing: %s\n" % error)


class ViewOverlay(QtCore.QObject):
    """Keeps the heads-up bar, task pane tabs, triad and view name on the active 3D view."""

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self.hud = HeadsUpBar(shell)

        # Display Style, Hide/Show Items; drawings-land50 display commands)
        self.hud_sheet = HeadsUpBar(shell, spec=getattr(catalog, "HEADS_UP_SHEET", ()), name="SWHeadsUpSheet")
        self.tasks = TaskPaneTabs(shell)
        self.corner = ViewCorner(shell)
        self.confirm = ConfirmationCorner(shell)
        self.hud.hide()
        self.hud_sheet.hide()
        self.tasks.hide()
        self.corner.hide()
        self.host = None
        self.sheet = None
        self.blank = None
        self.mdi = shell.window.findChild(QtWidgets.QMdiArea)
        if self.mdi is not None:
            self.mdi.subWindowActivated.connect(self.attach)
        QtCore.QTimer.singleShot(0, self.attach)

    def attach(self, *args):
        host = self._active_view_widget()
        if host is not None:
            QtCore.QTimer.singleShot(0, _model_workbench)

        # the heads-up bar, triad and view name only on 3D views
        sheet = self._active_sheet_widget() if host is None else None

        # of the empty window; they sit on the empty document area (the pane opened at the screen's corner)
        blank = self.mdi if host is None and sheet is None and self.mdi is not None and alive(self.mdi) else None
        if host is self.host and alive(host) and (sheet is None or sheet is self.sheet) and \
                (host is not None or sheet is not None or blank is getattr(self, "blank", None)):
            self._place()
            return
        if self.host is not None and alive(self.host):
            self.host.removeEventFilter(self)
        if getattr(self, "sheet", None) is not None and alive(self.sheet):
            self.sheet.removeEventFilter(self)
        if getattr(self, "blank", None) is not None and alive(self.blank):
            self.blank.removeEventFilter(self)
        self.host = host
        self.sheet = sheet
        self.blank = blank
        for w in (self.hud, self.tasks, self.corner):
            if not alive(w):
                continue
            if w is self.tasks and host is None and (sheet or blank) is not None:
                w.setParent(sheet or blank)
                w.show()
                continue
            w.setParent(host)
            if host is not None:
                w.show()
        if alive(self.hud_sheet):
            self.hud_sheet.setParent(sheet)
            if sheet is not None:
                self.hud_sheet.show()
                self.hud_sheet.place()
        if alive(self.confirm):
            # shown only while something is being edited
            self.confirm.setParent(host)
            self.confirm.hide()
            self.confirm.refresh()
        if host is not None:
            host.installEventFilter(self)
            self._place()
        elif sheet is not None:
            sheet.installEventFilter(self)
            if alive(self.tasks):
                self.tasks.place()
            if alive(self.hud_sheet):
                self.hud_sheet.place()
        elif blank is not None:
            blank.installEventFilter(self)
            if alive(self.tasks):
                self.tasks.place()

    def _active_view_widget(self):
        if self.mdi is None or not alive(self.mdi):
            return None
        sub = (self.mdi.activeSubWindow() or self.mdi.currentSubWindow())
        if sub is None:
            subs = self.mdi.subWindowList()
            sub = subs[0] if subs else None
        if sub is None:
            return None
        view = sub.widget()
        if view is None or "View3DInventor" not in view.metaObject().className():
            return None
        return view

    def _active_sheet_widget(self):
        if self.mdi is None or not alive(self.mdi):
            return None
        sub = self.mdi.activeSubWindow() or self.mdi.currentSubWindow()
        view = sub.widget() if sub is not None else None
        if view is None or "MDIViewPage" not in view.metaObject().className():
            return None
        return view

    def _place(self):
        if alive(self.hud):
            self.hud.place()
        if alive(self.tasks):
            self.tasks.place()
        if alive(self.corner):
            self.corner.place()
        if alive(self.confirm):
            self.confirm.place()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if obj is self.host and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self._place()
        elif obj is getattr(self, "sheet", None) and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            if alive(self.tasks):
                self.tasks.place()
            if alive(self.hud_sheet):
                self.hud_sheet.place()
        elif obj is getattr(self, "blank", None) and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            if alive(self.tasks):
                self.tasks.place()
        return False

    def remove(self):
        if self.mdi is not None and alive(self.mdi):
            try:
                self.mdi.subWindowActivated.disconnect(self.attach)
            except Exception as _fw_err:
                _fw_log("chrome.py:933", _fw_err)
        if self.host is not None and alive(self.host):
            self.host.removeEventFilter(self)
        if getattr(self, "blank", None) is not None and alive(self.blank):
            self.blank.removeEventFilter(self)
        for w in (self.hud, self.hud_sheet, self.tasks, self.corner, self.confirm):
            if alive(w):
                w.hide()
                w.setParent(None)
                w.deleteLater()


# --------------------------------------------------------------------------- model tabs
def _drawing_in_front():
    """True when the window in front is a drawing sheet (TechDraw page)."""
    try:
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = mdi.activeSubWindow() if mdi is not None else None
        w = sub.widget() if sub is not None else None
        return w is not None and "MDIViewPage" in w.metaObject().className()
    except Exception:
        return False


class ModelTabs(QtWidgets.QWidget):
    """Full-width row under the graphics area with one tab per open view."""

    NAV_W = 48
    PAD = 8.0

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.setObjectName("SWModelTabs")
        self.shell = shell
        self.mdi = shell.window.findChild(QtWidgets.QMdiArea)
        self.k = ui_scale()
        self.nav_w = self.NAV_W * self.k
        self.setFixedHeight(scaled(18, self.k))
        self.setMouseTracking(True)
        self._spans = []
        self._titles = []
        self._hover = -1
        self._signature = None

    def _find_mdi(self):
        """FreeCAD's MDI area: the main window's central widget, else the one holding the most views
        (the area found when the row was made can be gone or be another one)."""
        mw = self.shell.window
        try:
            central = mw.centralWidget()
            if isinstance(central, QtWidgets.QMdiArea):
                return central
        except Exception as _fw_err:
            _fw_log("chrome.py:984", _fw_err)
        areas = [a for a in mw.findChildren(QtWidgets.QMdiArea) if alive(a)]
        areas.sort(key=lambda a: len(a.subWindowList()), reverse=True)
        return areas[0] if areas else None

    def subwindows(self):
        if self.mdi is None or not alive(self.mdi) or not self.mdi.subWindowList():
            self.mdi = self._find_mdi()
        if self.mdi is None or not alive(self.mdi):
            return []

        # a tab ("Model"); the other documents are on FreeCAD's document tabs
        active = self.mdi.activeSubWindow() or self.mdi.currentSubWindow()
        return [active] if active is not None and self._is_model(active) else []

    def _drawing_in_front(self):
        try:
            sub = self.mdi.activeSubWindow() or self.mdi.currentSubWindow()
            return "TechDraw" in sub.widget().metaObject().className()
        except Exception:
            return False

    @staticmethod
    def _is_model(sub):
        ""
        try:
            w = sub.widget()
            name = w.metaObject().className() if w is not None else ""
        except Exception:
            return True
        return "Start" not in name and "WebView" not in name and "TechDraw" not in name

    def _rows(self, subs, active):
        """(title, active) of every tab: one per view, else 'Model' for the document in front, then the extras."""
        if self._drawing_in_front():
            return []
        rows = [(self._title(sub, len(subs)), sub is active) for sub in subs]
        if not rows and App.ActiveDocument is not None:
            rows = [("Model", True)]
        rows += [(t, a) for t, _k, _p, a in self.extras()]
        if not getattr(self, "_logged", False):
            self._logged = True
            App.Console.PrintLog("FreeCAD model tabs: mdi=%s views=%d tabs=%s\n"
                                 % (type(self.mdi).__name__ if self.mdi is not None else None, len(subs),
                                    [r[0] for r in rows]))
        return rows

    def extras(self):
        ""


        out = []
        if _drawing_in_front():
            return out
        try:
            from . import views3d
            dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "SW3DViewsDock")
            out.append(("3D Views", "views3d", None, dock is not None and dock.isVisible()))
        except Exception as _fw_err:
            _fw_log("chrome.py:1043", _fw_err)
        try:
            from . import asmcore, asmmotion
            asm = asmcore.assembly_of(App.ActiveDocument)
            if asm is not None:
                pane = asmmotion.pane()
                shown = getattr(pane, "sim", None)
                found = list(asmmotion.studies(asm))
                for sim in found:
                    out.append((sim.Label, "motion", (asm, sim), shown is sim))
                if not found:
                    out.append(("Motion Study 1", "motion_new", asm, False))
            elif App.ActiveDocument is not None:
                from . import partmotion       # a part: an Animation study (Rotate Model, Play, Save Animation)
                out.append(("Motion Study 1", "partmotion", None, partmotion.shown()))
        except Exception as _fw_err:
            _fw_log("chrome.py:1059", _fw_err)
        return out

    def _open_extra(self, title, kind, payload):
        try:
            if kind == "views3d":
                from . import views3d
                views3d.show_pane()
            elif kind == "motion":
                from . import asmmotion
                asmmotion.show_pane(*payload)
            elif kind == "motion_new":
                from . import asmmotion
                asmmotion.show_pane(payload, asmmotion.new_study(payload))
            elif kind == "partmotion":
                from . import partmotion
                partmotion.show_pane()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: %s tab: %s\n" % (title, error))

    def _title(self, sub, count=None):
        ""


        if count is None:
            count = len(self.subwindows())
        if count == 1:
            return "Model"
        w = sub.widget()
        title = (w.windowTitle() if w is not None else sub.windowTitle()) or "Model"
        return title.replace("[*]", "")

    def refresh(self):
        subs = self.subwindows()
        try:
            from . import drawsheet
            drawsheet.place_row_bars(self)          # drawrow-1121: a drawing's sheet tabs are this row
        except Exception as error:
            _fw_log("chrome.drawrow", error)
        active = (self.mdi.activeSubWindow() or self.mdi.currentSubWindow()) if self.mdi is not None and alive(self.mdi) else None
        sig = tuple((id(s), self._title(s, len(subs)), s is active) for s in subs) + \
            tuple((t, k, a) for t, k, _p, a in self.extras())
        if sig != self._signature:
            self._signature = sig
            self.update()

    def _activate(self, index):
        subs = self.subwindows()
        if 0 <= index < len(subs):
            self.mdi.setActiveSubWindow(subs[index])
            try:
                from . import partmotion
                partmotion.hide_pane()
            except Exception as _fw_err:
                _fw_log("chrome.py:1108", _fw_err)
            return
        extras = self.extras()
        i = index - (len(subs) or (1 if App.ActiveDocument is not None else 0))   # the fallback 'Model' row
        if 0 <= i < len(extras):
            title, kind, payload, _active = extras[i]
            self._open_extra(title, kind, payload)

    def _nav(self, which):
        if self._drawing_in_front():
            try:
                from . import drawsheet
                drawsheet.row_nav(self, which)      # drawrow-1121: a drawing's arrows step through its sheets
            except Exception as error:
                _fw_log("chrome.drawrow-nav", error)
            return
        subs = self.subwindows()
        if not subs:
            return
        active = (self.mdi.activeSubWindow() or self.mdi.currentSubWindow())
        i = subs.index(active) if active in subs else 0
        target = {0: 0, 1: max(0, i - 1), 2: min(len(subs) - 1, i + 1), 3: len(subs) - 1}[which]
        self._activate(target)

    def _hit(self, x):
        if x < self.nav_w:
            return ("nav", min(3, int(x // (self.nav_w / 4.0))))
        for i, (a, b) in enumerate(self._spans):
            if a <= x < b:
                return ("tab", i)
        return None

    def mousePressEvent(self, e):
        hit = self._hit(e.position().x())
        if not hit:
            return
        kind, i = hit
        if e.button() == Qt.LeftButton:
            if kind == "nav":
                self._nav(i)
            else:
                self._activate(i)
        elif e.button() == Qt.RightButton and kind == "tab":
            subs = self.subwindows()
            if i < len(subs):
                menu = QtWidgets.QMenu(self)
                close = menu.addAction("Close")
                close.triggered.connect(lambda checked=False, sub=subs[i]: (alive(sub) and sub.close(), self.refresh()))
                popup_menu(menu, e.globalPosition().toPoint())
        self.refresh()

    def mouseMoveEvent(self, e):
        hit = self._hit(e.position().x())
        h = hit[1] if hit and hit[0] == "tab" else -1
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        dpr = self.devicePixelRatioF()
        W, H = dev(self.width(), dpr), dev(self.height(), dpr)
        subs = self.subwindows()
        active = (self.mdi.activeSubWindow() or self.mdi.currentSubWindow()) if self.mdi is not None and alive(self.mdi) else None
        p.save()
        p.scale(1.0 / dpr, 1.0 / dpr)
        p.fillRect(0, 0, W, H, T.pane)
        p.fillRect(0, 0, W, 1, T.line)
        p.fillRect(0, H - 1, W, 1, T.line)
        # navigation buttons
        nav = dev(self.nav_w, dpr)
        bw = nav // 4
        for j in range(4):
            x = 2 + j * bw
            p.fillRect(x, 3, bw - 2, H - 6, T.base)
            p.fillRect(x, H - 4, bw - 2, 1, T.tab_underline)
        p.fillRect(nav + 1, 1, 1, H - 2, T.line)
        x = nav + 2
        spans = []
        bold, normal = ui_font(True), ui_font(False)
        rows = self._rows(subs, active)
        for title, is_active in rows:
            font = bold if is_active else normal
            w = dev(QtGui.QFontMetricsF(font).horizontalAdvance(title) + 2 * self.PAD * self.k, dpr)
            fill = T.pane if is_active else (T.tab_hover if len(spans) == self._hover else T.tab)
            p.fillRect(x, 1, w, H - 2, fill)
            p.fillRect(x + w, 1, 1, H - 2, T.line)
            spans.append((x, x + w))
            x += w + 1
        p.restore()
        self._spans = [(a / dpr, b / dpr) for a, b in spans]
        # arrow glyphs
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(T.glyph)
        cy = self.height() / 2.0
        step = self.nav_w / 4.0
        k = self.k
        for j in range(4):
            cx = 1 + j * step + step / 2.0
            sign = -1 if j < 2 else 1
            path = QtGui.QPainterPath()
            path.moveTo(cx - 2 * k * sign, cy - 3 * k)
            path.lineTo(cx + 2 * k * sign, cy)
            path.lineTo(cx - 2 * k * sign, cy + 3 * k)
            path.closeSubpath()
            p.drawPath(path)
            if j in (0, 3):
                bar = cx - 3 * k if j == 0 else cx + 2.5 * k
                p.drawRect(QtCore.QRectF(bar, cy - 3 * k, 0.8 * k, 6 * k))
        p.setBrush(Qt.NoBrush)
        for i, (title, is_active) in enumerate(rows):
            if i >= len(self._spans):
                break
            a, b = self._spans[i]
            p.setFont(bold if is_active else normal)
            p.setPen(T.text)
            p.drawText(QtCore.QPointF(a + self.PAD * self.k, 13.0 * self.k), title)
        p.end()


def sketch_state(sketch):
    ""

    try:

        # unsolvable, only redundant ones make it over defined. FreeCAD marks both Invalid.
        if sketch.ConflictingConstraints or sketch.MalformedConstraints:
            return "No Solution Found"
        if sketch.RedundantConstraints:
            return "Over Defined"
        if "Invalid" in sketch.State:

            # updated because the result would be invalid geometry (study 06)
            return "Invalid Solution Found"
        count = getattr(sketch, "GeometryCount", None)   # fix232: no copy of every curve at each status tick
        if (count == 0) if count is not None else not sketch.Geometry:
            return "Under Defined"
        fully = getattr(sketch, "FullyConstrained", None)
        if fully is None:
            fully = sketch.DoF == 0
        return "Fully Defined" if fully else "Under Defined"
    except Exception:
        return ""


def _length_text(value):
    try:
        return App.Units.Quantity(value, App.Units.Length).UserString
    except Exception:
        return "%.4g mm" % value


def _decimals(kind="length"):
    """The document's decimals as the Units page sets them (Length: FreeCAD's Decimals preference; Angle row)."""   # look-audit sbarfmt-1120
    try:
        from . import unitspage
        n = unitspage.angle_decimals() if kind == "angle" else unitspage.decimals()
        return max(0, min(8, int(n)))
    except Exception:
        return 2


def _trim(value, n=None):
    ""
    text = "%.*f" % (_decimals() if n is None else n, value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _point_text(point):
    ""
    return ",".join(_measure_text(v) for v in (point.x, point.y, point.z))      # '0mm,44mm,-228mm': no trailing zeros


def _area_text(value):
    try:
        shown, factor, unit = App.Units.Quantity(10.0, App.Units.Length).getUserPreferred()
        value = value / (factor * factor)
    except Exception:
        unit = "mm"
    return _trim(value) + unit + "^2"


def _sketch_point(sketch, name):
    """A picked sketch point ('Vertex3', 'RootPoint') in sketch coordinates, else None."""
    try:
        if name == "RootPoint":
            return App.Vector(0, 0, 0)
        if name.startswith("Vertex"):
            geo, pos = sketch.getGeoVertexIndex(int(name[6:]) - 1)
            return sketch.getPoint(geo, pos)
    except Exception as _fw_err:
        _fw_log("chrome.py:sketchpoint", _fw_err)
    return None


def _picked_shapes(sketch=None):
    """The points, edges and faces picked, as shapes: sketch geometry in sketch coordinates when a
    sketch is in edit, model sub-shapes otherwise. None when something without a measurement is
    picked (an axis, a constraint)."""
    import Part
    shapes = []
    for sel in Gui.Selection.getSelectionEx():
        if sketch is not None:
            if sel.Object != sketch:
                continue
            for name in sel.SubElementNames:
                if name.startswith("Edge"):
                    shapes.append(sketch.Geometry[int(name[4:]) - 1].toShape())
                    continue
                point = _sketch_point(sketch, name)
                if point is None:
                    return None     # an axis or a relation: no readout
                shapes.append(Part.Vertex(point))
        else:
            shapes.extend(s for s in sel.SubObjects if s.ShapeType in ("Vertex", "Edge", "Face"))
    return shapes


def _angle_text(degrees):
    return _trim(degrees, _decimals("angle")) + "deg"


def _straight(shape):
    return shape.ShapeType == "Edge" and type(shape.Curve).__name__ in ("Line", "LineSegment")


def _direction(edge):
    return (edge.Vertexes[-1].Point - edge.Vertexes[0].Point).normalize()


def _one_readout(shape):
    kind = shape.ShapeType
    if kind == "Vertex":
        p = shape.Point
        return "X: %s Y: %s Z: %s" % (_measure_text(p.x), _measure_text(p.y), _measure_text(p.z))
    if kind == "Edge":
        curve = type(shape.Curve).__name__
        if curve == "Circle":
            if shape.isClosed():
                return "Diameter: " + _measure_text(2 * shape.Curve.Radius) + "  Center: " + _point_text(shape.Curve.Center)
            return "Arc Length: " + _measure_text(shape.Length)
        return "Length: " + _measure_text(shape.Length)
    if kind == "Face":
        surface = type(shape.Surface).__name__
        if surface == "Cylinder":
            return "Diameter: " + _measure_text(2 * shape.Surface.Radius)
        if surface == "Plane":
            perimeter = sum(e.Length for e in shape.OuterWire.Edges)
            return "Area: " + _area_text(shape.Area) + "  Perimeter: " + _measure_text(perimeter)
        return "Area: " + _area_text(shape.Area)
    return ""


def _two_readout(a, b, sketch=None):
    kinds = (a.ShapeType, b.ShapeType)
    edges = kinds == ("Edge", "Edge")
    total = (" Total Length: " + _measure_text(a.Length + b.Length)) if edges else ""
    if edges and all(type(e.Curve).__name__ == "Circle" for e in (a, b)):
        gap = (a.Curve.Center - b.Curve.Center).Length
        return "Distance between circular centers: " + _measure_text(gap)
    if kinds == ("Face", "Face") and all(type(f.Surface).__name__ == "Plane" for f in (a, b)):
        na, nb = a.normalAt(0, 0), b.normalAt(0, 0)
        if abs(abs(na.dot(nb)) - 1) < 1e-9:
            gap = abs((b.Vertexes[0].Point - a.Vertexes[0].Point).dot(na))
            return "Normal Distance: " + _measure_text(gap)
        import math
        return "Angle: " + _angle_text(math.degrees(na.getAngle(nb)))
    if edges and _straight(a) and _straight(b):
        da, db = _direction(a), _direction(b)
        if abs(abs(da.dot(db)) - 1) < 1e-9:
            off = b.Vertexes[0].Point - a.Vertexes[0].Point
            gap = (off - da * off.dot(da)).Length
            return "Normal Distance: " + _measure_text(gap) + total
        import math
        angle = math.degrees(da.getAngle(db))
        return "Angle: " + _angle_text(min(angle, 180 - angle)) + total
    dist, pairs, _info = a.distToShape(b)
    p, q = pairs[0]
    d = q - p
    return "Distance: %s dX: %s dY: %s dZ: %s%s" % (_measure_text(dist), _measure_text(d.x), _measure_text(d.y),
                                                   _measure_text(d.z), total)


def selection_readout(sketch=None):
    ""








    try:
        shapes = _picked_shapes(sketch)
    except Exception:
        return ""
    if not shapes:
        return ""
    try:
        if len(shapes) == 1:
            return _one_readout(shapes[0])
        if len(shapes) == 2:
            return _two_readout(shapes[0], shapes[1], sketch)
        if all(s.ShapeType == "Edge" for s in shapes):
            return "Total Length: " + _measure_text(sum(s.Length for s in shapes))
        if all(s.ShapeType == "Face" for s in shapes):
            return "Total Area: " + _area_text(sum(f.Area for f in shapes))
    except Exception as _fw_err:
        _fw_log("chrome.py:readout", _fw_err)
    return ""


def sketch_readout(sketch):
    """The sketch-edit readout: the picked sketch entities' measurement (selection_readout)."""
    return selection_readout(sketch)


def _measure_text(value):
    ""
    try:
        shown, factor, unit = App.Units.Quantity(10.0, App.Units.Length).getUserPreferred()
        value, unit = value / factor, unit
    except Exception:
        unit = "mm"
    return _trim(value) + unit


def hover_readout():
    ""


    try:
        pre = Gui.Selection.getPreselection()
        from . import teardown
        try:
            obj = pre.Object
        except Exception:
            return ""           # its document closed under the pointer
        if obj is not None and not teardown.alive(obj):
            return ""
        shapes = list(getattr(pre, "SubObjects", ()) or ())
        if not shapes and pre.Object is not None and pre.SubElementNames:
            shapes = [pre.Object.getSubObject(pre.SubElementNames[0])]
        if len(shapes) != 1 or shapes[0] is None:
            return ""
        shape = shapes[0]
        kind = shape.ShapeType
        if kind == "Face":
            surface = shape.Surface
            if type(surface).__name__ == "Cylinder":
                return "Diameter: " + _measure_text(2 * surface.Radius)
            return ""
        if kind == "Edge":
            curve = type(shape.Curve).__name__
            if curve == "Circle":
                return "Radius: " + _measure_text(shape.Curve.Radius) + " Center: " + _point_text(shape.Curve.Center)
            if curve in ("Line", "LineSegment"):
                return "Length: " + _measure_text(shape.Length)
    except Exception as _fw_err:
        _fw_log("chrome.py:1377", _fw_err)
    return ""


def _coordinate_text(value):
    ""
    try:
        # the document's length unit, not one scaled to the value (FreeCAD writes 25 µm)
        shown, factor, unit = App.Units.Quantity(10.0, App.Units.Length).getUserPreferred()
        value = value / factor
        return _trim(value) + unit
    except Exception:
        return _trim(value) + "mm"


def pointer_position(sketch):
    ""


    try:
        view = Gui.ActiveDocument.ActiveView
        widget = view.graphicsView() if hasattr(view, "graphicsView") else None
        if widget is not None:
            local = widget.viewport().mapFromGlobal(QtGui.QCursor.pos())
            if not widget.viewport().rect().contains(local):
                return ""
        x, y = view.getCursorPos()
        point = view.getPoint(x, y)
        direction = view.getViewDirection()
        inverse = sketch.getGlobalPlacement().inverse()
        start = inverse.multVec(point)
        along = inverse.Rotation.multVec(direction)
        if abs(along.z) < 1e-9:
            return ""
        at = start - along * (start.z / along.z)
    except Exception:
        return ""
    zero = _coordinate_text(0.0)
    return "%s    %s    %s" % (_coordinate_text(at.x), _coordinate_text(at.y), zero)


_WARNING_PNG = []


def _warning_png():
    """A yellow warning triangle with a black "!" as a PNG in FreeCAD's cache folder, for the
    status bar's rich text (a QLabel takes images by path)."""
    if _WARNING_PNG:
        return _WARNING_PNG[0]
    path = ""
    try:
        import os
        path = os.path.join(App.getUserCachePath(), "swstyle-warning.png")
        side = 64
        image = QtGui.QImage(side, side, QtGui.QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        triangle = QtGui.QPolygonF([QtCore.QPointF(side / 2, 3), QtCore.QPointF(side - 3, side - 4),
                                    QtCore.QPointF(3, side - 4)])
        painter.setPen(QtGui.QPen(QtGui.QColor(120, 90, 0), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(QtGui.QColor(255, 204, 0))
        painter.drawPolygon(triangle)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor(0, 0, 0))
        painter.drawRoundedRect(QtCore.QRectF(side / 2 - 3.5, side * 0.30, 7, side * 0.36), 3, 3)
        painter.drawEllipse(QtCore.QPointF(side / 2, side * 0.79), 4.5, 4.5)
        painter.end()
        if not image.save(path, "PNG"):
            path = ""
    except Exception as error:
        App.Console.PrintLog("FreeCAD: warning icon not made: %s\n" % error)
        path = ""
    url = QtCore.QUrl.fromLocalFile(path).toString() if path else ""     # file:///C:/... on Windows
    _WARNING_PNG.append(url)
    return url


class _Balloon(QtWidgets.QFrame):
    ""


    def __init__(self, title, text, action, parent=None):
        super().__init__(parent, Qt.ToolTip)
        self.setObjectName("SWNoticeBalloon")
        self.action = action
        self.setFrameShape(QtWidgets.QFrame.Box)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        head = QtWidgets.QLabel(title, self)
        font = ui_font()
        font.setBold(True)
        head.setFont(font)
        body = QtWidgets.QLabel(text, self)
        body.setFont(ui_font())
        layout.addWidget(head)
        layout.addWidget(body)
        self.title, self.text = title, text
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        self.close()
        try:
            self.action()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s\n" % error)


class StatusInfo(QtWidgets.QLabel):
    ""



    OVER_TIP = "The sketch is over defined. Click here to resolve the conflict."
    UNSOLVED_TIP = "The sketch is unsolvable. Click here to resolve the conflict."
    FIXED_TIP = "The sketch is no longer over defined."
    SOLVED_TIP = "The sketch can now find a valid solution."
    VALID_TIP = "The sketch can now find a solution with valid geometry."
    INVALID_TIP = ("The sketch has not been updated because solving it would result in invalid geometry "
                   "(such as a zero-length line).  Consider :\n o Deleting the invalid geometry.\n"
                   " o Changing relations or dimensions to eliminate the invalid geometry.")
    BAD = ("Over Defined", "No Solution Found", "Invalid Solution Found")
    TIPS = {"over": OVER_TIP, "unsolved": UNSOLVED_TIP, "invalid": INVALID_TIP}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWStatusInfo")
        self.setFont(ui_font())
        self.setMinimumWidth(150)

        # the left (coordinates, sketch state), see shots/01, 03, 07 (statusbar-1119)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Relations on the conflicting relations when SketchXpert isn't there).
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.linkActivated.connect(self._resolve)
        self.linkHovered.connect(lambda link: self.setToolTip(
            self.TIPS.get(link, self.OVER_TIP) if link else ""))
        self.plain = ""             # the text without markup, for checks and other readers
        self.last = (None, "")      # (sketch name, state) of the last refresh
        self.notice = ""            # the last one-shot notice shown, for checks
        self.balloon = None
        # the pointer coordinates follow the mouse while sketching: refresh faster then
        self.fast = QtCore.QTimer(self)
        self.fast.setInterval(80)
        self.fast.timeout.connect(self.refresh)

    def _resolve(self, _link=None):
        try:
            from . import contextbar, sketchxpert
            sketch = contextbar.sketch_in_edit()
            if sketch is not None:
                sketchxpert.open_for(sketch)
                return
        except Exception as error:
            App.Console.PrintLog("FreeCAD: SketchXpert not opened: %s\n" % error)
        try:
            from . import relationspm, shell
            pm = getattr(shell.shell(), "relations_pm", None)
            if pm is not None:
                pm.display_delete(relationspm.DD_BAD)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Display/Delete Relations not opened: %s\n" % error)

    def _markup(self, text):
        html = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("    ", "&nbsp;" * 4)
        for words, link in (("Over Defined", "over"), ("No Solution Found", "unsolved"),
                            ("Invalid Solution Found", "invalid")):
            if words not in text:
                continue
            red = "#ff6b6b" if style.dark() else "#e00000"

            warn = _warning_png()
            size = self.fontMetrics().height() - 2
            mark = '<img src="%s" width="%d" height="%d" style="vertical-align:middle">&nbsp;' % (warn, size, size) \
                if warn else ""
            html = html.replace(words, '%s<a href="%s" style="color:%s; text-decoration:none">%s</a>'
                                % (mark, link, red, words), 1)
        return html

    def _notify(self, name, state):
        ""

        before_name, before = self.last
        self.last = (name, state)
        if name is None or name != before_name or state == before:
            return
        if state == "No Solution Found":
            self.notice = self.UNSOLVED_TIP
            self._show_balloon("Unsolvable", self.UNSOLVED_TIP)
        elif before in self.BAD and state not in self.BAD:
            # one note for each way back (study 12 batch 4)
            tip = {"Over Defined": self.FIXED_TIP, "No Solution Found": self.SOLVED_TIP,
                   "Invalid Solution Found": self.VALID_TIP}[before]
            self.notice = tip
            self._hide_balloon()
            QtWidgets.QToolTip.showText(self.mapToGlobal(QtCore.QPoint(0, -self.height())), tip, self)

    def _show_balloon(self, title, text):
        self._hide_balloon()
        balloon = _Balloon(title, text, self._resolve, self.window())
        balloon.adjustSize()
        win = self.window()
        corner = win.mapToGlobal(QtCore.QPoint(win.width(), win.height()))
        bar = self.height() + 8
        balloon.move(corner.x() - balloon.width() - 12, corner.y() - bar - balloon.height())
        balloon.show()
        self.balloon = balloon
        QtCore.QTimer.singleShot(8000, self._hide_balloon)

    def _hide_balloon(self):
        if self.balloon is not None:
            try:
                self.balloon.close()
            except RuntimeError as _fw_err:
                _fw_log("chrome.py:1590", _fw_err)
            self.balloon = None

    def text(self):
        return self.plain

    def refresh(self):
        text = ""
        sketching = False
        try:
            gdoc = Gui.ActiveDocument
            if gdoc is not None:
                edit = gdoc.getInEdit()
                # an active assembly is in edit through its C++ view provider, which has no .Object
                obj = getattr(edit, "Object", None) if edit is not None else None
                if obj is not None and obj.TypeId == "Sketcher::SketchObject":
                    text = "Editing " + obj.Label
                    sketching = True
                    state = sketch_state(obj)
                    self._notify(obj.Name, state)
                    if state:
                        text = state + "    " + text
                    readout = sketch_readout(obj) or hover_readout() or pointer_position(obj)
                    if readout:
                        text = readout + "    " + text
                    if _sketch_tool_running():
                        text += " (Locked Focus)"
                else:
                    text = "Editing " + editing_what()
                    if _drawing_in_front():
                        text = "Under Defined    " + text
                    readout = hover_readout() or selection_readout()
                    if readout:
                        text = readout + "    " + text
                    self.last = (None, "")
                    self._hide_balloon()
        except Exception:
            text = ""
        if sketching != self.fast.isActive():
            self.fast.start() if sketching else self.fast.stop()
        if text != self.plain:
            self.plain = text
            self.setText(self._markup(text))
        self._hold_width(sketching)

    def _hold_width(self, sketching):
        ""


        try:
            base = 150
            want = self.sizeHint().width()
            self.setMinimumWidth(max(self.minimumWidth(), want, base) if sketching else base)
            beside = self.parentWidget().findChild(QtWidgets.QWidget, "SWSimplifiedInterface") \
                if self.parentWidget() is not None else None
            gap = scaled(12) if beside is not None and beside.isVisible() else scaled(84)
            if self.contentsMargins().right() != gap:
                self.setContentsMargins(0, 0, gap, 0)
        except Exception as _fw_err:
            _fw_log("chrome.py:StatusInfo._hold_width", _fw_err)


def editing_what():
    """What the status bar says is being edited outside a sketch: Part, Assembly or the drawing sheet."""
    try:
        from . import swmenus
        if swmenus.drawing_in_front():
            try:
                from . import drawings
                page = drawings.active_page()
                if page is not None:
                    try:
                        from . import drawsheet
                        tpl = getattr(page, "Template", None)
                        if tpl is not None and drawsheet.editing_format(page):
                            return tpl.Label
                    except Exception as _fw_err:
                        _fw_log("chrome.py:sheet format", _fw_err)
                    return page.Label
            except Exception as _fw_err:
                _fw_log("chrome.py:1645", _fw_err)
            return "Sheet"
    except Exception as _fw_err:
        _fw_log("chrome.py:1648", _fw_err)
    try:
        from . import asmcore, asmreview
        if asmcore.is_assembly() or asmreview.is_review(App.ActiveDocument):    # also Large Design Review
            return "Assembly" + _open_mode_suffix()
    except Exception as _fw_err:
        _fw_log("chrome.py:1654", _fw_err)
    return "Part" + _open_mode_suffix()


def _open_mode_suffix():
    ""
    try:
        from . import saveas
        mode = saveas.open_mode()
    except Exception:
        mode = ""
    return " (%s)" % mode if mode else ""


def _sketch_tool_running():
    try:
        from . import contextbar, shell
        s = shell.shell()
        return s is not None and contextbar.tool_running(s)
    except Exception:
        return False


class RebuildIndicator(QtWidgets.QToolButton):
    ""


    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWRebuildIndicator")
        self.setAutoRaise(True)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.setIcon(icons.family("STANDARD_REBUILD"))
        self.setIconSize(QtCore.QSize(scaled(16), scaled(16)))
        self.setToolTip("Rebuild (Ctrl+B): the model has changed since its last rebuild")
        self.clicked.connect(self._rebuild)
        self.needed = False
        self.setVisible(False)          # shown only while a rebuild is needed (status241)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        try:
            from . import ticks as _ticks
            _ticks.slow_when_idle(self.timer)
        except Exception as _fw_err:
            __import__("FreeCAD").Console.PrintLog("FreeCAD ticks: %s\n" % _fw_err)
        self.refresh()

    @staticmethod
    def rebuild_needed(doc=None):
        doc = doc or App.ActiveDocument
        if doc is None:
            return False
        try:
            # DocumentObject.mustExecute is not exposed to Python in FreeCAD 1.1: the indicator never showed
            if doc.isTouched():
                return True
            return any("Touched" in o.State or "Invalid" in o.State for o in doc.Objects)
        except Exception:
            return False

    def refresh(self):
        needed = self.rebuild_needed()
        if needed != self.needed:
            self.needed = needed
            self.setVisible(needed)

    def _rebuild(self):
        try:
            from . import keys
            keys.rebuild()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: rebuild: %s\n" % error)
        self.refresh()


def document_title():
    ""

    # winmenu-1119
    try:
        doc = App.ActiveDocument
        if doc is None:
            return ""
        text = __import__("os").path.basename(doc.FileName) if doc.FileName else doc.Label
        gdoc = Gui.ActiveDocument
        try:

            edit = gdoc.getInEdit() if gdoc is not None else None
            obj = getattr(edit, "Object", None) if edit is not None else None
            if obj is None or obj.TypeId != "Sketcher::SketchObject":
                s3d = __import__("sys").modules.get(__name__.rsplit(".", 1)[0] + ".sketch3d")
                obj = s3d.editing() if s3d is not None else None      # a 3D sketch: "3DSketch1 of Part1"
            if obj is not None and getattr(obj, "Document", None) is doc:
                text = "%s of %s" % (obj.Label, text)
        except Exception as _fw_err:
            _fw_log("chrome.py:document_title", _fw_err)
        if gdoc is not None and getattr(gdoc, "Modified", False):
            text += " *"
        return text
    except Exception:
        return ""


# --------------------------------------------------------------------------- status bar
def _short_class(widget):
    try:
        return widget.metaObject().className().split("::")[-1]
    except Exception:
        return ""



# area FreeCAD parks toolbars in, and the navigation style button the Tux module adds.

# one measurement, the StatusInfo's own ("Area: 1200mm^2  Perimeter: 140mm").
STATUS_EXTRAS = ("StatusBarArea", "NavigationIndicator", "rightSideLabel")


def freecad_status_items(status_bar):
    ""


    found = []
    for widget in status_bar.findChildren(QtWidgets.QWidget):
        if widget.parentWidget() is not status_bar:
            continue
        if widget.objectName() in STATUS_EXTRAS or _short_class(widget) == "DimensionWidget":
            found.append(widget)
    return found


UNITS = "User parameter:BaseApp/Preferences/Units"


UNIT_NAMES = {"Internal": "MMGS", "MKS": "MKS", "Imperial": "IPS", "ImperialDecimal": "IPS",
              "Centimeter": "CGS", "ImperialBuilding": "Custom", "MmMin": "MMGS",
              "ImperialCivil": "Custom", "FEM": "MMGS", "MeterDecimal": "MKS"}
# ... and by the length unit in a schema description, for FreeCAD versions that list those
UNIT_SYSTEMS = {"mm": "MMGS", "m": "MKS", "cm": "CGS", "in": "IPS"}


def schema_label(name, description=""):
    ""

    if name in UNIT_NAMES:
        return UNIT_NAMES[name]
    text = description or name
    inside = text.split("(", 1)[1].split(")", 1)[0] if "(" in text else text
    first = inside.split(",")[0].strip().split("/")[0].split(" ")[0].split("-")[0]
    return UNIT_SYSTEMS.get(first, "Custom" if "(" in text else (first or text[:6]))


def schemas():
    """[(name, description)] of FreeCAD's unit schemas in index order. FreeCAD 1.1
    lists names and describes one schema per index; older versions list descriptions."""
    try:
        names = [str(name) for name in App.Units.listSchemas()]
    except Exception:
        return []
    out = []
    for index, name in enumerate(names):
        try:
            description = str(App.Units.listSchemas(index))
        except Exception:
            description = name
        out.append((name, description))
    return out


def current_schema():
    try:
        return int(App.Units.getSchema())
    except Exception:
        try:
            return App.ParamGet(UNITS).GetInt("UserSchema", 0)
        except Exception:
            return 0


def set_schema(index):
    """What FreeCAD's own status bar button does: the document's unit system when a
    document is open, the preference otherwise, then the live schema."""
    try:
        doc = App.ActiveDocument
        if doc is not None and hasattr(doc, "UnitSystem"):
            if doc.UnitSystem != index:
                doc.UnitSystem = index
        else:
            App.ParamGet(UNITS).SetInt("UserSchema", index)
        App.Units.setSchema(index)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: unit system not changed: %s\n" % error)
        return
    try:
        Gui.updateGui()
    except Exception as _fw_err:
        _fw_log("chrome.py:1834", _fw_err)


class UnitsButton(QtWidgets.QToolButton):
    ""


    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWUnits")
        self.setFont(ui_font())
        self.setAutoRaise(True)
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.setToolTip("Unit System")
        self._menu = QtWidgets.QMenu(self)
        group_class = getattr(QtGui, "QActionGroup", None) or QtWidgets.QActionGroup
        self._group = group_class(self._menu)
        self._group.setExclusive(True)
        self._group.triggered.connect(self._choose)
        self.setMenu(self._menu)

        self.setStyleSheet("QToolButton#SWUnits::menu-indicator { image: none; width: 0px; }"
                           "QToolButton#SWUnits { padding-left: 6px; padding-right: 34px; }")
        self._known = None
        self.refresh()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        c = self.palette().color(QtGui.QPalette.WindowText if self.isEnabled() else QtGui.QPalette.Mid)
        c.setAlpha(150)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        x = self.width() - 14.0
        y = self.height() / 2.0 + 1.0
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x - 3, y + 1.5), QtCore.QPointF(x + 3, y + 1.5), QtCore.QPointF(x, y - 2)]))
        p.end()

    def _choose(self, action):
        set_schema(int(action.data()))
        self.refresh()


    SYSTEMS = (("MKS", "MKS (meter, kilogram, second)", ("MKS",)),
               ("CGS", "CGS (centimeter, gram, second)", ("Centimeter",)),
               ("MMGS", "MMGS (millimeter, gram, second)", ("Internal", "Standard")),
               ("IPS", "IPS (inch, pound, second)", ("ImperialDecimal", "Imperial")))

    def _schema_index(self, schema_names):
        names = [n for n, _d in schemas()]
        for wanted in schema_names:
            if wanted in names:
                return names.index(wanted)
        return -1

    def refresh(self):
        names = schemas()
        if names != self._known:
            self._known = names
            self._menu.clear()
            for label, text, schema_names in self.SYSTEMS:
                index = self._schema_index(schema_names)
                action = self._menu.addAction(text)
                action.setCheckable(True)
                action.setData(index)
                action.setEnabled(index >= 0)
                self._group.addAction(action)

            self._custom = self._menu.addAction("Custom...")
            self._custom.setObjectName("SWUnitsCustom")
            self._custom.setCheckable(True)
            self._custom.triggered.connect(lambda _checked=False: self.edit_document_units(custom=True))
            self._menu.addSeparator()
            edit = self._menu.addAction("Edit Document Units...")
            edit.setObjectName("SWUnitsEdit")
            edit.triggered.connect(lambda _checked=False: self.edit_document_units())
        index = current_schema()
        label = schema_label(*names[index]) if 0 <= index < len(names) else ""
        if label != self.text():
            self.setText(label)
        for action in self._group.actions():
            action.setChecked(action.data() == index)
        custom = getattr(self, "_custom", None)
        if custom is not None:
            try:
                from . import unitspage
                custom.setChecked(unitspage.system_of(index) == "Custom")
            except Exception:
                custom.setChecked(False)

    def edit_document_units(self, custom=False):
        ""
        try:
            from . import options
            box = options.OptionsDialog(tab=1)
            tree = getattr(box, "tree", None)
            if tree is not None:
                for item in tree.findItems("Units", Qt.MatchFixedString | Qt.MatchRecursive):
                    tree.setCurrentItem(item)
                    break
            if custom:
                radio = box.findChild(QtWidgets.QRadioButton, "SWUnits_Custom")
                if radio is not None:
                    radio.setChecked(True)
            options._open.append(box)
            try:
                box.exec()
            finally:
                options._open.remove(box)
                box.deleteLater()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Document Properties not opened: %s\n" % error)
            try:
                Gui.runCommand("Std_DlgPreferences", 0)
            except Exception as _fw_err:
                _fw_log("chrome.py:1951", _fw_err)
