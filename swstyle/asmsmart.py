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
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import asmcore as ac
from . import asmfeature as af

SMART_TYPE = "SWStyle::SmartComponent"
LAST = {}
OPEN = []


# ---------------------------------------------------------------------- the smart data
class SmartData:
    Type = SMART_TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        for kind, name, tip in (("App::PropertyStringList", "Components", "Associated components (json)"),
                                ("App::PropertyStringList", "Features", "Associated features (json)"),
                                ("App::PropertyBool", "AutoSize", "Auto size: configurations picked by size"),
                                ("App::PropertyStringList", "Sizes", "Auto size: configuration, min and max diameter (json)")):
            if name not in obj.PropertiesList:
                obj.addProperty(kind, name, "Smart Component", tip)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class SmartDataView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        from pivy import coin
        self.Object = vobj.Object
        vobj.addDisplayMode(coin.SoGroup(), "Default")

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return ":/icons/Std_LinkMake.svg"

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _target(comp):
    """The component's own part (not the cut copy an assembly feature shows)."""
    try:
        return af.own_part(comp)
    except Exception:
        return getattr(comp, "LinkedObject", None)


def data(comp):
    """The SmartComponent data of the component's part, or None."""
    target = _target(comp)
    if target is None:
        return None
    return next((o for o in target.Document.Objects
                 if getattr(getattr(o, "Proxy", None), "Type", None) == SMART_TYPE), None)


def is_smart(comp):
    return data(comp) is not None


def _pl_text(pl):
    return [list(pl.Base), list(pl.Rotation.Q)]


def _pl_from(v):
    return App.Placement(App.Vector(*v[0]), App.Rotation(*v[1]))


def configurations_of(comp):
    from . import asmreplacecomp
    t = _target(comp)
    try:
        return list(asmreplacecomp.configurations(t.Document) or []) if t is not None else []
    except Exception:
        return []


def sizes_of(comp):
    """[(configuration, min, max)] of an auto size smart component ([] when Auto size is off)."""
    obj = data(comp)
    if obj is None or not getattr(obj, "AutoSize", False):
        return []
    out = []
    for t in getattr(obj, "Sizes", []) or []:
        try:
            r = json.loads(t)
            out.append((r["config"], float(r["min"]), float(r["max"])))
        except Exception as _fw_err:
            _fw_log("asmsmart.py:150", _fw_err)
    return out


def diameter_of(shape):
    """A reference's diameter: a cylindrical face's or a circular edge's (else None)."""
    try:
        if shape.ShapeType == "Face" and hasattr(shape.Surface, "Radius"):
            return 2.0 * shape.Surface.Radius
        if shape.ShapeType == "Edge" and hasattr(shape.Curve, "Radius"):
            return 2.0 * shape.Curve.Radius
    except Exception as _fw_err:
        _fw_log("asmsmart.py:162", _fw_err)
    return None


def size_for(sizes, d):
    """The configuration whose [min, max] holds d (the smallest such range), else None."""
    hits = [(hi - lo, c) for c, lo, hi in sizes if lo - 1e-9 <= d <= hi + 1e-9]
    return min(hits)[1] if hits else None


def make_smart(asm, smart, comps, feats, auto_size=False, sizes=()):
    """Keep comps and feats (assembly features) in smart's part, relative to smart. Returns the data."""
    target = _target(smart)
    doc = target.Document
    inv = smart.Placement.inverse()
    rows = []
    for c in comps:
        t = _target(c)
        if t is None:
            continue
        rows.append(json.dumps({"file": t.Document.FileName, "doc": t.Document.Name, "object": t.Name,
                                "label": ac.part_name(c), "placement": _pl_text(inv.multiply(c.Placement))}))
    frows = []
    for f in feats:
        solid = af.tool(f, asm)
        if solid is None or solid.isNull():
            continue
        local = solid.transformed(inv.toMatrix())
        frows.append(json.dumps({"name": f.Label, "brep": local.exportBrepToString()}))
    obj = data(smart)
    if obj is None:
        obj = doc.addObject("App::FeaturePython", "SmartComponent")
        SmartData(obj)
        if App.GuiUp:
            SmartDataView(obj.ViewObject)
        obj.Label = "Smart Component"
    obj.Components, obj.Features = rows, frows
    obj.AutoSize = bool(auto_size)
    obj.Sizes = [json.dumps({"config": c, "min": float(lo), "max": float(hi)}) for c, lo, hi in sizes or ()]
    doc.recompute()
    if doc.FileName:
        doc.save()
    return obj


def components_of(comp):
    obj = data(comp)
    return [json.loads(t) for t in (obj.Components if obj else [])]


def features_of(comp):
    obj = data(comp)
    return [json.loads(t) for t in (obj.Features if obj else [])]


