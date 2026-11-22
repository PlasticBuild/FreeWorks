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
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from .widgets import ui_font

COMMANDS = {}


def command(name, menu, tip):
    def wrap(func):
        COMMANDS[name] = (menu, tip, func)
        return func
    return wrap


# ------------------------------------------------------------------ shared helpers
def _solids_of(obj):
    shape = getattr(obj, "Shape", None)
    if shape is None or not hasattr(shape, "isNull") or shape.isNull():   # a FEM mesh's Shape is a link, not a shape
        return []
    try:
        return list(shape.Solids)
    except Exception as _fw_err:
        _fw_log("evaluate.py:50", _fw_err)
        return []


def _shown_broken(doc):
    """Names of the parts hidden only because a Model Break View shows them broken."""
    try:
        from . import modelbreak
        return {o.Source.Name for o in modelbreak.breaks(doc) if o.Active and o.Source is not None}
    except Exception:
        return set()


def visible_bodies(doc=None):
    """Top-level visible objects with solids: bodies, Part features not used by a body."""
    doc = doc or App.ActiveDocument
    out = []
    if doc is None:
        return out
    broken = _shown_broken(doc)
    for obj in doc.Objects:
        if not _solids_of(obj):
            continue
        vo = getattr(obj, "ViewObject", None)
        if vo is not None and not vo.Visibility and obj.Name not in broken:
            continue
        # a feature inside a body: the body stands for it
        if any(p.isDerivedFrom("PartDesign::Body") for p in obj.InList):
            continue
        if any(_solids_of(p) and p.TypeId != "App::Part" for p in obj.InList):
            continue
        out.append(obj)
    return out


def picked_or_visible():
    picked = []
    for sel in Gui.Selection.getSelectionEx():
        obj = sel.Object
        body = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
        if body is not None and body.isDerivedFrom("PartDesign::Body"):
            obj = body
        if obj not in picked and _solids_of(obj):
            picked.append(obj)
    return picked or visible_bodies()


def _jacobi(m):
    from .massprops import _jacobi as jac
    return jac(m)


def _f(v, n=2):
    return ("%%.%df" % n) % v


# ------------------------------------------------------------------ the document's units

# Properties > Units); the computing stays in mm. unitspage.length_unit gives the unit.
POWER_MARK = {1: "", 2: "\u00b2", 3: "\u00b3"}


def doc_unit(doc=None):
    """(symbol, mm per unit) of the active part's length unit; ("mm", 1.0) when it cannot be read."""
    try:
        from . import unitspage
        sym, mm = unitspage.length_unit(doc or App.ActiveDocument)
        return sym, float(mm)
    except Exception as _fw_err:
        _fw_log("evaluate.py:doc_unit", _fw_err)
        return "mm", 1.0


def unit_name(power=1, doc=None):
    return doc_unit(doc)[0] + POWER_MARK[power]


def in_doc(v, power=1, doc=None):
    """A value in mm (mm^2, mm^3) in the document's unit."""
    return v / doc_unit(doc)[1] ** power


def len_text(v, power=1, n=3, doc=None, fmt=None):
    """A length (area, volume) in mm as text in the document's unit: "0.039 in"."""
    return (fmt or "%%.%df" % (n + (1 if doc_unit(doc)[1] > 1.0 else 0))) % in_doc(v, power, doc) + " " + unit_name(power, doc)


def unit_spin(spin, power=1, doc=None):
    """A spin box made in mm shown in the document's unit; mm_of(spin) reads it back in mm."""
    sym, mm = doc_unit(doc)
    k = mm ** power
    spin.setProperty("swmm", k)
    if k == 1.0:
        return spin
    v, lo, hi = spin.value(), spin.minimum(), spin.maximum()
    spin.blockSignals(True)
    try:
        spin.setDecimals(spin.decimals() + (1 if power == 1 else 2))
        step = 10.0 ** -spin.decimals()
        spin.setRange(max(lo / k, step), hi / k)
        spin.setSuffix(" " + sym + POWER_MARK[power])
        spin.setValue(v / k)
    finally:
        spin.blockSignals(False)
    return spin


def mm_of(spin):
    """A spin box's value in mm (mm^2, mm^3), whatever unit it shows (unit_spin)."""
    k = spin.property("swmm")
    return spin.value() * (float(k) if k else 1.0)


class FaceColours:
    """Per-face colours on an object's view, put back as they were on restore()."""

    def __init__(self):
        self.saved = {}

    @staticmethod
    def _view(obj):
        """The view that draws the faces: a PartDesign body shows its tip feature's shape."""
        tip = getattr(obj, "Tip", None) if obj.isDerivedFrom("PartDesign::Body") else None
        return (tip or obj).ViewObject

    def paint(self, obj, colours):
        vo = self._view(obj)
        if obj not in self.saved:
            # FreeCAD 1.1 keeps per-face colours in ShapeAppearance (no DiffuseColor on a body's
            # view): save and restore the materials, paint a copy of the first with each colour.
            self.saved[obj] = list(vo.ShapeAppearance)
        base = vo.ShapeAppearance[0] if vo.ShapeAppearance else App.Material()
        materials = []
        for c in colours:
            m = App.Material()
            for name in ("AmbientColor", "SpecularColor", "EmissiveColor", "Shininess", "Transparency"):
                try:
                    setattr(m, name, getattr(base, name))
                except Exception as _fw_err:
                    _fw_log("evaluate.py:130", _fw_err)
            m.DiffuseColor = tuple(float(x) for x in c[:3]) + (1.0,)
            materials.append(m)
        vo.ShapeAppearance = materials

    def restore(self):
        for obj, materials in self.saved.items():
            try:
                self._view(obj).ShapeAppearance = materials
            except Exception as _fw_err:
                _fw_log("evaluate.py:140", _fw_err)
        self.saved = {}


class Overlay:
    """Shapes drawn in the 3D view only (interference volumes), not in the document."""

    def __init__(self):
        self.nodes = []

    def add(self, shape, rgb=(1.0, 0.0, 0.0), transparency=0.3):
        from pivy import coin
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None or shape.isNull():
            return
        sep = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*rgb)
        mat.emissiveColor.setValue(rgb[0] * 0.4, rgb[1] * 0.4, rgb[2] * 0.4)
        mat.transparency.setValue(transparency)
        sep.addChild(mat)
        inp = coin.SoInput()
        inp.setBuffer(shape.writeInventor())
        node = coin.SoDB.readAll(inp)
        if node is None:
            return
        sep.addChild(node)
        view.getSceneGraph().addChild(sep)
        self.nodes.append((view, sep))

    def clear(self):
        for view, sep in self.nodes:
            try:
                view.getSceneGraph().removeChild(sep)
            except Exception as _fw_err:
                _fw_log("evaluate.py:175", _fw_err)
        self.nodes = []


