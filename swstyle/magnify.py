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
import os
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths
from .widgets import alive

Qt = QtCore.Qt

ZOOM = "MagnifyZoom"         # addon parameter: how much the glass enlarges
DEFAULT_ZOOM = 4.0
ZOOMS = (1.5, 30.0)
SIZE = 240                   # glass diameter, in logical pixels
PICK = 5.0                   # pick distance, in glass pixels
REST = 180                   # ms the pointer rests before the sharp picture
RIM = 0.85                   # past this part of the radius the pointer pulls the glass along


def _zoom():
    return min(max(paths.params().GetFloat(ZOOM, DEFAULT_ZOOM), ZOOMS[0]), ZOOMS[1])


def _view():
    try:
        view = Gui.ActiveDocument.ActiveView
    except Exception:
        return None
    return view if hasattr(view, "getObjectInfo") else None


def _viewport():
    try:
        from . import shell as shell_module
        sh = shell_module.shell()
        view = sh.view_widget() if sh is not None else None
    except Exception:
        view = None
    if view is not None and hasattr(view, "viewport"):
        return view, view.viewport()
    return None, None


def _in_sketch():
    try:
        from . import contextbar
        return contextbar.sketch_in_edit() is not None
    except Exception:
        return False


# --------------------------------------------------------------------------- picking at the glass's scale
class Spot:
    """A point of the view in device pixels (y up, fractions allowed) and its ray."""

    def __init__(self, view, x, y):
        self.view, self.x, self.y = view, x, y
        x0, y0 = int(math.floor(x)), int(math.floor(y))
        p00 = App.Vector(view.getPoint((x0, y0)))
        ex = App.Vector(view.getPoint((x0 + 1, y0))) - p00
        ey = App.Vector(view.getPoint((x0, y0 + 1))) - p00
        self.focal = p00 + ex * (x - x0) + ey * (y - y0)       # on the focal plane
        self.per_pixel = max(ex.Length, 1e-12)
        self.dir = App.Vector(view.getViewDirection()).normalize()
        if "Perspective" in view.getCameraType():
            eye = App.Vector(*view.getCameraNode().position.getValue())
            d = self.focal - eye
            if d.Length > 1e-12:
                self.dir = d.normalize()
                self.eye = eye
                return
        self.eye = self.focal - self.dir * 1e5

    def pixels_to(self, point):
        """How far the point lies from the ray, in view pixels at its depth."""
        v = point - self.eye
        off = v - self.dir * v.dot(self.dir)
        scale = self.per_pixel
        if "Perspective" in self.view.getCameraType():
            focal_depth = (self.focal - self.eye).dot(self.dir)
            depth = v.dot(self.dir)
            if focal_depth > 1e-9 and depth > 1e-9:
                scale = self.per_pixel * depth / focal_depth
        return off.Length / scale


def _element(doc, info):
    """The picked element's shape, in the document's coordinates."""
    try:
        parent = info.get("ParentObject")
        if parent is not None and not isinstance(parent, str):
            obj = parent        # FreeCAD 1.1 gives the object itself, not its name: a body's edges and corners
                                # were never candidates, so the glass picked the face behind them (vd210, 11-27)
        else:
            obj = doc.getObject(parent or info["Object"])
        sub = info.get("SubName") if parent else info.get("Component")
        return obj.getSubObject(sub or "")
    except Exception:
        return None


def pick_at(view, x, y, zoom):
    """The pick under (x, y) judged at the glass's scale: a vertex or an edge whose drawing passes
    within PICK glass pixels, else what the ray through the spot hits. A dict as getObjectInfo
    gives, or None."""
    spot = Spot(view, x, y)
    limit = PICK / zoom
    best = None
    try:
        found = view.getObjectsInfo((int(round(x)), int(round(y)))) or []
    except Exception:
        found = []
    doc = App.ActiveDocument
    for info in found:
        comp = info.get("Component") or ""
        if not comp.startswith(("Vertex", "Edge")):
            continue
        shape = _element(doc, info)
        if shape is None:
            continue
        try:
            import Part
            line = Part.LineSegment(spot.eye, spot.eye + spot.dir * 2e5).toShape()
            near = shape.distToShape(line)[1][0][0]
        except Exception:
            continue
        d = spot.pixels_to(near)
        rank = (0 if comp.startswith("Vertex") else 1, d)
        if d <= limit and (best is None or rank < best[0]):
            best = (rank, info)
    if best is not None:
        return best[1]
    try:
        return view.getObjectInfoRay(spot.eye, spot.dir)
    except Exception:
        return None


