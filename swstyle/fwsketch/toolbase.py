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

from .vec import sub, length
from . import inference as I
from . import snap as S
from . import relations as R
from .scene import Scene
from .cursor import ToolCursor, glyphs_for, HORIZONTAL, VERTICAL

SKETCHER_GROUP = "User parameter:BaseApp/Preferences/Mod/Sketcher"
GENERAL_GROUP = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"

_active = None


class _EditEnd:
    """fix237 (look audit AC5): Exit Sketch (or any end of the sketch edit) with a tool still on
    and no pointer move after it left the tool running, its hint and prompt on the status bar
    through the next features. The tool now ends with the edit. Gui observer (slotResetEdit only)."""

    def slotResetEdit(self, _vp):
        QtCore.QTimer.singleShot(0, self._check)

    def _check(self):
        tool = _active
        if tool is None:
            return
        try:
            if not tool._still_editing():
                tool.end()
        except Exception as _fw_err:
            _fw_log("fwsketch/toolbase.py: edit end", _fw_err)


_edit_watch = [None]


def _watch_edit():
    if _edit_watch[0] is None:
        try:
            watch = _EditEnd()
            Gui.addDocumentObserver(watch)
            _edit_watch[0] = watch
        except Exception as _fw_err:
            _fw_log("fwsketch/toolbase.py: edit watch", _fw_err)
            _edit_watch[0] = False


def active():
    """The running tool, or None."""
    return _active


# Undo or Redo under a running tool (Ctrl+Z while a chain is drawn): what the tool remembers of the
# sketch (the chain's last line, the entities picked so far) is gone or renumbered. Seen as: Ctrl+Z
# in a line chain, the next line got "Coincident" between its own two ends and the sketch no longer
# solved. An App document observer tells the tool (SketchTool.after_undo).
_step_watch = [None]


class _StepWatch:
    def slotUndoDocument(self, doc):
        _stepped(doc)

    def slotRedoDocument(self, doc):
        _stepped(doc)


def _stepped(doc):
    try:
        name = doc.Name
    except Exception:
        return
    QtCore.QTimer.singleShot(0, lambda: _prune_selection(name))     # once the step is in the sketch
    tool = _active
    if tool is None:
        return
    try:
        if tool.sketch.Document.Name != name:
            return
        tool.after_undo()
    except Exception as error:
        App.Console.PrintLog("FreeWorks sketch tool after Undo: %s\n" % error)


def _prune_selection(doc_name):
    ""


    try:
        try:
            _gdoc, sketch = edited_sketch()
        except RuntimeError:
            return
        if sketch.Document.Name != doc_name:
            return
        stale = False
        for ex in Gui.Selection.getSelectionEx(doc_name):
            if ex.Object is None or ex.Object.Name != sketch.Name:
                continue
            for sub in ex.SubElementNames:
                if sub.startswith("Edge") and sub[4:].isdigit():
                    stale = stale or int(sub[4:]) > sketch.GeometryCount
                elif sub.startswith("Vertex") and sub[6:].isdigit():
                    stale = stale or sketch.getGeoVertexIndex(int(sub[6:]) - 1)[0] == -2000
                elif sub.startswith("Constraint") and sub[10:].isdigit():
                    stale = stale or int(sub[10:]) > sketch.ConstraintCount
                elif sub.startswith("ExternalEdge") and sub[12:].isdigit():
                    stale = stale or int(sub[12:]) > len(sketch.ExternalGeo) - 2
        if stale:
            Gui.Selection.clearSelection()
    except Exception as error:
        App.Console.PrintLog("FreeWorks sketch selection after Undo: %s\n" % error)


def _watch_steps():
    if _step_watch[0] is None:
        try:
            watch = _StepWatch()
            App.addDocumentObserver(watch)
            _step_watch[0] = watch
        except Exception as error:
            App.Console.PrintLog("FreeWorks sketch tools: no Undo watch: %s\n" % error)
            _step_watch[0] = False


# Undo or Redo under a running tool (Ctrl+Z while a chain is drawn): what the tool remembers of the
# sketch (the chain's last line, the entities picked so far) is gone or renumbered. Seen as: Ctrl+Z
# in a line chain, the next line got "Coincident" between its own two ends and the sketch no longer
# solved. An App document observer tells the tool (SketchTool.after_undo).
_step_watch = [None]


class _StepWatch:
    def slotUndoDocument(self, doc):
        _stepped(doc)

    def slotRedoDocument(self, doc):
        _stepped(doc)


def _stepped(doc):
    try:
        name = doc.Name
    except Exception:
        return
    QtCore.QTimer.singleShot(0, lambda: _prune_selection(name))     # once the step is in the sketch
    tool = _active
    if tool is None:
        return
    try:
        if tool.sketch.Document.Name != name:
            return
        tool.after_undo()
    except Exception as error:
        App.Console.PrintLog("FreeCAD sketch tool after Undo: %s\n" % error)


