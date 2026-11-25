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


def _error_css():
    ""
    try:
        from . import propertymanager
        return propertymanager.error_css()
    except Exception as _fw_err:
        _fw_log("slicingpm.py:31", _fw_err)
        return "color: #c00000;"
from PySide import QtCore, QtWidgets

COMMAND = "SWStyle_Slicing"
TITLE = "Slicing"
ICON = "FEATURES_CURVES"
PLANES = ("App::Plane", "PartDesign::Plane", "Part::Plane")


def _plane_of(obj, sub):
    """(origin, unit normal) of a plane feature or a flat face; None when it is neither."""
    try:
        if sub.startswith("Face"):
            face = obj.Shape.getElement(sub)
            surface = face.Surface
            if surface.__class__.__name__ != "Plane":
                return None
            return face.CenterOfMass, App.Vector(surface.Axis).normalize()
        if obj.TypeId in PLANES or getattr(obj, "Role", "") in ("XY_Plane", "XZ_Plane", "YZ_Plane"):
            p = obj.Placement
            return p.Base, p.Rotation.multVec(App.Vector(0, 0, 1)).normalize()
    except Exception as _fw_err:
        _fw_log("slicingpm.py:54", _fw_err)
        return None
    return None


def _solids(doc):
    """What there is to slice: the tip of each visible body, else every solid."""
    out = []
    for body in (o for o in doc.Objects if o.TypeId == "PartDesign::Body"):
        if body.Tip is not None and not body.Shape.isNull():
            out.append(body)
    if not out:
        out = [o for o in doc.Objects if hasattr(o, "Shape") and not o.Shape.isNull() and o.Shape.Solids
               and not o.InList]
    return out


def _to_sketch(sketch, edges, inverse):
    """edges (in model coordinates) into sketch, as its own geometry (lines, arcs, circles, splines)."""
    import Part
    for edge in edges:
        e = edge.copy()
        e.transformShape(inverse)
        try:
            curve = e.Curve
            kind = curve.__class__.__name__
            if kind == "Line":
                sketch.addGeometry(Part.LineSegment(e.Vertexes[0].Point, e.Vertexes[-1].Point))
            elif kind == "Circle" and e.isClosed():
                sketch.addGeometry(Part.Circle(curve.Center, App.Vector(0, 0, 1), curve.Radius))
            elif kind == "Circle":
                # through the edge's own start, middle and end: the edge's parameters belong to its own
                # circle, whose start direction a new circle does not share
                flat = lambda v: App.Vector(v.x, v.y, 0)
                mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
                sketch.addGeometry(Part.Arc(flat(e.Vertexes[0].Point), flat(mid), flat(e.Vertexes[-1].Point)))
            else:
                sketch.addGeometry(curve.toBSpline(e.FirstParameter, e.LastParameter))
        except Exception:
            try:
                sketch.addGeometry(Part.LineSegment(e.Vertexes[0].Point, e.Vertexes[-1].Point))
            except Exception as _fw_err:
                _fw_log("slicingpm.py:90", _fw_err)


def _to_sketch3d(data, edges, normal):
    """edges (model coordinates, on a plane square to normal) into a 3D sketch's points / entities /
    relations: lines, circles and arcs (with their ArcPlane), anything else a spline through points."""
    from . import sketch3dsolve as S3
    pts, ents, rels = data
    n = App.Vector(normal)
    n.normalize()

    def point(v):
        pts.append((v.x, v.y, v.z))
        return len(pts) - 1

    for e in edges:
        try:
            kind = e.Curve.__class__.__name__
            if kind == "Line":
                ents.append(S3.Entity("L", [point(e.Vertexes[0].Point), point(e.Vertexes[-1].Point)]))
            elif kind == "Circle":
                c = point(e.Curve.Center)
                a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
                if e.isClosed():
                    ia = point(a)
                    ents.append(S3.Entity("C", [c, ia]))
                    rels.append(S3.Relation("ArcPlane", [c, ia, ia], [n.x, n.y, n.z]))
                    continue
                axis = e.Curve.Axis
                if e.Orientation == "Reversed":
                    axis = axis * -1
                if axis.dot(n) < 0:
                    a, b = b, a        # counterclockwise about the slice's normal
                ia, ib = point(a), point(b)
                ents.append(S3.Entity("A", [c, ia, ib]))
                rels.append(S3.Relation("ArcPlane", [c, ia, ib], [n.x, n.y, n.z]))
            else:
                ents.append(S3.Entity("S", [point(v) for v in e.discretize(12)]))
        except Exception as _fw_err:
            _fw_log("slicingpm _to_sketch3d", _fw_err)


