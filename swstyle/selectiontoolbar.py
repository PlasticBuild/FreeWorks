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
from PySide import QtCore, QtGui, QtWidgets

from .widgets import alive

Qt = QtCore.Qt
HINT_MAGENTA = (0.9, 0.1, 0.9)
_EPS = 1e-6


# --------------------------------------------------------------------------- edge sets
def _index(shape, edge):
    for i, e in enumerate(shape.Edges):
        if e.isSame(edge):
            return i
    return None


def _faces_of(shape, edge):
    try:
        return list(shape.ancestorsOfType(edge, __import__("Part").Face))
    except Exception:
        return []


def _loop(face, edge):
    for wire in face.Wires:
        if any(e.isSame(edge) for e in wire.Edges):
            return list(wire.Edges)
    return []


def convexity(shape, edge):
    """'convex', 'concave' or None (tangent, seam or open edge)."""
    import Part
    faces = _faces_of(shape, edge)
    if len(faces) != 2 or faces[0].isSame(faces[1]):
        return None
    try:
        t = (edge.FirstParameter + edge.LastParameter) / 2.0
        p = edge.valueAt(t)
        tangent = edge.tangentAt(t)
        normals = []
        for f in faces:
            u, v = f.Surface.parameter(p)
            normals.append(f.normalAt(u, v))
        n1, n2 = normals
        if n1.cross(n2).Length < 1e-3:
            return None                     # tangent faces: neither
        size = max(edge.Length, 1.0) * 1e-3
        inward = n1.cross(tangent)
        inward.normalize()
        q = p + inward * size
        if faces[0].distToShape(Part.Vertex(q))[0] > size * 0.5:
            inward = inward * -1.0
        return "concave" if n2.dot(inward) > 0 else "convex"
    except Exception:
        return None


def _feature_edges(panel, edge):
    """Edges of the faces that the feature which made one of this edge's faces added."""
    from . import filletpm
    shape = panel.base.Shape
    faces = _faces_of(shape, edge)
    if not faces:
        return []
    feature = panel.base
    while feature is not None:
        before = getattr(feature, "BaseFeature", None)
        try:
            made = filletpm.new_faces(before.Shape, feature.Shape) if before is not None else list(feature.Shape.Faces)
        except Exception:
            made = []
        if made and any(_on_any(f, made) for f in faces):
            found = [f for f in shape.Faces if _on_any(f, made)]
            edges = []
            for f in found:
                for e in f.Edges:
                    if not any(e.isSame(x) for x in edges):
                        edges.append(e)
            return edges
        feature = before
    return []


def _on_any(face, faces):
    try:
        u0, u1, v0, v1 = face.ParameterRange
        p = face.valueAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        import Part
        vertex = Part.Vertex(p)
        return any(f.distToShape(vertex)[0] < 1e-5 for f in faces)
    except Exception:
        return False


def edge_sets(panel, sub):
    """[(kind, tooltip stem, [edge names])] for the edge picked as sub (names on panel.base)."""
    shape = panel.base.Shape
    try:
        edge = shape.getElement(sub)
    except Exception:
        return []
    sets = []
    faces = _faces_of(shape, edge)
    for i, face in enumerate(faces[:2]):
        loop = _loop(face, edge)
        if len(loop) > 1:
            sets.append(("start" if i == 0 else "end",
                         "Connected to %s loop" % ("start" if i == 0 else "end"), loop))
    feature = _feature_edges(panel, edge)
    if len(feature) > 1:
        sets.append(("feature", "Connected to feature", feature))
    convex, concave = [], []
    for e in shape.Edges:
        kind = convexity(shape, e)
        if kind == "convex":
            convex.append(e)
        elif kind == "concave":
            concave.append(e)
    if convex:
        sets.append(("convex", "All convex", convex))
    if concave:
        sets.append(("concave", "All concave", concave))
    out = []
    for kind, stem, edges in sets:
        names = []
        for e in edges:
            i = _index(shape, e)
            if i is not None and "Edge%d" % (i + 1) not in names:
                names.append("Edge%d" % (i + 1))
        if not names or names == [sub]:
            continue
        out.append((kind, stem, names))
    return out


def _side_edges(shape, face, wires):
    """Edges that leave face from a vertex of wires without lying on face."""
    on = list(face.Edges)
    out = []
    for w in wires:
        for v in w.Vertexes:
            try:
                touching = shape.ancestorsOfType(v, __import__("Part").Edge)
            except Exception:
                touching = []
            for e in touching:
                if any(e.isSame(x) for x in on) or any(e.isSame(x) for x in out):
                    continue
                out.append(e)
    return out


