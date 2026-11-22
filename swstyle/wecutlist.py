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

import ast
import csv
import math
import operator
import os
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import wetrim

COMMAND = "SWStyle_WECutList"
FOLDER = "Cut list"
ITEM = "Cut-List-Item"
GROUP = "Cut List"
COLUMNS = ("Cut List Item", "QUANTITY", "DESCRIPTION", "LENGTH", "ANGLE1", "ANGLE2", "MATERIAL", "MASS",
           "TOTAL LENGTH")

ITEM_PROPS = (("MATERIAL", "Material"), ("QUANTITY", "Quantity"), ("DESCRIPTION", "Description"),
              ("LENGTH", "Length"), ("ANGLE1", "Angle1"), ("ANGLE2", "Angle2"), ("MASS", "Mass"),
              ("TOTAL LENGTH", "TotalLength"))
DENSITY = 1e-6


def _weicon(name):
    from . import weprofile
    return weprofile.icon(name)

# extapps132: the profile's "Steel" is no name in FreeCAD's material library (it has MildSteel, Steel-S275N...), so the mass
# of every steel member fell back to 1000 kg/m^3, 7.8 times too light; it weighs as Plain Carbon Steel (7800 kg/m^3).
PROFILE_ALIASES = {"Steel": "Plain Carbon Steel"}


def _density_named(name):
    ""
    if not name or name.lower() in ("default", "material <not specified>"):
        return None
    try:
        from . import material, wemember
        name = PROFILE_ALIASES.get(name, name)
        value = material.known_density(name) or material.known_density(name.replace("-Generic", ""))
        if not value:
            lib = wemember._library(name)
            value = material.library_density(lib) if lib is not None else None
        return value * 1e-9 if value else None          # kg/m^3 -> kg/mm^3
    except Exception as _fw_err:
        _fw_log("wecutlist.py:68", _fw_err)
        return None


def mass_of(obj, material_name=None):
    """The mass of one body (kg): its volume times its material's density (the body's own material,
    else the cut list item's MATERIAL: a member gets its material from the profile, not on the body)."""
    density = None
    mat = getattr(obj, "ShapeMaterial", None)
    try:
        if mat is not None and getattr(mat, "Name", "").lower() != "default":
            density = float(App.Units.Quantity(mat.getPhysicalValue("Density")).getValueAs("kg/mm^3")) or None
    except Exception as _fw_err:
        _fw_log("wecutlist.py:79", _fw_err)
    density = density or _density_named(material_name) or DENSITY
    try:
        return obj.Shape.Solids[0].Volume * density if obj.Shape.Solids else 0.0
    except Exception:
        return 0.0


def _kind(obj):
    return type(getattr(obj, "Proxy", None)).__name__


def folder(doc, create=False):
    found = next((o for o in doc.Objects if _kind(o) == "CutListFolder"), None)
    if found is None and create:
        found = doc.addObject("App::FeaturePython", "CutList")
        CutListFolder(found)
        if App.GuiUp:
            ViewProviderCutListFolder(found.ViewObject)
        found.Label = "%s(0)" % FOLDER
    return found


# ---------------------------------------------------------------- what goes in it
def _fingerprint(shape):
    """Volume, area and face count, rounded: equal for identical bodies, wherever they are."""
    try:
        return (round(shape.Volume, 1), round(shape.Area, 1), len(shape.Faces))
    except Exception:
        return ()


def member_data(body):
    """(key, properties) for a structural member body (a merged mitered chain: its members' lengths added)."""
    if getattr(body, "Merged", False):
        parts = [member_data(p)[1] for p in body.Parts]
        sm = _member_feature(body)
        kind = getattr(sm, "Type", "") if sm is not None else ""
        size = getattr(sm, "Size", "") if sm is not None else ""
        length = round(sum(p["Length"] for p in parts), 2)
        key = ("merged", kind, size, length, len(parts), _fingerprint(body.Shape))
        return key, {"Description": ("%s %s" % (kind, size)).strip().upper(), "Length": length, "Angle1": 0.0,
                     "Angle2": 0.0, "Material": _material(sm, body)}
    base = wetrim.base_of(body)
    p0, p1 = wetrim.line_of(base)
    u = (p1 - p0).normalize()
    shape = body.Shape
    proj = [v.Point.dot(u) for v in shape.Vertexes]
    length = max(proj) - min(proj)
    angles = []
    for far in (min, max):
        ends = [f for f in shape.Faces if f.Surface.TypeId == "Part::GeomPlane" and abs(f.normalAt(0, 0).dot(u)) > 0.3]
        if not ends:
            angles.append(0.0)
            continue
        f = far(ends, key=lambda f: f.CenterOfMass.dot(u))
        c = min(1.0, abs(f.normalAt(0, 0).dot(u)))
        angles.append(round(math.degrees(math.acos(c)), 2))
    sm = _member_feature(body)
    kind = getattr(sm, "Type", "") if sm is not None else ""
    size = getattr(sm, "Size", "") if sm is not None else ""
    description = ("%s %s" % (kind, size)).strip().upper()
    from . import wemember
    material = wemember.material_of(sm, base)

    key = ("member", kind, size, round(length, 2), tuple(sorted(angles)), _fingerprint(shape))
    return key, {"Description": description, "Length": round(length, 2), "Angle1": angles[0],
                 "Angle2": angles[1], "Material": material}


