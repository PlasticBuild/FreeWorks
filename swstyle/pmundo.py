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

Qt = QtCore.Qt
DONE = "swundo"
BUTTON_TITLES = ("Fillet", "FilletXpert", "Draft", "DraftXpert")

_undo, _redo = [], []
_busy = [False]
_watchers = {}


def clear():
    del _undo[:]
    del _redo[:]
    _watchers.clear()
    _refresh()


def depth():
    return len(_undo), len(_redo)


def can_undo():
    return bool(_undo)


def can_redo():
    return bool(_redo)


# --------------------------------------------------------------------------- values
def _alive(w):
    try:
        w.objectName()
        return True
    except RuntimeError as _fw_err:
        _fw_log("pmundo.py:61", _fw_err)
        return False


def _get(w):
    if isinstance(w, QtWidgets.QAbstractSpinBox):
        if w.property("rawValue") is not None:
            return w.property("rawValue")
        if isinstance(w, (QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)):
            return w.value()        # a plain field: its text "10.00mm" set back is not read again
        return w.text()
    if isinstance(w, QtWidgets.QLineEdit):
        return w.text()
    if isinstance(w, QtWidgets.QComboBox):
        return w.currentIndex()
    if isinstance(w, QtWidgets.QAbstractButton):
        return w.isChecked()
    return None


def _set(w, value):
    _busy[0] = True
    try:
        if isinstance(w, QtWidgets.QAbstractSpinBox):
            if w.property("rawValue") is not None:
                w.setProperty("rawValue", value)
            elif isinstance(w, (QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)) and isinstance(value, (int, float)):
                w.setValue(value)
            else:
                w.lineEdit().setText(str(value))
            try:
                w.editingFinished.emit()
            except Exception as _fw_err:
                _fw_log("pmundo.py:92", _fw_err)
        elif isinstance(w, QtWidgets.QLineEdit):
            w.setText(value)
            w.editingFinished.emit()
        elif isinstance(w, QtWidgets.QComboBox):
            w.setCurrentIndex(value)
        elif isinstance(w, QtWidgets.QAbstractButton):
            w.setChecked(value)
    finally:
        _busy[0] = False


class _Watch(QtCore.QObject):
    """One field: remembers its value and records a change as an undo step."""

    def __init__(self, w):
        super().__init__(w)
        self.w = w
        self.last = _get(w)
        if isinstance(w, QtWidgets.QAbstractSpinBox) or isinstance(w, QtWidgets.QLineEdit):
            w.editingFinished.connect(self.changed)
            if isinstance(w, QtWidgets.QAbstractSpinBox):
                w.installEventFilter(self)       # the arrows and the wheel change it without editingFinished
        elif isinstance(w, QtWidgets.QComboBox):
            w.currentIndexChanged.connect(self.changed)
        elif isinstance(w, QtWidgets.QAbstractButton):
            w.toggled.connect(self.changed)

    def eventFilter(self, watched, event):
        if isinstance(event, QtCore.QEvent) and event.type() in (QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.Wheel):
            QtCore.QTimer.singleShot(0, self.changed)
        return False

    def changed(self, *args):
        if _busy[0] or not _alive(self.w):
            return
        if isinstance(self.w, (QtWidgets.QComboBox, QtWidgets.QAbstractButton)) and \
                not (self.w.hasFocus() or self.w.underMouse()):
            self.last = _get(self.w)     # the page set it itself: not a step of the user's
            return
        now = _get(self.w)
        if now == self.last:
            return
        _undo.append(("value", self.w, self.last, now))
        del _redo[:]
        self.last = now
        _refresh()