def _prune_selection(doc_name):
    ""


    try:
        try:
            _gdoc, sketch = edited_sketch()
        except RuntimeError:
            return
        if sketch.Document.Name != doc_name:
            return
        stale = False
        for ex in Gui.Selection.getSelectionEx(doc_name):
            if ex.Object is None or ex.Object.Name != sketch.Name:
                continue
            for sub in ex.SubElementNames:
                if sub.startswith("Edge") and sub[4:].isdigit():
                    stale = stale or int(sub[4:]) > sketch.GeometryCount
                elif sub.startswith("Vertex") and sub[6:].isdigit():
                    stale = stale or sketch.getGeoVertexIndex(int(sub[6:]) - 1)[0] == -2000
                elif sub.startswith("Constraint") and sub[10:].isdigit():
                    stale = stale or int(sub[10:]) > sketch.ConstraintCount
                elif sub.startswith("ExternalEdge") and sub[12:].isdigit():
                    stale = stale or int(sub[12:]) > len(sketch.ExternalGeo) - 2
        if stale:
            Gui.Selection.clearSelection()
    except Exception as error:
        App.Console.PrintLog("FreeCAD sketch selection after Undo: %s\n" % error)


def _watch_steps():
    if _step_watch[0] is None:
        try:
            watch = _StepWatch()
            App.addDocumentObserver(watch)
            _step_watch[0] = watch
        except Exception as error:
            App.Console.PrintLog("FreeCAD sketch tools: no Undo watch: %s\n" % error)
            _step_watch[0] = False


def other_buttons(event):
    """True when a button other than the left one is held during this mouse event (the view is
    being panned or turned). Integers, not Qt's flag objects: on Windows' PySide the flag
    arithmetic read a middle-button drag as no button (stock runs 2-4)."""
    try:
        held = event.buttons()
        value = getattr(held, "value", None)      # PySide6 enum flags carry .value; int() may not take them
        if value is None:
            value = int(held)
        return bool(int(value) & ~1)              # Qt.LeftButton == 1
    except Exception:
        try:
            return bool(event.buttons() & ~QtCore.Qt.LeftButton)
        except Exception:
            return False


def preselected_subs(sketch):
    """The sub-elements of sketch under the pointer (FreeCAD's preselection), as "Edge1", "Vertex3"...
    A sketch edited through its Body (the Sketch button on a picked plane) is preselected as the Body
    with "Sketch.Edge1": both forms count."""
    try:
        pre = Gui.Selection.getPreselection()
        if pre.DocumentName != sketch.Document.Name:
            return []
        out = []
        for sub in pre.SubElementNames:
            # "Edge1", "Sketch.Edge1", or with a mapped name "Sketch.;g2;SKT.Edge2"
            parts = sub.split(".")
            objects = [x for x in parts[:-1] if x and not x.startswith(";")]
            owner = objects[-1] if objects else pre.ObjectName
            if owner == sketch.Name and parts[-1]:
                out.append(parts[-1])
        return out
    except Exception:
        return []


def prune_unused_references(sketch, before):
    ""


    try:
        if len(sketch.ExternalGeo) > before:
            from . import references
            references.prune(sketch)
    except Exception as _fw_err:
        _fw_log("fwsketch/toolbase.py: prune references", _fw_err)


def automatic_relations():
    ""

    try:
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc is not None else None
        if vp is not None and hasattr(vp, "Autoconstraints"):
            return bool(vp.Autoconstraints)
    except Exception as _fw_err:
        _fw_log("fwsketch/toolbase.py:106", _fw_err)
    return param_bool(GENERAL_GROUP, "AutoConstraints", True)


def _digit(key):
    if QtCore.Qt.Key_0 <= key <= QtCore.Qt.Key_9:
        return chr(ord("0") + key - QtCore.Qt.Key_0)
    if key in (QtCore.Qt.Key_Period, QtCore.Qt.Key_Comma):
        return "."
    return None