def _material(sm, body):
    from . import wemember
    return wemember.material_of(sm, wetrim.base_of(body))


def _member_feature(body):
    ref = wetrim.ref_of(body)
    if ref is None:
        return None
    return body.Document.getObject(ref.rpartition(":")[0])


def plate_data(obj, solid, what):
    b = solid.BoundBox
    dims = tuple(sorted(round(x, 2) for x in (b.XLength, b.YLength, b.ZLength)))
    key = (what, round(solid.Volume, 2), dims)
    return key, {"Description": "%s %s" % (what.upper(), " X ".join("%g" % d for d in reversed(dims))),
                 "Length": 0.0, "Angle1": 0.0, "Angle2": 0.0, "Material": ""}


PLATES = {"EndCap": "End cap", "Gusset": "Gusset", "ConnectionElement": "Connection element",
          "ConnectionPattern": "Connection element"}


def entries(doc):
    """[(key, properties, object)] for every body of the weldment, in tree order."""
    from . import wemember
    out = []
    for sm in wemember.structural_members(doc):
        for k in range(len(sm.Bodies)):
            tip = wetrim.current_tip(doc, "%s:%d" % (sm.Name, k))
            if tip is None or tip.Shape.isNull():
                continue
            try:
                key, props = member_data(tip)
            except Exception as _fw_err:
                _fw_log("wecutlist.py:187", _fw_err)
                continue
            out.append((key, props, tip))

    for o in doc.Objects:
        src = getattr(o, "WeldMirrorSource", None) or getattr(o, "WeldPatternSource", None)
        if src is None or o.Shape.isNull():
            continue
        seen = {o.Name}
        while src is not None and src.Name not in seen and \
                (getattr(src, "WeldMirrorSource", None) or getattr(src, "WeldPatternSource", None)):
            seen.add(src.Name)          # a pattern of a mirror (or a mirror of a pattern): back to the member
            src = getattr(src, "WeldMirrorSource", None) or getattr(src, "WeldPatternSource", None)
        what = PLATES.get(_kind(src))
        try:
            if what is not None:            # a mirrored / patterned end cap, gusset or connection element
                for solid in o.Shape.Solids:
                    key, props = plate_data(o, solid, what)
                    props["Material"] = next((p["Material"] for _k, p, _o in out if p["Material"]), "")
                    out.append((key, props, o))
                continue
            key, props = member_data(src)
        except Exception as _fw_err:
            _fw_log("wecutlist.py:210", _fw_err)
            continue
        out.append((key, props, o))
    for o in doc.Objects:
        what = {"EndCap": "End cap", "Gusset": "Gusset", "ConnectionElement": "Connection element",
                "ConnectionPattern": "Connection element"}.get(_kind(o))
        if what is None or o.Shape.isNull():
            continue
        for solid in o.Shape.Solids:
            key, props = plate_data(o, solid, what)
            # plates are cut from the members' stock material
            props["Material"] = next((p["Material"] for _k, p, _o in out if p["Material"]), "")
            out.append((key, props, o))
    return out


# ---------------------------------------------------------------- the folder and its items
class CutListFolder:
    def __init__(self, obj):
        obj.addProperty("App::PropertyLinkList", "Items", GROUP, "Cut list items")
        obj.addProperty("App::PropertyBool", "UpdateAutomatically", GROUP, "Update the cut list after changes")
        obj.UpdateAutomatically = True
        obj.setEditorMode("Items", 2)
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class CutListItem:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyLinkList", "Bodies", GROUP, "Bodies in this item")
        add("App::PropertyInteger", "Quantity", GROUP, "QUANTITY")
        add("App::PropertyString", "Description", GROUP, "DESCRIPTION")
        add("App::PropertyFloat", "Length", GROUP, "LENGTH (mm)")
        add("App::PropertyFloat", "Angle1", GROUP, "ANGLE1 (deg)")
        add("App::PropertyFloat", "Angle2", GROUP, "ANGLE2 (deg)")
        add("App::PropertyString", "Material", GROUP, "MATERIAL")
        _more(obj)
        obj.setEditorMode("Bodies", 2)
        for name in ("Quantity", "Length", "Angle1", "Angle2"):
            obj.setEditorMode(name, 1)
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _more(obj):
    """MASS and TOTAL LENGTH (also on an item from an older file)."""
    if "Mass" not in obj.PropertiesList:
        obj.addProperty("App::PropertyFloat", "Mass", GROUP, "MASS (kg)")
        obj.addProperty("App::PropertyFloat", "TotalLength", GROUP, "TOTAL LENGTH (mm): LENGTH x QUANTITY")
        obj.setEditorMode("Mass", 1)
        obj.setEditorMode("TotalLength", 1)


