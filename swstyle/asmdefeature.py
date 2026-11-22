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

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except Exception:   # pragma: no cover
    Gui = None

from . import asmcore as ac

METHODS = ("Remove details", "Silhouette")
SILHOUETTES = ("Bounding box", "Cylinder")
V = App.Vector


# ---------------------------------------------------------------- the geometry
def detail_faces(shape, holes=True, hole_max=10.0, fillets=True, fillet_max=3.0):
    """The faces Remove details takes away: holes (inner cylinders up to hole_max across) and
    fillets and chamfers (round faces up to fillet_max radius, narrow bevels)."""
    out = []
    for face in shape.Faces:
        s = face.Surface
        kind = s.TypeId
        if kind == "Part::GeomCylinder":
            r = s.Radius
            if _is_hole(shape, face):
                if holes and 2.0 * r <= hole_max + 1e-9:
                    out.append(face)
            elif fillets and r <= fillet_max + 1e-9 and _partial(face):
                out.append(face)
        elif kind in ("Part::GeomToroid", "Part::GeomSphere") and fillets:
            r = getattr(s, "MinorRadius", getattr(s, "Radius", 1e9))
            if r <= fillet_max + 1e-9:
                out.append(face)
        elif kind == "Part::GeomPlane" and fillets and _bevel(face, fillet_max):
            out.append(face)
        elif kind == "Part::GeomCone" and holes and _is_hole(shape, face):
            out.append(face)      # a countersink or drill point
    return out


def _partial(face):
    """A round face that is not a whole cylinder: a fillet (an arc of less than a half turn)."""
    try:
        u0, u1, _v0, _v1 = face.ParameterRange
        return (u1 - u0) < math.pi + 1e-6
    except Exception:
        return False


def _is_hole(shape, face):
    """A cylinder whose material is outside it (its normal points to the axis)."""
    try:
        u0, u1, v0, v1 = face.ParameterRange
        u, v = (u0 + u1) / 2.0, (v0 + v1) / 2.0
        p = face.valueAt(u, v)
        n = face.normalAt(u, v)
        axis = face.Surface.Axis
        c = face.Surface.Center
        d = p - c
        radial = d - axis * d.dot(axis)
        if radial.Length < 1e-9:
            return False
        return n.dot(radial) < 0
    except Exception as _fw_err:
        _fw_log("asmdefeature.py:99", _fw_err)
        return False


def _bevel(face, width):
    """A narrow flat face between two others at an angle: a chamfer up to width across."""
    try:
        b = face.BoundBox
        dims = sorted((b.XLength, b.YLength, b.ZLength))
        if dims[1] > width * 1.5 + 1e-9 or face.Area < 1e-9:
            return False
        n = face.normalAt(0, 0)
        return all(abs(abs(n[i]) - 1.0) > 1e-6 for i in range(3))   # not square to the axes
    except Exception as _fw_err:
        _fw_log("asmdefeature.py:113", _fw_err)
        return False


def remove_details(shape, **opts):
    """The shape with its details taken away, or as it was where OpenCASCADE cannot."""
    faces = detail_faces(shape, **opts)
    if not faces:
        return shape.copy(), 0
    try:
        out = shape.defeaturing(faces)
        if out.isValid() and not out.isNull() and out.Volume > 1e-9:
            return out, len(faces)
    except Exception as _fw_err:
        _fw_log("asmdefeature.py:124", _fw_err)
    done, n = shape.copy(), 0
    for face in faces:             # one at a time: keep the ones it can take
        try:
            match = [f for f in done.Faces if f.isSame(face) or _same_face(f, face)]
            if not match:
                continue
            nxt = done.defeaturing(match)
            if nxt.isValid() and nxt.Volume > 1e-9:
                done, n = nxt, n + 1
        except Exception as _fw_err:
            _fw_log("asmdefeature.py:138", _fw_err)
            continue
    return done, n


def _same_face(a, b):
    return abs(a.Area - b.Area) < 1e-6 and (a.CenterOfMass - b.CenterOfMass).Length < 1e-6


def _box(shape):
    try:
        return shape.optimalBoundingBox(False, False)     # exact, not from the tessellation
    except Exception:
        return shape.BoundBox