class ReportWindow(QtWidgets.QDialog):
    """Title row of options, a results table or text, and Recalculate / Copy / Close."""

    def __init__(self, title, columns=None, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle(title)
        self.setObjectName("SWEvaluate_" + title.replace(" ", ""))
        self.setFont(ui_font())
        self.resize(560, 480)
        self.layout_ = QtWidgets.QVBoxLayout(self)
        self.options = QtWidgets.QHBoxLayout()
        self.layout_.addLayout(self.options)
        if columns:
            self.table = QtWidgets.QTreeWidget()
            self.table.setHeaderLabels(columns)
            self.table.setRootIsDecorated(False)
            self.table.setAlternatingRowColors(True)
            self.table.itemSelectionChanged.connect(self._picked)
            self.layout_.addWidget(self.table, 1)
            self.text = None
        else:
            self.table = None
            self.text = QtWidgets.QPlainTextEdit()
            self.text.setReadOnly(True)
            self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
            self.text.setTabStopDistance(36)
            self.layout_.addWidget(self.text, 1)
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.layout_.addWidget(self.summary)
        row = QtWidgets.QHBoxLayout()
        self.recalc = QtWidgets.QPushButton("Recalculate")
        self.recalc.clicked.connect(self.refresh)
        self.copy = QtWidgets.QPushButton("Copy to Clipboard")
        self.copy.clicked.connect(self._copy)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(self.recalc)
        row.addWidget(self.copy)
        row.addStretch(1)
        row.addWidget(close)
        self.layout_.addLayout(row)
        self.rows = []      # per table row: list of (doc name, object name, sub name) to select

    def set_rows(self, rows):
        self.table.clear()
        self.rows = []
        for cells, picks in rows:
            self.table.addTopLevelItem(QtWidgets.QTreeWidgetItem([str(c) for c in cells]))
            self.rows.append(picks)
        for i in range(self.table.columnCount()):
            self.table.resizeColumnToContents(i)

    def _picked(self):
        items = self.table.selectedItems()
        if not items:
            return
        i = self.table.indexOfTopLevelItem(items[0])
        if i < 0 or i >= len(self.rows):
            return
        Gui.Selection.clearSelection()
        self.row_picking = True         # a result row shows its items: not a pick for the PM's boxes
        try:
            for doc, obj, sub in self.rows[i]:
                try:
                    Gui.Selection.addSelection(doc, obj, sub)
                except Exception as _fw_err:
                    _fw_log("evaluate.py:244", _fw_err)
        finally:
            self.row_picking = False

    def _copy(self):
        if self.text is not None:
            data = self.text.toPlainText()
        else:
            head = [self.table.headerItem().text(i) for i in range(self.table.columnCount())]
            lines = ["\t".join(head)]
            for i in range(self.table.topLevelItemCount()):
                it = self.table.topLevelItem(i)
                lines.append("\t".join(it.text(j) for j in range(self.table.columnCount())))
            data = "\n".join(lines + ["", self.summary.text()])
        QtWidgets.QApplication.clipboard().setText(data)

    def refresh(self):
        try:
            self.compute()
        except Exception as error:
            self.summary.setText("Could not compute: %s" % error)

    def compute(self):
        pass

    def cleanup(self):
        pass

    def closeEvent(self, event):
        self.cleanup()
        _OPEN.pop(type(self).__name__, None)
        super().closeEvent(event)


_OPEN = {}


def _show(cls):
    win = _OPEN.get(cls.__name__)
    if win is None or not win.isVisible():
        win = cls()
        _OPEN[cls.__name__] = win
    win.refresh()
    win.show()
    win.raise_()
    win.activateWindow()
    return win


# ------------------------------------------------------------------ Section Properties
def section_picks():
    """[(label, face, sketch placement or None)] of the picks: planar faces, and the faces a picked
    sketch's closed contours make (with the sketch, for its origin and axes)."""
    out = []
    for sel in Gui.Selection.getSelectionEx():
        obj = sel.Object
        sketches = []
        if obj.isDerivedFrom("Sketcher::SketchObject") and not sel.SubElementNames:
            sketches.append(obj)
        for sub in sel.SubElementNames:
            if sub.endswith("."):
                try:
                    leaf = obj.getSubObject(sub, 1)
                except Exception:
                    leaf = None
                if leaf is not None and leaf.isDerivedFrom("Sketcher::SketchObject"):
                    sketches.append(leaf)
        for sk in sketches:
            try:
                import Part
                place = sk.getGlobalPlacement() if hasattr(sk, "getGlobalPlacement") else sk.Placement
                wires = [w for w in sk.Shape.Wires if w.isClosed()]
                if wires:
                    face = Part.makeFace(wires, "Part::FaceMakerBullseye")
                    out.append((sk.Label, face, place))
            except Exception as error:
                App.Console.PrintLog("Section Properties: %s: %s\n" % (sk.Label, error))
        if sketches:
            continue
        for sub, shp in zip(sel.SubElementNames, sel.SubObjects):
            if sub.startswith("Face") and shp.Surface.__class__.__name__ == "Plane":
                out.append(("%s of %s" % (sub, obj.Label), shp, None))
    return out


def section_faces():
    """Picked planar faces, or the faces made by picked sketches' closed wires."""
    return [f for _l, f, _p in section_picks()]


def _num(value, n=None):
    if abs(value) < 1e-9:
        value = 0.0
    try:
        from . import massprops
        return massprops._fmt(value)
    except Exception:
        return _f(value, 2 if n is None else n)


def section_data(faces):
    """Area, centroid, area moments about the centroid (OCC's sign: products negative) and the
    principal moments and axes of coplanar faces; None without faces."""
    if not faces:
        return None
    n0 = faces[0].normalAt(0, 0)
    faces = [f for f in faces if abs(abs(f.normalAt(0, 0).dot(n0)) - 1.0) < 1e-6]
    area = sum(f.Area for f in faces)
    c = App.Vector()
    for f in faces:
        c += f.CenterOfMass * f.Area
    c = c * (1.0 / area)
    m = [[0.0] * 3 for _ in range(3)]
    for f in faces:
        mi = f.MatrixOfInertia
        d = f.CenterOfMass - c
        dv = (d.x, d.y, d.z)
        for i in range(3):
            for j in range(3):
                shift = f.Area * ((dv[0] ** 2 + dv[1] ** 2 + dv[2] ** 2) * (i == j) - dv[i] * dv[j])
                m[i][j] += mi.A[i * 4 + j] + shift
    return {"faces": faces, "area": area, "center": c, "m": m, "normal": n0, "principal": _jacobi(m)}


def _rotated(m, rot):
    """Tensor m (world axes) in the axes of rotation rot: R^T M R."""
    r = rot.toMatrix()
    R = [[r.A[i * 4 + j] for j in range(3)] for i in range(3)]
    return [[sum(R[k][i] * m[k][l] * R[l][j] for k in range(3) for l in range(3)) for j in range(3)] for i in range(3)]


def section_report(faces, frame=None, frame_label=None, sketch=None):
    d = section_data(faces)
    if d is None:
        return "Select planar faces or a sketch with closed contours, then press Recalculate."
    faces, area, c, m, n0 = d["faces"], d["area"], d["center"], d["m"], d["normal"]

    try:
        from . import massprops
        _sym, k, unit = massprops.SYSTEMS[massprops.report_system()][:3]
    except Exception:
        k, unit = 1.0, "millimeters"
    k2, k4 = k ** 2, k ** 4
    frame = frame or App.Placement()
    local = frame.inverse().multVec(c)
    mf = _rotated(m, frame.Rotation)
    where = "output coordinate system" if frame_label is None else frame_label
    lines = ["Section properties of %d selected face%s" % (len(faces), "" if len(faces) == 1 else "s"), "",
             "Area = %s square %s" % (_num(area / k2), unit), "",
             "Centroid relative to %s origin: ( %s )" % (where, unit)]
    for axis, value in zip("XYZ", (local.x, local.y, local.z)):
        lines.append("\t%s = %s" % (axis, _num(value / k)))
    if sketch is not None:
        s = sketch.inverse().multVec(c)
        lines += ["", "Centroid relative to sketch origin: ( %s )" % unit,
                  "\tX = %s" % _num(s.x / k), "\tY = %s" % _num(s.y / k)]
    lines += ["", "Moments of area, at the centroid, aligned with the output coordinate system: ( %s ^ 4 )" % unit]
    names = "xyz"
    for i in range(3):
        lines.append("\t" + "\t".join("L%s%s = %s" % (names[i], names[j], _num((mf[i][j] if i == j else -mf[i][j]) / k4))
                                      for j in range(3)))
    lines += ["", "Polar moment of area, at the centroid = %s %s ^ 4" % (_num(_polar(m, n0) / k4), unit)]
    principal = d["principal"]
    if sketch is not None:
        sx = sketch.Rotation.multVec(App.Vector(1, 0, 0))
        # the in-plane principal axis of the smaller moment (Ix), against the sketch's X axis
        flat = [p for p in principal if abs(App.Vector(*p[1]).dot(n0)) < 0.5] or principal
        ax = App.Vector(*min(flat, key=lambda p: p[0])[1])
        ax = ax - n0 * ax.dot(n0)
        if ax.Length > 1e-9:
            ang = math.degrees(math.atan2(n0.dot(sx.cross(ax)), sx.dot(ax)))
            while ang > 90:
                ang -= 180
            while ang <= -90:
                ang += 180
            lines += ["", "Angle between principal axes and sketch axes = %s degrees" % _num(ang)]
    lines += ["", "Principal axes of area and principal moments of area, at the centroid: ( %s ^ 4 )" % unit]
    for name, (moment, axis) in zip(("Ix", "Iy", "Iz"), principal):
        a = frame.Rotation.inverted().multVec(App.Vector(*axis))
        lines.append("\t %s = (%s, %s, %s)   \tP%s = %s" % (name, _f(a.x, 3), _f(a.y, 3), _f(a.z, 3), name[1], _num(moment / k4)))
    # parallel axis: moments about the output coordinate system's origin, along its axes
    dvec = c - frame.Base
    dv = (dvec.x, dvec.y, dvec.z)
    mo = [[m[i][j] + area * ((dv[0] ** 2 + dv[1] ** 2 + dv[2] ** 2) * (i == j) - dv[i] * dv[j]) for j in range(3)]
          for i in range(3)]
    mo = _rotated(mo, frame.Rotation)
    lines += ["", "Moments of area, at the output coordinate system: ( %s ^ 4 )" % unit]
    for i in range(3):
        lines.append("\t" + "\t".join("I%s%s = %s" % (names[i], names[j], _num((mo[i][j] if i == j else -mo[i][j]) / k4))
                                      for j in range(3)))
    return "\n".join(lines)


def _polar(m, n):
    """Polar moment about the face normal through the centroid: n . M . n."""
    v = (n.x, n.y, n.z)
    return sum(v[i] * m[i][j] * v[j] for i in range(3) for j in range(3))


class SectionPropertiesWindow(ReportWindow):
    ""




    def __init__(self):
        super().__init__("Section Properties")
        from . import massprops
        self.massprops = massprops
        self.options_button = QtWidgets.QPushButton("Options...")
        self.options_button.setObjectName("SWSectionOptions")
        self.options_button.clicked.connect(self._options)
        self.options.addWidget(self.options_button)
        self.options.addStretch(1)
        at = 1
        self.items = QtWidgets.QListWidget()
        self.items.setObjectName("SWSectionSelected")
        self.items.setMaximumHeight(64)
        self.layout_.insertWidget(at, QtWidgets.QLabel("Selected items:"))
        self.layout_.insertWidget(at + 1, self.items)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Report coordinate values relative to:"))
        self.frame = QtWidgets.QComboBox()
        self.frame.setObjectName("SWSectionFrame")
        self.frame.activated.connect(lambda *a: self.refresh())
        row.addWidget(self.frame, 1)
        self.layout_.insertLayout(at + 2, row)
        self.axis = QtWidgets.QCheckBox("Show output coordinate system in corner of window")
        self.axis.setObjectName("SWSectionShowAxis")
        self.axis.setChecked(True)
        self.axis.toggled.connect(self._axis)
        self.layout_.insertWidget(self.layout_.count() - 1, self.axis)
        self.print_button = QtWidgets.QPushButton("Print...")
        self.print_button.setObjectName("SWSectionPrint")
        self.print_button.clicked.connect(self._print)
        self.layout_.itemAt(self.layout_.count() - 1).layout().insertWidget(1, self.print_button)
        self.triad = massprops.Triad()
        self._axis_before = None
        self._sel_timer = QtCore.QTimer(self)
        self._sel_timer.setSingleShot(True)
        self._sel_timer.setInterval(150)
        self._sel_timer.timeout.connect(lambda: self.isVisible() and self.refresh())
        self._observer = massprops._SelWatch(self._sel_timer)
        Gui.Selection.addObserver(self._observer)

    def _frames(self):
        doc = App.ActiveDocument
        items = [("-- default --", None)] + self.massprops.frames(doc)
        now = self.frame.currentText()
        self.frame.blockSignals(True)
        self.frame.clear()
        for label, _p in items:
            self.frame.addItem(label)
        index = self.frame.findText(now)
        self.frame.setCurrentIndex(index if index >= 0 else 0)
        self.frame.blockSignals(False)
        return dict(items)

    def compute(self):
        picks = section_picks()
        self.items.clear()
        for label, _f_, _p in picks:
            self.items.addItem(label)
        places = self._frames()
        label = self.frame.currentText()
        frame = places.get(label)
        sketch = next((p for _l, _fc, p in picks if p is not None), None)
        faces = [fc for _l, fc, _p in picks]
        self.text.setPlainText(section_report(faces, frame, None if frame is None else label, sketch))
        d = section_data(faces)
        if d is None:
            self.triad.hide()
            return
        self.triad.show({"center": tuple(d["center"]), "principal": d["principal"], "shapes": d["faces"],
                         "volume": d["area"] ** 1.5})
        self._axis(self.axis.isChecked())

    def _options(self):
        if self.massprops.OptionsBox(self, axis=False).exec_():      # massprops-1119: its own corner-axis box stays on this dialog
            self.refresh()

    def _print(self):
        """Print... the report; without Qt's print support, a PDF of it opens instead."""
        from PySide import QtGui as G
        doc = G.QTextDocument(self.text.toPlainText())
        try:
            try:
                from PySide import QtPrintSupport
            except ImportError:
                from PySide6 import QtPrintSupport
            printer = QtPrintSupport.QPrinter()
            if QtPrintSupport.QPrintDialog(printer, self).exec_():
                (doc.print_ if hasattr(doc, "print_") else doc.print)(printer)
        except Exception:
            import os
            import tempfile
            path = os.path.join(tempfile.gettempdir(), "Section-Properties.pdf")
            try:
                open(path, "ab").close()        # pkg321: still open (locked) in a PDF viewer: a new name
            except OSError:
                path = os.path.join(tempfile.gettempdir(), "Section-Properties-%d.pdf" % int(time.time() * 1000))
            writer = G.QPdfWriter(path)
            (doc.print_ if hasattr(doc, "print_") else doc.print)(writer)
            del writer
            G.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))
            self.pdf = path

    def _axis(self, on):
        """The view's corner coordinate system, on while the box asks for it (put back on close)."""
        try:
            view = Gui.ActiveDocument.ActiveView
        except Exception:
            return
        if not hasattr(view, "setAxisCross"):
            return
        if self._axis_before is None:
            try:
                self._axis_before = (view, bool(view.hasAxisCross()))
            except Exception:
                self._axis_before = (view, False)
        try:
            view.setAxisCross(bool(on))
        except Exception as _fw_err:
            _fw_log("evaluate.py:554", _fw_err)

    def cleanup(self):
        self.triad.hide()
        try:
            Gui.Selection.removeObserver(self._observer)
        except Exception as _fw_err:
            _fw_log("evaluate.py:561", _fw_err)
        if self._axis_before is not None:
            view, was = self._axis_before
            try:
                view.setAxisCross(was)
            except Exception as _fw_err:
                _fw_log("evaluate.py:567", _fw_err)
            self._axis_before = None


