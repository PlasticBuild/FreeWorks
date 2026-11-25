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
from .widgets import alive

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchSettings"
KEY = "OverrideDimsOnDrag"
COMMAND = "SWStyle_OverrideDimsOnDrag"
TRANSACTION = "Drag with Dimensions"
DIMENSIONS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
UNDEF = -2000
V = App.Vector


def on():
    return App.ParamGet(PARAMS).GetBool(KEY, False)


def _connected(sketch, geo):
    """The entities tied to geo through relations, directly or not (the origin's axes cut ties)."""
    links = {}
    for c in sketch.Constraints:
        geos = [g for g in (c.First, c.Second, c.Third) if g >= 0]
        for a in geos:
            links.setdefault(a, set()).update(geos)
    seen, todo = {geo}, [geo]
    while todo:
        for g in links.get(todo.pop(), ()):
            if g not in seen:
                seen.add(g)
                todo.append(g)
    return seen


def _points(sketch, geo, pos):
    """The dragged point and the points joined to it (Coincident), as (geo, pos) pairs; for a
    whole entity (pos 0) its own end, centre points and the entity itself."""
    pts = {(geo, pos)} if pos else {(geo, 0), (geo, 1), (geo, 2), (geo, 3)}
    grew = True
    while grew:
        grew = False
        for c in sketch.Constraints:
            if c.Type != "Coincident":
                continue
            a, b = (c.First, c.FirstPos), (c.Second, c.SecondPos)
            if a in pts and b not in pts:
                pts.add(b); grew = True
            elif b in pts and a not in pts:
                pts.add(a); grew = True
    return pts


def dimensions(sketch, geo, pos=0):
    ""


    pts = _points(sketch, geo, pos)
    geos = {g for g, _p in pts}
    out = []
    for i, c in enumerate(sketch.Constraints):
        if c.Type not in DIMENSIONS or not c.Driving:
            continue
        refs = [(c.First, c.FirstPos), (c.Second, c.SecondPos), (c.Third, c.ThirdPos)]
        on_point = any(r in pts for r in refs if r[0] >= 0 and r[1] != 0)
        size = c.First in geos and c.FirstPos == 0 and c.Second < 0 if c.Type != "Angle" else \
            (c.First in geos or c.Second in geos)
        if on_point or size:
            out.append(i)
    return out


def free(sketch, indices):
    for i in indices:
        sketch.setDriving(i, False)
    sketch.solve()


def drive(sketch, indices):
    """The freed dimensions drive again, at the values they measure now."""
    for i in indices:
        sketch.setDriving(i, True)
    sketch.solve()


def _sketch():
    try:
        from . import contextbar
        return contextbar.sketch_in_edit()
    except Exception:
        return None


class _GLView(type):
    def __instancecheck__(cls, obj):
        # FreeCAD 1.1's 3D view drawing area comes to Python as a plain QWidget (its class is not
        # wrapped), so isinstance(QOpenGLWidget) is never true there: ask Qt what it is instead
        try:
            return isinstance(obj, QtCore.QObject) and obj.inherits("QOpenGLWidget")
        except Exception:
            return False


class GLView(metaclass=_GLView):
    """isinstance(widget, GLView): widget is the 3D view's drawing area."""


def _gl_class():
    return GLView


def local(sketch, widget, pos):
    """Viewport position -> the point on the sketch plane, in sketch coordinates."""
    view = Gui.ActiveDocument.ActiveView
    dpr = widget.devicePixelRatioF()
    x, y = pos.x() * dpr, view.getSize()[1] - pos.y() * dpr
    on_focal = V(view.getPoint((int(round(x)), int(round(y)))))
    direction = V(view.getViewDirection())
    pl = sketch.getGlobalPlacement()
    normal = pl.Rotation.multVec(V(0, 0, 1))
    denom = direction.dot(normal)
    hit = on_focal if abs(denom) < 1e-9 else \
        on_focal + direction * ((pl.Base - on_focal).dot(normal) / denom)
    p = pl.inverse().multVec(hit)
    return V(p.x, p.y, 0)


