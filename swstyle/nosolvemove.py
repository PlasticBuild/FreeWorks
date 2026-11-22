# SPDX-License-Identifier: LGPL-2.1-or-later
""










import FreeCAD as App
import FreeCADGui as Gui

from . import overridedrag

PARAMS = overridedrag.PARAMS
KEY = "NoSolveMove"
COMMAND = "SWStyle_NoSolveMove"
TRANSACTION = "No Solve Move"


def on():
    return App.ParamGet(PARAMS).GetBool(KEY, False)


def held(sketch, geo):
    """The active relations and dimensions on geo."""
    out = []
    for i, c in enumerate(sketch.Constraints):
        if geo in (c.First, c.Second, c.Third) and getattr(c, "IsActive", True):
            out.append(i)
    return out


def release(sketch, indices):
    for i in indices:
        sketch.setActive(i, False)
    sketch.solve()


def restore(sketch, indices, geo=None):
    """Switches the relations on again and solves: the moved entity geo stays where it was let go
    and what is tied to it follows, unless its own relations pull it back."""
    import Sketcher
    pin = None
    if geo is not None:
        pin = sketch.addConstraint(Sketcher.Constraint("Block", geo))
    for i in indices:
        sketch.setActive(i, True)
    solved = sketch.solve() == 0 and not list(sketch.ConflictingConstraints)
    if pin is not None:
        sketch.delConstraint(pin)
        if not solved:
            # its own relations hold it elsewhere: the plain solve puts it back where they say
            sketch.solve()
    sketch.solve()


class _Filter(overridedrag._Filter):
    instance = None

    def _entity(self, widget):
        if not on():
            return None
        return self._under(widget)

    def _start(self, widget, pos):
        _w, _p, sketch, geo, gpos = self.held
        self.held = None
        sketch.Document.openTransaction(TRANSACTION)
        try:
            freed = held(sketch, geo)
            release(sketch, freed)
            self.drag = (sketch, geo, gpos, freed, overridedrag.local(sketch, widget, _p))
        except BaseException:
            try:
                sketch.Document.abortTransaction()
            except Exception:
                pass
            raise
        self._move(widget, pos)

    def _finish(self):
        sketch, _geo, _gpos, freed, _last = self.drag
        self.drag = None
        try:
            restore(sketch, freed, _geo)
            sketch.recompute()
        finally:
            sketch.Document.commitTransaction()


class _Toggle(overridedrag._Toggle):
    def GetResources(self):
        return {"MenuText": "No Solve Move", "Pixmap": "Sketcher_Toggle_Constraint_Driving",
                "ToolTip": "Dragging a sketch entity moves it alone; its relations are solved when it is let go",
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
