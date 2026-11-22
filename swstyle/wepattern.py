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
import Part

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

GROUP = "FreeCAD"


def direction_of(obj, sub):
    """(point, unit direction) of a straight edge, an axis, or a round edge / face (its centre and axis)."""
    try:
        s = obj.getSubObject(sub) if sub else None
    except Exception:
        s = None
    if s is None or s.isNull():
        if obj.TypeId in ("App::Line", "PartDesign::Line"):
            pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
            # an origin axis (App::Line) runs along its local X, a datum axis along its local Z
            local = App.Vector(1, 0, 0) if obj.TypeId == "App::Line" else App.Vector(0, 0, 1)
            return pl.Base, pl.Rotation.multVec(local).normalize()
        edges = getattr(getattr(obj, "Shape", None), "Edges", [])
        s = edges[0] if len(edges) == 1 else None
    if s is None:
        return None
    if isinstance(s, Part.Edge):
        c = s.Curve
        if isinstance(c, (Part.Line, Part.LineSegment)):
            a, b = s.Vertexes[0].Point, s.Vertexes[-1].Point
            return a, (b - a).normalize()
        if isinstance(c, (Part.Circle, Part.ArcOfCircle)) or hasattr(c, "Axis"):
            return c.Center, App.Vector(c.Axis).normalize()
    if isinstance(s, Part.Face) and s.Surface.TypeId in ("Part::GeomCylinder", "Part::GeomCone"):
        return s.Surface.Center, App.Vector(s.Surface.Axis).normalize()
    return None


