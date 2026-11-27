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

from . import mirrorpm, patterns, pmboxes, pmvalues, refplane, simplefeature as sf


def _error_css():
    ""
    try:
        from . import propertymanager
        return propertymanager.error_css()
    except Exception:
        return "color: #c00000;"

NOT_YET = "Not in FreeCAD yet"
UP_TO_KINDS = ("ThroughAll", "UpToFace", "UpToLast", "UpToFirst")
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Patterns"

# icon column (2024 shots of Linear Pattern and Mirror: about 30 px in)
INDENT = 30


def _indented(lay):
    """A column inside lay, in line with the selection boxes."""
    col = QtWidgets.QVBoxLayout()
    col.setContentsMargins(INDENT, 0, 0, 0)
    lay.addLayout(col)
    return col


def _params():
    return App.ParamGet(PARAMS)


# --------------------------------------------------------------------------- directions
def own_edge(body, obj, sub):
    """An edge as (the feature that made it, its edge there), so a direction picked on the
    pattern's own result names the feature before it; None when the pattern itself made it."""
    import Part
    try:
        from . import contextbar
        owner = contextbar.owner_feature(obj, sub)
    except Exception:
        owner = obj
    if owner is None or owner is obj or owner not in mirrorpm.features_of(body):
        return (obj, sub)
    edge = obj.Shape.getElement(sub)
    a, b = edge.FirstParameter, edge.LastParameter
    points = [edge.valueAt(a + (b - a) * f) for f in (0.3, 0.5, 0.7)]
    for i, e in enumerate(owner.Shape.Edges):
        try:
            if type(e.Curve) is type(edge.Curve) and all(e.distToShape(Part.Vertex(p))[0] < 1e-6 for p in points):
                return (owner, "Edge%d" % (i + 1))
        except Exception:
            continue
    return (obj, sub)


def _usable(body, ref, pattern):
    """A reference made by the pattern itself (or later) would loop: refuse it."""
    if ref is None or pattern is None:
        return ref
    obj = ref[0]
    if obj is pattern:
        return None
    feats = mirrorpm.features_of(body)
    if obj in feats and pattern in feats and feats.index(obj) > feats.index(pattern):
        return None
    return ref


def _in_frame(body, obj, sub):
    """A pick on another body with its own placement as a reference in this body's coordinates
    (refplane.datum_ref: a hidden binder), so the pattern runs along the edge where it is."""
    dr = getattr(refplane, "datum_ref", None)
    return dr(obj, sub, body) if dr is not None and sub else (obj, sub)


def linear_direction(body, obj, sub):
    """A direction for a linear pattern from a pick, else None: a straight edge or axis, or a
    flat face or plane (its normal)."""
    obj, sub = _in_frame(body, obj, sub)
    kind = refplane.kind_of(obj, sub)
    if kind == "line":
        return own_edge(body, obj, sub) if sub else (obj, sub)
    if kind == "plane":
        if sub:
            return mirrorpm.own_face(body, obj, sub)
        return (obj, sub)
    return None


def circular_axis(body, obj, sub):
    """An axis for a circular pattern: a straight edge or axis, a round edge, or a round face
    (FreeCAD takes the axis from an edge, so one of the face's round edges)."""
    obj, sub = _in_frame(body, obj, sub)
    kind = refplane.kind_of(obj, sub)
    if kind == "line":
        return own_edge(body, obj, sub) if sub else (obj, sub)
    if kind == "curve" and sub:
        edge = obj.Shape.getElement(sub)
        if type(edge.Curve).__name__ == "Circle":
            return _origin_axis(body, edge.Curve.Center, edge.Curve.Axis) or own_edge(body, obj, sub)
        return None
    if kind == "cylinder" and sub:
        try:
            surf = obj.Shape.getElement(sub).Surface
            origin = _origin_axis(body, surf.Center, surf.Axis)
        except Exception:
            origin = None
        if origin is not None:
            return origin
        from . import refaxis
        try:
            return own_edge(body, obj, refaxis._round_edge(obj, sub))
        except Exception:
            return None
    return None


def _origin_axis(body, point, direction):
    """The body's X, Y or Z axis when the round face or edge picked is on it (a hub on Z). The pattern
    then holds on to the axis, not to an edge of a later feature whose name can be lost (Loft1:Edge5)."""
    try:
        for axis in body.Origin.OriginFeatures:
            if axis.Role not in ("X_Axis", "Y_Axis", "Z_Axis"):
                continue
            d = axis.Placement.Rotation.multVec(App.Vector(1, 0, 0))
            o = axis.Placement.Base
            if abs(abs(d.normalize().dot(App.Vector(direction).normalize())) - 1.0) > 1e-7:
                continue
            off = App.Vector(point) - o
            if (off - d * off.dot(d)).Length < 1e-6:
                return (axis, "")
    except Exception as _fw_err:
        _fw_log("patternpm.py:_origin_axis", _fw_err)
    return None


def _name(ref):
    obj, sub = ref
    return "%s@%s" % (sub, obj.Label) if sub else obj.Label


def _picked_name(body, obj, sub):
    ""

    if not sub.startswith("Face"):
        return None
    try:
        return _name(mirrorpm.own_face(body, obj, sub))
    except Exception:
        return _name((obj, sub))


# --------------------------------------------------------------------------- the pages
_current = None
PATTERN_TYPES = ("PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::Mirrored",
                 "PartDesign::MultiTransform")


def current():
    return _current


def _body_of(obj):
    for parent in getattr(obj, "InList", []):
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None



def _typing(spin):
    """The field holds typed text its value has not taken yet: a refresh must not wipe it
    (pkg106 real-use pass)."""
    try:
        edit = spin.lineEdit()
        return spin.hasFocus() and edit is not None and edit.isModified()
    except Exception:
        return False

class _Focus(QtCore.QObject):
    def __init__(self, panel, key):
        super().__init__()
        self.panel, self.key = panel, key

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            self.panel.active = self.key
            self.panel._show()
        return False


class _Escape(QtCore.QObject):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) and event.key() == QtCore.Qt.Key_Escape \
                and not (event.modifiers() & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)):
            if t == QtCore.QEvent.KeyPress and current() is self.panel:
                from . import pmkeys
                QtCore.QTimer.singleShot(0, lambda: pmkeys.when_idle(self.panel.reject))
            return True
        return False


class SkipDots(QtCore.QObject):
    ""



    RADIUS = 9          # px around a dot that a click takes
    PINK = (0.9, 0.1, 0.9)

    def __init__(self, sites, toggle):
        super().__init__()
        self.sites, self.toggle = sites, toggle
        self.root = self.view = None
        self.widgets, self.shown, self._eat = [], [], False
        coin = getattr(mirrorpm, "coin", None)
        if coin is None:
            return
        attached = None
        try:
            self.view = Gui.ActiveDocument.ActiveView
            self.root = coin.SoAnnotation()
            style = coin.SoPickStyle()
            style.style = coin.SoPickStyle.UNPICKABLE
            self.root.addChild(style)
            self.marks = coin.SoSeparator()
            self.root.addChild(self.marks)
            attached = self.view.getSceneGraph()
            attached.addChild(self.root)
            w = self.view.graphicsView().viewport()
            w.installEventFilter(self)
            self.widgets.append(w)
        except Exception as _fw_err:
            _fw_log("patternpm.py:SkipDots", _fw_err)
            # the view could not take the clicks: the node already in the scene goes too (Codex review b9)
            for w in self.widgets:
                try:
                    w.removeEventFilter(self)
                except Exception as _fw_err2:
                    _fw_log("patternpm.py:SkipDots.undo-filter", _fw_err2)
            self.widgets = []
            if attached is not None and self.root is not None:
                try:
                    attached.removeChild(self.root)
                except Exception as _fw_err2:
                    _fw_log("patternpm.py:SkipDots.undo-node", _fw_err2)
            self.root = None

    def show(self, on):
        if self.root is None:
            return
        from pivy import coin
        self.marks.removeAllChildren()
        self.shown = []
        if not on:
            return
        try:
            self.shown = [(k, p, bool(gone)) for k, p, gone in self.sites()]
        except Exception as _fw_err:
            _fw_log("patternpm.py:SkipDots.sites", _fw_err)
            return
        for gone, marker in ((False, "CIRCLE_FILLED_9_9"), (True, "CIRCLE_LINE_9_9")):
            points = [p for _k, p, g in self.shown if g == gone]
            if not points:
                continue
            group = coin.SoSeparator()
            colour = coin.SoBaseColor()
            colour.rgb = self.PINK
            group.addChild(colour)
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
            group.addChild(coords)
            marks = coin.SoMarkerSet()
            marks.markerIndex = getattr(coin.SoMarkerSet, marker)
            group.addChild(marks)
            self.marks.addChild(group)

    def at(self, widget, x, y):
        """The key of the dot under a viewport point (logical pixels, Qt's y), or None."""
        import math
        try:
            dpr = widget.devicePixelRatioF()
            best = None
            for key, p, _gone in self.shown:
                vx, vy = self.view.getPointOnViewport(p)
                d = math.hypot(vx / dpr - x, widget.height() - vy / dpr - y)
                if d <= self.RADIUS and (best is None or d < best[0]):
                    best = (d, key)
            return best and best[1]
        except Exception as _fw_err:
            _fw_log("patternpm.py:SkipDots.at", _fw_err)
            return None

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress and self.shown and event.button() == QtCore.Qt.LeftButton \
                and not (event.modifiers() & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)):
            pos = event.position() if hasattr(event, "position") else event.pos()
            key = self.at(watched, pos.x(), pos.y())
            if key is not None:
                self._eat = True
                QtCore.QTimer.singleShot(0, lambda: self.toggle(key))
                return True
        elif t in (QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick) and self._eat:
            if t == QtCore.QEvent.MouseButtonRelease:
                self._eat = False
            return True         # the press went to a dot: no pick, no box select
        return False

    def remove(self):
        for w in self.widgets:
            try:
                w.removeEventFilter(self)
            except Exception as _fw_err:
                _fw_log("patternpm.py:SkipDots.remove", _fw_err)
        self.widgets, self.shown = [], []
        if self.root is not None:
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("patternpm.py:SkipDots.remove2", _fw_err)
            self.root = None


