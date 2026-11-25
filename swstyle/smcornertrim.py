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

import json

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, smflatten
from . import pmboxes
from .smbaseflange import _box, _spin

COMMAND = "SWStyle_SMCornerTrim"
TITLE = "Corner Trim"
LABEL = "Corner-Trim"
GROUP = "Corner Trim"
RELIEFS = ("Circular", "Square", "Bend Waist")
BREAKS = ("Chamfer", "Fillet")
V = App.Vector
TOL = 1e-6


# ================================================================ geometry
def flat_normal(shape):
    faces = [f for f in shape.Faces if f.Surface.TypeId == "Part::GeomPlane"]
    f = max(faces, key=lambda f: f.Area)
    return f.normalAt(0, 0).normalize(), f


def thickness_edges(shape, n=None):
    """[(index, edge)] of the edges straight through the thickness."""
    n = n or flat_normal(shape)[0]
    out = []
    for i, e in enumerate(shape.Edges, 1):
        if e.Curve.TypeId != "Part::GeomLine":
            continue
        d = e.Vertexes[-1].Point - e.Vertexes[0].Point
        if d.Length > TOL and abs(abs(d.normalize().dot(n)) - 1) < 1e-7:
            out.append((i, e))
    return out


def _section(shape, n):
    """The flat pattern's outline as a face at mid thickness."""
    bb = shape.BoundBox
    pts = [V(x, y, z) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)]
    ds = [p.dot(n) for p in pts]
    mid = (min(ds) + max(ds)) / 2
    wires = shape.slice(n, mid)
    return Part.makeFace(wires, "Part::FaceMakerBullseye"), mid


def _project(p, n, mid):
    return p + n * (mid - p.dot(n))


def corner_kind(shape, edge, n=None, section=None):
    """'outside' (convex), 'inside' (concave) or None for a thickness edge that is not a sharp corner."""
    n = n or flat_normal(shape)[0]
    face, mid = section or _section(shape, n)
    c = _project(edge.Vertexes[0].Point, n, mid)
    dirs = []
    for e in face.Edges:
        for k, v in ((0, e.Vertexes[0]), (1, e.Vertexes[-1])):
            if (v.Point - c).Length < 1e-5:
                if e.Curve.TypeId != "Part::GeomLine":
                    return None
                other = e.Vertexes[-1 if k == 0 else 0].Point
                dirs.append((other - c).normalize())
    if len(dirs) != 2 or abs(dirs[0].dot(dirs[1])) > 1 - 1e-9:
        return None
    probe = c + (dirs[0] + dirs[1]).normalize() * 1e-3
    return "outside" if face.isInside(probe, 1e-9, True) else "inside"


def bend_lines(fp):
    lines = getattr(fp, "BendLines", None)
    if lines is None or lines.Shape.isNull():
        return []
    return [e for e in lines.Shape.Edges if e.Curve.TypeId == "Part::GeomLine"]


def _line_dist(p, e, n):
    a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
    d = (b - a).normalize()
    w = p - a
    w = w - n * w.dot(n)
    return (w - d * w.dot(d)).Length


def _near_bends(p, lines, n, reach):
    return sorted((l for l in lines if _line_dist(p, l, n) <= reach), key=lambda l: _line_dist(p, l, n))


def bend_crossing(p, lines, n, reach):
    """Where the two bend lines nearest the corner p cross (in the plane), or None."""
    near = _near_bends(p, lines, n, reach)
    for i in range(len(near)):
        for j in range(i + 1, len(near)):
            a0, a1 = near[i].Vertexes[0].Point, near[i].Vertexes[-1].Point
            b0, b1 = near[j].Vertexes[0].Point, near[j].Vertexes[-1].Point
            da, db = (a1 - a0).normalize(), (b1 - b0).normalize()
            cross = da.cross(db)
            if cross.Length < 1e-6:
                continue
            # a0 + s da = b0 + t db, solved in the plane
            w = b0 - a0
            s = w.cross(db).dot(cross) / cross.dot(cross)
            x = a0 + da * s
            return x - n * (x - p).dot(n), da, db
    return None


