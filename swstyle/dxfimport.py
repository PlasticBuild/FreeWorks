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
import os

import FreeCAD as App
import Part

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

V = App.Vector


UNITS = (("Millimeters", 1.0, 4), ("Centimeters", 10.0, 5), ("Meters", 1000.0, 6), ("Inches", 25.4, 1),
         ("Feet", 304.8, 2))
FILE_MM = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}       # what FreeCAD's reader scaled the file by
METHODS = ("drawing", "sketch", "curves")
LAST_METHOD = "DxfImportMethod"


def _params():
    from . import paths
    return paths.params()


# --------------------------------------------------------------------------- reading
def file_insunits(path):
    """The file's $INSUNITS (0 when it says none)."""
    try:
        from . import drawdxf
        head = drawdxf.sections(drawdxf.read(path)).get("HEADER", [])
        val = drawdxf.header_vars(head).get("$INSUNITS", [])
        return int(float(val[0][1])) if val else 0
    except Exception as _fw_err:
        _fw_log("dxfimport.py:insunits", _fw_err)
        return 0


def as_dxf(path):
    """path itself for a DXF; for a DWG the DXF FreeCAD's DWG converter writes (RuntimeError without one)."""
    if os.path.splitext(path)[1].lower() != ".dwg":
        return path
    import importDWG
    out = importDWG.convertToDxf(path)
    if not out or not os.path.isfile(out):
        raise RuntimeError("FreeCAD has no DWG converter (ODA File Converter, LibreDWG or QCAD), so a DWG file "
                           "cannot be read. Save it as DXF in the program that made it.")
    return out


class Reading(object):
    """The file read once: its edges by layer (in mm, as the file's $INSUNITS says) and that unit."""

    def __init__(self, path):
        self.path = path
        self.dxf = as_dxf(path)
        self.insunits = file_insunits(self.dxf)
        self.layers = {}            # layer name -> [edges]
        self.order = []
        self._read()

    def _read(self):
        grp = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
        keys = (("dxfShowDialog", False), ("dxfImportAsShapes", True), ("dxfImportAsDraft", False),
                ("dxfUseDraftVisGroups", True))
        keep = [(k, grp.GetBool(k, d)) for k, d in (("dxfShowDialog", True), ("dxfImportAsShapes", False),
                                                    ("dxfImportAsDraft", False), ("dxfUseDraftVisGroups", True))]
        mode = grp.GetInt("DxfImportMode", 2)
        active = App.ActiveDocument
        doc = App.newDocument("FwDxfRead", hidden=True)
        try:
            for k, v in keys:
                grp.SetBool(k, v)
            grp.SetInt("DxfImportMode", 2)
            import importDXF
            importDXF.insert(self.dxf, doc.Name)
            placed = set()
            for o in doc.Objects:
                if o.TypeId == "App::FeaturePython" and "Group" in o.PropertiesList and \
                        getattr(getattr(o, "Proxy", None), "Type", "") == "Layer":
                    edges = []
                    for m in o.Group:
                        edges += self._edges(m)
                        placed.add(m.Name)
                    self._add(o.Label, edges)
            loose = []
            for o in doc.Objects:
                if o.Name not in placed and o.isDerivedFrom("Part::Feature"):
                    loose += self._edges(o)
            if loose:
                self._add("0", loose)
        finally:
            for k, v in keep:
                grp.SetBool(k, v)
            grp.SetInt("DxfImportMode", mode)
            try:
                try:
                    if App.getActiveTransaction():
                        App.closeActiveTransaction(True)
                except Exception as _fw_err:
                    _fw_log("dxfimport.py:transaction", _fw_err)
                App.closeDocument(doc.Name)
            except Exception as _fw_err:
                _fw_log("dxfimport.py:close", _fw_err)
            if active is not None and active.Name in App.listDocuments():
                App.setActiveDocument(active.Name)

    @staticmethod
    def _edges(o):
        s = getattr(o, "Shape", None)
        if s is None or s.isNull():
            return []
        return [e.copy() for e in s.Edges]

    def _add(self, name, edges):
        if name not in self.layers:
            self.layers[name] = []
            self.order.append(name)
        self.layers[name] += edges

    def file_unit(self):
        """The index in UNITS of the file's own unit (Millimeters when it says none)."""
        for i, u in enumerate(UNITS):
            if u[2] == self.insunits:
                return i
        return 0

    def edges(self, layers, unit, move=(0.0, 0.0), angle=0.0, origin=None):
        """The edges of layers, read in UNITS[unit], origin (a point of the file, mm as read) put on the
        origin, then moved by move (mm) and turned angle degrees about the origin."""
        k = UNITS[unit][1] / FILE_MM.get(self.insunits, 1.0)
        m = App.Matrix()
        if origin is not None:
            m.move(V(-origin[0], -origin[1], 0))
        m.scale(k, k, k)
        m2 = App.Matrix()
        m2.move(V(move[0], move[1], 0))
        m = m2.multiply(m)
        if angle:
            r = App.Matrix()
            r.rotateZ(math.radians(angle))
            m = r.multiply(m)
        out = []
        for name in self.order:
            if name in layers:
                for e in self.layers[name]:
                    try:
                        out.append(_moved(e, m))
                    except Exception as _fw_err:
                        _fw_log("dxfimport.py:edges", _fw_err)
        return out