class _FolderView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        from . import wemember
        wemember._empty_mode(vobj)

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return ":/icons/folder.svg"

    def setupContextMenu(self, vobj, menu):
        doc = vobj.Object.Document
        a = menu.addAction("Update")
        a.triggered.connect(lambda: update(doc, force=True))
        context_menu(vobj.Object, menu)
        b = menu.addAction("Cut List Properties...")
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


class ViewProviderCutListFolder(_FolderView):
    def claimChildren(self):
        if not hasattr(self, "Object"):     # asked before attach() on a reopened file (pkg123)
            return []
        if getattr(self.Object, "CollapseItems", False):
            out = []
            for item in self.Object.Items:
                out += [b for b in _tree_bodies(item) if b not in out]
            return out
        return list(self.Object.Items)


def _tree_bodies(item):
    ""

    from . import weendcap, wegusset
    return [b for b in item.Bodies if not (weendcap.is_end_cap(b) or wegusset.is_gusset(b))]


class ViewProviderCutListItem(_FolderView):
    def claimChildren(self):
        if not hasattr(self, "Object"):     # asked before attach() on a reopened file (pkg123)
            return []
        return _tree_bodies(self.Object)

    def onDelete(self, vobj, subelements):
        return False


def update(doc, force=False):
    """Groups the weldment's bodies into cut list items."""
    box = folder(doc)
    if box is None or (not box.UpdateAutomatically and not force):
        return box
    groups = []                 # [(key, props, [objects], count)]
    _ensure_box(box)
    collect = bool(box.CollectIdentical)
    for key, props, obj in entries(doc):
        if not collect:                     # Sorting Options: every body its own item
            key = (key, obj.Name, len(groups))
        g = next((g for g in groups if g[0] == key), None)
        if g is None:
            groups.append((key, props, [obj], [1]))
        else:
            if obj not in g[2]:
                g[2].append(obj)
            g[3][0] += 1
    groups = sort_groups(groups, box.SortBy)
    items = list(box.Items)
    while len(items) < len(groups):
        item = doc.addObject("App::FeaturePython", "CutListItem")
        CutListItem(item)
        if App.GuiUp:
            ViewProviderCutListItem(item.ViewObject)
        items.append(item)
    for extra in items[len(groups):]:
        try:
            doc.removeObject(extra.Name)
        except Exception as _fw_err:
            _fw_log("wecutlist.py:375", _fw_err)
    items = items[:len(groups)]
    for item in items:
        item.Label = "_" + item.Name          # free the labels before numbering
    excluded = list(getattr(box, "ExcludedKeys", []) or [])
    from . import weldprops
    for n, (item, (key, props, objs, count)) in enumerate(zip(items, groups), 1):
        _ensure_item(item)
        props = weldprops.item_props(doc, props)        # Document Properties > Weldments
        item.Key = repr(key)
        item.Excluded = item.Key in excluded
        item.Bodies = objs
        item.Quantity = count[0]
        item.Description = props["Description"]
        item.Length = props["Length"]
        item.Angle1 = props["Angle1"]
        item.Angle2 = props["Angle2"]
        item.Material = props["Material"]
        _more(item)
        _apply_overrides(item)              # a Description typed in Cut List Properties
        item.Mass = round(mass_of(objs[0], item.Material), 4) if objs else 0.0
        item.TotalLength = round(props["Length"] * count[0], 2)
        item.Label = weldprops.item_label(doc, "%s%d(%d)" % (ITEM, n, count[0]), props, count[0]) + \
            (" (Excluded)" if item.Excluded else "")
        item.purgeTouched()
    box.Items = items
    box.Label = "%s(%d)" % (FOLDER, sum(g[3][0] for g in groups))
    box.purgeTouched()
    return box


def summary(doc):
    """The Cut List Summary rows."""
    box = folder(doc)
    rows = []
    for item in (box.Items if box is not None else []):
        if getattr(item, "Excluded", False):
            continue
        rows.append((item.Label.split("(")[0], item.Quantity, item.Description,
                     "%g" % item.Length if item.Length else "", "%g" % item.Angle1 if item.Length else "",
                     "%g" % item.Angle2 if item.Length else "", item.Material,
                     "%g" % getattr(item, "Mass", 0.0), "%g" % getattr(item, "TotalLength", 0.0) if item.Length else ""))
    return rows


def export_csv(doc, path):
    with open(path, "w", newline="") as fd:
        w = csv.writer(fd)
        w.writerow(COLUMNS)
        for row in summary(doc):
            w.writerow(row)


