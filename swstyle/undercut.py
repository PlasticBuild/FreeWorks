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
CLASSES = ("dir1", "dir2", "occluded", "straddle", "none")
LABELS = {"dir1": "Direction1 undercut", "dir2": "Direction2 undercut", "occluded": "Occluded undercut",
          "straddle": "Straddle undercut", "none": "No undercut"}
COLOURS = {"dir1": (0.85, 0.0, 0.0), "dir2": (1.0, 0.85, 0.0), "occluded": (0.55, 0.0, 0.75),
           "straddle": (0.2, 0.55, 1.0), "none": (0.0, 0.75, 0.0)}
_FLAT = 1e-3


def _samples(face, n=SAMPLES):
    """(point, normal) spread over the face."""
    u0, u1, v0, v1 = face.ParameterRange
    out = []
    for i in range(n):
        for j in range(n):
            u = u0 + (u1 - u0) * (i + 0.5) / n
            v = v0 + (v1 - v0) * (j + 0.5) / n
            try:
                p = face.valueAt(u, v)
                if not face.isInside(p, 1e-6, True):
                    continue
                out.append((p, face.normalAt(u, v)))
            except Exception:
                continue
    if not out:
        try:
            p = face.CenterOfMass
            out.append((p, face.normalAt(*face.Surface.parameter(p))))
        except Exception as _fw_err:
            _fw_log("undercut.py:66", _fw_err)
    return out


def _seen(solid, point, normal, pull, reach):
    """Whether a ray from point (just off the face) along pull leaves the part untouched."""
    start = point + normal * 1e-3 + pull * 1e-3
    ray = Part.LineSegment(start, start + pull * reach).toShape()
    try:
        inside = ray.common(solid)
    except Exception:
        return True
    return not inside.Edges or sum(e.Length for e in inside.Edges) < 1e-6


def classify(solid, face, pull):
    reach = solid.BoundBox.DiagonalLength * 2 + 1.0
    facing = []
    seen1, seen2 = [], []
    for p, n in _samples(face):
        d = n.dot(pull)
        facing.append(0 if abs(d) < _FLAT else (1 if d > 0 else -1))
        seen1.append(_seen(solid, p, n, pull, reach))
        seen2.append(_seen(solid, p, n, -pull, reach))
    if not facing:
        return "none"
    if 1 in facing and -1 in facing:
        return "straddle"
    if 1 in facing:
        return "none" if all(seen1) else ("dir1" if any(seen1) else "occluded")
    if -1 in facing:
        return "none" if all(seen2) else ("dir2" if any(seen2) else "occluded")
    if all(seen1) or all(seen2):
        return "none"
    return "occluded" if any(not a and not b for a, b in zip(seen1, seen2)) else "none"


def analyse(shape, pull):
    """[class] per face of shape."""
    out = []
    solids = shape.Solids or [shape]
    for f in shape.Faces:
        solid = next((s for s in solids if any(f.isSame(g) for g in s.Faces)), solids[0])
        out.append(classify(solid, f, pull))
    return out


class UndercutWindow(evaluate.ReportWindow):
    ""


    def __init__(self):
        super().__init__("Undercut Analysis", ["Undercut faces", "Faces"])
        self.recalc.setText("Calculate")
        self.colours = evaluate.FaceColours()
        self.options.addWidget(QtWidgets.QLabel("Direction of pull:"))
        self.direction = QtWidgets.QLabel("Z axis")
        self.direction.setObjectName("SWUndercutDirection")
        self.options.addWidget(self.direction)
        self.reverse = QtWidgets.QCheckBox("Reverse")
        self.options.addWidget(self.reverse)
        self.options.addStretch(1)
        self.pull = V(0, 0, 1)
        self.reverse.toggled.connect(self.refresh)
        self.counts = {}
        self.kinds = {}

    def compute(self):
        pull, name = evaluate._pull_from_selection()
        if pull is not None:
            self.pull = pull
            self.direction.setText(name)
        pull = self.pull * (-1.0 if self.reverse.isChecked() else 1.0)
        self.colours.restore()
        counts = dict.fromkeys(CLASSES, 0)
        self.kinds = {}
        for obj in evaluate.visible_bodies():
            kinds = analyse(obj.Shape, pull)
            self.kinds[obj.Name] = kinds
            for k in kinds:
                counts[k] += 1
            self.colours.paint(obj, [COLOURS[k] for k in kinds])
        self.counts = counts
        self.set_rows([((LABELS[k], counts[k]), []) for k in CLASSES])
        self.summary.setText("Red faces face direction 1 but the part hangs over some of them, yellow the same "
                             "for direction 2, purple faces cannot be seen from either side, blue faces turn "
                             "from one side to the other, green faces release. Pick a planar face or a "
                             "straight edge, then Calculate, to set the direction of pull.")

    def cleanup(self):
        self.colours.restore()


@evaluate.command("SWStyle_UndercutAnalysis", "Undercut Analysis",
                  "Colors the faces a two-part mold pulling along a direction could not release.")
def undercut_analysis():
    return evaluate._show(UndercutWindow)


def register():
    if Gui.Command.get("SWStyle_UndercutAnalysis") is None:
        Gui.addCommand("SWStyle_UndercutAnalysis", evaluate._Cmd("SWStyle_UndercutAnalysis"))