def _far_loops(shape, face, wires):
    """The loops at the far ends of the side faces that stand on wires (the top or bottom
    edges of a boss or a cut made from those loops)."""
    import Part
    on = list(face.Edges)
    sides = []
    for w in wires:
        for e in w.Edges:
            for f in _faces_of(shape, e):
                if not f.isSame(face) and not any(f.isSame(x) for x in sides):
                    sides.append(f)
    side_edges = _side_edges(shape, face, wires)
    out = []
    for f in sides:
        for e in f.Edges:
            if any(e.isSame(x) for x in on) or any(e.isSame(x) for x in side_edges):
                continue
            # an edge shared by two side faces runs along the extrusion, not across it
            if any(g.isSame(f) is False and any(g.isSame(s) for s in sides) for g in _faces_of(shape, e)):
                continue
            if not any(e.isSame(x) for x in out):
                out.append(e)
    return out


def face_sets(panel, sub):
    ""


    shape = panel.base.Shape
    try:
        face = shape.getElement(sub)
    except Exception:
        return []
    outer = face.OuterWire
    inner = [w for w in face.Wires if not w.isSame(outer)]
    sets = [("outer", "Outer edges", list(outer.Edges))]
    if inner:
        sets.append(("inner", "Inner edges", [e for w in inner for e in w.Edges]))
    sets.append(("outside", "Edges outside of face", _side_edges(shape, face, [outer])))
    if inner:
        sets.append(("extrusion", "Inner edges on extrusions", _far_loops(shape, face, inner)))
    out = []
    for kind, stem, edges in sets:
        names = []
        for e in edges:
            i = _index(shape, e)
            if i is not None and "Edge%d" % (i + 1) not in names:
                names.append("Edge%d" % (i + 1))
        if names:
            out.append((kind, stem, names))
    return out


# --------------------------------------------------------------------------- pictures
def _glyph(kind):
    ""
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pm = _hidpi.canvas(20, 20)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    grey, blue = QtGui.QColor(110, 110, 110), QtGui.QColor(40, 110, 220)
    if kind == "close":
        p.setBrush(QtGui.QColor(200, 40, 40))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(3, 3, 14, 14, 2, 2)
        p.setPen(QtGui.QPen(Qt.white, 2))
        p.drawLine(7, 7, 13, 13)
        p.drawLine(13, 7, 7, 13)
    else:
        # a box drawn in grey, the edges the button adds in blue
        p.setPen(QtGui.QPen(grey, 1.2))
        box = [QtCore.QPointF(3, 7), QtCore.QPointF(13, 7), QtCore.QPointF(13, 17), QtCore.QPointF(3, 17)]
        top = [QtCore.QPointF(3, 7), QtCore.QPointF(7, 3), QtCore.QPointF(17, 3), QtCore.QPointF(13, 7)]
        side = [QtCore.QPointF(13, 7), QtCore.QPointF(17, 3), QtCore.QPointF(17, 13), QtCore.QPointF(13, 17)]
        for poly in (box, top, side):
            p.drawPolygon(QtGui.QPolygonF(poly))
        p.setPen(QtGui.QPen(blue, 2.2))
        if kind == "start":
            p.drawPolygon(QtGui.QPolygonF(top))
        elif kind == "end":
            p.drawPolygon(QtGui.QPolygonF(box))
        elif kind == "feature":
            for poly in (box, top, side):
                p.drawPolygon(QtGui.QPolygonF(poly))
        elif kind == "convex":
            p.drawLine(top[0], top[3])
            p.drawLine(top[3], side[1])
            p.drawLine(side[0], side[3])
        elif kind == "concave":
            p.drawLine(QtCore.QPointF(3, 17), QtCore.QPointF(8, 12))
            p.drawLine(QtCore.QPointF(8, 12), QtCore.QPointF(8, 4))
            p.drawLine(QtCore.QPointF(8, 12), QtCore.QPointF(17, 12))
        elif kind == "outer":
            p.drawPolygon(QtGui.QPolygonF(top))
        elif kind in ("inner", "extrusion"):
            hole = [QtCore.QPointF(7, 5), QtCore.QPointF(13, 5), QtCore.QPointF(11, 6.5), QtCore.QPointF(5.5, 6.5)]
            p.drawPolygon(QtGui.QPolygonF(hole))
            if kind == "extrusion":
                p.drawLine(QtCore.QPointF(5.5, 6.5), QtCore.QPointF(5.5, 12))
                p.drawLine(QtCore.QPointF(11, 6.5), QtCore.QPointF(11, 12))
        elif kind == "outside":
            p.drawLine(box[0], box[3])
            p.drawLine(box[1], box[2])
            p.drawLine(side[1], side[2])
    p.end()
    return QtGui.QIcon(pm)