# ---------------------------------------------------------------------- smart features in an assembly
def _install_tool():
    if getattr(af, "_fw_smart", False):
        return
    af.KINDS.setdefault("Smart", "Cut-Extrude")
    af.ICONS.setdefault("Smart", "PartDesign_Pocket")
    tool0 = af.tool

    def tool(feat, asm=None):
        if getattr(feat, af.FEATURE_PROP, "") != "Smart":
            return tool0(feat, asm)
        owner = feat.Document.getObject(getattr(feat, "SmartOwner", "") or "")
        text = getattr(feat, "SmartTool", "")
        if owner is None or not text:
            return None
        shape = Part.Shape()
        shape.importBrepFromString(text)
        return shape.transformed(owner.Placement.toMatrix())
    af.tool = tool
    scope0 = af.scope_of

    def scope_of(feat, asm, solid=None):
        out = scope0(feat, asm, solid)
        if getattr(feat, af.FEATURE_PROP, "") != "Smart":
            return out
        skip = {getattr(feat, "SmartOwner", "")} | set(getattr(feat, "SmartSkip", []) or [])
        return [c for c in out if c.Name not in skip]     # never the smart component's own parts
    af.scope_of = scope_of
    af._fw_smart = True


def insert_smart_features(asm, smart, comp_rows=None, feat_rows=None, diameter=None):
    """Insert the smart component's components and features. Returns (components, features).
    With diameter (Auto size's reference), the smart component first shows the configuration
    sized for it."""
    _install_tool()
    if diameter is not None:
        config = size_for(sizes_of(smart), diameter)
        if config is not None:
            from . import asmreplacecomp
            asmreplacecomp.set_configuration(_target(smart), config)
            LAST["size"] = config
    comp_rows = components_of(smart) if comp_rows is None else comp_rows
    feat_rows = features_of(smart) if feat_rows is None else feat_rows
    doc = asm.Document
    made, cuts = [], []
    for row in comp_rows:
        src = None
        try:
            src = App.getDocument(row["doc"])
        except Exception:
            src = None
        if src is None and row.get("file"):
            try:
                src = App.openDocument(row["file"], True)
            except Exception:
                src = None
        obj = src.getObject(row["object"]) if src is not None else None
        if obj is None:
            continue
        made.append(ac.insert(asm, obj, smart.Placement.multiply(_pl_from(row["placement"]))))
    for row in feat_rows:
        feat = asm.newObject("App::FeaturePython", "AsmCut")
        af.Feature(feat, "Smart")
        if App.GuiUp and feat.ViewObject is not None:
            af.ViewProviderFeature(feat.ViewObject)
        feat.addProperty("App::PropertyString", "SmartOwner", "Smart Feature", "The smart component")
        feat.addProperty("App::PropertyString", "SmartTool", "Smart Feature", "The cut, relative to it (BREP)")
        feat.setPropertyStatus("SmartTool", "Hidden")
        feat.addProperty("App::PropertyStringList", "SmartSkip", "Smart Feature", "Components it never cuts")
        feat.SmartOwner, feat.SmartTool = smart.Name, row["brep"]
        feat.SmartSkip = [c.Name for c in made]
        feat.AutoSelect = True
        feat.Label = af._next_label(asm, row.get("name", "Cut-Extrude").rstrip("0123456789") or "Cut-Extrude")
        cuts.append(feat)
    if cuts:
        af.update(cuts[-1], True)
    doc.recompute()
    return made, cuts


# ---------------------------------------------------------------------- PropertyManagers
def _list(name, parent, height=60):
    w = QtWidgets.QListWidget(parent)
    w.setObjectName(name)
    w.setMaximumHeight(height)
    return w


class _Panel:
    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmsmart.py:311", _fw_err)
        if self in OPEN:
            OPEN.remove(self)
        Gui.Control.closeDialog()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def reject(self):
        self._close()
        return True

    def removeSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def setPreselection(self, *a):
        pass

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.asm.Document.Name:
            return
        obj = self.asm.Document.getObject(name)
        if obj is not None:
            QtCore.QTimer.singleShot(0, lambda: self.pick(obj))

    def _comp(self, obj):
        names = {c.Name for c in ac.components(self.asm)}
        if obj.Name in names:
            return obj
        for parent in obj.InListRecursive:
            if parent.Name in names:
                return parent
        return None


