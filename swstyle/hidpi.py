"""hidpi-1119: pictures the add-on draws itself, made at the screen's scale.

On a 175 % screen a picture drawn at 1:1 is enlarged by Qt and looks soft, and a cursor drawn at
1:1 looks blurred. canvas() gives a pixmap with the screen's device pixel ratio set, so painting
code keeps its logical coordinates and the result is sharp. hotspot() gives a cursor hotspot the
way FreeCAD's own sketcher does it: logical pixels on Windows and macOS, device pixels on X11."""
from PySide import QtGui


def ratio():
    """The largest device pixel ratio of the screens (1.75 on a 175 % screen), never below 1."""
    try:
        values = [float(s.devicePixelRatio()) for s in QtGui.QGuiApplication.screens()]
    except Exception:
        values = []
    return max([1.0] + values)


def canvas(width, height, scale=None):
    """A QPixmap of width x height logical pixels with the screen's device pixel ratio set."""
    scale = ratio() if scale is None else float(scale)
    pixmap = QtGui.QPixmap(max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def hotspot(x, y, pixmap):
    """The QCursor hotspot for a point (x, y) given in the pixmap's logical pixels."""
    scale = pixmap.devicePixelRatio() or 1.0
    try:
        xcb = QtGui.QGuiApplication.platformName() == "xcb"
    except Exception:
        xcb = False
    if xcb:
        return int(round(x * scale)), int(round(y * scale))
    return int(round(x)), int(round(y))
