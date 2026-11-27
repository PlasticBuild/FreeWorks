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

from . import pickguard
from . import refplane, pmboxes

V = App.Vector
BLUE = "QListWidget { background: #cfe3ff; }"
WHITE = "QListWidget { background: white; }"
BODILESS = {"PartDesign::Point": "Part::DatumPoint", "PartDesign::CoordinateSystem": "Part::LocalCoordinateSystem",
            "PartDesign::Plane": "Part::DatumPlane", "PartDesign::Line": "Part::DatumLine"}


# --------------------------------------------------------------------------- picks
def _dpr():
    try:
        from PySide import QtWidgets as _Q
        return float(_Q.QApplication.instance().devicePixelRatio() or 1.0)
    except Exception:
        return 1.0


def element_kind(obj, sub):
    """'point', 'line', 'circle', 'curve', 'plane', 'face', 'sketch' or None."""
    try:
        if not sub:
            if obj.isDerivedFrom("Sketcher::SketchObject"):
                return "sketch"
            if obj.TypeId in ("PartDesign::Point", "Part::DatumPoint") or obj.isDerivedFrom("App::Point"):
                return "point"
            if obj.TypeId in ("PartDesign::Line", "Part::DatumLine") or obj.isDerivedFrom("App::Line"):
                return "line"
            if obj.TypeId in ("PartDesign::Plane", "Part::DatumPlane") or obj.isDerivedFrom("App::Plane"):
                return "plane"
            if obj.TypeId in ("PartDesign::CoordinateSystem", "App::LocalCoordinateSystem", "App::Origin"):
                return "csys"
        s = refplane.shape_of(obj, sub)
    except Exception:
        return None
    if s is None or s.isNull():
        return None
    if s.ShapeType == "Vertex":
        return "point"
    if s.ShapeType == "Edge":
        name = type(s.Curve).__name__
        if name in ("Line", "LineSegment"):
            return "line"
        if name in ("Circle", "ArcOfCircle", "Ellipse"):
            return "circle"
        return "curve"
    if s.ShapeType == "Face":
        return "plane" if type(s.Surface).__name__ == "Plane" else "face"
    return None


def label(obj, sub):
    return "%s@%s" % (sub, obj.Label) if sub else obj.Label


def holder(doc):
    """The active body (or the assembly's holder), else None: the datum goes in the document."""
    try:
        return refplane.body_of(doc)
    except Exception:
        return None


def new_datum(doc, body, kind, name):
    if body is not None:
        return body.newObject(kind, name)
    return doc.addObject(BODILESS.get(kind, kind), name)


def drop(doc, body, obj):
    if obj is None:
        return
    name = obj.Name
    if body is not None:
        try:
            body.removeObject(obj)
        except Exception as _fw_err:
            _fw_log("refgeom2.py:114", _fw_err)
    try:
        doc.removeObject(name)
    except Exception as _fw_err:
        _fw_log("refgeom2.py:118", _fw_err)


def attach(obj, support, mode, offset=None):
    obj.MapMode = "Deactivated"         # a new support may not suit the last mode
    obj.AttachmentSupport = support
    obj.MapMode = mode
    obj.AttachmentOffset = offset or App.Placement()
    obj.Document.recompute()
    if "Invalid" in obj.State:
        raise RuntimeError(obj.getStatusString())


def _is_sketch(obj):
    try:
        return obj.isDerivedFrom("Sketcher::SketchObject")
    except Exception:
        return False


def _curve_feature(obj):
    """A curve object (helix, projected/composite/XYZ curve): edges only, in one chain of several."""
    try:
        if obj.isDerivedFrom("Sketcher::SketchObject") or obj.isDerivedFrom("PartDesign::Body"):
            return False
        shape = obj.Shape
        if shape.isNull() or shape.Faces or len(shape.Edges) < 2:
            return False
        return len(shape.Wires) == 1 and len(shape.Wires[0].Edges) == len(shape.Edges)
    except Exception:
        return False



PROMPTS = ("Select ", "Type ")


class PickBox(QtWidgets.QListWidget):
    ""

    def __init__(self, panel, name, kinds, many=False, height=26):
        super().__init__()
        self.panel, self.kinds, self.many = panel, kinds, many
        self.setObjectName(name)
        self.setFixedHeight(height)
        self.items = []         # [(obj, sub)]
        self.setStyleSheet(WHITE)

    def mousePressEvent(self, event):
        self.panel.activate(self)
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        self.panel.activate(self)
        super().focusInEvent(event)

    def take(self, obj, sub):
        kind = element_kind(obj, sub)
        if kind not in self.kinds and "sketch" in self.kinds and sub and _is_sketch(obj):

            # (fix155: a preselected or clicked sketch entity left "Select a sketch to project.")
            kind, sub = "sketch", ""
        elif sub and "curve" in self.kinds and "sketch" in self.kinds and _curve_feature(obj):

            # edges takes the whole curve (fix155: Composite Curve took one turn of a helix)
            kind, sub = "curve", ""
        if kind not in self.kinds:
            return False
        for i, (o, s) in enumerate(self.items):
            if o == obj and s == sub:
                del self.items[i]
                self.show_items()
                return True
        if self.many:
            self.items.append((obj, sub))
        else:
            self.items = [(obj, sub)]
        self.show_items()
        return True

    def show_items(self):
        self.clear()
        try:
            from . import refplanelook
            texts = refplanelook.sw_labels(list(self.items))
        except Exception as _fw_err:
            _fw_log("refgeom2.py:sw_labels", _fw_err)
            texts = [label(o, s) for o, s in self.items]
        for text in texts:
            self.addItem(text)

    def first(self):
        return self.items[0] if self.items else None


class _Escape(QtCore.QObject):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) and event.key() == QtCore.Qt.Key_Escape \
                and not event.modifiers():
            if t == QtCore.QEvent.KeyPress and _OPEN and _OPEN[0] is self.panel:
                QtCore.QTimer.singleShot(0, self.panel.reject)
            return True
        return False


_OPEN = []


def current():
    return _OPEN[0] if _OPEN else None


