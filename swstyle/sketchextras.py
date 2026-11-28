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
from . import unitbox

from .widgets import alive, ui_font
from . import geomkeep


# ------------------------------------------------------------------ helpers
def sketch_in_edit():
    try:
        vp = Gui.ActiveDocument.getInEdit()
    except Exception:
        return None
    obj = getattr(vp, "Object", None)
    if obj is not None and obj.isDerivedFrom("Sketcher::SketchObject"):
        return obj
    return None


def picked_geo_ids(sketch):
    """Geometry indexes of the picked sketch edges ('Edge3' -> 2), in pick order."""
    out = []
    for sel in Gui.Selection.getSelectionEx():
        if sel.Object != sketch:
            continue
        for sub in sel.SubElementNames:
            if sub.startswith("Edge"):
                out.append(int(sub[4:]) - 1)
    return out


def _tell(title, text):
    QtWidgets.QMessageBox.information(Gui.getMainWindow(), title, text)


class _Form(QtWidgets.QDialog):
    """Small PropertyManager-like box: rows of label + field, OK / Cancel."""

    def __init__(self, title):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle(title)
        self.setFont(ui_font())
        self.form = QtWidgets.QFormLayout(self)
        self.fields = {}

    def add(self, key, label, widget):
        self.fields[key] = widget
        self.form.addRow(label, widget)
        return widget

    def finish(self):
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.form.addRow(buttons)


# ------------------------------------------------------------------ Segment
def segment(sketch, geo_id, count, mode="points"):
    ""

    import Part
    import Sketcher
    geo = sketch.Geometry[geo_id]
    edge = geo.toShape()
    count = max(2, int(count))
    first, last = edge.FirstParameter, edge.LastParameter
    length = edge.Length
    closed = edge.isClosed()
    params = [edge.getParameterByLength(length * k / count) for k in range(1, count)]
    if closed:
        # a circle has count pieces: count points round it, the first at its start
        params = [first] + params
    points = [edge.valueAt(p) for p in params]
    made = []
    if mode == "points":
        for p in points:
            pid = sketch.addGeometry(Part.Point(p), False)
            sketch.addConstraint(Sketcher.Constraint("PointOnObject", pid, 1, geo_id))
            made.append(pid)
        return made
    if closed:
        # Sketcher cannot split a whole circle; make it arcs between the points
        centre, radius = geo.Center, geo.Radius
        sketch.delGeometry(geo_id)
        angles = [math.atan2(p.y - centre.y, p.x - centre.x) for p in points]
        for k in range(len(angles)):
            a0 = angles[k]
            a1 = angles[(k + 1) % len(angles)]
            if a1 <= a0:
                a1 += 2 * math.pi
            made.append(sketch.addGeometry(Part.ArcOfCircle(Part.Circle(centre, App.Vector(0, 0, 1), radius), a0, a1), False))
        for k in range(len(made)):
            sketch.addConstraint(Sketcher.Constraint("Coincident", made[k], 2, made[(k + 1) % len(made)], 1))
        return made
    # open entity: split from the far end so the earlier points keep their geometry index
    ids = [geo_id]
    for p in reversed(points):
        sketch.split(geo_id, p)
    return ids


def segment_command():
    sketch = sketch_in_edit()
    if sketch is None:
        _tell("Segment", "Open a sketch, select a line, arc, circle or spline, then click Segment.")
        return
    ids = picked_geo_ids(sketch)
    if len(ids) != 1:
        from . import pickfirst
        return pickfirst.ask_in_sketch(sketch, "Segment", "Sketch Segment", segment_command, single=True)
    dlg = _Form("Segment")
    count = dlg.add("count", "Number of instances", QtWidgets.QSpinBox())
    count.setRange(2, 999)
    count.setValue(4)
    kind = dlg.add("kind", "Type", QtWidgets.QComboBox())
    kind.addItems(["Sketch points", "Sketch segments"])
    dlg.finish()
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return
    App.ActiveDocument.openTransaction("Segment")
    try:
        segment(sketch, ids[0], count.value(), "points" if kind.currentIndex() == 0 else "segments")
    except BaseException:
        try:
            App.ActiveDocument.abortTransaction()
        except Exception:
            pass
        raise
    App.ActiveDocument.commitTransaction()
    sketch.recompute()


# ------------------------------------------------------------------ Equation Driven Curve
_MATH = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
_MATH.update(abs=abs, min=min, max=max, pow=pow)


def _evaluator(text, var):
    code = compile(text.replace("^", "**"), "<equation>", "eval")
    for name in code.co_names:
        if name not in _MATH and name != var:
            raise ValueError("unknown name '%s' in %s" % (name, text))
    return lambda v: float(eval(code, {"__builtins__": {}}, dict(_MATH, **{var: v})))


def equation_points(kind, exprs, start, end, samples=60):
    """kind 'explicit': exprs = (y(x),); 'parametric': exprs = (x(t), y(t))."""
    if end <= start:
        raise ValueError("the end value must be larger than the start value")
    vals = [start + (end - start) * k / (samples - 1) for k in range(samples)]
    if kind == "explicit":
        fy = _evaluator(exprs[0], "x")
        return [App.Vector(x, fy(x), 0) for x in vals]
    fx, fy = _evaluator(exprs[0], "t"), _evaluator(exprs[1], "t")
    return [App.Vector(fx(t), fy(t), 0) for t in vals]


def add_equation_curve(sketch, kind, exprs, start, end):
    import Part
    pts = equation_points(kind, exprs, start, end)
    closed = pts[0].distanceToPoint(pts[-1]) < 1e-7
    if closed:
        pts = pts[:-1]
    curve = Part.BSplineCurve()
    curve.interpolate(pts, PeriodicFlag=closed)
    g = sketch.addGeometry(curve, False)

    try:
        import Sketcher
        sketch.addConstraint(Sketcher.Constraint("Block", g))
    except Exception as _fw_err:
        _fw_log("sketchextras.py:188", _fw_err)
    return g


def equation_curve_command():
    ""
    sketch = sketch_in_edit()
    if sketch is None:
        _tell("Equation Driven Curve", "Open a sketch first, then click Equation Driven Curve.")
        return
    from . import equationpm
    return equationpm.open_page()


# ------------------------------------------------------------------ Fit Spline
def fit_spline(sketch, geo_ids, delete=False, tolerance=0.0):
    ""

    import Part
    edges = [sketch.Geometry[i].toShape() for i in geo_ids]
    groups = Part.sortEdges(edges)
    if len(groups) != 1:
        raise ValueError("the picked entities must form one connected chain")
    wire = Part.Wire(groups[0])
    n = max(8, 12 * len(edges))
    pts = wire.discretize(Number=n)
    closed = wire.isClosed()
    if closed:
        pts = pts[:-1]
    curve = Part.BSplineCurve()
    if tolerance > 0:
        curve.approximate(Points=pts, Tolerance=tolerance)
    else:
        curve.interpolate(pts, PeriodicFlag=closed)
    for i in sorted(geo_ids, reverse=True):
        if delete:
            sketch.delGeometry(i)
        else:
            sketch.setConstruction(i, True)
    return sketch.addGeometry(curve, False)


