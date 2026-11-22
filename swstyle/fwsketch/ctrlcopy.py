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

from .toolbase import ViewMath, preselected_subs

TRANSACTION = "Copy Entities"
PREVIEW_COLOR = (0.25, 0.45, 0.95)
KEPT = ("Coincident", "Horizontal", "Vertical", "Parallel", "Perpendicular", "Tangent", "Equal",
        "PointOnObject", "Symmetric")
_watcher = None


def _edited():
    try:
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc is not None else None
        obj = getattr(vp, "Object", None)
        if obj is not None and obj.TypeId == "Sketcher::SketchObject":
            return gdoc, obj
    except Exception as _fw_err:
        _fw_log("fwsketch/ctrlcopy.py:45", _fw_err)
    return None, None


def _edge_index(sub):
    if sub.startswith("Edge"):
        try:
            return int(sub[4:]) - 1
        except ValueError:
            return None
    return None


def picked_edges(sketch):
    out = []
    for s in Gui.Selection.getSelectionEx(sketch.Document.Name):
        if s.Object == sketch or s.ObjectName == sketch.Name:
            for sub in s.SubElementNames:
                i = _edge_index(sub.split(".")[-1])
                if i is not None and i not in out:
                    out.append(i)
    return out


def copy_entities(sketch, geos, delta):
    """Copies of the geos moved by delta (dx, dy), with the relations among them; returns the
    new geo ids. One undo step."""
    doc = sketch.Document
    doc.openTransaction(TRANSACTION)
    try:
        index = {}
        for g in geos:
            c = sketch.Geometry[g].copy()
            c.translate(App.Vector(delta[0], delta[1], 0))
            index[g] = sketch.addGeometry(c, bool(sketch.getConstruction(g)))
        import Sketcher
        new = []
        for c in sketch.Constraints:
            if c.Type not in KEPT:
                continue
            used = [x for x in (c.First, c.Second, c.Third) if x != -2000]
            if not used or any(x not in index for x in used):
                continue
            m = lambda x: index.get(x, x)
            if c.Type in ("Horizontal", "Vertical") and c.Second == -2000:
                new.append(Sketcher.Constraint(c.Type, m(c.First)))
            elif c.Type in ("Parallel", "Perpendicular", "Equal") and int(c.FirstPos) == 0 and int(c.SecondPos) == 0:
                new.append(Sketcher.Constraint(c.Type, m(c.First), m(c.Second)))
            elif c.Type == "Tangent" and int(c.FirstPos) == 0 and int(c.SecondPos) == 0:
                new.append(Sketcher.Constraint(c.Type, m(c.First), m(c.Second)))
            elif c.Type == "PointOnObject":
                new.append(Sketcher.Constraint(c.Type, m(c.First), int(c.FirstPos), m(c.Second)))
            elif c.Type == "Symmetric" and c.Third != -2000:
                new.append(Sketcher.Constraint(c.Type, m(c.First), int(c.FirstPos), m(c.Second), int(c.SecondPos),
                                               m(c.Third), int(c.ThirdPos)))
            elif c.Second != -2000:
                new.append(Sketcher.Constraint(c.Type, m(c.First), int(c.FirstPos), m(c.Second), int(c.SecondPos)))
        if new:
            sketch.addConstraint(new)
        sketch.solve()
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    doc.recompute()
    return [index[g] for g in geos]


class _Session(ViewMath):
    def __init__(self, gdoc, sketch, geos, start, press_global, toggle_sub):
        self.setup_view(gdoc, sketch)
        self.geos, self.start, self.press_global, self.toggle_sub = geos, start, press_global, toggle_sub
        self.dragged = False
        from pivy import coin
        self.root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        col = coin.SoBaseColor()
        col.rgb = PREVIEW_COLOR
        style = coin.SoDrawStyle()
        style.lineWidth = 2 * self.ratio
        self.co = coin.SoCoordinate3()
        self.ls = coin.SoLineSet()
        self.ls.numVertices.setNum(0)
        for n in (pick, light, col, style, self.co, self.ls):
            self.root.addChild(n)
        self.view.getSceneGraph().addChild(self.root)
        self.polys = []
        for g in geos:
            try:
                pts = sketch.Geometry[g].discretize(24)
            except Exception:
                pts = []
            self.polys.append([(p.x, p.y) for p in pts])

    def show(self, delta):
        pts, counts = [], []
        for poly in self.polys:
            if len(poly) < 2:
                continue
            for x, y in poly:
                v = self.matrix.multVec(App.Vector(x + delta[0], y + delta[1], 0))
                pts.append((v.x, v.y, v.z))
            counts.append(len(poly))
        self.co.point.setValues(0, len(pts), pts)
        self.co.point.setNum(len(pts))
        self.ls.numVertices.setValues(0, len(counts), counts)
        self.ls.numVertices.setNum(len(counts))

    def delta(self):
        p, _px = self.pointer()
        if p is None:
            return None
        return (p[0] - self.start[0], p[1] - self.start[1])

    def close(self):
        try:
            self.view.getSceneGraph().removeChild(self.root)
        except Exception as _fw_err:
            _fw_log("fwsketch/ctrlcopy.py:166", _fw_err)


