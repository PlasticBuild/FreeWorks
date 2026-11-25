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
from PySide import QtCore, QtGui, QtWidgets

from . import contextbar, sketchtoolpm
from .widgets import alive

Qt = QtCore.Qt

SNAP = 8.0                       # pixels a click may be from a sketch point to land on it
RHO = (0.01, 0.99)
NAME = "SWConicPreview"


def weight(rho):
    return rho / (1.0 - rho)


def rho_of(w):
    return w / (1.0 + w)


def curve(start, top, end, rho):
    import Part
    bs = Part.BSplineCurve()
    bs.buildFromPolesMultsKnots([start, top, end], [3, 3], [0.0, 1.0], False, 2, [1.0, weight(rho), 1.0])
    return bs


def rho_from_pointer(start, top, end, point):
    ""

    mid = (start + end) * 0.5
    axis = top - mid
    if axis.Length < 1e-9:
        return None
    t = (point - mid).dot(axis) / axis.dot(axis)
    return min(max(t, RHO[0]), RHO[1])


OPTION_PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchTools"


def add_conic(sketch, start, top, end, rho, ties=(None, None, None)):
    """Adds the conic, its poles and the weight that holds Rho; ties are (geo, pos) of sketch points
    for the start, the top vertex and the end, or None. Returns the conic's geometry index."""
    import Sketcher
    g = sketch.addGeometry(curve(start, top, end, rho), False)
    sketch.exposeInternalGeometry(g)
    poles = {}
    for c in sketch.Constraints:
        if c.Type == "InternalAlignment" and c.Second == g and \
                type(sketch.Geometry[c.First]).__name__ == "Circle":
            poles[getattr(c, "InternalAlignmentIndex", len(poles))] = c.First
    cons = []
    middle = poles.get(1)
    if middle is not None:
        # with Rho 0.5 every weight is 1 and exposeInternalGeometry ties the middle pole Equal to
        # the end poles: Rho's own Weight would then be redundant (and Rho could not change)
        for i in reversed(range(len(sketch.Constraints))):
            c = sketch.Constraints[i]
            if c.Type == "Equal" and middle in (c.First, c.Second):
                sketch.delConstraint(i)
        cons.append(Sketcher.Constraint("Weight", middle, weight(rho)))
    targets = ((g, 1), (poles.get(1), 3) if middle is not None else None, (g, 2))
    for tie, mine in zip(ties, targets):
        if tie is not None and mine is not None and mine[0] is not None:
            cons.append(Sketcher.Constraint("Coincident", mine[0], mine[1], tie[0], tie[1]))
    if cons:
        sketch.addConstraint(cons)

    circles = set(poles.values())
    for i, c in enumerate(sketch.Constraints):
        if c.Type in ("Weight", "Equal") and c.First in circles:
            try:
                sketch.setVirtualSpace(i, True)
            except Exception as _fw_err:
                _fw_log("conic.py:106", _fw_err)
    sketch.solve()
    return g


# --------------------------------------------------------------------------- the preview
class Preview:
    def __init__(self):
        self.node = None
        self.view = None

    def clear(self):
        if self.node is not None and self.view is not None:
            try:
                self.view.getSceneGraph().removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("conic.py:122", _fw_err)
        self.node = self.view = None

    def show(self, view, lines, points):
        """lines: [[global points]], drawn on top; points: global points marked."""
        from pivy import coin
        self.clear()
        root = coin.SoAnnotation()
        root.setName(NAME)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        root.addChild(light)
        colour = coin.SoBaseColor()
        colour.rgb.setValue(0.1, 0.35, 0.9)
        root.addChild(colour)
        style = coin.SoDrawStyle()
        style.lineWidth = 2
        style.pointSize = 7
        root.addChild(style)
        lines = [line for line in lines if len(line) >= 2]
        if lines:
            coords = coin.SoCoordinate3()
            pts = [(p.x, p.y, p.z) for line in lines for p in line]
            coords.point.setValues(0, len(pts), pts)
            root.addChild(coords)
            ls = coin.SoLineSet()
            ls.numVertices.setValues(0, len(lines), [len(line) for line in lines])
            root.addChild(ls)
        if points:
            sep = coin.SoSeparator()
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
            sep.addChild(coords)
            sep.addChild(coin.SoPointSet())
            root.addChild(sep)
        view.getSceneGraph().addChild(root)
        self.node, self.view = root, view