def fit_spline_command():
    ""

    from . import fitsplinepm
    if sketch_in_edit() is None:
        _tell("Fit Spline", "Open a sketch, select the entities to fit, then click Fit Spline.")
        return
    fitsplinepm.open_page()


# ------------------------------------------------------------------ Face Curves
class FaceCurves:
    """Iso-parameter curves across a face, kept up to date with the face."""

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyLinkSub", "Face", "Face Curves", "Face the curves lie on")
        obj.addProperty("App::PropertyInteger", "Direction1", "Face Curves", "Curves in the first direction").Direction1 = 5
        obj.addProperty("App::PropertyInteger", "Direction2", "Face Curves", "Curves in the second direction").Direction2 = 5
        obj.addProperty("App::PropertyBool", "SWCurve", "Base", "A FreeCAD curve")
        obj.setEditorMode("SWCurve", 2)
        obj.SWCurve = True
        self.more(obj)

    @staticmethod
    def more(obj):
        ""
        have = obj.PropertiesList
        if "Mode" not in have:
            obj.addProperty("App::PropertyEnumeration", "Mode", "Face Curves", "Mesh: evenly across; Position: through a point")
            obj.Mode = ["Mesh", "Position"]
        if "PositionPoint" not in have:
            obj.addProperty("App::PropertyVector", "PositionPoint", "Face Curves", "The point the Position curves go through")
        if "IgnoreHoles" not in have:
            obj.addProperty("App::PropertyBool", "IgnoreHoles", "Face Curves", "The curves run across holes")

    def onDocumentRestored(self, obj):
        self.more(obj)

    def execute(self, obj):
        import Part
        link, subs = obj.Face
        if link is None or not subs:
            obj.Shape = Part.Shape()
            return
        sub = subs[0]
        try:
            face = link.Shape.getElement(sub)
        except Exception:
            face = link.Shape.getElement(sub.split(".")[-1].lstrip("?"))
        obj.Shape = face_curves(face, obj.Direction1, obj.Direction2, getattr(obj, "Mode", "Mesh"),
                                getattr(obj, "PositionPoint", None), getattr(obj, "IgnoreHoles", False))

    def dumps(self):
        return None

    def loads(self, state):
        return None


def face_curves(face, n1, n2, mode="Mesh", point=None, ignore_holes=False):
    """Iso curves across face: Mesh n1 / n2 evenly; Position one of each direction (n > 0) through
    point. ignore_holes: trimmed by the outer boundary only."""
    import Part
    u0, u1, v0, v1 = face.ParameterRange
    surf = face.Surface
    edges = []
    if mode == "Position" and point is not None:
        try:
            u, v = face.Surface.parameter(point)
        except Exception:
            u, v = (u0 + u1) / 2, (v0 + v1) / 2
        us, vs = ([u] if n1 else []), ([v] if n2 else [])
    else:
        us = [u0 + (u1 - u0) * k / (n1 + 1) for k in range(1, n1 + 1)]
        vs = [v0 + (v1 - v0) * k / (n2 + 1) for k in range(1, n2 + 1)]
    for u in us:
        edges.append(Part.Edge(surf.uIso(u), v0, v1))
    for v in vs:
        edges.append(Part.Edge(surf.vIso(v), u0, u1))
    if ignore_holes and len(face.Wires) > 1:
        try:
            face = Part.Face(face.Surface, face.OuterWire)
        except Exception as _fw_err:
            _fw_log("sketchextras.py:314", _fw_err)
    pieces = []
    for e in edges:
        try:
            # keep the part of each curve inside the face's boundary (holes, trims)
            pieces += face.common(e).Edges
        except Exception:
            pieces.append(e)
    return Part.Compound(pieces)


def face_curves_command():
    picks = [(s.Object, s.SubElementNames[0]) for s in Gui.Selection.getSelectionEx()
             if s.SubElementNames and s.SubElementNames[0].startswith("Face")]
    from . import facecurvespm
    return facecurvespm.open_panel(picks[:1])


def make_face_curves(obj, face_name, n1=5, n2=5, transaction=True):
    doc = App.ActiveDocument
    if transaction:
        doc.openTransaction("Face Curves")
    fc = doc.addObject("Part::FeaturePython", "FaceCurves")
    FaceCurves(fc)
    if App.GuiUp:
        from .curves import _CurveView
        _CurveView(fc.ViewObject)
    fc.Label = "Face Curves"
    fc.Face = (obj, [face_name])
    fc.Direction1, fc.Direction2 = n1, n2
    doc.recompute()
    if transaction:
        doc.commitTransaction()
    return fc


def face_curves_to_sketches(fc, constrain=True, samples=9):
    ""


    from . import sketch3d as K
    from . import sketch3dsolve as S3
    doc = fc.Document
    link, subs = fc.Face
    sub = subs[0] if subs else ""
    out = []
    for e in fc.Shape.Edges:
        closed = e.isClosed()
        ps = e.discretize(Number=samples + (1 if closed else 0))
        if closed:
            ps = ps[:-1]
        pts = [(p.x, p.y, p.z) for p in ps]
        idx = list(range(len(pts)))
        ents = [S3.Entity("S", idx + ([0] if closed else []))]
        rels = []
        if constrain and link is not None:
            if not closed:
                # in the face's own parameters, so all of it lies on the face (a closed curve would
                # cross the face's seam there: its points are held On Surface instead)
                rels.append(S3.Relation("SplineOnSurface", idx[:2], [], (link.Name, sub)))
            rels += [K.model_relation(doc, "OnSurface", i, link.Name, sub) for i in idx]
        sk = K.make(doc)
        K.store(sk, pts, ents, rels)
        out.append(sk)
    doc.removeObject(fc.Name)
    doc.recompute()
    return out


# ------------------------------------------------------------------ Modify Sketch
def modify_sketch(sketch, dx=0.0, dy=0.0, angle=0.0):
    """Moves and turns the whole sketch on its plane (Tools > Sketch Tools > Modify), through the
    attachment offset so relations and dimensions inside the sketch stay as they are."""
    move = App.Placement(App.Vector(dx, dy, 0), App.Rotation(App.Vector(0, 0, 1), angle))
    if sketch.MapMode != "Deactivated" and sketch.AttachmentSupport:
        sketch.AttachmentOffset = move.multiply(sketch.AttachmentOffset)
    else:
        sketch.Placement = sketch.Placement.multiply(move)
    sketch.recompute()