def _shape(doc):
    import Part
    solids = _solids(doc)
    if not solids:
        return None
    shape = Part.makeCompound([o.Shape for o in solids])
    if not shape.isValid():
        try:
            fixed = shape.copy()
            fixed.fix(1e-7, 1e-7, 1e-7)
            if fixed.isValid():
                shape = fixed
        except Exception as _fw_err:
            _fw_log("slicingpm.py:106", _fw_err)
    return shape


def slice_edges(shape, origin, normal, count, spacing, reverse=False):
    """[(point, edges)] for each slice that meets the shape (the preview and make share it)."""
    n = App.Vector(normal)
    n.normalize()
    if reverse:
        n = n * -1
    out = []
    for i in range(int(count)):
        point = App.Vector(origin) + n * (spacing * i)
        d = n.dot(point)
        edges = []
        for nudge in (0.0, 1e-3, -1e-3):
            try:
                wires = shape.slice(n, d + nudge)
            except Exception:
                wires = []
            edges = [e for w in wires for e in w.Edges]
            if edges:
                break
        out.append((point, edges))
    return out


class _Preview:
    ""

    def __init__(self):
        self.node = None
        self.view = None

    def show(self, slices):
        self.clear()
        try:
            from pivy import coin
            self.view = Gui.ActiveDocument.ActiveView
            sep = coin.SoSeparator()
            style = coin.SoDrawStyle()
            style.lineWidth = 2
            colour = coin.SoBaseColor()
            colour.rgb = (1.0, 0.85, 0.0)
            sep.addChild(style)
            sep.addChild(colour)
            pts, counts = [], []
            for _, edges in slices:
                for e in edges:
                    line = [tuple(v) for v in e.discretize(Deflection=0.05)]
                    if len(line) > 1:
                        pts.extend(line)
                        counts.append(len(line))
            if not pts:
                return
            co = coin.SoCoordinate3()
            co.point.setValues(0, len(pts), pts)
            ls = coin.SoLineSet()
            ls.numVertices.setValues(0, len(counts), counts)
            sep.addChild(co)
            sep.addChild(ls)
            self.view.getSceneGraph().addChild(sep)
            self.node = sep
        except Exception as error:
            App.Console.PrintLog("FreeCAD: slicing preview: %s\n" % error)

    def clear(self):
        if self.node is not None and self.view is not None:
            try:
                self.view.getSceneGraph().removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("slicingpm.py:177", _fw_err)
        self.node = None


