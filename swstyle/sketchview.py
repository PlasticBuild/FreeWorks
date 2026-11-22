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
from PySide import QtCore

from . import contextbar, relationspm

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchView"
KINDS = {"SWStyle_ViewSketchRelations": ("Relations", "Sketch Relations",
                                          "Shows or hides the relation glyphs of the sketch being edited"),
         "SWStyle_ViewSketchDimensions": ("Dimensions", "Sketch Dimensions",
                                           "Shows or hides the dimensions of the sketch being edited")}


def shown(kind):
    return App.ParamGet(PARAMS).GetBool(kind, True)


def _is_dimension(c):
    return c.Type in relationspm.DIMENSIONS


def _ids(sketch, kind, start=0):
    want_dims = kind == "Dimensions"
    return [i for i, c in enumerate(sketch.Constraints) if i >= start and c.Type not in ("Block", "InternalAlignment")
            and _is_dimension(c) == want_dims]


def apply(sketch, kind, visible, start=0):
    ids = _ids(sketch, kind, start)
    if ids:
        try:
            sketch.setVisibility(ids, bool(visible))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s: %s\n" % (kind, error))


class _Watch(QtCore.QObject):
    """Keeps new relations or dimensions hidden while their toggle is off."""

    def __init__(self):
        super().__init__()
        self.key = None
        self.count = 0
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def tick(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            self.key = None
            return
        key = (sketch.Document.Name, sketch.Name)
        n = len(sketch.Constraints)
        start = None
        if key != self.key:
            self.key, start = key, 0          # a sketch opened: bring it in line
        elif n > self.count:
            start = self.count                # added since the last look
        self.count = n
        if start is None:
            return
        for kind in ("Relations", "Dimensions"):
            if not shown(kind):
                apply(sketch, kind, False, start)


class ViewToggleCommand:
    def __init__(self, name):
        self.name = name
        self.kind, self.menu, self.tip = KINDS[name]

    def GetResources(self):
        return {"Pixmap": "Constraint_Horizontal" if self.kind == "Relations" else "Constraint_Length",
                "MenuText": self.menu, "ToolTip": self.tip, "CmdType": "ForEdit",
                "Checkable": shown(self.kind)}

    def IsActive(self):
        on = shown(self.kind)
        try:
            actions = Gui.Command.get(self.name).getAction()
        except Exception:
            actions = []
        for action in actions:
            if action.isChecked() != on:
                blocked = action.blockSignals(True)
                action.setChecked(on)
                action.blockSignals(blocked)
        return App.ActiveDocument is not None

    def Activated(self, checked=0):
        try:
            has_action = bool(Gui.Command.get(self.name).getAction())
        except Exception:
            has_action = False
        on = bool(checked) if has_action else not shown(self.kind)
        App.ParamGet(PARAMS).SetBool(self.kind, on)
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            apply(sketch, self.kind, on)
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "%s %s." % (self.menu, "shown" if on else "hidden"), 5000)
        except Exception as _fw_err:
            _fw_log("sketchview.py:130", _fw_err)


_watch = None


def register():
    global _watch
    for name in KINDS:
        try:
            if name not in Gui.listCommands():
                Gui.addCommand(name, ViewToggleCommand(name))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (name, error))
    if _watch is None:
        _watch = _Watch()
