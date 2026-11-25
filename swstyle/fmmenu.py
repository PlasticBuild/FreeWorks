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
from PySide import QtCore, QtGui, QtWidgets

from . import paths, treefolders

Qt = QtCore.Qt

PLANE_TYPES = ("App::Plane", "PartDesign::Plane")
AXIS_TYPES = ("App::Line", "PartDesign::Line")
POINT_TYPES = ("App::Point", "PartDesign::Point")
REFERENCE_TYPES = PLANE_TYPES + AXIS_TYPES + POINT_TYPES + (
    "PartDesign::CoordinateSystem", "App::LocalCoordinateSystem", "PartDesign::ShapeBinder",
    "PartDesign::SubShapeBinder", "Sketcher::SketchObject")
FULL_ONLY = ("InvertSelection", "Customize", "BodyProperties", "GoToFeatureInTree",
             # R9 read 52: a suppressed feature's short menu is the unsuppressed one (the row's eye unsuppresses)
             "Unsuppress", "UnsuppressDependents",

             "BodyComment", "BodyMoveCopy", "BodyFavorites", "BodyFreeCADProperties", "BodyGoTo", "BodyTreeItems")

# toolbar there, not in the menu

# as on the face bar (partmenu.ROW_TOP)
TREE_ROW = {"feature": ("EditFeature", "EditFeatureSketch", "Suppress", "Rollback", "HideSelection", "ZoomSelection",
                        "NormalTo", "EditAppearance"),

            # R9 read 53, a body row: Insert into New Part / Hide, Zoom to Selection, Normal To, Appearance
            "body": ("InsertIntoNewPart", "HideSelection", "ZoomSelection", "NormalTo", "EditAppearance"),
            "sketch": ("EditFeatureSketch", "EditSketchPlane", "Suppress", "Rollback", "HideSelection", "ZoomSelection",
                       "NormalTo")}


TREE_ITEMS = (
    ("Blocks", "Automatic"), ("Design Binder", "Automatic"), ("Annotations", "Show"),
    ("Solid Bodies", "Automatic"), ("Surface Bodies", "Automatic"), ("Tables", "Automatic"),
    ("Favorites", "Automatic"), ("Selection Sets", "Automatic"), ("Markups", "Automatic"),
    ("Equations", "Automatic"), ("Material", "Show"), ("Default Planes", "Show"), ("Origin", "Show"),
    ("Mate References", "Automatic"), ("Sensors", "Show"), ("History", "Show"),
    ("Graphic Bodies", "Automatic"),
)

HIDDEN_FOLDERS = ("Design Binder", "Surface Bodies", "Solid Bodies", "Lights and Cameras", "Markups", "Equations")
TREE_DISPLAY = (
    ("TreeFlat", "Show Flat Tree View", False),
    ("TreeShowNames", "Show Feature Names", True),
    ("TreeShowDescriptions", "Show Feature Descriptions", False),
    ("TreeComponentDescriptions", "Component Name and Description.", False),
    ("TreeCommentIndicator", "Show Comment Indicator", True),
)

MATERIALS = (
    ("Plain Carbon Steel", ("Steel-Generic", "CalculiX-Steel", "MildSteel")),
    ("Cast Alloy Steel", ("Steel-Generic", "LowAlloySteel")),
    ("ABS PC", ("ABS-Generic",)),
    ("Malleable Cast Iron", ("Iron-Generic", "MalleableCastIron")),
    ("1060 Alloy", ("Aluminum-Generic", "Aluminum-6061-T6")),
    ("Brass", ("Brass-Generic", "Brass")),
    ("Copper", ("Copper-Generic", "Copper")),
    ("PBT General Purpose", ("PBT-Generic", "PBT")),
    ("Nickel", ("Nickel-Generic", "Nickel")),
    ("Rubber", ("Rubber-Generic", "Rubber")),
)
# The look a favourite gives the part when FreeCAD has no material of that name (shape colour)
FAVORITE_COLORS = {"PBT General Purpose": (0.92, 0.92, 0.90), "Nickel": (0.72, 0.72, 0.70),
                   "Rubber": (0.10, 0.10, 0.10), "Brass": (0.80, 0.66, 0.30)}


FOLDER_KINDS = ("material", "bodies", "surfaces", "blank", "history", "sensors", "annotations", "flatfolder")


class Folder:
    """A FeatureManager row that is not a document object: the Material row ("material"), the
    Solid Bodies folder ("bodies"), or the empty space under the rows ("blank"). label is the
    row's text, as the tree shows it."""

    def __init__(self, kind, doc=None, label=""):
        self.kind = kind
        self.doc = doc or App.ActiveDocument
        self.label = label or {"material": "Material", "bodies": "Solid Bodies", "surfaces": "Surface Bodies"}.get(kind, kind)

    @property
    def Document(self):
        return self.doc


class CutBody(Folder):
    ""


    def __init__(self, obj, item=None):
        super().__init__("cutbody", obj.Document, obj.Label)
        self.obj, self.item = obj, item


CUT_ITEM_PROXIES = ("CutListItem", "SMCutListItem")


def cut_body_row(view, global_pos, target):
    """target wrapped as a CutBody when the tree row under global_pos is a body under a cut list item."""
    try:
        if target is None or isinstance(target, (App.Document, Folder)) or not hasattr(view, "fm"):
            return target
        node = view.fm.node(view.indexAt(view.viewport().mapFromGlobal(global_pos)))
        parent = getattr(node, "parent", None)
        item = getattr(parent, "obj", None)
        if node is not None and node.obj is target and item is not None and \
                type(getattr(item, "Proxy", None)).__name__ in CUT_ITEM_PROXIES:
            return CutBody(target, item)
    except Exception as _fw_err:
        _fw_log("fmmenu.py:cut-body-row", _fw_err)
    return target


def _cut_body_entries(shell, row, view=None):
    ""

    from . import featurerc
    body, doc = row.obj, row.doc
    out = []
    add = out.append
    add((None, "Body (%s)" % body.Label, None, False))
    vo = getattr(body, "ViewObject", None)
    if vo is not None:
        shown = bool(vo.Visibility)
        add(("HideBody", "Hide" if shown else "Show", lambda: setattr(body.ViewObject, "Visibility", not shown), True))
    have = {e[0]: e for e in featurerc._body_entries([body])}
    for key in ("IsolateBody", "DeleteKeepBody", "InsertIntoNewPart"):
        e = have.get(key)
        if e is not None and e[3]:
            add(e)
    add(("Comment", "Comment", Sub(lambda m: _comment_menu(m, shell, None, doc)), True))
    add(("GoTo", "Go To...", lambda: go_to(view, doc), True))
    add(("-", None, None, False))
    add(("TreeItems", "Hide/Show Tree Items...", tree_items, True))
    add(("Collapse", "Collapse Items", lambda: collapse(view), True))
    add(("Customize", "Customize Menu", None, True))
    return out


def _cut_body_bar(shell, row):
    """The body toolbar over its menu, as on a Solid Bodies row: Hide (Show when hidden), Zoom to Selection."""
    from . import contextbar
    out = []
    try:
        shown = bool(row.obj.ViewObject.Visibility)
        b = shell.binding("HideSelection" if shown else "ShowSelection")
        out.append(contextbar.Entry("HideSelection", b.cmd.label, b.icon(), contextbar._tip(b.cmd.label, row.obj.Label),
                                    lambda o=row.obj, on=not shown: setattr(o.ViewObject, "Visibility", on)))
    except Exception as _fw_err:
        _fw_log("fmmenu.py:cut-body-bar", _fw_err)
    zoom = contextbar._command_entry(shell, "ZoomSelection")
    if zoom is not None:
        out.append(zoom)
    return out


def material_favorites():
    ""

    legacy = _legacy_favorites()
    try:
        from . import materialdlg
        known = dict(legacy)
        return [(n, tuple(known.get(n, (n,)))) for n in materialdlg.favorites()]
    except Exception as _fw_err:
        _fw_log("fmmenu.py:favorites", _fw_err)
    return legacy


def _legacy_favorites():
    ""
    try:
        kept = json.loads(_params().GetString("MaterialFavorites", "") or "null")
    except Exception:
        kept = None
    if isinstance(kept, list):
        return [(str(label), tuple(names)) for label, names in kept]
    return list(MATERIALS)


def set_material_favorites(items):
    _params().SetString("MaterialFavorites", json.dumps([[label, list(names)] for label, names in items]))
    try:
        from . import materialdlg
        materialdlg.set_favorites([label for label, _names in items])
    except Exception as _fw_err:
        _fw_log("fmmenu.py:setfav", _fw_err)


def _dialog_material(label):
    """A material of the Material box's libraries (Custom Materials and the user's own libraries too)."""
    try:
        from . import materialdlg
        return materialdlg.find(label)
    except Exception:
        return None


def _all_materials():
    """Names of FreeCAD's materials, sorted."""
    try:
        import Materials
        return sorted({m.Name for m in Materials.MaterialManager().Materials.values()}, key=str.lower)
    except Exception:
        return []


def current_material(doc):
    try:
        from . import material as _mat
        name = _mat.current(doc)[1] if doc is not None else None
        if name:
            return name
    except Exception as _fw_err:
        _fw_log("fmmenu.py:156", _fw_err)
    for o in material_targets(doc) if doc is not None else []:
        m = getattr(o, "ShapeMaterial", None)
        if m is not None and getattr(m, "Name", "") and m.Name.lower() != "default":     # FreeCAD's Default: none
            return m.Name
    return ""


def _params():
    return paths.params()


def _mw():
    return Gui.getMainWindow()


class Sub:
    """A submenu entry: fill(menu) adds its items each time it opens."""

    def __init__(self, fill):
        self.fill = fill


def _later(fn):
    """Run after the menu's own event loop has ended."""
    QtCore.QTimer.singleShot(0, fn)


# ---- what a row is -----------------------------------------------------------------------------

def kind_of(target):
    if isinstance(target, Folder):
        return target.kind
    if isinstance(target, App.Document) or target is None:
        return "part"
    if treefolders.is_folder(target):
        return "treefolder"
    if _surface_type(target) == "row":
        return "surfacerow"
    try:
        from . import equations
        if equations.is_sheet(target):
            return "equations"
    except Exception as _fw_err:
        _fw_log("fmmenu.py:198", _fw_err)
    tid = target.TypeId
    if tid in PLANE_TYPES:
        return "plane"
    if tid in AXIS_TYPES or tid in POINT_TYPES or tid == "App::Origin" or tid.endswith("CoordinateSystem"):
        return "reference"
    if target.isDerivedFrom("Sketcher::SketchObject"):
        return "sketch"
    if tid == "PartDesign::Body":
        return "body"
    return "feature"


def heading(target):
    if isinstance(target, Folder):
        return target.label
    if kind_of(target) == "part":
        doc = target if isinstance(target, App.Document) else App.ActiveDocument
        return "Part (%s)" % (doc.Label if doc is not None else "")
    if kind_of(target) == "treefolder":
        return "Folder (%s)" % target.Label
    if kind_of(target) == "equations":
        return "Equations"
    return "Feature (%s)" % target.Label


def body_of(obj):
    try:
        for parent in obj.InList:
            if parent.TypeId == "PartDesign::Body" and obj in parent.Group:
                return parent
    except Exception as _fw_err:
        _fw_log("fmmenu.py:230", _fw_err)
    return None


# ---- document lists (favorites, selection sets) ------------------------------------------------

def _meta_list(doc, key):
    try:
        return json.loads(doc.Meta.get(key, "[]"))
    except Exception:
        return []


def _set_meta_list(doc, key, value):
    meta = dict(doc.Meta)
    meta[key] = json.dumps(value)
    doc.Meta = meta


def favorites(doc):
    return [doc.getObject(n) for n in _meta_list(doc, "SWFavorites") if doc.getObject(n) is not None]


def add_favorite(obj):
    doc = obj.Document
    names = _meta_list(doc, "SWFavorites")
    if obj.Name not in names:
        names.append(obj.Name)
        _set_meta_list(doc, "SWFavorites", names)