def _greyed(text, parent):
    w = QtWidgets.QCheckBox(text, parent)
    w.setEnabled(False)
    w.setToolTip(NOT_YET)
    return w


class _DirectionBox(QtWidgets.QWidget):
    """Direction 1 / 2 (or the Pattern Axis): the pick, Reverse, the spacing or angle and the count."""

    def __init__(self, panel, key, title, circular=False, optional=False):
        super().__init__()
        self.panel, self.key = panel, key
        n = key[-1]
        self.circular = circular
        self.setWindowTitle(title)
        lay = QtWidgets.QVBoxLayout(self)
        if optional:
            self.use = QtWidgets.QCheckBox("Use " + title, self)
            self.use.setObjectName("SWPattern%sOn" % key.title())
            self.use.toggled.connect(lambda on: panel.set_use(key, on))
            lay.addWidget(self.use)
        else:
            self.use = None
            self.compat = None
            if key == "dir2":

                # Linear Direction 2 has none (a picked direction is the second direction)
                compat = QtWidgets.QCheckBox("Use " + title, self)
                compat.setObjectName("SWPatternDir2On")
                compat.toggled.connect(lambda on: panel.set_use(key, on))
                compat.hide()
                self.compat = compat
        self.symmetric = None
        if key == "dir2":
            self.symmetric = QtWidgets.QCheckBox("Symmetric", self)
            self.symmetric.setObjectName("SWPatternSymmetric")
            self.symmetric.setToolTip("The same instances the other way round the axis" if circular else
                                      "The Direction 1 instances the other way from the seed too")
            self.symmetric.toggled.connect(lambda on: panel.set_value(key, "symmetric", on))
            lay.addWidget(self.symmetric)
        row = QtWidgets.QHBoxLayout()
        self.reverse = QtWidgets.QToolButton(self)
        self.reverse.setObjectName("SWPatternReverse" + n)
        self.reverse.setIcon(pmvalues.reverse_icon())
        self.reverse.setIconSize(QtCore.QSize(16, 16))
        self.reverse.setToolTip("Reverse Direction")
        self.reverse.setCheckable(True)
        self.reverse.toggled.connect(lambda on: panel.set_value(key, "reverse", on))
        row.addWidget(self.reverse)
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("SWPatternDirection" + n)
        self.list.setFixedHeight(26)
        self.list.installEventFilter(self)
        pmboxes.bind(self.list, lambda row, p=panel, k=key: p.remove_item(k, row), lambda p=panel, k=key: p.clear_items(k))
        row.addWidget(self.list)
        if circular and key == "dir2":
            # the second circular direction shares the axis: no pick of its own
            self.reverse.hide()
            self.list.hide()
        lay.addLayout(row)
        self.equal = None
        self.up_to = None
        if circular:
            self.instance_spacing = QtWidgets.QRadioButton("Instance spacing", self)
            self.instance_spacing.setObjectName("SWPatternInstanceSpacing" + n)
            self.equal = QtWidgets.QRadioButton("Equal spacing", self)
            self.equal.setObjectName("SWPatternEqualSpacing" + n)
            self.equal.toggled.connect(lambda on: panel.set_value(key, "equal", on))
            col = _indented(lay)
            col.addWidget(self.instance_spacing)
            col.addWidget(self.equal)
        else:
            self.spacing_mode = QtWidgets.QRadioButton("Spacing and instances", self)
            self.spacing_mode.setObjectName("SWPatternSpacingAndInstances" + n)
            self.spacing_mode.setChecked(True)
            self.up_to = QtWidgets.QRadioButton("Up to reference", self)
            self.up_to.setObjectName("SWPatternUpToReference" + n)
            self.up_to.setToolTip("The instances reach a picked vertex, edge or face: the spacing follows")
            self.up_to.toggled.connect(lambda on: panel.set_value(key, "upto", on))
            col = _indented(lay)
            col.addWidget(self.spacing_mode)
            col.addWidget(self.up_to)
            ref_row = QtWidgets.QHBoxLayout()
            ref_row.addWidget(QtWidgets.QLabel("Reference:", self))
            self.ref_list = QtWidgets.QListWidget(self)
            self.ref_list.setObjectName("SWPatternUpTo" + n)
            self.ref_list.setFixedHeight(26)
            self.ref_list.setToolTip("Pick the vertex, edge or face the last instance reaches")
            self.ref_list.installEventFilter(self)
            pmboxes.bind(self.ref_list, lambda row, p=panel, k="upto" + n: p.remove_item(k, row), lambda p=panel, k="upto" + n: p.clear_items(k))
            ref_row.addWidget(self.ref_list)
            self.ref_widget = QtWidgets.QWidget(self)
            ref_lay = QtWidgets.QVBoxLayout(self.ref_widget)
            ref_lay.setContentsMargins(0, 0, 0, 0)
            ref_lay.addLayout(ref_row)

            # reference, which point of the seed is measured, and what the reach sets
            off_row = QtWidgets.QHBoxLayout()
            off_row.addWidget(QtWidgets.QLabel("Offset distance:", self))
            from .pmspin import TrimSpin
            self.offset = TrimSpin(self)
            self.offset.setObjectName("SWPatternOffset" + n)
            self.offset.setDecimals(3)
            self.offset.setRange(0.0, 1e6)
            self.offset.setSuffix(" mm")
            self.offset.setKeyboardTracking(False)
            self.offset.setToolTip("How far before the reference the last instance stops")
            self.offset.valueChanged.connect(lambda v: panel.set_value(key, "offset", v))
            off_row.addWidget(self.offset)
            ref_lay.addLayout(off_row)
            self.reverse_offset = QtWidgets.QCheckBox("Reverse offset", self)
            self.reverse_offset.setObjectName("SWPatternReverseOffset" + n)
            self.reverse_offset.setToolTip("The last instance stops past the reference by the offset")
            self.reverse_offset.toggled.connect(lambda on: panel.set_value(key, "reverse_offset", on))
            ref_lay.addWidget(self.reverse_offset)
            self.ref_centroid = QtWidgets.QRadioButton("Centroid", self)
            self.ref_centroid.setObjectName("SWPatternRefCentroid" + n)
            self.ref_centroid.setToolTip("The reach is measured from the seed's centroid")
            self.ref_selected = QtWidgets.QRadioButton("Selected reference", self)
            self.ref_selected.setObjectName("SWPatternRefSelected" + n)
            self.ref_selected.setToolTip("The reach is measured from a vertex or edge of the seed")
            self.ref_selected.toggled.connect(lambda on: panel.set_value(key, "ref_from", on))
            self.ref_group = QtWidgets.QButtonGroup(self)
            self.ref_group.addButton(self.ref_centroid)
            self.ref_group.addButton(self.ref_selected)
            self.ref_centroid.setChecked(True)
            ref_lay.addWidget(QtWidgets.QLabel("Seed reference:", self))
            ref_lay.addWidget(self.ref_centroid)
            ref_lay.addWidget(self.ref_selected)
            seed_row = QtWidgets.QHBoxLayout()
            self.seed_list = QtWidgets.QListWidget(self)
            self.seed_list.setObjectName("SWPatternSeedReference" + n)
            self.seed_list.setFixedHeight(26)
            self.seed_list.setToolTip("Pick the vertex or edge of the seed the reach is measured from")
            self.seed_list.installEventFilter(self)
            pmboxes.bind(self.seed_list, lambda row, p=panel, k="seedref" + n: p.remove_item(k, row), lambda p=panel, k="seedref" + n: p.clear_items(k))
            seed_row.addWidget(self.seed_list)
            self.seed_widget = QtWidgets.QWidget(self)
            self.seed_widget.setLayout(seed_row)
            seed_row.setContentsMargins(0, 0, 0, 0)
            self.seed_widget.hide()
            ref_lay.addWidget(self.seed_widget)
            self.set_spacing = QtWidgets.QRadioButton("Set spacing", self)
            self.set_spacing.setObjectName("SWPatternSetSpacing" + n)
            self.set_spacing.setToolTip("The spacing is typed: the number of instances follows from the reach")
            self.set_count = QtWidgets.QRadioButton("Set number of instances", self)
            self.set_count.setObjectName("SWPatternSetInstances" + n)
            self.set_count.setToolTip("The number of instances is typed: the spacing follows from the reach")
            self.set_count.toggled.connect(lambda on: panel.set_value(key, "set_by", "count" if on else "spacing"))
            self.set_group = QtWidgets.QButtonGroup(self)
            self.set_group.addButton(self.set_spacing)
            self.set_group.addButton(self.set_count)
            self.set_spacing.setChecked(True)
            ref_lay.addWidget(self.set_spacing)
            ref_lay.addWidget(self.set_count)
            self.ref_widget.hide()
            lay.addWidget(self.ref_widget)
        form = QtWidgets.QFormLayout()
        from .pmspin import TrimSpin
        self.value = TrimSpin(self)
        self.value.setObjectName("SWPatternSpacing" + n)
        self.value.setDecimals(3)
        self.value.setKeyboardTracking(False)
        if circular:
            self.value.setRange(0.001, 360.0)
            self.value.setSuffix("°")
        else:
            self.value.setRange(0.001, 1e6)
            self.value.setSuffix(" mm")
        self.value.valueChanged.connect(lambda v: panel.set_value(key, "value", v))
        form.addRow("Angle:" if circular else "Spacing:", self.value)
        self.count = QtWidgets.QSpinBox(self)
        self.count.setObjectName("SWPatternInstances" + n)
        self.count.setRange(1, 10000)
        self.count.setKeyboardTracking(False)
        self.count.valueChanged.connect(lambda v: panel.set_value(key, "count", v))
        form.addRow("Number of instances:", self.count)
        lay.addLayout(form)
        self.seed = None
        if key == "dir2" and not circular:
            self.seed = QtWidgets.QCheckBox("Pattern seed only", self)
            self.seed.setObjectName("SWPatternSeedOnly")
            self.seed.setToolTip("Direction 2 copies the seed only, not the whole Direction 1 row")
            self.seed.toggled.connect(lambda on: panel.set_value(key, "seed", on))
            _indented(lay).addWidget(self.seed)

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            n = self.key[-1]
            if watched is getattr(self, "ref_list", None):
                self.panel.active = "upto" + n
            elif watched is getattr(self, "seed_list", None):
                self.panel.active = "seedref" + n
            else:
                self.panel.active = self.key
            self.panel._show()
        return False

    def fill(self, d, active):
        self.list.clear()
        if d["ref"] is not None:
            self.list.addItem(d.get("shown") or _name(d["ref"]))
        # Direction 1 is wanted: pink while empty, OK and Enter wait for it and the keyboard
        # stays with the 3D view (pkg106 real-use pass; Direction 2 is optional)
        pmboxes.mark(self.list, active, need=active and d["ref"] is None and self.key == "dir1")
        widgets = [self.reverse, self.value, self.count] + ([self.equal] if self.equal else []) + \
            ([self.use] if self.use else []) + ([self.seed] if self.seed else []) + \
            ([self.up_to, self.spacing_mode, self.offset, self.reverse_offset, self.ref_centroid, self.ref_selected,
              self.set_spacing, self.set_count] if self.up_to else []) + ([self.symmetric] if self.symmetric else [])
        for w in widgets:
            w.blockSignals(True)
        self.reverse.setChecked(d["reverse"])
        if not _typing(self.value):
            self.value.setValue(d["value"])      # not over a value being typed (pkg106)
        if not _typing(self.count):
            self.count.setValue(d["count"])
        if self.equal is not None:
            self.equal.setChecked(d["equal"])
            self.instance_spacing.setChecked(not d["equal"])
        if self.use is not None:
            self.use.setChecked(d["use"])
        if self.seed is not None:
            self.seed.setChecked(d.get("seed", False))
        if self.symmetric is not None:
            self.symmetric.setChecked(d.get("symmetric", False))
            self.value.setEnabled(not d.get("symmetric", False))
        if self.up_to is not None:
            self.up_to.setChecked(d.get("upto", False))
            self.spacing_mode.setChecked(not d.get("upto", False))
            self.ref_widget.setVisible(d.get("upto", False))
            self.ref_list.clear()
            if d.get("upto_ref") is not None:
                self.ref_list.addItem(_name(d["upto_ref"]))
            pmboxes.mark(self.ref_list, self.panel.active == "upto" + self.key[-1],
                         need=bool(d.get("upto")) and d.get("upto_ref") is None)
            if not _typing(self.offset):
                self.offset.setValue(float(d.get("offset", 0.0)))
            self.reverse_offset.setChecked(bool(d.get("reverse_offset")))
            self.ref_selected.setChecked(bool(d.get("ref_from")))
            self.ref_centroid.setChecked(not d.get("ref_from"))
            self.seed_widget.setVisible(bool(d.get("ref_from")))
            self.seed_list.clear()
            if d.get("seed_ref") is not None:
                self.seed_list.addItem(_name(d["seed_ref"]))
            pmboxes.mark(self.seed_list, self.panel.active == "seedref" + self.key[-1],
                         need=bool(d.get("upto")) and bool(d.get("ref_from")) and d.get("seed_ref") is None)
            by_count = d.get("set_by", "spacing") == "count"
            self.set_count.setChecked(by_count)
            self.set_spacing.setChecked(not by_count)

            self.value.setReadOnly(bool(d.get("upto")) and by_count)
            self.count.setReadOnly(bool(d.get("upto")) and not by_count)
        for w in widgets:
            w.blockSignals(False)
        if getattr(self, "compat", None) is not None:
            self.compat.blockSignals(True)
            self.compat.setChecked(bool(d["use"]))
            self.compat.blockSignals(False)
        on = d["use"] if self.use is not None else True
        sym = self.symmetric is not None and bool(d.get("symmetric"))
        for w in (self.reverse, self.list, self.value, self.count):
            w.setEnabled(on and not sym)
        if self.up_to is not None:
            for w in (self.spacing_mode, self.up_to):
                w.setEnabled(not sym)
        if self.seed is not None:
            self.seed.setEnabled(not sym)
        if self.symmetric is not None:
            self.symmetric.setEnabled(on)


