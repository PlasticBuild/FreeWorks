# SPDX-License-Identifier: LGPL-2.1-or-later
""













from . import editobj

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

from . import paths

DONE = "swstyle_pmkeys"
PICK_BUTTON = "buttonRefSel"
ALL_EDGES = "checkBoxUseAllEdges"
PICKED_DRESSUPS = {"PartDesign::Fillet": "Select items to fillet",
                   "PartDesign::Chamfer": "Select items to chamfer"}
REVOLVES = ("PartDesign::Revolution", "PartDesign::Groove")
NO_AXIS = "Select an axis of revolution"
WAITING = "Select reference"     # FreeCAD's axis list while it waits for a pick
DEPTHS = {"PartDesign::Pad": "LastExtrudeDepth", "PartDesign::Pocket": "LastCutDepth"}
_new = set()        # (document, name) of Extrudes and Cuts made since the panel last looked
_keepers = {}       # id(view) -> PickKeeper


def _editing():
    try:
        edit = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
        return editobj.of(edit) if edit is not None else None
    except Exception as _fw_err:
        _fw_log("pmkeys.py:53", _fw_err)
        return None


def _alive(widget):
    try:
        widget.objectName()
        return True
    except RuntimeError as _fw_err:
        _fw_log("pmkeys.py:62", _fw_err)
        return False


def _on_change(widget, slot):
    """Calls slot after the panel's own handler of a value change."""
    name = widget.metaObject().className()
    if isinstance(widget, QtWidgets.QComboBox):
        widget.currentIndexChanged.connect(slot)
    elif isinstance(widget, QtWidgets.QAbstractButton):
        widget.toggled.connect(slot)
    elif "QuantitySpinBox" in name:
        if not QtCore.QObject.connect(widget, QtCore.SIGNAL("valueChanged(double)"), slot):
            widget.editingFinished.connect(slot)
    elif isinstance(widget, QtWidgets.QDoubleSpinBox) or isinstance(widget, QtWidgets.QSpinBox):
        widget.valueChanged.connect(slot)


class PickKeeper(QtCore.QObject):
    """Turns picking back on after FreeCAD turned it off for a value change."""

    def __init__(self, view, button):
        super().__init__(view)
        self.button = button
        self.armed = button.isChecked()
        self.user = False
        button.toggled.connect(self._toggled)
        button.installEventFilter(self)

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        kind = event.type()
        if kind == QtCore.QEvent.MouseButtonRelease or (
                kind == QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Space, QtCore.Qt.Key_Return)):
            self.user = True
            QtCore.QTimer.singleShot(0, self._user_done)
        return False

    def _user_done(self):
        self.user = False

    def _toggled(self, on):
        if on or self.user:
            self.armed = on

    def rearm(self, *args):
        button = self.button
        if self.armed and _alive(button) and button.isEnabled() and not button.isChecked():
            button.setChecked(True)   # FreeCAD's own toggled handler starts picking again


def nothing_picked():
    """The hint to show when the open Fillet or Chamfer has no items, else None."""
    obj = _editing()
    hint = PICKED_DRESSUPS.get(obj.TypeId) if obj is not None else None
    if hint is None or getattr(obj, "UseAllEdges", False):
        return None
    base = obj.Base
    return hint if base is None or not base[1] else None


def _axis_waiting():
    for combo in Gui.getMainWindow().findChildren(QtWidgets.QComboBox, "axis"):
        if _alive(combo) and combo.currentText().endswith(("\u2026", "...")):
            return True
    return False


def no_axis():
    """The hint to show when the open Revolve has no usable axis, else None."""
    obj = _editing()
    if obj is None or obj.TypeId not in REVOLVES:
        return None
    if _axis_waiting():
        return NO_AXIS
    try:
        if "Touched" in obj.State:
            obj.Document.recompute()
        if obj.isValid():
            return None
        return obj.getStatusString() or NO_AXIS
    except Exception as _fw_err:
        _fw_log("pmkeys.py:145", _fw_err)
        return None