def turn_sketch(sketch, angle, about=(0.0, 0.0)):
    """Turns the whole sketch on its plane by angle (degrees) about a point of the sketch (Modify
    Sketch's right-drag: about the sketch origin, or the moveable origin when that is chosen)."""
    turn = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), angle), App.Vector(about[0], about[1], 0))
    if sketch.MapMode != "Deactivated" and sketch.AttachmentSupport:
        sketch.AttachmentOffset = sketch.AttachmentOffset.multiply(turn)
    else:
        sketch.Placement = sketch.Placement.multiply(turn)
    sketch.recompute()


class _ModifyDrag(QtCore.QObject):
    ""



    TYPES = (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease,
             QtCore.QEvent.ContextMenu)

    def __init__(self, box):
        super().__init__()
        self.box = box
        self.drag = None
        from .fwsketch import appevents
        appevents.listen(self, self.TYPES)

    def stop(self):
        try:
            from .fwsketch import appevents
            appevents.stop(self)
        except Exception as _fw_err:
            _fw_log("sketchextras.py:modifydrag.stop", _fw_err)
        if self.drag is not None:
            self._put_back()
        self.drag = None

    def _viewport(self):
        try:
            gdoc = Gui.ActiveDocument
            if gdoc is None or sketch_in_edit() is not self.box.sketch:
                return None
            return gdoc.ActiveView.graphicsView().viewport()
        except Exception:
            return None

    def _point(self):
        p, _px = self.drag["vm"].pointer()
        return p

    def _put_back(self):
        sk, (offset, placement) = self.box.sketch, self.drag["start"]
        sk.AttachmentOffset = offset
        sk.Placement = placement

    def _show(self, final=False):
        d = self.drag
        p = self._point()
        if p is None:
            return None
        if d["kind"] == "move":
            value = (p[0] - d["p0"][0], p[1] - d["p0"][1])
        else:
            c = d["about"]
            a0 = math.atan2(d["p0"][1] - c[1], d["p0"][0] - c[0])
            a1 = math.atan2(p[1] - c[1], p[0] - c[0])
            value = math.degrees((a1 - a0 + math.pi) % (2.0 * math.pi) - math.pi)
        self._put_back()
        if final:
            return value
        if d["kind"] == "move":
            modify_sketch(self.box.sketch, value[0], value[1], 0.0)
        else:
            turn_sketch(self.box.sketch, value, d["about"])
        return value

    def eventFilter(self, obj, event):
        try:
            return self._filter(obj, event)
        except Exception as _fw_err:
            _fw_log("sketchextras.py:modifydrag", _fw_err)
            return False

    def _filter(self, obj, event):
        box = self.box
        if not alive(box) or not box.isVisible():
            return False
        viewport = self._viewport()
        if viewport is None or obj is not viewport:
            return False
        t = event.type()
        if t == QtCore.QEvent.ContextMenu:
            return True                  # the right button turns the sketch here, no menu
        if t == QtCore.QEvent.MouseButtonPress and self.drag is None:
            button = event.button()
            if button not in (QtCore.Qt.LeftButton, QtCore.Qt.RightButton):
                return False
            from .fwsketch.toolbase import ViewMath
            vm = ViewMath()
            vm.setup_view(Gui.ActiveDocument, box.sketch)
            sk = box.sketch
            self.drag = {"vm": vm, "button": button, "kind": "move" if button == QtCore.Qt.LeftButton else "turn",
                         "start": (sk.AttachmentOffset, sk.Placement),
                         "about": (box.mx.value(), box.my.value()) if box.about_moveable.isChecked() else (0.0, 0.0)}
            self.drag["p0"] = self._point()
            if self.drag["p0"] is None:
                self.drag = None
                return False
            return True
        if self.drag is None:
            return False
        if t == QtCore.QEvent.MouseMove:
            self._show()
            return True
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == self.drag["button"]:
            value = self._show(final=True)
            kind, about = self.drag["kind"], self.drag["about"]
            self.drag = None
            if value is not None:
                box.dragged(kind, value, about)
            return True
        return True


def scale_sketch(sketch, factor, about=(0.0, 0.0)):
    ""

    if factor <= 0.0 or abs(factor - 1.0) < 1e-12:
        return
    centre = App.Vector(about[0], about[1], 0)
    geos = []
    for g in geomkeep.read(sketch):
        g = g.clone()                       # clone: the entity's Tag stays (Sketch Text, Fit Spline links)
        g.scale(centre, factor)
        geos.append(g)
    keep = list(sketch.Constraints)
    lengths = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter")
    sketch.Geometry = geos
    sketch.Constraints = keep
    for i, c in enumerate(sketch.Constraints):
        if c.Type in lengths and c.Driving:
            try:
                sketch.setDatum(i, App.Units.Quantity("%.12g mm" % (c.Value * factor)))
            except Exception as _fw_err:
                _fw_log("sketchextras.py:415", _fw_err)
    sketch.solve()
    sketch.recompute()


FLIP_KINDS = ("LineSegment", "Circle", "ArcOfCircle", "Point")


def flip_sketch(sketch, axis):
    ""



    import Part
    bad = [g for g in sketch.Geometry if type(g).__name__ not in FLIP_KINDS]
    if bad:
        raise ValueError("Flip works on lines, arcs, circles and points")
    fx, fy = (1.0, -1.0) if axis == "X" else (-1.0, 1.0)

    def m(v):
        return App.Vector(v.x * fx, v.y * fy, 0)
    geos, arcs = [], set()
    for i, g in enumerate(sketch.Geometry):
        kind = type(g).__name__
        if kind == "LineSegment":
            n = Part.LineSegment(m(g.StartPoint), m(g.EndPoint))
        elif kind == "Circle":
            n = Part.Circle(m(g.Center), App.Vector(0, 0, 1), g.Radius)
        elif kind == "ArcOfCircle":
            a, b = g.FirstParameter, g.LastParameter
            if axis == "X":
                start, end = -b, -a
            else:
                start, end = math.pi - b, math.pi - a
            n = Part.ArcOfCircle(Part.Circle(m(g.Center), App.Vector(0, 0, 1), g.Radius), start, end)
            arcs.add(i)
        else:
            n = Part.Point(m(App.Vector(g.X, g.Y, 0)))
        geos.append(n)
    cons = []
    for c in sketch.Constraints:
        c = c.clone() if hasattr(c, "clone") else c
        cons.append(c)
    swapped = []
    for c in cons:
        for attr_geo, attr_pos in (("First", "FirstPos"), ("Second", "SecondPos"), ("Third", "ThirdPos")):
            g = getattr(c, attr_geo, None)
            if g in arcs and getattr(c, attr_pos, 0) in (1, 2):
                try:
                    setattr(c, attr_pos, 3 - getattr(c, attr_pos))
                except Exception:
                    swapped.append(c)
    construction = [sketch.getConstruction(i) for i in range(len(sketch.Geometry))]
    sketch.Geometry = geos
    for i, on in enumerate(construction):
        if on:
            sketch.setConstruction(i, True)
    sketch.Constraints = cons
    flip_value = ("DistanceY",) if axis == "X" else ("DistanceX",)
    for i, c in enumerate(sketch.Constraints):
        try:
            if c.Type in flip_value and c.Driving:
                sketch.setDatum(i, App.Units.Quantity("%.12g mm" % -c.Value))
            elif c.Type == "Angle" and c.Driving and c.Second == -2000:
                sketch.setDatum(i, App.Units.Quantity("%.12g rad" % -c.Value))
        except Exception as _fw_err:
            _fw_log("sketchextras.py:481", _fw_err)
    sketch.solve()
    sketch.recompute()


