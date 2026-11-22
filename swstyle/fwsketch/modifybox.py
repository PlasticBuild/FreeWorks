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
import re

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtGui, QtWidgets

try:
    from PySide import QtSvg
except ImportError:  # pragma: no cover
    QtSvg = None

SKETCHER_GROUP = "User parameter:BaseApp/Preferences/Mod/Sketcher"

CHECK_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M2.5 8.5l3.5 3.5 7.5-8" '
             'fill="none" stroke="#1e9e3a" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>')
CROSS_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9" '
             'fill="none" stroke="#d6282b" stroke-width="2.4" stroke-linecap="round"/></svg>')
REBUILD_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
               '<rect x="4.5" y="0.75" width="7" height="14.5" rx="3.5" fill="#3a3a3a"/>'
               '<circle cx="8" cy="4.6" r="2.3" fill="#f2c200"/><circle cx="8" cy="11.4" r="2.3" fill="#29b34a"/></svg>')
REVERSE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
               '<path d="M1.5 8h13M1.5 8l3.5-3.5M1.5 8l3.5 3.5M14.5 8L11 4.5M14.5 8L11 11.5" fill="none" '
               'stroke="#2b5fb4" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')
LENGTH_UNITS = (("Millimeters", "mm", 1.0), ("Centimeters", "cm", 10.0), ("Meters", "m", 1000.0),
                ("Microns", "um", 0.001), ("Inches", "in", 25.4), ("Feet", "ft", 304.8))
ANGLE_UNITS = (("Degrees", "deg", 1.0), ("Radians", "rad", 180.0 / math.pi))

DIMENSIONAL = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle", "Weight", "SnellsLaw")

DRIVEN, DRIVING, CANCEL = "driven", "driving", "cancel"
MARK_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
            '<rect x="2" y="3" width="12" height="10" fill="none" stroke="#555" stroke-width="1.2"/>'
            '<path d="M4 10h8M4 10l2-1.5M4 10l2 1.5M12 10l-2-1.5M12 10l-2 1.5M5 5.5h6" fill="none" '
            'stroke="#2b5fb4" stroke-width="1.2" stroke-linecap="round"/></svg>')
FUNCTIONS = ("sin", "cos", "tan", "sec", "cosec", "cotan", "arcsin", "arccos", "atn", "arcsec", "arccosec",
             "arccotan", "abs", "exp", "log", "sqr", "int", "sgn", "pi")

FREECAD_FUNCTIONS = {"atn": "atan", "arcsin": "asin", "arccos": "acos", "sqr": "sqrt", "int": "trunc",
                     "sgn": "sgn", "log": "log"}


FLAT = 1e-7             # rv30: a line shorter or a radius smaller than this (mm) has no shape
FLAT_ERROR = "the value leaves a line with no length or a circle with no radius"


def freecad_expression(doc, text, target=None):
    ""

    out = text.strip().lstrip("=")
    try:
        from .. import equations
        out = equations.to_freecad(doc, out, target=target)
    except Exception as _fw_err:
        _fw_log("fwsketch/modifybox.py:71", _fw_err)
    def fn(m):
        return FREECAD_FUNCTIONS.get(m.group(1).lower(), m.group(1)) + "("
    out = __import__("re").sub(r"\b(atn|arcsin|arccos|sqr|int)\s*\(", fn, out)
    out = __import__("re").sub(r"\bsec\s*\(([^()]*)\)", r"(1/cos(\1))", out)
    out = __import__("re").sub(r"\bcosec\s*\(([^()]*)\)", r"(1/sin(\1))", out)
    out = __import__("re").sub(r"\bcotan\s*\(([^()]*)\)", r"(1/tan(\1))", out)
    out = __import__("re").sub(r"\barcsec\s*\(([^()]*)\)", r"acos(1/(\1))", out)
    out = __import__("re").sub(r"\barccosec\s*\(([^()]*)\)", r"asin(1/(\1))", out)
    out = __import__("re").sub(r"\barccotan\s*\(([^()]*)\)", r"atan(1/(\1))", out)
    return out


def global_variables(doc):
    try:
        from .. import equations
        return [n for n, _v, _e in equations.variables(doc)]
    except Exception:
        return []


MARK_PROP = "FWDimensionMarks"


def marked(sketch, index):
    ""
    name = sketch.Constraints[index].Name or ""
    off = (getattr(sketch, MARK_PROP, "") or "").split("\n")
    return not name or name not in off


def set_marked(sketch, index, on):
    c = sketch.Constraints[index]
    if not c.Name:
        n = 1
        used = {k.Name for k in sketch.Constraints if k.Name}
        while "D%d" % n in used:
            n += 1
        sketch.renameConstraint(index, "D%d" % n)
    name = sketch.Constraints[index].Name
    if MARK_PROP not in sketch.PropertiesList:
        sketch.addProperty("App::PropertyString", MARK_PROP, "FreeCAD", "Dimensions not imported into drawings")
        try:
            sketch.setEditorMode(MARK_PROP, 2)
        except Exception as _fw_err:
            _fw_log("fwsketch/modifybox.py:116", _fw_err)
    off = [n for n in (getattr(sketch, MARK_PROP, "") or "").split("\n") if n and n != name]
    if not on:
        off.append(name)
    setattr(sketch, MARK_PROP, "\n".join(off))

CONFIG_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
              '<rect x="1.5" y="2" width="7" height="5" fill="#d8a43a" stroke="#6b4e12"/>'
              '<rect x="4.5" y="6" width="7" height="5" fill="#e8c35c" stroke="#6b4e12"/>'
              '<path d="M12 12.5l2 2.5 2-2.5z" fill="#3a3a3a"/></svg>')
THIS_CONFIG, ALL_CONFIGS = "this", "all"


def _configs():
    """The ConfigurationManager helper (swstyle/configs.py, the assemblies thread), or None."""
    try:
        from .. import configs
        return configs
    except Exception:
        return None


