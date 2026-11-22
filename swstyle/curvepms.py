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

from . import refgeom2
from .refgeom2 import PM

EDGE_KINDS = ("line", "circle", "curve", "sketch")


def _proxy_name(obj):
    return type(getattr(obj, "Proxy", None)).__name__


class _AppEscape(QtCore.QObject):
    ""



    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.swallow = False

    def eventFilter(self, watched, event):
        try:
            if not isinstance(event, QtCore.QEvent):
                return False
            t = event.type()
            if t not in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease, QtCore.QEvent.ShortcutOverride):
                return False
            if event.key() != QtCore.Qt.Key_Escape or event.modifiers():
                return False
            if t == QtCore.QEvent.KeyRelease:
                if self.swallow:
                    self.swallow = False
                    return True         # FreeCAD's 3D view would reject on the release
                return False
            if QtWidgets.QApplication.activePopupWidget() is not None \
                    or QtWidgets.QApplication.activeModalWidget() is not None:
                return False
            focus = QtWidgets.QApplication.focusWidget()
            if isinstance(focus, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)):
                return False            # Esc in a field is the field's own
            if not (refgeom2._OPEN and refgeom2._OPEN[0] is self.panel):
                return False
            if t == QtCore.QEvent.KeyPress:
                self.swallow = True
                QtCore.QTimer.singleShot(0, self.panel.reject)
            return True
        except Exception:
            return False


def _hook_escape(panel, *widgets):
    """Esc = Cancel on these pages, as on every other page: an application filter for the page's life, and
    the 3D view, its viewport and the page's pick boxes. Cancel aborts the page's transaction, so the curve
    previewed from picks made first goes too."""
    views = []
    try:
        from . import pmtakeover
        vp = pmtakeover.view_widget()
        if vp is not None:
            views = [vp, vp.parentWidget()]         # the viewport and its view, which has the keyboard focus
    except Exception as _fw_err:
        _fw_log("curvepms.py:88", _fw_err)
    for w in views + list(widgets):
        try:
            if w is not None and w not in panel._views:
                w.installEventFilter(panel._esc)
                panel._views.append(w)
        except Exception as _fw_err:
            _fw_log("curvepms.py:95", _fw_err)
    app = QtWidgets.QApplication.instance()
    panel._app_esc = _AppEscape(panel)
    app.installEventFilter(panel._app_esc)
    close = panel._close

    def close_and_unhook():
        try:
            app.removeEventFilter(panel._app_esc)
        except Exception as _fw_err:
            _fw_log("curvepms.py:105", _fw_err)
        close()
    panel._close = close_and_unhook


def _whole(obj):
    """A pick of a curve feature itself (no sub-element) stands for all of its edges."""
    return (obj, "")


class CompositeCurvePM(PM):
    TITLE = "Composite Curve"
    ICON = "CURVES_COMPOSITE"

    def __init__(self, doc, picks=(), obj=None):
        super().__init__(doc)
        self.obj = obj
        if obj is not None:
            self.made = [obj]
        box, lay = self.group("Entities to Join", "SWCompositeEntitiesBox")
        self.entities = self.pick_box("SWCompositeEntities", EDGE_KINDS, many=True, height=96)
        lay.addWidget(self.entities)
        if obj is not None:
            for link, subs in obj.Entities:
                for s in (subs or ("",)):
                    self.entities.items.append((link, "" if s == "" else s))
            self.entities.show_items()
        _hook_escape(self, self.entities)
        self.start([p for p in picks if refgeom2.element_kind(*p) in EDGE_KINDS])

    def build(self):
        from . import curves
        items = self.entities.items
        if not items:
            raise RuntimeError("Select the edges, sketches or curves to join.")
        if self.obj is None:
            self.obj = curves._add_feature("CompositeCurve", curves.CompositeCurve, "Composite Curve")
            self.made = [self.obj]
        groups = {}
        order = []
        for o, s in items:
            if o.Name not in groups:
                groups[o.Name] = (o, [])
                order.append(o.Name)
            if s:
                groups[o.Name][1].append(s)
        self.obj.Entities = [(groups[n][0], tuple(groups[n][1]) or ("",)) for n in order]
        self.doc.recompute()
        shape = self.obj.Shape
        if shape.isNull() or not shape.Edges:
            raise RuntimeError("The picks have no edges to join.")
        if len(shape.Wires) != 1 or len(shape.Wires[0].Edges) != len(shape.Edges):

            raise RuntimeError("The entities must meet end to end, in one chain.")


