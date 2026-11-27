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

from . import naming, paths, smallowance, smedgegeom, smflatten, smtear
from . import pmboxes
from .smbaseflange import NOT_YET, RELIEFS, ALLOWANCES, _box, _spin, _active_body


def _row(w, on):
    """Shows or hides w with its form row label (a row that does not apply is hidden, never greyed)."""
    try:
        lay = w.parentWidget().layout() if w.parentWidget() is not None else None
        if isinstance(lay, QtWidgets.QFormLayout) and hasattr(lay, "setRowVisible") and lay.indexOf(w) >= 0:
            lay.setRowVisible(w, bool(on))
            return
    except Exception:
        pass
    w.setVisible(bool(on))

COMMAND = "SWStyle_SMEdgeFlange"
TITLE = "Edge-Flange"
LABEL = "Edge-Flange"
LENGTH_SPECS = (("Outer Virtual Sharp", "Outer Sharp"), ("Inner Virtual Sharp", "Inner Sharp"),
                ("Tangent Bend", "Tangential"))

# the edge (Material Outside); its "Material Outside" puts the whole bend outside (Bend Outside).
POSITIONS = (("Material Inside", "Material Inside"), ("Material Outside", "Thickness Outside"),
             ("Bend Outside", "Material Outside"), ("Bend from Virtual Sharp", None), ("Tangent to Bend", None))
# (None: an Offset wall at the offset smedgegeom works out)
ANGLE_MODES = ("Perpendicular to face", "Parallel to face")
VERTEX_MODES = ("Perpendicular to flange plane", "Parallel to base flange")

RELIEF_TYPES = {"Rectangular": "Rectangle", "Obround": "Round", "Tear": None}


def _engine():
    import SheetMetalCmd
    return SheetMetalCmd


def is_edge_flange(obj):
    proxy = getattr(obj, "Proxy", None)
    return proxy is not None and type(proxy).__name__ == "SMBendWall"


def _root(obj):
    ""

    for item in [obj] + list(getattr(obj, "OutListRecursive", [])):
        if type(getattr(item, "Proxy", None)).__name__ in ("SWConvertSolid", "SWInsertBends"):
            return item
    try:
        import SheetMetalTools
        root = SheetMetalTools.getOriginalBendObject(obj)
    except Exception:
        root = None
    if root is None and type(getattr(obj, "Proxy", None)).__name__ == "SMBaseBend":
        root = obj
    return root


def _edge_on(base, edge):
    """The base object's edge matching an edge picked on another shape (the preview), else None."""
    for i, e in enumerate(base.Shape.Edges, 1):
        if abs(e.Length - edge.Length) < 1e-6 and e.CenterOfMass.distanceToPoint(edge.CenterOfMass) < 1e-6:
            return "Edge%d" % i
    return None


def make(base, edges):
    doc = base.Document
    engine = _engine()
    body = None
    for parent in base.InList:
        if parent.TypeId == "PartDesign::Body":
            body = parent
    body = body or _active_body(doc)
    doc.openTransaction(TITLE)
    try:
        obj = doc.addObject("PartDesign::FeaturePython", "Bend")
        engine.SMBendWall(obj, base, list(edges))
        if App.GuiUp:
            engine.SMViewProviderFlat(obj.ViewObject)
        if body is not None:
            body.addObject(obj)
        root = _root(base)
        if root is not None:
            try:
                obj.radius = root.Radius
            except Exception as _fw_err:
                _fw_log("smedgeflange.py:101", _fw_err)
            if hasattr(root, "SWReliefRatio"):
                obj.UseReliefFactor = bool(root.SWUseReliefRatio)
                obj.ReliefFactor = root.SWReliefRatio
                obj.reliefType = RELIEF_TYPES.get(root.SWAutoRelief) or "Rectangle"
                if root.SWAutoRelief == "Tear":
                    obj.UseReliefFactor = False
                    obj.reliefw = smtear.TEAR_WIDTH
                    obj.reliefd = smtear.depth("Rip", float(obj.radius), smedgegeom.thickness(obj))
        smedgegeom.ensure(obj)
        smedgegeom.mark_live(obj)
        obj.angle = 90.0
        obj.LengthSpec = "Outer Sharp"
        obj.BendType = "Material Inside"
        obj.Label = naming.next_label(doc, LABEL)
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:119", _fw_err)
        doc.recompute()
        return obj
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


AUTO_DIMS = "Automatically add Flange Length dimensions to flange profiles"


def auto_length_dims(doc):
    ""
    try:
        from . import optionspages
        return bool(optionspages.doc_value(doc, "Sheet Metal", AUTO_DIMS, False))
    except Exception:
        return False


def add_profile_dims(sk, x0, y0, x1, y1):
    """The flange profile fully defined: its Flange Length (the side away from the bend), its width
    and where its corner sits (the sketch origin is on the flange's edge)."""
    import Sketcher
    sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, y1 - y0))
    sk.renameConstraint(len(sk.Constraints) - 1, "FlangeLength")
    sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, x1 - x0))
    sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 1, x0))
    sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 1, y0))


def edge_list(owner):
    ""
    edges = QtWidgets.QListWidget()
    edges.setObjectName("SWSMEdges")
    edges.setMaximumHeight(64)
    edges.setToolTip("Edges to use. Pick them in the graphics area; Delete removes one.")
    pmboxes.mark(edges, True)
    keys = _DeleteKey(owner)
    keys.setParent(edges)        # kept with the box: an unreferenced filter is collected and Delete went dead
    edges.installEventFilter(keys)
    return edges


