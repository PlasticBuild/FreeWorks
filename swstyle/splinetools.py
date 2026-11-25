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
from . import geomkeep

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SplineTools"
SAMPLES = 400
TOGGLES = {
    "SWStyle_ShowInflectionPoints": ("ShowInflectionPoints", "Show Inflection Points",
                                     "Shows where each spline changes the way it bends", "Sketcher_BSplineComb"),
    "SWStyle_ShowMinimumRadius": ("ShowMinimumRadius", "Show Minimum Radius",
                                  "Shows where each spline bends tightest, and that radius", "Sketcher_BSplineComb"),
}


def _on(key):
    return App.ParamGet(PARAMS).GetBool(key, False)


# --------------------------------------------------------------------------- the maths
def _bend(curve, u):
    """Signed bend at u in the sketch plane: cross(d1, d2), and |d1|."""
    p, d1, d2 = curve.getD2(u)
    return d1.x * d2.y - d1.y * d2.x, d1.Length


def _curvature(curve, u):
    cross, speed = _bend(curve, u)
    return abs(cross) / speed ** 3 if speed > 1e-12 else 0.0


def _params(curve):
    a, b = curve.FirstParameter, curve.LastParameter
    return [a + (b - a) * k / float(SAMPLES) for k in range(SAMPLES + 1)]


def inflections(curve):
    """Points where the spline's bend changes sign."""
    us = _params(curve)
    signs = []
    for u in us:
        cross, speed = _bend(curve, u)
        k = cross / speed ** 3 if speed > 1e-12 else 0.0
        signs.append(0 if abs(k) < 1e-9 else (1 if k > 0 else -1))
    out = []
    last = None            # (index, sign) of the last clearly bent sample
    for i, s in enumerate(signs):
        if s == 0:
            continue
        if last is not None and s != last[1]:
            lo, hi = us[last[0]], us[i]
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                m = _bend(curve, mid)[0]
                if (m > 0) == (last[1] > 0) and m != 0:
                    lo = mid
                else:
                    hi = mid
            out.append(curve.value(0.5 * (lo + hi)))
        last = (i, s)
    return out


def minimum_radius(curve):
    """(point, radius) where the spline bends tightest, or None for a straight one."""
    us = _params(curve)
    ks = [_curvature(curve, u) for u in us]
    i = max(range(len(us)), key=lambda k: ks[k])
    if ks[i] < 1e-9:
        return None
    lo, hi = us[max(0, i - 1)], us[min(len(us) - 1, i + 1)]
    g = (5 ** 0.5 - 1) / 2
    for _ in range(60):
        a, b = hi - g * (hi - lo), lo + g * (hi - lo)
        if _curvature(curve, a) > _curvature(curve, b):
            hi = b
        else:
            lo = a
    u = 0.5 * (lo + hi)
    if _curvature(curve, u) < ks[i]:
        u = us[i]
    return curve.value(u), 1.0 / _curvature(curve, u)


def splines(sketch):
    return [(i, g) for i, g in enumerate(sketch.Geometry) if type(g).__name__ == "BSplineCurve"]


# --------------------------------------------------------------------------- drawing
class _Overlay(QtCore.QObject):
    """Draws the inflection points and minimum radii of the sketch in edit."""
    instance = None

    def __init__(self):
        super().__init__()
        self.node = self.view = self.key = None
        self.drawn = {}
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(300)

    @staticmethod
    def sketch():
        doc = Gui.ActiveDocument
        vp = doc.getInEdit() if doc is not None else None
        obj = getattr(vp, "Object", None)
        return obj if obj is not None and obj.TypeId == "Sketcher::SketchObject" else None

    def tick(self):
        try:
            sketch = self.sketch()
            show_i, show_r = _on("ShowInflectionPoints"), _on("ShowMinimumRadius")
            items = splines(sketch) if sketch is not None and (show_i or show_r) else []
            key = (sketch and sketch.Name, show_i, show_r,
                   tuple((i, tuple((round(p.x, 6), round(p.y, 6)) for p in g.getPoles()), g.Degree) for i, g in items),
                   str(sketch.getGlobalPlacement()) if sketch is not None else "")
            if key == self.key:
                return
            self.key = key
            drawn = {}
            for i, g in items:
                drawn[i] = {"inflections": inflections(g) if show_i else [],
                            "minimum": minimum_radius(g) if show_r else None}
            self.drawn = drawn
            self.draw(sketch, drawn)
        except Exception as error:
            App.Console.PrintLog("FreeCAD spline tools: %s\n" % error)

    def draw(self, sketch, drawn):
        self.clear()
        if not drawn or Gui.ActiveDocument is None:
            return
        from pivy import coin
        place = sketch.getGlobalPlacement()
        view = Gui.ActiveDocument.ActiveView
        root = coin.SoAnnotation()
        root.setName("SWStyle_SplineTools")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
        marks = [place.multVec(p) for d in drawn.values() for p in d["inflections"]]
        if marks:
            sep = coin.SoSeparator()
            colour = coin.SoBaseColor()
            colour.rgb.setValue(0.85, 0.1, 0.55)
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(marks), [(p.x, p.y, p.z) for p in marks])
            markers = coin.SoMarkerSet()
            markers.markerIndex = Gui.getMarkerIndex("DIAMOND_FILLED", 9)
            for node in (colour, coords, markers):
                sep.addChild(node)
            root.addChild(sep)
        for d in drawn.values():
            if d["minimum"] is None:
                continue
            point, radius = d["minimum"]
            where = place.multVec(point)
            sep = coin.SoSeparator()
            colour = coin.SoBaseColor()
            colour.rgb.setValue(0.0, 0.35, 0.8)
            coords = coin.SoCoordinate3()
            coords.point.setValue(where.x, where.y, where.z)
            markers = coin.SoMarkerSet()
            markers.markerIndex = Gui.getMarkerIndex("CIRCLE_FILLED", 7)
            move = coin.SoTranslation()
            move.translation.setValue(where.x, where.y, where.z)
            font = coin.SoFont()
            font.size = 13
            label = coin.SoText2()
            label.string = "  R %.2f" % radius
            for node in (colour, coords, markers, move, font, label):
                sep.addChild(node)
            root.addChild(sep)
        view.getSceneGraph().addChild(root)
        self.node, self.view = root, view

    def clear(self):
        if self.node is not None:
            try:
                self.view.getSceneGraph().removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("splinetools.py:212", _fw_err)
        self.node = self.view = None