class ReferencePointsCurvePM(PM):
    TITLE = "Curve Through Reference Points"
    ICON = "CURVES_THROUGH_REFERENCE_POINTS"

    def __init__(self, doc, picks=(), obj=None):
        super().__init__(doc)
        self.obj = obj
        if obj is not None:
            self.made = [obj]
        box, lay = self.group("Through Points", "SWRefPointsCurveBox")
        self.points = self.pick_box("SWRefPointsCurvePoints", ("point",), many=True, height=96)
        lay.addWidget(self.points)
        self.closed = QtWidgets.QCheckBox("Closed curve")
        self.closed.setObjectName("SWRefPointsCurveClosed")
        lay.addWidget(self.closed)
        if obj is not None:
            for link, subs in obj.References:
                for s in (subs or ("",)):
                    self.points.items.append((link, s))
            self.points.show_items()
            self.closed.setChecked(bool(obj.Closed))
        self.closed.toggled.connect(self.changed)
        _hook_escape(self, self.points)
        self.start([p for p in picks if refgeom2.element_kind(*p) == "point"])

    def build(self):
        from . import curves
        items = self.points.items
        if len(items) < 2:
            raise RuntimeError("Select two or more points or vertices, in order.")
        if self.closed.isChecked() and len(items) < 3:
            raise RuntimeError("A closed curve needs three or more points.")
        if self.obj is None:
            self.obj = curves._add_feature("CurveThroughPoints", curves.CurveThroughPoints, "Curve")
            self.made = [self.obj]
        self.obj.References = [(o, (s,) if s else ("",)) for o, s in items]
        self.obj.Closed = self.closed.isChecked()
        self.doc.recompute()
        if self.obj.Shape.isNull():
            raise RuntimeError("The curve could not be made through these points.")


class XYZCurvePM(PM):
    ""


    TITLE = "Curve Through XYZ Points"
    ICON = "FW_CurveThroughXYZPoints"     # the pack's picture (CURVES_THROUGH_XYZ_POINTS is not in it: Look audit row 22)

    def __init__(self, doc, picks=(), obj=None):
        super().__init__(doc)
        from . import curves
        self.obj = obj
        if obj is not None:
            self.made = [obj]
            curves.ensure_xyz_props(obj)
        box, lay = self.group("Coordinate System", "SWXYZCurveCoordSysBox")
        self.csys = self.pick_box("SWXYZCurveCoordSys", ("csys",))
        self.csys.setToolTip("The points' X, Y, Z are in this coordinate system (empty: the part's origin)")
        lay.addWidget(self.csys)
        pbox, play = self.group("Points", "SWXYZCurvePointsBox")
        self.table = QtWidgets.QTableWidget(4, 3)
        self.table.setObjectName("SWXYZCurveTable")
        self.table.setHorizontalHeaderLabels(["X", "Y", "Z"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.table.setMinimumHeight(150)
        play.addWidget(self.table)
        grid = QtWidgets.QGridLayout()
        self.path = ""
        for i, (key, text, call) in enumerate((("Browse", "Browse...", self.browse), ("Save", "Save", lambda: self.save(False)),
                                               ("SaveAs", "Save As...", lambda: self.save(True)),
                                               ("Insert", "Insert", self.insert), ("Delete", "Delete", self.delete_row))):
            b = QtWidgets.QPushButton(text)
            b.setObjectName("SWXYZCurve" + key)
            b.clicked.connect(call)
            grid.addWidget(b, i // 3, i % 3)
        play.addLayout(grid)
        self.closed = QtWidgets.QCheckBox("Closed curve")
        self.closed.setObjectName("SWXYZCurveClosed")
        play.addWidget(self.closed)
        if obj is not None:
            self.set_points(list(obj.Points))
            self.closed.setChecked(bool(obj.Closed))
            if getattr(obj, "CoordSystem", None) is not None:
                self.csys.items = [(obj.CoordSystem, "")]
                self.csys.show_items()
        self.table.itemChanged.connect(self.changed)
        self.closed.toggled.connect(self.changed)
        _hook_escape(self, self.csys, self.table)
        self.start([p for p in picks if refgeom2.element_kind(*p) == "csys"])

    # the table
    def set_points(self, pts):
        from . import curves
        self.table.blockSignals(True)
        self.table.setRowCount(max(4, len(pts) + 1))
        self.table.clearContents()
        for i, p in enumerate(pts):
            for j, v in enumerate((p.x, p.y, p.z)):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(curves.cell_text(v)))
        self.table.blockSignals(False)

    def points(self):
        from . import curves
        out = []
        for i in range(self.table.rowCount()):
            vals = []
            for j in range(3):
                it = self.table.item(i, j)
                if it is None or not it.text().strip():
                    continue
                v = curves._length(it.text())
                if v is None:
                    _fw_log("curvepms.py:271", it.text())
                else:
                    vals.append(v)
            if len(vals) == 3:
                out.append(App.Vector(*vals))
        return out

    def insert(self):
        self.table.insertRow(max(0, self.table.currentRow() + 1))

    def delete_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self.changed()

    def browse(self):
        from . import curves
        path, _ = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Curve file", "",
                                                        "Curves (*.sldcrv *.txt *.csv);;All files (*)")
        if path:
            self.path = path
            self.set_points(curves.read_points_file(path))
            self.changed()

    def save(self, ask=False):
        from . import curves
        path = self.path
        if ask or not path:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save curve file", path or "curve.sldcrv",
                                                            "Curves (*.sldcrv);;Text (*.txt);;All files (*)")
        if not path:
            return False
        curves.write_points_file(path, self.points())
        self.path = path
        return True

    def build(self):
        from . import curves
        pts = self.points()
        if len(pts) < 2:
            raise RuntimeError("Type two or more points (X, Y, Z), or Browse... for a curve file.")
        if self.closed.isChecked() and len(pts) < 3:
            raise RuntimeError("A closed curve needs three or more points.")
        if self.obj is None:
            self.obj = curves._add_feature("CurveThroughXYZ", curves.CurveThroughPoints, "Curve")
            curves.ensure_xyz_props(self.obj)
            self.made = [self.obj]
        cs = self.csys.first()
        self.obj.CoordSystem = cs[0] if cs else None
        self.obj.Points = pts
        self.obj.Closed = self.closed.isChecked()
        self.doc.recompute()
        if self.obj.Shape.isNull():
            raise RuntimeError("The curve could not be made through these points.")

    def done_text(self):
        cs = self.csys.first()
        return "%d points%s" % (len(self.points()), (" in " + cs[0].Label) if cs else "")