class _Filter(QtCore.QObject):
    """Holds a press on a sketch entity; a move then drags it with its dimensions freed."""

    instance = None

    def __init__(self):
        super().__init__()
        self.held = None        # (widget, press position, sketch, geo, pos)
        self.drag = None        # (sketch, geo, pos, freed, last point)
        self.sending = False
        from .fwsketch import appevents
        appevents.listen(self, (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove))   # one application filter (fix65)

    def _entity(self, widget):
        """(sketch, geo, pos) under the pointer, when a press there should wait."""
        return self._under(widget) if on() else None

    def _under(self, widget):
        """(sketch, geo, pos) of the sketch entity under the pointer, with no drawing tool running."""
        if not isinstance(widget, _gl_class()):
            return None
        sketch = _sketch()
        if sketch is None or widget.cursor().shape() == QtCore.Qt.BitmapCursor:
            return None          # a drawing tool has its own cursor
        pre = Gui.Selection.getPreselection()
        subs = pre.SubElementNames
        if not subs:
            return None
        parts = subs[0].split(".")
        owner = pre.ObjectName if len(parts) == 1 else parts[-2]
        if owner != sketch.Name:
            return None
        name = parts[-1]
        if name.startswith("Edge"):
            return sketch, int(name[4:]) - 1, 0
        if name.startswith("Vertex"):
            geo, pos = sketch.getGeoVertexIndex(int(name[6:]) - 1)
            if geo >= 0:
                return sketch, geo, int(pos)
        return None

    def _send(self, widget, kind, pos, buttons):
        from PySide import QtGui
        e = QtGui.QMouseEvent(kind, QtCore.QPointF(pos), QtCore.QPointF(widget.mapToGlobal(QtCore.QPointF(pos))),
                              QtCore.Qt.LeftButton, buttons, QtCore.Qt.NoModifier)
        self.sending = True
        try:
            QtWidgets.QApplication.sendEvent(widget, e)
        finally:
            self.sending = False

    def _start(self, widget, pos):
        _w, _p, sketch, geo, gpos = self.held
        self.held = None
        freed = dimensions(sketch, geo, gpos)
        sketch.Document.openTransaction(TRANSACTION)
        try:
            try:
                from . import detachdrag
                if gpos == 0 and detachdrag.on():
                    detachdrag.detach(sketch, geo)
                    freed = dimensions(sketch, geo, gpos)
            except Exception as _fw_err:
                _fw_log("overridedrag.py:212", _fw_err)
            free(sketch, freed)
            self._widget = widget
            self.drag = (sketch, geo, gpos, freed, local(sketch, widget, _p))
        except BaseException:
            try:
                sketch.Document.abortTransaction()
            except Exception:
                pass
            raise
        self._move(widget, pos)

    def _move(self, widget, pos):
        sketch, geo, gpos, freed, last = self.drag
        here = local(sketch, widget, pos)
        try:
            if gpos == 0:
                sketch.moveGeometry(geo, 0, here - last, True)
            else:
                sketch.moveGeometry(geo, gpos, here, False)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: drag with dimensions: %s\n" % error)
        self.drag = (sketch, geo, gpos, freed, here)
        Gui.updateGui()

    def _finish(self):
        sketch, geo, gpos, freed, last = self.drag
        self.drag = None
        if gpos != 0:
            # FreeCAD's drag solve moves a point only part of the way when the pointer runs ahead:

            for _k in range(8):
                try:
                    if (sketch.getPoint(geo, gpos) - last).Length < 1e-6:
                        break
                    sketch.moveGeometry(geo, gpos, last, False)
                except Exception:
                    break
        try:
            drive(sketch, freed)
            sketch.recompute()
        finally:
            sketch.Document.commitTransaction()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter237(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter overridedrag.py: %s\n" % exc)
            return False

    def _fw_filter237(self, obj, event):
        if self.sending:
            return False
        t = event.type()
        QE = QtCore.QEvent
        if self.drag is not None:
            if t == QE.MouseMove and isinstance(obj, _gl_class()):
                self._move(obj, event.position())
                return True
            if t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
                widget = getattr(self, "_widget", None)
                if widget is not None and alive(widget):
                    # where the pointer is now: moves still queued must not leave the point behind
                    from PySide import QtGui
                    sketch, geo, gpos, freed, _last = self.drag
                    at = QtCore.QPointF(widget.mapFromGlobal(QtGui.QCursor.pos()))
                    self.drag = (sketch, geo, gpos, freed, local(sketch, widget, at))
                self._finish()
                return True
            return False
        if t == QE.MouseButtonPress and event.button() == QtCore.Qt.LeftButton \
                and event.modifiers() == QtCore.Qt.NoModifier:
            if not isinstance(obj, QtWidgets.QWidget):
                return False
            found = self._entity(obj)
            if found is None:
                return False
            self.held = (obj, event.position()) + found
            return True
        if self.held is None or obj is not self.held[0]:
            return False
        widget, pos = self.held[0], self.held[1]
        if t == QE.MouseMove:
            if (event.position() - pos).manhattanLength() < QtWidgets.QApplication.startDragDistance():
                return True
            self._start(widget, event.position())
            return True
        if t == QE.MouseButtonRelease:
            # a plain click: FreeCAD gets its press and release and picks as usual
            self.held = None
            self._send(widget, QE.MouseButtonPress, pos, QtCore.Qt.LeftButton)
            return False
        return False


class _Toggle:
    def GetResources(self):
        return {"MenuText": "Override Dims on Drag/Move", "Pixmap": "Constraint_Length",
                "ToolTip": "Dragging a sketch entity changes the dimensions that hold it",
                "Checkable": on(), "CmdType": "ForEdit"}

    def Activated(self, checked):
        App.ParamGet(PARAMS).SetBool(KEY, bool(checked))

    def IsActive(self):
        state = on()
        try:
            actions = Gui.Command.get(COMMAND).getAction()
        except Exception:
            actions = []
        for action in actions:
            if action.isChecked() != state:
                blocked = action.blockSignals(True)
                action.setChecked(state)
                action.blockSignals(blocked)
        return App.ActiveDocument is not None


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, _Toggle())
    if _Filter.instance is None:
        _Filter.instance = _Filter()
