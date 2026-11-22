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
from PySide import QtWidgets

FOLDER = "Cut list"
ITEM = "Sheet"
GROUP = "Cut List"
DENSITY = 1e-6
PROPS = ("Bounding Box Length", "Bounding Box Width", "Sheet Metal Thickness", "Bend Radius", "Bends",
         "Cutting Length-Outer", "Cutting Length-Inner", "Cut Outs", "Surface Treatment", "Bend Allowance",
         "Material", "Mass")
# property name on the item for each
NAMES = {p: p.replace(" ", "").replace("-", "") for p in PROPS}


def _kind(obj):
    return type(getattr(obj, "Proxy", None)).__name__


def folder(doc, create=False):
    found = next((o for o in doc.Objects if _kind(o) == "SMCutListFolder"), None)
    if found is None and create:
        found = doc.addObject("App::FeaturePython", "SMCutList")
        SMCutListFolder(found)
        if App.GuiUp:
            ViewProviderSMCutList(found.ViewObject)
        found.Label = "%s(0)" % FOLDER
    return found


class SMCutListFolder:
    def __init__(self, obj):
        obj.addProperty("App::PropertyLinkList", "Items", GROUP, "Cut list items")
        obj.setEditorMode("Items", 2)
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class SMCutListItem:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLink", "Body", GROUP, "The sheet metal body")
        for p in PROPS:
            kind = "App::PropertyString" if p in ("Surface Treatment", "Bend Allowance", "Material") else (
                "App::PropertyInteger" if p in ("Bends", "Cut Outs") else "App::PropertyFloat")
            add(kind, NAMES[p], GROUP, p)
            if p != "Surface Treatment":
                obj.setEditorMode(NAMES[p], 1)
        obj.setEditorMode("Body", 2)
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderSMCutList:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        try:
            from . import wemember
            wemember._empty_mode(vobj)      # look-audit smwe-1120: counts as shown, so the tree writes it black
        except Exception as _fw_err:
            _fw_log("smcutlist.py:attach", _fw_err)

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return ":/icons/folder.svg" if _kind(self.Object) == "SMCutListFolder" else ":/icons/Tree_Part.svg"

    def claimChildren(self):
        return list(getattr(self.Object, "Items", []))

    def setupContextMenu(self, vobj, menu):
        doc = vobj.Object.Document
        a = menu.addAction("Update")
        a.triggered.connect(lambda: update(doc))
        b = menu.addAction("Properties...")
        b.triggered.connect(lambda: show_properties(doc))

    def doubleClicked(self, vobj):
        show_properties(vobj.Object.Document)
        return True

    def onDelete(self, vobj, subelements):
        return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


# ---------------------------------------------------------------- the values
def _flat(body):
    """The Flat-Pattern of body, computed (the part stays as it is shown)."""
    from . import smflatten
    fp = smflatten.flat_pattern(body)
    if fp is None:
        return None
    if not fp.SWFlattened or fp.Shape.isNull():
        was = fp.SWFlattened
        fp.SWFlattened = True
        try:
            fp.recompute()
        finally:
            fp.SWFlattened = was
            fp.purgeTouched()
    return fp if not fp.Shape.isNull() else None


def _allowance(root):
    kind = getattr(root, "SWBendAllowanceType", "K-Factor")
    if kind == "K-Factor":
        return "K-Factor %g" % float(getattr(root, "SWKFactor", 0.5))
    if kind == "Bend Allowance":
        return "Bend Allowance %g" % float(root.SWBendAllowance)
    if kind == "Bend Deduction":
        return "Bend Deduction %g" % float(root.SWBendDeduction)
    table = root.Document.getObject(root.SWBendTable) if getattr(root, "SWBendTable", "") else None
    return "%s %s" % (kind, table.Label if table is not None else "")


def _density(body):
    for o in (body,):
        mat = getattr(o, "ShapeMaterial", None)
        try:
            d = mat.getPhysicalValue("Density")
            v = float(App.Units.Quantity(d).getValueAs("kg/mm^3"))
            if v > 0 and getattr(mat, "Name", "").lower() != "default":
                return v
        except Exception as _fw_err:
            _fw_log("smcutlist.py:171", _fw_err)
    return DENSITY


def values(body):
    ""
    from . import smflatten, smgauge, smunfold
    root = smflatten.root(body)
    fp = _flat(body)
    if root is None or fp is None:
        return None
    flat = fp.Shape
    box = fp.BoundingBox.Shape if fp.BoundingBox is not None else None
    lengths = sorted((e.Length for e in box.Edges), reverse=True) if box is not None and not box.isNull() else [0, 0]
    t = float(getattr(root, "Thickness", 0) or 0)
    # the flat's big face on the fixed side: its outline is cut outside, its holes inside
    faces = sorted((f for f in flat.Faces if f.Surface.TypeId == "Part::GeomPlane"), key=lambda f: -f.Area)
    outer = inner = 0.0
    cutouts = 0
    if faces:
        f = faces[0]
        outer = f.OuterWire.Length
        holes = [w for w in f.Wires if not w.isSame(f.OuterWire)]
        inner = sum(w.Length for w in holes)
        cutouts = len(holes)
    tip = body.Tip
    try:
        bends = len(smunfold.bends_of(tip.Shape))
    except Exception:
        bends = 0
    mat = smgauge.material_of(root)
    return {
        "Bounding Box Length": round(lengths[0], 4), "Bounding Box Width": round(lengths[-1] if len(lengths) > 1 else 0, 4),
        "Sheet Metal Thickness": t, "Bend Radius": float(getattr(root, "Radius", 0) or 0), "Bends": bends,
        "Cutting Length-Outer": round(outer, 4), "Cutting Length-Inner": round(inner, 4), "Cut Outs": cutouts,
        "Bend Allowance": _allowance(root), "Material": mat,
        "Mass": round(tip.Shape.Volume * _density(body), 6),
    }


