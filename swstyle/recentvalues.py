# SPDX-License-Identifier: LGPL-2.1-or-later
""













import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import events, paths

PARAM = "RecentValuesList"     # addon parameter (default on)
GROUP = "RecentValues"         # parameter group under the addon's, one string per field name
KEEP = 8                       # values kept per field
DONE = "swstyle_recentvalues"
TIP = "Enter a value or start with = to create an equation"
SPIN_CLASSES = ("Gui::QuantitySpinBox",)

_watcher = None


def enabled():
    return paths.params().GetBool(PARAM, True)


def _store():
    return paths.params().GetGroup(GROUP)


def _compact(text):
    ""
    return " ".join(text.split()).replace(" ", "")


def _with_unit(text, shown):
    """A plain number typed into a field gets the unit the field shows ('32' in '10.00 mm' -> '32mm')."""
    text = _compact(text)
    try:
        float(text.replace(",", "."))
    except ValueError:
        return text
    unit = "".join(ch for ch in shown if not (ch.isdigit() or ch in ".,-+ ")) if shown else ""
    return text + unit.strip()


def values(key):
    text = _store().GetString(key, "")
    return [v for v in text.split(";") if v]


def remember(key, text):
    text = _compact(text)
    if not key or not text or text.startswith("="):
        return
    kept = [text] + [v for v in values(key) if v != text]
    _store().SetString(key, ";".join(kept[:KEEP]))


def _in_task_panel(widget):
    parent = widget.parentWidget()
    while parent is not None:
        if parent.inherits("Gui::TaskView::TaskView"):
            return True
        parent = parent.parentWidget()
    return False


class _List(QtWidgets.QListWidget):
    """The drop-down under the field: a plain list, picked by click or Enter."""

    def __init__(self, field):
        super().__init__(field.spin.window())
        self.field = field
        self.setWindowFlags(QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.itemClicked.connect(lambda item: field.pick(item.text()))


class Field(QtCore.QObject):
    """One number field's list and memory."""

    def __init__(self, spin):
        super().__init__(spin)
        self.spin = spin
        self.edit = spin.lineEdit() if hasattr(spin, "lineEdit") else spin.findChild(QtWidgets.QLineEdit)
        self.key = spin.objectName()
        self.start = self.edit.text() if self.edit is not None else ""
        self.typed = False
        self.popup = None
        if self.edit is None or not self.key:
            return
        if not spin.toolTip():
            spin.setToolTip(TIP)
        self.edit.textEdited.connect(self._edited)
        spin.editingFinished.connect(self._finished)
        self.edit.installEventFilter(self)
        spin.installEventFilter(self)          # the spin box sees the arrow keys first

    # -- the list
    def shown(self):
        return self.popup is not None and self.popup.isVisible()

    def items(self):
        return [self.popup.item(i).text() for i in range(self.popup.count())] if self.popup is not None else []

    def show_list(self, prefix=""):
        if not enabled():
            return
        found = [v for v in values(self.key) if v.lower().startswith(_compact(prefix).lower())]
        if not found:
            self.hide_list()
            return
        if self.popup is None:
            self.popup = _List(self)
        self.popup.clear()
        self.popup.addItems(found)
        row = self.popup.sizeHintForRow(0) if found else 18
        self.popup.setFixedSize(self.spin.width(), row * len(found) + 2 * self.popup.frameWidth() + 2)
        self.popup.move(self.spin.mapToGlobal(QtCore.QPoint(0, self.spin.height())))
        self.popup.setCurrentRow(-1)
        self.popup.show()
        self.popup.raise_()

    def hide_list(self):
        if self.popup is not None:
            self.popup.hide()

    def pick(self, text):
        self.hide_list()
        self.edit.setText(text)
        self.typed = True
        # Enter makes FreeCAD's spin box take the text, as when typed
        for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(self.edit, QtGui.QKeyEvent(kind, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier))
        self.edit.setFocus()

    # -- signals
    def _edited(self, text):
        self.typed = True
        if text.startswith("="):
            self.hide_list()
            return
        self.show_list(text.strip())

    def _finished(self):
        self.hide_list()
        if self.typed and self.edit.text() != self.start:
            unit = self.spin.property("unit") or self.start
            remember(self.key, _with_unit(self.edit.text(), unit if isinstance(unit, str) else self.start))
            self.start = self.edit.text()
        self.typed = False

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        kind = event.type()
        if kind == QtCore.QEvent.KeyPress and self.shown():
            key = event.key()
            if key in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Up):
                row = self.popup.currentRow() + (1 if key == QtCore.Qt.Key_Down else -1)
                self.popup.setCurrentRow(max(0, min(self.popup.count() - 1, row)))
                return True
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and self.popup.currentItem() is not None:
                self.pick(self.popup.currentItem().text())
                return True
            if key == QtCore.Qt.Key_Escape:
                self.hide_list()
                return True
        elif kind == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Down \
                and event.modifiers() & QtCore.Qt.AltModifier:
            self.show_list("")
            return True
        elif kind in (QtCore.QEvent.FocusOut, QtCore.QEvent.Hide):
            QtCore.QTimer.singleShot(150, self.hide_list)
        return False


class Watcher(QtCore.QObject):
    """Gives each number field of a task panel its list the first time it shows."""

    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.fields = 0            # fields set up, for checks
        events.register("recentvalues", (QtCore.QEvent.Show,), self.eventFilter)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QAbstractSpinBox):
            try:
                if any(obj.inherits(c) for c in SPIN_CLASSES) and not obj.property(DONE) \
                        and _in_task_panel(obj):
                    obj.setProperty(DONE, True)
                    Field(obj)             # a child of the field: lives and dies with it
                    self.fields += 1
            except Exception as error:
                App.Console.PrintLog("FreeCAD: recent values: %s\n" % error)
        return False


def field_of(spin):
    """The Field object of a number field, or None."""
    for child in spin.children():
        if isinstance(child, Field):
            return child
    return None


def register():
    global _watcher
    if _watcher is None:
        _watcher = Watcher()
    return _watcher
