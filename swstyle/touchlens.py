# SPDX-License-Identifier: LGPL-2.1-or-later
"""Touch Mode's precision selection lens (Options > Touch > Automatically pop up Selection tool
while hunting for precise location).

With Touch Mode on, a finger (or the left button) held nearly still on the 3D view is someone
hunting for a small edge or point: after a short hold the magnifying glass (magnify.py) opens
where the finger is. Moving the finger then moves the pointer in the glass, and lifting it picks
what lies under the pointer in the enlarged picture, then puts the glass away. A quick tap, or a
drag that starts moving at once, goes to FreeCAD as before.

FreeCAD gets the press only once it is known to be a tap or a drag: the press is held back for the
hold time and then sent on (at its first place) when the finger lifts or moves away.
"""
import FreeCAD as App

try:
    from PySide import QtCore, QtGui
except ImportError:
    QtCore = None

ROW = ("Touch", "Automatically pop up Selection tool while hunting for precise location")
HOLD = 450          # ms held still before the lens opens
SLOP = 8            # px a finger may wander and still be holding still

_state = {"press": None, "obj": None, "timer": None, "lens": False, "replaying": False}


def enabled():
    try:
        from . import uiextras, optionspages
        return uiextras.touch_mode() and bool(optionspages.stored(ROW[0], ROW[1], True))
    except Exception:
        return False


def _is_view(obj):
    try:
        return obj.inherits("QOpenGLWidget") or "QuarterWidget" in obj.metaObject().className()
    except Exception:
        return False


def _copy(event, kind=None, pos=None, button=None, buttons=None):
    Qt = QtCore.Qt
    p = QtCore.QPointF(pos) if pos is not None else event.position()
    g = event.globalPosition() + (p - event.position())
    return QtGui.QMouseEvent(kind or event.type(), p, g, button if button is not None else event.button(),
                             buttons if buttons is not None else event.buttons(), event.modifiers())


def _send(obj, event):
    _state["replaying"] = True
    try:
        QtCore.QCoreApplication.sendEvent(obj, event)
    finally:
        _state["replaying"] = False


def _forget():
    t = _state["timer"]
    if t is not None:
        t.stop()
    _state.update(press=None, obj=None, lens=False)


def _replay_press():
    """The held-back press goes to FreeCAD at its first place (a tap or a drag after all)."""
    press, obj = _state["press"], _state["obj"]
    _state["press"] = None
    if press is not None and obj is not None:
        _send(obj, press)


def _open_lens():
    press, obj = _state["press"], _state["obj"]
    if press is None or obj is None:
        return
    from . import magnify
    if magnify._in_sketch():
        _replay_press()         # a sketch keeps FreeCAD's own picks (the glass sends clicks there)
        return
    widget = magnify._viewport()[1]
    if widget is None:
        _replay_press()
        return
    pos = QtCore.QPointF(widget.mapFromGlobal(press.globalPosition().toPoint()))
    if magnify.GLASS.open(pos):
        _state["lens"] = True
        _state["press"] = None
    else:
        _replay_press()


def handler(obj, event):
    Qt = QtCore.Qt
    if _state["replaying"]:
        return False
    t = event.type()
    if t == QtCore.QEvent.MouseButtonPress:
        if event.button() != Qt.LeftButton or not _is_view(obj) or not enabled():
            return False
        from . import magnify
        if magnify.GLASS.is_open():
            return False        # the glass is already out: its own clicks pick
        _forget()
        _state["press"] = _copy(event)
        _state["obj"] = obj
        if _state["timer"] is None:
            timer = QtCore.QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(_open_lens)
            _state["timer"] = timer
        _state["timer"].start(HOLD)
        return True
    if obj is not _state["obj"]:
        return False
    if _state["lens"]:
        from . import magnify
        widget = magnify.GLASS.widget
        if widget is None:
            _forget()
            return False
        here = QtCore.QPointF(widget.mapFromGlobal(event.globalPosition().toPoint()))
        if t == QtCore.QEvent.MouseMove:
            magnify.GLASS.follow(here)
            return True
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            magnify.GLASS.click(here, bool(event.modifiers() & Qt.ControlModifier))
            _forget()
            QtCore.QTimer.singleShot(0, magnify.GLASS.close)
            return True
        return False
    press = _state["press"]
    if press is None:
        return False
    if t == QtCore.QEvent.MouseMove:
        d = event.position() - press.position()
        if abs(d.x()) + abs(d.y()) <= SLOP:
            return True                 # still holding still
        _state["timer"].stop()
        _replay_press()                 # a drag: FreeCAD gets the press, then this move
        _state["obj"] = None
        return False
    if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
        _state["timer"].stop()
        _replay_press()                 # a tap
        _state["obj"] = None
        return False
    return False


def install():
    if QtCore is None:
        return
    try:
        from . import events
        events.register("touchlens", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease,
                                      QtCore.QEvent.MouseMove), handler)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: touch lens: %s\n" % error)
