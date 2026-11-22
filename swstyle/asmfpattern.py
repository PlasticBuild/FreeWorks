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

from . import asmcore as ac
from . import asmfeature as af

V = App.Vector
NAMES = {"LPattern": "LPattern", "CPattern": "CirPattern", "MPattern": "Mirror", "TPattern": "TPattern",
         "SPattern": "SketchPattern"}
TITLES = {"LPattern": "Linear Pattern", "CPattern": "Circular Pattern", "MPattern": "Mirror",
          "TPattern": "Table Driven Pattern", "SPattern": "Sketch Driven Pattern"}
ICONS = {"LPattern": "PartDesign_LinearPattern", "CPattern": "PartDesign_PolarPattern", "MPattern": "PartDesign_Mirrored",
         "TPattern": "PartDesign_LinearPattern", "SPattern": "PartDesign_LinearPattern"}
FAMILIES = {"LPattern": "FEATURES_LINEAR_PATTERN", "CPattern": "FEATURES_CIRCULAR_PATTERN", "MPattern": "FEATURES_MIRROR",
            "TPattern": "FEATURES_TABLE_DRIVEN_PATTERN", "SPattern": "FEATURES_SKETCH_DRIVEN_PATTERN"}
PROPS = (
    ("App::PropertyLinkList", "Sources", "Pattern", "Features to Pattern"),
    ("App::PropertyVector", "Dir1", "Pattern", "Direction 1"),
    ("App::PropertyLength", "Spacing1", "Pattern", "Direction 1 spacing"),
    ("App::PropertyInteger", "Count1", "Pattern", "Direction 1 instances"),
    ("App::PropertyVector", "Dir2", "Pattern", "Direction 2"),
    ("App::PropertyLength", "Spacing2", "Pattern", "Direction 2 spacing"),
    ("App::PropertyInteger", "Count2", "Pattern", "Direction 2 instances (1: no Direction 2)"),
    ("App::PropertyVector", "AxisPoint", "Pattern", "Circular pattern axis: a point"),
    ("App::PropertyVector", "AxisDir", "Pattern", "Circular pattern axis: direction"),
    ("App::PropertyAngle", "PatternAngle", "Pattern", "Circular pattern angle"),
    ("App::PropertyBool", "EqualSpacing", "Pattern", "Circular pattern: equal spacing"),
    ("App::PropertyVector", "MirrorBase", "Pattern", "Mirror plane: a point"),
    ("App::PropertyVector", "MirrorNormal", "Pattern", "Mirror plane: normal"),
    ("App::PropertyVectorList", "Offsets", "Pattern", "Table driven pattern: X, Y, Z of each instance"),
)


def is_pattern(obj):
    return getattr(obj, af.FEATURE_PROP, "") in NAMES


def _props(obj):
    for typ, name, group, tip in PROPS:
        if not hasattr(obj, name):
            obj.addProperty(typ, name, group, tip)


# ---------------------------------------------------------------- geometry
def seed_solid(feat, asm):
    """The cut a feature makes, as one shape (a Hole Series: its holes together)."""
    import Part
    kind = getattr(feat, af.FEATURE_PROP, "")
    if kind == "Series":
        solids = [s for _c, s in af.series_tools(feat, asm)]
        return Part.makeCompound(solids) if solids else None
    return af.tool(feat, asm)


def sketch_points(sketch):
    place = sketch.getGlobalPlacement()
    out = []
    for i, g in enumerate(sketch.Geometry):
        if g.TypeId == "Part::GeomPoint" and not sketch.getConstruction(i):
            out.append(place.multVec(V(g.X, g.Y, g.Z)))
    return out