def _select(info, add):
    doc = info.get("Document")
    top = info.get("ParentObject") or info.get("Object")
    sub = info.get("SubName") if info.get("ParentObject") else info.get("Component")
    if top is not None and not isinstance(top, str):
        top = top.Name          # FreeCAD 1.1 gives the parent object itself (a body's edge was never picked)
    if not add:
        Gui.Selection.clearSelection()
    try:
        if add and Gui.Selection.isSelected(App.getDocument(doc).getObject(top), sub or ""):
            Gui.Selection.removeSelection(doc, top, sub or "")
        else:
            Gui.Selection.addSelection(doc, top, sub or "")
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: magnified selection: %s\n" % error)


# --------------------------------------------------------------------------- the glass
class Glass(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SWMagnifyingGlass")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.image = None
        self.sharp = False
        self.mark = QtCore.QPointF()         # the pointer, from the middle
        self.resize(SIZE + 4, SIZE + 4)
        self.hide()

    def place(self, pos):
        self.move(int(pos.x()) - self.width() // 2, int(pos.y()) - self.height() // 2)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        circle = QtCore.QRectF(2, 2, SIZE, SIZE)
        path = QtGui.QPainterPath()
        path.addEllipse(circle)
        p.save()
        p.setClipPath(path)
        if self.image is not None and not self.image.isNull():
            p.drawImage(circle, self.image)
        else:
            p.fillRect(circle, QtGui.QColor(235, 235, 240))
        p.restore()
        p.setPen(QtGui.QPen(QtGui.QColor(70, 70, 70), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(circle)
        c = circle.center() + self.mark
        p.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20), 1))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p.drawLine(QtCore.QPointF(c.x() + dx * 4, c.y() + dy * 4), QtCore.QPointF(c.x() + dx * 10, c.y() + dy * 10))
        p.end()


class Magnifier(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.glass = None
        self.widget = None            # the viewport
        self.viewer = None            # the view widget (takes the keys)
        self.centre = None            # QPointF, viewport coordinates of the glass's middle
        self.pointer = None           # QPointF, viewport coordinates of the pointer
        self.cache = None             # (camera string, QImage of the view)
        self.rest = QtCore.QTimer(self)
        self.rest.setSingleShot(True)
        self.rest.setInterval(REST)
        self.rest.timeout.connect(self.sharpen)
        self.tmp = os.path.join(tempfile.gettempdir(), "freeworks-glass-%d.png" % os.getpid())
        # for checks
        self.picks = 0
        self.last_pick = None
        self.hover = None
        self.sharp_renders = 0

    def is_open(self):
        return self.glass is not None and alive(self.glass) and self.widget is not None

    def toggle(self):
        if self.is_open():
            self.close()
        else:
            self.open()

    def open(self, pos=None):
        viewer, widget = _viewport()
        if widget is None or _view() is None:
            return False
        self.close()
        self.viewer, self.widget = viewer, widget
        self.glass = Glass(widget)
        self.glass.destroyed.connect(self._glass_gone)
        widget.installEventFilter(self)
        viewer.installEventFilter(self)
        widget.setMouseTracking(True)
        self._esc_first()
        self.cache = None
        if pos is None:
            pos = QtCore.QPointF(widget.mapFromGlobal(QtGui.QCursor.pos()))
        if not widget.rect().contains(QtCore.QPointF(pos).toPoint()):
            pos = QtCore.QPointF(widget.width() / 2.0, widget.height() / 2.0)
        self.centre = None
        self.follow(QtCore.QPointF(pos))
        return True

    def _esc_first(self):
        ""

        try:
            from . import events
            events.register("magnify-esc", (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress), self._esc)
            for t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
                lst = events._BY_TYPE.get(t, [])
                lst[:] = [e for e in lst if e[0] == "magnify-esc"] + [e for e in lst if e[0] != "magnify-esc"]
        except Exception as _fw_err:
            _fw_log("magnify.py:esc", _fw_err)

    def _glass_gone(self, *_args):
        """The glass went with its view or document, without close(): take its Esc handler off too (Reviewer,
        11-27). A glass put away by close() and then opened again keeps the new one's."""
        if self.glass is not None and alive(self.glass):
            return
        try:
            from . import events
            events.unregister("magnify-esc")
        except Exception as _fw_err:
            _fw_log("magnify.py:esc-gone", _fw_err)
        self.rest.stop()
        self.glass = self.widget = self.viewer = None

    def _esc(self, obj, event):
        if not isinstance(event, QtGui.QKeyEvent) or event.key() != Qt.Key_Escape or not self.is_open():
            return False
        if QtWidgets.QApplication.activeModalWidget() is not None or QtWidgets.QApplication.activePopupWidget() is not None:
            return False        # a dialog or a menu on top takes its own Esc
        if event.type() == QtCore.QEvent.KeyPress:
            QtCore.QTimer.singleShot(0, self.close)
        event.accept()
        return True

    def close(self):
        self.rest.stop()
        try:
            from . import events
            events.unregister("magnify-esc")
        except Exception as _fw_err:
            _fw_log("magnify.py:esc-off", _fw_err)
        for w in (self.widget, self.viewer):
            if w is not None and alive(w):
                w.removeEventFilter(self)
        if self.glass is not None and alive(self.glass):
            try:
                self.glass.destroyed.disconnect(self._glass_gone)
            except (RuntimeError, TypeError) as _fw_err:
                _fw_log("magnify.py:gone-off", _fw_err)
            self.glass.hide()
            self.glass.deleteLater()
        self.glass = self.widget = self.viewer = None
        try:
            Gui.Selection.removePreselection()
        except Exception as _fw_err:
            _fw_log("magnify.py:279", _fw_err)

    # ------------------------------------------------------------------ where
    def device(self, pos):
        """Viewport coordinates -> view device pixels, y up."""
        dpr = self.widget.devicePixelRatioF()
        view = _view()
        height = view.getSize()[1] if view is not None else self.widget.height() * dpr
        return pos.x() * dpr, height - pos.y() * dpr

    def target(self):
        """Where the pointer points in the view: the spot it shows enlarged in the glass."""
        d = (self.pointer - self.centre) / _zoom()
        return self.centre + d

    def follow(self, pos):
        self.pointer = QtCore.QPointF(pos)
        moved = False
        if self.centre is None:
            self.centre, moved = QtCore.QPointF(pos), True
        else:
            d = self.pointer - self.centre
            r = math.hypot(d.x(), d.y())
            reach = RIM * SIZE / 2.0
            if r > reach:
                self.centre = self.pointer - d * (reach / r)
                moved = True
        self.glass.place(self.centre)
        self.glass.mark = self.pointer - self.centre
        self.glass.update()
        self.glass.show()
        self.glass.raise_()
        if moved:
            self.quick()
        self.rest.start()

    # ------------------------------------------------------------------ pictures
    def _grab(self):
        view = _view()
        key = view.getCamera() if view is not None else ""
        if self.cache is None or self.cache[0] != key:
            image = self.widget.grabFramebuffer() if hasattr(self.widget, "grabFramebuffer") else self.widget.grab().toImage()
            self.cache = (key, image)
        return self.cache[1]

    def quick(self):
        """The view's own pixels, enlarged."""
        try:
            image = self._grab()
        except Exception as _fw_err:
            _fw_log("magnify.py:330", _fw_err)
            return
        dpr = self.widget.devicePixelRatioF()
        side = SIZE * dpr / _zoom()
        cx, cy = self.centre.x() * dpr, self.centre.y() * dpr
        src = QtCore.QRectF(cx - side / 2.0, cy - side / 2.0, side, side)
        out = QtGui.QImage(int(SIZE * dpr), int(SIZE * dpr), QtGui.QImage.Format_RGB32)
        out.fill(QtGui.QColor(235, 235, 240))
        p = QtGui.QPainter(out)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        p.drawImage(QtCore.QRectF(0, 0, out.width(), out.height()), image, src)
        p.end()
        self.glass.image, self.glass.sharp = out, False
        self.glass.update()

    def sharpen(self):
        """FreeCAD draws the spot at the glass's scale; the view's camera is put back at once."""
        if not self.is_open():
            return
        view = _view()
        if view is None:
            return
        self.preselect()
        cam = view.getCameraNode()
        x, y = self.device(self.centre)
        dpr = self.widget.devicePixelRatioF()
        side = int(SIZE * dpr)
        zoom = _zoom()
        spot = Spot(view, x, y)
        centre = Spot(view, view.getSize()[0] / 2.0, view.getSize()[1] / 2.0)
        saved = {}
        for name in ("position", "orientation", "height", "heightAngle"):
            if hasattr(cam, name):
                value = getattr(cam, name).getValue()
                # pivy hands back the field's own vector: keep plain numbers
                saved[name] = tuple(value.getValue()) if hasattr(value, "getValue") else value
        try:
            if "height" in saved:
                cam.height.setValue(side / zoom * spot.per_pixel)
                shift = spot.focal - centre.focal
                p = cam.position.getValue()
                cam.position.setValue(p[0] + shift.x, p[1] + shift.y, p[2] + shift.z)
            elif "heightAngle" in saved:
                half = math.atan(math.tan(saved["heightAngle"] / 2.0) * (side / zoom) / view.getSize()[1])
                cam.heightAngle.setValue(2.0 * half)
                from pivy import coin
                old = centre.dir
                turn = coin.SbRotation(coin.SbVec3f(old.x, old.y, old.z), coin.SbVec3f(spot.dir.x, spot.dir.y, spot.dir.z))
                cam.orientation.setValue(cam.orientation.getValue() * turn)
            view.saveImage(self.tmp, side, side, "Current")
        except Exception as error:
            App.Console.PrintLog("FreeCAD: magnifying glass: %s\n" % error)
        finally:
            for name, value in saved.items():
                if isinstance(value, tuple):
                    getattr(cam, name).setValue(*value)
                else:
                    getattr(cam, name).setValue(value)
        image = QtGui.QImage(self.tmp)
        if not image.isNull():
            self.glass.image, self.glass.sharp = image, True
            self.sharp_renders += 1
            self.glass.update()

    def preselect(self):
        if _in_sketch():
            return
        view = _view()
        x, y = self.device(self.target())
        info = pick_at(view, x, y, _zoom())
        self.hover = info
        try:
            Gui.Selection.removePreselection()
            if info is not None:
                doc = App.getDocument(info["Document"])
                top = doc.getObject(info.get("ParentObject") or info["Object"])
                sub = info.get("SubName") if info.get("ParentObject") else info.get("Component")
                pt = info.get("PickedPoint") or App.Vector(info.get("x", 0), info.get("y", 0), info.get("z", 0))
                Gui.Selection.setPreselection(top, sub or "", pt.x, pt.y, pt.z)
        except Exception as _fw_err:
            _fw_log("magnify.py:408", _fw_err)

    # ------------------------------------------------------------------ events
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if obj is self.viewer:
            if t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress) and event.key() == Qt.Key_Escape:
                if t == QtCore.QEvent.KeyPress:
                    QtCore.QTimer.singleShot(0, self.close)
                event.accept()
                return True
            return False
        if obj is not self.widget:
            return False
        if t == QtCore.QEvent.MouseMove:
            self.follow(QtCore.QPointF(event.position()))
            return not event.buttons()          # a drag (turn, pan) stays FreeCAD's
        if t == QtCore.QEvent.Wheel:
            steps = event.angleDelta().y() / 120.0
            paths.params().SetFloat(ZOOM, min(max(_zoom() * (1.25 ** steps), ZOOMS[0]), ZOOMS[1]))
            self.quick()
            self.rest.start()
            return True
        if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick):
            if event.button() != Qt.LeftButton or _in_sketch():
                return False
            if t == QtCore.QEvent.MouseButtonRelease:
                self.click(QtCore.QPointF(event.position()), bool(event.modifiers() & Qt.ControlModifier))
            return True
        if t == QtCore.QEvent.Leave:
            if self.glass is not None and alive(self.glass):
                self.glass.hide()
            return False
        if t == QtCore.QEvent.Resize:
            self.cache = None
        return False

    def click(self, pos, add):
        view = _view()
        if view is None:
            return
        self.follow(pos)
        x, y = self.device(self.target())
        info = pick_at(view, x, y, _zoom())
        self.picks += 1
        self.last_pick = info
        if info is None:
            if not add:
                Gui.Selection.clearSelection()
        else:
            _select(info, add)
        self.cache = None
        QtCore.QTimer.singleShot(0, self.sharpen)


GLASS = Magnifier()


class _Command:
    def GetResources(self):
        return {"MenuText": "Magnified Selection",
                "ToolTip": "Shows a magnifying glass at the pointer (G): pick small items without zooming the view; "
                           "the wheel changes the enlargement, G or Esc puts it away.",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return Gui.ActiveDocument is not None

    def Activated(self):
        GLASS.toggle()


def register():
    if "SWStyle_MagnifiedSelection" not in Gui.listCommands():
        Gui.addCommand("SWStyle_MagnifiedSelection", _Command())