PIPES = ("PartDesign::AdditivePipe", "PartDesign::SubtractivePipe")
LOFTS = ("PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft")


def half_specified():
    """The hint when the open Sweep or Loft still lacks what FreeCAD cannot build without (OK
    then shows FreeCAD's modal "Input error", and on the PC crashed it), else None (pkg99)."""
    obj = _editing()
    if obj is None:
        return None
    try:
        if obj.TypeId in PIPES:
            if _empty_link(obj.Profile):
                return "Select the profile first."
            if _empty_link(obj.Spine):
                return "Select the path first."
        elif obj.TypeId in LOFTS:
            if _empty_link(obj.Profile):
                return "Select the profiles first."
            if not obj.Sections:
                return "Select a second profile first."
    except Exception as _fw_err:
        _fw_log("pmkeys.py:171", _fw_err)
        return None
    return None


def _empty_link(link):
    if link is None:
        return True
    if isinstance(link, (list, tuple)):
        return link[0] is None
    return False


REQUIRED_BOXES = ("SWStyle_SweepProfile", "SWStyle_SweepPath", "SWStyle_LoftProfiles", "SWStyle_BoundaryDir1")


def empty_box(window):
    ""


    if window is None:
        return None
    try:
        boxes = window.findChildren(QtWidgets.QListWidget)
    except Exception as _fw_err:
        _fw_log("pmkeys.py:196", _fw_err)
        return None
    for box in boxes:
        try:
            if not box.isVisible() or box.count() or not (box.property("swNeed") or box.objectName() in REQUIRED_BOXES):
                continue
            name = (box.toolTip() or "").split("\n")[0].strip().rstrip(".")
            if not name:
                name = box.objectName().replace("SWStyle_", "").replace("SW", "")
            name = name.split(":")[0].strip()
            if " " not in name and any(c.isupper() for c in name[1:]):
                return MISSING      # pkg432: an internal name ("axisSelections"), not words to show
            return "Select the %s first." % (name[:1].lower() + name[1:])
        except RuntimeError as _fw_err:
            _fw_log("pmkeys.py:208", _fw_err)
            continue
    return None


CROSSING = "The sketch has self-intersecting contours: a profile crosses itself. Fix the sketch first."
NO_SOLID = "The feature would give no solid (it has no volume). Change the values or the sketch."
BAD_SOLID = "The feature would give a self-intersecting (invalid) solid. Change the values, the profile or the path."
ADDSUB = ("PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution", "PartDesign::Groove",
          "PartDesign::AdditivePipe", "PartDesign::SubtractivePipe", "PartDesign::AdditiveLoft",
          "PartDesign::SubtractiveLoft", "PartDesign::AdditiveHelix", "PartDesign::SubtractiveHelix")


def _crosses_itself(shape, tol=1e-6):
    ""

    for wire in shape.Wires:
        edges = wire.Edges
        if len(edges) < 3 or len(edges) > 400:
            continue
        boxes = []
        for e in edges:
            bb = e.BoundBox
            bb.enlarge(10 * tol)
            boxes.append(bb)
        for i, a in enumerate(edges):
            for j in range(i + 1, len(edges)):
                b = edges[j]
                if not boxes[i].intersect(boxes[j]):
                    continue
                shared = [v for v in a.Vertexes for w in b.Vertexes if v.Point.distanceToPoint(w.Point) <= tol]
                try:
                    dist, pairs, _info = a.distToShape(b)
                except Exception:
                    continue
                if dist > tol:
                    continue
                for p, q in pairs:
                    if not any(p.distanceToPoint(v.Point) <= 10 * tol for v in shared):
                        return True
    return False


def _profiles(obj):
    out = []
    for name in ("Profile", "Sections"):
        link = getattr(obj, name, None)
        if link is None:
            continue
        items = link if isinstance(link, list) else [link]
        for item in items:
            o = item[0] if isinstance(item, tuple) else item
            if o is not None and hasattr(o, "Shape") and o.isDerivedFrom("Sketcher::SketchObject"):
                out.append(o)
    return out


