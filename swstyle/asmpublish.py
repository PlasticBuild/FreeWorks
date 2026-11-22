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
from PySide import QtCore, QtWidgets

from . import asmcore as ac

FROM_PROP = "FwPublishedFrom"          # "TopDocName/ComponentName" on a published envelope
ASSET_TYPE = "SWStyle::PublishedAsset"
OPEN = []


# ---------------------------------------------------------------------- envelopes
def subassemblies(asm):
    return [c for c in ac.components(asm) if ac.is_subassembly(c)]


def _frame(sublink):
    from . import asmexplode as ax
    return ax.gplacement(sublink)


def touching_box(asm, sublink, comps=None):
    """Top-level components whose boxes touch the target subassembly's box."""
    box = sublink.Shape.BoundBox if not sublink.Shape.isNull() else None
    if box is None or not box.isValid():
        return []
    out = []
    for c in comps if comps is not None else ac.components(asm):
        if c is sublink or ac.is_subassembly(c):
            continue
        b = c.Shape.BoundBox
        if b.isValid() and b.intersect(box):
            out.append(c)
    return out


def published(src):
    """The published envelopes inside a subassembly file's assembly."""
    return [c for c in ac.components(src) if getattr(c, FROM_PROP, "")]


def publish(asm, comps, sublink):
    """Copies comps into sublink's assembly as envelopes. Returns the new components there."""
    from . import asminsert, asmreorg
    src = getattr(sublink, "LinkedObject", None)
    comps = [c for c in comps if c in ac.components(asm) and c is not sublink and not ac.is_subassembly(c)]
    if src is None or not comps:
        return []
    inv = _frame(sublink).inverse()
    out = []
    done = {getattr(c, FROM_PROP, "") for c in published(src)}
    for c in comps:
        key = "%s/%s" % (asm.Document.Name, c.Name)
        if key in done:
            continue
        target = c.LinkedObject if c.TypeId == "App::Link" else c
        link = ac.insert(src, target, inv.multiply(c.Placement))
        link.Placement = inv.multiply(c.Placement)
        link.addProperty("App::PropertyString", FROM_PROP, "FreeCAD", "Published by Envelope Publisher from")
        setattr(link, FROM_PROP, key)
        link.setEditorMode(FROM_PROP, 1)
        asminsert.make_envelope(link)
        if link not in ac.grounded(src):
            ac.fix(src, link)          # an envelope holds the place of its source
        out.append(link)
    src.Document.recompute()
    if src.Document.FileName:
        src.Document.save()
    asmreorg._resync(sublink)
    asm.Document.recompute()
    return out


def update(asm, sublink):
    """Update published envelopes: each copy moves to where its source is now. Returns how many moved."""
    from . import asmreorg
    src = getattr(sublink, "LinkedObject", None)
    if src is None:
        return 0
    inv = _frame(sublink).inverse()
    moved = 0
    for env in published(src):
        doc_name, _sep, name = getattr(env, FROM_PROP).partition("/")
        if doc_name != asm.Document.Name:
            continue
        source = asm.Document.getObject(name)
        if source is None:
            continue
        want = inv.multiply(source.Placement)
        if not want.isSame(env.Placement, 1e-9):
            env.Placement = want
            moved += 1
    if moved:
        src.Document.recompute()
        if src.Document.FileName:
            src.Document.save()
        asmreorg._resync(sublink)
        asm.Document.recompute()
    return moved


class _Picks(QtWidgets.QListWidget):
    pass


