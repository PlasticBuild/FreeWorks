"""Measure on the plate toolbar, as the slicers' Measure tool (key U): click a point, an edge or a face of an object
on the plate (the nearest corner or edge to the click wins over the face, as the slicers snap to features), then a
second one. The panel gives what the first is (a point, an edge's length, a circle's diameter, a face's area) and,
with two, the distance between them with its X, Y and Z parts, and the angle between two planes or edges. The
picks show on the plate, and a line between the nearest points."""
import math

import FreeCAD as App
from PySide import QtCore, QtWidgets

PICK_COLOUR = (0.95, 0.55, 0.10)
LINE_COLOUR = (0.10, 0.45, 0.85)


def snap_tolerance(item):
    """How near (mm, model size) a click has to be to a corner or an edge to take it."""
    b = item._shape.BoundBox
    return max(0.3, min(1.5, 0.03 * max(b.XLength, b.YLength, b.ZLength)))


def feature_at(item, face, point):
    """("point" | "edge" | "face", the model-coordinate subshape) at a click on a CAD face."""
    import Part
    shape = item._shape
    f = shape.Faces[face]
    tol = snap_tolerance(item)
    v = Part.Vertex(point)
    best = min(f.Vertexes, key=lambda x: (x.Point - point).Length, default=None)
    if best is not None and (best.Point - point).Length <= tol:
        return "point", best
    edges = sorted(f.Edges, key=lambda e: e.distToShape(v)[0])
    if edges and edges[0].distToShape(v)[0] <= tol * 0.6:
        return "edge", edges[0]
    return "face", f


def placed(sub, matrix):
    """The subshape as it stands on the plate (a scaled object: its geometry scaled too)."""
    s = sub.copy()
    if _rigid(matrix):
        s.transformShape(matrix)
        return s
    return s.transformGeometry(matrix)


def _rigid(m):
    """True when the matrix only turns and moves (no scale): the cheaper transform keeps the exact geometry."""
    cols = [App.Vector(m.A11, m.A21, m.A31), App.Vector(m.A12, m.A22, m.A32), App.Vector(m.A13, m.A23, m.A33)]
    return all(abs(c.Length - 1.0) < 1e-9 for c in cols)


def _circle(edge):
    c = getattr(edge, "Curve", None)
    return c if c is not None and c.__class__.__name__ == "Circle" else None


def _plane_normal(face):
    try:
        if face.Surface.__class__.__name__ == "Plane":
            u0, u1, v0, v1 = face.ParameterRange
            return face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
    except Exception:
        pass
    return None


def _line_dir(edge):
    c = getattr(edge, "Curve", None)
    if c is not None and c.__class__.__name__ in ("Line", "LineSegment"):
        d = edge.Vertexes[-1].Point - edge.Vertexes[0].Point
        return d.normalize() if d.Length > 1e-9 else None
    return None


def describe(kind, s):
    if kind == "point":
        p = s.Point
        return "Point  X %.2f  Y %.2f  Z %.2f" % (p.x, p.y, p.z)
    if kind == "edge":
        c = _circle(s)
        if c is not None:
            return "Circle  diameter %.2f mm  (centre X %.2f  Y %.2f  Z %.2f)" % (2 * c.Radius, c.Center.x, c.Center.y,
                                                                                  c.Center.z)
        return "Edge  length %.2f mm" % s.Length
    n = _plane_normal(s)
    return "%s  area %.2f mm²" % ("Plane" if n is not None else "Face", s.Area)


def measure(a, b):
    """{"distance", "dx", "dy", "dz", "p", "q", "angle" (deg or None), "centres" (or None)} of two picks."""
    (ka, sa), (kb, sb) = a, b
    d, pairs, _info = sa.distToShape(sb)
    p, q = pairs[0]
    out = {"distance": d, "dx": abs(q.x - p.x), "dy": abs(q.y - p.y), "dz": abs(q.z - p.z), "p": p, "q": q,
           "angle": None, "centres": None}
    da = _plane_normal(sa) if ka == "face" else (_line_dir(sa) if ka == "edge" else None)
    db = _plane_normal(sb) if kb == "face" else (_line_dir(sb) if kb == "edge" else None)
    if da is not None and db is not None:
        cos = max(-1.0, min(1.0, abs(da.dot(db))))
        out["angle"] = math.degrees(math.acos(cos))
        if ka == kb == "face" and out["angle"] < 1e-4:
            # two parallel planes: the distance between them (the slicers' "Distance" of parallel planes)
            out["distance"] = abs((sb.Vertexes[0].Point - sa.Vertexes[0].Point).dot(da))
    ca = _circle(sa) if ka == "edge" else None
    cb = _circle(sb) if kb == "edge" else None
    if ca is not None and cb is not None:
        out["centres"] = (cb.Center - ca.Center).Length
    return out


