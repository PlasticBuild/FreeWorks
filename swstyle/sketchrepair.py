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
import Part
from . import geomkeep

COMMAND = "SWStyle_RepairSketch"
NATIVE = "Sketcher_ValidateSketch"
_dialog = None


def _in_edit():
    gdoc = Gui.ActiveDocument
    try:
        vp = gdoc.getInEdit() if gdoc is not None else None
    except Exception:
        vp = None
    obj = getattr(vp, "Object", None)
    if obj is not None and obj.isDerivedFrom("Sketcher::SketchObject"):
        return obj
    return None


def _ends(g):
    if isinstance(g, (Part.LineSegment, Part.ArcOfCircle, Part.ArcOfEllipse, Part.BSplineCurve,
                      Part.ArcOfParabola, Part.ArcOfHyperbola)):
        try:
            return [(1, g.StartPoint), (2, g.EndPoint)]
        except Exception:
            return []
    return []


def _key(g, gap):
    def r(v):
        return (round(v.x / gap), round(v.y / gap))
    if isinstance(g, Part.LineSegment):
        return ("L",) + tuple(sorted([r(g.StartPoint), r(g.EndPoint)]))
    if isinstance(g, Part.Circle):
        return ("C", r(g.Center), round(g.Radius / gap))
    if isinstance(g, Part.ArcOfCircle):
        return ("A", r(g.Center), round(g.Radius / gap)) + tuple(sorted([r(g.StartPoint), r(g.EndPoint)]))
    if isinstance(g, Part.Point):
        return ("P", r(App.Vector(g.X, g.Y, 0)))
    return None


def _joined(sketch, a, pa, b, pb):
    for c in sketch.Constraints:
        if c.Type == "Coincident" and {(c.First, c.FirstPos), (c.Second, c.SecondPos)} == {(a, pa), (b, pb)}:
            return True
    return False


def _merge_overlapping_lines(sketch, gap):
    ""

    gone = 0
    while True:
        geos = list(sketch.Geometry)
        pair = None
        for i, a in enumerate(geos):
            if not isinstance(a, Part.LineSegment) or sketch.getConstruction(i):
                continue
            d = a.EndPoint - a.StartPoint
            L = d.Length
            if L < gap:
                continue
            u = App.Vector(d).normalize()
            for j in range(i + 1, len(geos)):
                b = geos[j]
                if not isinstance(b, Part.LineSegment) or sketch.getConstruction(j):
                    continue
                off = [((q - a.StartPoint) - u * (q - a.StartPoint).dot(u)).Length for q in (b.StartPoint, b.EndPoint)]
                if max(off) > gap:
                    continue
                t = sorted((q - a.StartPoint).dot(u) for q in (b.StartPoint, b.EndPoint))
                if min(L, t[1]) - max(0.0, t[0]) <= gap:
                    continue        # end to end (or apart): not overlapping
                pair = (i, j, min(0.0, t[0]), max(L, t[1]), u)
                break
            if pair:
                break
        if pair is None:
            return gone
        i, j, t0, t1, u = pair
        a = sketch.Geometry[i]
        start, end = a.StartPoint + u * t0, a.StartPoint + u * t1
        sketch.delGeometry(j)      # j > i: the first line keeps its index and its relations
        g = sketch.Geometry[i]
        if (g.StartPoint - start).Length > gap or (g.EndPoint - end).Length > gap:
            geos = list(geomkeep.read(sketch))
            geos[i] = Part.LineSegment(start, end)
            sketch.Geometry = geos
        gone += 1