def _picked_point(sketch):
    """(x, y) of the one sketch point picked, else None (Position selected point)."""
    try:
        for s in Gui.Selection.getSelectionEx(sketch.Document.Name):
            if s.Object is not sketch:
                continue
            for sub in s.SubElementNames:
                name = sub.rsplit(".", 1)[-1]
                if name.startswith("Vertex"):
                    g, pos = sketch.getGeoVertexIndex(int(name[6:]) - 1)
                    p = sketch.getPoint(g, pos)
                    return p.x, p.y
    except Exception as _fw_err:
        _fw_log("sketchextras.py:499", _fw_err)
    return None


class ModifySketchDialog(QtWidgets.QDialog):
    ""



    def __init__(self, sketch):
        super().__init__(Gui.getMainWindow())
        self.sketch = sketch
        self.setObjectName("SWModifySketch")
        self.setWindowTitle("Modify Sketch")
        self.setFont(ui_font())
        self.setModal(False)
        self.start = (sketch.AttachmentOffset, sketch.Placement, [g.clone() for g in geomkeep.read(sketch)],
                      list(sketch.Constraints))
        lay = QtWidgets.QVBoxLayout(self)
        box = QtWidgets.QGroupBox("Scale About", self)
        bl = QtWidgets.QGridLayout(box)
        self.about_origin = QtWidgets.QRadioButton("Sketch origin", box)
        self.about_origin.setObjectName("SWModifySketchOrigin")
        self.about_moveable = QtWidgets.QRadioButton("Moveable origin", box)
        self.about_moveable.setObjectName("SWModifySketchMoveable")
        self.about_origin.setChecked(True)
        bl.addWidget(self.about_origin, 0, 0)
        bl.addWidget(self.about_moveable, 0, 1)
        bl.addWidget(QtWidgets.QLabel("Factor:", box), 1, 0)
        self.factor = self._spin(box, 1.0, 1e-6, 1e6, "", "SWModifySketchFactor")
        bl.addWidget(self.factor, 1, 1)
        self.mx = self._spin(box, 0.0, -1e6, 1e6, " mm", "SWModifySketchMoveableX")
        self.my = self._spin(box, 0.0, -1e6, 1e6, " mm", "SWModifySketchMoveableY")
        bl.addWidget(QtWidgets.QLabel("Moveable origin X/Y:", box), 2, 0)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.mx)
        row.addWidget(self.my)
        bl.addLayout(row, 2, 1)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Translate", self)
        bl = QtWidgets.QGridLayout(box)
        bl.addWidget(QtWidgets.QLabel("X value:", box), 0, 0)
        self.tx = self._spin(box, 0.0, -1e6, 1e6, " mm", "SWModifySketchX")
        bl.addWidget(self.tx, 0, 1)
        bl.addWidget(QtWidgets.QLabel("Y value:", box), 1, 0)
        self.ty = self._spin(box, 0.0, -1e6, 1e6, " mm", "SWModifySketchY")
        bl.addWidget(self.ty, 1, 1)
        self.position = QtWidgets.QCheckBox("Position selected point", box)
        self.position.setObjectName("SWModifySketchPosition")
        self.position.setToolTip("Puts the picked sketch point at X, Y (pick one point first)")
        bl.addWidget(self.position, 2, 0, 1, 2)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Rotate", self)
        bl = QtWidgets.QHBoxLayout(box)
        self.rotate = self._spin(box, 0.0, -360.0, 360.0, "°", "SWModifySketchRotate")
        bl.addWidget(self.rotate)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Flip", self)
        bl = QtWidgets.QHBoxLayout(box)
        self.flip_x = QtWidgets.QPushButton("Flip X", box)
        self.flip_x.setObjectName("SWModifySketchFlipX")
        self.flip_x.setToolTip("Mirrors the sketch about its X axis")
        self.flip_y = QtWidgets.QPushButton("Flip Y", box)
        self.flip_y.setObjectName("SWModifySketchFlipY")
        self.flip_y.setToolTip("Mirrors the sketch about its Y axis")
        bl.addWidget(self.flip_x)
        bl.addWidget(self.flip_y)
        lay.addWidget(box)
        self.flip_x.clicked.connect(lambda: self._flip("X"))
        self.flip_y.clicked.connect(lambda: self._flip("Y"))
        row = QtWidgets.QHBoxLayout()
        self.restore = QtWidgets.QPushButton("Restore", self)
        self.restore.setObjectName("SWModifySketchRestore")
        self.close_button = QtWidgets.QPushButton("Close", self)
        self.close_button.setObjectName("SWModifySketchClose")
        row.addStretch(1)
        row.addWidget(self.restore)
        row.addWidget(self.close_button)
        lay.addLayout(row)
        self.about_moveable.toggled.connect(lambda on: (self.mx.setEnabled(on), self.my.setEnabled(on)))
        self.mx.setEnabled(False)
        self.my.setEnabled(False)
        self.factor.editingFinished.connect(self._scale)
        self.tx.editingFinished.connect(self._translate)
        self.ty.editingFinished.connect(self._translate)
        self.rotate.editingFinished.connect(self._rotate)
        self.restore.clicked.connect(self._restore)
        self.close_button.clicked.connect(self.close)
        self.done_scale, self.done_move, self.done_turn = 1.0, (0.0, 0.0), 0.0
        self.mouse = _ModifyDrag(self)

    def hideEvent(self, event):
        try:
            self.mouse.stop()
        except Exception as _fw_err:
            _fw_log("sketchextras.py:modify.hide", _fw_err)
        super().hideEvent(event)

    def dragged(self, kind, value, about):
        """A drag in the view moved (value dx, dy) or turned (value degrees) the sketch: one undo step,
        and the Translate or Rotate values follow."""
        if kind == "move":
            if abs(value[0]) < 1e-12 and abs(value[1]) < 1e-12:
                return
            self._step("Modify Sketch", lambda: modify_sketch(self.sketch, value[0], value[1], 0.0))
            self.done_move = (self.done_move[0] + value[0], self.done_move[1] + value[1])
            pairs = ((self.tx, self.done_move[0]), (self.ty, self.done_move[1]))
        else:
            if abs(value) < 1e-9:
                return
            self._step("Modify Sketch", lambda: turn_sketch(self.sketch, value, about))
            self.done_turn = (self.done_turn + value + 180.0) % 360.0 - 180.0
            pairs = ((self.rotate, self.done_turn),)
        for w, v in pairs:
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)

    def _spin(self, parent, value, lo, hi, suffix, name):
        b = unitbox.UnitSpinBox(parent)
        b.setRange(lo, hi)
        b.setDecimals(4)
        b.setSuffix(suffix)
        b.setValue(value)
        b.setObjectName(name)
        b.setKeyboardTracking(False)
        return b

    def _step(self, name, work):
        doc = self.sketch.Document
        doc.openTransaction(name)
        try:
            work()
            doc.commitTransaction()
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintWarning("Modify Sketch: %s\n" % error)
        doc.recompute()

    def _scale(self):
        f = self.factor.value()
        rel = f / self.done_scale
        if abs(rel - 1.0) < 1e-12:
            return
        about = (self.mx.value(), self.my.value()) if self.about_moveable.isChecked() else (0.0, 0.0)
        self._step("Modify Sketch", lambda: scale_sketch(self.sketch, rel, about))
        self.done_scale = f

    def _translate(self):
        x, y = self.tx.value(), self.ty.value()
        if self.position.isChecked():
            p = _picked_point(self.sketch)
            if p is None:
                return
            # the point goes to X, Y: through the offset, so the point's sketch coordinates stay
            dx, dy = x - p[0] - self.done_move[0], y - p[1] - self.done_move[1]
        else:
            dx, dy = x - self.done_move[0], y - self.done_move[1]
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
            return
        self._step("Modify Sketch", lambda: modify_sketch(self.sketch, dx, dy, 0.0))
        self.done_move = (self.done_move[0] + dx, self.done_move[1] + dy)

    def _rotate(self):
        a = self.rotate.value() - self.done_turn
        if abs(a) < 1e-12:
            return
        self._step("Modify Sketch", lambda: modify_sketch(self.sketch, 0.0, 0.0, a))
        self.done_turn = self.rotate.value()

    def _flip(self, axis):
        bad = [g for g in self.sketch.Geometry if type(g).__name__ not in FLIP_KINDS]
        if bad:
            Gui.getMainWindow().statusBar().showMessage("Flip works on lines, arcs, circles and points", 6000)
            return
        self._step("Modify Sketch Flip", lambda: flip_sketch(self.sketch, axis))

    def _restore(self):
        offset, placement, geos, cons = self.start

        def work():
            self.sketch.AttachmentOffset = offset
            self.sketch.Placement = placement
            self.sketch.Geometry = [g.clone() for g in geos]
            self.sketch.Constraints = list(cons)
            self.sketch.solve()
            self.sketch.recompute()
        self._step("Modify Sketch Restore", work)
        self.done_scale, self.done_move, self.done_turn = 1.0, (0.0, 0.0), 0.0
        for w, v in ((self.factor, 1.0), (self.tx, 0.0), (self.ty, 0.0), (self.rotate, 0.0)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)