# --------------------------------------------------------------------------- the PropertyManager
class ConicPage(sketchtoolpm.ToolPage):
    OK_ONLY = True
    TITLE = "Conic"
    ICON = "SKETCH_CONIC"
    PIXMAP = "Sketcher_CreateHyperbolic_Arc"
    TRANSACTION = "Conic"

    def build(self):

        g = self.group("Options")
        self.construction = QtWidgets.QCheckBox("For construction", g.body)
        self.construction.setObjectName("SWConicForConstruction")
        self.construction.setChecked(App.ParamGet(OPTION_PARAMS).GetBool("ConicForConstruction", False))
        self.construction.toggled.connect(
            lambda on: App.ParamGet(OPTION_PARAMS).SetBool("ConicForConstruction", bool(on)))
        g.content.addWidget(self.construction)
        g = self.group("Parameters")
        form = QtWidgets.QFormLayout()
        self.readouts = []
        for label in ("Start", "End", "Top vertex"):
            value = QtWidgets.QLabel("-", g.body)
            form.addRow(label + ":", value)
            self.readouts.append(value)
        self.rho = QtWidgets.QDoubleSpinBox(g.body)
        self.rho.setObjectName("SWConicRho")
        self.rho.setRange(RHO[0], RHO[1])
        self.rho.setDecimals(4)
        self.rho.setSingleStep(0.05)
        self.rho.setValue(0.5)
        self.rho.setToolTip("0.5 is a parabola, less an ellipse, more a hyperbola")
        self.rho.setKeyboardTracking(False)
        form.addRow("Rho:", self.rho)
        g.content.addLayout(form)
        self.tool = None

    def accept(self):
        if self.tool is not None:
            self.tool.finish_typed()
            self.tool.stop(close_page=False)
        sketchtoolpm.ToolPage.accept(self)

    def reject(self):
        if self.tool is not None:
            self.tool.stop(close_page=False)
        sketchtoolpm.ToolPage.reject(self)

    def leave(self):
        if self.tool is not None:
            self.tool.stop(close_page=False)
        sketchtoolpm.ToolPage.leave(self)


# --------------------------------------------------------------------------- the tool
def _cursor():
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(32, 32)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 3))
    for pen in (QtGui.QPen(QtGui.QColor(255, 255, 255), 3), QtGui.QPen(QtGui.QColor(0, 0, 0), 1)):
        p.setPen(pen)
        p.drawLine(4, 0, 4, 8)
        p.drawLine(0, 4, 8, 4)
        path = QtGui.QPainterPath(QtCore.QPointF(12, 28))
        path.quadTo(QtCore.QPointF(16, 10), QtCore.QPointF(30, 12))
        p.drawPath(path)
    p.end()
    return QtGui.QCursor(pix, *_hidpi.hotspot(4, 4, pix))


