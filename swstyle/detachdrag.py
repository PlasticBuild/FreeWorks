# SPDX-License-Identifier: LGPL-2.1-or-later
""









import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchSettings"
KEY = "DetachSegmentOnDrag"
COMMAND = "SWStyle_DetachSegmentOnDrag"
UNDEF = -2000
JOINS = ("Coincident", "PointOnObject", "Tangent", "Perpendicular")


def on():
    return App.ParamGet(PARAMS).GetBool(KEY, False)


def joins(sketch, geo):
    """The relations that join geo's ends to other entities (indices)."""
    out = []
    for i, c in enumerate(sketch.Constraints):
        if c.Type not in JOINS or c.Second == UNDEF:
            continue
        ends = [(c.First, c.FirstPos), (c.Second, c.SecondPos)]
        mine = [p for g, p in ends if g == geo]
        others = [g for g, _ in ends if g != geo]
        if not mine or not others:
            continue
        if c.Type == "PointOnObject":
            # this segment's end on another curve, or another entity's point on this segment
            out.append(i)
        elif any(p in (1, 2) for p in mine):
            out.append(i)
    return out


def detach(sketch, geo):
    """Deletes the relations joining geo's ends to the rest; how many went."""
    doomed = joins(sketch, geo)
    for i in reversed(doomed):
        sketch.delConstraint(i)
    return len(doomed)


def _sketch():
    try:
        from . import contextbar
        return contextbar.sketch_in_edit()
    except Exception:
        return None


class _Filter(QtCore.QObject):
    """Holds a press on a segment back until the pointer moves (then detaches) or lets go."""

    instance = None

    def __init__(self):
        super().__init__()
        self.held = None        # (widget, press position, modifiers, geo)
        self.sending = False
        from .fwsketch import appevents
        appevents.listen(self, (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove))   # one application filter (fix65)

    def _segment(self, widget):
        """(sketch, geo) of the sketch segment under the pointer, when a press there should wait."""
        if not on() or not isinstance(widget, _gl_class()):
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
        if owner != sketch.Name or not parts[-1].startswith("Edge"):
            return None
        return sketch, int(parts[-1][4:]) - 1

    def _press(self, widget, pos, mods):
        e = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, QtCore.QPointF(pos),
                              QtCore.QPointF(widget.mapToGlobal(QtCore.QPointF(pos))),
                              QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, mods)
        self.sending = True
        try:
            QtWidgets.QApplication.sendEvent(widget, e)
        finally:
            self.sending = False

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter100(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter detachdrag.py: %s\n" % exc)
            return False

    def _fw_filter100(self, obj, event):
        if self.sending:
            return False
        t = event.type()
        QE = QtCore.QEvent
        if t == QE.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            if not isinstance(obj, QtWidgets.QWidget):
                return False
            found = self._segment(obj)
            if found is None:
                return False
            self.held = (obj, event.position(), event.modifiers(), found)
            return True
        if self.held is None or obj is not self.held[0]:
            return False
        widget, pos, mods, (sketch, geo) = self.held
        if t == QE.MouseMove:
            if (event.position() - pos).manhattanLength() < QtWidgets.QApplication.startDragDistance():
                return True
            self.held = None
            doc = sketch.Document
            if joins(sketch, geo):
                doc.openTransaction("Detach Segment")
                try:
                    detach(sketch, geo)
                    sketch.solve()
                finally:
                    doc.commitTransaction()
            self._press(widget, pos, mods)
            return False
        if t == QE.MouseButtonRelease:
            self.held = None
            self._press(widget, pos, mods)
            return False
        return False


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


class _Toggle:
    def GetResources(self):
        return {"MenuText": "Detach Segment on Drag", "Pixmap": "Sketcher_Toggle_Constraint_Driving",
                "ToolTip": "Dragging a sketch segment pulls it loose from the entities its ends are joined to",
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
