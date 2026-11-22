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

import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import overridedrag

V = App.Vector
TITLE = "Sketch Ink"
STRAIGHT = 0.02         # largest bulge, as a share of the stroke's length, for a line
ROUND = 0.04            # largest radius error, as a share of the radius, for an arc or circle
CLOSED = 0.12           # largest gap between the ends, as a share of the length, for a circle


def _length(points):
    return sum((points[i + 1] - points[i]).Length for i in range(len(points) - 1))


def _circle(points):
    """Least-squares circle through points: (centre, radius, worst error / radius)."""
    n = len(points)
    sx = sum(p.x for p in points) / n
    sy = sum(p.y for p in points) / n
    suu = suv = svv = suuu = svvv = suvv = svuu = 0.0
    for p in points:
        u, v = p.x - sx, p.y - sy
        suu += u * u
        svv += v * v
        suv += u * v
        suuu += u * u * u
        svvv += v * v * v
        suvv += u * v * v
        svuu += v * u * u
    det = suu * svv - suv * suv
    if abs(det) < 1e-12:
        return None
    b1 = 0.5 * (suuu + suvv)
    b2 = 0.5 * (svvv + svuu)
    uc = (b1 * svv - b2 * suv) / det
    vc = (suu * b2 - suv * b1) / det
    centre = V(sx + uc, sy + vc, 0)
    radius = math.sqrt(uc * uc + vc * vc + (suu + svv) / n)
    worst = max(abs((p - centre).Length - radius) for p in points) / radius if radius > 1e-9 else 1e9
    return centre, radius, worst


ELLIPSE_FIT = 0.10      # largest error of a closed stroke from an ellipse, as a share of its axes
SLOT_FIT = 0.14         # largest error from a slot outline, as a share of the cap radius
OBLONG = 1.15           # a closed round stroke this much longer than wide is an ellipse, not a circle


def _frame(pts):
    """The stroke's middle and long direction (principal axis), and its points in that frame,
    centred on their bounding box."""
    n = len(pts)
    cx = sum(p.x for p in pts) / n
    cy = sum(p.y for p in pts) / n
    sxx = sum((p.x - cx) ** 2 for p in pts) / n
    syy = sum((p.y - cy) ** 2 for p in pts) / n
    sxy = sum((p.x - cx) * (p.y - cy) for p in pts) / n
    ang = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    d = (math.cos(ang), math.sin(ang))
    q = [((p.x - cx) * d[0] + (p.y - cy) * d[1], -(p.x - cx) * d[1] + (p.y - cy) * d[0]) for p in pts]
    du = (max(u for u, _ in q) + min(u for u, _ in q)) / 2.0
    dv = (max(v for _, v in q) + min(v for _, v in q)) / 2.0
    q = [(u - du, v - dv) for u, v in q]
    centre = V(cx + du * d[0] - dv * d[1], cy + du * d[1] + dv * d[0], 0)
    return centre, d, q


def _closed_shape(pts):
    """A closed stroke that is not a circle: ("ellipse", centre, axis, a, b) or ("slot", centre, axis,
    half length between the cap centres, cap radius), whichever fits it better, else None."""
    if len(pts) < 12:
        return None
    centre, d, q = _frame(pts)
    a = max(abs(u) for u, _ in q)
    b = max(abs(v) for _, v in q)
    if b < 1e-9 or a < OBLONG * b:
        return None
    best = None
    err = max(abs(math.hypot(u / a, v / b) - 1.0) for u, v in q)
    if err <= ELLIPSE_FIT:
        best = (err, ("ellipse", centre, d, a, b))
    h = a - b
    if h > 0.05 * b:
        def gap(u, v):
            return abs(math.hypot(u - max(-h, min(h, u)), v) - b) / b
        err = max(gap(u, v) for u, v in q)
        if err <= SLOT_FIT and (best is None or err < best[0]):
            best = (err, ("slot", centre, d, h, b))
    return best[1] if best else None


