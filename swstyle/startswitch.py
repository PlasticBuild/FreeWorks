# SPDX-License-Identifier: LGPL-2.1-or-later
"""startswitch-1127: which start screen FreeCAD opens on, the Welcome dialog (default) or FreeCAD's own
Start page, restyled in the look's theme. A switch button in the bottom right corner of each screen
goes to the other one, and the choice is remembered across restarts. Options > General can hide the
switch; the screen picked last stays.
startblur-1127-v2: the switch is a two-way "Start screen: Welcome | Start Page" control, the picked side lit; with
the Start page picked, the page fills the part window. No blur (Ati 20:44Z)."""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import paths

Qt = QtCore.Qt
SCREEN = "StartScreen"                  # "welcome" (default) or "start"
HIDE = "StartScreenSwitchHidden"        # Options > General: the switch buttons are hidden
START_VIEW = "StartGui::StartView"
BUTTON = "FWStartScreenSwitch"          # the button on the Start page
WELCOME_BUTTON = "SWWelcomeStartSwitch"  # the button on the Welcome dialog
TO_START = "Start Page"
TO_WELCOME = "Welcome"
MARGIN = 14
SAFE_AGE = 3.5      # s: FreeCAD's Start page runs timers just after it opens; closing it sooner crashes FreeCAD

SHEET = """
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget { background: ${pane}; border: none; }
QLabel { color: ${text}; background: transparent; }
QCheckBox { color: ${text}; background: transparent; }
QListView, QListWidget { background: ${pane}; color: ${text}; border: none; }
QPushButton { background: ${base}; color: ${text}; border: 1px solid ${line_light}; border-radius: 3px;
    padding: 6px 10px; }
QPushButton:hover { background: ${hover}; border-color: ${hover_line}; }
QPushButton:pressed { background: ${down}; border-color: ${down_line}; }
QPushButton:focus { border-color: ${accent}; }
"""

PILL_SHEET = """
QFrame#PILL { background: ${base}; border: 1px solid ${line_mid}; border-radius: 6px; }
QFrame#PILL QLabel { color: ${text_dim}; background: transparent; border: none; padding: 0 4px 0 6px; }
QFrame#PILL QToolButton { background: transparent; color: ${text}; border: 1px solid transparent; border-radius: 4px;
    padding: 4px 12px; font-weight: bold; }
QFrame#PILL QToolButton:hover { background: ${hover}; border-color: ${hover_line}; }
QFrame#PILL QToolButton:checked { background: ${accent}; color: #ffffff; border-color: ${accent}; }
"""


def screen():
    """The start screen picked last: "welcome" or "start"."""
    return "start" if paths.params().GetString(SCREEN, "welcome") == "start" else "welcome"


def set_screen(name):
    paths.params().SetString(SCREEN, "start" if name == "start" else "welcome")


def switch_hidden():
    return paths.params().GetBool(HIDE, False)


def set_switch_hidden(on):
    """Options > General. Hiding the switch keeps the screen picked last."""
    paths.params().SetBool(HIDE, bool(on))
    for view in start_views():
        pill = view.findChild(QtWidgets.QFrame, BUTTON)
        if pill is not None:
            pill.setVisible(not on)
    try:
        from . import welcome
        from .widgets import alive
        for box in welcome._open:
            if alive(box):
                pill = box.findChild(QtWidgets.QFrame, WELCOME_BUTTON)
                if pill is not None:
                    pill.setVisible(not on)
    except Exception as _fw_err:
        _fw_log("startswitch.py:hide", _fw_err)


def _area():
    mw = Gui.getMainWindow()
    return mw.findChild(QtWidgets.QMdiArea) if mw else None


def start_views():
    area = _area()
    out = []
    for sub in (area.subWindowList() if area is not None else []):
        try:
            view = sub.widget()
            if view is not None and view.metaObject().className() == START_VIEW:
                out.append(view)
        except RuntimeError:
            continue
    return out


class SwitchPill(QtWidgets.QFrame):
    """startblur-1127: "Start screen:  [Welcome] [Start Page]", the screen in use lit in the accent colour.
    A click on the other side switches now and at start-up; the lit side is the current state (a radio pair)."""

    def __init__(self, parent, name, current):
        super().__init__(parent)
        self.setObjectName(name)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        lay.addWidget(QtWidgets.QLabel("Start screen:", self))
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        self.buttons = {}
        for key, text, tip in (("welcome", TO_WELCOME, "The Welcome screen, now and at start-up."),
                               ("start", TO_START, "FreeCAD's Start page, now and at start-up.")):
            b = QtWidgets.QToolButton(self)
            b.setObjectName(name + "_" + key)
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setChecked(key == current)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _on=False, k=key: self._pick(k))
            group.addButton(b)
            lay.addWidget(b)
            self.buttons[key] = b
        self.restyle()
        self.setVisible(not switch_hidden())

    def restyle(self):
        try:
            from . import style
            self.setStyleSheet(style.fill(PILL_SHEET.replace("PILL", self.objectName())))
        except Exception as _fw_err:
            _fw_log("startswitch.py:pill", _fw_err)

    def _pick(self, key):
        if key == screen() and key == ("start" if self.objectName() == BUTTON else "welcome"):
            return      # the screen shown already is the one picked
        QtCore.QTimer.singleShot(0, use_start if key == "start" else use_welcome)


def welcome_button(parent):
    """The Welcome dialog's switch (its bottom right corner)."""
    return SwitchPill(parent, WELCOME_BUTTON, "welcome")