class PatternPanel:
    """What both pages share: the picks, the pattern object, the check and the cross."""

    TYPE = None
    TITLE = None
    ICON = None

    def __init__(self, doc, body, picks=()):
        global _current
        _current = self
        try:
            from . import configedits      # spacing or count typed here goes into the shown configuration
            configedits.install()
        except Exception as _fw_err:
            _fw_log("patternpm.py:configedits", _fw_err)
        self.doc, self.body = doc, body
        self.features = []
        self.ref_seeds = None           # planes / axes / points patterned (refpattern), loaded on edit
        self.whole = False
        self.pattern = None
        self.before = None
        self.opened = False
        self.ok = False
        self.active = "dir1"
        self.dirs = self.make_dirs()
        self.boxes = self.make_boxes()
        first = self.boxes["dir1"]
        first.setProperty("swstyle_pm_title", self.TITLE)
        first.setProperty("swstyle_pm_icon", self.ICON)
        self.message = QtWidgets.QLabel("", first)
        self.message.setObjectName("SWPatternMessage")
        self.message.setWordWrap(True)
        first.layout().insertWidget(0, self.message)
        self.faces = []                 # (obj, sub) of Faces to Pattern; their features join self.features
        self.solids = []                # (obj, sub) of Bodies to Pattern: one solid of a multibody part each
        self.skip = set()               # Instances to Skip: 1-based (i, j), circular (k, 1)
        self.vary = False
        self.geometry = False
        self.propagate = True
        self.features_box = mirrorpm._PickBox(self, "features", "Features and Faces", "SWPatternFeatures", 56)
        self.features_box.layout().insertWidget(0, QtWidgets.QLabel("Features to Pattern:", self.features_box))
        self.features_box.layout().addWidget(QtWidgets.QLabel("Faces to Pattern:", self.features_box))
        self.faces_list = QtWidgets.QListWidget(self.features_box)
        self.faces_list.setObjectName("SWPatternFaces")
        self.faces_list.setFixedHeight(44)
        self.faces_list.setToolTip("Faces to Pattern: the faces' features are patterned")
        self._focus = []                # the filters must stay referenced or Python drops them
        for w in (self.faces_list, self.faces_list.viewport()):
            self._focus.append(_Focus(self, "faces"))
            w.installEventFilter(self._focus[-1])
        pmboxes.bind(self.faces_list, lambda row: self.remove_item("faces", row), lambda: self.clear_items("faces"))
        self.features_box.layout().addWidget(self.faces_list)
        self.bodies_box = mirrorpm._PickBox(self, "bodies", "Bodies", "SWPatternBodies", 26)
        skip = QtWidgets.QWidget()
        skip.setWindowTitle("Instances to Skip")
        skip_lay = QtWidgets.QVBoxLayout(skip)
        self.skip_list = QtWidgets.QListWidget(skip)
        self.skip_list.setObjectName("SWPatternSkip")
        self.skip_list.setFixedHeight(60)
        pmboxes.bind(self.skip_list, lambda row: self.remove_item("skip", row), lambda: self.clear_items("skip"))
        self.skip_list.setToolTip("Click an instance in the graphics area to skip it; click it again to bring it back")
        for w in (self.skip_list, self.skip_list.viewport()):      # a click on the empty list lands on
            self._focus.append(_Focus(self, "skip"))               # its viewport (C13-03)
            w.installEventFilter(self._focus[-1])
        skip_lay.addWidget(self.skip_list)
        self.skip_note = QtWidgets.QLabel("Click instances in the graphics area to skip them.", skip)
        self.skip_note.setWordWrap(True)
        skip_lay.addWidget(self.skip_note)
        options = QtWidgets.QWidget()
        options.setWindowTitle("Options")
        lay = QtWidgets.QVBoxLayout(options)
        m = lay.contentsMargins()
        lay.setContentsMargins(m.left() + INDENT, m.top(), m.right(), m.bottom())
        self.vary_box = QtWidgets.QCheckBox("Vary sketch", options)
        self.vary_box.setObjectName("SWPatternVarySketch")
        self.vary_box.setToolTip("Not with Geometry pattern")
        self.vary_box.toggled.connect(lambda on: self.set_option("vary", on))
        lay.addWidget(self.vary_box)
        self.geometry_box = QtWidgets.QCheckBox("Geometry pattern", options)
        self.geometry_box.setObjectName("SWPatternGeometryPattern")
        self.geometry_box.setToolTip("Copies the features' geometry; off, Up To Surface and Through All features "
                                     "are made again at each instance")
        self.geometry_box.toggled.connect(lambda on: self.set_option("geometry", on))
        lay.addWidget(self.geometry_box)
        self.propagate_box = QtWidgets.QCheckBox("Propagate visual properties", options)
        self.propagate_box.setObjectName("SWPatternPropagate")
        self.propagate_box.setChecked(True)
        self.propagate_box.setToolTip("The copies take the seed features' color")
        self.propagate_box.toggled.connect(lambda on: self.set_option("propagate", on))
        lay.addWidget(self.propagate_box)

        self.full_preview = QtWidgets.QRadioButton("Full preview", options)
        self.full_preview.setObjectName("SWPatternFullPreview")
        self.full_preview.setToolTip("Show the result")
        self.partial_preview = QtWidgets.QRadioButton("Partial preview", options)
        self.partial_preview.setObjectName("SWPatternPartialPreview")
        self.partial_preview.setToolTip("Show the copies see-through over the part as it is")
        self.partial_preview.setChecked(True)
        self.partial_preview.toggled.connect(lambda on: self._preview())
        lay.addWidget(self.full_preview)
        lay.addWidget(self.partial_preview)
        self.ghost = mirrorpm._Ghost()
        self.dots = SkipDots(self._dot_sites, self._skip_toggle)
        self.form = [self.boxes[k] for k in self.boxes] + [self.features_box, self.bodies_box, skip, options]
        self.scope_page = self._scope_page()       # Feature Scope, in a multibody part only (as Mirror, pkg310)
        if self.scope_page is not None:
            self.form.append(self.scope_page)
        for obj, sub in picks:
            self._add(obj, sub)
        if self.dirs["dir1"]["ref"] is None:
            self.active = "dir1"
        self.update()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        self._views = []
        self._esc = _Escape(self)
        try:
            # stock FreeCAD 1.1: findChildren(QOpenGLWidget) finds nothing from Python
            for w in [v for v in Gui.getMainWindow().findChildren(QtWidgets.QWidget) if v.inherits("QOpenGLWidget")]:
                w.installEventFilter(self._esc)
                self._views.append(w)
        except Exception as _fw_err:
            _fw_log("patternpm.py:603", _fw_err)


    def _scope_page(self):
        try:
            solids = list(self.body.Tip.Shape.Solids) if self.body.Tip is not None else []
        except Exception:
            solids = []
        if len(solids) < 2:
            return None
        page = QtWidgets.QWidget()
        page.setWindowTitle("Feature Scope")
        page.setObjectName("SWPatternFeatureScope")
        lay = QtWidgets.QVBoxLayout(page)
        m = lay.contentsMargins()
        lay.setContentsMargins(m.left() + INDENT, m.top(), m.right(), m.bottom())
        self.scope_all = QtWidgets.QRadioButton("All bodies", page)
        self.scope_all.setObjectName("SWPatternScopeAll")
        self.scope_some = QtWidgets.QRadioButton("Selected bodies", page)
        self.scope_some.setObjectName("SWPatternScopeSelected")
        self.scope_auto = QtWidgets.QCheckBox("Auto-select", page)
        self.scope_auto.setObjectName("SWPatternScopeAuto")
        self.scope_auto.setChecked(True)
        self.scope_list = QtWidgets.QListWidget(page)
        self.scope_list.setObjectName("SWPatternScopeBodies")
        self.scope_list.setFixedHeight(80)
        self.scope_list.setToolTip("The bodies the patterned features change: tick them")
        for w in (self.scope_all, self.scope_some, self.scope_auto, self.scope_list):
            lay.addWidget(w)
        self.scope_all.setChecked(True)
        self._scope_fill(solids, [])
        self._scope_loaded = False
        self.scope_all.toggled.connect(lambda on: self.update())
        self.scope_auto.toggled.connect(lambda on: self.update())
        self.scope_list.itemChanged.connect(lambda item: self.update())
        return page

    def _scope_fill(self, solids, picked):
        self.scope_solids = list(solids)
        self.scope_list.blockSignals(True)
        self.scope_list.clear()
        for i, solid in enumerate(solids):
            item = QtWidgets.QListWidgetItem("Body %d (%.0f mm\u00b3)" % (i + 1, solid.Volume))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if any(solid.isSame(p) for p in picked) else QtCore.Qt.Unchecked)
            self.scope_list.addItem(item)
        self.scope_list.blockSignals(False)

    def _scope_shown(self):
        if getattr(self, "scope_page", None) is None:
            return
        self.scope_auto.setVisible(self.scope_some.isChecked())
        self.scope_list.setVisible(self.scope_some.isChecked() and not self.scope_auto.isChecked())

    def _apply_scope(self, p):
        if getattr(self, "scope_page", None) is None or p is None or self.whole:
            return
        try:
            from . import multibody
            if getattr(self, "edited", None) is p and not self._scope_loaded:
                self._scope_loaded = True
                everything, auto, picked = multibody.scope_of(p)
                for w in (self.scope_all, self.scope_some, self.scope_auto):
                    w.blockSignals(True)
                (self.scope_all if everything else self.scope_some).setChecked(True)
                self.scope_auto.setChecked(auto)
                for w in (self.scope_all, self.scope_some, self.scope_auto):
                    w.blockSignals(False)
                self._scope_fill(multibody._base_solids(p), picked)
                self._scope_shown()
            everything = self.scope_all.isChecked()
            if everything and multibody.helper_of(p) is None:
                return
            picked = [self.scope_solids[i] for i in range(self.scope_list.count())
                      if self.scope_list.item(i).checkState() == QtCore.Qt.Checked and i < len(self.scope_solids)]
            multibody.set_scope(p, everything, self.scope_auto.isChecked(), picked)
        except Exception as _fw_err:
            _fw_log("patternpm.py:scope", _fw_err)

    def _drop_scope(self):
        """The Feature Scope step goes with the pattern it belongs to."""
        try:
            from . import multibody
            helper = multibody.helper_of(self.pattern) if self.pattern is not None else None
            if helper is not None:
                if self.body.Tip is helper:
                    self.body.Tip = self.pattern
                self.body.removeObject(helper)
                self.doc.removeObject(helper.Name)
        except Exception as _fw_err:
            _fw_log("patternpm.py:drop scope", _fw_err)

    # --- what each page fills in
    def make_dirs(self):
        raise NotImplementedError

    def make_boxes(self):
        raise NotImplementedError

    def direction_of(self, obj, sub):
        raise NotImplementedError

    def set_pattern(self, p):
        raise NotImplementedError

    # --- picks
    def _gone(self):
        """True when the page was closed without OK or Cancel (Gui.Control.closeDialog from elsewhere):
        it lets go of the selection, so a later click in the tree or the model cannot change the
        pattern behind a closed page."""
        try:
            self.message.objectName()
            return False
        except RuntimeError:
            pass
        global _current
        if _current is self:
            _current = None

        def let_go():
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("patternpm.py:gone", _fw_err)
        QtCore.QTimer.singleShot(0, let_go)
        return True

    def addSelection(self, doc, name, sub, pnt):
        try:
            if current() is not self or doc != self.doc.Name:
                return
        except Exception:
            return
        if self._gone():
            return
        obj = self.doc.getObject(name)
        if obj is None:
            return
        obj, sub = refplane.resolve(obj, sub)
        if self.active == "skip" and pnt is not None and (obj is self.pattern or obj is self.body or
                                                          _body_of(obj) is self.body):
            # a real click lands as Body + "LPattern.Face12" (ChatGPT C13-03): any instance of the
            # part under the pointer is the one to skip
            point = App.Vector(*pnt)
            QtCore.QTimer.singleShot(0, lambda: self._skip_at(point))
            return
        QtCore.QTimer.singleShot(0, lambda: self._picked(obj, sub))

    def _picked(self, obj, sub):
        if self._gone():
            return              # the page closed before the pick came through
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("patternpm.py:642", _fw_err)
        self._add(obj, sub)
        self.update()

    def _focus_value(self, key):
        ""

        box = self.boxes.get(key) if hasattr(self, "boxes") else None
        if box is None:
            return
        def go():
            try:
                w = box.value if not box.value.isReadOnly() else box.count
                if w.isVisible() and w.isEnabled():
                    w.setFocus(QtCore.Qt.OtherFocusReason)
                    w.selectAll()
            except Exception as _fw_err:
                _fw_log("patternpm.py:659", _fw_err)
        QtCore.QTimer.singleShot(0, go)

    def _skip_at(self, point):
        """The instance under a click in the graphics area: skipped, or back if it was."""
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("patternpm.py:667", _fw_err)
        index = self.instance_at(point)
        if index is None or index == (1, 1):
            return
        self._skip_toggle(index)

    def _skip_toggle(self, index):
        """A click on an instance or on its skip dot: skipped, or back if it was."""
        if self._gone():
            return
        if index in self.skip:
            self.skip.discard(index)
        else:
            self.skip.add(index)
        self.update()

    def sites(self):
        """[(index, placement)] of every instance but the seed, skipped ones too (the skip dots)."""
        return []

    def _dot_sites(self):
        centre = self.seed_centre()
        return [(ij, pl.multVec(centre), ij in self.skip) for ij, pl in self.sites()]

    def set_option(self, what, on):
        setattr(self, what, on)
        self.update()

    def _part_shape(self):
        """The part before the pattern (the solids a Bodies pick is found on)."""
        p = self.pattern
        shape_of = p.BaseFeature if p is not None and getattr(p, "BaseFeature", None) is not None else self.body.Tip
        return shape_of.Shape if shape_of is not None else self.body.Shape

    def _solid_of(self, obj, sub):
        from .loftsweep import body_holds
        try:
            element = obj.Shape.getElement(sub)
            solids = self._part_shape().Solids
        except Exception:
            return None
        return next((i for i, x in enumerate(solids) if body_holds(x, element)), None)

    def _add_solid(self, obj, sub):
        ""



        if obj is self.pattern or _body_of(obj) is not self.body:
            return False
        i = self._solid_of(obj, sub)
        if i is None:
            return False
        if len(self._part_shape().Solids) < 2:
            self.whole = not self.whole
            self.solids = []
            if self.whole:
                self.features = []
            return True
        same = [x for x in self.solids if self._solid_of(*x) == i]
        if same:
            self.solids.remove(same[0])
        else:
            self.solids.append((obj, sub))
            self.whole = False
        return True

    def _solid_names(self):
        try:
            from . import multibody
            names = [n.replace("\u200b", "") for n, _s in multibody.solids(self.body)]
        except Exception:
            names = []
        out = []
        for o, sub in self.solids:
            i = self._solid_of(o, sub)
            out.append(names[i] if i is not None and i < len(names) else "%s@%s" % (sub, o.Label))
        return out

    def _add(self, obj, sub):
        obj, sub = refplane.resolve(obj, sub or "")
        if self.active == "bodies" and sub and obj.TypeId != "PartDesign::Body":
            self._add_solid(obj, sub)
            return
        if self.active in ("upto1", "upto2") and sub:
            d = self.dirs[self.active.replace("upto", "dir")]
            d["upto_ref"] = None if d.get("upto_ref") == (obj, sub) else (obj, sub)
            return
        if self.active in ("seedref1", "seedref2") and (sub.startswith("Vertex") or sub.startswith("Edge")):
            d = self.dirs[self.active.replace("seedref", "dir")]
            d["seed_ref"] = None if d.get("seed_ref") == (obj, sub) else (obj, sub)
            return
        if self.active == "faces" and sub.startswith("Face"):
            feature = mirrorpm.feature_of_face(self.body, obj, sub)
            if feature is None or feature.TypeId in PATTERN_TYPES or feature is self.pattern:
                return
            if (obj, sub) in self.faces:
                self.faces.remove((obj, sub))
            else:
                self.faces.append((obj, sub))
                self.whole = False
            self.features = [f for f in self.features if f not in [mirrorpm.feature_of_face(self.body, o, s) for o, s in self.faces]]
            return
        if obj.TypeId == "PartDesign::Body":
            if obj is self.body:
                self.whole = not self.whole
                if self.whole:
                    self.features = []
            return
        from . import refpattern
        if self.active == "features" and refpattern.is_datum(obj) and _body_of(obj) is self.body and \
                not (self.pattern is not None and obj in (getattr(self.pattern, refpattern.COPIES, None) or [])):

            seeds = self._ref_seeds()
            if obj in seeds:
                seeds.remove(obj)
            else:
                seeds.append(obj)
            return
        if self.active in self.dirs:
            ref = _usable(self.body, self.direction_of(obj, sub), self.pattern)
            if ref is not None:
                d = self.dirs[self.active]
                d["ref"] = None if d["ref"] == ref else ref
                d["shown"] = _picked_name(self.body, obj, sub) if d["ref"] is not None else None
                if d["ref"] is not None:
                    d["use"] = True
                    if self.active == "dir2" and d["count"] < 2:
                        d["count"] = 2
                    self._focus_value(self.active)   # pkg108: the keyboard goes to the spacing / angle
                    self.active = "features"
                return
            if sub:
                # pkg108: a face or edge that is no direction (a flat face as a circular pattern's

                # through and put the face's feature into Features to Pattern
                try:
                    Gui.getMainWindow().statusBar().showMessage(
                        "Select an axis, a round edge or a round face for the pattern" if self.CIRCULAR
                        else "Select an edge, axis, face or dimension for the direction", 4000)
                except Exception as _fw_err:
                    _fw_log("patternpm.py:740", _fw_err)
                return
        if sub.startswith("Edge") or obj.TypeId in ("App::Line", "PartDesign::Line") or \
                (self.dirs["dir1"]["ref"] is None and sub):
            ref = _usable(self.body, self.direction_of(obj, sub), self.pattern)
            if ref is not None and self.dirs["dir1"]["ref"] is None:
                self.dirs["dir1"]["ref"] = ref
                self.dirs["dir1"]["shown"] = _picked_name(self.body, obj, sub)
                self._focus_value("dir1")
                self.active = "features"
                return
            if sub.startswith("Edge") or not sub.startswith("Face"):
                return
        feature = None
        if not sub and mirrorpm.is_feature(obj, self.body):
            feature = obj
        elif sub.startswith("Face"):
            feature = mirrorpm.feature_of_face(self.body, obj, sub)
        if feature is None or feature.TypeId in PATTERN_TYPES or feature is self.pattern:
            return
        if feature in self.features:
            self.features.remove(feature)
        else:
            self.features.append(feature)
            self.whole = False
        self.active = "features"

    def remove_item(self, key, row):
        ""
        if key in self.dirs:
            self.dirs[key]["ref"] = None
            self.dirs[key]["shown"] = None
            self.active = key
        elif key in ("upto1", "upto2"):
            self.dirs[key.replace("upto", "dir")]["upto_ref"] = None
        elif key in ("seedref1", "seedref2"):
            self.dirs[key.replace("seedref", "dir")]["seed_ref"] = None
        elif key == "features" and 0 <= row < len(self.features):
            self.features.pop(row)
        elif key == "features" and 0 <= row - len(self.features) < len(self._ref_seeds()):
            self._ref_seeds().pop(row - len(self.features))
        elif key == "faces" and 0 <= row < len(self.faces):
            self.faces.pop(row)
        elif key == "bodies":
            if self.whole:
                self.whole = False
            elif 0 <= row < len(self.solids):
                self.solids.pop(row)
        elif key == "skip":
            skips = sorted(self.skip)
            if 0 <= row < len(skips):
                self.skip.discard(skips[row])
        self.update()

    def clear_items(self, key):
        """Clear Selections in a box."""
        if key in self.dirs:
            self.dirs[key]["ref"] = None
            self.active = key
        elif key in ("upto1", "upto2"):
            self.dirs[key.replace("upto", "dir")]["upto_ref"] = None
        elif key in ("seedref1", "seedref2"):
            self.dirs[key.replace("seedref", "dir")]["seed_ref"] = None
        elif key == "features":
            self.features = []
            self.ref_seeds = []
        elif key == "faces":
            self.faces = []
        elif key == "bodies":
            self.whole = False
            self.solids = []
        elif key == "skip":
            self.skip = set()
        self.update()

    # --- the box edits
    def set_value(self, key, what, value):
        self.dirs[key][what] = value
        if what == "upto" and value and self.dirs[key].get("upto_ref") is None:
            self.active = "upto" + key[-1]
        elif what == "ref_from" and value and self.dirs[key].get("seed_ref") is None:
            self.active = "seedref" + key[-1]
        self.update()

    def set_use(self, key, on):
        self.dirs[key]["use"] = on
        if on:
            self.active = key
        self.update()

    # --- the pattern
    def seeds(self):
        """The features patterned: Features to Pattern plus the features of Faces to Pattern."""
        out = list(self.features)
        for obj, sub in self.faces:
            f = mirrorpm.feature_of_face(self.body, obj, sub)
            if f is not None and f not in out:
                out.append(f)
        return out

    def missing(self):
        if self.dirs["dir1"]["ref"] is None:
            return self.ASK_DIRECTION
        for key, d in self.dirs.items():
            if d["use"] and d.get("upto") and d.get("upto_ref") is None:
                return "Select the vertex, edge or face the %s instances reach." % key.replace("dir", "Direction ")
            if d["use"] and d.get("upto") and d.get("ref_from") and d.get("seed_ref") is None:
                return "Select the seed vertex or edge the %s reach is measured from." % key.replace("dir", "Direction ")
        if not self.seeds() and not self.whole and not self._ref_seeds() and not self.solids:
            return "Select the features or the body to pattern."
        if self.vary and self.geometry:
            return "A pattern with variant sketch option is not suitable for geometry pattern."
        return None

    def _ref_seeds(self):
        if self.ref_seeds is None:
            from . import refpattern
            p = getattr(self, "edited", None) or self.pattern
            self.ref_seeds = list(getattr(p, refpattern.SEEDS, None) or []) if p is not None else []
        return self.ref_seeds

    def needs_own(self):
        ""
        if self.skip or self.vary or getattr(self, "instances_vary", {}).get("on"):
            return True
        if getattr(self, "stock_failed", False):
            return True             # FreeCAD's pattern failed on these seeds (a lofted blade: "Null shape")
        if not self.seeds() and not self.whole and self._ref_seeds():
            return True
        if any(d["use"] and d.get("upto") for d in self.dirs.values()):
            return True             # Up to reference with its offset and seed reference (features/103)
        if self.faces:
            return True             # Faces to Pattern: the faces closed off into the seed (patterns._face_seeds)
        if self.solids:
            return True
        if any(patterns.is_dressup(f) for f in self.seeds()):
            return True             # a fillet in the list: FreeCAD copies its whole part (the hub was lost)
        if any(patterns.odd_profile(f) for f in self.seeds()):
            return True             # FreeCAD's pattern copies nothing of a Selected Contours / From Offset seed
        if self.CIRCULAR and self.dirs["dir2"]["use"]:
            return True
        if self.dirs.get("dir2", {}).get("use") and (self.dirs["dir2"].get("seed") or self.dirs["dir2"].get("symmetric")
                                                      or self.CIRCULAR):
            return True
        if not self.geometry and any(str(getattr(f, "Type", "")) in UP_TO_KINDS for f in self.seeds()):
            return True
        return False

    def wanted_type(self):
        return self.OWN.type if self.needs_own() else self.TYPE

    def _make(self):
        wanted = self.wanted_type()
        if self.pattern is not None and self.pattern.TypeId != wanted:
            self._drop_scope()
            if getattr(self, "edited", None) is self.pattern:
                # editing an accepted pattern: the feature changes kind in place (C13-03/04)
                self.pattern = self.edited = patterns.replace_feature(self.body, self.pattern, wanted, self.OWN, self.NAME)
            else:
                self._drop()
        if self.pattern is None:
            if not self.opened:
                self.doc.openTransaction(self.TITLE)
                self.opened = True
            self.before = self.body.Tip
            self.pattern = self.body.newObject(wanted, self.NAME)
            if wanted == self.OWN.type:
                sf.Feature(self.pattern, self.OWN)
                if self.pattern.ViewObject is not None:
                    sf.View(self.pattern.ViewObject)
                from . import naming
                self.pattern.Label = naming.next_label(self.doc, self.NAME)
            if self.body.Tip is not self.pattern:
                self.body.Tip = self.pattern
            try:
                self.pattern.ViewObject.Visibility = True
                if self.before is not None:
                    self.before.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("patternpm.py:906", _fw_err)
        return self.pattern

    def _drop(self):
        if self.pattern is not None:
            self._drop_scope()
            name = self.pattern.Name
            self.body.removeObject(self.pattern)
            self.doc.removeObject(name)
            self.pattern = None
            if self.before is not None and self.before in self.body.Group:
                self.body.Tip = self.before
                try:
                    self.before.ViewObject.Visibility = True
                except Exception as _fw_err:
                    _fw_log("patternpm.py:920", _fw_err)

    def update(self):
        if self._gone():
            return
        missing = self.missing()
        if missing:
            self._drop()
            self.doc.recompute()
            if self._gone():            # closed while it rebuilt (features-420)
                return
            self.message.setText("")
            try:
                Gui.getMainWindow().statusBar().showMessage(missing, 0)
            except Exception as _fw_err:
                _fw_log("patternpm.py:931", _fw_err)
            self.message.setStyleSheet("")
            self.ok = False
        else:
            p = self._make()
            try:
                self._up_to_spacing()
                seeds = self.seeds()
                if p.TypeId == self.OWN.type:
                    own = self.features if self.faces else seeds
                    p.Features = [f for f in (mirrorpm.features_of(self.body) if self.whole else mirrorpm.originals(own)) if f is not p]
                    p.Faces = [(o, [sub]) for o, sub in self.faces]
                    if "Bodies" in p.PropertiesList:
                        p.Bodies = [(o, [sub]) for o, sub in self.solids]
                    self.set_own(p)
                    self._read_reach(p)
                elif self.whole:
                    p.Originals = []
                    p.TransformMode = "Whole shape"
                else:
                    p.TransformMode = "Features"
                    p.Originals = mirrorpm.originals(seeds)
                if p.TypeId != self.OWN.type:
                    self.set_pattern(p)
                from . import refpattern
                if self._ref_seeds() or refpattern.SEEDS in p.PropertiesList:
                    refpattern.set_seeds(p, self._ref_seeds())
                self.doc.recompute()
                if refpattern.SEEDS in p.PropertiesList:
                    refpattern.sync(p)
                bad = "Invalid" in p.State or not p.isValid()
                text = p.getStatusString() if bad else ""
                if bad and p.TypeId != self.OWN.type and not getattr(self, "stock_failed", False):
                    self.stock_failed = True
                    return self.update()
                if not bad:
                    self._colour(p)
                    self._apply_scope(p)
            except Exception as error:
                bad, text = True, str(error)
            if self._gone():            # OK or Cancel came in while the preview rebuilt (features-420)
                return
            self.message.setText((text or "The pattern could not be made.") if bad else "")
            self.message.setStyleSheet(_error_css() if bad else "")
            self.ok = not bad
        self._show()
        self._preview()

    def _show(self):
        self.message.setVisible(bool(self.message.text()))
        for key, box in self.boxes.items():
            box.fill(self.dirs[key], self.active == key)
        self.features_box.fill([f.Label for f in self.features] + [f.Label for f in self._ref_seeds()],
                               self.active == "features")
        self.faces_list.clear()
        for obj, sub in self.faces:
            self.faces_list.addItem(_name((obj, sub)))
        pmboxes.mark(self.faces_list, self.active == "faces")
        self.bodies_box.fill([self.body.Label] if self.whole else self._solid_names(), self.active == "bodies")
        self.skip_list.clear()
        for ij in sorted(self.skip):
            self.skip_list.addItem(self.skip_name(ij))
        pmboxes.mark(self.skip_list, self.active == "skip")
        for box, value in ((self.vary_box, self.vary), (self.geometry_box, self.geometry), (self.propagate_box, self.propagate)):
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)
        self.vary_box.setVisible(self.vary or self._vary_ok())     # not greyed: shown where it can work
        self._scope_shown()
        dots = getattr(self, "dots", None)
        if dots is not None:
            dots.show(self.active == "skip" and self.ok)

    def _vary_ok(self):
        ""
        seeds = self.seeds()
        return self.dirs["dir1"]["ref"] is not None and bool(seeds) and \
            all(getattr(f, "Profile", None) is not None for f in seeds)

    # --- what the own feature and the extras need
    def seed_centre(self):
        feats = mirrorpm.features_of(self.body) if self.whole else self.seeds()
        shapes = []
        for f in feats:
            if f is self.pattern or f.AddSubShape.isNull():
                continue
            shape = f.AddSubShape.copy()
            shape.Placement = f.Placement.multiply(shape.Placement)
            shapes.append((shape, False))
        if not shapes:
            return self.body.Shape.BoundBox.Center if not self.body.Shape.isNull() else App.Vector()
        c = patterns._center(shapes)
        # a Through All cut's tool runs far past the part (its centre was 118 mm above a 10 mm plate, so the

        try:
            if not self.body.Shape.isNull():
                bb = self.body.Shape.BoundBox
                c = App.Vector(min(max(c.x, bb.XMin), bb.XMax), min(max(c.y, bb.YMin), bb.YMax),
                               min(max(c.z, bb.ZMin), bb.ZMax))
        except Exception as _fw_err:
            _fw_log("patternpm.py:seed_centre", _fw_err)
        return c

    def _ref_point(self, ref):
        shape = refplane.shape_of(*ref)
        if shape.ShapeType == "Vertex":
            return shape.Point
        if shape.ShapeType == "Edge":
            return shape.valueAt(shape.FirstParameter + (shape.LastParameter - shape.FirstParameter) / 2)
        return shape.CenterOfMass

    def _read_reach(self, p):
        ""

        if self.CIRCULAR:
            return
        try:
            base = p.BaseFeature.Shape if getattr(p, "BaseFeature", None) is not None else None
            seeds = patterns._seeds(p, base)
        except Exception:
            return
        for k, key in ((1, "dir1"), (2, "dir2")):
            d = self.dirs[key]
            if not (d["use"] and d.get("upto") and d.get("upto_ref") is not None and d["ref"] is not None):
                continue
            _v, spacing, count = patterns._direction(p, k, seeds, base)
            d["value"], d["count"] = round(spacing, 3), int(count)

    def _up_to_spacing(self):
        """Up to reference: the spacing that puts the last instance at the reference."""
        if self.needs_own():
            return
        for key, d in self.dirs.items():
            if not (d["use"] and d.get("upto") and d.get("upto_ref") is not None and d["ref"] is not None):
                continue
            direction = patterns.direction_of(*d["ref"])
            if d["reverse"]:
                direction = direction * -1
            reach = (self._ref_point(d["upto_ref"]) - self.seed_centre()).dot(direction)
            if reach <= 0:
                raise RuntimeError("The reference is not in the %s direction." % key.replace("dir", "Direction "))
            if d["count"] > 1:
                d["value"] = round(reach / (d["count"] - 1), 3)

    def _colour(self, p):
        """Propagate visual properties: the copies take the seed features' colour."""
        try:
            seeds = [f for f in self.seeds() if f is not p]
            vobj = p.ViewObject
            if vobj is None:
                return
            if not self.propagate or not seeds:
                vobj.ShapeAppearance = [vobj.ShapeAppearance[0]]
                return
            seed_app = seeds[0].ViewObject.ShapeAppearance
            base_app = vobj.ShapeAppearance[0]
            colour = seed_app[0]
            if tuple(colour.DiffuseColor) == tuple(base_app.DiffuseColor):
                vobj.ShapeAppearance = [base_app]
                return
            boxes = []
            for placement in self.placements():
                for f in seeds:
                    if f.AddSubShape.isNull():
                        continue
                    shape = f.AddSubShape.copy()
                    shape.Placement = placement.multiply(f.Placement.multiply(shape.Placement))
                    box = shape.BoundBox
                    box.enlarge(1e-3)
                    boxes.append(box)
            apps = []
            for face in p.Shape.Faces:
                c = face.CenterOfMass
                apps.append(colour if any(b.isInside(c) for b in boxes) else base_app)
            vobj.ShapeAppearance = apps
        except Exception as _fw_err:
            _fw_log("patternpm.py:1085", _fw_err)

    # --- check and cross
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _preview(self):
        """Partial preview: the part as it was, the copies drawn as a ghost; Full: the result (pkg123)."""
        g = getattr(self, "ghost", None)
        if g is None:
            return
        p, b = self.pattern, self.before
        try:
            if p is None or not self.ok or not self.partial_preview.isChecked() or b is None:
                g.show([])
                if p is not None:
                    p.ViewObject.Visibility = True
                    if b is not None:
                        b.ViewObject.Visibility = False
                return
            extra = p.Shape.cut(b.Shape)
            g.show([extra] if not extra.isNull() else [])
            p.ViewObject.Visibility = False
            b.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("patternpm.py:1110", _fw_err)

    def _close(self):
        global _current
        _current = None
        try:
            self.ghost.remove()
        except Exception as _fw_err:
            _fw_log("patternpm.py:1118", _fw_err)
        try:
            self.dots.remove()
        except Exception as _fw_err:
            _fw_log("patternpm.py:dots", _fw_err)
        try:
            if self.pattern is not None and self.pattern.ViewObject is not None:
                self.pattern.ViewObject.Visibility = True
                if self.before is not None:
                    self.before.ViewObject.Visibility = False
                from . import multibody
                helper = multibody.helper_of(self.pattern)
                if helper is not None and self.body.Tip is helper:      # Feature Scope: its step shows the part
                    self.pattern.ViewObject.Visibility = False
                    helper.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("patternpm.py:1125", _fw_err)
        for w in self._views:
            try:
                w.removeEventFilter(self._esc)
            except Exception as _fw_err:
                _fw_log("patternpm.py:1130", _fw_err)
        self._views = []
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("patternpm.py:1135", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if not self.ok:
            return False
        self.remember()
        self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        names = _names(self.pattern, getattr(self, "edited", None))
        if self.opened:
            self.doc.abortTransaction()
        for name in names:          # made by the Linear/Circular Pattern spec command: Cancel leaves nothing
            sf.drop_made(self.doc, name)
        self.doc.recompute()
        try:
            self.body.Tip.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("patternpm.py:1153", _fw_err)
        self._close()
        return True

    def remember(self):
        pass


def _names(*objs):
    out = []
    for o in objs:
        try:
            if o is not None and o.Name not in out:
                out.append(o.Name)
        except Exception:           # already deleted
            pass
    return out


def _direction(value, count, use=True):
    return {"ref": None, "reverse": False, "value": value, "count": count, "equal": True, "use": use,
            "upto": False, "upto_ref": None, "seed": False, "symmetric": False,
            "offset": 0.0, "reverse_offset": False, "ref_from": False, "seed_ref": None, "set_by": "spacing"}


class _VaryMixin:
    ""

    VARY_SPACING_UNIT = " mm"

    def _vary_setup(self, doc, body, picks):
        self.instances_vary = {"on": False, "VarySpacing1": 0.0, "VaryDepth1": 0.0, "VaryScale1": 0.0,
                               "VarySpacing2": 0.0, "VaryDepth2": 0.0, "VaryScale2": 0.0}
        super().__init__(doc, body, picks)
        self.form.append(self._vary_page())

    def _set_vary(self, p):
        iv = self.instances_vary
        p.VaryInstances = bool(iv["on"])
        for key in ("VarySpacing1", "VaryDepth1", "VaryScale1", "VarySpacing2", "VaryDepth2", "VaryScale2"):
            setattr(p, key, float(iv[key]))

    def _vary_spacing(self, spacing, k, direction):
        """How far instance k sits from the seed with the spacing increment (as patterns._spaced)."""
        iv = self.instances_vary
        inc = float(iv["VarySpacing%d" % direction]) if iv["on"] else 0.0
        return spacing * k + inc * k * (k - 1) / 2.0

    def _vary_page(self):
        page = QtWidgets.QWidget()
        page.setWindowTitle("Instances to Vary")
        lay = QtWidgets.QFormLayout(page)
        on = QtWidgets.QCheckBox("Instances to Vary", page)
        on.setObjectName("SWPatternInstancesToVary")
        lay.addRow(on)
        rows = []
        unit = self.VARY_SPACING_UNIT
        for key, label, suffix in (("VarySpacing1", "Direction 1 spacing increment", unit),
                                   ("VaryDepth1", "Direction 1 depth increment", " mm"),
                                   ("VaryScale1", "Direction 1 size increment", " %"),
                                   ("VarySpacing2", "Direction 2 spacing increment", unit),
                                   ("VaryDepth2", "Direction 2 depth increment", " mm"),
                                   ("VaryScale2", "Direction 2 size increment", " %")):
            spin = QtWidgets.QDoubleSpinBox(page)
            spin.setObjectName("SWPattern" + key)
            spin.setRange(-99.0 if suffix == " %" else -1e4, 1e4)
            spin.setDecimals(2)
            spin.setSuffix(suffix)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda v, k=key: self._vary_value(k, v))
            text = QtWidgets.QLabel(label, page)
            lay.addRow(text, spin)
            rows.append((text, spin))

        def shown(flag):
            for text, spin in rows:
                text.setVisible(flag)
                spin.setVisible(flag)
        shown(False)
        on.toggled.connect(lambda flag: (shown(flag), self._vary_value("on", flag)))
        self.vary_on, self.vary_spins = on, {spin.objectName()[9:]: spin for _t, spin in rows}
        return page

    def load_vary(self, f):
        """Edit Feature: the Instances to Vary values of f back on the page, without a rebuild."""
        values = {"on": bool(getattr(f, "VaryInstances", False))}
        for key in self.vary_spins:
            values[key] = float(getattr(f, key, 0.0))
        self.instances_vary.update(values)
        for key, spin in self.vary_spins.items():
            spin.blockSignals(True)
            spin.setValue(values[key])
            spin.blockSignals(False)
        self.vary_on.blockSignals(True)
        self.vary_on.setChecked(values["on"])
        self.vary_on.blockSignals(False)
        for key, spin in self.vary_spins.items():
            spin.setVisible(values["on"])
        for text in self.vary_on.parentWidget().findChildren(QtWidgets.QLabel):
            text.setVisible(values["on"])

    def _vary_value(self, key, value):
        self.instances_vary[key] = value
        self.update()