def unique_dimension_name(sketch):
    ""
    used = {c.Name for c in sketch.Constraints if c.Name}
    n = 1
    while "D%d" % n in used:
        n += 1
    return "D%d" % n

# tests replace these with answers of their own
ASK_DRIVEN = []       # callables() -> DRIVEN | DRIVING | CANCEL | None (None = show the box)
BOX_HOOKS = []        # callables(box) called when a Modify box opens, before exec


def svg_icon(svg, size=16):
    from .. import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pm = _hidpi.canvas(size, size)
    pm.fill(QtCore.Qt.transparent)
    if QtSvg is not None:
        r = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
        p = QtGui.QPainter(pm)
        r.render(p)
        p.end()
    return QtGui.QIcon(pm)


def status(text, ms=5000):
    try:
        Gui.getMainWindow().showMessage(text, ms)
    except Exception as _fw_err:
        _fw_log("fwsketch/modifybox.py:166", _fw_err)


def beside_pointer(w):
    """Move the window beside the pointer, kept inside the main window."""
    try:
        frame = Gui.getMainWindow().geometry()
        at = QtGui.QCursor.pos() + QtCore.QPoint(16, 16)
        x = min(max(at.x(), frame.left() + 10), max(frame.left() + 10, frame.right() - w.width() - 10))
        y = min(max(at.y(), frame.top() + 10), max(frame.top() + 10, frame.bottom() - w.height() - 10))
        w.move(x, y)
    except Exception as _fw_err:
        _fw_log("fwsketch/modifybox.py:178", _fw_err)


def dimension_zone(text=""):
    """Where the dimension being edited is on screen: around the pointer (the double-click, or the
    place the new dimension was put), as wide as its text."""
    at = QtGui.QCursor.pos()
    try:
        fm = QtGui.QFontMetrics(Gui.getMainWindow().font())
        k = max(1.0, fm.height() / 16.0)
        half_w = max(60, fm.horizontalAdvance(text or "000.00") + 24)
        half_h = int(fm.height() * 0.9 + 6 * k)
    except Exception:
        half_w, half_h = 80, 22
    return QtCore.QRect(at.x() - half_w, at.y() - half_h, 2 * half_w, 2 * half_h)


def clear_of_dimension(w, text=""):
    ""

    try:
        frame = Gui.getMainWindow().geometry()
        zone = dimension_zone(text)
        at = QtGui.QCursor.pos()
        x = min(max(at.x() - 20, frame.left() + 10), max(frame.left() + 10, frame.right() - w.width() - 10))
        y = zone.bottom() + 4
        if y + w.height() > frame.bottom() - 10:
            y = zone.top() - w.frameGeometry().height() - 4
        y = max(frame.top() + 10, y)
        w.move(x, y)
    except Exception:
        beside_pointer(w)


def kind_of(constraint):
    t = constraint.Type
    return {"Angle": "Angle", "Radius": "Radius", "Diameter": "Diameter"}.get(t, "Distance")


# --- Make Dimension Driven? (12b) ----------------------------------------------------------------
def prompt_driven_state():
    return App.ParamGet(SKETCHER_GROUP).GetBool("PromptDrivenState", True)


def driven_when_over_defining():
    return App.ParamGet(SKETCHER_GROUP).GetBool("DrivenWhenOverDefining", True)


def ask_driven_state():
    """The box: Make this dimension driven / Leave this dimension driving / Cancel; Don't show
    again turns the prompt off and keeps the answer as the default."""
    for hook in ASK_DRIVEN:
        answer = hook()
        if answer is not None:
            return answer
    grp = App.ParamGet(SKETCHER_GROUP)
    dlg = QtWidgets.QDialog(Gui.getMainWindow())
    dlg.setObjectName("SketcherMakeDimensionDriven")
    dlg.setWindowTitle("Make Dimension Driven?")
    dlg.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint
                       | QtCore.Qt.CustomizeWindowHint)
    layout = QtWidgets.QVBoxLayout(dlg)
    top = QtWidgets.QHBoxLayout()
    icon = QtWidgets.QLabel(dlg)
    icon.setPixmap(dlg.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxWarning).pixmap(32, 32))
    icon.setAlignment(QtCore.Qt.AlignTop)
    top.addWidget(icon)
    text = QtWidgets.QLabel("Adding this dimension will make the sketch over defined or unable to solve. "
                            "Do you want to add it as a driven dimension instead?", dlg)
    text.setWordWrap(True)
    top.addWidget(text, 1)
    layout.addLayout(top)
    driven = QtWidgets.QRadioButton("Make this dimension driven", dlg)
    driving = QtWidgets.QRadioButton("Leave this dimension driving", dlg)
    (driven if driven_when_over_defining() else driving).setChecked(True)
    layout.addWidget(driven)
    layout.addWidget(driving)
    no_more = QtWidgets.QCheckBox("Don't show again", dlg)
    layout.addWidget(no_more)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, dlg)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    dlg.setFixedWidth(360)
    dlg.adjustSize()
    beside_pointer(dlg)
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return CANCEL
    choice = DRIVEN if driven.isChecked() else DRIVING
    if no_more.isChecked():
        grp.SetBool("PromptDrivenState", False)
        grp.SetBool("DrivenWhenOverDefining", choice == DRIVEN)
    return choice


def settle_over_defining(sketch, index):
    """After the dimension was made driven while placed: the answer, applied (settleOverDefining)."""
    if not prompt_driven_state():
        return DRIVEN
    choice = ask_driven_state()
    if choice == DRIVING:
        sketch.setDriving(index, True)
        status("The sketch is over defined")
    return choice