# --------------------------------------------------------------------------- the strip
class _Button(QtWidgets.QToolButton):
    def __init__(self, strip, kind, tip, names):
        super().__init__(strip)
        self.strip, self.names = strip, names
        self.setAutoRaise(True)
        self.setIcon(_glyph(kind))
        self.setIconSize(QtCore.QSize(20, 20))
        self.setToolTip(tip)
        self.setObjectName("SWSelectionToolbar_" + kind)

    # An exception in a Qt event override can bring FreeCAD down: keep these quiet.
    def event(self, event):
        try:
            t = event.type()
            if t == QtCore.QEvent.Enter:
                self.strip.hint(self.names)
            elif t == QtCore.QEvent.Leave:
                self.strip.hint([])
        except Exception as _fw_err:
            _fw_log("selectiontoolbar.py:307", _fw_err)
        return super().event(event)


class Strip(QtWidgets.QFrame):
    def __init__(self, panel, view_widget):
        super().__init__(view_widget)
        self.panel = panel
        self.setObjectName("SWSelectionToolbar")
        self.setStyleSheet("QFrame#SWSelectionToolbar { background: rgba(245,245,245,230);"
                           " border: 1px solid #b8b8b8; border-radius: 2px; }"
                           "QToolTip { color: black; background: #ffffe1; }")
        self.row = QtWidgets.QHBoxLayout(self)
        self.row.setContentsMargins(2, 2, 2, 2)
        self.row.setSpacing(1)
        self.anchor = None
        self.hide()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.place)
        self.timer.start(60)

    def show_for(self, sub):
        self.hint([])
        while self.row.count():
            w = self.row.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        try:
            if hasattr(self.panel, "selection_sets"):       # a page with its own sets (Delete Face: faces)
                sets = self.panel.selection_sets(sub)
                self.anchor = self.panel.base.Shape.getElement(sub).CenterOfMass
            elif sub.startswith("Face"):
                sets = face_sets(self.panel, sub)
                face = self.panel.base.Shape.getElement(sub)
                self.anchor = face.CenterOfMass
            else:
                sets = edge_sets(self.panel, sub)
                edge = self.panel.base.Shape.getElement(sub)
                self.anchor = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        except Exception:
            sets, self.anchor = [], None
        if not sets:
            self.close_strip()
            return
        for kind, stem, names in sets:
            unit = getattr(self.panel, "set_unit", "Edges")
            b = _Button(self, kind, "%s, %d %s" % (stem, len(names), unit), names)
            b.clicked.connect(lambda checked=False, n=names: self.take(n))
            self.row.addWidget(b)
        close = QtWidgets.QToolButton(self)
        close.setAutoRaise(True)
        close.setObjectName("SWSelectionToolbar_close")
        close.setIcon(_glyph("close"))
        close.setIconSize(QtCore.QSize(20, 20))
        close.setToolTip("Close")
        close.clicked.connect(self.close_strip)
        self.row.addWidget(close)
        self.adjustSize()
        self.place()

    def hint(self, names):
        overlay = getattr(self.panel, "overlay", None)
        if overlay is None:
            return
        edges = []
        for n in names:
            try:
                edges.append(self.panel.base.Shape.getElement(n))
            except Exception as _fw_err:
                _fw_log("selectiontoolbar.py:376", _fw_err)
        overlay.show_hint(edges)

    def take(self, names):
        self.hint([])
        panel = self.panel
        if "" in panel.items:
            panel.items.remove("")
        for n in names:
            if n not in panel.items:
                panel.items.append(n)
        self.close_strip()
        panel.update()

    def close_strip(self):
        self.hint([])
        self.anchor = None
        self.hide()

    def place(self):
        if self.anchor is None or not alive(self):
            if alive(self):
                self.hide()
            return
        try:
            view = Gui.ActiveDocument.ActiveView
            x, y = view.getPointOnViewport(self.anchor)
        except Exception:
            self.hide()
            return
        parent = self.parentWidget()
        ratio = parent.devicePixelRatioF() if hasattr(parent, "devicePixelRatioF") else 1.0
        x, y = x / ratio, parent.height() - y / ratio

        self.move(int(max(0, x - self.width() - 8)), int(max(0, y - self.height() - 6)))
        if not self.isVisible():
            self.show()
            self.raise_()

    def remove(self):
        self.timer.stop()
        self.hint([])
        self.hide()
        self.deleteLater()
