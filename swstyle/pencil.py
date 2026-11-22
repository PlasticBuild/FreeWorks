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

import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import contextbar, paths
from .widgets import alive

Qt = QtCore.Qt

PARAM = "PencilCursor"
POINTER = 32                 # FreeCAD's tool pointer: 32 px square, the crosshair at (8, 8)
HOT = 8
PICTURE = 10                 # the tool's picture fills the pointer from here on
TAIL = 16                    # each relation symbol FreeCAD adds to the right, 16 px, at y 16
TIP = 1                      # the pencil's tip, the pointer's hotspot, in our pixmap
LENGTH = 34                  # the pencil along its own axis
BOX = 20                     # the tool's picture sits in a white box under the pencil
BOX_AT = (4, 27)
TAIL_AT = (26, 29)           # relation symbols, right of the box
HEIGHT = 48
INK = "#262626"              # pencil outline, tool picture
BORDER = "#8c8c8c"
CACHE = 48                   # pointers kept (FreeCAD makes a new one each time a relation shows)

SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">
<g transform="translate(%(tip)d,%(tip)d) rotate(45)" stroke="%(ink)s" stroke-width="1.1" stroke-linejoin="round">
 <polygon points="0,0 8,-4 8,4" fill="#e6d2a6"/>
 <polygon points="0,0 2.8,-1.2 2.8,1.2" fill="%(ink)s" stroke="none"/>
 <rect x="8" y="-4" width="20" height="8" fill="#f6c431"/>
 <line x1="8" y1="-1.3" x2="28" y2="-1.3" stroke="#d9a40f" stroke-width="0.8"/>
 <line x1="8" y1="1.3" x2="28" y2="1.3" stroke="#d9a40f" stroke-width="0.8"/>
 <rect x="28" y="-4" width="3" height="8" fill="#a8a8a8"/>
 <rect x="31" y="-4" width="3" height="8" rx="1.5" fill="#ee8ea7"/>
</g></svg>"""


def enabled():
    return paths.params().GetBool(PARAM, True)


def _view():
    try:
        return Gui.ActiveDocument.ActiveView
    except Exception:
        return None


# --------------------------------------------------------------------------- the pointer
def is_tool_pointer(pixmap, hotspot):
    """FreeCAD's sketch tool pointer: 32 px high, 32 px wide plus 16 per relation
    symbol, the crosshair's centre at (8, 8); all in device pixels."""
    dpr = pixmap.devicePixelRatio() or 1.0
    unit = round(TAIL * dpr)
    return (unit > 0 and pixmap.height() == 2 * unit and pixmap.width() >= 2 * unit
            and pixmap.width() % unit == 0
            and hotspot == QtCore.QPoint(round(HOT * dpr), round(HOT * dpr)))


def _tinted(pixmap, colour):
    """The pixmap's shape in one colour: its alpha with the colour everywhere."""
    image = QtGui.QImage(pixmap.size(), QtGui.QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(pixmap.devicePixelRatio())
    image.fill(QtGui.QColor(colour))
    painter = QtGui.QPainter(image)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return QtGui.QPixmap.fromImage(image)


def _pencil(dpr):
    from PySide6.QtSvg import QSvgRenderer
    svg = SVG % {"tip": TIP, "ink": INK}
    return QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))