# --- the Modify box (12, 15c) -----------------------------------------------------------------------
class Thumbwheel(QtWidgets.QWidget):
    ""

    def __init__(self, parent, step, done):
        super().__init__(parent)
        self.step, self.done = step, done
        self.setObjectName("SketcherModifyThumbwheel")
        self.setFixedHeight(9)
        self.setCursor(QtCore.Qt.SizeHorCursor)
        self.setToolTip("Drag to change the value (Alt: finer, Ctrl: coarser)")
        self.last_x = 0
        self.turned = 0
        self.dragging = False

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        shade = QtGui.QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0.0, QtGui.QColor(110, 110, 110))
        shade.setColorAt(0.5, QtGui.QColor(225, 225, 225))
        shade.setColorAt(1.0, QtGui.QColor(110, 110, 110))
        p.fillRect(self.rect(), shade)
        p.setPen(QtGui.QColor(70, 70, 70))
        pitch = 4
        x = ((self.turned % pitch) + pitch) % pitch
        while x < self.width():
            p.drawLine(x, 1, x, self.height() - 2)
            x += pitch
        p.end()

    @staticmethod
    def factor(modifiers):
        if modifiers & QtCore.Qt.AltModifier:
            return 0.1
        return 10.0 if modifiers & QtCore.Qt.ControlModifier else 1.0

    def mousePressEvent(self, event):
        self.last_x = int(event.position().x()) if hasattr(event, "position") else event.pos().x()
        self.dragging = True

    def mouseMoveEvent(self, event):
        if not self.dragging:
            return
        x = int(event.position().x()) if hasattr(event, "position") else event.pos().x()
        notches = int((x - self.last_x) / 4)
        if notches:
            self.last_x += notches * 4
            self.turned += notches * 4
            self.step(notches * self.factor(event.modifiers()))
            self.update()

    def mouseReleaseEvent(self, _event):
        if self.dragging:
            self.dragging = False
            self.done()

    def wheelEvent(self, event):
        notches = int(event.angleDelta().y() / 120)
        if notches:
            self.turned += notches * 4
            self.step(notches * self.factor(event.modifiers()))
            self.update()
            self.done()
        event.accept()


UNITS_LENGTH = ("mm", "in", "cm", "m", "ft")    # the PM boxes' order (pmvalues)
UNITS_ANGLE = ("deg", "rad")
_NUMBER_TAIL = re.compile(r"(-?\d+(?:[.,]\d*)?)\s*([A-Za-z]*)$")


class UnitSuggest(QtCore.QObject):
    ""



    def __init__(self, edit, angle):
        super().__init__(edit)
        self.edit = edit
        self.units = UNITS_ANGLE if angle else UNITS_LENGTH
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWUnitSuggest")
        self.list.setWindowFlags(QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)
        self.list.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.list.setFocusPolicy(QtCore.Qt.NoFocus)
        self.list.itemClicked.connect(lambda item: self.chosen(item.text()))
        edit.textEdited.connect(self.typed)
        edit.installEventFilter(self)
        box = edit.parentWidget()
        if isinstance(box, QtWidgets.QAbstractSpinBox):
            box.installEventFilter(self)      # the spin box has the focus and gets the keys
        edit.destroyed.connect(self.list.deleteLater)

    def typed(self, text):
        m = _NUMBER_TAIL.search(text or "")
        if not m or text.lstrip().startswith("="):
            self.list.hide()
            return
        number, unit = m.group(1), m.group(2).lower()
        head = text[:m.start()]
        options = [u for u in self.units if u.startswith(unit)] if unit else list(self.units)
        if not options or (unit in self.units and len(options) == 1):
            self.list.hide()
            return
        self.list.clear()
        rows = ["%s%s %s" % (head, number, u) for u in options]
        if not unit and number.isdigit() and len(number) == 1 and "in" in self.units:
            rows.insert(options.index("in") + 1, "%s%s/4in" % (head, number))     # a single digit: also a fraction of an inch (after "in", as pmvalues)
        for r in rows:
            self.list.addItem(r)
        self.list.setCurrentRow(-1)
        row = self.list.sizeHintForRow(0) if self.list.count() else 16
        self.list.setFixedSize(max(self.edit.width(), 80), row * self.list.count() + 4)
        self.list.move(self.edit.mapToGlobal(QtCore.QPoint(0, self.edit.height())))
        self.list.show()

    def chosen(self, text):
        self.edit.setText(text)
        self.list.hide()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t in (QtCore.QEvent.FocusOut, QtCore.QEvent.Hide):
            self.list.hide()
            return False
        if t != QtCore.QEvent.KeyPress or not self.list.isVisible():
            return False
        k = event.key()
        if k in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Up):
            n = self.list.count()
            r = self.list.currentRow()
            r = (r + (1 if k == QtCore.Qt.Key_Down else -1)) % n if r >= 0 else (0 if k == QtCore.Qt.Key_Down else n - 1)
            self.list.setCurrentRow(r)
            return True
        if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Tab) and self.list.currentRow() >= 0:
            self.chosen(self.list.currentItem().text())
            return True
        if k == QtCore.Qt.Key_Escape:
            picked = self.list.currentRow() >= 0
            self.list.hide()
            # a row arrowed into: Esc only closes the list; none: Esc goes on to the box, which

            return picked
        if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.list.hide()
        return False