class PatternCopy:
    """One instance of a patterned body: its source's shape moved by Move."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "WeldPatternSource", GROUP, "The body this repeats")
        obj.addProperty("App::PropertyPlacement", "Move", GROUP, "Where this instance goes")
        obj.Proxy = self

    def execute(self, obj):
        src = obj.WeldPatternSource
        if src is None or src.Shape.isNull():
            obj.Shape = Part.Shape()
            return
        s = src.Shape.copy()
        s.Placement = obj.Move.multiply(s.Placement)
        obj.Shape = Part.makeCompound([s])        # (a feature puts its own Placement on a shape it is given)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def moves(kind, ref, count, value, equal=False, reverse=False):
    """The placements of instances 2..count. Linear: value = spacing; circular: value = angle (total when
    equal spacing, else between instances)."""
    p, d = ref
    if reverse:
        d = -d
    out = []
    for k in range(1, max(1, int(count))):
        if kind == "linear":
            out.append(App.Placement(d * (value * k), App.Rotation()))
        else:
            step = (value / count if abs(value - 360.0) < 1e-9 else value / max(1, count - 1)) if equal else value
            rot = App.Rotation(d, step * k)
            out.append(App.Placement(p - rot.multVec(p), rot))
    return out


def pattern_bodies(doc, kind, ref, bodies, count, value, equal=False, reverse=False):
    made = []
    for m in moves(kind, ref, count, value, equal, reverse):
        for b in bodies:
            o = doc.addObject("Part::FeaturePython", "BodyPattern")
            PatternCopy(o)
            o.WeldPatternSource = b
            o.Move = m
            o.Label = "%s-%s" % ("LPattern" if kind == "linear" else "CirPattern", b.Label)
            if App.GuiUp:
                try:
                    o.ViewObject.Proxy = 0
                    o.ViewObject.ShapeColor = b.ViewObject.ShapeColor
                except Exception as _fw_err:
                    _fw_log("wepattern.py:116", _fw_err)
            made.append(o)
    doc.recompute()
    try:
        from . import wecutlist
        wecutlist.update(doc)
    except Exception as _fw_err:
        _fw_log("wepattern.py:123", _fw_err)
    return made


class BodiesPatternPanel:
    TITLES = {"linear": "Linear Pattern", "circular": "Circular Pattern"}

    def __init__(self, doc, kind, picks=()):
        self.doc, self.kind = doc, kind
        self.ref = None
        self.bodies = []
        title = self.TITLES[kind]
        d = QtWidgets.QWidget()
        d.setWindowTitle("Direction 1")
        d.setProperty("swstyle_pm_title", title)
        d.setProperty("swstyle_pm_icon", "FEATURES_LINEAR_PATTERN" if kind == "linear" else "FEATURES_CIRCULAR_PATTERN")
        lay = QtWidgets.QVBoxLayout(d)
        self.ref_list = QtWidgets.QListWidget(d)
        self.ref_list.setObjectName("SWBodyPatternDirection")
        self.ref_list.setMaximumHeight(28)
        self.ref_list.setToolTip("Pattern Direction" if kind == "linear" else "Pattern Axis")
        lay.addWidget(self.ref_list)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        self.reverse.setObjectName("SWBodyPatternReverse")
        lay.addWidget(self.reverse)
        if kind == "circular":
            self.equal = QtWidgets.QCheckBox("Equal spacing")
            self.equal.setObjectName("SWBodyPatternEqual")
            self.equal.setChecked(True)
            lay.addWidget(self.equal)
        self.value = QtWidgets.QDoubleSpinBox(d)
        self.value.setObjectName("SWBodyPatternSpacing" if kind == "linear" else "SWBodyPatternAngle")
        self.value.setDecimals(3)
        self.value.setRange(0.001, 1e6 if kind == "linear" else 360.0)
        self.value.setValue(10.0 if kind == "linear" else 360.0)
        self.value.setSuffix(" mm" if kind == "linear" else " °")
        lay.addWidget(self.value)
        self.count = QtWidgets.QSpinBox(d)
        self.count.setObjectName("SWBodyPatternInstances")
        self.count.setRange(1, 10000)
        self.count.setValue(2 if kind == "linear" else 4)
        self.count.setToolTip("Number of Instances")
        lay.addWidget(self.count)
        b = QtWidgets.QWidget()
        b.setWindowTitle("Bodies")
        bl = QtWidgets.QVBoxLayout(b)
        self.body_list = QtWidgets.QListWidget(b)
        self.body_list.setObjectName("SWBodyPatternBodies")
        self.body_list.setMaximumHeight(90)
        self.body_list.setToolTip("Solid/Surface Bodies to Pattern")
        bl.addWidget(self.body_list)
        self.form = [d, b]
        for p in picks:
            obj, sub = (p[0], p[1]) if isinstance(p, (tuple, list)) else (p, "")
            self._take(obj, sub)
        Gui.Selection.addObserver(self)
        for ms in (300, 900, 1500, 2100):      # the Bodies group starts folded on feature pages
            QtCore.QTimer.singleShot(ms, self._unfold)

    def _unfold(self):
        try:
            from . import pmlayout
            w = self.body_list
            while w is not None and not w.inherits("QSint::ActionGroup"):
                w = w.parentWidget()
            if w is not None and not pmlayout._group_open(w):
                pmlayout._show_hide(w)
        except Exception as _fw_err:
            _fw_log("wepattern.py:191", _fw_err)

    def _take(self, obj, sub):
        if obj is None:
            return
        if self.ref is None and direction_of(obj, sub) is not None and (sub or not obj.Shape.Solids):
            self.ref = (obj, sub)
            self.ref_list.clear()
            self.ref_list.addItem("%s%s" % (obj.Label, ("@" + sub) if sub else ""))
            return
        if hasattr(obj, "Shape") and obj.Shape.Solids and not sub and obj not in self.bodies:
            self.bodies.append(obj)
            self.body_list.addItem(obj.Label)

    def addSelection(self, doc, name, sub, _pos):
        if doc == self.doc.Name:
            self._take(self.doc.getObject(name), sub)

    def _done(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("wepattern.py:213", _fw_err)

    def accept(self):
        if self.ref is None or not self.bodies:
            App.Console.PrintWarning("%s: pick the direction and the bodies to pattern\n" % self.TITLES[self.kind])
            return False
        self._done()
        title = self.TITLES[self.kind]
        self.doc.openTransaction(title)
        try:
            pattern_bodies(self.doc, self.kind, direction_of(*self.ref), self.bodies, self.count.value(),
                           self.value.value(), getattr(self, "equal", None) is not None and self.equal.isChecked(),
                           self.reverse.isChecked())
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._done()
        Gui.Control.closeDialog()
        return True


def open_panel(doc, kind, picks=()):
    QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(BodiesPatternPanel(doc, kind, picks)))
