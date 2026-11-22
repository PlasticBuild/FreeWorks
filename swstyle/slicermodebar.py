"""The slicers' top tabs over the 3D view: Prepare, Preview, Device, and the Calibration menu. The tabs press the same
buttons as the panel's Prepare / Preview / Device row and follow its state."""
from PySide import QtCore, QtWidgets

from . import style

Qt = QtCore.Qt
TABS = (("prepare", "Prepare"), ("preview", "Preview"), ("device", "Device"))


class ModeBar(QtWidgets.QFrame):
    def __init__(self, panel, host):
        super().__init__(host)
        self.panel, self.host = panel, host
        self.setObjectName("SWSlicerModeBar")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.buttons = {}
        for key, text in TABS:
            b = QtWidgets.QToolButton()
            b.setObjectName("SWSlicerModeTab")
            b.setText(text)
            b.setCheckable(True)
            b.setToolTip(panel.mode_buttons[key].toolTip())
            b.clicked.connect(lambda _=False, k=key: self._press(k))
            lay.addWidget(b)
            self.buttons[key] = b
        from . import slicercalib
        self.calib = QtWidgets.QToolButton()
        self.calib.setObjectName("SWSlicerModeTab")
        self.calib.setText("Calibration")
        self.calib.setToolTip("Calibration: print a test to tune temperature, flow, pressure advance or speed")
        self.calib.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.calib.setMenu(slicercalib.menu(panel, self.calib))
        lay.addWidget(self.calib)
        # the calibration prints are made of Orca Slicer's settings
        self.calib.setVisible(panel.key != "prusa")
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        host.installEventFilter(self)
        style.signals.theme_changed.connect(self._restyle)
        self._restyle()
        self.refresh()
        self.adjustSize()
        self.show()
        self.place()

    def _press(self, key):
        self.panel.mode_buttons[key].click()
        self.refresh()

    def refresh(self):
        for key, b in self.buttons.items():
            src = self.panel.mode_buttons[key]
            b.setChecked(src.isChecked())
            b.setEnabled(self.panel.preview_check.isEnabled() if key == "preview" else True)

    def _restyle(self, *_):
        T = style.T
        self.setStyleSheet(
            "#SWSlicerModeBar{background:%(pane)s;border:1px solid %(line)s;}"
            "#SWSlicerModeTab{color:%(text)s;background:transparent;border:none;border-bottom:3px solid transparent;"
            "padding:5px 16px 3px 16px;}"
            "#SWSlicerModeTab:hover{background:%(hover)s;}"
            "#SWSlicerModeTab:checked{border-bottom:3px solid %(accent)s;font-weight:bold;}"
            "#SWSlicerModeTab:disabled{color:%(dim)s;}"
            "#SWSlicerModeTab::menu-indicator{image:none;width:0;}"
            % {"pane": T.hex("pane"), "line": T.hex("line_mid"), "text": T.hex("text"), "hover": T.hex("hover"),
               "accent": T.hex("accent"), "dim": T.hex("line_mid")})

    def eventFilter(self, obj, event):
        if obj is self.host and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self.place()
        return False

    def place(self):
        self.adjustSize()
        self.move(12, 40)
        self.raise_()
        tb = getattr(self.panel, "toolbar", None)
        if tb is not None and hasattr(tb, "place"):
            tb.place()     # it keeps clear of the tabs

    def remove(self):
        self.timer.stop()
        try:
            style.signals.theme_changed.disconnect(self._restyle)
        except Exception:
            pass
        self.host.removeEventFilter(self)
        self.hide()
        self.setParent(None)
        self.deleteLater()