class LinearPanel(_VaryMixin, PatternPanel):
    TYPE = "PartDesign::LinearPattern"
    OWN = patterns.LINEAR
    CIRCULAR = False
    TITLE = "Linear Pattern"
    NAME = "LPattern"
    ICON = "FEATURES_LINEAR_PATTERN"
    ASK_DIRECTION = "Select an edge, axis or face for Direction 1."

    def dir2(self):
        ""

        d1, d2 = self.dirs["dir1"], self.dirs["dir2"]
        if not d2.get("symmetric"):
            return d2
        return dict(d2, ref=d1["ref"], reverse=not d1["reverse"], value=d1["value"], count=d1["count"],
                    seed=True, use=d1["ref"] is not None, upto=False)

    def set_use(self, key, on):
        if key == "dir2" and not on:
            self.dirs["dir2"].update(ref=None, symmetric=False)     # as clearing the Direction 2 box
        super().set_use(key, on)

    def update(self):
        d2 = self.dirs["dir2"]
        # Direction 2's title tick (as Circular Pattern's): a picked direction or Symmetric ticks it
        if d2["ref"] is not None or bool(d2.get("symmetric")):
            d2["use"] = True
        if d2.get("symmetric"):
            d2["upto"] = False
        super().update()

    def set_own(self, p):
        d1, d2 = self.dirs["dir1"], self.dir2()
        p.Direction1 = [(d1["ref"][0], [d1["ref"][1]])]
        p.Reverse1 = d1["reverse"]
        p.Spacing1 = d1["value"]
        p.Count1 = d1["count"]
        p.UseDirection2 = bool(d2["use"] and d2["ref"] is not None)
        p.Direction2 = [(d2["ref"][0], [d2["ref"][1]])] if p.UseDirection2 else []
        p.Reverse2 = d2["reverse"]
        p.Spacing2 = d2["value"]
        p.Count2 = d2["count"]
        p.SeedOnly = bool(d2.get("seed"))
        for k, d in ((1, d1), (2, d2)):
            self._set_up_to(p, k, d)
        if patterns.parse_skip(p.Skip or "") != self.skip:     # the same instances keep their text
            p.Skip = patterns.format_skip(self.skip)
        p.VarySketch = self.vary
        p.GeometryPattern = self.geometry
        p.Propagate = self.propagate
        self._set_vary(p)

    def _set_up_to(self, p, k, d):
        """Direction k's Up to reference fields (features/103): the mode, the reference, the offset,
        the seed point measured from and whether the spacing or the count is typed."""
        upto = bool(d["use"] and d.get("upto") and d.get("upto_ref") is not None)
        setattr(p, "Mode%d" % k, patterns.UP_TO_REFERENCE if upto else patterns.SPACING_MODES[0])
        setattr(p, "Reference%d" % k, [(d["upto_ref"][0], [d["upto_ref"][1]])] if upto else [])
        setattr(p, "Offset%d" % k, float(d.get("offset", 0.0)))
        setattr(p, "ReverseOffset%d" % k, bool(d.get("reverse_offset")))
        setattr(p, "RefFrom%d" % k, "Selected reference" if d.get("ref_from") else "Centroid")
        seed = d.get("seed_ref") if d.get("ref_from") else None
        setattr(p, "SeedReference%d" % k, [(seed[0], [seed[1]])] if seed is not None else [])
        setattr(p, "SetBy%d" % k, "Set number of instances" if d.get("set_by") == "count" else "Set spacing")

    def __init__(self, doc, body, picks=()):
        self._vary_setup(doc, body, picks)

    def placements(self):
        d1, d2 = self.dirs["dir1"], self.dir2()
        if d1["ref"] is None:
            return []
        v1 = patterns.direction_of(*d1["ref"]) * (-1 if d1["reverse"] else 1)
        n1, s1 = d1["count"], d1["value"]
        v2, n2, s2 = None, 1, 0.0
        if d2["use"] and d2["ref"] is not None:
            v2 = patterns.direction_of(*d2["ref"]) * (-1 if d2["reverse"] else 1)
            n2, s2 = d2["count"], d2["value"]
        out = []
        for i in range(n1):
            for j in range(n2):
                if (i == 0 and j == 0) or (i + 1, j + 1) in self.skip or (d2.get("seed") and i > 0 and j > 0):
                    continue
                move = v1 * (s1 * i) + (v2 * (s2 * j) if v2 is not None else App.Vector())
                out.append(App.Placement(move, App.Rotation()))
        return out

    def sites(self):
        d1, d2 = self.dirs["dir1"], self.dir2()
        if d1["ref"] is None:
            return []
        v1 = patterns.direction_of(*d1["ref"]) * (-1 if d1["reverse"] else 1)
        n1, s1 = d1["count"], d1["value"]
        v2, n2, s2 = None, 1, 0.0
        if d2["use"] and d2["ref"] is not None:
            v2 = patterns.direction_of(*d2["ref"]) * (-1 if d2["reverse"] else 1)
            n2, s2 = d2["count"], d2["value"]
        out = []
        for i in range(n1):
            for j in range(n2):
                if (i == 0 and j == 0) or (d2.get("seed") and i > 0 and j > 0):
                    continue
                move = v1 * (s1 * i) + (v2 * (s2 * j) if v2 is not None else App.Vector())
                out.append(((i + 1, j + 1), App.Placement(move, App.Rotation())))
        return out

    def instance_at(self, point):
        d1, d2 = self.dirs["dir1"], self.dir2()
        if d1["ref"] is None:
            return None
        rel = point - self.seed_centre()
        v1 = patterns.direction_of(*d1["ref"]) * (-1 if d1["reverse"] else 1)
        i = int(round(rel.dot(v1) / d1["value"])) if d1["value"] > 0 else 0
        j = 0
        if d2["use"] and d2["ref"] is not None and d2["value"] > 0:
            v2 = patterns.direction_of(*d2["ref"]) * (-1 if d2["reverse"] else 1)
            j = int(round(rel.dot(v2) / d2["value"]))
        i = min(max(i, 0), d1["count"] - 1)
        j = min(max(j, 0), (d2["count"] - 1) if d2["use"] else 0)
        return (i + 1, j + 1)

    def skip_name(self, ij):
        return "(%d, %d)" % ij

    def make_dirs(self):
        p = _params()
        return {"dir1": _direction(p.GetFloat("LinearSpacing", 10.0), p.GetInt("LinearInstances", 2)),
                "dir2": _direction(p.GetFloat("LinearSpacing", 10.0), 1, use=False)}

    def make_boxes(self):
        return {"dir1": _DirectionBox(self, "dir1", "Direction 1"),
                "dir2": _DirectionBox(self, "dir2", "Direction 2")}

        # hidden SWPatternDir2On check stays for macros, and a picked direction or Symmetric turns it on

    def direction_of(self, obj, sub):
        return linear_direction(self.body, obj, sub)

    def missing(self):
        text = super().missing()
        d2 = self.dirs["dir2"]
        if text is None and d2["use"] and d2["ref"] is None and not d2.get("symmetric"):
            return "Select an edge, axis or face for Direction 2."
        return text

    def set_pattern(self, p):
        d1, d2 = self.dirs["dir1"], self.dirs["dir2"]
        p.Direction = (d1["ref"][0], [d1["ref"][1]])
        p.Reversed = d1["reverse"]
        p.Mode = "Spacing"
        p.Offset = d1["value"]
        p.Occurrences = d1["count"]
        if d2["use"] and d2["ref"] is not None:
            p.Direction2 = (d2["ref"][0], [d2["ref"][1]])
            p.Reversed2 = d2["reverse"]
            p.Mode2 = "Spacing"
            p.Offset2 = d2["value"]
            p.Occurrences2 = d2["count"]
        else:
            p.Direction2 = None
            p.Occurrences2 = 1

    def remember(self):
        p = _params()
        p.SetFloat("LinearSpacing", self.dirs["dir1"]["value"])
        p.SetInt("LinearInstances", self.dirs["dir1"]["count"])


