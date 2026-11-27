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

import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

ROW = ("Turn off Automatic Solve Mode and Undo when sketch contains more than", "2000 sketch entities")
SKETCHER = "User parameter:BaseApp/Preferences/Mod/Sketcher"
_watcher = None


COUNT = "sketch entities"


def limit():
    """The entity count over which Automatic Solve and Undo go off, or None when the box is cleared."""
    try:
        from .. import optionspages
        if not optionspages.stored("Sketch", ROW[0], True):
            return None
        return max(1, int(optionspages.stored("Sketch", COUNT, 2000)))
    except Exception as _fw_err:
        _fw_log("fwsketch/bigsketch.py: limit", _fw_err)
    return 2000


def _edited():
    try:
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc is not None else None
        obj = getattr(vp, "Object", None)
        if obj is not None and obj.TypeId == "Sketcher::SketchObject":
            return obj
    except Exception as _fw_err:
        _fw_log("fwsketch/bigsketch.py:48", _fw_err)
    return None


class Watcher(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.sketch = None
        self.saved = None        # (AutoRecompute, document, UndoMode) to put back
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def tick(self):
        try:
            sk = _edited()
            if sk is self.sketch:
                return
            self.restore()
            self.sketch = sk
            n = limit()
            if sk is not None and n is not None and len(sk.Geometry) > n:
                self.turn_off(sk)
        except Exception as error:
            App.Console.PrintLog("FreeCAD big sketch: %s\n" % error)

    def turn_off(self, sk):
        p = App.ParamGet(SKETCHER)
        doc = sk.Document
        self.saved = (p.GetBool("AutoRecompute", False), doc, doc.UndoMode)
        p.SetBool("AutoRecompute", False)
        doc.UndoMode = 0
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "Automatic Solve and Undo are off: this sketch has more than %d entities "
                "(Options > Sketch)" % limit(), 8000)
        except Exception as _fw_err:
            _fw_log("fwsketch/bigsketch.py:85", _fw_err)

    def restore(self):
        if self.saved is None:
            return
        auto, doc, undo = self.saved
        self.saved = None
        App.ParamGet(SKETCHER).SetBool("AutoRecompute", auto)
        try:
            doc.UndoMode = undo
        except Exception as _fw_err:
            _fw_log("fwsketch/bigsketch.py:96", _fw_err)

    def stop(self):
        self.timer.stop()
        self.restore()


def start():
    global _watcher
    if _watcher is None:
        _watcher = Watcher()
    return _watcher


def stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
        _watcher = None
