# SPDX-License-Identifier: LGPL-2.1-or-later
""





from PySide import QtWidgets

SHOWN = 2


def trim(text, point):
    """'10.000mm' style text without the trailing zeros past SHOWN decimals (the unit is not in the text here)."""
    if point not in text:
        return text
    head, tail = text.split(point, 1)
    digits = len(tail) - len(tail.lstrip("0123456789"))
    frac, rest = tail[:digits], tail[digits:]
    while len(frac) > SHOWN and frac.endswith("0"):
        frac = frac[:-1]
    return head + point + frac + rest


class TrimSpin(QtWidgets.QDoubleSpinBox):
    def textFromValue(self, value):
        text = super().textFromValue(value)
        try:
            return trim(text, self.locale().decimalPoint())
        except Exception:
            return text