class CircularPanel(_VaryMixin, PatternPanel):
    VARY_SPACING_UNIT = "\u00b0"
    TYPE = "PartDesign::PolarPattern"
    OWN = patterns.CIRCULAR
    CIRCULAR = True
    TITLE = "Circular Pattern"
    NAME = "CirPattern"
    ICON = "FEATURES_CIRCULAR_PATTERN"
    ASK_DIRECTION = "Select an axis, a round edge or a round face for the pattern axis."

    def make_dirs(self):
        p = _params()
        d = _direction(p.GetFloat("CircularAngle", 360.0), p.GetInt("CircularInstances", 4))
        d["equal"] = p.GetBool("CircularEqual", True)
        d2 = _direction(p.GetFloat("CircularAngle", 360.0), 2, use=False)
        d2["equal"] = d["equal"]
        return {"dir1": d, "dir2": d2}

    def make_boxes(self):
        return {"dir1": _DirectionBox(self, "dir1", "Direction 1", circular=True),
                "dir2": _DirectionBox(self, "dir2", "Direction 2", circular=True, optional=True)}

    def missing(self):
        text = super().missing()
        return text

    def _step(self, d=None):
        d = self.dirs["dir1"] if d is None else d
        if d["equal"]:
            return d["value"] / d["count"] if abs(d["value"] - 360.0) < 1e-6 else (d["value"] / (d["count"] - 1) if d["count"] > 1 else 0.0)
        return d["value"]

    def set_own(self, p):
        d, d2 = self.dirs["dir1"], self.dirs["dir2"]
        p.Axis = [(d["ref"][0], [d["ref"][1]])]
        p.Reverse1 = d["reverse"]
        p.EqualSpacing = d["equal"]
        p.Angle = d["value"]
        p.Count1 = d["count"]
        p.UseDirection2 = bool(d2["use"])
        p.Symmetric = bool(d2.get("symmetric"))
        p.EqualSpacing2 = bool(d2["equal"])
        p.Angle2 = d2["value"]
        p.Count2 = d2["count"]
        if patterns.parse_skip(p.Skip or "") != self.skip:     # the same instances keep their text
            p.Skip = patterns.format_skip(self.skip)
        p.VarySketch = self.vary
        p.GeometryPattern = self.geometry
        p.Propagate = self.propagate
        self._set_vary(p)

    def __init__(self, doc, body, picks=()):
        self._vary_setup(doc, body, picks)

    def placements(self):
        d, d2 = self.dirs["dir1"], self.dirs["dir2"]
        if d["ref"] is None:
            return []
        point, axis = patterns.axis_of(*d["ref"])
        if d["reverse"]:
            axis = axis * -1
        step = self._step()
        out = []
        for k in range(1, d["count"]):
            if (k + 1, 1) not in self.skip:
                out.append(App.Placement(App.Vector(), App.Rotation(axis, self._vary_spacing(step, k, 1)), point))
        if d2["use"]:
            n2 = d["count"] if d2.get("symmetric") else d2["count"]
            step2 = step if d2.get("symmetric") else self._step(d2)
            for k in range(1, n2):
                if (-k - 1, 1) not in self.skip:
                    out.append(App.Placement(App.Vector(), App.Rotation(axis, -self._vary_spacing(step2, k, 2)), point))
        return out

    def sites(self):
        d, d2 = self.dirs["dir1"], self.dirs["dir2"]
        if d["ref"] is None:
            return []
        point, axis = patterns.axis_of(*d["ref"])
        if d["reverse"]:
            axis = axis * -1
        step = self._step()
        out = [((k + 1, 1), App.Placement(App.Vector(), App.Rotation(axis, self._vary_spacing(step, k, 1)), point))
               for k in range(1, d["count"])]
        if d2["use"]:
            n2 = d["count"] if d2.get("symmetric") else d2["count"]
            step2 = step if d2.get("symmetric") else self._step(d2)
            out += [((-k - 1, 1), App.Placement(App.Vector(), App.Rotation(axis, -self._vary_spacing(step2, k, 2)), point))
                    for k in range(1, n2)]
        return out

    def instance_at(self, point):
        import math
        d, d2 = self.dirs["dir1"], self.dirs["dir2"]
        if d["ref"] is None:
            return None
        origin, axis = patterns.axis_of(*d["ref"])
        if d["reverse"]:
            axis = axis * -1
        step = self._step()
        if step <= 0:
            return None
        seed = self.seed_centre() - origin
        seed = seed - axis * seed.dot(axis)
        rel = point - origin
        rel = rel - axis * rel.dot(axis)
        if seed.Length < 1e-9 or rel.Length < 1e-9:
            return None
        angle = math.degrees(math.atan2(axis.dot(seed.cross(rel)), seed.dot(rel)))
        k = int(round(angle / step))
        if k < 0 and not d2["use"]:
            k = k % max(int(round(360.0 / step)), 1) if abs(d["value"] - 360.0) < 1e-6 else 0
        if k == 0:
            return (1, 1)
        return (k + 1, 1) if k > 0 else (k - 1, 1)

    def skip_name(self, ij):
        k = ij[0]
        return "(%d)" % k if k > 0 else "(%d, Direction 2)" % (-k)

    def direction_of(self, obj, sub):
        return circular_axis(self.body, obj, sub)

    def set_pattern(self, p):
        d = self.dirs["dir1"]
        p.Axis = (d["ref"][0], [d["ref"][1]])
        p.Reversed = d["reverse"]
        if d["equal"]:
            p.Mode = "Extent"
            p.Angle = d["value"]
        else:
            p.Mode = "Spacing"
            p.Offset = d["value"]
        p.Occurrences = d["count"]

    def remember(self):
        p = _params()
        d = self.dirs["dir1"]
        p.SetFloat("CircularAngle", d["value"])
        p.SetInt("CircularInstances", d["count"])
        p.SetBool("CircularEqual", d["equal"])