@command("SWStyle_SectionProperties", "Section Properties",
         "Area, centroid and area moments of the selected planar faces or sketch.")
def section_properties():
    return _show(SectionPropertiesWindow)


# ------------------------------------------------------------------ Interference Detection
def interferences(objs, tol=1e-6):
    out = []
    shapes = [(o, o.Shape) for o in objs]
    # multibody parts: each solid of one object against the others too
    items = []
    for o, s in shapes:
        sol = list(s.Solids)
        if len(sol) == 1:
            items.append((o.Label, o, sol[0]))
        else:
            for k, so in enumerate(sol):
                items.append(("%s / body %d" % (o.Label, k + 1), o, so))
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i][2], items[j][2]
            if not a.BoundBox.intersect(b.BoundBox):
                continue
            try:
                common = a.common(b)
            except Exception:
                continue
            if common.isNull() or common.Volume <= tol:
                continue
            out.append((items[i], items[j], common))
    return out


class InterferenceWindow(ReportWindow):
    ""


    def __init__(self):
        super().__init__("Interference Detection", ["Interference", "Volume (%s)" % unit_name(3)])
        self.recalc.setText("Calculate")
        self.overlay = Overlay()

    def compute(self):
        self.overlay.clear()
        objs = picked_or_visible()
        found = interferences(objs)
        rows = []
        for k, (a, b, common) in enumerate(found):
            self.overlay.add(common)
            doc = a[1].Document.Name
            rows.append((("Interference%d: %s, %s" % (k + 1, a[0], b[0]), _f(in_doc(common.Volume, 3), 4 if doc_unit()[1] > 1 else 2)),
                         [(doc, a[1].Name, ""), (doc, b[1].Name, "")]))
        self.set_rows(rows)
        self.summary.setText("%d bodies checked. %s" % (
            len(objs), "No interferences." if not found else "%d interference%s, shown in red." % (len(found), "" if len(found) == 1 else "s")))

    def cleanup(self):
        self.overlay.clear()


