# SPDX-License-Identifier: LGPL-2.1-or-later
"""Show a unit chooser below length fields in the TaskView.

The chooser does not activate its window, so typing continues in the spin box.
Values selected from the menu are converted to millimetres before committing.
"""

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
import re

import FreeCAD as App
from PySide import QtCore, QtWidgets, QtGui


UNITS = [
    ("\u00c5", 1e-7),
    ("cm", 10.0),
    ("ft", 304.8),
    ("in", 25.4),
    ("m", 1000.0),
    ("uin", 2.54e-5),
    ("um", 0.001),
    ("mil", 0.0254),
    ("mm", 1.0),
    ("nm", 1e-6),
]

_NUMBER = re.compile(
    r"\s*([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)"
    r"(?:[eE][+-]?\d+)?)\s*(?:[A-Za-zµμ.]+)?\s*\Z"
)
_popup = None


def to_mm(text, unit):
    """Return the typed number in millimetres, or None for invalid input."""
    factor = dict(UNITS).get(unit)
    if factor is None or not isinstance(text, str):
        return None
    match = _NUMBER.fullmatch(text)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ".")) * factor
    except (ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _spin_for(obj):
    """Find the spin box receiving an event, including its line edit."""
    while obj is not None:
        if isinstance(obj, QtWidgets.QAbstractSpinBox):
            return obj
        obj = obj.parent()
    return None


def _is_length_field(spin):
    if spin is None or not spin.isVisible():
        return False

    parent = spin
    in_task_view = False
    while parent is not None:
        if parent.metaObject().className() == "Gui::TaskView::TaskView":
            in_task_view = True
            break
        parent = parent.parent()
    if not in_task_view:
        return False

    if "QuantitySpinBox" in spin.metaObject().className():   # Gui::QuantitySpinBox and Gui::PrefQuantitySpinBox
        # This deliberately recognizes only the common millimetre display.
        unit = spin.property("unit")
        if unit is not None and "mm" in str(unit).lower():
            return True
        raw = spin.property("rawValue")
        return raw is not None and spin.lineEdit().text().strip().lower().endswith("mm")

    return isinstance(spin, QtWidgets.QDoubleSpinBox) and ("mm" in spin.suffix().lower()
                                                          or spin.property("fw_length_power") == 1)   # pmlength


def _inside(widget, ancestor):
    return widget is not None and (
        widget is ancestor or ancestor.isAncestorOf(widget)
    )


def _hide_popup():
    global _popup
    popup = _popup
    _popup = None
    if popup is not None:
        try:
            popup.menu.hide()
            popup.hide()
            popup.deleteLater()
        except RuntimeError as _fw_err:
            _fw_log("pmunits.py:111", _fw_err)


def _check_focus(spin, popup):
    """Run after Qt has completed a focus change or opened the menu."""
    if popup is not _popup:
        return
    try:
        if not spin.isVisible():
            _hide_popup()
            return
        app = QtWidgets.QApplication.instance()
        focus = app.focusWidget()
        active_popup = app.activePopupWidget()
        if (_inside(focus, spin) or _inside(focus, popup)
                or _inside(focus, popup.menu)
                or active_popup is popup.menu or popup.menu.isVisible()):
            return
        _hide_popup()
    except RuntimeError:
        _hide_popup()


class _UnitsButton(QtWidgets.QToolButton):
    def __init__(self, popup):
        super().__init__(popup)
        self._units_popup = popup
        self.setText("Units    >")
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.clicked.connect(self._open_menu)

    def _open_menu(self):
        popup = self._units_popup
        if not popup.menu.isVisible():
            popup.menu.popup(self.mapToGlobal(self.rect().topRight()))

    def enterEvent(self, event):
        super().enterEvent(event)
        self._open_menu()


class _UnitsPopup(QtWidgets.QWidget):
    def __init__(self, spin):
        super().__init__(spin, QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)
        self.spin = spin
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)

        self.button = _UnitsButton(self)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.button)

        self.menu = QtWidgets.QMenu(self)
        for name, _factor in UNITS:
            action = self.menu.addAction(name)
            action.triggered.connect(
                lambda checked=False, selected=name: self._choose(selected)
            )
        self.menu.aboutToHide.connect(self._menu_hidden)

    def _menu_hidden(self):
        QtCore.QTimer.singleShot(0, lambda: _check_focus(self.spin, self))

    def _choose(self, unit):
        spin = self.spin
        try:
            value = to_mm(spin.lineEdit().text(), unit)
            if value is not None:
                if "QuantitySpinBox" in spin.metaObject().className():   # Gui::QuantitySpinBox and Gui::PrefQuantitySpinBox
                    spin.setProperty("rawValue", value)      # Gui::QuantitySpinBox: sets the text and sends valueChanged
                    spin.lineEdit().setText(format(value, ".15g") + " mm")
                    spin.editingFinished.emit()
                elif isinstance(spin, QtWidgets.QDoubleSpinBox):
                    spin.setValue(value)
            _hide_popup()
            spin.setFocus(QtCore.Qt.OtherFocusReason)
        except Exception as error:
            _hide_popup()
            App.Console.PrintLog("FreeCAD pmunits: %s\n" % error)


def _show_popup(spin):
    global _popup
    if _popup is not None:
        try:
            if _popup.spin is not spin:
                _hide_popup()
        except RuntimeError:
            _hide_popup()
    if _popup is None:
        _popup = _UnitsPopup(spin)
    _popup.adjustSize()
    _popup.move(spin.mapToGlobal(spin.rect().bottomLeft()))
    _popup.show()


def _handler(obj, event):
    try:
        spin = _spin_for(obj)
        if event.type() == QtCore.QEvent.FocusOut:
            if _popup is not None and spin is _popup.spin:
                popup = _popup
                QtCore.QTimer.singleShot(0, lambda: _check_focus(spin, popup))
        elif event.type() == QtCore.QEvent.KeyPress:
            if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Escape):
                if _popup is not None and spin is _popup.spin:
                    _hide_popup()
            elif (len(event.text()) == 1 and event.text() in "0123456789.,"
                  and _is_length_field(spin)):
                _show_popup(spin)
    except Exception as error:
        App.Console.PrintLog("FreeCAD pmunits: %s\n" % error)
    return False


def install():
    from . import events
    events.register(
        "pmunits", (QtCore.QEvent.KeyPress, QtCore.QEvent.FocusOut), _handler
    )
