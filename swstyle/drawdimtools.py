
"""Dimension Palette (beside the picked dimensions, fading as the pointer moves away; Arrange buttons for several),
Align (Align Collinear/Radial, Align Parallel/Concentric, Space Evenly, Group / Break Alignment, Auto Arrange),
Autodimension, Ordinate dimensions (with jogs when the texts crowd), Baseline dimensions, Chamfer Dimension and
the inference lines shown while a dimension's text is dragged (it snaps in line with the others).

Positions: a TechDraw dimension's X, Y is its text centre relative to its view's centre, in sheet mm (y up). View
geometry (getVertexByIndex) is unscaled about the view centre, y up: sheet = view position + geometry * scale."""

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
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D
from . import drawviews as DV
from . import drawannot as DA

V = App.Vector
FROM_MODEL = 10.0
BETWEEN = 6.0
ALIGN_SNAP = 1.0           # inference: a dragged text within 1mm of another's line snaps onto it
CHAMFER_FORMATS = ("1 X 45°", "45° X 1", "1 X 1", "C1")
SCHEMES = ("Baseline", "Chain", "Ordinate")


# --------------------------------------------------------------------------- dimensions on a sheet
def is_dim(o):
    return o is not None and getattr(o, "TypeId", "") == "TechDraw::DrawViewDimension"


def dims_on(page):
    return [o for o in page.Views if is_dim(o)]


def view_of(dim):
    for v, _s in dim.References2D or []:
        return v
    return None


def picked_dims():
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        o = s.Object
        if is_dim(o) and o not in out:
            out.append(o)
    return out


def orientation(dim):
    """'h' (measures across: DistanceX, or a Distance more across than up), 'v', 'r' (radius/diameter), or ''."""
    t = dim.Type
    if t == "DistanceX":
        return "h"
    if t == "DistanceY":
        return "v"
    if t in ("Radius", "Diameter"):
        return "r"
    if t == "Distance":
        pts = ref_points(dim)
        if len(pts) >= 2:
            return "h" if abs(pts[-1][0] - pts[0][0]) >= abs(pts[-1][1] - pts[0][1]) else "v"
    return ""


def ref_points(dim):
    """Sheet-offset points (view-relative, sheet mm) the dimension measures."""
    from . import drawdimpm as DP
    return [(p.x, p.y) for p in DP._ref_points(dim)]


def value(dim):
    try:
        from . import drawdimpm as DP
        return DP.value_of(dim)
    except Exception:
        return 0.0


def at(dim):
    return float(dim.X), float(dim.Y)


def put(dim, x=None, y=None):
    """Moves a dimension's text without dragging its alignment group along (our own arranging)."""
    was = GroupWatch._busy
    GroupWatch._busy = True
    try:
        if x is not None:
            dim.X = x
        if y is not None:
            dim.Y = y
    finally:
        GroupWatch._busy = was
    GroupWatch.note([dim])


def view_box(view):
    """(x0, y0, x1, y1) of the view's geometry, view-relative sheet mm."""
    k = DV.view_scale(view)
    xs, ys = [], []
    for _i, p in DA.vertices(view):
        xs.append(p.x * k)
        ys.append(p.y * k)
    if not xs:
        return -10, -10, 10, 10
    return min(xs), min(ys), max(xs), max(ys)


# --------------------------------------------------------------------------- Align
def align_collinear(dims):
    """Align Collinear/Radial: the texts on one line (linear: the first one's line; radial: the first one's angle
    from each centre)."""
    if len(dims) < 2:
        return False
    o = orientation(dims[0])
    x, y = at(dims[0])
    for d in dims[1:]:
        k = orientation(d)
        if k == "h":
            put(d, y=y)
        elif k == "v":
            put(d, x=x)
        elif k == "r" and o == "r":
            c0 = _centre(dims[0])
            c = _centre(d)
            if c0 is None or c is None:
                continue
            ang = math.atan2(y - c0[1], x - c0[0])
            r = math.hypot(float(d.X) - c[0], float(d.Y) - c[1])
            put(d, c[0] + r * math.cos(ang), c[1] + r * math.sin(ang))
    _group(dims, "collinear")
    return True


def _centre(dim):
    for v, sub in dim.References2D or []:
        subs = sub if isinstance(sub, (list, tuple)) else [sub]
        k = DV.view_scale(v)
        for s in subs:
            if s.startswith("Edge"):
                try:
                    c = v.getEdgeByIndex(int(s[4:])).Curve.Center
                    return c.x * k, c.y * k
                except Exception as _fw_err:
                    _fw_log("drawdimtools.py:159", _fw_err)
    return None


def align_parallel(dims, between=None):
    """Align Parallel/Concentric: the dimensions stacked evenly, the shortest nearest the model."""
    between = offsets()[1] if between is None else between
    groups = {}
    for d in dims:
        groups.setdefault(orientation(d), []).append(d)
    done = False
    for o, ds in groups.items():
        if o not in ("h", "v") or len(ds) < 2:
            continue
        ds.sort(key=lambda d: abs(value(d)))
        side = 1 if (at(ds[0])[1] if o == "h" else at(ds[0])[0]) >= 0 else -1
        base = min((abs(at(d)[1 if o == "h" else 0]) for d in ds))
        for n, d in enumerate(ds):
            c = side * (base + n * between)
            put(d, y=c) if o == "h" else put(d, x=c)
        _group(ds, "parallel")
        done = True
    return done


def space_evenly(dims):
    """Space Evenly Linear/Diametric: the texts between the outermost two at equal spacing."""
    groups = {}
    for d in dims:
        groups.setdefault(orientation(d), []).append(d)
    done = False
    for o, ds in groups.items():
        if len(ds) < 3:
            continue
        axis = 1 if o == "h" else 0
        ds.sort(key=lambda d: at(d)[axis])
        a, b = at(ds[0])[axis], at(ds[-1])[axis]
        for n, d in enumerate(ds):
            c = a + (b - a) * n / (len(ds) - 1)
            put(d, y=c) if axis == 1 else put(d, x=c)
        done = True
    return done


def auto_arrange(dims, between=None, from_model=None):
    """Auto Arrange: across dimensions stacked above the view, up dimensions to its right (or below/left when
    they already are there), FROM_MODEL off the model and BETWEEN apart; texts centred between the extension
    lines."""
    from . import drawdimpm as DP
    fm, bw = offsets()
    from_model = fm if from_model is None else from_model
    between = bw if between is None else between
    by_view = {}
    for d in dims:
        by_view.setdefault((view_of(d), orientation(d)), []).append(d)
    for (v, o), ds in by_view.items():
        if v is None or o not in ("h", "v"):
            continue
        x0, y0, x1, y1 = view_box(v)
        ds.sort(key=lambda d: abs(value(d)))
        if o == "h":
            above = sum(1 for d in ds if float(d.Y) >= (y0 + y1) / 2) >= len(ds) / 2.0
            for n, d in enumerate(ds):
                put(d, y=(y1 + from_model + n * between) if above else (y0 - from_model - n * between))
                DP.center_text(d)
        else:
            right = sum(1 for d in ds if float(d.X) >= (x0 + x1) / 2) >= len(ds) / 2.0
            for n, d in enumerate(ds):
                put(d, x=(x1 + from_model + n * between) if right else (x0 - from_model - n * between))
                DP.center_text(d)
        _group(ds, "parallel")
    try:
        spread_texts([d for d in dims if view_of(d) is not None])
    except Exception as _fw_err:
        _fw_log("drawdimtools.py:233", _fw_err)
    return True


def spread_texts(dims, gap=1.0):
    ""



    from . import drawdimlines as DL, drawlabelspread as LS
    by_view = {}
    for d in dims:
        v = view_of(d)
        if v is not None:
            by_view.setdefault(v.Name, (v, []))[1].append(d)
    moved = 0
    for v, ds in by_view.values():
        others = [o for o in v.Document.Objects if is_dim(o) and o not in ds and view_of(o) is v]
        alld = ds + others           # dimensions not being arranged are obstacles: they come first and stay
        labels = []
        for d in alld:
            hw, hh = DL.text_box(d)
            o = orientation(d) if d in ds else None
            labels.append({"x": float(d.X), "y": float(d.Y), "w": 2 * hw, "h": 2 * hh,
                           "axis": {"h": "x", "v": "y"}.get(o, "fixed")})
        order = [i for i in range(len(alld)) if labels[i]["axis"] == "fixed"] + \
            [i for i in range(len(alld)) if labels[i]["axis"] != "fixed"]
        for lb in labels:
            if lb["axis"] == "fixed":   # obstacles: they never move (written back below only for movers)
                lb["axis"] = "x"
        far = (1e9, 1e9, 1e9 + 1.0, 1e9 + 1.0)      # no keep-out: only text on text counts
        out = LS.spread([labels[i] for i in order], far, gap=gap)
        for i, (x, y) in zip(order, out):
            if i >= len(ds) or orientation(alld[i]) not in ("h", "v"):
                continue
            d = alld[i]
            if abs(x - float(d.X)) > 1e-6 or abs(y - float(d.Y)) > 1e-6:
                put(d, x=x, y=y)
                moved += 1
    return moved


# Group: dimensions aligned together move together (Break Alignment takes one out)
def _group(dims, kind):
    import uuid
    gid = "%s:%s" % (kind, uuid.uuid4().hex[:8])
    for d in dims:
        if "SWDimAlignGroup" not in d.PropertiesList:
            d.addProperty("App::PropertyString", "SWDimAlignGroup", "FreeCAD", "Dimension alignment group")
        d.SWDimAlignGroup = gid
    GroupWatch.start()


def break_alignment(dims):
    for d in dims:
        if "SWDimAlignGroup" in d.PropertiesList:
            d.SWDimAlignGroup = ""
    return True


def group_of(dim):
    g = getattr(dim, "SWDimAlignGroup", "") or ""
    if not g:
        return []
    return [o for o in dim.Document.Objects if is_dim(o) and o is not dim and getattr(o, "SWDimAlignGroup", "") == g]


class GroupWatch:
    """Dragging one dimension of an aligned group drags the rest along (collinear: they stay on one line;
    parallel: they keep their spacing)."""
    _on = None
    _busy = False
    _last = {}

    @classmethod
    def start(cls):
        if cls._on is None:
            cls._on = cls()
            App.addDocumentObserver(cls._on)

    def slotChangedObject(self, obj, prop):
        if GroupWatch._busy or prop not in ("X", "Y") or not is_dim(obj):
            return
        g = getattr(obj, "SWDimAlignGroup", "") or ""
        key = obj.Document.Name + "." + obj.Name
        new = float(getattr(obj, prop))
        old = GroupWatch._last.get((key, prop))
        GroupWatch._last[(key, prop)] = new
        if not g or old is None or abs(new - old) < 1e-9:
            return
        o = orientation(obj)
        moving = (o == "h" and prop == "Y") or (o == "v" and prop == "X")
        if not moving:
            return
        GroupWatch._busy = True
        try:
            for d in group_of(obj):
                if orientation(d) == o:
                    setattr(d, prop, float(getattr(d, prop)) + (new - old))
                    GroupWatch._last[(d.Document.Name + "." + d.Name, prop)] = float(getattr(d, prop))
        finally:
            GroupWatch._busy = False

    @staticmethod
    def note(dims):
        for d in dims:
            for prop in ("X", "Y"):
                GroupWatch._last[(d.Document.Name + "." + d.Name, prop)] = float(getattr(d, prop))


# --------------------------------------------------------------------------- Dimension Palette
class DimensionPalette(QtWidgets.QFrame):
    ""



    def __init__(self):
        super().__init__(Gui.getMainWindow(), QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.setObjectName("SWDimensionPalette")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        from . import drawdimpm as DP
        from . import drawpmparts as PP
        row = QtWidgets.QHBoxLayout()
        self.style = QtWidgets.QComboBox(self)           # Style: the saved dimension styles (favorites)
        self.style.setObjectName("SWDimPaletteStyle")
        self.style.setToolTip("Style")
        self.style.activated.connect(lambda *_: self.do_style(self.style.currentText()))
        row.addWidget(self.style, 1)
        self.layer = QtWidgets.QComboBox(self)
        self.layer.setObjectName("SWDimPaletteLayer")
        self.layer.setToolTip("Layer")
        self.layer.activated.connect(lambda *_: self.do_layer(self.layer.currentText()))
        row.addWidget(self.layer, 1)
        lay.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.tol = QtWidgets.QComboBox(self)
        self.tol.setObjectName("SWDimPaletteTolerance")
        self.tol.addItems(DP.TOLERANCES)
        self.tol.setToolTip("Tolerance type")
        self.prec = QtWidgets.QComboBox(self)
        self.prec.setObjectName("SWDimPalettePrecision")
        self.prec.addItems(DP.PRECISIONS)
        self.prec.setToolTip("Unit precision")
        self.tprec = QtWidgets.QComboBox(self)
        self.tprec.setObjectName("SWDimPaletteTolPrecision")
        self.tprec.addItems(DP.PRECISIONS)
        self.tprec.setToolTip("Tolerance precision")
        for w in (self.tol, self.prec, self.tprec):
            row.addWidget(w)
        lay.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.plus = QtWidgets.QDoubleSpinBox(self)
        self.plus.setObjectName("SWDimPalettePlus")
        self.minus = QtWidgets.QDoubleSpinBox(self)
        self.minus.setObjectName("SWDimPaletteMinus")
        for w, t in ((self.plus, "Maximum variation"), (self.minus, "Minimum variation")):
            w.setRange(-1000, 1000)
            w.setDecimals(3)
            w.setSingleStep(0.01)
            w.setToolTip(t)
            row.addWidget(w)
        lay.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.text = QtWidgets.QLineEdit(self)
        self.text.setObjectName("SWDimPaletteText")
        self.text.setToolTip("Dimension text: <DIM> is the value")
        row.addWidget(self.text, 1)
        self.parens = QtWidgets.QToolButton(self)
        self.parens.setObjectName("SWDimPaletteParentheses")
        self.parens.setText("( )")
        self.parens.setCheckable(True)
        self.parens.setToolTip("Add Parentheses")
        self.center = QtWidgets.QToolButton(self)
        self.center.setObjectName("SWDimPaletteCenter")
        self.center.setText("|↔|")
        self.center.setToolTip("Center Dimension")
        self.inspect = QtWidgets.QToolButton(self)
        self.inspect.setObjectName("SWDimPaletteInspection")
        self.inspect.setText("(□)")
        self.inspect.setCheckable(True)
        self.inspect.setToolTip("Inspection Dimension")
        self.dual = QtWidgets.QToolButton(self)
        self.dual.setObjectName("SWDimPaletteDual")
        self.dual.setText("[ ]")
        self.dual.setCheckable(True)
        self.dual.setToolTip("Dual Dimension")
        for w in (self.parens, self.center, self.inspect, self.dual):
            row.addWidget(w)
        lay.addLayout(row)
        self.arrange = QtWidgets.QWidget(self)
        self.arrange.setObjectName("SWDimPaletteArrange")
        al = QtWidgets.QHBoxLayout(self.arrange)
        al.setContentsMargins(0, 0, 0, 0)
        self.arrange_buttons = {}
        for name, tip, fn in (("Auto Arrange", "Auto Arrange", auto_arrange),
                              ("Collinear", "Align Collinear/Radial", align_collinear),
                              ("Parallel", "Align Parallel/Concentric", align_parallel),
                              ("Space Evenly", "Space Evenly Linear/Diametric", space_evenly),
                              ("Break", "Break Alignment", break_alignment)):
            b = QtWidgets.QToolButton(self.arrange)
            b.setObjectName("SWDimPaletteArrange_" + name.replace(" ", ""))
            b.setText(name)
            b.setToolTip(tip)
            b.clicked.connect(lambda *_a, fn=fn, tip=tip: self.do_arrange(fn, tip))
            al.addWidget(b)
            self.arrange_buttons[name] = b
        self.arrange_head = QtWidgets.QLabel("Arrange Dimensions", self)
        self.arrange_head.setObjectName("SWDimPaletteArrangeHead")
        lay.addWidget(self.arrange_head)        # DW-4: the heading shows and hides with its row
        lay.addWidget(self.arrange)
        self.dims = []
        self._filling = False
        self.tol.currentIndexChanged.connect(self.changed)
        self.prec.currentIndexChanged.connect(self.changed)
        self.tprec.currentIndexChanged.connect(self.changed)
        self.plus.valueChanged.connect(self.changed)
        self.minus.valueChanged.connect(self.changed)
        self.text.editingFinished.connect(self.changed)
        self.parens.toggled.connect(self.changed)
        self.inspect.toggled.connect(self.changed)
        self.dual.toggled.connect(self.changed)
        self.center.clicked.connect(self.do_center)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.fade)
        self.opacity = 1.0

    # fill / write
    def show_for(self, dims, near=None):
        from . import drawdimpm as DP
        self.dims = list(dims)
        GroupWatch.note(self.dims)
        self._filling = True
        try:
            o = DP.options_of(self.dims[0])
            self.tol.setCurrentText(o.get("tol", DP.tolerance_of(self.dims[0])))
            self.prec.setCurrentText(o.get("precision", ".12"))
            self.tprec.setCurrentText(o.get("tol_precision", ".12"))
            self.plus.setValue(float(o.get("plus", 0.0)))
            self.minus.setValue(float(o.get("minus", 0.0)))
            self.text.setText(o.get("text", DP.DIM))
            self.parens.setChecked(bool(o.get("parens", False)))
            self.inspect.setChecked(bool(o.get("inspection", False)))
            self.dual.setChecked(bool(o.get("dual", False)))
            from . import drawpmparts as PP
            doc = self.dims[0].Document
            self.style.clear()
            self.style.addItem(PP.NONE_STYLE)
            self.style.addItems(sorted(PP.styles(doc, "Dimension")))
            PP.fill_layers(self.layer, doc, getattr(self.dims[0], "SWLayer", "") or PP.NONE_LAYER)
        finally:
            self._filling = False
        self.arrange.setVisible(len(self.dims) > 1)
        self.arrange_head.setVisible(len(self.dims) > 1)
        self.adjustSize()
        pos = near or QtGui.QCursor.pos()
        self.move(pos + QtCore.QPoint(18, 18))
        self.set_opacity(1.0)
        self.show()
        self.raise_()
        self.timer.start()

    def changed(self, *_):
        if self._filling or not self.dims:
            return
        from . import drawdimpm as DP
        doc = self.dims[0].Document
        doc.openTransaction("Dimension Palette")
        try:
            for d in self.dims:
                o = DP.options_of(d)
                o.update(tol=self.tol.currentText(), precision=self.prec.currentText(),
                         tol_precision=self.tprec.currentText(), plus=self.plus.value(), minus=self.minus.value(),
                         text=self.text.text() or DP.DIM, parens=self.parens.isChecked(),
                         inspection=self.inspect.isChecked(), dual=self.dual.isChecked())
                keys = DP.apply.__code__.co_varnames[1:DP.apply.__code__.co_argcount]
                DP.apply(d, **{k: v for k, v in o.items() if k in keys})
        finally:
            doc.commitTransaction()
        doc.recompute()

    def do_style(self, name):
        """Style: a saved dimension style goes onto the picked dimensions (as the Dimension PM's Style list)."""
        from . import drawdimpm as DP
        from . import drawpmparts as PP
        if not self.dims or name == PP.NONE_STYLE:
            return False
        vals = PP.styles(self.dims[0].Document, "Dimension").get(name)
        if not vals:
            return False
        pm = DP.DimensionPanel(self.dims[0], self.dims[1:])
        try:
            PP.restore(pm, {k: v for k, v in vals.items() if k not in pm._style_skip})
        finally:
            pm._end(True)
            pm.form.deleteLater()
        self.show_for(self.dims, self.pos() - QtCore.QPoint(18, 18))
        return True

    def do_layer(self, name):
        from . import drawpmparts as PP
        if not self.dims:
            return
        doc = self.dims[0].Document
        doc.openTransaction("Layer")
        try:
            for d in self.dims:
                try:
                    PP.apply_layer(d, name)
                except Exception as _fw_err:
                    _fw_log("drawdimtools.py:543", _fw_err)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        doc.recompute()

    def do_center(self):
        from . import drawdimpm as DP
        if not self.dims:
            return
        doc = self.dims[0].Document
        doc.openTransaction("Center Dimension")
        try:
            for d in self.dims:
                DP.center_text(d)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        doc.recompute()

    def do_arrange(self, fn, title):
        if not self.dims:
            return
        doc = self.dims[0].Document
        doc.openTransaction(title)
        try:
            fn(self.dims)
        finally:
            doc.commitTransaction()
        GroupWatch.note(self.dims)
        doc.recompute()

    # fade
    def set_opacity(self, a):
        self.opacity = a
        try:
            self.setWindowOpacity(a)
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:576", _fw_err)

    def distance(self, pos=None):
        pos = pos or QtGui.QCursor.pos()
        r = self.frameGeometry()
        dx = max(r.left() - pos.x(), 0, pos.x() - r.right())
        dy = max(r.top() - pos.y(), 0, pos.y() - r.bottom())
        return math.hypot(dx, dy)

    def fade(self):
        if not self.isVisible():
            self.timer.stop()
            return
        d = self.distance()
        a = 1.0 if d <= 15 else max(0.0, 1.0 - (d - 15) / 120.0)
        if a <= 0.0:
            self.hide()
            self.timer.stop()
            return
        self.set_opacity(a)


