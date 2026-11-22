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

import json

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

from . import simpms
from . import simxpress as sx

TYPES = ("Contact", "Bonded", "Free")
SET = "FwContactSet"            # on every pair: the set's label; the first pair also keeps the PM values (FwSimPM)
TOUCH = 1e-4                    # mm: faces closer than this touch


def _faces(obj, names):
    return [(n, obj.Shape.getElement(n)) for n in names]


def pairs(obj, set1, set2, gap=None):
    ""

    out = []
    reach = max(TOUCH, float(gap or 0.0))
    for n1, f1 in _faces(obj, set1):
        for n2, f2 in _faces(obj, set2):
            if n1 != n2 and f1.distToShape(f2)[0] < reach:
                out.append((n1, n2))
    return out


def _shared_area(f1, f2, reach):
    """The area two faces have face to face (faces that only meet along an edge share none). Touching faces: their
    common part; faces a gap apart: f1 moved onto f2 along f2's normal, when both are flat and parallel."""
    try:
        c = f1.common(f2)
        if c.Faces:
            return c.Area
        if reach > TOUCH and f1.Surface.TypeId == f2.Surface.TypeId == "Part::GeomPlane":
            n = f2.normalAt(0, 0)
            if abs(abs(f1.normalAt(0, 0).dot(n)) - 1.0) < 1e-6:
                d = (f2.CenterOfMass - f1.CenterOfMass).dot(n)
                g = f1.copy()
                g.translate(n * d)
                c = g.common(f2)
                return c.Area if c.Faces else 0.0
    except Exception as _fw_err:
        _fw_log("simconnect.py:shared", _fw_err)
    return 0.0


def gap_mm(obj, percent):
    ""
    return float(percent) / 100.0 * obj.Shape.BoundBox.DiagonalLength


def find_interactions(obj, gap=None):
    """Automatically find local interactions: the face pairs of two different solids of obj that touch (or are less
    than gap mm apart), as (Set 1 faces, Set 2 faces, [(face, face)...]). Set 1 holds the faces of the solid listed
    first in each pair."""
    shape = obj.Shape
    solids = list(shape.Solids)
    if len(solids) < 2:
        return [], [], []
    owner = {}
    for i, f in enumerate(shape.Faces, 1):
        for k, so in enumerate(solids):
            if any(f.isSame(x) for x in so.Faces):
                owner["Face%d" % i] = k
                break
    reach = max(TOUCH, float(gap or 0.0))
    names = sorted(owner, key=lambda n: int(n[4:]))
    found = []
    for a_i, n1 in enumerate(names):
        f1 = shape.getElement(n1)
        for n2 in names[a_i + 1:]:
            if owner[n1] == owner[n2]:
                continue
            f2 = shape.getElement(n2)
            box = App.BoundBox(f1.BoundBox)
            box.enlarge(reach)
            if not box.intersect(f2.BoundBox):
                continue
            if f1.distToShape(f2)[0] < reach and _shared_area(f1, f2, reach) > 1e-6 * min(f1.Area, f2.Area):
                lo, hi = (n1, n2) if owner[n1] < owner[n2] else (n2, n1)
                found.append((lo, hi))
    set1 = sorted({p_[0] for p_ in found}, key=lambda n: int(n[4:]))
    set2 = sorted({p_[1] for p_ in found}, key=lambda n: int(n[4:]))
    return set1, set2, found


def members(a, label):
    return [o for o in a.Group if getattr(o, SET, None) == label]


def head(o):
    """The set's first pair (the one that keeps the PM values) for any pair of it."""
    label = getattr(o, SET, None)
    a = next((x for x in o.InList if x.isDerivedFrom("Fem::FemAnalysis")), None)
    if label is None or a is None:
        return o
    return next((m for m in members(a, label) if simpms.kept(m)), o)


def _young_mpa(a):
    for o in a.Group:
        mat = getattr(o, "Material", None)
        if isinstance(mat, dict) and mat.get("YoungsModulus"):
            try:
                return App.Units.Quantity(mat["YoungsModulus"]).getValueAs("MPa").Value
            except Exception as _fw_err:
                _fw_log("simconnect.py:E", _fw_err)
    return 1e5