def curve_through_xyz_points():
    return _show(XYZCurvePM)


def _show(panel_cls, obj=None):
    doc = App.ActiveDocument if obj is None else obj.Document
    if doc is None or Gui.Control.activeDialog():
        return None
    picks = refgeom2._picks(doc) if obj is None else ()
    panel = panel_cls(doc, picks, obj)
    Gui.Control.showDialog(panel)
    return panel


def composite_curve():
    return _show(CompositeCurvePM)


def curve_through_reference_points():
    return _show(ReferencePointsCurvePM)


# --------------------------------------------------------------------------- Edit Feature
def edit_points_curve(obj):
    if Gui.Control.activeDialog():
        return None
    if obj.References:
        return _show(ReferencePointsCurvePM, obj)
    return _show(XYZCurvePM, obj)
    from . import curves
    dlg = curves.XYZDialog()
    dlg.set_points(list(obj.Points))
    dlg.closed.setChecked(bool(obj.Closed))
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return None
    pts = dlg.points()
    if len(pts) < 2:
        return None
    doc = obj.Document
    doc.openTransaction("Curve Through XYZ Points")
    try:
        obj.Points = pts
        obj.Closed = dlg.closed.isChecked()
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return obj


def edit_projected(obj):
    if Gui.Control.activeDialog():
        return None
    panel = refgeom2.ProjectedCurvePM(obj.Document, (), obj)
    Gui.Control.showDialog(panel)
    return panel


# --------------------------------------------------------------------------- sweep corners
PIPES = ("PartDesign::AdditivePipe", "PartDesign::SubtractivePipe")


class _PipeCorners:
    ""




    def slotCreatedObject(self, obj):
        try:
            if obj.TypeId in PIPES and not obj.Document.Restoring and "Transition" in obj.PropertiesList:
                obj.Transition = "Right corner"
        except Exception as _fw_err:
            _fw_log("curvepms.py:400", _fw_err)


_WATCH = [None]


def install():
    if _WATCH[0] is None:
        _WATCH[0] = _PipeCorners()
        App.addDocumentObserver(_WATCH[0])
    from . import curves
    curves.EDITORS["CompositeCurve"] = lambda o: _show(CompositeCurvePM, o)
    curves.EDITORS["CurveThroughPoints"] = edit_points_curve
    curves.EDITORS["ProjectedCurve"] = edit_projected