def palette():
    p = getattr(palette, "w", None)
    try:
        if p is not None:
            p.isVisible()
            return p
    except RuntimeError as _fw_err:
        _fw_log("drawdimtools.py:605", _fw_err)
    palette.w = DimensionPalette()
    return palette.w


def palette_enabled():
    """System Options > General: Show Dimension Palette (on unless turned off)."""
    try:
        return bool(D.system_option("General", "Enable dimension palette", True))
    except Exception:
        return True


class PaletteSelection:
    """Picking dimensions on a sheet brings the Dimension Palette up beside them."""

    def addSelection(self, doc, obj, sub, pnt):
        QtCore.QTimer.singleShot(0, self.update)

    def removeSelection(self, doc, obj, sub):
        QtCore.QTimer.singleShot(0, self.update)

    def setSelection(self, doc):
        QtCore.QTimer.singleShot(0, self.update)

    def clearSelection(self, doc):
        QtCore.QTimer.singleShot(0, self.update)

    DRAG_PX = 6
    _wait = None

    def held(self):
        return bool(QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton)

    def wait_release(self):
        ""

        if PaletteSelection._wait is None:
            PaletteSelection._wait = {"from": QtGui.QCursor.pos()}
            t = QtCore.QTimer()
            t.setInterval(40)
            PaletteSelection._wait["timer"] = t
            t.timeout.connect(self.poll)
            t.start()
        p = getattr(palette, "w", None)
        if p is not None and p.isVisible():
            p.hide()

    def poll(self):
        w = PaletteSelection._wait
        if w is None:
            return
        if self.held():
            return
        w["timer"].stop()
        PaletteSelection._wait = None
        moved = (QtGui.QCursor.pos() - w["from"]).manhattanLength()
        if moved > self.DRAG_PX:
            return                         # a drag: no palette over the dragged text
        self.update()

    def update(self):
        try:
            if self.held():
                self.wait_release()
                return
            dims = picked_dims()
            others = [s for s in Gui.Selection.getSelectionEx("", 0) if not is_dim(s.Object)]
            if dims and not others and palette_enabled():
                palette().show_for(dims)
            else:
                p = getattr(palette, "w", None)
                if p is not None:
                    p.hide()
        except Exception as e:
            App.Console.PrintWarning("FreeCAD: Dimension Palette: %s\n" % e)


# --------------------------------------------------------------------------- Ordinate dimensions
def _doc_row(doc, page, text, default):
    from . import drawdocprops
    return drawdocprops.row(doc, page, text, default)


def offsets(doc=None):
    ""

    doc = doc or App.ActiveDocument
    out = []
    for text, default in (("Offset from model", FROM_MODEL), ("Offset between dimensions", BETWEEN)):
        try:
            v = float(_doc_row(doc, "Dimensions", text, default))
            out.append(v if v > 0 else default)
        except Exception:
            out.append(default)
    return tuple(out)


def ordinate_svg(values, direction, line_off, text_h=DA.TEXT_SIZE, jog=True):
    """SVG body of an ordinate set about (0, 0) = the view centre. values: [(feature pos along, feature pos
    across, text)] in view-relative sheet mm; direction 'h' (texts on a line above/below at across = line_off)
    or 'v'. Texts too close get jogged apart (the extension line bends)."""
    out = []
    gap = text_h * 1.2
    order = sorted(range(len(values)), key=lambda i: values[i][0])
    placed = {}
    last = None
    for i in order:
        a = values[i][0]
        if jog and last is not None and a - last < gap:
            a = last + gap                       # Jog lines (Document Properties > Dimensions > Ordinate)
        placed[i] = a
        last = a
    for i, (a, c, text) in enumerate(values):
        t = placed[i]
        sgn = 1 if line_off >= c else -1
        knee = line_off - sgn * 2.0
        start = c + sgn * 1.0
        if direction == "h":
            pts = [(a, start), (a, knee - sgn * 1.5)] + ([(t, knee)] if abs(t - a) > 1e-6 else []) + [(t, line_off)]
            svg_pts = " ".join("%g,%g" % (x, -y) for x, y in pts)
            out.append('<polyline points="%s" fill="none" stroke="#000" stroke-width="0.25"/>' % svg_pts)
            tx, ty = t, line_off + sgn * (text_h * 0.3)
            out.append('<text x="%g" y="%g" font-size="%g" font-family="osifont,sans-serif" text-anchor="start" '
                       'transform="rotate(-90 %g %g)">%s</text>' % (tx + text_h * 0.35, -ty, text_h, tx + text_h * 0.35,
                                                                   -ty, DA._esc(text)))
        else:
            pts = [(start, a), (knee - sgn * 1.5, a)] + ([(knee, t)] if abs(t - a) > 1e-6 else []) + [(line_off, t)]
            svg_pts = " ".join("%g,%g" % (x, -y) for x, y in pts)
            out.append('<polyline points="%s" fill="none" stroke="#000" stroke-width="0.25"/>' % svg_pts)
            tx = line_off + sgn * 0.8
            out.append('<text x="%g" y="%g" font-size="%g" font-family="osifont,sans-serif" text-anchor="%s">%s</text>'
                       % (tx, -t + text_h * 0.35, text_h, "start" if sgn > 0 else "end", DA._esc(text)))
    return "".join(out), placed


def make_ordinate(page, view, base, points, direction="h", line_off=None, precision=2, jog=None, as_chain=None,
                  refs=None):
    ""



    doc = page.Document
    if line_off is None:
        x0, y0, x1, y1 = view_box(view)
        line_off = (y1 if direction == "h" else x1) + offsets(page.Document)[0]
    if jog is None:
        jog = bool(_doc_row(doc, "Ordinate", "Jog lines", True))
    if as_chain is None:
        as_chain = bool(_doc_row(doc, "Ordinate", "Display as chain dimension", False))
    allp = [base] + list(points)
    refs = list(refs) if refs is not None and len(refs) == len(allp) else [-1] * len(allp)
    x0, y0 = D.view_position(view)
    s = DA.svg_symbol(page, "Ordinate", "", 10, (x0, y0), "Ordinate Dimension", "Ordinate")
    for name, kind, val in (("SWOrdinateView", "App::PropertyString", view.Name),
                            ("SWOrdinateDirection", "App::PropertyString", direction),
                            ("SWOrdinateLine", "App::PropertyFloat", line_off),
                            ("SWOrdinatePoints", "App::PropertyString", _pts_text(allp)),
                            ("SWOrdinateRefs", "App::PropertyString", ";".join(str(int(i)) for i in refs)),
                            ("SWOrdinateOptions", "App::PropertyString",
                             "%d|%d|%d" % (int(precision), bool(jog), bool(as_chain)))):
        s.addProperty(kind, name, "FreeCAD", "Ordinate dimension")
        setattr(s, name, val)
    redraw_ordinate(s)
    try:
        s.setExpression("X", "%s.X" % view.Name)
        s.setExpression("Y", "%s.Y" % view.Name)
    except Exception as _fw_err:
        _fw_log("drawdimtools.py:737", _fw_err)
    return s


def _pts_text(pts):
    return ";".join("%.6g,%.6g" % (p[0], p[1]) for p in pts)


def ordinate_points(s):
    return [tuple(float(c) for c in q.split(",")) for q in (s.SWOrdinatePoints or "").split(";") if q]


def ordinate_refs(s):
    pts = ordinate_points(s)
    try:
        refs = [int(i) for i in (getattr(s, "SWOrdinateRefs", "") or "").split(";") if i != ""]
    except ValueError:
        refs = []
    return refs if len(refs) == len(pts) else [-1] * len(pts)


def ordinate_options(s):
    """(precision, jog, display as chain) of an ordinate set."""
    try:
        n, j, c = (getattr(s, "SWOrdinateOptions", "") or "").split("|")
        return int(n), j == "1", c == "1"
    except ValueError:
        doc = s.Document
        return 2, bool(_doc_row(doc, "Ordinate", "Jog lines", True)), \
            bool(_doc_row(doc, "Ordinate", "Display as chain dimension", False))


def set_ordinate_options(s, precision=None, jog=None, as_chain=None):
    n, j, c = ordinate_options(s)
    n = n if precision is None else int(precision)
    j = j if jog is None else bool(jog)
    c = c if as_chain is None else bool(as_chain)
    if "SWOrdinateOptions" not in s.PropertiesList:
        s.addProperty("App::PropertyString", "SWOrdinateOptions", "FreeCAD", "Ordinate dimension")
    s.SWOrdinateOptions = "%d|%d|%d" % (n, j, c)


def _trail(text, doc):
    """Document Properties > Dimensions > Trailing zeroes, dimensions (usage run 11-27: the ordinate texts read
    120.00 next to the Model Items' 120). Smart trims a whole value's zeroes, Remove every trailing zero."""
    try:
        tz = str(_doc_row(doc, "Dimensions", "Trailing zeroes, dimensions", "Smart"))
    except Exception:
        tz = "Smart"
    if "." not in text:
        return text
    if tz == "Remove" or (tz == "Smart" and float(text) == int(float(text))):
        return text.rstrip("0").rstrip(".")
    return text


def _driven_hex():
    ""
    try:
        from . import drawdocprops
        c = drawdocprops.driven_color()
        return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c[:3])
    except Exception:
        return "#808080"


def redraw_ordinate(s):
    """The ordinate set drawn again from its points and options."""
    view = s.Document.getObject(s.SWOrdinateView)
    if view is None:
        return False
    precision, jog, as_chain = ordinate_options(s)
    direction = s.SWOrdinateDirection
    allp = ordinate_points(s)
    if not allp:
        return False
    k = DV.view_scale(view)
    ax = 0 if direction == "h" else 1
    across = 1 - ax
    base = allp[0]
    seen = set()
    ds = []
    for p in allp:
        d = round((p[ax] - base[ax]), 6)
        if d in seen:
            continue
        seen.add(d)
        ds.append((d, p))
    prev = {}
    if as_chain:                                 # Display as chain dimension: each value from the one before
        order = sorted(ds, key=lambda q: q[0])
        for n, (d, _p) in enumerate(order):
            prev[d] = order[n - 1][0] if n else d
    vals = []
    for d, p in ds:
        shown = d - prev[d] if as_chain else d
        vals.append((p[ax] * k, p[across] * k, _trail(("%%.%df" % precision) % abs(shown), s.Document)))
    line_off = float(s.SWOrdinateLine)
    body, placed = ordinate_svg(vals, direction, line_off, jog=jog)
    body = body.replace('stroke="#000"', 'stroke="%s"' % _driven_hex()).replace(
        '<text ', '<text fill="%s" ' % _driven_hex())
    reach = max([abs(v[0]) for v in vals] + [abs(v[1]) for v in vals] + [abs(line_off) + 15, 10])
    R = max(5.0, reach + 5.0)
    s.Symbol = ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
                % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))
    return True


def add_to_ordinate(s, picks):
    """Add To Ordinate: more vertices ((index, geometry point)) dimensioned from the same zero."""
    pts, refs = ordinate_points(s), ordinate_refs(s)
    have = set(i for i in refs if i >= 0)
    n = 0
    for i, q in picks:
        if i is not None and i >= 0 and i in have:
            continue
        pts.append((q[0], q[1]))
        refs.append(-1 if i is None else int(i))
        have.add(i)
        n += 1
    s.SWOrdinatePoints = _pts_text(pts)
    if "SWOrdinateRefs" not in s.PropertiesList:
        s.addProperty("App::PropertyString", "SWOrdinateRefs", "FreeCAD", "Ordinate dimension")
    s.SWOrdinateRefs = ";".join(str(i) for i in refs)
    redraw_ordinate(s)
    return n


def realign_ordinate(s):
    """Re-Align Ordinate: the texts back on one line FROM_MODEL off the view (the side they were on)."""
    view = s.Document.getObject(s.SWOrdinateView)
    if view is None:
        return False
    x0, y0, x1, y1 = view_box(view)
    k = DV.view_scale(view)
    lo, hi = (y0, y1) if s.SWOrdinateDirection == "h" else (x0, x1)
    cur = float(s.SWOrdinateLine)
    fm = offsets(s.Document)[0]
    s.SWOrdinateLine = (hi + fm) if cur >= (lo + hi) / 2 else (lo - fm)
    return redraw_ordinate(s)


def toggle_jog(s):
    """Jog: the extension lines bend to keep crowded texts apart, or run straight."""
    n, j, c = ordinate_options(s)
    set_ordinate_options(s, jog=not j)
    redraw_ordinate(s)
    return not j


def refresh_ordinates(doc, view=None):
    """Ordinate sets follow their vertices (the model changed): returns the ones drawn again."""
    out = []
    for s in doc.Objects:
        if getattr(s, "SWAnnotation", "") != "Ordinate" or not hasattr(s, "SWOrdinateRefs"):
            continue
        if view is not None and s.SWOrdinateView != view.Name:
            continue
        v = doc.getObject(s.SWOrdinateView)
        refs = ordinate_refs(s)
        if v is None or all(i < 0 for i in refs):
            continue
        pts = ordinate_points(s)
        new = list(pts)
        for n, i in enumerate(refs):
            if i < 0:
                continue
            try:
                q = v.getVertexByIndex(i).Point
            except Exception:
                continue
            new[n] = (q.x, q.y)
        if any(abs(a[0] - b[0]) > 1e-6 or abs(a[1] - b[1]) > 1e-6 for a, b in zip(pts, new)):
            s.SWOrdinatePoints = _pts_text(new)
            redraw_ordinate(s)
            out.append(s)
    return out


class _OrdinateFollow:
    """A view recomputed: its ordinate sets read their vertices again (after TechDraw has drawn it)."""

    def slotRecomputedObject(self, obj):
        try:
            if obj.TypeId in ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem") and any(
                    getattr(o, "SWOrdinateView", "") == obj.Name for o in obj.Document.Objects):
                key = (obj.Document.Name, obj.Name)
                QtCore.QTimer.singleShot(0, lambda k=key: self.later(k))
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:900", _fw_err)

    def later(self, key, tries=8):
        """TechDraw may still be drawing the view: look again a few times until its vertices have moved."""
        try:
            doc = App.getDocument(key[0])
            v = doc.getObject(key[1])
            if v is None:
                return
            if refresh_ordinates(doc, v):
                doc.recompute()
            elif tries > 0:
                QtCore.QTimer.singleShot(400, lambda: self.later(key, tries - 1))
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:914", _fw_err)


