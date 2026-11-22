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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

T_HINT = "Press Esc to stop the view turning."
TICK = 60                       # ms between camera checks
QUIET = 2                       # ticks without camera change before the view counts as still

_state = {"last": None, "moving": 0, "timer": None, "hinted": False, "stopped": 0}


def _view():
    try:
        gdoc = Gui.ActiveDocument
        v = gdoc.ActiveView if gdoc is not None else None
        return v if v is not None and hasattr(v, "getCameraOrientation") and hasattr(v, "stopAnimating") else None
    except Exception:
        return None


def _camera(v):
    try:
        q = v.getCameraOrientation().Q
        node = v.getCameraNode()
        p = node.position.getValue()
        h = node.height.getValue() if hasattr(node, "height") else (node.heightAngle.getValue()
                                                                      if hasattr(node, "heightAngle") else 0.0)
        return tuple(round(x, 5) for x in tuple(q) + tuple(p) + (h,))
    except Exception:
        return None


def animating():
    """True while the active view turns on its own (no mouse button held)."""
    return _state["moving"] > 0


def _status(text):
    try:
        bar = Gui.getMainWindow().statusBar()
        if text:
            bar.showMessage(text)
            _state["hinted"] = True
        elif _state["hinted"]:
            if bar.currentMessage() == T_HINT:
                bar.clearMessage()
            _state["hinted"] = False
    except Exception as _fw_err:
        _fw_log("viewanim.py:69", _fw_err)


def _tick():
    v = _view()
    cam = _camera(v) if v is not None else None
    held = QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton
    changed = cam is not None and _state["last"] is not None and cam != _state["last"]
    _state["last"] = cam
    if changed and not held:
        if _state["moving"] == 0:
            _status(T_HINT)
        _state["moving"] = QUIET
    elif _state["moving"] > 0:
        _state["moving"] -= 1
        if _state["moving"] == 0:
            _status("")


def stop():
    """Stops the view where it is (Esc while it turns). True when it was turning."""
    if not animating():
        return False
    v = _view()
    if v is None:
        return False
    try:
        v.stopAnimating()
    except Exception:
        return False
    _state["moving"] = 0
    _state["last"] = _camera(v)
    _state["stopped"] += 1
    _status("")
    return True


def _on_key(obj, event):
    if event.key() != QtCore.Qt.Key_Escape or event.modifiers() not in (QtCore.Qt.NoModifier, QtCore.Qt.KeypadModifier):
        return False
    if not animating():
        return False
    if event.type() == QtCore.QEvent.ShortcutOverride:
        event.accept()
        return False
    return stop()


def install():
    if _state["timer"] is not None:
        return
    t = QtCore.QTimer(QtWidgets.QApplication.instance())
    t.setObjectName("FW_ViewAnimWatch")
    t.timeout.connect(_tick)
    t.start(TICK)
    _state["timer"] = t
    try:
        from . import events
        events.register("viewanim", (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress), _on_key)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Esc stops a view animation: %s\n" % error)


def remove():
    t = _state["timer"]
    if t is not None:
        t.stop()
        t.deleteLater()
        _state["timer"] = None
    try:
        from . import events
        events.unregister("viewanim")
    except Exception as _fw_err:
        _fw_log("viewanim.py:142", _fw_err)