def copies(feat, asm, solid, reference=None):
    """The copies of solid the pattern makes (the seed itself left out)."""
    kind = getattr(feat, af.FEATURE_PROP)
    out = []
    if kind == "LPattern":
        d1, d2 = V(feat.Dir1), V(feat.Dir2)
        n1, n2 = max(1, feat.Count1), max(1, feat.Count2) if d2.Length > 1e-9 else 1
        if d1.Length < 1e-9:
            return []
        d1.normalize()
        if d2.Length > 1e-9:
            d2.normalize()
        s1, s2 = float(feat.Spacing1), float(feat.Spacing2)
        for i in range(n1):
            for k in range(n2):
                if i == 0 and k == 0:
                    continue
                out.append(solid.translated(d1 * (s1 * i) + d2 * (s2 * k)))
    elif kind == "CPattern":
        axis = V(feat.AxisDir)
        n = max(1, feat.Count1)
        if axis.Length < 1e-9 or n < 2:
            return []
        total = float(feat.PatternAngle)
        if feat.EqualSpacing:
            step = total / n if abs(total - 360.0) < 1e-6 else total / (n - 1)
        else:
            step = total
        for i in range(1, n):
            s = solid.copy()
            s.rotate(V(feat.AxisPoint), axis, step * i)
            out.append(s)
    elif kind == "MPattern":
        normal = V(feat.MirrorNormal)
        if normal.Length < 1e-9:
            return []
        out.append(solid.mirror(V(feat.MirrorBase), normal))
    elif kind == "TPattern":
        ref = reference if reference is not None else V()
        for p in feat.Offsets:
            out.append(solid.translated(V(p) - ref))
    elif kind == "SPattern":
        sk = feat.Profile
        if sk is None:
            return []
        ref = reference if reference is not None else solid.BoundBox.Center
        for p in sketch_points(sk):
            if (p - ref).Length > 1e-6:
                out.append(solid.translated(p - ref))
    return out


def reference_point(feat, asm):
    ""
    pts = []
    for f in feat.Sources:
        s = seed_solid(f, asm)
        if s is not None and not s.isNull():
            pts.append(s.BoundBox.Center)
    if not pts:
        return V()
    c = V()
    for p in pts:
        c += p
    return c * (1.0 / len(pts))


def pattern_tool(feat, asm=None):
    import Part
    asm = asm or ac.assembly_of(feat.Document)
    ref = reference_point(feat, asm) if getattr(feat, af.FEATURE_PROP) in ("SPattern", "TPattern") else None
    shapes = []
    for f in feat.Sources:
        if f is feat:
            continue
        s = seed_solid(f, asm)
        if s is None or s.isNull():
            continue
        shapes += copies(feat, asm, s, ref)
    shapes = [s for s in shapes if s is not None and not s.isNull()]
    return Part.makeCompound(shapes) if shapes else None


def make(asm, kind, values):
    feat = asm.newObject("App::FeaturePython", "AsmCut")
    af.Feature(feat, kind)
    _props(feat)
    feat.Count1, feat.Count2, feat.PatternAngle, feat.EqualSpacing = 2, 1, 360.0, True
    if App.GuiUp and feat.ViewObject is not None:
        af.ViewProviderFeature(feat.ViewObject)
        feat.ViewObject.Visibility = True
    feat.Label = af._next_label(asm, NAMES[kind])
    set_values(feat, values)
    af.update(feat, True)
    asm.Document.recompute()
    return feat


def set_values(feat, values):
    _props(feat)
    af._extra(feat)
    for key, value in values.items():
        if key == "Scope":
            value = [c.Name for c in value]
        setattr(feat, key, value)
    sk = values.get("Profile")
    if sk is not None and App.GuiUp and sk.ViewObject is not None:
        sk.ViewObject.Visibility = False


# ---------------------------------------------------------------- picks
def _geometry(asm, root, sub):
    """(kind, point, direction) of a pick: 'line' (an edge or axis), 'plane' (a flat face or a
    plane), 'circle' (a round edge or face: its axis), or None."""
    ref = ac.reference(asm, root, sub) if root is not None and sub else None
    shape = ac.element(*ref) if ref is not None else None
    if shape is None and root is not None:
        try:
            obj = root.getSubObject(sub, retType=1) if sub else root
            plc = root.getSubObject(sub, retType=3) if sub else root.Placement
        except Exception:
            obj, plc = None, None
        if obj is not None and plc is not None:
            if obj.TypeId == "App::Line" or obj.isDerivedFrom("PartDesign::Line"):
                return "line", plc.Base, plc.Rotation.multVec(V(1, 0, 0)) if obj.TypeId == "App::Line" else plc.Rotation.multVec(V(0, 0, 1))
            if obj.TypeId == "App::Plane" or obj.isDerivedFrom("PartDesign::Plane"):
                return "plane", plc.Base, plc.Rotation.multVec(V(0, 0, 1))
            try:
                shape = obj.getSubObject(sub.split(".")[-1]) if sub else None
            except Exception:
                shape = None
    if shape is None:
        return None
    if shape.ShapeType == "Edge":
        c = shape.Curve
        if c.TypeId == "Part::GeomLine" or c.TypeId == "Part::GeomLineSegment":
            a, b = shape.Vertexes[0].Point, shape.Vertexes[-1].Point
            return "line", a, b - a
        if hasattr(c, "Axis") and hasattr(c, "Center"):
            return "circle", V(c.Center), V(c.Axis)
        return None
    if shape.ShapeType == "Face":
        s = shape.Surface
        if s.TypeId == "Part::GeomPlane":
            u, v = s.parameter(shape.CenterOfMass)
            return "plane", shape.CenterOfMass, shape.normalAt(u, v)
        if hasattr(s, "Axis") and hasattr(s, "Center"):
            return "circle", V(s.Center), V(s.Axis)
        try:
            if hasattr(s, "Axis"):
                return "circle", V(s.Location if hasattr(s, "Location") else s.Center), V(s.Axis)
        except Exception as _fw_err:
            _fw_log("asmfpattern.py:238", _fw_err)
    return None


