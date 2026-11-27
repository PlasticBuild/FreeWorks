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
import Part
from PySide import QtCore, QtGui, QtWidgets

from . import naming, paths, smallowance, smedgegeom, smflatten, smtear
from . import smlive
from .smbaseflange import ALLOWANCES, RELIEFS, _active_body, _box, _spin
from .smedgeflange import RELIEF_TYPES, EdgePicks, _radio, _root, edge_list, error_label, start as _start

COMMAND = "SWStyle_SMHem"
TITLE = "Hem"
LABEL = "Hem"

TYPES = (("Closed", "Flat", ("length",)), ("Open", "Open", ("length", "gap")),
         ("Tear Drop", "Teardrop", ("angle", "radius")), ("Rolled", "Rolled", ("angle", "radius")))
POSITIONS = (("Material Inside", "Material Inside"), ("Bend Outside", "Thickness Outside"))
# A Closed hem has no bend radius, and the engine can't cut a zero-width strip for Thickness
# Outside; Material Outside gives the same solid there.
CLOSED_OUTSIDE = "Material Outside"

# flattens, so a Closed hem is built as the engine's Open hem with this tiny gap (SWClosedHem marks it).
CLOSED_GAP = 0.01


def _type_icon(kind):
    """The hem's side view: the sheet (grey) folded back over itself as each type does (blue)."""
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(28, 28)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    try:
        from . import pmlayout
        dark = pmlayout._dark()
        blue, grey = (pmlayout.BLUE_DARK, pmlayout.GREY_DARK) if dark else (pmlayout.BLUE, pmlayout.GREY)
    except Exception:
        blue, grey = QtGui.QColor(0x2f, 0x6f, 0xc4), QtGui.QColor(0x5a, 0x5a, 0x5a)
    p.setPen(QtGui.QPen(grey, 2.2))
    p.drawLine(QtCore.QPointF(2, 20), QtCore.QPointF(18, 20))           # the sheet
    pen = QtGui.QPen(blue, 2.2)
    p.setPen(pen)
    path = QtGui.QPainterPath(QtCore.QPointF(18, 20))
    if kind == "Flat":            # Closed: flat back onto the sheet
        path.cubicTo(QtCore.QPointF(21, 20), QtCore.QPointF(21, 17.5), QtCore.QPointF(18, 17.5))
        path.lineTo(QtCore.QPointF(6, 17.5))
    elif kind == "Open":          # Open: back over the sheet with a gap
        path.cubicTo(QtCore.QPointF(24, 20), QtCore.QPointF(24, 13), QtCore.QPointF(18, 13))
        path.lineTo(QtCore.QPointF(6, 13))
    elif kind == "Teardrop":      # Tear Drop: a round loop closing onto the sheet
        path.cubicTo(QtCore.QPointF(27, 20), QtCore.QPointF(27, 6), QtCore.QPointF(18, 8))
        path.cubicTo(QtCore.QPointF(14, 9), QtCore.QPointF(12, 16), QtCore.QPointF(8, 18.5))
    else:                         # Rolled: an open curl
        path.cubicTo(QtCore.QPointF(26, 20), QtCore.QPointF(26, 8), QtCore.QPointF(19, 8))
        path.cubicTo(QtCore.QPointF(15, 8), QtCore.QPointF(14, 12), QtCore.QPointF(15, 14))
    p.drawPath(path)
    p.end()
    return QtGui.QIcon(pix)


def set_kind(obj, kind, gap=None):
    ""
    if "SWClosedHem" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "SWClosedHem", "Sheet Metal", "Closed hem")
        obj.setEditorMode("SWClosedHem", 2)
    closed = kind == "Flat"
    obj.SWClosedHem = closed
    obj.HemType = "Open" if closed else kind
    obj.opened = closed or kind == "Open"
    if closed:
        obj.opening = CLOSED_GAP
    elif gap is not None:
        obj.opening = gap


def kind_of(obj):
    """The TYPES value of a hem ("Flat" for a Closed one, old or new)."""
    closed = getattr(obj, "SWClosedHem", False) and obj.HemType == "Open" and abs(obj.opening.Value - CLOSED_GAP) < 1e-9
    return "Flat" if closed else obj.HemType