def remove_favorite(obj):
    doc = obj.Document
    names = [n for n in _meta_list(doc, "SWFavorites") if n != obj.Name]
    _set_meta_list(doc, "SWFavorites", names)


def selection_sets(doc):
    return _meta_list(doc, "SWSelectionSets")


def new_selection_set(doc, target=None):
    ""

    picks = []
    for s in Gui.Selection.getSelectionEx(doc.Name, 0):
        subs = list(s.SubElementNames) or [""]
        for sub in subs:
            picks.append([s.ObjectName, sub])
    if not picks and target is not None and getattr(target, "Document", None) is doc:
        picks.append([target.Name, ""])
    if not picks:
        return None
    sets = selection_sets(doc)
    taken = {s["name"] for s in sets}
    n = 1
    while "Selection Set%d" % n in taken:
        n += 1
    entry = {"name": "Selection Set%d" % n, "picks": picks}
    sets.append(entry)
    _set_meta_list(doc, "SWSelectionSets", sets)
    return entry


def select_set(doc, name):
    for s in selection_sets(doc):
        if s["name"] == name:
            Gui.Selection.clearSelection()
            for obj, sub in s["picks"]:
                if doc.getObject(obj.split(".")[0]) is None:
                    continue
                if sub:
                    Gui.Selection.addSelection(doc.Name, obj, sub)
                else:
                    Gui.Selection.addSelection(doc.Name, obj)
            return True
    return False


# ---- relations -------------------------------------------------------------------------------

def _shown_feature(obj):
    from .multibody import is_helper
    return obj is not None and obj.TypeId not in ("App::Origin", "PartDesign::Body") and \
        not obj.isDerivedFrom("App::DocumentObjectGroup") and not is_helper(obj)


def parents(obj):
    ""

    from . import treerefs
    return [o for o in treerefs.parents(obj) if _shown_feature(o)]


def children(obj):
    """The features built on obj (the same relation, the other way)."""
    from . import treerefs
    return [o for o in treerefs.children(obj) if _shown_feature(o)]


def unused_features(doc):
    ""
    out = []
    for obj in doc.Objects:
        if obj.TypeId not in REFERENCE_TYPES:
            continue
        body = body_of(obj)
        if body is not None and getattr(body, "Tip", None) == obj:
            continue
        if any(o.TypeId not in ("PartDesign::Body", "App::Origin") and not o.isDerivedFrom("App::DocumentObjectGroup")
               for o in obj.InList):
            continue
        try:
            origin_parent = any(o.TypeId == "App::Origin" for o in obj.InList)
        except Exception:
            origin_parent = False
        if origin_parent:
            continue
        out.append(obj)
    return out


# ---- materials -----------------------------------------------------------------------------------

def _material(names):
    try:
        import Materials
        mm = Materials.MaterialManager()
        by_name = {}
        for uuid, m in mm.Materials.items():
            by_name.setdefault(m.Name, m)
        for n in names:
            m = by_name.get(n)
            if m is not None:
                return m
    except Exception as _fw_err:
        _fw_log("fmmenu.py:363", _fw_err)
    return None


def material_targets(doc):
    out = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    if not out:
        out = [o for o in doc.Objects if hasattr(o, "ShapeMaterial") and not o.InList]
    return out


def favorite_density(label, m=None):
    ""
    from . import material as _mat
    return _mat.known_density(label) or (_mat.library_density(m) if m is not None else None)


def usable_favorite(label, names):
    return _material(names) is not None or favorite_density(label) is not None or _dialog_material(label) is not None


def set_material(doc, names, label=None):
    ""

    from . import material as _mat
    m = _material(names)
    label = label or (m.Name if m is not None else (names[0] if names else ""))
    value = favorite_density(label, m)
    if m is None and value is None:
        if _dialog_material(label) is None:
            return False
        from . import materialdlg       # one of the user's own materials (Custom Materials)
        doc.openTransaction("Material")
        try:
            materialdlg.apply_favorite(doc, label)
        finally:
            doc.commitTransaction()
        return True
    doc.openTransaction("Material")
    try:
        _mat.assign(doc, label, value or _mat.DEFAULT_DENSITY, getattr(m, "UUID", "") if m is not None else "")
        for o in material_targets(doc):
            if m is not None and hasattr(o, "ShapeMaterial"):
                o.ShapeMaterial = m
            rgb = FAVORITE_COLORS.get(label) if m is None else None
            vo = getattr(o, "ViewObject", None)
            if rgb is not None and vo is not None:
                try:
                    vo.ShapeColor = rgb
                except Exception as _fw_err:
                    _fw_log("fmmenu.py:405", _fw_err)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return True


# ---- dialogs ---------------------------------------------------------------------------------------

class ParentChildDialog(QtWidgets.QDialog):
    ""

    def __init__(self, obj, parent=None):
        super().__init__(parent or _mw())
        self.setObjectName("SWParentChild")
        self.setWindowTitle("Parent/Child Relationships")
        lay = QtWidgets.QVBoxLayout(self)
        self.lists = {}
        for title, items in (("Parents", parents(obj)), ("Children", children(obj))):
            box = QtWidgets.QGroupBox(title, self)
            v = QtWidgets.QVBoxLayout(box)
            lw = QtWidgets.QListWidget(box)
            lw.setObjectName("SW" + title)
            for o in items:
                it = QtWidgets.QListWidgetItem(o.ViewObject.Icon if o.ViewObject else QtGui.QIcon(), o.Label)
                lw.addItem(it)
            if not items:
                lw.addItem("(none)")
            v.addWidget(lw)
            lay.addWidget(box)
            self.lists[title] = lw
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close | QtWidgets.QDialogButtonBox.Help, self)
        buttons.rejected.connect(self.reject)
        buttons.helpRequested.connect(self.help)
        lay.addWidget(buttons)
        self.resize(320, 380)

    HELP = ("Parents are what this item is built on: its sketch, the plane or face it sits on, the "
            "feature whose edges or faces it uses. Children are the items built on it. Deleting or "
            "suppressing an item also affects its children; a child cannot be moved above its parent.")

    def help(self):
        self.last_help = self.HELP
        if not getattr(self, "quiet_help", False):
            QtWidgets.QMessageBox.information(self, "Parent/Child Relationships", self.HELP)
        return self.HELP


class PropertiesDialog(QtWidgets.QDialog):
    ""

    def __init__(self, obj, parent=None, title="Feature Properties"):
        super().__init__(parent or _mw())
        self.obj = obj
        self.setObjectName("SWFeatureProperties")
        self.setWindowTitle(title)
        form = QtWidgets.QFormLayout(self)
        self.name = QtWidgets.QLineEdit(obj.Label, self)
        self.name.setObjectName("SWFeatureName")
        self.description = QtWidgets.QLineEdit(obj.Label2, self)
        self.description.setObjectName("SWFeatureDescription")
        doc = obj.Document
        form.addRow("Name:", self.name)
        form.addRow("Description:", self.description)
        self.suppressed = None
        if "Suppressed" in obj.PropertiesList:
            self.suppressed = QtWidgets.QCheckBox("Suppressed", self)
            self.suppressed.setChecked(bool(obj.Suppressed))
            form.addRow("", self.suppressed)

        self.scope = self.configs = None
        try:
            from . import configs as _cfgs
            several = self.suppressed is not None and _cfgs.several(doc)
        except Exception:
            several = False
        if several:
            from . import configmanager as _cm
            self.scope = QtWidgets.QComboBox(self)
            self.scope.setObjectName("SWFeatureConfigScope")
            self.scope.addItems(["This configuration", "All configurations", "Specify configurations"])
            form.addRow("", self.scope)
            self.configs = QtWidgets.QListWidget(self)
            self.configs.setObjectName("SWFeatureConfigList")
            t = _cm.table(doc)
            for n in t.names():
                item = QtWidgets.QListWidgetItem(n)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if n == t.active() else Qt.Unchecked)
                self.configs.addItem(item)
            self.configs.setMaximumHeight(90)
            self.configs.setEnabled(False)
            self.scope.currentIndexChanged.connect(lambda i: self.configs.setEnabled(i == 2))
            form.addRow("", self.configs)
        # the feature's own author and dates (featuredates), the document's for older features
        try:
            from . import featuredates
            who, made, changed = featuredates.info(obj)
        except Exception:
            who, made, changed = (getattr(doc, "CreatedBy", "") or "", getattr(doc, "CreationDate", "") or "",
                                  getattr(doc, "LastModifiedDate", "") or "")
        form.addRow("Created by:", QtWidgets.QLabel(who, self))
        form.addRow("Date created:", QtWidgets.QLabel(made, self))
        form.addRow("Last modified:", QtWidgets.QLabel(changed, self))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self):
        obj = self.obj
        doc = obj.Document
        doc.openTransaction("Feature Properties")
        try:
            if self.name.text().strip() and self.name.text() != obj.Label:
                obj.Label = self.name.text().strip()
            if self.description.text() != obj.Label2:
                obj.Label2 = self.description.text()
            if self.scope is not None and self.scope.currentIndex() > 0 and self.suppressed is not None:
                # All / Specify: set every chosen configuration, even when this one already matches
                from . import configs as _cfgs
                if self.scope.currentIndex() == 1:
                    where = "all"
                else:
                    where = [self.configs.item(i).text() for i in range(self.configs.count())
                             if self.configs.item(i).checkState() == Qt.Checked]
                if where:
                    _cfgs.set_suppressed(obj, self.suppressed.isChecked(), where)
            elif self.suppressed is not None and bool(obj.Suppressed) != self.suppressed.isChecked():
                from . import suppress
                if suppress.configured(obj):
                    suppress.set_one(obj, self.suppressed.isChecked())     # This configuration
                else:
                    obj.Suppressed = self.suppressed.isChecked()
                    doc.recompute()
        finally:
            doc.commitTransaction()


