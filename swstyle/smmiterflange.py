# SPDX-License-Identifier: LGPL-2.1-or-later
""















from . import editobj

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
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, smallowance, smbaseflange, smedgegeom, smflatten, smtear
from . import smlive
from .smbaseflange import ALLOWANCES, RELIEFS, _active_body, _box, _spin
from .smedgeflange import RELIEF_TYPES, EdgePicks, _radio, _root, edge_list, error_label

COMMAND = "SWStyle_SMMiterFlange"
TITLE = "Miter Flange"
LABEL = "Miter Flange"
GROUP = "Miter Flange"

POSITIONS = (("Material Inside", "Material Inside"), ("Material Outside", "Thickness Outside"),
             ("Bend Outside", "Material Outside"))
PICK_MESSAGE = "Select a linear edge of the sheet. A sketch opens on a plane normal to the edge, at its nearer end."
NOT_PROFILE = "The miter flange profile must be one or more open lines starting at the edge."
V = App.Vector


def _engine():
    import SheetMetalCmd
    return SheetMetalCmd


# ================================================================ geometry
def _frame(shape, edge, thk):
    """At a sheet edge: n the normal of the sheet face holding it, o outward from the sheet, ends."""
    faces = [f for f in shape.ancestorsOfType(edge, Part.Face) if f.Surface.TypeId == "Part::GeomPlane"]
    if not faces:
        raise ValueError("The edge must lie on a flat face of the sheet")
    sheet = max(faces, key=lambda f: f.Area)
    n = sheet.normalAt(0, 0)
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    o = (b - a).normalize().cross(n)
    mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
    if shape.isInside(mid + o * 0.01 - n * (thk / 2), 1e-7, True):
        o = o * -1
    return n, o, (a, b)


def _profile_points(sketch, ends):
    wires = sketch.Shape.Wires
    if len(wires) != 1 or wires[0].isClosed() or any(e.Curve.TypeId != "Part::GeomLine" for e in wires[0].Edges):
        raise ValueError(NOT_PROFILE)
    pts = [v.Point for v in wires[0].OrderedVertexes]
    axis = (ends[1] - ends[0]).normalize()

    def off(p):
        q = p - ends[0]
        return (q - axis * q.dot(axis)).Length
    if off(pts[-1]) < off(pts[0]):
        pts.reverse()
    return pts


def walls(shape, edge, sketch, radius, thk, outer_first):
    """[(length, angle, length type)] for the SheetMetal wall, one per profile line.

    The profile is the face F of the flange (outside at the first bend when outer_first); its corners
    are F's virtual sharps. The first wall is measured from its bend's outer virtual sharp, the
    others by their flat length past their bend."""
    n, o, ends = _frame(shape, edge, thk)
    k = o.cross(n)
    pts = _profile_points(sketch, ends)
    lines = []
    for p, q in zip(pts, pts[1:]):
        d = q - p
        d = d - k * d.dot(k)
        if d.Length < 1e-6:
            raise ValueError(NOT_PROFILE)
        lines.append((d.Length, V(d).normalize()))
    if lines[0][1].dot(n) ** 2 < 1e-12:
        # along the sheet face either way (outward or back over the sheet): no bend to make, and the

        raise ValueError("The first profile line must leave the face of the sheet")
    a0 = math.degrees(math.atan2(lines[0][1].dot(n), lines[0][1].dot(o)))
    turns = [math.degrees(math.atan2(p[1].cross(q[1]).dot(k), p[1].dot(q[1]))) for p, q in zip(lines, lines[1:])]
    if any(abs(t) < 1e-6 or abs(abs(t) - 180.0) < 1e-6 for t in turns):
        raise ValueError(NOT_PROFILE)       # straight on, or folded back on itself (tan 90 deg)
    up = a0 > 0
    # F on the outside of each bend? A bend turning the other way swaps the sides.
    outer = [outer_first] + [outer_first if (t > 0) == up else not outer_first for t in turns]
    shift = [thk * math.tan(math.radians(abs(t)) / 2) for t in [a0] + turns]
    out = []
    for i, (length, d) in enumerate(lines):
        if i == 0:
            start = -thk / abs(d.dot(n)) if outer_first else -shift[0]
        else:
            start = (0.0 if outer[i] else -shift[i]) + (radius + thk) * math.tan(math.radians(abs(turns[i - 1])) / 2)
        end = length + (shift[i + 1] if i + 1 < len(lines) and not outer[i + 1] else 0.0)
        if end - start <= 1e-6:
            raise ValueError("A profile line is too short for its bends")
        out.append((end - start, a0 if i == 0 else -turns[i - 1], "Outer Sharp" if i == 0 else "Leg"))
    return out