def collect(shape, fp, mode, internal_only=False):
    """Corner points for Collect all corners: 'relief' takes the inside corners next to bends, 'break'
    every sharp corner (only inside ones with internal_only)."""
    n, _f = flat_normal(shape)
    section = _section(shape, n)
    lines = bend_lines(fp)
    t = _thick(shape, n)
    out = []
    for _i, e in thickness_edges(shape, n):
        kind = corner_kind(shape, e, n, section)
        if kind is None:
            continue
        p = (e.Vertexes[0].Point + e.Vertexes[-1].Point) * 0.5
        if mode == "relief":
            if kind == "inside" and len(_near_bends(p, lines, n, 4 * t + 10)) >= 2:
                out.append(p)
        elif kind == "inside" or not internal_only:
            out.append(p)
    return out


def _thick(shape, n):
    ds = [v.Point.dot(n) for v in shape.Vertexes]
    return max(ds) - min(ds)


def edge_at(shape, point, n=None):
    """The thickness edge through point."""
    best, best_d = None, None
    for _i, e in thickness_edges(shape, n):
        d = e.distToShape(Part.Vertex(point))[0]
        if best_d is None or d < best_d:
            best, best_d = e, d
    return best if best_d is not None and best_d < 1e-4 else None


def _prism(face2d, base_level, n, height):
    return face2d.extrude(n * height)


def relief_tool(p, n, t, kind, size, centre, axes, fillet=0.0):
    """The solid cut out for one relief: a cylinder (Circular) or a square prism (Square, its corners rounded
    by fillet) through the sheet."""
    lo = min(v for v in (p.dot(n),)) - t - 1
    base = centre - n * (centre.dot(n) - lo)
    h = 3 * t + 2
    if kind == "Circular":
        return Part.makeCylinder(size, h, base, n)
    u, v = axes
    half = size / 2
    corners = [base + u * a + v * b for a, b in ((-half, -half), (half, -half), (half, half), (-half, half))]
    face = Part.Face(Part.makePolygon(corners + corners[:1]))
    r = min(fillet, half * 0.999)
    if r > 1e-6:
        face = Part.Face(face.makeOffset2D(-r, 0).makeOffset2D(r, 0).OuterWire)
    return face.extrude(n * h)


def bend_reach(p, n, where, da, db):
    """How far the corner p is from the two bend lines crossing at where: half the bend's width, as the
    corner sits on the edge of the bend."""
    w = p - where
    w = w - n * w.dot(n)
    return max((w - d * w.dot(d)).Length for d in (da, db))


def waist_tool(p, n, t, width, where, da, db):
    """Bend Waist: a slot as wide as width along each bend line, from the crossing past the corner p."""
    lo = p.dot(n) - t - 1
    h = 3 * t + 2
    out = None
    for d in (da, db):
        d = d if (p - where).dot(d) >= 0 else d * -1
        m = n.cross(d).normalize() * (width / 2)
        length = (p - where).dot(d) + width
        a = where - n * (where.dot(n) - lo) - d * (width / 2)
        b = a + d * (length + width / 2)
        slot = Part.Face(Part.makePolygon([a + m, b + m, b - m, a - m, a + m])).extrude(n * h)
        out = slot if out is None else out.fuse(slot)
    return out


def _more_props(obj):
    """Tangent to bend and Add fillet corners (older trims had them greyed)."""
    for name, kind, tip, default in (
            ("TangentToBend", "App::PropertyBool", "Tangent to bend", False),
            ("AddFilletCorners", "App::PropertyBool", "Add fillet corners (Square)", False),
            ("FilletRadius", "App::PropertyLength", "Fillet radius of the square relief's corners", 0.5)):
        if name not in obj.PropertiesList:
            obj.addProperty(kind, name, GROUP, tip)
            setattr(obj, name, default)