# A hem folded to the inside at a corner runs into the flange beside it; the engine fuses the two and the part

# sheet thickness on the engine's own end gaps (gap1/gap2, not shown in the PM); SWHemEndClear holds what was
# added so the user's gaps stay as set.
END_CLEAR = "SWHemEndClear"


def _ends_in(obj):
    """The hem's edge ends that stop in the plane of another flange's face (an open corner where the flange
    beside it starts): the hem's end face then lies on that flange's face and the part does not unfold."""
    try:
        base = obj.baseObject[0].Shape
        if base.isNull():
            return []
        t = smedgegeom.thickness(obj) or 1.0
    except Exception as _fw_err:
        _fw_log("smhem.py:ends", _fw_err)
        return []
    hits = []
    for sub in obj.baseObject[1]:
        try:
            edge = base.getElement(sub)
        except Exception:
            continue
        if edge.Curve.TypeId != "Part::GeomLine":
            continue
        a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        d = b - a
        if d.Length < 2 * t:
            continue
        d.normalize()
        sides = [f for f in base.ancestorsOfType(edge, Part.Face) if f.Surface.TypeId == "Part::GeomPlane"]
        if not sides:
            continue
        wall = max(sides, key=lambda f: f.Area)          # the wall's sheet face: its normal is the thickness way
        nt = wall.normalAt(*wall.Surface.parameter(edge.CenterOfMass))
        w = nt.cross(d)
        for v in (a, b):
            for f in base.Faces:
                if f.Surface.TypeId != "Part::GeomPlane":
                    continue
                n = f.Surface.Axis
                if abs(abs(n.dot(d)) - 1.0) > 1e-7 or abs((f.Surface.Position - v).dot(d)) > 1e-6:
                    continue
                across = [(p.Point - v).dot(nt) for p in f.Vertexes]
                along = [(p.Point - v).dot(w) for p in f.Vertexes]       # up the wall from the edge
                level = min(along) < t + 1e-4 and max(along) > -(t + 1e-4)
                if level and (min(across) < -(t + 1e-4) or max(across) > 1e-4):
                    hits.append(v)
                    break
    return hits


def clear_ends(obj):
    """Stops a hem one thickness short at each end that runs into a flange beside it (see END_CLEAR)."""
    if not is_hem(obj) or not hasattr(obj, "gap1"):
        return False
    if END_CLEAR not in obj.PropertiesList:
        obj.addProperty("App::PropertyFloatList", END_CLEAR, "Sheet Metal", "End gaps added where the hem meets a flange")
        obj.setEditorMode(END_CLEAR, 2)
    added = list(getattr(obj, END_CLEAR, []) or []) + [0.0, 0.0]
    g1, g2 = obj.gap1.Value - added[0], obj.gap2.Value - added[1]
    t = smedgegeom.thickness(obj) or 1.0

    def build(c1, c2):
        obj.gap1, obj.gap2 = g1 + c1, g2 + c2
        setattr(obj, END_CLEAR, [c1, c2])
        obj.recompute()

    hits = _ends_in(obj)
    edge = None
    try:
        edge = obj.baseObject[0].Shape.getElement(obj.baseObject[1][0])
    except Exception as _fw_err:
        _fw_log("smhem.py:clear", _fw_err)
    want = [0.0, 0.0]
    ends = []
    if edge is not None and len(obj.baseObject[1]) == 1:
        a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        for q in hits:
            i = 0 if (q - a).Length < (q - b).Length else 1
            want[i] = t
            ends.append((q, (b - a) if i == 0 else (a - b)))
    elif hits:
        want = [t, t]                   # several edges: both ends of the set
    if want == added[:2]:
        return False
    build(want[0], want[1])
    if ends and not _short_of(obj, ends, t):
        build(want[1], want[0])         # the engine's Left/Right the other way round on this edge
        if not _short_of(obj, ends, t):
            build(want[0], want[1])
    return _done(obj)