def use_start():
    """The Start page from now on: the Welcome closes and the Start page opens (styled, with the switch)."""
    from . import welcome
    set_screen("start")
    welcome.sync_start_page()
    from .widgets import alive
    for box in list(welcome._open):
        if alive(box):
            box.close()
    open_start_page()


def use_welcome():
    """The Welcome from now on: the Start page closes and the Welcome opens."""
    from . import welcome
    set_screen("welcome")
    welcome.sync_start_page()
    welcome.show()
    # later, not now: the click came from a button on the Start page itself, and a Start page opened only
    # just now still has FreeCAD's own timers running (a close then crashed FreeCAD in StartGui's slot)
    wait = max([0.0] + [SAFE_AGE - (time.monotonic() - getattr(v, "_fw_born", 0.0)) for v in start_views()])
    QtCore.QTimer.singleShot(int(wait * 1000), _close_if_welcome)


def _close_if_welcome():
    """Closes the Start page if the Welcome is still the pick (the user may have switched back meanwhile)."""
    if screen() == "welcome":
        from . import welcome
        welcome.close_start_page()


def open_start_page():
    """Shows FreeCAD's Start page (the open one, or a new one through Start_Start), styled."""
    views = start_views()
    if views:
        try:
            sub = views[0].parentWidget()
            _area().setActiveSubWindow(sub)
        except Exception as _fw_err:
            _fw_log("startswitch.py:activate", _fw_err)
    else:
        try:
            Gui.runCommand("Start_Start", 0)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Start page: %s\n" % error)
    QtCore.QTimer.singleShot(0, decorate_all)
    QtCore.QTimer.singleShot(400, decorate_all)


class _Corner(QtCore.QObject):
    """Keeps the switch in the view's bottom right corner as the view resizes."""

    def __init__(self, view, button):
        super().__init__(view)
        self.view, self.button = view, button
        view.installEventFilter(self)
        self.place()

    def place(self):
        try:
            hint = self.button.sizeHint()
            self.button.resize(hint)
            bar = 0
            for area in self.view.findChildren(QtWidgets.QScrollArea):
                sb = area.verticalScrollBar()
                if sb is not None and sb.isVisible():
                    bar = max(bar, sb.width())
            x, y = self.view.width() - hint.width() - MARGIN - bar, self.view.height() - hint.height() - MARGIN
            # startblur-1127: kept clear of the page's own bottom row ("Don't show this Start page..." box)
            spot = QtCore.QRect(x, y, hint.width(), hint.height())
            for other in self.view.findChildren(QtWidgets.QAbstractButton):
                if other.isVisible() and not self.button.isAncestorOf(other):
                    r = QtCore.QRect(other.mapTo(self.view, QtCore.QPoint(0, 0)), other.size())
                    if r.intersects(spot):
                        y = min(y, r.top() - hint.height() - 6)
                        spot.moveTop(y)
            self.button.move(x, y)
            self.button.raise_()
        except RuntimeError:
            return

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show, QtCore.QEvent.LayoutRequest):
            QtCore.QTimer.singleShot(0, self.place)
        return False


def _sheet():
    try:
        from . import style
        return style.fill(SHEET)
    except Exception as _fw_err:
        _fw_log("startswitch.py:sheet", _fw_err)
        return ""


def decorate(view):
    """The look's theme on one Start page, and the switch in its bottom right corner."""
    try:
        view.setStyleSheet(_sheet())
        if view.findChild(QtWidgets.QFrame, BUTTON) is None:
            view._fw_born = time.monotonic()
            pill = SwitchPill(view, BUTTON, "start")
            view._fw_corner = _Corner(view, pill)
        else:
            view._fw_corner.place()
    except (RuntimeError, AttributeError) as _fw_err:
        _fw_log("startswitch.py:decorate", _fw_err)


def decorate_all(*_args):
    for view in start_views():
        decorate(view)
    fill_part_window()


def restyle(*_args):
    sheet = _sheet()
    for view in start_views():
        try:
            view.setStyleSheet(sheet)
            pill = view.findChild(QtWidgets.QFrame, BUTTON)
            if pill is not None:
                pill.restyle()
        except RuntimeError:
            continue


# ---------------------------------------------------------------- startblur-1127-v2: the Start page fills the part window
def fill_part_window(*_args):
    """With the Start page picked, its sub-window is maximized so it fills the part window (no blur: Ati 20:44Z)."""
    if screen() != "start":
        return
    for view in start_views():
        try:
            sub = view.parentWidget()
            if sub is not None and not sub.isMaximized():
                sub.showMaximized()
        except RuntimeError:
            continue


def at_startup(start_was_hidden):
    """Start-up with the Start page picked: no Welcome. FreeCAD opens its Start page itself, except on
    the first start-up after the switch (the Welcome had kept it from opening): open it here."""
    if App.listDocuments():
        return
    start = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Start")
    if start_was_hidden and start.GetBool("ShowOnStartup", True) and not start_views():
        open_start_page()
    else:
        decorate_all()
    App.Console.PrintLog("FreeCAD: Start page at start-up\n")


_hooked = []


def start():
    """Every Start page that opens, by any route (Help > Start Page too), gets the theme and the switch."""
    if _hooked:
        return
    area = _area()
    if area is None:
        return
    try:
        area.subWindowActivated.connect(lambda *_: QtCore.QTimer.singleShot(0, decorate_all))
        _hooked.append(area)
    except Exception as _fw_err:
        _fw_log("startswitch.py:hook", _fw_err)
    try:
        from . import style
        style.signals.theme_changed.connect(restyle)
    except Exception as _fw_err:
        _fw_log("startswitch.py:theme", _fw_err)
    decorate_all()