@command("SWStyle_InterferenceDetection", "Interference Detection",
         "Finds overlapping volumes between the bodies of the part.")
def interference_detection():
    return _show(InterferenceWindow)


# ------------------------------------------------------------------ Draft Analysis
POSITIVE, NEGATIVE, REQUIRES, STRADDLE = (0.0, 0.75, 0.0), (0.85, 0.0, 0.0), (1.0, 0.85, 0.0), (0.2, 0.55, 1.0)


def _face_angles(face, pull, n=5):
    """Draft angles (deg) sampled over the face: 90 - angle(normal, pull); positive faces the pull."""
    u0, u1, v0, v1 = face.ParameterRange
    out = []
    for i in range(n):
        for j in range(n):
            u = u0 + (u1 - u0) * (i + 0.5) / n
            v = v0 + (v1 - v0) * (j + 0.5) / n
            try:
                if not face.isInside(face.valueAt(u, v), 1e-6, True):
                    continue
                nrm = face.normalAt(u, v)
            except Exception:
                continue
            cosang = max(-1.0, min(1.0, nrm.dot(pull)))
            out.append(90.0 - math.degrees(math.acos(cosang)))
    if not out:
        try:
            cosang = max(-1.0, min(1.0, face.normalAt(*face.Surface.parameter(face.CenterOfMass)).dot(pull)))
            out.append(90.0 - math.degrees(math.acos(cosang)))
        except Exception:
            out.append(0.0)
    return out


