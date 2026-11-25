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

import math

import FreeCAD as App
import FreeCADGui as Gui
from . import events
from PySide import QtCore, QtGui, QtWidgets

COMMAND = "SWStyle_TurnCamera"
DEGREES_PER_PIXEL = 0.25


def turn(view, yaw, pitch):
    """Turns view's camera by yaw (about its up direction) and pitch (about its right), in
    degrees, keeping its position."""
    from pivy import coin
    cam = view.getCameraNode()
    q = cam.orientation.getValue()
    up = q.multVec(coin.SbVec3f(0, 1, 0))
    right = q.multVec(coin.SbVec3f(1, 0, 0))
    position = coin.SbVec3f(cam.position.getValue())
    r = coin.SbRotation(up, math.radians(-yaw)) * coin.SbRotation(right, math.radians(-pitch))
    cam.orientation.setValue(q * r)
    cam.position.setValue(position)


class _Mode(QtCore.QObject):
    instance = None

    def __init__(self):
        super().__init__()
        self.last = None
        events.register("turncamera", (QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseMove,), self.eventFilter)
        try:
            Gui.getMainWindow().statusBar().showMessage("Turn Camera: drag to turn the camera; Esc ends", 0)
        except Exception as _fw_err:
            _fw_log("turncamera.py:56", _fw_err)

    def stop(self):
        try:
            events.unregister("turncamera")
        except Exception as _fw_err:
            _fw_log("turncamera.py:62", _fw_err)
        try:
            Gui.getMainWindow().statusBar().clearMessage()
        except Exception as _fw_err:
            _fw_log("turncamera.py:66", _fw_err)
        _Mode.instance = None

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        from . import overridedrag
        t = event.type()
        QE = QtCore.QEvent
        if t == QE.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            self.stop()
            return True
        if not isinstance(obj, overridedrag._gl_class()):
            return False
        if t == QE.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            self.last = event.position()
            obj.setCursor(QtGui.QCursor(QtCore.Qt.ClosedHandCursor))
            return True
        if t == QE.MouseMove and self.last is not None:
            p = event.position()
            dx, dy = p.x() - self.last.x(), p.y() - self.last.y()
            self.last = p
            try:
                turn(Gui.ActiveDocument.ActiveView, dx * DEGREES_PER_PIXEL, dy * DEGREES_PER_PIXEL)
            except Exception as _fw_err:
                _fw_log("turncamera.py:91", _fw_err)
            return True
        if t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton and self.last is not None:
            self.last = None
            obj.unsetCursor()
            return True
        return False


def active():
    return _Mode.instance is not None


class _Command:
    def GetResources(self):
        return {"Pixmap": "view-rotate-left", "MenuText": "Turn Camera",
                "ToolTip": "Turns the camera where it stands: drag to look round; Esc ends",
                "CmdType": "ForEdit"}      # extapps77: also while a sketch is open

    def IsActive(self):
        return Gui.ActiveDocument is not None and hasattr(Gui.ActiveDocument.ActiveView, "getCameraNode")

    def Activated(self):
        if _Mode.instance is not None:
            _Mode.instance.stop()
        else:
            _Mode.instance = _Mode()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, _Command())