def silhouette(shape, kind="Bounding box"):
    """A simple solid around the shape: its box, or a cylinder on its longest axis (a round
    component's own radius when it has an outer cylinder on that axis)."""
    import Part
    b = _box(shape)
    if kind == "Cylinder":
        dims = [(b.XLength, V(1, 0, 0)), (b.YLength, V(0, 1, 0)), (b.ZLength, V(0, 0, 1))]
        length, axis = max(dims, key=lambda d: d[0])
        across = [d[0] for d in dims if d[1] != axis]
        c = V(b.Center)
        r = math.hypot(*across) / 2.0
        rounds = [f.Surface.Radius for f in shape.Faces if f.Surface.TypeId == "Part::GeomCylinder"
                  and abs(abs(f.Surface.Axis.dot(axis)) - 1.0) < 1e-6 and not _is_hole(shape, f)]
        if rounds and max(rounds) * 2.0 >= max(across) - 1e-3:
            r = max(rounds)
        start = c - axis * (length / 2.0)
        return Part.makeCylinder(max(r, 1e-6), max(length, 1e-6), start, axis)
    return Part.makeBox(max(b.XLength, 1e-6), max(b.YLength, 1e-6), max(b.ZLength, 1e-6), V(b.XMin, b.YMin, b.ZMin))


def defeature(asm, comps=None, method="Remove details", remove_internal=True, holes=True, hole_max=10.0,
              fillets=True, fillet_max=3.0, shape_kind="Bounding box", name=None, groups=(), propagate=True):
    """The new part: one body per component kept. Returns (document, {component label: removed})."""
    from . import asmtools, asmmenubar
    comps = list(comps) if comps is not None else [c for c in ac.components(asm) if c.Visibility]
    if method == "Remove details" and remove_internal:
        inside = set(c.Name for c in asmmenubar.internal(asm))
        comps = [c for c in comps if c.Name not in inside]
    doc = App.newDocument(name or (asm.Document.Label + "_Defeature"))
    report = {}
    group_of = {}
    for i, g in enumerate(groups or ()):
        for c in g:
            group_of.setdefault(c.Name, i)
    grouped = {}
    for comp in comps:
        try:
            shape = asmtools._global_shape(comp)
        except Exception:
            shape = None
        if shape is None or shape.isNull():
            continue
        if method == "Silhouette":
            out, n = silhouette(shape, shape_kind), 1
        else:
            out, n = remove_details(shape, holes=holes, hole_max=hole_max, fillets=fillets, fillet_max=fillet_max)
        if comp.Name in group_of:
            grouped.setdefault(group_of[comp.Name], []).append((comp, out))
            report[comp.Label] = n
            continue
        body = doc.addObject("Part::Feature", "Body")
        body.Shape = out
        body.Label = comp.Label
        report[comp.Label] = n
        if propagate:
            from . import asmdefrules
            asmdefrules.propagate_visuals(comp, body)
    import Part
    for i in sorted(grouped):
        shapes = [sh for _c, sh in grouped[i]]
        try:
            out = shapes[0].fuse(shapes[1:]).removeSplitter() if len(shapes) > 1 else shapes[0]
            if not out.Solids:
                raise ValueError("no solid")
        except Exception:
            out = Part.makeCompound(shapes)
        body = doc.addObject("Part::Feature", "Body")
        body.Shape = out
        body.Label = "Group%d" % (i + 1)
        if propagate:
            from . import asmdefrules
            asmdefrules.propagate_visuals(grouped[i][0][0], body)
    doc.recompute()
    return doc, report


# ---------------------------------------------------------------- the PropertyManager
def paths_params():
    from . import paths
    return paths.params()