def repair(sketch, gap=None):
    """[what was fixed] after Repair Sketch on sketch (the caller opens the undo step)."""
    import Sketcher
    geos = list(sketch.Geometry)
    size = max([1.0] + [abs(v) for g in geos for _p, q in _ends(g) for v in (q.x, q.y)])
    gap = 1e-4 * size if gap is None else gap
    fixed = []
    # entities of no length, then entities lying twice on one another
    gone, seen = [], {}
    short = twice = 0
    for i, g in enumerate(geos):
        if isinstance(g, Part.LineSegment) and (g.EndPoint - g.StartPoint).Length < gap:
            gone.append(i); short += 1
            continue
        k = _key(g, gap)
        if k is None:
            continue
        if k in seen:
            gone.append(i); twice += 1
        else:
            seen[k] = i
    if gone:
        sketch.delGeometries(sorted(gone))
    if short:
        fixed.append("%d entit%s of no length deleted" % (short, "y" if short == 1 else "ies"))
    if twice:
        fixed.append("%d overlapping entit%s deleted" % (twice, "y" if twice == 1 else "ies"))
    merged = _merge_overlapping_lines(sketch, gap)
    if merged:
        fixed.append("%d overlapping line%s merged" % (merged, "" if merged == 1 else "s"))
    # gaps between ends
    geos = list(sketch.Geometry)
    ends = [(i, p, q) for i, g in enumerate(geos) for p, q in _ends(g)]
    closed = 0
    for n, (a, pa, qa) in enumerate(ends):
        for b, pb, qb in ends[n + 1:]:
            if a == b or (qa - qb).Length >= gap or _joined(sketch, a, pa, b, pb):
                continue
            try:
                sketch.addConstraint(Sketcher.Constraint("Coincident", a, pa, b, pb))
                closed += 1
            except Exception as _fw_err:
                _fw_log("sketchrepair.py:158", _fw_err)
    if closed:
        fixed.append("%d gap%s closed" % (closed, "" if closed == 1 else "s"))
    # relations FreeCAD finds redundant or malformed
    try:
        sketch.solve()
        bad = sorted(set(list(sketch.RedundantConstraints) + list(getattr(sketch, "MalformedConstraints", []))),
                     reverse=True)
    except Exception:
        bad = []
    for k in bad:
        try:
            sketch.delConstraint(k - 1)
        except Exception as _fw_err:
            _fw_log("sketchrepair.py:172", _fw_err)
    if bad:
        fixed.append("%d redundant relation%s deleted" % (len(bad), "" if len(bad) == 1 else "s"))
    sketch.solve()
    return fixed


def problems(sketch, show_gap, gap=None):
    ""

    geos = list(sketch.Geometry)
    size = max([1.0] + [abs(v) for g in geos for _p, q in _ends(g) for v in (q.x, q.y)])
    gap = 1e-4 * size if gap is None else gap
    out = []
    ends = [(i, p, q) for i, g in enumerate(geos) for p, q in _ends(g)]
    for n, (a, pa, qa) in enumerate(ends):
        for b, pb, qb in ends[n + 1:]:
            d = (qa - qb).Length
            if a == b or d < gap or d > show_gap or _joined(sketch, a, pa, b, pb):
                continue
            out.append(("Gap of %.4g mm between Edge%d and Edge%d" % (d, a + 1, b + 1), [a, b]))
    try:
        sketch.solve()
        bad = sorted(set(sketch.ConflictingConstraints))
        if bad:
            cons = [sketch.Constraints[k - 1] for k in bad]
            geo = sorted({g for c in cons for g in (c.First, getattr(c, "Second", -2000)) if 0 <= g < len(geos)})
            out.append(("Conflicting relations: " + ", ".join("%s (%s)" % (c.Type, c.Name or "Constraint%d" % k)
                                                               for c, k in zip(cons, bad)), geo))
    except Exception as _fw_err:
        _fw_log("sketchrepair.py:202", _fw_err)
    return out