def bad_result():
    ""



    obj = _editing()
    if obj is None or obj.TypeId not in ADDSUB:
        return None
    try:
        for sk in _profiles(obj):
            if _crosses_itself(sk.Shape):
                return CROSSING
        if "Touched" in obj.State:
            obj.Document.recompute()
        if not obj.isValid():
            return None
        tool = getattr(obj, "AddSubShape", None)
        if tool is None or tool.isNull():
            return None
        if not tool.Solids or tool.Volume <= 1e-9:
            return NO_SOLID
        if not tool.isValid() or (not obj.Shape.isNull() and not obj.Shape.isValid()):
            return BAD_SOLID
    except Exception as _fw_err:
        _fw_log("pmkeys.py:bad_result", _fw_err)
    return None


FAILED = "The feature could not be made with these settings: change them, or Cancel."
# FreeCAD's words for a failed page -> plain words (pkg429)
FAILED_WORDS = (("Finding axis failed", "Place the hole first: a point or a circle on the face gives its position."),)


def failed_result():
    ""


    obj = _editing()
    if obj is None or not getattr(obj, "TypeId", "").startswith("PartDesign::") or obj.TypeId == "PartDesign::Body":
        return None
    try:
        take_typed()                # a value still being typed counts before the check
        if "Touched" in obj.State:
            obj.Document.recompute()
        if obj.isValid():
            return None
        text = obj.getStatusString() or ""
        for raw, plain in FAILED_WORDS:
            if raw in text:
                return plain
        try:
            from . import rebuilderrors
            text = rebuilderrors.describe(obj, text) or text
        except Exception as _fw_err:
            _fw_log("pmkeys.py:failed-words", _fw_err)
        return text.strip() or FAILED
    except Exception as _fw_err:
        _fw_log("pmkeys.py:failed_result", _fw_err)
        return None


MISSING = "This page still needs input above."
BLOCKED = "Correct the value marked in red first."


def missing(window):
    ""
    hint = empty_box(window)
    if hint:
        return hint
    try:
        for box in window.findChildren(QtWidgets.QListWidget):
            if box.isVisible() and not box.count() and box.isEnabled():
                group = box.parentWidget()
                while group is not None and not isinstance(group, QtWidgets.QGroupBox):
                    group = group.parentWidget()
                name = group.title().replace("&", "").strip() if group is not None else ""
                if name and " " not in name and any(c.isupper() for c in name[1:]):
                    name = ""       # pkg432: an internal name ("axisSelections"), not a title to show
                if name:
                    return "Select the %s first." % (name[:1].lower() + name[1:])
    except Exception as _fw_err:
        _fw_log("pmkeys.py:missing", _fw_err)
    return MISSING


def rebuilding():
    """A document is being rebuilt. FreeCAD lets events through during a rebuild (so Esc can stop
    it), so an Enter, a click on OK or a queued timer can arrive while a page's preview is still
    building; closing the page then deleted the widgets the rebuild returns into (the tray
    tutorial's Linear Pattern crashed FreeCAD that way)."""
    try:
        return any(getattr(d, "Recomputing", False) for d in App.listDocuments().values())
    except Exception:
        return False


def when_idle(fn, widget=None, tries=0):
    ""

    if rebuilding() and tries < 1200:          # 3 minutes at most
        QtCore.QTimer.singleShot(150, lambda: when_idle(fn, widget, tries + 1))
        return False
    if widget is not None and not _alive(widget):
        return False
    fn()
    return True


def accept(native):
    ""


    if rebuilding():
        when_idle(lambda: accept(native), native)
        return
    from . import pmmessage
    window = None
    try:
        window = native.window()
    except Exception as _fw_err:
        _fw_log("pmkeys.py:219", _fw_err)
    try:
        if pmmessage.blocked(window):
            Gui.getMainWindow().statusBar().showMessage(BLOCKED, 4000)
            return
    except Exception as _fw_err:
        _fw_log("pmkeys.py:214", _fw_err)
    hint = nothing_picked() or no_axis() or half_specified() or empty_box(window) or bad_result()
    if hint is None and not native.isEnabled():
        hint = missing(window)
    if hint is None:
        hint = failed_result()
    if hint is None:
        take_typed()
        native.click()
        return
    try:
        Gui.getMainWindow().statusBar().showMessage(hint, 4000)
    except Exception as _fw_err:
        _fw_log("pmkeys.py:227", _fw_err)
    try:
        pmmessage.notice(window, hint)
    except Exception as _fw_err:
        _fw_log("pmkeys.py:231", _fw_err)