def classify_draft(face, pull, angle):
    a = _face_angles(face, pull)
    if min(a) >= angle - 1e-6:
        return "positive"
    if max(a) <= -angle + 1e-6:
        return "negative"
    if max(a) < angle and min(a) > -angle:
        return "requires"
    return "straddle"


COLOURS = {"positive": POSITIVE, "negative": NEGATIVE, "requires": REQUIRES, "straddle": STRADDLE}
LABELS = {"positive": "Positive draft", "negative": "Negative draft", "requires": "Requires draft", "straddle": "Straddle faces"}


def _pull_from_selection():
    for sel in Gui.Selection.getSelectionEx():
        for sub, shp in zip(sel.SubElementNames, sel.SubObjects):
            try:
                if sub.startswith("Face") and shp.Surface.__class__.__name__ == "Plane":
                    return shp.normalAt(0, 0), "%s.%s" % (sel.Object.Label, sub)
                if sub.startswith("Edge") and shp.Curve.__class__.__name__ in ("Line", "LineSegment"):
                    d = shp.Vertexes[-1].Point - shp.Vertexes[0].Point
                    return d.normalize(), "%s.%s" % (sel.Object.Label, sub)
            except Exception:
                continue
        obj = sel.Object
        if obj.isDerivedFrom("App::Plane") or obj.isDerivedFrom("PartDesign::Plane"):
            return obj.Placement.Rotation.multVec(App.Vector(0, 0, 1)), obj.Label
    return None, None


class DraftAnalysisWindow(ReportWindow):
    ""


    def __init__(self):
        super().__init__("Draft Analysis", ["Face classification", "Faces"])
        self.recalc.setText("Calculate")
        self.colours = FaceColours()
        self.options.addWidget(QtWidgets.QLabel("Direction of pull:"))
        self.direction = QtWidgets.QLabel("Z axis")
        self.options.addWidget(self.direction)
        self.reverse = QtWidgets.QCheckBox("Reverse")
        self.options.addWidget(self.reverse)
        self.options.addWidget(QtWidgets.QLabel("Draft angle:"))
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setRange(0.0, 89.0)
        self.angle.setValue(1.0)
        self.angle.setSuffix(" °")
        self.options.addWidget(self.angle)
        self.options.addStretch(1)
        self.pull = App.Vector(0, 0, 1)
        self.reverse.toggled.connect(self.refresh)
        self.angle.valueChanged.connect(self.refresh)
        self.counts = {}

    def compute(self):
        pull, name = _pull_from_selection()
        if pull is not None:
            self.pull, self.direction_name = pull, name
            self.direction.setText(name)
        pull = self.pull * (-1.0 if self.reverse.isChecked() else 1.0)
        self.colours.restore()
        counts = dict.fromkeys(COLOURS, 0)
        for obj in visible_bodies():
            kinds = [classify_draft(f, pull, self.angle.value()) for f in obj.Shape.Faces]
            for k in kinds:
                counts[k] += 1
            self.colours.paint(obj, [COLOURS[k] for k in kinds])
        self.counts = counts
        self.set_rows([((LABELS[k], counts[k]), []) for k in ("positive", "requires", "negative", "straddle")])
        self.summary.setText("Green faces have at least the draft angle towards the pull, red away from it, "
                             "yellow need draft, blue faces straddle. Pick a planar face or a straight edge, "
                             "then Calculate, to set the direction of pull.")

    def cleanup(self):
        self.colours.restore()


@command("SWStyle_DraftAnalysis", "Draft Analysis",
         "Colours faces by their draft against a direction of pull.")
def draft_analysis():
    return _show(DraftAnalysisWindow)


# ------------------------------------------------------------------ Geometry Analysis
def geometry_problems(objs, edge_len=0.1, face_angle=10.0):
    ""
    found = []
    for obj in objs:
        shape = obj.Shape
        doc = obj.Document.Name
        for i, e in enumerate(shape.Edges):
            if e.Length < edge_len:
                found.append(("Short edge", "Edge%d" % (i + 1), len_text(e.Length, 1, 4), (doc, obj.Name, "Edge%d" % (i + 1)), obj))
        for i, f in enumerate(shape.Faces):
            if f.Area < edge_len ** 2:
                found.append(("Small face", "Face%d" % (i + 1), len_text(f.Area, 2, 4), (doc, obj.Name, "Face%d" % (i + 1)), obj))
            else:
                w = edge_len
                p = sum(e.Length for e in f.Edges)
                if f.Area < w * (p / 2.0 - w):
                    found.append(("Sliver face", "Face%d" % (i + 1), len_text(f.Area, 2, 4), (doc, obj.Name, "Face%d" % (i + 1)), obj))
        # knife edges: the two faces meet at a sharp angle (inside angle below face_angle)
        for i, e in enumerate(shape.Edges):
            faces = shape.ancestorsOfType(e, __import__("Part").Face)
            if len(faces) != 2:
                continue
            try:
                p = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
                n1 = faces[0].normalAt(*faces[0].Surface.parameter(p))
                n2 = faces[1].normalAt(*faces[1].Surface.parameter(p))
            except Exception:
                continue
            between = 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, n1.dot(n2)))))
            if between < face_angle:
                found.append(("Knife edge", "Edge%d" % (i + 1), _f(between, 2) + " °", (doc, obj.Name, "Edge%d" % (i + 1)), obj))
    return found