def recognise(points):
    """What a stroke is: ("line", a, b), ("circle", centre, r), ("arc", centre, r, a0, a1),
    ("ellipse", centre, axis, a, b), ("slot", centre, axis, half length, r) or ("spline", points)."""
    pts = [V(p.x, p.y, 0) for p in points]
    if len(pts) < 2:
        return None
    length = _length(pts)
    if length < 1e-6:
        return None
    a, b = pts[0], pts[-1]
    chord = b - a
    if chord.Length > 1e-9:
        d = chord * (1.0 / chord.Length)
        bulge = max(abs((p - a).x * d.y - (p - a).y * d.x) for p in pts)
        if bulge <= STRAIGHT * length:
            return ("line", a, b)
    fit = _circle(pts) if len(pts) >= 5 else None
    if fit is not None and fit[2] <= ROUND:
        c, r = fit[0], fit[1]
        if (b - a).Length <= CLOSED * length:
            return ("circle", c, r)
        angles = [math.atan2(p.y - c.y, p.x - c.x) for p in pts]
        turn = sum(((angles[i + 1] - angles[i] + math.pi) % (2 * math.pi)) - math.pi for i in range(len(angles) - 1))
        start, end = angles[0], angles[0] + turn
        if end < start:
            start, end = end, start
        return ("arc", c, r, start, end)
    if (b - a).Length <= CLOSED * length:

        other = _closed_shape(pts)
        if other is not None:
            return other
    return ("spline", pts)


def add(sketch, shape):
    """Adds what recognise() found; the new geometry index."""
    import Part
    z = V(0, 0, 1)
    kind = shape[0]
    if kind == "line":
        return sketch.addGeometry(Part.LineSegment(shape[1], shape[2]))
    if kind == "circle":
        return sketch.addGeometry(Part.Circle(shape[1], z, shape[2]))
    if kind == "arc":
        return sketch.addGeometry(Part.ArcOfCircle(Part.Circle(shape[1], z, shape[2]), shape[3], shape[4]))
    if kind == "ellipse":
        c, d, a, b = shape[1], shape[2], shape[3], shape[4]
        major = V(c.x + d[0] * a, c.y + d[1] * a, 0)
        minor = V(c.x - d[1] * b, c.y + d[0] * b, 0)
        g = sketch.addGeometry(Part.Ellipse(major, minor, c))
        try:
            sketch.exposeInternalGeometry(g)
        except Exception as _fw_err:
            _fw_log("sketchink.py:173", _fw_err)
        return g
    if kind == "slot":
        from .fwsketch import slot
        c, d, h, r = shape[1], shape[2], shape[3], shape[4]
        return slot.add_straight_slot(sketch, (c.x - d[0] * h, c.y - d[1] * h), (c.x + d[0] * h, c.y + d[1] * h), r)
    pts = shape[1]
    # thin the stroke out, then fit a cubic spline through it
    keep = [pts[0]]
    step = max(_length(pts) / 40.0, 1e-6)
    for p in pts[1:-1]:
        if (p - keep[-1]).Length >= step:
            keep.append(p)
    keep.append(pts[-1])
    if len(keep) < 4:
        return sketch.addGeometry(Part.LineSegment(keep[0], keep[-1]))
    spline = Part.BSplineCurve()
    spline.approximate(Points=keep, DegMin=3, DegMax=3, Tolerance=step * 0.25)
    g = sketch.addGeometry(spline)
    try:
        sketch.exposeInternalGeometry(g)
    except Exception as _fw_err:
        _fw_log("sketchink.py:195", _fw_err)
    return g


