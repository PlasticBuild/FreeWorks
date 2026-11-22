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

from . import asmcore as ac

Qt = QtCore.Qt
STATE = {"comp": None, "press": None, "copy": None, "base": None, "start": None, "widget": None}
LAST = {}


def _asm():
    try:
        return ac.assembly_of(App.ActiveDocument)
    except Exception:
        return None


def _busy():
    try:
        return Gui.Control.activeDialog()
    except Exception:
        return False


def _view():
    try:
        return Gui.ActiveDocument.ActiveView
    except Exception:
        return None


def _gl(widget, pos):
    dpr = widget.devicePixelRatioF()
    return int(pos.x() * dpr), int((widget.height() - pos.y()) * dpr)


def _component_at(asm, widget, pos):
    view = _view()
    try:
        info = view.getObjectInfo(_gl(widget, pos)) if view is not None else None
    except Exception:
        info = None
    names = ((info or {}).get("SubName", "") or "").split(".")
    comps = {c.Name: c for c in ac.components(asm)}
    for part in names:
        if part in comps:
            return comps[part]
    return None


def _plane_point(widget, pos):
    view = _view()
    return view.getPoint(*_gl(widget, pos)) if view is not None else None


def _source(comp):
    """What a new instance of comp links to: its own part or subassembly."""
    try:
        from . import asmspeedpak as sp
        return sp.own(comp.LinkedObject)
    except Exception:
        return getattr(comp, "LinkedObject", None)


def copy_component(asm, comp, placement=None):
    """A new instance of comp (no mates), at placement (default: on top of it)."""
    target = _source(comp)
    if target is None:
        return None
    return ac.insert(asm, target, App.Placement(placement or comp.Placement))


def drop_instance(asm, comp, point):
    """Tree drag into the graphics area: a new instance with its centre at point."""
    doc = asm.Document
    doc.openTransaction("Insert Component")
    try:
        new = copy_component(asm, comp)
        if new is None:
            return None
        doc.recompute()
        try:
            centre = new.Shape.BoundBox.Center
        except Exception:
            centre = new.Placement.Base
        view = _view()
        d = App.Vector(view.getViewDirection()) if view is not None else App.Vector(0, 0, -1)
        if d.Length > 1e-9:
            d.normalize()
            point = App.Vector(point) + d * (centre - App.Vector(point)).dot(d)   # in the plane through its centre
        pl = App.Placement(new.Placement)
        pl.Base = pl.Base + (App.Vector(point) - centre)
        new.Placement = pl
        doc.recompute()
    finally:
        doc.commitTransaction()
    _after(new)
    return new


def _after(new):
    LAST["copy"] = new
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(new)
    except Exception as _fw_err:
        _fw_log("asmctrlcopy.py:129", _fw_err)
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmctrlcopy.py:134", _fw_err)


def _tree_comp(asm, data):
    from . import asmrestructure as rs
    if not data.hasFormat(rs.MIME):
        return None
    names = bytes(data.data(rs.MIME)).decode().split("\n")
    comps = {c.Name: c for c in ac.components(asm)}
    hits = [comps[n] for n in names if n in comps]
    return hits[0] if len(hits) == 1 else None


class _Filter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        try:
            if t in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove, QtCore.QEvent.Drop):
                return self._drop_event(obj, event, t)
            if t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease):
                return False
            if not obj.inherits("QOpenGLWidget"):
                return False
            if t == QtCore.QEvent.MouseButtonPress:
                self._reset()
                if event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier and not _busy():
                    asm = _asm()
                    comp = _component_at(asm, obj, event.position()) if asm is not None else None
                    if comp is not None:
                        STATE.update(comp=comp, press=QtCore.QPointF(event.position()), widget=obj,
                                     start=_plane_point(obj, event.position()))
                return False
            if t == QtCore.QEvent.MouseMove:
                if STATE["comp"] is None or not (event.buttons() & Qt.LeftButton):
                    return False
                if STATE["copy"] is None:
                    moved = (event.position() - STATE["press"]).manhattanLength()
                    if moved < QtWidgets.QApplication.startDragDistance():
                        return False
                    self._begin()
                    if STATE["copy"] is None:
                        return False
                self._follow(obj, event.position())
                return True
            if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                if STATE["copy"] is not None:
                    self._follow(obj, event.position())
                    self._finish()
                    return False        # FreeCAD had the press: it must see the release too
                self._reset()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Ctrl+drag copy: %s\n" % error)
            self._reset()
        return False

    def _drop_event(self, obj, event, t):
        if not obj.inherits("QOpenGLWidget"):
            return False
        asm = _asm()
        comp = _tree_comp(asm, event.mimeData()) if asm is not None else None
        if comp is None:
            return False
        if t == QtCore.QEvent.Drop:
            point = _plane_point(obj, event.position())
            if point is not None:
                drop_instance(asm, comp, point)
        event.setDropAction(Qt.CopyAction)
        event.accept()
        return True

    def _begin(self):
        asm = _asm()
        comp = STATE["comp"]
        if asm is None or comp is None:
            return
        asm.Document.openTransaction("Copy Component")
        new = copy_component(asm, comp)
        if new is None:
            asm.Document.abortTransaction()
            return
        STATE["copy"], STATE["base"] = new, App.Placement(new.Placement)

    def _follow(self, widget, pos):
        now = _plane_point(widget, pos)
        if now is None or STATE["start"] is None:
            return
        pl = App.Placement(STATE["base"])
        pl.Base = pl.Base + (App.Vector(now) - App.Vector(STATE["start"]))
        STATE["copy"].Placement = pl

    def _finish(self):
        new = STATE["copy"]
        doc = new.Document
        doc.recompute()
        doc.commitTransaction()
        self._reset()
        _after(new)

    def _reset(self):
        STATE.update(comp=None, press=None, copy=None, base=None, start=None, widget=None)


_FILTER = []


def _accept_drops():
    """The 3D views take drops (FreeCAD's take files only)."""
    try:
        try:
            from PySide6.QtOpenGLWidgets import QOpenGLWidget
            ws = Gui.getMainWindow().findChildren(QOpenGLWidget)
        except Exception:
            ws = [w for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget) if w.inherits("QOpenGLWidget")]
        for w in ws:
            if not w.acceptDrops():
                w.setAcceptDrops(True)
            if _FILTER and not w.property("fw_ctrlcopy"):
                w.installEventFilter(_FILTER[0])       # drops reach the view itself first
                w.setProperty("fw_ctrlcopy", True)
    except Exception as _fw_err:
        _fw_log("asmctrlcopy.py:256", _fw_err)


def _app_filter(name, types, flt, on=True):
    ""
    try:
        from . import events
        if on:
            events.register(name, types, flt.eventFilter)
        else:
            events.unregister(name)
        return True
    except ImportError:
        app = QtWidgets.QApplication.instance()
        (app.installEventFilter if on else app.removeEventFilter)(flt)
        return False


def install():
    if _FILTER:
        return
    f = _Filter()
    _FILTER.append(f)
    _app_filter("asm.ctrlcopy", (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove, QtCore.QEvent.Drop) + (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease), f)
    _accept_drops()
    timer = QtCore.QTimer()
    timer.setInterval(2000)
    timer.timeout.connect(_accept_drops)
    timer.start()
    _FILTER.append(timer)
