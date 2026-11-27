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


from PySide import QtCore, QtWidgets

COLUMNS = 2
BUTTON = 26
MARGIN = 6

GRID = ("HideAllTypes", None,
        "ViewAllAnnotations", "ToggleAxisCross", "ViewTemporaryAxes", "ViewCameras", "ViewCenterOfMass",
        "ViewBoundingBox", "ViewCoordinateSystems", "ViewCurves", "ViewDimensionNames", "ViewLights",
        "ViewLiveSectionPlanes",    # viewrows-1126: View/display pkg154, MENU 12 order
        "ViewOrigins",
        "ViewPartingLines", "ViewPlanes", "ViewPoints", "ViewSketches", "ViewBendLines", "ViewSketchDimensions",
        "ViewSketchPlanes", "ViewWeldBead", "ViewMarkups", None,
        "ViewDecals",       # bendtable-1126: View/display pkg153, MENU 12 order
        "ViewGrid", "ViewSketchRelations", None,
        "ViewBodies", "ViewPrimaryPlanes")
PICKED = ("ToggleVisibility", "ShowSelection", "HideSelection", "ShowAll")


class Panel(QtWidgets.QWidget):
    def __init__(self, shell, keys, parent=None):
        super().__init__(parent)
        from .widgets import CommandButton
        self.setObjectName("SWHideShowFlyout")
        self.buttons = {}
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        grid.setSpacing(2)
        row = col = 0
        known = set(keys)
        for key in GRID:
            if key is None:
                continue            # the menu's separators: the palette runs on without a break
            if key not in known:
                continue
            try:
                b = CommandButton(shell, key, None, "qat", self)
            except Exception as _fw_err:
                _fw_log("hideshow.py:button", _fw_err)
                continue
            b.setObjectName("SWHideShow_" + key)
            b.setFixedSize(BUTTON, BUTTON)
            b.binding.resolve()
            b.binding.update_state()
            b.installEventFilter(self)
            grid.addWidget(b, row, col)
            self.buttons[key] = b
            col += 1
            if col == COLUMNS:
                row, col = row + 1, 0
        grid.setColumnStretch(COLUMNS, 1)      # the palette stays packed at the left when the menu is wider

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.MouseButtonRelease:
            QtCore.QTimer.singleShot(60, self.refresh)
        return False

    def refresh(self):
        for b in self.buttons.values():
            try:
                b.binding.update_state()
                b.update()
            except Exception as _fw_err:
                _fw_log("hideshow.py:refresh", _fw_err)


def fill_flyout(shell, menu, keys):
    """The grid in the flyout menu, then the pick rows that can do something now."""
    panel = Panel(shell, keys, menu)
    act = QtWidgets.QWidgetAction(menu)
    act.setDefaultWidget(panel)
    menu.addAction(act)
    rows = []
    for key in PICKED:
        if key not in keys:
            continue
        b = shell.binding(key)
        b.resolve()
        b.update_state()
        if b.enabled:
            rows.append(key)
    if rows:
        menu.addSeparator()
        for key in rows:
            shell._add_binding_action(menu, key)
    menu.setProperty("swHideShowPanel", True)
    menu.panel = panel
    return menu
