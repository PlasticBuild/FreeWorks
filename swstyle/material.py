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

import os
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import icons

NAME = "Material"
NOT_SPECIFIED = "Material <not specified>"
DEFAULT_DENSITY = 1000.0   # kg/m^3


FOLDERS = [
    ("Steel", ("Standard/Metal/Steel",)),
    ("Iron", ("Standard/Metal/Iron",)),
    ("Aluminium Alloys", ("Standard/Metal/Aluminum",)),
    ("Copper Alloys", ("Standard/Metal/Copper",)),
    ("Titanium Alloys", ("Standard/Metal/Titanium",)),
    ("Other Alloys", ("Standard/Metal/Alloys",)),
    ("Plastics", ("Standard/Thermoplast",)),
    ("Woods", ("Standard/Wood",)),
    ("Other Non-metals", ("Standard/Glass", "Standard/Carbon", "Standard/Aggregate", "Standard")),
]

COMMON = [
    ("Steel", "Plain Carbon Steel", 7800), ("Steel", "AISI 1020", 7900), ("Steel", "AISI 304", 8000),
    ("Steel", "Alloy Steel", 7700),
    ("Iron", "Gray Cast Iron", 7200), ("Iron", "Malleable Cast Iron", 7300),
    ("Aluminium Alloys", "1060 Alloy", 2700), ("Aluminium Alloys", "6061 Alloy", 2700),
    ("Aluminium Alloys", "6063-T6", 2700), ("Aluminium Alloys", "7075-T6", 2810),
    ("Steel", "Cast Alloy Steel", 7300),
    ("Copper Alloys", "Brass", 8500), ("Copper Alloys", "Copper", 8900),
    ("Other Alloys", "Nickel", 8900),   # extapps119: 8900 kg/m^3, the published density (it read 8800)
    ("Titanium Alloys", "Ti-6Al-4V", 4430),
    ("Plastics", "ABS", 1020), ("Plastics", "ABS PC", 1070), ("Plastics", "Acrylic (Medium-high impact)", 1200),
    ("Plastics", "Nylon 6/10", 1400), ("Plastics", "PE High Density", 952), ("Plastics", "PP Copolymer", 890),
    ("Plastics", "PLA", 1240), ("Plastics", "PETG", 1270), ("Plastics", "PBT General Purpose", 1300),
    ("Other Non-metals", "Rubber", 1000),
    ("Woods", "Balsa", 160), ("Woods", "Pine", 500), ("Woods", "Oak", 700),
]


def row(doc):
    if doc is None:
        return None
    for obj in doc.Objects:
        if getattr(getattr(obj, "Proxy", None), "Type", None) == "SWStyle::Material":
            return obj
    return None


def known_density(name):
    ""
    for _folder, n, value in COMMON:
        if n.lower() == (name or "").lower():
            return float(value)
    return None


def library_density(mat):
    """kg/m^3 from a FreeCAD material's physical properties, or None (appearance-only materials)."""
    try:
        text = mat.PhysicalProperties.get("Density")
        return float(App.Units.Quantity(text).getValueAs("kg/m^3").Value) if text else None
    except Exception:
        return None


def current(doc):
    ""



    obj = row(doc)
    if obj is not None and obj.MaterialName:
        return float(obj.Density), obj.MaterialName
    for body in (doc.Objects if doc is not None else []):
        if body.TypeId != "PartDesign::Body":
            continue
        mat = getattr(body, "ShapeMaterial", None)
        name = getattr(mat, "Name", "") if mat is not None else ""
        if not name or name.lower() == "default":
            continue
        value = library_density(mat) or known_density(name.replace("-Generic", ""))
        if value:
            return value, name
    return None, None


def part_density(doc):
    """kg/m^3 typed for a part with no material (Document Properties > Material Properties > Density), or None."""
    obj = row(doc) if doc is not None else None
    if obj is not None and not obj.MaterialName and float(getattr(obj, "Density", 0.0) or 0.0) > 0:
        return float(obj.Density)
    return None


