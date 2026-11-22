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
LINE = (0.0, 0.9, 1.0)
WIDTH = 4.0


def _side(kind):
    return {"positive": 1, "negative": -1}.get(kind, 0)


def analyse(shape, pull, angle=1.0):
    """([face class], [edge index on the parting line])."""
    kinds = [evaluate.classify_draft(f, pull, angle) for f in shape.Faces]
    owners = {}
    for i, f in enumerate(shape.Faces):
        for e in f.Edges:
            for k, edge in enumerate(shape.Edges):
                if edge.isSame(e):
                    owners.setdefault(k, set()).add(i)
                    break
    line = []
    for k, faces in owners.items():
        sides = set(_side(kinds[i]) for i in faces)
        walls = [i for i in faces if kinds[i] == "requires"]
        if 1 in sides and -1 in sides:
            line.append(k)
        elif walls and -1 in sides:
            line.append(k)
    return kinds, sorted(line)


class _Lines:
    """The parting line drawn in the 3D view only."""

    def __init__(self):
        self.nodes = []

    def add(self, edges):
        from pivy import coin
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None or not edges:
            return
        sep = coin.SoSeparator()
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(WIDTH)
        colour = coin.SoBaseColor()
        colour.rgb.setValue(*LINE)
        light = coin.SoLightModel()
        light.model.setValue(coin.SoLightModel.BASE_COLOR)
        sep.addChild(light)
        sep.addChild(style)
        sep.addChild(colour)
        points, counts = [], []
        for e in edges:
            pts = e.discretize(Deflection=0.01) if e.Curve.__class__.__name__ not in ("Line", "LineSegment") \
                else [e.Vertexes[0].Point, e.Vertexes[-1].Point]
            points += [(p.x, p.y, p.z) for p in pts]
            counts.append(len(pts))
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(points), points)
        lines = coin.SoLineSet()
        lines.numVertices.setValues(0, len(counts), counts)
        sep.addChild(coords)
        sep.addChild(lines)
        view.getSceneGraph().addChild(sep)
        self.nodes.append((view, sep))

    def clear(self):
        for view, sep in self.nodes:
            try:
                view.getSceneGraph().removeChild(sep)
            except Exception as _fw_err:
                _fw_log("partingline.py:105", _fw_err)
        self.nodes = []


class PartingLineWindow(evaluate.ReportWindow):
    ""


    def __init__(self):
        super().__init__("Parting Line Analysis", ["Result", "Count"])
        self.recalc.setText("Calculate")
        self.colours = evaluate.FaceColours()
        self.lines = _Lines()
        self.options.addWidget(QtWidgets.QLabel("Direction of pull:"))
        self.direction = QtWidgets.QLabel("Z axis")
        self.direction.setObjectName("SWPartingDirection")
        self.options.addWidget(self.direction)
        self.reverse = QtWidgets.QCheckBox("Reverse")
        self.options.addWidget(self.reverse)
        self.options.addWidget(QtWidgets.QLabel("Draft angle:"))
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setObjectName("SWPartingAngle")
        self.angle.setRange(0.0, 89.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix(" deg")
        self.angle.setValue(1.0)
        self.options.addWidget(self.angle)
        self.options.addStretch(1)
        self.pull = V(0, 0, 1)
        self.reverse.toggled.connect(self.refresh)
        self.found = {}

    def compute(self):
        pull, name = evaluate._pull_from_selection()
        if pull is not None:
            self.pull = pull
            self.direction.setText(name)
        pull = self.pull * (-1.0 if self.reverse.isChecked() else 1.0)
        self.colours.restore()
        self.lines.clear()
        counts = dict.fromkeys(("positive", "negative", "requires", "straddle"), 0)
        self.found = {}
        rows_line = []
        doc = App.ActiveDocument.Name if App.ActiveDocument else ""
        edges = []
        for obj in evaluate.visible_bodies():
            kinds, line = analyse(obj.Shape, pull, self.angle.value())
            self.found[obj.Name] = (kinds, line)
            for k in kinds:
                counts[k] += 1
            self.colours.paint(obj, [evaluate.COLOURS[k] for k in kinds])
            edges += [obj.Shape.Edges[k] for k in line]
            rows_line += [(doc, obj.Name, "Edge%d" % (k + 1)) for k in line]
        self.lines.add(edges)
        rows = [((evaluate.LABELS[k], counts[k]), []) for k in ("positive", "negative", "requires", "straddle")]
        rows.append((("Parting line edges", len(rows_line)), rows_line))
        self.set_rows(rows)
        self.summary.setText("The bright line is the possible parting line: the mould splits there. Green faces "
                             "release towards the pull, red ones the other way, yellow ones need draft; the line "
                             "also runs across blue (straddle) faces. Pick a planar face or a straight edge, then "
                             "Calculate, to set the direction of pull.")

    def cleanup(self):
        self.colours.restore()
        self.lines.clear()


@evaluate.command("SWStyle_PartingLineAnalysis", "Parting Line Analysis",
                  "Shows where a two-part mould pulling along a direction would split the part.")
def parting_line_analysis():
    return evaluate._show(PartingLineWindow)


def register():
    if Gui.Command.get("SWStyle_PartingLineAnalysis") is None:
        Gui.addCommand("SWStyle_PartingLineAnalysis", evaluate._Cmd("SWStyle_PartingLineAnalysis"))