_modify = None


def modify_sketch_command():
    global _modify
    sketch = sketch_in_edit()
    if sketch is None:
        picked = [s.Object for s in Gui.Selection.getSelectionEx() if s.Object.isDerivedFrom("Sketcher::SketchObject")]
        sketch = picked[0] if picked else None
    if sketch is None:
        from . import pickfirst
        return pickfirst.ask("Modify Sketch", "Sketch to modify", ("Sketch",), modify_sketch_command)
    try:
        if _modify is not None and _modify.isVisible():
            _modify.close()
    except RuntimeError as _fw_err:
        _fw_log("sketchextras.py:682", _fw_err)
    _modify = ModifySketchDialog(sketch)
    _modify.show()
    return _modify


# ------------------------------------------------------------------ Shaded Sketch Contours
def _bounded_regions(edges):
    """The areas the edges (in the sketch plane) bound: a plane past them split by the edges,
    less the piece around everything."""
    import Part
    try:
        shape = Part.makeCompound(edges)
        bb = shape.BoundBox
        if bb.XLength < 1e-9 or bb.YLength < 1e-9:
            return []
        m = max(bb.DiagonalLength * 0.1, 1.0)
        big = Part.makePlane(bb.XLength + 2 * m, bb.YLength + 2 * m, App.Vector(bb.XMin - m, bb.YMin - m, 0))
        pieces, _map = big.generalFuse(edges)
        corners = [v.Point for v in big.Vertexes]
        return [f for f in pieces.Faces
                if not any(v.Point.distanceToPoint(c) < 1e-7 for v in f.Vertexes for c in corners)]
    except Exception:
        return []


def contour_faces(sketch):
    """Faces of the sketch's closed contours (holes left open), in model coordinates."""
    import Part
    # from the geometry, not sketch.Shape: that only updates on a recompute, not while editing
    edges = [g.toShape() for i, g in enumerate(sketch.Geometry)
             if not sketch.getConstruction(i) and not isinstance(g, Part.Point)]
    wires = []
    for group in Part.sortEdges(edges) if edges else []:
        try:
            w = Part.Wire(group)
        except Exception:
            continue
        if w.isClosed():
            w.Placement = sketch.getGlobalPlacement()
            wires.append(w)

    # overlapping circles: three areas; lines that run past each other: the area they enclose)
    # Nested loops keep the hole open (Bullseye) as before; only crossing or open entities need
    # the split.
    crossing = any(wires[i].distToShape(wires[j])[0] < 1e-7
                   for i in range(len(wires)) for j in range(i + 1, len(wires)))
    loose = len(Part.sortEdges(edges)) > len(wires) if edges else False
    regions = _bounded_regions(edges) if crossing or loose else []
    if regions:
        c = Part.makeCompound(regions)
        c.Placement = sketch.getGlobalPlacement()
        return c
    if not wires:
        return Part.Shape()
    try:
        return Part.makeFace(wires, "Part::FaceMakerBullseye")
    except Exception:
        try:
            return Part.makeFace(wires, "Part::FaceMakerSimple")
        except Exception:
            return Part.Shape()