def ordinate_menu_items(s):
    """The ordinate set's own right-click items: Add To Ordinate, Re-Align Ordinate, Jog."""
    from . import rcmenus
    n, jog, c = ordinate_options(s)

    def add():
        from . import drawattach
        page = drawattach.page_of(s) or D.active_page()
        AddToOrdinatePanel.ORDINATE[0] = s
        D._show(AddToOrdinatePanel(page))

    def act(fn, title):
        doc = s.Document
        doc.openTransaction(title)
        try:
            fn(s)
        finally:
            doc.commitTransaction()
        doc.recompute()
    return [rcmenus.action("AddToOrdinate", "Add To Ordinate", add),
            rcmenus.action("ReAlignOrdinate", "Re-Align Ordinate", lambda: act(realign_ordinate, "Re-Align Ordinate")),
            rcmenus.action("OrdinateJog", "Jog", lambda: act(toggle_jog, "Jog"), checked=jog)]


def _wrap_menu():
    try:
        from . import drawmenu
    except Exception:
        return False
    if getattr(drawmenu, "_fw_ordinate", False):
        return True
    items0 = drawmenu.annotation_items

    def annotation_items(a, label_of=None):
        out = items0(a, label_of)
        if getattr(a, "SWAnnotation", "") == "Ordinate":
            try:
                extra = ordinate_menu_items(a)
                at = next((i for i, it in enumerate(out) if getattr(it, "key", "") == "MakeBlock"), len(out))
                out = out[:at] + extra + out[at:]
            except Exception as error:
                App.Console.PrintLog("FreeCAD: ordinate menu: %s\n" % error)
        return out
    drawmenu.annotation_items = annotation_items
    drawmenu._fw_ordinate = True
    return True


def ordinate_values(s):
    pts = ordinate_points(s)
    ax = 0 if s.SWOrdinateDirection == "h" else 1
    return [round(p[ax] - pts[0][ax], 6) for p in pts] if pts else []


# --------------------------------------------------------------------------- picking in views
def vertex_at(page, p, tol_mm=2.0):
    """(view, vertex index, geometry point) of the model vertex nearest sheet point p."""
    v = DV.view_at(page, p, tol_mm + 1.0)      # a corner of the view is on its edge
    if v is None or not v.isDerivedFrom("TechDraw::DrawViewPart"):
        return None, None, None
    g = DV.to_geometry(v, p)
    tol = tol_mm / max(DV.view_scale(v), 1e-9)
    best = None
    for i, q in DA.vertices(v):
        d = math.hypot(q.x - g[0], q.y - g[1])
        if d <= tol and (best is None or d < best[0]):
            best = (d, i, (q.x, q.y))
    return (v, best[1], best[2]) if best else (v, None, None)


def ordinate_pick(page, p, tol_mm=2.0):
    ""


    v = DV.view_at(page, p, tol_mm + 1.0)
    if v is None or not v.isDerivedFrom("TechDraw::DrawViewPart"):
        return None, None, None
    g = DV.to_geometry(v, p)
    tol = tol_mm / max(DV.view_scale(v), 1e-9)
    verts = DA.vertices(v)

    def vertex_of(x, y):
        best = min(verts, key=lambda iq: math.hypot(iq[1].x - x, iq[1].y - y), default=None)
        return best[0] if best is not None and math.hypot(best[1].x - x, best[1].y - y) < 1e-6 else -1
    near = min(((math.hypot(q.x - g[0], q.y - g[1]), i, q) for i, q in verts), default=None)
    hit = DA.edge_at(v, g, tol)
    # a hole's rim wins over a center mark line through it (the marks are lines of the view too)
    rim = min(((abs(math.hypot(g[0] - c.x, g[1] - c.y) - r), c, r) for _i, c, r in DA.circles(v)),
              key=lambda t: t[0], default=None)
    if rim is not None and rim[0] <= tol:
        c, r = rim[1], rim[2]
        corner = near is not None and near[0] <= tol * 0.5 and abs(math.hypot(near[2].x - c.x, near[2].y - c.y) - r) > 1e-6
        if not corner:
            return v, vertex_of(c.x, c.y), (c.x, c.y)
    if near is not None and near[0] <= tol:
        return v, near[1], (near[2].x, near[2].y)
    if hit is not None:
        import Part
        e = hit[1]
        try:
            q = e.distToShape(Part.Vertex(V(g[0], g[1], 0)))[1][0][0]
        except Exception:
            return v, None, None
        ends = [vertex_of(t.Point.x, t.Point.y) for t in e.Vertexes]
        ends = [i for i in ends if i >= 0]
        return v, (ends[0] if ends else -1), (q.x, q.y)
    return v, None, None


def _vertex_point(view, i, q):
    """The geometry point of vertex i of view (q when it is not found)."""
    try:
        for j, p in DA.vertices(view):
            if j == i:
                return (p.x, p.y)
    except Exception as _fw_err:
        _fw_log("drawdimtools.py:vertex_point", _fw_err)
    return q


def _edge_run(view, p, tol_mm=2.0):
    """'h' or 'v' when the sheet point p is on a straight horizontal or vertical edge of view (and not on a vertex
    or a hole), else None."""
    try:
        g = DV.to_geometry(view, p)
        tol = tol_mm / max(DV.view_scale(view), 1e-9)
        if any(math.hypot(q.x - g[0], q.y - g[1]) <= tol for _i, q in DA.vertices(view)):
            return None
        hit = DA.edge_at(view, g, tol)
        if hit is None or len(hit[1].Vertexes) != 2:
            return None
        a, b = hit[1].Vertexes[0].Point, hit[1].Vertexes[1].Point
        if hit[1].Curve.TypeId != "Part::GeomLine":
            return None
        if abs(a.y - b.y) < 1e-6:
            return "h"
        if abs(a.x - b.x) < 1e-6:
            return "v"
    except Exception as _fw_err:
        _fw_log("drawdimtools.py:edge_run", _fw_err)
    return None


def baseline(page, view, base, others, direction=None, from_model=None, between=None):
    ""


    fm, bw = offsets(page.Document)
    from_model = fm if from_model is None else from_model
    between = bw if between is None else between
    k = DV.view_scale(view)
    if direction is None and others:
        dx = abs(others[0][1][0] - base[1][0])
        dy = abs(others[0][1][1] - base[1][1])
        direction = "h" if dx >= dy else "v"
    x0, y0, x1, y1 = view_box(view)
    kind = "DistanceX" if direction == "h" else "DistanceY"
    ax = 0 if direction == "h" else 1
    made = []
    for n, (i, q) in enumerate(sorted(others, key=lambda o: abs(o[1][ax] - base[1][ax]))):
        if abs(q[ax] - base[1][ax]) < 1e-9:
            continue
        d = DA.dimension(page, view, kind, ["Vertex%d" % base[0], "Vertex%d" % i])
        mid = (base[1][ax] + q[ax]) / 2 * k
        if direction == "h":
            put(d, mid, y1 + from_model + len(made) * between)
        else:
            put(d, x1 + from_model + len(made) * between, mid)
        made.append(d)
    if len(made) > 1:
        _group(made, "parallel")
    return made


def chain(page, view, pts, direction, from_model=None):
    """Chain dimensions between consecutive points, on one line."""
    from_model = offsets(page.Document)[0] if from_model is None else from_model
    k = DV.view_scale(view)
    x0, y0, x1, y1 = view_box(view)
    ax = 0 if direction == "h" else 1
    kind = "DistanceX" if direction == "h" else "DistanceY"
    pts = sorted(pts, key=lambda o: o[1][ax])
    made = []
    for (i, a), (j, b) in zip(pts, pts[1:]):
        if abs(b[ax] - a[ax]) < 1e-9:
            continue
        d = DA.dimension(page, view, kind, ["Vertex%d" % i, "Vertex%d" % j])
        mid = (a[ax] + b[ax]) / 2 * k
        if direction == "h":
            put(d, mid, y1 + from_model)
        else:
            put(d, x1 + from_model, mid)
        made.append(d)
    if len(made) > 1:
        _group(made, "collinear")
    return made


def _seam_points(view):
    ""

    out = []
    for _i, e in DA.edges(view):
        try:
            if type(e.Curve).__name__ == "Circle" and e.isClosed():
                out.append(e.Vertexes[0].Point)
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:1051", _fw_err)
    return out


def unique_points(view, axis, picked=None):
    """One vertex per distinct coordinate along axis (0 x, 1 y), lowest first: [(index, point)]. A circle's
    seam vertex is left out (its centre counts)."""
    seen = {}
    seams = _seam_points(view)
    for i, q in DA.vertices(view):
        if picked is not None and i not in picked:
            continue
        if any(abs(q.x - p.x) < 1e-6 and abs(q.y - p.y) < 1e-6 for p in seams):
            continue
        key = round((q.x, q.y)[axis], 5)
        if key not in seen:
            seen[key] = (i, (q.x, q.y))
    return [seen[k] for k in sorted(seen)]


def autodimension(page, view, h_scheme="Baseline", v_scheme="Baseline", h_place="Above view", v_place="Right of view",
                  picked=None, h_on=True, v_on=True, h_origin=None, v_origin=None):
    ""


    made = []
    for on, axis, scheme, place, origin in ((h_on, 0, h_scheme, h_place, h_origin), (v_on, 1, v_scheme, v_place, v_origin)):
        if not on:
            continue
        pts = unique_points(view, axis, picked)
        if len(pts) < 2:
            continue
        if origin is not None and scheme != "Chain":
            k = min(range(len(pts)), key=lambda j: abs(pts[j][1][axis] - origin))
            pts = [pts[k]] + pts[:k] + pts[k + 1:]
        direction = "h" if axis == 0 else "v"
        flip = place in ("Below view", "Left of view")
        if scheme == "Ordinate":
            x0, y0, x1, y1 = view_box(view)
            fm = offsets(page.Document)[0]
            off = (y0 - fm if flip else y1 + fm) if axis == 0 else (x0 - fm if flip else x1 + fm)
            made.append(make_ordinate(page, view, pts[0][1], [p for _i, p in pts[1:]], direction, off,
                                      refs=[-1 if i is None else i for i, _p in pts]))
            continue
        ds = baseline(page, view, pts[0], pts[1:], direction) if scheme == "Baseline" else \
            chain(page, view, pts, direction)
        if flip:
            x0, y0, x1, y1 = view_box(view)
            for d in ds:
                if axis == 0:
                    put(d, y=y0 - (float(d.Y) - y1))
                else:
                    put(d, x=x0 - (float(d.X) - x1))
        made += ds
    return made


# --------------------------------------------------------------------------- Chamfer Dimension
CHAMFER_TOLERANCES = ("None", "Basic", "Bilateral", "Symmetric", "Limit", "MIN", "MAX")


def tol_text(value, text, kind, plus=0.0, minus=0.0, places=2, unit=""):
    ""

    f = "%%.%df" % max(0, places)

    def signed(v):
        return ("+" + f) % v if v >= 0 else f % v
    if kind == "Symmetric":
        return "%s±%s%s" % (text, f % abs(plus), unit)
    if kind == "Bilateral":
        return "%s %s%s/%s%s" % (text, signed(plus), unit, signed(minus), unit)
    if kind == "Limit":
        return "%s%s/%s%s" % (f % (value + plus), unit, f % (value + minus), unit)
    if kind == "Basic":
        return "[%s]" % text
    if kind in ("MIN", "MAX"):
        return "%s %s" % (text, kind)
    return text


def chamfer_text(chamfer, lead, fmt="1 X 45°", precision=2, length_tol=None, angle_tol=None):
    ""

    (a, b), (c, d) = chamfer, lead
    u = (b[0] - a[0], b[1] - a[1])
    w = (d[0] - c[0], d[1] - c[1])
    L = math.hypot(*u)
    lw = math.hypot(*w) or 1.0
    cos = abs(u[0] * w[0] + u[1] * w[1]) / ((L or 1.0) * lw)
    ang = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
    d1 = L * math.cos(math.radians(ang))        # along the lead-in edge
    d2 = L * math.sin(math.radians(ang))        # square to it
    f = "%%.%df" % precision
    a_txt = ("%.0f" % ang if abs(ang - round(ang)) < 0.05 else "%.1f" % ang) + "°"
    try:      # Document Properties > Dimensions > Chamfer > Angle precision ("0", ".1", ".12", ...)
        ap = str(_doc_row(App.ActiveDocument, "Chamfer", "Angle precision", "0"))
        n = len(ap.split(".", 1)[1]) if "." in ap else 0
        if n:
            a_txt = ("%%.%df" % n) % ang + "°"
    except Exception as _fw_err:
        _fw_log("drawdimtools.py:1152", _fw_err)
    lt = length_tol or ("None", 0.0, 0.0)
    at = angle_tol or ("None", 0.0, 0.0)
    an = len(a_txt.split(".", 1)[1]) - 1 if "." in a_txt else 0

    def L(v):
        return tol_text(v, f % v, lt[0], lt[1], lt[2], precision)

    def A():
        return tol_text(ang, a_txt, at[0], at[1], at[2], max(an, 1 if at[0] != "None" else 0), "°")
    if fmt == "45° X 1":
        return "%s X %s" % (A(), L(d1))
    if fmt == "1 X 1":
        return "%s X %s" % (L(d1), L(d2))
    if fmt == "C1" and abs(ang - 45) < 0.05:
        return "C%s" % L(d1)
    return "%s X %s" % (L(d1), A())


def _chamfer_body(page, view, chamfer, lead, text_at, text):
    """The chamfer dimension's svg body (leader to the middle of the chamfer edge, the text on a shoulder) and
    its reach."""
    k = DV.view_scale(view)
    x0, y0 = D.view_position(view)
    (a, b) = chamfer
    tip = (x0 + (a[0] + b[0]) / 2 * k, y0 + (a[1] + b[1]) / 2 * k)
    rx, ry = DA._rel(text_at, tip)
    tw = DA._text_width(text)
    side = 1 if rx < 0 else -1          # the shoulder runs towards the text
    sx = side * 4.0
    body = DA._arrow(rx, ry, sx * 0, 0) + \
        '<line x1="0" y1="0" x2="%g" y2="0" stroke="#000" stroke-width="%g"/>' % (sx, DA.STROKE) + \
        '<text x="%g" y="%g" font-size="%g" font-family="osifont,sans-serif" text-anchor="%s">%s</text>' % (
            sx + side * 1.0, DA.TEXT_SIZE * 0.35, DA.TEXT_SIZE, "start" if side > 0 else "end", DA._esc(text))
    return body, max(DA._reach(text_at, tip), tw + 6)


def _edges_text(chamfer, lead):
    return ";".join(",".join("%.6g" % v for v in (p[0][0], p[0][1], p[1][0], p[1][1])) for p in (chamfer, lead))


def _edges_of(text):
    try:
        out = []
        for part in text.split(";"):
            v = [float(x) for x in part.split(",")]
            out.append(((v[0], v[1]), (v[2], v[3])))
        return out[0], out[1]
    except Exception:
        return None


def make_chamfer_dimension(page, view, chamfer, lead, text_at, fmt="1 X 45°", precision=2, length_tol=None,
                           angle_tol=None):
    ""

    x0, y0 = D.view_position(view)
    text = chamfer_text(chamfer, lead, fmt, precision, length_tol, angle_tol)
    body, reach = _chamfer_body(page, view, chamfer, lead, text_at, text)
    s = DA.svg_symbol(page, "ChamferDimension", body, reach, text_at, "Chamfer Dimension", "ChamferDimension")
    tols = "%s;%s" % ("|".join(str(x) for x in (length_tol or ("None", 0, 0))),
                      "|".join(str(x) for x in (angle_tol or ("None", 0, 0))))
    for name, val in (("SWChamferView", view.Name), ("SWChamferText", text), ("SWChamferFormat", fmt),
                      ("SWChamferTolerance", tols), ("SWChamferEdges", _edges_text(chamfer, lead)),
                      ("SWChamferPrecision", str(precision))):
        s.addProperty("App::PropertyString", name, "FreeCAD", "Chamfer dimension")
        setattr(s, name, val)
    try:
        s.setExpression("X", "%s.X + %g mm" % (view.Name, text_at[0] - x0))
        s.setExpression("Y", "%s.Y + %g mm" % (view.Name, text_at[1] - y0))
    except Exception as _fw_err:
        _fw_log("drawdimtools.py:1223", _fw_err)
    return s


def _ch_lines(view):
    out = []
    for _i, e in DA.edges(view):
        if type(e.Curve).__name__ in ("Line", "LineSegment") and len(e.Vertexes) >= 2:
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            out.append(((a.x, a.y), (b.x, b.y)))
    return out


def _ch_dir(e):
    dx, dy = e[1][0] - e[0][0], e[1][1] - e[0][1]
    L = math.hypot(dx, dy) or 1.0
    return dx / L, dy / L


def _ch_parallel(e, f, tol=1e-3):
    u, w = _ch_dir(e), _ch_dir(f)
    return abs(u[0] * w[1] - u[1] * w[0]) < tol


def _ch_mid(e):
    return (e[0][0] + e[1][0]) / 2, (e[0][1] + e[1][1]) / 2


def _ch_touch(e, f, tol=1e-3):
    return any(math.hypot(p[0] - q[0], p[1] - q[1]) < tol for p in e for q in f)


def follow_chamfer(view, chamfer, lead):
    """The view's chamfer and lead-in edges now: the edge parallel to the old chamfer edge nearest it, and the
    edge parallel to the old lead-in edge that meets it. None when the chamfer is gone."""
    lines = _ch_lines(view)
    m = _ch_mid(chamfer)
    cands = sorted((e for e in lines if _ch_parallel(e, chamfer)),
                   key=lambda e: math.hypot(_ch_mid(e)[0] - m[0], _ch_mid(e)[1] - m[1]))
    for c in cands[:4]:
        leads = [e for e in lines if e is not c and _ch_parallel(e, lead) and _ch_touch(e, c)]
        if leads:
            ml = _ch_mid(lead)
            best = min(leads, key=lambda e: math.hypot(_ch_mid(e)[0] - ml[0], _ch_mid(e)[1] - ml[1]))
            return c, best
    return None