def error_label():
    error = QtWidgets.QLabel("")
    error.setObjectName("SWSMError")
    error.setWordWrap(True)
    error.setStyleSheet("color: #c00000;")
    error.hide()
    from . import pickprompt
    return pickprompt.style(error)   # look audit AI1: the start prompt in the yellow box, errors red


def _radio(name, text, enabled=True):
    b = QtWidgets.QRadioButton(text)
    b.setObjectName(name)
    if not enabled:
        b.setEnabled(False)
        b.setToolTip(NOT_YET)
    return b


def _gap_pixmap():
    ""
    from PySide import QtCore as C, QtGui as G
    from . import pmlayout
    dark = pmlayout._dark()
    blue = pmlayout.BLUE_DARK if dark else pmlayout.BLUE
    pix = G.QPixmap(pmlayout.SIZE, pmlayout.SIZE)
    pix.fill(C.Qt.transparent)
    p = G.QPainter(pix)
    p.setRenderHint(G.QPainter.Antialiasing)
    p.setPen(G.QPen(blue, 1.2))
    p.drawRect(C.QRectF(1, 9, 6, 6))
    p.drawRect(C.QRectF(11, 9, 6, 6))
    pmlayout._arrow(p, 7.5, 5, 10.5, 5)
    p.drawLine(C.QPointF(7, 3), C.QPointF(7, 8))
    p.drawLine(C.QPointF(11, 3), C.QPointF(11, 8))
    p.end()
    return pix


def _glyph_label(name, tip):
    ""
    label = QtWidgets.QLabel()
    try:
        from . import pmlayout
        label.setPixmap(_gap_pixmap() if name == "gap" else pmlayout.pixmap(name))
        label.setFixedWidth(pmlayout.SIZE + 6)
    except Exception:
        label.setText(tip)
    label.setToolTip(tip)
    return label


NEAR_PX = 8          # how near the pointer counts, in screen pixels


def _near_edge(doc_name, name, sub, point):
    """The edge of the picked face nearest to the pick point, when it is within NEAR_PX on screen."""
    import Part
    try:
        obj = App.getDocument(doc_name).getObject(name)
        face = obj.Shape.getElement(sub)
        p = App.Vector(*point)
        view = Gui.ActiveDocument.ActiveView
        x, y = view.getPointOnViewport(p) if hasattr(view, "getPointOnViewport") else view.getPointOnScreen(p)
        tol = (view.getPoint(int(x) + NEAR_PX, int(y)) - view.getPoint(int(x), int(y))).Length
        best, best_d = None, None
        for e in face.Edges:
            d = e.distToShape(Part.Vertex(p))[0]
            if best_d is None or d < best_d:
                best, best_d = e, d
        if best is None or best_d > tol:
            return None
        for i, e in enumerate(obj.Shape.Edges, 1):
            if e.isSame(best):
                return "Edge%d" % i
    except Exception:
        return None
    return None


class EdgePicks:
    """What the edge-based sheet metal PropertyManagers share: the Edges list filled from picks in
    the graphics area (a pick on the preview is taken as the part's matching edge), the feature
    made at the first edge, and OK/Cancel. A subclass sets obj, new, base, edges, error and make()."""

    make = staticmethod(make)
    HINT = "Please select an edge of a planar face to create the edge flange."

    # ---------------------------------------------------------------- selection
    def _open(self):
        """This PropertyManager is still up. One left behind (closed without its own close) kept
        clearing every pick in the view: it lets go of the selection then."""
        try:
            forms = self.form if isinstance(self.form, (list, tuple)) else [self.form]
            from .widgets import alive
            if Gui.Control.activeDialog() and any(alive(f) and _in_tasks(f) for f in forms):
                return True
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:257", _fw_err)
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:261", _fw_err)
        return False

    def addSelection(self, doc, name, sub, point):
        if not self._open():
            return
        if sub.startswith("Face"):
            # an edge of a thin wall is hard to hit square on: a click that lands on a face near one of its

            sub = _near_edge(doc, name, sub, point) or ""
        if not sub.startswith("Edge"):
            return
        QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub))

    def _picked(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:279", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        base = self.base
        if base is None:
            base = self.base = picked
        if picked is not base:
            sub = _edge_on(base, picked.Shape.getElement(sub))
            if sub is None:
                return
        subs = [self.edges.item(i).text() for i in range(self.edges.count())]
        if sub in subs:
            return
        self.edges.addItem(sub)
        self._apply_edges()

    def remove_current(self):
        row = self.edges.currentRow()
        if row >= 0:
            self.edges.takeItem(row)
            self._apply_edges()

    def _apply_edges(self):
        subs = [self.edges.item(i).text() for i in range(self.edges.count())]
        if self.obj is None:
            if not subs:
                return
            self.obj = self.make(self.base, subs)
            self._changed()
            return
        if subs:
            self.obj.baseObject = (self.base, subs)
            self.obj.Document.recompute()
        self._report()

    def _report(self):
        if self.obj is None:
            self.error.setText(self.HINT)
            self.error.setVisible(True)
            return False
        invalid = "Invalid" in self.obj.State
        self.error.setText(naming.status_text(self.obj, "The flange") if invalid else "")
        self.error.setVisible(invalid)
        return not invalid

    # ---------------------------------------------------------------- closing
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:333", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:339", _fw_err)

    def accept(self):
        self._changed()
        if not self._report():
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        if self.obj is not None:
            doc = self.obj.Document
            base = self.base if self.new else None
            doc.abortTransaction()
            doc.recompute()
            if getattr(self, "made_before_back", False):
                # pkg460: back from Edit Flange Profile, the new flange's step is already in the Undo list
                _drop_new(doc, getattr(self, "back_new", self.new))
            if base is not None:
                try:
                    base.ViewObject.Visibility = True
                except Exception as _fw_err:
                    _fw_log("smedgeflange.py:359", _fw_err)
        self._close()
        return True


