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
from PySide import QtCore, QtWidgets
from .. import unitbox

from . import splineedit as E
from . import splineshow
from .toolbase import SketchTool, edited_sketch, active

PICK_PIXELS = 8.0


def _edited():
    gdoc = Gui.ActiveDocument
    vp = gdoc.getInEdit() if gdoc else None
    if getattr(vp, "Object", None) is None or not vp.Object.isDerivedFrom("Sketcher::SketchObject"):
        return None, None
    return gdoc, vp.Object


def picked_splines(sketch):
    """Spline geo ids whose curve or spline point is picked, in the order picked."""
    out = []
    try:
        sel = Gui.Selection.getSelectionEx(sketch.Document.Name)
    except Exception as _fw_err:
        _fw_log("fwsketch/splinecommands.py:55", _fw_err)
        return out
    for s in sel:
        if getattr(s.Object, "Name", None) != sketch.Name:
            continue
        for name in s.SubElementNames:
            geo = None
            if name.startswith("Edge"):
                geo = int(name[4:]) - 1
            elif name.startswith("Vertex"):
                try:
                    geo = sketch.getGeoVertexIndex(int(name[6:]) - 1)[0]
                except Exception:
                    geo = None
            if geo is not None and geo >= 0:
                spline = E.spline_of(sketch, geo)
                if spline is not None and spline not in out:
                    out.append(spline)
    return out


def _transaction(sketch, name, body):
    doc = sketch.Document
    doc.openTransaction(name)
    try:
        result = body()
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    finally:
        try:
            App.closeActiveTransaction(False)
        except Exception as _fw_err:
            _fw_log("fwsketch/splinecommands.py:87", _fw_err)
    doc.recompute()
    return result


def _redraw(gdoc, sketch, geo):
    try:
        from . import splinehandles
        if splinehandles.current() is not None:
            splinehandles.show(gdoc, sketch, geo)
            splinehandles.current().refresh()
    except Exception as _fw_err:
        _fw_log("fwsketch/splinecommands.py:99", _fw_err)
    splineshow.refresh()


# --- the actions, each on one spline ----------------------------------------------------------------
def through_point(sketch, geo):
    """Relax, Simplify, Insert and Proportional are for splines through points, not style splines."""
    return E.is_spline(sketch, geo) and not E.is_style(sketch, geo)


def relax(gdoc, sketch, geo):
    if not through_point(sketch, geo):
        return False
    _transaction(sketch, "Relax spline", lambda: E.relax(sketch, geo))
    _redraw(gdoc, sketch, geo)
    return True


def proportional(gdoc, sketch, geo):
    if not through_point(sketch, geo):
        return False
    on = not E.is_proportional(sketch, geo)
    _transaction(sketch, "Proportional spline", lambda: E.set_proportional(sketch, geo, on))
    _redraw(gdoc, sketch, geo)
    return True


def insert(gdoc, sketch, geo, point):
    if not through_point(sketch, geo):
        return None
    at = _transaction(sketch, "Insert spline point", lambda: E.insert_point(sketch, geo, point))
    _redraw(gdoc, sketch, geo)
    return at


def show(kind):
    def act(gdoc, sketch, geo):
        on = splineshow.toggle(sketch, kind, [geo])
        return on
    return act


def simplify(gdoc, sketch, geo):
    if not through_point(sketch, geo):
        return False
    box = SimplifyBox(gdoc, sketch, geo)
    box.show()
    return box


# --- Simplify Spline's box -------------------------------------------------------------------------
_box = None


def simplify_box():
    return _box