class ConicTool(QtCore.QObject):
    def __init__(self, sketch, page):
        super().__init__()
        self.sketch = sketch
        self.page = page
        page.tool = self
        self.points = []             # local sketch points picked: start, end, top vertex
        self.ties = []               # (geo, pos) or None for each
        self.pointer = None          # local point under the pointer
        self.rho_typed = False
        self.preview = Preview()
        self.made = []               # conics added, for checks
        self.viewer, self.widget = self._widgets()
        if self.widget is None:
            raise RuntimeError("no 3D view")
        self.widget.installEventFilter(self)
        self.viewer.installEventFilter(self)
        self.widget.setMouseTracking(True)
        self._old_cursor = self.widget.cursor()
        self._had_cursor = self.widget.testAttribute(Qt.WA_SetCursor)
        self.widget.setCursor(_cursor())
        page.rho.valueChanged.connect(self._rho_typed)
        self._note()

    @staticmethod
    def _widgets():
        from . import shell as shell_module
        sh = shell_module.shell()
        view = sh.view_widget() if sh is not None else None
        if view is None or not hasattr(view, "viewport"):
            return None, None
        return view, view.viewport()

    # ------------------------------------------------------------------ geometry
    def _placement(self):
        return self.sketch.getGlobalPlacement()

    def local(self, pos):
        """Viewport position -> the point on the sketch plane, in sketch coordinates."""
        view = Gui.ActiveDocument.ActiveView
        dpr = self.widget.devicePixelRatioF()
        x, y = pos.x() * dpr, view.getSize()[1] - pos.y() * dpr
        on_focal = App.Vector(view.getPoint((int(round(x)), int(round(y)))))
        direction = App.Vector(view.getViewDirection())
        pl = self._placement()
        normal = pl.Rotation.multVec(App.Vector(0, 0, 1))
        denom = direction.dot(normal)
        if abs(denom) < 1e-9:
            hit = on_focal
        else:
            hit = on_focal + direction * ((pl.Base - on_focal).dot(normal) / denom)
        p = pl.inverse().multVec(hit)
        return App.Vector(p.x, p.y, 0)

    def screen(self, local):
        view = Gui.ActiveDocument.ActiveView
        dpr = self.widget.devicePixelRatioF()
        x, y = view.getPointOnViewport(self._placement().multVec(local))
        return QtCore.QPointF(x / dpr, (view.getSize()[1] - y) / dpr)

    def snap(self, pos):
        """(local point, (geo, pos) or None): the sketch point within SNAP pixels, else the plane."""
        best = None
        candidates = [((-1, 1), App.Vector(0, 0, 0))]
        for g, geo in enumerate(self.sketch.Geometry):
            for p in (1, 2, 3):
                try:
                    candidates.append(((g, p), App.Vector(self.sketch.getPoint(g, p))))
                except Exception as _fw_err:
                    _fw_log("conic.py:302", _fw_err)
        for tie, point in candidates:
            q = self.screen(point)
            d = math.hypot(q.x() - pos.x(), q.y() - pos.y())
            if d <= SNAP and (best is None or d < best[0]):
                best = (d, point, tie)
        if best is not None:
            return best[1], best[2]
        return self.local(pos), None

    # ------------------------------------------------------------------ steps
    def _note(self):
        steps = ("Click the start point.", "Click the end point.", "Click the top vertex (where the end tangents meet).",
                 "Move to set Rho and click, or type Rho and press Enter.")
        self.page.show_note(steps[min(len(self.points), 3)])
        for label, point in zip(self.page.readouts, self.points + [None] * 3):
            label.setText("-" if point is None else "%.3f, %.3f" % (point.x, point.y))

    def _rho_typed(self, *args):
        if not getattr(self, "_setting_rho", False):
            self.rho_typed = True
            self.draw()

    def _set_rho(self, value):
        self._setting_rho = True
        try:
            self.page.rho.setValue(value)
        finally:
            self._setting_rho = False

    def draw(self):
        view = Gui.ActiveDocument.ActiveView
        pl = self._placement()
        pts = list(self.points)
        if self.pointer is not None and len(pts) < 3:
            pts.append(self.pointer)
        lines = []
        if len(pts) == 2:
            lines.append([pl.multVec(p) for p in pts])
        elif len(pts) >= 3:
            start, end, top = pts[0], pts[1], pts[2]
            if len(self.points) == 3 and self.pointer is not None and not self.rho_typed:
                rho = rho_from_pointer(start, top, end, self.pointer)
                if rho is not None:
                    self._set_rho(rho)
            try:
                bs = curve(start, top, end, self.page.rho.value())
                lines.append([pl.multVec(p) for p in bs.discretize(48)])
            except Exception as _fw_err:
                _fw_log("conic.py:351", _fw_err)
            lines.append([pl.multVec(start), pl.multVec(top), pl.multVec(end)])
        self.preview.show(view, lines, [pl.multVec(p) for p in pts])

    def click(self, pos):
        point, tie = self.snap(pos)
        if len(self.points) < 3:
            self.points.append(point)
            self.ties.append(tie)
            self.pointer = point
            self._note()
            self.draw()
            return
        self.make()

    def make(self):
        if len(self.points) < 3:
            return False
        start, end, top = self.points
        doc = self.sketch.Document
        doc.openTransaction("Conic")
        try:
            g = add_conic(self.sketch, start, top, end, self.page.rho.value(),
                          (self.ties[0], self.ties[2], self.ties[1]))
            if self.page.construction.isChecked():
                self.sketch.setConstruction(g, True)
            doc.commitTransaction()
            self.made.append(g)
        except Exception as error:
            doc.abortTransaction()
            self.page.show_note("Could not add the conic: %s" % error, True)
            return False
        self.sketch.recompute()
        self.points, self.ties, self.rho_typed = [], [], False
        self._note()
        self.draw()
        return True

    def finish_typed(self):
        """The check: a conic with three points picked is added with the Rho shown."""
        if len(self.points) == 3:
            self.make()

    def stop(self, close_page=True):
        self.preview.clear()
        for w in (self.widget, self.viewer):
            if w is not None and alive(w):
                w.removeEventFilter(self)
        if self.widget is not None and alive(self.widget):
            # give the view back its own cursor: a cursor left set on the viewport hides the next
            # FreeCAD tool's picture cursor, and that tool then gets no PropertyManager (Parabola)
            if self._had_cursor:
                self.widget.setCursor(self._old_cursor)
            else:
                self.widget.unsetCursor()
        self.page.tool = None
        global TOOL
        if TOOL is self:
            TOOL = None
        if close_page and alive(self.page):
            sketchtoolpm.close(self.page)

    # ------------------------------------------------------------------ events
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter391(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter conic.py: %s\n" % exc)
            return False

    def _fw_filter391(self, obj, event):
        t = event.type()
        if obj is self.viewer:
            if t in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
                key = event.key()
                if key == Qt.Key_Escape:
                    if t == QtCore.QEvent.KeyPress:
                        if self.points:
                            self.points, self.ties = [], []
                            self._note()
                            self.draw()
                        else:
                            QtCore.QTimer.singleShot(0, lambda: self.page.reject())
                    event.accept()
                    return True
                if key in (Qt.Key_Return, Qt.Key_Enter) and len(self.points) == 3:
                    if t == QtCore.QEvent.KeyPress:
                        self.make()
                    event.accept()
                    return True
            return False
        if obj is not self.widget:
            return False
        if t == QtCore.QEvent.MouseMove:
            if event.buttons():
                return False
            self.pointer = self.snap(QtCore.QPointF(event.position()))[0]
            self.draw()
            return True
        if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick):
            return event.button() == Qt.LeftButton
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self.click(QtCore.QPointF(event.position()))
            return True
        return False


TOOL = None


def start():
    global TOOL
    sketch = contextbar.sketch_in_edit()
    if sketch is None:
        return None
    if TOOL is not None:
        TOOL.stop()
    page = ConicPage(sketch)
    if not sketchtoolpm.open_page(page):
        return None
    TOOL = ConicTool(sketch, page)
    return TOOL


class _Command:
    def GetResources(self):
        return {"Pixmap": "Sketcher_CreateHyperbolic_Arc", "MenuText": "Conic",
                "ToolTip": "Sketches a conic: start, end, top vertex, then Rho (0.5 parabola, less an ellipse, "
                           "more a hyperbola)", "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        start()


def register():
    if "SWStyle_Conic" not in Gui.listCommands():
        Gui.addCommand("SWStyle_Conic", _Command())