class MakeSmartPanel(_Panel):
    """Make Smart Component: Smart Component, Components and Features boxes."""

    def __init__(self, asm):
        self.asm = asm
        self.smart, self.comps, self.feats = None, [], []
        form = QtWidgets.QWidget()
        form.setObjectName("SWMakeSmartComponent")
        form.setWindowTitle("Smart Component")
        form.setProperty("swstyle_pm_title", "Smart Component")
        lay = QtWidgets.QVBoxLayout(form)
        for title, attr, h in (("Smart Component", "smart_box", 28), ("Components", "comp_box", 80),
                               ("Features", "feat_box", 80)):
            box = QtWidgets.QGroupBox(title, form)
            bl = QtWidgets.QVBoxLayout(box)
            w = _list("SW" + title.replace(" ", ""), box, h)
            setattr(self, attr, w)
            bl.addWidget(w)
            lay.addWidget(box)
        self.sizes = []
        abox = QtWidgets.QGroupBox("Auto size", form)
        al = QtWidgets.QVBoxLayout(abox)
        self.auto = QtWidgets.QCheckBox("Auto size", abox)
        self.auto.setObjectName("SWSmartAutoSize")
        self.auto.setToolTip("Insert Smart Features picks the configuration by the size of the reference")
        al.addWidget(self.auto)
        self.configure = QtWidgets.QPushButton("Configure Component...", abox)
        self.configure.setObjectName("SWSmartConfigure")
        self.configure.clicked.connect(lambda *_: self.configure_sizes())
        al.addWidget(self.configure)
        self.auto.toggled.connect(lambda *_: self._sync_auto())
        lay.addWidget(abox)
        self.info = QtWidgets.QLabel("Select the component to make smart, then its components and features.", form)
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        lay.addStretch(1)
        self.form = form
        for s in Gui.Selection.getSelectionEx(asm.Document.Name):
            self.pick(s.Object)
        Gui.Selection.addObserver(self)
        OPEN.append(self)
        self._sync_auto()

    def pick(self, obj):
        if af.is_feature(obj):
            if obj not in self.feats:
                self.feats.append(obj)
        else:
            comp = self._comp(obj)
            if comp is None:
                return
            if self.smart is None:
                self.smart = comp
            elif comp.Name != self.smart.Name and all(c.Name != comp.Name for c in self.comps):
                self.comps.append(comp)
        self._show()

    def _sync_auto(self):
        many = self.smart is not None and len(configurations_of(self.smart)) > 1
        self.auto.setEnabled(many)
        if not many:
            self.auto.setChecked(False)
        self.configure.setEnabled(many and self.auto.isChecked())

    def configure_sizes(self, run=True):
        """Configure Component: each configuration's Min and Max diameter."""
        dlg = ConfigureSizesDialog(configurations_of(self.smart) if self.smart else [], self.sizes)
        self.sizes_dialog = dlg
        if run and dlg.exec():
            self.sizes = dlg.sizes()
        return dlg

    def _show(self):
        self._sync_auto()
        self.smart_box.clear()
        if self.smart is not None:
            self.smart_box.addItem(self.smart.Label)
        self.comp_box.clear()
        self.comp_box.addItems([c.Label for c in self.comps])
        self.feat_box.clear()
        self.feat_box.addItems([f.Label for f in self.feats])

    def accept(self):
        if self.smart is None or not (self.comps or self.feats):
            return False
        self.result = make_smart(self.asm, self.smart, self.comps, self.feats,
                                 self.auto.isChecked(), self.sizes if self.auto.isChecked() else ())
        self._close()
        return True


class ConfigureSizesDialog(QtWidgets.QDialog):
    """Configure Component: a row per configuration with its Min and Max diameter (mm)."""

    def __init__(self, configs, sizes=(), parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWSmartConfigureSizes")
        self.setWindowTitle("Configure Component")
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(len(configs), 3, self)
        self.table.setObjectName("SWSmartSizesTable")
        self.table.setHorizontalHeaderLabels(["Configuration", "Min diameter (mm)", "Max diameter (mm)"])
        have = {c: (lo, hi) for c, lo, hi in sizes or ()}
        for i, c in enumerate(configs):
            it = QtWidgets.QTableWidgetItem(c)
            it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(i, 0, it)
            lo, hi = have.get(c, ("", ""))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem("" if lo == "" else "%g" % lo))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem("" if hi == "" else "%g" % hi))
        self.table.resizeColumnsToContents()
        lay.addWidget(self.table)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def set_row(self, config, lo, hi):
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0).text() == config:
                self.table.item(i, 1).setText("%g" % lo)
                self.table.item(i, 2).setText("%g" % hi)

    def sizes(self):
        out = []
        for i in range(self.table.rowCount()):
            try:
                lo, hi = float(self.table.item(i, 1).text()), float(self.table.item(i, 2).text())
            except (ValueError, AttributeError):
                continue
            out.append((self.table.item(i, 0).text(), min(lo, hi), max(lo, hi)))
        return out