def refresh_chamfers(doc):
    ""
    for s in list(doc.Objects):
        if getattr(s, "SWAnnotation", "") != "ChamferDimension" or not hasattr(s, "SWChamferEdges"):
            continue
        try:
            view = doc.getObject(s.SWChamferView)
            old = _edges_of(s.SWChamferEdges)
            if view is None or old is None:
                continue
            got = follow_chamfer(view, *old)
            if got is None:
                continue
            tl = s.SWChamferTolerance.split(";")
            tol = lambda t: (t.split("|")[0], float(t.split("|")[1]), float(t.split("|")[2]))
            prec = int(getattr(s, "SWChamferPrecision", "2") or 2)
            text = chamfer_text(got[0], got[1], s.SWChamferFormat, prec, tol(tl[0]), tol(tl[1]))
            edges = _edges_text(*got)
            if text == s.SWChamferText and edges == s.SWChamferEdges:
                continue
            page = next((p for p in s.InList if p.TypeId == "TechDraw::DrawPage"), None)
            x0, y0 = D.view_position(view)
            at = (float(s.X), float(s.Y))
            body, reach = _chamfer_body(page, view, got[0], got[1], at, text)
            font = DA.doc_font(doc)
            if font:
                body = DA.with_font(body, font)
            R = max(5.0, reach + 5.0)
            s.Symbol = ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">'
                        '%s</svg>' % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))
            s.SWChamferText = text
            s.SWChamferEdges = edges
        except Exception as error:
            App.Console.PrintLog("FreeCAD: chamfer dimension: %s\n" % error)


# --------------------------------------------------------------------------- Display As Linear (circles)

# mark kept; it stays that circle's dimension (it follows the model) and can go back to Diameter or Radius.
# TechDraw has no linear dimension on a circle, so it measures between two points of ours on the circle's sides.
LINEAR_KINDS = ("Distance", "DistanceX", "DistanceY")


def _ref_parts(dim):
    out = []
    for o, subs in dim.References2D:
        for s in (subs if isinstance(subs, (list, tuple)) else [subs]):
            out.append((o, s))
    return out


def is_linear_round(dim):
    return bool(getattr(dim, "SWLinearOf", "")) and dim.Type in LINEAR_KINDS


def _circle_near(view, centre):
    best = None
    for i, c, r in DA.circles(view):
        dd = (c - centre).Length
        if best is None or dd < best[0]:
            best = (dd, i, c, r)
    return best[1:] if best is not None else None


def _linear_ends(c, r, kind):
    if kind == "DistanceY":
        return V(c.x, c.y - r, 0), V(c.x, c.y + r, 0)
    return V(c.x - r, c.y, 0), V(c.x + r, c.y, 0)


def _vertex_at(view, q):
    for i, p in DA.vertices(view):
        if abs(p.x - q.x) < 1e-4 and abs(p.y - q.y) < 1e-4:
            return "Vertex%d" % i
    return None


def _drop_points(view, dim):
    for tag in [t for t in (getattr(dim, "SWLinearTags", "") or "").split(";") if t]:
        try:
            view.removeCosmeticVertex(tag)
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:linear drop", _fw_err)
    dim.SWLinearTags = ""


def _place_linear(view, dim, c, r, kind):
    """dim measures across circle (c, r) as kind, between two points of ours on its sides."""
    _drop_points(view, dim)
    a, b = _linear_ends(c, r, kind)
    tags = [view.makeCosmeticVertex(a), view.makeCosmeticVertex(b)]
    view.Document.recompute([view])
    refs = [_vertex_at(view, a), _vertex_at(view, b)]
    if None in refs:
        raise RuntimeError("no points on the circle's sides")
    dim.SWLinearTags = ";".join(str(t) for t in tags)
    dim.SWLinearCentre = V(c.x, c.y, 0)
    dim.References2D = [(view, s) for s in refs]
    dim.Type = kind


def _diameter_spec(spec):
    spec = spec or "%.2w"
    lead = "(" if spec.startswith("(") else ""
    rest = spec[len(lead):]
    if rest.startswith("R"):
        rest = "⌀" + rest[1:]
    elif not rest.startswith("⌀"):
        rest = "⌀" + rest
    return lead + rest


def display_as_linear(dim, kind="DistanceX"):
    """Display As Linear: the circle's diameter as a linear dimension across it (horizontal unless asked)."""
    if is_linear_round(dim):
        return True
    if dim.Type not in ("Radius", "Diameter"):
        return False
    view, sub = _ref_parts(dim)[0]
    i = int(str(sub)[4:])
    hit = next(((c, r) for k, c, r in DA.circles(view) if k == i), None)
    if hit is None:
        return False
    for name, typ, doc in (("SWLinearOf", "App::PropertyString", "Display As Linear: the kind it was"),
                           ("SWLinearTags", "App::PropertyString", "Display As Linear: its points on the circle"),
                           ("SWLinearCentre", "App::PropertyVector", "Display As Linear: the circle's center")):
        if not hasattr(dim, name):
            dim.addProperty(typ, name, "FreeCAD", doc)
    was = dim.Type
    _place_linear(view, dim, hit[0], hit[1], kind)
    dim.SWLinearOf = was
    dim.FormatSpec = _diameter_spec(dim.FormatSpec)
    return True


def display_as_round(dim, kind):
    """Display As Diameter / Display As Radius on a dimension shown as linear: back on its circle."""
    if not is_linear_round(dim):
        return False
    view = _ref_parts(dim)[0][0]
    hit = _circle_near(view, App.Vector(dim.SWLinearCentre))
    if hit is None:
        return False
    _drop_points(view, dim)
    dim.References2D = [(view, "Edge%d" % hit[0])]
    dim.Type = kind
    spec = dim.FormatSpec or ""
    if kind == "Radius":
        spec = spec.replace("⌀", "R", 1)
    dim.FormatSpec = spec
    dim.SWLinearOf = ""
    return True


def refresh_linear_rounds(doc):
    """Dimensions shown as linear follow their circle (a model change, Set Vertical, Align to edge)."""
    for dim in list(doc.Objects):
        if dim.TypeId != "TechDraw::DrawViewDimension" or not is_linear_round(dim):
            continue
        try:
            view = _ref_parts(dim)[0][0]
            hit = _circle_near(view, App.Vector(dim.SWLinearCentre))
            if hit is None:
                continue
            i, c, r = hit
            a, b = _linear_ends(c, r, dim.Type)
            got = [o.getVertexByIndex(int(s[6:])).Point for o, s in _ref_parts(dim)]
            if len(got) == 2 and (got[0] - a).Length < 1e-6 and (got[1] - b).Length < 1e-6:
                continue
            _place_linear(view, dim, c, r, dim.Type)
            doc.recompute([dim])
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:refresh_linear_rounds", _fw_err)


# --------------------------------------------------------------------------- inference lines while dragging
def label_centre(page, dim):
    x0, y0 = D.view_position(view_of(dim)) if view_of(dim) is not None else (0.0, 0.0)
    return x0 + float(dim.X), y0 + float(dim.Y)


def inference(page, dim, p):
    """(snapped sheet point, [(x0, y0, x1, y1) inference lines]) for dim's text at sheet point p: in line with
    another dimension's text of the same kind (across texts share a height, up texts a column)."""
    return infer(page, view_of(dim), orientation(dim), p, dim)


def _drawing_option(text, default):
    """extapps83: Tools > Options > System Options > Drawings: that row's kept value."""
    try:
        from . import optionspages
        return optionspages.stored("Drawings", text, default)
    except Exception:
        return default


def infer(page, view, o, p, dim=None):
    """inference for a text of orientation o of view at sheet point p (dim: the one moved, None while placing)."""
    lines = []
    sx, sy = p
    best_x = best_y = None
    for d in dims_on(page):
        if d is dim:
            continue
        q = label_centre(page, d)
        if _drawing_option("Disable note/dimension inference", False):
            break                   # extapps83: System Options > Drawings
        if o in ("h", "r", "") and orientation(d) in ("h", o) and abs(q[1] - p[1]) <= ALIGN_SNAP:
            if best_y is None or abs(q[1] - p[1]) < abs(best_y[0] - p[1]):
                best_y = (q[1], q)
        if o in ("v", "r", "") and orientation(d) in ("v", o) and abs(q[0] - p[0]) <= ALIGN_SNAP:
            if best_x is None or abs(q[0] - p[0]) < abs(best_x[0] - p[0]):
                best_x = (q[0], q)
    if best_y:
        sy = best_y[0]
        lines.append((min(p[0], best_y[1][0]) - 5, sy, max(p[0], best_y[1][0]) + 5, sy))
    if best_x:
        sx = best_x[0]
        lines.append((sx, min(p[1], best_x[1][1]) - 5, sx, max(p[1], best_x[1][1]) + 5))
    if o in ("h", "v") and (best_y is None if o == "h" else best_x is None):
        try:
            got = _offset_band(page, view, (sx, sy), o, dim)
        except Exception as _fw_err:
            got = None
            _fw_log("drawdimtools.py:offset_snap", _fw_err)
        if got is not None:
            (sx, sy), line = got
            lines.append(line)
    return (sx, sy), lines


OFFSET_SNAP = 2.0          # a dragged dimension within 2 mm of an offset distance snaps onto it


def offset_snap(page, dim, p, o):
    ""


    return _offset_band(page, view_of(dim), p, o, dim)


def _offset_band(page, view, p, o, dim=None):
    if view is None:
        return None
    a, b, c, e = DV.view_box(view)
    off_model, between = offsets(page.Document)
    lo, hi = (b, e) if o == "h" else (a, c)
    at = p[1] if o == "h" else p[0]
    if lo <= at <= hi:
        return None                         # inside the view: no snap
    up = at > hi
    edge = hi if up else lo
    sign = 1.0 if up else -1.0
    marks = [edge + sign * off_model]
    for d in dims_on(page):
        if d is dim or view_of(d) is not view or orientation(d) != o:
            continue
        q = label_centre(page, d)[1 if o == "h" else 0]
        if (q - edge) * sign > 0:
            marks.append(q + sign * between)
    best = min(marks, key=lambda m: abs(m - at))
    if abs(best - at) > OFFSET_SNAP:
        return None
    if o == "h":
        return (p[0], best), (a, best, c, best)
    return (best, p[1]), (best, b, best, e)


class InferenceDrag(QtCore.QObject):
    ""


    def __init__(self):
        super().__init__()
        self.dim = None          # (document name, object name) — never a Qt item across events
        self.lines = []

    def _dim_under(self, page, p):
        """The dimension whose text is under sheet point p, found from the dimensions' own positions (no
        TechDraw graphics item is touched: they are rebuilt under us, and a press must reach TechDraw first)."""
        best = None
        for d in dims_on(page):
            if view_of(d) is None:
                continue
            q = label_centre(page, d)
            dx, dy = abs(q[0] - p[0]), abs(q[1] - p[1])
            if dx <= 6.0 and dy <= 3.0 and (best is None or dx + dy < best[0]):
                best = (dx + dy, d)
        return best[1] if best else None

    def eventFilter(self, obj, ev):
        if not isinstance(ev, QtCore.QEvent):
            return False          # a stale PySide wrapper can arrive here
        try:
            t = ev.type()
            if t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease):
                return False
            gv = obj.parent() if isinstance(obj, QtWidgets.QWidget) else None
            if not isinstance(gv, QtWidgets.QGraphicsView) or not gv.objectName().endswith("View"):
                return False
            page = D.active_page()
            if page is None or D.page_view(page) != gv:
                return False
            pos = ev.position().toPoint()
            if t == QtCore.QEvent.MouseButtonPress:
                pal = getattr(palette, "w", None)
                if pal is not None and pal.isVisible():
                    pal.hide()          # a click on the sheet sends the palette away (a new pick brings it back)
            if t == QtCore.QEvent.MouseButtonPress and ev.button() == QtCore.Qt.LeftButton:
                settle_labels(page)     # before TechDraw takes the press: a click that deselects writes no step
                self.start = D.to_sheet(gv.mapToScene(pos))
                d = self._dim_under(page, self.start)
                InferenceDrag.pressed = d.Name if d is not None else "-"
                self.dim = (d.Document.Name, d.Name) if d is not None else None
                self.at0 = label_centre(page, d) if d is not None else None
            elif t == QtCore.QEvent.MouseMove and self.dim and ev.buttons() & QtCore.Qt.LeftButton:
                d = App.getDocument(self.dim[0]).getObject(self.dim[1])
                p = D.to_sheet(gv.mapToScene(pos))
                q = (self.at0[0] + p[0] - self.start[0], self.at0[1] + p[1] - self.start[1])
                _s, lines = inference(page, d, q)
                self.show_lines(gv, lines)
            elif t == QtCore.QEvent.MouseButtonRelease and self.dim:
                key = self.dim
                self.dim = None
                self.clear()
                QtCore.QTimer.singleShot(60, lambda: self.snap(key))
        except Exception as e:
            App.Console.PrintWarning("FreeCAD: dimension inference: %s\n" % e)
        return False

    def snap(self, key):
        try:
            d = App.getDocument(key[0]).getObject(key[1])
            page = D.active_page()
            if d is None or page is None:
                return
            p = label_centre(page, d)
            (sx, sy), lines = inference(page, d, p)
            if lines:
                x0, y0 = D.view_position(view_of(d))
                put(d, sx - x0, sy - y0)
                d.Document.recompute()
            InferenceDrag.last_snap = (key, bool(lines))
        except Exception as e:
            App.Console.PrintWarning("FreeCAD: dimension inference: %s\n" % e)

    def show_lines(self, gv, lines):
        self.clear()
        pen = QtGui.QPen(QtGui.QColor(0, 120, 215))
        pen.setStyle(QtCore.Qt.DashLine)
        pen.setCosmetic(True)
        for x0, y0, x1, y1 in lines:
            a, b = D.to_scene(x0, y0), D.to_scene(x1, y1)
            it = QtWidgets.QGraphicsLineItem(a.x(), a.y(), b.x(), b.y())
            it.setPen(pen)
            it.setZValue(1e6)
            gv.scene().addItem(it)
            self.lines.append(it)
        InferenceDrag.shown = len(lines)

    def clear(self):
        for it in self.lines:
            try:
                sc = it.scene()
                if sc is not None:
                    sc.removeItem(it)
            except RuntimeError as _fw_err:
                _fw_log("drawdimtools.py:1437", _fw_err)
        self.lines = []


# --------------------------------------------------------------------------- PropertyManagers
class _PickPanel(D._Panel):
    LAYER = True

    def build(self):
        self.say(self.HINT)
        self.view = None
        self.base = None
        self.others = []
        self.parameters()

    def parameters(self):
        pass


class OrdinatePanel(_PickPanel):
    TITLE = "Ordinate Dimension"
    PIXMAP = "TechDraw_ExtensionCreateHorizCoordDimension"
    HINT = "Click the zero (a vertex), then the vertices to dimension; OK places them."
    DIRECTION = None

    def parameters(self):
        box, lay = D._group("Ordinate", self.form)
        self.dir = QtWidgets.QComboBox(box)
        self.dir.setObjectName("SWOrdinateDirection")
        self.dir.addItems(["Horizontal", "Vertical"])
        if self.DIRECTION == "v":
            self.dir.setCurrentIndex(1)
        lay.addWidget(self.dir)
        self.lay.addWidget(box)


    # horizontal, left/right: vertical), then each edge or hole: every click adds its dimension at once (drawings-land282)
    def sheet_click(self, p):
        v, i, q = ordinate_pick(self.page, p)
        if self.view is None:
            if q is None:
                self.say("Click an edge, a vertex or a hole in a view: the zero.")
                return True
            self.view, self.base, self.set = v, (i, q), None
            self.say("Zero set. Click where the dimensions go, then each edge or hole to dimension.")
            return True
        if q is None or v is not self.view:
            self.place(p)
            return True
        if (i is not None and i >= 0 and i in [o[0] for o in self.others] + [self.base[0]]) or \
                any(math.hypot(q[0] - o[1][0], q[1] - o[1][1]) < 1e-6 for o in self.others + [self.base]):
            return True
        self.others.append((i, q))
        if self.set is None:
            self.make()
        else:
            add_to_ordinate(self.set, [(i, q)])
        self.doc.recompute()
        return True

    def make(self, direction=None, line_off=None):
        d = direction or ("h" if self.dir.currentIndex() == 0 else "v")
        self.set = make_ordinate(self.page, self.view, self.base[1], [q for _i, q in self.others], d, line_off,
                                 refs=[self.base[0]] + [i for i, _q in self.others])
        self.made.append(self.set)

    def place(self, p):
        """A click off the geometry after the zero: where the dimension line goes (and so its direction)."""
        x0, y0 = D.view_position(self.view)
        rx, ry = p[0] - x0, p[1] - y0
        bx0, by0, bx1, by1 = view_box(self.view)
        out_y = max(by0 - ry, ry - by1, 0.0)
        out_x = max(bx0 - rx, rx - bx1, 0.0)
        if self.DIRECTION:
            d = self.DIRECTION
        elif out_y or out_x:
            d = "h" if out_y >= out_x else "v"
        else:
            d = "h" if self.dir.currentIndex() == 0 else "v"
        self.dir.setCurrentIndex(0 if d == "h" else 1)
        line = ry if d == "h" else rx
        if self.set is None:
            self.make(d, line)
        else:
            self.set.SWOrdinateDirection = d
            self.set.SWOrdinateLine = line
            redraw_ordinate(self.set)
        self.doc.recompute()
        self.say("Click each edge or hole to dimension from the zero; OK or Esc ends.")

    def finish(self):
        if getattr(self, "set", None) is None and self.view is not None and self.others:   # picks given without clicks
            self.make()

    def reject(self):
        ""
        if getattr(self, "set", None) is not None:
            return self.accept()
        return super().reject()