def apply(trim, shape, fp):
    """The flat pattern shape with one Corner Trim's reliefs and broken corners."""
    _more_props(trim)
    n, _f = flat_normal(shape)
    t = _thick(shape, n)
    lines = bend_lines(fp)
    if trim.Relief:
        tools, centres = [], []
        size = float(trim.RatioToThickness) * t if trim.UseRatio else float(trim.ReliefSize)
        for p in _points(trim.ReliefCorners):
            this = size
            crossing = bend_crossing(p, lines, n, 4 * t + 10)
            if crossing is not None:
                where, da, db = crossing
                centre = where if trim.CenteredOnBendLines else p
                axes = (da, db)
                if trim.TangentToBend and trim.ReliefType != "Bend Waist":
                    reach = bend_reach(p, n, where, da, db)
                    this = reach if trim.ReliefType == "Circular" else 2 * reach
            else:
                where, centre, axes = None, p, _plane_axes(n)
            if trim.ReliefType != "Bend Waist" and any((centre - c).Length < 1e-6 for c in centres):
                continue        # corners around the same bend crossing share one relief (a waist is per corner)
            centres.append(centre)
            if trim.ReliefType == "Bend Waist":
                if where is None:
                    raise ValueError("Bend Waist needs two bend lines crossing at the corner")
                tools.append(waist_tool(p, n, t, this, where, da, db))
            else:
                tools.append(relief_tool(p, n, t, trim.ReliefType, this, centre, axes,
                                         float(trim.FilletRadius) if trim.AddFilletCorners else 0.0))
        if tools:
            shape = shape.cut(Part.makeCompound(tools) if len(tools) > 1 else tools[0])
            shape = _clean(shape)
    if trim.Break:
        edges = [edge_at(shape, p, n) for p in _points(trim.BreakCorners)]
        edges = [e for e in edges if e is not None]
        if edges:
            d = float(trim.BreakSize)
            shape = shape.makeChamfer(d, edges) if trim.BreakType == "Chamfer" else shape.makeFillet(d, edges)
            shape = _clean(shape)
    return shape


def _plane_axes(n):
    u = V(1, 0, 0) if abs(n.x) < 0.9 else V(0, 1, 0)
    u = (u - n * u.dot(n)).normalize()
    return u, n.cross(u)


def _clean(shape):
    try:
        shape = shape.removeSplitter()
    except Exception as _fw_err:
        _fw_log("smcornertrim.py:289", _fw_err)
    solids = shape.Solids
    return solids[0] if len(solids) == 1 else shape


def _points(text):
    try:
        return [V(*p) for p in json.loads(text or "[]")]
    except Exception as _fw_err:
        _fw_log("smcornertrim.py:299", _fw_err)
        return []


def _dump(points):
    return json.dumps([[round(p.x, 6), round(p.y, 6), round(p.z, 6)] for p in points])