# --------------------------------------------------------------------------- Reverse Endpoint Tangent
def end_tangent(curve, pos):
    """The direction the spline leaves its start (pos 1) or reaches its end (pos 2)."""
    u = curve.FirstParameter if pos == 1 else curve.LastParameter
    t = curve.tangent(u)[0]
    t.normalize()
    return t


def reverse_end_tangent(sketch, geo, pos):
    """Turns the spline geo round at its start (pos 1) or end (pos 2); True when it turned."""
    curve = sketch.Geometry[geo]
    if curve.TypeId != "Part::GeomBSplineCurve" or pos not in (1, 2):
        raise ValueError("Pick the end of a spline")
    before = end_tangent(curve, pos)
    poles = curve.getPoles()
    end, near = (0, 1) if pos == 1 else (len(poles) - 1, len(poles) - 2)
    old = poles[near]
    new = poles[end] * 2 - old
    geos = geomkeep.read(sketch)
    turned = geos[geo].clone()
    turned.setPole(near + 1, new)
    geos[geo] = turned
    for c in sketch.Constraints:
        # the control point's circle sits on the pole: move it along
        if c.Type == "InternalAlignment" and c.Second == geo and c.First >= 0 and \
                geos[c.First].TypeId == "Part::GeomCircle" and (geos[c.First].Center - old).Length < 1e-6:
            circle = geos[c.First].clone()
            circle.Center = new
            geos[c.First] = circle
    sketch.Geometry = geos
    sketch.solve()
    return end_tangent(sketch.Geometry[geo], pos).dot(before) < 0


def flip_arc_end(sketch, geo):
    ""



    import Part
    import Sketcher
    arc = sketch.Geometry[geo]
    if arc.TypeId != "Part::GeomArcOfCircle":
        raise ValueError("Pick the end of an arc or spline")
    swap = {1: 2, 2: 1}
    keep = []
    for i, c in enumerate(sketch.Constraints):
        if geo in (c.First, c.Second, c.Third):
            keep.append(i)
    saved = []
    for i in keep:
        c = sketch.Constraints[i]
        ends = [(c.First, c.FirstPos), (c.Second, c.SecondPos), (c.Third, c.ThirdPos)]
        ends = [(g, swap.get(int(p), int(p)) if g == geo else int(p)) for g, p in ends]
        saved.append((c, ends))
    for i in sorted(keep, reverse=True):
        sketch.delConstraint(i)
    a0, a1 = arc.FirstParameter, arc.LastParameter
    import math
    new = Part.ArcOfCircle(Part.Circle(arc.Center, arc.Axis, arc.Radius), a1, a0 + 2 * math.pi)
    construction = sketch.getConstruction(geo)
    geos = geomkeep.read(sketch)
    geos[geo] = new
    sketch.Geometry = geos
    if construction:
        sketch.setConstruction(geo, True)
    for c, ends in saved:
        (f, fp), (sg, sp), (t, tp) = ends
        try:
            if c.Type in ("Tangent", "Perpendicular") and fp in (1, 2) and sp in (1, 2):
                n = Sketcher.Constraint(c.Type, f, fp, sg, sp)
            elif c.Type in ("Radius", "Diameter", "Angle") and sg == -2000:
                n = Sketcher.Constraint(c.Type, f, c.Value)
            elif sg == -2000:
                n = Sketcher.Constraint(c.Type, f) if fp == 0 else Sketcher.Constraint(c.Type, f, fp)
            elif t == -2000:
                if c.Type in ("Distance", "DistanceX", "DistanceY", "Angle"):
                    n = Sketcher.Constraint(c.Type, f, fp, sg, sp, c.Value) if fp or sp else Sketcher.Constraint(c.Type, f, sg, c.Value)
                elif fp == 0 and sp == 0:
                    n = Sketcher.Constraint(c.Type, f, sg)
                else:
                    n = Sketcher.Constraint(c.Type, f, fp, sg, sp)
            else:
                n = Sketcher.Constraint(c.Type, f, fp, sg, sp, t, tp)
            k = sketch.addConstraint(n)
            if c.Name:
                sketch.renameConstraint(k, c.Name)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Flip Endpoint Tangent left out %s: %s\n" % (c.Type, error))
    sketch.solve()
    return True