class Panel(EdgePicks):
    """The Edge Flange PropertyManager. obj is None until the first edge is picked."""

    def __init__(self, obj, new, base=None, edges=()):
        self.obj = obj
        self.new = new
        self.base = obj.baseObject[0] if obj is not None else base
        self.busy = True

        params = _box("Flange Parameters")
        f = params.layout()
        self.edges = edge_list(self)
        self.profile = QtWidgets.QPushButton("Edit Flange Profile")
        self.profile.setObjectName("SWSMEditProfile")
        self.profile.setToolTip("Draw the flange's outline in a sketch on its outer face (one edge)")
        self.profile.clicked.connect(self.edit_profile)
        self.default_radius = QtWidgets.QCheckBox("Use default radius")
        self.default_radius.setObjectName("SWSMDefaultRadius")
        root = _root(self.base) if self.base is not None else None
        self.root_radius = root.Radius.Value if root is not None and hasattr(root, "Radius") else None
        self.radius = _spin("SWSMRadius", obj.radius.Value if obj else (self.root_radius or 1.0), 0.0, 10000.0)
        self.radius.setToolTip("Bend radius")
        self.default_radius.setChecked(self.root_radius is not None and abs(self.radius.value() - self.root_radius) < 1e-9)
        self.gap = _spin("SWSMGap", obj.minGap.Value if obj else 1.0, 0.0, 1000.0)
        self.gap.setToolTip("Gap distance between flanges that meet")
        f.addRow(self.edges)
        f.addRow(self.profile)
        f.addRow(self.default_radius)
        f.addRow(_glyph_label("radius", "Bend radius"), self.radius)
        f.addRow(_glyph_label("gap", "Gap distance"), self.gap)

        angle = _box("Angle")
        self.angle = _spin("SWSMAngle", obj.angle.Value if obj else 90.0, 0.01, 180.0, suffix=" deg")
        self.angle.setToolTip("Flange angle")
        angle.layout().addRow(self.angle)
        self.angle_face = QtWidgets.QListWidget()
        self.angle_face.setObjectName("SWSMAngleFace")
        self.angle_face.setMaximumHeight(28)
        self.angle_face.setStyleSheet("QListWidget { background: #ffd6ec; }")
        self.angle_face.setToolTip("Face or plane the flange angle is taken from. Pick it; Delete removes it.")
        angle.layout().addRow(self.angle_face)
        self._del = _DeleteKey(self)
        self.angle_face.installEventFilter(self._del)
        modes = QtWidgets.QWidget()          # own parent: radios group with every radio sibling
        QtWidgets.QVBoxLayout(modes).setContentsMargins(0, 0, 0, 0)
        self.angle_modes = []
        mode = getattr(obj, "SWAngleFaceMode", ANGLE_MODES[0]) if obj is not None else ANGLE_MODES[0]
        for text in ANGLE_MODES:
            b = _radio("SWSMAngle" + text.replace(" ", ""), text)
            b.setChecked(text == mode)
            modes.layout().addWidget(b)
            self.angle_modes.append(b)
        angle.layout().addRow(modes)
        if obj is not None and obj.AngleFaceReference is not None:
            self.angle_face.addItem(self._ref_text(obj.AngleFaceReference))

        length = _box("Flange Length")
        f = length.layout()
        self.end = QtWidgets.QComboBox()
        self.end.setObjectName("SWSMLengthEnd")
        self.end.addItems(("Blind", "Up To Vertex"))
        self.end.setCurrentText(getattr(obj, "SWLengthEnd", "Blind") if obj is not None else "Blind")
        self.vertex = QtWidgets.QListWidget()
        self.vertex.setObjectName("SWSMLengthVertex")
        self.vertex.setMaximumHeight(28)
        self.vertex.setStyleSheet("QListWidget { background: #e6d6ff; }")
        self.vertex.setToolTip("The vertex the flange goes up to. Pick it; Delete removes it.")
        self.vertex.installEventFilter(self._del)
        if obj is not None and getattr(obj, "SWLengthVertex", None) is not None:
            self.vertex.addItem(self._ref_text(obj.SWLengthVertex))
        self.vertex_box = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(self.vertex_box).setContentsMargins(0, 0, 0, 0)
        self.vertex_modes = []
        mode = getattr(obj, "SWVertexMode", VERTEX_MODES[0]) if obj is not None else VERTEX_MODES[0]
        for name, text in zip(("SWSMVertexPerpendicular", "SWSMVertexParallel"), VERTEX_MODES):
            b = _radio(name, text)
            b.setChecked(text == mode)
            self.vertex_box.layout().addWidget(b)
            self.vertex_modes.append(b)
        self.invert = QtWidgets.QCheckBox("Reverse Direction")
        from . import pmvalues
        self.invert.setIcon(pmvalues.reverse_icon())
        self.invert.setObjectName("SWSMLengthReverse")
        self.invert.setChecked(bool(obj.invert) if obj else False)
        self.length = _spin("SWSMLength", obj.length.Value if obj else 10.0, 0.01, 100000.0)
        self.length.setToolTip("Length")
        f.addRow(self.end)
        f.addRow(self.invert)
        f.addRow(self.length)

        self.multi = QtWidgets.QCheckBox("Multi-length flange")
        self.multi.setObjectName("SWSMMultiLength")
        self.multi.setToolTip("Give each picked edge its own flange length")
        self.multi.setChecked(bool(getattr(obj, "SWMultiLength", False)) if obj is not None else False)
        self.lengths = QtWidgets.QTableWidget(0, 2)
        self.lengths.setObjectName("SWSMEdgeLengths")
        self.lengths.setHorizontalHeaderLabels(["Edge", "Length"])
        self.lengths.horizontalHeader().setStretchLastSection(True)
        self.lengths.verticalHeader().setVisible(False)
        self.lengths.setMaximumHeight(120)
        f.addRow(self.multi)
        f.addRow(self.lengths)
        f.addRow(self.vertex)
        f.addRow(self.vertex_box)
        self.specs = QtWidgets.QButtonGroup(length)
        current = obj.LengthSpec if obj else "Outer Sharp"
        from . import pmpics
        row = QtWidgets.QHBoxLayout()
        for i, (text, value) in enumerate(LENGTH_SPECS):
            b = pmpics.button("SWSMLength" + text.replace(" ", ""), "flange_length", text, value == current)
            self.specs.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        f.addRow(row)
        if self.specs.checkedButton() is None:
            self.specs.button(0).setChecked(True)

        position = _box("Flange Position")
        f = position.layout()
        self.positions = QtWidgets.QButtonGroup(position)
        current = obj.BendType if obj else "Material Inside"
        ours = getattr(obj, "SWPosition", "") if obj is not None else ""
        row = QtWidgets.QHBoxLayout()
        for i, (text, value) in enumerate(POSITIONS):
            b = pmpics.button("SWSMPosition" + text.replace(" ", ""), "flange_position", text,
                              text == ours if ours else (value is not None and value == current))
            self.positions.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        f.addRow(row)
        if self.positions.checkedButton() is None:
            self.positions.button(0).setChecked(True)
        self.trim = QtWidgets.QCheckBox("Trim side bends")
        self.trim.setObjectName("SWSMTrimSideBends")
        self.trim.setToolTip("Removes the material of the bends beside the flange")

        self.trim.setChecked(bool(getattr(obj, "SWTrimSideBends", False)) if obj is not None else True)
        self.offset_on = QtWidgets.QCheckBox("Offset")
        self.offset_on.setObjectName("SWSMOffsetOn")
        self.offset_on.setChecked(current == "Offset" and not ours)
        self.offset = _spin("SWSMOffset", obj.offset.Value if obj else 0.0, -100000.0, 100000.0)
        f.addRow(self.trim)
        f.addRow(self.offset_on)
        f.addRow(self.offset)

        allowance = _box("Custom Bend Allowance")
        f = allowance.layout()
        self.custom_k = QtWidgets.QCheckBox("Custom Bend Allowance")
        self.custom_k.setObjectName("SWSMCustomAllowance")
        self.allowance = QtWidgets.QComboBox()
        self.allowance.setObjectName("SWSMAllowance")
        self.allowance.addItems(ALLOWANCES)
        k = None
        if obj is not None:
            try:
                k = float(obj.kfactor)
            except Exception:
                k = None
        root_k = getattr(root, "SWKFactor", 0.5) if root is not None else 0.5
        self.custom_k.setChecked(k is not None and k >= 0 and abs(k - root_k) > 1e-9)
        self.kfactor = _spin("SWSMKFactor", k if k is not None and k >= 0 else root_k, 0.0, 1.0,
                             suffix="", decimals=4, step=0.05)
        self.root_k = root_k
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
        self.relief_w = _spin("SWSMReliefWidth", obj.reliefw.Value if obj else 1.0, 0.0, 1000.0)
        self.relief_w.setToolTip("Relief width")
        self.relief_d = _spin("SWSMReliefDepth", obj.reliefd.Value if obj else 1.0, 0.0, 1000.0)
        self.relief_d.setToolTip("Relief depth")
        f.addRow(self.custom_relief)
        f.addRow(self.relief)
        self.tear = smtear.TearRows(self.relief, f, obj, self._changed)
        f.addRow(self.ratio_on)
        f.addRow("Ratio", self.ratio)
        f.addRow("Width", self.relief_w)
        f.addRow("Depth", self.relief_d)

        self.error = error_label()
        params.layout().addRow(self.error)

        try:
            title = obj.Label if obj is not None else naming.next_label(self.base.Document if self.base is not None
                                                                       else App.ActiveDocument, LABEL)
        except Exception:
            title = TITLE
        params.setProperty("swstyle_pm_title", title)
        params.setProperty("swstyle_pm_icon", "SheetMetal_AddWall")
        self.form = [params, angle, length, position, allowance, relief]

        if obj is not None:
            for sub in obj.baseObject[1]:
                self.edges.addItem(sub)
        else:
            for sub in edges:
                self.edges.addItem(sub)
        self._live()            # before _changed: a radius typed turns Use default radius off before it is read
        for w in (self.radius, self.gap, self.angle, self.length, self.offset, self.kfactor, self.ratio,
                  self.relief_w, self.relief_d):
            w.valueChanged.connect(self._changed)
        for w in (self.default_radius, self.invert, self.offset_on, self.custom_k, self.custom_relief, self.ratio_on,
                  self.trim, self.multi):
            w.toggled.connect(self._changed)
        self.specs.buttonClicked.connect(self._changed)
        self.positions.buttonClicked.connect(self._changed)
        self.relief.currentIndexChanged.connect(self._changed)
        self.end.currentIndexChanged.connect(self._changed)
        for b in self.angle_modes + self.vertex_modes:
            b.toggled.connect(self._changed)
        self.pick_error = ""
        self._fill_lengths()
        self._show()
        self.busy = False
        if obj is None and not edges:
            self._report()      # the hint: which edge to pick
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        self._click = None
        try:
            view = Gui.ActiveDocument.ActiveView
            self._click = (view, view.addEventCallback("SoMouseButtonEvent", self._mouse))
        except Exception:
            self._click = None

    # ---------------------------------------------------------------- flange height from a click
    def height_at(self, p):
        ""

        obj, base = self.obj, self.base
        if obj is None or base is None or self.edges.count() == 0 or obj.Shape.isNull():
            return None
        edge = base.Shape.getElement(self.edges.item(0).text())
        a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        axis = b - a
        if axis.Length < 1e-9:
            return None
        axis.normalize()

        def off_line(q):
            v = q - a
            return v - axis * v.dot(axis)

        far = self._far(a, axis)
        if far is None or far.Length < 1e-9:
            return None
        up = self._up(far)
        h = off_line(p).dot(up)
        return max(0.01, float(self.length.value()) + (h - far.dot(up)))

    def _far(self, a, axis):
        """The flange's farthest point off its edge line, as an off-line vector. Only the new flange counts: the
        feature's shape also holds the base part, whose own corners are left out."""
        base_shape = self.base.Shape
        best = None
        for v in self.obj.Shape.Vertexes:
            try:
                if base_shape.distToShape(v)[0] < 1e-4:
                    continue
            except Exception as _fw_err:
                _fw_log("smedgeflange.py:626", _fw_err)
            w = v.Point - a
            w = w - axis * w.dot(axis)
            if best is None or w.Length > best.Length:
                best = w
        return best

    def _up(self, far):
        """The way the flange runs: the normal of its end face (the flat face at the far point, facing away from the
        edge). Falls back to the far point's own direction."""
        tip = App.Vector(far).normalize()
        best, score = tip, 0.5
        for f in self.obj.Shape.Faces:
            try:
                if f.Surface.TypeId != "Part::GeomPlane":
                    continue
                n = f.normalAt(*f.Surface.parameter(f.CenterOfMass))
            except Exception:
                continue
            if n.dot(tip) > score:
                best, score = App.Vector(n), n.dot(tip)
        return best

    def _plane_point(self, view, pos):
        """Where the line of sight through pos meets the flange's own plane."""
        obj, base = self.obj, self.base
        edge = base.Shape.getElement(self.edges.item(0).text())
        a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        axis = (b - a).normalize()
        far = self._far(a, axis)
        if far is None or far.Length < 1e-9:
            return None
        normal = axis.cross(self._up(far))
        p, d = view.getPoint(*pos), view.getViewDirection()
        try:                        # a perspective camera: the ray runs from the eye through the point
            cam = view.getCameraNode()
            if cam.getTypeId().getName() == "PerspectiveCamera":
                eye = App.Vector(*cam.position.getValue().getValue())
                if (p - eye).Length > 1e-9:
                    d = (p - eye).normalize()
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:667", _fw_err)
        den = d.dot(normal)
        if abs(den) < 1e-3:         # the flange is seen edge on: the point under the pointer, put on its plane
            return p - normal * (p - a).dot(normal)
        return p + d * ((a - p).dot(normal) / den)

    def _mouse(self, info):
        try:
            if info.get("Button") != "BUTTON1" or info.get("State") != "DOWN" or self.edges.count() == 0:
                return
            if self.end.currentText() != "Blind" or not self.length.isEnabled():
                return
            view, pos = self._click[0], info.get("Position")
            if view.getObjectInfo(pos):
                return              # on the model: a pick, not a height
            p = self._plane_point(view, pos)
            h = self.height_at(p) if p is not None else None
            if h is not None:
                self.length.setValue(h)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Edge Flange height from the click: %s\n" % error)

    def _close(self):
        if getattr(self, "_click", None):
            try:
                self._click[0].removeEventCallback("SoMouseButtonEvent", self._click[1])
            except Exception as _fw_err:
                _fw_log("smedgeflange.py:694", _fw_err)
            self._click = None
        EdgePicks._close(self)

    # ---------------------------------------------------------------- values
    def _show(self):
        obj = self.obj
        face = self.angle_face.count() > 0
        # NO DEAD CONTROLS: what does not apply now is hidden, what applies is live (using a box turns its option on)
        _row(self.angle, not face)            # a face picked sets the angle
        for b in self.angle_modes:
            b.setVisible(face)
        tangent = POSITIONS[max(0, self.positions.checkedId())][0] == "Tangent to Bend" and not self.offset_on.isChecked()
        self.angle.blockSignals(True)
        self.angle.setMinimum(90.0 if tangent else 0.01)
        self.angle.blockSignals(False)
        profile = obj is not None and getattr(obj, "SWProfile", None) is not None
        self.profile.setVisible(obj is not None and self.edges.count() == 1)
        vertex = self.end.currentText() == "Up To Vertex"
        self.end.setVisible(not profile)      # an edited flange profile sets the length
        _row(self.length, not vertex and not profile)
        many = self.edges.count() > 1 and not vertex and not profile
        self.multi.setVisible(many)
        self.lengths.setVisible(many and self.multi.isChecked())
        self.vertex.setVisible(vertex)
        self.vertex_box.setVisible(vertex)
        self.tear.show(True)
        self.offset.setVisible(self.offset_on.isChecked())
        self.custom.show(True)
        tear = self.relief.currentText() == "Tear"
        self.ratio_on.setVisible(not tear)
        ratio = self.ratio_on.isChecked()
        _row(self.ratio, ratio and not tear)
        _row(self.relief_w, not ratio and not tear)
        _row(self.relief_d, not ratio and not tear)

    def _turn_on(self, check, on=True):
        """A box used by hand turns its option on (Use default radius off for a radius typed, and so on)."""
        if self.busy:
            return
        if check.isChecked() != on:
            check.setChecked(on)

    def _live(self):
        ""
        self.radius.valueChanged.connect(
            lambda *_: self.root_radius is not None and abs(self.radius.value() - self.root_radius) > 1e-9 and
            self._turn_on(self.default_radius, False))
        self.gap.valueChanged.connect(lambda *_: self._turn_on(self.default_radius, False))
        for w in (self.allowance,):
            w.activated.connect(lambda *_: self._turn_on(self.custom_k))
        self.kfactor.valueChanged.connect(lambda *_: self._turn_on(self.custom_k))
        for name in ("combo", "kspin", "ba", "bd"):
            w = getattr(self.custom, name, None)
            if isinstance(w, QtWidgets.QComboBox):
                w.activated.connect(lambda *_: self._turn_on(self.custom_k))
            elif w is not None and hasattr(w, "valueChanged"):
                w.valueChanged.connect(lambda *_: self._turn_on(self.custom_k))
        self.relief.activated.connect(lambda *_: self._turn_on(self.custom_relief))
        for b in self.tear.buttons:
            b.clicked.connect(lambda *_: self._turn_on(self.custom_relief))
        self.ratio_on.clicked.connect(lambda *_: self._turn_on(self.custom_relief))
        self.ratio.valueChanged.connect(lambda *_: (self._turn_on(self.custom_relief), self._turn_on(self.ratio_on)))
        for w in (self.relief_w, self.relief_d):
            w.valueChanged.connect(lambda *_: (self._turn_on(self.custom_relief), self._turn_on(self.ratio_on, False)))

        def position(b):
            if POSITIONS[self.positions.id(b)][1] is not None:
                self._turn_on(self.offset_on, False)        # a position Offset can't use: Offset off
        self.positions.buttonClicked.connect(position)

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
        obj.radius = self.radius.value()
        obj.minGap = self.gap.value()
        obj.angle = self.angle.value()
        obj.invert = self.invert.isChecked()
        smedgegeom.ensure(obj)
        if obj.SWProfile is None:
            obj.length = self.length.value()
            obj.LengthSpec = LENGTH_SPECS[max(0, self.specs.checkedId())][1]
        obj.SWLengthEnd = self.end.currentText()
        obj.SWVertexMode = next(b.text() for b in self.vertex_modes if b.isChecked())
        obj.SWAngleFaceMode = next(b.text() for b in self.angle_modes if b.isChecked())
        obj.SWTrimSideBends = self.trim.isChecked()
        obj.SWMultiLength = self.multi.isChecked()
        obj.SWEdgeLengths = self.edge_lengths()
        if self.offset_on.isChecked():
            obj.SWPosition = ""
            obj.BendType = "Offset"
            obj.offset = self.offset.value()
        else:
            text, value = POSITIONS[max(0, self.positions.checkedId())]
            obj.SWPosition = "" if value is not None else text
            obj.BendType = value or "Offset"
        try:
            obj.kfactor = smallowance.k_for(self, obj, self.angle.value()) if self.custom_k.isChecked() else self.root_k
            self.custom.save(obj)
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:777", _fw_err)
        if self.custom_relief.isChecked():
            obj.reliefType = RELIEF_TYPES.get(self.relief.currentText()) or "Rectangle"
            obj.UseReliefFactor = self.ratio_on.isChecked()
            obj.ReliefFactor = self.ratio.value()
            obj.reliefw = self.relief_w.value()
            obj.reliefd = self.relief_d.value()
            self.tear.apply(obj, float(obj.radius), smedgegeom.thickness(obj))
        obj.Document.recompute()
        self._place_profile()
        self._report()
        smallowance.report(self)
        if self.pick_error:
            self.error.setText(self.pick_error)
            self.error.setVisible(True)

    # ---------------------------------------------------------------- multi-length flange
    def edge_lengths(self):
        """The Length column, in the order of the edges (the main Length where a row has none)."""
        out = []
        for r in range(self.lengths.rowCount()):
            w = self.lengths.cellWidget(r, 1)
            out.append(float(w.value()) if w is not None else float(self.length.value()))
        return out

    def _fill_lengths(self):
        """One row per picked edge: its length, the main Length to start with."""
        subs = [self.edges.item(i).text() for i in range(self.edges.count())]
        old = {}
        for r in range(self.lengths.rowCount()):
            item, w = self.lengths.item(r, 0), self.lengths.cellWidget(r, 1)
            if item is not None and w is not None:
                old[item.text()] = w.value()
        if not old and self.obj is not None:
            vals = list(getattr(self.obj, "SWEdgeLengths", []) or [])
            on = list(self.obj.baseObject[1])
            old = {sub: vals[i] for i, sub in enumerate(on) if i < len(vals)}
        self.lengths.setRowCount(len(subs))
        for r, sub in enumerate(subs):
            item = QtWidgets.QTableWidgetItem(sub)
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.lengths.setItem(r, 0, item)
            spin = _spin("SWSMEdgeLength%d" % (r + 1), old.get(sub, self.length.value()), 0.01, 100000.0)
            spin.valueChanged.connect(self._changed)
            self.lengths.setCellWidget(r, 1, spin)

    def _apply_edges(self):
        super()._apply_edges()
        self._fill_lengths()
        if not self.busy and self.obj is not None and self.multi.isChecked():
            self._changed()
        else:
            self._show()

    # ---------------------------------------------------------------- angle face, vertex, profile
    @staticmethod
    def _ref_text(link):
        obj, subs = link
        sub = subs[0] if subs and subs[0] else ""
        return "%s of %s" % (sub, obj.Label) if sub else obj.Label

    def addSelection(self, doc, name, sub, point):
        if sub.startswith("Edge"):
            return EdgePicks.addSelection(self, doc, name, sub, point)
        from . import safe_later as _sl; _sl.later(0, lambda: self._picked_other(doc, name, sub), self, "angle_face")

    def _picked_other(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:847", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        obj = self.obj
        if picked is None or obj is None:
            return
        self.pick_error = ""
        if picked is obj:
            # a pick on the flange itself is taken as the part's matching face or vertex before it
            item = picked.Shape.getElement(sub) if sub else None
            sub = self._on_base(item, sub)
            picked = self.base
            if sub is None:
                self.pick_error = "Pick a face or vertex of the part before this flange, or a plane."
                self._report()
                return
        smedgegeom.ensure(obj)
        plane = not sub and "Plane" in picked.TypeId
        if sub.startswith("Face") or plane:
            obj.AngleFaceReference = (picked, [sub or ""])
            self.angle_face.clear()
            self.angle_face.addItem(self._ref_text(obj.AngleFaceReference))
        elif sub.startswith("Vertex") and self.end.currentText() == "Up To Vertex":
            obj.SWLengthVertex = (picked, [sub])
            self.vertex.clear()
            self.vertex.addItem(self._ref_text(obj.SWLengthVertex))
        elif sub.startswith("Vertex") and self.end.currentText() == "Blind" and self.length.isEnabled():
            h = self.height_at(picked.Shape.getElement(sub).Point)      # Blind: the vertex sets the height
            if h is None:
                return
            self.length.setValue(h)
            return
        else:
            return
        self._changed()

    def _on_base(self, item, sub):
        if item is None or self.base is None:
            return None
        shape = self.base.Shape
        if sub.startswith("Vertex"):
            for i, v in enumerate(shape.Vertexes, 1):
                if v.Point.distanceToPoint(item.Point) < 1e-6:
                    return "Vertex%d" % i
        if sub.startswith("Face"):
            for i, f in enumerate(shape.Faces, 1):
                if abs(f.Area - item.Area) < 1e-6 and f.CenterOfMass.distanceToPoint(item.CenterOfMass) < 1e-6:
                    return "Face%d" % i
        return None

    def remove_current(self):
        obj = self.obj
        if self.angle_face.hasFocus():
            self.angle_face.clear()
            if obj is not None:
                obj.AngleFaceReference = None
                obj.angle = self.angle.value()
            self._changed()
        elif self.vertex.hasFocus():
            self.vertex.clear()
            if obj is not None:
                obj.SWLengthVertex = None
            self._changed()
        else:
            EdgePicks.remove_current(self)

    def _place_profile(self):
        """Keeps the profile sketch on the flange's outer face when the flange moves (angle, position)."""
        obj = self.obj
        sk = getattr(obj, "SWProfile", None) if obj is not None else None
        if sk is None or "Invalid" in obj.State:
            return
        try:
            pl = smedgegeom.frame(obj)[0]
        except ValueError:
            return
        if not pl.isSame(sk.Placement, 1e-7):
            sk.Placement = pl
            obj.Document.recompute()

    def edit_profile(self):
        """Edit Flange Profile: the flange's outline as a sketch on its outer face; OK, then the sketch opens."""
        obj = self.obj
        if obj is None or self.edges.count() != 1:
            return
        smedgegeom.ensure(obj)
        sk = obj.SWProfile
        doc = obj.Document
        if sk is None:
            try:
                pl, (x0, y0, x1, y1) = smedgegeom.profile_rectangle(obj)
            except ValueError as e:
                self.pick_error = str(e)
                self._report()
                return
            import Part
            import Sketcher
            sk = doc.addObject("Sketcher::SketchObject", "Sketch")
            body = next((p for p in obj.InList if p.TypeId == "PartDesign::Body"), None)
            if body is not None:
                body.insertObject(sk, obj, False)
            sk.MapMode = "Deactivated"
            sk.Placement = pl
            pts = [App.Vector(x0, y0, 0), App.Vector(x1, y0, 0), App.Vector(x1, y1, 0), App.Vector(x0, y1, 0)]
            for a, b in zip(pts, pts[1:] + pts[:1]):
                sk.addGeometry(Part.LineSegment(a, b))
            for i in range(4):
                sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
            sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
            sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
            sk.addConstraint(Sketcher.Constraint("Vertical", 1))
            sk.addConstraint(Sketcher.Constraint("Vertical", 3))
            if auto_length_dims(doc):
                add_profile_dims(sk, x0, y0, x1, y1)
            sk.Label = naming.next_label(doc, "Sketch")
            obj.SWProfile = sk
            doc.recompute()

        # Sketch" dialog (Back / Finish / Cancel), the flange following the sketch live; Finish makes it.
        # The page's own step stays open across the sketch (leaving the sketch commits it: one Undo).
        self._changed()
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:profile-observer", _fw_err)
        Gui.Control.closeDialog()
        try:
            sk.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:968", _fw_err)
        Gui.ActiveDocument.setEdit(sk.Name)
        ProfileSketch(obj, sk, getattr(self, "back_new", self.new))

class ProfileSketch(QtWidgets.QDialog):
    ""

    current = None

    def __init__(self, obj, sketch, new):
        super().__init__(Gui.getMainWindow(), QtCore.Qt.Tool)
        self.setObjectName("SWSMProfileSketch")
        self.setWindowTitle("Profile Sketch")
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.obj, self.sketch, self.new, self.doc = obj, sketch, new, obj.Document
        self.undo0 = len(self.doc.UndoNames)
        lay = QtWidgets.QHBoxLayout(self)
        for name, text in (("Back", "Back"), ("Finish", "Finish"), ("Cancel", "Cancel")):
            b = QtWidgets.QPushButton(text, self)
            b.setObjectName("SWSMProfileSketch" + name)
            b.clicked.connect(getattr(self, name.lower()))
            lay.addWidget(b)
        self.seen = self._state()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._follow)
        self.timer.start(300)
        ProfileSketch.current = self
        try:
            view = Gui.getMainWindow().centralWidget()
            self.adjustSize()
            self.move(view.mapToGlobal(QtCore.QPoint(view.width() - self.width() - 40, 60)))
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:profile-place", _fw_err)
        self.show()

    def _state(self):
        try:
            sk = self.sketch
            return (len(sk.Geometry),
                    tuple(round(c, 6) for g in sk.Geometry for p in (getattr(g, "StartPoint", None), getattr(g, "EndPoint", None))
                          if p is not None for c in (p.x, p.y)),
                    tuple(str(getattr(c, "Value", "")) for c in sk.Constraints))
        except Exception:
            return None

    def _follow(self):
        ""
        try:
            gdoc = Gui.ActiveDocument
            if gdoc is None or gdoc.getInEdit() is None:
                # the sketch was closed another way (its own Close): as Finish
                self.timer.stop()
                self._done()
                return
            state = self._state()
            if state != self.seen:
                self.seen = state
                self.sketch.recompute()     # its shape (the solver alone leaves the old one)
                self.obj.touch()
                self.obj.recompute()
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:profile-follow", _fw_err)

    def _leave(self):
        self.timer.stop()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:profile-leave", _fw_err)

    def _done(self):
        if ProfileSketch.current is self:
            ProfileSketch.current = None
        try:
            self.sketch.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:profile-hide", _fw_err)
        try:
            self.doc.recompute()
        except Exception as _fw_err:
            _fw_log("smedgeflange.py:profile-recompute", _fw_err)
        self.close()

    def finish(self):
        self._leave()
        self._done()

    def back(self):
        self._leave()
        if ProfileSketch.current is self:
            ProfileSketch.current = None
        self.close()
        try:
            self.doc.recompute()
            panel = Panel(self.obj, self.new)
            # the flange's step was closed with the sketch: Cancel now takes it out with one Undo
            panel.made_before_back = True
            panel.back_new = self.new
            panel.undo_at_back = len(self.doc.UndoNames)
            Gui.Control.showDialog(panel)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Edge Flange: %s\n" % error)

    def cancel(self):
        self._leave()
        if ProfileSketch.current is self:
            ProfileSketch.current = None
        self.close()
        _drop_new(self.doc, self.new)


