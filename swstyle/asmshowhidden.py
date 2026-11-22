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

from . import asmcore as ac

Qt = QtCore.Qt
EXIT_TEXT = "Exit Show-Hidden"
EDIT_PROMPT = "Select a component to edit."
SHOW_PROMPT = "Click the hidden components to show. Exit Show-Hidden when done."
MODE = {"show": None, "edit": None}


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 0 if text else 1)
    except Exception as _fw_err:
        _fw_log("asmshowhidden.py:41", _fw_err)


def _view_widget(doc):
    try:
        from . import asmbom
        return asmbom._view_widget(doc)
    except Exception:
        return None


def _picked(asm):
    try:
        from . import asmtools
        return asmtools._picked_components(asm)
    except Exception:
        return []


class _Esc(QtCore.QObject):
    def __init__(self, cancel):
        super().__init__()
        self.cancel = cancel

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        try:
            if event.type() == QtCore.QEvent.KeyPress and event.key() == Qt.Key_Escape:
                QtCore.QTimer.singleShot(0, self.cancel)
                return True
        except Exception as _fw_err:
            _fw_log("asmshowhidden.py:73", _fw_err)
        return False


def _app_filter(name, types, flt, on=True):
    ""
    try:
        from . import events
        if on:
            events.register(name, types, flt.eventFilter)
        else:
            events.unregister(name)
        return True
    except ImportError:
        app = QtWidgets.QApplication.instance()
        (app.installEventFilter if on else app.removeEventFilter)(flt)
        return False


# ============================================================================= Show Hidden Components
class ShowHidden:
    def __init__(self, asm):
        self.asm, self.doc = asm, asm.Document
        self.comps = list(ac.components(asm))
        self.before = {c.Name: bool(c.Visibility) for c in self.comps}
        self.to_show = []
        self.button = None
        self.esc = _Esc(self.exit)

    def _mode_look(self):
        for c in self.comps:
            try:
                c.Visibility = (not self.before[c.Name]) and c not in self.to_show   # the hidden ones come up
            except Exception as _fw_err:
                _fw_log("asmshowhidden look", _fw_err)

    def _real_look(self):
        for c in self.comps:
            try:
                c.Visibility = self.before[c.Name]
            except Exception as _fw_err:
                _fw_log("asmshowhidden real", _fw_err)

    # document observer: a save while the mode is on writes the assembly as it really is (it wrote the shown
    # components hidden and the hidden ones shown, vd116, 11-20)
    def slotStartSaveDocument(self, doc, _name=""):
        if doc is self.doc and MODE["show"] is self:
            self._real_look()

    def slotFinishSaveDocument(self, doc, _name=""):
        if doc is self.doc and MODE["show"] is self:
            self._mode_look()

    def enter(self):
        self._mode_look()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        try:
            App.addDocumentObserver(self)
        except Exception as _fw_err:
            _fw_log("asmshowhidden observer", _fw_err)
        _app_filter("asm.showhidden", (QtCore.QEvent.KeyPress,), self.esc)
        parent = _view_widget(self.doc)
        if parent is not None:
            b = QtWidgets.QPushButton(EXIT_TEXT, parent)
            b.setObjectName("FW_ExitShowHidden")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(self.exit)
            b.adjustSize()
            b.setAutoFillBackground(True)
            b.move(max(8, (parent.width() - b.width()) // 2), 44)     # under the Heads-up View toolbar
            b.show()
            b.raise_()
            self.button = b
        _status(SHOW_PROMPT)
        return self

    # selection observer
    def addSelection(self, doc, obj, sub, pnt):
        QtCore.QTimer.singleShot(0, self._take)

    def removeSelection(self, *a):
        pass

    def setSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def _take(self):
        if MODE["show"] is not self:
            return
        for c in _picked(self.asm):
            if not self.before.get(c.Name, True) and c not in self.to_show:
                self.pick(c)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("asmshowhidden.py:145", _fw_err)

    def pick(self, comp):
        """A hidden component clicked: it leaves this view and is shown on exit."""
        if comp in self.to_show or self.before.get(comp.Name, True):
            return
        self.to_show.append(comp)
        comp.Visibility = False

    def exit(self):
        if MODE["show"] is not self:
            return []
        MODE["show"] = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmshowhidden.py:161", _fw_err)
        try:
            _app_filter("asm.showhidden", (), self.esc, False)
        except Exception as _fw_err:
            _fw_log("asmshowhidden.py:165", _fw_err)
        if self.button is not None:
            try:
                self.button.hide()
                self.button.deleteLater()
            except RuntimeError as _fw_err:
                _fw_log("asmshowhidden.py:171", _fw_err)
        _status("")
        try:
            App.removeDocumentObserver(self)
        except Exception as _fw_err:
            _fw_log("asmshowhidden observer off", _fw_err)
        names = {c.Name for c in self.to_show}
        # back to the assembly as it was, outside the Undo step: Undo then only hides the picked ones again
        # (it brought back the mode's look, every shown component hidden, vd116, 11-20)
        self._real_look()
        try:
            self.doc.openTransaction("Show Hidden Components")
            try:
                for c in self.comps:
                    try:
                        if c.Name in names and not self.before[c.Name]:
                            c.Visibility = True
                    except Exception as _fw_err:
                        _fw_log("asmshowhidden.py:180", _fw_err)
            except BaseException:
                try:
                    self.doc.abortTransaction()
                except Exception:
                    pass
                raise
            self.doc.commitTransaction()
        except Exception as _fw_err:
            _fw_log("asmshowhidden.py:183", _fw_err)
        _refresh()
        return list(self.to_show)


def show_hidden(asm):
    """The command: enters the mode, or leaves it when it is on."""
    cur = MODE["show"]
    if cur is not None:
        cur.exit()
        return None
    cancel_edit_pick()
    MODE["show"] = mode = ShowHidden(asm)
    return mode.enter()


def active():
    return MODE["show"]


# ============================================================================= Edit Component, tool first
class EditPick:
    def __init__(self, asm):
        self.asm = asm
        self.esc = _Esc(self.cancel)

    def start(self):
        Gui.Selection.addObserver(self)
        _app_filter("asm.editpick", (QtCore.QEvent.KeyPress,), self.esc)
        _status(EDIT_PROMPT)
        return self

    def addSelection(self, doc, obj, sub, pnt):
        QtCore.QTimer.singleShot(0, self._take)

    def removeSelection(self, *a):
        pass

    def setSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def _take(self):
        if MODE["edit"] is not self:
            return
        from . import asmtools
        if asmtools.editing() is not None:      # Edit Component ran meanwhile: it has the pick
            self.cancel()
            return
        comps = _picked(self.asm)
        if not comps:
            return
        self.cancel()
        asmtools.edit_component(self.asm, comps[0])

    def cancel(self):
        if MODE["edit"] is not self:
            return
        MODE["edit"] = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmshowhidden.py:247", _fw_err)
        try:
            _app_filter("asm.editpick", (), self.esc, False)
        except Exception as _fw_err:
            _fw_log("asmshowhidden.py:251", _fw_err)
        _status("")


def edit_pick(asm):
    if MODE["edit"] is not None:
        MODE["edit"].cancel()
        return None
    MODE["edit"] = p = EditPick(asm)
    return p.start()


def cancel_edit_pick():
    if MODE["edit"] is not None:
        MODE["edit"].cancel()


def _refresh():
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmshowhidden.py:273", _fw_err)