def _pick_text(root, sub):
    if root is None:
        return ""
    return "%s@%s" % (sub.rstrip(".").split(".")[-1] if sub else root.Label, root.Label)


# ---------------------------------------------------------------- PropertyManager
class PatternPanel(af._FeaturePanel):
    ""


    def __init__(self, asm, kind, feat=None, seeds=()):
        from . import asmpm
        self._start(asm, kind, feat)
        self.sources = list(feat.Sources) if feat is not None else [s for s in seeds if af.is_feature(s)]
        self.dir1 = V(feat.Dir1) if feat is not None else None
        self.dir2 = V(feat.Dir2) if feat is not None and V(feat.Dir2).Length > 1e-9 else None
        self.axis = (V(feat.AxisPoint), V(feat.AxisDir)) if feat is not None and V(feat.AxisDir).Length > 1e-9 else None
        self.plane = (V(feat.MirrorBase), V(feat.MirrorNormal)) if feat is not None and V(feat.MirrorNormal).Length > 1e-9 else None
        self.sketch = feat.Profile if feat is not None else None
        self.form = []
        style = asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit")
        self.active = None

        def pick_box(name, text=""):
            w = QtWidgets.QLineEdit(text)
            w.setObjectName(name)
            w.setReadOnly(True)
            w.setStyleSheet(style)
            w.installEventFilter(self._focus)
            return w

        self._focus = _Focus(self)
        if kind == "LPattern":
            box, lay = asmpm._box("Direction 1", TITLES[kind], FAMILIES[kind])
            self.dir1_box = pick_box("FW_AsmPatDir1", "(picked)" if self.dir1 is not None else "")
            lay.addWidget(self.dir1_box)
            self.rev1 = QtWidgets.QCheckBox("Reverse Direction")
            from . import pmvalues
            self.rev1.setIcon(pmvalues.reverse_icon())
            from . import pmvalues
            self.rev1.setIcon(pmvalues.reverse_icon())
            self.rev1.setObjectName("FW_AsmPatRev1")
            lay.addWidget(self.rev1)
            form = QtWidgets.QFormLayout()
            self.spacing1 = af._spin("FW_AsmPatSpacing1", float(feat.Spacing1) if feat is not None else 10.0)
            self.count1 = _count("FW_AsmPatCount1", feat.Count1 if feat is not None else 2)
            form.addRow("Spacing:", self.spacing1)
            form.addRow("Number of Instances:", self.count1)
            lay.addLayout(form)
            box2, lay2 = asmpm._box("Direction 2")
            self.use2 = QtWidgets.QCheckBox("Direction 2")
            self.use2.setObjectName("FW_AsmPatUse2")
            self.use2.setChecked(self.dir2 is not None)
            lay2.addWidget(self.use2)
            self.dir2_box = pick_box("FW_AsmPatDir2", "(picked)" if self.dir2 is not None else "")
            lay2.addWidget(self.dir2_box)
            self.rev2 = QtWidgets.QCheckBox("Reverse Direction")
            from . import pmvalues
            self.rev2.setIcon(pmvalues.reverse_icon())
            self.rev2.setObjectName("FW_AsmPatRev2")
            lay2.addWidget(self.rev2)
            form2 = QtWidgets.QFormLayout()
            self.spacing2 = af._spin("FW_AsmPatSpacing2", float(feat.Spacing2) if feat is not None and float(feat.Spacing2) > 0 else 10.0)
            self.count2 = _count("FW_AsmPatCount2", feat.Count2 if feat is not None and feat.Count2 > 1 else 2)
            form2.addRow("Spacing:", self.spacing2)
            form2.addRow("Number of Instances:", self.count2)
            lay2.addLayout(form2)
            for w in (self.dir2_box, self.rev2, self.spacing2, self.count2):
                w.setEnabled(self.use2.isChecked())
            self.use2.toggled.connect(lambda on: [w.setEnabled(on) for w in (self.dir2_box, self.rev2, self.spacing2, self.count2)])
            self.use2.toggled.connect(lambda on: self._activate(self.dir2_box if on else self.dir1_box))
            self.form += [box, box2]
            self.active = self.dir1_box
        elif kind == "CPattern":
            box, lay = asmpm._box("Parameters", TITLES[kind], FAMILIES[kind])
            self.axis_box = pick_box("FW_AsmPatAxis", "(picked)" if self.axis is not None else "")
            lay.addWidget(self.axis_box)
            self.rev1 = QtWidgets.QCheckBox("Reverse Direction")
            from . import pmvalues
            self.rev1.setIcon(pmvalues.reverse_icon())
            from . import pmvalues
            self.rev1.setIcon(pmvalues.reverse_icon())
            self.rev1.setObjectName("FW_AsmPatRev1")
            lay.addWidget(self.rev1)
            form = QtWidgets.QFormLayout()
            self.angle = QtWidgets.QDoubleSpinBox()
            self.angle.setObjectName("FW_AsmPatAngle")
            self.angle.setRange(0.01, 360.0)
            self.angle.setSuffix("deg")
            self.angle.setValue(float(feat.PatternAngle) if feat is not None else 360.0)
            self.count1 = _count("FW_AsmPatCount1", feat.Count1 if feat is not None else 4)
            form.addRow("Angle:", self.angle)
            form.addRow("Number of Instances:", self.count1)
            lay.addLayout(form)
            self.equal = QtWidgets.QCheckBox("Equal spacing")
            self.equal.setObjectName("FW_AsmPatEqual")
            self.equal.setChecked(feat.EqualSpacing if feat is not None else True)
            lay.addWidget(self.equal)
            self.form.append(box)
            self.active = self.axis_box
        elif kind == "MPattern":
            box, lay = asmpm._box("Mirror Face/Plane", TITLES[kind], FAMILIES[kind])
            self.plane_box = pick_box("FW_AsmPatPlane", "(picked)" if self.plane is not None else "")
            lay.addWidget(self.plane_box)
            self.form.append(box)
            self.active = self.plane_box
        elif kind == "TPattern":
            box, lay = asmpm._box("Points (X, Y, Z of each instance)", TITLES[kind], FAMILIES[kind])
            self.table = QtWidgets.QTableWidget(0, 3)
            self.table.setObjectName("FW_AsmPatTable")
            self.table.setHorizontalHeaderLabels(["X", "Y", "Z"])
            lay.addWidget(self.table)
            add = QtWidgets.QPushButton("Add Point")
            add.setObjectName("FW_AsmPatAddRow")
            add.clicked.connect(lambda: self.add_row())
            lay.addWidget(add)
            ref = reference_point(feat, asm) if feat is not None else None
            if feat is not None:
                for p in feat.Offsets:
                    self.add_row(p)
            self.reference = QtWidgets.QLabel("")
            self.reference.setObjectName("FW_AsmPatReference")
            lay.addWidget(self.reference)
            self.form.append(box)
        elif kind == "SPattern":
            box, lay = asmpm._box("Selections", TITLES[kind], FAMILIES[kind])
            lay.addWidget(QtWidgets.QLabel("Reference Sketch:"))
            self.sketch_box = pick_box("FW_AsmPatSketch", self.sketch.Label if self.sketch is not None else "")
            lay.addWidget(self.sketch_box)
            lay.addWidget(QtWidgets.QLabel("Reference point: Centroid"))
            self.form.append(box)
            self.active = self.sketch_box
        fbox, flay = asmpm._box("Features to Pattern" if kind != "MPattern" else "Features to Mirror")
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_AsmPatFeatures")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 4))
        self.list.installEventFilter(self._focus)
        for s in self.sources:
            self.list.addItem(s.Label)
        flay.addWidget(self.list)
        self._error_label(flay)
        self.form.append(fbox)
        if self.active is None or (not self.sources and feat is None and kind == "TPattern"):
            self.active = self.list
        self._activate(self.active)
        Gui.Selection.addObserver(self, 0)

    def add_row(self, p=None):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for k in range(3):
            self.table.setItem(r, k, QtWidgets.QTableWidgetItem("%g" % (p[k] if p is not None else 0.0)))
        return r

    def _activate(self, w):
        for b in self._pick_boxes():
            b.setProperty("fwActive", b is w)
            b.setStyleSheet(b.styleSheet())
        self.active = w

    def _pick_boxes(self):
        return [getattr(self, n) for n in ("dir1_box", "dir2_box", "axis_box", "plane_box", "sketch_box", "list") if hasattr(self, n)]

    def _add_source(self, obj):
        if obj is not None and af.is_feature(obj) and obj not in self.sources and obj is not self.feat:
            self.sources.append(obj)
            self.list.addItem(obj.Label)
            return True
        return False

    def _pick(self, root, sub, point):
        if root is None:
            return
        target = root
        if sub:
            try:
                target = root.getSubObject(sub, retType=1) or root
            except Exception:
                target = root
        if af.is_feature(target) or af.is_feature(root):
            self._add_source(target if af.is_feature(target) else root)
            return
        if self.kind == "SPattern":
            sk = target if target.isDerivedFrom("Sketcher::SketchObject") else None
            if sk is None:
                try:
                    path = root.getSubObjectList(sub) if sub else [root]
                    sk = next((o for o in reversed(path) if o.isDerivedFrom("Sketcher::SketchObject")), None)
                except Exception:
                    sk = None
            if sk is not None:
                self.sketch = sk
                self.sketch_box.setText(sk.Label)
                self._activate(self.list)
            return
        g = _geometry(self.asm, root, sub)
        if g is None:
            return
        kind, p, d = g
        text = _pick_text(root, sub)
        if self.kind == "LPattern" and kind in ("line", "plane"):
            if self.active is getattr(self, "dir2_box", None) and self.use2.isChecked():
                self.dir2 = V(d)
                self.dir2_box.setText(text)
                self._activate(self.list)
            else:
                self.dir1 = V(d)
                self.dir1_box.setText(text)
                self._activate(self.dir2_box if self.use2.isChecked() and self.dir2 is None else self.list)
        elif self.kind == "CPattern" and kind in ("line", "circle"):
            self.axis = (V(p), V(d))
            self.axis_box.setText(text)
            self._activate(self.list)
        elif self.kind == "MPattern" and kind == "plane":
            self.plane = (V(p), V(d))
            self.plane_box.setText(text)
            self._activate(self.list)
        self.error.hide()

    def values(self):
        out = {"Sources": list(self.sources), "AutoSelect": True}
        if self.kind == "LPattern":
            d1 = V(self.dir1) * (-1 if self.rev1.isChecked() else 1)
            out.update({"Dir1": d1, "Spacing1": self.spacing1.value(), "Count1": self.count1.value()})
            if self.use2.isChecked() and self.dir2 is not None:
                out.update({"Dir2": V(self.dir2) * (-1 if self.rev2.isChecked() else 1),
                            "Spacing2": self.spacing2.value(), "Count2": self.count2.value()})
            else:
                out.update({"Dir2": V(), "Count2": 1})
        elif self.kind == "CPattern":
            out.update({"AxisPoint": self.axis[0], "AxisDir": self.axis[1] * (-1 if self.rev1.isChecked() else 1),
                        "PatternAngle": self.angle.value(), "Count1": self.count1.value(),
                        "EqualSpacing": self.equal.isChecked()})
        elif self.kind == "MPattern":
            out.update({"MirrorBase": self.plane[0], "MirrorNormal": self.plane[1]})
        elif self.kind == "TPattern":
            pts = []
            for r in range(self.table.rowCount()):
                try:
                    pts.append(V(*[float(self.table.item(r, k).text().replace(",", ".")) for k in range(3)]))
                except Exception as _fw_err:
                    _fw_log("asmfpattern.py:486", _fw_err)
                    continue
            out["Offsets"] = pts
        elif self.kind == "SPattern":
            out["Profile"] = self.sketch
        return out

    def accept(self):
        if not self.sources:
            return self._fail("Pick the assembly features to pattern in the FeatureManager tree.")
        if self.kind == "LPattern" and self.dir1 is None:
            return self._fail("Pick an edge or a face for Direction 1.")
        if self.kind == "CPattern" and self.axis is None:
            return self._fail("Pick an axis, a round edge or a round face for the pattern axis.")
        if self.kind == "MPattern" and self.plane is None:
            return self._fail("Pick the plane or flat face to mirror about.")
        if self.kind == "SPattern" and self.sketch is None:
            return self._fail("Pick the sketch whose points place the copies.")
        if self.kind == "TPattern" and not self.table.rowCount():
            return self._fail("Add the points of the copies.")
        values = self.values()
        self._close()
        if self.feat is None:
            self.doc.openTransaction(TITLES[self.kind])
            self.feat = make(self.asm, self.kind, values)
        else:
            set_values(self.feat, values)
            af.update(self.feat, True)
            self.feat.touch()
            self.doc.recompute()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        af._refresh()
        return True


