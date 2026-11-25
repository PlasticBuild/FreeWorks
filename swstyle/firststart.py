# SPDX-License-Identifier: LGPL-2.1-or-later
""







import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import paths, style

WIDGET = "ThemeSelectorWidget"
HOOKED = "swFreeWorksTheme"

BUTTONS = (("FreeCAD Light", "Light"), ("FreeCAD Dark", "Dark"))
_timer = None


def _translated(text):
    return QtWidgets.QApplication.translate("StartGui::ThemeSelectorWidget", text, "Visual theme name")


def _theme_of(button):
    ""
    hooked = button.property(HOOKED)
    if hooked:
        return hooked
    text = button.text()
    for label, theme in BUTTONS:
        if text in (label, _translated(label)):
            return theme
    return None


def _picked(theme):
    if theme == "Dark" and style.theme_name() == "AMOLED":
        theme = "AMOLED"        # AMOLED is the dark look too: a Dark pick keeps it
    try:
        from . import themeoptions
        if themeoptions._live_shell() is not None:
            style.set_theme(theme)
        else:
            # the classic interface is up: kept for the next time the look is switched on
            store = paths.params()
            store.SetString(style.THEME_SETTING, theme)
            store.SetInt(style.SCENE_SETTING, -1)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: theme from the Start page not applied: %s\n" % error)


def _show_current(buttons):
    on = style.theme_name()
    # AMOLED is the dark look too
    on = "Dark" if on == "AMOLED" else on
    for button, theme in buttons:
        if theme == on and not button.isChecked():
            button.setChecked(True)


def _hook(widget):
    buttons = []
    for button in widget.findChildren(QtWidgets.QToolButton):
        theme = _theme_of(button)
        if theme is None:
            continue
        buttons.append((button, theme))
        if button.property(HOOKED):
            continue
        button.setProperty(HOOKED, theme)
        button.clicked.connect(lambda checked=False, t=theme: _picked(t))
    for button, theme in buttons:
        # FreeCAD names them again when the language changes
        name = "FreeCAD " + theme
        if button.text() != name:
            button.setText(name)
    _show_current(buttons)
    return bool(buttons)


def _scan():
    mw = Gui.getMainWindow()
    if mw is None:
        return
    for widget in mw.findChildren(QtWidgets.QWidget, WIDGET):
        try:
            if widget.isVisible() or not widget.property(HOOKED):
                if _hook(widget):
                    widget.setProperty(HOOKED, True)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Start page theme row: %s\n" % error)


def install():
    """Watches for the Start page's theme row (it can be opened again at any time)."""
    global _timer
    if _timer is not None:
        return
    _timer = QtCore.QTimer()
    _timer.setInterval(700)
    _timer.timeout.connect(_scan)
    _timer.start()
    try:
        from . import ticks as _ticks
        _ticks.slow_when_idle(_timer)
    except Exception as _fw_err:
        __import__("FreeCAD").Console.PrintLog("FreeCAD ticks: %s\n" % _fw_err)
