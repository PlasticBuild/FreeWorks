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
from PySide import QtCore, QtGui, QtWidgets

ZOOM_AREA = "SWStyle_ViewZoomArea"
ZOOM_IN_OUT = "SWStyle_ViewZoomInOut"
HINTS = {"area": "Zoom to Area: drag a box to zoom to it; Esc ends",
         "zoom": "Zoom In/Out: drag up to zoom in, down to zoom out; Esc ends"}


def _push():
    try:
        from . import shell
        shell.shell().push_view()
    except Exception as _fw_err:
        _fw_log("viewtools.py:42", _fw_err)


def zoom(view, dy, per_pixel=0.01):
    """Drag up (dy < 0) zooms in."""
    cam = view.getCameraNode()
    k = math.exp(dy * per_pixel)
    if hasattr(cam, "height"):
        cam.height.setValue(max(1e-6, cam.height.getValue() * k))
        return
    from pivy import coin
    q = cam.orientation.getValue()
    d = q.multVec(coin.SbVec3f(0, 0, -1))
    f = cam.focalDistance.getValue()
    nf = max(1e-6, f * k)
    pos = coin.SbVec3f(cam.position.getValue())
    cam.position.setValue(pos + d * (f - nf))
    cam.focalDistance.setValue(nf)


def _mode_class():
    from . import viewextras
    return viewextras.DragMode


def _add_hints():
    D = _mode_class()
    for k, v in HINTS.items():
        D.HINT.setdefault(k, v)


def start(kind):
    """Turns a view tool on, or off when it is the one on now."""
    D = _mode_class()
    _add_hints()
    if D.current is not None:
        same = D.current.kind == kind
        D.current.stop()
        if same:
            return None
    D.current = _make(kind)
    return D.current


def on(kind):
    D = _mode_class()
    return D.current is not None and D.current.kind == kind


_classes = {}


def _make(kind):
    D = _mode_class()
    if not _classes:
        class ZoomMode(D):
            def drag(self, dx, dy):
                view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
                if view is not None:
                    if not getattr(self, "_pushed", False):
                        _push()
                        self._pushed = True
                    zoom(view, dy)

            def eventFilter(self, obj, event):
                if isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.MouseButtonRelease:
                    self._pushed = False
                return D.eventFilter(self, obj, event)

        class AreaMode(D):
            band = None
            origin = None

            def eventFilter(self, obj, event):
                if not isinstance(event, QtCore.QEvent):
                    return False
                from . import overridedrag
                QE = QtCore.QEvent
                t = event.type()
                if t == QE.KeyPress and event.key() == QtCore.Qt.Key_Escape:
                    self._drop_band()
                    self.stop()
                    return True
                if not isinstance(obj, overridedrag._gl_class()):
                    return False
                if t == QE.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                    self.origin = event.position().toPoint()
                    self._drop_band()
                    self.band = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Rectangle, obj)
                    self.band.setGeometry(QtCore.QRect(self.origin, QtCore.QSize()))
                    self.band.show()
                    return True
                if t == QE.MouseMove and self.origin is not None:
                    if self.band is not None:
                        self.band.setGeometry(QtCore.QRect(self.origin, event.position().toPoint()).normalized())
                    return True
                if t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton and self.origin is not None:
                    r = QtCore.QRect(self.origin, event.position().toPoint()).normalized()
                    self.origin = None
                    self._drop_band()
                    if r.width() > 3 and r.height() > 3:
                        self.zoom_to(obj, r)
                    return True
                return False

            def _drop_band(self):
                if self.band is not None:
                    try:
                        self.band.hide()
                        self.band.deleteLater()
                    except Exception as _fw_err:
                        _fw_log("viewtools.py:153", _fw_err)
                self.band = None

            def zoom_to(self, widget, r):
                view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
                if view is None:
                    return
                _push()
                dpr = widget.devicePixelRatioF()
                h = widget.height()
                # boxZoom takes viewport pixels with y up from the bottom
                x0, x1 = r.left() * dpr, r.right() * dpr
                y0, y1 = (h - r.bottom()) * dpr, (h - r.top()) * dpr
                try:
                    view.boxZoom(int(x0), int(y0), int(x1), int(y1))
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: zoom to area: %s\n" % error)

            def stop(self):
                self._drop_band()
                D.stop(self)

        _classes["zoom"], _classes["area"] = ZoomMode, AreaMode
    cls = _classes.get(kind, D)
    return cls(kind)


class _Cmd:
    def __init__(self, kind, label, tip, pixmap):
        self.kind, self.label, self.tip, self.pixmap = kind, label, tip, pixmap

    def GetResources(self):
        return {"MenuText": self.label, "ToolTip": self.tip, "Pixmap": self.pixmap}

    def IsActive(self):
        return Gui.ActiveDocument is not None and hasattr(Gui.ActiveDocument.ActiveView, "getCameraNode")

    def Activated(self):
        start(self.kind)


def install():
    _add_hints()
    if ZOOM_AREA not in Gui.listCommands():
        Gui.addCommand(ZOOM_AREA, _Cmd("area", "Zoom to Area", "Drag a box to zoom to it; stays on until Esc", "zoom-border"))
    if ZOOM_IN_OUT not in Gui.listCommands():
        Gui.addCommand(ZOOM_IN_OUT, _Cmd("zoom", "Zoom In/Out", "Drag up to zoom in, down to zoom out; stays on until Esc", "zoom-in"))
    try:
        from . import shell             # bindings made before these commands existed take them now
        sh = shell.shell()
        for key in ("ZoomArea",):
            b = sh.bindings.get(key) if sh is not None else None
            if b is not None and b.native != ZOOM_AREA:
                b.action = None
                b.resolve()
                b.update_state()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: view tools: %s\n" % error)
    try:
        from . import checkstate
        checkstate.register(ZOOM_AREA, lambda: on("area"))
        checkstate.register(ZOOM_IN_OUT, lambda: on("zoom"))
    except Exception as _fw_err:
        _fw_log("viewtools.py:216", _fw_err)
