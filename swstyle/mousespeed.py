# SPDX-License-Identifier: LGPL-2.1-or-later
""







import FreeCAD as App

try:
    from PySide import QtCore, QtGui
except ImportError:
    QtCore = None

FACTORS = {"Slow": 0.5, "Medium": 0.75, "Fast": 1.0}
ROW = ("View", "Mouse speed", "Fast")
_state = {"anchor": None, "busy": False}


def factor():
    try:
        from . import optionspages
        return FACTORS.get(str(optionspages.stored(ROW[0], ROW[1], ROW[2])), 1.0)
    except Exception:
        return 1.0


def _is_view(obj):
    try:
        return obj.inherits("QOpenGLWidget") or obj.inherits("QOpenGLWindow")
    except Exception:
        return False


def handler(obj, event):
    Qt = QtCore.Qt
    t = event.type()
    if _state["busy"] or not _is_view(obj):
        return False
    if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.MiddleButton:
        _state["anchor"] = event.position()
        return False
    if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.MiddleButton:
        _state["anchor"] = None
        return False
    if t != QtCore.QEvent.MouseMove or _state["anchor"] is None:
        return False
    if not (event.buttons() & Qt.MiddleButton) or event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
        return False
    k = factor()
    if k >= 0.999:
        return False
    a = _state["anchor"]
    p = event.position()
    q = QtCore.QPointF(a.x() + (p.x() - a.x()) * k, a.y() + (p.y() - a.y()) * k)
    g = event.globalPosition() + (q - p)
    moved = QtGui.QMouseEvent(t, q, g, event.button(), event.buttons(), event.modifiers())
    _state["busy"] = True
    try:
        QtCore.QCoreApplication.sendEvent(obj, moved)
    finally:
        _state["busy"] = False
    return True


FAST_WHEEL = 3


def wheel(obj, event):
    ""

    Qt = QtCore.Qt
    if _state["busy"] or not _is_view(obj):
        return False
    mods = event.modifiers()
    if not (mods & Qt.ShiftModifier) or mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
        return False
    d = event.angleDelta()
    if d.y() == 0 and d.x() != 0:
        d = QtCore.QPoint(0, d.x())        # some systems turn a Shift+wheel into a sideways one
    if d.y() == 0:
        return False
    big = QtCore.QPoint(0, d.y() * FAST_WHEEL)
    pix = event.pixelDelta()
    fast = QtGui.QWheelEvent(event.position(), event.globalPosition(), QtCore.QPoint(0, pix.y() * FAST_WHEEL),
                             big, event.buttons(), mods & ~Qt.ShiftModifier, event.phase(), event.inverted())
    target = obj.parentWidget() if obj.parentWidget() is not None and obj.parentWidget().inherits("QGraphicsView") else obj
    _state["busy"] = True
    try:
        QtCore.QCoreApplication.sendEvent(target, fast)      # FreeCAD's view zooms in its QGraphicsView
    finally:
        _state["busy"] = False
    return True


def install():
    if QtCore is None:
        return
    try:
        from . import events
        events.register("mousespeed", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease,
                                       QtCore.QEvent.MouseMove), handler)
        events.register("mousespeed.wheel", (QtCore.QEvent.Wheel,), wheel)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: mouse speed: %s\n" % error)