# ---------------------------------------------------------------- Cut List Properties
TYPES = ("Text", "Date", "Number", "Yes or no", "Equation")
NEW_ROW = "<Type a new property>"
LINKED = ("DESCRIPTION", "LENGTH", "ANGLE1", "ANGLE2", "QUANTITY", "MATERIAL", "MASS", "TOTAL LENGTH")


def _store(box):
    if "ItemProps" not in box.PropertiesList:
        box.addProperty("App::PropertyString", "ItemProps", GROUP, "Cut list items' own properties (JSON)")
        box.setEditorMode("ItemProps", 2)
    try:
        import json
        return json.loads(box.ItemProps or "{}")
    except Exception:
        return {}


def item_properties(item):
    ""


    box = folder(item.Document)
    own = _store(box).get(item.Key, []) if box is not None else []
    own_names = {r[0].upper() for r in own}
    part = os.path.basename(item.Document.FileName or item.Document.Label)
    linked = [(n, "Number" if n not in ("DESCRIPTION", "MATERIAL") else "Text",
               '"%s@@@%s@%s"' % (n, item.Label.split("(")[0], part)) for n in LINKED if n not in own_names]
    return linked + [tuple(r) for r in own]


def _value_of(item, name, depth):
    """A property's evaluated value by name: a linked one (LENGTH...) or one of the item's own rows."""
    name = name.upper()
    for n, kind, v in item_properties(item):
        if n.upper() == name and depth < 8:
            return evaluated(item, v, kind, depth + 1)
    prop = dict(ITEM_PROPS).get(name)
    v = getattr(item, prop, "") if prop else ""
    return "%g" % v if isinstance(v, float) else str(v)


_REF = re.compile(r'"([^"]+)"')
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"sin": lambda x: math.sin(math.radians(x)), "cos": lambda x: math.cos(math.radians(x)),
          "tan": lambda x: math.tan(math.radians(x)), "sqr": math.sqrt, "sqrt": math.sqrt, "abs": abs,
          "int": int, "round": round, "min": min, "max": max, "pi": math.pi}