def set_density(doc, value):
    """Document Properties > Material Properties > Density (kg/m^3), in one Undo step: the part's density with no
    material; with a material, that material's density in this part."""
    value = float(value)
    obj = row(doc)
    if obj is not None and abs(float(obj.Density or 0.0) - value) < 1e-12:
        return
    doc.openTransaction("Density")
    try:
        obj = obj or make(doc)
        obj.Density = value
    finally:
        doc.commitTransaction()
    doc.recompute()


def density(doc):
    value, _ = current(doc)
    return value or part_density(doc) or DEFAULT_DENSITY


def _library():
    """FreeCAD's materials as (folder, name, density, uuid), sorted by folder and name."""
    out = []
    try:
        import Materials
        materials = Materials.MaterialManager().Materials
    except Exception:
        return out
    for uuid, mat in materials.items():
        folder = None
        for title, dirs in FOLDERS:
            if mat.Directory in dirs:
                folder = title
                break
        text = mat.PhysicalProperties.get("Density") if folder else None
        if not text:
            continue
        try:
            value = App.Units.Quantity(text).getValueAs("kg/m^3").Value
        except Exception:
            continue
        out.append((folder, mat.Name, float(value), uuid))
    return sorted(out, key=lambda m: (m[0], m[1].lower()))


def assign(doc, name, value, uuid=""):
    """Sets the Material row (no transaction of its own): the tree row then reads the name and
    Mass Properties uses the density."""
    obj = row(doc) or make(doc)
    obj.MaterialName = name
    obj.Density = float(value) if name else 0.0
    obj.MaterialUUID = uuid if name else ""
    _to_bodies(doc, obj)
    _into_configuration(doc, name)
    return obj


def apply(doc, name, value, uuid=""):
    """Gives the part a material ("" clears it), in one Undo step."""
    doc.openTransaction("Edit Material")
    try:
        assign(doc, name, value, uuid)
    finally:
        doc.commitTransaction()
    doc.recompute()


def _into_configuration(doc, name):
    ""


    try:
        from . import configmanager as cm, configs, configtable as ct
        t = cm.table(doc)
        if t is not None and configs.column_of(t, ct.MATERIAL) is not None:
            if (configs.cell_value(t, ct.MATERIAL, t.active()) or "").strip() != (name or ""):
                configs.set_cell(t, ct.MATERIAL, name or "", [t.active()])
    except Exception as _fw_err:
        _fw_log("material.py:configuration", _fw_err)


DEFAULT_UUID = "7f9fd73b-50c9-41d8-b7b2-575a030c1eeb"     # FreeCAD's own "Default" material (a new body's)


def _to_bodies(doc, obj):
    mat = None
    # no material (<not specified>): the bodies go back to FreeCAD's Default material, so nothing reads the old one
    uuid = obj.MaterialUUID or ("" if obj.MaterialName else DEFAULT_UUID)
    if uuid:
        try:
            import Materials
            mat = Materials.MaterialManager().getMaterial(uuid)
        except Exception:
            mat = None
    for body in doc.Objects:
        if body.TypeId != "PartDesign::Body" or "ShapeMaterial" not in body.PropertiesList:
            continue
        try:
            if mat is not None:
                body.ShapeMaterial = mat
        except Exception as _fw_err:
            _fw_log("material.py:181", _fw_err)


class MaterialRow:
    Type = "SWStyle::Material"

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        props = obj.PropertiesList
        if "MaterialName" not in props:
            obj.addProperty("App::PropertyString", "MaterialName", "Material", "The part's material, empty when not specified")
        if "Density" not in props:
            obj.addProperty("App::PropertyFloat", "Density", "Material", "Density in kg/m^3")
        if "MaterialUUID" not in props:
            obj.addProperty("App::PropertyString", "MaterialUUID", "Material", "FreeCAD library material, if any")
        self.label(obj)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def onChanged(self, obj, prop):
        if prop == "MaterialName":
            self.label(obj)

    def label(self, obj):
        text = obj.MaterialName if "MaterialName" in obj.PropertiesList and obj.MaterialName else NOT_SPECIFIED
        if obj.Label != text:
            obj.Label = text

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


