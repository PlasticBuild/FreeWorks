"""The slicers' orientation cube at the bottom left of the plate view: a small cube with Top / Front / Left /
Right / Back / Bottom that turns with the view; a click on a face turns the view to look at that face (a
turntable view, as the slicers' number keys 0 to 6). Our own drawing."""
import math

import FreeCAD as App
from PySide import QtCore, QtGui, QtWidgets

from . import style
from .slicernav import Camera

Qt = QtCore.Qt
SIZE = 110

# face name, outward normal (bed coordinates: X right, Y back, Z up), label, corner indexes into CORNERS
CORNERS = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
FACES = [("Top", (0, 0, 1), (4, 5, 6, 7)), ("Bottom", (0, 0, -1), (3, 2, 1, 0)),
         ("Front", (0, -1, 0), (0, 1, 5, 4)), ("Back", (0, 1, 0), (2, 3, 7, 6)),
         ("Left", (-1, 0, 0), (3, 0, 4, 7)), ("Right", (1, 0, 0), (1, 2, 6, 5))]


class ViewCube(QtWidgets.QWidget):
    def __init__(self, bed, host):
        super().__init__(host)
        self.bed, self.host = bed, host
        self.setFixedSize(SIZE, SIZE)
        self.setMouseTracking(True)
        self.setObjectName("SWSlicerViewCube")
        self._key = None
        self._hover = None
        self._polys = []
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        host.installEventFilter(self)
        self.show()
        self.place()

    # ------------------------------------------------------------------ placement and state
    def eventFilter(self, obj, event):
        if obj is self.host and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self.place()
        return False

    def place(self):
        self.move(84, max(0, self.host.height() - SIZE - 20))
        self.raise_()

    def axes(self):
        view = self.bed.view
        if view is None:
            return None
        try:
            return Camera(view).axes()          # right, up, forward (world)
        except Exception:
            return None

    def poll(self):
        ax = self.axes()
        key = None if ax is None else tuple(round(c, 3) for v in ax for c in (v.x, v.y, v.z))
        if key != self._key:
            self._key = key
            self.update()

    # ------------------------------------------------------------------ drawing
    def _project(self, ax, p):
        r, u, f = ax
        x = p[0] * r.x + p[1] * r.y + p[2] * r.z
        y = p[0] * u.x + p[1] * u.y + p[2] * u.z
        z = p[0] * f.x + p[1] * f.y + p[2] * f.z          # larger = farther
        s = SIZE * 0.26
        return QtCore.QPointF(SIZE / 2 + x * s, SIZE / 2 - y * s), z

    def paintEvent(self, event):
        ax = self.axes()
        if ax is None:
            return
        T = style.T
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        faces = []
        for name, normal, idx in FACES:
            r, u, f = ax
            facing = normal[0] * f.x + normal[1] * f.y + normal[2] * f.z    # < 0: towards the viewer
            pts = [self._project(ax, CORNERS[i])[0] for i in idx]
            faces.append((facing, name, normal, pts))
        self._polys = []
        for facing, name, normal, pts in sorted(faces, key=lambda t: -t[0]):
            if facing >= 0:
                continue                                                      # the far side
            poly = QtGui.QPolygonF(pts)
            hot = name == self._hover
            shade = 0.78 + 0.22 * min(1.0, -facing)
            base = QtGui.QColor(T.hex("accent") if hot else T.hex("pane"))
            base = QtGui.QColor(int(base.red() * shade), int(base.green() * shade), int(base.blue() * shade))
            painter.setBrush(base)
            painter.setPen(QtGui.QPen(QtGui.QColor(T.hex("line_mid")), 1.2))
            painter.drawPolygon(poly)
            c = poly.boundingRect().center()
            painter.setPen(QtGui.QColor(T.hex("text")))
            font = painter.font()
            font.setPointSizeF(7.5 if -facing > 0.5 else 6.5)
            painter.setFont(font)
            painter.drawText(poly.boundingRect(), Qt.AlignCenter, name)
            self._polys.append((name, normal, poly))
        painter.end()

    # ------------------------------------------------------------------ mouse
    def _face_at(self, pos):
        for name, normal, poly in reversed(self._polys):          # the nearest drawn last
            if poly.containsPoint(QtCore.QPointF(pos), Qt.OddEvenFill):
                return name, normal
        return None, None

    def mouseMoveEvent(self, event):
        name, _ = self._face_at(event.position().toPoint())
        if name != self._hover:
            self._hover = name
            self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def mousePressEvent(self, event):
        name, normal = self._face_at(event.position().toPoint())
        if name is None or event.button() != Qt.LeftButton:
            return
        view = self.bed.view
        if view is None:
            return
        cam = Camera(view)
        t = cam.target()
        dist = float(cam.cam.focalDistance.getValue())
        n = App.Vector(*normal)
        if name in ("Top", "Bottom"):
            n = n * 1.0 + App.Vector(0, -1e-3, 0)
            n.normalize()
        cam.look(t + n * dist, t)
        self.update()

    def remove(self):
        self.timer.stop()
        self.host.removeEventFilter(self)
        self.hide()
        self.setParent(None)
        self.deleteLater()
