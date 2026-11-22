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


import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
import Sketcher
from PySide import QtCore

from .toolbase import SketchTool, edited_sketch, other_buttons
from . import trim as T

CLOSED = ("Part::GeomCircle", "Part::GeomEllipse")
SPLITTABLE = ("Part::GeomLineSegment", "Part::GeomArcOfCircle", "Part::GeomArcOfEllipse",
              "Part::GeomArcOfHyperbola", "Part::GeomArcOfParabola", "Part::GeomBSplineCurve") + CLOSED


def on_curve(geo, p):
    """The point of geo nearest p (sketch x, y)."""
    try:
        u = geo.parameter(App.Vector(p[0], p[1], 0))
        q = geo.value(u)
        return (q.x, q.y)
    except Exception as _fw_err:
        _fw_log("fwsketch/split.py:44", _fw_err)
        return p


def is_closed(geo):
    if geo.TypeId in CLOSED:
        return True
    if geo.TypeId == "Part::GeomBSplineCurve":
        try:
            return bool(geo.isClosed()) or bool(geo.isPeriodic())
        except Exception as _fw_err:
            _fw_log("fwsketch/split.py:55", _fw_err)
            return False
    return False


def split(sketch, geo, at):
    """Splits geo at sketch point at; returns the ids of the pieces' (the first, the second)."""
    before = sketch.GeometryCount
    sketch.split(geo, App.Vector(at[0], at[1], 0))
    sketch.solve()
    return before


def split_closed(sketch, geo, first, second):
    """A closed entity split at two points: two pieces end to end."""
    sketch.split(geo, App.Vector(first[0], first[1], 0))      # FreeCAD: the closed curve opens there
    sketch.solve()
    piece = geo if geo < sketch.GeometryCount and not is_closed(sketch.Geometry[geo]) else sketch.GeometryCount - 1
    for i in (geo, sketch.GeometryCount - 1):
        if 0 <= i < sketch.GeometryCount and not is_closed(sketch.Geometry[i]) and \
                sketch.Geometry[i].TypeId != "Part::GeomPoint":
            try:
                if T.near_curve(sketch.Geometry[i], second, 1e-6):
                    piece = i
                    break
            except Exception as _fw_err:
                _fw_log("fwsketch/split.py:78", _fw_err)
    sketch.split(piece, App.Vector(second[0], second[1], 0))
    sketch.solve()


class SplitTool(SketchTool):
    def __init__(self, gdoc, sketch):
        super().__init__(gdoc, sketch)
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Splitting"

    def title(self):
        return "Split Entities"

    def starts_click_drag(self):
        return False

    def reset(self):
        super().reset()
        self.hover = None
        self.at = None
        self.pending = None      # (geo, point, point id) of the first split point on a closed entity
        self.last = None         # for tests

    def _filter(self, obj, event):
        if (obj is self.viewport or obj is self.quarter) and event.type() == QtCore.QEvent.MouseMove \
                and self._press is None:
            if self._other_down or other_buttons(event):
                return False
            QtCore.QTimer.singleShot(0, self._move)
            return False
        return super()._filter(obj, event)

    def on_move(self, p, px):
        d = self.snap(p, px, allow_point=False, allow_edge=False, allow_angle=False, allow_grid=False)
        sk = self.sketch
        geo = T.hovered_edge(sk)
        ok = geo is not None and 0 <= geo < sk.GeometryCount and sk.Geometry[geo].TypeId in SPLITTABLE
        if ok and not T.near_curve(sk.Geometry[geo], d.position, 8.0 * px):
            ok = False
        self.hover = geo if ok else None
        self.at = on_curve(sk.Geometry[geo], d.position) if ok else None
        self.preview([], points=[self.at] if self.at else [])
        return []

    def end(self):
        self._drop_pending()
        super().end()

    def _drop_pending(self):
        pending, self.pending = self.pending, None
        if pending is None:
            return
        sk = self.sketch
        try:
            pid = pending[2]
            if pid < sk.GeometryCount and sk.Geometry[pid].TypeId == "Part::GeomPoint":
                sk.Document.openTransaction("Split Entities")
                try:
                    sk.delGeometry(pid)
                except BaseException:
                    try:
                        sk.Document.abortTransaction()
                    except Exception:
                        pass
                    raise
                sk.Document.commitTransaction()
                sk.Document.recompute()
        except Exception as _fw_err:
            _fw_log("fwsketch/split.py:142", _fw_err)

    def on_click(self, d):
        if self.hover is None or self.at is None:
            return
        geo, at = self.hover, self.at
        sk = self.sketch
        try:
            Gui.Selection.rmPreselect()
        except Exception as _fw_err:
            _fw_log("fwsketch/split.py:152", _fw_err)
        try:
            if is_closed(sk.Geometry[geo]):
                if self.pending is None or self.pending[0] != geo:
                    self._drop_pending()

                    def mark():
                        pid = sk.addGeometry(Part.Point(App.Vector(at[0], at[1], 0)), False)
                        sk.addConstraint(Sketcher.Constraint("PointOnObject", pid, 1, geo))
                        return pid
                    pid = self.transaction("Split point", mark)
                    self.pending = (geo, at, pid)
                    self.last = ("point", geo, at)
                else:
                    first = sk.getPoint(self.pending[2], 1)
                    pid = self.pending[2]
                    self.pending = None

                    def body():
                        sk.delGeometry(pid)
                        g = geo if geo < pid else geo - 1
                        split_closed(sk, g, (first.x, first.y), at)
                    self.transaction("Split Entities", body)
                    self.last = ("closed", geo, at)
            else:
                self.transaction("Split Entities", lambda: split(sk, geo, at))
                self.last = ("open", geo, at)
        except Exception as e:
            App.Console.PrintError("FreeCAD Split: %s\n" % e)
        self.hover = self.at = None
        self.preview([])


def start_split():
    gdoc, sketch = edited_sketch()
    t = SplitTool(gdoc, sketch)
    t.begin()
    return t