_icon_path = None


def _icon():
    global _icon_path
    if _icon_path and os.path.exists(_icon_path):
        return _icon_path
    icon = icons.family("TREE_MATERIAL_FOLDER")
    # tree-1119: 64 px, never 16 (a 16 px file is drawn half size on a 150-200 % Windows screen)
    pixmap = icon.pixmap(64, 64) if not icon.isNull() else None
    if pixmap is None or pixmap.isNull():
        pixmap = QtGui.QPixmap(64, 64)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.scale(4.0, 4.0)        # drawn on a 16 px grid
        painter.setPen(QtGui.QPen(QtGui.QColor("#5a6b7d"), 1))
        painter.setBrush(QtGui.QBrush(QtGui.QColor("#c9d3dd")))
        painter.drawRect(QtCore.QRectF(2.5, 4.5, 11, 9))
        painter.setBrush(QtGui.QBrush(QtGui.QColor("#e8b04a")))
        painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(2.5, 4.5), QtCore.QPointF(5.5, 2.5),
                                             QtCore.QPointF(13.5, 2.5), QtCore.QPointF(13.5, 4.5)]))
        painter.end()
    _icon_path = os.path.join(tempfile.gettempdir(), "swstyle-material-%d.png" % os.getpid())     # pkg321: per session
    pixmap.save(_icon_path)
    return _icon_path


class MaterialView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        # An empty display mode, so the tree shows the row in black, not greyed out as hidden.
        from pivy import coin
        vobj.addDisplayMode(coin.SoGroup(), "Default")

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return _icon()

    def setupContextMenu(self, vobj, menu):
        action = menu.addAction("Edit Material...")
        action.triggered.connect(lambda: edit(vobj.Object.Document))
        try:
            from . import materialdlg
            for name in materialdlg.favorites()[:10]:
                fav = menu.addAction(name)
                fav.triggered.connect(lambda checked=False, n=name: materialdlg.apply_favorite(vobj.Object.Document, n))
            if materialdlg.favorites():
                menu.addSeparator()
        except Exception as _fw_err:
            _fw_log("material.py:279", _fw_err)
        if vobj.Object.MaterialName:
            clear = menu.addAction("Remove Material")
            clear.triggered.connect(lambda: apply(vobj.Object.Document, "", 0))
        return True

    def doubleClicked(self, vobj):
        edit(vobj.Object.Document)
        return True

    def onDelete(self, vobj, subelements):
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(doc):
    obj = doc.addObject("App::FeaturePython", NAME)
    MaterialRow(obj)
    if App.GuiUp:
        MaterialView(obj.ViewObject)
        obj.ViewObject.Visibility = True
    return obj