def _short_of(obj, ends, t):
    """True when the hem's own material stops at least a thickness short of each (end, inward) given."""
    try:
        extra = obj.Shape.cut(obj.baseObject[0].Shape)
        pts = [p.Point for p in extra.Vertexes]
    except Exception as _fw_err:
        _fw_log("smhem.py:short", _fw_err)
        return True
    if not pts:
        return True
    for v, inward in ends:
        inward = App.Vector(inward)
        inward.normalize()
        if min((p - v).dot(inward) for p in pts) < t - 1e-4:
            return False
    return True


def _done(obj):
    obj.Document.recompute()
    return True


def _engine():
    import SheetMetalHem
    return SheetMetalHem


def is_hem(obj):
    proxy = getattr(obj, "Proxy", None)
    return proxy is not None and type(proxy).__name__ == "SMHem"


def make(base, edges):
    doc = base.Document
    engine = _engine()
    body = next((p for p in base.InList if p.TypeId == "PartDesign::Body"), None) or _active_body(doc)
    doc.openTransaction(TITLE)
    try:
        obj = doc.addObject("PartDesign::FeaturePython", "Hem")
        engine.SMHem(obj, base, list(edges))
        if App.GuiUp:
            engine.SMViewProviderFlat(obj.ViewObject)
        if body is not None:
            body.addObject(obj)
        root = _root(base)
        if root is not None and hasattr(root, "SWReliefRatio"):
            obj.UseReliefFactor = bool(root.SWUseReliefRatio)
            obj.ReliefFactor = root.SWReliefRatio
            obj.reliefType = RELIEF_TYPES.get(root.SWAutoRelief) or "Rectangle"
        set_kind(obj, "Flat")
        obj.BendType = "Material Inside"
        obj.Label = naming.next_label(doc, LABEL)
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smhem.py:132", _fw_err)
        doc.recompute()
        clear_ends(obj)
        return obj
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


