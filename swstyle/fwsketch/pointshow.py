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

from . import sysopts

INTERVAL_MS = 400
TOL = 1e-6
_watcher = None


def _edited():
    try:
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc is not None else None
        obj = getattr(vp, "Object", None)
        if obj is not None and obj.TypeId == "Sketcher::SketchObject":
            return gdoc, obj
    except Exception as _fw_err:
        _fw_log("fwsketch/pointshow.py:43", _fw_err)
    return None, None


def hidden_points(sketch, centres, ends):
    """[(x, y)] of the vertices to hide: arc and circle centres (centres False), end points
    of the sketch's curves (ends False)."""
    out = []
    for g in sketch.Geometry:
        kind = type(g).__name__
        if kind == "Point":
            continue
        if not centres and kind in ("Circle", "ArcOfCircle", "Ellipse", "ArcOfEllipse",
                                    "ArcOfHyperbola", "ArcOfParabola"):
            c = g.Center
            out.append((c.x, c.y))
        if not ends and hasattr(g, "StartPoint") and kind not in ("Circle", "Ellipse"):
            for p in (g.StartPoint, g.EndPoint):
                out.append((p.x, p.y))
    return out


def _marker_sets(view):
    from pivy import coin
    sa = coin.SoSearchAction()
    sa.setType(coin.SoMarkerSet.getClassTypeId())
    sa.setInterest(coin.SoSearchAction.ALL)
    sa.apply(view.getSceneGraph())
    out = []
    paths = sa.getPaths()
    for i in range(paths.getLength()):
        path = paths[i]
        names = [path.getNode(k).getName().getString() for k in range(path.getLength())]
        tail = path.getTail()
        if "Sketch_EditRoot" in names and tail.getName().getString().startswith("PointSet"):
            parent = path.getNodeFromTail(1)
            coords = None
            for k in range(parent.getNumChildren()):
                n = parent.getChild(k)
                if n.isOfType(coin.SoCoordinate3.getClassTypeId()):
                    coords = n
                if n == tail:
                    break
            out.append((tail, coords))
    return out


def apply(view, sketch):
    """Hide or show the vertices as the two options say; returns how many are hidden."""
    from pivy import coin
    centres = sysopts.on(sysopts.ARC_CENTERPOINTS)
    ends = sysopts.on(sysopts.ENTITY_POINTS)
    hide = hidden_points(sketch, centres, ends) if not (centres and ends) else []
    count = 0
    for marker, coords in _marker_sets(view):
        n_idx = marker.markerIndex.getNum()
        shown = marker.markerIndex[0] if n_idx else 0
        if shown == coin.SoMarkerSet.NONE:
            shown = next((marker.markerIndex[j] for j in range(n_idx) if marker.markerIndex[j] != coin.SoMarkerSet.NONE),
                         getattr(marker, "_fw_shown", 0))
        if coords is None:
            continue
        start = marker.startIndex.getValue()
        total = coords.point.getNum()
        num = marker.numPoints.getValue()
        num = total - start if num < 0 else num
        if not hide:
            if n_idx > 1:
                marker.markerIndex.setNum(1)
                marker.markerIndex.set1Value(0, shown)
            continue
        values = []
        for j in range(num):
            p = coords.point[start + j]
            gone = any(abs(p[0] - x) < TOL and abs(p[1] - y) < TOL for x, y in hide)
            values.append(coin.SoMarkerSet.NONE if gone else shown)
            count += gone
        current = [marker.markerIndex[j] for j in range(n_idx)]
        if current != values:
            marker.markerIndex.setValues(0, len(values), values)
            marker.markerIndex.setNum(len(values))
    return count


class Watcher:
    def __init__(self):
        self.timer = QtCore.QTimer()
        self.timer.setInterval(INTERVAL_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.last = None

    def tick(self):
        gdoc, sketch = _edited()
        if sketch is None:
            return
        try:
            centres = sysopts.on(sysopts.ARC_CENTERPOINTS)
            ends = sysopts.on(sysopts.ENTITY_POINTS)
            if centres and ends and self.last in (None, 0):
                return          # nothing to hide, nothing hidden: no scene walk
            self.last = apply(gdoc.ActiveView, sketch)
        except Exception as _fw_err:
            _fw_log("fwsketch/pointshow.py:146", _fw_err)

    def stop(self):
        self.timer.stop()


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
