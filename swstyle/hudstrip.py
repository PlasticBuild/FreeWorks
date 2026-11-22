# SPDX-License-Identifier: LGPL-2.1-or-later
""








_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeWorks %s: %s\n" % (site, err))
    except Exception:
        return


from PySide import QtCore, QtWidgets

BUTTON = 26
MARGIN = 3
STRIPS = ("DisplayStyle", "ViewSettings")


class _Name(QtWidgets.QLabel):
    """A row's name: a click on it is a click on its button."""

    def __init__(self, button, parent):
        super().__init__(button.binding.cmd.label, parent)
        self.button = button
        self.setObjectName("SWHudStripName_" + button.binding.cmd.key)
        self.setContentsMargins(4, 0, 8, 0)

    def mouseReleaseEvent(self, event):
        if self.rect().contains(event.pos()):
            self.button.binding.run()
            QtCore.QTimer.singleShot(0, self.button.parent().menu.close)


class Strip(QtWidgets.QWidget):
    def __init__(self, shell, keys, menu, named=False):
        super().__init__(menu)
        from .widgets import CommandButton
        self.setObjectName("SWHudStrip")
        self.menu = menu
        self.buttons = {}
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        box.setSpacing(2)
        for key in keys:
            try:
                b = CommandButton(shell, key, None, "qat", self)
            except Exception as _fw_err:
                _fw_log("hudstrip.py:button", _fw_err)
                continue
            b.setObjectName("SWHudStrip_" + key)
            b.setFixedSize(BUTTON, BUTTON)
            b.binding.resolve()
            b.binding.update_state()
            b.setToolTip(b.binding.cmd.label)
            b.installEventFilter(self)
            if named:
                row = QtWidgets.QHBoxLayout()
                row.setSpacing(0)
                row.addWidget(b)
                row.addWidget(_Name(b, self), 1)
                box.addLayout(row)
            else:
                box.addWidget(b)
            self.buttons[key] = b

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.MouseButtonRelease and watched.rect().contains(event.pos()):
            QtCore.QTimer.singleShot(0, self.menu.close)     # after the button has run
        return False


def fill_flyout(shell, menu, keys):
    # View Settings' strip (its keys hold Perspective) has names; Display Style's is icons only
    strip = Strip(shell, keys, menu, named="Perspective" in keys)
    act = QtWidgets.QWidgetAction(menu)
    act.setDefaultWidget(strip)
    menu.addAction(act)
    width = strip.sizeHint().width() + 2

    menu._fit = lambda: (menu.setMinimumWidth(width), menu.setMaximumWidth(width))
    menu.setProperty("swHudStrip", True)
    menu.strip = strip
    return menu