def _moved(e, m):
    """e under m (a move, a turn and one scale): circles stay circles."""
    c = e.copy()
    c.transformShape(m, False, True)
    return c


def picks(edges):
    """The points a click can put on the origin: end points and centres."""
    out = []
    for e in edges:
        for v in e.Vertexes:
            out.append((v.Point.x, v.Point.y))
        c = getattr(e.Curve, "Center", None)
        if c is not None:
            out.append((c.x, c.y))
    return out


def nearest(points, x, y):
    best, d = None, None
    for p in points:
        dd = (p[0] - x) ** 2 + (p[1] - y) ** 2
        if d is None or dd < d:
            best, d = p, dd
    return best


# --------------------------------------------------------------------------- making
def _sketch_geometry(edges, merge):
    """Sketch geometry of edges; line end points within merge of another end point (or an arc's) moved onto it."""
    anchors = []
    for e in edges:
        if e.Curve.TypeId != "Part::GeomLine":
            anchors += [v.Point for v in e.Vertexes]
    ends = []

    def snap(p):
        if merge > 0:
            for a in anchors + ends:
                if (a - p).Length <= merge:
                    return V(a)
        ends.append(V(p))
        return V(p)

    geos = []
    for e in edges:
        try:
            t = e.Curve.TypeId
            if t == "Part::GeomLine":
                a, b = snap(e.Vertexes[0].Point), snap(e.Vertexes[-1].Point)
                if (a - b).Length > 1e-7:
                    geos.append(Part.LineSegment(V(a.x, a.y, 0), V(b.x, b.y, 0)))
            elif t == "Part::GeomCircle":
                c = e.Curve
                circ = Part.Circle(V(c.Center.x, c.Center.y, 0), V(0, 0, 1), c.Radius)
                if e.isClosed():
                    geos.append(circ)
                else:
                    a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
                    pa = circ.parameter(V(a.x, a.y, 0))
                    pb = circ.parameter(V(b.x, b.y, 0))
                    if c.Axis.z < 0:
                        pa, pb = pb, pa
                    geos.append(Part.ArcOfCircle(circ, pa, pb))
            else:
                pts = [V(p.x, p.y, 0) for p in e.discretize(24)]
                bs = Part.BSplineCurve()
                bs.interpolate(pts)
                geos.append(bs)
        except Exception as _fw_err:
            _fw_log("dxfimport.py:geometry", _fw_err)
    return geos