def _drop_new(doc, new):
    """Cancel after the profile sketch: a new flange (and its sketch) goes with its Undo step, as if never made;
    an edited one goes back as it was."""
    try:
        if doc.UndoNames and doc.UndoNames[0] == (TITLE if new else "Edit " + TITLE):
            doc.undo()
            doc.recompute()
    except Exception as _fw_err:
        _fw_log("smedgeflange.py:profile-cancel", _fw_err)


class _DeleteKey(QtCore.QObject):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.KeyPress and event.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            self.panel.remove_current()
            return True
        return False


def start(panel=None):
    panel_class = panel or Panel
    doc = App.ActiveDocument
    if doc is None:
        return
    base, edges = None, []
    for s in Gui.Selection.getSelectionEx():
        subs = [n for n in s.SubElementNames if n.startswith("Edge")]
        if subs and base is None:
            base, edges = s.Object, subs
    if base is None:
        body = _active_body(doc)
        base = body.Tip if body is not None else None
    panel = panel_class(None, True, base=base)
    Gui.Control.showDialog(panel)
    if edges:
        for sub in edges:
            panel.edges.addItem(sub)
        panel._apply_edges()


class Command:
    def GetResources(self):
        try:
            import SheetMetalTools, os
            pixmap = os.path.join(SheetMetalTools.icons_path, "SheetMetal_AddWall.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Edge Flange", "ToolTip": "Adds a flange on one or more edges."}

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


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
    smedgegeom.patch()
    view = _engine().SMViewProviderTree
    if "setEdit" not in _patched:
        _patched["setEdit"] = view.setEdit

        def setEdit(self, vobj, mode=0, original=_patched["setEdit"]):
            obj = vobj.Object
            if mode != 0 or not is_edge_flange(obj) or not paths.params().GetBool("Enabled", True):
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
    if "claimChildren" not in _patched:
        _patched["claimChildren"] = view.claimChildren

        def claimChildren(self, original=_patched["claimChildren"]):

            kids = [k for k in original(self) if k is not None]
            profile = getattr(self.Object, "SWProfile", None)
            return kids + [profile] if profile is not None and profile not in kids else kids
        view.claimChildren = claimChildren


def _in_tasks(w):
    """The form still sits in FreeCAD's task view: shown, or hidden behind the FeatureManager tab."""
    try:
        p = w
        while p is not None:
            if p.metaObject().className() in ("Gui::TaskView::TaskView", "Gui::TaskView::TaskBox"):
                return True
            p = p.parentWidget()
    except (RuntimeError, AttributeError):
        return False
    return False