class ValuesBox(QtCore.QObject):
    ""

    accepted = QtCore.Signal(object)
    cancelled = QtCore.Signal()

    def __init__(self, parent, labels, first):
        super().__init__(parent)
        self.frame = QtWidgets.QFrame(parent)
        self.frame.setObjectName("FreeWorksValuesBox")
        lay = QtWidgets.QHBoxLayout(self.frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.edits = []
        for i, label in enumerate(labels):
            e = QtWidgets.QLineEdit(self.frame)
            e.setObjectName("FreeWorksValue%d" % (i + 1))
            e.setPlaceholderText(label)
            e.setToolTip(label)
            e.setFixedWidth(80)
            e.installEventFilter(self)
            e.returnPressed.connect(self._accept)
            lay.addWidget(e)
            self.edits.append(e)
        self.edits[0].setText(first)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        try:
            if event.type() == QtCore.QEvent.KeyPress:
                if event.key() == QtCore.Qt.Key_Escape:
                    self.cancelled.emit()
                    return True
                if event.key() in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab) and obj in self.edits:
                    k = self.edits.index(obj)
                    nxt = self.edits[(k + (1 if event.key() == QtCore.Qt.Key_Tab else -1)) % len(self.edits)]
                    nxt.setFocus()
                    nxt.selectAll()
                    return True
        except Exception:
            return False
        return False

    def _accept(self):
        values = []
        for e in self.edits:
            text = e.text().strip().replace(",", ".")
            if not text:
                values.append(None)
                continue
            angle = "Angle" in (e.placeholderText() or "")
            try:
                if angle:
                    value = float(App.Units.Quantity(text.replace("°", " deg")).getValueAs("deg")) \
                        if any(ch.isalpha() or ch == "°" for ch in text) else float(text)
                elif any(ch.isalpha() or ch == '"' for ch in text):
                    value = float(App.Units.Quantity(text).getValueAs("mm"))
                else:
                    value = float(text) * length_unit()[0]   # a bare number: the document's unit
            except Exception:
                return
            values.append(value)
        self.accepted.emit(values)

    def move(self, x, y):
        self.frame.move(x, y)

    def show(self):
        self.frame.adjustSize()
        self.frame.show()
        self.frame.raise_()
        self.edits[0].setFocus()
        self.edits[0].end(False)

    def close(self):
        self.frame.hide()
        self.frame.deleteLater()


def toward(origin, cur, dist):
    """The point dist from origin in the direction of cur (along x when cur is origin)."""
    dx, dy = (cur[0] - origin[0], cur[1] - origin[1]) if cur is not None else (0.0, 0.0)
    n = math.hypot(dx, dy)
    ux, uy = (dx / n, dy / n) if n > 1e-12 else (1.0, 0.0)
    return (origin[0] + ux * dist, origin[1] + uy * dist)


def side_of(value):
    return -1.0 if value < 0 else 1.0


def lines_of(sketch, geos):
    """The (geo, horizontal-ish) of the solid lines among geos."""
    out = []
    for g in geos:
        try:
            geo = sketch.Geometry[g]
            if type(geo).__name__ != "LineSegment" or sketch.getConstruction(g):
                continue
            d = geo.EndPoint - geo.StartPoint
            out.append((g, abs(d.x) >= abs(d.y)))
        except Exception:
            continue
    return out


def param_bool(group, name, default):
    try:
        return App.ParamGet(group).GetBool(name, default)
    except Exception:
        return default


def continuous_mode():
    return param_bool(SKETCHER_GROUP, "ContinuousCreationMode", True)


def escape_ends_tool():
    return param_bool(SKETCHER_GROUP, "EscapeEndsTool", True)


def click_drag_drawing():
    return param_bool(SKETCHER_GROUP, "ClickDragDrawing", True)


def show_cursor_coords():
    return param_bool(GENERAL_GROUP, "ShowCursorCoords", True)


def length_unit():
    ""


    try:
        _text, factor, unit = App.Units.schemaTranslate(App.Units.Quantity(25.4, App.Units.Length), App.Units.getSchema())
        if factor > 0 and unit:
            return float(factor), unit
    except Exception as _fw_err:
        _fw_log("fwsketch/toolbase.py:257", _fw_err)
    return 1.0, "mm"


def _decimals():
    try:
        return max(0, min(8, App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("Decimals", 2)))
    except Exception:
        return 2


def _trim(text):
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def fmt_length(value, decimals=None):
    ""

    factor, _unit = length_unit()
    return _trim("%.*f" % (_decimals() if decimals is None else decimals, value / factor))


def fmt_angle(degrees, decimals=None):
    return _trim("%.*f" % (_decimals() if decimals is None else decimals, degrees)) + "°"