class RepairDialog(object):
    ""


    def __init__(self, sketch, fixed):
        from PySide import QtCore, QtWidgets
        self.sketch, self.fixed, self.index = sketch, fixed, 0
        mw = Gui.getMainWindow()
        old = mw.findChild(QtWidgets.QDialog, "SWRepairSketch")
        if old is not None:
            old.close()
        d = self.dialog = QtWidgets.QDialog(mw)
        d.setObjectName("SWRepairSketch")
        d.setWindowTitle("Repair Sketch")
        d.setModal(False)
        d.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        lay = QtWidgets.QVBoxLayout(d)
        self.repaired = QtWidgets.QLabel(d)
        self.repaired.setObjectName("SWRepairSketchRepaired")
        self.repaired.setWordWrap(True)
        lay.addWidget(self.repaired)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Show gaps up to:", d))
        self.gap = QtWidgets.QDoubleSpinBox(d)
        self.gap.setObjectName("SWRepairSketchGap")
        self.gap.setDecimals(3); self.gap.setRange(0.0, 1e6); self.gap.setSuffix(" mm")
        self.gap.setValue(1.0)
        self.gap.valueChanged.connect(self.search)
        row.addWidget(self.gap)
        lay.addLayout(row)
        self.count = QtWidgets.QLabel(d)
        self.count.setObjectName("SWRepairSketchCount")
        lay.addWidget(self.count)
        nav = QtWidgets.QHBoxLayout()
        self.prev = QtWidgets.QToolButton(d); self.prev.setArrowType(QtCore.Qt.LeftArrow)
        self.prev.setObjectName("SWRepairSketchPrevious"); self.prev.setToolTip("Previous problem")
        self.next = QtWidgets.QToolButton(d); self.next.setArrowType(QtCore.Qt.RightArrow)
        self.next.setObjectName("SWRepairSketchNext"); self.next.setToolTip("Next problem")
        self.text = QtWidgets.QLabel(d); self.text.setObjectName("SWRepairSketchProblem")
        self.text.setWordWrap(True)
        self.prev.clicked.connect(lambda: self.go(-1))
        self.next.clicked.connect(lambda: self.go(1))
        nav.addWidget(self.prev); nav.addWidget(self.text, 1); nav.addWidget(self.next)
        lay.addLayout(nav)
        close = QtWidgets.QPushButton("Close", d)
        close.setObjectName("SWRepairSketchClose")
        close.clicked.connect(d.close)
        lay.addWidget(close, 0, QtCore.Qt.AlignRight)
        self.repaired.setText("Repaired: " + ("; ".join(fixed) + "." if fixed else "nothing to repair."))
        self.search()
        d.show()

    def search(self, *args):
        self.found = problems(self.sketch, self.gap.value())
        self.index = 0
        n = len(self.found)
        self.count.setText("No problems found." if not n else "%d problem%s found." % (n, "" if n == 1 else "s"))
        for w in (self.prev, self.next):
            w.setEnabled(n > 1)
        self.show_one()

    def go(self, step):
        if self.found:
            self.index = (self.index + step) % len(self.found)
            self.show_one()

    def show_one(self):
        if not self.found:
            self.text.setText("")
            return
        text, geo = self.found[self.index]
        self.text.setText("%d of %d: %s" % (self.index + 1, len(self.found), text))
        try:
            Gui.Selection.clearSelection()
            for g in geo:
                Gui.Selection.addSelection(self.sketch.Document.Name, self.sketch.Name, "Edge%d" % (g + 1))
            Gui.SendMsgToActiveView("ViewSelection")
        except Exception as _fw_err:
            _fw_log("sketchrepair.py:284", _fw_err)


def _say(text, sketch=None, fixed=None):
    App.Console.PrintMessage(text + "\n")
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 8000)
        if sketch is not None:
            return RepairDialog(sketch, fixed or [])
    except Exception as _fw_err:
        _fw_log("sketchrepair.py:294", _fw_err)
    return None


def repair_in_edit():
    sketch = _in_edit()
    if sketch is None:
        return None
    doc = sketch.Document
    doc.openTransaction("Repair Sketch")
    try:
        fixed = repair(sketch)
    except Exception as error:
        doc.abortTransaction()
        _say("Repair Sketch: %s" % error)
        return None
    doc.commitTransaction()
    doc.recompute()
    global _dialog
    _dialog = _say("Repair Sketch: " + ("; ".join(fixed) + "." if fixed else "No problems found."), sketch, fixed)
    return fixed


class RepairCommand:
    def GetResources(self):
        return {"MenuText": "Repair Sketch", "Pixmap": NATIVE,
                "ToolTip": "Finds and repairs sketch errors: gaps, entities of no length, overlapping entities "
                           "and redundant relations."}

    def IsActive(self):
        if _in_edit() is not None:
            return True
        try:
            return bool(Gui.Command.get(NATIVE).isActive())
        except Exception:
            return False

    def Activated(self):
        if _in_edit() is not None:
            repair_in_edit()
        else:
            Gui.runCommand(NATIVE, 0)


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, RepairCommand())