class SWMiterFlange:
    def __init__(self, obj, base, edges, sketch):
        add = obj.addProperty
        add("App::PropertyLinkSub", "baseObject", GROUP, "The sheet and the edges the flange runs along")
        add("App::PropertyLink", "Profile", GROUP, "Sketch with the flange profile")
        add("App::PropertyLength", "Radius", GROUP, "Bend radius")
        add("App::PropertyEnumeration", "Position", GROUP, "Flange position")
        add("App::PropertyLength", "Gap", GROUP, "Gap distance at the mitres")
        add("App::PropertyBool", "TrimSideBends", GROUP, "Trim side bends")
        add("App::PropertyLength", "StartOffset", GROUP, "Start offset distance")
        add("App::PropertyLength", "EndOffset", GROUP, "End offset distance")
        add("App::PropertyFloat", "KFactor", GROUP, "K-Factor")
        add("App::PropertyEnumeration", "ReliefType", GROUP, "Relief type")
        add("App::PropertyBool", "UseReliefRatio", GROUP, "Use relief ratio")
        add("App::PropertyFloat", "ReliefRatio", GROUP, "Relief ratio")
        add("App::PropertyLength", "ReliefWidth", GROUP, "Relief width")
        add("App::PropertyLength", "ReliefDepth", GROUP, "Relief depth")
        obj.Position = [t for t, _v in POSITIONS]
        obj.ReliefType = ["Rectangle", "Round"]
        obj.baseObject = (base, list(edges))
        obj.Profile = sketch
        obj.Radius = 1.0
        obj.Gap = 0.25
        obj.KFactor = 0.5
        obj.UseReliefRatio = True
        obj.ReliefRatio = 0.5
        obj.ReliefWidth = 1.0
        obj.ReliefDepth = 1.0
        obj.Proxy = self

    def execute(self, obj):
        base, edges = obj.baseObject
        if base is None or not edges or obj.Profile is None:
            raise ValueError("Miter Flange: needs a profile sketch and an edge of the sheet")
        engine = _engine()
        main, kept = smedgegeom.trimmed_shape(base).copy(), smedgegeom.kept_material(base)
        if kept:        # built on the base without the side bend material it kept; that goes back after
            names = smedgegeom.remap(base.Shape, main, list(edges))
            if names is None:
                main, kept = base.Shape.copy(), []
            else:
                edges = names
        thk = engine.sheet_thk(main, edges[0])[0]
        bend_type = dict(POSITIONS)[obj.Position]
        plan = walls(main, main.getElement(edges[0]), obj.Profile, obj.Radius.Value, thk,
                     obj.Position == "Material Inside")
        face = list(edges)
        for i, (length, angle, spec) in enumerate(plan):
            s, f = engine.smBend(
                thk, bendR=obj.Radius.Value, bendA=angle, BendType=bend_type if i == 0 else "Material Inside",
                flipped=False, unfold=False, extLen=length, LengthSpec=spec,
                gap1=obj.StartOffset.Value if i == 0 else 0.0, gap2=obj.EndOffset.Value if i == 0 else 0.0,
                reliefType=obj.ReliefType, reliefW=obj.ReliefWidth.Value, reliefD=obj.ReliefDepth.Value,
                ReliefFactor=obj.ReliefRatio, UseReliefFactor=obj.UseReliefRatio, kfactor=obj.KFactor,
                automiter=True, mingap=obj.Gap.Value, selFaceNames=face, MainObject=main)
            face = engine.smGetFace(f, s)
            main = s
        base_shape = smedgegeom.trimmed_shape(base) if kept else base.Shape
        wall = main
        if getattr(obj, smedgegeom.LIVE, False) and not obj.TrimSideBends:
            lines = [base_shape.getElement(e) for e in edges if e.startswith("Edge")]
            lines = [e for e in lines if e.Curve.TypeId == "Part::GeomLine"]
            gap = smedgegeom.relief_gap(thk, obj.UseReliefRatio, obj.ReliefRatio, obj.ReliefWidth)
            main = smedgegeom.put_back_side_bends(main, base_shape, lines, gap, 3 * (obj.Radius.Value + thk) + gap)
        if getattr(obj, smedgegeom.LIVE, False):
            smedgegeom.remember_trimmed(obj, wall)
        obj.Shape = smedgegeom.with_kept(main, kept)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _icon():
    try:
        import SheetMetalTools
        return os.path.join(SheetMetalTools.icons_path, "SheetMetal_AddWall.svg")
    except Exception:
        return ""