def _page_class():
    from pivy import coin
    from . import sketchtoolpm

    class _Ink(QtCore.QObject):
        """Captures strokes in the 3D view while the page is open."""

        def __init__(self, page):
            super().__init__()
            self.page = page
            self.stroke = None
            self.widget = None
            from .fwsketch import appevents
            appevents.listen(self, (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove))   # one application filter (fix65)

        def stop(self):
            self.page = None
            try:
                from .fwsketch import appevents
                appevents.stop(self)
            except Exception as _fw_err:
                _fw_log("sketchink.py:220", _fw_err)

        def eventFilter(self, obj, event):
            if not isinstance(event, QtCore.QEvent):
                return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
            page = self.page
            if page is None or not isinstance(obj, overridedrag._gl_class()):
                return False
            t = event.type()
            QE = QtCore.QEvent
            if t == QE.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                self.widget = obj
                self.stroke = [overridedrag.local(page.sketch, obj, event.position())]
                page.draw(self.stroke)
                return True
            if self.stroke is not None and t == QE.MouseMove:
                p = overridedrag.local(page.sketch, obj, event.position())
                if (p - self.stroke[-1]).Length > 1e-9:
                    self.stroke.append(p)
                    page.draw(self.stroke)
                return True
            if self.stroke is not None and t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
                stroke, self.stroke = self.stroke, None
                page.draw([])
                page.ink(stroke)
                return True
            return False

    class InkPage(sketchtoolpm.ToolPage):
        TITLE = TITLE
        ICON = "SKETCH_INK"
        PIXMAP = "Sketcher_CreateBSpline"
        TRANSACTION = TITLE

        def build(self):
            g = self.group("Sketch Ink")
            text = QtWidgets.QLabel("Draw in the sketch with the left mouse button (or a pen).", g.body)
            text.setWordWrap(True)
            g.content.addWidget(text)
            self.shapes = QtWidgets.QCheckBox("Recognize shapes", g.body)
            self.shapes.setObjectName("SWInkShapes")
            self.shapes.setChecked(True)
            g.content.addWidget(self.shapes)
            self.made = []
            self.node = None
            self.coords = None
            self.lines = None
            self.ink_filter = _Ink(self)

        def draw(self, stroke):
            """The stroke so far, drawn over the sketch."""
            view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
            if view is None:
                return
            if self.node is None:
                self.node = coin.SoSeparator()
                style = coin.SoDrawStyle()
                style.lineWidth.setValue(2)
                colour = coin.SoBaseColor()
                colour.rgb.setValue(0.1, 0.3, 0.9)
                self.coords = coin.SoCoordinate3()
                self.lines = coin.SoLineSet()
                for child in (style, colour, self.coords, self.lines):
                    self.node.addChild(child)
                view.getSceneGraph().addChild(self.node)
            pl = self.sketch.getGlobalPlacement()
            pts = [pl.multVec(p) for p in stroke]
            self.coords.point.setNum(0)
            if len(pts) >= 2:
                self.coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
                self.lines.numVertices.setValues(0, 1, [len(pts)])
            else:
                self.lines.numVertices.setNum(0)

        def ink(self, stroke):
            shape = recognise(stroke)
            if shape is None:
                return
            if not self.shapes.isChecked() and shape[0] != "spline":
                shape = ("spline", [V(p.x, p.y, 0) for p in stroke]) if len(stroke) >= 4 else shape
            doc = self.doc
            doc.openTransaction(TITLE)
            try:
                g = add(self.sketch, shape)
                self.sketch.solve()
            finally:
                doc.commitTransaction()
            self.made.append((shape[0], g))
            sketchtoolpm._refresh(self.sketch)
            self.show_note("%s added." % shape[0].capitalize())

        def closing(self):
            self.ink_filter.stop()
            if self.node is not None:
                try:
                    Gui.ActiveDocument.ActiveView.getSceneGraph().removeChild(self.node)
                except Exception as _fw_err:
                    _fw_log("sketchink.py:317", _fw_err)
                self.node = None

    return InkPage


class _Command:
    def GetResources(self):
        return {"Pixmap": "Sketcher_CreateBSpline", "MenuText": TITLE,
                "ToolTip": "Strokes drawn freehand become lines, arcs, circles, ellipses, slots or splines", "CmdType": "ForEdit"}

    def IsActive(self):
        from . import contextbar
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        from . import contextbar, sketchtoolpm
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(_page_class()(sketch))


def register():
    try:
        if "SWStyle_SketchInk" not in Gui.listCommands():
            Gui.addCommand("SWStyle_SketchInk", _Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Sketch Ink command not added (%s)\n" % error)
