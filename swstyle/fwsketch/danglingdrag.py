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
import Part

try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtGui, QtWidgets

RED = QtGui.QColor(0xEB, 0x00, 0x08)
RADIUS = 4.5        # logical pixels
REACH = 8.0         # a press this close takes the dot
UNDEF = -2000
STEP = "Repair Dangling Relation"
HINT = "Drop the red dot on an edge or vertex of the model to re-attach the dangling relation."


def handles(sketch):
    """[(external index k, App.Vector global)]: one dot per dangling model reference that a relation
    or dimension still uses."""
    try:
        from .. import relationspm
        missing = relationspm._missing_externals(sketch)
    except Exception as err:
        _fw_log("fwsketch/danglingdrag.py:missing", err)
        return []
    if not missing:
        return []
    out = []
    placement = sketch.getGlobalPlacement()
    cons = sketch.Constraints
    for k, _obj, _element, geo in missing:
        g = -3 - k
        used = [c for c in cons if g in (c.First, c.Second, c.Third)]
        if not used:
            continue
        try:
            at = _place(sketch, geo, g, used)
        except Exception as err:
            _fw_log("fwsketch/danglingdrag.py:place", err)
            at = None
        if at is not None:
            out.append((k, placement.multVec(at)))
    return out


def _place(sketch, geo, g, used):
    """The point of the lost geometry nearest the sketch point its first relation holds."""
    if isinstance(geo, Part.Point):
        return App.Vector(geo.X, geo.Y, 0)
    own = None
    for c in used:
        for gg, pp in ((c.First, int(c.FirstPos)), (c.Second, int(c.SecondPos)), (c.Third, int(c.ThirdPos))):
            if gg not in (UNDEF, g) and gg >= 0 and pp in (1, 2, 3):
                own = sketch.getPoint(gg, pp)
                break
        if own is not None:
            break
    if own is not None:
        try:
            return geo.value(geo.parameter(own))
        except Exception as err:
            _fw_log("fwsketch/danglingdrag.py:nearest", err)
    return geo.value((geo.FirstParameter + geo.LastParameter) / 2.0)


def element_at(view, sketch, at):
    """(object, "EdgeN" / "VertexN") of the model under view pixel at (Inventor's, from the bottom
    left), or None. The sketch's own entities under it do not count (the dot is dragged over them)."""
    try:
        hits = view.getObjectsInfo(at) or []
    except Exception as err:
        _fw_log("fwsketch/danglingdrag.py:hits", err)
        return None
    doc = sketch.Document
    for hit in hits:
        name, sub = hit.get("Object"), hit.get("Component") or ""
        if not name or name == sketch.Name or not sub.startswith(("Edge", "Vertex")):
            continue
        obj = doc.getObject(name)
        if obj is not None and hasattr(obj, "Shape"):
            return obj, sub
    return None


class Overlay(QtWidgets.QWidget):
    """The red dots over one view's viewport, and the dragged one."""

    def __init__(self, viewport, view):
        super().__init__(viewport)
        self.setObjectName("FwDanglingDots")
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.viewport, self.view = viewport, view
        self.items = []         # [(k, App.Vector global)]
        self.drag = None        # (k, QPointF start, QPointF now) while dragging
        self.placed = []        # [(k, QPointF)] the last paint, for tests
        self._pending = False
        self.resize(viewport.size())
        viewport.installEventFilter(self)

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QtCore.QEvent.Resize:
            self.resize(self.viewport.size())
        if t in (QtCore.QEvent.Paint, QtCore.QEvent.UpdateRequest) and self.items and not self._pending:
            self._pending = True
            QtCore.QTimer.singleShot(0, self._again)
        return False

    def _again(self):
        self._pending = False
        try:
            self.update()
        except RuntimeError:
            pass

    def set_items(self, items):
        self.items = items
        if not items:
            self.placed = []
        self.setVisible(bool(items))
        if items:
            self.raise_()
        self.update()

    def screen(self, v):
        x, y = self.view.getPointOnViewport(v)[:2]
        ratio = self.viewport.devicePixelRatioF() if hasattr(self.viewport, "devicePixelRatioF") else 1.0
        return QtCore.QPointF(x / ratio, (self.viewport.height() * ratio - y) / ratio)

    def paintEvent(self, _event):
        self.placed = []
        if not self.items:
            return
        p = QtGui.QPainter(self)
        try:
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            p.setBrush(RED)
            p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1.0))
            for k, v in self.items:
                try:
                    at = self.screen(v)
                except Exception:
                    continue
                if self.drag is not None and self.drag[0] == k:
                    pen = QtGui.QPen(RED, 1.2, QtCore.Qt.DashLine)
                    p.setPen(pen)
                    p.drawLine(at, self.drag[2])
                    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0), 1.0))
                    at = self.drag[2]
                p.drawEllipse(at, RADIUS, RADIUS)
                self.placed.append((k, at))
        finally:
            p.end()