class GeometryAnalysisWindow(ReportWindow):
    ""

    def __init__(self):
        super().__init__("Geometry Analysis", ["Problem", "Body", "Entity", "Value"])
        self.recalc.setText("Calculate")
        self.options.addWidget(QtWidgets.QLabel("Edge length below:"))
        self.length = QtWidgets.QDoubleSpinBox()
        self.length.setDecimals(3)
        self.length.setRange(0.001, 1000.0)
        self.length.setValue(0.1)
        self.length.setSuffix(" mm")
        self.options.addWidget(self.length)
        self.options.addWidget(QtWidgets.QLabel("Face angle below:"))
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setRange(0.1, 90.0)
        self.angle.setValue(10.0)
        self.angle.setSuffix(" °")
        self.options.addWidget(self.angle)
        self.options.addStretch(1)

    def compute(self):
        objs = picked_or_visible()
        found = geometry_problems(objs, self.length.value(), self.angle.value())
        self.set_rows([((kind, obj.Label, ent, val), [pick]) for kind, ent, val, pick, obj in found])
        self.summary.setText("%d bodies analysed. %s" % (len(objs), "No problem geometry found." if not found
                                                         else "%d item%s found; click one to select it." % (len(found), "" if len(found) == 1 else "s")))


@command("SWStyle_GeometryAnalysis", "Geometry Analysis",
         "Finds short edges, small and sliver faces and knife edges.")
def geometry_analysis():
    return _show(GeometryAnalysisWindow)


# ------------------------------------------------------------------ Performance Evaluation
def is_feature(obj):
    ""

    if obj.isDerivedFrom("App::DocumentObjectGroup") or obj.TypeId in ("PartDesign::Body", "App::Annotation",
                                                                        "Spreadsheet::Sheet", "App::Part"):
        return False
    if getattr(getattr(obj, "Proxy", None), "Type", None) in ("FreeWorksComment", "FreeWorksComments", "FreeWorksMarkups"):
        return False
    if type(getattr(obj, "Proxy", None)).__name__ == "MarkupObject":
        return False
    if any(p.isDerivedFrom("PartDesign::Body") and obj in p.Group for p in obj.InList):
        return True
    return obj.isDerivedFrom("Part::Feature") and not obj.isDerivedFrom("PartDesign::Feature") \
        and not (obj.Label or "").startswith(("Material", "Solid Bodies", "Surface Bodies"))


def tree_order(obj):
    """Where the feature sits in the FeatureManager tree: its body's place, then its place in the body."""
    doc = obj.Document
    names = [o.Name for o in doc.Objects]
    for p in obj.InList:
        if p.isDerivedFrom("PartDesign::Body") and obj in p.Group:
            return (names.index(p.Name), p.Group.index(obj))
    return (names.index(obj.Name) if obj.Name in names else 0, 0)


def feature_times(doc):
    """Recompute each feature on its own, in tree order, and time it."""
    # the times are real builds: the slow-feature result cache (fcache) is not used here
    try:
        from . import fcache
        fcache.BYPASS[0] = True
    except Exception:
        fcache = None
    try:
        return _feature_times(doc)
    finally:
        if fcache is not None:
            fcache.BYPASS[0] = False


def _feature_times(doc):
    out = []
    order = doc.TopologicalSortedObjects if hasattr(doc, "TopologicalSortedObjects") else doc.Objects
    for obj in order:
        if obj.TypeId in ("App::Origin", "App::Line", "App::Plane", "App::Point") or obj.isDerivedFrom("App::OriginFeature"):
            continue
        if not hasattr(obj, "recompute") or not is_feature(obj):
            continue
        obj.touch()
        t0 = time.perf_counter()
        try:
            obj.recompute()
        except Exception as _fw_err:
            _fw_log("evaluate.py:878", _fw_err)
        out.append((obj, time.perf_counter() - t0))
    doc.recompute()
    return out


OPEN_TIMES = {}         # document name -> seconds it took to open (Open Performance)


class _OpenWatch:
    """Times each document's opening: from its creation to the first idle moment after (a new,
    unsaved document has no file and is not counted)."""

    def slotCreatedDocument(self, doc):
        name, t0 = doc.Name, time.perf_counter()

        def done():
            d = App.listDocuments().get(name)
            if d is not None and d.FileName:
                OPEN_TIMES[name] = time.perf_counter() - t0
        QtCore.QTimer.singleShot(0, done)


_open_watch = None


def watch_open_times():
    global _open_watch
    if _open_watch is None:
        _open_watch = _OpenWatch()
        App.addDocumentObserver(_open_watch)
    return _open_watch


def triangles(bodies, deviation=None):
    """The graphics triangles the bodies need at the part's image quality (Graphics Performance)."""
    n = 0
    for b in bodies:
        try:
            dev = deviation if deviation is not None else 0.5
            box = b.Shape.BoundBox
            tol = max(1e-3, (box.XLength + box.YLength + box.ZLength) / 300.0 * dev)
            n += len(b.Shape.tessellate(tol)[1])
        except Exception:
            continue
    return n


def _key(face):
    c = face.CenterOfMass
    return (type(face.Surface).__name__, round(face.Area, 4), round(c.x, 4), round(c.y, 4), round(c.z, 4))


def feature_graphics(obj, deviation=None):
    ""

    try:
        shape = obj.Shape
        if shape.isNull() or not shape.Faces:
            return 0, 0
    except Exception:
        return 0, 0
    base = getattr(obj, "BaseFeature", None)
    old = set()
    try:
        if base is not None and not base.Shape.isNull():
            old = {_key(f) for f in base.Shape.Faces}
    except Exception:
        old = set()
    new = [f for f in shape.Faces if _key(f) not in old]
    if obj.isDerivedFrom("Sketcher::SketchObject"):
        return 0, 0
    dev = deviation if deviation is not None else 0.5
    box = shape.BoundBox
    tol = max(1e-3, (box.XLength + box.YLength + box.ZLength) / 300.0 * dev)
    n = 0
    for f in new:
        try:
            n += len(f.tessellate(tol)[1])
        except Exception:
            continue
    return len(new), n