class _Focus(QtCore.QObject):
    ""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, obj, event):
        if isinstance(event, QtCore.QEvent) and event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.FocusIn):
            self.panel._activate(obj)
        return False


def _count(name, value):
    box = QtWidgets.QSpinBox()
    box.setObjectName(name)
    box.setRange(1, 1000)
    box.setValue(int(value))
    return box


# ---------------------------------------------------------------- commands
def _picked_features():
    """The assembly features picked (in the tree), the seeds of a new pattern."""
    out = []
    for obj in Gui.Selection.getSelection():
        if af.is_feature(obj) and obj not in out:
            out.append(obj)
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub in sel.SubElementNames or [""]:
            try:
                obj = sel.Object.getSubObject(sub, retType=1) if sub else sel.Object
            except Exception:
                obj = None
            if obj is not None and af.is_feature(obj) and obj not in out:
                out.append(obj)
    return out


class _PatternCommand:
    KIND = "LPattern"

    def GetResources(self):
        return {"MenuText": TITLES[self.KIND], "Pixmap": ICONS[self.KIND],
                "ToolTip": "%s of assembly cuts and holes, in the assembly only." % TITLES[self.KIND]}

    def Activated(self):
        from . import asmtools
        asm = asmtools._assembly()
        if asm is None:
            return
        af._show(PatternPanel(asm, self.KIND, seeds=_picked_features()))

    def IsActive(self):
        asm = ac.assembly_of(App.ActiveDocument) if App.ActiveDocument is not None else None

        return asm is not None


