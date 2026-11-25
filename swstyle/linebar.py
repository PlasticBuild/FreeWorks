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

from . import checkstate, lineformat, paths

Qt = QtCore.Qt
NAME = "SWLineFormatToolBar"
PARAM = "LineFormatToolbar"
TICK = 400

TOOLBAR = None


def _params():
    return paths.params()


def _icon(key, pattern, width):
    try:
        from . import catalog, icons
        cmd = catalog.BY_KEY.get(key)
        icon = icons.command_icon(cmd) if cmd is not None else QtGui.QIcon()
        if not icon.isNull():
            return icon
    except Exception as _fw_err:
        _fw_log("linebar.py:43", _fw_err)
    try:
        from . import style
        color = QtGui.QColor("#e6e6e6") if style.dark() else QtGui.QColor(Qt.black)
    except Exception:
        color = QtGui.QColor(Qt.black)
    return lineformat._sample(pattern, width, color)


def _active(name):
    try:
        return lineformat.COMMANDS[name].IsActive()
    except Exception as _fw_err:
        _fw_log("linebar.py:57", _fw_err)
        return False


class LineFormatToolbar(QtWidgets.QToolBar):
    def __init__(self, mw):
        super().__init__("Line Format", mw)
        self.setObjectName(NAME)
        self.setIconSize(QtCore.QSize(20, 20))
        self.buttons = {}
        self._button("SWStyle_LineColor", "LineColor", "Line Color", ("solid", 2.0), None)
        self._button("SWStyle_LineThickness", "LineThickness", "Line Thickness", ("solid", 4.0),
                     lineformat.thickness_menu)
        self._button("SWStyle_LineStyle", "LineStyle", "Line Style", ("dash", 1.5), lineformat.style_menu)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(TICK)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def _button(self, name, key, label, sample, menu_of):
        cmd = lineformat.COMMANDS[name]
        button = QtWidgets.QToolButton(self)
        button.setObjectName("SWLineFormat_" + key)
        button.setIcon(_icon(key, *sample))
        button.setToolTip("<b>%s</b><br>%s" % (label, cmd.tip))
        button.setStatusTip(cmd.tip)
        button.setAutoRaise(True)
        if menu_of is None:
            button.clicked.connect(lambda checked=False, n=name: Gui.runCommand(n, 0))
        else:

            holder = QtWidgets.QMenu(button)
            button.setMenu(holder)
            button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            holder.aboutToShow.connect(lambda h=holder, f=menu_of: self._fill(h, f))
        self.addWidget(button)
        self.buttons[name] = button

    @staticmethod
    def _fill(holder, menu_of):
        holder.clear()
        menu = menu_of(holder)
        for action in list(menu.actions()):
            action.setParent(holder)
            holder.addAction(action)
        holder.setToolTipsVisible(True)
        lineformat.LAST[:] = [holder]

    def refresh(self):
        if not self.isVisible():
            return
        for name, button in self.buttons.items():
            on = _active(name)
            if button.isEnabled() != on:
                button.setEnabled(on)


def toolbar(create=True):
    global TOOLBAR
    if TOOLBAR is not None:
        try:
            TOOLBAR.objectName()
            return TOOLBAR
        except RuntimeError:
            TOOLBAR = None
    mw = Gui.getMainWindow()
    if not create or mw is None:
        return None
    TOOLBAR = LineFormatToolbar(mw)
    mw.addToolBar(Qt.TopToolBarArea, TOOLBAR)
    TOOLBAR.setVisible(False)
    TOOLBAR.visibilityChanged.connect(lambda shown: _params().SetBool(PARAM, shown))
    return TOOLBAR


def shown():
    tb = toolbar(create=False)
    return tb is not None and tb.isVisible()


def toggle():
    tb = toolbar()
    if tb is not None:
        tb.setVisible(not tb.isVisible())
        if tb.isVisible():
            tb.refresh()


class _Toggle:
    def GetResources(self):
        return {"MenuText": "Line Format", "ToolTip": "Shows or hides the Line Format toolbar."}

    def Activated(self, checked=None):
        toggle()

    def IsActive(self):
        return True


_installed = False


def install():
    """The commands, the toggle and the toolbar (built now, so View > Toolbars lists it; shown
    again at start when it was on)."""
    global _installed
    if _installed:
        return
    lineformat.register()
    if "SWStyle_LineFormatToolbar" not in Gui.listCommands():
        Gui.addCommand("SWStyle_LineFormatToolbar", _Toggle())
    checkstate.register("SWStyle_LineFormatToolbar", shown)
    _installed = True
    _when_ready()


def _when_ready(tries=[0]):
    mw = Gui.getMainWindow()
    if mw is None or not mw.isVisible():
        if tries[0] < 100:
            tries[0] += 1
            QtCore.QTimer.singleShot(200, _when_ready)
        return
    tb = toolbar()
    if tb is not None and _params().GetBool(PARAM, False):
        tb.setVisible(True)
        tb.refresh()
