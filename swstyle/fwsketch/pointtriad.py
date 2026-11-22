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

try:
    from PySide import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtWidgets

from .. import sketchtriad

STEP = "Move Spline Point"


def _drop_step(doc):
    """abortTransaction leaves a step that recorded nothing armed in FreeCAD: the next change
    (anywhere) opens it under this tool's name and wipes Redo. Close it at application level too."""
    doc.abortTransaction()
    try:
        import FreeCAD
        if FreeCAD.getActiveTransaction():
            FreeCAD.closeActiveTransaction(True)
    except Exception as _fw_err:
        _fw_log("%s:drop step" % __name__, _fw_err)


def spline_point(sketch, geo, pos):
    ""
    from . import splineedit as E
    try:
        owner = E.spline_of(sketch, geo)
    except Exception:
        return False
    if owner is None:
        return False
    if owner == geo:
        return pos in (1, 2)
    return True


def _preselected_point(sketch):
    try:
        pre = Gui.Selection.getPreselection()
        sub = pre.SubElementNames[0] if pre.SubElementNames else ""
        if pre.Object is not sketch:
            # a sketch in a Body is preselected through it: Body + "Sketch.Vertex3"
            parts = sub.split(".")
            if len(parts) < 2 or parts[-2] != sketch.Name:
                return None
        sub = sub.split(".")[-1]
    except Exception:
        return None
    if not sub.startswith("Vertex"):
        return None
    try:
        geo, pos = sketch.getGeoVertexIndex(int(sub[6:]) - 1)
    except Exception:
        return None
    if geo is None or geo < 0:
        return None
    return geo, pos


class _PointTriad(sketchtriad._Triad):
    """The sketch triad drawn on one spline point; its arms move the point."""

    def __init__(self):
        super().__init__()
        self.point = None            # (geo, pos)

    def poll(self):
        if self.drag is not None or self.sketch is None:
            return
        gdoc = Gui.ActiveDocument
        try:
            vp = gdoc.getInEdit() if gdoc is not None else None
        except Exception:
            vp = None
        if getattr(vp, "Object", None) is not self.sketch:
            self.stop()

    def show(self, sketch, geo, pos):
        self.clear()
        gdoc = Gui.ActiveDocument
        view = gdoc.ActiveView if gdoc is not None else None
        if view is None or not hasattr(view, "getPoint"):
            return False
        gpl = sketch.getGlobalPlacement()
        p = sketch.getPoint(geo, pos)
        self.sketch, self.point = sketch, (geo, pos)
        self.base = gpl.multVec(App.Vector(p.x, p.y, 0))
        self.axes = (gpl.Rotation.multVec(App.Vector(1, 0, 0)), gpl.Rotation.multVec(App.Vector(0, 1, 0)))
        self.length = self._arm_mm(view, self.base)
        self.key = ("point", sketch.Name, geo, pos)
        self._draw(view)
        self.start()
        return True

    def clear(self):
        super().clear()
        self.point = None

    def on_event(self, event):
        t = event.type()
        QE = QtCore.QEvent
        if self.drag is None and t == QE.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            self.stop()
            return False
        if self.drag is None and t == QE.MouseButtonPress and hasattr(event, "button") and self.widget is not None:
            if self._arm_under(self.coin_pos(event)) is None:
                QtCore.QTimer.singleShot(0, self.stop)   # a click elsewhere: the triad goes
                return False
        return super().on_event(event)

    def press(self, arm, pos):
        from .. import instant3d
        axis = self.axes[arm]
        t0 = instant3d._ray_param(self.view, pos, self.base, axis)
        if t0 is None:
            return False
        sk = self.sketch
        geo, p = self.point
        doc = sk.Document
        doc.openTransaction(STEP)
        try:
            self.drag = {"arm": arm, "t0": t0, "doc": doc, "start": App.Vector(sk.getPoint(geo, p)),
                         "shift": App.Vector(), "d": 0.0, "snapped": False, "ruler": None}
            QtWidgets.QApplication.instance().installEventFilter(self.filter)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        self._set_hover(arm)
        self._ruler_start(arm)
        return True

    def _apply(self):
        sk, drag = self.sketch, self.drag
        geo, p = self.point
        start = drag["start"]
        local = App.Vector(drag["d"], 0, 0) if drag["arm"] == 0 else App.Vector(0, drag["d"], 0)
        try:
            sk.moveGeometry(geo, p, start + local, False)
            sk.solve()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: spline point triad: %s\n" % error)
        try:
            Gui.ActiveDocument.getInEdit().Object.touch()
        except Exception as _fw_err:
            _fw_log("fwsketch/pointtriad.py:153", _fw_err)
        sk.Document.recompute()

    def release(self):
        drag = self.drag
        if abs(drag["d"]) < 1e-9:
            _drop_step(drag["doc"])
        else:
            drag["doc"].commitTransaction()
        self._end()
        sk, point = self.sketch, self.point
        if sk is not None and point is not None:
            QtCore.QTimer.singleShot(0, lambda: self.show(sk, *point))   # the triad moves with the point

    def cancel(self):
        if self.drag is None:
            return
        drag = self.drag
        try:
            geo, p = self.point
            self.sketch.moveGeometry(geo, p, drag["start"], False)
            drag["doc"].abortTransaction()
            self.sketch.solve()
            drag["doc"].recompute()
        except Exception as _fw_err:
            _fw_log("fwsketch/pointtriad.py:178", _fw_err)
        self._end()
        self.clear()


class _Watcher(QtCore.QObject):
    """A double-click on a spline point in the edited sketch, with no tool running."""

    def __init__(self):
        super().__init__()
        self.triad = _PointTriad()
        self.swallow_release = False
        from . import appevents
        appevents.listen(self, (QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseButtonRelease))

    def stop(self):
        try:
            from . import appevents
            appevents.stop(self)
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/pointtriad.py:198", _fw_err)
        self.triad.stop()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        try:
            return self._filter(obj, event)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: spline point triad: %s\n" % error)
            return False

    def _filter(self, obj, event):
        t = event.type()
        if t == QtCore.QEvent.MouseButtonRelease and self.swallow_release:
            if event.button() == QtCore.Qt.LeftButton:
                self.swallow_release = False
                return True
            return False
        if t != QtCore.QEvent.MouseButtonDblClick or event.button() != QtCore.Qt.LeftButton:
            return False
        from . import tool
        from .dimedit import edited_sketch
        if tool.active() is not None:
            return False
        gdoc, sketch = edited_sketch()
        if sketch is None:
            return False
        try:
            if obj is not gdoc.ActiveView.graphicsView().viewport():
                return False
        except (AttributeError, RuntimeError):
            return False
        hit = _preselected_point(sketch)
        if hit is None or not spline_point(sketch, *hit):
            return False
        self.swallow_release = True
        QtCore.QTimer.singleShot(0, lambda: self.triad.show(sketch, *hit))
        return True


_watcher = None


def start():
    global _watcher
    if _watcher is None:
        _watcher = _Watcher()
    return _watcher


def stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
        _watcher = None


def watcher():
    return _watcher


def show(sketch, geo, pos):
    return start().triad.show(sketch, geo, pos)
