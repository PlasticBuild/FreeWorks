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

from . import contextbar

COMMAND = "SWStyle_AlignOrdinate"


def _points(sketch, c):
    return (c.First, c.FirstPos), (c.Second, c.SecondPos)


def _row(sketch, c):
    """Where dimension c is drawn across its direction: a y for DistanceX, an x for DistanceY."""
    (g1, p1), (g2, p2) = _points(sketch, c)
    a, b = sketch.getPoint(g1, p1), sketch.getPoint(g2, p2)
    if c.Type == "DistanceX":
        s = 1.0 if b.x - a.x >= 0 else -1.0
        return b.y + s * c.LabelDistance
    s = 1.0 if b.y - a.y >= 0 else -1.0
    return b.x - s * c.LabelDistance


def _distance_for(sketch, c, row):
    (g1, p1), (g2, p2) = _points(sketch, c)
    a, b = sketch.getPoint(g1, p1), sketch.getPoint(g2, p2)
    if c.Type == "DistanceX":
        s = 1.0 if b.x - a.x >= 0 else -1.0
        return (row - b.y) / s
    s = 1.0 if b.y - a.y >= 0 else -1.0
    return (b.x - row) / s


def group(sketch, index):
    """The dimensions of index's ordinate group (index included)."""
    cons = sketch.Constraints
    c = cons[index]
    if c.Type not in ("DistanceX", "DistanceY") or c.Second is None or c.Second < -2000:
        return [index]
    same = [i for i, k in enumerate(cons) if k.Type == c.Type and k.Second is not None and k.Second > -2000]
    ends = _points(sketch, c)

    def members(pt):
        return [i for i in same if pt in _points(sketch, cons[i])]
    zero = max(ends, key=lambda pt: len(members(pt)))
    return members(zero)


def align(sketch, index):
    """Puts every dimension of index's group on index's row; how many moved."""
    row = _row(sketch, sketch.Constraints[index])
    moved = 0
    for i in group(sketch, index):
        if i == index:
            continue
        want = _distance_for(sketch, sketch.Constraints[i], row)
        if abs(want - sketch.Constraints[i].LabelDistance) > 1e-9:
            sketch.setLabelDistance(i, want)
            moved += 1
    return moved


def _picked_dimension(sketch):
    for sel in Gui.Selection.getSelectionEx():
        if getattr(sel.Object, "Name", None) != sketch.Name:
            continue
        for sub in sel.SubElementNames:
            name = sub.split(".")[-1]
            if name.startswith("Constraint"):
                try:
                    return int(name[len("Constraint"):]) - 1
                except ValueError as _fw_err:
                    _fw_log("ordinatealign.py:92", _fw_err)
    return None


class AlignOrdinateCommand:
    def GetResources(self):
        return {"Pixmap": "Constraint_HorizontalDistance", "MenuText": "Align Ordinate",
                "ToolTip": "Lines up the dimensions of an ordinate group with the one selected",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return
        index = _picked_dimension(sketch)
        if index is None or not 0 <= index < len(sketch.Constraints):
            try:
                Gui.getMainWindow().statusBar().showMessage("Align Ordinate: select an ordinate dimension first.", 6000)
            except Exception as _fw_err:
                _fw_log("ordinatealign.py:114", _fw_err)
            return
        doc = sketch.Document
        doc.openTransaction("Align Ordinate")
        try:
            align(sketch, index)
        finally:
            doc.commitTransaction()
        doc.recompute()


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, AlignOrdinateCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
