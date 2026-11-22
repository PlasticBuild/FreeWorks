# SPDX-License-Identifier: LGPL-2.1-or-later
""











import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from . import contextbar, nativepms, sketchtoolpm
from .widgets import alive


TYPES = {
    "SWStyle_3PointCornerRectangle": ("Rectangle", "3 Point Corner Rectangle",
                                      "Sketches a rectangle at an angle: two corners, then the width."),
    "SWStyle_3PointCenterRectangle": ("Rectangle", "3 Point Center Rectangle",
                                      "Sketches a rectangle at an angle from its center point."),
    "SWStyle_Parallelogram": ("Rectangle", "Parallelogram",
                              "Sketches a parallelogram: two corners, then the third."),
    "SWStyle_CenterpointStraightSlot": ("Slot", "Centerpoint Straight Slot",
                                        "Sketches a straight slot from its center point."),
    "SWStyle_3PointArcSlot": ("Slot", "3 Point Arc Slot",
                              "Sketches an arc slot through three points on its centre arc."),
}


def entry(kind, name):
    """nativepms' row for a type: (name, FreeCAD tool, method index, icon family, FreeCAD pixmap)."""
    return next(t for t in nativepms.SHAPES[kind] if t[0] == name)


def available(kind, name):
    return contextbar.sketch_in_edit() is not None and nativepms._shape_available(name)


def start(kind, name):
    """Starts FreeCAD's tool on the type; an open page of the same kind just changes type."""
    row = entry(kind, name)
    page = sketchtoolpm.current()
    if isinstance(page, nativepms.ShapePage) and alive(page) and page.KIND == kind:
        page.choose(name)
        return
    nativepms._shape_next = name
    Gui.runCommand(row[1], 0)
    QtCore.QTimer.singleShot(500, lambda: _without_page(row))


def _without_page(row):
    """With the pages switched off nothing takes the type: set the tool's method here."""
    if nativepms._shape_next != row[0]:
        return
    nativepms._shape_next = None
    box = nativepms._tool_method_box()
    if box is not None and row[2] is not None and row[2] < box.count():
        box.setCurrentIndex(row[2])


class _Command:
    def __init__(self, command):
        self.kind, self.name, self.tip = TYPES[command]

    def GetResources(self):
        return {"MenuText": self.name, "ToolTip": self.tip, "Pixmap": entry(self.kind, self.name)[4]}

    def IsActive(self):
        return available(self.kind, self.name)

    def Activated(self):
        start(self.kind, self.name)


def register():
    for command in TYPES:
        try:
            if command not in Gui.listCommands():
                Gui.addCommand(command, _Command(command))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (TYPES[command][1], error))