class EquationList(QtCore.QObject):
    ""



    def __init__(self, box):
        super().__init__(box)
        self.box = box
        self.edit = box.line_edit()
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SketcherModifyEquationList")
        self.list.setWindowFlags(QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)
        self.list.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.list.setFocusPolicy(QtCore.Qt.NoFocus)
        self.list.itemClicked.connect(self.pick)
        self.edit.textEdited.connect(self.typed)
        self.edit.installEventFilter(self)
        spin = self.edit.parentWidget()
        if isinstance(spin, QtWidgets.QAbstractSpinBox):
            spin.installEventFilter(self)
        self.edit.destroyed.connect(self.list.deleteLater)

    def _word(self):
        text = self.edit.text()[:self.edit.cursorPosition()]
        m = re.search(r'"?[A-Za-z_][\w@]*$', text)
        return (m.start(), m.group(0)) if m else (len(text), "")

    def rows(self):
        out = []
        doc = self.box.sketch.Document
        names = global_variables(doc)
        if names:
            out.append(("Global Variables", None))
            out += [('"%s"' % n, '"%s"' % n) for n in names]
        out.append(("Functions", None))
        out += [(f, f if f == "pi" else f + "()") for f in FUNCTIONS]
        return out

    def typed(self, text):
        if not text.lstrip().startswith("="):
            self.list.hide()
            return
        self.box.unit_suggest.list.hide()
        _at, word = self._word()
        key = word.lstrip('"').lower()
        self.list.clear()
        head = None
        for shown, insert in self.rows():
            if insert is None:
                head = shown
                continue
            if key and not shown.lstrip('"').lower().startswith(key):
                continue
            if head is not None:
                h = QtWidgets.QListWidgetItem(head)
                h.setFlags(QtCore.Qt.NoItemFlags)
                f = h.font()
                f.setBold(True)
                h.setFont(f)
                self.list.addItem(h)
                head = None
            item = QtWidgets.QListWidgetItem("    " + shown)
            item.setData(QtCore.Qt.UserRole, insert)
            self.list.addItem(item)
        if not self.list.count():
            self.list.hide()
            return
        self.list.setCurrentRow(-1)
        row = self.list.sizeHintForRow(0) or 16
        self.list.setFixedSize(max(self.edit.width(), 150), row * min(self.list.count(), 12) + 4)
        self.list.move(self.edit.mapToGlobal(QtCore.QPoint(0, self.edit.height())))
        self.list.show()
        self.list.raise_()

    def pick(self, item):
        insert = item.data(QtCore.Qt.UserRole) if item is not None else None
        if not insert:
            return
        at, word = self._word()
        text = self.edit.text()
        pos = self.edit.cursorPosition()
        self.edit.setText(text[:at] + insert + text[pos:])
        self.edit.setCursorPosition(at + (insert.index("(") + 1 if insert.endswith("()") else len(insert)))
        self.edit.setFocus()
        self.list.hide()

    def _move(self, down):
        rows = [i for i in range(self.list.count()) if self.list.item(i).flags() & QtCore.Qt.ItemIsSelectable]
        if not rows:
            return
        cur = self.list.currentRow()
        if cur not in rows:
            self.list.setCurrentRow(rows[0] if down else rows[-1])
            return
        i = rows.index(cur) + (1 if down else -1)
        self.list.setCurrentRow(rows[max(0, min(len(rows) - 1, i))])

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t in (QtCore.QEvent.FocusOut, QtCore.QEvent.Hide):
            self.list.hide()
            return False
        if t != QtCore.QEvent.KeyPress or not self.list.isVisible():
            return False
        k = event.key()
        if k in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Up):
            self._move(k == QtCore.Qt.Key_Down)
            return True
        if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Tab) and self.list.currentRow() >= 0:
            self.pick(self.list.currentItem())
            return True
        if k == QtCore.Qt.Key_Escape:
            self.list.hide()
            return True
        if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.list.hide()
        return False


