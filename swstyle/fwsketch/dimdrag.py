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

import FreeCADGui as Gui

try:
    from PySide import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtWidgets

NO_DIMENSION = "A dimension could not be created from the selected items."
DRAG_STEP = "Drag Constraint"


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


def _pre(sketch):
    """FreeCAD's preselection in the sketch: ("constraint", index), ("geometry", sub) or None."""
    from .toolbase import preselected_subs
    subs = preselected_subs(sketch)
    sub = subs[0] if subs else ""
    if sub.startswith("Constraint"):
        try:
            return ("constraint", int(sub[len("Constraint"):]) - 1)
        except ValueError:
            return None
    if sub.startswith(("Edge", "Vertex", "RootPoint", "H_Axis", "V_Axis", "ExternalEdge")):
        return ("geometry", sub)
    return None


def _sketch_under(sketch):
    """True when Coin finds the sketch under the pointer. FreeCAD's preselection is no help at
    release: the tool keeps the drag's moves from FreeCAD, so it still names the pressed item."""
    try:
        view = Gui.ActiveDocument.ActiveView
        hits = view.getObjectsInfo(view.getCursorPos()) or []
    except Exception:
        return _pre(sketch) is not None
    return any(h.get("Object") == sketch.Name for h in hits)


def _global(event):
    try:
        return event.globalPosition().toPoint()
    except AttributeError:
        return event.globalPos()


class _State:
    def __init__(self):
        self.native = False      # FreeCAD has the press: a constraint drag
        self.press = None        # (global point, preselection) of a press on geometry
        self.dragged = False
        self.tips = []           # tooltips shown, for tests
        self.label = None        # (index, LabelDistance, LabelPosition) at the press
        self.ending = False      # the release went to FreeCAD; the step closes in a moment
        self.swallow = False     # the release kept from the tool (it comes twice)
        self.clicked = []        # dimensions clicked (no drag): their Modify box, for tests


def state(tool):
    s = getattr(tool, "_fw_dimdrag", None)
    if s is None:
        s = tool._fw_dimdrag = _State()
    return s


def _point_under(tool):
    """A sketch point within a few pixels of the pointer (under a dimension's extension line)."""
    try:
        from . import dimension as D
        p, px = tool.pointer()
        if p is None or not px:
            return False
        under = D.element_under(tool.sketch, p, px * 6.0)
        return under is not None and under.name.startswith("Vertex")
    except Exception:
        return False


def filter(tool, obj, event):
    if obj is not tool.viewport and obj is not getattr(tool, "quarter", None):
        return None
    t = event.type()
    s = state(tool)
    # the tool filters the view and its viewport, so each event can come twice
    if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
        if s.native:
            return False
        pre = _pre(tool.sketch)
        if pre is not None and pre[0] == "constraint" and _point_under(tool):
            pre = None
        if tool.empty() and pre is not None and pre[0] == "constraint":
            s.native = True
            from . import trace
            trace.note("dimdrag native press %d" % pre[1])
            c = tool.sketch.Constraints[pre[1]]
            s.label = (pre[1], c.LabelDistance, c.LabelPosition)

            tool.sketch.Document.openTransaction(DRAG_STEP)
            return False                       # FreeCAD drags the dimension
        s.press = (_global(event), pre) if pre is not None and pre[0] == "geometry" else None
        s.drag_pick = None
        if s.press is not None and tool.empty() and not tool.indexes:
            # dragdim-1127: what a click-drag starts from (the pressed element and where), see _drag_place
            try:
                from . import dimension as D
                s.drag_pick = (D.preselected(tool.sketch), tool.pointer()[0])
            except Exception as _fw_err:
                _fw_log("fwsketch/dimdrag.py:drag-pick", _fw_err)
        s.dragged = False
        return None
    if t == QtCore.QEvent.MouseMove:
        if s.native:
            return False
        if s.press is not None and not s.dragged:
            if (_global(event) - s.press[0]).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                s.dragged = True
        return None
    if t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
        if s.native:
            if not s.ending:
                s.ending = True
                QtCore.QTimer.singleShot(0, lambda: _after_native(tool))
            return False
        if s.swallow:
            return True
        press, s.press = s.press, None
        drag_pick, s.drag_pick = getattr(s, "drag_pick", None), None
        if press is not None and s.dragged and drag_pick is not None and drag_pick[0] is not None \
                and drag_pick[1] is not None:

            # the dimension of what was pressed is placed where the button comes up, then the Modify box. Before,
            # the drag made no dimension, so the dimension seemed to vanish until the line was clicked again.
            s.dragged = False
            s.swallow = True
            QtCore.QTimer.singleShot(0, lambda: setattr(s, "swallow", False))
            tool._press = None
            where = QtCore.QPoint(_global(event))      # the event is gone once this returns
            QtCore.QTimer.singleShot(0, lambda: _drag_place(tool, drag_pick[0], drag_pick[1], where))
            return True
        if press is not None and s.dragged and not _sketch_under(tool.sketch):
            s.dragged = False
            s.swallow = True
            QtCore.QTimer.singleShot(0, lambda: setattr(s, "swallow", False))
            tool._press = None
            s.tips.append(NO_DIMENSION)
            QtWidgets.QToolTip.showText(_global(event) + QtCore.QPoint(16, -36), NO_DIMENSION)
            return True                        # no pick, no dimension; the tool stays
        s.dragged = False
        return None
    return None