def _no_sketch_on_new():
    """Options > Sketch > Create sketch on new part, off while the part is made (restore with the result)."""
    try:
        from . import optionsextras
        key = getattr(optionsextras, "SKETCH_ON_NEW", None)
        if key:
            p = optionsextras._p()
            was = p.GetBool(key, False)
            p.SetBool(key, False)
            return lambda: p.SetBool(key, was)
    except Exception as _fw_err:
        _fw_log("dxfimport.py:sketch_on_new", _fw_err)
    return lambda: None


def _new_part(stem):
    from . import newdoc
    restore = _no_sketch_on_new()
    try:
        doc = newdoc.make("Part")
    finally:
        restore()
    doc.Label = stem
    body = next((o for o in doc.Objects if o.TypeId == "PartDesign::Body"), None)
    return doc, body


def make_sketch(stem, edges, merge=0.0, constraints=True):
    doc, body = _new_part(stem)
    sk = body.newObject("Sketcher::SketchObject", "Sketch") if body is not None else \
        doc.addObject("Sketcher::SketchObject", "Sketch")
    sk.Label = "Sketch1"
    if body is not None:
        plane = next((f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"), None)
        if plane is not None:
            sk.AttachmentSupport = [(plane, "")]
            sk.MapMode = "FlatFace"
    geos = _sketch_geometry(edges, merge)
    if geos:
        sk.addGeometry(geos, False)
    if constraints and geos:
        try:
            if sk.detectMissingPointOnPointConstraints(max(merge, 1e-4)):
                sk.makeMissingPointOnPointCoincident(False)
            if sk.detectMissingVerticalHorizontalConstraints(math.radians(0.01)):
                sk.makeMissingVerticalHorizontal(False)
        except Exception as _fw_err:
            _fw_log("dxfimport.py:constraints", _fw_err)
    doc.recompute()
    return doc


def make_curves(stem, edges):
    doc, body = _new_part(stem)
    feat = doc.addObject("Part::Feature", "Curves")
    feat.Label = stem
    feat.Shape = Part.Compound(edges)
    doc.recompute()
    return doc


def make_drawing(stem, edges):
    from . import newdoc
    doc = App.newDocument(newdoc._next_name("Draw"))
    doc.Label = stem
    if Gui is not None:
        Gui.activateWorkbench("TechDrawWorkbench")
    page = newdoc.new_sheet(doc)
    src = doc.addObject("Part::Feature", "DxfGeometry")
    src.Label = stem + " geometry"
    src.Shape = Part.Compound(edges)
    view = doc.addObject("TechDraw::DrawViewPart", "View")
    view.Label = stem
    page.addView(view)
    view.Source = [src]
    view.Direction = V(0, 0, 1)
    view.XDirection = V(1, 0, 0)
    view.Scale = 1.0
    try:
        view.ScaleType = "Custom"
    except Exception as _fw_err:
        _fw_log("dxfimport.py:scaletype", _fw_err)
    bb = src.Shape.BoundBox
    view.X, view.Y = bb.Center.x, bb.Center.y
    if Gui is not None and src.ViewObject is not None:
        src.ViewObject.Visibility = False
    doc.recompute()
    return doc


def finish(reading, method, layers, unit, move=(0.0, 0.0), angle=0.0, origin=None, merge=0.0, constraints=True):
    edges = reading.edges(layers, unit, move, angle, origin)
    if not edges:
        raise RuntimeError("Nothing 2D was found on the layers picked.")
    stem = os.path.splitext(os.path.basename(reading.path))[0]
    if method == "drawing":
        return make_drawing(stem, edges)
    if method == "curves":
        return make_curves(stem, edges)
    return make_sketch(stem, edges, merge, constraints)


# --------------------------------------------------------------------------- the wizard
if Gui is not None:
    class Preview(QtWidgets.QGraphicsView):
        """The geometry as it will come in; with Select a point on, a click picks the nearest point."""
        picked = QtCore.Signal(float, float)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setScene(QtWidgets.QGraphicsScene(self))
            self.setRenderHint(QtGui.QPainter.Antialiasing)
            self.setMinimumSize(320, 260)
            self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor(255, 255, 255)))
            self.picking = False
            self.points = []

        def show_edges(self, edges, origin_mark=True):
            sc = self.scene()
            sc.clear()
            pen = QtGui.QPen(QtGui.QColor(0, 0, 0))
            pen.setCosmetic(True)
            self.points = picks(edges)
            for e in edges:
                try:
                    pts = e.discretize(Deflection=0.05) if e.Curve.TypeId != "Part::GeomLine" else \
                        [e.Vertexes[0].Point, e.Vertexes[-1].Point]
                except Exception:
                    pts = [v.Point for v in e.Vertexes]
                path = QtGui.QPainterPath()
                for i, p in enumerate(pts):
                    (path.moveTo if i == 0 else path.lineTo)(p.x, -p.y)
                sc.addPath(path, pen)
            if origin_mark:
                red = QtGui.QPen(QtGui.QColor(200, 0, 0))
                red.setCosmetic(True)
                r = sc.itemsBoundingRect()
                s = max(r.width(), r.height(), 1.0) * 0.04
                sc.addLine(-s, 0, s, 0, red)
                sc.addLine(0, -s, 0, s, red)
            r = sc.itemsBoundingRect()
            m = max(r.width(), r.height()) * 0.05 + 0.5
            self.fitInView(r.adjusted(-m, -m, m, m), QtCore.Qt.KeepAspectRatio)

        def resizeEvent(self, event):
            super().resizeEvent(event)
            r = self.scene().itemsBoundingRect()
            if not r.isNull():
                self.fitInView(r, QtCore.Qt.KeepAspectRatio)

        def mousePressEvent(self, event):
            if self.picking and self.points:
                p = self.mapToScene(event.pos())
                self.picked.emit(p.x(), -p.y())
                return
            super().mousePressEvent(event)

    class ImportWizard(QtWidgets.QDialog):
        def __init__(self, reading, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.reading = reading
            self.origin = None          # the file point put on the origin (mm as read, before units)
            self.setWindowTitle("DXF/DWG Import")
            self.setObjectName("FW_DxfImport")
            lay = QtWidgets.QVBoxLayout(self)
            self.stack = QtWidgets.QStackedWidget(self)
            lay.addWidget(self.stack)
            self.stack.addWidget(self._method_page())
            self.stack.addWidget(self._settings_page())
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            self.back = QtWidgets.QPushButton("< Back")
            self.next = QtWidgets.QPushButton("Next >")
            self.finish_button = QtWidgets.QPushButton("Finish")
            cancel = QtWidgets.QPushButton("Cancel")
            for b in (self.back, self.next, self.finish_button, cancel):
                row.addWidget(b)
            lay.addLayout(row)
            self.back.clicked.connect(lambda: self._go(0))
            self.next.clicked.connect(lambda: self._go(1))
            self.finish_button.clicked.connect(self.accept)
            cancel.clicked.connect(self.reject)
            self.result_doc = None
            self.resize(760, 520)
            self._go(0)

        # page 1
        def _method_page(self):
            w = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(w)
            v.addWidget(QtWidgets.QLabel("<b>Import Method</b>"))
            v.addWidget(QtWidgets.QLabel(os.path.basename(self.reading.path)))
            self.r_drawing = QtWidgets.QRadioButton("Create new drawing")
            self.r_part = QtWidgets.QRadioButton("Import to a new part as:")
            self.r_sketch = QtWidgets.QRadioButton("2D sketch")
            self.r_curves = QtWidgets.QRadioButton("3D curves")
            sub = QtWidgets.QButtonGroup(w)
            top = QtWidgets.QButtonGroup(w)
            top.addButton(self.r_drawing)
            top.addButton(self.r_part)
            sub.addButton(self.r_sketch)
            sub.addButton(self.r_curves)
            v.addWidget(self.r_drawing)
            v.addWidget(self.r_part)
            for b in (self.r_sketch, self.r_curves):
                h = QtWidgets.QHBoxLayout()
                h.addSpacing(24)
                h.addWidget(b)
                h.addStretch(1)
                v.addLayout(h)
            v.addStretch(1)
            last = _params().GetString(LAST_METHOD, "drawing")
            (self.r_sketch if last == "sketch" else self.r_curves if last == "curves" else self.r_sketch).setChecked(True)
            (self.r_drawing if last == "drawing" else self.r_part).setChecked(True)
            self.r_drawing.toggled.connect(self._method_changed)
            self.r_sketch.toggled.connect(self._method_changed)
            return w

        def method(self):
            if self.r_drawing.isChecked():
                return "drawing"
            return "sketch" if self.r_sketch.isChecked() else "curves"

        def _method_changed(self, *_a):
            for b in (self.r_sketch, self.r_curves):
                b.setVisible(self.r_part.isChecked())       # no greyed rows: shown only where they act
            sketch = self.method() == "sketch"
            self.sketch_box.setVisible(sketch)
            self.layers_title.setText("Layers selected for sheet" if self.method() == "drawing" else
                                      "Layers selected for import")

        # page 2
        def _settings_page(self):
            w = QtWidgets.QWidget()
            h = QtWidgets.QHBoxLayout(w)
            left = QtWidgets.QVBoxLayout()
            h.addLayout(left, 0)
            left.addWidget(QtWidgets.QLabel("<b>Document Settings</b>"))
            self.layers_title = QtWidgets.QLabel("Layers selected for sheet")
            left.addWidget(self.layers_title)
            self.layer_list = QtWidgets.QListWidget()
            self.layer_list.setObjectName("FW_DxfLayers")
            for name in self.reading.order:
                it = QtWidgets.QListWidgetItem("%s (%d)" % (name, len(self.reading.layers[name])))
                it.setData(QtCore.Qt.UserRole, name)
                it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Checked)
                self.layer_list.addItem(it)
            self.layer_list.setMaximumHeight(140)
            self.layer_list.itemChanged.connect(self._refresh)
            left.addWidget(self.layer_list)
            form = QtWidgets.QFormLayout()
            self.units = QtWidgets.QComboBox()
            self.units.setObjectName("FW_DxfUnits")
            self.units.addItems([u[0] for u in UNITS])
            self.units.setCurrentIndex(self.reading.file_unit())
            self.units.currentIndexChanged.connect(self._refresh)
            form.addRow("Units:", self.units)
            left.addLayout(form)
            pos = QtWidgets.QGroupBox("Geometry Positioning")
            pf = QtWidgets.QFormLayout(pos)
            self.move_x = self._spin(-1e6, 1e6, "FW_DxfMoveX")
            self.move_y = self._spin(-1e6, 1e6, "FW_DxfMoveY")
            self.rotate = self._spin(-360, 360, "FW_DxfRotate", " deg")
            pf.addRow("Move entities X:", self.move_x)
            pf.addRow("Y:", self.move_y)
            pf.addRow("Rotate entities:", self.rotate)
            self.pick = QtWidgets.QPushButton("Select a point to Position on origin")
            self.pick.setObjectName("FW_DxfPick")
            self.pick.setCheckable(True)
            self.pick.toggled.connect(self._pick_mode)
            pf.addRow(self.pick)
            self.reset_pos = QtWidgets.QPushButton("Reset")
            self.reset_pos.clicked.connect(self._reset_position)
            pf.addRow(self.reset_pos)
            left.addWidget(pos)
            self.sketch_box = QtWidgets.QGroupBox("2D Sketch")
            sf = QtWidgets.QFormLayout(self.sketch_box)
            self.merge = self._spin(0, 1000, "FW_DxfMerge", " mm", 0.0001)
            sf.addRow("Merge points closer than:", self.merge)
            self.constraints = QtWidgets.QCheckBox("Add constraints")
            self.constraints.setObjectName("FW_DxfConstraints")
            self.constraints.setChecked(True)
            sf.addRow(self.constraints)
            left.addWidget(self.sketch_box)
            left.addStretch(1)
            self.preview = Preview(w)
            self.preview.picked.connect(self._picked)
            h.addWidget(self.preview, 1)
            return w

        def _spin(self, lo, hi, name, suffix=" mm", value=0.0):
            s = QtWidgets.QDoubleSpinBox()
            s.setObjectName(name)
            s.setRange(lo, hi)
            s.setDecimals(4)
            s.setSuffix(suffix)
            s.setValue(value)
            s.valueChanged.connect(self._refresh)
            return s

        def layers(self):
            out = set()
            for i in range(self.layer_list.count()):
                it = self.layer_list.item(i)
                if it.checkState() == QtCore.Qt.Checked:
                    out.add(it.data(QtCore.Qt.UserRole))
            return out

        def settings(self):
            return dict(layers=self.layers(), unit=self.units.currentIndex(),
                        move=(self.move_x.value(), self.move_y.value()), angle=self.rotate.value(),
                        origin=self.origin, merge=self.merge.value(), constraints=self.constraints.isChecked())

        def _edges(self):
            s = self.settings()
            return self.reading.edges(s["layers"], s["unit"], s["move"], s["angle"], s["origin"])

        def _refresh(self, *_a):
            if self.stack.currentIndex() == 1:
                self.preview.show_edges(self._edges())

        def _pick_mode(self, on):
            self.preview.picking = on
            self.preview.setCursor(QtCore.Qt.CrossCursor if on else QtCore.Qt.ArrowCursor)

        def _picked(self, x, y):
            """x, y on the preview (as shown) -> the nearest file point; it goes on the origin."""
            p = nearest(self.preview.points, x, y)
            if p is None:
                return
            # back to the file's point: undo rotate, move and scale of the shown geometry
            s = self.settings()
            a = -math.radians(s["angle"])
            px, py = p[0] * math.cos(a) - p[1] * math.sin(a), p[0] * math.sin(a) + p[1] * math.cos(a)
            px, py = px - s["move"][0], py - s["move"][1]
            k = UNITS[s["unit"]][1] / FILE_MM.get(self.reading.insunits, 1.0)
            ox, oy = (self.origin or (0.0, 0.0))
            self.origin = (px / k + ox, py / k + oy)
            for sp in (self.move_x, self.move_y):
                sp.blockSignals(True)
                sp.setValue(0.0)
                sp.blockSignals(False)
            self.pick.setChecked(False)
            self._refresh()

        def _reset_position(self):
            self.origin = None
            for sp in (self.move_x, self.move_y, self.rotate):
                sp.blockSignals(True)
                sp.setValue(0.0)
                sp.blockSignals(False)
            self._refresh()

        def _go(self, i):
            self.stack.setCurrentIndex(i)
            self.back.setVisible(i == 1)
            self.next.setVisible(i == 0)
            self._method_changed()
            self._refresh()

        def accept(self):
            """Finish (or Enter, or a script's accept()): the document is made with the settings shown."""
            if self.result_doc is None:
                s = self.settings()
                method = self.method()
                try:
                    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
                    try:
                        self.result_doc = finish(self.reading, method, **s)
                    finally:
                        QtWidgets.QApplication.restoreOverrideCursor()
                except Exception as error:
                    QtWidgets.QMessageBox.warning(self, "DXF/DWG Import", str(error))
                    return
                _params().SetString(LAST_METHOD, method)
            super().accept()


def open_wizard(path):
    """File > Open of a DXF or DWG: the wizard; the document made, or None on Cancel."""
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        reading = Reading(path)
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()
    if not any(reading.layers.values()):
        raise RuntimeError("Nothing 2D was found in the file. It may be empty or damaged.")
    box = ImportWizard(reading)
    box.exec()
    doc = box.result_doc
    if doc is not None and Gui is not None:
        try:
            Gui.SendMsgToActiveView("ViewFit")
        except Exception as _fw_err:
            _fw_log("dxfimport.py:fit", _fw_err)
    return doc