class _ShadedContours:
    """Shaded Sketch Contours: closed areas of the sketch being edited drawn filled, kept in step
    with the sketch while it is edited."""

    def __init__(self):
        self.on = False
        self.overlay = None
        self.key = None
        self.timer = None

    def _sketch_key(self, sketch):
        """From the geometry itself: sketch.Shape only changes on a recompute, so a drag or a new
        dimension left the old fill showing until then."""
        key = [sketch.Name, len(sketch.Geometry)]
        for i, g in enumerate(sketch.Geometry):
            try:
                b = g.toShape().BoundBox
                key.append((round(b.XMin, 5), round(b.YMin, 5), round(b.XMax, 5), round(b.YMax, 5),
                            sketch.getConstruction(i)))
            except Exception:
                key.append(None)
        return tuple(key)

    def draw(self):
        from .evaluate import Overlay
        sketch = sketch_in_edit()
        if self.overlay is None:
            self.overlay = Overlay()
        self.overlay.clear()
        self.key = None
        if sketch is None:
            return
        faces = contour_faces(sketch)
        if not faces.isNull():
            # lifted a hair off the sketch plane: in sketch edit FreeCAD puts the far clipping
            # plane right at the sketch, where a fill at the plane itself is clipped away
            normal = sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
            faces.translate(normal * 0.02)
            self._fill(faces)
        self.key = self._sketch_key(sketch)

    def _fill(self, faces):
        """The faces drawn light blue, pushed behind the sketch lines and not pickable."""
        from pivy import coin
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None:
            return
        sep = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
        offset = coin.SoPolygonOffset()
        offset.factor.setValue(2.0)
        offset.units.setValue(2.0)
        light = coin.SoLightModel()
        light.model.setValue(coin.SoLightModel.BASE_COLOR)     # flat tint, no headlight glare
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(0.42, 0.6, 0.9)
        mat.transparency.setValue(0.45)
        inp = coin.SoInput()
        head = "#Inventor V2.1 ascii"
        # the faces only: writeInventor adds a second block with the edges drawn black
        inp.setBuffer(head + faces.writeInventor().split(head)[1])
        node = coin.SoDB.readAll(inp)
        if node is None:
            return
        for child in (pick, offset, light, mat, node):
            sep.addChild(child)
        view.getSceneGraph().addChild(sep)
        self.overlay.nodes.append((view, sep))

    def poll(self):
        sketch = sketch_in_edit()
        key = self._sketch_key(sketch) if sketch is not None else None
        if key != self.key:
            self.draw()

    def toggle(self):
        from PySide import QtCore
        if self.on:
            self.on = False
            if self.timer is not None:
                self.timer.stop()
            if self.overlay is not None:
                self.overlay.clear()
            return
        self.on = True
        if self.timer is None:
            self.timer = QtCore.QTimer()
            self.timer.setInterval(300)
            self.timer.timeout.connect(self.poll)
        self.draw()
        self.timer.start()


SHADED = _ShadedContours()


def shading_on():
    ""

    from . import paths, relationspm
    return paths.params().GetBool(relationspm.SHADING_PARAM, True)


def shading_toggle():
    from . import paths, relationspm
    paths.params().SetBool(relationspm.SHADING_PARAM, not shading_on())
    if SHADED.on:
        SHADED.toggle()     # the old second fill, if a macro turned it on


# ------------------------------------------------------------------ Check Sketch for Feature

# contours allowed, the "Required contour type" text)
_DISJOINT = "Disjoint closed contours or nested closed contours"
_ONE_OPEN = "Single open contour"
_ONE_CLOSED = "Single closed contour"
_THIN = "Single open, single closed or disjoint closed contours"
CHECK_KINDS = {
    "Any": (False, True, True, "Any contour"),
    "Base Extrude": (True, False, True, _DISJOINT),
    "Boss Extrude": (True, False, True, _DISJOINT),
    "Cut Extrude": (True, False, True, _DISJOINT),
    "Base Revolve": (True, False, True, _DISJOINT),
    "Boss Revolve": (True, False, True, _DISJOINT),
    "Cut Revolve": (True, False, True, _DISJOINT),
    "Thin Feature": (False, True, True, _THIN),
    "Sweep Path": (False, True, False, "Single open or single closed contour"),
    "Sweep Section": (True, False, False, _ONE_CLOSED),
    "Loft Section": (True, False, False, _ONE_CLOSED),
    "Loft Guide Curve": (False, True, False, _ONE_OPEN),
    "Loft Centerline": (False, True, False, _ONE_OPEN),
    "Rib": (False, True, True, "Open or closed contours"),
    "Surface Extrude": (False, True, True, "Open or closed contours"),
    "Planar Surface": (True, False, True, _DISJOINT),
}
_OLD_KINDS = {"Base or Boss Extrude": "Boss Extrude", "Revolve": "Boss Revolve", "Thin feature": "Thin Feature",
              "Sweep profile": "Sweep Section", "Sweep path": "Sweep Path", "Loft profile": "Loft Section"}


def _wires(sketch):
    """The sketch's contours from its geometry (sketch.Shape only updates on a recompute, not
    while the sketch is edited); construction geometry and points left out."""
    import Part
    edges = [g.toShape() for i, g in enumerate(sketch.Geometry)
             if not sketch.getConstruction(i) and not isinstance(g, Part.Point)]
    wires = []
    for group in Part.sortEdges(edges) if edges else []:
        try:
            wires.append(Part.Wire(group))
        except Exception:
            wires.extend(Part.Wire([e]) for e in group)
    return edges, wires


def found_contours(sketch):
    ""
    _edges, wires = _wires(sketch)
    if not wires:
        return "None"
    closed = [w for w in wires if w.isClosed()]
    if len(wires) == 1:
        return _ONE_CLOSED if closed else _ONE_OPEN
    if len(closed) == len(wires):
        if _crossing(wires):
            return "Intersecting closed contours"
        return "Nested closed contours" if _nested(closed) else "Disjoint closed contours"
    if not closed:
        return "Multiple open contours"
    return "Open and closed contours"


def _nested(closed):
    """One closed contour inside another (a hole)."""
    import Part
    for i, a in enumerate(closed):
        try:
            face = Part.Face(a)
        except Exception:
            continue
        for j, b in enumerate(closed):
            if i != j and face.isInside(b.Vertexes[0].Point, 1e-7, True):
                return True
    return False


def _self_crossings(wire):
    """Points where a contour crosses itself (edges meeting away from their shared ends)."""
    edges = wire.Edges
    out = []
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            try:
                d, pairs, _info = edges[i].distToShape(edges[j])
            except Exception:
                continue
            if d > 1e-7:
                continue
            ends = [v.Point for v in edges[i].Vertexes] + [v.Point for v in edges[j].Vertexes]
            for p, _q in pairs:
                if all((p - e).Length > 1e-6 for e in ends):
                    out.append(p)
    return out


def _crossing(wires):
    for i in range(len(wires)):
        for j in range(i + 1, len(wires)):
            try:
                if wires[i].distToShape(wires[j])[0] < 1e-7:
                    return True
            except Exception as _fw_err:
                _fw_log("sketchextras.py:944", _fw_err)
    return False