class MaterialDialog(QtWidgets.QDialog):
    ""


    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.setWindowTitle("Material")
        self.resize(620, 460)
        layout = QtWidgets.QVBoxLayout(self)
        self.search = QtWidgets.QLineEdit(self)
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        middle = QtWidgets.QHBoxLayout()
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        middle.addWidget(self.tree, 3)
        side = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLabel("-")
        self.folder = QtWidgets.QLabel("-")
        self.density = QtWidgets.QLabel("-")
        side.addRow("Name:", self.name)
        side.addRow("Category:", self.folder)
        side.addRow("Mass density:", self.density)
        box = QtWidgets.QGroupBox("Properties", self)
        box.setLayout(side)
        middle.addWidget(box, 2)
        layout.addLayout(middle, 1)
        buttons = QtWidgets.QDialogButtonBox(self)
        self.apply_button = buttons.addButton("Apply", QtWidgets.QDialogButtonBox.ApplyRole)
        buttons.addButton(QtWidgets.QDialogButtonBox.Close)
        layout.addWidget(buttons)
        self.apply_button.clicked.connect(self._apply)
        buttons.rejected.connect(self.close)
        self.tree.currentItemChanged.connect(self._show)
        self.tree.itemDoubleClicked.connect(lambda item, column: self._apply())
        self.search.textChanged.connect(self._filter)
        self._fill()

    def _fill(self):
        folders = {}
        for title, _ in FOLDERS:
            folders[title] = QtWidgets.QTreeWidgetItem(self.tree, [title])
        entries = [(f, n, d, "") for f, n, d in COMMON] + _library()
        now = current(self.doc)[1]
        for folder, name, value, uuid in entries:
            item = QtWidgets.QTreeWidgetItem(folders[folder], [name])
            item.setData(0, QtCore.Qt.UserRole, (folder, name, value, uuid))
            if name == now:
                self.tree.setCurrentItem(item)
        for item in folders.values():
            if item.childCount() == 0:
                item.setHidden(True)

    def _picked(self):
        item = self.tree.currentItem()
        return item.data(0, QtCore.Qt.UserRole) if item is not None else None

    def _show(self, *args):
        data = self._picked()
        self.apply_button.setEnabled(data is not None)
        if data is None:
            for label in (self.name, self.folder, self.density):
                label.setText("-")
            return
        folder, name, value, _ = data
        self.name.setText(name)
        self.folder.setText(folder)
        self.density.setText("%g kg/m^3" % value)

    def _filter(self, text):
        text = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            folder = self.tree.topLevelItem(i)
            shown = 0
            for j in range(folder.childCount()):
                child = folder.child(j)
                hide = bool(text) and text not in child.text(0).lower()
                child.setHidden(hide)
                shown += not hide
            folder.setHidden(shown == 0)
            folder.setExpanded(bool(text) and shown > 0)

    def _apply(self):
        data = self._picked()
        if data is None:
            return
        folder, name, value, uuid = data
        apply(self.doc, name, value, uuid)


_dialog = None


def edit(doc=None):
    global _dialog
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    if _dialog is not None:
        try:
            _dialog.close()
        except RuntimeError as _fw_err:
            _fw_log("material.py:412", _fw_err)
    try:
        from . import materialdlg
        _dialog = materialdlg.edit(doc)
        return _dialog
    except Exception as error:
        App.Console.PrintLog("FreeCAD: material dialog: %s\n" % error)
    _dialog = MaterialDialog(doc)
    _dialog.show()
    return _dialog


class _Observer:
    def slotCreatedDocument(self, doc):
        name = doc.Name  # the document may be closed before the timer fires
        QtCore.QTimer.singleShot(0, lambda: _new_document(name))

    def slotCreatedObject(self, obj):
        if obj.TypeId != "PartDesign::Body":
            return
        doc = obj.Document
        try:
            if doc.Restoring or doc.Importing:
                return
        except AttributeError as _fw_err:
            _fw_log("material.py:437", _fw_err)
        name = doc.Name
        QtCore.QTimer.singleShot(0, lambda: _first_body(name))


def _busy(doc, again):
    """True while the document recomputes; the timer can fire inside it, and FreeCAD refuses a
    recompute there ("Recursive calling of recompute"), so try again a little later."""
    if getattr(doc, "Recomputing", False):
        QtCore.QTimer.singleShot(50, again)
        return True
    return False


def _new_document(doc_name):
    ""
    try:
        doc = App.getDocument(doc_name)
    except Exception:
        return
    if _busy(doc, lambda: _new_document(doc_name)):
        return
    if doc.FileName or doc.Objects or row(doc) is not None:
        return
    make(doc)
    doc.recompute()
    try:   # an empty new part closes without a save prompt
        Gui.getDocument(doc_name).Modified = False
    except Exception as _fw_err:
        _fw_log("material.py:466", _fw_err)


def _first_body(doc_name):
    try:
        doc = App.getDocument(doc_name)
    except Exception:
        return
    if _busy(doc, lambda: _first_body(doc_name)):
        return
    obj = row(doc)
    if obj is None:
        make(doc)
        doc.recompute()
    else:
        _to_bodies(doc, obj)


_observer = None


def install():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
