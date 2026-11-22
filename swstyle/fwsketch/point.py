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
import Part

from . import inference as I
from . import relations as R
from .toolbase import SketchTool, edited_sketch


class PointTool(SketchTool):
    def __init__(self, gdoc, sketch):
        super().__init__(gdoc, sketch)
        self.reset()

    def icon_name(self):
        return "Sketcher_Pointer_Create_Point"

    def title(self):
        return "Point"

    def reset(self):
        super().reset()
        self.sug = []

    def on_move(self, p, px):
        self.snapper.set_reference(None)
        d = self.snap(p, px)
        self.preview([], points=[d.position])
        self.readout(d.position, "")
        self.sug = self.seek(d.position, (0.0, 0.0), R.VERTEX)
        return self.sug

    def on_click(self, d):
        pos, sug = d.position, list(self.sug)

        def body():
            geo = self.add_geometry(Part.Point(App.Vector(pos[0], pos[1], 0)))     # For construction on the page
            self.add_relations(sug, geo, I.START)
            self.sketch.solve()
            return geo

        self.transaction("Add sketch point", body)

        self.reset()
        self._move()


def picked_lines(sketch):
    """The two sketch lines picked (Edge names), else None."""
    import FreeCADGui as Gui
    out = []
    try:
        for entry in Gui.Selection.getSelectionEx(sketch.Document.Name):
            if entry.Object is not sketch:
                continue
            for sub in entry.SubElementNames:
                name = sub.rsplit(".", 1)[-1]
                if not name.startswith("Edge"):
                    return None
                g = int(name[4:]) - 1
                if sketch.Geometry[g].TypeId != "Part::GeomLineSegment":
                    return None
                out.append(g)
    except Exception:
        return None
    return out if len(out) == 2 else None


def virtual_sharp(sketch, a, b):
    ""


    import Sketcher
    la, lb = sketch.Geometry[a], sketch.Geometry[b]
    d1, d2 = la.EndPoint - la.StartPoint, lb.EndPoint - lb.StartPoint
    den = d1.x * d2.y - d1.y * d2.x
    if abs(den) < 1e-12:
        return None
    w = lb.StartPoint - la.StartPoint
    t = (w.x * d2.y - w.y * d2.x) / den
    p = la.StartPoint + d1 * t
    doc = sketch.Document
    doc.openTransaction("Virtual Sharp")
    try:
        g = sketch.addGeometry(Part.Point(App.Vector(p.x, p.y, 0)), True)
        sketch.addConstraint([Sketcher.Constraint("PointOnObject", g, 1, a), Sketcher.Constraint("PointOnObject", g, 1, b)])
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    sketch.solve()
    sketch.recompute()
    return g


def start_point():
    gdoc, sketch = edited_sketch()
    lines = picked_lines(sketch)
    if lines is not None:
        made = virtual_sharp(sketch, *lines)
        if made is not None:
            import FreeCADGui as Gui
            Gui.Selection.clearSelection()
            try:
                Gui.getMainWindow().statusBar().showMessage("Virtual sharp added", 4000)
            except Exception as _fw_err:
                _fw_log("fwsketch/point.py:120", _fw_err)
            return None
    tool = PointTool(gdoc, sketch)
    tool.begin()
    return tool