def _command(kind):
    return type("AsmPattern_" + kind, (_PatternCommand,), {"KIND": kind})


COMMAND_NAMES = {"LPattern": "SWStyle_AsmLinearPattern", "CPattern": "SWStyle_AsmCircularPattern",
                 "MPattern": "SWStyle_AsmMirror", "TPattern": "SWStyle_AsmTableDrivenPattern",
                 "SPattern": "SWStyle_AsmSketchDrivenPattern"}
COMMANDS = tuple((COMMAND_NAMES[k], _command(k)) for k in NAMES)
CATALOG = tuple(("Asm" + COMMAND_NAMES[k][len("SWStyle_Asm"):], TITLES[k], COMMAND_NAMES[k], FAMILIES[k],
                 "%s of assembly cuts and holes, in the assembly only." % TITLES[k]) for k in NAMES)


def install():
    """Teaches asmfeature the pattern kinds: names, icons, their cut and their PM."""
    if getattr(af, "_fw_patterns", False):
        return
    for k in NAMES:
        af.KINDS[k] = NAMES[k]
        af.ICONS[k] = ICONS[k]
    tool0, edit0 = af.tool, af.edit

    def tool(feat, asm=None):
        if is_pattern(feat):
            return pattern_tool(feat, asm)
        return tool0(feat, asm)

    def edit(feat):
        if is_pattern(feat):
            asm = ac.assembly_of(feat.Document)
            return af._show(PatternPanel(asm, getattr(feat, af.FEATURE_PROP), feat=feat)) if asm is not None else None
        return edit0(feat)
    af.tool, af.edit = tool, edit
    af._fw_patterns = True