class ViewMath:
    """The view of the edited sketch: device pixels to sketch coordinates and back."""

    def setup_view(self, gdoc, sketch):
        self.gdoc, self.sketch = gdoc, sketch
        self.vp = gdoc.getObject(sketch.Name)
        self.view = gdoc.ActiveView
        self.quarter = self.view.graphicsView()
        self.viewport = self.quarter.viewport()
        self.matrix = gdoc.EditingTransform
        self.to_local = self.matrix.inverse()
        self.ratio = self.viewport.devicePixelRatioF()

    def _grid_size(self):
        try:
            return float(self.vp.GridSize)
        except Exception:
            return 0.0

    def plane_point(self, x, y):
        """Sketch coordinates where the view ray through device pixel (x, y) meets the sketch."""
        p = self.view.getPoint(int(x), int(y))
        d = self.view.getViewDirection()
        o = self.matrix.multVec(App.Vector(0, 0, 0))
        n = self.matrix.multVec(App.Vector(0, 0, 1)) - o
        denom = d.dot(n)
        if abs(denom) < 1e-12:
            return None
        t = (o - p).dot(n) / denom
        local = self.to_local.multVec(p + d * t)
        return (local.x, local.y)

    def pixel_size(self, x, y):
        """Sketch units per logical pixel around device pixel (x, y)."""
        a, b = self.plane_point(x, y), self.plane_point(x + 10, y)
        if a is None or b is None:
            return 0.0
        return length(sub(b, a)) / 10.0 * self.ratio

    def _view_box(self):
        w, h = self.view.getSize()
        corners = [self.plane_point(0, 0), self.plane_point(w, 0), self.plane_point(0, h), self.plane_point(w, h)]
        if any(c is None for c in corners):
            return None
        xs, ys = [c[0] for c in corners], [c[1] for c in corners]
        margin = 0.1 * max(max(xs) - min(xs), max(ys) - min(ys))
        return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)

    def pointer(self):
        """(sketch point under the pointer or None, sketch units per pixel there)."""
        x, y = self.view.getCursorPos()
        return self.plane_point(x, y), self.pixel_size(x, y)