def _global(event):
    try:
        return event.globalPosition().toPoint()
    except AttributeError:
        return event.globalPos()


class Watcher(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.session = None
        self.made = []          # for checks: the copies of the last drop
        from . import appevents
        appevents.listen(self, (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                                QtCore.QEvent.MouseButtonRelease))

    def _filter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if self.session is None:
            if t != QtCore.QEvent.MouseButtonPress or event.button() != QtCore.Qt.LeftButton:
                return False
            if not (event.modifiers() & QtCore.Qt.ControlModifier):
                return False
            return self._press(obj, event)
        s = self.session
        if t == QtCore.QEvent.MouseMove:
            if not s.dragged and (_global(event) - s.press_global).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                s.dragged = True
            if s.dragged:
                d = s.delta()
                if d is not None:
                    s.show(d)
            return True
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            self.session = None
            s.close()
            if s.dragged:
                d = s.delta()
                if d is not None and (abs(d[0]) > 0 or abs(d[1]) > 0):
                    try:
                        self.made = copy_entities(s.sketch, s.geos, d)
                        Gui.Selection.clearSelection()
                        for g in self.made:
                            Gui.Selection.addSelection(s.sketch.Document.Name, s.sketch.Name, "Edge%d" % (g + 1))
                    except Exception as error:
                        App.Console.PrintWarning("FreeCAD Ctrl-drag copy: %s\n" % error)
            else:
                self._toggle(s)
            return True
        return t == QtCore.QEvent.MouseButtonPress

    def eventFilter(self, obj, event):
        try:
            return self._filter(obj, event)
        except Exception as error:
            App.Console.PrintLog("FreeCAD Ctrl-drag copy: %s\n" % error)
            self.session = None
            return False

    def _press(self, obj, event):
        gdoc, sketch = _edited()
        if sketch is None:
            return False
        try:
            from . import toolbase
            if toolbase.active() is not None or Gui.Control.activeDialog() and _foreign_dialog():
                return False
        except Exception as _fw_err:
            _fw_log("fwsketch/ctrlcopy.py:239", _fw_err)
        viewport = gdoc.ActiveView.graphicsView().viewport() if hasattr(gdoc.ActiveView, "graphicsView") else None
        if viewport is None or obj is not viewport:
            return False
        subs = preselected_subs(sketch)
        edge = next((_edge_index(s) for s in subs if _edge_index(s) is not None), None)
        if edge is None:
            return False
        picked = picked_edges(sketch)
        geos = picked if edge in picked else [edge]
        probe = ViewMath()
        probe.setup_view(gdoc, sketch)
        start, _px = probe.pointer()
        if start is None:
            return False
        self.session = _Session(gdoc, sketch, geos, start, _global(event), "Edge%d" % (edge + 1))
        return True

    def _toggle(self, s):
        """A Ctrl-click without a drag: the entity goes into the selection or out of it."""
        doc, name = s.sketch.Document.Name, s.sketch.Name
        if any(sub.split(".")[-1] == s.toggle_sub for x in Gui.Selection.getSelectionEx(doc)
               if x.ObjectName == name for sub in x.SubElementNames):
            Gui.Selection.removeSelection(doc, name, s.toggle_sub)
        else:
            Gui.Selection.addSelection(doc, name, s.toggle_sub)

    def stop(self):
        from . import appevents
        appevents.stop(self)
        if self.session is not None:
            self.session.close()
            self.session = None


def _foreign_dialog():
    """A task dialog other than the sketch's own (a feature's PropertyManager) is up."""
    try:
        dlg = Gui.Control.activeDialog()
        return bool(dlg) and Gui.ActiveDocument.getInEdit() is None
    except Exception:
        return False


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