class ModifyBox(QtWidgets.QDialog):
    """A small window titled Modify at the pointer: check, cross, rebuild (and reverse), the name,
    the value, the thumbwheel and the Units row. run() returns True when the value was kept."""

    def __init__(self, sketch, index, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.sketch, self.index = sketch, index
        self.constraint = sketch.Constraints[index]
        self.success = False
        self.scale_first = False   # a dimension being created: the first one scales the sketch
        self.scaled_by = None
        self.angle = self.constraint.Type == "Angle"
        self.setObjectName("SketcherModifyBox")
        self.setWindowTitle("Modify")
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint
                            | QtCore.Qt.CustomizeWindowHint)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(3)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(1)
        self.check = self.button(CHECK_SVG, "Save the current value and exit the dialog", self.accept)
        self.check.setDefault(True)
        self.cross = self.button(CROSS_SVG, "Restore the original value and exit the dialog", self.reject)
        self.rebuild_button = self.button(REBUILD_SVG, "Rebuild the sketch with the current value", self.rebuild)
        for b in (self.check, self.cross, self.rebuild_button):
            row.addWidget(b)

        self.mark_button = self.button(MARK_SVG, "Mark dimension to be imported into a drawing", self.toggle_mark)
        self.mark_button.setObjectName("SketcherModifyMark")
        self.mark_button.setCheckable(True)
        self.mark_button.setChecked(marked(sketch, index))
        self._mark0 = self.mark_button.isChecked()
        self.own_transaction = False   # True: the box's transaction holds only its own change (no empty undo step)
        row.addWidget(self.mark_button)
        self.reverse_button = None
        if self.constraint.Type in ("DistanceX", "DistanceY"):
            self.reverse_button = self.button(REVERSE_SVG, "Reverse the sense of the dimension", self.reverse)
            row.addWidget(self.reverse_button)

        self.config_scope = None
        self.config_button = None
        cfg = _configs()
        try:
            several = cfg is not None and cfg.several(sketch.Document)
        except Exception:
            several = False
        if several:
            self.config_scope = THIS_CONFIG
            b = self.button(CONFIG_SVG, "This Configuration", self.show_config_menu)
            b.setObjectName("SketcherModifyConfigurations")
            m = QtWidgets.QMenu(b)
            self.config_actions = {}
            group = QtGui.QActionGroup(m) if hasattr(QtGui, "QActionGroup") else QtWidgets.QActionGroup(m)
            for key, label in ((THIS_CONFIG, "This Configuration"), (ALL_CONFIGS, "All Configurations"),
                               ("specify", "Specify Configurations...")):
                a = m.addAction(label)
                a.setCheckable(True)
                group.addAction(a)
                a.triggered.connect(lambda _c=False, k=key: self.pick_scope(k))
                self.config_actions[key] = a
            self.config_actions[THIS_CONFIG].setChecked(True)
            self.config_menu = m
            self.config_button = b
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)

        self.name = QtWidgets.QLineEdit(self._name_text(self.constraint.Name), self)
        self.name.setPlaceholderText("Name")
        self.name.setToolTip(kind_of(self.constraint))
        layout.addWidget(self.name)
        self.value = self.make_value_widget()
        self._full_value_text()
        self.value.setToolTip("%s (Enter a value or start with = to create an equation)" % kind_of(self.constraint))
        self.unit_suggest = UnitSuggest(self.line_edit(), self.angle)
        self.equation_list = EquationList(self)

        # a linked value opens with its value, and a new value changes every dimension on it
        self.expr_path, self.expr0 = self._expression_now()
        self.link_name = None
        if self.expr0:
            try:
                from .. import equations
                self.link_name = equations.linked_name(sketch, self.expr_path)
                if self.link_name is None:
                    self.line_edit().setText("=" + equations.to_sw(sketch.Document, self.expr0, owner=sketch))
            except Exception as _fw_err:
                _fw_log("fwsketch/modifybox.py:expr", _fw_err)
        # Enter in the value keeps it and closes the box, also after arithmetic (25*2) that the
        # quantity box would only work out on the first Enter
        self.line_edit().installEventFilter(self)
        self._user_typed = False
        self.line_edit().textEdited.connect(self._typed_now)
        if isinstance(self.value, QtWidgets.QAbstractSpinBox):
            self.value.installEventFilter(self)
        vrow = QtWidgets.QHBoxLayout()
        vrow.setSpacing(1)
        vrow.addWidget(self.value, 1)

        self.value_menu_button = QtWidgets.QToolButton(self)
        self.value_menu_button.setObjectName("SketcherModifyValueMenu")
        self.value_menu_button.setText("\u25be")
        self.value_menu_button.setToolTip("Global Variables, Functions, Link Value")
        self.value_menu_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.value_menu_button.setAutoRaise(True)
        self.value_menu_button.clicked.connect(self.show_value_menu)
        vrow.addWidget(self.value_menu_button)
        layout.addLayout(vrow)
        self.linked = False
        self.wheel = Thumbwheel(self, self.step_value, self.rebuild)
        layout.addWidget(self.wheel)
        units = QtWidgets.QPushButton("Units", self)
        units.setObjectName("SketcherModifyUnits")
        units.setFlat(True)
        units.setAutoDefault(False)
        units.setFocusPolicy(QtCore.Qt.NoFocus)
        units.setStyleSheet("QPushButton { text-align: left; padding: 2px 4px; }")
        arrow = QtWidgets.QLabel(">", units)
        arrow.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        ul = QtWidgets.QHBoxLayout(units)
        ul.setContentsMargins(0, 0, 6, 0)
        ul.addStretch(1)
        ul.addWidget(arrow)
        menu = QtWidgets.QMenu(units)
        for label, unit, factor in (ANGLE_UNITS if self.angle else LENGTH_UNITS):
            menu.addAction(label, lambda u=unit, f=factor: self.show_in_unit(u, f))
        units.clicked.connect(lambda: menu.popup(units.mapToGlobal(QtCore.QPoint(units.width(), 0))))
        self.units = units

        # value's arrow (and a unit can be typed with the value)
        units.hide()
        self.setMinimumWidth(170)
        self.adjustSize()
        edit = self.line_edit()
        # the value as shown (to the display precision): kept as it is, not rounded to it, when

        self._shown_text = edit.text().strip() if edit is not None else None
        self.initial = self.current_value()

    def _expression_now(self):
        """(path, expression) of the expression on this dimension, else (None, None)."""
        name = self.constraint.Name or ""
        for path, expr in getattr(self.sketch, "ExpressionEngine", []) or []:
            p = path.lstrip(".")
            if p == "Constraints[%d]" % self.index or (name and p == "Constraints." + name):
                return path, expr
        return None, None

    def _as_opened(self, text):
        """The text the box opened with: the full value it shows, or the quantity box's own
        rounded form of it (the box writes "36.06 mm" back over "36.0555 mm" when it takes the
        focus): either one keeps the exact value."""
        if getattr(self, "_user_typed", False) and text != getattr(self, "_shown_text", None):
            return False
        return text in (getattr(self, "_shown_text", None), getattr(self, "_box_text", None))

    def _typed_now(self, _text):
        self._user_typed = True

    def _equation_back(self):
        """The quantity box writes its number over the text when it is shown or takes the focus:
        the equation goes back in."""
        edit = self.line_edit()
        shown = getattr(self, "_shown_text", None) or ""
        if getattr(self, "_user_typed", False):
            return
        if edit is not None and shown.startswith("=") and edit.text().strip() != shown:
            edit.setText(shown)

    def eventFilter(self, obj, event):
        if isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.KeyPress \
                and event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and self.isVisible():
            for chooser in (self.unit_suggest.list, self.equation_list.list):
                if chooser.isVisible() and chooser.currentRow() >= 0:
                    return False        # Enter picks the row first
            self.unit_suggest.list.hide()
            self.equation_list.list.hide()
            self.accept()
            return True
        return False

    def button(self, svg, tip, slot):
        b = QtWidgets.QPushButton(self)
        b.setObjectName("SketcherModifyButton")
        b.setFlat(True)
        b.setAutoDefault(False)
        b.setFocusPolicy(QtCore.Qt.NoFocus)
        b.setIcon(svg_icon(svg))
        b.setIconSize(QtCore.QSize(16, 16))
        b.setFixedSize(24, 22)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    # --- the value ------------------------------------------------------------------------------
    def make_value_widget(self):
        value = self.constraint.Value
        if self.angle:
            value = math.degrees(value)
        else:

            # value; the sketch keeps the near-edge distance
            self.extra = 0.0
            try:
                from .. import dimensionpm
                self.extra = float(dimensionpm.shown_value(self.sketch, self.index)) - float(value)
            except Exception:
                self.extra = 0.0
            value += self.extra
        self._exact = value
        w = None
        try:
            w = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
            w.setParent(self)
            w.setProperty("unit", "deg" if self.angle else "mm")
            w.setProperty("rawValue", value)
            self.quantity = True
        except Exception:
            w = None
        if w is None:
            w = QtWidgets.QDoubleSpinBox(self)
            w.setDecimals(3)
            w.setRange(-1e9, 1e9)
            w.setValue(value)
            w.setSuffix(" deg" if self.angle else " mm")
            self.quantity = False
        w.setObjectName("DatumValue")
        w.setKeyboardTracking(False)
        return w

    def line_edit(self):
        return self.value.findChild(QtWidgets.QLineEdit) or self.value.lineEdit()

    def typed_value(self):
        ""



        edit = self.line_edit()
        text = edit.text().strip() if edit is not None else ""
        if not text or text.startswith("=") or self._as_opened(text):
            return None
        try:
            q = App.Units.Quantity(text)
            if q.Unit == App.Units.Unit():

                return float(q.Value) * (1.0 if self.angle else self.length_factor())
            return float(q.getValueAs("deg" if self.angle else "mm"))
        except Exception as _fw_err:
            _fw_log("fwsketch/modifybox.py:614", _fw_err)
            return None

    def length_factor(self):
        """Millimetres per unit of the length the box shows (1 in MMGS, 25.4 in IPS)."""
        try:
            shown = abs(float(self.constraint.Value)) or 1.0
            q = App.Units.Quantity(shown, App.Units.Length)
            factor = float(App.Units.schemaTranslate(q, App.Units.getSchema())[1])
            return factor if factor > 0 else 1.0
        except Exception:
            return 1.0

    def current_value(self):
        """The value in the box, in degrees for an angle, else in millimetres."""
        typed = self.typed_value()
        if typed is not None:
            return typed
        edit = self.line_edit()
        if getattr(self, "_exact", None) is not None and edit is not None \
                and self._as_opened(edit.text().strip()):
            return self._exact      # untouched: the exact value, not the rounded one the box shows
        if self.quantity:
            return float(self.value.property("rawValue"))
        return float(self.value.value())

    def set_value(self, v):
        if self.quantity:
            self.value.setProperty("rawValue", v)
        else:
            self.value.setValue(v)
        self.select_number()

    def select_number(self):
        edit = self.line_edit()
        if edit is not None:
            self.value.setFocus()
            edit.selectAll()

    def step_value(self, steps):
        step = float(self.value.property("singleStep") or 1.0) if self.quantity else self.value.singleStep()
        self.set_value(self.current_value() + steps * step)

    def quantity_text(self):
        v = self.current_value()
        return "%.8g %s" % (v, "deg" if self.angle else "mm")

    def expression(self):
        edit = self.line_edit()
        text = edit.text().strip() if edit is not None else ""
        return text[1:].strip() if text.startswith("=") else None

    def apply_value(self, first=False):
        if self.linked:
            return          # Link Value tied the value to the shared one
        expr = self.expression()
        extra = 0.0 if self.angle else getattr(self, "extra", 0.0)
        edit = self.line_edit()
        if expr and self.expr0 and edit is not None and self._as_opened(edit.text().strip()):
            return          # the equation it opened with, untouched
        if not expr and self.link_name:
            # a linked value: the new value is the shared one, so every dimension on it follows
            if edit is not None and self._as_opened(edit.text().strip()):
                return
            from .. import equations
            equations.set_variable(self.sketch.Document, self.link_name, "%.12g %s" % (
                self.current_value() - extra, "deg" if self.angle else "mm"))
            return
        if self.expr0 and not getattr(self, "_expr_cleared", False):

            self.sketch.setExpression(self.expr_path, None)
            self._expr_cleared = True
        if expr:
            path = self.expr_path or ("Constraints[%d]" % self.index)
            fc = freecad_expression(self.sketch.Document, expr, target=(self.sketch, "." + path.lstrip(".")))
            if abs(extra) > 1e-12:
                fc = "(%s) - %.12g mm" % (fc, extra)
            from .. import equations
            try:

                equations.accept_expression(self.sketch.Document, self.sketch, path, fc,
                                            self.constraint.Name or "the dimension")
            except ValueError:
                if self.expr0 and self.expr_path:
                    self.sketch.setExpression(self.expr_path, self.expr0)     # the old equation stays
                    self._expr_cleared = False
                raise
        elif abs(extra) > 1e-12:
            self.sketch.setDatum(self.index, App.Units.Quantity("%.12g mm" % (self.current_value() - extra)))
        else:
            if first and self.scale_first and not self.angle:
                from . import firstdim
                self.scaled_by = firstdim.on_first_dimension(self.sketch, self.index, self.current_value())
            self.sketch.setDatum(self.index, App.Units.Quantity(self.quantity_text()))

    # --- the buttons ----------------------------------------------------------------------------
    def _no_flat_geometry(self, before):
        ""

        from . import invalid
        if invalid.degenerate(self.sketch, FLAT) - before:
            raise ValueError(FLAT_ERROR)

    def rebuild(self):
        from . import invalid
        try:
            before = invalid.degenerate(self.sketch, FLAT)
            value0 = self.sketch.Constraints[self.index].Value
        except Exception:
            before, value0 = None, None
        try:
            self.apply_value()
            self.sketch.solve()
            if before is not None:
                self._no_flat_geometry(before)
        except Exception as e:
            if FLAT_ERROR in str(e) and value0 is not None:
                try:   # rv30: Rebuild is not an undo step of its own, so the value it tried goes back here
                    self.sketch.setDatum(self.index, value0)
                except Exception as _fw_err:
                    _fw_log("fwsketch/modifybox.py:rebuild flat", _fw_err)
            self.value_failed(e)
        self.select_number()

    def value_failed(self, error):
        ""

        from . import invalid
        if invalid.value_error(error) or FLAT_ERROR in str(error):
            invalid.value_box(self)   # FreeCAD's setDatum (or rv30's check) has put the old value back
        else:
            status("Value Error: %s" % error)
        self.sketch.solve()

    def reverse(self):
        self.set_value(-self.current_value())

    # --- the value's menu ---------------------------------------------------------------------------
    def value_menu(self):
        """The arrow's menu: Global Variables (the part's), Functions and Link Value."""
        m = QtWidgets.QMenu(self)
        m.setObjectName("SketcherModifyValueMenuList")
        self._submenus = []
        gv = QtWidgets.QMenu("Global Variables", m)
        m.addMenu(gv)
        self._submenus.append(gv)
        names = global_variables(self.sketch.Document)
        for name in names:
            gv.addAction(name, lambda n=name: self.insert_text('"%s"' % n))
        gv.addSeparator()
        gv.addAction("Create Global Variable...", self.create_variable)
        fn = QtWidgets.QMenu("Functions", m)
        m.addMenu(fn)
        self._submenus.append(fn)
        for f in FUNCTIONS:
            fn.addAction(f, lambda t=f: self.insert_text(t if t == "pi" else t + "("))
        m.addAction("Link Value...", self.link_value)
        um = QtWidgets.QMenu("Units", m)
        m.addMenu(um)
        self._submenus.append(um)
        for label, unit, factor in (ANGLE_UNITS if self.angle else LENGTH_UNITS):
            um.addAction(label, lambda u=unit, f=factor: self.show_in_unit(u, f))
        return m

    def show_value_menu(self):
        self._menu = self.value_menu()
        b = self.value_menu_button
        self._menu.popup(b.mapToGlobal(QtCore.QPoint(0, b.height())))

    def insert_text(self, text):
        ""

        edit = self.line_edit()
        if edit is None:
            return
        now = edit.text().strip()
        if not now.startswith("="):
            now = "="
        edit.setText(now + text)
        edit.setFocus()
        edit.end(False)

    def create_variable(self, name=None, value=None):
        """A new global variable with the box's value, used in the box (= "name")."""
        if name is None:
            name, ok = QtWidgets.QInputDialog.getText(self, "Global Variable", "Name:")
            if not ok or not name.strip():
                return None
        name = name.strip()
        v = self.current_value() if value is None else value
        try:
            from .. import equations
            equations.set_variable(self.sketch.Document, name, "%.10g" % v)
        except Exception as error:
            status("Global Variable: %s" % error)
            return None
        edit = self.line_edit()
        if edit is not None:
            edit.setText('="%s"' % name)
        return name

    def link_value(self, name=None):
        ""

        try:
            from .. import equations
        except Exception:
            equations = None
        if equations is not None and hasattr(equations, "link_value"):
            # part-wide, as the right-click Link Values (rcextras): across sketches and features
            if name is None:
                names = equations.linked_values(self.sketch.Document)
                name, ok = QtWidgets.QInputDialog.getItem(self, "Shared Values", "Name:", names or [""], 0, True)
                if not ok or not (name or "").strip():
                    return False
            try:
                if not self.expression() and not self.link_name:
                    self.apply_value()      # the value typed so far is the one a new name takes
                path = self.expr_path or ("Constraints[%d]" % self.index)
                equations.link_value(self.sketch, path, name.strip())
            except Exception as error:
                status("Link Value: %s" % error)
                return False
            self.linked = True
            self.sketch.solve()
            status("Linked to %s" % name.strip())
            self.accept()
            return True
        if name is None:
            try:
                from .. import rcextras
                names = rcextras.linked_names(self.sketch)
            except Exception:
                names = []
            name, ok = QtWidgets.QInputDialog.getItem(self, "Shared Values", "Name:", names or [""], 0, True)
            if not ok or not (name or "").strip():
                return False
        safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name.strip())
        if safe[:1].isdigit():
            safe = "_" + safe
        sk = self.sketch
        master = next((i for i, c in enumerate(sk.Constraints) if c.Name == safe and i != self.index), None)
        try:
            from .. import rcextras
            flags = rcextras._flags(sk, rcextras.DISPLAY_PROP)
        except Exception:
            rcextras, flags = None, None
        if master is None:
            self.sketch.setDatum(self.index, App.Units.Quantity(self.quantity_text()))
            sk.renameConstraint(self.index, safe)
            if rcextras is not None:
                rcextras._set_flags(sk, rcextras.DISPLAY_PROP, flags + ["%s:LinkMaster" % safe])
            self.name.setText(self._name_text(safe))
        else:
            if (sk.Constraints[master].Type == "Angle") != self.angle:
                status("An angle cannot share a value with a length")
                return False
            sk.setExpression("Constraints[%d]" % self.index, "Constraints.%s" % safe)
            self.linked = True
        sk.solve()
        status("Linked to %s" % safe)
        self.accept()
        return True

    def toggle_mark(self):
        set_marked(self.sketch, self.index, self.mark_button.isChecked())

    def show_config_menu(self):
        b = self.config_button
        self.config_menu.popup(b.mapToGlobal(QtCore.QPoint(0, b.height())))

    def pick_scope(self, key):
        """This Configuration / All Configurations, or the Specify Configurations box's names."""
        labels = {THIS_CONFIG: "This Configuration", ALL_CONFIGS: "All Configurations"}
        if key != "specify":
            self.config_scope = key
            self.config_button.setToolTip(labels[key])
            return

        def chosen(names):
            names = list(names or [])
            if names:
                self.config_scope = names
                self.config_button.setToolTip("Specify Configurations: %s" % ", ".join(names))
                self.config_actions["specify"].setChecked(True)
            self.select_number()
        # the Specify box stays open over this one (it calls chosen on OK); until then the old choice holds
        cur = self.config_scope
        self.config_actions["specify" if isinstance(cur, list) else cur].setChecked(True)
        try:
            try:
                _configs().specify(self.sketch.Document, chosen, parent=self)
            except TypeError:
                _configs().specify(self.sketch.Document, chosen)
        except Exception as e:
            status("Specify Configurations: %s" % e)

    def apply_to_configurations(self):
        """The kept value through the ConfigurationManager, for the scope picked on the button."""
        if not self.sketch.Constraints[self.index].Name:
            self.sketch.renameConstraint(self.index, unique_dimension_name(self.sketch))
            self.name.setText(self._name_text(self.sketch.Constraints[self.index].Name))
        name = self.sketch.Constraints[self.index].Name
        unit = "deg" if self.angle else "mm"
        _configs().set_value(self.sketch, "Constraints.%s" % name, App.Units.Quantity(self.quantity_text()),
                             self.config_scope, old=App.Units.Quantity("%.8g %s" % (self.initial, unit)))

    def show_in_unit(self, unit, factor):
        edit = self.line_edit()
        if edit is not None:
            edit.setText("%s %s" % (("%.10g" % (self.current_value() / factor)), unit))
            self.select_number()

    def _name_text(self, name):
        """D2@Sketch1: the dimension's name, or the D# it would get, and its sketch."""
        try:
            return "%s@%s" % (name or unique_dimension_name(self.sketch), self.sketch.Label)
        except Exception:
            return name or ""

    def _typed_name(self):
        """The name typed, without its @Sketch1; "" when an unnamed dimension's D# is left as shown."""
        text = self.name.text().strip()
        tail = "@" + (getattr(self.sketch, "Label", "") or "")   # a feature's own dimension (Pad depth) has no sketch
        if text.endswith(tail):
            text = text[:-len(tail)].strip()
        if not self.constraint.Name and text == unique_dimension_name(self.sketch):
            return ""
        return text

    def _full_value_text(self):
        ""

        try:
            edit = self.line_edit()
            v = getattr(self, "_exact", None)
            if edit is None or v is None or not self.quantity:
                return
            self._box_text = edit.text().strip()
            try:
                from .. import unitspage
                least = int(unitspage.angle_decimals(self.sketch.Document) if self.angle else unitspage.decimals())
            except Exception:
                least = 2
            if self.angle:
                shown, unit = v, "°"
            else:
                _text, factor, unit = App.Units.Quantity(v, App.Units.Length).getUserPreferred()
                shown = v / float(factor or 1.0)
            text = "%.8f" % shown
            whole, _, frac = text.partition(".")
            frac = frac.rstrip("0")
            if len(frac) < least:
                frac = frac + "0" * (least - len(frac))
            number = whole + ("." + frac if frac else "")
            edit.setText("%s %s" % (number, unit) if unit != "°" else number + unit)
        except Exception as _fw_err:
            _fw_log("fwsketch/modifybox.py:full value", _fw_err)

    def accept(self):
        from . import invalid
        if invalid.bad_name(self._typed_name()):

            invalid.name_box(self)
            self.name.setFocus()
            self.name.selectAll()
            return
        try:
            if self.own_transaction and self._untouched(self._typed_name() or (self.constraint.Name or "")):
                self._drop_own_step()
                self.success = True
                super().accept()
                return
        except Exception as _fw_err:
            _fw_log("fwsketch/modifybox.py:untouched", _fw_err)
        try:
            from . import invalid as _invalid
            before = _invalid.degenerate(self.sketch, FLAT)
            self.apply_value(first=True)
            self.sketch.solve()
            self._no_flat_geometry(before)
            name = self._typed_name()
            if name and name != (self.constraint.Name or ""):
                try:
                    self.sketch.renameConstraint(self.index, name)
                except Exception as _fw_err:
                    _fw_log("fwsketch/modifybox.py:866", _fw_err)
            if self.config_scope is not None and not self.expression():
                self.apply_to_configurations()
            if self.own_transaction and self._untouched(name or (self.constraint.Name or "")):
                self._drop_own_step()     # nothing changed: no empty undo step
            else:
                self.sketch.Document.commitTransaction()
            self.sketch.solve()
            self.success = True
        except Exception as e:
            from . import invalid
            self.sketch.Document.abortTransaction()
            if invalid.value_error(e) or FLAT_ERROR in str(e):
                invalid.value_box()
            else:
                status("Value Error: %s" % e)
            self.sketch.solve()
        super().accept()

    def _untouched(self, name):
        """The box changed nothing: same value, no equation or link, same name and mark, no
        configurations (their table is written on every accept), the sketch not scaled."""
        try:
            v0, v = float(self.initial), float(self.current_value())
        except Exception:
            return False
        return (abs(v - v0) <= 1e-12 * (1.0 + abs(v0)) and not self.expression() and not self.linked
                and name == (self.constraint.Name or "") and self.mark_button.isChecked() == self._mark0
                and self.config_scope is None and not self.scaled_by)

    def _drop_own_step(self):
        """Abort the box's step. A step that recorded nothing yet stays armed in FreeCAD after
        abortTransaction (it opens on the next change, e.g. the recompute below, and wipes Redo),
        so the box's own step is also closed at application level."""
        self.sketch.Document.abortTransaction()
        if self.own_transaction:
            try:
                if App.getActiveTransaction():
                    App.closeActiveTransaction(True)
            except Exception as _fw_err:
                _fw_log("fwsketch/modifybox.py:drop step", _fw_err)

    def reject(self):
        try:   # the sketch may be gone when the box is closed with its document (window closed)
            self._drop_own_step()
            self.sketch.recompute()
        except Exception as _fw_err:
            _fw_log("fwsketch/modifybox.py:887", _fw_err)
        super().reject()

    def run(self):
        """Show the box beside the pointer and wait; True when the value was kept."""
        for hook in BOX_HOOKS:
            hook(self)
        self.show()
        self._equation_back()
        try:
            shown = "%s" % self.line_edit().text() if self.line_edit() is not None else ""
        except Exception:
            shown = ""
        clear_of_dimension(self, shown)
        self.raise_()
        self.activateWindow()
        self.value.setFocus()
        self._equation_back()
        self.select_number()
        # the window's activation can come after this and put the caret back (Windows, a box after the
        # first): select the whole value again once it is up, unless something was typed already
        opened = self.line_edit().text() if self.line_edit() is not None else None

        def again():
            self._equation_back()
            edit = self.line_edit()
            if edit is not None and self.isVisible() and edit.text() == opened and not edit.hasSelectedText():
                self.select_number()
        for ms in (0, 80, 250):
            QtCore.QTimer.singleShot(ms, again)
        self.exec()
        return self.success