class Dragger(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.overlay = None
        self.done = []          # (k, (object name, sub)) repaired, for tests
        from . import appevents
        appevents.listen(self, (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                                QtCore.QEvent.MouseButtonRelease))

    def stop(self):
        try:
            from . import appevents
            appevents.stop(self)
        except RuntimeError as err:
            _fw_log("fwsketch/danglingdrag.py:stop", err)
        self.clear()

    def clear(self):
        if self.overlay is not None:
            try:
                self.overlay.drag = None
                self.overlay.set_items([])
            except RuntimeError:
                self.overlay = None

    def _drop_overlay(self):
        """The old view's dots go with their viewport filter (a new view gets its own overlay)."""
        o, self.overlay = self.overlay, None
        if o is None:
            return
        try:
            o.viewport.removeEventFilter(o)
            o.deleteLater()
        except RuntimeError:
            pass            # its viewport (and so the overlay) is already gone

    def _context(self):
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc else None
        obj = getattr(vp, "Object", None) if vp is not None else None
        if obj is None or not obj.isDerivedFrom("Sketcher::SketchObject"):
            return None
        from . import tool
        if tool.active() is not None:
            return None
        return gdoc.ActiveView, obj

    def update(self, view, sketch):
        """The dots of the sketch in edit (overdefined.py calls this after each refresh)."""
        try:
            items = handles(sketch)
        except Exception as err:
            _fw_log("fwsketch/danglingdrag.py:update", err)
            items = []
        if not items and self.overlay is None:
            return items
        o = self.overlay
        try:
            if o is None or o.view is not view or o.isVisible() is None:
                raise RuntimeError
        except RuntimeError:
            self._drop_overlay()
            try:
                o = self.overlay = Overlay(view.graphicsView().viewport(), view)
            except Exception as err:
                _fw_log("fwsketch/danglingdrag.py:overlay", err)
                return items
        if o.drag is None:
            o.set_items(items)
        return items

    def eventFilter(self, obj, event):
        o = self.overlay
        try:
            if o is None or not o.items or obj is not o.viewport:
                return False
        except RuntimeError:
            self.overlay = None
            return False
        t = event.type()
        pos = event.position() if hasattr(event, "position") else QtCore.QPointF(event.pos())
        if t == QtCore.QEvent.MouseButtonPress:
            held = event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier | QtCore.Qt.AltModifier)
            if event.button() != QtCore.Qt.LeftButton or held or self._context() is None:
                return False
            for k, at in o.placed:
                if (at - pos).manhattanLength() <= REACH * 1.5 and QtCore.QLineF(at, pos).length() <= REACH:
                    o.drag = (k, at, pos)
                    o.update()
                    return True
            return False
        if o.drag is None:
            return False
        if t == QtCore.QEvent.MouseMove:
            o.drag = (o.drag[0], o.drag[1], pos)
            o.update()
            return True
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            k = o.drag[0]
            o.drag = None
            self.drop(k, pos)
            return True
        return False

    def drop(self, k, pos):
        ctx = self._context()
        if ctx is None:
            return False
        view, sketch = ctx
        ratio = self.overlay.viewport.devicePixelRatioF() if hasattr(self.overlay.viewport, "devicePixelRatioF") else 1.0
        at = (int(pos.x() * ratio), int((self.overlay.viewport.height() - pos.y()) * ratio))
        found = element_at(view, sketch, at)
        if found is None or not str(found[1]).startswith(("Edge", "Vertex")):
            self._say(HINT)
            self.overlay.update()
            return False
        from .. import relationspm
        doc = sketch.Document
        doc.openTransaction(STEP)
        try:
            ok = relationspm.repair_one(sketch, k, found)
        except Exception as err:
            ok = False
            _fw_log("fwsketch/danglingdrag.py:repair", err)
        if not ok:
            doc.abortTransaction()
            self._say(HINT)
            return False
        doc.commitTransaction()
        doc.recompute()
        self.done.append((k, (found[0].Name, found[1])))
        self.update(view, sketch)
        return True

    @staticmethod
    def _say(text):
        try:
            Gui.getMainWindow().statusBar().showMessage(text, 6000)
        except Exception as err:
            _fw_log("fwsketch/danglingdrag.py:say", err)


_dragger = [None]


def start():
    if _dragger[0] is None:
        _dragger[0] = Dragger()
    return _dragger[0]


def dragger():
    return _dragger[0]


def update(view, sketch):
    d = _dragger[0]
    return d.update(view, sketch) if d is not None else []