class Panel(EdgePicks):
    """The Hem PropertyManager. obj is None until the first edge is picked."""

    make = staticmethod(make)
    HINT = "Please select the edges to put a hem on."

    def __init__(self, obj, new, base=None):
        self.obj = obj
        self.new = new
        self.base = obj.baseObject[0] if obj is not None else base
        self.busy = True
        root = _root(self.base) if self.base is not None else None

        edges = _box("Edges")
        f = edges.layout()
        self.edges = edge_list(self)
        self.invert = QtWidgets.QCheckBox("Reverse Direction")
        from . import pmvalues
        self.invert.setIcon(pmvalues.reverse_icon())
        self.invert.setObjectName("SWSMHemReverse")
        self.invert.setChecked(bool(obj.invert) if obj else False)
        f.addRow(self.edges)
        self.width_button = QtWidgets.QPushButton("Edit Hem Width")
        self.width_button.setObjectName("SWSMEditHemWidth")
        self.width_button.setToolTip("Set how much of the edge the hem covers, in a sketch on the edge (one edge)")
        self.width_button.clicked.connect(self.edit_width)
        f.addRow(self.width_button)
        f.addRow(self.invert)
        self.positions = QtWidgets.QButtonGroup(edges)
        current = obj.BendType if obj else "Material Inside"
        current = "Thickness Outside" if current == CLOSED_OUTSIDE else current
        from . import pmpics
        prow = QtWidgets.QHBoxLayout()
        for i, (text, value) in enumerate(POSITIONS):
            b = pmpics.button("SWSMHemPosition" + text.replace(" ", ""), "flange_position", text)
            b.setChecked(value == current)
            self.positions.addButton(b, i)
            prow.addWidget(b)
        prow.addStretch(1)
        f.addRow(prow)
        if self.positions.checkedButton() is None:
            self.positions.button(0).setChecked(True)

        size = _box("Type and Size")
        f = size.layout()
        self.types = QtWidgets.QButtonGroup(size)
        current = kind_of(obj) if obj else "Open"
        row = QtWidgets.QGridLayout()      # two by two, as the Fillet types (the panel is narrow)
        for i, (text, value, _uses) in enumerate(TYPES):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWSMHemType" + text.replace(" ", ""))
            b.setToolTip(text)
            b.setIcon(_type_icon(value))
            b.setIconSize(QtCore.QSize(28, 28))
            b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setChecked(value == current)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self.types.addButton(b, i)
            row.addWidget(b, i // 2, i % 2)
        if self.types.checkedButton() is None:
            self.types.button(0).setChecked(True)
        f.addRow(row)
        self.length = _spin("SWSMHemLength", obj.width.Value if obj else 10.0, 0.01, 10000.0)
        self.length.setToolTip("Length")
        self.gap = _spin("SWSMHemGap", obj.opening.Value if obj and not getattr(obj, "SWClosedHem", False) else 1.0, 0.0, 1000.0)
        self.gap.setToolTip("Gap distance")
        self.angle = _spin("SWSMHemAngle", obj.RollAngle.Value if obj else 225.0, 1.0, 359.0, suffix=" deg")
        self.angle.setToolTip("Angle")
        radius = obj.radius.Value if obj else (root.Radius.Value if root is not None and hasattr(root, "Radius") else 1.0)
        self.radius = _spin("SWSMHemRadius", radius, 0.0, 10000.0)
        self.radius.setToolTip("Radius")
        self.rows = {}
        for key, label, w in (("length", "Length", self.length), ("gap", "Gap", self.gap),
                              ("angle", "Angle", self.angle), ("radius", "Radius", self.radius)):
            text = QtWidgets.QLabel(label)
            f.addRow(text, w)
            self.rows[key] = (text, w)

        miter = _box("Miter Gap")
        self.miter = _spin("SWSMHemMiterGap", obj.minGap.Value if obj else 0.2, 0.0, 1000.0)
        self.miter.setToolTip("Gap where hems meet")
        miter.layout().addRow(self.miter)

        allowance = _box("Custom Bend Allowance")
        f = allowance.layout()
        self.custom_k = QtWidgets.QCheckBox("Custom Bend Allowance")
        self.custom_k.setObjectName("SWSMCustomAllowance")
        self.allowance = QtWidgets.QComboBox()
        self.allowance.setObjectName("SWSMAllowance")
        self.allowance.addItems(ALLOWANCES)
        self.root_k = getattr(root, "SWKFactor", 0.5) if root is not None else 0.5
        k = None
        if obj is not None:
            try:
                k = float(obj.kfactor)
            except Exception:
                k = None
        self.custom_k.setChecked(k is not None and k >= 0 and abs(k - self.root_k) > 1e-9)
        self.kfactor = _spin("SWSMKFactor", k if k is not None and k >= 0 else self.root_k, 0.0, 1.0,
                             suffix="", decimals=4, step=0.05)
        f.addRow(self.custom_k)
        f.addRow(self.allowance)
        f.addRow("K", self.kfactor)
        self.custom = smallowance.CustomAllowance(self.allowance, self.kfactor, f, obj, self._changed)
        self.custom_k.setChecked(self.custom_k.isChecked() or self.custom.kind() != "K-Factor")

        relief = _box("Custom Relief Type")
        f = relief.layout()
        self.custom_relief = QtWidgets.QCheckBox("Custom Relief Type")
        self.custom_relief.setObjectName("SWSMCustomRelief")
        self.relief = QtWidgets.QComboBox()
        self.relief.setObjectName("SWSMRelief")
        self.relief.addItems(RELIEFS)
        torn = obj is not None and smtear.is_torn(obj.reliefw.Value, obj.UseReliefFactor)
        self.relief.setCurrentText("Tear" if torn else
                                   "Obround" if obj is not None and obj.reliefType == "Round" else "Rectangular")
        self.ratio_on = QtWidgets.QCheckBox("Use relief ratio")
        self.ratio_on.setObjectName("SWSMReliefRatioOn")
        self.ratio_on.setChecked(bool(obj.UseReliefFactor) if obj else True)
        self.ratio = _spin("SWSMReliefRatio", obj.ReliefFactor if obj else 0.5, 0.05, 2.0, suffix="", decimals=2, step=0.05)
        f.addRow(self.custom_relief)
        f.addRow(self.relief)
        self.tear = smtear.TearRows(self.relief, f, obj, self._changed)
        f.addRow(self.ratio_on)
        f.addRow("Ratio", self.ratio)

        self.error = error_label()
        edges.layout().addRow(self.error)
        edges.setProperty("swstyle_pm_title", TITLE)
        edges.setProperty("swstyle_pm_icon", "SheetMetal_AddHem")
        self.form = [edges, size, miter, allowance, relief]
        if obj is not None:
            for sub in obj.baseObject[1]:
                self.edges.addItem(sub)
        smlive.live(self)          # before _changed: using a box turns its option on first
        for w in (self.length, self.gap, self.angle, self.radius, self.miter, self.kfactor, self.ratio):
            w.valueChanged.connect(self._changed)
        for w in (self.invert, self.custom_k, self.custom_relief, self.ratio_on):
            w.toggled.connect(self._changed)
        self.positions.buttonClicked.connect(self._changed)
        self.types.buttonClicked.connect(self._changed)
        self.relief.currentIndexChanged.connect(self._changed)
        self._show()
        self.busy = False
        if obj is None:
            self._report()      # the hint: which edge to pick
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _type(self):
        return TYPES[max(0, self.types.checkedId())]

    def _show(self):
        self.width_button.setVisible(self.obj is not None and self.edges.count() == 1)
        uses = self._type()[2]
        for key, (text, w) in self.rows.items():
            text.setVisible(key in uses)
            w.setVisible(key in uses)
        smlive.show(self)                  # nothing greyed: rows that don't apply hidden, the rest live

    def _changed(self, *args):
        if self.busy:
            return
        self._show()
        obj = self.obj
        if obj is None:
            return
        text, kind, _uses = self._type()
        obj.width = self.length.value()
        set_kind(obj, kind, self.gap.value())
        obj.RollAngle = self.angle.value()
        obj.radius = self.radius.value()
        obj.invert = self.invert.isChecked()
        position = POSITIONS[max(0, self.positions.checkedId())][1]
        obj.BendType = CLOSED_OUTSIDE if kind == "Flat" and position == "Thickness Outside" else position
        obj.minGap = self.miter.value()
        try:
            obj.kfactor = smallowance.k_for(self, obj, 180.0) if self.custom_k.isChecked() else self.root_k
            self.custom.save(obj)
        except Exception as _fw_err:
            _fw_log("smhem.py:322", _fw_err)
        if self.custom_relief.isChecked():
            obj.reliefType = RELIEF_TYPES.get(self.relief.currentText()) or "Rectangle"
            obj.UseReliefFactor = self.ratio_on.isChecked()
            obj.ReliefFactor = self.ratio.value()
            self.tear.apply(obj, float(obj.radius), smedgegeom.thickness(obj))
        obj.Document.recompute()
        clear_ends(obj)
        self._report()
        smallowance.report(self)


    def edit_width(self):
        ""

        obj = self.obj
        if obj is None or self.edges.count() != 1:
            return
        sk = width_sketch(obj, create=True)
        if sk is None:
            self.pick_error = "The hem width needs a straight edge on a flat face."
            self._report()
            return
        if not self.accept():
            return
        try:
            sk.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("smhem.py:349", _fw_err)
        Gui.ActiveDocument.setEdit(sk.Name)


# ---------------------------------------------------------------- Edit Hem Width
def _edge_frame(obj):
    """(placement, length): x along the hem's edge from its start, z out of the face the edge bounds."""
    base, subs = obj.baseObject[0], list(obj.baseObject[1])
    if len(subs) != 1:
        return None
    shape = base.Shape
    edge = shape.getElement(subs[0])
    if edge.Curve.TypeId != "Part::GeomLine":
        return None
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    x = b - a
    if x.Length < 1e-9:
        return None
    x.normalize()
    faces = [f for f in shape.ancestorsOfType(edge, Part.Face) if f.Surface.TypeId == "Part::GeomPlane"]
    if not faces:
        return None
    face = max(faces, key=lambda f: f.Area)
    z = face.normalAt(*face.Surface.parameter(face.CenterOfMass))
    y = z.cross(x)
    rot = App.Rotation(x, y, z, "ZXY")
    return App.Placement(a, rot), (b - a).Length


def width_sketch(obj, create=False):
    sk = getattr(obj, "SWHemWidth", None)
    if sk is not None or not create:
        return sk
    framed = _edge_frame(obj)
    if framed is None:
        return None
    pl, length = framed
    import Sketcher
    doc = obj.Document
    if "SWHemWidth" not in obj.PropertiesList:
        obj.addProperty("App::PropertyLink", "SWHemWidth", "FreeCAD", "Edit Hem Width sketch: the stretch of the edge the hem covers")
    sk = doc.addObject("Sketcher::SketchObject", "Sketch")
    body = next((p for p in obj.InList if p.TypeId == "PartDesign::Body"), None)
    if body is not None:
        body.insertObject(sk, obj, False)
    sk.MapMode = "Deactivated"
    sk.Placement = pl
    sk.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(length, 0, 0)))
    sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
    sk.addConstraint(Sketcher.Constraint("PointOnObject", 0, 1, -1))
    sk.Label = naming.next_label(doc, "Sketch")
    try:
        sk.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("smhem.py:403", _fw_err)
    obj.SWHemWidth = sk
    doc.recompute()
    return sk