class PM:
    """The task dialog base: a message box, pick boxes, one transaction, check and cross."""

    TITLE = ""
    ICON = ""

    def __init__(self, doc):
        _OPEN[:] = [self]
        self.doc = doc
        self.boxes = []
        self.active = None
        self.made = []
        self.ok = False
        self.opened = False
        self.busy = False
        doc.openTransaction(self.TITLE)
        try:
            self.opened = True
            msg = QtWidgets.QWidget()
            msg.setWindowTitle("Message")
            msg.setProperty("swstyle_pm_title", self.TITLE)
            msg.setProperty("swstyle_pm_icon", self.ICON)
            lay = QtWidgets.QVBoxLayout(msg)
            self.message = QtWidgets.QLabel("", msg)
            self.message.setObjectName("SW%sMessage" % self.TITLE.replace(" ", "").replace("/", ""))
            self.message.setWordWrap(True)
            lay.addWidget(self.message)
            self.form = [msg]
            self._esc = _Escape(self)
            self._views = []
            try:
                for w in [v for v in Gui.getMainWindow().findChildren(QtWidgets.QWidget) if v.inherits("QOpenGLWidget")]:
                    w.installEventFilter(self._esc)
                    self._views.append(w)
            except Exception as _fw_err:
                _fw_log("refgeom2.py:261", _fw_err)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise

    def group(self, title, name=None):
        box = QtWidgets.QWidget()
        box.setWindowTitle(title)
        if name:
            box.setObjectName(name)
        lay = QtWidgets.QVBoxLayout(box)
        self.form.append(box)
        return box, lay

    def pick_box(self, name, kinds, many=False, height=26):
        b = PickBox(self, name, kinds, many, height)
        self.boxes.append(b)
        return b

    def activate(self, box):
        self.active = box
        self._mark()

    def _mark(self):
        """pkg108: the boxes marked as every other PM's (pmboxes): the active one pink, the
        active empty one needed (so OK and the opening keyboard wait for the pick)."""
        for b in self.boxes:
            try:
                pmboxes.mark(b, b is self.active, need=b is self.active and not b.items and not self.ok)
            except Exception:
                b.setStyleSheet(BLUE if b is self.active else WHITE)

    def start(self, picks=()):
        if self.boxes and self.active is None:
            self.activate(self.boxes[0])
        for obj, sub in picks:
            self._take(obj, sub)
        self.update()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # --- picks
    def _gone(self):
        """True when this page was closed from outside (Gui.Control.closeDialog(), as when another
        command starts): it stops listening, so it no longer clears the next page's picks."""
        try:
            alive = bool(_OPEN) and _OPEN[0] is self and bool(Gui.Control.activeDialog())
        except Exception:
            alive = False
        if alive:
            return False
        if _OPEN and _OPEN[0] is self:
            _OPEN[:] = []
        for w in self._views:
            try:
                w.removeEventFilter(self._esc)
            except Exception as _fw_err:
                _fw_log("refgeom2.py:315", _fw_err)
        self._views = []
        QtCore.QTimer.singleShot(0, self._unwatch)     # not from inside the observer's own call
        return True

    def _unwatch(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("refgeom2.py:324", _fw_err)

    def addSelection(self, doc, name, sub, pnt):
        if self._gone() or pickguard.stale(self, self.doc):
            return
        if doc != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        if obj is None or obj in self.made:
            return
        obj, sub = refplane.resolve(obj, sub)
        sub = self._vertex_near(obj, sub, pnt)
        QtCore.QTimer.singleShot(0, lambda: self._picked(obj, sub))

    def _vertex_near(self, obj, sub, pnt, pixels=6):
        ""


        try:
            if not (sub and sub.startswith("Edge") and pnt is not None):
                return sub
            shown = [b for b in self.boxes if not b.isHidden()]
            if not shown or any(set(b.kinds) - {"point"} for b in shown):
                return sub
            shape = obj.Shape
            edge = shape.getElement(sub)
            view = Gui.ActiveDocument.ActiveView
            at = view.getPointOnScreen(App.Vector(*pnt))
            best = None
            for v in edge.Vertexes:
                sx, sy = view.getPointOnScreen(v.Point)
                d = ((sx - at[0]) ** 2 + (sy - at[1]) ** 2) ** 0.5
                if d <= pixels * _dpr() and (best is None or d < best[0]):
                    best = (d, v)
            if best is None:
                return sub
            for i, v in enumerate(shape.Vertexes, 1):
                if v.isSame(best[1]):
                    return "Vertex%d" % i
        except Exception as _fw_err:
            _fw_log("refgeom2.py:_vertex_near", _fw_err)
        return sub

    def _picked(self, obj, sub):
        if self._gone():
            return
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("refgeom2.py:343", _fw_err)
        self._take(obj, sub)
        self.update()

    def _take(self, obj, sub):
        ""

        if isinstance(self, (CoordinateSystemPM, PointPM)):
            obj, sub = refplane.datum_ref(obj, sub, getattr(self, "body", None))     # datums: picks in another frame
        shown = [b for b in self.boxes if not b.isHidden()]
        order = ([self.active] if self.active in shown else []) + [b for b in shown if b is not self.active]
        for b in order:
            if b.take(obj, sub):
                if not b.many and b.items:
                    nxt = next((x for x in shown if not x.items and x is not b), None)
                    if nxt is not None:
                        self.activate(nxt)
                return True
        return False

    # --- result
    def build(self):
        """Make or update the result; raise RuntimeError with what is missing."""
        raise NotImplementedError

    def changed(self, *_args):
        self.update()

    def update(self):
        if self.busy:
            return
        self.busy = True
        try:
            self.layout_rows()
            self.build()
            self.message.setText(self.done_text())
            self.message.setStyleSheet("QLabel { color: #2e7d32; border: none; background: transparent; }")
            self.ok = True
        except Exception as error:
            self.message.setText(str(error))

            # promptink-fix01: "Type two or more points ..." (Curve Through XYZ Points, nothing given yet) is a prompt too
            ink = "#000000" if str(error).startswith(PROMPTS) else "#c00000"
            self.message.setStyleSheet("QLabel { color: %s; border: none; background: transparent; }" % ink)
            self.ok = False
        finally:
            self.busy = False
        try:
            from . import refplanelook
            done = self.ok and self.message.text() == "Fully defined"
            refplanelook.paint_label(self.message, done)
            refplanelook.paint_later(self.message, lambda: self.ok and self.message.text() == "Fully defined")
        except Exception as _fw_err:
            _fw_log("refgeom2.py:message", _fw_err)
        self._mark()

    def layout_rows(self):
        """Show or hide rows as the options change."""

    def done_text(self):
        return ""

    # --- check and cross
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        _OPEN[:] = []
        for w in self._views:
            try:
                w.removeEventFilter(self._esc)
            except Exception as _fw_err:
                _fw_log("refgeom2.py:403", _fw_err)
        self._views = []
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("refgeom2.py:408", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if not self.ok:
            return False
        self.finish()
        self.doc.commitTransaction()
        self._close()
        return True

    def finish(self):
        """Last touches before the check keeps the result."""

    def reject(self):
        if self.opened:
            self.doc.abortTransaction()
        self.doc.recompute()
        self._close()
        return True


def _region_text(column, v):
    """A Variable pitch table cell: Pitch and Diameter (columns 0 and 2) in the part's units, Rev as it is."""
    if column == 1:
        return "%g" % v
    from . import curves
    return curves.cell_text(v)


def _region_value(column, text):
    ""
    if column == 1:
        return float(text)
    from . import curves
    v = curves._length(text)
    if v is None:
        raise ValueError(text)
    return v


def _spin(value, low, high, suffix="", decimals=3, name=None):
    from .pmspin import TrimSpin
    s = TrimSpin()
    s.setDecimals(decimals)
    s.setRange(low, high)
    s.setValue(value)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    if name:
        s.setObjectName(name)
    return s


def _unit_len(spin, lo, hi, doc=None, unit=True):
    ""

    from . import evaluate
    old = float(spin.property("swmm") or 1.0)
    sym, k = evaluate.doc_unit(doc) if unit else ("%", 1.0)
    suffix = " " + sym if unit else " %"
    if abs(old - k) < 1e-12 and spin.suffix() in (suffix, suffix.strip()):
        return spin
    spin.blockSignals(True)
    try:
        # from a percentage the number typed stays as it is, in the new unit
        v = (spin.value() * (k if spin.suffix() == " %" else old)) if unit else spin.value()
        spin.setProperty("swmm", k)
        spin.setDecimals(3 if k == 1.0 else 4)
        spin.setRange(lo / k, hi / k) if unit else spin.setRange(0.0, 1e6)
        spin.setSuffix(suffix)
        spin.setValue(v / k)
    finally:
        spin.blockSignals(False)
    return spin


class _WrapLabel(QtWidgets.QLabel):
    ""


    def __init__(self, text, box):
        super().__init__(text)
        self.box = box
        self.setWordWrap(True)
        self.setBuddy(box)

    def mousePressEvent(self, event):
        if self.box.isEnabled():
            self.box.toggle()


class _WrapCheck(QtWidgets.QCheckBox):
    """A check box whose text sits in a wrapping label beside it; text() still gives that text."""

    def __init__(self, text):
        super().__init__()
        self._text = text

    def text(self):
        return self._text


def _wrap_check(lay, text, name):
    box = _WrapCheck(text)
    box.setObjectName(name)
    box.setToolTip(text)
    box.setAccessibleName(text)
    lab = _WrapLabel(text, box)
    lab.setObjectName(name + "Text")
    row = QtWidgets.QHBoxLayout()
    row.addWidget(box, 0, QtCore.Qt.AlignTop)
    row.addWidget(lab, 1)
    lay.addLayout(row)
    return box


def _row(lay, text, widget):
    row = QtWidgets.QHBoxLayout()
    lab = QtWidgets.QLabel(text)
    row.addWidget(lab)
    row.addWidget(widget, 1)
    lay.addLayout(row)
    return lab


# =========================================================================== Coordinate System
AXES = ("X", "Y", "Z")
# FreeCAD's origin-and-two-axes modes for the pairs of axes picked
O_MODES = {("X", "Y"): "OXY", ("X", "Z"): "OXZ", ("Y", "Z"): "OYZ",
           ("Y", "X"): "OYX", ("Z", "X"): "OZX", ("Z", "Y"): "OZY"}
# Reverse an axis: turned half round another axis (the system stays right-handed)
REVERSE_ABOUT = {"X": V(0, 0, 1), "Y": V(0, 0, 1), "Z": V(1, 0, 0)}


def default_origin(doc, body=None):
    ""

    holders = [body] if body is not None else []
    try:
        holders.append(Gui.ActiveDocument.ActiveView.getActiveObject("part"))
    except Exception as _fw_err:
        _fw_log("refgeom2.py:default_origin", _fw_err)
    holders += [o for o in doc.Objects if o.TypeId.startswith("Assembly::") or o.TypeId == "App::Part"]
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    holders += bodies if len(bodies) == 1 else []
    for h in holders:
        for f in getattr(getattr(h, "Origin", None), "OriginFeatures", []) or []:
            if f.TypeId == "App::Point" and getattr(f, "Role", "") == "Origin":
                return (f, "")
    return None


def _axis_dir(origin, pick):
    ""

    kind = element_kind(*pick)
    if kind == "plane":
        return refplane._plane_of(*pick)[1] if pick[1] else \
            pick[0].Placement.Rotation.multVec(V(0, 0, 1))
    if kind == "point":
        at = refplane._point_of(*pick) if pick[1] else V(pick[0].Placement.Base)
        o = refplane._point_of(*origin) if origin is not None and origin[1] else \
            (V(origin[0].Placement.Base) if origin is not None else V())
        return at - o
    if kind == "line":
        if pick[1]:
            return refplane._line_of(*pick)[1]
        return pick[0].Placement.Rotation.multVec(V(0, 0, 1))
    raise RuntimeError("Select an edge, a point or a plane for the axis.")


def plane_axes(axes):
    """The axes picked on a plane or flat face (FreeCAD's origin-and-axes modes take only edges and points)."""
    return [a for a in AXES if axes.get(a) and element_kind(*axes[a]) == "plane"]


def cs_rotation(origin, axes):
    """The coordinate system's rotation from the picked axes, as FreeCAD's O-modes make it: the first picked
    axis exact, the second made square to it."""
    picked = [a for a in AXES if axes.get(a)]
    dirs = {a: _axis_dir(origin, axes[a]) for a in picked}
    for a, d in dirs.items():
        if d.Length < 1e-9:
            raise RuntimeError("The %s axis pick gives no direction." % a)
    order = "".join(picked[:2]) + "".join(a for a in AXES if a not in picked[:2])
    if len(picked) == 1:
        order = {"X": "XYZ", "Y": "YXZ", "Z": "ZXY"}[picked[0]]
    x, y, z = (App.Vector(dirs.get(a, V())) for a in AXES)
    return App.Rotation(x, y, z, order)


def cs_recipe(origin, axes, reverse=(), position=None, rotation=None):
    """(support, mode, offset) for the coordinate system. axes: {"X": (obj, sub), ...}."""
    picked = [a for a in AXES if axes.get(a)]
    support = []
    if origin is not None:
        support.append(origin)
    if plane_axes(axes) and origin is not None:
        # rgdeep: a plane for an axis: FreeCAD's O-modes cannot take it (it failed: "all directions supplied are
        # zero"); the system sits on its origin (Translate) and is turned by the picks (follow_cs after rebuilds)
        rot = cs_rotation(origin, axes)
        for a in reverse:
            rot = rot.multiply(App.Rotation(REVERSE_ABOUT[a], 180))
        if rotation is not None and any(rotation):
            rot = rot.multiply(App.Rotation(*rotation[::-1]))
        return support, "Translate", App.Placement(V(*position) if position is not None else V(), rot)
    if len(picked) >= 2 and origin is not None:
        pair = tuple(picked[:2])
        mode = O_MODES[pair]
        support += [axes[pair[0]], axes[pair[1]]]
    elif len(picked) == 1 and origin is not None:

        mode = {"X": "OXY", "Y": "OYX", "Z": "OZX"}[picked[0]]
        support.append(axes[picked[0]])
    elif origin is not None:
        mode = "Translate"
    elif picked:
        raise RuntimeError("Select a point for the origin.")
    else:
        mode = "Deactivated"
    rot = App.Rotation()
    for a in reverse:
        rot = rot.multiply(App.Rotation(REVERSE_ABOUT[a], 180))
    if rotation is not None:
        rot = App.Rotation(*rotation[::-1]).multiply(rot) if any(rotation) else rot
    offset = App.Placement(V(*position) if position is not None else V(), rot)
    return support, mode, offset


class CoordinateSystemPM(PM):
    TITLE = "Coordinate System"
    ICON = "REFGEO_CSYS"

    def __init__(self, doc, picks=()):
        super().__init__(doc)
        self.body = holder(doc)
        self.cs = None
        box, lay = self.group("Selections", "SWCSysSelections")
        lay.addWidget(QtWidgets.QLabel("Position"))
        self.origin = self.pick_box("SWCSysOrigin", ("point",))
        lay.addWidget(self.origin)
        self.numeric_pos = _wrap_check(lay, "Define position with numeric values", "SWCSysNumericPosition")
        self.pos = [_unit_len(_spin(0.0, -1e7, 1e7, " mm", name="SWCSysPos" + a), -1e7, 1e7, doc) for a in AXES]
        self.pos_labels = [_row(lay, a, s) for a, s in zip(AXES, self.pos)]
        lay.addWidget(QtWidgets.QLabel("Orientation"))
        self.axis_box, self.reverse = {}, {}
        for a in AXES:
            row = QtWidgets.QHBoxLayout()
            rev = QtWidgets.QCheckBox("Reverse %s Axis Direction" % a)
            rev.setObjectName("SWCSysReverse" + a)
            b = self.pick_box("SWCSysAxis" + a, ("line", "point", "plane"))
            row.addWidget(QtWidgets.QLabel("%s axis" % a))
            row.addWidget(b, 1)
            lay.addLayout(row)
            lay.addWidget(rev)
            self.axis_box[a], self.reverse[a] = b, rev
            rev.toggled.connect(self.changed)
        self.numeric_rot = _wrap_check(lay, "Define rotation with numeric values", "SWCSysNumericRotation")
        self.rot = [_spin(0.0, -360, 360, "°", 2, name="SWCSysRot" + a) for a in AXES]
        self.rot_labels = [_row(lay, "Rotate about %s" % a, s) for a, s in zip(AXES, self.rot)]
        for w in self.pos + self.rot:
            w.valueChanged.connect(self.changed)
        self.numeric_pos.toggled.connect(self.changed)
        self.numeric_rot.toggled.connect(self.changed)
        self.start(picks)

    def layout_rows(self):
        for w, l in zip(self.pos, self.pos_labels):
            w.setVisible(self.numeric_pos.isChecked())
            l.setVisible(self.numeric_pos.isChecked())
        for w, l in zip(self.rot, self.rot_labels):
            w.setVisible(self.numeric_rot.isChecked())
            l.setVisible(self.numeric_rot.isChecked())

    def recipe(self):
        axes = {a: self.axis_box[a].first() for a in AXES}
        rev = [a for a in AXES if self.reverse[a].isChecked()]
        from . import evaluate
        pos = tuple(evaluate.mm_of(s) for s in self.pos) if self.numeric_pos.isChecked() else None
        rot = tuple(s.value() for s in self.rot) if self.numeric_rot.isChecked() else None
        origin = self.origin.first()
        if origin is None and any(axes.values()):
            origin = default_origin(self.doc, self.body)
        return cs_recipe(origin, axes, rev, pos, rot)

    def build(self):
        support, mode, offset = self.recipe()
        if self.cs is None:
            self.cs = new_datum(self.doc, self.body, "PartDesign::CoordinateSystem", "CoordinateSystem")
            self.made = [self.cs]
        if mode == "Deactivated":
            self.cs.MapMode = "Deactivated"
            self.cs.AttachmentSupport = None
            self.cs.Placement = offset
            self.doc.recompute()
        else:
            _attach_cs(self.cs, support, mode, offset)
        keep_cs_axes(self.cs, {a: self.axis_box[a].first() for a in AXES},
                     [a for a in AXES if self.reverse[a].isChecked()],
                     tuple(s.value() for s in self.rot) if self.numeric_rot.isChecked() else None)

    def done_text(self):
        return "Fully defined" if self.origin.items else "The coordinate system is at the part's origin."


def make_coordinate_system(doc, origin=None, axes=None, reverse=(), position=None, rotation=None):
    """The Coordinate System without the PropertyManager (for macros and tests)."""
    body = holder(doc)
    if origin is None and any((axes or {}).values()):
        origin = default_origin(doc, body)
    support, mode, offset = cs_recipe(origin, axes or {}, reverse, position, rotation)
    doc.openTransaction("Coordinate System")
    try:
        cs = new_datum(doc, body, "PartDesign::CoordinateSystem", "CoordinateSystem")
        if mode == "Deactivated":
            cs.Placement = offset
            doc.recompute()
        else:
            _attach_cs(cs, support, mode, offset)
        keep_cs_axes(cs, axes or {}, reverse, rotation)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return cs


CS_KEEP = "FreeCAD references"


def keep_cs_axes(cs, axes, reverse=(), rotation=None):
    """rgdeep: the axis picks kept on the coordinate system (plain properties): Edit Feature puts each back in its
    own box (an edited Z-only system came back with its Z edge in the X box and was turned), and a system turned by
    a plane follows the plane after each rebuild (follow_cs)."""
    import json
    try:
        for a in AXES:
            prop = "FwAxis" + a
            if prop not in cs.PropertiesList:
                cs.addProperty("App::PropertyLinkSubGlobal", prop, CS_KEEP, "The %s axis pick" % a)
                cs.setEditorMode(prop, 2)
            pick = axes.get(a)
            setattr(cs, prop, (pick[0], [pick[1]] if pick[1] else []) if pick else None)
        if "FwAxes" not in cs.PropertiesList:
            cs.addProperty("App::PropertyString", "FwAxes", CS_KEEP, "Reverse and rotation of the axis picks")
            cs.setEditorMode("FwAxes", 2)
        cs.FwAxes = json.dumps({"reverse": list(reverse or ()), "rotation": list(rotation) if rotation else None,
                                "planes": bool(plane_axes(axes))})
    except Exception as _fw_err:
        _fw_log("refgeom2.py:keep_cs_axes", _fw_err)


def kept_cs_axes(cs):
    """{axis: (obj, sub)} kept on the coordinate system, else None (made before rgdeep, or another way)."""
    if "FwAxisX" not in cs.PropertiesList:
        return None
    out = {}
    for a in AXES:
        link = getattr(cs, "FwAxis" + a, None)
        if link and link[0] is not None:
            out[a] = (link[0], link[1][0] if link[1] else "")
    return out


def _follow_cs(cs):
    import json
    try:
        data = json.loads(getattr(cs, "FwAxes", "") or "{}")
    except Exception:
        return False
    if not data.get("planes") or cs.MapMode != "Translate" or not cs.AttachmentSupport:
        return False
    axes = kept_cs_axes(cs) or {}
    origin = cs.AttachmentSupport[0]
    origin = (origin[0], origin[1][0] if origin[1] else "")
    _s, _m, offset = cs_recipe(origin, axes, data.get("reverse") or (), None, data.get("rotation"))
    if cs.Placement.Rotation.isSame(offset.Rotation, 1e-9):
        return False
    cs.Placement = App.Placement(cs.Placement.Base, offset.Rotation)
    return True


def _follow_along(pt):
    ""

    d = float(getattr(pt, "FwAlongDistance", -1.0))
    if d < 0 or pt.MapMode != "OnEdge" or not pt.AttachmentSupport:
        return False
    obj, subs = pt.AttachmentSupport[0]
    edge = refplane.shape_of(obj, subs[0] if subs else "").Edges[0]
    if edge.Length <= 0:
        return False
    t = _edge_parameter(edge, min(1.0, d / edge.Length))
    if abs(t - pt.MapPathParameter) < 1e-9:
        return False
    pt.MapPathParameter = t
    return True


VERTEX_KEEP = "FwVertexEdges"


def keep_vertex_edges(datum):
    ""



    import json
    try:
        keep = []
        for obj, subs in datum.AttachmentSupport or []:
            for sub in subs:
                if not sub.startswith("Vertex"):
                    continue
                shape = obj.Shape
                v = shape.getElement(sub)
                names = []
                for i, e in enumerate(shape.Edges, 1):
                    if any(x.isSame(v) for x in e.Vertexes):
                        m = shape.getElementMappedName("Edge%d" % i)
                        m = m[0] if isinstance(m, (tuple, list)) else m
                        if m:
                            names.append(m)
                keep.append([obj.Name, names])
        if not keep and VERTEX_KEEP not in datum.PropertiesList:
            return
        if VERTEX_KEEP not in datum.PropertiesList:
            datum.addProperty("App::PropertyString", VERTEX_KEEP, "FreeCAD references",
                              "Edges meeting at the vertex the datum sits on")
            datum.setEditorMode(VERTEX_KEEP, 2)
        text = json.dumps(keep)
        if getattr(datum, VERTEX_KEEP) != text:
            setattr(datum, VERTEX_KEEP, text)
    except Exception as _fw_err:
        _fw_log("refgeom2.py:keep_vertex_edges", _fw_err)


def _corner(obj, mapped):
    """The vertex of obj ("VertexN") where the kept edges that still exist meet, when two or more are left."""
    shape = obj.Shape
    emap = shape.ElementMap
    edges = []
    for m in mapped:
        n = emap.get(m)
        if n and n.startswith("Edge"):
            try:
                edges.append(shape.getElement(n))
            except Exception:
                continue
    if len(edges) < 2:
        return None
    hits = [i for i, v in enumerate(shape.Vertexes, 1) if all(any(x.isSame(v) for x in e.Vertexes) for e in edges)]
    return "Vertex%d" % hits[0] if len(hits) == 1 else None


def _follow_vertex(datum):
    """A datum whose model vertex FreeCAD lost ("?VertexN") goes back on the corner where its kept edges meet."""
    support = list(datum.AttachmentSupport or [])
    if not any(s.startswith("?Vertex") for _o, subs in support for s in subs):
        return False
    import json
    try:
        kept = json.loads(getattr(datum, VERTEX_KEEP, "") or "[]")
    except Exception:
        return False
    k, out, changed = 0, [], False
    for obj, subs in support:
        new = []
        for s in subs:
            if s.lstrip("?").startswith("Vertex"):
                entry = kept[k] if k < len(kept) else None
                k += 1
                if s.startswith("?") and entry is not None and entry[0] == obj.Name:
                    hit = _corner(obj, entry[1])
                    if hit:
                        s, changed = hit, True
            new.append(s)
        out.append((obj, new))
    if not changed:
        return False
    mode = datum.MapMode
    datum.AttachmentSupport = [(o, ss) for o, ss in out]
    datum.MapMode = mode
    keep_vertex_edges(datum)
    return True


_following = set()


def follow(doc):
    """After a rebuild: coordinate systems turned by a plane, and points a distance along a curve, follow."""
    if doc.Name in _following or current() is not None:
        return
    changed = corners = False
    for o in doc.Objects:
        try:
            if o.TypeId in ("PartDesign::CoordinateSystem", "Part::LocalCoordinateSystem") and "FwAxes" in o.PropertiesList:
                changed = _follow_cs(o) or changed
            elif "FwAlongDistance" in o.PropertiesList:
                changed = _follow_along(o) or changed
            if VERTEX_KEEP in o.PropertiesList and _follow_vertex(o):
                corners = True
        except Exception as error:
            App.Console.PrintLog("FreeCAD: %s not worked out again: %s\n" % (o.Label, error))
    if corners:
        # a datum put back on its corner is rebuilt once this rebuild is over (rebuilt from inside it, it kept
        # FreeCAD's Invalid mark)
        QtCore.QTimer.singleShot(0, lambda d=doc: _rebuild(d))
    if changed:
        _following.add(doc.Name)
        try:
            doc.recompute()
        finally:
            _following.discard(doc.Name)


def _rebuild(doc):
    try:
        if doc.Name not in App.listDocuments() or doc.Name in _following:
            return
        _following.add(doc.Name)
        try:
            doc.recompute()
        finally:
            _following.discard(doc.Name)
    except Exception as _fw_err:
        _fw_log("refgeom2.py:_rebuild", _fw_err)


def _attach_cs(cs, support, mode, offset):
    """FreeCAD's Translate mode takes only the origin from the vertex; the orientation is the
    object's own Placement, so Reverse and the numeric rotation go there (they did nothing before)."""
    if mode != "Translate":
        attach(cs, support, mode, offset)
        keep_vertex_edges(cs)
        return
    attach(cs, support, mode, App.Placement(offset.Base, App.Rotation()))
    keep_vertex_edges(cs)
    cs.Placement = App.Placement(cs.Placement.Base, offset.Rotation)
    cs.Document.recompute()


# =========================================================================== Point
POINT_TYPES = (
    ("ArcCenter", "Arc Center", ("circle",)),
    ("FaceCenter", "Center of Face", ("plane", "face")),
    ("Intersection", "Intersection", ("line", "circle", "curve", "plane", "face")),
    ("Projection", "Projection", ("point", "plane", "face", "line", "circle", "curve")),
    ("OnPoint", "On Point", ("point",)),
    ("AlongCurve", "Along curve distance or multiple reference point", ("line", "circle", "curve")),
)
ALONG = ("Distance", "Percentage", "Evenly Distribute")


def point_guess(kinds):
    k = sorted(kinds)
    if k == ["circle"]:
        return "ArcCenter"
    if len(k) == 1 and k[0] in ("plane", "face"):
        return "FaceCenter"
    if len(k) == 2 and "point" in k:
        return "Projection"
    if len(k) == 2:
        return "Intersection"
    if k == ["point"]:
        return "OnPoint"
    if len(k) == 1 and k[0] in ("line", "curve"):
        return "AlongCurve"
    return None


def _edge_parameter(edge, fraction):
    """FreeCAD's OnEdge parameter (0 to 1 over the curve) at a fraction of the edge's length."""
    length = edge.Length
    p = edge.getParameterByLength(max(0.0, min(length, fraction * length)))
    a, b = edge.FirstParameter, edge.LastParameter
    return (p - a) / (b - a) if b != a else 0.0


def along_fractions(edge_length, how, value, count):
    """The points along a curve: fractions of its length (0 to 1)."""
    if how == "Evenly Distribute":
        return [k / float(count + 1) for k in range(1, count + 1)]
    if how == "Percentage":
        out = [value / 100.0 * k for k in range(1, count + 1)]
    else:
        if edge_length <= 0:
            return []
        out = [value * k / edge_length for k in range(1, count + 1)]
    return [f for f in out if f <= 1.0 + 1e-9]


def _intersection(a, b):
    sa, sb = refplane.shape_of(*a), refplane.shape_of(*b)
    dist, pairs, _info = sa.distToShape(sb)
    if dist > 1e-6:
        raise RuntimeError("The selected entities do not meet.")
    return pairs[0][0]


def point_recipes(way, picks, how="Distance", value=10.0, count=1):
    """[(support, mode, extra)] one per point; extra: {"MapPathParameter": t} or {"Placement": p}."""
    kinds = [element_kind(*p) for p in picks]
    if way == "ArcCenter":
        if kinds != ["circle"]:
            raise RuntimeError("Select an arc or circle edge.")
        return [([picks[0]], "CenterOfCurvature", {})]
    if way == "FaceCenter":
        if len(picks) != 1 or kinds[0] not in ("plane", "face"):
            raise RuntimeError("Select a face.")
        return [([picks[0]], "CenterOfMass", {})]
    if way == "Intersection":
        if len(picks) != 2:
            raise RuntimeError("Select two edges, or an edge and a face or plane.")
        p = _intersection(picks[0], picks[1])
        # where the picks meet at a vertex of the model the point sits on that vertex (it follows
        # the model); elsewhere it is kept where they meet
        for obj, _sub in picks:
            try:
                for i, v in enumerate(obj.Shape.Vertexes):
                    if v.Point.distanceToPoint(p) < 1e-6:
                        return [([(obj, "Vertex%d" % (i + 1))], "Vertex", {})]
            except Exception as _fw_err:
                _fw_log("refgeom2.py:705", _fw_err)
        # rgdeep: elsewhere FreeCAD's nearest-point mode on the edge (or curve) towards the other pick puts it
        # where they meet and follows the model (kept fixed before, so it stayed behind when the model changed)
        order = sorted(picks, key=lambda q: 0 if element_kind(*q) in ("line", "circle", "curve") else 1)
        return [(order, "ProximityPoint1", {"fallback": p})]
    if way == "Projection":
        if len(picks) != 2 or "point" not in kinds:
            raise RuntimeError("Select a point and a face, plane or edge to project it onto.")
        point = picks[kinds.index("point")]
        onto = picks[1 - kinds.index("point")]
        return [([onto, point], "ProximityPoint1", {})]
    if way == "OnPoint":
        if kinds != ["point"] or len(picks) != 1:
            raise RuntimeError("Select a sketch point or vertex.")
        return [([picks[0]], "Vertex", {})]
    if way == "AlongCurve":
        if len(picks) != 1 or kinds[0] not in ("line", "circle", "curve"):
            raise RuntimeError("Select an edge or curve.")
        edge = refplane.shape_of(*picks[0]).Edges[0]
        fr = along_fractions(edge.Length, how, value, count)
        if not fr:
            raise RuntimeError("The distance is longer than the curve.")
        return [([picks[0]], "OnEdge", dict({"MapPathParameter": _edge_parameter(edge, f)},
                                            **({"FwAlongDistance": f * edge.Length} if how == "Distance" else {})))
                for f in fr]
    raise RuntimeError("Select references to define the point.")


def place_point(pt, support, mode, extra):
    if mode == "Deactivated" and "fallback" in extra:
        pt.MapMode = "Deactivated"
        pt.AttachmentSupport = None
        pt.Placement = App.Placement(V(extra["fallback"]), App.Rotation())
        pt.Document.recompute()
        return
    try:
        pt.MapMode = "Deactivated"
        pt.AttachmentSupport = support
        pt.MapMode = mode
        if "MapPathParameter" in extra:
            pt.MapPathParameter = extra["MapPathParameter"]
        if "FwAlongDistance" in extra or "FwAlongDistance" in pt.PropertiesList:
            if "FwAlongDistance" not in pt.PropertiesList:
                pt.addProperty("App::PropertyFloat", "FwAlongDistance", "FreeCAD references",
                               "Distance along the curve (mm) the point keeps; -1 for a percentage")
                pt.setEditorMode("FwAlongDistance", 2)
            pt.FwAlongDistance = float(extra.get("FwAlongDistance", -1.0))
        keep_vertex_edges(pt)
        pt.Document.recompute()
        bad = "Invalid" in pt.State
        if not bad and "fallback" in extra and pt.Placement.Base.distanceToPoint(V(extra["fallback"])) > 1e-6:
            bad = True          # the nearest point is not where the picks meet: kept where they meet
    except Exception:
        bad = True
    if bad and "fallback" in extra:
        # FreeCAD's intersection mode takes only some pairs; the point is kept where they meet
        pt.MapMode = "Deactivated"
        pt.AttachmentSupport = None
        pt.Placement = App.Placement(V(extra["fallback"]), App.Rotation())
        pt.Document.recompute()
        bad = False
    if bad:
        raise RuntimeError(pt.getStatusString() if hasattr(pt, "getStatusString") else "The point cannot be made.")


class PointPM(PM):
    TITLE = "Point"
    ICON = "REFGEO_POINT"

    def __init__(self, doc, picks=()):
        super().__init__(doc)
        self.body = holder(doc)
        self.points = []
        self.way = None
        box, lay = self.group("Selections", "SWPointSelections")
        self.refs = self.pick_box("SWPointReferences", ("point", "line", "circle", "curve", "plane", "face"),
                                  many=True, height=56)
        lay.addWidget(self.refs)
        self.buttons = {}
        group = QtWidgets.QButtonGroup(box)
        for key, text, _kinds in POINT_TYPES:
            b = QtWidgets.QToolButton(box)
            b.setObjectName("SWPoint" + key)

            # whole PropertyManager pane 54 px wider than every other page
            b.setText(text.replace(" or multiple", " or\nmultiple"))
            b.setToolTip(text)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
            b.clicked.connect(lambda _c=False, k=key: self.set_way(k))
            group.addButton(b)
            lay.addWidget(b)
            self.buttons[key] = b
        self.how = {}
        hl = QtWidgets.QHBoxLayout()
        hg = QtWidgets.QButtonGroup(box)
        for text in ALONG:
            r = QtWidgets.QRadioButton(text)
            r.setObjectName("SWPoint" + text.replace(" ", ""))
            hg.addButton(r)
            hl.addWidget(r)
            self.how[text] = r
            r.toggled.connect(self.changed)
        self.how["Distance"].setChecked(True)
        lay.addLayout(hl)
        self.value = _spin(10.0, 0.0, 1e6, " mm", name="SWPointDistance")
        self.value_label = _row(lay, "Distance", self.value)
        self.count = QtWidgets.QSpinBox()
        self.count.setObjectName("SWPointCount")
        self.count.setRange(1, 500)
        self.count_label = _row(lay, "Number of points", self.count)
        self.value.valueChanged.connect(self.changed)
        self.count.valueChanged.connect(self.changed)

        self.numeric_pos = _wrap_check(lay, "Define position with numeric values", "SWPointNumericPosition")
        self.pos = [_unit_len(_spin(0.0, -1e7, 1e7, " mm", name="SWPointPos" + a), -1e7, 1e7, doc) for a in AXES]
        self.pos_labels = [_row(lay, a, w) for a, w in zip(AXES, self.pos)]
        for w in self.pos:
            w.valueChanged.connect(self.changed)
        self.numeric_pos.toggled.connect(self.changed)
        self.start(picks)

    def _take(self, obj, sub):
        ok = super()._take(obj, sub)
        self.way = None
        return ok

    def set_way(self, key):
        self.way = key
        self.update()

    def current_how(self):
        return next(t for t, r in self.how.items() if r.isChecked())

    def layout_rows(self):
        way = self.way or point_guess([element_kind(*p) for p in self.refs.items])
        for key, b in self.buttons.items():
            b.setChecked(key == way)
        along = way == "AlongCurve"
        how = self.current_how()
        for r in self.how.values():
            r.setVisible(along)
        self.value.setVisible(along and how != "Evenly Distribute")
        self.value_label.setVisible(along and how != "Evenly Distribute")
        self.value_label.setText("Percentage" if how == "Percentage" else "Distance")
        _unit_len(self.value, 0.0, 1e6, self.doc, unit=how != "Percentage")    # Distance in the part's unit
        self.count.setVisible(along)
        self.count_label.setVisible(along)
        numeric = self.numeric_pos.isChecked()
        for w, label in zip(self.pos, self.pos_labels):
            w.setVisible(numeric)
            label.setVisible(numeric)
        # numeric values place the point with nothing picked: the picks and types go out of the
        # way rather than greyed (no greyed control: Ati's rule)
        self.refs.setVisible(not numeric)
        for b in self.buttons.values():
            b.setVisible(not numeric)

    def build(self):
        if self.numeric_pos.isChecked():
            self._points(1)
            from . import evaluate
            at = V(*(evaluate.mm_of(w) for w in self.pos))
            place_point(self.points[0], None, "Deactivated", {"fallback": at})
            return
        way = self.way or point_guess([element_kind(*p) for p in self.refs.items])
        if not self.refs.items:
            self._points(0)
            raise RuntimeError("Select references and a type of point.")
        from . import evaluate
        rec = point_recipes(way, self.refs.items, self.current_how(), evaluate.mm_of(self.value), self.count.value())
        self._points(len(rec))
        for pt, (support, mode, extra) in zip(self.points, rec):
            place_point(pt, support, mode, extra)

    def _points(self, n):
        while len(self.points) < n:
            self.points.append(new_datum(self.doc, self.body, "PartDesign::Point", "Point"))
        while len(self.points) > n:
            drop(self.doc, self.body, self.points.pop())
        self.made = list(self.points)
        self.doc.recompute()

    def done_text(self):
        return "Fully defined"


def make_points(doc, way, picks, how="Distance", value=10.0, count=1):
    body = holder(doc)
    doc.openTransaction("Point")
    try:
        out = []
        for support, mode, extra in point_recipes(way, picks, how, value, count):
            pt = new_datum(doc, body, "PartDesign::Point", "Point")
            place_point(pt, support, mode, extra)
            out.append(pt)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return out


# =========================================================================== Helix / Spiral
DEFINED_BY = ["Pitch and Revolution", "Height and Revolution", "Height and Pitch", "Spiral"]


def _circle_of(sketch):
    """(centre, radius) of the sketch's circle (its first circle or arc), in the sketch's own plane."""
    for g in sketch.Geometry:
        if hasattr(g, "Radius") and hasattr(g, "Center"):
            return V(g.Center), g.Radius
    raise RuntimeError("The sketch must hold one circle.")


def helix_size(obj):
    """(revolutions, height, pitch) from the property the Defined By uses."""
    by = obj.DefinedBy
    if by == "Pitch and Revolution":
        return obj.Revolutions, obj.Pitch.Value * obj.Revolutions, obj.Pitch.Value
    if by == "Height and Revolution":
        return obj.Revolutions, obj.Height.Value, obj.Height.Value / max(obj.Revolutions, 1e-9)
    if by == "Height and Pitch":
        return obj.Height.Value / max(obj.Pitch.Value, 1e-9), obj.Height.Value, obj.Pitch.Value
    return obj.Revolutions, 0.0, obj.Pitch.Value


def helix_points(radius, revs, pitch, start=0.0, clockwise=False, reverse=False, taper=0.0, outward=False,
                 spiral=False, regions=None, per_rev=48):
    """Points of the helix (or spiral) in its own frame: the circle's centre at the origin, its
    axis along Z. regions: [(revolution, pitch, diameter)] for a variable pitch."""
    n = max(2, int(math.ceil(revs * per_rev)))
    sign = -1.0 if clockwise else 1.0
    up = -1.0 if reverse else 1.0
    tan = math.tan(math.radians(taper)) * (1.0 if outward else -1.0)
    pts = []
    z = 0.0
    last_t = 0.0
    for i in range(n + 1):
        t = revs * i / float(n)                 # revolutions so far
        p, r = pitch, radius
        if regions and len(regions) >= 2:
            p, d = _region_at(regions, t)
            r = d / 2.0
        if spiral:
            rr = radius + up * pitch * t        # a spiral grows by the pitch each turn, in its plane
            zz = 0.0
        else:
            z += p * (t - last_t)
            zz = up * z
            rr = r + abs(zz) * tan
        last_t = t
        a = math.radians(start) + sign * 2 * math.pi * t
        pts.append(V(rr * math.cos(a), rr * math.sin(a), zz))
    return pts


def exact_helix(radius, revs, pitch, start=0.0, clockwise=False, reverse=False, taper=0.0, outward=False,
                frame=None):
    ""


    import Part
    if revs <= 0 or pitch <= 0 or radius <= 0:
        return None
    up = -1.0 if reverse else 1.0
    left = bool(clockwise)          # seen along the axis it turns the same way once mirrored down
    angle = taper * (1.0 if outward else -1.0)
    try:
        # One edge per turn (makeLongHelix, as stock Part Helix does): the same exact curve, but the
        # swept spring is meshed for display in turns, about twice as fast as one long face.
        wire = Part.makeLongHelix(pitch, pitch * revs, radius, angle, left) if revs > 1 else \
            Part.makeHelix(pitch, pitch * revs, radius, angle, left)
    except Exception:
        try:
            wire = Part.makeHelix(pitch, pitch * revs, radius, angle, left)
        except Exception:
            return None
    m = App.Matrix()
    if reverse:
        m.scale(1, 1, -1)                       # mirrored through its base plane: it goes down
    turn = App.Matrix()
    turn.rotateZ(math.radians(start))
    m = turn.multiply(m)
    if frame is not None:
        m = frame.toMatrix().multiply(m)
    # baked into the geometry in one go (a Part feature puts its own Placement on the shape)
    return wire.transformGeometry(m)


def _region_at(regions, t):
    """Pitch and diameter at revolution t, straight between the table's rows."""
    rows = sorted(regions)
    if t <= rows[0][0]:
        return rows[0][1], rows[0][2]
    for (t0, p0, d0), (t1, p1, d1) in zip(rows, rows[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 != t0 else 0.0
            return p0 + (p1 - p0) * f, d0 + (d1 - d0) * f
    return rows[-1][1], rows[-1][2]


class Helix:
    """Insert > Curve > Helix/Spiral: a helix or spiral on a sketch circle, following the sketch."""

    def __init__(self, obj):
        obj.Proxy = self
        add = obj.addProperty
        add("App::PropertyBool", "SWCurve", "Base", "A FreeCAD curve")
        obj.setEditorMode("SWCurve", 2)
        obj.SWCurve = True
        add("App::PropertyLink", "Sketch", "Helix/Spiral", "The sketch with the circle")
        add("App::PropertyEnumeration", "DefinedBy", "Helix/Spiral", "Defined By")
        obj.DefinedBy = DEFINED_BY
        add("App::PropertyBool", "VariablePitch", "Helix/Spiral", "Variable pitch (the region table)")
        add("App::PropertyLength", "Pitch", "Helix/Spiral", "Pitch")
        add("App::PropertyFloat", "Revolutions", "Helix/Spiral", "Revolutions")
        add("App::PropertyLength", "Height", "Helix/Spiral", "Height")
        add("App::PropertyBool", "Reverse", "Helix/Spiral", "Reverse direction")
        add("App::PropertyAngle", "StartAngle", "Helix/Spiral", "Start angle")
        add("App::PropertyBool", "Clockwise", "Helix/Spiral", "Clockwise (else Counterclockwise)")
        add("App::PropertyBool", "TaperHelix", "Taper Helix", "Taper Helix")
        add("App::PropertyAngle", "TaperAngle", "Taper Helix", "Taper angle")
        add("App::PropertyBool", "TaperOutward", "Taper Helix", "Taper outward")
        add("App::PropertyFloatList", "RegionRevolutions", "Region parameters", "Rev of each row")
        add("App::PropertyFloatList", "RegionPitch", "Region parameters", "P of each row")
        add("App::PropertyFloatList", "RegionDiameter", "Region parameters", "Dia of each row")
        obj.Pitch, obj.Revolutions, obj.Height = 5.0, 4.0, 20.0

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def regions(self, obj):
        rows = list(zip(obj.RegionRevolutions, obj.RegionPitch, obj.RegionDiameter))
        return rows if obj.VariablePitch and len(rows) >= 2 else None

    def execute(self, obj):
        import Part
        sk = obj.Sketch
        if sk is None:
            obj.Shape = Part.Shape()
            return
        centre, radius = _circle_of(sk)
        revs, height, pitch = helix_size(obj)
        regions = self.regions(obj)
        if regions:
            revs = max(r[0] for r in regions)
        pts = helix_points(radius, revs, pitch, obj.StartAngle.Value, obj.Clockwise, obj.Reverse,
                           obj.TaperAngle.Value if obj.TaperHelix else 0.0, obj.TaperOutward,
                           obj.DefinedBy == "Spiral", regions)
        frame = sk.getGlobalPlacement().multiply(App.Placement(centre, App.Rotation()))
        if not regions and obj.DefinedBy != "Spiral" and not (obj.TaperHelix and obj.TaperAngle.Value):
            # (OpenCascade's tapered helix measures its height along the cone and only widens:
            # a tapered one stays on the drawn points)
            wire = exact_helix(radius, revs, pitch, obj.StartAngle.Value, obj.Clockwise, obj.Reverse,
                               0.0, False, frame)
            ends = [frame.multVec(pts[0]), frame.multVec(pts[-1])]
            # the exact one, when it starts and ends where the drawn points do
            if wire is not None and wire.Vertexes and \
                    min(v.Point.distanceToPoint(ends[0]) for v in wire.Vertexes) < 1e-6 * max(radius, 1.0) and \
                    min(v.Point.distanceToPoint(ends[1]) for v in wire.Vertexes) < 1e-4 * max(radius, 1.0):
                obj.Shape = wire
                return
        pts = [frame.multVec(p) for p in pts]
        curve = Part.BSplineCurve()
        curve.interpolate(pts)
        obj.Shape = curve.toShape()


def make_helix(sketch, **values):
    doc = sketch.Document
    obj = doc.addObject("Part::FeaturePython", "Helix")
    Helix(obj)
    if App.GuiUp:
        from .curves import _CurveView
        _CurveView(obj.ViewObject)
    from . import naming
    obj.Label = naming.next_label(doc, "Helix/Spiral")
    obj.Sketch = sketch
    for k, v in values.items():
        setattr(obj, k, v)
    doc.recompute()
    return obj


class HelixPM(PM):
    TITLE = "Helix/Spiral"
    ICON = "CURVES_HELIX"

    def __init__(self, doc, picks=(), obj=None):
        super().__init__(doc)
        self.obj = obj
        box, lay = self.group("Defined By", "SWHelixDefinedBy")
        self.sketch = self.pick_box("SWHelixSketch", ("sketch", "circle"))
        lay.addWidget(self.sketch)
        self.by = QtWidgets.QComboBox()
        self.by.setObjectName("SWHelixDefinedByCombo")
        self.by.addItems(DEFINED_BY)
        lay.addWidget(self.by)
        box, lay = self.group("Parameters", "SWHelixParameters")
        pl = QtWidgets.QHBoxLayout()
        self.constant = QtWidgets.QRadioButton("Constant pitch")
        self.constant.setObjectName("SWHelixConstant")
        self.variable = QtWidgets.QRadioButton("Variable pitch")
        self.variable.setObjectName("SWHelixVariable")
        self.constant.setChecked(True)
        self._pitch_group = QtWidgets.QButtonGroup(box)
        self._pitch_group.addButton(self.constant)
        self._pitch_group.addButton(self.variable)
        pl.addWidget(self.constant)
        pl.addWidget(self.variable)
        lay.addLayout(pl)
        self.table = QtWidgets.QTableWidget(2, 3)
        self.table.setObjectName("SWHelixRegions")
        self.table.setHorizontalHeaderLabels(["P", "Rev", "Dia"])
        self.table.setFixedHeight(110)
        lay.addWidget(self.table)
        self.height = _spin(20.0, 0.001, 1e6, " mm", name="SWHelixHeight")
        self.height_label = _row(lay, "Height", self.height)
        self.pitch = _spin(5.0, 0.001, 1e6, " mm", name="SWHelixPitch")
        self.pitch_label = _row(lay, "Pitch", self.pitch)
        from . import evaluate
        for w in (self.height, self.pitch):
            evaluate.unit_spin(w)
        self.revs = _spin(4.0, 0.01, 1e5, "", 3, name="SWHelixRevolutions")
        self.revs_label = _row(lay, "Revolutions", self.revs)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        self.reverse.setObjectName("SWHelixReverse")
        lay.addWidget(self.reverse)
        self.start_angle = _spin(0.0, -360, 360, "°", 2, name="SWHelixStartAngle")
        _row(lay, "Start angle", self.start_angle)
        rl = QtWidgets.QHBoxLayout()
        self.cw = QtWidgets.QRadioButton("Clockwise")
        self.cw.setObjectName("SWHelixClockwise")
        self.ccw = QtWidgets.QRadioButton("Counterclockwise")
        self.ccw.setObjectName("SWHelixCounterclockwise")
        self.ccw.setChecked(True)
        self._turn_group = QtWidgets.QButtonGroup(box)
        self._turn_group.addButton(self.cw)
        self._turn_group.addButton(self.ccw)
        rl.addWidget(self.cw)
        rl.addWidget(self.ccw)
        lay.addLayout(rl)
        tbox, tlay = self.group("Taper Helix", "SWHelixTaper")
        self.taper = QtWidgets.QCheckBox("Taper Helix")
        self.taper.setObjectName("SWHelixTaperOn")
        tlay.addWidget(self.taper)
        self.taper_angle = _spin(5.0, 0.0, 89.0, "°", 2, name="SWHelixTaperAngle")
        self.taper_label = _row(tlay, "Taper angle", self.taper_angle)
        self.outward = QtWidgets.QCheckBox("Taper outward")
        self.outward.setObjectName("SWHelixTaperOutward")
        tlay.addWidget(self.outward)
        if obj is not None:
            self._load(obj)
        for w in (self.height, self.pitch, self.revs, self.start_angle, self.taper_angle):
            w.valueChanged.connect(self.changed)
        for w in (self.reverse, self.cw, self.variable, self.taper, self.outward):
            w.toggled.connect(self.changed)
        self.by.currentIndexChanged.connect(self.changed)
        self.table.itemChanged.connect(self.changed)
        self.start(picks)

    def _load(self, obj):
        self.made = [obj]
        if obj.Sketch is not None:
            self.sketch.items = [(obj.Sketch, "")]
            self.sketch.show_items()
        self.by.setCurrentText(obj.DefinedBy)
        from . import evaluate
        self.height.setValue(evaluate.in_doc(obj.Height.Value))
        self.pitch.setValue(evaluate.in_doc(obj.Pitch.Value))
        self.revs.setValue(obj.Revolutions)
        self.reverse.setChecked(obj.Reverse)
        self.start_angle.setValue(obj.StartAngle.Value)
        (self.cw if obj.Clockwise else self.ccw).setChecked(True)
        self.variable.setChecked(obj.VariablePitch)
        self.taper.setChecked(obj.TaperHelix)
        self.taper_angle.setValue(obj.TaperAngle.Value)
        self.outward.setChecked(obj.TaperOutward)
        rows = list(zip(obj.RegionPitch, obj.RegionRevolutions, obj.RegionDiameter))
        if rows:
            self.table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                for j, v in enumerate(row):
                    self.table.setItem(i, j, QtWidgets.QTableWidgetItem(_region_text(j, v)))

    def _sketch(self):
        item = self.sketch.first()
        if item is None:
            return None
        obj, sub = item
        return obj if obj.isDerivedFrom("Sketcher::SketchObject") else None

    def _regions(self):
        rows = []
        for i in range(self.table.rowCount()):
            vals = []
            for j in range(3):
                it = self.table.item(i, j)
                try:
                    vals.append(_region_value(j, it.text()))
                except Exception:
                    vals.append(None)
            if None not in vals:
                rows.append(vals)
        return rows

    def layout_rows(self):
        by = self.by.currentText()
        spiral = by == "Spiral"
        variable = self.variable.isChecked() and not spiral
        self.table.setVisible(variable)

        show = {"Pitch and Revolution": ("pitch", "revs"), "Height and Revolution": ("height", "revs"),
                "Height and Pitch": ("height", "pitch"), "Spiral": ("pitch", "revs")}[by]
        for key, w, l in (("height", self.height, self.height_label), ("pitch", self.pitch, self.pitch_label),
                          ("revs", self.revs, self.revs_label)):
            on = key in show and not (variable and key != "height" and by != "Height and Pitch")
            w.setVisible(on)
            l.setVisible(on)
        self.constant.setVisible(not spiral)
        self.variable.setVisible(not spiral)
        self.taper.setVisible(not spiral)
        self.taper_angle.setVisible(self.taper.isChecked() and not spiral)
        self.taper_label.setVisible(self.taper.isChecked() and not spiral)
        self.outward.setVisible(self.taper.isChecked() and not spiral)
        if variable and self._sketch() is not None:

            try:
                from . import evaluate
                _c, r = _circle_of(self._sketch())
                if all(self.table.item(i, 0) is None for i in range(self.table.rowCount())):
                    self.table.blockSignals(True)
                    for i, rev in enumerate((0.0, max(1.0, self.revs.value()))):
                        for j, v in enumerate((evaluate.mm_of(self.pitch), rev, 2 * r)):
                            self.table.setItem(i, j, QtWidgets.QTableWidgetItem(_region_text(j, v)))
                    self.table.blockSignals(False)
            except Exception as _fw_err:
                _fw_log("refgeom2.py:1219", _fw_err)

    def build(self):
        sk = self._sketch()
        if sk is None:
            raise RuntimeError("Select a sketch with one circle.")
        _circle_of(sk)
        if self.obj is None:
            self.obj = make_helix(sk)
            self.made = [self.obj]
        o = self.obj
        o.Sketch = sk
        o.DefinedBy = self.by.currentText()
        from . import evaluate
        o.Height, o.Pitch, o.Revolutions = evaluate.mm_of(self.height), evaluate.mm_of(self.pitch), self.revs.value()
        o.Reverse = self.reverse.isChecked()
        o.StartAngle = self.start_angle.value()
        o.Clockwise = self.cw.isChecked()
        o.VariablePitch = self.variable.isChecked()
        rows = self._regions()
        o.RegionPitch = [r[0] for r in rows]
        o.RegionRevolutions = [r[1] for r in rows]
        o.RegionDiameter = [r[2] for r in rows]
        o.TaperHelix = self.taper.isChecked()
        o.TaperAngle = self.taper_angle.value()
        o.TaperOutward = self.outward.isChecked()
        self.doc.recompute()
        if "Invalid" in o.State:
            raise RuntimeError("The helix cannot be made with these values.")

    def finish(self):
        sk = self._sketch()
        if sk is not None and App.GuiUp:
            try:
                sk.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("refgeom2.py:1254", _fw_err)


# =========================================================================== Projected Curve
PROJECT_TYPES = ["Sketch on faces", "Sketch on sketch"]


def _sketch_dir(sk):
    return sk.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))


def project_on_faces(sketch, faces, reverse=False, both=False):
    """The sketch's curves projected onto the faces along the sketch's normal."""
    pl = sketch.getGlobalPlacement()
    d = _sketch_dir(sketch)
    if reverse:
        d = d * -1
    out = []
    for face in faces:
        for edge in sketch.Shape.Edges:
            try:
                found = face.makeParallelProjection(edge, d).Edges
            except Exception:
                continue
            if not both:
                found = [e for e in found
                         if (e.valueAt((e.FirstParameter + e.LastParameter) / 2) - pl.Base).dot(d) >= -1e-6]
            out += found
    return out


def project_sketch_on_sketch(a, b):
    """Where the two sketches' curves, each drawn out along its own normal, cross: the 3D curve."""
    size = max(a.Shape.BoundBox.DiagonalLength, b.Shape.BoundBox.DiagonalLength, 1.0) * 4
    sheets = []
    for sk in (a, b):
        d = _sketch_dir(sk)
        faces = []
        for e in sk.Shape.Edges:
            moved = e.copy()
            moved.translate(d * -size)
            faces.append(moved.extrude(d * (2 * size)))
        import Part
        sheets.append(Part.makeCompound(faces))
    return sheets[0].section(sheets[1]).Edges


class ProjectedCurve:
    def __init__(self, obj):
        obj.Proxy = self
        add = obj.addProperty
        add("App::PropertyBool", "SWCurve", "Base", "A FreeCAD curve")
        obj.setEditorMode("SWCurve", 2)
        obj.SWCurve = True
        add("App::PropertyEnumeration", "ProjectionType", "Projected Curve", "Sketch on faces or Sketch on sketch")
        obj.ProjectionType = PROJECT_TYPES
        add("App::PropertyLink", "Sketch", "Projected Curve", "Sketch to project")
        add("App::PropertyLink", "Sketch2", "Projected Curve", "The second sketch (Sketch on sketch)")
        add("App::PropertyLinkSubListGlobal", "Faces", "Projected Curve", "Projection faces")
        add("App::PropertyBool", "Reverse", "Projected Curve", "Reverse projection")
        add("App::PropertyBool", "BiDirectional", "Projected Curve", "Bi-directional")

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        import Part
        edges = []
        if obj.ProjectionType == "Sketch on sketch":
            if obj.Sketch is not None and obj.Sketch2 is not None:
                edges = project_sketch_on_sketch(obj.Sketch, obj.Sketch2)
        elif obj.Sketch is not None:
            faces = []
            for src, subs in obj.Faces:
                for s in subs:
                    try:
                        faces.append(src.Shape.getElement(s))
                    except Exception as _fw_err:
                        _fw_log("refgeom2.py:1335", _fw_err)
            edges = project_on_faces(obj.Sketch, faces, obj.Reverse, obj.BiDirectional)
        obj.Shape = Part.Compound(edges) if edges else Part.Shape()


def make_projected_curve(doc, kind, sketch, faces=(), sketch2=None, reverse=False, both=False):
    obj = doc.addObject("Part::FeaturePython", "ProjectedCurve")
    ProjectedCurve(obj)
    if App.GuiUp:
        from .curves import _CurveView
        _CurveView(obj.ViewObject)
    from . import naming
    obj.Label = naming.next_label(doc, "Curve")
    obj.ProjectionType = kind
    obj.Sketch, obj.Sketch2 = sketch, sketch2
    obj.Faces = [(o, [s]) for o, s in faces]
    obj.Reverse, obj.BiDirectional = reverse, both
    doc.recompute()
    return obj


class ProjectedCurvePM(PM):
    TITLE = "Projected Curve"
    ICON = "CURVES_PROJECTED"

    def __init__(self, doc, picks=(), obj=None):
        super().__init__(doc)
        self.obj = obj
        if obj is not None:
            self.made = [obj]
        box, lay = self.group("Selections", "SWProjectedSelections")
        tl = QtWidgets.QVBoxLayout()
        self.types = {}
        tg = QtWidgets.QButtonGroup(box)
        for t in PROJECT_TYPES:
            r = QtWidgets.QRadioButton(t)
            r.setObjectName("SWProjected" + t.title().replace(" ", ""))
            tg.addButton(r)
            tl.addWidget(r)
            self.types[t] = r
            r.toggled.connect(self.changed)
        lay.addLayout(tl)
        self.sketch = self.pick_box("SWProjectedSketch", ("sketch",))
        self.sketch_label = QtWidgets.QLabel("Sketch to Project")
        lay.addWidget(self.sketch_label)
        lay.addWidget(self.sketch)
        self.faces_label = QtWidgets.QLabel("Projection Faces")
        lay.addWidget(self.faces_label)
        self.faces = self.pick_box("SWProjectedFaces", ("plane", "face"), many=True, height=56)
        lay.addWidget(self.faces)
        self.sketch2_label = QtWidgets.QLabel("Sketches to project")
        lay.addWidget(self.sketch2_label)
        self.sketch2 = self.pick_box("SWProjectedSketch2", ("sketch",))
        lay.addWidget(self.sketch2)
        self.reverse = QtWidgets.QCheckBox("Reverse projection")
        self.reverse.setObjectName("SWProjectedReverse")
        lay.addWidget(self.reverse)
        self.both = QtWidgets.QCheckBox("Bi-directional")
        self.both.setObjectName("SWProjectedBiDirectional")
        lay.addWidget(self.both)
        self.reverse.toggled.connect(self.changed)
        self.both.toggled.connect(self.changed)
        sketches = [p for p in picks if element_kind(*p) == "sketch"]
        if obj is not None:
            # Edit Feature: the page as the curve was made
            self.types[obj.ProjectionType].setChecked(True)
            if obj.Sketch is not None:
                self.sketch.items = [(obj.Sketch, "")]
                self.sketch.show_items()
            if obj.Sketch2 is not None:
                self.sketch.items = self.sketch.items[:1] + [(obj.Sketch2, "")]
                self.sketch.show_items()
            self.faces.items = [(o, s) for o, subs in obj.Faces for s in subs]
            self.faces.show_items()
            self.reverse.setChecked(bool(obj.Reverse))
            self.both.setChecked(bool(obj.BiDirectional))
        else:
            self.types["Sketch on sketch" if len(sketches) >= 2 else "Sketch on faces"].setChecked(True)
        self.start(picks)

    def kind(self):
        return next(t for t, r in self.types.items() if r.isChecked())

    def layout_rows(self):
        ""

        on_faces = self.kind() == "Sketch on faces"
        for w in (self.faces_label, self.faces, self.reverse, self.both):
            w.setVisible(on_faces)
        self.sketch2_label.setVisible(False)
        self.sketch2.setVisible(False)
        if self.sketch2.items:          # an older page's second box: its sketch goes in the one box
            self.sketch.items = self.sketch.items[:1] + self.sketch2.items[:1]
            self.sketch2.items = []
        self.sketch.many = not on_faces
        if on_faces and len(self.sketch.items) > 1:
            self.sketch.items = self.sketch.items[:1]
        elif len(self.sketch.items) > 2:
            self.sketch.items = self.sketch.items[-2:]
        self.sketch.show_items()
        self.sketch.setFixedHeight(26 if on_faces else 44)
        self.sketch_label.setText("Sketch to Project" if on_faces else "Sketches to Project")

    def _second(self):
        return self.sketch.items[1] if len(self.sketch.items) > 1 else None

    def build(self):
        kind = self.kind()
        sk = self.sketch.first()
        if sk is None:
            raise RuntimeError("Select a sketch to project.")
        if kind == "Sketch on faces" and not self.faces.items:
            raise RuntimeError("Select the faces to project the sketch onto.")
        if kind == "Sketch on sketch" and self._second() is None:
            raise RuntimeError("Select the second sketch.")
        if self.obj is None:
            self.obj = make_projected_curve(self.doc, kind, sk[0])
            self.made = [self.obj]
        o = self.obj
        o.ProjectionType = kind
        o.Sketch = sk[0]
        o.Sketch2 = self._second()[0] if kind == "Sketch on sketch" and self._second() else None
        o.Faces = [(ob, [s]) for ob, s in self.faces.items if s]
        o.Reverse, o.BiDirectional = self.reverse.isChecked(), self.both.isChecked()
        self.doc.recompute()
        if o.Shape.isNull() or not o.Shape.Edges:
            raise RuntimeError("The sketch does not fall on the faces. Try Reverse projection or Bi-directional."
                               if kind == "Sketch on faces" else "The two sketches do not cross.")

    def finish(self):
        if App.GuiUp:
            for b in (self.sketch, self.sketch2):
                for item in b.items:
                    try:
                        item[0].ViewObject.Visibility = False
                    except Exception as _fw_err:
                        _fw_log("refgeom2.py:1454", _fw_err)


# =========================================================================== Bounding Box
class BoundingBoxPM(PM):
    TITLE = "Bounding Box"
    ICON = "REFGEO_BOUNDING_BOX"

    def __init__(self, doc, obj=None, picks=()):
        super().__init__(doc)
        from . import curves
        self.obj = obj
        if self.obj is None:
            self.obj = curves.new_bounding_box(doc)
        self.made = [self.obj]
        curves.ensure_box_props(self.obj)

        tbox, tlay = self.group("Type of Bounding Box", "SWBoxType")
        self.rect = QtWidgets.QRadioButton("Rectangular")
        self.rect.setObjectName("SWBoxRectangular")
        self.cyl = QtWidgets.QRadioButton("Cylindrical")
        self.cyl.setObjectName("SWBoxCylindrical")
        self.cyl.setToolTip("The smallest cylinder round the part (Custom Plane: standing on the plane)")
        tlay.addWidget(self.rect)
        tlay.addWidget(self.cyl)
        box, lay = self.group("Reference Face/Plane", "SWBoxReference")
        self.best = QtWidgets.QRadioButton("Best Fit")
        self.best.setObjectName("SWBoxBestFit")
        self.custom = QtWidgets.QRadioButton("Custom Plane")
        self.custom.setObjectName("SWBoxCustomPlane")
        lay.addWidget(self.best)
        lay.addWidget(self.custom)
        self.plane = self.pick_box("SWBoxPlane", ("plane",))
        lay.addWidget(self.plane)

        self.by_csys = QtWidgets.QRadioButton("Coordinate System")
        self.by_csys.setObjectName("SWBoxCoordinateSystem")
        lay.addWidget(self.by_csys)
        self.csys = self.pick_box("SWBoxCoordinateSystemPick", ("csys",))
        lay.addWidget(self.csys)
        self.fix = QtWidgets.QCheckBox("Fix directions")
        self.fix.setObjectName("SWBoxFixDirections")
        self.fix.setToolTip("Length, Width and Thickness stay on the X, Y and Z axes when the sizes change")
        lay.addWidget(self.fix)
        obox, olay = self.group("Options", "SWBoxOptions")
        self.hidden = QtWidgets.QCheckBox("Include hidden bodies")
        self.hidden.setObjectName("SWBoxIncludeHidden")
        self.surfaces = QtWidgets.QCheckBox("Include surfaces")
        self.surfaces.setObjectName("SWBoxIncludeSurfaces")
        self.preview = QtWidgets.QCheckBox("Show Preview")
        self.preview.setObjectName("SWBoxShowPreview")
        for w in (self.hidden, self.surfaces, self.preview):
            olay.addWidget(w)
        o = self.obj
        {"Custom Plane": self.custom, "Coordinate System": self.by_csys}.get(o.Reference, self.best).setChecked(True)
        if getattr(o, "CoordSystem", None) is not None:
            self.csys.items = [(o.CoordSystem, "")]
            self.csys.show_items()
        self.fix.setChecked(bool(getattr(o, "FixDirections", False)))
        (self.cyl if getattr(o, "BoxType", "Rectangular") == "Cylindrical" else self.rect).setChecked(True)
        if o.Plane:
            self.plane.items = [(o.Plane[0], o.Plane[1][0] if o.Plane[1] else "")]
            self.plane.show_items()
        self.hidden.setChecked(o.IncludeHidden)
        self.surfaces.setChecked(o.IncludeSurfaces)
        self.preview.setChecked(True)
        for w in (self.best, self.custom, self.by_csys, self.fix, self.rect, self.cyl, self.hidden, self.surfaces, self.preview):
            w.toggled.connect(self.changed)
        self.start(picks)

    def layout_rows(self):
        self.plane.setVisible(self.custom.isChecked())
        self.csys.setVisible(self.by_csys.isChecked())

    def build(self):
        o = self.obj
        o.Reference = "Custom Plane" if self.custom.isChecked() else \
            "Coordinate System" if self.by_csys.isChecked() else "Best Fit"
        item = self.plane.first()
        o.Plane = (item[0], [item[1]] if item[1] else []) if item else None
        cs = self.csys.first()
        o.CoordSystem = cs[0] if cs else None
        o.FixDirections = self.fix.isChecked()
        if self.by_csys.isChecked() and cs is None:
            self.doc.recompute()
            raise RuntimeError("Select a coordinate system for the box's directions.")
        o.IncludeHidden = self.hidden.isChecked()
        o.IncludeSurfaces = self.surfaces.isChecked()
        o.BoxType = "Cylindrical" if self.cyl.isChecked() else "Rectangular"
        from . import curves
        curves.watch_bodies(o)
        self.doc.recompute()
        if App.GuiUp:
            try:
                o.ViewObject.Visibility = self.preview.isChecked()
            except Exception as _fw_err:
                _fw_log("refgeom2.py:1547", _fw_err)
        if self.custom.isChecked() and item is None:
            raise RuntimeError("Select a plane or flat face for the box to sit on.")
        if o.Shape.isNull():
            raise RuntimeError("There is no body to box.")

    def finish(self):
        if App.GuiUp:
            try:
                self.obj.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("refgeom2.py:1558", _fw_err)
        try:
            add_box_properties(self.doc)
        except Exception as _fw_err:
            _fw_log("refgeom2.py:box_props", _fw_err)

    def done_text(self):
        o = self.obj
        if getattr(o, "BoxType", "Rectangular") == "Cylindrical":
            return "Ø%.2f x %.2f mm" % (o.CylinderDiameter.Value, o.CylinderLength.Value)
        return "%.2f x %.2f x %.2f mm" % (o.BoxLength.Value, o.BoxWidth.Value, o.BoxHeight.Value)


def add_box_properties(doc):
    ""


    from . import customprops, fileprops
    for config in fileprops.configurations(doc):
        rows = list(fileprops.read_config(doc, config))
        have = {n.lower() for n, _k, _v in rows}
        new = [(name, "Text", '$PRP:"%s"' % name) for name in customprops.BOX_LINKS if name.lower() not in have]
        if new:
            fileprops.write_config(doc, config, rows + new)


# =========================================================================== commands
def _picks(doc):
    try:
        return refplane._picks_before(doc)
    except Exception:
        return []


def _show(make):
    doc = App.ActiveDocument
    if doc is None or Gui.Control.activeDialog():
        return None
    picks = _picks(doc)
    panel = make(doc, picks)
    Gui.Control.showDialog(panel)
    return panel


def coordinate_system():
    return _show(lambda d, p: CoordinateSystemPM(d, p))


def point():
    return _show(lambda d, p: PointPM(d, p))


def helix():
    return _show(lambda d, p: HelixPM(d, p))


def projected_curve():
    return _show(lambda d, p: ProjectedCurvePM(d, p))


def bounding_box():
    from . import curves
    doc = App.ActiveDocument
    if doc is None or Gui.Control.activeDialog():
        return None
    old = curves.existing_bounding_box(doc)
    panel = BoundingBoxPM(doc, old, _picks(doc))
    Gui.Control.showDialog(panel)
    return panel


def edit(obj):
    """Edit Feature on a helix: its PropertyManager again."""
    if type(getattr(obj, "Proxy", None)).__name__ == "Helix" and not Gui.Control.activeDialog():
        panel = HelixPM(obj.Document, (), obj)
        Gui.Control.showDialog(panel)
        return panel
    return None


COMMANDS = {
    "SWStyle_RefCoordinateSystem": ("Coordinate System", "Adds a reference coordinate system.",
                                    "PartDesign_CoordinateSystem", coordinate_system),
    "SWStyle_RefPoint": ("Point", "Adds a reference point.", "PartDesign_Point", point),
    "SWStyle_HelixSpiral": ("Helix/Spiral", "Makes a helix or spiral on a sketch circle.", "Part_Helix_Parametric", helix),
    "SWStyle_ProjectedCurve": ("Projected Curve", "Projects a sketch onto faces, or two sketches into one 3D curve.",
                               "Part_ProjectionOnSurface", projected_curve),
}


class _Cmd:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        menu, tip, pixmap, _fn = COMMANDS[self.name]
        return {"MenuText": menu, "ToolTip": tip, "Pixmap": pixmap}

    def Activated(self):
        QtCore.QTimer.singleShot(0, COMMANDS[self.name][3])

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()


def install():
    try:
        for name in COMMANDS:
            if Gui.Command.get(name) is None:
                Gui.addCommand(name, _Cmd(name))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: reference geometry commands not added: %s\n" % error)
        return
    try:
        # Edit Feature on a helix opens its PropertyManager again
        from . import curves
        curves.EDITORS["Helix"] = edit
        curves.EDITORS["BoundingBox"] = lambda o: (None if Gui.Control.activeDialog() else
                                                   Gui.Control.showDialog(BoundingBoxPM(o.Document, o)))
        from . import curvepms
        curvepms.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: helix editing: %s\n" % error)