def performance_sections(doc, times):
    ""
    total = sum(t for _, t in times)
    bodies = visible_bodies(doc)
    solids = sum(len(b.Shape.Solids) for b in bodies)
    surfaces = 0
    for o in doc.Objects:
        sh = getattr(o, "Shape", None)
        try:
            if sh is None or sh.isNull() or not sh.Faces or sh.Solids or not is_feature(o) \
                    or getattr(o, "SWStyleKind", "") == "CosmeticThread" or o.isDerivedFrom("Sketcher::SketchObject"):
                continue
            if any(p.isDerivedFrom("PartDesign::Body") for p in o.InList) or o.ViewObject is None \
                    or not o.ViewObject.Visibility:
                continue
            if any(o in getattr(x, "OutList", []) and getattr(x, "Shape", None) is not None for x in o.InList
                   if x.isDerivedFrom("Part::Feature")):
                continue        # used by a later feature
            surfaces += len(sh.Shells) or 1
        except Exception as _fw_err:
            _fw_log("evaluate.py:982", _fw_err)
    faces = sum(len(b.Shape.Faces) for b in bodies)
    edges = sum(len(b.Shape.Edges) for b in bodies)
    sketches = sum(1 for o, _t in times if o.isDerivedFrom("Sketcher::SketchObject"))
    imported = sum(1 for o, _t in times if o.TypeId == "Part::Feature")
    try:
        from . import equations
        n_eq = len(equations.equations(doc)) + len(equations.variables(doc))
    except Exception:
        n_eq = 0
    try:
        from . import configmanager
        t = configmanager.table(doc)
        n_cfg = len(t.names()) if t is not None else 1
    except Exception:
        n_cfg = 1
    slow = max(times, key=lambda x: x[1]) if times else None
    try:
        dev = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part").GetFloat("MeshDeviation", 0.5)
    except Exception:
        dev = 0.5
    check = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part/Boolean").GetBool("CheckModel", True)
    opened = OPEN_TIMES.get(doc.Name)
    return [
        ("Open Performance", [("Time to open the document",
                               (_f(opened, 3) + " s") if opened is not None else "Not opened from a file this session")]),
        ("Rebuild Performance", [("Total rebuild time", _f(total, 3) + " s"),
                                 ("Number of features", str(len(times))),
                                 ("Slowest feature", ("%s (%s s)" % (slow[0].Label, _f(slow[1], 3))) if slow else "-")]),
        ("Graphics Performance", [("Graphics triangles", str(triangles(bodies, dev))),
                                  ("Image quality (deviation)", _f(dev, 2) + " %")]),
        ("Settings Performance", [("Verification on rebuild", "On" if check else "Off")]),
        ("Statistics", [("Solid bodies", str(solids)), ("Surface bodies", str(surfaces)), ("Faces", str(faces)),
                        ("Edges", str(edges)), ("Sketches", str(sketches)), ("Imported features", str(imported)),
                        ("Equations and global variables", str(n_eq)), ("Configurations", str(n_cfg))]),
    ]