class SketchTool(QtCore.QObject, ViewMath):
    """A tool on the sketch being edited in gdoc's active view."""

    # state names shared by the tools
    FIRST, SECOND, THIRD = 0, 1, 2

    def __init__(self, gdoc, sketch, construction=False):
        super().__init__()
        self.setup_view(gdoc, sketch)
        self.construction = construction  # the geometry is drawn as construction (Centerline)
        self.snapper = S.Snapper(sketch, grid_size=self._grid_size, view_box=self._view_box)
        self.scene = None
        self.cursor = None
        self.tail = None
        self.decision = None         # of the last move
        self.suggestions = []        # of the last move
        self.created = []            # geo ids this tool added
        self.placements = []         # the geo ids of each placement (paramedit: Parameters boxes)
        self.log = []                # (winner, position, suggestion keys, crossing) per move, for tests
        self.state = self.FIRST
        self._press = None           # (global QPoint, was first state) of the left press being held
        self._dragged = False
        self._other_down = False     # a middle (or other) button is held: the view navigates
        self._hinted = None          # the state the status-bar hints were last shown for
        self._app = QtWidgets.QApplication.instance()

    # --- for subclasses --------------------------------------------------------------------
    def icon_name(self):
        return "Sketcher_Pointer_Create_Lineset"

    def icon_badge(self):
        """A 16 px icon drawn on the crosshair instead of a pointer icon of its own."""
        return None

    def is_first_state(self):
        return self.state == self.FIRST

    def starts_click_drag(self):
        """The next press places the tool's first point: a drag from it places the second."""
        return self.is_first_state()

    def on_move(self, d):
        """Update the preview for the snapped decision d; return the suggestions to show."""
        return []

    def on_click(self, d):
        pass

    def after_click_drag(self):
        pass

    def on_key(self, key):
        """A key while the pointer is over the view; True when the tool used it."""
        return False

    def cancel_current(self):
        """A right click while something is being drawn: drop it, keep the tool."""
        self.reset()

    def reset(self):
        self.state = self.FIRST
        self.suggestions = []
        self.snapper.set_reference(None)
        if self.scene is not None:
            self.scene.clear()

    def after_undo(self):
        ""


        self._press = None
        self._dragged = False
        try:
            self._close_values_box()
        except Exception:
            pass
        self.reset()
        self._count_after = None
        self.snapper.sketch_changed()
        self._hinted = None
        self.show_hints()

    def title(self):
        return "Sketch tool"

    # --- life --------------------------------------------------------------------------------
    def begin(self):
        global _active
        if _active is not None:
            _active.end()
        else:
            # a stock Sketcher tool still running (its own toolbar button, continuous mode): end it

            # later would otherwise end this new tool at once (fix158)
            try:
                from .. import nativepms
                nativepms._end_tool()
            except Exception as _fw_err:
                _fw_log("fwsketch/toolbase.py:421", _fw_err)
        _active = self
        _watch_steps()
        _watch_edit()
        self.scene = Scene(self.view, self.matrix, self.ratio)
        self.cursor = ToolCursor(self.icon_name(), self.ratio, self.icon_badge())
        from .cursor import Tail
        self.tail = Tail(self.viewport, self.cursor)
        for w in (self.viewport, self.quarter):
            w.installEventFilter(self)
        from . import appevents
        appevents.listen(self, (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease, QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove, QtCore.QEvent.ShortcutOverride))   # one application filter (fix65)
        self.viewport.setCursor(self.cursor.cursor())
        try:
            self.quarter.setFocus()
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/toolbase.py:435", _fw_err)
        self.reset()
        self._hinted = None
        self.show_hints()

    def hint_state(self):
        """The state the status-bar hints are for (hints.HINTS[title][state])."""
        return self.state

    def show_hints(self):
        state = self.hint_state()
        if state == self._hinted:
            return
        self._hinted = state
        try:
            from . import hints
            hints.show(self.title(), state)
        except Exception as _fw_err:
            _fw_log("fwsketch/toolbase.py:453", _fw_err)

    def end(self):
        global _active
        for w in (self.viewport, self.quarter):
            try:
                w.removeEventFilter(self)
            except RuntimeError as _fw_err:
                _fw_log("fwsketch/toolbase.py:461", _fw_err)
        from . import appevents
        appevents.stop(self)
        try:
            from . import hints
            hints.hide()
        except Exception as _fw_err:
            _fw_log("fwsketch/toolbase.py:468", _fw_err)
        try:
            self.viewport.unsetCursor()
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/toolbase.py:472", _fw_err)
        if getattr(self, "tail", None) is not None:
            self.tail.close()
            self.tail = None
        if self.scene is not None:
            self.scene.remove()
            self.scene = None
        self.snapper.reset()
        if _active is self:
            _active = None

    def finish_or_continue(self):
        """The element is done (a chain ended, a shape placed): stay for the next one in
        continuous mode, else end the tool."""
        if continuous_mode():
            self.reset()
            self._move()
        else:
            self.end()

    # --- events ----------------------------------------------------------------------------------
    TOOL_KEYS = (QtCore.Qt.Key_Escape, QtCore.Qt.Key_A, QtCore.Qt.Key_M)

    def claims_key(self, key):
        """Keys the tool takes ahead of FreeCAD's shortcuts while the pointer is over the view."""
        if _digit(key) is not None and self._numeric_spec_now() is not None:
            return True     # a typed number goes to the on-screen numeric input (fix65)
        return key in self.TOOL_KEYS


    def numeric_spec(self):
        """None, or (labels, place) for the step being drawn: place(values) gives the sketch point
        the typed values stand for (a value left empty: None, the pointer's)."""
        return None

    def _numeric_spec_now(self):
        if getattr(self, "numeric", None) is not None or self.decision is None:
            return None
        if not param_bool(GENERAL_GROUP, "OnScreenNumericInput", False):
            return None
        try:
            return self.numeric_spec()
        except Exception:
            return None

    def _open_values_box(self, first):
        spec = self._numeric_spec_now()
        if spec is None:
            return False
        labels, place, keys = (tuple(spec) + (None,))[:3]
        box = ValuesBox(self.viewport, labels, first)
        box.accepted.connect(lambda values, place=place, keys=keys: self._typed_values(place, values, keys))
        box.cancelled.connect(self._close_values_box)
        pos = self.viewport.mapFromGlobal(QtGui.QCursor.pos())
        box.move(pos.x() + 18, pos.y() + 18)
        box.show()
        self.numeric = box
        return True

    def _close_values_box(self):
        box, self.numeric = getattr(self, "numeric", None), None
        if box is not None:
            try:
                box.close()
            except RuntimeError as _fw_err:
                _fw_log("fwsketch/toolbase.py:537", _fw_err)
        try:
            self.quarter.setFocus()
        except (RuntimeError, AttributeError) as _fw_err:
            _fw_log("fwsketch/toolbase.py:541", _fw_err)

    def after_typed_move(self, values):
        """After the preview follows a typed point: a tool fixes what a point cannot say (the
        sweep of an arc typed past 180 degrees)."""

    def typed_dimensions(self, geos, typed):
        ""

        return []

    def _typed_values(self, place, values, keys=None):
        self._close_values_box()
        try:
            pos = place(values)
        except Exception:
            pos = None
        if pos is None:
            return
        if self.state == self.FIRST or not hasattr(self, "typed"):
            self.typed = {}
        for k, v in zip(keys or (), values):
            if v is not None:
                self.typed[k] = v
        self._entities_gone()
        S.FORCED[0] += 1
        try:
            self.suggestions = list(self.on_move(pos, self.pixel) or [])
            self.after_typed_move(values)
            d = self.decision
            if d is not None:
                d.position = pos
                self.on_click(d)
        finally:
            S.FORCED[0] -= 1
        self._move()

    def _add_typed_dimensions(self, geos):
        typed, self.typed = getattr(self, "typed", None) or {}, {}
        if not typed or not geos or not param_bool(GENERAL_GROUP, "NumericInputAddsDimension", True):
            return
        for c in self.typed_dimensions(list(geos), typed) or []:
            try:
                self.sketch.addConstraint(c)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: typed dimension: %s\n" % error)

    def _text_has_focus(self):
        w = QtWidgets.QApplication.focusWidget()
        return isinstance(w, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
                              QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox))

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide on Windows can hand a filter a stale wrapper (a QWidgetItem) instead
        # an exception out of a Qt override takes FreeCAD down: keep them in here
        try:
            return self._filter(obj, event)
        except ReferenceError:
            # the sketch (or its document) is gone under the running tool: end it quietly
            # (tester E12-17: the Circle tool's moves kept failing on a deleted sketch)
            try:
                self.end()
            except Exception as _fw_err:
                _fw_log("fwsketch/toolbase.py:604", _fw_err)
            return False
        except Exception:
            import traceback
            App.Console.PrintError("FreeCAD sketch tool: %s" % traceback.format_exc())
            return False

    def _filter(self, obj, event):
        t = event.type()
        if obj is not self.viewport and obj is not self.quarter:
            # the application filter: keys for the tool reach it from anywhere in the window while
            # the pointer is over the view, ahead of FreeCAD's shortcuts on the same letters
            # (patch 05 ShortcutListener); everything else is not ours
            if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease) and isinstance(event, QtGui.QKeyEvent) \
                    and event.key() in (QtCore.Qt.Key_Control, QtCore.Qt.Key_Shift) and not event.isAutoRepeat():
                # Ctrl or Shift with the focus outside the view (the PC, 11-08 step 4): the hover

                QtCore.QTimer.singleShot(0, self._move)
                return False
            if t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress) and isinstance(event, QtGui.QKeyEvent) \
                    and not self._text_has_focus():
                try:
                    over = self.viewport.underMouse()
                except RuntimeError:
                    return False
                if over and self.claims_key(event.key()):
                    if t == QtCore.QEvent.ShortcutOverride:
                        event.accept()
                        return True
                    return self._key(event.key())
            return False
        if t == QtCore.QEvent.ShortcutOverride and self.claims_key(event.key()):
            event.accept()
            return True
        if t == QtCore.QEvent.KeyPress:
            if event.key() in (QtCore.Qt.Key_Control, QtCore.Qt.Key_Shift):
                self._move()  # replay the hover with the new modifier
                return False
            return self._key(event.key())
        if t == QtCore.QEvent.KeyRelease and event.key() in (QtCore.Qt.Key_Control, QtCore.Qt.Key_Shift):
            self._move()
            return False
        if t == QtCore.QEvent.MouseMove:
            if self._other_down or other_buttons(event):
                return False  # panning or turning the view: FreeCAD's navigation handles it
            if self._press is not None and not self._dragged:
                start = self._press[0]
                now = self._global(event)
                if (now - start).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                    self._dragged = True
            self._move()
            return True
        if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick):
            if t == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.LeftButton \
                    and self.on_double_click():
                self._press = None
                return True
            if event.button() == QtCore.Qt.LeftButton:
                self._left_press(event)
                return True
            if event.button() == QtCore.Qt.RightButton:
                return True
            self._other_down = True   # middle button (or another): the view's own navigation
            return False
        if t == QtCore.QEvent.MouseButtonRelease:
            if event.button() == QtCore.Qt.LeftButton:
                self._left_release()
                return True
            if event.button() == QtCore.Qt.RightButton:
                self._context_click()
                return True
            self._other_down = False
            return False
        return False

    def on_double_click(self):
        ""
        return False

    @staticmethod
    def _global(event):
        try:
            return event.globalPosition().toPoint()
        except AttributeError:
            return event.globalPos()

    def _key(self, key):
        typed = _digit(key)
        if typed is not None and self._numeric_spec_now() is not None:
            return self._open_values_box(typed)
        if key == QtCore.Qt.Key_Escape:
            self.typed = {}
            if escape_ends_tool():
                self.end()
            else:
                self._right_click()
            return True
        return bool(self.on_key(key))

    def _entities_gone(self):
        """Delete (the key, the menu) took entities away while the tool is up: the chain's last
        entity and the picks the tool remembers may be gone or renumbered (monkey 11-19: the next
        line got a malformed Coincident). As after an Undo, the tool starts again from its first point."""
        seen = getattr(self, "_count_after", None)
        try:
            gone = seen is not None and self.sketch.GeometryCount < seen
        except Exception:
            gone = False
        if gone:
            self.after_undo()

    def _left_press(self, event):
        self._entities_gone()
        first = self.starts_click_drag() and click_drag_drawing()
        self._press = (self._global(event), first)
        self._dragged = False
        self._move()
        if self.decision is not None:
            self.on_click(self.decision)
            if _active is self:
                self._move()

    def _left_release(self):
        press, self._press = self._press, None
        if press is None or _active is not self:
            return
        if press[1] and self._dragged and not self.starts_click_drag():
            # dragged from the first point: the release places the next one, as a click would
            self._move()
            if self.decision is not None:
                self.on_click(self.decision)
                if _active is self:
                    self.after_click_drag()
                    if _active is self:
                        self._move()
        self._dragged = False

    def _context_click(self):
        ""

        try:
            from swstyle import rcmenus
            if rcmenus.tool_menu(self):
                self._press = None
                return
        except ImportError:
            pass
        except Exception as e:
            App.Console.PrintError("FreeCAD right-click menu: %s\n" % e)
        self._right_click()

    def _right_click(self):
        self._press = None
        if self.is_first_state():
            self.end()
        else:
            self.cancel_current()
            if _active is self:
                self._move()

    # --- moves -------------------------------------------------------------------------------------
    def _move(self):
        try:
            self._move_now()
        except ReferenceError:
            try:
                self.end()      # the sketch is gone (deleted, its document closed)
            except Exception as _fw_err:
                _fw_log("fwsketch/toolbase.py:759", _fw_err)

    def _still_editing(self):
        """The tool's sketch is still the one in edit (it can be deleted, or the edit closed, under
        a running tool: tester E12-17)."""
        try:
            vp = self.gdoc.getInEdit()
            obj = getattr(vp, "Object", None) if vp is not None else None
            return obj is not None and obj.Name == self.sketch.Name and obj.Document.Name == self.sketch.Document.Name
        except Exception:
            return False

    def _move_now(self):
        if _active is not self or self.scene is None:
            return
        if not self._still_editing():
            self.end()
            return
        p, px = self.pointer()
        if p is None:
            return
        self.pixel = px
        self.suggestions = list(self.on_move(p, px) or [])
        self.show_hints()
        d = self.decision
        if d is None:
            return
        self.log.append((d.winner, d.position, [s.key() for s in self.suggestions], self.snapper.last_guides.crossing))
        self._draw_common(d)

    def snap(self, p, px, allow_point=True, allow_edge=True, allow_angle=True, allow_grid=True):
        """Snap the pointer and remember the decision."""
        self.decision = self.snapper.snap(p, px, allow_point, allow_edge, allow_angle, allow_grid)
        return self.decision

    def seek(self, position, direction, target=R.VERTEX):
        return R.seek(self.snapper, position, direction, target)

    def _draw_common(self, d):
        sc = self.scene
        cand, rel, snaps = self.snapper.guide_lines(d)
        sc.lines("candidates", cand)
        sc.lines("relations", rel)
        sc.lines("snaps", snaps)
        hints, act = self.snapper.markers(d)
        sc.points("hints", hints)
        sc.points("quadrants", getattr(self.snapper, "quadrant_marks", []))
        sc.points("active", act)
        sc.lines("hover", self._hovered_curves(d))
        glyphs = glyphs_for(self.suggestions) if not S.inference_suppressed() else []
        for g in getattr(self, "preview_glyphs", ()):     # what the segment itself is (a tangent arc's Tangent)
            if g not in glyphs:
                glyphs.insert(0, g)
        white = []
        h, v = self.snapper.last_alignments_at(d.position)
        if h:
            white.append(HORIZONTAL)
        if v:
            white.append(VERTICAL)
        try:
            self.viewport.setCursor(self.cursor.cursor())
            if getattr(self, "tail", None) is not None:
                self.tail.show(glyphs, white)
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/toolbase.py:822", _fw_err)

    ON_CURVE = (S.SKETCH_CURVE, S.MIDPOINT, S.QUADRANT, S.TANGENT_POINT, S.NORMAL_POINT, S.INTERSECTION)

    def _hovered_curves(self, d):
        ""

        if d is None or d.winner not in self.ON_CURVE or S.inference_suppressed():
            return []
        out = []
        for geo in (d.geo, getattr(d, "geo2", I.GEO_UNDEF) if d.winner == S.INTERSECTION else I.GEO_UNDEF):
            if geo in (None, I.GEO_UNDEF):
                continue
            try:
                g = self.snapper.geometry(geo)
                if g is None:
                    continue
                from .dragwatch import outline
                pts = outline(g)
                if not pts and hasattr(g, "discretize"):
                    pts = [(q.x, q.y) for q in g.discretize(48)]
                if pts:
                    out.append(pts)
            except Exception:
                continue
        return out

    def readout(self, position, text):
        if self.scene is not None:
            self.scene.label(position, "  " + text if text and show_cursor_coords() else "")

    def preview(self, polylines, construction=(), points=()):
        if self.scene is not None:
            polylines, construction, points = list(polylines), list(construction), list(points)
            mirrored = _dynamic_mirror_preview(self.sketch, polylines, construction, points)
            if mirrored is not None:
                polylines, construction, points = mirrored
            self.scene.lines("preview", polylines)
            self.scene.lines("construction", construction)
            self.scene.points("points", points)

    # --- writing ---------------------------------------------------------------------------------------
    def transaction(self, name, body):
        """Run body() inside one undo step of the document; recompute after."""
        doc = self.sketch.Document
        doc.openTransaction(name)
        before = len(self.created)
        R.still_solved(self.sketch)   # forget an older note
        try:
            result = body()
            if getattr(self, "typed", None):
                self._add_typed_dimensions(self.created[before:])      # in the same undo step
            doc.commitTransaction()
            if len(self.created) > before:
                self.placements.append(list(self.created[before:]))
        except Exception:
            doc.abortTransaction()
            raise
        if App.ParamGet(SKETCHER_GROUP).GetBool("AutoRecompute", False):
            doc.recompute()
        else:
            # Automatic Solve off (Sketcher's AutoRecompute, FreeCAD's default): the sketch is
            # solved and the part waits for Rebuild or the sketch's exit, as in stock FreeCAD's
            # tools. A document recompute per tool action cost 0.5 s in a 960-relation sketch
            # (review 1119 perf3). Not twice when the body's last step solved it already
            if not R.still_solved(self.sketch):
                self.sketch.solve()
        self.snapper.sketch_changed()
        try:
            self._count_after = self.sketch.GeometryCount
        except Exception:
            self._count_after = None
        return result

    def add_geometry(self, geometry, construction=None):
        if construction is None:
            construction = self.construction
        geo = self.sketch.addGeometry(geometry, construction)
        self.created.append(geo)
        return geo

    def add_constraint(self, constraint):
        return self.sketch.addConstraint(constraint)

    def add_relations(self, suggestions, geo, pos):
        """The automatic relations of suggestions on point pos of geo (createAutoConstraints)."""
        if not automatic_relations():
            return 0
        pending = []
        e0 = len(self.sketch.ExternalGeo)
        R.generate(pending, R.resolve_model(self.snapper, list(suggestions)), geo, pos, self.snapper.geometry)
        n0 = len(self.sketch.Constraints)
        added = R.add_without_redundancy(self.sketch, pending, avoid_redundant=True)
        try:

            from . import helpers
            helpers.lock_new_arc_midpoints(self.sketch, suggestions, geo, pos, n0)
        except Exception as _fw_err:
            _fw_log("fwsketch/toolbase.py: arc midpoint", _fw_err)
        prune_unused_references(self.sketch, e0)
        return added

    def select_new(self, geos):
        """Keep the new geometry picked (SelectNewRectangle, package 29; stock default off)."""
        if not param_bool(GENERAL_GROUP, "SelectNewRectangle", False):
            return
        try:
            Gui.Selection.clearSelection()
            for geo in geos:
                Gui.Selection.addSelection(self.sketch.Document.Name, self.sketch.Name, "Edge%d" % (geo + 1))
        except Exception as _fw_err:
            _fw_log("fwsketch/toolbase.py:910", _fw_err)