def add_contact_set(doc, a, obj, set1, set2, kind="Contact", friction=None, edit=None, gap=None, gap_percent=None,
                    auto=False):
    """A contact set between obj's Set 1 and Set 2 faces in study a: one FreeCAD Contact (or Tie for Bonded) per
    face pair that touches or is closer than gap (mm). friction: the coefficient, or None for frictionless. edit: a
    pair of the set to replace. gap_percent / auto are kept for the PM (Gap range %, Automatically find)."""
    import ObjectsFem
    if kind not in TYPES:
        raise simpms.SetupError("Unknown contact type %r." % kind)
    if not set1 or not set2:
        raise simpms.SetupError("Pick the faces of Set 1 and of Set 2.")
    found = pairs(obj, set1, set2, gap)
    if not found:
        raise simpms.SetupError("No face of Set 1 touches a face of Set 2 (or is within the gap range): pick faces "
                                "that lie on each other.")
    label = None
    if edit is not None:
        first = head(edit)
        label = first.Label
        for m in members(a, getattr(first, SET, None)) or [edit]:
            a.removeObject(m)
            doc.removeObject(m.Name)
    if label is None:
        label = simpms._label(a, "Contact Set")
    made = []
    size = obj.Shape.BoundBox.DiagonalLength
    if kind == "Free":
        # nothing for CalculiX: one tree item holding the faces, so the interactions leave them apart
        o = doc.addObject("App::FeaturePython", "FreeSet")
        o.addProperty("App::PropertyLinkSubList", "References", "FreeCAD", "The faces that do not interact")
        o.addProperty("App::PropertyBool", "Suppressed", "Base", "Left out of the run")
        o.References = [(obj, tuple(sorted({f for p_ in found for f in p_}, key=lambda n: int(n[4:]))))]
        a.addObject(o)
        o.addProperty("App::PropertyString", SET, "FreeCAD", "The contact set this item is")
        o.setPropertyStatus(SET, "Hidden")
        setattr(o, SET, label)
        o.Label = label
        made.append(o)
    with sx.fem_safe():
        for i, (f1, f2) in enumerate(found if kind != "Free" else ()):
            if kind == "Bonded":
                o = ObjectsFem.makeConstraintTie(doc, "Bonded")
                o.Tolerance = "%r mm" % max(0.1, 0.01 * size, 1.01 * float(gap or 0.0))
            else:
                o = ObjectsFem.makeConstraintContact(doc, "Contact")
                slope = 10.0 * _young_mpa(a)            # N/mm^3: stiff enough that the faces barely pass into each other
                o.Slope = "%r GPa/m" % slope
                if friction:
                    o.Friction = True
                    o.FrictionCoefficient = float(friction)
                    o.StickSlope = "%r GPa/m" % (slope / 10.0)
            o.References = [(obj, (f2,)), (obj, (f1,))]          # CalculiX: the first is the slave, the second the master
            a.addObject(o)
            o.addProperty("App::PropertyString", SET, "FreeCAD", "The contact set this face pair belongs to")
            o.setPropertyStatus(SET, "Hidden")
            setattr(o, SET, label)
            o.Label = label if i == 0 else "%s (pair %d)" % (label, i + 1)
            made.append(o)
    simpms._keep(made[0], contact=kind, set1=list(set1), set2=list(set2), friction=friction,
                 gap=float(gap) if gap else None, gap_percent=gap_percent, auto=bool(auto))
    _apart(a)
    doc.recompute()
    return made


def _owner(shape, sub):
    """The solid of shape that holds face sub."""
    face = shape.getElement(sub)
    for solid in shape.Solids:
        if any(face.isSame(f) for f in solid.Faces):
            return solid
    return None