def check_sketch(sketch, kind):
    """Problems that stop the sketch making that feature, as (text, points to show)."""
    kind = _OLD_KINDS.get(kind, kind)
    closed_needed, open_ok, many_ok, _required = CHECK_KINDS[kind]
    edges, wires = _wires(sketch)
    problems = []
    if not edges:
        return [("The sketch has no geometry.", [])]
    open_wires = [w for w in wires if not w.isClosed()]
    if closed_needed and open_wires:
        ends = []
        for w in open_wires:
            ends += [w.Vertexes[0].Point, w.Vertexes[-1].Point]
        problems.append(("The sketch has %d open contour(s); %s needs closed contours." % (len(open_wires), kind),
                         ends))
    if not open_ok and not closed_needed and open_wires:
        problems.append(("Open contours are not allowed.", []))
    if not many_ok and len(wires) > 1:
        problems.append(("The sketch has %d contours; %s takes one contour." % (len(wires), kind), []))

    for n, w in enumerate(wires):
        pts = _self_crossings(w)
        if pts:
            problems.append(("Contour %d intersects itself." % (n + 1), pts))
    # contours that cross each other (a branch or a self-intersection)
    for i in range(len(wires)):
        for j in range(i + 1, len(wires)):
            try:
                d = wires[i].distToShape(wires[j])[0]
            except Exception:
                continue
            if d < 1e-7:
                pts = [v.Point for v in wires[i].section(wires[j]).Vertexes]
                problems.append(("Contours %d and %d touch or cross." % (i + 1, j + 1), pts))
    # three or more entities meeting at one point make a branch
    ends = {}
    for e in edges:
        if e.isClosed():
            continue
        for v in (e.Vertexes[0], e.Vertexes[-1]):
            k = tuple(round(c, 6) for c in v.Point)
            ends[k] = ends.get(k, 0) + 1
    branches = [App.Vector(*k) for k, n in ends.items() if n > 2]
    if branches and kind != "Any":
        problems.append(("%d point(s) where three or more entities meet." % len(branches), branches))
    return problems


class CheckSketchDialog(QtWidgets.QDialog):
    ""



    def __init__(self, sketch):
        super().__init__(Gui.getMainWindow())
        self.setObjectName("SWCheckSketchForFeature")
        self.setWindowTitle("Check Sketch for Feature Usage")
        self.setFont(ui_font())
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.sketch = sketch
        self.marks = None
        self.problems = []
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.kind = QtWidgets.QComboBox(self)
        self.kind.setObjectName("SWCheckFeatureUsage")
        self.kind.addItems(list(CHECK_KINDS))
        self.kind.setCurrentText(App.ParamGet(_CHECK_PARAMS).GetString("FeatureUsage", "Base Extrude"))
        form.addRow("Feature usage:", self.kind)
        lay.addLayout(form)
        box = QtWidgets.QGroupBox("Contour types", self)
        f2 = QtWidgets.QFormLayout(box)
        self.required = QtWidgets.QLabel("", box)
        self.required.setObjectName("SWCheckRequired")
        self.found = QtWidgets.QLabel("", box)
        self.found.setObjectName("SWCheckFound")
        for w in (self.required, self.found):
            w.setWordWrap(True)
        f2.addRow("Required contour type:", self.required)
        f2.addRow("Found contour type:", self.found)
        lay.addWidget(box)
        row = QtWidgets.QHBoxLayout()
        self.check_btn = QtWidgets.QPushButton("Check", self)
        self.reset_btn = QtWidgets.QPushButton("Reset", self)
        self.close_btn = QtWidgets.QPushButton("Close", self)
        for b, slot in ((self.check_btn, self.check), (self.reset_btn, self.reset), (self.close_btn, self.close)):
            b.setObjectName("SWCheck" + b.text())
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        self.kind.currentTextChanged.connect(self._kind_changed)
        self._kind_changed()

    def _kind_changed(self, *args):
        kind = self.kind.currentText()
        self.required.setText(CHECK_KINDS[kind][3])
        self.found.setText("")
        self.reset()
        App.ParamGet(_CHECK_PARAMS).SetString("FeatureUsage", kind)

    def check(self, quiet=False):
        ""

        self.reset()
        try:
            self.found.setText(found_contours(self.sketch))
            self.problems = check_sketch(self.sketch, self.kind.currentText())
        except Exception as error:
            self.problems = [("Could not check the sketch: %s" % error, [])]
        points = [p for _t, pts in self.problems for p in pts]
        if points:
            self._mark(points)
        if quiet:
            return self.problems
        if not self.problems:
            _tell("Check Sketch for Feature Usage", "No problems found.")
        else:
            QtWidgets.QMessageBox.warning(self, "Check Sketch for Feature Usage",
                                          "\n".join(t for t, _p in self.problems))
        return self.problems

    def _mark(self, points):
        """Red dots on the problem points, drawn over the sketch."""
        from pivy import coin
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None:
            return
        place = self.sketch.getGlobalPlacement()
        sep = coin.SoSeparator()
        sep.setName("SWCheckSketchMarks")
        pick = coin.SoPickStyle()
        pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(1.0, 0.0, 0.0)
        style = coin.SoDrawStyle()
        style.pointSize.setValue(9)
        coords = coin.SoCoordinate3()
        pts = [place.multVec(p) for p in points]
        coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
        for n in (pick, mat, style, coords, coin.SoPointSet()):
            sep.addChild(n)
        view.getSceneGraph().addChild(sep)
        self.marks = (view, sep)

    def reset(self):
        if self.marks is not None:
            view, sep = self.marks
            try:
                view.getSceneGraph().removeChild(sep)
            except Exception as _fw_err:
                _fw_log("sketchextras.py:1099", _fw_err)
            self.marks = None
        self.problems = []

    def closeEvent(self, event):
        self.reset()
        super().closeEvent(event)


_CHECK_PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/CheckSketch"
_check_box = None


def check_sketch_command():
    global _check_box
    sketch = sketch_in_edit()
    if sketch is None:
        picked = [s.Object for s in Gui.Selection.getSelectionEx() if s.Object.isDerivedFrom("Sketcher::SketchObject")]
        sketch = picked[0] if picked else None
    if sketch is None:
        from . import pickfirst
        return pickfirst.ask("Check Sketch for Feature", "Sketch to check", ("Sketch",), check_sketch_command)
    try:
        if _check_box is not None and alive(_check_box):
            _check_box.close()
    except Exception as _fw_err:
        _fw_log("sketchextras.py:1125", _fw_err)
    _check_box = CheckSketchDialog(sketch)
    _check_box.show()
    return _check_box