class AddToOrdinatePanel(_PickPanel):
    TITLE = "Add To Ordinate"
    PIXMAP = "TechDraw_ExtensionCreateHorizCoordDimension"
    HINT = "Click the vertices to add to the ordinate dimensions; OK adds them."
    ORDINATE = [None]

    def parameters(self):
        self.ordinate = self.ORDINATE[0]
        self.view = self.doc.getObject(self.ordinate.SWOrdinateView) if self.ordinate is not None else None

    def sheet_click(self, p):
        v, i, q = vertex_at(self.page, p)
        if v is None or i is None or v is not self.view:
            self.say("Click a vertex in the ordinate dimensions' view.")
            return True
        if i not in [o[0] for o in self.others]:
            self.others.append((i, q))
        return True

    def finish(self):
        if self.ordinate is not None and self.others:
            add_to_ordinate(self.ordinate, self.others)


def make_angular_running(page, view, centre, ref, points, precision=2, arcs=None, as_chain=None):
    ""


    doc = page.Document
    if arcs is None:
        arcs = bool(_doc_row(doc, "Angular Running", "Extension line arcs", True))
    if as_chain is None:
        as_chain = bool(_doc_row(doc, "Angular Running", "Display as chain dimension", False))
    out, vals, reach = _angular_body(view, centre, ref, points, precision, arcs, as_chain)
    x0, y0 = D.view_position(view)
    s = DA.svg_symbol(page, "AngularRunning", "".join(out), reach, (x0, y0),
                      "Angular Running Dimension", "AngularRunning")
    pts = ";".join("%.6g,%.6g" % (q[0], q[1]) for q in [centre, ref] + list(points))
    for name, kind, val in (("SWAngularView", "App::PropertyString", view.Name),
                            ("SWAngularValues", "App::PropertyFloatList", vals),
                            ("SWAngularPoints", "App::PropertyString", pts),
                            ("SWAngularStyle", "App::PropertyString", "%d,%d,%d" % (precision, arcs, as_chain))):
        s.addProperty(kind, name, "FreeCAD", "Angular running dimension")
        setattr(s, name, val)
    try:
        s.setExpression("X", "%s.X" % view.Name)
        s.setExpression("Y", "%s.Y" % view.Name)
    except Exception as _fw_err:
        _fw_log("drawdimtools.py:1540", _fw_err)
    return s


def _angular_body(view, centre, ref, points, precision, arcs, as_chain):
    """The angular running dimension's svg pieces, its angles and reach."""
    doc = view.Document
    k = DV.view_scale(view)
    cx, cy = centre[0] * k, centre[1] * k
    a0 = math.atan2(ref[1] - centre[1], ref[0] - centre[0])
    rmax = max(math.hypot(q[0] - centre[0], q[1] - centre[1]) for q in [ref] + list(points)) * k
    R = rmax + offsets(doc)[0]

    def pt(ang, rad):
        return cx + rad * math.cos(ang), -(cy + rad * math.sin(ang))
    angs = sorted({round(math.degrees((math.atan2(q[1] - centre[1], q[0] - centre[0]) - a0) % (2 * math.pi)), 6)
                   for q in points} - {0.0})
    out = []
    vals = []
    prev = 0.0
    for deg in [0.0] + angs:
        ang = a0 + math.radians(deg)
        (x1, y1), (x2, y2) = pt(ang, 1.0), pt(ang, R + 2.0)
        out.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="0.25"/>' % (x1, y1, x2, y2))
        shown = deg - prev if as_chain and deg else deg
        prev = deg
        tx, ty = pt(ang, R + 3.5)
        out.append('<text x="%g" y="%g" font-size="%g" font-family="osifont,sans-serif" text-anchor="middle">%s</text>'
                   % (tx, ty, DA.TEXT_SIZE, DA._esc(("%%.%df\u00b0" % precision) % shown)))
        vals.append(shown)
    if arcs and angs:
        (sx, sy), (ex, ey) = pt(a0, R), pt(a0 + math.radians(angs[-1]), R)
        big = 1 if angs[-1] > 180 else 0
        out.append('<path d="M%g %g A%g %g 0 %d 0 %g %g" fill="none" stroke="#000" stroke-width="0.25"/>'
                   % (sx, sy, R, R, big, ex, ey))
    return out, vals, math.hypot(cx, cy) + R + 10


def refresh_angular_running(doc):
    ""

    for s in list(doc.Objects):
        if getattr(s, "SWAnnotation", "") != "AngularRunning" or not hasattr(s, "SWAngularPoints"):
            continue
        try:
            view = doc.getObject(s.SWAngularView)
            if view is None:
                continue
            old = [tuple(float(v) for v in q.split(",")) for q in s.SWAngularPoints.split(";")]
            verts = [(p.x, p.y) for _i, p in DA.vertices(view)]
            for _i, c, _r in DA.circles(view):
                verts.append((c.x, c.y) if hasattr(c, "x") else tuple(c[:2]))
            new = []
            for q in old:          # the nearest free vertex (a centred view shifts by half a model edit)
                free = [v for v in verts if v not in new]
                best = min(free, key=lambda v: math.hypot(v[0] - q[0], v[1] - q[1])) if free else None
                if best is None or math.hypot(best[0] - q[0], best[1] - q[1]) > 25.0:
                    new = None
                    break
                new.append(best)
            if not new:
                continue
            pts = ";".join("%.6g,%.6g" % q for q in new)
            if pts == s.SWAngularPoints:
                continue
            prec, arcs, chain = (int(v) for v in s.SWAngularStyle.split(","))
            out, vals, reach = _angular_body(view, new[0], new[1], new[2:], prec, bool(arcs), bool(chain))
            body = "".join(out)
            font = DA.doc_font(doc)
            if font:
                body = DA.with_font(body, font)
            R = max(5.0, reach + 5.0)
            s.Symbol = ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">'
                        '%s</svg>' % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))
            s.SWAngularValues = vals
            s.SWAngularPoints = pts
        except Exception as error:
            App.Console.PrintLog("FreeCAD: angular running dimension: %s\n" % error)


class AngularRunningPanel(_PickPanel):
    TITLE = "Angular Running Dimension"
    PIXMAP = "TechDraw_AngleDimension"
    HINT = "Click the center (a vertex), then the vertex at 0\u00b0, then the vertices to dimension; OK places them."

    def parameters(self):
        pass

    def sheet_click(self, p):
        v, i, q = vertex_at(self.page, p)
        if v is None or i is None:
            self.say("Click a vertex in a view.")
            return True
        if self.view is None:
            self.view, self.base, self.zero = v, (i, q), None
            self.say("Center set. Click the vertex at 0\u00b0.")
        elif v is self.view and getattr(self, "zero", None) is None and i != self.base[0]:
            self.zero = (i, q)
            self.say("0\u00b0 set. Click the vertices to dimension; OK places them.")
        elif v is self.view and i not in [o[0] for o in self.others] + [self.base[0], self.zero[0]]:
            self.others.append((i, q))
        return True

    def finish(self):
        if self.view is None or getattr(self, "zero", None) is None or not self.others:
            return
        self.made.append(make_angular_running(self.page, self.view, self.base[1], self.zero[1],
                                              [q for _i, q in self.others]))


class HorizontalOrdinatePanel(OrdinatePanel):
    TITLE = "Horizontal Ordinate Dimension"
    DIRECTION = "h"


class VerticalOrdinatePanel(OrdinatePanel):
    TITLE = "Vertical Ordinate Dimension"
    PIXMAP = "TechDraw_ExtensionCreateVertCoordDimension"
    DIRECTION = "v"


class BaselinePanel(_PickPanel):
    TITLE = "Baseline Dimension"
    PIXMAP = "TechDraw_ExtensionCreateHorizCoordDimension"
    HINT = "Click the base (an edge end, a vertex or a hole), then each one to dimension from it."


    def sheet_click(self, p):
        v, i, q = ordinate_pick(self.page, p)
        if v is None or i is None or i < 0:
            self.say("Click a vertex, an edge end or a hole in a view.")
            return True
        q = _vertex_point(v, i, q)          # usage run 11-27: the dimension measures the vertex, not the pointer
        if self.view is None:
            self.view, self.base = v, (i, q)

            run = _edge_run(v, p)
            if run and getattr(self, "_dir", None) is None:
                self._dir = "h" if run == "v" else "v"
            self.say("Base set. Click each one to dimension.")
        elif v is self.view and i != self.base[0] and i not in [o[0] for o in self.others]:
            ax = {"h": 0, "v": 1}.get(getattr(self, "_dir", None))
            if ax is not None and self.GROUP and abs(q[ax] - self.base[1][ax]) < 1e-6:
                self.say("That one is level with the base. Click a vertex, a hole or an edge across from it.")
                return True
            self.others.append((i, q))
            self.redo()
        return True

    def build_dims(self):
        return baseline(self.page, self.view, self.base, self.others)

    def newest(self):
        """The dimension of the last click only, stacked one step further out (drawings-land287: the ones placed
        before, perhaps dragged or edited meanwhile, are left alone)."""
        fm, bw = offsets(self.page.Document)
        if getattr(self, "_dir", None) is None:
            q0, q1 = self.base[1], self.others[0][1]
            self._dir = "h" if abs(q1[0] - q0[0]) >= abs(q1[1] - q0[1]) else "v"
        n = getattr(self, "_slot", 0)       # a slot is never given twice, even after a placed one is deleted
        made = baseline(self.page, self.view, self.base, self.others[-1:], self._dir, fm + n * bw, bw)
        self._slot = n + len(made)
        return made

    GROUP = "parallel"

    def redo(self):
        new = list(self.newest())
        if new and self.GROUP:
            live = [o for o in self.made if self.doc.getObject(o.Name) is not None]
            gid = next((getattr(o, "SWDimAlignGroup", "") for o in live if getattr(o, "SWDimAlignGroup", "")), "")
            if gid:
                for d in new:
                    if "SWDimAlignGroup" not in d.PropertiesList:
                        d.addProperty("App::PropertyString", "SWDimAlignGroup", "FreeCAD", "Dimension alignment group")
                    d.SWDimAlignGroup = gid
            elif live:
                _group(live + new, self.GROUP)
        self.made += new
        self.doc.recompute()

    def finish(self):
        if self.view is not None and self.others and not self.made:     # picks given without clicks
            self.made = list(self.build_dims())

    def reject(self):
        ""
        if self.made:
            return self.accept()
        return super().reject()


class ChainPanel(BaselinePanel):
    ""
    TITLE = "Chain Dimension"
    HINT = "Click the first one (an edge end, a vertex or a hole), then the next ones in turn."
    GROUP = None            # each chain dimension stands alone, as before

    def build_dims(self):
        pts = [self.base] + list(self.others)
        out = []
        for a, b in zip(pts, pts[1:]):
            out += baseline(self.page, self.view, a, [b])
        return out

    def newest(self):
        pts = [self.base] + list(self.others)
        return baseline(self.page, self.view, pts[-2], [pts[-1]])


def chamfer_format_index(doc=None):
    """Options > Document Properties > Dimensions > Chamfer > Format, as the index into CHAMFER_FORMATS (0: 1 X 45°)."""
    try:
        want = str(_doc_row(doc or App.ActiveDocument, "Chamfer", "Format", CHAMFER_FORMATS[0]))
        return CHAMFER_FORMATS.index(want) if want in CHAMFER_FORMATS else 0
    except Exception:
        return 0


class ChamferDimensionPanel(D._Panel):
    TITLE = "Chamfer Dimension"
    PIXMAP = "TechDraw_ExtensionCreateHorizChamferDimension"
    LAYER = True
    HINT = "Click the chamfer edge, then a lead-in edge, then where the text goes."

    def build(self):
        self.say(self.HINT)
        box, lay = D._group("Chamfer Text Format", self.form)
        self.fmt = QtWidgets.QButtonGroup(box)
        for n, t in enumerate(CHAMFER_FORMATS):
            b = QtWidgets.QRadioButton(t, box)
            b.setObjectName("SWChamferFormat%d" % n)
            self.fmt.addButton(b, n)
            lay.addWidget(b)
        self.fmt.button(chamfer_format_index(getattr(self, "doc", None))).setChecked(True)
        self.prec = QtWidgets.QComboBox(box)
        self.prec.setObjectName("SWChamferPrecision")
        self.prec.addItems(["None", ".1", ".12", ".123", ".1234"])
        self.prec.setCurrentText(".12")
        lay.addWidget(self.prec)
        self.lay.addWidget(box)
        box, lay = D._group("Tolerance/Precision", self.form)
        self.tols = {}
        for key, label, unit in (("length", "Length tolerance:", ""), ("angle", "Angle tolerance:", "°")):
            lay.addWidget(QtWidgets.QLabel(label, box))
            kind = QtWidgets.QComboBox(box)
            kind.setObjectName("SWChamferTol" + key.capitalize())
            kind.addItems(CHAMFER_TOLERANCES)
            row = QtWidgets.QHBoxLayout()
            spins = []
            for side, default in (("Max", 0.1 if key == "length" else 1.0), ("Min", -0.1 if key == "length" else -1.0)):
                sp = QtWidgets.QDoubleSpinBox(box)
                sp.setObjectName("SWChamferTol%s%s" % (key.capitalize(), side))
                sp.setRange(-1000, 1000)
                sp.setDecimals(3 if key == "length" else 2)
                sp.setSingleStep(0.01 if key == "length" else 0.5)
                sp.setValue(default)
                if unit:
                    sp.setSuffix(unit)
                row.addWidget(sp)
                spins.append(sp)
            lay.addWidget(kind)
            lay.addLayout(row)

            def follow(text, spins=spins):
                spins[0].setVisible(text in ("Bilateral", "Symmetric", "Limit"))     # hidden, never greyed
                spins[1].setVisible(text in ("Bilateral", "Limit"))
            kind.currentTextChanged.connect(follow)
            follow(kind.currentText())
            self.tols[key] = (kind, spins)
        self.lay.addWidget(box)
        self.edges = []
        self.view = None

    def sheet_click(self, p):
        if len(self.edges) < 2:
            # the edge-pick reach: an outline edge lies on the view's box, so a click on it may fall just outside
            v = DV.view_at(self.page, p, 2.0)
            if v is None or not v.isDerivedFrom("TechDraw::DrawViewPart"):
                self.say("Click an edge in a view.")
                return True
            hit = DA.line_at(v, DV.to_geometry(v, p), 2.0 / DV.view_scale(v))
            if hit is None:
                self.say("Click a straight edge.")
                return True
            if self.view is not None and v is not self.view:
                return True
            self.view = v
            i, a, b = hit
            self.edges.append(((a.x, a.y), (b.x, b.y)))
            self.say("Click a lead-in edge." if len(self.edges) == 1 else "Click where the text goes.")
            return True
        n = self.prec.currentIndex()
        lt, at = (tuple([k.currentText()] + [sp.value() for sp in spins]) for k, spins in
                  (self.tols["length"], self.tols["angle"]))
        self.made.append(make_chamfer_dimension(self.page, self.view, self.edges[0], self.edges[1], p,
                                                CHAMFER_FORMATS[self.fmt.checkedId()], max(0, n), lt, at))
        self.edges = []
        self.view = None
        self.doc.recompute()
        self.say(self.HINT)
        return True


def symmetric_text(dim):
    """Symmetric Linear Diametric Dimension: twice the distance from the centerline, with the diameter sign."""
    try:
        v = float(dim.getRawValue())
    except Exception as _fw_err:
        _fw_log("drawdimtools.py:1800", _fw_err)
        return None
    n = int(getattr(dim, "SWSymmetricPlaces", 2))
    return "\u2300" + ("%%.%df" % n) % (2 * abs(v))


def make_symmetric_diameter(page, view, edge, axis, at, places=2):
    """A linear dimension from a centerline (axis) to an edge that shows the diameter (twice the distance)."""
    (ia, a0, a1), (ib, b0, b1) = edge, axis
    vertical = abs(a1.x - a0.x) < abs(a1.y - a0.y)
    kind = "DistanceX" if vertical else "DistanceY"
    x0, y0 = D.view_position(view)
    dim = DA.dimension(page, view, kind, ["Edge%d" % ia, "Edge%d" % ib], (at[0] - x0, at[1] - y0))
    dim.addProperty("App::PropertyInteger", "SWSymmetricPlaces", "FreeCAD", "Symmetric Linear Diametric: decimals")
    dim.SWSymmetricPlaces = int(places)
    dim.addProperty("App::PropertyBool", "SWSymmetricDiameter", "FreeCAD", "Symmetric Linear Diametric Dimension")
    dim.SWSymmetricDiameter = True
    page.Document.recompute()
    t = symmetric_text(dim)
    if t:
        dim.Arbitrary = True
        dim.FormatSpec = t
    page.Document.recompute()
    return dim


def refresh_symmetric(doc):
    """Update View / Rebuild: the symmetric diametric dimensions' text worked out again from the model."""
    n = 0
    for dim in doc.Objects:
        if getattr(dim, "SWSymmetricDiameter", False):
            t = symmetric_text(dim)
            if t and dim.FormatSpec != t:
                dim.FormatSpec = t
                n += 1
    return n