class GoToDialog(QtWidgets.QDialog):
    ""

    def __init__(self, doc, parent=None):
        super().__init__(parent or _mw())
        self.doc = doc
        self.setObjectName("SWGoTo")
        self.setWindowTitle("Go To")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Find what:", self))
        self.edit = QtWidgets.QLineEdit(self)
        self.edit.setObjectName("SWGoToText")
        lay.addWidget(self.edit)
        self.list = QtWidgets.QListWidget(self)
        lay.addWidget(self.list)
        buttons = QtWidgets.QDialogButtonBox(self)
        self.find = buttons.addButton("Find Next", QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.addButton(QtWidgets.QDialogButtonBox.Close)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.edit.textChanged.connect(self.fill)
        self.list.itemDoubleClicked.connect(lambda item: self.accept())
        self.fill("")

    def matches(self, text):
        text = text.lower()
        return [o for o in self.doc.Objects if _shown_feature(o) or o.TypeId == "PartDesign::Body"
                if text in o.Label.lower()]

    def fill(self, text):
        self.list.clear()
        for o in self.matches(text):
            item = QtWidgets.QListWidgetItem(o.Label)
            item.setData(Qt.UserRole, o.Name)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def chosen(self):
        item = self.list.currentItem()
        return self.doc.getObject(item.data(Qt.UserRole)) if item is not None else None


class TreeItemsDialog(QtWidgets.QDialog):
    ""

    def __init__(self, parent=None):
        super().__init__(parent or _mw())
        self.setObjectName("SWTreeItems")
        self.setWindowTitle("FeatureManager - Hide/show tree items")
        lay = QtWidgets.QVBoxLayout(self)
        box = QtWidgets.QGroupBox("Hide/show tree items", self)
        grid = QtWidgets.QGridLayout(box)
        self.combos = {}
        half = (len(TREE_ITEMS) + 1) // 2
        for i, (name, default) in enumerate(TREE_ITEMS):
            combo = QtWidgets.QComboBox(box)
            combo.setObjectName("SWTreeItem_" + name.replace(" ", ""))
            combo.addItems(("Automatic", "Hide", "Show"))
            combo.setCurrentText(_params().GetString("TreeItem." + name, default))
            row, col = (i, 0) if i < half else (i - half, 2)
            grid.addWidget(QtWidgets.QLabel(name, box), row, col)
            grid.addWidget(combo, row, col + 1)
            self.combos[name] = combo
        lay.addWidget(box)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def apply(self):
        for name, combo in self.combos.items():
            _params().SetString("TreeItem." + name, combo.currentText())
        _rebuild_trees()


def _rebuild_trees():
    try:
        from . import swkeys
        swkeys.rebuild_trees()
    except Exception as _fw_err:
        _fw_log("fmmenu.py:626", _fw_err)


def _show_tree_item(name):
    _params().SetString("TreeItem." + name, "Show")
    _rebuild_trees()


class PurgeDialog(QtWidgets.QDialog):
    ""

    def __init__(self, doc, parent=None):
        super().__init__(parent or _mw())
        self.doc = doc
        self.setObjectName("SWPurge")
        self.setWindowTitle("Purge Unused Features")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Features that nothing in the part uses:", self))
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("SWPurgeList")
        for o in unused_features(doc):
            item = QtWidgets.QListWidgetItem(o.Label)
            item.setData(Qt.UserRole, o.Name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list.addItem(item)
        lay.addWidget(self.list)
        buttons = QtWidgets.QDialogButtonBox(self)
        self.purge = buttons.addButton("Purge", QtWidgets.QDialogButtonBox.AcceptRole)
        if self.list.count() == 0:
            # nothing to purge: say so, no greyed Purge button
            self.list.hide()
            lay.itemAt(0).widget().setText("Nothing in the part is unused: there is nothing to purge.")
            self.purge.hide()
        buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def chosen(self):
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out

    def apply(self):
        names = self.chosen()
        if not names:
            return 0
        self.doc.openTransaction("Purge Unused Features")
        try:
            for n in names:
                if self.doc.getObject(n) is not None:
                    self.doc.removeObject(n)
        finally:
            self.doc.commitTransaction()
        self.doc.recompute()
        return len(names)


class CustomizeDialog(QtWidgets.QDialog):
    ""

    def __init__(self, kind, entries, parent=None):
        super().__init__(parent or _mw())
        self.kind = kind
        self.setObjectName("SWCustomizeMenu")
        self.setWindowTitle("Customize Menu")
        lay = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget(self)
        hidden = hidden_entries(kind)
        for key, label in entries:
            item = QtWidgets.QListWidgetItem(label.replace("&", ""))
            item.setData(Qt.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if key in hidden else Qt.Checked)
            self.list.addItem(item)
        lay.addWidget(self.list)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def apply(self):
        hidden = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() != Qt.Checked:
                hidden.append(item.data(Qt.UserRole))
        _params().SetString("FMMenuHidden." + self.kind, ",".join(hidden))


def hidden_entries(kind):
    return {k for k in _params().GetString("FMMenuHidden." + kind, "").split(",") if k}


OPEN = []        # dialogs open now (tests reach them here)


def _run_dialog(box, on_ok=None):
    OPEN.append(box)
    try:
        if box.exec() == QtWidgets.QDialog.Accepted and on_ok is not None:
            return on_ok(box)
    finally:
        OPEN.remove(box)
        box.deleteLater()
    return None


# ---- the actions -------------------------------------------------------------------------------

def _select(obj):
    Gui.Selection.clearSelection()
    if obj is None or isinstance(obj, App.Document):
        return
    Gui.Selection.addSelection(obj.Document.Name, obj.Name)


def _sketch3d_on_plane(target):
    ""
    try:
        from . import sketch3d
        sketch3d.new_sketch_on_plane(target, "")
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: 3D Sketch On Plane failed: %s\n" % error)


def _binding(shell, key):
    if shell is None:
        return False
    try:
        from . import contextbar
        contextbar.run_key(shell, key)
        return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s failed: %s\n" % (key, error))
        return False


def _binding_ready(shell, key):
    if shell is None:
        return False
    try:
        from . import catalog, contextbar
        cmd = catalog.BY_KEY.get(key)
        if cmd is None:
            return False
        if cmd.natives:
            return contextbar.active_native(cmd) is not None
        return bool(cmd.call and shell.special_enabled(cmd.call))
    except Exception:
        return False


def rename(view, obj):
    if view is not None and hasattr(view, "fm_rename"):
        view.fm_rename(obj)
        return
    target = obj if obj is not None else App.ActiveDocument
    text, ok = QtWidgets.QInputDialog.getText(_mw(), "Rename", "Name:", text=target.Label)
    if ok and text.strip():
        if isinstance(target, App.Document):
            target.Label = text.strip()
        else:
            target.Document.openTransaction("Rename")
            try:
                target.Label = text.strip()
            except BaseException:
                try:
                    target.Document.abortTransaction()
                except Exception:
                    pass
                raise
            target.Document.commitTransaction()


def collapse(view):
    if view is not None and hasattr(view, "fm_collapse"):
        view.fm_collapse()
        return
    if view is not None and hasattr(view, "collapseAll"):
        view.collapseAll()
        model = view.model()
        if model is not None and model.rowCount() > 0:
            view.expand(model.index(0, 0))
        return
    # no tree widget handed in (called from a script or the sweep): the visible model tree of the window
    trees = [t for t in _mw().findChildren(QtWidgets.QTreeWidget) if t.isVisible() and t.topLevelItemCount()]
    if trees:
        collapse(trees[0])


def go_to(view, doc):
    def found(box):
        return box.chosen()
    obj = _run_dialog(GoToDialog(doc), found)
    if obj is None:
        return None
    _select(obj)
    if view is not None and hasattr(view, "fm_reveal"):
        view.fm_reveal(obj)
    return obj


def feature_properties(obj, title="Feature Properties"):
    _run_dialog(PropertiesDialog(obj, title=title), lambda box: box.apply())


def with_body(items, target):
    """The expanded menu of a feature: a Body heading with Body Properties... after Change
    Transparency (entries() keeps its arguments: the assembly menus wrap it)."""
    body = body_of(target) if kind_of(target) == "feature" else None
    keys = [i[0] for i in items]
    if body is None or "ChangeTransparency" not in keys:
        return items
    at = keys.index("ChangeTransparency") + 1
    return items[:at] + [(None, "Body", None, False),
                         ("BodyProperties", "Body Properties...", lambda: feature_properties(body, "Body Properties"), True)] + items[at:]


def picked_with(target):
    """The features picked in the tree together with the row right-clicked."""
    out = [o for o in Gui.Selection.getSelection(target.Document.Name)
           if not isinstance(o, App.Document) and kind_of(o) in ("feature", "sketch")]
    if target not in out:
        out = [target]
    return out


def _rename_new(view, folder):
    ""
    if view is not None and hasattr(view, "fm_rename"):
        QtCore.QTimer.singleShot(400, lambda: rename(view, folder) if folder.Document.getObject(folder.Name) else None)


def add_to_new_folder(view, objs):
    folder = treefolders.add_to_new_folder(objs)
    if folder is not None:
        _rename_new(view, folder)
    return folder


def create_new_folder(view, obj):
    folder = treefolders.create_new_folder(obj)
    if folder is not None:
        _rename_new(view, folder)
    return folder


def delete_folder(folder):
    ""
    answer = QtWidgets.QMessageBox.question(_mw(), "Confirm Delete", "Delete %s?" % folder.Label,
                                            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    if answer != QtWidgets.QMessageBox.Yes:
        return False
    return treefolders.delete(folder)


def change_transparency(obj):
    """A feature's Change Transparency: its body see-through (75 %), or back."""
    body = obj if getattr(obj, "TypeId", "") == "PartDesign::Body" else body_of(obj)
    if body is None:
        body = obj
    vobj = getattr(body, "ViewObject", None)
    if vobj is None or not hasattr(vobj, "Transparency"):
        return False
    vobj.Transparency = 0 if getattr(vobj, "Transparency", 0) >= 50 else 75
    return True


def _external_refs_of(target):
    """The in-context references (SubShapeBinders to another document) target is built on, or,
    for a document, all of its references."""
    try:
        from . import asmextref
        doc = target if isinstance(target, App.Document) else target.Document
        refs = asmextref.binders(doc)
        if not refs or isinstance(target, App.Document):
            return refs
        deps = set(o.Name for o in target.OutListRecursive) | {target.Name}
        return [b for b in refs if b.Name in deps]
    except Exception:
        return []


def _context_file(doc, target):
    """The assembly file target's in-context references came from, when it is there."""
    try:
        from . import asmextref
        return asmextref.context_of(doc, target)[0]
    except Exception:
        return None


def _edit_in_context(doc, target):
    from . import asmextref
    return asmextref.edit_in_context(doc, target)


def _list_external_refs(doc):
    from . import asmextref
    return _later(lambda: asmextref.list_external_references(doc))


def parent_child(obj):
    _run_dialog(ParentChildDialog(obj))


def tree_items():
    _run_dialog(TreeItemsDialog(), lambda box: box.apply())


def purge(doc):
    return _run_dialog(PurgeDialog(doc), lambda box: box.apply())


def delete(obj):
    _select(obj)
    Gui.runCommand("Std_Delete")
    return True


def _hideable(obj):
    ""

    try:
        return getattr(obj, "ViewObject", None) is not None and (
            obj.isDerivedFrom("Sketcher::SketchObject") or obj.TypeId.startswith("PartDesign::") and
            obj.TypeId in PLANE_TYPES + AXIS_TYPES + POINT_TYPES)
    except Exception:
        return False


def folder_suppressed(folder, on):
    objs = [o for o in treefolders.items(folder) if "Suppressed" in o.PropertiesList]
    if not objs:
        return False

    # their children along (a fillet outside the folder on a cut inside it), and Unsuppress brings back
    # the parents they need. suppress.py does both, in one Undo step (it commits its own transaction
    # even when it stops halfway, so only a missing suppress.py falls back to the code below).
    try:
        from . import suppress
        act = suppress.suppress if on else suppress.unsuppress
    except (ImportError, AttributeError) as error:
        App.Console.PrintLog("FreeCAD: folder suppress: %s\n" % error)
        act = None
    if act is not None:
        try:
            act(objs)
            return True
        except Exception as error:
            App.Console.PrintLog("FreeCAD: folder suppress: %s\n" % error)
            return False
    doc = folder.Document
    doc.openTransaction("Suppress" if on else "Unsuppress")
    try:
        for o in objs:
            o.Suppressed = on
    finally:
        doc.commitTransaction()
    doc.recompute()
    return True


def _folder_shown_items(folder):
    """The folder's items and the sketches its features took in (shown under them in the tree)."""
    out = []
    for o in treefolders.items(folder):
        out.append(o)
        prof = getattr(o, "Profile", None)
        prof = prof[0] if isinstance(prof, (list, tuple)) and prof else prof
        if prof is not None and hasattr(prof, "isDerivedFrom") and prof.isDerivedFrom("Sketcher::SketchObject"):
            out.append(prof)
    return out


def folder_visible(folder, on):
    objs = [o for o in _folder_shown_items(folder) if _hideable(o)]
    for o in objs:
        o.ViewObject.Visibility = on
    return bool(objs)


def set_suppressed(obj, on):
    if "Suppressed" not in obj.PropertiesList:
        return False
    obj.Document.openTransaction("Suppress" if on else "Unsuppress")
    try:
        obj.Suppressed = on
    except BaseException:
        try:
            obj.Document.abortTransaction()
        except Exception:
            pass
        raise
    obj.Document.commitTransaction()
    obj.Document.recompute()
    return True


def _top_level_components(doc):
    """deadrc-1121: the components Top Level Transparency acts on in an assembly (none in a part)."""
    try:
        from . import asmcore
        asm = asmcore.assembly_of(doc)
        return [c for c in (asmcore.components(asm) if asm is not None else [])
                if getattr(c, "ViewObject", None) is not None and "ShapeMaterial" in c.ViewObject.PropertiesList]
    except Exception as _fw_err:
        _fw_log("fmmenu.py:top level components", _fw_err)
        return []


def top_level_transparency_ready(doc):
    """Something for Top Level Transparency to act on: the row button is left out otherwise (greyed = dead)."""
    return doc is not None and bool([o for o in material_targets(doc) if getattr(o, "ViewObject", None) is not None]
                                    or _top_level_components(doc))


def top_level_transparency(doc):
    ""

    bodies = [o for o in material_targets(doc) if getattr(o, "ViewObject", None) is not None]
    if not bodies:
        comps = _top_level_components(doc)
        if not comps:
            return
        from . import asmmenu
        make = not all(asmmenu.transparent(c) for c in comps)
        doc.openTransaction("Top Level Transparency")
        try:
            for c in comps:
                if asmmenu.transparent(c) != make:
                    asmmenu.change_transparency(c)
        finally:
            doc.commitTransaction()
        return
    clear = all(getattr(o.ViewObject, "Transparency", 0) >= 50 for o in bodies)
    for o in bodies:
        o.ViewObject.Transparency = 0 if clear else 75


def edit_sketch(sketch):
    ""
    try:
        Gui.getDocument(sketch.Document.Name).setEdit(sketch.Name)
        return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Edit Sketch: %s\n" % error)
        return False


def _to3d(sketch):
    try:
        from .fwsketch import to3d
        to3d.run(sketch)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Convert to 3D Sketch: %s\n" % error)


def sketch_color(sketch):
    ""
    vobj = getattr(sketch, "ViewObject", None)
    if vobj is None:
        return False
    try:
        r, g, b = vobj.LineColor[:3]
        start = QtGui.QColor.fromRgbF(r, g, b)
    except Exception:
        start = QtGui.QColor(0, 0, 0)
    color = QtWidgets.QColorDialog.getColor(start, Gui.getMainWindow(), "Sketch Color")
    if not color.isValid():
        return False
    value = (color.redF(), color.greenF(), color.blueF())
    doc = sketch.Document
    doc.openTransaction("Sketch Color")
    try:
        for prop in ("LineColor", "PointColor"):
            try:
                setattr(vobj, prop, value)
            except Exception as _fw_err:
                _fw_log("fmmenu.py:1027", _fw_err)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return True


def edit_sketch_plane(sketch):
    _select(sketch)
    for name in ("Sketcher_MapSketch", "Part_EditAttachment"):
        try:
            if Gui.Command.get(name) is not None:
                Gui.runCommand(name)
                return True
        except Exception:
            continue
    return False


# ---- the menu ----------------------------------------------------------------------------------

def entries(shell, target, view=None):
    """_entries with the per-feature-type entries (featurerc.py: Configure Feature, Unsuppress with
    Dependents, reference Delete..., body and Solid Bodies items)."""
    out = _entries(shell, target, view)
    try:
        from . import featurerc
        out = featurerc.tree(out, target, kind_of(target))
    except Exception as _fw_err:
        _fw_log("fmmenu.py:1054", _fw_err)
    if kind_of(target) == "body":
        out = _body_row(out, shell, target, view)
    out = _hide_all_dimensions(out, target)
    try:
        out = _with_expand_and_freecad(out, target, view)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: tree menu extras: %s\n" % error)
    return out


# ---- Expand Items and the FreeCAD submenu (no FreeCAD tree action is lost) ----------------------
def expand(view):
    """Expand Items: every folder and feature of the tree opened (Collapse Items' other half)."""
    if view is not None and hasattr(view, "expandAll"):
        view.expandAll()
        return True
    trees = [t for t in _mw().findChildren(QtWidgets.QTreeWidget) if t.isVisible() and t.topLevelItemCount()]
    if trees:                       # no tree widget handed in: the visible model tree
        trees[0].expandAll()
        return True
    try:
        Gui.runCommand("Std_TreeExpand", 0)
        return True
    except Exception:
        return False



FREECAD_GROUPS = (
    ("Link Actions", ("Std_LinkMake", "Std_LinkMakeRelative", "Std_LinkMakeGroup", "Std_LinkReplace",
                      "Std_LinkUnlink", "Std_LinkImport", "Std_LinkImportAll")),
    ("Link Navigation", ("Std_LinkSelectLinked", "Std_LinkSelectLinkedFinal", "Std_LinkSelectAllLinks",
                         "Std_TreeSelectAllInstances")),
    ("Expression Actions", ("Std_Expressions",)),
    (None, ("Std_ToggleSkipRecompute",)),
    ("Part Design", ("PartDesign_MoveFeature", "PartDesign_MoveFeatureInTree", "PartDesign_Migrate")),

    ("Object", ("Std_Placement", "Part_EditAttachment", "Part_ColorPerFace", "Std_RandomColor", "Std_ToggleFreeze",
                "Std_ToggleSelectability", "Std_SendToPythonConsole")),
)
# FreeCAD's tree widget actions (no command behind them), by their text, per submenu
FREECAD_TREE_ACTIONS = ("Allow Partial Recomputes", "Mark to Recompute", "Recompute Object",
                        "Add Dependent Objects to Selection", "Search Objects")
FREECAD_TREE_SUBMENUS = (("Recompute", FREECAD_TREE_ACTIONS),
                         ("Tree Settings", ("Show Items Hidden in Tree View", "Toggle Visibility in Tree View",
                                            "Show Description", "Show Internal Name")))


# FreeCAD group commands without a QAction until a FreeCAD menu holds them: their items, run by index
GROUP_ITEMS = {"Std_LinkMakeGroup": ("Simple Group", "Group with Links", "Group with Transform Links")}
# FreeCAD's Expression actions crash when run before FreeCAD made their QActions (StdCmdExpression uses

# item opens FreeCAD's tree menu, which holds them, and later menus show them here
NEEDS_ACTION = ("Std_Expressions",)


def _info(name):
    try:
        return Gui.Command.get(name).getInfo() or {}
    except Exception:
        return {}


def _command_actions(name):
    try:
        cmd = Gui.Command.get(name)
    except Exception:
        cmd = None
    if cmd is None:
        return []
    try:
        return [a for a in cmd.getAction() if isinstance(a, QtGui.QAction)]
    except Exception:
        return []


def _active(name):
    """Always on: FreeCAD's Command.isActive() from Python can crash on a command whose QAction a closed
    FreeCAD menu deleted (seen on the bench), and running an inactive command does nothing."""
    return True


def _own_action(menu, name, text=None, index=0):
    """An item that runs a FreeCAD command that has no QAction yet (FreeCAD makes them only for its own menus)."""
    info = _info(name)
    act = QtGui.QAction((text or info.get("menuText") or name).replace("&", ""), menu)
    act.setToolTip(info.get("toolTip") or "")
    try:
        if info.get("pixmap"):
            act.setIcon(Gui.getIcon(info["pixmap"]))
    except Exception as _fw_err:
        _fw_log("fmmenu.py:1146", _fw_err)
    act.setVisible(_active(name))       # FreeCAD's command does not apply here: left out, not greyed
    if name == "Std_ToggleSkipRecompute":
        doc = App.ActiveDocument
        act.setCheckable(True)
        act.setChecked(bool(getattr(doc, "RecomputesFrozen", False)) if doc is not None else False)
    if name == "Std_ToggleSkipRecompute":
        # a toggle command: FreeCAD reads the message as the new state (1 skip, 0 recompute)
        act.triggered.connect(lambda checked=False: _later(lambda: Gui.runCommand(
            "Std_ToggleSkipRecompute", 0 if getattr(App.ActiveDocument, "RecomputesFrozen", False) else 1)))
        return act
    act.triggered.connect(lambda checked=False, n=name, i=index: _later(lambda: Gui.runCommand(n, i)))
    return act


def _freecad_tree():
    """FreeCAD's own tree (hidden under the FeatureManager), which holds its tree actions."""
    for t in _mw().findChildren(QtWidgets.QTreeWidget):
        if t.objectName() == "" and t.findChildren(QtGui.QAction):
            return t
    return None


def fill_freecad(menu, target=None, view=None):
    """The FreeCAD submenu: Link actions, Expression actions, Skip Recomputes, the recompute marks and
    PartDesign's Move to body / Move after / Migrate (FreeCAD's own actions where it has made them), and
    the whole FreeCAD tree menu as the last item."""
    keep = []
    for title, names in FREECAD_GROUPS:
        holder = QtWidgets.QMenu(title, menu) if title else menu
        keep.append(holder)
        for n in names:
            if n in GROUP_ITEMS:
                sub = QtWidgets.QMenu((_info(n).get("menuText") or n).replace("&", ""), holder)
                keep.append(sub)
                for i, text in enumerate(GROUP_ITEMS[n]):
                    sub.addAction(_own_action(sub, n, text, i))
                if not _active(n):
                    continue    # left out, not greyed
                if title == "Expression Actions":
                    for a in sub.actions():
                        holder.addAction(a)
                else:
                    holder.addMenu(sub)
                continue
            if n not in GROUP_ITEMS and Gui.Command.get(n) is None:
                continue            # a workbench not loaded yet (Part's commands): left out, no dead item
            found = _command_actions(n)
            if n in NEEDS_ACTION:
                if found:
                    for a in found:
                        if a.menu() is None and a.text() and a.isEnabled():
                            holder.addAction(a)
                else:
                    first = holder.addAction("Open FreeCAD's Tree Menu for These...")
                    first.setToolTip("FreeCAD keeps these in its own tree menu; after it has opened once they show here")
                    first.setVisible(view is not None and hasattr(view, "fm_native_menu"))
                    first.triggered.connect(lambda checked=False: _later(
                        lambda: view.fm_native_menu(target, QtGui.QCursor.pos())))
                continue
            if len(found) == 1 and not found[0].isEnabled():
                continue        # FreeCAD's own action, greyed for this row: left out
            holder.addAction(found[0] if len(found) == 1 else _own_action(holder, n))
        if title and any(a.isVisible() for a in holder.actions()):
            menu.addMenu(holder)
    tree = _freecad_tree()
    if tree is not None:
        mine = {}
        for a in tree.findChildren(QtGui.QAction):
            mine.setdefault(a.text().replace("&", ""), a)
        for title, texts in FREECAD_TREE_SUBMENUS:
            got = [mine[t] for t in texts if t in mine and mine[t].isEnabled()]
            if got:
                sub = QtWidgets.QMenu(title, menu)
                keep.append(sub)
                for a in got:
                    sub.addAction(a)
                menu.addMenu(sub)
    menu.addSeparator()
    whole = menu.addAction("FreeCAD Tree Menu...")
    whole.setToolTip("FreeCAD's own menu for this row (as Shift+right-click)")
    whole.setVisible(view is not None and hasattr(view, "fm_native_menu"))
    whole.triggered.connect(lambda checked=False: _later(lambda: view.fm_native_menu(target, QtGui.QCursor.pos())))
    menu._fc_keep = keep
    return menu


def _with_expand_and_freecad(out, target, view):
    keys = [e[0] for e in out]
    if "Collapse" in keys and "Expand" not in keys:
        at = keys.index("Collapse")
        out = out[:at + 1] + [("Expand", "Expand Items", lambda: expand(view), True)] + out[at + 1:]
        keys = [e[0] for e in out]
    if isinstance(target, CutBody):
        target = target.obj         # a cut list body row keeps FreeCAD's own menu for the object
    if "FreeCAD" not in keys and not isinstance(target, Folder):
        entry = ("FreeCAD", "FreeCAD", Sub(lambda m: fill_freecad(m, target, view)), True)
        at = keys.index("Customize") if "Customize" in keys else len(out)
        out = out[:at] + [entry] + out[at:]
    return out


DISPLAY_MODES = (("Shaded With Edges", "Flat Lines"), ("Shaded", "Shaded"), ("Wireframe", "Wireframe"),
                 ("Points", "Points"))


def _body_display_menu(menu, body):
    vo = getattr(body, "ViewObject", None)
    modes = list(vo.listDisplayModes()) if vo is not None else []
    for text, mode in DISPLAY_MODES:
        if mode in modes:
            a = menu.addAction(text)
            a.setCheckable(True)
            a.setChecked(vo.DisplayMode == mode)
            a.triggered.connect(lambda _c=False, m=mode: setattr(vo, "DisplayMode", m))


def _body_row(out, shell, body, view):
    ""



    rows = {r[0]: r for r in out if r[0] and r[0] != "-"}
    tip = getattr(body, "Tip", None) or body
    group = picked_with(body)
    from . import partmenu

    def ren(key, new):
        r = rows.pop(key, None)
        return (new,) + tuple(r[1:]) if r else None
    new = [rows.pop("InvertSelection", None), (None, "Body", None, False),
           rows.pop("IsolateBody", None),
           ("BodyMaterial", "Material", Sub(lambda m: _body_material_menu(m, body)), True) if rows.pop("BodyMaterial", None)
           else None,
           ("BodyDisplay", "Body Display", Sub(lambda m: _body_display_menu(m, body)), True),
           rows.pop("DeleteKeepBody", None),
           ("AddToNewFolder", "Add to New Folder", lambda: add_to_new_folder(view, group), True)
           if treefolders.can_group(group) else None,
           rows.pop("InsertIntoNewPart", None), rows.pop("SaveSelection", None), rows.pop("BodyProperties", None),
           ("ChangeTransparency", "Change Transparency", lambda: partmenu._change_transparency(body), True),
           (None, "Feature (%s)" % tip.Label, None, False),
           ("GoToFeatureInTree", "Go To Feature (in Tree)", lambda: _go_to_feature(tip), True),
           rows.pop("ParentChild", None), rows.pop("Collapse", None), rows.pop("Rename", None),
           ren("Comment", "BodyComment"), ren("MoveCopyBody", "BodyMoveCopy"), ren("Favorites", "BodyFavorites"),
           ren("Properties", "BodyFreeCADProperties"), ren("GoTo", "BodyGoTo"), ren("TreeItems", "BodyTreeItems")]
    new = [r for r in new if r is not None]
    new += [r for k, r in rows.items() if k not in ("Customize",) and r[0] is not None]
    new.append(rows.get("Customize") or ("Customize", "Customize Menu", None, True))
    return new


def _body_material_menu(menu, body):
    ""

    from . import massprops
    menu.addAction("Edit Material").triggered.connect(lambda: _later(lambda: massprops.edit_body_material(body)))
    now = massprops.body_material(body)[0] or ""
    for label, names in material_favorites():
        if not usable_favorite(label, names):
            continue
        a = menu.addAction(label)
        a.setCheckable(True)
        a.setChecked(label == now)
        a.triggered.connect(lambda _c=False, l=label, n=names: _later(
            lambda: massprops.set_body_material(body, l, favorite_density(l, _material(n)))))


def _go_to_feature(feature):
    try:
        from . import partextras
        partextras.go_to_feature(feature)
    except Exception:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(feature)


def dims_shown(target):
    try:
        from . import featuredimshow
        return bool(featuredimshow.SHOWN.feature) and featuredimshow.SHOWN.feature == getattr(target, "Name", None)
    except Exception:
        return False


def _hide_all_dimensions(out, target):
    ""

    if not dims_shown(target) or any(r[0] == "HideAllDimensions" for r in out):
        return out
    from . import featuredimshow
    row = ("HideAllDimensions", "Hide All Dimensions", featuredimshow.hide, True)
    at = next((i + 1 for i, r in enumerate(out) if r[0] is None and r[1].startswith("Feature")), None)
    if at is None:
        at = next((i for i, r in enumerate(out) if r[0] == "Comment"), 0)
    return out[:at] + [row] + out[at:]


def _entries(shell, target, view=None):
    ""

    kind = kind_of(target)
    doc = target if isinstance(target, App.Document) else (target.Document if target is not None else App.ActiveDocument)
    out = []
    add = out.append
    if kind == "part":
        add(("GoTo", "Go To...", lambda: go_to(view, doc), True))
        add((None, heading(target), None, False))
        add(("HiddenTreeItems", "Hidden Tree Items", Sub(_hidden_items_menu), True))
        add(("AddToLibrary", "Add to Library", lambda: add_part_to_library(doc), True))
        add(("Comment", "Comment", Sub(lambda m: _comment_menu(m, shell, None, doc)), True))
        add(("TreeDisplay", "Tree Display", Sub(_tree_display_menu), True))
        add(("DocumentProperties", "Document Properties...", lambda: _document_properties(), True))
        if _external_refs_of(doc):
            add(("ExternalRefs", "External References...", lambda: _list_external_refs(doc), True))
        add(("ConfigurationPublisher", "Configuration Publisher...", lambda: configuration_publisher(doc), True))
        add(("Appearance", "Appearance", Sub(lambda m: _appearance_menu(m, shell, doc)), True))
        add(("Material", "Material", Sub(lambda m: _material_menu(m, shell, doc)), True))
        add(("TopLevelTransparency", "Top Level Transparency", lambda: top_level_transparency(doc),
             top_level_transparency_ready(doc)))
        add(("Purge", "Purge Unused Features...", lambda: purge(doc), True))
        add(("ConvertToBodies", "Convert to Bodies...", lambda: convert_to_bodies(doc), bool(_solid_shapes(doc))))
        add(("-", None, None, False))
        add(("Rename", "Rename tree item", lambda: rename(view, doc), True))
        add(("TreeItems", "Hide/Show Tree Items...", tree_items, True))
        add(("Collapse", "Collapse Items", lambda: collapse(view), True))
        add(("Customize", "Customize Menu", None, True))
        return out
    if kind == "cutbody":
        return _cut_body_entries(shell, target, view)
    if kind in FOLDER_KINDS:
        return folder_entries(shell, target, view)
    if kind == "surfacerow":
        return _surface_row_entries(shell, target, view)
    if kind == "equations":

        def manage():
            from . import equations
            equations.show(doc)
        add(("ManageEquations", "Manage Equations...", manage, True))
        add((None, heading(target), None, False))
        add(("-", None, None, False))
        add(("TreeItems", "Hide/Show Tree Items...", tree_items, True))
        add(("Collapse", "Collapse Items", lambda: collapse(view), True))
        add(("Customize", "Customize Menu", None, True))
        return out
    if kind == "treefolder":
        add((None, heading(target), None, False))

        # reference items, as on the features themselves
        inside = list(treefolders.items(target))
        can = [o for o in inside if "Suppressed" in o.PropertiesList]
        if can:
            off = all(bool(o.Suppressed) for o in can)
            add(("Suppress", "Unsuppress" if off else "Suppress", lambda: folder_suppressed(target, not off), True))
        seen = [o for o in _folder_shown_items(target) if _hideable(o)]
        if seen:
            shown = any(o.ViewObject.Visibility for o in seen)
            add(("HideFolder", "Hide" if shown else "Show", lambda: folder_visible(target, not shown), True))
        add(("Delete", "Delete...", lambda: delete_folder(target), True))
        add(("GoTo", "Go To...", lambda: go_to(view, doc), True))
        add(("-", None, None, False))
        add(("Rename", "Rename tree item", lambda: rename(view, target), True))
        add(("TreeItems", "Hide/Show Tree Items...", tree_items, True))
        add(("Collapse", "Collapse Items", lambda: collapse(view), True))
        add(("Customize", "Customize Menu", None, True))
        return out
    add(("InvertSelection", "Invert Selection", lambda: _binding(shell, "InvertSelection"),
         _binding_ready(shell, "InvertSelection")))
    add((None, heading(target), None, False))
    if kind == "sketch":

        add(("MakeReferenceSketch", "Make Reference Sketch", lambda: make_reference_sketch(target), True))
    if kind == "feature" and _is_fillet(target):
        add(("ConvertFilletToChamfer", "Convert Fillet to Chamfer", lambda: convert_fillet_to_chamfer(target),
             _fillet_body(target) is not None))
    if kind == "plane":
        add(("Sketch3DOnPlane", "3D Sketch On Plane", lambda: _sketch3d_on_plane(target), shell is not None))
        add(("SectionView", "Section View", lambda: (_select(target), _binding(shell, "SectionView")),
             shell is not None))
        add(("LiveSection", "Live Section Plane", lambda: (_select(target), _binding(shell, "LiveSection")),
             shell is not None))
    try:
        from . import treevirtual
        if treevirtual.is_sensor(target):
            add(("EditSensor", "Edit Sensor...", lambda: _later(lambda: treevirtual.edit_sensor(target)), True))
    except Exception as _fw_err:
        _fw_log("fmmenu.py:1404", _fw_err)
    add(("Comment", "Comment", Sub(lambda m: _comment_menu(m, shell, target, doc)), True))
    add(("ParentChild", "Parent/Child...", lambda: parent_child(target), True))
    if _external_refs_of(target):

        add(("ListExternalRefs", "List External Refs...", lambda: _list_external_refs(doc), True))
        if _context_file(doc, target):

            add(("EditInContext", "Edit In Context", lambda: _later(lambda: _edit_in_context(doc, target)), True))
    if kind == "sketch":
        add(("ConfigureFeature", "Configure Feature", lambda: _configure_feature(target), True))


    # entries; a sketch on its own has them, as a feature does
    own = kind == "feature" or (kind == "sketch" and sketch_owner(target) is None)
    if own:
        add(("Delete", "Delete...", lambda: delete(target), True))
    fav = target in favorites(doc)
    add(("Favorites", "Remove from Favorites" if fav else "Add to Favorites",
         (lambda: remove_favorite(target)) if fav else (lambda: add_favorite(target)), True))
    add(("SaveSelection", "Save Selection", Sub(lambda m: _save_selection_menu(m, doc, target)), True))
    if own:
        group = picked_with(target)
        add(("AddToNewFolder", "Add to New Folder", lambda: add_to_new_folder(view, group),
             treefolders.can_group(group)))
    if kind == "sketch":
        add(("SketchColor", "Sketch Color", lambda: sketch_color(target), True))
    if kind == "sketch" and getattr(target, "TypeId", "") == "Sketcher::SketchObject":

        add(("ConvertTo3DSketch", "Convert to 3D Sketch", lambda: _to3d(target), True))
    if kind == "sketch" and "Suppressed" in target.PropertiesList:
        on = bool(target.Suppressed)
        add(("Suppress", "Unsuppress" if on else "Suppress", lambda: set_suppressed(target, not on), True))
    if kind in ("feature", "sketch"):
        add(("Properties", "Feature Properties...", lambda: feature_properties(target), True))
    else:
        add(("Properties", "Properties...", lambda: feature_properties(target), True))
    if kind == "feature":
        body = body_of(target)
        add(("ChangeTransparency", "Change Transparency", lambda: change_transparency(target), body is not None))
        add(("FeatureWorks", "Feature Recognition...", Sub(_featureworks_menu), True))     # own name (alpha AE6)
    if kind in ("sketch", "plane"):
        add(("-", None, None, False))
    add(("GoTo", "Go To...", lambda: go_to(view, doc), True))
    if own:
        add(("CreateNewFolder", "Create New Folder", lambda: create_new_folder(view, target),
             body_of(target) is not None))

    # Axis1) ends Go To..., Create New Folder, Collapse Items, Rename tree item, Hide/Show Tree Items...; a row with
    # rows under it (Boss-Extrude1 with its sketch) and the default planes end Rename tree item, Hide/Show Tree
    # Items..., Collapse Items (pkg211)
    if _collapse_last(target):
        add(("Rename", "Rename tree item", lambda: rename(view, target), True))
        add(("TreeItems", "Hide/Show Tree Items...", tree_items, True))
        add(("Collapse", "Collapse Items", lambda: collapse(view), True))
    else:
        add(("Collapse", "Collapse Items", lambda: collapse(view), True))
        add(("Rename", "Rename tree item", lambda: rename(view, target), True))
        add(("TreeItems", "Hide/Show Tree Items...", tree_items, True))
    add(("Customize", "Customize Menu", None, True))
    return out


def _collapse_last(target):
    """True for a tree row with rows under it, or a default plane of the Origin (see the tail above)."""
    try:
        if any(target in (getattr(o, "OriginFeatures", None) or []) for o in target.InList
               if o.TypeId == "App::Origin"):
            return True
        vo = getattr(target, "ViewObject", None)
        return bool(vo is not None and vo.claimChildren())
    except Exception:
        return False


def _surface_row_entries(shell, row, view=None):
    """A body in the Surface Bodies folder: Hide (Show when hidden) the body, Delete/Keep Body..., Comment, Go To...,
    Hide/Show Tree Items..., Collapse Items. It got the part feature menu before: Configure Feature, Parent/Child...,
    FeatureWorks..., none of which reach a body row (pkg219)."""
    from . import surfacebodies
    doc = row.Document
    src = surfacebodies.source(row)
    out = []
    add = out.append
    add((None, "Body (%s)" % (src.Label if src is not None else row.Label), None, False))
    if src is not None and src.ViewObject is not None:
        shown = bool(src.ViewObject.Visibility)
        add(("HideBody", "Hide" if shown else "Show", lambda: setattr(row.ViewObject, "Visibility", not shown), True))

        def delete_keep():
            from . import surfdelkeep
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(src)
            surfdelkeep.start(doc)
        add(("DeleteKeepBody", "Delete/Keep Body...", lambda: _later(delete_keep), True))
    add(("Comment", "Comment", Sub(lambda m: _comment_menu(m, shell, None, doc)), True))
    add(("GoTo", "Go To...", lambda: go_to(view, doc), True))
    add(("-", None, None, False))
    add(("TreeItems", "Hide/Show Tree Items...", tree_items, True))
    add(("Collapse", "Collapse Items", lambda: collapse(view), True))
    add(("Customize", "Customize Menu", None, True))
    return out


def folder_entries(shell, folder, view=None):
    """The Material row and the Solid Bodies folder."""
    doc = folder.doc
    out = []
    add = out.append
    if folder.kind in ("history", "sensors", "annotations"):
        from . import treevirtual         # the part's top folders
        return treevirtual.entries(folder.kind, doc, view)
    if folder.kind == "flatfolder":
        # pkg257: the Flat-Pattern folder row of a sheet metal part had no menu at all (a dead row); the
        # tree rows every folder has
        add((None, "Folder (%s)" % folder.label, None, False))
        add(("GoTo", "Go To...", lambda: go_to(view, doc), True))
        add(("TreeItems", "Hide/Show Tree Items...", tree_items, True))
        add(("Collapse", "Collapse Items", lambda: collapse(view), True))
        add(("Customize", "Customize Menu", None, True))
        return out
    if folder.kind == "blank":
        # a right-click under the rows (1000-hour recording 9527ae7a)
        add(("DocumentProperties", "Document Properties...", lambda: _document_properties(), True))
        add(("TreeItems", "Hide/Show Tree Items...", tree_items, True))
        add(("Collapse", "Collapse Items", lambda: collapse(view), True))
        add(("Customize", "Customize Menu", None, True))
        return out
    if folder.kind == "material":
        add((None, heading(folder), None, False))
        add(("EditMaterial", "Edit Material", lambda: _edit_material(shell, doc), bool(material_targets(doc))))
        add(("ManageFavorites", "Manage Favorites", lambda: manage_favorites(doc), True))
        add(("-", None, None, False))
        current = current_material(doc)
        for label, names in material_favorites():
            m = _material(names)
            if not usable_favorite(label, names):
                continue
            tick = bool(current) and (label == current or (m is not None and m.Name == current))
            if tick:
                current = ""         # several favourites can share one FreeCAD material: tick the first
            add(("Fav:" + label, ("✓ " if tick else "") + label,
                 (lambda n=names, l=label: set_material(doc, n, l)), bool(material_targets(doc))))
        add(("-", None, None, False))
    elif folder.kind == "surfaces":
        # the Surface Bodies folder: its surfaces shown or hidden together, as the Solid Bodies folder's
        from . import surfacebodies
        surfaces = surfacebodies.bodies(doc)
        shown = any(b.ViewObject is not None and b.ViewObject.Visibility for b in surfaces)
        add((None, heading(folder), None, False))
        add(("HideBodies", "Hide Bodies" if shown else "Show Bodies",
             lambda: surfacebodies.show_all(doc, not shown), bool(surfaces)))
        add(("Comment", "Comment", Sub(lambda m: _comment_menu(m, shell, None, doc)), True))
    else:
        bodies = _solid_bodies(doc)
        shown = any(b.ViewObject is not None and b.ViewObject.Visibility for b in bodies)
        add((None, heading(folder), None, False))
        add(("HideBodies", "Hide Bodies" if shown else "Show Bodies",
             lambda: _show_bodies(bodies, not shown), bool(bodies)))
        add(("SaveBodies", "Save Bodies...", lambda: _binding(shell, "SaveBodies"),
             _binding_ready(shell, "SaveBodies") and bool(bodies)))
        add(("Combine", "Combine", lambda: (_select_all(bodies), _binding(shell, "Combine")),
             len(bodies) > 1 and shell is not None))
        add(("MoveCopyBodies", "Move/Copy Bodies", lambda: (_select_all(bodies), _binding(shell, "MoveCopyBodies")),
             bool(bodies) and shell is not None))
        add(("Comment", "Comment", Sub(lambda m: _comment_menu(m, shell, None, doc)), True))
    add(("GoTo", "Go To...", lambda: go_to(view, doc), True))
    add(("-", None, None, False))
    add(("TreeItems", "Hide/Show Tree Items...", tree_items, True))
    add(("Collapse", "Collapse Items", lambda: collapse(view), True))
    add(("Customize", "Customize Menu", None, True))
    return out


def _solid_bodies(doc):
    """The bodies the Solid Bodies folder stands for (a surface is in Surface Bodies, not here)."""
    try:
        from .viewtypes import objects_of
        found = objects_of("Bodies", doc)
    except Exception:
        found = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"] if doc is not None else []
    out = []
    for o in found:
        try:
            if o.TypeId == "PartDesign::Body" or o.Shape.Solids:
                out.append(o)
        except Exception:
            out.append(o)
    return out


def _show_bodies(bodies, on):
    for b in bodies:
        if b.ViewObject is not None:
            b.ViewObject.Visibility = bool(on)


def _select_all(objs):
    Gui.Selection.clearSelection()
    for o in objs:
        Gui.Selection.addSelection(o.Document.Name, o.Name)


def _edit_material(shell, doc):
    _select_all(material_targets(doc))
    _binding(shell, "EditMaterial") or Gui.runCommand("Std_SetMaterial", 0)


class FavoritesDialog(QtWidgets.QDialog):
    """Manage Favorites: which materials the Material row's menu lists, in order."""

    def __init__(self, parent=None):
        super().__init__(parent or _mw())
        self.setObjectName("SWMaterialFavorites")
        self.setWindowTitle("Manage Favorites")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Favorite materials:"))
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWFavoritesList")
        lay.addWidget(self.list, 1)
        for label, names in material_favorites():
            item = QtWidgets.QListWidgetItem(label)
            item.setData(Qt.UserRole, list(names))
            self.list.addItem(item)
        row = QtWidgets.QHBoxLayout()
        self.pick = QtWidgets.QComboBox()
        self.pick.setObjectName("SWFavoritesPick")
        self.pick.addItems(_all_materials())
        row.addWidget(self.pick, 1)
        add = QtWidgets.QPushButton("Add")
        add.setObjectName("SWFavoritesAdd")
        add.clicked.connect(self.add_current)
        row.addWidget(add)
        lay.addLayout(row)
        buttons = QtWidgets.QHBoxLayout()
        for name, text, fn in (("SWFavoritesRemove", "Remove", self.remove), ("SWFavoritesUp", "Move Up", self.up),
                               ("SWFavoritesDown", "Move Down", self.down),
                               ("SWFavoritesReset", "Defaults", self.defaults)):
            b = QtWidgets.QPushButton(text)
            b.setObjectName(name)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        lay.addLayout(buttons)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def add_current(self, name=None):
        name = name or self.pick.currentText()
        if not name or any(self.list.item(i).text() == name for i in range(self.list.count())):
            return
        item = QtWidgets.QListWidgetItem(name)
        item.setData(Qt.UserRole, [name])
        self.list.addItem(item)

    def remove(self):
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)

    def _move(self, step):
        row = self.list.currentRow()
        if 0 <= row + step < self.list.count() and row >= 0:
            item = self.list.takeItem(row)
            self.list.insertItem(row + step, item)
            self.list.setCurrentRow(row + step)

    def up(self):
        self._move(-1)

    def down(self):
        self._move(1)

    def defaults(self):
        self.list.clear()
        for label, names in MATERIALS:
            item = QtWidgets.QListWidgetItem(label)
            item.setData(Qt.UserRole, list(names))
            self.list.addItem(item)

    def items(self):
        return [(self.list.item(i).text(), tuple(self.list.item(i).data(Qt.UserRole)))
                for i in range(self.list.count())]

    def apply(self):
        set_material_favorites(self.items())


def manage_favorites(doc=None):
    ""
    try:
        from . import materialdlg
        box = materialdlg.edit(doc or App.ActiveDocument)
        if box is not None:
            for i in range(box.tabs.count()):
                if box.tabs.tabText(i) == "Favorites":
                    box.tabs.setCurrentIndex(i)
            return box
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Manage Favorites: %s\n" % error)
    return _run_dialog(FavoritesDialog(), lambda box: box.apply())


def _document_properties():
    try:
        from . import options
        options.show(tab=1)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Document Properties: %s\n" % error)


def _comment_menu(menu, shell, target, doc):
    def add_comment():
        if target is None:
            text, ok = QtWidgets.QInputDialog.getMultiLineText(_mw(), "Comment", "Comment on %s" % doc.Label,
                                                               doc.Comment)
            if ok:
                doc.Comment = text
            return
        _select(target)
        _binding(shell, "AddComment") or _fallback_comment(target)
    menu.addAction("Add Comment").triggered.connect(lambda: _later(add_comment))


def _fallback_comment(obj):
    from . import parttools
    text, ok = QtWidgets.QInputDialog.getMultiLineText(_mw(), "Comment", "Comment on %s" % obj.Label,
                                                       getattr(obj, "Comment", ""))
    if ok:
        parttools.set_comment(obj, text)


def _save_selection_menu(menu, doc, target=None):
    # New Selection Set saves the picks, or the right-clicked row; with neither it is left out instead of greyed
    # (NO DEAD CONTROLS; pkg216)
    if Gui.Selection.getSelectionEx(doc.Name, 0) or target is not None:
        menu.addAction("New Selection Set").triggered.connect(lambda: _later(lambda: new_selection_set(doc, target)))
    sets = selection_sets(doc)
    if sets:
        if menu.actions():
            menu.addSeparator()
        for s in sets:
            menu.addAction(s["name"]).triggered.connect(lambda checked=False, n=s["name"]: _later(lambda: select_set(doc, n)))


def _hidden_items_menu(menu):

    for name in HIDDEN_FOLDERS:
        state = _params().GetString("TreeItem." + name, dict(TREE_ITEMS).get(name, "Automatic"))
        if state == "Show":
            continue
        sub = menu.addMenu(name)
        a = sub.addAction("Show")
        a.triggered.connect(lambda checked=False, n=name: _show_tree_item(n))
    if [a for a in menu.actions() if a.menu() is not None]:
        menu.addSeparator()     # nothing hidden: only Hide/Show Tree Items (no greyed placeholder)
    menu.addAction("Hide/Show Tree Items...").triggered.connect(lambda: _later(tree_items))


def _toggle_tree_display(key, default):
    _params().SetBool(key, not _params().GetBool(key, default))
    if key in ("TreeFlat", "TreeConfigNames", "TreeDisplayStateNames"):
        from . import swkeys
        swkeys.rebuild_trees()



TREE_DISPLAY_ASM = (
    ("TreeConfigNames", "Show Component Configuration Names", True),
    ("TreeDisplayStateNames", "Show Display State Names", True),
)


def _tree_display_rows():
    rows = list(TREE_DISPLAY)
    try:
        from . import asmcore
        if App.ActiveDocument is not None and asmcore.is_assembly(App.ActiveDocument):
            rows += list(TREE_DISPLAY_ASM)
    except Exception as _fw_err:
        _fw_log("fmmenu.py:1692", _fw_err)
    return rows


def _tree_display_menu(menu):
    for key, label, default in _tree_display_rows():
        a = menu.addAction(label)
        a.setCheckable(True)
        a.setChecked(_params().GetBool(key, default))
        a.triggered.connect(lambda checked=False, k=key, d=default: _toggle_tree_display(k, d))


def _appearance_menu(menu, shell, doc):
    def run():
        bodies = material_targets(doc)
        Gui.Selection.clearSelection()
        for b in bodies:
            Gui.Selection.addSelection(doc.Name, b.Name)
        _binding(shell, "EditAppearance")
    menu.addAction("Appearance").triggered.connect(lambda: _later(run))


def _material_menu(menu, shell, doc):
    def edit():
        Gui.Selection.clearSelection()
        for b in material_targets(doc):
            Gui.Selection.addSelection(doc.Name, b.Name)
        _binding(shell, "EditMaterial")
    menu.addAction("Edit Material").triggered.connect(lambda: _later(edit))
    for label, names in material_favorites():
        m = _material(names)
        if not usable_favorite(label, names):
            continue
        a = menu.addAction(label)
        a.setToolTip("FreeCAD material: %s" % m.Name if m is not None else "%g kg/m^3" % favorite_density(label))
        a.triggered.connect(lambda checked=False, n=names, l=label: _later(lambda: set_material(doc, n, l)))
    menu.setToolTipsVisible(True)


class _Chevron(QtWidgets.QWidgetAction):
    def __init__(self, menu, on_click):
        super().__init__(menu)
        button = QtWidgets.QToolButton()
        button.setObjectName("SWMenuChevron")
        button.setText("⌄")
        button.setToolTip("Show the full menu")
        button.setAutoRaise(True)
        button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        button.clicked.connect(on_click)
        self.setDefaultWidget(button)
        self.button = button



# Hidden Tree Items > | Isolate | Comment > | Tree Display > | Speedpak Options > | Configuration Publisher... | ...
# | Set Resolved to Lightweight | ... | Document Properties... | --- | Create New Folder | Collapse Items | Rename tree
# item | Hide/Show Tree Items... FreeCAD's own items (Add to Library, Appearance, Expand Items, FreeCAD >) stay after

TOP_ASSEMBLY_ORDER = ("InvertSelection", "GoTo", None, "HiddenTreeItems", "Isolate", "Comment", "TreeDisplay", "SpeedPak",
                      "ConfigurationPublisher", "LightweightToResolved", "ResolvedToLightweight", "DocumentProperties",
                      "-", "NewFolder", "Collapse", "Rename", "TreeItems")


def _select_all(objs):
    Gui.Selection.clearSelection()
    for o in objs:
        try:
            Gui.Selection.addSelection(o.Document.Name, o.Name)
        except Exception as _fw_err:
            _fw_log("fmmenu.py:select all", _fw_err)


def top_assembly_order(items, target):
    ""
    try:
        from . import asmfolder, asmcore
        asm = asmcore.assembly_of(target.Document)
        if asm is not None and not any(i[0] == "NewFolder" for i in items):
            items = list(items) + [("NewFolder", "Create New Folder", lambda a=asm: asmfolder.create_new_folder(a), True)]
    except Exception as _fw_err:
        _fw_log("fmmenu.py:top assembly folder", _fw_err)
    try:
        from . import asmcore
        asm = asmcore.assembly_of(target.Document)
        comps = list(asmcore.components(asm)) if asm is not None else []
        if comps and not any(i[0] == "InvertSelection" for i in items):
            items = [("InvertSelection", "Invert Selection", lambda c=comps: _select_all(c), True)] + list(items)
    except Exception as _fw_err:
        _fw_log("fmmenu.py:top assembly invert", _fw_err)
    out, used = [], set()
    for key in TOP_ASSEMBLY_ORDER:
        for n, it in enumerate(items):
            if n in used or it[0] != key or key == "-":
                continue
            if key is None:
                it = (None, "Top Assembly (%s)" % target.Document.Label) + tuple(it[2:])
            out.append(it)
            used.add(n)
        if key == "-":
            out.append(("-", None, None, False))
    rest = [it for n, it in enumerate(items) if n not in used and it[0] != "-"]
    tail = [it for it in rest if it[0] == "Customize"]
    rest = [it for it in rest if it[0] != "Customize"]
    return out + ([("-", None, None, False)] + rest if rest else []) + tail


def _surface_type(target):
    """"folder" for the Surface Bodies folder object, "row" for one of its body rows (surfacebodies.py), else None."""
    try:
        from . import surfacebodies
        t = getattr(getattr(target, "Proxy", None), "Type", None)
        return {surfacebodies.FOLDER_TYPE: "folder", surfacebodies.ROW_TYPE: "row"}.get(t)
    except Exception:
        return None


def build(shell, target, view=None, full=False, parent=None):
    """The QMenu for a tree row (not shown yet)."""
    if _surface_type(target) == "folder":
        # the Surface Bodies folder is a document object: it got the part feature menu (Configure Feature,
        # Parent/Child..., FeatureWorks...); it has the folder's own menu, as Solid Bodies (pkg219)
        target = Folder("surfaces", target.Document, target.Label)
    kind = kind_of(target)
    if kind in WHOLE_MENU:
        full = True
    menu = QtWidgets.QMenu(parent or _mw())
    menu.setObjectName("SWFeatureMenu")
    menu.setProperty("swContextRow", True)      # contextbar adds no second toolbar row
    menu.setProperty("swKind", kind)
    menu.setProperty("swFull", full)
    hidden = hidden_entries(kind)
    items = entries(shell, target, view)
    top = getattr(target, "TypeId", "") == "Assembly::AssemblyObject"
    if top:
        items = top_assembly_order(items, target)
    if full:
        items = with_body(items, target)

    row_entries = []
    if shell is not None and kind == "cutbody":
        row_entries = _cut_body_bar(shell, target)
    elif shell is not None and kind not in ("part", "surfacerow") + FOLDER_KINDS:
        try:
            from . import contextbar
            row_entries = contextbar.part_entries(shell, target, "")
        except Exception:
            row_entries = []
        if kind in TREE_ROW:
            row_entries = _tree_row(shell, target, kind, row_entries)
    elif shell is not None and kind == "part":
        try:
            from . import contextbar
            row_entries = [e for e in (contextbar._command_entry(shell, k) for k in ("ZoomSelection", "EditAppearance"))
                           if e is not None]

            # Reference Visualization toggles, Top Level Transparency, Open Drawing
            try:
                copy = contextbar._command_entry(shell, "CopyAppearance")
                if copy is not None and getattr(copy, "enabled", True):
                    row_entries.append(copy)
            except Exception as _fw_err:
                _fw_log("fmmenu.py:part copy appearance", _fw_err)
            # drv-1120
            from . import icons
            for kind in ("Parent", "Child"):
                def _toggle(k=kind):
                    from . import uiextras
                    uiextras.set_reference_visualization(k, not uiextras.reference_visualization(k))
                from . import uiextras as _ui
                on = _ui.reference_visualization(kind)
                row_entries.append(contextbar.Entry(
                    "DynamicReference" + kind, "Dynamic Reference Visualization (%s)" % kind, icons.drawn("DynRef" + kind),
                    "Dynamic Reference Visualization (%s): %s. Click to turn it %s." % (kind, "On" if on else "Off", "off" if on else "on"),
                    _toggle))
            from . import rcextras
            part_doc = target if isinstance(target, App.Document) else getattr(target, "Document", None) or App.ActiveDocument
            if top_level_transparency_ready(part_doc):      # deadrc-1121: nothing to act on, no button
                row_entries.append(contextbar.Entry(
                    "TopLevelTransparency", "Top Level Transparency",
                    rcextras._icon("Top Level Transparency", "TOP_LEVEL_TRANSPARENCY", "FW_TopLevelTransparency", "FW_ChangeTransparency"),
                    rcextras._tip("Top Level Transparency", "Makes every body see-through, or solid again"),
                    lambda d=part_doc: top_level_transparency(d)))
            row_entries.append(contextbar.Entry(
                "OpenDrawing", "Open Drawing", rcextras._icon("Open Drawing", "FILE_OPEN_DRAWING", "OPEN_DRAWING", "FW_OpenDrawing"),
                rcextras._tip("Open Drawing", "Opens the drawing of the part"),
                lambda: Gui.runCommand("SWStyle_OpenDrawing", 0)))
        except Exception:
            row_entries = []
    if shell is not None and _solid_row(target):
        row_entries = _solid_row_bar(shell, target)
    try:
        from . import customizedlg
        if not customizedlg.option("ShowInShortcutMenu"):
            row_entries = []        # Customize > Toolbars: Show in shortcut menu off drops the row here too
    except Exception as _fw_err:
        _fw_log("fmmenu.py:1779", _fw_err)
    if row_entries:
        row = TreeRows(row_entries, kind)
        row.chosen.connect(lambda entry, m=menu: (m.close(), _later(entry.run)))
        action = QtWidgets.QWidgetAction(menu)
        action.setDefaultWidget(row)
        menu.addAction(action)
        menu.addSeparator()
        menu.row = row
    for key, label, run, enabled in items:
        if key == "-":
            menu.addSeparator()
            continue
        if key is None:
            a = menu.addAction(label)
            f = a.font()
            f.setBold(True)
            a.setFont(f)
            a.setProperty("swHeading", True)
            continue
        if key in hidden or (not full and key in FULL_ONLY and not (key == "InvertSelection" and top)):
            continue            # pkg262: the top assembly row has Invert Selection in its short form too (read 11-19)
        if not enabled and key != "Customize":
            continue            # does not apply to this row now: left out, not greyed (no dead entries)
        if key == "Customize":
            try:
                from . import customizedlg
                if not customizedlg.option("CustomizeMenuItems"):
                    continue        # Customize > Customization: Show Customize Menu in shortcut menus off
            except Exception as _fw_err:
                _fw_log("fmmenu.py:1808", _fw_err)
            a = menu.addAction(label)
            a.setProperty("swKey", key)
            choices = [(k, l) for k, l, r, e in items if k not in (None, "-", "Customize")]
            a.triggered.connect(lambda checked=False, c=choices: _later(
                lambda: _run_dialog(CustomizeDialog(kind, c), lambda box: box.apply())))
            continue
        if isinstance(run, Sub):
            sub = menu.addMenu(label)
            sub.setObjectName("SWFeatureMenu_" + key)
            sub.menuAction().setProperty("swKey", key)
            sub.aboutToShow.connect(lambda s=sub, r=run: (s.clear(), r.fill(s)))
            run.fill(sub)       # filled now too, so the entries are there before it opens
            if not enabled:
                menu.removeAction(sub.menuAction())
            continue
        if not enabled:
            continue        # nothing greyed: an entry that cannot work here is left out (pkg207)
        a = menu.addAction(label)
        a.setProperty("swKey", key)
        try:
            from . import rcextras
            pic = rcextras.item_icon(label)
            if pic is not None:
                a.setIcon(pic)
        except Exception as _fw_err:
            _fw_log("fmmenu.py:item-icon", _fw_err)
        if run is not None:
            a.triggered.connect(lambda checked=False, r=run: _later(r))
    if not full:
        menu.addAction(_Chevron(menu, lambda: _reopen(menu, shell, target, view)))
    return menu


class TreeRows(QtWidgets.QWidget):
    ""



    chosen = QtCore.Signal(object)

    def __init__(self, entries, kind, parent=None):
        super().__init__(parent)
        from . import contextbar
        self.setObjectName("SWContextMenuRows")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        lines = [list(entries)]
        if kind in TREE_ROW:
            cut = next((n for n, e in enumerate(entries) if e.key in VIEW_ROW_KEYS), None)
            if cut:
                lines = [list(entries[:cut]), list(entries[cut:])]
        self.rows = []
        for line in lines:
            row = contextbar.MenuRow(line, self)
            row.chosen.connect(self.chosen.emit)
            layout.addWidget(row)
            self.rows.append(row)
        self.buttons = [b for r in self.rows for b in r.buttons]

    def keys(self):
        return [b.entry.key for b in self.buttons]

    def button(self, key):
        for b in self.buttons:
            if b.entry.key == key:
                return b
        return None


# the buttons that start the second line of a tree row's icon box
VIEW_ROW_KEYS = ("HideSelection", "ShowSelection", "ZoomSelection", "NormalTo", "EditAppearance")


def _tree_row(shell, target, kind, row_entries):
    """The part context row with Suppress added, in the tree menu's order."""
    from . import contextbar
    if kind == "body":
        return _body_tree_row(shell, target, row_entries)
    if "Suppressed" in getattr(target, "PropertiesList", ()):
        on = bool(target.Suppressed)
        key = "Unsuppress" if on else "Suppress"
        try:
            icon = shell.binding(key).icon()
        except Exception:
            icon = QtGui.QIcon()
        row_entries = [e for e in row_entries if e.key not in ("Suppress", "Unsuppress")]
        row_entries.append(contextbar.Entry("Suppress", key, icon, key,
                                            lambda target=target, on=on: set_suppressed(target, not on)))
    if kind == "sketch" and not any(e.key == "Rollback" for e in row_entries):
        owner = sketch_owner(target)
        try:
            from . import rollbackbar
            if owner is not None and rollbackbar.can_roll_back(owner):
                row_entries.append(contextbar.Entry(
                    "Rollback", "Rollback", shell.binding("Rollback").icon(),
                    contextbar._tip("Rollback", "Roll back to before %s" % owner.Label),
                    lambda owner=owner: rollbackbar.roll_back_to(owner)))
        except Exception as _fw_err:
            _fw_log("fmmenu.py:1856", _fw_err)
    if kind == "feature" and not any(e.key == "NormalTo" for e in row_entries):

        try:
            from . import contextbar
            e = contextbar._command_entry(shell, "NormalTo")
            if e is not None:
                row_entries.append(e)
        except Exception as _fw_err:
            _fw_log("fmmenu.py:normal-to", _fw_err)
    if kind == "sketch" and getattr(target, "TypeId", "") == "Sketcher::SketchObject" \
            and not any(e.key == "EditSketchPlane" for e in row_entries):
        row_entries.append(edit_sketch_plane_entry(target))
    if kind == "feature":
        row_entries = _normal_to_live(target, row_entries)
    order = TREE_ROW[kind]
    same = {"ShowSelection": "HideSelection"}

    def place(entry):
        key = same.get(entry.key, entry.key)
        return order.index(key) if key in order else len(order)
    return sorted(row_entries, key=place)


def _normal_to_live(target, row_entries):
    """Normal To stays on a feature or body row only when it has a sketch plane to look at (keys.feature_sketch).
    Otherwise FreeCAD's Align to Selection does nothing with the whole feature picked (NO DEAD CONTROLS)."""
    try:
        from . import keys
        if keys.feature_sketch(target) is not None:
            return row_entries
    except Exception as _fw_err:
        _fw_log("fmmenu.py:normal-live", _fw_err)
        return row_entries
    return [e for e in row_entries if e.key != "NormalTo"]


def _body_tree_row(shell, body, row_entries):
    from . import contextbar
    keys = [e.key for e in row_entries]
    if "NormalTo" not in keys:
        e = contextbar._command_entry(shell, "NormalTo")
        if e is not None:
            row_entries.append(e)
    if "InsertIntoNewPart" not in keys:
        from . import featurerc
        icon = QtGui.QIcon()
        try:
            icon = shell.binding("InsertPart").icon()      # the same picture idea: a part from bodies
        except Exception as _fw_err:
            _fw_log("fmmenu.py:body-row", _fw_err)
        row_entries.append(contextbar.Entry("InsertIntoNewPart", featurerc.T_INSERT_NEW_PART, icon,
                                            contextbar._tip("Insert into New Part", "A new part from %s" % body.Label),
                                            lambda b=body: featurerc.insert_into_new_part(b)))
    row_entries = _normal_to_live(body, row_entries)
    order = TREE_ROW["body"]
    same = {"ShowSelection": "HideSelection"}
    return sorted(row_entries, key=lambda e: order.index(same.get(e.key, e.key)) if same.get(e.key, e.key) in order
                  else len(order))


def edit_sketch_plane_entry(sketch):
    ""
    from . import contextbar
    icon = QtGui.QIcon()
    try:

        from . import icons
        icon = icons.family("VIEW_SKETCH_PLANES")
    except Exception as _fw_err:
        _fw_log("fmmenu.py:esp-icon", _fw_err)
    try:
        from . import icons
        painted = icons.paints(icon)
    except Exception:
        painted = not icon.isNull()
    if not painted:
        try:
            import SketcherGui  # noqa: F401  (loads the Sketcher's commands and icons)
            act = Gui.Command.get("Sketcher_MapSketch").getAction()
            icon = act[0].icon() if act else icon
        except Exception as _fw_err:
            _fw_log("fmmenu.py:1878", _fw_err)
    return contextbar.Entry("EditSketchPlane", "Edit Sketch Plane", icon,
                            contextbar._tip("Edit Sketch Plane", "Changes the plane or face %s sits on" % sketch.Label),
                            lambda sketch=sketch: edit_sketch_plane(sketch))


def sketch_owner(sketch):
    """The solid feature that uses this sketch (the row it sits under in the tree), else None."""
    for obj in getattr(sketch, "InList", ()):
        prof = getattr(obj, "Profile", None)
        prof = prof[0] if isinstance(prof, tuple) else prof
        if prof is sketch and obj.isDerivedFrom("PartDesign::Feature"):
            return obj
    return None


def _reopen(menu, shell, target, view):
    pos = menu.pos()
    menu.close()

    def again():
        full = build(shell, target, view, full=True)
        LAST[0] = full
        full.popup(pos)
    _later(again)


LAST = [None]       # the menu shown last (tests)
WHOLE_MENU = ("annotations",)


def _solid_row(target):
    try:
        from . import multibody
        return getattr(getattr(target, "Proxy", None), "Type", None) == multibody.ROW_TYPE
    except Exception:
        return False


def _solid_row_bar(shell, row):
    ""


    from . import contextbar, multibody
    out = []
    try:
        shown = bool(row.ViewObject.Visibility)
    except Exception:
        return out
    b = shell.binding("HideSelection" if shown else "ShowSelection")
    out.append(contextbar.Entry("HideSelection", b.cmd.label, b.icon(), contextbar._tip(b.cmd.label, row.Label),
                                lambda r=row, on=not shown: setattr(r.ViewObject, "Visibility", on)))
    b = shell.binding("Isolate")
    if multibody._ISOLATED.get(row.Document.Name) is None:
        out.append(contextbar.Entry("Isolate", b.cmd.label, b.icon(), contextbar._tip(b.cmd.label, b.cmd.tip or ""),
                                    lambda r=row: multibody.isolate(r.Document, [r])))
    zoom = contextbar._command_entry(shell, "ZoomSelection")
    if zoom is not None:
        out.append(zoom)
    return out


def show(shell, target, global_pos, view=None):
    ""

    if QtWidgets.QApplication.keyboardModifiers() & Qt.ShiftModifier:
        return None
    target = cut_body_row(view, global_pos, target)
    if isinstance(target, CutBody) and not Gui.Selection.isSelected(target.obj):
        _select(target.obj)
    if target is not None and not isinstance(target, (App.Document, Folder)):
        if not Gui.Selection.isSelected(target):
            _select(target)
    menu = build(shell, target, view)
    LAST[0] = menu
    menu.popup(global_pos)
    return menu




def add_part_to_library(doc):
    """Part row > Add to Library: a copy of the part in the Design Library parts folder."""
    import os
    from . import designlib
    root = designlib.library_root()
    folder = os.path.join(root, "parts") if os.path.isdir(os.path.join(root, "parts")) else root
    path = designlib.add_to_library(doc, folder)
    if path:
        App.Console.PrintMessage("FreeCAD: added to the Design Library: %s\n" % path)
    return path


def configuration_publisher(doc):
    from . import configmanager
    return configmanager.configuration_publisher(doc)


def _solid_shapes(doc):
    out = []
    for o in (doc.Objects if doc else []):
        if o.TypeId == "PartDesign::Body" or (hasattr(o, "Shape") and o.TypeId.startswith("Part::") and not o.InList):
            try:
                if o.Shape.Solids:
                    out.append(o)
            except Exception as _fw_err:
                _fw_log("fmmenu.py:1949", _fw_err)
    return out


def convert_to_bodies(doc):
    """Part row > Convert to Bodies...: a new part holding each solid body as a plain body, no features."""
    objs = _solid_shapes(doc)
    if not objs:
        return None
    new = App.newDocument((doc.Label or "Part") + "_Bodies")
    for o in objs:
        for i, sol in enumerate(o.Shape.Solids):
            f = new.addObject("Part::Feature", "Body")
            f.Label = o.Label if len(o.Shape.Solids) == 1 else "%s[%d]" % (o.Label, i + 1)
            f.Shape = sol.copy()
    new.recompute()
    return new


def _is_fillet(obj):
    return getattr(obj, "TypeId", "") == "PartDesign::Fillet"


def _fillet_body(obj):
    try:
        for p in obj.InList:
            if p.TypeId == "PartDesign::Body":
                return p
    except Exception as _fw_err:
        _fw_log("fmmenu.py:1978", _fw_err)
    return None


def convert_fillet_to_chamfer(fillet):
    """Fillet row > Convert Fillet to Chamfer: the same edges, a chamfer of the fillet's radius, in its place."""
    body = _fillet_body(fillet)
    if body is None:
        return None
    doc = fillet.Document
    doc.openTransaction("Convert Fillet to Chamfer")
    try:
        was_tip = body.Tip == fillet
        ch = doc.addObject("PartDesign::Chamfer", "Chamfer")
        body.insertObject(ch, fillet, True)
        ch.Base = fillet.Base
        ch.Size = fillet.Radius
        name = fillet.Name
        body.removeObject(fillet)
        doc.removeObject(name)
        if was_tip or body.Tip is None:
            body.Tip = ch
        doc.recompute()
    finally:
        doc.commitTransaction()
    return ch


def make_reference_sketch(sketch):
    """Sketch row > Make Reference Sketch: every entity becomes construction geometry (a reference
    the features no longer use as a profile); a second time puts them back."""
    n = len(getattr(sketch, "Geometry", []))
    if not n:
        return
    doc = sketch.Document
    on = not all(sketch.getConstruction(i) for i in range(n))
    doc.openTransaction("Make Reference Sketch")
    try:
        for i in range(n):
            if bool(sketch.getConstruction(i)) != on:
                sketch.toggleConstruction(i)
        doc.recompute()
    finally:
        doc.commitTransaction()


def _configure_feature(obj):
    from . import featurerc
    return featurerc._configure(obj)


def _featureworks_menu(menu):
    for cmd, text in (("SWStyle_RecognizeFeatures", "Recognize Features..."),
                      ("SWStyle_FeatureWorksOptions", "Options...")):
        a = menu.addAction(text)
        a.triggered.connect(lambda checked=False, c=cmd: Gui.runCommand(c, 0))