def _calc(node):
    if isinstance(node, ast.Expression):
        return _calc(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_calc(node.left), _calc(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_calc(node.operand))
    if isinstance(node, ast.Name) and node.id.lower() == "pi":
        return math.pi
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.lower() in _FUNCS \
            and not node.keywords:
        return _FUNCS[node.func.id.lower()](*[_calc(a) for a in node.args])
    raise ValueError("not a number")


def equation(item, text, depth=0):
    ""


    body = text.strip()
    if body.startswith("="):
        body = body[1:]

    def ref(m):
        name = m.group(1).split("@@@")[0]
        v = _value_of(item, name, depth)
        try:
            return repr(float(v))
        except ValueError:
            raise ValueError(name)
    try:
        expr = _REF.sub(ref, body).replace("^", "**")
        value = _calc(ast.parse(expr, mode="eval"))
    except Exception:
        return None
    return float(value)


def evaluated(item, expression, kind=None, depth=0):
    """The Evaluated Value of a Value / Text Expression: a link "NAME@@@item@part" reads the item's value;
    an Equation (or a value starting with =) is worked out."""
    text = str(expression or "")
    if kind == "Equation" or text.lstrip().startswith("="):
        v = equation(item, text, depth)
        return "%g" % v if v is not None else "#Error"
    bare = text.strip('"')
    if "@@@" in bare:
        name = bare.split("@@@")[0].upper()
        prop = dict(ITEM_PROPS).get(name)
        v = getattr(item, prop, "") if prop else ""
        return "%g" % v if isinstance(v, float) else str(v)
    return bare


def set_item_properties(item, rows):
    """Keeps an item's own rows [(name, type, value)]; a linked name given a plain value overrides it
    (DESCRIPTION is written on the item)."""
    import json
    box = folder(item.Document)
    data = _store(box)
    own = [[str(n), t if t in TYPES else "Text", str(v)] for n, t, v in rows
           if n and not (n.upper() in LINKED and "@@@" in str(v))]
    if own:
        data[item.Key] = own
    else:
        data.pop(item.Key, None)
    box.ItemProps = json.dumps(data)
    _apply_overrides(item)


def _apply_overrides(item):
    box = folder(item.Document)
    for name, _t, value in (_store(box).get(item.Key, []) if box is not None else []):
        if name.upper() == "DESCRIPTION":
            item.Description = value


# tests put answers here: callables(name, items) -> QMessageBox.Yes / No / Cancel (None = ask)
ASK_OVERWRITE = []


class PropertiesDialog(QtWidgets.QDialog):
    ""


    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self._filling = False
        self.setObjectName("SWWECutListDialog")
        self.setWindowTitle("Cut-List Properties")
        self.resize(820, 420)
        lay = QtWidgets.QVBoxLayout(self)
        self.tabs = tabs = QtWidgets.QTabWidget()
        tabs.setObjectName("SWWECutListTabs")
        lay.addWidget(tabs)
        # Cut List Summary: the items on the left, the picked item's properties on the right
        page = QtWidgets.QWidget()
        tabs.addTab(page, "Cut List Summary")
        pl = QtWidgets.QHBoxLayout(page)
        self.item_list = QtWidgets.QListWidget()
        self.item_list.setObjectName("SWWECutListItems")
        self.item_list.setMaximumWidth(220)
        pl.addWidget(self.item_list)
        self.props = QtWidgets.QTableWidget(0, 4)
        self.props.setObjectName("SWWECutListProps")
        self.props.setHorizontalHeaderLabels(["Property Name", "Type", "Value / Text Expression", "Evaluated Value"])
        self.props.horizontalHeader().setStretchLastSection(True)
        fm = self.props.horizontalHeader().fontMetrics()       # look-audit smwe-1120: headings whole
        for col, text in enumerate(["Property Name", "Type", "Value / Text Expression"]):
            self.props.setColumnWidth(col, max(self.props.columnWidth(col), fm.horizontalAdvance(text) + 2 * fm.height()))
        pl.addWidget(self.props, 1)
        self.item_list.currentRowChanged.connect(self._fill_props)
        self.props.itemChanged.connect(self._edited)

        self.props.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.props.customContextMenuRequested.connect(self._props_menu)
        # Properties Summary: a property's value in every item
        summ = QtWidgets.QWidget()
        tabs.addTab(summ, "Properties Summary")
        sl = QtWidgets.QHBoxLayout(summ)
        self.prop_names = QtWidgets.QListWidget()
        self.prop_names.setObjectName("SWWECutListPropNames")
        self.prop_names.setMaximumWidth(220)
        sl.addWidget(self.prop_names)
        self.across = QtWidgets.QTableWidget(0, 3)
        self.across.setObjectName("SWWECutListAcross")
        self.across.setHorizontalHeaderLabels(["Cut List Item", "Value / Text Expression", "Evaluated Value"])
        self.across.horizontalHeader().setStretchLastSection(True)
        sl.addWidget(self.across, 1)
        self.prop_names.currentRowChanged.connect(self._fill_across)
        self.across.itemChanged.connect(self._across_edited)
        # Cut List Table: the rows a cut list table shows
        tpage = QtWidgets.QWidget()
        tabs.addTab(tpage, "Cut List Table")
        tl = QtWidgets.QVBoxLayout(tpage)
        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("SWWECutListTable")
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        tl.addWidget(self.table)
        buttons = QtWidgets.QHBoxLayout()
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.setObjectName("SWWECutListDelete")
        self.update_button = QtWidgets.QPushButton("Update")
        self.update_button.setObjectName("SWWECutListUpdate")
        self.export_button = QtWidgets.QPushButton("Export...")
        self.export_button.setObjectName("SWWECutListExport")
        ok = QtWidgets.QPushButton("OK")
        ok.setObjectName("SWWECutListOK")
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.setObjectName("SWWECutListCancel")
        for b in (self.delete_button, self.update_button, self.export_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        lay.addLayout(buttons)
        self.delete_button.clicked.connect(self._delete)
        self.update_button.clicked.connect(self._update)
        self.export_button.clicked.connect(self._export)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        self._edits = {}            # item key -> rows, written on OK
        self.fill()

    # ---------------------------------------------------------------- filling
    def _items(self):
        box = folder(self.doc)
        return list(box.Items) if box is not None else []

    def _rows(self, item):
        return self._edits.get(item.Key, None) or item_properties(item)

    def fill(self):
        rows = summary(self.doc)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        self.item_list.clear()
        for item in self._items():
            self.item_list.addItem(item.Label)
        if self.item_list.count():
            self.item_list.setCurrentRow(0)
        self._fill_names()

    def _fill_props(self, row):
        items = self._items()
        item = items[row] if 0 <= row < len(items) else None
        self._filling = True
        rows = self._rows(item) if item is not None else []
        self.props.setRowCount(len(rows) + (1 if item is not None else 0))
        for r, (name, kind, value) in enumerate(rows):
            self._set_row(r, item, name, kind, value)
        if item is not None:
            r = len(rows)
            new = QtWidgets.QTableWidgetItem(NEW_ROW)
            new.setForeground(self.palette().mid())
            self.props.setItem(r, 0, new)
            for c in (1, 2, 3):
                self.props.setItem(r, c, QtWidgets.QTableWidgetItem(""))
        self.props.resizeColumnToContents(0)
        self._filling = False

    def _set_row(self, r, item, name, kind, value):
        self.props.setItem(r, 0, QtWidgets.QTableWidgetItem(name))
        combo = QtWidgets.QComboBox()
        combo.addItems(list(TYPES))
        combo.setCurrentText(kind)
        combo.currentTextChanged.connect(lambda _t: self._edited(None))
        self.props.setCellWidget(r, 1, combo)
        self.props.setItem(r, 2, QtWidgets.QTableWidgetItem(value))
        ev = QtWidgets.QTableWidgetItem(evaluated(item, value, kind))
        ev.setFlags(ev.flags() & ~QtCore.Qt.ItemIsEditable)
        self.props.setItem(r, 3, ev)

    def _table_rows(self):
        out = []
        for r in range(self.props.rowCount()):
            name = self.props.item(r, 0).text().strip() if self.props.item(r, 0) else ""
            if not name or name == NEW_ROW:
                continue
            combo = self.props.cellWidget(r, 1)
            value = self.props.item(r, 2).text() if self.props.item(r, 2) else ""
            out.append((name, combo.currentText() if combo else "Text", value))
        return out

    def _edited(self, cell):
        if self._filling:
            return
        items = self._items()
        row = self.item_list.currentRow()
        if not 0 <= row < len(items):
            return
        item = items[row]
        self._edits[item.Key] = self._table_rows()
        self._fill_props(row)
        self._fill_names()

    def _delete(self):
        items = self._items()
        row = self.item_list.currentRow()
        r = self.props.currentRow()
        if not 0 <= row < len(items) or r < 0:
            return
        rows = self._table_rows()
        name = self.props.item(r, 0).text() if self.props.item(r, 0) else ""
        rows = [x for x in rows if x[0] != name]
        self._edits[items[row].Key] = rows
        self._fill_props(row)
        self._fill_names()

    def _props_menu(self, pos):
        r = self.props.rowAt(pos.y())
        name = self.props.item(r, 0).text().strip() if r >= 0 and self.props.item(r, 0) else ""
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWWECutListPropMenu")
        act = menu.addAction("Copy to All Cut List Items")
        act.setObjectName("SWWECutListCopyToAll")
        act.setEnabled(bool(name) and name != NEW_ROW and len(self._items()) > 1)
        act.triggered.connect(lambda: self.copy_to_all(r))
        self._menu = menu
        menu.popup(self.props.viewport().mapToGlobal(pos))
        return menu

    def copy_to_all(self, r):
        """Copy the property on row r of the picked item to every other cut list item; an item that
        has a property of that name already is overwritten only when the answer is Yes."""
        items = self._items()
        row = self.item_list.currentRow()
        if not 0 <= row < len(items):
            return 0
        rows = self._table_rows()
        name = self.props.item(r, 0).text().strip() if 0 <= r < self.props.rowCount() and self.props.item(r, 0) else ""
        src = next((x for x in rows if x[0] == name), None)
        if src is None:
            return 0
        others = [i for k, i in enumerate(items) if k != row]
        clash = [i for i in others if any(n == name and v != src[2] for n, _k, v in self._rows(i))]
        overwrite = True
        if clash:
            answer = None
            for fn in ASK_OVERWRITE:
                answer = fn(name, clash)
            if answer is None:
                answer = QtWidgets.QMessageBox.question(
                    self, "Copy to All Cut List Items",
                    "%d cut list item%s already ha%s a property named '%s'.\nOverwrite %s value%s?"
                    % (len(clash), "" if len(clash) == 1 else "s", "s" if len(clash) == 1 else "ve", name,
                       "its" if len(clash) == 1 else "their", "" if len(clash) == 1 else "s"),
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel,
                    QtWidgets.QMessageBox.Yes)
            if answer == QtWidgets.QMessageBox.Cancel:
                return 0
            overwrite = answer == QtWidgets.QMessageBox.Yes
        self._edits[items[row].Key] = rows
        done = 0
        for item in others:
            cur = list(self._rows(item))
            k = next((i for i, x in enumerate(cur) if x[0] == name), None)
            if k is None:
                cur.append(src)
            elif overwrite:
                cur[k] = src
            else:
                continue
            self._edits[item.Key] = cur
            done += 1
        self._fill_props(row)
        self._fill_names()
        return done

    def _fill_names(self):
        names = []
        for item in self._items():
            for name, _k, _v in self._rows(item):
                if name not in names:
                    names.append(name)
        keep = self.prop_names.currentItem().text() if self.prop_names.currentItem() else None
        self.prop_names.blockSignals(True)
        self.prop_names.clear()
        self.prop_names.addItems(names)
        self.prop_names.blockSignals(False)
        self.prop_names.setCurrentRow(names.index(keep) if keep in names else (0 if names else -1))
        self._fill_across(self.prop_names.currentRow())

    def _fill_across(self, row):
        name = self.prop_names.item(row).text() if 0 <= row < self.prop_names.count() else None
        items = self._items()
        was, self._filling = self._filling, True
        self.across.setRowCount(len(items) if name else 0)
        for r, item in enumerate(items if name else []):
            value, kind = next(((v, k) for n, k, v in self._rows(item) if n == name), ("", None))
            label = QtWidgets.QTableWidgetItem(item.Label)
            label.setFlags(label.flags() & ~QtCore.Qt.ItemIsEditable)
            self.across.setItem(r, 0, label)
            self.across.setItem(r, 1, QtWidgets.QTableWidgetItem(value))
            ev = QtWidgets.QTableWidgetItem(evaluated(item, value, kind))
            ev.setFlags(ev.flags() & ~QtCore.Qt.ItemIsEditable)
            self.across.setItem(r, 2, ev)
        self._filling = was

    def _across_edited(self, cell):
        """Properties Summary: a value typed for one item sets (or adds) that property on the item."""
        if self._filling or cell is None or cell.column() != 1:
            return
        name = self.prop_names.currentItem().text() if self.prop_names.currentItem() else None
        items = self._items()
        r = cell.row()
        if not name or not 0 <= r < len(items):
            return
        item = items[r]
        rows = list(self._rows(item))
        k = next((i for i, x in enumerate(rows) if x[0] == name), None)
        if k is None:
            rows.append((name, "Text", cell.text()))
        else:
            rows[k] = (name, rows[k][1], cell.text())
        self._edits[item.Key] = rows
        self._fill_props(self.item_list.currentRow())
        self._fill_across(self.prop_names.currentRow())

    # ---------------------------------------------------------------- buttons
    def apply(self):
        by_key = {i.Key: i for i in self._items()}
        if self._edits:
            self.doc.openTransaction("Cut List Properties")
            try:
                for key, rows in self._edits.items():
                    if key in by_key:
                        set_item_properties(by_key[key], rows)
            except BaseException:
                try:
                    self.doc.abortTransaction()
                except Exception:
                    pass
                raise
            self.doc.commitTransaction()
        self._edits = {}

    def accept(self):
        self.apply()
        super().accept()

    def _update(self):
        self.apply()
        update(self.doc, force=True)
        self.fill()

    def _export(self):
        path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Export Cut List", "cut list.csv", "CSV (*.csv)")
        if path:
            export_csv(self.doc, path)


_dialogs = []


def show_properties(doc):
    update(doc, force=True)
    dlg = PropertiesDialog(doc)
    _dialogs[:] = [dlg]
    dlg.show()
    return dlg


class Command:
    def GetResources(self):
        try:
            pixmap = _weicon("bom.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Weldment Cut List",
                "ToolTip": "Lists the members with their lengths."}

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and folder(doc) is not None

    def Activated(self):
        show_properties(App.ActiveDocument)


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())



def _ensure_box(box):
    if not hasattr(box, "CollapseItems"):
        box.addProperty("App::PropertyBool", "CollapseItems", GROUP, "Show the bodies directly under the cut list")
    if not hasattr(box, "ExcludedKeys"):
        box.addProperty("App::PropertyStringList", "ExcludedKeys", GROUP, "Cut list items excluded from the cut list")
    if not hasattr(box, "CollectIdentical"):
        box.addProperty("App::PropertyBool", "CollectIdentical", GROUP, "Sorting Options: identical bodies in one item")
        box.CollectIdentical = True
        box.setEditorMode("CollectIdentical", 2)
    if not hasattr(box, "SortBy"):
        box.addProperty("App::PropertyString", "SortBy", GROUP, "Sorting Options: the order of the items")
        box.SortBy = SORT_BY[0]
        box.setEditorMode("SortBy", 2)


SORT_BY = ("Order in the tree", "Description", "Length", "Quantity")


def sort_groups(groups, by):
    """Sorting Options: the cut list items in tree order, or by Description (then length), Length
    (longest first) or Quantity (most first)."""
    if by == "Description":
        return sorted(groups, key=lambda g: (str(g[1].get("Description", "")), -float(g[1].get("Length", 0) or 0)))
    if by == "Length":
        return sorted(groups, key=lambda g: -float(g[1].get("Length", 0) or 0))
    if by == "Quantity":
        return sorted(groups, key=lambda g: -g[3][0])
    return groups


def set_sorting(box, collect=None, by=None):
    _ensure_box(box)
    if collect is not None:
        box.CollectIdentical = bool(collect)
    if by is not None and by in SORT_BY:
        box.SortBy = by
    update(box.Document, force=True)


sorting_hook = None     # checks: callable(box) -> (collect, sort by) or None instead of the dialog


def show_sorting(box):
    ""
    _ensure_box(box)
    if sorting_hook is not None:
        got = sorting_hook(box)
        if got:
            set_sorting(box, *got)
        return
    dlg = QtWidgets.QDialog(Gui.getMainWindow())
    dlg.setObjectName("SWCutListSorting")
    dlg.setWindowTitle("Cut List Sorting Options")
    lay = QtWidgets.QVBoxLayout(dlg)
    collect = QtWidgets.QCheckBox("Collect identical bodies")
    collect.setObjectName("SWCutListCollect")
    collect.setChecked(bool(box.CollectIdentical))
    lay.addWidget(collect)
    row = QtWidgets.QHBoxLayout()
    row.addWidget(QtWidgets.QLabel("Sort cut list items by:"))
    by = QtWidgets.QComboBox()
    by.setObjectName("SWCutListSortBy")
    by.addItems(list(SORT_BY))
    by.setCurrentText(box.SortBy or SORT_BY[0])
    row.addWidget(by)
    lay.addLayout(row)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    if dlg.exec():
        set_sorting(box, collect.isChecked(), by.currentText())


def _ensure_item(item):
    if not hasattr(item, "Excluded"):
        item.addProperty("App::PropertyBool", "Excluded", GROUP, "Exclude from cut list")
        item.setEditorMode("Excluded", 1)
    if not hasattr(item, "Key"):
        item.addProperty("App::PropertyString", "Key", GROUP, "Grouping key")
        item.setEditorMode("Key", 2)


def set_update_automatically(box, on):
    box.UpdateAutomatically = bool(on)
    if on:
        update(box.Document, force=True)


def set_collapse(box, on):
    _ensure_box(box)
    box.CollapseItems = bool(on)
    box.touch()
    box.purgeTouched()


def set_excluded(item, on):
    box = folder(item.Document)
    _ensure_box(box)
    _ensure_item(item)
    keys = [k for k in box.ExcludedKeys if k != item.Key]
    if on:
        keys.append(item.Key)
    box.ExcludedKeys = keys
    update(item.Document, force=True)


def create_subweldment(items):
    """Create Sub-weldment: a Sub-weldment folder holding the items' bodies."""
    doc = items[0].Document
    n = 1
    while doc.getObjectsByLabel("Sub-weldment%d" % n):
        n += 1
    sub = doc.addObject("App::DocumentObjectGroup", "SubWeldment")
    sub.Label = "Sub-weldment%d" % n
    bodies = []
    for it in items:
        bodies += [b for b in it.Bodies if b not in bodies]
    sub.addProperty("App::PropertyLinkListHidden", "Bodies", GROUP, "Bodies of the sub-weldment")
    sub.Bodies = bodies
    box = folder(doc)
    if box is not None:
        sub.addProperty("App::PropertyLinkHidden", "CutList", GROUP, "Parent cut list")
        sub.CutList = box
    return sub


def insert_into_new_part(items):
    """Insert into New Part: a new document with a copy of the items' bodies, linked by name."""
    src = items[0].Document
    new = App.newDocument("Part")
    for it in items:
        for b in it.Bodies:
            f = new.addObject("Part::Feature", b.Name)
            f.Shape = b.Shape.copy()
            f.Label = b.Label
            f.addProperty("App::PropertyString", "SourceBody", GROUP, "Body in the parent weldment")
            f.SourceBody = "%s#%s" % (src.Name, b.Name)
    new.recompute()
    return new


def save_item_bodies(items, path=None, ext=".FCStd"):
    from . import parttools
    bodies = []
    for it in items:
        bodies += [b for b in it.Bodies if b not in bodies]
    if path is None:
        path = QtWidgets.QFileDialog.getExistingDirectory(Gui.getMainWindow(), "Save Bodies")
        if not path:
            return []
    return parttools.save_bodies(bodies, path, ext)


def _selected_items(obj):
    try:
        sel = [o for o in Gui.Selection.getSelection() if o.Name.startswith("CutListItem")]
    except Exception:
        sel = []
    return sel if obj in sel else [obj]


def context_menu(obj, menu):
    ""
    box = folder(obj.Document)
    if box is None:
        return
    _ensure_box(box)
    if obj is box:
        u = menu.addAction("Update Automatically")
        u.setCheckable(True)
        u.setChecked(bool(box.UpdateAutomatically))
        u.toggled.connect(lambda on: set_update_automatically(box, on))
        o = menu.addAction("Sorting Options...")
        o.triggered.connect(lambda: show_sorting(box))
        c = menu.addAction("Collapse items")
        c.setCheckable(True)
        c.setChecked(bool(box.CollapseItems))
        c.toggled.connect(lambda on: set_collapse(box, on))
        s = menu.addAction("Save Bodies...")
        s.triggered.connect(lambda: save_item_bodies(list(box.Items)))
        return
    _ensure_item(obj)
    e = menu.addAction("Exclude from cut list")
    e.setCheckable(True)
    e.setChecked(bool(obj.Excluded))
    e.toggled.connect(lambda on: set_excluded(obj, on))
    w = menu.addAction("Create Sub-weldment")
    w.triggered.connect(lambda: create_subweldment(_selected_items(obj)))
    i = menu.addAction("Insert into New Part...")
    i.triggered.connect(lambda: insert_into_new_part(_selected_items(obj)))
    s = menu.addAction("Save Bodies...")
    s.triggered.connect(lambda: save_item_bodies(_selected_items(obj)))