def install(view):
    """Watch the page's fields (called from the PropertyManager dressing loop)."""
    for w in view.findChildren(QtWidgets.QWidget):
        try:
            if w.property(DONE) or not w.isVisible():
                continue
            if not isinstance(w, (QtWidgets.QAbstractSpinBox, QtWidgets.QLineEdit, QtWidgets.QComboBox,
                                  QtWidgets.QCheckBox, QtWidgets.QRadioButton)):
                continue
            if isinstance(w, QtWidgets.QLineEdit) and isinstance(w.parentWidget(), (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
                continue
            if w.objectName() in ("SWStyle_PMTitle",) or w.objectName().startswith("SWHelp"):
                continue
            w.setProperty(DONE, True)
            _watchers[id(w)] = _Watch(w)
        except RuntimeError:
            continue


# --------------------------------------------------------------------------- picks
class _Picks:
    def addSelection(self, doc, name, sub, pnt):
        if _busy[0] or not _open():
            return
        _undo.append(("pick", doc, name, sub))
        del _redo[:]
        _refresh()

    def removeSelection(self, doc, name, sub):
        pass

    def clearSelection(self, doc):
        pass


def _open():
    try:
        from . import pmconfirm
        return pmconfirm.open()
    except Exception as _fw_err:
        _fw_log("pmundo.py:183", _fw_err)
        return False


def _pick(entry, add):
    _, doc, name, sub = entry
    _busy[0] = True
    try:
        if add:
            Gui.Selection.addSelection(doc, name, sub)
        elif Gui.Selection.isSelected(App.getDocument(doc).getObject(name), sub):
            Gui.Selection.removeSelection(doc, name, sub)     # FreeCAD's pages read the selection
        else:
            # the page took the pick into its own list and cleared the selection (Fillet, Delete
            # Face...): picked again, it takes the item out
            Gui.Selection.addSelection(doc, name, sub)
    except Exception as _fw_err:
        _fw_log("pmundo.py:197", _fw_err)
    finally:
        _busy[0] = False


def undo():
    if not _undo:
        return False
    entry = _undo.pop()
    if entry[0] == "value":
        _, w, old, new = entry
        if _alive(w):
            _set(w, old)
            watch = _watchers.get(id(w))
            if watch is not None:
                watch.last = old
    else:
        _pick(entry, False)
    _redo.append(entry)
    _refresh()
    return True


def redo():
    if not _redo:
        return False
    entry = _redo.pop()
    if entry[0] == "value":
        _, w, old, new = entry
        if _alive(w):
            _set(w, new)
            watch = _watchers.get(id(w))
            if watch is not None:
                watch.last = new
    else:
        _pick(entry, True)
    _undo.append(entry)
    _refresh()
    return True


# --------------------------------------------------------------------------- keys and buttons
_buttons = []


def _refresh():
    for undo_b, redo_b in list(_buttons):
        try:
            # shown on the pages that have them (the header's fw_shows) once there is a step to take back or
            # forward: never a greyed button (no dead controls)
            shows = bool(undo_b.property("fw_shows"))
            undo_b.setEnabled(True)
            redo_b.setEnabled(True)
            undo_b.setVisible(shows and bool(_undo))
            redo_b.setVisible(shows and bool(_redo))
        except RuntimeError:
            _buttons.remove((undo_b, redo_b))


def register_buttons(undo_b, redo_b):
    _buttons.append((undo_b, redo_b))
    undo_b.clicked.connect(undo)
    redo_b.clicked.connect(redo)
    _refresh()


def shows_buttons(title):
    return any(title == t or title.startswith(t) for t in BUTTON_TITLES)


class Keys(QtCore.QObject):
    """Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z while a page is open: the page's own undo, not the document's."""

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent) or event.type() not in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride):
            return False
        key, mods = event.key(), event.modifiers()
        if not (mods & Qt.ControlModifier) or key not in (Qt.Key_Z, Qt.Key_Y):
            return False
        if mods & Qt.AltModifier or not _open():
            return False
        if event.type() == QtCore.QEvent.ShortcutOverride:
            event.accept()          # keeps Std_Undo's shortcut off; the KeyPress follows
            return True
        if key == Qt.Key_Y or (mods & Qt.ShiftModifier):
            redo()
        else:
            undo()
        return True


_keys = None
_picks = None


def start():
    global _keys, _picks
    if _keys is None:
        _keys = Keys()
        from . import pmevents
        pmevents.hook("pm.undo", (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride), _keys.eventFilter)      # pkg98
    if _picks is None:
        _picks = _Picks()
        Gui.Selection.addObserver(_picks)