def limit_width(obj, shape):
    """The hem cut down to the Edit Hem Width line: the base part plus the hem's material between the
    line's two ends (planes square to the edge)."""
    sk = getattr(obj, "SWHemWidth", None)
    framed = _edge_frame(obj) if sk is not None else None
    if framed is None:
        return shape
    pl, length = framed
    lines = [e for e in sk.Shape.Edges]
    if not lines:
        return shape
    inv = pl.inverse()
    xs = [inv.multVec(v.Point).x for e in lines for v in e.Vertexes]
    x0, x1 = max(min(xs), -1e6), min(max(xs), 1e6)
    if x1 - x0 < 1e-6 or (x0 <= 1e-6 and x1 >= length - 1e-6):
        return shape
    base = obj.baseObject[0].Shape
    big = 10 * (shape.BoundBox.DiagonalLength + 1)
    slab = Part.makeBox(x1 - x0, 2 * big, 2 * big, App.Vector(x0, -big, -big))
    slab.Placement = pl.multiply(slab.Placement)
    extra = shape.cut(base)
    kept = extra.common(slab)
    out = base.fuse(kept) if kept.Solids else base
    try:
        out = out.removeSplitter()
    except Exception as _fw_err:
        _fw_log("smhem.py:435", _fw_err)
    solids = out.Solids
    return solids[0] if len(solids) == 1 else out


