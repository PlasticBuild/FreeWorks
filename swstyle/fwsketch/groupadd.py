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

try:
    from PySide import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtWidgets

STEP = "Add to Relation Group"
_NAME = re.compile(r"FWGroup_(C?)(\d+)_(\d+)$")


def members(sketch, key):
    """(constraint indexes, geo ids) of group key ('3' or 'C3')."""
    idx, geos = [], []
    for i, c in enumerate(sketch.Constraints):
        m = _NAME.match(c.Name or "")
        if m and m.group(1) + m.group(2) == key:
            idx.append(i)
            for g in (c.First, c.Second):
                if g is not None and g >= 0 and g not in geos:
                    geos.append(g)
    return idx, geos


def join(sketch, geo, constraint):
    import Sketcher
    try:
        c = sketch.Constraints[constraint]
    except Exception:
        return False
    m = _NAME.match(c.Name or "")
    if not m:
        return False
    key = m.group(1) + m.group(2)
    idx, geos = members(sketch, key)
    if geo in geos or not geos:
        return False
    first = geos[0]
    kind = c.Type
    adds = []
    if m.group(1) == "C":             # Coradial: Coincident centres + Equal
        adds = [Sketcher.Constraint("Coincident", geo, 3, first, 3), Sketcher.Constraint("Equal", geo, first)]
    elif kind == "Parallel":
        adds = [Sketcher.Constraint("Parallel", geo, first)]
    elif kind == "Equal":
        adds = [Sketcher.Constraint("Equal", geo, first)]
    elif kind == "Tangent":
        adds = [Sketcher.Constraint("Tangent", geo, first)]
    else:
        return False
    used = {int(_NAME.match(sketch.Constraints[i].Name).group(3)) for i in idx}
    j = max(used) + 1 if used else 0
    doc = sketch.Document
    doc.openTransaction(STEP)
    try:
        for con in adds:
            n = sketch.addConstraint(con)
            sketch.renameConstraint(n, "FWGroup_%s%s_%d" % (m.group(1), m.group(2), j))
            j += 1
        sketch.solve()
        doc.recompute()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (STEP, error))
        return False
    doc.commitTransaction()
    return True


def _edited():
    try:
        vp = Gui.ActiveDocument.getInEdit()
        o = getattr(vp, "Object", None)
        return o if o is not None and o.isDerivedFrom("Sketcher::SketchObject") else None
    except Exception:
        return None


class _Watcher:
    def __init__(self):
        Gui.Selection.addObserver(self)
        self.busy = False

    def stop(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("fwsketch/groupadd.py:111", _fw_err)

    def addSelection(self, doc, obj, sub, pnt):
        sketch = _edited()
        if sketch is None:
            return
        if obj != sketch.Name:
            # a sketch in a Body is picked through it: Body + "Sketch.Constraint3"
            parts = sub.split(".")
            if len(parts) < 2 or parts[-2] != sketch.Name:
                return
        sub = sub.split(".")[-1]
        if self.busy or not sub.startswith("Constraint"):
            return
        if not (QtWidgets.QApplication.queryKeyboardModifiers() & QtCore.Qt.ControlModifier):
            return
        try:
            ci = int(sub[10:]) - 1
        except ValueError:
            return
        if not _NAME.match(sketch.Constraints[ci].Name or "") if 0 <= ci < len(sketch.Constraints) else True:
            return
        edges = []
        for s in Gui.Selection.getSelectionEx():
            if s.Object is not sketch:
                continue
            for name in (n.split(".")[-1] for n in s.SubElementNames):
                if name.startswith("Edge"):
                    edges.append(int(name[4:]) - 1)
        if not edges:
            return
        QtCore.QTimer.singleShot(0, lambda: self._run(sketch, edges, ci))

    def _run(self, sketch, edges, ci):
        self.busy = True
        try:
            done = [g for g in edges if join(sketch, g, ci)]
            if done:
                Gui.Selection.clearSelection()
        finally:
            self.busy = False


_watcher = None


def start():
    global _watcher
    if _watcher is None:
        _watcher = _Watcher()
    return _watcher


def stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
        _watcher = None
