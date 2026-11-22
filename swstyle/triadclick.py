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
from PySide import QtCore
Qt = QtCore.Qt

from .widgets import alive

NEAR = 5.0          # px from an arrow that still counts as on it
log = []            # (axis letter, modifiers, action) for checks


def _corner(shell):
    overlay = getattr(shell, "overlay", None)
    corner = getattr(overlay, "corner", None) if overlay is not None else None
    if corner is None or not alive(corner) or not corner.isVisible() or corner.quat is None:
        return None
    return corner


def axis_at(shell, global_pos):
    """(axis vector, letter) of the triad arrow under the global point, or None."""
    from . import chrome
    corner = _corner(shell)
    if corner is None or not chrome.triad_shown():
        return None
    p = corner.mapFromGlobal(global_pos.toPoint() if hasattr(global_pos, "toPoint") else global_pos)
    if not corner.rect().contains(p):
        return None
    ox, oy = corner.ORIGIN
    best = None
    for depth, (axis, letter, _c, _t), tx, ty, length in corner.arrows():
        if length < 2.5:
            d = math.hypot(p.x() - ox, p.y() - oy)
        else:
            ux, uy = (tx - ox) / length, (ty - oy) / length
            s = max(0.0, min(length, (p.x() - ox) * ux + (p.y() - oy) * uy))
            d = math.hypot(p.x() - (ox + ux * s), p.y() - (oy + uy * s))
            if s < 4.0:
                d += 3.0        # near the origin the arrows meet: the one nearer its tip wins
        if d <= NEAR and (best is None or (d, -depth) < (best[0], -best[1])):
            best = (d, depth, axis, letter)
    return (App.Vector(*best[2]), best[3]) if best else None


def _step():
    try:
        from . import viewkeys
        return float(getattr(viewkeys, "STEP", 15.0))
    except Exception:
        return 15.0


def turn(axis, modifiers, view=None):
    """Turns the active view for a click on that axis; returns what it did."""
    view = view or Gui.activeView()
    if view is None or not hasattr(view, "getCameraOrientation"):
        return None
    try:
        view.stopAnimating()
    except Exception as _fw_err:
        _fw_log("triadclick.py:84", _fw_err)
    cam = view.getCameraOrientation()
    ctrl = bool(modifiers & Qt.ControlModifier)
    if modifiers & Qt.ShiftModifier:
        angle, action = (-90.0 if ctrl else 90.0), "rotate90"
    elif modifiers & Qt.AltModifier:
        angle, action = (-_step() if ctrl else _step()), "rotate_step"
    else:
        angle, action = None, "normal"
    if angle is not None:
        # the model turns about the axis by the angle: the camera the other way
        new = App.Rotation(axis, -angle).multiply(cam)
    else:
        towards = cam.multVec(App.Vector(0, 0, 1))
        if towards.dot(axis) > 0.999:
            new = App.Rotation(cam.multVec(App.Vector(0, 1, 0)), 180).multiply(cam)
            action = "reverse"
        else:
            new = App.Rotation(towards, axis).multiply(cam)
    view.setCameraOrientation(new.Q)
    return action


class Clicks(object):
    """Left presses on the 3D view that land on the triad."""

    def __init__(self, shell):
        self.shell = shell
        self._eat_release = False

    def handle(self, event):
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            hit = axis_at(self.shell, event.globalPosition())
            if hit is None:
                return False
            mods = event.modifiers()
            action = turn(hit[0], mods)
            log.append((hit[1], int(mods.value) if hasattr(mods, "value") else int(mods), action))
            self._eat_release = True
            return True
        if t in (QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick) and self._eat_release \
                and event.button() == Qt.LeftButton:
            if t == QtCore.QEvent.MouseButtonRelease:
                self._eat_release = False
            return True
        return False