def _drag_place(tool, pick, at, where):
    """dragdim-1127: the pressed element is picked as a click at the press would pick it, the new dimension
    follows to where the button came up, and that counts as the placing click (Modify box)."""
    from . import toolbase as TB
    s = state(tool)
    try:
        if TB.active() is not tool:
            return
        tool.release(at, forced_pick=pick)
        if not tool.indexes:
            s.tips.append(NO_DIMENSION)
            QtWidgets.QToolTip.showText(where + QtCore.QPoint(16, -36), NO_DIMENSION)
            return
        tool._move()                    # the dimension (and its kind) follows the pointer, as on a plain move
        p, px = tool.pointer()
        if p is not None:
            tool.pixel = px
            tool.clear_hover()
            tool.finalize()             # the placing click
    except Exception as _fw_err:
        _fw_log("fwsketch/dimdrag.py:drag-place", _fw_err)


CENTRE_SNAP_PX = 8.0


def _centre_text(tool, index):
    ""

    sk = tool.sketch
    c = sk.Constraints[index]
    if c.Type not in ("Distance", "DistanceX", "DistanceY") or abs(c.LabelPosition) <= 1e-12:
        return False
    try:
        _p, px = tool.pointer()
    except Exception:
        px = 0.0
    if not px or not px > 0.0 or abs(c.LabelPosition) > CENTRE_SNAP_PX * px:
        return False
    sk.setLabelPosition(index, 0.0)
    return True


def _after_native(tool):
    """FreeCAD has dropped the dimension: one "Drag Constraint" step when it moved, and the tool
    goes on with nothing picked."""
    s = state(tool)
    s.native = s.ending = False
    doc = tool.sketch.Document
    clicked = None
    try:
        index, distance, position = s.label
        c = tool.sketch.Constraints[index]
        moved = abs(c.LabelDistance - distance) > 1e-9 or abs(c.LabelPosition - position) > 1e-9
        if moved:
            _centre_text(tool, index)
            doc.commitTransaction()
        else:
            _drop_step(doc)
            from .modifybox import DIMENSIONAL
            if c.Type in DIMENSIONAL:
                clicked = index
    except Exception:
        _drop_step(doc)
    try:
        Gui.Selection.clearSelection()
    except Exception as _fw_err:
        _fw_log("fwsketch/dimdrag.py:192", _fw_err)
    if clicked is not None:

        # box and the tool stays on (user report via Ati 11-27: placed dimensions did not take clicks)
        sketch = tool.sketch
        s.clicked.append(clicked)

        def edit():
            from . import dimedit, toolbase as TB
            if TB.active() is tool:
                dimedit.edit(sketch, clicked)
        QtCore.QTimer.singleShot(0, edit)
