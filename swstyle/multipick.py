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
from PySide import QtCore, QtGui, QtWidgets

from . import contextbar, paths

Qt = QtCore.Qt
PARAM = "MultiPick"
DRAG_PX = 4
KEYS = Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier


def enabled():
    return paths.params().GetBool(PARAM, True)


def _mods(event):
    return event.modifiers() & KEYS


def _point(event):
    try:
        return event.position()
    except AttributeError:
        return QtCore.QPointF(event.pos())


def _over_model(widget, event):
    """Something of the model is under the pointer (asked of the view: a face hover clears
    FreeCAD's preselection, so that cannot tell)."""
    try:
        view = Gui.ActiveDocument.ActiveView
        p = _point(event)
        dpr = widget.devicePixelRatioF()
        info = view.getObjectInfo((int(p.x() * dpr), int((widget.height() - p.y()) * dpr)))
        return bool(info)
    except Exception as _fw_err:
        _fw_log("multipick.py:over", _fw_err)
        return False


def _leaf(sub):
    return str(sub).rsplit(".", 1)[-1].lower()


def _sketch_picks(sketch):
    """[(object name, full sub, leaf)] picked inside the sketch in edit."""
    out = []
    try:
        for sel in Gui.Selection.getSelectionEx(sketch.Document.Name, 0):
            for sub in sel.SubElementNames:
                out.append((sel.ObjectName, sub, _leaf(sub)))
    except Exception as _fw_err:
        _fw_log("multipick.py:picks", _fw_err)
    return out


def _hovered(sketch):
    """The leaf name of the sketch entity under the pointer ('edge2', 'vertex3'...), else None."""
    try:
        pre = Gui.Selection.getPreselection()
        if pre.ObjectName and pre.SubElementNames:
            sub = pre.SubElementNames[0]
            if sub:
                return _leaf(sub)
    except Exception as _fw_err:
        _fw_log("multipick.py:pre", _fw_err)
    return None


def _in_3d_sketch():
    try:
        from . import sketch3d
        return sketch3d.session() is not None
    except Exception:
        return False


def _collecting(shell):
    ""

    try:
        rel = getattr(shell, "relations_pm", None)
        if rel is not None and getattr(rel, "_add", None):
            return True
    except Exception as _fw_err:
        _fw_log("multipick.py:rel", _fw_err)
    try:
        from . import sketchtoolpm
        if sketchtoolpm.current() is not None:
            return True
    except Exception as _fw_err:
        _fw_log("multipick.py:page", _fw_err)
    return False


class MultiPick(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.converting = False     # this press goes to FreeCAD as Ctrl until its release
        self.sending = False
        self.press = None           # (pos, mods, in sketch) of the last left press
        self.shift_clicks = 0       # for checks
        self.replaced = 0
        self.unpicked = 0
        from . import events
        events.register("multipick", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease,
                                      QtCore.QEvent.MouseMove), self.filter)

    def _resend(self, obj, event, mods):
        new = QtGui.QMouseEvent(event.type(), _point(event), event.globalPosition() if hasattr(event, "globalPosition") else QtCore.QPointF(event.globalPos()),
                                event.button(), event.buttons(), mods)
        self.sending = True
        try:
            QtWidgets.QApplication.sendEvent(obj, new)
        finally:
            self.sending = False
        return True

    def filter(self, obj, event):
        if self.sending or not enabled() or not self.shell.enabled:
            return False
        if not obj.inherits("QOpenGLWidget"):
            return False
        if _in_3d_sketch():
            return False                            # the 3D sketch has its own clicks and picks
        kind = event.type()
        if kind == QtCore.QEvent.MouseMove:
            if self.converting:
                m = _mods(event)
                return self._resend(obj, event, (m & ~Qt.ShiftModifier) | Qt.ControlModifier)
            return False
        if event.button() != Qt.LeftButton:
            return False
        sketch = contextbar.sketch_in_edit()
        if kind == QtCore.QEvent.MouseButtonPress:
            mods = _mods(event)
            self.press = (_point(event), mods, sketch is not None and not contextbar.tool_running(self.shell))
            self.converting = False
            if sketch is None and mods == Qt.ShiftModifier and not contextbar.tool_running(self.shell) \
                    and _over_model(obj, event):
                self.converting = True
                self.shift_clicks += 1
                return self._resend(obj, event, Qt.ControlModifier)
            return False
        # release
        if self.converting:
            self.converting = False
            m = _mods(event)
            return self._resend(obj, event, (m & ~Qt.ShiftModifier) | Qt.ControlModifier)
        press, self.press = self.press, None
        if sketch is None or press is None or not press[2] or contextbar.tool_running(self.shell):
            return False
        if (_point(event) - press[0]).manhattanLength() > DRAG_PX:
            return False                            # a drag: FreeCAD's own
        mods = press[1]
        hovered = _hovered(sketch)
        if hovered is None:
            return False
        picks = _sketch_picks(sketch)
        if mods == Qt.NoModifier:
            if picks and not _collecting(self.shell) and [p[2] for p in picks] != [hovered]:
                # FreeCAD's click toggles the entity in the pick and keeps the rest: once it is done,
                # keep only this one, picked
                try:
                    pre = Gui.Selection.getPreselection()
                    again = (pre.DocumentName, pre.ObjectName, pre.SubElementNames[0])
                except Exception:
                    again = None
                QtCore.QTimer.singleShot(0, lambda h=hovered, a=again, d=sketch.Document.Name: self._only(d, h, a))
            return False
        if mods in (Qt.ControlModifier, Qt.ShiftModifier):
            mine = [p for p in picks if p[2] == hovered]
            if mine:
                QtCore.QTimer.singleShot(0, lambda m=mine, d=sketch.Document.Name: self._unpick(d, m))
        return False

    def _only(self, doc_name, hovered, again):
        picks = []
        try:
            for sel in Gui.Selection.getSelectionEx(doc_name, 0):
                for sub in sel.SubElementNames:
                    picks.append((sel.ObjectName, sub, _leaf(sub)))
        except Exception as _fw_err:
            _fw_log("multipick.py:only", _fw_err)
        others = [p for p in picks if p[2] != hovered]
        self._unpick(doc_name, others)
        if not any(p[2] == hovered for p in picks) and again is not None:
            try:
                Gui.Selection.addSelection(*again)
            except Exception as _fw_err:
                _fw_log("multipick.py:again", _fw_err)
        self.replaced += 1

    def _unpick(self, doc_name, items):
        for name, sub, _leafname in items:
            try:
                Gui.Selection.removeSelection(doc_name, name, sub)
                self.unpicked += 1
            except Exception as _fw_err:
                _fw_log("multipick.py:unpick", _fw_err)

    def remove(self):
        from . import events
        events.unregister("multipick")