# ------------------------------------------------------------------ Silhouette Entities
def _groups(edges, tol=1e-6):
    """Edges in connected groups (a shared end point joins two edges)."""
    parent = list(range(len(edges)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    ends = [[v.Point for v in e.Vertexes] for e in edges]
    for i in range(len(edges)):
        for j in range(i + 1, len(edges)):
            if any(a.distanceToPoint(b) < tol for a in ends[i] for b in ends[j]):
                parent[find(i)] = find(j)
    out = {}
    for i, e in enumerate(edges):
        out.setdefault(find(i), []).append(e)
    return list(out.values())


def _straightened(edge):
    """HLR gives a circle seen edge-on as a B-spline; a straight one becomes a line again."""
    import Part
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    if not isinstance(edge.Curve, (Part.Line, Part.LineSegment)) and not edge.isClosed() \
            and abs(edge.Length - a.distanceToPoint(b)) < 1e-7 * max(1.0, edge.Length):
        return Part.LineSegment(a, b).toShape()
    return edge


def silhouette_edges(shape, sketch, internal=False):
    """The body's outline as seen square to the sketch plane, in sketch coordinates: the outer
    boundary of each separate region, or the visible edges inside it too when internal is set."""
    import Part
    import TechDraw
    local = shape.transformed(sketch.getGlobalPlacement().inverse().toMatrix())
    # projectEx: visible sharp, smooth, seam, outline, iso, then the same five hidden
    parts = TechDraw.projectEx(local, App.Vector(0, 0, 1))

    def edges_of(indexes):
        out = []
        for i in indexes:
            comp = parts[i]
            if comp is not None and not comp.isNull():
                out += [_straightened(e) for e in comp.Edges]
        return out
    if internal:
        return edges_of((0, 1, 2, 3))
    # the outline is the boundary of everything, hidden edges included (a boss ending on a
    # side face meets the part only through edges seen edge-on): split every edge where it
    # crosses another, then take the outer wire of each connected set
    allp = edges_of((0, 1, 2, 3, 5, 6, 7, 8))
    if not allp:
        return []
    try:
        pieces = allp[0].generalFuse(allp[1:])[0].Edges if len(allp) > 1 else allp
    except Exception:
        pieces = allp
    pieces = [e for e in pieces if e.Length > 1e-7]
    faces, loose = [], []
    for group in _groups(pieces):
        try:
            wire = TechDraw.findOuterWire(group)
        except Exception:
            wire = None
        if wire is not None and wire.isClosed():
            faces.append(Part.Face(wire))
        else:
            loose += group
    if not faces:
        return loose
    merged = faces[0].fuse(faces[1:]).removeSplitter() if len(faces) > 1 else faces[0]
    out = []
    for f in merged.Faces:
        out += f.OuterWire.Edges
    return out


def _sketch_curve(edge):
    import Part
    a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
    if isinstance(edge.Curve, (Part.Line, Part.LineSegment)):
        return Part.LineSegment(App.Vector(a.x, a.y, 0), App.Vector(b.x, b.y, 0))
    if isinstance(edge.Curve, Part.Circle) and not edge.isClosed():
        mid = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
        if (mid.x - a.x) * (b.y - mid.y) - (mid.y - a.y) * (b.x - mid.x) < 0:
            a, b = b, a     # counter-clockwise, as the sketcher draws arcs: a clockwise (-Z) arc can jump on the next solve
        return Part.Arc(App.Vector(a.x, a.y, 0), App.Vector(mid.x, mid.y, 0), App.Vector(b.x, b.y, 0))
    if isinstance(edge.Curve, Part.Circle):
        c = edge.Curve.Center
        return Part.Circle(App.Vector(c.x, c.y, 0), App.Vector(0, 0, 1), edge.Curve.Radius)
    return edge.Curve.toBSpline(edge.FirstParameter, edge.LastParameter)


def silhouette(sketch, shape, internal=False):
    """Adds the outline as sketch geometry; returns the new geometry indexes."""
    return [sketch.addGeometry(_sketch_curve(e), False) for e in silhouette_edges(shape, sketch, internal)]


def _picked_bodies(sketch):
    from .evaluate import _solids_of
    bodies = []
    for sel in Gui.Selection.getSelectionEx():
        if sel.Object != sketch and _solids_of(sel.Object):
            obj = sel.Object
            for p in obj.InList:
                if p.isDerivedFrom("PartDesign::Body"):
                    obj = p
            if obj not in bodies:
                bodies.append(obj)
    return bodies


def silhouette_command():
    ""

    sketch = sketch_in_edit()
    if sketch is None:
        _tell("Silhouette Entities", "Open a sketch, select a body in the graphics area, then click Silhouette Entities.")
        return
    from . import pickfirst
    return pickfirst.ask_in_sketch(sketch, "Silhouette Entities", "Entities to Convert",
                                   lambda opts: _silhouette_run(sketch, opts), bodies=True,
                                   options=(("external", "External silhouette", True),))


def _silhouette_run(sketch, opts):
    bodies = _picked_bodies(sketch)
    if not bodies:
        return
    App.ActiveDocument.openTransaction("Silhouette Entities")
    try:
        for b in bodies:
            silhouette(sketch, b.Shape, not opts.get("external", True))
    except BaseException:
        try:
            App.ActiveDocument.abortTransaction()
        except Exception:
            pass
        raise
    App.ActiveDocument.commitTransaction()
    Gui.Selection.clearSelection()
    sketch.recompute()


# ------------------------------------------------------------------ commands
def _in_sketch():
    return sketch_in_edit() is not None


COMMANDS = {
    "SWStyle_Segment": ("Segment", "Splits a sketch entity into equal segments or adds equally spaced points on it.",
                        segment_command, _in_sketch),
    "SWStyle_EquationDrivenCurve": ("Equation Driven Curve", "Sketches a curve from an explicit or parametric equation.",
                                    equation_curve_command, _in_sketch),
    "SWStyle_FitSpline": ("Fit Spline", "Replaces a chain of sketch entities with one spline that follows them.",
                          fit_spline_command, _in_sketch),
    "SWStyle_FaceCurves": ("Face Curves", "Makes a grid of curves across a face.",
                           face_curves_command, lambda: App.ActiveDocument is not None and not _in_sketch()),
    "SWStyle_ModifySketch": ("Modify Sketch", "Scales, moves or turns the whole sketch on its plane.",
                             modify_sketch_command, lambda: App.ActiveDocument is not None),
    "SWStyle_ShadedSketchContours": ("Shaded Sketch Contours", "Fills the closed areas of the sketch being edited.",
                                     shading_toggle, _in_sketch),
    "SWStyle_SilhouetteEntities": ("Silhouette Entities", "Sketches the outline of a body as seen square to the sketch.",
                                   silhouette_command, _in_sketch),
    "SWStyle_CheckSketchForFeature": ("Check Sketch for Feature",
                                      "Says whether the sketch can make the chosen feature, and what stops it.",
                                      check_sketch_command, lambda: App.ActiveDocument is not None),
}


class _Cmd:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        menu, tip, _, _ = COMMANDS[self.name]
        res = {"MenuText": menu, "ToolTip": tip}
        if self.name != "SWStyle_FaceCurves":
            res["CmdType"] = "ForEdit"
        return res

    def Activated(self):
        COMMANDS[self.name][2]()

    def IsActive(self):
        try:
            return bool(COMMANDS[self.name][3]())
        except Exception:
            return False


_installed = False


def install():
    global _installed
    if _installed:
        return
    for name in COMMANDS:
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _Cmd(name))
    from . import checkstate
    checkstate.register("SWStyle_ShadedSketchContours", shading_on)
    try:
        from . import sketchcenterlines
        sketchcenterlines.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sketch centerlines not added: %s\n" % error)
    try:
        pass                                # parts made from layout blocks: asmtabs.follow drives them
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: block-driven parts not kept in step: %s\n" % error)
    _installed = True