def _one_side(femmesh, entries, obj, sub):
    """Keep the element faces of the solid that owns face sub. FreeCAD finds a face's mesh faces by where they are, so
    on two parts that touch it takes both parts' faces, and CalculiX then pairs a surface with itself."""
    solid = _owner(obj.Shape, sub)
    if solid is None:
        return entries
    out = []
    for refs, surf, is_sub_el in entries:
        if not is_sub_el:
            out.append((refs, surf, is_sub_el))
            continue
        keep = []
        for elem, fno in surf:
            nodes = femmesh.getElementNodes(elem)
            c = App.Vector()
            for n in nodes:
                c = c + femmesh.getNodeById(n)
            if solid.isInside(c * (1.0 / len(nodes)), 1e-6, True):
                keep.append((elem, fno))
        out.append((refs, keep, is_sub_el))
    return out


def _shim():
    """Contact and Bonded sets made here get their own side's mesh faces (see _one_side); FreeCAD's own objects are left
    as they are. If this FreeCAD's mesh sets work differently, nothing is changed."""
    try:
        from femmesh import meshsetsgetter as msg
    except ImportError:
        return False
    cls = msg.MeshSetsGetter
    if getattr(cls, "_fw_contact_shim", False):
        return True
    for name, slave, master in (("get_constraints_contact_faces", "ContactSlaveFaces", "ContactMasterFaces"),
                                ("get_constraints_tie_faces", "TieSlaveFaces", "TieMasterFaces")):
        orig = getattr(cls, name, None)
        if orig is None:
            return False

        def wrapped(self, _orig=orig, _slave=slave, _master=master, _name=name):
            _orig(self)
            members_ = self.member.cons_contact if "contact" in _name else self.member.cons_tie
            for femobj in members_:
                o = femobj["Object"]
                if getattr(o, SET, None) is None:
                    continue
                try:
                    refs = [(r[0], sub) for r in o.References for sub in r[1]]     # one entry (same object) or two
                    if len(refs) != 2:
                        continue
                    (obj, s_sub), (_m, m_sub) = refs
                    femobj[_slave] = _one_side(self.femmesh, femobj[_slave], obj, s_sub)
                    femobj[_master] = _one_side(self.femmesh, femobj[_master], obj, m_sub)
                except Exception as _fw_err:
                    _fw_log("simconnect.py:shim", _fw_err)
        setattr(cls, name, wrapped)
    cls._fw_contact_shim = True
    return True


def _apart(a):
    """A contact set needs the two parts meshed apart: Gmsh's coherence merges the touching faces' nodes (glued, and
    CalculiX then loops on a tie or contact between the same nodes). A mesh made with it is cleared, so the next run
    meshes again."""
    try:
        m = simpms.gmsh_of(a)
    except Exception as _fw_err:
        _fw_log("simconnect.py:mesh", _fw_err)
        return
    if m is None or not getattr(m, "CoherenceMesh", False):
        return
    m.CoherenceMesh = False
    import Fem
    if m.FemMesh.NodeCount:
        m.FemMesh = Fem.FemMesh()