class SymmetricDiameterPanel(D._Panel):
    TITLE = "Symmetric Linear Diametric Dimension"
    PIXMAP = "TechDraw_ExtensionInsertDiameter"
    LAYER = True
    HINT = "Click the edge, then the centerline it turns about, then where the dimension goes."

    def build(self):
        self.say(self.HINT)
        box, lay = D._group("Tolerance/Precision", self.form)
        self.prec = QtWidgets.QComboBox(box)
        self.prec.setObjectName("SWSymmetricPrecision")
        self.prec.addItems(["None", ".1", ".12", ".123", ".1234"])
        self.prec.setCurrentText(".12")
        lay.addWidget(self.prec)
        self.lay.addWidget(box)
        self.edges = []
        self.view = None

    def sheet_click(self, p):
        if len(self.edges) < 2:
            # the edge-pick reach: an outline edge lies on the view's box, so a click on it may fall just outside
            v = DV.view_at(self.page, p, 2.0)
            if v is None or not v.isDerivedFrom("TechDraw::DrawViewPart"):
                self.say("Click an edge in a view.")
                return True
            hit = DA.line_at(v, DV.to_geometry(v, p), 2.0 / DV.view_scale(v))
            if hit is None:
                self.say("Click a straight edge or a centerline.")
                return True
            if self.view is not None and v is not self.view:
                return True
            if self.edges:
                a0, a1 = self.edges[0][1], self.edges[0][2]
                b0, b1 = hit[1], hit[2]
                ua, ub = a1 - a0, b1 - b0
                if ua.Length < 1e-9 or ub.Length < 1e-9 or abs(ua.normalize().cross(ub.normalize()).z) > 1e-3:
                    self.say("The centerline must be parallel to the edge.")
                    return True
            self.view = v
            self.edges.append(hit)
            self.say("Click the centerline." if len(self.edges) == 1 else "Click where the dimension goes.")
            return True
        self.made.append(make_symmetric_diameter(self.page, self.view, self.edges[0], self.edges[1], p,
                                                 max(0, self.prec.currentIndex())))
        self.edges = []
        self.view = None
        self.say(self.HINT)
        return True


class AutodimensionPanel(D._Panel):
    TITLE = "Autodimension"
    PIXMAP = "TechDraw_Dimension"
    LAYER = True
    HINT = "Set the schemes, then click the view to dimension."

    def build(self):
        self.say(self.HINT)
        box, lay = D._group("Entities to Dimension", self.form)
        self.all = QtWidgets.QRadioButton("All entities in view", box)
        self.all.setObjectName("SWAutoDimAll")
        self.sel = QtWidgets.QRadioButton("Selected entities", box)
        self.sel.setObjectName("SWAutoDimSelected")
        self.all.setChecked(True)
        lay.addWidget(self.all)
        lay.addWidget(self.sel)
        self.lay.addWidget(box)
        self.sch = {}
        self.origin_ui = {}
        for key, title, places in (("h", "Horizontal Dimensions", ("Above view", "Below view")),
                                   ("v", "Vertical Dimensions", ("Right of view", "Left of view"))):
            box, lay = D._group(title, self.form)
            on = QtWidgets.QCheckBox(title, box)
            on.setObjectName("SWAutoDim_%s_on" % key)
            on.setChecked(True)
            lay.addWidget(on)
            scheme = QtWidgets.QComboBox(box)
            scheme.setObjectName("SWAutoDim_%s_scheme" % key)
            scheme.addItems(SCHEMES)
            lay.addWidget(scheme)
            place = QtWidgets.QComboBox(box)
            place.setObjectName("SWAutoDim_%s_place" % key)
            place.addItems(places)
            lay.addWidget(place)

            row = QtWidgets.QHBoxLayout()
            org = QtWidgets.QLineEdit("", box)
            org.setObjectName("SWAutoDim_%s_origin" % key)
            org.setReadOnly(True)
            org.setPlaceholderText("Origin: lower left of the view")
            pick = QtWidgets.QToolButton(box)
            pick.setText("Pick")
            pick.setCheckable(True)
            pick.setObjectName("SWAutoDim_%s_pick" % key)
            pick.setToolTip("Click a %s edge or a vertex of the view as the origin" %
                            ("vertical" if key == "h" else "horizontal"))
            pick.toggled.connect(lambda on, key=key: self.arm(key, on))
            row.addWidget(org, 1)
            row.addWidget(pick)
            lay.addLayout(row)
            self.lay.addWidget(box)
            self.sch[key] = (on, scheme, place)
            self.origin_ui[key] = (org, pick)
        self.origin = {"h": None, "v": None}
        self.picking = None

    def arm(self, key, on):
        if on:
            other = self.origin_ui["v" if key == "h" else "h"][1]
            if other.isChecked():
                other.setChecked(False)
            self.picking = key
            self.say("Click a %s edge or a vertex as the %s origin." % ("vertical" if key == "h" else "horizontal",
                                                                       "horizontal" if key == "h" else "vertical"))
        elif self.picking == key:
            self.picking = None
            self.say(self.HINT)

    def pick_origin(self, p):
        key = self.picking
        axis = 0 if key == "h" else 1
        v, ent = entity_at(self.page, p)
        val, name = None, ""
        if ent is not None and ent[0] == "vertex":
            val, name = ent[2][axis], "Vertex%d" % ent[1]
        elif ent is not None and ent[0] == "line":
            a, b = ent[2], ent[3]
            if abs(a[axis] - b[axis]) < 1e-6:          # square to the axis: a vertical edge for horizontal dims
                val, name = a[axis], "Edge%d" % ent[1]
        if val is None:
            self.say("Click a %s edge or a vertex of the view." % ("vertical" if key == "h" else "horizontal"))
            return True
        self.origin[key] = val
        org, pick = self.origin_ui[key]
        org.setText("%s@%s" % (name, v.Label))
        pick.setChecked(False)
        self.say("Origin set. " + self.HINT)
        return True

    def picked_vertices(self, v):
        out = set()
        for s in Gui.Selection.getSelectionEx("", 0):
            if s.Object is v:
                for n in s.SubElementNames:
                    if n.startswith("Vertex"):
                        out.add(int(n[6:]))
                    elif n.startswith("Edge"):
                        e = v.getEdgeByIndex(int(n[4:]))
                        for q in e.Vertexes:
                            for i, p in DA.vertices(v):
                                if (p - q.Point).Length < 1e-6:
                                    out.add(i)
        return out

    def sheet_click(self, p):
        if self.picking:
            return self.pick_origin(p)
        v = DV.view_at(self.page, p, 0.0)
        if v is None or not v.isDerivedFrom("TechDraw::DrawViewPart"):
            self.say("Click a view.")
            return True
        picked = self.picked_vertices(v) if self.sel.isChecked() else None
        (hon, hs, hp), (von, vs, vp) = self.sch["h"], self.sch["v"]
        self.made += autodimension(self.page, v, hs.currentText(), vs.currentText(), hp.currentText(),
                                   vp.currentText(), picked, hon.isChecked(), von.isChecked(),
                                   self.origin["h"], self.origin["v"])
        self.doc.recompute()
        self.say("%d dimensions added. Click another view, or OK." % len(self.made))
        return True

# --------------------------------------------------------------------------- Smart Dimension (land54)
PICK_POINT = 1.5            # mm on the sheet: a click this near a vertex picks the vertex
PICK_EDGE = 2.0             # mm on the sheet: ... this near an edge picks the edge
PICK_COLOUR = QtGui.QColor(255, 140, 0)
HOVER_COLOUR = QtGui.QColor(0, 120, 215)


def entity_at(page, p):
    ""


    v = DV.view_at(page, p, PICK_EDGE + 1.0)
    if v is None or not v.isDerivedFrom("TechDraw::DrawViewPart"):
        return None, None
    k = max(DV.view_scale(v), 1e-9)
    g = DV.to_geometry(v, p)
    best = None
    seams = set(_grid(sx, sy) for sx, sy in _seams(v))
    for i, q in DA.vertices(v):
        dist = math.hypot(q.x - g[0], q.y - g[1])
        if seams and _near_grid(q.x, q.y, seams):
            continue                 # a full circle's seam point: the circle is picked there, not a point
        if dist <= PICK_POINT / k and (best is None or dist < best[0]):
            best = (dist, i, (q.x, q.y))
    if best:
        return v, ("vertex", best[1], best[2])
    tol = PICK_EDGE / k
    hit_c = DA.circle_at(v, g, tol)
    hit_l = DA.line_at(v, g, tol)
    dc = abs(math.hypot(g[0] - hit_c[1].x, g[1] - hit_c[1].y) - hit_c[2]) if hit_c else None
    dl = DA._dist_seg(g, hit_l[1], hit_l[2]) if hit_l else None
    # a line through the circle's centre (its centre mark or centerline) crosses the circle where it is clicked:

    mark = bool(hit_c and hit_l) and DA._dist_seg((hit_c[1].x, hit_c[1].y), hit_l[1], hit_l[2]) < 1e-6
    if hit_c and (dl is None or dc <= dl or mark and dc <= tol):
        i, c, r = hit_c
        e = v.getEdgeByIndex(i)
        full = e.isClosed() or len(e.Vertexes) < 2
        return v, ("circle", i, (c.x, c.y), r, full)
    if hit_l:
        i, a, b = hit_l
        return v, ("line", i, (a.x, a.y), (b.x, b.y))
    return v, None


def _seams(view):
    """The points where TechDraw starts and ends each full circle, when no straight edge ends there."""
    ends, seams = [], []
    for _i, e in DA.edges(view):
        if type(e.Curve).__name__ == "Circle" and (e.isClosed() or len(e.Vertexes) < 2):
            seams += [(q.Point.x, q.Point.y) for q in e.Vertexes]
        else:
            ends += [(q.Point.x, q.Point.y) for q in e.Vertexes]
    if not seams:
        return seams
    grid = set(_grid(a, b) for a, b in ends)      # a set, not a scan of every end per seam (0.12 s a click
    return [s for s in seams if not _near_grid(s[0], s[1], grid)]      # on a 50-part view)


def _grid(x, y):
    return (int(round(x * 1e6)), int(round(y * 1e6)))


def _near_grid(x, y, grid):
    """True when point (x, y) is within 1e-6 of a point in grid (cells of _grid)."""
    gx, gy = _grid(x, y)
    return any((gx + i, gy + j) in grid for i in (-1, 0, 1) for j in (-1, 0, 1))


def _corner(a, b):
    """The point where lines a and b meet (their shared end, else where their lines cross), or None."""
    for p in (a[2], a[3]):
        for q in (b[2], b[3]):
            if abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6:
                return p
    (ux, uy), (wx, wy) = _dir(a), _dir(b)
    den = ux * wy - uy * wx
    if abs(den) < 1e-9:
        return None
    dx, dy = b[2][0] - a[2][0], b[2][1] - a[2][1]
    t = (dx * wy - dy * wx) / den
    return a[2][0] + ux * t, a[2][1] + uy * t


def angle_rays(a, b, m):
    ""

    c = _corner(a, b)
    if c is None:
        return None
    ua, ub = _dir(a), _dir(b)
    mx, my = m[0] - c[0], m[1] - c[1]
    best = None
    for sa in (1, -1):
        for sb in (1, -1):
            ra, rb = (ua[0] * sa, ua[1] * sa), (ub[0] * sb, ub[1] * sb)
            bis = (ra[0] + rb[0], ra[1] + rb[1])
            score = bis[0] * mx + bis[1] * my
            n = math.hypot(*bis) or 1.0
            score /= n
            # the sector between the two rays that holds m wins (the bisector alone picked the 45 degree
            # sector next to a 135 degree one the text was in)
            cab = ra[0] * rb[1] - ra[1] * rb[0]
            c1 = ra[0] * my - ra[1] * mx
            c2 = mx * rb[1] - my * rb[0]
            if abs(cab) > 1e-9 and c1 * cab >= 0 and c2 * cab >= 0:
                score += 1e6
            if best is None or score > best[0]:
                best = (score, ra, rb)
    return c, best[1], best[2]


def _ref(view, ent):
    return ("Vertex%d" if ent[0] == "vertex" else "Edge%d") % ent[1]


def _anchor(ent):
    """The point of an entity a distance is measured from (a circle's centre, a line's middle)."""
    if ent[0] == "vertex":
        return ent[2]
    if ent[0] == "circle":
        return ent[2]
    (ax, ay), (bx, by) = ent[2], ent[3]
    return (ax + bx) / 2.0, (ay + by) / 2.0


def _dir(ent):
    (ax, ay), (bx, by) = ent[2], ent[3]
    L = math.hypot(bx - ax, by - ay) or 1.0
    return (bx - ax) / L, (by - ay) / L


def _orient(ent, tol=1e-3):
    ux, uy = _dir(ent)
    if abs(uy) < tol:
        return "h"
    if abs(ux) < tol:
        return "v"
    return "s"


def _span_kind(a, b, m):
    ""

    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    in_x, in_y = x0 <= m[0] <= x1, y0 <= m[1] <= y1
    if abs(x1 - x0) < 1e-9:
        return "DistanceY"
    if abs(y1 - y0) < 1e-9:
        return "DistanceX"
    if in_x and not in_y:
        return "DistanceX"
    if in_y and not in_x:
        return "DistanceY"
    return "Distance"


FORCE = [None]      # Horizontal / Vertical / Angular / Radius-Diameter Dimension: the one kind the tool makes
FORCE_TITLE = {"DistanceX": "Horizontal Dimension", "DistanceY": "Vertical Dimension", "Angle": "Angular Dimension",
               "Circle": "Radius/Diameter Dimension"}


def smart_kind(picks, m):
    """smart_kind_free, held to the kind of the Horizontal / Vertical / Angular / Radius tool when one is on."""
    kind, centres = smart_kind_free(picks, m)
    force = FORCE[0]
    if force is None or kind is None:
        return kind, centres
    if force in ("DistanceX", "DistanceY"):
        if kind in ("Distance", "DistanceX", "DistanceY"):
            return force, centres
        return None, False
    if force == "Angle":
        return (kind, centres) if kind == "Angle" else (None, False)
    if force == "Circle":
        return (kind, centres) if kind in ("Radius", "Diameter") else (None, False)
    return kind, centres


def smart_kind_free(picks, m):
    """The dimension Smart Dimension makes of the picked entities with the text at geometry point m:
    (TechDraw type, needs circle centres) — a line's length, a circle's diameter, an arc's radius, an angle between
    two lines that are not parallel, else a distance (horizontal, vertical or aligned by where the text is)."""
    if is_arc_length(picks):
        return "ArcLength", False
    if len(picks) == 1:
        e = picks[0]
        if e[0] == "circle":
            return ("Diameter" if e[4] else "Radius"), False
        if e[0] == "line":
            if _orient(e) != "s":
                return "Distance", False
            return _span_kind(e[2], e[3], m), False
        return None, False
    a, b = picks[:2]
    if a[0] == "line" and b[0] == "line":
        ua, ub = _dir(a), _dir(b)
        if abs(ua[0] * ub[1] - ua[1] * ub[0]) > 1e-3:
            return "Angle", False
        o = _orient(a)
        return {"h": "DistanceY", "v": "DistanceX"}.get(o, "Distance"), False
    centres = a[0] == "circle" or b[0] == "circle"
    line = a if a[0] == "line" else b if b[0] == "line" else None
    if line is not None:
        o = _orient(line)
        return {"h": "DistanceY", "v": "DistanceX"}.get(o, "Distance"), centres
    return _span_kind(_anchor(a), _anchor(b), m), centres


def is_arc_length(picks):
    ""
    return len(picks) == 3 and picks[0][0] == "circle" and not picks[0][4] and \
        all(e[0] == "vertex" for e in picks[1:])


def arc_sweep(c, a, b):
    """(start angle, sweep) in radians of the arc from a to b about c, the shorter way round."""
    a1 = math.atan2(a[1] - c[1], a[0] - c[0])
    a2 = math.atan2(b[1] - c[1], b[0] - c[0])
    sw = (a2 - a1) % (2 * math.pi)
    if sw > math.pi:
        a1, sw = a2, 2 * math.pi - sw
    return a1, sw


def arc_length_value(picks):
    arc, p, q = picks
    return arc[3] * arc_sweep(arc[2], p[2], q[2])[1]


def arc_symbol(doc):
    """Document Properties > Dimensions > Arc Length: Display arc symbol."""
    return bool(_doc_row(doc, "Arc Length", "Display arc symbol", True))


def _arc_body(page, view, picks, at, precision):
    """The arc length dimension's svg pieces, its value and reach."""
    arc, p, q = picks
    k = DV.view_scale(view)
    c = arc[2]
    g = DV.to_geometry(view, at)
    R = max(math.hypot(g[0] - c[0], g[1] - c[1]), arc[3] + 3.0 / k) * k
    a1, sw = arc_sweep(c, p[2], q[2])
    cx, cy = c[0] * k, c[1] * k

    def pt(ang, rad):
        return cx + rad * math.cos(ang), -(cy + rad * math.sin(ang))
    r0 = arc[3] * k
    out = []
    for ang in (a1, a1 + sw):
        (x1, y1), (x2, y2) = pt(ang, r0 + 1.0), pt(ang, R + 1.5)
        out.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="0.25"/>' % (x1, y1, x2, y2))
    (sx, sy), (ex, ey) = pt(a1, R), pt(a1 + sw, R)
    out.append('<path d="M%g %g A%g %g 0 0 0 %g %g" fill="none" stroke="#000" stroke-width="0.25"/>'
               % (sx, sy, R, R, ex, ey))
    for ang, sgn in ((a1, 1), (a1 + sw, -1)):          # arrows point along the arc, outwards to the ends
        tip = pt(ang, R)
        t = ang + sgn * 3.0 / max(R, 1e-6)
        b1, b2 = pt(t, R - 0.5), pt(t, R + 0.5)
        out.append('<path d="M%g %g L%g %g L%g %g Z" fill="#000"/>' % (tip[0], tip[1], b1[0], b1[1], b2[0], b2[1]))
    value = arc_length_value(picks)
    text = ("%%.%df" % precision) % value
    if arc_symbol(page.Document):
        text = "\u2322" + text
    tx, ty = pt(a1 + sw / 2, R + 1.5)
    out.append('<text x="%g" y="%g" font-size="%g" font-family="osifont,sans-serif" text-anchor="middle">%s</text>'
               % (tx, ty, DA.TEXT_SIZE, DA._esc(text)))
    reach = math.hypot(cx, cy) + R + 10
    return out, value, reach