class SmartFeaturesPanel(_Panel):
    """Insert > Smart Features: the smart component's Components and Features, checked."""

    def __init__(self, asm):
        self.asm = asm
        self.smart = None
        form = QtWidgets.QWidget()
        form.setObjectName("SWSmartFeatures")
        form.setWindowTitle("Smart Features")
        form.setProperty("swstyle_pm_title", "Smart Features")
        lay = QtWidgets.QVBoxLayout(form)
        box = QtWidgets.QGroupBox("Smart Component", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.smart_box = _list("SWSmartComponent", box, 28)
        bl.addWidget(self.smart_box)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Components", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.comp_box = _list("SWSmartComponents", box, 90)
        bl.addWidget(self.comp_box)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Features", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.feat_box = _list("SWSmartFeatureList", box, 90)
        bl.addWidget(self.feat_box)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Auto size", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.auto = QtWidgets.QCheckBox("Auto size", box)
        self.auto.setObjectName("SWSmartFeaturesAutoSize")
        bl.addWidget(self.auto)
        bl.addWidget(QtWidgets.QLabel("Reference:", box))
        self.ref_box = _list("SWSmartReference", box, 28)
        bl.addWidget(self.ref_box)
        self.size_label = QtWidgets.QLabel("", box)
        self.size_label.setObjectName("SWSmartSizeFound")
        bl.addWidget(self.size_label)
        self.auto.toggled.connect(lambda *_: self._sync_auto())
        lay.addWidget(box)
        self.diameter = None
        lay.addStretch(1)
        self.form = form
        for s in Gui.Selection.getSelectionEx(asm.Document.Name):
            self.pick(s.Object)
        Gui.Selection.addObserver(self)
        OPEN.append(self)
        self._sync_auto()

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.asm.Document.Name:
            return
        obj = self.asm.Document.getObject(name)
        if obj is not None:
            from . import safe_later as _sl; _sl.later(0, lambda: self.pick(obj, sub), self, "auto")

    def _sync_auto(self):
        on = self.smart is not None and bool(sizes_of(self.smart))
        self.auto.setEnabled(on)
        if not on:
            self.auto.setChecked(False)
        self.ref_box.setEnabled(on and self.auto.isChecked())
        self._sync_size()

    def _sync_size(self):
        if self.smart is None or not self.auto.isChecked() or self.diameter is None:
            self.size_label.setText("")
            return
        c = size_for(sizes_of(self.smart), self.diameter)
        self.size_label.setText(("Configuration: %s" % c) if c else "No configuration fits %.2f mm" % self.diameter)

    def pick_reference(self, obj, sub):
        """Auto size's Reference: a cylindrical face or circular edge of another component."""
        ref = ac.reference(self.asm, obj, sub) if sub else None
        shape = ac.element(*ref) if ref is not None else None
        d = diameter_of(shape) if shape is not None else None
        if d is None:
            return False
        self.diameter = d
        self.ref_box.clear()
        self.ref_box.addItem("%s@%s" % (sub.split(".")[-1], ref[0].Label))
        self._sync_size()
        return True

    def pick(self, obj, sub=None):
        if self.smart is not None and self.auto.isChecked() and sub:
            comp = self._comp(obj) if obj is not None else None
            if self.pick_reference(obj, sub):
                return
        comp = self._comp(obj)
        if comp is None or not is_smart(comp):
            return
        self.smart = comp
        self.smart_box.clear()
        self.smart_box.addItem(comp.Label)
        for box, rows, key in ((self.comp_box, components_of(comp), "label"), (self.feat_box, features_of(comp), "name")):
            box.clear()
            for row in rows:
                it = QtWidgets.QListWidgetItem(row.get(key, "?"))
                it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Checked)
                box.addItem(it)
        self._sync_auto()

    def _checked(self, box, rows):
        return [r for i, r in enumerate(rows) if i < box.count() and box.item(i).checkState() == QtCore.Qt.Checked]

    def accept(self):
        if self.smart is None:
            return False
        doc = self.asm.Document
        doc.openTransaction("Smart Features")
        try:
            self.result = insert_smart_features(self.asm, self.smart,
                                                self._checked(self.comp_box, components_of(self.smart)),
                                                self._checked(self.feat_box, features_of(self.smart)),
                                                self.diameter if self.auto.isChecked() else None)
        finally:
            doc.commitTransaction()
        self._close()
        return True


def start_make_smart(asm):
    if Gui.Control.activeDialog():
        return None
    p = MakeSmartPanel(asm)
    Gui.Control.showDialog(p)
    return p


def start_smart_features(asm):
    if Gui.Control.activeDialog():
        return None
    _install_tool()
    p = SmartFeaturesPanel(asm)
    Gui.Control.showDialog(p)
    return p


def install():
    """On load: smart cuts in files opened later rebuild (the tool hook)."""
    _install_tool()