# =========================================================================== GUI
if Gui is not None:
    class ContactPM(simpms._PM):
        ""



        PM = "Local Interactions"

        def __init__(self, doc, kind="Contact", edit=None):
            edit = head(edit) if edit is not None else None
            super().__init__(doc, edit)
            k = simpms.kept(edit) if edit is not None else {}
            kind = k.get("contact", kind)
            inter = sx._box("Interaction", None, self.PM)
            il = QtWidgets.QVBoxLayout(inter)
            self.manual = QtWidgets.QRadioButton("Manually select local interactions")
            self.manual.setObjectName("SWSimContactManual")
            self.auto = QtWidgets.QRadioButton("Automatically find local interactions")
            self.auto.setObjectName("SWSimContactAuto")
            self.manual.setChecked(True)
            il.addWidget(self.manual)
            il.addWidget(self.auto)
            self.find = QtWidgets.QPushButton("Find Local Interactions")
            self.find.setObjectName("SWSimContactFind")
            self.find.setToolTip("Every face pair of two different bodies that touch: they fill Set 1 and Set 2")
            self.find.clicked.connect(self._find)
            il.addWidget(self.find)
            self.results = QtWidgets.QListWidget()
            self.results.setObjectName("SWSimContactResults")
            self.results.setFixedHeight(64)
            il.addWidget(self.results)
            typ = sx._box("Type")
            tl = QtWidgets.QVBoxLayout(typ)
            self.kind = QtWidgets.QComboBox()
            self.kind.setObjectName("SWSimContactType")
            self.kind.addItems(list(TYPES))
            tl.addWidget(self.kind)
            self.set1 = sx._PickList("SWSimContactSet1")
            self.set1.setToolTip("Faces for Set 1 (click them; a second click takes one out)")
            self.set2 = sx._PickList("SWSimContactSet2")
            self.set2.setToolTip("Faces for Set 2: the faces they lie on")
            self.swap = QtWidgets.QToolButton()
            self.swap.setObjectName("SWSimContactSwap")
            self.swap.setText("\u21c5")
            self.swap.setToolTip("Swap Set 1 and Set 2")
            self.swap.clicked.connect(self._swap)
            tl.addWidget(self.set1)
            srow = QtWidgets.QHBoxLayout()
            srow.addWidget(self.swap)
            srow.addStretch(1)
            tl.addLayout(srow)
            tl.addWidget(self.set2)
            opt = sx._box("Properties")
            ol = QtWidgets.QFormLayout(opt)
            self.gap = QtWidgets.QDoubleSpinBox()
            self.gap.setObjectName("SWSimContactGap")
            self.gap.setRange(0.0, 100.0)
            self.gap.setDecimals(2)
            self.gap.setSuffix("%")
            self.gap_mm = QtWidgets.QLabel("")
            self.gap_mm.setObjectName("SWSimContactGapMM")
            grow = QtWidgets.QHBoxLayout()
            grow.addWidget(self.gap)
            grow.addWidget(self.gap_mm, 1)
            self.gap_label = QtWidgets.QLabel("Gap range to consider contact:")
            ol.addRow(self.gap_label)
            ol.addRow(grow)
            self.friction = QtWidgets.QCheckBox("Coefficient of friction")
            self.friction.setObjectName("SWSimContactFriction")
            self.coef = QtWidgets.QDoubleSpinBox()
            self.coef.setObjectName("SWSimContactCoefficient")
            self.coef.setRange(0.0, 1.0)
            self.coef.setDecimals(3)
            self.coef.setSingleStep(0.05)
            self.coef.setValue(0.05)
            ol.addRow(self.friction, self.coef)
            self.opt = opt
            self.inter = inter
            self.boxes = [self.set1, self.set2]
            self.form = [inter, typ, opt]
            self.kind.setCurrentText(kind)
            self.gap.setValue(k.get("gap_percent") if k.get("gap_percent") is not None else self._default_gap(kind))
            if edit is not None:
                self.set1.addItems(k.get("set1") or [])
                self.set2.addItems(k.get("set2") or [])
                if k.get("friction"):
                    self.friction.setChecked(True)
                    self.coef.setValue(float(k["friction"]))
                if k.get("auto"):
                    self.auto.setChecked(True)
            self.kind.currentTextChanged.connect(lambda *_: self._kind_changed())
            self.friction.toggled.connect(lambda *_: self._enable())
            self.auto.toggled.connect(lambda *_: self._enable())
            self.gap.valueChanged.connect(lambda *_: self._gap_text())
            self._gap_text()
            self._enable()
            self._start()

        @staticmethod
        def _default_gap(kind):

            return 0.01 if kind == "Bonded" else 10.0

        def _gap(self):
            return gap_mm(self.obj, self.gap.value()) if self.obj is not None else 0.0

        def _gap_text(self):
            self.gap_mm.setText("= %.4g mm" % self._gap())

        def _kind_changed(self):
            self.gap.setValue(self._default_gap(self.kind.currentText()))
            self._enable()

        def _swap(self):
            a = self.set1.values()
            b = self.set2.values()
            self.set1.clear()
            self.set2.clear()
            self.set1.addItems(b)
            self.set2.addItems(a)

        def _find(self):
            s1, s2, found = find_interactions(self.obj) if self.obj is not None else ([], [], [])
            self.set1.clear()
            self.set2.clear()
            self.set1.addItems(s1)
            self.set2.addItems(s2)
            self.results.clear()
            self.results.addItems(["%s - %s" % p_ for p_ in found] or ["No touching faces of two bodies were found."])

        def _picked(self, name, sub):
            last = (sub or "").split(".")[-1]
            if self.current is not None and last.startswith("Face"):
                self.current.toggle(last)
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("simconnect.py:pick", _fw_err)

        def _enable(self):
            kind = self.kind.currentText()
            c = kind == "Contact"

            simpms._box_visible(self.opt, kind != "Free")
            self.gap_label.setText("Gap range for bonding:" if kind == "Bonded" else "Gap range to consider contact:")
            self.friction.setVisible(c)
            self.coef.setVisible(c and self.friction.isChecked())
            auto = self.auto.isChecked()
            self.find.setVisible(auto)
            self.results.setVisible(auto)
            QtCore.QTimer.singleShot(0, lambda: self._open() and simpms._box_visible(
                self.opt, self.kind.currentText() != "Free"))

        def apply(self):
            kind = self.kind.currentText()
            fr = self.coef.value() if kind == "Contact" and self.friction.isChecked() else None
            gap = self._gap() if kind != "Free" else None
            return add_contact_set(self.doc, self.a, self.obj, self.set1.values(), self.set2.values(),
                                   kind, fr, self.edit, gap, self.gap.value() if kind != "Free" else None,
                                   self.auto.isChecked())

    def edit_definition(o):
        """Our PM for o (a contact set pair, or a fixture / load from simpms), else None."""
        if getattr(o, SET, None) is not None:
            return simpms.show(ContactPM(o.Document, edit=o))
        return simpms.edit_definition(o)

    def ours(o):
        return getattr(o, SET, None) is not None or bool(simpms.kept(o)) and o.TypeId.startswith("Fem::Constraint")

    class EditHook:
        ""

        def slotInEdit(self, vp):
            try:
                o = vp.Object
            except Exception:
                return
            if ours(o):
                QtCore.QTimer.singleShot(0, lambda: self._swap(o))

        def _swap(self, o):
            try:
                gd = Gui.getDocument(o.Document.Name)
                gd.resetEdit()
                if Gui.Control.activeDialog():
                    Gui.Control.closeDialog()
                edit_definition(o)
            except Exception as e:
                App.Console.PrintWarning("FreeCAD Edit Definition: %s\n" % e)

    HOOK = {"hook": None}

    class _Cmd:
        def __init__(self, text, tip, kind, pixmap):
            self.text, self.tip, self.kind, self.pixmap = text, tip, kind, pixmap

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": self.pixmap}

        def IsActive(self):
            doc = App.ActiveDocument
            return doc is not None and not Gui.Control.activeDialog() and simpms.active_study(doc) is not None

        def Activated(self):
            simpms.show(ContactPM(App.ActiveDocument, self.kind))

    COMMANDS = {
        "SWStyle_SimContact": _Cmd("Contact Set", "Faces that press on each other (Contact), are glued (Bonded) or "
                                   "do not interact (Free).", "Contact", "FEM_ConstraintContact"),
        "SWStyle_SimBonded": _Cmd("Bonded", "Faces glued together (a Bonded contact set).", "Bonded", "FEM_ConstraintTie"),
    }

KEYS = (
    ("SIM_Contact", "Contact Set", ("SWStyle_SimContact", "FEM_ConstraintContact"),
     "Faces that press on each other (Contact) or are glued (Bonded).", "Connections\nAdvisor"),
    ("SIM_Bonded", "Bonded", ("SWStyle_SimBonded", "FEM_ConstraintTie"), "Faces glued together.", None),
)


def install():
    if Gui is None:
        return
    from . import catalog
    have = set(Gui.listCommands())
    for name, cmd in COMMANDS.items():
        if name not in have:
            Gui.addCommand(name, cmd)
    for key, label, natives, tip, caption in KEYS:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, natives, None, tip, caption=caption)
    _shim()
    if HOOK["hook"] is None:
        HOOK["hook"] = EditHook()
        Gui.addDocumentObserver(HOOK["hook"])