def make_arc_length(page, view, picks, at, precision=2):
    """An arc length dimension: a dimension arc concentric with the picked arc through the text place, its
    extension lines from the arc's ends, arrows, and the length (with the arc symbol, per Document Properties).
    It follows the model (refresh_arc_lengths)."""
    out, value, reach = _arc_body(page, view, picks, at, precision)
    arc = picks[0]
    x0, y0 = D.view_position(view)
    doc = page.Document
    doc.openTransaction("Smart Dimension")
    try:
        s = DA.svg_symbol(page, "ArcLength", "".join(out), reach, (x0, y0), "Arc Length Dimension", "ArcLength")
        for name, kind, val in (("SWArcLengthView", "App::PropertyString", view.Name),
                                ("SWArcLengthEdge", "App::PropertyInteger", int(arc[1])),
                                ("SWArcLengthValue", "App::PropertyFloat", value),
                                ("SWArcLengthAt", "App::PropertyString", "%.6g,%.6g" % (at[0] - x0, at[1] - y0)),
                                ("SWArcLengthPrecision", "App::PropertyInteger", int(precision)),
                                ("SWArcLengthGeom", "App::PropertyString", "%.6g,%.6g,%.6g" % (arc[2][0], arc[2][1], arc[3]))):
            s.addProperty(kind, name, "FreeCAD", "Arc length dimension")
            setattr(s, name, val)
        try:
            s.setExpression("X", "%s.X" % view.Name)
            s.setExpression("Y", "%s.Y" % view.Name)
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:2270", _fw_err)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return s


def smart_value(picks, kind, m=None):
    """The value the preview shows (model mm or degrees); m: where the text is (an angle's side)."""
    if kind == "ArcLength":
        return arc_length_value(picks)
    if kind in ("Diameter", "Radius"):
        r = picks[0][3]
        return 2 * r if kind == "Diameter" else r
    if len(picks) == 1:
        (ax, ay), (bx, by) = picks[0][2], picks[0][3]
        return {"DistanceX": abs(bx - ax), "DistanceY": abs(by - ay)}.get(kind, math.hypot(bx - ax, by - ay))
    a, b = picks[:2]
    if kind == "Angle":
        rays = angle_rays(a, b, m) if m is not None else None
        if rays is None:
            ua, ub = _dir(a), _dir(b)
            return math.degrees(math.acos(max(-1.0, min(1.0, abs(ua[0] * ub[0] + ua[1] * ub[1])))))
        _c, ra, rb = rays
        return math.degrees(math.acos(max(-1.0, min(1.0, ra[0] * rb[0] + ra[1] * rb[1]))))
    line = a if a[0] == "line" else b if b[0] == "line" else None
    if line is not None:
        other = b if line is a else a
        p = _anchor(other)
        (ax, ay) = line[2]
        ux, uy = _dir(line)
        return abs((p[0] - ax) * uy - (p[1] - ay) * ux)        # perpendicular distance
    p, q = _anchor(a), _anchor(b)
    return {"DistanceX": abs(q[0] - p[0]), "DistanceY": abs(q[1] - p[1])}.get(kind, math.hypot(q[0] - p[0], q[1] - p[1]))


def preview_text(picks, kind, m=None):
    try:
        val = smart_value(picks, kind, m)
    except Exception:
        return ""
    if kind == "Diameter":
        return "⌀%.2f" % val
    if kind == "Radius":
        return "R%.2f" % val
    if kind == "Angle":
        return "%.2f°" % val
    if kind == "ArcLength":
        return "\u2322%.2f" % val
    return "%.2f" % val


def _centre_ref(view, c):
    """A circle's centre as a point TechDraw can dimension: a cosmetic vertex there (made once)."""
    for i, q in DA.vertices(view):
        if abs(q.x - c[0]) < 1e-4 and abs(q.y - c[1]) < 1e-4:
            return "Vertex%d" % i
    view.makeCosmeticVertex(V(c[0], c[1], 0))
    view.Document.recompute([view])
    for i, q in DA.vertices(view):
        if abs(q.x - c[0]) < 1e-4 and abs(q.y - c[1]) < 1e-4:
            return "Vertex%d" % i
    return None


def _length(ent):
    (ax, ay), (bx, by) = ent[2], ent[3]
    return math.hypot(bx - ax, by - ay)


def _point_ref(view, q):
    """A point of the view TechDraw can dimension at geometry point q: its vertex there, else a cosmetic one."""
    for i, p in DA.vertices(view):
        if abs(p.x - q[0]) < 1e-4 and abs(p.y - q[1]) < 1e-4:
            return "Vertex%d" % i
    return _centre_ref(view, q)


def place_orientation(picks, kind):
    """'h' / 'v' for the text of a new dimension that measures across / up (the ones that snap), else ''."""
    if kind == "DistanceX":
        return "h"
    if kind == "DistanceY":
        return "v"
    if kind != "Distance" or not picks:
        return ""
    if len(picks) == 1 and picks[0][0] == "line":
        a, b = picks[0][2], picks[0][3]
    elif len(picks) == 2:
        a, b = _anchor(picks[0]), _anchor(picks[1])
    else:
        return ""
    dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
    if dy <= 1e-6 * max(dx, 1.0):
        return "h"
    if dx <= 1e-6 * max(dy, 1.0):
        return "v"
    return ""                       # aligned on a slant: placed where clicked


def place_snap(page, view, picks, p):
    ""


    try:
        kind = smart_kind(picks, DV.to_geometry(view, p))[0]
        o = place_orientation(picks, kind)
        if not o:
            return p, []
        q, lines = infer(page, view, o, p)
        if (q[0], q[1]) != (p[0], p[1]) and smart_kind(picks, DV.to_geometry(view, q))[0] != kind:
            return p, []            # the snap would turn it into another kind of dimension
        return q, lines
    except Exception as _fw_err:
        _fw_log("drawdimtools.py:place_snap", _fw_err)
        return p, []


def make_smart(page, view, picks, at):
    """The dimension Smart Dimension places for picks with its text at sheet point at."""
    g = DV.to_geometry(view, at)
    kind, centres = smart_kind(picks, g)
    if kind is None:
        return None
    if kind == "ArcLength":
        return make_arc_length(page, view, picks, at)
    refs = []
    if kind == "Angle":
        rays = angle_rays(picks[0], picks[1], g)
        if rays is not None:
            c, ra, rb = rays
            L = max(1.0, min(_length(picks[0]), _length(picks[1])) / 2.0)
            pts = [(c[0] + ra[0] * L, c[1] + ra[1] * L), c, (c[0] + rb[0] * L, c[1] + rb[1] * L)]
            r3 = [_point_ref(view, q) for q in pts]
            if all(r3):
                kind, refs = "Angle3Pt", r3
                picks = []
    for e in picks:
        if centres and e[0] == "circle":
            r = _centre_ref(view, e[2])
            if r is None:
                return None
            refs.append(r)
        else:
            refs.append(_ref(view, e))
    x0, y0 = D.view_position(view)
    doc = page.Document
    doc.openTransaction(TOOL_NAMES.get(FORCE[0], "Smart Dimension"))
    try:
        dim = DA.dimension(page, view, kind, refs, (at[0] - x0, at[1] - y0))
        try:
            from . import drawdocprops
            drawdocprops.apply_dimension(dim, dict(drawdocprops.defaults(), **drawdocprops.stored(doc)))
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:2384", _fw_err)
        doc.recompute()
        dim.X, dim.Y = at[0] - x0, at[1] - y0
    finally:
        doc.commitTransaction()
    doc.recompute()
    settle_labels(page)
    for ms in (150, 500, 1200):         # the PM and the snapping that follow still move it a little
        QtCore.QTimer.singleShot(ms, lambda: settle_labels(page))
    return dim



TOOL_NAMES = {"DistanceX": "Horizontal Dimension", "DistanceY": "Vertical Dimension", "Angle": "Angular Dimension",
              "Circle": "Radius/Diameter Dimension"}


def settle_labels(page):
    """A dimension placed or moved by code: FreeCAD's label counts any move as a drag and writes a "Drag
    Dimension" undo step the first time it is deselected, so one Smart Dimension left two steps (and Esc after it
    one more). The labels are told the move is over, signals held, so no step is written; what is picked stays
    picked."""
    try:
        gv = D.page_view(page)
        sc = gv.scene() if gv is not None else None
        if sc is None:
            return 0
        n = 0
        for item in sc.items():
            go = item.toGraphicsObject()
            if go is None or not go.metaObject().className().endswith("QGIDatumLabel"):
                continue
            held_scene, held = sc.blockSignals(True), go.blockSignals(True)
            try:
                was = go.isSelected()
                go.setSelected(not was)
                go.setSelected(was)
            finally:
                go.blockSignals(held)
                sc.blockSignals(held_scene)
            n += 1
        return n
    except Exception as _fw_err:
        _fw_log("drawdimtools.py:settle_labels", _fw_err)
        return 0


SMART_EVENTS = (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick,
                QtCore.QEvent.MouseMove, QtCore.QEvent.KeyPress)


def _first_filter(name, types, handler):
    """handler on the add-on's one application filter, ahead of the other handlers (a pick made while Smart
    Dimension is on is the tool's, not a view drag's or an arrow dot's)."""
    try:
        from . import events
        events.register(name, types, handler)
        for t in types:
            lst = events._BY_TYPE.get(t, [])
            mine = [h for h in lst if h[0] == name]
            lst[:] = mine + [h for h in lst if h[0] != name]
        return True
    except Exception:
        return False


class SmartDimension(QtCore.QObject):
    ""




    def __init__(self, page, gv):
        super().__init__(gv.viewport())
        self.page = page
        self.doc_name = page.Document.Name
        self.page_name = page.Name
        self.gv = gv
        self.view_name = None
        self.picks = []
        self.items = []           # our own preview graphics (never TechDraw's)
        self.hover = []
        self.made = []
        self.global_filter = _first_filter("draw.smartdim", SMART_EVENTS, self.eventFilter)
        if not self.global_filter:
            gv.viewport().installEventFilter(self)
            gv.installEventFilter(self)
        gv.viewport().setCursor(QtCore.Qt.CrossCursor)
        self.say("Select an edge, circle or point to dimension.")

    # ---- state
    def say(self, text):
        self.message = text
        if D.VIEW_PM and isinstance(D.VIEW_PM[0], SmartPickPanel):
            D.VIEW_PM[0].say(text)
        try:
            Gui.getMainWindow().statusBar().showMessage(FORCE_TITLE.get(FORCE[0], "Smart Dimension") + ": " + text)
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:2444", _fw_err)

    def view(self):
        doc = App.getDocument(self.doc_name) if self.doc_name in App.listDocuments() else None
        return doc.getObject(self.view_name) if doc is not None and self.view_name else None

    def done(self):
        PICK_SETTINGS.clear()
        self.clear(self.items)
        self.clear(self.hover)
        try:
            if self.global_filter:
                from . import events
                events.unregister("draw.smartdim")
            else:
                self.gv.viewport().removeEventFilter(self)
                self.gv.removeEventFilter(self)
            self.gv.viewport().unsetCursor()
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:2462", _fw_err)
        if SMART and SMART[0] is self:
            SMART[:] = []
            FORCE[0] = None
            if D.VIEW_PM and isinstance(D.VIEW_PM[0], SmartPickPanel):
                pan = D.VIEW_PM[0]
                D.VIEW_PM[:] = []
                pan.close_quietly()
        try:
            Gui.getMainWindow().statusBar().clearMessage()
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:2473", _fw_err)
        self.deleteLater()

    # ---- graphics
    def clear(self, items):
        for it in items:
            try:
                sc = it.scene()
                if sc is not None:
                    sc.removeItem(it)
            except RuntimeError as _fw_err:
                _fw_log("drawdimtools.py:2484", _fw_err)
        items[:] = []

    def _to_sheet(self, view, g):
        x0, y0 = D.view_position(view)
        k = DV.view_scale(view)
        return x0 + g[0] * k, y0 + g[1] * k

    def _path(self, view, ent):
        path = QtGui.QPainterPath()
        if ent[0] == "vertex":
            c = D.to_scene(*self._to_sheet(view, ent[2]))
            path.addEllipse(c, 8, 8)
        elif ent[0] == "line":
            a = D.to_scene(*self._to_sheet(view, ent[2]))
            b = D.to_scene(*self._to_sheet(view, ent[3]))
            path.moveTo(a)
            path.lineTo(b)
        else:
            e = view.getEdgeByIndex(ent[1])
            pts = e.discretize(48)
            for n, q in enumerate(pts):
                s = D.to_scene(*self._to_sheet(view, (q.x, q.y)))
                path.moveTo(s) if n == 0 else path.lineTo(s)
        return path

    def _add(self, items, path, colour, width=3, dash=False, z=1e6):
        pen = QtGui.QPen(colour)
        pen.setWidthF(width)
        pen.setCosmetic(True)
        if dash:
            pen.setStyle(QtCore.Qt.DashLine)
        it = QtWidgets.QGraphicsPathItem(path)
        it.setPen(pen)
        it.setZValue(z)
        self.gv.scene().addItem(it)
        items.append(it)
        return it

    def show_hover(self, view, ent):
        self.clear(self.hover)
        if view is not None and ent is not None:
            self._add(self.hover, self._path(view, ent), HOVER_COLOUR, 2)

    def show_preview(self, p):
        """The picked entities in orange and, from them to the pointer, the dimension's value."""
        self.clear(self.items)
        view = self.view()
        if view is None or not self.picks:
            return
        for e in self.picks:
            self._add(self.items, self._path(view, e), PICK_COLOUR, 3)
        g = DV.to_geometry(view, p)
        kind, _c = smart_kind(self.picks, g)
        if kind is None:
            self.preview = ""
            return
        self.preview = preview_text(self.picks, kind, g)
        self.preview_kind = kind
        p, lines = place_snap(self.page, view, self.picks, p)
        self.snapped = (p, lines)
        for x0_, y0_, x1_, y1_ in lines:
            band = QtGui.QPainterPath()
            band.moveTo(D.to_scene(x0_, y0_))
            band.lineTo(D.to_scene(x1_, y1_))
            self._add(self.items, band, PICK_COLOUR, 1, dash=True)
        m = D.to_scene(*p)
        path = QtGui.QPainterPath()
        for e in self.picks:
            a = D.to_scene(*self._to_sheet(view, _anchor(e)))
            if kind == "DistanceX":
                path.moveTo(a)
                path.lineTo(a.x(), m.y())
            elif kind == "DistanceY":
                path.moveTo(a)
                path.lineTo(m.x(), a.y())
            else:
                path.moveTo(a)
                path.lineTo(m)
        self._add(self.items, path, PICK_COLOUR, 1, dash=True)
        txt = QtWidgets.QGraphicsSimpleTextItem(self.preview)
        f = txt.font()
        f.setPointSizeF(35.0)          # scene units are 0.1mm: about a 3.5mm text, as the dimensions
        txt.setFont(f)
        txt.setBrush(QtGui.QBrush(PICK_COLOUR))
        r = txt.boundingRect()
        txt.setPos(m.x() - r.width() / 2, m.y() - r.height() - 5)
        txt.setZValue(1e6 + 1)
        self.gv.scene().addItem(txt)
        self.items.append(txt)

    # ---- clicks
    def click(self, p):
        page = self.page
        view, ent = entity_at(page, p)
        cur = self.view()
        arcs = bool(self.picks) and self.picks[0][0] == "circle" and not self.picks[0][4] and \
            all(e[0] == "vertex" for e in self.picks[1:]) and ent is not None and ent[0] == "vertex"
        can_add = ent is not None and (cur is None or view is cur) and (len(self.picks) < 2 or
                                                                          (arcs and len(self.picks) < 3))
        if can_add and self.picks:
            first = self.picks[0]
            if first[0] == "circle" and ent[0] == "circle" and ent[1] == first[1]:
                can_add = False
            if first == ent:
                can_add = False
        if can_add and not (self.picks and self.placeable() and ent is None):
            if not self.picks:
                self.view_name = view.Name
            self.picks.append(ent)
            self.say("Select another item, or click where the dimension goes." if len(self.picks) == 1 and
                     self.placeable() else "Click where the dimension goes." if self.placeable() else
                     "Select a second point or edge.")
            self.show_preview(p)
            return
        if self.picks and self.placeable():
            v = self.view()
            p = place_snap(page, v, self.picks, p)[0]
            dim = make_smart(page, v, self.picks, p)
            self.picks = []
            self.view_name = None
            self.clear(self.items)
            if dim is not None:
                self.made.append(dim.Name)
                try:
                    from . import drawdimpm
                    panel = drawdimpm.open_for(dim)  # the PM first: no context toolbar pops up for the pick
                    _pick_settings(dim, panel, page)
                    Gui.Selection.clearSelection()
                    try:            # the tool's own pick, not the user's: Ctrl+Z in the PM must not take it back
                        from . import pmundo     # (that deselect made TechDraw write the label's X/Y: a step)
                        busy = pmundo._busy
                    except Exception:
                        busy = [False]
                    was, busy[0] = busy[0], True
                    try:
                        Gui.Selection.addSelection(dim)
                    finally:
                        busy[0] = was
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: Smart Dimension PM: %s\n" % error)
            self.say("Select an edge, circle or point to dimension.")
            return
        if not self.picks:
            self.say("Select an edge, circle or point to dimension.")

    def placeable(self):
        """The picks so far make a dimension (a single point does not)."""
        if not self.picks:
            return False
        return smart_kind(self.picks, (0, 0))[0] is not None

    def _has_keys(self, obj):
        """The sheet window has the keyboard: its view, or the page window holding it (on Windows the keyboard
        often sits on the page window after a click on the CommandManager; the sheet's own keys took Esc then)."""
        focus = QtWidgets.QApplication.focusWidget()
        if obj is self.gv or obj is self.gv.viewport() or focus in (self.gv, self.gv.viewport()):
            return True
        try:
            from . import drawkeys
            return obj is focus and drawkeys._sheet_for(obj)[1] is self.gv
        except Exception:
            return False

    def eventFilter(self, obj, ev):
        if not isinstance(ev, QtCore.QEvent):
            return False          # a stale PySide wrapper can arrive here
        try:
            t = ev.type()
            if t == QtCore.QEvent.KeyPress and ev.key() == QtCore.Qt.Key_Escape and self._has_keys(obj):
                if self.picks:
                    self.picks = []
                    self.view_name = None
                    self.clear(self.items)
                    self.say("Select an edge, circle or point to dimension.")
                else:
                    self.done()
                return True
            if t == QtCore.QEvent.KeyPress:
                return False
            if obj is not self.gv.viewport():
                return False
            if t == QtCore.QEvent.MouseButtonPress:
                if ev.button() == QtCore.Qt.RightButton:
                    self.done()
                    return False             # the sheet's own right-click menu still opens
                if ev.button() == QtCore.Qt.LeftButton:
                    p = D.to_sheet(self.gv.mapToScene(ev.position().toPoint()))
                    self.click(p)
                    return True
            elif t == QtCore.QEvent.MouseButtonDblClick and ev.button() == QtCore.Qt.LeftButton:
                return True
            elif t == QtCore.QEvent.MouseMove:
                p = D.to_sheet(self.gv.mapToScene(ev.position().toPoint()))
                view, ent = entity_at(self.page, p)
                cur = self.view()
                self.show_hover(view if ent is not None and (cur is None or view is cur) else None, ent)
                if self.picks:
                    self.show_preview(p)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Smart Dimension: %s\n" % error)
        return False