class DefeaturePanel:
    ""

    def __init__(self, asm):
        from . import asmpm
        self.asm = asm
        self.comps = [c for c in ac.components(asm) if c.Visibility]
        mbox, ml = asmpm._box("Method", "Defeature")
        mbox.setObjectName("FW_AsmDefeature")
        self.details = QtWidgets.QRadioButton("Remove details")
        self.details.setObjectName("FW_DefeatureDetails")
        self.silh = QtWidgets.QRadioButton("Silhouette")
        self.silh.setObjectName("FW_DefeatureSilhouette")
        self.rules_radio = QtWidgets.QRadioButton("Rules")
        self.rules_radio.setObjectName("FW_DefeatureRules")
        self.rules_radio.setToolTip("Run the rules from the Rules Editor, top to bottom")
        self.details.setChecked(True)
        ml.addWidget(self.details)
        ml.addWidget(self.silh)
        ml.addWidget(self.rules_radio)
        self.propagate = QtWidgets.QCheckBox("Propagate visual properties")
        self.propagate.setObjectName("FW_DefeaturePropagate")
        self.propagate.setToolTip("The new part keeps the components' appearances and transparency")
        self.propagate.setChecked(paths_params().GetBool("DefeaturePropagateVisuals", True))
        self.propagate.toggled.connect(lambda on: paths_params().SetBool("DefeaturePropagateVisuals", on))
        ml.addWidget(self.propagate)
        cbox, cl = asmpm._box("Components")
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_DefeatureComponents")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 5))
        cl.addWidget(self.list)
        hint = QtWidgets.QLabel("Click a component to add it or take it out.")
        hint.setWordWrap(True)
        cl.addWidget(hint)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.groups = []
        gbox, gl = asmpm._box("Define Motion")
        self.group_list = QtWidgets.QListWidget()
        self.group_list.setObjectName("FW_DefeatureGroups")
        self.group_list.setFixedHeight(asmpm._rows(self.group_list, 3))
        gl.addWidget(self.group_list)
        row = QtWidgets.QHBoxLayout()
        self.add_group_button = QtWidgets.QPushButton("Add Group")
        self.add_group_button.setObjectName("FW_DefeatureAddGroup")
        self.add_group_button.setToolTip("The components picked in the Components list move as one body")
        self.add_group_button.clicked.connect(lambda: self.add_group())
        self.del_group_button = QtWidgets.QPushButton("Delete Group")
        self.del_group_button.setObjectName("FW_DefeatureDeleteGroup")
        self.del_group_button.clicked.connect(lambda: self.delete_group())
        row.addWidget(self.add_group_button)
        row.addWidget(self.del_group_button)
        gl.addLayout(row)
        self.gbox = gbox
        rbox, rl = asmpm._box("Remove")
        self.internal = QtWidgets.QCheckBox("Internal components")
        self.internal.setObjectName("FW_DefeatureInternal")
        self.internal.setChecked(True)
        rl.addWidget(self.internal)
        form = QtWidgets.QFormLayout()
        self.holes = QtWidgets.QCheckBox("Holes up to")
        self.holes.setObjectName("FW_DefeatureHoles")
        self.holes.setChecked(True)
        self.hole_max = _length("FW_DefeatureHoleMax", 10.0)
        form.addRow(self.holes, self.hole_max)
        self.fillets = QtWidgets.QCheckBox("Fillets and chamfers up to")
        self.fillets.setObjectName("FW_DefeatureFillets")
        self.fillets.setChecked(True)
        self.fillet_max = _length("FW_DefeatureFilletMax", 3.0)
        form.addRow(self.fillets, self.fillet_max)
        rl.addLayout(form)
        self.holes.toggled.connect(self.hole_max.setEnabled)
        self.fillets.toggled.connect(self.fillet_max.setEnabled)
        sbox, sl = asmpm._box("Silhouette")
        self.shape = QtWidgets.QComboBox()
        self.shape.setObjectName("FW_DefeatureShape")
        self.shape.addItems(list(SILHOUETTES))
        sform = QtWidgets.QFormLayout()
        sform.addRow("Simplify to:", self.shape)
        sl.addLayout(sform)
        from . import asmdefrules as dr
        self.rules = dr.saved()
        self.rule_result, self.rule_log = None, []
        ubox, ul = asmpm._box("Rules")
        self.rule_list = QtWidgets.QListWidget()
        self.rule_list.setObjectName("FW_DefeatureRuleSummary")
        self.rule_list.setFixedHeight(asmpm._rows(self.rule_list, 4))
        ul.addWidget(self.rule_list)
        urow = QtWidgets.QHBoxLayout()
        self.editor_button = QtWidgets.QPushButton("Rules Editor...")
        self.editor_button.setObjectName("FW_DefeatureRulesEditorButton")
        self.editor_button.clicked.connect(lambda: self.edit_rules())
        self.apply_button = QtWidgets.QPushButton("Apply Rules")
        self.apply_button.setObjectName("FW_DefeatureApplyRules")
        self.apply_button.setToolTip("Run the rules now and show what each component becomes")
        self.apply_button.clicked.connect(lambda: self.apply_rules())
        urow.addWidget(self.editor_button)
        urow.addWidget(self.apply_button)
        ul.addLayout(urow)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setObjectName("FW_DefeatureRuleLog")
        self.log.setReadOnly(True)
        self.log.setFixedHeight(asmpm._rows(self.rule_list, 5))
        ul.addWidget(self.log)
        self.ubox = ubox
        self._show_rules()
        self.rbox, self.sbox = rbox, sbox
        self.details.toggled.connect(self._method)
        self.silh.toggled.connect(self._method)
        self.rules_radio.toggled.connect(self._method)
        self.form = [mbox, cbox, gbox, rbox, sbox, ubox]
        self._method()
        self._show()
        Gui.Selection.addObserver(self, 0)

    def method(self):
        if self.rules_radio.isChecked():
            return "Rules"
        return "Silhouette" if self.silh.isChecked() else "Remove details"

    def _method(self, *_a):
        m = self.method()
        self.rbox.setVisible(m == "Remove details")
        self.gbox.setVisible(m == "Remove details")
        self.sbox.setVisible(m == "Silhouette")
        self.ubox.setVisible(m == "Rules")

    def _show_rules(self):
        from . import asmdefrules as dr
        self.rule_list.clear()
        for i, r in enumerate(self.rules, 1):
            self.rule_list.addItem("%d. %s%s" % (i, dr.text(r), "" if r.get("on", True) else " (off)"))

    def edit_rules(self, run=True):
        """Opens the Rules Editor; returns it (run=False leaves it for the caller to drive)."""
        from . import asmdefrules as dr
        ed = dr.RulesEditor(self.rules, Gui.getMainWindow())
        if run and ed.exec_():
            self.rules = ed.rules
            self.rule_result = None
            self._show_rules()
        return ed

    def apply_rules(self):
        """Apply Rules: runs them now; the log says what each did, and what each component becomes."""
        from . import asmdefrules as dr
        self.rule_result, self.rule_log = dr.apply(self.asm, list(self.comps), self.rules)
        lines = list(self.rule_log)
        lines.append("")
        for c in self.comps:
            got = self.rule_result.get(c.Name)
            if got is not None:
                lines.append("%s: %s" % (c.Label, got[1]))
        self.log.setPlainText("\n".join(lines))
        return self.rule_result

    def add_group(self, comps=None):
        """Define Motion: comps (else the ones picked in the Components list) move as one."""
        if comps is None:
            rows = sorted(self.list.row(i) for i in self.list.selectedItems())
            comps = [self.comps[r] for r in rows if 0 <= r < len(self.comps)]
        taken = {c.Name for g in self.groups for c in g}
        comps = [c for c in comps if c.Name not in taken]
        if not comps:
            return None
        self.groups.append(comps)
        self._show_groups()
        return comps

    def delete_group(self, index=None):
        if index is None:
            index = self.group_list.currentRow()
        if 0 <= index < len(self.groups):
            del self.groups[index]
            self._show_groups()

    def _show_groups(self):
        self.group_list.clear()
        for i, g in enumerate(self.groups):
            self.group_list.addItem("Group%d: %s" % (i + 1, ", ".join(c.Label for c in g)))

    def _show(self):
        self.list.clear()
        for c in self.comps:
            self.list.addItem(c.Label)

    def toggle(self, comp):
        if comp in self.comps:
            self.comps.remove(comp)
        else:
            self.comps.append(comp)
        self.rule_result = None
        self._show()

    def addSelection(self, doc, obj, sub, pnt):
        names = {c.Name: c for c in ac.components(self.asm)}
        comp = names.get(obj) or names.get((sub or "").split(".")[0])
        if comp is not None:
            QtCore.QTimer.singleShot(0, lambda: (self.toggle(comp), Gui.Selection.clearSelection()))

    def removeSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def setPreselection(self, *a):
        pass

    def options(self):
        return dict(method=self.method(), remove_internal=self.internal.isChecked(),
                    holes=self.holes.isChecked(), hole_max=self.hole_max.value(),
                    fillets=self.fillets.isChecked(), fillet_max=self.fillet_max.value(),
                    shape_kind=self.shape.currentText(),
                    groups=[list(g) for g in self.groups] if not self.silh.isChecked() else [],
                    propagate=self.propagate.isChecked())

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmdefeature.py:453", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if not self.comps:
            return False
        opts, comps = self.options(), list(self.comps)
        if opts["method"] == "Rules":
            from . import asmdefrules as dr
            result = self.rule_result or dr.apply(self.asm, comps, self.rules)[0]
            self._close()
            doc = dr.make_part(self.asm, comps, result, propagate=opts["propagate"])
            self.result = (doc, {c.Label: result[c.Name][1] for c in comps if c.Name in result})
        else:
            self._close()
            self.result = defeature(self.asm, comps, **opts)
        try:
            Gui.SendMsgToActiveView("ViewFit")
        except Exception as _fw_err:
            _fw_log("asmdefeature.py:472", _fw_err)
        return True

    def reject(self):
        self._close()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def _length(name, value):
    w = QtWidgets.QDoubleSpinBox()
    w.setObjectName(name)
    w.setRange(0.01, 1e6)
    w.setDecimals(2)
    w.setSuffix(" mm")
    w.setValue(value)
    return w


def open_panel(asm=None):
    from . import asmpm, asmtools
    asm = asm or asmtools._assembly()
    if asm is None:
        return None
    if Gui.Control.activeDialog() and not asmpm.close_open():
        Gui.Control.closeDialog()
    panel = DefeaturePanel(asm)
    asmpm._track(panel)
    Gui.Control.showDialog(panel)
    return panel


class DefeatureCommand:
    def GetResources(self):
        return {"MenuText": "Defeature", "Pixmap": "Part_Defeaturing",
                "ToolTip": "Makes a simplified part from the assembly: details removed, or each component's silhouette."}

    def Activated(self, *a):
        open_panel()

    def IsActive(self):
        from . import asmtools
        return asmtools._assembly() is not None


COMMANDS = (("SWStyle_AsmDefeature", DefeatureCommand),)


def register():
    for name, cls in COMMANDS:
        try:
            Gui.addCommand(name, cls())
        except Exception as _fw_err:
            _fw_log("asmdefeature.py:527", _fw_err)