def make(doc, origin, normal, count, spacing, reverse=False, single=False):
    """The slices as sketches in a Slicing group. Returns the group."""
    import Part
    from . import naming
    n = App.Vector(normal)
    n.normalize()
    if reverse:
        n = n * -1
    solids = _solids(doc)
    if not solids:
        raise RuntimeError("Nothing to slice: make a part first.")
    shape = Part.makeCompound([o.Shape for o in solids])
    if not shape.isValid():
        # pkg108: on the PC the part came with "Refine failed" and every slice was empty;
        # a healed copy slices
        try:
            fixed = shape.copy()
            fixed.fix(1e-7, 1e-7, 1e-7)
            if fixed.isValid():
                shape = fixed
        except Exception as _fw_err:
            _fw_log("slicingpm.py:202", _fw_err)
    doc.openTransaction("Slicing")
    try:
        group = doc.addObject("App::DocumentObjectGroup", "Slicing")
        group.Label = naming.next_label(doc, "Slicing")
        rotation = App.Rotation(App.Vector(0, 0, 1), n)
        made = []
        single_sketch = None
        for i in range(int(count)):
            point = App.Vector(origin) + n * (spacing * i)
            d = n.dot(point)
            edges = []
            for nudge in (0.0, 1e-3, -1e-3):     # a slice right on a face of the model is empty: nudge it 1 micron in
                try:
                    wires = shape.slice(n, d + nudge)
                except Exception:
                    wires = []
                edges = [e for w in wires for e in w.Edges]
                if edges:
                    break
            if not edges:
                continue
            if single:

                if single_sketch is None:
                    from . import sketch3d
                    single_sketch = sketch3d.make(doc)
                    single_sketch.Label = "3DSlices"
                    group.addObject(single_sketch)
                    made.append(single_sketch)
                    data3d = ([], [], [])
                _to_sketch3d(data3d, edges, n)
                continue
            else:
                target = doc.addObject("Sketcher::SketchObject", "Slice")
                target.Label = "Slice%d" % (i + 1)
                target.Placement = App.Placement(point, rotation)
                group.addObject(target)
                made.append(target)
            _to_sketch(target, edges, target.Placement.inverse().toMatrix())
        if not made:
            raise RuntimeError("No slice meets the part: check the plane, the direction (Reverse) and the spacing.")
        if single_sketch is not None:
            from . import sketch3d
            sketch3d.store(single_sketch, *data3d)
        doc.recompute()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    return group