def pencil_pointer(pixmap):
    ""

    dpr = pixmap.devicePixelRatio() or 1.0
    unit = round(TAIL * dpr)
    tail = pixmap.width() // unit - 2
    width = max(TIP + LENGTH * 0.7072 + 6, TAIL_AT[0] + TAIL * tail + 1, BOX_AT[0] + BOX + 1)
    out = QtGui.QPixmap(round(width * dpr), round(HEIGHT * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    painter = QtGui.QPainter(out)
    painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
    # the tool's picture, FreeCAD's red lines in ink, in a white box under the pencil
    picture = pixmap.copy(round(PICTURE * dpr), round(PICTURE * dpr),
                          round((POINTER - PICTURE) * dpr), round((POINTER - PICTURE) * dpr))
    picture = picture.scaled(round((BOX - 2) * dpr), round((BOX - 2) * dpr),
                             Qt.KeepAspectRatio, Qt.SmoothTransformation)
    picture.setDevicePixelRatio(dpr)
    box = QtCore.QRectF(BOX_AT[0], BOX_AT[1], BOX, BOX)
    painter.fillRect(box, QtGui.QColor(255, 255, 255, 235))
    painter.setPen(QtGui.QPen(QtGui.QColor(BORDER), 1))
    painter.drawRect(box.adjusted(0.5, 0.5, -0.5, -0.5))
    painter.drawPixmap(QtCore.QPointF(BOX_AT[0] + 1, BOX_AT[1] + 1), _tinted(picture, INK))
    # the relation symbols, as FreeCAD draws them
    for i in range(tail):
        symbol = pixmap.copy((2 + i) * unit, unit, unit, unit)
        symbol.setDevicePixelRatio(dpr)
        painter.drawPixmap(QtCore.QPointF(TAIL_AT[0] + TAIL * i, TAIL_AT[1]), symbol)
    _pencil(dpr).render(painter, QtCore.QRectF(0, 0, 28, 28))
    painter.end()
    from . import hidpi as _hidpi   # hidpi-1119: logical hotspot on Windows, as FreeCAD's sketcher
    return QtGui.QCursor(out, *_hidpi.hotspot(TIP, TIP, out))


# --------------------------------------------------------------------------- the swap
class PencilCursor(QtCore.QObject):
    """Swaps FreeCAD's sketch tool pointer for the pencil as it is set on the 3D view."""

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.mw = Gui.getMainWindow()
        self._watched = []
        self._made = {}          # FreeCAD's pointer pixmap key -> (pencil pointer, FreeCAD's pointer)
        self._ours = {}          # pencil pointer pixmap key -> FreeCAD's pointer
        self._applying = False
        self.swaps = 0           # for checks
        self.mdi = self.mw.findChild(QtWidgets.QMdiArea)
        if self.mdi is not None:
            self.mdi.subWindowActivated.connect(self.attach)
        QtCore.QTimer.singleShot(0, self.attach)

    def attach(self, *args):
        self._watched = [w for w in self._watched if alive(w)]
        view = self.shell.view_widget()
        if view is None or not alive(view):
            return
        view.installEventFilter(self)
        if view not in self._watched:
            self._watched.append(view)
        if self.shell.enabled and enabled():
            self.swap(view)

    def remove(self):
        for view in self._watched:
            if alive(view):
                self.restore(view)
                view.removeEventFilter(self)
        self._watched = []
        if self.mdi is not None and alive(self.mdi):
            try:
                self.mdi.subWindowActivated.disconnect(self.attach)
            except Exception as _fw_err:
                _fw_log("pencil.py:171", _fw_err)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.CursorChange and not self._applying:
            if self.shell.enabled and enabled():
                self.swap(obj)
            else:
                self.restore(obj)
        return False

    def ours(self, view):
        """FreeCAD's pointer behind the pencil the view shows, or None."""
        cursor = view.cursor()
        if cursor.shape() != Qt.BitmapCursor:
            return None
        return self._ours.get(cursor.pixmap().cacheKey())

    def swap(self, view):
        cursor = view.cursor()
        if cursor.shape() != Qt.BitmapCursor:
            return False
        pixmap = cursor.pixmap()
        key = pixmap.cacheKey()
        if key in self._ours or not is_tool_pointer(pixmap, cursor.hotSpot()):
            return False
        if contextbar.sketch_in_edit() is None:
            return False
        made = self._made.get(key)
        if made is None:
            if len(self._made) >= CACHE:
                self._made.clear()
                self._ours.clear()
            try:
                pencil = pencil_pointer(pixmap)
            except Exception:
                return False
            made = self._made[key] = (pencil, QtGui.QCursor(cursor))
            self._ours[pencil.pixmap().cacheKey()] = made[1]
        self._set(view, made[0])
        self.swaps += 1
        return True

    def restore(self, view):
        original = self.ours(view)
        if original is not None:
            self._set(view, original)

    def _set(self, view, cursor):
        self._applying = True
        try:
            view.setCursor(cursor)
        finally:
            self._applying = False