# ================================================================ feature
class CornerTrim:
    def __init__(self, obj, fp):
        add = obj.addProperty
        add("App::PropertyLink", "FlatPattern", GROUP, "The flat pattern it trims")
        add("App::PropertyBool", "Relief", GROUP, "Relief Options")
        add("App::PropertyString", "ReliefCorners", GROUP, "Relief corners (points, JSON)")
        add("App::PropertyEnumeration", "ReliefType", GROUP, "Relief Type")
        obj.ReliefType = list(RELIEFS)
        add("App::PropertyBool", "CenteredOnBendLines", GROUP, "Centered on bend lines")
        add("App::PropertyLength", "ReliefSize", GROUP, "Radius (Circular) or side length (Square)")
        add("App::PropertyBool", "UseRatio", GROUP, "Ratio to thickness")
        add("App::PropertyFloat", "RatioToThickness", GROUP, "Ratio to thickness")
        add("App::PropertyBool", "Break", GROUP, "Break Corner Options")
        add("App::PropertyString", "BreakCorners", GROUP, "Break corners (points, JSON)")
        add("App::PropertyEnumeration", "BreakType", GROUP, "Break type")
        obj.BreakType = list(BREAKS)
        add("App::PropertyLength", "BreakSize", GROUP, "Distance (Chamfer) or radius (Fillet)")
        add("App::PropertyBool", "InternalOnly", GROUP, "Internal corners only")
        for name in ("ReliefCorners", "BreakCorners"):
            obj.setEditorMode(name, 2)
        obj.FlatPattern = fp
        obj.Relief, obj.CenteredOnBendLines = True, True
        obj.ReliefSize, obj.UseRatio, obj.RatioToThickness = 1.0, False, 0.5
        obj.BreakSize = 1.0
        _more_props(obj)
        obj.Proxy = self

    def execute(self, obj):
        pass        # the Flat-Pattern applies it (apply_all)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderCornerTrim:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        try:
            import os
            import SheetMetalTools
            return os.path.join(SheetMetalTools.icons_path, "SheetMetal_AddRelief.svg")
        except Exception:
            return ""

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        if not vobj.Object.FlatPattern.SWFlattened:
            return False
        vobj.Object.Document.openTransaction("Edit " + TITLE)
        try:
            Gui.Control.showDialog(Panel(vobj.Object, False))
        except BaseException:
            try:
                vobj.Object.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def onDelete(self, vobj, subelements):
        fp = vobj.Object.FlatPattern
        if fp is not None:
            QtCore.QTimer.singleShot(0, lambda: (fp.touch(), fp.Document.recompute()))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_corner_trim(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "CornerTrim"


def trims(fp):
    from . import smbendnotch
    return [o for o in fp.Document.Objects if (is_corner_trim(o) or smbendnotch.is_bend_notch(o))
            and o.FlatPattern is fp]


def apply_all(fp, shape):
    """The flat pattern shape with its Corner Trims, in tree order."""
    for trim in trims(fp):
        try:
            if is_corner_trim(trim):
                shape = apply(trim, shape, fp)
            else:
                from . import smbendnotch
                shape = smbendnotch.apply(trim, shape, fp)
        except Exception as e:
            App.Console.PrintWarning("%s: %s\n" % (trim.Label, e))
    return shape


def make(fp):
    doc = fp.Document
    obj = doc.addObject("App::FeaturePython", "CornerTrim")
    CornerTrim(obj, fp)
    if App.GuiUp:
        ViewProviderCornerTrim(obj.ViewObject)
    obj.Label = naming.next_label(doc, LABEL)
    return obj


# ================================================================ PropertyManager
_LAST = None


class Panel:
    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj, self.new, self.busy = obj, new, True
        self.fp = obj.FlatPattern
        self.base_shape = None
        relief = _box("Relief Options")
        f = relief.layout()
        self.relief_on = QtWidgets.QCheckBox("Relief Options")
        self.relief_on.setObjectName("SWSMTrimRelief")
        self.relief_list = QtWidgets.QListWidget()
        self.relief_list.setObjectName("SWSMTrimReliefCorners")
        self.relief_list.setToolTip("Corner edges")
        self.relief_list.setMaximumHeight(80)
        pmboxes.mark(self.relief_list, True)
        self.relief_collect = QtWidgets.QPushButton("Collect all corners")
        self.relief_collect.setObjectName("SWSMTrimReliefCollect")
        self.relief_type = QtWidgets.QComboBox()
        self.relief_type.setObjectName("SWSMTrimReliefType")
        self.relief_type.addItems(list(RELIEFS))
        self.centred = QtWidgets.QCheckBox("Centered on bend lines")
        self.centred.setObjectName("SWSMTrimCentered")
        self.size = _spin("SWSMTrimReliefSize", float(obj.ReliefSize), 0.01, 10000.0)
        self.size_label = QtWidgets.QLabel("Radius")
        self.ratio_on = QtWidgets.QCheckBox("Ratio to thickness")
        self.ratio_on.setObjectName("SWSMTrimRatioOn")
        self.ratio = _spin("SWSMTrimRatio", float(obj.RatioToThickness), 0.01, 100.0, suffix="", decimals=2, step=0.1)
        self.tangent = QtWidgets.QCheckBox("Tangent to bend")
        self.tangent.setObjectName("SWSMTrimTangent")
        self.fillets = QtWidgets.QCheckBox("Add fillet corners")
        self.fillets.setObjectName("SWSMTrimFillets")
        _more_props(obj)
        self.fillet_r = _spin("SWSMTrimFilletRadius", float(obj.FilletRadius), 0.01, 1000.0)
        self.fillet_r.setToolTip("Fillet radius")
        self.fillet_label = QtWidgets.QLabel("Fillet radius")
        f.addRow(self.relief_on)
        f.addRow(self.relief_list)
        f.addRow(self.relief_collect)
        f.addRow("Relief Type:", self.relief_type)
        f.addRow(self.centred)
        f.addRow(self.size_label, self.size)
        f.addRow(self.ratio_on)
        f.addRow(self.ratio)
        f.addRow(self.tangent)
        f.addRow(self.fillets)
        f.addRow(self.fillet_label, self.fillet_r)

        brk = _box("Break Corner Options")
        f = brk.layout()
        self.break_on = QtWidgets.QCheckBox("Break Corner Options")
        self.break_on.setObjectName("SWSMTrimBreak")
        self.break_list = QtWidgets.QListWidget()
        self.break_list.setObjectName("SWSMTrimBreakCorners")
        self.break_list.setToolTip("Corner edges")
        self.break_list.setMaximumHeight(80)
        self.break_list.setStyleSheet("QListWidget { background: #ffd6ec; }")
        self.break_collect = QtWidgets.QPushButton("Collect all corners")
        self.break_collect.setObjectName("SWSMTrimBreakCollect")
        row = self.break_row = QtWidgets.QWidget()
        hl = QtWidgets.QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(QtWidgets.QLabel("Break type:"))
        self.break_buttons = []
        for k, name in enumerate(BREAKS):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWSMTrimBreak%s" % name)
            b.setText(name)
            b.setToolTip(name)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.clicked.connect(self._changed)
            self.break_buttons.append(b)
            hl.addWidget(b)
        hl.addStretch(1)
        self.break_size = _spin("SWSMTrimBreakSize", float(obj.BreakSize), 0.01, 10000.0)
        self.break_label = QtWidgets.QLabel("D")
        self.internal = QtWidgets.QCheckBox("Internal corners only")
        self.internal.setObjectName("SWSMTrimInternal")
        f.addRow(self.break_on)
        f.addRow(self.break_list)
        f.addRow(self.break_collect)
        f.addRow(row)
        f.addRow(self.break_label, self.break_size)
        f.addRow(self.internal)

        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("SWSMError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        from . import pickprompt
        pickprompt.style(self.error)     # look audit AI1: the start prompt in the yellow box
        self.error.hide()
        relief.layout().insertRow(0, self.error)
        relief.setProperty("swstyle_pm_title", TITLE)
        relief.setProperty("swstyle_pm_icon", "SheetMetal_AddRelief")
        self.form = [relief, brk]

        self.relief_on.setChecked(bool(obj.Relief))
        self.relief_type.setCurrentText(obj.ReliefType)
        self.centred.setChecked(bool(obj.CenteredOnBendLines))
        self.ratio_on.setChecked(bool(obj.UseRatio))
        self.tangent.setChecked(bool(obj.TangentToBend))
        self.fillets.setChecked(bool(obj.AddFilletCorners))
        self.break_on.setChecked(bool(obj.Break))
        self.break_buttons[BREAKS.index(obj.BreakType)].setChecked(True)
        self.internal.setChecked(bool(obj.InternalOnly))
        self.active = self.relief_list
        for w in (self.relief_list, self.break_list):
            w.installEventFilter(self._keys())
        self._fill()
        for w in (self.relief_on, self.centred, self.ratio_on, self.break_on, self.internal, self.tangent,
                  self.fillets):
            w.toggled.connect(self._changed)
        self.relief_type.currentIndexChanged.connect(self._changed)
        for w in (self.size, self.ratio, self.break_size, self.fillet_r):
            w.valueChanged.connect(self._changed)
        self.relief_collect.clicked.connect(lambda: self.collect("relief"))
        self.break_collect.clicked.connect(lambda: self.collect("break"))
        self.busy = False
        self._show()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # -------------------------------------------------------------- helpers
    def _keys(self):
        panel = self

        class Keys(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if event.type() == QtCore.QEvent.FocusIn:
                    panel.active = watched
                if event.type() == QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Delete,
                                                                               QtCore.Qt.Key_Backspace):
                    panel.remove_current(watched)
                    return True
                return False
        self._filters = getattr(self, "_filters", [])
        self._filters.append(Keys())
        return self._filters[-1]

    def _untrimmed(self):
        """The flat pattern without this trim (and the ones after it): what corners are picked on."""
        fp = self.fp
        shape = getattr(fp.Proxy, "untrimmed", None)
        return shape if shape is not None else fp.Shape

    def _prop(self, w):
        return "ReliefCorners" if w is self.relief_list else "BreakCorners"

    def _fill(self):
        for w in (self.relief_list, self.break_list):
            w.clear()
            for k, p in enumerate(_points(getattr(self.obj, self._prop(w))), 1):
                w.addItem("Corner %d (%.2f, %.2f, %.2f)" % (k, p.x, p.y, p.z))

    def _show(self):
        kind = self.relief_type.currentText()
        circ = kind == "Circular"
        label = {"Circular": "Radius", "Square": "Side length", "Bend Waist": "Width"}[kind]
        self.size_label.setText(label)
        self.size.setToolTip("Relief " + label.lower())
        self.size.setEnabled(not self.ratio_on.isChecked())
        self.ratio.setEnabled(self.ratio_on.isChecked())
        on = self.relief_on.isChecked()
        for w in (self.relief_list, self.relief_collect, self.relief_type, self.centred, self.size, self.ratio_on,
                  self.ratio, self.size_label):
            w.setVisible(on)
        self.centred.setVisible(on and kind != "Bend Waist")
        self.tangent.setVisible(on and kind != "Bend Waist")
        self.fillets.setVisible(on and kind == "Square")
        for w in (self.fillet_r, self.fillet_label):
            w.setVisible(on and kind == "Square" and self.fillets.isChecked())
        self.tangent.setEnabled(True)
        self.fillets.setEnabled(not circ)
        fillet = self.break_buttons[1].isChecked()
        self.break_label.setText("R" if fillet else "D")
        self.break_size.setToolTip("Radius" if fillet else "Distance")
        for w in (self.break_list, self.break_collect, self.break_size, self.break_label, self.internal):
            w.setVisible(self.break_on.isChecked())
        self.break_row.setVisible(self.break_on.isChecked())

    def _changed(self, *args):
        if self.busy:
            return
        o = self.obj
        o.Relief = self.relief_on.isChecked()
        o.ReliefType = self.relief_type.currentText()
        o.CenteredOnBendLines = self.centred.isChecked()
        o.ReliefSize = self.size.value()
        o.UseRatio = self.ratio_on.isChecked()
        o.RatioToThickness = self.ratio.value()
        o.TangentToBend = self.tangent.isChecked()
        o.AddFilletCorners = self.fillets.isChecked()
        o.FilletRadius = self.fillet_r.value()
        o.Break = self.break_on.isChecked()
        o.BreakType = BREAKS[1] if self.break_buttons[1].isChecked() else BREAKS[0]
        o.BreakSize = self.break_size.value()
        o.InternalOnly = self.internal.isChecked()
        self._show()
        self._apply()

    def _apply(self):
        self.fp.touch()
        self.fp.Document.recompute()
        self._report()

    def _report(self):
        text = ""
        if "Invalid" in self.fp.State:
            text = "The corner trim cannot be made: %s" % self.fp.getStatusString()
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text

    def collect(self, mode):
        shape = self._untrimmed()
        pts = collect(shape, self.fp, mode, self.internal.isChecked())
        setattr(self.obj, "ReliefCorners" if mode == "relief" else "BreakCorners", _dump(pts))
        self._fill()
        self._apply()

    def remove_current(self, w):
        row = w.currentRow()
        prop = self._prop(w)
        pts = _points(getattr(self.obj, prop))
        if 0 <= row < len(pts):
            del pts[row]
            setattr(self.obj, prop, _dump(pts))
            self._fill()
            self._apply()

    def addSelection(self, doc, name, sub, point):
        QtCore.QTimer.singleShot(0, lambda: self.picked(name, sub))

    def picked(self, name, sub):
        """A pick on the flat pattern: a thickness edge, or a face/vertex next to one, goes in the active list."""
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smcornertrim.py:671", _fw_err)
        if name != self.fp.Name or not sub:
            return
        shape = self.fp.Shape
        el = shape.getElement(sub)
        n, _f = flat_normal(shape)
        if sub.startswith("Edge"):
            e = el
        else:
            p = el.Point if sub.startswith("Vertex") else el.CenterOfMass
            cand = thickness_edges(shape, n)
            e = min((c for _i, c in cand), key=lambda c: c.distToShape(Part.Vertex(p))[0], default=None)
        if e is None:
            return
        d = e.Vertexes[-1].Point - e.Vertexes[0].Point
        if d.Length < TOL or abs(abs(d.normalize().dot(n)) - 1) > 1e-7:
            return
        p = (e.Vertexes[0].Point + e.Vertexes[-1].Point) * 0.5
        prop = self._prop(self.active)
        pts = _points(getattr(self.obj, prop))
        same = [k for k, q in enumerate(pts) if (q - p).Length < 1e-4]
        if same:
            del pts[same[0]]
        else:
            pts.append(p)
        setattr(self.obj, prop, _dump(pts))
        self._fill()
        self._apply()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smcornertrim.py:707", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smcornertrim.py:713", _fw_err)

    def accept(self):
        o = self.obj
        if not ((o.Relief and _points(o.ReliefCorners)) or (o.Break and _points(o.BreakCorners))):
            self.error.setText("Select corner edges, or Collect all corners.")
            self.error.setVisible(True)
            return False
        if not self._report():
            return False
        o.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        try:
            App.closeActiveTransaction(True)
        except Exception as _fw_err:
            _fw_log("smcornertrim.py:733", _fw_err)
        self.fp.touch()
        doc.recompute()
        self._close()
        return True


# ================================================================ command
class Command:
    def GetResources(self):
        return {"Pixmap": "SheetMetal_AddRelief", "MenuText": "Corner Trim",
                "ToolTip": "Adds reliefs and broken corners to the flat pattern (the part must be flattened)."}

    def IsActive(self):
        if not smflatten.is_flat():
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        body = smflatten._body()
        fp = smflatten.flat_pattern(body)
        doc = fp.Document
        doc.openTransaction(TITLE)
        try:
            obj = make(fp)
            picked = [(s.ObjectName, n) for s in Gui.Selection.getSelectionEx() for n in s.SubElementNames]
            panel = Panel(obj, True)
            Gui.Control.showDialog(panel)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        for name, sub in picked:
            panel.picked(name, sub)


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