class PerformanceWindow(ReportWindow):
    ""




    def __init__(self):
        super().__init__("Performance Evaluation", ["Feature", "Time %", "Time (s)", "Faces", "Graphics Triangles"])
        self.graphics = {}
        self.recalc.setText("Refresh")
        self.sections = QtWidgets.QTreeWidget()
        self.sections.setObjectName("SWPerformanceSections")
        self.sections.setHeaderLabels(["Performance", "Value"])
        self.sections.setMaximumHeight(230)
        self.layout_.insertWidget(1, self.sections)
        self.options.addWidget(QtWidgets.QLabel("Features:"))
        self.order = QtWidgets.QComboBox()
        self.order.setObjectName("SWPerformanceSort")
        self.order.addItems(["Slowest first", "Feature order", "Most graphics triangles"])
        self.order.currentIndexChanged.connect(self._show_times)
        self.options.addWidget(self.order)
        self.options.addStretch(1)
        self.table.header().setSectionsClickable(True)
        self.table.header().sectionClicked.connect(
            lambda col: self.order.setCurrentIndex(1 if col == 0 else 2 if col in (3, 4) else 0))
        self.table.setObjectName("SWPerformanceFeatures")
        self.times = []

        self.print_button = QtWidgets.QPushButton("Print...")
        self.print_button.setObjectName("SWPerformancePrint")
        self.print_button.clicked.connect(self.print_report)
        self.layout_.itemAt(self.layout_.count() - 1).layout().insertWidget(2, self.print_button)

    def report_text(self):
        lines = [self.windowTitle(), ""]
        for i in range(self.sections.topLevelItemCount()):
            top = self.sections.topLevelItem(i)
            lines.append(top.text(0))
            for j in range(top.childCount()):
                lines.append("  %s\t%s" % (top.child(j).text(0), top.child(j).text(1)))
        lines.append("")
        lines.append("\t".join(self.table.headerItem().text(i) for i in range(self.table.columnCount())))
        for r in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(r)
            lines.append("\t".join(item.text(i) for i in range(self.table.columnCount())))
        return "\n".join(lines)

    def _copy(self):
        QtWidgets.QApplication.clipboard().setText(self.report_text())

    def print_report(self, printer=None):
        """Print...: the report on a printer (or a PDF file from the print box)."""
        try:
            from PySide6 import QtPrintSupport
        except ImportError:
            from PySide2 import QtPrintSupport
        printer = printer or QtPrintSupport.QPrinter()
        if not isinstance(printer, QtPrintSupport.QPrinter):
            printer = QtPrintSupport.QPrinter()
        if printer.outputFileName() == "":
            box = QtPrintSupport.QPrintDialog(printer, self)
            if box.exec() != QtWidgets.QDialog.Accepted:
                return False
        doc = QtGui.QTextDocument()
        doc.setPlainText(self.report_text())
        doc.print_(printer)
        return True

    def _show_times(self, *args):
        doc = App.ActiveDocument
        total = sum(t for _, t in self.times) or 1e-9
        g = self.graphics
        mode = self.order.currentIndex()
        if mode == 1:
            rows = sorted(self.times, key=lambda x: tree_order(x[0]))
        elif mode == 2:
            rows = sorted(self.times, key=lambda x: -g.get(x[0].Name, (0, 0))[1])
        else:
            rows = sorted(self.times, key=lambda x: -x[1])
        self.set_rows([((o.Label, _f(100.0 * t / total, 1), _f(t, 3), g.get(o.Name, (0, 0))[0], g.get(o.Name, (0, 0))[1]),
                        [(doc.Name, o.Name, "")]) for o, t in rows if doc is not None])

    def compute(self):
        doc = App.ActiveDocument
        self.sections.clear()
        if doc is None:
            self.times = []
            self.set_rows([])
            self.summary.setText("Open a part first.")
            return
        self.times = feature_times(doc)
        dev = None
        try:
            dev = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Part").GetFloat("MeshDeviation", 0.5)
        except Exception:
            dev = None
        self.graphics = {}
        for o, _t in self.times:
            try:
                self.graphics[o.Name] = feature_graphics(o, dev)
            except Exception:
                self.graphics[o.Name] = (0, 0)
        self._show_times()
        for name, rows in performance_sections(doc, self.times):
            top = QtWidgets.QTreeWidgetItem([name, ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            for row, value in rows:
                top.addChild(QtWidgets.QTreeWidgetItem([row, value]))
            self.sections.addTopLevelItem(top)
            top.setExpanded(True)
        self.sections.resizeColumnToContents(0)
        total = sum(t for _, t in self.times)
        self.summary.setText("Total rebuild time: %s s. Click a feature to select it." % _f(total, 3))


@command("SWStyle_PerformanceEvaluation", "Performance Evaluation",
         "Rebuild time of every feature, slowest first.")
def performance_evaluation():
    return _show(PerformanceWindow)


try:
    watch_open_times()
except Exception as _error:
    App.Console.PrintLog("FreeCAD: open times: %s\n" % _error)


# ------------------------------------------------------------------ Symmetry Check
SYMMETRIC, ASYMMETRIC = (0.1, 0.7, 0.2), (0.9, 0.15, 0.1)


def _plane_from_selection():
    for sel in Gui.Selection.getSelectionEx():
        obj = sel.Object
        for sub, shp in zip(sel.SubElementNames, sel.SubObjects):
            if sub.startswith("Face") and shp.Surface.__class__.__name__ == "Plane":
                return shp.CenterOfMass, shp.normalAt(0, 0), "%s.%s" % (obj.Label, sub)
        try:
            if obj.isDerivedFrom("App::Plane") or obj.isDerivedFrom("PartDesign::Plane"):
                pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
                return pl.Base, pl.Rotation.multVec(App.Vector(0, 0, 1)), obj.Label
        except Exception as _fw_err:
            _fw_log("evaluate.py:1164", _fw_err)
    return None


def symmetric_faces(shape, base, normal, tol=1e-3):
    mirrored = shape.mirror(base, normal)
    keys = [(round(f.Area, 3), f.CenterOfMass) for f in mirrored.Faces]
    out = []
    for f in shape.Faces:
        a, c = round(f.Area, 3), f.CenterOfMass
        out.append(any(abs(a - ka) <= max(tol, 1e-4 * a) and (c - kc).Length <= max(tol, 1e-4 * shape.BoundBox.DiagonalLength)
                       for ka, kc in keys))
    return out


class SymmetryWindow(ReportWindow):
    ""

    def __init__(self):
        super().__init__("Symmetry Check", ["Faces", "Count"])
        self.recalc.setText("Check")
        self.colours = FaceColours()
        self.options.addWidget(QtWidgets.QLabel("Plane:"))
        self.plane = QtWidgets.QComboBox()
        self.plane.addItems(["Right Plane (YZ)", "Front Plane (XZ)", "Top Plane (XY)", "Selected plane or face"])
        self.options.addWidget(self.plane)
        self.options.addStretch(1)
        self.plane.currentIndexChanged.connect(self.refresh)

    def compute(self):
        self.colours.restore()
        pick = _plane_from_selection()
        if pick is not None:
            self.plane.blockSignals(True)
            self.plane.setCurrentIndex(3)
            self.plane.blockSignals(False)
        i = self.plane.currentIndex()
        if i == 3 and pick is None:
            self.summary.setText("Select a plane or a planar face, then press Check.")
            return
        base, normal, name = pick if i == 3 else (App.Vector(), [App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1)][i], self.plane.currentText())
        sym = asym = 0
        for obj in visible_bodies():
            flags = symmetric_faces(obj.Shape, base, normal)
            sym += sum(flags)
            asym += len(flags) - sum(flags)
            self.colours.paint(obj, [SYMMETRIC if f else ASYMMETRIC for f in flags])
        self.set_rows([(("Symmetric faces", sym), []), (("Asymmetric faces", asym), [])])
        self.summary.setText("About %s: green faces have a mirror partner, red faces do not." % name)

    def cleanup(self):
        self.colours.restore()


@command("SWStyle_SymmetryCheck", "Symmetry Check",
         "Colours faces that are symmetric or asymmetric about a plane.")
def symmetry_check():
    return _show(SymmetryWindow)


# ------------------------------------------------------------------ Check
@command("SWStyle_Check", "Check",
         "Checks the selected bodies, or every visible body, for invalid geometry.")
def check():
    ""
    if not Gui.Selection.getSelection():
        doc = App.ActiveDocument
        for obj in visible_bodies():
            Gui.Selection.addSelection(doc.Name, obj.Name)
    Gui.runCommand("Part_CheckGeometry", 0)


# ------------------------------------------------------------------ registration
class _Cmd:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        menu, tip, _ = COMMANDS[self.name]
        return {"MenuText": menu, "ToolTip": tip, "CmdType": "ForEdit"}

    def Activated(self):
        COMMANDS[self.name][2]()

    def IsActive(self):
        return App.ActiveDocument is not None


_installed = False


def install():
    """Adds the SWStyle_* evaluate commands to FreeCAD (once)."""
    global _installed
    if _installed:
        return
    for name in COMMANDS:
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _Cmd(name))
    _installed = True
    try:
        from . import evalpm
        evalpm.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Evaluate boxes: %s\n" % error)


def close_all():
    for win in list(_OPEN.values()):
        try:
            win.close()
        except Exception as _fw_err:
            _fw_log("evaluate.py:1276", _fw_err)
