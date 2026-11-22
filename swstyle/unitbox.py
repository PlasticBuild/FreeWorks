# SPDX-License-Identifier: LGPL-2.1-or-later
""




import re

import FreeCAD as App
from PySide import QtGui, QtWidgets

_CHARS = re.compile(r"[0-9.,\s+\-*/^()a-zA-Z°\"'µ]*")


def _units_of(suffix):
    s = (suffix or "").strip()
    if s == "mm":
        return "mm"
    if s in ("°", "deg"):
        return "deg"
    return None


def parse(text, suffix="", unit=None):
    """The value of text in the box's unit, or None. A bare number is in the box's unit."""
    t = (text or "").strip()
    s = (suffix or "").strip()
    if s and t.endswith(s):
        t = t[:-len(s)].strip()
    if not t:
        return None
    t = t.replace(",", ".") if t.count(",") == 1 and "." not in t else t
    try:
        q = App.Units.Quantity(t)
    except Exception:
        return None
    if q.Unit == App.Units.Unit():
        return float(q.Value)
    unit = unit or _units_of(suffix)
    if unit is None:
        return None
    try:
        return float(q.getValueAs(unit))
    except Exception:
        return None


def _state(r):
    return r[0] if isinstance(r, (tuple, list)) else r


class UnitSpinBox(QtWidgets.QDoubleSpinBox):
    """QDoubleSpinBox that also takes "1in", "25.4mm", "2*15", "90deg"."""

    def _value_of(self, text):
        return parse(text, self.suffix())

    def validate(self, text, pos):
        r = super().validate(text, pos)
        if _state(r) == QtGui.QValidator.Acceptable:
            return r
        v = self._value_of(text)
        if v is not None and self.minimum() <= v <= self.maximum():
            return (QtGui.QValidator.Acceptable, text, pos)
        if _CHARS.fullmatch(text or ""):
            return (QtGui.QValidator.Intermediate, text, pos)
        return r

    def valueFromText(self, text):
        v = self._value_of(text)
        if v is not None:
            return v
        return super().valueFromText(text)

    def textFromValue(self, value):
        ""
        text = super().textFromValue(value)
        try:
            from .pmspin import trim
            return trim(text, self.locale().decimalPoint())
        except Exception:
            return text