class EnvelopePublisherPanel:
    ""

    def __init__(self, asm):
        self.asm, self.doc = asm, asm.Document
        self.comps = []
        form = QtWidgets.QWidget()
        form.setObjectName("SWEnvelopePublisher")
        form.setWindowTitle("Envelope Publisher")
        form.setProperty("swstyle_pm_title", "Envelope Publisher")
        lay = QtWidgets.QVBoxLayout(form)
        box = QtWidgets.QGroupBox("Target Assembly", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.target = QtWidgets.QComboBox(box)
        self.target.setObjectName("SWEnvelopeTarget")
        for s in subassemblies(asm):
            self.target.addItem(s.Label, s.Name)
        bl.addWidget(self.target)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Envelope Components", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.list = _Picks(box)
        self.list.setObjectName("SWEnvelopeComponents")
        self.list.setMaximumHeight(90)
        bl.addWidget(self.list)
        self.by_box = QtWidgets.QPushButton("Select by Box", box)
        self.by_box.setObjectName("SWEnvelopeByBox")
        self.by_box.setToolTip("Adds the components that touch the target assembly's box")
        bl.addWidget(self.by_box)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Options", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.update_box = QtWidgets.QCheckBox("Update published envelopes", box)
        self.update_box.setObjectName("SWEnvelopeUpdate")
        self.update_box.setChecked(True)
        bl.addWidget(self.update_box)
        lay.addWidget(box)
        self.note = QtWidgets.QLabel("", form)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.form = form
        self.by_box.clicked.connect(self.select_by_box)
        for sel in Gui.Selection.getSelectionEx(self.doc.Name):
            for sub in (sel.SubElementNames or ("",)):
                self._add(sel.Object, sub)
        self._show()
        Gui.Selection.addObserver(self)
        OPEN.append(self)

    def sublink(self):
        name = self.target.currentData()
        return self.doc.getObject(name) if name else None

    def _comp(self, obj, sub):
        """The top-level component a pick belongs to."""
        if obj is self.asm and sub:
            name = sub.split(".")[0]
            return self.doc.getObject(name)
        return obj if obj in ac.components(self.asm) else None

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        if obj is not None:
            QtCore.QTimer.singleShot(0, lambda: (self._add(obj, sub), self._show()))

    def _add(self, obj, sub):
        c = self._comp(obj, sub)
        if c is None or ac.is_subassembly(c):
            return
        if c in self.comps:
            self.comps.remove(c)        # a second pick takes it out
        else:
            self.comps.append(c)

    def select_by_box(self):
        s = self.sublink()
        if s is None:
            return
        for c in touching_box(self.asm, s):
            if c not in self.comps:
                self.comps.append(c)
        self._show()

    def _show(self):
        self.list.clear()
        for c in self.comps:
            self.list.addItem(c.Label)
        if self.target.count() == 0:
            self.note.setText("The assembly has no subassembly to publish to.")
        else:
            self.note.setText("")

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmpublish.py:236", _fw_err)
        if self in OPEN:
            OPEN.remove(self)
        Gui.Control.closeDialog()

    def accept(self):
        s = self.sublink()
        if s is None:
            return False
        self.doc.openTransaction("Envelope Publisher")
        try:
            if self.update_box.isChecked():
                update(self.asm, s)
            self.result = publish(self.asm, self.comps, s)
        finally:
            self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self._close()
        return True


def start_envelope_publisher(asm):
    if Gui.Control.activeDialog():
        return None
    p = EnvelopePublisherPanel(asm)
    Gui.Control.showDialog(p)
    return p


# ---------------------------------------------------------------------- assets
class PublishedAsset:
    Type = ASSET_TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        props = obj.PropertiesList
        for name, kind, tip in (("AssetName", "App::PropertyString", "The asset's name"),
                                ("Mounting", "App::PropertyStringList", "Mate references the asset mounts with"),
                                ("ConnectionPoints", "App::PropertyStringList", "Object:Element of each connection point"),
                                ("PointNames", "App::PropertyStringList", "Name of each connection point")):
            if name not in props:
                obj.addProperty(kind, name, "Asset", tip)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class PublishedAssetView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        from pivy import coin
        vobj.addDisplayMode(coin.SoGroup(), "Default")

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return ":/icons/Std_Placement.svg"

    def doubleClicked(self, vobj):
        start_asset_publisher(vobj.Object.Document, vobj.Object)
        return True

    def setupContextMenu(self, vobj, menu):
        menu.addAction("Edit Feature").triggered.connect(lambda: start_asset_publisher(vobj.Object.Document, vobj.Object))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def assets(doc):
    return [o for o in (doc.Objects if doc is not None else [])
            if getattr(getattr(o, "Proxy", None), "Type", None) == ASSET_TYPE]


def point_of(doc, text):
    """The global point of a connection point 'Object:Element'."""
    name, _sep, sub = text.partition(":")
    obj = doc.getObject(name)
    if obj is None:
        return None
    try:
        if sub:
            s = obj.Shape.getElement(sub)
            return s.Vertexes[0].Point if s.ShapeType == "Vertex" else s.CenterOfMass
        p = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
        return p.Base
    except Exception:
        return None


def publish_asset(doc, name, mounting, points, feature=None):
    """points: [(obj, sub, point name)]. Returns the Published Asset feature."""
    if feature is None:
        feature = doc.addObject("App::FeaturePython", "PublishedAsset")
        PublishedAsset(feature)
        if App.GuiUp:
            PublishedAssetView(feature.ViewObject)
        feature.Label = "Published Asset"
    feature.AssetName = name
    feature.Mounting = list(mounting)
    feature.ConnectionPoints = ["%s:%s" % (o.Name, s) for o, s, _n in points]
    feature.PointNames = [n for _o, _s, n in points]
    asm = ac.assembly_of(doc)
    if asm is not None and feature not in asm.Group:
        try:
            asm.addObject(feature)
        except Exception as _fw_err:
            _fw_log("asmpublish.py:369", _fw_err)
            from . import fwtell
            fwtell.tell("The asset was published, but it could not be added to the assembly.", _fw_err)
    doc.recompute()
    return feature


class AssetPublisherPanel:
    ""


    def __init__(self, doc, feature=None):
        from . import asmrefgeom
        self.doc, self.feature = doc, feature
        self.points = []            # (obj, sub, name)
        if feature is not None:
            for text, n in zip(feature.ConnectionPoints, feature.PointNames):
                o = doc.getObject(text.partition(":")[0])
                if o is not None:
                    self.points.append((o, text.partition(":")[2], n))
        form = QtWidgets.QWidget()
        form.setObjectName("SWAssetPublisher")
        form.setWindowTitle("Asset Publisher")
        form.setProperty("swstyle_pm_title", "Asset Publisher")
        lay = QtWidgets.QVBoxLayout(form)
        box = QtWidgets.QGroupBox("Asset", form)
        bl = QtWidgets.QFormLayout(box)
        self.name = QtWidgets.QLineEdit(feature.AssetName if feature is not None else doc.Label, box)
        self.name.setObjectName("SWAssetName")
        bl.addRow("Name:", self.name)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Geometric Mounting", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.mounting = QtWidgets.QListWidget(box)
        self.mounting.setObjectName("SWAssetMounting")
        self.mounting.setMaximumHeight(80)
        now = list(feature.Mounting) if feature is not None else None
        for ref in asmrefgeom.mate_references(doc):
            it = QtWidgets.QListWidgetItem(ref.RefName)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if now is None or ref.RefName in now else QtCore.Qt.Unchecked)
            self.mounting.addItem(it)
        bl.addWidget(self.mounting)
        self.add_ref = QtWidgets.QPushButton("Add Mate Reference...", box)
        self.add_ref.setObjectName("SWAssetAddMateRef")
        bl.addWidget(self.add_ref)
        lay.addWidget(box)
        box = QtWidgets.QGroupBox("Connection Points", form)
        bl = QtWidgets.QVBoxLayout(box)
        self.plist = QtWidgets.QListWidget(box)
        self.plist.setObjectName("SWAssetPoints")
        self.plist.setMaximumHeight(90)
        bl.addWidget(self.plist)
        lay.addWidget(box)
        self.note = QtWidgets.QLabel("Pick vertices, points or coordinate systems for the connection points.", form)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.form = form
        self.add_ref.clicked.connect(self._mate_reference)
        for sel in Gui.Selection.getSelectionEx(doc.Name):
            for sub in (sel.SubElementNames or ("",)):
                self._add(sel.Object, sub)
        self._show()
        Gui.Selection.addObserver(self)
        OPEN.append(self)

    def _mate_reference(self):
        ""

        self.note.setText("Make the mate reference (Insert > Reference Geometry > Mate Reference), "
                          "then open Asset Publisher again.")
        self.reject()
        from . import asmrefgeom
        QtCore.QTimer.singleShot(0, lambda: asmrefgeom.edit_mate_reference(doc=self.doc))

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        if obj is not None:
            QtCore.QTimer.singleShot(0, lambda: (self._add(obj, sub), self._show()))

    def _add(self, obj, sub):
        from . import refplane
        obj, sub = refplane.resolve(obj, sub or "")
        ok = False
        if sub:
            try:
                ok = obj.Shape.getElement(sub).ShapeType == "Vertex"
            except Exception:
                ok = False
        else:
            ok = obj.TypeId in ("Part::DatumPoint", "PartDesign::Point", "Part::LocalCoordinateSystem",
                                "PartDesign::CoordinateSystem", "App::Point")
        if not ok:
            return
        for i, (o, s, _n) in enumerate(self.points):
            if o == obj and s == sub:
                del self.points[i]
                return
        self.points.append((obj, sub, "CPoint%d" % (len(self.points) + 1)))

    def _show(self):
        self.plist.clear()
        for o, s, n in self.points:
            self.plist.addItem("%s: %s" % (n, "%s@%s" % (s, o.Label) if s else o.Label))

    def mounting_names(self):
        return [self.mounting.item(i).text() for i in range(self.mounting.count())
                if self.mounting.item(i).checkState() == QtCore.Qt.Checked]

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmpublish.py:486", _fw_err)
        if self in OPEN:
            OPEN.remove(self)
        Gui.Control.closeDialog()

    def accept(self):
        if not self.points and not self.mounting_names():
            self.note.setText("Pick a connection point or keep a mate reference for the mounting.")
            return False
        self.doc.openTransaction("Asset Publisher")
        try:
            self.feature = publish_asset(self.doc, self.name.text().strip() or self.doc.Label,
                                         self.mounting_names(), self.points, self.feature)
        finally:
            self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self._close()
        return True


def start_asset_publisher(doc=None, feature=None):
    doc = doc or App.ActiveDocument
    if doc is None or Gui.Control.activeDialog():
        return None
    if feature is None and assets(doc):
        feature = assets(doc)[0]        # one published asset per model; reopening edits it
    p = AssetPublisherPanel(doc, feature)
    Gui.Control.showDialog(p)
    return p