def take_typed():
    ""


    try:
        from PySide import QtWidgets
        for dock in Gui.getMainWindow().findChildren(QtWidgets.QDockWidget):
            if not dock.isVisible():
                continue        # the Tasks / Combo View dock, or the left pane that holds the PM
            for spin in dock.findChildren(QtWidgets.QAbstractSpinBox):
                if spin.isVisible() and spin.isEnabled() and not spin.keyboardTracking() and EnterKey._typing(spin):
                    spin.interpretText()
    except Exception as _fw_err:
        _fw_log("pmkeys.py:take_typed", _fw_err)


NO_NEGATIVE = {"lengthEdit": "depth", "lengthEdit2": "depth"}
ANGLES = ("revolveAngle", "revolveAngle2")
DEPTH_RANGE = "Please enter a number greater than or equal to 0.0001 and less than or equal to 1000000."
ANGLE_RANGE = "Please enter a number greater than or equal to 0\u00b0 and less than or equal to 360\u00b0."


def _balloon(field, text):
    ""
    try:
        edit = field.lineEdit()
        QtWidgets.QToolTip.showText(field.mapToGlobal(QtCore.QPoint(field.width() // 2, field.height())), text, field,
                                    QtCore.QRect(), 5000)
        if edit is not None:
            QtCore.QTimer.singleShot(0, edit.selectAll)
        field.setFocus()
    except Exception as _fw_err:
        _fw_log("pmkeys.py:balloon", _fw_err)


def _refused_key(field, event):
    ""


    try:
        name = field.objectName()
        text = event.text()
        if not text or (name not in NO_NEGATIVE and name not in ANGLES):
            return False
        hint = None
        if text == "-":
            hint = DEPTH_RANGE if name in NO_NEGATIVE else ANGLE_RANGE
        elif name in ANGLES and text.isdigit():
            edit = field.lineEdit()
            cur = edit.text()
            if edit.hasSelectedText():
                a = edit.selectionStart()
                cur = cur[:a] + text + cur[a + len(edit.selectedText()):]
            else:
                a = edit.cursorPosition()
                cur = cur[:a] + text + cur[a:]
            import re
            m = re.match(r"\s*([0-9]+(?:[.,][0-9]*)?)", cur)
            if m and float(m.group(1).replace(",", ".")) > 360.0:
                hint = ANGLE_RANGE
        if hint is None:
            return False
        _balloon(field, hint)
        return True
    except Exception as _fw_err:
        _fw_log("pmkeys.py:refused_key", _fw_err)
        return False


DEPTH_MIN = 0.0001


def _depth_floor(field, event):
    ""


    try:
        if field.objectName() not in NO_NEGATIVE:
            return False
        kind = event.type()
        if kind == QtCore.QEvent.Wheel:
            if event.angleDelta().y() >= 0:
                return False
            notches = max(1, abs(event.angleDelta().y()) // 120)
        elif kind == QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Down, QtCore.Qt.Key_PageDown):
            notches = 10 if event.key() == QtCore.Qt.Key_PageDown else 1
        else:
            return False
        value = field.property("rawValue")
        step = field.property("singleStep")
        if value is None or step is None:
            return False
        value, step = float(value), float(step)
        if value - step * notches >= DEPTH_MIN - 1e-12:
            return False            # an ordinary step: FreeCAD's box takes it
        if value > DEPTH_MIN + 1e-12:
            field.setProperty("rawValue", DEPTH_MIN)
        event.accept()
        return True
    except Exception as _fw_err:
        _fw_log("pmkeys.py:depth_floor", _fw_err)
        return False


class EnterKey(QtCore.QObject):
    """Enter takes a typed value and presses OK."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.seen = {}

    @staticmethod
    def _typing(field):
        """The field holds typed text its value has not taken yet (pkg106: a focus round trip
        between the typing and Enter re-read the text as seen, and Enter was OK with the old
        value)."""
        try:
            edit = field.lineEdit()
            return edit is not None and edit.isModified()
        except Exception:
            return False

    def eventFilter(self, field, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        kind = event.type()
        if kind == QtCore.QEvent.FocusIn:
            if not self._typing(field):
                self.seen[id(field)] = field.text()
        elif kind == QtCore.QEvent.KeyPress and _refused_key(field, event):
            return True
        elif kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.Wheel) and _depth_floor(field, event):
            return True
        elif kind == QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):

            # Extrude in its tutorials; walks of T1, T5-T7 and the mug all expected it). Before, the first Enter
            # only took the value and a second one was needed.
            if self._typing(field):
                # the field takes its typed value on this Return itself (FreeCAD's quantity boxes commit there), then OK
                QtCore.QTimer.singleShot(0, lambda: self._take(field))
                QtCore.QTimer.singleShot(200, self.accept)
                return False
            QtCore.QTimer.singleShot(0, self.accept)
            return True
        return False

    def _take(self, field):
        """A field that did not take the typed text on its Return (a plain spin box): read it now."""
        try:
            if _alive(field) and self._typing(field):
                field.interpretText()
        except Exception as _fw_err:
            _fw_log("pmkeys:enter", _fw_err)

    def _record(self, field):
        if _alive(field):
            self.seen[id(field)] = field.text()

    def accept(self):
        roles = QtWidgets.QDialogButtonBox
        for box in self.view.findChildren(QtWidgets.QDialogButtonBox):
            for button in box.buttons():
                if box.buttonRole(button) == roles.AcceptRole and not button.isHidden():
                    accept(button)              # not ready: says in red what is missing, as the header OK
                    return


def _own_feature(obj):
    ""
    try:
        return obj.TypeId.endswith("Python") and type(obj.Proxy).__module__.split(".")[0] in ("swstyle", "smcore")
    except Exception:
        return False


def install(view):
    obj = _editing()
    if obj is not None and (not obj.TypeId.startswith("PartDesign::") or obj.TypeId == "PartDesign::Body") \
            and not _own_feature(obj):
        return
    if obj is None:

        # get the Enter key too (pkg106: Enter in the Fillet radius never reached OK)
        from . import pmconfirm
        if not pmconfirm.open():
            return
    keeper = _keepers.get(id(view))
    button = view.findChild(QtWidgets.QToolButton, PICK_BUTTON)
    if obj is not None and button is not None and (keeper is None or not _alive(keeper.button) or keeper.button is not button):
        keeper = _keepers[id(view)] = PickKeeper(view, button)
    enter = view.findChild(EnterKey)
    if enter is None:
        enter = EnterKey(view)
    for widget in view.findChildren(QtWidgets.QWidget):
        if widget.property(DONE) or not widget.isVisible():
            continue
        if widget.objectName() in (PICK_BUTTON, ALL_EDGES) or widget.objectName().startswith("SWStyle"):
            continue
        if isinstance(widget, (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox, QtWidgets.QCheckBox)):
            widget.setProperty(DONE, True)
            if keeper is not None:
                _on_change(widget, keeper.rearm)
            if isinstance(widget, QtWidgets.QAbstractSpinBox):
                widget.installEventFilter(enter)
                if widget.hasFocus():
                    enter.seen[id(widget)] = widget.text()
    if obj is not None:
        _start_depth(view, obj)


def _start_depth(view, obj):
    key = (obj.Document.Name, obj.Name)
    if key not in _new:
        return
    _new.discard(key)
    depth = paths.params().GetFloat(DEPTHS[obj.TypeId], 0.0)
    field = view.findChild(QtWidgets.QWidget, "lengthEdit")
    if depth > 0 and field is not None:
        field.setProperty("rawValue", depth)


def finished(doc_name, name):
    """The panel closed with OK: remember the depth for the next Extrude or Cut."""
    try:
        obj = App.getDocument(doc_name).getObject(name)
    except Exception:
        return
    if obj is not None and obj.TypeId in DEPTHS and obj.Type in ("Length", "TwoLengths"):
        paths.params().SetFloat(DEPTHS[obj.TypeId], float(obj.Length.Value))


def forget(view):
    _keepers.pop(id(view), None)


class _Observer:
    """New Extrudes and Cuts start at the last depth. Ones read from a file (opening a part, or
    pasting / importing features) keep their own: the first Edit Feature of a pad in an opened part
    took the last depth of another part, and Cancel kept it (robustness run 240)."""

    def __init__(self):
        self.restoring = set()

    def slotStartRestoreDocument(self, doc):
        self.restoring.add(doc.Name)

    def slotFinishRestoreDocument(self, doc):
        self.restoring.discard(doc.Name)

    def slotCreatedObject(self, obj):
        if obj.TypeId not in DEPTHS:
            return
        doc = obj.Document
        if doc.Name in self.restoring or getattr(doc, "Restoring", False):
            return
        _new.add((doc.Name, obj.Name))


_observer = None


class WheelGuard(QtCore.QObject):
    ""



    @staticmethod
    def _in_pane(widget):
        w = widget.parentWidget()
        while w is not None:
            if w.metaObject().className() == "Gui::TaskView::TaskView":
                return True
            w = w.parentWidget()
        return False

    @staticmethod
    def _in_tool_page(widget):
        """A sketch PropertyManager page (Line Properties, Circle, Sketch Fillet ...): sketchtoolpm / relationspm."""
        w = widget.parentWidget()
        while w is not None:
            if w.objectName() == "SWRelationsPM":
                return True
            w = w.parentWidget()
        return False

    def _unit_text(self, box):
        if isinstance(box, (QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)):
            # a box made before the add-on started (or by C++) keeps Qt's own setSuffix: spell it here once shown
            want = sw_suffix(box.suffix())
            if want != box.suffix() and not box.hasFocus() and self._in_pane(box):
                cls = QtWidgets.QDoubleSpinBox if isinstance(box, QtWidgets.QDoubleSpinBox) else QtWidgets.QSpinBox
                _qt_set_suffix.get(cls, cls.setSuffix)(box, want)
        elif box.inherits("Gui::QuantitySpinBox") and (self._in_pane(box) or self._in_tool_page(box)) \
                and not box.property("fw_deg_text"):
            edit = box.lineEdit()
            if edit is not None:
                box.setProperty("fw_deg_text", True)
                edit.textEdited.connect(lambda *_a, b=box: _typing(b, True))
                edit.editingFinished.connect(lambda b=box: (_typing(b, False), QtCore.QTimer.singleShot(0, lambda: _deg_text(b))))
                edit.textChanged.connect(lambda *_a, b=box: QtCore.QTimer.singleShot(0, lambda: _deg_text(b)))
            _deg_text(box)

    def eventFilter(self, watched, event):
        try:
            if not isinstance(event, QtCore.QEvent):
                return False
            kind = event.type()
            if kind == QtCore.QEvent.Show and isinstance(watched, (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
                # Qt gives a field the focus on a wheel turn (WheelFocus) before anyone sees the event: a PM field
                # takes the focus from a click or Tab only, so the wheel cannot start editing it
                if watched.focusPolicy() == QtCore.Qt.WheelFocus and self._in_pane(watched):
                    watched.setFocusPolicy(QtCore.Qt.StrongFocus)
                self._unit_text(watched)
                return False
            if kind == QtCore.QEvent.FocusOut and watched.property("fw_deg_text"):
                _typing(watched, False)
                QtCore.QTimer.singleShot(0, lambda b=watched: _deg_text(b))
                return False
            if kind != QtCore.QEvent.Wheel:
                return False
            field = watched
            if not isinstance(field, (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
                parent = field.parentWidget() if isinstance(field, QtWidgets.QWidget) else None
                if not isinstance(parent, (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
                    return False
                field = parent
            if field.hasFocus() or (isinstance(field, QtWidgets.QComboBox) and field.view().isVisible()):
                return False
            area, w = None, field.parentWidget()
            while w is not None:
                if isinstance(w, QtWidgets.QScrollArea):
                    area = w
                if w.metaObject().className() == "Gui::TaskView::TaskView":
                    break
                w = w.parentWidget()
            if w is None or area is None:
                return False        # not in the task pane: Qt's own behaviour
            bar = area.verticalScrollBar()
            step = event.angleDelta().y()
            if step and bar.maximum() > 0:
                bar.setValue(bar.value() - int(step / 120.0 * bar.singleStep() * 3))
            return True
        except RuntimeError:
            return False
        except Exception as _fw_err:
            _fw_log("pmkeys.py:wheel", _fw_err)
            return False



# given " mm" and "°" (and FreeCAD's own quantity boxes write "°"), so one panel showed three spellings.
SW_SUFFIX = {" mm": "mm", " in": "in", "°": "deg", " °": "deg", " deg": "deg"}


def sw_suffix(suffix):
    ""
    return SW_SUFFIX.get(suffix, suffix) if isinstance(suffix, str) else suffix


_qt_set_suffix = {}


def _wrap_suffix():
    ""
    for cls in (QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox):
        if cls in _qt_set_suffix:
            continue
        real = cls.setSuffix
        _qt_set_suffix[cls] = real

        def set_suffix(self, suffix, _real=real):
            return _real(self, sw_suffix(suffix))
        try:
            cls.setSuffix = set_suffix
        except Exception as _fw_err:
            _qt_set_suffix.pop(cls, None)
            _fw_log("pmkeys.py:suffix", _fw_err)


def _deg_text(box):
    """A FreeCAD quantity box in a PM shows "360.00deg" rather than "360.00°" while it is not being typed in."""
    try:
        edit = box.lineEdit()
        if edit is None or box.property("fw_deg_typing"):
            return                  # the user is typing in it: leave their text alone
        text = edit.text()
        if box.property("fw_bare_units"):
            # bareunits-1121: a sketch entity's PM (Line Properties, Circle, Point) writes a length with no unit

            spelled = text.replace(" °", "°").replace(" deg", "°").replace("deg", "°")
            for unit in (" mm", "mm", " in", "in"):
                if spelled.endswith(unit):
                    spelled = spelled[:-len(unit)]
                    break
        else:
            spelled = text.replace(" °", "deg").replace("°", "deg")
            for unit in (" mm", " in"):
                if spelled.endswith(unit):
                    spelled = spelled[:-len(unit)] + unit.strip()
        if spelled != text:
            whole = edit.hasSelectedText() and edit.selectedText() == text
            picked = edit.selectedText() if edit.hasSelectedText() else ""
            start = edit.selectionStart()
            pos = edit.cursorPosition()
            blocked = edit.blockSignals(True)
            try:
                edit.setText(spelled)
                if whole:
                    edit.selectAll()        # a PM opens with its first value selected, ready to type over
                elif picked and spelled[start:start + len(picked)] == picked:
                    # FreeCAD selects the number only ("10.00" of "10.00 mm"): keep it selected, or typed
                    # "60" went after it ("10.0060mm", Triple Clamp TC11 on A600)
                    edit.setSelection(start, len(picked))
                else:
                    edit.setCursorPosition(min(pos, len(edit.text())))
            finally:
                edit.blockSignals(blocked)
    except RuntimeError:
        pass


def _typing(box, on):
    try:
        box.setProperty("fw_deg_typing", bool(on))
    except RuntimeError:
        pass


_wheel = None


def start():
    global _observer, _wheel
    _wrap_suffix()
    if _wheel is None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            _wheel = WheelGuard(app)
            app.installEventFilter(_wheel)
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