def sheet_bodies(doc):
    from . import smflatten
    return [b for b in doc.Objects if b.TypeId == "PartDesign::Body" and smflatten.root(b) is not None]


def update(doc, compute=True):
    bodies = sheet_bodies(doc)
    box = folder(doc, create=bool(bodies))
    if box is None:
        return None
    items = list(box.Items)
    while len(items) < len(bodies):
        item = doc.addObject("App::FeaturePython", "SMCutListItem")
        SMCutListItem(item)
        if App.GuiUp:
            ViewProviderSMCutList(item.ViewObject)
        items.append(item)
    for extra in items[len(bodies):]:
        try:
            doc.removeObject(extra.Name)
        except Exception as _fw_err:
            _fw_log("smcutlist.py:232", _fw_err)
    items = items[:len(bodies)]
    for n, (item, body) in enumerate(zip(items, bodies), 1):
        item.Body = body
        vals = (values(body) if compute else None) or {}
        for p, v in vals.items():
            setattr(item, NAMES[p], v)
        item.Label = "%s<%d>" % (ITEM, n)
        item.purgeTouched()
    box.Items = items
    box.Label = "%s(%d)" % (FOLDER, len(items))
    box.purgeTouched()
    return box


# ---------------------------------------------------------------- Cut-List Properties
class PropertiesDialog(QtWidgets.QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.setObjectName("SWSMCutListDialog")
        self.setWindowTitle("Cut-List Properties")
        self.resize(560, 420)
        lay = QtWidgets.QVBoxLayout(self)
        self.items = QtWidgets.QListWidget()
        self.items.setObjectName("SWSMCutListItems")
        self.items.setMaximumHeight(70)
        lay.addWidget(self.items)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setObjectName("SWSMCutListTable")
        self.table.setHorizontalHeaderLabels(["Property Name", "Value / Text Expression"])
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        upd = QtWidgets.QPushButton("Update")
        upd.setObjectName("SWSMCutListUpdate")
        ok = QtWidgets.QPushButton("OK")
        ok.setObjectName("SWSMCutListOK")
        cancel = QtWidgets.QPushButton("Cancel")
        row.addWidget(upd)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)
        upd.clicked.connect(self._update)
        ok.clicked.connect(self._ok)
        cancel.clicked.connect(self.reject)
        self.items.currentRowChanged.connect(self._fill)
        self._list()

    def _box(self):
        return folder(self.doc)

    def _list(self):
        self.items.clear()
        box = self._box()
        for item in (box.Items if box is not None else []):
            self.items.addItem(item.Label)
        if self.items.count():
            self.items.setCurrentRow(0)

    def item(self):
        box = self._box()
        r = self.items.currentRow()
        return box.Items[r] if box is not None and 0 <= r < len(box.Items) else None

    def _fill(self, *args):
        item = self.item()
        self.table.setRowCount(len(PROPS))
        for r, p in enumerate(PROPS):
            v = getattr(item, NAMES[p], "") if item is not None else ""
            if isinstance(v, float):
                v = "%g" % v
            name = QtWidgets.QTableWidgetItem(p)
            name.setFlags(name.flags() & ~QtCore_editable())
            val = QtWidgets.QTableWidgetItem(str(v))
            if p != "Surface Treatment":
                val.setFlags(val.flags() & ~QtCore_editable())
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, val)
        self.table.resizeColumnToContents(0)

    def _save(self):
        item = self.item()
        if item is not None:
            r = PROPS.index("Surface Treatment")
            cell = self.table.item(r, 1)
            item.SurfaceTreatment = cell.text() if cell is not None else ""

    def _update(self):
        self._save()
        update(self.doc)
        self._fill()

    def _ok(self):
        self._save()
        self.accept()


def QtCore_editable():
    from PySide import QtCore
    return QtCore.Qt.ItemIsEditable


_dialogs = []


def show_properties(doc):
    update(doc)
    dlg = PropertiesDialog(doc)
    _dialogs[:] = [dlg]
    dlg.show()
    return dlg


def later(doc_name):
    """Update after the current recompute (the flat pattern has just been made)."""
    from PySide import QtCore

    def go():
        try:
            doc = App.getDocument(doc_name)
        except Exception:
            return
        if folder(doc) is not None:
            update(doc)
    QtCore.QTimer.singleShot(0, go)