SMART = []


PICK_SETTINGS = {}          # Smart Dimension's Style and Layer (its first PM) while the tool is on


def _pick_settings(dim, panel, page):
    """The Style and Layer picked in Smart Dimension's PM on a dimension it just placed."""
    style, layer = PICK_SETTINGS.get("style"), PICK_SETTINGS.get("layer")
    from . import drawpmparts as PP
    if style and style != PP.NONE_STYLE and panel is not None:
        vals = PP.styles(dim.Document, "Dimension").get(style)
        if vals:
            PP.restore(panel, vals)
    if layer and layer != "-None-":
        from . import drawextras
        drawextras.set_layer([dim], layer, page)


class SmartPickPanel:
    ""



    def __init__(self, page):
        self.page = page
        self.view = None
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWDrawPM")
        self.form.setWindowTitle("Dimension")
        self.form.setProperty("swstyle_pm_title", "Dimension")
        lay = QtWidgets.QVBoxLayout(self.form)
        tabs = QtWidgets.QHBoxLayout()
        for name in ("DimXpert", "Autodimension"):
            b = QtWidgets.QToolButton(self.form)
            b.setText(name)
            b.setObjectName("SWDimPMTab" + name)
            b.setCheckable(True)
            b.setChecked(name == "DimXpert")
            b.setAutoRaise(True)
            tabs.addWidget(b)
            if name == "Autodimension":
                b.clicked.connect(self.autodimension)
        tabs.addStretch(1)
        lay.addLayout(tabs)
        self.message = QtWidgets.QLabel("Select an edge, circle or point to dimension.", self.form)
        self.message.setWordWrap(True)
        self.message.setObjectName("SWDimPMMessage")
        box, bl = D._group("Message", self.form, False)
        bl.addWidget(self.message)
        lay.addWidget(box)
        box, bl = D._group("Dimension Assist Tools", self.form, False)
        self.smart = QtWidgets.QRadioButton("Smart dimensioning", box)
        self.smart.setObjectName("SWDimPMSmart")
        self.smart.setChecked(True)
        self.rapid = QtWidgets.QCheckBox("Rapid dimensioning", box)
        self.rapid.setObjectName("SWDimPMRapid")
        self.rapid.setChecked(True)
        self.dimx = QtWidgets.QRadioButton("DimXpert", box)
        self.dimx.setObjectName("SWDimPMDimXpert")
        for w in (self.smart, self.rapid, self.dimx):
            bl.addWidget(w)
        self.dimx.toggled.connect(lambda on: on and self.autodimension())
        lay.addWidget(box)
        # Style and Layer: the dimensions placed while the tool is on take them (the drawing's saved dimension
        # styles; its layers, as the Layer toolbar lists them)
        from . import drawpmparts as PP
        box, bl = D._group("Style", self.form, False)
        st = QtWidgets.QComboBox(box)
        st.setObjectName("SWDimPMStyle")
        st.addItem(PP.NONE_STYLE)
        try:
            st.addItems(sorted(PP.styles(page.Document, "Dimension")))
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:SmartPickPanel styles", _fw_err)
        st.setCurrentText(PICK_SETTINGS.get("style", PP.NONE_STYLE))
        st.currentTextChanged.connect(lambda t: PICK_SETTINGS.__setitem__("style", t))
        bl.addWidget(st)
        lay.addWidget(box)
        box, bl = D._group("Layer", self.form, False)
        ly = QtWidgets.QComboBox(box)
        ly.setObjectName("SWDimPMLayer")
        try:
            from . import drawextras
            ly.addItems([row[0] for row in drawextras.layers(page)])
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:SmartPickPanel layers", _fw_err)
            ly.addItem("-None-")
        ly.setCurrentText(PICK_SETTINGS.get("layer", "-None-"))
        ly.currentTextChanged.connect(lambda t: PICK_SETTINGS.__setitem__("layer", t))
        bl.addWidget(ly)
        lay.addWidget(box)
        lay.addStretch(1)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel   # no int(): PySide6 refuses it

    def say(self, text):
        try:
            self.message.setText(text)
        except RuntimeError as _fw_err:
            _fw_log("drawdimtools.py:2729", _fw_err)

    def _end_tool(self):
        if D.VIEW_PM and D.VIEW_PM[0] is self:
            D.VIEW_PM[:] = []
        if SMART:
            SMART[0].done()

    def accept(self):
        self._end_tool()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        return self.accept()

    def close_quietly(self):
        """Gives the PM's place to another (the placed dimension's PM): the tool stays on."""
        try:
            Gui.Control.closeDialog()
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:2750", _fw_err)

    def autodimension(self):
        page = self.page
        self._end_tool()
        try:
            Gui.Control.closeDialog()
        except Exception as _fw_err:
            _fw_log("drawdimtools.py:2758", _fw_err)
        QtCore.QTimer.singleShot(0, lambda: D._show(AutodimensionPanel(page)))


def _show_pick_panel(page):
    try:
        if D.VIEW_PM:
            D.VIEW_PM[0].close_quietly()
            D.VIEW_PM[:] = []
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()   # the Drawing View / Dimension PM gives its place to the Dimension PM
        if Gui.Control.activeDialog():
            return None              # another PM is open: the tool still works, as before
        pan = SmartPickPanel(page)
        Gui.Control.showDialog(pan)
        D.VIEW_PM[:] = [pan]
        return pan
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Dimension PM: %s\n" % error)
        return None


def smart_dimension(force=None):
    """Smart Dimension pressed with a sheet in front: on (or off when it is already on). force: the Horizontal,
    Vertical, Angular or Radius/Diameter Dimension tool (the same picking, one kind of dimension)."""
    page = D.active_page()
    gv = D.page_view(page) if page is not None else None
    if gv is None:
        return None
    if SMART:
        old = SMART[0]
        same = FORCE[0] == force
        old.done()
        if old.gv is gv and same:
            return None
    FORCE[0] = force
    if Gui.Control.activeDialog() and not D.VIEW_PM:
        Gui.Control.closeDialog()
    SMART[:] = [SmartDimension(page, gv)]
    _show_pick_panel(page)
    if force:
        SMART[0].say({"DistanceX": "Select the items for a horizontal dimension.",
                      "DistanceY": "Select the items for a vertical dimension.",
                      "Angle": "Select two lines for an angular dimension.",
                      "Circle": "Select a circle or an arc."}[force])
    return SMART[0]


# --------------------------------------------------------------------------- commands
COMMANDS = {
    "FreeWorks_DrawSmartDimension": ("Smart Dimension", "TechDraw_Dimension",
                                     "Dimensions what you pick: a length, diameter, radius, angle or distance."),
    "FreeWorks_DrawAutodimension": ("Autodimension", "TechDraw_Dimension",
                                    "Dimensions the points of a view in a baseline, chain or ordinate scheme."),
    "FreeWorks_DrawOrdinateDimension": ("Ordinate Dimension", "TechDraw_ExtensionCreateHorizCoordDimension",
                                        "Dimensions points from a zero, texts jogged apart when they crowd."),
    "FreeWorks_DrawHorizontalOrdinate": ("Horizontal Ordinate Dimension", "TechDraw_ExtensionCreateHorizCoordDimension",
                                         "Horizontal ordinate dimensions from a zero."),
    "FreeWorks_DrawVerticalOrdinate": ("Vertical Ordinate Dimension", "TechDraw_ExtensionCreateVertCoordDimension",
                                       "Vertical ordinate dimensions from a zero."),
    "FreeWorks_DrawAngularRunning": ("Angular Running Dimension", "TechDraw_AngleDimension",
                                     "Angles about a center, measured from one zero, on one circle."),
    "FreeWorks_DrawBaselineDimension": ("Baseline Dimension", "TechDraw_ExtensionCreateHorizCoordDimension",
                                        "Dimensions from one base point, stacked."),
    "FreeWorks_DrawChamferDimension": ("Chamfer Dimension", "TechDraw_ExtensionCreateHorizChamferDimension",
                                       "Dimensions a chamfer: pick the chamfer edge and a lead-in edge."),
    "FreeWorks_DrawSymmetricDiameter": ("Symmetric Linear Diametric Dimension", "TechDraw_ExtensionInsertDiameter",
                                        "Dimensions an edge from its centerline as a diameter (twice the distance)."),
    "FreeWorks_DrawPathLength": ("Path Length Dimension", "TechDraw_ExtensionArcLengthAnnotation",
                                 "The total length of the picked edges of a view (a path)."),
    "FreeWorks_DrawHorizontalDimension": ("Horizontal Dimension", "TechDraw_HorizontalDimension",
                                          "A horizontal dimension between two items."),
    "FreeWorks_DrawVerticalDimension": ("Vertical Dimension", "TechDraw_VerticalDimension",
                                        "A vertical dimension between two items."),
    "FreeWorks_DrawAngularDimension": ("Angular Dimension", "TechDraw_AngleDimension",
                                       "The angle between two lines."),
    "FreeWorks_DrawRadiusDimension": ("Radius/Diameter Dimension", "TechDraw_RadiusDimension",
                                      "The radius of an arc or the diameter of a circle."),
    "FreeWorks_DrawChainDimension": ("Chain Dimension", "TechDraw_ExtensionCreateHorizChainDimension",
                                     "Dimensions vertex to vertex in a chain."),
    "FreeWorks_DrawDimAutoArrange": ("Auto Arrange", "TechDraw_Dimension",
                                     "Spaces and aligns the picked dimensions round their views."),
    "FreeWorks_DrawDimAlignCollinear": ("Align Collinear/Radial", "TechDraw_Dimension",
                                        "Puts the picked dimensions' texts on one line."),
    "FreeWorks_DrawDimAlignParallel": ("Align Parallel/Concentric", "TechDraw_Dimension",
                                       "Stacks the picked dimensions evenly."),
    "FreeWorks_DrawDimSpaceEvenly": ("Space Evenly Linear/Diametric", "TechDraw_Dimension",
                                     "Spaces the picked dimensions' texts evenly."),
    "FreeWorks_DrawDimBreakAlignment": ("Break Alignment", "TechDraw_Dimension",
                                        "Takes the picked dimensions out of their alignment group."),
}
PATH_LENGTH = "TechDraw_ExtensionArcLengthAnnotation"


def path_edges_picked():
    """Edges of a drawing view are picked (what Path Length Dimension measures)."""
    try:
        for s in Gui.Selection.getSelectionEx("", 0):
            if s.Object.isDerivedFrom("TechDraw::DrawViewPart") and \
                    any(n.startswith("Edge") for n in s.SubElementNames):
                return True
    except Exception as _fw_err:
        _fw_log("drawdimtools.py:path edges", _fw_err)
    return False


FORCED = {"FreeWorks_DrawHorizontalDimension": "DistanceX", "FreeWorks_DrawVerticalDimension": "DistanceY",
          "FreeWorks_DrawAngularDimension": "Angle", "FreeWorks_DrawRadiusDimension": "Circle"}
PANELS = {"FreeWorks_DrawChainDimension": ChainPanel, "FreeWorks_DrawAutodimension": AutodimensionPanel, "FreeWorks_DrawOrdinateDimension": OrdinatePanel,
          "FreeWorks_DrawHorizontalOrdinate": HorizontalOrdinatePanel,
          "FreeWorks_DrawVerticalOrdinate": VerticalOrdinatePanel, "FreeWorks_DrawBaselineDimension": BaselinePanel,
          "FreeWorks_DrawChamferDimension": ChamferDimensionPanel,
          "FreeWorks_DrawSymmetricDiameter": SymmetricDiameterPanel,
          "FreeWorks_DrawAngularRunning": AngularRunningPanel}
ARRANGE = {"FreeWorks_DrawDimAutoArrange": auto_arrange, "FreeWorks_DrawDimAlignCollinear": align_collinear,
           "FreeWorks_DrawDimAlignParallel": align_parallel, "FreeWorks_DrawDimSpaceEvenly": space_evenly,
           "FreeWorks_DrawDimBreakAlignment": break_alignment}


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}

    def IsActive(self):
        page = D.active_page()
        if page is None or not D.sheet_shown(page):
            return False
        if self.name == "FreeWorks_DrawPathLength":
            # live once edges of a view are picked; before, the CommandManager's tool-first page asks for them
            # (TechDraw's own command is live on any sheet and answers an empty pick with an error box)
            return path_edges_picked() and not D.busy()
        if self.name in ARRANGE:
            n = len(picked_dims())
            return n >= (1 if self.name in ("FreeWorks_DrawDimBreakAlignment", "FreeWorks_DrawDimAutoArrange") else 2)
        return not D.busy()

    def Activated(self):
        page = D.active_page()
        if page is None:
            return
        if self.name == "FreeWorks_DrawPathLength":
            if path_edges_picked():
                Gui.runCommand(PATH_LENGTH, 0)
            return
        if self.name == "FreeWorks_DrawSmartDimension":
            smart_dimension()
            return
        if self.name in FORCED:
            smart_dimension(FORCED[self.name])
            return
        if self.name in ARRANGE:
            dims = picked_dims()
            doc = page.Document
            doc.openTransaction(self.text)
            try:
                ARRANGE[self.name](dims)
            finally:
                doc.commitTransaction()
            GroupWatch.note(dims)
            doc.recompute()
            return
        D._show(PANELS[self.name](page))


def _install_filter(f):
    try:
        from . import events
        events.register("drawdimtools", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                                         QtCore.QEvent.MouseButtonRelease), f.eventFilter)
    except Exception:
        QtWidgets.QApplication.instance().installEventFilter(f)


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    if getattr(register, "done", False):
        return
    register.done = True
    register.selection = PaletteSelection()
    Gui.Selection.addObserver(register.selection)
    register.follow = _OrdinateFollow()
    App.addDocumentObserver(register.follow)
    _wrap_menu()
    register.inference = InferenceDrag()
    _install_filter(register.inference)
    GroupWatch.start()


def follow_arc(view, cx, cy, r):
    """The view's arc now nearest the old one (centre, then radius): (edge index, centre, radius, start, end)."""
    best = None
    for i, e in DA.edges(view):
        if type(e.Curve).__name__ not in ("Circle", "ArcOfCircle") or len(e.Vertexes) < 2 or e.isClosed():
            continue
        c = e.Curve.Center
        score = math.hypot(c.x - cx, c.y - cy) + abs(e.Curve.Radius - r)
        if best is None or score < best[0]:
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            best = (score, i, (c.x, c.y), e.Curve.Radius, (a.x, a.y), (b.x, b.y))
    if best is None or best[0] > 5.0 + 0.5 * r:      # nothing like it left: the dimension stays as it is
        return None
    return best[1:]


def refresh_arc_lengths(doc):
    ""
    for s in list(doc.Objects):
        if getattr(s, "SWAnnotation", "") != "ArcLength" or not hasattr(s, "SWArcLengthGeom"):
            continue
        try:
            view = doc.getObject(s.SWArcLengthView)
            if view is None:
                continue
            cx, cy, r = (float(v) for v in s.SWArcLengthGeom.split(","))
            got = follow_arc(view, cx, cy, r)
            if got is None:
                continue
            i, c, rad, a, b = got
            picks = (("arc", i, c, rad), ("point", -1, a), ("point", -1, b))
            value = arc_length_value(picks)
            geom = "%.6g,%.6g,%.6g" % (c[0], c[1], rad)
            if abs(value - s.SWArcLengthValue) < 1e-6 and geom == s.SWArcLengthGeom:
                continue
            page = next((p for p in s.InList if p.TypeId == "TechDraw::DrawPage"), None)
            x0, y0 = D.view_position(view)
            ax, ay = (float(v) for v in s.SWArcLengthAt.split(","))
            out, value, reach = _arc_body(page, view, picks, (x0 + ax, y0 + ay), s.SWArcLengthPrecision)
            body = "".join(out)
            font = DA.doc_font(doc)
            if font:
                body = DA.with_font(body, font)
            R = max(5.0, reach + 5.0)
            s.Symbol = ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">'
                        '%s</svg>' % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))
            s.SWArcLengthValue = value
            s.SWArcLengthEdge = int(i)
            s.SWArcLengthGeom = geom
        except Exception as error:
            App.Console.PrintLog("FreeCAD: arc length dimension: %s\n" % error)