def held(sketch, geo, pos):
    """Whether a relation holds the spline's tangent at that end (an end-to-end Tangent or
    Perpendicular there, or the spline fixed)."""
    for c in sketch.Constraints:
        ends = [(c.First, c.FirstPos), (c.Second, c.SecondPos), (c.Third, c.ThirdPos)]
        if c.Type in ("Tangent", "Perpendicular") and (geo, pos) in ends:
            return True
        if c.Type == "Block" and c.First == geo:
            return True
    return False


def _picked_end(sketch):
    try:
        from . import relationspm
        subs = relationspm.picked_subs(sketch)
    except Exception:
        subs = []
    for sub in subs:
        if sub.startswith("Vertex"):
            geo, pos = sketch.getGeoVertexIndex(int(sub[6:]) - 1)
            if geo >= 0 and pos in (1, 2) and sketch.Geometry[geo].TypeId in ("Part::GeomBSplineCurve",
                                                                            "Part::GeomArcOfCircle"):
                return geo, pos
    return None


class _Reverse:
    def GetResources(self):

        return {"MenuText": "Flip Endpoint Tangent", "Pixmap": "Sketcher_BSplinePolygon",
                "ToolTip": "The picked spline or arc end leaves the other way", "CmdType": "ForEdit"}

    def IsActive(self):
        from . import contextbar
        sketch = contextbar.sketch_in_edit()
        return sketch is not None and _picked_end(sketch) is not None

    def Activated(self):
        from . import contextbar
        sketch = contextbar.sketch_in_edit()
        end = _picked_end(sketch) if sketch is not None else None
        if end is None:
            return
        if sketch.Geometry[end[0]].TypeId == "Part::GeomArcOfCircle":
            doc = sketch.Document
            doc.openTransaction("Flip Endpoint Tangent")
            try:
                flip_arc_end(sketch, end[0])
            except Exception as error:
                doc.abortTransaction()
                App.Console.PrintWarning("FreeCAD: Flip Endpoint Tangent: %s\n" % error)
                return
            doc.commitTransaction()
            sketch.recompute()
            return
        if held(sketch, *end):
            App.Console.PrintWarning("FreeCAD: a relation holds this spline end's tangent; "
                                     "delete it to reverse the tangent\n")
            return
        doc = sketch.Document
        doc.openTransaction("Reverse Endpoint Tangent")
        try:
            turned = reverse_end_tangent(sketch, *end)
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintWarning("FreeCAD: Reverse Endpoint Tangent: %s\n" % error)
            return
        if not turned:
            # something else held the end the way it was
            doc.abortTransaction()
            App.Console.PrintWarning("FreeCAD: a relation holds this spline end's tangent; "
                                     "delete it to reverse the tangent\n")
            return
        doc.commitTransaction()
        sketch.recompute()


# --------------------------------------------------------------------------- the toggles
class _Toggle:
    def __init__(self, command):
        self.command = command
        self.key, self.menu, self.tip, self.pixmap = TOGGLES[command]

    def GetResources(self):
        return {"MenuText": self.menu, "ToolTip": self.tip, "Pixmap": self.pixmap,
                "Checkable": _on(self.key), "CmdType": "ForEdit"}

    def Activated(self, checked):
        App.ParamGet(PARAMS).SetBool(self.key, bool(checked))
        if _Overlay.instance is not None:
            _Overlay.instance.tick()

    def IsActive(self):
        on = _on(self.key)
        try:
            actions = Gui.Command.get(self.command).getAction()
        except Exception:
            actions = []
        for action in actions:
            if action.isChecked() != on:
                blocked = action.blockSignals(True)
                action.setChecked(on)
                action.blockSignals(blocked)
        return App.ActiveDocument is not None


def register():
    for command in TOGGLES:
        if command not in Gui.listCommands():
            Gui.addCommand(command, _Toggle(command))
    if "SWStyle_ReverseEndpointTangent" not in Gui.listCommands():
        Gui.addCommand("SWStyle_ReverseEndpointTangent", _Reverse())
    if _Overlay.instance is None:
        _Overlay.instance = _Overlay()