def start():
    _start(Panel)


class Command:
    def GetResources(self):
        try:
            import SheetMetalTools, os
            pixmap = os.path.join(SheetMetalTools.icons_path, "SheetMetal_AddHem.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Hem", "ToolTip": "Folds an edge back on itself."}

    def IsActive(self):
        if App.ActiveDocument is None or smflatten.blocked():
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        start()


_patched = {}


def _patch_execute():
    cls = _engine().SMHem
    if "execute" in _patched:
        return
    _patched["execute"] = cls.execute

    def execute(self, fp, original=_patched["execute"]):
        original(self, fp)
        if getattr(fp, "SWHemWidth", None) is not None:
            try:
                fp.Shape = limit_width(fp, fp.Shape)
            except Exception as e:
                App.Console.PrintWarning("FreeCAD: Edit Hem Width: %s\n" % e)
    cls.execute = execute


def register():
    _patch_execute()
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
    view = _engine().SMViewProviderTree
    if "setEdit" not in _patched:
        _patched["setEdit"] = view.setEdit

        def setEdit(self, vobj, mode=0, original=_patched["setEdit"]):
            obj = vobj.Object
            if mode != 0 or not is_hem(obj) or not paths.params().GetBool("Enabled", True):
                return original(self, vobj, mode)
            obj.Document.openTransaction("Edit " + TITLE)
            try:
                Gui.Control.showDialog(Panel(obj, False))
            except BaseException:
                try:
                    obj.Document.abortTransaction()
                except Exception:
                    pass
                raise
            return True
        view.setEdit = setEdit
