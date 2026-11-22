# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tear relief for the flange PropertyManagers' Custom Relief Type (Edge Flange, Hem, Miter Flange).

SheetMetal cuts rectangular or round reliefs only. A tear is a cut with no width; the flat pattern needs some,
so it is a hairline (TEAR_WIDTH) through the bend's depth (Rip), or a thickness further into the part (Extend).
"""
from PySide import QtWidgets

TEARS = ("Rip", "Extend")
TEAR_WIDTH = 0.01
PROP = "SWTear"


def depth(kind, radius, thickness):
    return radius + thickness + (0.0 if kind == "Rip" else thickness)


class TearRows:
    """Rip / Extend under a relief list; shown while Tear is picked."""

    def __init__(self, combo, layout, obj, changed, row=None):
        self.combo = combo
        self.box = QtWidgets.QWidget()          # own parent: radios group with every radio sibling
        QtWidgets.QVBoxLayout(self.box).setContentsMargins(0, 0, 0, 0)
        self.buttons = []
        kind = getattr(obj, PROP, "Rip") if obj is not None else "Rip"
        for text in TEARS:
            b = QtWidgets.QRadioButton(text)
            b.setObjectName("SWSMTear" + text)
            b.setChecked(text == (kind or "Rip"))
            b.toggled.connect(changed)
            self.box.layout().addWidget(b)
            self.buttons.append(b)
        if row is None:
            layout.addRow(self.box)
        else:
            layout.insertRow(row, self.box)

    def on(self):
        return self.combo.currentText() == "Tear"

    def kind(self):
        return next(b.text() for b in self.buttons if b.isChecked())

    def show(self, enabled):
        self.box.setVisible(self.on())
        for b in self.buttons:
            b.setEnabled(enabled)

    def apply(self, obj, radius, thickness, width="reliefw", deep="reliefd", ratio="UseReliefFactor",
              kind="reliefType"):
        """Writes the tear into the feature's relief settings (only while Tear is picked)."""
        if not self.on():
            return
        if PROP not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", PROP, "FreeCAD", "Tear relief: Rip or Extend")
        setattr(obj, PROP, self.kind())
        setattr(obj, kind, "Rectangle")
        setattr(obj, ratio, False)
        setattr(obj, width, TEAR_WIDTH)
        setattr(obj, deep, depth(self.kind(), radius, thickness))


def is_torn(width_value, use_ratio):
    return not use_ratio and width_value <= TEAR_WIDTH + 1e-9