# --------------------------------------------------------------------------- the commands
class _Command:
    PANEL = None
    NATIVE = None
    PIXMAP = None
    TEXT = None
    TIP = None

    def GetResources(self):
        return {"Pixmap": self.PIXMAP, "MenuText": self.TEXT, "ToolTip": self.TIP}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        body = refplane.body_of(doc)
        if body is None:

            if any(o.TypeId != "PartDesign::Body" and hasattr(o, "Shape") and o.Shape.Solids for o in doc.Objects):
                from . import wepattern
                wepattern.open_panel(doc, "linear" if self.NATIVE == "PartDesign_LinearPattern" else "circular",
                                     mirrorpm.preselected(doc))
                return
            Gui.runCommand(self.NATIVE, 0)
            return
        picks = mirrorpm.preselected(doc)     # a feature and its own edge stay two picks
        panel = self.PANEL
        QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(panel(doc, body, picks)))


class LinearCommand(_Command):
    PANEL = LinearPanel
    NATIVE = "PartDesign_LinearPattern"
    PIXMAP = "PartDesign_LinearPattern"
    TEXT = "Linear Pattern"
    TIP = "Copies features along one or two directions, by spacing and number of instances"


class CircularCommand(_Command):
    PANEL = CircularPanel
    NATIVE = "PartDesign_PolarPattern"
    PIXMAP = "PartDesign_PolarPattern"
    TEXT = "Circular Pattern"
    TIP = "Copies features around an axis, by angle and number of instances"


COMMANDS = {"SWStyle_LinearPattern": LinearCommand, "SWStyle_CircularPattern": CircularCommand}


def register():
    for name, cls in COMMANDS.items():
        try:
            if name not in Gui.listCommands():
                Gui.addCommand(name, cls())
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (name, error))