def edited_sketch():
    """(gdoc, sketch) of the sketch being edited, or raises."""
    gdoc = Gui.ActiveDocument
    vp = gdoc.getInEdit() if gdoc else None
    if getattr(vp, "Object", None) is None or not vp.Object.isDerivedFrom("Sketcher::SketchObject"):
        raise RuntimeError("open a sketch first")
    return gdoc, vp.Object


def _dynamic_mirror_preview(sketch, polylines, construction, points):
    ""



    try:
        from .. import dimcommands as DC
        dm = DC._dynamic_mirror
        if dm is None or not dm.active() or dm.sketch is not sketch:
            return None
        a, b = DC._axis_ends(sketch, dm.axis)
        a, b = App.Vector(a.x, a.y, 0), App.Vector(b.x, b.y, 0)
        if (b - a).Length < 1e-9:
            return None
    except Exception:
        return None

    def m(p):
        q = DC._mirror(App.Vector(p[0], p[1], 0), a, b)
        return (q.x, q.y)
    from .dragwatch import outline
    made, made_c = [], []
    try:
        for g in range(dm.count, len(sketch.Geometry)):
            if g == dm.axis:
                continue
            pts = outline(sketch.Geometry[g])
            if pts:
                (made_c if sketch.getConstruction(g) else made).append(pts)
    except Exception as _fw_err:
        _fw_log("fwsketch/toolbase.py:952", _fw_err)
    lines = polylines + [[m(p) for p in poly] for poly in polylines + made]
    cons = construction + [[m(p) for p in poly] for poly in list(construction) + made_c]
    return lines, cons, points + [m(p) for p in points]