class SimplifyBox(QtWidgets.QDialog):
    ""


    def __init__(self, gdoc, sketch, geo):
        global _box
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle("Simplify Spline")
        self.setObjectName("FreeWorksSimplifySpline")
        self.gdoc, self.sketch, self.geo = gdoc, sketch, geo
        data = E.info(sketch, geo)
        self.original = len(data["points"])
        self.reference = sketch.Geometry[geo].copy()
        box = self.reference.toShape().BoundBox
        self.size = max(box.DiagonalLength, 1e-6)
        self.steps = []          # (tolerance or None, count or None) applied, for Previous
        self.done = False
        lay = QtWidgets.QFormLayout(self)
        self.original_label = QtWidgets.QLabel(str(self.original))
        self.simplified_label = QtWidgets.QLabel(str(self.original))
        self.original_label.setObjectName("OriginalPoints")
        self.simplified_label.setObjectName("SimplifiedPoints")
        lay.addRow("Number of points in original curve:", self.original_label)
        lay.addRow("Number of points in simplified curve:", self.simplified_label)
        self.tolerance = unitbox.UnitSpinBox()
        self.tolerance.setObjectName("Tolerance")
        self.tolerance.setDecimals(3)
        self.tolerance.setRange(0.0, self.size)
        self.tolerance.setSingleStep(max(round(self.size / 200.0, 3), 0.001))
        self.tolerance.setSuffix(" mm")
        self.tolerance.setKeyboardTracking(False)     # a typed value counts once it is entered
        lay.addRow("Tolerance:", self.tolerance)
        row = QtWidgets.QHBoxLayout()
        self.previous_button = QtWidgets.QPushButton("Previous")
        self.smooth_button = QtWidgets.QPushButton("Smooth")
        self.ok_button = QtWidgets.QPushButton("OK")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        for b in (self.previous_button, self.smooth_button, self.ok_button, self.cancel_button):
            b.setObjectName(b.text())
            b.setAutoDefault(False)
            row.addWidget(b)
        self.ok_button.setDefault(True)
        lay.addRow(row)
        self.previous_button.clicked.connect(lambda: self._safe(self.previous))
        self.smooth_button.clicked.connect(lambda: self._safe(self.smooth))
        self.ok_button.clicked.connect(lambda: self._safe(self.ok))
        self.cancel_button.clicked.connect(lambda: self._safe(self.cancel))
        self.rejected.connect(lambda: self._safe(self._close, False))     # Esc or the window's X
        self.tolerance.blockSignals(True)
        self.tolerance.setValue(round(self.size * 0.01, 3))
        self.tolerance.blockSignals(False)
        self.tolerance.valueChanged.connect(lambda v: self._safe(self._tolerance_changed, v))
        self.begun = False
        _box = self
        # the undo step opens once the button's command has returned: FreeCAD closes a transaction
        # opened inside a command when the command ends (found with real clicks)
        QtCore.QTimer.singleShot(0, lambda: self._safe(self._begin))

    def _begin(self):
        if self.done or self.begun:
            return
        self.begun = True
        self.sketch.Document.openTransaction("Simplify spline")
        try:
            self._apply(self.tolerance.value(), None)
            self.steps = [(self.tolerance.value(), None)]
        except BaseException:
            try:
                self.sketch.Document.abortTransaction()
            except Exception:
                pass
            raise

    @staticmethod
    def _safe(fn, *args):
        # an exception out of a Qt slot or override can take FreeCAD down: keep them in here
        try:
            return fn(*args)
        except Exception:
            import traceback
            App.Console.PrintError("FreeCAD Simplify Spline: %s" % traceback.format_exc())

    def points_now(self):
        return len(E.info(self.sketch, self.geo)["points"])

    def _restore(self):
        """Back to the spline as it was when the box opened (inside the open undo step)."""
        if self.points_now() == self.original and E.deviation(self.sketch.Geometry[self.geo], self.reference, 80) < 1e-9:
            return
        doc = self.sketch.Document
        doc.abortTransaction()
        doc.openTransaction("Simplify spline")

    def _apply(self, tolerance, count):
        self._restore()
        if tolerance is None and count is None:
            n = self.original
        else:
            n, _ = E.simplify(self.sketch, self.geo, tolerance=tolerance, count=count)
        self.sketch.Document.recompute()
        self.simplified_label.setText(str(n))
        _redraw(self.gdoc, self.sketch, self.geo)

    def _tolerance_changed(self, value):
        self._apply(value, None)
        self.steps.append((value, None))

    def smooth(self):
        n = max(self.points_now() // 2, 3 if self.reference.isPeriodic() else 2)
        self._apply(None, n)
        self.steps.append((None, n))

    def previous(self):
        if len(self.steps) > 1:
            self.steps.pop()
        tol, count = self.steps[-1] if self.steps else (None, None)
        if tol is not None:
            self.tolerance.blockSignals(True)
            self.tolerance.setValue(tol)
            self.tolerance.blockSignals(False)
        self._apply(tol, count)

    def _close(self, keep):
        global _box
        if self.done:
            return
        if not self.begun:
            self.begun = True
            keep = False       # closed before anything was done
            self.sketch.Document.openTransaction("Simplify spline")
        self.done = True
        doc = self.sketch.Document
        if keep:
            doc.commitTransaction()
        else:
            doc.abortTransaction()
        try:
            App.closeActiveTransaction(False)
        except Exception as _fw_err:
            _fw_log("fwsketch/splinecommands.py:289", _fw_err)
        doc.recompute()
        _redraw(self.gdoc, self.sketch, self.geo)
        if _box is self:
            _box = None

    def ok(self):
        self._close(True)
        self.hide()
        self.deleteLater()

    def cancel(self):
        self._close(False)
        self.hide()
        self.deleteLater()


# --- tool first: wait for a click on a spline ---------------------------------------------------------
class SplinePickTool(SketchTool):
    """Waits for a click on a spline, then runs action(gdoc, sketch, geo[, point])."""

    def __init__(self, gdoc, sketch, title, action, stay=False, with_point=False, style_too=False):
        super().__init__(gdoc, sketch)
        self._title, self.action, self.stay = title, action, stay
        self.with_point, self.style_too = with_point, style_too
        self.hover = None
        self.results = []
        self.only = None       # Insert Spline Point started on picked splines: only those

    def title(self):
        return self._title

    def icon_name(self):
        return "Sketcher_Pointer_Create_BSpline"

    def starts_click_drag(self):
        return False

    def is_first_state(self):
        return True        # a right click lets the tool go

    def nearest(self, p, px):
        """(geo, point on it) of the spline within PICK_PIXELS of p, else (None, None)."""
        best = (PICK_PIXELS * px, None, None)
        for geo in range(self.sketch.GeometryCount):
            if not E.is_spline(self.sketch, geo):
                continue
            if not self.style_too and E.is_style(self.sketch, geo):
                continue
            if self.only and geo not in self.only:
                continue
            curve = self.sketch.Geometry[geo]
            try:
                u = curve.parameter(App.Vector(p[0], p[1], 0))
                q = curve.value(u)
            except Exception:
                continue
            dist = q.distanceToPoint(App.Vector(p[0], p[1], 0))
            if dist <= best[0]:
                best = (dist, geo, (q.x, q.y))
        return best[1], best[2]

    def on_move(self, p, px):
        self.pixel = px
        self.snap(p, px, False, False, False, False)
        geo, q = self.nearest(p, px)
        self.hover = (geo, q) if geo is not None else None
        if geo is not None:
            self.preview([E.sample(self.sketch.Geometry[geo], 96)], points=[q] if self.with_point else [])
        else:
            self.preview([])
        self.readout(p, "")
        return []

    def on_click(self, d):
        p = d.position
        geo, q = self.nearest(p, getattr(self, "pixel", 0.0) or 0.0)
        if geo is None:
            return
        gdoc, sketch = self.gdoc, self.sketch
        if self.with_point:
            r = self.action(gdoc, sketch, geo, q)
        else:
            r = self.action(gdoc, sketch, geo)
        self.results.append(r)
        self.snapper.sketch_changed()
        if not self.stay:
            self.end()


# --- the commands ---------------------------------------------------------------------------------------
# name -> (menu text, tooltip, icon, action, kind) ; kind: "one" (each picked spline), "point" (a tool
# that clicks on the spline), "show" (the picked splines together), "box" (the first picked spline)
COMMANDS = {
    "FreeWorks_InsertSplinePoint": ("Insert Spline Point", "Adds a spline point where you click on a spline; "
                                    "the shape stays. Esc ends.", "Sketcher_BSplineInsertKnot", insert, "point"),
    "FreeWorks_SimplifySpline": ("Simplify Spline", "Takes spline points away while the spline stays within a "
                                 "tolerance of its shape", "Sketcher_BSplineDecreaseDegree", simplify, "box"),
    "FreeWorks_RelaxSpline": ("Relax Spline", "Lets the spline's handles go: the smoothest spline through the "
                              "same points", "Sketcher_CreateBSpline", relax, "one"),
    "FreeWorks_SplineProportional": ("Proportional", "Dragging an end of the spline scales and turns all of it "
                                     "(click again to switch it off)", "Sketcher_CreateBSpline", proportional, "one"),
    "FreeWorks_ShowCurvatureCombs": ("Show Curvature Combs", "Shows the picked spline's curvature comb",
                                     "Sketcher_BSplineComb", show(splineshow.COMB), "show"),
    "FreeWorks_ShowInflectionPoints": ("Show Inflection Points", "Shows where the picked spline changes the way "
                                       "it bends", "Sketcher_BSplineComb", show(splineshow.INFLECTION), "show"),
    "FreeWorks_ShowMinimumRadius": ("Show Minimum Radius", "Shows where the picked spline bends tightest, and that "
                                    "radius", "Sketcher_BSplineComb", show(splineshow.MINRADIUS), "show"),
}
STYLE_TOO = ("show",)


def run(name, geos=None):
    """What the button does (also the shortcut menu entries, with the right-clicked spline as geos);
    returns the pick tool when it waits."""
    text, _, _, action, kind = COMMANDS[name]
    gdoc, sketch = _edited()
    if sketch is None:
        return None
    running = active()
    if running is not None and running.title() == text:
        running.end()
        return None
    picked = [g for g in (geos if geos is not None else picked_splines(sketch))
              if kind in STYLE_TOO or through_point(sketch, g)]
    if picked and kind != "point":
        if kind == "box":
            return action(gdoc, sketch, picked[0])
        if kind == "show":
            on = splineshow.toggle(sketch, _show_kind(name), picked)
            return on
        for g in picked:
            action(gdoc, sketch, g)
        return True
    if running is not None:
        running.end()
    tool = SplinePickTool(gdoc, sketch, text, action, stay=(kind == "point"), with_point=(kind == "point"),
                          style_too=(kind in STYLE_TOO))
    if picked and kind == "point":
        tool.only = picked
    try:
        Gui.Selection.clearSelection()
    except Exception as _fw_err:
        _fw_log("fwsketch/splinecommands.py:432", _fw_err)
    tool.begin()
    return tool


def _show_kind(name):
    return {"FreeWorks_ShowCurvatureCombs": splineshow.COMB, "FreeWorks_ShowInflectionPoints": splineshow.INFLECTION,
            "FreeWorks_ShowMinimumRadius": splineshow.MINRADIUS}[name]


def checked(name, sketch, geo):
    """Whether the entry shows a check mark for spline geo (the switches)."""
    if name == "FreeWorks_SplineProportional":
        return E.is_proportional(sketch, geo)
    if name in ("FreeWorks_ShowCurvatureCombs", "FreeWorks_ShowInflectionPoints", "FreeWorks_ShowMinimumRadius"):
        return _show_kind(name) in splineshow.shown(sketch, geo)
    return None


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.tip, self.icon = COMMANDS[name][:3]

    def GetResources(self):
        # ForEdit NoTransaction as commands._Command (the actions keep their own undo steps)
        return {"Pixmap": self.icon, "MenuText": self.text, "ToolTip": self.tip, "CmdType": "ForEdit NoTransaction"}

    def IsActive(self):
        gdoc, sketch = _edited()
        if sketch is None:
            return False
        style_too = COMMANDS[self.name][4] in STYLE_TOO
        return any(E.is_spline(sketch, g) and (style_too or not E.is_style(sketch, g))
                   for g in range(sketch.GeometryCount))

    def Activated(self):
        _safe_run(self.name)



MENU_ORDER = ("FreeWorks_InsertSplinePoint", "FreeWorks_SimplifySpline", "FreeWorks_RelaxSpline",
              "FreeWorks_SplineProportional", "FreeWorks_ShowCurvatureCombs", "FreeWorks_ShowInflectionPoints",
              "FreeWorks_ShowMinimumRadius")


class MenuSpy(QtCore.QObject):
    """Application filter: a shortcut menu opening over the sketch while a spline is picked gets the
    spline entries (a separator, then one action per entry) at its end."""

    def __init__(self):
        super().__init__()
        self.last = None      # [entry texts] of the last menu, for checks
        from . import appevents
        appevents.listen(self, (QtCore.QEvent.Show,))   # one application filter (fix65)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide on Windows can hand a filter a stale wrapper (a QWidgetItem) instead
        try:
            if event.type() == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QMenu):
                self.menu_shown(obj)
        except Exception as _fw_err:
            _fw_log("fwsketch/splinecommands.py:495", _fw_err)
        return False

    def menu_shown(self, menu):
        if menu.property("fwSplineEntries") or isinstance(menu.parent(), QtWidgets.QMenu):
            return
        gdoc, sketch = _edited()
        if sketch is None or active() is not None:
            return
        view = None
        try:
            view = gdoc.ActiveView.graphicsView().viewport()
        except Exception as _fw_err:
            _fw_log("fwsketch/splinecommands.py:508", _fw_err)
        if view is None or not view.rect().contains(view.mapFromGlobal(menu.pos())) and \
                not view.rect().contains(view.mapFromGlobal(menu.pos() - QtCore.QPoint(2, 2))):
            return
        splines = picked_splines(sketch)
        if not splines:
            return
        geo = splines[0]
        style = E.is_style(sketch, geo)
        menu.setProperty("fwSplineEntries", True)
        menu.addSeparator()
        texts = []
        for name in MENU_ORDER:
            text, tip, icon, _, kind = COMMANDS[name]
            if style and kind not in STYLE_TOO:
                continue
            act = menu.addAction(text)
            act.setObjectName(name)
            act.setToolTip(tip)
            mark = checked(name, sketch, geo)
            if mark is not None:
                act.setCheckable(True)
                act.setChecked(mark)
            act.triggered.connect(lambda _=False, n=name, g=geo: QtCore.QTimer.singleShot(0, lambda: _safe_run(n, [g])))
            texts.append(text)
        self.last = texts
        menu.resize(menu.sizeHint())
        # longer now: keep it on the screen (Qt placed it for its old height)
        screen = menu.screen().availableGeometry() if menu.screen() is not None else None
        if screen is not None and menu.geometry().bottom() > screen.bottom():
            menu.move(menu.x(), max(screen.top(), screen.bottom() - menu.height()))


def _safe_run(name, geos=None):
    try:
        run(name, geos)
    except Exception:
        import traceback
        App.Console.PrintError("FreeCAD spline tools: %s" % traceback.format_exc())


_spy = None


def register():
    global _spy
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    splineshow.start()
    if _spy is None:
        _spy = MenuSpy()


def spy():
    return _spy
