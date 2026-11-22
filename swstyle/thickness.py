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
from PySide import QtWidgets

from . import evaluate

V = App.Vector
SAMPLES = 5
GREY = (0.75, 0.75, 0.75)


def _samples(face, n=SAMPLES):
    """(point, outward normal) spread over the face, off its edges; a finer grid for a face
    the first grid misses (a narrow rim)."""
    u0, u1, v0, v1 = face.ParameterRange
    edges = Part.Compound(face.Edges)
    margin = 1e-4 * max(1.0, face.BoundBox.DiagonalLength)
    for size in (n, 2 * n + 1, 4 * n + 3):
        out = []
        for i in range(size):
            for j in range(size):
                u = u0 + (u1 - u0) * (i + 0.5) / size
                v = v0 + (v1 - v0) * (j + 0.5) / size
                try:
                    p = face.valueAt(u, v)
                    if not face.isInside(p, 1e-6, True):
                        continue
                    if edges.distToShape(Part.Vertex(p))[0] < margin:
                        continue        # on an edge the ray would run along the next face
                    out.append((p, face.normalAt(u, v)))
                except Exception:
                    continue
        if out:
            return out
    return []


def wall(solid, point, normal, reach):
    """The thickness under point: how far a ray into the solid along -normal stays inside."""
    inward = normal * -1.0
    if solid.isInside(point + normal * 1e-3, 1e-6, False) and not solid.isInside(point + inward * 1e-3, 1e-6, False):
        inward = normal            # the face's normal points into the solid (a reversed face)
    start = point + inward * 1e-4
    ray = Part.LineSegment(start, start + inward * reach).toShape()
    try:
        inside = ray.common(solid)
    except Exception:
        return None
    best = None
    for e in inside.Edges:
        if min((v.Point - start).Length for v in e.Vertexes) < 1e-3:
            best = e.Length + 1e-4
            break
    return best


def face_thickness(solid, face, corners_zero=False):
    ""



    try:
        from . import wallthick
        got = wallthick.face_thickness(solid, face, SAMPLES, corners_zero)
        if got is not None:
            return got
    except Exception as _fw_err:
        _fw_log("thickness.py:93", _fw_err)
    reach = solid.BoundBox.DiagonalLength * 2 + 1.0
    walls = [w for w in (wall(solid, p, n, reach) for p, n in _samples(face, SAMPLES)) if w is not None]
    return min(walls) if walls else None


def analyse(shape, corners_zero=False):
    """[(face index, thinnest wall or None, area)] for each face of shape."""
    solids = shape.Solids or [shape]
    out = []
    for i, f in enumerate(shape.Faces):
        solid = next((s for s in solids if any(f.isSame(g) for g in s.Faces)), solids[0])
        out.append((i, face_thickness(solid, f, corners_zero), f.Area))
    return out


def _blend(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(a[k] + (b[k] - a[k]) * t for k in range(3))


def colour(t, target, low, high, thin=True):
    """A face's colour: thin regions red to yellow up to the target, thick regions yellow to blue."""
    if t is None:
        return GREY
    if thin:
        if t >= target:
            return GREY
        return _blend((1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (t - low) / (target - low) if target > low else 1.0)
    if t <= target:
        return GREY
    return _blend((1.0, 1.0, 0.0), (0.0, 0.3, 1.0), (t - target) / (high - target) if high > target else 1.0)


class ThicknessWindow(evaluate.ReportWindow):
    ""


    def __init__(self):
        super().__init__("Thickness Analysis", ["Result", "Value"])
        self.recalc.setText("Calculate")
        self.colours = evaluate.FaceColours()
        self.options.addWidget(QtWidgets.QLabel("Target thickness:"))
        self.target = QtWidgets.QDoubleSpinBox()
        self.target.setObjectName("SWThicknessTarget")
        self.target.setRange(0.001, 1e6)
        self.target.setDecimals(3)
        self.target.setSuffix(" mm")
        self.target.setValue(1.0)
        evaluate.unit_spin(self.target)
        self.options.addWidget(self.target)
        self.thin = QtWidgets.QRadioButton("Show thin regions")
        self.thin.setObjectName("SWThicknessThin")
        self.thin.setChecked(True)
        self.thick = QtWidgets.QRadioButton("Show thick regions")
        self.thick.setObjectName("SWThicknessThick")
        self.options.addWidget(self.thin)
        self.options.addWidget(self.thick)
        self.options.addStretch(1)
        self.thin.toggled.connect(self._paint)
        self.results = {}
        self.walls = {}

    def compute(self):
        self.walls = {}
        for obj in evaluate.visible_bodies():
            self.walls[obj.Name] = (obj, analyse(obj.Shape))
        self._paint()

    def _paint(self, *args):
        self.colours.restore()
        target = evaluate.mm_of(self.target)
        found = [t for _obj, rows in self.walls.values() for _i, t, _a in rows if t is not None]
        if not found:
            self.results = {}
            self.set_rows([(("Thinnest wall", "-"), [])])
            self.summary.setText("No visible solid to analyse.")
            return
        low, high = min(found), max(found)
        thin = self.thin.isChecked()
        area = under = 0.0
        thinnest = thickest = None
        for name, (obj, rows) in self.walls.items():
            self.colours.paint(obj, [colour(t, target, low, high, thin) for _i, t, _a in rows])
            for i, t, a in rows:
                area += a
                if t is not None and t < target:
                    under += a
                if t is not None and (thinnest is None or t < thinnest[0]):
                    thinnest = (t, obj, i)
                if t is not None and (thickest is None or t > thickest[0]):
                    thickest = (t, obj, i)
        share = 100.0 * under / area if area else 0.0
        doc = App.ActiveDocument.Name if App.ActiveDocument else ""
        self.results = {"thinnest": thinnest[0], "thickest": thickest[0], "under": share}
        self.set_rows([
            (("Thinnest wall", evaluate.len_text(thinnest[0])), [(doc, thinnest[1].Name, "Face%d" % (thinnest[2] + 1))]),
            (("Thickest wall", evaluate.len_text(thickest[0])), [(doc, thickest[1].Name, "Face%d" % (thickest[2] + 1))]),
            (("Target thickness", evaluate.len_text(target)), []),
            (("Area thinner than the target", "%.1f %%" % share), []),
        ])
        self.summary.setText("Red faces are the thinnest, yellow are at the target, grey are outside the range "
                             "shown." if thin else
                             "Yellow faces are at the target, blue are the thickest, grey are thinner than the "
                             "target.")

    def cleanup(self):
        self.colours.restore()


@evaluate.command("SWStyle_ThicknessAnalysis", "Thickness Analysis",
                  "Colours the faces by the wall thickness under them, against a target thickness.")
def thickness_analysis():
    return evaluate._show(ThicknessWindow)


def register():
    if Gui.Command.get("SWStyle_ThicknessAnalysis") is None:
        Gui.addCommand("SWStyle_ThicknessAnalysis", evaluate._Cmd("SWStyle_ThicknessAnalysis"))