class ViewProviderMiterFlange:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return _icon()

    def claimChildren(self):
        return [self.Object.Profile] if self.Object.Profile is not None else []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
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

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_miter_flange(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWMiterFlange"


def make(base, edges, sketch):
    doc = base.Document
    body = next((p for p in base.InList if p.TypeId == "PartDesign::Body"), None) or _active_body(doc)
    doc.openTransaction(TITLE)
    try:
        obj = doc.addObject("PartDesign::FeaturePython", "MiterFlange")
        SWMiterFlange(obj, base, edges, sketch)
        if App.GuiUp:
            ViewProviderMiterFlange(obj.ViewObject)
        if body is not None:
            body.addObject(obj)
        root = _root(base)
        if root is not None:
            if hasattr(root, "Radius"):
                obj.Radius = root.Radius.Value
            obj.KFactor = float(getattr(root, "SWKFactor", 0.5))
            if hasattr(root, "SWReliefRatio"):
                obj.UseReliefRatio = bool(root.SWUseReliefRatio)
                obj.ReliefRatio = root.SWReliefRatio
                obj.ReliefType = RELIEF_TYPES.get(root.SWAutoRelief) or "Rectangle"
        obj.Label = naming.next_label(doc, LABEL)
        smedgegeom.mark_live(obj, "TrimSideBends")
        for o in (base, sketch):
            try:
                o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("smmiterflange.py:276", _fw_err)
        doc.recompute()
        return obj
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


def _sketch_edge(sketch):
    """(sheet feature, edge) the sketch is attached normal to, else (None, None)."""
    try:
        for obj, subs in sketch.AttachmentSupport:
            if subs and subs[0].startswith("Edge") and hasattr(obj, "Shape") and not obj.TypeId.startswith("App::"):
                return obj, subs[0]
    except Exception as _fw_err:
        _fw_log("smmiterflange.py:288", _fw_err)
    return None, None


# ================================================================ PropertyManager
_LAST = None        # the open Miter Flange PropertyManager


class Panel(EdgePicks):
    """The Miter Flange PropertyManager. obj is None until an edge is known."""

    HINT = "Select the edges along which to make the miter flange."

    def __init__(self, obj, new, sketch=None):
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        self.sketch = obj.Profile if obj is not None else sketch
        base, edge = _sketch_edge(self.sketch) if obj is None else (obj.baseObject[0], None)
        if base is None:
            body = smbaseflange._body_of(self.sketch) or _active_body(self.sketch.Document)
            base = body.Tip if body is not None and body.Tip is not self.sketch else None
        self.base = base
        self.busy = True
        root = _root(base) if base is not None else None
        self.root_radius = root.Radius.Value if root is not None and hasattr(root, "Radius") else None
        self.root_k = float(getattr(root, "SWKFactor", 0.5)) if root is not None else 0.5

        params = _box("Miter Parameters")
        f = params.layout()
        f.addRow(QtWidgets.QLabel("Along Edges:"))
        self.edges = edge_list(self)
        f.addRow(self.edges)
        self.propagate = QtWidgets.QPushButton("Propagate")
        self.propagate.setObjectName("SWSMMiterPropagate")
        self.propagate.setToolTip("Adds the edges tangent to the picked ones, round the bends")
        self.propagate.clicked.connect(self.propagate_edges)
        f.addRow(self.propagate)
        self.default_radius = QtWidgets.QCheckBox("Use default radius")
        self.default_radius.setObjectName("SWSMDefaultRadius")
        radius = obj.Radius.Value if obj is not None else (self.root_radius or 1.0)
        self.radius = _spin("SWSMRadius", radius, 0.0, 10000.0)
        self.radius.setToolTip("Bend Radius")
        self.default_radius.setChecked(self.root_radius is None or abs(radius - self.root_radius) < 1e-9)
        f.addRow(self.default_radius)
        f.addRow(self.radius)
        f.addRow(QtWidgets.QLabel("Flange position:"))
        self.positions = QtWidgets.QButtonGroup(params)
        current = obj.Position if obj is not None else "Material Inside"
        for i, (text, _v) in enumerate(POSITIONS):
            b = _radio("SWSMMiterPosition" + text.replace(" ", ""), text)
            b.setChecked(text == current)
            self.positions.addButton(b, i)
            f.addRow(b)
        self.trim = QtWidgets.QCheckBox("Trim side bends")
        self.trim.setObjectName("SWSMTrimSideBends")
        self.trim.setToolTip("Removes the material of the bends beside the flange")
        self.trim.setChecked(bool(obj.TrimSideBends) if obj is not None else False)
        f.addRow(self.trim)
        self.gap = _spin("SWSMMiterGap", obj.Gap.Value if obj is not None else 0.25, 0.0, 1000.0)
        self.gap.setToolTip("Gap distance")
        f.addRow("Gap distance", self.gap)
        self.error = error_label()
        f.addRow(self.error)

        offsets = _box("Start/End Offset")
        f = offsets.layout()
        self.start_offset = _spin("SWSMMiterStartOffset", obj.StartOffset.Value if obj is not None else 0.0, 0.0, 100000.0)
        self.start_offset.setToolTip("Start offset distance")
        self.end_offset = _spin("SWSMMiterEndOffset", obj.EndOffset.Value if obj is not None else 0.0, 0.0, 100000.0)
        self.end_offset.setToolTip("End offset distance")
        f.addRow("Start", self.start_offset)
        f.addRow("End", self.end_offset)

        allowance = _box("Custom Bend Allowance")
        f = allowance.layout()
        self.custom_k = QtWidgets.QCheckBox("Custom Bend Allowance")
        self.custom_k.setObjectName("SWSMCustomAllowance")
        self.allowance = QtWidgets.QComboBox()
        self.allowance.setObjectName("SWSMAllowance")
        self.allowance.addItems(ALLOWANCES)
        k = float(obj.KFactor) if obj is not None else self.root_k
        self.custom_k.setChecked(abs(k - self.root_k) > 1e-9)
        self.kfactor = _spin("SWSMKFactor", k, 0.0, 1.0, suffix="", decimals=4, step=0.05)
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
        torn = obj is not None and smtear.is_torn(obj.ReliefWidth.Value, obj.UseReliefRatio)
        self.relief.setCurrentText("Tear" if torn else
                                   "Obround" if obj is not None and obj.ReliefType == "Round" else "Rectangular")
        self.ratio_on = QtWidgets.QCheckBox("Use relief ratio")
        self.ratio_on.setObjectName("SWSMReliefRatioOn")
        self.ratio_on.setChecked(bool(obj.UseReliefRatio) if obj is not None else True)
        self.ratio = _spin("SWSMReliefRatio", obj.ReliefRatio if obj is not None else 0.5, 0.05, 2.0, suffix="",
                           decimals=2, step=0.05)
        self.relief_w = _spin("SWSMReliefWidth", obj.ReliefWidth.Value if obj is not None else 1.0, 0.0, 1000.0)
        self.relief_w.setToolTip("Relief width")
        self.relief_d = _spin("SWSMReliefDepth", obj.ReliefDepth.Value if obj is not None else 1.0, 0.0, 1000.0)
        self.relief_d.setToolTip("Relief depth")
        f.addRow(self.custom_relief)
        f.addRow(self.relief)
        self.tear = smtear.TearRows(self.relief, f, obj, self._changed)
        f.addRow(self.ratio_on)
        f.addRow("Ratio", self.ratio)
        f.addRow("Width", self.relief_w)
        f.addRow("Depth", self.relief_d)

        params.setProperty("swstyle_pm_title", TITLE)
        params.setProperty("swstyle_pm_icon", "SheetMetal_AddWall")
        self.form = [params, offsets, allowance, relief]

        if obj is not None:
            for sub in obj.baseObject[1]:
                self.edges.addItem(sub)
        smlive.live(self)          # before _changed: using a box turns its option on first
        for w in (self.radius, self.gap, self.start_offset, self.end_offset, self.kfactor, self.ratio,
                  self.relief_w, self.relief_d):
            w.valueChanged.connect(self._changed)
        for w in (self.default_radius, self.custom_k, self.custom_relief, self.ratio_on, self.trim):
            w.toggled.connect(self._changed)
        self.positions.buttonClicked.connect(self._changed)
        self.relief.currentIndexChanged.connect(self._changed)
        self._show()
        self.busy = False
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        if obj is None and edge is not None:
            self.edges.addItem(edge)
            self._apply_edges()
        elif obj is None:
            self._report()

    def make(self, base, subs):
        return make(base, subs, self.sketch)

    def propagate_edges(self):
        ""
        if self.base is None:
            return
        subs = [self.edges.item(i).text() for i in range(self.edges.count())]
        added = [n for n in tangent_chain(self.base.Shape, subs) if n not in subs]
        for n in added:
            self.edges.addItem(n)
        if added:
            self._apply_edges()
        return added

    def _show(self):
        smlive.show(self)                  # nothing greyed: rows that don't apply hidden, the rest live

    def _changed(self, *args):
        if self.busy:
            return
        if self.default_radius.isChecked() and self.root_radius is not None:
            self.busy = True
            self.radius.setValue(self.root_radius)
            self.busy = False
        self._show()
        obj = self.obj
        if obj is None:
            return
        obj.Radius = self.radius.value()
        obj.Position = POSITIONS[max(0, self.positions.checkedId())][0]
        obj.Gap = self.gap.value()
        obj.TrimSideBends = self.trim.isChecked()
        obj.StartOffset = self.start_offset.value()
        obj.EndOffset = self.end_offset.value()
        obj.KFactor = smallowance.k_for(self, obj, 90.0) if self.custom_k.isChecked() else self.root_k
        self.custom.save(obj)
        if self.custom_relief.isChecked():
            obj.ReliefType = RELIEF_TYPES.get(self.relief.currentText()) or "Rectangle"
            obj.UseReliefRatio = self.ratio_on.isChecked()
            obj.ReliefRatio = self.ratio.value()
            obj.ReliefWidth = self.relief_w.value()
            obj.ReliefDepth = self.relief_d.value()
            self.tear.apply(obj, float(obj.Radius), smallowance.thickness_of(_root(obj.BaseFeature), obj.Document),
                            width="ReliefWidth", deep="ReliefDepth", ratio="UseReliefRatio", kind="ReliefType")
        obj.Document.recompute()
        self._report()
        smallowance.report(self)

    def reject(self):
        if self.obj is None:
            self._close()
            return True
        doc = self.obj.Document
        shown = (self.base, self.sketch) if self.new else ()
        doc.abortTransaction()
        doc.recompute()
        for o in shown:
            try:
                o.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smmiterflange.py:504", _fw_err)
        self._close()
        return True


def open_on(sketch):
    Gui.Selection.clearSelection()
    Gui.Control.showDialog(Panel(None, True, sketch=sketch))


# ================================================================ the edge pick that starts the sketch
class EdgePicker:
    """Waits for a linear edge of the sheet, then sketches on a plane normal to it at its nearer end."""

    def __init__(self, doc):
        self.doc = doc
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Message")
        self.form.setProperty("swstyle_pm_title", TITLE)
        self.form.setProperty("swstyle_pm_icon", "SheetMetal_AddWall")
        lay = QtWidgets.QVBoxLayout(self.form)
        text = QtWidgets.QLabel(PICK_MESSAGE)
        text.setWordWrap(True)
        lay.addWidget(text)
        self.error = error_label()
        lay.addWidget(self.error)
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def addSelection(self, doc, name, sub, point):
        if sub.startswith("Edge"):
            at = App.Vector(*point) if point else None
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _picked(self, doc_name, name, sub, at):
        obj = App.getDocument(doc_name).getObject(name)
        if obj is None:
            return
        edge = obj.Shape.getElement(sub)
        if edge.Curve.TypeId != "Part::GeomLine":
            self.error.setText("Select a linear edge.")
            self.error.show()
            return
        start_sketch(obj, sub, at)
        self._close()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smmiterflange.py:557", _fw_err)
        Gui.Control.closeDialog()

    def reject(self):
        self._close()
        return True


def tangent_chain(shape, subs, tol=1e-6):
    """The linear edges of shape joined to subs end to end with no kink (through bend arcs)."""
    edges = shape.Edges
    names = {e.hashCode(): "Edge%d" % i for i, e in enumerate(edges, 1)}
    seen = set(subs)
    todo = [shape.getElement(n) for n in subs]
    found = []

    def tangent(e, p):
        u = e.Curve.parameter(p)
        t = e.tangentAt(u)
        return t.normalize() if t.Length > tol else None
    while todo:
        e = todo.pop()
        for v in e.Vertexes:
            t0 = tangent(e, v.Point)
            if t0 is None:
                continue
            for o in edges:
                if o.isSame(e) or not any(w.Point.distanceToPoint(v.Point) < tol for w in o.Vertexes):
                    continue
                t1 = tangent(o, v.Point)
                if t1 is None or t0.cross(t1).Length > 1e-4:
                    continue            # a kink: not tangent
                n = names.get(o.hashCode())
                if n is None or n in seen:
                    continue
                seen.add(n)
                todo.append(o)
                if o.Curve.TypeId == "Part::GeomLine":
                    found.append(n)
    return found


def start_sketch(obj, sub, at=None):
    """A sketch normal to obj's edge sub at its end nearer at, opened for editing; the Miter Flange
    PropertyManager opens when it closes."""
    doc = obj.Document
    edge = obj.Shape.getElement(sub)
    body = next((p for p in obj.InList if p.TypeId == "PartDesign::Body"), None) or _active_body(doc)
    far = at is not None and (at - edge.Vertexes[-1].Point).Length < (at - edge.Vertexes[0].Point).Length
    sketch = body.newObject("Sketcher::SketchObject", "Sketch")
    sketch.AttachmentSupport = [(obj, sub)]
    sketch.MapMode = "NormalToEdge"
    sketch.MapPathParameter = 1.0 if far else 0.0
    doc.recompute()
    Gui.Selection.clearSelection()
    QtCore.QTimer.singleShot(0, lambda: _edit(sketch))
    return sketch


def _edit(sketch):
    Gui.ActiveDocument.setEdit(sketch.Name)
    wait = smbaseflange._wait
    wait.clear()
    wait["idle"] = 0
    wait["then"] = open_on
    QtCore.QTimer.singleShot(250, smbaseflange._watch)


def start():
    doc = App.ActiveDocument
    if doc is None:
        return
    gdoc = Gui.ActiveDocument
    edit = gdoc.getInEdit() if gdoc is not None else None
    if edit is not None and editobj.type_id(edit) == "Sketcher::SketchObject":
        sketch = editobj.of(edit)
        Gui.runCommand("Sketcher_LeaveSketch", 0)
        if sketch.Geometry:
            QtCore.QTimer.singleShot(0, lambda: open_on(sketch))
        return
    picked = Gui.Selection.getSelectionEx()
    sketches = [s.Object for s in picked if s.Object.TypeId == "Sketcher::SketchObject"]
    if len(sketches) == 1:
        open_on(sketches[0])
        return
    for s in picked:
        for sub, p in zip(s.SubElementNames, s.PickedPoints or [None] * len(s.SubElementNames)):
            if sub.startswith("Edge") and s.Object.Shape.getElement(sub).Curve.TypeId == "Part::GeomLine":
                start_sketch(s.Object, sub, p)
                return
    Gui.Control.showDialog(EdgePicker(doc))


class Command:
    def GetResources(self):
        return {"Pixmap": _icon(), "MenuText": "Miter Flange",
                "ToolTip": "Adds flanges along a chain of edges from one sketched profile, with mitred corners."}

    def IsActive(self):
        if App.ActiveDocument is None or smflatten.blocked():
            return False
        try:
            gdoc = Gui.ActiveDocument
            edit = gdoc.getInEdit() if gdoc is not None else None
            in_sketch = edit is not None and editobj.type_id(edit) == "Sketcher::SketchObject"
            return in_sketch or not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