class Measurer:
    """The Measure tool's clicks on the plate."""

    def __init__(self, toolbar):
        self.toolbar, self.bed = toolbar, toolbar.bed
        self.picks = []          # [(kind, placed subshape)]
        self.callback = None
        self.node = None
        self.start()

    def start(self):
        from pivy import coin
        bed = self.bed
        if bed.view is None:
            return
        bed.stop_pick()
        bed.picking = self

        def button(cb):
            ev = cb.getEvent()
            if ev.getButton() == coin.SoMouseButtonEvent.BUTTON1 and ev.getState() == coin.SoButtonEvent.DOWN:
                if self.pick_at(ev.getPosition()):
                    cb.setHandled()
        self.callback = bed.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), button)

    def stop(self):
        from pivy import coin
        if self.callback is not None and self.bed.view is not None:
            try:
                self.bed.view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.callback)
            except Exception as error:
                App.Console.PrintLog("slicer measure: %s\n" % error)
        self.callback = None
        if self.bed.picking is self:
            self.bed.picking = None
        self.picks = []
        self.show(None)

    def pick_at(self, pos):
        from . import slicerpaint
        hit = slicerpaint.hit_under(self.bed, pos)
        if hit is None:
            return False
        item, face, point = hit
        if face is None or point is None:
            self.toolbar.panel._say("Measure works on the faces of a FreeCAD part or a STEP file, not on a mesh.")
            return True
        kind, sub = feature_at(item, face, point)
        self.add(kind, placed(sub, self.bed.world_matrix(item)))
        return True

    def add(self, kind, shape):
        if len(self.picks) >= 2:
            self.picks = []              # a third click starts again, as in the slicers
        self.picks.append((kind, shape))
        self.update()

    def restart(self):
        self.picks = []
        self.update()

    def result(self):
        return measure(self.picks[0], self.picks[1]) if len(self.picks) == 2 else None

    def update(self):
        self.show(self.result())
        p = self.toolbar.tool_panel
        if p is not None and hasattr(p, "fill"):
            p.fill(self)

    def show(self, result):
        from pivy import coin
        root = self.bed.root
        if self.node is not None and root is not None:
            try:
                root.removeChild(self.node)
            except Exception:
                pass
        self.node = None
        if root is None or (not self.picks and result is None):
            return
        sep = coin.SoSeparator()
        sep.setName("SWStyle_SlicerMeasure")
        style = coin.SoDrawStyle()
        style.lineWidth = 3.0
        style.pointSize = 9.0
        sep.addChild(style)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        sep.addChild(light)
        for kind, s in self.picks:
            mat = coin.SoMaterial()
            mat.diffuseColor = PICK_COLOUR
            sep.addChild(mat)
            if kind == "point":
                pts = [tuple(s.Point)]
                c = coin.SoCoordinate3()
                c.point.setValues(0, 1, pts)
                sep.addChild(c)
                sep.addChild(coin.SoPointSet())
                continue
            edges = [s] if kind == "edge" else s.Edges
            for e in edges:
                pts = [tuple(v) for v in e.discretize(Deflection=0.05)]
                if len(pts) < 2:
                    continue
                c = coin.SoCoordinate3()
                c.point.setValues(0, len(pts), pts)
                sep.addChild(c)
                ls = coin.SoLineSet()
                ls.numVertices.setValue(len(pts))
                sep.addChild(ls)
        if result is not None and result["distance"] > 1e-9:
            mat = coin.SoMaterial()
            mat.diffuseColor = LINE_COLOUR
            sep.addChild(mat)
            c = coin.SoCoordinate3()
            c.point.setValues(0, 2, [tuple(result["p"]), tuple(result["q"])])
            sep.addChild(c)
            ls = coin.SoLineSet()
            ls.numVertices.setValue(2)
            sep.addChild(ls)
        root.addChild(sep)
        self.node = sep


def panel(toolbar, ToolPanel):
    """The Measure tool panel."""
    p = ToolPanel("Measure", toolbar.parentWidget())
    p.setObjectName("SWSlicerToolPanel")
    hint = QtWidgets.QLabel("Click a point, an edge or a face of an object, then a second one.")
    hint.setWordWrap(True)
    p.lay.addWidget(hint, p.lay.rowCount(), 0, 1, 4)
    p.first = QtWidgets.QLabel("Selection 1: none")
    p.second = QtWidgets.QLabel("Selection 2: none")
    p.out = QtWidgets.QLabel("")
    p.out.setObjectName("SWStyle_SlicerMeasureResult")
    p.out.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    for w in (p.first, p.second, p.out):
        w.setWordWrap(True)
        p.lay.addWidget(w, p.lay.rowCount(), 0, 1, 4)
    again = QtWidgets.QPushButton("Restart selection")
    again.setToolTip("Clear both selections")
    again.clicked.connect(lambda: toolbar.measurer.restart() if toolbar.measurer is not None else None)
    p.lay.addWidget(again, p.lay.rowCount(), 0, 1, 2)

    def fill(m):
        picks = m.picks
        p.first.setText("Selection 1: " + (describe(*picks[0]) if picks else "none"))
        p.second.setText("Selection 2: " + (describe(*picks[1]) if len(picks) > 1 else "none"))
        r = m.result()
        if r is None:
            p.out.setText("")
            toolbar.place()
            return
        rows = ["<b>Distance %.3f mm</b>" % r["distance"],
                "X %.3f   Y %.3f   Z %.3f" % (r["dx"], r["dy"], r["dz"])]
        if r["angle"] is not None:
            rows.append("Angle %.2f°" % r["angle"])
        if r["centres"] is not None:
            rows.append("Centre to centre %.3f mm" % r["centres"])
        p.out.setText("<br>".join(rows))
        toolbar.place()                  # the panel grows to its new rows
    p.fill = fill
    p.setMinimumWidth(300)
    return p