class SlicingPanel:
    ""

    def __init__(self, doc, plane=None):
        self.doc = doc
        self.plane = plane              # (object, sub) picked before or on the panel
        page = QtWidgets.QWidget()
        page.setWindowTitle("Slicing Plane")
        page.setProperty("swstyle_pm_title", TITLE)
        page.setProperty("swstyle_pm_icon", ICON)
        lay = QtWidgets.QVBoxLayout(page)
        self.box = QtWidgets.QListWidget()
        self.box.setObjectName("SWStyle_SlicingPlane")
        self.box.setMaximumHeight(44)
        self.box.setToolTip("Plane or flat face the slices start from")
        lay.addWidget(self.box)
        try:
            # right-click Delete / Clear Selections and the Delete key take the plane out
            from . import pmboxes
            pmboxes.bind(self.box, lambda row: self.clear_plane(), self.clear_plane)
        except Exception as _fw_err:
            _fw_log("slicingpm.py:270", _fw_err)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        self.reverse.setObjectName("SWStyle_SlicingReverse")
        lay.addWidget(self.reverse)
        params = QtWidgets.QWidget()
        params.setWindowTitle("Slicing Parameters")
        form = QtWidgets.QFormLayout(params)
        self.count = QtWidgets.QSpinBox()
        self.count.setObjectName("SWStyle_SlicingCount")
        self.count.setRange(1, 999)
        self.count.setValue(5)
        form.addRow("Number of slices:", self.count)
        self.spacing = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        self.spacing.setObjectName("SWStyle_SlicingSpacing")
        self.spacing.setProperty("unit", "mm")
        self.spacing.setProperty("rawValue", 5.0)
        form.addRow("Spacing:", self.spacing)
        options = QtWidgets.QWidget()
        options.setWindowTitle("Options")
        inner = QtWidgets.QVBoxLayout(options)
        self.single = QtWidgets.QCheckBox("Create one 3D sketch")
        self.single.setObjectName("SWStyle_SlicingSingle")
        self.single.setToolTip("All the slices in one sketch; off, a 2D sketch per slice")
        inner.addWidget(self.single)
        self.message = QtWidgets.QLabel("")
        self.message.setWordWrap(True)
        inner.addWidget(self.message)
        self.form = [page, params, options]
        self.preview = _Preview()
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._update_preview)
        self.reverse.toggled.connect(lambda *a: self._timer.start())
        self.count.valueChanged.connect(lambda *a: self._timer.start())
        try:
            self.spacing.valueChanged.connect(lambda *a: self._timer.start())
        except Exception as _fw_err:
            _fw_log("slicingpm.py:308", _fw_err)
        self._show()
        Gui.Selection.addObserver(self)

    def _show(self):
        self.box.clear()
        if self.plane is not None:
            obj, sub = self.plane
            self.box.addItem(("%s@%s" % (sub, obj.Label)) if sub else obj.Label)
        self.message.setText("" if self.plane else "Select a plane or a flat face to slice from.")
        self.message.setStyleSheet("")
        if hasattr(self, "_timer"):
            self._timer.start()

    def _update_preview(self):
        if self.plane is None:
            self.preview.clear()
            return
        try:
            shape = _shape(self.doc)
            origin, normal = _plane_of(*self.plane)
            slices = slice_edges(shape, origin, normal, self.count.value(), float(self.spacing.property("rawValue")),
                                 self.reverse.isChecked()) if shape is not None else []
        except Exception:
            slices = []
        self.preview.show(slices)
        if self.plane is not None and not any(edges for _, edges in slices):
            self.message.setText("No slice meets the part: check the plane, the direction (Reverse) and the spacing.")
        elif self.message.text().startswith("No slice meets"):
            self.message.setText("")

    def clear_plane(self):
        self.plane = None
        self._show()

    def _gone(self):
        if Gui.Control.activeDialog():
            return False
        try:
            self.preview.clear()
        except Exception as _fw_err:
            _fw_log("slicingpm.py:349", _fw_err)
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("slicingpm.py:353", _fw_err)
        return True

    def addSelection(self, doc, name, sub, pnt):
        try:
            if doc != self.doc.Name or self._gone():
                return
        except ReferenceError:          # its document was closed
            return
        obj = self.doc.getObject(name)
        sub = sub.split(".")[-1] if sub else ""
        if obj is not None and _plane_of(obj, sub) is not None:
            self.plane = (obj, sub)
            QtCore.QTimer.singleShot(0, self._show)

    def removeSelection(self, doc, name, sub):
        pass

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            self._timer.stop()
            self.preview.clear()
        except Exception as _fw_err:
            _fw_log("slicingpm.py:379", _fw_err)
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("slicingpm.py:383", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if self.plane is None:
            self.message.setText("Select a plane or a flat face to slice from.")
            return False
        origin, normal = _plane_of(*self.plane)
        try:
            group = make(self.doc, origin, normal, self.count.value(), float(self.spacing.property("rawValue")),
                         self.reverse.isChecked(), self.single.isChecked())
        except Exception as error:
            self.message.setText(str(error))
            self.message.setStyleSheet(_error_css())
            return False
        self._close()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(group)
        return True

    def reject(self):
        self._close()
        return True


def run():
    doc = App.ActiveDocument
    if doc is None:
        return None
    plane = None
    for sel in Gui.Selection.getSelectionEx():
        subs = [s.split(".")[-1] for s in sel.SubElementNames if s]
        for sub in subs or [""]:
            if _plane_of(sel.Object, sub) is not None:
                plane = (sel.Object, sub)
    Gui.Selection.clearSelection()
    panel = SlicingPanel(doc, plane)
    Gui.Control.showDialog(panel)
    return panel


class _Cmd:
    def GetResources(self):
        return {"MenuText": "Slicing", "ToolTip": "Section sketches through the model at evenly spaced planes.",
                "Pixmap": "Part_SliceApart"}

    def Activated(self):
        run()

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and not Gui.Control.activeDialog() and bool(_solids(doc))


def install():
    if Gui.Command.get(COMMAND) is None:
        Gui.addCommand(COMMAND, _Cmd())
